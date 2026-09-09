# Feature Specification

**Rama del feature**: `009-ux-web-informe-completo`

**Creado**: 2026-08-31

**Estado**: Draft

**Entrada**: Descripción del usuario: "Feature 9 de mcp-bogota-factibilidad: completar la interfaz web de prefactibilidad para que la página de detalle del proyecto (`proyecto.html`) renderice el informe completo de factibilidad con los 19 bloques evaluables, la evidencia normativa, el score, las advertencias, el resumen ejecutivo, un mapa Leaflet con la geometría del lote, y la identidad contextual (CHIP, dirección, coordenadas, localidad, UPL, manzana). Actualmente solo muestra el anillo de score, la UPL y las advertencias."

---

## User Scenarios & Testing (obligatorio)

### User Story 1 (P1) — Informe completo en la página de detalle

Como usuario de la interfaz web de prefactibilidad, quiero que al crear o consultar un proyecto, la página de detalle muestre el informe completo con todos los bloques de datos del lote para poder evaluar la factibilidad de construcción de forma integral.

**Por qué esta prioridad**: la página de detalle es el producto principal del usuario; sin ella, el informe generado es inaccesible salvo vía JSON.

**Prueba independiente**: crear un proyecto vía POST y verificar que el detalle (GET) contiene: score ring, llm_ready_summary, identidad del lote, contexto administrativo, mapa Leaflet, los 19 bloques evaluables, evidencia normativa, score con razones y advertencias.

**Escenarios de aceptación**:
1. Dado un proyecto completado con informe, cuando se visita la página de detalle, entonces se muestra el score con el anillo SVG y la confianza.
2. Dado un proyecto completado con informe, cuando se visita la página de detalle, entonces se muestra el `llm_ready_summary` como párrafo destacado.
3. Dado un proyecto completado con informe, cuando se visita la página de detalle, entonces se muestra la identidad del lote (CHIP, dirección, coordenadas, manzana, localidad, UPL).
4. Dado un proyecto completado con informe, cuando se visita la página de detalle, entonces se muestra un mapa Leaflet con la geometría del lote y su centroide.
5. Dado un proyecto completado con informe, cuando se visita la página de detalle, entonces se renderizan los 19 bloques evaluables con título, estado badge, dato, interpretación y proveniencia.
6. Dado un proyecto completado con informe, cuando se visita la página de detalle, entonces se muestra la evidencia normativa con artículos, títulos, libros, partes y citas literales.
7. Dado un proyecto completado con informe, cuando se visita la página de detalle, entonces se muestra el score con razones, reglas aplicadas y bloques evaluados/disponibles/no encontrados.
8. Dado un proyecto completado con informe con advertencias, cuando se visita la página de detalle, entonces se muestran las advertencias con código y mensaje.
9. Dado un proyecto completado sin geometría, cuando se visita la página de detalle, entonces el mapa se omite o muestra un estado vacío sin errores.

### User Story 2 (P2) — CSS consistente con la identidad visual

Como diseñadora de la interfaz, quiero que las nuevas secciones del informe sigan la identidad visual "Bogotá Reverdece" (5 Pillars: Fraunces, paleta verde/ambar/crema, composición asimétrica) para mantener consistencia visual.

**Por qué esta prioridad**: la consistencia visual es clave para la credibilidad de la herramienta.

**Escenarios de aceptación**:
1. Los bloques de datos usan tarjetas con borde redondeado, sombra y fondo blanco (`.tarjeta` existente).
2. El mapa Leaflet se integra visualmente dentro del diseño sin romper la retícula.
3. Los badges de estado (`disponible`/`no_encontrado`) usan la paleta de colores existente.
4. La proveniencia de datos se muestra en texto pequeño con la fuente y vigencia.
5. El layout es responsivo (1 columna en móvil, 2 columnas en desktop).

---

## Requirements (obligatorio)

### Functional Requirements

- **FR-001**: La página de detalle (`proyecto.html`) DEBE renderizar los 19 bloques evaluables del informe cuando `proyecto.estado == "completado"`.
- **FR-002**: Cada bloque DEBE mostrar: título en español, badge de estado (`disponible`/`no_encontrado`), dato (serializado), interpretación, y source_trace/source_traces.
- **FR-003**: La página DEBE incluir un mapa Leaflet con la geometría del lote (GeoJSON de `identidad_lote.geometry`) y un marcador en el centroide.
- **FR-004**: El mapa DEBE ser absent-friendly: si `geometry` no está disponible, se omite el mapa sin errores.
- **FR-005**: La página DEBE mostrar `llm_ready_summary` como párrafo destacado cerca del score.
- **FR-006**: La página DEBE mostrar la evidencia normativa (`normative_evidence.items`) con cada ítem: artículo, título, libro, parte, norma y cita literal.
- **FR-007**: La página DEBE mostrar el `feasibility_score` con score numérico, confidence, reasons y rules_applied.
- **FR-008**: Las advertencias (`warnings`) DEBEN renderizarse con código y mensaje.
- **FR-009**: Leaflet.js y leaflet.css DEBEN estar vendorizados en `app/web/static/` (sin CDN).
- **FR-010**: Las nuevas secciones DEBEN seguir la identidad visual "Bogotá Reverdece" (5 Pillars).
- **FR-011**: El layout DEBE ser responsivo (mobile-first con retícula asimétrica existente).
- **FR-012**: Los elementos DEBEN tener `aria-label` y `role` apropiados para accesibilidad.
- **FR-013**: La página DEBE incluir estados de carga/error graceful.

### Non-Functional Requirements

- **NFR-001**: No se añaden dependencias Python nuevas; Leaflet se vendoriza como archivos estáticos.
- **NFR-002**: Las pruebas usan fixtures httpx.MockTransport existentes (sin red real).
- **NFR-003**: El template NO introduce JavaScript framework; usa vanilla JS + HTMX existente.

---

## Success Criteria

- **SC-001**: `uv run pytest -q` pasa con todos los tests existentes + nuevos.
- **SC-002**: La página de detalle renderiza los 19 bloques del informe.
- **SC-003**: El mapa Leaflet carga y muestra la geometría del lote.
- **SC-004**: `bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks` exit 0.
