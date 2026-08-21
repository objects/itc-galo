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
from datetime import datetime, timezone
from typing import Any

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
    BloqueObrasPublicas,
    BloqueParametrosUrbanisticos,
    BloquePatrimonioCultural,
    BloqueReservaVial,
    BloqueRiesgosGeotecnicos,
    BloqueValorReferencia,
    Centroide,
    ContextoAdministrativo,
    ContextoCatastro,
    ContextoSocioeconomico,
    EntornoRegulatorio,
    EvidenciaNormativa,
    EstacionamientosRequeridos,
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
from app.providers.arcgis import ArcGISProvider
from app.providers.arcgis_utils import RAIZ_ARCGIS
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

try:  # mcp >= 1.x: FastMCP
    from mcp.server.fastmcp import FastMCP as _ClaseServidorMCP
except ImportError:  # mcp 2.x renombro FastMCP a MCPServer
    from mcp.server.mcpserver import MCPServer as _ClaseServidorMCP

NOMBRE_SERVIDOR = "mcp-bogota-factibilidad"
PATRON_CHIP = re.compile(r"^[A-Z0-9]{11}$")

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
    ) -> None:
        self._mapas = provider_mapas
        self._arcgis = provider_arcgis
        self._upl = provider_upl
        self._normativa = provider_normativa
        self._sdp = provider_sdp or SDPProvider()

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
        if not isinstance(address, str) or not address.strip():
            return construir_error(
                CodigoError.PARAMETROS_INVALIDOS,
                message="Parámetros inválidos: la dirección no puede estar vacía.",
            )
        if not self._mapas.tiene_api_key():
            return construir_error(CodigoError.CREDENCIAL_FALTANTE)
        try:
            candidatos = await self._mapas.geocodificar(address.strip())
        except (Fuente5xxError, Fuente4xxError, FuenteDatosInvalidosError, CredencialFaltanteError) as exc:
            if isinstance(exc, CredencialFaltanteError):
                return construir_error(CodigoError.CREDENCIAL_FALTANTE)
            return _error_de_fuente(exc)
        if not candidatos:
            return construir_error(CodigoError.DIRECCION_NO_LOCALIZADA)
        if len(candidatos) > 1:
            return self._respuesta_multiples_candidatos(candidatos)
        lote, error = await self._resolver_lote_por_candidato(candidatos[0])
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
        # Consulta catastro data en paralelo (F7)
        try:
            contexto_catastro, trace_catastro = await self._arcgis.consultar_contexto_catastro(
                lote.centroid.lng, lote.centroid.lat
            )
            catastro_disponible = contexto_catastro.construccion is not None or contexto_catastro.manzana is not None or contexto_catastro.densidad_predial is not None or contexto_catastro.variacion_area is not None or contexto_catastro.sector_catastral is not None
        except Exception:
            contexto_catastro = ContextoCatastro()
            trace_catastro = SourceTrace(
                source_name="Catastro — Construcción",
                layer_id="0",
                service_url=f"{RAIZ_ARCGIS}/catastro/construccion/MapServer",
                data_vigencia="2024",
                query_timestamp=_ahora_iso(),
            )
            catastro_disponible = False

        # Consulta parámetros urbanísticos (F8, degradación independiente)
        summary_warnings: list[dict[str, str]] = []
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
            if not isinstance(direccion, str) or not direccion.strip():
                return construir_error(
                    CodigoError.PARAMETROS_INVALIDOS,
                    message="Parámetros inválidos: la dirección no puede estar vacía.",
                )
            if not self._mapas.tiene_api_key():
                return construir_error(CodigoError.CREDENCIAL_FALTANTE)
            try:
                candidatos = await self._mapas.geocodificar(direccion.strip())
            except (Fuente5xxError, Fuente4xxError, FuenteDatosInvalidosError, CredencialFaltanteError) as exc:
                if isinstance(exc, CredencialFaltanteError):
                    return construir_error(CodigoError.CREDENCIAL_FALTANTE)
                return _error_de_fuente(exc)
            if not candidatos:
                return construir_error(CodigoError.DIRECCION_NO_LOCALIZADA)
            if len(candidatos) > 1:
                return self._respuesta_multiples_candidatos(candidatos)
            res = await self._resolver_lote_por_candidato(candidatos[0])
            if isinstance(res, dict) and "error" in res:
                return res
            lote, error = res
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
            if not self._mapas.tiene_api_key():
                return construir_error(CodigoError.CREDENCIAL_FALTANTE)
            try:
                candidatos = await self._mapas.geocodificar(direccion.strip())
            except (
                Fuente5xxError,
                Fuente4xxError,
                FuenteDatosInvalidosError,
                CredencialFaltanteError,
            ) as exc:
                if isinstance(exc, CredencialFaltanteError):
                    return construir_error(CodigoError.CREDENCIAL_FALTANTE)
                return _error_de_fuente(exc)
            if not candidatos:
                return construir_error(CodigoError.DIRECCION_NO_LOCALIZADA)
            if len(candidatos) > 1:
                return construir_error(
                    CodigoError.LOTE_NO_ENCONTRADO,
                    message=(
                        "No se encontró un lote único para la dirección: hay varios "
                        "candidatos. Refina la dirección para elegir uno."
                    ),
                )
            lote, error = await self._resolver_lote_por_candidato(
                candidatos[0], incluir_contexto=False
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
            if nombre_localidad is None:
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
                localidad = Localidad(
                    codigo=_LOCALIDAD_A_CODIGO.get(nombre_localidad, ""),
                    nombre=nombre_localidad,
                )
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
        # Cada bloque degrada independientemente (FR-012): un fallo en una fuente
        # produce un bloque con estado "no_encontrado" y warning, sin interrumpir
        # las demas consultas. Los errores 5xx se propagan como FUENTE_5XX fatal
        # (FR-009) porque return_exceptions captura todas las excepciones.
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
        (
            r_geotecnia,
            r_socio,
            r_regulatorio,
            r_patrimonio,
            r_movilidad,
            r_catastro,
        ) = await asyncio.gather(
            t_geotecnia,
            t_socio,
            t_regulatorio,
            t_patrimonio,
            t_movilidad,
            t_catastro,
            return_exceptions=True,
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
        # Cada bloque degrada independientemente (FR-012): errores tipados del
        # provider se capturan con return_exceptions y producen "no_encontrado"
        # con warning; un 5xx fatal se propagaria como FUENTE_5XX (FR-009).

        # Bloque geotechnical_risks
        if isinstance(r_geotecnia, BaseException):
            bloque_geotecnia = BloqueRiesgosGeotecnicos(
                estado="no_encontrado",
                interpretation="No se pudieron consultar los datos geotécnicos.",
                source_trace=SourceTrace(
                    source_name="emergencias/gestionriesgos",
                    layer_id="2",
                    service_url=f"{RAIZ_ARCGIS}/emergencias/gestionriesgos/MapServer",
                    data_vigencia="2023",
                    query_timestamp=_ahora_iso(),
                ),
            )
            warnings.append({
                "codigo": "BLOQUE_DEGRADADO",
                "mensaje": "Bloque geotechnical_risks degradado: error al consultar la fuente.",
            })
        else:
            riesgos_geotec, trace_geotecnia = r_geotecnia
            tiene_datos_geotec = any([
                riesgos_geotec.amenaza_movimientos,
                riesgos_geotec.geologia,
                riesgos_geotec.respuesta_sismica,
                riesgos_geotec.zonificacion_geotecnica,
            ])
            if tiene_datos_geotec:
                partes_geotec = []
                if riesgos_geotec.amenaza_movimientos:
                    partes_geotec.append(f"amenaza: {riesgos_geotec.amenaza_movimientos}")
                if riesgos_geotec.geologia:
                    partes_geotec.append(f"geología: {riesgos_geotec.geologia}")
                if riesgos_geotec.respuesta_sismica:
                    partes_geotec.append(f"sísmica: {riesgos_geotec.respuesta_sismica}")
                if riesgos_geotec.zonificacion_geotecnica:
                    partes_geotec.append(
                        f"zonificación: {riesgos_geotec.zonificacion_geotecnica}"
                    )
                interpretation_geotec = (
                    f"Clasificación geotécnica del lote: {', '.join(partes_geotec)}."
                )
            else:
                interpretation_geotec = (
                    "No se encontraron datos geotécnicos para el lote en la fuente consultada."
                )
                warnings.append({
                    "codigo": "BLOQUE_SIN_DATO",
                    "mensaje": (
                        "Bloque geotechnical_risks no encontrado: no se hallaron "
                        "datos geotécnicos para el lote."
                    ),
                })
            bloque_geotecnia = BloqueRiesgosGeotecnicos(
                estado="disponible" if tiene_datos_geotec else "no_encontrado",
                dato=riesgos_geotec if tiene_datos_geotec else None,
                interpretation=interpretation_geotec,
                source_trace=trace_geotecnia,
            )

        # Bloque socioeconomic_context
        if isinstance(r_socio, BaseException):
            bloque_socio = BloqueContextoSocioeconomico(
                estado="no_encontrado",
                interpretation="No se pudieron consultar los datos socioeconómicos.",
                source_trace=SourceTrace(
                    source_name="Estratificación socioeconómica",
                    layer_id="1",
                    service_url=f"{RAIZ_ARCGIS}/ordenamientoterritorial/estratificacion/MapServer",
                    data_vigencia="2024",
                    query_timestamp=_ahora_iso(),
                ),
            )
            warnings.append({
                "codigo": "BLOQUE_DEGRADADO",
                "mensaje": "Bloque socioeconomic_context degradado: error al consultar la fuente.",
            })
        else:
            contexto_socio, trace_socio = r_socio
            tiene_datos_socio = any([
                contexto_socio.estrato is not None,
                contexto_socio.uso_predominante,
                contexto_socio.altura_media is not None,
                contexto_socio.mediana_avaluo is not None,
            ])
            partes_socio = []
            if contexto_socio.estrato is not None:
                partes_socio.append(f"estrato {contexto_socio.estrato}")
            if contexto_socio.uso_predominante:
                partes_socio.append(f"uso: {contexto_socio.uso_predominante}")
            if contexto_socio.altura_media is not None:
                partes_socio.append(f"altura media: {_formatear_numero(contexto_socio.altura_media)} pisos")
            if contexto_socio.mediana_avaluo is not None:
                partes_socio.append(
                    f"avalúo catastral mediano: {_formatear_numero(contexto_socio.mediana_avaluo)} COP"
                )
            if partes_socio:
                interpretation_socio = (
                    f"Contexto socioeconómico del lote: {', '.join(partes_socio)}."
                )
            else:
                interpretation_socio = (
                    "No se encontraron datos socioeconómicos para el lote en la fuente consultada."
                )
                warnings.append({
                    "codigo": "BLOQUE_SIN_DATO",
                    "mensaje": (
                        "Bloque socioeconomic_context no encontrado: no se hallaron "
                        "datos socioeconómicos para el lote."
                    ),
                })
            bloque_socio = BloqueContextoSocioeconomico(
                estado="disponible" if tiene_datos_socio else "no_encontrado",
                dato=contexto_socio if tiene_datos_socio else None,
                interpretation=interpretation_socio,
                source_trace=trace_socio,
            )

        # Bloque regulatory_environment
        if isinstance(r_regulatorio, BaseException):
            bloque_regulatorio = BloqueEntornoRegulatorio(
                estado="no_encontrado",
                interpretation="No se pudieron consultar los datos regulatorios.",
                source_trace=SourceTrace(
                    source_name="Licencias de construcción aprobadas",
                    layer_id="3",
                    service_url=f"{RAIZ_ARCGIS}/ordenamientoterritorial/licenciasconstruccion/MapServer",
                    data_vigencia="2025",
                    query_timestamp=_ahora_iso(),
                ),
            )
            warnings.append({
                "codigo": "BLOQUE_DEGRADADO",
                "mensaje": "Bloque regulatory_environment degradado: error al consultar la fuente.",
            })
        else:
            entorno_reg, trace_regulatorio = r_regulatorio
            tiene_datos_reg = any([
                entorno_reg.licencias_encontradas is not None,
                entorno_reg.zona_plusvalia is not None,
            ])
            partes_reg = []
            if entorno_reg.licencias_encontradas is not None:
                plural_lic = "s" if entorno_reg.licencias_encontradas != 1 else ""
                partes_reg.append(
                    f"{entorno_reg.licencias_encontradas} licencia{plural_lic} aprobada{plural_lic}"
                )
            if entorno_reg.zona_plusvalia is True:
                detalle_plan = ""
                if entorno_reg.nombre_plan_plusvalia:
                    detalle_plan = f" ({entorno_reg.nombre_plan_plusvalia})"
                partes_reg.append(f"zona de plusvalía{detalle_plan}")
            if partes_reg:
                interpretation_reg = (
                    f"Entorno regulatorio del lote: {', '.join(partes_reg)}."
                )
            else:
                interpretation_reg = (
                    "No se encontraron datos regulatorios para el lote en la fuente consultada."
                )
                warnings.append({
                    "codigo": "BLOQUE_SIN_DATO",
                    "mensaje": (
                        "Bloque regulatory_environment no encontrado: no se hallaron "
                        "datos regulatorios para el lote."
                    ),
                })
            bloque_regulatorio = BloqueEntornoRegulatorio(
                estado="disponible" if tiene_datos_reg else "no_encontrado",
                dato=entorno_reg if tiene_datos_reg else None,
                interpretation=interpretation_reg,
                source_trace=trace_regulatorio,
            )

        # Bloque cultural_heritage
        if isinstance(r_patrimonio, BaseException):
            bloque_patrimonio = BloquePatrimonioCultural(
                estado="no_encontrado",
                interpretation="No se pudieron consultar los datos de patrimonio cultural.",
                source_trace=SourceTrace(
                    source_name="Bienes de Interés Cultural",
                    layer_id="1",
                    service_url=f"{RAIZ_ARCGIS}/recreaciondeporte/bienesinterescultural/MapServer",
                    data_vigencia="2023",
                    query_timestamp=_ahora_iso(),
                ),
            )
            warnings.append({
                "codigo": "BLOQUE_DEGRADADO",
                "mensaje": "Bloque cultural_heritage degradado: error al consultar la fuente.",
            })
        else:
            patrimonio, trace_patrimonio = r_patrimonio
            tiene_datos_pat = any([
                patrimonio.bic_cercano is not None,
                patrimonio.zona_arqueologica is not None,
            ])
            partes_pat = []
            if patrimonio.bic_cercano is True:
                detalle_bic = ""
                if patrimonio.nombre_bic:
                    detalle_bic = f" ({patrimonio.nombre_bic})"
                partes_pat.append(f"BIC cercano{detalle_bic}")
            if patrimonio.zona_arqueologica is True:
                partes_pat.append("zona arqueológica")
            if partes_pat:
                interpretation_pat = (
                    f"Patrimonio cultural del lote: {', '.join(partes_pat)}."
                )
            else:
                interpretation_pat = (
                    "No se encontraron elementos de patrimonio cultural para el lote "
                    "en la fuente consultada."
                )
                warnings.append({
                    "codigo": "BLOQUE_SIN_DATO",
                    "mensaje": (
                        "Bloque cultural_heritage no encontrado: no se hallaron "
                        "elementos de patrimonio cultural para el lote."
                    ),
                })
            bloque_patrimonio = BloquePatrimonioCultural(
                estado="disponible" if tiene_datos_pat else "no_encontrado",
                dato=patrimonio if tiene_datos_pat else None,
                interpretation=interpretation_pat,
                source_trace=trace_patrimonio,
            )

        # Bloque transit_access
        if isinstance(r_movilidad, BaseException):
            bloque_movilidad = BloqueAccesoMovilidad(
                estado="no_encontrado",
                interpretation="No se pudieron consultar los datos de transporte público.",
                source_trace=SourceTrace(
                    source_name="Transporte público — Estaciones TransMilenio",
                    layer_id="1",
                    service_url=f"{RAIZ_ARCGIS}/movilidad/transportepublico/MapServer",
                    data_vigencia="2025",
                    query_timestamp=_ahora_iso(),
                ),
            )
            warnings.append({
                "codigo": "BLOQUE_DEGRADADO",
                "mensaje": "Bloque transit_access degradado: error al consultar la fuente.",
            })
        else:
            movilidad, trace_movilidad = r_movilidad
            tiene_datos_mov = any([
                movilidad.estaciones_transmilenio is not None,
                movilidad.paraderos_sitp is not None,
                movilidad.estaciones_metro is not None,
            ])
            partes_mov = []
            if movilidad.estaciones_transmilenio is not None:
                plural_tm = "s" if movilidad.estaciones_transmilenio != 1 else ""
                partes_mov.append(
                    f"{movilidad.estaciones_transmilenio} estación{plural_tm} TransMilenio"
                )
            if movilidad.paraderos_sitp is not None:
                plural_sitp = "s" if movilidad.paraderos_sitp != 1 else ""
                partes_mov.append(
                    f"{movilidad.paraderos_sitp} paradero{plural_sitp} SITP"
                )
            if movilidad.estaciones_metro is not None:
                plural_metro = "s" if movilidad.estaciones_metro != 1 else ""
                partes_mov.append(
                    f"{movilidad.estaciones_metro} estación{plural_metro} Metro"
                )
            if movilidad.estacion_cercana:
                partes_mov.append(f"estación más cercana: {movilidad.estacion_cercana}")
            if partes_mov:
                interpretation_mov = (
                    f"Acceso a transporte público del lote: {', '.join(partes_mov)}."
                )
            else:
                interpretation_mov = (
                    "No se encontraron estaciones de transporte público cercanas al lote "
                    "en la fuente consultada."
                )
                warnings.append({
                    "codigo": "BLOQUE_SIN_DATO",
                    "mensaje": (
                        "Bloque transit_access no encontrado: no se identificaron "
                        "estaciones de transporte público cercanas al lote."
                    ),
                })
            bloque_movilidad = BloqueAccesoMovilidad(
                estado="disponible" if tiene_datos_mov else "no_encontrado",
                dato=movilidad if tiene_datos_mov else None,
                interpretation=interpretation_mov,
                source_trace=trace_movilidad,
            )

        # Bloque catastro_data
        if isinstance(r_catastro, BaseException):
            bloque_catastro = BloqueCatastroData(
                estado="no_encontrado",
                interpretation="No se pudieron consultar los datos catastrales adicionales.",
                source_trace=SourceTrace(
                    source_name="Catastro — Construcción",
                    layer_id="0",
                    service_url=f"{RAIZ_ARCGIS}/catastro/construccion/MapServer",
                    data_vigencia="2024",
                    query_timestamp=_ahora_iso(),
                ),
            )
            warnings.append({
                "codigo": "BLOQUE_DEGRADADO",
                "mensaje": "Bloque catastro_data degradado: error al consultar la fuente.",
            })
        else:
            contexto_catastro, trace_catastro = r_catastro
            tiene_datos_catastro = any([
                contexto_catastro.construccion is not None,
                contexto_catastro.manzana is not None,
                contexto_catastro.densidad_predial is not None,
                contexto_catastro.variacion_area is not None,
                contexto_catastro.sector_catastral is not None,
            ])
            partes_catastro = []
            if contexto_catastro.sector_catastral:
                partes_catastro.append(f"sector: {contexto_catastro.sector_catastral}")
            if contexto_catastro.manzana:
                codigo_mz = contexto_catastro.manzana.get("codigo_manzana")
                if codigo_mz:
                    partes_catastro.append(f"manzana: {codigo_mz}")
            if contexto_catastro.densidad_predial:
                num_predios = contexto_catastro.densidad_predial.get("num_predios")
                if num_predios is not None:
                    partes_catastro.append(f"predios en manzana: {int(num_predios)}")
            if contexto_catastro.construccion:
                pisos = contexto_catastro.construccion.get("pisos")
                if pisos is not None:
                    partes_catastro.append(f"pisos: {int(pisos)}")
            if contexto_catastro.variacion_area:
                periodo = contexto_catastro.variacion_area.get("periodo")
                if periodo:
                    partes_catastro.append(f"variación: {periodo}")
            if partes_catastro:
                interpretation_catastro = (
                    f"Datos catastrales del lote: {', '.join(partes_catastro)}."
                )
            else:
                interpretation_catastro = (
                    "No se encontraron datos catastrales adicionales para el lote "
                    "en la fuente consultada."
                )
                warnings.append({
                    "codigo": "BLOQUE_SIN_DATO",
                    "mensaje": (
                        "Bloque catastro_data no encontrado: no se hallaron "
                        "datos catastrales adicionales para el lote."
                    ),
                })
            bloque_catastro = BloqueCatastroData(
                estado="disponible" if tiene_datos_catastro else "no_encontrado",
                dato=contexto_catastro if tiene_datos_catastro else None,
                interpretation=interpretation_catastro,
                source_trace=trace_catastro,
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
            "urbanistic_parameters": _bloque_a_contrato(bloque_urbanistic),
            "normative_evidence": evidencia.model_dump(),
            "feasibility_score": score.model_dump(),
            "warnings": warnings,
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
        """
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
        return (
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
        lote = Lote(
            chip=arcgis.chip,
            codigo_catastral=arcgis.codigo_catastral,
            manzana=arcgis.manzana,
            direccion_normalizada=arcgis.direccion_normalizada,
            barrio=arcgis.barrio,
            geometry=arcgis.geometry,
            centroid=Centroide(lat=lat, lng=lng),
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


def _validar_coordenadas(latitude: Any, longitude: Any) -> dict | None:
    es_numero = lambda valor: isinstance(valor, (int, float)) and not isinstance(valor, bool)
    if not es_numero(latitude) or not es_numero(longitude):
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


def _ahora_iso() -> str:
    """Marca temporal ISO 8601 UTC (patron F1/F2); no participa del score (SC-003)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _formatear_numero(valor: float) -> str:
    """Formato determinista del numero en interpretations (4500000.0 -> "4500000")."""
    if float(valor).is_integer():
        return str(int(valor))
    return str(valor)


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
            f'retiro frontal, retiro lateral y retiro posterior (en metros), '
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
    estacionamientos desde el texto del LLM. Si un patrón no matchea, el
    campo queda None (FR-014: sin LLM para interpretaciones).
    """
    cos = _extraer_float_patron(respuesta_rag, r"COS[:\s]+(\d+\.?\d*)")
    cus = _extraer_float_patron(respuesta_rag, r"CUS[:\s]+(\d+\.?\d*)")
    altura = _extraer_float_patron(respuesta_rag, r"altura[:\s]+(\d+\.?\d*)\s*m")
    frontal = _extraer_float_patron(respuesta_rag, r"frontal[:\s]+(\d+\.?\d*)\s*m")
    laterales = _extraer_float_patron(respuesta_rag, r"laterales[:\s]+(\d+\.?\d*)\s*m")
    posterior = _extraer_float_patron(respuesta_rag, r"posterior[:\s]+(\d+\.?\d*)\s*m")
    estacionamientos = _extraer_int_patron(respuesta_rag, r"(\d+)\s*estacionamiento")
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
    1. Consulta SDP (tratamiento espacial via SINUPOT layer 2)
    2. Si tratamiento OK → consulta RAG normativo para parámetros numéricos
    3. Parsing regex determinista de la respuesta (FR-014)
    4. Degradación independiente por fuente: SDP falla → no_encontrado; RAG falla → tratamiento OK + campos None

    Contrato (contracts/urbanistic-parameters.md:Degradación por fuente).
    """
    try:
        tratamiento, trace_sdp = await provider_sdp.consultar_tratamiento(lng, lat)
    except (Fuente5xxError, Fuente4xxError, FuenteDatosInvalidosError):
        # SDP falla → bloque no_encontrado + warning BLOQUE_DEGRADADO (FR-009)
        warnings.append({
            "codigo": "BLOQUE_DEGRADADO",
            "mensaje": (
                "Bloque urbanistic_parameters degradado: "
                "error al consultar la capa SINUPOT/SDP."
            ),
        })
        trace_fallback = SourceTrace(
            source_name="SINUPOT — Norma Urbanística y OT",
            layer_id="2",
            service_url=provider_sdp._tratamiento.service_url,
            data_vigencia="2021",
            query_timestamp=_ahora_iso(),
        )
        return BloqueParametrosUrbanisticos(
            estado="no_encontrado",
            interpretation="No se encontró un tratamiento urbanístico para el lote en la fuente consultada.",
            source_trace=trace_fallback,
        )
    except Exception:
        # Excepción inesperada del SDP → no_encontrado + warning
        warnings.append({
            "codigo": "BLOQUE_DEGRADADO",
            "mensaje": (
                "Bloque urbanistic_parameters degradado: "
                "error inesperado al consultar la capa SINUPOT/SDP."
            ),
        })
        trace_fallback = SourceTrace(
            source_name="SINUPOT — Norma Urbanística y OT",
            layer_id="2",
            service_url=provider_sdp._tratamiento.service_url,
            data_vigencia="2021",
            query_timestamp=_ahora_iso(),
        )
        return BloqueParametrosUrbanisticos(
            estado="no_encontrado",
            interpretation="No se encontró un tratamiento urbanístico para el lote en la fuente consultada.",
            source_trace=trace_fallback,
        )

    # --- SDP OK: tratamiento resuelto espacialmente ---
    prompt_rag = _construir_prompt_parametros_urbanisticos(
        tratamiento.denominacion, upl_codigo
    )
    parametros_rag = None
    try:
        resultado_normativa = await provider_normativa.consultar(
            consulta=prompt_rag, upl=upl_codigo, top_k=3
        )
        respuesta_texto = resultado_normativa.get("respuesta", "")
        parametros_rag = _parsear_parametros_rag(respuesta_texto)
    except Exception:
        # RAG falla → tratamiento OK, campos numéricos None (FR-009)
        pass

    # --- Construcción del bloque con patrón {estado, dato, interpretation, source_trace} ---
    cos = None
    cus = None
    altura = None
    frontal = None
    laterales = None
    posterior = None
    estacionamientos_req = None
    solo_tratamiento = False

    if parametros_rag is not None:
        cos = parametros_rag["cos"]
        cus = parametros_rag["cus"]
        altura = parametros_rag["altura_maxima_m"]
        frontal = parametros_rag["frontal_m"]
        laterales = parametros_rag["laterales_m"]
        posterior = parametros_rag["posteriores_m"]
        estacionamientos_req = parametros_rag["estacionamientos_requeridos"]
        tiene_datos_numericos = any(v is not None for v in [
            cos, cus, altura, frontal, laterales, posterior, estacionamientos_req
        ])
        if not tiene_datos_numericos:
            solo_tratamiento = True
    else:
        solo_tratamiento = True

    # --- Interpretación determinista (FR-014) ---
    if solo_tratamiento:
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
    edificabilidad = ParametrosEdificabilidad(
        cos=cos, cus=cus, altura_maxima_m=altura
    )
    retiros = RetirosLote(
        frontal_m=frontal, laterales_m=laterales, posteriores_m=posterior
    )
    estacionamientos = EstacionamientosRequeridos(
        requeridos=estacionamientos_req,
        criterio=(
            "Artículo 389 Decreto 555/2021"
            if estacionamientos_req is not None
            else None
        ),
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
    """
    if bloque.estado == "disponible" and bloque.dato is not None:
        dato = bloque.dato.model_dump(exclude={"estado", "source_trace"}, exclude_none=True)
        if extra_dato:
            dato.update(extra_dato)
    else:
        dato = None
    return {
        "estado": bloque.estado,
        "dato": dato,
        "interpretation": bloque.interpretation,
        "source_trace": bloque.source_trace.model_dump(),
    }


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
