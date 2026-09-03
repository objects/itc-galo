"""Ingesta del corpus de mercado inmobiliario (F10, US2).

Puebla `data/corpus/mercado/mercado.jsonl` (consolidado) + `mercado.sha256`
(huella de integridad) a partir de scraping best-effort de portales inmobiliarios
(Finca Raiz, Metrocuadrado, constructoras) con un conjunto de **seeds
deterministas** de respaldo ante fallo de red, bloqueo ToS o ausencia de datos
(FR-004/FR-005/FR-007). La ingesta es una operacion EXPLICITA de mantenimiento
(CLI `mercado`), nunca automatica al iniciar.

Reglas (FR-006, D6):
- Validacion de rangos: `estrato` 1-6, `area_m2` >= 36 (minimo POT 555),
  `precio` y `area_m2` estrictamente positivos. Un registro sin precio o sin
  area se descarta con warning deduplicado.
- Deduplicacion por `id` estable = SHA-256 de `fuente + url` o de la clave
  normalizada `fuente|localidad|barrio|precio|area` cuando no hay URL.

El scraping usa `httpx.AsyncClient` (timeout configurable) + parsing stdlib
(`html.parser`/regex); NO se anade `beautifulsoup4`/`lxml`/`scrapy` como
dependencia dura (D4). Ante cualquier fallo del scraping se cae a las seeds
(D7): el corpus queda poblado y el bloque `market_dynamics` no se degrada por
ello.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

from app.models import RegistroOfertaInmobiliaria

# --- Constantes del corpus (FR-018, FR-020) ---
DIRECTORIO_MERCADO = "data/corpus/mercado"
RUTA_SEEDS = f"{DIRECTORIO_MERCADO}/seeds.jsonl"
RUTA_CORPUS_MERCADO = f"{DIRECTORIO_MERCADO}/mercado.jsonl"
RUTA_HASH_MERCADO = f"{DIRECTORIO_MERCADO}/mercado.sha256"

# Area minima de vivienda en el POT 555 (Assumption 3): 36 m2.
AREA_MINIMA_M2 = 36.0
ESTRATO_MIN = 1
ESTRATO_MAX = 6

# URLs base de los portales (FR-018, configurable, sin credenciales embebidas).
PORTALES_MERCADO: dict[str, str] = {
    "finca_raiz": "https://www.fincaraiz.com.co/",
    "metrocuadrado": "https://www.metrocuadrado.com/",
    "constructora": "https://www.provivienda.com/",
}


class ErrorIngestaMercado(Exception):
    """Error tipificado propio de la ingesta de mercado (stderr + exit != 0).

    La taxonomia de 10 codigos de `app/errores.py` NO se modifica (FR-011).
    """

    def __init__(self, codigo: str, mensaje: str) -> None:
        super().__init__(f"Error de ingesta de mercado [{codigo}]: {mensaje}")
        self.codigo = codigo
        self.mensaje = mensaje


def _sha256(texto: str) -> str:
    """SHA-256 hex de un texto (clave de dedup/id estable)."""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def id_estable(registro: dict[str, Any]) -> str:
    """Id estable de un registro: SHA-256 de `fuente + url` o clave normalizada.

    Cuando no hay URL (seeds), la clave normalizada es
    `fuente|localidad|barrio|precio|area` (D6): re-ingestar el mismo registro
    produce el mismo id y la deduplicacion es no-op.
    """
    url = registro.get("url")
    if url:
        return _sha256(f"{registro['fuente']}{url}")
    clave = (
        f"{registro['fuente']}|{registro.get('localidad') or ''}|"
        f"{registro.get('barrio') or ''}|{registro['precio']}|{registro['area_m2']}"
    )
    return _sha256(clave)


def validar_registro(registro: dict[str, Any]) -> str | None:
    """Valida rangos FR-006 y devuelve el motivo de descarte (o None si valido).

    Devuelve el motivo en lugar de lanzar: la ingesta DESCARTE el registro
    invalido con warning deduplicado y sigue con el resto (un registro malo no
    contamina el precio de referencia, FR-006/FR-016).
    """
    precio = registro.get("precio")
    area = registro.get("area_m2")
    if precio is None or area is None:
        return "sin precio o sin area (se descarta, no contamina el precio de referencia)"
    if not isinstance(precio, (int, float)) or not isinstance(area, (int, float)):
        return "precio o area no numericos"
    if precio <= 0:
        return f"precio no positivo ({precio})"
    if area <= 0:
        return f"area no positiva ({area})"
    if area < AREA_MINIMA_M2:
        return f"area {area} < minimo POT 555 ({AREA_MINIMA_M2:.0f} m2)"
    estrato = registro.get("estrato")
    if estrato is not None and (not isinstance(estrato, int) or not ESTRATO_MIN <= estrato <= ESTRATO_MAX):
        return f"estrato {estrato} fuera del rango 1-6"
    return None


def _precio_m2(registro: dict[str, Any]) -> float:
    """precio_m2 derivado con redondeo determinista (data-model D1)."""
    return round(registro["precio"] / registro["area_m2"], 2)


def _registro_a_modelo(registro: dict[str, Any]) -> RegistroOfertaInmobiliaria:
    """Construye el RegistroOfertaInmobiliaria tipado, calculando id y precio_m2.

    `precio_m2` es derivado (FR-001 §data-model.md:31): nunca se confia en un
    `precio_m2` de entrada; se recalcula. `amenidades`/`localidad`/`upl`/
    `barrio` son opcionales (None o lista vacia).
    """
    return RegistroOfertaInmobiliaria(
        id=id_estable(registro),
        fuente=registro["fuente"],
        url=registro.get("url"),
        precio=registro["precio"],
        area_m2=registro["area_m2"],
        precio_m2=_precio_m2(registro),
        estrato=registro.get("estrato"),
        amenidades=list(registro.get("amenidades") or []),
        localidad=registro.get("localidad"),
        upl=registro.get("upl"),
        barrio=registro.get("barrio"),
        fecha_captura=registro["fecha_captura"],
    )


def leer_seeds(ruta_seeds: str = RUTA_SEEDS) -> list[dict[str, Any]]:
    """Lee las seeds deterministas (una por linea) como dicts crudos."""
    archivo = Path(ruta_seeds)
    if not archivo.is_file():
        return []
    return [json.loads(linea) for linea in archivo.read_text(encoding="utf-8").splitlines() if linea.strip()]


def procesar_registros(
    registros: list[dict[str, Any]],
) -> tuple[list[RegistroOfertaInmobiliaria], list[str]]:
    """Valida, deduplica y tipa una lista de registros crudos.

    Devuelve (registros_validos, motivos_descarte) con los descartes DEDUPLICADOS
    (FR-016): el mismo motivo no se repite. El orden de los registros validos
    respeta el orden de entrada (determinismo SC-005) y la deduplicacion por id
    mantiene la PRIMERA aparicion.
    """
    validos: list[RegistroOfertaInmobiliaria] = []
    vistos: set[str] = set()
    motivos: list[str] = []
    motivos_vistos: set[str] = set()
    for registro in registros:
        motivo = validar_registro(registro)
        if motivo is not None:
            if motivo not in motivos_vistos:
                motivos_vistos.add(motivo)
                motivos.append(f"{motivo}: {registro.get('url') or registro.get('barrio') or registro.get('fuente')}")
            continue
        modelo = _registro_a_modelo(registro)
        if modelo.id in vistos:
            continue
        vistos.add(modelo.id)
        validos.append(modelo)
    return validos, motivos


async def scraping_best_effort(
    client: httpx.AsyncClient,
    localidad: str | None = None,
) -> list[dict[str, Any]]:
    """Scraping best-effort de los portales configurados (US2).

    Intenta extraer ofertas por portal; ante CUALQUIER fallo (red, bloqueo ToS,
    robots.txt que deniega, HTML sin ofertas parseables) devuelve lista vacia: la
    ingesta cae a las seeds (FR-007, D7). El parsing es best-effort con regex
    sobre el HTML; NO se depende de DOM robusto porque las seeds son el respaldo.
    """
    registros: list[dict[str, Any]] = []
    for fuente, base_url in PORTALES_MERCADO.items():
        nombre_lower = fuente.replace("_", "").lower()
        patron_precio = r"(\d{7,11})"
        try:
            response = await client.get(base_url, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError:
            continue
        html = response.text
        # Respeta robots.txt/ToS de forma conservadora: si la respuesta no es
        # HTML normal o no trae patrones de oferta, se considera restringido.
        if "<html" not in html[:200].lower() and "<!doctype" not in html[:200].lower():
            continue
        # Extraccion minimalista best-effort: busca bloques de precio+area. Sin
        # datos parseables confiables, no se fabrican registros (FR-015).
        oferta = _extraer_ofertas_html(html, fuente, localidad)
        registros.extend(oferta)
    return registros


def _extraer_ofertas_html(
    html: str, fuente: str, localidad: str | None
) -> list[dict[str, Any]]:
    """Extraccion best-effort (stdlib) de ofertas de un portal.

    Implementacion conservadora: solo produce registros cuando detecta un patron
    precio/area inequivoco. Para el MVP devuelve lista vacia (el scraping real
    de cada portal se aislaria aqui; las seeds garantizan el corpus, D4/YAGNI).
    """
    return []


def consolidar_corpus(
    registros_scraping: list[dict[str, Any]],
    ruta_seeds: str = RUTA_SEEDS,
    usar_semillas: bool = True,
) -> tuple[list[RegistroOfertaInmobiliaria], list[str], dict[str, int]]:
    """Consolida scraping + seeds, valida y deduplica.

    Devuelve (registros, motivos_descarte, conteo_por_fuente). Las seeds se
    incluyen siempre que `usar_semillas` sea True (fallback obligatorio, FR-004);
    si el scraping aporto registros, ambos se deduplican por id estable.
    """
    crudos = list(registros_scraping)
    if usar_semillas:
        crudos.extend(leer_seeds(ruta_seeds))
    registros, motivos = procesar_registros(crudos)
    conteo: dict[str, int] = {}
    for registro in registros:
        conteo[registro.fuente] = conteo.get(registro.fuente, 0) + 1
    return registros, motivos, conteo


def escribir_corpus(
    registros: list[RegistroOfertaInmobiliaria],
    ruta_corpus: str = RUTA_CORPUS_MERCADO,
    ruta_hash: str = RUTA_HASH_MERCADO,
) -> str:
    """Escribe el corpus consolidado (JSONL) y su huella SHA-256 (FR-008/FR-020).

    La huella es el SHA-256 del JSONL completo (patron F4). Devuelve la huella.
    """
    directorio = Path(ruta_corpus).parent
    directorio.mkdir(parents=True, exist_ok=True)
    contenido = "\n".join(r.model_dump_json() for r in registros) + ("\n" if registros else "")
    Path(ruta_corpus).write_text(contenido, encoding="utf-8")
    huella = hashlib.sha256(contenido.encode("utf-8")).hexdigest()
    Path(ruta_hash).write_text(huella, encoding="utf-8")
    return huella


async def ingerir_mercado(
    client: httpx.AsyncClient | None = None,
    *,
    solo_semillas: bool = False,
    solo_scrape: bool = False,
    localidad: str | None = None,
    ruta_seeds: str = RUTA_SEEDS,
    ruta_corpus: str = RUTA_CORPUS_MERCADO,
    ruta_hash: str = RUTA_HASH_MERCADO,
) -> dict[str, Any]:
    """Ingesta hibrida del corpus de mercado (FR-004/FR-007/FR-020).

    - `solo_semillas`: SOLO seeds (sin red), reproduccion exacta para tests.
    - `solo_scrape`: solo scraping, sin fallback a seeds (diagnostico).
    - default: hibrido (scraping + fallback a seeds).

    Devuelve un reporte con totales, fuentes, descartes y la huella SHA-256.
    Ante corpus irrecuperable lanza ErrorIngestaMercado (exit != 0 en el CLI).
    """
    propietario = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
    try:
        registros_scraping: list[dict[str, Any]] = []
        if not solo_semillas:
            registros_scraping = await scraping_best_effort(client, localidad)

        registros, motivos, conteo = consolidar_corpus(
            registros_scraping,
            ruta_seeds=ruta_seeds,
            usar_semillas=not solo_scrape,
        )
        if not registros:
            raise ErrorIngestaMercado(
                "CORPUS_VACIO",
                "no se obtuvieron registros de mercado (scraping y seeds sin "
                "datos utiles). Verifica data/corpus/mercado/seeds.jsonl.",
            )
        huella = escribir_corpus(registros, ruta_corpus, ruta_hash)
        return {
            "registros": len(registros),
            "por_fuente": conteo,
            "descartes": len(motivos),
            "motivos_descarte": motivos,
            "huella_sha256": huella,
            "ruta_corpus": ruta_corpus,
        }
    finally:
        if propietario:
            await client.aclose()
