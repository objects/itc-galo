"""Provider de la capa UPL (Unidad de Planeamiento Local) del catastro de Bogota.

Consulta la capa `ordenamientoterritorial/unidadplaneamientolocal/MapServer/0`
por punto (interseccion espacial) y devuelve UPL con trazabilidad (FR-005, FR-006).

Frontera de parsing para la API ArcGIS REST del catastro (Principio II).
El mapeo NOMBRE -> localidad se deriva de research D3 (mapeo estatico).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel

from app.errores import Fuente4xxError, Fuente5xxError, FuenteDatosInvalidosError, UplNoEncontradaError
from app.models import UPL, SourceTrace
from app.providers.arcgis_utils import (
    RAIZ_ARCGIS,
    CapaConfig,
    construir_params_punto,
    consultar_query,
)


# Vigencia por defecto de la capa UPL (Decreto 555/2021 define las UPL)
VIGENCIA_UPL_DEFAULT = "2021-12-30"


# Mapeo estatico NOMBRE_UPL -> localidad (research D3)
# Basado en el mapa de UPLs del POT Bogota (Decreto 555/2021)
NOMBRE_UPL_A_LOCALIDAD: dict[str, str] = {
    "SUMAPAZ": "Sumapaz",
    "USME": "Usme",
    "CIUDAD BOLIVAR": "Ciudad Bolivar",
    "TUNJUELITO": "Tunjuelito",
    "BOSA": "Bosa",
    "KENNEDY": "Kennedy",
    "FONTIBON": "Fontibon",
    "ENGATIVA": "Engativa",
    "SUBA": "Suba",
    "BARRIOS UNIDOS": "Barrios Unidos",
    "TEUSAQUILLO": "Teusaquillo",
    "LOS MARTIRES": "Los Martires",
    "ANTONIO NARINO": "Antonio Narino",
    "PUENTE ARANDA": "Puente Aranda",
    "CANDELARIA": "La Candelaria",
    "RAFAEL URIBE URIBE": "Rafael Uribe Uribe",
    "USAQUEN": "Usaquen",
    "CHAPINERO": "Chapinero",
    "SANTA FE": "Santa Fe",
    # UPLs rurales / areas especiales
    "SUMAPAZ RURAL": "Sumapaz",
    "SAN CRISTOBAL SUR": "San Cristobal",
    "SAN CRISTOBAL NORTE": "San Cristobal",
    "USME RURAL": "Usme",
    "CIUDAD BOLIVAR RURAL": "Ciudad Bolivar",
}


class UPLFeature(BaseModel):
    """Feature UPL parseado de la capa ArcGIS (layer 0 unidadplaneamientolocal)."""

    codigo_upl: str
    nombre: str
    acto_administrativo: str | None = None
    numero_acto_administrativo: str | None = None
    fecha_acto_administrativo: str | None = None
    normativa: str | None = None
    vocacion: str | None = None
    observacion: str | None = None
    area_ha: float | None = None


def _configuracion_upl(vigencia: str | None = None) -> CapaConfig:
    """Configuracion de la capa UPL (layer 0 del servicio unidadplaneamientolocal)."""
    return CapaConfig(
        clave="upl",
        source_name="IDECA Catastro — Unidad de Planeamiento Local",
        service_url=f"{RAIZ_ARCGIS}/ordenamientoterritorial/unidadplaneamientolocal/MapServer",
        layer_id="0",
        data_vigencia=vigencia or VIGENCIA_UPL_DEFAULT,
    )


class UPLProvider:
    """Cliente httpx async para la capa UPL del catastro de Bogota."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        vigencia: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._client = httpx.AsyncClient(base_url=RAIZ_ARCGIS, transport=transport, timeout=timeout)
        self._capa = _configuracion_upl(vigencia)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def consultar_upl_por_punto(self, lng: float, lat: float) -> UPL:
        """Consulta la capa UPL por punto (lng, lat) en WGS84.

        Devuelve la UPL que intersecta el punto, con codigo, nombre,
        localidad derivada y trazabilidad completa (5 campos).
        """
        params = {
            "f": "geojson",
            "geometry": f"{lng},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outSR": "4326",
            "returnGeometry": "false",
            "outFields": "*",
        }
        data = await self._consultar(params)
        upl_feature = self._parsear_upl(data)
        return self._construir_upl(upl_feature)

    async def _consultar(self, params: dict[str, Any]) -> dict[str, Any]:
        """Consulta la capa UPL delegando en utilidades compartidas."""
        return await consultar_query(
            client=self._client,
            base_url=self._capa.service_url,
            layer_id=self._capa.layer_id,
            source_name=self._capa.source_name,
            params=params,
        )

    def _parsear_upl(self, data: dict[str, Any]) -> UPLFeature:
        """Parsea la respuesta GeoJSON de la capa UPL.

        Si no hay features -> UplNoEncontradaError (dato no encontrado, FR-007).
        Si hay multiples features, toma la primera (la interseccion espacial
        deberia ser unica para un punto).
        """
        features = data.get("features") or []
        if not features:
            raise UplNoEncontradaError(
                self._capa.source_name
            )

        propiedades = features[0].get("properties") or {}
        codigo_upl = _primer_texto(propiedades, ["CODIGO_UPL", "CODIGO", "UPL"])
        nombre = _primer_texto(propiedades, ["NOMBRE", "NOMBRE_UPL"])

        if not codigo_upl or not nombre:
            raise FuenteDatosInvalidosError(
                self._capa.source_name, "el feature UPL no tiene CODIGO_UPL o NOMBRE"
            )

        return UPLFeature(
            codigo_upl=codigo_upl,
            nombre=nombre,
            acto_administrativo=_primer_texto(propiedades, ["ACTO_ADMINISTRATIVO", "ACTO"]),
            numero_acto_administrativo=_primer_texto(propiedades, ["NUMERO_ACTO", "NUM_ACTO"]),
            fecha_acto_administrativo=_primer_texto(propiedades, ["FECHA_ACTO", "FECHA_ACTO_ADMINISTRATIVO"]),
            normativa=_primer_texto(propiedades, ["NORMATIVA", "NORMATIVA_APLICABLE"]),
            vocacion=_primer_texto(propiedades, ["VOCACION", "VOCACION_SUELO"]),
            observacion=_primer_texto(propiedades, ["OBSERVACION", "OBSERVACIONES"]),
            area_ha=_extraer_numero(propiedades, ["AREA_HA", "AREA", "HECTAREAS"]),
        )

    def _construir_upl(self, feature: UPLFeature) -> UPL:
        """Construye el modelo UPL con localidad derivada y trazabilidad."""
        localidad = NOMBRE_UPL_A_LOCALIDAD.get(feature.nombre.upper())
        trace = SourceTrace(
            source_name=self._capa.source_name,
            layer_id=self._capa.layer_id,
            service_url=self._capa.service_url,
            data_vigencia=self._capa.data_vigencia,
            query_timestamp=_ahora_iso(),
        )
        return UPL(
            codigo_upl=feature.codigo_upl,
            nombre=feature.nombre,
            localidad_derivada=localidad,
            acto_administrativo=feature.acto_administrativo,
            numero_acto_administrativo=feature.numero_acto_administrativo,
            fecha_acto_administrativo=feature.fecha_acto_administrativo,
            normativa=feature.normativa,
            vocacion=feature.vocacion,
            observacion=feature.observacion,
            area_ha=feature.area_ha,
            estado="disponible",
            source_trace=trace,
        )


def _primer_texto(objeto: dict[str, Any], claves: list[str]) -> str | None:
    for clave in claves:
        if clave in objeto and objeto[clave] is not None:
            texto = str(objeto[clave]).strip()
            if texto:
                return texto
    return None


def _extraer_numero(objeto: dict[str, Any], claves: list[str]) -> float | None:
    valor = _primer_valor(objeto, claves)
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _primer_valor(objeto: dict[str, Any], claves: list[str]) -> Any:
    for clave in claves:
        if clave in objeto and objeto[clave] is not None:
            return objeto[clave]
    return None


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")