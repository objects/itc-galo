<!--
Sync Impact Report
- Version change: N/A → 1.0.0 (ratificación inicial de la constitución)
- Añadido: 5 principios fundamentales (I. Español primero, II. Modularidad por providers,
  III. Trazabilidad de fuentes (NON-NEGOTIABLE), IV. Contratos de error explícitos
  (Fail Fast, Fail Loud), V. Entrega incremental (MVP first)); secciones Restricciones
  técnicas, Flujo de desarrollo y Governance.
- Removido: ninguna sección.
- Deferred TODOs: ninguno.
-->

# Constitución de mcp-bogota-factibilidad

## Principios Fundamentales

### I. Español primero

Toda especificación, documentación, código, comentarios y mensajes DEBE escribirse en
español. Las tools MCP y los campos de salida JSON DEBEN conservar nombres técnicos en
inglés donde el contrato lo exige (p. ej. `source_name`, `layer_id`).

### II. Modularidad por providers

Cada fuente de datos (Mapas Bogotá API, ArcGIS REST temáticas, RAG normativo futuro)
DEBE ser un provider aislado con una única responsabilidad. Los providers son el límite
de parsing: exponen modelos tipados (pydantic) y NO DEBEN mezclar responsabilidades
entre fuentes.

### III. Trazabilidad de fuentes (NON-NEGOTIABLE)

Toda salida para el LLM DEBE incluir trazabilidad por fuente: `source_name`, `layer_id`,
`service_url`, `data_vigencia`, `query_timestamp`. NO DEBEN mezclarse capas de vigencias
distintas como una sola fotografía temporal. El `feasibility_score` es heurístico: nunca
inferir reglas urbanísticas ausentes en la fuente.

### IV. Contratos de error explícitos (Fail Fast, Fail Loud)

Toda tool DEBE distinguir "dato disponible" de "dato no encontrado". DEBE fallar rápido
con mensaje claro si falta `MAPAS_BOGOTA_APIKEY` en geocodificación. DEBEN manejarse de
forma explícita los resultados vacíos y los errores 5xx de los servicios.

### V. Entrega incremental (MVP first)

Se avanza por features pequeñas: F1 resolver lote + contexto temático, F2 RAG
normativo, F3 orquestación unificada. YAGNI: NO DEBE implementarse lo que no exige la
feature activa.

## Restricciones técnicas

- Stack Python: dependencia `mcp>=1.0.0` (incluye FastMCP), `httpx`, `pydantic`;
  proyecto con `pyproject.toml`; estructura `app/` modular (`main.py` con FastMCP,
  `providers/`, `models.py`).
- Transporte MCP por stdio.
- Docker Python: imagen multi-etapa razonable; sin requisito de versión específica aún.
- Sin credenciales embebidas en código: `MAPAS_BOGOTA_APIKEY` solo vía entorno (`.env`),
  opcional salvo geocodificación (`geocodificar` / `geocodificar_inverso`);
  `.env.example` documenta la variable.
- Fuentes públicas de datos: Mapas Bogotá API y servicios ArcGIS REST del catastro de
  Bogotá.

## Flujo de desarrollo

- Ciclo Spec Kit obligatorio, en este orden: `/speckit.specify` → `/speckit.plan` →
  `/speckit.tasks` → `/speckit.implement`, con separador `.` (`/speckit.specify`, no
  `/speckit-specify`).
- Commit en cada hito ratificado: constitución, spec, plan, tasks, checklist e
  implementación.
- Toda spec/plan DEBE revisarse antes de implementar; la constitución y `AGENTS.md` son
  de lectura obligatoria antes de especificar o planificar.
- El brief `20260809-01-perplexity.md` es la fuente de verdad del producto; el feature
  activo se resuelve vía `.specify/feature.json`.

## Governance

- La constitución prevalece sobre prácticas ad hoc. Toda enmienda exige justificación
  escrita, aprobación del usuario y bump semántico de versión:
  - MAJOR: cambios incompatibles de gobernanza.
  - MINOR: principio o sección nueva.
  - PATCH: clarificaciones.
- Revisión de cumplimiento en cada ciclo de implementación: checklist del feature +
  revisión por el reviewer.
- Las convenciones de runtime y datos del dominio se mantienen en `AGENTS.md`; referir
  a él para detalles operativos.

**Version**: 1.0.0 | **Ratified**: 2026-08-10 | **Last Amended**: 2026-08-10
