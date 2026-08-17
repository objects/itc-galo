# Contrato: Bloque catastro_data del informe de factibilidad (Feature 7)

**Feature**: [spec.md](spec.md) | **Fecha**: 2026-08-17

## Bloque catastro_data en `get_feasibility_report`

El bloque `catastro_data` se añade al contrato existente de F3/F6 (15 bloques → 16 bloques). La tool `get_feasibility_report` NO cambia su firma; solo se enriquece la respuesta.

```json
{
  "estado": "disponible | no_encontrado",
  "dato": {
    "construccion": {
      "codigo": "string | null",
      "pisos": "float | null",
      "sotanos": "float | null",
      "semisotanos": "float | null",
      "altura": "float | null",
      "elevacion_cota": "float | null",
      "mejoras": "float | null",
      "voladizo": "float | null"
    },
    "manzana": {
      "codigo_manzana": "string | null",
      "codigo_seccion": "string | null"
    },
    "densidad_predial": {
      "codigo_manzana": "string | null",
      "num_predios": "float | null",
      "ano": "float | null"
    },
    "variacion_area": {
      "codigo_manzana": "string | null",
      "area_inicial_m2": "float | null",
      "area_final_m2": "float | null",
      "variacion_m2": "float | null",
      "variacion_porcentual": "float | null",
      "periodo": "string | null"
    },
    "sector_catastral": "string | null"
  },
  "interpretation": "string",
  "source_trace": {
    "source_name": "Catastro — Construcción",
    "layer_id": "0",
    "service_url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/catastro/construccion/MapServer",
    "data_vigencia": "2024",
    "query_timestamp": "2026-08-17T00:00:00Z"
  }
}
```

### Capas consultadas

| Clave | Capa | Layer ID | URL |
|-------|------|----------|-----|
| construccion | catastro/construccion | 0 | `{RAIZ_ARCGIS}/catastro/construccion/MapServer` |
| manzana_catastro | catastro/manzana | 0 | `{RAIZ_ARCGIS}/catastro/manzana/MapServer` |
| densidad_predial | catastro/densidadpredialmz | 0 | `{RAIZ_ARCGIS}/catastro/densidadpredialmz/MapServer` |
| variacion_area | catastro/variacionareaconstruida | 1 | `{RAIZ_ARCGIS}/catastro/variacionareaconstruida/MapServer` |
| sector_catastral | catastro/sectorcatastral | 0 | `{RAIZ_ARCGIS}/catastro/sectorcatastral/MapServer` |

### Campos por capa

**construccion** (layer 0): `CONCODIGO` (código), `CONNPISOS` (pisos), `CONNSOTANO` (sotanos), `CONTSEMIS` (semisotanos), `CONALTURA` (altura), `CONELEVACI` (elevación cota), `CONMEJORA` (mejoras), `CONVOLADIZ` (voladizo).

**manzana_catastro** (layer 0): `MANCODIGO` (código manzana), `SECCODIGO` (código sección).

**densidad_predial** (layer 0): `MANCODIGO` (código manzana), `N_PREDIOS` (número de predios), `ANO` (año).

**variacion_area** (layer 1): `MANCODIGO` (código manzana), `AC_M2_MZ_INIC` (área inicial m²), `AC_M2_MZ_FIN` (área final m²), `VAR_M2_AC` (variación m²), `PVAR_M2_AC` (variación porcentual), `PERIODO` (periodo).

**sector_catastral** (layer 0): `SCANOMBRE` (nombre del sector).

### Bloque catastro_data en `get_lot_summary_by_chip`

El resumen del lote incluye `catastro_data` con el mismo shape:

```json
{
  "catastro_data": {
    "estado": "disponible | no_encontrado",
    "dato": {
      "construccion": "object | null",
      "manzana": "object | null",
      "densidad_predial": "object | null",
      "variacion_area": "object | null",
      "sector_catastral": "string | null"
    },
    "source_trace": {
      "source_name": "Catastro — Construcción",
      "layer_id": "0",
      "service_url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/catastro/construccion/MapServer",
      "data_vigencia": "2024",
      "query_timestamp": "2026-08-17T00:00:00Z"
    }
  }
}
```

### feasibility_score (extendido)

El `confidence` se recalcula sobre **12 bloques evaluables** (11 de F3/F6 + 1 de F7: `catastro_data`).

### warnings (sin cambios)

Se reutilizan los códigos existentes `BLOQUE_SIN_DATO` y `BLOQUE_DEGRADADO`.
