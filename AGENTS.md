# AGENTS.md

Workspace de desarrollo dirigido por especificaciones (Spec Kit v0.16.1) para construir
**mcp-bogota-factibilidad**: un servidor MCP (Python) que evalúa la factibilidad
de lotes para construcción en Bogotá, fusionando contexto geoespacial (Mapas Bogotá + ArcGIS REST)
con evidencia normativa del POT (RAG sobre el Decreto 555 de 2021).

## Estado actual

- **Repositorio en `master` con 27 commits; último hito: `feat(plan): feature 3`** (spec/plan de F3).
  El repo ya contiene la aplicación implementada y probada (F1, F2) y la feature F3 en curso.
- **F1 — `specs/001-resolver-lote-contexto/`**: COMPLETA. spec.md, plan.md, research.md,
  data-model.md, contracts/, tasks.md (36 tareas T001–T036 marcadas completadas), quickstart.md,
  checklists/. Implementa las 4 tools de resolución de lote.
- **F2 — `specs/002-rag-normativo-upl/`**: COMPLETA. spec aprobada (3 US, 14 FR, 6 SC), plan,
  research, data-model, contracts, tasks (34 tareas, 6 fases), quickstart, checklists. Implementa
  2 tools (`get_upl`, `consultar_normativa`) + el pipeline de ingesta con el corpus REAL del
  Decreto 555/2021 (608 artículos).
- **F3 — `specs/003-informe-factibilidad/`**: EN CURSO y es la **feature activa**
  (`.specify/feature.json` → `specs/003-informe-factibilidad`). Existen spec.md, plan.md,
  research.md, data-model.md, contracts/, tasks.md (25 tareas T001–T025, NINGUNA marcada aún),
  quickstart.md y checklists/.
  - Estado del código: la parte "Foundational" YA está implementada en disco (modelos F3 en
    `app/models.py`, `app/scoring.py` completo con `calcular_score`, métodos
    `consultar_destino_economico` y `consultar_obras_publicas_radio` en `app/providers/arcgis.py`,
    fixtures F3 en `tests/conftest.py`), pero ese código foundational **parece NO estar
    commiteado aún** (el último commit es solo del plan F3).
  - Pendiente para completar F3: registrar la 7ª tool `get_feasibility_report` en `app/main.py`
    (hoy siguen 6 tools), crear los tests F3 (`test_get_feasibility_report.py`, `test_scoring.py`,
    etc.), actualizar `tests/smoke/test_main.py` (espera 6 tools) y actualizar el README (dice que
    F3 está "fuera de alcance").
- `20260809-01-perplexity.md` es la **fuente de verdad del producto** (arquitectura, fuentes de
  datos, herramientas MCP, pipeline RAG). Léelo antes de especificar o planificar.

## Flujo de trabajo (obligatorio)

La app se construye con la cadena de comandos Spec Kit, en orden:
1. `/speckit.specify` → crea `specs/NNN-<short-name>/spec.md` (numeración secuencial) y `.specify/feature.json`
2. `/speckit.plan` → genera `research.md`, `data-model.md`, `contracts/`, `quickstart.md`
3. `/speckit.tasks` → genera `tasks.md` (formato `- [ ] T### [P] [USn] ...`)
4. `/speckit.implement` → valida con `check-prerequisites.sh --json --require-tasks --include-tasks` y ejecuta `tasks.md`

Notas:
- Separador de invocación `.` (ver `.specify/integration.json`): `/speckit.specify`, no `/speckit-specify`.
- Un `/speckit.specify` crea exactamente una feature. El feature activo se resuelve vía `.specify/feature.json`
  (gitignored, local a la máquina); se fuerza con `SPECIFY_FEATURE_DIRECTORY=<path>`. En monorepos: `SPECIFY_INIT_DIR`.
- `/speckit.implement` exige `plan.md` y `tasks.md` existentes y checklists completos en
  `specs/<feature>/checklists/`; si faltan, pregunta antes de continuar.
- `speckit.plan` y `speckit.tasks` leen `.specify/memory/constitution.md` (ratificada, v1.0.0).
  Enmiéndala con `/speckit.constitution` si cambian los principios.
- Hooks de extensiones se leen de `.specify/extensions.yml` (no existe hoy).
- Comandos auxiliares: `/speckit.clarify`, `/speckit.checklist`, `/speckit.converge`, `/speckit.analyze`, `/speckit.taskstoissues`.

## Datos del dominio (costosos de reconstruir)

- App objetivo: Python (`mcp>=1.0.0` que incluye FastMCP, `httpx`, `pydantic`); MCP por stdio;
  Docker Python; la ingesta del corpus POT se ejecuta de forma explícita (CLI), no automática al iniciar.
  Paquete `mcp-bogota-factibilidad` v0.1.0 (`pyproject.toml`), requires-python `>=3.11`.
- Herramientas MCP: **6 implementadas** (`resolve_lot_by_chip`, `resolve_lot_by_address`,
  `resolve_lot_by_coordinates`, `get_lot_summary_by_chip`, `get_upl`, `consultar_normativa`)
  registradas por `crear_servidor_mcp()` en `app/main.py`, + **`get_feasibility_report` planificada (F3)**
  (7ª tool, aún NO registrada). FastMCP (mcp>=1.x) con fallback a MCPServer (mcp 2.x); transporte stdio;
  lifespan cierra providers (httpx.AsyncClient); validaciones fail-fast (FR-012/FR-013).
- API de búsqueda: `https://catalogopmb.catastrobogota.gov.co/PMBWeb/web/buscar` con
  `cmd=direccion_chip&query=<CHIP>&spatialReference=102100`. Geocodificar/geocodificar_inverso
  usan `https://catalogopmb.catastrobogota.gov.co/PMBWeb/web/api` y requieren
  `MAPAS_BOGOTA_APIKEY` (solo para resolución por dirección). Convierte Web Mercator 102100 → WGS84.
- ArcGIS REST: `https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/`:
  - `Mapa_Referencia/Mapa_Referencia/MapServer` → **Lote = capa 38** (`LOTCODIGO`, `MANZCODIGO`).
  - UPL = `ordenamientoterritorial/unidadplaneamientolocal/MapServer`, **layer `0`** (verificar el
    layer_id exacto en `_configuracion_upl` de `app/providers/upl.py`). El mapeo NOMBRE → localidad
    se deriva estático (nunca se lee de la capa).
  - Temáticas: `catastro/valorreferencia`, `ordenamientoterritorial/reservavial`,
    `gestionpublica/obraspublicas`. `catastro/destinolt` se retiró del contexto: el
    servicio en vivo responde 500 ("not started") y puede reincorporarse cuando vuelva
    (ver `app/providers/arcgis.py`).
  - **F3 — capa tabular Predio**: `catastro/lote/MapServer/3` para destino económico, consultada
    con `f=pjson` (nunca `f=geojson`, responde 400), `where` por `PRECHIP` o `BARMANPRE`, fila
    dominante por mayor `PREAUSO`, vigencia `PREVACTUAL`. Obras públicas por radio: buffer 500 m
    sobre capa multipunto.
  - Consultas: `f=geojson`, `geometry=<lng,lat>&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects`; metadatos con `f=pjson`.
- RAG normativo: corpus = Decreto 555 de 2021 (POT "Bogotá Reverdece 2022-2035") + micrositio POT +
  compendio de Datos Abiertos. **608 artículos en `data/corpus/decreto_555_2021.jsonl` + `.sha256`,
  versionados en git (fuente de verdad, FR-009).** Índice vectorial derivado en `.data/chroma/`
  (gitignored, regenerable), colección `decreto_555_2021`. Chunks con metadatos (norma, artículo,
  tema, vigencia, jerarquía, territorio/UPL). Modelos Ollama: `bge-m3` (embeddings, 1024 dims) y
  `qwen3:8b` (chat, con citation forcing de citas literales verificables).

## Estructura del proyecto

- `app/`: código de aplicación. `main.py` (servidor MCP + lógica de dominio de las 6 tools),
  `models.py` (pydantic v2: F1 SourceTrace/Lote/DatoTematico; F2 UPL/Localidad/ArticuloNormativo/
  Chunk; F3 InformeFactibilidad y bloques), `errores.py` (taxonomía), `scoring.py` (F3, función
  pura `calcular_score`).
- `app/providers/`: un provider por fuente (Principio II): `arcgis.py` (Lote, contexto temático,
  Predio F3, obras por radio), `arcgis_utils.py` (`CapaConfig`, params/consulta compartidos),
  `mapas_bogota.py` (Mapas Bogotá), `upl.py` (capa UPL), `normativa.py` (RAG ChromaDB + Ollama).
- `app/ingesta/corpus.py`: CLI con subcomandos `descargar` (HTML sisjur → JSONL + `.sha256`, SIN
  Ollama), `indexar` (JSONL → ChromaDB), `full` (pipeline completo), `consultar` (debug).
- `tests/`: `smoke/test_main.py` (arranque y registro de tools) y `tests/contract/` (14 archivos:
  resolvers, upl, normativa, ingesta, errores, estados, validación, trazabilidad, quickstart).
  Fixtures con `httpx.MockTransport` en `tests/conftest.py` (sin red real ni Ollama). F3 aún NO
  tiene tests propios.
- `specs/001-*`, `specs/002-*`, `specs/003-*`: features Spec Kit (ver "Estado actual").
- `.specify/`: feature.json (feature activa), integration.json (opencode, separador `.`),
  memory/constitution.md, scripts/, templates/, workflows/.
- `.opencode/`: commands/ (comandos `speckit.*`), opencode.json, package.json (plugin).
- Raíz: `Dockerfile` (multi-etapa, usuario no privilegiado `mcp`, CMD `python -m app.main`),
  `.env.example`, `.gitignore`, `README.md`, `20260809-01-perplexity.md`, `pyproject.toml`.

## Convenciones

- Todo el dominio está en español: especifica, documenta y comenta en español.
- Salida para el LLM: JSON estructurado con trazabilidad por fuente (`source_name`, `layer_id`,
  `service_url`, `data_vigencia`, `query_timestamp`). No mezclar capas de vigencias distintas
  como una sola fotografía temporal.
- El `feasibility_score` es heurístico (F3): el LLM no debe inferir reglas urbanísticas ausentes
  en la fuente (FR-014). `calcular_score` es determinista (SC-003), sin LLM ni reloj: base 50,
  clamps a [0,100], confidence según bloques evaluables.
- Errores: taxonomía canónica de **10 códigos** (`CodigoError` en `app/errores.py`) con excepciones
  tipadas y `construir_error`. Un 5xx NUNCA se reporta como "no encontrado" (FR-009).
- Tests sin red real ni Ollama: siempre usar fixtures `httpx.MockTransport` de `tests/conftest.py`
  (CHIP_VALIDO=AAA0072LRYN, CHIP_INEXISTENTE=ZZZ9999ZZZ9).
- Ingesta: `descargar` no requiere Ollama; `indexar` reconstruye el índice automáticamente si cambia
  el modelo de embeddings (se persiste en la metadata de la colección). El proyecto NO carga `.env`
  automáticamente (lee del entorno; ver `.env.example`).
- `.gitignore`: `data/` NO se ignora (el corpus JSONL es fuente de verdad); `.data/` SÍ se ignora
  (índice derivado).
