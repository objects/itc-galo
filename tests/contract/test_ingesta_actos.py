"""Contract tests para F4 — Ingesta de actos modificatorios (tasks.md T011).

Cubre el núcleo de ingesta del corpus consolidado
(contracts/ingesta-actos-modificatorios.md): parseo del HTML sisjur del Decreto
122 (13 artículos con títulos del `<i>` y ordinales `Nº.`, D4/H2), extracción
genérica de PDF/DOCX/Markdown/TXT (D5), deduplicación por hash SHA-256 (FR-007,
SC-003), fallo atómico ante formato no soportado / documento sin artículos /
fecha anterior al 555 (FR-009, SC-006) y errores tipificados (`ErrorIngesta`,
data-model.md:178-191). Sin red real ni Ollama: solo fixtures de
`tests/conftest.py` y directorios temporales (`tmp_path`).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ingesta.actos import (
    ErrorIngesta,
    detectar_formato,
    escribir_documento_acto,
    extraer_articulos,
    extraer_articulos_referenciados,
    extraer_documento_sisjur,
    hash_archivo,
    leer_registro_corpus,
    validar_relacion_con_555,
)
from app.models import ArticuloNormativo, DocumentoNormativo
from tests.conftest import (
    BANNER_DEROGACION_122,
    DECRETO_122_METADATA,
    DECRETO_122_TITULOS,
    docx_decreto_122,
    html_decreto_122,
    md_decreto_122,
    pdf_decreto_122,
    txt_decreto_122,
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
    """DocumentoNormativo canónico del 122 para los casos de escritura (3-4).

    Se construye con DECRETO_122_METADATA + hash SHA-256 del ARCHIVO fuente
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


# --- 1. Parseo del HTML sisjur del Decreto 122 (D4/H2, quickstart E1) ---

def test_extraer_articulos_sisjur_122(contenido_html_122):
    """El HTML sisjur del 122 se parsea con el parser de anclas de F2.

    La plantilla del 122 marca el número con ordinal (`<b>Nº.</b>`) y el título
    en `<i style="font-weight: bold;">` en lugar del `<b>` del 555 (D4/H2): el
    parser reutilizado debe reconocer ambos sin adaptación y entregar los 13
    artículos con sus títulos canónicos.
    """
    articulos = extraer_articulos(contenido_html_122, "sisjur_html")
    assert len(articulos) == 13
    assert all(isinstance(a, ArticuloNormativo) for a in articulos)
    assert [a.numero for a in articulos] == list(range(1, 14))
    assert all(a.titulo for a in articulos)
    assert [a.titulo for a in articulos] == DECRETO_122_TITULOS
    # El artículo 1 conserva la referencia textual a los artículos del 555.
    assert "233" in articulos[0].texto
    assert "243" in articulos[0].texto
    assert "384" in articulos[0].texto


# --- 2. Extracción genérica de PDF/DOCX/Markdown/TXT (D5, quickstart E4) ---

@pytest.mark.parametrize(
    "generador, formato",
    [
        (pdf_decreto_122, "pdf"),
        (docx_decreto_122, "docx"),
        (md_decreto_122, "markdown"),
        (txt_decreto_122, "txt"),
    ],
)
def test_extraer_articulos_generico_122(generador, formato):
    """Cada formato genérico produce los 13 artículos del 122.

    Las fixtures comparten el mismo articulado plano ("ARTÍCULO Nº. Título" +
    cuerpo; la variante Markdown añade los `##` que `_texto_markdown` elimina):
    cada formato entrega exactamente 13 artículos con los títulos canónicos.
    """
    contenido = generador()
    if isinstance(contenido, str):
        contenido = contenido.encode("utf-8")
    articulos = extraer_articulos(contenido, formato)
    assert len(articulos) == 13
    assert [a.numero for a in articulos] == list(range(1, 14))
    assert [a.titulo for a in articulos] == DECRETO_122_TITULOS


# --- 3. Deduplicación por hash SHA-256 (FR-007, SC-003, quickstart E2) ---

def test_escribir_documento_acto_deduplica_por_hash(
    tmp_path, contenido_html_122, articulos_122, documento_122
):
    """Re-ingestar el mismo archivo es no-op con `"duplicado": true`.

    El registro guarda el hash SHA-256 del archivo (FR-007): la segunda ingesta
    no reescribe el JSONL ni el `.sha256` y el registro conserva una sola
    entrada. Ni siquiera un JSONL manipulado se reescribe (no-op total, SC-003).
    """
    ruta_registro = tmp_path / ".corpus_consolidado.json"
    directorio_salida = tmp_path / "actos"
    jsonl = directorio_salida / "Decreto_122_2023.jsonl"
    sha = directorio_salida / "Decreto_122_2023.jsonl.sha256"

    primera = escribir_documento_acto(
        contenido_html_122,
        documento_122,
        articulos_122,
        ruta_registro=ruta_registro,
        directorio_salida=directorio_salida,
    )
    assert primera["duplicado"] is False
    assert primera["articulos"] == 13
    assert primera["documento_id"] == "Decreto_122_2023"
    assert jsonl.exists() and sha.exists()
    jsonl_previo = jsonl.read_text(encoding="utf-8")
    sha_previo = sha.read_text(encoding="utf-8")

    segunda = escribir_documento_acto(
        contenido_html_122,
        documento_122,
        articulos_122,
        ruta_registro=ruta_registro,
        directorio_salida=directorio_salida,
    )
    assert segunda["duplicado"] is True
    assert jsonl.read_text(encoding="utf-8") == jsonl_previo
    assert sha.read_text(encoding="utf-8") == sha_previo
    assert len(leer_registro_corpus(ruta_registro)["documentos"]) == 1

    jsonl.write_text("contenido manipulado", encoding="utf-8")
    tercera = escribir_documento_acto(
        contenido_html_122,
        documento_122,
        articulos_122,
        ruta_registro=ruta_registro,
        directorio_salida=directorio_salida,
    )
    assert tercera["duplicado"] is True
    assert jsonl.read_text(encoding="utf-8") == "contenido manipulado"


# --- 4. Fallo atómico (FR-009, SC-006, quickstart E3/E5) ---

def test_detectar_formato_no_soportado_no_toca_corpus(tmp_path):
    """Extensión no reconocida -> FORMATO_NO_SOPORTADO (FR-001, FR-009)."""
    ruta = tmp_path / "acto.xyz"
    ruta.write_bytes(b"contenido de un formato no soportado")
    with pytest.raises(ErrorIngesta) as excinfo:
        detectar_formato(ruta)
    assert excinfo.value.codigo == "FORMATO_NO_SOPORTADO"
    assert "no es un formato soportado" in excinfo.value.mensaje
    assert "NO se modificó" in excinfo.value.mensaje


def test_extraer_articulos_sin_articulados_raise():
    """Documento sin articulado -> SIN_ARTICULOS_PARSEABLES (FR-009)."""
    with pytest.raises(ErrorIngesta) as excinfo:
        extraer_articulos("texto sin ningún artículo parseable".encode("utf-8"), "txt")
    assert excinfo.value.codigo == "SIN_ARTICULOS_PARSEABLES"


def test_validar_relacion_con_555_fecha_anterior_raise():
    """Acto anterior a la vigencia del 555 -> FECHA_ANTERIOR_AL_555 (FR-014)."""
    with pytest.raises(ErrorIngesta) as excinfo:
        validar_relacion_con_555("2020-01-01", [233, 243, 384])
    assert excinfo.value.codigo == "FECHA_ANTERIOR_AL_555"


def test_documento_normativo_rechaza_fecha_anterior_al_555():
    """Defensa en profundidad del FR-014: el modelo pydantic también rechaza.

    El rechazo tipificado de la ingesta ocurre ANTES de construir el modelo
    (models.py); el validador de `DocumentoNormativo` es la segunda línea de
    defensa si un llamador lo construye directamente con una fecha inválida.
    """
    metadatos = {**DECRETO_122_METADATA, "fecha_expedicion": "2020-01-01"}
    with pytest.raises(ValidationError):
        DocumentoNormativo(
            **metadatos,
            titulo="Decreto antiguo",
            hash_sha256="abc123",
            formato="sisjur_html",
            relacion_con_555="sin_referencia",
        )


# --- 5. Referencias verificables a artículos del 555 (H2, FR-014) ---

def test_extraer_articulos_referenciados_122():
    """Los enlaces sisjur internos al 555 se deduplican en orden de aparición.

    El artículo 1 del 122 enlaza `Norma1.jsp?i=119582#233/243/384`: la
    referencia verificable por máquina de `relacion_con_555` (contract:50).
    """
    assert extraer_articulos_referenciados(html_decreto_122()) == [233, 243, 384]


# --- 6. Metadatos de estado del documento sisjur (H7, contract:51-52) ---

def test_extraer_documento_sisjur_122_derogado(contenido_html_122):
    """El banner de derogación se captura como metadato sin romper el parseo.

    El banner vive FUERA de los `<p class="MsoNormal">` del articulado (H7): la
    plantilla real marca el 122 derogado/compilado por el DUDOT 670 de 2025.
    """
    articulos, estado_documento, derogado_compilado_por = extraer_documento_sisjur(
        contenido_html_122
    )
    assert len(articulos) == 13
    assert estado_documento == "derogado"
    assert derogado_compilado_por == BANNER_DEROGACION_122


# --- 7. Errores tipificados (data-model.md:178-191, contract:69-78) ---

@pytest.mark.parametrize(
    "codigo",
    [
        "FORMATO_NO_SOPORTADO",
        "SIN_TEXTO_EXTRAIBLE",
        "SIN_ARTICULOS_PARSEABLES",
        "FECHA_ANTERIOR_AL_555",
        "FUENTE_NO_DISPONIBLE",
        "DUPLICADO",
    ],
)
def test_error_ingesta_codigos_documentados(codigo):
    """Cada código del contrato se construye y expone `.codigo` y `.mensaje`."""
    error = ErrorIngesta(codigo, "mensaje de prueba")
    assert error.codigo == codigo
    assert error.mensaje == "mensaje de prueba"


def test_error_ingesta_expone_codigo_y_mensaje():
    """ErrorIngesta tipifica el fallo: el str incluye código y mensaje."""
    error = ErrorIngesta("DUPLICADO", "el documento ya está en el registro")
    assert error.codigo == "DUPLICADO"
    assert error.mensaje == "el documento ya está en el registro"
    assert "DUPLICADO" in str(error)
    assert "el documento ya está en el registro" in str(error)
