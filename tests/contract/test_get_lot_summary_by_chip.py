"""Contract test de get_lot_summary_by_chip (T014, Historia de Usuario 1)."""

from __future__ import annotations

from tests.conftest import (
    CHIP_INEXISTENTE,
    CHIP_VALIDO,
    CODIGO_CATASTRAL,
    MANZANA,
    construir_servidor,
)

CAMPOS_TRAZA = {
    "source_name",
    "layer_id",
    "service_url",
    "data_vigencia",
    "query_timestamp",
}


async def test_resumen_consolidado_descriptivo_sin_geometria():
    servidor = construir_servidor()
    try:
        respuesta = await servidor.get_lot_summary_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    identidad = respuesta["identidad"]
    assert identidad["chip"] == CHIP_VALIDO
    assert identidad["codigo_catastral"] == CODIGO_CATASTRAL
    assert identidad["manzana"] == MANZANA
    assert "geometry" not in identidad  # el resumen es descriptivo (FR-011)
    assert set(identidad["source_trace"]) == CAMPOS_TRAZA

    por_fuente = respuesta["contexto_por_fuente"]
    assert len(por_fuente) == 4
    assert {bloque["fuente"] for bloque in por_fuente} == {
        "valor_referencia",
        "destino_economico",
        "reserva_vial",
        "obras_publicas",
    }
    for bloque in por_fuente:
        assert bloque["estado"] in {"disponible", "no_encontrado"}
        assert set(bloque["source_trace"]) == CAMPOS_TRAZA


async def test_resumen_no_incluye_puntaje_de_factibilidad():
    servidor = construir_servidor()
    try:
        respuesta = await servidor.get_lot_summary_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    texto = str(respuesta)
    assert "feasibility" not in texto.lower()
    assert "puntaje" not in texto.lower()


async def test_chip_inexistente_devuelve_lote_no_encontrado():
    servidor = construir_servidor()
    try:
        respuesta = await servidor.get_lot_summary_by_chip(CHIP_INEXISTENTE)
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "LOTE_NO_ENCONTRADO"
