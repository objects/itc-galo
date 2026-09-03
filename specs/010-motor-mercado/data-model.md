# Data Model: Motor de Mercado (F10)

Modelo de datos del bloque `market_dynamics` y del corpus de mercado. Los modelos son
pydantic v2; los nombres de campo del contrato JSON se conservan en inglés donde lo
exige la constitución (Principio I).

## Resumen de entidades

| Entidad | Rol | Ubicación |
|---|---|---|
| `RegistroOfertaInmobiliaria` | Línea del corpus JSONL (oferta individual) | `app/models.py` + `data/corpus/mercado/*.jsonl` |
| `OfertaCompetidora` | Clúster de ofertas comparables | `app/models.py` |
| `RitmoAbsorcion` | Velocidad de venta (unidades/mes + criterio) | `app/models.py` |
| `ContextoMercado` | `dato` del bloque (`market_dynamics`) | `app/models.py` |
| `BloqueMarketDynamics` | Bloque del informe `{estado, dato, interpretation, source_trace}` | `app/models.py` |

---

## 1. `RegistroOfertaInmobiliaria`

Una oferta individual extraída de un portal o definida en los seeds. Es la unidad de
almacenamiento del corpus JSONL y la entrada de la validación/dedup (FR-006).

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `id` | `str` | sí | Identificador estable: SHA-256 de `fuente + url` (o de la clave normalizada si no hay URL). |
| `fuente` | `Literal["finca_raiz","metrocuadrado","constructora","seed"]` | sí | Portal de origen (o `seed` para los respaldos deterministas). |
| `url` | `str \| None` | no | URL pública de la oferta (si aplica). |
| `precio` | `float` | sí | Precio total en COP (estrictamente positivo). |
| `area_m2` | `float` | sí | Área privada vendible en m² (≥ 36, FR-006). |
| `precio_m2` | `float` | sí (derivado) | `precio / area_m2`, calculado en ingesta. |
| `estrato` | `int \| None` | no | Estrato 1-6 (validado). |
| `amenidades` | `list[str]` | no | Lista de amenidades (conjunto, garaje, etc.). |
| `localidad` | `str \| None` | no | Localidad de la oferta (para filtro territorial). |
| `upl` | `str \| None` | no | UPL de la oferta (para filtro territorial). |
| `barrio` | `str \| None` | no | Barrio (detalle opcional). |
| `fecha_captura` | `str` | sí | ISO 8601 de captura (sin reloj en runtime: congelada en la huella). |

**Validaciones (FR-006)**: `estrato` ∈ 1-6; `area_m2` ≥ 36; `precio > 0` y `area_m2 > 0`.
Un registro sin `precio` o sin `area_m2` se descarta con warning deduplicado.

## 2. `OfertaCompetidora`

Clúster determinista de ofertas comparables, agrupado por (`estrato`, `zona`) (research D2).

| Campo | Tipo | Descripción |
|---|---|---|
| `zona` | `str` | Localidad o UPL del clúster. |
| `conteo` | `int` | Número de ofertas del clúster. |
| `precio_m2_promedio` | `float \| None` | Media de `precio_m2` de las ofertas del clúster. |
| `estrato` | `int \| None` | Estrato del clúster (1-6). |

## 3. `RitmoAbsorcion`

Velocidad de venta de la zona (research D3), derivada de forma determinista.

| Campo | Tipo | Descripción |
|---|---|---|
| `unidades_mes` | `float \| None` | Unidades vendidas por mes estimadas. |
| `criterio` | `str \| None` | Texto que documenta la fórmula/derivación. |

## 4. `ContextoMercado`

`dato` del bloque. Todos los campos son `None` cuando faltan datos (degradación por campo,
FR-015). No se infieren datos ausentes.

| Campo | Tipo | Descripción |
|---|---|---|
| `precio_m2_referencia` | `float \| None` | Mediana del `precio_m2` de las ofertas comparables de la zona del lote. |
| `estrato` | `int \| None` | Estrato 1-6 de la zona. |
| `oferta_competidora` | `list[OfertaCompetidora] \| None` | Clústeres de oferta comparables. |
| `ritmo_absorcion` | `RitmoAbsorcion \| None` | Ritmo de absorción de la zona. |

## 5. `BloqueMarketDynamics`

Bloque del informe con el patrón F3/F6/F7/F8 `{estado, dato, interpretation, source_trace}`.

| Campo | Tipo | Descripción |
|---|---|---|
| `estado` | `EstadoDato` | `disponible` \| `no_encontrado`. |
| `dato` | `ContextoMercado \| None` | `None` si `estado == "no_encontrado"`. |
| `interpretation` | `str` | Texto determinista (sin LLM, FR-014) sobre los datos reales. |
| `source_trace` | `SourceTrace` | 5 campos (FR-010); fuente primaria = corpus de mercado. |

> **Nota (FR-010)**: el bloque NO publica `source_traces` (a diferencia de F6/F7): la
> fuente primaria es única (el corpus local) y la proveniencia por registro (portal
> origen) viaja dentro de `dato.oferta_competidora` / `interpretation`, no como trazas
> fabricadas. `source_trace` documenta la consulta al corpus.

## 6. Campos en `InformeFactibilidad`

Se añade UN campo aditivo a `InformeFactibilidad` (opcional, default `None`, patrón
`urbanistic_parameters`/`financial_analysis`):

```text
market_dynamics: BloqueMarketDynamics | None = None
```

Los bloques previos (incluido `market_context` = valor de referencia catastral) no se
tocan (FR-013).

## 7. Scoring (extensión de `app/scoring.py`)

Reglas nuevas, aditivas sobre la base F3:

| Regla | Puntos | Condición |
|---|---|---|
| `r_contexto_mercado` | +10 | `market_dynamics` disponible con `precio_m2_referencia` y `estrato` no None. |
| `r_oferta_competidora` | +5 | `market_dynamics` disponible con `oferta_competidora` no vacía. |
| `r_absorcion_mercado` | +5 | `market_dynamics` disponible con `ritmo_absorcion` presente. |

- `market_dynamics` se añade a `BLOQUES_EVALUABLES` como bloque evaluable adicional y a
  `_disponibilidad_bloques`/`_bloques_con_estado` (tratamiento opcional: `None` = no
  evaluado, mismo que F8/Fase 3).
- Los umbrales de confidence se mantienen absolutos (high ≥10, medium 5-9, low ≤4)
  (FR-012). La regla existente `r_mercado` (valor catastral) permanece sin cambios.

## 8. Esquema del corpus (JSONL)

```text
data/corpus/mercado/
├── seeds.jsonl        # seeds deterministas (versionado, sin red)
├── mercado.jsonl      # corpus consolidado (scraping + seeds), versionado
└── mercado.sha256     # huella SHA-256 del mercado.jsonl (integridad/dedup)
```

Cada línea de `seeds.jsonl` y `mercado.jsonl` es un objeto `RegistroOfertaInmobiliaria`
serializado (un JSON por línea). La huella `mercado.sha256` sigue el patrón F4
(`.sha256` al lado del JSONL).
