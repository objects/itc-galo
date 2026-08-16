# Implementation Plan: Interfaz web de prefactibilidad (Feature 5)

**Branch**: `005-interfaz-web-prefactibilidad` | **Date**: 2026-08-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/005-interfaz-web-prefactibilidad/spec.md`

**Note**: Este plan es la salida del comando `/speckit.plan` (Phase 0 + Phase 1). Los
artefactos de diseño son [research.md](research.md), [data-model.md](data-model.md),
[contracts/interfaz-web-prefactibilidad.md](contracts/interfaz-web-prefactibilidad.md) y
[quickstart.md](quickstart.md). La descomposición en tareas (`tasks.md`) la genera el
comando `/speckit.tasks` (Phase 2), NO este plan.

## Summary

Requisito primario (FR-001 a FR-014): **interfaz web de prefactibilidad** (FastAPI + Jinja2 +
HTMX) que permite **US1** crear una evaluación de prefactibilidad desde un formulario (CHIP,
dirección o coordenadas; consulta normativa opcional; top_k 1–6) y listar los proyectos, y
**US2** ver el detalle de un proyecto (anillo de score, UPL, warnings o error), re-evaluarlo y
obtener su informe JSON. La capa web **reutiliza `ServidorLotes.get_feasibility_report` (F3)
SIN protocolo MCP** (D1): construye su propio `ServidorLotes` en el lifespan y lo cierra con
`aclose()`; los proyectos se persisten en SQLite (`sqlite3` stdlib, sin dependencia nueva) con
estado `completado`/`fallido`; la taxonomía de errores (10 códigos, `app/errores.py`) se
mapea a status HTTP (400/404/502/503/500) sin degradar 5xx (FR-009); las validaciones de
formulario fallan rápido con 400 (FR-012).

Enfoque técnico (research D1–D6): paquete nuevo `app/web/` con `main.py` (factory
`crear_app_web(servidor_lotes=None, repositorio=None)` con inyección de dependencias),
`db.py` (`Proyecto` pydantic + `ProyectoRepositorio` SQLite), `templates/` (base, index,
proyecto, error) y `static/` (htmx.min.js v2.0.4 + Fraunces woff2 + `fonts.css` + `estilos.css`
vendorizados, sin CDN). Extra `web` en `pyproject.toml` (fastapi, uvicorn, jinja2,
python-multipart) + script `web-mcp-bogota-factibilidad`. Identidad visual (Fase 6, 5 Pillars):
Fraunces variable, paleta "Bogotá Reverdece" (verde profundo + ámbar sobre crema), UNA
animación (anillo de score), composición asimétrica, textura de curvas de nivel SVG. **Sin
tools MCP nuevas** (FR-014): `tests/smoke/test_main.py` permanece con las 7 tools de F1–F3.

## Technical Context

**Language/Version**: Python 3.11+ (requisito `requires-python = ">=3.11"`). FastAPI ≥ 0.115
(verificado 0.141.1), Starlette ≥ 1.6 (firma `TemplateResponse(request, name, context)`),
Jinja2 ≥ 3.1 (verificado 3.1.6), python-multipart ≥ 0.0.9, uvicorn ≥ 0.30.

**Primary Dependencies**: 4 dependencias nuevas SOLO del extra `web` (no runtime MCP):
`fastapi>=0.115`, `uvicorn>=0.30`, `jinja2>=3.1`, `python-multipart>=0.0.9`. Sin variables de
entorno nuevas obligatorias: `WEB_HOST` (default 127.0.0.1), `WEB_PORT` (default 8000),
`PROYECTOS_DB_PATH` (default `.data/proyectos.db`). HTMX 2.0.4 y Fraunces v38 (6 woff2:
normal/italic × latin/latin-ext/vietnamese) vendorizados en `app/web/static/`.

**Storage**: `ProyectoRepositorio` (SQLite vía `sqlite3` stdlib) en `PROYECTOS_DB_PATH`
(default `.data/proyectos.db`, gitignored): tabla `proyectos` con id (hex uuid), nombre,
criterio_tipo, criterio_valor, consulta, top_k, estado, informe (JSON), error (JSON),
creado_en, actualizado_en. Transacción por operación (crear/obtener/listar/actualizar);
`ahora_iso()` = UTC ISO 8601.

**Testing**: `pytest` con `asyncio_mode = "auto"`. Nuevos contract tests:
`tests/contract/test_web_rutas.py` (16 tests: POST 303, GET 200, validación 400, 404,
reevaluar, /json, mapeo `_error_a_http`), `tests/contract/test_proyectos_repositorio.py`
(8 tests Fase 2), y smoke web `tests/smoke/test_web.py` (4 tests: rutas registradas, index con
identidad, estáticos 200, flujo completo). Todo sin red real ni Ollama: `TestClient` con
`server_lotes_f3` + `NormativaProviderStub` + `ProyectoRepositorio(tmp_path)`.

## Phases

1. **Fase 1 — Setup** (T001–T005): paquete `app/web/` (con `main.py` factory mínima + db.py
   placeholder + templates/static `.gitkeep`), extra `web` + script + package-data en
   `pyproject.toml`, `.env.example`, `Dockerfile`. Commits: `69139ca`.
2. **Fase 2 — Repositorio** (T006–T013): `Proyecto` (pydantic) + `ProyectoRepositorio`
   (sqlite3) + 8 contract tests. Commit: `70347f7`.
3. **Fase 3 — Rutas US1** (T014–T018): `GET /` y `POST /proyectos` con validación fail-fast
   (400), persistencia, 303 PRG.
4. **Fase 4 — Rutas US2** (T019–T023): `GET /proyectos/{id}`, `POST /proyectos/{id}/reevaluar`,
   `GET /proyectos/{id}/json`.
5. **Fase 5 — Mapeo de errores** (T024–T028): `_ERROR_A_HTTP` + `_error_a_http()`, manejadores
   HTML vs `/json`, error 500 fail-loud. Commits Fases 3-5: `daff1eb` (16 contract tests).
6. **Fase 6 — Frontend 5 Pillars** (T029–T034): vendorizar htmx 2.0.4 + Fraunces woff2,
   `fonts.css`, `estilos.css` (5 Pillars), plantillas base/index/proyecto/error con htmx.
7. **Fase 7 — Smoke + docs + cierre** (T035–T040): smoke web (4 tests), README (sección
   Feature 5 + Pruebas + Estructura), `specs/005` + `.specify/feature.json`, suite completa
   (263) y commits finales.

## Riesgos y mitigaciones

- **Firma de `TemplateResponse` (Starlette ≥ 1.6)**: `(request, name, context=None, ...)`; no
  la firma antigua posicional `(name, {"request": request})`. Verificado en vivo (research D3).
- **`Form(...)` con valor vacío**: FastAPI responde 422 "Field required" antes de llegar al
  handler; se usan defaults `Form("")` y la validación de dominio (`_validar_formulario`)
  responde 400 con el mensaje del contrato (fix aplicado en la Fase 3).
- **TestClient sigue redirects por defecto**: para asertar el 303 se usa
  `follow_redirects=False`.
- **Shape de `administrative_context`**: la plantilla `proyecto.html` lee
  `administrative_context.upl.codigo/nombre` (shape real del contrato F3, verificado en
  `test_get_feasibility_report.py:188-193`), no `dato.upl`.