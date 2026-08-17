# Data Model: Enriquecimiento del Informe de Factibilidad con 5 Nuevas Fuentes ArcGIS

**Feature**: [spec.md](spec.md) | **Fecha**: 2026-08-17

## Modelos de datos (app/models.py)

Los 5 modelos de datos representan la información cruda de cada categoría. Los 5 wrappers de bloque siguen el patrón `{estado, dato, interpretation, source_trace}` de F3.

### 1. RiesgoGeotecnicos

```python
class RiesgoGeotecnicos(BaseModel):
    amenaza_movimientos: str | None = None    # Clasificación layer 2
    geologia: str | None = None               # Clasificación layer 5
    respuesta_sismica: str | None = None      # Clasificación layer 7
    zonificacion_geotecnica: str | None = None # Clasificación layer 8
    nivel_amenaza: Literal["alto", "medio", "bajo", "desconocido"] | None = None
```

**Campos**: 4 clasificaciones textuales de las capas + 1 nivel inferido.
**Degradación**: cada campo se pobló solo si la capa correspondiente respondió; `None` si falló.

### 2. ContextoSocioeconomico

```python
class ContextoSocioeconomico(BaseModel):
    estrato: int | None = None           # Capa estratificacion [1]
    uso_predominante: str | None = None  # Capa usopredominante [0]
    altura_media: float | None = None    # Capa alturamedia [0]
    mediana_avaluo: float | None = None  # Capa medianaavaluo [0]
```

**Campos**: 1 entero (estrato), 1 texto (uso), 2 floats (altura y avalúo).
**Degradación**: cada campo se pobló solo si la capa correspondiente respondió.

### 3. EntornoRegulatorio

```python
class EntornoRegulatorio(BaseModel):
    licencias_encontradas: int | None = None     # Conteo layer 3
    zona_plusvalia: bool | None = None           # Presencia layer 1
    nombre_plan_plusvalia: str | None = None     # Nombre del plan
```

**Campos**: 1 entero (conteo), 1 booleano (plusvalía), 1 texto (nombre del plan).
**Degradación**: cada campo se pobló solo si la capa correspondiente respondió.

### 4. PatrimonioCultural

```python
class PatrimonioCultural(BaseModel):
    bic_cercano: bool | None = None          # Presencia layer 1
    nombre_bic: str | None = None            # Nombre del BIC
    zona_arqueologica: bool | None = None    # Presencia layer 9
```

**Campos**: 2 booleanos (BIC, arqueología), 1 texto (nombre del BIC).
**Degradación**: cada campo se pobló solo si la capa correspondiente respondió.

### 5. AccesoMovilidad

```python
class AccesoMovilidad(BaseModel):
    estaciones_transmilenio: int | None = None  # Conteo layer 1, radio 800 m
    paraderos_sitp: int | None = None          # Conteo layer 5, radio 500 m
    estaciones_metro: int | None = None        # Conteo layer 0, radio 800 m
    estacion_cercana: str | None = None        # Nombre de la más cercana
```

**Campos**: 3 enteros (conteos), 1 texto (estación más cercana).
**Degradación**: cada campo se pobló solo si la capa correspondiente respondió.

### Wrappers de bloque

Cada wrapper sigue el patrón de F3:

```python
class BloqueRiesgosGeotecnicos(BaseModel):
    estado: EstadoDato
    dato: RiesgoGeotecnicos | None = None
    interpretation: str
    source_trace: SourceTrace

class BloqueContextoSocioeconomico(BaseModel):
    estado: EstadoDato
    dato: ContextoSocioeconomico | None = None
    interpretation: str
    source_trace: SourceTrace

class BloqueEntornoRegulatorio(BaseModel):
    estado: EstadoDato
    dato: EntornoRegulatorio | None = None
    interpretation: str
    source_trace: SourceTrace

class BloquePatrimonioCultural(BaseModel):
    estado: EstadoDato
    dato: PatrimonioCultural | None = None
    interpretation: str
    source_trace: SourceTrace

class BloqueAccesoMovilidad(BaseModel):
    estado: EstadoDato
    dato: AccesoMovilidad | None = None
    interpretation: str
    source_trace: SourceTrace
```

### InformeFactibilidad (extendido)

El modelo raíz se extiende con los 5 campos nuevos:

```python
class InformeFactibilidad(BaseModel):
    # ... 10 bloques de F3 ...
    geotechnical_risks: BloqueRiesgosGeotecnicos
    socioeconomic_context: BloqueContextoSocioeconomico
    regulatory_environment: BloqueEntornoRegulatorio
    cultural_heritage: BloquePatrimonioCultural
    transit_access: BloqueAccesoMovilidad
    # ... feasibility_score, warnings, query_timestamp ...
```

## Scoring extendido (app/scoring.py)

### Bloques evaluables (11 total)

```python
BLOQUES_EVALUABLES = (
    "administrative_context",    # F3
    "planning_constraints",      # F3
    "market_context",            # F3
    "environment_context",       # F3
    "economic_context",          # F3
    "geotechnical_risks",        # F6
    "socioeconomic_context",     # F6
    "regulatory_environment",    # F6
    "cultural_heritage",         # F6
    "transit_access",            # F6
    "normative_evidence",        # F3
)
```

### Reglas nuevas

| Regla | Tipo | Puntos | Condición |
|-------|------|--------|-----------|
| `r_contexto_socio` | positiva | +5 | `socioeconomic_context.estado == "disponible"` |
| `r_acceso_movilidad` | positiva | +5 | `transit_access.estado == "disponible"` y al menos una estación TM o Metro |
| `r_riesgo_geotec_alto` | negativa | −10 | `geotechnical_risks.dato.nivel_amenaza == "alto"` |
| `r_patrimonio_cultural` | negativa | −10 | BIC cercano o zona arqueológica |

### Confidence recalculado

```python
def _confidence_por_cobertura(bloques) -> Literal["high", "medium", "low"]:
    disponibles = _contar_bloques_disponibles(bloques)  # 11 bloques
    if disponibles >= 9: return "high"
    if disponibles >= 5: return "medium"
    return "low"
```

## Constantes del provider (app/providers/arcgis.py)

### Vigencias por tema

```python
VIGENCIAS_DEFAULT = {
    # ... F3/F5 ...
    "geotecnia_amenaza": "2023",
    "geotecnia_geologia": "2023",
    "geotecnia_sismo": "2023",
    "geotecnia_zonificacion": "2023",
    "estratificacion": "2024",
    "usopredominante": "2024",
    "alturamedia": "2024",
    "medianaavaluo": "2024",
    "licencias": "2025",
    "plusvalia": "2024",
    "bic": "2023",
    "planarqueologico": "2023",
    "transmilenio": "2025",
    "sitp": "2025",
    "metro": "2025",
}
```

### Capas y layer IDs

```python
_CAPAS_CANONICOS = {
    # ... F3/F5 ...
    "geotecnia_amenaza": "2",
    "geotecnia_geologia": "5",
    "geotecnia_sismo": "7",
    "geotecnia_zonificacion": "8",
    "estratificacion": "1",
    "usopredominante": "0",
    "alturamedia": "0",
    "medianaavaluo": "0",
    "licencias": "3",
    "plusvalia": "1",
    "bic": "1",
    "planarqueologico": "9",
    "transmilenio": "1",
    "sitp": "5",
    "metro": "0",
}
```
