# Implementation Plan: Informe de factibilidad orquestado (`get_feasibility_report`)

**Branch**: `003-informe-factibilidad` | **Date**: 2026-08-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-informe-factibilidad/spec.md`

**Note**: Este plan es la salida del comando `/speckit.plan` (Phase 0 + Phase 1). Los
artefactos de diseño son [research.md](research.md), [data-model.md](data-model.md),
[contracts/get-feasibility-report.md](contracts/get-feasibility-report.md) y
[quickstart.md](quickstart.md). La descomposición en tareas (`tasks.md`) la genera el
comando `/speckit.tasks` (Phase 2), NO este plan.

## Summary

Requisito primario (FR-001 a FR-014): emitir el **informe de factibilidad** de un lote
catastral de Bogotá en una sola tool MCP (`get_feasibility_report`) que orquesta la
resolución del lote (por CHIP, dirección o coordenadas), su UPL/localidad, los bloques
temáticos (reserva vial, valor de referencia, obras públicas en radio de 500 m), el
contexto económico (destino económico desde la capa catastral viva `catastro/lote/MapServer/3`),
la evidencia normativa del POT (consulta opcional o automática) y un `feasibility_score`
0–100 **100 % determinístico sin LLM** con confidence y reasons trazables; con degradación
por bloque (no por error) y los 6 errores fatales de FR-012.

Enfoque técnico (research D1–D5): el reporte es la **7ª tool** en `ServidorLotes`
(app/main.py) reutilizando los flujos privados de F1/F2 sin modificarlos; el destino
económico vive en un nuevo método de `ArcGISProvider` (`consultar_destino_economico`,
capa tabular Predio, `f=pjson`, join por `PRECHIP` o `BARMANPRE`) que reactiva el modelo
`DestinoEconomico` ya definido en F1 sin tocar `ContextoTematico`; `environment_context`
usa un nuevo `consultar_obras_publicas_radio(500m)` (la capa es multipunto, FR-004); el
scoring es una función pura en `app/scoring.py`; el orquestador captura
`UplNoEncontradaError`/`CorpusNoIngestadoError`/`OllamaNoDisponibleError` como
degradaciones representadas en el reporte (no como errores de la tool).

## Technical Context

**Language/Version**: Python 3.11+ (requisito `requires-python = ">=3.11"`; Stack Python de la
constitución: `mcp>=1.0.0` incluye FastMCP, `httpx`, `pydantic`).

**Primary Dependencies**: `mcp>=1.0.0` (FastMCP/MCPServer), `httpx>=0.27.0`, `pydantic>=2.7.0`;
dev: `pytest>=8.0.0`, `pytest-asyncio>=0.23.0`. NO se añaden dependencias nuevas (la capa
Predio es ArcGIS REST ya cubierta por `httpx`; el RAG reutiliza `chromadb`/`ollama` de F2).

**Storage**: Sin almacenamiento nuevo en F3. El `economic_context` se consulta en vivo a
ArcGIS REST (`f=pjson`); el RAG reutiliza la colección ChromaDB de F2 (`.data/chroma`,
`VECTOR_DB_PATH`). Los dominios `D_PreDestino`/`D_UsoTUso` se versionan como constantes del
provider (research H1, patrón del mapeo NOMBRE→localidad de F2).

**Testing**: `pytest` con `asyncio_mode = "auto"` (tests en `tests/contract/` y
`tests/smoke/`); patrón existente: servidores con `MockTransport`, providers mockeados,
tests de contrato/estados/trazabilidad/validación. Nuevos tests: `test_get_feasibility_report.py`,
`test_scoring.py` (determinismo), extensiones de `test_trazabilidad.py` si aplica.

**Target Platform**: Servidor MCP por stdio (Docker Python; el contenedor ejecuta
`mcp-bogota-factibilidad`).

**Project Type**: library/servicio CLI (servidor MCP con entrada/salida por stdio).

**Performance Goals**: SC-001 — reporte completo en < 10 s sin normativa y < 20 s con
evidencia normativa, en condiciones normales de red. El bloque económico es una consulta
adicional al `asyncio.gather` de F1 (paralelizable); el RAG hereda la latencia de
`consultar_normativa` de F2.

**Constraints**: Trazabilidad NON-NEGOTIABLE de 5 campos en cada bloque de datos (FR-010,
SC-002); sin mezclar vigencias (FR-008); determinismo del score (SC-003); degradación por
bloque y no por error (FR-009/FR-012, SC-005); `f=pjson` obligatorio en la capa Predio
(`f=geojson` → 400); NO modificar F1/F2 (CHK-015); sin LLM en score ni interpretaciones
(FR-007); sin credenciales embebidas (constitución; `MAPAS_BOGOTA_APIKEY` solo vía entorno,
opcional salvo geocodificación).

**Scale/Scope**: 1 tool nueva (7ª) en un servidor MCP existente; ~4 archivos tocados/creados
(app/main.py, app/providers/arcgis.py, app/models.py, app/scoring.py) + tests; sin cambios a
los contratos de las 6 tools existentes.

## Constitution Check

*GATE: must pass before Phase 0 research. Re-check after Phase 1 design.*

**Resultado del gate**: **APROBADO** — sin violaciones. Re-evaluado tras el diseño
(Phase 1): sin violaciones.

| Principio | Cumplimiento | Evidencia |
|-----------|--------------|-----------|
| I. Español primero | ✅ | Spec, research, data-model y contrato en español; campos técnicos en inglés donde el contrato lo exige (`score`, `source_trace`, `interpretation`, `estado`) |
| II. Modularidad por providers | ✅ | Frontera de parsing de la capa Predio en `ArcGISProvider.consultar_destino_economico` (D5); sin providers nuevos (la capa es ArcGIS) |
| III. Trazabilidad de fuentes (NON-NEGOTIABLE) | ✅ | Cada bloque lleva `SourceTrace` de 5 campos (FR-010, SC-002); `data_vigencia` del bloque económico = `PREVACTUAL` del registro (H7); score heurístico sin inferir normativa (FR-014) |
| IV. Contratos de error explícitos (Fail Fast, Fail Loud) | ✅ | 6 errores fatales vía `_error_de_fuente` (FR-012); degradaciones representadas en el reporte (D5, divergencia documentada en research.md); 5xx nunca degradado a `no_encontrado` |
| V. Entrega incremental (MVP first) | ✅ | Solo la tool `get_feasibility_report` + sus 3 piezas (provider/arcgis, models, scoring); YAGNI: sin orquestador nuevo, sin providers nuevos, sin diagnóstico de prefactibilidad (mejora futura fuera de alcance) |

**Complexity Tracking**: no aplica (sin violaciones que justificar).

## Project Structure

### Documentation (this feature)

```text
specs/003-informe-factibilidad/
├── plan.md              # Este archivo (/speckit.plan command output)
├── spec.md              # Especificación de la feature (entrada)
├── research.md          # Phase 0 output: decisiones D1–D5, hallazgos H1–H7
├── data-model.md        # Phase 1 output: modelo de datos y reglas del reporte
├── quickstart.md        # Phase 1 output: guía de validación (escenarios E1–E9)
├── contracts/           # Phase 1 output:
│   └── get-feasibility-report.md   # Contrato JSON Schema de la 7ª tool
├── checklists/
│   └── requirements.md  # Checklist de requisitos (validado)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
app/
├── main.py              # MODIFICAR: 7ª tool `get_feasibility_report` en ServidorLotes;
│                        #   registrar en crear_servidor_mcp; pipeline de orquestación
│                        #   (validación → lote → UPL → temáticas → económico →
│                        #   normativa → scoring → reporte)
├── models.py            # MODIFICAR: reactivar `DestinoEconomico` con la nueva fuente;
│                        #   añadir `UsoEconomico`, `FeasibilityScore`, `InformeFactibilidad`
│                        #   y modelos de bloque (shapes del data-model.md)
├── scoring.py           # NUEVO: función pura `calcular_score` + reglas/clamp/confidence/reasons
│                        #   (research D3; determinismo SC-003)
├── errores.py           # SIN CAMBIOS (se reutilizan los 10 códigos y _error_de_fuente)
└── providers/
    ├── arcgis.py        # MODIFICAR: `consultar_destino_economico(chip, codigo_catastral)`
    │                    #   (capa Predio 3, f=pjson, join PRECHIP/BARMANPRE, dominios
    │                    #   versionados, selección por mayor PREAUSO) y
    │                    #   `consultar_obras_publicas_radio(lng, lat, radio_m=500)`
    ├── upl.py           # SIN CAMBIOS (UPL.vocacion ya parseado; research H4)
    ├── normativa.py     # SIN CAMBIOS (se reutiliza consultar_normativa tal cual; H6)
    └── mapas_bogota.py  # SIN CAMBIOS (geocodificación reutilizada en el flujo por dirección)

tests/
├── contract/
│   ├── test_get_feasibility_report.py   # NUEVO: contrato 10 bloques, ejemplos, errores
│   │                                    #   fatales, degradaciones y warnings
│   ├── test_scoring.py                  # NUEVO: determinismo, reglas, clamp, confidence,
│   │                                    #   reasons (SC-003)
│   └── (extensiones de test_validacion.py / test_trazabilidad.py si aplica)
└── smoke/
    └── test_main.py     # MODIFICAR: registrar la 7ª tool en la lista de tools del servidor
```

**Structure Decision**: Se mantiene la estructura de proyecto existente (convención de F1/F2).
El orquestador es un método de `ServidorLotes` (patrón del proyecto, D5); el scoring es un
módulo puro nuevo (`app/scoring.py`) para cumplir la Ley 3 (Atomic Predictability) y aislar
las reglas para test de determinismo; no se crean servicios/providers nuevos (YAGNI).

## Fases de implementación (referencia para /speckit.tasks)

> La descomposición formal en tareas T### [P] [USn] la genera `/speckit.tasks`. Esta sección
> resume el orden lógico para que el checklist de implementación los valide.

1. **Modelos** (`app/models.py`): `UsoEconomico`, `DestinoEconomico` reactivado,
   `FeasibilityScore`, modelos de bloque e `InformeFactibilidad` (data-model.md).
2. **Provider ArcGIS** (`app/providers/arcgis.py`): `consultar_destino_economico` (con
   dominios versionados `D_PreDestino`/`D_UsoTUso`) y `consultar_obras_publicas_radio`.
3. **Scoring** (`app/scoring.py`): `calcular_score` puro (base 50, reglas +/−, clamp,
   confidence por cobertura, reasons fijos; D3).
4. **Orquestación** (`app/main.py`): pipeline del reporte (validación FR-013 → lote →
   UPL → temáticas + buffer → económico → normativa con degradación → score → 10 bloques),
   captura de `UplNoEncontradaError`/RAG, warnings deduplicados; registro de la 7ª tool.
5. **Tests**: contrato, estados/degradación, validación, determinismo del scoring,
   trazabilidad; smoke de registro de la tool.

## Notas de trazabilidad

- Las decisiones de diseño D1–D5 y los hallazgos verificados en vivo H1–H7 están
  documentados en [research.md](research.md) con su fuente; los nombres de los archivos de
  código referidos arriba son los existentes en `app/` y `tests/` (verificados en el repo).
- El plan no introduce reglas de negocio urbanístico: el `feasibility_score` es heurístico
  sobre disponibilidad/afectación de las fuentes (FR-014; mejora futura fuera de alcance).
