"""Contract tests de trazabilidad (T034, FR-006/FR-008, SC-003/SC-004).

Cada dato incluye exactamente los 5 campos de SourceTrace y nunca se mezclan
vigencias distintas como una sola fotografia temporal (Principio III).
"""

from __future__ import annotations

from tests.conftest import (
    CHIP_VALIDO,
    construir_servidor,
    feature_destino,
    feature_valor,
    provider_arcgis_estandar,
)

CAMPOS_TRAZA = {
    "source_name",
    "layer_id",
    "service_url",
    "data_vigencia",
    "query_timestamp",
}


async def test_cada_dato_lleva_los_5_campos_de_trazabilidad():
    servidor = construir_servidor()
    try:
        respuesta = await servidor.resolve_lot_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    bloques = [respuesta["lote"]["source_trace"]]
    bloques += [bloque["source_trace"] for bloque in respuesta["contexto_tematico"].values()]
    assert len(bloques) == 5  # lote + 4 tematicas

    for traza in bloques:
        assert set(traza) == CAMPOS_TRAZA
        assert traza["source_name"]
        assert traza["layer_id"]
        assert traza["service_url"].startswith("http")
        assert traza["data_vigencia"]
        assert "T" in traza["query_timestamp"] and traza["query_timestamp"].endswith("Z")


async def test_nunca_se_mezclan_vigencias_distintas():
    # valorreferencia declara ANIO 2025 y destinolt ANIO 2022 (research.md D5)
    arcgis = provider_arcgis_estandar(
        valor=[feature_valor(valor_m2=3200000, anio=2025)],
        destino=[feature_destino(codigo="01", descripcion="VIVIENDA", anio=2022)],
    )
    servidor = construir_servidor(arcgis=arcgis)
    try:
        respuesta = await servidor.resolve_lot_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    contexto = respuesta["contexto_tematico"]
    vigencia_valor = contexto["valor_referencia"]["source_trace"]["data_vigencia"]
    vigencia_destino = contexto["destino_economico"]["source_trace"]["data_vigencia"]

    # Cada bloque conserva su propia vigencia: no se mezclan (FR-008, SC-004)
    assert vigencia_valor == "2025"
    assert vigencia_destino == "2022"
    assert vigencia_valor != vigencia_destino
    # Y la vigencia del dato es coherente con la de su trazabilidad
    assert contexto["valor_referencia"]["dato"]["vigencia"] == vigencia_valor
    assert contexto["destino_economico"]["dato"]["vigencia"] == vigencia_destino


async def test_trazabilidad_en_resumen_por_fuente():
    servidor = construir_servidor()
    try:
        respuesta = await servidor.get_lot_summary_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    bloques = [respuesta["identidad"]["source_trace"]]
    bloques += [bloque["source_trace"] for bloque in respuesta["contexto_por_fuente"]]
    assert len(bloques) == 5
    for traza in bloques:
        assert set(traza) == CAMPOS_TRAZA
