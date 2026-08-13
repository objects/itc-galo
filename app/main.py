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
    BloqueDestinoEconomico,
    BloqueObrasPublicas,
    BloqueReservaVial,
    BloqueValorReferencia,
    Centroide,
    ContextoAdministrativo,
    EvidenciaNormativa,
    ItemEvidenciaNormativa,
    Localidad,
    Lote,
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
    ) -> None:
        self._mapas = provider_mapas
        self._arcgis = provider_arcgis
        self._upl = provider_upl
        self._normativa = provider_normativa

    async def aclose(self) -> None:
        await self._mapas.aclose()
        await self._arcgis.aclose()
        await self._upl.aclose()
        await self._normativa.aclose()

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
        return {
            "identidad": _identidad_a_contrato(lote),
            "contexto_por_fuente": contexto.a_lista_por_fuente(),
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
        if not isinstance(top_k, int) or not 1 <= top_k <= TOP_K_MAX:
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
            lote, error = await self._resolver_lote_por_candidato(candidatos[0])
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

        # --- Contexto tematico (reserva vial + valor de referencia de F1) ---
        contexto, error_contexto = await self._consultar_contexto_seguro(lote)
        if error_contexto:
            return error_contexto

        # --- Obras publicas con buffer 500 m (FR-004, research H5) ---
        try:
            obras_publicas = await self._arcgis.consultar_obras_publicas_radio(
                lote.centroid.lng, lote.centroid.lat, RADIO_OBRAS_M
            )
        except (Fuente5xxError, Fuente4xxError, FuenteDatosInvalidosError) as exc:
            return _error_de_fuente(exc)

        # --- Destino economico (capa Predio por PRECHIP o BARMANPRE, research H2) ---
        try:
            destino = await self._arcgis.consultar_destino_economico(
                chip=lote.chip, codigo_catastral=lote.codigo_catastral
            )
        except (Fuente5xxError, Fuente4xxError, FuenteDatosInvalidosError) as exc:
            return _error_de_fuente(exc)

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
            normative_evidence=evidencia,
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
        self, candidato: CandidatoDireccion
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


def _error_de_fuente(exc: Exception) -> dict[str, Any]:
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
