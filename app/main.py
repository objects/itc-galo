"""Servidor MCP mcp-bogota-factibilidad: registra 6 tools (4 F1 + 2 F2).

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
from app.models import Centroide, Lote
from app.providers.arcgis import ArcGISProvider
from app.providers.mapas_bogota import CandidatoDireccion, MapasBogotaProvider
from app.providers.normativa import NormativaProvider
from app.providers.upl import UPLProvider

try:  # mcp >= 1.x: FastMCP
    from mcp.server.fastmcp import FastMCP as _ClaseServidorMCP
except ImportError:  # mcp 2.x renombro FastMCP a MCPServer
    from mcp.server.mcpserver import MCPServer as _ClaseServidorMCP

NOMBRE_SERVIDOR = "mcp-bogota-factibilidad"
PATRON_CHIP = re.compile(r"^[A-Z0-9]{11}$")

CAMPOS_TRAZA = {"source_name", "layer_id", "service_url", "data_vigencia", "query_timestamp"}


class ServidorLotes:
    """Logica de dominio de las 6 tools MCP (4 F1 + 2 F2) sobre los providers tipados."""

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

        return {
            "upl": {
                "codigo": upl.codigo_upl,
                "nombre": upl.nombre,
                "localidad": upl.localidad_derivada,
            },
            "trazabilidad": upl.source_trace.model_dump() if upl.source_trace else None,
        }

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

        Semantica del retorno:
        - (Lote, None): lote unico encontrado.
        - (None, error): no se pudo resolver (5xx, limite entre lotes o identidad
          incompleta); el error ya es la respuesta de la tool.
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
        if arcgis.chip is None:
            # El contrato exige chip en la identidad; sin el atributo de la capa no
            # se puede construir una identidad veraz (no se inventa el dato).
            return None, construir_error(
                CodigoError.LOTE_NO_ENCONTRADO,
                message="No se encontró un lote único para el punto ({lat}, {lng}).",
                lat=lat,
                lng=lng,
            )
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
                lote.codigo_catastral, lote.centroid.lng, lote.centroid.lat
            )
        except (Fuente5xxError, Fuente4xxError, FuenteDatosInvalidosError) as exc:
            return None, _error_de_fuente(exc)
        return contexto, None

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
    """Construye el servidor MCP registrando EXACTAMENTE las 6 tools del contrato (4 F1 + 2 F2).

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
    return mcp


servidor_lotes = _construir_servidor_lotes()
mcp = crear_servidor_mcp(servidor_lotes)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
