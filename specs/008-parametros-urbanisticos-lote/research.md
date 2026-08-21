# Research: Parámetros Urbanísticos del Lote (Feature 8)

**Feature**: [spec.md](spec.md) | **Fecha**: 2026-08-20

## D1 — Fuente espacial: SINUPOT/SDP ArcGIS REST

**Servicio**: `sinu.sdp.gov.co/serverp/rest/services/POT555/NORMA_URBANÍSTICA_Y_OT/MapServer`

Verificaciones realizadas:
- **Público (sin autenticación)**: confirmado. El servicio responde sin credenciales, a diferencia de Mapas Bogotá API (que necesita `MAPAS_BOGOTA_APIKEY`).
- **Diferente de Catastro**: el dominio `sinu.sdp.gov.co` es distinto de `serviciosgis.catastrobogota.gov.co`. El proyecto NO consulta este servidor actualmente; es una fuente nueva.
- **CRS de las capas**: EPSG 4686 (MAGNA-SIRGAS). La consulta debe usar `inSR=4326` (WGS84 del centroide) y `outSR=4686` para la conversión correcta.
- **Layer 2 — Tratamiento urbanístico**: contiene polígonos de tratamiento con denominación del tratamiento (nombre legible). Campo de atributos esperado: nombre del tratamiento.
- **Layer 14 — Rangos de edificabilidad**: contiene COS, CUS y altura por tratamiento de desarrollo. Complementa la información del RAG normativo.
- **Patrón de consulta**: idéntico a Catastro — `geometry=<lng,lat>&geometryType=esriGeometryPoint&inSR=4326&outSR=4686&spatialRel=esriSpatialRelIntersects&f=geojson`.

**Decisión D1**: Crear un provider nuevo `app/providers/sdp.py` que encapsule la consulta a SINUPOT (Principio II). El provider usa `httpx.AsyncClient` con timeout configurable (default 10s). La URL base se configura como constante `SDP_BASE_URL` (FR-022).

## D2 — Fuente normativa: RAG para parámetros numéricos

**Estrategia**: consultar la colección consolidada `decreto_555_2021` existente con un prompt específico para extraer COS, CUS, altura y retiros.

**Artículos relevantes del Decreto 555/2021**:
- **Art. 281**: edificabilidad, COS (Coeficiente de Ocupación del Suelo), CUS (Coeficiente de Utilización del Suelo), altura máxima.
- **Art. 389**: estacionamientos requeridos por uso y área.
- **Anexo 5 — Manual de Normas Comunes a Tratamientos Urbanísticos**: retiros frontales, laterales y posteriores por tipo de vía y tratamiento.

**Decisión D2**: No crear un nuevo índice ni colección. Reutilizar `NormativaProvider.consultar()` con un prompt estructurado que solicite valores numéricos específicos (COS, CUS, altura, retiros, estacionamientos). El prompt se construye en `app/main.py` (patrón `_construir_consulta_automatica`). La salida del RAG para este bloque es diferente de `normative_evidence`: los campos numéricos se extraen del texto de la respuesta del LLM, no de los items de evidencia.

**Implícito**: la consulta RAG puede no retornar valores numéricos exactos (el Decreto 555 define COS/CUS por rangos o por tipo de tratamiento, no como un valor fijo por lote). Cuando el RAG no puede extraer un valor numérico, el campo queda `None` (degradación por bloque).

## D3 — Integración con la arquitectura existente

**Patrón de bloque** (F3/F6/F7): cada bloque sigue `{estado, dato, interpretation, source_trace}`. El bloque `urbanistic_parameters` es un bloque más del informe, con la particularidad de que su dato proviene de **dos fuentes** (SDP + RAG).

**Patrón de degradación** (FR-008/FR-009):
- Si SDP falla → bloque `no_encontrado` + warning `BLOQUE_DEGRADADO`. El RAG no se consulta (no hay tratamiento para buscar parámetros).
- Si SDP responde pero sin features → bloque `no_encontrado` + warning `BLOQUE_SIN_DATO`.
- Si SDP responde con tratamiento pero RAG falla → bloque `disponible` con tratamiento y campos numéricos en `None`.
- Si ambos responden → bloque `disponible` con todos los campos poblados.

**Orquestación**: el bloque se añade como una **tercera ronda de consultas paralelas** en `get_feasibility_report` y `get_lot_summary_by_chip`. La consulta SDP y la consulta RAG se ejecutan en secuencia (la RAG depende del tratamiento de SDP para construir el prompt).

**Source trace dual**: cuando ambas fuentes responden, el `source_trace` principal es el de SDP (fuente primaria del bloque); los campos numéricos del RAG no generan un source_trace propio en el contrato del bloque (patrón F6: un solo source_trace por bloque).

## D4 — Modelo de datos

**Entidades nuevas** (5 modelos en `app/models.py`):

1. **TratamientoUrbanistico**: denominación del tratamiento + código de capa. Fuente: SDP layer 2.
2. **ParametrosEdificabilidad**: COS, CUS, altura_maxima_m. Fuente: RAG (art. 281) + SDP layer 14 (complementario).
3. **RetirosLote**: frontal_m, laterales_m, posteriores_m. Fuente: RAG (Anexo 5).
4. **EstacionamientosRequeridos**: requeridos (entero), criterio (string). Fuente: RAG (art. 389).
5. **ParametrosUrbanisticos**: contenedor del bloque con tratamiento + edificabilidad + retiros + estacionamientos.

**Wrapper de bloque**: `BloqueParametrosUrbanisticos` con patrón `{estado, dato, interpretation, source_trace}`.

**Relación con modelos existentes**: `ParametrosUrbanisticos` es un modelo independiente; no hereda de `DatoTematico` (que tiene estado/source_trace integrados). El wrapper de bloque maneja el estado externamente (patrón F6).

## D5 — Scoring extension

**Reglas nuevas** (3 reglas en `app/scoring.py`):

| Regla | Tipo | Puntos | Condición |
|-------|------|--------|-----------|
| `r_parametros_urbanisticos` | Positiva | +10 | Tratamiento y edificabilidad disponibles |
| `r_estacionamientos_calculados` | Positiva | +5 | Estacionamientos calculados (requeridos > 0) |
| `r_tratamiento_conservacion` | Negativa | −15 | Tratamiento == "Conservación" sin licencia especial |

**Total de bloques evaluables**: 13 (12 actuales + `urbanistic_parameters`).

**Thresholds de confidence** (actualizados de FR-012):
- `high` ≥ 10 disponibles
- `medium` 5–9
- `low` ≤ 4

**Decisión D5**: la regla `r_tratamiento_conservacion` solo penaliza si el tratamiento es exactamente "Conservación" (patrón del SINUPOT). No se infiere si hay o no licencia especial (el LLM no debe inferir reglas ausentes, FR-015).

## D6 — Consulta RAG para parámetros urbanísticos

**Prompt estructurado** (generado por reglas, sin LLM):

```
¿Cuáles son los valores de COS, CUS, altura máxima (en metros), retiros frontales,
laterales y posteriores (en metros), y estacionamientos requeridos para un lote con
tratamiento urbanístico "<tratamiento>" en la UPL <codigo_upl>? Cita los artículos
y valores exactos del POT.
```

**Parsing de la respuesta**: el LLM retorna texto libre. Se extraen valores numéricos con patrones regex (COS/CUS como float, altura como entero, retiros como float, estacionamientos como entero). Si un valor no se puede extraer, queda `None`.

**Decisión D6**: el parsing regex es una capa de abstracción adicional pero necesaria para convertir la salida del RAG en datos tipados. La alternativa de pedir JSON al LLM fue rechazada porque el citation forcing de F2/F4 prioriza citas literales, no formato estructurado. El parsing regex es determinista (mismo texto → mismos valores).

## D7 — Alternativas consideradas y rechazadas

1. **Consultar SINUPOT como parte de ArcGISProvider** (rechazado): viola Principio II (modularidad por providers). SINUPOT es un servicio diferente de Catastro; mezclarlos crearía acoplamiento.

2. **Nuevo provider RAG para parámetros urbanísticos** (rechazado): la consulta reutiliza `NormativaProvider.consultar()` con un prompt diferente. Crear un nuevo provider RAG implicaría duplicar la conexión a ChromaDB y Ollama.

3. **Capa 14 como fuente primaria de COS/CUS** (rechazada): la capa 14 contiene rangos, no valores exactos por lote. El RAG normativo es la fuente de referencia para los valores del POT.

4. **Nuevo campo `source_trace_secundario`** en el bloque (rechazado): rompería el patrón `{estado, dato, interpretation, source_trace}` de F3/F6/F7. El source_trace principal documenta la fuente primaria (SDP); los datos del RAG son complementarios.

5. **Dependencia del tratamiento para la consulta RAG** (aceptada): la consulta RAG necesita el nombre del tratamiento para construir un prompt específico. Esto crea una dependencia secuencial (SDP → RAG) pero es necesaria para la precisión de la consulta.

## D8 — Rendimiento

- **Tiempo base del reporte** (F3+F6+F7): ~10 s (3 rondas paralelas de consultas ArcGIS).
- **Overhead F8**: 1 consulta SDP (< 2 s) + 1 consulta RAG (< 1 s) = ~3 s adicional.
- **SC-001**: reporte total < 15 s en condiciones normales.
- **SC-007**: overhead adicional ≤ 3 s sobre el tiempo base.
- **Degradación**: si SDP tarda > 10 s, el timeout del provider produce `Fuente5xxError` → bloque `no_encontrado`. El reporte continúa.
