"""Contract tests de validacion FR-012 (T033).

CHIP mal formado, direccion vacia y coordenadas fuera de rango -> PARAMETROS_INVALIDOS,
sin llamar a las fuentes (fail-fast).
"""

from __future__ import annotations

from tests.conftest import construir_servidor

CHIPS_INVALIDOS = [
    "abc",  # demasiado corto
    "AAA0072LRY",  # 10 caracteres
    "AAA0072LRYNA",  # 12 caracteres
    "aaa0072lryn",  # minusculas
    "AAA 072LRYN",  # espacio
    "AAA0072LRYÑ",  # caracter fuera de [A-Z0-9]
]


async def test_chip_mal_formado_devuelve_parametros_invalidos():
    servidor = construir_servidor()
    try:
        for chip in CHIPS_INVALIDOS:
            respuesta = await servidor.resolve_lot_by_chip(chip)
            assert respuesta["error"]["code"] == "PARAMETROS_INVALIDOS", chip
            assert "11 caracteres alfanuméricos" in respuesta["error"]["message"], chip

            respuesta_resumen = await servidor.get_lot_summary_by_chip(chip)
            assert respuesta_resumen["error"]["code"] == "PARAMETROS_INVALIDOS", chip
    finally:
        await servidor.aclose()


async def test_direccion_vacia_devuelve_parametros_invalidos():
    servidor = construir_servidor()
    try:
        for direccion in ["", "   ", "\t\n"]:
            respuesta = await servidor.resolve_lot_by_address(direccion)
            assert respuesta["error"]["code"] == "PARAMETROS_INVALIDOS"
            assert "no puede estar vacía" in respuesta["error"]["message"]
    finally:
        await servidor.aclose()


async def test_coordenadas_fuera_de_rango_devuelven_parametros_invalidos():
    servidor = construir_servidor()
    try:
        casos = [
            (91.0, -74.08),  # latitud > 90
            (-91.0, -74.08),  # latitud < -90
            (4.6, 181.0),  # longitud > 180
            (4.6, -181.0),  # longitud < -180
        ]
        for lat, lng in casos:
            respuesta = await servidor.resolve_lot_by_coordinates(lat, lng)
            assert respuesta["error"]["code"] == "PARAMETROS_INVALIDOS", (lat, lng)
    finally:
        await servidor.aclose()
