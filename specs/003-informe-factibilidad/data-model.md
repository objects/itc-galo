# Data Model: Informe de factibilidad orquestado (`get_feasibility_report`)

**Fase**: Phase 1 del comando `/speckit.plan` | **Fecha**: 2026-08-12
**Feature**: [spec.md](spec.md) | **Base**: constitución v1.0.0, [research.md](research.md)

Este documento define el modelo de datos de la Feature 3: el reporte de factibilidad con
sus 10 bloques, la reutilización de los modelos F1/F2 (`Lote`, `SourceTrace`,
`DatoTematico`, `ValorReferencia`, `ReservaVial`, `ObraPublica`, `ContextoTematico`, `UPL`,
`Localidad`, `ArticuloNormativo`, `CorpusInfo`), las entidades nuevas del reporte
(`DestinoEconomico` reactivado con la nueva fuente, `FeasibilityScore`, `InformeFactibilidad`),
las reglas de validación y las transiciones de estado de bloque. Los nombres técnicos de
campos se conservan en inglés donde el contrato lo exige (constitución Principio I, CHK-015);
la prosa y los valores de dominio están en español. **Ninguna regla de este modelo usa LLM**:
score e interpretaciones son funciones puras sobre los datos recuperados (research D3).

## Convenciones

- **Frontera de parsing** (Principio II): la capa Predio (`catastro/lote/MapServer/3`,
  `f=pjson`) se parsea una sola vez en `ArcGISProvider.consultar_destino_economico`
  (research D5); el resto de bloques reutiliza los parsing de F1/F2. A partir de ahí, el
  orquestador trabaja con modelos pydantic tipados.
- **Estado por bloque**: cada bloque temático/económico usa el patrón F1
  `{estado: "disponible" | "no_encontrado", dato, interpretation, source_trace}` (FR-007,
  SC-002). Un dato ausente o no aplicable es `no_encontrado`, nunca cero ni vacío silencioso.
- **Trazabilidad NON-NEGOTIABLE** (Principio III): cada bloque de datos lleva un
  `SourceTrace` de 5 campos (`source_name`, `layer_id`, `service_url`, `data_vigencia`,
  `query_timestamp`), sin mezclar vigencias (FR-008). `query_timestamp` del reporte marca la
  generación; el de cada bloque marca la consulta a su fuente.
- **Degradación deliberada** (research D5, FR-009/FR-012): un bloque degradado se representa
  en el propio reporte (`no_encontrado`, `upl: null`, `normative_evidence` vacío + causa) con
  su `warning`, nunca como error fatal; los 6 errores fatales solo cubren estados en que el
  reporte no puede construirse con sentido.
- **Determinismo** (FR-006/FR-007): score, confidence, reasons e interpretations son
  funciones puras; el reloj solo alimenta `query_timestamp` (no participa del score).

## Entidades reutilizadas de F1/F2 (sin modificaciones)

### Lote (app/models.py, F1)

Entidad central resuelta por el orquestador mediante los flujos privados de F1
(`_resolver_lote_por_chip`, `_resolver_lote_por_candidato`, `_resolver_lote_por_punto`).
Campos relevantes para el reporte: `chip: str | None` (nullable desde F1), `codigo_catastral`
(= `LOTCODIGO` de la capa Lote 38; **siempre disponible**, también sin CHIP — research H2),
`manzana`, `direccion_normalizada`, `barrio`, `geometry`, `centroid`, `fuente`.

### SourceTrace (app/models.py, F1)

5 campos obligatorios; usado tal cual en los 6 bloques de datos del reporte y en
`source_trace` de `normative_evidence`. `data_vigencia` del bloque económico = `PREVACTUAL`
del registro seleccionado (research H7).

### DatoTematico / ValorReferencia / ReservaVial / ObraPublica / ContextoTematico (F1)

`ContextoTematico` (valor de referencia, reserva vial, obras públicas por punto) se
reutiliza **parcialmente**: `planning_constraints` y `market_context` se alimentan de
`contexto_tematico.reserva_vial` y `contexto_tematico.valor_referencia` respectivamente.
El `environment_context` **no** reutiliza `contexto_tematico.obras_publicas`: la capa es
multipunto y FR-004 exige radio de 500 m (research H5) → consulta propia con buffer (D5).
No se modifica `ContextoTematico` (CHK-015).

### UPL / Localidad / ArticuloNormativo / CorpusInfo (F2)

`UPL` (con `codigo`, `nombre`, `vocacion`, `source_trace`) alimenta
`administrative_context.upl` y `clasificacion_suelo` (research D2). `Localidad`
(`codigo`, `nombre`) alimenta `administrative_context.localidad`. `ArticuloNormativo`
(`articulo`, `titulo`, `libro`, `parte`, `texto_cita`, `similitud` según el shape de los
resultados de `consultar_normativa`) alimenta `normative_evidence.items`.
`CorpusInfo`/`CorpusNoIngestadoError`/`OllamaNoDisponibleError` se usan para detectar
estados degradados del RAG en el orquestador.

## Entidades nuevas del reporte

### DestinoEconomico (reactivado en app/models.py con la NUEVA fuente)

Modelo definido en F1 pero **sin uso**; se reactiva en F3 con los campos de la capa Predio
(research D1/H1). No se toca `ContextoTematico` ni F1/F2.

```python
class DestinoEconomico(BaseModel):
    estado: EstadoDato                          # "disponible" | "no_encontrado"
    codigo_destino: str | None                  # PRECDESTIN (2 dígitos, dominio D_PreDestino)
    descripcion_destino: str | None             # descripción traducida del código (dominio versionado)
    uso: str | None                             # PRECUSO (3 dígitos) + descripción D_UsoTUso de la fila dominante
    area_uso: float | None                      # PREAUSO de la fila dominante (m²)
    usos: list[UsoEconomico]                    # lista de filas del predio (código, descripción, área)
    area_terreno: float | None                  # PREATERRE
    area_construccion: float | None             # PREACONST
    direccion: str | None                       # PREDIRECC
    barrio: str | None                          # PRENBARRIO
    vigencia: str | None                        # PREVACTUAL (2026) → data_vigencia del bloque
    source_trace: SourceTrace
```

`UsoEconomico` (sub-entidad): `{codigo: str, descripcion: str, area_uso: float}`.
La traducción de códigos usa las tablas de dominio versionadas en el provider
(`D_PreDestino` 28 códigos, `D_UsoTUso` 85 códigos; research H1), patrón del mapeo
`NOMBRE → localidad` de F2.

### FeasibilityScore (app/models.py, módulo de scoring app/scoring.py)

```python
class FeasibilityScore(BaseModel):
    score: int          # 0-100, clamp aplicado, entero
    confidence: Literal["high", "medium", "low"]
    reasons: list[str]  # texto fijo por regla + dato + source_name
    rules_applied: list[str]  # códigos de regla aplicados (trazabilidad interna)
```

Funciones puras en `app/scoring.py` (research D3): `calcular_score(bloques) ->
FeasibilityScore` donde `bloques` es una estructura tipada de los 6 bloques evaluables;
`_reglas_positivas`, `_reglas_negativas`, `_clamp`, `_confidence_por_cobertura`,
`_reasons`. Sin I/O, sin LLM, sin reloj (SC-003: mismo input → mismo output).

### InformeFactibilidad (entidad raíz del contrato)

```python
class InformeFactibilidad(BaseModel):
    lot_identity: IdentidadLote
    administrative_context: ContextoAdministrativo
    planning_constraints: BloqueReservaVial
    market_context: BloqueValorReferencia
    environment_context: BloqueObrasPublicas
    economic_context: BloqueDestinoEconomico
    normative_evidence: EvidenciaNormativa
    feasibility_score: FeasibilityScore
    warnings: list[Warning]
    query_timestamp: str   # ISO 8601 UTC, generación del reporte
```

Shapes de los bloques:

- **IdentidadLote**: `{chip, codigo_catastral, manzana, direccion_normalizada, barrio,
  geometry (GeoJSON), centroid, source_trace}` (reutiliza el contrato F1 `lote`).
- **ContextoAdministrativo**: `{upl: {codigo, nombre, vocacion, localidad,
  source_trace} | null, localidad: {codigo, nombre} | null, clasificacion_suelo:
  "urbano" | "rural" | "urbano-rural" | null, source_trace}`. `upl` y `localidad`
  null + warning cuando la UPL no se resuelve (no error; research D5).
- **BloqueReservaVial / BloqueValorReferencia / BloqueObrasPublicas**: patrón
  `{estado, dato, interpretation, source_trace}` (F1). La `interpretation` es texto fijo por
  regla del estado y dato (FR-007), p. ej. `"El lote está afectado por zona de reserva
  vial."` / `"No se encontraron zonas de reserva vial que afecten el lote en la fuente
  consultada."`.
- **BloqueDestinoEconomico**: `{estado, dato: DestinoEconomico | null, interpretation,
  source_trace}`.
- **EvidenciaNormativa**: `{items: [{articulo, titulo, libro, parte, texto_cita,
  similitud}], consulta: str, consulta_automatica: bool, sin_resultados: bool,
  causa: Literal["CORPUS_NO_INGESTADO", "OLLAMA_NO_DISPONIBLE", "SIN_RESULTADOS",
  null], source_trace}`. Degradación: `items: []` + `causa` + warning (FR-009).
- **Warning**: `{codigo: Literal["LOTE_SIN_CHIP", "UPL_NO_ENCONTRADA",
  "LOCALIDAD_NO_DERIVADA", "BLOQUE_SIN_DATO", "NORMATIVA_NO_DISPONIBLE",
  "NORMATIVA_SIN_RESULTADOS"], mensaje: str}`.

## Relaciones

- `InformeFactibilidad.lot_identity` ↔ 1 `Lote` (resuelto por criterio).
- `ContextoAdministrativo.upl` ← 1 `UPL` (join espacial punto-en-polígono, F2);
  `clasificacion_suelo` ← derivado puro de `UPL.vocacion` (D2).
- `BloqueDestinoEconomico.dato` ← `DestinoEconomico` (capa Predio, join por `PRECHIP` o
  `BARMANPRE` = `codigo_catastral` del Lote; research D1).
- `BloqueObrasPublicas.dato` ← query buffer 500 m de `obraspublicas/0` (H5).
- `EvidenciaNormativa.items` ← resultados de `consultar_normativa(consulta, upl=...,
  top_k=...)` (H6).
- `FeasibilityScore` ← función pura sobre los 6 bloques evaluables (D3).

## Reglas de validación (FR-013) y transiciones de estado de bloque

### Validación de entrada (en el límite de la tool, fail-fast)

| Regla | Resultado |
|-------|-----------|
| Exactamente uno de `chip`, `direccion`, `coordenadas` | si no → `PARAMETROS_INVALIDOS` |
| `chip` `^[A-Z0-9]{11}$` | si no → `PARAMETROS_INVALIDOS` (sin llamar fuentes) |
| `direccion` no vacía y `MAPAS_BOGOTA_APIKEY` presente | sin llave → `CREDENCIAL_FALTANTE` |
| `coordenadas`: lat ∈ [-90, 90], lon ∈ [-180, 180] | si no → `PARAMETROS_INVALIDOS` |
| `consulta` opcional 1–500 caracteres | si no → `PARAMETROS_INVALIDOS` |
| `top_k` opcional 1–6 entero | si no → `PARAMETROS_INVALIDOS` |
| Punto fuera de Bogotá | → `FUERA_DE_COBERTURA` |
| Lote no encontrado / múltiples candidatos sin desambiguar | → `LOTE_NO_ENCONTRADO` / `_respuesta_multiples_candidatos` |
| Dirección no localizable | → `DIRECCION_NO_LOCALIZADA` |
| 5xx de una fuente (HTTP o `body.error`) | → `FUENTE_5XX` (vía `_error_de_fuente`) |

### Transiciones de estado de los bloques (degradación, no error)

| Bloque | Disponible | No encontrado / degradado | Warning |
|--------|------------|---------------------------|---------|
| planning_constraints | contexto_tematico.reserva_vial con features | sin features → `no_encontrado` | `BLOQUE_SIN_DATO` |
| market_context | valor_referencia con features | sin features → `no_encontrado` | `BLOQUE_SIN_DATO` |
| environment_context | buffer 500 m devuelve features | sin features → `no_encontrado` | `BLOQUE_SIN_DATO` |
| economic_context | capa Predio devuelve filas (PRECHIP o BARMANPRE) | sin filas → `no_encontrado`; lote sin CHIP y sin codigo_catastral → `no_encontrado` | `BLOQUE_SIN_DATO` y/o `LOTE_SIN_CHIP` |
| administrative_context.upl | UPL resuelta | `UplNoEncontradaError` capturada → `upl: null` | `UPL_NO_ENCONTRADA` |
| administrative_context.localidad | mapeo NOMBRE→localidad aplica | UPL nula → `localidad: null` | `LOCALIDAD_NO_DERIVADA` |
| administrative_context.clasificacion_suelo | derivada de `UPL.vocacion` | UPL nula → `null` | hereda `UPL_NO_ENCONTRADA` |
| normative_evidence | RAG disponible y resultados ≥ umbral (top_k) | `CORPUS_NO_INGESTADO`/`OLLAMA_NO_DISPONIBLE` → items vacíos + causa; sin resultados → `sin_resultados: true` (+ causa `SIN_RESULTADOS`) | `NORMATIVA_NO_DISPONIBLE` / `NORMATIVA_SIN_RESULTADOS` |

Reglas transversales:

- Un 5xx de **cualquier** fuente es fatal (`FUENTE_5XX`); **nunca** se degrada a
  `no_encontrado` (FR-009, research D5).
- `lot_identity` siempre está disponible si la tool no abortó (es la base del reporte); sus
  campos `chip: null` y `codigo_catastral` siempre poblado son estados válidos documentados
  (FR-011 → warning `LOTE_SIN_CHIP`).
- Los `warnings` se construyen de forma determinista en el orquestador (una entrada por
  degradación, código + mensaje) y se deduplican.

## Reglas del feasibility_score (research D3, sin LLM)

| Regla | Tipo | Puntos | Condition |
|-------|------|--------|-----------|
| Base | base | 50 | — |
| UPL resuelta | positivo | +10 | `administrative_context.upl != null` |
| Localidad derivada | positivo | +5 | `administrative_context.localidad != null` |
| market_context disponible | positivo | +10 | `market_context.estado == "disponible"` |
| economic_context disponible | positivo | +10 | `economic_context.estado == "disponible"` |
| Evidencia normativa con ítems | positivo | +5 | `len(normative_evidence.items) > 0` |
| Reserva vial afecta al lote | negativo | −15 | `planning_constraints.dato.afecta_lote == true` |
| UPL ausente | negativo | −5 | `administrative_context.upl == null` |
| Bloque temático/económico no_encontrado | negativo | −5 c/u | por cada bloque con `estado == "no_encontrado"` |
| Evidencia normativa vacía (degradación o sin resultados) | negativo | −5 | `len(items) == 0` |

- `score = clamp(50 + Σ, 0, 100)` entero.
- `confidence`: cobertura de los 6 bloques evaluables — `high` ≥ 5 disponibles, `medium` 3–4,
  `low` ≤ 2. Disponible = bloque con dato (upl o localidad, `estado == "disponible"`,
  items no vacíos).
- `reasons`: textos fijos por regla con el dato interpolado y `source_name`; si
  `confidence == "low"`, se enumeran los bloques ausentes (US3.2).
- **Ninguna regla inventa normativa** (FR-014): solo opera sobre disponibilidad/afectación
  declarada por las fuentes; el `rules_applied` permite auditar qué reglas participaron.

## Errores del reporte (contrato de error, Principio IV)

- **Fatales** (FR-012, vía `_error_de_fuente`): `PARAMETROS_INVALIDOS`,
  `LOTE_NO_ENCONTRADO`, `FUERA_DE_COBERTURA`, `DIRECCION_NO_LOCALIZADA`,
  `CREDENCIAL_FALTANTE`, `FUENTE_5XX`.
- **No fatales** (se representan en el reporte): `UPL_NO_ENCONTRADA` (→ `upl: null`),
  `CORPUS_NO_INGESTADO`/`OLLAMA_NO_DISPONIBLE` (→ `normative_evidence` vacío con causa), y
  los estados `no_encontrado` de bloque. Ver divergencia deliberada en research.md.

## Trazabilidad de vigencias por bloque (FR-008)

| Bloque | source_name | layer_id | data_vigencia |
|--------|-------------|----------|---------------|
| lot_identity | Mapa_Referencia/Mapa_Referencia | 38 | del feature (patrón F1) |
| administrative_context | IDECA Catastro — Unidad de Planeamiento Local | 0 | `2021-12-30` (POT 555/2021) |
| planning_constraints | ordenamientoterritorial/reservavial | 2 | del feature (patrón F1) |
| market_context | catastro/valorreferencia | 0 | del feature (patrón F1) |
| environment_context | gestionpublica/obraspublicas | 0 | del feature (buffer 500 m) |
| economic_context | Predio (catastro/lote) | 3 | `PREVACTUAL` del registro (2026 verificado) |
| normative_evidence | Decreto 555 de 2021 (POT Bogotá) | Decreto_555_2021 | `2021-12-30` |

Nota: los `layer_id`/`data_vigencia` de los bloques F1/F2 se toman de la configuración
`CapaConfig` existente del provider (ver `VIGENCIAS_DEFAULT` en arcgis.py); el reporte no
añade vigencias propias ni mezcla fotos temporales.

Nota 2 (patrón F1/F2): el `source_name` de cada bloque proviene de la constante del
provider, no de un nombre descriptivo local: `_NOMBRES_CANONICOS` en
`app/providers/arcgis.py` (`Mapa_Referencia/Mapa_Referencia`, `catastro/valorreferencia`,
`ordenamientoterritorial/reservavial`, `gestionpublica/obraspublicas`),
`_configuracion_upl` en `app/providers/upl.py` (`IDECA Catastro — Unidad de Planeamiento
Local`) y `CORPUS_SOURCE_NAME` en `app/providers/normativa.py` (`Decreto 555 de 2021 (POT
Bogotá)`). El de `economic_context` (`Predio (catastro/lote)`) lo fijará la configuración
de la capa Predio que implementa T004 en `app/providers/arcgis.py`, siguiendo el mismo
patrón de `_NOMBRES_CANONICOS`.
