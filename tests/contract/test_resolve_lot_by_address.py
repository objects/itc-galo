"""Contract test de resolve_lot_by_address (T021, Historia de Usuario 2)."""

from __future__ import annotations

import httpx

from tests.conftest import (
    CHIP_VALIDO,
    CODIGO_CATASTRAL,
    MANZANA,
    construir_servidor,
    geocodificar_unica,
    geocodificar_vacia,
    geocodificar_varias,
    provider_arcgis_estandar,
    provider_mapas_estandar,
)
from app.providers.mapas_bogota import MapasBogotaProvider

DIRECCION = "Calle 26 # 69-76"


async def test_resolucion_unica_devuelve_lote():
    servidor = construir_servidor()
    try:
        respuesta = await servidor.resolve_lot_by_address(DIRECCION)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    lote = respuesta["lote"]
    assert lote["chip"] == CHIP_VALIDO
    assert lote["codigo_catastral"] == CODIGO_CATASTRAL
    assert lote["manzana"] == MANZANA
    assert lote["direccion_normalizada"] == DIRECCION
    assert set(lote["source_trace"]) == {
        "source_name",
        "layer_id",
        "service_url",
        "data_vigencia",
        "query_timestamp",
    }
    assert "contexto_tematico" in respuesta


async def test_direccion_no_localizada_no_inventa_lote():
    def handler(request: httpx.Request) -> httpx.Response:
        cmd = request.url.params.get("cmd")
        if cmd == "geocodificar":
            return httpx.Response(200, json=geocodificar_vacia())
        return httpx.Response(404, json={"error": "sin respuesta simulada"})

    mapas = MapasBogotaProvider(
        transport=httpx.MockTransport(handler), api_key="clave-de-prueba"
    )
    servidor = construir_servidor(mapas=mapas)
    try:
        respuesta = await servidor.resolve_lot_by_address("Calle 99 # 99-99")
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "DIRECCION_NO_LOCALIZADA"
    assert "lote" not in respuesta


async def test_multiples_candidatos_no_elige_arbitrariamente():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cmd") == "geocodificar":
            return httpx.Response(200, json=geocodificar_varias())
        return httpx.Response(404, json={"error": "sin respuesta simulada"})

    mapas = MapasBogotaProvider(
        transport=httpx.MockTransport(handler), api_key="clave-de-prueba"
    )
    arcgis = provider_arcgis_estandar()
    servidor = construir_servidor(mapas=mapas, arcgis=arcgis)
    try:
        respuesta = await servidor.resolve_lot_by_address(DIRECCION)
    finally:
        await servidor.aclose()

    assert respuesta.get("multiples_candidatos") is True
    assert len(respuesta["candidatos"]) == 2
    for candidato in respuesta["candidatos"]:
        assert set(candidato) == {"direccion_normalizada", "centroid"}
        assert set(candidato["centroid"]) == {"lat", "lng"}
    assert "lote" not in respuesta
    traza = respuesta["source_trace"]
    assert traza["source_name"] == "mapas_bogota"
    assert traza["layer_id"] == "geocodificar"
    assert set(traza) == {
        "source_name",
        "layer_id",
        "service_url",
        "data_vigencia",
        "query_timestamp",
    }


async def test_credencial_faltante_falla_rapido_sin_llamar_fuentes():
    llamadas = []

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas.append(request.url)
        return httpx.Response(200, json=geocodificar_unica())

    mapas = MapasBogotaProvider(transport=httpx.MockTransport(handler), api_key=None)
    servidor = construir_servidor(mapas=mapas)
    try:
        respuesta = await servidor.resolve_lot_by_address(DIRECCION)
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "CREDENCIAL_FALTANTE"
    assert "MAPAS_BOGOTA_APIKEY" in respuesta["error"]["message"]
    assert llamadas == []  # fail-fast: nunca se consulto la fuente
