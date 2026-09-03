# Feature Specification: Motor de Mercado

**Rama del feature**: `010-motor-mercado`

**Creado**: 2026-09-03

**Estado**: Draft

**Entrada**: Descripción del usuario: "Motor de Mercado para prefactibilidad inmobiliaria en Bogotá (F10): añade el bloque `market_context` al informe de factibilidad con precio por m² de referencia, estrato, oferta competidora (clustering) y ritmos de absorción. Los datos se obtienen por scraping de portales inmobiliarios (Finca Raíz, Metrocuadrado, constructoras) con un corpus local de seeds deterministas como respaldo ante fallos de red o restricciones ToS. Incluye un subcomando CLI `python -m app.ingesta.corpus mercado` para actualizar el corpus de mercado. Las 7 tools MCP permanecen sin cambios."

---

## User Scenarios & Testing (obligatorio)

### User Story 1 (P1) — Contexto de mercado del lote

Como usuario del servidor MCP, quiero que al consultar la factibilidad de un lote se incluya el contexto de mercado (precio por m² de referencia, estrato, oferta competidora y ritmos de absorción de la zona) para evaluar la viabilidad comercial del proyecto.

**Por qué esta prioridad**: el mercado es uno de los 4 pilares de prefactibilidad (Legal/Normativo, Mercado, Técnico/Diseño, Financiero). Sin datos de mercado, el análisis financiero carece de sustento: el precio por m² y el ritmo de absorción determinan los ingresos y la velocidad de venta del proyecto. Es el único de los 4 motores del MVP aún no implementado.

**Prueba independiente**: invocar `get_feasibility_report` con un CHIP válido y verificar que `market_context` tiene el patrón `{estado, dato, interpretation, source_trace}` con los campos `precio_m2_referencia`, `estrato`, `oferta_competidora` y `ritmo_absorcion`.

**Escenarios de aceptación**:
1. Dado un lote con datos de mercado disponibles en el corpus, cuando se genera el reporte, entonces `market_context.dato.precio_m2_referencia` contiene el precio por m² de referencia de la zona.
2. Dado un lote con estrato identificable, cuando se genera el reporte, entonces `market_context.dato.estrato` contiene el estrato (1 a 6) de la zona.
3. Dado un lote con ofertas comparables en el corpus, cuando se genera el reporte, entonces `market_context.dato.oferta_competidora` contiene los clústeres de oferta con conteo y precio promedio.
4. Dado un lote con datos de absorción disponibles, cuando se genera el reporte, entonces `market_context.dato.ritmo_absorcion` contiene unidades/mes y el criterio de cálculo.
5. Dado un lote sin datos de mercado, cuando se genera el reporte, entonces `market_context.estado == "no_encontrado"` con `interpretation` que indica la ausencia.
6. Dado que el corpus de mercado está vacío o corrupto, cuando se genera el reporte, entonces `market_context` se degrada con warning sin afectar otros bloques.

### User Story 2 (P2) — Ingesta de mercado (scraping + seeds deterministas)

Como operador del sistema, quiero poblar el corpus de mercado con datos de portales inmobiliarios (Finca Raíz, Metrocuadrado, constructoras) y con un conjunto de seeds deterministas de respaldo, para que el bloque `market_context` tenga datos reales y reproducibles.

**Por qué esta prioridad**: sin un corpus poblado, el bloque de mercado (US1) siempre se degrada. La ingesta híbrida (scraping real + seeds deterministas) garantiza que el bloque funcione tanto con red como sin ella.

**Prueba independiente**: ejecutar la ingesta de mercado y verificar que el corpus local contiene registros de oferta con los campos tabulados (precio, m², estrato, área, amenidades, fuente, fecha); y que sin red, los seeds deterministas producen el mismo corpus.

**Escenarios de aceptación**:
1. Dado acceso a un portal inmobiliario, cuando se ejecuta la ingesta, entonces se extraen registros de oferta con precio, área y estrato tabulados.
2. Dado fallo de red o restricción ToS en el scraping, cuando se ejecuta la ingesta, entonces se usan los seeds deterministas y el corpus queda poblado.
3. Dado un registro sin precio o sin área, cuando se procesa, entonces se descarta o se marca como incompleto (no contamina el precio de referencia).
4. Dado un registro con datos inconsistentes (precio/área fuera de rango), cuando se procesa, entonces se valida y se descarta con warning deduplicado.

### User Story 3 (P3) — Subcomando CLI de mercado

Como operador del sistema, quiero un subcomando CLI `python -m app.ingesta.corpus mercado` para actualizar y consultar el corpus de mercado de forma explícita, siguiendo el patrón de ingesta existente (`descargar`, `indexar`, `acto`).

**Por qué esta prioridad**: la ingesta de mercado es una operación de mantenimiento explícita (no automática), como el resto del pipeline de ingesta del proyecto. El CLI permite regenerar el corpus sin tocar el código.

**Prueba independiente**: ejecutar `python -m app.ingesta.corpus mercado` y verificar que el corpus se actualiza y se persiste con su huella (hash), de forma análoga a `descargar`/`acto`.

**Escenarios de aceptación**:
1. Dado el subcomando `mercado`, cuando se ejecuta, entonces actualiza el corpus de mercado y persiste su huella de integridad.
2. Dado el subcomando `mercado` sin red y con seeds, cuando se ejecuta, entonces genera el corpus determinista de respaldo.
3. Dado un corpus previo, cuando se re-ejecuta la ingesta, entonces los registros se deduplican por identificador (no duplicados).

### Edge Cases

- **Scraping falla (red/5xx)**: la ingesta cae a seeds deterministas; el corpus queda poblado y el bloque no se degrada por ello.
- **Restricción ToS del portal**: el scraping respeta robots.txt y límites; ante bloqueo, usa seeds.
- **Corpus vacío**: el bloque `market_context` se reporta como `no_encontrado` con warning `BLOQUE_SIN_DATO`.
- **Corpus corrupto o con esquema legado**: la ingesta detecta el esquema y reconstruye; el bloque degrada con warning si el esquema no es legible.
- **Lote sin estrato derivable**: el bloque reporta `estrato: null` con interpretation que indica que no pudo derivarse.
- **Ofertas con precio/área inconsistentes**: se validan rangos (estrato 1-6, área mínima 36 m²) y se descartan con warning deduplicado.
- **Degradación independiente**: la falla del corpus de mercado no afecta a otros bloques ni a los de F3/F6/F7/F8/F9.
- **Determinismo**: mismo corpus + mismo lote → mismo bloque y mismo score (sin LLM, sin reloj).

---

## Requirements (obligatorio)

### Functional Requirements

- FR-001: El reporte DEBE incluir un bloque `market_context` con los campos: `precio_m2_referencia` (float o null), `estrato` (int 1-6 o null), `oferta_competidora` (lista de clústeres con `zona`, `conteo`, `precio_m2_promedio` o null), `ritmo_absorcion` (objeto con `unidades_mes` y `criterio` o null).
- FR-002: El bloque `market_context` DEBE seguir el patrón `{estado, dato, interpretation, source_trace}` de F3/F6/F7/F8.
- FR-003: El bloque DEBE degradarse independientemente: si el corpus de mercado está vacío o es ilegible, el bloque se reporta como `no_encontrado` con warning `BLOQUE_SIN_DATO`; un fallo de scraping nunca es fatal para el informe.
- FR-004: Los datos de mercado DEBEN provenir de un corpus local versionado (fuente de verdad), poblado por scraping de portales inmobiliarios (Finca Raíz, Metrocuadrado, portales de constructoras) y por seeds deterministas de respaldo.
- FR-005: Los seeds deterministas DEBEN producir el mismo corpus ante la misma entrada (sin red, sin reloj), garantizando reproducibilidad y permitiendo tests sin red real.
- FR-006: La ingesta DEBE deduplicar registros por identificador estable (URL o clave normalizada) y validar rangos (estrato 1-6, área ≥ 36 m², precio/área positivos).
- FR-007: La ingesta DEBE respetar robots.txt y límites de cortesía de los portales; ante restricción ToS o bloqueo, DEBE caer a seeds deterministas sin fallar.
- FR-008: El subcomando CLI `python -m app.ingesta.corpus mercado` DEBE actualizar el corpus de mercado y persistir su huella de integridad (hash), análogo a `descargar`/`acto`.
- FR-009: El provider de mercado DEBE ser un provider nuevo en `app/providers/mercado.py` siguiendo el Principio II de la constitución (modularidad por providers).
- FR-010: El bloque DEBE incluir `source_trace` con los 5 campos: `source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp`. La fuente primaria es el corpus de mercado; la proveniencia por registro (portal origen) queda en `interpretation`/`dato`, no como trazas fabricadas.
- FR-011: El `feasibility_score` DEBE extenderse con reglas nuevas: bonus +10 si hay precio de referencia y estrato disponibles (`r_contexto_mercado`), bonus +5 si hay oferta competidora (`r_oferta_competidora`), bonus +5 si hay ritmo de absorción (`r_absorcion_mercado`).
- FR-012: El `confidence` del scoring DEBE considerar el bloque `market_context` como un bloque evaluable adicional; los umbrales absolutos se mantienen sin cambios (high ≥10, medium 5-9, low ≤4).
- FR-013: El bloque `market_context` NO DEBE modificar los contratos de las 7 tools existentes ni los bloques de F3/F6/F7/F8/F9.
- FR-014: Las interpretaciones del bloque DEBEN ser textos deterministas generados por reglas sobre los datos reales, sin LLM.
- FR-015: El sistema NO DEBE inferir datos de mercado ausentes en el corpus; el bloque reporta solo datos reales (precio de referencia, estrato, oferta, absorción) del corpus.
- FR-016: Cada fuente o registro sin datos DEBE generar un warning deduplicado con código `BLOQUE_SIN_DATO` o `BLOQUE_DEGRADADO` según la causa.
- FR-017: El provider de mercado DEBE usar `httpx.AsyncClient` con timeout configurable (default 10s) para el scraping, y manejar errores de red/HTTP de forma consistente con los otros providers.
- FR-018: La URL base de los portales y el directorio del corpus DEBEN ser constantes configurables, sin hardcodear en la lógica de consulta.
- FR-019: El bloque `market_context` DEBE incluirse tanto en `get_feasibility_report` como en `get_lot_summary_by_chip` (consistencia con F7/F8).
- FR-020: El corpus de mercado DEBE residir en `data/corpus/mercado/` (JSONL + huella) y versionarse en git como fuente de verdad (patrón FR-009/FR-013 de F4).

### Key Entities

- **RegistroOfertaInmobiliaria**: una oferta individual de un portal (precio, área, estrato, amenidades, fuente, fecha de captura). Relaciones: agrupado en clústeres por zona/estrato.
- **ContextoMercado**: bloque resultante del informe (precio por m² de referencia, estrato, oferta competidora, ritmo de absorción). Relaciones: derivado del corpus de mercado filtrado por la zona del lote.
- **OfertaCompetidora**: clúster de ofertas comparables (zona, conteo, precio por m² promedio). Relaciones: agrupación de RegistroOfertaInmobiliaria.
- **RitmoAbsorcion**: velocidad de venta de la zona (unidades/mes, criterio de cálculo). Relaciones: derivado de la oferta histórica de la zona.

---

## Success Criteria

- SC-001: El `feasibility_score` sigue siendo 100% determinístico: misma entrada (corpus + lote) → mismo score/confidence/reasons (SC-003 de F3 preservado).
- SC-002: El bloque `market_context` incluye los 5 campos de trazabilidad (`source_trace`) en el 100% de los casos.
- SC-003: El bloque `market_context` degrada independientemente: la ausencia o falla del corpus no afecta a otros bloques ni a los de F3/F6/F7/F8/F9.
- SC-004: Las 7 tools existentes mantienen su contrato sin cambios (no-regresión F1-F9).
- SC-005: Los seeds deterministas reproducen el mismo corpus ante la misma entrada, permitiendo tests sin red real ni Ollama.
- SC-006: El tiempo de respuesta adicional del bloque `market_context` no supera 3 segundos sobre el tiempo base del reporte (consulta local al corpus, sin red en el camino principal).
- SC-007: El 100% de las `rules_applied` nuevas del scoring son trazables a los bloques evaluados.

---

## Assumptions

- Los portales inmobiliarios (Finca Raíz, Metrocuadrado, constructoras) son públicos, pero el scraping está sujeto a ToS y puede fallar o ser bloqueado; por ello los seeds deterministas son el respaldo obligatorio.
- El estrato en Bogotá es 1 a 6; el área mínima de vivienda es 36 m² (contexto POT 555).
- El ritmo de absorción se aproxima por zona/estrato usando los registros históricos del corpus; no se requiere un modelo ML completo para el MVP (YAGNI, Principio V).
- El corpus de mercado se indexa/actualiza de forma explícita vía CLI, no automática al iniciar el servidor (patrón de ingesta existente).
- No se añaden variables de entorno nuevas; URLs de portales y rutas de corpus se configuran como constantes.
- El scoring se extiende sin cambiar la fórmula base de F3; se añaden reglas adicionales sobre el nuevo bloque.
- El bloque de mercado es heurístico: reporta datos reales del corpus y no predice precios futuros ni infiere absorción ausente.
- La arquitectura visionaria del doc (React+Node.js+FastAPI) NO aplica; la implementación sigue el patrón Python/FastAPI existente del servidor MCP.

---

## Clarifications

No hay aclaraciones pendientes. Las decisiones de diseño (fuente híbrida scraping + seeds, alcance bloque + CLI, sin nueva tool MCP) fueron resueltas por el usuario y se basan en la arquitectura existente del proyecto.
