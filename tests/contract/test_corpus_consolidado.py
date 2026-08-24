"""Contract tests para F4 — Corpus consolidado de actos modificatorios (tasks.md T012).

Cubre el registro y la escritura versionada del corpus consolidado
(contracts/ingesta-actos-modificatorios.md:80-129): JSONL + `.sha256` por acto
(FR-013), registro `.corpus_consolidado.json` con hash y metadatos por documento
(FR-002, FR-007, FR-008), re-ingesta duplicada -> no-op sin duplicar artículos ni
fragmentos (SC-003), validación FR-014 (rechazo `FECHA_ANTERIOR_AL_555`; acto sin
referencia -> se integra con `relacion_con_555="sin_referencia"`) y fallo atómico
por documento (FR-009, SC-006). La sección 9 cubre la re-indexación aditiva
(T017, FR-008, E7): tests RED hasta T020, cuando la indexación upsertará SOLO los
chunks del documento cambiado con ids `norma_id-art-<NNN>` y persistirá la huella
multi-documento en la metadata de la colección. Sin red real ni Ollama: solo
fixtures de `tests/conftest.py`, directorios temporales (`tmp_path`) y el
`FakeEmbeddingFunction` de F2 (`tests/contract/test_ingesta_f2.py`); nunca se
toca `data/`.
"""

from __future__ import annotations

import json
from pathlib import Path

import chromadb
import pytest

from app.ingesta.actos import (
    ErrorIngesta,
    escribir_documento_acto,
    extraer_articulos,
    extraer_articulos_referenciados,
    hash_archivo,
    leer_registro_corpus,
    marcar_documento_indexado,
    validar_relacion_con_555,
)
from app.ingesta.corpus import (
    deserializar_corpus,
    hash_documento,
    indexar_corpus,
    parsear_articulos,
)
from app.models import (
    ArticuloNormativo,
    COLECCION_NORMATIVA,
    DocumentoNormativo,
    FECHA_VIGENCIA_555,
    METADATA_EMBEDDING_MODEL,
)
from tests.conftest import (
    BANNER_DEROGACION_122,
    DECRETO_122_METADATA,
    DECRETO_122_TITULOS,
    REGISTRO_CORPUS_PRUEBA,
    entrada_registro_corpus,
    html_decreto_122,
)
from tests.contract.test_ingesta_f2 import FakeEmbeddingFunction, HTML_SINTETICO
from tests.conftest import (
    BANNER_DEROGACION_122,
    DECRETO_122_METADATA,
    DECRETO_122_TITULOS,
    REGISTRO_CORPUS_PRUEBA,
    entrada_registro_corpus,
    html_decreto_122,
)


@pytest.fixture
def contenido_html_122() -> bytes:
    """Bytes UTF-8 del HTML sisjur del Decreto 122 (fixture F4)."""
    return html_decreto_122().encode("utf-8")


@pytest.fixture
def articulos_122(contenido_html_122) -> list[ArticuloNormativo]:
    """Artículos del 122 extraídos del HTML sisjur (13, D4/H2)."""
    return extraer_articulos(contenido_html_122, "sisjur_html")


@pytest.fixture
def documento_122(contenido_html_122) -> DocumentoNormativo:
    """DocumentoNormativo canónico del 122 (mismo patrón que T011).

    Se construye desde DECRETO_122_METADATA + hash SHA-256 del ARCHIVO fuente
    (FR-007, SC-003) + `relacion_con_555` validada contra el 555 (FR-014).
    """
    referenciados = extraer_articulos_referenciados(html_decreto_122())
    return DocumentoNormativo(
        **DECRETO_122_METADATA,
        titulo="Decreto 122 de 2023",
        hash_sha256=hash_archivo(contenido_html_122),
        formato="sisjur_html",
        relacion_con_555=validar_relacion_con_555(
            DECRETO_122_METADATA["fecha_expedicion"], referenciados
        ),
        articulos_referenciados=referenciados,
        estado_documento="derogado",
        derogado_compilado_por=BANNER_DEROGACION_122,
    )


# --- 1. Registro ausente: estructura base vacía (FR-002) ---

def test_leer_registro_sin_archivo_devuelve_estructura_vacia(tmp_path):
    """Sin `.corpus_consolidado.json` -> estructura base con `documentos: []`.

    El registro es aditivo (FR-002): un corpus aún sin actos se declara con el
    documento base (Decreto_555_2021) y la lista vacía de documentos.
    """
    registro = leer_registro_corpus(tmp_path / "no_existe" / ".corpus_consolidado.json")
    assert registro == REGISTRO_CORPUS_PRUEBA


# --- 2. Escritura versionada: JSONL + `.sha256` por acto (FR-013) ---

def test_escribir_documento_acto_jsonl_y_sha256(
    tmp_path, contenido_html_122, articulos_122, documento_122
):
    """Cada acto produce `<documento_id>.jsonl` + `.jsonl.sha256` (FR-013).

    El JSONL tiene una línea por artículo; cada línea conserva los campos F2 del
    artículo y añade los metadatos de norma del contrato
    (contracts/ingesta-actos-modificatorios.md:86-101). El `.sha256` no está
    vacío y contiene la huella del documento (`hash_documento`).
    """
    ruta_registro = tmp_path / ".corpus_consolidado.json"
    directorio_salida = tmp_path / "actos"

    salida = escribir_documento_acto(
        contenido_html_122,
        documento_122,
        articulos_122,
        ruta_registro=ruta_registro,
        directorio_salida=directorio_salida,
    )
    # Shape de éxito del contrato (contract:38-55).
    assert salida["duplicado"] is False
    assert salida["documento_id"] == "Decreto_122_2023"
    assert salida["hash_sha256"] == hash_archivo(contenido_html_122)
    assert salida["articulos"] == 13
    assert salida["relacion_con_555"] == "referencia_articulos"
    assert salida["articulos_referenciados"] == [233, 243, 384]

    jsonl = directorio_salida / "Decreto_122_2023.jsonl"
    sha = directorio_salida / "Decreto_122_2023.jsonl.sha256"
    assert jsonl.exists()
    assert sha.exists()
    huella_sha = sha.read_text(encoding="utf-8").strip()
    assert huella_sha
    assert huella_sha == hash_documento(articulos_122)

    lineas = [
        json.loads(linea) for linea in jsonl.read_text(encoding="utf-8").splitlines()
    ]
    assert len(lineas) == len(articulos_122) == 13
    assert [linea["numero"] for linea in lineas] == list(range(1, 14))
    # Campos F2 del artículo (contract:88-90): esquema inalterado (FR-011).
    for linea in lineas:
        assert {
            "numero",
            "titulo",
            "texto",
            "libro",
            "parte",
            "seccion",
            "upls_mencionadas",
            "articulos_derogados",
        } <= set(linea)
    # Metadatos de norma añadidos (contract:91-100).
    for linea in lineas:
        assert linea["norma_id"] == "Decreto_122_2023"
        assert linea["tipo_norma"] == "decreto"
        assert linea["numero_norma"] == 122
        assert linea["año"] == 2023
        assert linea["fecha_vigencia"] == "2023-03-31"
        assert linea["titulo_norma"] == "Decreto 122 de 2023"
        assert linea["relacion_con_555"] == "referencia_articulos"
        assert linea["articulos_referenciados"] == [233, 243, 384]
        assert linea["estado_documento"] == "derogado"
        assert linea["derogado_compilado_por"] == BANNER_DEROGACION_122
    assert lineas[0]["titulo"] == DECRETO_122_TITULOS[0]


def test_archivos_del_acto_escriben_con_modo_0644(
    tmp_path, contenido_html_122, articulos_122, documento_122
):
    """JSONL, `.sha256` y registro salen con modo 0644 (SC-001, cosmetico).

    `mkstemp` crea el temporal con 0600; `_escribir_atomicamente` fija 0644
    ANTES del replace para que el corpus versionado en git sea legible por
    cualquier usuario del repo, no solo por el que ingirió.
    """
    ruta_registro = tmp_path / ".corpus_consolidado.json"
    directorio_salida = tmp_path / "actos"
    escribir_documento_acto(
        contenido_html_122,
        documento_122,
        articulos_122,
        ruta_registro=ruta_registro,
        directorio_salida=directorio_salida,
    )
    for ruta in (
        directorio_salida / "Decreto_122_2023.jsonl",
        directorio_salida / "Decreto_122_2023.jsonl.sha256",
        ruta_registro,
    ):
        assert ruta.stat().st_mode & 0o777 == 0o644


# --- 3. Registro del corpus consolidado (FR-002, FR-007, FR-008) ---

def test_registro_corpus_consolidado_con_metadatos(
    tmp_path, contenido_html_122, articulos_122, documento_122
):
    """El registro guarda un hash y metadatos por documento (FR-007/FR-008).

    `hash_sha256` es el hash del ARCHIVO fuente (base de la deduplicación
    FR-007) y la entrada es la forma canónica del contrato
    (contracts/ingesta-actos-modificatorios.md:109-129).
    """
    ruta_registro = tmp_path / ".corpus_consolidado.json"
    escribir_documento_acto(
        contenido_html_122,
        documento_122,
        articulos_122,
        ruta_registro=ruta_registro,
        directorio_salida=tmp_path / "actos",
    )

    registro = leer_registro_corpus(ruta_registro)
    assert registro["documento_base"] == "Decreto_555_2021"
    assert len(registro["documentos"]) == 1
    entrada = registro["documentos"][0]
    assert entrada["hash_sha256"] == hash_archivo(contenido_html_122)
    assert entrada["documento_id"] == "Decreto_122_2023"
    assert entrada["tipo_norma"] == "decreto"
    assert entrada["numero"] == 122
    assert entrada["año"] == 2023
    assert entrada["fecha_expedicion"] == "2023-03-30"
    assert entrada["fecha_vigencia"] == "2023-03-31"
    assert entrada["url_origen"] == DECRETO_122_METADATA["url_origen"]
    assert entrada["formato"] == "sisjur_html"
    assert entrada["relacion_con_555"] == "referencia_articulos"
    assert entrada["articulos"] == 13
    assert entrada["indexado"] is False
    # Forma canónica de la entrada (fixture `entrada_registro_corpus` de T010).
    assert entrada == entrada_registro_corpus(hash_sha256=hash_archivo(contenido_html_122))


def test_marcar_documento_indexado_tras_indexar(
    tmp_path, contenido_html_122, articulos_122, documento_122
):
    """`marcar_documento_indexado` refleja en el registro la indexación real.

    La ingesta escribe el registro con `indexado` según el `--indexar` de la
    llamada (SC-001: quedaba `false` tras indexar por separado); el marcado
    posterior actualiza la entrada del documento a `true` sin tocar las demás.
    """
    ruta_registro = tmp_path / ".corpus_consolidado.json"
    escribir_documento_acto(
        contenido_html_122,
        documento_122,
        articulos_122,
        ruta_registro=ruta_registro,
        directorio_salida=tmp_path / "actos",
    )
    marcar_documento_indexado("Decreto_122_2023", ruta_registro)

    entrada = leer_registro_corpus(ruta_registro)["documentos"][0]
    assert entrada["documento_id"] == "Decreto_122_2023"
    assert entrada["indexado"] is True
    assert len(leer_registro_corpus(ruta_registro)["documentos"]) == 1


def test_marcar_documento_indexado_documento_ausente_no_op(tmp_path):
    """Marcar un documento que no está en el registro no escribe nada (no-op)."""
    ruta_registro = tmp_path / ".corpus_consolidado.json"
    marcar_documento_indexado("Decreto_999_2099", ruta_registro)
    assert not ruta_registro.exists()


# --- 4. Re-ingesta duplicada: no-op sin duplicar artículos (SC-003) ---

def test_reingesta_duplicada_no_op(
    tmp_path, contenido_html_122, articulos_122, documento_122
):
    """Re-ingestar el mismo archivo es no-op con `"duplicado": true`.

    La segunda llamada no reescribe el JSONL (mismo contenido y mtime) ni añade
    entradas al registro (SC-003): la deduplicación por hash SHA-256 del archivo
    (FR-007) deja el corpus consolidado intacto.
    """
    ruta_registro = tmp_path / ".corpus_consolidado.json"
    directorio_salida = tmp_path / "actos"
    jsonl = directorio_salida / "Decreto_122_2023.jsonl"

    primera = escribir_documento_acto(
        contenido_html_122,
        documento_122,
        articulos_122,
        ruta_registro=ruta_registro,
        directorio_salida=directorio_salida,
    )
    assert primera["duplicado"] is False
    jsonl_previo = jsonl.read_text(encoding="utf-8")
    mtime_previo = jsonl.stat().st_mtime_ns

    segunda = escribir_documento_acto(
        contenido_html_122,
        documento_122,
        articulos_122,
        ruta_registro=ruta_registro,
        directorio_salida=directorio_salida,
    )
    assert segunda["duplicado"] is True
    assert jsonl.read_text(encoding="utf-8") == jsonl_previo
    assert jsonl.stat().st_mtime_ns == mtime_previo
    assert len(leer_registro_corpus(ruta_registro)["documentos"]) == 1


# --- 5. Validación FR-014: rechazo por fecha anterior al 555 ---

def test_validar_relacion_con_555_rechaza_fecha_anterior():
    """Acto anterior a la vigencia del 555 -> FECHA_ANTERIOR_AL_555.

    La validación ocurre ANTES de construir el `DocumentoNormativo` (fail-fast en
    la ingesta): el rechazo es tipificado y el corpus existente NO se modifica.
    """
    with pytest.raises(ErrorIngesta) as excinfo:
        validar_relacion_con_555("2020-01-01", [233, 243, 384])
    assert excinfo.value.codigo == "FECHA_ANTERIOR_AL_555"
    assert "NO se modificó" in excinfo.value.mensaje


# --- 6. Validación FR-014: acto sin referencia al 555 se integra ---

def test_documento_sin_referencia_al_555_se_integra(
    tmp_path, contenido_html_122, articulos_122
):
    """Acto sin enlaces verificables al 555 se integra con `sin_referencia`.

    La relación no siempre es verificable por máquina (FR-014): un acto posterior
    sin referencias NO se rechaza; se integra con warning y la entrada del
    registro y las líneas JSONL lo reflejan.
    """
    documento_sin_referencia = DocumentoNormativo(
        **DECRETO_122_METADATA,
        titulo="Decreto 122 de 2023",
        hash_sha256=hash_archivo(contenido_html_122),
        formato="sisjur_html",
        relacion_con_555=validar_relacion_con_555(
            DECRETO_122_METADATA["fecha_expedicion"], []
        ),
        articulos_referenciados=[],
        estado_documento="derogado",
        derogado_compilado_por=BANNER_DEROGACION_122,
    )
    assert documento_sin_referencia.relacion_con_555 == "sin_referencia"

    ruta_registro = tmp_path / ".corpus_consolidado.json"
    salida = escribir_documento_acto(
        contenido_html_122,
        documento_sin_referencia,
        articulos_122,
        ruta_registro=ruta_registro,
        directorio_salida=tmp_path / "actos",
    )
    assert salida["duplicado"] is False
    assert salida["relacion_con_555"] == "sin_referencia"

    entrada = leer_registro_corpus(ruta_registro)["documentos"][0]
    assert entrada["relacion_con_555"] == "sin_referencia"

    jsonl = tmp_path / "actos" / "Decreto_122_2023.jsonl"
    lineas = [json.loads(linea) for linea in jsonl.read_text(encoding="utf-8").splitlines()]
    assert len(lineas) == 13
    assert lineas[0]["relacion_con_555"] == "sin_referencia"
    assert lineas[0]["articulos_referenciados"] == []


# --- 7. Fallo atómico por documento (FR-009, SC-006) ---

def test_fallo_atomico_registro_corrupto(
    tmp_path, contenido_html_122, articulos_122, documento_122
):
    """Registro corrupto -> RuntimeError y el corpus previo queda intacto.

    El fallo ocurre ANTES de escribir: `leer_registro_corpus` rechaza el JSON
    inválido (infraestructura, FR-009) y `escribir_documento_acto` aborta sin
    reescribir el JSONL ni tocar el registro corrupto (SC-006).
    """
    ruta_registro = tmp_path / ".corpus_consolidado.json"
    directorio_salida = tmp_path / "actos"

    # Corpus previo: el 122 ya está ingestado correctamente.
    escribir_documento_acto(
        contenido_html_122,
        documento_122,
        articulos_122,
        ruta_registro=ruta_registro,
        directorio_salida=directorio_salida,
    )
    jsonl_previo = (directorio_salida / "Decreto_122_2023.jsonl").read_text(encoding="utf-8")
    sha_previo = (directorio_salida / "Decreto_122_2023.jsonl.sha256").read_text(
        encoding="utf-8"
    )

    # El registro se corrompe con JSON inválido (registro medio-escrito).
    registro_corrupto = '{"documento_base": "Decreto_555_2021", "documentos": ['
    ruta_registro.write_text(registro_corrupto, encoding="utf-8")

    with pytest.raises(RuntimeError):
        escribir_documento_acto(
            contenido_html_122,
            documento_122,
            articulos_122,
            ruta_registro=ruta_registro,
            directorio_salida=directorio_salida,
        )

    # Fallo atómico: el corpus previo queda intacto y el registro corrupto no se tocó.
    assert (directorio_salida / "Decreto_122_2023.jsonl").read_text(encoding="utf-8") == jsonl_previo
    assert (directorio_salida / "Decreto_122_2023.jsonl.sha256").read_text(
        encoding="utf-8"
    ) == sha_previo
    assert ruta_registro.read_text(encoding="utf-8") == registro_corrupto


def test_fallo_atomico_registro_no_escribible(
    tmp_path, contenido_html_122, articulos_122, documento_122
):
    """Fallo al actualizar el registro -> rollback del JSONL y `.sha256` nuevos.

    El JSONL y el `.sha256` se escriben ANTES que el registro; si el registro no
    se puede escribir (su directorio padre es un archivo), la ingesta revierte
    los archivos nuevos y deja el corpus previo intacto (FR-009, SC-006).
    """
    ruta_registro = tmp_path / ".corpus_consolidado.json"
    directorio_salida = tmp_path / "actos"

    # Corpus previo: el 122 ya está ingestado correctamente.
    escribir_documento_acto(
        contenido_html_122,
        documento_122,
        articulos_122,
        ruta_registro=ruta_registro,
        directorio_salida=directorio_salida,
    )
    jsonl_previo = (directorio_salida / "Decreto_122_2023.jsonl").read_text(encoding="utf-8")
    registro_previo = ruta_registro.read_text(encoding="utf-8")

    # El padre del registro es un ARCHIVO: mkdir/mkstemp del registro falla.
    bloqueo = tmp_path / "bloqueo"
    bloqueo.write_text("soy un archivo", encoding="utf-8")
    ruta_registro_invalida = bloqueo / ".corpus_consolidado.json"

    # Segundo acto (documento_id distinto: archivos nuevos que deben revertirse).
    metadatos_otro = {**DECRETO_122_METADATA, "documento_id": "Decreto_123_2023"}
    otro_documento = DocumentoNormativo(
        **metadatos_otro,
        titulo="Decreto 123 de 2023",
        hash_sha256="hash-del-otro-documento",
        formato="sisjur_html",
        relacion_con_555="referencia_articulos",
        articulos_referenciados=[233, 243, 384],
        estado_documento="derogado",
        derogado_compilado_por=BANNER_DEROGACION_122,
    )
    with pytest.raises(OSError):
        escribir_documento_acto(
            contenido_html_122,
            otro_documento,
            articulos_122,
            ruta_registro=ruta_registro_invalida,
            directorio_salida=directorio_salida,
        )

    # Rollback: los archivos nuevos se revierten y el corpus previo queda intacto.
    assert not (directorio_salida / "Decreto_123_2023.jsonl").exists()
    assert not (directorio_salida / "Decreto_123_2023.jsonl.sha256").exists()
    assert (directorio_salida / "Decreto_122_2023.jsonl").read_text(encoding="utf-8") == jsonl_previo
    assert ruta_registro.read_text(encoding="utf-8") == registro_previo


# --- 8. Registro corrupto: RuntimeError de infraestructura (FR-009) ---

@pytest.mark.parametrize(
    "contenido_corrupto",
    [
        '{"documento_base": "Decreto_555_2021", "documentos": [',  # JSON cortado
        "[1, 2, 3]",  # JSON válido pero no es un objeto de registro
    ],
)
def test_leer_registro_corrupto_raise_runtimeerror(tmp_path, contenido_corrupto):
    """Registro corrupto -> RuntimeError (infraestructura), nunca ErrorIngesta.

    Un registro medio-escrito rompería la deduplicación: el fallo es de
    infraestructura (FR-009) y no se enmascara como error tipificado de ingesta.
    """
    ruta_registro = tmp_path / ".corpus_consolidado.json"
    ruta_registro.write_text(contenido_corrupto, encoding="utf-8")
    with pytest.raises(RuntimeError):
        leer_registro_corpus(ruta_registro)


# --- 9. Re-indexación aditiva del corpus consolidado (T017, FR-008, E7) ---
# RED hasta T020 (tasks.md T020): hoy `indexar_corpus` recibe UN corpus y la
# huella de la colección es mono-documento (`corpus_sha256`); re-indexar el acto
# reconstruye y pierde el 555, e indexar el corpus consolidado lanza
# DuplicateIDError (los ids `art-NNN` colisionan entre normas). El contrato
# exige ids `norma_id-art-<NNN>` para los actos (data-model.md:121), metadatos
# extendidos de norma por chunk (data-model.md:113-130) y la huella
# multi-documento `hash_corpus` en la metadata de la colección (data-model.md:85).


def _coleccion_normativa(ruta_indice: Path):
    """Abre la colección única del corpus normativo para inspección."""
    cliente = chromadb.PersistentClient(path=str(ruta_indice))
    return cliente.get_collection(COLECCION_NORMATIVA)


@pytest.fixture
def corpus_555_sintetico():
    """Corpus base sintético del 555 (3 artículos, HTML_SINTETICO de F2)."""
    return parsear_articulos(HTML_SINTETICO)


@pytest.fixture
def fake_ef():
    """Embedding function determinista (mismo fake de F2, modelo `fake`)."""
    return FakeEmbeddingFunction()


@pytest.fixture
def indice_consolidado(
    tmp_path, contenido_html_122, articulos_122, documento_122,
    corpus_555_sintetico, fake_ef,
):
    """Índice con el 555 y el acto 122 ya integrados (estado previo a T020).

    Indexa el 555, ingesta el acto (JSONL + registro) y re-indexa los chunks
    del acto sobre la MISMA colección `decreto_555_2021` (FR-008). Devuelve
    las piezas necesarias para verificar la re-indexación aditiva.
    """
    ruta_registro = tmp_path / ".corpus_consolidado.json"
    directorio_salida = tmp_path / "actos"
    escribir_documento_acto(
        contenido_html_122,
        documento_122,
        articulos_122,
        ruta_registro=ruta_registro,
        directorio_salida=directorio_salida,
    )
    articulos_acto = deserializar_corpus(
        str(directorio_salida / "Decreto_122_2023.jsonl")
    )
    ruta_indice = tmp_path / "chroma_test"
    indexar_corpus(corpus_555_sintetico, str(ruta_indice), fake_ef)
    indexar_corpus(articulos_acto, str(ruta_indice), fake_ef)
    return {
        "ruta_indice": ruta_indice,
        "corpus_555": corpus_555_sintetico,
        "articulos_acto": articulos_acto,
        "documento_122": documento_122,
    }


def test_upsert_aditivo_por_documento(indice_consolidado):
    """Tras ingestar un acto, la re-indexación upserta SOLO sus chunks (FR-008).

    La colección única `decreto_555_2021` contiene AMBOS documentos: los ids
    del 555 (`art-NNN`, patrón F2 inalterado) y los del acto
    (`Decreto_122_2023-art-NNN`, data-model.md:121); el conteo es la suma y los
    chunks del acto materializan los metadatos extendidos de norma
    (data-model.md:113-130). RED hasta T020: hoy re-indexar el acto reconstruye
    y deja solo los chunks del acto con ids `art-NNN` (pierde el 555).
    """
    ruta_indice = indice_consolidado["ruta_indice"]
    corpus_555 = indice_consolidado["corpus_555"]
    articulos_acto = indice_consolidado["articulos_acto"]

    # Identidad norma+artículo (research D3): dos normas pueden tener el mismo
    # número de artículo sin colisión; el 555 conserva su patrón F2.
    ids_esperados = {
        *{f"art-{a.numero:03d}" for a in corpus_555},
        *{f"{a.norma_id}-art-{a.numero:03d}" for a in articulos_acto},
    }
    assert len(ids_esperados) == len(corpus_555) + len(articulos_acto)

    coleccion = _coleccion_normativa(ruta_indice)
    assert set(coleccion.get()["ids"]) == ids_esperados
    assert coleccion.count() == len(corpus_555) + len(articulos_acto)

    # Metadatos extendidos del acto materializados en el chunk (data-model.md:113-130).
    meta_acto = coleccion.get(ids=["Decreto_122_2023-art-001"])["metadatas"][0]
    assert meta_acto.get("norma_id") == "Decreto_122_2023"
    assert meta_acto.get("tipo_norma") == "decreto"
    assert meta_acto.get("numero_norma") == 122
    assert meta_acto.get("año") == 2023
    assert meta_acto.get("fecha_vigencia") == "2023-03-31"
    assert meta_acto.get("titulo_norma") == "Decreto 122 de 2023"
    assert meta_acto.get("source_name") == "Decreto 122 de 2023"
    assert meta_acto.get("data_vigencia") == "2023-03-31"
    assert meta_acto.get("relacion_con_555") == "referencia_articulos"


def test_huella_multi_documento_persistida(indice_consolidado):
    """La huella multi-documento se persiste en la metadata (FR-008, data-model.md:85).

    `hash_corpus` guarda un hash por documento del registro consolidado: el del
    555 (huella F2 del corpus) y el del acto (`hash_sha256` del archivo en el
    registro). RED hasta T020: hoy la metadata solo tiene `corpus_sha256`
    mono-documento y la clave `hash_corpus` no existe.
    """
    ruta_indice = indice_consolidado["ruta_indice"]
    corpus_555 = indice_consolidado["corpus_555"]
    documento_122 = indice_consolidado["documento_122"]

    coleccion = _coleccion_normativa(ruta_indice)
    hash_corpus = coleccion.metadata.get("hash_corpus")
    assert hash_corpus is not None
    assert str(hash_documento(corpus_555)) in str(hash_corpus)
    assert str(documento_122.hash_sha256) in str(hash_corpus)


def test_reindexacion_reconstruye_al_cambiar_documento(indice_consolidado):
    """Un cambio de documento dispara reconstrucción automática (FR-008, E7).

    Si el acto cambia (v2 sin el artículo 13), la re-indexación del corpus
    consolidado reconstruye la colección: NO queda `Decreto_122_2023-art-013`
    (ni vectores de la versión previa) y la huella multi-documento cambia.
    RED hasta T020: hoy indexar el corpus consolidado lanza DuplicateIDError
    (los ids `art-NNN` colisionan entre normas: la identidad norma+artículo
    aún no existe).
    """
    ruta_indice = indice_consolidado["ruta_indice"]
    corpus_555 = indice_consolidado["corpus_555"]
    articulos_acto = indice_consolidado["articulos_acto"]

    hash_corpus_previo = _coleccion_normativa(ruta_indice).metadata.get("hash_corpus")

    articulos_acto_v2 = articulos_acto[:-1]  # el acto cambia: sin el artículo 13
    consolidado_v2 = [*corpus_555, *articulos_acto_v2]
    indexar_corpus(consolidado_v2, str(ruta_indice), FakeEmbeddingFunction())

    coleccion = _coleccion_normativa(ruta_indice)
    ids = set(coleccion.get()["ids"])
    assert "Decreto_122_2023-art-013" not in ids
    assert "Decreto_122_2023-art-012" in ids
    assert coleccion.count() == len(corpus_555) + len(articulos_acto_v2)
    assert coleccion.metadata.get("hash_corpus") != hash_corpus_previo


def test_reindexacion_reconstruye_al_cambiar_modelo_embedding(indice_consolidado):
    """Un cambio del modelo de embeddings reconstruye sin mezclar vectores (FR-008).

    Re-indexar el corpus consolidado con otro modelo (`modelo-b`) deja la
    colección con EXACTAMENTE los chunks del corpus actual y persiste el nuevo
    `embedding_model`. RED hasta T020: hoy indexar el corpus consolidado lanza
    DuplicateIDError (misma causa que el cambio de documento).
    """
    ruta_indice = indice_consolidado["ruta_indice"]
    corpus_555 = indice_consolidado["corpus_555"]
    articulos_acto = indice_consolidado["articulos_acto"]

    consolidado = [*corpus_555, *articulos_acto]
    ef_b = FakeEmbeddingFunction(model_name="modelo-b")
    indexar_corpus(consolidado, str(ruta_indice), ef_b)

    coleccion = _coleccion_normativa(ruta_indice)
    assert coleccion.metadata.get(METADATA_EMBEDDING_MODEL) == "modelo-b"
    ids_esperados = {
        *{f"art-{a.numero:03d}" for a in corpus_555},
        *{f"{a.norma_id}-art-{a.numero:03d}" for a in articulos_acto},
    }
    assert set(coleccion.get()["ids"]) == ids_esperados
    assert coleccion.count() == len(ids_esperados)


def test_metadatos_extendidos_555_materializados_en_indice(corpus_555_sintetico, fake_ef, tmp_path):
    """El 555 materializa sus metadatos aditivos en el índice (FR-012, data-model.md:108-111).

    El JSONL del 555 NO se modifica (FR-012), pero al indexarse sus chunks
    ganan la identidad de norma (`norma_id=Decreto_555_2021`) y la trazabilidad
    FR-004 (`source_name`, `data_vigencia`); los metadatos F2 se conservan
    (FR-011). RED hasta T020: hoy los chunks solo llevan los metadatos F2.
    """
    ruta_indice = tmp_path / "chroma_test"
    indexar_corpus(corpus_555_sintetico, str(ruta_indice), fake_ef)

    coleccion = _coleccion_normativa(ruta_indice)
    meta = coleccion.get(ids=["art-001"])["metadatas"][0]
    assert meta.get("norma_id") == "Decreto_555_2021"
    assert meta.get("fecha_vigencia") == FECHA_VIGENCIA_555
    assert meta.get("data_vigencia") == FECHA_VIGENCIA_555
    assert meta.get("titulo_norma") == "Decreto 555 de 2021"
    assert meta.get("source_name") == "Decreto 555 de 2021 (POT Bogotá)"
    # Metadatos F2 conservados (FR-011): el chunk sigue siendo el mismo.
    assert meta.get("articulo") == 1
    # FR-002: `upls` es list[str] real ($contains = membresia exacta), no CSV.
    assert meta.get("upls") == ["UPL17"]
