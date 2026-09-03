# Research: Motor de Mercado (F10)

Investigación y decisiones de diseño para el bloque `market_dynamics` y la ingesta de
mercado. Formato: Decision / Rationale / Alternatives considered.

## D0 — Naming del bloque nuevo: `market_dynamics` (no `market_context`)

- **Decision**: el bloque nuevo del informe se llama `market_dynamics` (dinámica de
  mercado inmobiliario). La entidad de datos es `ContextoMercado`.
- **Rationale**: el campo `market_context` YA existe en `InformeFactibilidad`
  (`app/models.py` línea 976) como `BloqueValorReferencia`, que expone el **valor de
  referencia catastral** del terreno (capa `catastro/valorreferencia`, campo `valor_m2`)
  y ya alimenta la regla de scoring `r_mercado` (+10, `PUNTOS_MERCADO`). El spec F10
  pide un bloque con `precio_m2_referencia` de **mercado de venta**, `estrato`,
  `oferta_competidora` y `ritmo_absorcion` — datos distintos. FR-013 prohíbe modificar
  los bloques de F3, y SC-004 exige no-regresión de las 7 tools. Por tanto el bloque
  nuevo usa un nombre distinto y el `market_context` existente (valor catastral)
  permanece intacto.
- **Alternatives considered**: (a) reutilizar el nombre `market_context` reemplazando el
  valor catastral → rompe el contrato F1/F3 y pierde el valor de referencia catastral;
  (b) renombrar el bloque catastral existente a `catastral_value` y usar `market_context`
  para F10 → migración de contrato incompatible, viola FR-013. Rechazadas ambas.

## D1 — Fuente híbrida: scraping real + seeds deterministas

- **Decision**: el corpus se puebla intentando scraping de portales (Finca Raíz,
  Metrocuadrado, constructoras) y, ante fallo de red / bloqueo ToS / ausencia de datos,
  cae a un conjunto de **seeds deterministas** versionado en git. Los seeds garantizan
  que el bloque funcione sin red y que los tests sean reproducibles (FR-005, SC-005).
- **Rationale**: el scraping de portales inmobiliarios es frágil (ToS, cambios de DOM,
  anti-bot). El spec (FR-004/FR-007) exige el respaldo. El patrón es análogo al del
  corpus normativo (fuente de verdad versionada + ingesta explícita).
- **Alternatives considered**: (a) solo scraping → bloque siempre degradado en CI/tests
  sin red; (b) solo seeds → no aporta datos reales, contradice US2. Rechazadas.

## D2 — Clustering determinista (sin ML)

- **Decision**: `oferta_competidora` se calcula agrupando los registros por
  (`estrato`, `zona`) donde `zona` es la localidad o UPL derivada del registro; cada
  clúster reporta `conteo` y `precio_m2_promedio` (media de `precio_m2` de los
  registros del clúster). Es un agrupamiento determinista por llaves discretas, no un
  algoritmo de clustering no supervisado.
- **Rationale**: el spec pide "clustering" pero el MVP no requiere ML (Assumption 3,
  Principio V YAGNI). Agrupar por estrato+zona es suficiente para "oferta competidora y
  ritmos de absorción" y es 100% determinista (SC-001).
- **Alternatives considered**: k-means o DBSCAN sobre coordenadas → dependencia nueva,
  no determinista (semillas aleatorias), overkill para el MVP. Rechazada.

## D3 — Ritmo de absorción heurístico

- **Decision**: `ritmo_absorcion.unidades_mes` se estima de forma determinista a partir
  de la antigüedad de las ofertas comparables del corpus (diferencia entre `fecha_captura`
  y la vigencia del corpus) o, si el corpus no trae fechas, de un valor de seeds por
  zona/estrato. `criterio` documenta la fórmula en texto. No se usa reloj en runtime:
  la vigencia se congela en la huella del corpus (SC-001).
- **Rationale**: la absorción real requiere histórico de ventas que los portales públicos
  no exponen; el spec la declara aproximación (Assumption 3, FR-014/FR-015 no inferir
  datos ausentes). Se reporta solo cuando hay dato real derivable.
- **Alternatives considered**: modelo ML de absorción → fuera de alcance MVP. Rechazada.

## D4 — Librería de scraping: httpx + stdlib (sin dependencia nueva)

- **Decision**: el scraping usa `httpx.AsyncClient` (ya en el stack) con timeout
  configurable 10s (FR-017) y parsing con `html.parser`/regex de stdlib. No se añade
  `beautifulsoup4`/`lxml`/`scrapy` como dependencia dura.
- **Rationale**: las seeds deterministas son el respaldo robusto; el scraping es
  best-effort. Evitar dependencias nuevas respeta Principio V (YAGNI) y mantiene el
  `pyproject.toml` estable. Si un portal exige parsing HTML complejo, el cambio se
  aísla en `app/ingesta/mercado.py`.
- **Alternatives considered**: `beautifulsoup4` → depende de `lxml`/`soupsieve`, no
  aporta para páginas que ya requieren anti-bot; `scrapy` → framework completo, overkill.
  Rechazadas por ahora (se pueden re-evaluar si un portal específico lo exige).

## D5 — Esquema del corpus y huella

- **Decision**: el corpus vive en `data/corpus/mercado/mercado.jsonl` (una línea por
  `RegistroOfertaInmobiliaria`) + `mercado.sha256` (huella SHA-256 del JSONL), versionado
  en git (FR-020). Las seeds viven en `data/corpus/mercado/seeds.jsonl` (deterministas,
  versionadas). El subcomando `mercado` escribe el JSONL consolidado y su huella, análogo
  a `descargar`/`acto` (FR-008).
- **Rationale**: patrón F4 (`data/corpus/actos_modificatorios/` JSONL + `.sha256`): el
  corpus es fuente de verdad versionada; el índice/derivado es regenerable. La huella
  permite verificar integridad y deduplicar re-ingestas.
- **Alternatives considered**: SQLite → añade motor y migraciones, innecesario para miles
  de registros leídos como lista. Rechazada.

## D6 — Deduplicación y validación de registros

- **Decision**: deduplicación por `id` estable (SHA-256 de `fuente + url` o de la clave
  normalizada `fuente|localidad|barrio|precio|area` cuando no hay URL) (FR-006).
  Validación de rangos: `estrato` ∈ 1-6, `area_m2` ≥ 36 (POT 555), `precio` y `area_m2`
  estrictamente positivos; registros sin precio o sin área se descartan (o marcan
  incompletos) con warning deduplicado (FR-006, FR-016).
- **Rationale**: evita contaminar el `precio_m2_referencia` con outliers/ruido y evita
  duplicados entre re-ingestas. Los descartes son deterministas (SC-001).
- **Alternatives considered**: no validar → precio de referencia distorsionado por
  outliers; deduplicar solo por URL → seeds sin URL se duplican. Rechazadas.

## D7 — Degradación del bloque

- **Decision**: si el corpus de mercado está vacío, ilegible o sin registros para la zona
  del lote → `estado="no_encontrado"` + warning `BLOQUE_SIN_DATO`. Un fallo de scraping
  en la INGESTA cae a seeds (no degrada el bloque); un fallo de scraping nunca ocurre en
  el camino de consulta del bloque (la consulta es local al corpus). El bloque nunca es
  fatal para el informe (FR-003). La ausencia de un campo puntual (p. ej. `estrato`)
  se reporta como `None` en ese campo con `interpretation` que lo indica (FR-015).
- **Rationale**: patrón F3/F8 de degradación por bloque; consistente con SC-003.
- **Alternatives considered**: propagar el fallo de scraping al informe → viola FR-003 y
  SC-003. Rechazada.

## D8 — Filtro territorial del corpus

- **Decision**: el bloque filtra los registros por la zona del lote usando `localidad` y
  `upl` derivadas del centroide (datos ya disponibles en `administrative_context`). Si hay
  registros para esa zona → `precio_m2_referencia` = mediana de `precio_m2` de las
  ofertas comparables; si no hay → `no_encontrado`. No se inventa un precio de otra zona
  (FR-015).
- **Rationale**: el precio de referencia debe ser de la zona del lote, no un promedio
  global de Bogotá (relevancia comercial, FR-014/FR-015).
- **Alternatives considered**: promedio global → distorsiona la factibilidad; precio de
  localidad vecina → infiere datos ausentes. Rechazadas.
