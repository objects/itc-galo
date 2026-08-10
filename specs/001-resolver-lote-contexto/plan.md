# Implementation Plan: Resolver lote con contexto temático

**Branch**: `master` | **Date**: 2026-08-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-resolver-lote-contexto/spec.md`

## Summary

**Requisito principal (Feature 1 / MVP)**: construir un servidor MCP que permita a un usuario
consultar un lote catastral de Bogotá por **CHIP**, por **dirección** o por **coordenadas**,
enriquecerlo con **contexto temático** (valor de referencia catastral, destino económico,
reservas viales y obras públicas) y obtener un **resumen consolidado** del lote con
trazabilidad por fuente. Fuera de alcance de F1: consulta de UPL, RAG normativo del POT
(Decreto 555 de 2021) y reporte de factibilidad.

**Enfoque técnico**: servidor MCP en **Python** según la constitución v1.0.0 (Principio V y
Restricciones técnicas): dependencia `mcp>=1.0.0` (incluye FastMCP), `httpx` y `pydantic`,
transporte por **stdio**, estructura `app/` modular con un **provider por fuente**
(Mapas Bogotá API y ArcGIS REST), modelos pydantic como frontera de parsing y salida JSON
para el LLM con los 5 campos de trazabilidad (`source_name`, `layer_id`, `service_url`,
`data_vigencia`, `query_timestamp`) en cada dato. No hay persistencia: las consultas son
puntuales contra fuentes públicas en vivo.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `mcp>=1.0.0` (incluye FastMCP), `httpx`, `pydantic`; dev: `pytest`

**Storage**: N/A — sin persistencia; consultas puntuales a fuentes públicas en vivo
(Mapas Bogotá API y ArcGIS REST del catastro de Bogotá).

**Testing**: pytest — smoke test de arranque (`tests/smoke`) y contract tests
(`tests/contract`) que validan los contratos de las tools y los estados de error
(disponible vs no encontrado, 5xx, credencial faltante, parámetros inválidos).

**Target Platform**: Linux (contenedor Docker Python; MCP por stdio).

**Project Type**: servidor MCP (protocolo Model Context Protocol), proyecto único `app/`
modular (`main.py` con FastMCP, `providers/`, `models.py`).

**Performance Goals**: SC-001 del spec — el resumen de un lote con CHIP válido se obtiene
en **menos de 10 segundos** desde el inicio de la consulta, en condiciones de red normales.

**Constraints**: constitución v1.0.0 — trazabilidad NON-NEGOTIABLE
(`source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp` en toda
salida para el LLM); contratos de error explícitos (distinguir "dato disponible" de "dato
no encontrado"; un 5xx de la fuente NO se reporta como no encontrado; fail-fast sin
`MAPAS_BOGOTA_APIKEY` en geocodificación); nunca mezclar vigencias de capas distintas como
una sola fotografía temporal; sin credenciales embebidas (`.env` + `.env.example`); YAGNI
(solo lo que exige F1); toda especificación, documentación y mensajes en español.

**Scale/Scope**: consultas puntuales (un lote por consulta); sin UPL, sin RAG normativo,
sin feasibility score (fuera de alcance de F1); 4 tools MCP.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Gate (constitución v1.0.0) | Estado | Justificación |
|---|----------------------------|--------|---------------|
| I | **Español primero** | PASS | Toda la documentación, mensajes y código en español; los nombres técnicos del contrato (`source_name`, `layer_id`, etc.) se conservan en inglés porque el contrato lo exige. |
| II | **Modularidad por providers** | PASS | Un provider por fuente (`mapas_bogota.py`, `arcgis.py`), frontera de parsing con modelos pydantic (`models.py`), sin mezclar responsabilidades entre fuentes. |
| III | **Trazabilidad NON-NEGOTIABLE** | PASS | Toda salida para el LLM incluye los 5 campos de trazabilidad por dato; las vigencias distintas se conservan y exponen sin mezclarse. |
| IV | **Contratos de error explícitos** | PASS | Taxonomía de errores canónica (LOTE_NO_ENCONTRADO, DIRECCION_NO_LOCALIZADA, FUERA_DE_COBERTURA, DATO_NO_ENCONTRADO_POR_FUENTE, FUENTE_5XX, CREDENCIAL_FALTANTE, PARAMETROS_INVALIDOS); fail-fast en credencial faltante. |
| V | **Entrega incremental (MVP first)** | PASS | F1 se limita a resolver lote + contexto temático + resumen; YAGNI: sin UPL, sin RAG normativo, sin feasibility score. |

**Re-check tras Phase 1 (diseño de contratos y modelo de datos)**: **PASS** — los 4
contratos de tools incluyen explícitamente los 5 campos de trazabilidad en cada dato
(incluye `query_timestamp`, que SC-003 del spec omite y el revisor exige), la taxonomía de
errores es explícita por tool, los providers se definen como frontera de parsing con
pydantic, la documentación está en español y el alcance sigue limitado a F1. No hay
violaciones que justificar.

## Project Structure

### Documentation (this feature)

```text
specs/001-resolver-lote-contexto/
├── plan.md              # Este archivo (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   ├── resolve-lot-by-chip.md
│   ├── resolve-lot-by-address.md
│   ├── resolve-lot-by-coordinates.md
│   └── get-lot-summary-by-chip.md
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
app/
├── main.py              # FastMCP: registra las 4 tools
├── models.py            # Modelos pydantic (Lote, contexto temático, trazabilidad)
└── providers/           # Un provider por fuente
    ├── mapas_bogota.py  # Mapas Bogotá API (chip, geocodificación)
    └── arcgis.py        # ArcGIS REST (Lote=38 + temáticas)
tests/
├── contract/            # Contratos de las tools y de error
└── smoke/               # Smoke test de arranque
```

**Structure Decision**: se elige **proyecto único `app/` modular** (con `main.py`,
`providers/`, `models.py` y `tests/` con `contract/` y `smoke/`) en lugar de la estructura
por defecto del template `src/{models,services,cli,lib}` por dos razones:

1. **Constitución, Principio II (Modularidad por providers)**: la constitución fija
   explícitamente "estructura `app/` modular (`main.py` con FastMCP, `providers/`,
   `models.py`)" en sus Restricciones técnicas; los providers son el límite de parsing y
   el repositorio no necesita capas `services/`/`cli/` separadas para un servidor MCP.
2. **Forma de F1**: la feature expone exactamente 4 tools MCP registradas en `main.py`,
   con la lógica de dominio distribuida por fuente (`mapas_bogota.py`, `arcgis.py`) y los
   modelos pydantic en `models.py` como frontera tipada. `tests/contract` valida los
   contratos de las tools y `tests/smoke` valida el arranque; no hay flujos `cli/` ni
   librerías `lib/` que justifiquen capas adicionales (YAGNI).
