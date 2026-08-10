# Contrato: `resolve_lot_by_chip`

**Feature**: [Resolver lote con contexto temático](../spec.md)
**Tool MCP**: `resolve_lot_by_chip`
**Fecha**: 2026-08-10 | **Estado**: Aprobado en plan

## Propósito

Resuelve un lote catastral de Bogotá a partir de su **CHIP** (identificador oficial del
predio) y devuelve la identidad del lote (CHIP, código catastral, manzana, dirección
normalizada cuando esté disponible), su geometría/centroide con trazabilidad y el contexto
temático asociado (valor de referencia, destino económico, reserva vial y obras públicas)
con su estado `disponible` / `no_encontrado` y su trazabilidad por fuente (FR-001, FR-004).

Es la vía de menor fricción y la que entrega el valor principal de la feature: el resumen
consolidado (Historia de Usuario 1, P1).

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
      "description": "CHIP del predio catastral de Bogotá.",
      "pattern": "^[A-Z0-9]{11}$",
      "examples": ["AAA0072LRYN"]
    }
  }
}
```

### Reglas de validación (FR-012)

- `chip` es obligatorio y debe ser `string` de **exactamente 11 caracteres alfanuméricos en
  mayúsculas** (`^[A-Z0-9]{11}$`). Si no cumple el formato → `PARAMETROS_INVALIDOS`, sin
  llamar a las fuentes (fail-fast).

## Salida (output)

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["lote", "contexto_tematico"],
  "properties": {
    "lote": {
      "type": "object",
      "additionalProperties": false,
      "required": ["chip", "codigo_catastral", "manzana", "geometry", "centroid", "source_trace"],
      "properties": {
        "chip": { "type": "string", "pattern": "^[A-Z0-9]{11}$" },
        "codigo_catastral": { "type": "string", "description": "LOTCODIGO de la capa Lote." },
        "manzana": { "type": "string", "description": "MANZCODIGO de la capa Lote." },
        "direccion_normalizada": { "type": ["string", "null"] },
        "barrio": { "type": ["string", "null"] },
        "geometry": { "type": "object", "description": "Geometría GeoJSON del lote (SRID 4326)." },
        "centroid": {
          "type": "object",
          "required": ["lat", "lng"],
          "properties": {
            "lat": { "type": "number", "minimum": -90, "maximum": 90 },
            "lng": { "type": "number", "minimum": -180, "maximum": 180 }
          }
        },
        "source_trace": { "$ref": "#/definitions/source_trace" }
      }
    },
    "contexto_tematico": {
      "type": "object",
      "additionalProperties": false,
      "required": ["valor_referencia", "destino_economico", "reserva_vial", "obras_publicas"],
      "properties": {
        "valor_referencia": { "$ref": "#/definitions/dato_tematico" },
        "destino_economico": { "$ref": "#/definitions/dato_tematico" },
        "reserva_vial": { "$ref": "#/definitions/dato_tematico" },
        "obras_publicas": { "$ref": "#/definitions/dato_tematico" }
      }
    }
  },
  "definitions": {
    "dato_tematico": {
      "type": "object",
      "additionalProperties": false,
      "required": ["estado", "dato", "source_trace"],
      "properties": {
        "estado": {
          "type": "string",
          "enum": ["disponible", "no_encontrado"],
          "description": "FR-007: un dato ausente o no aplicable se reporta como no_encontrado, nunca como cero ni vacío silencioso."
        },
        "dato": { "type": ["object", "null"], "description": "Contenido de la fuente (ver data-model.md). null si estado=no_encontrado." },
        "source_trace": { "$ref": "#/definitions/source_trace" }
      }
    },
    "source_trace": {
      "type": "object",
      "additionalProperties": false,
      "required": ["source_name", "layer_id", "service_url", "data_vigencia", "query_timestamp"],
      "description": "Trazabilidad de 5 campos (FR-006, Principio III). Obligatoria en cada dato, incluida la marca de tiempo de la consulta.",
      "properties": {
        "source_name": { "type": "string", "description": "Nombre canónico de la fuente." },
        "layer_id": { "type": "string", "description": "Capa/tema dentro del servicio." },
        "service_url": { "type": "string", "format": "uri" },
        "data_vigencia": { "type": "string", "description": "Vigencia del dato en la fuente (fecha ISO o año)." },
        "query_timestamp": { "type": "string", "format": "date-time", "description": "Marca de tiempo de la consulta (ISO 8601 UTC)." }
      }
    }
  }
}
```

### Trazabilidad

- El `lote.source_trace` documenta la capa Lote (`Mapa_Referencia/Mapa_Referencia`,
  `layer_id=38`) y, cuando aplique, la búsqueda por CHIP de Mapas Bogotá
  (`mapas_bogota`, `layer_id=direccion_chip`).
- Cada bloque temático adjunta su propio `source_trace` con los **5 campos** y su
  `data_vigencia` (FR-006, FR-008, SC-003/SC-004). Nunca se mezclan vigencias distintas
  como una sola fotografía temporal.

## Estados de error

| Código | Condición | Mensaje (español) |
|--------|-----------|-------------------|
| `LOTE_NO_ENCONTRADO` | El CHIP no resuelve a ningún lote en las fuentes. | `No se encontró ningún lote para el CHIP <chip>. Verifica el identificador.` |
| `PARAMETROS_INVALIDOS` | CHIP mal formado (formato, tipo o ausencia). | `Parámetros inválidos: el CHIP debe tener 11 caracteres alfanuméricos.` |
| `FUENTE_5XX` | La API de Mapas Bogotá o una capa ArcGIS responde 5xx. | `La fuente <source_name> no está disponible (error <status>). Intenta nuevamente.` |

El error 5xx **nunca** se reporta como "lote no encontrado" ni como "dato no encontrado"
(FR-009): un 5xx es un fallo del servidor de la fuente y la respuesta lo identifica.

## Referencias cruzadas al spec

| Requisito | Descripción |
|-----------|-------------|
| FR-001 | Identidad del lote por CHIP. |
| FR-004 | Contexto temático (valor, destino, reserva vial, obras públicas). |
| FR-006 | Trazabilidad de 5 campos por dato. |
| FR-007 | Distinción `disponible` / `no_encontrado` por fuente. |
| FR-008 | No mezclar vigencias. |
| FR-009 | Error explícito ante 5xx de la fuente. |
| FR-012 | Rechazo de CHIP mal formado. |
| SC-001 | Resumen con CHIP válido en < 10 s. |
| SC-005 | 100% de consultas con CHIP válido entregan resumen. |
| SC-006 | CHIP inexistente termina en error claro. |
