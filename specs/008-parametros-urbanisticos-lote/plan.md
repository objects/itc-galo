# Implementation Plan: Parámetros Urbanísticos del Lote

**Branch**: `008-parametros-urbanisticos-lote` | **Date**: 2026-08-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/008-parametros-urbanisticos-lote/spec.md`

## Summary

Requisito primario (FR-001 a FR-022): enriquecer el informe de factibilidad (`get_feasibility_report`) y el resumen (`get_lot_summary_by_chip`) con un bloque `urbanistic_parameters` que consulta los parámetros urbanísticos del lote desde **dos fuentes**: (1) **SINUPOT/SDP** (`sinu.sdp.gov.co/serverp/rest/services/POT555/NORMA_URBANÍSTICA_Y_OT/MapServer`, layer 2: tratamiento, layer 14: edificabilidad) para el tratamiento espacial, y (2) **RAG normativo** del Decreto 555/2021 (art. 281, art. 389, Anexo 5) para COS, CUS, altura, retiros y estacionamientos. El scoring se extiende con 3 reglas nuevas (+10, +5, −15) y el confidence se recalcula sobre 13 bloques evaluables. **No se añaden tools MCP nuevas**; las 7 tools permanecen sin cambios.

Enfoque técnico (research D1–D8): un **provider nuevo** `app/providers/sdp.py` encapsula la consulta a SINUPOT (Principio II). El bloque `urbanistic_parameters` se construye como una **tercera ronda de consultas** en `get_feasibility_report` y `get_lot_summary_by_chip`: primero SDP (tratamiento), luego RAG (parámetros numéricos, usando el tratamiento para construir el prompt). El parsing de la respuesta del RAG usa regex determinista para extraer valores numéricos. El scoring se extiende en `app/scoring.py` con 3 reglas y actualización de `BLOQUES_EVALUABLES` a 13 elementos.

## Technical Context

**Language/Version**: Python 3.11+ (`requires-python = ">=3.11"`).

**Primary Dependencies**: `mcp>=1.0.0` (FastMCP), `httpx>=0.27.0`, `pydantic>=2.7.0`. No se añaden dependencias nuevas.

**Storage**: Sin almacenamiento nuevo. Consultas en vivo contra SINUPOT/SDP y RAG existente.

**Testing**: `pytest` con `asyncio_mode = "auto"`; patrón `MockTransport` de `tests/conftest.py`. Tests nuevos en `tests/contract/test_urbanistic_parameters.py`.

**Target Platform**: Servidor MCP por stdio (Docker Python).

**Performance Goals**: SC-001 — reporte completo en < 15 s. Overhead adicional F8: ≤ 3 s (SDP < 2 s + RAG < 1 s).

**Constraints**: Trazabilidad NON-NEGOTIABLE de 5 campos (FR-010); determinismo del scoring (SC-003); degradación por bloque e independiente por fuente (FR-008/FR-009); sin LLM para interpretaciones (FR-014); sin modificar F1/F2/F3/F4/F6/F7 (SC-005).

## Constitution Check

*GATE: Aprobado — sin violaciones.*

| Principio | Cumplimiento | Evidencia |
|-----------|--------------|-----------|
| I. Español primero | ✅ | Spec, research, data-model, contratos y quickstart en español. Código y campos técnicos en inglés donde el contrato lo exige. |
| II. Modularidad por providers | ✅ | Provider nuevo `app/providers/sdp.py` para SINUPOT/SDP (fuente diferente de Catastro). RAG reutiliza `NormativaProvider` existente. |
| III. Trazabilidad de fuentes | ✅ | Cada bloque lleva `SourceTrace` de 5 campos (FR-010). Bloque dual SDP+RAG con trace principal de SDP. |
| IV. Contratos explícitos | ✅ | Degradación por fuente documentada en `contracts/urbanistic-parameters.md`. Errores tipados heredados de F3. |
| V. Entrega incremental | ✅ | Solo 1 bloque nuevo en el informe existente; sin tools nuevas; sin variables de entorno nuevas. |

## Project Structure

### Documentation (this feature)

```text
specs/008-parametros-urbanisticos-lote/
├── plan.md                              # Este archivo
├── research.md                          # Phase 0: investigación SINUPOT + RAG
├── data-model.md                        # Phase 1: modelos + scoring
├── quickstart.md                        # Phase 1: guía de verificación
├── contracts/
│   └── urbanistic-parameters.md         # Phase 1: contrato del bloque
├── spec.md                              # Especificación del feature
└── tasks.md                             # Phase 2 (NO creado por /speckit-plan)
```

### Source Code (repository root)

```text
app/
├── main.py                              # MODIFICADO: 3ª ronda de consultas + bloque urbanistic_parameters
├── models.py                            # MODIFICADO: 5 modelos nuevos + 1 wrapper + extensión InformeFactibilidad/BloquesEvaluables
├── scoring.py                           # MODIFICADO: 3 reglas nuevas + BLOQUES_EVALUABLES a 13
├── errores.py                           # Sin cambios
├── providers/
│   ├── sdp.py                           # NUEVO: provider SINUPOT/SDP
│   ├── arcgis.py                        # Sin cambios
│   ├── arcgis_utils.py                  # Sin cambios (reutilizar construir_params_punto)
│   ├── mapas_bogota.py                  # Sin cambios
│   ├── normativa.py                     # Sin cambios (reutilizar consultar())
│   └── upl.py                           # Sin cambios
├── ingesta/                             # Sin cambios
tests/
├── smoke/
│   └── test_main.py                     # Sin cambios (7 tools)
├── contract/
│   ├── test_urbanistic_parameters.py    # NUEVO: tests del bloque y scoring
│   └── ... (14 archivos F1/F2 + 6 F3 + 3 F4 sin cambios)
└── conftest.py                          # Sin cambios (fixtures MockTransport)
```

**Structure Decision**: proyecto Python único (`app/`), provider nuevo en `app/providers/sdp.py` siguiendo la estructura existente. Tests en `tests/contract/`. Sin nuevos directorios ni dependencias.

## Fases de implementación

1. **Provider SDP** (`app/providers/sdp.py`): `SDPProvider` con `consultar_tratamiento(lng, lat)` que consulta layer 2 del SINUPOT. Usa `construir_params_punto` de `arcgis_utils.py` con `outSR=4686`. Timeout configurable (default 10s). Constante `SDP_BASE_URL`.

2. **Modelos** (`app/models.py`): `TratamientoUrbanistico`, `ParametrosEdificabilidad`, `RetirosLote`, `EstacionamientosRequeridos`, `ParametrosUrbanisticos` + wrapper `BloqueParametrosUrbanisticos`. Extensión de `InformeFactibilidad` (campo `urbanistic_parameters`) y `BloquesEvaluables` (campo `urbanistic_parameters`).

3. **Orquestación** (`app/main.py`): inyección de `SDPProvider` en `ServidorLotes`. Tercera ronda de consultas en `get_feasibility_report`: SDP (tratamiento) → RAG (parámetros numéricos). Construcción del bloque `urbanistic_parameters` con patrón `{estado, dato, interpretation, source_trace}`. Degradación independiente por fuente. Extensión de `get_lot_summary_by_chip` (FR-020).

4. **Scoring** (`app/scoring.py`): 3 reglas nuevas (`r_parametros_urbanisticos`, `r_estacionamientos_calculados`, `r_tratamiento_conservacion`). Actualización de `BLOQUES_EVALUABLES` a 13. Actualización de `BloquesEvaluables` con campo `urbanistic_parameters`. Umbrales de confidence: `high ≥ 10`, `medium 5-9`, `low ≤ 4`.

5. **Tests** (`tests/contract/test_urbanistic_parameters.py`): tests del bloque con MockTransport (SDP layer 2), tests de scoring con las 3 reglas nuevas, tests de degradación independiente, tests de no-regresión (las 7 tools no cambian).

## Complexity Tracking

> Sin violaciones de la constitución. No se requiere justificación.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| N/A | N/A | N/A |
