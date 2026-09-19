# Contrato: Wizard v2 - Preview + Interrogación

**Historias**: US2 (P2) wizard validación guiada + preview persistente; US3 (P3) persistencia

## Endpoints

### POST /proyectos/preview (ligero, sin 23 bloques)

**Request** (Form): `criterio_tipo` in {chip,direccion,coordenadas}, `criterio_valor` string ≤500, `coordenadas` opcional "lat,lon"

**Response 200** JSON:
```json
{
  "lote": {"chip":"AAA0072LRYN","direccion_normalizada":"CL 26 #...","barrio":"...","centroid":{"lat":4.6,"lon":-74.08},"geometry":{...}},
  "upl": {"codigo":"UPL01","nombre":"...","localidad":"Chapinero"} | null
}
```
Errores: 400 PARAMETROS_INVALIDOS (criterio vacío/formato), 404 LOTE_NO_ENCONTRADO / FUERA_DE_COBERTURA / DIRECCION_NO_LOCALIZADA, 502 FUENTE_5XX, reuse cache LRU+TTL y World fallback sin API.

**Invariante**: no crea `Proyecto`; separa costo barato (geometría+UPL) de costoso (23 bloques).

### POST /proyectos (creación final, con wizard opcional)

**Request Form** (todos opcionales wizard además de legacy):
- `nombre`, `criterio_tipo/valor`, `consulta`, `top_k` (legacy)
- `uso_previsto` enum {residencial,comercial,mixto,dotacional,industrial}
- `escala_m2` number ≥36
- `presupuesto_rango` enum {bajo,medio,alto}
- `horizonte_meses` int 6-120
- `aversion_riesgo` enum {baja,media,alta}

Validación dual: HTML5 + `app/web/main.py:_validar_formulario` → 400 con mensaje inline por campo. Preview persistente client-side (`hx-include` + campos ocultos + Leaflet 320px clic → coordenadas).

**Response**: 303 → `GET /proyectos/{id}` con informe 23 bloques (17 loop + 6 separadas).

### POST /proyectos/{id}/reevaluar

Conserva 5 campos wizard originales; regenera informe sin perder metadata (FR-011).

## Persistencia

`Proyecto` (app/web/db.py) migra aditiva: `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` por cada campo wizard; filas viejas leen `None`. `uso_previsto` etc. son metadata contextual (FR-016 pilares), no alimentan `app/financiero.py` en F11.

## Trazabilidad

Todo bloque del informe conserva 5 campos; wizard params no alteran scoring (base 50 clamp 19 evaluables).
