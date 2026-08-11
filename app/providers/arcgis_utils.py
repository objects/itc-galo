"""Utilidades compartidas del patron ArcGIS REST (T007, plan.md:303-312).

Funciones puras que reciben el cliente explicitamente (constitucion, Principio
II): `construir_params_punto` construye la consulta espacial por punto y
`consultar_query` ejecuta el clasificador de errores tipado de F1 (FR-009) sobre
un cliente inyectado. `CapaConfig` es la configuracion canonica de una capa del
servicio, compartida por `arcgis.py` (F1) y `upl.py` (F2).

Diseno (Ley 3, Atomic Predictability): el modulo no crea clientes httpx ni
mantiene estado; cada funcion recibe lo que necesita (cliente, URL, parametros)
para ser predecible y reutilizable sin efectos ocultos.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel

from app.errores import (
    Fuente4xxError,
    Fuente5xxError,
    FuenteDatosInvalidosError,
    verificar_body_sin_error,
)

RAIZ_ARCGIS = "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services"


class CapaConfig(BaseModel):
    """Configuracion canonica de una capa del servicio ArcGIS."""

    clave: str
    source_name: str
    service_url: str
    layer_id: str
    data_vigencia: str

    @property
    def ruta_consulta(self) -> str:
        return f"{self.service_url.replace(RAIZ_ARCGIS, '').lstrip('/')}/{self.layer_id}/query"


def construir_params_punto(lat: float, lon: float) -> dict[str, Any]:
    """Parametros de la consulta espacial por punto (patron F1 `_params_punto`).

    Devuelve exactamente el mismo dict que producia `ArcGISProvider._params_punto`
    de F1: geometria del punto WGS84 con `esriSpatialRelIntersects` y salida
    GeoJSON sin geometria de respuesta. `lon` es la longitud y `lat` la latitud
    (el orden del dict preserva la semantica F1: geometry = "lon,lat").
    """
    return {
        "f": "geojson",
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outSR": "4326",
        "returnGeometry": "false",
        "outFields": "*",
    }


async def consultar_query(
    client: httpx.AsyncClient,
    base_url: str,
    layer_id: str,
    source_name: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Ejecuta una consulta `query` de ArcGIS REST sobre el cliente inyectado.

    Misma semantica del clasificador `_consultar` de F1 (FR-009, Principio IV):

    - HTTP/body 5xx -> Fuente5xxError (nunca "no encontrado").
    - HTTP/body 4xx -> Fuente4xxError (peticion rechazada).
    - Payload no utilizable -> FuenteDatosInvalidosError.
    - HTTP 200 + body {"error": {code, ...}} (patron ArcGIS REST) se detecta via
      `verificar_body_sin_error` y se clasifica igual que el status HTTP.

    `base_url` es la raiz del servicio (p. ej. `.../MapServer`) y `layer_id` el
    segmento de capa: la URL final es `{base_url}/{layer_id}/query`. `source_name`
    identifica la fuente en los errores tipados para que el mensaje sea accionable.
    """
    ruta_consulta = f"{base_url.rstrip('/')}/{layer_id}/query"
    try:
        respuesta = await client.get(ruta_consulta, params=params)
    except httpx.TransportError as exc:
        # Fallo de red: la fuente no esta disponible
        raise Fuente5xxError(source_name, 503) from exc
    if respuesta.status_code >= 500:
        raise Fuente5xxError(source_name, respuesta.status_code)
    if respuesta.status_code >= 400:
        raise Fuente4xxError(source_name, respuesta.status_code)
    try:
        data = respuesta.json()
    except json.JSONDecodeError as exc:
        raise FuenteDatosInvalidosError(
            source_name, "la respuesta no es JSON válido"
        ) from exc
    return verificar_body_sin_error(data, source_name)
