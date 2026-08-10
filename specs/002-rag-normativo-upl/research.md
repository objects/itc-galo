# Research: RAG normativo del POT (Decreto 555/2021) con consulta de UPL

**Fase**: Phase 0 del comando `/speckit.plan` | **Fecha**: 2026-08-10
**Feature**: [spec.md](spec.md) | **Estado**: Resuelto — todas las decisiones zanjadas, sin marcadores de aclaración pendiente

## Alcance

Esta investigación resuelve las decisiones técnicas de la Feature 2 (UPL + RAG normativo del
Decreto 555 de 2021) antes de diseñar el modelo de datos y los contratos, con base en la
spec aprobada (`spec.md`: 3 historias de usuario, 14 FR, 6 SC y 8 casos límite) y en la
constitución v1.0.0 (`.specify/memory/constitution.md`). Las decisiones quedan zanjadas por
la constitución (Principio V: entrega incremental; F2 = UPL + RAG normativo) y por las
clarificaciones del 2026-08-10 registradas en la spec (Ollama local, corpus oficial +
ingesta, vector store local embebido, dos tools: `get_upl` y `consultar_normativa`).

Todas las fuentes fueron **verificadas en vivo el 2026-08-10** (acceso directo a los
servicios públicos, a la documentación oficial de Ollama y a las referencias de RAG citadas).
Los hallazgos se organizan en cinco temas (H1–H5) y cada decisión (D1–D7) cita su fuente
(URL), de modo que el plan pueda referenciarlas con trazabilidad.

**Nota de verificación**: el "Decreto 468" (corrección cartográfica del POT) **no pudo
verificarse** durante la investigación en vivo; no se cita en ninguna decisión ni en el
plan. Todos los artefactos citan exclusivamente fuentes verificadas el 2026-08-10.

---

## Hallazgos

### H1. Decreto 555 de 2021 (POT Bogotá): el corpus normativo y su fuente de extracción

El Decreto 555 de 2021 ("Por el cual se adopta la revisión general del Plan de
Ordenamiento Territorial de Bogotá D.C. — POT Bogotá Reverdece 2022-2035") es el documento
de 608 artículos organizados en 8 Libros: I Adopción · II Componente General · III
Componente Urbano · IV Componente Rural · V Actuaciones Estratégicas · VI Instrumentos de
Planeación · VII Contenido Programático · VIII Disposiciones Generales. El **Art. 608
(Derogatorias)** deroga las Unidades de Planeamiento Zonal (UPZ), reemplazadas por las UPL.

Vigencia y estado (verificado el 2026-08-10):

- Vigente desde **30/12/2021** (publicado en el Registro Distrital 7326).
- La suspensión provisional de 2022 fue **revocada** (auto del Tribunal Administrativo de
  Cundinamarca del 22/08/2022).
- Reglamentación posterior numerosa: Dctos. 203/2022, 506/2022, 18/72/122/165/263/2023, entre
  otros; las UPL se reglamentan de forma progresiva (cada UPL con su acto administrativo).

**Hallazgo clave para la ingesta**: existe una **versión HTML estructurada** del articulado
(artículos con anclas `id="N"`) que es **más fácil de extraer que el PDF** (el PDF exige
parseo de layout; el HTML permite regex sobre el marcado de artículo y enlaces con ancla).
Fuentes oficiales del articulado:

- HTML oficial — Régimen Legal (Alcaldía de Bogotá):
  `https://www.alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=119582`
- HTML oficial — sisjur Bogotá Jurídica:
  `https://sisjur.bogotajuridica.gov.co/sisjur/normas/Norma1.jsp?i=119582`
- Micrositio POT de la SDP:
  `https://www.sdp.gov.co/micrositios/pot/decreto-pot-bogota-2021`
- Compilación HTML de la SHD:
  `https://compilacionjuridica.shd.gov.co/compilacion/docs/d_alcabog_0555_2021.htm`
- PDF oficial:
  `https://bogota.gov.co/bog/pot-2022-2035/Decreto_555_de_2021.pdf`

### H2. Capa UPL: join espacial punto-en-polígono (la capa Lote no trae UPL)

La capa **Lote** (`Mapa_Referencia/Mapa_Referencia`, layer 38) que usa F1 **NO trae UPL**:
sus campos visibles son solo `LOTCODIGO`, `LOTDISPERS`, `LOTILDISPE`, `LOTUPREDIA`,
`LOTDISTRIT`, `MANZCODIGO`. Por tanto, resolver la UPL de un lote exige un **join espacial
punto-en-polígono** contra la capa de UPL usando el centroide del lote (o el punto
consultado), con el mismo patrón `_params_punto` de F1 (`esriSpatialRelIntersects`).

La capa UPL oficial de Catastro (verificada en vivo el 2026-08-10):
`https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/ordenamientoterritorial/unidadplaneamientolocal/MapServer/0`

- Layer **0** del servicio `ordenamientoterritorial/unidadplaneamientolocal`.
- **33 features** (`UPL01`–`UPL33`; p. ej. Sumapáz = UPL01, Bosa = UPL17, Barrios Unidos =
  UPL33).
- Atributos: `CODIGO_UPL`, `NOMBRE`, `ACTO_ADMINISTRATIVO`,
  `NUMERO_ACTO_ADMINISTRATIVO`, `FECHA_ACTO_ADMINISTRATIVO`, `NORMATIVA`, `VOCACION`,
  `OBSERVACION`, `AREA_HA`. **NO trae localidad**.
- SR EPSG 4686/4326; consulta por punto con `esriSpatialRelIntersects` (mismo patrón que F1).

Otras fuentes de UPL consideradas (todas verificadas en vivo el 2026-08-10):

- Mapa_Referencia layer 44 (capa UPL dentro del Mapa de Referencia):
  `https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/Mapa_Referencia/Mapa_Referencia/MapServer/44`
- POT en ArcGIS Online (FeatureServer, layer 35):
  `https://services7.arcgis.com/lsxbLWF2l19Rmhqj/arcgis/rest/services/POT_Bogota_Decreto_555_2021/FeatureServer/35`
- IDECA — descarga GeoJSON/KMZ y WMS/WFS:
  `http://www.ideca.gov.co/recursos/mapas/unidad-de-planeamiento-local-bogota-dc`
- Datos Abiertos Bogotá — dataset UPL:
  `https://datosabiertos.bogota.gov.co/dataset/unidad-planeamiento-local-bogota-d-c`
- SDP — micrositio de UPL:
  `https://www.sdp.gov.co/micrositios/pot/upl`

### H3. Ollama (2026): modelos locales de embeddings y chat

La API de Ollama (documentación verificada en vivo el 2026-08-10) tiene dos familias de
endpoints:

- **Embeddings moderno**: `POST /api/embed` con cuerpo `{"model", "input": [str, ...]}` →
  `{"embeddings": [[float, ...]]}` (vectores L2-normalizados). Reemplaza al legado.
- **Embeddings legado**: `POST /api/embeddings` con `{"model", "prompt"}` →
  `{"embedding": [...]}`. Es el que usa `OllamaEmbeddingFunction` de ChromaDB.
- **Chat**: `POST /api/chat` con `{"model", "messages": [{"role", "content"}], "stream":
  false, "format": "json"}` → `{"message": {"content"}}`.
- Variables de entorno: `OLLAMA_HOST` (bind moderno) y `OLLAMA_BASE_URL` (legado; la que usa
  ChromaDB).

Docs: `https://docs.ollama.com/api/embed` · `https://docs.ollama.com/capabilities/embeddings`

Modelos recomendados:

- **Embeddings: `bge-m3`** — 1024 dims, multilingüe (ideal para español jurídico), contexto
  8192, instalable con `ollama pull bge-m3`. Alternativas: `nomic-embed-text` (768 dims, más
  rápido pero optimizado a inglés) y `qwen3-embedding` (SOTA pero pesado).
- **Chat: `qwen3:8b`** — recomendado para generar la respuesta con citas. `qwen3:4b` en
  máquinas pequeñas; `llama3.2:3b` como mínimo; `phi-4` (14B) si hay RAM suficiente.

Integración con ChromaDB: `chromadb.utils.embedding_functions.OllamaEmbeddingFunction` es
estable y documentada. Limitaciones conocidas: usa el **endpoint legado** `/api/embeddings`,
exige Ollama levantado y el modelo descargado, y **no reintenta solo** (el fail-fast de
`OLLAMA_NO_DISPONIBLE` queda en el límite de la tool, Principio IV).

### H4. Vector store y chunking legal

Comparación de vector stores (verificada el 2026-08-10):

- **ChromaDB** — recomendado: core en Rust desde 1.0, persistencia a directorio, API Python
  nativa, filtros por metadatos (necesarios para el filtro estricto de UPL, FR-002).
- sqlite-vec — pre-1.0, búsqueda brute-force sin ANN. Descartado.
- LanceDB — robusto a escala, API joven. Descartado (YAGNI).
- FAISS — solo búsqueda, sin persistencia. Descartado.

**Los vectores son dato derivado**: el corpus parseado (los artículos en texto) es la
**fuente de verdad**; si cambia el modelo de embeddings, se re-indexa (FR-009: índice
regenerable y gitignored).

Chunking legal **boundary-aware por artículo** (sobre el HTML oficial):

- Regex sobre el articulado: `"ARTÍCULO N. <TÍTULO>"` → **1 chunk = 1 artículo**.
- Los artículos muy largos se parten por parágrafos con overlap (ventanas 512–1024 tokens).
- Metadatos por chunk: `{"articulo": N, "titulo": "...", "libro": "...", "parte":
  "general/urbano/rural", "seccion": "..."}`.

### H5. RAG legal con citas y mitigación de alucinación

Recomendaciones para RAG sobre normativa (verificadas el 2026-08-10):

- Recuperar **top-k de 4–6** candidatos, aplicar **umbral de similitud coseno ≥ 0.30–0.35**
  (bge-m3; calibrar con ~50 consultas reales) y quedarse con **top-3** sobre el umbral.
- **Cita literal obligatoria**: se cita el texto literal del chunk (no se parafrasea la
  norma) y el número de artículo.
- Prompt: "responde SOLO con base en estos fragmentos; cita el texto exacto y el número de
  artículo".
- **Post-verificación (citation forcing)**: el artículo citado debe existir en los metadatos
  del chunk recuperado.
- **Temperatura baja** (0–0.2) para reducir la varianza.
- **Abstención explícita**: si ningún resultado supera el umbral, responder "No se
  encontraron resultados relevantes en el POT 555/2021" (nunca inventar).
- Contexto del riesgo: los LLM legales **alucinan citas en el 17–33% de los casos** — la
  cita literal es obligatoria.

Fuentes:

- `https://knowledged.to/notes/ml/top-k-in-rag-search`
- `https://mbrenndoerfer.com/writing/hallucination-mitigation`
- `https://insiderllm.com/guides/best-local-llms-rag/`
- `https://aclanthology.org/2025.ldk-1.16/`

---

## D1. Extraer el articulado desde el HTML de sisjur (no del PDF)

**Decision**: La ingesta del corpus del Decreto 555/2021 extrae el articulado desde la
**versión HTML estructurada** del servicio oficial sisjur (Bogotá Jurídica), parseando las
anclas de artículo del HTML; no se extrae del PDF.

**Rationale**: El HTML oficial está estructurado con anclas por artículo (patrón de marcado
con `id="N"`), lo que permite un chunking boundary-aware por artículo (D6) con una regex
simple y robusta; el PDF exige parseo de layout y tablas, más frágil y sin anclas
semánticas (H1). El HTML de sisjur es la misma fuente oficial que el PDF (mismo número de
Registro Distrital 7326 y vigencia 2021-12-30).

**Alternatives considered**:

- **PDF oficial** (`https://bogota.gov.co/bog/pot-2022-2035/Decreto_555_de_2021.pdf`):
  parseo de layout propenso a errores y sin anclas por artículo. Descartado.
- **Compilación HTML de la SHD**: es una compilación (documento consolidado), no la fuente
  normativa original; útil como contraste pero no como fuente primaria de ingesta.

**Fuente**: `https://sisjur.bogotajuridica.gov.co/sisjur/normas/Norma1.jsp?i=119582` y
`https://www.alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=119582` (H1).

---

## D2. Capa UPL del catastro `unidadplaneamientolocal/0` con join espacial punto-en-polígono

**Decision**: `get_upl` resuelve el lote con el resolver de F1 (CHIP, dirección o
coordenadas) y luego hace un **join espacial punto-en-polígono** del centroide del lote
contra la capa `ordenamientoterritorial/unidadplaneamientolocal` (layer 0) reutilizando el
patrón `_params_punto` de F1 (`geometryType=esriGeometryPoint`, `inSR=4326`,
`spatialRel=esriSpatialRelIntersects`, `outSR=4326`), leyendo `CODIGO_UPL` y `NOMBRE`.

**Rationale**: La capa Lote (layer 38) que usa F1 **no trae UPL** (H2: campos visibles
limitados), por lo que el join espacial contra la capa UPL oficial de Catastro es
obligatorio. La capa `unidadplaneamientolocal/0` es la fuente oficial con 33 features
(`UPL01`–`UPL33`) y el patrón de consulta espacial ya está validado en F1 (misma
semántica ArcGIS REST, mismos errores tipados).

**Alternatives considered**:

- **Mapa_Referencia layer 44** (capa UPL dentro del Mapa de Referencia): fuente alternativa
  válida pero fuera del servicio temático de ordenamiento territorial y sin ventaja frente a
  `unidadplaneamientolocal/0`. Descartada.
- **POT en ArcGIS Online (FeatureServer 35)** y descargas IDECA/Datos Abiertos: útiles para
  auditoría y descarga masiva, pero agregan una dependencia externa de terceros para una
  consulta puntual en vivo. Descartadas (YAGNI).

**Fuente**: `https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/ordenamientoterritorial/unidadplaneamientolocal/MapServer/0` (H2).

---

## D3. Localidad derivada por mapeo NOMBRE → localidad (tabla de 33 entradas)

**Decision**: La **localidad** de una UPL se deriva con un **mapeo `NOMBRE → localidad`** de
**33 entradas** (una por UPL) mantenido como tabla de configuración versionada en el
repositorio (con su propia fuente citada), no mediante un join espacial contra una capa de
localidades en runtime.

**Rationale**: La capa UPL no trae localidad (H2), pero la relación UPL → localidad es una
relación **normativa y estática** del POT (cada UPL pertenece a una única localidad, p. ej.
UPL01 Sumapáz → localidad Sumapaz; UPL33 Barrios Unidos → localidad Barrios Unidos): no
cambia durante la vigencia del decreto y su fuente es el propio POT. La tabla de 33 entradas
es determinista, revisable en código (unit testable), no agrega una consulta de red
adicional por lote (menor latencia y superficie de fallo para SC-004) y permite
trazabilidad directa (el mapeo se cita a la fuente SDP/micrositio). Un join espacial contra
una capa de localidades añade otra fuente en vivo (otra latencia y otro riesgo de 5xx)
para un dato que no cambia en runtime.

**Alternatives considered**:

- **Join espacial contra capa de localidades**: más "oficial" en apariencia, pero introduce
  una dependencia de red adicional, un `data_vigencia` extra y riesgo de inconsistencia
  geográfica (puntos de límite) para un dato estático. Descartado.
- **Derivar la localidad del nombre del lote**: el lote no trae localidad confiable.
  Descartado.

**Fuente**: capa UPL sin atributo de localidad (H2) y micrositio UPL de la SDP
`https://www.sdp.gov.co/micrositios/pot/upl`; la tabla de 33 entradas se construye sobre el
articulado del POT (H1).

---

## D4. Ollama local: `bge-m3` para embeddings + `qwen3:8b` para chat

**Decision**: El proveedor de modelos es **Ollama local** con **`bge-m3`** para embeddings
(1024 dims, multilingüe, contexto 8192) y **`qwen3:8b`** para chat (o `qwen3:4b` en máquinas
pequeñas). Para el chat se usa `POST /api/chat`; para embeddings el pipeline de ChromaDB
usa el endpoint **legacy** `/api/embeddings` (vía `OllamaEmbeddingFunction`); el endpoint
moderno `POST /api/embed` NO se usa en runtime y queda documentado como **alternativa
futura** (ver D5). Configuración por variables de entorno: `OLLAMA_HOST` (bind moderno) y
`OLLAMA_BASE_URL` (legado que usa ChromaDB), más `OLLAMA_EMBEDDING_MODEL` y
`OLLAMA_CHAT_MODEL` (FR-010, sin credenciales en código).

**Rationale**: El español jurídico del POT exige un modelo multilingüe; `bge-m3` cubre 1024
dimensiones y 8192 tokens de contexto, superior a `nomic-embed-text` (optimizado a inglés)
sin el peso de `qwen3-embedding`. `qwen3:8b` es el balance recomendado para generar la
respuesta con citas literales en español (H3).

**Alternatives considered**:

- **`nomic-embed-text`**: más rápido pero optimizado a inglés; degrada la calidad en español
  jurídico. Descartado.
- **`qwen3-embedding`**: SOTA pero pesado para una máquina local. Descartado (SC-001: < 15 s).
- **`phi-4` (14B) para chat**: calidad alta pero mayor requisito de RAM; queda como opción
  configurable vía entorno, no como default.

**Fuente**: `https://docs.ollama.com/api/embed` y
`https://docs.ollama.com/capabilities/embeddings` (H3).

---

## D5. ChromaDB persistente como vector store local con `OllamaEmbeddingFunction`

**Decision**: El índice vectorial se almacena en **ChromaDB** (core Rust desde 1.0) con
persistencia a **directorio local gitignored** y se indexa con
`chromadb.utils.embedding_functions.OllamaEmbeddingFunction` (modelo `bge-m3`). El directorio
de persistencia del índice no se versiona (`gitignored` en `.data/chroma/`, FR-009:
artefacto regenerable); el corpus parseado en JSONL de artículos es la fuente de verdad
**versionada en git** (`data/corpus/`, D6).

**Rationale**: ChromaDB es la única opción evaluada que combina persistencia a directorio,
API Python nativa y **filtros por metadatos** — requeridos por el filtro estricto de UPL de
`consultar_normativa` (FR-002, filtro por `parte`/`upls_mencionadas` de cada chunk). La
integración `OllamaEmbeddingFunction` es estable y documentada (H3/H4). Limitaciones
asumidas: usa el endpoint legado `/api/embeddings`, exige Ollama levantado y modelo
descargado, y no reintenta solo — el fail-fast de `OLLAMA_NO_DISPONIBLE` se implementa en el
límite de la tool (Principio IV).

**Alternatives considered**:

- **sqlite-vec**: pre-1.0, búsqueda brute-force sin ANN y sin filtros maduros por metadatos.
  Descartado.
- **LanceDB**: robusto a escala pero API joven; más superficie para el volumen de 608
  artículos. Descartado (YAGNI).
- **FAISS**: solo búsqueda, sin persistencia ni filtros. Descartado.

**Fuente**: H4 (comparativa de vector stores) y H3 (`OllamaEmbeddingFunction`).

---

## D6. Chunking boundary-aware por artículo con metadatos; corpus parseado como fuente de verdad

**Decision**: La ingesta (FR-008) aplica **chunking boundary-aware por artículo**: regex
sobre el HTML oficial `"ARTÍCULO N. <TÍTULO>"`, **1 chunk = 1 artículo**; los artículos muy
largos se parten por parágrafos con overlap (ventanas 512–1024 tokens). Cada chunk lleva
metadatos `{"articulo": N, "titulo": "...", "libro": "...", "parte":
"general|urbano|rural", "seccion": "..."}`. El corpus parseado (JSONL de los 608 artículos)
es la **fuente de verdad** versionada en git (`data/corpus/decreto_555_2021.jsonl`, con su
huella SHA-256 en `data/corpus/decreto_555_2021.jsonl.sha256`); el índice vectorial
(ChromaDB) es **dato derivado gitignored** (`.data/chroma/`) que se re-indexa si cambia el
modelo o el corpus (FR-009: hash del documento fuente y aviso de índice desactualizado).

**Rationale**: Un chunk por artículo preserva la unidad semántica legal (la cita siempre es
verificable por número de artículo, FR-003/SC-002) y el overhead de partición solo aplica a
los artículos largos (parágrafos). Los metadatos permiten el filtro estricto por UPL
(FR-002, por `parte` = clasificación de suelo y mención explícita) y la post-verificación de
citas (D7). Mantener el corpus parseado como fuente de verdad y los vectores como derivado
cumple FR-009 (índice regenerable, gitignored).

**Alternatives considered**:

- **Chunking por párrafos/tokens sin frontera de artículo**: rompe la unidad legal y
  degrada la cita verificable. Descartado.
- **Persistir solo los embeddings**: violaría FR-009 (el índice no sería regenerable sin el
  corpus). Descartado.

**Fuente**: H1 (HTML estructurado con anclas por artículo) y H4 (chunking legal).

---

## D7. RAG con citas: top-k 4–6 → top-3, umbral 0.30–0.35, cita literal + citation forcing, temperatura 0.1, abstención explícita

**Decision**: El pipeline de `consultar_normativa`:

1. Recuperar **top-k de 4–6** candidatos por similitud coseno (bge-m3).
2. Aplicar **umbral ≥ 0.30–0.35** (calibrado con ~50 consultas reales durante la ingesta) y
   quedarse con **top-3** piezas sobre el umbral.
3. Generar la respuesta con el prompt "responde SOLO con base en estos fragmentos; cita el
   texto exacto y el número de artículo" y **temperatura 0.1**.
4. **Post-verificación (citation forcing)**: cada artículo citado debe existir en los
   metadatos de los chunks recuperados; si no, se descarta la cita.
5. Si **ninguna** pieza supera el umbral → abstención explícita: "No se encontraron
   resultados relevantes en el POT 555/2021" (`sin_resultados=true`, FR-004) — **nunca**
   inventar contenido.

**Rationale**: Los LLM legales alucinan citas en el 17–33% de los casos (H5), por lo que la
cita literal del chunk + número de artículo es obligatoria (FR-003/SC-002), el `citation
forcing` bloquea citas no respaldadas y la abstención explícita cubre el caso límite de
consulta sin resultados (FR-004/SC-003). El umbral bajo se calibra con consultas reales para
evitar falsos negativos en jerga jurídica; el paso top-k → top-3 acota la respuesta amplia
(caso límite "todo el decreto") sin truncar el texto literal de cada artículo recuperado.

**Alternatives considered**:

- **Devolver todos los candidatos sin umbral**: mezclaría piezas irrelevantes y rompería la
  garantía de cita verificable. Descartado.
- **Dejar que el LLM parafrasee**: viola FR-003 y aumenta el riesgo de alucinación.
  Descartado.
- **Sin citation forcing**: la verificación post-hoc de las citas es la defensa directa
  contra la alucinación de citas. Descartado.

**Fuente**: H5 — `https://knowledged.to/notes/ml/top-k-in-rag-search`,
`https://mbrenndoerfer.com/writing/hallucination-mitigation`,
`https://insiderllm.com/guides/best-local-llms-rag/`,
`https://aclanthology.org/2025.ldk-1.16/`.

---

## Resumen de decisiones y artefactos derivados

| # | Decisión | Artefacto que la materializa |
|---|----------|------------------------------|
| D1 | Extracción del articulado desde el HTML de sisjur (no del PDF) | `plan.md` (ingesta), `data-model.md` (Corpus Normativo) |
| D2 | Capa UPL `unidadplaneamientolocal/0` con join espacial punto-en-polígono | `contracts/get-upl.md`, `data-model.md` (UPL) |
| D3 | Localidad derivada por mapeo NOMBRE→localidad (tabla de 33 entradas) | `data-model.md` (UPL.localidad_derivada), `contracts/get-upl.md` |
| D4 | Ollama local: `bge-m3` (embeddings) + `qwen3:8b` (chat); `/api/chat` y endpoint legado `/api/embeddings` (ChromaDB); `/api/embed` como alternativa futura; `OLLAMA_HOST`/`OLLAMA_BASE_URL`, `OLLAMA_EMBEDDING_MODEL`, `OLLAMA_CHAT_MODEL` | `plan.md` (provider Ollama), `contracts/consultar-normativa.md` |
| D5 | ChromaDB persistente con `OllamaEmbeddingFunction` | `data-model.md` (VectorStore), `plan.md` |
| D6 | Chunking boundary-aware por artículo con metadatos; corpus parseado como fuente de verdad | `data-model.md` (Artículo/Chunk/Corpus), `plan.md` (ingesta) |
| D7 | RAG: top-k 4–6 → top-3, umbral 0.30–0.35, cita literal + citation forcing, temperatura 0.1, abstención explícita | `contracts/consultar-normativa.md` |
