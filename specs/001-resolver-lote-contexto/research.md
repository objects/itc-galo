# Research: Resolver lote con contexto temático

**Fase**: Phase 0 del comando `/speckit.plan` | **Fecha**: 2026-08-10
**Feature**: [spec.md](spec.md) | **Estado**: Resuelto — todas las decisiones zanjadas, sin marcadores de aclaración pendiente

## Alcance

Esta investigación resuelve las decisiones técnicas de la Feature 1 (MVP) antes de diseñar
el modelo de datos y los contratos. Todas las decisiones quedan zanjadas por la
constitución v1.0.0 (`.specify/memory/constitution.md`) y por el brief del producto
(`20260809-01-perplexity.md`), que es la fuente de verdad. No se consultaron ni se
consultarán en runtime las fuentes de datos desde este comando; las URLs y parámetros se
documentan a partir del brief y de la documentación pública referenciada en él.

Fuentes de decisión citadas en el brief:

- API de búsqueda de Mapas Bogotá: `https://mapas.bogota.gov.co/api/`
  (`cmd=direccion_chip`, `cmd=geocodificar`, `cmd=geocodificar_inverso`).
- ArcGIS REST del catastro: `https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/`
  (`Mapa_Referencia/Mapa_Referencia/MapServer` capa 38 = Lote; temáticas
  `catastro/valorreferencia`, `catastro/destinolt`, `ordenamientoterritorial/reservavial`,
  `gestionpublica/obraspublicas`).

---

## D1. Framework MCP: FastMCP (Python) vía `mcp>=1.0.0`

**Decision**: Usar el SDK oficial de MCP para Python con **FastMCP**
(dependencia `mcp>=1.0.0`, que lo incluye) para registrar las 4 tools de la feature.

**Rationale**: La constitución v1.0.0 fija el stack Python con `mcp>=1.0.0` (Restricciones
técnicas) y el brief entrega un esqueleto Python con `mcp>=1.0.0`, `httpx` y `pydantic` que
usa FastMCP. FastMCP reduce el boilerplate de registro de tools y devuelve JSON
estructurado directamente, que es la salida que consume el LLM. La decisión de stack
(Python) es del usuario, no negociable en esta feature.

**Alternatives considered**:

- **Node.js con `@modelcontextprotocol/sdk`**: descartado por decisión de stack del
  usuario (la constitución fija Python).
- **SDK MCP de Python sin FastMCP** (uso directo de `mcp.server.Server` + decoradores
  `@server.tool`): posible pero agrega boilerplate sin beneficio; FastMCP está incluido en
  la misma dependencia y es la vía idiomática documentada.

---

## D2. Cliente HTTP: httpx

**Decision**: Usar **httpx** (cliente async) para todas las llamadas a la API de Mapas
Bogotá y a los servicios ArcGIS REST.

**Rationale**: Es la dependencia declarada en la constitución y en el esqueleto Python del
brief. Soporta async nativo (las 4 tools son async y las consultas temáticas pueden
ejecutarse en paralelo con `asyncio.gather`), maneja timeouts por cliente y `raise_for_status`
facilita el fail-fast ante errores 5xx de la fuente.

**Alternatives considered**:

- **requests**: síncrono; obligaría a envolver llamadas en threads o a secuenciar las
  consultas temáticas, en detrimento de SC-001 (< 10 s). Descartado.
- **urllib (stdlib)**: sin gestión de timeouts/retry idiomática y sin async. Descartado.

---

## D3. Validación: modelos pydantic v2 como frontera de parsing

**Decision**: Definir en `app/models.py` modelos **pydantic v2** (`Lote`, entidades
temáticas con su `estado`, `SourceTrace` con los 5 campos de trazabilidad) como frontera
de parsing de los providers: el JSON crudo de cada fuente se parsea una sola vez en el
provider y, a partir de ahí, la lógica interna trabaja con datos tipados y confiables.

**Rationale**: Constitución Principio II (los providers son el límite de parsing: exponen
modelos tipados pydantic). Corresponde a la ley "Parse, Don't Validate": los datos entran
tipados al núcleo y no requieren chequeos defensivos repetidos; además pydantic v2 valida
tipos y rangos al construir el modelo (fail-fast en el límite).

**Alternatives considered**:

- **Validación manual con dicts**: sin garantía de tipos, propensa a errores y sin
  mensajes descriptivos. Descartado.
- **dataclasses**: sin validación automática de tipos en el límite. Descartado.

---

## D4. Resolución del lote: Mapas Bogotá API + ArcGIS REST capa 38

**Decision**: Resolver el lote con dos pasos por fuente, según el medio de entrada:

- **Por CHIP**: `GET https://mapas.bogota.gov.co/api/` con
  `cmd=direccion_chip&query=<CHIP>&spatialReference=102100` → resultado con geometría del
  predio; se calcula el centroide y se consulta la capa **Lote** de ArcGIS.
- **Por dirección**: `GET https://mapas.bogota.gov.co/api/` con `cmd=geocodificar`
  (requiere `MAPAS_BOGOTA_APIKEY`; fail-fast si falta) → punto geográfico → se consulta la
  capa Lote.
- **Por coordenadas**: consulta directa de la capa **Lote**:
  `https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/Mapa_Referencia/Mapa_Referencia/MapServer/38/query`
  con `f=geojson`, `geometry=<lng,lat>`, `geometryType=esriGeometryPoint`, `inSR=4326`,
  `spatialRel=esriSpatialRelIntersects`, `outSR=4326`; campos visibles `LOTCODIGO` y
  `MANZCODIGO`.

El lote resuelto (identidad + geometría + centroide) es la entidad central a la que se
asocia el contexto temático.

**Rationale**: Es el flujo documentado en el brief y en la capa oficial de IDECA/UAECD:
la búsqueda por CHIP de Mapas Bogotá entrega la geometría del predio y la capa Lote del
Mapa de Referencia entrega el `LOTCODIGO`/`MANZCODIGO` oficiales. El punto de intersección
(`esriSpatialRelIntersects`) es el método estable de ArcGIS para resolver el lote que
contiene un punto.

**Alternatives considered**:

- **Solo Mapas Bogotá API para todo**: la API no expone la capa Lote oficial con
  `LOTCODIGO` como la consulta espacial de ArcGIS; la geometría oficial y el código
  catastral del lote provienen del Mapa de Referencia. Descartado.
- **Resolución por coordenadas vía `geocodificar_inverso`**: requiere `MAPAS_BOGOTA_APIKEY`
  innecesariamente; la capa Lote resuelve el punto sin credencial (YAGNI y menor fricción).

---

## D5. Contexto temático: servicios ArcGIS temáticos con join por `ESOCLOTE`

**Decision**: Enriquecer el lote con 4 temáticas, cada una con su propio provider de
consulta y su `data_vigencia`:

- **Valor de referencia**: `catastro/valorreferencia` (capa 0), por punto/centroide.
- **Destino económico**: `catastro/destinolt` (capa 0), join por `ESOCLOTE=<lotcodigo>`.
- **Reserva vial**: `ordenamientoterritorial/reservavial` (capa 1), por punto/centroide.
- **Obras públicas**: `gestionpublica/obraspublicas` (capa 0), por punto/centroide.

Consulta base: `.../query` con `f=geojson` y los parámetros espaciales estándar
(`geometryType=esriGeometryPoint`, `inSR=4326`, `spatialRel=esriSpatialRelIntersects`,
`outSR=4326`), o `where=ESOCLOTE='<lotcodigo>'` con `returnGeometry=false` para el destino.
Cada dato conserva su `data_vigencia`; cuando la fuente no devuelve un resultado, el estado
es **"no_encontrado"** (nunca cero ni vacío silencioso, FR-007).

**Rationale**: Son los servicios públicos oficiales que el brief recomienda para el
contexto de mercado, uso y restricciones de un lote. Cada servicio declara cobertura y
vigencia distintas (p. ej. `destinolt` con información 2022 y `valorreferencia` con rangos
2012–2025), por lo que conservar `data_vigencia` por dato es obligatorio (FR-008).

**Alternatives considered**:

- **Consultar todas las temáticas por `where` con join**: el destino económico se une por
  `ESOCLOTE`; las demás temáticas no tienen el código del lote como llave estable y se
  resuelven espacialmente por punto. Descartado.
- **Incluir UPL/localidad como contexto**: fuera de alcance de F1 (la UPL queda para la
  feature de RAG normativo; YAGNI).

---

## D6. Contratos de error: taxonomía explícita

**Decision**: Definir una taxonomía canónica de errores aplicada en todas las tools, con
códigos y mensajes en español, y estados de dato por fuente:

- `LOTE_NO_ENCONTRADO` — el CHIP/dirección/coordenadas no resuelven a ningún lote.
- `DIRECCION_NO_LOCALIZADA` — la dirección no pudo geocodificarse (no encontrada o
  ambigua; nunca se inventa un lote).
- `FUERA_DE_COBERTURA` — el punto está fuera del área de Bogotá.
- `DATO_NO_ENCONTRADO_POR_FUENTE` — estado por fuente temática (no fatal): la fuente no
  tiene dato para el lote; se reporta como `estado: "no_encontrado"`.
- `FUENTE_5XX` — error del lado del servidor de la fuente, indicando **cuál** fuente
  falló; nunca se confunde con "no encontrado" (FR-009).
- `CREDENCIAL_FALTANTE` — falta `MAPAS_BOGOTA_APIKEY` en geocodificación; fail-fast
  (FR-010).
- `PARAMETROS_INVALIDOS` — CHIP mal formado, coordenadas fuera de rango, dirección vacía
  (FR-012).

**Rationale**: Constitución Principio IV (contratos de error explícitos, Fail Fast, Fail
Loud) y FR-009/FR-012 del spec. Un 5xx de la fuente es un fallo del servidor de datos y
debe ser accionable (reintentar o reportar la fuente); "dato no encontrado" es un resultado
válido de la fuente.

**Alternatives considered**:

- **Errores genéricos (HTTP status)**: no distinguen el origen del fallo y no son
  accionables para el LLM. Descartado.
- **Reportar 5xx como "sin datos"**: viola FR-009 y la constitución (Principio IV).
  Descartado.

---

## D7. Trazabilidad: 5 campos canónicos por fuente (incluye `query_timestamp`)

**Decision**: Toda salida para el LLM incluye, **por cada dato**, los 5 campos canónicos:
`source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp`. Las
vigencias distintas nunca se mezclan como una sola fotografía temporal (FR-008/SC-004).

**Rationale**: Constitución Principio III (NON-NEGOTIABLE) y FR-006. **Hallazgo del
revisor**: SC-003 del spec omite `query_timestamp` (solo menciona "fuente, capa y URL del
servicio" y "vigencia"); el contrato DEBE incluir **siempre los 5 campos**, incluida la
marca de tiempo de la consulta, porque la salida para el LLM es una fotografía del momento
de la consulta sobre fuentes públicas en vivo. El modelo `SourceTrace` en `data-model.md` y
los JSON schemas de `contracts/` fijan los 5 campos como obligatorios en cada dato.

**Alternatives considered**:

- **Trazabilidad solo a nivel de bloque `sources`**: insuficiente; el LLM necesita saber
  el origen y la vigencia de **cada dato**, no solo el listado de fuentes usadas.
- **Un solo `source_trace` global**: ocultaría la vigencia distinta por temática.
  Descartado.

---

## D8. Transporte: MCP por stdio

**Decision**: El servidor MCP se comunica por **stdio** (constitución, Restricciones
técnicas): el proceso se lanza como subproceso y lee/escribe JSON-RPC por la entrada y
salida estándar, apto para clientes MCP locales (LLM) y para el contenedor Docker.

**Rationale**: La constitución fija "Transporte MCP por stdio" y el brief lo usa en ambos
esqueletos (`mcp.run()` con FastMCP usa stdio por defecto). No hay requisito de acceso
remoto en F1; la ingesta de corpus y el RAG (que sí se beneficiarían de un transporte de
red) quedan para F2.

**Alternatives considered**:

- **SSE/HTTP**: transporte de red para clientes remotos; agrega superficie de ataque,
  configuración de puertos y no lo exige F1. Descartado (YAGNI).

---

## Resumen de decisiones y artefactos derivados

| # | Decisión | Artefacto que la materializa |
|---|----------|------------------------------|
| D1 | FastMCP (Python) | `plan.md` (Technical Context, Project Structure) |
| D2 | httpx | `plan.md` (Technical Context) |
| D3 | pydantic v2 como frontera de parsing | `data-model.md`, `plan.md` (Structure Decision) |
| D4 | Resolución: Mapas Bogotá API + ArcGIS capa 38 | `contracts/resolve-lot-by-*.md` |
| D5 | Contexto temático ArcGIS con `data_vigencia` | `data-model.md`, `contracts/*.md` |
| D6 | Taxonomía de errores explícita | `data-model.md`, `contracts/*.md` |
| D7 | Trazabilidad de 5 campos por dato | `data-model.md` (SourceTrace), `contracts/*.md` |
| D8 | Transporte stdio | `plan.md` (Target Platform) |
