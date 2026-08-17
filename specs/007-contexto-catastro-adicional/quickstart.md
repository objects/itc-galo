# Quickstart: Contexto Catastral Adicional del Lote

**Fase**: Feature 7 | **Fecha**: 2026-08-17
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
3. **Servidor MCP levantado**: las 7 tools están registradas.

## Escenarios de validación

### E1. Informe de factibilidad con el bloque catastro_data

**Tool**: `get_feasibility_report`

```json
{ "chip": "AAA0072LRYN" }
```

**Resultado esperado**:
- Los 16 bloques del reporte están presentes: `lot_identity`, `administrative_context`, `planning_constraints`, `market_context`, `environment_context`, `economic_context`, `geotechnical_risks`, `socioeconomic_context`, `regulatory_environment`, `cultural_heritage`, `transit_access`, `catastro_data`, `normative_evidence`, `feasibility_score`, `warnings`, `query_timestamp`.
- `catastro_data` tiene `estado` (`"disponible"` o `"no_encontrado"`), `dato`, `interpretation` y `source_trace` con 5 campos.

### E2. Resumen del lote con catastro_data

**Tool**: `get_lot_summary_by_chip`

```json
{ "chip": "AAA0072LRYN" }
```

**Resultado esperado**:
- La respuesta incluye `catastro_data` con `estado`, `dato` (con los 5 sub-campos) y `source_trace`.

### E3. Degradación independiente por capa

**Condición**: una de las 5 capas catastrales falla (simular en tests con `MockTransport` retornando 500).

**Resultado esperado**:
- Las capas que respondieron tienen datos; las que fallaron quedan en `None` dentro de `dato`.
- `warnings` incluye `BLOQUE_SIN_DATO` o `BLOQUE_DEGRADADO`.
- Los demás bloques no se afectan.

### E4. Scoring con 12 bloques evaluables

**Tool**: `get_feasibility_report`

```json
{ "chip": "AAA0072LRYN" }
```

**Resultado esperado**:
- `feasibility_score.confidence` se calcula sobre 12 bloques evaluables (no 11).
- Si `catastro_data.estado == "disponible"`, se cuenta como bloque disponible.

## Fuera de alcance

- **Nuevas tools MCP**: F7 no añade tools; solo enriquece `get_feasibility_report` y `get_lot_summary_by_chip`.
- **Modificación de F1/F2/F3/F4/F6**: los contratos existentes no se modifican.
- **Parsing detallado de campos**: los campos de `construccion`, `manzana`, `densidad_predial` y `variacion_area` son diccionarios con los atributos crudos de cada capa; no se traducen a modelos tipados adicionales.
