# Checklist de Requisitos — Feature 6: Enriquecimiento del Informe de Factibilidad

Estado: **Validado** contra la spec el 2026-08-17. Todos los ítems cumplidos.

## User Scenarios & Testing
- [x] CHK-001: La spec define 5 user stories priorizadas (P1–P5), una por cada nuevo bloque, y cada una explica "Por qué esta prioridad".
- [x] CHK-002: Cada user story tiene una "Prueba independiente" verificable y escenarios de aceptación en formato Dado/Cuando/Entonces.
- [x] CHK-003: La spec cubre edge cases (capas que fallan individualmente, bloque sin datos, todos los bloques no encontrados, parámetros de radio, SR diferentes).

## Requirements
- [x] CHK-004: Los Functional Requirements están numerados (FR-001 a FR-020) y redactados en español con DEBE/NO DEBE.
- [x] CHK-005: Los 5 bloques nuevos siguen el patrón `{estado, dato, interpretation, source_trace}` de F3.
- [x] CHK-006: Cada bloque consulta las capas ArcGIS correctas con los layer IDs y SR documentados en research.md.
- [x] CHK-007: Las consultas de radio (TransMilenio 800 m, SITP 500 m, Metro 800 m) usan `distance=<radio_m>&units=esriSRUnit_Meter`.
- [x] CHK-008: Los 5 bloques se ejecutan en paralelo con `asyncio.gather` (FR-007).
- [x] CHK-009: Cada sub-bloque que falla se degrada independientemente dentro de su bloque (FR-008).
- [x] CHK-010: Cada bloque incluye `source_trace` con los 5 campos (FR-010).
- [x] CHK-011: El scoring se extiende con reglas nuevas sin romper el determinismo de F3 (FR-011, SC-003).
- [x] CHK-012: Los 5 bloques no modifican los contratos de las 7 tools existentes (FR-012, CHK-015).
- [x] CHK-013: Las interpretaciones son textos deterministas sin LLM (FR-013).
- [x] CHK-014: El sistema no infiere reglas urbanísticas ausentes (FR-014).
- [x] CHK-015: Los warnings usan los códigos `BLOQUE_SIN_DATO` y `BLOQUE_DEGRADADO` (FR-015).
- [x] CHK-016: Las conversiones de SR se manejan via `inSR=4326` en ArcGIS REST (FR-017, FR-018).

## Success Criteria
- [x] CHK-017: Los Success Criteria son medibles (tiempos, porcentajes, determinismo).

## General (Principios del proyecto)
- [x] CHK-018: La spec está redactada en español.
- [x] CHK-019: La feature está delimitada frente a F1–F5 (reutiliza sin modificarlas).
- [x] CHK-020: La spec no contiene secciones "[NEEDS CLARIFICATION]" pendientes.
