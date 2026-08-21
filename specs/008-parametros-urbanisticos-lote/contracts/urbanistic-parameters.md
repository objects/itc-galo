# Contrato: Bloque urbanistic_parameters (Feature 8)

**Feature**: [spec.md](spec.md) | **Fecha**: 2026-08-20

## Bloque nuevo en `get_feasibility_report`

El bloque `urbanistic_parameters` se añade al contrato existente de F3+F6+F7 (15 bloques → 16 bloques). La tool `get_feasibility_report` NO cambia su firma; solo se enriquece la respuesta. También se añade a `get_lot_summary_by_chip` (FR-020).

### urbanistic_parameters

```json
{
  "estado": "disponible | no_encontrado",
  "dato": {
    "tratamiento": {
      "denominacion": "string",
      "codigo_capa": "string | null"
    },
    "edificabilidad": {
      "cos": "float | null",
      "cus": "float | null",
      "altura_maxima_m": "float | null"
    },
    "retiros": {
      "frontal_m": "float | null",
      "laterales_m": "float | null",
      "posteriores_m": "float | null"
    },
    "estacionamientos": {
      "requeridos": "integer | null",
      "criterio": "string | null"
    }
  },
  "interpretation": "string",
  "source_trace": {
    "source_name": "SINUPOT — Norma Urbanística y OT",
    "layer_id": "2",
    "service_url": "https://sinu.sdp.gov.co/serverp/rest/services/POT555/NORMA_URBANÍSTICA_Y_OT/MapServer",
    "data_vigencia": "2021",
    "query_timestamp": "2026-08-20T00:00:00Z"
  }
}
```

### Estados del bloque

| Estado | Condición | `dato` |
|--------|-----------|--------|
| `disponible` | SDP responde con tratamiento Y al menos un campo numérico del RAG | Objeto `ParametrosUrbanisticos` con tratamiento + sub-modelos |
| `disponible` | SDP responde con tratamiento pero campos numéricos `None` | Objeto con tratamiento y sub-modelos en `None` |
| `no_encontrado` | SDP falla o no tiene features para el lote | `None` |

### Degradación por fuente

| Fuente | Éxito | Fallo |
|--------|-------|-------|
| SDP (tratamiento) | Tratamiento poblado en `dato` | Bloque `no_encontrado` + warning `BLOQUE_DEGRADADO` |
| RAG (parámetros numéricos) | Campos COS/CUS/altura/retiros/estacionamientos poblados | Campos en `None`, bloque mantiene `disponible` si tratamiento OK |

**Regla FR-009**: un 5xx de SDP NO se trata como "no encontrado" si el RAG respondió. El bloque mantiene estado `disponible` con tratamiento del SINUPOT y campos numéricos del RAG.

### Warnings

| Código | Condición |
|--------|-----------|
| `BLOQUE_DEGRADADO` | SDP falla (5xx, timeout, error de red) |
| `BLOQUE_SIN_DATO` | SDP responde pero sin features para el lote |

### Scoring extension

| Regla | Tipo | Puntos | Condición |
|-------|------|--------|-----------|
| `r_parametros_urbanisticos` | Positiva | +10 | `tratamiento` y `edificabilidad` disponibles |
| `r_estacionamientos_calculados` | Positiva | +5 | `estacionamientos.requeridos > 0` |
| `r_tratamiento_conservacion` | Negativa | −15 | `tratamiento.denominacion == "Conservación"` |

**Bloques evaluables**: 13 (12 actuales + `urbanistic_parameters`).

### Interpretaciones (deterministas, FR-014)

Patrón de generación de `interpretation`:

- **Tratamiento disponible**: `"Tratamiento urbanístico del lote: <denominación> (SINUPOT layer 2). COS: <valor>, CUS: <valor>, altura máxima: <valor> m."`
- **Solo tratamiento**: `"Tratamiento urbanístico del lote: <denominación>. Los parámetros numéricos (COS, CUS, altura, retiros, estacionamientos) no están disponibles en el corpus normativo."`
- **Sin datos**: `"No se encontró un tratamiento urbanístico para el lote en la fuente consultada."`

### Consulta RAG para parámetros urbanísticos

**Prompt** (construido por reglas en `app/main.py`):

```
¿Cuáles son los valores de COS, CUS, altura máxima (en metros), retiros frontales,
laterales y posteriores (en metros), y estacionamientos requeridos para un lote con
tratamiento urbanístico "<tratamiento>" en la UPL <codigo_upl>? Cita los artículos
y valores exactos del POT.
```

**Parsing regex** de la respuesta del LLM:

| Campo | Patrón | Ejemplo |
|-------|--------|---------|
| COS | `COS[:\s]+(\d+\.?\d*)` | `COS: 0.70` |
| CUS | `CUS[:\s]+(\d+\.?\d*)` | `CUS: 2.80` |
| Altura | `altura[:\s]+(\d+\.?\d*)\s*m` | `altura máxima: 24 m` |
| Retiro frontal | `frontal[:\s]+(\d+\.?\d*)\s*m` | `retiro frontal: 5 m` |
| Retiro laterales | `laterales[:\s]+(\d+\.?\d*)\s*m` | `retiros laterales: 3 m` |
| Retiro posterior | `posterior[:\s]+(\d+\.?\d*)\s*m` | `retiro posterior: 4 m` |
| Estacionamientos | `(\d+)\s*estacionamiento` | `4 estacionamientos` |

Si un patrón no matchea, el campo queda `None`.

### No-regresión

- Las 7 tools existentes mantienen su contrato sin cambios (SC-005).
- Los 15 bloques existentes del informe no cambian (FR-013).
- El `feasibility_score` sigue siendo 100% determinístico (SC-003).
- No se añaden variables de entorno nuevas (SDP_BASE_URL es constante).
