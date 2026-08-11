"""Contract tests para F2 — Provider UPL (get_upl)."""

from __future__ import annotations

import httpx
import pytest

from app.providers.upl import UPLProvider, NOMBRE_UPL_A_LOCALIDAD


# Respuesta GeoJSON simulada de la capa UPL (layer 0)
FEATURE_UPL_EJEMPLO = {
    "type": "Feature",
    "properties": {
        "CODIGO_UPL": "UPL17",
        "NOMBRE": "Chapinero",
        "ACTO_ADMINISTRATIVO": "Decreto",
        "NUMERO_ACTO": "555",
        "FECHA_ACTO_ADMINISTRATIVO": "2021-12-30",
        "NORMATIVA": "POT Bogotá Reverdece",
        "VOCACION": "Urbano",
        "OBSERVACION": "Zona de renovación urbana",
        "AREA_HA": 450.5,
    },
    "geometry": None,
}

GEOJSON_UPL = {"type": "FeatureCollection", "features": [FEATURE_UPL_EJEMPLO]}


def handler_upl_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=GEOJSON_UPL)


def handler_upl_vacio(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"type": "FeatureCollection", "features": []})


def handler_upl_sin_campos(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"type": "FeatureCollection", "features": [{"properties": {}}]})


def handler_upl_500(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, json={"error": {"code": 500, "message": "Internal Server Error"}})


@pytest.fixture
def provider_upl_ok():
    return UPLProvider(transport=httpx.MockTransport(handler_upl_ok))


@pytest.fixture
def provider_upl_vacio():
    return UPLProvider(transport=httpx.MockTransport(handler_upl_vacio))


@pytest.fixture
def provider_upl_sin_campos():
    return UPLProvider(transport=httpx.MockTransport(handler_upl_sin_campos))


@pytest.fixture
def provider_upl_500():
    return UPLProvider(transport=httpx.MockTransport(handler_upl_500))


@pytest.mark.asyncio
async def test_upl_provider_consulta_punto_devuelve_upl_completa(provider_upl_ok):
    upl = await provider_upl_ok.consultar_upl_por_punto(-74.07, 4.65)
    await provider_upl_ok.aclose()

    assert upl.codigo_upl == "UPL17"
    assert upl.nombre == "Chapinero"
    assert upl.localidad_derivada == "Chapinero"
    assert upl.estado == "disponible"
    assert upl.source_trace is not None
    assert upl.source_trace.source_name == "IDECA Catastro — Unidad de Planeamiento Local"
    assert upl.source_trace.layer_id == "0"
    assert "unidadplaneamientolocal" in upl.source_trace.service_url
    assert upl.source_trace.data_vigencia == "2021-12-30"
    assert upl.acto_administrativo == "Decreto"
    assert upl.numero_acto_administrativo == "555"
    assert upl.fecha_acto_administrativo == "2021-12-30"
    assert upl.normativa == "POT Bogotá Reverdece"
    assert upl.vocacion == "Urbano"
    assert upl.observacion == "Zona de renovación urbana"
    assert upl.area_ha == 450.5


@pytest.mark.asyncio
async def test_upl_provider_sin_features_raise_fuente_datos_invalidos(provider_upl_vacio):
    with pytest.raises(Exception, match="no devolvio ningun feature"):
        await provider_upl_vacio.consultar_upl_por_punto(-74.07, 4.65)
    await provider_upl_vacio.aclose()


@pytest.mark.asyncio
async def test_upl_provider_feature_sin_campos_requeridos_raise(provider_upl_sin_campos):
    with pytest.raises(Exception, match="no tiene CODIGO_UPL o NOMBRE"):
        await provider_upl_sin_campos.consultar_upl_por_punto(-74.07, 4.65)
    await provider_upl_sin_campos.aclose()


@pytest.mark.asyncio
async def test_upl_provider_5xx_raise_fuente_5xx(provider_upl_500):
    from app.errores import Fuente5xxError
    with pytest.raises(Fuente5xxError):
        await provider_upl_500.consultar_upl_por_punto(-74.07, 4.65)
    await provider_upl_500.aclose()


def test_mapeo_nombre_upl_a_localidad_cubre_upls_principales():
    # Verifica que el mapeo estatico tiene las localidades principales
    assert NOMBRE_UPL_A_LOCALIDAD["SUMAPAZ"] == "Sumapaz"
    assert NOMBRE_UPL_A_LOCALIDAD["CHAPINERO"] == "Chapinero"
    assert NOMBRE_UPL_A_LOCALIDAD["KENNEDY"] == "Kennedy"
    assert NOMBRE_UPL_A_LOCALIDAD["SUBA"] == "Suba"
    assert NOMBRE_UPL_A_LOCALIDAD["USAQUEN"] == "Usaquen"
    # UPLs con sufijo RURAL
    assert NOMBRE_UPL_A_LOCALIDAD["SUMAPAZ RURAL"] == "Sumapaz"
    assert NOMBRE_UPL_A_LOCALIDAD["USME RURAL"] == "Usme"