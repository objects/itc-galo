# Implementation Plan: Ingesta de actos normativos que modifican el Decreto 555 (corpus consolidado)

**Branch**: `004-ingesta-actos-modificatorios` | **Date**: 2026-08-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/004-ingesta-actos-modificatorios/spec.md`

**Note**: Este plan es la salida del comando `/speckit.plan` (Phase 0 + Phase 1). Los
artefactos de diseño son [research.md](research.md), [data-model.md](data-model.md),
[contracts/ingesta-actos-modificatorios.md](contracts/ingesta-actos-modificatorios.md) y
[quickstart.md](quickstart.md). La descomposición en tareas (`tasks.md`) la genera el
comando `/speckit.tasks` (Phase 2), NO este plan.

## Summary

Requisito primario (FR-001 a FR-014): permitir **alimentar el corpus normativo con actos
administrativos** (decretos/resoluciones) que reglamentan o modifican el Decreto 555 de 2021
(POT de Bogotá), en HTML sisjur (recomendado), PDF, DOCX, Markdown y TXT; los documentos se
integran en un **corpus consolidado** (555 + actos) que `consultar_normativa` (F2) y
`get_feasibility_report` (F3) consultan como un solo contexto, con identificación de norma por
fragmento (`norma`/`source_name` por ítem, FR-004/FR-005), precedencia temporal comunicada al
LLM vía prompt (FR-006, SC-004), deduplicación por hash SHA-256 del archivo (FR-007, SC-003),
reconstrucción automática del índice (FR-008), validación temporal/referencial contra el 555
(FR-014) y sin romper los contratos de F2/F3 (FR-011, SC-005).

Enfoque técnico (research D1–D7): la ingesta es una **extensión CLI** de `app/ingesta/corpus.py`
(patrón F2, sin tools MCP nuevas, D1): nuevo subcomando `acto` que detecta el formato
(extensión + magic bytes), extrae los artículos (parser sisjur reutilizado con adaptación
acotada D4 para las variantes `Nº.`/`<i>`, o extracción genérica D5 para PDF/DOCX/MD/TXT),
valida contra el 555 (fecha de expedición ≥ 2021-12-30 y referencia a artículos, FR-014),
escribe JSONL + `.sha256` por documento versionados en git (FR-013) y actualiza el índice
ChromaDB de forma **aditiva** en la colección única consultada por F2/F3 (FR-003, FR-011). Los
metadatos de chunk se extienden con la norma de origen (`norma_id`, `tipo_norma`, `numero`,
`año`, `fecha_vigencia`, `titulo_norma`, `relacion_con_555`); las respuestas de F2/F3 ganan
campos **aditivos** por ítem (`norma`, `source_name`); el prompt del RAG gana la regla de
precedencia temporal (D7).

## Technical Context

**Language/Version**: Python 3.11+ (requisito `requires-python = ">=3.11"`; Stack Python de la
constitución: `mcp>=1.0.0` incluye FastMCP, `httpx`, `pydantic`).

**Primary Dependencies**: Se añaden **2 dependencias de ingesta** (solo CLI, no runtime MCP):
`pypdf>=5` (PDF; verificado v6.16.0 en el PDF real del Decreto 122) y `python-docx>=1.1`
(DOCX; verificado v1.2.0). `pdfplumber` (v0.11.10 verificado) como alternativa de extracción
para layouts complejos cuando pypdf no reconstruye el orden de lectura (research D5). El parser
sisjur reutiliza `re`/stdlib; el índice reutiliza `chromadb`/`ollama` de F2.

**Storage**: Corpus consolidado versionado en git: `data/corpus/decreto_555_2021.jsonl`
(INALTERADO, norma base, FR-012) + `data/corpus/actos_modificatorios/<documento_id>.jsonl` y
`.sha256` por acto (FR-013); registro del corpus consolidado
`data/corpus/actos_modificatorios/.corpus_consolidado.json` con un hash por documento y los
metadatos del acto (FR-002, FR-007, FR-008). Índice derivado: colección ChromaDB única
(`decreto_555_2021`, la misma consultada por F2/F3) con metadatos extendidos por chunk y huella
multi-documento persistida en la metadata de la colección (FR-008).

**Testing**: `pytest` con `asyncio_mode = "auto"` (tests en `tests/contract/` y `tests/smoke/`),
patrón existente (fixtures sin red real ni Ollama). Nuevos tests: `test_ingesta_actos.py`
(parseo del 122, formatos, deduplicación, fallo atómico), `test_corpus_consolidado.py` (JSONL +
registro + re-indexación aditiva + validación FR-014), `test_precedencia.py` (regla en el
prompt, SC-004), y extensiones **ADITIVAS** de `test_consultar_normativa.py` y
`test_get_feasibility_report.py` (campos nuevos por ítem, SC-005). `tests/smoke/test_main.py`
sin cambios (no hay tools MCP nuevas).

**Target Platform**: Servidor MCP por stdio (Docker Python) + CLI de ingesta
(`python -m app.ingesta.corpus`).

**Project Type**: library/servicio CLI (servidor MCP con entrada/salida por stdio + CLI de
ingesta, patrón F2).

**Performance Goals**: SC-001 — ingesta del Decreto 122 (13 artículos) en < 5 s sin Ollama
(FR-010); re-indexación aditiva solo de los documentos cambiados (FR-008); sin cambio
apreciable en la latencia de consulta de F2/F3 (el índice es el mismo; el prompt crece en
< 1 kB).

**Constraints**: No romper F1/F2/F3 (FR-011, SC-005): campos nuevos **aditivos**, taxonomía de
errores intacta, semántica de degradación intacta; el 555 no se modifica (FR-012); fallo
atómico por documento (FR-009, SC-006); ingesta sin Ollama (FR-010); deduplicación por hash del
archivo (FR-007); validación temporal ≥ 2021-12-30 con rechazo tipificado (FR-014); sin tools
MCP nuevas (D1; la ingesta es CLI como en F2); sin credenciales embebidas (constitución).

**Scale/Scope**: 1 CLI extendida + 1 colección extendida; archivos tocados:
`app/ingesta/corpus.py` (CLI + parser), `app/ingesta/actos.py` (NUEVO), `app/models.py`
(campos aditivos), `app/providers/normativa.py` (chunk metadata + prompt), y tests; `app/main.py`
solo verificación de shapes aditivos; sin cambios en los contratos de las 7 tools existentes.

## Constitution Check

*GATE: must pass before Phase 0 research. Re-check after Phase 1 design.*

**Resultado del gate**: **APROBADO** — sin violaciones. Re-evaluado tras el diseño
(Phase 1): sin violaciones.

| Principio | Cumplimiento | Evidencia |
|-----------|--------------|-----------|
| I. Español primero | ✅ | Spec, research, data-model, contrato y quickstart en español; campos técnicos en inglés donde el contrato lo exige (`norma`, `source_name`, `documento_id`) |
| II. Modularidad por providers | ✅ | Frontera de parsing en `app/ingesta/` (un módulo por frontera: `corpus.py` para sisjur/555, `actos.py` para detección + extracción genérica); el RAG consulta el corpus consolidado vía el provider `normativa.py` existente sin cambiar su interfaz |
| III. Trazabilidad de fuentes (NON-NEGOTIABLE) | ✅ | Cada fragmento conserva los 5 campos de trazabilidad y gana `norma`/`source_name` por ítem (FR-004); `data_vigencia` del fragmento = vigencia de su norma (FR-014); identidad norma+artículo `norma_id-art-<NNN>` (assumption de la spec) |
| IV. Contratos de error explícitos (Fail Fast, Fail Loud) | ✅ | Errores tipificados para formato no soportado, sin contenido extraíble, fecha anterior a 2021-12-30 (FR-014), URL no disponible, documento duplicado; fallo atómico por documento (FR-009, SC-006); taxonomía F1–F3 intacta (FR-011) |
| V. Entrega incremental (MVP first) | ✅ | Solo la ingesta CLI + campos aditivos + precedencia vía prompt; YAGNI: sin tools MCP nuevas, sin catálogo automático SDP (Excel), sin OCR, sin eliminación/derogación de actos (fuera de alcance de la spec) |

**Complexity Tracking**: no aplica (sin violaciones que justificar).

## Project Structure

### Documentation (this feature)

```text
specs/004-ingesta-actos-modificatorios/
├── plan.md              # Este archivo (/speckit.plan command output)
├── spec.md              # Especificación de la feature (entrada)
├── research.md          # Phase 0 output: decisiones D1–D7, hallazgos H1–H7
├── data-model.md        # Phase 1 output: modelo de datos del corpus consolidado
├── quickstart.md        # Phase 1 output: guía de validación (escenarios E1–E7)
├── contracts/
│   └── ingesta-actos-modificatorios.md  # Contrato CLI + campos aditivos F2/F3
├── checklists/
│   └── requirements.md  # Checklist de requisitos (validado)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
app/
├── ingesta/
│   ├── corpus.py        # MODIFICAR: subcomando `acto` en la CLI; adaptación acotada del
│   │                    #   parser sisjur (D4) sin romper el 555; helpers de hash/metadatos
│   └── actos.py         # NUEVO: detección de formato (extensión + magic bytes), extracción
│                        #   genérica (pypdf/python-docx/MD/TXT), normalización de orden de
│                        #   lectura, validación FR-014, registro .corpus_consolidado.json y
│                        #   escritura JSONL + .sha256 por acto (FR-013)
├── models.py            # MODIFICAR: DocumentoNormativo; campos aditivos de
│                        #   ArticuloNormativo/Chunk y de la respuesta de consultar_normativa
│                        #   (norma_id, tipo_norma, numero, año, fecha_vigencia, titulo_norma,
│                        #   norma, source_name por ítem)
├── providers/
│   └── normativa.py     # MODIFICAR: consultar el corpus consolidado (misma colección),
│                        #   devolver norma/source_name por ítem (aditivo), regla de
│                        #   precedencia temporal en el prompt (D7), re-indexación aditiva
└── main.py              # SIN CAMBIOS funcionales (verificar shapes aditivos de F2/F3)

data/corpus/
├── decreto_555_2021.jsonl (+ .sha256)   # INALTERADO (norma base, FR-012)
└── actos_modificatorios/
    ├── .corpus_consolidado.json         # NUEVO: registro con hash y metadatos por documento
    ├── Decreto_122_2023.jsonl (+ .sha256)  # NUEVO: artículos del acto + metadatos de norma

tests/
├── contract/
│   ├── test_ingesta_actos.py            # NUEVO: parseo 122, formatos, dedup, fallo atómico
│   ├── test_corpus_consolidado.py       # NUEVO: registro, re-indexación aditiva, FR-014
│   ├── test_precedencia.py              # NUEVO: regla de precedencia en el prompt (SC-004)
│   └── (extensiones ADITIVAS de test_consultar_normativa.py y test_get_feasibility_report.py)
└── smoke/
    └── test_main.py     # SIN CAMBIOS (siguen las 7 tools; no hay tools MCP nuevas)
```

**Structure Decision**: Se mantiene la estructura de proyecto existente (convención F1/F2/F3).
La frontera de ingesta de actos vive en `app/ingesta/actos.py` (Principio II: un módulo por
frontera); el parser sisjur reutilizado se extiende en `corpus.py` sin reescribir el flujo del
555; el RAG consume el corpus consolidado a través de `normativa.py` sin cambiar su interfaz
interna (FR-011).

## Fases de implementación (referencia para /speckit.tasks)

> La descomposición formal en tareas T### [P] [USn] la genera `/speckit.tasks`. Esta sección
> resume el orden lógico para que el checklist de implementación los valide.

1. **Modelos y metadatos** (`app/models.py`): `DocumentoNormativo`, campos aditivos de
   `ArticuloNormativo`/`Chunk`/respuesta de `consultar_normativa` (`norma`, `source_name` por
   ítem) y del ítem de `normative_evidence` de F3 (data-model.md).
2. **Registro y extracción genérica** (`app/ingesta/actos.py`): detección de formato,
   extracción pypdf/python-docx/MD/TXT con normalización de orden de lectura, validación
   FR-014, registro `.corpus_consolidado.json`, escritura JSONL + `.sha256` (FR-013).
3. **Adaptación del parser sisjur** (`app/ingesta/corpus.py`): variante `Nº.` + título en
   `<i style="font-weight: bold;">` (D4) sin romper el 555 (regresión con `test_ingesta_f2.py`);
   captura del banner de derogación/compilación como metadato (H7).
4. **CLI de ingesta**: subcomando `acto` (descargar por URL o leer archivo local → parsear →
   validar → escribir → indexar aditivo) con fallo atómico por documento (FR-009, SC-006).
5. **RAG consolidado + precedencia** (`app/providers/normativa.py`): consulta de la colección
   consolidada, campos aditivos por ítem (FR-004/FR-005), prompt con precedencia temporal
   (FR-006, SC-004) y re-indexación aditiva por documento (FR-008).
6. **Tests**: ingesta, corpus consolidado, precedencia, extensiones aditivas F2/F3 (SC-005),
   regresión completa (185 tests de F1–F3 + nuevos).

## Notas de trazabilidad

- Las decisiones de diseño D1–D7 y los hallazgos verificados en vivo H1–H7 están
  documentados en [research.md](research.md) con su fuente; los nombres de archivos referidos
  arriba son los existentes en `app/`, `data/corpus/` y `tests/` (verificados en el repo y en
  la fase de research).
- El plan no elimina ni reescribe artículos del 555 (FR-012): los actos se integran como
  documentos nuevos; la precedencia temporal es una regla de prompt, no una sustitución de
  fuentes (FR-006).
