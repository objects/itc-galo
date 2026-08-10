# Data Model: RAG normativo del POT (Decreto 555/2021) con consulta de UPL

**Fase**: Phase 1 del comando `/speckit.plan` | **Fecha**: 2026-08-10
**Feature**: [spec.md](spec.md) | **Base**: constitución v1.0.0 y [research.md](research.md)

Este documento define el modelo de datos de la Feature 2: las entidades del dominio (UPL,
Localidad, Artículo Normativo, Corpus Normativo, Chunk, VectorStore), el Lote reutilizado
de F1, las relaciones entre entidades, la trazabilidad (`SourceTrace`) y la taxonomía de
errores de los contratos. Los nombres de campos y códigos se conservan en inglés donde el
contrato lo exige (Principio I de la constitución); toda la prosa está en español.

## Convenciones

- **Frontera de parsing** (Principio II): el JSON crudo de cada fuente se parsea **una sola
  vez** en el provider correspondiente mediante modelos pydantic v2. Providers de F2:
  ArcGIS UPL (`unidadplaneamientolocal`), Ollama (embeddings y chat) e ingesta del corpus.
  A partir de ese punto, el núcleo trabaja con objetos tipados.
- **Dato derivado vs fuente de verdad**: los **embeddings son dato derivado** (regenerables);
  el **corpus parseado** (JSONL de los 608 artículos del Decreto 555/2021) es la **fuente de
  verdad** versionada en git (`data/corpus/decreto_555_2021.jsonl`, con su huella SHA-256 en
  `data/corpus/decreto_555_2021.jsonl.sha256`, FR-009). El índice vectorial se reconstruye si
  cambia el modelo de embeddings o el corpus (huella del documento fuente).
- **Estado por dato**: toda entidad de fuente en vivo (UPL) lleva `estado` con los valores
  `"disponible"` | `"no_encontrado"` (FR-007). Un dato ausente o no aplicable es
  `"no_encontrado"`, nunca cero ni vacío silencioso.
- **Trazabilidad**: cada dato presentado al LLM lleva un `SourceTrace` de **5 campos**
  obligatorios (FR-006, Principio III). Ver sección [SourceTrace](#sourcetrace).
- **Vigencias**: los datos de vigencias distintas nunca se presentan como una sola
  fotografía temporal (FR-014); cada documento conserva su vigencia explícita.
- **Persistencia local**: el vector store (ChromaDB) persiste en un directorio **gitignored**
  (`.data/chroma/`, FR-009) y es un **dato derivado**; los scripts de ingesta y el corpus
  parseado (JSONL en `data/corpus/`) sí se versionan.

---

## Entidades

### Lote (reutilizado de F1)

Entidad central de F1, **reutilizada sin cambios** en F2 como insumo de `get_upl`
(FR-005): toda consulta de UPL resuelve primero el Lote (por CHIP, dirección o coordenadas)
y sobre su centroide se hace el join espacial contra la capa UPL (research D2).

| Campo | Tipo | Requerido | Descripción / Validación |
|-------|------|-----------|--------------------------|
| `chip` | `string` | sí | CHIP del predio (11 caracteres alfanuméricos, `^[A-Z0-9]{11}$`). |
| `codigo_catastral` | `string` | sí | Código catastral del lote (`LOTCODIGO` de la capa Lote). |
| `manzana` | `string` | sí | Código de la manzana (`MANZCODIGO`). |
| `direccion_normalizada` | `string` | no | Dirección normalizada cuando la fuente la provee. |
| `barrio` | `string` | no | Barrio cuando la fuente lo provee. |
| `geometry` | `object` (GeoJSON) | sí | Geometría poligonal oficial (SRID 4326). |
| `centroid` | `object` | sí | `{ "lat": number, "lng": number }` en WGS84 (4326). |

Referencia: definición completa en
`specs/001-resolver-lote-contexto/data-model.md` (F1). F2 no modifica su esquema.

### UPL (Unidad de Planeamiento Local)

Unidad territorial de planeamiento del POT de Bogotá definida por el Decreto 555/2021
(Key Entity). Se obtiene por join espacial punto-en-polígono del centroide del Lote contra
la capa `ordenamientoterritorial/unidadplaneamientolocal` (layer 0; research D2). Los
atributos `acto_administrativo`, `normativa` y `vocacion` provienen de los campos de la capa;
la `localidad` se deriva por mapeo `NOMBRE → localidad` (research D3).

| Campo | Tipo | Requerido | Descripción / Validación |
|-------|------|-----------|--------------------------|
| `estado` | `string` | sí | `"disponible"` \| `"no_encontrado"`. En `get_upl`, `no_encontrado` se reporta como `LOTE_SIN_UPL` (FR-007). |
| `codigo_upl` | `string` | si `estado=disponible` | Código oficial de la UPL (`CODIGO_UPL`), p. ej. `UPL01`; patrón `^UPL\d{2}$`, valores `UPL01`–`UPL33`. |
| `nombre` | `string` | si `estado=disponible` | Nombre oficial de la UPL (`NOMBRE`), p. ej. `Sumapáz`. |
| `acto_administrativo` | `string` | no | Nombre del acto administrativo que adopta/reglamenta la UPL (`ACTO_ADMINISTRATIVO`). |
| `numero_acto_administrativo` | `string` | no | Número del acto administrativo (`NUMERO_ACTO_ADMINISTRATIVO`). |
| `fecha_acto_administrativo` | `string` | no | Fecha del acto administrativo (`FECHA_ACTO_ADMINISTRATIVO`). |
| `normativa` | `string` | no | Referencia normativa asociada (`NORMATIVA`). |
| `vocacion` | `string` | no | Vocación de la UPL (`VOCACION`). |
| `observacion` | `string` | no | Observación de la fuente (`OBSERVACION`). |
| `area_ha` | `number` | no | Área de la UPL en hectáreas (`AREA_HA`). |
| `localidad_derivada` | `string` | si `estado=disponible` | **Derivada** por mapeo `NOMBRE → localidad` (research D3). Nunca se lee de la capa UPL (no la trae). |
| `source_trace` | `SourceTrace` | sí | Origen: `IDECA Catastro — Unidad de Planeamiento Local`, `layer_id=unidadplaneamientolocal.0`. |

### Localidad

División administrativa de Bogotá (Key Entity). Contiene una o más UPL; cada UPL se ubica
dentro de una única localidad (relación normativa del POT).

| Campo | Tipo | Requerido | Descripción / Validación |
|-------|------|-----------|--------------------------|
| `codigo` | `string` | sí | Código de la localidad (p. ej. `20` para Sumapaz). |
| `nombre` | `string` | sí | Nombre de la localidad (p. ej. `Sumapaz`). |

### Artículo Normativo

Unidad de recuperación del RAG normativo (Key Entity): un artículo del Decreto 555/2021
con su texto literal y sus metadatos de ubicación en el documento.

| Campo | Tipo | Requerido | Descripción / Validación |
|-------|------|-----------|--------------------------|
| `numero` | `int` | sí | Número del artículo (1–608). Identifica la cita (FR-003). |
| `titulo` | `string` | no | Título del artículo (de la ancla del HTML oficial). |
| `texto` | `string` | sí | **Texto literal** del artículo tal como aparece en la fuente oficial (FR-003). |
| `libro` | `string` | sí | Libro del decreto (I Adopción … VIII Disposiciones Generales). |
| `parte` | `string` | sí | Clasificación de suelo / parte del POT: `"general" \| "urbano" \| "rural"`. Base del filtro estricto de UPL (FR-002). |
| `seccion` | `string` | no | Sección del decreto a la que pertenece el artículo. |
| `articulos_derogados` | `array<int>` | no | Artículos del POT anterior que el artículo deroga (p. ej. el Art. 608 deroga las UPZ). |
| `upls_mencionadas` | `array<string>` | no | UPLs mencionadas explícitamente en el artículo (mención explícita para el filtro FR-002). |

### Corpus Normativo

Colección de artículos del Decreto 555/2021 descargada de la fuente oficial, extraída,
dividida en chunks e indexada (Key Entity). Cada documento conserva su propia vigencia
(FR-014).

| Campo | Tipo | Requerido | Descripción / Validación |
|-------|------|-----------|--------------------------|
| `documento` | `string` | sí | `Decreto 555 de 2021 (POT Bogotá)` — POT "Bogotá Reverdece 2022-2035". |
| `documento_id` | `string` | sí | Identificador canónico del documento (equivale a `layer_id` en la trazabilidad): `Decreto_555_2021`. |
| `vigencia` | `string` | sí | Vigencia del documento: `2021-12-30` (Registro Distrital 7326). |
| `hash_documento` | `string` | sí | Huella del documento fuente (p. ej. SHA-256 del HTML parseado). Permite verificar integridad/actualidad del corpus (FR-009). |
| `url_fuente` | `string` | sí | URL oficial de la fuente (sisjur): `https://sisjur.bogotajuridica.gov.co/sisjur/normas/Norma1.jsp?i=119582`. |
| `total_articulos` | `int` | no | Número de artículos indexados (derivable; 608 esperados, SC-006). |

Reglas de dominio:

- El corpus es la **fuente de verdad**; el índice vectorial es un **dato derivado**
  (FR-009). Si `hash_documento` cambia o el modelo de embeddings cambia, se re-indexa.
- Nunca se mezclan vigencias de documentos distintos como una sola fotografía temporal
  (FR-014).

### Chunk

Pieza indexada en el vector store, derivada de un `Artículo Normativo` por chunking
boundary-aware (research D6: 1 chunk = 1 artículo; los muy largos se parten por parágrafos
con overlap, ventanas 512–1024 tokens).

| Campo | Tipo | Requerido | Descripción / Validación |
|-------|------|-----------|--------------------------|
| `id` | `string` | sí | Identificador único del chunk (p. ej. `decreto555-2021-art-042-1`). |
| `articulo` | `int` | sí | Número del artículo del que deriva (1–608). |
| `titulo` | `string` | no | Título del artículo (heredado del Artículo). |
| `libro` | `string` | sí | Libro del decreto (heredado). |
| `parte` | `string` | sí | `"general" \| "urbano" \| "rural"` (heredado; filtro de UPL, FR-002). |
| `seccion` | `string` | no | Sección del decreto (heredada). |
| `texto` | `string` | sí | Texto del fragmento (texto literal del artículo o de su parágrafo). Es el texto que se cita (FR-003). |
| `embedding` | `array<float>` | **derivado** | Vector del chunk (1024 dims con `bge-m3`). No es fuente de verdad: se regenera en la ingesta. |

### VectorStore

Índice vectorial local embebido (ChromaDB persistente) que indexa los `Chunk`
(research D5).

| Campo | Tipo | Requerido | Descripción / Validación |
|-------|------|-----------|--------------------------|
| `tipo` | `string` | sí | `chromadb` (core Rust desde 1.0, persistencia a directorio). |
| `directorio` | `string` | sí | Directorio de persistencia local, **gitignored** (FR-009). |
| `coleccion` | `string` | sí | Colección que indexa los chunks (p. ej. `decreto555_2021`) con metadatos por chunk `{articulo, titulo, libro, parte, seccion}` y filtros por metadatos (FR-002). |
| `embedding_function` | `string` | sí | `OllamaEmbeddingFunction` (modelo `bge-m3`). Usa el endpoint legado `/api/embeddings` (research D5). |
| `estado` | `string` | sí | `"ingestado"` \| `"vacio"` \| `"desactualizado"`. `"vacio"`/`"desactualizado"` se reportan como `CORPUS_NO_INGESTADO` (FR-009/FR-013). |

---

## Relaciones

- **Lote → UPL**: pertenencia espacial (punto-en-polígono). El centroide del Lote se
  consulta contra la capa UPL con `esriSpatialRelIntersects`; si ningún feature intersecta,
  la UPL es `"no_encontrado"` (`LOTE_SIN_UPL`).
- **UPL → Localidad**: cada UPL pertenece a una única localidad; la localidad se deriva por
  mapeo `NOMBRE → localidad` (research D3), no por la capa (no la trae).
- **Artículo Normativo ∈ Corpus Normativo**: el corpus contiene 1..n artículos; cada
  artículo pertenece a un único corpus.
- **Chunk ← Artículo Normativo**: un artículo se divide en 1..n chunks (boundary-aware,
  research D6); cada chunk referencia su artículo y hereda sus metadatos.
- **VectorStore indexa Chunk**: la colección ChromaDB guarda los chunks (texto + metadatos)
  con sus embeddings derivados; el corpus parseado es la fuente de verdad.

---

## SourceTrace

Trazabilidad canónica de un dato (Principio III NON-NEGOTIABLE, FR-006). **Los 5 campos son
obligatorios en toda salida para el LLM**, incluida la marca de tiempo de la consulta.

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `source_name` | `string` | sí | Nombre canónico de la fuente: `IDECA Catastro — Unidad de Planeamiento Local` (UPL) y `Decreto 555 de 2021 (POT Bogotá)` (RAG normativo). |
| `layer_id` | `string` | sí | Identificador de la capa/tema dentro del servicio, o **identificador de documento** (FR-006): `unidadplaneamientolocal.0` para la capa UPL; `Decreto_555_2021` para el corpus. |
| `service_url` | `string` | sí | URL del servicio consultado (capa UPL o URL oficial de sisjur del decreto). |
| `data_vigencia` | `string` | sí | Vigencia del dato en la fuente (fecha ISO o año, según la declare la fuente). |
| `query_timestamp` | `string` | sí | Marca de tiempo de la consulta, ISO 8601 UTC (p. ej. `2026-08-10T14:30:00Z`). |

Reglas de trazabilidad:

- `get_upl` adjunta la trazabilidad de la capa UPL (con el mismo patrón de config de
  `data_vigencia` por capa de F1, configurable por entorno).
- `consultar_normativa` adjunta la trazabilidad del documento consultado: cada respuesta
  identifica el decreto, su vigencia (`2021-12-30`) y su URL oficial.
- No se mezclan vigencias: si el corpus incluyera más documentos en el futuro, cada uno
  conserva su `data_vigencia` (FR-014).

---

## Estados de dato por fuente

| `estado` | Significado | Cómo se reporta |
|----------|-------------|-----------------|
| `disponible` | La fuente devolvió dato(s) (UPL encontrada / corpus ingestado). | Se incluye el dato con su `source_trace`. |
| `no_encontrado` | La fuente no tiene dato para el lote (lote sin UPL) o el corpus no responde (abstención). | En `get_upl`: `LOTE_SIN_UPL` (FR-007). En `consultar_normativa`: `sin_resultados=true` (FR-004), que **no es un error**. |

Un fallo 5xx de la fuente **no** es un estado de dato: es un error fatal de la tool
(`FUENTE_5XX`) que identifica la fuente (FR-009). Un servicio de modelos no disponible
tampoco: es `OLLAMA_NO_DISPONIBLE` (FR-011).

---

## Taxonomía de errores del contrato

Códigos canónicos usados por las tools de F2 (Principio IV, contratos explícitos). Los
códigos heredados de F1 conservan su semántica; los nuevos (`LOTE_SIN_UPL`,
`CORPUS_NO_INGESTADO`, `OLLAMA_NO_DISPONIBLE`) se marcan como (nuevo).

| Código | Condición | Fatal | Mensaje (español) |
|--------|-----------|-------|-------------------|
| `LOTE_NO_ENCONTRADO` | El CHIP, la dirección o el punto no resuelven a ningún lote. | sí | `No se encontró ningún lote para el criterio consultado.` |
| `DIRECCION_NO_LOCALIZADA` | La dirección no pudo geocodificarse (no encontrada o ambigua). | sí | `La dirección no pudo localizarse. Refina la dirección o usa CHIP/coordenadas.` |
| `FUERA_DE_COBERTURA` | El punto está fuera del área de Bogotá. | sí | `El punto está fuera del área de cobertura (Bogotá).` |
| `LOTE_SIN_UPL` (nuevo) | El lote se resolvió pero **no tiene UPL asignada** (dato no encontrado, FR-007). | no | `El lote <codigo_catastral> no tiene UPL asignada (dato no encontrado).` |
| `CORPUS_NO_INGESTADO` (nuevo) | El vector store está vacío o desactualizado (no se ejecutó la ingesta o el índice no corresponde al corpus). | sí | `El corpus normativo no está ingestado o está desactualizado. Ejecuta el script de ingesta antes de consultar.` |
| `OLLAMA_NO_DISPONIBLE` (nuevo) | El servicio Ollama no es accesible o un modelo requerido (embeddings/chat) no está instalado. | sí | `El servicio Ollama no está disponible o falta el modelo <modelo>. Verifica OLLAMA_HOST/OLLAMA_BASE_URL y ollama pull <modelo>.` |
| `FUENTE_5XX` | Error del lado del servidor de la fuente (5xx), indicando cuál fuente. | sí | `La fuente <source_name> no está disponible (error <status>). Intenta nuevamente.` |
| `CREDENCIAL_FALTANTE` | Falta `MAPAS_BOGOTA_APIKEY` en geocodificación (fail-fast). | sí | `Falta la variable MAPAS_BOGOTA_APIKEY para consultas por dirección. Configúrala en .env.` |
| `PARAMETROS_INVALIDOS` | Parámetros de entrada inválidos (FR-013). | sí | `Parámetros inválidos: <detalle>.` |

Forma del error en la respuesta de la tool:

```json
{
  "error": {
    "code": "OLLAMA_NO_DISPONIBLE",
    "message": "El servicio Ollama no está disponible o falta el modelo bge-m3. Verifica OLLAMA_HOST/OLLAMA_BASE_URL y ollama pull bge-m3.",
    "source_name": "ollama"
  }
}
```

Notas:

- `LOTE_SIN_UPL` **no** es un 5xx ni un lote no encontrado: es un resultado válido de
  "dato no encontrado" que el contrato distingue de forma explícita (FR-007).
- `CORPUS_NO_INGESTADO` **no** es "sin resultados": es un estado de infraestructura que se
  reporta como error para evitar resultados vacíos silenciosos (caso límite del spec).
- `sin_resultados=true` en `consultar_normativa` **no es un error** (FR-004).

---

## Reglas de validación de entrada (FR-013)

Aplicadas en el límite de cada tool (fail-fast; si fallan, se responde
`PARAMETROS_INVALIDOS` sin llamar a las fuentes):

1. **CHIP mal formado**: el CHIP debe ser una cadena de exactamente 11 caracteres
   alfanuméricos en mayúsculas (patrón `^[A-Z0-9]{11}$`).
2. **Coordenadas fuera de rango**: `latitude` ∈ [-90, 90] y `longitude` ∈ [-180, 180].
   El punto válido en rango pero fuera de Bogotá produce `FUERA_DE_COBERTURA` (no es un
   parámetro inválido).
3. **Dirección vacía**: una dirección en blanco o solo espacios se rechaza.
4. **Consulta normativa vacía o demasiado larga**: `consulta` debe ser `string` no vacía
   (después de trim) y de 1 a 500 caracteres.
5. **UPL mal formada o inexistente**: `upl` debe cumplir `^UPL\d{2}$` y existir en el
   conjunto `UPL01`–`UPL33` (p. ej. `UPL99` se rechaza aunque el formato sea válido).
6. **`top_k` fuera de rango**: debe ser `int` entre 1 y 6 (default 3).
7. **Entrada de `get_upl`**: exactamente uno de `{chip, direccion, coordenadas}` debe estar
   presente; cero o más de uno se rechaza.

---

## Relación con el spec

| Artefacto | Requisitos del spec |
|-----------|---------------------|
| `Lote` (reutilizado F1) | FR-005, Key Entity Lote |
| `UPL`, `Localidad` | FR-005, FR-007, Key Entities UPL/Localidad |
| `Artículo Normativo`, `Corpus Normativo`, `Chunk` | FR-001, FR-003, FR-008, FR-009, FR-014, Key Entities |
| `VectorStore` | FR-008, FR-009, FR-010 |
| `SourceTrace` | FR-006, FR-014, SC-005, Principio III |
| Estados `disponible` / `no_encontrado` | FR-004, FR-007, SC-003 |
| Taxonomía de errores | FR-007, FR-009, FR-011, FR-013, Principio IV |
| Reglas de validación de entrada | FR-013, SC-006 |
| Filtro por `parte`/`upls_mencionadas` | FR-002 (filtro estricto por UPL) |
