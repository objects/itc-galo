# Contrato: `get_feasibility_report`

**Feature**: [Informe de factibilidad orquestado](../spec.md)
**Tool MCP**: `get_feasibility_report`
**Fecha**: 2026-08-12 | **Estado**: Aprobado en plan

## Propósito

Emite el **informe de factibilidad** de un lote catastral de Bogotá en una sola llamada
orquestada (FR-001): resuelve el lote (por CHIP, dirección o coordenadas), su UPL y
localidad, las restricciones (reserva vial), el mercado (valor de referencia), el entorno
(obras públicas en un radio de 500 m), el contexto económico (destino económico desde la
capa catastral viva), la evidencia normativa del POT (consulta del usuario o automática) y
un `feasibility_score` 100 % determinístico con reasons trazables (FR-006/FR-007).

Pipeline interno: validar entrada (fail-fast, FR-013) → resolver lote (flujos privados F1)
→ resolver UPL (capturando `UplNoEncontradaError` como `upl: null` + warning) → contexto
Temático (reusando `reserva_vial` y `valor_referencia` de F1) + obras públicas con buffer
500 m → destino económico (capa Predio, por `PRECHIP` o `BARMANPRE`) → consulta normativa
(explícita o automática; degradando `CORPUS_NO_INGESTADO`/`OLLAMA_NO_DISPONIBLE` a evidencia
vacía + warning) → scoring puro (research D3) → montar los 10 bloques del reporte.

### Divergencia deliberada con F2 (documentada en research.md)

Esta tool **degrada** por bloque (FR-009/FR-012): RAG no disponible → `normative_evidence`
items vacíos + `causa` + warning (NO error `CORPUS_NO_INGESTADO`/`OLLAMA_NO_DISPONIBLE`);
UPL ausente → `upl: null` + warning (NO error `LOTE_SIN_UPL`); dato por fuente → estado
`no_encontrado` a nivel de bloque. Los errores **fatales** son 6: `PARAMETROS_INVALIDOS`,
`LOTE_NO_ENCONTRADO`, `FUERA_DE_COBERTURA`, `DIRECCION_NO_LOCALIZADA`,
`CREDENCIAL_FALTANTE`, `FUENTE_5XX`. Un 5xx de una fuente nunca se degrada a
`no_encontrado`.

## Entrada (input)

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "chip": {
      "type": "string",
      "pattern": "^[A-Z0-9]{11}$",
      "description": "CHIP del predio catastral de Bogotá. Criterio de entrada 1 de 3 (exactamente uno).",
      "examples": ["AAA0072LRYN"]
    },
    "direccion": {
      "type": "string",
      "minLength": 1,
      "maxLength": 200,
      "description": "Dirección para geocodificar. Criterio de entrada 2 de 3 (exactamente uno). Requiere MAPAS_BOGOTA_APIKEY."
    },
    "coordenadas": {
      "type": "object",
      "additionalProperties": false,
      "required": ["lat", "lon"],
      "properties": {
        "lat": { "type": "number", "minimum": -90, "maximum": 90 },
        "lon": { "type": "number", "minimum": -180, "maximum": 180 }
      },
      "description": "Coordenadas WGS84 del punto. Criterio de entrada 3 de 3 (exactamente uno)."
    },
    "consulta": {
      "type": "string",
      "minLength": 1,
      "maxLength": 500,
      "description": "Consulta en lenguaje natural para la evidencia normativa (opcional). Si se omite, se construye automáticamente desde el contexto del lote (UPL + localidad + clasificación de suelo)."
    },
    "top_k": {
      "type": "integer",
      "minimum": 1,
      "maximum": 6,
      "default": 3,
      "description": "Número de artículos normativos a recuperar (coherente con consultar_normativa)."
    }
  }
}
```

### Reglas de validación (FR-013)

- **Exactamente uno** de `chip` | `direccion` | `coordenadas`. Cero o más de uno →
  `PARAMETROS_INVALIDOS`, sin llamar a las fuentes (fail-fast).
- `chip`: `^[A-Z0-9]{11}$` (idéntico a F1/F2).
- `direccion`: string no vacío; sin `MAPAS_BOGOTA_APIKEY` → `CREDENCIAL_FALTANTE`.
- `coordenadas`: `lat ∈ [-90, 90]`, `lon ∈ [-180, 180]` (idéntico a F1/F2).
- `consulta`: opcional, 1–500 caracteres.
- `top_k`: opcional, entero 1–6, default 3.
- Punto fuera de Bogotá (sin lote) → `FUERA_DE_COBERTURA`.

## Salida (output)

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "lot_identity", "administrative_context", "planning_constraints",
    "market_context", "environment_context", "economic_context",
    "normative_evidence", "feasibility_score", "warnings", "query_timestamp"
  ],
  "properties": {
    "lot_identity": {
      "type": "object",
      "description": "Identidad del lote (bloque F1 reutilizado).",
      "required": ["chip", "codigo_catastral", "manzana", "direccion_normalizada", "barrio", "geometry", "centroid", "source_trace"],
      "properties": {
        "chip": { "type": ["string", "null"], "description": "CHIP del predio. Puede ser null cuando el lote se resolvió por coordenadas (capa Lote no publica CHIP)." },
        "codigo_catastral": { "type": "string", "description": "LOTCODIGO de la capa Lote 38. Siempre presente; es el join key con BARMANPRE de la capa Predio." },
        "manzana": { "type": "string" },
        "direccion_normalizada": { "type": "string" },
        "barrio": { "type": "string" },
        "geometry": { "type": "object", "description": "Geometría GeoJSON del lote (p. ej. Polygon)." },
        "centroid": { "type": "object", "properties": { "lat": { "type": "number" }, "lng": { "type": "number" } } },
        "source_trace": { "$ref": "#/definitions/source_trace" }
      }
    },
    "administrative_context": {
      "type": "object",
      "description": "UPL, localidad y clasificación de suelo del lote.",
      "required": ["upl", "localidad", "clasificacion_suelo", "source_trace"],
      "properties": {
        "upl": { "type": ["object", "null"], "description": "UPL resuelta. null + warning UPL_NO_ENCONTRADA si no se resuelve (no error).", "properties": { "codigo": { "type": "string" }, "nombre": { "type": "string" }, "vocacion": { "type": "string" }, "source_trace": { "$ref": "#/definitions/source_trace" } } },
        "localidad": { "type": ["object", "null"], "properties": { "codigo": { "type": "string" }, "nombre": { "type": "string" } } },
        "clasificacion_suelo": { "type": ["string", "null"], "enum": ["urbano", "rural", "urbano-rural", null], "description": "Derivada de UPL.vocacion (research D2). null si no hay UPL." },
        "source_trace": { "$ref": "#/definitions/source_trace" }
      }
    },
    "planning_constraints": { "$ref": "#/definitions/bloque_estado" },
    "market_context": { "$ref": "#/definitions/bloque_estado" },
    "environment_context": { "$ref": "#/definitions/bloque_estado" },
    "economic_context": {
      "type": "object",
      "description": "Destino económico del predio desde la capa catastral viva Predio (catastro/lote/MapServer/3).",
      "required": ["estado", "dato", "interpretation", "source_trace"],
      "properties": {
        "estado": { "$ref": "#/definitions/estado" },
        "dato": {
          "type": ["object", "null"],
          "properties": {
            "codigo_destino": { "type": "string", "description": "PRECDESTIN (2 dígitos, dominio D_PreDestino)." },
            "descripcion_destino": { "type": "string", "description": "Descripción del código de destino (tabla de dominio versionada)." },
            "uso": { "type": "string", "description": "PRECUSO (3 dígitos) + descripción D_UsoTUso de la fila dominante (mayor PREAUSO)." },
            "area_uso": { "type": "number", "description": "PREAUSO de la fila dominante (m²)." },
            "usos": { "type": "array", "items": { "type": "object", "properties": { "codigo": { "type": "string" }, "descripcion": { "type": "string" }, "area_uso": { "type": "number" } } }, "description": "Todas las filas del predio por construcción/uso." },
            "area_terreno": { "type": "number", "description": "PREATERRE (m²)." },
            "area_construccion": { "type": "number", "description": "PREACONST (m²)." },
            "direccion": { "type": "string", "description": "PREDIRECC." },
            "barrio": { "type": "string", "description": "PRENBARRIO." },
            "vigencia": { "type": "string", "description": "PREVACTUAL (vigencia de actualización catastral, p. ej. '2026')." }
          }
        },
        "interpretation": { "type": "string", "description": "Texto fijo por regla: destino predominante con su descripción y área, o aviso de no encontrado." },
        "source_trace": { "$ref": "#/definitions/source_trace" }
      }
    },
    "normative_evidence": {
      "type": "object",
      "description": "Evidencia normativa del POT con citas literales. Se degrada (items vacíos + causa) si el RAG no está disponible o no hay resultados.",
      "required": ["items", "consulta", "consulta_automatica", "sin_resultados", "source_trace"],
      "properties": {
        "items": { "type": "array", "items": { "type": "object", "properties": { "articulo": { "type": "string" }, "titulo": { "type": "string" }, "libro": { "type": "string" }, "parte": { "type": "string" }, "texto_cita": { "type": "string" }, "similitud": { "type": "number" } } } },
        "consulta": { "type": "string", "description": "Texto de la consulta efectivamente usada (del usuario o automática)." },
        "consulta_automatica": { "type": "boolean" },
        "sin_resultados": { "type": "boolean" },
        "causa": { "type": ["string", "null"], "enum": ["CORPUS_NO_INGESTADO", "OLLAMA_NO_DISPONIBLE", "SIN_RESULTADOS", null] },
        "source_trace": { "$ref": "#/definitions/source_trace" }
      }
    },
    "feasibility_score": {
      "type": "object",
      "description": "Score 0-100 determinístico sin LLM (research D3).",
      "required": ["score", "confidence", "reasons"],
      "properties": {
        "score": { "type": "integer", "minimum": 0, "maximum": 100 },
        "confidence": { "type": "string", "enum": ["high", "medium", "low"] },
        "reasons": { "type": "array", "items": { "type": "string" }, "description": "Texto fijo por regla con dato y source_name; enumera datos faltantes cuando confidence es low." },
        "rules_applied": { "type": "array", "items": { "type": "string" } }
      }
    },
    "warnings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["codigo", "mensaje"],
        "properties": {
          "codigo": { "type": "string", "enum": ["LOTE_SIN_CHIP", "UPL_NO_ENCONTRADA", "LOCALIDAD_NO_DERIVADA", "BLOQUE_SIN_DATO", "NORMATIVA_NO_DISPONIBLE", "NORMATIVA_SIN_RESULTADOS"] },
          "mensaje": { "type": "string" }
        }
      }
    },
    "query_timestamp": { "type": "string", "format": "date-time", "description": "ISO 8601 UTC de generación del reporte." },
    "definitions": {}
  }
}
```

### Definiciones compartidas

```json
{
  "estado": { "type": "string", "enum": ["disponible", "no_encontrado"], "description": "Estado del dato por fuente (FR-007)." },
  "source_trace": {
    "type": "object",
    "required": ["source_name", "layer_id", "service_url", "data_vigencia", "query_timestamp"],
    "properties": {
      "source_name": { "type": "string" },
      "layer_id": { "type": "string" },
      "service_url": { "type": "string" },
      "data_vigencia": { "type": "string" },
      "query_timestamp": { "type": "string", "format": "date-time" }
    }
  },
  "bloque_estado": {
    "type": "object",
    "required": ["estado", "dato", "interpretation", "source_trace"],
    "properties": {
      "estado": { "$ref": "#/definitions/estado" },
      "dato": { "type": ["object", "null"], "description": "Dato de la fuente (ReservaVial, ValorReferencia u ObrasPublicas); null si no_encontrado." },
      "interpretation": { "type": "string" },
      "source_trace": { "$ref": "#/definitions/source_trace" }
    }
  }
}
```

## Ejemplo (destino económico disponible, UPL resuelta)

```json
{
  "lot_identity": {
    "chip": "AAA0072LRYN",
    "codigo_catastral": "006101016001",
    "manzana": "006101016",
    "direccion_normalizada": "AK 30 25 90",
    "barrio": "FLORIDA",
    "geometry": { "type": "Polygon", "coordinates": [] },
    "centroid": { "lat": 4.625188, "lng": -74.081333 },
    "source_trace": { "source_name": "Mapa_Referencia/Mapa_Referencia", "layer_id": "38", "service_url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/Mapa_Referencia/Mapa_Referencia/MapServer/38", "data_vigencia": "2025", "query_timestamp": "2026-08-12T02:15:00Z" }
  },
  "administrative_context": {
    "upl": { "codigo": "UPL24", "nombre": "Chapinero", "vocacion": "Urbano", "source_trace": { "source_name": "IDECA Catastro — Unidad de Planeamiento Local", "layer_id": "0", "service_url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/ordenamientoterritorial/unidadplaneamientolocal/MapServer/0", "data_vigencia": "2021-12-30", "query_timestamp": "2026-08-12T02:15:01Z" } },
    "localidad": { "codigo": "02", "nombre": "Chapinero" },
    "clasificacion_suelo": "urbano",
    "source_trace": { "source_name": "IDECA Catastro — Unidad de Planeamiento Local", "layer_id": "0", "service_url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/ordenamientoterritorial/unidadplaneamientolocal/MapServer/0", "data_vigencia": "2021-12-30", "query_timestamp": "2026-08-12T02:15:01Z" }
  },
  "planning_constraints": {
    "estado": "no_encontrado",
    "dato": null,
    "interpretation": "No se encontraron zonas de reserva vial que afecten el lote en la fuente consultada.",
    "source_trace": { "source_name": "ordenamientoterritorial/reservavial", "layer_id": "2", "service_url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/ordenamientoterritorial/reservavial/MapServer/2", "data_vigencia": "2025", "query_timestamp": "2026-08-12T02:15:02Z" }
  },
  "market_context": {
    "estado": "disponible",
    "dato": { "valor_referencia_m2": 4500000, "moneda": "COP", "m2_terreno": 3704.8, "vigencia": "2025" },
    "interpretation": "Valor de referencia catastral del terreno: 4500000 COP/m² (vigencia 2025).",
    "source_trace": { "source_name": "catastro/valorreferencia", "layer_id": "0", "service_url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/catastro/valorreferencia/MapServer/0", "data_vigencia": "2025", "query_timestamp": "2026-08-12T02:15:02Z" }
  },
  "environment_context": {
    "estado": "disponible",
    "dato": { "obras": [ { "nombre": "Ampliación de Estaciones: Calle 146…", "entidad": "IDU", "ubicacion": "Estaciones Del Sistema Transmilenio…" } ], "radio_m": 500 },
    "interpretation": "Se identificaron 1 obra(s) pública(s) en un radio de 500 m del lote.",
    "source_trace": { "source_name": "gestionpublica/obraspublicas", "layer_id": "0", "service_url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/gestionpublica/obraspublicas/MapServer/0", "data_vigencia": "2025", "query_timestamp": "2026-08-12T02:15:02Z" }
  },
  "economic_context": {
    "estado": "disponible",
    "dato": {
      "codigo_destino": "04",
      "descripcion_destino": "Dotacional público",
      "uso": "015 - Oficinas y Consultorios oficiales en NPH",
      "area_uso": 40453.8,
      "usos": [
        { "codigo": "015", "descripcion": "Oficinas y Consultorios oficiales en NPH", "area_uso": 40453.8 },
        { "codigo": "096", "descripcion": "Parqueadero Cubierto en NPH", "area_uso": 3011.3 }
      ],
      "area_terreno": 3704.8,
      "area_construccion": 43465.1,
      "direccion": "AK 30 25 90",
      "barrio": "FLORIDA",
      "vigencia": "2026"
    },
    "interpretation": "Destino económico predominante del lote: Dotacional público (código 04, uso: 015 - Oficinas y Consultorios oficiales en NPH).",
    "source_trace": { "source_name": "Predio (catastro/lote)", "layer_id": "3", "service_url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/catastro/lote/MapServer/3", "data_vigencia": "2026", "query_timestamp": "2026-08-12T02:15:03Z" }
  },
  "normative_evidence": {
    "items": [
      { "articulo": "361", "titulo": "Usos del suelo", "libro": "III", "parte": "urbano", "texto_cita": "…", "similitud": 0.42 }
    ],
    "consulta": "normas urbanísticas aplicables a la UPL Chapinero (UPL24), localidad Chapinero, clasificación de suelo urbano",
    "consulta_automatica": true,
    "sin_resultados": false,
    "causa": null,
    "source_trace": { "source_name": "Decreto 555 de 2021 (POT Bogotá)", "layer_id": "Decreto_555_2021", "service_url": "https://sisjur.bogotajuridica.gov.co/sisjur/normas/Norma1.jsp?i=119582", "data_vigencia": "2021-12-30", "query_timestamp": "2026-08-12T02:15:04Z" }
  },
  "feasibility_score": {
    "score": 85,
    "confidence": "high",
    "reasons": [
      "UPL resuelta: UPL24 Chapinero (IDECA Catastro — Unidad de Planeamiento Local).",
      "Localidad derivada: Chapinero (IDECA Catastro — Unidad de Planeamiento Local).",
      "Valor de referencia disponible: 4500000 COP/m² (catastro/valorreferencia).",
      "Destino económico disponible: Dotacional público (código 04, Predio (catastro/lote)).",
      "Evidencia normativa recuperada: 1 artículo del POT (Decreto 555 de 2021).",
      "Bloque planning_constraints no encontrado: penalización −5 (ordenamientoterritorial/reservavial)."
    ],
    "rules_applied": ["r_base", "r_upl", "r_localidad", "r_mercado", "r_economico", "r_normativa", "r_no_encontrado"]
  },
  "warnings": [
    { "codigo": "BLOQUE_SIN_DATO", "mensaje": "Bloque planning_constraints no encontrado: no se hallaron zonas de reserva vial que afecten el lote en la fuente consultada." }
  ],
  "query_timestamp": "2026-08-12T02:15:04Z"
}
```

## Errores

### Fatales (FR-012)

| Código | Cuándo |
|--------|--------|
| `PARAMETROS_INVALIDOS` | Más de un criterio, ninguno, formato de CHIP/coordenadas inválido, `consulta` > 500, `top_k` fuera de 1–6 |
| `LOTE_NO_ENCONTRADO` | Ningún lote para el criterio, o múltiples candidatos no desambiguables |
| `FUERA_DE_COBERTURA` | Punto fuera del área de cobertura (Bogotá) |
| `DIRECCION_NO_LOCALIZADA` | La dirección no pudo localizarse |
| `CREDENCIAL_FALTANTE` | Falta `MAPAS_BOGOTA_APIKEY` en geocodificación (falla sin llamar fuentes) |
| `FUENTE_5XX` | 5xx (HTTP o `body.error`) de cualquier fuente; nunca degradado |

Formato de error (misma convención F1/F2): `{ "codigo": "<CODIGO>", "mensaje": "...", "trazabilidad": { "fuente": "...", "capa": "...", "servicio": "...", "vigencia": "...", "timestamp": "..." } }`.

### Degradaciones (NO error; se representan en el reporte + warnings)

| Situación | Representación | Warning |
|-----------|----------------|---------|
| Lote sin CHIP (resuelto por coordenadas) | `lot_identity.chip: null` | `LOTE_SIN_CHIP` |
| UPL no encontrada | `administrative_context.upl: null`, `clasificacion_suelo: null` | `UPL_NO_ENCONTRADA` |
| Localidad no derivada | `administrative_context.localidad: null` | `LOCALIDAD_NO_DERIVADA` |
| Bloque temático/económico sin dato | `estado: "no_encontrado"`, `dato: null` | `BLOQUE_SIN_DATO` |
| RAG no disponible (corpus u Ollama) | `normative_evidence.items: []`, `causa: "CORPUS_NO_INGESTADO"` / `"OLLAMA_NO_DISPONIBLE"` | `NORMATIVA_NO_DISPONIBLE` |
| Sin resultados normativos | `normative_evidence.items: []`, `sin_resultados: true`, `causa: "SIN_RESULTADOS"` | `NORMATIVA_SIN_RESULTADOS` |

## Notas de trazabilidad y convenciones

- Los nombres de bloques y campos técnicos (`score`, `confidence`, `reasons`,
  `interpretation`, `source_trace`, `estado`) son en inglés; los atributos de dominio
  (`codigo`, `nombre`, `codigo_destino`, `descripcion_destino`, `usos`) siguen el estilo de
  los contratos F1/F2 (constitución Principio I, CHK-015).
- El bloque `economic_context` usa `f=pjson` en la capa Predio (NUNCA `f=geojson` → 400).
- `data_vigencia` del bloque económico = `PREVACTUAL` del registro (research H7).
- La consulta normativa automática se construye con UPL + localidad + clasificación de
  suelo y se pasa `upl=<codigo>` a `consultar_normativa` (filtro territorial F2); si no hay
  UPL, solo localidad sin filtro territorial (research D2).
