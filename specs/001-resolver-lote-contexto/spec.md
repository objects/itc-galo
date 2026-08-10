# Feature Specification: Resolver lote con contexto temático

**Rama del feature**: `master`

**Creado**: 2026-08-10

**Estado**: Draft

**Entrada**: Descripción del usuario: "Feature 1 (MVP) de mcp-bogota-factibilidad: un servidor MCP que permite a un usuario consultar un lote catastral de Bogotá por CHIP, por dirección o por coordenadas, enriquecerlo con contexto temático (valor de referencia catastral, destino económico, reservas viales y obras públicas) y obtener un resumen consolidado del lote. Fuera de alcance para esta feature: consulta de UPL (quedó para la feature de RAG normativo), RAG normativo del POT (Decreto 555 de 2021) y el reporte consolidado de factibilidad (feature posterior)."

## User Scenarios & Testing *(obligatorio)*

> Historias de usuario priorizadas como viajes de usuario ordenados por importancia. Cada historia es **independientemente comprobable**: implementar solo una de ellas debe producir un MVP viable que entregue valor.

### Historia de Usuario 1 - Consultar un lote por CHIP y obtener su resumen con contexto (Prioridad: P1)

Como usuario, quiero consultar un lote catastral de Bogotá escribiendo su CHIP y recibir un resumen consolidado que incluya su contexto temático (valor de referencia catastral, destino económico, reservas viales y obras públicas), para conocer rápidamente las características del lote sin revisar múltiples fuentes por separado.

**Por qué esta prioridad**: El CHIP es el identificador oficial del predio y permite resolver el lote de forma directa y confiable; es la vía de menor fricción y la que entrega el valor principal de la feature: el resumen consolidado. Sin esta historia no hay MVP.

**Prueba independiente**: Puede probarse de forma independiente consultando un CHIP válido y verificando que la respuesta contiene la identidad del lote (CHIP, manzana, dirección) y el contexto temático con su trazabilidad, sin requerir dirección ni coordenadas. El caso de CHIP inexistente también se prueba aquí.

**Escenarios de aceptación**:

1. **Dado** un CHIP válido de un lote catastral de Bogotá, **Cuando** el usuario consulta el lote por CHIP, **Entonces** el sistema identifica el lote y devuelve un resumen consolidado con la identidad del lote, el contexto temático disponible y la trazabilidad por fuente.
2. **Dado** un CHIP válido cuyo lote no tiene datos para alguna temática (por ejemplo, ninguna obra pública asociada), **Cuando** el usuario consulta el lote, **Entonces** el resumen distingue explícitamente "dato disponible" de "dato no encontrado" para esa fuente, sin presentar vacíos como ceros ni omitir el dato.
3. **Dado** un CHIP inexistente o mal formado, **Cuando** el usuario consulta el lote, **Entonces** el sistema responde con un error claro y accionable que indica que no se encontró ningún lote con ese CHIP.

---

### Historia de Usuario 2 - Consultar un lote por dirección (Prioridad: P2)

Como usuario, quiero consultar un lote catastral de Bogotá escribiendo una dirección, para identificar el lote asociado cuando no conozco su CHIP.

**Por qué esta prioridad**: P2 porque amplía la accesibilidad de la feature (muchos usuarios no conocen el CHIP), pero depende de un paso intermedio de localización de la dirección que requiere una credencial opcional y presenta mayor riesgo de ambigüedad. El valor principal ya está cubierto por la consulta por CHIP.

**Prueba independiente**: Puede probarse de forma independiente consultando una dirección conocida y localizable de Bogotá y verificando que el sistema resuelve el lote asociado y devuelve su resumen; también se prueba el caso de dirección no localizable.

**Escenarios de aceptación**:

1. **Dado** una dirección válida y localizable en Bogotá, **Cuando** el usuario consulta el lote por dirección, **Entonces** el sistema identifica el lote asociado y devuelve su resumen consolidado con contexto.
2. **Dado** una dirección que no puede localizarse (no encontrada o ambigua), **Cuando** el usuario consulta el lote, **Entonces** el sistema responde con un error claro indicando que la dirección no pudo localizarse, sin inventar ni asumir un lote.
3. **Dado** una dirección que corresponde a más de un lote candidato, **Cuando** el usuario consulta el lote, **Entonces** el sistema presenta los candidatos o solicita precisión adicional, en lugar de elegir uno arbitrariamente.

---

### Historia de Usuario 3 - Consultar un lote por coordenadas (Prioridad: P3)

Como usuario, quiero consultar un lote catastral de Bogotá indicando un punto por coordenadas geográficas, para identificar el lote que contiene ese punto.

**Por qué esta prioridad**: P3 porque es la vía menos frecuente y la más técnica, pensada para integraciones y usos geoespaciales; no es imprescindible para el valor principal de la feature, pero completa la resolución del lote por los tres medios previstos.

**Prueba independiente**: Puede probarse de forma independiente consultando un punto que cae dentro de un lote catastral conocido de Bogotá y verificando que el sistema resuelve ese lote; también se prueba el rechazo de puntos fuera de Bogotá.

**Escenarios de aceptación**:

1. **Dado** un punto con coordenadas dentro de un lote catastral de Bogotá, **Cuando** el usuario consulta el lote por coordenadas, **Entonces** el sistema identifica el lote que contiene el punto y devuelve su resumen consolidado.
2. **Dado** un punto con coordenadas fuera del área de Bogotá, **Cuando** el usuario consulta el lote, **Entonces** el sistema responde con un error claro indicando que el punto está fuera del área de cobertura.
3. **Dado** un punto sobre el límite entre dos o más lotes o sin lote asociado, **Cuando** el usuario consulta el lote, **Entonces** el sistema indica que no hay un lote único o que no encontró lote, según corresponda.

---

### Casos límite (Edge Cases)

- **CHIP inexistente o mal formado**: el sistema responde "lote no encontrado" con un error claro y accionable, distinto del estado "dato no encontrado" por fuente.
- **Dirección sin geocodificar (no encontrada o ambigua)**: el sistema responde "dirección no localizada" y nunca inventa un lote; si hay varios candidatos, los presenta o pide precisión.
- **Coordenadas fuera de Bogotá**: el sistema responde un error claro de cobertura.
- **Dato disponible vs. dato no encontrado por fuente**: por cada fuente temática, el resumen distingue explícitamente ambos estados; un dato no aplicable se reporta como no encontrado, no como cero ni como vacío silencioso.
- **Mezcla de vigencias**: los datos de vigencias distintas nunca se presentan como una sola fotografía temporal; cada dato conserva su vigencia explícita.
- **Servicio de datos no disponible (fallo del lado del servidor de la fuente, p. ej. 5xx)**: el sistema responde un error explícito y accionable indicando qué fuente falló, y no lo confunde con "dato no encontrado".
- **Falta de credencial de localización de direcciones**: la consulta por dirección falla rápido con un mensaje claro; las consultas por CHIP y por coordenadas siguen funcionando.

## Requirements *(obligatorio)*

### Functional Requirements

- **FR-001**: El sistema DEBE permitir consultar un lote catastral de Bogotá por su CHIP y devolver la identidad del lote (CHIP, manzana y dirección normalizada cuando esté disponible).
- **FR-002**: El sistema DEBE permitir consultar un lote catastral por dirección, localizando primero la dirección dentro de Bogotá; si la dirección no puede localizarse, DEBE responder "dirección no localizada" sin inventar un lote.
- **FR-003**: El sistema DEBE permitir consultar un lote catastral por coordenadas geográficas dentro de Bogotá; si el punto está fuera del área de cobertura, DEBE responder un error claro.
- **FR-004**: El sistema DEBE enriquecer el lote resuelto con contexto temático de valor de referencia catastral, destino económico, reservas viales y obras públicas, a partir de las fuentes públicas oficiales de datos de Bogotá.
- **FR-005**: El sistema DEBE generar un resumen consolidado del lote que presente, en un formato estructurado, la identidad del lote y el contexto temático disponible.
- **FR-006**: El sistema DEBE incluir para cada dato presentado la trazabilidad de su origen: nombre de la fuente, capa o tema consultado, URL del servicio, vigencia del dato y marca de tiempo de la consulta (nombres canónicos del contrato: `source_name`, `layer_id`, `service_url`, `data_vigencia`, `query_timestamp`).
- **FR-007**: El sistema DEBE distinguir explícitamente "dato disponible" de "dato no encontrado" por cada fuente temática; un dato ausente o no aplicable DEBE reportarse como no encontrado y no como cero o vacío.
- **FR-008**: El sistema NO DEBE mezclar datos de vigencias distintas como una sola fotografía temporal; DEBE conservar y exponer la vigencia de cada dato.
- **FR-009**: El sistema DEBE responder con un error claro y accionable cuando una fuente de datos no esté disponible (fallo del lado del servidor de la fuente), indicando qué fuente falló, y DEBE distinguir ese caso de "dato no encontrado".
- **FR-010**: El sistema DEBE fallar rápido con un mensaje claro cuando falte la credencial necesaria para localizar direcciones, y DEBE permitir las consultas por CHIP y por coordenadas sin esa credencial.
- **FR-011**: El sistema NO DEBE calcular ni emitir puntajes de factibilidad ni inferir reglas urbanísticas ausentes en las fuentes; el resumen del lote DEBE ser descriptivo.
- **FR-012**: El sistema DEBE rechazar consultas con parámetros inválidos (CHIP mal formado, coordenadas fuera de rango, dirección vacía) con un mensaje de error claro.

### Key Entities *(incluir si la feature involucra datos)*

- **Lote**: Unidad predial catastral de Bogotá. Atributos clave: CHIP (identificador oficial del predio), código catastral del lote, manzana a la que pertenece, dirección normalizada y ubicación geográfica (geometría y centroide). Es la entidad central: toda consulta (por CHIP, dirección o coordenadas) resuelve a un Lote, y el contexto temático se asocia a él.
- **Valor de Referencia**: Valor de referencia catastral del terreno publicado por el catastro oficial, con su vigencia. Se asocia al Lote directamente o a su manzana.
- **Destino Económico**: Uso o destino económico predominante del Lote según el catastro oficial, con su vigencia.
- **Reserva Vial**: Zona de reserva vial del ordenamiento territorial que afecta o se superpone al Lote, cuando aplica; su ausencia se reporta como "dato no encontrado".
- **Obra Pública**: Obras públicas de la gestión pública distrital cercanas al Lote, cuando aplica; su ausencia se reporta como "dato no encontrado".

## Success Criteria *(obligatorio)*

### Resultados medibles

- **SC-001**: El resumen de un lote con CHIP válido se obtiene en menos de 10 segundos desde el inicio de la consulta.
- **SC-002**: El 100% de las respuestas distingue "dato disponible" de "dato no encontrado" por fuente temática.
- **SC-003**: Toda respuesta incluye el origen (fuente, capa y URL del servicio) y la vigencia de cada dato presentado.
- **SC-004**: Los datos de distintas vigencias nunca se presentan como una sola fotografía temporal; en toda respuesta con más de una vigencia, cada dato conserva su vigencia explícita.
- **SC-005**: El 100% de las consultas con CHIP válido entregan el resumen consolidado con la identidad del lote.
- **SC-006**: El 100% de las consultas con CHIP inexistente, dirección no localizable o coordenadas fuera de Bogotá terminan en un error claro y accionable, sin inventar datos.

## Assumptions

- Las fuentes de datos (catastro oficial, ordenamiento territorial y gestión pública de Bogotá) son públicas y accesibles para las consultas por CHIP y por coordenadas; la localización de direcciones puede requerir una credencial opcional, sin la cual las consultas por dirección no están disponibles.
- El usuario de la feature es una persona o agente que usa las capacidades de consulta; no se definen roles ni permisos adicionales en esta feature.
- El resumen del lote es descriptivo: presenta hechos observados en las fuentes; la evaluación de factibilidad y cualquier puntaje asociado quedan fuera de alcance (feature posterior).
- Los datos de las fuentes pueden tener vigencias distintas; la feature las conserva y las expone sin mezclarlas.
- La cobertura geográfica es el área de Bogotá; los puntos fuera de esta área se rechazan.
- Las consultas son puntuales (un lote por consulta); no se incluyen consultas masivas, históricas ni listados.
- Las obras públicas se presentan como contexto cercano al lote según los criterios de la propia fuente; no se define un radio específico en esta feature.
- El objetivo de rendimiento SC-001 asume condiciones de red normales.
- Fuera de alcance de esta feature: la consulta de UPL (queda para la feature de RAG normativo), el RAG normativo del POT (Decreto 555 de 2021) y el reporte consolidado de factibilidad (feature posterior).
