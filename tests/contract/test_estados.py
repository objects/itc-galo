"""Contract tests de estados de dato por fuente (T035, FR-007, SC-002).

El 100% de las respuestas distingue "disponible" de "no_encontrado"; un dato
ausente se reporta como no_encontrado, nunca como cero ni vacio silencioso.
"""

from __future__ import annotations

from tests.conftest import (
    CHIP_VALIDO,
    construir_servidor,
    provider_arcgis_estandar,
)

ESTADOS_VALIDOS = {"disponible", "no_encontrado"}


async def test_todas_las_tematicas_reportan_estado():
    servidor = construir_servidor()
    try:
        respuesta = await servidor.resolve_lot_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    contexto = respuesta["contexto_tematico"]
    assert len(contexto) == 3
    for nombre, bloque in contexto.items():
        assert bloque["estado"] in ESTADOS_VALIDOS, nombre
        if bloque["estado"] == "no_encontrado":
            assert bloque["dato"] is None
        else:
            assert bloque["dato"] is not None


async def test_fuente_sin_dato_reporta_no_encontrado_y_no_cero():
    # obras_publicas sin features y reserva_vial sin features -> no_encontrado
    arcgis = provider_arcgis_estandar(obras=[], reserva=[])
    servidor = construir_servidor(arcgis=arcgis)
    try:
        respuesta = await servidor.resolve_lot_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    contexto = respuesta["contexto_tematico"]
    assert contexto["obras_publicas"]["estado"] == "no_encontrado"
    assert contexto["obras_publicas"]["dato"] is None
    assert contexto["reserva_vial"]["estado"] == "no_encontrado"
    assert contexto["reserva_vial"]["dato"] is None
    # Las demas tematicas siguen disponibles
    assert contexto["valor_referencia"]["estado"] == "disponible"


async def test_estados_en_el_resumen_por_fuente():
    servidor = construir_servidor()
    try:
        respuesta = await servidor.get_lot_summary_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    por_fuente = respuesta["contexto_por_fuente"]
    assert len(por_fuente) == 3
    for bloque in por_fuente:
        assert bloque["estado"] in ESTADOS_VALIDOS
