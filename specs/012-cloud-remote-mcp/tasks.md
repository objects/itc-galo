---
description: Task list for Feature 012 — Exposición remota del servidor MCP (Cloud)
---

# Tasks: Exposición remota del servidor MCP (Cloud)

**Input**: Design documents from `/specs/012-cloud-remote-mcp/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/transporte-http.md

**Tests**: INCLUIDOS — plan.md exige contract tests herméticos del modo HTTP
(`httpx.ASGITransport`, sin puertos reales ni red), y spec.md SC-001/SC-003 los
hacen verificables.

**Organización**: tareas agrupadas por historia de usuario. US1 (P1) es el MVP en
código; US2 (P2, OAuth producción) es documentación operativa (el AS es gestionado
— D-01 — fuera de este repo); US3 (P3, coexistencia web) es documentación del
patrón de mount SIN activarlo (decisión del plan).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelable (archivos distintos, sin dependencias pendientes)
- **[Story]**: US1 / US2 / US3
- Rutas exactas de archivos en cada descripción

---

## Phase 1: Setup (Configuración compartida)

**Purpose**: variables de entorno y entidad `ConfigTransporte` (data-model.md §1)

- [x] T001 [P] Documentar las variables `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`, `MCP_ALLOWED_ORIGINS` (defaults `stdio` / `127.0.0.1` / `8000` / vacío, reglas de `.env.example`) en `.env.example`
- [x] T002 Crear `app/servidor_http.py` con la entidad `ConfigTransporte` (frozen dataclass o pydantic: `transporte`, `host`, `puerto`, `origines_permitidos: list[str]`) y su resolutor `resolver_config(...)` que combina flags CLI > entorno > default y falla FAST con `SystemExit(2)` + mensaje claro en español ante `transporte ∉ {stdio,http}`, puerto fuera de 1–65535 u origen malformado en la allowlist — en `app/servidor_http.py`

**Checkpoint**: ConfigTransporte valida y resuelve sola; todavía no hay HTTP.

---

## Phase 2: Foundational (Bloquea todas las historias)

**Purpose**: app ASGI Streamable HTTP con lifespan encadenado y seguridad Origin

**⚠️ CRITICAL**: nada de US1–US3 puede terminar sin esta fase.

- [x] T003 Implementar `construir_app_http(servidor_lotes, config)` en `app/servidor_http.py`: construye el servidor vía `crear_servidor_mcp(servidor_lotes)`, obtiene `mcp.http_app(path="/mcp")` y COMPONE un único lifespan que arranca el `StreamableHTTPSessionManager` del SDK y al cerrar ejecuta el cierre de providers (`servidor_lotes.aclose()`) — contrato §4
- [x] T004 Implementar la política `Origin` en `app/servidor_http.py` (middleware ASGI o `host_origin_protection` del SDK si la versión instalada lo expone): Origin ausente → permitido; Origin presente y no allowlisted (incl. allowlist vacío default) → 403 sin procesar JSON-RPC — contrato §3; reutilizar `_clave_sin_tildes`/helpers de `app/utilidades.py` solo si aplica (no duplicar parsing)
- [x] T005 Ampliar `main()` en `app/main.py` con `argparse`: `--transport {stdio,http}` (default `stdio`,ruta actual `mcp.run()` intacta), `--host`, `--port`; modo http → `resolver_config` + `construir_app_http` + `uvicorn.run(app, host=..., port=...)` con error de arranque explícito (no traceback) si `uvicorn` no está instalado (`uv sync --extra web`) — contrato §1

**Checkpoint**: `python -m app.main --transport http` sirve `/mcp` en loopback.

---

## Phase 3: User Story 1 — Demo remota (Consumir las 7 tools por HTTPS) (Priority: P1) 🎯 MVP

**Goal**: un cliente MCP (Claude Desktop vía `npx mcp-remote`, Inspector) lista y
ejecuta las 7 tools contra `http://127.0.0.1:8000/mcp` con resultados idénticos a
stdio, con Origin validado y bind loopback por defecto (spec US1, FR-001…FR-005,
FR-008).

**Independent Test**: `tests/contract/test_transporte_http.py` sobre
`httpx.ASGITransport` (hermético) + validación manual del quickstart §§1–3.

### Tests for User Story 1 ⚠️ (escribir ANTES de validar green)

- [x] T006 [P] [US1] Test de paridad: `initialize` + `tools/list` contra la app de T003 → exactamente las 7 tools con los mismos `name`/`inputSchema` que `crear_servidor_mcp()` en stdio, en `tests/contract/test_transporte_http.py`
- [x] T007 [P] [US1] Test de seguridad Origin: `Origin: https://evil.example` → 403 sin procesar JSON-RPC; petición SIN `Origin` → 200 JSON-RPC válido; Origin allowlisted (config con `MCP_ALLOWED_ORIGINS=https://app.example`) → permitida, en `tests/contract/test_transporte_http.py`
- [x] T008 [P] [US1] Test de configuración: default del host resuelto = `127.0.0.1`; `MCP_TRANSPORT=ftp` y `MCP_PORT=0` → `SystemExit` con mensaje claro (sin traceback crudo), en `tests/contract/test_transporte_http.py`
- [x] T009 [P] [US1] Test de lifespan encadenado (FR-004): dentro del contexto ASGI ejecutar una tool con providers mock (`httpx.MockTransport` de `tests/conftest.py`) y afirmar que al salir del lifespan `servidor_lotes` quedó cerrado, en `tests/contract/test_transporte_http.py`
- [x] T010 [US1] Ejecutar `uv run pytest tests/contract/test_transporte_http.py -q`: verificar RED antes de T003–T005 y GREEN después; corregir hasta pasar, en `tests/contract/test_transporte_http.py`

### Implementation for User Story 1

- [x] T011 [US1] Validación manual end-to-end del quickstart §§1–3 en el entorno local: stdio intacto, `--transport http` escucha solo en `127.0.0.1:8000` (`ss -ltnp`), curl con Origin foráneo → 403, sin Origin → 200, Inspector o `npx mcp-remote` listan las 7 tools (SC-002), registrando el resultado en `specs/012-cloud-remote-mcp/quickstart.md` (casillas de "Criterios de salida")
- [x] T012 [US1] Documentar la demo Fase 2 (túnel) en `README.md`: `cloudflared tunnel --url http://localhost:8000`, añadir la URL `https://<random>.trycloudflare.com/mcp` como custom connector (auth `none`/bearer estático SOLO demo, FR-006), y nota de que las tools son read-only sobre datos públicos

**Checkpoint**: MVP — modo HTTP local verificado, paridad stdio↔HTTP demostrada.

---

## Phase 4: User Story 2 — Producción con OAuth 2.1 (Priority: P2)

**Goal**: guiar el despliegue VPS + TLS + OAuth 2.1 (spec US2, FR-007, SC-004). El
Authorization Server es GESTIONADO (D-01): este repo NO implementa un AS; entrega
documentación operativa y la variante de contenedor.

**Independent Test**: un lector con el doc puede montar el flujo
PRM→AS-metadata→DCR→PKCE→RFC 8707 contra Auth0/Cognito y conectar ChatGPT.

### Implementation for User Story 2

- [x] T013 [US2] Crear la guía de producción `specs/012-cloud-remote-mcp/produccion-oauth.md`: AS gestionado (D-01), `/.well-known/oauth-protected-resource` (RFC 9728), `/.well-known/oauth-authorization-server` (RFC 8414), DCR (RFC 7591), PKCE obligatorio, echo `resource` (RFC 8707), redirect `https://chatgpt.com/connector/oauth/{callback_id}`, modos de Claude ("Always required"/lazy) y validación JWT en el borde (research §§3–4)
- [x] T014 [US2] Documentar en `produccion-oauth.md` la variante Docker de producción: CMD con `--transport http --host 0.0.0.0`, `EXPOSE 8000`, healthcheck, reverse-proxy TLS (Caddy), secrets por entorno/secret store (FR-010) y co-localización de Ollama con degradación RAG documentada (D-04, FR-009); sin cambios al `Dockerfile` actual (default stdio)

**Checkpoint**: ruta de producción documentada sin código nuevo en el repo.

---

## Phase 5: User Story 3 — Coexistencia con la web F5 (Priority: P3)

**Goal**: dejar verificado y documentado el patrón `Mount("/mcp")` sobre la app
FastAPI de F5 con lifespan propagado (spec US3), SIN cambiar el comportamiento de
la web (decisión del plan).

**Independent Test**: un test que monta la app MCP dentro de FastAPI con el
lifespan propagado y lista las 7 tools por `TestClient` — el patrón funciona.

### Tests for User Story 3

- [x] T015 [P] [US3] Test del patrón de montaje: FastAPI con `lifespan` que compone el de `http_app()`, `app.mount("/mcp", ...)` + `httpx.ASGITransport` → `tools/list` responde las 7 tools y el shutdown cierra providers, en `tests/contract/test_transporte_http.py`

### Implementation for User Story 3

- [x] T016 [US3] Documentar el patrón (código de ejemplo comentado, NO activado) en el docstring de `crear_app_web` en `app/web/main.py`: propagación explícita del lifespan de `http_app()` al FastAPI padre y `Mount("/mcp", app=mcp_app)` (contrato §5)

**Checkpoint**: coexistencia MCP+web soportada por documentación verificada.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T017 [P] Actualizar `AGENTS.md` (estado F12: flag `--transport`, módulo `app/servidor_http.py`, 4 variables nuevas, invariantes 7 tools/23 bloques intactos) y `specs/012-cloud-remote-mcp/quickstart.md` (casillas de criterios de salida marcadas tras T011)
- [x] T018 [P] Enmendar la constitución `.specify/memory/constitution.md`: cláusula "Transporte MCP por stdio." → "Transporte MCP por stdio (por defecto) y modo Streamable HTTP opcional (F12), con validación Origin y bind loopback por defecto." — ⚠️ GATE DE GOBERNANZA: requiere aprobación explícita del usuario antes de aplicar (via `/speckit.constitution`)
- [x] T019 Ejecutar la suite completa `uv run pytest -q --tb=no -p no:warnings` (exit 0 sobre el baseline ≥512) y `uv run ruff check app tests` (≤199 baseline) en `tests/`
- [x] T020 Re-ejecutar `specs/012-cloud-remote-mcp/quickstart.md` §§1–5 completo como validación final de salida de Fase 1

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias
- **Foundational (Phase 2)**: depende de T002 (ConfigTransporte); BLOQUEA US1–US3
- **US1 (Phase 3)**: depende de T003–T005; los tests T006–T009 pueden escribirse
  en paralelo contra el contrato antes de que T003–T005 estén verdes (TDD)
- **US2 (Phase 4)**: depende conceptualmente de US1 (documenta el modo http ya
  existente); archivos distintos → paralelable con US3
- **US3 (Phase 5)**: depende de T003 (reutiliza `construir_app_http`); paralelable con US2
- **Polish (Phase 6)**: depende de las fases deseadas; T018 (enmienda) puede
  pedirse al usuario al finalizar Phase 2, no más tarde de implementar

### User Story Dependencies

- **US1 (P1)**: MVP — ninguna dependencia entre historias
- **US2 (P2)**: docs; no toca código de US1
- **US3 (P3)**: test + comentario doc; no cambia comportamiento de la web

### Within Each User Story

- Tests RED antes de su implementación de Fase 2 correspondiente (T010 lo verifica)
- Verificación manual (T011) solo después de tests verdes

### Parallel Opportunities

- T001 ∥ T002
- T006–T009 ∥ (cuatro bloques de test, mismo archivo → NO marcar [P] entre sí si
  se editan en paralelo; aquí [P] indica independencia de T010, no concurrencia de escritura — escribirlos en un solo commit de tests)
- US2 (T013–T014) ∥ US3 (T015–T016) ∥ pulido T017

---

## Parallel Example: User Story 1

```bash
# Tests de US1 (un solo archivo, redactar en un paso, verificar RED con T010):
Task: "Contract de paridad 7 tools stdio↔HTTP en tests/contract/test_transporte_http.py"
Task: "Contract 403 Origin / 200 sin-Origin / allowlist"
Task: "Contract fail-fast de configuración"
Task: "Contract lifespan encadenado + providers cerrados"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 (T001–T002) → 2. Phase 2 (T003–T005) → 3. Phase 3 (T006–T012)
4. **STOP and VALIDATE**: quickstart §§1–4 + pytest verde
5. Pedir al usuario la aprobación de la enmienda constitucional (T018) antes de
   commitear la implementación (gate del plan §Constitution Check)
6. Demo opcional con cloudflared (T012)

### Incremental Delivery

1. MVP (US1) → modo HTTP local consumible por mcp-remote/Inspector
2. US2 → guía de producción OAuth (VPS + AS gestionado)
3. US3 → patrón de coexistencia web documentado y testeado
4. Polish → docs, gates de suite, enmienda

---

## Notes

- [P] = archivos distintos / sin bloqueos; los 4 tests de US1 comparten archivo:
  redactarlos juntos (un commit) aunque sean lógicamente independientes
- Ninguna tarea toca `app/providers/`, `app/models.py`, `app/scoring.py`,
  `app/errores.py`, `app/cache.py`, `app/ingesta/` ni las 7 tools (FR-008)
- Los tests usan `httpx.ASGITransport` + fixtures de `tests/conftest.py`
  (`CHIP_VALIDO=AAA0072LRYN`): sin puertos reales, sin red, sin Ollama
- Racha de commits sugerida: T001–T002 / T003–T005+T006–T010 / T011–T012 / T013–T016 / T017–T020
