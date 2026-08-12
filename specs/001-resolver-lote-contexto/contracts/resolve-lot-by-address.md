# Contrato: `resolve_lot_by_address`

**Feature**: [Resolver lote con contexto temático](../spec.md)
**Tool MCP**: `resolve_lot_by_address`
**Fecha**: 2026-08-10 | **Estado**: Aprobado en plan

## Propósito

Resuelve un lote catastral de Bogotá a partir de una **dirección**, localizándola primero
dentro de Bogotá (geocodificación) y consultando luego la capa Lote con el punto resultante
(FR-002). La geocodificación requiere `MAPAS_BOGOTA_APIKEY`; si falta la credencial, la
tool falla rápido (fail-fast) sin consultar las fuentes (FR-010).

Si la dirección no puede localizarse (no encontrada o ambigua), la tool responde
`DIRECCION_NO_LOCALIZADA` sin inventar ni asumir un lote. Si la dirección corresponde a
**más de un lote candidato**, la tool presenta los candidatos o solicita precisión
adicional, en lugar de elegir uno arbitrariamente (Historia de Usuario 2, P2).

## Entrada (input)

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["address"],
  "properties": {
    "address": {
      "type": "string",
      "minLength": 1,
      "description": "Dirección en Bogotá a localizar, p. ej. 'Calle 26 # 69-76'."
    }
  }
}
```

### Reglas de validación (FR-012) y precondiciones

- `address` es obligatoria y no puede ser vacía ni solo espacios → si lo es,
  `PARAMETROS_INVALIDOS` (fail-fast).
- **Precondición**: si `MAPAS_BOGOTA_APIKEY` no está configurada en el entorno → la tool
  falla rápido con `CREDENCIAL_FALTANTE`, sin llamar a las fuentes. Las consultas por CHIP
  y por coordenadas no se ven afectadas (FR-010).

## Salida (output)

### JSON Schema (resolución única)

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
      "required": ["chip", "codigo_catastral", "manzana", "direccion_normalizada", "geometry", "centroid", "source_trace"],
      "properties": {
        "chip": { "type": "string", "pattern": "^[A-Z0-9]{11}$" },
        "codigo_catastral": { "type": "string", "description": "LOTCODIGO de la capa Lote." },
        "manzana": { "type": "string", "description": "MANZCODIGO de la capa Lote." },
        "direccion_normalizada": { "type": "string", "description": "Dirección normalizada devuelta por la geocodificación." },
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
      "required": ["valor_referencia", "reserva_vial", "obras_publicas"],
      "properties": {
        "valor_referencia": { "$ref": "#/definitions/dato_tematico" },
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
        "estado": { "type": "string", "enum": ["disponible", "no_encontrado"] },
        "dato": { "type": ["object", "null"], "description": "Contenido de la fuente (ver data-model.md). null si estado=no_encontrado." },
        "source_trace": { "$ref": "#/definitions/source_trace" }
      }
    },
    "source_trace": {
      "type": "object",
      "additionalProperties": false,
      "required": ["source_name", "layer_id", "service_url", "data_vigencia", "query_timestamp"],
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

### JSON Schema (múltiples candidatos)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["multiples_candidatos", "candidatos", "source_trace"],
  "properties": {
    "multiples_candidatos": {
      "type": "boolean",
      "const": true
    },
    "candidatos": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["direccion_normalizada", "centroid"],
        "properties": {
          "direccion_normalizada": { "type": "string" },
          "centroid": {
            "type": "object",
            "required": ["lat", "lng"],
            "properties": {
              "lat": { "type": "number" },
              "lng": { "type": "number" }
            }
          }
        }
      }
    },
    "mensaje": {
      "type": "string",
      "description": "Solicitud de precisión adicional en español, p. ej. 'La dirección tiene varios candidatos. Refina la dirección para elegir uno.'"
    },
    "source_trace": {
      "type": "object",
      "additionalProperties": false,
      "required": ["source_name", "layer_id", "service_url", "data_vigencia", "query_timestamp"],
      "properties": {
        "source_name": { "type": "string", "description": "mapas_bogota" },
        "layer_id": { "type": "string", "description": "geocodificar" },
        "service_url": { "type": "string", "format": "uri" },
        "data_vigencia": { "type": "string" },
        "query_timestamp": { "type": "string", "format": "date-time" }
      }
    }
  }
}
```

### Trazabilidad

- El `lote.source_trace` documenta la capa Lote (`Mapa_Referencia/Mapa_Referencia`,
  `layer_id=38`); la geocodificación agrega un trace de la API de Mapas Bogotá
  (`mapas_bogota`, `layer_id=geocodificar`) como fuente de la localización.
- La respuesta de múltiples candidatos lleva su propio `source_trace` con los **5 campos**
  de la geocodificación (`mapas_bogota`, `layer_id=geocodificar`), igual que la resolución única.
- Cada bloque temático adjunta su propio `source_trace` con los **5 campos** y su
  `data_vigencia` (FR-006, FR-008, SC-003/SC-004).

## Estados de error

| Código | Condición | Mensaje (español) |
|--------|-----------|-------------------|
| `DIRECCION_NO_LOCALIZADA` | La dirección no pudo geocodificarse (no encontrada o ambigua). | `La dirección no pudo localizarse. Refina la dirección o usa CHIP/coordenadas.` |
| `CREDENCIAL_FALTANTE` | Falta `MAPAS_BOGOTA_APIKEY` (fail-fast). | `Falta la variable MAPAS_BOGOTA_APIKEY para consultas por dirección. Configúrala en .env.` |
| `PARAMETROS_INVALIDOS` | Dirección vacía o tipo incorrecto. | `Parámetros inválidos: la dirección no puede estar vacía.` |
| `FUENTE_5XX` | La API de Mapas Bogotá o una capa ArcGIS responde 5xx. | `La fuente <source_name> no está disponible (error <status>). Intenta nuevamente.` |

Un error 5xx **nunca** se confunde con `DIRECCION_NO_LOCALIZADA` ni con
`LOTE_NO_ENCONTRADO` (FR-009). La dirección ambigua **no** produce `DIRECCION_NO_LOCALIZADA`
como error fatal: se responde el caso de múltiples candidatos (ver JSON Schema de salida).

## Referencias cruzadas al spec

| Requisito | Descripción |
|-----------|-------------|
| FR-002 | Resolución por dirección; no inventar lote. |
| FR-004 | Contexto temático del lote resuelto. |
| FR-006 | Trazabilidad de 5 campos por dato. |
| FR-007 | Distinción `disponible` / `no_encontrado` por fuente. |
| FR-009 | Error explícito ante 5xx de la fuente. |
| FR-010 | Fail-fast sin `MAPAS_BOGOTA_APIKEY`; CHIP/coordenadas siguen funcionando. |
| FR-012 | Rechazo de dirección vacía. |
| SC-006 | Dirección no localizable termina en error claro. |
