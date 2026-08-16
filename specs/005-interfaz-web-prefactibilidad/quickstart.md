# Quickstart: Interfaz web de prefactibilidad (Feature 5)

**Fecha**: 2026-08-16 | **Feature**: `005-interfaz-web-prefactibilidad`

## 1. Instalación

```bash
# Extra web (FastAPI + uvicorn + jinja2 + python-multipart); no afecta el runtime MCP
pip install -e ".[web]"
```

## 2. Ejecución

```bash
# Script de consola (extra web)
web-mcp-bogota-factibilidad

# O con uvicorn sobre la factory
uvicorn "app.web.main:crear_app_web" --factory --host 127.0.0.1 --port 8000
```

Variables de entorno (opcionales, `.env.example`):

| Variable | Default | Descripción |
|---|---|---|
| `WEB_HOST` | `127.0.0.1` | Host de la interfaz web |
| `WEB_PORT` | `8000` | Puerto de la interfaz web |
| `PROYECTOS_DB_PATH` | `.data/proyectos.db` | Base SQLite de proyectos (estado derivado, gitignored) |

El resto del entorno es el de siempre (`MAPAS_BOGOTA_APIKEY` solo si se resuelve por
dirección; `OLLAMA_*`/`VECTOR_DB_PATH` para el RAG). La app web construye su PROPIO
`ServidorLotes` (providers reales) en el lifespan y lo cierra con `aclose()` — no comparte
estado con el proceso MCP por stdio.

## 3. Uso

1. Abrir `http://127.0.0.1:8000/`.
2. **Crear**: llenar el formulario (nombre, criterio `chip`/`direccion`/`coordenadas`, valor,
   consulta normativa opcional, top_k 1–6) → se evalúa, se persiste y se redirige al detalle.
3. **Listar**: el índice muestra los proyectos (más recientes primero).
4. **Ver detalle**: anillo de score (heurístico, determinista — sin interpretación normativa
   inventada), UPL/localidad, warnings, o caja de error.
5. **Re-evaluar**: `POST /proyectos/{id}/reevaluar` actualiza el mismo proyecto.
6. **JSON**: `GET /proyectos/{id}/json` expone el informe F3 completo (10 bloques).

## 4. Rutas

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Formulario + lista de proyectos |
| POST | `/proyectos` | Crear y evaluar (303 → detalle) |
| GET | `/proyectos/{id}` | Detalle del proyecto |
| POST | `/proyectos/{id}/reevaluar` | Re-evaluar conservando id |
| GET | `/proyectos/{id}/json` | Informe JSON (10 bloques) |

## 5. Mapeo de errores (resumen)

`PARAMETROS_INVALIDOS`→400 · `LOTE_NO_ENCONTRADO`/`DIRECCION_NO_LOCALIZADA`/
`FUERA_DE_COBERTURA`/`LOTE_SIN_UPL`/`DATO_NO_ENCONTRADO_POR_FUENTE`→404 · `FUENTE_5XX`→502
(un 5xx NUNCA se degrada a "no encontrado") · `CREDENCIAL_FALTANTE`/`CORPUS_NO_INGESTADO`/
`OLLAMA_NO_DISPONIBLE`→503 · desconocido→500. Detalle completo:
[contracts/interfaz-web-prefactibilidad.md](contracts/interfaz-web-prefactibilidad.md).

## 6. Pruebas

```bash
# Solo la capa web (contract + smoke, sin red real ni Ollama)
pytest tests/contract/test_proyectos_repositorio.py tests/contract/test_web_rutas.py tests/smoke/test_web.py -q

# Suite completa (263 tests)
pytest tests/ -q
```

## 7. Estructura de la capa web

```
app/web/
├── main.py          # factory crear_app_web() + rutas US1/US2 + _error_a_http
├── db.py            # Proyecto (pydantic) + ProyectoRepositorio (sqlite3)
├── templates/       # base.html, index.html, proyecto.html, error.html
└── static/          # htmx.min.js (2.0.4), fonts/ (6 woff2 Fraunces),
                     # fonts.css, estilos.css (5 Pillars)
```