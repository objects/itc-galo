"""Contract tests para F2 — Tool MCP `consultar_normativa` (Historia de Usuario 1, FR-001, FR-003)."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import chromadb
import pytest

from app.errores import CorpusNoIngestadoError, OllamaNoDisponibleError
from app.models import COLECCION_NORMATIVA
from app.providers.normativa import NormativaProvider, UPL_VALIDAS
from tests.conftest import construir_servidor, provider_arcgis_estandar


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


class FakeEmbeddingFunctionConstante:
    """Embedding function que devuelve el mismo vector unitario para todo texto.

    Con ella toda consulta recupera los chunks del corpus con similitud 1.0:
    permite probar el flujo RAG completo (recuperación + citation forcing)
    sin Ollama real ni red.
    """

    VECTOR = [1.0 / (1024 ** 0.5)] * 1024

    def name(self) -> str:
        return "fake_constante"

    def __call__(self, input: list[str]) -> list[list[float]]:
        return self.embed_query(input)

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return [list(self.VECTOR) for _ in input]


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
El presente artículo regula los usos del suelo en la UPL17. Permite vivienda y comercio.

LIBRO III
ARTÍCULO 2. Normas urbanas UPL20.
Este artículo establece normas para la UPL20. Define alturas máximas.

LIBRO III
ARTÍCULO 3. Derogatoria.
La presente norma deroga el artículo 5 del Decreto 100 de 2000.
"""
    corpus = parsear_articulos(html)
    indexar_corpus(corpus, str(chroma_path), fake_ef)
    return corpus


def _construir_servidor_normativa(chroma_path: Path, ef, indexar: bool = True):
    """ServidorLotes con corpus normativo opcionalmente indexado (sin red ni Ollama)."""
    if indexar:
        _indexar_corpus_sintetico(chroma_path, ef)
    import httpx
    from app.providers.normativa import NormativaProvider
    from app.main import ServidorLotes
    from app.providers.upl import UPLProvider
    from app.providers.mapas_bogota import MapasBogotaProvider

    provider_norm = NormativaProvider(ruta_indice=str(chroma_path))
    provider_norm._embedding_function = ef
    provider_norm._chat_model = "fake"

    return ServidorLotes(
        MapasBogotaProvider(api_key="clave"),
        provider_arcgis_estandar(),
        UPLProvider(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"type": "FeatureCollection", "features": []}))),
        provider_norm,
    )


@pytest.fixture
def servidor_normativa_ok(chroma_tempdir, fake_ef):
    """Servidor con corpus indexado y proveedor normativa funcional."""
    return _construir_servidor_normativa(chroma_tempdir, fake_ef)


@pytest.fixture
def servidor_normativa_rag(chroma_tempdir):
    """Servidor con embeddings constantes: el flujo RAG se prueba sin Ollama real."""
    return _construir_servidor_normativa(chroma_tempdir, FakeEmbeddingFunctionConstante())


@pytest.fixture
def servidor_normativa_sin_indice(chroma_tempdir):
    """Servidor cuyo índice normativo no existe (flujo CORPUS_NO_INGESTADO)."""
    return _construir_servidor_normativa(chroma_tempdir, FakeEmbeddingFunctionConstante(), indexar=False)


# --- Tests de validación de entrada (FR-013) ---

@pytest.mark.asyncio
async def test_consultar_normativa_consulta_vacia_devuelve_parametros_invalidos(servidor_normativa_ok):
    resp = await servidor_normativa_ok.consultar_normativa(consulta="")
    await servidor_normativa_ok.aclose()
    assert resp["error"]["code"] == "PARAMETROS_INVALIDOS"
    assert "vacía" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_consultar_normativa_consulta_muy_larga_devuelve_parametros_invalidos(servidor_normativa_ok):
    resp = await servidor_normativa_ok.consultar_normativa(consulta="x" * 501)
    await servidor_normativa_ok.aclose()
    assert resp["error"]["code"] == "PARAMETROS_INVALIDOS"
    assert "excede" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_consultar_normativa_top_k_fuera_de_rango_devuelve_parametros_invalidos(servidor_normativa_ok):
    resp = await servidor_normativa_ok.consultar_normativa(consulta="test", top_k=0)
    await servidor_normativa_ok.aclose()
    assert resp["error"]["code"] == "PARAMETROS_INVALIDOS"
    assert "top_k debe estar entre 1 y 6" in resp["error"]["message"]

    resp = await servidor_normativa_ok.consultar_normativa(consulta="test", top_k=7)
    assert resp["error"]["code"] == "PARAMETROS_INVALIDOS"


@pytest.mark.asyncio
async def test_top_k_bool_devuelve_parametros_invalidos(servidor_normativa_ok):
    """top_k=True (bool es subclase de int) -> PARAMETROS_INVALIDOS (deuda post-revision).

    El provider validaba `1 <= top_k <= TOP_K_MAX` sin type-check: True pasaba
    como 1. Ahora rechaza explicitamente los bools y la tool F2 traduce el
    ValueError a PARAMETROS_INVALIDOS.
    """
    resp = await servidor_normativa_ok.consultar_normativa(consulta="test", top_k=True)
    await servidor_normativa_ok.aclose()
    assert resp["error"]["code"] == "PARAMETROS_INVALIDOS"
    assert "top_k debe estar entre 1 y 6" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_consultar_normativa_upl_invalida_formato_devuelve_parametros_invalidos(servidor_normativa_ok):
    resp = await servidor_normativa_ok.consultar_normativa(consulta="test", upl="UPL99")
    await servidor_normativa_ok.aclose()
    assert resp["error"]["code"] == "PARAMETROS_INVALIDOS"
    assert "UPL inválida" in resp["error"]["message"]

    resp = await servidor_normativa_ok.consultar_normativa(consulta="test", upl="UPLX")
    assert resp["error"]["code"] == "PARAMETROS_INVALIDOS"


# --- Test de UPLs válidas ---

def test_upl_validas_cubre_upl01_a_upl33():
    assert len(UPL_VALIDAS) == 33
    assert "UPL01" in UPL_VALIDAS
    assert "UPL17" in UPL_VALIDAS
    assert "UPL33" in UPL_VALIDAS
    assert "UPL00" not in UPL_VALIDAS
    assert "UPL34" not in UPL_VALIDAS


# --- Tests de flujo RAG sin red ni Ollama real (LLM falso inyectado) ---
# El LLM se mockea con unittest.mock sobre _generar_respuesta_llm; la
# recuperación vectorial es real sobre el corpus sintético con embeddings
# constantes (FakeEmbeddingFunctionConstante -> similitud 1.0).

@pytest.mark.asyncio
async def test_consultar_normativa_respuesta_con_cita_valida_devuelve_exito(servidor_normativa_rag):
    """Respuesta LLM citando un artículo recuperado -> éxito sin reintento."""
    mock_llm = AsyncMock(
        return_value="Según el Artículo 1, el uso del suelo en UPL17 es vivienda y comercio."
    )
    with patch.object(NormativaProvider, "_verificar_ollama_chat", new=AsyncMock()), \
         patch.object(NormativaProvider, "_generar_respuesta_llm", new=mock_llm):
        resp = await servidor_normativa_rag.consultar_normativa(consulta="usos del suelo")
    await servidor_normativa_rag.aclose()

    assert resp["sin_resultados"] is False
    assert "Artículo 1" in resp["respuesta"]
    assert {r["articulo"] for r in resp["resultados"]} == {1, 2, 3}
    mock_llm.assert_awaited_once()


@pytest.mark.asyncio
async def test_consultar_normativa_cita_no_verificable_devuelve_abstencion(servidor_normativa_rag):
    """Respuesta LLM citando un artículo ajeno a los recuperados -> reintento y abstención."""

    async def _respuesta_con_cita_ajena(consulta, chunks, articulos_permitidos=None):
        return "Según el Artículo 99, se permite lo que diga la norma."

    mock_llm = AsyncMock(side_effect=_respuesta_con_cita_ajena)
    with patch.object(NormativaProvider, "_verificar_ollama_chat", new=AsyncMock()), \
         patch.object(NormativaProvider, "_generar_respuesta_llm", new=mock_llm):
        resp = await servidor_normativa_rag.consultar_normativa(consulta="usos del suelo")
    await servidor_normativa_rag.aclose()

    assert resp["sin_resultados"] is True
    assert resp["resultados"] == []
    assert "No se encontraron resultados" in resp["respuesta"]
    # Primer intento + reintento restringido a los artículos recuperados (FIX 4).
    assert mock_llm.await_count == 2
    primer_intento, reintento = mock_llm.await_args_list
    assert "articulos_permitidos" not in primer_intento.kwargs
    assert reintento.kwargs["articulos_permitidos"] == {1, 2, 3}


@pytest.mark.asyncio
async def test_consultar_normativa_corpus_no_ingestado_devuelve_codigo_canonico(servidor_normativa_sin_indice):
    """Índice inexistente -> CORPUS_NO_INGESTADO en el límite de la tool."""
    with patch.object(NormativaProvider, "_verificar_ollama_chat", new=AsyncMock()):
        resp = await servidor_normativa_sin_indice.consultar_normativa(consulta="usos del suelo")
    await servidor_normativa_sin_indice.aclose()

    assert resp["error"]["code"] == "CORPUS_NO_INGESTADO"
    assert "no está ingestado" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_consultar_normativa_ollama_no_disponible_devuelve_codigo_canonico(servidor_normativa_rag):
    """Ollama caído -> OLLAMA_NO_DISPONIBLE en el límite de la tool."""
    with patch.object(
        NormativaProvider,
        "_verificar_ollama_chat",
        new=AsyncMock(side_effect=OllamaNoDisponibleError(modelo="qwen3:8b")),
    ):
        resp = await servidor_normativa_rag.consultar_normativa(consulta="usos del suelo")
    await servidor_normativa_rag.aclose()

    assert resp["error"]["code"] == "OLLAMA_NO_DISPONIBLE"
    assert "qwen3:8b" in resp["error"]["message"]


def test_coleccion_runtime_es_coleccion_normativa(chroma_tempdir, fake_ef):
    """El provider lee en runtime la colección COLECCION_NORMATIVA (constante compartida)."""
    _indexar_corpus_sintetico(chroma_tempdir, fake_ef)
    provider = NormativaProvider(ruta_indice=str(chroma_tempdir))
    provider._embedding_function = fake_ef

    coleccion = provider._get_coleccion()
    assert coleccion.name == COLECCION_NORMATIVA == "decreto_555_2021"


# --- Test de estructura de respuesta esperada (contrato) ---

@pytest.mark.asyncio
async def test_consultar_normativa_estructura_respuesta_coincide_con_contrato(servidor_normativa_rag):
    """Valida que la respuesta real coincide con el contrato consultar-normativa.md."""
    mock_llm = AsyncMock(
        return_value="El Artículo 1 regula los usos del suelo en la UPL17."
    )
    with patch.object(NormativaProvider, "_verificar_ollama_chat", new=AsyncMock()), \
         patch.object(NormativaProvider, "_generar_respuesta_llm", new=mock_llm):
        resp = await servidor_normativa_rag.consultar_normativa(consulta="usos del suelo")
    await servidor_normativa_rag.aclose()

    assert set(resp) == {"respuesta", "sin_resultados", "resultados", "trazabilidad"}
    assert isinstance(resp["respuesta"], str) and resp["respuesta"]
    assert isinstance(resp["sin_resultados"], bool)

    for resultado in resp["resultados"]:
        assert set(resultado) == {"articulo", "titulo", "libro", "parte", "texto_cita", "similitud"}
        assert isinstance(resultado["articulo"], int) and resultado["articulo"] >= 1
        assert isinstance(resultado["titulo"], str)
        assert isinstance(resultado["libro"], str)
        assert resultado["parte"] in {"general", "urbano", "rural"}
        assert isinstance(resultado["texto_cita"], str)
        assert 0.0 <= resultado["similitud"] <= 1.0

    assert set(resp["trazabilidad"]) == {
        "source_name", "layer_id", "service_url", "data_vigencia", "query_timestamp",
    }
    assert resp["trazabilidad"]["source_name"] == "Decreto 555 de 2021 (POT Bogotá)"


def test_codigos_error_contrato():
    """Documenta los códigos de error esperados según el contrato."""
    codigos = {
        "PARAMETROS_INVALIDOS": "consulta vacía/larga, top_k fuera de rango, UPL mal formada/inexistente",
        "CORPUS_NO_INGESTADO": "índice vacío o desactualizado",
        "OLLAMA_NO_DISPONIBLE": "servicio Ollama inaccesible o modelo faltante",
        "FUENTE_5XX": "verificación/actualización de corpus responde 5xx",
    }
    assert len(codigos) == 4