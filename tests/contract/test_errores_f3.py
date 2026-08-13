"""Contract tests F3 — errores fatales de `get_feasibility_report` (T010, FR-012).

LOTE_NO_ENCONTRADO, FUERA_DE_COBERTURA, DIRECCION_NO_LOCALIZADA,
CREDENCIAL_FALTANTE y FUENTE_5XX (un 5xx NUNCA se degrada a no_encontrado).
Formato de error: {"error": {"code", "message", "source_name"}}.

NOTA (TDD red): la tool `get_feasibility_report` AUN NO existe; estos tests
fallan con AttributeError hasta su implementacion (fase posterior).
"""

from __future__ import annotations

import httpx

from app.providers.mapas_bogota import MapasBogotaProvider
from tests.conftest import (
    CHIP_INEXISTENTE,
    CHIP_VALIDO,
    NormativaProviderStub,
    geocodificar_vacia,
    provider_arcgis_f3,
    server_lotes_f3,
)


async def test_chip_inexistente_devuelve_lote_no_encontrado():
    """CHIP sin predio en Mapas Bogota -> LOTE_NO_ENCONTRADO."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub())
    try:
        respuesta = await servidor.get_feasibility_report(chip=CHIP_INEXISTENTE)
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "LOTE_NO_ENCONTRADO"
    assert respuesta["error"]["message"]
    assert respuesta["error"]["source_name"] is None


async def test_punto_sin_lote_devuelve_fuera_de_cobertura():
    """Punto sin lote en la capa 38 (fuera de Bogota) -> FUERA_DE_COBERTURA."""
    arcgis_vacio = provider_arcgis_f3(lotes=[])
    servidor = server_lotes_f3(arcgis=arcgis_vacio, normativa=NormativaProviderStub())
    try:
        respuesta = await servidor.get_feasibility_report(coordenadas={"lat": 6.25, "lon": -75.57})
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "FUERA_DE_COBERTURA"
    assert "fuera del área de cobertura" in respuesta["error"]["message"]


async def test_direccion_no_localizada_devuelve_direccion_no_localizada():
    """Direccion que no geocodifica -> DIRECCION_NO_LOCALIZADA."""

    def _handler_geo_vacia(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cmd") == "geocodificar":
            return httpx.Response(200, json=geocodificar_vacia())
        return httpx.Response(500, json={"error": "cmd no simulado"})

    mapas = MapasBogotaProvider(transport=httpx.MockTransport(_handler_geo_vacia), api_key="clave")
    servidor = server_lotes_f3(mapas=mapas, normativa=NormativaProviderStub())
    try:
        respuesta = await servidor.get_feasibility_report(direccion="Direccion Inexistente 999")
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "DIRECCION_NO_LOCALIZADA"


async def test_direccion_sin_api_key_devuelve_credencial_faltante():
    """Direccion sin MAPAS_BOGOTA_APIKEY -> CREDENCIAL_FALTANTE sin llamar fuentes."""
    mapas = MapasBogotaProvider(api_key=None)
    servidor = server_lotes_f3(mapas=mapas, normativa=NormativaProviderStub())
    try:
        respuesta = await servidor.get_feasibility_report(direccion="Calle 26 # 69-76")
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "CREDENCIAL_FALTANTE"


async def test_5xx_de_capa_lote_devuelve_fuente_5xx_y_no_no_encontrado():
    """5xx de la capa Lote 38 -> FUENTE_5XX, NUNCA degradado a no_encontrado (FR-009)."""
    arcgis_5xx = provider_arcgis_f3(lotes=(None, 500))
    servidor = server_lotes_f3(arcgis=arcgis_5xx, normativa=NormativaProviderStub())
    try:
        respuesta = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "FUENTE_5XX"
    assert respuesta["error"]["source_name"] == "Mapa_Referencia/Mapa_Referencia"
    assert "no_encontrado" not in respuesta["error"]["message"].lower()


async def test_5xx_de_capa_predio_devuelve_fuente_5xx():
    """5xx de la capa Predio (economic_context) -> FUENTE_5XX, reporte NO degradado."""
    arcgis_5xx_predio = provider_arcgis_f3(predio=(None, 503))
    servidor = server_lotes_f3(arcgis=arcgis_5xx_predio, normativa=NormativaProviderStub())
    try:
        respuesta = await servidor.get_feasibility_report(chip=CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "FUENTE_5XX"
    assert respuesta["error"]["source_name"] == "Predio (catastro/lote)"
    assert "503" in respuesta["error"]["message"]
