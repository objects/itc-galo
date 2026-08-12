"""Contract tests de escenarios del quickstart (T036, SC-005/SC-006/SC-003/SC-004).

Escenarios 1 (resumen por CHIP), 2 (CHIP inexistente), 4 (fuera de cobertura) y
5 (direccion sin credencial) del quickstart.md.
"""

from __future__ import annotations

import httpx

from tests.conftest import (
    CHIP_INEXISTENTE,
    CHIP_VALIDO,
    construir_servidor,
    geocodificar_unica,
    provider_arcgis_estandar,
)
from app.providers.mapas_bogota import MapasBogotaProvider

CAMPOS_TRAZA = {
    "source_name",
    "layer_id",
    "service_url",
    "data_vigencia",
    "query_timestamp",
}


async def test_escenario_1_chip_valido_devuelve_resumen_con_trazabilidad():
    servidor = construir_servidor()
    try:
        respuesta = await servidor.get_lot_summary_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    assert set(respuesta) == {"identidad", "contexto_por_fuente"}
    assert respuesta["identidad"]["chip"] == CHIP_VALIDO
    assert len(respuesta["contexto_por_fuente"]) == 3
    for bloque in respuesta["contexto_por_fuente"]:
        assert set(bloque["source_trace"]) == CAMPOS_TRAZA


async def test_escenario_2_chip_inexistente_devuelve_error_claro():
    servidor = construir_servidor()
    try:
        respuesta = await servidor.get_lot_summary_by_chip(CHIP_INEXISTENTE)
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "LOTE_NO_ENCONTRADO"
    assert respuesta["error"]["message"]


async def test_escenario_4_coordenadas_fuera_de_bogota_devuelve_error_claro():
    arcgis = provider_arcgis_estandar(lotes=[])
    servidor = construir_servidor(arcgis=arcgis)
    try:
        respuesta = await servidor.resolve_lot_by_coordinates(6.25, -75.57)
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "FUERA_DE_COBERTURA"


async def test_escenario_5_direccion_sin_credencial_falla_rapido():
    def handler(request: httpx.Request) -> httpx.Response:
        # Si se llamara a la fuente, esta prueba fallaria por si sola
        return httpx.Response(200, json=geocodificar_unica())

    mapas = MapasBogotaProvider(transport=httpx.MockTransport(handler), api_key=None)
    servidor = construir_servidor(mapas=mapas)
    try:
        respuesta = await servidor.resolve_lot_by_address("Calle 26 # 69-76")
        # Y las consultas por CHIP/coordenadas siguen funcionando sin credencial (FR-010)
        resumen = await servidor.get_lot_summary_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "CREDENCIAL_FALTANTE"
    assert "error" not in resumen
