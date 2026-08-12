# AGENTS.md

Workspace de desarrollo dirigido por especificaciones (Spec Kit v0.16.1) para construir
**mcp-bogota-factibilidad**: un servidor MCP (Python) que evalúa la factibilidad
de lotes para construcción en Bogotá, fusionando contexto geoespacial (Mapas Bogotá + ArcGIS REST)
con evidencia normativa del POT (RAG sobre el Decreto 555 de 2021).

## Estado actual
- **Aún no hay código de aplicación.** El repo contiene solo el brief del producto, el tooling
  `.specify/` y los comandos `.opencode/commands/speckit.*.md`. No hay `specs/` todavía. El repositorio git ya está inicializado (commit inicial: AGENTS.md + tooling).
- `20260809-01-perplexity.md` es la **fuente de verdad del producto** (arquitectura, fuentes de
  datos, herramientas MCP, pipeline RAG). Léelo antes de especificar o planificar.

## Flujo de trabajo (obligatorio)
La app se construye con la cadena de comandos Spec Kit, en orden:
1. `/speckit.specify` → crea `specs/NNN-<short-name>/spec.md` (numeración secuencial) y `.specify/feature.json`
2. `/speckit.plan` → genera `research.md`, `data-model.md`, `contracts/`, `quickstart.md`
3. `/speckit.tasks` → genera `tasks.md` (formato `- [ ] T### [P] [USn] ...`)
4. `/speckit.implement` → valida con `check-prerequisites.sh --json --require-tasks --include-tasks` y ejecuta `tasks.md`

Notas:
- Separador de invocación `.` (ver `.specify/integration.json`): `/speckit.specify`, no `/speckit-specify`.
- Un `/speckit.specify` crea exactamente una feature. El feature activo se resuelve vía `.specify/feature.json`
  (gitignored, local a la máquina); se fuerza con `SPECIFY_FEATURE_DIRECTORY=<path>`. En monorepos: `SPECIFY_INIT_DIR`.
- `/speckit.implement` exige `plan.md` y `tasks.md` existentes y checklists completos en
  `specs/<feature>/checklists/`; si faltan, pregunta antes de continuar.
- `speckit.plan` y `speckit.tasks` leen `.specify/memory/constitution.md` (ratificada, v1.0.0).
  Enmiéndala con `/speckit.constitution` si cambian los principios.
- Hooks de extensiones se leen de `.specify/extensions.yml` (no existe hoy).
- Comandos auxiliares: `/speckit.clarify`, `/speckit.checklist`, `/speckit.converge`, `/speckit.analyze`, `/speckit.taskstoissues`.

## Datos del dominio (costosos de reconstruir)
- App objetivo: Python (`mcp>=1.0.0` que incluye FastMCP, `httpx`, `pydantic`); MCP por stdio;
  Docker Python; ingesta automática del corpus POT al iniciar.
- Herramientas MCP planeadas: `resolve_lot_by_chip`, `resolve_lot_by_address`,
  `resolve_lot_by_coordinates`, `get_lot_summary_by_chip`, `get_feasibility_report`.
- API de búsqueda: `https://catalogopmb.catastrobogota.gov.co/PMBWeb/web/buscar` con
  `cmd=direccion_chip&query=<CHIP>&spatialReference=102100`. Geocodificar/geocodificar_inverso
  usan `https://catalogopmb.catastrobogota.gov.co/PMBWeb/web/api` y requieren
  `MAPAS_BOGOTA_APIKEY`.
- ArcGIS REST: `https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/`:
  - `Mapa_Referencia/Mapa_Referencia/MapServer` → **Lote = capa 38** (`LOTCODIGO`, `MANZCODIGO`), **UPL = capa 44**
  - Temáticas: `catastro/valorreferencia`, `ordenamientoterritorial/reservavial`,
    `gestionpublica/obraspublicas`. `catastro/destinolt` se retiró del contexto: el
    servicio en vivo responde 500 ("not started") y puede reincorporarse cuando vuelva
    (ver `app/providers/arcgis.py`).
  - Consultas: `f=geojson`, `geometry=<lng,lat>&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects`; metadatos con `f=pjson`
- RAG normativo: corpus = Decreto 555 de 2021 (POT "Bogotá Reverdece 2022-2035") + micrositio POT +
  compendio de Datos Abiertos; chunks con metadatos (norma, artículo, tema, vigencia, jerarquía, territorio/UPL); almacén JSONL.

## Convenciones
- Todo el dominio está en español: especifica, documenta y comenta en español.
- Salida para el LLM: JSON estructurado con trazabilidad por fuente (`source_name`, `layer_id`,
  `service_url`, `data_vigencia`, `query_timestamp`). No mezclar capas de vigencias distintas
  como una sola fotografía temporal.
- El `feasibility_score` es heurístico: el LLM no debe inferir reglas urbanísticas ausentes en la fuente.
