# Data Model: Interfaz web de prefactibilidad (Feature 5)

**Fecha**: 2026-08-16 | **Feature**: `005-interfaz-web-prefactibilidad`

## 1. Entidad `Proyecto` (nueva, capa web — `app/web/db.py`)

Modelo pydantic v2 (no SQLAlchemy): valida el dominio sin añadir dependencias (pydantic ya es
core del proyecto). Campos:

| Campo | Tipo | Descripción | Reglas |
|---|---|---|---|
| `id` | `str` | Identificador único | hex uuid (8 bytes), `uuid.uuid4().hex`; default al crear |
| `nombre` | `str` | Nombre del proyecto | obligatorio, ≤ 200 chars (validación formulario) |
| `criterio_tipo` | `Literal["chip","direccion","coordenadas"]` | Criterio de evaluación | requerido |
| `criterio_valor` | `str` | CHIP / dirección / "lat,lon" | requerido; coordenadas se validan numéricas |
| `consulta` | `str \| None` | Consulta normativa opcional | `None` o ≤ 500 chars (F3 la usa si se da) |
| `top_k` | `int` | K del RAG | default 3; rango 1–6 (validación formulario) |
| `estado` | `Literal["completado","fallido"]` | Estado de la última evaluación | `"completado"` si informe OK, `"fallido"` si error |
| `informe` | `dict \| None` | Informe F3 (10 bloques) | presente si `estado=="completado"` |
| `error` | `dict \| None` | `{code, message, source_name}` | presente si `estado=="fallido"` |
| `creado_en` | `str` | Fecha creación | UTC ISO 8601, `ahora_iso()` |
| `actualizado_en` | `str` | Fecha última evaluación | UTC ISO 8601; = creado_en al crear |

**Reglas de dominio**:
- `estado`/`informe`/`error` son mutuamente coherentes: `completado` ⇒ `informe` no None y
  `error` None; `fallido` ⇒ `error` no None e `informe` None.
- La re-evaluación (`POST /proyectos/{id}/reevaluar`) conserva `id`, `nombre`, `criterio_tipo`,
  `criterio_valor`, `consulta`, `top_k` y `creado_en`; actualiza `estado`, `informe`/`error` y
  `actualizado_en`.
- El informe F3 es un `dict` (JSON) con los 10 bloques raíz del contrato de
  `get_feasibility_report` (ver `contracts/interfaz-web-prefactibilidad.md`); la capa web NO
  redefine el shape, solo lo serializa.

## 2. Repositorio `ProyectoRepositorio` (SQLite, `sqlite3` stdlib)

**Archivo**: `app/web/db.py`. **Tabla** `proyectos`:

```sql
CREATE TABLE IF NOT EXISTS proyectos (
    id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    criterio_tipo TEXT NOT NULL,
    criterio_valor TEXT NOT NULL,
    consulta TEXT,
    top_k INTEGER NOT NULL DEFAULT 3,
    estado TEXT NOT NULL,
    informe TEXT,
    error TEXT,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT NOT NULL
);
```

- `informe`/`error` se serializan con `json.dumps` (safe=True); al leer, `json.loads`.
- **Transacción por operación**: cada método abre un `with self._conexion:` (commit/rollback
  automático) — operación atómica, SC-005.
- Conexión por hilo: la app FastAPI es async (uvicorn) y los handlers son `def` (no `async
  def`) para evitar bloqueo del event loop (FastAPI ejecuta `def` en threadpool).
- Métodos:
  - `crear(proyecto: Proyecto) -> Proyecto` (INSERT, falla si el id ya existe)
  - `obtener(proyecto_id: str) -> Proyecto | None`
  - `listar() -> list[Proyecto]` (ORDER BY creado_en DESC)
  - `actualizar(proyecto: Proyecto) -> Proyecto | None` (UPDATE por id; None si no existe)

**Ubicación del archivo**: `PROYECTOS_DB_PATH` env (default `.data/proyectos.db`; `.data/`
está en `.gitignore` — es estado derivado, no fuente de verdad). El repositorio recibe la ruta
en el constructor (`ProyectoRepositorio(ruta)`); crea el directorio padre si no existe y la
tabla al instanciarse.

## 3. Capa de presentación (templates/static — NO son datos de dominio)

- `templates/base.html`: layout (header con marca + kicker + textura SVG, nav, footer con
  disclaimer de score heurístico FR-014).
- `templates/index.html`: formulario (nombre, criterio con 3 modos, consulta, top_k) + lista
  de proyectos (o mensaje de vacío).
- `templates/proyecto.html`: detalle — criterio, fechas, estado, score/confianza (anillo
  SVG), UPL/localidad, warnings, o caja de error; enlace a `/json`.
- `templates/error.html`: caja de error con código HTTP + código canónico + mensaje.
- `static/`: `htmx.min.js` (2.0.4), `fonts/` (6 woff2 Fraunces), `fonts.css` (@font-face),
  `estilos.css` (5 Pillars).

## 4. Criterios de búsqueda del dominio (sin cambios)

La Feature 5 NO modifica `app/models.py`, `app/main.py`, `app/errores.py`, `app/scoring.py`,
`app/providers/*` ni `app/ingesta/*`. El shape de `InformeFactibilidad` (F3, 10 bloques) y la
taxonomía de 10 códigos de error son la fuente de verdad; la web los consume sin redefinirlos.