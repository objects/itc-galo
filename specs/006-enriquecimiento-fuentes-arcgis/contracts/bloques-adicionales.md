# Contrato: Bloques adicionales del informe de factibilidad (Feature 6)

**Feature**: [spec.md](spec.md) | **Fecha**: 2026-08-17

## Bloques nuevos en `get_feasibility_report`

Los 5 bloques se añaden al contrato existente de F3 (10 bloques → 15 bloques). La tool `get_feasibility_report` NO cambia su firma; solo se enriquece la respuesta.

### geotechnical_risks

```json
{
  "estado": "disponible | no_encontrado",
  "dato": {
    "amenaza_movimientos": "string | null",
    "geologia": "string | null",
    "respuesta_sismica": "string | null",
    "zonificacion_geotecnica": "string | null",
    "nivel_amenaza": "alto | medio | bajo | desconocido | null"
  },
  "interpretation": "string",
  "source_trace": {
    "source_name": "Gestión de Riesgos — Amenaza movimientos en masa urbano",
    "layer_id": "2",
    "service_url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/emergencias/gestionriesgos/MapServer",
    "data_vigencia": "2023",
    "query_timestamp": "2026-08-17T00:00:00Z"
  }
}
```

### socioeconomic_context

```json
{
  "estado": "disponible | no_encontrado",
  "dato": {
    "estrato": "integer | null",
    "uso_predominante": "string | null",
    "altura_media": "float | null",
    "mediana_avaluo": "float | null"
  },
  "interpretation": "string",
  "source_trace": {
    "source_name": "Estratificación socioeconómica",
    "layer_id": "1",
    "service_url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/ordenamientoterritorial/estratificacion/MapServer",
    "data_vigencia": "2024",
    "query_timestamp": "2026-08-17T00:00:00Z"
  }
}
```

### regulatory_environment

```json
{
  "estado": "disponible | no_encontrado",
  "dato": {
    "licencias_encontradas": "integer | null",
    "zona_plusvalia": "boolean | null",
    "nombre_plan_plusvalia": "string | null"
  },
  "interpretation": "string",
  "source_trace": {
    "source_name": "Licencias de construcción aprobadas",
    "layer_id": "3",
    "service_url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/ordenamientoterritorial/licenciasconstruccion/MapServer",
    "data_vigencia": "2025",
    "query_timestamp": "2026-08-17T00:00:00Z"
  }
}
```

### cultural_heritage

```json
{
  "estado": "disponible | no_encontrado",
  "dato": {
    "bic_cercano": "boolean | null",
    "nombre_bic": "string | null",
    "zona_arqueologica": "boolean | null"
  },
  "interpretation": "string",
  "source_trace": {
    "source_name": "Bienes de Interés Cultural",
    "layer_id": "1",
    "service_url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/recreaciondeporte/bienesinterescultural/MapServer",
    "data_vigencia": "2023",
    "query_timestamp": "2026-08-17T00:00:00Z"
  }
}
```

### transit_access

```json
{
  "estado": "disponible | no_encontrado",
  "dato": {
    "estaciones_transmilenio": "integer | null",
    "paraderos_sitp": "integer | null",
    "estaciones_metro": "integer | null",
    "estacion_cercana": "string | null"
  },
  "interpretation": "string",
  "source_trace": {
    "source_name": "Transporte público — Estaciones TransMilenio",
    "layer_id": "1",
    "service_url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/movilidad/transportepublico/MapServer",
    "data_vigencia": "2025",
    "query_timestamp": "2026-08-17T00:00:00Z"
  }
}
```

### feasibility_score (extendido)

Las `rules_applied` incluyen los códigos nuevos:
- `r_contexto_socio` — contexto socioeconómico disponible
- `r_acceso_movilidad` — acceso a transporte público con estaciones de alta capacidad
- `r_riesgo_geotec_alto` — riesgo geotecnico alto
- `r_patrimonio_cultural` — patrimonio cultural cercano

### warnings (extendido)

Se añade el código `BLOQUE_DEGRADADO` para bloques que fallan completamente (todas las capas del bloque retornan error):
```json
{
  "codigo": "BLOQUE_DEGRADADO",
  "mensaje": "Bloque <nombre> degradado: error al consultar la fuente."
}
```
