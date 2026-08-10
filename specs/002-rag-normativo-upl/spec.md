# Feature Specification: RAG normativo del POT (Decreto 555/2021) con consulta de UPL

**Feature Branch**: `002-rag-normativo-upl`

**Created**: 2026-08-10

**Status**: Draft

**Input**: User description: "Feature 2 de mcp-bogota-factibilidad: consultar la UPL (Unidad de Planeamiento Local) de un lote catastral de Bogotá y responder preguntas en lenguaje natural sobre la normativa del POT mediante un RAG normativo 100% local sobre el Decreto 555 de 2021, devolviendo los artículos más relevantes con su texto literal citado y trazabilidad por fuente. Fuera de alcance para esta feature: la orquestación unificada (lote → UPL → normativa en una sola tool) y el reporte consolidado de factibilidad con puntajes (feature F3 futura). Las decisiones de clarificación se tomaron el 2026-08-10: (1) la feature incluye UPL + RAG normativo (ambas capacidades); (2) el proveedor de modelos es local (Ollama); (3) el corpus del Decreto 555/2021 proviene de la descarga oficial + script de ingesta; (4) los índices vectoriales se almacenan en un vector store local embebido, con persistencia en directorio gitignored; (5) F2 expone dos tools MCP: `get_upl` y `consultar_normativa`."

## User Scenarios & Testing *(obligatorio)*

> Historias de usuario priorizadas como viajes de usuario ordenados por importancia. Cada historia es **independientemente comprobable**: implementar solo una de ellas debe producir un MVP viable que entregue valor.

### Historia de Usuario 1 - Consultar la normativa del POT (Prioridad: P1)

Como usuario, quiero hacer una consulta en lenguaje natural sobre la normativa del POT (por ejemplo, "¿qué se puede construir en suelo urbano?" o "¿qué normas aplican a usos industriales?") y recibir los artículos más relevantes del Decreto 555 de 2021 con su texto literal citado y su trazabilidad, para fundamentar decisiones de prefactibilidad en la norma vigente sin leer el decreto completo.

**Por qué esta prioridad**: Es el valor central de la feature: el RAG normativo sobre el Decreto 555 de 2021. Las decisiones urbanísticas se apoyan en el texto de la norma, no en un punto geográfico aislado; sin esta historia no hay MVP de la feature.

**Prueba independiente**: Puede probarse de forma independiente con el corpus del Decreto 555/2021 ya indexado, consultando un tema y verificando que la respuesta contiene los artículos más relevantes con cita literal (número de artículo, título y texto) verificable contra el corpus; también se prueba aquí el caso de consulta sin resultados relevantes.

**Escenarios de aceptación**:

1. **Dado** el corpus del Decreto 555/2021 indexado y el servicio Ollama disponible, **Cuando** el usuario consulta un tema (p. ej., "¿qué se puede construir en suelo urbano?"), **Entonces** el sistema devuelve los artículos más relevantes ordenados por relevancia, con el texto literal de cada artículo citado e identificado por número y título.
2. **Dado** el corpus indexado, **Cuando** el usuario consulta un tema sin piezas sobre el umbral de relevancia, **Entonces** el sistema responde explícitamente "sin resultados" y no inventa contenido.
3. **Dado** el servicio Ollama no disponible o un modelo requerido no instalado, **Cuando** el usuario consulta la normativa, **Entonces** el sistema falla rápido con un mensaje claro y accionable, sin generar una respuesta parcial.

---

### Historia de Usuario 2 - Consultar la UPL de un lote (Prioridad: P2)

Como usuario, quiero consultar la UPL de un lote catastral de Bogotá por su CHIP (y también por dirección o coordenadas, reutilizando el resolver de F1), para conocer la unidad de planeamiento local y la localidad a las que pertenece el lote.

**Por qué esta prioridad**: P2 porque depende del resolver de lote de F1 (ya implementado) pero no del RAG normativo; entrega la llave territorial que F3 usará para enrutar consultas normativas, pero el valor principal de la feature (el RAG) ya está cubierto por la US1.

**Prueba independiente**: Puede probarse de forma independiente consultando un CHIP válido y verificando que la respuesta contiene el código y el nombre de la UPL y la localidad del lote, con trazabilidad de la capa; también se prueba aquí el caso de lote sin UPL asignada.

**Escenarios de aceptación**:

1. **Dado** un CHIP válido de un lote con UPL asignada, **Cuando** el usuario consulta la UPL, **Entonces** el sistema devuelve el código y el nombre de la UPL y la localidad del lote, con la trazabilidad de la capa.
2. **Dado** un CHIP válido de un lote sin UPL asignada, **Cuando** el usuario consulta la UPL, **Entonces** el sistema responde "dato no encontrado" de forma explícita.
3. **Dado** un punto con coordenadas fuera del área de cobertura de Bogotá, **Cuando** el usuario consulta la UPL por coordenadas, **Entonces** el sistema responde un error claro de cobertura.
4. **Dado** una dirección válida y localizable en Bogotá, **Cuando** el usuario consulta la UPL por dirección, **Entonces** el sistema resuelve el lote asociado (reutilizando el resolver de F1) y devuelve su UPL y localidad con trazabilidad.

---

### Historia de Usuario 3 - Consultar la normativa específica de una UPL (Prioridad: P3)

Como usuario, quiero pasar el código de una UPL a `consultar_normativa` para que los resultados se filtren estrictamente a los artículos que aplican a esa UPL (por clasificación de suelo o mención explícita), para conocer la normativa aplicable a un territorio concreto.

**Por qué esta prioridad**: P3 porque es la combinación de las dos capacidades previas (UPL y RAG) como filtro de recuperación — no como orquestación; el valor base ya lo aportan la US1 y la US2 por separado.

**Prueba independiente**: Puede probarse de forma independiente con una UPL conocida y un tema, verificando que los artículos devueltos aplican a esa UPL (por clasificación de suelo o mención explícita) y que la cita literal sigue siendo verificable contra el corpus.

**Escenarios de aceptación**:

1. **Dado** un código de UPL válido y un tema de consulta, **Cuando** el usuario consulta la normativa con el filtro de UPL, **Entonces** el sistema devuelve únicamente los artículos del Decreto 555/2021 que aplican a esa UPL (por clasificación de suelo o mención explícita), con cita literal y trazabilidad.
2. **Dado** un código de UPL válido sin artículos aplicables para el tema consultado, **Cuando** el usuario consulta la normativa, **Entonces** el sistema responde explícitamente "sin resultados".
3. **Dado** un código de UPL mal formado, **Cuando** el usuario consulta la normativa, **Entonces** el sistema rechaza el parámetro con un error claro.

---

### Casos límite (Edge Cases)

- **Consulta normativa sin resultados relevantes**: cuando ninguna pieza del corpus supera el umbral de relevancia (similitud), el sistema responde explícitamente "sin resultados" y nunca inventa artículos ni contenido.
- **Ollama no disponible o modelo no instalado**: el sistema falla rápido con un mensaje claro y accionable que indica el problema concreto (servicio no accesible, modelo de embeddings o modelo de chat no instalado), sin generar una respuesta parcial ni recuperar artículos no verificables.
- **Alucinación**: el sistema solo cita texto literal extraído del corpus; NO DEBE redactar ni resumir contenido que no esté respaldado por un artículo recuperado, y toda cita se identifica con número y título de artículo.
- **Lote sin UPL asignada o punto fuera de Bogotá**: `get_upl` responde "dato no encontrado" cuando el lote no tiene UPL asignada y un error de cobertura cuando el punto está fuera de Bogotá, reutilizando la semántica de errores de F1.
- **Consulta demasiado amplia** (p. ej., "todo el decreto"): el sistema acota la respuesta a los top-k resultados sobre el umbral, sin truncar silenciosamente el texto literal citado de cada artículo recuperado.
- **Parámetros inválidos**: consulta vacía, UPL mal formada o coordenadas fuera de rango se rechazan con un mensaje de error claro.
- **Corpus no ingestado o índice vacío**: el sistema responde un error claro que indica ejecutar el script de ingesta antes de consultar, en lugar de devolver resultados vacíos silenciosos.
- **Vigencias**: el Decreto 555/2021 es un documento con vigencia propia; si el corpus incluyera más documentos en el futuro, cada documento conserva su vigencia y la trazabilidad la expone por fuente (Principio III), sin mezclar vigencias como una sola fotografía temporal.

## Requirements *(obligatorio)*

### Functional Requirements

- **FR-001**: El sistema DEBE aceptar en `consultar_normativa` una consulta en lenguaje natural y devolver los artículos más relevantes del Decreto 555/2021 ordenados por relevancia, con cita literal del texto de cada artículo.
- **FR-002**: El sistema DEBE aceptar en `consultar_normativa` un parámetro opcional de UPL/localidad que, cuando se proporciona, DEBE filtrar estrictamente los resultados y devolver únicamente los artículos aplicables a esa UPL (por clasificación de suelo o mención explícita en el artículo); si se omite el parámetro, la consulta DEBE devolver resultados sin filtrar por territorio.
- **FR-003**: El sistema DEBE citar el texto literal extraído del corpus, identificando el número de artículo y el título del artículo; NO DEBE redactar contenido que no esté respaldado por un artículo recuperado.
- **FR-004**: El sistema DEBE responder explícitamente "sin resultados" cuando ninguna pieza del corpus supere el umbral de relevancia, y NO DEBE inventar contenido.
- **FR-005**: El sistema DEBE permitir en `get_upl` consultar la UPL de un lote por CHIP, dirección o coordenadas (reutilizando el resolver de F1) y devolver el código y el nombre de la UPL y la localidad del lote.
- **FR-006**: El sistema DEBE incluir en toda respuesta la trazabilidad por fuente con los nombres canónicos del contrato: `source_name`, `layer_id` (o identificador de documento), `service_url`, `data_vigencia`, `query_timestamp` (Principio III).
- **FR-007**: El sistema DEBE distinguir con errores o mensajes distintos "lote no encontrado", "lote sin UPL asignada" (dato no encontrado) y "punto fuera de cobertura".
- **FR-008**: El sistema DEBE contar con un script de ingesta reproducible que descarga la fuente oficial del Decreto 555/2021, extrae el texto, lo divide en chunks con metadatos (artículo, título) y lo indexa en el vector store local.
- **FR-009**: El índice DEBE ser un artefacto regenerable y gitignored; la ingesta DEBE verificar la integridad o actualidad del corpus (p. ej., huella del documento fuente) y advertir si el índice está desactualizado.
- **FR-010**: Los modelos de Ollama (embeddings y chat) DEBEN ser configurables por variables de entorno (p. ej., `OLLAMA_BASE_URL`, modelo de embeddings, modelo de chat), sin credenciales en código; el proveedor DEBE ser un provider aislado con una única responsabilidad (Principio II).
- **FR-011**: El sistema DEBE fallar rápido con un mensaje claro y accionable cuando el servicio Ollama no esté disponible o un modelo requerido no esté instalado (Principio IV), sin generar una respuesta parcial.
- **FR-012**: El sistema NO DEBE calcular puntajes de factibilidad ni emitir el reporte consolidado (fuera de alcance; feature F3 futura).
- **FR-013**: El sistema DEBE rechazar parámetros inválidos (consulta vacía, UPL mal formada, coordenadas fuera de rango) con mensajes de error claros.
- **FR-014**: El sistema NO DEBE mezclar vigencias de documentos distintos como una sola fotografía temporal; cada documento DEBE conservar su vigencia explícita en la trazabilidad.

### Key Entities *(incluir si la feature involucra datos)*

- **UPL (Unidad de Planeamiento Local)**: Unidad territorial de planeamiento del POT de Bogotá definida en el Decreto 555/2021. Atributos clave: código UPL, nombre, localidad a la que pertenece y clasificación de suelo que aplica. Se asocia al Lote por pertenencia espacial (el lote cae dentro del polígono de la UPL); está publicada como capa oficial consultable (capa Unidad Planeamiento Local del Mapa de Referencia).
- **Localidad**: División administrativa de Bogotá (código y nombre). Contiene una o más UPL; la UPL se ubica dentro de una localidad.
- **Artículo Normativo**: Unidad de recuperación del RAG normativo. Atributos clave: número de artículo, título, texto literal, sección del decreto a la que pertenece y clasificación de suelo o UPL a la que aplica, cuando el artículo lo precise.
- **Corpus Normativo**: Colección de artículos del Decreto 555/2021 (POT "Bogotá Reverdece 2022-2035") descargada de la fuente oficial, extraída, dividida en chunks e indexada en el vector store local, con metadatos de vigencia y de fuente oficial; cada documento conserva su propia vigencia.
- **Lote**: Unidad predial catastral de Bogotá, entidad central de F1 (CHIP, código catastral, manzana, dirección y geometría). Se reutiliza en F2 como insumo de `get_upl`: toda consulta de UPL resuelve primero el Lote.

## Success Criteria *(obligatorio)*

### Resultados medibles

- **SC-001**: `consultar_normativa` responde una consulta típica con resultados en menos de 15 segundos con Ollama local.
- **SC-002**: El 100% de las respuestas de `consultar_normativa` citan texto literal verificable contra el corpus (artículo + título + texto).
- **SC-003**: El 100% de las consultas sin resultados relevantes responden "sin resultados" de forma explícita.
- **SC-004**: `get_upl` resuelve la UPL de un lote con CHIP válido en menos de 10 segundos, con trazabilidad de la capa.
- **SC-005**: El 100% de las respuestas incluyen los 5 campos de trazabilidad (`source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp`).
- **SC-006**: La ingesta indexa el 100% de los artículos del Decreto 555/2021, verificable contra el documento fuente.

## Assumptions

- Ollama es accesible en localhost para el RAG; la URL base y los modelos de embeddings y de chat son configurables por variables de entorno.
- El texto oficial del Decreto 555/2021 es públicamente descargable desde la fuente oficial (Alcaldía de Bogotá / Secretaría Distrital de Planeación).
- Existe una capa o archivo geográfico oficial de UPL de Bogotá consultable o descargable para `get_upl` (se validará en la fase de investigación/plan).
- El RAG es 100% local: solo hay red local hacia Ollama y la descarga puntual del corpus durante la ingesta.
- Las consultas son puntuales (una consulta por consulta); no se incluyen consultas masivas, históricas ni listados.
- El objetivo de rendimiento SC-001 asume condiciones normales de la máquina local con Ollama.
- Fuera de alcance de esta feature: la orquestación unificada (lote → UPL → normativa en una sola tool), el reporte de factibilidad con puntajes y el `feasibility_score` (feature F3 futura, Principio V).

## Clarifications

Clarificaciones tomadas con el usuario el 2026-08-10:

- **Q**: ¿Qué incluye la Feature 2? → **A**: UPL + RAG normativo (ambas capacidades).
- **Q**: ¿Qué proveedor de modelos usamos? → **A**: Local (Ollama).
- **Q**: ¿De dónde sale el corpus del Decreto 555/2021? → **A**: Descarga oficial + ingesta.
- **Q**: ¿Dónde almacenamos los índices vectoriales? → **A**: Local embebido.
- **Q**: ¿Qué tools MCP expone F2? → **A**: `get_upl` + `consultar_normativa`.
