"""Contract tests F3 — trazabilidad de los bloques del reporte (T021, FR-010, SC-002).

El 100% de los bloques de datos del reporte incluye source_trace con los 5
campos (source_name, layer_id, service_url, data_vigencia, query_timestamp);
economic_context lleva data_vigencia = PREVACTUAL del registro (2026) y
normative_evidence el source_name del corpus (Decreto 555 de 2021).

NOTA (TDD red): la tool `get_feasibility_report` AUN NO existe; estos tests
fallan con AttributeError hasta su implementacion (fase posterior).
"""

from __future__ import annotations

from tests.conftest import (
    CHIP_VALIDO,
    NormativaProviderStub,
    respuesta_normativa_ok,
    server_lotes_f3,
)
from tests.contract._f3_shared import CAMPOS_TRAZA

# Bloques de datos del reporte que DEBEN llevar source_trace (7 de los 10 bloques).
BLOQUES_CON_TRAZA = [
    "lot_identity",
    "administrative_context",
    "planning_constraints",
    "market_context",
    "environment_context",
    "economic_context",
    "normative_evidence",
]


async def test_los_7_bloques_de_datos_llevan_los_5_campos_de_trazabilidad():
    """SC-002: 100% de bloques de datos con source_trace de 5 campos."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    for nombre in BLOQUES_CON_TRAZA:
        traza = reporte[nombre]["source_trace"]
        assert set(traza) == CAMPOS_TRAZA, nombre
        assert traza["source_name"], nombre
        assert traza["layer_id"], nombre
        assert traza["service_url"].startswith("http"), nombre
        assert traza["data_vigencia"], nombre
        assert "T" in traza["query_timestamp"] and traza["query_timestamp"].endswith("Z"), nombre


async def test_economic_context_vigencia_es_prevactual_del_registro():
    """data_vigencia del bloque economico = PREVACTUAL del fixture (research H7): 2026."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    economico = reporte["economic_context"]
    assert economico["source_trace"]["data_vigencia"] == "2026"
    assert economico["dato"]["vigencia"] == "2026"
    assert economico["source_trace"]["data_vigencia"] == economico["dato"]["vigencia"]


async def test_normative_evidence_traza_al_corpus_decreto_555():
    """source_trace de normative_evidence apunta al corpus Decreto 555/2021."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    traza = reporte["normative_evidence"]["source_trace"]
    assert traza["source_name"] == "Decreto 555 de 2021 (POT Bogotá)"
    assert traza["layer_id"] == "Decreto_555_2021"
    assert traza["data_vigencia"] == "2021-12-30"


async def test_upl_anidada_en_administrative_context_lleva_su_propia_traza():
    """El objeto UPL (anidado) tambien conserva los 5 campos (FR-010)."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    traza_upl = reporte["administrative_context"]["upl"]["source_trace"]
    assert set(traza_upl) == CAMPOS_TRAZA


async def test_query_timestamp_raiz_es_iso8601_utc():
    """query_timestamp raiz del reporte sigue el patron ISO 8601 UTC de los source_trace (contrato:198)."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    marca = reporte["query_timestamp"]
    assert "T" in marca and marca.endswith("Z")
