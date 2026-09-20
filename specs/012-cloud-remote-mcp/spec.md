# Feature 012 — Exposición remota del servidor MCP (Cloud)

**Estado:** borrador de investigación (2026-09-19). No planificar implementación hasta que el
usuario la active. Ver `research.md` para las fuentes primarias de cada afirmación.

## Resumen

El servidor `mcp-bogota-factibilidad` expone hoy sus 7 tools MCP por **stdio** (un proceso por
cliente, sin acceso por red). Esta feature lo convierte en un **servidor MCP remoto** accesible
vía HTTPS con el transporte estándar **Streamable HTTP**, consumible desde Claude Desktop,
Claude.ai (custom connector), ChatGPT y cualquier agente compatible con MCP.

## Conexión remota

### Requisitos funcionales

- **FR-001.** El servidor debe poder ejecutarse en modo HTTP Streamable exponiendo un único
  endpoint `/mcp` (POST por mensaje JSON-RPC), sin eliminar el modo stdio actual (flag
  `--transport stdio|http`; default `stdio` para no romper Docker/CLI existentes).
- **FR-002.** En modo HTTP debe bindear `127.0.0.1` por defecto y solo abrirse a la red cuando el
  operador lo pida explícitamente (host/puerto configurables por variables de entorno).
- **FR-003.** Debe validar el header `Origin` en todas las conexiones HTTP (403 si no está en la
  allowlist), según la especificación MCP 2025-06-18 (protección DNS-rebinding).
- **FR-004.** El ciclo de vida del transporte HTTP (session manager) debe encadenarse al lifespan
  actual que cierra los `httpx.AsyncClient` de los providers; si se monta junto a la web F5,
  propagar el lifespan anidado explícitamente.
- **FR-005.** Diseño **stateless por request** en lo posible (el borrador de protocolo
  2026-07-28 elimina sesiones a nivel de protocolo); si se usa `Mcp-Session-Id`, documentar la
  afinidad de sesión para despliegues multi-worker (Redis).
- **FR-006.** Etapa de demo/piloto: exposición mediante Cloudflare Tunnel (`cloudflared`) o
  equivalente, con autenticación `none` (demo) o bearer estático — aceptable solo porque las tools
  son read-only sobre datos públicos.
- **FR-007.** Etapa de producción: OAuth 2.1 conforme a la spec de autorización MCP —
  `/.well-known/oauth-protected-resource` (RFC 9728), AS con `/.well-known/oauth-authorization-server`
  (RFC 8414), DCR (RFC 7591), PKCE obligatorio y echo del parámetro `resource` (RFC 8707). Requisito
  indispensable para el connector de ChatGPT; Claude.ai lo admite como "Always required" o lazy.
- **FR-008.** Las 7 tools, los 23 bloques base, `BLOQUES_EVALUABLES` (19), la taxonomía de 10
  códigos de error y el scoring determinista permanecen INVARIANTES — la conversión de transporte
  no cambia el contrato de ninguna tool.
- **FR-009.** El despliegue remoto debe garantizar accesibilidad a Ollama (embeddings `bge-m3` +
  modelo de chat) o degradar conscientemente el RAG normativo (evidencia vacía + warnings, patrón
  F3); el índice ChromaDB se regenera en el host con `python -m app.ingesta.corpus indexar`.
- **FR-010.** `MAPAS_BOGOTA_APIKEY` y demás configuración se inyectan por entorno/secret store del
  hosting; nunca se comitean.

### Historias de usuario resumidas

1. **US1 (demo):** un usuario comparte `https://<tunel>.trycloudflare.com/mcp` y la añade a Claude
   Desktop vía `npx mcp-remote` o a Claude.ai como custom connector sin auth; las 7 tools
   responden igual que por stdio.
2. **US2 (producción):** un operador despliega el contenedor en un VPS con TLS + OAuth 2.1; los
   usuarios de Claude y ChatGPT se autentican con su identidad y consumen el servidor.
3. **US3 (coexistencia web):** la app FastAPI de prefactibilidad (F5) y el endpoint MCP conviven en
   un mismo proceso uvicorn montando `mcp.http_app()` bajo `/mcp`.

### Criterios de éxito

- **SC-001.** `pytest` completo en verde (≥512) con el modo HTTP añadido; smoke existente de 7
  tools invariante.
- **SC-002.** Un cliente MCP de referencia (Claude Desktop con `mcp-remote`, o Inspector) lista y
  ejecuta las 7 tools contra `http://127.0.0.1:8000/mcp` con resultados idénticos a stdio.
- **SC-003.** Con `Origin` foráneo el servidor responde 403; con bind default nothing escucha
  fuera de loopback (verificable con `ss -ltnp`).
- **SC-004.** (Etapa producción) el flujo OAuth completo funciona contra un AS real y ChatGPT
  acepta el connector.

### Fuera de alcance

- Portar el servidor a Cloudflare Workers/TypeScript (descartado en `research.md` §5 por
  ChromaDB/Ollama).
- Multiusuario con facturación, límites de cuota por plan, o listado en el directorio de
  conectores de Anthropic.
- Cambios a scoring, RAG o a los 23 bloques del informe.

## Decisiones pendientes para activar la feature

1. Elegir AS: gestionado (Auth0/Cognito) vs embebido en FastAPI (esfuerzo/mantenimiento).
2. Hosting destino: VPS propio vs túnel temporal para demo interna.
3. ¿MCP y web F5 en un mismo proceso (mount ASGI) o contenedores separados?
4. Política de exposición de `consultar_normativa` (depende de Ollama: el único bloque que no
   puede correr sin un LLM local en el host).
