# Feature Specification

**Rama del feature**: `003-informe-factibilidad`

**Creado**: 2026-08-12

**Estado**: Draft

**Entrada**: Descripción del usuario: "Feature 3 de mcp-bogota-factibilidad: emitir el informe de factibilidad de un lote catastral de Bogotá mediante la orquestación unificada (lote → UPL → contexto temático → evidencia normativa → scoring heurístico) en una sola tool MCP (`get_feasibility_report`). El objetivo del MCP es llegar con la información necesaria para iniciar el informe de factibilidad: identidad del lote, contexto administrativo (UPL y localidad), restricciones (reserva vial), mercado (valor de referencia), entorno (obras públicas), contexto económico (destino económico consultado en la fuente catastral de Mapas Bogotá), evidencia normativa del POT con citas literales y un `feasibility_score` heurístico determinístico con razones trazables. El reporte es 100% determinístico (sin LLM): el score y las interpretaciones de cada bloque se calculan con reglas transparentes sobre los datos recuperados; la evidencia normativa se alimenta de una consulta opcional del usuario o, si se omite, de una consulta automática construida desde el contexto del lote (UPL, localidad, clasificación de suelo). Fuera de alcance: el diagnóstico de prefactibilidad con reglas de negocio urbanístico (mejora futura) y las interpretaciones redactadas por LLM."

Decisiones de clarificación (2026-08-12):
1. **Bloques del reporte**: el destino económico se incluye como bloque `economic_context`, consultado desde la fuente catastral viva de Mapas Bogotá (es información catastral consultable allí), no desde la capa `catastro/destinolt` de ArcGIS que está caída (500 en vivo).
2. **Scoring e interpretaciones**: 100% determinístico, sin LLM. El `feasibility_score` (0-100, confidence, reasons) y las `interpretation` de cada bloque se calculan con reglas determinísticas transparentes sobre los datos recuperados; la feature funciona sin Ollama.
3. **Evidencia normativa**: la tool acepta un parámetro opcional `consulta` (tema en lenguaje natural); si se omite, la consulta se construye automáticamente desde el contexto del lote (UPL, localidad, clasificación de suelo — `topic_hints` del brief).

---

## User Scenarios & Testing (obligatorio)

### User Story 1 (P1) — Obtener el informe de factibilidad estructural de un lote

Como usuario del MCP, quiero consultar el informe de factibilidad de un lote (por CHIP, dirección o coordenadas) en una sola llamada, para obtener en un único reporte la identidad del lote, su contexto administrativo (UPL y localidad), las restricciones (reserva vial), el contexto de mercado (valor de referencia), el contexto de entorno (obras públicas), el contexto económico (destino económico catastral) y un scoring preliminar de factibilidad con sus razones, todo sin depender de un LLM.

**Por qué esta prioridad**: es el núcleo de la feature — la orquestación unificada que el brief (línea 1179) define como "feasibility_report estructurado con identidad del lote, contexto administrativo, restricciones, mercado, entorno, evidencia normativa y un scoring preliminar de factibilidad". Sin este bloque no hay feature 3.

**Prueba independiente**: invocar `get_feasibility_report` con un CHIP válido y verificar que el reporte devuelve los bloques `lot_identity`, `administrative_context`, `planning_constraints`, `market_context`, `environment_context`, `economic_context`, `normative_evidence`, `feasibility_score`, `warnings` y `query_timestamp`, con cada bloque de datos trazado a su fuente (5 campos de trazabilidad).

**Escenarios de aceptación**:
1. Dado un CHIP válido de 11 caracteres alfanuméricos, cuando se invoca `get_feasibility_report` con `chip`, entonces se devuelve un reporte con `lot_identity` (identidad del lote), `administrative_context` (UPL + localidad), `planning_constraints`, `market_context`, `environment_context`, `economic_context`, `feasibility_score` con `score` (0-100), `confidence` y `reasons`, `warnings` y `query_timestamp`.
2. Dado un lote sin CHIP, cuando se invoca `get_feasibility_report` con `coordenadas`, entonces el reporte incluye `lot_identity` con `chip: null` y el resto de bloques se resuelven igualmente.
3. Dado un lote cuya UPL no se encuentra, cuando se genera el reporte, entonces `administrative_context.upl` es `null`, el bloque normativo automático no puede filtrar por UPL y se registra una advertencia explícita en `warnings`.
4. Dado un lote con datos de contexto temático incompletos (alguna capa sin resultado), cuando se genera el reporte, entonces el bloque afectado se reporta con estado `no_encontrado` y NO se inventa información: `planning_constraints.reserva_vial_hits` refleja solo datos reales de la fuente.
5. Dado un reporte generado sin infraestructura RAG disponible (sin Ollama o sin corpus), cuando se solicita, entonces el bloque `normative_evidence` se entrega vacío y `warnings` explica la causa (`CORPUS_NO_INGESTADO` o `OLLAMA_NO_DISPONIBLE`), sin fallar el resto del reporte.

### User Story 2 (P2) — Enriquecer el informe con evidencia normativa del POT

Como usuario del MCP, quiero que el informe incluya evidencia normativa del POT (Decreto 555 de 2021) con citas literales trazables, alimentada por una consulta automática construida desde el contexto del lote o por una consulta opcional que yo proporcione, para sustentar el inicio del informe de factibilidad con la norma aplicable al territorio del lote.

**Por qué esta prioridad**: el brief (línea 1120) define la convergencia: el MCP geoespacial entrega `upl_code` y `topic_hints`, y el RAG normativo produce la evidencia normativa trazable al Decreto 555 y al territorio aplicable. Es el diferencial del producto, pero depende de la infraestructura RAG y por eso es P2.

**Prueba independiente**: invocar `get_feasibility_report` sin `consulta` sobre un lote con UPL conocida y verificar que `normative_evidence` contiene artículos con cita literal (número de artículo, título y texto) coherentes con el territorio; invocarla con `consulta` explícita y verificar que los resultados responden al tema solicitado.

**Escenarios de aceptación**:
1. Dado un lote con UPL resuelta, cuando se invoca `get_feasibility_report` sin `consulta`, entonces se construye automáticamente una consulta a partir del contexto del lote (UPL, localidad, clasificación de suelo / topic_hints) y `normative_evidence` devuelve chunks con cita literal (número de artículo, título y texto) y su trazabilidad al corpus.
2. Dado un usuario que proporciona `consulta` (tema en lenguaje natural), cuando se invoca `get_feasibility_report`, entonces `normative_evidence` responde al tema solicitado con citas literales.
3. Dado un lote en una UPL rural (p. ej. Sumapáz), cuando se genera la consulta automática, entonces los resultados se filtran estrictamente por las partes del Decreto 555 aplicables al suelo rural, según los metadatos del corpus (semántica de filtro territorial de la feature 2).
4. Dado que la consulta (automática o del usuario) no produce resultados relevantes, cuando se genera el reporte, entonces `normative_evidence` se entrega vacío con una advertencia explícita, sin inventar artículos ni inferir reglas ausentes.

### User Story 3 (P3) — Conocer el alcance del scoring y sus límites

Como usuario del MCP, quiero que el `feasibility_score` sea heurístico, determinístico y transparente — con `confidence` y `reasons` trazables a los datos reales — para entender qué tan preliminar es la evaluación y no confundirla con un diagnóstico urbanístico formal.

**Por qué esta prioridad**: AGENTS.md exige que "el feasibility_score es heurístico: el LLM no debe inferir reglas urbanísticas ausentes en la fuente" y el brief (línea 1214) deja la integración de reglas de negocio urbanístico como mejora futura. Es la salvaguarda de honestidad del producto, por eso se prioriza sobre detalles de presentación.

**Prueba independiente**: invocar `get_feasibility_report` dos veces con los mismos datos y verificar que el score, confidence y reasons son idénticos (determinismo); verificar que ninguna razón cita reglas urbanísticas que no provienen de las fuentes consultadas.

**Escenarios de aceptación**:
1. Dado el mismo lote consultado dos veces, cuando se genera el reporte, entonces `feasibility_score.score`, `confidence` y `reasons` son idénticos (resultado 100% determinístico, sin LLM).
2. Dado un lote con escasos datos (p. ej., sin UPL y sin temáticas), cuando se genera el reporte, entonces `confidence` es baja y `reasons` enumeran explícitamente qué datos faltan.
3. Dado un lote afectado por reserva vial, cuando se genera el reporte, entonces `planning_constraints.interpretation` y las `reasons` del score lo reflejan de forma determinística (texto por reglas) y trazable a la capa de reserva vial.
4. Dado cualquier lote, cuando se genera el reporte, entonces el sistema NO DEBE citar en `reasons` ni en `interpretation` reglas urbanísticas que no estén respaldadas por las fuentes consultadas (límite heurístico documentado).

### Edge Cases
- **Lote sin UPL**: `administrative_context.upl` en `null`, advertencia en `warnings`, consulta normativa automática sin filtro territorial.
- **Punto fuera del área de cobertura (fuera de Bogotá)**: error tipificado `FUERA_DE_COBERTURA`, sin reporte parcial.
- **Lote sin CHIP (resuelto por coordenadas)**: `lot_identity.chip` en `null`; el resto de bloques se resuelven igual.
- **Dirección ambigua con múltiples candidatos**: se respeta la semántica de F1 (lista de candidatos para que el usuario desambigüe); el reporte no se genera con ambigüedad.
- **Dirección no localizable**: error tipificado `DIRECCION_NO_LOCALIZADA` (semántica F1).
- **Capa temática sin dato**: bloque con estado `no_encontrado` (nunca un cero fingido ni dato inventado).
- **Infraestructura RAG no disponible (corpus no ingestado u Ollama caído)**: `normative_evidence` vacío + advertencia con la causa; el resto del reporte se entrega completo.
- **Consulta normativa sin resultados relevantes**: `normative_evidence` vacío + advertencia, sin inventar artículos.
- **`MAPAS_BOGOTA_APIKEY` ausente con resolución por dirección**: error tipificado `CREDENCIAL_FALTANTE` (semántica F1: la llave solo aplica a la geocodificación); la resolución por CHIP o por coordenadas y el contexto económico no requieren la llave.
- **CHIP inválido / coordenadas fuera de rango**: error tipificado `PARAMETROS_INVALIDOS` (validación idéntica a F1).
- **Múltiples criterios de búsqueda a la vez (chip + coordenadas)**: error tipificado `PARAMETROS_INVALIDOS` (exactamente un criterio, como en `get_upl`).
- **Lote sin localidad derivable**: `administrative_context.locality` en `null` + advertencia.

---

## Requirements (obligatorio)

### Functional Requirements

- FR-001: La tool MCP `get_feasibility_report` DEBE aceptar exactamente un criterio de identificación entre `chip`, `direccion` y `coordenadas`, y DEBE emitir el reporte de factibilidad estructurado en una sola llamada.
- FR-002: El reporte DEBE incluir `lot_identity` con la identidad del lote (CHIP si existe, código catastral, manzana, dirección normalizada si existe, barrio si existe, geometría, centroide y trazabilidad).
- FR-003: El reporte DEBE incluir `administrative_context` con la UPL del lote (reutilizando la resolución de UPL de la feature 2) y la localidad derivada; si la UPL no se encuentra, DEBE entregar `upl: null` con advertencia explícita, NO fallar el reporte.
- FR-004: El reporte DEBE incluir los bloques temáticos `planning_constraints` (reserva vial), `market_context` (valor de referencia) y `environment_context` (obras públicas en un radio de 500 m alrededor del lote, criterio del brief), cada uno con su estado (`disponible`/`no_encontrado`), sus datos y su interpretación determinística por reglas.
- FR-005: El reporte DEBE incluir `economic_context` con el destino económico del lote consultado desde la fuente catastral de Mapas Bogotá (no desde la capa `catastro/destinolt` de ArcGIS, que está fuera de servicio); si el destino económico no está disponible, el bloque DEBE reportarse con estado `no_encontrado`.
- FR-006: El `feasibility_score` DEBE ser un valor 0-100 calculado por reglas determinísticas y transparentes sobre los datos recuperados, con `confidence` (valores canónicos del contrato: `"high"`, `"medium"`, `"low"`) y `reasons` (lista de razones trazables a los datos).
- FR-007: El sistema NO DEBE usar LLM para calcular el score ni para redactar las interpretaciones de los bloques; las interpretaciones DEBEN ser textos fijos generados por reglas (la feature DEBE funcionar sin Ollama).
- FR-008: El reporte DEBE incluir `normative_evidence` con evidencia normativa del POT (Decreto 555 de 2021): chunks recuperados con cita literal (número de artículo, título y texto), metadatos del corpus y trazabilidad; la consulta DEBE ser el parámetro opcional `consulta` si el usuario la provee, o una consulta automática construida desde el contexto del lote (UPL, localidad, clasificación de suelo) si se omite.
- FR-009: Si la infraestructura RAG no está disponible (corpus no ingestado u Ollama no disponible) o la consulta no produce resultados relevantes, el sistema NO DEBE fallar el reporte: DEBE entregar `normative_evidence` vacío con una advertencia explícita de la causa en `warnings`.
- FR-010: Cada bloque de datos del reporte DEBE incluir su trazabilidad de fuente con los 5 campos: `source_name`, `layer_id`, `service_url`, `data_vigencia` y `query_timestamp`; el sistema NO DEBE mezclar capas de vigencias distintas como una sola fotografía temporal.
- FR-011: El reporte DEBE incluir `warnings` (lista) y `query_timestamp`; `warnings` DEBE listar al menos: lote sin CHIP, UPL ausente, temáticas sin dato, evidencia normativa no disponible y cualquier degradación parcial.
- FR-012: La tool DEBE reutilizar la semántica de errores tipificados de las features 1 y 2 para los fallos que son fatales en el reporte: `PARAMETROS_INVALIDOS`, `LOTE_NO_ENCONTRADO`, `FUERA_DE_COBERTURA`, `DIRECCION_NO_LOCALIZADA`, `CREDENCIAL_FALTANTE` y `FUENTE_5XX`. El sistema NO DEBE emitir `LOTE_SIN_UPL`, `CORPUS_NO_INGESTADO` ni `OLLAMA_NO_DISPONIBLE` como errores del reporte: la ausencia de UPL se representa como `upl: null` con advertencia, y la indisponibilidad de la infraestructura RAG se representa como `normative_evidence` vacío con la causa registrada en `warnings` (a diferencia de las features 1 y 2, donde esos códigos son errores fatales de su tool específica). El dato no encontrado por fuente se modela a nivel de bloque con estado `no_encontrado`, no como error (`DATO_NO_ENCONTRADO_POR_FUENTE` no aplica en F3).
- FR-013: La validación de parámetros DEBE ser idéntica a la de F1: CHIP de 11 caracteres alfanuméricos, coordenadas con latitud en [-90, 90] y longitud en [-180, 180], y exactamente un criterio de búsqueda; el incumplimiento DEBE devolver `PARAMETROS_INVALIDOS`.
- FR-014: El sistema NO DEBE inferir ni citar reglas urbanísticas ausentes en las fuentes; el `feasibility_score` es heurístico y su naturaleza preliminar DEBE ser evidente en `confidence` y `reasons` (límite documentado; el diagnóstico de prefactibilidad con reglas de negocio urbanístico es mejora futura, fuera de alcance).

### Key Entities

- **InformeFactibilidad (feasibility_report)**: entidad raíz del contrato. Atributos: `lot_identity`, `administrative_context`, `planning_constraints`, `market_context`, `environment_context`, `economic_context`, `normative_evidence`, `feasibility_score`, `warnings`, `query_timestamp`. Relaciones: agrega un Lote; agrega una UPL (o null); agrega bloques de contexto temático; agrega evidencia normativa; agrega un score heurístico.
- **IdentidadLote (lot_identity)**: CHIP (null si se resuelve por coordenadas), código catastral, manzana, dirección normalizada (null si no aplica), barrio (null si no aplica), geometría, centroide, trazabilidad. Relaciones: referencia al Lote de F1.
- **ContextoAdministrativo (administrative_context)**: UPL (o null) con sus atributos (código, nombre, localidad derivada, acto administrativo, vocación, normativa, área, estado) y localidad (o null); trazabilidad. Relaciones: referencia a la UPL de F2.
- **BloqueTematico**: patrón de los bloques `planning_constraints`, `market_context`, `environment_context` y `economic_context`. Atributos: estado (`disponible`/`no_encontrado`), datos del bloque (hits y detalle según tipo), `interpretation` (texto fijo por reglas), trazabilidad. Relaciones: deriva de `DatoTematico`/`ContextoTematico` de F1 y del destino económico catastral de Mapas Bogotá.
- **EvidenciaNormativa (normative_evidence)**: lista de chunks recuperados con cita literal (número de artículo, título, texto), metadatos (libro, parte, sección, UPLs mencionadas), similitud y trazabilidad. Relaciones: referencia a `Chunk`/`ArticuloNormativo` de F2.
- **PuntajeFactibilidad (feasibility_score)**: `score` (0-100, entero), `confidence` (`"high"`/`"medium"`/`"low"`), `reasons` (lista de razones trazables). Relaciones: calculado por reglas determinísticas sobre IdentidadLote, ContextoAdministrativo y BloquesTematicos; nunca por LLM.

---

## Success Criteria

- SC-001: `get_feasibility_report` con un criterio de búsqueda válido devuelve el reporte estructural completo (bloques FR-002 a FR-006, FR-008, FR-010, FR-011) en menos de 10 segundos sin normativa y en menos de 20 segundos con evidencia normativa, en condiciones normales de red.
- SC-002: El 100% de los bloques de datos del reporte incluyen los 5 campos de trazabilidad de fuente.
- SC-003: El 100% de los `reasons` del `feasibility_score` son trazables a datos reales de las fuentes y el score es idéntico ante consultas repetidas (determinismo 100%).
- SC-004: El 100% de los ítems de `normative_evidence` incluyen cita literal verificable (número de artículo y texto) recuperada del corpus indexado.
- SC-005: El reporte se entrega completo sin Ollama: la única degradación permitida es `normative_evidence` vacío con su advertencia explícita.
- SC-006: El 100% de los escenarios de error tipificados (FR-012, FR-013) devuelven el código de error correcto sin reporte parcial no advertido.

---

## Assumptions

- El destino económico de un lote es información catastral consultable en la fuente viva de Mapas Bogotá y su disponibilidad se valida durante la fase de planificación (research) de esta feature; si la fuente no lo expusiera, el bloque `economic_context` se entrega con estado `no_encontrado` y advertencia.
- Las capas temáticas de ArcGIS actualmente operativas (`catastro/valorreferencia`, `ordenamientoterritorial/reservavial`, `gestionpublica/obraspublicas`) permanecen disponibles; la capa `catastro/destinolt` sigue fuera de servicio y NO es fuente de esta feature.
- El corpus del Decreto 555 de 2021 está indexado (o puede indexarse con `python -m app.ingesta.corpus`) y Ollama está disponible cuando se requiere evidencia normativa; la feature degrada con advertencia si no lo están.
- La clasificación de suelo para la consulta normativa automática se deriva de la UPL o de los metadatos del corpus, según se valide en la fase de planificación; si no está disponible, la consulta automática se construye con UPL y localidad.
- El `feasibility_score` es heurístico por definición; la integración de reglas de negocio urbanístico (diagnóstico de prefactibilidad formal) es mejora futura y está fuera de alcance.
- El reporte es 100% determinístico: ni el score ni las interpretaciones usan LLM.
- Se respeta la semántica de errores y validaciones de F1 y F2 (sin cambios retroactivos a las features 1 y 2).

---

## Clarifications

**2026-08-12 — Q1: ¿Qué bloques debe incluir el reporte y cómo tratar el destino económico?**
A: (respuesta del usuario, textual) "El destino economico de un lote es información catastral que puede ser consultado en mapas bogota, el objeto del MCP es llegar con la información necesaria para iniciar el informe de factivilidad". → El bloque `economic_context` se incluye y el destino económico se consulta desde la fuente catastral de Mapas Bogotá (no desde la capa caída `destinolt` de ArcGIS).

**2026-08-12 — Q2: ¿Cómo calcular el score y las interpretaciones?**
A: "100% determinístico, sin LLM". → `feasibility_score` (0-100, confidence, reasons) por reglas determinísticas transparentes; interpretaciones por reglas (textos fijos); la feature funciona sin Ollama.

**2026-08-12 — Q3: ¿Cómo alimentar la evidencia normativa?**
A: "Consulta opcional + automática". → `get_feasibility_report` acepta parámetro opcional `consulta`; si se omite, la consulta se construye automáticamente desde el contexto del lote (UPL, localidad, clasificación de suelo — topic_hints del brief).
