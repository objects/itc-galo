# Data Model — Feature 012: Exposición remota del servidor MCP

**Fecha**: 2026-09-19 · **Plan**: [plan.md](./plan.md) · **Especificación**: [spec.md](./spec.md)

Esta feature NO añade entidades de dominio ni tablas: introduce una única
entidad de configuración de arranque y documenta los contratos de respuesta
HTTP ya definidos en la especificación MCP.

---

## 1. Entidad `ConfigTransporte` (nueva, solo lectura de entorno)

Fuente: variables de entorno (`.env.example`, nunca valores comiteados — FR-010)
con sobreescritura por flags CLI. Validación **fail-fast al arrancar** (Principio IV).

| Campo | Variable | Flag CLI | Default | Validación |
|-------|----------|----------|---------|------------|
| `transporte` | `MCP_TRANSPORT` | `--transport` | `stdio` | ∈ {`stdio`, `http`} — otro valor → error de arranque con mensaje explícito |
| `host` | `MCP_HOST` | `--host` | `127.0.0.1` | dirección IP/hostname válido; FR-002: solo `0.0.0.0` si el operador lo pide explícitamente |
| `puerto` | `MCP_PORT` | `--port` | `8000` | entero 1–65535 |
| `origines_permitidos` | `MCP_ALLOWED_ORIGINS` | — | vacío | lista CSV de orígenes `https://…` (y `http://localhost:*` para desarrollo) |

**Reglas**:

- Con `transporte=stdio` el comportamiento es idéntico al actual (Dockerfile
  `CMD python -m app.main` sin cambio) — retrocompatibilidad total (FR-001).
- `origines_permitidos` vacío en modo HTTP: se rechaza CUALQUIER header
  `Origin` presente (403) y se permiten peticiones SIN `Origin` (clientes no
  browser: Claude Code, `mcp-remote`, Inspector, curl) — postura segura por
  defecto anti DNS-rebinding (FR-003, spec MCP 2025-06-18 MUST validar Origin).
- No hay códigos de error nuevos en la taxonomía `CodigoError` (invariante
  FR-008): los 403/401 HTTP son del transporte, no del dominio.

## 2. Contrato de respuesta del bloque MCP (sin cambios de dominio)

- Cada tool devuelve EXACTAMENTE el mismo payload JSON por stdio que por HTTP
  (SC-002). La serialización vive en `app/main.py` (las 7 tools registradas por
  `crear_servidor_mcp()`); el transporte solo enmarca JSON-RPC.
- Errores de dominio: siguen la taxonomía de 10 códigos con `construir_error`
  (Principio IV) — un `FUENTE_5XX` del proveedor ArcGIS se reporta como
  tool-result de error MCP en ambos transportes, nunca como 5xx HTTP del
  transporte (eso es responsabilidad de `consultar_query`).

## 3. Entidades derivadas del transporte (gestionadas por el SDK, no por nosotros)

| Concepto | Dueño | Nota |
|----------|-------|------|
| `Mcp-Session-Id` | SDK `StreamableHTTPSessionManager` | stateless-first (D-05); afinidad/Redis a Fase 3 (D-03) |
| `MCP-Protocol-Version` | SDK | negociado en `initialize` (2025-06-18) |
| JWT OAuth 2.1 | AS gestionado (D-01) | Fase 3; el SDK solo valida + publica `WWW-Authenticate: resource_metadata` |

## 4. Validaciones de integridad (tests)

- `initialize` sobre la app ASGI (vía `httpx.ASGITransport`) → `tools/list`
  devuelve las 7 tools con los mismos `name`/`inputSchema` que stdio.
- Petición con `Origin: https://evil.example` → 403 sin procesar el JSON-RPC.
- Petición sin `Origin` → 200 con resultado JSON-RPC válido.
- `MCP_TRANSPORT=http` con `MCP_PORT=0` o `MCP_TRANSPORT=ftp` → SystemExit con
  mensaje claro (fail-fast, sin traceback crudo).
