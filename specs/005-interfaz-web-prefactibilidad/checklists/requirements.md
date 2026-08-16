# Checklist de Requisitos: Interfaz web de prefactibilidad (Feature 5)

**Fecha**: 2026-08-16 | **Feature**: `005-interfaz-web-prefactibilidad`

Verificación final de requisitos de la especificación (spec.md). Marcar `[x]` solo con
evidencia (test en verde o inspección verificada).

## Requisitos Funcionales

- [x] **FR-001** `GET /` renderiza `index.html` con formulario + lista de proyectos (más recientes primero); sin proyectos → mensaje de lista vacía. — `tests/contract/test_web_rutas.py` (tests index), `tests/smoke/test_web.py`
- [x] **FR-002** `POST /proyectos` recibe nombre/criterio/consulta/top_k, evalúa con `get_feasibility_report` y persiste. — `test_crear_proyecto_completado`
- [x] **FR-003** Validación fail-fast 400 (nombre, criterio, valor, consulta ≤ 500, top_k 1–6, coordenadas numéricas). — `test_validacion_*`
- [x] **FR-004** Proyecto `completado` con informe 10 bloques o `fallido` con error `{code, message, source_name}`, sin lanzar. — `test_crear_proyecto_chip_inexistente`
- [x] **FR-005** `POST /proyectos` → 303 `Location: /proyectos/{id}` (PRG, `follow_redirects=False`). — `test_crear_proyecto_303`
- [x] **FR-006** `GET /proyectos/{id}` detalle (score/UPL/warnings o error); inexistente → 404. — `test_detalle_*`
- [x] **FR-007** `POST /proyectos/{id}/reevaluar` actualiza conservando id/creado_en; 303. — `test_reevaluar_*`
- [x] **FR-008** `GET /proyectos/{id}/json` → informe 10 bloques (200) o `{"error": ...}` con status mapeado. — `test_json_*`
- [x] **FR-009** Mapeo taxonomía→HTTP: 400/404/502/503/500; 5xx NUNCA degradado a "no encontrado". — `test_error_a_http_*`, `test_fuente_5xx_502`
- [x] **FR-010** Rutas `/json` responden JSON de error; rutas HTML → `error.html` con mismo status. — `test_manejador_*`
- [x] **FR-011** Errores inesperados → 500 `ERROR_INTERNO` (fail loud). — `test_error_interno_500`
- [x] **FR-012** `crear_app_web(servidor_lotes, repositorio)` con inyección de dependencias; lifespan cierra `ServidorLotes` con `aclose()`. — inspección `app/web/main.py` + fixtures
- [x] **FR-013** Estáticos vendorizados (htmx 2.0.4, Fraunces woff2, fonts.css, estilos.css) sin CDN; plantillas empaquetadas vía package-data. — `tests/smoke/test_web.py` (estáticos 200)
- [x] **FR-014** Sin tools MCP nuevas: `tests/smoke/test_main.py` SIN CAMBIOS (7 tools). — suite completa verde

## Success Criteria

- [x] **SC-001** Suite completa 263 tests en verde (259 previos + 4 smoke web), exit 0. — verificado 2026-08-16
- [x] **SC-002** Tests web sin red real ni Ollama: `TestClient` + `server_lotes_f3` + `NormativaProviderStub` + `ProyectoRepositorio(tmp_path)`. — fixtures en `tests/contract/test_web_rutas.py`
- [x] **SC-003** Identidad visual 5 Pillars: Fraunces vendorizada (sin Inter/Roboto/Arial/system-ui), paleta verde+ámbar sobre crema, UNA animación (anillo), composición asimétrica, textura SVG. — inspección `estilos.css`/`fonts.css`/plantillas
- [x] **SC-004** Score mostrado sin interpretación normativa inventada (FR-014 F3); disclaimer en footer. — `base.html`
- [x] **SC-005** Persistencia atómica por operación (transacción SQLite); fallo de evaluación → proyecto `fallido`, no corrompe. — `test_proyectos_repositorio.py`

## Artefactos Spec Kit (Feature 5)

- [x] `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/interfaz-web-prefactibilidad.md`, `tasks.md` (T001–T040), `quickstart.md`, `checklists/requirements.md`
- [x] `.specify/feature.json` → `specs/005-interfaz-web-prefactibilidad`

**Total FR: 14/14 · SC: 5/5 · Tareas: 40/40 marcadas `[x]`**