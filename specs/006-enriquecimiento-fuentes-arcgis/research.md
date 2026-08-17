# Research: Enriquecimiento del Informe de Factibilidad con 5 Nuevas Fuentes ArcGIS

**Fase**: Phase 0 del comando `/speckit.plan` | **Fecha**: 2026-08-17
**Feature**: [spec.md](spec.md) | **Estado**: Resuelto — todas las decisiones zanjadas

## Alcance

Esta investigación documenta los 15 servicios ArcGIS REST utilizados por la Feature 6 para enriquecer el informe de factibilidad con 5 nuevos bloques de contexto. Cada servicio fue verificado en vivo contra los endpoints públicos de Catastro Bogotá.

---

## Hallazgos: Servicios ArcGIS REST

### H1. Bloque `geotechnical_risks` — emergencias/gestionriesgos (4 capas)

La capa `emergencias/gestionriesgos/MapServer` es un MapServer con múltiples feature layers. Las 4 capas relevantes son:

| Clave | Layer ID | Nombre | SR | Campos clave |
|-------|----------|--------|----|--------------|
| `geotecnia_amenaza` | 2 | Amenaza movimientos en masa urbano | 102100 | `GEOTECNIA`, `NOMBRE`, `TIPO`, `DESCRIPCION` |
| `geotecnia_geologia` | 5 | Geología Rural | 102100 | `GEOTECNIA`, `NOMBRE`, `TIPO` |
| `geotecnia_sismo` | 7 | Respuesta Sísmica | 102100 | `GEOTECNIA`, `NOMBRE`, `TIPO` |
| `geotecnia_zonificacion` | 8 | Zonificación Geotécnica | 102100 | `GEOTECNIA`, `NOMBRE`, `TIPO`, `DESCRIPCION` |

- **SR 102100** (Web Mercator): las consultas usan `inSR=4326` (ArcGIS REST convierte internamente).
- **Vigencia declarada**: 2023.
- **Consulta**: punto con `esriSpatialRelIntersects`; la capa es poligonal.
- **Inferencia de nivel de amenaza**: se extrae del campo `GEOTECNIA` o `TIPO` con clasificación por palabras clave (`alto`, `medio`, `bajo`).

### H2. Bloque `socioeconomic_context` — 4 capas de contexto socioeconómico

| Clave | Layer ID | Servicio | SR | Campos clave |
|-------|----------|----------|----|--------------|
| `estratificacion` | 1 | `ordenamientoterritorial/estratificacion` | PCS_CarMAGBOG | `ESTRATO`, `ESTRATA`, `ESTRAT` |
| `usopredominante` | 0 | `catastro/usopredominante` | 4326 | `GRUPOUSOECON`, `USO`, `GRUPO` |
| `alturamedia` | 0 | `catastro/alturamedia` | 4326 | `ALTURA`, `ALTURAMEDIA`, `PISOS` |
| `medianaavaluo` | 0 | `catastro/medianaavaluocatastral` | 4326 | `MED_VALOR_CATAS`, `VALOR`, `AVALUO` |

- **SR 4326** para las 3 capas de catastro: consultas directas con `inSR=4326`.
- **SR PCS_CarMAGBOG** para estratificación: `inSR=4326` funciona (ArcGIS REST convierte).
- **Vigencia declarada**: 2024.
- Cada sub-bloque degrada independientemente (4 consultas en paralelo con `return_exceptions=True`).

### H3. Bloque `regulatory_environment` — licencias y plusvalía

| Clave | Layer ID | Servicio | SR | Campos clave |
|-------|----------|----------|----|--------------|
| `licencias` | 3 | `ordenamientoterritorial/licenciasconstruccion` | PCS_CarMAGBOG | Conteo de features |
| `plusvalia` | 1 | `ordenamientoterritorial/plusvalia` | PCS_CarMAGBOG | `NOMBRE`, `CODIGO_PLAN_PARCIAL`, `NOMBRE_PLAN` |

- **SR PCS_CarMAGBOG**: `inSR=4326` funciona para ambas capas.
- **Vigencia declarada**: 2025 (licencias), 2024 (plusvalía).
- Licencias: el conteo de features indica la actividad de desarrollo en el entorno.
- Plusvalía: presencia/ausencia + nombre del plan parcial.

### H4. Bloque `cultural_heritage` — BIC y plan arqueológico

| Clave | Layer ID | Servicio | SR | Campos clave |
|-------|----------|----------|----|--------------|
| `bic` | 1 | `recreaciondeporte/bienesinterescultural` | 102100 | `NOMBRE`, `CATEGORIA`, `DENOMINACION` |
| `planarqueologico` | 9 | `recreaciondeporte/planarqueologico` | 102233 | Presencia/ausencia |

- **SR 102100** para BIC, **SR 102233** para plan arqueológico: `inSR=4326` funciona.
- **Vigencia declarada**: 2023.
- BIC: presencia/ausencia + nombre del bien.
- Plan arqueológico: presencia/ausencia (booleano).

### H5. Bloque `transit_access` — transporte público y Metro

| Clave | Layer ID | Servicio | SR | Radio | Campos nombre |
|-------|----------|----------|----|-------|---------------|
| `transmilenio` | 1 | `movilidad/transportepublico` | 102100 | 800 m | `ETRNOMBRE`, `NOMBRE`, `ESTACION` |
| `sitp` | 5 | `movilidad/transportepublico` | 102100 | 500 m | `PSINOMBRE`, `NOMBRE`, `PARADERO` |
| `metro` | 0 | `movilidad/metrobogota` | 102100 | 800 m | `REFNAME`, `NOMBRE`, `ESTACION` |

- **SR 102100** para las 3 capas: `inSR=4326` funciona.
- **Vigencia declarada**: 2025.
- **Radios**: 800 m para TransMilenio y Metro (estaciones de alta capacidad), 500 m para SITP (paraderos de cercanía).
- **Consulta con radio**: `distance=<radio_m>&units=esriSRUnit_Meter` (patrón `consultar_obras_publicas_radio` de F3).
- **Estación más cercana**: se extrae del primer feature del resultado de TransMilenio o Metro.

---

## Decisiones

### D1. Degradación por sub-bloque dentro de cada bloque

**Decision**: Cada bloque que consulta múltiples capas ejecuta `asyncio.gather(*tareas, return_exceptions=True)`. Si una capa individual falla (5xx), su sub-bloque queda en `None` pero las demás capas que respondieron se reportan. El bloque整体 mantiene `estado: "disponible"` si al menos un sub-bloque tiene datos; si todos fallan, `estado: "no_encontrado"` con warning `BLOQUE_DEGRADADO`.

**Rationale**: Cumple FR-008/FR-009: un 5xx de una capa no degrada todo el bloque ni se mapea silenciosamente a `no_encontrado` cuando hay datos de otras capas. Es la misma semántica de F3 pero a nivel de sub-bloque.

### D2. Configuración de radios de influencia

**Decision**: Los radios (800 m TM/Metro, 500 m SITP) se definen como constantes en `app/providers/arcgis.py` (constantes del módulo). No son parámetros del contrato de la tool.

**Rationale**: Los radios son criterios técnicos de planificación urbana (distancia de caminata razonable: 800 m ≈ 10 min, 500 m ≈ 6 min); exponerlos como parámetros complicaría el contrato sin beneficio para el usuario del MCP.

### D3. Scoring extendido con 4 reglas nuevas

**Decision**: El `feasibility_score` añade:
- **Positivas**: contexto socioeconómico disponible `+5` (`r_contexto_socio`); acceso a movilidad con al menos una estación de alta capacidad `+5` (`r_acceso_movilidad`).
- **Negativas**: riesgo geotecnico alto `−10` (`r_riesgo_geotec_alto`); patrimonio cultural cercano (BIC o zona arqueológica) `−10` (`r_patrimonio_cultural`).
- **Confidence recalculado** sobre 11 bloques: `high` ≥ 9, `medium` 5–8, `low` ≤ 4.

**Rationale**: Las reglas positivas incentivan la disponibilidad de datos (más datos = mejor score); las negativas penalizan factores de riesgo reales identificados en las fuentes. Los valores son conservadores (5/10 puntos) para no dominar el score base de F3.

### D4. Trazabilidad con source_trace por bloque

**Decision**: Cada bloque nuevo usa como `source_trace` el de la primera capa consultada del bloque (la de mayor prioridad o la primera en la lista). Cuando todas las capas fallan, se usa un `source_trace` por defecto con el `source_name` y `service_url` de la capa principal del bloque.

**Rationale**: Un bloque que consulta 4 capas no puede tener 4 `source_trace` (el contrato solo admite uno por bloque). La trazabilidad por sub-bloque se preserva en los campos del `dato` (cada sub-bloque tiene su propio origen implícito en el campo).

### D5. Manejo de sistemas de coordenadas

**Decision**: Todas las consultas usan `inSR=4326` (WGS84). ArcGIS REST de Catastro Bogotá acepta `inSR=4326` para todas las capas incluidas las de SR proyectado (102100, 102233, PCS_CarMAGBOG) y realiza la conversión internamente. No se requiere conversión manual de coordenadas en el cliente.

**Rationale**: Simplifica la implementación (sin `pyproj` ni proyecciones manuales) y es la práctica estándar de las APIs REST de ArcGIS para consultas espaciales.

---

## Resumen de servicios

| # | Bloque | Capas | SR principal | Radio |
|---|--------|-------|-------------|-------|
| 1 | geotechnical_risks | emergencias/gestionriesgos [2],[5],[7],[8] | 102100 | punto |
| 2 | socioeconomic_context | estratificacion [1], usopredominante [0], alturamedia [0], medianaavaluo [0] | PCS_CarMAGBOG / 4326 | punto |
| 3 | regulatory_environment | licenciasconstruccion [3], plusvalia [1] | PCS_CarMAGBOG | punto |
| 4 | cultural_heritage | bienesinterescultural [1], planarqueologico [9] | 102100 / 102233 | punto |
| 5 | transit_access | transportepublico [1],[5], metrobogota [0] | 102100 | 800/500/800 m |
