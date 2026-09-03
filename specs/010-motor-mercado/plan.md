# Implementation Plan: Motor de Mercado

**Branch**: `010-motor-mercado` | **Date**: 2026-09-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/010-motor-mercado/spec.md`

## Summary

Añadir el bloque `market_dynamics` al informe de factibilidad (y al resumen por lote)
con precio por m² de referencia de **mercado**, estrato, oferta competidora (clústeres)
y ritmo de absorción. Los datos provienen de un corpus local versionado
(`data/corpus/mercado/`) poblado por scraping de portales inmobiliarios (Finca Raíz,
Metrocuadrado, constructoras) con un conjunto de seeds deterministas como respaldo ante
fallos de red o restricciones ToS. Se añade el subcomando CLI `python -m app.ingesta.corpus
mercado` para actualizar el corpus. Las 7 tools MCP permanecen SIN cambios.

**Nota de naming (decisión D0, ver research.md)**: el spec literal usa el nombre
`market_context` para el bloque nuevo, pero ese campo YA existe en `InformeFactibilidad`
(`BloqueValorReferencia`, valor de referencia **catastral** de `catastro/valorreferencia`,
con su regla `r_mercado` +10). Para cumplir FR-013 (no modificar bloques F3) el bloque
nuevo se llama **`market_dynamics`**; la entidad de datos es `ContextoMercado`.

## Technical Context

**Language/Version**: Python >=3.11 (igual al resto del proyecto)

**Primary Dependencies**: `mcp>=1.0.0` (FastMCP), `httpx`, `pydantic` v2 (ya existentes).
Sin dependencias duras nuevas: el scraping usa `httpx` (ya presente) + parsing stdlib
(`html.parser`/regex); el clustering y la absorción son deterministas (stdlib, sin ML).
No hay variables de entorno nuevas.

**Storage**: archivos JSONL + huella SHA-256 en `data/corpus/mercado/`, versionados en
git como fuente de verdad (patrón `data/corpus/actos_modificatorios/` de F4).

**Testing**: pytest con fixtures `httpx.MockTransport` de `tests/conftest.py`, sin red
real; seeds deterministas permiten tests reproducibles sin red ni Ollama.

**Target Platform**: Linux server (servidor MCP por stdio + CLI de ingesta).

**Project Type**: MCP server (Python) + subcomando CLI de ingesta.

**Performance Goals**: el bloque `market_dynamics` añade <3s al reporte (SC-006); en el
camino principal la consulta es local al corpus (sin red).

**Constraints**: determinismo total (SC-001/SC-005, mismo corpus+lote → mismo score);
sin credenciales embebidas; fuentes públicas; respeto de robots.txt/ToS (FR-007); las 7
tools sin cambios (FR-013).

**Scale/Scope**: 33 UPLs de Bogotá, 6 estratos; corpus de mercado acotado (miles de
registros, deduplicados por id estable).

## Constitution Check

*GATE: Pasa antes de Phase 0. Re-evaluado tras Phase 1: sigue PASANDO.*

- **I. Español primero** — PASS: toda doc/comentario/código en español; campos de
  contrato en inglés donde el JSON lo exige (`source_name`, `layer_id`, `precio_m2_referencia`).
- **II. Modularidad por providers** — PASS: provider nuevo `app/providers/mercado.py`
  (FR-009), frontera de parsing con modelos pydantic tipados.
- **III. Trazabilidad NON-NEGOTIABLE** — PASS: `source_trace` de 5 campos (FR-010),
  fuente primaria = corpus de mercado; proveniencia por registro en `interpretation`/`dato`.
- **IV. Contratos de error explícitos** — PASS: degradación `no_encontrado` + warning
  `BLOQUE_SIN_DATO`/`BLOQUE_DEGRADADO` (FR-003/FR-016); fallo de scraping nunca es fatal.
- **V. Entrega incremental (MVP/YAGNI)** — PASS: absorción heurística sin modelo ML
  completo; clustering determinista; sin features extra.

## Project Structure

### Documentation (this feature)

```text
specs/010-motor-mercado/
├── plan.md              # Este archivo
├── research.md          # Phase 0 (decisiones D0-D8)
├── data-model.md        # Phase 1 (entidades y esquema del corpus)
├── quickstart.md        # Phase 1 (guía de validación end-to-end)
├── contracts/
│   └── market-dynamics.md  # Contrato del bloque + subcomando CLI
├── checklists/
│   └── requirements.md  # checklist del spec (completo)
└── tasks.md             # Phase 2 (NO lo crea /speckit.plan)
```

### Source Code (repository root)

```text
app/
├── models.py                    # + ContextoMercado, OfertaCompetidora, RitmoAbsorcion,
│                                #   RegistroOfertaInmobiliaria, BloqueMarketDynamics
├── scoring.py                   # + r_contexto_mercado, r_oferta_competidora,
│                                #   r_absorcion_mercado; market_dynamics en evaluables
├── main.py                      # + _bloque_market_dynamics (orquestación); registro
│                                #   en get_feasibility_report y get_lot_summary_by_chip
├── providers/
│   └── mercado.py               # NUEVO: provider del corpus de mercado (Principio II)
└── ingesta/
    ├── corpus.py                # + subcomando `mercado` (CLI)
    └── mercado.py               # NUEVO: scraping + seeds + validación/dedup + huella
data/corpus/mercado/             # JSONL + .sha256 (git-versionado, FR-020)
tests/contract/
├── test_mercado.py              # bloque market_dynamics + scoring + degradación
├── test_ingesta_mercado.py      # scraping/seeds/dedup/validación/CLI
└── test_scoring.py              # extensiones aditivas r_* nuevas
```

**Structure Decision**: patrón F8 — un provider por fuente (Principio II) en
`app/providers/`, el subcomando de ingesta en `app/ingesta/`, los modelos en
`app/models.py`, el scoring en `app/scoring.py`, y el corpus versionado en
`data/corpus/mercado/`. Sin nuevos directorios de código fuera de los existentes.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Desviación del nombre literal del spec (`market_context` → `market_dynamics`) | El campo `market_context` ya existe en el contrato F3 (`BloqueValorReferencia`, valor de referencia catastral) y FR-013 prohíbe modificar bloques existentes | Renombrar el bloque F3 existente rompería el contrato de `get_feasibility_report` y `get_lot_summary_by_chip` (no-regresión F1-F9, SC-004) |
