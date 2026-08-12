"""Fixtures compartidas: providers con respuestas simuladas via httpx.MockTransport.

Ninguna prueba hace llamadas de red reales (tasks.md: T013-T036).
"""

from __future__ import annotations

import httpx

from app.main import ServidorLotes
from app.providers.arcgis import ArcGISProvider
from app.providers.mapas_bogota import MapasBogotaProvider
from app.providers.normativa import NormativaProvider
from app.providers.upl import UPLProvider


# --- Respuestas simuladas de las fuentes ---

CHIP_VALIDO = "AAA0072LRYN"
CHIP_INEXISTENTE = "ZZZ9999ZZZ9"
CODIGO_CATASTRAL = "006202003016"
MANZANA = "006202003"

RESPUESTA_CHIP_AAA = {
    "resultados": [
        {
            "OBJECTID": "68410691",
            "CODIGO_POSTAL": "111311",
            "VALUE": "AAA0072LRYN",
            "NOMBRE": "CRA 12 # 10-20",
            "BARRIO": "LAS NIEVES",
            "GEOMETRY": {
                "rings": [
                    [
                        [-74.083, 4.603],
                        [-74.082, 4.603],
                        [-74.082, 4.604],
                        [-74.083, 4.604],
                        [-74.083, 4.603],
                    ]
                ]
            },
        }
    ],
    "status": True,
}

# CHIP desconocido: la API viva responde HTTP 200 con status:false y el mensaje
# "El servicio no esta disponible" (NO es un 5xx; se mapea a "no encontrado").
RESPUESTA_CHIP_VACIA = {"mensaje": "El servicio no esta disponible", "status": False}


def geocodificar_unica():
    return {
        "resultados": [
            {"NOMBRE": "Calle 26 # 69-76", "LATITUD": 4.665, "LONGITUD": -74.102}
        ]
    }


def geocodificar_varias():
    return {
        "resultados": [
            {"NOMBRE": "Calle 26 # 69-76", "LATITUD": 4.665, "LONGITUD": -74.102},
            {"NOMBRE": "Calle 26 # 69-76 A", "LATITUD": 4.668, "LONGITUD": -74.105},
        ]
    }


def geocodificar_vacia():
    return {"resultados": []}


def feature_lote(codigo_catastral=CODIGO_CATASTRAL, manzana=MANZANA, chip=CHIP_VALIDO):
    return {
        "type": "Feature",
        "properties": {"LOTCODIGO": codigo_catastral, "MANZCODIGO": manzana, "CHIP": chip},
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-74.084, 4.603],
                    [-74.082, 4.603],
                    [-74.082, 4.604],
                    [-74.084, 4.604],
                    [-74.084, 4.603],
                ]
            ],
        },
    }


def feature_valor(valor_m2=3200000, anio=2025):
    return {
        "type": "Feature",
        "properties": {"VALOR_M2": valor_m2, "ANIO": anio},
        "geometry": None,
    }


def feature_reserva(descripcion="Reserva vial Avenida 68", anio=None):
    propiedades = {"DESCRIPCION": descripcion}
    if anio is not None:
        propiedades["ANIO"] = anio
    return {
        "type": "Feature",
        "properties": propiedades,
        "geometry": None,
    }


def feature_obra(nombre):
    return {
        "type": "Feature",
        "properties": {"NOMBRE": nombre},
        "geometry": None,
    }


def geojson(features):
    return {"type": "FeatureCollection", "features": features}


# --- Constructores de providers ---


def provider_mapas_estandar(api_key="clave-de-prueba"):
    """Provider de Mapas Bogota: CHIP conocido, CHIP inexistente y geocodificacion unica.

    La API viva expone /buscar (cmd=direccion_chip) y /api (cmd=geocodificar)
    en https://catalogopmb.catastrobogota.gov.co/PMBWeb/web; el mock valida la
    ruta y el cmd de cada consulta.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        cmd = request.url.params.get("cmd")
        if cmd == "direccion_chip" and request.url.path.endswith("/buscar"):
            query = request.url.params.get("query")
            if query == CHIP_VALIDO:
                return httpx.Response(200, json=RESPUESTA_CHIP_AAA)
            return httpx.Response(200, json=RESPUESTA_CHIP_VACIA)
        if cmd == "geocodificar" and request.url.path.endswith("/api"):
            return httpx.Response(200, json=geocodificar_unica())
        return httpx.Response(500, json={"error": "cmd no simulado"})

    return MapasBogotaProvider(transport=httpx.MockTransport(handler), api_key=api_key)


def provider_arcgis_estandar(
    lotes=None,
    valor=None,
    reserva=None,
    obras=None,
):
    """Provider ArcGIS: capa Lote por punto y las 3 tematicas activas con respuestas simuladas.

    Cada parametro acepta una lista de features o la tupla (payload, status) para
    simular errores HTTP de la fuente.
    """

    def respuesta_de(contenido):
        if isinstance(contenido, tuple) and len(contenido) == 2 and isinstance(contenido[1], int):
            payload, status = contenido
            return httpx.Response(status, json=payload)
        return httpx.Response(200, json=geojson(contenido))

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "Mapa_Referencia/Mapa_Referencia/MapServer/38/query" in url:
            return respuesta_de(lotes if lotes is not None else [feature_lote()])
        if "valorreferencia" in url:
            return respuesta_de(valor if valor is not None else [feature_valor()])
        if "reservavial" in url:
            return respuesta_de(reserva if reserva is not None else [feature_reserva()])
        if "obraspublicas" in url:
            return respuesta_de(
                obras
                if obras is not None
                else [feature_obra("Parque Metropolitano"), feature_obra("Avenida Ciudad de Cali")]
            )
        return httpx.Response(404, json={"error": f"sin respuesta simulada para {url}"})

    return ArcGISProvider(transport=httpx.MockTransport(handler))


def construir_servidor(mapas=None, arcgis=None):
    """ServidorLotes con providers simulados (por defecto el flujo feliz estandar)."""
    return ServidorLotes(
        mapas if mapas is not None else provider_mapas_estandar(),
        arcgis if arcgis is not None else provider_arcgis_estandar(),
        UPLProvider(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"type": "FeatureCollection", "features": []}))),
        NormativaProvider(),
    )
