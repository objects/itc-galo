# Quickstart — F11 Catálogo Extensible + Wizard v2

**Feature**: `011-catalogo-extensible-wizard-v2` | **Branch**: `011-*` | **Baseline**: 486 tests, HEAD 9641504, 23 bloques 19 evaluables

## Prerrequisitos

```bash
uv sync --extra web --extra dev
# opcional Ollama para RAG real; tests usan MockTransport/FakeEmbedding
python -m app.ingesta.corpus indexar  # si .data/chroma vacío
```

## Escenarios de validación end-to-end

### S1 — Catálogo extensible (US1 P1, ≤30min how-to)

1. Definir `CapaConfig(service_url="https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/catastro/prueba/MapServer", layer_id="99", source_name="catastro/prueba")` en test con `httpx.MockTransport` → 200 geojson 1 feature.
2. Registrar en `CATALOGO_CAPAS["prueba"]`.
3. `POST /proyectos` con chip `AAA0072LRYN` → 303 → `GET /proyectos/{id}/json` incluye clave `prueba` con 5 campos traza.
4. `pytest -q` ≥486 0 failed; `docker build -t mcp-bogota-factibilidad .` ok; 7 tools invariante.

### S2 — Wizard preview + interrogación (US2 P2)

1. `GET /` → formulario + mapa Leaflet 320px.
2. `POST /proyectos/preview` chip `AAA0072LRYN` → 200 `lote.geometry/centroid + upl`; clic mapa (4.6,-74.08) → mismo.
3. Paso interrogación: llenar 5 campos; `escala_m2=10` → error inline <500ms submit bloqueado; bypass → 400.
4. Preview permanece visible al alternar pasos (hx-include, sin nueva petición fuentes); `POST /proyectos` final → 303 → `GET /proyectos/{id}` 23 bloques.

### S3 — Persistencia + reevaluación (US3 P3)

1. Crear con `uso_previsto=residencial escala_m2=120` → `GET /json` muestra 5 campos.
2. Simular DB vieja (sin columnas wizard) → `ProyectoRepositorio` hace `ALTER TABLE` aditivo, lectura `None` sin 500.
3. `POST /proyectos/{id}/reevaluar` → conserva campos wizard.

### S4 — Regresión 23 bloques / 19 evaluables

`GET /proyectos/{id}` renderiza 17 loop (incl. `market_dynamics`) + 6 separadas = 23 base; `market_dynamics` visible; `llm_ready_summary` + `feasibility_score` presentes; Fraunces/5 Pillars/anillo intactos.

## Comandos de verificación

```bash
uv run pytest --co -q | tail   # 486 collected 0 errors
uv run pytest -q               # 486 passed 0 failed
python -m app.web.main         # 127.0.0.1:8000 → flujo S1-S3 manual
curl -X POST http://127.0.0.1:8000/proyectos/preview -d "criterio_tipo=chip&criterio_valor=AAA0072LRYN"
```

## Referencias

- Catálogo: `specs/011-*/contracts/catalogo.md`, `app/providers/arcgis_utils.py:32`
- Wizard: `specs/011-*/contracts/wizard.md`, `app/web/main.py:222-290`, `app/web/db.py:PRAGMA`
- Data model: `specs/011-*/data-model.md` (Proyecto 16 cols, CapaConfig, PreviewLote)
- Research: `specs/011-*/research.md` R-01..R-07
