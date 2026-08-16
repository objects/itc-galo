# Contrato: Interfaz web de prefactibilidad (Feature 5)

**Versión**: 1.0 | **Fecha**: 2026-08-16 | **Feature**: `005-interfaz-web-prefactibilidad`

Este contrato define la capa HTTP de la interfaz web. El contrato de dominio (10 bloques del
informe) es el de F3 (`get-feasibility-report.md`, feature 003) — la web lo consume sin
redefinirlo.

---

## 1. `GET /`

Renderiza `index.html`: formulario de nueva evaluación + lista de proyectos (más recientes
primero) o mensaje de lista vacía.

- **200** `text/html` — plantilla `index.html` con contexto `{"formulario": {...}, "proyectos": [...], "errores": None}`.

---

## 2. `POST /proyectos`

Crea un proyecto de prefactibilidad y lo evalúa.

**Formulario** (`application/x-www-form-urlencoded`):

| Campo | Tipo | Regla |
|---|---|---|
| `nombre` | `str` | obligatorio, no vacío (trim), ≤ 200 |
| `criterio_tipo` | `str` | `chip` \| `direccion` \| `coordenadas` |
| `criterio_valor` | `str` | obligatorio; si `coordenadas`: `latitud,longitud` numéricas |
| `consulta` | `str` | opcional, ≤ `CONSULTA_MAX_CHARS` (500) |
| `top_k` | `int` | default 3, 1–6 (`TOP_K_MAX`) |

**Respuestas**:

- **400** `text/html` (o `application/json` si `Accept`/`X-Requested-With` htmx) — re-renderiza
  `index.html` con `errores` (validación fail-fast, FR-012). Cuerpo error:
  `{"error": {"code": "PARAMETROS_INVALIDOS", "message": "...", "campos": {...}}}`.
- **303** `See Other` — `Location: /proyectos/{id}` (PRG). El proyecto se persiste ANTES de
  redirigir: `estado="completado"` con `informe` (10 bloques) o `estado="fallido"` con
  `error={"code", "message", "source_name"}`. Un error de evaluación NUNCA produce 500 en esta
  ruta (se persiste `fallido`, FR-004).
- **500** — solo si falla la persistencia o un error inesperado (fail loud, FR-011).

---

## 3. `GET /proyectos/{id}`

Detalle de un proyecto.

- **200** `text/html` — `proyecto.html` con:
  - `proyecto`: `{id, nombre, criterio_tipo, criterio_valor, consulta, top_k, estado,
    creado_en, actualizado_en}`;
  - `informe` (si `completado`): `feasibility_score.score` (int 0–100), `feasibility_score.confidence`,
    `administrative_context.upl.codigo/nombre`, `administrative_context.localidad.nombre`,
    `warnings` (lista);
  - `error` (si `fallido`): `{code, message, source_name}`.
- **404** — `error.html` con `{"code": "NO_ENCONTRADO", ...}` si el id no existe.

---

## 4. `POST /proyectos/{id}/reevaluar`

Re-evalúa el proyecto con sus mismos criterios.

- **303** `See Other` — `Location: /proyectos/{id}`. Conserva `id`/`creado_en`, actualiza
  `estado`/`informe`/`error` y `actualizado_en`.
- **404** — id inexistente.
- **500** — error inesperado (fail loud).

---

## 5. `GET /proyectos/{id}/json`

Informe del proyecto en JSON (integración con otras herramientas).

- **200** `application/json` — si `estado=="completado"`: el informe completo (10 bloques,
  shape F3 exacto).
- **404** `application/json` — si `estado=="fallido"`: `{"error": {"code", "message",
  "source_name"}}` con el status HTTP mapeado por `_error_a_http` (p. ej. `LOTE_NO_ENCONTRADO`
  → 404; `FUENTE_5XX` → 502).
- **404** — id inexistente: `{"error": {"code": "NO_ENCONTRADO", ...}}`.
- **500** — error inesperado.

---

## 6. Mapeo de errores canónicos a HTTP (`_ERROR_A_HTTP`)

| `CodigoError` | HTTP | Nota |
|---|---|---|
| `PARAMETROS_INVALIDOS` | 400 | validación formulario / dominio |
| `LOTE_NO_ENCONTRADO` | 404 | CHIP inexistente |
| `DIRECCION_NO_LOCALIZADA` | 404 | |
| `FUERA_DE_COBERTURA` | 404 | |
| `LOTE_SIN_UPL` | 404 | |
| `DATO_NO_ENCONTRADO_POR_FUENTE` | 404 | |
| `FUENTE_5XX` | 502 | un 5xx NUNCA se degrada a "no encontrado" (FR-009) |
| `CREDENCIAL_FALTANTE` | 503 | |
| `CORPUS_NO_INGESTADO` | 503 | |
| `OLLAMA_NO_DISPONIBLE` | 503 | |
| (desconocido / `None`) | 500 | fail loud |

Códigos extra de la web: `NO_ENCONTRADO` (id de proyecto inexistente) → 404;
`ERROR_INTERNO` → 500.

---

## 7. Estáticos y recursos

- `/static/htmx.min.js` — HTMX 2.0.4 vendorizado (sin CDN).
- `/static/fonts/fraunces-var-*.woff2` — 6 archivos (normal/italic × latin/latin-ext/vietnamese).
- `/static/fonts.css`, `/static/estilos.css` — `@font-face` locales + estilos 5 Pillars.
- Todos **200** `text/javascript`/`text/css`/`font/woff2` con `Cache-Control` de Starlette.

---

## 8. Semántica de vida útil

- La app web construye y cierra su propio `ServidorLotes` en el lifespan (`aclose()`), sin
  tocar los singletons de `app.main` (FR-012).
- `crear_app_web(servidor_lotes=None, repositorio=None)` — si se omiten, los construye desde
  el entorno; en pruebas se inyectan simulados (`server_lotes_f3` + `ProyectoRepositorio(tmp_path)`).