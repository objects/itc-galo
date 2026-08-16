# Research: Interfaz web de prefactibilidad (Feature 5)

**Fecha**: 2026-08-16 | **Feature**: `005-interfaz-web-prefactibilidad`

## D1 — Reutilizar `ServidorLotes` sin MCP (decisión de arquitectura)

La capa web NO debe depender del protocolo MCP: el servidor MCP vive por stdio y la web es una
capa de presentación HTTP independiente. Se reutiliza la **clase** `ServidorLotes`
(`app/main.py:132`) — el orquestador de `get_feasibility_report` — construyendo una instancia
propia en el lifespan de la app FastAPI con los 4 providers reales:

- `MapasBogotaProvider(api_key=os.environ.get("MAPAS_BOGOTA_APIKEY"))`
- `ArcGISProvider()`, `UPLProvider()`, `NormativaProvider()`

y cerrándola con `await servidor.aclose()` al terminar. NO se usan los singletons
`servidor_lotes`/`mcp` de `app.main` (evita estado compartido entre el proceso stdio y el
proceso web). Para pruebas se inyecta `crear_app_web(servidor_lotes=server_lotes_f3(...),
repositorio=ProyectoRepositorio(tmp_path))`: `server_lotes_f3` (tests/conftest.py:296) con
providers simulados vía `httpx.MockTransport` — cero red real, cero Ollama.

## D2 — Persistencia: SQLite con `sqlite3` stdlib (sin dependencia nueva)

Los proyectos se persisten en SQLite. Opciones: SQLAlchemy (pesado, dependencia nueva),
peewee (dependencia nueva), `sqlite3` stdlib (cero dependencias, suficiente para un CRUD de
una tabla). **Decisión**: `sqlite3` stdlib con una tabla `proyectos` y transacción por
operación. El repositorio (`ProyectoRepositorio`) expone `crear/obtener/listar/actualizar` y
serializa `informe`/`error` como JSON. `Proyecto` es un modelo pydantic v2 (validación de
dominio, sin romper el patrón del proyecto: pydantic ya es dependencia core). Base por defecto
`.data/proyectos.db` (gitignored, como `.data/chroma/`).

## D3 — Firma de `Jinja2Templates.TemplateResponse` en Starlette 1.6 (verificado)

Starlette ≥ 1.6 cambió la firma: `TemplateResponse(request, name, context=None,
status_code=200, ...)` — el `request` va PRIMERO como argumento posicional. La firma antigua
`TemplateResponse(name, {"request": request})` quedó deprecada. Verificado en vivo con
fastapi 0.141.1 / starlette 1.6.0 (pip show tras `pip install -e ".[web,dev]"`). Uso en
`app/web/main.py`: `plantillas.TemplateResponse(request, "index.html", {"proyectos": ...})`.
Para el error con status: `TemplateResponse(request, "error.html", {...}, status_code=404)`.

## D4 — HTMX 2.0.4 vendorizado + Jinja2 en plantillas

HTMX se sirve desde `/static/htmx.min.js` (descargado de unpkg, 50.9 KB, versión 2.0.4) — sin
CDN: la interfaz funciona offline. Uso en las plantillas:
- `hx-boost="true"` en `<body>`: navegación/forms por AJAX con swap de `body`.
- `hx-post` + `hx-target="body"` + `hx-swap="outerHTML"` + `hx-indicator` en los forms
  (progressive enhancement: sin JS los forms siguen funcionando por POST normal).
- `.htmx-indicator` oculto por defecto, visible durante la petición (CSS en `estilos.css`).

Jinja2: `{% extends "base.html" %}`, bloques `titulo`/`contenido`, `url_for('static',
path=...)` → `/static/...` (las plantillas usan rutas absolutas `/static/...`).

## D5 — Identidad visual (5 Pillars) y vendorización de Fraunces

Diseño "Bogotá Reverdece" (POT 2022-2035) en 5 Pillars:
1. **Fraunces** (serif variable, opsz 9..144, wght 100..900) — vendorizada como 6 woff2
   (normal/italic × latin/latin-ext/vietnamese) en `app/web/static/fonts/` + `fonts.css` con
   `@font-face` y `unicode-range` locales (replicando el CSS de Google Fonts v38). Prohibido
   Inter/Roboto/Arial/system-ui.
2. **Paleta**: verde profundo `#0b3d2e`, verde bosque `#14563f`, ámbar `#c9a227`, dorado
   `#e0b84c`, crema `#f7f2e7`, tinta `#1e2a24`; rojo de error `#b03a2e`.
3. **UNA animación**: el anillo de score (SVG con `stroke-dasharray`/`stroke-dashoffset`
   animado una vez al cargar, `@keyframes dibujar-anillo` 1.1s forwards); respeta
   `prefers-reduced-motion`.
4. **Composición asimétrica**: retícula 7fr/5fr (no centra todo), marca anclada a la
   izquierda con `kicker` + título + subtítulo, chip lateral desplazado.
5. **Textura de curvas de nivel**: SVG data-URI de fondo del encabezado (3 paths contorneando
   la marca), evocando la cartografía bogotana.

## D6 — Mapeo de errores canónicos a HTTP (Fase 5)

La taxonomía de `app/errores.py` (10 códigos, `CodigoError`) se traduce a status HTTP con un
dict `_ERROR_A_HTTP` + `_error_a_http(codigo)` (catch-all 500). Regla de oro FR-009: un 5xx de
una fuente (`FUENTE_5XX`) NUNCA se degrada a "no encontrado" → **502**. Los errores de
evaluación NO se lanzan como excepciones HTTP: el proyecto se persiste `fallido` con
`{code, message, source_name}` y el detalle HTML / `/json` lo exponen con el status mapeado.
Las validaciones de formulario sí fallan rápido con `HTTPException(400)` (FR-012).

## Fuentes consultadas

- Starlette docs: `Jinja2Templates` (`TemplateResponse` request-first, Starlette 1.6+).
- FastAPI docs: `Form(...)` + `python-multipart`; `TestClient` (sigue redirects por defecto);
  lifespan + `app.state`; `StaticFiles` mount; exception handlers por ruta `/json`.
- Google Fonts CSS API v38 para Fraunces (mapeo de woff2/unicode-range, vendorizado local).
- unpkg htmx.org@2.0.4 (archivo minificado vendorizado).
- Contrato F3 `get-feasibility-report.md` y `_f3_shared.py` (10 bloques; `feasibility_score`
  con `score` int 0–100 y `confidence`; `administrative_context.upl.codigo/nombre`).