# Checklist de Requisitos — Feature 4: Ingesta de actos normativos que modifican el Decreto 555 de 2021 (corpus consolidado)

Estado: **Validado** contra la spec el 2026-08-14. Todos los ítems cumplidos.

## User Scenarios & Testing
- [x] CHK-001: La spec define al menos 3 user stories priorizadas (P1, P1, P2) y cada una explica "Por qué esta prioridad".
- [x] CHK-002: Cada user story tiene una "Prueba independiente" verificable y escenarios de aceptación en formato Dado/Cuando/Entonces.
- [x] CHK-003: La spec cubre edge cases (formato no soportado, archivo duplicado por hash, documento sin artículos, acto sin fecha, colisión de numeración entre normas, PDF escaneado, URL no disponible, cambio de modelo de embeddings, corpus sin indexar, coexistencia 555 + acto posterior).

## Requirements
- [x] CHK-004: Los Functional Requirements están numerados (FR-001 a FR-013) y redactados en español con DEBE/NO DEBE.
- [x] CHK-005: La feature define la ingesta de actos administrativos (decretos/resoluciones) que reglamentan o modifican el Decreto 555/2021, en formatos HTML sisjur (recomendado, anclas `class="ancla"` y plantilla `Norma1.jsp?i=N`), PDF, DOCX, Markdown y TXT.
- [x] CHK-006: El corpus consolidado (555 + actos) es la única fuente de consulta de `consultar_normativa` (F2) y `get_feasibility_report` (F3), sin romper sus contratos.
- [x] CHK-007: Cada resultado indica la norma de origen (`source_name`) y se aplica la precedencia temporal vía prompt, sin ocultar artículos (coexistencia de fuentes).
- [x] CHK-008: La ingesta captura metadatos por documento (`tipo_norma`, `numero`, `año`, `fecha_expedicion`, `fecha_vigencia`, `url_origen`, `titulo`) y deduplica por hash SHA-256 del archivo.
- [x] CHK-009: El índice se reconstruye automáticamente si cambia un documento del corpus o el modelo de embeddings (bge-m3, 1024 dims; chat qwen3:8b con citation forcing); la huella se persiste en los metadatos de la colección.
- [x] CHK-010: Formato no soportado o documento sin contenido → error claro y tipificado sin corromper el corpus; la ingesta (descarga/parseo) no requiere Ollama, solo indexación y consulta.
- [x] CHK-011: Extensión no destructiva de los contratos F2/F3 (FR-011) y el Decreto 555 permanece como norma base con sus 608 artículos (FR-012, FR-013).

## Success Criteria
- [x] CHK-012: Los Success Criteria son medibles (100% de trazabilidad por norma, deduplicación 100%, 185 tests de F1-F3 sin romperse, corpus intacto ante errores de ingesta).

## General (Principios del proyecto)
- [x] CHK-013: La spec está redactada en español (dominio en español; nombres técnicos en inglés solo en el contrato de salida).
- [x] CHK-014: La spec es coherente con el brief del producto (20260809-01-perplexity.md), con AGENTS.md (corpus versionado, modelos Ollama, trazabilidad de 5 campos) y con los contratos de F2/F3.
- [x] CHK-015: La feature 4 queda delimitada frente a F2 y F3 (extiende el corpus sin modificarlas retroactivamente) y frente a mejoras futuras (p. ej. actualización automática del catálogo de actos desde el Excel de la SDP).
- [x] CHK-016: La spec no contiene secciones "[NEEDS CLARIFICATION]" pendientes.
