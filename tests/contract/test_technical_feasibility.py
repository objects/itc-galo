"""Contract tests Fase 3 — Bloque technical_feasibility (motor técnico)."""

from app.tecnico import analisis_tecnico, calcular_area_bruta, calcular_area_neta, calcular_cabida
from tests.conftest import CHIP_VALIDO, NormativaProviderStub, feature_valor, provider_arcgis_f3, server_lotes_f3
from tests.contract._f3_shared import CAMPOS_TRAZA
from tests.contract.test_urbanistic_parameters import provider_sdp_estandar, respuesta_rag_parametros


def test_calcular_area_neta():
    assert calcular_area_neta(1000.0, False) == 1000.0
    assert calcular_area_neta(1000.0, True) == 850.0


def test_calcular_cabida():
    assert calcular_cabida(850.0, 0.5) == 425.0
    assert calcular_cabida(None, 0.5) is None


def test_analisis_tecnico_determinista():
    geom = {"type": "Polygon", "coordinates": [[[0,0],[0,0.001],[0.001,0.001],[0.001,0],[0,0]]]}
    r1 = analisis_tecnico(geom, False, 0.5, 1000.0)
    r2 = analisis_tecnico(geom, False, 0.5, 1000.0)
    assert r1 == r2


async def test_bloque_technical_feasibility_estructura():
    servidor = server_lotes_f3(
        arcgis=provider_arcgis_f3(valor=[feature_valor(valor_m2=10_000_000)]),
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()
    bloque = reporte["technical_feasibility"]
    assert set(bloque.keys()) == {"estado", "dato", "interpretation", "source_trace"}
    assert bloque["estado"] in {"disponible", "no_encontrado"}
    assert set(bloque["source_trace"]) == CAMPOS_TRAZA


async def test_bloque_technical_feasibility_valores():
    servidor = server_lotes_f3(
        arcgis=provider_arcgis_f3(valor=[feature_valor(valor_m2=10_000_000)]),
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()
    bloque = reporte["technical_feasibility"]
    assert bloque["estado"] == "disponible"
    assert bloque["dato"]["viable"] is True
    assert bloque["dato"]["area_neta_m2"] is not None
