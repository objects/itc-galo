# Tasks: Enriquecimiento del Informe de Factibilidad con 5 Nuevas Fuentes ArcGIS

**Input**: Diseños de `/specs/006-enriquecimiento-fuentes-arcgis/` (plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md)

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: pytest — contract tests (`tests/contract/`) y smoke tests (`tests/smoke/`).

**Organization**: Las tareas se agrupan por fase para implementación secuencial.

## Formato: `T### [P?] [Story] Descripción — Cita`

- **[P]**: Puede ejecutarse en paralelo (archivos distintos, sin dependencias).
- **[Story]**: Historia de usuario a la que pertenece la tarea.
- **Cita**: referencia a `spec.md`, `data-model.md`, `contracts/`, `research.md`, `quickstart.md` o `plan.md`.

---

## Fase 1: Setup (Verificación de no-cambio)

- [x] T001 Verificar que F6 no requiere cambios de infraestructura: `pyproject.toml` sin dependencias nuevas, `.env.example` sin variables nuevas, `app/errores.py` sin códigos nuevos — plan.md:constraints, spec.md:Assumptions

---

## Fase 2: Modelos (app/models.py)

- [x] T002 Definir `RiesgoGeotecnicos` en `app/models.py` con los 5 campos: `amenaza_movimientos`, `geologia`, `respuesta_sismica`, `zonificacion_geotecnica` (str | None) y `nivel_amenaza` (Literal["alto", "medio", "bajo", "desconocido"] | None) — data-model.md:10-18, spec.md:FR-001
- [x] T003 [P] Definir `ContextoSocioeconomico` en `app/models.py` con los 4 campos: `estrato` (int | None), `uso_predominante` (str | None), `altura_media` (float | None), `mediana_avaluo` (float | None) — data-model.md:22-28, spec.md:FR-002
- [x] T004 [P] Definir `EntornoRegulatorio` en `app/models.py` con los 3 campos: `licencias_encontradas` (int | None), `zona_plusvalia` (bool | None), `nombre_plan_plusvalia` (str | None) — data-model.md:32-37, spec.md:FR-003
- [x] T005 [P] Definir `PatrimonioCultural` en `app/models.py` con los 3 campos: `bic_cercano` (bool | None), `nombre_bic` (str | None), `zona_arqueologica` (bool | None) — data-model.md:41-46, spec.md:FR-004
- [x] T006 [P] Definir `AccesoMovilidad` en `app/models.py` con los 4 campos: `estaciones_transmilenio` (int | None), `paraderos_sitp` (int | None), `estaciones_metro` (int | None), `estacion_cercana` (str | None) — data-model.md:50-57, spec.md:FR-005
- [x] T007 Definir los 5 wrappers de bloque (`BloqueRiesgosGeotecnicos`, `BloqueContextoSocioeconomico`, `BloqueEntornoRegulatorio`, `BloquePatrimonioCultural`, `BloqueAccesoMovilidad`) con el patrón `{estado, dato, interpretation, source_trace}` — data-model.md:60-85, spec.md:FR-006
- [x] T008 Extender `InformeFactibilidad` con los 5 campos nuevos: `geotechnical_risks`, `socioeconomic_context`, `regulatory_environment`, `cultural_heritage`, `transit_access` — data-model.md:87-97, spec.md:FR-006

**Checkpoint**: Modelos definidos — el provider puede implementarse.

---

## Fase 3: Provider ArcGIS (app/providers/arcgis.py)

- [x] T009 Añadir las 15 claves nuevas a `VIGENCIAS_DEFAULT`, `_NOMBRES_CANONICOS`, `_URLS_CANONICOS` y `_CAPAS_CANONICOS` en `app/providers/arcgis.py` — research.md:H1-H5, data-model.md:110-145
- [x] T010 Implementar `consultar_riesgos_geotecnicos(lng, lat)` en `ArcGISProvider`: consulta 4 capas de `emergencias/gestionriesgos` [2],[5],[7],[8] en paralelo con `return_exceptions=True`, retorna `tuple[RiesgoGeotecnicos, SourceTrace]` — spec.md:FR-001, research.md:H1
- [x] T011 [P] Implementar `consultar_contexto_socioeconomico(lng, lat)` en `ArcGISProvider`: consulta 4 capas (estratificacion [1], usopredominante [0], alturamedia [0], medianaavaluo [0]) en paralelo, retorna `tuple[ContextoSocioeconomico, SourceTrace]` — spec.md:FR-002, research.md:H2
- [x] T012 [P] Implementar `consultar_entorno_regulatorio(lng, lat)` en `ArcGISProvider`: consulta 2 capas (licenciasconstruccion [3], plusvalia [1]) en paralelo, retorna `tuple[EntornoRegulatorio, SourceTrace]` — spec.md:FR-003, research.md:H3
- [x] T013 [P] Implementar `consultar_patrimonio_cultural(lng, lat)` en `ArcGISProvider`: consulta 2 capas (bienesinterescultural [1], planarqueologico [9]) en paralelo, retorna `tuple[PatrimonioCultural, SourceTrace]` — spec.md:FR-004, research.md:H4
- [x] T014 [P] Implementar `consultar_acceso_movilidad(lng, lat)` en `ArcGISProvider`: consulta 3 capas con radio (transmilenio [1] 800 m, sitp [5] 500 m, metro [0] 800 m) usando `_consultar_radio`, retorna `tuple[AccesoMovilidad, SourceTrace]` — spec.md:FR-005, research.md:H5
- [x] T015 Implementar `_inferir_nivel_amenaza(amenaza)` como función auxiliar pura: clasificación por palabras clave (`alto`, `medio`, `bajo`, `desconocido`) — spec.md:FR-001, data-model.md:17

**Checkpoint**: Provider con 5 métodos nuevos — la orquestación puede integrarlos.

---

## Fase 4: Orquestación (app/main.py)

- [x] T016 Añadir la segunda ronda de consultas paralelas en `get_feasibility_report`: 5 tareas (`consultar_riesgos_geotecnicos`, `consultar_contexto_socioeconomico`, `consultar_entorno_regulatorio`, `consultar_patrimonio_cultural`, `consultar_acceso_movilidad`) con `asyncio.gather(return_exceptions=True)` — plan.md:Phase 3, spec.md:FR-007
- [x] T017 Implementar la construcción del bloque `geotechnical_risks` en el orquestador: patrón `{estado, dato, interpretation, source_trace}`, degradación por excepción (`isinstance(r, BaseException)`) → `no_encontrado` + warning `BLOQUE_DEGRADADO` — spec.md:FR-006, FR-008, FR-015
- [x] T018 [P] Implementar la construcción del bloque `socioeconomic_context` en el orquestador — spec.md:FR-006, FR-008
- [x] T019 [P] Implementar la construcción del bloque `regulatory_environment` en el orquestador — spec.md:FR-006, FR-008
- [x] T020 [P] Implementar la construcción del bloque `cultural_heritage` en el orquestador — spec.md:FR-006, FR-008
- [x] T021 [P] Implementar la construcción del bloque `transit_access` en el orquestador — spec.md:FR-006, FR-008
- [x] T022 Integrar los 5 bloques en el dict de retorno de `get_feasibility_report` y en `BloquesEvaluables` del scoring — data-model.md:87-97, spec.md:FR-006

**Checkpoint**: Los 5 bloques se entregan en el reporte — el scoring puede extenderse.

---

## Fase 5: Scoring (app/scoring.py)

- [x] T023 Extender `BloquesEvaluables` con los 5 campos nuevos y actualizar `BLOQUES_EVALUABLES` a 11 entradas — data-model.md:100-110, spec.md:FR-019
- [x] T024 Añadir 2 reglas positivas (`r_contexto_socio` +5, `r_acceso_movilidad` +5) y 2 negativas (`r_riesgo_geotec_alto` −10, `r_patrimonio_cultural` −10) en `_reglas_positivas` y `_reglas_negativas` — spec.md:FR-011, data-model.md:115-130
- [x] T025 Actualizar `_confidence_por_cobertura` y `_contar_bloques_disponibles` para 11 bloques: high ≥ 9, medium 5–8, low ≤ 4 — spec.md:FR-019, data-model.md:132-140

**Checkpoint**: Scoring extendido con determinismo preservado (SC-003).

---

## Fase 6: Tests

- [x] T026 Extender `tests/conftest.py` con fixtures F6: payloads de las 15 capas nuevas (mockeados) — plan.md:testing
- [x] T027 Extender `tests/contract/test_get_feasibility_report.py` con tests de los 5 bloques nuevos: shape completo, estados, degradación por excepción — spec.md:FR-006, FR-008
- [x] T028 Extender `tests/contract/test_scoring.py` con tests de las 4 reglas nuevas: determinismo, reglas positivas/negativas, confidence con 11 bloques — spec.md:FR-011, FR-019
- [x] T029 Extender `tests/contract/test_trazabilidad_f3.py` con trazabilidad de los 5 bloques nuevos — spec.md:FR-010
- [x] T030 Ejecutar pytest completo: no-regresión F1/F2/F3/F4/F5 + tests F6 — plan.md:testing

---

## Dependencias y orden de ejecución

### Dependencias por fase

- **Setup (Fase 1)**: sin dependencias — puede comenzar de inmediato.
- **Modelos (Fase 2)**: depende de Setup. BLOQUEA Provider y Orquestación.
- **Provider (Fase 3)**: depende de Modelos. BLOQUEA Orquestación.
- **Orquestación (Fase 4)**: depende de Provider. BLOQUEA Scoring.
- **Scoring (Fase 5)**: depende de Orquestación.
- **Tests (Fase 6)**: depende de todas las fases anteriores.

### Oportunidades de paralelismo

- T003, T004, T005, T006 son modelos independientes → paralelo.
- T011, T012, T013, T014 son métodos del provider independientes → paralelo.
- T018, T019, T020, T021 son bloques del orquestador independientes → paralelo.
