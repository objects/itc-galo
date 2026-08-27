"""Servidor MCP mcp-bogota-factibilidad: registra 7 tools (4 F1 + 2 F2 + 1 F3).

Transporte por stdio (constitucion, Restricciones tecnicas; research.md D8). Los
providers son la frontera de parsing (Principio II); las tools aplican las
validaciones FR-012 en su limite (fail-fast) y toda salida lleva la trazabilidad
de 5 campos por dato (Principio III, FR-006).

Taxonomia de errores (Principio IV): un 5xx de la fuente es FUENTE_5XX (nunca
"no encontrado"); un 4xx de la fuente es PARAMETROS_INVALIDOS con mensaje que
identifica la fuente; la falta de MAPAS_BOGOTA_APIKEY en geocodificacion es
CREDENCIAL_FALTANTE sin llamar a las fuentes (FR-010). Toda clasificacion ocurre
en _error_de_fuente (decision A2, puntos 4 y 9).

Jerarquia de fuentes del Lote (decision A1 punto 1, opcion b): la fuente primaria
de identidad y geometria es la capa ArcGIS layer 38 (Mapa_Referencia) y su
source_trace documenta esa capa. direccion_normalizada y barrio, cuando la capa
no los trae, se enriquecen desde Mapas Bogota (direccion_chip / geocodificar) o
desde el geocodificador en el flujo por direccion. El contrato ya documenta esta
doble procedencia en su seccion Trazabilidad ("y, cuando aplique, la busqueda por
CHIP de Mapas Bogota"); los campos enriquecidos no declaran vigencia propia para
no mezclar vigencias (FR-008). No se anade ningun campo a la respuesta: el schema
del contrato es additionalProperties=false.

Ciclo de vida (decision A1 punto 3): el servidor instanciado a nivel de modulo se
cierra con un lifespan de FastMCP/MCPServer (shutdown -> aclose de todos
providers). Los tests construyen servidores con MockTransport y los cierran
manualmente via servidor.aclose(); el lifespan solo corre cuando mcp.run() arranca.
"""

from __future__ import annotations

import asyncio
import os
import re
from contextlib import asynccontextmanager
from typing import Any, Callable

from app.cache import CacheLRUConTTL, construir_cache_por_defecto
from app.errores import (
    CodigoError,
    CorpusNoIngestadoError,
    CredencialFaltanteError,
    Fuente4xxError,
    Fuente5xxError,
    FuenteDatosInvalidosError,
    OllamaNoDisponibleError,
    UplNoEncontradaError,
    construir_error,
)
from app.models import (
    AccesoMovilidad,
    BloqueAccesoMovilidad,
    BloqueCatastroData,
    BloqueContextoSocioeconomico,
    BloqueDestinoEconomico,
    BloqueEntornoRegulatorio,
    BloqueEquipamientosCercanos,
    BloqueEspacioPublico,
    BloqueObrasPublicas,
    BloqueParametrosUrbanisticos,
    BloquePatrimonioCultural,
    BloqueRedVial,
    BloqueReservaVial,
    BloqueRiesgosGeotecnicos,
    BloqueValorReferencia,
    Centroide,
    ContextoAdministrativo,
    ContextoSocioeconomico,
    EntornoRegulatorio,
    EvidenciaNormativa,
    EstacionamientosRequeridos,
    FeasibilityScore,
    ItemEvidenciaNormativa,
    Localidad,
    Lote,
    ParametrosEdificabilidad,
    ParametrosUrbanisticos,
    PatrimonioCultural,
    RetirosLote,
    RiesgoGeotecnicos,
    SourceTrace,
    UPL,
    Warning,
)
from app.providers.arcgis import ArcGISProvider, FalloCapa
from app.providers.arcgis_utils import RAIZ_ARCGIS
from app.providers.geom import centroide_interior_de_geometria
from app.providers.mapas_bogota import CandidatoDireccion, MapasBogotaProvider
from app.providers.normativa import (
    CONSULTA_MAX_CHARS,
    CORPUS_LAYER_ID,
    CORPUS_SERVICE_URL,
    CORPUS_SOURCE_NAME,
    CORPUS_VIGENCIA,
    NormativaProvider,
    TOP_K_MAX,
)
from app.providers.sdp import SDPProvider
from app.providers.upl import UPLProvider, VIGENCIA_UPL_DEFAULT
from app.scoring import BloquesEvaluables, calcular_score
# Helpers compartidos (hallazgo m7): unica definicion en app/utilidades.py,
# importados con alias privado para no tocar los call sites de este modulo.
from app.utilidades import (
    PATRON_CHIP,
    ahora_iso as _ahora_iso,
    es_numero as _es_numero,
    formatear_numero as _formatear_numero,
)

try:  # mcp >= 1.x: FastMCP
    from mcp.server.fastmcp import FastMCP as _ClaseServidorMCP
except ImportError:  # mcp 2.x renombro FastMCP a MCPServer
    from mcp.server.mcpserver import MCPServer as _ClaseServidorMCP

NOMBRE_SERVIDOR = "mcp-bogota-factibilidad"


def _tiene_datos_catastro(ctx) -> bool:
    """True si el contexto catastral tiene al menos un campo poblado."""
    return any([
        ctx.construccion is not None,
        ctx.manzana is not None,
        ctx.densidad_predial is not None,
        ctx.variacion_area is not None,
        ctx.sector_catastral is not None,
    ])

CAMPOS_TRAZA = {"source_name", "layer_id", "service_url", "data_vigencia", "query_timestamp"}

# --- Feature 3: constantes del informe de factibilidad (research D3/H1-H7) ---
# Limites de la entrada del contrato get_feasibility_report (FR-013): direccion
# 1-200 caracteres, radio de obras publicas 500 m (FR-004). CONSULTA_MAX_CHARS y
# TOP_K_MAX se importan del provider normativa (limites compartidos con F2).
DIRECCION_MAX_CHARS = 200
RADIO_OBRAS_M = 500

# Derivacion clasificacion_suelo desde UPL.vocacion (research D2/H4): "Urbano" ->
# "urbano", "Rural" -> "rural", "Urbano-Rural" -> "urbano-rural"; vocacion
# desconocida o ausente -> None (el modelo admite null).
_CLASIFICACION_POR_VOCACION: dict[str, str] = {
    "urbano": "urbano",
    "rural": "rural",
    "urbano-rural": "urbano-rural",
}

# Codigo de localidad (01-20) por nombre derivado de la UPL (espejo del mapeo
# NOMBRE_UPL_A_LOCALIDAD de app/providers/upl.py, research D3).
_LOCALIDAD_A_CODIGO: dict[str, str] = {
    "Usaquen": "01",
    "Chapinero": "02",
    "Santa Fe": "03",
    "San Cristobal": "04",
    "Usme": "05",
    "Tunjuelito": "06",
    "Bosa": "07",
    "Kennedy": "08",
    "Fontibon": "09",
    "Engativa": "10",
    "Suba": "11",
    "Barrios Unidos": "12",
    "Teusaquillo": "13",
    "Los Martires": "14",
    "Antonio Narino": "15",
    "Puente Aranda": "16",
    "La Candelaria": "17",
    "Rafael Uribe Uribe": "18",
    "Ciudad Bolivar": "19",
    "Sumapaz": "20",
}


class ServidorLotes:
    """Logica de dominio de las 7 tools MCP (4 F1 + 2 F2 + 1 F3) sobre los providers tipados."""

    def __init__(
        self,
        provider_mapas: MapasBogotaProvider,
        provider_arcgis: ArcGISProvider,
        provider_upl: UPLProvider,
        provider_normativa: NormativaProvider,
        provider_sdp: SDPProvider | None = None,
        cache_lotes: CacheLRUConTTL | None = None,
    ) -> None:
        self._mapas = provider_mapas
        self._arcgis = provider_arcgis
        self._upl = provider_upl
        self._normativa = provider_normativa
        self._sdp = provider_sdp or SDPProvider()
        # Cache LRU+TTL de resolucion de lote (Fase 5): por defecto se lee de
        # CACHE_TTL_SEGUNDOS (0 = desactivada); los tests inyectan la suya.
        # Chequeo explicito de None (no `or`): una cache vacia tiene __len__ 0
        # y seria falsy, sustituida silenciosamente por la de entorno.
        self._cache_lotes = (
            cache_lotes if cache_lotes is not None else construir_cache_por_defecto()
        )

    async def aclose(self) -> None:
        await self._mapas.aclose()
        await self._arcgis.aclose()
        await self._upl.aclose()
        await self._normativa.aclose()
        await self._sdp.aclose()

    async def resolve_lot_by_chip(self, chip: str) -> dict[str, Any]:
        """Resuelve un lote por CHIP y devuelve su identidad, geometria, centroide y contexto tematico con trazabilidad por fuente."""
        error = _validar_chip(chip)
        if error:
            return error
        lote, error = await self._resolver_lote_por_chip(chip)
        if error:
            return error
        contexto, error = await self._consultar_contexto_seguro(lote)
        if error:
            return error
        return {"lote": _lote_a_contrato(lote), "contexto_tematico": contexto.a_contexto_contrato()}

    async def resolve_lot_by_address(self, address: str) -> dict[str, Any]:
        """Resuelve el lote asociado a una direccion (requiere MAPAS_BOGOTA_APIKEY; falla rapido si falta)."""
        error_direccion = _validar_direccion(address)
        if error_direccion:
            return error_direccion
        lote, error = await self._resolver_por_direccion(address)
        if error:
            return error
        contexto, error = await self._consultar_contexto_seguro(lote)
        if error:
            return error
        return {"lote": _lote_a_contrato(lote), "contexto_tematico": contexto.a_contexto_contrato()}

    async def resolve_lot_by_coordinates(
        self, latitude: float, longitude: float
    ) -> dict[str, Any]:
        """Resuelve el lote que contiene un punto (latitud, longitud en WGS84). No requiere credencial."""
        error = _validar_coordenadas(latitude, longitude)
        if error:
            return error
        lote, error = await self._resolver_lote_por_punto(longitude, latitude)
        if error:
            return error
        if lote is None:
            return construir_error(
                CodigoError.FUERA_DE_COBERTURA,
                message="El punto ({lat}, {lng}) está fuera del área de cobertura (Bogotá).",
                lat=latitude,
                lng=longitude,
            )
        contexto, error = await self._consultar_contexto_seguro(lote)
        if error:
            return error
        return {"lote": _lote_a_contrato(lote), "contexto_tematico": contexto.a_contexto_contrato()}

    async def get_lot_summary_by_chip(self, chip: str) -> dict[str, Any]:
        """Resumen consolidado descriptivo del lote por CHIP (identidad + contexto por fuente). Sin puntajes de factibilidad (FR-011)."""
        error = _validar_chip(chip)
        if error:
            return error
        lote, error = await self._resolver_lote_por_chip(chip)
        if error:
            return error
        contexto, error = await self._consultar_contexto_seguro(lote)
        if error:
            return error
        # Consulta catastro data en paralelo (F7): el provider reporta los
        # fallos tipados por capa como FalloCapa (FR-009); cada fallo produce un
        # warning BLOQUE_DEGRADADO con la causa real y la traza publicada es la
        # de la fuente consultada, nunca una fabricada. `source_traces` expone
        # la procedencia por sub-fuente (hallazgo M4): una traza por capa
        # exitosa con su vigencia propia.
        contexto_catastro, trace_catastro, trazas_catastro, fallos_catastro = (
            await self._arcgis.consultar_contexto_catastro(
                lote.centroid.lng, lote.centroid.lat
            )
        )
        catastro_disponible = _tiene_datos_catastro(contexto_catastro)

        # Consulta parámetros urbanísticos (F8, degradación independiente)
        summary_warnings: list[dict[str, str]] = []
        if fallos_catastro:
            summary_warnings.append(
                {
                    "codigo": "BLOQUE_DEGRADADO",
                    "mensaje": (
                        f"Bloque catastro_data degradado: "
                        f"{_mensaje_fallos(fallos_catastro)}."
                    ),
                }
            )
        bloque_urbanistic_summary = await _bloque_parametros_urbanisticos(
            lng=lote.centroid.lng,
            lat=lote.centroid.lat,
            provider_sdp=self._sdp,
            provider_normativa=self._normativa,
            upl_codigo=None,  # Sin UPL en resumen; se consultará si se necesita
            warnings=summary_warnings,
        )

        return {
            "identidad": _identidad_a_contrato(lote),
            "contexto_por_fuente": contexto.a_lista_por_fuente(),
            "catastro_data": {
                "estado": "disponible" if catastro_disponible else "no_encontrado",
                "dato": {
                    "construccion": contexto_catastro.construccion,
                    "manzana": contexto_catastro.manzana,
                    "densidad_predial": contexto_catastro.densidad_predial,
                    "variacion_area": contexto_catastro.variacion_area,
                    "sector_catastral": contexto_catastro.sector_catastral,
                } if catastro_disponible else None,
                "source_trace": trace_catastro.model_dump(),
                "source_traces": [traza.model_dump() for traza in trazas_catastro],
            },
            "urbanistic_parameters": _bloque_a_contrato(bloque_urbanistic_summary),
            "warnings": summary_warnings,
        }

    # --- F2: Tools de UPL y Normativa ---

    async def get_upl(
        self,
        chip: str | None = None,
        direccion: str | None = None,
        coordenadas: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Resuelve la UPL de un lote por CHIP, direccion o coordenadas (FR-005).
        Reutiliza el resolver de F1 para obtener el lote y su centroide,
        luego consulta la capa UPL (join espacial punto-en-poligono).
        """
        # Validacion fail-fast: exactamente un criterio (FR-013)
        criterios = sum(1 for c in (chip, direccion, coordenadas) if c is not None)
        if criterios != 1:
            return construir_error(
                CodigoError.PARAMETROS_INVALIDOS,
                message="Parámetros inválidos: debe proveer exactamente uno de chip, direccion o coordenadas.",
            )

        lote, error = None, None

        if chip is not None:
            error = _validar_chip(chip)
            if error:
                return error
            lote, error = await self._resolver_lote_por_chip(chip)
            if error:
                return error

        elif direccion is not None:
            error_direccion = _validar_direccion(direccion)
            if error_direccion:
                return error_direccion
            lote, error = await self._resolver_por_direccion(direccion)
            if error:
                return error

        elif coordenadas is not None:
            lat = coordenadas.get("lat")
            lng = coordenadas.get("lon")
            error = _validar_coordenadas(lat, lng)
            if error:
                return error
            lote, error = await self._resolver_lote_por_punto(lng, lat)
            if error and error.get("error", {}).get("code") == CodigoError.LOTE_NO_ENCONTRADO.value:
                # Fix E2E: si el punto es ambiguo (limite entre lotes), la UPL se
                # consulta directamente por el punto de entrada: la capa UPL
                # intersecta por geometria y no depende de la identidad del lote.
                return await self._consultar_upl_por_punto(lng, lat)
            if error:
                return error
            if lote is None:
                return construir_error(
                    CodigoError.FUERA_DE_COBERTURA,
                    message="El punto ({lat}, {lng}) está fuera del área de cobertura (Bogotá).",
                    lat=lat,
                    lng=lng,
                )

        if lote is None:
            return construir_error(CodigoError.LOTE_NO_ENCONTRADO)

        # Consulta UPL por centroide del lote
        try:
            upl = await self._upl.consultar_upl_por_punto(lote.centroid.lng, lote.centroid.lat)
        except Exception as exc:
            return _error_de_fuente(exc)

        return _respuesta_upl(upl, metodo="centroide_lote")

    async def consultar_normativa(
        self,
        consulta: str,
        upl: str | None = None,
        top_k: int = 3,
    ) -> dict[str, Any]:
        """Consulta la normativa del POT (Decreto 555/2021) con RAG (FR-001, FR-003, Historia 1).

        Filtro estricto por UPL opcional (FR-002, Historia 3).
        """
        # Validaciones fail-fast (FR-013) - el provider valida internamente
        try:
            resultado = await self._normativa.consultar(consulta=consulta, upl=upl, top_k=top_k)
        except ValueError as exc:
            return construir_error(CodigoError.PARAMETROS_INVALIDOS, message=f"Parámetros inválidos: {exc}.")
        except Exception as exc:
            # CorpusNoIngestadoError, OllamaNoDisponibleError, Fuente5xxError, etc.
            return _error_de_fuente(exc)

        return resultado

    # --- F3: Informe de factibilidad orquestado ---

    async def get_feasibility_report(
        self,
        chip: str | None = None,
        direccion: str | None = None,
        coordenadas: dict[str, float] | None = None,
        consulta: str | None = None,
        top_k: int = 3,
    ) -> dict[str, Any]:
        """Informe de factibilidad de un lote (FR-001): identidad, UPL, restricciones,
        mercado, entorno, destino economico, normativa y score deterministico.

        Degrada por bloque (contrato F3): UPL/RAG ausentes no son errores; un 5xx
        de cualquier fuente es FUENTE_5XX fatal (FR-009). El score es 100 %
        deterministico (SC-003) y las interpretations solo describen datos reales
        de las fuentes (FR-014).
        """
        # --- Validacion fail-fast (FR-013): entrada invalida no toca ninguna fuente ---
        criterios = sum(1 for c in (chip, direccion, coordenadas) if c is not None)
        if criterios != 1:
            return construir_error(
                CodigoError.PARAMETROS_INVALIDOS,
                message="Parámetros inválidos: debe proveer exactamente uno de chip, direccion o coordenadas.",
            )
        if chip is not None:
            error_chip = _validar_chip(chip)
            if error_chip:
                return error_chip
        if direccion is not None:
            error_direccion = _validar_direccion(direccion)
            if error_direccion:
                return error_direccion
        if coordenadas is not None:
            if not isinstance(coordenadas, dict):
                return construir_error(
                    CodigoError.PARAMETROS_INVALIDOS,
                    message="Parámetros inválidos: coordenadas debe ser un objeto con lat y lon.",
                )
            lat_entrada = coordenadas.get("lat")
            lng_entrada = coordenadas.get("lon")
            error_coordenadas = _validar_coordenadas(lat_entrada, lng_entrada)
            if error_coordenadas:
                return error_coordenadas
        if consulta is not None:
            if not isinstance(consulta, str) or not consulta.strip():
                return construir_error(
                    CodigoError.PARAMETROS_INVALIDOS,
                    message="Parámetros inválidos: la consulta no puede estar vacía.",
                )
            if len(consulta.strip()) > CONSULTA_MAX_CHARS:
                return construir_error(
                    CodigoError.PARAMETROS_INVALIDOS,
                    message=(
                        f"Parámetros inválidos: la consulta no puede superar "
                        f"{CONSULTA_MAX_CHARS} caracteres."
                    ),
                )
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= TOP_K_MAX:
            return construir_error(
                CodigoError.PARAMETROS_INVALIDOS,
                message=f"Parámetros inválidos: top_k debe ser un entero entre 1 y {TOP_K_MAX}.",
            )

        # --- Resolucion del lote (flujos privados de F1) ---
        if chip is not None:
            lote, error = await self._resolver_lote_por_chip(chip)
        elif direccion is not None:
            lote, error = await self._resolver_por_direccion(direccion, incluir_contexto=False)
            if error and error.get("multiples_candidatos"):
                error = construir_error(
                    CodigoError.LOTE_NO_ENCONTRADO,
                    message=(
                        "No se encontró un lote único para la dirección: hay varios "
                        "candidatos. Refina la dirección para elegir uno."
                    ),
                )
            if error:
                return error
            if lote is None:
                return construir_error(
                    CodigoError.FUERA_DE_COBERTURA,
                    message="El punto ({lat}, {lng}) está fuera del área de cobertura (Bogotá).",
                    lat=lat_entrada,
                    lng=lng_entrada,
                )
        else:
            lote, error = await self._resolver_lote_por_punto(lng_entrada, lat_entrada)
            if error:
                return error
            if lote is None:
                return construir_error(
                    CodigoError.FUERA_DE_COBERTURA,
                    message="El punto ({lat}, {lng}) está fuera del área de cobertura (Bogotá).",
                    lat=lat_entrada,
                    lng=lng_entrada,
                )
        if error:
            return error
        if lote is None:
            return construir_error(CodigoError.LOTE_NO_ENCONTRADO)

        warnings: list[dict[str, str]] = []
        if lote.chip is None:
            warnings.append(
                {
                    "codigo": "LOTE_SIN_CHIP",
                    "mensaje": "El lote se resolvió sin CHIP: la capa Lote no publica el identificador catastral.",
                }
            )

        # --- UPL, localidad y clasificacion de suelo (degradacion por bloque) ---
        upl = None
        try:
            upl = await self._upl.consultar_upl_por_punto(lote.centroid.lng, lote.centroid.lat)
        except UplNoEncontradaError:
            warnings.append(
                {
                    "codigo": "UPL_NO_ENCONTRADA",
                    "mensaje": "No se encontró una UPL para el lote en la fuente consultada.",
                }
            )
        except Exception as exc:
            return _error_de_fuente(exc)

        localidad = None
        clasificacion_suelo = None
        if upl is not None:
            nombre_localidad = upl.localidad_derivada
            codigo_localidad = (
                _LOCALIDAD_A_CODIGO.get(nombre_localidad) if nombre_localidad else None
            )
            if nombre_localidad is None or codigo_localidad is None:
                # Hallazgo m3: sin codigo derivado NO se construye Localidad con
                # centinela "": el bloque queda en null + warning (mismo trato
                # que un nombre fuera del mapeo estatico).
                warnings.append(
                    {
                        "codigo": "LOCALIDAD_NO_DERIVADA",
                        "mensaje": (
                            f"No se pudo derivar la localidad de la UPL "
                            f"{upl.codigo_upl} {upl.nombre}."
                        ),
                    }
                )
            else:
                localidad = Localidad(codigo=codigo_localidad, nombre=nombre_localidad)
            vocacion = (upl.vocacion or "").strip().lower()
            clasificacion_suelo = _CLASIFICACION_POR_VOCACION.get(vocacion)

        if upl is not None and upl.source_trace is not None:
            trace_upl = upl.source_trace
        else:
            trace_upl = SourceTrace(**_trace_upl_por_defecto())
        administrativo = ContextoAdministrativo(
            upl=upl,
            localidad=localidad,
            clasificacion_suelo=clasificacion_suelo,
            source_trace=trace_upl,
        )

        # --- Contexto tematico, obras publicas y destino economico en paralelo ---
        # (deuda tecnica post-revision: antes eran 3 rondas HTTP secuenciales).
        # Semantica de errores preservada: contexto primero (tuple (contexto,
        # error|None) de _consultar_contexto_seguro), luego obras y destino
        # (excepciones tipadas -> _error_de_fuente; inesperadas -> fail loud).
        t_contexto = self._consultar_contexto_seguro(lote)
        t_obras = self._arcgis.consultar_obras_publicas_radio(
            lote.centroid.lng, lote.centroid.lat, RADIO_OBRAS_M
        )
        t_destino = self._arcgis.consultar_destino_economico(
            chip=lote.chip, codigo_catastral=lote.codigo_catastral
        )
        r_contexto, r_obras, r_destino = await asyncio.gather(
            t_contexto, t_obras, t_destino, return_exceptions=True
        )
        if isinstance(r_contexto, BaseException):
            return _error_de_fuente(r_contexto)
        contexto, error_contexto = r_contexto
        if error_contexto:
            return error_contexto
        if isinstance(r_obras, BaseException):
            return _error_de_fuente(r_obras)
        obras_publicas = r_obras
        if isinstance(r_destino, BaseException):
            return _error_de_fuente(r_destino)
        destino = r_destino

        # --- Segunda ronda de consultas paralelas: 5 bloques adicionales F6 ---
        # Cada bloque degrada independientemente (FR-012): los fallos tipados de
        # capa viajan DENTRO del resultado del provider (FalloCapa, FR-009) y
        # producen warning BLOQUE_DEGRADADO con la causa real; nunca se maquillan
        # como "no encontrado" silencioso. Solo una excepcion inesperada (no
        # tipada) del provider llega hasta aqui, y se clasifica con
        # _error_de_fuente (fail loud para errores no tipados).
        t_geotecnia = self._arcgis.consultar_riesgos_geotecnicos(
            lote.centroid.lng, lote.centroid.lat
        )
        t_socio = self._arcgis.consultar_contexto_socioeconomico(
            lote.centroid.lng, lote.centroid.lat
        )
        t_regulatorio = self._arcgis.consultar_entorno_regulatorio(
            lote.centroid.lng, lote.centroid.lat
        )
        t_patrimonio = self._arcgis.consultar_patrimonio_cultural(
            lote.centroid.lng, lote.centroid.lat
        )
        t_movilidad = self._arcgis.consultar_acceso_movilidad(
            lote.centroid.lng, lote.centroid.lat
        )
        t_catastro = self._arcgis.consultar_contexto_catastro(
            lote.centroid.lng, lote.centroid.lat
        )
        # Fase 3: espacio publico, malla vial y equipamientos cercanos.
        t_espacio_publico = self._arcgis.consultar_espacio_publico(
            lote.centroid.lng, lote.centroid.lat
        )
        t_red_vial = self._arcgis.consultar_red_vial(lote.centroid.lng, lote.centroid.lat)
        t_equipamientos = self._arcgis.consultar_equipamientos_cercanos(
            lote.centroid.lng, lote.centroid.lat
        )
        # Dos gathers anidados bajo un gather externo: los 9 bloques corren en
        # paralelo y cada grupo conserva la tupla tipada de resultados (la
        # sobrecarga tipada de asyncio.gather degrada a uniones combinatorias
        # con mas de 6 corutinas).
        (
            (
                r_geotecnia,
                r_socio,
                r_regulatorio,
                r_patrimonio,
                r_movilidad,
                r_catastro,
            ),
            (r_espacio_publico, r_red_vial, r_equipamientos),
        ) = await asyncio.gather(
            asyncio.gather(
                t_geotecnia,
                t_socio,
                t_regulatorio,
                t_patrimonio,
                t_movilidad,
                t_catastro,
                return_exceptions=True,
            ),
            asyncio.gather(
                t_espacio_publico,
                t_red_vial,
                t_equipamientos,
                return_exceptions=True,
            ),
        )

        # --- Bloques con el patron {estado, dato, interpretation, source_trace} ---
        reserva = contexto.reserva_vial
        if reserva.estado == "disponible":
            interpretation_planning = "El lote se superpone a una zona de reserva vial."
        else:
            interpretation_planning = (
                "No se encontraron zonas de reserva vial que afecten el lote "
                "en la fuente consultada."
            )
            warnings.append(
                {
                    "codigo": "BLOQUE_SIN_DATO",
                    "mensaje": (
                        "Bloque planning_constraints no encontrado: no se hallaron "
                        "zonas de reserva vial que afecten el lote en la fuente consultada."
                    ),
                }
            )
        bloque_planning = BloqueReservaVial(
            estado=reserva.estado,
            dato=reserva if reserva.estado == "disponible" else None,
            interpretation=interpretation_planning,
            source_trace=reserva.source_trace,
        )

        valor = contexto.valor_referencia
        if valor.estado == "disponible":
            valor_m2_texto = (
                _formatear_numero(valor.valor_m2) if valor.valor_m2 is not None else "desconocido"
            )
            vigencia_texto = valor.vigencia or "desconocida"
            interpretation_market = (
                f"Valor de referencia catastral del terreno: {valor_m2_texto} "
                f"COP/m² (vigencia {vigencia_texto})."
            )
        else:
            interpretation_market = (
                "No se encontró un valor de referencia catastral para el lote "
                "en la fuente consultada."
            )
            warnings.append(
                {
                    "codigo": "BLOQUE_SIN_DATO",
                    "mensaje": (
                        "Bloque market_context no encontrado: no se halló valor "
                        "de referencia catastral para el lote en la fuente consultada."
                    ),
                }
            )
        bloque_market = BloqueValorReferencia(
            estado=valor.estado,
            dato=valor if valor.estado == "disponible" else None,
            interpretation=interpretation_market,
            source_trace=valor.source_trace,
        )

        if obras_publicas.estado == "disponible":
            cantidad_obras = len(obras_publicas.obras or [])
            interpretation_environment = (
                f"Se identificaron {cantidad_obras} obra(s) pública(s) en un radio "
                f"de {RADIO_OBRAS_M} m del lote."
            )
        else:
            interpretation_environment = (
                f"No se identificaron obras públicas en un radio de {RADIO_OBRAS_M} m "
                "del lote en la fuente consultada."
            )
            warnings.append(
                {
                    "codigo": "BLOQUE_SIN_DATO",
                    "mensaje": (
                        "Bloque environment_context no encontrado: no se identificaron "
                        "obras públicas en el radio consultado."
                    ),
                }
            )
        bloque_environment = BloqueObrasPublicas(
            estado=obras_publicas.estado,
            dato=obras_publicas if obras_publicas.estado == "disponible" else None,
            interpretation=interpretation_environment,
            source_trace=obras_publicas.source_trace,
        )

        if destino.estado == "disponible":
            detalle_destino = f"código {destino.codigo_destino}"
            if destino.uso:
                detalle_destino += f", uso: {destino.uso}"
            interpretation_economic = (
                f"Destino económico predominante del lote: "
                f"{destino.descripcion_destino or 'destino económico'} ({detalle_destino})."
            )
        else:
            interpretation_economic = (
                "No se encontró un destino económico para el lote en la fuente consultada."
            )
            warnings.append(
                {
                    "codigo": "BLOQUE_SIN_DATO",
                    "mensaje": (
                        "Bloque economic_context no encontrado: no se halló destino "
                        "económico para el lote en la fuente consultada."
                    ),
                }
            )
        bloque_economic = BloqueDestinoEconomico(
            estado=destino.estado,
            dato=destino if destino.estado == "disponible" else None,
            interpretation=interpretation_economic,
            source_trace=destino.source_trace,
        )

        # --- Bloques adicionales F6: construccion con patron {estado, dato, interpretation, source_trace} ---
        # Cada bloque degrada independientemente (FR-012): los fallos tipados de
        # capa llegan como FalloCapa dentro del resultado del provider y producen
        # warning BLOQUE_DEGRADADO con la causa real (FR-009). Regla por bloque:
        # fallos sin datos -> no_encontrado + BLOQUE_DEGRADADO; fallos con datos
        # -> disponible + BLOQUE_DEGRADADO parcial; sin fallos y sin datos ->
        # no_encontrado + BLOQUE_SIN_DATO.

        # Bloque geotechnical_risks
        if isinstance(r_geotecnia, BaseException):
            return _error_de_fuente(r_geotecnia)
        riesgos_geotec, trace_geotecnia, trazas_geotec, fallos_geotec = r_geotecnia
        bloque_geotecnia = _construir_bloque_degradable(
            "geotechnical_risks",
            dato=riesgos_geotec, trace=trace_geotecnia, trazas=trazas_geotec,
            fallos=fallos_geotec,
            tiene_datos_fn=lambda d: any([
                d.amenaza_movimientos, d.geologia,
                d.respuesta_sismica, d.zonificacion_geotecnica,
            ]),
            interpretacion_fn=_interpretar_geotecnia,
            bloque_class=BloqueRiesgosGeotecnicos,
            warnings=warnings,
            msg_degradado="No se pudieron consultar los datos geotécnicos.",
            msg_no_encontrado="no se hallaron datos geotécnicos para el lote.",
        )

        # Bloque socioeconomic_context
        if isinstance(r_socio, BaseException):
            return _error_de_fuente(r_socio)
        contexto_socio, trace_socio, trazas_socio, fallos_socio = r_socio
        bloque_socio = _construir_bloque_degradable(
            "socioeconomic_context",
            dato=contexto_socio, trace=trace_socio, trazas=trazas_socio,
            fallos=fallos_socio,
            tiene_datos_fn=lambda d: any([
                d.estrato is not None, d.uso_predominante,
                d.altura_media is not None, d.mediana_avaluo is not None,
            ]),
            interpretacion_fn=_interpretar_socio,
            bloque_class=BloqueContextoSocioeconomico,
            warnings=warnings,
            msg_degradado="No se pudieron consultar los datos socioeconómicos.",
            msg_no_encontrado="no se hallaron datos socioeconómicos para el lote.",
        )

        # Bloque regulatory_environment
        if isinstance(r_regulatorio, BaseException):
            return _error_de_fuente(r_regulatorio)
        entorno_reg, trace_regulatorio, trazas_regulatorio, fallos_regulatorio = r_regulatorio
        bloque_regulatorio = _construir_bloque_degradable(
            "regulatory_environment",
            dato=entorno_reg, trace=trace_regulatorio, trazas=trazas_regulatorio,
            fallos=fallos_regulatorio,
            tiene_datos_fn=lambda d: any([
                d.licencias_encontradas is not None, d.zona_plusvalia is not None,
            ]),
            interpretacion_fn=_interpretar_regulatorio,
            bloque_class=BloqueEntornoRegulatorio,
            warnings=warnings,
            msg_degradado="No se pudieron consultar los datos regulatorios.",
            msg_no_encontrado="no se hallaron datos regulatorios para el lote.",
        )

        # Bloque cultural_heritage
        if isinstance(r_patrimonio, BaseException):
            return _error_de_fuente(r_patrimonio)
        patrimonio, trace_patrimonio, trazas_patrimonio, fallos_patrimonio = r_patrimonio
        bloque_patrimonio = _construir_bloque_degradable(
            "cultural_heritage",
            dato=patrimonio, trace=trace_patrimonio, trazas=trazas_patrimonio,
            fallos=fallos_patrimonio,
            tiene_datos_fn=lambda d: any([
                d.bic_cercano is not None, d.zona_arqueologica is not None,
            ]),
            interpretacion_fn=_interpretar_patrimonio,
            bloque_class=BloquePatrimonioCultural,
            warnings=warnings,
            msg_degradado="No se pudieron consultar los datos de patrimonio cultural.",
            msg_no_encontrado="no se hallaron elementos de patrimonio cultural para el lote.",
        )

        # Bloque transit_access
        if isinstance(r_movilidad, BaseException):
            return _error_de_fuente(r_movilidad)
        movilidad, trace_movilidad, trazas_movilidad, fallos_movilidad = r_movilidad
        bloque_movilidad = _construir_bloque_degradable(
            "transit_access",
            dato=movilidad, trace=trace_movilidad, trazas=trazas_movilidad,
            fallos=fallos_movilidad,
            tiene_datos_fn=lambda d: any([
                d.estaciones_transmilenio is not None,
                d.paraderos_sitp is not None,
                d.estaciones_metro is not None,
            ]),
            interpretacion_fn=_interpretar_movilidad,
            bloque_class=BloqueAccesoMovilidad,
            warnings=warnings,
            msg_degradado="No se pudieron consultar los datos de transporte público.",
            msg_no_encontrado="no se identificaron estaciones de transporte público cercanas al lote.",
        )

        # Bloque catastro_data
        if isinstance(r_catastro, BaseException):
            return _error_de_fuente(r_catastro)
        contexto_catastro, trace_catastro, trazas_catastro_f3, fallos_catastro_f3 = r_catastro
        bloque_catastro = _construir_bloque_degradable(
            "catastro_data",
            dato=contexto_catastro, trace=trace_catastro, trazas=trazas_catastro_f3,
            fallos=fallos_catastro_f3,
            tiene_datos_fn=_tiene_datos_catastro,
            interpretacion_fn=_interpretar_catastro,
            bloque_class=BloqueCatastroData,
            warnings=warnings,
            msg_degradado="No se pudieron consultar los datos catastrales adicionales.",
            msg_no_encontrado="no se hallaron datos catastrales adicionales para el lote.",
        )

        # --- Bloques Fase 3: espacio publico, malla vial y equipamientos ---
        # Mismo patron de degradacion independiente que los bloques F6/F7:
        # fallos sin datos -> no_encontrado + BLOQUE_DEGRADADO; fallos con
        # datos -> disponible + BLOQUE_DEGRADADO parcial; sin fallos y sin
        # datos -> no_encontrado + BLOQUE_SIN_DATO.

        # Bloque public_space_context (monofuente: indicadorespaciopublico/8)
        if isinstance(r_espacio_publico, BaseException):
            return _error_de_fuente(r_espacio_publico)
        espacio_publico, trace_espacio, _, fallos_espacio = r_espacio_publico
        bloque_espacio = _construir_bloque_degradable(
            "public_space_context",
            dato=espacio_publico, trace=trace_espacio, trazas=None,
            fallos=fallos_espacio,
            tiene_datos_fn=lambda d: d.ep_total_m2_hab is not None,
            interpretacion_fn=_interpretar_espacio_publico,
            bloque_class=BloqueEspacioPublico,
            tiene_source_traces=False,
            warnings=warnings,
            msg_degradado="No se pudieron consultar los datos de espacio público.",
            msg_no_encontrado="no se halló indicador de espacio público para la UPL del lote.",
        )

        # Bloque road_network_context (monofuente: Mapa_Referencia layer 13)
        if isinstance(r_red_vial, BaseException):
            return _error_de_fuente(r_red_vial)
        red_vial, trace_vial, _, fallos_vial = r_red_vial
        bloque_vial = _construir_bloque_degradable(
            "road_network_context",
            dato=red_vial, trace=trace_vial, trazas=None,
            fallos=fallos_vial,
            tiene_datos_fn=lambda d: bool(d.vias_frente),
            interpretacion_fn=_interpretar_red_vial,
            bloque_class=BloqueRedVial,
            tiene_source_traces=False,
            warnings=warnings,
            msg_degradado="No se pudieron consultar los datos de la malla vial.",
            msg_no_encontrado="no se hallaron ejes viales en el radio consultado.",
        )

        # Bloque nearby_facilities (multifuente: 5 capas de equipamientos)
        if isinstance(r_equipamientos, BaseException):
            return _error_de_fuente(r_equipamientos)
        equipamientos, trace_facilidades, trazas_facilidades, fallos_facilidades = (
            r_equipamientos
        )
        bloque_facilidades = _construir_bloque_degradable(
            "nearby_facilities",
            dato=equipamientos, trace=trace_facilidades, trazas=trazas_facilidades,
            fallos=fallos_facilidades,
            tiene_datos_fn=lambda d: bool(d.equipamientos),
            interpretacion_fn=_interpretar_equipamientos,
            bloque_class=BloqueEquipamientosCercanos,
            warnings=warnings,
            msg_degradado="No se pudieron consultar los equipamientos cercanos.",
            msg_no_encontrado="no se hallaron equipamientos cercanos al lote.",
        )

        # --- Cuarta ronda: parámetros urbanísticos (F8, degradación independiente) ---
        # Consulta SDP (tratamiento espacial) + RAG (parámetros numéricos).
        # No afecta a otros bloques si falla (FR-008, SC-004).
        upl_filtro_urban = upl.codigo_upl if upl is not None else None
        bloque_urbanistic = await _bloque_parametros_urbanisticos(
            lng=lote.centroid.lng,
            lat=lote.centroid.lat,
            provider_sdp=self._sdp,
            provider_normativa=self._normativa,
            upl_codigo=upl_filtro_urban,
            warnings=warnings,
        )

        # --- Evidencia normativa (consulta explicita o automatica; degradacion por bloque) ---
        consulta_automatica = consulta is None
        consulta_efectiva = (
            consulta
            if not consulta_automatica
            else _construir_consulta_automatica(upl, localidad, clasificacion_suelo)
        )
        upl_filtro = upl.codigo_upl if upl is not None else None
        try:
            resultado_normativa = await self._normativa.consultar(
                consulta=consulta_efectiva, upl=upl_filtro, top_k=top_k
            )
        except CorpusNoIngestadoError:
            items_normativa: list[ItemEvidenciaNormativa] = []
            causa_normativa = "CORPUS_NO_INGESTADO"
            sin_resultados_normativa = True
            traza_normativa = _trace_corpus_por_defecto()
            warnings.append(
                {
                    "codigo": "NORMATIVA_NO_DISPONIBLE",
                    "mensaje": "El corpus normativo no está disponible: se omite la evidencia normativa del informe.",
                }
            )
        except OllamaNoDisponibleError:
            items_normativa = []
            causa_normativa = "OLLAMA_NO_DISPONIBLE"
            sin_resultados_normativa = True
            traza_normativa = _trace_corpus_por_defecto()
            warnings.append(
                {
                    "codigo": "NORMATIVA_NO_DISPONIBLE",
                    "mensaje": "El servicio Ollama no está disponible: se omite la evidencia normativa del informe.",
                }
            )
        except Exception as exc:
            return _error_de_fuente(exc)
        else:
            items_normativa = [
                ItemEvidenciaNormativa(
                    articulo=str(item["articulo"]),
                    titulo=item.get("titulo", ""),
                    libro=item.get("libro", ""),
                    parte=item.get("parte"),
                    texto_cita=item.get("texto_cita", ""),
                    similitud=item.get("similitud"),
                    # Campos aditivos F4 (FR-004/FR-005): norma real del fragmento
                    # (555 o acto modificatorio) con su trazabilidad. Si el provider
                    # no los emite, quedan None (degradacion F3 intacta).
                    norma=item.get("norma"),
                    source_name=item.get("source_name"),
                )
                for item in resultado_normativa.get("resultados", [])
            ]
            causa_normativa = "SIN_RESULTADOS" if not items_normativa else None
            sin_resultados_normativa = not items_normativa
            traza_normativa = (
                resultado_normativa.get("trazabilidad") or _trace_corpus_por_defecto()
            )
            if not items_normativa:
                warnings.append(
                    {
                        "codigo": "NORMATIVA_SIN_RESULTADOS",
                        "mensaje": "No se encontraron resultados normativos relevantes para la consulta.",
                    }
                )

        evidencia = EvidenciaNormativa(
            items=items_normativa,
            consulta=consulta_efectiva,
            consulta_automatica=consulta_automatica,
            sin_resultados=sin_resultados_normativa,
            causa=causa_normativa,
            source_trace=SourceTrace(**traza_normativa),
        )

        # --- Scoring puro (research D3, SC-003) ---
        bloques_evaluables = BloquesEvaluables(
            administrative_context=administrativo,
            planning_constraints=bloque_planning,
            market_context=bloque_market,
            environment_context=bloque_environment,
            economic_context=bloque_economic,
            geotechnical_risks=bloque_geotecnia,
            socioeconomic_context=bloque_socio,
            regulatory_environment=bloque_regulatorio,
            cultural_heritage=bloque_patrimonio,
            transit_access=bloque_movilidad,
            catastro_data=bloque_catastro,
            public_space_context=bloque_espacio,
            road_network_context=bloque_vial,
            nearby_facilities=bloque_facilidades,
            normative_evidence=evidencia,
            urbanistic_parameters=bloque_urbanistic,
        )
        score = calcular_score(bloques_evaluables)

        return {
            "lot_identity": _lote_a_contrato(lote),
            "administrative_context": _contexto_administrativo_a_contrato(administrativo),
            "planning_constraints": _bloque_a_contrato(bloque_planning),
            "market_context": _bloque_a_contrato(bloque_market),
            "environment_context": _bloque_a_contrato(
                bloque_environment, extra_dato={"radio_m": RADIO_OBRAS_M}
            ),
            "economic_context": _bloque_a_contrato(bloque_economic),
            "geotechnical_risks": _bloque_a_contrato(bloque_geotecnia),
            "socioeconomic_context": _bloque_a_contrato(bloque_socio),
            "regulatory_environment": _bloque_a_contrato(bloque_regulatorio),
            "cultural_heritage": _bloque_a_contrato(bloque_patrimonio),
            "transit_access": _bloque_a_contrato(bloque_movilidad),
            "catastro_data": _bloque_a_contrato(bloque_catastro),
            "public_space_context": _bloque_a_contrato(bloque_espacio),
            "road_network_context": _bloque_a_contrato(bloque_vial),
            "nearby_facilities": _bloque_a_contrato(bloque_facilidades),
            "urbanistic_parameters": _bloque_a_contrato(bloque_urbanistic),
            "normative_evidence": evidencia.model_dump(),
            "feasibility_score": score.model_dump(),
            "warnings": warnings,
            "llm_ready_summary": _construir_llm_ready_summary(
                lote=lote,
                upl=upl,
                localidad=localidad,
                clasificacion_suelo=clasificacion_suelo,
                score=score,
                warnings=warnings,
            ),
            "query_timestamp": _ahora_iso(),
        }

    # --- Flujos internos ---

    async def _resolver_lote_por_chip(self, chip: str) -> tuple[Lote | None, dict | None]:
        """Resuelve el lote por CHIP: capa ArcGIS layer 38 + enriquecimiento Mapas Bogota.

        Jerarquia de fuentes (decision A1 punto 1, opcion b): la identidad y la
        geometria provienen de la capa Lote (source_trace = capa Lote). Cuando la
        capa no trae direccion/barrio, se enriquecen desde Mapas Bogota
        (direccion_chip); la capa manda sobre el enriquecimiento si trae el dato.
        Los campos enriquecidos no declaran vigencia propia: no se mezclan
        vigencias (FR-008) ni se atribuye a ArcGIS datos de Mapas Bogota.

        Cache (Fase 5): solo los resultados EXITOSOS se cachean bajo
        `chip:<CHIP>`; errores de fuente y "no encontrado" nunca se cachean para
        que un fallo transitorio o un CHIP dado de alta a medias no quede
        congelado durante el TTL. La cache es transparente: mismo resultado.
        """
        clave_cache = f"chip:{chip}"
        cacheado = self._cache_lotes.obtener(clave_cache)
        if cacheado is not None:
            return cacheado
        try:
            predio = await self._mapas.buscar_por_chip(chip)
        except (Fuente5xxError, Fuente4xxError, FuenteDatosInvalidosError) as exc:
            return None, _error_de_fuente(exc)
        if predio is None:
            return None, self._error_chip_no_encontrado(chip)
        lng, lat = predio.centroid
        lote, error = await self._resolver_lote_por_punto(lng, lat)
        if error:
            return None, error
        if lote is None:
            return None, self._error_chip_no_encontrado(chip)
        # La identidad oficial (CHIP) proviene del criterio de entrada; la capa
        # Lote manda sobre los campos enriquecidos cuando los trae.
        resuelto = (
            Lote(
                chip=chip,
                codigo_catastral=lote.codigo_catastral,
                manzana=lote.manzana,
                direccion_normalizada=lote.direccion_normalizada or predio.direccion,
                barrio=lote.barrio or predio.barrio,
                geometry=lote.geometry,
                centroid=lote.centroid,
                source_trace=lote.source_trace,
            ),
            None,
        )
        self._cache_lotes.guardar(clave_cache, resuelto)
        return resuelto

    async def _resolver_lote_por_candidato(
        self, candidato: CandidatoDireccion, incluir_contexto: bool = True
    ) -> tuple[Lote | None, dict | None]:
        lote, error = await self._resolver_lote_por_punto(candidato.lng, candidato.lat)
        if error:
            return None, error
        if lote is None:
            return None, construir_error(
                CodigoError.LOTE_NO_ENCONTRADO,
                message="No se encontró un lote único para el punto ({lat}, {lng}).",
                lat=candidato.lat,
                lng=candidato.lng,
            )
        lote_con_direccion = Lote(
            chip=lote.chip,
            codigo_catastral=lote.codigo_catastral,
            manzana=lote.manzana,
            direccion_normalizada=lote.direccion_normalizada or candidato.direccion_normalizada,
            barrio=lote.barrio,
            geometry=lote.geometry,
            centroid=lote.centroid,
            source_trace=lote.source_trace,
        )
        if incluir_contexto:
            # Comportamiento F1 (resolve_lot_by_address/get_upl por direccion): se
            # propaga un error del contexto tematico como error de la resolucion.
            # El orquestador F3 llama con incluir_contexto=False: consulta el
            # contexto una sola vez (deuda tecnica post-revision).
            contexto, error = await self._consultar_contexto_seguro(lote_con_direccion)
            if error:
                return None, error
        return lote_con_direccion, None

    async def _resolver_lote_por_punto(
        self, lng: float, lat: float
    ) -> tuple[Lote | None, dict | None]:
        """Resuelve el lote unico que contiene el punto.

        La identidad del lote NO depende del CHIP: la capa Lote (layer 38) no
        trae el campo CHIP y este solo llega desde Mapas Bogota; LOTCODIGO y
        MANZCODIGO son identidad catastral suficiente (decision de producto).
        Un lote unico sin CHIP se resuelve igual (chip=None en la respuesta).

        Semantica del retorno:
        - (Lote, None): lote unico encontrado (con o sin CHIP).
        - (None, error): no se pudo resolver (5xx o punto ambiguo entre lotes);
          el error ya es la respuesta de la tool.
        - (None, None): no hay lote en el punto. El llamador decide el codigo
          (FUERA_DE_COBERTURA para coordenadas, LOTE_NO_ENCONTRADO para CHIP/direccion).
        """
        try:
            lotes = await self._arcgis.consultar_lotes_por_punto(lng, lat)
        except (Fuente5xxError, Fuente4xxError, FuenteDatosInvalidosError) as exc:
            return None, _error_de_fuente(exc)
        if len(lotes) == 0:
            return None, None
        if len(lotes) > 1:
            return None, construir_error(
                CodigoError.LOTE_NO_ENCONTRADO,
                message="No se encontró un lote único para el punto ({lat}, {lng}).",
                lat=lat,
                lng=lng,
            )
        arcgis = lotes[0]
        # Centroide publicado (hallazgo M3): es el centroide GEOMETRICO interior
        # del poligono de la capa 38, no el punto de consulta. El punto de
        # consulta puede caer en el borde del lote y distorsionar las consultas
        # tematicas posteriores; el fallback al punto de entrada solo aplica si
        # la geometria no es utilizable (determinismo preservado).
        centroide_geometrico = centroide_interior_de_geometria(arcgis.geometry)
        lng_centroide, lat_centroide = (
            centroide_geometrico if centroide_geometrico is not None else (lng, lat)
        )
        lote = Lote(
            chip=arcgis.chip,
            codigo_catastral=arcgis.codigo_catastral,
            manzana=arcgis.manzana,
            direccion_normalizada=arcgis.direccion_normalizada,
            barrio=arcgis.barrio,
            geometry=arcgis.geometry,
            centroid=Centroide(lat=lat_centroide, lng=lng_centroide),
            source_trace=arcgis.source_trace,
        )
        return lote, None

    async def _consultar_contexto_seguro(
        self, lote: Lote
    ) -> tuple[Any, dict | None]:
        try:
            contexto = await self._arcgis.consultar_contexto_tematico(
                lote.centroid.lng, lote.centroid.lat
            )
        except (Fuente5xxError, Fuente4xxError, FuenteDatosInvalidosError) as exc:
            return None, _error_de_fuente(exc)
        return contexto, None

    async def _consultar_upl_por_punto(self, lng: float, lat: float) -> dict[str, Any]:
        """Fallback de get_upl por coordenadas: capa UPL consultada por el punto.

        Se activa cuando el punto de entrada es ambiguo (limite entre lotes). La
        capa UPL intersecta por geometria, sin depender de la identidad del lote.
        Mismo manejo de errores que el flujo principal: 5xx -> FUENTE_5XX
        (FR-009); sin dato -> LOTE_SIN_UPL (FR-007).
        """
        try:
            upl = await self._upl.consultar_upl_por_punto(lng, lat)
        except Exception as exc:
            return _error_de_fuente(exc)
        return _respuesta_upl(upl, metodo="punto_directo")

    async def _resolver_por_direccion(
        self, direccion: str, *, incluir_contexto: bool = True
    ) -> tuple[Lote | None, dict | None]:
        """Resuelve un lote por dirección geocodificada.

        Returns (lote, error_dict). error_dict is None on success.
        When multiple candidates exist, returns (None, multiples_dict) with the
        candidates response from _respuesta_multiples_candidatos.
        """
        if not self._mapas.tiene_api_key():
            return None, construir_error(CodigoError.CREDENCIAL_FALTANTE)
        try:
            candidatos = await self._mapas.geocodificar(direccion.strip())
        except (Fuente5xxError, Fuente4xxError, FuenteDatosInvalidosError, CredencialFaltanteError) as exc:
            if isinstance(exc, CredencialFaltanteError):
                return None, construir_error(CodigoError.CREDENCIAL_FALTANTE)
            return None, _error_de_fuente(exc)
        if not candidatos:
            return None, construir_error(CodigoError.DIRECCION_NO_LOCALIZADA)
        if len(candidatos) > 1:
            return None, self._respuesta_multiples_candidatos(candidatos)
        lote, error = await self._resolver_lote_por_candidato(
            candidatos[0], incluir_contexto=incluir_contexto
        )
        return lote, error

    def _respuesta_multiples_candidatos(
        self, candidatos: list[CandidatoDireccion]
    ) -> dict[str, Any]:
        """Presenta los candidatos sin elegir uno arbitrariamente (Historia 2)."""
        return {
            "multiples_candidatos": True,
            "candidatos": [
                {
                    "direccion_normalizada": candidato.direccion_normalizada,
                    "centroid": {"lat": candidato.lat, "lng": candidato.lng},
                }
                for candidato in candidatos
            ],
            "mensaje": "La dirección tiene varios candidatos. Refina la dirección para elegir uno.",
            "source_trace": self._mapas.construir_trace("geocodificar").model_dump(),
        }

    @staticmethod
    def _error_chip_no_encontrado(chip: str) -> dict[str, Any]:
        return construir_error(
            CodigoError.LOTE_NO_ENCONTRADO,
            message="No se encontró ningún lote para el CHIP {chip}. Verifica el identificador.",
            chip=chip,
        )


# --- Limite de entrada: validaciones FR-012 (fail-fast) ---


def _error_de_fuente(exc: BaseException) -> dict[str, Any]:
    """Traduce un error tipado del provider a la respuesta canonica de la tool.

    Clasificacion (decision A2): 5xx (HTTP o code del body) -> FUENTE_5XX; 4xx ->
    PARAMETROS_INVALIDOS con mensaje que identifica la fuente y el status; payload
    inutilizable -> FUENTE_5XX descriptivo. Ninguna de estas se confunde con
    "no encontrado" (FR-009).
    """
    if isinstance(exc, Fuente5xxError):
        return construir_error(
            CodigoError.FUENTE_5XX, source_name=exc.source_name, status=exc.status
        )
    if isinstance(exc, UplNoEncontradaError):
        return construir_error(
            CodigoError.LOTE_SIN_UPL,
            source_name=exc.source_name,
            codigo_catastral=exc.codigo_catastral,
        )
    if isinstance(exc, FuenteDatosInvalidosError):
        return construir_error(
            CodigoError.FUENTE_5XX,
            message="La fuente {source_name} devolvió datos no válidos: {detalle}.",
            source_name=exc.source_name,
            detalle=exc.detail,
        )
    if isinstance(exc, Fuente4xxError):
        detalle = f": {exc.detail}" if exc.detail else ""
        return construir_error(
            CodigoError.PARAMETROS_INVALIDOS,
            message=(
                "Parámetros inválidos: la fuente {source_name} rechazó la consulta "
                "(error {status}){detalle}."
            ),
            source_name=exc.source_name,
            status=exc.status,
            detalle=detalle,
        )
    if isinstance(exc, CorpusNoIngestadoError):
        # Estado de infraestructura (data-model.md:247): no es "sin resultados" ni
        # un fallo de la fuente; se reporta CORPUS_NO_INGESTADO con mensaje accionable.
        return construir_error(
            CodigoError.CORPUS_NO_INGESTADO,
            source_name=exc.source_name,
        )
    if isinstance(exc, OllamaNoDisponibleError):
        return construir_error(
            CodigoError.OLLAMA_NO_DISPONIBLE,
            source_name=exc.source_name,
            modelo=exc.modelo if exc.modelo else "requerido",
        )
    raise exc  # error inesperado: fail loud, no se enmascara


def _respuesta_upl(upl, metodo: str) -> dict[str, Any]:
    """Respuesta de exito de get_upl con el metodo de resolucion usado.

    `metodo` documenta como se resolvio la UPL: "centroide_lote" (flujo normal,
    lote resuelto por F1) o "punto_directo" (fallback por punto de entrada).
    """
    return {
        "metodo_resolucion": metodo,
        "upl": {
            "codigo": upl.codigo_upl,
            "nombre": upl.nombre,
            "localidad": upl.localidad_derivada,
        },
        "trazabilidad": upl.source_trace.model_dump() if upl.source_trace else None,
    }


def _validar_chip(chip: Any) -> dict | None:
    if not isinstance(chip, str) or not PATRON_CHIP.fullmatch(chip):
        return construir_error(
            CodigoError.PARAMETROS_INVALIDOS,
            message="Parámetros inválidos: el CHIP debe tener 11 caracteres alfanuméricos.",
        )
    return None


def _validar_direccion(direccion: Any) -> dict | None:
    """Validacion de direccion uniforme en las 3 tools que la aceptan (hallazgo m4).

    Mismas reglas FR-012 para resolve_lot_by_address, get_upl y
    get_feasibility_report: no vacia y maximo DIRECCION_MAX_CHARS caracteres.
    """
    if not isinstance(direccion, str) or not direccion.strip():
        return construir_error(
            CodigoError.PARAMETROS_INVALIDOS,
            message="Parámetros inválidos: la dirección no puede estar vacía.",
        )
    if len(direccion.strip()) > DIRECCION_MAX_CHARS:
        return construir_error(
            CodigoError.PARAMETROS_INVALIDOS,
            message=(
                f"Parámetros inválidos: la dirección no puede superar "
                f"{DIRECCION_MAX_CHARS} caracteres."
            ),
        )
    return None


def _validar_coordenadas(latitude: Any, longitude: Any) -> dict | None:
    if not _es_numero(latitude) or not _es_numero(longitude):
        return construir_error(
            CodigoError.PARAMETROS_INVALIDOS,
            message="Parámetros inválidos: latitud y longitud deben ser numéricos.",
        )
    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        return construir_error(
            CodigoError.PARAMETROS_INVALIDOS,
            message="Parámetros inválidos: latitud debe estar entre -90 y 90 y longitud entre -180 y 180.",
        )
    return None


# --- Serializacion a los contratos ---


def _lote_a_contrato(lote: Lote) -> dict[str, Any]:
    return {
        "chip": lote.chip,
        "codigo_catastral": lote.codigo_catastral,
        "manzana": lote.manzana,
        "direccion_normalizada": lote.direccion_normalizada,
        "barrio": lote.barrio,
        "geometry": lote.geometry,
        "centroid": lote.centroid.model_dump(),
        "source_trace": lote.source_trace.model_dump(),
    }


def _identidad_a_contrato(lote: Lote) -> dict[str, Any]:
    """Identidad del resumen: descriptiva, omite geometry deliberadamente (FR-011)."""
    return {
        "chip": lote.chip,
        "codigo_catastral": lote.codigo_catastral,
        "manzana": lote.manzana,
        "direccion_normalizada": lote.direccion_normalizada,
        "centroid": lote.centroid.model_dump(),
        "source_trace": lote.source_trace.model_dump(),
    }


# --- Feature 3: serializacion del informe de factibilidad ---


# _ahora_iso y _formatear_numero viven en app/utilidades.py (hallazgo m7).


def _mensaje_fallos(fallos: list[FalloCapa]) -> str:
    """Causa legible de los fallos de capa de un bloque multifuente (FR-009).

    Un bloque con capas caidas NUNCA se reporta como "no encontrado" silencioso:
    este mensaje alimenta el warning BLOQUE_DEGRADADO con la fuente y la causa
    real de cada capa que fallo.
    """
    return "; ".join(
        f"error al consultar la capa {fallo.source_name} ({fallo.detalle})"
        for fallo in fallos
    )


# --- Helper de construccion de bloques con patron de degradacion (FR-012) ---
# Patrin comun de los bloques F6/F7/Fase3: este helper elimina la duplicacion
# estructural (isinstance, unpack, tiene_datos, warnings, bloque construction)
# y deja la logica especifica de cada bloque en lambdas/funciones pequenas.


def _construir_bloque_degradable(
    nombre: str,
    *,
    dato: Any,
    trace: Any,
    trazas: list | None,
    fallos: list | None,
    tiene_datos_fn: Callable[[Any], bool],
    interpretacion_fn: Callable[[Any, bool], str],
    bloque_class: type,
    tiene_source_traces: bool = True,
    warnings: list[dict[str, str]],
    msg_degradado: str | None = None,
    msg_no_encontrado: str | None = None,
) -> Any:
    """Construye un bloque con patron de degradacion independiente (FR-012).

    Patron comun de los bloques F6/F7/Fase3:
    - fallos + sin datos -> no_encontrado + BLOQUE_DEGRADADO
    - fallos + con datos -> disponible + BLOQUE_DEGRADADO parcial
    - sin fallos + sin datos -> no_encontrado + BLOQUE_SIN_DATO
    - sin fallos + con datos -> disponible

    El caller debe manejar separadamente el caso isinstance(result, BaseException)
    para poder hacer ``return _error_de_fuente(result)`` (fail loud).

    Args:
        nombre: Nombre del bloque (e.g. "geotechnical_risks")
        dato: Dato desempaquetado de la tupla del provider
        trace: SourceTrace principal del bloque
        trazas: Lista de source_traces (None si el bloque no las soporta)
        fallos: Lista de FalloCapa (None o vacia = sin fallos)
        tiene_datos_fn: Callable(dato) -> bool; evalua si hay datos reales
        interpretacion_fn: Callable((dato, tiene_datos)) -> str; genera texto
        bloque_class: Clase Pydantic del bloque
        tiene_source_traces: Si el bloque soporta source_traces (True por defecto)
        warnings: Lista de warnings a la que se anexan los generados
        msg_degradado: Interpretacion cuando fallos + sin datos (override)
        msg_no_encontrado: Detalle del BLOQUE_SIN_DATO (override)
    """
    tiene_datos = tiene_datos_fn(dato)
    tiene_fallos = bool(fallos)

    if tiene_fallos and not tiene_datos:
        warnings.append({
            "codigo": "BLOQUE_DEGRADADO",
            "mensaje": f"Bloque {nombre} degradado: {_mensaje_fallos(fallos)}.",
        })
        kwargs: dict[str, Any] = dict(
            estado="no_encontrado",
            interpretation=msg_degradado or f"No se pudieron consultar los datos de {nombre}.",
            source_trace=trace,
        )
        if tiene_source_traces and trazas is not None:
            kwargs["source_traces"] = trazas
        return bloque_class(**kwargs)

    if tiene_fallos:
        warnings.append({
            "codigo": "BLOQUE_DEGRADADO",
            "mensaje": f"Bloque {nombre} degradado parcialmente: {_mensaje_fallos(fallos)}.",
        })

    interpretacion = interpretacion_fn(dato, tiene_datos)

    if not tiene_datos and not tiene_fallos:
        detalle = msg_no_encontrado or f"no se hallaron datos de {nombre} para el lote."
        warnings.append({
            "codigo": "BLOQUE_SIN_DATO",
            "mensaje": f"Bloque {nombre} no encontrado: {detalle}",
        })

    kwargs = dict(
        estado="disponible" if tiene_datos else "no_encontrado",
        dato=dato if tiene_datos else None,
        interpretation=interpretacion,
        source_trace=trace,
    )
    if tiene_source_traces and trazas is not None:
        kwargs["source_traces"] = trazas
    return bloque_class(**kwargs)


# --- Funciones de interpretacion por bloque (usadas por _construir_bloque_degradable) ---


def _interpretar_geotecnia(dato: Any, tiene_datos: bool) -> str:
    if not tiene_datos:
        return "No se encontraron datos geotécnicos para el lote en la fuente consultada."
    partes = []
    if dato.amenaza_movimientos:
        partes.append(f"amenaza: {dato.amenaza_movimientos}")
    if dato.geologia:
        partes.append(f"geología: {dato.geologia}")
    if dato.respuesta_sismica:
        partes.append(f"sísmica: {dato.respuesta_sismica}")
    if dato.zonificacion_geotecnica:
        partes.append(f"zonificación: {dato.zonificacion_geotecnica}")
    return f"Clasificación geotécnica del lote: {', '.join(partes)}."


def _interpretar_socio(dato: Any, tiene_datos: bool) -> str:
    if not tiene_datos:
        return "No se encontraron datos socioeconómicos para el lote en la fuente consultada."
    partes = []
    if dato.estrato is not None:
        partes.append(f"estrato {dato.estrato}")
    if dato.uso_predominante:
        partes.append(f"uso: {dato.uso_predominante}")
    if dato.altura_media is not None:
        partes.append(f"altura media: {_formatear_numero(dato.altura_media)} pisos")
    if dato.mediana_avaluo is not None:
        partes.append(
            f"avalúo catastral mediano: {_formatear_numero(dato.mediana_avaluo)} COP"
        )
    if partes:
        return f"Contexto socioeconómico del lote: {', '.join(partes)}."
    return "No se encontraron datos socioeconómicos para el lote en la fuente consultada."


def _interpretar_regulatorio(dato: Any, tiene_datos: bool) -> str:
    if not tiene_datos:
        return "No se encontraron datos regulatorios para el lote en la fuente consultada."
    partes = []
    if dato.licencias_encontradas is not None:
        plural_lic = "s" if dato.licencias_encontradas != 1 else ""
        partes.append(
            f"{dato.licencias_encontradas} licencia{plural_lic} aprobada{plural_lic}"
        )
    if dato.zona_plusvalia is True:
        detalle_plan = ""
        if dato.nombre_plan_plusvalia:
            detalle_plan = f" ({dato.nombre_plan_plusvalia})"
        partes.append(f"zona de plusvalía{detalle_plan}")
    if partes:
        return f"Entorno regulatorio del lote: {', '.join(partes)}."
    return "No se encontraron datos regulatorios para el lote en la fuente consultada."


def _interpretar_patrimonio(dato: Any, tiene_datos: bool) -> str:
    if not tiene_datos:
        return (
            "No se encontraron elementos de patrimonio cultural para el lote "
            "en la fuente consultada."
        )
    partes = []
    if dato.bic_cercano is True:
        detalle_bic = ""
        if dato.nombre_bic:
            detalle_bic = f" ({dato.nombre_bic})"
        partes.append(f"BIC cercano{detalle_bic}")
    if dato.zona_arqueologica is True:
        partes.append("zona arqueológica")
    if partes:
        return f"Patrimonio cultural del lote: {', '.join(partes)}."
    return (
        "No se encontraron elementos de patrimonio cultural para el lote "
        "en la fuente consultada."
    )


def _interpretar_movilidad(dato: Any, tiene_datos: bool) -> str:
    if not tiene_datos:
        return (
            "No se encontraron estaciones de transporte público cercanas al lote "
            "en la fuente consultada."
        )
    partes = []
    if dato.estaciones_transmilenio is not None:
        plural_tm = "s" if dato.estaciones_transmilenio != 1 else ""
        partes.append(
            f"{dato.estaciones_transmilenio} estación{plural_tm} TransMilenio"
        )
    if dato.paraderos_sitp is not None:
        plural_sitp = "s" if dato.paraderos_sitp != 1 else ""
        partes.append(
            f"{dato.paraderos_sitp} paradero{plural_sitp} SITP"
        )
    if dato.estaciones_metro is not None:
        plural_metro = "s" if dato.estaciones_metro != 1 else ""
        partes.append(
            f"{dato.estaciones_metro} estación{plural_metro} Metro"
        )
    if dato.estacion_cercana:
        partes.append(f"estación más cercana: {dato.estacion_cercana}")
    if partes:
        return f"Acceso a transporte público del lote: {', '.join(partes)}."
    return (
        "No se encontraron estaciones de transporte público cercanas al lote "
        "en la fuente consultada."
    )


def _interpretar_catastro(dato: Any, tiene_datos: bool) -> str:
    if not tiene_datos:
        return (
            "No se encontraron datos catastrales adicionales para el lote "
            "en la fuente consultada."
        )
    partes = []
    if dato.sector_catastral:
        partes.append(f"sector: {dato.sector_catastral}")
    if dato.manzana:
        codigo_mz = dato.manzana.get("codigo_manzana")
        if codigo_mz:
            partes.append(f"manzana: {codigo_mz}")
    if dato.densidad_predial:
        num_predios = dato.densidad_predial.get("num_predios")
        if num_predios is not None:
            partes.append(f"predios en manzana: {int(num_predios)}")
    if dato.construccion:
        pisos = dato.construccion.get("pisos")
        if pisos is not None:
            partes.append(f"pisos: {int(pisos)}")
    if dato.variacion_area:
        periodo = dato.variacion_area.get("periodo")
        if periodo:
            partes.append(f"variación: {periodo}")
    if partes:
        return f"Datos catastrales del lote: {', '.join(partes)}."
    return (
        "No se encontraron datos catastrales adicionales para el lote "
        "en la fuente consultada."
    )


def _interpretar_espacio_publico(dato: Any, tiene_datos: bool) -> str:
    if not tiene_datos:
        return (
            "No se encontró un indicador de espacio público para la UPL del lote "
            "en la fuente consultada."
        )
    ept_texto = _formatear_numero(dato.ep_total_m2_hab or 0.0)
    upl_ep_texto = dato.nombre_upl or dato.codigo_upl or "la UPL"
    return (
        f"Espacio público total efectivo de {upl_ep_texto}: "
        f"{ept_texto} m²/habitante."
    )


def _interpretar_red_vial(dato: Any, tiene_datos: bool) -> str:
    if not tiene_datos:
        return (
            "No se encontraron ejes viales en el entorno inmediato del lote "
            "en la fuente consultada."
        )
    primera_via = dato.vias_frente[0]
    detalle_via = primera_via.nombre_via or primera_via.tipo_via or "vía sin nombre"
    jerarquia_texto = dato.jerarquia_maxima or "desconocida"
    return (
        f"Frente vial del lote: {len(dato.vias_frente)} vía(s) en el "
        f"entorno inmediato; la principal es {detalle_via} con jerarquía "
        f"derivada {jerarquia_texto}."
    )


def _interpretar_equipamientos(dato: Any, tiene_datos: bool) -> str:
    if not tiene_datos:
        return (
            "No se encontraron equipamientos de salud, educación o cultura "
            "en los radios consultados."
        )
    partes = []
    for tipo, total in (
        ("salud", dato.total_salud),
        ("educación", dato.total_educacion),
        ("cultura", dato.total_cultura),
    ):
        if total is not None:
            plural_tipo = "s" if total != 1 else ""
            partes.append(f"{total} de {tipo}{plural_tipo}")
    detalle_cercano = ""
    if dato.mas_cercano is not None and dato.mas_cercano.nombre:
        distancia_texto = (
            f" ({int(dato.mas_cercano.distancia_m)} m)"
            if dato.mas_cercano.distancia_m is not None
            else ""
        )
        detalle_cercano = (
            f"; el más cercano: {dato.mas_cercano.nombre}"
            f"{distancia_texto}"
        )
    return (
        f"Equipamientos cercanos al lote: {', '.join(partes)}"
        f"{detalle_cercano}."
    )


# Nombres de bloque reconocibles en el mensaje de un warning (patron
# "Bloque <nombre> ..."): alimenta el resumen llm_ready_summary sin depender
# de una lista manual que podria desincronizarse.
_PATRON_BLOQUE_EN_WARNING = re.compile(r"Bloque ([a-z_]+)")


def _construir_llm_ready_summary(
    *,
    lote: Lote,
    upl: UPL | None,
    localidad: Localidad | None,
    clasificacion_suelo: str | None,
    score: FeasibilityScore,
    warnings: list[dict[str, str]],
) -> str:
    """Resumen en espanol del informe generado DETERMINISTICAMENTE (sin LLM).

    Un parrafo normalizado con identidad del lote, UPL/localidad/suelo, score,
    confidence y bloques degradados o sin dato (derivados de los warnings por
    regex, no de una lista manual). Pensado para pegar en cualquier LLM
    evaluador; mismo input -> mismo texto (SC-003).
    """
    chip_texto = lote.chip if lote.chip is not None else "sin CHIP"
    direccion_texto = lote.direccion_normalizada or "no disponible"
    partes = [
        (
            f"Lote {lote.codigo_catastral} (CHIP {chip_texto}), manzana "
            f"{lote.manzana}, dirección {direccion_texto}"
        )
    ]
    if lote.barrio:
        partes.append(f"barrio {lote.barrio}")
    if upl is not None:
        partes.append(f"UPL {upl.codigo_upl} {upl.nombre}")
    if localidad is not None:
        partes.append(f"localidad {localidad.nombre}")
    if clasificacion_suelo is not None:
        partes.append(f"suelo {clasificacion_suelo}")
    resumen = f"{', '.join(partes)}. "

    confidence_es = {"high": "alta", "medium": "media", "low": "baja"}[score.confidence]
    resumen += (
        f"Score de factibilidad {score.score}/100 con confianza {confidence_es}."
    )

    bloques_con_problema: list[str] = []
    for warning in warnings:
        match = _PATRON_BLOQUE_EN_WARNING.search(warning.get("mensaje", ""))
        if match and match.group(1) not in bloques_con_problema:
            bloques_con_problema.append(match.group(1))
    if bloques_con_problema:
        resumen += (
            " Bloques degradados o sin datos: "
            + ", ".join(bloques_con_problema)
            + "."
        )
    return resumen


def _trace_upl_por_defecto() -> dict[str, str]:
    """Traza de la capa UPL cuando no hay dato (espejo de _configuracion_upl en app/providers/upl.py).

    ContextoAdministrativo exige source_trace de 5 campos siempre (FR-010); si la
    UPL no se resolvio, esta traza documenta la capa consultada sin resultado.
    """
    return {
        "source_name": "IDECA Catastro — Unidad de Planeamiento Local",
        "layer_id": "0",
        "service_url": f"{RAIZ_ARCGIS}/ordenamientoterritorial/unidadplaneamientolocal/MapServer",
        "data_vigencia": VIGENCIA_UPL_DEFAULT,
        "query_timestamp": _ahora_iso(),
    }


def _trace_corpus_por_defecto() -> dict[str, str]:
    """Traza del corpus cuando el RAG no responde (espejo de NormativaProvider._construir_trace)."""
    return {
        "source_name": CORPUS_SOURCE_NAME,
        "layer_id": CORPUS_LAYER_ID,
        "service_url": CORPUS_SERVICE_URL,
        "data_vigencia": CORPUS_VIGENCIA,
        "query_timestamp": _ahora_iso(),
    }


def _upl_a_contrato(upl: UPL) -> dict[str, Any]:
    """Shape del contrato para el objeto UPL anidado (codigo, nombre, vocacion, source_trace)."""
    return {
        "codigo": upl.codigo_upl,
        "nombre": upl.nombre,
        "vocacion": upl.vocacion,
        "source_trace": (
            upl.source_trace.model_dump() if upl.source_trace is not None else _trace_upl_por_defecto()
        ),
    }


def _contexto_administrativo_a_contrato(contexto: ContextoAdministrativo) -> dict[str, Any]:
    """Bloque administrative_context: UPL/localidad/clasificacion + traza de la capa UPL."""
    return {
        "upl": _upl_a_contrato(contexto.upl) if contexto.upl is not None else None,
        "localidad": (
            contexto.localidad.model_dump() if contexto.localidad is not None else None
        ),
        "clasificacion_suelo": contexto.clasificacion_suelo,
        "source_trace": contexto.source_trace.model_dump(),
    }


def _construir_prompt_parametros_urbanisticos(
    tratamiento: str, upl_codigo: str | None
) -> str:
    """Genera el prompt para el RAG que extrae COS, CUS, altura, retiros y estacionamientos.

    Contrato (contracts/urbanistic-parameters.md:Consulta RAG): prompt con el
    nombre del tratamiento y la UPL para extraer parámetros numéricos del POT.
    """
    partes = [
        (
            f'¿Cuáles son los valores de COS, CUS, altura máxima (en metros), '
            f'retiros frontales, laterales y posteriores (en metros), '
            f'y estacionamientos requeridos para un lote con tratamiento '
            f'urbanístico "{tratamiento}"'
        ),
    ]
    if upl_codigo:
        partes.append(f"en la UPL {upl_codigo}")
    partes.append(
        "? Cita los artículos y valores exactos del POT."
    )
    return " ".join(partes)


def _parsear_parametros_rag(respuesta_rag: str) -> dict[str, Any]:
    """Extrae valores numéricos de la respuesta del RAG con regex determinista.

    Contrato (contracts/urbanistic-parameters.md:Parsing regex): 7 patrones
    que extraen COS, CUS, altura, retiros frontales/laterales/posteriores y
    estacionamientos desde el texto del LLM. Los patrones de retiros aceptan
    singular y plural ("retiro lateral" / "retiros laterales", "posterior" /
    "posteriores") para tolerar la formulación del LLM (hallazgo m2). Antes de
    extraer se NORMALIZA la coma decimal a punto ("0,5" -> "0.5", nitpick
    Fase 5): los LLM en español a veces responden con coma decimal y sin esta
    normalización el valor se perdería. Si un patrón no matchea, el campo
    queda None (FR-014: sin LLM para interpretaciones).
    """
    texto_normalizado = respuesta_rag.replace(",", ".")
    cos = _extraer_float_patron(texto_normalizado, r"COS[:\s]+(\d+\.?\d*)")
    cus = _extraer_float_patron(texto_normalizado, r"CUS[:\s]+(\d+\.?\d*)")
    altura = _extraer_float_patron(texto_normalizado, r"altura[:\s]+(\d+\.?\d*)\s*m")
    frontal = _extraer_float_patron(
        texto_normalizado, r"(?:frontales|frontal)[:\s]+(\d+\.?\d*)\s*m"
    )
    laterales = _extraer_float_patron(
        texto_normalizado, r"(?:laterales|lateral)[:\s]+(\d+\.?\d*)\s*m"
    )
    posterior = _extraer_float_patron(
        texto_normalizado, r"(?:posteriores|posterior)[:\s]+(\d+\.?\d*)\s*m"
    )
    estacionamientos = _extraer_int_patron(texto_normalizado, r"(\d+)\s*estacionamiento")
    return {
        "cos": cos,
        "cus": cus,
        "altura_maxima_m": altura,
        "frontal_m": frontal,
        "laterales_m": laterales,
        "posteriores_m": posterior,
        "estacionamientos_requeridos": estacionamientos,
    }


def _extraer_float_patron(texto: str, patron: str) -> float | None:
    """Extrae un float desde un patrón regex (retorna None si no matchea)."""
    match = re.search(patron, texto, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            return None
    return None


def _extraer_int_patron(texto: str, patron: str) -> int | None:
    """Extrae un entero desde un patrón regex (retorna None si no matchea)."""
    match = re.search(patron, texto, re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None
    return None


def _trace_sdp_de_config(config: Any) -> SourceTrace:
    """SourceTrace de fallback desde una CapaConfig del provider SDP (SC-002).

    Usado cuando el bloque se degrada y no hay trace de una consulta exitosa;
    evita acceder a atributos privados del provider (hallazgo m4).
    """
    return SourceTrace(
        source_name=config.source_name,
        layer_id=config.layer_id,
        service_url=config.service_url,
        data_vigencia=config.data_vigencia,
        query_timestamp=_ahora_iso(),
    )


def _bloque_urbanistic_degradado(
    provider_sdp: SDPProvider,
    warnings: list[dict[str, str]],
    causa: str,
) -> BloqueParametrosUrbanisticos:
    """Bloque urbanistic_parameters en estado no_encontrado por fallo de SDP.

    Emite warning BLOQUE_DEGRADADO con la causa registrada (FR-009 enmendada,
    FR-016) y retorna el bloque con traza de fallback; nunca es fatal para el
    resto del informe (FR-008, SC-004).
    """
    warnings.append({
        "codigo": "BLOQUE_DEGRADADO",
        "mensaje": f"Bloque urbanistic_parameters degradado: {causa}.",
    })
    return BloqueParametrosUrbanisticos(
        estado="no_encontrado",
        interpretation="No se encontró un tratamiento urbanístico para el lote en la fuente consultada.",
        source_trace=_trace_sdp_de_config(provider_sdp.configuracion_tratamiento()),
    )


def _extraer_criterio_normativo(texto_rag: str) -> str | None:
    """Extrae la referencia normativa presente en la respuesta del RAG (FR-015).

    El criterio de estacionamientos DEBE derivarse del texto real del RAG
    (data-model.md:EstacionamientosRequeridos); nunca se hardcodea. Retorna
    None si el texto no cita ninguna referencia verificable.
    """
    referencia_completa = re.search(
        r"[Aa]rt[íi]culo\s+\d+\s+del\s+Decreto\s+[\d/]+", texto_rag
    )
    if referencia_completa:
        return referencia_completa.group(0)
    referencia_simple = re.search(r"[Aa]rt[íi]culo\s+\d+", texto_rag)
    if referencia_simple:
        return referencia_simple.group(0)
    return None


async def _bloque_parametros_urbanisticos(
    lng: float,
    lat: float,
    provider_sdp: SDPProvider,
    provider_normativa: NormativaProvider,
    upl_codigo: str | None,
    warnings: list[dict[str, str]],
) -> BloqueParametrosUrbanisticos:
    """Construye el bloque urbanistic_parameters con degradación independiente.

    Orquestación (T016, plan.md Phase 3):
    1. Consulta SDP capa 2 (tratamiento espacial): fallo → BLOQUE_DEGRADADO;
       respuesta sin features/denominación → BLOQUE_SIN_DATO (contrato:62-67)
    2. Si tratamiento OK → consulta RAG normativo para parámetros numéricos;
       fallo del RAG → warning BLOQUE_DEGRADADO sin perder el tratamiento
       (FR-008, FR-016)
    3. Consulta capa 14 SINUPOT (edificabilidad oficial, FR-006/FR-021): sus
       valores tienen precedencia sobre el parsing RAG; los campos que la capa
       no entregue se complementan con el RAG. Degradación independiente.
    4. Parsing regex determinista de la respuesta (FR-014)

    Contrato (contracts/urbanistic-parameters.md:Degradación por fuente).
    """
    # --- 1. SDP capa 2: tratamiento espacial ---
    try:
        tratamiento, trace_sdp = await provider_sdp.consultar_tratamiento(lng, lat)
    except (Fuente5xxError, Fuente4xxError):
        return _bloque_urbanistic_degradado(
            provider_sdp, warnings, "error al consultar la capa SINUPOT/SDP"
        )
    except Exception:
        return _bloque_urbanistic_degradado(
            provider_sdp, warnings, "error inesperado al consultar la capa SINUPOT/SDP"
        )

    if tratamiento is None:
        # SDP responde pero sin features/denominación → BLOQUE_SIN_DATO (FR-016)
        warnings.append({
            "codigo": "BLOQUE_SIN_DATO",
            "mensaje": (
                "Bloque urbanistic_parameters sin dato: la capa SINUPOT/SDP "
                "no reporta tratamiento urbanístico para el lote."
            ),
        })
        return BloqueParametrosUrbanisticos(
            estado="no_encontrado",
            interpretation="No se encontró un tratamiento urbanístico para el lote en la fuente consultada.",
            source_trace=_trace_sdp_de_config(provider_sdp.configuracion_tratamiento()),
        )

    # --- 2. RAG normativo: parámetros numéricos (FR-003, FR-018) ---
    prompt_rag = _construir_prompt_parametros_urbanisticos(
        tratamiento.denominacion, upl_codigo
    )
    respuesta_texto = ""
    parametros_rag: dict[str, Any] | None = None
    try:
        resultado_normativa = await provider_normativa.consultar(
            consulta=prompt_rag, upl=upl_codigo, top_k=3
        )
        respuesta_texto = resultado_normativa.get("respuesta", "")
        parametros_rag = _parsear_parametros_rag(respuesta_texto)
    except (CorpusNoIngestadoError, OllamaNoDisponibleError):
        # Fallo de infraestructura del RAG → warning BLOQUE_DEGRADADO (FR-016);
        # el tratamiento se conserva y los campos numéricos quedan en None (FR-008).
        warnings.append({
            "codigo": "BLOQUE_DEGRADADO",
            "mensaje": (
                "Bloque urbanistic_parameters degradado: el RAG normativo no "
                "está disponible (corpus no ingestado u Ollama caído); los "
                "parámetros numéricos quedan en None."
            ),
        })
    except Exception:
        warnings.append({
            "codigo": "BLOQUE_DEGRADADO",
            "mensaje": (
                "Bloque urbanistic_parameters degradado: error inesperado al "
                "consultar el RAG normativo; los parámetros numéricos quedan "
                "en None."
            ),
        })

    # --- 3. Capa 14 SINUPOT: edificabilidad oficial (FR-006, FR-021) ---
    # Los valores oficiales de la capa tienen precedencia sobre el parsing RAG;
    # los campos que la capa no entregue se complementan con el RAG. La capa 14
    # es complementaria: su ausencia de features NO genera warning (no es una
    # fuente requerida del bloque), pero su fallo sí (degradación independiente).
    cos_capa14 = cus_capa14 = altura_capa14 = None
    try:
        edif_capa14, _ = await provider_sdp.consultar_edificabilidad(lng, lat)
        if edif_capa14 is not None:
            cos_capa14 = edif_capa14.cos
            cus_capa14 = edif_capa14.cus
            altura_capa14 = edif_capa14.altura_maxima_m
    except (Fuente5xxError, Fuente4xxError):
        warnings.append({
            "codigo": "BLOQUE_DEGRADADO",
            "mensaje": (
                "Bloque urbanistic_parameters degradado parcialmente: error al "
                "consultar la capa de edificabilidad (layer 14) del SINUPOT."
            ),
        })
    except Exception:
        warnings.append({
            "codigo": "BLOQUE_DEGRADADO",
            "mensaje": (
                "Bloque urbanistic_parameters degradado parcialmente: error "
                "inesperado al consultar la capa de edificabilidad (layer 14)."
            ),
        })

    cos = cos_capa14 if cos_capa14 is not None else (parametros_rag or {}).get("cos")
    cus = cus_capa14 if cus_capa14 is not None else (parametros_rag or {}).get("cus")
    altura = (
        altura_capa14
        if altura_capa14 is not None
        else (parametros_rag or {}).get("altura_maxima_m")
    )
    frontal = (parametros_rag or {}).get("frontal_m")
    laterales = (parametros_rag or {}).get("laterales_m")
    posterior = (parametros_rag or {}).get("posteriores_m")
    estacionamientos_req = (parametros_rag or {}).get("estacionamientos_requeridos")

    tiene_datos_numericos = any(
        v is not None
        for v in [cos, cus, altura, frontal, laterales, posterior, estacionamientos_req]
    )

    # --- Interpretación determinista (FR-014) ---
    if not tiene_datos_numericos:
        interpretation = (
            f"Tratamiento urbanístico del lote: {tratamiento.denominacion}. "
            "Los parámetros numéricos (COS, CUS, altura, retiros, estacionamientos) "
            "no están disponibles en el corpus normativo."
        )
    else:
        partes = [
            f"Tratamiento urbanístico del lote: {tratamiento.denominacion} "
            f"(SINUPOT layer 2)."
        ]
        if cos is not None:
            partes.append(f"COS: {cos}")
        if cus is not None:
            partes.append(f"CUS: {cus}")
        if altura is not None:
            partes.append(f"altura máxima: {altura} m")
        interpretation = " ".join(partes)

    # --- Sub-modelos ---
    # Edificabilidad solo si hay al menos un valor real (capa 14 o RAG): si los
    # tres campos son None el sub-modelo queda en None y la regla +10 del
    # scoring (r_parametros_urbanisticos) no se activa (hallazgo M6).
    edificabilidad = (
        ParametrosEdificabilidad(cos=cos, cus=cus, altura_maxima_m=altura)
        if any(v is not None for v in (cos, cus, altura))
        else None
    )
    retiros = RetirosLote(
        frontal_m=frontal, laterales_m=laterales, posteriores_m=posterior
    )
    criterio = (
        _extraer_criterio_normativo(respuesta_texto)
        if estacionamientos_req is not None
        else None
    )
    estacionamientos = EstacionamientosRequeridos(
        requeridos=estacionamientos_req,
        criterio=criterio,
    )

    dato = ParametrosUrbanisticos(
        tratamiento=tratamiento,
        edificabilidad=edificabilidad,
        retiros=retiros,
        estacionamientos=estacionamientos,
    )

    return BloqueParametrosUrbanisticos(
        estado="disponible",
        dato=dato,
        interpretation=interpretation,
        source_trace=trace_sdp,
    )


def _construir_consulta_automatica(
    upl: UPL | None,
    localidad: Localidad | None,
    clasificacion_suelo: str | None,
) -> str:
    """Consulta normativa automatica desde el contexto del lote (contrato:355-357).

    Con UPL: "normas urbanísticas aplicables a la UPL <nombre> (<codigo>), localidad
    <nombre>, clasificación de suelo <clasificacion>". Sin UPL: solo "al lote",
    sin filtro territorial (upl=None en la consulta).
    """
    if upl is not None:
        partes = [f"normas urbanísticas aplicables a la UPL {upl.nombre} ({upl.codigo_upl})"]
    else:
        partes = ["normas urbanísticas aplicables al lote"]
    if localidad is not None:
        partes.append(f"localidad {localidad.nombre}")
    if clasificacion_suelo is not None:
        partes.append(f"clasificación de suelo {clasificacion_suelo}")
    return ", ".join(partes)


def _bloque_a_contrato(
    bloque: Any,
    *,
    extra_dato: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Patron {estado, dato, interpretation, source_trace} de los bloques con estado (FR-004/FR-005).

    El dato se serializa sin los campos anidados estado/source_trace (shape F1
    `a_dato_contrato`); cuando estado=no_encontrado, dato es None (FR-007).
    `extra_dato` anade campos derivados del orquestador (p. ej. radio_m en
    environment_context, research H5).

    Los bloques multifuente (F6/F7) exponen ademas `source_traces`: la
    procedencia por sub-fuente con la vigencia propia de cada capa exitosa
    (hallazgo M4). Los bloques monofuente no definen el campo y no lo publican.
    """
    if bloque.estado == "disponible" and bloque.dato is not None:
        dato = bloque.dato.model_dump(exclude={"estado", "source_trace"}, exclude_none=True)
        if extra_dato:
            dato.update(extra_dato)
    else:
        dato = None
    salida = {
        "estado": bloque.estado,
        "dato": dato,
        "interpretation": bloque.interpretation,
        "source_trace": bloque.source_trace.model_dump(),
    }
    trazas_subfuente = getattr(bloque, "source_traces", None)
    if trazas_subfuente is not None:
        salida["source_traces"] = [traza.model_dump() for traza in trazas_subfuente]
    return salida


# --- Registro del servidor MCP (stdio) ---


def _construir_servidor_lotes() -> ServidorLotes:
    api_key = os.environ.get("MAPAS_BOGOTA_APIKEY")
    return ServidorLotes(
        MapasBogotaProvider(api_key=api_key),
        ArcGISProvider(),
        UPLProvider(),
        NormativaProvider(),
        SDPProvider(),
    )


def crear_servidor_mcp(servidor_lotes: ServidorLotes | None = None) -> _ClaseServidorMCP:
    """Construye el servidor MCP registrando EXACTAMENTE las 7 tools del contrato (4 F1 + 2 F2 + 1 F3).

    Registra un lifespan que cierra los providers (httpx.AsyncClient) al terminar
    el ciclo de vida del servidor MCP (decision A1 punto 3). El lifespan solo
    corre cuando el servidor arranca (mcp.run()); los tests construyen servidores
    con MockTransport y los cierran manualmente via servidor.aclose().
    """
    servidor_lotes = servidor_lotes or _construir_servidor_lotes()

    @asynccontextmanager
    async def _lifespan_cerrar_providers(_server: Any):
        try:
            yield
        finally:
            await servidor_lotes.aclose()

    mcp = _ClaseServidorMCP(NOMBRE_SERVIDOR, lifespan=_lifespan_cerrar_providers)
    mcp.tool()(servidor_lotes.resolve_lot_by_chip)
    mcp.tool()(servidor_lotes.resolve_lot_by_address)
    mcp.tool()(servidor_lotes.resolve_lot_by_coordinates)
    mcp.tool()(servidor_lotes.get_lot_summary_by_chip)
    mcp.tool()(servidor_lotes.get_upl)
    mcp.tool()(servidor_lotes.consultar_normativa)
    mcp.tool()(servidor_lotes.get_feasibility_report)
    return mcp


servidor_lotes = _construir_servidor_lotes()
mcp = crear_servidor_mcp(servidor_lotes)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
