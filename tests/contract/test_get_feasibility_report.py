"""Contract tests F3 — Tool MCP `get_feasibility_report` (T008, US1, FR-001 a FR-011).

Shape completo de los 10 bloques del reporte, patron {estado, dato,
interpretation, source_trace} en los bloques tematicos/economicos, ejemplo del
contrato con economic_context disponible (2 filas, fila dominante por mayor
PREAUSO) y determinismo del score (SC-003).

Nota: la tool `get_feasibility_report` está implementada y registrada en
app/main.py (commit 7e3b6c1); estos tests pasan.
"""

from __future__ import annotations

from tests.conftest import (
    CHIP_VALIDO,
    NormativaProviderStub,
    PAYLOAD_PREDIO_VACIO,
    feature_lote,
    feature_upl,
    provider_arcgis_f3,
    provider_upl_estandar,
    respuesta_normativa_ok,
    server_lotes_f3,
)
from tests.contract._f3_shared import BLOQUES_CON_ESTADO, BLOQUES_RAIZ, CAMPOS_TRAZA

# Terminos de reglas urbanisticas que el reporte NO debe citar (FR-014): el
# score y las interpretations solo hablan de datos reales de las fuentes.
TERMINOS_NORMATIVOS_INVENTADOS = [
    "altura máxima",
    "altura permitida",
    "índice de construcción",
    "índice de ocupación",
    "cesión",
    "retiro",
    "edificabilidad",
    "aprovechamiento",
]


async def test_reporte_por_chip_devuelve_los_10_bloques():
    """CHIP valido -> reporte con exactamente los 10 bloques del contrato (FR-001)."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert set(reporte) == BLOQUES_RAIZ


async def test_lot_identity_tiene_identidad_completa():
    """lot_identity: chip, codigo catastral, manzana, direccion, barrio, geometry, centroid, source_trace."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    identidad = reporte["lot_identity"]
    assert identidad["chip"] == CHIP_VALIDO
    assert identidad["codigo_catastral"] == "006101016001"
    assert identidad["manzana"] == "006101016"
    assert isinstance(identidad["direccion_normalizada"], str)
    assert isinstance(identidad["barrio"], str)
    assert identidad["geometry"]["type"] == "Polygon"
    assert "lat" in identidad["centroid"] and "lng" in identidad["centroid"]
    assert set(identidad["source_trace"]) == CAMPOS_TRAZA


async def test_bloques_tematicos_con_patron_estado_dato_interpretation():
    """Cada bloque tematico/economico usa {estado, dato, interpretation, source_trace} (FR-004/FR-005)."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    for nombre in BLOQUES_CON_ESTADO:
        bloque = reporte[nombre]
        assert set(bloque) == {"estado", "dato", "interpretation", "source_trace"}, nombre
        assert bloque["estado"] in {"disponible", "no_encontrado"}, nombre
        assert isinstance(bloque["interpretation"], str) and bloque["interpretation"], nombre
        assert set(bloque["source_trace"]) == CAMPOS_TRAZA, nombre
        if bloque["estado"] == "disponible":
            assert bloque["dato"] is not None, nombre
        else:
            assert bloque["dato"] is None, nombre


async def test_economic_context_destino_disponible_del_contrato():
    """economic_context: fila dominante por mayor PREAUSO (04/015, 40453.8 m2) + usos (2 filas)."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    economico = reporte["economic_context"]
    assert economico["estado"] == "disponible"
    dato = economico["dato"]
    assert dato["codigo_destino"] == "04"
    assert dato["descripcion_destino"] == "Dotacional público"
    assert dato["uso"] == "015 - Oficinas y Consultorios oficiales en NPH"
    assert dato["area_uso"] == 40453.8
    assert dato["area_terreno"] == 3704.8
    assert dato["area_construccion"] == 43465.1
    assert dato["direccion"] == "AK 30 25 90"
    assert dato["barrio"] == "FLORIDA"
    assert dato["vigencia"] == "2026"
    assert len(dato["usos"]) == 2
    assert dato["usos"][0]["codigo"] == "015"
    assert dato["usos"][0]["area_uso"] == 40453.8
    assert dato["usos"][1]["codigo"] == "096"
    assert dato["usos"][1]["area_uso"] == 3011.3


async def test_environment_context_con_obras_en_buffer_500():
    """environment_context: obras publicas en radio 500 m (Ampliacion de Estaciones: Calle 146)."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    entorno = reporte["environment_context"]
    assert entorno["estado"] == "disponible"
    obras = entorno["dato"]["obras"]
    assert len(obras) == 1
    assert obras[0]["nombre"] == "Ampliación de Estaciones: Calle 146"


async def test_administrative_context_con_upl24_chapinero_y_clasificacion():
    """administrative_context: UPL24 Chapinero, localidad derivada y clasificacion urbano."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    administrativo = reporte["administrative_context"]
    assert administrativo["upl"]["codigo"] == "UPL24"
    assert administrativo["upl"]["nombre"] == "Chapinero"
    assert administrativo["localidad"]["nombre"] == "Chapinero"
    assert administrativo["clasificacion_suelo"] == "urbano"
    assert set(administrativo["source_trace"]) == CAMPOS_TRAZA


async def test_normative_evidence_tiene_shape_del_contrato():
    """normative_evidence es uno de los 10 bloques con shape (items, consulta, consulta_automatica, sin_resultados, causa, source_trace)."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    evidencia = reporte["normative_evidence"]
    assert set(evidencia) == {
        "items", "consulta", "consulta_automatica", "sin_resultados", "causa", "source_trace",
    }
    assert isinstance(evidencia["items"], list)
    assert evidencia["items"], "con respuesta_normativa_ok debe haber 1 item"
    # SC-004: el articulo se serializa como str (el provider F2 lo emite int) y la cita es literal.
    item = evidencia["items"][0]
    assert item["articulo"] == "361"
    assert isinstance(item["articulo"], str)
    assert item["texto_cita"], "texto_cita no puede estar vacio (cita literal verificable)"
    assert isinstance(evidencia["consulta"], str) and evidencia["consulta"]
    assert isinstance(evidencia["consulta_automatica"], bool)
    assert isinstance(evidencia["sin_resultados"], bool)
    assert evidencia["causa"] in {"CORPUS_NO_INGESTADO", "OLLAMA_NO_DISPONIBLE", "SIN_RESULTADOS", None}
    assert set(evidencia["source_trace"]) == CAMPOS_TRAZA


async def test_feasibility_score_shape_y_rango():
    """feasibility_score: score entero 0-100, confidence canonico y reasons no vacias (FR-006)."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score = reporte["feasibility_score"]
    assert isinstance(score["score"], int)
    assert 0 <= score["score"] <= 100
    assert score["confidence"] in {"high", "medium", "low"}
    assert isinstance(score["reasons"], list) and score["reasons"]
    assert isinstance(score["rules_applied"], list)


async def test_lote_sin_chip_por_coordenadas_devuelve_chip_null_y_warning():
    """Lote resuelto por coordenadas (capa 38 sin CHIP) -> chip null + warning LOTE_SIN_CHIP."""
    arcgis_sin_chip = provider_arcgis_f3(
        lotes=[feature_lote(codigo_catastral="006101016001", manzana="006101016", chip=None)]
    )
    servidor = server_lotes_f3(
        arcgis=arcgis_sin_chip,
        normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()),
    )
    try:
        reporte = await servidor.get_feasibility_report(coordenadas={"lat": 4.6035, "lon": -74.083})
    finally:
        await servidor.aclose()

    assert reporte["lot_identity"]["chip"] is None
    codigos_warning = {w["codigo"] for w in reporte["warnings"]}
    assert "LOTE_SIN_CHIP" in codigos_warning
    # El resto de bloques se resuelven igual (US1 escenario 2)
    assert set(reporte) == BLOQUES_RAIZ


async def test_lote_sin_upl_devuelve_upl_null_clasificacion_null_y_warning():
    """Capa UPL sin dato -> upl null, clasificacion_suelo null + warning UPL_NO_ENCONTRADA (FR-003)."""
    servidor = server_lotes_f3(
        upl=provider_upl_estandar(upl_features=[]),
        normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    administrativo = reporte["administrative_context"]
    assert administrativo["upl"] is None
    assert administrativo["localidad"] is None
    assert administrativo["clasificacion_suelo"] is None
    codigos_warning = {w["codigo"] for w in reporte["warnings"]}
    assert "UPL_NO_ENCONTRADA" in codigos_warning
    # No es un error fatal: el reporte se entrega completo (FR-003/FR-009)
    assert set(reporte) == BLOQUES_RAIZ


async def test_reserva_vial_vacia_genera_warning_bloque_sin_dato():
    """Capa reserva vial sin features -> planning_constraints no_encontrado + BLOQUE_SIN_DATO (FR-011)."""
    arcgis_sin_reserva = provider_arcgis_f3(reserva=[])
    servidor = server_lotes_f3(
        arcgis=arcgis_sin_reserva,
        normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    planificacion = reporte["planning_constraints"]
    assert planificacion["estado"] == "no_encontrado"
    assert planificacion["dato"] is None
    codigos_warning = {w["codigo"] for w in reporte["warnings"]}
    assert "BLOQUE_SIN_DATO" in codigos_warning
    # El resto del reporte se entrega completo (FR-009/FR-011)
    assert reporte["lot_identity"]["chip"] == CHIP_VALIDO
    assert 0 <= reporte["feasibility_score"]["score"] <= 100
    assert set(reporte) == BLOQUES_RAIZ


async def test_predio_vacio_genera_warning_bloque_sin_dato():
    """Capa Predio sin filas -> economic_context no_encontrado + BLOQUE_SIN_DATO (FR-005/FR-011)."""
    arcgis_sin_predio = provider_arcgis_f3(predio=PAYLOAD_PREDIO_VACIO)
    servidor = server_lotes_f3(
        arcgis=arcgis_sin_predio,
        normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    economico = reporte["economic_context"]
    assert economico["estado"] == "no_encontrado"
    assert economico["dato"] is None
    codigos_warning = {w["codigo"] for w in reporte["warnings"]}
    assert "BLOQUE_SIN_DATO" in codigos_warning
    assert reporte["lot_identity"]["chip"] == CHIP_VALIDO
    assert 0 <= reporte["feasibility_score"]["score"] <= 100
    assert set(reporte) == BLOQUES_RAIZ


async def test_upl_sin_localidad_derivable_genera_warning_localidad_no_derivada():
    """UPL con NOMBRE fuera del mapeo estatico -> localidad null + LOCALIDAD_NO_DERIVADA (contrato:342)."""
    servidor = server_lotes_f3(
        upl=provider_upl_estandar(
            upl_features=[feature_upl(nombre="UPL DESCONOCIDA", codigo="UPL99", vocacion="Urbano")]
        ),
        normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    administrativo = reporte["administrative_context"]
    assert administrativo["upl"] is not None
    assert administrativo["upl"]["codigo"] == "UPL99"
    assert administrativo["localidad"] is None
    # La clasificacion de suelo se deriva de la vocacion, no de la localidad (research D2).
    assert administrativo["clasificacion_suelo"] == "urbano"
    codigos_warning = {w["codigo"] for w in reporte["warnings"]}
    assert "LOCALIDAD_NO_DERIVADA" in codigos_warning
    assert "UPL_NO_ENCONTRADA" not in codigos_warning
    assert set(reporte) == BLOQUES_RAIZ


async def test_score_es_determinista_en_dos_invocaciones():
    """SC-003: dos llamadas con los mismos datos -> score/confidence/reasons identicos."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        reporte_1 = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
        reporte_2 = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score_1 = reporte_1["feasibility_score"]
    score_2 = reporte_2["feasibility_score"]
    assert score_1["score"] == score_2["score"]
    assert score_1["confidence"] == score_2["confidence"]
    assert score_1["reasons"] == score_2["reasons"]
    assert score_1["rules_applied"] == score_2["rules_applied"]


async def test_reasons_e_interpretations_no_citan_reglas_urbanisticas_inventadas():
    """FR-014: el score y las interpretations hablan solo de datos reales, sin reglas ausentes."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    textos = list(reporte["feasibility_score"]["reasons"])
    for nombre in BLOQUES_CON_ESTADO:
        textos.append(reporte[nombre]["interpretation"])

    for texto in textos:
        for termino in TERMINOS_NORMATIVOS_INVENTADOS:
            assert termino not in texto.lower(), f"'{termino}' aparece en: {texto}"
