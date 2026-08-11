# Checklist de Requisitos: RAG normativo del POT (Decreto 555/2021) con consulta de UPL

**Purpose**: Validar la completitud y calidad de la especificación de la Feature 2 (RAG normativo + consulta de UPL) antes de pasar a la planificación
**Created**: 2026-08-10
**Feature**: [spec.md](../spec.md)

## Estructura y Estado

- [x] CHK001 La spec identifica la feature con título, rama (`002-rag-normativo-upl`), fecha de creación (2026-08-10), estado (Draft) e entrada (Input), sin placeholders ni marcadores [NEEDS CLARIFICATION]
- [x] CHK002 La entrada (Input) cita la descripción original del usuario y las decisiones de clarificación del 2026-08-10: UPL + RAG normativo (ambas capacidades), proveedor Ollama local, corpus oficial + script de ingesta, vector store local embebido y dos tools MCP (`get_upl` y `consultar_normativa`)

## Historias de Usuario

- [x] CHK003 La US1 (consultar normativa, P1) declara prioridad, justificación, prueba independiente y 3 escenarios Dado/Cuando/Entonces que cubren resultados relevantes con cita literal, consulta sin resultados y fallo del servicio Ollama
- [x] CHK004 La US2 (consultar UPL, P2) declara prioridad, justificación, prueba independiente y 4 escenarios Dado/Cuando/Entonces que cubren CHIP con UPL, lote sin UPL, coordenadas fuera de Bogotá y dirección válida
- [x] CHK005 La US3 (normativa por UPL, P3) declara prioridad, justificación, prueba independiente y 3 escenarios Dado/Cuando/Entonces que cubren filtro estricto por UPL, sin resultados aplicables y UPL mal formada

## Requisitos Funcionales

- [x] CHK006 Los 14 FR (FR-001 a FR-014) usan DEBE/NO DEBE y son verificables individualmente, con semántica clara y sin ambigüedades
- [x] CHK007 El filtro de UPL (FR-002) es estricto y sin ambigüedad: solo devuelve artículos aplicables a esa UPL (por clasificación de suelo o mención explícita), y su omisión devuelve resultados sin filtrar por territorio; no quedan expresiones ambiguas tipo "filtrar o priorizar"
- [x] CHK008 FR-003 exige cita literal verificable contra el corpus (número y título del artículo) y FR-006 conserva los 5 campos canónicos del contrato de trazabilidad (`source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp`)
- [x] CHK009 FR-010 y FR-011 fijan el provider aislado de Ollama configurable por variables de entorno sin credenciales en código y el fail-fast ante servicio/modelo no disponible; FR-012 y FR-014 declaran NO DEBE (factibilidad F3 y mezcla de vigencias)

## Criterios de Éxito

- [x] CHK010 Los 6 SC (SC-001 a SC-006) son medibles con métricas numéricas: latencias de 15 segundos y 10 segundos, y 100% en cita literal, respuestas "sin resultados", trazabilidad de 5 campos y cobertura de ingesta

## Casos Límite

- [x] CHK011 Los 8 casos límite están identificados: consulta sin resultados relevantes, Ollama no disponible/modelo no instalado, alucinación, lote sin UPL o punto fuera de Bogotá, consulta demasiado amplia, parámetros inválidos, corpus no ingestado e índice vacío, y vigencias

## Entidades y Supuestos

- [x] CHK012 Las 5 Key Entities (UPL, Localidad, Artículo Normativo, Corpus Normativo, Lote) están definidas con sus atributos clave y sus relaciones (pertenencia espacial, ubicación y reutilización del Lote de F1)
- [x] CHK013 Las Assumptions identifican dependencias y supuestos (Ollama en localhost, corpus oficial descargable, capa UPL oficial consultable, consultas puntuales, condiciones normales de rendimiento) y declaran F3 fuera de alcance

## Clarificaciones

- [x] CHK014 Las Clarifications registran las 5 Q&A del 2026-08-10: alcance (UPL + RAG normativo), proveedor de modelos (Ollama local), corpus (descarga oficial + ingesta), almacenamiento de índices (vector store local embebido) y tools MCP expuestas (`get_upl` + `consultar_normativa`)

## Alcance y Gobernanza

- [x] CHK015 La spec está redactada en español (Principio I); los nombres técnicos en inglés se limitan al contrato (tools MCP y campos de salida)
- [x] CHK016 La spec cumple el Principio II (provider aislado con única responsabilidad), el Principio III (trazabilidad por fuente NON-NEGOTIABLE con 5 campos, sin mezclar vigencias) y el Principio IV (fail-fast, distinción entre "dato no encontrado", "lote no encontrado" y error de cobertura)
- [x] CHK017 La spec cumple el Principio V (MVP first): F3 (orquestación unificada lote → UPL → normativa, reporte de factibilidad y `feasibility_score`) está declarada fuera de alcance en la spec
- [x] CHK018 La spec es coherente con la de F1: `get_upl` reutiliza el resolver de lote de F1 (CHIP/dirección/coordenadas) y conserva su semántica de errores y los contratos de trazabilidad

## Notes

- Todos los elementos están desmarcados: el checklist se llena y se revalida tras cada cambio de la spec, antes de `/speckit.plan`.
- La entrada (Input) cita la descripción original del usuario y las decisiones de clarificación tomadas el 2026-08-10; es el texto literal proporcionado y no constituye una decisión de implementación adicional.
- FR-006 conserva los nombres canónicos del contrato de trazabilidad exigidos por la constitución del proyecto (Principio III: trazabilidad de fuentes NON-NEGOTIABLE); son claves del contrato de datos, no una elección de implementación.
- Elementos marcados como incompletos requieren actualizaciones de la spec antes de `/speckit.plan`.
