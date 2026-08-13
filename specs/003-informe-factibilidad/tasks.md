# Tasks: Informe de factibilidad orquestado (`get_feasibility_report`)

**Input**: Diseños de `/specs/003-informe-factibilidad/` (plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md)

**Prerequisites**: plan.md (obligatorio), spec.md (obligatorio para historias de usuario), research.md, data-model.md, contracts/, quickstart.md

**Tests**: pytest — smoke test de arranque (`tests/smoke`) y contract tests (`tests/contract`) según plan.md:48-51; las historias incluyen sus contract tests (escribirlos primero para que fallen antes de implementar, patrón F1/F2).

**Organization**: Las tareas se agrupan por historia de usuario para permitir implementación y pruebas independientes de cada historia (constitución v1.0.0, Principio V — MVP first).

## Formato: `T### [P?] [Story] Descripción — Cita`

- **[P]**: Puede ejecutarse en paralelo (archivos distintos, sin dependencias).
- **[Story]**: Historia de usuario a la que pertenece la tarea (US1, US2, US3).
- **Cita**: referencia a `spec.md` (FR/SC), `data-model.md`, `contracts/`, `research.md`, `quickstart.md` o `plan.md` con línea, p. ej. `spec.md:83`.

## Convenciones de rutas

- Proyecto único: `app/`, `tests/` en la raíz del repositorio (plan.md:132-140).
- Estructura: `app/main.py` (FastMCP, 7 tools tras F3), `app/models.py` (pydantic), `app/scoring.py` (nuevo, función pura del score), `app/errores.py` (taxonomía, SIN CAMBIOS), `app/providers/` (un provider por fuente; se modifican `arcgis.py` con 2 métodos nuevos; `upl.py`, `normativa.py` y `mapas_bogota.py` SIN CAMBIOS), `tests/contract/` y `tests/smoke/` (plan.md:112-140).
- F3 NO añade dependencias ni variables de entorno nuevas (plan.md:39-46): sin cambios en `pyproject.toml`, `.env.example` ni `.gitignore`.

---

## Fase 1: Setup (Infraestructura compartida)

**Propósito**: verificar que el stack existente cubre F3 sin dependencias, variables de entorno ni códigos de error nuevos (la capa Predio es ArcGIS REST de `httpx`, el RAG reutiliza `chromadb`/`ollama` de F2 y la taxonomía de errores los 10 códigos de F1/F2)

- [x] T001 Verificar y documentar que F3 no requiere cambios de infraestructura: `pyproject.toml` sin dependencias nuevas, `.env.example` sin variables nuevas (`MAPAS_BOGOTA_APIKEY` ya existe y NO se usa para el bloque económico — research H7), `app/errores.py` sin códigos nuevos (se reutilizan los 10 existentes y `_error_de_fuente`) — plan.md:39-46, plan.md:63-68, research.md:187-198, plan.md:122

---

## Fase 2: Foundational (Prerrequisitos bloqueantes)

**Propósito**: infraestructura central (modelos del reporte, métodos nuevos del provider ArcGIS, scoring puro y fixtures de test) que DEBE estar completa antes de que cualquier historia de usuario pueda implementarse

**⚠️ CRITICAL**: ningún trabajo de historias de usuario puede comenzar hasta que esta fase esté completa

- [x] T002 Definir modelos pydantic v2 en `app/models.py`: `UsoEconomico` (codigo, descripcion, area_uso); **reactivar** `DestinoEconomico` con la nueva fuente (estado, codigo_destino, descripcion_destino, uso, area_uso, usos, area_terreno, area_construccion, direccion, barrio, vigencia, source_trace); `FeasibilityScore` (score, confidence, reasons, rules_applied); modelos de bloque (`IdentidadLote`, `ContextoAdministrativo`, `BloqueReservaVial`, `BloqueValorReferencia`, `BloqueObrasPublicas`, `BloqueDestinoEconomico`, `EvidenciaNormativa`, `Warning`) e `InformeFactibilidad` (entidad raíz de 10 bloques) — data-model.md:71-152, spec.md:98-105, plan.md:117-119
- [x] T003 [P] Añadir al provider `app/providers/arcgis.py` los dominios versionados `D_PreDestino` (28 códigos) y `D_UsoTUso` (85 códigos) como constantes para traducir `PRECDESTIN`/`PRECUSO` a descripciones sin consultar la metadata en runtime (patrón del mapeo `NOMBRE → localidad` de F2) — research.md:54-92, plan.md:124-127
- [x] T004 [P] Implementar `consultar_destino_economico(chip=None, codigo_catastral=None)` en `app/providers/arcgis.py`: consulta a la capa tabular Predio `catastro/lote/MapServer/3` con `f=pjson` (NUNCA `f=geojson` → 400), `returnGeometry=false`, `where=PRECHIP='<chip>'` o `where=BARMANPRE='<codigo_catastral>'`; devuelve `DestinoEconomico` con selección por mayor `PREAUSO` (fila dominante → `codigo_destino`/`descripcion_destino`/`uso`/`area_uso`; las demás → `usos`), `data_vigencia = PREVACTUAL` del registro y `estado=no_encontrado` si no hay filas (sin inventar dato) — research.md:201-234, data-model.md:73-98, data-model.md:182-204
- [x] T005 [P] Implementar `consultar_obras_publicas_radio(lng, lat, radio_m=500)` en `app/providers/arcgis.py`: consulta a `gestionpublica/obraspublicas/0` con `esriSpatialRelIntersects` + `distance=500&units=esriSRUnit_Meter` sobre el centroide del lote (la capa es multipunto; la consulta puntual de F1 no cumple FR-004); SIN modificar `_consultar_obras_publicas` de F1 — research.md:158-174, research.md:365-413, spec.md:86
- [x] T006 [P] Crear `app/scoring.py` con la función pura `calcular_score(bloques) -> FeasibilityScore`: base 50; reglas positivas (UPL +10, localidad +5, market_context disponible +10, economic_context disponible +10, evidencia con ítems +5) y negativas (reserva vial que afecta −15, UPL ausente −5, cada bloque no_encontrado −5, evidencia vacía −5); `clamp(0,100)` entero; `confidence` por cobertura de 6 bloques (high ≥5, medium 3–4, low ≤2); `reasons` fijos con dato interpolado y `source_name`; sin I/O, sin LLM, sin reloj — research.md:272-314, data-model.md:99-113, data-model.md:205-227
- [x] T007 Extender `tests/conftest.py` con fixtures F3 (patrón payload/status de F1/F2): payload de la capa Predio (2 filas del CHIP `AAA0072LRYN`: `PRECDESTIN=04`, `PRECUSO=015`/`096`, `PREAUSO=40453.8`/`3011.3`, `PREVACTUAL=2026`, `BARMANPRE=006101016001`), payload de `obraspublicas/0` con buffer 500 m y `server_lotes_f3` con providers mockeados — plan.md:48-51, quickstart.md:160-171

**Checkpoint**: fundación lista — las historias de usuario pueden comenzar.

---

## Fase 3: Historia de Usuario 1 — Obtener el informe de factibilidad estructural de un lote (Prioridad: P1) 🎯 MVP

**Goal**: emitir el informe de factibilidad de un lote (por CHIP, dirección o coordenadas) en una sola llamada con los bloques `lot_identity`, `administrative_context`, `planning_constraints`, `market_context`, `environment_context`, `economic_context`, `feasibility_score`, `warnings` y `query_timestamp`, cada bloque de datos trazado a su fuente (5 campos).

**Prueba independiente**: invocar `get_feasibility_report` con un CHIP válido y verificar que el reporte devuelve los 10 bloques con cada bloque de datos trazado a su fuente (5 campos de trazabilidad) — spec.md:26

### Tests para Historia de Usuario 1 (escribirlos PRIMERO para que fallen antes de implementar)

- [x] T008 [P] [US1] Contract test de `get_feasibility_report` en `tests/contract/test_get_feasibility_report.py`: shape completo de 10 bloques, patrón `{estado, dato, interpretation, source_trace}` en los bloques temáticos/económicos, ejemplo del contrato con `economic_context` disponible (2 filas, fila dominante por mayor PREAUSO) y `normative_evidence` verificado como BLOQUE de los 10 con su shape (`items`, `consulta`, `consulta_automatica`, `sin_resultados`, `causa`, `source_trace`) — `items` vacío cuando aún no hay RAG/US2 integrado, SIN exigir `consulta_automatica: true` (esa verificación vive en T015, Fase 4/US2) — spec.md:26, contracts/get-feasibility-report.md:233-317, quickstart.md:31-53
- [x] T009 [P] [US1] Contract tests de validación FR-013 en `tests/contract/test_validacion_f3.py`: exactamente un criterio de `{chip, direccion, coordenadas}` (cero o más de uno → `PARAMETROS_INVALIDOS` sin llamar fuentes), `chip` `^[A-Z0-9]{11}$`, `coordenadas` lat ∈ [-90,90]/lon ∈ [-180,180], `consulta` 1–500, `top_k` 1–6 — spec.md:95, contracts/get-feasibility-report.md:83-93, quickstart.md:128-139
- [x] T010 [P] [US1] Contract tests de errores fatales en `tests/contract/test_errores_f3.py`: `LOTE_NO_ENCONTRADO`, `FUERA_DE_COBERTURA`, `DIRECCION_NO_LOCALIZADA`, `CREDENCIAL_FALTANTE` (dirección sin `MAPAS_BOGOTA_APIKEY`), y `FUENTE_5XX` de cualquier fuente (5xx NUNCA degradado a `no_encontrado`) — spec.md:94, contracts/get-feasibility-report.md:320-332, quickstart.md:128-139

### Implementación para Historia de Usuario 1

- [ ] T011 [US1] Registrar tool `get_feasibility_report` en `app/main.py`: 7ª tool vía `mcp.tool()(servidor_lotes.get_feasibility_report)` en `crear_servidor_mcp`, con el JSON Schema del contrato (criterio único + `consulta`/`top_k` opcionales) — plan.md:24-32, plan.md:113-116, contracts/get-feasibility-report.md:35-93
- [ ] T012 [US1] Implementar el pipeline de orquestación en `ServidorLotes.get_feasibility_report`: validar entrada (FR-013) → resolver lote (flujos privados de F1) → UPL capturando `UplNoEncontradaError` como `upl: null` + warning → `planning_constraints`/`market_context` desde `ContextoTematico` de F1 → `environment_context` con `consultar_obras_publicas_radio` (buffer 500 m) → `economic_context` con `consultar_destino_economico` → scoring (T006) → montar los 10 bloques; los 5xx se propagan con `_error_de_fuente` (FR-012) — spec.md:83-87, research.md:365-413, data-model.md:165-204
- [ ] T013 [US1] Implementar `lot_identity`, `administrative_context` (UPL + localidad + `clasificacion_suelo` derivada de `UPL.vocacion`; `upl: null` → `localidad: null` + warning) y los bloques temáticos con interpretaciones de texto fijo por reglas (FR-007, sin LLM), incluyendo el warning `LOTE_SIN_CHIP` cuando `chip: null` (lote por coordenadas) — spec.md:84-86, research.md:137-156, data-model.md:38-60, data-model.md:182-204
- [ ] T014 [US1] Actualizar `tests/smoke/test_main.py` de 6 a 7 tools en el MISMO hito en que se registra `get_feasibility_report` (sin dejar ventana roja) — plan.md:139-140

**Checkpoint**: Historia de Usuario 1 funcional y comprobable de forma independiente (MVP; SC-001: < 10 s sin normativa, SC-002: 100 % de bloques con 5 campos); el bloque `normative_evidence` se valida por shape (`items` vacío sin RAG/US2), sin exigir la consulta automática, que llega en Fase 4 (T015).

---

## Fase 4: Historia de Usuario 2 — Enriquecer el informe con evidencia normativa del POT (Prioridad: P2)

**Goal**: incluir `normative_evidence` con citas literales del Decreto 555/2021, alimentada por consulta automática desde el contexto del lote (UPL + localidad + clasificación de suelo) o por `consulta` explícita del usuario, con degradación por bloque cuando el RAG no está disponible.

**Prueba independiente**: invocar `get_feasibility_report` sin `consulta` sobre un lote con UPL conocida y verificar que `normative_evidence` contiene artículos con cita literal coherentes con el territorio; invocarla con `consulta` explícita y verificar que los resultados responden al tema solicitado — spec.md:41

### Tests para Historia de Usuario 2 (escribirlos PRIMERO para que fallen antes de implementar)

- [x] T015 [P] [US2] Contract tests de `normative_evidence` en `tests/contract/test_normativa_f3.py`: consulta automática (`consulta_automatica: true`, consulta contiene UPL + localidad + clasificación, `upl=<codigo>` pasado a `consultar_normativa`), consulta explícita (`consulta_automatica: false`, `consulta ==` texto del usuario, `top_k` respetado), degradación sin Ollama/corpus (`items: []` + `causa: "OLLAMA_NO_DISPONIBLE"`/`"CORPUS_NO_INGESTADO"` + warning `NORMATIVA_NO_DISPONIBLE`, el resto del reporte completo) y sin resultados (`sin_resultados: true` + `causa: "SIN_RESULTADOS"`) — spec.md:41, spec.md:44-47, contracts/get-feasibility-report.md:96-203, contracts/get-feasibility-report.md:333-343, quickstart.md:70-111

### Implementación para Historia de Usuario 2

- [ ] T016 [US2] Construir la consulta normativa automática desde el contexto del lote en `app/main.py`: `"normas urbanísticas aplicables a la UPL {nombre} ({codigo}), localidad {localidad}, clasificación de suelo {clasificacion}"` con `upl=<codigo>`; respaldo con solo localidad y SIN filtro territorial cuando la UPL no se resolvió (FR-003/FR-008) — research.md:237-270, spec.md:90, data-model.md:61-70
- [ ] T017 [US2] Integrar `consultar_normativa` (reutilizada tal cual de F2, filtro territorial H6) en el pipeline con degradación deliberada: capturar `CorpusNoIngestadoError`/`OllamaNoDisponibleError` → `normative_evidence.items: []` + `causa` + warning `NORMATIVA_NO_DISPONIBLE` (NO error de la tool, FR-009/FR-012; divergencia documentada); `sin_resultados: true` + warning `NORMATIVA_SIN_RESULTADOS` cuando la consulta no produce ítems; el bloque conserva `source_trace` al corpus (Decreto 555/2021, `data_vigencia=2021-12-30`) — spec.md:90-91, spec.md:94, research.md:417-437, contracts/get-feasibility-report.md:333-343

**Checkpoint**: Historias de Usuario 1 y 2 funcionales de forma independiente (SC-004: cita literal verificable; SC-005: reporte completo sin Ollama).

---

## Fase 5: Historia de Usuario 3 — Conocer el alcance del scoring y sus límites (Prioridad: P3)

**Goal**: garantizar que el `feasibility_score` sea heurístico, determinístico y transparente — con `confidence` y `reasons` trazables a los datos reales — y que el reporte exponga sus límites (no confundirlo con un diagnóstico urbanístico formal).

**Prueba independiente**: invocar `get_feasibility_report` dos veces con los mismos datos y verificar que el score, confidence y reasons son idénticos (determinismo); verificar que ninguna razón cita reglas urbanísticas que no provienen de las fuentes consultadas — spec.md:55

### Tests para Historia de Usuario 3 (escribirlos PRIMERO para que fallen antes de implementar)

- [x] T018 [P] [US3] Contract tests de scoring en `tests/contract/test_scoring.py`: determinismo (mismo input → mismo score/confidence/reasons, SC-003), cobertura de bloques (high/medium/low), `confidence: "low"` enumera explícitamente qué datos faltan (US3.2), penalización por reserva vial (−15) reflejada en `reasons` con `source_name`, y verificación de que ninguna razón/interpretation cita reglas urbanísticas ausentes (FR-014) — spec.md:55-61, spec.md:113, data-model.md:205-227, quickstart.md:141-151

### Implementación para Historia de Usuario 3

- [ ] T019 [US3] Ajustar e integrar las reglas del scoring (T006) en el pipeline: aplicar penalizaciones por reserva vial que afecta el lote (de `planning_constraints.dato.afecta_lote`), UPL ausente, bloques `no_encontrado` y evidencia vacía; `confidence` por cobertura de los 6 bloques evaluables; `reasons` enumeran los bloques ausentes cuando `confidence: "low"`; poblar `rules_applied` para auditoría — research.md:272-314, data-model.md:205-227, spec.md:88, spec.md:96
- [ ] T020 [US3] Implementar los `warnings` deterministas y deduplicados en el orquestador: `LOTE_SIN_CHIP`, `UPL_NO_ENCONTRADA`, `LOCALIDAD_NO_DERIVADA`, `BLOQUE_SIN_DATO`, `NORMATIVA_NO_DISPONIBLE`, `NORMATIVA_SIN_RESULTADOS` (una entrada por degradación, código + mensaje) — spec.md:93, data-model.md:182-204, contracts/get-feasibility-report.md:333-343

**Checkpoint**: las tres historias de usuario funcionales de forma independiente (SC-003, SC-006).

---

## Fase 6: Polish y transversal

**Propósito**: pruebas transversales (trazabilidad, no-regresión), documentación final, gate y verificación de la checklist que afectan a múltiples historias

- [x] T021 [P] Contract tests de trazabilidad en `tests/contract/test_trazabilidad_f3.py`: los 5 campos (`source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp`) en cada bloque de datos (`lot_identity`, `administrative_context`, `planning_constraints`, `market_context`, `environment_context`, `economic_context`, `normative_evidence`); `data_vigencia` del bloque económico = `PREVACTUAL` del registro; nunca mezclar vigencias (FR-008/FR-010) — spec.md:92, spec.md:112, data-model.md:238-248, quickstart.md:152-159
- [ ] T022 [P] Actualizar `README.md` raíz: 7 tools expuestas (incluida `get_feasibility_report` con su resumen de bloques), estructura con `app/scoring.py`, nota de que `economic_context` usa la capa Predio de ArcGIS (sin `MAPAS_BOGOTA_APIKEY`) — plan.md:143-146
- [ ] T023 Ejecutar `.specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks` → PASS con `plan.md`, `tasks.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md` y checklists completos — AGENTS.md flujo de trabajo, plan.md:148-163
- [ ] T024 Mantener completada la checklist `checklists/requirements.md` 16/16 (CHK-001 a CHK-016) y verificación cruzada spec ↔ plan ↔ contratos ↔ data-model ↔ tasks (sin regresiones a F1/F2) — plan.md:74-89
- [ ] T025 Ejecución completa de pytest: no-regresión de F1/F2 (tests existentes en `tests/contract/` y `tests/smoke/`) + tests nuevos de F3, sin red real ni Ollama en vivo — plan.md:48-51

---

## Dependencias y orden de ejecución

### Dependencias por fase

- **Setup (Fase 1)**: sin dependencias — puede comenzar de inmediato (T001 es una verificación de no-cambio).
- **Foundational (Fase 2)**: depende de Setup — BLOQUEA todas las historias.
- **Historias de usuario (Fases 3-5)**: dependen de Foundational; además, US1 (T012) usa los modelos (T002), el provider (T004/T005) y el scoring (T006); US2 (T017) integra `consultar_normativa` de F2 y depende de US1 (T012) y de la consulta automática (T016); US3 (T019) depende del scoring (T006) y de los bloques de US1 (T012/T013). El orden MVP-first secuencial (P1 → P2 → P3) es el previsto.
- **Fase 4 (US2)**: depende de Fase 3 (US1) — T017 integra `consultar_normativa` sobre el bloque `normative_evidence` montado en T012/T013; la verificación de la consulta automática (`consulta_automatica: true`, consulta con UPL + localidad + clasificación, `upl=<codigo>`) vive **exclusivamente** en T015 (US2), no en T008 (US1), para no romper la independencia del checkpoint de US1 (MVP sin RAG).
- **Polish (Fase 6)**: depende de las historias deseadas completas.

### Dentro de cada historia

- Los contract tests se escriben PRIMERO y deben fallar antes de implementar.
- Validación y manejo de errores antes de la integración completa de la tool.
- La historia se completa antes de pasar a la siguiente prioridad.

### Oportunidades de paralelismo

- T003, T004, T005 y T006 tocan zonas distintas de `app/providers/arcgis.py`/`app/scoring.py` — T003 (constantes) precede a T004 (uso de las constantes); T004 y T005 son métodos independientes del provider y pueden ir en paralelo; T006 (scoring) es un módulo nuevo e independiente.
- T008, T009 y T010 (US1) son contract tests de archivos distintos (test_get_feasibility_report.py, test_validacion_f3.py, test_errores_f3.py) y pueden ejecutarse en paralelo.
- T015 (US2) y T018 (US3) son contract tests de archivos distintos y pueden ejecutarse en paralelo con los de US1.
- T011 → T012 → T013 → T014 son estrictamente secuenciales (mismo módulo `app/main.py` + smoke).
- T021 y T022 (Polish) tocan archivos distintos (`tests/contract/test_trazabilidad_f3.py`, `README.md`) y pueden ejecutarse en paralelo.

---

## Estrategia de implementación

### MVP primero (solo Historia de Usuario 1)

1. Completar Fase 1 (Setup).
2. Completar Fase 2 (Foundational) — CRÍTICO, bloquea todo.
3. Completar Fase 3 (Historia de Usuario 1).
4. **DETENERSE y VALIDAR**: probar la Historia de Usuario 1 de forma independiente (SC-001: < 10 s sin normativa, SC-002: trazabilidad 5 campos, SC-003: determinismo).
5. Continuar con US2 y US3 (entrega incremental).

### Entrega incremental

1. Setup + Foundational → fundación lista.
2. Agregar Historia de Usuario 1 → probar independientemente → MVP.
3. Agregar Historia de Usuario 2 → probar independientemente.
4. Agregar Historia de Usuario 3 → probar independientemente.
5. Cada historia agrega valor sin romper las anteriores (no-regresión F1/F2).

---

## Notas

- [P] = archivos distintos, sin dependencias.
- [Story] = historia de usuario para trazabilidad de la tarea.
- Cada historia es completable y comprobable de forma independiente.
- Verificar que los tests fallen antes de implementar.
- Commit en cada hito ratificado (constitución, Flujo de desarrollo).
- Evitar tareas vagas, conflictos de archivos compartidos y dependencias entre historias que rompan la independencia.
- El reporte es 100 % determinístico (FR-007): el score y las `interpretation` NUNCA usan LLM; la única salida del RAG es `normative_evidence` (FR-014).
- La capa Predio se consulta con `f=pjson` (NUNCA `f=geojson` → 400; research H1) y su `data_vigencia` es la del registro (`PREVACTUAL`, research H7).
