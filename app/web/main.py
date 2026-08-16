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


def _validar_formulario(
    nombre: str,
    criterio_tipo: str,
    criterio_valor: str,
    consulta: str | None,
    top_k: int,
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
        raise HTTPException(status_code=400, detail=f"top_k debe estar entre 1 y {TOP_K_MAX}.")


def _proyecto_desde_resultado(
    nombre: str,
    criterio_tipo: str,
    criterio_valor: str,
    consulta: str | None,
    top_k: int,
    resultado: dict[str, Any],
) -> Proyecto:
    """Proyecto nuevo: estado e informe segun el resultado de la evaluacion."""
    ahora = ahora_iso()
    es_error = "error" in resultado
    return Proyecto(
        id=uuid.uuid4().hex,
        nombre=nombre.strip(),
        criterio_tipo=criterio_tipo,
        criterio_valor=criterio_valor.strip(),
        consulta=consulta.strip() if consulta else None,
        top_k=top_k,
        estado="fallido" if es_error else "completado",
        informe=None if es_error else resultado,
        error=resultado["error"] if es_error else None,
        creado_en=ahora,
        actualizado_en=ahora,
    )


def _actualizar_proyecto(proyecto: Proyecto, resultado: dict[str, Any]) -> Proyecto:
    """Copia del proyecto con el resultado de la re-evaluacion (mismo id)."""
    es_error = "error" in resultado
    return proyecto.model_copy(
        update={
            "estado": "fallido" if es_error else "completado",
            "informe": None if es_error else resultado,
            "error": resultado["error"] if es_error else None,
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
    ):
        _validar_formulario(nombre, criterio_tipo, criterio_valor, consulta, top_k)
        kwargs = _kwargs_evaluacion(criterio_tipo, criterio_valor, consulta, top_k)
        resultado = await request.app.state.servidor_lotes.get_feasibility_report(**kwargs)
        proyecto = _proyecto_desde_resultado(
            nombre, criterio_tipo, criterio_valor, consulta, top_k, resultado
        )
        request.app.state.repositorio.crear(proyecto)
        return RedirectResponse(url=f"/proyectos/{proyecto.id}", status_code=303)

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
                content={"error": proyecto.error},
            )
        return JSONResponse(content=proyecto.informe)


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
    """
    plantillas = Jinja2Templates(directory=str(RUTA_TEMPLATES))

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
