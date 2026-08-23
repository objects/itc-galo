"""Contract tests F8 — Bloque urbanistic_parameters (T024-T028, US1-US3, FR-001-FR-022).

Valida la estructura del bloque, degradación independiente (SDP falla →
estado="no_encontrado"; SDP sin features → BLOQUE_SIN_DATO; RAG caído →
BLOQUE_DEGRADADO con tratamiento conservado), la precedencia de la capa 14
del SINUPOT sobre el parsing RAG (FR-006/FR-021) y las 3 reglas de scoring
del bloque (SC-003, determinista).

Los tests usan httpx.MockTransport sobre SDPProvider y NormativaProviderStub.
Ninguna prueba hace llamadas de red reales.

Nota sobre la fuente de datos: el bloque urbanistic_parameters combina:
1. SDP/SINUPOT (capa 2) → tratamiento urbanístico (consulta espacial)
2. RAG normativo → parámetros numéricos (COS, CUS, altura, retiros,
   estacionamientos) extraídos por regex del texto del LLM (FR-014)
3. SDP/SINUPOT (capa 14) → edificabilidad oficial con precedencia sobre el
   parsing RAG (FR-006/FR-021)
"""

from __future__ import annotations

import httpx

from app.errores import CorpusNoIngestadoError
from app.main import _parsear_parametros_rag
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


def feature_edificabilidad(
    cos: float | None = 0.70,
    cus: float | None = 2.10,
    altura: float | None = None,
) -> dict:
    """Feature de la capa 14 (edificabilidad) con campos COS/CUS/ALTURA."""
    propiedades: dict = {"COS": cos, "CUS": cus}
    if altura is not None:
        propiedades["ALTURA"] = altura
    return {"type": "Feature", "properties": propiedades, "geometry": None}


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
    edificabilidad: list[dict] | None = None,
    status_edificabilidad: int = 200,
) -> SDPProvider:
    """Provider SDP con respuestas simuladas de las capas 2 y 14 del SINUPOT.

    Por defecto: tratamiento "Residencial" en capa 2 y capa 14 sin features
    (la edificabilidad oficial es complementaria, FR-006/FR-021).
    `status_edificabilidad` permite simular fallo 5xx de la capa 14.
    """
    trat = tratamiento if tratamiento is not None else [feature_tratamiento()]
    edif = edificabilidad if edificabilidad is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/MapServer/2/query" in url:
            return httpx.Response(200, json=geojson(trat))
        if "/MapServer/14/query" in url:
            return httpx.Response(status_edificabilidad, json=geojson(edif))
        return httpx.Response(404, json={"error": f"sin respuesta simulada para {url}"})

    return SDPProvider(transport=httpx.MockTransport(handler))


def provider_sdp_sin_features() -> SDPProvider:
    """Provider SDP que retorna features vacíos en capa 2 (SDP responde sin dato)."""
    return provider_sdp_estandar(tratamiento=[])


def provider_sdp_5xx() -> SDPProvider:
    """Provider SDP cuya capa 2 responde 500 (fallo de infraestructura, FR-009)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "fallo simulado del SINUPOT"})

    return SDPProvider(transport=httpx.MockTransport(handler))


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
        sdp=provider_sdp_estandar(),
    )
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
        sdp=provider_sdp_estandar(),
    )
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
        sdp=provider_sdp_estandar(),
    )
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
    """Bloque tiene source_trace con trazabilidad del SINUPOT (FR-010)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(),
    )
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
    """SDP responde sin features → no_encontrado + warning BLOQUE_SIN_DATO (contrato:62-67, FR-016)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_sin_features(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    bloque = reporte["urbanistic_parameters"]
    assert bloque["estado"] == "no_encontrado"
    assert bloque["dato"] is None
    warnings_bloque = [
        w for w in reporte["warnings"]
        if "urbanistic_parameters" in w.get("mensaje", "")
    ]
    assert len(warnings_bloque) == 1
    # Codigo exacto: "SDP responde pero sin features" es BLOQUE_SIN_DATO,
    # NO BLOQUE_DEGRADADO (hallazgo M1 del code review)
    assert warnings_bloque[0]["codigo"] == "BLOQUE_SIN_DATO"


async def test_degradacion_sdp_5xx():
    """SDP con 5xx → no_encontrado + warning BLOQUE_DEGRADADO, sin abortar el informe (FR-008/FR-009)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_5xx(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    bloque = reporte["urbanistic_parameters"]
    assert bloque["estado"] == "no_encontrado"
    assert bloque["dato"] is None
    warnings_bloque = [
        w for w in reporte["warnings"]
        if "urbanistic_parameters" in w.get("mensaje", "")
    ]
    assert len(warnings_bloque) == 1
    assert warnings_bloque[0]["codigo"] == "BLOQUE_DEGRADADO"
    # La causa 5xx queda registrada en el mensaje del warning (FR-009 enmendada)
    assert "SINUPOT/SDP" in warnings_bloque[0]["mensaje"]


async def test_degradacion_rag_no_disponible_emite_warning():
    """RAG caído (CorpusNoIngestadoError) → warning BLOQUE_DEGRADADO + tratamiento conservado (FR-008/FR-016).

    Hallazgo M2 del code review: el fallo del RAG NUNCA se silencia; los
    campos numéricos quedan en None pero el bloque mantiene el tratamiento.
    """
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(error=CorpusNoIngestadoError()),
        sdp=provider_sdp_estandar(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    bloque = reporte["urbanistic_parameters"]
    assert bloque["estado"] == "disponible"
    assert bloque["dato"]["tratamiento"]["denominacion"] == "Residencial"
    warnings_rag = [
        w for w in reporte["warnings"]
        if "RAG normativo" in w.get("mensaje", "")
    ]
    assert len(warnings_rag) == 1
    assert warnings_rag[0]["codigo"] == "BLOQUE_DEGRADADO"


# --- Tests T025b: Capa 14 SINUPOT — edificabilidad oficial (FR-006/FR-021) ---

async def test_capa14_tiene_precedencia_sobre_rag():
    """Capa 14 con valores oficiales → precedencia sobre el parsing RAG (FR-021)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(
            edificabilidad=[feature_edificabilidad(cos=0.80, cus=2.50)]
        ),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    edif = reporte["urbanistic_parameters"]["dato"]["edificabilidad"]
    # Valores oficiales de la capa 14, no los del RAG (0.60 / 1.80)
    assert edif["cos"] == 0.80
    assert edif["cus"] == 2.50


async def test_capa14_parcial_se_complementa_con_rag():
    """Capa 14 sin altura → la altura se complementa desde el texto RAG (FR-021)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(
            edificabilidad=[feature_edificabilidad(cos=0.80, cus=None)]
        ),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    edif = reporte["urbanistic_parameters"]["dato"]["edificabilidad"]
    assert edif["cos"] == 0.80  # oficial capa 14
    assert edif["cus"] == 1.80  # complementado desde el RAG
    assert edif["altura_maxima_m"] == 18.0  # complementado desde el RAG


async def test_capa14_falla_sin_tumbar_el_bloque():
    """Capa 14 con 5xx → warning propio y el bloque sigue disponible con datos del RAG."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(status_edificabilidad=500),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    bloque = reporte["urbanistic_parameters"]
    assert bloque["estado"] == "disponible"
    edif = bloque["dato"]["edificabilidad"]
    assert edif["cos"] == 0.60  # del RAG
    warnings_capa14 = [
        w for w in reporte["warnings"]
        if "layer 14" in w.get("mensaje", "")
    ]
    assert len(warnings_capa14) == 1
    assert warnings_capa14[0]["codigo"] == "BLOQUE_DEGRADADO"


async def test_degradacion_sdp_no_rompe_reporte():
    """SDP falla → los demás bloques del reporte se construyen normalmente."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_sin_features(),
    )
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
    """RAG sin COS/CUS/altura en respuesta → tratamiento OK, edificabilidad None (hallazgo M6)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_sin_parametros()),
        sdp=provider_sdp_estandar(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    bloque = reporte["urbanistic_parameters"]
    assert bloque["estado"] == "disponible"
    assert bloque["dato"]["tratamiento"]["denominacion"] == "Residencial"
    # Sin ningún valor real (capa 14 ni RAG), el sub-modelo no se construye (M6):
    # exclude_none=True lo elimina de la serialización.
    assert "edificabilidad" not in bloque["dato"]


# --- Tests T027: Scoring - r_parametros_urbanisticos (+10) ---

async def test_scoring_parametros_urbanisticos_disponible():
    """Tratamiento + edificabilidad disponibles → +10 (r_parametros_urbanisticos)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(),
    )
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
        sdp=provider_sdp_sin_features(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score = reporte["feasibility_score"]
    assert "r_parametros_urbanisticos" not in score["rules_applied"]


async def test_scoring_parametros_urbanisticos_rag_sin_parametros():
    """RAG sin COS/CUS/altura y capa 14 vacía → edificabilidad None → la regla +10 NO se activa.

    Hallazgo M6 del code review: el bonus r_parametros_urbanisticos exige
    datos reales de edificabilidad; un lote con tratamiento y cero parámetros
    numéricos no recibe el +10.
    """
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_sin_parametros()),
        sdp=provider_sdp_estandar(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score = reporte["feasibility_score"]
    assert "r_parametros_urbanisticos" not in score["rules_applied"]


async def test_scoring_parametros_urbanisticos_con_capa14():
    """Capa 14 con valores oficiales (sin RAG numérico) → la regla +10 SÍ se activa."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_sin_parametros()),
        sdp=provider_sdp_estandar(
            edificabilidad=[feature_edificabilidad(cos=0.70, cus=2.10)]
        ),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score = reporte["feasibility_score"]
    assert "r_parametros_urbanisticos" in score["rules_applied"]


# --- Tests T027: Scoring - r_tratamiento_conservacion (-15) ---

async def test_scoring_tratamiento_conservacion():
    """Tratamiento Conservación → -15 (r_tratamiento_conservacion)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_conservacion()),
        sdp=provider_sdp_tratamiento_conservacion(),
    )
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
        sdp=provider_sdp_tratamiento_conservacion_mayusculas(),
    )
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
        sdp=provider_sdp_estandar(),
    )
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
        sdp=provider_sdp_estandar(),
    )
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
        sdp=provider_sdp_estandar(),
    )
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
        sdp=provider_sdp_estandar(),
    )
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
        sdp=provider_sdp_tratamiento_conservacion(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    score = reporte["feasibility_score"]
    assert "r_parametros_urbanisticos" in score["rules_applied"]
    assert "r_tratamiento_conservacion" in score["rules_applied"]


# --- Tests T024: Resumen por chip incluye urbanistic_parameters ---

async def test_resumen_por_chip_incluye_urbanistic_parameters():
    """get_lot_summary_by_chip incluye urbanistic_parameters (FR-020)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_parametros()),
        sdp=provider_sdp_estandar(),
    )
    try:
        resumen = await servidor.get_lot_summary_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "urbanistic_parameters" in resumen
    bloque = resumen["urbanistic_parameters"]
    assert bloque["estado"] == "disponible"
    assert bloque["dato"]["tratamiento"]["denominacion"] == "Residencial"


# --- Tests T027: Parsing regex directo de _parsear_parametros_rag ---

def test_parsear_parametros_rag_retiros_completos():
    """Respuesta RAG con retiros frontal/laterales/posterior → los 3 se extraen (FR-014).

    El texto replica el formato de una respuesta real del LLM: etiquetas
    "retiro frontal:", "retiros laterales:", "retiro posterior:" con valor
    y unidad "m" (contracts/urbanistic-parameters.md:Parsing regex).
    """
    texto = (
        "Según el Artículo 389 del Decreto 555/2021, para el tratamiento "
        "Residencial en la UPL UP-10 los parámetros son: COS: 0.60, "
        "CUS: 1.80, altura: 18.0 m. Los retiros exigidos son "
        "retiro frontal: 3.5 m, retiros laterales: 2.0 m y "
        "retiro posterior: 2.5 m. Se requieren 2 estacionamientos por unidad."
    )
    parametros = _parsear_parametros_rag(texto)

    assert parametros["frontal_m"] == 3.5
    assert parametros["laterales_m"] == 2.0
    assert parametros["posteriores_m"] == 2.5
    # Los demás campos también se extraen del mismo texto
    assert parametros["cos"] == 0.60
    assert parametros["cus"] == 1.80
    assert parametros["altura_maxima_m"] == 18.0
    assert parametros["estacionamientos_requeridos"] == 2


def test_parsear_parametros_rag_retiros_ausentes():
    """Respuesta RAG sin retiros → frontal/laterales/posteriores quedan None; el resto sí se extrae."""
    texto = (
        "Para el tratamiento Residencial: COS: 0.50, CUS: 1.20, altura: 12.0 m, "
        "4 estacionamientos requeridos por el Artículo 389."
    )
    parametros = _parsear_parametros_rag(texto)

    assert parametros["frontal_m"] is None
    assert parametros["laterales_m"] is None
    assert parametros["posteriores_m"] is None
    assert parametros["cos"] == 0.50
    assert parametros["cus"] == 1.20
    assert parametros["altura_maxima_m"] == 12.0
    assert parametros["estacionamientos_requeridos"] == 4


def test_parsear_parametros_rag_retiros_case_insensitive():
    """Etiquetas de retiros en mayúsculas → parsing case insensitive (re.IGNORECASE)."""
    texto = (
        "Retiro FRONTAL: 5.0 m, RETIROS LATERALES: 3.0 m, "
        "retiro POSTERIOR: 3.0 m según la norma."
    )
    parametros = _parsear_parametros_rag(texto)

    assert parametros["frontal_m"] == 5.0
    assert parametros["laterales_m"] == 3.0
    assert parametros["posteriores_m"] == 3.0


def test_parsear_parametros_rag_retiros_singular():
    """Etiquetas en singular ("retiro lateral", "retiro posterior") también se extraen (hallazgo m2).

    El regex acepta singular y plural para tolerar la formulación del LLM:
    el prompt pide retiros y la respuesta puede ecoar "retiro lateral" o
    "retiros laterales" indistintamente.
    """
    texto = (
        "COS: 0.60, CUS: 1.80, altura: 18.0 m. Retiro frontal: 3.0 m, "
        "retiro lateral: 2.0 m y retiro posterior: 2.0 m."
    )
    parametros = _parsear_parametros_rag(texto)

    assert parametros["frontal_m"] == 3.0
    assert parametros["laterales_m"] == 2.0
    assert parametros["posteriores_m"] == 2.0


# --- Tests m3: criterio de estacionamientos derivado del RAG (FR-015) ---

async def test_criterio_estacionamientos_derivado_del_rag():
    """criterio se deriva de la referencia normativa citada en el texto RAG (hallazgo m3).

    Nunca se hardcodea: la referencia debe existir en la respuesta real.
    """
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_rag_estacionamientos(num=4)),
        sdp=provider_sdp_estandar(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    estacionamientos = reporte["urbanistic_parameters"]["dato"]["estacionamientos"]
    assert estacionamientos["requeridos"] == 4
    assert estacionamientos["criterio"] == "Artículo 389 del Decreto 555/2021"


async def test_criterio_none_sin_referencia_normativa_en_rag():
    """RAG con estacionamientos pero sin referencia normativa citada → criterio None (FR-015)."""
    respuesta_sin_referencia = {
        "respuesta": (
            "Para el tratamiento Residencial se requieren 3 estacionamientos "
            "según la norma urbanística aplicable."
        ),
        "sin_resultados": False,
        "resultados": [],
        "trazabilidad": {
            "source_name": "Decreto 555 de 2021 (POT Bogotá)",
            "layer_id": "Decreto_555_2021",
            "service_url": "https://sisjur.bogotajuridica.gov.co/sisjur/normas/Norma1.jsp?i=119582",
            "data_vigencia": "2021-12-30",
            "query_timestamp": "2026-08-12T02:15:04Z",
        },
    }
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_sin_referencia),
        sdp=provider_sdp_estandar(),
    )
    try:
        reporte = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    estacionamientos = reporte["urbanistic_parameters"]["dato"]["estacionamientos"]
    assert estacionamientos["requeridos"] == 3
    # exclude_none=True elimina la clave cuando el criterio es None
    assert estacionamientos.get("criterio") is None
