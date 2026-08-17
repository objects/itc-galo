# Implementation Plan: Enriquecimiento del Informe de Factibilidad con 5 Nuevas Fuentes ArcGIS

**Branch**: `006-enriquecimiento-fuentes-arcgis` | **Date**: 2026-08-17 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/006-enriquecimiento-fuentes-arcgis/spec.md`

**Note**: Este plan documenta la implementación completa de la Feature 6. Los artefactos de diseño son [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/) y [quickstart.md](quickstart.md).

## Summary

Requisito primario (FR-001 a FR-020): enriquecer el informe de factibilidad (`get_feasibility_report`) con **5 nuevos bloques** que consultan **15 servicios ArcGIS REST adicionales** de Catastro Bogotá: (1) riesgos geotécnicos (4 capas de emergencias/gestionriesgos), (2) contexto socioeconómico (4 capas de estratificación/uso/altura/avalúo), (3) entorno regulatorio (licencias + plusvalía), (4) patrimonio cultural (BIC + plan arqueológico) y (5) acceso y movilidad (TransMilenio, SITP, Metro). Cada bloque se ejecuta en paralelo, degrada independientemente y sigue el patrón `{estado, dato, interpretation, source_trace}` de F3. El scoring se extiende con 4 reglas nuevas (+2 bonus, −2 penalizaciones) sin romper el determinismo.

Enfoque técnico (research D1–D5): los 5 bloques se implementan como un **nuevo grupo de consultas paralelas** en el orquestador de `app/main.py`, con 5 métodos nuevos en `ArcGISProvider` (`consultar_riesgos_geotecnicos`, `consultar_contexto_socioeconomico`, `consultar_entorno_regulatorio`, `consultar_patrimonio_cultural`, `consultar_acceso_movilidad`). Cada método consulta 2–4 capas en paralelo con `asyncio.gather(return_exceptions=True)` para degradación por sub-bloque. Los modelos F6 se añaden a `app/models.py` (5 modelos de datos + 5 wrappers de bloque). El scoring en `app/scoring.py` se extiende con 2 reglas positivas y 2 negativas, y el `confidence` se recalcula sobre 11 bloques evaluables. **No se añaden tools MCP nuevas**; las 7 tools permanecen sin cambios.

## Technical Context

**Language/Version**: Python 3.11+ (`requires-python = ">=3.11"`).

**Primary Dependencies**: `mcp>=1.0.0`, `httpx>=0.27.0`, `pydantic>=2.7.0`. No se añaden dependencias nuevas.

**Storage**: Sin almacenamiento nuevo. Las consultas son en vivo contra ArcGIS REST.

**Testing**: `pytest` con `asyncio_mode = "auto"`; patrón `MockTransport` de `tests/conftest.py`. Tests: `test_get_feasibility_report.py` extendido con 5 bloques, `test_scoring.py` extendido con reglas nuevas.

**Target Platform**: Servidor MCP por stdio (Docker Python).

**Performance Goals**: SC-001 — reporte completo en < 15 s con los 5 bloques adicionales (las 10 consultas ArcGIS se ejecutan en 2 rondas paralelas de 3 + 5 tareas).

**Constraints**: Trazabilidad NON-NEGOTIABLE de 5 campos en cada bloque (FR-010); determinismo del scoring (SC-003); degradación por bloque (FR-008/FR-009); sin LLM (FR-013); sin modificar F1/F2/F3/F4/F5 (CHK-015).

## Constitution Check

**Resultado del gate**: **APROBADO** — sin violaciones.

| Principio | Cumplimiento | Evidencia |
|-----------|--------------|-----------|
| I. Español primero | ✅ | Spec, research, data-model y contratos en español |
| II. Modularidad por providers | ✅ | 5 métodos nuevos en `ArcGISProvider` (la fuente es ArcGIS) |
| III. Trazabilidad de fuentes | ✅ | Cada bloque lleva `SourceTrace` de 5 campos (FR-010) |
| IV. Contratos explícitos | ✅ | Degradación por bloque documentada; errores fatales heredados de F3 |
| V. Entrega incremental | ✅ | Solo 5 bloques nuevos en el informe existente; sin tools nuevas |

## Fases de implementación

1. **Modelos** (`app/models.py`): `RiesgoGeotecnicos`, `ContextoSocioeconomico`, `EntornoRegulatorio`, `PatrimonioCultural`, `AccesoMovilidad` + 5 wrappers `Bloque*`.
2. **Provider ArcGIS** (`app/providers/arcgis.py`): 5 métodos nuevos + constantes de radios + dominios.
3. **Orquestación** (`app/main.py`): segunda ronda de consultas paralelas en `get_feasibility_report` + construccion de los 5 bloques.
4. **Scoring** (`app/scoring.py`): 2 reglas positivas + 2 negativas + recalculo de confidence sobre 11 bloques.
5. **Tests**: extensión de tests existentes + tests nuevos para los 5 bloques.
