"""Contract tests Fase 2 — Bloque financial_analysis (motor financiero).

Valida el bloque derivado del informe de factibilidad: estructura
{estado, dato, interpretation, source_trace}, cálculo puro y determinista
(SC-003, sin LLM ni reloj), degradación cuando faltan datos de entrada
(no_encontrado + BLOQUE_SIN_DATO, FR-014) y la regla de scoring
r_financiero_viable (+10). También cubre la retrocompatibilidad del campo
(financial_analysis: None por defecto).

Los tests usan httpx.MockTransport sobre los providers simulados de
tests/conftest.py. Ninguna prueba hace llamadas de red reales.

Nota sobre la fuente de datos: el bloque financial_analysis NO consulta
fuentes externas adicionales; combina como entradas puras datos ya
consultados de otros bloques:
1. area_terreno (economic_context / capa Predio, PREATERRE)
2. precio_m2_terreno (market_context / valorreferencia, VALOR_M2)
3. cos (urbanistic_parameters / edificabilidad, capa 14 o RAG)
"""

from __future__ import annotations

import pytest

from app.financiero import (
    analisis_financiero,
    calcular_area_vendible,
    calcular_costos,
    calcular_flujo_neto_anual,
    calcular_ingresos,
    calcular_margen,
    calcular_punto_equilibrio,
    calcular_tir,
    calcular_vpn,
)
from tests.conftest import (
    CHIP_VALIDO,
    NormativaProviderStub,
    feature_valor,
    provider_arcgis_f3,
    server_lotes_f3,
)
from tests.contract._f3_shared import CAMPOS_TRAZA
from tests.contract.test_urbanistic_parameters import (
    provider_sdp_estandar,
    respuesta_rag_parametros,
    respuesta_rag_sin_parametros,
)


# --- Tests de las funciones puras (SC-003, determinismo) ---


def test_calcular_area_vendible():
    """area_vendible = area_terreno * COS."""
    assert calcular_area_vendible(1000.0, 0.5) == 500.0


def test_calcular_area_vendible_falta_dato():
    """Falta area_terreno o COS -> None (degradación, no cero silencioso)."""
    assert calcular_area_vendible(None, 0.5) is None
    assert calcular_area_vendible(1000.0, None) is None


def test_calcular_ingresos():
    """ingresos = area_vendible * precio_m2."""
    assert calcular_ingresos(500.0, 10_000_000.0) == 5_000_000_000.0


def test_calcular_costos():
    """costos = area_terreno * costo_terreno + area_vendible * costo_construccion."""
    # costos unitarios explícitos para independencia del entorno
    costos = calcular_costos(
        1000.0,
        500.0,
        costo_construccion=1_800_000.0,
        costo_terreno_unitario=3_200_000.0,
    )
    assert costos == 1000.0 * 3_200_000.0 + 500.0 * 1_800_000.0


def test_calcular_margen():
    """margen = (ingresos - costos) / ingresos * 100."""
    assert calcular_margen(5_000_000_000.0, 4_100_000_000.0) == pytest.approx(18.0)


def test_calcular_margen_ingresos_cero():
    """ingresos == 0 -> None (evitar división por cero)."""
    assert calcular_margen(0.0, 100.0) is None


def test_calcular_flujo_neto_anual():
    """flujo_neto = (ingresos - costos) * (1 - tasa)."""
    flujo = calcular_flujo_neto_anual(5_000_000_000.0, 4_100_000_000.0, tasa=0.35)
    assert flujo == pytest.approx(900_000_000.0 * 0.65)


def test_calcular_vpn_determinista():
    """VPN por fórmula cerrada; mismo input -> mismo output (SC-003)."""
    vpn_1 = calcular_vpn(100.0, tasa=0.10, num_periodos=3)
    vpn_2 = calcular_vpn(100.0, tasa=0.10, num_periodos=3)
    assert vpn_1 == vpn_2
    # 100/1.1 + 100/1.1^2 + 100/1.1^3
    esperado = 100 / 1.1 + 100 / 1.1**2 + 100 / 1.1**3
    assert vpn_1 == pytest.approx(esperado)


def test_calcular_vpn_tasa_cero():
    """tasa == 0 -> flujo * n (sin descuento)."""
    assert calcular_vpn(100.0, tasa=0.0, num_periodos=3) == pytest.approx(300.0)


def test_calcular_tir_determinista():
    """TIR por bisección; mismo input -> mismo output (SC-003)."""
    tir_1 = calcular_tir(100.0, num_periodos=5)
    tir_2 = calcular_tir(100.0, num_periodos=5)
    assert tir_1 == tir_2
    assert tir_1 is not None
    assert tir_1 > 0.0


def test_calcular_tir_flujo_negativo():
    """Flujo neto negativo -> TIR negativa (proyecto no rentable)."""
    tir = calcular_tir(-100.0, num_periodos=5)
    assert tir is not None
    assert tir < 0.0


def test_calcular_punto_equilibrio():
    """punto_equilibrio = costos_fijos / (precio_venta - costo_variable)."""
    pe = calcular_punto_equilibrio(1_000_000.0, 500_000.0, 300_000.0)
    assert pe == pytest.approx(5.0)


def test_calcular_punto_equilibrio_sin_margen():
    """precio_venta <= costo_variable -> None (no hay margen)."""
    assert calcular_punto_equilibrio(1_000_000.0, 200_000.0, 300_000.0) is None


def test_analisis_financiero_determinista():
    """analisis_financiero es puro: mismo input -> mismo output (SC-003)."""
    entrada = (1000.0, 10_000_000.0, 0.5)
    r1 = analisis_financiero(*entrada)
    r2 = analisis_financiero(*entrada)
    assert r1 == r2


def test_analisis_financiero_valores():
    """Valores calculados con entradas limpias (área 1000, precio 10M, COS 0.5)."""
    r = analisis_financiero(1000.0, 10_000_000.0, 0.5)
    assert r["area_vendible_m2"] == 500.0
    assert r["ingresos_totales"] == 5_000_000_000.0
    assert r["costos_totales"] == pytest.approx(4_100_000_000.0)
    assert r["margen_porcentual"] == pytest.approx(18.0)
    assert r["vpn"] is not None and r["vpn"] > 0
    assert r["tir"] is not None and r["tir"] > 0.12
    assert r["viable"] is True


def test_analisis_financiero_falta_dato():
    """Falta un dato de entrada -> todos los indicadores None, viable None.

    `viable` es None cuando no hay datos suficientes (degradación, M2); solo
    es True/False cuando el cálculo pudo ejecutarse con los tres insumos.
    """
    r = analisis_financiero(None, 10_000_000.0, 0.5)
    assert r["area_vendible_m2"] is None
    assert r["ingresos_totales"] is None
    assert r["costos_totales"] is None
    assert r["margen_porcentual"] is None
    assert r["vpn"] is None
    assert r["tir"] is None
    assert r["viable"] is None


# --- Tests de integración: bloque financial_analysis en el informe ---


async def test_bloque_financial_analysis_estructura():
    """Bloque tiene estado, dato, interpretation y source_trace (FR-001, FR-004/FR-005)."""
    servidor = server_lotes_f3(
        arcgis=provider_arcgis_f3(valor=[feature_valor(valor_m2=10_000_000)]),
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    bloque = reporte["financial_analysis"]
    assert set(bloque.keys()) == {"estado", "dato", "interpretation", "source_trace"}
    assert bloque["estado"] == "disponible"
    assert bloque["dato"] is not None
    assert set(bloque["source_trace"].keys()) == CAMPOS_TRAZA


async def test_bloque_financial_analysis_valores():
    """Bloque calcula los indicadores a partir de area_terreno, precio_m2 y COS."""
    servidor = server_lotes_f3(
        arcgis=provider_arcgis_f3(valor=[feature_valor(valor_m2=10_000_000)]),
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    dato = reporte["financial_analysis"]["dato"]
    # area_terreno = PREATERRE (3704.8), COS = 0.60 (RAG), precio_m2 = 10M
    assert dato["area_vendible_m2"] == pytest.approx(3704.8 * 0.60)
    assert dato["ingresos_totales"] == pytest.approx(3704.8 * 0.60 * 10_000_000)
    assert dato["costos_totales"] is not None
    assert dato["margen_porcentual"] is not None
    assert dato["vpn"] is not None and dato["vpn"] > 0
    assert dato["tir"] is not None and dato["tir"] > 0.12
    assert dato["viable"] is True


async def test_bloque_financial_analysis_source_trace():
    """Bloque tiene source_trace con trazabilidad de la fuente (FR-010)."""
    servidor = server_lotes_f3(
        arcgis=provider_arcgis_f3(valor=[feature_valor(valor_m2=10_000_000)]),
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    trace = reporte["financial_analysis"]["source_trace"]
    assert "valorreferencia" in trace["source_name"].lower()
    assert "data_vigencia" in trace


async def test_degradacion_faltan_datos():
    """Falta un dato de entrada -> no_encontrado + warning BLOQUE_SIN_DATO (FR-014)."""
    # Sin valor de referencia (market_context no disponible) -> falta precio_m2
    servidor = server_lotes_f3(
        arcgis=provider_arcgis_f3(valor=[]),
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    bloque = reporte["financial_analysis"]
    assert bloque["estado"] == "no_encontrado"
    assert bloque["dato"] is None
    warnings_bloque = [
        w for w in reporte["warnings"]
        if "financial_analysis" in w.get("mensaje", "")
    ]
    assert len(warnings_bloque) == 1
    assert warnings_bloque[0]["codigo"] == "BLOQUE_SIN_DATO"


async def test_degradacion_sin_cos():
    """Sin COS (urbanistic_parameters no disponible) -> no_encontrado + BLOQUE_SIN_DATO."""
    # SDP sin features -> urbanistic_parameters no_encontrado -> cos None
    servidor = server_lotes_f3(
        arcgis=provider_arcgis_f3(valor=[feature_valor(valor_m2=10_000_000)]),
        normativa=NormativaProviderStub(respuesta=respuesta_rag_sin_parametros()),
        sdp=provider_sdp_estandar(tratamiento=[]),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    bloque = reporte["financial_analysis"]
    assert bloque["estado"] == "no_encontrado"
    assert bloque["dato"] is None


async def test_degradacion_no_rompe_reporte():
    """Falta un dato -> los demás bloques del reporte se construyen normalmente."""
    servidor = server_lotes_f3(
        arcgis=provider_arcgis_f3(valor=[]),
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert reporte["lot_identity"]["chip"] == CHIP_VALIDO
    assert reporte["market_context"]["estado"] == "no_encontrado"
    assert reporte["economic_context"]["estado"] == "disponible"
    assert "feasibility_score" in reporte


# --- Tests de scoring: r_financiero_viable (+10) ---


async def test_scoring_financiero_viable():
    """Bloque disponible y viable -> +10 (r_financiero_viable)."""
    servidor = server_lotes_f3(
        arcgis=provider_arcgis_f3(valor=[feature_valor(valor_m2=10_000_000)]),
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score = reporte["feasibility_score"]
    assert "r_financiero_viable" in score["rules_applied"]
    assert any("Análisis financiero viable" in r for r in score["reasons"])


async def test_scoring_financiero_no_viable():
    """Bloque disponible pero no viable -> sin +10 (r_financiero_viable ausente).

    Se fija un precio_m2 deliberadamente bajo (1M COP/m²) para que los costos
    (terreno 3.2M/m² + construcción 1.8M/m²) superen los ingresos con holgura:
    con area_terreno=3704.8 m² y COS=0.60, ingresos ≈ 2.22B COP frente a
    costos ≈ 15.86B COP. No se depende del default de costo_terreno_m2.
    """
    servidor = server_lotes_f3(
        arcgis=provider_arcgis_f3(valor=[feature_valor(valor_m2=1_000_000)]),
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    bloque = reporte["financial_analysis"]
    assert bloque["estado"] == "disponible"
    assert bloque["dato"]["viable"] is False
    # El precio bajo garantiza ingresos < costos (no viable por construcción).
    assert bloque["dato"]["ingresos_totales"] < bloque["dato"]["costos_totales"]
    score = reporte["feasibility_score"]
    assert "r_financiero_viable" not in score["rules_applied"]


async def test_scoring_financiero_no_disponible():
    """Bloque no_encontrado -> sin +10 (r_financiero_viable ausente)."""
    servidor = server_lotes_f3(
        arcgis=provider_arcgis_f3(valor=[]),
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score = reporte["feasibility_score"]
    assert "r_financiero_viable" not in score["rules_applied"]


# --- Tests de retrocompatibilidad ---


async def test_financial_analysis_default_none():
    """El campo financial_analysis es opcional: None por defecto (retrocompatibilidad)."""
    from app.models import InformeFactibilidad

    assert InformeFactibilidad.model_fields["financial_analysis"].default is None
    assert not InformeFactibilidad.model_fields["financial_analysis"].is_required()

    servidor = server_lotes_f3(
        arcgis=provider_arcgis_f3(valor=[feature_valor(valor_m2=10_000_000)]),
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    reporte_legado = {k: v for k, v in reporte.items() if k != "financial_analysis"}
    assert "financial_analysis" not in reporte_legado
    assert reporte["financial_analysis"] is not None
