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

# Formato real de sisjur (HTML exportado por Word): artículo 1 con ancla
# (`id="1"`, el número NO va inline), artículo 2 con número inline ("Artículo 2."),
# título multilínea con tags, y una referencia interna falsa ("artículo 5 de la
# Ley X" sin punto) que NO debe crear un artículo 5. El LIBRO II (ancla "L.2")
# está antes del artículo 2 para probar la proximidad de libro/parte.
HTML_SISJUR = """\
<body>
<p class="MsoNormal" style="text-align:justify">
<b><span lang="ES" style="color:black">Artículo</span></b>
<span style="font-size: 12pt;" class="ancla" id="1"></span>
<b><span lang="ES" style="color:black">1. </span></b>
<b><span lang="ES">Título del
primer artículo en varias líneas.</span></b>
<span lang="ES">Cuerpo del artículo uno con <b>negrita</b> y enlaces.</span>
</p>
<p class="MsoNormal"><b>LIBRO<span class="ancla" id="L.2"></span>&nbsp;II</b></p>
<p class="MsoNormal" style="text-align:justify">
<b><span lang="ES" style="color:black">Artículo 2.</span></b>
<b><span lang="ES">Normas urbanas en UPL 20.</span></b>
<span lang="ES">Cuerpo del artículo dos; cita al artículo 5 de la Ley X sin punto y a la UPL 20.</span>
</p>
</body>
"""

# Frontera contaminante del formato real: el encabezado del artículo 2 separa la
# palabra "Artículo" en un grupo <b> propio ANTES de su ancla. Sin el ajuste de
# frontera (FIX 1), esa palabra suelta caería al final del cuerpo del artículo 1.
HTML_SISJUR_BORDE = """\
<body>
<p class="MsoNormal" style="text-align:justify">
<span style="font-size: 12pt;" class="ancla" id="1"></span>
<b><span lang="ES">1. </span></b>
<b><span lang="ES">Título del primer artículo.</span></b>
<span lang="ES">Cuerpo del primer artículo con frontera limpia.</span>
</p>
<p class="MsoNormal" style="text-align:justify">
<b><span lang="ES" style="color:black">Artículo</span></b>
<span style="font-size: 12pt;" class="ancla" id="2"></span>
<b><span lang="ES">2. </span></b>
<b><span lang="ES">Título del segundo artículo.</span></b>
<span lang="ES">Cuerpo del segundo artículo.</span>
</p>
</body>
"""

# Punto final del título FUERA del grupo <b> (queda entre el título y el cuerpo):
# sin el ajuste (FIX 2), el cuerpo arrancaría con un "." huérfano.
HTML_SISJUR_PUNTO_FUERA = """\
<body>
<p class="MsoNormal" style="text-align:justify">
<span style="font-size: 12pt;" class="ancla" id="1"></span>
<b><span lang="ES">1. </span></b>
<b><span lang="ES">Título con punto fuera del grupo</span></b>.
<span lang="ES">Cuerpo del artículo con punto huérfano.</span>
</p>
</body>
"""

# Pie de página real de sisjur: <script> con gtag/dataLayer/UA- y <style> caen
# dentro del rango del último artículo; sin el ajuste (FIX 3) contaminan el cuerpo.
HTML_SISJUR_SCRIPT = """\
<body>
<p class="MsoNormal" style="text-align:justify">
<span style="font-size: 12pt;" class="ancla" id="1"></span>
<b><span lang="ES">1. </span></b>
<b><span lang="ES">Artículo con pie de página.</span></b>
<span lang="ES">Cuerpo del artículo.</span>
</p>
<script type="text/javascript">
  $(document).ready(function() {
    gtag('config', 'UA-129457683-1');
    dataLayer.push({event: 'pageview'});
  });
</script>
<style>p { color: red; }</style>
</body>
"""

# Ancla detectada pero sin ningún grupo <b> con el número del artículo: el título
# es irrecuperable y el parser debe fallar rápido (FIX 6), no devolver ("", inicio).
HTML_SISJUR_SIN_TITULO = """\
<body>
<p class="MsoNormal" style="text-align:justify">
<span style="font-size: 12pt;" class="ancla" id="1"></span>
<span lang="ES">Cuerpo sin grupo de número en negrita.</span>
</p>
</body>
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


class FakeEmbeddingFunctionConLimite(FakeEmbeddingFunction):
    """EF que aborta si una sola llamada recibe más de `max_por_llamada` textos.

    Verifica que el upsert se particiona: sin batching, ChromaDB pasaría todos
    los chunks de una vez y esta EF lanzaría AssertionError.
    """

    def __init__(self, max_por_llamada: int, model_name: str = "fake"):
        super().__init__(model_name=model_name)
        self.max_por_llamada = max_por_llamada

    def __call__(self, input: list[str]) -> list[list[float]]:
        if len(input) > self.max_por_llamada:
            raise AssertionError(
                f"El EF recibió {len(input)} documentos en una sola llamada; "
                f"máximo permitido {self.max_por_llamada}"
            )
        return super().__call__(input)


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


# --- Parseo del formato real de sisjur (Word exportado: anclas + inline) ---
# Fuente autoritativa del número: span `class="ancla" id="N"` unido a los
# encabezados inline "Artículo N." con punto. Las referencias internas sin
# punto ("artículo 5 de la Ley X") NO crean artículos.

def test_parsear_articulos_sisjur_ancla_e_inline():
    corpus = parsear_articulos(HTML_SISJUR)
    assert [a.numero for a in corpus] == [1, 2]
    # La referencia interna "artículo 5 de la Ley X" no genera un artículo 5.
    assert all(a.numero != 5 for a in corpus)
    assert len(corpus) == 2


def test_parsear_articulos_sisjur_titulo_limpio_multilinea():
    corpus = parsear_articulos(HTML_SISJUR)
    art1 = next(a for a in corpus if a.numero == 1)
    art2 = next(a for a in corpus if a.numero == 2)
    assert art1.titulo == "Título del primer artículo en varias líneas."
    assert art2.titulo == "Normas urbanas en UPL 20."
    # Títulos sin tags ni saltos internos (requisito B).
    for a in corpus:
        assert "<" not in a.titulo
        assert "\n" not in a.titulo


def test_parsear_articulos_sisjur_cuerpo_sin_tags():
    corpus = parsear_articulos(HTML_SISJUR)
    art1 = next(a for a in corpus if a.numero == 1)
    assert "<" not in art1.texto
    assert "Cuerpo del artículo uno con negrita y enlaces." in art1.texto


def test_parsear_articulos_sisjur_libro_por_proximidad():
    corpus = parsear_articulos(HTML_SISJUR)
    art1 = next(a for a in corpus if a.numero == 1)
    art2 = next(a for a in corpus if a.numero == 2)
    # Sin LIBRO previo el artículo 1 cae en el libro por defecto ("I"); el
    # artículo 2 hereda el LIBRO II vigente y su parte derivada.
    assert art1.libro == "I"
    assert art1.parte is None
    assert art2.libro == "II"
    assert art2.parte == "general"


def test_parsear_articulos_sisjur_upls_mencionadas():
    corpus = parsear_articulos(HTML_SISJUR)
    art2 = next(a for a in corpus if a.numero == 2)
    assert art2.upls_mencionadas == ["UPL20"]


def test_parsear_articulos_sisjur_ningun_cuerpo_termina_en_palabra_articulo():
    # Aserción de frontera sobre el fixture base: el cuerpo de ningún artículo
    # puede terminar en la palabra suelta "Artículo" del encabezado siguiente.
    corpus = parsear_articulos(HTML_SISJUR)
    for a in corpus:
        assert not a.texto.endswith("Artículo")
        assert not a.texto.rstrip().endswith("Artículo")


def test_parsear_articulos_sisjur_borde_recorta_articulo_siguiente():
    # El encabezado del artículo 2 usa el estilo real (`<b>Artículo</b>` + ancla):
    # sin el ajuste de frontera (FIX 1), el cuerpo del artículo 1 terminaría en la
    # palabra suelta "Artículo" y el cuerpo del artículo 2 empezaría con "2.".
    corpus = parsear_articulos(HTML_SISJUR_BORDE)
    assert [a.numero for a in corpus] == [1, 2]
    art1 = next(a for a in corpus if a.numero == 1)
    art2 = next(a for a in corpus if a.numero == 2)
    assert art1.texto == "Cuerpo del primer artículo con frontera limpia."
    assert "Artículo" not in art1.texto
    assert art2.texto == "Cuerpo del segundo artículo."


def test_parsear_articulos_sisjur_cuerpo_sin_punto_huerfano_inicial():
    # El punto final del título quedó fuera del grupo <b> (FIX 2): el cuerpo debe
    # arrancar directo con el texto, sin el "." huérfano.
    corpus = parsear_articulos(HTML_SISJUR_PUNTO_FUERA)
    art1 = corpus[0]
    assert art1.titulo == "Título con punto fuera del grupo"
    assert art1.texto == "Cuerpo del artículo con punto huérfano."
    assert not art1.texto.startswith(".")


def test_parsear_articulos_sisjur_elimina_script_y_style_del_cuerpo():
    # El pie de página inyecta <script> (gtag/dataLayer/UA-) y <style> dentro del
    # rango del último artículo (FIX 3): no deben quedar restos en el cuerpo.
    corpus = parsear_articulos(HTML_SISJUR_SCRIPT)
    art1 = corpus[0]
    assert art1.texto == "Cuerpo del artículo."
    for marca in ("gtag", "dataLayer", "UA-", "$(document", "ready", "<script", "<style"):
        assert marca not in art1.texto


def test_parsear_articulos_sisjur_upl_un_digito_normaliza_con_cero():
    # La fuente real menciona "UPL 2".."UPL 9" de un dígito y "UPL20" de dos
    # (FIX 4): todos se normalizan a la forma canónica de dos dígitos.
    html = """\
<body>
<p class="MsoNormal" style="text-align:justify">
<span style="font-size: 12pt;" class="ancla" id="1"></span>
<b><span lang="ES">1. </span></b>
<b><span lang="ES">Edificabilidad por UPL.</span></b>
<span lang="ES">Regula la edificabilidad UPL 2, UPL20 y UPL 33.</span>
</p>
</body>
"""
    corpus = parsear_articulos(html)
    art1 = corpus[0]
    assert art1.upls_mencionadas == ["UPL02", "UPL20", "UPL33"]


def test_parsear_articulos_sisjur_sin_titulo_raise_valueerror():
    # Ancla detectada pero sin grupo <b> con el número: Fail Fast (FIX 6), no un
    # título vacío silencioso.
    with pytest.raises(ValueError, match=r"No se encontró el título del marcador ancla 1"):
        parsear_articulos(HTML_SISJUR_SIN_TITULO)


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


# --- Particionado del upsert en batches (servidor Ollama remoto) ---
# El servidor real rechaza lotes grandes de embeddings; el test fuerza batch
# pequeño (3) e indexa ~8 chunks con un EF que aborta si recibe más de 3 textos
# por llamada: sin el particionado la prueba falla al primer upsert.

def test_indexar_corpus_particiona_upsert_en_batches(chroma_tempdir):
    # 4 artículos largos (~2 chunks cada uno = 8 chunks) y batch de 3: el EF
    # no puede recibir más de 3 documentos por llamada.
    html = "LIBRO II\n" + "\n".join(
        f"ARTÍCULO {i}. Artículo largo.\n" + ("Párrafo " + "x" * 100 + "\n") * 30
        for i in range(1, 5)
    )
    corpus = parsear_articulos(html)
    chunks = [c for a in corpus for c in chunk_articulo(a)]
    assert len(chunks) > 3  # sanity: el escenario realmente exige particionar

    ef = FakeEmbeddingFunctionConLimite(max_por_llamada=3)

    info = indexar_corpus(corpus, str(chroma_tempdir), ef, batch_tamano=3)

    cliente = chromadb.PersistentClient(path=str(chroma_tempdir))
    coleccion = cliente.get_collection(COLECCION_NORMATIVA)
    assert coleccion.count() == len(chunks)
    assert info.total_articulos == len(corpus)


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