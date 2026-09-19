# Research: 011-catalogo-extensible-wizard-v2

**Feature**: `011-catalogo-extensible-wizard-v2` | **Date**: 2026-09-09 | **Spec**: [spec.md](./spec.md)

## Resumen

F11 extiende la base HEAD 9641504 (wizard 3 pasos con `POST /proyectos/preview:222-290`, 5 campos wizard migrados `PRAGMA table_info`, 23 bloques/19 evaluables, 486 tests 0 errors) en dos ejes sin romper 7 tools ni scoring: (A) catálogo declarativo de capas ArcGIS (`CapaConfig` + `construir_params_punto` genérico) y (B) wizard v2 con preview persistente client-side + validación guiada. La investigación resuelve las incógnitas que bloqueaban diseño: reutilizar orquestación iterando catálogo vs tocar `get_feasibility_report`, preservar contrato 23 bloques baseline, elegir `hx-include` sin sesión servidor, migración aditiva ya existente, y how-to mínimo sin DSL.

## Decisiones

### R-01 Catálogo declarativo con `CapaConfig` + iteración en orquestador

- **Decision**: Añadir nueva capa como una entrada `CapaConfig(service_url, layer_id, source_name, ruta_consulta, construir_params_punto)` en el catálogo central (lista en `app/providers/arcgis_utils.py` o `app/providers/arcgis.py`), y refactorizar `app/main.py:get_feasibility_report` para iterar el catálogo en lugar de hardcodear cada bloque temático. El bloque nuevo se produce con la misma `SourceTrace` de 5 campos que los 23 base.
- **Rationale**: Hoje é cada bloque `F6 (5 bloques: geotecnia/socioeconomía/regulatorio/patrimonio/movilidad)`, `F7 catastro_data (5 capas)`, `F8 urbanistic_parameters (SDP 2+14)`, `Fase 3 (3 bloques EPT/road/nearby)` está hardcodeado en `app/main.py` (producción de bloque + scoring + template). Con ~15 capas ArcGIS reales más `SDP 2+14` y `mercado.py` F10, el catálogo evita `N×M` cambios. Preserva Principio II (providers aislados) y III (trazabilidad) y el `specs/012-futura-ampliacion/spec.md` candidato 2 (Node) y 3 (token fuera CapaConfig) quedan fuera de alcance; fuentes con token se documentan como no soportadas en F11.
- **Alternatives considered**: (a) Plugin registry con import dinámico — descartado por YAGNI y complejidad de discovery; (b) DSL YAML para capas — descartado por MVP first, el how-to de 3 pasos con Python es suficiente; (c) Tocar orquestador por cada capa — descartado por acoplar nueva lógica de negocio al orquestador y romper FR-001.
- **Evidencia**: `app/providers/arcgis_utils.py:32` `CapaConfig`, `app/providers/arcgis.py` ya usa `construir_params_punto:46` genérico para 23 bloques, `app/cache.py` LRU 128 TTL 3600 reutilizable, `specs/009-ux-web-informe-completo/research.md` documenta referencias ArcGIS `f=geojson` point query.

### R-02 Contrato 23 bloques base intacto, 19 evaluables baseline

- **Decision**: 23 bloques base (17 loop + 6 separadas `lot_identity/administrative_context/normative_evidence/urbanistic_parameters/feasibility_score/llm_ready_summary`) es baseline no decrecible; `BLOQUES_EVALUABLES` 19 permanece en `app/scoring.py:94-114`. Añadir capa NO altera `calcular_score` salvo regla explícita documentada; si la capa aporta penalización/bonificación, se añade una regla `r_nueva_capa` con clamp [0,100] y test de scoring.
- **Rationale**: FR-003 + FR-016 (4 pilares + 10 temáticas) exigen evolución sin romper scoring determinista SC-003. `market_dynamics` F10 ya demostró el patrón: nuevo bloque `market_dynamics` (F10) no tocó `BLOQUES_EVALUABLES` evaluables de F3 salvo reglas `r_contexto_mercado` declaradas.
- **Alternatives**: Recalcular scoring dinámico por número de bloques — descartado por romper clamps y confidence `high ≥10 / medium 5-9 / low ≤4` (cobertura mínima absoluta no proporcional).

### R-03 Wizard v2 estado client-side `hx-include` sin sesión servidor para MVP

- **Decision**: Mantener el wizard sin `wizard_drafts` tabla ni sesión servidor. `POST /proyectos/preview` (ya en `app/web/main.py:222-290`) retorna `lote+upl` ligero (<2s, World fallback) y el paso 1b (interrogación 5 campos) se envía junto al criterio en un solo `POST /proyectos` final via `hx-include` + campos ocultos. El preview persiste visualmente entre pasos sin nueva consulta a fuentes.
- **Rationale**: `app/web/db.py:ProyectoRepositorio` ya migra aditivamente (`PRAGMA table_info` + `ALTER TABLE ADD COLUMN` F5/F11-wizard, 16 cols tras F11). Añadir tabla intermedia rompe V MVP first y duplica estado. HTMX 2.0.4 vendorizado basta para `hx-post/hx-target/hx-indicator` + Leaflet 320px clic ya en `app/web/templates/index.html` (F11 wizard). Reevaluación `POST /proyectos/{id}/reevaluar` conserva 5 campos originales (FR-011).
- **Alternatives**: (a) `wizard_drafts` SQLite — descartado por MVP, reservado para `specs/012` candidato 7 background jobs si escala; (b) Cookie/session server — descartado por Principio II y sin auth en F11 (servidor local 127.0.0.1).

### R-04 Validación inline dual HTML5 + server 400 con help text

- **Decision**: `index.html` details plegable 5 campos con `min="36"` / `min="6" max="120"` / `required` + `help text` por campo (escala ≥36 m² mínimo POT, horizonte 6-120 meses). Server `app/web/main.py:_validar_formulario` extendido valida enum (`uso_previsto` residencial/comercial/mixto/dotacional/industrial, `presupuesto_rango` bajo/medio/alto, `aversion_riesgo` baja/media/alta) y rangos, retorna 400 con error inline si bypass. Ningún valor inválido persiste.
- **Rationale**: FR-007/008 exigen <500ms inline y 100% rechazo server. `DIRECCION_MAX_CHARS` y `PATRON_CHIP` ya validan lote; reutilizar mismo patrón para wizard. `presupuesto_rango/horizonte_meses` son metadata contextual (Assumption F11: no alimentan `app/financiero.py` en F11, solo analista/LLM).
- **Alternatives**: JS framework validación — descartado por "HTMX vendorizado basta" (Assumption) y YAGNI.

### R-05 Migración aditiva ya resuelta, reevaluación conserva interrogación

- **Decision**: Reutilizar migración aditiva ya en `app/web/db.py` ( `_crear_tabla` + `_fila_a_proyecto` con `None` para filas viejas + `ALTER TABLE ADD COLUMN` para 5 campos). `crear`/`actualizar` con 16 cols. `POST /proyectos/{id}/reevaluar` lee `uso_previsto/.../aversion_riesgo` del proyecto original y los re-inyecta al regenerar informe.
- **Rationale**: FR-010/011 + SC-005 exigen que proyectos F10 (sin wizard) lean como `null` sin 500. Ya implementado en HEAD 9641504 para F11-wizard; solo se verifica con `uv run pytest -q` 486 tests y `docker build` sin regresión, no se reimplementa.
- **Evidencia**: `app/web/db.py` HEAD 9641504 ya tiene `_fila_a_proyecto` con compat viejos proyectos `None` y migración `PRAGMA table_info`.

### R-06 Trazabilidad 5 campos + degradación por bloque para catálogo

- **Decision**: Cada bloque nuevo usa `SourceTrace(source_name, layer_id, service_url, data_vigencia, query_timestamp)` con `data_vigencia` propia (no mezcla). 5xx → `estado: "no_encontrado"` + `warnings: ["BLOQUE_DEGRADADO"]` sin `FUENTE_5XX` fatal; UPL ausente → `upl: null` sin warning (ausencia normal). Web reusa `app/cache.py` para preview (FR-014).
- **Rationale**: Principio III NON-NEGOTIABLE + FR-002/016; patrón F6/F7 ya con `asyncio.gather(return_exceptions=True)` degradación por capa. Catálogo nuevo hereda mismo `verificar_body_sin_error` y `construir_params_punto`.
- **Evidencia**: `app/providers/arcgis.py` `RAIZ_ARCGIS`, `app/models.py:SourceTrace:23-34`, `app/main.py:1156 calcular_score` puro determinista.

### R-07 How-to 3 pasos y alcance de fuentes

- **Decision**: Documentar en `app/providers/arcgis_utils.py` docstring o `README.md` cómo añadir capa: 1) definir `CapaConfig`, 2) registrar en catálogo, 3) añadir test `MockTransport` con verificación 5 campos. Fuentes que requieran token fuera de `CapaConfig` fuera de alcance F11 (Assumption).
- **Rationale**: SC-001 ≤30 min sin tocar orquestación más allá del registro. Fuentes `serviciosgis.catastrobogota.gov.co/arcgis/rest/services` con `f=geojson` point query son catálogo válido; token param queda para `specs/012` candidato 3.
- **Alternatives**: Wiki externa — descartado por colocalizar con código.

## Riesgos y mitigaciones

| Riesgo | Mitigación F11 | Fuera de F11 (012) |
|--------|----------------|---------------------|
| Scoring se rompe al añadir bloque | FR-003: `BLOQUES_EVALUABLES` baseline; test `calcular_score` con clamp | — |
| Preview sin API falla | FR-005 World fallback `geocode.arcgis.com/World/GeocodeServer` ya en preview | — |
| Proyectos viejos 500 | PRAGMA migration + `None` default, verificado SC-005 | — |
| Catálogo con token | Fuera de alcance, how-to lo declara | Candidato 3 |
| Scraping vivo FincaRaíz | Fuera de alcance | Candidato 1 |
| Rate limiting | Sin auth, servidor local 127.0.0.1, YAGNI | Candidato 4 |

## Referencias verificadas

- `app/providers/arcgis_utils.py:32` CapaConfig + `construir_params_punto:46`, `app/cache.py` LRU+TTL, `app/main.py:get_feasibility_report:464` orquestación 23 bloques, `app/scoring.py:94-114` 19 evaluables, `app/web/main.py:222-290` preview ligero, `app/web/db.py` migración PRAGMA, `app/models.py:SourceTrace:23-34`, `20260809-01-perplexity.md:728-743` 10 temáticas, `20260831-01-googleai:8-35` 4 pilares + motores, `HEAD 9641504` 5 files wizard.
