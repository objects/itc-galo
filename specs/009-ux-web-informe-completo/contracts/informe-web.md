# Contrato: Renderizado del Informe Completo en la Web

## Endpoint

`GET /proyectos/{id}` → `proyecto.html`

## Datos del template

El template `proyecto.html` recibe un `Proyecto` con `proyecto.informe` (dict serializado de `InformeFactibilidad`).

### Estructura del informe (campos del dict)

```python
informe = {
    "lot_identity": {
        "chip": str | None,
        "codigo_catastral": str,
        "manzana": str,
        "direccion_normalizada": str | None,
        "barrio": str | None,
        "geometry": {"type": "Polygon", "coordinates": [...]},
        "centroid": {"lat": float, "lng": float},
        "source_trace": {...}
    },
    "administrative_context": {
        "upl": {"codigo_upl": str, "nombre": str, ...} | None,
        "localidad": {"codigo": str, "nombre": str} | None,
        "clasificacion_suelo": "urbano" | "rural" | "urbano-rural" | None,
        "source_trace": {...}
    },
    "planning_constraints": {"estado": str, "interpretation": str, "source_trace": {...}, "dato": {...} | None},
    "market_context": {"estado": str, "interpretation": str, "source_trace": {...}, "dato": {...} | None},
    "environment_context": {"estado": str, "interpretation": str, "source_trace": {...}, "dato": {...} | None},
    "economic_context": {"estado": str, "interpretation": str, "source_trace": {...}, "dato": {...} | None},
    "geotechnical_risks": {"estado": str, "interpretation": str, "source_trace": {...}, "source_traces": [...], "dato": {...} | None},
    "socioeconomic_context": {"estado": str, "interpretation": str, "source_trace": {...}, "source_traces": [...], "dato": {...} | None},
    "regulatory_environment": {"estado": str, "interpretation": str, "source_trace": {...}, "source_traces": [...], "dato": {...} | None},
    "cultural_heritage": {"estado": str, "interpretation": str, "source_trace": {...}, "source_traces": [...], "dato": {...} | None},
    "transit_access": {"estado": str, "interpretation": str, "source_trace": {...}, "source_traces": [...], "dato": {...} | None},
    "catastro_data": {"estado": str, "interpretation": str, "source_trace": {...}, "source_traces": [...], "dato": {...} | None},
    "urbanistic_parameters": {"estado": str, "interpretation": str, "source_trace": {...}, "dato": {...} | None} | None,
    "public_space_context": {"estado": str, "interpretation": str, "source_trace": {...}, "dato": {...} | None} | None,
    "road_network_context": {"estado": str, "interpretation": str, "source_trace": {...}, "dato": {...} | None} | None,
    "nearby_facilities": {"estado": str, "interpretation": str, "source_trace": {...}, "source_traces": [...], "dato": {...} | None} | None,
    "normative_evidence": {
        "items": [{"articulo": str, "titulo": str, "libro": str, "parte": str, "texto_cita": str, "norma": str, "source_name": str}],
        "consulta": str,
        "sin_resultados": bool,
        "causa": str | None,
        "source_trace": {...}
    },
    "feasibility_score": {
        "score": int,
        "confidence": "high" | "medium" | "low",
        "reasons": [str],
        "rules_applied": [str]
    },
    "warnings": [{"codigo": str, "mensaje": str}],
    "llm_ready_summary": str | None,
    "query_timestamp": str
}
```

### Convenciones de renderizado

- **Badges de estado**: `disponible` → verde, `no_encontrado` → gris/ámbar.
- **Source trace**: se muestra `source_name`, `layer_id` y `data_vigencia` en texto pequeño.
- **Mapa**: Leaflet con GeoJSON del `lot_identity.geometry` y marcador en `lot_identity.centroid`.
- **Bloques None**: se omiten del renderizado (bloques opcionales que aún no se han integrado).

### Contrato de test

```python
# Verificaciones del test principal
assert "anillo-score" in response.text        # Score ring SVG
assert "llm_ready_summary" in response.text   # Resumen ejecutivo
assert "AAA0072LRYN" in response.text         # CHIP
assert "contenedor-mapa" in response.text     # Mapa Leaflet
assert "Reserva vial" in response.text        # Bloque planning_constraints
assert "Artículo 361" in response.text        # Evidencia normativa
assert "bloque-score" in response.text        # Score detallado
assert "advertencia" in response.text         # Warnings
```
