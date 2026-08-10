# mcp-bogota-factibilidad

Servidor MCP (Model Context Protocol) en Python que permite consultar un **lote
catastral de Bogotá** por CHIP, por dirección o por coordenadas, enriquecerlo con
**contexto temático** (valor de referencia catastral, destino económico, reservas
viales y obras públicas) y obtener un **resumen consolidado** con trazabilidad por
fuente.

Es la Feature 1 (MVP) del producto de factibilidad de lotes para construcción en
Bogotá. Fuera de alcance en esta versión: consulta de UPL, RAG normativo del POT
(Decreto 555 de 2021) y el reporte consolidado de factibilidad.

## Requisitos

- Python 3.11 o superior.
- Acceso de red a las fuentes públicas:
  - `https://mapas.bogota.gov.co/api/` (API de búsqueda de Mapas Bogotá)
  - `https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/` (ArcGIS REST del catastro)

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuración

Copia `.env.example` a `.env` si deseas configurar la credencial opcional:

```bash
cp .env.example .env
```

| Variable | Obligatoria | Descripción |
|----------|-------------|-------------|
| `MAPAS_BOGOTA_APIKEY` | Solo para consulta por dirección | API key de Mapas Bogotá para `geocodificar`. Sin ella, `resolve_lot_by_address` falla rápido con `CREDENCIAL_FALTANTE`; las consultas por CHIP y por coordenadas siguen funcionando. |

Las variables de entorno se leen directamente del entorno; el proyecto no carga `.env`
automáticamente.

## Ejecución del servidor MCP

El servidor se comunica por **stdio** (transporte por defecto de FastMCP):

```bash
python -m app.main
```

O bien, con la entrada de consola instalada:

```bash
mcp-bogota-factibilidad
```

### Tools expuestas

| Tool | Descripción |
|------|-------------|
| `resolve_lot_by_chip` | Resuelve un lote por CHIP y devuelve identidad, geometría/centroide y contexto temático. |
| `resolve_lot_by_address` | Geocodifica una dirección y resuelve el lote asociado (requiere `MAPAS_BOGOTA_APIKEY`). |
| `resolve_lot_by_coordinates` | Resuelve el lote que contiene un punto (`latitud`, `longitud` en WGS84). |
| `get_lot_summary_by_chip` | Resumen consolidado descriptivo del lote por CHIP (identidad + contexto por fuente). |

Los contratos exactos (JSON Schema de entrada/salida) están en
`specs/001-resolver-lote-contexto/contracts/`.

## Pruebas

```bash
python -m pytest -q
```

- `tests/smoke/`: el servidor arranca y las 4 tools quedan registradas.
- `tests/contract/`: contratos de las tools, taxonomía de errores, validación
  FR-012, trazabilidad (5 campos por dato), estados `disponible`/`no_encontrado`
  y escenarios del quickstart. Las pruebas usan respuestas simuladas
  (`httpx.MockTransport`): **no** hacen llamadas de red reales.

## Trazabilidad (Principio III, no negociable)

Cada dato presentado al LLM incluye exactamente 5 campos de origen:

- `source_name`: nombre canónico de la fuente (`mapas_bogota`,
  `Mapa_Referencia/Mapa_Referencia`, `catastro/valorreferencia`,
  `catastro/destinolt`, `ordenamientoterritorial/reservavial`,
  `gestionpublica/obraspublicas`).
- `layer_id`: capa o tema dentro del servicio.
- `service_url`: URL del servicio consultado.
- `data_vigencia`: vigencia del dato en la fuente.
- `query_timestamp`: marca de tiempo de la consulta (ISO 8601 UTC).

Los datos de vigencias distintas nunca se presentan como una sola fotografía
temporal: cada dato conserva su vigencia.

## Estructura del proyecto

```text
app/
├── main.py              # FastMCP: registra las 4 tools
├── models.py            # Modelos pydantic (Lote, contexto temático, trazabilidad)
├── errores.py           # Taxonomía de errores del contrato
└── providers/           # Un provider por fuente
    ├── mapas_bogota.py  # Mapas Bogotá API (direccion_chip, geocodificar)
    └── arcgis.py        # ArcGIS REST (Lote=38 + temáticas)
tests/
├── contract/            # Contratos de las tools y de error
└── smoke/               # Smoke test de arranque
```

## Docker

```bash
docker build -t mcp-bogota-factibilidad .
docker run --rm -i mcp-bogota-factibilidad
```

El contenedor ejecuta el servidor MCP por stdio; conéctalo como subproceso desde
un cliente MCP (p. ej. el Inspector de MCP).
