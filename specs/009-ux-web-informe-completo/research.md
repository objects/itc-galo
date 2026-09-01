# Research: UX Web — Informe Completo de Factibilidad

**Feature**: `specs/009-ux-web-informe-completo` | **Date**: 2026-08-31

## Objetivo

Determinar cómo renderizar el informe completo de factibilidad (20 bloques) en la interfaz web
de prefactibilidad (Feature 5) sin cambiar el contrato del informe ni las 7 tools MCP.

## Hallazgos

### R1. El informe ya está persistido como dict JSON
`Proyecto.informe` (SQLite, F5) guarda el resultado de `get_feasibility_report` como dict
serializado. La página de detalle (`GET /proyectos/{id}`) ya lo pasa a la plantilla como
`proyecto.informe`. No hay llamadas de red adicionales para renderizar el detalle.

### R2. Estructura del informe (contrato F3)
El dict del informe usa claves snake_case:
- `lot_identity` (IdentidadLote: `chip`, `codigo_catastral`, `manzana`, `direccion_normalizada`,
  `barrio`, `geometry`, `centroid`{`lat`,`lng`}, `source_trace`)
- `administrative_context` (UPL `codigo`/`nombre`, localidad `nombre`, `clasificacion_suelo`)
- 14 bloques de contexto, cada uno `{estado, dato, interpretation, source_trace, source_traces?}`
- `normative_evidence` (`items`[] con `articulo`, `titulo`, `libro`, `parte`, `texto_cita`,
  `norma`, `source_name`; `causa` opcional)
- `feasibility_score` (`score`, `confidence`, `reasons`, `rules_applied`)
- `warnings`[] (`codigo`, `mensaje`)
- `llm_ready_summary` (párrafo determinista)
- `query_timestamp`

### R3. Trampa de Jinja con claves de dict
En Jinja, `evidencia.items` sobre un dict resuelve al **método** `dict.items` (builtin), no a la
clave `"items"`. Para acceder a la clave hay que usar `evidencia["items"]`. Es la única clave del
informe que colisiona con un método de dict.

### R4. Mapa Leaflet sin CDN
Leaflet 1.9.4 se vendoriza en `app/web/static/` (`leaflet.js` 147552 B, `leaflet.css` 14806 B).
La capa base usa tiles de OSM (`https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png`). La
geometría y el centroide se pasan al JS vía `data-attributes` en el contenedor del mapa usando
`tojson` (escapa `'`→`\u0027`, seguro en atributos de comillas simples). El JS inicializa el mapa
solo si existen ambos (`if (!geometry || !centroid) return;`).

### R5. Filtro `json_pretty`
`tojson` escapa caracteres de forma fea dentro de `<pre>`. Se registra un filtro Jinja
`json_pretty` (`json.dumps(v, ensure_ascii=False, indent=2)`) en `app/web/main.py` para volcar
los datos de cada bloque como JSON legible.

### R6. Bloques `estilos_extra`/`scripts_extra`
`base.html` no tenía bloques para inyectar CSS/JS por plantilla. Se añaden `estilos_extra` en
`<head>` (para `leaflet.css`) y `scripts_extra` antes de `</body>` (para `leaflet.js` + init JS).

## Decisiones

- **D1**: Reescribir `proyecto.html` para volcar los 20 bloques (identidad, mapa, 14 bloques de
  contexto, evidencia, score, advertencias) con la identidad "Bogotá Reverdece".
- **D2**: Usar `informe["items"]` (no `informe.items`) para la evidencia normativa.
- **D3**: Vendorizar Leaflet; sin CDN en runtime.
- **D4**: Pasar geometría/centroide al JS vía `data-attributes` + `tojson`.
- **D5**: Registrar el filtro `json_pretty` para el volcado JSON legible.
- **D6**: No cambiar el contrato del informe ni las 7 tools MCP (SC-005).

## Riesgos

- **Riesgo A**: `tojson` en atributos — mitigado con comillas simples + `tojson` (escapa `'`).
- **Riesgo B**: Claves de bloque ausentes en el dict → `UndefinedError`. Mitigado: el contrato
  garantiza las 14 claves (None ok); el test `_informe_sin_geometria` cubre el caso mínimo.
- **Riesgo C**: Leaflet sin red en tests → el init JS se incluye pero no se ejecuta en pytest
  (solo se verifica el HTML renderizado).
