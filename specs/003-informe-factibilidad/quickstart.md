# Quickstart: Informe de factibilidad orquestado (`get_feasibility_report`)

**Fase**: Phase 1 del comando `/speckit.plan` | **Fecha**: 2026-08-12
**Feature**: [spec.md](spec.md)
**Naturaleza**: guía de **validación** (escenarios ejecutables + resultados esperados).
No es una especificación de implementación: para los contratos y el modelo de datos,
remitirse a [contracts/get-feasibility-report.md](contracts/get-feasibility-report.md) y
[data-model.md](data-model.md).

## Prerrequisitos

1. **Python 3.11+** y proyecto instalado en modo editable con dependencias dev:
   ```bash
   pip install -e ".[dev]"
   ```
2. **Variables de entorno** (`.env`, ver `.env.example`):
   - `MAPAS_BOGOTA_APIKEY` (opcional salvo escenario por dirección): geocodificación.
   - `OLLAMA_BASE_URL`, `OLLAMA_EMBEDDING_MODEL=bge-m3`, `OLLAMA_CHAT_MODEL`,
     `VECTOR_DB_PATH=.data/chroma` (solo para la evidencia normativa; el reporte degrada
     sin Ollama).
3. **Ollama corriendo** (opcional) e ingestado el corpus del Decreto 555/2021:
   ```bash
   ollama serve
   python -m app.ingesta.corpus full
   ```
4. **Servidor MCP levantado** (cualquier cliente MCP, p. ej. OpenCode conectado al
   servidor registrado): `get_feasibility_report` es la 7ª tool.

## Escenarios de validación end-to-end

### E1. Reporte por CHIP (ruta completa, bloques disponibles)

**Tool**: `get_feasibility_report`

```json
{ "chip": "AAA0072LRYN" }
```

**Resultado esperado**:

- `lot_identity.chip == "AAA0072LRYN"`, `codigo_catastral == "006101016001"`
  (verificado en vivo, research H2).
- `administrative_context.upl` no nulo, `clasificacion_suelo` derivada de `vocacion`.
- `economic_context.estado == "disponible"` con `descripcion_destino == "Dotacional
  público"` (código 04), fila dominante por mayor `PREAUSO` (40453.8, uso 015), y `usos`
  con las 2 filas del predio (verificado en vivo, research H1/H3).
- `planning_constraints`, `market_context`, `environment_context` con su `estado` y
  `source_trace` de 5 campos.
- `normative_evidence` con `consulta_automatica: true` y ítems si el RAG está disponible.
- `feasibility_score.score` entre 0-100, `confidence`, `reasons` no vacíos.
- `warnings` puede incluir `BLOQUE_SIN_DATO` por bloque `no_encontrado` (los datos
  temáticos puntuales no siempre existen).

### E2. Reporte por coordenadas sin CHIP (join BARMANPRE)

**Tool**: `get_feasibility_report`

```json
{ "coordenadas": { "lat": 4.625188, "lng": -74.081333 } }
```

**Resultado esperado**:

- `lot_identity.chip == null`, `codigo_catastral == "006101016001"` (siempre poblado).
- Warning `LOTE_SIN_CHIP`.
- `economic_context` **resuelto por `BARMANPRE`** = `codigo_catastral`: mismas 2 filas del
  predio (verificado en vivo, research H2) → `estado == "disponible"` igual que E1.
- `administrative_context`, scoring y warnings según disponibilidad.

### E3. Reporte con consulta normativa explícita

```json
{ "chip": "AAA0072LRYN", "consulta": "¿Qué usos del suelo permite la UPL 24 (Chapinero) para un lote de uso dotacional público?", "top_k": 5 }
```

**Resultado esperado**:

- `normative_evidence.consulta ==` el texto enviado, `consulta_automatica: false`,
  `top_k: 5` aplicado.
- Ítems con cita literal (articulo/titulo/libro/parte/texto_cita/similitud);
  `sin_resultados: false` si hay ítems sobre el umbral.

### E4. Reporte con consulta normativa automática (sin parámetro `consulta`)

```json
{ "chip": "AAA0072LRYN" }
```

**Resultado esperado**:

- `normative_evidence.consulta_automatica: true`; `consulta` contiene la UPL, la localidad
  y la clasificación de suelo (research D2); se pasó `upl=UPLxx` a `consultar_normativa`
  (filtro territorial estricto de F2, research H6).

### E5. Degradación sin Ollama (reporte NO falla)

**Condición**: Ollama apagado o modelo ausente; `OLLAMA_BASE_URL` inalcanzable.

```json
{ "chip": "AAA0072LRYN" }
```

**Resultado esperado**:

- **No** error `OLLAMA_NO_DISPONIBLE`.
- `normative_evidence.items == []`, `causa == "OLLAMA_NO_DISPONIBLE"` (o
  `"CORPUS_NO_INGESTADO"` si el corpus no está), warning `NORMATIVA_NO_DISPONIBLE`.
- Los otros 9 bloques completos; `feasibility_score` incluye la penalización por evidencia
  vacía (−5) y el reason correspondiente. (Divergencia deliberada vs `consultar_normativa`,
  research.md.)

### E6. Reporte sin UPL (degrada a `upl: null`, no `LOTE_SIN_UPL`)

**Condición**: punto resuelto por coordenadas en zona sin UPL asignada (o simular en tests
mockeando `UplNoEncontradaError`).

```json
{ "coordenadas": { "lat": 4.0, "lng": -74.0 } }
```

**Resultado esperado**:

- `administrative_context.upl == null`, `clasificacion_suelo == null`, warning
  `UPL_NO_ENCONTRADA` (y `LOCALIDAD_NO_DERIVADA` si aplica).
- `lot_identity` y demás bloques continúan; la consulta normativa automática usa solo
  localidad sin filtro territorial (research D2).

### E7. Errores fatales (validación de entrada y cobertura)

| Llamada | Resultado esperado |
|---------|--------------------|
| `{}` (ningún criterio) | `PARAMETROS_INVALIDOS` |
| `{ "chip": "abc" }` (formato inválido) | `PARAMETROS_INVALIDOS` |
| `{ "chip": "AAA0072LRYN", "coordenadas": { "lat": 4.6, "lng": -74.1 } }` (dos criterios) | `PARAMETROS_INVALIDOS` |
| `{ "chip": "ZZZ99999999" }` (CHIP inexistente) | `LOTE_NO_ENCONTRADO` |
| `{ "direccion": "Calle 1 # 2-3" }` sin `MAPAS_BOGOTA_APIKEY` | `CREDENCIAL_FALTANTE` |
| `{ "coordenadas": { "lat": 40.0, "lng": -3.0 } }` (fuera de Bogotá) | `FUERA_DE_COBERTURA` |
| `{ "chip": "AAA0072LRYN", "consulta": "x" * 501 }` | `PARAMETROS_INVALIDOS` |
| `{ "chip": "AAA0072LRYN", "top_k": 10 }` | `PARAMETROS_INVALIDOS` |

### E8. Determinismo del scoring (SC-003)

Dos llamadas idénticas con la misma configuración de entorno y fuentes:

```json
{ "chip": "AAA0072LRYN" }
```

**Resultado esperado**: `feasibility_score` **idéntico** (mismo `score`, `confidence` y
`reasons`) en ambas; solo varía `query_timestamp` (que no participa del score).

### E9. Trazabilidad de 5 campos (FR-010, SC-002) en todo bloque de datos

Verificar que cada bloque (`lot_identity`, `administrative_context`,
`planning_constraints`, `market_context`, `environment_context`, `economic_context`,
`normative_evidence`) incluya `source_trace` con los 5 campos: `source_name`, `layer_id`,
`service_url`, `data_vigencia`, `query_timestamp`. En `economic_context`,`data_vigencia`
debería reflejar la vigencia del registro (`PREVACTUAL`, p. ej. `"2026"`).

## Verificaciones de datos en vivo (referencia para validar E1/E2)

Fuentes verificadas el 2026-08-12 (research H1-H3):

- CHIP `AAA0072LRYN` → 2 filas en `catastro/lote/MapServer/3` (`PRECDESTIN=04`,
  `PRECUSO=015`/`096`, `PREAUSO=40453.8`/`3011.3`).
- `LOTCODIGO` (capa Lote 38) == `BARMANPRE` (capa Predio 3): `006101016001` y
  `004103017022` (join del escenario E2).
- La capa Predio requiere `f=pjson` (`f=geojson` → 400).
- Capa `obraspublicas/0` es multipunto: el buffer 500 m requiere
  `distance=500&units=esriSRUnit_Meter` (FR-004).

## Fuera de alcance (validación negativa)

- **Diagnóstico de prefactibilidad con reglas de negocio urbanístico**: no existe en F3;
  el `feasibility_score` es heurístico sobre datos (FR-014) y el diagnóstico es mejora
  futura explícita.
- **Modificación de F1/F2**: `get_feasibility_report` no altera los contratos de las 6
  tools existentes ni el `contexto_tematico` de F1 (CHK-015).
