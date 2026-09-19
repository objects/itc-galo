# Tasks: Catálogo Extensible + Wizard v2

**Input**: Diseños de `/specs/011-catalogo-extensible-wizard-v2/` (plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md)
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/preview.md, contracts/catalog.md, contracts/wizard.md, quickstart.md
**Tests**: pytest — contract tests (`tests/contract/`) y smoke tests (`tests/smoke/`), con `httpx.MockTransport` hermético y `TestClient`.
**Organization**: Las tareas se agrupan por capa (catálogo → wizard backend → wizard frontend → persistencia → pulido). Cada tarea lleva su etiqueta `[USn]`. Sin nuevas deps, sin nueva tool MCP.

## Formato: `T### [P?] [Story] Descripción — Cita`

- **[P]**: Puede ejecutarse en paralelo (archivos distintos, sin dependencias).
- **[Story]**: Historia de usuario a la que pertenece (US1=catálogo, US2=wizard v2, US3=persistencia).
- **Cita**: referencia a `spec.md`, `data-model.md`, `contracts/*`, `research.md`, `quickstart.md` o `plan.md`.

---

## Fase 1: Setup (Verificación de no-cambio + catálogo base)

- [x] T001 Verificar que F11 no requiere infraestructura nueva: `pyproject.toml` sin deps nuevas, `.env.example` sin vars nuevas, `app/errores.py` sin códigos nuevos, 7 tools invariante — plan.md:Technical Context, spec.md:Assumptions, research.md:R-01..R-07
- [x] T002 [P] [US1] Documentar inventario del catálogo actual: listar las 15+ capas ArcGIS de los 23 bloques (Mapa_Referencia 38, UPL 0, F6 5 bloques, F7 5 capas, SDP 2+14, Fase3 3 bloques) con `service_url/layer_id` y nota de extensible sin rediseño — research.md:R-01, plan.md:Summary, contracts/catalog.md

**Checkpoint**: Catálogo base inventariado — el how-to y el registro declarativo pueden implementarse.

---

## Fase 2: Catálogo extensible (app/providers/arcgis_utils.py, app/providers/arcgis.py, app/main.py)

- [x] T003 [US1] Definir el catálogo central declarativo: lista `CATALOGO_CAPAS` de `CapaConfig` en `app/providers/arcgis_utils.py` (o `arcgis.py`) que reúna las capas de los 23 bloques base usando `RAIZ_ARCGIS + construir_params_punto` genérico — spec.md:FR-001, plan.md:Project Structure, research.md:R-01, contracts/catalog.md, data-model.md:Proyecto/CapaConfig
- [x] T004 [US1] Refactorizar `app/main.py:get_feasibility_report` para iterar `CATALOGO_CAPAS` en lugar de hardcodear cada bloque temático: cada entrada produce un `BloqueInforme` con `SourceTrace` 5 campos (`source_name/layer_id/service_url/data_vigencia/query_timestamp`), degradación por bloque `BLOQUE_DEGRADADO` sin fatal, preservando `BLOQUES_EVALUABLES` 19 baseline — spec.md:FR-001, FR-002, FR-003, contracts/catalog.md, research.md:R-02, R-06
- [x] T005 [US1] Añadir how-to mínimo de 3 pasos para capa nueva en docstring de `arcgis_utils.py` o `README.md`: 1) definir `CapaConfig`, 2) registrar en `CATALOGO_CAPAS`, 3) añadir test MockTransport con verificación 5 campos — spec.md:FR-004, research.md:R-07, contracts/catalog.md, quickstart.md:S1

**Checkpoint**: Catálogo declarativo operativo — añadir capa es 1 config + 1 test sin tocar orquestación.

---

## Fase 3: Wizard backend — preview ligero (app/web/main.py)

- [x] T006 [US2] Verificar/consolidar `POST /proyectos/preview` ligero (`app/web/main.py:222-290`): resuelve lote por `chip|direccion|coordenadas|clic` con `httpx.MockTransport` hermético, retorna `PreviewLote{lote{chip,direccion_normalizada,barrio,centroid,geometry}, upl{codigo,nombre,localidad}|null, manzana}` sin 23 bloques, con World fallback `geocode.arcgis.com/World/GeocodeServer` sin exigir `MAPAS_BOGOTA_APIKEY` y reuso `app/cache.py` LRU+TTL — spec.md:FR-005, FR-014, contracts/preview.md, research.md:R-03
- [x] T007 [US2] Implementar `hx-include` client-side para preview persistente: el preview confirmado persiste visualmente entre pasos sin nueva consulta a fuentes (campos ocultos + `hx-include`, sin sesión servidor/tabla `wizard_drafts`), sobreviviendo a navegación intra-wizard y a `hx-indicator` — spec.md:FR-006, research.md:R-03, contracts/wizard.md, quickstart.md:S2

**Checkpoint**: Preview ligero y persistente validado — el paso de interrogación puede habilitarse.

---

## Fase 4: Wizard frontend — interrogación + validación guiada (app/web/templates/index.html, app/web/main.py)

- [x] T008 [US2] Presentar el paso de interrogación con 5 campos opcionales persistidos (`uso_previsto` enum residencial/comercial/mixto/dotacional/industrial, `escala_m2` number ≥36, `presupuesto_rango` bajo/medio/alto, `horizonte_meses` 6-120, `aversion_riesgo` baja/media/alta) con `help text` por campo en `details` plegable `app/web/templates/index.html` — spec.md:FR-007, contracts/wizard.md, research.md:R-04, data-model.md:Proyecto
- [x] T009 [US2] Implementar validación dual inline: client-side HTML5 (`min="36"`, `min="6" max="120"`, `required` + mensajes) y server-side `app/web/main.py:_validar_formulario` extendido con enums/rangos, retorno 400 con error inline si bypass, sin persistir inválidos — spec.md:FR-008, research.md:R-04, contracts/wizard.md, plan.md:Technical Context
- [x] T010 [US2] Asegurar orden lógico inversión (1 identificar+preview → 1b interrogar → 2 informe): `POST /proyectos` final crea el proyecto con `criterio_tipo/valor + consulta/top_k + 5 campos wizard` via single POST con `hx-include`; cualquier reordenamiento menor se mantiene client-side HTMX sin sesión servidor — spec.md:FR-009, FR-012, research.md:R-03, contracts/wizard.md

**Checkpoint**: Wizard 3 pasos con validación guiada operativo — puede generar informe.

---

## Fase 5: Persistencia y reevaluación (app/web/db.py, app/web/main.py)

- [x] T011 [US3] Verificar migración aditiva `ProyectoRepositorio` (`app/web/db.py:PRAGMA table_info + ALTER TABLE ADD COLUMN` para `uso_previsto/escala_m2/presupuesto_rango/horizonte_meses/aversion_riesgo` 16 cols): `_fila_a_proyecto` lee filas viejas F10 con `None` sin 500, `crear`/`actualizar` con 16 cols — spec.md:FR-010, research.md:R-05, data-model.md:Proyecto, contracts/wizard.md
- [x] T012 [US3] Verificar `POST /proyectos/{id}/reevaluar` conserva los 5 campos wizard del proyecto original al regenerar informe; `GET /proyectos/{id}/json` incluye los 5 campos; flujo legacy `POST /proyectos` sin wizard sigue funcionando — spec.md:FR-011, FR-012, contracts/wizard.md, quickstart.md:S3

**Checkpoint**: Persistencia sin regresión para proyectos viejos y reevaluación.

---

## Fase 6: Pulido informe + identidad (app/web/templates/proyecto.html, app/web/templates/base.html)

- [x] T013 [US1] Verificar `GET /proyectos/{id}` renderiza 23 bloques base (17 loop + 6 separadas) con `market_dynamics` incluido (fix H-01), `llm_ready_summary` y `feasibility_score` visibles, 5 campos traza por bloque — spec.md:FR-015, FR-016, contracts/catalog.md, quickstart.md:S4
- [x] T014 [US2] Verificar identidad "Bogotá Reverdece" (Fraunces, 5 Pillars, anillo score SVG) y vendorización HTMX 2.0.4 / Leaflet 1.9.x sin CDN, responsive sin regresión — spec.md:FR-013, plan.md:Project Structure, quickstart.md:S4

**Checkpoint**: Informe y visual sin regresión.

---

## Fase 7: Tests contrato + smoke

- [x] T015 [P] [US1] Crear `tests/contract/test_catalogo_extensible.py`: añadir capa ficticia `catastro/prueba/MapServer/99` vía `CapaConfig` con `MockTransport`, verificar bloque nuevo con 5 campos, vigencias no mezcladas, 5xx degrada solo ese bloque sin `FUENTE_5XX` fatal, `BLOQUES_EVALUABLES` baseline intacto — spec.md:FR-001, FR-002, FR-003, contracts/catalog.md, quickstart.md:S1, research.md:R-02
- [x] T016 [P] [US2] Crear `tests/contract/test_wizard_v2.py`: preview ligero por chip `AAA0072LRYN`/dirección/coords/clic mapa, `POST /proyectos/preview` <2s, persistencia client-side entre pasos sin nueva consulta, validación inline `<36`/no numérica bloquea submit y server 400, reordenamiento lógico — spec.md:FR-005, FR-006, FR-007, FR-008, FR-009, contracts/preview.md, contracts/wizard.md, quickstart.md:S2
- [x] T017 [P] [US3] Ampliar tests de persistencia (`tests/contract/test_wizard_persistencia.py` o `test_web` existente): proyecto con 5 campos wizard persiste y reaparece en `GET /{id}/json`, `reevaluar` conserva, fila antigua sin columnas wizard lee `null` sin 500 — spec.md:FR-010, FR-011, contracts/wizard.md, quickstart.md:S3
- [x] T018 [US1] Añadir tests de no-regresión: 7 tools invariante (`tests/smoke/test_main.py` assert 7), `GET /{id}` 23 bloques, 486 tests baseline ≥486 0 failed, `docker build` sin regresión, `ruff check` sin E/F nuevo — spec.md:FR-015, SC-004, SC-005, plan.md:Performance Goals

**Checkpoint**: Suite F11 verificada — catálogo + wizard + persistencia sin regresión.

---

## Fase 8: Cierre (docs + commit)

- [x] T019 Actualizar `README.md` / `Caracteristicas.md` si aplica: documentar catálogo extensible (how-to) y wizard v2 preview persistente; `get_feasibility_report` sigue orquestando 23 bloques base — plan.md:Summary, spec.md:FR-004
- [x] T020 Commit de la feature F11 con mensaje convencional (p. ej. `feat(catalogo-wizard): catálogo extensible CapaConfig + wizard v2 preview persistente (F11)`) — flujo Spec Kit, constitución:commit en cada hito

**Checkpoint**: Feature F11 completa y commiteada, lista para `/speckit.clarify` si aplica o cierre.

---

## Dependencias y orden de ejecución

### Dependencias por fase

- **Setup (Fase 1)**: sin dependencias — puede comenzar de inmediato.
- **Catálogo (Fase 2)**: depende de Setup (T002 inventory). BLOQUEA Fase 6 pulido (T013 necesita catálogo iterado).
- **Wizard backend preview (Fase 3)**: depende de Setup; independiente de Catálogo (usa resolvers ligeros existentes HEAD 9641504).
- **Wizard frontend interrogación (Fase 4)**: depende de Fase 3 (preview persistente T007) y de Persistencia esquema (T011 puede paralelizarse).
- **Persistencia (Fase 5)**: depende de Setup; `db.py` ya migrado en HEAD 9641504 — verificación, no reimplementación. T012 depende de T011.
- **Pulido (Fase 6)**: depende de Catálogo (T004) y Wizard frontend (T010) — necesita informe final integrado.
- **Tests (Fase 7)**: depende de todas las fases anteriores; T015/T016/T017 paralelizables (archivos distintos).
- **Cierre (Fase 8)**: depende de Tests.

### Dependencias entre historias de usuario

- **US1 (catálogo)**: Fases 1-2, 6-7 (T002-T005, T013, T015, T018). Independiente tras Setup; verificable con MockTransport sin tocar wizard.
- **US2 (wizard v2)**: Fases 3-4, 6-7 (T006-T010, T014, T016). Reusa preview ligero HEAD 9641504; el bloque T007 (hx-include) habilita T008-T010.
- **US3 (persistencia)**: Fase 5 + 7 (T011-T012, T017). Ya migrado en HEAD; solo verificación + reevaluar conserva.

### Oportunidades de paralelismo

- T001 (no-cambio) y T002 (inventario catálogo) → paralelo (archivos distintos).
- T003-T005 (catálogo) secuenciales entre sí (tocan orquestación + doc), pero paralelizables con T006-T007 (wizard backend preview).
- T011 (persistencia) puede ir en paralelo con T008-T010 (wizard frontend).
- T015, T016, T017 son archivos de tests distintos → paralelo total (≈3 min suite).

---

## Estrategia de implementación

### MVP primero (US1 catálogo solo)

1. Fase 1 (T001-T002) inventory.
2. Fase 2 (T003-T004 catálogo declarativo + iteración orquestador) + T005 how-to.
3. Fase 7: T015 catálogo extensible + T018 no-regresión (sin wizard nuevo).
4. **STOP y VALIDAR**: `GET /proyectos/{id}/json` incluye bloque ficticio con 5 campos; `python -m pytest -q` ≥486 0 failed; `docker build` ok.
5. Luego US2+US3 (wizard + persistencia).

### Entrega incremental

1. Setup + Catálogo → extensión declarativa testeable sin wizard (MVP catálogo).
2. Wizard backend preview → separación costo barato/costoso validada.
3. Wizard frontend interrogación + validación dual → flujo 3 pasos guiado.
4. Persistencia + reevaluar conserva → sin regresión F10.
5. Pulido 23 bloques + identidad → cierre visual sin CDN.
6. Cada historia agrega valor sin romper las previas (catálogo no toca wizard; wizard no toca scoring).

---

## Notas

- [P] = archivos distintos, sin dependencias; ejecutar en paralelo cuando sea posible.
- [USn] mapea la tarea a su historia para trazabilidad con `spec.md`.
- Verificar que tests nuevos FALLAN antes de implementar (TDD, patrón del repo hermético).
- Commit tras cada fase o grupo lógico; no mezclar catálogo y wizard en un solo commit si son fases separadas.
- Detenerse en cualquier checkpoint para validar la historia independientemente.
- Evitar: tareas vagas, conflictos en el mismo archivo sin secuenciar, tocar `calcular_score` salvo regla explícita documentada en FR-003.

