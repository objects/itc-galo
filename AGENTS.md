# AGENTS.md

Workspace de desarrollo dirigido por especificaciones (Spec Kit v0.16.1) para construir
**mcp-bogota-factibilidad**: un servidor MCP (Python) que evalúa la factibilidad
de lotes para construcción en Bogotá, fusionando contexto geoespacial (Mapas Bogotá + ArcGIS REST)
con evidencia normativa del POT (RAG sobre el Decreto 555 de 2021).

## Estado actual

- **Repositorio en `master`; HEAD `398e094` (feature 4 implementada y commiteada:
  `feat(feature4): implementar ingesta de actos modificatorios del 555 (US1-US3)`).** La aplicación
  está implementada y probada: F1, F2,
  F3 y F4 completas, **231 tests passing (132 contract F1/F2 + 54 F3 + 2 smoke + 43 F4), 0 failed**,
  gate PASS, con las **7 tools** registradas (F4 no añade tools MCP).
- **F1 — `specs/001-resolver-lote-contexto/`**: COMPLETA. spec.md, plan.md, research.md,
  data-model.md, contracts/, tasks.md (36 tareas T001–T036 marcadas completadas), quickstart.md,
  checklists/. Implementa las 4 tools de resolución de lote.
- **F2 — `specs/002-rag-normativo-upl/`**: COMPLETA. spec aprobada (3 US, 14 FR, 6 SC), plan,
  research, data-model, contracts, tasks (34 tareas, 6 fases), quickstart, checklists. Implementa
  2 tools (`get_upl`, `consultar_normativa`) + el pipeline de ingesta con el corpus REAL del
  Decreto 555/2021 (608 artículos).
- **F3 — `specs/003-informe-factibilidad/`**: COMPLETA e implementada (feature activa,
  `.specify/feature.json` → `specs/003-informe-factibilidad`). spec.md, plan.md, research.md,
  data-model.md, contracts/, quickstart.md y checklists/ (requirements.md 16/16). tasks.md con
  25 tareas T001–T025 **TODAS marcadas `[x]`**.
  - Implementa la 7ª tool `get_feasibility_report`: orquestación de 10 bloques, `_construir_consulta_automatica`
    y 8 helpers de serialización en `app/main.py`; `app/scoring.py` completo (función pura
    `calcular_score`, determinista, sin LLM); modelos F3 en `app/models.py` (InformeFactibilidad + 10
    bloques) y métodos `consultar_destino_economico` (capa Predio) y `consultar_obras_publicas_radio`
    (buffer 500 m) en `app/providers/arcgis.py`. Tests F3: 6 archivos en `tests/contract/` (52 tests)
    + `_f3_shared.py` (constantes compartidas); smoke actualizado a 7 tools. README.md ya documenta F3.
  - Commits: `f19d98a` (foundational F3), `bc70505` (tests F3), `7e3b6c1` (implementación completa),
    luego fixes `b591391`/`c0315cd`, limpieza TDD `ec7e63b`, docs `2e55b5d`/`3a4dc49`/`5939625`
    (Caracteristicas.md con el inventario de las 7 herramientas MCP).
- **F4 — `specs/004-ingesta-actos-modificatorios/`**: COMPLETA e implementada (feature activa,
  `.specify/feature.json` → `specs/004-ingesta-actos-modificatorios`). spec.md, plan.md, research.md,
  data-model.md, contracts/, quickstart.md y checklists/ (requirements.md 16/16). tasks.md con
  26 tareas T001–T026 (6 fases) **TODAS marcadas `[x]`**, gate PASS.
  - Implementa la ingesta CLI de actos que reglamentan o modifican el Decreto 555/2021 en 3 historias:
    **US1** subcomando `acto` con 5 formatos (`sisjur_html`, `pdf`, `docx`, `markdown`, `txt`),
    deduplicación por hash SHA-256 del archivo (FR-007), fallo atómico por documento (FR-009) y
    validación FR-014 (rechazo si `fecha_expedicion < 2021-12-30`); **US2** RAG consolidado en la MISMA
    colección `decreto_555_2021` con `norma`/`source_name` aditivos por ítem (FR-004/FR-005), regla de
    precedencia temporal en el prompt y re-indexación aditiva con huella multi-documento (FR-008);
    **US3** evidencia de F3 (`normative_evidence`) con norma real por ítem sin romper el contrato de F3
    (FR-011, SC-005). Las **7 tools MCP permanecen SIN cambios**.
  - Archivos clave: `app/ingesta/actos.py` (NUEVO: detección de formato + extracción genérica +
    validación FR-014 + registro del corpus consolidado), subcomando `acto` en `app/ingesta/corpus.py`
    (T013/T014), `app/providers/normativa.py` (RAG consolidado + precedencia + `indexar_acto`),
    `app/models.py` (`DocumentoNormativo` + campos aditivos en `ArticuloNormativo`/`Chunk`/
    `ItemEvidenciaNormativa`). Storage: `data/corpus/actos_modificatorios/` (JSONL por acto + `.sha256`
    + `.corpus_consolidado.json`, versionados en git, FR-013).
  - 3 desviaciones menores documentadas del contrato CLI: código de error extra `METADATOS_INCOMPLETOS`,
    `url_origen="cli"` para `--archivo`, y `fecha_vigencia` con fallback a `fecha_expedicion`.
    Dependencias CLI nuevas (solo ingesta): `pypdf>=5`, `python-docx>=1.1` (`pdfplumber` solo CLI como
    alternativa); sin variables de entorno nuevas.
  - Commits: de especificación/plan `ea9415e` (spec+checklist), `b8e328e` (correcciones de revisión
    C1/M1/M2), `601570d` (plan) y de implementación `398e094` (implementación completa). La
    implementación T001–T026 está completa y commiteada. Próximo paso: verificar la ingesta real del
    Decreto 122 de 2023 (SC-001) con Ollama disponible.
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
- Herramientas MCP: **7 implementadas** (`resolve_lot_by_chip`, `resolve_lot_by_address`,
  `resolve_lot_by_coordinates`, `get_lot_summary_by_chip`, `get_upl`, `consultar_normativa`,
  `get_feasibility_report`) registradas por `crear_servidor_mcp()` en `app/main.py`.
  `get_feasibility_report` (F3) orquesta el informe en 10 bloques con scoring heurístico determinístico
  (`calcular_score`) y degrada UPL/RAG con warnings en lugar de errores. FastMCP (mcp>=1.x) con fallback
  a MCPServer (mcp 2.x); transporte stdio;
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
- RAG normativo: corpus consolidado = Decreto 555 de 2021 (POT "Bogotá Reverdece 2022-2035", 608
  artículos, micrositio POT + compendio de Datos Abiertos) + actos modificatorios del 555 (F4).
  **608 artículos del 555 en `data/corpus/decreto_555_2021.jsonl` + `.sha256` y actos en
  `data/corpus/actos_modificatorios/` (JSONL por acto + `.sha256` + `.corpus_consolidado.json`),
  versionados en git (fuente de verdad, FR-009).** Índice vectorial derivado en `.data/chroma/`
  (gitignored, regenerable), colección única `decreto_555_2021` con re-indexación aditiva por documento
  y huella multi-documento (FR-008). Chunks con metadatos extendidos (norma, artículo, tema, vigencia,
  jerarquía, territorio/UPL + `norma_id`, `fecha_vigencia`, `titulo_norma`, `source_name`). Modelos
  Ollama: `bge-m3` (embeddings, 1024 dims) y `qwen3:8b` (chat, con citation forcing de citas literales
  verificables y regla de precedencia temporal de los actos en el prompt).

## Estructura del proyecto

- `app/`: código de aplicación. `main.py` (servidor MCP + lógica de dominio de las 7 tools, incluida
  la orquestación de 10 bloques y `_construir_consulta_automatica` de F3),
  `models.py` (pydantic v2: F1 SourceTrace/Lote/DatoTematico; F2 UPL/Localidad/ArticuloNormativo/
  Chunk; F3 InformeFactibilidad y bloques), `errores.py` (taxonomía), `scoring.py` (F3, función
  pura `calcular_score`, implementada).
- `app/providers/`: un provider por fuente (Principio II): `arcgis.py` (Lote, contexto temático,
  Predio F3, obras por radio), `arcgis_utils.py` (`CapaConfig`, params/consulta compartidos),
  `mapas_bogota.py` (Mapas Bogotá), `upl.py` (capa UPL), `normativa.py` (RAG ChromaDB + Ollama).
- `app/ingesta/`: `corpus.py` (CLI con subcomandos `descargar` (HTML sisjur → JSONL + `.sha256`, SIN
  Ollama), `indexar` (JSONL → ChromaDB), `full` (pipeline completo), `consultar` (debug) y `acto`
  (F4: ingesta de actos modificatorios del 555)) y `actos.py` (NUEVO, F4: detección de formato por
  extensión + magic bytes, extracción genérica PDF/DOCX/MD/TXT, validación FR-014 y registro del
  corpus consolidado).
- `tests/`: `smoke/test_main.py` (arranque y registro de las 7 tools) y `tests/contract/`
  (14 archivos F1/F2 + 6 archivos F3: get_feasibility_report, validación, errores, normativa,
  scoring y trazabilidad + `_f3_shared.py` con constantes compartidas + 3 archivos F4:
  test_ingesta_actos, test_corpus_consolidado, test_precedencia + extensiones aditivas de
  test_consultar_normativa y test_get_feasibility_report). Fixtures con
  `httpx.MockTransport` en `tests/conftest.py` (sin red real ni Ollama).
- `specs/001-*`, `specs/002-*`, `specs/003-*`, `specs/004-*`: features Spec Kit (ver "Estado actual").
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
- F3 degrada por bloque (no fatal): UPL ausente → `upl: null` + warning; RAG no disponible → evidencia
  vacía + causa + warning; un 5xx NUNCA se degrada ni se reporta como "no encontrado" (FR-012/FR-009).
- Errores: taxonomía canónica de **10 códigos** (`CodigoError` en `app/errores.py`) con excepciones
  tipadas y `construir_error`. Un 5xx NUNCA se reporta como "no encontrado" (FR-009).
- Tests sin red real ni Ollama: siempre usar fixtures `httpx.MockTransport` de `tests/conftest.py`
  (CHIP_VALIDO=AAA0072LRYN, CHIP_INEXISTENTE=ZZZ9999ZZZ9).
- Ingesta: `descargar` no requiere Ollama; `indexar` reconstruye el índice automáticamente si cambia
  el modelo de embeddings (se persiste en la metadata de la colección). El proyecto NO carga `.env`
  automáticamente (lee del entorno; ver `.env.example`).
- `.gitignore`: `data/` NO se ignora (el corpus JSONL es fuente de verdad); `.data/` SÍ se ignora
  (índice derivado).
