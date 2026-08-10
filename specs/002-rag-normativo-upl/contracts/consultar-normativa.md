# Contrato: `consultar_normativa`

**Feature**: [RAG normativo del POT (Decreto 555/2021) con consulta de UPL](../spec.md)
**Tool MCP**: `consultar_normativa`
**Fecha**: 2026-08-10 | **Estado**: Aprobado en plan

## Propósito

Responde una **consulta en lenguaje natural** sobre la normativa del POT (Decreto 555 de
2021) con los artículos más relevantes del corpus, **cita literal del texto de cada
artículo** (número y título) y trazabilidad por fuente (FR-001, FR-003, Historia de Usuario
1). El parámetro opcional `upl` aplica un **filtro estricto** por metadatos/clasificación
(FR-002, Historia de Usuario 3): solo se devuelven artículos aplicables a esa UPL (por
clasificación de suelo `parte` o mención explícita en el chunk); si se omite, la consulta
no filtra por territorio.

Pipeline interno (research D7): validar entrada → verificar corpus ingestado
(`CORPUS_NO_INGESTADO`) → verificar disponibilidad de Ollama y modelos
(`OLLAMA_NO_DISPONIBLE`) → recuperar top-k 4–6 candidatos por similitud coseno (bge-m3),
aplicando el filtro de UPL cuando exista → umbral ≥ 0.30–0.35 → top-3 sobre el umbral →
generar respuesta con el LLM de chat (temperatura 0.1, "responde SOLO con base en estos
fragmentos; cita el texto exacto y el número de artículo") → post-verificación de citas
(citation forcing) contra los metadatos de los chunks recuperados → si ningún candidato
supera el umbral, abstención explícita.

## Entrada (input)

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["consulta"],
  "properties": {
    "consulta": {
      "type": "string",
      "minLength": 1,
      "maxLength": 500,
      "description": "Consulta en lenguaje natural sobre la normativa del POT, p. ej. \"¿qué se puede construir en suelo urbano?\".",
      "examples": ["¿qué se puede construir en suelo urbano?"]
    },
    "upl": {
      "type": "string",
      "pattern": "^UPL\\d{2}$",
      "description": "Código de UPL para filtro ESTRICTO por metadatos/clasificación (FR-002). Valores UPL01–UPL33. Si se omite, no filtra por territorio.",
      "examples": ["UPL17"]
    },
    "top_k": {
      "type": "integer",
      "minimum": 1,
      "maximum": 6,
      "default": 3,
      "description": "Número de artículos a devolver (top-3 sobre el umbral de relevancia)."
    }
  }
}
```

### Reglas de validación (FR-013)

- `consulta` es obligatoria, debe ser `string` **no vacía** (después de trim) y de **1 a 500
  caracteres**. Vacía o demasiado larga → `PARAMETROS_INVALIDOS`, sin llamar a las fuentes
  (fail-fast).
- `upl` es opcional. Si se provee, debe cumplir `^UPL\d{2}$` **y** existir en el conjunto
  `UPL01`–`UPL33` (p. ej. `UPL99` se rechaza aunque el formato sea válido) →
  `PARAMETROS_INVALIDOS`.
- `top_k` es opcional, `int` entre 1 y 6 (default 3). Fuera de rango →
  `PARAMETROS_INVALIDOS`.

## Salida (output)

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["respuesta", "sin_resultados", "resultados", "trazabilidad"],
  "properties": {
    "respuesta": {
      "type": "string",
      "description": "Respuesta generada por el LLM con citas literales del corpus y números de artículo (FR-003). Si sin_resultados=true, es el texto de abstención explícita (FR-004)."
    },
    "sin_resultados": {
      "type": "boolean",
      "description": "true si ninguna pieza del corpus superó el umbral de relevancia. Sin resultados NO es un error (FR-004): es una abstención explícita, nunca se inventa contenido."
    },
    "resultados": {
      "type": "array",
      "description": "Artículos recuperados sobre el umbral, ordenados por similitud descendente (máximo top_k). Vacío si sin_resultados=true.",
      "items": { "$ref": "#/definitions/resultado" }
    },
    "trazabilidad": { "$ref": "#/definitions/source_trace" }
  },
  "definitions": {
    "resultado": {
      "type": "object",
      "additionalProperties": false,
      "required": ["articulo", "titulo", "libro", "parte", "texto_cita", "similitud"],
      "properties": {
        "articulo": {
          "type": "integer",
          "minimum": 1,
          "description": "Número del artículo del Decreto 555/2021 (identifica la cita, FR-003)."
        },
        "titulo": {
          "type": "string",
          "description": "Título del artículo (metadato del chunk)."
        },
        "libro": {
          "type": "string",
          "description": "Libro del decreto al que pertenece (I Adopción … VIII Disposiciones Generales)."
        },
        "parte": {
          "type": "string",
          "enum": ["general", "urbano", "rural"],
          "description": "Clasificación de suelo / parte del POT. Base del filtro estricto de UPL (FR-002)."
        },
        "texto_cita": {
          "type": "string",
          "description": "Texto literal del chunk recuperado (cita verificable contra el corpus, FR-003/SC-002)."
        },
        "similitud": {
          "type": "number",
          "minimum": 0,
          "maximum": 1,
          "description": "Similitud coseno del chunk (>= umbral 0.30–0.35)."
        }
      }
    },
    "source_trace": {
      "type": "object",
      "additionalProperties": false,
      "required": ["source_name", "layer_id", "service_url", "data_vigencia", "query_timestamp"],
      "description": "Trazabilidad de 5 campos (FR-006, Principio III). layer_id es el identificador de documento (FR-006): Decreto_555_2021.",
      "properties": {
        "source_name": { "type": "string", "description": "Nombre canónico de la fuente: Decreto 555 de 2021 (POT Bogotá)." },
        "layer_id": { "type": "string", "description": "Identificador de documento: Decreto_555_2021." },
        "service_url": { "type": "string", "format": "uri", "description": "URL oficial del articulado (sisjur)." },
        "data_vigencia": { "type": "string", "description": "Vigencia del documento: 2021-12-30 (Registro Distrital 7326)." },
        "query_timestamp": { "type": "string", "format": "date-time", "description": "Marca de tiempo de la consulta (ISO 8601 UTC)." }
      }
    }
  }
}
```

### Ejemplo de uso — consulta con resultados

Consulta: `{"consulta": "¿qué se puede construir en suelo urbano?", "top_k": 3}`

```json
{
  "respuesta": "Con base en el Decreto 555 de 2021 (POT Bogotá): el Artículo 42 (Usos en suelo urbano) establece que «...texto literal del artículo...»; el Artículo 87 (Cesiones urbanísticas) señala que «...texto literal...».",
  "sin_resultados": false,
  "resultados": [
    {
      "articulo": 42,
      "titulo": "Usos en suelo urbano",
      "libro": "III. Componente Urbano",
      "parte": "urbano",
      "texto_cita": "ARTÍCULO 42. USOS EN SUELO URBANO. «...texto literal del artículo...»",
      "similitud": 0.81
    },
    {
      "articulo": 87,
      "titulo": "Cesiones urbanísticas",
      "libro": "III. Componente Urbano",
      "parte": "urbano",
      "texto_cita": "ARTÍCULO 87. CESIONES URBANÍSTICAS. «...texto literal del artículo...»",
      "similitud": 0.64
    }
  ],
  "trazabilidad": {
    "source_name": "Decreto 555 de 2021 (POT Bogotá)",
    "layer_id": "Decreto_555_2021",
    "service_url": "https://sisjur.bogotajuridica.gov.co/sisjur/normas/Norma1.jsp?i=119582",
    "data_vigencia": "2021-12-30",
    "query_timestamp": "2026-08-10T14:30:00Z"
  }
}
```

### Ejemplo de uso — filtro estricto por UPL

Consulta: `{"consulta": "normas de usos industriales", "upl": "UPL17"}`

La recuperación aplica el filtro estricto por metadatos/clasificación (FR-002): solo se
consideran los chunks aplicables a UPL17 (parte de suelo urbano o mención explícita en el
chunk). La forma de la salida es idéntica al ejemplo anterior; los `resultados` contienen
únicamente artículos que aplican a la UPL.

### Ejemplo de uso — sin resultados relevantes (abstención explícita)

Consulta: `{"consulta": "¿cuántos árboles hay en la Avenida El Dorado?", "top_k": 3}`

```json
{
  "respuesta": "No se encontraron resultados relevantes en el POT 555/2021.",
  "sin_resultados": true,
  "resultados": [],
  "trazabilidad": {
    "source_name": "Decreto 555 de 2021 (POT Bogotá)",
    "layer_id": "Decreto_555_2021",
    "service_url": "https://sisjur.bogotajuridica.gov.co/sisjur/normas/Norma1.jsp?i=119582",
    "data_vigencia": "2021-12-30",
    "query_timestamp": "2026-08-10T14:30:00Z"
  }
}
```

### Trazabilidad

- `trazabilidad` documenta el documento consultado: `source_name` =
  `Decreto 555 de 2021 (POT Bogotá)`, `layer_id` = `Decreto_555_2021` (**identificador de
  documento**, FR-006), `service_url` = URL oficial del articulado (sisjur),
  `data_vigencia` = `2021-12-30`.
- La vigencia del documento es explícita y propia del Decreto 555/2021 (FR-014): si el
  corpus incluyera más documentos en el futuro, cada uno conserva su `data_vigencia`; nunca
  se mezclan vigencias como una sola fotografía temporal.

## Estados de error

| Código | Condición | Mensaje (español) |
|--------|-----------|-------------------|
| `PARAMETROS_INVALIDOS` | Consulta vacía o > 500 caracteres, `top_k` fuera de 1–6, `upl` mal formada (`^UPL\d{2}$`) o inexistente (no está en `UPL01`–`UPL33`). | `Parámetros inválidos: <detalle>.` |
| `CORPUS_NO_INGESTADO` | El vector store está vacío o desactualizado (no se ejecutó la ingesta o el índice no corresponde al corpus). | `El corpus normativo no está ingestado o está desactualizado. Ejecuta el script de ingesta antes de consultar.` |
| `OLLAMA_NO_DISPONIBLE` | El servicio Ollama no es accesible o un modelo requerido (embeddings o chat) no está instalado. | `El servicio Ollama no está disponible o falta el modelo <modelo>. Verifica OLLAMA_HOST/OLLAMA_BASE_URL y ollama pull <modelo>.` |
| `FUENTE_5XX` | La verificación/actualización del corpus contra la fuente oficial responde 5xx (si aplica durante la consulta). | `La fuente <source_name> no está disponible (error <status>). Intenta nuevamente.` |

Notas:

- **Sin resultados NO es un error**: ninguna pieza sobre el umbral → `sin_resultados=true`
  con abstención explícita (FR-004/SC-003), no `CORPUS_NO_INGESTADO` ni error.
- `CORPUS_NO_INGESTADO` **no** es "sin resultados": es un estado de infraestructura que se
  reporta como error para evitar resultados vacíos silenciosos (caso límite del spec).
- `OLLAMA_NO_DISPONIBLE` falla rápido (FR-011) sin generar respuesta parcial ni recuperar
  artículos no verificables.
- El error 5xx **nunca** se reporta como "sin resultados" (FR-009): un 5xx es un fallo del
  servidor de la fuente y la respuesta lo identifica.

## Referencias cruzadas al spec

| Requisito | Descripción |
|-----------|-------------|
| FR-001 | Consulta en lenguaje natural → artículos más relevantes con cita literal. |
| FR-002 | Filtro estricto por UPL (clasificación de suelo / mención explícita); omisión → sin filtrar por territorio. |
| FR-003 | Cita literal (texto del corpus) con número y título de artículo; no redactar contenido no respaldado. |
| FR-004 | "Sin resultados" explícito cuando ninguna pieza supera el umbral; nunca inventar. |
| FR-006 | Trazabilidad de 5 campos (`layer_id` = identificador de documento `Decreto_555_2021`). |
| FR-008 | Ingestion: corpus oficial descargado, extraído y dividido en chunks con metadatos. |
| FR-009 | Índice regenerable/gitignored; verificación de integridad o actualidad del corpus. |
| FR-010 | Modelos de Ollama configurables por variables de entorno (`OLLAMA_HOST`/`OLLAMA_BASE_URL`, embeddings, chat). |
| FR-011 | Fail-fast con mensaje claro y accionable cuando Ollama no está disponible o falta un modelo. |
| FR-013 | Rechazo de parámetros inválidos (consulta vacía, UPL mal formada, top_k fuera de rango). |
| FR-014 | No mezclar vigencias; cada documento conserva su vigencia explícita. |
| SC-001 | Consulta típica en < 15 s con Ollama local. |
| SC-002 | 100% de respuestas con cita literal verificable (artículo + título + texto). |
| SC-003 | 100% de consultas sin resultados responden "sin resultados" explícitamente. |
| SC-005 | 100% de respuestas con los 5 campos de trazabilidad. |
| SC-006 | Ingesta indexa el 100% de los artículos (verificable contra la fuente). |
