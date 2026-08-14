# Contrato: Ingesta de actos modificatorios del Decreto 555 (corpus consolidado)

**Feature**: [Ingesta de actos normativos que modifican el Decreto 555](../spec.md)
**Interfaz**: CLI `python -m app.ingesta.corpus acto` + campos aditivos en F2/F3
**Fecha**: 2026-08-14 | **Estado**: Aprobado en plan

## Propósito

Alimentar el **corpus normativo consolidado** con actos administrativos (decretos y
resoluciones) que reglamentan o modifican el Decreto 555 de 2021, en HTML sisjur (recomendado),
PDF, DOCX, Markdown y TXT (FR-001). Los documentos se integran a la colección única consultada
por `consultar_normativa` (F2) y `get_feasibility_report` (F3) sin romper sus contratos
(FR-003, FR-011), con deduplicación por hash SHA-256 del archivo (FR-007, SC-003),
identificación de norma por fragmento (FR-004/FR-005) y precedencia temporal comunicada al LLM
vía prompt (FR-006, SC-004).

Pipeline interno: detectar formato → extraer artículos (sisjur reutilizado con adaptación D4, o
extracción genérica D5) → validar contra el 555 (FR-014) → deduplicar por hash (FR-007) →
escribir JSONL + `.sha256` (FR-013) → actualizar el registro
`.corpus_consolidado.json` → re-indexar de forma aditiva (FR-008). Fallo atómico por documento
(FR-009, SC-006): cualquier error deja el corpus existente intacto.

## Interfaz CLI (ingesta — misma semántica de la feature 2)

```text
python -m app.ingesta.corpus acto [--url <URL> | --archivo <PATH>] [--output <DIR>] [--indexar]
```

| Argumento | Tipo | Descripción |
|-----------|------|-------------|
| `--url` | `string` | URL sisjur del acto (p. ej. `https://www.alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=139499`). Mutuamente excluyente con `--archivo`. |
| `--archivo` | `string` | Ruta local del archivo (HTML/PDF/DOCX/MD/TXT). Mutuamente excluyente con `--url`. |
| `--output` | `string` | Directorio de salida del JSONL (por defecto `data/corpus/actos_modificatorios/`). |
| `--indexar` | flag | Si se pasa, re-indexa en ChromaDB de forma aditiva tras escribir el JSONL. |

**Salida en éxito** (stdout, JSON):

```json
{
  "documento_id": "Decreto_122_2023",
  "tipo_norma": "decreto",
  "numero": 122,
  "año": 2023,
  "fecha_expedicion": "2023-03-30",
  "fecha_vigencia": "2023-03-31",
  "url_origen": "https://www.alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=139499",
  "hash_sha256": "<sha256 del archivo>",
  "articulos": 13,
  "relacion_con_555": "referencia_articulos",
  "articulos_referenciados": [233, 243, 384],
  "estado_documento": "derogado",
  "derogado_compilado_por": "Derogado y compilado por el art. 1526, Decreto Único Distrital de Ordenamiento Territorial 670 de 2025",
  "duplicado": false,
  "indexado": true
}
```

**Salida en documento duplicado** (FR-007, SC-003): mismo shape con `"duplicado": true` y sin
reescribir el JSONL ni re-indexar.

**Salida en error** (stderr + exit code ≠ 0, fallo atómico FR-009/SC-006): mensaje descriptivo
tipificado y accionable, p. ej.:

```text
Error de ingesta [FORMATO_NO_SOPORTADO]: el archivo 'acto.xls' no es un formato soportado
(HTML sisjur, PDF, DOCX, Markdown, TXT). El corpus existente NO se modificó.
```

Errores tipificados de la ingesta:

| Código | Situación | Acción sugerida |
|--------|-----------|-----------------|
| `FORMATO_NO_SOPORTADO` | Extensión/magic bytes no reconocidos | Usar uno de los 5 formatos soportados (FR-001). |
| `SIN_TEXTO_EXTRAIBLE` | PDF escaneado o documento sin texto | Usar el formato HTML sisjur (edge case de la spec). |
| `SIN_ARTICULOS_PARSEABLES` | No se detectó ningún artículo | Verificar que el documento tiene articulado; usar sisjur si es PDF escaneado (FR-009). |
| `FECHA_ANTERIOR_AL_555` | `fecha_expedicion < 2021-12-30` | El acto no puede reglamentar/modificar el 555; no se integra (FR-014). |
| `FUENTE_NO_DISPONIBLE` | URL de origen no responde | Reintentar o descargar manualmente y usar `--archivo` (edge case de la spec). |
| `DUPLICADO` | El hash SHA-256 ya está en el registro | No-op; el documento ya está ingestado (FR-007). |

## Formato del JSONL por acto (fuente de verdad versionada, FR-013)

`data/corpus/actos_modificatorios/<documento_id>.jsonl`, una línea por artículo. Cada línea
conserva los campos del `ArtículoNormativo` de F2 (para el 555) y **añade** los campos de norma
(data-model.md):

```json
{
  "numero": 1,
  "titulo": "Objeto y ámbito de aplicación.",
  "texto": "El presente decreto reglamenta los artículos 233, 243 y 384 del Decreto Distrital 555 de 2021, ...",
  "norma_id": "Decreto_122_2023",
  "tipo_norma": "decreto",
  "numero_norma": 122,
  "año": 2023,
  "fecha_vigencia": "2023-03-31",
  "titulo_norma": "Decreto 122 de 2023",
  "relacion_con_555": "referencia_articulos",
  "articulos_referenciados": [233, 243, 384],
  "estado_documento": "derogado",
  "derogado_compilado_por": "Derogado y compilado por el art. 1526, Decreto Único Distrital de Ordenamiento Territorial 670 de 2025"
}
```

## Registro del corpus consolidado

`data/corpus/actos_modificatorios/.corpus_consolidado.json` — un hash y metadatos por documento
(FR-002, FR-007, FR-008; research D3):

```json
{
  "documento_base": "Decreto_555_2021",
  "documentos": [
    {
      "documento_id": "Decreto_122_2023",
      "hash_sha256": "<sha256 del archivo>",
      "tipo_norma": "decreto",
      "numero": 122,
      "año": 2023,
      "fecha_expedicion": "2023-03-30",
      "fecha_vigencia": "2023-03-31",
      "url_origen": "https://www.alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=139499",
      "formato": "sisjur_html",
      "relacion_con_555": "referencia_articulos",
      "articulos": 13,
      "indexado": true
    }
  ]
}
```

## Campos aditivos en la respuesta de F2 (`consultar_normativa.resultados[]`)

Cada ítem de `resultados` conserva sus campos existentes y **gana** (FR-004, FR-005, FR-011):

```json
{
  "norma": "Decreto 122 de 2023",
  "source_name": "Decreto 122 de 2023"
}
```

- `norma`: nombre legible de la norma de origen (FR-005), p. ej. `"Decreto 555 de 2021"` o
  `"Decreto 122 de 2023"`.
- `source_name`: nombre de la fuente de trazabilidad (FR-004), igual a `norma` para el corpus
  normativo.

## Campos aditivos en la respuesta de F3 (`get_feasibility_report.normative_evidence.items[]`)

Cada ítem de `items` conserva sus campos existentes y gana los mismos campos aditivos
(`norma`, `source_name`). El `source_trace` de bloque de `normative_evidence` se conserva
intacto (FR-004).

## Regla de precedencia temporal en el prompt del RAG (FR-006, SC-004)

El contexto que se entrega al LLM en `consultar_normativa` (y por tanto en la evidencia de F3)
incluye la regla explícita:

> Los fragmentos provienen del corpus consolidado del POT (Decreto 555 de 2021 y actos
> posteriores que lo reglamentan o modifican). Cuando un acto posterior reglamente o modifique
> un artículo del 555, el acto posterior PREVALECE. Cita ambas normas sin ocultar los artículos
> del 555 (coexistencia de fuentes) e indica la norma de origen de cada cita.

Los fragmentos del contexto se ordenan por `fecha_vigencia` descendente (el acto más reciente
primero). El citation forcing de F2 (citas literales verificables) se mantiene sin cambios.

## Criterios de aceptación (mapeo a SC)

| Criterio | Contrato |
|----------|----------|
| SC-001 (acto real ingestado y consultable) | `python -m app.ingesta.corpus acto --url ...i=139499` produce `Decreto_122_2023.jsonl` con 13 artículos y la consulta "vivienda colectiva" devuelve fragmentos del 122. |
| SC-002 (norma de origen en el 100% de fragmentos) | Todo ítem de `resultados`/`items` lleva `norma` y `source_name`. |
| SC-003 (deduplicación 100%) | Re-ingestar el mismo archivo → `"duplicado": true`, sin nuevos artículos/fragmentos. |
| SC-004 (precedencia en el 100% de consultas) | El prompt del RAG incluye la regla de precedencia (test de prompt) y los fragmentos se ordenan por vigencia descendente. |
| SC-005 (185 tests de F1–F3 intactos + extensiones aditivas) | Los shapes exactos se actualizan solo para incluir `norma`/`source_name`; sin cambios semánticos. |
| SC-006 (fallo atómico) | Ingestar un formato no soportado o un documento sin artículos NO modifica el corpus existente. |
