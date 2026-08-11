# Tasks: Resolver lote con contexto temático

**Input**: Diseños de `/specs/001-resolver-lote-contexto/` (plan.md, spec.md, research.md, data-model.md, contracts/)

**Prerequisites**: plan.md (obligatorio), spec.md (obligatorio para historias de usuario), research.md, data-model.md, contracts/

**Tests**: pytest — smoke test de arranque (`tests/smoke`) y contract tests (`tests/contract`) según plan.md:33; las historias incluyen sus contract tests (escribirlos primero para que fallen antes de implementar).

**Organization**: Las tareas se agrupan por historia de usuario para permitir implementación y pruebas independientes de cada historia (constitución v1.0.0, Principio V — MVP first).

## Formato: `T### [P?] [Story] Descripción — Cita`

- **[P]**: Puede ejecutarse en paralelo (archivos distintos, sin dependencias).
- **[Story]**: Historia de usuario a la que pertenece la tarea (US1, US2, US3).
- **Cita**: referencia a `spec.md` (FR/SC) o `plan.md` con línea, p. ej. `spec.md:77`.

## Convenciones de rutas

- Proyecto único: `app/`, `tests/` en la raíz del repositorio (plan.md:96).
- Estructura: `app/main.py` (FastMCP), `app/models.py` (pydantic), `app/providers/` (un provider por fuente), `tests/contract/` y `tests/smoke/`.

---

## Fase 1: Setup (Infraestructura compartida)

**Propósito**: inicialización del proyecto y estructura básica

- [x] T001 Crear la estructura del proyecto `app/` modular (`app/`, `app/providers/`, `tests/`, `tests/contract/`, `tests/smoke/`) — plan.md:96
- [x] T002 [P] Crear `pyproject.toml` con dependencias `mcp>=1.0.0`, `httpx`, `pydantic` y dev `pytest` — plan.md:28
- [x] T003 [P] Crear `.env.example` documentando `MAPAS_BOGOTA_APIKEY` (opcional, salvo consulta por dirección) — plan.md:50
- [x] T004 [P] Crear `README.md` en español con instalación, configuración y ejecución del servidor — plan.md:51
- [x] T005 [P] Crear `Dockerfile` Python 3.11+ (imagen multi-etapa, transporte MCP por stdio) y entradas de `.gitignore` — plan.md:26, plan.md:37, constitution.md:54 (Docker multi-etapa); `.gitignore` según convenciones del workspace (plan.md:96)

---

## Fase 2: Foundational (Prerrequisitos bloqueantes)

**Propósito**: infraestructura central que DEBE estar completa antes de que cualquier historia de usuario pueda implementarse

**⚠️ CRITICAL**: ningún trabajo de historias de usuario puede comenzar hasta que esta fase esté completa

- [x] T006 Definir modelos pydantic v2 en `app/models.py`: `Lote`, `ValorReferencia`, `DestinoEconomico`, `ReservaVial`, `ObraPublica` — spec.md:92
- [x] T007 Definir `SourceTrace` en `app/models.py` con los 5 campos obligatorios (`source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp`) — spec.md:82
- [x] T008 Definir el estado por dato (`disponible` | `no_encontrado`) en las entidades temáticas de `app/models.py` — spec.md:83
- [x] T009 Definir la taxonomía de errores canónica en `app/models.py` (`LOTE_NO_ENCONTRADO`, `DIRECCION_NO_LOCALIZADA`, `FUERA_DE_COBERTURA`, `DATO_NO_ENCONTRADO_POR_FUENTE`, `FUENTE_5XX`, `CREDENCIAL_FALTANTE`, `PARAMETROS_INVALIDOS`) — spec.md:85, spec.md:88, spec.md:65-71, data-model.md:137-149
- [x] T010 [P] Implementar provider `app/providers/mapas_bogota.py`: cliente httpx async para Mapas Bogotá API (`cmd=direccion_chip`, `cmd=geocodificar`) con `raise_for_status` para detectar 5xx — plan.md:100, spec.md:85
- [x] T011 [P] Implementar provider `app/providers/arcgis.py`: cliente httpx async para ArcGIS REST con query por punto (`esriGeometryPoint`, `inSR=4326`, `spatialRel=esriSpatialRelIntersects`) y `where` por `ESOCLOTE` — plan.md:101, spec.md:80
- [x] T012 Implementar `app/main.py`: servidor FastMCP por stdio registrando EXACTAMENTE las 4 tools (`resolve_lot_by_chip`, `resolve_lot_by_address`, `resolve_lot_by_coordinates`, `get_lot_summary_by_chip`) — plan.md:97, plan.md:37

**Checkpoint**: fundación lista — las historias de usuario pueden comenzar.

---

## Fase 3: Historia de Usuario 1 — Consultar un lote por CHIP y obtener su resumen con contexto (Prioridad: P1) 🎯 MVP

**Goal**: resolver el lote por CHIP (Mapas Bogotá `cmd=direccion_chip` + capa Lote ArcGIS `layer_id=38`) y devolver el resumen consolidado con contexto temático y trazabilidad por fuente.

**Prueba independiente**: consultar un CHIP válido y verificar que la respuesta contiene la identidad del lote (CHIP, manzana, dirección) y el contexto temático con su trazabilidad, sin requerir dirección ni coordenadas; probar también el CHIP inexistente — spec.md:21

### Tests para Historia de Usuario 1 (escribirlos PRIMERO para que fallen antes de implementar)

- [x] T013 [P] [US1] Contract test de `resolve_lot_by_chip` en `tests/contract/test_resolve_lot_by_chip.py` — spec.md:21
- [x] T014 [P] [US1] Contract test de `get_lot_summary_by_chip` en `tests/contract/test_get_lot_summary_by_chip.py` — spec.md:21

### Implementación para Historia de Usuario 1

- [x] T015 [P] [US1] Implementar validación de CHIP con patrón `^[A-Z0-9]{11}$` en el límite de las tools (fail-fast, `PARAMETROS_INVALIDOS`) — spec.md:88
- [x] T016 [P] [US1] Implementar búsqueda por CHIP vía Mapas Bogotá `cmd=direccion_chip` (geometría del predio + centroide) en `app/providers/mapas_bogota.py` — plan.md:100, spec.md:77
- [x] T017 [P] [US1] Implementar consulta de la capa Lote (`Mapa_Referencia/Mapa_Referencia`, `layer_id=38`) por punto/centroide en `app/providers/arcgis.py` — plan.md:101, spec.md:77
- [x] T018 [US1] Implementar las 4 consultas temáticas (`catastro/valorreferencia`, `catastro/destinolt` por `ESOCLOTE`, `ordenamientoterritorial/reservavial`, `gestionpublica/obraspublicas`) en `app/providers/arcgis.py`, cada una con su `data_vigencia`, ejecutadas en paralelo con `asyncio.gather` (SC-001, rendimiento <10 s) — spec.md:80, spec.md:84, spec.md:102, research.md:53-54
- [x] T019 [US1] Implementar `resolve_lot_by_chip` completa: resolver lote (identidad + geometría + centroide) y enriquecer con contexto temático y trazabilidad por fuente — spec.md:77, spec.md:82
- [x] T020 [US1] Implementar `get_lot_summary_by_chip` completa: resumen consolidado descriptivo (`identidad` + `contexto_por_fuente`), sin puntajes de factibilidad ni reglas inferidas — spec.md:81, spec.md:87

**Checkpoint**: Historia de Usuario 1 funcional y comprobable de forma independiente.

---

## Fase 4: Historia de Usuario 2 — Consultar un lote por dirección (Prioridad: P2)

**Goal**: resolver el lote por dirección (geocodificación con `cmd=geocodificar` + capa Lote) con fail-fast de credencial y manejo explícito de candidatos múltiples.

**Prueba independiente**: consultar una dirección conocida y localizable de Bogotá y verificar que el sistema resuelve el lote asociado y devuelve su resumen; probar también el caso de dirección no localizable — spec.md:37

### Tests para Historia de Usuario 2 (escribirlos PRIMERO para que fallen antes de implementar)

- [x] T021 [P] [US2] Contract test de `resolve_lot_by_address` en `tests/contract/test_resolve_lot_by_address.py` (resolución única, dirección no localizada, múltiples candidatos, credencial faltante) — spec.md:37, spec.md:43, spec.md:86

### Implementación para Historia de Usuario 2

- [x] T022 [P] [US2] Implementar fail-fast de credencial en el límite de la tool `resolve_lot_by_address` en `app/main.py`: si falta `MAPAS_BOGOTA_APIKEY` en el entorno → `CREDENCIAL_FALTANTE` sin llamar a las fuentes — spec.md:86, contracts/resolve-lot-by-address.md:43-45
- [x] T023 [US2] Implementar geocodificación de dirección (`cmd=geocodificar`) en `app/providers/mapas_bogota.py` — plan.md:100, spec.md:78
- [x] T024 [US2] Implementar resolución del lote por punto geocodificado reutilizando la capa Lote y las temáticas de US1 — spec.md:78, spec.md:80
- [x] T025 [US2] Implementar manejo de múltiples candidatos: respuesta `multiples_candidatos` con `candidatos` y `source_trace` de `geocodificar`, sin elegir uno arbitrariamente — spec.md:43
- [x] T026 [US2] Implementar error `DIRECCION_NO_LOCALIZADA` (sin inventar ni asumir un lote) y completar `resolve_lot_by_address` — spec.md:78, spec.md:66

**Checkpoint**: Historias de Usuario 1 y 2 funcionales de forma independiente.

---

## Fase 5: Historia de Usuario 3 — Consultar un lote por coordenadas (Prioridad: P3)

**Goal**: resolver el lote que contiene un punto (capa Lote ArcGIS con `esriGeometryPoint`, `inSR=4326`) sin credencial, con manejo explícito de cobertura y de límites.

**Prueba independiente**: consultar un punto que cae dentro de un lote catastral conocido de Bogotá y verificar que el sistema resuelve ese lote; probar también el rechazo de puntos fuera de Bogotá — spec.md:53

### Tests para Historia de Usuario 3 (escribirlos PRIMERO para que fallen antes de implementar)

- [x] T027 [P] [US3] Contract test de `resolve_lot_by_coordinates` en `tests/contract/test_resolve_lot_by_coordinates.py` (punto dentro de un lote, punto fuera de Bogotá, límite entre lotes sin lote único) — spec.md:53, spec.md:59

### Implementación para Historia de Usuario 3

- [x] T028 [P] [US3] Verificar la consulta por punto de la capa Lote reutilizando el helper de T017 dentro del flujo de `resolve_lot_by_coordinates`, validando `FUERA_DE_COBERTURA` (spec.md:58) y `LOTE_NO_ENCONTRADO` (spec.md:59) — spec.md:53, spec.md:79
- [x] T029 [US3] Implementar error `FUERA_DE_COBERTURA` para puntos dentro de rango pero fuera del área de Bogotá — spec.md:79, spec.md:67
- [x] T030 [US3] Implementar `LOTE_NO_ENCONTRADO` para puntos en límite entre lotes o sin lote asociado, y completar `resolve_lot_by_coordinates` — spec.md:59

**Checkpoint**: las tres historias de usuario funcionales de forma independiente.

---

## Fase 6: Polish y transversal

**Propósito**: pruebas, verificación de trazabilidad y mejoras que afectan a múltiples historias

- [x] T031 [P] Smoke test de arranque en `tests/smoke/test_main.py`: el servidor inicia y las 4 tools quedan registradas — plan.md:33
- [x] T032 [P] Contract tests de la taxonomía de errores en `tests/contract/test_errores.py`: un 5xx de la fuente se reporta como `FUENTE_5XX` y NUNCA como no encontrado; se verifican los 7 códigos canónicos — spec.md:85
- [x] T033 [P] Contract tests de validación FR-012 en `tests/contract/test_validacion.py`: CHIP mal formado, dirección vacía y coordenadas fuera de rango → `PARAMETROS_INVALIDOS` — spec.md:88
- [x] T034 [P] Verificar trazabilidad completa en `tests/contract/test_trazabilidad.py`: los 5 campos (`source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp`) en cada dato y nunca mezclar vigencias — spec.md:104, spec.md:105
- [x] T035 Verificar estados `disponible` / `no_encontrado` por fuente en el 100% de las respuestas (SC-002) en `tests/contract/test_estados.py` — spec.md:103
- [x] T036 Validar contra `quickstart.md` los escenarios de CHIP, coordenadas, dirección sin credencial y trazabilidad en `tests/contract/test_quickstart.py` (SC-005, SC-006, SC-003/SC-004, FR-010; SC-001 de rendimiento <10 s se valida contra quickstart.md) — spec.md:86, spec.md:102, spec.md:104, spec.md:105, spec.md:106, spec.md:107

---

## Dependencias y orden de ejecución

### Dependencias por fase

- **Setup (Fase 1)**: sin dependencias — puede comenzar de inmediato.
- **Foundational (Fase 2)**: depende de Setup — BLOQUEA todas las historias.
- **Historias de usuario (Fases 3-5)**: dependen de Foundational; además, US2 (T024) y US3 (T030) reutilizan la capa Lote y las temáticas de US1 (T017/T018), por lo que dependen de esas tareas y NO pueden comenzar hasta que aterricen. El orden MVP-first secuencial (P1 → P2 → P3) es el previsto; no hay paralelismo real entre historias.
- **Polish (Fase 6)**: depende de las historias deseadas completas.

### Dentro de cada historia

- Los contract tests se escriben PRIMERO y deben fallar antes de implementar.
- Validación y manejo de errores antes de la integración completa de la tool.
- La historia se completa antes de pasar a la siguiente prioridad.

### Oportunidades de paralelismo

- Todas las tareas [P] de Setup y Foundational pueden ejecutarse en paralelo.
- T015, T016, T017 (US1) tocan archivos distintos (`main.py`, `mapas_bogota.py`, `arcgis.py`) y pueden ejecutarse en paralelo.
- T024 (US2), T028 y T030 (US3) reutilizan el helper de la capa Lote (T017) y las temáticas (T018) de US1: dependen de esas tareas y NO pueden ejecutarse en paralelo con US1 (dependencia real entre historias).
- Los contract tests [P] de cada historia pueden ejecutarse en paralelo.

---

## Estrategia de implementación

### MVP primero (solo Historia de Usuario 1)

1. Completar Fase 1 (Setup).
2. Completar Fase 2 (Foundational) — CRÍTICO, bloquea todo.
3. Completar Fase 3 (Historia de Usuario 1).
4. **DETENERSE y VALIDAR**: probar la Historia de Usuario 1 de forma independiente (SC-005).
5. Continuar con US2 y US3 (entrega incremental).

### Entrega incremental

1. Setup + Foundational → fundación lista.
2. Agregar Historia de Usuario 1 → probar independientemente → MVP.
3. Agregar Historia de Usuario 2 → probar independientemente.
4. Agregar Historia de Usuario 3 → probar independientemente.
5. Cada historia agrega valor sin romper las anteriores.

---

## Notas

- [P] = archivos distintos, sin dependencias.
- [Story] = historia de usuario para trazabilidad de la tarea.
- Cada historia es completable y comprobable de forma independiente.
- Verificar que los tests fallen antes de implementar.
- Commit en cada hito ratificado (constitución, Flujo de desarrollo).
- Evitar tareas vagas, conflictos de archivos compartidos y dependencias entre historias que rompan la independencia.
