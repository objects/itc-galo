# Conectores de clientes — MCP remoto Bogotá Factibilidad (F12)

**Actualizado**: 2026-09-22 · **Requisito**: servidor en modo HTTP (`--transport http`)
expuesto por HTTPS (túnel cloudflared para demo, VPS+TLS para producción — ver
[README](../../README.md) y [produccion-oauth.md](./produccion-oauth.md)).

Endpoint: `https://<host>/mcp` · transporte: Streamable HTTP (JSON-RPC por POST)
· tools: las 7 históricas con el mismo payload que stdio.

---

## 0. Verificación ejecutada (demo con túnel, 2026-09-22)

Servidor local `--transport http --port 8000` + `cloudflared tunnel --url
http://localhost:8000`, con `MCP_ALLOWED_ORIGINS=https://<random>.trycloudflare.com`:

| Comprobación | Resultado |
|---|---|
| `initialize` público (curl) | 200 + `Mcp-Session-Id` + `serverInfo: mcp-bogota-factibilidad` ✓ |
| `tools/list` público | las 7 tools ✓ |
| `tools/call` (datos reales) | canalizado a las fuentes; ese día Catastro/Mapas Bogotá respondieron 503 y el servidor devolvió `FUENTE_5XX` como tool-result MCP (nunca "no encontrado") — clasificación correcta de la taxonomía vía HTTP ✓ |
| Origen foráneo sin allowlist | 403 · Host de túnel no derivado: 421 ✓ (arranque con `MCP_ALLOWED_ORIGINS=<url-del-túnel>` lo autoriza) |
| `npx mcp-remote <url>/mcp` (puente Claude Desktop) | initialize + tools/list = 7 ✓ |

## 1. Claude Desktop (bridge `mcp-remote`)

En `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "bogota-factibilidad": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://<host>/mcp"]
    }
  }
}
```

Reinicia Claude Desktop y las 7 tools aparecen bajo la campana de MCP. (Verificado
hoy el puente `mcp-remote` contra el endpoint público.)

## 2. Claude.ai — custom connector (web) y Claude Code

- **Claude.ai**: Settings → Connectors → Browse connectors → **+ Add custom
  connector** → *URL*: `https://<host>/mcp`. Sin auth (demo) conéctalo tal cual;
  con OAuth activo (Fase 3) Claude hace probe → 401 con `resource_metadata` →
  flujo DCR/PKCE automático.
- **Claude Code**:

```bash
claude mcp add --transport http bogota-factibilidad https://<host>/mcp
# con OAuth/Fase 3 tras la autenticación:
claude mcp add-json bogota https://<host>/mcp \
  '{"type":"http","url":"https://<host>/mcp","headers":{"Authorization":"Bearer <token>"}}'
```

## 3. OpenAI

### 3a. Custom connector de ChatGPT (requiere OAuth 2.1 — Fase 3)

Requisito duro de OpenAI (research.md §4): OAuth 2.1 conforme a la spec MCP.
Este repo ya implementa el lado *resource server* (Fase 3): `MCP_AUTH_ISSUER_URL`,
`MCP_AUTH_RESOURCE_URL`, `MCP_AUTH_JWKS_URL` + metadata RFC 9728 publicada. Pasos:

1. Alta del AS gestionado (Auth0/Okta/Cognito) con **DCR habilitado** y soporte
   de **resource indicators (RFC 8707)**; allowlist del redirect de ChatGPT:
   `https://chatgpt.com/connector/oauth/<callback_id>`.
2. Despliegue con TLS en dominio propio + envs `MCP_AUTH_*` (ver
   [produccion-oauth.md](./produccion-oauth.md)).
3. ChatGPT → Settings → **Connectors** → **Add** → Custom: MCP *Server URL*
   `https://mcp.<dominio>/mcp`; ChatGPT descubre
   `/.well-known/oauth-protected-resource` → autoriza al usuario → consume las
   tools.

### 3b. OpenAI Responses API (funciona YA con el endpoint público, sin OAuth)

El tool `mcp` de la Responses API conecta servidores remotos server-side y acepta
`headers` estáticos — no exige OAuth. Con `OPENAI_API_KEY` en el entorno:

```python
from openai import OpenAI

client = OpenAI()  # OPENAI_API_KEY desde el entorno (nunca embebido en código)
resp = client.responses.create(
    model="gpt-5-mini",
    input="¿Qué uso de suelo permite el POT para el lote con CHIP AAA0072LRYN?",
    tools=[
        {
            "type": "mcp",
            "server_label": "bogota_factibilidad",
            "server_url": "https://<host>/mcp",
            "require_approval": "never",
            # "headers": {"Authorization": "Bearer <token-oauth>"},  # Fase 3
        }
    ],
)
print(resp.output_text)
```

### 3c. OpenAI Agents SDK

```python
from agents import Agent, Runner
from agents.mcp import MCPServerStreamableHttp

async def main():
    mcp = MCPServerStreamableHttp(
        {"url": "https://<host>/mcp", "name": "bogota_factibilidad"},
        cache_tools_list=True,
    )
    await mcp.connect()
    agente = Agent(
        name="urbano-bogota",
        instructions="Responde sobre factibilidad de lotes en Bogotá usando las tools del POT.",
        mcp_servers=[mcp],
    )
    resultado = await Runner.run(agente, "Resume el lote AAA0072LRYN")
    await mcp.cleanup()
    print(resultado.final_output)
```

Con OAuth (Fase 3) añade `{"Authorization": f"Bearer {token}"}` a `url`→`headers`
usando un token del AS gestionado.

## 4. Prueba rápida sin cliente (curl)

```bash
URL=https://<host>/mcp
curl -sS -D /tmp/h.txt -X POST "$URL/mcp" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
SID=$(grep -i '^mcp-session-id:' /tmp/h.txt | tr -d '\r' | awk '{print $2}')
curl -sS -X POST "$URL/mcp" -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -H "Mcp-Session-Id: $SID" -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'
curl -sS -X POST "$URL/mcp" -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -H "Mcp-Session-Id: $SID" -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
# Con OAuth activo (Fase 3), añade -H "Authorization: Bearer <token>" a todo.
```

## 5. Notas de seguridad de la demo

- La URL `trycloudflare.com` es **aleatoria y temporal** (muere al parar
  `cloudflared`); solo datos públicos read-only; auth `none` aceptable SOLO demo
  (FR-006). Para compartir de forma permanente: VPS + OAuth 2.1 (§3a).
- Cambiar de hostname de túnel ⇒ reiniciar el servidor con el nuevo
  `MCP_ALLOWED_ORIGINS` (si no, las peticiones por túnel reciben 421/403).
