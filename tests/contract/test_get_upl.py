"""Contract tests para F2 — Tool MCP `get_upl` (Historia de Usuario 2, FR-005)."""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import (
    CHIP_VALIDO,
    CHIP_INEXISTENTE,
    CODIGO_CATASTRAL,
    MANZANA,
    feature_lote,
    geocodificar_unica,
    geocodificar_varias,
    geocodificar_vacia,
    provider_arcgis_estandar,
    provider_mapas_estandar,
    provider_sdp_f3,
)
from app.providers.upl import NOMBRE_UPL_A_LOCALIDAD


# Handler para la capa UPL (layer 0 unidadplaneamientolocal)
def handler_upl_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "CODIGO_UPL": "UPL17",
                "NOMBRE": "CHAPINERO",
                "ACTO_ADMINISTRATIVO": "Decreto",
                "NUMERO_ACTO": "555",
                "FECHA_ACTO_ADMINISTRATIVO": "2021-12-30",
                "NORMATIVA": "POT Bogotá Reverdece",
                "VOCACION": "Urbano",
                "OBSERVACION": "Zona de renovación urbana",
                "AREA_HA": 450.5,
            },
            "geometry": None,
        }]
    })


def handler_upl_vacio(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"type": "FeatureCollection", "features": []})


def handler_upl_500(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, json={"error": {"code": 500, "message": "Internal Server Error"}})


def _crear_servidor_con_upl(upl_handler, arcgis=None):
    """Helper para crear ServidorLotes con UPL mockeado y Mapas Bogota estándar."""
    from app.providers.upl import UPLProvider
    from app.main import ServidorLotes

    return ServidorLotes(
        provider_mapas_estandar(),
        arcgis if arcgis is not None else provider_arcgis_estandar(),
        UPLProvider(transport=httpx.MockTransport(upl_handler)),
        __import__('app.providers.normativa', fromlist=['NormativaProvider']).NormativaProvider(),
        provider_sdp_f3(),  # SDP mockeado: get_upl no lo consulta (hallazgo M5)
    )


# --- Tests por CHIP ---

@pytest.mark.asyncio
async def test_get_upl_por_chip_devuelve_upl_con_localidad():
    """CHIP válido -> UPL con código, nombre y localidad derivada."""
    servidor = _crear_servidor_con_upl(handler_upl_ok)
    try:
        resp = await servidor.get_upl(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "error" not in resp
    assert "upl" in resp
    assert resp["upl"]["codigo"] == "UPL17"
    assert resp["upl"]["nombre"] == "CHAPINERO"
    assert resp["upl"]["localidad"] == "Chapinero"
    assert resp["metodo_resolucion"] == "centroide_lote"
    assert "trazabilidad" in resp
    trace = resp["trazabilidad"]
    assert trace["source_name"] == "IDECA Catastro — Unidad de Planeamiento Local"
    assert trace["layer_id"] == "0"
    assert "unidadplaneamientolocal" in trace["service_url"]
    assert trace["data_vigencia"] == "2021-12-30"


@pytest.mark.asyncio
async def test_get_upl_chip_inexistente_devuelve_lote_no_encontrado():
    """CHIP inexistente -> LOTE_NO_ENCONTRADO (ArcGIS layer 38 vacío)."""
    arcgis_vacio = provider_arcgis_estandar(lotes=[])
    servidor = _crear_servidor_con_upl(handler_upl_ok, arcgis=arcgis_vacio)
    try:
        resp = await servidor.get_upl(chip=CHIP_INEXISTENTE)
    finally:
        await servidor.aclose()

    assert resp["error"]["code"] == "LOTE_NO_ENCONTRADO"


@pytest.mark.asyncio
async def test_get_upl_chip_mal_formado_devuelve_parametros_invalidos():
    """CHIP mal formado -> PARAMETROS_INVALIDOS."""
    servidor = _crear_servidor_con_upl(handler_upl_ok)
    try:
        resp = await servidor.get_upl(chip="CHIP_MALO")
    finally:
        await servidor.aclose()

    assert resp["error"]["code"] == "PARAMETROS_INVALIDOS"
    assert "CHIP debe tener 11 caracteres" in resp["error"]["message"]


# --- Tests por dirección ---

@pytest.mark.asyncio
async def test_get_upl_por_direccion_devuelve_upl():
    """Dirección válida con API key -> UPL."""
    servidor = _crear_servidor_con_upl(handler_upl_ok)
    try:
        resp = await servidor.get_upl(direccion="Calle 26 # 69-76")
    finally:
        await servidor.aclose()

    assert "error" not in resp
    assert resp["upl"]["codigo"] == "UPL17"
    assert resp["metodo_resolucion"] == "centroide_lote"


@pytest.mark.asyncio
async def test_get_upl_direccion_sin_api_key_devuelve_credencial_faltante():
    """Dirección sin MAPAS_BOGOTA_APIKEY -> CREDENCIAL_FALTANTE."""
    from app.providers.upl import UPLProvider
    from app.providers.mapas_bogota import MapasBogotaProvider
    from app.main import ServidorLotes
    from app.providers.arcgis import ArcGISProvider

    servidor = ServidorLotes(
        MapasBogotaProvider(api_key=None),  # Sin API key
        ArcGISProvider(),
        UPLProvider(transport=httpx.MockTransport(handler_upl_ok)),
        __import__('app.providers.normativa', fromlist=['NormativaProvider']).NormativaProvider(),
        provider_sdp_f3(),  # SDP mockeado: get_upl no lo consulta (hallazgo M5)
    )
    try:
        resp = await servidor.get_upl(direccion="Calle 26 # 69-76")
    finally:
        await servidor.aclose()

    assert resp["error"]["code"] == "CREDENCIAL_FALTANTE"


@pytest.mark.asyncio
async def test_get_upl_direccion_no_localizada_devuelve_direccion_no_localizada():
    """Dirección que no geocodifica -> DIRECCION_NO_LOCALIZADA."""
    from app.providers.upl import UPLProvider
    from app.providers.mapas_bogota import MapasBogotaProvider
    from app.main import ServidorLotes
    from app.providers.arcgis import ArcGISProvider

    def handler_geo_vacia(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cmd") == "geocodificar":
            return httpx.Response(200, json=geocodificar_vacia())
        return httpx.Response(200, json={"resultados": []})

    servidor = ServidorLotes(
        MapasBogotaProvider(transport=httpx.MockTransport(handler_geo_vacia), api_key="clave"),
        ArcGISProvider(),
        UPLProvider(transport=httpx.MockTransport(handler_upl_ok)),
        __import__('app.providers.normativa', fromlist=['NormativaProvider']).NormativaProvider(),
        provider_sdp_f3(),  # SDP mockeado: get_upl no lo consulta (hallazgo M5)
    )
    try:
        resp = await servidor.get_upl(direccion="Direccion Inexistente 999")
    finally:
        await servidor.aclose()

    assert resp["error"]["code"] == "DIRECCION_NO_LOCALIZADA"


@pytest.mark.asyncio
async def test_get_upl_direccion_multiples_candidatos_devuelve_candidatos():
    """Dirección ambigua -> multiples_candidatos."""
    from app.providers.upl import UPLProvider
    from app.providers.mapas_bogota import MapasBogotaProvider
    from app.main import ServidorLotes
    from app.providers.arcgis import ArcGISProvider

    def handler_geo_varias(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cmd") == "geocodificar":
            return httpx.Response(200, json=geocodificar_varias())
        return httpx.Response(200, json={"resultados": []})

    servidor = ServidorLotes(
        MapasBogotaProvider(transport=httpx.MockTransport(handler_geo_varias), api_key="clave"),
        ArcGISProvider(),
        UPLProvider(transport=httpx.MockTransport(handler_upl_ok)),
        __import__('app.providers.normativa', fromlist=['NormativaProvider']).NormativaProvider(),
        provider_sdp_f3(),  # SDP mockeado: get_upl no lo consulta (hallazgo M5)
    )
    try:
        resp = await servidor.get_upl(direccion="Calle 26 # 69-76")
    finally:
        await servidor.aclose()

    assert resp.get("multiples_candidatos") is True
    assert len(resp["candidatos"]) == 2


# --- Tests por coordenadas ---

@pytest.mark.asyncio
async def test_get_upl_por_coordenadas_devuelve_upl():
    """Coordenadas válidas en Bogotá -> UPL."""
    servidor = _crear_servidor_con_upl(handler_upl_ok)
    try:
        resp = await servidor.get_upl(coordenadas={"lat": 4.65, "lon": -74.07})
    finally:
        await servidor.aclose()

    assert "error" not in resp
    assert resp["upl"]["codigo"] == "UPL17"
    assert resp["metodo_resolucion"] == "centroide_lote"


@pytest.mark.asyncio
async def test_get_upl_coordenadas_fuera_de_bogota_devuelve_fuera_de_cobertura():
    """Punto fuera de Bogotá -> FUERA_DE_COBERTURA."""
    arcgis_vacio = provider_arcgis_estandar(lotes=[])
    servidor = _crear_servidor_con_upl(handler_upl_ok, arcgis=arcgis_vacio)
    try:
        resp = await servidor.get_upl(coordenadas={"lat": 6.25, "lon": -75.57})
    finally:
        await servidor.aclose()

    assert resp["error"]["code"] == "FUERA_DE_COBERTURA"


@pytest.mark.asyncio
async def test_get_upl_coordenadas_lote_sin_chip_resuelve_por_centroide():
    """Lote unico sin CHIP en la capa 38 -> la UPL se resuelve por el centroide
    del lote (la identidad catastral LOTCODIGO/MANZCODIGO es suficiente; el
    fallback punto_directo queda solo para puntos ambiguos entre lotes)."""
    arcgis_sin_chip = provider_arcgis_estandar(lotes=[feature_lote(chip=None)])
    servidor = _crear_servidor_con_upl(handler_upl_ok, arcgis=arcgis_sin_chip)
    try:
        resp = await servidor.get_upl(coordenadas={"lat": 4.65, "lon": -74.07})
    finally:
        await servidor.aclose()

    assert "error" not in resp
    assert resp["metodo_resolucion"] == "centroide_lote"
    assert resp["upl"]["codigo"] == "UPL17"
    assert resp["trazabilidad"]["layer_id"] == "0"


@pytest.mark.asyncio
async def test_get_upl_coordenadas_punto_ambiguo_fallback_punto_directo():
    """Punto en limite entre dos lotes -> fallback: UPL por punto de entrada."""
    arcgis_ambiguo = provider_arcgis_estandar(
        lotes=[feature_lote(), feature_lote(codigo_catastral="006202003017")]
    )
    servidor = _crear_servidor_con_upl(handler_upl_ok, arcgis=arcgis_ambiguo)
    try:
        resp = await servidor.get_upl(coordenadas={"lat": 4.65, "lon": -74.07})
    finally:
        await servidor.aclose()

    assert "error" not in resp
    assert resp["metodo_resolucion"] == "punto_directo"
    assert resp["upl"]["codigo"] == "UPL17"


@pytest.mark.asyncio
async def test_get_upl_coordenadas_fallback_sin_upl_devuelve_lote_sin_upl():
    """Fallback (punto ambiguo entre lotes) sin dato en la capa UPL ->
    LOTE_SIN_UPL (dato no encontrado, FR-007)."""
    arcgis_ambiguo = provider_arcgis_estandar(
        lotes=[feature_lote(), feature_lote(codigo_catastral="006202003017")]
    )
    servidor = _crear_servidor_con_upl(handler_upl_vacio, arcgis=arcgis_ambiguo)
    try:
        resp = await servidor.get_upl(coordenadas={"lat": 4.65, "lon": -74.07})
    finally:
        await servidor.aclose()

    assert resp["error"]["code"] == "LOTE_SIN_UPL"


@pytest.mark.asyncio
async def test_get_upl_coordenadas_fallback_5xx_devuelve_fuente_5xx():
    """Fallback (punto ambiguo entre lotes) con 5xx en la capa UPL -> FUENTE_5XX
    (nunca LOTE_SIN_UPL, FR-009)."""
    arcgis_ambiguo = provider_arcgis_estandar(
        lotes=[feature_lote(), feature_lote(codigo_catastral="006202003017")]
    )
    servidor = _crear_servidor_con_upl(handler_upl_500, arcgis=arcgis_ambiguo)
    try:
        resp = await servidor.get_upl(coordenadas={"lat": 4.65, "lon": -74.07})
    finally:
        await servidor.aclose()

    assert resp["error"]["code"] == "FUENTE_5XX"


@pytest.mark.asyncio
async def test_get_upl_coordenadas_5xx_capa38_no_fallback():
    """5xx de la capa Lote 38 -> FUENTE_5XX de esa fuente, sin fallback (FR-009)."""
    arcgis_5xx = provider_arcgis_estandar(
        lotes=({"error": {"code": 500, "message": "boom"}}, 500)
    )
    servidor = _crear_servidor_con_upl(handler_upl_ok, arcgis=arcgis_5xx)
    try:
        resp = await servidor.get_upl(coordenadas={"lat": 4.65, "lon": -74.07})
    finally:
        await servidor.aclose()

    assert resp["error"]["code"] == "FUENTE_5XX"
    assert resp["error"]["source_name"] == "Mapa_Referencia/Mapa_Referencia"


@pytest.mark.asyncio
async def test_get_upl_coordenadas_fuera_de_rango_devuelve_parametros_invalidos():
    """Coordenadas fuera de rango WGS84 -> PARAMETROS_INVALIDOS."""
    servidor = _crear_servidor_con_upl(handler_upl_ok)
    try:
        resp = await servidor.get_upl(coordenadas={"lat": 91, "lon": -74})
    finally:
        await servidor.aclose()

    assert resp["error"]["code"] == "PARAMETROS_INVALIDOS"


# --- Tests de validación de entrada (FR-013) ---

@pytest.mark.asyncio
async def test_get_upl_sin_criterio_devuelve_parametros_invalidos():
    """Sin chip/direccion/coordenadas -> PARAMETROS_INVALIDOS."""
    servidor = _crear_servidor_con_upl(handler_upl_ok)
    try:
        resp = await servidor.get_upl()
    finally:
        await servidor.aclose()

    assert resp["error"]["code"] == "PARAMETROS_INVALIDOS"
    assert "exactamente uno" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_get_upl_mas_de_un_criterio_devuelve_parametros_invalidos():
    """Más de un criterio -> PARAMETROS_INVALIDOS."""
    servidor = _crear_servidor_con_upl(handler_upl_ok)
    try:
        resp = await servidor.get_upl(chip=CHIP_VALIDO, direccion="Calle 1")
    finally:
        await servidor.aclose()

    assert resp["error"]["code"] == "PARAMETROS_INVALIDOS"
    assert "exactamente uno" in resp["error"]["message"]


# --- Tests de errores de fuente ---

@pytest.mark.asyncio
async def test_get_upl_fuente_5xx_devuelve_fuente_5xx():
    """UPL devuelve 5xx -> FUENTE_5XX (no LOTE_SIN_UPL)."""
    servidor = _crear_servidor_con_upl(handler_upl_500)
    try:
        resp = await servidor.get_upl(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert resp["error"]["code"] == "FUENTE_5XX"


@pytest.mark.asyncio
async def test_get_upl_sin_upl_devuelve_lote_sin_upl():
    """Lote existe pero sin UPL asignada -> LOTE_SIN_UPL."""
    servidor = _crear_servidor_con_upl(handler_upl_vacio)
    try:
        resp = await servidor.get_upl(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert resp["error"]["code"] == "LOTE_SIN_UPL"
    assert (
        resp["error"]["message"]
        == "El lote no tiene UPL asignada (dato no encontrado)."
    )


# --- Test de mapeo nombre UPL -> localidad ---

def test_mapeo_nombre_upl_a_localidad_cubre_casos():
    """Verifica mapeo estático para UPLs principales."""
    assert NOMBRE_UPL_A_LOCALIDAD["CHAPINERO"] == "Chapinero"
    assert NOMBRE_UPL_A_LOCALIDAD["KENNEDY"] == "Kennedy"
    assert NOMBRE_UPL_A_LOCALIDAD["SUBA"] == "Suba"
    assert NOMBRE_UPL_A_LOCALIDAD["SUMAPAZ"] == "Sumapaz"
    assert NOMBRE_UPL_A_LOCALIDAD["SUMAPAZ RURAL"] == "Sumapaz"
    assert NOMBRE_UPL_A_LOCALIDAD["USME RURAL"] == "Usme"