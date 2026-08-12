# Contrato: `resolve_lot_by_coordinates`

**Feature**: [Resolver lote con contexto temático](../spec.md)
**Tool MCP**: `resolve_lot_by_coordinates`
**Fecha**: 2026-08-10 | **Estado**: Aprobado en plan

## Propósito

Resuelve el lote catastral de Bogotá que **contiene un punto** indicado por coordenadas
geográficas (WGS84, SRID 4326), consultando directamente la capa Lote de ArcGIS con el
punto (FR-003). No requiere credencial (`MAPAS_BOGOTA_APIKEY` no aplica a esta tool).

Si el punto está fuera del área de Bogotá, responde `FUERA_DE_COBERTURA`. Si el punto cae
sobre el límite entre dos o más lotes, la tool indica que **no hay un lote único**, sin
elegir arbitrariamente (Historia de Usuario 3, P3).

El `chip` del lote resuelto puede ser `null`: las capas catastrales de ArcGIS no publican el
campo CHIP (este solo proviene de la API de Mapas Bogotá), así que la identidad del lote se
soporta en `codigo_catastral` (LOTCODIGO) y `manzana` (MANZCODIGO), que son siempre
obligatorios.

## Entrada (input)

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["latitude", "longitude"],
  "properties": {
    "latitude": {
      "type": "number",
      "minimum": -90,
      "maximum": 90,
      "description": "Latitud del punto en grados decimales (WGS84)."
    },
    "longitude": {
      "type": "number",
      "minimum": -180,
      "maximum": 180,
      "description": "Longitud del punto en grados decimales (WGS84)."
    }
  }
}
```

### Reglas de validación (FR-012)

- `latitude` y `longitude` son obligatorias y de tipo `number`.
- Rango válido: `latitude` ∈ [-90, 90], `longitude` ∈ [-180, 180]. Fuera de rango →
  `PARAMETROS_INVALIDOS` (fail-fast, sin llamar a las fuentes).
- Un punto dentro de rango pero fuera del área de Bogotá **no** es un parámetro inválido:
  produce `FUERA_DE_COBERTURA` tras la consulta espacial.

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
        "chip": { "type": ["string", "null"], "pattern": "^[A-Z0-9]{11}$", "description": "CHIP del predio si la fuente lo provee; null cuando la capa Lote no lo trae (identidad vía codigo_catastral/manzana)." },
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

### Trazabilidad

- El `lote.source_trace` documenta la capa Lote (`Mapa_Referencia/Mapa_Referencia`,
  `layer_id=38`), única fuente usada para la resolución por coordenadas.
- Cada bloque temático adjunta su propio `source_trace` con los **5 campos** y su
  `data_vigencia` (FR-006, FR-008, SC-003/SC-004).

## Estados de error

| Código | Condición | Mensaje (español) |
|--------|-----------|-------------------|
| `FUERA_DE_COBERTURA` | El punto está fuera del área de Bogotá. | `El punto (<lat>, <lng>) está fuera del área de cobertura (Bogotá).` |
| `LOTE_NO_ENCONTRADO` | El punto cae en límite entre lotes (sin lote único). | `No se encontró un lote único para el punto (<lat>, <lng>).` |
| `PARAMETROS_INVALIDOS` | Coordenadas fuera de rango o tipo incorrecto. | `Parámetros inválidos: latitud debe estar entre -90 y 90 y longitud entre -180 y 180.` |
| `FUENTE_5XX` | La capa Lote o una capa ArcGIS responde 5xx. | `La fuente <source_name> no está disponible (error <status>). Intenta nuevamente.` |

Un error 5xx **nunca** se confunde con `LOTE_NO_ENCONTRADO` ni con `FUERA_DE_COBERTURA`
(FR-009): un 5xx es un fallo del servidor de la fuente y la respuesta lo identifica.

## Referencias cruzadas al spec

| Requisito | Descripción |
|-----------|-------------|
| FR-003 | Resolución por coordenadas dentro de Bogotá; error claro fuera de cobertura. |
| FR-004 | Contexto temático del lote resuelto. |
| FR-006 | Trazabilidad de 5 campos por dato. |
| FR-007 | Distinción `disponible` / `no_encontrado` por fuente. |
| FR-009 | Error explícito ante 5xx de la fuente. |
| FR-012 | Rechazo de coordenadas fuera de rango. |
| SC-006 | Coordenadas fuera de Bogotá terminan en error claro. |
