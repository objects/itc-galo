# Implementation Plan: UX Web — Informe Completo de Factibilidad

**Branch**: `009-ux-web-informe-completo` | **Date**: 2026-08-31 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/009-ux-web-informe-completo/spec.md`

## Summary

Requisito primario (US1/US2, FR-001 a FR-013): renderizar en la interfaz web de
prefactibilidad (Feature 5) el **informe completo de factibilidad** de 20 bloques que ya
produce `get_feasibility_report`. Hoy `proyecto.html` solo muestra el anillo de score, la UPL
y las advertencias; el resto del informe (identidad, mapa, 14 bloques de contexto, evidencia
normativa, detalle del score) queda oculto. Esta feature reescribe la plantilla para volcar
todo el informe con trazabilidad por fuente, sin cambiar el contrato del informe ni las 7
tools MCP.

Enfoque técnico: reescribir `app/web/templates/proyecto.html` para renderizar los 20 bloques
con la identidad visual "Bogotá Reverdece" (5 Pillars), añadir un **mapa Leaflet** (vendorizado
en `app/web/static/`, sin CDN en runtime) que dibuja la geometría y el centroide del lote, y
registrar un filtro Jinja `json_pretty` para volcar los datos de cada bloque como JSON legible.
Se añaden bloques `estilos_extra`/`scripts_extra` a `base.html` y estilos nuevos a
`estilos.css`. **No se cambia el contrato del informe ni las 7 tools MCP.**

## Technical Context

**Language/Version**: Python 3.11+ (`requires-python = ">=3.11"`); plantillas Jinja2; JS/Leaflet 1.9.4.

**Primary Dependencies**: `fastapi`, `jinja2` (ya presentes en F5). Leaflet 1.9.4 vendorizado
(`leaflet.js` 147552 B, `leaflet.css` 14806 B) en `app/web/static/`. Sin dependencias nuevas.

**Storage**: Sin almacenamiento nuevo. El informe se lee del `Proyecto.informe` (dict JSON) ya
persistido en SQLite por F5.

**Testing**: `pytest` con `asyncio_mode = "auto"`; patrón `MockTransport` de `tests/conftest.py`.
Tests nuevos en `tests/contract/test_web_informe.py` (reutiliza el helper `_cliente` de
`test_web_rutas.py` y el fixture `server_lotes_f3`).

**Target Platform**: Interfaz web FastAPI (F5), servida por uvicorn.

**Performance Goals**: SC-001 — la página de detalle renderiza el informe sin llamadas de red
adicionales (el informe ya está persistido). SC-002 — el mapa se inicializa solo si hay
geometría/centroide.

**Constraints**: Trazabilidad por fuente visible (FR-004); determinismo (SC-003); degradación
por bloque (FR-009); sin LLM en la UI (FR-014); sin cambiar el contrato del informe ni las 7
tools MCP (SC-005); identidad visual "Bogotá Reverdece" (5 Pillars, NFR-001).

## Constitution Check

*GATE: Aprobado — sin violaciones.*

| Principio | Cumplimiento | Evidencia |
|-----------|--------------|-----------|
| I. Español primero | ✅ | Spec, plan, data-model, contratos y quickstart en español. Código y campos técnicos en inglés donde el contrato lo exige. |
| II. Modularidad por providers | ✅ | La UI solo consume el informe ya construido por `ServidorLotes`; no añade providers ni lógica de dominio. |
| III. Trazabilidad de fuentes | ✅ | Cada bloque muestra su `source_trace`/`source_traces` (procedencia por fuente). |
| IV. Contratos explícitos | ✅ | Degradación por bloque documentada en `contracts/informe-web.md`. |
| V. Entrega incremental | ✅ | Solo se reescribe la plantilla de detalle; sin tools nuevas; sin variables de entorno nuevas. |

## Project Structure

### Documentation (this feature)

```text
specs/009-ux-web-informe-completo/
├── plan.md                              # Este archivo
├── research.md                          # Phase 0: investigación del informe y Leaflet
├── data-model.md                        # Phase 1: modelos consumidos por la plantilla
├── quickstart.md                        # Phase 1: guía de verificación
├── contracts/
│   └── informe-web.md                   # Phase 1: contrato del render del informe
├── spec.md                              # Especificación del feature
└── tasks.md                             # Phase 2 (NO creado por /speckit-plan)
```

### Source Code (repository root)

```text
app/web/
├── main.py                              # Registra el filtro Jinja `json_pretty`
├── templates/
│   ├── base.html                        # Bloques nuevos `estilos_extra`/`scripts_extra`
│   └── proyecto.html                    # REWRITE: informe completo de 20 bloques + mapa
└── static/
    ├── estilos.css                      # Estilos nuevos de las secciones del informe
    ├── leaflet.js                       # Vendorizado (1.9.4)
    └── leaflet.css                      # Vendorizado (1.9.4)
tests/contract/
└── test_web_informe.py                  # Tests del render del informe completo
```

## Implementation Phases

### Phase 1: Base y filtro (T001–T004)
- `base.html`: añadir `{% block estilos_extra %}` en `<head>` y `{% block scripts_extra %}`
  antes de `</body>`.
- `main.py`: registrar `plantillas.env.filters["json_pretty"]`.

### Phase 2: Plantilla del informe (T005–T014)
- Reescribir `proyecto.html`: cabecera, resumen ejecutivo (anillo + `llm_ready_summary`),
  identidad del lote, mapa Leaflet (data-attributes + init JS), loop de 14 bloques de contexto,
  evidencia normativa, detalle del score y advertencias; columna de acciones.

### Phase 3: Estilos (T015–T017)
- `estilos.css`: secciones nuevas (`.columna-informe`, `.resumen-ejecutivo`, `.callout`,
  `.definiciones`, `.contenedor-mapa`, `.bloque-informe`, `.badge`, `.fuente`, `.evidencia`,
  `.score-detalle`, `.advertencia`).

### Phase 4: Tests y verificación (T018–T021)
- `tests/contract/test_web_informe.py`: render del informe completo, procedencia por fuente y
  caso sin geometría.
- Gate: `uv run pytest -q` y `check-prerequisites.sh --json --require-tasks --include-tasks`.

## Verification

```bash
uv run pytest -q
bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
```
