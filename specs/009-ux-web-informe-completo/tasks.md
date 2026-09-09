# Tasks: UX Web Informe Completo

**Input**: Diseños de `/specs/009-ux-web-informe-completo/` (spec.md)

**Prerequisites**: spec.md

**Tests**: pytest — contract tests (`tests/contract/`) y smoke tests (`tests/smoke/`).

**Organization**: Las tareas se agrupan por fase para implementación secuencial.

## Formato: `T### [P?] [Story] Descripción — Cita`

- **[P]**: Puede ejecutarse en paralelo (archivos distintos, sin dependencias).
- **[Story]**: Historia de usuario a la que pertenece la tarea.
- **Cita**: referencia a `spec.md`, `contracts/`, `data-model.md` o `plan.md`.

---

## Fase 1: Infraestructura estática (Leaflet vendorizado)

- [x] T001 Vendorizar Leaflet.js 1.9.4 en `app/web/static/leaflet.js` y `app/web/static/leaflet.css` — descargados de unpkg CDN, sin dependencia externa runtime — spec.md:FR-009

**Checkpoint**: Assets de Leaflet disponibles localmente.

---

## Fase 2: Template proyecto.html (renderizado completo del informe)

- [x] T002 Añadir CDN link a Leaflet CSS en `base.html` o `proyecto.html` (solo en la página de detalle) — spec.md:FR-009
- [x] T003 Reescribir `proyecto.html`: sección de resumen ejecutivo con `llm_ready_summary` como callout destacado — spec.md:FR-005
- [x] T004 Reescribir `proyecto.html`: sección de identidad del lote (CHIP, dirección, coordenadas, manzana, localidad, UPL) — spec.md:FR-001
- [x] T005 Reescribir `proyecto.html`: contenedor del mapa Leaflet con script de inicialización para geometría del lote + centroide — spec.md:FR-003, FR-004
- [x] T006 Reescribir `proyecto.html`: loop sobre los 19 bloques evaluable con título, badge de estado, dato, interpretación y source_trace/source_traces — spec.md:FR-001, FR-002
- [x] T007 Reescribir `proyecto.html`: sección de evidencia normativa con cada ítem (artículo, título, libro, parte, norma, cita literal) — spec.md:FR-006
- [x] T008 Reescribir `proyecto.html`: sección de feasibility_score con score, confidence, reasons, rules_applied — spec.md:FR-007
- [x] T009 Reescribir `proyecto.html`: sección de advertencias con código y mensaje — spec.md:FR-008
- [x] T010 Añadir accesibilidad (aria-label, roles, semantic HTML) y estados responsive — spec.md:FR-011, FR-012

**Checkpoint**: Template completo renderiza todos los campos del informe.

---

## Fase 3: CSS (estilos para las nuevas secciones)

- [x] T011 Añadir estilos para: tarjetas de bloque (`.bloque-informe`), badges de estado (`.badge--disponible`, `.badge--no_encontrado`), proveniencia (`.fuente`), mapa (`.contenedor-mapa`), evidencia normativa, score detallado, callout de resumen — spec.md:FR-010

**Checkpoint**: Estilos consistentes con la identidad visual "Bogotá Reverdece".

---

## Fase 4: Tests

- [x] T012 Crear `tests/contract/test_web_informe.py` con tests que verifiquen que el detalle renderiza: score ring, llm_ready_summary, identidad del lote, mapa, los 19 bloques, evidencia normativa, score detallado, advertencias — spec.md:SC-001, SC-002
- [x] T013 Añadir test de caso ausente: geometría None -> mapa omitido gracefully — spec.md:FR-004

**Checkpoint**: Tests pasan, spec validada.

---

## Fase 5: Spec Kit

- [x] T014 Crear `specs/009-ux-web-informe-completo/spec.md` con 2 user stories, 12 FR, 3 NFR, 4 SC — spec.md
- [x] T015 Crear `specs/009-ux-web-informe-completo/contracts/informe-web.md` con el contrato de renderizado del template — spec.md:FR-001
- [x] T016 Crear `specs/009-ux-web-informe-completo/data-model.md` con los modelos pydantic que el template consume (InformeFactibilidad, sus bloques, Warning) — spec.md:FR-001
- [x] T017 Crear `specs/009-ux-web-informe-completo/quickstart.md` con instrucciones de verificación — spec.md
- [x] T018 Crear `specs/009-ux-web-informe-completo/checklists/requirements.md` — spec.md
- [x] T019 Actualizar `.specify/feature.json` para apuntar a `specs/009-ux-web-informe-completo`

**Checkpoint**: Spec Kit completo, feature.json actualizado.

---

## Fase 6: Verificación final

- [x] T020 Ejecutar `uv run pytest -q` y verificar que todos los tests pasan (existentes + nuevos) — spec.md:SC-001
- [x] T021 Ejecutar `bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks` y verificar exit 0 — spec.md:SC-004
