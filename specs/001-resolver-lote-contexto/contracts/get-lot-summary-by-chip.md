# Contrato: `get_lot_summary_by_chip`

**Feature**: [Resolver lote con contexto temático](../spec.md)
**Tool MCP**: `get_lot_summary_by_chip`
**Fecha**: 2026-08-10 | **Estado**: Aprobado en plan

## Propósito

Genera el **resumen consolidado** de un lote a partir de su CHIP: identidad del lote y
contexto temático por fuente (valor de referencia, destino económico, reserva vial y obras
públicas), donde **cada dato** incluye su trazabilidad de **5 campos** y su estado
`disponible` / `no_encontrado` (FR-005, FR-006, FR-007). El resumen es **descriptivo**: no
calcula puntajes de factibilidad ni infiere reglas urbanísticas ausentes en las fuentes
(FR-011).

Es la salida principal para el LLM consumidor (Historia de Usuario 1, P1; SC-005).

Nota: `identidad` omite `geometry` deliberadamente — el resumen es descriptivo (FR-011);
la entidad completa `Lote` (incluida su geometría) se documenta en data-model.md.

## Entrada (input)

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["chip"],
  "properties": {
    "chip": {
      "type": "string",
      "pattern": "^[A-Z0-9]{11}$",
      "description": "CHIP del predio catastral de Bogotá.",
      "examples": ["AAA0072LRYN"]
    }
  }
}
```

### Reglas de validación (FR-012)

- `chip` es obligatorio y debe ser `string` de **exactamente 11 caracteres alfanuméricos en
  mayúsculas** (`^[A-Z0-9]{11}$`). Si no cumple el formato → `PARAMETROS_INVALIDOS`
  (fail-fast, sin llamar a las fuentes).

## Salida (output)

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["identidad", "contexto_por_fuente"],
  "properties": {
    "identidad": {
      "type": "object",
      "additionalProperties": false,
      "required": ["chip", "codigo_catastral", "manzana", "direccion_normalizada", "centroid", "source_trace"],
      "properties": {
        "chip": { "type": "string", "pattern": "^[A-Z0-9]{11}$" },
        "codigo_catastral": { "type": "string", "description": "LOTCODIGO de la capa Lote." },
        "manzana": { "type": "string", "description": "MANZCODIGO de la capa Lote." },
        "direccion_normalizada": { "type": ["string", "null"] },
        "centroid": {
          "type": "object",
          "required": ["lat", "lng"],
          "properties": {
            "lat": { "type": "number" },
            "lng": { "type": "number" }
          }
        },
        "source_trace": { "$ref": "#/definitions/source_trace" }
      }
    },
    "contexto_por_fuente": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["fuente", "estado", "dato", "source_trace"],
        "properties": {
          "fuente": {
            "type": "string",
            "enum": ["valor_referencia", "destino_economico", "reserva_vial", "obras_publicas"]
          },
          "estado": {
            "type": "string",
            "enum": ["disponible", "no_encontrado"],
            "description": "FR-007: dato ausente o no aplicable se reporta como no_encontrado, nunca como cero ni vacío silencioso."
          },
          "dato": { "type": ["object", "null"], "description": "Contenido de la fuente (ver data-model.md). null si estado=no_encontrado." },
          "source_trace": { "$ref": "#/definitions/source_trace" }
        }
      }
    }
  },
  "definitions": {
    "source_trace": {
      "type": "object",
      "additionalProperties": false,
      "required": ["source_name", "layer_id", "service_url", "data_vigencia", "query_timestamp"],
      "description": "Trazabilidad de 5 campos (FR-006, Principio III). Obligatoria en cada dato, incluida la marca de tiempo de la consulta.",
      "properties": {
        "source_name": { "type": "string" },
        "layer_id": { "type": "string" },
        "service_url": { "type": "string", "format": "uri" },
        "data_vigencia": { "type": "string" },
        "query_timestamp": { "type": "string", "format": "date-time" }
      }
    }
  }
}
```

### Trazabilidad

- `identidad.source_trace` documenta la capa Lote (`Mapa_Referencia/Mapa_Referencia`,
  `layer_id=38`) y la búsqueda por CHIP de Mapas Bogotá (`mapas_bogota`,
  `layer_id=direccion_chip`).
- **Cada** entrada de `contexto_por_fuente` incluye su `source_trace` con los **5 campos**
  (FR-006, SC-003; incluye `query_timestamp`, que SC-003 del spec omite y el contrato exige
  siempre) y su `data_vigencia`. Nunca se mezclan vigencias distintas como una sola
  fotografía temporal (FR-008, SC-004).

## Estados de error

| Código | Condición | Mensaje (español) |
|--------|-----------|-------------------|
| `LOTE_NO_ENCONTRADO` | El CHIP no resuelve a ningún lote. | `No se encontró ningún lote para el CHIP <chip>. Verifica el identificador.` |
| `PARAMETROS_INVALIDOS` | CHIP mal formado (formato, tipo o ausencia). | `Parámetros inválidos: el CHIP debe tener 11 caracteres alfanuméricos.` |
| `FUENTE_5XX` | La API de Mapas Bogotá o una capa ArcGIS responde 5xx. | `La fuente <source_name> no está disponible (error <status>). Intenta nuevamente.` |

El error 5xx **nunca** se reporta como "lote no encontrado" ni como `estado="no_encontrado"`
de una fuente (FR-009): un 5xx es un fallo del servidor de la fuente, la respuesta lo
identifica y la consulta puede reintentarse.

## Referencias cruzadas al spec

| Requisito | Descripción |
|-----------|-------------|
| FR-005 | Resumen consolidado estructurado (identidad + contexto temático). |
| FR-006 | Trazabilidad de 5 campos por dato. |
| FR-007 | Distinción `disponible` / `no_encontrado` por fuente. |
| FR-008 | No mezclar vigencias. |
| FR-009 | Error explícito ante 5xx de la fuente. |
| FR-011 | Resumen descriptivo: sin puntajes de factibilidad ni reglas inferidas. |
| FR-012 | Rechazo de CHIP mal formado. |
| SC-001 | Resumen con CHIP válido en < 10 s. |
| SC-002 | 100% de respuestas distinguen disponible/no encontrado. |
| SC-003 | Origen, capa, URL y vigencia en cada dato (el contrato añade `query_timestamp`). |
| SC-004 | Vigencias distintas nunca se presentan como una sola fotografía temporal. |
| SC-005 | 100% de consultas con CHIP válido entregan el resumen. |
| SC-006 | CHIP inexistente termina en error claro. |
