"""Capa web de prefactibilidad (Feature 5): FastAPI + Jinja2 + HTMX.

Reutiliza la logica de dominio de `ServidorLotes` (app/main.py) SIN protocolo
MCP. La app web construye SU PROPIO `ServidorLotes` en el lifespan (ciclo de
vida independiente del singleton de app.main) y lo cierra al terminar
(aclose de los 4 providers). No se usan los singletons `servidor_lotes`/`mcp`
de app.main: se importa solo la clase y las clases de providers.

Rutas (US1 + US2):
- GET  /                          -> index.html: lista los proyectos
- POST /proyectos                 -> crea y evalua un proyecto (form) -> 303 a /proyectos/{id}
- GET  /proyectos/{id}            -> proyecto.html: detalle del proyecto
- POST /proyectos/{id}/reevaluar  -> re-evalua el proyecto -> 303 a /proyectos/{id}
- GET  /proyectos/{id}/json       -> JSON del informe (o error mapeado a HTTP)

Mapeo de errores (Fase 5): el codigo canonico de la taxonomia (app/errores.py)
se traduce a status HTTP (400/404/502/503, catch-all 500). Los errores de
evaluacion (LOTE_NO_ENCONTRADO, FUENTE_5XX, ...) NO se lanzan como excepciones
HTTP: el proyecto se persiste con estado "fallido" y el error; la pagina de
detalle y el endpoint /json lo exponen con el status mapeado. Las validaciones
de formulario SI fallan rapido con HTTPException(400) (FR-012).
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.main import ServidorLotes
from app.providers.arcgis import ArcGISProvider
from app.providers.mapas_bogota import MapasBogotaProvider
from app.providers.normativa import CONSULTA_MAX_CHARS, NormativaProvider, TOP_K_MAX
from app.providers.upl import UPLProvider
from app.web.db import Proyecto, ProyectoRepositorio, ahora_iso

# Rutas de plantillas y estaticos dentro del paquete (empaquetadas via
# package-data en pyproject.toml).
RUTA_PAQUETE = Path(__file__).resolve().parent
RUTA_TEMPLATES = RUTA_PAQUETE / "templates"
RUTA_STATIC = RUTA_PAQUETE / "static"

CRITERIOS_VALIDOS = {"chip", "direccion", "coordenadas"}

# Mapeo de codigos canonicos (app/errores.py) a status HTTP (Fase 5). El 5xx
# de una fuente NUNCA se degrada a "no encontrado" (FR-009): es un 502 fatal.
_ERROR_A_HTTP: dict[str, int] = {
    "PARAMETROS_INVALIDOS": 400,
    "LOTE_NO_ENCONTRADO": 404,
    "DIRECCION_NO_LOCALIZADA": 404,
    "FUERA_DE_COBERTURA": 404,
    "DATO_NO_ENCONTRADO_POR_FUENTE": 404,
    "LOTE_SIN_UPL": 404,
    "CREDENCIAL_FALTANTE": 503,
    "CORPUS_NO_INGESTADO": 503,
    "OLLAMA_NO_DISPONIBLE": 503,
    "FUENTE_5XX": 502,
}


def _error_a_http(codigo: str | None) -> int:
    """Status HTTP del codigo canonico de error (catch-all 500)."""
    return _ERROR_A_HTTP.get(codigo or "", 500)


def _construir_servidor_lotes() -> ServidorLotes:
    """ServidorLotes con los 4 providers reales (misma fabrica que app.main).

    Los providers se construyen sin red (httpx.AsyncClient perezoso); solo
    arrancan al consultar. En pruebas se inyecta un servidor con providers
    simulados via `crear_app_web(servidor_lotes=...)`.
    """
    api_key = os.environ.get("MAPAS_BOGOTA_APIKEY")
    return ServidorLotes(
        MapasBogotaProvider(api_key=api_key),
        ArcGISProvider(),
        UPLProvider(),
        NormativaProvider(),
    )


def _coordenadas_desde_texto(texto: str) -> dict[str, float]:
    """Parsea "lat,lon" del formulario a {"lat": x, "lon": y}; 400 si invalido."""
    partes = [parte.strip() for parte in texto.split(",")]
    if len(partes) != 2:
        raise HTTPException(
            status_code=400,
            detail="Coordenadas inválidas: use el formato 'latitud,longitud'.",
        )
    try:
        lat, lon = float(partes[0]), float(partes[1])
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Coordenadas inválidas: latitud y longitud deben ser numéricas.",
        )
    return {"lat": lat, "lon": lon}


def _kwargs_evaluacion(
    criterio_tipo: str,
    criterio_valor: str,
    consulta: str | None,
    top_k: int,
) -> dict[str, Any]:
    """Construye los kwargs de get_feasibility_report desde el formulario."""
    if criterio_tipo == "chip":
        kwargs: dict[str, Any] = {"chip": criterio_valor.strip()}
    elif criterio_tipo == "direccion":
        kwargs = {"direccion": criterio_valor.strip()}
    else:
        kwargs = {"coordenadas": _coordenadas_desde_texto(criterio_valor)}
    if consulta and consulta.strip():
        kwargs["consulta"] = consulta.strip()
    kwargs["top_k"] = top_k
    return kwargs


USOS_VALIDOS = {"residencial", "comercial", "mixto", "dotacional", "industrial"}
PRESUPUESTO_VALIDOS = {"menos_1000M", "1000_5000M", "5000_10000M", "mas_10000M"}
AVERSION_VALIDOS = {"baja", "media", "alta"}


def _validar_formulario(
    nombre: str,
    criterio_tipo: str,
    criterio_valor: str,
    consulta: str | None,
    top_k: int,
    uso_previsto: str | None = None,
    escala_m2: str | None = None,
    presupuesto_rango: str | None = None,
    horizonte_meses: str | None = None,
    aversion_riesgo: str | None = None,
) -> None:
    """Fail-fast (FR-012): cualquier campo invalido es HTTPException(400)."""
    if not nombre or not nombre.strip():
        raise HTTPException(status_code=400, detail="El nombre del proyecto es obligatorio.")
    if criterio_tipo not in CRITERIOS_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail="El criterio debe ser 'chip', 'direccion' o 'coordenadas'.",
        )
    if not criterio_valor or not criterio_valor.strip():
        raise HTTPException(status_code=400, detail="El valor del criterio es obligatorio.")
    if consulta and len(consulta.strip()) > CONSULTA_MAX_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"La consulta no puede superar {CONSULTA_MAX_CHARS} caracteres.",
        )
    if not 1 <= top_k <= TOP_K_MAX:
        raise HTTPException(
            status_code=400, detail=f"top_k debe estar entre 1 y {TOP_K_MAX}."
        )
    if uso_previsto and uso_previsto.strip() and uso_previsto.strip() not in USOS_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=f"uso_previsto debe ser uno de {sorted(USOS_VALIDOS)}.",
        )
    if escala_m2 and escala_m2.strip():
        try:
            v = float(escala_m2.strip())
            if v <= 0 or v < 36:
                raise HTTPException(status_code=400, detail="escala_m2 debe ser >= 36.")
        except ValueError:
            raise HTTPException(status_code=400, detail="escala_m2 debe ser numérico.")
    pr = presupuesto_rango.strip() if presupuesto_rango else ""
    if pr and pr not in PRESUPUESTO_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=f"presupuesto_rango debe ser uno de {sorted(PRESUPUESTO_VALIDOS)}.",
        )
    if horizonte_meses and horizonte_meses.strip():
        try:
            v = int(horizonte_meses.strip())
            if not 6 <= v <= 120:
                raise HTTPException(
                    status_code=400,
                    detail="horizonte_meses debe estar entre 6 y 120.",
                )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="horizonte_meses debe ser entero.",
            )
    av = aversion_riesgo.strip() if aversion_riesgo else ""
    if av and av not in AVERSION_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=f"aversion_riesgo debe ser uno de {sorted(AVERSION_VALIDOS)}.",
        )


def _inferir_cabida_desde_informe(resultado: dict[str, Any]) -> tuple[float | None, list[dict[str, Any]] | None]:
    """Inferencia de m² construibles desde el informe: prioriza cabida normativa.

    Extrae `technical_feasibility.dato.cabida_arquitectonica` (area_neta*COS,
    donde area_neta ya descuenta reserva vial 15% y COS viene de
    urbanistic_parameters.edificabilidad). Guarda las referencias que delimitaron
    la cabida: technical_feasibility + planning_constraints (reserva vial) +
    urbanistic_parameters (COS/altura/retiros). Retorna (None, None) si el informe
    es error o sin dato.
    """
    if "error" in resultado:
        return None, None
    tec = resultado.get("technical_feasibility") or {}
    dato = tec.get("dato") if isinstance(tec, dict) else None
    cabida = None
    if isinstance(dato, dict):
        cabida = dato.get("cabida_arquitectonica")
        try:
            cabida = float(cabida) if cabida is not None else None
        except (TypeError, ValueError):
            cabida = None
    if cabida is None:
        return None, None
    refs: list[dict[str, Any]] = []
    for clave in ("technical_feasibility", "planning_constraints", "urbanistic_parameters"):
        bloque = resultado.get(clave)
        if isinstance(bloque, dict) and isinstance(bloque.get("source_trace"), dict):
            refs.append(
                {
                    "bloque": clave,
                    "interpretation": bloque.get("interpretation"),
                    "source_trace": bloque.get("source_trace"),
                }
            )
        # Añadir reserva vial específica si afecta
        if clave == "planning_constraints" and isinstance(bloque, dict):
            dato_pc = bloque.get("dato")
            if isinstance(dato_pc, dict) and dato_pc.get("afecta_lote") is True:
                refs[-1]["reserva_vial_afecta"] = True
    return cabida, refs if refs else None


def _proyecto_desde_resultado(
    nombre: str,
    criterio_tipo: str,
    criterio_valor: str,
    consulta: str | None,
    top_k: int,
    resultado: dict[str, Any],
    uso_previsto: str | None = None,
    escala_m2: str | None = None,
    presupuesto_rango: str | None = None,
    horizonte_meses: str | None = None,
    aversion_riesgo: str | None = None,
) -> Proyecto:
    """Proyecto nuevo: estado e informe segun el resultado de la evaluacion.

    Si `escala_m2` es None/vacío, infiere m² construibles desde
    technical_feasibility.cabida_arquitectonica y guarda referencias.
    """
    ahora = ahora_iso()
    es_error = "error" in resultado

    def _norm(v: str | None) -> str | None:
        return v.strip() if v and v.strip() else None

    escala_val = None
    if escala_m2 and escala_m2.strip():
        try:
            escala_val = float(escala_m2.strip())
        except ValueError:
            escala_val = None
    horizonte_val = None
    if horizonte_meses and horizonte_meses.strip():
        try:
            horizonte_val = int(horizonte_meses.strip())
        except ValueError:
            horizonte_val = None
    escala_inferida, refs_cabida = _inferir_cabida_desde_informe(resultado)
    return Proyecto(
        id=uuid.uuid4().hex,
        nombre=nombre.strip(),
        criterio_tipo=criterio_tipo,
        criterio_valor=criterio_valor.strip(),
        consulta=consulta.strip() if consulta else None,
        top_k=top_k,
        uso_previsto=_norm(uso_previsto),
        escala_m2=escala_val,
        presupuesto_rango=_norm(presupuesto_rango),
        horizonte_meses=horizonte_val,
        aversion_riesgo=_norm(aversion_riesgo),
        escala_inferida_m2=escala_inferida,
        referencias_cabida=refs_cabida,
        estado="fallido" if es_error else "completado",
        informe=None if es_error else resultado,
        error=resultado["error"] if es_error else None,
        creado_en=ahora,
        actualizado_en=ahora,
    )


def _actualizar_proyecto(proyecto: Proyecto, resultado: dict[str, Any]) -> Proyecto:
    """Copia del proyecto con el resultado de la re-evaluacion (mismo id).

    Recalcula escala_inferida_m2/referencias_cabida desde el nuevo informe.
    """
    es_error = "error" in resultado
    escala_inferida, refs_cabida = _inferir_cabida_desde_informe(resultado)
    return proyecto.model_copy(
        update={
            "estado": "fallido" if es_error else "completado",
            "informe": None if es_error else resultado,
            "error": resultado["error"] if es_error else None,
            "escala_inferida_m2": escala_inferida,
            "referencias_cabida": refs_cabida,
            "actualizado_en": ahora_iso(),
        }
    )


def _es_peticion_json(request: Request) -> bool:
    return request.url.path.endswith("/json")


def _registrar_rutas(app: FastAPI) -> None:
    @app.get("/")
    async def listar_proyectos(request: Request):
        proyectos = request.app.state.repositorio.listar()
        return request.app.state.plantillas.TemplateResponse(
            request, "index.html", {"proyectos": proyectos}
        )

    @app.post("/proyectos")
    async def crear_proyecto(
        request: Request,
        nombre: str = Form(""),
        criterio_tipo: str = Form(""),
        criterio_valor: str = Form(""),
        consulta: str | None = Form(None),
        top_k: int = Form(3),
        uso_previsto: str | None = Form(None),
        escala_m2: str | None = Form(None),
        presupuesto_rango: str | None = Form(None),
        horizonte_meses: str | None = Form(None),
        aversion_riesgo: str | None = Form(None),
    ):
        _validar_formulario(
            nombre, criterio_tipo, criterio_valor, consulta, top_k,
            uso_previsto, escala_m2, presupuesto_rango, horizonte_meses, aversion_riesgo,
        )
        kwargs = _kwargs_evaluacion(criterio_tipo, criterio_valor, consulta, top_k)
        resultado = await request.app.state.servidor_lotes.get_feasibility_report(**kwargs)
        proyecto = _proyecto_desde_resultado(
            nombre, criterio_tipo, criterio_valor, consulta, top_k, resultado,
            uso_previsto, escala_m2, presupuesto_rango, horizonte_meses, aversion_riesgo,
        )
        request.app.state.repositorio.crear(proyecto)
        return RedirectResponse(url=f"/proyectos/{proyecto.id}", status_code=303)

    @app.post("/proyectos/preview")
    async def preview_lote(
        request: Request,
        criterio_tipo: str = Form(""),
        criterio_valor: str = Form(""),
    ):
        """Preview ligero del lote para el wizard paso 1: identidad + geometría + UPL.

        Usa los resolvers de F1 (chip/dirección/coordenadas) sin orquestar el informe
        completo de 23 bloques. Extrae el lote y consulta la UPL por el centroide;
        la ausencia de UPL se reporta sin fallar (BLOQUE_SIN_DATO). Falla rápido
        400 si el criterio es inválido; 404/502 si el lote no existe o la fuente
        falla. Respuesta JSON estática para HTMX/Leaflet sin depender de Ollama.
        """
        if criterio_tipo not in CRITERIOS_VALIDOS:
            raise HTTPException(
                status_code=400,
                detail="El criterio debe ser 'chip', 'direccion' o 'coordenadas'.",
            )
        if not criterio_valor or not criterio_valor.strip():
            raise HTTPException(status_code=400, detail="El valor del criterio es obligatorio.")
        lote = None
        error = None
        servidor: ServidorLotes = request.app.state.servidor_lotes
        if criterio_tipo == "chip":
            from app.utilidades import PATRON_CHIP

            if not PATRON_CHIP.match(criterio_valor.strip().upper()):
                raise HTTPException(status_code=400, detail="CHIP inválido: debe tener 11 caracteres alfanuméricos.")
            lote, error = await servidor._resolver_lote_por_chip(criterio_valor.strip().upper())
        elif criterio_tipo == "direccion":
            valor = criterio_valor.strip()
            if len(valor) > 500:
                raise HTTPException(status_code=400, detail="Dirección demasiado larga.")
            lote, error = await servidor._resolver_por_direccion(valor)
        else:
            coords = _coordenadas_desde_texto(criterio_valor)
            lote, error = await servidor._resolver_lote_por_punto(coords["lon"], coords["lat"])
            if error is None and lote is None:
                return JSONResponse(
                    status_code=404,
                    content={"error": {"code": "FUERA_DE_COBERTURA", "message": "Punto fuera de cobertura."}},
                )
        if error:
            codigo = (error.get("error") or {}).get("code") or "ERROR"
            return JSONResponse(status_code=_error_a_http(codigo), content=error)
        if lote is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "LOTE_NO_ENCONTRADO", "message": "Lote no encontrado."}},
            )
        upl_payload = None
        try:
            upl = await servidor._upl.consultar_upl_por_punto(lote.centroid.lng, lote.centroid.lat)
            upl_payload = {"codigo": upl.codigo_upl, "nombre": upl.nombre, "localidad": upl.localidad_derivada}
        except Exception:
            upl_payload = None
        return JSONResponse(
            content={
                "lote": {
                    "chip": lote.chip,
                    "direccion_normalizada": lote.direccion_normalizada,
                    "barrio": lote.barrio,
                    "centroid": {"lat": lote.centroid.lat, "lng": lote.centroid.lng},
                    "geometry": lote.geometry,
                },
                "upl": upl_payload,
            }
        )

    @app.get("/proyectos/{proyecto_id}")
    async def ver_proyecto(request: Request, proyecto_id: str):
        proyecto = request.app.state.repositorio.obtener(proyecto_id)
        if proyecto is None:
            raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        return request.app.state.plantillas.TemplateResponse(
            request, "proyecto.html", {"proyecto": proyecto}
        )

    @app.post("/proyectos/{proyecto_id}/reevaluar")
    async def reevaluar_proyecto(request: Request, proyecto_id: str):
        repositorio = request.app.state.repositorio
        proyecto = repositorio.obtener(proyecto_id)
        if proyecto is None:
            raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        kwargs = _kwargs_evaluacion(
            proyecto.criterio_tipo, proyecto.criterio_valor, proyecto.consulta, proyecto.top_k
        )
        resultado = await request.app.state.servidor_lotes.get_feasibility_report(**kwargs)
        repositorio.actualizar(_actualizar_proyecto(proyecto, resultado))
        return RedirectResponse(url=f"/proyectos/{proyecto_id}", status_code=303)

    @app.get("/proyectos/{proyecto_id}/json")
    async def proyecto_json(request: Request, proyecto_id: str):
        proyecto = request.app.state.repositorio.obtener(proyecto_id)
        if proyecto is None:
            raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        if proyecto.estado == "fallido":
            codigo = (proyecto.error or {}).get("code")
            return JSONResponse(
                status_code=_error_a_http(codigo),
                content={"error": proyecto.error, "wizard": _wizard_de_proyecto(proyecto)},
            )
        # F11 T012: el exportado incluye los 5 campos del wizard como metadata
        # aditiva bajo la clave "wizard" (los bloques del informe no cambian).
        return JSONResponse(
            content={**(proyecto.informe or {}), "wizard": _wizard_de_proyecto(proyecto)}
        )


CAMPOS_WIZARD: tuple[str, ...] = (
    "uso_previsto",
    "escala_m2",
    "presupuesto_rango",
    "horizonte_meses",
    "aversion_riesgo",
)


def _wizard_de_proyecto(proyecto: Proyecto) -> dict[str, Any]:
    """Los 5 campos del wizard v2 como metadata aditiva del JSON exportado (F11 T012)."""
    return {campo: getattr(proyecto, campo) for campo in CAMPOS_WIZARD}


def _registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def _manejar_http_exception(request: Request, exc: HTTPException):
        if _es_peticion_json(request):
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"code": f"HTTP_{exc.status_code}", "message": str(exc.detail)}},
            )
        return request.app.state.plantillas.TemplateResponse(
            request,
            "error.html",
            {"status_code": exc.status_code, "mensaje": str(exc.detail)},
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def _manejar_error_inesperado(request: Request, exc: Exception):
        # Fail loud (FR-009): un error interno nunca se degrada ni se enmascara.
        if _es_peticion_json(request):
            return JSONResponse(
                status_code=500,
                content={"error": {"code": "ERROR_INTERNO", "message": "Error interno del servidor."}},
            )
        return request.app.state.plantillas.TemplateResponse(
            request,
            "error.html",
            {"status_code": 500, "mensaje": "Error interno del servidor."},
            status_code=500,
        )


def crear_app_web(
    servidor_lotes: ServidorLotes | None = None,
    repositorio: ProyectoRepositorio | None = None,
) -> FastAPI:
    """Construye la app FastAPI de prefactibilidad (factory para uvicorn).

    - Lifespan propio: crea un `ServidorLotes` y lo cierra al terminar.
    - `servidor_lotes` y `repositorio` opcionales: inyeccion de dependencias
      para las pruebas (providers simulados + base temporal). Por defecto usa
      los providers reales y `PROYECTOS_DB_PATH` (o .data/proyectos.db).
    - Rutas US1/US2 registradas y manejadores de error (HTML vs /json).
    - (F12/US3, documentado SIN activar) el endpoint MCP puede coexistir en
      este proceso montando la app de `app.servidor_http.construir_app_http`:
      el lifespan del session manager debe PROPAGARSE explicitamente al
      FastAPI padre (los lifespans de sub-apps montadas no se ejecutan solos):

        app_mcp = construir_app_http(crear_servidor_mcp(servidor), config_http)
        lifespan_hijo = app_mcp.router.lifespan_context
        # en _lifespan: `async with lifespan_hijo(app_mcp):` rodeando el yield
        app.mount("/", app_mcp)  # endpoint externo resultante: POST /mcp

      Patron verificado en tests/contract/test_transporte_http.py
      ::test_mount_asgi_fastapi_con_lifespan_propagado. Queda a decision del
      operador activarlo (tambien vale contenedor separado MCP + web).
    """
    plantillas = Jinja2Templates(directory=str(RUTA_TEMPLATES))
    # Filtro para volcar JSON legible en <pre> (tojson escapa <>&' y queda feo).
    plantillas.env.filters["json_pretty"] = lambda v: json.dumps(
        v, ensure_ascii=False, indent=2
    )

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        app.state.servidor_lotes = (
            servidor_lotes if servidor_lotes is not None else _construir_servidor_lotes()
        )
        app.state.repositorio = (
            repositorio
            if repositorio is not None
            else ProyectoRepositorio(os.environ.get("PROYECTOS_DB_PATH", ".data/proyectos.db"))
        )
        app.state.plantillas = plantillas
        try:
            yield
        finally:
            await app.state.servidor_lotes.aclose()

    app = FastAPI(title="mcp-bogota-factibilidad web", lifespan=_lifespan)
    app.mount("/static", StaticFiles(directory=str(RUTA_STATIC)), name="static")
    _registrar_rutas(app)
    _registrar_manejadores(app)
    return app


def main() -> None:
    """Punto de entrada: uvicorn con la factory `crear_app_web`.

    Host/puerto configurables via entorno (WEB_HOST/WEB_PORT), con los
    valores por defecto del quickstart (127.0.0.1:8000).
    """
    import uvicorn

    host = os.environ.get("WEB_HOST", "127.0.0.1")
    puerto = int(os.environ.get("WEB_PORT", "8000"))
    uvicorn.run("app.web.main:crear_app_web", host=host, port=puerto, factory=True)


if __name__ == "__main__":
    main()
