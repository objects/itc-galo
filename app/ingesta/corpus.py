"""Parseo del corpus normativo del Decreto 555/2021 (sisjur) en articulos tipados.

El HTML descargado de sisjur se convierte en una lista de `ArticuloNormativo`
con el texto literal de cada articulo (FR-003) y su ubicacion en el documento:
libro, parte derivada y referencias (UPLs mencionadas y articulos derogados).
Esta capa produce el corpus versionado en git y los chunks del indice vectorial.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import chromadb
import httpx
from chromadb.errors import NotFoundError
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

from app.errores import CorpusNoIngestadoError, OllamaNoDisponibleError
from app.models import (
    ArticuloNormativo,
    Chunk,
    COLECCION_NORMATIVA,
    CorpusInfo,
    METADATA_CORPUS_SHA256,
    METADATA_EMBEDDING_MODEL,
)

# Alternativas de numeral romano de mayor a menor longitud: sin ese orden el
# motor de regex elegiria "I" dentro de "II"/"III"/"IV" y el libro se perderia.
LIBRO_PATRON = re.compile(r"LIBRO\s+(VIII|VII|VI|V|IV|III|II|I)\b")
ARTICULO_PATRON = re.compile(r"ARTÍCULO\s+(\d+)")
UPL_PATRON = re.compile(r"UPL\d{2}")
ARTICULO_DEROGADO_PATRON = re.compile(
    r"deroga[ra]?\s+(?:el\s+)?art[ií]culo\s+(\d+)", re.IGNORECASE
)

PARTE_POR_LIBRO = {"II": "general", "III": "urbano", "IV": "rural"}


def parsear_articulos(html: str) -> list[ArticuloNormativo]:
    """Parsea el HTML del Decreto 555/2021 de sisjur en articulos tipados.

    Reglas de extraccion:
    - Cada "ARTÍCULO N." abre un articulo: su titulo es el resto de la linea del
      encabezado (sin punto final) y su texto llega hasta el siguiente "ARTÍCULO".
    - El libro vigente es el último "LIBRO <numeral>" anterior al articulo ("I"
      si no hay ninguno); la parte se deriva del libro (II general, III urbano,
      IV rural; el resto sin parte).
    - Las UPLs mencionadas y los articulos derogados se extraen del texto con
      regex y se deduplican.

    Fail fast: sin ningún "ARTÍCULO" el HTML no es el documento esperado y se
    lanza ValueError con mensaje accionable.
    """
    partidos = list(ARTICULO_PATRON.finditer(html))
    if not partidos:
        raise ValueError(
            "No se encontró ningún 'ARTÍCULO' en el HTML del Decreto 555/2021. "
            "Verifica que la fuente de sisjur devuelva el documento completo."
        )

    libros = list(LIBRO_PATRON.finditer(html))
    articulos: list[ArticuloNormativo] = []

    for indice, partido in enumerate(partidos):
        numero = int(partido.group(1))

        libro_vigente = next(
            (m.group(1) for m in reversed(libros) if m.start() < partido.start()),
            "I",
        )

        fin_encabezado = html.find("\n", partido.end())
        linea_titulo = (
            html[partido.end():fin_encabezado]
            if fin_encabezado != -1
            else html[partido.end():]
        )
        titulo = linea_titulo.strip(" \t\r.")

        inicio_cuerpo = fin_encabezado + 1 if fin_encabezado != -1 else len(html)
        fin_cuerpo = (
            partidos[indice + 1].start() if indice + 1 < len(partidos) else len(html)
        )
        texto = re.sub(r"\n{2,}", "\n", html[inicio_cuerpo:fin_cuerpo]).strip()

        upls_mencionadas = list(dict.fromkeys(UPL_PATRON.findall(texto)))
        articulos_derogados = [int(n) for n in ARTICULO_DEROGADO_PATRON.findall(texto)]

        articulos.append(
            ArticuloNormativo(
                numero=numero,
                titulo=titulo,
                texto=texto,
                libro=libro_vigente,
                parte=PARTE_POR_LIBRO.get(libro_vigente),
                upls_mencionadas=upls_mencionadas,
                articulos_derogados=articulos_derogados,
            )
        )

    return articulos


def _construir_chunk(
    articulo: ArticuloNormativo, id_chunk: str, parrafos: list[str]
) -> Chunk:
    """Crea un Chunk con el texto unido y los metadatos heredados del articulo."""

    return Chunk(
        id=id_chunk,
        articulo=articulo.numero,
        titulo=articulo.titulo,
        libro=articulo.libro,
        parte=articulo.parte,
        seccion=articulo.seccion,
        texto="\n".join(parrafos),
    )


def chunk_articulo(articulo: ArticuloNormativo) -> list[Chunk]:
    """Parte un articulo en chunks indexables (data-model.md:128-143).

    Regla base: 1 chunk = 1 articulo con id `art-<numero>` y texto completo. Si
    el texto supera los 3000 caracteres se parte por parrafos (\\n) con solape
    de 1 parrafo: cada bloque siguiente empieza repitiendo el ultimo parrafo del
    bloque anterior como primer parrafo, y sus ids son `art-<numero>-<i>`. Cada
    chunk hereda los metadatos del articulo (articulo, titulo, libro, parte,
    seccion). Devuelve siempre al menos un chunk: texto vacio produce un chunk
    con texto "".
    """
    id_base = f"art-{articulo.numero:03d}"
    if len(articulo.texto) <= 3000:
        return [_construir_chunk(articulo, id_base, [articulo.texto])]

    parrafos = articulo.texto.split("\n")
    bloques: list[list[str]] = [[parrafos[0]]]

    for parrafo in parrafos[1:]:
        bloque_con_parrafo = [*bloques[-1], parrafo]
        if len("\n".join(bloque_con_parrafo)) <= 3000:
            bloques[-1] = bloque_con_parrafo
        else:
            bloques.append([bloques[-1][-1], parrafo])

    return [
        _construir_chunk(
            articulo,
            id_base if indice == 0 else f"{id_base}-{indice}",
            bloque,
        )
        for indice, bloque in enumerate(bloques)
    ]


def hash_documento(corpus: list[ArticuloNormativo]) -> str:
    """SHA-256 del corpus como JSON canonico (FR-009).

    La huella se calcula sobre la representacion canonica del corpus: cada
    articulo serializado con `model_dump()` (valores planos), JSON con claves
    ordenadas y UTF-8. Corpus iguales producen siempre la misma huella, lo que
    permite verificar integridad y actualidad del indice vectorial.
    """
    json_canonico = json.dumps(
        [articulo.model_dump() for articulo in corpus],
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(json_canonico).hexdigest()


def serializar_corpus(corpus: list[ArticuloNormativo], ruta: str) -> None:
    """Escribe el corpus como JSONL (una linea por articulo) en `ruta`.

    Crea el directorio padre si no existe. Cada linea es la serializacion
    `model_dump_json` del articulo con caracteres UTF-8 sin escapar.
    """
    archivo_path = Path(ruta)
    archivo_path.parent.mkdir(parents=True, exist_ok=True)
    with archivo_path.open("w", encoding="utf-8") as archivo:
        for articulo in corpus:
            archivo.write(articulo.model_dump_json(ensure_ascii=False) + "\n")


def deserializar_corpus(ruta: str) -> list[ArticuloNormativo]:
    """Lee el JSONL escrito por `serializar_corpus` y devuelve los articulos.

    Cada linea se valida como `ArticuloNormativo` con `model_validate_json`.
    """
    with Path(ruta).open("r", encoding="utf-8") as archivo:
        return [ArticuloNormativo.model_validate_json(linea) for linea in archivo]


def _modelo_embedding_env() -> str:
    """Nombre del modelo de embeddings del env var, normalizado para ChromaDB.

    ChromaDB exige ":" o "@" (tag o digest) en el nombre; si el env var no lo
    incluye, se añade ":latest". Una variable definida pero vacía (o solo con
    espacios) se trata como no definida y cae al default. Es el valor que recibe
    OllamaEmbeddingFunction y el que se persiste como huella del modelo en la
    metadata de la colección.
    """
    model_name = os.getenv("OLLAMA_EMBEDDING_MODEL", "bge-m3").strip()
    if not model_name:
        model_name = "bge-m3"
    if ":" not in model_name and "@" not in model_name:
        return f"{model_name}:latest"
    return model_name


def _etiqueta_embedding(embedding_function) -> str:
    """Identidad del modelo de embeddings efectivo para la metadata (FR-008).

    Usa el `model_name` de la EF (OllamaEmbeddingFunction) cuando lo expone; si
    no lo expone (p. ej. chromadb < 1.4, donde el atributo era `_model_name`),
    cae al env var actual normalizado para que un cambio de modelo siga
    detectándose. Dos modelos distintos generan etiquetas distintas y disparan
    la reconstrucción del índice.
    """
    return getattr(embedding_function, "model_name", None) or _modelo_embedding_env()


def indexar_corpus(
    corpus: list[ArticuloNormativo], ruta_indice: str, embedding_function=None
) -> CorpusInfo:
    """Indexa el corpus en ChromaDB y devuelve metadatos del corpus indexado.

    El índice siempre contiene EXACTAMENTE los chunks del corpus actual (FR-008):
    el hash SHA-256 del corpus y el modelo de embeddings efectivo se persisten en
    los metadatos de la colección (`corpus_sha256` y `embedding_model`) y se usan
    como criterio para distinguir los tres flujos: crear (colección inexistente),
    actualizar (mismo corpus y mismo modelo, `upsert` idempotente) y reconstruir
    (corpus distinto, modelo de embeddings distinto o índice legado sin la huella
    del modelo: se borra la colección y se re-indexa desde cero para no mezclar
    vectores de versiones previas ni de modelos distintos en el mismo HNSW).
    """
    if embedding_function is None:
        embedding_function = _crear_embedding_function()
    embedding_model = _etiqueta_embedding(embedding_function)

    hash_actual = hash_documento(corpus)
    metadata_indice = {
        "hnsw:space": "cosine",
        METADATA_CORPUS_SHA256: hash_actual,
        METADATA_EMBEDDING_MODEL: embedding_model,
    }

    Path(ruta_indice).parent.mkdir(parents=True, exist_ok=True)
    cliente = chromadb.PersistentClient(path=ruta_indice)

    try:
        coleccion = cliente.get_collection(
            name=COLECCION_NORMATIVA, embedding_function=embedding_function
        )
    except NotFoundError:
        coleccion = None

    if coleccion is None:
        # Primera indexación: crear la colección con hash y modelo de embeddings.
        coleccion = cliente.create_collection(
            name=COLECCION_NORMATIVA,
            embedding_function=embedding_function,
            metadata=metadata_indice,
        )
    else:
        metadata_coleccion = coleccion.metadata or {}
        hash_persistido = metadata_coleccion.get(METADATA_CORPUS_SHA256)

        motivo = None
        if hash_persistido != hash_actual:
            hash_previo = hash_persistido[:16] if hash_persistido else "desconocido"
            motivo = (
                f"Índice de otra versión del corpus (hash persistido {hash_previo}... "
                f"!= actual {hash_actual[:16]}...)"
            )
        elif METADATA_EMBEDDING_MODEL not in metadata_coleccion:
            motivo = (
                "Índice legado sin la huella del modelo de embeddings en sus "
                "metadatos (clave 'embedding_model' ausente)"
            )
        else:
            embedding_model_persistido = metadata_coleccion[METADATA_EMBEDDING_MODEL]
            if embedding_model_persistido != embedding_model:
                motivo = (
                    f"Índice con otro modelo de embeddings "
                    f"({embedding_model_persistido} != {embedding_model})"
                )

        if motivo is not None:
            # Re-indexación con otra versión del corpus o de los embeddings:
            # reconstruir desde cero para no mezclar vectores (FR-008).
            print(
                f"{motivo}. Reconstruyendo la colección desde cero para no mezclar "
                "vectores de corpus o modelos distintos."
            )
            cliente.delete_collection(COLECCION_NORMATIVA)
            coleccion = cliente.create_collection(
                name=COLECCION_NORMATIVA,
                embedding_function=embedding_function,
                metadata=metadata_indice,
            )

    chunks = [c for a in corpus for c in chunk_articulo(a)]

    # Mapa articulo -> upls_mencionadas para metadatos de chunks
    upls_por_articulo = {a.numero: a.upls_mencionadas for a in corpus}

    ids = []
    documents = []
    metadatas = []

    for chunk in chunks:
        if chunk.articulo not in upls_por_articulo:
            raise ValueError(
                f"Chunk con id '{chunk.id}' referencia articulo {chunk.articulo} "
                "que no existe en el corpus"
            )
        upls = upls_por_articulo[chunk.articulo]
        ids.append(chunk.id)
        documents.append(chunk.texto)
        metadatas.append(
            {
                "articulo": chunk.articulo,
                "titulo": chunk.titulo,
                "libro": chunk.libro,
                "parte": chunk.parte or "",
                "seccion": chunk.seccion or "",
                "upls": ",".join(upls),
            }
        )

    coleccion.upsert(ids=ids, documents=documents, metadatas=metadatas)

    return CorpusInfo(
        documento="Decreto 555 de 2021 (POT Bogotá)",
        vigencia="2021-12-30",
        hash_sha256=hash_actual,
        total_articulos=len(corpus),
    )


def consultar_corpus(
    ruta_indice: str,
    embedding_function,
    consulta: str,
    top_k: int = 5,
    umbral_similitud: float = 0.35,
    upl_filtro: str | None = None,
) -> list[tuple[Chunk, float]]:
    """Consulta el índice vectorial del corpus normativo.

    Busca chunks semánticamente similares a la consulta, con filtro opcional
    estricto por UPL (FR-002) usando $contains sobre string CSV "UPL17,UPL20".

    Args:
        ruta_indice: Ruta al directorio del índice ChromaDB.
        embedding_function: Función de embedding (misma usada en indexar_corpus).
        consulta: Texto de la consulta en lenguaje natural.
        top_k: Máximo número de resultados a retornar.
        umbral_similitud: Umbral mínimo de similitud coseno (0-1).
        upl_filtro: Código de UPL para filtrar (ej. "UPL17").

    Returns:
        Lista de tuplas (Chunk, similitud) ordenada por similitud descendente.

    Raises:
        ValueError: Si la colección no existe en la ruta indicada.
    """
    cliente = chromadb.PersistentClient(path=ruta_indice)

    try:
        coleccion = cliente.get_collection(
            name=COLECCION_NORMATIVA,
            embedding_function=embedding_function,
        )
    except Exception as e:
        raise ValueError(
            f"Índice no encontrado en {ruta_indice}. Ejecuta la ingesta primero."
        ) from e

    where = {"upls": {"$contains": upl_filtro}} if upl_filtro else None

    results = coleccion.query(
        query_texts=[consulta],
        n_results=top_k,
        where=where,
    )

    resultados: list[tuple[Chunk, float]] = []

    if not results["ids"] or not results["ids"][0]:
        return resultados

    for id_chunk, document, metadata, distance in zip(
        results["ids"][0],
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        similitud = 1.0 - distance

        if similitud < umbral_similitud:
            continue

        parte = metadata.get("parte")
        seccion = metadata.get("seccion")

        chunk = Chunk(
            id=id_chunk,
            articulo=metadata["articulo"],
            titulo=metadata["titulo"],
            libro=metadata["libro"],
            parte=parte if parte != "" else None,
            seccion=seccion if seccion != "" else None,
            texto=document,
        )

        resultados.append((chunk, similitud))

    resultados.sort(key=lambda x: x[1], reverse=True)

    return resultados


RUTA_CORPUS = "data/corpus/decreto_555_2021.jsonl"
RUTA_HASH = "data/corpus/decreto_555_2021.jsonl.sha256"
DEFAULT_URL = os.getenv("CORPUS_URL", "https://www.sisjur.gov.co/decreto-555-2021")
DEFAULT_INDICE = os.getenv("VECTOR_DB_PATH", ".data/chroma")


def _crear_embedding_function() -> OllamaEmbeddingFunction:
    """Crea la embedding function por defecto usando variables de entorno."""
    base_url = os.getenv("OLLAMA_BASE_URL", "http://192.168.40.91:11434")
    return OllamaEmbeddingFunction(
        model_name=_modelo_embedding_env(), url=f"{base_url}/api/embeddings"
    )


def _html_sintetico_demo() -> str:
    """HTML mínimo de demostración (modo --demo): nunca es el corpus real.

    Solo se usa cuando el llamador lo pide explícitamente (`demo=True`). El
    flujo normal jamás persiste ni indexa este contenido sintético.
    """
    return """\
LIBRO II
ARTÍCULO 1. Usos del suelo en UPL17.
El presente artículo regula los usos del suelo en la UPL17.

LIBRO III
ARTÍCULO 2. Normas urbanas UPL20.
Este artículo establece normas para la UPL20 y la UPL20.

LIBRO III
ARTÍCULO 3. Derogatoria.
La presente norma deroga el artículo 5 del Decreto 100 de 2000.
"""


def cmd_descargar(url: str, demo: bool = False) -> None:
    """Descarga HTML de sisjur, parsea, guarda JSONL + .sha256. NO indexa.

    Si la red falla y `demo` es True, usa HTML sintético de demostración para
    probar el pipeline. Fuera de modo demo, un fallo de red aborta (Fail Fast)
    sin escribir el corpus ni indexar nada.
    """
    try:
        response = httpx.get(url, timeout=30.0)
        response.raise_for_status()
        html = response.text
    except Exception as e:
        if not demo:
            raise RuntimeError(
                f"No se pudo descargar el Decreto 555/2021 desde {url}: {e}. "
                "Sin modo demo no se escribe ni indexa corpus sintético."
            ) from e
        print(f"⚠ Red no disponible ({e}). Usando HTML sintético de demo.")
        html = _html_sintetico_demo()

    corpus = parsear_articulos(html)
    if not corpus:
        raise CorpusNoIngestadoError(detalle="No se parseó ningún artículo del HTML")

    serializar_corpus(corpus, RUTA_CORPUS)
    hash_val = hash_documento(corpus)
    Path(RUTA_HASH).write_text(hash_val, encoding="utf-8")

    print(f"Artículos: {len(corpus)} | Hash: {hash_val} | Corpus: {RUTA_CORPUS}")


def _verificar_hash_corpus(corpus: list[ArticuloNormativo]) -> str:
    """Verifica que el corpus en disco coincida con el hash persistido (FR-009).

    Fail fast: si el JSONL y su `.sha256` no coinciden, indexar continuaría
    sobre un índice posiblemente mezclado (FR-008). La única salida correcta es
    abortar con un error accionable y regenerar corpus + hash con 'descargar'.
    """
    hash_actual = hash_documento(corpus)
    try:
        hash_guardado = Path(RUTA_HASH).read_text(encoding="utf-8").strip()
    except FileNotFoundError as e:
        raise CorpusNoIngestadoError(
            detalle=(
                f"No se encontró el hash persistido del corpus ({RUTA_HASH}). "
                "Ejecuta 'python -m app.ingesta.corpus descargar' antes de indexar."
            )
        ) from e
    if hash_actual != hash_guardado:
        raise CorpusNoIngestadoError(
            detalle=(
                f"El corpus ({RUTA_CORPUS}) no coincide con su hash persistido "
                f"({RUTA_HASH}): {hash_actual[:16]}... != {hash_guardado[:16]}.... "
                "Regenera corpus y hash con 'python -m app.ingesta.corpus descargar'."
            )
        )
    return hash_actual


def cmd_indexar(ruta_indice: str) -> None:
    """Lee JSONL versionado, indexa en ChromaDB.

    Antes de indexar se verifica el hash del corpus en disco contra el persistido
    (Fail Fast): un mismatch aborta en lugar de continuar con un índice mezclado.
    """
    corpus = deserializar_corpus(RUTA_CORPUS)
    _verificar_hash_corpus(corpus)

    try:
        ef = _crear_embedding_function()
        info = indexar_corpus(corpus, ruta_indice, ef)
    except (httpx.RequestError, ConnectionError, TimeoutError) as e:
        modelo = os.getenv("OLLAMA_EMBEDDING_MODEL", "bge-m3")
        print(
            f"⚠ Ollama no disponible: {e}. "
            f"Verifica 'ollama serve' y ejecuta 'ollama pull {modelo}'"
        )
        raise OllamaNoDisponibleError(modelo=modelo) from e

    print(
        f"Indexados: {info.total_articulos} chunks | "
        f"Artículos: {len(corpus)} | Hash: {info.hash_sha256} | Índice: {ruta_indice}"
    )


def cmd_full(url: str, ruta_indice: str, demo: bool = False) -> None:
    """Ejecuta descargar + indexar (pipeline completo)."""
    cmd_descargar(url, demo)
    cmd_indexar(ruta_indice)


def cmd_consultar(
    consulta: str,
    top_k: int,
    umbral: float,
    upl_filtro: str | None,
    ruta_indice: str,
) -> None:
    """Consulta el índice vectorial."""
    ef = _crear_embedding_function()
    resultados = consultar_corpus(ruta_indice, ef, consulta, top_k, umbral, upl_filtro)

    if not resultados:
        print(f"Sin resultados por encima del umbral {umbral}")
        return

    for chunk, sim in resultados:
        parte_str = f"{chunk.libro}/{chunk.parte}" if chunk.parte else f"{chunk.libro}/sin parte"
        print(f"{chunk.id} (art {chunk.articulo}, {parte_str}): similitud={sim:.4f}")
        print(f"  {chunk.texto[:200]}...")


def _smoke() -> None:
    """Smoke test inline original (comentado, para uso manual)."""
    import hashlib

    class FakeEmbeddingFunction:
        def name(self) -> str:
            return "fake"

        def __call__(self, input: list[str]) -> list[list[float]]:
            return self.embed_query(input)

        def embed_query(self, input: list[str]) -> list[list[float]]:
            vectores = []
            for texto in input:
                h = hashlib.md5(texto.encode("utf-8")).digest()
                v = [((b - 127.5) / 127.5) for b in h]
                while len(v) < 1024:
                    v.extend(v[: min(len(v), 1024 - len(v))])
                v = v[:1024]
                norm = sum(x * x for x in v) ** 0.5
                if norm > 0:
                    v = [x / norm for x in v]
                vectores.append(v)
            return vectores

    html_sintetico = _html_sintetico_demo()

    corpus = parsear_articulos(html_sintetico)
    print(f"Articulos parseados: {len(corpus)}")
    for a in corpus:
        print(f"  Art {a.numero}: libro={a.libro}, parte={a.parte}, upls={a.upls_mencionadas}")

    fake_ef = FakeEmbeddingFunction()

    info1 = indexar_corpus(corpus, "/tmp/chroma_test", fake_ef)
    print(f"\nPrimera indexacion:")
    print(f"  total_articulos: {info1.total_articulos}")
    print(f"  hash_sha256: {info1.hash_sha256}")

    cliente = chromadb.PersistentClient(path="/tmp/chroma_test")
    coleccion = cliente.get_collection(name=COLECCION_NORMATIVA)
    count1 = coleccion.count()
    print(f"  coleccion.count(): {count1}")

    info2 = indexar_corpus(corpus, "/tmp/chroma_test", fake_ef)
    print(f"\nSegunda indexacion (idempotencia):")
    print(f"  total_articulos: {info2.total_articulos}")
    print(f"  hash_sha256: {info2.hash_sha256}")

    count2 = coleccion.count()
    print(f"  coleccion.count(): {count2}")
    print(f"  Idempotente (count igual): {count1 == count2}")

    resultado = coleccion.get(ids=["art-001"])
    print(f"\nMetadatos chunk art-001:")
    print(f"  ids: {resultado['ids']}")
    print(f"  metadatas: {resultado['metadatas']}")
    if resultado['metadatas']:
        meta = resultado['metadatas'][0]
        print(f"  parte == '': {meta.get('parte') == ''}")
        print(f"  upls == 'UPL17': {meta.get('upls') == 'UPL17'}")

    # Smoke tests para consultar_corpus
    print("\n=== Smoke tests consultar_corpus ===")

    # Test 1: Consulta básica
    print("\n1. consultar_corpus('usos del suelo', top_k=3, umbral_similitud=0.30)")
    resultados1 = consultar_corpus(
        "/tmp/chroma_test", fake_ef, "usos del suelo", top_k=3, umbral_similitud=0.30
    )
    print(f"   Resultados: {len(resultados1)}")
    for chunk, sim in resultados1:
        print(f"     {chunk.id} (art {chunk.articulo}): similitud={sim:.4f}")

    # Test 2: Consulta con filtro UPL
    print("\n2. consultar_corpus('usos del suelo', top_k=3, umbral_similitud=0.30, upl_filtro='UPL17')")
    resultados2 = consultar_corpus(
        "/tmp/chroma_test",
        fake_ef,
        "usos del suelo",
        top_k=3,
        umbral_similitud=0.30,
        upl_filtro="UPL17",
    )
    print(f"   Resultados: {len(resultados2)}")
    for chunk, sim in resultados2:
        print(f"     {chunk.id} (art {chunk.articulo}): similitud={sim:.4f}")

    # Test 3: Consulta sin resultados (umbral alto)
    print("\n3. consultar_corpus('texto inexistente xyz', top_k=3, umbral_similitud=0.50)")
    resultados3 = consultar_corpus(
        "/tmp/chroma_test", fake_ef, "texto inexistente xyz", top_k=3, umbral_similitud=0.50
    )
    print(f"   Resultados: {len(resultados3)} (esperado: 0)")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.ingesta.corpus",
        description="Ingesta y consulta del corpus normativo Decreto 555/2021",
    )
    subparsers = parser.add_subparsers(dest="comando", required=True)

    # --descargar
    p_desc = subparsers.add_parser("descargar", help="Descarga HTML sisjur, parsea, guarda JSONL + .sha256 (NO indexa)")
    p_desc.add_argument("--url", default=DEFAULT_URL, help="URL del documento en sisjur")
    p_desc.add_argument(
        "--demo",
        action="store_true",
        help="Si la red falla, usa HTML sintético de demo (no persiste corpus real)",
    )

    # --indexar
    p_idx = subparsers.add_parser("indexar", help="Lee JSONL versionado, indexa en ChromaDB")
    p_idx.add_argument("--ruta-indice", default=DEFAULT_INDICE, help="Ruta al índice ChromaDB")

    # --full
    p_full = subparsers.add_parser("full", help="Descarga + indexa (pipeline completo)")
    p_full.add_argument("--url", default=DEFAULT_URL, help="URL del documento en sisjur")
    p_full.add_argument("--ruta-indice", default=DEFAULT_INDICE, help="Ruta al índice ChromaDB")
    p_full.add_argument(
        "--demo",
        action="store_true",
        help="Si la red falla, usa HTML sintético de demo (no persiste corpus real)",
    )

    # --consultar
    p_cons = subparsers.add_parser("consultar", help="Consulta el índice vectorial")
    p_cons.add_argument("consulta", help="Texto de la consulta")
    p_cons.add_argument("--top-k", type=int, default=5, help="Máximo resultados (default: 5)")
    p_cons.add_argument("--umbral", type=float, default=0.35, help="Umbral similitud coseno (default: 0.35)")
    p_cons.add_argument("--upl", dest="upl_filtro", help="Filtrar por UPL (ej. UPL17)")
    p_cons.add_argument("--ruta-indice", default=DEFAULT_INDICE, help="Ruta al índice ChromaDB")

    args = parser.parse_args()

    try:
        if args.comando == "descargar":
            cmd_descargar(args.url, args.demo)
        elif args.comando == "indexar":
            cmd_indexar(args.ruta_indice)
        elif args.comando == "full":
            cmd_full(args.url, args.ruta_indice, args.demo)
        elif args.comando == "consultar":
            cmd_consultar(args.consulta, args.top_k, args.umbral, args.upl_filtro, args.ruta_indice)
    except CorpusNoIngestadoError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except OllamaNoDisponibleError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"Error inesperado: {e}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
