"""Contract tests F10 — bloque `market_dynamics` (T022, US1).

Verifica el shape completo del bloque (patron {estado, dato, interpretation,
source_trace}), los estados `disponible`/`no_encontrado`, la trazabilidad de 5
campos y la degradacion independiente del resto del informe (FR-002/FR-003/
FR-010/FR-014, SC-003). Sin red real ni Ollama: el corpus se inyecta como un
archivo JSONL temporal y el provider lee localmente.
"""

from __future__ import annotations

import json

from tests.conftest import (
    CHIP_VALIDO,
    NormativaProviderStub,
    respuesta_normativa_ok,
)
from tests.contract._f3_shared import CAMPOS_TRAZA

from app.providers.mercado import MercadoProvider


def _escribir_corpus(tmp_path, registros: list[dict]) -> str:
    """Escribe un corpus JSONL temporal y devuelve su ruta."""
    import hashlib

    lineas = [json.dumps(r, ensure_ascii=False) for r in registros]
    contenido = "\n".join(lineas) + "\n"
    ruta = tmp_path / "mercado.jsonl"
    ruta.write_text(contenido, encoding="utf-8")
    (tmp_path / "mercado.sha256").write_text(hashlib.sha256(contenido.encode()).hexdigest(), encoding="utf-8")
    return str(ruta)


def _registro_chapinero(precio=690000000, area=120, estrato=6, barrio="Chico Norte") -> dict:
    return {
        "id": "seed-001",
        "fuente": "seed",
        "url": None,
        "precio": precio,
        "area_m2": area,
        "precio_m2": round(precio / area, 2),
        "estrato": estrato,
        "amenidades": ["garaje"],
        "localidad": "Chapinero",
        "upl": "UPL24",
        "barrio": barrio,
        "fecha_captura": "2026-01-15",
    }


# --- Provider: consulta al corpus local ---


async def test_provider_devuelve_contexto_de_mercado_para_zona(tmp_path):
    ruta = _escribir_corpus(
        tmp_path,
        [
            _registro_chapinero(690000000, 120, 6, "Chico Norte"),
            _registro_chapinero(720000000, 130, 6, "Chico Norte"),
            _registro_chapinero(580000000, 90, 4, "Chapinero Alto"),
        ],
    )
    provider = MercadoProvider(ruta_corpus=ruta)
    try:
        contexto, trace = await provider.consultar_market_dynamics("Chapinero", "UPL24")
    finally:
        await provider.aclose()

    assert contexto is not None
    assert contexto.precio_m2_referencia == 5750000.0  # mediana de [5750000, 5538461.54, 6444444.44]
    assert contexto.estrato == 6
    assert contexto.oferta_competidora is not None
    total_ofertas = sum(c.conteo for c in contexto.oferta_competidora)
    assert total_ofertas == 3
    assert contexto.ritmo_absorcion is not None
    assert contexto.ritmo_absorcion.unidades_mes is not None
    assert contexto.ritmo_absorcion.criterio is not None


async def test_provider_devuelve_none_cuando_corpus_vacio(tmp_path):
    provider = MercadoProvider(ruta_corpus=str(tmp_path / "inexistente.jsonl"))
    try:
        contexto, trace = await provider.consultar_market_dynamics("Chapinero", "UPL24")
    finally:
        await provider.aclose()

    assert contexto is None
    assert trace is not None


async def test_provider_filtro_por_upl_sin_localidad(tmp_path):
    ruta = _escribir_corpus(tmp_path, [_registro_chapinero()])
    provider = MercadoProvider(ruta_corpus=ruta)
    try:
        contexto, _ = await provider.consultar_market_dynamics(None, "UPL24")
    finally:
        await provider.aclose()

    assert contexto is not None
    assert contexto.estrato == 6


async def test_provider_sin_registros_para_la_zona_devuelve_none(tmp_path):
    ruta = _escribir_corpus(tmp_path, [_registro_chapinero()])
    provider = MercadoProvider(ruta_corpus=ruta)
    try:
        contexto, _ = await provider.consultar_market_dynamics("Usaquén", "UPL25")
    finally:
        await provider.aclose()

    assert contexto is None


# --- Bloque market_dynamics en el informe ---


def _server_con_mercado(tmp_path, registros):
    from tests.conftest import provider_arcgis_f3, provider_mapas_estandar, provider_upl_estandar
    from app.main import ServidorLotes
    from app.providers.sdp import SDPProvider
    import httpx

    ruta = _escribir_corpus(tmp_path, registros)
    mercado = MercadoProvider(ruta_corpus=ruta)
    return ServidorLotes(
        provider_mapas_estandar(),
        provider_arcgis_f3(),
        provider_upl_estandar(),
        NormativaProviderStub(respuesta=respuesta_normativa_ok()),
        SDPProvider(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"type": "FeatureCollection", "features": []}))),
        provider_mercado=mercado,
    )


async def test_bloque_market_dynamics_disponible_en_informe(tmp_path):
    servidor = _server_con_mercado(
        tmp_path,
        [
            _registro_chapinero(690000000, 120, 6, "Chico Norte"),
            _registro_chapinero(720000000, 130, 6, "Chico Norte"),
        ],
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    bloque = reporte["market_dynamics"]
    assert bloque["estado"] == "disponible"
    assert set(bloque) == {"estado", "dato", "interpretation", "source_trace"}
    assert set(bloque["source_trace"]) == CAMPOS_TRAZA
    assert bloque["source_trace"]["source_name"] == "corpus-mercado"
    assert bloque["source_trace"]["layer_id"] == "mercado"
    assert bloque["source_trace"]["service_url"] == "data/corpus/mercado/mercado.jsonl"
    assert bloque["source_trace"]["data_vigencia"]
    assert bloque["dato"] is not None
    assert "precio_m2_referencia" in bloque["dato"]
    assert "estrato" in bloque["dato"]
    assert "oferta_competidora" in bloque["dato"]
    assert "ritmo_absorcion" in bloque["dato"]
    assert isinstance(bloque["interpretation"], str) and bloque["interpretation"]


async def test_bloque_market_dynamics_no_encontrado_sin_corpus():
    from tests.conftest import server_lotes_f3

    servidor = server_lotes_f3()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    bloque = reporte["market_dynamics"]
    assert bloque["estado"] == "no_encontrado"
    assert bloque["dato"] is None
    assert set(bloque["source_trace"]) == CAMPOS_TRAZA
    codigos = [w["codigo"] for w in reporte["warnings"] if "market_dynamics" in w.get("mensaje", "")]
    assert codigos == ["BLOQUE_SIN_DATO"]


async def test_bloque_market_dynamics_en_resumen(tmp_path):
    servidor = _server_con_mercado(
        tmp_path,
        [_registro_chapinero(690000000, 120, 6, "Chico Norte")],
    )
    try:
        resumen = await servidor.get_lot_summary_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "market_dynamics" in resumen
    bloque = resumen["market_dynamics"]
    assert set(bloque) == {"estado", "dato", "interpretation", "source_trace"}
    assert bloque["estado"] in {"disponible", "no_encontrado"}


async def test_degradacion_no_afecta_otros_bloques(tmp_path):
    servidor = _server_con_mercado(tmp_path, [_registro_chapinero()])
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "feasibility_score" in reporte
    assert reporte["lot_identity"]["chip"] == CHIP_VALIDO
    assert reporte["economic_context"]["estado"] == "disponible"
