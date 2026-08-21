# Quickstart: Parámetros Urbanísticos del Lote (Feature 8)

**Feature**: [spec.md](spec.md) | **Fecha**: 2026-08-20

## Visión general

Feature 8 añade un bloque `urbanistic_parameters` al informe de factibilidad que consulta los parámetros urbanísticos del lote desde dos fuentes:
1. **SINUPOT/SDP** (tratamiento espacial) — `sinu.sdp.gov.co/serverp/rest/services/POT555/NORMA_URBANÍSTICA_Y_OT/MapServer` layer 2
2. **RAG normativo** (COS, CUS, altura, retiros, estacionamientos) — colección `decreto_555_2021` existente

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `app/providers/sdp.py` | **NUEVO** — Provider SINUPOT/SDP |
| `app/models.py` | 5 modelos nuevos + 1 wrapper de bloque + extensión de `InformeFactibilidad` y `BloquesEvaluables` |
| `app/main.py` | Tercera ronda de consultas paralelas + construcción del bloque `urbanistic_parameters` en `get_feasibility_report` y `get_lot_summary_by_chip` |
| `app/scoring.py` | 3 reglas nuevas + actualización de `BLOQUES_EVALUABLES` + actualización de `BloquesEvaluables` + umbrales de confidence |
| `tests/contract/test_urbanistic_parameters.py` | **NUEVO** — Tests del bloque y scoring |

## Verificación

### 1. Lint y tipos

```bash
cd /home/elkingomez/Repositorios/OpenCode/itc-galo
uv run ruff check app/ tests/
uv run pyright app/ tests/
```

### 2. Tests

```bash
uv run pytest tests/ -v
```

### 3. Scoring determinístico (SC-003)

Verificar que `calcular_score()` con los mismos `BloquesEvaluables` siempre retorna el mismo `FeasibilityScore`:

```python
from app.scoring import calcular_score, BloquesEvaluables
# ... construir bloques_evaluables con urbanistic_parameters ...
score1 = calcular_score(bloques_evaluables)
score2 = calcular_score(bloques_evaluables)
assert score1 == score2  # SC-003
```

### 4. Degradación independiente (SC-004)

Verificar que la falla de SDP no afecta otros bloques:

```python
# SDP falla → urbanistic_parameters.no_encontrado + warning
# Resto del informe se genera normalmente
assert reporte["urbanistic_parameters"]["estado"] == "no_encontrado"
assert any(w["codigo"] == "BLOQUE_DEGRADADO" for w in reporte["warnings"])
# Los otros 15 bloques no se ven afectados
```

### 5. No-regresión (SC-005)

```bash
uv run pytest tests/smoke/ -v  # 7 tools registradas
uv run pytest tests/contract/ -v  # Todos los tests F1/F2/F3/F4/F6/F7 pasan
```

## Modelo de datos rápido

```python
# Bloque urbanistic_parameters
{
    "estado": "disponible",
    "dato": {
        "tratamiento": {"denominacion": "Desarrollo", "codigo_capa": None},
        "edificabilidad": {"cos": 0.70, "cus": 2.80, "altura_maxima_m": 24.0},
        "retiros": {"frontal_m": 5.0, "laterales_m": 3.0, "posteriores_m": 4.0},
        "estacionamientos": {"requeridos": 4, "criterio": "1 por cada 60 m²"}
    },
    "interpretation": "Tratamiento urbanístico del lote: Desarrollo...",
    "source_trace": {"source_name": "SINUPOT — Norma Urbanística y OT", ...}
}
```

## Scoring extension

```python
# Reglas nuevas en calcular_score()
+10  r_parametros_urbanisticos    # Tratamiento + edificabilidad disponibles
+5   r_estacionamientos_calculados # Estacionamientos > 0
-15  r_tratamiento_conservacion   # Tratamiento == "Conservación"

# Bloques evaluables: 13 (12 actuales + urbanistic_parameters)
# Confidence: high ≥ 10, medium 5-9, low ≤ 4
```
