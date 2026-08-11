"""Contract tests para F2 — Provider Normativa (consultar_normativa RAG)."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import chromadb
import pytest

from app.errores import CorpusNoIngestadoError
from app.providers.normativa import NormativaProvider, UPL_VALIDAS


class FakeEmbeddingFunction:
    """Embedding function determinista 1024 dims para tests."""

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


@pytest.fixture
def chroma_tempdir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp) / "chroma_test"


@pytest.fixture
def fake_ef():
    return FakeEmbeddingFunction()


def _indexar_corpus_sintetico(chroma_path: Path, fake_ef):
    """Indexa un corpus sintético mínimo para tests."""
    from app.ingesta.corpus import parsear_articulos, indexar_corpus

    html = """\
LIBRO II
ARTÍCULO 1. Usos del suelo en UPL17.
El presente artículo regula los usos del suelo en la UPL17.

LIBRO III
ARTÍCULO 2. Normas urbanas UPL20.
Este artículo establece normas para la UPL20.

LIBRO III
ARTÍCULO 3. Derogatoria.
La presente norma deroga el artículo 5 del Decreto 100 de 2000.
"""
    corpus = parsear_articulos(html)
    indexar_corpus(corpus, str(chroma_path), fake_ef)
    return corpus


def test_normativa_provider_indice_no_existe_raise_corpus_no_ingestado(chroma_tempdir, fake_ef):
    provider = NormativaProvider(ruta_indice=str(chroma_tempdir))
    # Inyectar fake EF
    provider._embedding_function = fake_ef

    with pytest.raises(CorpusNoIngestadoError, match="no está ingestado"):
        provider._get_coleccion()


def test_normativa_provider_validacion_consulta_vacia(chroma_tempdir, fake_ef):
    _indexar_corpus_sintetico(chroma_tempdir, fake_ef)
    provider = NormativaProvider(ruta_indice=str(chroma_tempdir))
    provider._embedding_function = fake_ef

    with pytest.raises(ValueError, match="vacía"):
        provider._validar_entrada("", None, 3)
    with pytest.raises(ValueError, match="vacía"):
        provider._validar_entrada("   ", None, 3)


def test_normativa_provider_validacion_consulta_larga(chroma_tempdir, fake_ef):
    _indexar_corpus_sintetico(chroma_tempdir, fake_ef)
    provider = NormativaProvider(ruta_indice=str(chroma_tempdir))
    provider._embedding_function = fake_ef

    with pytest.raises(ValueError, match="excede"):
        provider._validar_entrada("x" * 501, None, 3)


def test_normativa_provider_validacion_top_k_rango(chroma_tempdir, fake_ef):
    _indexar_corpus_sintetico(chroma_tempdir, fake_ef)
    provider = NormativaProvider(ruta_indice=str(chroma_tempdir))
    provider._embedding_function = fake_ef

    with pytest.raises(ValueError, match="top_k debe estar entre 1 y 6"):
        provider._validar_entrada("consulta", None, 0)
    with pytest.raises(ValueError, match="top_k debe estar entre 1 y 6"):
        provider._validar_entrada("consulta", None, 7)


def test_normativa_provider_validacion_upl_formato_invalido(chroma_tempdir, fake_ef):
    _indexar_corpus_sintetico(chroma_tempdir, fake_ef)
    provider = NormativaProvider(ruta_indice=str(chroma_tempdir))
    provider._embedding_function = fake_ef

    with pytest.raises(ValueError, match="UPL inválida"):
        provider._validar_entrada("consulta", "UPL99", 3)  # Fuera de rango
    with pytest.raises(ValueError, match="UPL inválida"):
        provider._validar_entrada("consulta", "UPLX", 3)   # Formato
    with pytest.raises(ValueError, match="UPL inválida"):
        provider._validar_entrada("consulta", "17", 3)     # Sin prefijo


def test_normativa_provider_upls_validas_cubre_upl01_a_upl33():
    assert len(UPL_VALIDAS) == 33
    assert "UPL01" in UPL_VALIDAS
    assert "UPL17" in UPL_VALIDAS
    assert "UPL33" in UPL_VALIDAS
    assert "UPL00" not in UPL_VALIDAS
    assert "UPL34" not in UPL_VALIDAS


# Tests de integración del pipeline RAG requieren Ollama real (chat model).
# Se ejecutan en entorno con ollama serve + modelos (bge-m3, qwen3:8b).
# Ver quickstart.md para instrucciones.

# @pytest.mark.integration
# @pytest.mark.asyncio
# async def test_normativa_provider_consulta_basica_sin_upl(chroma_tempdir, fake_ef):
#     pass  # Requiere Ollama real