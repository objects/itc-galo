# Contrato: Catálogo extensible Datos Abiertos

**Historia**: US1 - Catálogo extensible Datos Abiertos (P1)

## Interfaz declarativa

```python
# app/providers/arcgis_utils.py
@dataclass(frozen=True)
class CapaConfig:
    service_url: str  # ej. https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/catastro/construccion/MapServer
    layer_id: str     # ej. "0"
    source_name: str  # ej. "catastro/construccion"
    ruta_consulta: str  # propiedad: f"{service_url}/{layer_id}/query"
```

Registro: añadir instancia a `CATALOGO_CAPAS: dict[str, CapaConfig]` (nombre clave = bloque).

## Request / Response

**Request** (interna, orquestador → provider):
- `construir_params_punto(lat, lon) -> dict` con `geometry`, `geometryType=esriGeometryPoint`, `inSR=4326`, `spatialRel=esriSpatialRelIntersects`, `f=geojson`, `outFields=*`

**Response bloque** (persistido en `Proyecto.informe[clave]`):
```json
{
  "clave": "construccion",
  "titulo": "Construcción",
  "estado": "ok | no_encontrado | error",
  "datos": { "...": "..." },
  "source_traces": [
    {
      "source_name": "catastro/construccion",
      "layer_id": "0",
      "service_url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/catastro/construccion/MapServer",
      "data_vigencia": "2024-03-15",
      "query_timestamp": "2026-09-09T10:00:00Z"
    }
  ],
  "warnings": []
}
```

## Reglas

- 5 campos traza obligatorios por bloque; cada capa conserva `data_vigencia` independiente (FR-002).
- 5xx → `estado: "no_encontrado"` + `warnings: ["BLOQUE_DEGRADADO"]`, no propaga `FUENTE_5XX` (degradación por bloque).
- Publicar bloque en `GET /proyectos/{id}/json` y en `proyecto.html` loop (17 loop + 6 separadas = 23 base).
- Scoring: no altera `BLOQUES_EVALUABLES` ni `calcular_score` salvo regla explícita.
- 7 tools invariante.

## Validación (MockTransport)

```python
transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"features":[{"attributes":{"FIELD":"v"},"geometry":None}]}))
# registrar CapaConfig ficticia catastro/prueba/MapServer/99 → assert bloque con 5 campos
```
