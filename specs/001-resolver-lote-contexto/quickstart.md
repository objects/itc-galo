# Quickstart: Resolver lote con contexto temático

**Fase**: Phase 1 del comando `/speckit.plan` | **Fecha**: 2026-08-10
**Feature**: [spec.md](spec.md)
**Naturaleza**: guía de **validación** (escenarios ejecutables + resultados esperados).
No es una especificación de implementación: para los contratos y el modelo de datos,
remitirse a [contracts/](contracts/) y [data-model.md](data-model.md).

## Prerrequisitos

1. **Python 3.11+**.
2. Instalar el proyecto en modo editable con dependencias de desarrollo:
   ```bash
   pip install -e ".[dev]"
   ```
   (instala `mcp>=1.0.0`, `httpx`, `pydantic` y `pytest` según `pyproject.toml`).
3. **Variable de entorno `MAPAS_BOGOTA_APIKEY`** (opcional): **obligatoria solo para la
   consulta por dirección**. Se lee desde el entorno (`.env`); ver `.env.example` para el
   nombre exacto. Sin la variable, la consulta por dirección falla rápido con
   `CREDENCIAL_FALTANTE` (FR-010) y las consultas por CHIP y por coordenadas siguen
   funcionando.
4. **Fuentes públicas accesibles** desde la red donde se ejecute la validación:
   `https://catalogopmb.catastrobogota.gov.co/PMBWeb/web` (API de búsqueda de Mapas Bogotá)
   y `https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/`.

## Comandos de verificación automática

```bash
# Smoke test de arranque: el servidor inicia y las 4 tools quedan registradas
pytest tests/smoke

# Contract tests: validan los contratos de las tools y los estados de error
# (respuestas simuladas para los casos deterministas; ver contracts/)
pytest tests/contract
```

## Ejecución del servidor MCP

Iniciar el servidor para consumirlo con un cliente MCP por stdio (p. ej. el Inspector de
MCP):

```bash
python -m app.main
```

Las 4 tools expuestas: `resolve_lot_by_chip`, `resolve_lot_by_address`,
`resolve_lot_by_coordinates`, `get_lot_summary_by_chip`. Sus contratos completos están en
[contracts/](contracts/).

## Escenarios de validación contra servicios reales

> Los CHIP y coordenadas son ejemplos de trabajo tomados del brief del producto; un CHIP
> válido cualquiera de Bogotá sirve para el escenario 1.

### Escenario 1 — Resolver CHIP válido → resumen con trazabilidad

- **Acción**: invocar `get_lot_summary_by_chip` con un CHIP válido (p. ej. `AAA0072LRYN`).
- **Resultado esperado**: resumen consolidado con identidad del lote (CHIP, código
  catastral, manzana) y contexto por fuente. Verificar que la respuesta llega en **menos de
  10 s** (SC-001) y que el contenido es **descriptivo** (sin puntajes de factibilidad,
  FR-011).
- **Referencias**: contrato [get-lot-summary-by-chip.md](contracts/get-lot-summary-by-chip.md).

### Escenario 2 — CHIP inexistente → `LOTE_NO_ENCONTRADO`

- **Acción**: invocar `get_lot_summary_by_chip` (o `resolve_lot_by_chip`) con un CHIP
  inexistente (p. ej. `ZZZ9999ZZZ9`).
- **Resultado esperado**: error canónico `LOTE_NO_ENCONTRADO` con mensaje claro y accionable
  (SC-006), distinto de cualquier estado "dato no encontrado" por fuente.
- **Referencias**: taxonomía de errores en [data-model.md](data-model.md).

### Escenario 3 — Coordenadas dentro de un lote → lote

- **Acción**: invocar `resolve_lot_by_coordinates` con un punto dentro de Bogotá
  (p. ej. `latitude=4.60313`, `longitude=-74.08327`).
- **Resultado esperado**: lote con `codigo_catastral`, `manzana` y geometría; `chip`
  puede ser `null` (las capas catastrales ArcGIS no publican CHIP; la identidad la dan
  `codigo_catastral`/`manzana`); cada bloque de contexto temático con su `estado` y
  `source_trace`.
- **Referencias**: contrato [resolve-lot-by-coordinates.md](contracts/resolve-lot-by-coordinates.md).

### Escenario 4 — Coordenadas fuera de Bogotá → `FUERA_DE_COBERTURA`

- **Acción**: invocar `resolve_lot_by_coordinates` con un punto claramente fuera de Bogotá
  (p. ej. `latitude=6.25`, `longitude=-75.57`).
- **Resultado esperado**: error canónico `FUERA_DE_COBERTURA` con mensaje claro (SC-006).
  Nota: coordenadas fuera de rango [-90, 90] / [-180, 180] producen en cambio
  `PARAMETROS_INVALIDOS` (FR-012).
- **Referencias**: contrato [resolve-lot-by-coordinates.md](contracts/resolve-lot-by-coordinates.md).

### Escenario 5 — Dirección sin credencial → `CREDENCIAL_FALTANTE` (fail-fast)

- **Precondición**: `MAPAS_BOGOTA_APIKEY` **no** está configurada.
- **Acción**: invocar `resolve_lot_by_address` con una dirección de Bogotá
  (p. ej. `Calle 26 # 69-76`).
- **Resultado esperado**: error canónico `CREDENCIAL_FALTANTE` de inmediato, sin consultar
  fuentes (fail-fast, FR-010). Verificar que `resolve_lot_by_chip` y
  `resolve_lot_by_coordinates` **siguen funcionando** sin la credencial.
- **Referencias**: contrato [resolve-lot-by-address.md](contracts/resolve-lot-by-address.md).

### Escenario 6 — Verificar trazabilidad y estados por fuente

- **Acción**: sobre la respuesta del escenario 1, inspeccionar **cada dato** (identidad y
  cada entrada de `contexto_por_fuente`).
- **Resultado esperado**: cada dato incluye **exactamente los 5 campos de trazabilidad**
  `source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp` (FR-006,
  SC-003 — incluye `query_timestamp`, que el contrato exige siempre) y un `estado` que es
  `disponible` o `no_encontrado` (FR-007, SC-002), nunca cero ni vacío silencioso. Si dos
  temáticas tienen vigencias distintas, cada una conserva la suya (FR-008, SC-004).
- **Referencias**: modelo `SourceTrace` y estados de dato en [data-model.md](data-model.md).

## Criterios de éxito verificables con esta guía

| Criterio | Cómo se verifica |
|----------|------------------|
| SC-001 (< 10 s) | Escenario 1 (cronometrar la respuesta). |
| SC-002 (estados por fuente) | Escenarios 1 y 6. |
| SC-003 (origen + vigencia + `query_timestamp`) | Escenario 6. |
| SC-004 (no mezclar vigencias) | Escenario 6. |
| SC-005 (CHIP válido → resumen) | Escenario 1. |
| SC-006 (errores claros) | Escenarios 2, 4 y 5. |
