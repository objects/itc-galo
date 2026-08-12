# Checklist de Requisitos — Feature 3: Informe de factibilidad

Estado: **Validado** contra la spec el 2026-08-12. Todos los ítems cumplidos.

## User Scenarios & Testing
- [x] CHK-001: La spec define al menos 3 user stories priorizadas (P1, P2, P3) y cada una explica "Por qué esta prioridad".
- [x] CHK-002: Cada user story tiene una "Prueba independiente" verificable y escenarios de aceptación en formato Dado/Cuando/Entonces.
- [x] CHK-003: La spec cubre edge cases (lote sin CHIP, sin UPL, sin localidad, punto fuera de cobertura, capas sin dato, RAG no disponible, dirección ambigua, parámetros inválidos, múltiples criterios).

## Requirements
- [x] CHK-004: Los Functional Requirements están numerados (FR-001...) y redactados en español con DEBE/NO DEBE.
- [x] CHK-005: La feature define la tool `get_feasibility_report` como orquestación unificada (lote → UPL → contexto temático → evidencia normativa → scoring) en una sola llamada.
- [x] CHK-006: El reporte incluye identidad del lote, contexto administrativo (UPL + localidad), restricciones (reserva vial), mercado (valor de referencia), entorno (obras públicas) y contexto económico (destino económico desde Mapas Bogotá).
- [x] CHK-007: El `feasibility_score` (0-100, confidence, reasons) y las interpretaciones son 100% determinísticos, sin LLM; la feature funciona sin Ollama.
- [x] CHK-008: La evidencia normativa es consulta opcional del usuario o automática desde el contexto del lote, con citas literales verificables; si el RAG no está disponible o no hay resultados, se degrada con advertencia (no falla el reporte).
- [x] CHK-009: Cada bloque de datos mantiene la trazabilidad de 5 campos (source_name, layer_id, service_url, data_vigencia, query_timestamp) sin mezclar vigencias.
- [x] CHK-010: Se reutiliza la semántica de errores tipificados y validaciones de las features 1 y 2.
- [x] CHK-011: El scoring es explícitamente heurístico: el sistema no infiere reglas urbanísticas ausentes en las fuentes.

## Success Criteria
- [x] CHK-012: Los Success Criteria son medibles (tiempos, porcentajes, determinismo).

## General (Principios del proyecto)
- [x] CHK-013: La spec está redactada en español (dominio en español; nombres técnicos en inglés solo en el contrato de salida).
- [x] CHK-014: La spec es coherente con el brief del producto (20260809-01-perplexity.md) y con las decisiones de clarificación del usuario del 2026-08-12.
- [x] CHK-015: La feature 3 queda delimitada frente a F1 y F2 (reutiliza sin modificarlas) y frente a la mejora futura de reglas de negocio urbanístico.
- [x] CHK-016: La spec no contiene secciones "[NEEDS CLARIFICATION]" pendientes.
