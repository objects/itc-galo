# Data Model: 011-catalogo-extensible-wizard-v2

**Feature**: `011-catalogo-extensible-wizard-v2` | **Date**: 2026-09-09 | **Spec**: [spec.md](./spec.md)

## Entidades

### Proyecto (existente, ampliada en F11-wizard HEAD 9641504, sin cambios de schema en F11)

Representa una prefactibilidad iniciada por usuario web. 1:1 con InformeFactibilidad (23 bloques). Persistida en SQLite `app/web/db.py:ProyectoRepositorio` → `.data/proyectos.db` (migración aditiva `PRAGMA table_info` + `ALTER TABLE ADD COLUMN`).

| Campo | Tipo | Constraints | Origen |
|-------|------|-------------|--------|
| `id` | `str` (uuid) | PK, `NOT NULL` | `ProyectoRepositorio.crear` |
| `nombre` | `str` | `1..200` chars, `strip()` | `POST /proyectos` Form `nombre` |
| `criterio_tipo` | `Literal["chip","direccion","coordenadas"]` | enum | `POST /proyectos` / `preview` |
| `criterio_valor` | `str` | `PATRON_CHIP` si chip, `≤500` si dirección, `lat,lon` si coords | `app/utilidades.py:PATRON_CHIP`, `DIRECCION_MAX_CHARS` |
| `consulta` | `str | None` | `≤500` | Form `consulta` opcional |
| `top_k` | `int` | `1..6` default 3 | Form `top_k` |
| `informe` | `dict` (JSON 23 bloques) | `NOT NULL` tras factibilidad | `get_feasibility_report` |
| `uso_previsto` | `str | None` | enum `residencial/comercial/mixto/dotacional/industrial` | Wizard 1b opcional (F11) |
| `escala_m2` | `float | None` | `≥36` | Wizard 1b opcional |
| `presupuesto_rango` | `str | None` | enum `bajo/medio/alto` | Wizard 1b opcional |
| `horizonte_meses` | `int | None` | `6..120` | Wizard 1b opcional |
| `aversion_riesgo` | `str | None` | enum `baja/media/alta` | Wizard 1b opcional |
| `created_at` | `str ISO8601` | `NOT NULL` | `ProyectoRepositorio` |
| `updated_at` | `str ISO8601` | `NOT NULL` | `ProyectoRepositorio` |

**Validación**: server `app/web/main.py:_validar_formulario` extendido (FR-008) rechaza enum fuera de conjunto, `escala_m2` no numérica o `<36`, `horizonte_meses` fuera de `6..120` con 400 + error inline. Client HTML5 `min/max` + `help text` por campo (FR-007). Ningún inválido persiste.
**Reevaluación**: `POST /proyectos/{id}/reevaluar` conserva los 5 campos originales (FR-011).
**Compat**: filas viejas (F10 sin 5 cols) leen `None` sin 500 (FR-010, SC-005).

### CapaConfig (existente, reutilizada, no nueva entidad)

Configuración declarativa de una capa ArcGIS REST temática. Definida en `app/providers/arcgis_utils.py:32`. Relación 1:N con BloqueInforme.

| Campo | Tipo | Constraints |
|-------|------|-------------|
| `service_url` | `str` | `RAIZ_ARCGIS` + `/{servicio}/MapServer` |
| `layer_id` | `str | int` | `f=geojson` point query |
| `source_name` | `str` | Nombre trazable (5 campos) |
| `ruta_consulta` | `str` | Derivada de `service_url + /{layer_id}/query` |
| `construir_params_punto` | `Callable(lat,lon) -> dict` | Genérico `f=geojson&geometry=lon,lat&inSR=4326&spatialRel=Intersects` |

**Uso F11**: Registrar nueva capa = 1 `CapaConfig` en catálogo + registrar en iteración `get_feasibility_report` (FR-001). Reutiliza `RAIZ_ARCGIS`, `construir_params_punto:46`, `app/cache.py`. How-to 3 pasos en docstring/README (FR-004).

### PreviewLote (existente, `POST /proyectos/preview:222-290`, sin cambios F11)

Resultado ligero paso 1 del wizard, sin 23 bloques ni scoring, con World fallback sin API.

| Campo | Tipo | Notas |
|-------|------|-------|
| `lote` | `{chip, direccion_normalizada, barrio, centroid{lat,lon}, geometry}` | `get_lot_summary_by_chip` / `resolve_lot_by_*` ligero + caché Fase5 |
| `upl` | `{codigo,nombre,localidad} | null` | `unidadplaneamientolocal/MapServer/0` UPL lookup, `upl:null` si `UplNoEncontrada` sin warning |
| `manzana` | `str | None` | Si disponible del lote |

**Edge**: cambia criterio tras interrogación → invalida preview previo y obliga reconfirmación (FR-006).

### BloqueInforme (existente, 23 bloques base, F11 no crea tipo nuevo)

Uno de los 23 bloques del `InformeFactibilidad` con trazabilidad 5 campos (Principio III). Producido por `app/main.py:get_feasibility_report:464`.

| Campo | Tipo | Constraints |
|-------|------|-------------|
| `clave` | `str` | Una de 23 (`planning_constraints`, `market_context`, `market_dynamics`, ..., `technical_feasibility`, ...) |
| `titulo` | `str` | Título bloque |
| `estado` | `Literal["disponible","no_encontrado","error"]` | Degradación por bloque |
| `datos` | `dict | list` | Datos temáticos tipados (`app/models.py`) |
| `source_traces[]` | `list[SourceTrace]` | Cada traza con `source_name/layer_id/service_url/data_vigencia/query_timestamp` (FR-002) |
| `warnings` | `list[str]` | `BLOQUE_DEGRADADO` si 5xx |

**Baseline**: 17 loop (`proyecto.html:86` tras fix H-01 incluye `market_dynamics`) + 6 separadas (`lot_identity`, `administrative_context`, `normative_evidence`, `urbanistic_parameters`, `feasibility_score`, `llm_ready_summary`) = 23 (FR-015). 19 evaluables en `app/scoring.py:94-114` baseline no decrecible (FR-003).

### SourceTrace (existente, 5 campos NON-NEGOTIABLE)

| Campo | Tipo |
|-------|------|
| `source_name` | `str` |
| `layer_id` | `str | int` |
| `service_url` | `str` |
| `data_vigencia` | `str` (ISO date) |
| `query_timestamp` | `str` ISO8601 |

Cada bloque nuevo del catálogo conserva `data_vigencia` independiente sin mezclar vigencias (FR-002, FR-016 4 pilares + 10 temáticas).

## Relaciones

```
Proyecto 1 ── 1 InformeFactibilidad (23 BloqueInforme)
CapaConfig 1 ── N BloqueInforme (catálogo iterado en get_feasibility_report)
PreviewLote (efímero, no persistido, client-side hx-include) → Proyecto al POST final
```

## Validaciones y transiciones

- `Proyecto` creado solo tras `POST /proyectos/preview` 200 + interrogación válida (wizard client-side, 1 POST final, FR-006/009).
- `Proyecto` viejo (fila sin 5 cols wizard) → `_fila_a_proyecto` mapea `None` sin 500.
- `Proyecto` reevaluado → conserva 5 campos wizard originales.
- `CapaConfig` nueva con 5xx → bloque `no_encontrado` + `BLOQUE_DEGRADADO` no fatal.

## Fuera de alcance F11

- `specs/012-futura-ampliacion/spec.md` candidatos 1-7 (scraping vivo, Node, token param, rate limiting, PDF, motores a fondo, background jobs) no crean entidades nuevas en F11.
