"""Provider del corpus de mercado inmobiliario (F10, motor de mercado).

Lee el corpus local versionado (`data/corpus/mercado/mercado.jsonl`) y produce el
`ContextoMercado` del bloque `market_dynamics`: precio de referencia (mediana del
m²), estrato, oferta competidora (clustering determinista por estrato+zona) y
ritmo de absorción (heurística). La fuente primaria es única (el corpus local),
así que el bloque NO publica `source_traces` (FR-010).

El scraping de portales y la escritura del corpus viven en `app/ingesta/mercado.py`
(Principio II: la ingesta es la frontera de poblado; este provider es la frontera
de lectura/consulta). El provider es 100 % determinista (SC-001/SC-005): misma
entrada -> mismo `ContextoMercado`, sin LLM ni reloj (la vigencia es la huella
del corpus, congelada en disco).

Manejo de errores (FR-003, SC-003): un corpus vacío, ilegible o sin registros
para la zona retorna `(None, SourceTrace)`; el orquestador lo degrada a
`no_encontrado` + warning `BLOQUE_SIN_DATO`. Nunca se lanza un error tipado de
fuente (la lectura es local, D7).
"""

from __future__ import annotations

import hashlib
import statistics
from pathlib import Path

import httpx

from app.models import (
    ContextoMercado,
    OfertaCompetidora,
    RegistroOfertaInmobiliaria,
    RitmoAbsorcion,
    SourceTrace,
)
from app.utilidades import ahora_iso as _ahora_iso

# --- Constantes del corpus de mercado (FR-018, FR-020) ---
CORPUS_MERCADO_DIR = "data/corpus/mercado"
CORPUS_MERCADO_JSONL = f"{CORPUS_MERCADO_DIR}/mercado.jsonl"
CORPUS_MERCADO_HASH = f"{CORPUS_MERCADO_DIR}/mercado.sha256"

# Identidad canonica del source_trace (contracts/market-dynamics.md:1.3).
CORPUS_MERCADO_SOURCE_NAME = "corpus-mercado"
CORPUS_MERCADO_LAYER_ID = "mercado"
CORPUS_MERCADO_SERVICE_URL = "data/corpus/mercado/mercado.jsonl"


def _huella_corpus(ruta_corpus: str) -> str | None:
    """SHA-256 del corpus en disco o None si no existe (congelado, sin reloj)."""
    archivo = Path(ruta_corpus)
    if not archivo.is_file():
        return None
    return hashlib.sha256(archivo.read_bytes()).hexdigest()


def _leer_registros(ruta_corpus: str) -> list[RegistroOfertaInmobiliaria]:
    """Lee el corpus y valida cada linea como RegistroOfertaInmobiliaria.

    Un corpus ilegible (linea corrupta o JSON invalido) aborta con ValueError:
    el llamador lo degrada a `no_encontrado` (fail-fast local, FR-003).
    """
    archivo = Path(ruta_corpus)
    if not archivo.is_file():
        return []
    registros: list[RegistroOfertaInmobiliaria] = []
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        registros.append(RegistroOfertaInmobiliaria.model_validate_json(linea))
    return registros


def _clave_zona(registro: RegistroOfertaInmobiliaria) -> str | None:
    """Zona de un registro: localidad o UPL (la primera presente)."""
    return registro.localidad or registro.upl


def _filtro_por_zona(
    registros: list[RegistroOfertaInmobiliaria],
    localidad: str | None,
    upl: str | None,
) -> list[RegistroOfertaInmobiliaria]:
    """Registros comparables para la zona del lote (D8).

    La comparacion es insensible a tildes/caso por localidad; por UPL se exige
    coincidencia exacta del codigo. Sin zona de entrada no hay filtro utilizable
    -> lista vacia (nunca se inventa un precio de otra zona, FR-015).
    """
    if localidad is None and upl is None:
        return []
    resultado: list[RegistroOfertaInmobiliaria] = []
    for registro in registros:
        zona = _clave_zona(registro)
        if zona is None:
            continue
        if upl is not None and registro.upl == upl:
            resultado.append(registro)
            continue
        if localidad is not None and _clave_sin_tildes_local(zona) == _clave_sin_tildes_local(localidad):
            resultado.append(registro)
    return resultado


def _clave_sin_tildes_local(texto: str) -> str:
    """Normaliza a minusculas sin tildes (comparacion de localidad determinista)."""
    import unicodedata

    normalizado = unicodedata.normalize("NFD", texto)
    return "".join(c for c in normalizado if unicodedata.category(c) != "Mn").lower()


def _mediana(valores: list[float]) -> float | None:
    """Mediana de una lista no vacia (precio de referencia, data-model D8)."""
    if not valores:
        return None
    return statistics.median(valores)


def _clusters_de_oferta(
    registros: list[RegistroOfertaInmobiliaria],
) -> list[OfertaCompetidora]:
    """Agregacion determinista por (estrato, zona) (D2), orden estable.

    Cada cluster reporta `conteo` y `precio_m2_promedio` (media del m²); el
    orden de salida esta fijado por (zona normalizada, estrato) para garantizar
    el determinismo (SC-001).
    """
    agrupados: dict[tuple[str, int | None], list[float]] = {}
    orden: dict[tuple[str, int | None], tuple[str, int | None]] = {}
    for registro in registros:
        zona = _clave_zona(registro) or "sin zona"
        clave = (zona, registro.estrato)
        agrupados.setdefault(clave, []).append(registro.precio_m2)
        orden.setdefault(clave, (zona, registro.estrato))
    clusters: list[OfertaCompetidora] = []
    for clave in sorted(orden, key=lambda c: (_clave_sin_tildes_local(orden[c][0]), orden[c][1] if orden[c][1] is not None else 99)):
        zona, estrato = orden[clave]
        valores = agrupados[clave]
        media = sum(valores) / len(valores) if valores else None
        clusters.append(
            OfertaCompetidora(
                zona=zona,
                conteo=len(valores),
                precio_m2_promedio=media,
                estrato=estrato,
            )
        )
    return clusters


def _estrato_de_zona(registros: list[RegistroOfertaInmobiliaria]) -> int | None:
    """Estrato mas frecuente entre los registros comparables (None si no hay)."""
    conteos: dict[int, int] = {}
    for registro in registros:
        if registro.estrato is None:
            continue
        conteos[registro.estrato] = conteos.get(registro.estrato, 0) + 1
    if not conteos:
        return None
    return max(conteos, key=lambda e: (conteos[e], -e))


def _ritmo_absorcion(
    registros: list[RegistroOfertaInmobiliaria],
) -> RitmoAbsorcion | None:
    """Ritmo de absorcion heuristico por antiguedad de ofertas (D3).

    Aproximacion determinista: `unidades_mes` = volumen de ofertas comparable
    repartido sobre el numero de meses distintos de captura presentes en el
    corpus. Si no hay fechas de captura, el campo queda None (nunca se infiere,
    FR-015). `criterio` documenta la formula.
    """
    fechas: list[str] = [r.fecha_captura for r in registros if r.fecha_captura]
    if not fechas:
        return None
    criterio = "antigüedad media de ofertas comparables del corpus"
    meses_distintos = len({f[:7] for f in fechas}) or 1
    unidades_mes = len(registros) / meses_distintos
    return RitmoAbsorcion(unidades_mes=round(unidades_mes, 2), criterio=criterio)


class MercadoProvider:
    """Cliente de lectura del corpus de mercado (Principio II).

    El `httpx.AsyncClient` se mantiene por consistencia con el resto de los
    providers (FR-017) aunque la consulta principal es local al corpus; el
    timeout es configurable y expone `aclose()` para el ciclo de vida.
    """

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
        ruta_corpus: str = CORPUS_MERCADO_JSONL,
    ) -> None:
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout)
        self._ruta_corpus = ruta_corpus

    async def aclose(self) -> None:
        """Cierra el cliente httpx subyacente."""
        await self._client.aclose()

    async def consultar_market_dynamics(
        self, localidad: str | None, upl: str | None
    ) -> tuple[ContextoMercado | None, SourceTrace]:
        """Contexto de mercado de la zona del lote (localidad/UPL) desde el corpus.

        Retorna `(None, source_trace)` cuando el corpus esta vacio, es ilegible o
        no tiene registros para la zona (D7/D8): es una ausencia real, no un
        fallo. `source_trace` documenta la consulta al corpus con su huella como
        `data_vigencia` (congelada, SC-001). La lectura es local: sin red en el
        camino principal (SC-006).
        """
        huella = _huella_corpus(self._ruta_corpus)
        trace = SourceTrace(
            source_name=CORPUS_MERCADO_SOURCE_NAME,
            layer_id=CORPUS_MERCADO_LAYER_ID,
            service_url=CORPUS_MERCADO_SERVICE_URL,
            data_vigencia=huella or "corpus-vacio",
            query_timestamp=_ahora_iso(),
        )

        registros = _leer_registros(self._ruta_corpus)
        comparables = _filtro_por_zona(registros, localidad, upl)
        if not comparables:
            return None, trace

        precios = [r.precio_m2 for r in comparables]
        contexto = ContextoMercado(
            precio_m2_referencia=_mediana(precios),
            estrato=_estrato_de_zona(comparables),
            oferta_competidora=_clusters_de_oferta(comparables),
            ritmo_absorcion=_ritmo_absorcion(comparables),
        )
        return contexto, trace
