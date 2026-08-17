# Quickstart: Enriquecimiento del Informe de Factibilidad con 5 Nuevas Fuentes ArcGIS

**Fase**: Feature 6 | **Fecha**: 2026-08-17
**Feature**: [spec.md](spec.md)
**Naturaleza**: guía de **validación** (escenarios ejecutables + resultados esperados).

## Prerrequisitos

1. **Python 3.11+** y proyecto instalado en modo editable:
   ```bash
   pip install -e ".[dev]"
   ```
2. **Variables de entorno** (`.env`, ver `.env.example`):
   - `MAPAS_BOGOTA_APIKEY` (opcional, solo para resolución por dirección).
   - `OLLAMA_BASE_URL`, `OLLAMA_EMBEDDING_MODEL=bge-m3`, `OLLAMA_CHAT_MODEL`,
     `VECTOR_DB_PATH=.data/chroma` (solo para evidencia normativa).
3. **Servidor MCP levantado**: `get_feasibility_report` es la 7ª tool.

## Escenarios de validación end-to-end

### E1. Reporte por CHIP con los 5 bloques nuevos

**Tool**: `get_feasibility_report`

```json
{ "chip": "AAA0072LRYN" }
```

**Resultado esperado**:
- Los 15 bloques del reporte están presentes: `lot_identity`, `administrative_context`, `planning_constraints`, `market_context`, `environment_context`, `economic_context`, `geotechnical_risks`, `socioeconomic_context`, `regulatory_environment`, `cultural_heritage`, `transit_access`, `normative_evidence`, `feasibility_score`, `warnings`, `query_timestamp`.
- Cada bloque nuevo tiene `estado` (`"disponible"` o `"no_encontrado"`), `dato`, `interpretation` y `source_trace` con 5 campos.
- `feasibility_score.rules_applied` incluye los códigos nuevos (`r_contexto_socio`, `r_acceso_movilidad`, etc.) cuando corresponden.

### E2. Bloque geotechnical_risks con datos

**Tool**: `get_feasibility_report`

```json
{ "chip": "AAA0072LRYN" }
```

**Resultado esperado**:
- `geotechnical_risks.estado == "disponible"` (si el lote tiene clasificación geotécnica).
- `geotechnical_risks.dato.nivel_amenaza` ∈ `["alto", "medio", "bajo", "desconocido"]`.
- `geotechnical_risks.interpretation` describe la clasificación.

### E3. Bloque socioeconomic_context con estrato

**Tool**: `get_feasibility_report`

```json
{ "chip": "AAA0072LRYN" }
```

**Resultado esperado**:
- `socioeconomic_context.dato.estrato` es un entero (p. ej., 3, 4).
- `socioeconomic_context.dato.uso_predominante` es un texto si la capa tiene dato.

### E4. Bloque transit_access con conteos

**Tool**: `get_feasibility_report`

```json
{ "chip": "AAA0072LRYN" }
```

**Resultado esperado**:
- `transit_access.dato.estaciones_transmilenio` es un entero ≥ 0 (o `null` si la capa falló).
- `transit_access.dato.paraderos_sitp` es un entero ≥ 0 (o `null`).
- `transit_access.dato.estaciones_metro` es un entero ≥ 0 (o `null`).

### E5. Degradación de un bloque

**Condición**: una de las capas de un bloque falla (simular en tests con `MockTransport` retornando 500).

**Resultado esperado**:
- El bloque afectado tiene `estado: "no_encontrado"` si todas las capas fallaron, o `estado: "disponible"` con los sub-bloques disponibles en `None`.
- `warnings` incluye `BLOQUE_DEGRADADO` o `BLOQUE_SIN_DATO`.
- Los demás bloques (incluidos los de F3) no se afectan.

### E6. Determinismo del scoring (SC-003)

Dos llamadas idénticas con la misma configuración:

```json
{ "chip": "AAA0072LRYN" }
```

**Resultado esperado**: `feasibility_score` **idéntico** (mismo `score`, `confidence` y `reasons`) en ambas.

### E7. Scoring con reglas nuevas

**Tool**: `get_feasibility_report`

```json
{ "chip": "AAA0072LRYN" }
```

**Resultado esperado**:
- Si `geotechnical_risks.dato.nivel_amenaza == "alto"`, entonces `rules_applied` incluye `"r_riesgo_geotec_alto"` y `reasons` documenta la penalización.
- Si `socioeconomic_context.estado == "disponible"`, entonces `rules_applied` incluye `"r_contexto_socio"`.

### E8. Trazabilidad de 5 campos

Verificar que cada bloque nuevo (`geotechnical_risks`, `socioeconomic_context`, `regulatory_environment`, `cultural_heritage`, `transit_access`) incluya `source_trace` con los 5 campos: `source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp`.

## Fuera de alcance

- **Parámetros de radio**: los radios (800 m TM/Metro, 500 m SITP) no son parámetros del contrato.
- **Nuevas tools MCP**: F6 no añade tools; solo enriquece `get_feasibility_report`.
- **Modificación de F1/F2/F3/F4/F5**: los contratos existentes no se modifican.
