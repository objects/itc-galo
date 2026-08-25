"""Contract tests de procedencia por sub-fuente en bloques multifuente (hallazgo M4).

Cada bloque multifuente (geotecnia, socioeconomico, regulatorio, patrimonio,
movilidad, catastro) publica `source_traces` con UNA traza por capa consultada
EXITOSAMENTE, cada una con su propia vigencia/fecha de consulta; las capas
caidas NO generan traza (su fallo viaja tipado en FalloCapa, FR-009). El campo
`source_trace` se conserva poblado (primera capa exitosa) para retrocompatibilidad.
"""

from __future__ import annotations

import re

import httpx

from app.providers.arcgis import ArcGISProvider
from tests.conftest import (
    CHIP_VALIDO,
    NormativaProviderStub,
    feature_lote,
    geojson,
    server_lotes_f3,
)


def provider_arcgis_procedencia(fallos_por_url: dict[str, int] | None = None):
    """Provider ArcGIS con features con vigencia propia en las capas multifuente.

    Cada capa responde 200 con un feature que declara su propio ANIO; las URLs
    listadas en `fallos_por_url` responden con el status indicado. Las capas
    imprescindibles del flujo feliz (Lote 38, tematicas F1, Predio pjson)
    responden estandar.
    """
    fallos_por_url = fallos_por_url or {}

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
        if "emergencias/gestionriesgos" in url:
            coincidencia = re.search(r"/MapServer/(\d+)/query", url)
            anio = {"2": 2021, "5": 2022, "7": 2023, "8": 2024}.get(
                coincidencia.group(1) if coincidencia else "", 2023
            )
            return httpx.Response(
                200,
                json=geojson([{"type": "Feature", "properties": {"GEOTECNIA": f"clase-{anio}", "ANIO": str(anio)}, "geometry": None}]),
            )
        if "estratificacion" in url:
            return httpx.Response(
                200,
                json=geojson([{"type": "Feature", "properties": {"ESTRATO": 3, "ANIO": "2024"}, "geometry": None}]),
            )
        if "usopredominante" in url:
            return httpx.Response(
                200,
                json=geojson([{"type": "Feature", "properties": {"GRUPOUSOECON": "Comercio"}, "geometry": None}]),
            )
        return httpx.Response(200, json=geojson([]))

    return ArcGISProvider(transport=httpx.MockTransport(handler))


async def test_geotecnia_publica_una_traza_por_capa_con_vigencia_propia():
    """Las 4 capas de gestionriesgos exitosas -> source_traces con 4 entradas,
    cada una con el source_name/layer_id/data_vigencia de SU capa (M4)."""
    arcgis = provider_arcgis_procedencia()
    try:
        _riesgos, principal, trazas, fallos = await arcgis.consultar_riesgos_geotecnicos(-74.083, 4.6035)
    finally:
        await arcgis.aclose()

    assert fallos == []
    assert len(trazas) == 4
    esperadas = [
        ("Gestión de Riesgos — Amenaza movimientos en masa urbano", "2", "2021"),
        ("Gestión de Riesgos — Geología Rural", "5", "2022"),
        ("Gestión de Riesgos — Respuesta Sísmica", "7", "2023"),
        ("Gestión de Riesgos — Zonificación Geotécnica", "8", "2024"),
    ]
    for traza, (source_name, layer_id, vigencia) in zip(trazas, esperadas):
        assert traza.source_name == source_name
        assert traza.layer_id == layer_id
        assert traza.data_vigencia == vigencia
        assert traza.query_timestamp
    # La traza principal es la primera capa exitosa (compatibilidad)
    assert principal is trazas[0]


async def test_capa_caida_no_genera_traza_solo_fallo_tipado():
    """Geologia caida -> source_traces sin entrada para esa capa y FalloCapa
    con la causa real; las otras 3 capas conservan su traza (FR-009 + M4)."""
    arcgis = provider_arcgis_procedencia({"emergencias/gestionriesgos/MapServer/5": 500})
    try:
        _riesgos, principal, trazas, fallos = await arcgis.consultar_riesgos_geotecnicos(-74.083, 4.6035)
    finally:
        await arcgis.aclose()

    nombres = [traza.source_name for traza in trazas]
    assert len(trazas) == 3
    assert "Gestión de Riesgos — Geología Rural" not in nombres
    assert len(fallos) == 1
    assert fallos[0].source_name == "Gestión de Riesgos — Geología Rural"
    assert "500" in fallos[0].detalle
    # La traza principal salta a la primera capa EXITOSA, no a la caida
    assert principal.source_name == "Gestión de Riesgos — Amenaza movimientos en masa urbano"


async def test_todas_las_capas_caidas_dejan_source_trace_poblado_sin_trazas_subfuente():
    """Fallo total: source_traces vacio (ninguna capa respondio) pero
    source_trace sigue poblado con la primera capa declarada (contrato)."""
    arcgis = provider_arcgis_procedencia({"emergencias/gestionriesgos": 500})
    try:
        _riesgos, principal, trazas, fallos = await arcgis.consultar_riesgos_geotecnicos(-74.083, 4.6035)
    finally:
        await arcgis.aclose()

    assert len(fallos) == 4
    assert trazas == []
    assert principal.source_name == "Gestión de Riesgos — Amenaza movimientos en masa urbano"


async def test_informe_publica_source_traces_y_conserva_source_trace():
    """get_feasibility_report: geotechnical_risks publica source_traces con una
    entrada por capa exitosa y source_trace sigue presente (= primera traza)."""
    arcgis = provider_arcgis_procedencia()
    servidor = server_lotes_f3(arcgis=arcgis, normativa=NormativaProviderStub())
    try:
        respuesta = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    bloque = respuesta["geotechnical_risks"]
    assert bloque["estado"] == "disponible"
    # Compatibilidad: source_trace sigue presente y es la primera sub-fuente
    assert bloque["source_trace"]["source_name"] == (
        "Gestión de Riesgos — Amenaza movimientos en masa urbano"
    )
    # Procedencia por sub-fuente: 4 entradas con vigencia propia por capa
    trazas = bloque["source_traces"]
    assert [t["source_name"] for t in trazas] == [
        "Gestión de Riesgos — Amenaza movimientos en masa urbano",
        "Gestión de Riesgos — Geología Rural",
        "Gestión de Riesgos — Respuesta Sísmica",
        "Gestión de Riesgos — Zonificación Geotécnica",
    ]
    assert [t["data_vigencia"] for t in trazas] == ["2021", "2022", "2023", "2024"]
    assert all(set(t) == {
        "source_name", "layer_id", "service_url", "data_vigencia", "query_timestamp"
    } for t in trazas)


async def test_informe_bloque_monofuente_no_publica_source_traces():
    """Los bloques monofuente (p. ej. planning_constraints) no cambian su shape:
    solo source_trace, sin clave source_traces."""
    servidor = server_lotes_f3()
    try:
        respuesta = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    assert "source_traces" not in respuesta["planning_constraints"]
    assert "source_trace" in respuesta["planning_constraints"]


async def test_resumen_catastro_publica_source_traces_por_subfuente():
    """get_lot_summary_by_chip: catastro_data expone source_traces (una entrada
    por capa exitosa) manteniendo source_trace para retrocompatibilidad."""
    arcgis = provider_arcgis_procedencia()
    servidor = server_lotes_f3(arcgis=arcgis, normativa=NormativaProviderStub())
    try:
        respuesta = await servidor.get_lot_summary_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    catastro = respuesta["catastro_data"]
    assert catastro["source_trace"]["source_name"] == "Catastro — Construcción"
    # Las 5 capas respondieron (aunque sin features): 5 trazas exitosas, cada
    # una con la vigencia declarada de su capa
    nombres = [t["source_name"] for t in catastro["source_traces"]]
    assert nombres == [
        "Catastro — Construcción",
        "Catastro — Manzana",
        "Catastro — Densidad Predial",
        "Catastro — Variación Área Construida",
        "Catastro — Sector Catastral",
    ]
    assert all(t["data_vigencia"] == "2024" for t in catastro["source_traces"])


async def test_resumen_catastro_con_capas_caidas_mantiene_compatibilidad():
    """Con todas las capas catastro caidas: source_traces vacio, source_trace
    poblado con la capa declarada y warning BLOQUE_DEGRADADO (regresion M2)."""
    arcgis = provider_arcgis_procedencia(
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
    catastro = respuesta["catastro_data"]
    assert catastro["estado"] == "no_encontrado"
    assert catastro["source_traces"] == []
    assert catastro["source_trace"]["source_name"] == "Catastro — Construcción"
    degradados = [w for w in respuesta["warnings"] if w["codigo"] == "BLOQUE_DEGRADADO"]
    assert any("catastro_data" in w["mensaje"] for w in degradados)
