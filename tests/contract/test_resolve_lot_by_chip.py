"""Contract test de resolve_lot_by_chip (T013, Historia de Usuario 1)."""

from __future__ import annotations

from tests.conftest import (
    CHIP_INEXISTENTE,
    CHIP_VALIDO,
    CODIGO_CATASTRAL,
    MANZANA,
    construir_servidor,
)


async def test_resuelve_lote_valido_con_contexto_tematico():
    servidor = construir_servidor()
    try:
        respuesta = await servidor.resolve_lot_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    lote = respuesta["lote"]
    assert lote["chip"] == CHIP_VALIDO
    assert lote["codigo_catastral"] == CODIGO_CATASTRAL
    assert lote["manzana"] == MANZANA
    assert lote["direccion_normalizada"] == "CRA 12 # 10-20"
    assert lote["barrio"] == "LAS NIEVES"
    assert "geometry" in lote
    assert set(lote["centroid"]) == {"lat", "lng"}
    assert set(lote["source_trace"]) == {
        "source_name",
        "layer_id",
        "service_url",
        "data_vigencia",
        "query_timestamp",
    }

    contexto = respuesta["contexto_tematico"]
    assert set(contexto) == {"valor_referencia", "destino_economico", "reserva_vial", "obras_publicas"}
    for bloque in contexto.values():
        assert bloque["estado"] in {"disponible", "no_encontrado"}
        assert set(bloque["source_trace"]) == {
            "source_name",
            "layer_id",
            "service_url",
            "data_vigencia",
            "query_timestamp",
        }


async def test_chip_inexistente_devuelve_lote_no_encontrado():
    servidor = construir_servidor()
    try:
        respuesta = await servidor.resolve_lot_by_chip(CHIP_INEXISTENTE)
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "LOTE_NO_ENCONTRADO"
    assert "Verifica el identificador" in respuesta["error"]["message"]
