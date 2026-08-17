# Implementation Plan: Contexto Catastral Adicional del Lote

**Branch**: `007-contexto-catastro-adicional` | **Date**: 2026-08-17 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/007-contexto-catastro-adicional/spec.md`

**Note**: Este plan documenta la implementación completa de la Feature 7. Los artefactos de diseño son [contracts/](contracts/) y [quickstart.md](quickstart.md).

## Summary

Requisito primario (FR-001 a FR-010): enriquecer el informe de factibilidad (`get_feasibility_report`) y el resumen del lote (`get_lot_summary_by_chip`) con un **bloque `catastro_data`** que consulta **5 capas catastrales adicionales** de Catastro Bogotá en paralelo: (1) construccion [0], (2) manzana [0], (3) densidadpredialmz [0], (4) variacionareaconstruida [1] y (5) sectorcatastral [0]. Cada capa se consulta por punto (centroide del lote) con `inSR=4326`. Las 5 consultas corren en paralelo con `asyncio.gather(return_exceptions=True)` para degradación independiente por capa. El bloque sigue el patrón `{estado, dato, interpretation, source_trace}` de F3/F6. El scoring se extiende con un bloque evaluable adicional (12 bloques evaluable total). **No se añaden tools MCP nuevas**; las 7 tools permanecen sin cambios.

Enfoque técnico: el bloque `catastro_data` se implementa como un **método nuevo** `consultar_contexto_catastro` en `ArcGISProvider` (`app/providers/arcgis.py`) que consulta las 5 capas en paralelo. Los modelos `ContextoCatastro` y `BloqueCatastroData` se añaden a `app/models.py`. La orquestación en `app/main.py` integra el bloque tanto en `get_feasibility_report` (conjunto con los 5 bloques de F6) como en `get_lot_summary_by_chip`. El scoring en `app/scoring.py` añade `catastro_data` a `BloquesEvaluables` y `_bloques_con_estado`.

## Technical Context

**Language/Version**: Python 3.11+ (`requires-python = ">=3.11"`).

**Primary Dependencies**: `mcp>=1.0.0`, `httpx>=0.27.0`, `pydantic>=2.7.0`. No se añaden dependencias nuevas.

**Storage**: Sin almacenamiento nuevo. Las consultas son en vivo contra ArcGIS REST.

**Testing**: `pytest` con `asyncio_mode = "auto"`; patrón `MockTransport` de `tests/conftest.py`.

**Target Platform**: Servidor MCP por stdio (Docker Python).

**Constraints**: Trazabilidad NON-NEGOTIABLE de 5 campos en cada bloque (FR-006); determinismo del scoring (SC-002/SC-003); degradación independiente por capa (FR-004); sin LLM (FR-014); sin modificar F1/F2/F3/F4/F6 (CHK-015).

## Constitution Check

**Resultado del gate**: **APROBADO** — sin violaciones.

| Principio | Cumplimiento | Evidencia |
|-----------|--------------|-----------|
| I. Español primero | ✅ | Spec, contratos y quickstart en español |
| II. Modularidad por providers | ✅ | Método nuevo `consultar_contexto_catastro` en `ArcGISProvider` |
| III. Trazabilidad de fuentes | ✅ | Cada capa lleva `SourceTrace` de 5 campos (FR-006) |
| IV. Contratos explícitos | ✅ | Degradación por capa documentada; errores fatales heredados de F3 |
| V. Entrega incremental | ✅ | Solo 1 bloque nuevo en el informe existente; sin tools nuevas |

## Fases de implementación

1. **Modelos** (`app/models.py`): `ContextoCatastro` (5 campos de datos) + `BloqueCatastroData` (wrapper con patrón `{estado, dato, interpretation, source_trace}`) + campo `catastro_data` en `InformeFactibilidad`.
2. **Provider ArcGIS** (`app/providers/arcgis.py`): 5 configs de capas nuevas (`construccion`, `manzana_catastro`, `densidad_predial`, `variacion_area`, `sector_catastral`) + método `consultar_contexto_catastro(lng, lat)` con `asyncio.gather(return_exceptions=True)`.
3. **Orquestación** (`app/main.py`): integrar `catastro_data` en la segunda ronda de consultas paralelas de `get_feasibility_report` + añadir al resumen de `get_lot_summary_by_chip`.
4. **Scoring** (`app/scoring.py`): añadir `catastro_data` a `BLOQUES_EVALUABLES`, `BloquesEvaluables`, `_bloques_con_estado`, `_contar_bloques_disponibles` y `_reasons_datos_faltantes` (12 bloques evaluables total).
5. **Tests**: extensión de tests existentes para cubrir el nuevo bloque.
