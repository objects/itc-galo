# mcp-bogota-factibilidad

Servidor MCP (Model Context Protocol) en Python que permite consultar un **lote
catastral de Bogotá** por CHIP, por dirección o por coordenadas, enriquecerlo con
**contexto temático** (valor de referencia catastral, reservas
viales y obras públicas), resolver su **UPL (Unidad de Planeamiento Local)** y
consultar la **normativa del POT** (Decreto 555 de 2021) con RAG 100 % local
(ChromaDB + Ollama), todo con trazabilidad por fuente.

- **Feature 1** (MVP): resolución de lote + contexto temático (4 tools).
- **Feature 2**: RAG normativo del POT + consulta de UPL (2 tools nuevas).
- **Feature 3**: informe de factibilidad orquestado (1 tool nueva: `get_feasibility_report`).
- **Feature 4**: ingesta de actos modificatorios del Decreto 555 (corpus consolidado; sin tools MCP nuevas).

## Requisitos

- Python 3.11 o superior.
- Acceso de red a las fuentes públicas:
  - `https://catalogopmb.catastrobogota.gov.co/PMBWeb/web` (API de búsqueda de Mapas Bogotá: `buscar` para CHIP, `api` para geocodificar)
  - `https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/` (ArcGIS REST del catastro)
- **Ollama local** (solo Feature 2: `get_upl` y `consultar_normativa`) con los
  modelos de embeddings y de chat descargados:
  ```bash
  ollama pull bge-m3
  ollama pull qwen3:8b
  # Alternativas de chat: ollama pull gemma4:e4b (8-16 GB RAM) o gemma4:26b (16 GB+ VRAM, 256K ctx)
  ollama pull gemma4:e4b
  ```
  El RAG normativo es 100 % local: sin llamadas a APIs de pago ni nube.

  > **Cambiar de modelo de embeddings**: la ingesta persiste el modelo usado en
  > la metadata de la colección ChromaDB (`embedding_model`). Si cambias
  > `OLLAMA_EMBEDDING_MODEL`, al re-indexar se detecta el cambio y el índice se
  > reconstruye automáticamente (no se mezclan vectores de modelos distintos).
  > Con otros clientes externos, borra `.data/` manualmente antes de re-indexar.

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuración

Copia `.env.example` a `.env` y ajusta los valores:

```bash
cp .env.example .env
```

| Variable | Obligatoria | Descripción |
|----------|-------------|-------------|
| `MAPAS_BOGOTA_APIKEY` | Solo consulta por dirección | API key de Mapas Bogotá para `geocodificar`. Sin ella, `resolve_lot_by_address` y `get_upl` por dirección fallan rápido con `CREDENCIAL_FALTANTE`; las consultas por CHIP y por coordenadas siguen funcionando. |
| `OLLAMA_BASE_URL` | Solo F2 | Endpoint de Ollama (default `http://localhost:11434`; ChromaDB usa el legado `/api/embeddings`). |
| `OLLAMA_EMBEDDING_MODEL` | Solo F2 | Modelo de embeddings (default `bge-m3`, 1024 dims). Al cambiar el modelo, la ingesta reconstruye el índice automáticamente (el modelo se persiste en la metadata de la colección; con clientes externos, borra `.data/` manualmente). |
| `OLLAMA_CHAT_MODEL` | Solo F2 | Modelo de chat para la generación de respuesta (default `qwen3:8b`; alternativas `gemma4:e4b` 8-16 GB RAM o `gemma4:26b` 16 GB+ VRAM, 256K ctx). |
| `CORPUS_URL` | Ingesta | URL oficial del articulado en sisjur (default `Norma1.jsp?i=119582`). |
| `VECTOR_DB_PATH` | Solo F2 | Directorio del índice ChromaDB (default `.data/chroma`, gitignored, regenerable). |
| `EMBEDDING_DIM` | Solo F2 | Dimensión del embedding (default `1024`, debe coincidir con el modelo). |

Las variables de entorno se leen directamente del entorno; el proyecto no carga `.env`
automáticamente.

## Ingesta del corpus normativo (Feature 2)

Antes de usar `consultar_normativa` hay que ingerir el corpus del Decreto 555/2021:

```bash
# Pipeline completo: descarga sisjur → parsea 608 artículos → versiona JSONL + .sha256 → indexa en ChromaDB
python -m app.ingesta.corpus full

# Solo descargar y versionar (no requiere Ollama; genera data/corpus/decreto_555_2021.jsonl + .sha256)
python -m app.ingesta.corpus descargar

# Solo indexar el corpus ya versionado (requiere Ollama con bge-m3)
python -m app.ingesta.corpus indexar

# Consulta directa al índice (debugging)
python -m app.ingesta.corpus consultar "usos del suelo" --top-k 5 --umbral 0.35 --upl UPL17
```

El JSONL versionado (`data/corpus/`) es la fuente de verdad versionada en git
(FR-009); el índice vectorial (`.data/chroma/`) es un dato derivado regenerable.

## Ingesta de actos modificatorios del Decreto 555 (Feature 4)

El POT es una norma viva: decretos y resoluciones posteriores lo reglamentan o
modifican. F4 alimenta el RAG normativo con esos **actos modificatorios** e
integra un **corpus consolidado** que `consultar_normativa` (F2) y
`get_feasibility_report` (F3) consultan como un solo contexto. F4 **no añade
tools MCP**: siguen las **7 tools** de F1–F3; la alimentación del corpus es por CLI.

- El **Decreto 555 de 2021 permanece como norma base INALTERADA**: sus 608
  artículos (`data/corpus/decreto_555_2021.jsonl` + `.sha256`) no se modifican
  (FR-012).
- Los actos se integran como **documentos nuevos versionados en git** en
  `data/corpus/actos_modificatorios/`: un JSONL + `.sha256` por acto y un
  registro `.corpus_consolidado.json` con el hash SHA-256 y los metadatos por
  documento (fuente de verdad versionada; el índice `.data/chroma/` sigue siendo
  un dato derivado regenerable, FR-013).

### Subcomando CLI `acto`

```bash
# Ingestar un acto desde su URL sisjur (formato recomendado) y re-indexar
python -m app.ingesta.corpus acto --url <URL> --indexar

# Ingestar desde un archivo local (HTML sisjur, PDF, DOCX, Markdown o TXT)
python -m app.ingesta.corpus acto --archivo <ruta> [--output <dir>] [--indexar]
```

- **5 formatos soportados** (FR-001): HTML sisjur (recomendado: reutiliza el
  parser de anclas `class="ancla"` de F2), PDF, DOCX, Markdown y TXT.
- **Deduplicación por hash SHA-256** (FR-007): re-ingestar el mismo archivo es un
  no-op con `"duplicado": true` en la salida JSON, sin reescribir el JSONL ni
  re-indexar.
- **Validación temporal y referencial** (FR-014): un acto con `fecha_expedicion`
  anterior a 2021-12-30 se rechaza con `FECHA_ANTERIOR_AL_555`; un acto sin
  referencias verificables a artículos del 555 se integra dejando constancia en
  `relacion_con_555: "sin_referencia"` (no se rechaza: la relación no siempre es
  verificable por máquina).
- **Fallo atómico por documento** (FR-009): cualquier error deja el corpus
  existente intacto (sin escrituras parciales).
- **Salida JSON** con metadatos completos (tipo, número, año, fechas, url,
  hash SHA-256, artículos, relación con el 555, estado del documento y
  `indexado`).
- La **ingesta NO requiere Ollama** (FR-010); solo `--indexar` (embeddings) lo
  requiere.

### RAG consolidado y precedencia temporal

- `consultar_normativa` (F2) y `get_feasibility_report` (F3) consultan la misma
  colección ChromaDB consolidada (555 + actos); cada fragmento indica su norma de
  origen (`norma`/`source_name` por ítem, campos aditivos que no rompen los
  contratos de F2/F3, FR-011).
- La **regla de precedencia temporal va en el prompt del LLM** (FR-006): el acto
  posterior prevalece SIN ocultar los artículos del 555 (coexistencia de
  fuentes), y la respuesta indica la norma de origen de cada cita.
- **Re-indexación aditiva**: `--indexar` upserta solo los chunks del acto nuevo;
  si cambia un documento o el modelo de embeddings (bge-m3), el índice se
  reconstruye automáticamente desde cero (555 + todos los actos del registro)
  para no mezclar vectores (FR-008).

### Notas y errores tipificados del CLI

- **Sin OCR**: los PDF escaneados sin texto extraíble se rechazan con
  `SIN_TEXTO_EXTRAIBLE` sugiriendo el formato HTML sisjur (fuera de alcance).
- Errores tipificados del CLI (stderr + exit code ≠ 0):
  `FORMATO_NO_SOPORTADO`, `SIN_TEXTO_EXTRAIBLE`, `SIN_ARTICULOS_PARSEABLES`,
  `FECHA_ANTERIOR_AL_555`, `FUENTE_NO_DISPONIBLE` y `METADATOS_INCOMPLETOS`. La
  taxonomía de los **10 códigos de errores MCP** de `app/errores.py` no cambia
  (FR-011).

## Ejecución del servidor MCP

El servidor se comunica por **stdio** (transporte por defecto de FastMCP):

```bash
python -m app.main
```

O bien, con la entrada de consola instalada:

```bash
mcp-bogota-factibilidad
```

### Tools expuestas (7)

| Tool | Descripción |
|------|-------------|
| `resolve_lot_by_chip` | Resuelve un lote por CHIP y devuelve identidad, geometría/centroide y contexto temático. |
| `resolve_lot_by_address` | Geocodifica una dirección y resuelve el lote asociado (requiere `MAPAS_BOGOTA_APIKEY`). |
| `resolve_lot_by_coordinates` | Resuelve el lote que contiene un punto (`latitud`, `longitud` en WGS84). |
| `get_lot_summary_by_chip` | Resumen consolidado descriptivo del lote por CHIP (identidad + contexto por fuente). |
| `get_upl` | Resuelve la UPL del lote por CHIP, dirección o coordenadas (join espacial punto-en-polígono contra la capa UPL; localidad derivada por mapeo nombre → localidad). |
| `consultar_normativa` | Consulta en lenguaje natural sobre el POT con citas literales de artículos (RAG local); filtro estricto opcional por UPL. |
| `get_feasibility_report` | Informe de factibilidad orquestado en 10 bloques (identidad, contexto administrativo, restricciones, mercado, entorno, contexto económico, evidencia normativa, score heurístico determinístico, warnings y timestamp) con trazabilidad por fuente. |

> **Nota**: el bloque `economic_context` de `get_feasibility_report` consulta la
> capa tabular Predio de ArcGIS (`catastro/lote/MapServer/3`) y no requiere
> `MAPAS_BOGOTA_APIKEY` (esa clave solo la usan la resolución y la UPL por dirección).

Los contratos exactos (JSON Schema de entrada/salida) están en
`specs/001-resolver-lote-contexto/contracts/` (F1),
`specs/002-rag-normativo-upl/contracts/` (F2) y
`specs/003-informe-factibilidad/contracts/` (F3).

Para una guía práctica de uso de las 7 herramientas (entrada y validación, salida,
fuentes consultadas, errores tipificados y ejemplos de invocación), ver
[`Caracteristicas.md`](./Caracteristicas.md).

## Pruebas

```bash
python -m pytest -q
```

- `tests/smoke/`: el servidor arranca y las 7 tools quedan registradas.
- `tests/contract/`: contratos de las tools, taxonomía de errores, validación
  FR-013, trazabilidad (5 campos por dato), estados `disponible`/`no_encontrado`,
  ingesta del corpus (parseo, chunking, hash, indexación idempotente) y escenarios
  del quickstart. Las pruebas usan respuestas simuladas (`httpx.MockTransport`) y
  un embedding function determinista: **no** hacen llamadas de red reales ni
  requieren Ollama.

## Trazabilidad (Principio III, no negociable)

Cada dato presentado al LLM incluye exactamente 5 campos de origen:

- `source_name`: nombre canónico de la fuente (`mapas_bogota`,
  `Mapa_Referencia/Mapa_Referencia`, `catastro/valorreferencia`,
  `ordenamientoterritorial/reservavial`,
  `gestionpublica/obraspublicas`, `IDECA Catastro — Unidad de Planeamiento Local`,
  `Decreto 555 de 2021 (POT Bogotá)`).
- `layer_id`: capa o tema dentro del servicio (p. ej. `38`, `unidadplaneamientolocal.0`,
  `Decreto_555_2021`).
- `service_url`: URL del servicio consultado.
- `data_vigencia`: vigencia del dato en la fuente.
- `query_timestamp`: marca de tiempo de la consulta (ISO 8601 UTC).

> **Nota**: `catastro/destinolt` (destino económico) se retiró del contexto temático:
> el servicio en vivo responde 500 ("Service catastro/destinolt/MapServer not started").
> Puede reincorporarse cuando el servicio vuelva a responder (ver `app/providers/arcgis.py`).

Los datos de vigencias distintas nunca se presentan como una sola fotografía
temporal: cada dato conserva su vigencia (FR-014).

## Estructura del proyecto

```text
app/
├── main.py              # FastMCP: registra las 7 tools (4 F1 + 2 F2 + 1 F3)
├── models.py            # Modelos pydantic (Lote, contexto, UPL, ArticuloNormativo, Chunk, CorpusInfo, InformeFactibilidad)
├── errores.py           # Taxonomía de errores del contrato (10 códigos)
├── scoring.py           # F3: función pura calcular_score (score heurístico determinístico)
├── providers/           # Un provider por fuente (Principio II)
│   ├── mapas_bogota.py  # Mapas Bogotá API (direccion_chip, geocodificar)
│   ├── arcgis.py        # ArcGIS REST (Lote=38 + temáticas; F3: capa Predio + obras por radio)
│   ├── arcgis_utils.py  # Utilidades compartidas (params por punto, consultar_query, CapaConfig)
│   ├── upl.py           # Capa UPL (unidadplaneamientolocal.0) + mapeo nombre → localidad
│   └── normativa.py     # RAG: ChromaDB + embeddings Ollama + chat LLM con citation forcing
├── ingesta/             # Pipeline de ingesta del corpus normativo (F2) y de actos modificatorios (F4)
│   ├── actos.py         # F4: detección de formato, extracción genérica y validación FR-014 de actos
│   └── corpus.py        # Parseo sisjur, chunking, hash SHA-256, indexación ChromaDB, CLI (descargar/indexar/full/consultar/acto)
├── data/corpus/         # Corpus versionado en git (JSONL + .sha256) — FR-009
│   └── actos_modificatorios/  # F4: JSONL + .sha256 por acto + .corpus_consolidado.json
└── tests/
    ├── contract/        # Contratos de las tools, errores, validación, trazabilidad, ingesta
    └── smoke/           # Smoke test de arranque (7 tools)
```

## Docker

```bash
docker build -t mcp-bogota-factibilidad .
docker run --rm -i mcp-bogota-factibilidad
```

El contenedor ejecuta el servidor MCP por stdio; conéctalo como subproceso desde
un cliente MCP (p. ej. el Inspector de MCP). Para Feature 2, el contenedor necesita
acceso al servicio Ollama (p. ej. `--add-host` o red compartida) y el volumen del
índice vectorial ya ingerido.
