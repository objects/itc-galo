# Research — Servidor MCP remoto (Cloud) para mcp-bogota-factibilidad

**Fecha:** 2026-09-19 · **Estado:** investigación web con citas primarias · **Feature:** 012-cloud-remote-mcp

## 0. Contexto del servidor actual

- `app/main.py` construye un `FastMCP` (paquete `mcp>=1.0.0`) vía `crear_servidor_mcp()`, que registra
  las **7 tools** (`resolve_lot_by_chip`, `resolve_lot_by_address`, `resolve_lot_by_coordinates`,
  `get_lot_summary_by_chip`, `get_upl`, `consultar_normativa`, `get_feasibility_report`).
- Transporte actual: **stdio** (un proceso por cliente). `Dockerfile` multi-etapa con
  `CMD ["python", "-m", "app.main"]`.
- Dependencias locales relevantes: **Ollama** (`bge-m3` + chat) para el RAG normativo y
  `.data/chroma` (índice local regenerable). Cualquier hosting remoto debe poder alcanzar Ollama.

## 1. Especificación MCP — transporte Streamable HTTP

Fuente: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports

- La especificación define dos transportes estándar: **stdio** y **Streamable HTTP** (este último
  reemplazó al antiguo HTTP+SSE de 2024-11-05).
- Un servidor remoto es un **proceso independiente que atiende múltiples clientes** y expone **un
  único endpoint HTTP** (el "MCP endpoint", p. ej. `https://example.com/mcp`) que soporta:
  - `POST`: cada mensaje JSON-RPC del cliente es una petición POST (respuesta JSON o stream SSE).
  - `GET`: stream opcional para mensajes servidor→cliente.
- **Seguridad obligatoria/recomendada:** validar el header `Origin` en toda conexión (protección
  DNS-rebinding; responder 403 si es inválido); en despliegues locales bindear **solo 127.0.0.1**;
  implementar autenticación en todas las conexiones.
- **Sesiones:** el servidor MAY asignar `Mcp-Session-Id` en la respuesta de `initialize`; los
  clientes MUST reenviarlo. El header `MCP-Protocol-Version` (p. ej. `2025-06-18`) es obligatorio
  en peticiones subsecuentes.
- La versión 2025-11-25 mantiene la misma forma. El **borrador DRAFT/2026-07-28** simplifica:
  elimina el GET stream endpoint y las sesiones a nivel de protocolo (solo POST; notificaciones por
  `subscriptions/listen`) — conviene exponer el servidor de forma **stateless** para compatibilidad
  futura.
- Autorización: https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization define
  el framework **OAuth 2.1** para transportes HTTP.

## 2. FastMCP / SDK Python — cómo servir HTTP

Fuentes: https://gofastmcp.com/deployment/running-server · https://gofastmcp.com/deployment/http.md ·
https://pypi.org/project/mcp/1.8.0

- **Opción mínima (una línea):** `mcp.run(transport="http", host="0.0.0.0", port=8000)` → servidor
  Streamable HTTP en `http://host:8000/mcp`. Múltiples clientes concurrentes (a diferencia de stdio).
  El transporte SSE legacy NO debe usarse en proyectos nuevos.
- **Opción producción (ASGI):** `app = mcp.http_app()` devuelve una app Starlette real →
  `uvicorn app:app --host 0.0.0.0 --port 8000`; permite múltiples workers, middleware, logging y
  integración con infraestructura existente. Path configurable: `mcp.http_app(path="/api/mcp")`.
- **Montar en una app FastAPI/Starlette existente** (nuestro caso: coexistir con la web F5):
  `Mount("/mcp", app=mcp_app)` — es **obligatorio propagar el lifespan** de `http_app()` al app
  padre (los lifespans anidados no se reconocen), o el `session_manager` no arranca. Patrón SDK:
  `FastAPI(lifespan=mcp.streamable_http_app().lifespan)` + `app.mount(...)`.
- **Protección Host/Origin opt-in:** `mcp.run(transport="http", host_origin_protection=True,
  allowed_hosts=["mcp.example.com"], allowed_origins=["https://app.example.com"])`.
  Redis para sesiones distribuidas; CORS solo aplica a clientes browser sobre Streamable HTTP.
- CLI: `fastmcp run server.py` / `mcp run server.py --transport streamable-http`.
- **Consecuencia para el repo:** hoy `main.py` corre `mcp.run()` (stdio). La conversión es añadir un
  flag (`--transport http`) o una segunda entrada `python -m app.main --http`; el lifespan del
  `http_app` debe encadenarse al cierre actual de los `httpx.AsyncClient` de los providers.

## 3. Cliente Claude (Anthropic)

Fuentes: https://claude.com/docs/connectors/custom/remote-mcp ·
https://claude.com/docs/connectors/building/authentication ·
https://platform.claude.com/docs/en/agents-and-tools/mcp-connector ·
https://claude.com/docs/connectors/directory

- **Custom connector remoto:** basta la URL pública (`https://mcp.example.com/mcp`).
  Free/Pro/Max: Customize → Connectors → Add custom connector; Team/Enterprise: Organization
  settings → Connectors.
- **Modos de autenticación del cliente:** "Always required" (OAuth por usuario), "Required when the
  server asks" (lazy: 401 → tarjeta Connect inline) y "None" (sin auth; API key por header
  estático). Tipos formales: `oauth_dcr` (Dynamic Client Registration, RFC 7591, soportado
  out-of-box), `oauth_cimd`, `oauth_anthropic_creds`, `custom_connection`, `static_headers` (beta,
  bearer/API key la define un admin de organización) y `none`.
- **Claude Desktop** sigue soportando stdio local por archivo de configuración; para consumir un
  endpoint remoto sin OAuth completo se usa el puente **`npx mcp-remote <url>`** como `command`
  (patrón de los demos de Cloudflare). **Claude Code:** `claude mcp add --transport http nombre
  https://.../mcp` o `add-json {"type":"http","url":...,"headers":{"Authorization":"Bearer ..."}}`.
- **Flujo OAuth lazy:** probe `/mcp` → 401 con `WWW-Authenticate` →
  `/.well-known/oauth-protected-resource` (RFC 9728) → `/.well-known/oauth-authorization-server`
  (RFC 8414) → DCR `/register` → `/authorize` con PKCE → callback `claude.ai/api/mcp/auth_callback`
  → intercambio de token.
- **Messages API MCP connector** (beta, header `mcp-client-2025-11-20`): la API de Claude conecta
  servidores remotos por sí sola (`type:"url"` + `authorization_token`); exige servidor público
  HTTP, nunca stdio local.
- **Directorio de conectores:** listado público (verificado/community) que requiere cumplir la
  Software Directory Policy; la verificación es revisión ligera, no auditoría de seguridad.

## 4. Cliente OpenAI / ChatGPT

Fuentes: https://developers.openai.com/apps-sdk/build/auth ·
https://platform.openai.com/docs/guides/agents/mcp

- El **connector de ChatGPT exige OAuth 2.1 conforme a la spec de autorización MCP**: tres roles —
  resource server (nuestro MCP), authorization server (Auth0/Okta/Cognito/custom) y client (ChatGPT).
- Requisitos concretos:
  - `GET /.well-known/oauth-protected-resource` en el host del MCP (o advertised en el 401 con
    `WWW-Authenticate`) devolviendo `{"resource","authorization_servers","scopes_supported"}`.
  - El AS publica `/.well-known/oauth-authorization-server` (o `/.well-known/openid-configuration`)
    con `authorization_endpoint`, `token_endpoint` y `registration_endpoint` (DCR).
  - **PKCE obligatorio**; el token debe hacer echo del parámetro `resource` (RFC 8707).
  - El redirect URI del connector es `https://chatgpt.com/connector/oauth/{callback_id}` (allowlist
    en el AS).
- El **OpenAI Agents SDK** consume MCP server-side por connector con las mismas expectativas de
  endpoint remoto + auth.
- Conclusión: **para ChatGPT no hay atajo sin OAuth 2.1 real** (a diferencia de Claude, que admite
  `none`/`static_headers` para casos de uso limitados).

## 5. Opciones de hosting

Fuentes: https://developers.cloudflare.com/agents/guides/remote-mcp-server ·
https://github.com/cloudflare/ai/blob/main/demos/remote-mcp-authless/README.md ·
https://docs.docker.com/reference/cli/docker/mcp/gateway/run

- **Cloudflare Workers:** plantilla oficial `npm create cloudflare@latest -- my-mcp
  --template=cloudflare/ai/demos/remote-mcp-authless` → MCP **stateless** en
  `*.workers.dev/mcp`, sin auth, compatible con clientes 2025 y con el borrador 2026-07-28; auth
  opcional vía Cloudflare Access o IdP externo. `createMcpHandler()` stateless es el patrón
  recomendado (McpAgent/Durable Objects queda para stateful). Prueba con AI Playground
  (https://playground.ai.cloudflare.com/). **PERO:** Workers ejecuta TypeScript; nuestro servidor es
  Python pesado (chromadb + httpx + Ollama local) → portar NO es trivial; Workers solo serviría
  como proxy delgado, no como el servidor.
- **Cloudflare Tunnel (cloudflared):** expone un servicio local a internet con HTTPS público sin
  abrir puertos: `cloudflared tunnel --url http://localhost:8000` (URL temporal gratis vía
  trycloudflare) o túnel gestionado con hostname propio. **La ruta más barata para dar demo/piloto
  al servidor Python existente.**
- **Docker MCP Gateway:** `docker mcp gateway run --transport streaming --port N` empaqueta
  servidores MCP con token de auth (`MCP_GATEWAY_AUTH_TOKEN`, anti DNS-rebinding), bloqueo de
  secrets y límites de recursos. Útil como flota local, no como exposición pública con OAuth.
- **VPS + Docker (producción completa):** `uvicorn app:app --host 0.0.0.0 --port 8000` detrás de un
  reverse proxy TLS (Caddy/nginx) con dominio propio; el `Dockerfile` multi-etapa actual solo
  cambia el `CMD` al modo HTTP, añade `EXPOSE 8000` y healthcheck sobre `/mcp`. OAuth 2.1 con AS
  gestionado (Auth0) o embebido (FastAPI + RFC 9728/8414/7591/8707 + PKCE).

## 6. Matriz comparativa

| Opción | Esfuerzo código | Acceso Claude Desktop | Acceso Claude.ai (web) | Acceso ChatGPT | Ollama | Coste |
|---|---|---|---|---|---|---|
| stdio local (hoy) | 0 | ✔ directo | ✘ | ✘ | local | 0 |
| Streamable HTTP en LAN | ~1 flag | ✔ vía `mcp-remote` | ✘ (sin URL pública) | ✘ | local | 0 |
| Túnel Cloudflare | ~1 flag + cloudflared | ✔ | ✔ (modo none/static) | parcial (OAuth mínimo no cumple) | local (túnel lo alcanza) | gratis |
| VPS Docker + OAuth 2.1 | modo HTTP + AS + TLS | ✔ | ✔ connector verificado | ✔ (exige OAuth 2.1) | debe correr o ser alcanzable en el VPS | VPS |
| Cloudflare Workers | port completo a TS | ✔ | ✔ | ✔ | ✘ (no hay Ollama en Workers) | free tier |

## 7. Recomendación escalonada

1. **Paso 1 (día):** modo HTTP al servidor FastMCP existente
   (`mcp.run(transport="http", host="127.0.0.1", port=8000)` detrás del flag `--transport`),
   validación de `Origin`, sin tocar las 7 tools ni la lógica. Claude Desktop local consume vía
   `npx mcp-remote http://127.0.0.1:8000/mcp`.
2. **Paso 2 (piloto público):** `cloudflared tunnel` → URL HTTPS pública; auth `none` para demo o
   `static_headers` bearer (beta de Claude) para uso personal.
3. **Paso 3 (producción):** VPS con el Dockerfile en modo HTTP + Caddy TLS + dominio + OAuth 2.1
   (AS gestionado tipo Auth0 con DCR + PKCE + RFC 8707) → connector verificable en Claude y
   admisible por ChatGPT. Ollama (bge-m3 + chat) debe convivir en el VPS o exponerse en red privada;
   el índice ChromaDB se regenera con `python -m app.ingesta.corpus indexar`.
4. **Descartado:** port a Cloudflare Workers (TypeScript) mientras el pipeline dependa de
   ChromaDB/Ollama en Python.

## 8. Riesgos y limitaciones detectadas

- **Statefulness:** `Mcp-Session-Id` implica afinidad de sesión; el borrador 2026-07-28 empuja a
  stateless → preferir diseño sin estado por request para no reescribir luego.
- **Ollama como cuello de botella remoto:** `consultar_normativa` y el bloque RAG del informe
  requieren un LLM; sin Ollama accesible el servidor degrada (evidencia vacía + warnings) — el
  hosting remoto debe incluirlo o aceptar degradación RAG.
- **Credenciales:** `MAPAS_BOGOTA_APIKEY` y variables de entorno deben migrar a secret store del
  ASGI/VPS (hoy se leen del entorno; el proyecto no carga `.env`).
- **Seguridad:** la spec exige validar `Origin` y auth en TODAS las conexiones HTTP; exponer sin
  OAuth un servidor que consulta APIs de catastro es aceptable solo para demo (las tools son
  read-only, sin datos personales de usuario).

## 9. Decisiones formateadas (F12) — resolución de las 4 pendientes de spec.md

### D-01 Authorization Server: gestionado, no embebido
- **Decisión**: para la Fase 3 (producción OAuth 2.1) usar un AS gestionado (Auth0 / Okta / AWS Cognito) fronting el recurso MCP; NO implementar un AS embebido en el repo.
- **Racional**: OAuth 2.1 + DCR (RFC 7591) + PKCE + metadata RFC 9728/8414 es superficie de seguridad crítica y mantenida; el valor del producto está en las 7 tools, no en ser IdP. FastMCP/SDK solo necesita validar JWT y publicar `WWW-Authenticate` con `resource_metadata`.
- **Alternativas descartadas**: AS embebido (auto-generar tokens: más superficie, más riesgo, fuera de MVP); sin auth en producción (inadmisible para ChatGPT y para la spec MCP "auth in all connections").
- **Fase 1 no afectada**: sin OAuth local; solo Origin validation + loopback.

### D-02 Hosting demo vs producción: túnel primero, VPS después
- **Decisión**: Fase 2 = Cloudflare Tunnel (`cloudflared tunnel --url http://localhost:8000`) sobre el servidor Python local, auth `none`/bearer estático, solo demo. Fase 3 = VPS con Dockerfile en modo HTTP + Caddy TLS + AS gestionado (D-01).
- **Racional**: el túnel es gratis, sin puertos abiertos ni IP pública, y valida el contrato Streamable HTTP con clientes reales (Claude custom connector vía URL, mcp-remote) antes de invertir en infraestructura.
- **Alternativas descartadas**: Cloudflare Workers port (TypeScript — descartado, pipeline Python ChromaDB/Ollama); exponer el puerto local directamente (DNS-rebinding/TLS manual).

### D-03 Topología de proceso: un uvicorn, sin Redis
- **Decisión**: Fases 1–2 corren UN proceso uvicorn con sesiones en memoria por proceso; sin Redis ni multi-worker con afinidad. El contenedor Docker existente gana un CMD opcional en modo HTTP (Fase 3), no un orquestador nuevo.
- **Racional**: stateless-first (D-05 abajo) minimiza el problema; la carga esperada (demo/piloto, tools read-only) no justifica infraestructura distribuida; FastMCP soporta `event_store`/Redis pero es deuda prematura.
- **Alternativas descartadas**: `uvicorn --workers N` con sesiones compartidas (requiere Redis: fuera de alcance); k8s/sidecars (excesivo).

### D-04 Política de `consultar_normativa`/Ollama en remoto
- **Decisión**: Ollama (`bge-m3` + chat) debe co-localizarse con el servidor (mismo host/VPS). Si no está accesible, el servidor ARRANCA y responde con la degradación RAG ya implementada (evidencia vacía + warnings, patrón F3/FR-009 de la spec) — NUNCA es un error fatal.
- **Racional**: es el comportamiento actual del provider `normativa.py` (healthcheck GET /api/tags barato, degradación por bloque); exponer Ollama en red pública es un riesgo innecesario; las otras 6 tools no lo necesitan.
- **Alternativas descartadas**: bloquear el arranque sin Ollama (rompe FR-009 y el patrón de degradación); API LLM externa (cambio de proveedor fuera de alcance F12).

### D-05 (derivada de §8) Statelessness como defecto de diseño
- **Decisión**: priorizar flujo sin `Mcp-Session-Id` persistente cuando el cliente lo permita; documentar que sesiones stateful quedan a Fase 3 con afinidad.
- **Racional**: el borrador 2026-07-28 elimina el stream GET y las sesiones a nivel de protocolo; diseñar stateless hoy evita reescribir mañana.
