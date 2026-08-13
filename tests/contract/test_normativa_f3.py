"""Contract tests F3 — evidencia normativa del POT (T015, US2, FR-008/FR-009).

Consulta explicita del usuario, consulta automatica construida desde el contexto
del lote (UPL + localidad + clasificacion), degradacion sin Ollama/corpus
(NORMATIVA_NO_DISPONIBLE) y sin resultados (NORMATIVA_SIN_RESULTADOS), con el
resto del reporte completo (SC-005).

Nota: la tool `get_feasibility_report` está implementada (commit 7e3b6c1);
estos tests pasan.
"""

from __future__ import annotations

from app.errores import CorpusNoIngestadoError, OllamaNoDisponibleError
from tests.conftest import (
    CHIP_VALIDO,
    NormativaProviderStub,
    provider_upl_estandar,
    respuesta_normativa_ok,
    respuesta_normativa_sin_resultados,
    server_lotes_f3,
)
from tests.contract._f3_shared import BLOQUES_RAIZ


def _verificar_resto_del_reporte_completo(reporte: dict) -> None:
    """El reporte se entrega completo pese a la degradacion de normative_evidence (FR-009/SC-005).

    Valida al menos: los 10 bloques raiz, lot_identity presente,
    economic_context con estado valido y feasibility_score entero en [0,100].
    """
    assert set(reporte) == BLOQUES_RAIZ
    assert reporte["lot_identity"]["codigo_catastral"] == "006101016001"
    assert reporte["economic_context"]["estado"] in {"disponible", "no_encontrado"}
    assert isinstance(reporte["feasibility_score"]["score"], int)
    assert 0 <= reporte["feasibility_score"]["score"] <= 100


async def test_consulta_explicita_llega_al_provider_con_consulta_y_top_k():
    """consulta del usuario -> el NormativaProvider recibe ese texto y el top_k (FR-008)."""
    stub = NormativaProviderStub(respuesta=respuesta_normativa_ok())
    servidor = server_lotes_f3(normativa=stub)
    try:
        reporte = await servidor.get_feasibility_report(
            chip=CHIP_VALIDO, consulta="usos del suelo en Chapinero", top_k=5
        )
    finally:
        await servidor.aclose()

    assert stub.llamadas, "El NormativaProvider debió ser consultado"
    llamada = stub.llamadas[-1]
    assert llamada["consulta"] == "usos del suelo en Chapinero"
    assert llamada["top_k"] == 5
    assert reporte["normative_evidence"]["consulta"] == "usos del suelo en Chapinero"
    assert reporte["normative_evidence"]["consulta_automatica"] is False
    assert reporte["normative_evidence"]["sin_resultados"] is False
    # SC-004: el articulo se serializa como str (el provider F2 lo emite int) con cita literal.
    items = reporte["normative_evidence"]["items"]
    assert items and items[0]["articulo"] == "361"
    assert isinstance(items[0]["articulo"], str)
    assert items[0]["texto_cita"], "texto_cita no puede estar vacio (cita literal verificable)"


async def test_consulta_automatica_usa_upl_localidad_y_clasificacion():
    """Sin consulta -> el provider recibe UPL + localidad + clasificacion y upl=<codigo> (FR-008)."""
    stub = NormativaProviderStub(respuesta=respuesta_normativa_ok())
    servidor = server_lotes_f3(normativa=stub)
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert stub.llamadas, "El NormativaProvider debió ser consultado"
    llamada = stub.llamadas[-1]
    assert "Chapinero" in llamada["consulta"]
    assert "UPL24" in llamada["consulta"]
    assert "urbano" in llamada["consulta"].lower()
    assert llamada["upl"] == "UPL24"
    assert llamada["top_k"] == 3  # default del contrato
    assert reporte["normative_evidence"]["consulta_automatica"] is True


async def test_consulta_automatica_sin_upl_no_filtra_por_territorio():
    """Lote sin UPL -> consulta automatica sin filtro territorial (upl=None), sin "UPL24" (contrato:356)."""
    stub = NormativaProviderStub(respuesta=respuesta_normativa_ok())
    servidor = server_lotes_f3(
        upl=provider_upl_estandar(upl_features=[]),
        normativa=stub,
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert stub.llamadas, "El NormativaProvider debió ser consultado"
    llamada = stub.llamadas[-1]
    assert llamada["upl"] is None
    assert "UPL24" not in llamada["consulta"]
    assert reporte["normative_evidence"]["consulta_automatica"] is True
    codigos_warning = {w["codigo"] for w in reporte["warnings"]}
    assert "UPL_NO_ENCONTRADA" in codigos_warning
    _verificar_resto_del_reporte_completo(reporte)


async def test_rag_corpus_no_ingestado_degrada_evidencia_vacia_y_reporta_completo():
    """CorpusNoIngestadoError -> items vacios + causa + warning, el resto del reporte completo (FR-009/SC-005)."""
    stub = NormativaProviderStub(error=CorpusNoIngestadoError())
    servidor = server_lotes_f3(normativa=stub)
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    evidencia = reporte["normative_evidence"]
    assert evidencia["items"] == []
    assert evidencia["causa"] == "CORPUS_NO_INGESTADO"
    codigos_warning = {w["codigo"] for w in reporte["warnings"]}
    assert "NORMATIVA_NO_DISPONIBLE" in codigos_warning
    # El resto del reporte se entrega completo: no es un error de la tool (FR-012)
    _verificar_resto_del_reporte_completo(reporte)


async def test_rag_ollama_no_disponible_degrada_evidencia_vacia_y_reporta_completo():
    """OllamaNoDisponibleError -> items vacios + causa OLLAMA_NO_DISPONIBLE + warning."""
    stub = NormativaProviderStub(error=OllamaNoDisponibleError(modelo="qwen3:8b"))
    servidor = server_lotes_f3(normativa=stub)
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    evidencia = reporte["normative_evidence"]
    assert evidencia["items"] == []
    assert evidencia["causa"] == "OLLAMA_NO_DISPONIBLE"
    codigos_warning = {w["codigo"] for w in reporte["warnings"]}
    assert "NORMATIVA_NO_DISPONIBLE" in codigos_warning
    _verificar_resto_del_reporte_completo(reporte)


async def test_sin_resultados_degrada_evidencia_vacia_con_advertencia():
    """Consulta sin resultados -> items vacios, sin_resultados true, causa SIN_RESULTADOS + warning."""
    stub = NormativaProviderStub(respuesta=respuesta_normativa_sin_resultados())
    servidor = server_lotes_f3(normativa=stub)
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    evidencia = reporte["normative_evidence"]
    assert evidencia["items"] == []
    assert evidencia["sin_resultados"] is True
    assert evidencia["causa"] == "SIN_RESULTADOS"
    codigos_warning = {w["codigo"] for w in reporte["warnings"]}
    assert "NORMATIVA_SIN_RESULTADOS" in codigos_warning
    _verificar_resto_del_reporte_completo(reporte)
