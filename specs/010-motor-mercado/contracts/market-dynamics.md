# Contract: Bloque `market_dynamics` y subcomando CLI `mercado`

Contrato del bloque `market_dynamics` (motor de mercado, F10) y del subcomando de
ingesta `python -m app.ingesta.corpus mercado`.

## 1. Bloque `market_dynamics` en el informe

### 1.1 Shape del bloque

```json
{
  "estado": "disponible",
  "dato": {
    "precio_m2_referencia": 6450000.0,
    "estrato": 4,
    "oferta_competidora": [
      { "zona": "Chapinero", "conteo": 12, "precio_m2_promedio": 6400000.0, "estrato": 4 },
      { "zona": "Chapinero", "conteo": 5, "precio_m2_promedio": 7100000.0, "estrato": 5 }
    ],
    "ritmo_absorcion": { "unidades_mes": 8.5, "criterio": "antigüedad media de ofertas comparables" }
  },
  "interpretation": "Oferta de mercado en Chapinero: precio de referencia 6.45 M COP/m² (estrato 4), 17 ofertas comparables.",
  "source_trace": {
    "source_name": "corpus-mercado",
    "layer_id": "mercado",
    "service_url": "data/corpus/mercado/mercado.jsonl",
    "data_vigencia": "<huella del corpus>",
    "query_timestamp": "2026-09-03T00:00:00Z"
  }
}
```

### 1.2 Reglas de estado y degradación

- `estado == "disponible"`: hay al menos un registro comparable en el corpus para la
  zona del lote; `dato` poblado.
- `estado == "no_encontrado"`: corpus vacío, ilegible, o sin registros para la zona;
  `dato == null`, `interpretation` explica la ausencia, y se emite un warning
  `BLOQUE_SIN_DATO` (deduplicado).
- Campos puntuales ausentes (p. ej. `estrato` no derivable): el campo va en `None` con
  `interpretation` que lo indica; NO se inventan valores (FR-015).
- La degradación es independiente: no afecta a otros bloques ni al resto del informe
  (FR-003, SC-003).

### 1.3 Trazabilidad (FR-010)

`source_trace` siempre lleva los 5 campos obligatorios. `source_name` identifica el
corpus de mercado; `data_vigencia` es la huella del corpus (congelada, no un reloj en
runtime). La proveniencia por registro (portal de origen) vive dentro de `dato`, no como
trazas adicionales fabricadas.

## 2. Subcomando CLI `mercado`

### 2.1 Invocación

```text
python -m app.ingesta.corpus mercado [--solo-semillas] [--solo-scrape]
```

- `mercado` (sin flags): pipeline híbrido — intenta scraping de los portales
  configurados; ante fallo de red / bloqueo ToS / sin datos, cae a seeds deterministas.
- `--solo-semillas`: genera el corpus SOLO con seeds deterministas (sin red), para
  reproducción exacta y tests.
- `--solo-scrape`: solo scraping, sin fallback a seeds (para diagnóstico).

### 2.2 Comportamiento

1. Lee/descarga registros (scraping y/o seeds) según los flags.
2. Valida cada registro (estrato 1-6, área ≥ 36 m², precio/área positivos) y descarta
   los inválidos con warning deduplicado (FR-006).
3. Deduplica por `id` estable (FR-006).
4. Escribe `data/corpus/mercado/mercado.jsonl` y `mercado.sha256` (FR-008, FR-020).
5. Reporta: nº de registros consolidados, fuentes usadas, huella, y descartes.

### 2.3 Salida

Resumen en consola (stdout) con: registros totales, por fuente, descartes, y la huella
SHA-256 resultante. Código de salida 0 en éxito; distinto de 0 en error de escritura
o corpus irrecuperable (patrón `descargar`/`acto`).

## 3. No-regresión

- Las 7 tools MCP mantienen su contrato intacto (FR-013, SC-004).
- `InformeFactibilidad` solo gana el campo aditivo `market_dynamics`; los bloques
  existentes (incluido `market_context` = valor de referencia catastral) no cambian.
- El scoring conserva la fórmula base F3; solo añade 3 reglas `r_*` sobre el bloque
  nuevo (SC-007).
