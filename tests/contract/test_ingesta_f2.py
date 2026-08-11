"""Contract tests para F2 — Ingesta normativa RAG (tasks.md T020-T024).

Cubre: parseo, chunking, hash, serialización, indexación idempotente,
consulta con filtro UPL estricto. Sin red real; usa fake embeddings.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import chromadb
import pytest

from app.ingesta.corpus import (
    _etiqueta_embedding,
    _modelo_embedding_env,
    parsear_articulos,
    chunk_articulo,
    hash_documento,
    serializar_corpus,
    deserializar_corpus,
    indexar_corpus,
    consultar_corpus,
)
from app.models import (
    ArticuloNormativo,
    Chunk,
    COLECCION_NORMATIVA,
    CorpusInfo,
    METADATA_CORPUS_SHA256,
    METADATA_EMBEDDING_MODEL,
)


HTML_SINTETICO = """\
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

HTML_SIN_PARTE = """\
LIBRO I
ARTÍCULO 1. Disposiciones generales.
Este es un artículo del Libro I sin parte derivada.
"""

HTML_CHUNKING = """\
LIBRO II
ARTÍCULO 1. Artículo largo.
""" + ("Párrafo " + "x" * 100 + "\n") * 50


class FakeEmbeddingFunction:
    """Embedding function determinista 1024 dims para tests.

    `model_name` emula el nombre del modelo de embeddings (p. ej. el que recibe
    OllamaEmbeddingFunction): permite simular el cambio de `OLLAMA_EMBEDDING_MODEL`
    usando dos fakes con nombres distintos.
    """

    def __init__(self, model_name: str = "fake"):
        self.model_name = model_name

    def name(self) -> str:
        return self.model_name

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


class EmbeddingFunctionLegacy:
    """Stub de EF de chromadb < 1.4: sin atributo `model_name`.

    Emula el comportamiento degradado de OllamaEmbeddingFunction en versiones
    antiguas (el atributo era `_model_name` y `name()` siempre devolvía "ollama").
    """

    def name(self) -> str:
        return "ollama"


@pytest.fixture
def corpus_base():
    return parsear_articulos(HTML_SINTETICO)


@pytest.fixture
def fake_ef():
    return FakeEmbeddingFunction()


@pytest.fixture
def chroma_tempdir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp) / "chroma_test"


# --- Parseo (FR-003: texto literal, ubicación, referencias) ---

def test_parsear_articulos_devuelve_articulos_tipados(corpus_base):
    assert len(corpus_base) == 3
    for a in corpus_base:
        assert isinstance(a, ArticuloNormativo)
        assert a.numero > 0
        assert a.titulo
        assert a.texto
        assert a.libro in {"I", "II", "III", "IV", "V", "VI", "VII", "VIII"}
        assert isinstance(a.upls_mencionadas, list)
        assert isinstance(a.articulos_derogados, list)


def test_parsear_articulos_libro_ii_tiene_parte_general(corpus_base):
    art1 = next(a for a in corpus_base if a.numero == 1)
    assert art1.libro == "II"
    assert art1.parte == "general"
    assert "UPL17" in art1.upls_mencionadas


def test_parsear_articulos_libro_iii_tiene_parte_urbano(corpus_base):
    art2 = next(a for a in corpus_base if a.numero == 2)
    assert art2.libro == "III"
    assert art2.parte == "urbano"
    assert art2.upls_mencionadas == ["UPL20"]


def test_parsear_articulos_libro_i_sin_parte():
    corpus = parsear_articulos(HTML_SIN_PARTE)
    art = corpus[0]
    assert art.libro == "I"
    assert art.parte is None


def test_parsear_articulos_articulos_derogados(corpus_base):
    art3 = next(a for a in corpus_base if a.numero == 3)
    assert 5 in art3.articulos_derogados


def test_parsear_articulos_html_vacio_raise_valueerror():
    with pytest.raises(ValueError, match=r"No se encontró ningún 'ARTÍCULO'"):
        parsear_articulos("<html><body>Sin artículos</body></html>")


# --- Chunking (boundary-aware, overlap 1 párrafo) ---

def test_chunk_articulo_articulo_corto_un_chunk(corpus_base):
    art1 = next(a for a in corpus_base if a.numero == 1)
    chunks = chunk_articulo(art1)
    assert len(chunks) == 1
    c = chunks[0]
    assert isinstance(c, Chunk)
    assert c.id == "art-001"
    assert c.articulo == 1
    assert c.titulo == art1.titulo
    assert c.libro == art1.libro
    assert c.parte == art1.parte
    assert c.texto == art1.texto


def test_chunk_articulo_articulo_largo_multiples_chunks_con_solape():
    corpus = parsear_articulos(HTML_CHUNKING)
    art = corpus[0]
    chunks = chunk_articulo(art)
    assert len(chunks) > 1
    assert chunks[0].id == "art-001"
    assert chunks[1].id == "art-001-1"
    # Verificar solape: último párrafo del chunk 0 == primer párrafo del chunk 1
    p0 = chunks[0].texto.split("\n")[-1]
    p1 = chunks[1].texto.split("\n")[0]
    assert p0 == p1


def test_chunk_articulo_hereda_metadatos(corpus_base):
    for a in corpus_base:
        for c in chunk_articulo(a):
            assert c.articulo == a.numero
            assert c.titulo == a.titulo
            assert c.libro == a.libro
            assert c.parte == a.parte
            assert c.seccion == a.seccion


# --- Hash determinista (FR-009) ---

def test_hash_documento_determinista(corpus_base):
    h1 = hash_documento(corpus_base)
    h2 = hash_documento(corpus_base)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_hash_documento_diferente_corpus_diferente_hash():
    c1 = parsear_articulos(HTML_SINTETICO)
    c2 = parsear_articulos(HTML_SIN_PARTE)
    assert hash_documento(c1) != hash_documento(c2)


# --- Serialización JSONL roundtrip ---

def test_serializar_deserializar_corpus_roundtrip(corpus_base, tmp_path):
    ruta = tmp_path / "corpus_test.jsonl"
    serializar_corpus(corpus_base, str(ruta))
    corpus2 = deserializar_corpus(str(ruta))
    assert len(corpus2) == len(corpus_base)
    assert hash_documento(corpus2) == hash_documento(corpus_base)
    for a1, a2 in zip(corpus_base, corpus2):
        assert a1.model_dump() == a2.model_dump()


def test_serializar_corpus_crea_directorio_padre(tmp_path):
    corpus_base_local = parsear_articulos(HTML_SINTETICO)
    ruta = tmp_path / "subdir" / "corpus.jsonl"
    serializar_corpus(corpus_base_local, str(ruta))
    assert ruta.exists()


def test_deserializar_corpus_no_existe_raise():
    with pytest.raises(FileNotFoundError):
        deserializar_corpus("/ruta/inexistente.jsonl")


# --- Indexación idempotente (ChromaDB upsert) ---

def test_indexar_corpus_devuelve_corpus_info(corpus_base, chroma_tempdir, fake_ef):
    info = indexar_corpus(corpus_base, str(chroma_tempdir), fake_ef)
    assert isinstance(info, CorpusInfo)
    assert info.documento == "Decreto 555 de 2021 (POT Bogotá)"
    assert info.vigencia == "2021-12-30"
    assert info.hash_sha256 == hash_documento(corpus_base)
    assert info.total_articulos == len(corpus_base)


def test_indexar_corpus_idempotente_duplicados_no_aumentan_count(corpus_base, chroma_tempdir, fake_ef):
    indexar_corpus(corpus_base, str(chroma_tempdir), fake_ef)
    cliente = chromadb.PersistentClient(path=str(chroma_tempdir))
    coleccion = cliente.get_collection(COLECCION_NORMATIVA)
    count1 = coleccion.count()

    indexar_corpus(corpus_base, str(chroma_tempdir), fake_ef)
    count2 = coleccion.count()

    assert count1 == count2
    assert count1 > 0


def test_indexar_corpus_metadatos_chunk_correctos(corpus_base, chroma_tempdir, fake_ef):
    indexar_corpus(corpus_base, str(chroma_tempdir), fake_ef)
    cliente = chromadb.PersistentClient(path=str(chroma_tempdir))
    coleccion = cliente.get_collection(COLECCION_NORMATIVA)

    res = coleccion.get(ids=["art-001"])
    meta = res["metadatas"][0]
    assert meta["parte"] == "general"
    assert meta["upls"] == "UPL17"
    assert meta["articulo"] == 1
    assert meta["libro"] == "II"

    res2 = coleccion.get(ids=["art-002"])
    meta2 = res2["metadatas"][0]
    assert meta2["parte"] == "urbano"
    assert meta2["upls"] == "UPL20"


# --- Reconstrucción del índice por cambio de embeddings (FR-008) ---

def test_indexar_reconstruye_al_cambiar_modelo_embedding(corpus_base, chroma_tempdir):
    ef_a = FakeEmbeddingFunction(model_name="modelo-a")
    ef_b = FakeEmbeddingFunction(model_name="modelo-b")

    indexar_corpus(corpus_base, str(chroma_tempdir), ef_a)

    cliente_inicial = chromadb.PersistentClient(path=str(chroma_tempdir))
    col_inicial = cliente_inicial.get_collection(COLECCION_NORMATIVA)
    assert col_inicial.metadata[METADATA_EMBEDDING_MODEL] == "modelo-a"
    assert col_inicial.metadata[METADATA_CORPUS_SHA256] == hash_documento(corpus_base)
    conteo_inicial = col_inicial.count()

    # Mismo corpus, otro modelo de embeddings: la colección se reconstruye.
    indexar_corpus(corpus_base, str(chroma_tempdir), ef_b)

    cliente_final = chromadb.PersistentClient(path=str(chroma_tempdir))
    col_final = cliente_final.get_collection(COLECCION_NORMATIVA)
    assert col_final.metadata[METADATA_EMBEDDING_MODEL] == "modelo-b"
    assert col_final.count() == conteo_inicial
    assert col_final.count() == len(corpus_base)
    # Sin duplicados ni huérfanos: ids exactos de los chunks del corpus actual.
    ids_esperados = sorted(c.id for a in corpus_base for c in chunk_articulo(a))
    assert sorted(col_final.get()["ids"]) == ids_esperados


def test_indexar_reconstruye_indice_legado_sin_huella_embedding(
    corpus_base, chroma_tempdir, fake_ef
):
    # Colección creada antes del safeguard: metadata sin la clave embedding_model.
    cliente_legado = chromadb.PersistentClient(path=str(chroma_tempdir))
    cliente_legado.create_collection(
        name=COLECCION_NORMATIVA,
        embedding_function=fake_ef,
        metadata={
            "hnsw:space": "cosine",
            METADATA_CORPUS_SHA256: hash_documento(corpus_base),
        },
    )

    # Re-indexar: el índice legado se reconstruye y la metadata gana la huella.
    indexar_corpus(corpus_base, str(chroma_tempdir), fake_ef)

    cliente_final = chromadb.PersistentClient(path=str(chroma_tempdir))
    coleccion = cliente_final.get_collection(COLECCION_NORMATIVA)
    assert coleccion.metadata[METADATA_EMBEDDING_MODEL] == "fake"
    assert coleccion.metadata[METADATA_CORPUS_SHA256] == hash_documento(corpus_base)
    assert coleccion.count() == len(corpus_base)


# --- Normalización del modelo de embeddings y etiqueta (FR-008) ---
# Unit tests directos de helpers: sin ChromaDB ni red.

def test_modelo_embedding_env_default_sin_tag(monkeypatch):
    """Env sin variable: el default se normaliza a 'bge-m3:latest'."""
    monkeypatch.delenv("OLLAMA_EMBEDDING_MODEL", raising=False)
    assert _modelo_embedding_env() == "bge-m3:latest"


def test_modelo_embedding_env_con_tag_se_preserva(monkeypatch):
    """Tag explícito 'bge-m3:1.2': se conserva tal cual."""
    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "bge-m3:1.2")
    assert _modelo_embedding_env() == "bge-m3:1.2"


def test_modelo_embedding_env_con_digest_se_preserva(monkeypatch):
    """Digest 'sha256:...': se conserva tal cual."""
    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "sha256:abc123...")
    assert _modelo_embedding_env() == "sha256:abc123..."


def test_modelo_embedding_env_variable_vacia_usa_default(monkeypatch):
    """Variable definida pero vacía: se trata como no definida (default)."""
    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "")
    assert _modelo_embedding_env() == "bge-m3:latest"


def test_modelo_embedding_env_con_espacios_se_normaliza(monkeypatch):
    """Variable con solo espacios alrededor: se normaliza al default."""
    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "  bge-m3  ")
    assert _modelo_embedding_env() == "bge-m3:latest"


def test_etiqueta_embedding_usa_model_name_de_la_ef():
    """EF con `model_name`: la etiqueta usa ese nombre, no el env var."""
    assert _etiqueta_embedding(FakeEmbeddingFunction(model_name="modelo-a")) == "modelo-a"


def test_etiqueta_embedding_sin_model_name_cae_al_env_var(monkeypatch):
    """EF de versión vieja (sin `model_name`): la etiqueta usa el env var actual."""
    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "modelo-b")
    assert _etiqueta_embedding(EmbeddingFunctionLegacy()) == "modelo-b:latest"


# --- Consulta con top-k, umbral y filtro UPL (FR-002) ---
# Nota: fake embeddings no tienen calidad semántica; tests validan flujo y parámetros.

def test_consultar_corpus_ejecuta_y_devuelve_lista(corpus_base, chroma_tempdir, fake_ef):
    indexar_corpus(corpus_base, str(chroma_tempdir), fake_ef)
    resultados = consultar_corpus(
        str(chroma_tempdir), fake_ef, "usos del suelo", top_k=3, umbral_similitud=0.0
    )
    assert isinstance(resultados, list)
    for chunk, sim in resultados:
        assert isinstance(chunk, Chunk)
        assert 0.0 <= sim <= 1.0


def test_consultar_corpus_filtro_upl_estricto(corpus_base, chroma_tempdir, fake_ef):
    indexar_corpus(corpus_base, str(chroma_tempdir), fake_ef)

    # Con filtro UPL17
    resultados_upl17 = consultar_corpus(
        str(chroma_tempdir), fake_ef, "normas", top_k=10, umbral_similitud=0.0, upl_filtro="UPL17"
    )

    # Verificar que el filtro se aplica (aunque fake embeddings pueden devolver 0 resultados,
    # el parámetro where se pasa correctamente a Chroma)
    # Validamos que no falle y que si hay resultados, tengan UPL17
    for chunk, _ in resultados_upl17:
        art_original = next(a for a in corpus_base if a.numero == chunk.articulo)
        assert "UPL17" in art_original.upls_mencionadas

    # Filtro UPL inexistente -> no falla
    resultados_vacio = consultar_corpus(
        str(chroma_tempdir), fake_ef, "normas", top_k=10, umbral_similitud=0.0, upl_filtro="UPL99"
    )
    assert isinstance(resultados_vacio, list)


def test_consultar_corpus_umbral_similitud_filtra(corpus_base, chroma_tempdir, fake_ef):
    indexar_corpus(corpus_base, str(chroma_tempdir), fake_ef)

    r_alto = consultar_corpus(str(chroma_tempdir), fake_ef, "usos", top_k=5, umbral_similitud=0.80)
    r_bajo = consultar_corpus(str(chroma_tempdir), fake_ef, "usos", top_k=5, umbral_similitud=0.10)
    assert len(r_alto) <= len(r_bajo)


def test_consultar_corpus_ordenado_por_similitud_desc(corpus_base, chroma_tempdir, fake_ef):
    indexar_corpus(corpus_base, str(chroma_tempdir), fake_ef)
    resultados = consultar_corpus(str(chroma_tempdir), fake_ef, "usos", top_k=5, umbral_similitud=0.0)
    sims = [s for _, s in resultados]
    assert sims == sorted(sims, reverse=True)


def test_consultar_corpus_indice_no_existente_raise(chroma_tempdir, fake_ef):
    with pytest.raises(ValueError, match="Índice no encontrado"):
        consultar_corpus(str(chroma_tempdir), fake_ef, "test", top_k=5, umbral_similitud=0.0)