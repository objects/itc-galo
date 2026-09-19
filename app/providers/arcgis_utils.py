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

import asyncio
import json
from typing import Any

import httpx
from dataclasses import dataclass

from app.errores import (
    Fuente4xxError,
    Fuente5xxError,
    FuenteDatosInvalidosError,
    verificar_body_sin_error,
)
from app.utilidades import ahora_iso

RAIZ_ARCGIS = "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services"


@dataclass(frozen=True)
class CapaConfig:
    """Configuración de una capa ArcGIS consultable por punto."""

    clave: str
    source_name: str
    service_url: str
    layer_id: str
    data_vigencia: str

    @property
    def ruta_consulta(self) -> str:
        """URL completa de consulta (contrato F11): `{service_url}/{layer_id}/query`."""
        return f"{self.service_url.rstrip('/')}/{self.layer_id}/query"


# Catálogo declarativo extensible (F11 FR-001/FR-002/R-01, contrato
# specs/011-catalogo-extensible-wizard-v2/contracts/catalogo.md).
#
# Fuente de verdad declarativa de las capas ArcGIS del informe (clave = nombre
# de capa del provider; un bloque del informe puede consumir varias claves).
# Las dos capas SDP (tratamiento/edificabilidad) se EXCLUYEN deliberadamente:
# viven en sdp.py con su propio CRS (EPSG:4686) y no usan el patrón genérico.
#
# Cómo añadir una capa nueva (T005):
#   1. Añade una entrada a CATALOGO_CAPAS con service_url completo, layer_id,
#      source_name y data_vigencia de la fuente (no inventar vigencia).
#   2. Mapea la clave a su bloque en la orquestación (app/main.py) si el
#      informe debe publicar un bloque nuevo; si solo enriquece uno existente,
#      añade la clave a la lista de ese bloque.
#   3. Reutiliza construir_params_punto + consultar_query: el clasificador de
#      errores tipado (FR-009) y la caché por lote (Fase 5) aplican sin
#      escribir código nuevo. Valida con httpx.MockTransport (patrón tests).
CATALOGO_CAPAS: dict[str, CapaConfig] = {
    "lote": CapaConfig(
        clave="lote",
        source_name="Mapa_Referencia/Mapa_Referencia",
        service_url=f"{RAIZ_ARCGIS}/Mapa_Referencia/Mapa_Referencia/MapServer",
        layer_id="38",
        data_vigencia="2019",
    ),
    "valorreferencia": CapaConfig(
        clave="valorreferencia",
        source_name="catastro/valorreferencia",
        service_url=f"{RAIZ_ARCGIS}/catastro/valorreferencia/MapServer",
        layer_id="0",
        data_vigencia="2012-2025",
    ),
    # reservavial usa el layer 2: el layer 1 es un Group Layer y la capa
    # consultable es el Feature Layer 2 (hallazgo vivo, Fix C).
    "reservavial": CapaConfig(
        clave="reservavial",
        source_name="ordenamientoterritorial/reservavial",
        service_url=f"{RAIZ_ARCGIS}/ordenamientoterritorial/reservavial/MapServer",
        layer_id="2",
        data_vigencia="2019-08-15",
    ),
    "obraspublicas": CapaConfig(
        clave="obraspublicas",
        source_name="gestionpublica/obraspublicas",
        service_url=f"{RAIZ_ARCGIS}/gestionpublica/obraspublicas/MapServer",
        layer_id="0",
        data_vigencia="2025",
    ),
    # Predio (capa tabular, F3): la consulta real usa f=pjson (f=geojson
    # responde 400); la vigencia del registro es PREVACTUAL y este valor es
    # solo el respaldo de CapaConfig.
    "predio": CapaConfig(
        clave="predio",
        source_name="Predio (catastro/lote)",
        service_url=f"{RAIZ_ARCGIS}/catastro/lote/MapServer",
        layer_id="3",
        data_vigencia="2026",
    ),
    "upl": CapaConfig(
        clave="upl",
        source_name="IDECA Catastro — Unidad de Planeamiento Local",
        service_url=f"{RAIZ_ARCGIS}/ordenamientoterritorial/unidadplaneamientolocal/MapServer",
        layer_id="0",
        data_vigencia="2021-12-30",
    ),
    "geotecnia_amenaza": CapaConfig(
        clave="geotecnia_amenaza",
        source_name="Gestión de Riesgos — Amenaza movimientos en masa urbano",
        service_url=f"{RAIZ_ARCGIS}/emergencias/gestionriesgos/MapServer",
        layer_id="2",
        data_vigencia="2023",
    ),
    "geotecnia_geologia": CapaConfig(
        clave="geotecnia_geologia",
        source_name="Gestión de Riesgos — Geología Rural",
        service_url=f"{RAIZ_ARCGIS}/emergencias/gestionriesgos/MapServer",
        layer_id="5",
        data_vigencia="2023",
    ),
    "geotecnia_sismo": CapaConfig(
        clave="geotecnia_sismo",
        source_name="Gestión de Riesgos — Respuesta Sísmica",
        service_url=f"{RAIZ_ARCGIS}/emergencias/gestionriesgos/MapServer",
        layer_id="7",
        data_vigencia="2023",
    ),
    "geotecnia_zonificacion": CapaConfig(
        clave="geotecnia_zonificacion",
        source_name="Gestión de Riesgos — Zonificación Geotécnica",
        service_url=f"{RAIZ_ARCGIS}/emergencias/gestionriesgos/MapServer",
        layer_id="8",
        data_vigencia="2023",
    ),
    "estratificacion": CapaConfig(
        clave="estratificacion",
        source_name="Estratificación socioeconómica",
        service_url=f"{RAIZ_ARCGIS}/ordenamientoterritorial/estratificacion/MapServer",
        layer_id="1",
        data_vigencia="2024",
    ),
    "usopredominante": CapaConfig(
        clave="usopredominante",
        source_name="Uso predominante",
        service_url=f"{RAIZ_ARCGIS}/catastro/usopredominante/MapServer",
        layer_id="0",
        data_vigencia="2024",
    ),
    "alturamedia": CapaConfig(
        clave="alturamedia",
        source_name="Altura media",
        service_url=f"{RAIZ_ARCGIS}/catastro/alturamedia/MapServer",
        layer_id="0",
        data_vigencia="2024",
    ),
    "medianaavaluo": CapaConfig(
        clave="medianaavaluo",
        source_name="Mediana avalúo catastral",
        service_url=f"{RAIZ_ARCGIS}/catastro/medianaavaluocatastral/MapServer",
        layer_id="0",
        data_vigencia="2024",
    ),
    "licencias": CapaConfig(
        clave="licencias",
        source_name="Licencias de construcción aprobadas",
        service_url=f"{RAIZ_ARCGIS}/ordenamientoterritorial/licenciasconstruccion/MapServer",
        layer_id="3",
        data_vigencia="2025",
    ),
    "plusvalia": CapaConfig(
        clave="plusvalia",
        source_name="Plusvalía — Planes parciales",
        service_url=f"{RAIZ_ARCGIS}/ordenamientoterritorial/plusvalia/MapServer",
        layer_id="1",
        data_vigencia="2024",
    ),
    "bic": CapaConfig(
        clave="bic",
        source_name="Bienes de Interés Cultural",
        service_url=f"{RAIZ_ARCGIS}/recreaciondeporte/bienesinterescultural/MapServer",
        layer_id="1",
        data_vigencia="2023",
    ),
    "planarqueologico": CapaConfig(
        clave="planarqueologico",
        source_name="Plan Arqueológico",
        service_url=f"{RAIZ_ARCGIS}/recreaciondeporte/planarqueologico/MapServer",
        layer_id="9",
        data_vigencia="2023",
    ),
    "transmilenio": CapaConfig(
        clave="transmilenio",
        source_name="Transporte público — Estaciones TransMilenio",
        service_url=f"{RAIZ_ARCGIS}/movilidad/transportepublico/MapServer",
        layer_id="1",
        data_vigencia="2025",
    ),
    "sitp": CapaConfig(
        clave="sitp",
        source_name="Transporte público — Paraderos SITP",
        service_url=f"{RAIZ_ARCGIS}/movilidad/transportepublico/MapServer",
        layer_id="5",
        data_vigencia="2025",
    ),
    "metro": CapaConfig(
        clave="metro",
        source_name="Metro Bogotá",
        service_url=f"{RAIZ_ARCGIS}/movilidad/metrobogota/MapServer",
        layer_id="0",
        data_vigencia="2025",
    ),
    "construccion": CapaConfig(
        clave="construccion",
        source_name="Catastro — Construcción",
        service_url=f"{RAIZ_ARCGIS}/catastro/construccion/MapServer",
        layer_id="0",
        data_vigencia="2024",
    ),
    "manzana_catastro": CapaConfig(
        clave="manzana_catastro",
        source_name="Catastro — Manzana",
        service_url=f"{RAIZ_ARCGIS}/catastro/manzana/MapServer",
        layer_id="0",
        data_vigencia="2024",
    ),
    "densidad_predial": CapaConfig(
        clave="densidad_predial",
        source_name="Catastro — Densidad Predial",
        service_url=f"{RAIZ_ARCGIS}/catastro/densidadpredialmz/MapServer",
        layer_id="0",
        data_vigencia="2024",
    ),
    "variacion_area": CapaConfig(
        clave="variacion_area",
        source_name="Catastro — Variación Área Construida",
        service_url=f"{RAIZ_ARCGIS}/catastro/variacionareaconstruida/MapServer",
        layer_id="1",
        data_vigencia="2024",
    ),
    "sector_catastral": CapaConfig(
        clave="sector_catastral",
        source_name="Catastro — Sector Catastral",
        service_url=f"{RAIZ_ARCGIS}/catastro/sectorcatastral/MapServer",
        layer_id="0",
        data_vigencia="2024",
    ),
    # Fase 3: layer 8 = "Total por UPL"; layer 13 = "Malla Vial"; IPS de
    # vacunacion (layer 7) y colegios oficiales (layer 0); equipamiento
    # cultural por categoria (layers 1-3). El layer 6 "Museos" responde 400
    # en vivo y se excluye (limitacion documentada en AGENTS.md).
    "espacio_publico": CapaConfig(
        clave="espacio_publico",
        source_name="Indicadores de Espacio Público — Total por UPL",
        service_url=f"{RAIZ_ARCGIS}/espaciopublico/indicadorespaciopublico/MapServer",
        layer_id="8",
        data_vigencia="2024",
    ),
    "malla_vial": CapaConfig(
        clave="malla_vial",
        source_name="Mapa de Referencia — Malla Vial",
        service_url=f"{RAIZ_ARCGIS}/Mapa_Referencia/Mapa_Referencia/MapServer",
        layer_id="13",
        data_vigencia="2019",
    ),
    "facilidad_salud": CapaConfig(
        clave="facilidad_salud",
        source_name="Salud — IPS con Servicio de Vacunación",
        service_url=f"{RAIZ_ARCGIS}/salud/serviciosips/MapServer",
        layer_id="7",
        data_vigencia="2025",
    ),
    "facilidad_educacion": CapaConfig(
        clave="facilidad_educacion",
        source_name="Educación — Colegios",
        service_url=f"{RAIZ_ARCGIS}/educacion/infraestructuraeducativa/MapServer",
        layer_id="0",
        data_vigencia="2025",
    ),
    "facilidad_cultura_ciencia": CapaConfig(
        clave="facilidad_cultura_ciencia",
        source_name="Cultura — Equipamientos culturales (Ciencia)",
        service_url=f"{RAIZ_ARCGIS}/recreaciondeporte/equipamientocultural/MapServer",
        layer_id="1",
        data_vigencia="2025",
    ),
    "facilidad_cultura_arte": CapaConfig(
        clave="facilidad_cultura_arte",
        source_name="Cultura — Equipamientos culturales (Arte)",
        service_url=f"{RAIZ_ARCGIS}/recreaciondeporte/equipamientocultural/MapServer",
        layer_id="2",
        data_vigencia="2025",
    ),
    "facilidad_cultura_historia": CapaConfig(
        clave="facilidad_cultura_historia",
        source_name="Cultura — Equipamientos culturales (Historia)",
        service_url=f"{RAIZ_ARCGIS}/recreaciondeporte/equipamientocultural/MapServer",
        layer_id="3",
        data_vigencia="2025",
    ),
}



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


# Claves que ya tienen un bloque especializado en la orquestación del informe
# (F3/F6/F7/F8/Fase 3/F10). Es un snapshot en tiempo de import: una entrada
# AÑADIDA a `CATALOGO_CAPAS` después de este frozenset NO queda excluida, es
# decir, queda servida automaticamente por el camino generico de F11.
BLOQUES_ESPECIALIZADOS: frozenset[str] = frozenset(CATALOGO_CAPAS)


async def consultar_bloque_catalogo(
    client: httpx.AsyncClient,
    clave: str,
    capa: CapaConfig,
    lat: float,
    lng: float,
) -> dict[str, Any]:
    """Consulta una capa del catálogo y devuelve el bloque en forma contrato F11.

    Forma exacta de `contracts/catalogo.md`: `clave`, `titulo`, `estado`
    (`ok` | `no_encontrado`), `datos`, `source_traces` con los 5 campos
    obligatorios (`source_name`, `layer_id`, `service_url`, `data_vigencia`,
    `query_timestamp`) y `warnings`.

    Nunca lanza (FR-004, Principio IV degradado por bloque): un fallo de la
    fuente —5xx, 4xx o payload inválido— degrada SOLO este bloque a
    `no_encontrado` con el warning `BLOQUE_DEGRADADO`; jamás propaga
    `FUENTE_5XX` al informe. La vigencia publicada es la declarada de la capa,
    independiente de las demás (FR-002).
    """
    params = construir_params_punto(lat, lng)
    try:
        data = await consultar_query(
            client, capa.service_url, capa.layer_id, capa.source_name, params
        )
    except (Fuente5xxError, Fuente4xxError, FuenteDatosInvalidosError):
        return {
            "clave": clave,
            "titulo": clave,
            "estado": "no_encontrado",
            "datos": [],
            "source_traces": [],
            "warnings": ["BLOQUE_DEGRADADO"],
        }
    features = data.get("features") or []
    traza = {
        "source_name": capa.source_name,
        "layer_id": capa.layer_id,
        "service_url": capa.service_url,
        "data_vigencia": capa.data_vigencia,
        "query_timestamp": ahora_iso(),
    }
    return {
        "clave": clave,
        "titulo": clave,
        "estado": "ok" if features else "no_encontrado",
        "datos": features,
        "source_traces": [traza],
        "warnings": [],
    }


async def consultar_bloques_catalogo_adicionales(
    client: httpx.AsyncClient,
    lat: float,
    lng: float,
) -> dict[str, Any]:
    """Orquestación genérica F11 (T004): sirve las entradas NUEVAS del catálogo.

    Itera `CATALOGO_CAPAS` y consulta por el camino genérico solo las claves
    que aún no tienen bloque especializado (`BLOQUES_ESPECIALIZADOS`), en
    paralelo. Hoy el catálogo está compuesto íntegramente por claves
    especializadas, así que devuelve `{}` y el informe no cambia un ápice; en
    cuanto la wizard (o un desarrollo futuro) registre una capa nueva, aparece
    automáticamente como bloque con sus 5 campos de trazabilidad sin tocar la
    orquestación (R-07: "añadir capa es 1 config + 1 test").
    """
    pendientes = [
        (clave, capa)
        for clave, capa in CATALOGO_CAPAS.items()
        if clave not in BLOQUES_ESPECIALIZADOS
    ]
    if not pendientes:
        return {}
    resultados = await asyncio.gather(
        *(
            consultar_bloque_catalogo(client, clave, capa, lat, lng)
            for clave, capa in pendientes
        )
    )
    return {clave: bloque for (clave, _), bloque in zip(pendientes, resultados)}
