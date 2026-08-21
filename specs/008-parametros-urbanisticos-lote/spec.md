# Feature Specification

**Rama del feature**: `008-parametros-urbanisticos-lote`

**Creado**: 2026-08-20

**Estado**: Draft

**Entrada**: Descripción del usuario: "Feature 8 de mcp-bogota-factibilidad: enriquecer el informe de factibilidad (get_feasibility_report) con un bloque `urbanistic_parameters` que consulta los parámetros urbanísticos del lote (tratamiento urbanístico, COS, CUS, altura máxima, retiros frontales/laterales/posteriores, y estacionamientos requeridos) para evaluar la factibilidad de construcción. El tratamiento se resuelve espacialmente vía capa ArcGIS del SINUPOT/SDP (`sinu.sdp.gov.co/serverp/rest/services/POT555/NORMA_URBANÍSTICA_Y_OT/MapServer`, layer 2: tratamiento, layer 14: rangos de edificabilidad). Los parámetros numéricos (COS, CUS, altura, retiros, estacionamientos) se obtienen vía RAG normativo del Decreto 555/2021 (art. 281 edificabilidad/altura, art. 389 estacionamientos, Anexo 5 Manual de Normas Comunes). El bloque sigue el patrón `{estado, dato, interpretation, source_trace}` de F3/F6/F7, degrada independientemente, y extiende el scoring con un bloque evaluable adicional (13 bloques evaluables total). No se añaden tools MCP nuevas."

---

## User Scenarios & Testing (obligatorio)

### User Story 1 (P1) — Parámetros urbanísticos del lote

Como usuario del servidor MCP, quiero que al consultar la factibilidad de un lote se incluyan los parámetros urbanísticos (tratamiento urbanístico, COS, CUS, altura máxima, retiros frontales/laterales/posteriores, y estacionamientos requeridos) para evaluar la factibilidad de construcción.

**Por qué esta prioridad**: los parámetros urbanísticos son el factor más determinante en la factibilidad de un proyecto de construcción. El tratamiento urbanístico define qué se puede construir (usos, intensidad), y los parámetros numéricos (COS, CUS, altura, retiros) determinan las dimensiones físicas del proyecto. Sin esta información, la factibilidad es incompleta.

**Prueba independiente**: invocar `get_feasibility_report` con un CHIP válido y verificar que `urbanistic_parameters` tiene el patrón `{estado, dato, interpretation, source_trace}` con los campos `tratamiento`, `cos`, `cus`, `altura_maxima`, `retiros`, `estacionamientos`. También verificar que el scoring incluye el bloque evaluable adicional.

**Escenarios de aceptación**:
1. Dado un lote con datos de tratamiento disponibles, cuando se genera el reporte, entonces `urbanistic_parameters.dato.tratamiento` contiene la denominación del tratamiento y el código de la capa SINUPOT.
2. Dado un lote con tratamiento de desarrollo, cuando se genera el reporte, entonces `urbanistic_parameters.dato.cos` y `urbanistic_parameters.dato.cus` contienen los valores numéricos del Anexo 5 del POT.
3. Dado un lote con datos de edificabilidad disponibles, cuando se genera el reporte, entonces `urbanistic_parameters.dato.altura_maxima_m` contiene la altura máxima permitida en metros.
4. Dado un lote con datos de retiros disponibles, cuando se genera el reporte, entonces `urbanistic_parameters.dato.retiros` contiene `frontal_m`, `laterales_m` y `posteros_m`.
5. Dado un lote con datos de estacionamientos, cuando se genera el reporte, entonces `urbanistic_parameters.dato.estacionamientos` contiene `requeridos` y `criterio`.
6. Dado un lote sin datos de tratamiento, cuando se genera el reporte, entonces `urbanistic_parameters.estado == "no_encontrado"` con `interpretation` que indica la ausencia.
7. Dado que la capa SDP/SINUPOT falla, cuando se genera el reporte, entonces `urbanistic_parameters` se degrada con warning sin afectar otros bloques.

### User Story 2 (P2) — Scoring extendido con parámetros urbanísticos

Como usuario del servidor MCP, quiero que el scoring de factibilidad incorpore la disponibilidad de parámetros urbanísticos para que el puntaje refleje la completitud de la información disponible.

**Por qué esta prioridad**: el scoring es el indicador principal de factibilidad; un lote con parámetros urbanísticos disponibles tiene información más completa que uno sin ellos, lo que debe reflejarse en el puntaje.

**Prueba independiente**: invocar `get_feasibility_report` con un CHIP válido y verificar que `feasibility_score.rules_applied` incluye las reglas nuevas (`r_parametros_urbanisticos`, `r_estacionamientos_calculados`, `r_tratamiento_conservacion`).

**Escenarios de aceptación**:
1. Dado un lote con tratamiento y edificabilidad disponibles, cuando se genera el reporte, entonces `feasibility_score` aplica bonus de +10 y `rules_applied` incluye `r_parametros_urbanisticos`.
2. Dado un lote con estacionamientos calculados, cuando se genera el reporte, entonces `feasibility_score` aplica bonus de +5 y `rules_applied` incluye `r_estacionamientos_calculados`.
3. Dado un lote en tratamiento de conservación sin licencia especial, cuando se genera el reporte, entonces `feasibility_score` aplica penalización de −15 y `rules_applied` incluye `r_tratamiento_conservacion`.

### Edge Cases
- **La capa SDP/SINUPOT falla (5xx)**: el bloque se reporta como `no_encontrado` con warning `BLOQUE_DEGRADADO`; el resto del reporte continúa.
- **La capa SDP responde sin features para el lote**: el bloque se reporta como `no_encontrado` con interpretation que indica que el lote no tiene tratamiento asignado en la capa.
- **El RAG normativo no retorna artículos para el tratamiento**: los campos numéricos (COS, CUS, altura, retiros, estacionamientos) quedan en `None`; el bloque mantiene estado `"disponible"` si el tratamiento fue resuelto.
- **Tratamiento resuelto pero parámetros numéricos ausentes**: el bloque tiene estado `"disponible"` con los campos numéricos en `None`; la interpretación indica que los parámetros no están disponibles en el corpus normativo.
- **Lote sin UPL resuelta**: el bloque se consulta igualmente (no depende de la UPL para el tratamiento espacial).
- **Tratamiento en zona de conservación patrimonial**: se aplica penalización de −15 en scoring solo si `tratamiento == "Conservación"` (patrón exacto del SINUPOT).
- **Degradación independiente**: si la capa SDP falla pero el RAG responde, o viceversa, cada fuente se evalúa por separado dentro del bloque.

---

## Requirements (obligatorio)

### Functional Requirements

- FR-001: El reporte DEBE incluir un bloque `urbanistic_parameters` con los campos: `tratamiento` (denominación + código), `cos` (float o null), `cus` (float o null), `altura_maxima_m` (float o null), `retiros` (objeto con `frontal_m`, `laterales_m`, `posteros_m` o null), `estacionamientos` (objeto con `requeridos` entero y `criterio` string o null).
- FR-002: El tratamiento urbanístico DEBE resolverse espacialmente vía la capa ArcGIS REST del SINUPOT/SDP: `sinu.sdp.gov.co/serverp/rest/services/POT555/NORMA_URBANÍSTICA_Y_OT/MapServer`, layer 2 (tratamiento).
- FR-003: Los parámetros numéricos (COS, CUS, altura máxima, retiros, estacionamientos) DEBEN obtenerse vía RAG normativo del Decreto 555/2021, consultando artículos relevantes (art. 281 edificabilidad/altura, art. 389 estacionamientos, Anexo 5 Manual de Normas Comunes a Tratamientos Urbanísticos).
- FR-004: La consulta a la capa de tratamiento DEBE usar el centroide del lote como punto de consulta con `geometry=<lng,lat>&geometryType=esriGeometryPoint&inSR=4326&outSR=4686&spatialRel=esriSpatialRelIntersects`.
- FR-005: La capa de tratamiento del SINUPOT usa el CRS EPSG:4686 (MAGNA-SIRGAS); la consulta DEBE usar `inSR=4326` y `outSR=4686` para la conversión correcta.
- FR-006: Opcionalmente, la capa de rangos de edificabilidad (layer 14) DEBE consultarse para obtener COS/CUS/altura por tratamiento de desarrollo, complementando la información del RAG.
- FR-007: El bloque `urbanistic_parameters` DEBE seguir el patrón `{estado, dato, interpretation, source_trace}` de F3/F6/F7.
- FR-008: El bloque DEBE degradarse independientemente de otros bloques: si la capa SDP falla, el bloque se reporta como `no_encontrado` con warning `BLOQUE_DEGRADADO`; si el RAG falla, los campos numéricos quedan en `None` pero el tratamiento espacial se mantiene.
- FR-009: Un 5xx de la capa SDP NO DEBE ser tratado como `"no_encontrado"` si el RAG respondió exitosamente; el bloque mantiene estado `"disponible"` con tratamiento del SINUPOT y campos numéricos del RAG.
- FR-010: El bloque DEBE incluir `source_trace` con los 5 campos: `source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp`. Cuando la información proviene de dos fuentes (SDP + RAG), DEBE incluir traces de ambas.
- FR-011: El `feasibility_score` DEBE extenderse con reglas nuevas: bonus +10 si tratamiento y edificabilidad están disponibles (`r_parametros_urbanisticos`), bonus +5 si estacionamientos están calculados (`r_estacionamientos_calculados`), penalización −15 si tratamiento es "Conservación" sin licencia especial (`r_tratamiento_conservacion`).
- FR-012: El `confidence` del scoring DEBE considerar los 13 bloques evaluables (12 actuales + `urbanistic_parameters`): `high` ≥ 10 disponibles, `medium` 5–9, `low` ≤ 4.
- FR-013: El bloque `urbanistic_parameters` NO DEBE modificar los contratos de las 7 tools existentes ni los bloques de F3/F6/F7.
- FR-014: Las interpretaciones del bloque DEBEN ser textos deterministas generados por reglas sobre los datos reales, sin LLM.
- FR-015: El sistema NO DEBE inferir reglas urbanísticas ausentes en las fuentes; el bloque reporta datos reales de la capa SDP y del RAG normativo.
- FR-016: Cada fuente que no tenga datos DEBE generar un warning deduplicado con código `BLOQUE_SIN_DATO` o `BLOQUE_DEGRADADO` según la causa.
- FR-017: El proveedor SDP DEBE ser un provider nuevo en `app/providers/sdp.py` siguiendo el Principio II de la constitución (modularidad por providers).
- FR-018: La consulta RAG normativo para parámetros urbanísticos DEBE usar la colección consolidada `decreto_555_2021` existente, con un prompt específico que extraiga COS, CUS, altura y retiros del artículo 281 y estacionamientos del artículo 389.
- FR-019: El provider SDP DEBE usar `httpx.AsyncClient` con timeout configurable (default 10s) y manejar errores de red/HTTP de forma consistente con los otros providers.
- FR-020: El bloque `urbanistic_parameters` DEBE incluirse tanto en `get_feasibility_report` como en `get_lot_summary_by_chip` (consistencia con F7).
- FR-021: La capa de rangos de edificabilidad (layer 14) del SINUPOT contiene información complementaria de COS/CUS por tratamiento; cuando está disponible, DEBE usarse para enriquecer los datos del RAG.
- FR-022: El provider SDP DEBE incluir la URL base del servicio como constante configurable (`SDP_BASE_URL`), sin hardcodear en la lógica de consulta.

### Key Entities

- **ParametrosUrbanisticos**: parámetros urbanísticos del lote (tratamiento, COS, CUS, altura, retiros, estacionamientos). Relaciones: datos de la capa SDP/SINUPOT (tratamiento espacial) + RAG normativo (parámetros numéricos).
- **TratamientoUrbanistico**: clasificación del tratamiento urbanístico del lote (denominación, código, fuente espacial). Relaciones: capa SINUPOT layer 2.
- **ParametrosEdificabilidad**: parámetros numéricos de edificabilidad (COS, CUS, altura máxima). Relaciones: RAG normativo art. 281 + Anexo 5.
- **RetirosLote**: retiros obligatorios del lote (frontal, laterales, posteriores). Relaciones: RAG normativo Anexo 5.
- **EstacionamientosRequeridos**: estacionamientos requeridos por el lote (cantidad, criterio de cálculo). Relaciones: RAG normativo art. 389.

---

## Success Criteria

- SC-001: El reporte con el bloque `urbanistic_parameters` se entrega en menos de 15 segundos (10 s F3 + overhead de 1 consulta SDP + 1 consulta RAG) en condiciones normales de red.
- SC-002: El bloque `urbanistic_parameters` incluye los 5 campos de trazabilidad (`source_trace`) en el 100% de los casos.
- SC-003: El `feasibility_score` sigue siendo 100% determinístico: misma entrada → mismo score/confidence/reasons (SC-003 de F3 preservado).
- SC-004: El bloque `urbanistic_parameters` degrada independientemente: la falla de la capa SDP o del RAG no afecta a otros bloques ni a los bloques de F3/F6/F7.
- SC-005: Las 7 tools existentes mantienen su contrato sin cambios (no-regresión F1/F2/F3/F4/F6/F7).
- SC-006: El 100% de las `rules_applied` del scoring son trazables a los bloques evaluados.
- SC-007: El tiempo de respuesta adicional del bloque `urbanistic_parameters` no supera 3 segundos sobre el tiempo base del reporte (consulta SDP < 2s + RAG < 1s).

---

## Assumptions

- El servicio ArcGIS REST del SINUPOT/SDP (`sinu.sdp.gov.co/serverp/rest/services/POT555/NORMA_URBANÍSTICA_Y_OT/MapServer`) está operativo y público (sin autenticación), como fue verificado en la investigación previa.
- La capa layer 2 del SINUPOT contiene los polígonos de tratamiento urbanístico con un campo de denominación (nombre del tratamiento).
- La capa layer 14 del SINUPOT contiene rangos de edificabilidad (COS, CUS) por tratamiento de desarrollo.
- El Decreto 555/2021 está indexado en la colección `decreto_555_2021` del RAG con 608 artículos; los artículos 281, 389 y referencias al Anexo 5 contienen la información de COS/CUS/altura/retiros/estacionamientos.
- El CRS EPSG:4686 (MAGNA-SIRGAS) es el sistema de coordenadas de las capas del SINUPOT.
- No se añaden variables de entorno nuevas; la URL base del SINUPOT se configura como constante en el provider.
- El scoring se extiende sin cambiar la fórmula base de F3; se añaden reglas adicionales sobre el nuevo bloque.
- La consulta al RAG para parámetros urbanísticos reutiliza la infraestructura existente de `consultar_normativa` con un prompt específico, sin crear un nuevo índice.
- El `feasibility_score` es heurístico: nunca inferir reglas urbanísticas ausentes en la fuente (FR-014 de F3 preservado).

---

## Clarifications

No hay aclaraciones pendientes. Todas las decisiones de diseño se basan en la investigación previa del dominio y la arquitectura existente del proyecto.
