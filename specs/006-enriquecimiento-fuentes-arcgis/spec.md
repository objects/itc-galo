# Feature Specification

**Rama del feature**: `006-enriquecimiento-fuentes-arcgis`

**Creado**: 2026-08-17

**Estado**: Draft

**Entrada**: Descripción del usuario: "Feature 6 de mcp-bogota-factibilidad: enriquecer el informe de factibilidad (get_feasibility_report) con 5 nuevos bloques de contexto que consultan 15 servicios ArcGIS REST adicionales del catastro de Bogotá: (1) riesgos geotécnicos desde emergencias/gestionriesgos [2],[5],[7],[8] — amenaza de movimientos en masa, geología rural, respuesta sísmica y zonificación geotécnica; (2) contexto socioeconómico desde estratificación [1], uso predominante [0], altura media [0] y mediana avalúo catastral [0]; (3) entorno regulatorio desde licencias de construcción [3] y plusvalía [1]; (4) patrimonio cultural desde bienes de interés cultural [1] y plan arqueológico [9]; y (5) acceso y movilidad desde transporte público (TransMilenio [1], SITP [5]) y Metro Bogotá [0]. Cada bloque se ejecuta en paralelo, degrada independientemente (FR-012), y sigue el patrón {estado, dato, interpretation, source_trace} de F3. El scoring se extiende con reglas nuevas para los 5 bloques adicionales sin romper el determinismo de F3 (SC-003)."

---

## User Scenarios & Testing (obligatorio)

### User Story 1 (P1) — Riesgos geotécnicos del lote

Como usuario del MCP, quiero que el informe de factibilidad incluya un bloque `geotechnical_risks` con la clasificación geotécnica del lote (amenaza de movimientos en masa, geología rural, respuesta sísmica y zonificación geotécnica) proveniente de 4 capas de emergencias/gestionriesgos, para evaluar si el terreno presenta restricciones geotécnicas para la construcción.

**Por qué esta prioridad**: los riesgos geotécnicos son un factor determinante en la factibilidad de un proyecto de construcción; un terreno con amenaza alta puede ser inviable sin estudios adicionales. Es el bloque con mayor impacto en la decisión de inversión.

**Prueba independiente**: invocar `get_feasibility_report` con un CHIP válido y verificar que `geotechnical_risks` tiene el patrón `{estado, dato, interpretation, source_trace}`, con `nivel_amenaza` en `["alto", "medio", "bajo", "desconocido"]` y los 4 campos de clasificación.

**Escenarios de aceptación**:
1. Dado un lote en zona con amenaza de movimientos en masa, cuando se genera el reporte, entonces `geotechnical_risks.dato.amenaza_movimientos` contiene la clasificación y `nivel_amenaza` refleja el nivel crítico inferido.
2. Dado un lote sin datos geotécnicos disponibles, cuando se genera el reporte, entonces `geotechnical_risks.estado == "no_encontrado"` con `interpretation` que indica la ausencia de datos.
3. Dado que una de las 4 capas geotécnicas falla, cuando se genera el reporte, entonces el bloque se construye con las capas que respondieron y las que fallaron quedan en `None`.
4. Dado un lote con riesgo geotecnico alto, cuando se genera el reporte, entonces `feasibility_score` aplica la penalización correspondiente y `reasons` lo documenta.

### User Story 2 (P2) — Contexto socioeconómico del lote

Como usuario del MCP, quiero que el informe incluya un bloque `socioeconomic_context` con el estrato socioeconómico, uso predominante, altura media de construcción y mediana avalúo catastral del lote, para contextualizar el mercado y las condiciones del entorno inmediato.

**Por qué esta prioridad**: el contexto socioeconómico informa el perfil del usuario final y las condiciones de mercado, complementando al `market_context` (valor de referencia) con datos de estratificación y uso.

**Prueba independiente**: invocar `get_feasibility_report` con un CHIP válido y verificar que `socioeconomic_context` tiene el patrón `{estado, dato, interpretation, source_trace}` con los 4 sub-bloques (estrato, uso, altura, avalúo).

**Escenarios de aceptación**:
1. Dado un lote en estrato 4, cuando se genera el reporte, entonces `socioeconomic_context.dato.estrato == 4`.
2. Dado un lote sin datos socioeconómicos, cuando se genera el reporte, entonces `socioeconomic_context.estado == "no_encontrado"`.
3. Dado que una de las 4 capas socioeconomicas falla, cuando se genera el reporte, entonces las capas que respondieron se reportan y las que fallaron quedan en `None`.

### User Story 3 (P3) — Entorno regulatorio del lote

Como usuario del MCP, quiero que el informe incluya un bloque `regulatory_environment` con las licencias de construcción aprobadas en el entorno del lote y si se encuentra en zona de plusvalía, para entender el contexto de desarrollo inmobiliario y las obligaciones fiscales adicionales.

**Por qué esta prioridad**: las licencias aprobadas indican la actividad de desarrollo inmobiliario en el entorno, y la plusvalía tiene implicaciones fiscales directas para el inversionista.

**Prueba independiente**: invocar `get_feasibility_report` con un CHIP válido y verificar que `regulatory_environment` tiene el patrón `{estado, dato, interpretation, source_trace}` con `licencias_encontradas` y `zona_plusvalia`.

**Escenarios de aceptación**:
1. Dado un lote con licencias aprobadas en el entorno, cuando se genera el reporte, entonces `regulatory_environment.dato.licencias_encontradas` refleja el conteo.
2. Dado un lote en zona de plusvalía, cuando se genera el reporte, entonces `zona_plusvalia == True` y `nombre_plan_plusvalia` contiene el nombre del plan parcial.
3. Dado un lote sin datos regulatorios, cuando se genera el reporte, entonces `regulatory_environment.estado == "no_encontrado"`.

### User Story 4 (P4) — Patrimonio cultural del lote

Como usuario del MCP, quiero que el informe incluya un bloque `cultural_heritage` con la presencia de Bienes de Interés Cultural (BIC) y zonas arqueológicas en el entorno del lote, para evaluar restricciones patrimoniales que afecten el diseño y la viabilidad del proyecto.

**Por qué esta prioridad**: el patrimonio cultural genera restricciones de diseño y normativas de protección que impactan directamente la factibilidad; un BIC cercano puede limitar alturas, materiales y usos.

**Prueba independiente**: invocar `get_feasibility_report` con un CHIP válido y verificar que `cultural_heritage` tiene el patrón `{estado, dato, interpretation, source_trace}` con `bic_cercano` y `zona_arqueologica`.

**Escenarios de aceptación**:
1. Dado un lote con un BIC cercano, cuando se genera el reporte, entonces `cultural_heritage.dato.bic_cercano == True` y `nombre_bic` contiene la denominación.
2. Dado un lote con zona arqueológica, cuando se genera el reporte, entonces `zona_arqueologica == True`.
3. Dado un lote sin patrimonio cultural, cuando se genera el reporte, entonces `cultural_heritage.estado == "no_encontrado"` o los campos booleanos son `null`.

### User Story 5 (P5) — Acceso y movilidad del lote

Como usuario del MCP, quiero que el informe incluya un bloque `transit_access` con la cantidad de estaciones TransMilenio, paraderos SITP y estaciones Metro dentro de radios de influencia (800 m TM/Metro, 500 m SITP), para evaluar la conectividad del lote con el sistema de transporte público.

**Por qué esta prioridad**: la conectividad con transporte público es un factor clave de factibilidad comercial y residencial; un lote bien conectado tiene mayor valor de mercado y demanda.

**Prueba independiente**: invocar `get_feasibility_report` con un CHIP válido y verificar que `transit_access` tiene el patrón `{estado, dato, interpretation, source_trace}` con las 3 métricas de conteo y la estación más cercana.

**Escenarios de aceptación**:
1. Dado un lote con estaciones TransMilenio a 800 m, cuando se genera el reporte, entonces `transit_access.dato.estaciones_transmilenio` refleja el conteo.
2. Dado un lote sin transporte público cercano, cuando se genera el reporte, entonces `transit_access.estado == "no_encontrado"`.
3. Dado un lote con acceso a TransMilenio y Metro, cuando se genera el reporte, entonces `estacion_cercana` contiene el nombre de la estación más cercana.

### Edge Cases
- **Las 5 capas del mismo bloque fallan (5xx)**: el bloque se reporta como `no_encontrado` con warning `BLOQUE_DEGRADADO`; el resto del reporte continúa.
- **Una capa del bloque falla pero las demás responden**: el bloque se construye con las capas disponibles; las que fallaron quedan en `None` dentro del dato.
- **Capa sin features en la zona del lote**: el sub-bloque correspondiente queda en `None`; si ningún sub-bloque tiene datos, el bloque整体 es `no_encontrado`.
- **Lote sin UPL**: los 5 nuevos bloques se consultan igualmente (no dependen de la UPL).
- **Todos los bloques nuevos no encontrados**: el scoring penaliza con −5 por cada bloque ausente pero el reporte se entrega completo.
- **Parámetros de radio (SITP 500 m, TM/Metro 800 m)**: configurados como constantes; no son parámetros del contrato.

---

## Requirements (obligatorio)

### Functional Requirements

- FR-001: El reporte DEBE incluir `geotechnical_risks` con los 4 sub-bloques de emergencias/gestionriesgos (amenaza de movimientos en masa layer [2], geología rural [5], respuesta sísmica [7], zonificación geotécnica [8]), cada uno con su clasificación textual y un `nivel_amenaza` inferido (`"alto"`, `"medio"`, `"bajo"` o `"desconocido"`).
- FR-002: El reporte DEBE incluir `socioeconomic_context` con el estrato socioeconómico (entero), uso predominante (texto), altura media (float) y mediana avalúo catastral (float), consultados desde las capas `estratificacion [1]`, `usopredominante [0]`, `alturamedia [0]` y `medianaavaluocatastral [0]`.
- FR-003: El reporte DEBE incluir `regulatory_environment` con el conteo de licencias de construcción aprobadas (entero), si el lote está en zona de plusvalía (booleano) y el nombre del plan parcial de plusvalía si aplica, consultados desde `licenciasconstruccion [3]` y `plusvalia [1]`.
- FR-004: El reporte DEBE incluir `cultural_heritage` con la presencia de Bienes de Interés Cultural cercanos (booleano + nombre) y zona arqueológica (booleano), consultados desde `bienesinterescultural [1]` y `planarqueologico [9]`.
- FR-005: El reporte DEBE incluir `transit_access` con el conteo de estaciones TransMilenio (radio 800 m), paraderos SITP (radio 500 m) y estaciones Metro (radio 800 m), más el nombre de la estación más cercana, consultados desde `transportepublico [1],[5]` y `metrobogota [0]`.
- FR-006: Los 5 nuevos bloques DEBEN seguir el patrón `{estado, dato, interpretation, source_trace}` de F3, con estado `"disponible"` cuando hay datos y `"no_encontrado"` cuando no.
- FR-007: Los 5 nuevos bloques DEBEN consultarse en paralelo con `asyncio.gather` para no degradar el rendimiento del reporte (SC-001).
- FR-008: Cada sub-bloque que falla (5xx de una capa individual) DEBE degradarse independientemente dentro de su bloque: las capas que respondieron se reportan, las que fallaron quedan en `None`; el bloque整体 mantiene estado `"disponible"` si al menos un sub-bloque tiene datos.
- FR-009: Un 5xx de una capa NO DEBE ser tratado como `"no_encontrado"` a nivel de bloque si otras capas del mismo bloque respondieron exitosamente (FR-008); un 5xx que causa la falla de todas las capas de un bloque resulta en `estado: "no_encontrado"` con warning `BLOQUE_DEGRADADO`.
- FR-010: Cada bloque nuevo DEBE incluir `source_trace` con los 5 campos: `source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp`.
- FR-011: El `feasibility_score` DEBE extenderse con reglas nuevas para los 5 bloques: bonus por contexto socioeconómico disponible (+5), bonus por acceso a movilidad con al menos una estación (+5), penalización por riesgo geotecnico alto (−10), penalización por patrimonio cultural cercano (BIC o zona arqueológica, −10), y penalización por cada bloque no encontrado (−5).
- FR-012: Los 5 bloques adicionales NO DEBEN modificar los contratos de las 7 tools existentes ni los bloques de F3 (CHK-015).
- FR-013: Las interpretaciones de los 5 bloques DEBEN ser textos deterministas generados por reglas sobre los datos reales, sin LLM (FR-007 de F3).
- FR-014: El sistema NO DEBE inferir reglas urbanísticas ausentes en las fuentes; los 5 bloques reportan datos reales de las capas consultadas (FR-014 de F3).
- FR-015: Cada bloque que no tenga datos DEBE generar un warning deduplicado con código `BLOQUE_SIN_DATO` o `BLOQUE_DEGRADADO` según la causa.
- FR-016: Las consultas de radio (TransMilenio 800 m, SITP 500 m, Metro 800 m) DEBEN usar `distance=<radio_m>&units=esriSRUnit_Meter` sobre el centroide del lote.
- FR-017: La capa `estratificacion` usa el sistema de coordenadas `PCS_CarMAGBOG`; la consulta DEBE convertir las coordenadas del lote (WGS84) al SR de la capa usando `inSR=4326&outSR` apropiado.
- FR-018: La capa `planarqueologico` usa el SR `102233`; la consulta DEBE manejar la conversión de SR correctamente.
- FR-019: El `confidence` del scoring DEBE considerar los 11 bloques evaluables (6 originales F3 + 5 nuevos F6): `high` ≥ 9 disponibles, `medium` 5–8, `low` ≤ 4.
- FR-020: El `rules_applied` del scoring DEBE incluir los códigos de las reglas nuevas: `r_contexto_socio`, `r_acceso_movilidad`, `r_riesgo_geotec_alto`, `r_patrimonio_cultural`.

### Key Entities

- **RiesgoGeotecnicos**: clasificación geotécnica del lote (4 sub-bloques + nivel de amenaza inferido). Relaciones: datos de 4 capas de emergencias/gestionriesgos.
- **ContextoSocioeconomico**: contexto socioeconómico del lote (estrato, uso, altura, avalúo). Relaciones: datos de 4 capas de catastro/estratificación.
- **EntornoRegulatorio**: entorno regulatorio del lote (licencias, plusvalía). Relaciones: datos de 2 capas de ordenamiento territorial.
- **PatrimonioCultural**: patrimonio cultural del lote (BIC, arqueología). Relaciones: datos de 2 capas de recreación/deporte.
- **AccesoMovilidad**: acceso a transporte público (TransMilenio, SITP, Metro). Relaciones: datos de 3 capas de movilidad.

---

## Success Criteria

- SC-001: El reporte con los 5 bloques adicionales se entrega en menos de 15 segundos (10 s F3 + overhead paralelo de 5 consultas adicionales) en condiciones normales de red.
- SC-002: Los 5 nuevos bloques incluyen los 5 campos de trazabilidad (`source_trace`) en el 100% de los casos.
- SC-003: El `feasibility_score` sigue siendo 100% determinístico: misma entrada → mismo score/confidence/reasons (SC-003 de F3 preservado).
- SC-004: Los 5 bloques adicionales degradan independientemente: la falla de un bloque no afecta a los demás ni a los bloques de F3.
- SC-005: Las 7 tools existentes mantienen su contrato sin cambios (no-regresión F1/F2/F3/F4/F5).
- SC-006: El 100% de las `rules_applied` del scoring son trazables a los bloques evaluados.

---

## Assumptions

- Los 15 servicios ArcGIS REST de las 5 categorías están operativos y públicos (sin autenticación).
- Las capas de `emergencias/gestionriesgos` usan SR 102100; `estratificacion` usa `PCS_CarMAGBOG`; `usopredominante`, `alturamedia` y `medianaavaluo` usan SR 4326; `licenciasconstruccion` y `plusvalia` usan `PCS_CarMAGBOG`; `bienesinterescultural` usa SR 102100; `planarqueologico` usa SR 102233; `transportepublico` usa SR 102100; `metrobogota` usa SR 102100.
- La inversión de coordenadas (lon/lat → lat/lon) depende del SR de la capa: con `inSR=4326` se usa `(lng, lat)`; con SR proyectado se requiere conversión previa.
- Las capas de `estratificacion`, `licenciasconstruccion` y `plusvalia` (`PCS_CarMAGBOG`) admiten consulta con `inSR=4326` (ArcGIS REST realiza la conversión internamente).
- Los radios de influencia (800 m TM/Metro, 500 m SITP) son configurables como constantes pero no como parámetros del contrato.
- No se añaden dependencias nuevas ni variables de entorno nuevas.
- El scoring se extiende sin cambiar la fórmula base de F3; se añaden reglas adicionales sobre los nuevos bloques.

---

## Clarifications

No hay aclaraciones pendientes. Todas las decisiones de diseño se basan en la implementación completa que ya existe en el working tree.
