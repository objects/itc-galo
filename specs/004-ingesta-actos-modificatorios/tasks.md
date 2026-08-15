# Tasks: Ingesta de actos normativos que modifican el Decreto 555 (corpus consolidado)

**Input**: Diseños de `/specs/004-ingesta-actos-modificatorios/` (plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md)

**Prerequisites**: plan.md (obligatorio), spec.md (obligatorio para historias de usuario), research.md, data-model.md, contracts/, quickstart.md

**Tests**: pytest — smoke test de arranque (`tests/smoke`, SIN CAMBIOS: siguen las 7 tools de F1–F3) y contract tests (`tests/contract`) según plan.md:56-62; las historias incluyen sus contract tests (escribirlos primero para que fallen antes de implementar, patrón F1/F2/F3).

**Organization**: Las tareas se agrupan por historia de usuario para permitir implementación y pruebas independientes de cada historia (constitución v1.0.0, Principio V — MVP first).

## Formato: `T### [P?] [Story] Descripción — Cita`

- **[P]**: Puede ejecutarse en paralelo (archivos distintos, sin dependencias).
- **[Story]**: Historia de usuario a la que pertenece la tarea (US1, US2, US3).
- **Cita**: referencia a `spec.md` (FR/SC), `plan.md`, `research.md`, `data-model.md`, `contracts/ingesta-actos-modificatorios.md` o `quickstart.md` con línea, p. ej. `spec.md:122`.

## Convenciones de rutas

- Proyecto único: `app/`, `tests/` en la raíz del repositorio (plan.md:121-156).
- Estructura: `app/ingesta/corpus.py` (CLI + parser sisjur, MODIFICAR), `app/ingesta/actos.py` (NUEVO), `app/models.py` (pydantic, MODIFICAR aditivo), `app/providers/normativa.py` (RAG, MODIFICAR), `app/main.py` (SIN CAMBIOS funcionales; solo verificación de shapes aditivos), `app/errores.py` (taxonomía, SIN CAMBIOS), `data/corpus/actos_modificatorios/` (JSONL + `.sha256` + registro `.corpus_consolidado.json`), `tests/contract/` y `tests/smoke/` (plan.md:121-156).
- F4 añade 2 dependencias de ingesta SOLO CLI (`pypdf>=5`, `python-docx>=1.1`; `pdfplumber` solo CLI como alternativa para layouts complejos), sin variables de entorno nuevas y sin tools MCP nuevas (plan.md:42-46, research D1:17-32).

---

## Fase 1: Setup (Infraestructura compartida)

**Propósito**: verificar que el stack existente cubre F4 con cambios mínimos de infraestructura — dependencias de ingesta solo CLI (pypdf/python-docx/pdfplumber), sin variables de entorno nuevas, taxonomía de errores F1–F3 intacta y sin tools MCP nuevas (la ingesta es CLI como en F2, D1)

- [x] T001 Verificar y documentar el impacto de infraestructura de F4: `pyproject.toml` gana las 2 dependencias de ingesta SOLO CLI `pypdf>=5` y `python-docx>=1.1` (verificadas en vivo: 6.16.0 y 1.2.0; `pdfplumber` 0.11.10 solo CLI como alternativa) sin tocar el runtime MCP; `.env.example` SIN variables nuevas (se reutilizan `OLLAMA_*`, `VECTOR_DB_PATH`, `CORPUS_URL`); `app/errores.py` SIN códigos nuevos — la taxonomía de 10 códigos de F1–F3 se mantiene intacta y los errores de ingesta son tipificados propios del CLI — plan.md:42-46, plan.md:75-79, data-model.md:178-191
- [x] T002 Verificar que F4 NO introduce tools MCP nuevas: `tests/smoke/test_main.py` permanece SIN CAMBIOS y registra EXACTAMENTE las 7 tools de F1–F3 (`resolve_lot_by_chip`, `resolve_lot_by_address`, `resolve_lot_by_coordinates`, `get_lot_summary_by_chip`, `get_upl`, `consultar_normativa`, `get_feasibility_report`); la alimentación del corpus es por CLI (D1) — research.md:17-32, plan.md:154-155, quickstart.md:127-130

---

## Fase 2: Foundational (Prerrequisitos bloqueantes)

**Propósito**: infraestructura central (modelos aditivos + `DocumentoNormativo`, `app/ingesta/actos.py` NUEVO con detección de formato + extracción genérica + validación FR-014 + registro, adaptación acotada del parser sisjur en `corpus.py` sin romper el 555) que DEBE estar completa antes de que cualquier historia de usuario pueda implementarse

**⚠️ CRITICAL**: ningún trabajo de historias de usuario puede comenzar hasta que esta fase esté completa

- [x] T003 Definir modelos pydantic v2 en `app/models.py`: entidad NUEVA `DocumentoNormativo` (tipo_norma, numero, año, documento_id, titulo, fecha_expedicion, fecha_vigencia, url_origen, hash_sha256, formato, relacion_con_555, articulos_referenciados, estado_documento, derogado_compilado_por; reglas de dominio: rechazo FR-014 si `fecha_expedicion < 2021-12-30`, `relacion_con_555="sin_referencia"` con advertencia, deduplicación por hash) + campos ADITIVOS de `ArticuloNormativo`/`Chunk` (norma_id, tipo_norma, numero, año, fecha_vigencia, titulo_norma; Chunk: source_name, data_vigencia, relacion_con_555) y del ítem de `normative_evidence` (`ItemEvidenciaNormativa` gana `norma`, `source_name`), SIN eliminar ni renombrar campos existentes (FR-011, SC-005); el 555 conserva su esquema con `norma_id=Decreto_555_2021` — data-model.md:40-130, data-model.md:148-152, spec.md:126-129, plan.md:132-135
- [x] T004 Crear `app/ingesta/actos.py` (NUEVO): detección de formato por extensión + magic bytes para los 5 formatos soportados (`sisjur_html`, `pdf`, `docx`, `markdown`, `txt`) con error tipificado `FORMATO_NO_SOPORTADO` (FR-001, FR-009) — research.md D5:93-116, plan.md:128-131, contracts/ingesta-actos-modificatorios.md:69-78
- [x] T005 Implementar en `app/ingesta/actos.py` la extracción genérica (D5): pypdf primario para PDF con pdfplumber como alternativa cuando el orden de lectura no se reconstruye (PDF escaneado → error `SIN_TEXTO_EXTRAIBLE` sugiriendo HTML sisjur), python-docx para DOCX (párrafos + tablas en orden de lectura), stdlib para Markdown/TXT; patrón `Artículo Nº?\.?` con normalización de ordinales textuales (Primero → 1, Único → 1); sin artículos parseables → error `SIN_ARTICULOS_PARSEABLES` (sin ingesta parcial, FR-009) — research.md D5:93-116, spec.md:90-97, contracts/ingesta-actos-modificatorios.md:69-78 — T004 → T005
- [x] T006 [P] Adaptar acotadamente el parser sisjur en `app/ingesta/corpus.py` (D4) sin tocar el flujo del 555: normalizar `Nº.`/`N°.` → `N.` antes de `numero_patron` en `_extraer_titulo_sisjur` y leer el título desde `<i style="font-weight: bold;">` como fuente alternativa (el `<b>` sigue siendo la fuente para el 555); regresión garantizada por `tests/contract/test_ingesta_f2.py` (cubre los 608 artículos del 555) — research.md D4:72-91, research.md H2:165-179, research.md H5:206-212, plan.md:175-177
- [x] T007 Capturar el banner de derogación/compilación de la plantilla sisjur como metadato del documento (H7): `estado_documento="derogado"` y `derogado_compilado_por` (p. ej. "Derogado y compilado por el art. 1526, Decreto Único Distrital de Ordenamiento Territorial 670 de 2025") sin romper el parseo de artículos (el banner vive fuera de los `<p class="MsoNormal">`); el acto derogado SIGUE formando parte del corpus consolidado (SC-001; la eliminación/derogación está fuera de alcance) — research.md H7:225-241, data-model.md:60-61, contracts/ingesta-actos-modificatorios.md:51-52 — T006 → T007
- [x] T008 Implementar la validación FR-014 en `app/ingesta/actos.py`: rechazo tipificado `FECHA_ANTERIOR_AL_555` cuando `fecha_expedicion < 2021-12-30` (el acto no puede reglamentar/modificar el 555; fallo atómico, corpus intacto); extracción de `articulos_referenciados` desde los enlaces internos sisjur (`Norma1.jsp?i=119582#NNN`, H2) — referencia verificable por máquina; acto SIN referencias verificables al 555 → se integra con warning y `relacion_con_555="sin_referencia"` (no se rechaza: la relación no siempre es verificable por máquina) — spec.md:92-93, spec.md:122, data-model.md:58-70, research.md H2:177-179 — T005 → T008
- [x] T009 Implementar en `app/ingesta/actos.py` el registro del corpus consolidado y la escritura versionada (D3): `.corpus_consolidado.json` con hash SHA-256 del archivo + metadatos por documento (deduplicación FR-007/SC-003: si el hash ya existe → no-op con `"duplicado": true`, sin reescribir JSONL ni re-indexar); escritura de `<documento_id>.jsonl` + `.sha256` en `data/corpus/actos_modificatorios/` (FR-013); fallo atómico por documento (FR-009, SC-006): cualquier error deja el corpus existente y el registro intactos — contracts/ingesta-actos-modificatorios.md:80-129, data-model.md:72-86, spec.md:115, spec.md:117, spec.md:121 — T008 → T009
- [x] T010 [P] Extender `tests/conftest.py` con fixtures F4 (patrón payload/status de F1–F3): HTML sisjur del Decreto 122 con anclas `id="1".."13"`, ordinal `Nº.` y título en `<i style="font-weight: bold;">`, enlaces a los artículos 233/243/384 del 555 y banner de derogación (H2/H7); representaciones sintéticas PDF/DOCX/MD/TXT; registro `.corpus_consolidado.json` de prueba — plan.md:56-62, research.md H2:165-179

**Checkpoint**: fundación lista — los modelos aditivos, la extracción genérica, la validación FR-014, el registro versionado y el parser sisjur adaptado (D4) están disponibles; las historias de usuario pueden comenzar.

---

## Fase 3: Historia de Usuario 1 — Ingestar un acto normativo que modifica el Decreto 555 (Prioridad: P1) 🎯 MVP

**Goal**: alimentar el corpus normativo con un acto administrativo (decreto o resolución) que reglamenta o modifica el Decreto 555/2021, en HTML sisjur (recomendado), PDF, DOCX, Markdown o TXT (FR-001), vía el subcomando CLI `acto`, con deduplicación por hash SHA-256 del archivo (FR-007, SC-003), validación temporal/referencial (FR-014) y fallo atómico por documento (FR-009, SC-006); el 555 permanece como norma base INALTERADA (FR-012) y el corpus consolidado se versiona en git (FR-013).

**Prueba independiente**: ejecutar la ingesta del Decreto 122 de 2023 (reglamenta los artículos 233/243/384 de vivienda colectiva) y verificar que sus artículos quedan integrados al corpus consolidado con sus metadatos de norma — spec.md:49

### Tests para Historia de Usuario 1 (escribirlos PRIMERO para que fallen antes de implementar)

- [x] T011 [P] [US1] Contract test de ingesta en `tests/contract/test_ingesta_actos.py` (NUEVO): parseo del HTML sisjur del Decreto 122 (13 artículos con títulos del `<i>` y ordinales `Nº.`, D4/H2), extracción genérica de PDF/DOCX/Markdown/TXT (E4), deduplicación SHA-256 (SC-003, E2), fallo atómico ante formato no soportado / documento sin artículos / fecha anterior al 555 (SC-006, E3/E5) y errores tipificados (`FORMATO_NO_SOPORTADO`, `SIN_TEXTO_EXTRAIBLE`, `SIN_ARTICULOS_PARSEABLES`, `FECHA_ANTERIOR_AL_555`, `DUPLICADO`) — plan.md:150, spec.md:51-56, spec.md:86-96, contracts/ingesta-actos-modificatorios.md:61-78, quickstart.md:68-100
- [x] T012 [P] [US1] Contract test del corpus consolidado en `tests/contract/test_corpus_consolidado.py` (NUEVO): escritura de JSONL + `.sha256` por acto (FR-013), registro `.corpus_consolidado.json` con hash y metadatos por documento (FR-002, FR-007, FR-008), re-ingesta duplicada → no-op sin duplicar artículos ni fragmentos (SC-003), validación FR-014 (rechazo `FECHA_ANTERIOR_AL_555`; acto sin referencia → se integra con `relacion_con_555="sin_referencia"` y warning) — plan.md:151, spec.md:109-122, contracts/ingesta-actos-modificatorios.md:80-129, data-model.md:63-86, quickstart.md:76-100

### Implementación para Historia de Usuario 1

- [x] T013 [US1] Registrar el subcomando `acto` en la CLI `app/ingesta/corpus.py` (patrón F2, D1): argumentos `--url` | `--archivo` (mutuamente excluyentes), `--output` (default `data/corpus/actos_modificatorios/`) y `--indexar`; salida JSON en éxito (documento_id, tipo_norma, numero, año, fecha_expedicion, fecha_vigencia, url_origen, hash_sha256, articulos, relacion_con_555, articulos_referenciados, estado_documento, derogado_compilado_por, duplicado, indexado) y errores tipificados en stderr con exit code ≠ 0 (fallo atómico FR-009) — contracts/ingesta-actos-modificatorios.md:23-78, plan.md:178-179, quickstart.md:48-64
- [x] T014 [US1] Implementar `cmd_acto`: descargar por URL (httpx; decodificación ISO-8859-1/latin-1, H1) o leer archivo local → detectar formato (T004) → extraer artículos (T005) → validar FR-014 (T008) → deduplicar por hash SHA-256 (T009) → escribir JSONL + `.sha256` → actualizar `.corpus_consolidado.json` → `--indexar` (re-indexación aditiva de T020, US2); fallo atómico por documento (FR-009, SC-006); URL no disponible → error accionable `FUENTE_NO_DISPONIBLE` (misma semántica de `cmd_descargar` de F2, exit code ≠ 0) — research.md H1:156-163, spec.md:98, data-model.md:178-191, quickstart.md:48-64 — T013 → T014

**Checkpoint**: Historia de Usuario 1 funcional y comprobable de forma independiente (MVP; SC-003: dedup 100 %, SC-006: fallo atómico, SC-001: ingesta del 122 en < 5 s sin Ollama — FR-010); el corpus consolidado queda versionado en git (JSONL + `.sha256` + registro) sin tocar el 555. La consultabilidad del acto y el `--indexar` llegan en Fase 4 (T020, re-indexación aditiva).

---

## Fase 4: Historia de Usuario 2 — Consultar el corpus consolidado con identificación de norma y precedencia temporal (Prioridad: P1)

**Goal**: que `consultar_normativa` responda con fragmentos del corpus consolidado (555 + actos) indicando la norma de origen de cada ítem (`norma`, `source_name` aditivos, FR-004/FR-005) y aplicando la regla de precedencia temporal al LLM vía prompt (el acto posterior prevalece, sin ocultar artículos del 555 — FR-006, SC-004), con re-indexación aditiva solo de documentos cambiados (FR-008).

**Prueba independiente**: consultar un tema reglamentado por un acto posterior (p. ej. vivienda colectiva, Decreto 122 de 2023) y verificar que la respuesta menciona el acto modificatorio como norma de origen y que el LLM prioriza el acto posterior sin ocultar el artículo original del 555 — spec.md:64

### Tests para Historia de Usuario 2 (escribirlos PRIMERO para que fallen antes de implementar)

- [x] T015 [P] [US2] Contract test de precedencia en `tests/contract/test_precedencia.py` (NUEVO): el prompt del RAG incluye la regla de precedencia temporal (FR-006, SC-004) — texto canónico "el acto posterior PREVALECE... Cita ambas normas sin ocultar los artículos del 555" —, los fragmentos del contexto se ordenan por `fecha_vigencia` descendente (el acto más reciente primero) y el citation forcing de F2 (citas literales verificables) se mantiene sin cambios — research.md D7:136-150, contracts/ingesta-actos-modificatorios.md:153-164, spec.md:114, spec.md:138, quickstart.md:102-111
- [x] T016 [P] [US2] Extensión ADITIVA de `tests/contract/test_consultar_normativa.py`: actualizar `set(resultado) == {...}` (línea 300) SOLO para añadir `norma` y `source_name` (SC-005, sin cambios semánticos en los campos existentes); verificar que un fragmento del 555 lleva `norma: "Decreto 555 de 2021"` y un fragmento de un acto lleva `norma: "Decreto 122 de 2023"`, y que ambos coexisten sin ocultarse cuando cubren el mismo tema — spec.md:139, data-model.md:139-146, contracts/ingesta-actos-modificatorios.md:131-145
- [x] T017 [P] [US2] Extender `tests/contract/test_corpus_consolidado.py` con la re-indexación aditiva (FR-008, E7): tras ingestar un acto, la re-indexación upserta SOLO los chunks del documento cambiado (ids `norma_id-art-<NNN>`) en la colección única `decreto_555_2021`; la huella multi-documento se persiste en la metadata de la colección y un cambio de documento o del modelo de embeddings (bge-m3) dispara reconstrucción automática sin mezclar vectores de versiones ni modelos distintos — plan.md:56-62, spec.md:116, quickstart.md:113-119

### Implementación para Historia de Usuario 2

- [x] T018 [US2] Modificar `app/providers/normativa.py` para consultar el corpus consolidado (D2): leer los metadatos extendidos del chunk (`norma_id`, `tipo_norma`, `numero`, `año`, `fecha_vigencia`, `titulo_norma`, `source_name`, `data_vigencia`, `relacion_con_555`) en `_procesar_resultados` y añadir `norma` + `source_name` a cada ítem de `resultados` (FR-004, FR-005), SIN eliminar ni renombrar campos existentes (FR-011); la misma colección `decreto_555_2021` sigue siendo la única fuente de consulta (FR-003) — research.md D6:118-134, data-model.md:113-152, plan.md:180-182
- [x] T019 [US2] Añadir la regla de precedencia temporal al prompt del RAG en `app/providers/normativa.py` (`_generar_respuesta_llm`, D7): texto canónico del contrato ("Cuando un acto posterior reglamente o modifique un artículo del 555, el acto posterior PREVALECE. Cita ambas normas sin ocultar los artículos del 555 (coexistencia de fuentes) e indica la norma de origen de cada cita.") y ordenar los fragmentos del contexto por `fecha_vigencia` descendente; mantener el citation forcing de F2 (citas literales verificables) — contracts/ingesta-actos-modificatorios.md:153-164, research.md D7:136-150, spec.md:114
- [x] T020 [US2] Implementar la re-indexación aditiva solo de documentos cambiados (FR-008, D2/D3): extender la indexación (`app/ingesta/corpus.py` o helper en `actos.py`) para upsert SOLO los chunks del acto en la colección única `decreto_555_2021`, con ids `norma_id-art-<NNN>` para los actos (patrón existente `art-<NNN>` para el 555, data-model.md:121) y metadatos extendidos de norma (data-model.md:113-130); persistir la huella multi-documento (un hash por documento del registro `.corpus_consolidado.json`) en la metadata de la colección y reconstruir automáticamente cuando cambie un documento o el modelo de embeddings (bge-m3, 1024 dims); con esto el `--indexar` del CLI (T014) queda funcional — research.md D2:34-52, research.md D3:54-70, data-model.md:72-86, data-model.md:113-130, spec.md:116 — T020 → T014

**Checkpoint**: Historias de Usuario 1 y 2 funcionales de forma independiente (SC-002: norma de origen en el 100 % de los fragmentos, SC-004: precedencia temporal en el 100 % de las consultas, FR-008: re-indexación aditiva).

---

## Fase 5: Historia de Usuario 3 — Informe de factibilidad con evidencia del corpus consolidado (Prioridad: P2)

**Goal**: que `get_feasibility_report` use el corpus consolidado para su bloque `normative_evidence` sin romper el contrato de F3 — el `source_trace` de bloque se conserva y la norma real de cada fragmento se expone de forma aditiva por ítem (`norma`/`source_name`), para que el informe cite la norma vigente aplicable al lote (555 o acto modificatorio).

**Prueba independiente**: invocar `get_feasibility_report` para un lote cuyo tema está reglamentado por un acto posterior y verificar que `normative_evidence` cita la norma real (555 o acto modificatorio) en la identificación de norma por ítem, conservando la estructura del contrato de F3 — spec.md:78

### Tests para Historia de Usuario 3 (escribirlos PRIMERO para que fallen antes de implementar)

- [x] T021 [P] [US3] Extensión ADITIVA de `tests/contract/test_get_feasibility_report.py`: actualizar el shape de `normative_evidence` (líneas 182-196) SOLO para añadir `norma`/`source_name` por ítem (SC-005), conservando el `source_trace` de bloque intacto (FR-004); verificar determinismo (dos ejecuciones con los mismos datos y corpus → resultado idéntico, spec.md:83) y degradación vacía con `causa` (`CORPUS_NO_INGESTADO`/`OLLAMA_NO_DISPONIBLE`) + warning `NORMATIVA_NO_DISPONIBLE` cuando la infraestructura RAG no está disponible, sin fallar el reporte (spec.md:84) — spec.md:82-84, spec.md:139, data-model.md:148-152, contracts/ingesta-actos-modificatorios.md:147-151

### Implementación para Historia de Usuario 3

- [x] T022 [US3] Propagar la norma real por ítem en el orquestador F3 (`app/main.py`): extender el mapeo de `resultado_normativa["resultados"]` → `ItemEvidenciaNormativa` (líneas ~691-700) para incluir `norma` y `source_name` (FR-004, FR-005), conservando el `source_trace` de bloque, la taxonomía de errores y la semántica de degradación de F3 (FR-011, SC-005); `app/main.py` queda SIN cambios funcionales — solo verificación de shapes aditivos — plan.md:140, spec.md:82, data-model.md:148-152, contracts/ingesta-actos-modificatorios.md:147-151 — T021 → T022

**Checkpoint**: las tres historias de usuario funcionales de forma independiente (SC-002, SC-004, SC-005: 185 tests de F1–F3 intactos + extensiones aditivas).

---

## Fase 6: Polish y transversal

**Propósito**: pruebas transversales (regresión completa, docs, gate y checklist) que afectan a múltiples historias

- [x] T023 [P] Ejecución completa de pytest: no-regresión de F1–F3 (tests existentes en `tests/contract/` y `tests/smoke/` — SC-005 fija 185 tests de F1–F3; AGENTS.md reporta 188: 132 F1/F2 + 54 F3 + 2 smoke) + tests nuevos de F4 (`test_ingesta_actos.py`, `test_corpus_consolidado.py`, `test_precedencia.py` + extensiones aditivas de `test_consultar_normativa.py` y `test_get_feasibility_report.py`), sin red real ni Ollama en vivo — plan.md:56-62, spec.md:139, quickstart.md:35-46
- [x] T024 [P] Actualizar `README.md` raíz: documentar el subcomando `acto` de la ingesta (formatos soportados, deduplicación SHA-256, precedencia temporal, fallo atómico), el corpus consolidado (`data/corpus/actos_modificatorios/` con JSONL + `.sha256` + `.corpus_consolidado.json`) y que F4 NO añade tools MCP (siguen las 7 de F1–F3) — plan.md:81-84, research.md D1:17-32, quickstart.md:127-130
- [x] T025 Ejecutar `.specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks` → PASS con `plan.md`, `tasks.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md` y checklists completos — AGENTS.md flujo de trabajo, plan.md:7-11
- [x] T026 Mantener completada la checklist `checklists/requirements.md` 16/16 (CHK-001 a CHK-016) y verificación cruzada spec ↔ plan ↔ contratos ↔ data-model ↔ tasks (sin regresiones a F1/F2/F3) — checklists/requirements.md:1-27, spec.md:139

---

## Dependencias y orden de ejecución

### Dependencias por fase

- **Setup (Fase 1)**: sin dependencias — puede comenzar de inmediato (T001/T002 son verificaciones de infraestructura/no-cambio).
- **Foundational (Fase 2)**: depende de Setup — BLOQUEA todas las historias.
- **Historias de usuario (Fases 3-5)**: dependen de Foundational; además, US1 (T014) usa los modelos (T003), la detección/extracción (T004/T005), la validación FR-014 (T008) y el registro (T009); US2 (T020) depende de US1 (T014 produce el JSONL/registro que la re-indexación aditiva consume) y habilita el `--indexar` del CLI; US3 (T022) depende de US2 (la evidencia de F3 consume los ítems con `norma`/`source_name` del provider, T018). El orden MVP-first secuencial (P1 → P1 → P2) es el previsto.
- **Fase 5 (US3)**: depende de Fase 4 (US2) — T022 propaga los campos aditivos que T018 genera en el provider; la verificación del shape aditivo de `normative_evidence` vive exclusivamente en T021 (US3), no en los tests de US1/US2, para no romper la independencia de los checkpoints.
- **Polish (Fase 6)**: depende de las historias deseadas completas.

### Dentro de cada historia

- Los contract tests se escriben PRIMERO y deben fallar antes de implementar.
- Validación y manejo de errores (FR-014, fallo atómico) antes de la integración completa del CLI.
- La historia se completa antes de pasar a la siguiente prioridad.

### Oportunidades de paralelismo

- Foundational: T003 (models.py), T006/T007 (corpus.py) y T010 (conftest.py) tocan archivos distintos y pueden ejecutarse en paralelo; T004 → T005 → T008 → T009 son secuenciales dentro de `app/ingesta/actos.py` (mismo archivo) y T006 → T007 secuenciales en `app/ingesta/corpus.py`.
- T011 y T012 (US1) son contract tests de archivos distintos (test_ingesta_actos.py, test_corpus_consolidado.py) y pueden ejecutarse en paralelo.
- T015, T016 y T017 (US2) son contract tests de archivos distintos (test_precedencia.py, test_consultar_normativa.py, test_corpus_consolidado.py) y pueden ejecutarse en paralelo; T015/T016 no dependen de T020.
- T013 → T014 son estrictamente secuenciales (mismo módulo `app/ingesta/corpus.py`).
- T018 y T019 (US2) tocan zonas distintas de `app/providers/normativa.py` (mapeo de resultados y prompt) y pueden ejecutarse en paralelo; T020 (re-indexación aditiva) depende de US1 (T014).
- T021 → T022 (US3) son estrictamente secuenciales: la extensión del test precede a la propagación en `app/main.py`.
- T023 y T024 (Polish) tocan distintos (`pytest` completo y `README.md`) y pueden ejecutarse en paralelo.

---

## Estrategia de implementación

### MVP primero (solo Historia de Usuario 1)

1. Completar Fase 1 (Setup).
2. Completar Fase 2 (Foundational) — CRÍTICO, bloquea todo.
3. Completar Fase 3 (Historia de Usuario 1) — la ingesta CLI escribe JSONL + registro con dedup y fallo atómico SIN Ollama (FR-010).
4. **DETENERSE y VALIDAR**: probar la Historia de Usuario 1 de forma independiente (SC-001: ingesta del 122 en < 5 s sin Ollama, SC-003: dedup 100 %, SC-006: fallo atómico).
5. Continuar con US2 y US3 (entrega incremental).

### Entrega incremental

1. Setup + Foundational → fundación lista.
2. Agregar Historia de Usuario 1 → probar independientemente → MVP (corpus versionado, sin indexación).
3. Agregar Historia de Usuario 2 → probar independientemente (norma por ítem + precedencia temporal + re-indexación aditiva).
4. Agregar Historia de Usuario 3 → probar independientemente (evidencia F3 con norma real por ítem).
5. Cada historia agrega valor sin romper las anteriores (no-regresión F1/F2/F3).

---

## Notas

- [P] = archivos distintos, sin dependencias.
- [Story] = historia de usuario para trazabilidad de la tarea.
- Cada historia es completable y comprobable de forma independiente.
- Verificar que los tests fallen antes de implementar.
- Commit en cada hito ratificado (constitución, Flujo de desarrollo).
- Evitar tareas vagas, conflictos de archivos compartidos y dependencias entre historias que rompan la independencia.
- Aditividad estricta (FR-011, SC-005): ningún campo existente de F1/F2/F3 se elimina ni renombra; los shapes exactos — `set(resultado) == {...}` en `tests/contract/test_consultar_normativa.py:300` y el shape de `normative_evidence` en `tests/contract/test_get_feasibility_report.py:182` — se actualizan SOLO para incluir `norma`/`source_name`.
- El 555 permanece como norma base (FR-012): su JSONL versionado no se modifica; los actos se integran como documentos nuevos versionados en git (FR-013).
- La ingesta (descarga/parseo/validación) NO requiere Ollama (FR-010); solo `--indexar` y las consultas lo requieren.
- `tests/smoke/test_main.py` SIN CAMBIOS: siguen las 7 tools de F1–F3 (research D1; no hay tools MCP nuevas).
- Los errores de la ingesta son tipificados propios del CLI (`FORMATO_NO_SOPORTADO`, `SIN_TEXTO_EXTRAIBLE`, `SIN_ARTICULOS_PARSEABLES`, `FECHA_ANTERIOR_AL_555`, `FUENTE_NO_DISPONIBLE`, `DUPLICADO`) con fallo atómico por documento; la taxonomía de 10 códigos de `app/errores.py` no se toca (data-model.md:178-191).
