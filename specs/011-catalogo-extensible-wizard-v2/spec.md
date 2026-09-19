# Feature Specification: Catálogo Extensible + Wizard v2

**Feature Branch**: `011-catalogo-extensible-wizard-v2`

**Created**: 2026-09-09

**Status**: Draft

**Input**: User description: "F11 combinada alcance 2+3 del wizard prefactibilidad. 2) Catálogo extensible Datos Abiertos: capa configurable añadible sin rediseño, contrato 23 bloques base intacto, patrón CapaConfig arcgis_utils + construir_params_punto genérico, reutilizar cache, documentar how-to. 3) Mejora wizard validación guiada: preview persistente clic mapa, reordenar pasos si aporta flujo lógico inversión, validación inline más guiada (inline errors + help text). Preservar preview ligero POST /proyectos/preview y 5 campos opcionales persistidos. 7 tools invariante, trazabilidad 5 campos, 486 tests baseline, 23 bloques 19 evaluables HEAD 9641504. En español. Enriquecida tras revisión de 20260831-01-googleai-evaluacion_prefactibilidad_inmobiliaria_ia.md (4 pilares + motores + especificidades Bogotá POT 555) y 20260809-01-perplexity.md (10 temáticas + trazabilidad por capa + 8 herramientas visión)."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Catálogo extensible Datos Abiertos (Priority: P1)

Como desarrollador que mantiene `mcp-bogota-factibilidad`, quiero añadir una nueva capa temática de ArcGIS REST (Datos Abiertos Bogotá / Catastro / SDP) al informe de prefactibilidad de forma declarativa — definiendo solo `CapaConfig` y su `CapaConfig.ruta_consulta` + `construir_params_punto` genérico — sin modificar la orquestación central (`app/main.py:get_feasibility_report`), sin cambiar el scoring, sin crear nueva tool MCP y sin rediseñar el contrato de 23 bloques base, de modo que el nuevo dato aparezca como un bloque más con trazabilidad de 5 campos.

**Why this priority**: Es el habilitador de evolución del producto. Hoy añadir una capa requiere tocar orquestación, modelos, scoring y templates. Con el catálogo, la extensión es lineal (1 config + 1 test), preserva el principio II (modularidad por providers) y III (trazabilidad) de la constitución y blinda el invariante 7 tools / 23 bloques / 19 evaluables. Directamente habilita completar las 10 temáticas recomendadas de `20260809-01-perplexity.md:728-743` (Identificación predial, Contexto administrativo, Accesibilidad vial, Restricciones urbanas, Mercado y valor suelo, Uso económico actual, Movilidad/transporte, Equipamientos cercanos, Obras/entorno, Temporalidad/vigencia) y los 4 pilares de `20260831-01-googleai:8-35` (Legal/Normativa, Mercado, Técnica/Diseño, Financiera) sin acoplar nueva lógica de negocio al orquestador.

**Independent Test**: Puede probarse sin tocar el wizard: definir una capa ficticia `catastro/prueba/MapServer/99` con `CapaConfig` en un test con `httpx.MockTransport`, verificar que `GET /proyectos/{id}/json` incluye el nuevo bloque con `source_name/layer_id/service_url/data_vigencia/query_timestamp` y que `python -m pytest -q` sigue en 486+ tests 0 failed sin regresión en Dockerfile.

**Acceptance Scenarios**:

1. **Given** el catálogo base de 23 bloques intacto, **When** se registra una capa nueva vía `CapaConfig` reutilizando `construir_params_punto`, **Then** el informe incluye el nuevo bloque con los 5 campos de traza y el score no cambia salvo que se declare explícitamente una regla nueva.
2. **Given** una capa nueva con vigencia propia, **When** se consulta un lote con esa capa activa, **Then** la salida NO mezcla vigencias: cada bloque conserva su `data_vigencia` independiente.
3. **Given** una capa nueva que falla con 5xx, **When** se genera el informe, **Then** ese bloque degrada a `estado: "no_encontrado"` con `BLOQUE_DEGRADADO` sin propagar `FUENTE_5XX` al informe completo (degradación por bloque, no fatal).

---

### User Story 2 - Wizard v2 validación guiada + preview persistente (Priority: P2)

Como usuario de la web de prefactibilidad que inicia el flujo con chip/dirección/coordenadas o clic en mapa, quiero que el wizard me guíe paso a paso con un orden lógico de inversión: primero confirmo visualmente el lote en el mapa (preview ligero sin esperar 23 bloques), luego respondo la interrogación de inversión (uso previsto, escala m², presupuesto rango, horizonte meses, aversión riesgo con help text y validación inline inmediata), y finalmente genero el informe completo, sin perder el preview si navego o recargo parcialmente.

**Why this priority**: La interfaz actual (`GET /` → `POST /proyectos` → 303) es de un solo paso y muy básica; no sigue el enfoque en 2 pasos de `20260809-01-perplexity.md:42-61` (1 identificar lote + 2 enriquecer con múltiples fuentes) ni el flujo lógico de inversión de `20260831-01-googleai:8-15` (prefactibilidad cubre 4 pilares: Legal/Normativa POT 555, Mercado, Técnica/Diseño y Financiera). El preview persistente separa costo barato (geometría) de costoso (23 bloques), permite confirmar la UPL y el tratamiento antes de interrogar, y reduce frustración y tasa de abandono.

**Independent Test**: Puede probarse sin catálogo: abrir `GET /`, seleccionar lote por chip `AAA0072LRYN` o clic en mapa (Leaflet 320px) → `POST /proyectos/preview` retorna 200 con `lote.geometry/centroid + upl`; avanzar a interrogación con 5 campos opcionales; validar que `escala_m2 < 36` muestra error inline sin roundtrip completo; recargar paso intermedio y verificar que el preview sigue visible (persistencia client-side HTMX hx-include sin sesión servidor); generar informe y verificar `GET /proyectos/{id}` con 23 bloques.

**Acceptance Scenarios**:

1. **Given** un lote identificado por cualquier medio, **When** el usuario confirma el preview en mapa, **Then** el paso de interrogación queda habilitado y el preview permanece visible al navegar entre pasos sin nueva consulta a fuentes.
2. **Given** el formulario de interrogación, **When** el usuario ingresa `escala_m2` no numérica o `< 36`, **Then** ve error inline inmediato y el submit permanece bloqueado; el servidor también rechaza con 400 si el bypass ocurre.
3. **Given** un reordenamiento de pasos (p.ej. preview → interrogación → confirmación), **When** se evalúa flujo lógico de inversión, **Then** el usuario percibe progresión coherente (identificar → interrogar → decidir) sin pasos redundantes.

---

### User Story 3 - Persistencia interrogación sin regresión (Priority: P3)

Como usuario que creó un proyecto con interrogación, quiero que mis respuestas persistan y se re-muestren al reabrir el proyecto, y que la reevaluación conserve la interrogación original, sin romper proyectos viejos (sin wizard).

**Why this priority**: Garantiza extensibilidad sin migración destructiva. Proyectos de F10 (sin 5 campos) deben leerse como `null` sin error.

**Independent Test**: Crear proyecto con `uso_previsto=residencial, escala_m2=120`; verificar `GET /proyectos/{id}/json` incluye los 5 campos; simular DB de proyecto viejo (fila sin columnas wizard) y verificar que `ProyectoRepositorio` hace `ALTER TABLE ... ADD COLUMN` aditivo sin pérdida.

**Acceptance Scenarios**:

1. **Given** un proyecto con interrogación guardada, **When** se hace `POST /proyectos/{id}/reevaluar`, **Then** la reevaluación conserva los 5 campos originales en el nuevo informe.
2. **Given** una fila antigua sin columnas wizard, **When** se abre el proyecto, **Then** no hay error 500; los campos aparecen vacíos.

---

### Edge Cases

- ¿Qué pasa si el usuario cambia el criterio (chip→dirección) después de haber respondido interrogación? El sistema debe invalidar el preview previo y obligar reconfirmación.
- ¿Cómo maneja el preview una dirección sin `MAPAS_BOGOTA_APIKEY`? Usa fallback World `geocode.arcgis.com/World/GeocodeServer` sin exigir clave (ya implementado en `POST /proyectos/preview`).
- ¿Qué pasa si una capa del catálogo extensible no existe (404) o responde 5xx? Degrada solo ese bloque, no el informe.
- ¿Qué pasa con coordenadas fuera de Bogotá? Preview retorna 404 `FUERA_DE_COBERTURA` sin crear proyecto.
- ¿Cómo se comporta el wizard con JS deshabilitado? El flujo debe degradar a POST tradicional de un solo paso (progressive enhancement HTMX).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema DEBE permitir registrar una nueva capa temática mediante `CapaConfig` (definida en `app/providers/arcgis_utils.py:32`) reutilizando `construir_params_punto(lat,lon)` genérico y `RAIZ_ARCGIS`, sin modificar `app/main.py:get_feasibility_report` más allá de añadir la entrada al catálogo, preservando 7 tools MCP.
- **FR-002**: Cada bloque nuevo del catálogo DEBE exponer trazabilidad completa de 5 campos (`source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp`) y respetar degradación por bloque (5xx → `no_encontrado` + `BLOQUE_DEGRADADO`, no fatal).
- **FR-003**: El contrato base de 23 bloques / 19 evaluables DEBE permanecer intacto; añadir capa no altera `BLOQUES_EVALUABLES` ni `calcular_score` salvo regla explícita documentada; `23 bloques base` es baseline no decrecible.
- **FR-004**: El sistema DEBE documentar en `app/providers/arcgis_utils.py` o `README.md` un how-to mínimo (3 pasos) para añadir capa: 1) definir `CapaConfig`, 2) registrar en catálogo, 3) añadir test con MockTransport + verificar 5 campos.
- **FR-005**: La web DEBE ofrecer `POST /proyectos/preview` ligero (sin 23 bloques) que resuelva lote por `chip|direccion|coordenadas` o coordenadas de clic mapa, retorne `lote{chip,direccion_normalizada,barrio,centroid,geometry}` + `upl{codigo,nombre,localidad}|null` con World fallback sin API, y separe costo barato de costoso.
- **FR-006**: El preview confirmado DEBE persistir visualmente entre pasos del wizard sin nueva consulta a fuentes (client-side `hx-include`/campos ocultos, sin sesión servidor), sobreviviendo a navegación intra-wizard.
- **FR-007**: El paso de interrogación DEBE presentar 5 campos opcionales persistidos (`uso_previsto` enum residencial/comercial/mixto/dotacional/industrial, `escala_m2` number ≥36, `presupuesto_rango` enum bajo/medio/alto, `horizonte_meses` int 6-120, `aversion_riesgo` enum baja/media/alta) con `help text` y validación inline inmediata por campo.
- **FR-008**: La validación DEBE ser dual: inline client-side (HTML5 min/max + mensajes) y server-side (`app/web/main.py:_validar_formulario` extendido) con 400 y error inline si el bypass ocurre; ningún valor inválido persiste ni genera informe.
- **FR-009**: El orden de pasos DEBE seguir lógica de inversión (1 identificar+preview → 1b interrogar → 2 informe); cualquier reordenamiento DEBE justificarse como mejora de flujo lógico y mantenerse `client-side` HTMX sin sesión servidor para MVP.
- **FR-010**: La persistencia `Proyecto` (`app/web/db.py:ProyectoRepositorio`) DEBE migrar de forma aditiva (`PRAGMA table_info` + `ALTER TABLE ADD COLUMN`) para los 5 campos wizard, leyendo filas viejas con `None` sin error 500.
- **FR-011**: `POST /proyectos/{id}/reevaluar` DEBE conservar los 5 campos de interrogación del proyecto original al regenerar el informe.
- **FR-012**: El sistema DEBE preservar `POST /proyectos/preview` y los 5 campos opcionales como parámetros `Form` opcionales en `POST /proyectos` sin romper el flujo legacy de un solo POST.
- **FR-013**: La identidad visual "Bogotá Reverdece" (Fraunces, 5 Pillars, anillo score) y vendorización HTMX 2.0.4 / Leaflet sin CDN DEBE mantenerse sin regresión.
- **FR-014**: El cache LRU+TTL por CHIP (`app/cache.py`) y el fallback World geocoder DEBEN reutilizarse para el preview sin duplicar lógica.
- **FR-015**: `GET /proyectos/{id}` DEBE renderizar el informe ampliado a 17 claves loop + 6 separadas = 23 bloques base con `market_dynamics` incluido (fix H-01), sin ocultar `llm_ready_summary` ni `feasibility_score`.
- **FR-016**: El informe DEBE evidenciar cobertura de los 4 pilares de `20260831-01-googleai:8-35` (Legal/Normativa Decreto 555 2021 con cargas/cesiones/tratamientos, Mercado con dinámicas y oferta, Técnica/Diseño con cabida `technical_feasibility` GeoPandas/Shapely, Financiera con VPN/TIR Montecarlo) y de las 10 temáticas de `20260809-01-perplexity.md:728-743`, manteniendo 23 bloques base como baseline no decrecible.

### Key Entities

- **Proyecto**: Representa una prefactibilidad iniciada por usuario. Atributos: `id`, `nombre`, `criterio_tipo/valor`, `consulta/top_k`, `informe` (JSON 23 bloques), `uso_previsto/escala_m2/presupuesto_rango/horizonte_meses/aversion_riesgo` (opcionales wizard), `created_at/updated_at`. Relación 1:1 con Informe.
- **CapaConfig**: Configuración declarativa de una capa ArcGIS. Atributos: `service_url`, `layer_id`, `source_name`, `ruta_consulta`, `construir_params_punto`. Relación 1:N con Bloque temático.
- **PreviewLote**: Resultado ligero del paso 1. Atributos: `lote{chip,direccion_normalizada,barrio,centroid,geometry}`, `upl{codigo,nombre,localidad}|null`, `manzana` (si disponible). Sin 23 bloques ni scoring.
- **BloqueInforme**: Uno de los 23 bloques del informe con trazabilidad 5 campos. Atributos: `clave`, `titulo`, `estado`, `datos`, `source_traces[]` con `source_name/layer_id/service_url/data_vigencia/query_timestamp`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un desarrollador puede añadir una capa nueva al catálogo en ≤30 minutos siguiendo el how-to (1 `CapaConfig` + 1 test MockTransport) sin modificar `app/main.py` más allá del registro y sin romper 7 tools.
- **SC-002**: `POST /proyectos/preview` responde en <2s para chip `AAA0072LRYN` (cache hit <100ms) y el preview permanece visible al avanzar/retroceder en el wizard sin nueva petición a fuentes.
- **SC-003**: 100% de los campos de interrogación con valor inválido muestran error inline en <500ms y bloquean el submit; el servidor rechaza el bypass con 400 en 100% de los casos.
- **SC-004**: `GET /proyectos/{id}` renderiza 23 bloques base (17 loop + 6 separadas) incluyendo `market_dynamics` con 5 campos de traza por bloque; 0 regresión visual (Fraunces/5 Pillars/anillo intactos).
- **SC-005**: Proyectos creados antes de F11 se leen y reevalúan sin error (5 campos wizard aparecen como `null`); 486 tests baseline se mantienen ≥486 0 failed y `docker build` no regresa.
- **SC-006**: La validación guiada reduce el abandono en paso de interrogación: al menos 80% de los intentos con error inline se corrigen y completan el informe sin soporte (medido por logs o tasa de 400→200).

## Assumptions

- El catálogo extensible es declarativo: una `CapaConfig` por capa y el orquestador itera el catálogo; no se requiere DSL complejo para MVP.
- El wizard mantiene estado client-side (HTMX `hx-include` + campos ocultos) sin sesión servidor ni tabla `wizard_drafts` para MVP; un solo `POST /proyectos` final crea el proyecto.
- El reordenamiento de pasos, si se hace, es menor (p.ej. mover confirmación preview antes de interrogación) y no cambia el modelo de datos.
- `presupuesto_rango` y `horizonte_meses` se persisten como metadata contextual para el analista/LLM; no alimentan `app/financiero.py` en F11 (metadata, no motor).
- No hay auth/multiusuario ni rate limiting en F11; servidor local `127.0.0.1` asume uso interno.
- La validación inline usa HTML5 + mensajes server-side; no se añade JS framework nuevo (HTMX vendorizado basta).
- La capa nueva del catálogo puede ser cualquiera de `serviciosgis.catastrobogota.gov.co/arcgis/rest/services/` con `f=geojson` point query; fuentes que requieran token fuera de `CapaConfig` quedan fuera de alcance F11.
- El esqueleto dual Node/Python de `20260809-01-perplexity.md:805-926` se resuelve en Python (`FastAPI + Jinja2 + HTMX` ya en F5) por decisión de producto; F11 no reintroduce Node y reutiliza los 4 motores preexistentes (RAG ChromaDB `bge-m3`/`qwen3`, Mercado `mercado.py` clustering, Técnico `tecnico.py` GeoPandas/Shapely `financial_analysis`, Financiero Montecarlo) sin modificar `calcular_score` determinista (SC-003).
