"""Contract tests de confiabilidad: FR-009 real en bloques multifuente (M1)
y catastro del resumen sin silencios (M2).

Un 5xx de una capa de un bloque F6/F7 NUNCA se reporta como "no encontrado"
silencioso: el bloque se degrada con warning BLOQUE_DEGRADADO y la causa real
de la capa caida. Fallo total (todas las capas caidas, sin datos) -> bloque
no_encontrado + BLOQUE_DEGRADADO; fallo parcial (algunas capas ok) -> bloque
con los datos disponibles + BLOQUE_DEGRADADO parcial.
"""

from __future__ import annotations

import httpx

from app.providers.arcgis import ArcGISProvider
from tests.conftest import (
    CHIP_VALIDO,
    NormativaProviderStub,
    feature_lote,
    geojson,
    server_lotes_f3,
)


def feature_uso(usos="Comercio"):
    return {"type": "Feature", "properties": {"GRUPOUSOECON": usos}, "geometry": None}


def provider_arcgis_con_fallos(fallos_por_url: dict[str, int], extras: dict[str, list] | None = None):
    """Provider ArcGIS que sirve HTTP <status> en las URLs listadas.

    El resto de las capas responde 200 con features vacias, salvo `extras`
    (patron -> features) y las imprescindibles del flujo feliz (capa Lote 38,
    tematicas F1 y capa Predio pjson).
    """
    extras = extras or {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "Mapa_Referencia/Mapa_Referencia/MapServer/38/query" in url:
            return httpx.Response(
                200,
                json=geojson(
                    [feature_lote(codigo_catastral="006101016001", manzana="006101016")]
                ),
            )
        if "catastro/lote/MapServer/3/query" in url:
            return httpx.Response(200, json={"features": []})
        for patron, status in fallos_por_url.items():
            if patron in url:
                return httpx.Response(
                    status, json={"error": {"code": status, "message": "fallo simulado"}}
                )
        for patron, features in extras.items():
            if patron in url:
                return httpx.Response(200, json=geojson(features))
        return httpx.Response(200, json=geojson([]))

    return ArcGISProvider(transport=httpx.MockTransport(handler))


async def test_5xx_total_en_geotecnia_degrada_bloque_con_warning_y_causa():
    """Las 4 capas de gestionriesgos caidas -> bloque no_encontrado + BLOQUE_DEGRADADO
    con la causa real; JAMAS un "no encontrado" silencioso ni BLOQUE_SIN_DATO (M1)."""
    arcgis = provider_arcgis_con_fallos({"emergencias/gestionriesgos": 500})
    servidor = server_lotes_f3(arcgis=arcgis, normativa=NormativaProviderStub())
    try:
        respuesta = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    bloque = respuesta["geotechnical_risks"]
    assert bloque["estado"] == "no_encontrado"
    assert bloque["dato"] is None

    degradados = [w for w in respuesta["warnings"] if w["codigo"] == "BLOQUE_DEGRADADO"]
    assert any("geotechnical_risks" in w["mensaje"] for w in degradados)
    # La causa identifica a la fuente caida y el status HTTP
    assert any("Gestión de Riesgos" in w["mensaje"] and "500" in w["mensaje"] for w in degradados)
    # Nunca se maquilla como ausencia de dato
    sin_dato = [w for w in respuesta["warnings"] if w["codigo"] == "BLOQUE_SIN_DATO"]
    assert not any("geotechnical_risks" in w["mensaje"] for w in sin_dato)


async def test_5xx_parcial_en_socioeconomico_conserva_datos_y_advierte():
    """Estratificacion caida pero uso predominante ok -> bloque disponible con los
    datos de las capas vivas + BLOQUE_DEGRADADO parcial que nombra la capa caida."""
    arcgis = provider_arcgis_con_fallos(
        {"ordenamientoterritorial/estratificacion": 503},
        extras={"usopredominante": [feature_uso("Comercio")]},
    )
    servidor = server_lotes_f3(arcgis=arcgis, normativa=NormativaProviderStub())
    try:
        respuesta = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    bloque = respuesta["socioeconomic_context"]
    assert bloque["estado"] == "disponible"
    assert bloque["dato"] is not None
    assert bloque["dato"]["uso_predominante"] == "Comercio"

    degradados = [w for w in respuesta["warnings"] if w["codigo"] == "BLOQUE_DEGRADADO"]
    parciales = [w for w in degradados if "socioeconomic_context" in w["mensaje"]]
    assert len(parciales) == 1
    assert "parcialmente" in parciales[0]["mensaje"]
    assert "Estratificación" in parciales[0]["mensaje"]
    assert "503" in parciales[0]["mensaje"]


async def test_5xx_parcial_en_catastro_bloque_informe_degrada_parcialmente():
    """Manzana caida en catastro_data del informe -> bloque disponible con lo que
    respondio + warning parcial con la capa exacta (FR-009)."""
    arcgis = provider_arcgis_con_fallos({"catastro/manzana": 500})
    servidor = server_lotes_f3(arcgis=arcgis, normativa=NormativaProviderStub())
    try:
        respuesta = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    degradados = [w for w in respuesta["warnings"] if w["codigo"] == "BLOQUE_DEGRADADO"]
    assert any(
        "catastro_data" in w["mensaje"] and "Catastro — Manzana" in w["mensaje"]
        for w in degradados
    )


async def test_provider_catastro_reporta_fallos_por_capa_sin_tragar_excepciones():
    """El provider expone los fallos tipados por capa (FalloCapa) y sigue parseando
    las capas vivas: un 5xx nunca sale como 'sin features' (M1, nivel provider)."""
    arcgis = provider_arcgis_con_fallos({"catastro/manzana": 500})
    try:
        contexto, _traza, fallos = await arcgis.consultar_contexto_catastro(-74.083, 4.6035)
    finally:
        await arcgis.aclose()

    assert len(fallos) == 1
    assert fallos[0].source_name == "Catastro — Manzana"
    assert "500" in fallos[0].detalle
    # Las otras 4 capas no fallaron
    assert all(fallo.source_name != "Catastro — Construcción" for fallo in fallos)


async def test_resumen_catastro_5xx_emite_warning_y_no_traza_fabricada():
    """get_lot_summary_by_chip con todas las capas catastro caidas: estado
    no_encontrado + warning BLOQUE_DEGRADADO con la causa; sin except silencioso
    ni traza fabricada (M2)."""
    arcgis = provider_arcgis_con_fallos(
        {
            "catastro/construccion": 500,
            "catastro/manzana": 500,
            "catastro/densidadpredialmz": 500,
            "catastro/variacionareaconstruida": 500,
            "catastro/sectorcatastral": 500,
        }
    )
    servidor = server_lotes_f3(arcgis=arcgis, normativa=NormativaProviderStub())
    try:
        respuesta = await servidor.get_lot_summary_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    assert respuesta["catastro_data"]["estado"] == "no_encontrado"
    assert respuesta["catastro_data"]["dato"] is None
    degradados = [w for w in respuesta["warnings"] if w["codigo"] == "BLOQUE_DEGRADADO"]
    assert any("catastro_data" in w["mensaje"] for w in degradados)
    # La traza publicada es la de la fuente consultada (capa Construccion), con
    # su vigencia declarada, no una inventada ad hoc.
    assert (
        respuesta["catastro_data"]["source_trace"]["source_name"]
        == "Catastro — Construcción"
    )


async def test_resumen_sin_fallos_no_emite_warnings_de_degradacion():
    """Regresion: con todas las capas respondiendo (aunque sea sin datos), el
    resumen NO emite BLOQUE_DEGRADADO (la degradacion solo aplica a fallos)."""
    from tests.conftest import construir_servidor

    servidor = construir_servidor()
    try:
        respuesta = await servidor.get_lot_summary_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    degradados = [w for w in respuesta["warnings"] if w["codigo"] == "BLOQUE_DEGRADADO"]
    assert degradados == []
