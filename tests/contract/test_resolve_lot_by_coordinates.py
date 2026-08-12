"""Contract test de resolve_lot_by_coordinates (T027, Historia de Usuario 3)."""

from __future__ import annotations

from tests.conftest import (
    CHIP_VALIDO,
    CODIGO_CATASTRAL,
    MANZANA,
    construir_servidor,
    feature_lote,
    provider_arcgis_estandar,
)

LAT_DENTRO = 4.60313
LNG_DENTRO = -74.08327


async def test_punto_dentro_de_un_lote_resuelve_lote():
    servidor = construir_servidor()
    try:
        respuesta = await servidor.resolve_lot_by_coordinates(LAT_DENTRO, LNG_DENTRO)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    lote = respuesta["lote"]
    assert lote["chip"] == CHIP_VALIDO
    assert lote["codigo_catastral"] == CODIGO_CATASTRAL
    assert lote["manzana"] == MANZANA
    assert lote["centroid"] == {"lat": LAT_DENTRO, "lng": LNG_DENTRO}
    assert "contexto_tematico" in respuesta


async def test_punto_fuera_de_bogota_devuelve_fuera_de_cobertura():
    # La capa Lote no devuelve ningun feature para un punto fuera del area.
    arcgis = provider_arcgis_estandar(lotes=[])
    servidor = construir_servidor(arcgis=arcgis)
    try:
        respuesta = await servidor.resolve_lot_by_coordinates(6.25, -75.57)
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "FUERA_DE_COBERTURA"
    assert "fuera del área de cobertura" in respuesta["error"]["message"]


async def test_lote_unico_sin_chip_se_resuelve_con_chip_none():
    """Un lote unico sin CHIP (la capa Lote no trae el campo) es valido: la
    identidad catastral LOTCODIGO/MANZCODIGO es suficiente; chip=None en la
    respuesta (decision de producto, Fix B)."""
    arcgis_sin_chip = provider_arcgis_estandar(lotes=[feature_lote(chip=None)])
    servidor = construir_servidor(arcgis=arcgis_sin_chip)
    try:
        respuesta = await servidor.resolve_lot_by_coordinates(LAT_DENTRO, LNG_DENTRO)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    lote = respuesta["lote"]
    assert lote["chip"] is None
    assert lote["codigo_catastral"] == CODIGO_CATASTRAL
    assert lote["manzana"] == MANZANA
    assert "contexto_tematico" in respuesta


async def test_limite_entre_lotes_sin_lote_unico_devuelve_lote_no_encontrado():
    arcgis = provider_arcgis_estandar(
        lotes=[
            feature_lote(codigo_catastral="006202003016", chip="AAA0072LRYN"),
            feature_lote(codigo_catastral="006202003017", chip="AAA0072LRYO"),
        ]
    )
    servidor = construir_servidor(arcgis=arcgis)
    try:
        respuesta = await servidor.resolve_lot_by_coordinates(LAT_DENTRO, LNG_DENTRO)
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "LOTE_NO_ENCONTRADO"
    assert "lote único" in respuesta["error"]["message"]
