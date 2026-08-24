"""Contract tests de la taxonomia de errores (T032).

Un 5xx de la fuente se reporta como FUENTE_5XX y NUNCA como no encontrado (FR-009).
Se verifican los 10 codigos canonicos del contrato (los 7 de F1 + LOTE_SIN_UPL,
CORPUS_NO_INGESTADO y OLLAMA_NO_DISPONIBLE de F2; data-model.md:219-249).
"""

from __future__ import annotations

import httpx

from tests.conftest import (
    CHIP_VALIDO,
    construir_servidor,
    geocodificar_unica,
    provider_arcgis_estandar,
)
from app.errores import CodigoError, construir_error
from app.providers.mapas_bogota import MapasBogotaProvider

CODIGOS_CANONICOS = {
    "LOTE_NO_ENCONTRADO",
    "DIRECCION_NO_LOCALIZADA",
    "FUERA_DE_COBERTURA",
    "DATO_NO_ENCONTRADO_POR_FUENTE",
    "FUENTE_5XX",
    "CREDENCIAL_FALTANTE",
    "PARAMETROS_INVALIDOS",
    "LOTE_SIN_UPL",
    "CORPUS_NO_INGESTADO",
    "OLLAMA_NO_DISPONIBLE",
}


def test_los_10_codigos_canonicos_existen():
    codigos = {c.value for c in CodigoError}
    assert codigos == CODIGOS_CANONICOS


async def test_5xx_de_capa_tematica_es_fuente_5xx_y_no_no_encontrado():
    arcgis = provider_arcgis_estandar(valor=(None, 503))
    servidor = construir_servidor(arcgis=arcgis)
    try:
        respuesta = await servidor.resolve_lot_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "FUENTE_5XX"
    assert respuesta["error"]["source_name"] == "catastro/valorreferencia"
    assert "503" in respuesta["error"]["message"]
    # Nunca se confunde con un estado de dato de la fuente
    assert "no_encontrado" not in respuesta["error"]["message"].lower()


async def test_5xx_de_capa_lote_es_fuente_5xx():
    arcgis = provider_arcgis_estandar(lotes=(None, 500))
    servidor = construir_servidor(arcgis=arcgis)
    try:
        respuesta = await servidor.resolve_lot_by_coordinates(4.6, -74.08)
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "FUENTE_5XX"
    assert respuesta["error"]["source_name"] == "Mapa_Referencia/Mapa_Referencia"


async def test_5xx_de_mapas_bogota_es_fuente_5xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"error": "upstream"})

    # backoff_segundos=0: fallo persistente simulado, sin esperas reales
    mapas = MapasBogotaProvider(
        transport=httpx.MockTransport(handler),
        api_key="clave-de-prueba",
        backoff_segundos=0.0,
    )
    servidor = construir_servidor(mapas=mapas)
    try:
        respuesta = await servidor.resolve_lot_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "FUENTE_5XX"
    assert respuesta["error"]["source_name"] == "mapas_bogota"


async def test_chip_desconocido_con_body_status_false_no_es_5xx():
    """La API viva responde HTTP 200 {"mensaje": "...", "status": false} para un
    CHIP desconocido. Ese body NO es un 5xx de fuente (FR-009): se mapea a
    LOTE_NO_ENCONTRADO, nunca a FUENTE_5XX."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"mensaje": "El servicio no esta disponible", "status": False}
        )

    mapas = MapasBogotaProvider(transport=httpx.MockTransport(handler), api_key="clave-de-prueba")
    servidor = construir_servidor(mapas=mapas)
    try:
        respuesta = await servidor.resolve_lot_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "LOTE_NO_ENCONTRADO"


async def test_clave_invalida_de_geocodificacion_es_credencial_faltante():
    """La API viva rechaza una clave invalida con HTTP 200
    {"message": "API Key no valida", "status": false}: se reporta como
    CREDENCIAL_FALTANTE (problema de credencial), no como direccion no localizada."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cmd") == "geocodificar":
            return httpx.Response(
                200, json={"message": "API Key no valida", "status": False}
            )
        return httpx.Response(200, json=geocodificar_unica())

    mapas = MapasBogotaProvider(transport=httpx.MockTransport(handler), api_key="clave-invalida")
    servidor = construir_servidor(mapas=mapas)
    try:
        respuesta = await servidor.resolve_lot_by_address("Calle 26 # 69-76")
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "CREDENCIAL_FALTANTE"


async def test_5xx_de_geocodificacion_es_fuente_5xx_y_no_direccion_no_localizada():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cmd") == "geocodificar":
            return httpx.Response(503, json={"error": "upstream"})
        return httpx.Response(200, json=geocodificar_unica())

    # backoff_segundos=0: fallo persistente simulado, sin esperas reales
    mapas = MapasBogotaProvider(
        transport=httpx.MockTransport(handler),
        api_key="clave-de-prueba",
        backoff_segundos=0.0,
    )
    servidor = construir_servidor(mapas=mapas)
    try:
        respuesta = await servidor.resolve_lot_by_address("Calle 26 # 69-76")
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "FUENTE_5XX"
    assert respuesta["error"]["source_name"] == "mapas_bogota"


async def test_dato_no_encontrado_por_fuente_cuando_lote_si_existe_y_tematica_no():
    # El lote SÍ se resuelve, pero valor_referencia no tiene dato para ese lote
    # (data-model.md:146): no es un 5xx de la fuente ni un lote no encontrado.
    # Es no fatal: se reporta por fuente como estado="no_encontrado" (FR-007) y
    # el codigo canonico es DATO_NO_ENCONTRADO_POR_FUENTE.
    arcgis = provider_arcgis_estandar(valor=[])
    servidor = construir_servidor(arcgis=arcgis)
    try:
        respuesta = await servidor.resolve_lot_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    contexto = respuesta["contexto_tematico"]
    assert contexto["valor_referencia"]["estado"] == "no_encontrado"
    assert contexto["valor_referencia"]["dato"] is None
    assert contexto["valor_referencia"]["source_trace"]["source_name"] == "catastro/valorreferencia"

    error = construir_error(
        CodigoError.DATO_NO_ENCONTRADO_POR_FUENTE,
        source_name=contexto["valor_referencia"]["source_trace"]["source_name"],
    )
    assert error["error"]["code"] == "DATO_NO_ENCONTRADO_POR_FUENTE"
    assert (
        error["error"]["message"]
        == "La fuente catastro/valorreferencia no tiene datos para este lote."
    )
    assert error["error"]["source_name"] == "catastro/valorreferencia"
