# Checklist de Requisitos — Feature 8: Parámetros Urbanísticos del Lote

Estado: **Validado** contra la spec el 2026-08-20. Todos los ítems cumplidos.

## User Scenarios & Testing
- [x] CHK-001: La spec define 2 user stories priorizadas (P1, P2) que explican "Por qué esta prioridad" y cubren el bloque `urbanistic_parameters` y la extensión del scoring.
- [x] CHK-002: Las user stories tienen "Prueba independiente" verificable y escenarios de aceptación en formato Dado/Cuando/Entonces.
- [x] CHK-003: La spec cubre edge cases (capa SDP falla, RAG falla, tratamiento sin parámetros, conservación patrimonial, degradación independiente).

## Requirements
- [x] CHK-004: Los Functional Requirements están numerados (FR-001 a FR-022) y redactados en español con DEBE/NO DEBE.
- [x] CHK-005: El bloque `urbanistic_parameters` sigue el patrón `{estado, dato, interpretation, source_trace}` de F3/F6/F7.
- [x] CHK-006: El bloque consulta la capa SDP/SINUPOT correcta (`sinu.sdp.gov.co`, layer 2 tratamiento + layer 14 edificabilidad).
- [x] CHK-007: El RAG normativo consulta artículos específicos del Decreto 555 (art. 281, 389, Anexo 5) para parámetros numéricos.
- [x] CHK-008: La consulta a la capa SDP usa `inSR=4326&outSR=4686` para la conversión correcta de CRS.
- [x] CHK-009: El bloque incluye `source_trace` con los 5 campos por cada fuente (SDP + RAG) (FR-010).
- [x] CHK-010: El bloque se incluye tanto en `get_feasibility_report` como en `get_lot_summary_by_chip` (FR-020).
- [x] CHK-011: El scoring se extiende con 3 reglas nuevas: bonus +10 parámetros, bonus +5 estacionamientos, penalización −15 conservación (FR-011).
- [x] CHK-012: El confidence considera 13 bloques evaluables (12 actuales + 1 nuevo) (FR-012).
- [x] CHK-013: El bloque no modifica los contratos de las 7 tools existentes (FR-013).
- [x] CHK-014: Las interpretaciones son textos deterministas sin LLM (FR-014).
- [x] CHK-015: Los warnings usan los códigos `BLOQUE_SIN_DATO` y `BLOQUE_DEGRADADO` (FR-016).
- [x] CHK-016: La fuente 5xx es FUENTE_5XX fatal (FR-009, preservado de F3).
- [x] CHK-017: El provider SDP sigue el Principio II de la constitución (modularidad por providers) (FR-017).
- [x] CHK-018: La URL base del SINUPOT es una constante configurable (FR-022).

## Success Criteria
- [x] CHK-019: Los Success Criteria son medibles (tiempo, trazabilidad, determinismo, degradación, no-regresión).

## General (Principios del proyecto)
- [x] CHK-020: La spec está redactada en español (Principio I).
- [x] CHK-021: La feature está delimitada frente a F1–F7 (reutiliza sin modificarlas).
- [x] CHK-022: La spec no contiene secciones "[NEEDS CLARIFICATION]" pendientes.
- [x] CHK-023: La trazabilidad de fuentes es NON-NEGOTIABLE y está documentada en FR-010 (Principio III).
- [x] CHK-024: La feature es incremental (MVP) y no implementa YAGNI (Principio V).
