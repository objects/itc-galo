# Características de `mcp-bogota-factibilidad`

Guía de producto: inventario de las características implementadas y de cómo usarlas.
Cada herramienta cita su contrato (JSON Schema de entrada/salida y estados de error) como
referencia normativa. Todo dato afirmado aquí está contrastado contra esos contratos, los
quickstarts y `app/main.py`; si un valor no está en las fuentes, se omite o se marca
"verificar".

## 1. Resumen del producto

`mcp-bogota-factibilidad` v0.1.0 es un servidor **MCP** (Python, transporte **stdio**) que
evalúa la factibilidad de un lote catastral de Bogotá para construcción, fusionando
**contexto geoespacial** (API de Mapas Bogotá + ArcGIS REST del catastro) con **evidencia
normativa** del POT (RAG local sobre el Decreto 555 de 2021).

- **7 herramientas MCP** registradas por `crear_servidor_mcp()` en `app/main.py` (4 de F1 +
  2 de F2 + 1 de F3).
- **100 % determinista sin LLM** en la resolución de lote, el contexto temático y el
  `feasibility_score` (`app/scoring.py`, función pura). El LLM se usa **solo** en el RAG
  normativo opcional (`consultar_normativa` y la evidencia de `get_feasibility_report`).
- Suite: **419 tests passing (smoke 6 + contract 413), 0 failed** (sin red real ni Ollama).

Las 7 tools:

| Tool | Propósito |
|------|-----------|
| `resolve_lot_by_chip` | Lote por CHIP + contexto temático. |
| `resolve_lot_by_address` | Lote por dirección (geocodificación; requiere `MAPAS_BOGOTA_APIKEY`). |
| `resolve_lot_by_coordinates` | Lote que contiene un punto (WGS84). |
| `get_lot_summary_by_chip` | Resumen consolidado descriptivo por CHIP. |
| `get_upl` | UPL + localidad del lote por CHIP, dirección o coordenadas. |
| `consultar_normativa` | Consulta RAG en lenguaje natural sobre el POT, con citas literales. |
| `get_feasibility_report` | Informe de factibilidad orquestado en 20 bloques. |

## 2. Requisitos previos

- **Python ≥ 3.11** y proyecto instalado: `pip install -e ".[dev]"` (instala `mcp>=1.0.0`,
  `httpx`, `pydantic`, `chromadb`, `pytest`).
- **Acceso de red** a las fuentes públicas:
  - `https://catalogopmb.catastrobogota.gov.co/PMBWeb/web` (API de búsqueda de Mapas Bogotá).
  - `https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/` (ArcGIS REST).
- **Ollama** (`bge-m3` para embeddings y un modelo de chat, p. ej. `qwen3.5:9b`):
  **solo** para la evidencia normativa del RAG. La resolución de lote y el contexto
  temático (F1), y el `feasibility_score`, **no** requieren Ollama. El `.env.example`
  viene preconfigurado contra un servidor Ollama remoto en LAN
  (`http://192.168.40.91:11434`, chat `qwen3.5:9b`); para usar un Ollama local
  (`http://localhost:11434`) hay que ajustar `OLLAMA_HOST`/`OLLAMA_BASE_URL` y hacer
  `ollama pull bge-m3` + `ollama pull <modelo-de-chat>`.
- **`MAPAS_BOGOTA_APIKEY`**: **solo** para resolución/UPL por dirección. Sin ella, esas
  consultas fallan rápido con `CREDENCIAL_FALTANTE`; por CHIP y por coordenadas siguen
  funcionando.
- **Corpus indexado**: antes de `consultar_normativa` (o de evidencia en el reporte) hay que
  ejecutar la ingesta (`python -m app.ingesta.corpus full`). Ver sección 5.
- **Sin red real ni Ollama** para la mayoría de las tools: los tests y los casos
  deterministas usan `httpx.MockTransport` (CHIP válido `AAA0072LRYN`, inexistente
  `ZZZ9999ZZZ9`).

## 3. Configuración

El proyecto **no carga `.env` automáticamente**: las variables se leen del entorno (ver
`.env.example`; opcionalmente `cp .env.example .env` y exportarlas).

| Variable | Obligatoria | Descripción |
|----------|-------------|-------------|
| `MAPAS_BOGOTA_APIKEY` | Solo resolución/UPL por dirección | API key de Mapas Bogotá (`geocodificar`). Sin ella → `CREDENCIAL_FALTANTE`. |
| `OLLAMA_HOST` | Solo F2 | Bind moderno de Ollama (verificación de disponibilidad). Default en código `http://localhost:11434`; `.env.example` apunta al servidor remoto LAN `http://192.168.40.91:11434`. |
| `OLLAMA_BASE_URL` | Solo F2 | Endpoint que usa ChromaDB (`/api/embeddings`). Default en código `http://localhost:11434`; `.env.example` apunta al mismo servidor remoto LAN. |
| `OLLAMA_EMBEDDING_MODEL` | Solo F2 | Embeddings (default `bge-m3`, 1024 dims). Al cambiar, la ingesta reconstruye el índice automáticamente. |
| `OLLAMA_CHAT_MODEL` | Solo F2 | Modelo de chat (default en código `qwen3:8b`; `.env.example` recomienda `qwen3.5:9b`, disponible en el servidor remoto). |
| `CORPUS_URL` | Ingesta | URL oficial del articulado en sisjur (Decreto 555/2021). |
| `VECTOR_DB_PATH` | Solo F2 | Índice ChromaDB (default `.data/chroma`, gitignored). |
| `EMBEDDING_DIM` | Solo F2 | Dimensión del embedding (default `1024`). |

## 4. Las 7 herramientas

Convenciones comunes (se aplican a todas):

- **Trazabilidad de 5 campos** por dato (`source_trace`): `source_name`, `layer_id`,
  `service_url`, `data_vigencia`, `query_timestamp` (ISO 8601 UTC).
- **Estado por fuente** `estado` ∈ `{disponible, no_encontrado}`: un dato ausente o no
  aplicable se reporta como `no_encontrado`, **nunca** como cero ni vacío silencioso.
- **Formato de error canónico** (taxonomía `CodigoError` en `app/errores.py`, 10 códigos):

  ```json
  { "error": { "code": "<CODIGO>", "message": "<mensaje en español>", "source_name": "<fuente>" } }
  ```

- **Un 5xx de una fuente NUNCA se degrada** a "no encontrado" (`FUENTE_5XX` explícito).

### 4.1 `resolve_lot_by_chip`

Resuelve un lote catastral por su **CHIP** (11 caracteres alfanuméricos) y devuelve su
identidad, geometría/centroide y el contexto temático (valor de referencia, reserva vial,
obras públicas). Es la vía de menor fricción (US1, P1).

- **Entrada**

  | Parámetro | Tipo | Obligatorio | Validación |
  |-----------|------|-------------|------------|
  | `chip` | string | Sí | `^[A-Z0-9]{11}$` (exactamente 11 alfanuméricos en mayúsculas). Si no → `PARAMETROS_INVALIDOS` (fail-fast, sin consultar fuentes). |

- **Salida**: `lote` (`chip`, `codigo_catastral`, `manzana`, `direccion_normalizada`,
  `barrio`, `geometry`, `centroid`, `source_trace`) + `contexto_tematico`
  (`valor_referencia`, `reserva_vial`, `obras_publicas`, cada uno con `estado`, `dato`,
  `source_trace`).
- **Fuentes**: `Mapa_Referencia/Mapa_Referencia` (`layer_id=38`, Lote) y, cuando aplique,
  `mapas_bogota` (`layer_id=direccion_chip`).
- **Errores**: `LOTE_NO_ENCONTRADO`, `PARAMETROS_INVALIDOS`, `FUENTE_5XX`.
- **Ejemplo de invocación**:

  ```json
  { "chip": "AAA0072LRYN" }
  ```

- **Contrato**: `specs/001-resolver-lote-contexto/contracts/resolve-lot-by-chip.md`.

### 4.2 `resolve_lot_by_address`

Resuelve un lote por **dirección**: geocodifica dentro de Bogotá y consulta la capa Lote con
el punto resultante. Requiere `MAPAS_BOGOTA_APIKEY` (fail-fast sin ella). Si hay más de un
candidato, responde el caso de múltiples candidatos en lugar de elegir arbitrariamente.

- **Entrada**

  | Parámetro | Tipo | Obligatorio | Validación |
  |-----------|------|-------------|------------|
  | `address` | string | Sí | No vacía ni solo espacios (después de strip). Si no → `PARAMETROS_INVALIDOS`. Requiere `MAPAS_BOGOTA_APIKEY` → si falta, `CREDENCIAL_FALTANTE` (fail-fast). |

- **Salida**: resolución única (`lote` + `contexto_tematico`, igual que `resolve_lot_by_chip`
  pero `chip` puede ser `null` porque la capa Lote de ArcGIS no publica CHIP) o múltiples
  candidatos (`multiples_candidatos: true`, `candidatos[]`, `mensaje`, `source_trace`).
- **Fuentes**: `mapas_bogota` (`layer_id=geocodificar`) + `Mapa_Referencia/Mapa_Referencia`
  (`layer_id=38`).
- **Errores**: `DIRECCION_NO_LOCALIZADA`, `CREDENCIAL_FALTANTE`, `PARAMETROS_INVALIDOS`,
  `FUENTE_5XX`. La dirección ambigua **no** es `DIRECCION_NO_LOCALIZADA` fatal: se responde
  el caso de múltiples candidatos.
- **Ejemplo de invocación**:

  ```json
  { "address": "Calle 26 # 69-76" }
  ```

- **Contrato**: `specs/001-resolver-lote-contexto/contracts/resolve-lot-by-address.md`.

### 4.3 `resolve_lot_by_coordinates`

Resuelve el lote que **contiene un punto** (WGS84, SRID 4326) consultando la capa Lote.
No requiere credencial. Si el punto está fuera de Bogotá → `FUERA_DE_COBERTURA`; si cae en
el límite entre lotes → no hay lote único (error, sin elegir arbitrariamente).

- **Entrada**

  | Parámetro | Tipo | Obligatorio | Validación |
  |-----------|------|-------------|------------|
  | `latitude` | number | Sí | ∈ [-90, 90]. Fuera → `PARAMETROS_INVALIDOS`. |
  | `longitude` | number | Sí | ∈ [-180, 180]. Fuera → `PARAMETROS_INVALIDOS`. |

  Un punto válido en rango pero fuera de Bogotá **no** es inválido: produce
  `FUERA_DE_COBERTURA` tras la consulta espacial.

- **Salida**: `lote` (`chip` puede ser `null`; identidad vía `codigo_catastral`/`manzana`)
  + `contexto_tematico`.
- **Fuentes**: `Mapa_Referencia/Mapa_Referencia` (`layer_id=38`), única fuente de la
  resolución.
- **Errores**: `FUERA_DE_COBERTURA`, `LOTE_NO_ENCONTRADO` (punto en límite entre lotes),
  `PARAMETROS_INVALIDOS`, `FUENTE_5XX`.
- **Ejemplo de invocación**:

  ```json
  { "latitude": 4.60313, "longitude": -74.08327 }
  ```

- **Contrato**: `specs/001-resolver-lote-contexto/contracts/resolve-lot-by-coordinates.md`.

### 4.4 `get_lot_summary_by_chip`

Genera el **resumen consolidado descriptivo** de un lote por CHIP: identidad (sin
`geometry`, deliberadamente) y contexto temático **por fuente**. Es la salida principal para
el LLM consumidor. **Descriptivo**: no calcula puntajes de factibilidad ni infiere reglas
urbanísticas ausentes (FR-011).

- **Entrada**

  | Parámetro | Tipo | Obligatorio | Validación |
  |-----------|------|-------------|------------|
  | `chip` | string | Sí | `^[A-Z0-9]{11}$`. Si no → `PARAMETROS_INVALIDOS`. |

- **Salida**: `identidad` (`chip`, `codigo_catastral`, `manzana`, `direccion_normalizada`,
  `centroid`, `source_trace`) + `contexto_por_fuente[]` (cada entrada con `fuente` ∈
  {`valor_referencia`, `reserva_vial`, `obras_publicas`}, `estado`, `dato`, `source_trace`).
- **Fuentes**: `Mapa_Referencia/Mapa_Referencia` (`layer_id=38`) + `mapas_bogota`
  (`layer_id=direccion_chip`).
- **Errores**: `LOTE_NO_ENCONTRADO`, `PARAMETROS_INVALIDOS`, `FUENTE_5XX`.
- **Ejemplo de invocación**:

  ```json
  { "chip": "AAA0072LRYN" }
  ```

- **Contrato**: `specs/001-resolver-lote-contexto/contracts/get-lot-summary-by-chip.md`.

### 4.5 `get_upl`

Resuelve la **UPL** del lote por CHIP, dirección o coordenadas (reutilizando el resolver de
F1): join espacial punto-en-polígono contra la capa UPL, y localidad derivada por mapeo
`NOMBRE → localidad`. Fallback por coordenadas: si el punto cae en el límite entre lotes,
consulta la capa UPL directamente por el punto (`metodo_resolucion = "punto_directo"`).

- **Entrada** (exactamente uno de los criterios; cero o más de uno → `PARAMETROS_INVALIDOS`)

  | Parámetro | Tipo | Obligatorio | Validación |
  |-----------|------|-------------|------------|
  | `chip` | string | Uno de 3 | `^[A-Z0-9]{11}$`. |
  | `direccion` | string | Uno de 3 | No vacía tras trim; requiere `MAPAS_BOGOTA_APIKEY` → `CREDENCIAL_FALTANTE`. |
  | `coordenadas` | objeto | Uno de 3 | `lat ∈ [-90,90]`, `lon ∈ [-180,180]`; punto válido fuera de Bogotá → `FUERA_DE_COBERTURA`. |

- **Salida**: `metodo_resolucion` (`centroide_lote` | `punto_directo`), `upl` (`codigo`
  `^UPL\d{2}$` UPL01–UPL33, `nombre`, `localidad`), `trazabilidad` (5 campos).
- **Fuentes**: `IDECA Catastro — Unidad de Planeamiento Local`
  (`layer_id=unidadplaneamientolocal.0`); resolución de lote por F1 (capa Lote 38 /
  `mapas_bogota`).
- **Errores**: `LOTE_NO_ENCONTRADO`, `DIRECCION_NO_LOCALIZADA`, `FUERA_DE_COBERTURA`,
  `LOTE_SIN_UPL`, `FUENTE_5XX`, `CREDENCIAL_FALTANTE`, `PARAMETROS_INVALIDOS`.
  `LOTE_SIN_UPL` es "dato no encontrado" para la capa UPL (el lote existe), **distinto** de
  `LOTE_NO_ENCONTRADO`.
- **Ejemplo de invocación**:

  ```json
  { "chip": "AAA0072LRYN" }
  ```

  ```json
  { "coordenadas": { "lat": 4.65, "lon": -74.1 } }
  ```

- **Contrato**: `specs/002-rag-normativo-upl/contracts/get-upl.md`.

### 4.6 `consultar_normativa`

Responde una **consulta en lenguaje natural** sobre el POT (Decreto 555 de 2021) con los
artículos más relevantes, **cita literal** (número y título) y trazabilidad. El `upl`
opcional aplica un **filtro territorial estricto** (`$or` compuesto): artículos de las Partes
del Decreto aplicables a la vocación de suelo de la UPL **o** artículos que mencionan
explícitamente la UPL. Sin resultados relevantes → **abstención explícita** (no es un error).

- **Entrada**

  | Parámetro | Tipo | Obligatorio | Validación |
  |-----------|------|-------------|------------|
  | `consulta` | string | Sí | No vacía tras trim, 1–500 caracteres. Si no → `PARAMETROS_INVALIDOS`. |
  | `upl` | string | No | `^UPL\d{2}$` **y** existente en `UPL01`–`UPL33` (p. ej. `UPL99` rechazado). Si no → `PARAMETROS_INVALIDOS`. |
  | `top_k` | integer | No | 1–6, default 3. Fuera → `PARAMETROS_INVALIDOS`. |

- **Salida**: `respuesta` (texto LLM con citas literales o texto de abstención), `sin_resultados`
  (bool), `resultados[]` (`articulo`, `titulo`, `libro`, `parte` ∈ {general, urbano, rural},
  `texto_cita`, `similitud` ∈ [0,1]), `trazabilidad`.
- **Fuentes**: `Decreto 555 de 2021 (POT Bogotá)` (`layer_id=Decreto_555_2021` =
  identificador de documento, `service_url` sisjur, `data_vigencia=2021-12-30`).
- **Errores**: `PARAMETROS_INVALIDOS`, `CORPUS_NO_INGESTADO`, `OLLAMA_NO_DISPONIBLE`,
  `FUENTE_5XX`. Sin resultados **no** es error (`sin_resultados=true`).
- **Ejemplo de invocación**:

  ```json
  { "consulta": "¿qué se puede construir en suelo urbano?", "top_k": 3 }
  ```

  ```json
  { "consulta": "normas de usos industriales", "upl": "UPL17" }
  ```

- **Contrato**: `specs/002-rag-normativo-upl/contracts/consultar-normativa.md`.

### 4.7 `get_feasibility_report`

Emite el **informe de factibilidad orquestado** en una sola llamada (F3): resuelve el lote,
su UPL y localidad, restricciones (reserva vial), mercado (valor de referencia), entorno
(obras públicas en radio de 500 m), contexto económico (destino económico desde la capa
catastral viva Predio), evidencia normativa (consulta del usuario o automática) y un
`feasibility_score` **100 % determinístico** con reasons trazables. **Degrada por bloque** en
lugar de fallar (ver sección 7).

- **Entrada** (exactamente uno de `chip` | `direccion` | `coordenadas`; cero o más de uno →
  `PARAMETROS_INVALIDOS`)

  | Parámetro | Tipo | Obligatorio | Validación |
  |-----------|------|-------------|------------|
  | `chip` | string | Uno de 3 | `^[A-Z0-9]{11}$`. |
  | `direccion` | string | Uno de 3 | No vacía tras strip, ≤ 200; sin `MAPAS_BOGOTA_APIKEY` → `CREDENCIAL_FALTANTE`. |
  | `coordenadas` | objeto | Uno de 3 | `lat ∈ [-90,90]`, `lon ∈ [-180,180]`. |
  | `consulta` | string | No | 1–500 caracteres, no vacía tras strip. Si se omite, se construye automáticamente (UPL + localidad + clasificación de suelo). |
  | `top_k` | integer | No | 1–6, default 3. |

- **Salida (20 bloques)**: `lot_identity`, `administrative_context` (`upl` + `localidad` +
  `clasificacion_suelo`), `planning_constraints`, `market_context`, `environment_context`
  (`dato.radio_m` = 500), `economic_context` (`codigo_destino`, `descripcion_destino`,
  `uso`, `area_uso`, `usos[]`, `area_terreno`, `area_construccion`, `direccion`, `barrio`,
  `vigencia` = `PREVACTUAL`), `geotechnical_risks`, `socioeconomic_context`,
  `regulatory_environment`, `cultural_heritage`, `transit_access` (F6), `catastro_data`
  (F7), `public_space_context` (Fase 3: EPT m²/hab de la UPL), `road_network_context`
  (Fase 3: ejes viales del frente con jerarquía derivada, radio 100 m), `nearby_facilities`
  (Fase 3: equipamientos por tipo con distancias haversine; multifuente con
  `source_traces`), `urbanistic_parameters` (F8: tratamiento SINUPOT/SDP layer 2,
  edificabilidad capa 14 con precedencia sobre el RAG, retiros y estacionamientos vía parsing
  regex del texto RAG), `normative_evidence` (`items`, `consulta`,
  `consulta_automatica`, `sin_resultados`, `causa`, `source_trace`), `feasibility_score`
  (`score` 0–100, `confidence` ∈ {high, medium, low}, `reasons`, `rules_applied`),
  `warnings[]`, `llm_ready_summary` (resumen determinista en español),
  `query_timestamp`. Cada bloque con `source_trace` de 5 campos.
- **Fuentes**: capa Lote 38; capa UPL (`unidadplaneamientolocal.0`); `catastro/valorreferencia`;
  `ordenamientoterritorial/reservavial`; `gestionpublica/obraspublicas`; **capa tabular Predio**
  `catastro/lote/MapServer/3` (join por `PRECHIP` o `BARMANPRE`, `f=pjson`); capas catastrales F7;
  **SINUPOT/SDP** (`sinu.sdp.gov.co`, layer 2 tratamiento + layer 14 edificabilidad, CRS EPSG:4686);
  capas Fase 3 (`espaciopublico/indicadorespaciopublico` [8], `Mapa_Referencia` [13],
  `salud/serviciosips` [7], `educacion/infraestructuraeducativa` [0],
  `recreaciondeporte/equipamientocultural` [1,2,3]);
  `Decreto 555 de 2021`.
- **Errores fatales (6)**: `PARAMETROS_INVALIDOS`, `LOTE_NO_ENCONTRADO`,
  `FUERA_DE_COBERTURA`, `DIRECCION_NO_LOCALIZADA`, `CREDENCIAL_FALTANTE`, `FUENTE_5XX`.
  Un 5xx nunca se degrada a `no_encontrado`.
- **Ejemplo de invocación**:

  ```json
  { "chip": "AAA0072LRYN" }
  ```

  ```json
  { "coordenadas": { "lat": 4.625188, "lng": -74.081333 } }
  ```

  ```json
  { "chip": "AAA0072LRYN", "consulta": "¿Qué usos del suelo permite la UPL 24 (Chapinero)?", "top_k": 5 }
  ```

- **Contrato**: `specs/003-informe-factibilidad/contracts/get-feasibility-report.md`.

## 4.8 Interfaz Web de Prefactibilidad (Feature 5)

La interfaz web de prefactibilidad es una aplicación **FastAPI + Jinja2 + HTMX 2.0.4** que
expone las 7 tools MCP a través de una UI interactiva, sin protocolo MCP. Construye su propio
`ServidorLotes` con providers reales en el lifespan de FastAPI.

- **Stack**: FastAPI (servidor), Jinja2 (templates), HTMX 2.0.4 (vendorizado, interactividad
  sin JavaScript propio), SQLite (`ProyectoRepositorio` en `app/web/db.py`).
- **Identidad visual "Bogotá Reverdece"**: 5 Pillars de diseño, fuente Fraunces (vendorizada),
  anillo de score SVG.
- **Rutas principales**:

  | Ruta | Método | Propósito |
  |------|--------|-----------|
  | `/` | GET | Landing page (formulario de nuevo proyecto). |
  | `/proyectos` | POST | Crear proyecto + ejecutar informe (303 PRG → detalle). |
  | `/proyectos/{id}` | GET | Detalle del proyecto con informe completo. |
  | `/proyectos/{id}/reevaluar` | POST | Re-ejecutar informe con los mismos parámetros. |
  | `/proyectos/{id}/json` | GET | Exportar informe como JSON. |

- **Mapeo errores taxonomía → HTTP**: `PARAMETROS_INVALIDOS`→400,
  `LOTE_NO_ENCONTRADO`/`FUERA_DE_COBERTURA`/`DIRECCION_NO_LOCALIZADA`→404,
  `CREDENCIAL_FALTANTE`→503, `FUENTE_5XX`→502, resto→500.
- **NO añade tools MCP**: la web usa las 7 tools existentes internamente (construye
  `ServidorLotes` directamente, sin transporte MCP).
- **Ejecución**: `python -m app.web.main` (o entrada de consola `web-mcp-bogota-factibilidad`).
  Variables de entorno: `WEB_HOST`, `WEB_PORT`, `PROYECTOS_DB_PATH` (ver `.env.example`).

## 5. Pipeline de ingesta normativa

CLI `python -m app.ingesta.corpus` (en `app/ingesta/corpus.py`). El JSONL versionado
(`data/corpus/`, ~608 artículos del Decreto 555/2021) es **fuente de verdad** versionada en
git (FR-009); el índice vectorial (`.data/chroma/`) es un dato derivado regenerable.

| Subcomando | Qué hace | Requiere Ollama |
|------------|----------|-----------------|
| `descargar` | Descarga el HTML sisjur, parsea los artículos y guarda `data/corpus/decreto_555_2021.jsonl` + `.sha256` (hash determinista). NO indexa. | No |
| `indexar` | Lee el JSONL versionado y lo indexa en ChromaDB (`.data/chroma/`), idempotente (re-ejecutar no duplica chunks). Si cambió `OLLAMA_EMBEDDING_MODEL`, detecta el cambio en la metadata de la colección y reconstruye el índice automáticamente. | Sí (`bge-m3`) |
| `full` | Pipeline completo: descarga + indexa. | Sí |
| `consultar` | Consulta directa del índice para depuración (flags `--top-k`, `--umbral`, `--upl`, `--ruta-indice`). | Sí |

Ejemplos:

```bash
python -m app.ingesta.corpus full
python -m app.ingesta.corpus descargar            # solo versionar corpus (sin Ollama)
python -m app.ingesta.corpus indexar              # solo indexar JSONL ya versionado
python -m app.ingesta.corpus consultar "usos del suelo" --top-k 5 --umbral 0.35 --upl UPL17
cat data/corpus/decreto_555_2021.jsonl.sha256
```

## 6. Ejecución del servidor

- **Por stdio** (transporte por defecto): `python -m app.main` (o la entrada de consola
  `mcp-bogota-factibilidad`).
- **Docker**: `docker build -t mcp-bogota-factibilidad .` y `docker run --rm -i
  mcp-bogota-factibilidad`. Imagen multi-etapa con usuario no privilegiado `mcp`; ejecuta el
  servidor por stdio. Para la evidencia normativa, el contenedor necesita acceso al servicio
  Ollama (p. ej. `--add-host` o red compartida) y el volumen del índice ya ingerido.
- **Registro como servidor MCP en un cliente**: conéctalo como subproceso por **stdin/stdout**
  (p. ej. el Inspector de MCP u OpenCode). `crear_servidor_mcp()` registra las 7 tools y
  FastMCP (mcp ≥ 1.x) con fallback a MCPServer (mcp 2.x); `lifespan` cierra los
  `httpx.AsyncClient` de los providers al apagar.

## 7. Notas de uso transversales

- **Trazabilidad de 5 campos**: cada dato presenta `source_name`, `layer_id`, `service_url`,
  `data_vigencia` y `query_timestamp`. Nunca se mezclan capas de vigencias distintas como una
  sola fotografía temporal (FR-008/FR-014).
- **`feasibility_score` es heurístico y determinístico** (SC-003): base 50, clamp a
  [0, 100], `confidence` high/medium/low según bloques evaluables, `reasons` con texto fijo
  por regla (dato + `source_name`). **No** es un diagnóstico urbanístico formal (FR-014): el
  LLM no debe inferir reglas urbanísticas ausentes en la fuente.
- **Degradaciones deliberadas de `get_feasibility_report`** (divergencia vs F2, documentada
  en su research): UPL ausente → `administrative_context.upl: null` + warning
  `UPL_NO_ENCONTRADA` (NO `LOTE_SIN_UPL`); RAG no disponible → `normative_evidence.items: []`
  + `causa` (`CORPUS_NO_INGESTADO` / `OLLAMA_NO_DISPONIBLE`) + warning
  `NORMATIVA_NO_DISPONIBLE`; sin resultados → `causa: "SIN_RESULTADOS"` + warning
  `NORMATIVA_SIN_RESULTADOS`. Un 5xx NUNCA se degrada a "no encontrado".
- **Warnings canónicos** del reporte: `LOTE_SIN_CHIP`, `UPL_NO_ENCONTRADA`,
  `LOCALIDAD_NO_DERIVADA`, `BLOQUE_SIN_DATO`, `BLOQUE_DEGRADADO`, `NORMATIVA_NO_DISPONIBLE`,
  `NORMATIVA_SIN_RESULTADOS`.
- **Idioma**: el dominio va en español (atributos `codigo`, `nombre`, `codigo_destino`,
  `descripcion_destino`, `usos`, `estado`, `dato`), mientras que los nombres técnicos de los
  bloques F3 (`score`, `confidence`, `reasons`, `interpretation`, `source_trace`,
  `lot_identity`, `market_context`, …) están en inglés (constitución, Principio I).
- **Diferencias de convención entre F1 y F3** (contrastadas con los contratos):
  - F1 `resolve_lot_by_coordinates` usa parámetros `latitude`/`longitude`; F2/F3
    `get_upl`/`get_feasibility_report` usan el objeto `coordenadas` con claves `lat`/`lon`.
  - El bloque UPL del reporte F3 añade `vocacion` (y deriva `clasificacion_suelo` de él), que
    el contrato F2 de `get_upl` no expone (allí `upl` es `codigo`/`nombre`/`localidad`).
  - `economic_context` consulta la capa Predio con `f=pjson` (**nunca** `f=geojson` →
    400) y su `data_vigencia` = `PREVACTUAL` del registro; no requiere `MAPAS_BOGOTA_APIKEY`.
- **`catastro/destinolt` se retiró** del contexto temático: el servicio en vivo responde 500
  ("not started"); puede reincorporarse cuando vuelva a responder (ver `app/providers/arcgis.py`).
- **Umbral de relevancia del RAG**: 0.30–0.35 (similitud coseno) en el pipeline de
  `consultar_normativa`; por debajo → abstención explícita (`sin_resultados: true`).
- **F4 no añade tools MCP**: la feature 4 (ingesta de actos modificatorios del 555) amplía el
  corpus RAG a un corpus consolidado (Decreto 555 + actos), sin cambiar las 7 tools.
- **F6/F7/F8 no añaden tools MCP**: enriquecen el informe de factibilidad con bloques
  adicionales (F6: geotecnia, socioeconomía, regulatorio, patrimonio, movilidad; F7:
  `catastro_data`; F8: `urbanistic_parameters` vía SINUPOT/SDP + RAG) y extienden el scoring
  (+10 parámetros urbanísticos, +5 estacionamientos calculados, −15 tratamiento Conservación;
  confidence sobre 16 bloques evaluables), sin cambiar las 7 tools.
- **Fase 3 no añade tools MCP**: cierra las brechas temáticas del doc de visión con los bloques
  `public_space_context` (`espaciopublico/indicadorespaciopublico` [8]: EPT m²/hab de la UPL),
  `road_network_context` (`Mapa_Referencia` [13], radio 100 m; jerarquía DERIVADA de `MVITIPO`
  porque la capa no publica jerarquía funcional explícita) y `nearby_facilities`
  (`salud/serviciosips` [7] + `educacion/infraestructuraeducativa` [0] +
  `recreaciondeporte/equipamientocultural` [1,2,3]; distancias haversine desde el centroide).
  Scoring: +5 espacio público suficiente (EPT ≥ 15 m²/hab), +5 frente vial de avenida,
  +5 equipamientos de salud/educación cercanos. Añade además el campo `llm_ready_summary`
  (resumen determinista en español del informe). Las tools `get_lot_geometry` y
  `get_access_context` del doc de visión NO se implementan: la geometría vive en
  `lot_identity.geometry` (+ `centroid`) y el acceso en `transit_access` +
  `road_network_context`.
