# Guía de producción: MCP remoto con OAuth 2.1 (F12, Fase 3)

**Feature**: [012-cloud-remote-mcp](./spec.md) · **Decisiones**: D-01 (AS gestionado),
D-02 (túnel→VPS), D-03 (un uvicorn, sin Redis), D-04 (Ollama co-local)
**Estado**: documentación operativa — la Fase 1 del repo solo entrega el modo
`--transport http` (loopback + validación `Origin`). Esta guía describe lo que el
operador hace FUERA del repo para pasar a producción con clientes que exigen
OAuth 2.1 (ChatGPT; Claude verificado).

---

## 1. Arquitectura de autorización (D-01: AS gestionado)

Tres roles según la spec de autorización MCP (2025-06-18):

| Rol | Quién lo opera | Qué expone |
|-----|----------------|------------|
| **Resource server** | este repo (el MCP en modo http) | `/mcp` protegido por Bearer JWT + metadata RFC 9728 |
| **Authorization server** | Auth0 / Okta / AWS Cognito (NO se implementa en el repo) | `/authorize`, `/token`, `/register` (DCR), metadata RFC 8414 |
| **Client** | Claude.ai / Claude Desktop / ChatGPT | redirecciones propias del producto |

**Nunca** implementes un AS embebido: OAuth 2.1 + DCR + PKCE es superficie de
seguridad crítica y mantenida; el valor del producto está en las 7 tools.

### Checklist de requisitos del flujo (verificados contra la spec MCP y OpenAI)

- [ ] `GET https://mcp.<dominio>/.well-known/oauth-protected-resource` responde
      `{"resource": "https://mcp.<dominio>", "authorization_servers": ["https://<AS>"], "scopes_supported": [...]}`
      (RFC 9728). El SDK lo publica cuando se configura `resource_server_url`.
- [ ] El AS publica `/.well-known/oauth-authorization-server` (RFC 8414) con
      `authorization_endpoint`, `token_endpoint` y `registration_endpoint`.
- [ ] **DCR** (RFC 7591) habilitado en el AS — out-of-box en Auth0/Okta para
      aplicaciones MCP; es el modo `oauth_dcr` de Claude.
- [ ] **PKCE obligatorio** en `/authorize`.
- [ ] El token hace **echo del parámetro `resource`** (RFC 8707) — exigido por
      ChatGPT; los AS gestionados modernos lo soportan (resource indicator).
- [ ] Redirect URI de ChatGPT en allowlist del AS:
      `https://chatgpt.com/connector/oauth/{callback_id}`.
- [ ] El 401 del `/mcp` incluye `WWW-Authenticate: ... resource_metadata="..."`
      (probe lazy de Claude: "Required when the server asks").

### Implementado en el repo (Fase 3, código listo)

El lado *resource server* está implementado y testeado — solo falta el AS real:

| Pieza | Archivo |
|-------|---------|
| Verificador JWT (RS256, JWKS cacheado, `iss`/`aud` RFC 8707/exp/sub, fail-closed) | `app/verificador_jwt.py` |
| Config por entorno: `MCP_AUTH_ISSUER_URL` + `MCP_AUTH_RESOURCE_URL` + `MCP_AUTH_JWKS_URL` (+`MCP_AUTH_SCOPES` CSV, opcional) — viajan juntas o nada (fail-fast) | `app/servidor_http.py` (`_resolver_auth_desde_entorno`) |
| Cableado al SDK: `AuthSettings` + `token_verifier` al constructor del MCPServer → middleware Bearer, 401 con `resource_metadata`, ruta `/.well-known/oauth-protected-resource` | `crear_servidor_mcp(..., auth, token_verifier)` en `app/main.py` + `construir_componentes_auth` |

Arranque producción (VPS/túnel con dominio):

```bash
MCP_ALLOWED_ORIGINS=https://mcp.midominio.co \
MCP_AUTH_ISSUER_URL=https://<tenant>.auth0.com/ \
MCP_AUTH_RESOURCE_URL=https://mcp.midominio.co \
MCP_AUTH_JWKS_URL=https://<tenant>.auth0.com/.well-known/jwks.json \
MCP_AUTH_SCOPES=mcp:tools \
python -m app.main --transport http --host 0.0.0.0 --port 8000
```

El SDK se encarga de: 401 `Bearer error="invalid_token", resource_metadata="…/.well-known/oauth-protected-resource"` para probe lazy de Claude; 403 `insufficient_scope`; metadata RFC 9728 pública. En el AS (Auth0) falta solo tu tenant: habilitar DCR + resource indicators y allowlist del redirect de ChatGPT (`https://chatgpt.com/connector/oauth/{callback_id}`) — ver `conectores-clientes.md` §3a.

Para Claude, OAuth no es estrictamente necesario (admite `none`/`static_headers`
beta con bearer estático); para ChatGPT sí lo es. Decide el alcance de tu
connector antes de invertir en AS.

## 2. Hosting: VPS + Docker + TLS (Fase 3, sucesor del túnel de demo)

El `Dockerfile` multi-etapa actual NO cambia (CMD stdio histórico). Para el modo
HTTP se levanta con command override:

```yaml
# docker-compose.yml de ejemplo (VPS)
services:
  mcp-bogota:
    build: .
    image: mcp-bogota-factibilidad
    command: ["python", "-m", "app.main", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
    environment:
      MAPAS_BOGOTA_APIKEY: ${MAPAS_BOGOTA_APIKEY}   # desde secret store del host, NUNCA comiteado (FR-010)
      MCP_ALLOWED_ORIGINS: https://mcp.<dominio>    # activa 403 anti-rebinding + deriva Host permitido
      OLLAMA_HOST: http://host.docker.internal:11434  # D-04: Ollama co-local
    ports: ["127.0.0.1:8000:8000"]                 # uvicorn detrás de TLS, no expuesto directo
    volumes:
      - ${HOME}/.cache/ollama:/root/.ollama:ro     # si Ollama comparte host
      - ./data:/app/data                           # corpus JSONL versionado (fuente de verdad)
      - chroma:/app/.data                          # índice derivado, regenerable
```

- **TLS + dominio**: Caddy (`reverse_proxy mcp.midominio.co → 127.0.0.1:8000`)
  o nginx; el endpoint público es `https://mcp.<dominio>/mcp`.
- **Healthcheck** sugerido: `curl -o /dev/null -sf -X POST http://127.0.0.1:8000/mcp -H 'Content-Type: application/json' -H 'Accept: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"healthcheck","version":"0"}}}'`
  (sin `Origin` → 200; con OAuth, esperar 401 bien formado con
  `WWW-Authenticate`).
- **Ollama (D-04, FR-009)**: `bge-m3` + modelo de chat deben ser alcanzables
  desde el contenedor. Si Ollama no está, el servidor ARRANCA y
  `consultar_normativa`/bloque RAG degradan con warnings (patrón F3) — nunca es
  fatal. El índice ChromaDB se regenera en el host con
  `python -m app.ingesta.corpus indexar`.
- **Sesiones (D-03)**: un solo proceso uvicorn; `Mcp-Session-Id` es en memoria
  por proceso. Multi-worker (`--workers>1`) o réplicas requieren afinidad de
  sesión/Redis — FUERA del alcance F12 hasta que la carga lo justifique.
- **Secretos**: `MAPAS_BOGOTA_APIKEY` y análogos SOLO por entorno/secret store
  del hosting (FR-010); el proyecto no carga `.env` automáticamente.

## 3. Orden de migración sugerido

1. VPS + Caddy TLS + contenedor en modo http (auth `none`) → valida contrato con
   clientes reales por URL pública (Claude custom connector).
2. Alta de app MCP en Auth0/Okta/Cognito (DCR + PKCE + resource indicators);
   config del `token_verifier` JWT en el servidor (§1).
3. Prueba SC-004: flujo completo OAuth con Claude.ai (Always required o lazy) y
   ChatGPT (connector `https://mcp.<dominio>/mcp`).
4. Opcional: solicitud al directorio de conectores de Anthropic (fuera de F12).
