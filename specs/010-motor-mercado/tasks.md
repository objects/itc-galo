# Tasks: Motor de Mercado

**Input**: Diseños de `/specs/010-motor-mercado/` (plan.md, spec.md, research.md, data-model.md, contracts/market-dynamics.md, quickstart.md)

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/market-dynamics.md, quickstart.md

**Tests**: pytest — contract tests (`tests/contract/`) y smoke tests (`tests/smoke/`).

**Organization**: Las tareas se agrupan por capa (modelos → corpus → provider → orquestación → CLI → scoring → tests), siguiendo el patrón de F8 para una feature de bloque nueva. Cada tarea lleva su etiqueta de historia de usuario (`[USn]`) para trazabilidad.

## Formato: `T### [P?] [Story] Descripción — Cita`

- **[P]**: Puede ejecutarse en paralelo (archivos distintos, sin dependencias).
- **[Story]**: Historia de usuario a la que pertenece la tarea (US1=bloque, US2=ingesta, US3=CLI).
- **Cita**: referencia a `spec.md`, `data-model.md`, `contracts/`, `research.md`, `quickstart.md` o `plan.md`.

> **Nota de naming (D0)**: el spec literal usa `market_context` para el bloque nuevo, pero ese nombre YA existe en `InformeFactibilidad` (`BloqueValorReferencia` = valor de referencia **catastral**). El bloque nuevo se llama **`market_dynamics`** (entidad `ContextoMercado`). Ver research.md:D0 y plan.md:Complexity Tracking.

---

## Fase 1: Setup (Verificación de no-cambio)

- [x] T001 Verificar que F10 no requiere cambios de infraestructura: `pyproject.toml` sin dependencias nuevas (D4: scraping con `httpx` + stdlib), `.env.example` sin variables nuevas, `app/errores.py` sin códigos nuevos — plan.md:constraints, spec.md:Assumptions, research.md:D4

---

## Fase 2: Modelos (app/models.py)

- [x] T002 [P] [US2] Definir `RegistroOfertaInmobiliaria` en `app/models.py` con los campos: `id` (str), `fuente` (Literal["finca_raiz","metrocuadrado","constructora","seed"]), `url` (str | None), `precio` (float), `area_m2` (float), `precio_m2` (float), `estrato` (int | None), `amenidades` (list[str]), `localidad` (str | None), `upl` (str | None), `barrio` (str | None), `fecha_captura` (str) — data-model.md:19-40, spec.md:FR-006
- [x] T003 [P] [US1] Definir `OfertaCompetidora` en `app/models.py` con los 4 campos: `zona` (str), `conteo` (int), `precio_m2_promedio` (float | None), `estrato` (int | None) — data-model.md:42-51, spec.md:FR-001
- [x] T004 [P] [US1] Definir `RitmoAbsorcion` en `app/models.py` con los 2 campos: `unidades_mes` (float | None), `criterio` (str | None) — data-model.md:53-60, spec.md:FR-001
- [x] T005 [US1] Definir `ContextoMercado` en `app/models.py` como contenedor con los 4 campos: `precio_m2_referencia` (float | None), `estrato` (int | None), `oferta_competidora` (list[OfertaCompetidora] | None), `ritmo_absorcion` (RitmoAbsorcion | None) — data-model.md:62-72, spec.md:FR-001, contracts/market-dynamics.md:1.1
- [x] T006 [US1] Definir `BloqueMarketDynamics` en `app/models.py` con el patrón `{estado, dato, interpretation, source_trace}` (sin `source_traces`; fuente primaria única) — data-model.md:74-88, spec.md:FR-002, FR-010, contracts/market-dynamics.md:1.1
- [x] T007 [US1] Añadir campo aditivo `market_dynamics: BloqueMarketDynamics | None = None` a `InformeFactibilidad` en `app/models.py` (sin tocar `market_context` = valor catastral) — data-model.md:90-100, spec.md:FR-013

**Checkpoint**: Modelos definidos — el corpus y el provider pueden implementarse.

---

## Fase 3: Corpus de semillas + ingesta (data/corpus/mercado/, app/ingesta/mercado.py)

- [x] T008 [P] [US2] Crear `data/corpus/mercado/seeds.jsonl` con un conjunto de registros deterministas de respaldo (uno por línea, campos de `RegistroOfertaInmobiliaria`, `fuente="seed"`) — data-model.md:118-129, spec.md:FR-004, FR-005, research.md:D1, D5
- [x] T009 [US2] Crear `app/ingesta/mercado.py`: extracción best-effort con `httpx.AsyncClient` (timeout 10s) + parsing stdlib de los portales (Finca Raíz, Metrocuadrado, constructoras), respetando robots.txt/ToS; ante fallo de red/bloqueo/sin datos → fallback a seeds — spec.md:FR-004, FR-007, FR-017, research.md:D1, D4
- [x] T010 [US2] Implementar validación y deduplicación en `app/ingesta/mercado.py`: validar `estrato` ∈ 1-6, `area_m2` ≥ 36, `precio`/`area_m2` > 0; descartar registros sin precio/área con warning deduplicado; deduplicar por `id` estable (SHA-256 de `fuente+url` o clave normalizada) — spec.md:FR-006, FR-016, research.md:D6
- [x] T011 [US2] Implementar escritura del corpus consolidado en `app/ingesta/mercado.py`: `data/corpus/mercado/mercado.jsonl` + `mercado.sha256` (huella SHA-256), análogo a `descargar`/`acto` — spec.md:FR-008, FR-020, research.md:D5, contracts/market-dynamics.md:2.2

**Checkpoint**: Corpus de mercado poblado (seeds + scraping) con integridad verificable — el provider puede leerlo.

---

## Fase 4: Provider de mercado (app/providers/mercado.py)

- [x] T012 [US1] Crear `app/providers/mercado.py` con `MercadoProvider`: constante de ruta del corpus (`CORPUS_MERCADO_DIR`), `httpx.AsyncClient` con timeout configurable (default 10s), método `aclose()` — spec.md:FR-009, FR-017, FR-018, research.md:D5
- [x] T013 [US1] Implementar `consultar_market_dynamics(localidad, upl)` en `MercadoProvider`: lee el corpus local, filtra por zona (localidad/UPL, D8), calcula `precio_m2_referencia` (mediana), `estrato`, `oferta_competidora` (clustering determinista por estrato+zona, D2) y `ritmo_absorcion` (heurística, D3); retorna `tuple[ContextoMercado | None, SourceTrace]` — spec.md:FR-014, FR-015, FR-010, research.md:D2, D3, D8, contracts/market-dynamics.md:1.2

**Checkpoint**: Provider lee el corpus y produce `ContextoMercado` + traza — la orquestación puede integrarlo.

---

## Fase 5: Orquestación (app/main.py)

- [x] T014 [US1] Implementar helper `_bloque_market_dynamics(localidad, upl)` en `app/main.py`: construye el bloque con patrón `{estado, dato, interpretation, source_trace}`, `interpretation` determinista sin LLM (FR-014), degradación a `no_encontrado` + warning `BLOQUE_SIN_DATO` cuando el corpus está vacío/ilegible/sin registros para la zona — spec.md:FR-002, FR-003, FR-014, contracts/market-dynamics.md:1.2
- [x] T015 [US1] Integrar el bloque `market_dynamics` en `get_feasibility_report` (orquestación de bloques) con degradación independiente — spec.md:FR-003, FR-019, plan.md:Phase 3
- [x] T016 [US1] Integrar el bloque `market_dynamics` en `get_lot_summary_by_chip` con degradación independiente — spec.md:FR-019

**Checkpoint**: Bloque `market_dynamics` entregado en reporte y resumen — el scoring puede extenderse.

---

## Fase 6: Subcomando CLI (app/ingesta/corpus.py)

- [x] T017 [US3] Registrar subcomando `mercado` en `app/ingesta/corpus.py` con flags `--solo-semillas` / `--solo-scrape` (default híbrido), que invoca la ingesta de `app/ingesta/mercado.py` y reporta registros totales/por fuente/descartes/huella; exit 0 en éxito, ≠0 en error — spec.md:FR-008, US3, contracts/market-dynamics.md:2

**Checkpoint**: Operador puede actualizar el corpus vía CLI.

---

## Fase 7: Scoring (app/scoring.py)

- [x] T018 [US1] Añadir 3 constantes nuevas en `app/scoring.py`: `PUNTOS_CONTEXTO_MERCADO = 10`, `PUNTOS_OFERTA_COMPETIDORA = 5`, `PUNTOS_ABSORCION_MERCADO = 5` — data-model.md:102-110, spec.md:FR-011
- [x] T019 [US1] Extender `BloquesEvaluables` con el campo `market_dynamics: BloqueMarketDynamics | None = None` y actualizar `BLOQUES_EVALUABLES` (entrada adicional) — data-model.md:102-116, spec.md:FR-012
- [x] T020 [US1] Añadir 3 reglas positivas en `_reglas_positivas`: `r_contexto_mercado` (+10, precio+estrato), `r_oferta_competidora` (+5, oferta no vacía), `r_absorcion_mercado` (+5, ritmo presente) — spec.md:FR-011, data-model.md:106-110, contracts/market-dynamics.md:3
- [x] T021 [US1] Actualizar `_bloques_con_estado`, `_contar_bloques_disponibles` (o `_disponibilidad_bloques`), `_confidence_por_cobertura` y `_reasons_datos_faltantes` para el bloque evaluable adicional; umbrales absolutos sin cambio (high ≥10, medium 5-9, low ≤4); `market_dynamics: None` = no evaluado (patrón F8/Fase 3) — data-model.md:112-116, spec.md:FR-012

**Checkpoint**: Scoring extendido con determinismo preservado (SC-001/SC-007).

---

## Fase 8: Tests

- [x] T022 [US1] Crear `tests/contract/test_mercado.py` con tests del bloque `market_dynamics`: shape completo con corpus fixture (MockTransport/archivo temporal), estados `disponible`/`no_encontrado`, `source_trace` con 5 campos, interpretaciones deterministas, degradación independiente — spec.md:US1, FR-002, FR-010, FR-014, contracts/market-dynamics.md:1
- [x] T023 [P] [US2] Crear `tests/contract/test_ingesta_mercado.py` con tests de ingesta: scraping (MockTransport) + fallback a seeds, validación de rangos (estrato 1-6, área ≥36, precio/área positivos), deduplicación por id estable, escritura JSONL + huella SHA-256 — spec.md:US2, FR-005, FR-006, FR-008, research.md:D5, D6
- [x] T024 [P] [US1] Añadir tests de scoring en `tests/contract/test_scoring.py`: reglas `r_contexto_mercado` (+10), `r_oferta_competidora` (+5), `r_absorcion_mercado` (+5), determinismo SC-001, confidence con el bloque adicional, `market_dynamics: None` no evaluado — spec.md:US1, FR-011, FR-012, quickstart.md:Scoring
- [x] T025 [US3] Añadir tests del subcomando CLI `mercado` (flags `--solo-semillas`/`--solo-scrape`, exit codes) y de no-regresión: las 7 tools mantienen su contrato, bloque incluido en `get_lot_summary_by_chip` — spec.md:US3, FR-013, FR-019, SC-004, contracts/market-dynamics.md:2, 3
- [x] T026 Ejecutar pytest completo y `bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks`: verificar 0 failed, exit 0 — plan.md:constraints, SC-001, SC-004

**Checkpoint**: Suite verificada — la feature está lista para commit.

---

## Fase 9: Cierre (docs + commit)

- [x] T027 Actualizar `README.md`: documentar el bloque `market_dynamics` (motor de mercado F10) y el subcomando CLI `mercado`; `get_feasibility_report` ahora orquesta 23 bloques — plan.md:Summary
- [x] T028 Commit de la feature F10 con mensaje convencional (p. ej. `feat(mercado): bloque market_dynamics y subcomando CLI de ingesta (F10)`) — flujo Spec Kit, constitución:commit en cada hito

**Checkpoint**: Feature F10 completa y commiteada.

---

## Dependencias y orden de ejecución

### Dependencias por fase

- **Setup (Fase 1)**: sin dependencias — puede comenzar de inmediato.
- **Modelos (Fase 2)**: depende de Setup. BLOQUEA corpus/provider/orquestación/scoring.
- **Corpus + ingesta (Fase 3)**: depende de Modelos (`RegistroOfertaInmobiliaria`). Provee el archivo que lee el provider.
- **Provider (Fase 4)**: depende de Modelos (`ContextoMercado`, `BloqueMarketDynamics`) y del corpus (seeds). BLOQUEA Orquestación.
- **Orquestación (Fase 5)**: depende de Provider. BLOQUEA Scoring.
- **CLI (Fase 6)**: depende de la ingesta (Fase 3); independiente de Provider/Orquestación.
- **Scoring (Fase 7)**: depende de Orquestación (necesita `BloqueMarketDynamics`).
- **Tests (Fase 8)**: depende de todas las fases anteriores.
- **Cierre (Fase 9)**: depende de Tests.

### Dependencias entre historias de usuario

- **US1 (bloque `market_dynamics`)**: Fases 2 (modelos del bloque), 4 (provider), 5 (orquestación), 7 (scoring). Independiente tras Foundational; verificable con las seeds (sin red).
- **US2 (ingesta híbrida)**: Fases 2 (modelo `RegistroOfertaInmobiliaria`), 3 (corpus + ingesta). Proporciona el corpus que consume US1.
- **US3 (subcomando CLI)**: Fase 6. Envuelve US2; independiente de US1.

### Oportunidades de paralelismo

- T002, T003, T004 son modelos independientes → paralelo.
- T008 (seeds) y T009-T011 (módulo de ingesta) son archivos distintos → parcialmente paralelo.
- T022, T023, T024, T025 son archivos/grupos de tests independientes → paralelo.

---

## Estrategia de implementación

### MVP primero (US1 solo)

1. Fase 1 (Setup) + Fase 2 (Modelos).
2. Fase 3: solo `seeds.jsonl` (T008) — sin scraping — para que el bloque funcione sin red.
3. Fase 4 (Provider) + Fase 5 (Orquestación) + Fase 7 (Scoring).
4. Fase 8: `test_mercado.py` + `test_scoring.py` (sin scraping).
5. **STOP y VALIDAR**: `get_feasibility_report` devuelve `market_dynamics` poblado con seeds.
6. Luego US2 completa (scraping) y US3 (CLI).

### Entrega incremental

1. Setup + Modelos → base lista.
2. Seeds + bloque `market_dynamics` (US1) → reporte enriquecido, testeable sin red (MVP).
3. Scraping real + validación/dedup (US2) → corpus con datos reales.
4. Subcomando CLI (US3) → operación de mantenimiento explícita.
5. Cada historia agrega valor sin romper las previas.

---

## Notas

- [P] = archivos distintos, sin dependencias.
- [USn] mapea la tarea a su historia de usuario para trazabilidad.
- Verificar que los tests nuevos FALLAN antes de la implementación (TDD, patrón del repo).
- Commit tras cada fase o grupo lógico.
- Detenerse en cualquier checkpoint para validar la historia independientemente.
- Evitar: tareas vagas, conflictos en el mismo archivo, dependencias entre historias que rompan independencia.
