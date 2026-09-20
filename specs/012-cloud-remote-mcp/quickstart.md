# Quickstart — Feature 012: Exposición remota del servidor MCP (Fase 1)

> Documento de validación ejecutable. NO contiene código de implementación:
> describe cómo verificar el comportamiento cuando la Fase 1 esté implementada
> (flag `--transport` en `app/main.py` + módulo `app/servidor_http.py`).

## Requisitos previos

- Python 3.11+ con dependencias del proyecto instaladas (`uv sync`).
- El proyecto NO carga `.env` automáticamente: exporta las variables en el shell
  si quieres alejarte de los defaults (ver `.env.example`).
- Ollama opcional: sin él, `consultar_normativa` degrada con warnings (patrón F3),
  nunca es fatal.

## 1. Retrocompatibilidad stdio (default, FR-001)

```bash
uv run python -m app.main
```

Espera: el proceso arranca por stdio EXACTAMENTE como hoy (Dockerfile CMD
`python -m app.main` intacto). Un cliente MCP local (Claude Desktop con
`command/args`) ve las 7 tools. `Ctrl+C` termina limpio (el lifespan cierra los
providers httpx).

## 2. Modo HTTP en loopback (FR-002/FR-003)

```bash
uv run python -m app.main --transport http
# esperado: escucha en http://127.0.0.1:8000/mcp (logs en español)
```

### 2.1 Bind loopback-only (verificación OS)

```bash
ss -ltnp | grep 8000
```

Espera: la línea muestra `127.0.0.1:8000` — NUNCA `0.0.0.0:8000` ni `[::]:8000`
sin `--host 0.0.0.0` explícito (FR-002).

### 2.2 Origin foráneo rechazado (anti DNS-rebinding, MUST spec 2025-06-18)

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Origin: https://evil.example.com' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

Espera: `403` (Origin presente y no allowlisted → rechazo, con allowlist vacío
por defecto según data-model.md).

### 2.3 Cliente sin header Origin permitido (clientes no-browser)

```bash
curl -sS -X POST http://127.0.0.1:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

Espera: respuesta 200 con `result.serverInfo` y `protocolVersion`
(puede incluir header `Mcp-Session-Id`; los requests subsecuentes lo reenvían).

## 3. Paridad de tools stdio ↔ HTTP (SC-002)

Opción A — MCP Inspector:

```bash
npx @modelcontextprotocol/inspector
# conectar a http://127.0.0.1:8000/mcp (transport: Streamable HTTP)
```

Opción B — puente mcp-remote para Claude Desktop:

```bash
npx mcp-remote http://127.0.0.1:8000/mcp
```

Espera en ambos: la lista de tools es EXACTAMENTE las 7 de siempre —
`resolve_lot_by_chip`, `resolve_lot_by_address`, `resolve_lot_by_coordinates`,
`get_lot_summary_by_chip`, `get_upl`, `consultar_normativa`,
`get_feasibility_report` — con los mismos `name`/`inputSchema` que por stdio.
Una llamada real (`resolve_lot_by_chip` con `AAA0072LRYN`) devuelve el mismo
payload JSON que por stdio.

## 4. Suite de verificación automatizada

```bash
uv run pytest -q --tb=no -p no:warnings   # exit 0 (512 baseline + nuevos de transporte)
uv run ruff check app tests               # ≤199 errores = baseline, sin E/F nuevos
```

Los tests de transporte (`tests/contract/test_transporte_http.py`) usan
`httpx.ASGITransport` sobre la app Starlette: sin puertos reales, sin red.

## 5. Fail-fast de configuración (Principio IV)

```bash
MCP_TRANSPORT=ftp uv run python -m app.main            # esperado: SystemExit con mensaje claro en español, arranque abortado
MCP_PORT=0 uv run python -m app.main --transport http  # esperado: SystemExit, puerto fuera de 1-65535
```

## 6. (Opcional, Fase 2) Túnel de demostración

```bash
cloudflared tunnel --url http://localhost:8000
# usa la URL https://<random>.trycloudflare.com/mcp como endpoint remoto
```

Espera: Claude (custom connector por URL) o `npx mcp-remote <url>/mcp` listan y
ejecutan las 7 tools sobre HTTPS público. Auth: none/bearer estático SOLO demo
(FR-006); las tools exponen únicamente datos públicos de Bogotá.

## Criterios de salida de la Fase 1

- [x] `python -m app.main` (sin flag) = comportamiento stdio idéntico a hoy.
- [x] `--transport http` sirve `/mcp` en 127.0.0.1:8000 con 7 tools (SC-002).
- [x] Origin foráneo → 403 (SC-003); sin Origin → permitido.
- [x] `ss -ltnp` loopback-only por defecto.
- [x] Config inválida → SystemExit claro (fail-fast).
- [x] pytest exit 0; ruff ≤ baseline 199.

> Verificado 2026-09-20 (Fase 1): §§1–3 y §5 manuales sobre el puerto 8123
> (bind `127.0.0.1:8123` en `ss`, 403 con `Origin: https://evil.example.com`,
> 200 con `serverInfo`/`protocolVersion` sin Origin, `tools/list` = las 7 tools);
> §4 automatizado con `tests/contract/test_transporte_http.py` (14 tests),
> suite 526 passed y ruff 199 = baseline.
