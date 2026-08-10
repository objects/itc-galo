# Data Model: Resolver lote con contexto temático

**Fase**: Phase 1 del comando `/speckit.plan` | **Fecha**: 2026-08-10
**Feature**: [spec.md](spec.md) | **Base**: constitución v1.0.0 y brief del producto

Este documento define el modelo de datos de la Feature 1: las entidades del dominio, los
estados de dato por fuente, la trazabilidad (`SourceTrace`) y la taxonomía de errores del
contrato. Los nombres de campos y códigos se conservan en inglés donde el contrato lo exige
(Principio I de la constitución); toda la prosa está en español.

## Convenciones

- **Frontera de parsing**: el JSON crudo de cada fuente se parsea **una sola vez** en el
  provider correspondiente (Principio II) mediante modelos pydantic v2. A partir de ese
  punto, el núcleo trabaja con objetos tipados.
- **Estado por dato**: toda entidad temática lleva `estado` con los valores
  `"disponible"` | `"no_encontrado"` (FR-007). Un dato ausente o no aplicable es
  `"no_encontrado"`, nunca cero ni vacío silencioso.
- **Trazabilidad**: cada dato presentado al LLM lleva un `SourceTrace` de **5 campos**
  obligatorios (FR-006, Principio III). Ver sección [SourceTrace](#sourcetrace).
- **Vigencias**: los datos de vigencias distintas nunca se presentan como una sola
  fotografía temporal (FR-008/SC-004); cada dato conserva su `data_vigencia`.

---

## Entidades

### Lote

Entidad central: toda consulta (por CHIP, dirección o coordenadas) resuelve a un `Lote`, y
el contexto temático se asocia a él (Key Entity del spec).

| Campo | Tipo | Requerido | Descripción / Validación |
|-------|------|-----------|--------------------------|
| `chip` | `string` | sí | CHIP del predio (identificador oficial). Formato: 11 caracteres alfanuméricos, p. ej. `AAA0072LRYN`. Validación en FR-012. |
| `codigo_catastral` | `string` | sí | Código catastral del lote (`LOTCODIGO` de la capa Lote), p. ej. `006202003016`. |
| `manzana` | `string` | sí | Código de la manzana (`MANZCODIGO` de la capa Lote), p. ej. `006202003`. |
| `direccion_normalizada` | `string` | no | Dirección normalizada del lote cuando la fuente la provee (FR-001). |
| `barrio` | `string` | no | Barrio cuando la fuente lo provee. |
| `geometry` | `object` (GeoJSON) | sí | Geometría poligonal oficial del lote (SRID 4326). |
| `centroid` | `object` | sí | Centroide: `{ "lat": number, "lng": number }` en WGS84 (4326). Se deriva de la geometría del predio (búsqueda por CHIP) o es el punto consultado (coordenadas). |

Reglas de dominio:

- El `Lote` se resuelve por: CHIP (Mapas Bogotá `direccion_chip` + capa Lote), dirección
  (Mapas Bogotá `geocodificar` + capa Lote) o coordenadas (capa Lote por punto).
- Si la resolución no produce un lote único, no se inventa un lote: se responde el error
  correspondiente (ver taxonomía).

### ValorReferencia

Valor de referencia catastral del terreno publicado por el catastro oficial (Key Entity).

| Campo | Tipo | Requerido | Descripción / Validación |
|-------|------|-----------|--------------------------|
| `estado` | `string` | sí | `"disponible"` \| `"no_encontrado"` |
| `valor_m2` | `number` | si `estado=disponible` | Valor de referencia por metro cuadrado. |
| `unidad_monetaria` | `string` | si `estado=disponible` | Unidad del valor (COP). |
| `vigencia` | `string` | si `estado=disponible` | Año o periodo de vigencia del dato (p. ej. `2025`). |
| `source_trace` | `SourceTrace` | sí | Origen: `catastro/valorreferencia`. |

### DestinoEconomico

Uso o destino económico predominante del Lote según el catastro oficial (Key Entity),
obtenido por join `ESOCLOTE=<codigo_catastral>`.

| Campo | Tipo | Requerido | Descripción / Validación |
|-------|------|-----------|--------------------------|
| `estado` | `string` | sí | `"disponible"` \| `"no_encontrado"` |
| `codigo_destino` | `string` | si `estado=disponible` | Código del destino económico en la fuente. |
| `descripcion_destino` | `string` | si `estado=disponible` | Descripción legible del destino económico predominante. |
| `vigencia` | `string` | si `estado=disponible` | Vigencia del dato (p. ej. `2022`). |
| `source_trace` | `SourceTrace` | sí | Origen: `catastro/destinolt`. |

### ReservaVial

Zona de reserva vial del ordenamiento territorial que afecta o se superpone al Lote (Key
Entity). Su ausencia se reporta como `estado="no_encontrado"`.

| Campo | Tipo | Requerido | Descripción / Validación |
|-------|------|-----------|--------------------------|
| `estado` | `string` | sí | `"disponible"` \| `"no_encontrado"` |
| `afecta_lote` | `boolean` | si `estado=disponible` | `true` si el lote se superpone con una zona de reserva vial. |
| `descripcion` | `string` | no | Descripción de la reserva vial cuando la fuente la provee. |
| `vigencia` | `string` | si `estado=disponible` | Vigencia del dato. |
| `source_trace` | `SourceTrace` | sí | Origen: `ordenamientoterritorial/reservavial`. |

### ObraPublica

Obras públicas de la gestión pública distrital cercanas al Lote (Key Entity). La consulta
es espacial por punto/centroide y puede devolver cero, una o varias obras; si no hay
ninguna, `estado="no_encontrado"`.

| Campo | Tipo | Requerido | Descripción / Validación |
|-------|------|-----------|--------------------------|
| `estado` | `string` | sí | `"disponible"` \| `"no_encontrado"` |
| `obras` | `array<object>` | si `estado=disponible` | Lista de obras públicas cercanas según la fuente (cada una con su nombre/descripción). |
| `vigencia` | `string` | si `estado=disponible` | Vigencia del dato. |
| `source_trace` | `SourceTrace` | sí | Origen: `gestionpublica/obraspublicas`. |

### SourceTrace

Trazabilidad canónica de un dato (Principio III NON-NEGOTIABLE, FR-006). **Los 5 campos son
obligatorios en toda salida para el LLM**, incluida la marca de tiempo de la consulta
(hallazgo del revisor: SC-003 del spec omite `query_timestamp`; el contrato DEBE incluirlo
siempre).

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `source_name` | `string` | sí | Nombre canónico de la fuente: `mapas_bogota`, `Mapa_Referencia/Mapa_Referencia`, `catastro/valorreferencia`, `catastro/destinolt`, `ordenamientoterritorial/reservavial`, `gestionpublica/obraspublicas`. |
| `layer_id` | `string` | sí | Identificador de la capa/tema dentro del servicio (p. ej. `38` para Lote, `0` para valorreferencia/destinolt/obraspublicas, `1` para reservavial, `direccion_chip`/`geocodificar` para la API de Mapas Bogotá). |
| `service_url` | `string` | sí | URL del servicio consultado. |
| `data_vigencia` | `string` | sí | Vigencia del dato en la fuente (fecha ISO o año, según la declare la fuente). |
| `query_timestamp` | `string` | sí | Marca de tiempo de la consulta, ISO 8601 UTC (p. ej. `2026-08-10T14:30:00Z`). |

Reglas de trazabilidad:

- Cada bloque de dato (`ValorReferencia`, `DestinoEconomico`, `ReservaVial`,
  `ObraPublica`, el propio `Lote`) adjunta su `SourceTrace`.
- No se mezclan vigencias: si dos datos provienen de capas con `data_vigencia` distinta,
  cada uno conserva la suya (FR-008/SC-004).

---

## Estados de dato por fuente

| `estado` | Significado | Cómo se reporta |
|----------|-------------|-----------------|
| `disponible` | La fuente devolvió dato(s) para el lote. | Se incluye el dato con su `source_trace`. |
| `no_encontrado` | La fuente no tiene dato para el lote (ausencia o no aplica). | Se incluye el bloque con `dato` ausente y `estado="no_encontrado"`, **nunca** cero ni vacío silencioso (FR-007). |

Un fallo 5xx de la fuente **no** es un estado de dato: es un error fatal de la tool
(`FUENTE_5XX`) que identifica la fuente (FR-009).

---

## Taxonomía de errores del contrato

Códigos canónicos usados por todas las tools (Principio IV, contratos explícitos):

| Código | Condición | Fatal | Mensaje (español) |
|--------|-----------|-------|-------------------|
| `LOTE_NO_ENCONTRADO` | El CHIP, la dirección o el punto no resuelven a ningún lote (o el punto cae en límite sin lote único). | sí | `No se encontró ningún lote para el criterio consultado.` |
| `DIRECCION_NO_LOCALIZADA` | La dirección no pudo geocodificarse (no encontrada o ambigua); nunca se inventa un lote. | sí | `La dirección no pudo localizarse. Refina la dirección o usa CHIP/coordenadas.` |
| `FUERA_DE_COBERTURA` | El punto está fuera del área de Bogotá. | sí | `El punto está fuera del área de cobertura (Bogotá).` |
| `DATO_NO_ENCONTRADO_POR_FUENTE` | La fuente no tiene dato para el lote. **No es fatal**: se reporta como `estado="no_encontrado"` por fuente. | no | `La fuente <source_name> no tiene datos para este lote.` |
| `FUENTE_5XX` | Error del lado del servidor de la fuente (5xx), indicando cuál fuente. | sí | `La fuente <source_name> no está disponible (error <status>). Intenta nuevamente.` |
| `CREDENCIAL_FALTANTE` | Falta `MAPAS_BOGOTA_APIKEY` en geocodificación (fail-fast). | sí | `Falta la variable MAPAS_BOGOTA_APIKEY para consultas por dirección. Configúrala en .env.` |
| `PARAMETROS_INVALIDOS` | Parámetros de entrada inválidos (FR-012). | sí | `Parámetros inválidos: <detalle>.` |

Forma del error en la respuesta de la tool:

```json
{
  "error": {
    "code": "FUENTE_5XX",
    "message": "La fuente catastro/valorreferencia no está disponible (error 503). Intenta nuevamente.",
    "source_name": "catastro/valorreferencia"
  }
}
```

---

## Reglas de validación de entrada (FR-012)

Aplicadas en el límite de cada tool (fail-fast; si fallan, se responde
`PARAMETROS_INVALIDOS` sin llamar a las fuentes):

1. **CHIP mal formado**: el CHIP debe ser una cadena de exactamente 11 caracteres
   alfanuméricos en mayúsculas (patrón `^[A-Z0-9]{11}$`); se rechaza con
   `PARAMETROS_INVALIDOS` y mensaje `CHIP inválido: debe tener 11 caracteres alfanuméricos.`.
2. **Coordenadas fuera de rango**: `latitude` ∈ [-90, 90] y `longitude` ∈ [-180, 180];
   fuera de ese rango se rechaza con `PARAMETROS_INVALIDOS`. El punto válido en rango pero
   fuera de Bogotá produce `FUERA_DE_COBERTURA` (no es un parámetro inválido).
3. **Dirección vacía**: una dirección en blanco o solo espacios se rechaza con
   `PARAMETROS_INVALIDOS` y mensaje `La dirección no puede estar vacía.`.
4. **Tipos**: `chip` y `address` deben ser `string`; `latitude` y `longitude` deben ser
   `number`. Un tipo incorrecto es `PARAMETROS_INVALIDOS`.

---

## Relación con el spec

| Artefacto | Requisitos del spec |
|-----------|---------------------|
| `Lote` | FR-001, FR-002, FR-003, FR-012, Key Entity Lote |
| `ValorReferencia`, `DestinoEconomico`, `ReservaVial`, `ObraPublica` | FR-004, FR-007, Key Entities |
| `SourceTrace` | FR-006, FR-008, SC-003, SC-004, Principio III |
| Estados `disponible` / `no_encontrado` | FR-007, SC-002 |
| Taxonomía de errores | FR-009, FR-010, FR-012, SC-006, Principio IV |
| Reglas de validación FR-012 | FR-012, SC-006 |
