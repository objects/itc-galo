"""Contract tests F8 — Bloque urbanistic_parameters (T024-T028, US1-US3, FR-001-FR-028).

Valida la estructura del bloque, degradación independiente (SDP falla →
estado="no_encontrado") y las 3 reglas de scoring del bloque (SC-003,
determinista).

Los tests usan httpx.MockTransport sobre SDPProvider y NormativaProviderStub.
Ninguna prueba hace llamadas de red reales.

Nota sobre la fuente de datos: el bloque urbanistic_parameters combina:
1. SDP/SINUPOT (capa 2) → tratamiento urbanístico (consulta espacial)
2. RAG normativo → parámetros numéricos (COS, CUS, altura, retiros,
   estacionamientos) extraídos por regex del texto del LLM (FR-014)
"""

from __future__ import annotations

import httpx

from app.errores import CorpusNoIngestadoError
from app.providers.sdp import SDPProvider
from tests.conftest import (
    CHIP_VALIDO,
    NormativaProviderStub,
    provider_arcgis_f3,
    provider_upl_estandar,
    respuesta_normativa_ok,
    server_lotes_f3,
)
from tests.contract._f3_shared import CAMPOS_TRAZA


# --- Helpers: payloads simulados del SINUPOT/SDP ---

SDP_URL_BASE = (
    "https://sinu.sdp.gov.co/serverp/rest/services/"
    "POT555/NORMA_URBAN%C3%8DSTICA_Y_OT/MapServer"
)


def feature_tratamiento(denominacion: str = "Residencial", codigo: str = "R3") -> dict:
    """Feature de la capa 2 (tratamiento) con campo DENOMINACION."""
    return {
        "type": "Feature",
        "properties": {
            "DENOMINACION": denominacion,
            "CODIGO": codigo,
        },
        "geometry": None,
    }


def geojson(features):
    return {"type": "FeatureCollection", "features": features}


# --- Respuesta RAG con parámetros numéricos del POT ---

def respuesta_rag_parametros(
    cos: float = 0.60,
    cus: float = 1.80,
    altura: float = 18.0,
    frontal: float = 3.0,
    laterales: float = 2.0,
    posterior: float = 2.0,
    estacionamientos: int = 2,
) -> dict:
    """Respuesta RAG con parámetros numéricos del POT (formato que _parsear_parametros_rag espera).

    Los valores se insertan en el texto de la respuesta con los patrones regex
    que el orquestador usa para extraer COS, CUS, altura, retiros y
    estacionamientos (contracts/urbanistic-parameters.md:Parsing regex).
    """
    texto = (
        f"Para el tratamiento Residencial, los parámetros del POT son: "
        f"COS: {cos}, CUS: {cus}, altura: {altura} m, "
        f"retiro frontal: {frontal} m, retiros laterales: {laterales} m, "
        f"retiro posterior: {posterior} m, {estacionamientos} estacionamientos "
        f"requeridos por el Artículo 389 del Decreto 555/2021."
    )
    return {
        "respuesta": texto,
        "sin_resultados": False,
        "resultados": [
            {
                "articulo": 389,
                "titulo": "Parámetros urbanísticos",
                "libro": "III",
                "parte": "urbano",
                "texto_cita": texto,
                "similitud": 0.75,
            }
        ],
        "trazabilidad": {
            "source_name": "Decreto 555 de 2021 (POT Bogotá)",
            "layer_id": "Decreto_555_2021",
            "service_url": "https://sisjur.bogotajuridica.gov.co/sisjur/normas/Norma1.jsp?i=119582",
            "data_vigencia": "2021-12-30",
            "query_timestamp": "2026-08-12T02:15:04Z",
        },
    }


def respuesta_rag_conservacion() -> dict:
    """Respuesta RAG para tratamiento Conservación (penalización -15)."""
    texto = (
        "Para el tratamiento Conservación, los parámetros del POT son: "
        "COS: 0.30, CUS: 0.90, altura: 9.0 m, "
        "retiro frontal: 5.0 m, retiros laterales: 3.0 m, "
        "retiro posterior: 3.0 m, 1 estacionamiento requerido."
    )
    return {
        "respuesta": texto,
        "sin_resultados": False,
        "resultados": [
            {
                "articulo": 389,
                "titulo": "Parámetros urbanísticos",
                "libro": "III",
                "parte": "urbano",
                "texto_cita": texto,
                "similitud": 0.70,
            }
        ],
        "trazabilidad": {
            "source_name": "Decreto 555 de 2021 (POT Bogotá)",
            "layer_id": "Decreto_555_2021",
            "service_url": "https://sisjur.bogotajuridica.gov.co/sisjur/normas/Norma1.jsp?i=119582",
            "data_vigencia": "2021-12-30",
            "query_timestamp": "2026-08-12T02:15:04Z",
        },
    }


def respuesta_rag_sin_parametros() -> dict:
    """Respuesta RAG sin parámetros numéricos extraíbles (solo tratamiento)."""
    return {
        "respuesta": "El tratamiento Residencial se aplica en zonas urbanas del POT.",
        "sin_resultados": False,
        "resultados": [
            {
                "articulo": 281,
                "titulo": "Usos del suelo",
                "libro": "III",
                "parte": "urbano",
                "texto_cita": "El tratamiento Residencial se aplica en zonas urbanas.",
                "similitud": 0.40,
            }
        ],
        "trazabilidad": {
            "source_name": "Decreto 555 de 2021 (POT Bogotá)",
            "layer_id": "Decreto_555_2021",
            "service_url": "https://sisjur.bogotajuridica.gov.co/sisjur/normas/Norma1.jsp?i=119582",
            "data_vigencia": "2021-12-30",
            "query_timestamp": "2026-08-12T02:15:04Z",
        },
    }


def respuesta_rag_estacionamientos(num: int = 5) -> dict:
    """Respuesta RAG con estacionamientos requeridos."""
    texto = (
        f"Para el tratamiento Residencial: COS 0.60, CUS 1.80, altura 18 m, "
        f"{num} estacionamientos requeridos por el Artículo 389 del Decreto 555/2021."
    )
    return {
        "respuesta": texto,
        "sin_resultados": False,
        "resultados": [
            {
                "articulo": 389,
                "titulo": "Estacionamientos",
                "libro": "III",
                "parte": "urbano",
                "texto_cita": texto,
                "similitud": 0.65,
            }
        ],
        "trazabilidad": {
            "source_name": "Decreto 555 de 2021 (POT Bogotá)",
            "layer_id": "Decreto_555_2021",
            "service_url": "https://sisjur.bogotajuridica.gov.co/sisjur/normas/Norma1.jsp?i=119582",
            "data_vigencia": "2021-12-30",
            "query_timestamp": "2026-08-12T02:15:04Z",
        },
    }


# --- Constructores de providers con mock ---

def provider_sdp_estandar(
    tratamiento: list[dict] | None = None,
) -> SDPProvider:
    """Provider SDP con respuesta simulada de tratamiento (capa 2).

    Por defecto: tratamiento "Residencial". La capa 14 (edificabilidad) del
    SDP NO se usa para el bloque; los parámetros numéricos vienen del RAG.
    """
    trat = tratamiento if tratamiento is not None else [feature_tratamiento()]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/MapServer/2/query" in url:
            return httpx.Response(200, json=geojson(trat))
        if "/MapServer/14/query" in url:
            return httpx.Response(200, json=geojson([]))
        return httpx.Response(404, json={"error": f"sin respuesta simulada para {url}"})

    return SDPProvider(transport=httpx.MockTransport(handler))


def provider_sdp_sin_features() -> SDPProvider:
    """Provider SDP que retorna features vacíos en capa 2 (degradación)."""
    return provider_sdp_estandar(tratamiento=[])


def provider_sdp_tratamiento_conservacion() -> SDPProvider:
    """Provider SDP con tratamiento 'Conservación' (penalización -15)."""
    return provider_sdp_estandar(
        tratamiento=[feature_tratamiento(denominacion="Conservación", codigo="C2")]
    )


def provider_sdp_tratamiento_conservacion_mayusculas() -> SDPProvider:
    """Provider SDP con tratamiento 'CONSERVACIÓN' (penalización -15, mayúsculas)."""
    return provider_sdp_estandar(
        tratamiento=[feature_tratamiento(denominacion="CONSERVACIÓN", codigo="C2")]
    )


# --- Tests T024: Estructura del bloque urbanistic_parameters ---

async def test_bloque_urbanistic_parameters_estructura():
    """Bloque tiene estado, dato, interpretation y source_trace (FR-001, FR-004/FR-005)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
    )
    servidor._sdp = provider_sdp_estandar()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    bloque = reporte["urbanistic_parameters"]
    assert set(bloque.keys()) == {"estado", "dato", "interpretation", "source_trace"}
    assert bloque["estado"] == "disponible"
    assert bloque["dato"] is not None


async def test_bloque_urbanistic_parameters_tratamiento():
    """Bloque contiene tratamiento con denominación (FR-002, FR-004)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
    )
    servidor._sdp = provider_sdp_estandar()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    dato = reporte["urbanistic_parameters"]["dato"]
    assert dato["tratamiento"]["denominacion"] == "Residencial"
    assert dato["tratamiento"]["codigo_capa"] == "R3"


async def test_bloque_urbanistic_parameters_edificabilidad():
    """Bloque contiene edificabilidad con COS/CUS/altura extraídos del RAG (FR-006, FR-021)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
    )
    servidor._sdp = provider_sdp_estandar()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    dato = reporte["urbanistic_parameters"]["dato"]
    edif = dato["edificabilidad"]
    assert edif["cos"] == 0.60
    assert edif["cus"] == 1.80
    assert edif["altura_maxima_m"] == 18.0


async def test_bloque_urbanistic_parameters_source_trace():
    """Bloque tiene source_trace con trazabilidad del SINUPOT (FR-011)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
    )
    servidor._sdp = provider_sdp_estandar()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    trace = reporte["urbanistic_parameters"]["source_trace"]
    assert trace["source_name"] == "SINUPOT — Norma Urbanística y OT"
    assert trace["layer_id"] == "2"
    assert trace["service_url"] == SDP_URL_BASE
    assert "data_vigencia" in trace


# --- Tests T025: Degradación independiente del bloque ---

async def test_degradacion_sdp_sin_features():
    """SDP sin features → bloque estado='no_encontrado' + warning, sin abortar el reporte."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
    )
    servidor._sdp = provider_sdp_sin_features()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    bloque = reporte["urbanistic_parameters"]
    assert bloque["estado"] == "no_encontrado"
    assert bloque["dato"] is None
    assert len(reporte["warnings"]) > 0
    assert any(
        "urbanistic_parameters" in w.get("mensaje", "")
        for w in reporte["warnings"]
    )


async def test_degradacion_sdp_no_rompe_reporte():
    """SDP falla → los demás bloques del reporte se construyen normalmente."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
    )
    servidor._sdp = provider_sdp_sin_features()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert reporte["lot_identity"]["chip"] == CHIP_VALIDO
    assert reporte["market_context"]["estado"] == "disponible"
    assert reporte["economic_context"]["estado"] == "disponible"
    assert "feasibility_score" in reporte


# --- Tests T026: Degradación con RAG sin parámetros numéricos ---

async def test_degradacion_rag_sin_parametros():
    """RAG sin COS/CUS/altura en respuesta → tratamiento OK, campos numéricos None."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_sin_parametros()),
    )
    servidor._sdp = provider_sdp_estandar()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    bloque = reporte["urbanistic_parameters"]
    assert bloque["estado"] == "disponible"
    assert bloque["dato"]["tratamiento"]["denominacion"] == "Residencial"
    # Cuando todos los campos son None, exclude_none=True serializa como {}
    edif = bloque["dato"]["edificabilidad"]
    assert edif.get("cos") is None
    assert edif.get("cus") is None
    assert edif.get("altura_maxima_m") is None


# --- Tests T027: Scoring - r_parametros_urbanisticos (+10) ---

async def test_scoring_parametros_urbanisticos_disponible():
    """Tratamiento + edificabilidad disponibles → +10 (r_parametros_urbanisticos)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
    )
    servidor._sdp = provider_sdp_estandar()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score = reporte["feasibility_score"]
    assert "r_parametros_urbanisticos" in score["rules_applied"]
    assert any("Parámetros urbanísticos disponibles" in r for r in score["reasons"])


async def test_scoring_parametros_urbanisticos_no_disponible():
    """SDP falla → r_parametros_urbanisticos NO está en rules_applied."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
    )
    servidor._sdp = provider_sdp_sin_features()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score = reporte["feasibility_score"]
    assert "r_parametros_urbanisticos" not in score["rules_applied"]


async def test_scoring_parametros_urbanisticos_rag_sin_parametros():
    """RAG sin COS/CUS/altura → edificabilidad modelo vacío (no None) → regla SÍ se activa.

    El orquestador siempre crea ParametrosEdificabilidad cuando el treatment
    SDP tiene éxito; cuando el RAG no extrae valores, los campos son None pero
    el objeto existe. La regla r_parametros_urbanisticos verifica que
    edificabilidad no es None (el objeto existe), no que tenga valores.
    """
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_sin_parametros()),
    )
    servidor._sdp = provider_sdp_estandar()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score = reporte["feasibility_score"]
    # La regla SÍ se activa porque edificabilidad es un objeto (no None)
    assert "r_parametros_urbanisticos" in score["rules_applied"]


# --- Tests T027: Scoring - r_tratamiento_conservacion (-15) ---

async def test_scoring_tratamiento_conservacion():
    """Tratamiento Conservación → -15 (r_tratamiento_conservacion)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_conservacion()),
    )
    servidor._sdp = provider_sdp_tratamiento_conservacion()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score = reporte["feasibility_score"]
    assert "r_tratamiento_conservacion" in score["rules_applied"]
    assert any("Tratamiento de conservación" in r for r in score["reasons"])


async def test_scoring_tratamiento_conservacion_mayusculas():
    """Tratamiento CONSERVACIÓN (mayúsculas) → -15 (case insensitive)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_conservacion()),
    )
    servidor._sdp = provider_sdp_tratamiento_conservacion_mayusculas()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score = reporte["feasibility_score"]
    assert "r_tratamiento_conservacion" in score["rules_applied"]


async def test_scoring_no_conservacion_no_penaliza():
    """Tratamiento Residencial → sin penalización de conservación."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
    )
    servidor._sdp = provider_sdp_estandar()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score = reporte["feasibility_score"]
    assert "r_tratamiento_conservacion" not in score["rules_applied"]


# --- Tests T028: Scoring - r_estacionamientos_calculados (+5) ---

async def test_scoring_estacionamientos_requeridos():
    """Estacionamientos requeridos > 0 → +5 (r_estacionamientos_calculados)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_estacionamientos(num=5)),
    )
    servidor._sdp = provider_sdp_estandar()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score = reporte["feasibility_score"]
    assert "r_estacionamientos_calculados" in score["rules_applied"]
    assert any("Estacionamientos requeridos calculados" in r for r in score["reasons"])


async def test_scoring_estacionamientos_cero():
    """Estacionamientos = 0 → r_estacionamientos_calculados NO se activa."""
    # respuesta_rag_parametros tiene 2 estacionamientos; usar respuesta sin estacionamientos
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_sin_parametros()),
    )
    servidor._sdp = provider_sdp_estandar()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score = reporte["feasibility_score"]
    assert "r_estacionamientos_calculados" not in score["rules_applied"]


# --- Tests T029: Determinismo del score (SC-003) ---

async def test_score_determinismo():
    """Misma entrada → mismo score/confidence/reasons (SC-003)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
    )
    servidor._sdp = provider_sdp_estandar()
    try:
        reporte1 = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
        reporte2 = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score1 = reporte1["feasibility_score"]
    score2 = reporte2["feasibility_score"]
    assert score1["score"] == score2["score"]
    assert score1["confidence"] == score2["confidence"]
    assert score1["reasons"] == score2["reasons"]
    assert score1["rules_applied"] == score2["rules_applied"]


# --- Tests T027: Scoring combinado (conservación + parámetros) ---

async def test_scoring_conservacion_con_parametros():
    """Tratamiento Conservación + edificabilidad → +10 -15 = -5 neto."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_conservacion()),
    )
    servidor._sdp = provider_sdp_tratamiento_conservacion()
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score = reporte["feasibility_score"]
    assert "r_parametros_urbanisticos" in score["rules_applied"]
    assert "r_tratamiento_conservacion" in score["rules_applied"]


# --- Tests T024: Resumen por chip incluye urbanistic_parameters ---

async def test_resumen_por_chip_incluye_urbanistic_parameters():
    """get_lot_summary_by_chip incluye urbanistic_parameters (FR-011, F5)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
    )
    servidor._sdp = provider_sdp_estandar()
    try:
        resumen = await servidor.get_lot_summary_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "urbanistic_parameters" in resumen
    bloque = resumen["urbanistic_parameters"]
    assert bloque["estado"] == "disponible"
    assert bloque["dato"]["tratamiento"]["denominacion"] == "Residencial"
