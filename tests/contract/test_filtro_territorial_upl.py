"""Contract tests del filtro territorial FR-002 contra ChromaDB REAL.

Los mocks de `test_consultar_normativa.py` no ejercitan la semantica real de
los operadores de ChromaDB: por eso no detectaron que `$contains` sobre un
string CSV nunca matcheaba (bug FR-002). Estos tests usan ChromaDB real
(EphemeralClient o PersistentClient en tempdir), sin red ni Ollama.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import chromadb
import pytest

from app.ingesta.corpus import (
    VERSION_ESQUEMA_METADATOS,
    _huella_por_documento,
    _motivo_reconstruccion,
    chunk_articulo,
    indexar_corpus,
    parsear_articulos,
)
from app.models import (
    COLECCION_NORMATIVA,
    METADATA_CORPUS_SHA256,
    METADATA_EMBEDDING_MODEL,
    METADATA_ESQUEMA_METADATOS,
)
from app.providers.normativa import NormativaProvider
from app.providers.upl import (
    NOMBRE_UPL_A_LOCALIDAD,
    PARTES_POR_UPL,
    UPLS_BOGOTA,
    construir_filtro_territorial,
    partes_aplicables,
)


HTML_SINTETICO_FR002 = """\
LIBRO II
ARTÍCULO 1. Usos del suelo en UPL17.
El presente artículo regula los usos del suelo en la UPL17. Permite vivienda y comercio.

LIBRO III
ARTÍCULO 2. Normas urbanas.
Este artículo establece normas urbanas generales. Define alturas máximas.

LIBRO VII
ARTÍCULO 3. Disposición administrativa.
Ninguna referencia territorial aparece en este artículo.

LIBRO VII
ARTÍCULO 4. Regla especial para la UPL17.
La UPL17 tiene reglas especiales aunque el artículo no tenga parte derivada.
"""


class FakeEmbeddingFunctionConstante:
    """Embedding constante: toda consulta recupera los chunks con similitud 1.0."""

    model_name = "fake_constante"
    VECTOR = [1.0 / (1024 ** 0.5)] * 1024

    def name(self) -> str:
        return self.model_name

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return [list(self.VECTOR) for _ in input]

    def __call__(self, input: list[str]) -> list[list[float]]:
        return self.embed_query(input)


# --- Fase B: tabla estatica de las 33 UPLs y PARTES_POR_UPL ---


def test_upls_bogota_cubre_las_33_upls_con_vocacion_real():
    """La capa ArcGIS canonica tiene exactamente 33 features UPL01–UPL33."""
    assert len(UPLS_BOGOTA) == 33
    assert set(UPLS_BOGOTA) == {f"UPL{i:02d}" for i in range(1, 34)}
    for registro in UPLS_BOGOTA.values():
        assert set(registro) == {"nombre", "localidad", "vocacion"}
        assert registro["vocacion"] in {"Urbano", "Urbano-Rural", "Rural"}


def test_partes_por_upl_deriva_de_la_vocacion():
    """Urbano -> urbano+general; Rural -> rural+general; Urbano-Rural -> ambas+general."""
    assert PARTES_POR_UPL["UPL17"] == ["urbano", "general"]  # Bosa, Urbano
    assert PARTES_POR_UPL["UPL01"] == ["rural", "general"]  # Sumapáz, Rural
    # Vocación mixta: artículos pueden vivir en la Parte III o en la IV.
    assert PARTES_POR_UPL["UPL13"] == ["urbano", "rural", "general"]  # Tintal


def test_partes_aplicables_devuelve_copia_y_falla_con_upl_desconocida():
    partes = partes_aplicables("upl02")
    assert partes == ["rural", "general"]
    partes.append("urbano")  # mutar el retorno no corrompe la tabla
    assert PARTES_POR_UPL["UPL02"] == ["rural", "general"]

    with pytest.raises(ValueError, match="UPL desconocida"):
        partes_aplicables("UPL99")


def test_construir_filtro_territorial_upl_desconocida():
    """Fail loud directo: una UPL fuera del catalogo no produce filtro silencioso."""
    with pytest.raises(ValueError, match="UPL desconocida"):
        construir_filtro_territorial("UPL99")


def test_mapeo_nombre_a_localidad_derivado_de_upls_bogota():
    """NOMBRE_UPL_A_LOCALIDAD cubre las 33 UPLs reales (claves sin tildes)."""
    assert len(NOMBRE_UPL_A_LOCALIDAD) == 33
    assert NOMBRE_UPL_A_LOCALIDAD["SUMAPAZ"] == "Sumapaz"
    assert NOMBRE_UPL_A_LOCALIDAD["BARRIOS UNIDOS"] == "Barrios Unidos"
    # La capa trae nombres acentuados ("Engativá"): la clave se normaliza.
    assert NOMBRE_UPL_A_LOCALIDAD["ENGATIVA"] == "Engativa"


# --- Fase A: semantica REAL del filtro compuesto sobre ChromaDB ---


@pytest.fixture
def coleccion_memoria():
    """Coleccion efimera real con chunks de todas las combinaciones parte/upls."""
    cliente = chromadb.EphemeralClient()
    nombre = f"fr002_{uuid4().hex}"
    coleccion = cliente.create_collection(nombre)
    coleccion.add(
        ids=["c1", "c2", "c3", "c4", "c5", "c6"],
        documents=["t1", "t2", "t3", "t4", "t5", "t6"],
        metadatas=[
            {"parte": "urbano"},  # urbano sin mencion
            {"parte": "general"},  # general sin mencion
            {"parte": "rural"},  # rural sin mencion
            {"parte": ""},  # sin parte derivada, sin mencion
            {"upls": ["UPL01"]},  # sin parte PERO menciona UPL01
            {"parte": "urbano", "upls": ["UPL17"]},  # urbano que menciona otra UPL
        ],
    )
    yield coleccion
    cliente.delete_collection(coleccion.name)


def test_filtro_upl_rural_sumapaz_recibe_rural_general_y_mencion(coleccion_memoria):
    """UPL01 Sumapáz (Rural): recupera rural + general + mencion explicita."""
    where = construir_filtro_territorial("UPL01")
    recuperados = set(coleccion_memoria.get(where=where)["ids"])
    assert recuperados == {"c2", "c3", "c5"}
    # Quedan fuera: urbano sin mencion (c1), sin parte y sin mencion (c4),
    # urbano que menciona otra UPL (c6).


def test_filtro_upl_urbana_recupera_urbano_general_y_mencion(coleccion_memoria):
    """UPL17 Bosa (Urbano): recupera urbano + general + mencion explicita."""
    where = construir_filtro_territorial("UPL17")
    recuperados = set(coleccion_memoria.get(where=where)["ids"])
    assert recuperados == {"c1", "c2", "c6"}


def test_contains_sobre_metadata_csv_esta_muerto(coleccion_memoria):
    """El bug historico, reproducido contra ChromaDB real.

    Con `upls` guardado como string CSV ("UPL01,UPL17"), `$contains` jamas
    matcheaba: la consulta devolvia 0 resultados SIEMPRE. Con list[str] real
    la membresia exacta funciona.
    """
    coleccion_memoria.add(
        ids=["csv1"], documents=["legacy"], metadatas=[{"upls": "UPL01,UPL17"}]
    )
    recuperados = coleccion_memoria.get(where={"upls": {"$contains": "UPL01"}})["ids"]
    assert "csv1" not in recuperados
    assert recuperados == ["c5"]


# --- Fase A: extremo a extremo a traves del provider RAG (indice real) ---


def _indexar_fr002(chroma_path: Path):
    corpus = parsear_articulos(HTML_SINTETICO_FR002)
    info = indexar_corpus(corpus, str(chroma_path), FakeEmbeddingFunctionConstante())
    return corpus, info


@pytest.mark.asyncio
async def test_consultar_con_upl_recupera_parte_aplicable_y_mencion_explicita():
    """Bug CSV muerto, demostracion extremo a extremo.

    Con el filtro roto (`$contains` sobre CSV) esta consulta devolvia SIEMPRE
    0 resultados. Ahora recupera: art 1 (general), art 2 (urbano) y art 4
    (sin parte pero que menciona UPL17); el art 3 queda fuera.
    """
    with tempfile.TemporaryDirectory() as tmp:
        chroma_path = Path(tmp) / "chroma"
        corpus, _ = _indexar_fr002(chroma_path)

        provider = NormativaProvider(ruta_indice=str(chroma_path))
        provider._embedding_function = FakeEmbeddingFunctionConstante()
        with patch.object(
            NormativaProvider, "_verificar_ollama_chat", new=AsyncMock()
        ), patch.object(
            NormativaProvider,
            "_generar_respuesta_llm",
            new=AsyncMock(return_value="Según el Artículo 1, se permite vivienda."),
        ):
            resp = await provider.consultar(consulta="usos del suelo", upl="UPL17", top_k=6)
        await provider.aclose()

    assert resp["sin_resultados"] is False
    articulos = {r["articulo"] for r in resp["resultados"]}
    assert articulos == {1, 2, 4}
    partes = {r["articulo"]: r["parte"] for r in resp["resultados"]}
    assert partes[1] == "general"
    assert partes[2] == "urbano"


@pytest.mark.asyncio
async def test_consultar_sin_upl_no_aplica_filtro_territorial():
    """Sin `upl` no hay filtro territorial: los 4 articulos son candidatos."""
    with tempfile.TemporaryDirectory() as tmp:
        chroma_path = Path(tmp) / "chroma"
        _indexar_fr002(chroma_path)

        provider = NormativaProvider(ruta_indice=str(chroma_path))
        provider._embedding_function = FakeEmbeddingFunctionConstante()
        with patch.object(
            NormativaProvider, "_verificar_ollama_chat", new=AsyncMock()
        ), patch.object(
            NormativaProvider,
            "_generar_respuesta_llm",
            new=AsyncMock(return_value="Según el Artículo 1, se permite vivienda."),
        ):
            resp = await provider.consultar(consulta="normas", top_k=6)
        await provider.aclose()

    assert {r["articulo"] for r in resp["resultados"]} == {1, 2, 3, 4}


@pytest.mark.asyncio
async def test_validacion_upl_invalida_se_mantiene():
    """La validacion fail-fast de UPL mal formada no cambia con el nuevo filtro."""
    with tempfile.TemporaryDirectory() as tmp:
        chroma_path = Path(tmp) / "chroma"
        _indexar_fr002(chroma_path)

        provider = NormativaProvider(ruta_indice=str(chroma_path))
        provider._embedding_function = FakeEmbeddingFunctionConstante()
        with pytest.raises(ValueError, match="UPL desconocida"):
            await provider.consultar(consulta="normas", upl="UPL99")
        await provider.aclose()


# --- Fase A: reconstruccion del indice por cambio de esquema de metadatos ---


def test_motivo_reconstruccion_detecta_esquema_de_metadatos_distinto():
    """Un indice v1 (o sin version) reconstruye aunque el hash del corpus no cambie."""
    corpus = parsear_articulos(HTML_SINTETICO_FR002)
    huella = _huella_por_documento(corpus, {})
    metadata_vigente = {
        METADATA_EMBEDDING_MODEL: "fake_constante",
        METADATA_ESQUEMA_METADATOS: VERSION_ESQUEMA_METADATOS,
    }
    metadata_legacy = {
        METADATA_EMBEDDING_MODEL: "fake_constante",
        METADATA_ESQUEMA_METADATOS: "1",
    }

    assert _motivo_reconstruccion(metadata_legacy, "fake_constante", huella) is not None
    assert "esquema" in _motivo_reconstruccion(metadata_legacy, "fake_constante", huella)
    # Indice vigente (mismo modelo, mismo esquema, mismos hashes): flujo aditivo.
    assert _motivo_reconstruccion(metadata_vigente, "fake_constante", huella) is None
    # Indice sin la clave (creado antes de versionar el esquema): reconstruye.
    sin_clave = {METADATA_EMBEDDING_MODEL: "fake_constante"}
    assert "esquema" in _motivo_reconstruccion(sin_clave, "fake_constante", huella)


def test_indexar_reconstruye_indice_con_esquema_metadatos_legado(tmp_path):
    """Un indice v1 con documentos ajenos se reconstruye: no sobrevive el legado."""
    chroma_path = tmp_path / "chroma"
    cliente = chromadb.PersistentClient(path=str(chroma_path))
    legado = cliente.create_collection(
        COLECCION_NORMATIVA,
        embedding_function=FakeEmbeddingFunctionConstante(),
        metadata={
            METADATA_EMBEDDING_MODEL: "fake_constante",
            METADATA_CORPUS_SHA256: "hash-viejo",
        },
    )
    legado.upsert(ids=["legado-1"], documents=["chunk viejo"], metadatas=[{"articulo": 999}])

    corpus = parsear_articulos(HTML_SINTETICO_FR002)
    indexar_corpus(corpus, str(chroma_path), FakeEmbeddingFunctionConstante())

    reconstruida = cliente.get_collection(COLECCION_NORMATIVA)
    assert reconstruida.metadata[METADATA_ESQUEMA_METADATOS] == VERSION_ESQUEMA_METADATOS
    ids = reconstruida.get()["ids"]
    assert "legado-1" not in ids
    assert len(ids) == sum(len(chunk_articulo(a)) for a in corpus)


def test_indexar_flujo_aditivo_con_esquema_vigente_no_reconstruye(tmp_path):
    """Con el esquema vigente, re-indexar el mismo corpus es aditivo (FR-008 E7)."""
    chroma_path = tmp_path / "chroma"
    corpus = parsear_articulos(HTML_SINTETICO_FR002)
    indexar_corpus(corpus, str(chroma_path), FakeEmbeddingFunctionConstante())

    # Documento ajeno al corpus: si hubiera reconstruccion, desapareceria.
    cliente = chromadb.PersistentClient(path=str(chroma_path))
    coleccion = cliente.get_collection(
        COLECCION_NORMATIVA, embedding_function=FakeEmbeddingFunctionConstante()
    )
    coleccion.upsert(ids=["externo-1"], documents=["externo"], metadatas=[{"articulo": 998}])

    indexar_corpus(corpus, str(chroma_path), FakeEmbeddingFunctionConstante())

    ids = cliente.get_collection(
        COLECCION_NORMATIVA, embedding_function=FakeEmbeddingFunctionConstante()
    ).get()["ids"]
    assert "externo-1" in ids
