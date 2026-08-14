# Research: Ingesta de actos normativos que modifican el Decreto 555 (corpus consolidado)

**Fase**: Phase 0 del comando `/speckit.plan` | **Fecha**: 2026-08-14
**Feature**: [spec.md](spec.md) | **Base**: constitución v1.0.0

Este documento registra las decisiones de diseño (D1–D7) y los hallazgos verificados en vivo
(H1–H7) para la Feature 4. Las decisiones se validaron contra el código existente de F1/F2/F3,
la fuente oficial sisjur (descargas reales del HTML y el PDF del Decreto 122 de 2023) y las
librerías de extracción candidatas (pypdf, pdfplumber, python-docx). El contrato resultante está
en [contracts/ingesta-actos-modificatorios.md](contracts/ingesta-actos-modificatorios.md) y el
modelo de datos en [data-model.md](data-model.md).

---

## Decisiones de diseño

### D1. La ingesta es una extensión CLI (patrón F2), sin tools MCP nuevas

**Decisión**: La ingesta de actos se expone como una **extensión del CLI existente**
`python -m app.ingesta.corpus` (nuevo subcomando `acto`), no como una tool MCP nueva. El MCP
queda solo de consulta, como hoy (7 tools).

**Por qué**: FR-010 exige que "la ingesta de documentos (descarga y parseo) NO DEBE requerir
Ollama; solo la indexación y la consulta", con "la misma semántica de la feature 2" — y en F2 la
ingesta es 100 % CLI (`cmd_descargar`, `cmd_indexar`, `cmd_full`). El edge case de la spec
"en las tools MCP, `FUENTE_5XX`" se interpreta como la semántica de error aplicable si una
futura tool expusiera la ingesta; hoy no existe tal tool y no se crea (YAGNI, Principio V). La
spec tampoco define una tool MCP de ingesta: las US son del usuario del MCP como consumidor de
las consultas, y el CLI es el mecanismo de alimentación (igual que F2).

**Evidencia**: `app/ingesta/corpus.py` expone `descargar`/`indexar`/`consultar`/`full` por CLI;
`crear_servidor_mcp()` en `app/main.py` registra solo las 7 tools de consulta.

### D2. Corpus consolidado: JSONL por documento (git) + colección ChromaDB única

**Decisión**: El corpus consolidado vive en `data/corpus/` como **fuente de verdad versionada
en git** (FR-013): el `decreto_555_2021.jsonl` (INALTERADO, FR-012) más un JSONL por acto en
`data/corpus/actos_modificatorios/<documento_id>.jsonl` con su `.sha256`. El **índice vectorial
derivado** (ChromaDB, `.data/chroma/`, gitignored) se mantiene en la **misma colección
`decreto_555_2021`** consultada por F2/F3, ahora con documentos múltiples: la identidad de cada
chunk es `norma_id-art-<NNN>` (assumption de la spec) y los metadatos del chunk identifican la
norma de origen.

**Por qué**: FR-003 exige que el corpus consolidado sea la única fuente de consulta del RAG y
FR-011 que F2/F3 no cambien su estructura ni semántica. Mantener el nombre y la interfaz de la
colección (`consultar_normativa` consulta la misma colección) es el cambio mínimo; la evolución
semántica (la colección ahora contiene el corpus consolidado) se documenta en `data-model.md` y
no requiere cambios en el path de consulta de F2/F3.

**Evidencia**: `app/providers/normativa.py` consulta la colección `decreto_555_2021`
(`VECTOR_DB_PATH=.data/chroma`); `data/corpus/decreto_555_2021.jsonl` + `.sha256` versionados en
git (FR-009 de F2).

### D3. Deduplicación por hash SHA-256 del archivo + identidad norma+artículo

**Decisión**: La deduplicación (FR-007, SC-003) se hace a nivel de **documento**: hash SHA-256
del archivo original (HTML/PDF/DOCX/MD/TXT recibido), guardado en el registro
`data/corpus/actos_modificatorios/.corpus_consolidado.json` junto con los metadatos del acto
(FR-002). Si el hash ya existe, la ingesta es un no-op con mensaje claro ("documento ya
ingestado"). La identidad de cada artículo/fragmento combina norma + artículo
(`norma_id-art-<NNN>`): dos normas pueden tener "artículo 233" sin colisión (edge case de la
spec).

**Por qué**: La spec (assumption) define la deduplicación "a nivel de archivo (documento), no a
nivel de artículo"; la identidad norma+artículo es la única forma segura de coexistencia
(FR-012) y de respuesta con norma de origen (FR-005).

**Evidencia**: F2 ya persiste la huella del documento fuente en la metadata de la colección y
`.sha256` por JSONL; el patrón se extiende a multi-documento (un hash por documento en el
registro).

### D4. Adaptación acotada del parser sisjur para variantes de marcado (`Nº.` y título en `<i>`)

**Decisión**: El parser de anclas de F2 (`parsear_articulos` en `app/ingesta/corpus.py`) se
reutiliza para los actos en HTML sisjur (formato recomendado) con una **adaptación acotada** de
dos puntos, sin tocar el flujo del 555:

1. **Número de artículo con ordinal**: aceptar `Nº.`/`N°.` normalizando el marcador ordinal
   (`º`/`°` → `.`) antes de comparar contra `numero_patron` (`(?:Artículo\s+)?N\.`).
2. **Título en `<i style="font-weight: bold;">`**: cuando tras el grupo del número venga un
   grupo `<i style="font-weight: bold;">` en lugar de un `<b>`, leer el título de ahí
   (fuente alternativa, no sustitutiva: el `<b>` sigue siendo la fuente para el 555).

**Por qué**: H2 (verificado en el HTML real de la 122) muestra que la plantilla sisjur varió:
`<b>Artículo</b><span class="ancla" id="N"></span> <b>Nº.</b> <i style="font-weight: bold;">Título.</i>`.
El parser actual falla en dos puntos: `_extraer_titulo_sisjur` busca el número con `N\.` (no
acepta `1º.`) y lee el título solo de grupos `<b>` (no de `<i style="font-weight: bold;">`).
La adaptación DEBE mantener los patrones actuales intactos (regresión garantizada por
`tests/contract/test_ingesta_f2.py`, que cubre los 608 artículos del 555).

**Evidencia**: H2, H5 (verificaciones en vivo).

### D5. Extracción de PDF/DOCX/Markdown/TXT: pypdf (primario) + python-docx, pdfplumber como alternativa

**Decisión**: Para los formatos no sisjur (FR-001) se usa una extracción genérica con detección
por extensión + magic bytes:

- **PDF**: `pypdf` (primario, ligero, verificado v6.16.0 en el PDF real del 122). Si el texto
  extraído es vacío → error tipificado "documento sin texto extraíble" (PDF escaneado; se sugiere
  HTML sisjur, edge case de la spec). Si el layout no reconstruye el orden de lectura
  (columnas/tablas) → alternativa `pdfplumber` (v0.11.10 verificado), que maneja mejor el
  espaciado ("MAYOR DE BOGOTÁ, D.C." vs "MAYORDE BOGOTÁ,D.C." en pypdf).
- **DOCX**: `python-docx` (verificado v1.2.0): párrafos en orden + tablas en orden de lectura;
  si el orden no es reconstruible → error tipificado recomendando HTML sisjur.
- **Markdown/TXT**: stdlib (`pathlib`, `re`); se extrae texto plano y se detectan encabezados
  de artículo.
- **Artículos**: patrón `Artículo Nº?\.?` con soporte de ordinales textuales (`Primero` → 1,
  `Único` → 1; edge case de la spec); si no hay artículos parseables → error tipificado
  "documento sin contenido normativo extraíble" (FR-009) sin ingesta parcial (fallo atómico).

**Por qué**: son las librerías estándar de extracción en el Stack Python del proyecto (pypdf y
python-docx son livianas y sin dependencias nativas; pdfplumber solo para el caso complejo).
Ambas son dependencias de **CLI de ingesta**, no del runtime MCP (FR-010).

**Evidencia**: H6 (pypdf/pdfplumber verificados en el PDF real del 122) y prueba sintética de
python-docx (párrafos, encabezados).

### D6. Metadatos de norma por fragmento y campos aditivos de respuesta (FR-002, FR-004, FR-005)

**Decisión**: Todo fragmento (JSONL y chunk) lleva los metadatos del acto (FR-002):
`norma_id`, `tipo_norma`, `numero`, `año`, `fecha_expedicion`, `fecha_vigencia`, `url_origen`,
`titulo_norma`, `relacion_con_555`. En la respuesta de `consultar_normativa` (F2) cada ítem de
`resultados` gana **dos campos aditivos**: `norma` (nombre legible, p. ej. "Decreto 122 de 2023")
y `source_name` (nombre de la fuente de trazabilidad, FR-004). En `get_feasibility_report` (F3)
cada ítem de `normative_evidence.items` gana los mismos campos aditivos; el `source_trace` de
bloque de F3 se conserva intacto (FR-004). Ningún campo existente se elimina ni renombra
(FR-011, SC-005).

**Por qué**: FR-004/FR-005 exigen que el usuario sepa la norma real de cada fragmento; FR-011
exige aditividad estricta. La identificación por norma está en el ítem (no en el bloque) porque
un bloque puede contener fragmentos de varias normas.

**Evidencia**: `tests/contract/test_consultar_normativa.py` y `test_get_feasibility_report.py`
aserciones de shape exacto (SC-005: se actualizan solo para incluir los campos nuevos).

### D7. Precedencia temporal comunicada vía prompt (FR-006, SC-004)

**Decisión**: El prompt del RAG (construcción del contexto en `app/providers/normativa.py`) gana
una **regla de precedencia temporal** explícita: cuando un acto posterior reglamente o modifique
un artículo del 555, el acto posterior prevalece; el LLM DEBE citar ambas normas sin ocultar los
artículos del 555 (coexistencia, FR-012). Los fragmentos recuperados se ordenan por
`fecha_vigencia` descendente (el acto más reciente primero) dentro del contexto; el citation
forcing de F2 (citas literales verificables) se mantiene sin cambios.

**Por qué**: FR-006/SC-004 definen la precedencia como regla de prompt, no como eliminación de
fuentes. La ordenación por vigencia hace que el LLM lea primero la norma vigente más reciente y
cumple "sin ocultar artículos".

**Evidencia**: `_construir_prompt`/citation forcing de F2 en `app/providers/normativa.py` (el
prompt ya exige citas literales; solo se añade la regla de precedencia y el orden).

---

## Hallazgos verificados en vivo

### H1. La fuente viva de la 122 responde 200 y el espejo sisjur.bogotajuridica.gov.co NO responde

Se descargó el HTML del Decreto 122 de 2023 desde `https://www.alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=139499`:
HTTP 200, ~91 KB, charset ISO-8859-1 (Latin-1; hay que decodificar con `latin-1`, no UTF-8). El
espejo `https://sisjur.bogotajuridica.gov.co/sisjur/normas/Norma1.jsp?i=139499` (usado como
`CORPUS_SERVICE_URL` en la doc de F2) **no responde** (timeout/HTTP 000). Conclusión: la
descarga por defecto debe apuntar a `alcaldiabogota.gov.co` (ya es el `DEFAULT_URL` de la
ingesta F2).

### H2. Estructura de anclas verificada en la 122: número en el ancla, ordinal `Nº.`, título en `<i>`

El HTML de la 122 usa la **misma plantilla de anclas** del 555 (`class="ancla"`), con 13 anclas
`id="1"` … `id="13"` (13 artículos). El encabezado de artículo verificado:

```html
<p class="MsoNormal"><b>Artículo</b><span style="font-size: 12pt;" class="ancla" id="1"></span>
<b>1º.</b>&nbsp;<i style="font-weight: bold;">Objeto y ámbito de aplicación.</i> El presente
decreto reglamenta los artículos <a href="../normas/Norma1.jsp?i=119582#233">233</a>, ...</p>
```

Diferencias con el 555 que exigen la adaptación D4: el número lleva **ordinal** (`1º.`, no `1.`)
y el título está en **`<i style="font-weight: bold;">`**, no en `<b>`. Los enlaces internos a
artículos del 555 (`Norma1.jsp?i=119582#233`) son la **referencia verificable por máquina** para
`relacion_con_555` (FR-014).

### H3. El sisjur del 555 (i=119582) devuelve HTTP 500 transitorio; no bloquea la feature

Durante la verificación, `https://www.alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=119582`
devolvió **HTTP 500 "Java heap space"** (error de memoria del servidor, fallo transitorio; la
página es grande, ~1.5 MB con 608 artículos). No bloquea: el corpus JSONL del 555 está
**versionado en git** (fuente de verdad) y la re-descarga solo se necesita si se cambia el
modelo de embeddings (índice derivado). La ingesta de actos (F4) descarga la **página del acto**
(pequeña, p. ej. 91 KB la 122), no el 555.

### H4. Datos bibliográficos verificados del Decreto 122 de 2023

- **Título**: "Por medio del cual se reglamentan los artículos 233, 243 y 384 del Decreto
  Distrital 555 de 2021, en lo relacionado con la vivienda colectiva y las soluciones
  habitacionales con servicios, y se dictan otras disposiciones".
- **Expedición**: 30/03/2023. **Entrada en vigencia**: 31/03/2023.
- **Publicación**: Registro Distrital No. 7686 del 30 de marzo de 2023.
- **Referencia al 555**: artículos 233 (vivienda colectiva y soluciones habitacionales con
  servicios), 243 (condición 2ª del cuadro de usos, área de actividad de grandes servicios
  metropolitanos) y 384 (estándares mínimos de vivienda VIS/VIP).
- **Referencia F2 del 555** (para la validación FR-014): Registro Distrital No. 7326 del
  29/12/2021, vigencia 30/12/2021.

Fuente: página sisjur oficial de la 122 (descargada en vivo) y resultados de búsqueda de la
misma fuente oficial.

### H5. El parser de anclas de F2 es reutilizable para la 122 sin cambios estructurales

La 122 contiene la marca `class="ancla"` (MARCA_ANCLA del parser), los ids de ancla son los
números de artículo (1–13) y los artículos siguen el patrón de párrafos `<p class="MsoNormal">`.
El flujo `_parsear_formato_sisjur` entra por la misma rama; solo fallan los dos puntos de D4
(ordinal y `<i>`), lo que confirma que la adaptación es acotada y que no hay que reescribir el
parser.

### H6. Librerías de extracción verificadas: pypdf y pdfplumber extraen el PDF real de la 122; python-docx lee DOCX

- El PDF oficial de la 122 (descargable desde la misma página sisjur) tiene **6 páginas con
  texto nativo**: `pypdf 6.16.0` extrae el texto (p. ej. "LA ALCALDESA MAYOR DE BOGOTÁ, D.C.")
  con algunos espacios colapsados ("MAYORDE", "D.C.,"); `pdfplumber 0.11.10` reconstruye mejor
  el espaciado ("MAYOR DE BOGOTÁ, D.C."). Ambos son suficientes para el pipeline; se elige pypdf
  como primario (D5) por simplicidad y pdfplumber como alternativa cuando el orden de lectura no
  se reconstruya.
- `python-docx 1.2.0` lee correctamente párrafos y encabezados de un DOCX sintético
  ("ARTÍCULO 1º. Objeto y ámbito de aplicación.").

### H7. La plantilla sisjur incluye un banner de derogación/compilación que la ingesta debe capturar

La página de la 122 muestra el banner oficial: **"Derogado y compilado por el art. 1526, Decreto
Único Distrital de Ordenamiento Territorial 670 de 2025"** (enlace `Norma1.jsp?i=191905#1526`).
Implicaciones:

- El parser sisjur DEBE capturar este banner como **metadato del documento** (`estado_documento`
  = `"derogado"`, `derogado_compilado_por` = `"Decreto 670 de 2025"`) sin romper el parseo de
  artículos (el banner vive fuera de los `<p class="MsoNormal">` del articulado).
- El acto **derogado sigue siendo parte del corpus consolidado** (SC-001 exige que el 122 sea
  consultable); la eliminación/derogación de actos ingestados está **fuera de alcance** de la
  spec. La precedencia temporal (D7) ya ordena por vigencia; el operador puede decidir en una
  feature futura si excluir actos derogados.
- Hallazgo de contexto: el **Decreto 670 de 2025** (Decreto Único Distrital de Ordenamiento
  Territorial) compila/deroga normas urbanísticas; NO forma parte del alcance de F4 (la spec
  define el alcance sobre actos que reglamentan/modifican el 555 y no incluye el catálogo
  automático SDP). Se documenta como contenido futuro candidato.
