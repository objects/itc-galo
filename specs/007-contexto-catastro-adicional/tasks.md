# Tasks: Contexto Catastral Adicional del Lote

**Input**: Diseños de `/specs/007-contexto-catastro-adicional/` (plan.md, spec.md, contracts/, quickstart.md)

**Prerequisites**: plan.md, spec.md, contracts/, quickstart.md

**Tests**: pytest — contract tests (`tests/contract/`) y smoke tests (`tests/smoke/`).

**Organization**: Las tareas se agrupan por fase para implementación secuencial.

## Formato: `T### [P?] [Story] Descripción — Cita`

- **[P]**: Puede ejecutarse en paralelo (archivos distintos, sin dependencias).
- **[Story]**: Historia de usuario a la que pertenece la tarea.
- **Cita**: referencia a `spec.md`, `contracts/`, `quickstart.md` o `plan.md`.

---

## Fase 1: Modelos (app/models.py)

- [x] T001 Definir `ContextoCatastro` en `app/models.py` con los 5 campos: `construccion` (dict | None), `manzana` (dict | None), `densidad_predial` (dict | None), `variacion_area` (dict | None), `sector_catastral` (str | None) — spec.md:FR-003, contracts/contexto-catastro.md
- [x] T002 Definir `BloqueCatastroData` en `app/models.py` con el patrón `{estado, dato, interpretation, source_trace}` — spec.md:FR-004, contracts/contexto-catastro.md
- [x] T003 Añadir campo `catastro_data: BloqueCatastroData` a `InformeFactibilidad` en `app/models.py` — spec.md:FR-008

**Checkpoint**: Modelos definidos — el provider puede implementarse.

---

## Fase 2: Provider ArcGIS (app/providers/arcgis.py)

- [x] T004 Añadir 5 configs de capas nuevas a `VIGENCIAS_DEFAULT`, `_NOMBRES_CANONICOS`, `_URLS_CANONICOS` y `_CAPAS_CANONICOS`: `construccion` [0], `manzana_catastro` [0], `densidad_predial` [0], `variacion_area` [1], `sector_catastral` [0] — plan.md:Phase 2, spec.md:FR-002, FR-003
- [x] T005 Implementar `consultar_contexto_catastro(lng, lat)` en `ArcGISProvider`: consulta 5 capas en paralelo con `asyncio.gather(return_exceptions=True)`, retorna `tuple[ContextoCatastro, SourceTrace]` — spec.md:FR-001, FR-002, SC-001

**Checkpoint**: Provider con el método nuevo — la orquestación puede integrarlo.

---

## Fase 3: Orquestación (app/main.py)

- [x] T006 Integrar `consultar_contexto_catastro` en la segunda ronda de consultas paralelas de `get_feasibility_report` (junto con los 5 bloques de F6) — plan.md:Phase 3, spec.md:FR-008
- [x] T007 Integrar `consultar_contexto_catastro` en `get_lot_summary_by_chip` con degradación independiente — spec.md:FR-010
- [x] T008 Actualizar `app/scoring.py`: añadir `catastro_data` a `BLOQUES_EVALUABLES`, `BloquesEvaluables`, `_bloques_con_estado`, `_contar_bloques_disponibles` y `_reasons_datos_faltantes` (12 bloques evaluables total) — plan.md:Phase 4, spec.md:SC-002

**Checkpoint**: Orquestación completa — los tests pueden validarlo.

---

## Fase 4: Tests

- [x] T009 Actualizar tests: conftest.py (MockTransport para las 5 capas), _f3_shared.py (constantes), test_scoring.py (12 bloques evaluables), test_quickstart.py (16 bloques en informe) — spec.md:FR-008, SC-002
- [x] T010 Verificar suite completa: 263 tests passing, 0 failed — plan.md:constraints

**Checkpoint**: Suite verificada — la feature está lista para commit.
