"""Contract tests Fase 5 — caché por lote con TTL (Parte B).

Verifica la caché en memoria LRU+TTL (`app/cache.py`) y su integración con
`ServidorLotes._resolver_lote_por_chip`:
- hit/miss: la segunda resolución del mismo CHIP NO vuelve a consultar Mapas
  Bogotá y devuelve el MISMO resultado (transparencia, SC-003).
- expiración: pasado el TTL (con reloj INYECTADO, sin esperas reales) vuelve a
  consultar la fuente.
- desactivación: `CACHE_TTL_SEGUNDOS=0` (o TTL<=0) deja la caché transparente
  OFF: cada consulta va a la fuente (comportamiento pre-Fase 5).
- LRU: se desaloja la entrada menos recientemente usada al superar el máximo.

Sin red real ni Ollama: mismos fixtures MockTransport de conftest.
"""

from __future__ import annotations

import httpx
import pytest

from app.cache import CacheLRUConTTL, construir_cache_por_defecto, ttl_segundos_de_entorno
from app.main import ServidorLotes
from app.providers.normativa import NormativaProvider
from app.providers.upl import UPLProvider
from tests.conftest import (
    CHIP_INEXISTENTE,
    CHIP_VALIDO,
    provider_arcgis_estandar,
    provider_mapas_estandar,
)


# --- Unitarios de CacheLRUConTTL ---


def test_cache_hit_y_miss():
    reloj = {"t": 0.0}
    cache = CacheLRUConTTL(ttl_segundos=60, reloj=lambda: reloj["t"])

    assert cache.obtener("a") is None  # miss inicial
    cache.guardar("a", {"valor": 1})
    assert cache.obtener("a") == {"valor": 1}  # hit


def test_cache_expira_con_ttl():
    reloj = {"t": 0.0}
    cache = CacheLRUConTTL(ttl_segundos=10, reloj=lambda: reloj["t"])
    cache.guardar("a", "v1")
    assert cache.obtener("a") == "v1"

    reloj["t"] = 9.999
    assert cache.obtener("a") == "v1"  # dentro del TTL

    reloj["t"] = 10.0
    assert cache.obtener("a") is None  # expirada y purgada
    assert len(cache) == 0


def test_cache_desactivada_con_ttl_cero():
    cache = CacheLRUConTTL(ttl_segundos=0)
    assert cache.activa is False
    cache.guardar("a", "v1")  # no-op
    assert cache.obtener("a") is None
    assert len(cache) == 0


def test_cache_desactivada_con_ttl_negativo():
    cache = CacheLRUConTTL(ttl_segundos=-5)
    assert cache.activa is False
    cache.guardar("a", "v1")
    assert cache.obtener("a") is None


def test_cache_lru_desaloja_la_menos_reciente():
    reloj = {"t": 0.0}
    cache = CacheLRUConTTL(tamano_maximo=2, ttl_segundos=100, reloj=lambda: reloj["t"])
    cache.guardar("a", 1)
    cache.guardar("b", 2)
    assert cache.obtener("a") == 1  # "a" pasa a ser la más reciente
    cache.guardar("c", 3)  # desaloja "b" (la menos recientemente usada)

    assert cache.obtener("b") is None
    assert cache.obtener("a") == 1
    assert cache.obtener("c") == 3


def test_ttl_segundos_de_entorno(monkeypatch):
    monkeypatch.delenv("CACHE_TTL_SEGUNDOS", raising=False)
    assert ttl_segundos_de_entorno() == 3600.0  # default

    monkeypatch.setenv("CACHE_TTL_SEGUNDOS", "0")
    assert ttl_segundos_de_entorno() == 0.0  # desactivada

    monkeypatch.setenv("CACHE_TTL_SEGUNDOS", "120")
    assert ttl_segundos_de_entorno() == 120.0

    monkeypatch.setenv("CACHE_TTL_SEGUNDOS", "   ")
    assert ttl_segundos_de_entorno() == 3600.0  # vacía -> default

    monkeypatch.setenv("CACHE_TTL_SEGUNDOS", "no-es-numero")
    assert ttl_segundos_de_entorno() == 3600.0  # inválida -> default


def test_construir_cache_por_defecto_lee_entorno(monkeypatch):
    monkeypatch.setenv("CACHE_TTL_SEGUNDOS", "30")
    cache = construir_cache_por_defecto()
    assert cache.activa is True

    monkeypatch.setenv("CACHE_TTL_SEGUNDOS", "0")
    assert construir_cache_por_defecto().activa is False


# --- Integración con ServidorLotes._resolver_lote_por_chip ---


def _servidor_con_contador(cache):
    """ServidorLotes estándar cuyo Mapas Bogotá registra cada búsqueda por CHIP."""
    mapas = provider_mapas_estandar()
    llamadas: list[str] = []
    original = mapas.buscar_por_chip

    async def contado(chip: str):
        llamadas.append(chip)
        return await original(chip)

    mapas.buscar_por_chip = contado  # type: ignore[method-assign]
    servidor = ServidorLotes(
        mapas,
        provider_arcgis_estandar(),
        UPLProvider(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"type": "FeatureCollection", "features": []})
            )
        ),
        NormativaProvider(),
        cache_lotes=cache,
    )
    return servidor, llamadas


@pytest.mark.asyncio
async def test_resolucion_chip_segunda_llamada_es_hit_de_cache():
    """Mismo CHIP dos veces: Mapas Bogotá se consulta UNA vez; resultado idéntico."""
    servidor, llamadas = _servidor_con_contador(CacheLRUConTTL(ttl_segundos=300))
    try:
        primera = await servidor.resolve_lot_by_chip(CHIP_VALIDO)
        segunda = await servidor.resolve_lot_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert llamadas == [CHIP_VALIDO]  # solo 1 consulta a la fuente
    assert segunda == primera  # transparencia total (SC-003)


@pytest.mark.asyncio
async def test_resolucion_chip_expirada_vuelve_a_consultar_fuente():
    """Pasado el TTL (reloj inyectado), la resolución vuelve a golpear la fuente."""
    reloj = {"t": 0.0}
    servidor, llamadas = _servidor_con_contador(
        CacheLRUConTTL(ttl_segundos=10, reloj=lambda: reloj["t"])
    )
    try:
        await servidor.resolve_lot_by_chip(CHIP_VALIDO)
        reloj["t"] = 11.0
        await servidor.resolve_lot_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert llamadas == [CHIP_VALIDO, CHIP_VALIDO]  # miss tras expirar


@pytest.mark.asyncio
async def test_resolucion_chip_con_cache_desactivada_no_cachea():
    """TTL=0: cada llamada consulta la fuente (comportamiento pre-Fase 5)."""
    servidor, llamadas = _servidor_con_contador(CacheLRUConTTL(ttl_segundos=0))
    try:
        await servidor.resolve_lot_by_chip(CHIP_VALIDO)
        await servidor.resolve_lot_by_chip(CHIP_VALIDO)
    finally:
        await servidor.aclose()

    assert llamadas == [CHIP_VALIDO, CHIP_VALIDO]


@pytest.mark.asyncio
async def test_cache_no_guarda_errores_ni_no_encontrado():
    """Solo resultados EXITOSOS se cachean: errores y 'no encontrado' nunca."""
    servidor, llamadas = _servidor_con_contador(CacheLRUConTTL(ttl_segundos=300))
    try:
        fallo_1 = await servidor.resolve_lot_by_chip(CHIP_INEXISTENTE)
        fallo_2 = await servidor.resolve_lot_by_chip(CHIP_INEXISTENTE)
        assert fallo_1 == fallo_2  # misma respuesta de error
        # "No encontrado" NUNCA se cachea: ambas llamadas fueron a la fuente.
        assert llamadas == [CHIP_INEXISTENTE, CHIP_INEXISTENTE]

        # Un error tipado de fuente tampoco se cachea: provider que responde 500.
        mapas_error = provider_mapas_estandar()
        contador_500: list[str] = []
        original_error = mapas_error.buscar_por_chip

        async def contado_error(chip: str):
            contador_500.append(chip)
            return await original_error(chip)

        mapas_error.buscar_por_chip = contado_error  # type: ignore[method-assign]
        servidor_error = ServidorLotes(
            mapas_error,
            provider_arcgis_estandar(lotes=[]),
            UPLProvider(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(200, json={"type": "FeatureCollection", "features": []})
                )
            ),
            NormativaProvider(),
            cache_lotes=CacheLRUConTTL(ttl_segundos=300),
        )
        # CHIP válido en Mapas Bogotá pero punto sin lote en ArcGIS -> error;
        # repetir NO debe servir un resultado cacheado.
        error_1 = await servidor_error.resolve_lot_by_chip(CHIP_VALIDO)
        error_2 = await servidor_error.resolve_lot_by_chip(CHIP_VALIDO)
        assert error_1 == error_2
        assert contador_500 == [CHIP_VALIDO, CHIP_VALIDO]
        await servidor_error.aclose()
    finally:
        await servidor.aclose()
