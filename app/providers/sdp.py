"""Provider de las capas SINUPOT/SDP (Norma Urbanística y OT) del POT de Bogotá.

Consulta las capas del SINUPOT (sinu.sdp.gov.co) para obtener parámetros
urbanísticos del lote:

- Layer 2: tratamiento urbanístico (FR-002, FR-004, FR-005)
- Layer 14: rangos de edificabilidad COS/CUS/altura (FR-006, FR-021)

Frontera de parsing para la API ArcGIS REST del SINUPOT/SDP (Principio II,
FR-017). El CRS del servicio es EPSG:4686 (MAGNA-SIRGAS); la consulta recibe
puntos en WGS84 (inSR=4326) y declara outSR=4686 para consistencia con el
servicio (FR-005).

Manejo de errores (FR-009, Principio IV):
- HTTP 5xx / error de red -> Fuente5xxError (consultar_query).
- HTTP 4xx -> Fuente4xxError (consultar_query).
- Sin features para el punto -> consultar_tratamiento retorna None
  ("SDP responde pero sin dato", el orquestador emite BLOQUE_SIN_DATO);
  consultar_edificabilidad retorna (None, trace) por ser capa complementaria.
- El esquema de campos de la capa NO es conocido a priori; se usa outFields="*"
  y se intentan múltiples nombres de campo de forma defensiva (patrón upl.py).

URL base del servicio (FR-022): constante configurable SDP_BASE_URL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.models import (
    ParametrosEdificabilidad,
    SourceTrace,
    TratamientoUrbanistico,
)
from app.providers.arcgis_utils import CapaConfig, consultar_query

# --- Constantes del servicio SINUPOT/SDP (FR-022) ---

SDP_BASE_URL = (
    "https://sinu.sdp.gov.co/serverp/rest/services/"
    "POT555/NORMA_URBAN%C3%8DSTICA_Y_OT/MapServer"
)

# Vigencia del POT Bogotá Reverdece 2022-2035 (Decreto 555/2021)
VIGENCIA_SDP_DEFAULT = "2021"

# Capas del SINUPOT
CAPA_TRATAMIENTO = "2"
CAPA_EDIFICABILIDAD = "14"


def _configuracion_tratamiento() -> CapaConfig:
    """Configuración de la capa de tratamiento urbanístico (layer 2)."""
    return CapaConfig(
        clave="tratamiento_sdp",
        source_name="SINUPOT — Norma Urbanística y OT",
        service_url=SDP_BASE_URL,
        layer_id=CAPA_TRATAMIENTO,
        data_vigencia=VIGENCIA_SDP_DEFAULT,
    )


def _configuracion_edificabilidad() -> CapaConfig:
    """Configuración de la capa de rangos de edificabilidad (layer 14)."""
    return CapaConfig(
        clave="edificabilidad_sdp",
        source_name="SINUPOT — Norma Urbanística y OT (Edificabilidad)",
        service_url=SDP_BASE_URL,
        layer_id=CAPA_EDIFICABILIDAD,
        data_vigencia=VIGENCIA_SDP_DEFAULT,
    )


def _params_punto_sdp(lng: float, lat: float) -> dict[str, Any]:
    """Parámetros de la consulta espacial por punto para SINUPOT/SDP.

    Similar a construir_params_punto de arcgis_utils.py pero con outSR=4686
    (MAGNA-SIRGAS) para consistencia con el CRS del servicio SINUPOT (FR-005).
    """
    return {
        "f": "geojson",
        "geometry": f"{lng},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outSR": "4686",
        "returnGeometry": "false",
        "outFields": "*",
    }


class SDPProvider:
    """Cliente httpx async para las capas SINUPOT/SDP del POT de Bogotá.

    Consulta las capas de tratamiento (layer 2) y edificabilidad (layer 14)
    del servicio SINUPOT. Sigue el patrón de upl.py (Principio II): un
    provider por fuente, httpx.AsyncClient con timeout configurable,
    método aclose() para el ciclo de vida.
    """

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout)
        self._tratamiento = _configuracion_tratamiento()
        self._edificabilidad = _configuracion_edificabilidad()

    def configuracion_tratamiento(self) -> CapaConfig:
        """Configuración pública de la capa de tratamiento (layer 2).

        Expone la CapaConfig para que el orquestador construya source_trace
        de fallback sin acceder al atributo privado `_tratamiento`
        (encapsulación, hallazgo m4 del code review).
        """
        return self._tratamiento

    async def aclose(self) -> None:
        """Cierra el cliente httpx subyacente."""
        await self._client.aclose()

    async def consultar_tratamiento(
        self, lng: float, lat: float
    ) -> tuple[TratamientoUrbanistico | None, SourceTrace]:
        """Consulta el tratamiento urbanístico del lote en la capa layer 2 del SINUPOT.

        Retorna la tupla (tratamiento, source_trace). Cuando SDP responde con
        éxito pero SIN features para el punto (o el feature no tiene campo de
        denominación), retorna (None, source_trace): es un "SDP responde pero
        sin dato" y el orquestador debe emitir warning BLOQUE_SIN_DATO
        (contracts/urbanistic-parameters.md:Warnings, FR-016). Los fallos de
        transporte/HTTP sí se propagan como Fuente5xxError/Fuente4xxError
        (el orquestador los mapea a BLOQUE_DEGRADADO).

        El esquema de campos de la capa NO es conocido a priori; se intentan
        múltiples nombres defensivos para el campo de denominación (patrón
        _primer_texto de upl.py).
        """
        params = _params_punto_sdp(lng, lat)
        data = await consultar_query(
            client=self._client,
            base_url=self._tratamiento.service_url,
            layer_id=self._tratamiento.layer_id,
            source_name=self._tratamiento.source_name,
            params=params,
        )
        trace = SourceTrace(
            source_name=self._tratamiento.source_name,
            layer_id=self._tratamiento.layer_id,
            service_url=self._tratamiento.service_url,
            data_vigencia=self._tratamiento.data_vigencia,
            query_timestamp=_ahora_iso(),
        )
        features = data.get("features") or []
        if not features:
            return None, trace

        propiedades = features[0].get("properties") or {}
        denominacion = _primer_texto(
            propiedades,
            ["DENOMINACION", "NOMBRE", "TRATAMIENTO", "TIPO", "TIPO_TRATA"],
        )
        if not denominacion:
            return None, trace

        codigo = _primer_texto(
            propiedades,
            ["CODIGO", "CODIGO_CAPA", "ID", "OBJECTID", "OBJECTID_1"],
        )
        return TratamientoUrbanistico(
            denominacion=denominacion,
            codigo_capa=codigo,
        ), trace

    async def consultar_edificabilidad(
        self, lng: float, lat: float
    ) -> tuple[ParametrosEdificabilidad | None, SourceTrace]:
        """Consulta los parámetros de edificabilidad en la capa layer 14 del SINUPOT.

        Retorna la tupla (edificabilidad, source_trace). Cuando la capa no tiene
        features para el punto, retorna (None, source_trace) ya que la capa 14
        es complementaria (FR-006, FR-021): la ausencia de datos de edificabilidad
        NO impide que el bloque reporte el tratamiento.

        Los campos COS/CUS/altura se extraen de forma defensiva intentando
        múltiples nombres de campo posibles (el esquema exacto no se conoce
        a priori).
        """
        params = _params_punto_sdp(lng, lat)
        data = await consultar_query(
            client=self._client,
            base_url=self._edificabilidad.service_url,
            layer_id=self._edificabilidad.layer_id,
            source_name=self._edificabilidad.source_name,
            params=params,
        )
        features = data.get("features") or []
        if not features:
            return None, SourceTrace(
                source_name=self._edificabilidad.source_name,
                layer_id=self._edificabilidad.layer_id,
                service_url=self._edificabilidad.service_url,
                data_vigencia=self._edificabilidad.data_vigencia,
                query_timestamp=_ahora_iso(),
            )

        propiedades = features[0].get("properties") or {}
        trace = SourceTrace(
            source_name=self._edificabilidad.source_name,
            layer_id=self._edificabilidad.layer_id,
            service_url=self._edificabilidad.service_url,
            data_vigencia=self._edificabilidad.data_vigencia,
            query_timestamp=_ahora_iso(),
        )
        return ParametrosEdificabilidad(
            cos=_extraer_numero(propiedades, ["COS", "COS_BASE", "COEF_OCUPACION"]),
            cus=_extraer_numero(propiedades, ["CUS", "CUS_BASE", "COEF_UTILIZACION"]),
            altura_maxima_m=_extraer_numero(
                propiedades, ["ALTURA", "ALTURA_MAX", "ALTURA_MAXIMA", "ALTURA_M"]
            ),
        ), trace


# --- Utilidades de parsing defensivo (patrón upl.py) ---


def _primer_texto(objeto: dict[str, Any], claves: list[str]) -> str | None:
    """Retorna el primer valor de texto no vacío para las claves dadas."""
    for clave in claves:
        if clave in objeto and objeto[clave] is not None:
            texto = str(objeto[clave]).strip()
            if texto:
                return texto
    return None


def _extraer_numero(objeto: dict[str, Any], claves: list[str]) -> float | None:
    """Extrae el primer valor numérico de las claves dadas."""
    valor = _primer_valor(objeto, claves)
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _primer_valor(objeto: dict[str, Any], claves: list[str]) -> Any:
    """Retorna el primer valor no None para las claves dadas."""
    for clave in claves:
        if clave in objeto and objeto[clave] is not None:
            return objeto[clave]
    return None


def _ahora_iso() -> str:
    """Timestamp ISO 8601 UTC actual."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
