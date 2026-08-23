# Tasks: Parámetros Urbanísticos del Lote

**Input**: Diseños de `/specs/008-parametros-urbanisticos-lote/` (plan.md, spec.md, research.md, data-model.md, contracts/urbanistic-parameters.md, quickstart.md)

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/urbanistic-parameters.md, quickstart.md

**Tests**: pytest — contract tests (`tests/contract/`) y smoke tests (`tests/smoke/`).

**Organization**: Las tareas se agrupan por fase para implementación secuencial.

## Formato: `T### [P?] [Story] Descripción — Cita`

- **[P]**: Puede ejecutarse en paralelo (archivos distintos, sin dependencias).
- **[Story]**: Historia de usuario a la que pertenece la tarea.
- **Cita**: referencia a `spec.md`, `data-model.md`, `contracts/`, `research.md`, `quickstart.md` o `plan.md`.

---

## Fase 1: Setup (Verificación de no-cambio)

- [x] T001 Verificar que F8 no requiere cambios de infraestructura: `pyproject.toml` sin dependencias nuevas, `.env.example` sin variables nuevas, `app/errores.py` sin códigos nuevos — plan.md:constraints, spec.md:Assumptions

---

## Fase 2: Modelos (app/models.py)

- [x] T002 Definir `TratamientoUrbanistico` en `app/models.py` con los 2 campos: `denominacion` (str), `codigo_capa` (str | None) — data-model.md:9-16, spec.md:FR-001, contracts/urbanistic-parameters.md
- [x] T003 [P] Definir `ParametrosEdificabilidad` en `app/models.py` con los 3 campos: `cos` (float | None), `cus` (float | None), `altura_maxima_m` (float | None) — data-model.md:22-30, spec.md:FR-001, contracts/urbanistic-parameters.md
- [x] T004 [P] Definir `RetirosLote` en `app/models.py` con los 3 campos: `frontal_m` (float | None), `laterales_m` (float | None), `posteriores_m` (float | None) — data-model.md:36-44, spec.md:FR-001, contracts/urbanistic-parameters.md
- [x] T005 [P] Definir `EstacionamientosRequeridos` en `app/models.py` con los 2 campos: `requeridos` (int | None), `criterio` (str | None) — data-model.md:50-57, spec.md:FR-001, contracts/urbanistic-parameters.md
- [x] T006 Definir `ParametrosUrbanisticos` en `app/models.py` como contenedor con los 4 campos: `tratamiento` (TratamientoUrbanistico | None), `edificabilidad` (ParametrosEdificabilidad | None), `retiros` (RetirosLote | None), `estacionamientos` (EstacionamientosRequeridos | None) — data-model.md:63-74, spec.md:FR-001
- [x] T007 Definir `BloqueParametrosUrbanisticos` en `app/models.py` con el patrón `{estado, dato, interpretation, source_trace}` — data-model.md:79-87, spec.md:FR-007, contracts/urbanistic-parameters.md
- [x] T008 Añadir campo `urbanistic_parameters: BloqueParametrosUrbanisticos` a `InformeFactibilidad` en `app/models.py` — spec.md:FR-001, FR-013

**Checkpoint**: Modelos definidos — el provider puede implementarse.

---

## Fase 3: Provider SDP (app/providers/sdp.py)

- [x] T009 Crear `app/providers/sdp.py` con `SDPProvider`: constante `SDP_BASE_URL`, `httpx.AsyncClient` con timeout configurable (default 10s), método `aclose()` — spec.md:FR-017, FR-019, FR-022, research.md:D1
- [x] T010 Implementar `consultar_tratamiento(lng, lat)` en `SDPProvider`: consulta layer 2 del SINUPOT (`sinu.sdp.gov.co/serverp/rest/services/POT555/NORMA_URBANÍSTICA_Y_OT/MapServer`) con `inSR=4326`, `outSR=4686`, retorna `tuple[TratamientoUrbanistico, SourceTrace]` o lanza excepción tipada — spec.md:FR-002, FR-004, FR-005, research.md:D1
- [x] T011 Implementar `consultar_edificabilidad(lng, lat)` en `SDPProvider`: consulta layer 14 del SINUPOT para COS/CUS/altura por tratamiento, retorna `tuple[ParametrosEdificabilidad | None, SourceTrace]` — spec.md:FR-006, FR-021, research.md:D1

**Checkpoint**: Provider con los métodos de consulta — la orquestación puede integrarlo.

---

## Fase 4: Orquestación (app/main.py)

- [x] T012 Inyectar `SDPProvider` en `ServidorLotes`: añadir `provider_sdp` al `__init__`, `aclose()` y `_construir_servidor_lotes()` — plan.md:Phase 3, spec.md:FR-017
- [x] T013 Implementar helper `_construir_prompt_parametros_urbanisticos(tratamiento, upl, localidad)` en `app/main.py`: genera el prompt estructurado para el RAG con el nombre del tratamiento y la UPL — contracts/urbanistic-parameters.md:Consulta RAG, research.md:D6
- [x] T014 Implementar helper `_parsear_parametros_rag(respuesta_rag)` en `app/main.py`: parsing regex determinista de COS, CUS, altura, retiros frontales/laterales/posteriores y estacionamientos desde el texto del LLM — contracts/urbanistic-parameters.md:Parsing regex, research.md:D6
- [x] T015 Integrar la tercera ronda de consultas en `get_feasibility_report`: SDP `consultar_tratamiento` → (si OK) RAG `consultar` con prompt de parámetros → construcción del bloque `urbanistic_parameters` con degradación independiente por fuente — plan.md:Phase 3, spec.md:FR-008, FR-009
- [x] T016 Implementar la construcción del bloque `urbanistic_parameters` en el orquestador: patrón `{estado, dato, interpretation, source_trace}`, degradación por excepción → `no_encontrado` + warning `BLOQUE_DEGRADADO` o `BLOQUE_SIN_DATO` — spec.md:FR-007, FR-008, FR-016, contracts/urbanistic-parameters.md:Estados del bloque
- [x] T017 Integrar el bloque `urbanistic_parameters` en el dict de retorno de `get_feasibility_report` — spec.md:FR-001, FR-013
- [x] T018 Integrar el bloque `urbanistic_parameters` en `get_lot_summary_by_chip` con degradación independiente — spec.md:FR-020

**Checkpoint**: Bloque `urbanistic_parameters` entregado en el reporte y resumen — el scoring puede extenderse.

---

## Fase 5: Scoring (app/scoring.py)

- [x] T019 Añadir las 3 constantes nuevas en `app/scoring.py`: `PUNTOS_PARAMETROS_URBANISTICOS = 10`, `PUNTOS_ESTACIONAMIENTOS = 5`, `PENALIZACION_CONSERVACION = 15` — data-model.md:114-127, spec.md:FR-011
- [x] T020 Extender `BloquesEvaluables` con el campo `urbanistic_parameters: BloqueParametrosUrbanisticos` y actualizar `BLOQUES_EVALUABLES` a 13 entradas — data-model.md:93-100, spec.md:FR-012
- [x] T021 Añadir 2 reglas positivas (`r_parametros_urbanisticos` +10, `r_estacionamientos_calculados` +5) en `_reglas_positivas` — spec.md:FR-011, data-model.md:116-119, contracts/urbanistic-parameters.md:Scoring extension
- [x] T022 Añadir 1 regla negativa (`r_tratamiento_conservacion` −15) en `_reglas_negativas` — spec.md:FR-011, data-model.md:123-127, contracts/urbanistic-parameters.md:Scoring extension
- [x] T023 Actualizar `_bloques_con_estado`, `_contar_bloques_disponibles`, `_confidence_por_cobertura` y `_reasons_datos_faltantes` para 13 bloques evaluables: high ≥ 10, medium 5–9, low ≤ 4 — data-model.md:102-108, spec.md:FR-012

**Checkpoint**: Scoring extendido con determinismo preservado (SC-003).

---

## Fase 6: Tests

- [x] T024 Crear `tests/contract/test_urbanistic_parameters.py` con tests del bloque `urbanistic_parameters`: shape completo con MockTransport (SDP layer 2), estados `disponible`/`no_encontrado`, interpretaciones deterministas, source_trace con 5 campos — spec.md:US1, FR-007, FR-010, FR-014
- [x] T025 [P] Añadir tests de degradación independiente: SDP falla → bloque `no_encontrado` + warning `BLOQUE_DEGRADADO`; SDP sin features → warning `BLOQUE_SIN_DATO`; RAG falla → campos numéricos `None` pero tratamiento OK — spec.md:US1, FR-008, FR-009, FR-016, quickstart.md:Degradación
- [x] T026 [P] Añadir tests de scoring: regla `r_parametros_urbanisticos` (+10), regla `r_estacionamientos_calculados` (+5), regla `r_tratamiento_conservacion` (−15), determinismo SC-003, confidence con 13 bloques — spec.md:US2, FR-011, FR-012, quickstart.md:Scoring
- [x] T027 [P] Añadir tests de parsing regex: COS, CUS, altura, retiros (frontal/laterales/posterior) y estacionamientos extraídos correctamente; campos no matcheados quedan `None` — contracts/urbanistic-parameters.md:Parsing regex
- [x] T028 [P] Añadir tests de no-regresión: las 7 tools existentes mantienen su contrato sin cambios, smoke tests pasan, bloque `urbanistic_parameters` incluido en `get_lot_summary_by_chip` — spec.md:FR-013, FR-020, SC-005
- [x] T029 Ejecutar pytest completo: verificar 0 failed, todos los tests F1/F2/F3/F4/F6/F7 pasan + tests F8 — plan.md:constraints, SC-005

**Checkpoint**: Suite verificada — la feature está lista para commit.

---

## Dependencias y orden de ejecución

### Dependencias por fase

- **Setup (Fase 1)**: sin dependencias — puede comenzar de inmediato.
- **Modelos (Fase 2)**: depende de Setup. BLOQUEA Provider y Orquestación.
- **Provider (Fase 3)**: depende de Modelos. BLOQUEA Orquestación.
- **Orquestación (Fase 4)**: depende de Provider. BLOQUEA Scoring.
- **Scoring (Fase 5)**: depende de Orquestación (necesita `BloqueParametrosUrbanisticos`).
- **Tests (Fase 6)**: depende de todas las fases anteriores.

### Oportunidades de paralelismo

- T003, T004, T005 son modelos independientes → paralelo.
- T010, T011 son métodos del provider independientes → paralelo.
- T025, T026, T027, T028 son archivos/grupos de tests independientes → paralelo.
