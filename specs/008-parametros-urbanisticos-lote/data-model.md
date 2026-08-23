# Data Model: Parámetros Urbanísticos del Lote (Feature 8)

**Feature**: [spec.md](spec.md) | **Fecha**: 2026-08-20

## Modelos de datos (app/models.py)

Los 5 modelos representan los parámetros urbanísticos del lote. El wrapper de bloque sigue el patrón `{estado, dato, interpretation, source_trace}` de F3/F6/F7.

### 1. TratamientoUrbanistico

```python
class TratamientoUrbanistico(BaseModel):
    """Tratamiento urbanístico del lote (SINUPOT layer 2)."""
    denominacion: str                    # Nombre legible del tratamiento
    codigo_capa: str | None = None       # Código del atributo en la capa SINUPOT
```

**Campos**: 1 string (denominación), 1 string opcional (código de capa).
**Fuente**: SDP SINUPOT layer 2 (consulta espacial por punto).
**Degradación**: el modelo solo se construye cuando SDP responde con al menos 1 feature.

### 2. ParametrosEdificabilidad

```python
class ParametrosEdificabilidad(BaseModel):
    """Parámetros numéricos de edificabilidad (RAG art. 281 + SDP layer 14)."""
    cos: float | None = None             # Coeficiente de Ocupación del Suelo
    cus: float | None = None             # Coeficiente de Utilización del Suelo
    altura_maxima_m: float | None = None # Altura máxima permitida en metros
```

**Campos**: 3 floats opcionales.
**Fuentes**: RAG normativo (art. 281) como fuente primaria; SDP layer 14 como complementaria.
**Degradación**: cada campo se pobló solo si el RAG o la capa 14 lo retornaron; `None` si no están disponibles.

### 3. RetirosLote

```python
class RetirosLote(BaseModel):
    """Retiros obligatorios del lote (RAG Anexo 5)."""
    frontal_m: float | None = None       # Retiro frontal en metros
    laterales_m: float | None = None     # Retiros laterales en metros
    posteriores_m: float | None = None   # Retiro posterior en metros
```

**Campos**: 3 floats opcionales.
**Fuente**: RAG normativo (Anexo 5 Manual de Normas Comunes).
**Degradación**: cada campo se pobló solo si el RAG lo retornó; `None` si no están disponibles.

### 4. EstacionamientosRequeridos

```python
class EstacionamientosRequeridos(BaseModel):
    """Estacionamientos requeridos por el lote (RAG art. 389)."""
    requeridos: int | None = None        # Cantidad de estacionamientos
    criterio: str | None = None          # Criterio de cálculo (texto del RAG)
```

**Campos**: 1 entero opcional + 1 string opcional.
**Fuente**: RAG normativo (art. 389).
**Degradación**: ambos campos `None` si el RAG no retornó información.

### 5. ParametrosUrbanisticos

```python
class ParametrosUrbanisticos(BaseModel):
    """Contenedor de los parámetros urbanísticos del lote."""
    tratamiento: TratamientoUrbanistico | None = None
    edificabilidad: ParametrosEdificabilidad | None = None
    retiros: RetirosLote | None = None
    estacionamientos: EstacionamientosRequeridos | None = None
```

**Relación**: `ParametrosUrbanisticos` es el `dato` del bloque `urbanistic_parameters`. Cuando `tratamiento` es `None`, el bloque tiene estado `no_encontrado`. Cuando `tratamiento` está presente pero los sub-modelos son `None`, el bloque tiene estado `disponible` con campos numéricos ausentes.

### Wrapper de bloque

```python
class BloqueParametrosUrbanisticos(BaseModel):
    """Bloque urbanistic_parameters con el patron {estado, dato, interpretation, source_trace}."""
    estado: EstadoDato
    dato: ParametrosUrbanisticos | None = None
    interpretation: str
    source_trace: SourceTrace
```

**Patrón**: idéntico a `BloqueRiesgosGeotecnicos`, `BloqueCatastroData`, etc. de F3/F6/F7.

## Modelo de entrada de scoring (app/scoring.py)

### BloquesEvaluables — extensión

```python
class BloquesEvaluables(BaseModel):
    """Estructura tipada de los bloques evaluables del score."""
    # ... 12 campos existentes (F3/F6/F7) ...
    urbanistic_parameters: BloqueParametrosUrbanisticos  # NUEVO F8
```

**Total de campos**: 13 (12 existentes + 1 nuevo).

### Confidence — thresholds actualizados

| Nivel | Disponibles | Criterio |
|-------|-------------|----------|
| `high` | ≥ 10 | Cobertura amplia |
| `medium` | 5–9 | Cobertura parcial |
| `low` | ≤ 4 | Cobertura mínima |

**Decisión**: los thresholds se actualizan de los 11 actuales (F3+F6+F7) a 13 (F3+F6+F7+F8). Los umbrales `high ≥ 5`, `medium 3-4`, `low ≤ 2` se actualizan a `high ≥ 10`, `medium 5-9`, `low ≤ 4` para reflejar la mayor cantidad de bloques.

## Reglas de scoring (app/scoring.py)

### Reglas positivas nuevas

| Constante | Puntos | Condición | Código |
|-----------|--------|-----------|--------|
| `PUNTOS_PARAMETROS_URBANISTICOS` | +10 | `urbanistic_parameters.estado == "disponible"` y `dato.tratamiento is not None` y `dato.edificabilidad is not None` | `r_parametros_urbanisticos` |
| `PUNTOS_ESTACIONAMIENTOS` | +5 | `urbanistic_parameters.estado == "disponible"` y `dato.estacionamientos.requeridos is not None` y `dato.estacionamientos.requeridos > 0` | `r_estacionamientos_calculados` |

### Reglas negativas nuevas

| Constante | Puntos | Condición | Código |
|-----------|--------|-----------|--------|
| `PENALIZACION_CONSERVACION` | −15 | `urbanistic_parameters.estado == "disponible"` y `dato.tratamiento.denominacion == "Conservación"` | `r_tratamiento_conservacion` |

**Nota**: la penalización de −15 es la más fuerte del scoring (junto con reserva vial). Solo se activa para tratamiento "Conservación" exacto (FR-015: no se infiere reglas ausentes).

## Relaciones con entidades existentes

- **SourceTrace**: el bloque `urbanistic_parameters` tiene UN solo `SourceTrace`, que documenta la fuente primaria del tratamiento espacial (SINUPOT/SDP, layer 2). Los datos del RAG normativo NO generan un source_trace adicional en el contrato (patrón F6/F7: un solo source_trace por bloque); su proveniencia queda registrada en `interpretation` (mención de la norma/artículo consultado) y en los warnings del informe cuando el RAG falla o se degrada.
- **UPL**: la consulta RAG para parámetros urbanísticos puede filtrar por UPL (opcional). El tratamiento espacial NO depende de la UPL (consulta puramente espacial).
- **InformeFactibilidad**: el bloque se añade como campo `urbanistic_parameters` en el modelo `InformeFactibilidad`.
- **Bloques existentes**: sin cambios a los 15 bloques actuales (F3/F6/F7). Solo se añade el bloque 16.
