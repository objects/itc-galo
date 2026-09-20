# Implementation Plan: Feature 012 — Exposición remota del servidor MCP (Cloud)

**Branch**: `012-cloud-remote-mcp` | **Date**: 2026-09-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/012-cloud-remote-mcp/spec.md`

## Summary

Añadir al servidor MCP actual (FastMCP, 7 tools, transporte stdio) un modo de
transporte **Streamable HTTP** opcional mediante un flag `--transport stdio|http`
(default `stdio`, FR-001), sirviendo el endpoint `/mcp` con validación de `Origin`
(FR-003) y bind `127.0.0.1` por defecto (FR-002), encadenando el lifespan actual de
cierre de providers con el del `http_app()` (FR-004). La exposición pública se aborda
por fases escalonadas (túnel cloudflared para demo sin OAuth; VPS + OAuth 2.1 para
producción ChatGPT), sin tocar scoring, RAG, bloques ni las 7 tools (fuera de alcance).

Investigación con fuentes citadas en [research.md](./research.md) (especificación MCP
2025-06-18/2026-07-28, FastMCP, Claude, OpenAI, Cloudflare, Docker).

## Technical Context

**Language/Version**: Python 3.11+ (requires-python `>=3.11`, sin cambio)

**Primary Dependencies**: `mcp>=1.0.0` (FastMCP ya expone `http_app()`/Streamable HTTP),
`httpx`, `pydantic` v2; `fastapi>=0.115` + `uvicorn>=0.30` YA presentes en el extra
`web` — **cero dependencias nuevas** (decisión verificada en `pyproject.toml:32-33,43-44`).

**Storage**: sin cambio — corpus JSONL versionado en `data/corpus/`, índice derivado
`.data/chroma/` regenerable con `python -m app.ingesta.corpus indexar` (FR-009).

**Testing**: pytest + `httpx.MockTransport` (hermético, sin red real ni Ollama); tests
smoke de las 7 tools; nuevos contract tests del modo HTTP (listar tools vía cliente
Streamable HTTP sobre `http://127.0.0.1:<puerto>/mcp` con `mcp` client SDK).

**Target Platform**: Linux (Docker multi-etapa actual); local/LAN en Fase 1;
demo pública vía `cloudflared` (Fase 2); VPS con TLS (Fase 3, fuera de este repo).

**Project Type**: web-service + cli (un solo paquete `app/`, sin nuevos proyectos).

**Performance Goals**: overhead de transporte despreciable; el informe sigue dominado
por Ollama (`consultar_normativa`); preview web <2 s (ya vigente, no se toca).

**Constraints**: stdio sigue siendo el DEFAULT (Dockerfile `CMD python -m app.main`
no cambia de comportamiento); invariantes FR-008: 7 tools, 23 bloques base,
`BLOQUES_EVALUABLES` 19, taxonomía 10 códigos, `calcular_score` determinista;
bind loopback por defecto; secrets solo por entorno (FR-010); Ollama debe ser
accesible donde corra el servidor o `consultar_normativa` degrada con warnings
patrón F3 (FR-009).

**Scale/Scope**: 1 flag de arranque + 1 módulo fino de servidor HTTP + ~4–8 tests;
suite baseline 512 tests exit=0, ruff 199 = baseline.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación |
|---|---|
| I. Español primero | PASS — docs, comentarios y mensajes de error en español; nombres técnicos JSON en inglés (contrato MCP). |
| II. Modularidad por providers | PASS — el transporte NO es un provider; vive en la capa de arranque (`app/main.py` + módulo nuevo `app/servidor_http.py` si hiciera falta); providers intactos. |
| III. Trazabilidad NON-NEGOTIABLE | PASS — las 7 tools devuelven los mismos dicts con `source_traces` de 5 campos; el modo HTTP solo serializa idéntico payload por otro transporte. |
| IV. Contratos de error explícitos | PASS — 403 por `Origin` foráneo explícito; errores MCP invariables (taxonomía 10); sin 5xx silenciosos. |
| V. Entrega incremental MVP | PASS — Fase 1 = solo flag + endpoint local; OAuth/túnel/VPS son fases posteriores explícitas; YAGNI aplicado (Workers port descartado). |
| Restricción técnica: "Transporte MCP por stdio" | **ENMIENDA NECESARIA (PATCH)** — se propone redactar: "Transporte MCP por stdio (por defecto) y modo Streamable HTTP opcional (F12), con validación Origin y bind loopback por defecto." Requiere aprobación del usuario (Governance). El default stdio NO cambia, así que todo lo existente (Docker, tests, AGENTS.md) sigue válido. |

**Post-Phase-1 re-check**: sin violaciones que justifiquen Complexity Tracking (0
dependencias nuevas, 0 proyectos nuevos, módulo único de arranque).

## Project Structure

### Documentation (this feature)

```text
specs/012-cloud-remote-mcp/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Informe citado §0–§8 + Decisiones formateadas (F12)
├── data-model.md        # Configuración de transporte y contratos expuestos
├── quickstart.md        # Validación ejecutable Fase 1 (local, hermética)
├── contracts/
│   └── transporte-http.md  # CLI flag + endpoint /mcp + seguridad Origin + mount ASGI
├── checklists/
│   └── requirements.md  # Checklist de calidad de la spec (exigida por implement)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created here)
```

### Source Code (repository root)

```text
app/
├── main.py                  # main(): argparse --transport stdio|http --host --port
│                            #   (default stdio = comportamiento actual intacto)
├── servidor_http.py         # NUEVO (fino): construir_app_http(servidor_lotes, ...)
│                            #   -> mcp.http_app(path="/mcp") con lifespan encadenado
│                            #   y allowlist de hosts/origins desde entorno
├── web/main.py              # SIN cambios de comportamiento; documenta opción de
│                            #   mount Mount("/mcp", ...) (US3) sin activarlo
└── (providers/, models.py, scoring.py, errores.py, cache.py, ingesta/)  # INTACTOS

tests/
├── smoke/test_main.py       # 7 tools stdio — invariante, no se toca
└── contract/test_transporte_http.py   # NUEVO: app ASGI con TestClient/transporte
    #   httpx.ASGITransport: initialize lista 7 tools idénticas al stdio,
    #   403 con Origin foráneo, bind default loopback (config), sin red real.

Dockerfile                   # SIN cambio en CMD (stdio default); Fase 2+ añade
                             #   EXPOSE/healthcheck SOLO si se activa modo http.
.env.example                 # documenta MCP_TRANSPORT/MCP_HOST/MCP_PORT/MCP_ALLOWED_ORIGINS
```

**Structure Decision**: Opción 1 — proyecto único existente (`app/` + `tests/`). El
modo HTTP se limita a un módulo de arranque nuevo (`app/servidor_http.py`) + argparse
en `main()`; ningún provider, modelo ni bloque se toca. Los tests usan
`httpx.ASGITransport` sobre la app Starlette devuelta por `http_app()` — hermético,
sin subir puertos reales en CI.

## Complejidad / Riesgos clave

1. **Lifespan anidado** (FR-004): `http_app()` debe correr el session manager Y
   nuestro `_lifespan_cerrar_providers`; el SDK FastMCP compone el lifespan del
   constructor — verificar en el contract test (tools ejecutan y providers cierran).
2. **Ollama co-local** (FR-009): en modo remoto sin Ollama, `consultar_normativa` y
   el bloque RAG del informe degradan con warnings (patrón F3) — comportamiento ya
   implementado y testeado; solo documentar para el hosting.
3. **Sesiones stateful**: `Mcp-Session-Id` es por proceso; multi-worker (uvicorn
   --workers>1) requeriría Redis — FUERA de alcance Fase 1 (stateless-first, FR-005).
4. **Enmienda constitucional**: ver tabla — pedir aprobación del usuario antes de
   commitear la implementación.
