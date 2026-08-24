"""Contract tests de reintentos con backoff en MapasBogotaProvider.

La E2E en vivo detecto 503 TRANSITORIOS por cold-start del backend de Mapas
Bogota (primera peticion tras reposo tarda segundos; luego todo OK). El provider
reintenta GETs idempotentes ante TransportError y HTTP >= 500 con backoff
exponencial corto; los 4xx no se reintentan. Tras agotar los intentos lanza
Fuente5xxError (FR-009: un 5xx NUNCA es "no encontrado") con la causa
distinguible en el mensaje.

Patron MockTransport de tests/conftest.py: sin red real y sin esperas reales
(el backoff se inyecta via `dormir`, que solo registra las pausas).
"""

from __future__ import annotations

import httpx
import pytest

from app.errores import Fuente4xxError, Fuente5xxError
from app.providers.mapas_bogota import MapasBogotaProvider

CHIP_VALIDO = "AAA0072LRYN"

RESPUESTA_CHIP_OK = {
    "resultados": [
        {
            "VALUE": CHIP_VALIDO,
            "NOMBRE": "CRA 12 # 10-20",
            "BARRIO": "LAS NIEVES",
            "GEOMETRY": {
                "rings": [
                    [
                        [-74.083, 4.603],
                        [-74.082, 4.603],
                        [-74.082, 4.604],
                        [-74.083, 4.604],
                        [-74.083, 4.603],
                    ]
                ]
            },
        }
    ],
    "status": True,
}


class RegistroSuenos:
    """Dormilón inyectable: registra las pausas de backoff sin esperar de verdad."""

    def __init__(self) -> None:
        self.pausas: list[float] = []

    async def __call__(self, segundos: float) -> None:
        self.pausas.append(segundos)


def provider_con_secuencia(secuencia, registro: RegistroSuenos):
    """Provider cuyo mock responde los items de `secuencia` en orden.

    Cada item es una httpx.Response o una excepcion httpx.TransportError.
    Si la secuencia se agota, repite el ultimo item (fallo persistente).
    """
    llamadas: list[httpx.Request] = []
    indice = {"valor": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas.append(request)
        posicion = min(indice["valor"], len(secuencia) - 1)
        indice["valor"] += 1
        item = secuencia[posicion]
        if isinstance(item, Exception):
            raise item
        return item

    provider = MapasBogotaProvider(
        transport=httpx.MockTransport(handler),
        api_key="clave-de-prueba",
        dormir=registro,
    )
    return provider, llamadas


async def test_500_transitorio_reintenta_y_tiene_exito_en_segundo_intento():
    registro = RegistroSuenos()
    provider, llamadas = provider_con_secuencia(
        [httpx.Response(500, json={"error": "cold-start"}), httpx.Response(200, json=RESPUESTA_CHIP_OK)],
        registro,
    )
    try:
        predio = await provider.buscar_por_chip(CHIP_VALIDO)
    finally:
        await provider.aclose()

    assert predio is not None
    assert predio.chip == CHIP_VALIDO
    assert len(llamadas) == 2  # 1 fallo + 1 reintento exitoso


async def test_transport_error_transitorio_tiene_exito_tras_reintento():
    registro = RegistroSuenos()
    provider, llamadas = provider_con_secuencia(
        [httpx.ConnectError("conexion rechazada"), httpx.Response(200, json=RESPUESTA_CHIP_OK)],
        registro,
    )
    try:
        predio = await provider.buscar_por_chip(CHIP_VALIDO)
    finally:
        await provider.aclose()

    assert predio is not None
    assert len(llamadas) == 2


async def test_fallo_5xx_persistente_agota_intentos_y_lanza_fuente_5xx():
    registro = RegistroSuenos()
    provider, llamadas = provider_con_secuencia(
        [httpx.Response(503, json={"error": "upstream"})],
        registro,
    )
    try:
        with pytest.raises(Fuente5xxError) as exc_info:
            await provider.buscar_por_chip(CHIP_VALIDO)
    finally:
        await provider.aclose()

    assert len(llamadas) == 3  # intentos por defecto
    assert exc_info.value.status == 503
    assert exc_info.value.source_name == "mapas_bogota"
    # Causa distinguible: agotamiento explicito de reintentos
    assert "tras 3 intentos" in str(exc_info.value)
    assert "persistente" in str(exc_info.value)


async def test_timeout_persistente_reporta_causa_timeout_en_el_mensaje():
    registro = RegistroSuenos()
    provider, llamadas = provider_con_secuencia(
        [httpx.ReadTimeout("timeout de lectura")],
        registro,
    )
    try:
        with pytest.raises(Fuente5xxError) as exc_info:
            await provider.buscar_por_chip(CHIP_VALIDO)
    finally:
        await provider.aclose()

    assert len(llamadas) == 3
    assert exc_info.value.status == 503
    assert "tras 3 intentos" in str(exc_info.value)
    assert "timeout" in str(exc_info.value)


async def test_backoff_exponencial_corto_entre_intentos():
    registro = RegistroSuenos()
    provider, _ = provider_con_secuencia(
        [httpx.Response(503, json={"error": "upstream"})],
        registro,
    )
    try:
        with pytest.raises(Fuente5xxError):
            await provider.buscar_por_chip(CHIP_VALIDO)
    finally:
        await provider.aclose()

    # Defaults: 3 intentos -> 2 pausas exponenciales 0.5s -> 1.0s
    assert registro.pausas == [0.5, 1.0]


async def test_4xx_no_se_reintenta_y_falla_inmediato():
    registro = RegistroSuenos()
    provider, llamadas = provider_con_secuencia(
        [httpx.Response(400, json={"error": "peticion invalida"})],
        registro,
    )
    try:
        with pytest.raises(Fuente4xxError):
            await provider.buscar_por_chip(CHIP_VALIDO)
    finally:
        await provider.aclose()

    assert len(llamadas) == 1  # sin reintentos para 4xx
    assert registro.pausas == []  # ni una sola espera


async def test_exito_al_primer_intento_no_espera_nunca():
    registro = RegistroSuenos()
    provider, llamadas = provider_con_secuencia(
        [httpx.Response(200, json=RESPUESTA_CHIP_OK)],
        registro,
    )
    try:
        predio = await provider.buscar_por_chip(CHIP_VALIDO)
    finally:
        await provider.aclose()

    assert predio is not None
    assert len(llamadas) == 1
    assert registro.pausas == []


async def test_intentos_menor_a_uno_se_rechaza_fail_fast():
    with pytest.raises(ValueError, match="intentos"):
        MapasBogotaProvider(intentos=0)
