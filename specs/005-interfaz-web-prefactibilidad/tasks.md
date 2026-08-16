# Tasks: Interfaz web de prefactibilidad (Feature 5)

**Input**: Diseños de `/specs/005-interfaz-web-prefactibilidad/` (plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md)

**Prerequisites**: plan.md (obligatorio), spec.md (obligatorio para historias de usuario), research.md, data-model.md, contracts/, quickstart.md

**Tests**: pytest — smoke tests (`tests/smoke/`, SIN CAMBIOS: siguen las 7 tools de F1–F3 + 4 nuevos web) y contract tests (`tests/contract/`) según plan.md:54-61; las historias incluyen sus contract tests (escribirlos primero para que fallen antes de implementar, patrón F1/F2/F3).

**Organization**: Las tareas se agrupan por historia de usuario para permitir implementación y pruebas independientes de cada historia (constitución v1.0.0, Principio V — MVP first).

## Formato: `T### [P?] [Story] Descripción — Cita`

- **[P]**: Puede ejecutarse en paralelo (archivos distintos, sin dependencias).
- **[Story]**: Historia de usuario a la que pertenece la tarea (US1, US2, SETUP).
- **Cita**: referencia a `spec.md` (FR/SC), `plan.md`, `research.md`, `data-model.md`, `contracts/interfaz-web-prefactibilidad.md` o `quickstart.md` con línea, p. ej. `spec.md:122`.

## Convenciones de rutas

- Proyecto único: `app/`, `tests/` en la raíz del repositorio (plan.md:66-73).
- Estructura: `app/web/` (NUEVO: `main.py`, `db.py`, `templates/`, `static/`), `tests/contract/test_web_rutas.py` y `tests/contract/test_proyectos_repositorio.py` (NUEVOS), `tests/smoke/test_web.py` (NUEVO), `pyproject.toml` (extra `web`), `.env.example` (WEB_HOST/WEB_PORT/PROYECTOS_DB_PATH), `Dockerfile` (plan.md:66-73).
- Feature 5 NO modifica `app/main.py`, `app/models.py`, `app/errores.py`, `app/scoring.py`, `app/providers/*` ni `app/ingesta/*` (spec.md FR-014; data-model.md:61-63).

---

## Fase 1: Setup (Infraestructura compartida)

**Propósito**: crear el paquete `app/web/` y la infraestructura de empaquetado/ejecución de la capa web SIN lógica de dominio (la lógica llega en Fases 2–5)

- [x] T001 Crear el paquete `app/web/` con `__init__.py`, `main.py` (factory `crear_app_web(servidor_lotes=None, repositorio=None)` mínima que monta `/static` y responde 200 en `/`), `db.py` (placeholder), `templates/` y `static/` (con `.gitkeep`) — plan.md:66-73, research.md D1
- [x] T002 Añadir el extra `web` a `pyproject.toml` (`fastapi>=0.115`, `uvicorn>=0.30`, `jinja2>=3.1`, `python-multipart>=0.0.9`) + script `web-mcp-bogota-factibilidad` + `package-data` de plantillas/estáticos — plan.md:37-42, research.md D3
- [x] T003 Documentar en `.env.example` `WEB_HOST` (127.0.0.1), `WEB_PORT` (8000) y `PROYECTOS_DB_PATH` (`.data/proyectos.db`) — plan.md:37-42
- [x] T004 Ampliar `Dockerfile` (o documentar el arranque web con el extra `web`) sin romper el CMD MCP por stdio — plan.md:66-73
- [x] T005 Verificar que el smoke de arranque (`tests/smoke/test_main.py`) permanece SIN CAMBIOS con las 7 tools de F1–F3 (FR-014) — spec.md FR-014, plan.md:50-52

---

## Fase 2: Repositorio (Persistencia de proyectos)

**Propósito**: `Proyecto` (pydantic) + `ProyectoRepositorio` (sqlite3 stdlib) con transacción por operación; base de las rutas US1/US2

- [x] T006 [P] Escribir `tests/contract/test_proyectos_repositorio.py` (8 tests: crear/obtener/listar/actualizar, round-trip JSON de informe/error, actualizar a inexistente → None, transacción atómica) — data-model.md:15-33, data-model.md:43-57
- [x] T007 Definir `Proyecto` pydantic v2 en `app/web/db.py`: id (hex uuid), nombre, criterio_tipo (Literal), criterio_valor, consulta (opcional), top_k (default 3), estado (Literal completado/fallido), informe/error (dict opcionales, coherencia completado⇒informe, fallido⇒error) — data-model.md:15-33
- [x] T008 Implementar `ahora_iso()` (UTC ISO 8601) en `app/web/db.py` — data-model.md:24-25
- [x] T009 Implementar `ProyectoRepositorio(ruta)` en `app/web/db.py`: crea directorio padre + tabla `proyectos` (id TEXT PK, nombre, criterio_tipo, criterio_valor, consulta, top_k, estado, informe, error, creado_en, actualizado_en) — data-model.md:35-57
- [x] T010 Implementar `crear(proyecto)` (INSERT, falla si id duplicado) y `obtener(proyecto_id)` (SELECT → Proyecto | None) con `json.loads` de informe/error — data-model.md:43-57
- [x] T011 Implementar `listar()` (ORDER BY creado_en DESC) y `actualizar(proyecto)` (UPDATE por id, None si no existe) — data-model.md:43-57
- [x] T012 Ejecutar `tests/contract/test_proyectos_repositorio.py` en verde (8 tests) — data-model.md:54-61
- [x] T013 Commit `70347f7` — `feat(feature5): repositorio de proyectos prefactibilidad (Fase 2)`

---

## Fase 3: Rutas US1 (Crear y listar)

**Propósito**: `GET /` (formulario + lista) y `POST /proyectos` (validación fail-fast 400, evaluación, persistencia, 303 PRG)

- [x] T014 [P] Escribir `tests/contract/test_web_rutas.py` (16 tests, T014–T018 compartidos con Fases 4–5): `GET /` 200 con formulario+lista; `POST /proyectos` válido → 303 `Location: /proyectos/{id}` (follow_redirects=False); `POST /proyectos` con CHIP inexistente → 303 + proyecto `fallido` con `LOTE_NO_ENCONTRADO`; `GET /proyectos/{id}/json` de fallido → 404 con `{"error": ...}`; validación 400 (nombre vacío, criterio inválido, top_k fuera de rango, coordenadas mal formadas); 404 de id inexistente — spec.md FR-001..FR-005, FR-009, contracts §2, §3, §5
- [x] T015 Implementar `GET /` en `app/web/main.py`: renderiza `index.html` con formulario (modos chip/direccion/coordenadas) y lista `repositorio.listar()`; sin proyectos → mensaje de lista vacía — spec.md FR-001, FR-003
- [x] T016 Implementar `_validar_formulario(datos)` en `app/web/main.py`: nombre obligatorio ≤200, criterio_tipo válido, criterio_valor obligatorio (coordenadas `lat,lon` numéricas), consulta ≤500, top_k 1–6; devuelve errores por campo o dict limpio; usa `Form("")` para evitar el 422 de FastAPI con valores vacíos — spec.md FR-003, research.md D2 (riesgos), contracts §2
- [x] T017 Implementar `POST /proyectos` en `app/web/main.py`: valida (400 fail-fast), construye kwargs de `get_feasibility_report` según criterio (`chip=`/`direccion=`/`coordenadas=`), evalúa con el `ServidorLotes` inyectado (try/except → `proyecto.error` sin lanzar), persiste y responde 303 PRG — spec.md FR-002, FR-004, FR-005, contracts §2
- [x] T018 Ejecutar `tests/contract/test_web_rutas.py` parcial en verde (tests de US1) — spec.md FR-001..FR-005

---

## Fase 4: Rutas US2 (Detalle, re-evaluación y JSON)

**Propósito**: `GET /proyectos/{id}` (detalle), `POST /proyectos/{id}/reevaluar` (re-evaluación conservando id) y `GET /proyectos/{id}/json` (informe completo)

- [x] T019 Implementar `GET /proyectos/{id}` en `app/web/main.py`: renderiza `proyecto.html` con criterio/fechas/estado; si `completado` → score/confianza + UPL (administrative_context.upl.codigo/nombre) + localidad + warnings; si `fallido` → caja de error; id inexistente → 404 `error.html` — spec.md FR-006, FR-009, contracts §3
- [x] T020 Implementar `POST /proyectos/{id}/reevaluar` en `app/web/main.py`: re-evalúa con los criterios del proyecto, actualiza estado/informe/error y `actualizado_en`, conserva id/creado_en; 303 a `/proyectos/{id}`; 404 si inexistente — spec.md FR-007, contracts §4
- [x] T021 Implementar `GET /proyectos/{id}/json` en `app/web/main.py`: si `completado` → informe 10 bloques (200); si `fallido` → `{"error": ...}` con status mapeado por `_error_a_http`; id inexistente → 404 `{"error": {"code": "NO_ENCONTRADO"}}` — spec.md FR-008, FR-009, contracts §5
- [x] T022 Ejecutar `tests/contract/test_web_rutas.py` completo en verde (16 tests) — spec.md FR-006..FR-011
- [x] T023 Commit Fases 3-5 `daff1eb` — `feat(feature5): rutas web US1/US2 con mapeo de errores (Fase 3-5)` (incluye T024–T028)

---

## Fase 5: Mapeo de errores (taxonomía → HTTP)

**Propósito**: traducir los 10 códigos canónicos de `app/errores.py` a status HTTP sin degradar 5xx, con respuestas HTML y JSON diferenciadas

- [x] T024 Definir `_ERROR_A_HTTP` en `app/web/main.py`: PARAMETROS_INVALIDOS→400; LOTE_NO_ENCONTRADO/DIRECCION_NO_LOCALIZADA/FUERA_DE_COBERTURA/LOTE_SIN_UPL/DATO_NO_ENCONTRADO_POR_FUENTE→404; FUENTE_5XX→502; CREDENCIAL_FALTANTE/CORPUS_NO_INGESTADO/OLLAMA_NO_DISPONIBLE→503; desconocido/None→500 — spec.md FR-009, contracts §6
- [x] T025 Implementar `_error_a_http(codigo)` (catch-all 500) + función `_serializar_error` (`{code, message, source_name}`) — spec.md FR-009, FR-011, contracts §6
- [x] T026 Añadir manejadores de excepción: `HTTPException` → HTML `error.html` (o JSON si la ruta es `/json`); `Exception` genérica → 500 `ERROR_INTERNO` (fail loud) — spec.md FR-010, FR-011
- [x] T027 Verificar en `tests/contract/test_web_rutas.py` el caso FUENTE_5XX → 502 (provider_arcgis_f3(lotes=(None, 500))) y CREDENCIAL_FALTANTE → 503 — spec.md FR-009, research.md D6
- [x] T028 Commit `daff1eb` (junto con Fases 3-4, T023) — suite 259 tests en verde

---

## Fase 6: Frontend (Identidad visual 5 Pillars)

**Propósito**: diseño "Bogotá Reverdece" — Fraunces vendorizada, paleta, UNA animación (anillo de score), composición asimétrica, textura de curvas de nivel; HTMX 2.0.4 sin CDN (SC-003)

- [x] T029 [P] Vendorizar `htmx.min.js` v2.0.4 en `app/web/static/` (sin CDN, SC-003) — research.md D4
- [x] T030 [P] Descargar 6 woff2 de Fraunces variable (normal/italic × latin/latin-ext/vietnamese, mapeo `6NU78*`=normal/`6NU58*`=italic) a `app/web/static/fonts/` + escribir `fonts.css` con @font-face y unicode-range locales (sin CDN) — research.md D5, SC-003
- [x] T031 [P] Escribir `estilos.css` con los 5 Pillars: variables de paleta (--verde-profundo #0b3d2e, --ambar #c9a227, --dorado #e0b84c, --crema #f7f2e7), grid asimétrico 7fr/5fr, textura SVG de curvas de nivel, `@keyframes dibujar-anillo` (UNA animación, 1.1s forwards, respeta prefers-reduced-motion) y estilos de formulario/tabla/tarjetas — spec.md SC-003, research.md D5
- [x] T032 Reescribir `templates/base.html`: header con marca (kicker + título + textura de curvas de nivel) + nav + footer con disclaimer de score heurístico (FR-014 de F3); `hx-boost="true"` en body — spec.md SC-003, SC-004
- [x] T033 Reescribir `templates/index.html`: formulario (nombre, criterio con 3 modos, consulta, top_k) con htmx (`hx-post`, `hx-target="body"`, `hx-swap="outerHTML"`, indicador) + lista de proyectos (o mensaje de vacío fuera del `{% if proyectos %}`) — spec.md FR-001, FR-002, SC-003
- [x] T034 Reescribir `templates/proyecto.html` (anillo SVG de score con `--anillo-destino`, UPL/localidad desde `administrative_context.upl.codigo/nombre`, warnings, enlace /json, caja de error) y `templates/error.html` — spec.md FR-006, SC-003, SC-004; verificar 16 tests de rutas web en verde tras el rediseño

---

## Fase 7: Smoke + docs + cierre (Feature completa)

**Propósito**: smoke tests web, documentación (README), artefactos Spec Kit (specs/005) y cierre con la suite completa en verde

- [x] T035 [P] Escribir `tests/smoke/test_web.py` (4 tests): (1) rutas US1/US2 registradas en la app; (2) `GET /` 200 con identidad visual (Fraunces + htmx local, sin CDN); (3) estáticos 200 (`/static/htmx.min.js`, `/static/fonts.css`, `/static/estilos.css`, un woff2); (4) flujo completo POST 303 → GET detalle con `anillo-score` → `/json` con informe — spec.md FR-001..FR-008, SC-002, SC-003
- [x] T036 [P] Actualizar `README.md`: línea de la Feature 5 en el estado actual + sección "Interfaz web de prefactibilidad (Feature 5)" (instalación `pip install -e ".[web]"`, ejecución `web-mcp-bogota-factibilidad`/uvicorn factory, tabla de rutas, mapeo de errores, validación FR-012, identidad visual, sin estado compartido con MCP) + sección Pruebas (smoke web + contract web) + sección Estructura (`app/web/`) — spec.md FR-001..FR-014, SC-001..SC-005
- [x] T037 Ejecutar la suite completa: **263 tests** (259 previos + 4 smoke web) en verde, exit 0 — spec.md SC-001
- [x] T038 Escribir los artefactos Spec Kit de `specs/005-interfaz-web-prefactibilidad/` (spec.md, plan.md, research.md, data-model.md, contracts/, tasks.md, quickstart.md, checklists/requirements.md) — spec.md FR-001..FR-014
- [x] T039 Actualizar `.specify/feature.json` → `{"feature_directory": "specs/005-interfaz-web-prefactibilidad"}` — AGENTS.md flujo de trabajo
- [x] T040 Commit final Fases 6-7 — `feat(feature5): interfaz web con identidad Bogotá Reverdece + smoke/docs (Fase 6-7)`