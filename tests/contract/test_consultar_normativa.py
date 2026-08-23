"""Contract tests para F2 — Tool MCP `consultar_normativa` (Historia de Usuario 1, FR-001, FR-003)."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import chromadb
import pytest

from app.errores import CorpusNoIngestadoError, OllamaNoDisponibleError
from app.models import COLECCION_NORMATIVA
from app.providers.normativa import NormativaProvider, UPL_VALIDAS
from tests.conftest import construir_servidor, provider_arcgis_estandar, provider_sdp_f3


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
        provider_sdp_f3(),  # SDP mockeado: consultar_normativa no lo consulta (hallazgo M5)
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
    """Valida que la respuesta real coincide con el contrato consultar-normativa.md.

    Extension ADITIVA F4 (SC-005): cada item de `resultados` gana `norma` y
    `source_name` (FR-004/FR-005, data-model.md:139-146); los campos F2
    conservan su semantica (FR-011).
    """
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
        assert set(resultado) == {
            "articulo", "titulo", "libro", "parte", "texto_cita", "similitud",
            # Campos aditivos F4 (SC-005): norma de origen por ítem.
            "norma", "source_name",
        }
        assert isinstance(resultado["articulo"], int) and resultado["articulo"] >= 1
        assert isinstance(resultado["titulo"], str)
        assert isinstance(resultado["libro"], str)
        assert resultado["parte"] in {"general", "urbano", "rural"}
        assert isinstance(resultado["texto_cita"], str)
        assert 0.0 <= resultado["similitud"] <= 1.0
        assert isinstance(resultado["norma"], str) and resultado["norma"]
        assert isinstance(resultado["source_name"], str) and resultado["source_name"]

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


# --- Tests F4: identificación de norma por ítem (T016, FR-004/FR-005) ---
# Extensiones ADITIVAS del contrato de F2 (SC-005): cada ítem de `resultados`
# gana `norma` y `source_name` (data-model.md:139-146,
# contracts/ingesta-actos-modificatorios.md:131-145). El provider aún no los
# emite (T018): estos tests definen el shape objetivo y permanecen en RED hasta
# que `_procesar_resultados` lea los metadatos extendidos del chunk
# (`titulo_norma`, `source_name`, data-model.md:113-130) y `consultar` los
# añada a cada ítem sin tocar los campos F2 (FR-011).


def _respuesta_chroma_con_metadatos_norma() -> dict:
    """Resultado sintético de `coleccion.query` con metadatos extendidos de norma.

    Dos chunks que coexisten para el mismo tema: el artículo 1 del Decreto 555
    de 2021 (usos del suelo) y el artículo 4 del Decreto 122 de 2023 (vivienda
    colectiva). La coexistencia (FR-006/FR-012) exige que NINGUNO se oculte en
    la respuesta.
    """
    return {
        "ids": [["decreto555-2021-art-001", "Decreto_122_2023-art-004"]],
        "documents": [
            [
                "El presente artículo regula los usos del suelo en la UPL17. "
                "Permite vivienda y comercio.",
                "El presente decreto reglamenta la vivienda colectiva en Bogotá.",
            ]
        ],
        "metadatas": [
            [
                {
                    "articulo": 1,
                    "titulo": "Usos del suelo en UPL17",
                    "libro": "II",
                    "parte": "urbano",
                    "titulo_norma": "Decreto 555 de 2021",
                    "source_name": "Decreto 555 de 2021 (POT Bogotá)",
                },
                {
                    "articulo": 4,
                    "titulo": "Vivienda colectiva",
                    "libro": "III",
                    "parte": "urbano",
                    "titulo_norma": "Decreto 122 de 2023",
                    "source_name": "Decreto 122 de 2023",
                },
            ]
        ],
        "distances": [[0.0, 0.0]],
    }


async def _consultar_normativa_con_chunks_sinteticos(servidor, respuesta_llm: str) -> dict:
    """Consulta F2 con resultados sintéticos de ChromaDB (metadatos de norma F4).

    Reemplaza la recuperación vectorial real (los chunks del índice actual aún
    no llevan los metadatos extendidos: T020) por un resultado que SÍ los lleva;
    así el test fija el contrato de T018 de forma aislada y determinista.
    """
    coleccion_fake = MagicMock()
    coleccion_fake.query.return_value = _respuesta_chroma_con_metadatos_norma()
    with patch.object(NormativaProvider, "_get_coleccion", return_value=coleccion_fake), \
         patch.object(NormativaProvider, "_verificar_ollama_chat", new=AsyncMock()), \
         patch.object(
             NormativaProvider,
             "_generar_respuesta_llm",
             new=AsyncMock(return_value=respuesta_llm),
         ):
        return await servidor.consultar_normativa(consulta="vivienda colectiva")


@pytest.mark.asyncio
async def test_fragmento_decreto_555_lleva_norma_y_source_name(servidor_normativa_rag):
    """Un fragmento del 555 lleva `norma: "Decreto 555 de 2021"` y su source_name (FR-004/FR-005)."""
    resp = await _consultar_normativa_con_chunks_sinteticos(
        servidor_normativa_rag,
        respuesta_llm="El Artículo 1 regula los usos del suelo en la UPL17.",
    )
    await servidor_normativa_rag.aclose()

    fragmentos = {r["articulo"]: r for r in resp["resultados"]}
    assert fragmentos[1]["norma"] == "Decreto 555 de 2021"
    assert fragmentos[1]["source_name"] == "Decreto 555 de 2021 (POT Bogotá)"


@pytest.mark.asyncio
async def test_fragmento_de_acto_lleva_norma_decreto_122(servidor_normativa_rag):
    """Un fragmento del Decreto 122 de 2023 lleva `norma: "Decreto 122 de 2023"` (FR-004/FR-005)."""
    resp = await _consultar_normativa_con_chunks_sinteticos(
        servidor_normativa_rag,
        respuesta_llm="El Artículo 4 reglamenta la vivienda colectiva.",
    )
    await servidor_normativa_rag.aclose()

    fragmentos = {r["articulo"]: r for r in resp["resultados"]}
    assert fragmentos[4]["norma"] == "Decreto 122 de 2023"
    assert fragmentos[4]["source_name"] == "Decreto 122 de 2023"


@pytest.mark.asyncio
async def test_decreto_555_y_acto_coexisten_sin_ocultarse(servidor_normativa_rag):
    """555 y acto que cubren el mismo tema: AMBOS ítems están en resultados (FR-006, FR-012)."""
    resp = await _consultar_normativa_con_chunks_sinteticos(
        servidor_normativa_rag,
        respuesta_llm="El Artículo 1 y el Artículo 4 regulan la vivienda colectiva.",
    )
    await servidor_normativa_rag.aclose()

    assert {r["articulo"] for r in resp["resultados"]} == {1, 4}
    assert {r["norma"] for r in resp["resultados"]} == {
        "Decreto 555 de 2021",
        "Decreto 122 de 2023",
    }
