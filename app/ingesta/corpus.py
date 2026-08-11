"""Parseo del corpus normativo del Decreto 555/2021 (sisjur) en articulos tipados.

El HTML descargado de sisjur se convierte en una lista de `ArticuloNormativo`
con el texto literal de cada articulo (FR-003) y su ubicacion en el documento:
libro, parte derivada y referencias (UPLs mencionadas y articulos derogados).
Esta capa produce el corpus versionado en git y los chunks del indice vectorial.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_mod
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
# La fuente real menciona UPL de uno y dos dígitos ("UPL 2".."UPL 33"); el
# dígito se normaliza después a dos posiciones (UPL02..UPL33).
UPL_PATRON = re.compile(r"UPL\s*(\d{1,2})")
ARTICULO_DEROGADO_PATRON = re.compile(
    r"deroga[ra]?\s+(?:el\s+)?art[ií]culo\s+(\d+)", re.IGNORECASE
)

PARTE_POR_LIBRO = {"II": "general", "III": "urbano", "IV": "rural"}

# Formato sisjur (HTML exportado por Word): el número de artículo vive en el
# span ancla `class="ancla" id="N"` (483 artículos) o en el encabezado inline
# "Artículo N." (los 125 restantes). El ancla tambien marca los LIBRO
# (`id="L.2"`), que nunca colisionan con el patron numerico de articulo.
MARCA_ANCLA = 'class="ancla"'
ANCLA_ARTICULO_PATRON = re.compile(r'<span[^>]*class="ancla"[^>]*id="(\d+)"')
ARTICULO_INLINE_PATRON = re.compile(
    r'<b(?:\s[^>]*)?>\s*<span lang="ES"[^>]*>\s*Art[ií]culo\s+(\d+)\s*\.'
    r"(?:\s*|&nbsp;|(?:<font[^>]*>)?\s*&nbsp;\s*(?:</font>)?)</span></b>",
    re.IGNORECASE,
)
BOLD_PATRON = re.compile(r"<b(?:\s[^>]*)?>(.*?)</b>", re.DOTALL)
LIBRO_SISJUR_PATRON = re.compile(
    r'LIBRO<span[^>]*id="L\.\d+"[^>]*>\s*</span>\s*&nbsp;\s*'
    r"(VIII|VII|VI|V|IV|III|II|I)\b"
)

MENSAJE_SIN_ARTICULOS = (
    "No se encontró ningún 'ARTÍCULO' en el HTML del Decreto 555/2021. "
    "Verifica que la fuente de sisjur devuelva el documento completo."
)
# El formato sisjur no usa "ARTÍCULO" en mayúsculas: el número vive en el span
# `class="ancla"`; el mensaje debe señalar esa marca estructural.
MENSAJE_SIN_ARTICULOS_SISJUR = (
    "No se encontró ningún artículo con 'class=\"ancla\"' en el HTML del "
    "Decreto 555/2021. Verifica que la fuente de sisjur devuelva el documento "
    "completo."
)


def _limpiar_html(texto: str) -> str:
    """Limpia HTML del formato sisjur: tags fuera, entidades decodificadas.

    Los cierres de bloque y los saltos `<br>` se conservan como separación de
    párrafos (`\n`); el resto de tags se quita y toda corrida de espacios o de
    saltos suaves de línea de Word colapsa a un solo espacio (requisito B:
    los títulos no pueden tener saltos internos).
    """
    SALTO_PARRAFO = "\x00"
    # El pie de página de sisjur inyecta <script> con gtag/dataLayer/UA- y
    # <style>: no son contenido normativo y se eliminan enteros ANTES de tocar
    # los tags, para que su cuerpo no contamine el artículo final.
    texto = re.sub(
        r"<script\b.*?</script>|<style\b.*?</style>",
        "",
        texto,
        flags=re.DOTALL | re.IGNORECASE,
    )
    texto = re.sub(
        r"</(?:p|div|tr|li|table|h[1-6])>|<br\s*/?>",
        SALTO_PARRAFO,
        texto,
        flags=re.IGNORECASE,
    )
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = html_mod.unescape(texto)
    texto = re.sub(r"\s+", " ", texto)
    texto = re.sub(f" *{re.escape(SALTO_PARRAFO)} *", SALTO_PARRAFO, texto)
    texto = re.sub(re.escape(SALTO_PARRAFO) + r"+", SALTO_PARRAFO, texto)
    return texto.replace(SALTO_PARRAFO, "\n").strip()


def _extraer_upls(texto: str) -> list[str]:
    """UPLs mencionadas en el texto, únicas y en forma canónica de dos dígitos.

    Acepta las variantes de la fuente (`UPL 2`, `UPL20`, `UPL 33`) y normaliza
    todas a la forma canónica de dos dígitos (`UPL02`..`UPL33`), con cero-padding
    para los valores de un dígito: "UPL 2" -> "UPL02", "UPL20" -> "UPL20".
    """
    return list(
        dict.fromkeys(f"UPL{int(digitos):02d}" for digitos in UPL_PATRON.findall(texto))
    )


def _extraer_derogados(texto: str) -> list[int]:
    """Números de artículos que el texto deroga explícitamente."""
    return [int(n) for n in ARTICULO_DEROGADO_PATRON.findall(texto)]


def _parsear_formato_demo(html: str) -> list[ArticuloNormativo]:
    """Parsea el HTML plano del modo demo (encabezados "ARTÍCULO N. Título").

    Reglas de extraccion:
    - Cada "ARTÍCULO N." abre un articulo: su titulo es el resto de la linea del
      encabezado (sin punto final) y su texto llega hasta el siguiente "ARTÍCULO".
    - El libro vigente es el último "LIBRO <numeral>" anterior al articulo ("I"
      si no hay ninguno); la parte se deriva del libro (II general, III urbano,
      IV rural; el resto sin parte).
    """
    partidos = list(ARTICULO_PATRON.finditer(html))
    if not partidos:
        raise ValueError(MENSAJE_SIN_ARTICULOS)

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

        articulos.append(
            ArticuloNormativo(
                numero=numero,
                titulo=titulo,
                texto=texto,
                libro=libro_vigente,
                parte=PARTE_POR_LIBRO.get(libro_vigente),
                upls_mencionadas=_extraer_upls(texto),
                articulos_derogados=_extraer_derogados(texto),
            )
        )

    return articulos


def _es_solo_anclas(texto: str) -> bool:
    """True si el fragmento no tiene texto visible fuera de `<a href>...</a>`.

    Sisjur inyecta anotaciones editoriales ("Reglamentado por...") entre el
    número y el título del artículo; esas anotaciones se saltan al extraer el
    título porque no forman parte del texto normativo.
    """
    sin_anclas = re.sub(r"<a\b.*?</a>", "", texto, flags=re.DOTALL)
    return _limpiar_html(sin_anclas) == ""


def _extraer_titulo_sisjur(
    html: str, inicio: int, numero: int, fin_cuerpo: int
) -> tuple[str, int]:
    """Devuelve (titulo, inicio del cuerpo) para un articulo del formato sisjur.

    El titulo es el texto de los grupos `<b>` posteriores al numero del articulo.
    Word puede partir una palabra entre dos grupos ("4. P" + "rincipios..."), por
    eso se unen sin espacio cuando el HTML original no tenia ninguno entre ambos.
    Las anotaciones editoriales en `<a href>` se saltan; el cuerpo empieza en el
    primer texto visible que no es negrita ni anotacion.
    """
    numero_patron = re.compile(r"(?:Art[ií]culo\s+)?" + str(numero) + r"\.")
    grupo_numero = None
    cursor = inicio
    while grupo_numero is None:
        grupo = BOLD_PATRON.search(html, cursor, fin_cuerpo)
        if grupo is None:
            # Fail Fast: el marcador (ancla o inline) existió pero ningún grupo
            # <b> lleva el número del artículo; el título queda incompleto y un
            # fallback silencioso ("", inicio) contaminaría el corpus.
            raise ValueError(
                f"No se encontró el título del marcador ancla {numero} en el "
                "HTML del Decreto 555/2021."
            )
        if numero_patron.match(_limpiar_html(grupo.group(1))):
            grupo_numero = grupo
        else:
            cursor = grupo.end()

    coincidencia = numero_patron.match(_limpiar_html(grupo_numero.group(1)))
    cursor = grupo_numero.end()
    partes: list[str] = []
    if coincidencia:
        resto = _limpiar_html(grupo_numero.group(1))[coincidencia.end():]
        if resto:
            partes.append(resto)

    while True:
        grupo = BOLD_PATRON.search(html, cursor, fin_cuerpo)
        if grupo is None:
            break
        entre = html[cursor:grupo.start()]
        if _limpiar_html(entre) and not _es_solo_anclas(entre):
            break
        separador_tiene_espacio = re.search(
            r"\s", re.sub(r"<[^>]+>", "", entre).replace("&nbsp;", " ")
        )
        contenido = _limpiar_html(grupo.group(1))
        if not re.search(r"\w", contenido):
            cursor = grupo.end()
            continue
        if separador_tiene_espacio and partes and partes[-1] != " ":
            partes.append(" ")
        partes.append(contenido)
        cursor = grupo.end()

    titulo = re.sub(r"\s{2,}", " ", "".join(partes)).strip()
    return titulo, cursor


def _ajustar_fin_cuerpo(html: str, fin_cuerpo: int) -> int:
    """Recorta el fin del cuerpo a la frontera real del encabezado siguiente.

    En el formato sisjur, el encabezado del artículo siguiente separa la palabra
    "Artículo" en un grupo `<b>` propio situado ANTES de su ancla
    (`class="ancla"`); sin este recorte, esa palabra suelta contamina el final
    del cuerpo del artículo actual (frase huérfana "Artículo"). Solo se recorta
    cuando el contenido limpio del último grupo `<b>` anterior a la frontera es
    exactamente "Artículo" (re.IGNORECASE) y entre ese grupo y el ancla no hay
    texto visible; los encabezados inline "Artículo N." no cumplen ninguna de
    las dos condiciones y conservan el fin original.
    """
    ventana_inicio = max(0, fin_cuerpo - 2000)
    ventana = html[ventana_inicio:fin_cuerpo]
    grupo_anterior = None
    for grupo in BOLD_PATRON.finditer(ventana):
        grupo_anterior = grupo
    if grupo_anterior is None:
        return fin_cuerpo
    inicio_grupo = ventana_inicio + grupo_anterior.start()
    if _limpiar_html(html[ventana_inicio + grupo_anterior.end():fin_cuerpo]) != "":
        return fin_cuerpo
    if _limpiar_html(grupo_anterior.group(1)).strip().lower() != "artículo":
        return fin_cuerpo
    return inicio_grupo


def _parsear_formato_sisjur(html: str) -> list[ArticuloNormativo]:
    """Parsea el HTML real de sisjur (Word exportado): anclas + encabezados inline.

    Fuente autoritativa del numero: los spans `class="ancla" id="N"` (483) unidos
    a los encabezados inline "Artículo N." con punto (125). Las referencias
    internas ("artículo 12 de la Ley 810 de 2003", "artículo 2.2.2.1.2.3.5") no
    cumplen el patron inline (sin punto seguido de cierre del span) y quedan
    fuera; la union produce exactamente {1..608} sin lagunas.
    """
    marcadores: dict[int, int] = {}
    for partido in ANCLA_ARTICULO_PATRON.finditer(html):
        marcadores.setdefault(int(partido.group(1)), partido.start())
    for partido in ARTICULO_INLINE_PATRON.finditer(html):
        numero = int(partido.group(1))
        if numero not in marcadores or partido.start() < marcadores[numero]:
            marcadores[numero] = partido.start()
    if not marcadores:
        raise ValueError(MENSAJE_SIN_ARTICULOS_SISJUR)

    posiciones = sorted((posicion, numero) for numero, posicion in marcadores.items())
    libros = list(LIBRO_SISJUR_PATRON.finditer(html))
    articulos: list[ArticuloNormativo] = []

    for indice, (inicio, numero) in enumerate(posiciones):
        fin_cuerpo = (
            posiciones[indice + 1][0] if indice + 1 < len(posiciones) else len(html)
        )
        fin_cuerpo = _ajustar_fin_cuerpo(html, fin_cuerpo)
        titulo, inicio_cuerpo = _extraer_titulo_sisjur(html, inicio, numero, fin_cuerpo)
        texto = _limpiar_html(html[inicio_cuerpo:fin_cuerpo])
        if texto.startswith("."):
            texto = texto[1:].lstrip()

        libro_vigente = next(
            (m.group(1) for m in reversed(libros) if m.start() < inicio), "I"
        )

        articulos.append(
            ArticuloNormativo(
                numero=numero,
                titulo=titulo,
                texto=texto,
                libro=libro_vigente,
                parte=PARTE_POR_LIBRO.get(libro_vigente),
                upls_mencionadas=_extraer_upls(texto),
                articulos_derogados=_extraer_derogados(texto),
            )
        )

    return articulos


def parsear_articulos(html: str) -> list[ArticuloNormativo]:
    """Parsea el HTML del Decreto 555/2021 de sisjur en articulos tipados.

    Detecta el formato por una unica senal estructural, sin heuristica fragil:
    la presencia de `class="ancla"` (HTML exportado por Word de la fuente real)
    despacha al parser sisjur; su ausencia, al parser del HTML plano del modo
    demo y de los fixtures.

    Reglas comunes a ambos formatos:
    - Cada "ARTÍCULO N." abre un articulo: titulo del encabezado (limpio, sin
      tags ni saltos internos) y texto literal (FR-003) hasta el siguiente
      articulo.
    - El libro vigente es el último "LIBRO <numeral>" anterior al articulo ("I"
      si no hay ninguno); la parte se deriva del libro (II general, III urbano,
      IV rural; el resto sin parte).
    - Las UPLs mencionadas y los articulos derogados se extraen del texto con
      regex y se deduplican.

    Fail fast: sin ningún "ARTÍCULO" el HTML no es el documento esperado y se
    lanza ValueError con mensaje accionable.
    """
    if MARCA_ANCLA in html:
        return _parsear_formato_sisjur(html)
    return _parsear_formato_demo(html)


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


# Tamaño máximo de documentos por llamada de embedding/upsert. El servidor
# Ollama remoto rechaza lotes grandes de embeddings (evidencia empírica:
# n=200 funciona, n=500 falla), por eso 100 deja margen seguro. Se ajusta con
# la variable EMBEDDING_BATCH_SIZE sin tocar código.
BATCH_EMBEDDING_TAMANO = int(os.getenv("EMBEDDING_BATCH_SIZE", "100"))


def indexar_corpus(
    corpus: list[ArticuloNormativo],
    ruta_indice: str,
    embedding_function=None,
    batch_tamano: int = BATCH_EMBEDDING_TAMANO,
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

    El upsert se particiona en lotes de `batch_tamano` documentos para no saturar
    el servidor de embeddings remoto (ver `BATCH_EMBEDDING_TAMANO`); el resultado
    final es idéntico a un upsert único: mismos ids, documentos y metadatos.
    """
    if batch_tamano <= 0:
        raise ValueError(
            f"batch_tamano debe ser mayor que 0 (recibido: {batch_tamano})"
        )
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

    for inicio in range(0, len(ids), batch_tamano):
        coleccion.upsert(
            ids=ids[inicio : inicio + batch_tamano],
            documents=documents[inicio : inicio + batch_tamano],
            metadatas=metadatas[inicio : inicio + batch_tamano],
        )

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
DEFAULT_URL = os.getenv("CORPUS_URL", "https://www.alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=119582")
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
