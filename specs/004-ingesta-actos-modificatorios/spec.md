# Feature Specification

**Rama del feature**: `004-ingesta-actos-modificatorios`

**Creado**: 2026-08-14

**Estado**: Draft

**Entrada**: Descripción del usuario: "Feature 4 de mcp-bogota-factibilidad: ingesta de actos normativos que modifican el Decreto 555 de 2021 (corpus consolidado). El usuario podrá alimentar el RAG normativo con los actos (decretos/resoluciones) que reglamentan o modifican el Decreto 555 de 2021 (POT de Bogotá). Los documentos ingestados se integran en un corpus consolidado (hoy corpus fijo = Decreto 555/2021, 608 artículos en data/corpus/decreto_555_2021.jsonl, versionado en git con .sha256) consultado como un solo contexto por `consultar_normativa` (F2) y `get_feasibility_report` (F3)."

Decisiones de la especificación (2026-08-14):
1. **Corpus consolidado como única fuente de consulta**: el RAG consulta un solo contexto que agrupa el Decreto 555/2021 (norma base) y los actos modificatorios ingestados; `consultar_normativa` (F2) y `get_feasibility_report` (F3) lo usan sin cambiar sus contratos.
2. **Precedencia temporal vía prompt, sin ocultar artículos**: cuando un acto posterior reglamenta o modifica un artículo del 555, la preeminencia del acto posterior se comunica al LLM en el prompt; los artículos del 555 permanecen en el corpus (coexistencia de fuentes).
3. **Formatos soportados**: HTML sisjur (formato recomendado, reutiliza el parser existente de anclas `class="ancla"` y `Norma1.jsp?i=N`), PDF, DOCX, Markdown y TXT. La deduplicación es por hash SHA-256 del archivo.
4. **El 555 permanece como norma base**: sus 608 artículos (JSONL versionado en git) no se modifican; los actos se integran al corpus consolidado.

---

## Contexto y problema

El RAG normativo (F2) conoce hoy un solo documento: el Decreto 555 de 2021 (POT "Bogotá Reverdece 2022-2035"), con 608 artículos en `data/corpus/decreto_555_2021.jsonl` (fuente de verdad versionada en git con `.sha256`). Sin embargo, el POT es una norma viva: desde su adopción, Bogotá ha expedido **75+ actos administrativos** (26 decretos + 49 resoluciones, a noviembre de 2023) que reglamentan o modifican artículos del 555. Ejemplos reales verificados:

- **Decreto 122 de 2023**: reglamenta los artículos 233, 243 y 384 (vivienda colectiva).
- **Decreto 165 de 2023**: reglamenta el artículo 499 (legalización).
- **Decreto 083 de 2023**: reglamenta los artículos 218-219.
- **Decreto 072 de 2023**: espacio público.
- **Decreto 263 de 2023**: Manual de Espacio Público.
- **Decreto 427 de 2023**: Plan de Cuidado.
- **Decretos 506 y 520 de 2022**: obligaciones urbanísticas.

Fuente oficial catalogada: micrositio POT de la Secretaría Distrital de Planeación (https://www.sdp.gov.co/micrositios/pot/decreto-pot-bogota-2021), con enlaces PDF directos y el archivo Excel `Actos-Administrativos-Adoptados-POT.xlsx` como catálogo. El 555 está **VIGENTE**: el Concepto 2202413038 de 2024 lo confirma, y la suspensión provisional de 2022 fue revocada por auto del 22/08/2022.

**Problema**: las consultas normativas (`consultar_normativa`) y la evidencia normativa del informe de factibilidad (`get_feasibility_report`) responden solo con el texto original del 555, ignorando los actos posteriores que lo reglamentan o modifican. Un usuario que consulta "vivienda colectiva" recibe el artículo 233 del 555 pero no el Decreto 122 de 2023 que lo reglamenta: la respuesta puede quedar desactualizada frente al estado vigente del POT.

## Objetivo

El usuario alimenta el corpus normativo con los actos que reglamentan o modifican el Decreto 555 de 2021, en formatos HTML sisjur (recomendado — reutiliza el parser existente de anclas `class="ancla"`, cada acto tiene su `i=N` en la misma plantilla `Norma1.jsp?i=N`), PDF, DOCX, Markdown y TXT. Los documentos ingestados se integran en un **corpus consolidado** que `consultar_normativa` (F2) y `get_feasibility_report` (F3) consultan como un solo contexto, con trazabilidad por norma y precedencia temporal: el acto posterior prevalece y esa regla se comunica al LLM vía prompt, sin ocultar los artículos del 555.

---

## User Scenarios & Testing (obligatorio)

### User Story 1 (P1) — Ingestar un acto normativo que modifica el Decreto 555

Como usuario del MCP, quiero alimentar el corpus normativo con un acto administrativo (decreto o resolución) que reglamenta o modifica el Decreto 555 de 2021, en formatos HTML sisjur, PDF, DOCX, Markdown o TXT, para que sus disposiciones queden integradas en el corpus consolidado y sean consultables junto con el 555.

**Por qué esta prioridad**: es el núcleo de la feature — sin ingesta no hay corpus consolidado; el RAG seguiría conociendo únicamente el 555 y las consultas continuarían desactualizadas.

**Prueba independiente**: ejecutar la ingesta de un acto real (p. ej. el Decreto 122 de 2023, que reglamenta los artículos 233/243/384 de vivienda colectiva) y verificar que sus artículos quedan integrados al corpus consolidado con sus metadatos de norma y son consultables.

**Escenarios de aceptación**:

1. **Dado** un documento HTML en formato sisjur (con anclas `class="ancla"`, plantilla `Norma1.jsp?i=N`), **cuando** se ingesta, **entonces** sus artículos se parsean e integran al corpus consolidado con sus metadatos de norma y quedan consultables.
2. **Dado** un documento en PDF, DOCX, Markdown o TXT con contenido normativo, **cuando** se ingesta, **entonces** sus artículos se extraen e integran al corpus consolidado con sus metadatos de norma.
3. **Dado** un archivo con formato no soportado, **cuando** se intenta ingestar, **entonces** el sistema lo rechaza con un error claro y tipificado y el corpus existente NO se modifica.
4. **Dado** un documento ya ingestado (mismo hash SHA-256 del archivo), **cuando** se intenta ingestar de nuevo, **entonces** el sistema lo detecta y NO duplica artículos ni fragmentos en el corpus.

### User Story 2 (P1) — Consultar el corpus consolidado con identificación de norma y precedencia temporal

Como usuario del MCP, quiero que `consultar_normativa` responda con fragmentos del corpus consolidado indicando la norma de cada resultado (555 o acto modificatorio) y aplicando la regla de precedencia temporal (el acto posterior prevalece, comunicada al LLM vía prompt y sin ocultar artículos), para fundamentar la respuesta en la norma vigente aplicable al tema consultado.

**Por qué esta prioridad**: es el valor directo de la feature para el usuario — que la consulta normativa refleje el estado vigente del POT con sus reglamentaciones y modificaciones.

**Prueba independiente**: consultar un tema reglamentado por un acto posterior (p. ej. vivienda colectiva, reglamentada por el Decreto 122 de 2023) y verificar que la respuesta menciona el acto modificatorio como norma de origen y que el LLM prioriza el acto posterior sin ocultar el artículo original del 555.

**Escenarios de aceptación**:

1. **Dado** un tema reglamentado por un acto posterior, **cuando** se consulta en `consultar_normativa`, **entonces** cada fragmento de la respuesta indica su norma de origen (p. ej. "Decreto 122 de 2023") y el LLM recibe la precedencia temporal del acto posterior.
2. **Dado** un tema cubierto solo por el Decreto 555, **cuando** se consulta, **entonces** los resultados indican que provienen del 555 (norma base) y el LLM responde con esa fuente.
3. **Dado** que un acto modificatorio y el 555 cubren el mismo artículo, **cuando** se consulta, **entonces** ambos aparecen en los resultados (no se ocultan artículos) y el prompt comunica que el acto posterior prevalece sobre el texto del 555.

### User Story 3 (P2) — Informe de factibilidad con evidencia del corpus consolidado

Como usuario del MCP, quiero que `get_feasibility_report` use el corpus consolidado para su bloque de evidencia normativa sin romper su contrato — el `source_trace` de bloque se conserva y la norma real de cada fragmento se expone de forma aditiva por ítem —, para que el informe cite la norma vigente aplicable al lote (555 o acto modificatorio).

**Por qué esta prioridad**: depende de US1 y US2 (corpus consolidado y consulta con precedencia temporal) y es el consumidor final de la evidencia; por eso es P2.

**Prueba independiente**: invocar `get_feasibility_report` para un lote cuyo tema está reglamentado por un acto posterior y verificar que `normative_evidence` cita la norma real (555 o acto modificatorio) en la identificación de norma por ítem, conservando la estructura del contrato de F3.

**Escenarios de aceptación**:

1. **Dado** un lote con evidencia normativa en el corpus consolidado, **cuando** se genera el informe, **entonces** `normative_evidence` devuelve fragmentos con cita literal y expone la norma real de cada fragmento a nivel de ítem (`source_name`/`norma` por ítem), conservando el shape del bloque (el `source_trace` de bloque permanece intacto).
2. **Dado** el mismo lote y los mismos datos del corpus, **cuando** se genera el informe dos veces, **entonces** el resultado es idéntico (determinismo del scoring de F3, sin LLM en el score ni en las interpretaciones).
3. **Dado** que la infraestructura RAG no está disponible o la consulta no produce resultados, **cuando** se genera el informe, **entonces** `normative_evidence` se degrada vacío con advertencia explícita, sin romper el contrato de F3.

### Edge Cases

- **Formato no soportado**: error claro y tipificado; el corpus existente NO se modifica (fallo atómico por documento).
- **Archivo duplicado (mismo hash SHA-256)**: la re-ingesta se detecta y no duplica artículos ni fragmentos.
- **Documento sin artículos parseables**: error descriptivo señalando que no se encontró contenido normativo (sin ingesta parcial).
- **Acto sin fecha de expedición o sin fecha de vigencia explícita**: se documenta la fecha conocida y la regla de precedencia se aplica con la información disponible; si no hay fecha, el acto se integra con la fecha de la URL de origen o se registra como pendiente de verificación.
- **Acto con fecha de expedición anterior a la vigencia del 555 (2021-12-30)**: no puede reglamentarlo ni modificarlo → se RECHAZA con error claro y tipificado, sin integrar al corpus.
- **Acto sin referencias verificables a artículos del 555**: se INTEGRA con advertencia y se deja constancia en los metadatos del documento (`relacion_con_555`) para revisión del operador (no se rechaza: la relación no siempre es verificable por máquina).
- **Colisión de numeración de artículos entre normas**: dos normas pueden tener "artículo 233"; la identidad del fragmento combina norma + artículo, y la respuesta siempre indica la norma de origen.
- **Artículos con numeración no numérica** ("Artículo Primero", "Artículo Único"): se normalizan a ordinales numéricos (Primero → 1, Único → 1) para la identidad norma+artículo; si no es normalizable, se rechaza con el error descriptivo de documento sin artículos parseables.
- **PDF escaneado sin texto extraíble**: error claro indicando que el documento no contiene texto extraíble (se sugiere el formato HTML sisjur).
- **DOCX con tablas o PDF con columnas**: el texto extraído se normaliza en orden de lectura; si el orden no es reconstruible de forma fiable, se recomienda el formato HTML sisjur (misma semántica que el PDF escaneado).
- **URL de origen no disponible durante la descarga**: error tipificado de fuente — en la ingesta CLI, fallo atómico por documento con error accionable (RuntimeError, exit code 1, misma semántica que `cmd_descargar` de F2); en las tools MCP, `FUENTE_5XX` — sin corromper el corpus.
- **Cambio del modelo de embeddings o de un documento del corpus**: el índice se reconstruye automáticamente (huella en metadatos de la colección), sin mezclar vectores de modelos distintos.
- **Corpus consolidado sin indexar**: `consultar_normativa` (F2) responde error tipificado `CORPUS_NO_INGESTADO` en el límite de la tool; `get_feasibility_report` (F3) degrada `normative_evidence` vacío con `causa: CORPUS_NO_INGESTADO` y warning `NORMATIVA_NO_DISPONIBLE`, SIN fallar el reporte (semántica F3).
- **Artículo del 555 modificado por un acto posterior**: ambos se conservan (coexistencia); la precedencia se comunica vía prompt, no ocultando el artículo base.

---

## Requirements (obligatorio)

### Functional Requirements

- **FR-001**: El sistema DEBE permitir alimentar el corpus normativo con actos administrativos (decretos y resoluciones) que reglamentan o modifican el Decreto 555 de 2021, en los formatos HTML sisjur (formato recomendado), PDF, DOCX, Markdown y TXT.
- **FR-002**: Para cada documento ingestado, el sistema DEBE capturar los metadatos `tipo_norma`, `numero`, `año`, `fecha_expedicion`, `fecha_vigencia`, `url_origen` y `titulo`, y DEBE asociarlos a cada fragmento (chunk) indexado del documento.
- **FR-003**: El corpus normativo consolidado (Decreto 555/2021 + actos modificatorios) DEBE ser la única fuente de consulta del RAG: `consultar_normativa` (F2) y `get_feasibility_report` (F3) DEBEN consultar el corpus consolidado.
- **FR-004**: Cada fragmento del corpus consolidado DEBE conservar la trazabilidad de fuente con los 5 campos: `source_name`, `layer_id`, `service_url`, `data_vigencia` y `query_timestamp`; cada ítem de `resultados` de `consultar_normativa` (F2) y cada ítem de `normative_evidence.items` de `get_feasibility_report` (F3) DEBE conservar sus campos existentes y ganar campos nuevos de identificación de norma y trazabilidad de fuente (`norma` y `source_name` por ítem, con el nombre de la norma, p. ej. "Decreto 555 de 2021" o "Decreto 122 de 2023"), SIN eliminar ni renombrar campos existentes; el `source_trace` de bloque de F3 se conserva.
- **FR-005**: La respuesta de `consultar_normativa` DEBE indicar la norma de cada fragmento devuelto (identificación del acto y su número, no solo el número de artículo), de modo que el usuario sepa si el fragmento proviene del 555 o de un acto modificatorio.
- **FR-006**: El sistema DEBE aplicar la regla de precedencia temporal: cuando un acto posterior reglamenta o modifica un artículo del 555, la preeminencia del acto posterior DEBE comunicarse al LLM vía prompt, SIN ocultar los artículos del 555 (coexistencia de fuentes).
- **FR-007**: El sistema DEBE deduplicar documentos por hash SHA-256 del archivo: re-ingestar el mismo archivo NO DEBE duplicar artículos ni fragmentos en el corpus.
- **FR-008**: El sistema DEBE reconstruir el índice vectorial automáticamente cuando cambie un documento del corpus o el modelo de embeddings (bge-m3, 1024 dimensiones; chat qwen3:8b con citation forcing); la huella del corpus y el modelo DEBEN persistirse en los metadatos de la colección.
- **FR-009**: El sistema DEBE rechazar con un error claro y tipificado los formatos no soportados y los documentos sin contenido normativo extraíble, SIN corromper el corpus existente (fallo atómico por documento).
- **FR-010**: La ingesta de documentos (descarga y parseo) NO DEBE requerir Ollama; solo la indexación y la consulta (embeddings y chat) DEBEN requerirlo, con la misma semántica de la feature 2.
- **FR-011**: La extensión al corpus consolidado NO DEBE romper los contratos de F2 y F3: `consultar_normativa` y `get_feasibility_report` DEBEN conservar su estructura de respuesta, su taxonomía de errores y su semántica de degradación; los campos existentes conservan su semántica y los campos nuevos se añaden de forma aditiva (extensión no destructiva).
- **FR-012**: El Decreto 555 de 2021 DEBE permanecer como norma base del corpus consolidado: sus 608 artículos se conservan tal cual y los actos modificatorios se integran sin eliminar ni reescribir los artículos originales.
- **FR-013**: El corpus consolidado DEBE versionarse en git como el corpus actual (JSONL + `.sha256` por documento), manteniendo el 555 como fuente de verdad y los índices derivados fuera de git.
- **FR-014**: El sistema DEBE validar la relación temporal y referencial de cada acto con el Decreto 555: rechaza con error tipificado los actos con fecha de expedición anterior a la vigencia del 555 (2021-12-30) y advierte, dejando constancia en los metadatos (`relacion_con_555`), cuando un acto no referencia artículos del 555.

### Key Entities

- **DocumentoNormativo (acto administrativo)**: representación de un acto (decreto o resolución) que reglamenta o modifica el Decreto 555/2021. Atributos: `tipo_norma`, `numero`, `año`, `fecha_expedicion`, `fecha_vigencia`, `url_origen`, `titulo`, `hash_sha256` (huella de deduplicación), `relacion_con_555` (constancia de la relación temporal/referencial del acto con el 555, para revisión del operador cuando no es verificable por máquina, FR-014). Relaciones: se ingesta en el CorpusConsolidado; contiene ArtículoNormativo.
- **CorpusConsolidado**: colección de documentos normativos (555 + actos modificatorios) que el RAG consulta como un solo contexto. Atributos: documentos integrantes, índice vectorial, huella SHA-256 del corpus, modelo de embeddings. Relaciones: agrega DocumentoNormativo; evoluciona el CorpusInfo de F2 (misma colección consultada por F2/F3).
- **ArtículoNormativo** (extendido de F2): artículo de una norma con su texto literal y ubicación en el documento. Atributos nuevos: `norma_id`, `tipo_norma`, `numero`, `año`, `fecha_vigencia` (identificación de la norma de origen). Relaciones: pertenece a un DocumentoNormativo; base del filtro territorial de F2 (parte, UPLs mencionadas).
- **Chunk** (extendido de F2): fragmento indexado en el vector store, derivado de un ArtículoNormativo. Atributos nuevos: metadatos de la norma de origen y `data_vigencia` de la norma. Relaciones: referencia al ArtículoNormativo y al DocumentoNormativo; su `source_name` identifica la norma real.

---

## Success Criteria

- **SC-001**: Al menos un acto administrativo real (p. ej. el Decreto 122 de 2023, vivienda colectiva) se ingesta correctamente y sus artículos quedan consultables en el corpus consolidado.
- **SC-002**: El 100% de los fragmentos devueltos por `consultar_normativa` indican la norma de origen (555 o acto modificatorio) en su trazabilidad y en la respuesta.
- **SC-003**: La re-ingesta del mismo archivo (mismo hash SHA-256) NO duplica artículos ni fragmentos (deduplicación 100%).
- **SC-004**: El 100% de las consultas sobre temas reglamentados por un acto posterior comunican la precedencia temporal al LLM vía prompt, sin ocultar los artículos del 555.
- **SC-005**: Los 185 tests de F1-F3 siguen pasando sin cambios en los campos existentes ni en su semántica; los tests de contrato se extienden de forma ADITIVA: las aserciones de shape exacto (p. ej. `set(resultado) == {...}` en `tests/contract/test_consultar_normativa.py` y el shape de `normative_evidence` en `test_get_feasibility_report.py`) se actualizan únicamente para incluir los campos nuevos, sin cambiar la semántica de los existentes.
- **SC-006**: La ingesta de un formato no soportado o de un documento sin contenido normativo NO corrompe el corpus existente (el corpus queda idéntico al estado previo).

---

## Assumptions

- El corpus consolidado se consulta como un solo contexto; los actos modificatorios NO sustituyen físicamente los artículos del 555 (coexistencia, FR-006/FR-012).
- La precedencia temporal es una regla comunicada al LLM vía prompt, no una eliminación de fuentes: "el acto posterior prevalece" sin ocultar el artículo base.
- La fuente oficial del catálogo de actos es el micrositio POT de la SDP (https://www.sdp.gov.co/micrositios/pot/decreto-pot-bogota-2021), con enlaces PDF directos y el Excel `Actos-Administrativos-Adoptados-POT.xlsx` como inventario; la descarga directa de cada acto se valida en la fase de planificación (research).
- El formato HTML sisjur es el recomendado porque reutiliza el parser existente de F2 (anclas `class="ancla"`, plantilla `Norma1.jsp?i=N`); los formatos PDF/DOCX/Markdown/TXT requieren extracción adicional de texto cuyo detalle se define en planificación.
- La deduplicación por hash SHA-256 aplica a nivel de archivo (documento), no a nivel de artículo.
- Los modelos Ollama se mantienen: `bge-m3` (embeddings, 1024 dimensiones) y `qwen3:8b` (chat con citation forcing de citas literales verificables).
- El 555 permanece como norma base: su JSONL versionado en git no se modifica; los actos se integran en el corpus consolidado (nuevos archivos JSONL + `.sha256` versionados).
- El 555 está vigente (Concepto 2202413038 de 2024; suspensión provisional de 2022 revocada por auto del 22/08/2022); no se modela la ventana temporal de suspensión.
- La trazabilidad de F3 a nivel de bloque (`source_trace` de `normative_evidence`) se conserva; la identificación de norma por fragmento se expone de forma aditiva a nivel de ítem (FR-004).
- El esquema de ids de chunks (`art-<NNN>` en F2) y la huella de la colección (`corpus_sha256` mono-documento) se extienden: ids `norma_id-art-<NNN>` (identidad norma+artículo) y huella multi-documento (un hash por documento en el registro del corpus consolidado); decisión de detalle en planificación.

---

## Clarifications

No quedaron marcadores [NEEDS CLARIFICATION] en la spec. Las decisiones de alcance se registran en "Decisiones de la especificación" (inicio) y en Assumptions:

- **Q1 — ¿Cómo consulta el RAG el corpus consolidado?** A: como un solo contexto; `consultar_normativa` (F2) y `get_feasibility_report` (F3) usan el corpus consolidado sin cambiar sus contratos (FR-003, FR-011).
- **Q2 — ¿Qué hace la precedencia temporal con los artículos del 555?** A: se comunica al LLM vía prompt (el acto posterior prevalece) y NO se ocultan artículos: coexistencia de fuentes (FR-006, FR-012).
- **Q3 — ¿Qué formatos soporta la ingesta?** A: HTML sisjur (recomendado, reutiliza el parser de anclas `class="ancla"` / `Norma1.jsp?i=N`), PDF, DOCX, Markdown y TXT; deduplicación por hash SHA-256 del archivo (FR-001, FR-007).

---

## Fuera de alcance

Fuera de alcance de esta feature:
- OCR de PDF escaneados (el formato HTML sisjur es el recomendado para documentos sin texto extraíble).
- Actualización automática del catálogo de actos desde el Excel de la SDP (`Actos-Administrativos-Adoptados-POT.xlsx`).
- Eliminación/derogación de actos ya ingestados del corpus.
- Control de versiones/ediciones de un mismo acto.
