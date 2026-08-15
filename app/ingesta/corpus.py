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
from typing import Any

import chromadb
import httpx
from chromadb.errors import NotFoundError
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

from app.errores import CorpusNoIngestadoError, OllamaNoDisponibleError
from app.models import (
    ArticuloNormativo,
    Chunk,
    CAMPOS_ADITIVOS_F4,
    COLECCION_NORMATIVA,
    CorpusInfo,
    DocumentoNormativo,
    FECHA_VIGENCIA_555,
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
# Encabezados de sección del documento original (SECCIÓN 4, SECCIÓN 4A,
# TÍTULO III, LIBRO VIII...) que quedan pegados al final de algunos cuerpos
# entre artículos (p. ej. el art. 300 termina en "SECCIÓN 4\nTRATAMIENTO
# URBANÍSTICO DE RENOVACIÓN URBANA"). La alternancia también cubre las formas
# compuestas SUBSECCIÓN y SUBCAPÍTULO, colocadas ANTES de su forma base
# (SECCIÓN/CAPÍTULO) por legibilidad: el anclaje (?:\A|\n) ya impide que
# "SECCIÓN" dentro de "SUBSECCIÓN" matchee (no va precedida de \n). La línea
# debe EMPEZAR por el encabezado (tras salto de línea o inicio de cadena) y el
# bloque debe llegar hasta el FINAL absoluto (\Z): las referencias normativas
# que no abren la línea ("...en el Capítulo 2 del Componente Rural del
# presente Plan.") nunca matchean. El \b tras la clase romana blinda contra
# falsos positivos: bajo re.IGNORECASE, [IVXLCDM]+ matchearía la "d" inicial
# de "TÍTULO del presente decreto..." y \b exige que la letra romana no
# continúe dentro de otra palabra. El nombre puede ir en la misma línea o en
# líneas siguientes.
PATRON_ENCABEZADO_SECCION = re.compile(
    r"(?:\A|\n)\s*(?:SUBSECCI[OÓ]N|SECCI[OÓ]N|T[IÍ]TULO|SUBCAP[IÍ]TULO|CAP[IÍ]TULO|LIBRO|PARTE)\s+"
    r"(?:\d+[A-Za-z]?|[IVXLCDM]+\b)\s*\.?[^\n]*(?:\n[^\n]*)*\Z",
    re.IGNORECASE,
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
# Variante sisjur del título del Decreto 122 (D4/H2): `<i style="font-weight:
# bold;">Título.</i>` reemplaza al `<b>` del 555. El lookahead exige el atributo
# font-weight+bold en la etiqueta de apertura para no tratar como título
# cualquier itálica del cuerpo.
ITALICA_BOLD_PATRON = re.compile(
    r"<i(?=[^>]*font-weight[^>]*bold)[^>]*>(.*?)</i>",
    re.DOTALL | re.IGNORECASE,
)
# Banner de derogación/compilación de la plantilla sisjur (H7): vive FUERA de
# los `<p class="MsoNormal">` del articulado (p. ej. "Derogado y compilado por
# el art. 1526, Decreto Único Distrital de Ordenamiento Territorial 670 de 2025").
BANNER_DEROGACION_PATRON = re.compile(
    r"Derogado(?:\s+y\s+compilado)?\s+por\s+el\s+art\.?\s+\d+,[^.\n]*",
    re.IGNORECASE,
)
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


def _normalizar_ordinal(texto: str) -> str:
    """Normaliza el ordinal sisjur (`1º.`/`1°.`) a punto plano (`1.`).

    La plantilla del Decreto 122 (D4/H2) marca el número del artículo con
    ordinal (`<b>1º.</b>`); el parser del 555 usa el punto plano (`<b>1. </b>`).
    El colapso de puntos evita que `1º.` -> `1..` deje un punto residual al
    comparar contra `numero_patron` (`(?:Artículo\s+)?N\.`).
    """
    return re.sub(r"\.{2,}", ".", re.sub(r"[º°]", ".", texto))


def _siguiente_grupo_titulo(html: str, cursor: int, fin_cuerpo: int):
    """Devuelve el siguiente grupo de título (`<b>` o `<i font-weight:bold>`).

    La plantilla sisjur del 122 (D4/H2) pone el título en
    `<i style="font-weight: bold;">` en lugar de `<b>`; se devuelve el primer
    grupo `<b>` O `<i>` desde `cursor` (el que aparezca antes). El `<b>` sigue
    siendo la fuente del título para el 555. Ambos grupos exponen la misma
    interfaz (group(1)/start()/end()).
    """
    bold = BOLD_PATRON.search(html, cursor, fin_cuerpo)
    italica = ITALICA_BOLD_PATRON.search(html, cursor, fin_cuerpo)
    if bold is None:
        return italica
    if italica is None:
        return bold
    return bold if bold.start() < italica.start() else italica


def _html_fuera_de_articulado(html: str) -> str:
    """Devuelve el HTML fuera de los párrafos `<p class="MsoNormal">` (H7).

    El banner de derogación/compilación de la plantilla sisjur vive fuera del
    articulado; extraerlo SOLO de ahí garantiza que el parseo de artículos no
    se vea afectado y que una referencia del cuerpo no se confunda con el banner.
    """
    return "".join(
        re.split(r'<p[^>]*class="MsoNormal"[^>]*>', html, flags=re.IGNORECASE)[::2]
    )


def _extraer_banner_derogacion(html: str) -> tuple[str | None, str | None]:
    """Devuelve (estado_documento, texto del banner) si hay banner de derogación.

    La plantilla sisjur muestra el banner oficial (H7): "Derogado y compilado
    por el art. 1526, Decreto Único Distrital de Ordenamiento Territorial 670
    de 2025". Devuelve (None, None) si el documento no trae banner; el acto
    derogado SIGUE formando parte del corpus consolidado (SC-001).
    """
    texto = _limpiar_html(_html_fuera_de_articulado(html))
    coincidencia = BANNER_DEROGACION_PATRON.search(texto)
    if coincidencia is None:
        return None, None
    return "derogado", coincidencia.group(0).strip()


def _extraer_titulo_sisjur(
    html: str, inicio: int, numero: int, fin_cuerpo: int
) -> tuple[str, int]:
    """Devuelve (titulo, inicio del cuerpo) para un articulo del formato sisjur.

    El titulo es el texto de los grupos posteriores al numero del articulo:
    `<b>` (555) o `<i style="font-weight: bold;">` (variante 122, D4/H2). El
    numero puede llevar ordinal sisjur (`1º.`/`1°.`), que se normaliza a punto
    plano antes de comparar contra `numero_patron` (D4). Word puede partir una
    palabra entre dos grupos ("4. P" + "rincipios..."), por eso se unen sin
    espacio cuando el HTML original no tenia ninguno entre ambos. Las
    anotaciones editoriales en `<a href>` se saltan; el cuerpo empieza en el
    primer texto visible que no es negrita, cursiva negrita ni anotacion.
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
                f"No se encontró el título del marcador del artículo {numero} en el "
                "HTML del Decreto 555/2021."
            )
        if numero_patron.match(_normalizar_ordinal(_limpiar_html(grupo.group(1)))):
            grupo_numero = grupo
        else:
            cursor = grupo.end()

    contenido_numero = _normalizar_ordinal(_limpiar_html(grupo_numero.group(1)))
    coincidencia = numero_patron.match(contenido_numero)
    cursor = grupo_numero.end()
    partes: list[str] = []
    if coincidencia:
        resto = contenido_numero[coincidencia.end():]
        # El resto del grupo del número solo se añade si es texto real: el
        # ordinal normalizado (`1º.` -> `1..`) y los espacios no son título.
        if resto.strip(" .º°"):
            partes.append(resto)

    while True:
        grupo = _siguiente_grupo_titulo(html, cursor, fin_cuerpo)
        if grupo is None:
            break
        entre = html[cursor:grupo.start()]
        entre_limpio = _limpiar_html(entre)
        # El cuerpo empieza en el primer texto visible: un `&nbsp;` de
        # separación entre número y título (variante 122) NO es cuerpo.
        if entre_limpio and re.search(r"\w", entre_limpio) and not _es_solo_anclas(entre):
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
    del cuerpo del artículo actual (frase huérfana "Artículo"). Se recorta hasta
    el inicio del grupo cuando el contenido limpio del último grupo `<b>`
    anterior a la frontera es exactamente "Artículo" (re.IGNORECASE) y entre ese
    grupo y el ancla no hay texto visible. En cambio, se conserva el fin original
    cuando NO se cumplen las condiciones de recorte: cuando el último grupo
    `<b>` no es exactamente "Artículo" o cuando hay texto visible entre el grupo
    y el ancla del siguiente artículo (esto también cubre los encabezados inline
    "Artículo N.", que no cumplen ninguna de las dos condiciones).
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


def _recortar_encabezados_seccion(texto: str) -> str:
    """Recorta SOLO del final del cuerpo los encabezados de sección normativa.

    El documento original (Decreto 555/2021) inserta encabezados de estructura
    (SECCIÓN, TÍTULO, CAPÍTULO, LIBRO, PARTE) entre artículos; cuando el
    artículo anterior los absorbe, su cuerpo termina con p. ej. "SECCIÓN 4\n
    TRATAMIENTO URBANÍSTICO DE RENOVACIÓN URBANA" (art. 300). Es texto real del
    Decreto pero ensucia la recuperación RAG, por eso se recorta.

    Solo actúa al FINAL del cuerpo: el bloque debe abrir con un encabezado al
    inicio de línea (tras salto de línea o inicio de cadena) y llegar hasta el
    final absoluto de la cadena (`\Z`). El nombre del encabezado puede ir en la
    misma línea o en las líneas siguientes ("SECCIÓN 4" + "TRATAMIENTO...").
    El recorte es iterativo: varios encabezados consecutivos al final (fin de
    capítulo + inicio de sección) se eliminan todos. Las referencias normativas
    que no abren la línea ("...en el Capítulo 2 del Componente Rural del
    presente Plan.") nunca se tocan.
    """
    while True:
        coincidencia = PATRON_ENCABEZADO_SECCION.search(texto)
        if coincidencia is None:
            return texto
        texto = texto[: coincidencia.start()].rstrip()


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
        texto = _recortar_encabezados_seccion(texto)

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


def chunk_articulo(
    articulo: ArticuloNormativo, norma_id: str | None = None
) -> list[Chunk]:
    """Parte un articulo en chunks indexables (data-model.md:128-143).

    Regla base: 1 chunk = 1 articulo con id `art-<numero>` y texto completo. Si
    el texto supera los 3000 caracteres se parte por parrafos (\\n) con solape
    de 1 parrafo: cada bloque siguiente empieza repitiendo el ultimo parrafo del
    bloque anterior como primer parrafo, y sus ids son `art-<numero>-<i>`. Cada
    chunk hereda los metadatos del articulo (articulo, titulo, libro, parte,
    seccion). Devuelve siempre al menos un chunk: texto vacio produce un chunk
    con texto "".

    Identidad norma+articulo (F4, data-model.md:121): si el articulo pertenece a
    un acto (norma_id presente, o pasado explicitamente), el id se prefija con
    `norma_id-art-<numero>`; el 555 conserva exactamente su patron F2 (`art-NNN`)
    para no romper ids existentes (FR-011).
    """
    prefijo = norma_id or articulo.norma_id or ""
    id_base = f"{prefijo}-art-{articulo.numero:03d}" if prefijo else f"art-{articulo.numero:03d}"
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
    ordenadas y UTF-8. Los campos aditivos F4 (`CAMPOS_ADITIVOS_F4`) se EXCLUYEN
    de la huella: el Decreto 555 los tiene en None y su JSONL versionado no se
    modifica (FR-012), por lo que su hash actual debe permanecer identico.
    Corpus iguales producen siempre la misma huella, lo que permite verificar
    integridad y actualidad del indice vectorial.
    """
    json_canonico = json.dumps(
        [articulo.model_dump(exclude=CAMPOS_ADITIVOS_F4) for articulo in corpus],
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

# --- Corpus consolidado (F4, T020): identidad de documentos y huella multi-doc ---
# Clave de metadata de la colección que persiste la huella multi-documento
# (data-model.md:85): un hash por documento del corpus consolidado. Es la base
# de la re-indexación aditiva (FR-008 E7): un documento NUEVO se upserta, un
# documento CAMBIADO reconstruye la colección.
METADATA_DOCUMENTOS_HASH = "hash_corpus"

# Identidad canónica del documento base (FR-012): el 555 conserva su esquema F2
# y su JSONL no se modifica; los campos aditivos se materializan en el índice.
DOCUMENTO_BASE_ID = "Decreto_555_2021"
DOCUMENTO_BASE_NOMBRE = "Decreto 555 de 2021"
DOCUMENTO_BASE_SOURCE = "Decreto 555 de 2021 (POT Bogotá)"


def _agrupar_por_documento(
    corpus: list[ArticuloNormativo],
) -> dict[str, list[ArticuloNormativo]]:
    """Agrupa los artículos por documento de origen preservando el orden (F4).

    La identidad del fragmento es norma+articulo (data-model.md:105): dos normas
    pueden tener "artículo 233" sin colisión; el 555 se agrupa bajo
    `DOCUMENTO_BASE_ID` (sus artículos no llevan `norma_id`, FR-012).
    """
    grupos: dict[str, list[ArticuloNormativo]] = {}
    for articulo in corpus:
        documento_id = articulo.norma_id or DOCUMENTO_BASE_ID
        grupos.setdefault(documento_id, []).append(articulo)
    return grupos


def _entrada_registro_por_documento(
    registro: dict[str, Any], documento_id: str
) -> dict[str, Any] | None:
    """Entrada del registro `.corpus_consolidado.json` para un documento (None si no existe).

    La entrada aporta `hash_sha256` (huella del ARCHIVO fuente, FR-007) y
    `relacion_con_555` (FR-014) que el ArticuloNormativo del acto no lleva.
    """
    for entrada in registro.get("documentos", []):
        if entrada.get("documento_id") == documento_id:
            return entrada
    return None


def _serializar_huella(huella: dict[str, str]) -> str:
    """Serializa la huella multi-documento a JSON plano (metadata escalar de ChromaDB).

    ChromaDB exige valores escalares en la metadata de la colección; el JSON
    plano de `{doc_id: hash, f"{doc_id}_archivo": hash_archivo}` cumple y es
    legible en las herramientas de inspección.
    """
    return json.dumps(huella, ensure_ascii=False, sort_keys=True)


def _parsear_huella(texto: str) -> dict[str, str]:
    """Reconstruye la huella multi-documento persistida (dict vacío si no existe)."""
    try:
        valor = json.loads(texto)
    except (json.JSONDecodeError, TypeError):
        return {}
    return valor if isinstance(valor, dict) else {}


def _huella_por_documento(
    corpus: list[ArticuloNormativo], registro: dict[str, Any]
) -> dict[str, str]:
    """Huella plana por documento del corpus: {doc_id: hash, f"{doc_id}_archivo": hash_archivo}.

    El hash del documento es `hash_documento` de sus artículos (huella F2 del
    contenido); la entrada `_archivo` solo existe para los actos y es el
    `hash_sha256` del ARCHIVO fuente en el registro (FR-007). Un acto cambiado
    difiere en la primera; un mismo contenido re-ingestado mantiene la segunda.
    """
    grupos = _agrupar_por_documento(corpus)
    huella: dict[str, str] = {}
    for documento_id, articulos in grupos.items():
        huella[documento_id] = hash_documento(articulos)
        if documento_id == DOCUMENTO_BASE_ID:
            continue
        entrada = _entrada_registro_por_documento(registro, documento_id)
        if entrada is not None and entrada.get("hash_sha256"):
            huella[f"{documento_id}_archivo"] = entrada["hash_sha256"]
    return huella


def _metadatos_norma(
    documento_id: str,
    articulo: ArticuloNormativo | None,
    registro: dict[str, Any],
) -> dict[str, Any]:
    """Metadatos extendidos de norma para los chunks (data-model.md:113-130).

    Devuelve SOLO claves con valor no None: ChromaDB rechaza valores None en la
    metadata. El 555 usa las constantes del documento base (FR-012: su JSONL no
    cambia); los actos leen los campos aditivos del articulo y la entrada del
    registro (`relacion_con_555`).
    """
    if documento_id == DOCUMENTO_BASE_ID:
        return {
            "norma_id": DOCUMENTO_BASE_ID,
            "fecha_vigencia": FECHA_VIGENCIA_555,
            "titulo_norma": DOCUMENTO_BASE_NOMBRE,
            "source_name": DOCUMENTO_BASE_SOURCE,
            "data_vigencia": FECHA_VIGENCIA_555,
        }
    entrada = _entrada_registro_por_documento(registro, documento_id)
    metadatos = {
        "norma_id": documento_id,
        "tipo_norma": articulo.tipo_norma if articulo else None,
        "numero_norma": articulo.numero_norma if articulo else None,
        "año": articulo.año if articulo else None,
        "fecha_vigencia": articulo.fecha_vigencia if articulo else None,
        "titulo_norma": articulo.titulo_norma if articulo else None,
        "source_name": articulo.titulo_norma if articulo else None,
        "data_vigencia": articulo.fecha_vigencia if articulo else None,
        "relacion_con_555": entrada.get("relacion_con_555") if entrada else None,
    }
    return {k: v for k, v in metadatos.items() if v is not None}


def _motivo_reconstruccion(
    metadata_coleccion: dict[str, Any],
    embedding_model: str,
    huella_entrante: dict[str, str],
) -> str | None:
    """Motivo de reconstrucción del índice (FR-008) o None si el flujo es aditivo.

    Reconstruye cuando: (a) el índice legado no persiste la huella del modelo de
    embeddings, (b) el modelo difiere, o (c) un documento presente en la huella
    persistida CAMBIÓ su hash de contenido (otra versión del corpus). Un
    documento NUEVO (ausente de la huella persistida) no dispara reconstrucción:
    su integración es aditiva (upsert de sus chunks, FR-008 E7).
    """
    if METADATA_EMBEDDING_MODEL not in metadata_coleccion:
        return (
            "Índice legado sin la huella del modelo de embeddings en sus "
            "metadatos (clave 'embedding_model' ausente)"
        )
    modelo_persistido = metadata_coleccion[METADATA_EMBEDDING_MODEL]
    if modelo_persistido != embedding_model:
        return (
            f"Índice con otro modelo de embeddings "
            f"({modelo_persistido} != {embedding_model})"
        )

    huella_persistida = _parsear_huella(
        metadata_coleccion.get(METADATA_DOCUMENTOS_HASH, "")
    )
    # `corpus_sha256` es la huella F2 del corpus base: cubre los índices creados
    # antes de la huella multi-documento (legacy).
    hash_base_persistido = huella_persistida.get(
        DOCUMENTO_BASE_ID, metadata_coleccion.get(METADATA_CORPUS_SHA256)
    )
    if (
        DOCUMENTO_BASE_ID in huella_entrante
        and hash_base_persistido is not None
        and hash_base_persistido != huella_entrante[DOCUMENTO_BASE_ID]
    ):
        hash_actual = huella_entrante[DOCUMENTO_BASE_ID]
        hash_previo = str(hash_base_persistido)[:16]
        return (
            f"Índice de otra versión del corpus (hash persistido {hash_previo}... "
            f"!= actual {hash_actual[:16]}...)"
        )

    for documento_id, hash_actual in huella_entrante.items():
        if documento_id.endswith("_archivo"):
            continue
        hash_persistido = huella_persistida.get(documento_id)
        if hash_persistido is not None and hash_persistido != hash_actual:
            return (
                f"Índice de otra versión del documento {documento_id} "
                f"(hash persistido {hash_persistido[:16]}... "
                f"!= actual {hash_actual[:16]}...)"
            )
    return None


def _buscar_registro(
    ruta_indice: str, ruta_registro: str | None = None
) -> dict[str, Any]:
    """Registro del corpus consolidado para la re-indexación aditiva (F4).

    Busca el registro en: (1) la ruta explícita si se pasa, (2) junto al índice
    (`<directorio_indice>/.corpus_consolidado.json`, patrón de los tests y de la
    ingesta local) y (3) la ruta canónica de la ingesta. Sin registro se devuelve
    la estructura vacía: el 555 es el único documento del corpus.
    """
    from app.ingesta.actos import RUTA_REGISTRO_POR_DEFECTO, leer_registro_corpus

    candidatos = []
    if ruta_registro:
        candidatos.append(ruta_registro)
    candidatos.append(str(Path(ruta_indice).parent / ".corpus_consolidado.json"))
    candidatos.append(RUTA_REGISTRO_POR_DEFECTO)
    for candidato in candidatos:
        if Path(candidato).exists():
            return leer_registro_corpus(candidato)
    return {"documento_base": "Decreto_555_2021", "documentos": []}


def _corpus_info(corpus: list[ArticuloNormativo], hash_actual: str) -> CorpusInfo:
    """CorpusInfo del índice: identifica el documento base (555) o el acto único.

    El corpus consolidado que incluye el 555 se reporta con las constantes del
    documento base (contrato F2 inalterado); un corpus de un solo acto se
    identifica con su `titulo_norma` y `fecha_vigencia`.
    """
    grupos = _agrupar_por_documento(corpus)
    if DOCUMENTO_BASE_ID in grupos:
        return CorpusInfo(
            documento=DOCUMENTO_BASE_SOURCE,
            vigencia=FECHA_VIGENCIA_555,
            hash_sha256=hash_actual,
            total_articulos=len(corpus),
        )
    documento_id = next(iter(grupos))
    primer = grupos[documento_id][0]
    return CorpusInfo(
        documento=primer.titulo_norma or documento_id,
        vigencia=primer.fecha_vigencia or FECHA_VIGENCIA_555,
        hash_sha256=hash_actual,
        total_articulos=len(corpus),
    )


def indexar_corpus(
    corpus: list[ArticuloNormativo],
    ruta_indice: str,
    embedding_function=None,
    batch_tamano: int = BATCH_EMBEDDING_TAMANO,
    ruta_registro: str | None = None,
) -> CorpusInfo:
    """Indexa el corpus en ChromaDB y devuelve metadatos del corpus indexado.

    El índice contiene EXACTAMENTE los chunks del corpus actual (FR-008): el
    hash SHA-256 del corpus, el modelo de embeddings efectivo y la huella
    multi-documento `hash_corpus` se persisten en los metadatos de la colección
    y distinguen los tres flujos: crear (colección inexistente), actualizar
    (mismo corpus y mismo modelo, `upsert` idempotente) y reconstruir (corpus
    distinto, modelo de embeddings distinto o índice legado sin la huella del
    modelo: se borra la colección y se re-indexa desde cero para no mezclar
    vectores de versiones previas ni de modelos distintos en el mismo HNSW).

    Con actos del corpus consolidado (F4, T020) la actualización es ADITIVA por
    documento (FR-008 E7): un acto nuevo se upserta sobre la misma colección con
    ids `norma_id-art-<NNN>` y su huella se fusiona en `hash_corpus`; un acto
    modificado dispara la reconstrucción completa. El upsert se particiona en
    lotes de `batch_tamano` documentos para no saturar el servidor de embeddings
    remoto (ver `BATCH_EMBEDDING_TAMANO`); el resultado final es idéntico a un
    upsert único: mismos ids, documentos y metadatos.
    """
    if batch_tamano <= 0:
        raise ValueError(
            f"batch_tamano debe ser mayor que 0 (recibido: {batch_tamano})"
        )
    if embedding_function is None:
        embedding_function = _crear_embedding_function()
    embedding_model = _etiqueta_embedding(embedding_function)

    registro = _buscar_registro(ruta_indice, ruta_registro)
    huella_entrante = _huella_por_documento(corpus, registro)
    hash_actual = hash_documento(corpus)
    metadata_indice = {
        "hnsw:space": "cosine",
        METADATA_CORPUS_SHA256: hash_actual,
        METADATA_EMBEDDING_MODEL: embedding_model,
        METADATA_DOCUMENTOS_HASH: _serializar_huella(huella_entrante),
    }

    Path(ruta_indice).parent.mkdir(parents=True, exist_ok=True)
    cliente = chromadb.PersistentClient(path=ruta_indice)

    try:
        coleccion = cliente.get_collection(
            name=COLECCION_NORMATIVA, embedding_function=embedding_function
        )
    except NotFoundError:
        coleccion = None

    hash_corpus_fusionado: str | None = None
    if coleccion is None:
        # Primera indexación: crear la colección con hash, modelo y huella multi-doc.
        coleccion = cliente.create_collection(
            name=COLECCION_NORMATIVA,
            embedding_function=embedding_function,
            metadata=metadata_indice,
        )
    else:
        metadata_coleccion = coleccion.metadata or {}
        motivo = _motivo_reconstruccion(
            metadata_coleccion, embedding_model, huella_entrante
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
        else:
            # Flujo aditivo (FR-008 E7): fusionar la huella persistida con la
            # entrante. `corpus_sha256` (huella F2 del 555) NO se toca: seguir
            # reflejando el corpus base mantiene el contrato F2 intacto.
            huella_fusionada = {
                **_parsear_huella(metadata_coleccion.get(METADATA_DOCUMENTOS_HASH, "")),
                **huella_entrante,
            }
            hash_corpus_fusionado = _serializar_huella(huella_fusionada)

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []

    for articulo in corpus:
        documento_id = articulo.norma_id or DOCUMENTO_BASE_ID
        metadatos_norma = _metadatos_norma(documento_id, articulo, registro)
        for chunk in chunk_articulo(articulo):
            ids.append(chunk.id)
            documents.append(chunk.texto)
            metadatas.append(
                {
                    "articulo": chunk.articulo,
                    "titulo": chunk.titulo,
                    "libro": chunk.libro,
                    "parte": chunk.parte or "",
                    "seccion": chunk.seccion or "",
                    "upls": ",".join(articulo.upls_mencionadas),
                    **metadatos_norma,
                }
            )

    for inicio in range(0, len(ids), batch_tamano):
        coleccion.upsert(
            ids=ids[inicio : inicio + batch_tamano],
            documents=documents[inicio : inicio + batch_tamano],
            metadatas=metadatas[inicio : inicio + batch_tamano],
        )

    # La huella multi-documento se persiste DESPUÉS del upsert: si el upsert
    # falla, la metadata de la colección sigue reflejando el estado anterior y
    # la siguiente indexación repite la integración aditiva (idempotente). Las
    # claves `hnsw:*` (p. ej. `hnsw:space`) son inmutables tras crear la
    # colección: ChromaDB rechaza `modify` que las incluya.
    if hash_corpus_fusionado is not None:
        metadatos_actualizables = {
            k: v
            for k, v in (coleccion.metadata or {}).items()
            if not str(k).startswith("hnsw:")
        }
        coleccion.modify(
            metadata={
                **metadatos_actualizables,
                METADATA_DOCUMENTOS_HASH: hash_corpus_fusionado,
            }
        )

    return _corpus_info(corpus, hash_actual)


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


def _articulo_enriquecido(
    articulo: ArticuloNormativo, documento: DocumentoNormativo
) -> ArticuloNormativo:
    """Copia del artículo con los campos aditivos F4 de su documento (data-model.md:88-111).

    El JSONL del acto ya los materializa al escribir (`_articulo_a_linea` de
    actos.py); aquí se aplican en memoria para la indexación cuando el llamador
    trabaja con los artículos extraídos directamente.
    """
    return articulo.model_copy(
        update={
            "norma_id": documento.documento_id,
            "tipo_norma": documento.tipo_norma,
            "numero_norma": documento.numero,
            "año": documento.año,
            "fecha_vigencia": documento.fecha_vigencia,
            "titulo_norma": (
                f"{documento.tipo_norma.capitalize()} "
                f"{documento.numero} de {documento.año}"
            ),
        }
    )


def _indexar_corpus_consolidado_completo(
    ruta_indice: str,
    embedding_function,
    batch_tamano: int = BATCH_EMBEDDING_TAMANO,
    ruta_registro: str | None = None,
    directorio_actos: str | Path | None = None,
) -> CorpusInfo:
    """Reconstruye el índice con el corpus consolidado completo (555 + actos).

    Lee el JSONL versionado del 555 (verificando su `.sha256`, FR-009) y el de
    cada acto del registro (verificando su propio `.sha256`); un acto registrado
    sin JSONL o con hash desactualizado aborta con `CorpusNoIngestadoError`
    (fail-fast: no se reconstruye un índice con documentos a medias, FR-008).
    """
    from app.ingesta.actos import (
        DIRECTORIO_ACTOS_POR_DEFECTO,
        RUTA_REGISTRO_POR_DEFECTO,
        leer_registro_corpus,
    )

    registro = leer_registro_corpus(ruta_registro or RUTA_REGISTRO_POR_DEFECTO)
    directorio = Path(directorio_actos or DIRECTORIO_ACTOS_POR_DEFECTO)

    corpus_555 = deserializar_corpus(RUTA_CORPUS)
    _verificar_hash_corpus(corpus_555)
    corpus_consolidado: list[ArticuloNormativo] = [*corpus_555]

    for entrada in registro.get("documentos", []):
        documento_id = entrada.get("documento_id")
        ruta_jsonl = directorio / f"{documento_id}.jsonl"
        ruta_sha = directorio / f"{documento_id}.jsonl.sha256"
        if not ruta_jsonl.exists() or not ruta_sha.exists():
            raise CorpusNoIngestadoError(
                detalle=(
                    f"El acto {documento_id} está registrado pero falta su JSONL "
                    f"({ruta_jsonl}) o su hash ({ruta_sha}). Re-ingesta el acto o "
                    "repara el registro antes de reconstruir el índice."
                )
            )
        articulos_acto = deserializar_corpus(str(ruta_jsonl))
        hash_guardado = ruta_sha.read_text(encoding="utf-8").strip()
        if hash_documento(articulos_acto) != hash_guardado:
            raise CorpusNoIngestadoError(
                detalle=(
                    f"El JSONL del acto {documento_id} no coincide con su hash "
                    f"persistido ({ruta_sha}). Re-ingesta el acto antes de "
                    "reconstruir el índice."
                )
            )
        corpus_consolidado.extend(articulos_acto)

    return indexar_corpus(
        corpus_consolidado,
        ruta_indice,
        embedding_function,
        batch_tamano,
        ruta_registro=ruta_registro,
    )


def indexar_acto(
    documento: DocumentoNormativo,
    articulos: list[ArticuloNormativo],
    ruta_indice: str,
    embedding_function=None,
    batch_tamano: int = BATCH_EMBEDDING_TAMANO,
    ruta_registro: str | None = None,
    directorio_actos: str | Path | None = None,
) -> CorpusInfo:
    """Indexa un acto en el índice consolidado (FR-008 E7, tasks.md T020).

    Enriquece los artículos con la identidad de norma (data-model.md:88-111) y
    los indexa ADITIVAMENTE sobre la colección única (upsert de sus chunks). Si
    la colección no existe, el modelo de embeddings cambió o el acto CAMBIÓ
    respecto al índice, reconstruye el corpus consolidado completo (555 + todos
    los actos del registro) para no mezclar vectores ni perder documentos
    (FR-008). Importa `app.ingesta.actos` de forma perezosa (evita el ciclo de
    importación del módulo).
    """
    from app.ingesta.actos import RUTA_REGISTRO_POR_DEFECTO, leer_registro_corpus

    registro = leer_registro_corpus(ruta_registro or RUTA_REGISTRO_POR_DEFECTO)
    articulos_enriquecidos = [_articulo_enriquecido(a, documento) for a in articulos]
    hash_acto = hash_documento(articulos_enriquecidos)

    if embedding_function is None:
        embedding_function = _crear_embedding_function()
    embedding_model = _etiqueta_embedding(embedding_function)

    Path(ruta_indice).parent.mkdir(parents=True, exist_ok=True)
    cliente = chromadb.PersistentClient(path=ruta_indice)

    try:
        coleccion = cliente.get_collection(
            name=COLECCION_NORMATIVA, embedding_function=embedding_function
        )
    except NotFoundError:
        coleccion = None

    motivo = None
    if coleccion is not None:
        metadata_coleccion = coleccion.metadata or {}
        if METADATA_EMBEDDING_MODEL not in metadata_coleccion:
            motivo = "Índice legado sin la huella del modelo de embeddings"
        elif metadata_coleccion[METADATA_EMBEDDING_MODEL] != embedding_model:
            motivo = (
                f"Índice con otro modelo de embeddings "
                f"({metadata_coleccion[METADATA_EMBEDDING_MODEL]} != {embedding_model})"
            )
        else:
            huella_persistida = _parsear_huella(
                metadata_coleccion.get(METADATA_DOCUMENTOS_HASH, "")
            )
            hash_persistido = huella_persistida.get(documento.documento_id)
            if hash_persistido is not None and hash_persistido != hash_acto:
                motivo = (
                    f"El acto {documento.documento_id} cambió respecto al índice "
                    f"(hash persistido {hash_persistido[:16]}... != actual "
                    f"{hash_acto[:16]}...)"
                )

    if coleccion is None or motivo is not None:
        # Reconstrucción completa: 555 + todos los actos del registro. Solo así
        # la colección contiene EXACTAMENTE el corpus actual (FR-008) sin perder
        # el 555 ni los actos previos.
        if motivo is not None:
            print(
                f"{motivo}. Reconstruyendo la colección desde cero para no mezclar "
                "vectores de corpus o modelos distintos."
            )
        return _indexar_corpus_consolidado_completo(
            ruta_indice,
            embedding_function,
            batch_tamano,
            ruta_registro=ruta_registro,
            directorio_actos=directorio_actos,
        )

    return indexar_corpus(
        articulos_enriquecidos,
        ruta_indice,
        embedding_function,
        batch_tamano,
        ruta_registro=ruta_registro,
    )


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


# --- Subcomando `acto` (T013/T014, Feature 4: ingesta de actos modificatorios) ---
# El pipeline usa los dispositivos de `app/ingesta/actos.py` (detección de
# formato, extracción genérica, validación FR-014 y escritura versionada) e
# importa ese módulo de forma perezosa dentro de las funciones: `actos.py`
# importa helpers de este módulo en su cabecera, así que una importación a
# nivel de módulo aquí crearía un ciclo de importación.

CABECERA_NORMA_PATRON = re.compile(
    r"\b(decreto|resolucion)\s+(?:n[º°]?\.?\s*)?(\d{1,4})\s+de\s+(\d{4})\b",
    re.IGNORECASE,
)
TITULO_HTML_PATRON = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
MESES_A_NUMERO = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
FECHA_ISO_PATRON = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
FECHA_DMA_PATRON = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
FECHA_LARGA_PATRON = re.compile(
    r"\b(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})\b", re.IGNORECASE
)
ETIQUETA_EXPEDICION_PATRON = re.compile(
    r"(?:fecha\s+de\s+)?(?:expedici[oó]n|expedid[oa]\s+(?:el\s+)?)", re.IGNORECASE
)
ETIQUETA_VIGENCIA_PATRON = re.compile(r"entrada\s+en\s+vigencia", re.IGNORECASE)
# Ventana de cabecera del documento: los metadatos de norma (encabezado y fecha)
# viven en la parte superior del documento, antes del articulado.
VENTANA_METADATOS = 12000


def _decodificar_texto_acto(contenido: bytes) -> str:
    """Decodifica el contenido del acto: UTF-8 con fallback latin-1.

    La fuente sisjur sirve ISO-8859-1 (latin-1); sin el fallback los acentos del
    título/encabezado romperían la decodificación.
    """
    try:
        return contenido.decode("utf-8")
    except UnicodeDecodeError:
        return contenido.decode("latin-1")


def _texto_para_metadatos(contenido: bytes, formato: str) -> str:
    """Texto visible de la cabecera del documento (FR-002).

    Solo la cabecera (primeras líneas/páginas) se usa para extraer los metadatos
    de la norma: el encabezado oficial precede al articulado y una fecha citada
    en el cuerpo no debe contaminar la fecha de expedición.
    """
    if formato == "sisjur_html":
        return _limpiar_html(_decodificar_texto_acto(contenido)[:VENTANA_METADATOS])
    if formato in ("txt", "markdown"):
        return _decodificar_texto_acto(contenido)[:VENTANA_METADATOS]
    if formato == "pdf":
        from io import BytesIO

        from pypdf import PdfReader

        lector = PdfReader(BytesIO(contenido))
        paginas = (pagina.extract_text() or "" for pagina in lector.pages[:2])
        return "\n".join(paginas)[:VENTANA_METADATOS]
    if formato == "docx":
        from io import BytesIO

        import docx

        documento = docx.Document(BytesIO(contenido))
        parrafos = (parrafo.text for parrafo in documento.paragraphs[:60])
        return "\n".join(parrafos)[:VENTANA_METADATOS]
    return ""


def _metadatos_norma_desde_texto(texto: str) -> tuple[str, int, int] | None:
    """(tipo_norma, numero, año) de la cabecera de la norma (FR-002) o None.

    Reconoce el encabezado canónico "DECRETO 122 DE 2023" (o "RESOLUCION N. 123
    DE 2024") en el texto visible del documento. Devuelve None si no hay
    encabezado reconocible (fail-fast en cmd_acto).
    """
    coincidencia = CABECERA_NORMA_PATRON.search(texto)
    if coincidencia is None:
        return None
    return (
        coincidencia.group(1).lower(),
        int(coincidencia.group(2)),
        int(coincidencia.group(3)),
    )


def _titulo_desde_html(html: str) -> str | None:
    """Texto del `<title>` del HTML sisjur, limpio (None si no hay `<title>`)."""
    coincidencia = TITULO_HTML_PATRON.search(html)
    if coincidencia is None:
        return None
    titulo = _limpiar_html(coincidencia.group(1))
    return titulo or None


def _fecha_desde_texto(texto: str) -> str | None:
    """Primera fecha del texto, normalizada a AAAA-MM-DD.

    Acepta los formatos AAAA-MM-DD, DD/MM/AAAA y "30 de marzo de 2023".
    """
    coincidencia = FECHA_ISO_PATRON.search(texto)
    if coincidencia:
        return coincidencia.group(0)
    coincidencia = FECHA_DMA_PATRON.search(texto)
    if coincidencia:
        return (
            f"{int(coincidencia.group(3)):04d}-"
            f"{int(coincidencia.group(2)):02d}-"
            f"{int(coincidencia.group(1)):02d}"
        )
    coincidencia = FECHA_LARGA_PATRON.search(texto)
    if coincidencia:
        mes = MESES_A_NUMERO.get(coincidencia.group(2).lower())
        if mes is not None:
            return (
                f"{int(coincidencia.group(3)):04d}-"
                f"{mes:02d}-"
                f"{int(coincidencia.group(1)):02d}"
            )
    return None


def _fecha_cerca_de_etiqueta(texto: str, etiqueta_patron: re.Pattern[str]) -> str | None:
    """Fecha que sigue a una etiqueta (p. ej. "Fecha de expedición: 30/03/2023")."""
    coincidencia = etiqueta_patron.search(texto)
    if coincidencia is None:
        return None
    ventana = texto[coincidencia.end(): coincidencia.end() + 120]
    return _fecha_desde_texto(ventana)


def _formato_desde_contenido(contenido: bytes, url: str) -> str:
    """Detecta el formato de un acto descargado por URL (magic bytes + extensión).

    Para --url no hay archivo local que pasar a `detectar_formato`; el contenido
    manda (magic bytes: `%PDF-`, `PK\x03\x04` o HTML) y la extensión de la URL es
    el fallback (misma jerarquía que `detectar_formato` de actos.py).
    """
    from app.ingesta.actos import FORMATOS_POR_EXTENSION, ErrorIngesta

    if contenido.startswith(b"%PDF-"):
        return "pdf"
    if contenido.startswith(b"PK\x03\x04"):
        return "docx"
    if re.search(rb"<!DOCTYPE\s+html|<html[\s>]", contenido[:1024], re.IGNORECASE):
        return "sisjur_html"
    ruta_url = url.split("?")[0]
    formato = FORMATOS_POR_EXTENSION.get(Path(ruta_url).suffix.lower())
    if formato is None:
        raise ErrorIngesta(
            "FORMATO_NO_SOPORTADO",
            "la respuesta de la URL no es un formato soportado (HTML sisjur, PDF, "
            "DOCX, Markdown, TXT). El corpus existente NO se modificó.",
        )
    return formato


def cmd_acto(args) -> None:
    """Ingesta un acto normativo que reglamenta o modifica el Decreto 555/2021.

    Pipeline (T013/T014, contracts/ingesta-actos-modificatorios.md): fuente
    (--url XOR --archivo) → formato → extracción de artículos → metadatos FR-002
    → validación FR-014 → deduplicación por hash (FR-007) → escritura JSONL +
    .sha256 + registro (FR-013). Fallo atómico por documento (FR-009, SC-006):
    cualquier error deja el corpus existente intacto.

    Importa `app.ingesta.actos` de forma perezosa para evitar el ciclo de
    importación (actos.py importa helpers de este módulo en su cabecera).
    """
    from app.ingesta.actos import (
        ErrorIngesta,
        detectar_formato,
        escribir_documento_acto,
        extraer_articulos,
        extraer_articulos_referenciados,
        extraer_documento_sisjur,
        hash_archivo,
        validar_relacion_con_555,
    )

    # 1. Fuente: bytes del acto (--url o --archivo).
    if args.archivo:
        try:
            contenido = Path(args.archivo).read_bytes()
        except FileNotFoundError as e:
            raise ErrorIngesta(
                "FUENTE_NO_DISPONIBLE",
                f"el archivo '{args.archivo}' no existe o no es accesible. "
                "Verifica la ruta o usa --url. El corpus existente NO se modificó.",
            ) from e
        formato = detectar_formato(args.archivo)
        url_origen = "cli"
    else:
        try:
            response = httpx.get(args.url, timeout=30.0)
            response.raise_for_status()
            contenido = response.content
        except Exception as e:
            print(
                f"Error de ingesta [FUENTE_NO_DISPONIBLE]: no se pudo descargar el "
                f"acto desde {args.url}: {e}. Reintenta o descarga manualmente y "
                "usa --archivo. El corpus existente NO se modificó.",
                file=sys.stderr,
            )
            sys.exit(3)
        formato = _formato_desde_contenido(contenido, args.url)
        url_origen = args.url

    # 2. Extracción de artículos + metadatos de estado (sisjur H7).
    if formato == "sisjur_html":
        articulos, estado_documento, derogado_compilado_por = extraer_documento_sisjur(
            contenido
        )
        html_texto = _decodificar_texto_acto(contenido)
        articulos_referenciados = extraer_articulos_referenciados(html_texto)
    else:
        articulos = extraer_articulos(contenido, formato)
        estado_documento = None
        derogado_compilado_por = None
        articulos_referenciados = []

    # 3. Metadatos FR-002 desde la cabecera del documento (fail-fast si faltan).
    texto_metadatos = _texto_para_metadatos(contenido, formato)
    metadatos = _metadatos_norma_desde_texto(texto_metadatos)
    if metadatos is None:
        raise ErrorIngesta(
            "METADATOS_INCOMPLETOS",
            "no se pudo identificar la norma en el documento (se busca el "
            "encabezado 'DECRETO 122 DE 2023' o similar). Verifica que el "
            "encabezado oficial esté presente o usa el formato HTML sisjur. El "
            "corpus existente NO se modificó.",
        )
    tipo_norma, numero, año = metadatos

    fecha_expedicion = _fecha_cerca_de_etiqueta(
        texto_metadatos, ETIQUETA_EXPEDICION_PATRON
    )
    if fecha_expedicion is None:
        raise ErrorIngesta(
            "METADATOS_INCOMPLETOS",
            "no se pudo determinar la fecha de expedición del acto en el "
            "documento (se busca 'Fecha de expedición: 30/03/2023'). Sin la "
            "fecha no se puede validar la relación con el Decreto 555 (FR-014). "
            "El corpus existente NO se modificó.",
        )
    fecha_vigencia = (
        _fecha_cerca_de_etiqueta(texto_metadatos, ETIQUETA_VIGENCIA_PATRON)
        or fecha_expedicion
    )

    if formato == "sisjur_html":
        titulo = _titulo_desde_html(_decodificar_texto_acto(contenido))
    else:
        titulo = None
    if titulo is None:
        titulo = f"{tipo_norma.capitalize()} {numero} de {año}"
    documento_id = f"{tipo_norma.capitalize()}_{numero}_{año}"

    # 4. Validación FR-014 + modelo tipado.
    relacion_con_555 = validar_relacion_con_555(fecha_expedicion, articulos_referenciados)
    documento = DocumentoNormativo(
        tipo_norma=tipo_norma,
        numero=numero,
        año=año,
        documento_id=documento_id,
        titulo=titulo,
        fecha_expedicion=fecha_expedicion,
        fecha_vigencia=fecha_vigencia,
        url_origen=url_origen,
        hash_sha256=hash_archivo(contenido),
        formato=formato,
        relacion_con_555=relacion_con_555,
        articulos_referenciados=articulos_referenciados,
        estado_documento=estado_documento,
        derogado_compilado_por=derogado_compilado_por,
    )

    # 5. Escritura versionada + registro (dedup FR-007, fallo atómico FR-009).
    ruta_registro = Path(args.output) / ".corpus_consolidado.json"
    resultado = escribir_documento_acto(
        contenido,
        documento,
        articulos,
        ruta_registro=ruta_registro,
        directorio_salida=args.output,
        indexado=args.indexar,
    )

    if args.indexar and not resultado["duplicado"]:
        try:
            indexar_acto(
                documento,
                articulos,
                args.ruta_indice,
                ruta_registro=ruta_registro,
                directorio_actos=args.output,
            )
        except (httpx.RequestError, ConnectionError, TimeoutError) as e:
            modelo = os.getenv("OLLAMA_EMBEDDING_MODEL", "bge-m3")
            print(
                f"⚠ Ollama no disponible: {e}. "
                f"Verifica 'ollama serve' y ejecuta 'ollama pull {modelo}'"
            )
            raise OllamaNoDisponibleError(modelo=modelo) from e
        print(
            f"Acto indexado aditivamente en el corpus consolidado "
            f"(índice: {args.ruta_indice})."
        )
    elif args.indexar:
        print(
            "Acto duplicado (FR-007): la ingesta fue no-op y no se re-indexó.",
            file=sys.stderr,
        )

    print(json.dumps(resultado, ensure_ascii=False, indent=2))


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
    # Import perezoso para evitar el ciclo de importación: `actos.py` importa
    # helpers de este módulo en su cabecera (solo se importa al ejecutar el CLI).
    from app.ingesta.actos import DIRECTORIO_ACTOS_POR_DEFECTO, ErrorIngesta

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

    # --acto
    p_acto = subparsers.add_parser(
        "acto",
        help="Ingesta un acto normativo (decreto/resolución) que modifica el Decreto 555/2021",
    )
    fuente_acto = p_acto.add_mutually_exclusive_group(required=True)
    fuente_acto.add_argument(
        "--url",
        help="URL sisjur del acto (p. ej. https://www.alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=139499)",
    )
    fuente_acto.add_argument(
        "--archivo",
        help="Ruta local del acto (HTML sisjur, PDF, DOCX, Markdown o TXT)",
    )
    p_acto.add_argument(
        "--output",
        default=DIRECTORIO_ACTOS_POR_DEFECTO,
        help="Directorio de salida del JSONL + .sha256 y del registro "
        "(default: data/corpus/actos_modificatorios/)",
    )
    p_acto.add_argument(
        "--indexar",
        action="store_true",
        help="Indexa el acto aditivamente sobre el corpus consolidado (T020)",
    )
    p_acto.add_argument(
        "--ruta-indice",
        default=DEFAULT_INDICE,
        help="Ruta al índice ChromaDB (default: .data/chroma)",
    )

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
        elif args.comando == "acto":
            cmd_acto(args)
    except ErrorIngesta as e:
        print(f"Error de ingesta [{e.codigo}]: {e.mensaje}", file=sys.stderr)
        sys.exit(1)
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
