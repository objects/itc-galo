"""Contract tests Fase 4 — RAG híbrido + reglas de vigencia/jerarquía en retrieval.

Cubre los tres objetivos de la Fase 4 contra ChromaDB REAL (PersistentClient en
tempdir), sin red ni Ollama (mismo patrón de test_filtro_territorial_upl.py):

1. Metadatos v3 por chunk: `tema` (clasificación determinista), `estado`
   ("vigente"/"derogado") y `fecha_vigencia` garantizada.
2. Búsqueda híbrida: la fusión RRF recupera por la pata léxica un chunk que la
   pata vectorial pura pierde. Con `FakeEmbeddingFunctionPorPrimerToken` una
   consulta queda ORTOGONAL a los documentos que no comparten su primera
   palabra (similitud 0.0 < umbral 0.35): el vectorial solo no devuelve nada.
3. Reglas deterministas: derogados excluidos (con fallback downranked),
   jerarquía 555 > acto en empates de score, y determinismo extremo a extremo.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, patch

import chromadb
import pytest

from app.ingesta.corpus import (
    TEMA_DEFAULT,
    VERSION_ESQUEMA_METADATOS,
    clasificar_tema,
    estado_de_articulo,
    hash_documento,
    indexar_corpus,
    parsear_articulos,
)
from app.models import ArticuloNormativo, COLECCION_NORMATIVA
from app.providers.normativa import (
    NormativaProvider,
    _aplicar_reglas_vigencia_y_jerarquia,
    _fusion_rrf,
    _ordenar_por_jerarquia,
    _tokenizar,
)

# --- Corpus sintético del escenario híbrido ---
# El artículo 80 es el ÚNICO que contiene los términos de la consulta
# "estacionamientos obligatorios". Con la EF por primer token esa consulta es
# ortogonal a TODOS los documentos: la pata vectorial pura no devuelve nada y
# el art. 80 entra SOLO vía pata léxica + RRF.
HTML_SINTETICO_HIBRIDO = """\
LIBRO II
ARTÍCULO 10. Vías y espacio público.
Las vías y el espacio público se administran conforme a este plan.

LIBRO II
ARTÍCULO 20. Equipamientos.
Los equipamientos colectivos se localizan según la escala urbana.

LIBRO III
ARTÍCULO 30. Suelo urbano.
El suelo urbano se desarrolla conforme a las normas generales.

LIBRO III
ARTÍCULO 40. Vivienda.
La vivienda debe cumplir los estándares de habitabilidad.

LIBRO IV
ARTÍCULO 50. Suelo rural.
El suelo rural protege las actividades agropecuarias.

LIBRO IV
ARTÍCULO 60. Ambiente.
La gestión ambiental acompaña las decisiones de ordenamiento.

LIBRO VII
ARTÍCULO 70. Institucionalidad.
Las entidades distritales coordinan la implementación del plan.

LIBRO VII
ARTÍCULO 80. Estacionamientos obligatorios.
Toda edificación debe prever estacionamientos obligatorios y bicicleteros.
"""


class FakeEmbeddingFunctionPorPrimerToken:
    """One-hot sobre el primer token del texto (md5 → dimensión).

    Dos textos cuya PRIMERA palabra difiere quedan ortogonales: similitud
    coseno 0.0, por debajo del umbral 0.35 del provider. Así la pata vectorial
    solo recupera documentos que empiezan con la primera palabra de la
    consulta — control total sobre qué "ve" el vectorial.
    """

    model_name = "fake_primer_token"
    DIMS = 64

    def name(self) -> str:
        return self.model_name

    def _vector(self, texto: str) -> list[float]:
        vector = [0.0] * self.DIMS
        tokens = re.split(r"[^a-z0-9]+", texto.lower())
        if tokens and tokens[0]:
            dimension = int(hashlib.md5(tokens[0].encode()).hexdigest(), 16) % self.DIMS
            vector[dimension] = 1.0
        return vector

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return [self._vector(texto) for texto in input]

    def __call__(self, input: list[str]) -> list[list[float]]:
        return self.embed_query(input)


def _articulo_acto(
    numero: int,
    titulo: str,
    texto: str,
    estado_documento: Literal["vigente", "derogado"] | None = None,
) -> ArticuloNormativo:
    """Artículo de un acto modificatorio (Decreto 122 de 2023) para tests."""
    return ArticuloNormativo(
        numero=numero,
        titulo=titulo,
        texto=texto,
        libro="I",
        norma_id="Decreto_122_2023",
        tipo_norma="decreto",
        numero_norma=122,
        año=2023,
        fecha_vigencia="2023-03-31",
        titulo_norma="Decreto 122 de 2023",
        estado_documento=estado_documento,
    )


def _corpus_vigencia() -> list[ArticuloNormativo]:
    """555 (2 arts vigentes) + acto con 1 art derogado y 1 vigente.

    Los artículos 233 (555) y 4 (acto derogado) empiezan con "Vivienda": la
    consulta "vivienda colectiva" los alcanza VECTORIALMENTE por igual.
    """
    html_555 = """\
LIBRO III
ARTÍCULO 233. Vivienda colectiva.
Vivienda colectiva define requisitos urbanisticos.

LIBRO III
ARTÍCULO 243. Estándares de vivienda.
Estándares de vivienda garantizan habitabilidad.
"""
    return [
        *parsear_articulos(html_555),
        _articulo_acto(
            4,
            "Vivienda colectiva.",
            "Vivienda colectiva define requisitos urbanisticos.",
            "derogado",
        ),
        _articulo_acto(9, "Bicicleteros.", "Los bicicleteros acompanan la vivienda."),
        # Derogado que empieza con "Bicicleteros": la consulta "bicicleteros"
        # lo alcanza VECTORIALMENTE y a él solo → escenario de fallback.
        _articulo_acto(
            11,
            "Bicicleteros obligatorios.",
            "Bicicleteros obligatorios en vivienda colectiva.",
            "derogado",
        ),
    ]


def _indexar(corpus: list[ArticuloNormativo], chroma_path: Path, ef=None):
    return indexar_corpus(corpus, str(chroma_path), ef or FakeEmbeddingFunctionPorPrimerToken())


async def _consultar(chroma_path: Path, consulta: str, top_k: int = 3) -> dict:
    """Ejecuta provider.consultar con LLM y healthcheck mockeados.

    La respuesta simulada cita el PRIMER artículo recuperado para pasar el
    citation forcing (FR-003) sin acoplar el test a números fijos.
    """

    async def _respuesta_con_primera_cita(consulta, chunks, articulos_permitidos=None):
        return f"Según el Artículo {chunks[0].articulo}, procede."

    provider = NormativaProvider(ruta_indice=str(chroma_path))
    provider._embedding_function = FakeEmbeddingFunctionPorPrimerToken()  # pyright: ignore[reportAttributeAccessIssue]
    with patch.object(
        NormativaProvider, "_verificar_ollama_chat", new=AsyncMock()
    ), patch.object(
        NormativaProvider,
        "_generar_respuesta_llm",
        new=AsyncMock(side_effect=_respuesta_con_primera_cita),
    ):
        respuesta = await provider.consultar(consulta=consulta, top_k=top_k)
    await provider.aclose()
    return respuesta


# --- Objetivo 1: metadatos tema/estado/fecha_vigencia (esquema v3) ---


def test_version_esquema_metadatos_es_3():
    """El bump a "3" fuerza el rebuild automático del índice real al re-indexar."""
    assert VERSION_ESQUEMA_METADATOS == "3"


def test_clasificar_tema_mapeo_determinista():
    """Cada tema del mapeo explícito se asigna por el título; default general."""
    casos = [
        ("Usos del suelo en UPL17.", "usos_suelo"),
        ("Tratamiento urbanístico de renovación urbana.", "usos_suelo"),
        ("Índice de ocupación del suelo.", "edificabilidad"),
        ("Edificabilidad y constructibilidad.", "edificabilidad"),
        ("Espacio público eficiente.", "espacio_publico"),
        ("Parques metropolitanos.", "espacio_publico"),
        ("Viabilidad urbanística.", "viabilidad"),
        ("Licencias de construcción.", "viabilidad"),
        ("Procedimiento administrativo sancionatorio.", "procedimientos"),
        ("Recursos contra los actos.", "procedimientos"),
        ("Desafíos del ordenamiento territorial.", TEMA_DEFAULT),
    ]
    for titulo, esperado in casos:
        articulo = ArticuloNormativo(numero=1, titulo=titulo, texto="t", libro="II")
        assert clasificar_tema(articulo) == esperado, titulo


def test_estado_de_articulo_deriva_del_documento():
    """Acto con banner H7 → derogado; 555 (sin estado) → vigente."""
    derogado = _articulo_acto(4, "Vivienda colectiva.", "texto", "derogado")
    vigente_555 = ArticuloNormativo(numero=233, titulo="Vivienda.", texto="t", libro="III")
    assert estado_de_articulo(derogado) == "derogado"
    assert estado_de_articulo(vigente_555) == "vigente"
    # Un acto sin banner (None) también es vigente.
    assert estado_de_articulo(_articulo_acto(5, "Otro.", "t")) == "vigente"


def test_indexar_persiste_tema_estado_y_fecha_vigencia(tmp_path):
    """Los chunks llevan tema/estado/fecha_vigencia en la metadata REAL de ChromaDB."""
    corpus = [
        *parsear_articulos(HTML_SINTETICO_HIBRIDO),
        _articulo_acto(4, "Vivienda colectiva.", "Regula vivienda.", "derogado"),
    ]
    _indexar(corpus, tmp_path)

    cliente = chromadb.PersistentClient(path=str(tmp_path))
    coleccion = cliente.get_collection(COLECCION_NORMATIVA)

    meta_555 = coleccion.get(ids=["art-010"])["metadatas"][0]  # pyright: ignore[reportOptionalSubscript]
    assert meta_555["tema"] == "espacio_publico"
    assert meta_555["estado"] == "vigente"
    assert meta_555["fecha_vigencia"] == "2021-12-30"

    meta_acto = coleccion.get(ids=["Decreto_122_2023-art-004"])["metadatas"][0]  # pyright: ignore[reportOptionalSubscript]
    assert meta_acto["estado"] == "derogado"
    assert meta_acto["fecha_vigencia"] == "2023-03-31"

    # Todo chunk del índice lleva las tres claves pobladas (esquema v3).
    metadatas = coleccion.get()["metadatas"]
    assert metadatas is not None
    for metadata in metadatas:
        assert metadata["tema"]
        assert metadata["estado"] in {"vigente", "derogado"}
        assert metadata["fecha_vigencia"]


def test_hash_corpus_estable_con_campos_v3():
    """Añadir estado_documento al modelo NO altera la huella canónica (FR-012)."""
    corpus = parsear_articulos(HTML_SINTETICO_HIBRIDO)
    hash_base = hash_documento(corpus)
    corpus_con_estado = [
        articulo.model_copy(update={"estado_documento": "vigente"}) for articulo in corpus
    ]
    assert hash_documento(corpus_con_estado) == hash_base


# --- Funciones puras del híbrido: fusión RRF y reglas ---


def _chunk_de_prueba(
    id_chunk: str,
    similitud: float = 0.0,
    score_hibrido: float | None = None,
    norma_id: str | None = None,
    fecha_vigencia: str | None = None,
    estado: str | None = None,
):
    """ChunkRecuperado mínimo para ejercitar las funciones puras del híbrido."""
    from app.providers.normativa import ChunkRecuperado

    return ChunkRecuperado(
        id=id_chunk,
        articulo=1,
        titulo="t",
        libro="III",
        parte="urbano",
        texto="texto",
        similitud=similitud,
        norma_id=norma_id,
        fecha_vigencia=fecha_vigencia,
        estado=estado,
        score_hibrido=score_hibrido,
    )


def test_tokenizar_normaliza_tildes_y_descarta_cortos():
    assert _tokenizar("Estacionamientos Obligatorios en la Vía") == [
        "estacionamientos",
        "obligatorios",
        "via",
    ]


def test_fusion_rrf_combina_rankings_y_asigna_score_hibrido():
    vector = [_chunk_de_prueba("b", 0.9), _chunk_de_prueba("c", 0.8)]
    keyword = [_chunk_de_prueba("a"), _chunk_de_prueba("b", 0.9)]
    fusionados = _fusion_rrf(vector, keyword)

    puntajes = {c.id: c.score_hibrido for c in fusionados}
    # "b" aparece en ambas patas (rank 1 vectorial + rank 2 léxico): gana.
    assert puntajes["b"] is not None and puntajes["a"] is not None
    assert puntajes["b"] > puntajes["a"] > 0.0
    assert set(puntajes) == {"a", "b", "c"}


def test_ordenar_por_jerarquia_555_primero_en_empate():
    """Con score empatado, el Decreto 555 precede al acto modificatorio."""
    chunk_555 = _chunk_de_prueba("art-233")
    chunk_acto = _chunk_de_prueba("Decreto_122_2023-art-004", norma_id="Decreto_122_2023")
    orden = _ordenar_por_jerarquia([chunk_acto, chunk_555])
    assert [c.id for c in orden] == ["art-233", "Decreto_122_2023-art-004"]


def test_ordenar_por_jerarquia_fecha_reciente_rompe_segundo_empate():
    """Entre dos actos empatados, gana la fecha_vigencia más reciente."""
    viejo = _chunk_de_prueba("Decreto_100_2000-art-001", fecha_vigencia="2000-02-01")
    nuevo = _chunk_de_prueba("Decreto_122_2023-art-002", fecha_vigencia="2023-03-31")
    orden = _ordenar_por_jerarquia([viejo, nuevo])
    assert orden[0].id == "Decreto_122_2023-art-002"


def test_reglas_excluyen_derogados_y_aplican_fallback_downranked():
    vigente_1 = _chunk_de_prueba("art-001", estado="vigente", score_hibrido=0.05)
    derogado = _chunk_de_prueba(
        "acto-art-004", estado="derogado", score_hibrido=0.04
    )
    vigente_2 = _chunk_de_prueba("art-002", estado="vigente", score_hibrido=0.03)

    # Con cupo para todos los vigentes, el derogado queda fuera.
    seleccion = _aplicar_reglas_vigencia_y_jerarquia(
        [derogado, vigente_1, vigente_2], top_k=2
    )
    assert [c.id for c in seleccion] == ["art-001", "art-002"]

    # Sin vigentes suficientes, el derogado entra AL FINAL (fallback).
    seleccion_fallback = _aplicar_reglas_vigencia_y_jerarquia(
        [derogado, vigente_1], top_k=2
    )
    assert [c.id for c in seleccion_fallback] == ["art-001", "acto-art-004"]

    # Solo derogados disponibles: se devuelven (mejor eso que nada).
    solo_derogados = _aplicar_reglas_vigencia_y_jerarquia([derogado], top_k=3)
    assert [c.id for c in solo_derogados] == ["acto-art-004"]


# --- Objetivo 2: búsqueda híbrida extremo a extremo (ChromaDB real) ---


@pytest.mark.asyncio
async def test_vectorial_puro_pierde_todos_los_chunks_del_escenario(tmp_path):
    """Baseline: con la EF por primer token, la pata vectorial sola no trae NADA.

    Se aplica el MISMO umbral del provider (`_procesar_resultados`): la query
    cruda de ChromaDB siempre devuelve vecinos, pero todos quedan por debajo
    de UMBRAL_SIMILITUD_DEFAULT al ser ortogonales a la consulta.
    """
    chroma_path = tmp_path / "chroma"
    ef = FakeEmbeddingFunctionPorPrimerToken()
    _indexar(parsear_articulos(HTML_SINTETICO_HIBRIDO), chroma_path, ef)

    cliente = chromadb.PersistentClient(path=str(chroma_path))
    coleccion = cliente.get_collection(COLECCION_NORMATIVA, embedding_function=ef)  # pyright: ignore[reportArgumentType]
    resultados = coleccion.query(query_texts=["estacionamientos obligatorios"], n_results=6)

    provider = NormativaProvider(ruta_indice=str(chroma_path))
    provider._embedding_function = ef  # pyright: ignore[reportAttributeAccessIssue]
    assert provider._procesar_resultados(dict(resultados), None) == []  # pyright: ignore[reportArgumentType]
    await provider.aclose()


@pytest.mark.asyncio
async def test_hibrido_recupera_por_keyword_lo_que_el_vectorial_pierde(tmp_path):
    """La fusión RRF incorpora el art. 80 en el top_k final."""
    chroma_path = tmp_path / "chroma"
    _indexar(parsear_articulos(HTML_SINTETICO_HIBRIDO), chroma_path)

    resp = await _consultar(chroma_path, "estacionamientos obligatorios", top_k=2)

    assert resp["sin_resultados"] is False
    articulos = {r["articulo"] for r in resp["resultados"]}
    assert 80 in articulos
    # Campos aditivos Fase 4 por ítem.
    assert all(r["score_hibrido"] is not None for r in resp["resultados"])
    assert all(r["tema"] and r["estado"] for r in resp["resultados"])


@pytest.mark.asyncio
async def test_hibrido_es_determinista(tmp_path):
    """Dos consultas idénticas producen exactamente los mismos resultados (SC-003)."""
    chroma_path = tmp_path / "chroma"
    _indexar(parsear_articulos(HTML_SINTETICO_HIBRIDO), chroma_path)

    resp_1 = await _consultar(chroma_path, "estacionamientos obligatorios", top_k=3)
    resp_2 = await _consultar(chroma_path, "estacionamientos obligatorios", top_k=3)

    assert resp_1["resultados"] == resp_2["resultados"]


# --- Objetivo 3: reglas de vigencia y jerarquía extremo a extremo ---


@pytest.mark.asyncio
async def test_derogados_excluidos_cuando_hay_vigentes_suficientes(tmp_path):
    """El acto derogado matchea fuerte pero se excluye si los vigentes alcanzan."""
    chroma_path = tmp_path / "chroma"
    _indexar(_corpus_vigencia(), chroma_path)

    resp = await _consultar(chroma_path, "vivienda colectiva", top_k=3)

    estados = {r["articulo"]: r["estado"] for r in resp["resultados"]}
    assert "derogado" not in estados.values()
    assert 233 in estados  # el 555 vigente sigue presente
    assert 4 not in estados  # el acto derogado quedó fuera


@pytest.mark.asyncio
async def test_derogado_unico_match_entra_como_fallback(tmp_path):
    """Si los vigentes no alcanzan, el derogado entra AL FINAL (fallback).

    La consulta "bicicleteros" solo alcanza vectorialmente al art. 11
    (derogado) y léxicamente a los arts. 9 (vigente) y 11: el vigente va
    primero y el derogado completa el cupo como fallback downranked.
    """
    chroma_path = tmp_path / "chroma"
    _indexar(_corpus_vigencia(), chroma_path)

    resp = await _consultar(chroma_path, "bicicleteros", top_k=3)

    assert resp["sin_resultados"] is False
    resultados = resp["resultados"]
    assert {r["articulo"]: r["estado"] for r in resultados} == {
        9: "vigente",
        11: "derogado",
    }
    # El derogado queda DOWNRANKED: después del vigente.
    orden = [r["articulo"] for r in resultados]
    assert orden.index(9) < orden.index(11)


@pytest.mark.asyncio
async def test_jerarquia_555_y_acto_coexisten_en_la_misma_materia(tmp_path):
    """555 y acto que cubren la misma materia: ambos aparecen, ninguno oculto."""
    chroma_path = tmp_path / "chroma"
    _indexar(_corpus_vigencia(), chroma_path)

    resp = await _consultar(chroma_path, "vivienda colectiva requisitos", top_k=6)

    normas = [r["norma"] for r in resp["resultados"]]
    assert "Decreto 555 de 2021" in normas
    assert "Decreto 122 de 2023" in normas
