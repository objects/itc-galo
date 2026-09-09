# Checklist de Requisitos — Feature 9: UX Web Informe Completo

Estado: **Validado** contra la spec el 2026-08-31.

## User Scenarios & Testing
- [x] CHK-001: La spec define 2 user stories priorizadas (P1, P2) con "Prueba independiente" y escenarios de aceptación Dado/Cuando/Entonces.
- [x] CHK-002: Las user stories cubren: informe completo en detalle, CSS consistente con identidad visual.
- [x] CHK-003: La spec cubre edge cases (geometría ausente, bloques None, mapa absent-friendly).

## Requirements
- [x] CHK-004: Los Functional Requirements están numerados (FR-001 a FR-013) y redactados en español con DEBE/NO DEBE.
- [x] CHK-005: FR-001: renderiza los 19 bloques evaluables.
- [x] CHK-006: FR-002: cada bloque muestra título, badge, dato, interpretación, source_trace.
- [x] CHK-007: FR-003/FR-004: mapa Leaflet con geometría, absent-friendly.
- [x] CHK-008: FR-005: llm_ready_summary como callout.
- [x] CHK-009: FR-006: evidencia normativa con ítems detallados.
- [x] CHK-010: FR-007: feasibility_score con reasons y rules_applied.
- [x] CHK-011: FR-008: advertencias con código y mensaje.
- [x] CHK-012: FR-009: Leaflet vendorizado (sin CDN).
- [x] CHK-013: FR-010/FR-011: identidad visual consistente, responsive.
- [x] CHK-014: FR-012: accesibilidad (aria, roles, semantic HTML).
- [x] CHK-015: FR-013: estados de carga/error.

## Success Criteria
- [x] CHK-016: SC-001: pytest pasa con tests existentes + nuevos.
- [x] CHK-017: SC-002: página renderiza los 19 bloques.
- [x] CHK-018: SC-003: mapa Leaflet muestra geometría.
- [x] CHK-019: SC-004: check-prerequisites.sh exit 0.

## General
- [x] CHK-020: No se añaden dependencias Python nuevas (NFR-001).
- [x] CHK-021: Tests usan fixtures httpx.MockTransport existentes (NFR-002).
- [x] CHK-022: Template usa vanilla JS + HTMX, no framework JS nuevo (NFR-003).
