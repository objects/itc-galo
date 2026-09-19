"""F11 (T015): catálogo extensible — integridad del registro y camino genérico.

Verifica `contracts/catalogo.md`: una capa nueva registrada en
`CATALOGO_CAPAS` produce un bloque con los 5 campos de trazabilidad y su
vigencia propia (FR-002, sin mezclar capas); un 5xx degrada SOLO ese bloque
con `BLOQUE_DEGRADADO` y jamás propaga `FUENTE_5XX` (Principio IV); y el
baseline sigue intacto: 33 entradas especializadas, catálogo servido por el
camino genérico = `{}`, y `BLOQUES_EVALUABLES` con sus 19 bloques (R-02).

Todo con `httpx.MockTransport`: sin red real ni Ollama.
"""

from __future__ import annotations

import httpx
import pytest

from app.providers.arcgis_utils import (
    BLOQUES_ESPECIALIZADOS,
    CATALOGO_CAPAS,
    CapaConfig,
    consultar_bloque_catalogo,
    consultar_bloques_catalogo_adicionales,
)
from app.scoring import BLOQUES_EVALUABLES

URL_PRUEBA = (
    "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services"
    "/catastro/prueba/MapServer"
)

CAPA_PRUEBA = CapaConfig(
    clave="capa_prueba_f11",
    source_name="Capa de Prueba F11",
    service_url=URL_PRUEBA,
    layer_id="99",
    data_vigencia="2099-01-01",
)

LAT = 4.653
LNG = -74.083

CAMPOS_BLOQUE = {
    "clave",
    "titulo",
    "estado",
    "datos",
    "source_traces",
    "warnings",
}
CAMPOS_TRAZA = {
    "source_name",
    "layer_id",
    "service_url",
    "data_vigencia",
    "query_timestamp",
}


def _client_con_respuesta(status: int, payload: dict) -> httpx.AsyncClient:
    """Cliente con MockTransport que siempre responde `status` con `payload`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _payload_features(n: int) -> dict:
    return {
        "features": [
            {"attributes": {"FIELD": "v"}, "geometry": None} for _ in range(n)
        ]
    }


# ---------------------------------------------------------------------------
# (a) Integridad del catálogo declarado (T003) y baseline inalterado (R-02)
# ---------------------------------------------------------------------------


def test_catalogo_tiene_las_33_entradas_especializadas() -> None:
    assert len(CATALOGO_CAPAS) == 33
    assert BLOQUES_ESPECIALIZADOS == frozenset(CATALOGO_CAPAS)


def test_todas_las_rutas_de_consulta_son_url_completa() -> None:
    for clave, capa in CATALOGO_CAPAS.items():
        assert isinstance(capa, CapaConfig), clave
        assert capa.ruta_consulta.startswith("https://"), clave
        assert capa.ruta_consulta.endswith(f"/{capa.layer_id}/query"), clave


def test_catalogo_excluye_las_capas_sdp() -> None:
    # SDP vive en app/providers/sdp.py (EPSG:4686): no forma parte del
    # catálogo ArcGIS genérico.
    assert "tratamiento_sdp" not in CATALOGO_CAPAS
    assert "edificabilidad_sdp" not in CATALOGO_CAPAS


def test_baseline_evaluable_intacto() -> None:
    assert len(BLOQUES_EVALUABLES) == 19


# ---------------------------------------------------------------------------
# (b) Capa nueva → bloque contrato con los 5 campos y vigencia propia
# ---------------------------------------------------------------------------


async def test_capa_nueva_produce_bloque_con_cinco_campos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(CATALOGO_CAPAS, CAPA_PRUEBA.clave, CAPA_PRUEBA)
    async with _client_con_respuesta(200, _payload_features(1)) as client:
        bloque = await consultar_bloque_catalogo(
            client, CAPA_PRUEBA.clave, CAPA_PRUEBA, LAT, LNG
        )

    assert set(bloque) == CAMPOS_BLOQUE
    assert bloque["clave"] == "capa_prueba_f11"
    assert bloque["titulo"] == "capa_prueba_f11"
    assert bloque["estado"] == "ok"
    assert len(bloque["datos"]) == 1
    assert bloque["warnings"] == []

    (traza,) = bloque["source_traces"]
    assert set(traza) == CAMPOS_TRAZA
    # Vigencia propia de ESTA capa, no heredada de otras (FR-002).
    assert traza["data_vigencia"] == "2099-01-01"
    assert traza["source_name"] == "Capa de Prueba F11"
    assert traza["layer_id"] == "99"
    assert traza["service_url"] == URL_PRUEBA
    assert isinstance(traza["query_timestamp"], str) and traza["query_timestamp"]


# ---------------------------------------------------------------------------
# (c) 5xx degrada SOLO el bloque, sin FUENTE_5XX fatal
# ---------------------------------------------------------------------------


async def test_5xx_degrada_el_bloque_sin_propagar_error() -> None:
    async with _client_con_respuesta(
        500, {"error": {"code": 500, "message": "boom"}}
    ) as client:
        bloque = await consultar_bloque_catalogo(
            client, CAPA_PRUEBA.clave, CAPA_PRUEBA, LAT, LNG
        )

    assert set(bloque) == CAMPOS_BLOQUE
    assert bloque["estado"] == "no_encontrado"
    assert bloque["datos"] == []
    assert bloque["source_traces"] == []
    assert bloque["warnings"] == ["BLOQUE_DEGRADADO"]


# ---------------------------------------------------------------------------
# (d) Respuesta vacía → no_encontrado PERO con su trazabilidad
# ---------------------------------------------------------------------------


async def test_capa_vacia_deja_traza_poblada() -> None:
    async with _client_con_respuesta(200, _payload_features(0)) as client:
        bloque = await consultar_bloque_catalogo(
            client, CAPA_PRUEBA.clave, CAPA_PRUEBA, LAT, LNG
        )

    assert bloque["estado"] == "no_encontrado"
    assert bloque["datos"] == []
    assert bloque["warnings"] == []
    (traza,) = bloque["source_traces"]
    assert set(traza) == CAMPOS_TRAZA
    assert traza["data_vigencia"] == "2099-01-01"


# ---------------------------------------------------------------------------
# (e) Orquestador genérico: hoy cero llamadas; con capa nueva, la sirve
# ---------------------------------------------------------------------------


async def test_orquestador_no_llama_hoy() -> None:
    def handler_prohibido(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"llamada inesperada a {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler_prohibido))
    try:
        assert await consultar_bloques_catalogo_adicionales(client, LAT, LNG) == {}
    finally:
        await client.aclose()


async def test_orquestador_siere_capa_registrada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(CATALOGO_CAPAS, CAPA_PRUEBA.clave, CAPA_PRUEBA)
    async with _client_con_respuesta(200, _payload_features(1)) as client:
        bloques = await consultar_bloques_catalogo_adicionales(client, LAT, LNG)

    assert list(bloques) == ["capa_prueba_f11"]
    bloque = bloques["capa_prueba_f11"]
    assert bloque["estado"] == "ok"
    assert set(bloque["source_traces"][0]) == CAMPOS_TRAZA
