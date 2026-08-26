"""Contract tests de la Fase 3: public_space_context, road_network_context y
nearby_facilities, mas llm_ready_summary.

Patron de test_confiabilidad_f6_f7.py: provider ArcGIS con fallos tipados por
URL. Cada bloque nuevo degrada independientemente (FR-012): un 5xx de capa es
BLOQUE_DEGRADADO con la causa real (FR-009), nunca "no encontrado" silencioso;
sin features y sin fallo es no_encontrado + BLOQUE_SIN_DATO.
"""

from __future__ import annotations

import httpx
import pytest

from app.providers.arcgis import ArcGISProvider
from tests.conftest import (
    CHIP_VALIDO,
    NormativaProviderStub,
    feature_lote,
    geojson,
    server_lotes_f3,
)

CENTROIDE_LNG = -74.083
CENTROIDE_LAT = 4.6035


def feature_espacio_publico(ept=28.4, upl="UPL23", nombre="Centro Histórico"):
    return {
        "type": "Feature",
        "properties": {"CODIGO_UPL": upl, "NOMBRE": nombre, "EPT": ept, "VOCACION": 1},
        "geometry": None,
    }


def feature_via(tipo="AC", nombre="AVENIDA EL DORADO", carriles=3, velocidad="60"):
    return {
        "type": "Feature",
        "properties": {
            "MVITIPO": tipo,
            "MVINOMBRE": nombre,
            "MVINUMC": carriles,
            "MVIVELREG": velocidad,
        },
        "geometry": None,
    }


def feature_equipamiento(nombre, tipo_geom="Point", coords=None, direccion="KR 8 7 21"):
    geometria = None
    if tipo_geom == "Point":
        geometria = {"type": "Point", "coordinates": coords or [-74.0817, 4.6117]}
    return {
        "type": "Feature",
        "properties": {"NOMBRE": nombre, "DIRECCION": direccion},
        "geometry": geometria,
    }


def provider_arcgis_fase3(fallos_por_url=None, extras=None):
    """Provider ArcGIS que sirve HTTP <status> en las URLs listadas.

    El resto responde 200 con features vacias, salvo `extras` (patron ->
    features) y las imprescindibles del flujo feliz (capa Lote 38, tematicas
    F1 y capa Predio pjson).
    """
    fallos_por_url = fallos_por_url or {}
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


async def reporte_de(arcgis):
    servidor = server_lotes_f3(arcgis=arcgis, normativa=NormativaProviderStub())
    try:
        return await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()


# --- Shape del flujo feliz ---


async def test_bloques_fase3_disponibles_con_datos_reales():
    """Con features en las capas nuevas, los 3 bloques quedan disponibles con su dato."""
    extras = {
        "indicadorespaciopublico": [feature_espacio_publico(ept=28.4)],
        "Mapa_Referencia/Mapa_Referencia/MapServer/13/query": [
            feature_via(tipo="AC", nombre="AVENIDA EL DORADO")
        ],
        "serviciosips": [
            feature_equipamiento("IPS CENTRO", coords=[-74.0825, 4.604])
        ],
        "infraestructuraeducativa": [
            feature_equipamiento("COLEGIO SAN CARLOS", coords=[-74.0835, 4.6038])
        ],
        "equipamientocultural": [
            feature_equipamiento("MUSEO DE ARTE", coords=[-74.084, 4.6045])
        ],
    }
    reporte = await reporte_de(provider_arcgis_fase3(extras=extras))

    assert "error" not in reporte

    espacio = reporte["public_space_context"]
    assert espacio["estado"] == "disponible"
    assert espacio["dato"]["codigo_upl"] == "UPL23"
    assert espacio["dato"]["nombre_upl"] == "Centro Histórico"
    assert espacio["dato"]["ep_total_m2_hab"] == pytest.approx(28.4)
    # Monofuente: sin source_traces
    assert set(espacio) == {"estado", "dato", "interpretation", "source_trace"}

    vial = reporte["road_network_context"]
    assert vial["estado"] == "disponible"
    assert vial["dato"]["jerarquia_maxima"] == "alta"
    assert vial["dato"]["vias_frente"][0]["tipo_via"] == "AC"
    assert vial["dato"]["vias_frente"][0]["nombre_via"] == "AVENIDA EL DORADO"
    assert vial["dato"]["vias_frente"][0]["carriles"] == 3
    assert set(vial) == {"estado", "dato", "interpretation", "source_trace"}

    facilidades = reporte["nearby_facilities"]
    assert facilidades["estado"] == "disponible"
    assert facilidades["dato"]["total_salud"] == 1
    assert facilidades["dato"]["total_educacion"] == 1
    assert facilidades["dato"]["total_cultura"] == 1
    tipos = {eq["tipo"] for eq in facilidades["dato"]["equipamientos"]}
    assert tipos == {"salud", "educacion", "cultura"}
    cercano = facilidades["dato"]["mas_cercano"]
    assert cercano is not None and cercano["distancia_m"] is not None
    assert cercano["distancia_m"] < 500  # haversine sobre puntos vecinos
    # Multifuente: publica source_traces por sub-fuente exitosa
    assert set(facilidades) == {"estado", "dato", "interpretation", "source_trace", "source_traces"}
    assert len(facilidades["source_traces"]) == 5


async def test_bloques_fase3_sin_features_son_no_encontrado_con_warning():
    """Sin features ni fallos -> no_encontrado + BLOQUE_SIN_DATO (nunca ceros, FR-007)."""
    reporte = await reporte_de(provider_arcgis_fase3())

    assert "error" not in reporte
    for nombre in ("public_space_context", "road_network_context", "nearby_facilities"):
        bloque = reporte[nombre]
        assert bloque["estado"] == "no_encontrado", nombre
        assert bloque["dato"] is None, nombre
    sin_dato = [w for w in reporte["warnings"] if w["codigo"] == "BLOQUE_SIN_DATO"]
    for nombre in ("public_space_context", "road_network_context", "nearby_facilities"):
        assert any(nombre in w["mensaje"] for w in sin_dato), nombre


# --- Degradacion independiente (FR-009/FR-012) ---


async def test_5xx_total_en_espacio_publico_degrada_bloque_con_causa():
    """Capa de espacio publico caida -> no_encontrado + BLOQUE_DEGRADADO con la causa."""
    arcgis = provider_arcgis_fase3({"espaciopublico/indicadorespaciopublico": 500})
    reporte = await reporte_de(arcgis)

    assert "error" not in reporte
    bloque = reporte["public_space_context"]
    assert bloque["estado"] == "no_encontrado"
    assert bloque["dato"] is None
    degradados = [w for w in reporte["warnings"] if w["codigo"] == "BLOQUE_DEGRADADO"]
    assert any(
        "public_space_context" in w["mensaje"] and "Indicadores de Espacio Público" in w["mensaje"]
        for w in degradados
    )
    sin_dato = [w for w in reporte["warnings"] if w["codigo"] == "BLOQUE_SIN_DATO"]
    assert not any("public_space_context" in w["mensaje"] for w in sin_dato)


async def test_5xx_parcial_en_facilidades_conserva_datos_y_advierte():
    """IPS caida pero colegios ok -> nearby_facilities disponible + BLOQUE_DEGRADADO parcial."""
    extras = {
        "infraestructuraeducativa": [
            feature_equipamiento("COLEGIO SAN CARLOS", coords=[-74.0835, 4.6038])
        ],
    }
    arcgis = provider_arcgis_fase3({"salud/serviciosips": 503}, extras=extras)
    reporte = await reporte_de(arcgis)

    assert "error" not in reporte
    bloque = reporte["nearby_facilities"]
    assert bloque["estado"] == "disponible"
    assert bloque["dato"]["total_educacion"] == 1
    # La capa caida no aporta total; al ser None se excluye de la serializacion
    assert "total_salud" not in bloque["dato"]
    degradados = [w for w in reporte["warnings"] if w["codigo"] == "BLOQUE_DEGRADADO"]
    parciales = [w for w in degradados if "nearby_facilities" in w["mensaje"]]
    assert len(parciales) == 1
    assert "parcialmente" in parciales[0]["mensaje"]
    assert "IPS" in parciales[0]["mensaje"]
    assert "503" in parciales[0]["mensaje"]


# --- Scoring (reglas Fase 3) ---


async def test_scoring_reglas_fase3_se_activan_con_datos():
    """EPT >= 15 m²/hab + avenida en frente + salud/educacion cercana -> 3 reglas +15."""
    extras = {
        "indicadorespaciopublico": [feature_espacio_publico(ept=28.4)],
        "Mapa_Referencia/Mapa_Referencia/MapServer/13/query": [feature_via(tipo="AC")],
        "serviciosips": [feature_equipamiento("IPS CENTRO")],
        "infraestructuraeducativa": [feature_equipamiento("COLEGIO SAN CARLOS")],
    }
    reporte = await reporte_de(provider_arcgis_fase3(extras=extras))

    score = reporte["feasibility_score"]
    for regla in (
        "r_espacio_publico_suficiente",
        "r_frente_vial_avenida",
        "r_equipamientos_cercanos",
    ):
        assert regla in score["rules_applied"], regla
    razones = "\n".join(score["reasons"])
    assert "Espacio público suficiente" in razones
    assert "Frente vial de jerarquía alta" in razones
    assert "Equipamientos cercanos" in razones


async def test_scoring_espacio_publico_insuficiente_no_bonus():
    """EPT < 15 m²/hab -> r_espacio_publico_suficiente NO se activa."""
    extras = {"indicadorespaciopublico": [feature_espacio_publico(ept=9.1)]}
    reporte = await reporte_de(provider_arcgis_fase3(extras=extras))

    score = reporte["feasibility_score"]
    assert "r_espacio_publico_suficiente" not in score["rules_applied"]
    assert reporte["public_space_context"]["estado"] == "disponible"


async def test_scoring_via_local_no_activa_frente_avenida():
    """Via local (KR) en el frente -> jerarquia media, sin bonus de avenida."""
    extras = {
        "Mapa_Referencia/Mapa_Referencia/MapServer/13/query": [feature_via(tipo="KR")]
    }
    reporte = await reporte_de(provider_arcgis_fase3(extras=extras))

    score = reporte["feasibility_score"]
    assert "r_frente_vial_avenida" not in score["rules_applied"]
    assert reporte["road_network_context"]["dato"]["jerarquia_maxima"] == "media"


# --- llm_ready_summary ---


async def test_llm_ready_summary_presente_y_determinista():
    """El informe publica llm_ready_summary; mismo input -> mismo texto (SC-003)."""
    arcgis = provider_arcgis_fase3()
    servidor = server_lotes_f3(arcgis=arcgis, normativa=NormativaProviderStub())
    try:
        reporte_1 = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
        reporte_2 = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    resumen = reporte_1["llm_ready_summary"]
    assert isinstance(resumen, str) and len(resumen) > 50
    assert resumen == reporte_2["llm_ready_summary"]
    # Contenido minimo: identidad, UPL, score y confidence
    assert "Lote 006101016001" in resumen
    assert f"CHIP {CHIP_VALIDO}" in resumen
    assert "UPL24 Chapinero" in resumen
    assert "localidad Chapinero" in resumen
    assert "Score de factibilidad" in resumen
    assert "confianza" in resumen


async def test_llm_ready_summary_enumera_bloques_degradados():
    """Los warnings BLOQUE_DEGRADADO/SIN_DATO alimentan la lista de bloques con problema."""
    arcgis = provider_arcgis_fase3({"espaciopublico/indicadorespaciopublico": 500})
    reporte = await reporte_de(arcgis)

    resumen = reporte["llm_ready_summary"]
    assert "Bloques degradados o sin datos:" in resumen
    assert "public_space_context" in resumen


# --- Nivel provider: jerarquia derivada y distancias ---


async def test_provider_red_vial_deriva_jerarquia_por_tipo():
    """La jerarquia se deriva de MVITIPO: AC alta, CL media, DG baja, desconocida si no matchea."""
    extras = {
        "Mapa_Referencia/Mapa_Referencia/MapServer/13/query": [
            feature_via(tipo="AC"),
            feature_via(tipo="CL"),
            feature_via(tipo="DG"),
            feature_via(tipo="XX"),
        ]
    }
    arcgis = provider_arcgis_fase3(extras=extras)
    try:
        red_vial, _traza, _trazas, fallos = await arcgis.consultar_red_vial(
            CENTROIDE_LNG, CENTROIDE_LAT
        )
    finally:
        await arcgis.aclose()

    assert fallos == []
    jerarquias = {via.tipo_via: via.jerarquia for via in red_vial.vias_frente}
    assert jerarquias == {"AC": "alta", "CL": "media", "DG": "baja", "XX": "desconocida"}
    assert red_vial.jerarquia_maxima == "alta"


async def test_provider_equipamientos_calcula_distancia_haversine():
    """La distancia se calcula desde el centroide sobre la geometria real del feature."""
    extras = {
        "serviciosips": [
            feature_equipamiento("IPS CERCANA", coords=[-74.083, 4.604])  # ~55 m al norte
        ],
    }
    arcgis = provider_arcgis_fase3(extras=extras)
    try:
        equipamientos, _traza, _trazas, fallos = (
            await arcgis.consultar_equipamientos_cercanos(CENTROIDE_LNG, CENTROIDE_LAT)
        )
    finally:
        await arcgis.aclose()

    assert fallos == []
    assert equipamientos.total_salud == 1
    cercano = equipamientos.mas_cercano
    assert cercano is not None
    # 0.0005 grados de latitud ~ 55 m (tolerancia amplia por haversine)
    assert cercano.distancia_m == pytest.approx(55.0, abs=10.0)
