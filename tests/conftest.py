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


# --- Fixtures Feature 3 (informe de factibilidad, T007) ---
# Patron payload/status de F1/F2: respuestas simuladas de la capa Predio
# (f=pjson), de obraspublicas con buffer 500 m (f=geojson) y de la capa UPL
# (UPL24 Chapinero, vocacion Urbano). Ninguna prueba hace llamadas de red reales.

# Capa Predio (catastro/lote/MapServer/3): formato pjson {"features": [{"attributes": {...}}]}
# (research H1/H3). CHIP AAA0072LRYN -> 2 filas: PRECDESTIN=04, PRECUSO=015/096,
# PREAUSO=40453.8/3011.3, PREVACTUAL=2026, BARMANPRE=006101016001.
PREDIO_FILA_DOMINANTE = {
    "attributes": {
        "PRECDESTIN": "04",
        "PRECUSO": "015",
        "PREAUSO": 40453.8,
        "PREVACTUAL": "2026",
        "PREATERRE": 3704.8,
        "PREACONST": 43465.1,
        "PREDIRECC": "AK 30 25 90",
        "PRENBARRIO": "FLORIDA",
        "BARMANPRE": "006101016001",
    }
}

PREDIO_FILA_SECUNDARIA = {
    "attributes": {
        "PRECDESTIN": "04",
        "PRECUSO": "096",
        "PREAUSO": 3011.3,
        "PREVACTUAL": "2026",
        "PREATERRE": 3704.8,
        "PREACONST": 43465.1,
        "PREDIRECC": "AK 30 25 90",
        "PRENBARRIO": "FLORIDA",
        "BARMANPRE": "006101016001",
    }
}

PAYLOAD_PREDIO = {"features": [PREDIO_FILA_DOMINANTE, PREDIO_FILA_SECUNDARIA]}
PAYLOAD_PREDIO_VACIO = {"features": []}

# Obras publicas con buffer 500 m (FR-004, research H5): formato geojson.
PAYLOAD_OBRAS_BUFFER_500 = geojson(
    [feature_obra("Ampliación de Estaciones: Calle 146")]
)

# Capa UPL (unidadplaneamientolocal/0): UPL24 Chapinero con vocacion Urbano.
def feature_upl(codigo="UPL24", nombre="Chapinero", vocacion="Urbano"):
    return {
        "type": "Feature",
        "properties": {"CODIGO_UPL": codigo, "NOMBRE": nombre, "VOCACION": vocacion},
        "geometry": None,
    }


def provider_arcgis_f3(lotes=None, valor=None, reserva=None, obras=None, predio=None, contador=None):
    """Provider ArcGIS del flujo F3: capa Lote, tematicas, obras buffer 500 m y capa Predio.

    `predio` acepta el payload pjson de la capa Predio o la tupla (payload, status);
    `obras` por defecto es el payload con buffer 500 m (formato geojson).
    `contador` (opcional) es una lista donde el handler registra cada request
    (str(request.url)) para verificar el numero de consultas por ruta (deuda
    tecnica post-revision: contexto tematico consultado una sola vez).
    """

    def respuesta_de(contenido):
        if isinstance(contenido, tuple) and len(contenido) == 2 and isinstance(contenido[1], int):
            payload, status = contenido
            return httpx.Response(status, json=payload)
        if isinstance(contenido, list):
            return httpx.Response(200, json=geojson(contenido))
        return httpx.Response(200, json=contenido)

    def handler(request: httpx.Request) -> httpx.Response:
        if contador is not None:
            contador.append(str(request.url))
        url = str(request.url)
        if "Mapa_Referencia/Mapa_Referencia/MapServer/38/query" in url:
            return respuesta_de(lotes if lotes is not None else [feature_lote(codigo_catastral="006101016001", manzana="006101016")])
        if "valorreferencia" in url:
            return respuesta_de(valor if valor is not None else [feature_valor()])
        if "reservavial" in url:
            return respuesta_de(reserva if reserva is not None else [feature_reserva()])
        if "obraspublicas" in url:
            return respuesta_de(obras if obras is not None else PAYLOAD_OBRAS_BUFFER_500)
        if "catastro/lote/MapServer/3/query" in url:
            return respuesta_de(predio if predio is not None else PAYLOAD_PREDIO)
        return httpx.Response(404, json={"error": f"sin respuesta simulada para {url}"})

    return ArcGISProvider(transport=httpx.MockTransport(handler))


def provider_upl_estandar(upl_features=None):
    """Provider UPL: UPL24 Chapinero (vocacion Urbano) por defecto."""
    features = upl_features if upl_features is not None else [feature_upl()]
    return UPLProvider(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=geojson(features)))
    )


def server_lotes_f3(mapas=None, arcgis=None, upl=None, normativa=None):
    """ServidorLotes con providers simulados del flujo F3 (informe de factibilidad)."""
    return ServidorLotes(
        mapas if mapas is not None else provider_mapas_estandar(),
        arcgis if arcgis is not None else provider_arcgis_f3(),
        upl if upl is not None else provider_upl_estandar(),
        normativa if normativa is not None else NormativaProvider(),
    )


# --- Ampliacion de fixtures F3: stub del NormativaProvider (T015 y reporte F3) ---
# Los contract tests F3 no pueden usar el NormativaProvider real (requiere
# ChromaDB + Ollama, prohibido en tests). Este stub implementa la interfaz que
# usara el orquestador de `get_feasibility_report` (consultar + aclose), registra
# las llamadas para verificar la consulta explicita/automatica (T015) e inyecta
# errores tipados (CorpusNoIngestadoError/OllamaNoDisponibleError) o respuestas
# vacias para probar la degradacion deliberada de normative_evidence (FR-009).


def respuesta_normativa_ok():
    """Respuesta RAG con 1 articulo recuperado (formato consultar_normativa de F2).

    `trazabilidad` es el source_trace del corpus (Decreto 555/2021) que el
    orquestador debe propagar al bloque normative_evidence (T017).
    """
    return {
        "respuesta": "El Artículo 361 regula los usos del suelo.",
        "sin_resultados": False,
        "resultados": [
            {
                "articulo": 361,
                "titulo": "Usos del suelo",
                "libro": "III",
                "parte": "urbano",
                "texto_cita": "El presente artículo regula los usos del suelo...",
                "similitud": 0.42,
            }
        ],
        "trazabilidad": {
            "source_name": "Decreto 555 de 2021 (POT Bogotá)",
            "layer_id": "Decreto_555_2021",
            "service_url": "https://sisjur.bogotajuridica.gov.co/sisjur/normas/Norma1.jsp?i=119582",
            "data_vigencia": "2021-12-30",
            "query_timestamp": "2026-08-12T02:15:04Z",
        },
    }


def respuesta_normativa_sin_resultados():
    """Respuesta RAG sin resultados (formato consultar_normativa de F2)."""
    return {
        "respuesta": "No se encontraron resultados relevantes en el POT 555/2021.",
        "sin_resultados": True,
        "resultados": [],
        "trazabilidad": {
            "source_name": "Decreto 555 de 2021 (POT Bogotá)",
            "layer_id": "Decreto_555_2021",
            "service_url": "https://sisjur.bogotajuridica.gov.co/sisjur/normas/Norma1.jsp?i=119582",
            "data_vigencia": "2021-12-30",
            "query_timestamp": "2026-08-12T02:15:04Z",
        },
    }


class NormativaProviderStub:
    """Stub del NormativaProvider para los contract tests F3 (sin red ni Ollama).

    Registra cada llamada a `consultar` en `llamadas` (consulta, upl, top_k) y
    devuelve `respuesta` o lanza `error` si se inyecto uno (degradacion T015).
    """

    def __init__(
        self,
        respuesta: dict | None = None,
        error: Exception | None = None,
    ) -> None:
        self.respuesta = respuesta if respuesta is not None else respuesta_normativa_sin_resultados()
        self.error = error
        self.llamadas: list[dict] = []

    async def consultar(self, consulta: str, upl: str | None = None, top_k: int = 3) -> dict:
        self.llamadas.append({"consulta": consulta, "upl": upl, "top_k": top_k})
        if self.error is not None:
            raise self.error
        return self.respuesta

    async def aclose(self) -> None:
        return None
