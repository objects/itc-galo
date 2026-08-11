# Contrato: `get_upl`

**Feature**: [RAG normativo del POT (Decreto 555/2021) con consulta de UPL](../spec.md)
**Tool MCP**: `get_upl`
**Fecha**: 2026-08-10 | **Estado**: Aprobado en plan

## Propósito

Resuelve la **UPL (Unidad de Planeamiento Local)** de un lote catastral de Bogotá por
**CHIP**, **dirección** o **coordenadas** (reutilizando el resolver de lote de F1) y
devuelve el código y el nombre de la UPL y la localidad del lote, con la trazabilidad de la
capa (FR-005, Historia de Usuario 2).

Flujo interno: el criterio de entrada resuelve el `Lote` (provider F1: Mapas Bogotá API +
capa Lote 38) → se toma el centroide → **join espacial punto-en-polígono** contra la capa
UPL del catastro (`unidadplaneamientolocal`, layer 0, `esriSpatialRelIntersects`, research
D2) → se leen `CODIGO_UPL` y `NOMBRE` → se deriva la **localidad** por mapeo
`NOMBRE → localidad` (research D3).

Fallback por coordenadas (Fix E2E): cuando la consulta es por `coordenadas` y el lote no se
resuelve por identidad (la capa Lote 38 no trae CHIP) o el punto cae en el límite entre lotes,
`get_upl` **no** aborta con `LOTE_NO_ENCONTRADO`: consulta la capa UPL directamente por el punto
de entrada (`metodo_resolucion = "punto_directo"`), porque la capa UPL intersecta por geometría
y no depende de la identidad del lote. Si el punto no intersecta ningún lote (fuera de Bogotá)
se conserva `FUERA_DE_COBERTURA`, sin fallback.

## Entrada (input)

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "chip": {
      "type": "string",
      "pattern": "^[A-Z0-9]{11}$",
      "description": "CHIP del predio catastral de Bogotá. Alternativa de entrada 1.",
      "examples": ["AAA0072LRYN"]
    },
    "direccion": {
      "type": "string",
      "minLength": 1,
      "description": "Dirección en Bogotá. Requiere MAPAS_BOGOTA_APIKEY (geocodificación). Alternativa de entrada 2.",
      "examples": ["Calle 26 # 69-76"]
    },
    "coordenadas": {
      "type": "object",
      "additionalProperties": false,
      "required": ["lat", "lon"],
      "description": "Punto geográfico WGS84 (4326). Alternativa de entrada 3.",
      "properties": {
        "lat": { "type": "number", "minimum": -90, "maximum": 90 },
        "lon": { "type": "number", "minimum": -180, "maximum": 180 }
      }
    }
  },
  "oneOf": [
    { "required": ["chip"] },
    { "required": ["direccion"] },
    { "required": ["coordenadas"] }
  ]
}
```

### Reglas de validación (FR-013)

- **Exactamente uno** de `{chip, direccion, coordenadas}` debe estar presente. Cero o más
  de uno → `PARAMETROS_INVALIDOS`, sin llamar a las fuentes (fail-fast).
- `chip` debe ser `string` de **exactamente 11 caracteres alfanuméricos en mayúsculas**
  (`^[A-Z0-9]{11}$`) → `PARAMETROS_INVALIDOS` si no cumple.
- `direccion` debe ser `string` no vacía (después de trim) → `PARAMETROS_INVALIDOS` si está
  en blanco; requiere `MAPAS_BOGOTA_APIKEY` → `CREDENCIAL_FALTANTE` (fail-fast) si no está
  configurada.
- `coordenadas.lat` ∈ [-90, 90] y `coordenadas.lon` ∈ [-180, 180] → `PARAMETROS_INVALIDOS`
  fuera de rango. El punto válido en rango pero fuera de Bogotá produce
  `FUERA_DE_COBERTURA` (no es un parámetro inválido).

## Salida (output)

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["metodo_resolucion", "upl", "trazabilidad"],
  "properties": {
    "metodo_resolucion": {
      "type": "string",
      "enum": ["centroide_lote", "punto_directo"],
      "description": "Metodo usado para resolver la UPL: centroide_lote (flujo normal: el lote se resuelve por F1 y la UPL se consulta por el centroide del lote) o punto_directo (fallback: la capa UPL se consulta por el punto de entrada cuando el lote no se resuelve por identidad -capa 38 sin CHIP- o el punto es ambiguo -limite entre lotes-)."
    },
    "upl": {
      "type": "object",
      "additionalProperties": false,
      "required": ["codigo", "nombre", "localidad"],
      "properties": {
        "codigo": {
          "type": "string",
          "pattern": "^UPL\\d{2}$",
          "description": "Código oficial de la UPL (CODIGO_UPL de la capa). Valores UPL01–UPL33."
        },
        "nombre": {
          "type": "string",
          "description": "Nombre oficial de la UPL (NOMBRE de la capa), p. ej. Sumapáz."
        },
        "localidad": {
          "type": "string",
          "description": "Localidad del lote, derivada por mapeo NOMBRE → localidad (research D3); la capa UPL no trae localidad."
        }
      }
    },
    "trazabilidad": { "$ref": "#/definitions/source_trace" }
  },
  "definitions": {
    "source_trace": {
      "type": "object",
      "additionalProperties": false,
      "required": ["source_name", "layer_id", "service_url", "data_vigencia", "query_timestamp"],
      "description": "Trazabilidad de 5 campos (FR-006, Principio III). Obligatoria en cada dato, incluida la marca de tiempo de la consulta.",
      "properties": {
        "source_name": { "type": "string", "description": "Nombre canónico de la fuente: IDECA Catastro — Unidad de Planeamiento Local." },
        "layer_id": { "type": "string", "description": "Capa/tema dentro del servicio: unidadplaneamientolocal.0." },
        "service_url": { "type": "string", "format": "uri" },
        "data_vigencia": { "type": "string", "description": "Vigencia del dato en la fuente (fecha ISO o año)." },
        "query_timestamp": { "type": "string", "format": "date-time", "description": "Marca de tiempo de la consulta (ISO 8601 UTC)." }
      }
    }
  }
}
```

### Ejemplo de uso — lote con UPL asignada

Consulta: `{"chip": "AAA0072LRYN"}`

```json
{
  "metodo_resolucion": "centroide_lote",
  "upl": {
    "codigo": "UPL01",
    "nombre": "Sumapáz",
    "localidad": "Sumapaz"
  },
  "trazabilidad": {
    "source_name": "IDECA Catastro — Unidad de Planeamiento Local",
    "layer_id": "unidadplaneamientolocal.0",
    "service_url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/ordenamientoterritorial/unidadplaneamientolocal/MapServer/0",
    "data_vigencia": "2021-12-30",
    "query_timestamp": "2026-08-10T14:30:00Z"
  }
}
```

### Ejemplo de uso — lote sin UPL asignada (dato no encontrado)

Consulta: `{"coordenadas": {"lat": 4.65, "lon": -74.1}}`

```json
{
  "error": {
    "code": "LOTE_SIN_UPL",
    "message": "El lote no tiene UPL asignada (dato no encontrado).",
    "source_name": "IDECA Catastro — Unidad de Planeamiento Local"
  }
}
```

### Trazabilidad

- `trazabilidad` documenta la capa UPL consultada: `source_name` =
  `IDECA Catastro — Unidad de Planeamiento Local`, `layer_id` = `unidadplaneamientolocal.0`
  y `service_url` del layer 0.
- `data_vigencia` es configurable por entorno (patrón `VIGENCIAS_DEFAULT` de F1); el valor
  por defecto corresponde a la vigencia del Decreto 555/2021 que define las UPL
  (`2021-12-30`). Cada feature de la capa además trae su `FECHA_ACTO_ADMINISTRATIVO`.
- La resolución del Lote por F1 conserva su propia trazabilidad interna (capa Lote 38 /
  Mapas Bogotá); la salida pública de `get_upl` expone la trazabilidad de la capa UPL
  (FR-006/SC-005).

## Estados de error

| Código | Condición | Mensaje (español) |
|--------|-----------|-------------------|
| `LOTE_NO_ENCONTRADO` | El CHIP/dirección no resuelve a ningún lote, o el punto no intersecta ningún lote. Por coordenadas, los casos de identidad incompleta (capa 38 sin CHIP) y límite entre lotes se atienden con el fallback `punto_directo`, sin pasar por este error. | `No se encontró ningún lote para el criterio consultado.` |
| `DIRECCION_NO_LOCALIZADA` | La dirección no pudo geocodificarse (no encontrada o ambigua); nunca se inventa un lote. | `La dirección no pudo localizarse. Refina la dirección o usa CHIP/coordenadas.` |
| `FUERA_DE_COBERTURA` | El punto está fuera del área de Bogotá. | `El punto está fuera del área de cobertura (Bogotá).` |
| `LOTE_SIN_UPL` | El lote se resolvió pero **no tiene UPL asignada** (dato no encontrado, FR-007); ningún feature de la capa UPL intersecta el centroide. | `El lote no tiene UPL asignada (dato no encontrado).` |
| `FUENTE_5XX` | La API de Mapas Bogotá o la capa ArcGIS de UPL responde 5xx, indicando cuál fuente. | `La fuente <source_name> no está disponible (error <status>). Intenta nuevamente.` |
| `CREDENCIAL_FALTANTE` | Falta `MAPAS_BOGOTA_APIKEY` en consultas por dirección (fail-fast). | `Falta la variable MAPAS_BOGOTA_APIKEY para consultas por dirección. Configúrala en .env.` |
| `PARAMETROS_INVALIDOS` | Parámetros de entrada inválidos (FR-013): ninguno o más de un criterio, CHIP mal formado, coordenadas fuera de rango, dirección vacía. | `Parámetros inválidos: <detalle>.` |

Notas de semántica (FR-007):

- `LOTE_SIN_UPL` **no** es `LOTE_NO_ENCONTRADO` (el lote existe) ni `FUERA_DE_COBERTURA`
  (el punto está en Bogotá): es "dato no encontrado" para la capa UPL.
- El error 5xx **nunca** se reporta como "lote no encontrado" ni como "dato no encontrado"
  (FR-009): un 5xx es un fallo del servidor de la fuente y la respuesta lo identifica.
- En modo `punto_directo`, si la capa UPL no devuelve ningún feature para el punto, se responde
  `LOTE_SIN_UPL` (dato no encontrado, FR-007); el mensaje canónico no incluye código catastral
  (y en el fallback no hay identidad de lote que reportar). Un 5xx de la capa UPL en el fallback
  sigue siendo `FUENTE_5XX` (FR-009).

## Referencias cruzadas al spec

| Requisito | Descripción |
|-----------|-------------|
| FR-005 | UPL por CHIP, dirección o coordenadas, reutilizando el resolver de F1; devuelve código y nombre de la UPL y la localidad. |
| FR-006 | Trazabilidad de 5 campos (`source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp`). |
| FR-007 | Distinción `LOTE_NO_ENCONTRADO` / `LOTE_SIN_UPL` (dato no encontrado) / `FUERA_DE_COBERTURA`. |
| FR-013 | Rechazo de parámetros inválidos (ninguno o más de un criterio, CHIP mal formado, coordenadas fuera de rango, dirección vacía). |
| SC-004 | UPL de un lote con CHIP válido en < 10 s. |
| SC-005 | 100% de respuestas con los 5 campos de trazabilidad. |
| Key Entity UPL/Localidad | Atributos clave (código, nombre, localidad) y pertenencia espacial al Lote. |
