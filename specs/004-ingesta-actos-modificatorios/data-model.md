# Data Model: Corpus consolidado del POT (Decreto 555 + actos modificatorios)

**Fase**: Phase 1 del comando `/speckit.plan` | **Fecha**: 2026-08-14
**Feature**: [spec.md](spec.md) | **Base**: constitución v1.0.0 y [research.md](research.md)

Este documento define el modelo de datos de la Feature 4: las entidades del dominio
(DocumentoNormativo, CorpusConsolidado), la **extensión aditiva** de las entidades de F2
(ArtículoNormativo, Chunk) y de la respuesta de `consultar_normativa`/`get_feasibility_report`,
las relaciones entre entidades, la trazabilidad y la taxonomía de errores de la ingesta. Los
nombres de campos y códigos se conservan en inglés donde el contrato lo exige (Principio I de la
constitución); toda la prosa está en español.

## Convenciones

- **Frontera de parsing** (Principio II): el JSON crudo de cada fuente se parsea **una sola
  vez** en el provider/módulo correspondiente mediante modelos pydantic v2. En F4 la frontera de
  ingesta vive en `app/ingesta/` (un módulo por frontera): `corpus.py` (sisjur/555, existente) y
  `actos.py` (nuevo: detección de formato + extracción genérica).
- **Dato derivado vs fuente de verdad**: el **corpus consolidado** (JSONL por documento + `.sha256`,
  versionado en git) es la **fuente de verdad** (FR-013); los **embeddings y el índice vectorial**
  son **dato derivado** (regenerables, gitignored en `.data/chroma/`, FR-008).
- **Aditividad estricta** (FR-011, SC-005): ningún campo existente de F1/F2/F3 se elimina ni
  renombra; los campos nuevos se añaden sin cambiar la semántica de los existentes.
- **Estado por dato**: toda entidad de fuente en vivo lleva `estado`
  (`"disponible"` | `"no_encontrado"`). Un dato ausente o no aplicable es `"no_encontrado"`,
  nunca cero ni vacío silencioso.
- **Trazabilidad**: cada fragmento del corpus consolidado lleva los 5 campos del `SourceTrace`
  (FR-004): `source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp`; la
  identificación de norma se expone de forma aditiva por ítem (`norma`, `source_name`).
- **Vigencias**: los fragmentos de normas distintas nunca se mezclan como una sola fotografía
  temporal (FR-014 de F2); cada fragmento conserva la vigencia de su norma (`data_vigencia`).
- **Coexistencia**: los actos modificatorios NO sustituyen físicamente los artículos del 555
  (FR-006, FR-012); la precedencia temporal es una regla de prompt, no una eliminación de
  fuentes.

---

## Entidades

### DocumentoNormativo (acto administrativo) — NUEVA (Key Entity)

Representación de un acto (decreto o resolución) que reglamenta o modifica el Decreto 555/2021
(spec, Key Entities). Cada acto produce un JSONL versionado en git (FR-013) y un hash SHA-256
del archivo fuente para deduplicación (FR-007).

| Campo | Tipo | Requerido | Descripción / Validación |
|-------|------|-----------|--------------------------|
| `tipo_norma` | `string` | sí | `"decreto"` \| `"resolucion"` (FR-002). |
| `numero` | `int` | sí | Número del acto (p. ej. `122`). |
| `año` | `int` | sí | Año del acto (p. ej. `2023`). |
| `documento_id` | `string` | sí | Identificador canónico del documento (equivale a `layer_id` en trazabilidad): `Decreto_122_2023` (patrón `Decreto_<NNN>_<AAAA>` / `Resolucion_<NNN>_<AAAA>`). |
| `titulo` | `string` | sí | Título oficial del acto (FR-002). |
| `fecha_expedicion` | `string` (ISO date) | sí | Fecha de expedición (p. ej. `2023-03-30`). DEBE ser ≥ `2021-12-30` (vigencia del 555, FR-014). |
| `fecha_vigencia` | `string` (ISO date) | sí | Fecha de entrada en vigencia (p. ej. `2023-03-31`). Es el `data_vigencia` de los fragmentos del acto. |
| `url_origen` | `string` | sí | URL oficial de la fuente (sisjur, p. ej. `https://www.alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=139499`). |
| `hash_sha256` | `string` | sí | Huella SHA-256 del **archivo** recibido (HTML/PDF/DOCX/MD/TXT). Base de deduplicación (FR-007, SC-003). |
| `formato` | `string` | sí | Formato del archivo fuente: `"sisjur_html"` \| `"pdf"` \| `"docx"` \| `"markdown"` \| `"txt"`. |
| `relacion_con_555` | `string` | sí | Constancia de la relación temporal/referencial con el 555 (FR-014): `"referencia_articulos"` (referencias verificables a artículos del 555) \| `"sin_referencia"` (se integra con advertencia; revisión del operador). |
| `articulos_referenciados` | `array<int>` | no | Artículos del 555 referenciados explícitamente (extraídos de los enlaces `Norma1.jsp?i=119582#NNN` en sisjur, H2). |
| `estado_documento` | `string` | no | Estado normativo según la fuente: `"vigente"` \| `"derogado"`. Se captura del banner sisjur de derogación/compilación (H7). |
| `derogado_compilado_por` | `string` | no | Texto del banner de derogación/compilación (p. ej. `"Derogado y compilado por el art. 1526, Decreto Único Distrital de Ordenamiento Territorial 670 de 2025"`). Solo si `estado_documento=derogado`. |

Reglas de dominio:

- **Rechazo (FR-014)**: si `fecha_expedicion < 2021-12-30`, el acto NO puede reglamentar ni
  modificar el 555 → error tipificado, no se integra, corpus intacto (fallo atómico).
- **Advertencia (FR-014)**: si no hay referencias verificables a artículos del 555,
  `relacion_con_555 = "sin_referencia"` + warning en la ingesta (no se rechaza).
- **Deduplicación (FR-007)**: si `hash_sha256` ya existe en el registro
  `.corpus_consolidado.json`, la ingesta es no-op ("documento ya ingestado").

### CorpusConsolidado — NUEVA (Key Entity)

Colección de documentos normativos (555 + actos modificatorios) que el RAG consulta como un solo
contexto (spec, Key Entities). Evoluciona el `CorpusInfo`/colección de F2 **sin cambiar el
nombre de la colección ni la interfaz de consulta** (FR-003, FR-011, research D2).

| Campo | Tipo | Requerido | Descripción / Validación |
|-------|------|-----------|--------------------------|
| `documento_base` | `string` | sí | `Decreto 555 de 2021 (POT Bogotá)` — norma base, INALTERADA (FR-012). |
| `documentos_actos` | `array<DocumentoNormativo>` | sí | Actos modificatorios integrados (0..N). |
| `registro` | `string` | sí | Ruta del registro versionado: `data/corpus/actos_modificatorios/.corpus_consolidado.json` (un hash SHA-256 + metadatos por documento; research D3). |
| `directorio_actos` | `string` | sí | `data/corpus/actos_modificatorios/` (JSONL + `.sha256` por acto, FR-013). |
| `coleccion` | `string` | sí | `decreto_555_2021` (misma colección ChromaDB consultada por F2/F3; research D2). |
| `hash_corpus` | `string` | derivado | Huella multi-documento (un hash por documento) persistida en la metadata de la colección; si cambia o cambia el modelo de embeddings → reconstrucción automática (FR-008). |
| `embedding_model` | `string` | derivado | `bge-m3` (1024 dims); persistido en metadata de la colección (FR-008). |

### ArtículoNormativo (extendido de F2) — MODIFICADA ADITIVAMENTE

Artículo de una norma (555 o acto) con su texto literal y sus metadatos de ubicación. Hereda
todos los campos de F2 (numeración, texto, libro/parte/sección, articulos_derogados,
upls_mencionadas) y **gana** los campos de identificación de norma (FR-002, spec Key Entities):

| Campo | Tipo | Requerido | Descripción / Validación |
|-------|------|-----------|--------------------------|
| `norma_id` | `string` | sí (actos) | Identificador canónico de la norma de origen (p. ej. `Decreto_122_2023`). Para el 555: `Decreto_555_2021`. |
| `tipo_norma` | `string` | sí (actos) | `"decreto"` \| `"resolucion"` (heredado del documento). |
| `numero` | `int` | sí (actos) | Número del acto (p. ej. `122`). |
| `año` | `int` | sí (actos) | Año del acto (p. ej. `2023`). |
| `fecha_vigencia` | `string` (ISO date) | sí (actos) | Vigencia de la norma (p. ej. `2023-03-31`). Es el `data_vigencia` del fragmento (FR-014). |
| `titulo_norma` | `string` | sí (actos) | Título oficial de la norma (p. ej. `Decreto 122 de 2023`). |

Reglas de dominio:

- La **identidad del fragmento** es `norma_id-art-<numero>` (research D3): dos normas pueden
  tener "artículo 233" sin colisión (edge case de la spec); el `numero` de artículo es único
  **dentro** de cada norma, no global.
- El 555 conserva exactamente su esquema actual de F2 (campos base) más los campos aditivos de
  norma con `norma_id=Decreto_555_2021` al integrarse al corpus consolidado (FR-012: el JSONL
  del 555 no se modifica; los campos aditivos se materializan en el índice/metadata de la
  colección).

### Chunk (extendido de F2) — MODIFICADA ADITIVAMENTE

Fragmento indexado en el vector store, derivado de un ArtículoNormativo. Hereda los campos de F2
(`id`, `articulo`, `titulo`, `libro`, `parte`, `seccion`, `texto`, `embedding`) y **gana** los
metadatos de la norma de origen y la trazabilidad (FR-004):

| Campo | Tipo | Requerido | Descripción / Validación |
|-------|------|-----------|--------------------------|
| `id` | `string` | sí | Identidad norma+artículo: `Decreto_122_2023-art-001` (F2 usaba `decreto555-2021-art-042-1`; el patrón del 555 se conserva para no romper ids existentes, los actos usan `norma_id-art-<NNN>`). |
| `norma_id` | `string` | sí | Norma de origen (p. ej. `Decreto_122_2023`). |
| `tipo_norma` | `string` | sí | `"decreto"` \| `"resolucion"`. |
| `numero` | `int` | sí | Número del acto. |
| `año` | `int` | sí | Año del acto. |
| `fecha_vigencia` | `string` | sí | Vigencia de la norma (metadato de filtro/orden, D7). |
| `titulo_norma` | `string` | sí | Nombre legible de la norma. |
| `source_name` | `string` | sí | Nombre de la fuente de trazabilidad (FR-004): `Decreto 555 de 2021 (POT Bogotá)` o `Decreto 122 de 2023`. |
| `data_vigencia` | `string` | sí | Vigencia de la norma (5º campo del SourceTrace; igual a `fecha_vigencia`). |
| `relacion_con_555` | `string` | no | Relación del acto con el 555 (heredado del documento, FR-014). |

---

## Respuestas extendidas de F2/F3 (campos aditivos por ítem)

> Aditividad estricta (FR-011, SC-005): los campos existentes conservan su nombre, tipo y
> semántica. Solo se añaden campos nuevos.

### `consultar_normativa` (F2) — `resultados[]`

Cada ítem de `resultados` conserva todos sus campos existentes y **gana**:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `norma` | `string` | Nombre legible de la norma de origen (FR-005): `Decreto 555 de 2021` \| `Decreto 122 de 2023`. |
| `source_name` | `string` | Nombre de la fuente de trazabilidad (FR-004). |

### `get_feasibility_report` (F3) — `normative_evidence.items[]`

Cada ítem de `items` conserva sus campos existentes y **gana** los mismos campos aditivos
(`norma`, `source_name`). El `source_trace` de bloque de `normative_evidence` se conserva
intacto (FR-004).

---

## Relaciones

```text
CorpusConsolidado 1 ── 1 DocumentoNormativo (base: Decreto 555 de 2021)
CorpusConsolidado 1 ── N DocumentoNormativo (actos modificatorios)
DocumentoNormativo 1 ── N ArtículoNormativo
ArtículoNormativo 1 ── N Chunk
Chunk 1 ── 1 ArtículoNormativo (deriva de)
CorpusConsolidado 1 ── 1 VectorStore (colección única `decreto_555_2021`, research D2)
```

Reglas:

- Un artículo pertenece a **exactamente una** norma (`norma_id`).
- La colección del vector store indexa **todos** los chunks del corpus consolidado; el filtro
  territorial de F2 (FR-002 de F2: parte/UPLs mencionadas) se aplica igual, ahora con los
  metadatos de norma disponibles (p. ej. filtro por `norma_id` si el operador lo requiere).
- La precedencia temporal (D7) se deriva de `fecha_vigencia` del chunk (orden descendente en el
  contexto del prompt), sin eliminar chunks (FR-006, FR-012).

---

## Errores de la ingesta (taxonomía F1–F3 intacta + códigos de ingesta)

La taxonomía canónica de `app/errores.py` (10 códigos) NO se modifica (FR-011). La ingesta CLI
usa errores tipificados propios con fallo atómico por documento (FR-009, SC-006):

| Situación | Comportamiento |
|-----------|----------------|
| Formato no soportado | Error descriptivo; el corpus existente NO se modifica (SC-006). |
| Documento sin texto extraíble (PDF escaneado) | Error descriptivo sugiriendo HTML sisjur (edge case de la spec). |
| Documento sin artículos parseables | Error descriptivo; sin ingesta parcial (FR-009). |
| `fecha_expedicion < 2021-12-30` | Rechazo tipificado (FR-014); corpus intacto. |
| URL de origen no disponible | CLI: `RuntimeError` con mensaje accionable, exit code 1 (misma semántica que `cmd_descargar` de F2). |
| Documento duplicado (mismo SHA-256) | No-op con mensaje claro; sin duplicados (FR-007, SC-003). |
| Documento sin referencia a artículos del 555 | Se integra con warning + `relacion_con_555="sin_referencia"` (FR-014). |
