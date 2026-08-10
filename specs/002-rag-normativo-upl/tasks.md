# Tasks: RAG normativo del POT (Decreto 555/2021) con consulta de UPL

**Input**: Diseños de `/specs/002-rag-normativo-upl/` (plan.md, spec.md, research.md, data-model.md, contracts/)

**Prerequisites**: plan.md (obligatorio), spec.md (obligatorio para historias de usuario), research.md, data-model.md, contracts/

**Tests**: pytest — smoke test de arranque (`tests/smoke`) y contract tests (`tests/contract`) según plan.md:539; las historias incluyen sus contract tests (escribirlos primero para que fallen antes de implementar).

**Organization**: Las tareas se agrupan por historia de usuario para permitir implementación y pruebas independientes de cada historia (constitución v1.0.0, Principio V — MVP first).

## Formato: `T### [P?] [Story] Descripción — Cita`

- **[P]**: Puede ejecutarse en paralelo (archivos distintos, sin dependencias).
- **[Story]**: Historia de usuario a la que pertenece la tarea (US1, US2, US3).
- **Cita**: referencia a `spec.md` (FR/SC), `data-model.md`, `contracts/` o `plan.md` con línea, p. ej. `spec.md:79`.

## Convenciones de rutas

- Proyecto único: `app/`, `tests/` en la raíz del repositorio (plan.md:147).
- Estructura: `app/main.py` (FastMCP, 6 tools), `app/models.py` (pydantic), `app/errores.py` (taxonomía), `app/providers/` (un provider por fuente + `arcgis_utils.py` compartido), `app/ingesta/` (corpus), `tests/contract/` y `tests/smoke/`.

---

## Fase 1: Setup (Infraestructura compartida)

**Propósito**: habilitar las dependencias y la configuración de entorno del stack local (Ollama + ChromaDB + ingesta) sin romper F1

- [ ] T001 Añadir dependencias nuevas a `pyproject.toml`: `chromadb>=1.0.0` (vector store persistente) y `beautifulsoup4>=4.12.0` (parseo defensivo del HTML de sisjur); `httpx` ya existe (se reutiliza para Ollama y la descarga) y `pytest` ya está en dev — plan.md:188-191, plan.md:168
- [ ] T002 [P] Añadir y documentar en `.env.example` las 7 variables nuevas (manteniendo `MAPAS_BOGOTA_APIKEY`): `OLLAMA_HOST=http://localhost:11434` (default), `OLLAMA_BASE_URL`, `OLLAMA_EMBEDDING_MODEL=bge-m3`, `OLLAMA_CHAT_MODEL=qwen3:8b`, `CORPUS_URL` (default sisjur `Norma1.jsp?i=119582`), `VECTOR_DB_PATH=.data/chroma`, `EMBEDDING_DIM=1024` — plan.md:192-202, plan.md:214-217
- [ ] T003 [P] Añadir `.data/` al `.gitignore` (directorio del índice vectorial, regenerable); `data/` queda versionada en git (corpus JSONL y su `.sha256`) — plan.md:203-205
- [ ] T004 [P] Actualizar `README.md` raíz con la nota de requisito Ollama en la sección Requisitos (`ollama pull bge-m3` y `ollama pull qwen3:8b`) — plan.md:206-208
- [ ] T005 [P] Añadir a `app/errores.py` los 3 códigos nuevos (`LOTE_SIN_UPL`, `CORPUS_NO_INGESTADO`, `OLLAMA_NO_DISPONIBLE`) a los 7 existentes y las excepciones tipadas `CorpusNoIngestadoError`/`OllamaNoDisponibleError` (patrón de `Fuente5xxError`, con `source_name`) — plan.md:434-442, data-model.md:224-226

---

## Fase 2: Foundational (Prerrequisitos bloqueantes)

**Propósito**: infraestructura central (modelos, utilidades ArcGIS compartidas, ingesta del corpus y providers UPL/normativa) que DEBE estar completa antes de que cualquier historia de usuario pueda implementarse

**⚠️ CRITICAL**: ningún trabajo de historias de usuario puede comenzar hasta que esta fase esté completa

- [ ] T006 Definir modelos pydantic v2 nuevos en `app/models.py`: `UPL` (codigo_upl, nombre, localidad_derivada, acto_administrativo, numero_acto_administrativo, fecha_acto_administrativo, normativa, vocacion, observacion, area_ha, estado, source_trace), `Localidad` (codigo, nombre), `ArticuloNormativo` (numero, titulo, texto, libro, parte, seccion, upls_mencionadas, articulos_derogados), `Chunk` (id, articulo, titulo, libro, parte, seccion, texto) y `CorpusInfo` (documento, vigencia, hash) — spec.md:96-99, data-model.md:57-156, plan.md:130
- [ ] T007 [P] Crear `app/providers/arcgis_utils.py` con funciones puras que reciben el cliente explícitamente: `construir_params_punto(lat, lon) -> dict`, `consultar_query(client: httpx.AsyncClient, base_url, layer_id, params) -> dict` y `CapaConfig` — plan.md:303-312
- [ ] T008 Refactorizar `app/providers/arcgis.py` para usar `arcgis_utils` sin cambiar su comportamiento (garantía de no-regresión: los 33 tests de F1 siguen pasando) — plan.md:154-157, plan.md:344
- [ ] T009 Implementar la ingesta en `app/ingesta/corpus.py`: `descargar_html` (httpx, timeout generoso y reintento; 5xx/fallo de red → `Fuente5xxError`) y `extraer_articulos` (regex `ART[ÍI]CULO\s+(\d+)\.?\s+(.*?)`, manejo de parágrafos y detección de encabezados Libro/Capítulo/Sección → `libro`/`parte`/`seccion`) — plan.md:234-247
- [ ] T010 Ingesta: chunking boundary-aware (`1 chunk = 1 artículo`; largos por parágrafos con overlap; metadatos `{articulo, titulo, libro, parte, seccion}` + `upls_mencionadas`; id `decreto555-2021-art-{N}-{i}`) y hash SHA-256 del JSONL del corpus — plan.md:248-255, plan.md:262-265
- [ ] T011 Ingesta: indexar en ChromaDB persistente (`PersistentClient(VECTOR_DB_PATH)`, colección `decreto555_2021`, `OllamaEmbeddingFunction` bge-m3), re-indexación idempotente, CLI `python -m app.ingesta.corpus` con fail-fast de Ollama, guardar JSONL + `.sha256` en `data/corpus/decreto_555_2021.jsonl` y verificación de integridad (608 artículos, SC-006) — plan.md:256-273, plan.md:279-286
- [ ] T012 [P] Implementar provider `app/providers/upl.py`: `CapaConfig` UPL (`unidadplaneamientolocal.0`, `data_vigencia=2021-12-30`), `consultar_upl_por_punto` reutilizando `arcgis_utils` (depende de T007), parseo `UPLArcgis` (`CODIGO_UPL`, `NOMBRE`), mapeo `NOMBRE → localidad` (tabla versionada de 33 entradas), trazabilidad de 5 campos, errores `FUENTE_5XX`/`LOTE_SIN_UPL` — plan.md:313-338, contracts/get-upl.md:14-18
- [ ] T013 [P] Implementar provider `app/providers/normativa.py`: cliente ChromaDB, `verificar_corpus` (hash contra `decreto_555_2021.jsonl.sha256`), `verificar_ollama` (`/api/tags` y modelo), `recuperar` (top-k 4–6 → umbral 0.30–0.35 → top-3; filtro UPL estricto por metadatos), `generar_respuesta` (`/api/chat`, qwen3:8b, temp 0.1, system prompt fijo anti-inyección), citation forcing (post-verificación), abstención explícita y errores `CORPUS_NO_INGESTADO`/`OLLAMA_NO_DISPONIBLE` — plan.md:364-409, contracts/consultar-normativa.md:17-24

**Checkpoint**: fundación lista — las historias de usuario pueden comenzar.

---

## Fase 3: Historia de Usuario 1 — Consultar la normativa del POT (Prioridad: P1) 🎯 MVP

**Goal**: responder consultas en lenguaje natural sobre el POT (Decreto 555/2021) con los artículos más relevantes, cita literal verificable (número, título y texto) y trazabilidad por fuente, mediante el RAG 100% local (ChromaDB + Ollama).

**Prueba independiente**: consultar un tema con el corpus del Decreto 555/2021 indexado y Ollama disponible, y verificar que la respuesta contiene los artículos más relevantes con cita literal verificable contra el corpus; probar también el caso de consulta sin resultados relevantes — spec.md:21

### Tests para Historia de Usuario 1 (escribirlos PRIMERO para que fallen antes de implementar)

- [ ] T014 [P] Extender `tests/conftest.py` con fixtures F2: corpus sintético (HTML con N artículos de texto conocido y `libro`/`parte`/`seccion`), vector store sintético determinista (ChromaDB en `tmp_path` con embedding function sintética de 1024 dims), `provider_upl_estandar` (patrón payload/status de F1) y mock de Ollama (`/api/tags`, `/api/embeddings` legacy, `/api/chat`) — plan.md:492-504
- [ ] T015 [P] [US1] Contract test de `consultar_normativa` en `tests/contract/test_consultar_normativa.py` (mocks httpx de Ollama `/api/embeddings` legacy + `/api/chat`; corpus sintético) — spec.md:21, plan.md:529
- [ ] T016 [P] [US1] Test de abstención sin resultados: ningún chunk sobre el umbral → `sin_resultados=true` con texto de abstención y `resultados=[]`, sin llamar al chat — spec.md:26, spec.md:82, contracts/consultar-normativa.md:196-213

### Implementación para Historia de Usuario 1

- [ ] T017 [US1] Registrar tool `consultar_normativa` en `app/main.py`: validación FR-013 en el límite (consulta 1–500 chars, `top_k` 1–6 default 3, `upl` opcional) y mapeo canónico de errores (`CORPUS_NO_INGESTADO`, `OLLAMA_NO_DISPONIBLE`), extendiendo el clasificador `_error_de_fuente` — spec.md:91, plan.md:444-445, plan.md:454-461
- [ ] T018 [US1] Implementar el pipeline completo de `consultar_normativa`: recuperación → generación con citas literales → post-verificación (citation forcing) → serialización `{respuesta, sin_resultados, resultados, trazabilidad}` — spec.md:25, spec.md:79, contracts/consultar-normativa.md:17-24
- [ ] T019 [US1] Actualizar `tests/smoke/test_main.py` de 4 a 6 tools en el MISMO hito en que se registra `consultar_normativa` (sin dejar ventana roja) — plan.md:465-467, plan.md:172

**Checkpoint**: Historia de Usuario 1 funcional y comprobable de forma independiente (MVP).

---

## Fase 4: Historia de Usuario 2 — Consultar la UPL de un lote (Prioridad: P2)

**Goal**: resolver la UPL de un lote por CHIP, dirección o coordenadas (reutilizando el resolver de lote de F1) mediante join espacial punto-en-polígono contra la capa UPL, con localidad derivada y trazabilidad de la capa.

**Prueba independiente**: consultar un CHIP válido y verificar que la respuesta contiene el código y el nombre de la UPL y la localidad del lote, con trazabilidad de la capa; probar también el caso de lote sin UPL asignada — spec.md:37

### Tests para Historia de Usuario 2 (escribirlos PRIMERO para que fallen antes de implementar)

- [ ] T020 [P] [US2] Contract test de `get_upl` en `tests/contract/test_get_upl.py` (mock de la capa ArcGIS UPL con el patrón conftest de F1: payload/status) — spec.md:37, plan.md:526
- [ ] T021 [P] [US2] Tests de errores de `get_upl`: `LOTE_SIN_UPL`, `FUERA_DE_COBERTURA` y lote no encontrado — spec.md:42, spec.md:43, spec.md:85, spec.md:69

### Implementación para Historia de Usuario 2

- [ ] T022 [US2] Registrar tool `get_upl` en `app/main.py`: validación de exactamente uno de `{chip, direccion, coordenadas}` (reutilizando `_validar_chip`, `_validar_coordenadas` y `CREDENCIAL_FALTANTE`), propagando los errores del resolver F1 — spec.md:83, spec.md:91, plan.md:444-445, contracts/get-upl.md:61-72
- [ ] T023 [US2] Implementar la composición completa de `get_upl`: resolver lote (F1) → centroide → `UPLProvider.consultar_upl_por_punto` → localidad derivada → `LOTE_SIN_UPL` si `None` → serializar `{upl, trazabilidad}` — spec.md:41, spec.md:84, contracts/get-upl.md:14-18

**Checkpoint**: Historias de Usuario 1 y 2 funcionales de forma independiente.

---

## Fase 5: Historia de Usuario 3 — Consultar la normativa específica de una UPL (Prioridad: P3)

**Goal**: filtrar estrictamente los resultados de `consultar_normativa` a los artículos aplicables a una UPL (por clasificación de suelo `parte` o mención explícita en el chunk), sin ambigüedad.

**Prueba independiente**: consultar con `upl=UPL17` y un tema, y verificar que solo se devuelven artículos aplicables a esa UPL (por clasificación de suelo o mención explícita), con cita literal verificable contra el corpus — spec.md:54

### Tests para Historia de Usuario 3 (escribirlos PRIMERO para que fallen antes de implementar)

- [ ] T024 [P] [US3] Test de filtro UPL estricto: `upl=UPL17` → SOLO artículos de `parte` aplicable o con `upls_mencionadas`; validación `^UPL\d{2}$` (`UPL99` rechazado) — spec.md:58, spec.md:60, spec.md:80

### Implementación para Historia de Usuario 3

- [ ] T025 [US3] Implementar el parámetro `upl` opcional en `consultar_normativa`: filtro estricto por metadatos del chunk en `recuperar` (`PARTES_POR_UPL`: UPL urbana → `["urbano","general"]`, UPL01 Sumapáz → `["rural","general"]`, `general` siempre aplicable; o mención explícita) — spec.md:58, spec.md:80, plan.md:374-379

**Checkpoint**: las tres historias de usuario funcionales de forma independiente.

---

## Fase 6: Polish y transversal

**Propósito**: pruebas transversales, documentación final, gate y verificación de la checklist que afectan a múltiples historias

- [ ] T026 Crear `specs/002-rag-normativo-upl/quickstart.md` de F2 (prerrequisitos con `ollama pull bge-m3` + `ollama pull qwen3:8b`, ingesta `python -m app.ingesta.corpus` con verificación de 608 artículos, ejecución del servidor, escenarios de validación y tabla SC-001 a SC-006) — plan.md:554-565
- [ ] T027 [P] Actualizar `README.md` raíz (6 tools expuestas, requisito Ollama, tabla de variables de entorno, estructura con `app/ingesta/` y providers nuevos, comando de ingesta) — plan.md:566-568
- [ ] T028 [P] Contract tests de la taxonomía extendida en `tests/contract/test_errores_f2.py`: `LOTE_SIN_UPL`, `CORPUS_NO_INGESTADO`, `OLLAMA_NO_DISPONIBLE`; `sin_resultados` NO es un error — data-model.md:219-249
- [ ] T029 [P] Contract tests de validación FR-013 en `tests/contract/test_validacion_f2.py`: consulta vacía o >500 caracteres, `upl` mal formada o inexistente (`UPL99`), `top_k` fuera de 1–6, `get_upl` con cero o más de un criterio → `PARAMETROS_INVALIDOS` sin llamar a las fuentes — data-model.md:253-270, spec.md:91
- [ ] T030 [P] Contract tests de trazabilidad en `tests/contract/test_trazabilidad_f2.py`: los 5 campos (`source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp`) en `get_upl` y `consultar_normativa`; nunca mezclar vigencias (FR-014) — spec.md:84, spec.md:92, data-model.md:176-197
- [ ] T031 Ejecutar `.specify/scripts/bash/check-prerequisites.sh --json` → PASS con `plan.md`, `research.md`, `data-model.md`, `contracts/` y `quickstart.md` — plan.md:569-571, plan.md:599
- [ ] T032 Completar la checklist `checklists/requirements.md` 18/18 (CHK001–CHK018) y verificación cruzada spec ↔ plan ↔ contratos ↔ data-model — plan.md:572-573, plan.md:603
- [ ] T033 [US1] Tests unitarios de ingesta en `tests/contract/test_ingesta_f2.py`: parseo de artículos, chunking boundary-aware, indexación, re-indexación idempotente (2 ejecuciones → 608) y hash SHA-256 del corpus — plan.md:505-512
- [ ] T034 Ejecución completa de pytest: 33 tests de F1 (no-regresión) + ~15–20 tests nuevos de F2, sin red real ni Ollama en vivo — plan.md:538-540, plan.md:600

---

## Dependencias y orden de ejecución

### Dependencias por fase

- **Setup (Fase 1)**: sin dependencias — puede comenzar de inmediato.
- **Foundational (Fase 2)**: depende de Setup — BLOQUEA todas las historias.
- **Historias de usuario (Fases 3-5)**: dependen de Foundational; además, US2 (T023) reutiliza el provider UPL (T012) y el resolver de lote de F1; US3 (T025) extiende `consultar_normativa` de US1 (T018) y el filtro de metadatos del provider normativa (T013), por lo que dependen de esas tareas y NO pueden comenzar hasta que aterricen. El orden MVP-first secuencial (P1 → P2 → P3) es el previsto; no hay paralelismo real entre historias.
- **Polish (Fase 6)**: depende de las historias deseadas completas.

### Dentro de cada historia

- Los contract tests se escriben PRIMERO y deben fallar antes de implementar.
- Validación y manejo de errores antes de la integración completa de la tool.
- La historia se completa antes de pasar a la siguiente prioridad.

### Oportunidades de paralelismo

- La ingesta es estrictamente secuencial: T009 → T010 → T011 (mismo módulo `app/ingesta/corpus.py`).
- T007 (`arcgis_utils`) precede a T008 (refactor de `arcgis.py`) y a T012 (`upl.py`); las tareas [P] restantes de Setup y Foundational tocan archivos distintos y pueden ejecutarse en paralelo.
- T015 y T016 (US1) son contract tests de la MISMA tool (`consultar_normativa`): van en el mismo archivo `tests/contract/test_consultar_normativa.py` y se ejecutan en secuencia, no en paralelo.
- T023 (US2) depende del provider UPL (T012) y del resolver de F1; T025 (US3) depende de US1 (T018) y del filtro del provider normativa (T013): dependencia real entre historias, NO en paralelo.
- Los contract tests [P] de cada historia pueden ejecutarse en paralelo.

---

## Estrategia de implementación

### MVP primero (solo Historia de Usuario 1)

1. Completar Fase 1 (Setup).
2. Completar Fase 2 (Foundational) — CRÍTICO, bloquea todo.
3. Completar Fase 3 (Historia de Usuario 1).
4. **DETENERSE y VALIDAR**: probar la Historia de Usuario 1 de forma independiente (SC-001: < 15 s, SC-002: cita literal verificable, SC-003: abstención explícita).
5. Continuar con US2 y US3 (entrega incremental).

### Entrega incremental

1. Setup + Foundational → fundación lista.
2. Agregar Historia de Usuario 1 → probar independientemente → MVP.
3. Agregar Historia de Usuario 2 → probar independientemente.
4. Agregar Historia de Usuario 3 → probar independientemente.
5. Cada historia agrega valor sin romper las anteriores.

---

## Notas

- [P] = archivos distintos, sin dependencias.
- [Story] = historia de usuario para trazabilidad de la tarea.
- Cada historia es completable y comprobable de forma independiente.
- Verificar que los tests fallen antes de implementar.
- Commit en cada hito ratificado (constitución, Flujo de desarrollo).
- Evitar tareas vagas, conflictos de archivos compartidos y dependencias entre historias que rompan la independencia.
- El corpus parseado (`data/corpus/`) se versiona en git; solo el índice (`.data/chroma`) queda gitignored (plan.md:203-205, FR-009).
