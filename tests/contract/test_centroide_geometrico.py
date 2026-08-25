"""Tests del centroide geometrico interior (hallazgo M3).

El centroide publicado de un lote es el centroide geometrico del poligono
(shoelace) validado como punto interior; si cae fuera (lotes concavos), se usa
un punto interior seguro determinista. La media aritmetica de vertices quedo
atras: cae fuera de lotes concavos y provoca consultas fantasma al re-consultar
la capa por punto.
"""

from __future__ import annotations

import httpx
import pytest

from app.providers.geom import (
    centroide_de_anillo,
    centroide_interior_de_geometria,
    punto_en_anillo,
    punto_en_poligono,
)
from app.providers.mapas_bogota import MapasBogotaProvider, _centroide_desde_rings
from tests.conftest import CHIP_VALIDO, RESPUESTA_CHIP_VACIA

# Lote en U: la media de vertices (5.0, 5.5) y el centroide shoelace (~5.0,
# ~4.08) caen DENTRO del hueco (x en 2..8, y en 2..10), fuera del poligono.
ANILLO_EN_U = [
    [0.0, 0.0],
    [10.0, 0.0],
    [10.0, 10.0],
    [8.0, 10.0],
    [8.0, 2.0],
    [2.0, 2.0],
    [2.0, 10.0],
    [0.0, 10.0],
    [0.0, 0.0],  # cierre
]

RECTANGULO = [
    [-74.084, 4.603],
    [-74.082, 4.603],
    [-74.082, 4.604],
    [-74.084, 4.604],
    [-74.084, 4.603],
]


def test_centroide_de_anillo_rectangulo_es_el_centro():
    centro = centroide_de_anillo(RECTANGULO)
    assert centro == pytest.approx((-74.083, 4.6035))


def test_punto_en_anillo_clasifica_dentro_y_fuera():
    assert punto_en_anillo((-74.083, 4.6035), RECTANGULO)
    assert not punto_en_anillo((-74.09, 4.6035), RECTANGULO)


def test_lote_en_u_la_media_de_vertices_cae_fuera():
    """Documenta el bug original: la media simple de vertices del lote en U
    cae dentro del hueco, fuera del poligono."""
    xs = [p[0] for p in ANILLO_EN_U]
    ys = [p[1] for p in ANILLO_EN_U]
    media = (sum(xs) / len(xs), sum(ys) / len(ys))
    assert not punto_en_poligono(media, [ANILLO_EN_U])


def test_centroide_interior_de_geometria_en_u_devuelve_punto_interior():
    punto = centroide_interior_de_geometria(
        {"type": "Polygon", "coordinates": [ANILLO_EN_U]}
    )
    assert punto is not None
    assert punto_en_poligono(punto, [ANILLO_EN_U])


def test_centroide_interior_es_determinista():
    geometria = {"type": "Polygon", "coordinates": [ANILLO_EN_U]}
    assert centroide_interior_de_geometria(geometria) == centroide_interior_de_geometria(
        geometria
    )


def test_multipoligono_domina_el_de_mayor_area():
    grande = [[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]]
    pequeno = [[[20.0, 20.0], [21.0, 20.0], [21.0, 21.0], [20.0, 21.0], [20.0, 20.0]]]
    punto = centroide_interior_de_geometria(
        {"type": "MultiPolygon", "coordinates": [pequeno, grande]}
    )
    assert punto == (5.0, 5.0)


def test_geometria_no_utilizable_retorna_none():
    assert centroide_interior_de_geometria(None) is None
    assert centroide_interior_de_geometria({"type": "Point", "coordinates": [1, 2]}) is None
    assert centroide_interior_de_geometria({"type": "Polygon", "coordinates": []}) is None
    # Anillo degenerado (colineal): sin area util -> None
    degenerado = [[[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [0.0, 0.0]]]
    assert (
        centroide_interior_de_geometria({"type": "Polygon", "coordinates": degenerado})
        is None
    )


def test_centroide_desde_rings_con_agujeros_respeta_el_hueco():
    """Rings ESRI con agujero: el punto no puede caer dentro del agujero."""
    exterior = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]
    agujero = [[4.0, 4.0], [6.0, 4.0], [6.0, 6.0], [4.0, 6.0], [4.0, 4.0]]
    punto = _centroide_desde_rings([exterior, agujero])
    assert punto is not None and punto[0] is not None and punto[1] is not None
    assert punto_en_poligono((punto[0], punto[1]), [exterior, agujero])


async def test_buscar_por_chip_publica_centroide_interior_del_predio():
    """Flujo CHIP (M3): el centroide del predio devuelto por Mapas Bogota es un
    punto interior del poligono, aunque los rings sean concavos."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cmd") == "direccion_chip":
            query = request.url.params.get("query")
            if query == CHIP_VALIDO:
                return httpx.Response(
                    200,
                    json={
                        "resultados": [
                            {
                                "VALUE": CHIP_VALIDO,
                                "NOMBRE": "CRA 12 # 10-20",
                                "GEOMETRY": {"rings": [ANILLO_EN_U]},
                            }
                        ],
                        "status": True,
                    },
                )
            return httpx.Response(200, json=RESPUESTA_CHIP_VACIA)
        return httpx.Response(500, json={"error": "cmd no simulado"})

    provider = MapasBogotaProvider(transport=httpx.MockTransport(handler))
    try:
        predio = await provider.buscar_por_chip(CHIP_VALIDO)
    finally:
        await provider.aclose()

    assert predio is not None
    lng, lat = predio.centroid
    assert punto_en_poligono((lng, lat), [ANILLO_EN_U])
