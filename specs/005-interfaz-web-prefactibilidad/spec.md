# Feature Specification

**Rama del feature**: `005-interfaz-web-prefactibilidad`

**Creado**: 2026-08-16

**Estado**: Implementada

**Entrada**: Descripción del usuario: "Feature 5 de mcp-bogota-factibilidad: interfaz web de prefactibilidad. El usuario podrá crear, listar, ver y re-evaluar proyectos de prefactibilidad de un lote (por CHIP, dirección o coordenadas) desde el navegador, reutilizando la lógica de dominio de `get_feasibility_report` (F3) SIN protocolo MCP. La capa web es FastAPI + Jinja2 + HTMX, sin build, y los proyectos se persisten en SQLite."

Decisiones de la especificación (2026-08-16):
1. **Reutilización directa de `ServidorLotes`, sin MCP**: la capa web construye SU PROPIO `ServidorLotes` en el lifespan (providers reales) y lo cierra al terminar (`aclose`); no usa los singletons `servidor_lotes`/`mcp` de `app.main`. Inyección de dependencias (`crear_app_web(servidor_lotes=..., repositorio=...)`) para pruebas sin red.
2. **Proyectos persistidos**: cada evaluación es un `Proyecto` (SQLite, `sqlite3` stdlib) con id, nombre, criterio, consulta, top_k, estado (`completado`/`fallido`), informe o error y marcas de tiempo; se pueden re-evaluar conservando el id.
3. **Errores de evaluación NO se lanzan**: se persisten como proyecto `fallido` y se exponen con status HTTP mapeado (400/404/502/503/500); las validaciones de formulario sí fallan rápido con 400 (FR-012).
4. **Identidad visual (5 Pillars)**: tipografía Fraunces variable, paleta "Bogotá Reverdece" (verde profundo + ámbar sobre crema), una única animación (anillo de score), composición asimétrica y textura de curvas de nivel SVG. HTMX 2.0.4 vendorizado (sin CDN).
5. **Sin tools MCP nuevas**: siguen las 7 de F1–F3; la interfaz web es una capa de presentación adicional.

---

## Contexto y problema

El producto expone 7 tools MCP por stdio (F1–F3) para resolver lotes, consultar UPL/normativa y generar informes de factibilidad. El informe `get_feasibility_report` (F3) ya orquesta 10 bloques con score heurístico determinístico y trazabilidad por fuente. Sin embargo, todo el acceso es por protocolo MCP (cliente de escritura de código); **no hay una forma visual de crear, consultar y comparar evaluaciones** para un usuario no técnico (p. ej. un analista de planeación).

**Problema**: los informes de factibilidad viven solo como respuestas JSON transitorias de una sesión MCP; no se persisten, no se listan, no se re-evalúan. Un analista que quiere comparar la factibilidad de varios lotes debe repetir llamadas MCP y guardar los JSON manualmente.

## Objetivo

Interfaz web (FastAPI + Jinja2 + HTMX) que permite: **US1** crear una evaluación de prefactibilidad desde un formulario (CHIP, dirección o coordenadas; consulta normativa opcional; top_k) y listar los proyectos; **US2** ver el detalle de un proyecto (anillo de score, UPL, warnings o error), re-evaluarlo y obtener su informe JSON. La capa web reutiliza `ServidorLotes.get_feasibility_report` con providers reales, persiste los proyectos en SQLite y mapea la taxonomía de errores a status HTTP.

---

## User Scenarios & Testing (obligatorio)

### User Story 1 (P1) — Crear y listar proyectos de prefactibilidad

Como analista de planeación, quiero crear una evaluación de prefactibilidad de un lote desde el navegador (por CHIP, dirección o coordenadas) y ver la lista de mis proyectos, para iniciar un análisis sin escribir código MCP.

**Por qué esta prioridad**: es el núcleo de la feature — sin crear y listar no hay interfaz útil; el resto (detalle, re-evaluación, JSON) depende de que exista el proyecto.

**Prueba independiente**: `POST /proyectos` con un CHIP válido persiste un proyecto `completado` y redirige (303) a `/proyectos/{id}`; `GET /` lista los proyectos; un CHIP inexistente persiste un proyecto `fallido` con `LOTE_NO_ENCONTRADO` y `/proyectos/{id}/json` responde 404 (no 500).

### User Story 2 (P2) — Ver detalle, re-evaluar y exportar JSON

Como analista de planeación, quiero ver el detalle de un proyecto (score, UPL, warnings o error), re-evaluarlo cuando cambie el contexto y obtener su informe JSON, para compartir y comparar resultados.

**Por qué esta prioridad**: completa el ciclo de vida del proyecto; la re-evaluación conserva el id y el JSON es la forma de integrarse con otras herramientas.

**Prueba independiente**: `GET /proyectos/{id}` renderiza el detalle con el anillo de score; `POST /proyectos/{id}/reevaluar` re-evalúa y redirige al mismo id; `GET /proyectos/{id}/json` expone el informe completo (10 bloques).

---

## Requisitos Funcionales (FR)

### US1 — Crear y listar

- **FR-001** `GET /`: renderiza `index.html` con el formulario de nueva evaluación y la lista de proyectos (los más recientes primero). Sin proyectos → mensaje de lista vacía.
- **FR-002** `POST /proyectos`: recibe `nombre`, `criterio_tipo` (`chip`|`direccion`|`coordenadas`), `criterio_valor`, `consulta` (opcional) y `top_k` (default 3); construye los kwargs de `get_feasibility_report`, evalúa y persiste el proyecto.
- **FR-003** El formulario valida fail-fast (HTTP 400): nombre obligatorio, criterio válido, valor obligatorio, `consulta` ≤ 500 caracteres (`CONSULTA_MAX_CHARS`), `top_k` entre 1 y 6 (`TOP_K_MAX`). Coordenadas en formato `latitud,longitud` numérica.
- **FR-004** El resultado de evaluación exitoso se persiste con `estado="completado"` e `informe` (dict de 10 bloques); un error de evaluación se persiste con `estado="fallido"` y `error` (`{code, message, source_name}`), sin lanzar excepción.
- **FR-005** Tras persistir, `POST /proyectos` responde `303 See Other` con `Location: /proyectos/{id}` (PRG: evitar re-POST al refrescar).

### US2 — Detalle, re-evaluación y JSON

- **FR-006** `GET /proyectos/{id}`: renderiza `proyecto.html` con el detalle (criterio, fechas, estado; score/confianza + UPL + warnings si `completado`, o caja de error si `fallido`). Proyecto inexistente → 404.
- **FR-007** `POST /proyectos/{id}/reevaluar`: re-evalúa con los mismos criterios del proyecto, actualiza el estado/informe/error y la marca `actualizado_en`, conservando `id` y `creado_en`; responde 303 a `/proyectos/{id}`.
- **FR-008** `GET /proyectos/{id}/json`: devuelve el informe completo (10 bloques) en JSON; si el proyecto es `fallido`, devuelve `{"error": ...}` con el status HTTP mapeado; inexistente → 404.

### Mapeo de errores (capa web)

- **FR-009** La taxonomía canónica (`app/errores.py`, 10 códigos) se traduce a status HTTP: `PARAMETROS_INVALIDOS`→400; `LOTE_NO_ENCONTRADO`/`DIRECCION_NO_LOCALIZADA`/`FUERA_DE_COBERTURA`/`LOTE_SIN_UPL`/`DATO_NO_ENCONTRADO_POR_FUENTE`→404; `FUENTE_5XX`→502; `CREDENCIAL_FALTANTE`/`CORPUS_NO_INGESTADO`/`OLLAMA_NO_DISPONIBLE`→503; desconocido→500. Un 5xx NUNCA se degrada a "no encontrado".
- **FR-010** Peticiones a rutas `/json` con error de aplicación responden JSON `{"error": {...}}`; las rutas HTML responden la plantilla `error.html` con el mismo status.
- **FR-011** Errores inesperados (no tipificados) → 500 con `ERROR_INTERNO`, sin enmascarar ni degradar (fail loud).

### Infraestructura

- **FR-012** La app web construye su propio `ServidorLotes` (providers reales) en el lifespan y lo cierra con `aclose()`; `crear_app_web(servidor_lotes=None, repositorio=None)` permite inyectar providers simulados y un repositorio temporal en pruebas.
- **FR-013** Los estáticos (HTMX 2.0.4, Fraunces woff2, `fonts.css`, `estilos.css`) se sirven desde `/static` (vendorizados, sin CDN); plantillas empaquetadas vía `package-data` en `pyproject.toml`.
- **FR-014** La interfaz web NO añade tools MCP: el servidor MCP (`tests/smoke/test_main.py`) permanece con EXACTAMENTE las 7 tools de F1–F3.

---

## Requisitos No Funcionales / Success Criteria (SC)

- **SC-001** La suite completa (`tests/` — contract + smoke) pasa en verde: 263 tests (259 previos + 4 smoke web).
- **SC-002** La interfaz web es 100 % testeada sin red real ni Ollama: `TestClient` con `server_lotes_f3` + `NormativaProviderStub` + `ProyectoRepositorio(tmp_path)`.
- **SC-003** Identidad visual "Bogotá Reverdece" (5 Pillars): Fraunces variable vendorizada (sin Inter/Roboto/Arial/system-ui), paleta verde profundo + ámbar sobre crema, UNA animación (anillo de score), composición asimétrica, textura de curvas de nivel SVG.
- **SC-004** El score del informe se muestra sin interpretación normativa inventada (FR-014 de F3): la UI solo describe datos reales de las fuentes.
- **SC-005** La persistencia es idempotente y atómica por proyecto: crear/re-evaluar nunca corrompe la base (transacción por operación); un fallo de evaluación NO bloquea la creación del proyecto (se persiste `fallido`).