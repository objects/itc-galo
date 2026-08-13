"""Contract tests F3 — validacion fail-fast de `get_feasibility_report` (T009, FR-013).

Cero o mas de un criterio de {chip, direccion, coordenadas}, CHIP mal formado,
coordenadas fuera de rango o sin lat/lon, consulta > 500 y top_k fuera de 1-6
-> PARAMETROS_INVALIDOS SIN llamar a las fuentes (fail-fast).

NOTA (TDD red): la tool `get_feasibility_report` AUN NO existe; estos tests
fallan con AttributeError hasta su implementacion (fase posterior).
"""

from __future__ import annotations

import httpx

from app.main import ServidorLotes
from app.providers.arcgis import ArcGISProvider
from app.providers.mapas_bogota import MapasBogotaProvider
from app.providers.upl import UPLProvider
from tests.conftest import (
    CHIP_VALIDO,
    NormativaProviderStub,
    respuesta_normativa_ok,
    server_lotes_f3,
)

CHIPS_INVALIDOS = [
    "abc",  # demasiado corto
    "AAA0072LRY",  # 10 caracteres
    "AAA0072LRYNA",  # 12 caracteres
    "aaa0072lryn",  # minusculas
    "AAA 072LRYN",  # espacio
    "AAA0072LRYÑ",  # caracter fuera de [A-Z0-9]
]

# Strings que el contrato NO considera una direccion/consulta valida (minLength 1).
DIRECCIONES_VACIAS = ["", "   ", "\t\n"]
CONSULTAS_VACIAS = ["", "   "]


def _handler_fuente_no_consultada(request: httpx.Request) -> httpx.Response:
    """Fuente trampa: si la tool la consulta con parametros invalidos, falla ruidoso."""
    raise AssertionError("La fuente no debe consultarse con parámetros inválidos (fail-fast FR-013)")


def _servidor_con_fuentes_trampa() -> tuple[ServidorLotes, NormativaProviderStub]:
    """Servidor cuyas fuentes fallan si se consultan: la validacion debe cortar antes.

    Devuelve (servidor, stub_normativa) para verificar fail-fast total (MINOR 9):
    una entrada invalida no debe consultar NINGUNA fuente (stub.llamadas == []).
    """
    stub = NormativaProviderStub()
    return (
        ServidorLotes(
            MapasBogotaProvider(
                transport=httpx.MockTransport(_handler_fuente_no_consultada), api_key="clave"
            ),
            ArcGISProvider(transport=httpx.MockTransport(_handler_fuente_no_consultada)),
            UPLProvider(transport=httpx.MockTransport(_handler_fuente_no_consultada)),
            stub,
        ),
        stub,
    )


async def test_sin_criterio_devuelve_parametros_invalidos():
    """Ninguno de chip/direccion/coordenadas -> PARAMETROS_INVALIDOS."""
    servidor, stub = _servidor_con_fuentes_trampa()
    try:
        respuesta = await servidor.get_feasibility_report()
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "PARAMETROS_INVALIDOS"
    assert "exactamente uno" in respuesta["error"]["message"]
    assert stub.llamadas == []  # fail-fast: ninguna fuente consultada


async def test_mas_de_un_criterio_devuelve_parametros_invalidos():
    """chip+direccion o chip+coordenadas -> PARAMETROS_INVALIDOS."""
    servidor, stub = _servidor_con_fuentes_trampa()
    try:
        respuesta = await servidor.get_feasibility_report(chip=CHIP_VALIDO, direccion="Calle 26 # 69-76")
        assert respuesta["error"]["code"] == "PARAMETROS_INVALIDOS"

        respuesta = await servidor.get_feasibility_report(
            chip=CHIP_VALIDO, coordenadas={"lat": 4.6, "lon": -74.08}
        )
        assert respuesta["error"]["code"] == "PARAMETROS_INVALIDOS"
    finally:
        await servidor.aclose()
    assert stub.llamadas == []


async def test_chip_mal_formado_devuelve_parametros_invalidos():
    """CHIP que no cumple ^[A-Z0-9]{11}$ -> PARAMETROS_INVALIDOS."""
    servidor, stub = _servidor_con_fuentes_trampa()
    try:
        for chip in CHIPS_INVALIDOS:
            respuesta = await servidor.get_feasibility_report(chip=chip)
            assert respuesta["error"]["code"] == "PARAMETROS_INVALIDOS", chip
            assert "11 caracteres" in respuesta["error"]["message"], chip
    finally:
        await servidor.aclose()
    assert stub.llamadas == []


async def test_coordenadas_fuera_de_rango_devuelven_parametros_invalidos():
    """lat fuera de [-90,90] o lon fuera de [-180,180] -> PARAMETROS_INVALIDOS."""
    servidor, stub = _servidor_con_fuentes_trampa()
    try:
        casos = [
            {"lat": 91, "lon": -74.08},
            {"lat": -91, "lon": -74.08},
            {"lat": 4.6, "lon": 181},
            {"lat": 4.6, "lon": -181},
        ]
        for coordenadas in casos:
            respuesta = await servidor.get_feasibility_report(coordenadas=coordenadas)
            assert respuesta["error"]["code"] == "PARAMETROS_INVALIDOS", coordenadas
    finally:
        await servidor.aclose()
    assert stub.llamadas == []


async def test_coordenadas_sin_lat_o_sin_lon_devuelven_parametros_invalidos():
    """coordenadas incompletas (falta lat o lon) -> PARAMETROS_INVALIDOS."""
    servidor, stub = _servidor_con_fuentes_trampa()
    try:
        for coordenadas in [{"lat": 4.6}, {"lon": -74.08}, {}]:
            respuesta = await servidor.get_feasibility_report(coordenadas=coordenadas)
            assert respuesta["error"]["code"] == "PARAMETROS_INVALIDOS", coordenadas
    finally:
        await servidor.aclose()
    assert stub.llamadas == []


async def test_consulta_mayor_a_500_devuelve_parametros_invalidos():
    """consulta de mas de 500 caracteres -> PARAMETROS_INVALIDOS."""
    servidor, stub = _servidor_con_fuentes_trampa()
    try:
        respuesta = await servidor.get_feasibility_report(chip=CHIP_VALIDO, consulta="x" * 501)
    finally:
        await servidor.aclose()

    assert respuesta["error"]["code"] == "PARAMETROS_INVALIDOS"
    assert stub.llamadas == []


async def test_top_k_fuera_de_rango_devuelve_parametros_invalidos():
    """top_k fuera de 1-6 -> PARAMETROS_INVALIDOS."""
    servidor, stub = _servidor_con_fuentes_trampa()
    try:
        respuesta = await servidor.get_feasibility_report(chip=CHIP_VALIDO, top_k=0)
        assert respuesta["error"]["code"] == "PARAMETROS_INVALIDOS"

        respuesta = await servidor.get_feasibility_report(chip=CHIP_VALIDO, top_k=7)
        assert respuesta["error"]["code"] == "PARAMETROS_INVALIDOS"
    finally:
        await servidor.aclose()
    assert stub.llamadas == []


async def test_direccion_vacia_devuelve_parametros_invalidos():
    """direccion en blanco/espacios -> PARAMETROS_INVALIDOS sin llamar fuentes (contrato:51-53)."""
    servidor, stub = _servidor_con_fuentes_trampa()
    try:
        for direccion in DIRECCIONES_VACIAS:
            respuesta = await servidor.get_feasibility_report(direccion=direccion)
            assert respuesta["error"]["code"] == "PARAMETROS_INVALIDOS", repr(direccion)
    finally:
        await servidor.aclose()
    assert stub.llamadas == []


async def test_consulta_vacia_devuelve_parametros_invalidos():
    """consulta en blanco/espacios -> PARAMETROS_INVALIDOS sin llamar fuentes (contrato:67-70)."""
    servidor, stub = _servidor_con_fuentes_trampa()
    try:
        for consulta in CONSULTAS_VACIAS:
            respuesta = await servidor.get_feasibility_report(chip=CHIP_VALIDO, consulta=consulta)
            assert respuesta["error"]["code"] == "PARAMETROS_INVALIDOS", repr(consulta)
    finally:
        await servidor.aclose()
    assert stub.llamadas == []


async def test_consulta_de_exactamente_500_caracteres_es_valida():
    """consulta en el limite superior (500 chars) -> valida, el reporte fluye (contrato:69)."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        respuesta = await servidor.get_feasibility_report(chip=CHIP_VALIDO, consulta="x" * 500)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    assert "feasibility_score" in respuesta


async def test_direccion_de_exactamente_200_caracteres_es_valida():
    """direccion en el limite superior (200 chars) -> valida, el reporte fluye (contrato:53)."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    try:
        respuesta = await servidor.get_feasibility_report(direccion="A" * 200)
    finally:
        await servidor.aclose()

    assert "error" not in respuesta
    assert "feasibility_score" in respuesta
