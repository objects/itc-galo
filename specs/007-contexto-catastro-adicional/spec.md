# Feature Specification

**Rama del feature**: `007-contexto-catastro-adicional`

**Creado**: 2026-08-17

**Estado**: Implementada

**Entrada**: Descripción del usuario: "Feature 7 de mcp-bogota-factibilidad: enriquecer el informe de factibilidad (get_feasibility_report) y el resumen del lote (get_lot_summary_by_chip) con un bloque `catastro_data` que consulta 5 capas catastrales adicionales en paralelo: (1) construccion [0] — huella de construcción (pisos, sotanos, altura, elevación); (2) manzana [0] — código de manzana y sección catastral; (3) densidadpredialmz [0] — número de predios por manzana; (4) variacionareaconstruida [1] — variación del área construida por manzana; y (5) sectorcatastral [0] — nombre del sector catastral. Cada capa se consulta por punto (centroide del lote) con inSR=4326. Las 5 consultas corren en paralelo con `asyncio.gather(return_exceptions=True)` para degradación independiente por capa. El bloque se incluye tanto en el informe de factibilidad (16 bloques total) como en el resumen del lote, y se extiende el scoring con un bloque evaluable adicional (12 bloques evaluables total)."

---

## User Scenarios & Testing (obligatorio)

### User Story 1 (P1) — Datos catastrales adicionales del lote

Como usuario del servidor MCP, quiero que al consultar un lote se incluyan datos catastrales adicionales (construcción, manzana, densidad predial, variación de área construida, sector catastral) para obtener un contexto más completo.

**Por qué esta prioridad**: los datos catastrales adicionales enriquecen la respuesta del lote con información de construcción (pisos, sotanos, altura), estructura catastral (manzana, sección), densidad predial, tendencias de desarrollo (variación de área) y ubicación sectorial, complementando la identidad básica del lote (F1) y el destino económico (F3).

**Prueba independiente**: invocar `get_feasibility_report` con un CHIP válido y verificar que `catastro_data` tiene el patrón `{estado, dato, interpretation, source_trace}` con los 5 sub-campos (construccion, manzana, densidad_predial, variacion_area, sector_catastral). También invocar `get_lot_summary_by_chip` y verificar que `catastro_data` está presente.

**Escenarios de aceptación**:
1. Dado un lote con datos de construcción disponibles, cuando se genera el reporte, entonces `catastro_data.dato.construccion` contiene campos como `pisos`, `altura` y `elevacion_cota`.
2. Dado un lote con sector catastral disponible, cuando se genera el reporte, entonces `catastro_data.dato.sector_catastral` contiene el nombre del sector.
3. Dado un lote sin datos catastrales adicionales, cuando se genera el reporte, entonces `catastro_data.estado == "no_encontrado"` con `interpretation` que indica la ausencia.
4. Dado que una de las 5 capas catastrales falla, cuando se genera el reporte, entonces las capas que respondieron se reportan y las que fallaron quedan en `None`.
5. Dado un lote con variación de área construida, cuando se genera el reporte, entonces `catastro_data.dato.variacion_area` contiene el periodo y la variación porcentual.
