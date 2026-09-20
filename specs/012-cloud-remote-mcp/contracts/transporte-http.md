# Contrato: Transporte HTTP (CLI + endpoint `/mcp`) — F12 Fase 1

**Feature**: [012-cloud-remote-mcp](../spec.md) · **Plan**: [plan.md](../plan.md) · **Data model**: [data-model.md](../data-model.md) · **Quickstart**: [quickstart.md](../quickstart.md)

Este contrato cubre ÚNICAMENTE la capa de arranque/transporte. El contrato de las
7 tools MCP (nombres, `inputSchema`, payloads JSON con `source_traces`, taxonomía
de 10 códigos) permanece **INVARIANTE** (FR-008): el modo HTTP serializa el mismo
payload que stdio por otro canal (SC-002).

---

## 1. CLI — `python -m app.main`

| Flag | Equivalente env | Default | Semántica |
|------|-----------------|---------|-----------|
| `--transport {stdio,http}` | `MCP_TRANSPORT` | `stdio` | `stdio`: comportamiento actual idéntico (`mcp.run()`, Dockerfile CMD intacto). `http`: monta la app ASGI Streamable HTTP y corre uvicorn. Otro valor → `SystemExit(2)` con mensaje claro en español (fail-fast, Principio IV). |
| `--host HOST` | `MCP_HOST` | `127.0.0.1` | Solo aplica a `--transport http`. Bind loopback por defecto (FR-002); `0.0.0.0` exige que el operador lo pida explícitamente. |
| `--port N` | `MCP_PORT` | `8000` | Solo modo HTTP. Entero 1–65535; fuera de rango → `SystemExit(2)` con mensaje claro. |

Reglas:

- Flag CLI gana sobre la variable de entorno; ninguna de las dos se comitea con
  valor real (FR-010).
- En modo `http` se requiere `uvicorn` (ya presente en el extra `web` de
  `pyproject.toml` — cero dependencias nuevas). Si falta, error de arranque
  explícito: instale `uv sync --extra web` (nunca traceback crudo).
- La validez de `--transport`/`--host`/`--port` se resuelve ANTES de abrir
  sockets ni construir providers.

## 2. Endpoint MCP — `POST /mcp` (Streamable HTTP)

- Servido por `mcp.streamable_http_app(streamable_http_path="/mcp", json_response=True)`
  del SDK (transporte Streamable HTTP de la spec MCP 2025-06-18; nunca SSE
  legacy). `json_response=True` → cada POST responde JSON plano (sin stream SSE
  colgado), coherente con stateless-first (D-05) y con los ejemplos curl del
  quickstart; sigue siendo un response válida del transporte.
- El `Mcp-Session-Id` lo gestiona el SDK (stateless-first, D-05); afinidad de
  sesión/Redis queda fuera de Fase 1 (D-03).
- Cada tool responde con el MISMO JSON que por stdio. Errores de dominio (p. ej.
  `FUENTE_5XX` de un provider) viajan como tool-result de error MCP, nunca como
  5xx HTTP del transporte.

## 3. Seguridad `Origin` (FR-003, anti DNS-rebinding)

Política aplicada por middleware/protección del transporte sobre TODA petición HTTP:

| Header `Origin` de la petición | Resultado |
|--------------------------------|-----------|
| Ausente (clientes no-browser: Claude Code, `mcp-remote`, Inspector, curl) | **Permitida** |
| Presente y en allowlist (`MCP_ALLOWED_ORIGINS`, CSV de orígenes `https://…`; `http://localhost:*` para desarrollo) | **Permitida** |
| Presente y NO allowlisted (incl. allowlist vacío, default) | **403**, el JSON-RPC ni se procesa |

- El 403 es una respuesta del TRANSPORTE, no de la taxonomía `CodigoError`
  (invariante FR-008: 10 códigos, sin nuevos).
- Con allowlist vacío por defecto el servidor es seguro-por-defecto: ningún
  navegador de otro origen puede invocarlo.

## 4. Lifespan encadenado (FR-004)

`construir_app_http(servidor_lotes, config)` en `app/servidor_http.py` debe:

1. Crear la app Starlette vía `http_app()` de `crear_servidor_mcp(servidor_lotes)`.
2. Componer los dos ciclos de vida en UNO solo:
   - **startup**: el del `StreamableHTTPSessionManager` interno de `http_app()`
     (sin esto el endpoint responde 500 — riesgo 1 del plan);
   - **shutdown**: `_lifespan_cerrar_providers` actual → `servidor_lotes.aclose()`
     cierra los `httpx.AsyncClient` de los 5 providers.
3. El verification test debe ejecutar una tool real vía ASGI y comprobar que al
   cerrar el lifespan los providers quedaron cerrados.

## 5. Montaje ASGI junto a la web F5 (US3, documentado sin activar)

- Patrón soportado: `app_web.mount("/mcp", mcp_app)` con el **lifespan de
  `http_app()` propagado explícitamente al `FastAPI(lifespan=...)` padre**
  (los lifespans anidados no se ejecutan solos — SDK lo exige).
- Fase 1 NO cambia el comportamiento de `app/web/main.py`: solo se documenta el
  patrón (docstring/comentario). Activar el mount queda a decisión del operador.

## 6. Invariantes verificables (gate de tests)

1. `initialize` + `tools/list` sobre `httpx.ASGITransport` → exactamente las 7
   tools con los mismos `name`/`inputSchema` que stdio.
2. `Origin: https://evil.example` → 403 sin procesar JSON-RPC.
3. Sin `Origin` → 200 con resultado JSON-RPC válido.
4. Host default `127.0.0.1` (verificable en config resuelta; `ss -ltnp` en manual).
5. `MCP_TRANSPORT=ftp` o `MCP_PORT=0` → `SystemExit` con mensaje claro en español.
6. `--transport stdio` (default): código de arranque idéntico al actual — el
   smoke de 7 tools stdio no se toca.
7. Suite completa verde sobre baseline (≥512 tests) y ruff ≤ baseline 199.
