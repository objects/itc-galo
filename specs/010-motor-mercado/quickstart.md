# Quickstart: Motor de Mercado (F10)

Guía de validación end-to-end del bloque `market_dynamics` y la ingesta de mercado.
No incluye código de implementación (eso vive en `tasks.md`).

## Prerrequisitos

- Entorno Python con dependencias instaladas (`uv sync`).
- Sin requisito de red ni Ollama para los tests (fixtures `httpx.MockTransport` de
  `tests/conftest.py`, seeds deterministas).

## 1. Ingesta del corpus de mercado

```bash
# Corpus determinista (sin red): reproduce exactamente las seeds
uv run python -m app.ingesta.corpus mercado --solo-semillas

# Corpus híbrido (scraping + fallback a seeds)
uv run python -m app.ingesta.corpus mercado
```

**Esperado**: `data/corpus/mercado/mercado.jsonl` y `mercado.sha256` generados y
versionables; stdout reporta registros totales, fuentes y huella SHA-256. Re-ejecutar
la ingesta no duplica registros (deduplicación por `id` estable).

## 2. Bloque `market_dynamics` en el informe

Invocar `get_feasibility_report` (y `get_lot_summary_by_chip`) con un CHIP válido de
una zona con datos en el corpus.

**Esperado**:
- El bloque `market_dynamics` sigue el patrón `{estado, dato, interpretation,
  source_trace}` con `precio_m2_referencia`, `estrato`, `oferta_competidora` y
  `ritmo_absorcion` (o `None` por campo cuando faltan datos).
- `source_trace` con 5 campos (fuente primaria = corpus de mercado).
- El bloque `market_context` (valor de referencia catastral) permanece intacto.
- `feasibility_score.rules_applied` incluye `r_contexto_mercado`, `r_oferta_competidora`,
  `r_absorcion_mercado` cuando corresponden; el score sigue siendo determinista.

## 3. Degradación

- Con corpus vacío o sin registros para la zona → `market_dynamics.estado ==
  "no_encontrado"` + warning `BLOQUE_SIN_DATO`, sin afectar otros bloques.
- La falla del bloque de mercado no modifica el resto del informe (SC-003).

## 4. Tests

```bash
uv run pytest -q tests/contract/test_mercado.py tests/contract/test_ingesta_mercado.py tests/contract/test_scoring.py
uv run pytest -q   # suite completa (no-regresión)
```

**Esperado**: todos los tests pasan; los tests nuevos usan seeds deterministas y
`httpx.MockTransport`, sin red real ni Ollama.

## 5. Gate del feature

```bash
bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
```

**Esperado**: exit 0, resuelve `specs/010-motor-mercado` con todos los docs requeridos.

## Referencias

- Contrato del bloque y CLI: [contracts/market-dynamics.md](./contracts/market-dynamics.md)
- Modelo de datos: [data-model.md](./data-model.md)
- Decisiones de diseño: [research.md](./research.md)
- Especificación: [spec.md](./spec.md)
