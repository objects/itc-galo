# Implementation Plan: 011-catalogo-extensible-wizard-v2

**Branch**: `011-catalogo-extensible-wizard-v2` | **Date**: 2026-09-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/011-catalogo-extensible-wizard-v2/spec.md` (3 US: P1 catálogo extensible, P2 wizard v2 preview persistente, P3 persistencia)

## Summary

F11 combina dos objetivos sin romper el contrato existente (7 tools, 23 bloques / 19 evaluables, 486 tests, trazabilidad 5 campos HEAD 9641504):

1. **Catálogo extensible Datos Abiertos**: hacer declarativa la adición de capas ArcGIS REST temáticas al informe. Hoy añadir capa toca `app/main.py:get_feasibility_report` (orquestación), `app/models.py`, `app/scoring.py` y `app/web/templates/proyecto.html`. Con el catálogo, la extensión es 1 `CapaConfig` (en `app/providers/arcgis_utils.py:32`) + 1 test `MockTransport` con 5 campos de traza. Incluye how-to de 3 pasos y preserva `BLOQUES_EVALUABLES` baseline. Habilita completar las 10 temáticas de `20260809-01-perplexity.md:728-743` y los 4 pilares de `20260831-01-googleai:8-35` sin acoplar lógica al orquestador.

2. **Wizard v2 validación guiada + preview persistente**: el flujo prefactibilidad actual (`GET /` → `POST /proyectos` → 303) es de un solo paso. F11 mantiene `POST /proyectos/preview` ligero ya en `app/web/main.py:222-290` (preview sin 23 bloques, World fallback) y los 5 campos opcionales persistidos (`uso_previsto/escala_m2/presupuesto_rango/horizonte_meses/aversion_riesgo` con migración `PRAGMA table_info` ya en `app/web/db.py`), pero añade validación inline guiada (HTML5 + server 400 con help text por campo), preview persistente entre pasos (client-side `hx-include`/campos ocultos sin sesión servidor) y reordenamiento menor si aporta lógica inversión (identificar+preview → interrogar → informe), manteniendo identidad Bogotá Reverdece / Leaflet vendorizado / cache LRU+TTL.

El plan preserva preview ligero y 5 campos como `Form` opcionales, no crea tool MCP nueva, no toca scoring determinista `calcular_score`, y deja los 7 diferidos de `specs/012-futura-ampliacion/spec.md` (scraping vivo, Node, token fuera CapaConfig, rate limiting, PDF, motores a fondo, background jobs) fuera de alcance.

## Technical Context

**Language/Version**: Python 3.11 (requires-python `>=3.11`, Docker `python:3.11-slim`, `pyproject.toml` 77L)

**Primary Dependencies**: `mcp>=1.0.0` (FastMCP), `httpx>=0.27` + `httpx.MockTransport` en tests, `pydantic>=2.7`, `chromadb>=1.0`, `beautifulsoup4`, `ollama` (embed `bge-m3` + chat `qwen3:8b`), `shapely>=2`, `fastapi>=0.110` + `uvicorn` + `jinja2` + `python-multipart` (extra `web`), `pypdf/python-docx/pdfplumber` (extra `ingesta`). Vendorizados: `HTMX 2.0.4` + `Leaflet 1.9.x` + `Fraunces` woff2 en `app/web/static/`

**Storage**: SQLite stdlib `app/web/db.py:ProyectoRepositorio` → `.data/proyectos.db` (migración aditiva `PRAGMA table_info` + `ALTER TABLE` ya en F5/F11-wizard, 16 cols tras 5 campos wizard), ChromaDB `PersistentClient` → `.data/chroma` (colección `decreto_555_2021`, schema v3 `tema/estado/fecha_vigencia`), corpus JSONL `data/corpus/{decreto_555_2021.jsonl,actos_modificatorios/*.jsonl,mercado/*.jsonl}` + `.sha256`, `.data/` gitignored, `data/` versionado

**Testing**: `pytest` + `pytest-asyncio` (77L `[tool.pytest.ini_options]`), `httpx.MockTransport` hermético (sin red real ni Ollama vivo, `tests/conftest.py` fixtures `CHIP_VALIDO=AAA0072LRYN`), `FakeEmbeddingFunctionPorPrimerToken` para RAG híbrido BM25+RRF k=60, `fastapi.testclient.TestClient` para web, `chromadb OllamaEmbeddingFunction` solo en `NormativaProvider` real (stub `NormativaProviderStub:498-522` por defecto en conftest tras Todo22 harness), 486 tests collected 0 errors `14.4s` (HEAD 0850124 → 9641504 wizard)

**Target Platform**: Linux server, Docker multi-etapa `python:3.11-slim` `USER mcp` `CMD python -m app.main` (stdio), web `python -m app.web.main` `127.0.0.1:8000`, `MAPAS_BOGOTA_APIKEY` opcional con fallback `geocode.arcgis.com/World/GeocodeServer` (Sin `CREDENCIAL_FALTANTE` en preview)

**Project Type**: Python library `mcp-bogota-factibilidad` v0.1.0 (`pyproject.toml:packages app,app.providers,app.web`) con servidor MCP stdio (7 tools: 4 F1 + 2 F2 + 1 F3) + web FastAPI-HTMX (5 rutas + `POST /proyectos/preview` ligero)

**Performance Goals**:
- `POST /proyectos/preview` <2s (cache hit <100ms LRU 128 TTL 3600 via `app/cache.py`), sin 23 bloques ni Ollama
- `GET /proyectos/{id}` 23 bloques (17 loop + 6 separadas) con 5 campos traza por bloque, `llm_ready_summary` presente
- Suite `uv run pytest -q` 486 → ≥486 0 failed, `docker build` sin regresión, `ruff check` sin E/F nuevo (deuda 192 E501)

**Constraints**:
- 7 tools MCP invariante (smoke `tests/smoke/test_main.py:7-27` assert exacto 7), 23 bloques base / 19 evaluables baseline no decrecible (`app/scoring.py:94-114` BLOQUES_EVALUABLES 19, `app/models.py:1092` `market_dynamics` incluido)
- Trazabilidad 5 campos NON-NEGOTIABLE (Principio III: `source_name/layer_id/service_url/data_vigencia/query_timestamp` en `app/models.py:23-34` `SourceTrace` + `app/main.py:139` CAMPOS_TRAZA)
- Taxonomía 10 códigos `app/errores.py:20-32`, degradación por bloque (5xx → `no_encontrado` + `BLOQUE_DEGRADADO` no fatal, UPL ausente → `upl:null` + warning)
- Local-first 100% tests herméticos sin red/Ollama vivo, `asyncio.to_thread` para ChromaDB, `asyncio.gather(return_exceptions=True)` por bloque F6/F7
- Constitución v1.0.0 5 principios: I Español primero, II Modularidad por providers, III Trazabilidad (NON-NEGOTIABLE), IV Fail Fast Fail Loud, V MVP first; scoring `calcular_score` puro determinista base 50 clamp [0,100], sin tocar `calcular_score` en F11 salvo regla explícita

**Scale/Scope**: 10 features previas (001-010) + Fase 3 + Fase 5 + wizard prefactibilidad 3 pasos (HEAD 9641504 5 files wizard: `POST /proyectos/preview:222-290`, 5 campos wizard `db.py:16 cols`, `index.html` details plegable 5 campos, `proyecto.html` 17 loop + `market_dynamics` fix H-01), catálogo actual 23 bloques con 15+ capas ArcGIS (`catastro/*`, `espaciopublico/*`, `Mapa_Referencia:13`, `salud/educacion/recreacion`, `ordenamientoterritorial:0`, `SDP 2+14` EPSG:4686). F11 no añade fuentes vivas nuevas, solo habilita registro declarativo

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Check | Estado | Justificación |
|-----------|-------|--------|---------------|
| I Español primero | Spec/plan/docs en español, tools/campos JSON en inglés donde exige contrato | ✅ PASS | Spec 011 en español, campos `source_name/layer_id` preservados |
| II Modularidad por providers | Catálogo usa `CapaConfig` en `arcgis_utils.py` + `construir_params_punto` genérico, reutiliza `app/cache.py`, no mezcla parsing entre fuentes | ✅ PASS | Cada bloque es un provider aislado; `app/main.py:get_feasibility_report` solo itera catálogo |
| III Trazabilidad NON-NEGOTIABLE | Todo bloque nuevo con 5 campos, sin mezclar vigencias, `llm_ready_summary` determinista | ✅ PASS | FR-002/FR-015 exigen 5 campos por bloque + `data_vigencia` independiente |
| IV Fail Fast Fail Loud | Degradación por bloque, taxonomía 10 códigos, `DIRECCION_MAX_CHARS`, `PATRON_CHIP`, `MAPAS_BOGOTA_APIKEY` opcional con fallback World sin `CREDENCIAL_FALTANTE` en preview | ✅ PASS | FR-005 World fallback sin clave, edge case 5xx → `BLOQUE_DEGRADADO` |
| V MVP first | YAGNI: catálogo declarativo mínimo (1 config + 1 test), wizard client-side `hx-include` sin `wizard_drafts` tabla, no auth/rate limiting, no token fuera CapaConfig | ✅ PASS | `specs/012-futura-ampliacion/spec.md` reserva 7 diferidos (scraping vivo, Node, token param, rate limiting, PDF, motores a fondo, background jobs) |

Post-Phase 1 re-check: sin violaciones nuevas; `specs/012` no se activa (Reservada).

## Project Structure

### Documentation (this feature)

```text
specs/011-catalogo-extensible-wizard-v2/
├── plan.md              # This file (/speckit.plan output)
├── research.md          # Phase 0 output (resuelve catálogo vs wizard, hx-include, PRAGMA, validación)
├── data-model.md        # Phase 1 output (Proyecto/CapaConfig/PreviewLote/BloqueInforme)
├── quickstart.md        # Phase 1 output (validación runnable: preview, wizard, catálogo, 486 tests)
├── contracts/           # Phase 1 output (preview, catalog, wizard contracts)
│   ├── preview.md
│   ├── catalog.md
│   └── wizard.md
└── tasks.md             # Phase 2 output (/speckit.tasks - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
app/
├── main.py                 # Servidor MCP 7 tools; get_feasibility_report itera catálogo (FR-001)
├── models.py               # SourceTrace 5 campos, BloqueInforme, Proyecto con 5 campos wizard
├── scoring.py              # BLOQUES_EVALUABLES 19 baseline intacto (FR-003)
├── cache.py                # LRU+TTL por CHIP reutilizado en preview (FR-014)
├── utilidades.py           # PATRON_CHIP, _primer_texto, helpers compartidos
├── financiero.py/tecnico.py/geom.py  # Motores puros Fase2/3 (no tocar)
├── providers/
│   ├── arcgis_utils.py     # CapaConfig:32 + construir_params_punto:46 + how-to (FR-004)
│   ├── arcgis.py           # Capas temáticas 23 bloques base + catálogo extensible
│   ├── mapas_bogota.py     # catalogopmb + World fallback geocode.arcgis.com
│   ├── sdp.py              # SDP 2+14 EPSG:4686 (ya en catálogo)
│   ├── mercado.py          # F10 market_dynamics (referencia patrón catálogo)
│   └── normativa.py        # RAG híbrido BM25+RRF k=60 schema v3
├── ingesta/
│   ├── corpus.py           # CLI descargar/indexar/acto/mercado
│   └── mercado.py          # F10 corpus
└── web/
    ├── main.py             # 5 rutas + POST /proyectos/preview:222-290 (FR-005/006)
    ├── db.py               # ProyectoRepositorio PRAGMA table_info + 5 cols wizard (FR-010)
    └── templates/
        ├── index.html      # details plegable 5 campos + help text + hx-include (FR-007/008)
        ├── proyecto.html   # 17 loop + market_dynamics fix H-01 (FR-015)
        └── base.html       # HTMX 2.0.4 + Leaflet vendorizado (FR-013)

tests/
├── contract/               # 43 files + _f3_shared.py; preview, wizard, catálogo, get_feasibility
│   └── test_preview|wizard|catalogo|get_feasibility|...
└── smoke/
    ├── test_main.py        # 2 tests assert 7 tools exacto
    └── test_web.py         # 4 tests rutas + estáticos

data/corpus/  versionado (decreto_555_2021.jsonl + actos + mercado/*.jsonl + .sha256)
.data/        gitignored (chroma, proyectos.db)
```

**Structure Decision**: Single Python project con `app/providers` modular (Principio II); `app/ingesta` CLI no runtime MCP; `app/web` FastAPI-HTMX con SQLite stdlib; tests herméticos `MockTransport`. Se reutiliza estructura existente de 010, sin monorepo Node.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| N/A | Sin violaciones | — |
