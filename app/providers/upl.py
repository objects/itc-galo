"""Provider de la capa UPL (Unidad de Planeamiento Local) del catastro de Bogota.

Consulta la capa `ordenamientoterritorial/unidadplaneamientolocal/MapServer/0`
por punto (interseccion espacial) y devuelve UPL con trazabilidad (FR-005, FR-006).

Frontera de parsing para la API ArcGIS REST del catastro (Principio II).
El mapeo NOMBRE -> localidad se deriva de la tabla estatica UPLS_BOGOTA
(33 UPLs del Decreto 555/2021 con su vocacion), que tambien alimenta el
filtro territorial FR-002 (PARTES_POR_UPL).
"""

from __future__ import annotations

import asyncio
import unicodedata
from typing import Any

import httpx
from pydantic import BaseModel

from app.errores import Fuente4xxError, Fuente5xxError, FuenteDatosInvalidosError, UplNoEncontradaError
from app.models import UPL, SourceTrace
# Helpers compartidos (hallazgo m7): unica definicion en app/utilidades.py.
from app.utilidades import (
    ahora_iso as _ahora_iso,
    extraer_numero as _extraer_numero,
    primer_texto as _primer_texto,
    primer_valor as _primer_valor,
)
from app.providers.arcgis_utils import (
    RAIZ_ARCGIS,
    CapaConfig,
    construir_params_punto,
    consultar_query,
)


# Vigencia por defecto de la capa UPL (Decreto 555/2021 define las UPL)
VIGENCIA_UPL_DEFAULT = "2021-12-30"


# Tabla estatica versionada de las 33 UPLs de Bogota (Decreto 555/2021).
# Fuente canonica: capa ArcGIS
# `ordenamientoterritorial/unidadplaneamientolocal/MapServer/0` (33 features,
# atributos CODIGO_UPL/NOMBRE/VOCACION consultados con where=1=1). La localidad
# NO es un atributo de la capa: se asigna por la localidad principal de la UPL
# segun el POT. UPLs multilocalidad documentadas en su entrada.
# Vocacion (valores reales de la capa): "Urbano", "Urbano-Rural", "Rural".
UPLS_BOGOTA: dict[str, dict[str, str]] = {
    "UPL01": {"nombre": "Sumapáz", "localidad": "Sumapaz", "vocacion": "Rural"},
    # Cuenca rural del río Tunjuelo: abarca Usme (principal), Ciudad Bolívar y Tunjuelito.
    "UPL02": {"nombre": "Cuenca del Tunjuelo", "localidad": "Usme", "vocacion": "Rural"},
    "UPL03": {"nombre": "Arborizadora", "localidad": "Ciudad Bolivar", "vocacion": "Urbano-Rural"},
    "UPL04": {"nombre": "Lucero", "localidad": "Bosa", "vocacion": "Urbano-Rural"},
    "UPL05": {"nombre": "Usme - Entrenubes", "localidad": "Usme", "vocacion": "Urbano-Rural"},
    # Cerros Orientales: franja rural/protegida compartida por Santa Fe (principal),
    # San Cristóbal, Usaquén y Chapinero.
    "UPL06": {"nombre": "Cerros Orientales", "localidad": "Santa Fe", "vocacion": "Rural"},
    "UPL07": {"nombre": "Torca", "localidad": "Usaquen", "vocacion": "Urbano-Rural"},
    "UPL08": {"nombre": "Britalia", "localidad": "Suba", "vocacion": "Urbano-Rural"},
    "UPL09": {"nombre": "Suba", "localidad": "Suba", "vocacion": "Urbano"},
    "UPL10": {"nombre": "Tibabuyes", "localidad": "Suba", "vocacion": "Urbano-Rural"},
    "UPL11": {"nombre": "Engativá", "localidad": "Engativa", "vocacion": "Urbano-Rural"},
    "UPL12": {"nombre": "Fontibón", "localidad": "Fontibon", "vocacion": "Urbano-Rural"},
    "UPL13": {"nombre": "Tintal", "localidad": "Kennedy", "vocacion": "Urbano-Rural"},
    "UPL14": {"nombre": "Patio Bonito", "localidad": "Kennedy", "vocacion": "Urbano-Rural"},
    "UPL15": {"nombre": "Porvenir", "localidad": "Bosa", "vocacion": "Urbano-Rural"},
    "UPL16": {"nombre": "Edén", "localidad": "Kennedy", "vocacion": "Urbano"},
    "UPL17": {"nombre": "Bosa", "localidad": "Bosa", "vocacion": "Urbano"},
    "UPL18": {"nombre": "Kennedy", "localidad": "Kennedy", "vocacion": "Urbano"},
    "UPL19": {"nombre": "Tunjuelito", "localidad": "Tunjuelito", "vocacion": "Urbano"},
    "UPL20": {"nombre": "Rafael Uribe", "localidad": "Rafael Uribe Uribe", "vocacion": "Urbano"},
    "UPL21": {"nombre": "San Cristóbal", "localidad": "San Cristobal", "vocacion": "Urbano"},
    "UPL22": {"nombre": "Restrepo", "localidad": "Puente Aranda", "vocacion": "Urbano"},
    # Centro Histórico: abarca La Candelaria, Santa Fe (principal) y Los Mártires.
    "UPL23": {"nombre": "Centro Histórico", "localidad": "Santa Fe", "vocacion": "Urbano"},
    "UPL24": {"nombre": "Chapinero", "localidad": "Chapinero", "vocacion": "Urbano"},
    "UPL25": {"nombre": "Usaquén", "localidad": "Usaquen", "vocacion": "Urbano"},
    "UPL26": {"nombre": "Toberín", "localidad": "Fontibon", "vocacion": "Urbano"},
    "UPL27": {"nombre": "Niza", "localidad": "Engativa", "vocacion": "Urbano"},
    "UPL28": {"nombre": "Rincón de Suba", "localidad": "Suba", "vocacion": "Urbano"},
    "UPL29": {"nombre": "Tabora", "localidad": "Puente Aranda", "vocacion": "Urbano"},
    # Salitre: Ciudad Salitre repartida entre Engativá (principal) y Barrios Unidos.
    "UPL30": {"nombre": "Salitre", "localidad": "Engativa", "vocacion": "Urbano"},
    "UPL31": {"nombre": "Puente Aranda", "localidad": "Puente Aranda", "vocacion": "Urbano"},
    "UPL32": {"nombre": "Teusaquillo", "localidad": "Teusaquillo", "vocacion": "Urbano"},
    "UPL33": {"nombre": "Barrios Unidos", "localidad": "Barrios Unidos", "vocacion": "Urbano"},
}

# Partes del Decreto 555/2021 aplicables por vocación de la UPL (FR-002,
# plan.md F2: "general siempre aplicable"). Una UPL "Urbano-Rural" tiene suelo
# de ambas clases: sus artículos pueden vivir en la Parte III (urbana) o en la
# IV (rural).
PARTES_POR_VOCACION: dict[str, list[str]] = {
    "Urbano": ["urbano", "general"],
    "Urbano-Rural": ["urbano", "rural", "general"],
    "Rural": ["rural", "general"],
}

PARTES_POR_UPL: dict[str, list[str]] = {
    codigo: list(PARTES_POR_VOCACION[registro["vocacion"]])
    for codigo, registro in UPLS_BOGOTA.items()
}


def partes_aplicables(codigo_upl: str) -> list[str]:
    """Partes del Decreto 555/2021 que aplican a una UPL (FR-002).

    Fail loud: una UPL fuera del catálogo (UPL01–UPL33) no tiene una respuesta
    silenciosa; el llamador ya valida el formato, así que llegar aquí con un
    código desconocido es un estado ilegal.

    Raises:
        ValueError: si el código no está en el catálogo de 33 UPLs.
    """
    clave = codigo_upl.strip().upper()
    if clave not in PARTES_POR_UPL:
        raise ValueError(f"UPL desconocida: {codigo_upl}. Debe ser UPL01–UPL33.")
    return list(PARTES_POR_UPL[clave])


def construir_filtro_territorial(upl: str) -> dict[str, Any]:
    """Filtro territorial estricto por UPL para ChromaDB (FR-002, plan.md F2).

    Filtro compuesto `$or` (función pura): un chunk entra si su Parte del
    Decreto 555 aplica a la clasificación de suelo de la UPL (`parte` en
    `partes_aplicables(upl)`, vía PARTES_POR_UPL) O si el artículo menciona
    explícitamente la UPL (`upls`, list[str] en la metadata; `$contains`
    sobre lista es membresía exacta). Los chunks sin parte derivada
    (parte="" en el índice) solo entran por la vía de mención explícita.
    """
    return {
        "$or": [
            {"parte": {"$in": partes_aplicables(upl)}},
            {"upls": {"$contains": upl}},
        ]
    }


def _clave_nombre(nombre: str) -> str:
    """Clave de búsqueda para nombres de UPL: mayúsculas sin tildes."""
    sin_tildes = unicodedata.normalize("NFD", nombre)
    return "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn").upper()


# Mapeo estatico NOMBRE_UPL -> localidad, derivado de UPLS_BOGOTA (fuente:
# capa ArcGIS unidadplaneamientolocal/MapServer/0). Las claves van en
# mayusculas sin tildes porque la capa trae nombres acentuados ("Engativá").
NOMBRE_UPL_A_LOCALIDAD: dict[str, str] = {
    _clave_nombre(registro["nombre"]): registro["localidad"]
    for registro in UPLS_BOGOTA.values()
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
        localidad = NOMBRE_UPL_A_LOCALIDAD.get(_clave_nombre(feature.nombre))
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


# _primer_texto/_extraer_numero/_primer_valor/_ahora_iso viven en
# app/utilidades.py (hallazgo m7).