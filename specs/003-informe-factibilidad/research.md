# Research: Informe de factibilidad orquestado (`get_feasibility_report`)

**Fase**: Phase 0 del comando `/speckit.plan` | **Fecha**: 2026-08-12
**Feature**: [spec.md](spec.md) | **Estado**: Resuelto — todas las decisiones zanjadas, sin marcadores de aclaración pendiente

## Alcance

Esta investigación resuelve las decisiones técnicas de la Feature 3 (orquestación unificada
lote → UPL → contexto temático → evidencia normativa → scoring heurístico en la tool
`get_feasibility_report`) antes de diseñar el modelo de datos y los contratos, con base en
la spec aprobada (`spec.md`: 3 historias de usuario, 14 FR, 6 SC y 12 casos límite), en la
constitución v1.0.0 (`.specify/memory/constitution.md`) y en las clarificaciones del
2026-08-12 registradas en la spec (bloque `economic_context` con destino económico desde la
fuente catastral viva, scoring 100 % determinístico sin LLM, `consulta` opcional + automática).

Se incorporan como **hechos** (no se re-investigan) los hallazgos ya verificados en vivo por
el research previo de F1/F2 y la exploración de `app/`:

- **A. Fuente de destino económico**: la búsqueda por CHIP de Mapas Bogotá
  (`/PMBWeb/web/buscar`, `cmd=direccion_chip`) NO expone destino económico (solo OBJECTID,
  CODIGO_POSTAL, VALUE, NOMBRE, BARRIO, GEOMETRY); el destino económico vive en la **capa
  tabular** ArcGIS `catastro/lote/MapServer/3` (nombre "Predio"), pública sin auth, con
  campos `PRECDESTIN` (dominio D_PreDestino, 28 códigos), `PRECUSO` (dominio D_UsoTUso),
  `PREAUSO`, `PREVACTUAL`, `PREDIRECC`, `PRENBARRIO`, `PREATERRE`, `PREACONST`,
  `PRECEDCATA`, `PRENUPRE`, `BARMANPRE`, `PRECMANZ`, `PRECBARRIO`. **Obligatorio usar
  `f=pjson`** en esta capa (no tiene SHAPE; `f=geojson` responde 400).
- **B. Puntos de integración en `app/main.py`**: 6 tools registradas programáticamente en
  `crear_servidor_mcp`; métodos privados reutilizables de `ServidorLotes`
  (`_resolver_lote_por_chip`, `_resolver_lote_por_candidato`, `_resolver_lote_por_punto`,
  `_consultar_contexto_seguro`, `_consultar_upl_por_punto`, `_respuesta_multiples_candidatos`,
  `_lote_a_contrato`, `_identidad_a_contrato`, `_error_chip_no_encontrado`); validadores
  `_validar_chip` y `_validar_coordenadas`; clasificador `_error_de_fuente` (10 códigos);
  modelos `SourceTrace`, `Lote`, `DatoTematico`, `ValorReferencia`, `DestinoEconomico`
  (definido pero SIN USO), `ReservaVial`, `ObraPublica`, `ContextoTematico`, `UPL`,
  `Localidad`, `Chunk`, `ArticuloNormativo`, `CorpusInfo`; providers `ArcGISProvider`
  (temáticas en paralelo con fail-fast), `UPLProvider`, `NormativaProvider`,
  `MapasBogotaProvider`.
- **C. Decisiones del usuario 2026-08-12** (ya en la spec, NO se reabren): destino
  económico desde fuente catastral viva (NO `destinolt`); score e interpretaciones 100 %
  determinísticos sin LLM; `consulta` opcional con construcción automática desde el contexto
  del lote; degradación deliberada (FR-009/FR-012): RAG no disponible → `normative_evidence`
  vacío + warning (NO error), UPL ausente → `upl: null` + warning (NO `LOTE_SIN_UPL`), dato
  por fuente → estado `no_encontrado` a nivel de bloque; errores fatales del reporte:
  `PARAMETROS_INVALIDOS`, `LOTE_NO_ENCONTRADO`, `FUERA_DE_COBERTURA`,
  `DIRECCION_NO_LOCALIZADA`, `CREDENCIAL_FALTANTE`, `FUENTE_5XX`.

Los hallazgos nuevos (H1–H7, más el apéndice H8 sobre el portal de Datos Abiertos de la
UAECD) fueron **verificados en vivo el 2026-08-12** con acceso directo a los servicios
públicos; cada decisión (D1–D5) cita su fuente.

---

## Hallazgos nuevos (verificados en vivo el 2026-08-12)

### H1. Capa tabular "Predio" `catastro/lote/MapServer/3`: fuente viva del destino económico

La capa `catastro/lote/MapServer/3` (nombre de la capa: **Predio**) es la fuente del destino
económico. Es **tabular**: no tiene SHAPE, por lo que `f=geojson` responde 400
(`"The provided output spatial reference is not supported with geoJSON format."`) y la
consulta **debe usar `f=pjson`** (o `f=json`). Verificado en vivo:

- `GET .../catastro/lote/MapServer/3/query?f=pjson&where=PRECHIP='AAA0072LRYN'&outFields=*&returnGeometry=false`
  → HTTP 200 con 2 filas (features con `attributes`; sin geometría).
- Mismo endpoint con `f=geojson` → `{"error": {"code": 400, ...}}`.

La metadata de la capa (`?f=pjson`) expone los dominios codificados de los campos:

- **`D_PreDestino`** (PRECDESTIN, 28 códigos): `01` Residencial, `03` Industrial, `04`
  Dotacional público, `05` Recreacional público, `06` Dotacional privado, `07` Minero, `08`
  Recreacional privado, `21` Comercio en corredor comercial, `22` Comercio en centros
  comerciales, `23` Comercio puntual, `24` Parqueaderos, `61` Urbanizado no edificado, `62`
  Urbanizable no urbanizado, `63` No urbanizables y suelo protegido, `64` Urbanizado no
  edificado propiedad del Estado, `65` Vías, `66` Espacio público, `67` Predios con mejoras
  ajenas, `68` Servidumbre Predial, `81` Agropecuarios, `82` Otros, `83` Agrícola, `84`
  Pecuario, `85` Forestal, `86` Agroindustrial, `87` Agroforestal, `88` Tierras
  improductivas, `89` Predio rural con parcela no edificada.
- **`D_UsoTUso`** (PRECUSO, 85 códigos): `001` Habitacional menor o igual a 3 pisos en NPH,
  `002` Habitacional mayor o igual a 4 pisos en NPH, `003` Comercio puntual en NPH, ...,
  `040` Corredor Comercial en PH, `096` Parqueadero Cubierto en NPH, etc. (la spec previa
  estimaba ~95; el dominio real es de **85**).
- **`D_PreTPropie`** (PRETPROP, 8 códigos): `1` Oficial, `2` Distrital, `3` Religioso, `4`
  Embajada, `5` Parques, `6` Particular, `7` Mixto, `8` Otros.

Campos clave verificados en las filas (CHIP `AAA0072LRYN` y `AAA0153KDDM`): `PRECDESTIN`,
`PRECUSO`, `PREAUSO`, `PREVACTUAL` (= 2026, vigencia de actualización), `PREVFORMA` (=
1998, vigencia de formación), `PREDIRECC`, `PRENBARRIO`, `PREATERRE`, `PREACONST`,
`PRECEDCATA`, `PRENUPRE`, `BARMANPRE`, `PRECMANZ`, `PRECBARRIO`, `PRETPROP`, `PRECLASE`.
`PRECHIP` es el join por CHIP.

**Implicación**: la tabla de dominios `D_PreDestino`/`D_UsoTUso` es **estática y versionable**
(patrón del mapeo `NOMBRE → localidad` de F2, research D3): se embebe como constante del
provider para traducir los códigos a descripciones sin consultar la metadata en runtime.

### H2. Join para lotes sin CHIP: `LOTCODIGO` (capa Lote 38) == `BARMANPRE` (capa Predio 3)

Verificado en vivo con dos CHIPs reales:

| CHIP | `LOTCODIGO` (Lote 38) | `MANZCODIGO` (Lote 38) | `BARMANPRE` (Predio 3) | `PRECEDCATA` (Predio 3) | `PRENUPRE` (Predio 3) |
|------|-----------------------|------------------------|------------------------|-------------------------|------------------------|
| AAA0072LRYN | `006101016001` | `006101016` | `006101016001` | `24B 29 1` | `110010161140100160001300000000` |
| AAA0153KDDM | `004103017022` | `004103017` | `004103017022` | `004103172200101007` | `110010141140300170022901010007` |

- **`LOTCODIGO` == `BARMANPRE`** en ambos casos (COMPROBADO). Es la clave de join válida.
- `PRECEDCATA` (cédula catastral, formato `24B 29 1`) y `PRENUPRE` (número predial nacional
  de 30 dígitos) **NO coinciden** con `LOTCODIGO` ni con `MANZCODIGO`.
- La capa Predio es tabular y **no es consultable por geometría**, pero sí por atributo:
  `where=BARMANPRE='<codigo_catastral>'` funciona (verificado: `004103017022` → 8 filas).
- El `Lote.codigo_catastral` de F1 se llena desde `LOTCODIGO` de la capa Lote 38
  (app/providers/arcgis.py, `_parsear_lotes`); por tanto **siempre está disponible** incluso
  cuando `chip` es `None` (lote resuelto por coordenadas).

**Implicación**: el bloque `economic_context` puede resolverse para lotes sin CHIP usando
`codigo_catastral` como llave (`BARMANPRE`). Cuando el lote se resolvió por CHIP, la consulta
primaria es `where=PRECHIP='<chip>'` (más precisa); si no devuelve filas, se puede intentar
`BARMANPRE` como respaldo. Si ninguna devuelve filas → bloque `no_encontrado` + warning
(permitido por la spec).

### H3. Multiplicidad del destino económico: 1 predio → N filas

La capa Predio tiene **una fila por construcción/uso** del predio (patrón `PRECCONS` +
`PRECUSO` + `PREAUSO`):

- `AAA0072LRYN` → **2 filas**: `PRECDESTIN=04` (Dotacional público) con `PRECUSO=015`
  (Oficinas y Consultorios oficiales en NPH, `PREAUSO=40453.8`) y `PRECUSO=096` (Parqueadero
  Cubierto en NPH, `PREAUSO=3011.3`).
- `AAA0153KDDM` → **1 fila**: `PRECDESTIN=21` (Comercio en corredor comercial),
  `PRECUSO=040` (Corredor Comercial en PH, `PREAUSO=72.9`).
- Consulta por `BARMANPRE='004103017022'` → **8 filas** con CHIPs distintos (unidades de
  construcción del mismo predio catastral, cada una con CHIP propio).

**Implicación**: el contrato de `economic_context` debe representar la multiplicidad. Regla
de selección (determinística): **la fila con mayor `PREAUSO`** define
`descripcion_destino`/`codigo_destino`; las demás se listan en `usos` (código, descripción,
área). La justificación: `PREAUSO` es el área del uso en la fuente; el uso dominante es el
de mayor área construida/terreno asignada (criterio catastral), y la lista preserva la
información sin inventarla.

### H4. Clasificación de suelo derivable de la UPL (`vocacion` de la capa)

Verificada la capa `ordenamientoterritorial/unidadplaneamientolocal/0` en vivo (33
features): el atributo `VOCACION` clasifica cada UPL:

- **Rural**: `UPL01` Sumapáz, `UPL02` Cuenca del Tunjuelo, `UPL06` Cerros Orientales.
- **Urbano-Rural**: `UPL03` Arborizadora, `UPL04` Lucero, `UPL05` Usme - Entrenubes, `UPL07`
  Torca, `UPL08` Britalia, `UPL10` Tibabuyes, `UPL11` Engativá, `UPL12` Fontibón, `UPL13`
  Tintal, `UPL14` Patio Bonito, `UPL15` Porvenir.
- **Urbano**: `UPL09` Suba, `UPL16` Edén, `UPL17` Bosa … `UPL33` Barrios Unidos.

`UPLProvider` ya parsea `VOCACION` en `UPL.vocacion` (app/providers/upl.py, `_parsear_upl`),
por lo que la clasificación de suelo del lote se **deriva de la UPL resuelta** sin consultas
adicionales.

**Implicación** (decisión esperada por la spec, Assumption línea 125): la clasificación de
suelo para la consulta normativa automática se deriva de `UPL.vocacion`:
`"Urbano"` → `urbano`, `"Rural"` → `rural`, `"Urbano-Rural"` → ambos. Si la UPL no se
resuelve → `clasificacion_suelo: null` y la consulta automática se construye con la
localidad y sin filtro territorial.

### H5. `obras_publicas` es multipunto: el radio de 500 m (FR-004) exige buffer

La capa `gestionpublica/obraspublicas/0` (2696 features) es **`esriGeometryMultipoint`**.
Verificado en vivo:

- Consulta por punto con `esriSpatialRelIntersects` **sin distancia** (semántica de F1,
  `_consultar_obras_publicas`) → **0 features** en puntos de prueba (el punto casi nunca
  coincide con un multipunto).
- Consulta por punto con **`distance=500&units=esriSRUnit_Meter`** → 4 features en un punto
  cercano a la obra "Ampliación de Estaciones: Calle 146…"; con `distance=5000` → 467.

**Implicación**: FR-004 exige "obras públicas en un radio de 500 m alrededor del lote,
criterio del brief". Reutilizar `ContextoTematico.obras_publicas` (intersección puntual de
F1) devolvería casi siempre `no_encontrado` y **no** cumpliría FR-004. El bloque
`environment_context` del reporte debe consultar la capa con el parámetro de buffer
(`distance=500`, `units=esriSRUnit_Meter`) sobre el centroide del lote, sin modificar la
consulta puntual de F1 (ver D5).

### H6. F2 en runtime: filtro territorial por metadatos `upls` ($contains), no por `parte`

Verificado en código (`app/providers/normativa.py:235-240` y `app/ingesta/corpus.py:640-648`):
la colección ChromaDB guarda por chunk los metadatos `{articulo, titulo, libro, parte,
seccion, upls}` (este último como cadena `","`-unida) y el filtro por UPL de
`consultar_normativa` es `where={"upls": {"$contains": upl}}` (mención explícita). El
`parte` sí se indexa (clasificación `general|urbano|rural` según libro: II→general, III→
urbano, IV→rural), pero el runtime de F2 no lo usa en el `where`. F3 **reutiliza
`consultar_normativa` tal cual** (no modifica F2): pasar `upl=<codigo>` aplica el filtro
territorial que F2 implementa hoy; el término de clasificación de suelo viaja en el texto de
la consulta automática.

### H7. Vigencias del destino económico y límites de la fuente

- `PREVACTUAL` = **2026** en las filas verificadas (vigencia de actualización catastral);
  `PREVFORMA` = 1998 (vigencia de formación). `data_vigencia` del bloque `economic_context`
  = **vigencia del registro** (`PREVACTUAL`), no una constante global; el `source_trace` de
  la capa usa la vigencia del registro seleccionado (patrón `_vigencia_del_feature` de F1).
- La capa Predio es pública, sin autenticación (verificado en vivo). No requiere
  `MAPAS_BOGOTA_APIKEY` (la llave solo aplica a geocodificación, FR-012).
- La capa es tabular; una consulta con `where` de una cadena inexistente devuelve
  `features: []` (HTTP 200) → se modela como `no_encontrado` del bloque, no como error.

---

## D1. Destino económico desde la capa tabular `catastro/lote/MapServer/3` (Predio), con join por `PRECHIP` o `BARMANPRE`

**Decision**: El bloque `economic_context` se consulta desde la **capa tabular Predio**
(`catastro/lote/MapServer/3`) de ArcGIS REST, con `f=pjson`, `returnGeometry=false` y un
`where` por atributo: `PRECHIP='<chip>'` cuando el lote tiene CHIP; `BARMANPRE='<codigo_catastral>'`
cuando no (lote resuelto por coordenadas). Si la consulta no devuelve filas → bloque
`no_encontrado` + warning (FR-005), nunca un error fatal ni un dato inventado. La fila con
mayor `PREAUSO` define `descripcion_destino`; las demás se listan en `usos`.

**Rationale**: La búsqueda por CHIP de Mapas Bogotá no expone destino económico (hecho A);
la capa `catastro/destinolt` está fuera de servicio (500 en vivo, retirada de F1); la capa
Predio es la fuente catastral viva verificada que sí lo expone (H1). El join por `BARMANPRE`
resuelve el caso de lotes sin CHIP y está **comprobado en vivo** (H2: `LOTCODIGO` ==
`BARMANPRE` en los dos CHIPs de prueba). La selección por mayor `PREAUSO` es la regla
determinística más simple y trazable a la fuente para la multiplicidad (H3); el listado de
usos preserva la información completa sin inventar nada (FR-014). La tabla de dominios
`D_PreDestino`/`D_UsoTUso` se versiona como constante del provider (patrón F2/D3) para
traducir códigos de forma determinista y auditable (H1).

**Alternatives considered**:

- **Capa `catastro/destinolt`**: fuente original del modelo `DestinoEconomico` de F1, pero
  responde 500 en vivo ("Service catastro/destinolt/MapServer not started") y fue retirada
  del contexto temático (app/providers/arcgis.py, NOTA). Descartada por decisión del usuario
  (hecho C).
- **Derivar destino del CHIP vía Mapas Bogotá**: la respuesta de `direccion_chip` no trae
  destino económico (hecho A). Descartada.
- **Join por `PRECEDCATA` o `PRENUPRE`**: no coinciden con `LOTCODIGO`/`MANZCODIGO`
  (verificado en H2). Descartados.
- **Join espacial contra la capa Predio**: imposible; es tabular sin SHAPE (H1). Descartado.

**Fuente**: capa `catastro/lote/MapServer/3` (H1, H2, H3); metadata de dominios (H1);
`app/providers/arcgis.py` (origen de `codigo_catastral`); hecho A (Mapas Bogotá sin destino).

---

## D2. Clasificación de suelo derivada de `UPL.vocacion`; consulta automática con localidad como respaldo

**Decision**: La clasificación de suelo del lote se **deriva de la UPL resuelta**:
`UPL.vocacion == "Rural"` → `rural`; `"Urbano"` → `urbano`; `"Urbano-Rural"` → `urbano-rural`
(ambas partes aplican). La consulta normativa automática se construye como
`"normas urbanísticas aplicables a la UPL {nombre} ({codigo}), localidad {localidad},
clasificación de suelo {clasificacion}"` y se invoca `consultar_normativa` con `upl=<codigo>`
(cuando existe), que aplica el filtro territorial de F2. **Si la UPL no se resuelve**:
`clasificacion_suelo: null`, advertencia en `warnings`, y la consulta automática se construye
con la localidad (`"normas urbanísticas aplicables en la localidad {localidad}"`) **sin
filtro territorial** (`upl` omitido).

**Rationale**: La Assumption de la spec (línea 125) pide derivar la clasificación de la UPL o
de los metadatos del corpus; la capa UPL expone `VOCACION` (H4), que `UPLProvider` ya
parsea, por lo que la derivación es una regla pura sobre dato real sin consultas ni
suposiciones adicionales. El `upl` que se pasa a `consultar_normativa` reutiliza el filtro
territorial existente de F2 (H6). El respaldo sin UPL está exigido por FR-003/FR-008 y
cubierto por el edge case "Lote sin UPL" (upl null + warning, sin filtro territorial).

**Alternatives considered**:

- **Derivar la clasificación del corpus (metadatos `parte`)**: el corpus tiene `parte` por
  artículo, pero no es una propiedad del lote; usarla como clasificación del lote mezclaría
  niveles (norma vs territorio). Descartada como fuente primaria; el `parte` sigue siendo el
  filtro interno del RAG.
- **Regla fija por código (`UPL01` → rural, resto → urbano)**: incompleta (H4: `UPL02` y
  `UPL06` también son rurales) y menos trazable que leer `VOCACION` de la fuente. Descartada.
- **Consulta automática sin `upl` siempre**: perdería el filtro territorial estricto de F2
  para el caso normal. Descartada.

**Fuente**: capa `unidadplaneamientolocal/0` (H4); `app/providers/upl.py` (`UPL.vocacion`);
`app/providers/normativa.py` (filtro territorial H6); spec FR-003, FR-008, Assumption.

---

## D3. Scoring 100 % determinístico sin LLM: base, reglas positivas/negativas, clamp, confidence y reasons trazables

**Decision**: `feasibility_score` se calcula con una **función pura** (sin estado, sin LLM)
sobre los datos recuperados:

- **Base**: `50`.
- **Reglas positivas** (suman sobre datos reales, cada una con `source_name`):
  UPL resuelta `+10`; localidad derivada `+5`; `market_context` disponible `+10`; bloque
  `economic_context` disponible `+10`; `normative_evidence` con ítems `+5`.
- **Reglas negativas** (restan): reserva vial que afecta el lote `-15`; UPL ausente `-5`;
  cada bloque temático/económico en `no_encontrado` `-5`; `normative_evidence` vacío
  (degradación RAG o sin resultados) `-5`.
- **Clamp**: `score = max(0, min(100, base + Σ))`, entero 0–100 (FR-006).
- **Confidence** (canónico `"high"` | `"medium"` | `"low"`): por **cobertura de bloques de
  datos** entre 6 bloques evaluables (administrative_context, planning_constraints,
  market_context, environment_context, economic_context, normative_evidence): `high` si
  ≥ 5 disponibles; `medium` si 3–4; `low` si ≤ 2.
- **Reasons**: lista de textos **fijos por regla** con datos interpolados y `source_name`
  (p. ej. `"UPL resuelta: UPL24 Chapinero (IDECA Catastro — Unidad de Planeamiento Local)."`).
  Cuando `confidence` es `low`, las reasons enumeran explícitamente qué datos faltan
  (escenario US3.2).
- **Determinismo**: misma entrada → mismo score/confidence/reasons (SC-003); la función no
  lee reloj ni fuentes (el reloj solo afecta `query_timestamp`, que no participa del score).

**Rationale**: FR-006/FR-007 exigen score por reglas transparentes sin LLM; FR-014 exige no
inventar reglas urbanísticas. Todas las reglas operan sobre **hechos de disponibilidad o
afectación** declarados por las fuentes (reserva vial afecta/no, dato disponible/no), nunca
sobre normas urbanísticas no citadas. La base 50 con penalizaciones por datos ausentes hace
que `confidence` baja acompañe a `score` bajo (coherencia honesta). El diseño como función
pura cumple la Ley 3 (Atomic Predictability) de la filosofía de código y facilita el test
de determinismo (SC-003).

**Alternatives considered**:

- **Score con LLM**: prohibido por el usuario (hecho C) y FR-007. Descartado.
- **Reglas de negocio urbanístico (p. ej. penalizar usos no permitidos por la UPL)**:
  exigiría inferir normativa ausente (FR-014) y es la mejora futura declarada fuera de
  alcance. Descartado.
- **Score ponderado por similitud normativa**: introduciría dependencia de la calidad RAG en
  un score "de datos"; se mantiene el `+5` binario por evidencia no vacía. Descartado.
- **Sin clamp**: un score fuera de 0–100 violaría FR-006. Descartado.

**Fuente**: spec FR-006, FR-007, FR-014, US3, SC-003; datos verificados (H1–H5).

---

## D4. Contrato `get-feasibility-report` con 10 bloques y degradación por bloque (no por error)

**Decision**: La tool `get_feasibility_report` expone un **contrato único** con 10 bloques
(`lot_identity`, `administrative_context`, `planning_constraints`, `market_context`,
`environment_context`, `economic_context`, `normative_evidence`, `feasibility_score`,
`warnings`, `query_timestamp`), campos técnicos en inglés (bloques, `score`, `confidence`,
`reasons`, `interpretation`, `source_trace`), atributos de dominio en español siguiendo el
estilo de los contratos F1/F2 (`codigo`, `nombre`, `localidad`, `codigo_destino`,
`descripcion_destino`, ...). Firma:

- **Exactamente uno** de `{chip, direccion, coordenadas}` (FR-001, FR-013; validación
  idéntica a `get_upl`).
- `consulta`: `string | None`, opcional, 1–500 caracteres (mismo límite que
  `consultar_normativa`); si se omite, se construye automáticamente (D2).
- `top_k`: `int | None`, opcional, 1–6, default 3 (coherente con `consultar_normativa`).

Cada bloque de datos lleva su `source_trace` de 5 campos (FR-010, SC-002). Los bloques
temáticos y `economic_context` siguen el patrón `{estado: disponible|no_encontrado, dato,
interpretation, source_trace}` de F1 (con `interpretation` fija por reglas, FR-007);
`normative_evidence` se entrega vacío con causa y warning si el RAG no está disponible
(FR-009). `feasibility_score` es el D3. Los errores **fatales** son los 6 de FR-012; las
degradaciones se representan en el propio reporte (ver D5 y sección "Divergencia deliberada
con F2").

**Rationale**: El contrato materializa el brief ("feasibility_report estructurado con
identidad, contexto administrativo, restricciones, mercado, entorno, evidencia normativa y
scoring", línea 1179) y los FR de la spec. Mantener la firma coherente con `consultar_normativa`
(`consulta` + `top_k`) reduce la superficie cognitiva del MCP. El patrón `estado/dato`
reutiliza la semántica de F1 (FR-007) y la degradación por bloque cumple FR-009/FR-012 sin
reabrir decisiones del usuario (hecho C).

**Alternatives considered**:

- **Una tool por bloque**: multiplicaría las llamadas y rompería la orquestación unificada
  (FR-001). Descartado.
- **Repetir el shape completo de `consultar_normativa` dentro del reporte** (`respuesta`,
  `sin_resultados`, `resultados`, `trazabilidad`): el reporte solo necesita los ítems con
  cita y la consulta usada; se simplifica a `{items, consulta, consulta_automatica,
  sin_resultados, causa, source_trace}`. Descartado por YAGNI.
- **Admitir `consultar_normativa` como sub-tool del reporte**: el usuario pidió una sola
  llamada (FR-001). Descartado.

**Fuente**: spec FR-001 a FR-014, SC-001 a SC-006; contratos F1/F2 (estilo `estado/dato` y
`source_trace`); hecho C.

---

## D5. Arquitectura: 7ª tool en `ServidorLotes`, destino económico en `ArcGISProvider`, environment con buffer 500 m

**Decision**: La orquestación vive en un **nuevo método público `get_feasibility_report` de
`ServidorLotes`** (app/main.py), registrado como **7ª tool** en `crear_servidor_mcp`
(`mcp.tool()(servidor_lotes.get_feasibility_report)`), reutilizando los flujos privados de
F1/F2 sin modificarlos. El destino económico vive en un **nuevo método del
`ArcGISProvider`**: `consultar_destino_economico(chip=None, codigo_catastral=None)` que
consulta la capa Predio (`catastro/lote/MapServer/3`, `f=pjson`) y devuelve el modelo
`DestinoEconomico` **reactivado en `app/models.py` con la nueva fuente** (campos
`codigo_destino`, `descripcion_destino`, `uso`, `area_uso`, `area_terreno`,
`area_construccion`, `direccion`, `barrio`, `vigencia`, `estado`, `source_trace`), **sin
tocar `ContextoTematico`** ni F1/F2. El `environment_context` usa un **nuevo método
`consultar_obras_publicas_radio(lng, lat, radio_m=500)`** del mismo provider (buffer con
`distance`/`units=esriSRUnit_Meter`), porque la consulta puntual de F1 no cumple FR-004
(H5). El scoring es una **función pura** en un módulo nuevo `app/scoring.py` (D3).

El **orquestador captura `UplNoEncontradaError` internamente** (upl `null` + warning), y
captura `CorpusNoIngestadoError`/`OllamaNoDisponibleError` de la consulta normativa
(`normative_evidence` vacío + warning con causa); ambos casos **no** se propagan como
errores de la tool (hecho C, FR-009/FR-012). Los errores fatales se propagan con el
clasificador `_error_de_fuente` existente (FR-012).

**Rationale**: La constitución (Principio II) exige un provider por fuente con frontera de
parsing; la capa Predio es una fuente ArcGIS y su parsing pertenece a `ArcGISProvider`
(sin providers nuevos). `ServidorLotes` ya es el orquestador de las 6 tools; el reporte es
una orquestación más (Patrón del proyecto, `main.py`). `app/scoring.py` como módulo puro
cumple la Ley 3 (Atomic Predictability) y aísla las reglas para test de determinismo. La
reactivación de `DestinoEconomico` (sin usar desde F1) con la nueva fuente respeta el
principio YAGNI y el alcance (CHK-015): F1/F2 no se tocan.

**Alternatives considered**:

- **Orquestador en un servicio nuevo (`app/servicios/reporte.py`)**: sobre-ingeniería para
  una orquestación que reutiliza métodos privados del propio `ServidorLotes` (YAGNI).
  Descartado.
- **Consultar destino económico desde un provider nuevo (`predio.py`)**: la capa es ArcGIS
  del mismo dominio y `ArcGISProvider` ya encapsula la semántica ArcGIS; un provider nuevo
  duplicaría `CapaConfig`/`consultar_query`. Descartado (Principio II: responsabilidad por
  fuente, y la fuente ya está representada).
- **Reutilizar `ContextoTematico.obras_publicas` para `environment_context`**: no cumple
  FR-004 (radio 500 m; la capa es multipunto, H5). Descartado.
- **Consultar el destino económico dentro de `consultar_contexto_tematico` (añadirlo a las
  3 temáticas)**: modificaría el contrato de F1 (`contexto_tematico`) y el fail-fast del
  `asyncio.gather` (una temática caída tumbaría todo); además la capa Predio se consulta por
  atributo, no por punto. Descartado (CHK-015: no tocar F1/F2).

**Fuente**: `app/main.py` (flujos privados y registro), `app/providers/arcgis.py` (patrón de
provider y `_consultar`), `app/models.py` (`DestinoEconomico` sin uso), H5 (buffer 500 m),
constitución Principios II y V, spec FR-004/FR-012/CHK-015.

---

## Divergencia deliberada de degradación con el fail-fast de F2 (documentación requerida)

La Feature 2 usa **fail-fast** (Principio IV): `consultar_normativa` devuelve
`CORPUS_NO_INGESTADO` / `OLLAMA_NO_DISPONIBLE` como errores y `get_upl` devuelve
`LOTE_SIN_UPL`. La Feature 3 **degrada deliberadamente** (hecho C, FR-009/FR-012):

| Situación | F2 (tool puntual) | F3 (reporte) | Justificación |
|-----------|-------------------|--------------|---------------|
| Corpus no ingestado / Ollama no disponible | Error `CORPUS_NO_INGESTADO` / `OLLAMA_NO_DISPONIBLE` | `normative_evidence` vacío + warning con causa | El reporte es una orquestación única: un bloque degradado no debe descartar los otros 9 bloques ya recuperados (FR-009, SC-005). |
| UPL no encontrada | Error `LOTE_SIN_UPL` | `administrative_context.upl: null` + warning | La ausencia de UPL es un dato no encontrado representable en el reporte (FR-003); el resto de bloques continúa. |
| Sin resultados normativos | `sin_resultados=true` (no es error) | `normative_evidence` vacío + warning | Misma semántica de abstención de F2, sin error. |
| Dato ausente por fuente | Estado `no_encontrado` (F1) | Estado `no_encontrado` a nivel de bloque | `DATO_NO_ENCONTRADO_POR_FUENTE` no aplica en F3 (FR-012). |

Los 6 errores fatales del reporte (`PARAMETROS_INVALIDOS`, `LOTE_NO_ENCONTRADO`,
`FUERA_DE_COBERTURA`, `DIRECCION_NO_LOCALIZADA`, `CREDENCIAL_FALTANTE`, `FUENTE_5XX`) se
reservan para estados en los que el reporte **no puede construirse con sentido** (entrada
inválida, lote inexistente, punto fuera de Bogotá, dirección no localizable, credencial
faltante en geocodificación, 5xx de una fuente). Un 5xx de una fuente **nunca** se degrada a
`no_encontrado` (FR-009): es fatal y se propaga con `_error_de_fuente`. Esta divergencia es
intencional y queda registrada aquí para el reviewer (Principio IV: contratos explícitos; el
contrato del reporte documenta ambas vías: errores fatales y degradaciones).

---

## Resumen de decisiones y artefactos derivados

| # | Decisión | Artefacto que la materializa |
|---|----------|------------------------------|
| D1 | Destino económico desde capa Predio `catastro/lote/MapServer/3` (`f=pjson`), join por `PRECHIP` o `BARMANPRE`; fila de mayor `PREAUSO`; dominios versionados | `contracts/get-feasibility-report.md`, `data-model.md` (DestinoEconomico), `plan.md` (provider) |
| D2 | Clasificación de suelo derivada de `UPL.vocacion`; consulta automática con UPL+localidad+clasificación; respaldo con localidad sin filtro territorial | `data-model.md` (administrative_context), `contracts/get-feasibility-report.md` |
| D3 | Scoring puro 0–100: base 50, reglas positivas/negativas, clamp, confidence por cobertura (high/medium/low), reasons fijos con dato + `source_name`; sin LLM | `data-model.md` (feasibility_score), `contracts/get-feasibility-report.md`, `plan.md` (`app/scoring.py`) |
| D4 | Contrato único de 10 bloques; firma exactamente un criterio + `consulta`/`top_k` opcionales; errores fatales 6 + degradaciones | `contracts/get-feasibility-report.md` |
| D5 | Arquitectura: `get_feasibility_report` en `ServidorLotes` (7ª tool); `consultar_destino_economico` y `consultar_obras_publicas_radio(500m)` en `ArcGISProvider`; `DestinoEconomico` reactivado sin tocar F1/F2; captura de `UplNoEncontradaError`/RAG en el orquestador | `plan.md`, `data-model.md` |

**Hechos incorporados (A/B/C)**: véase la sección Alcance y las referencias a `app/` en cada
decisión. No queda ningún `NEEDS CLARIFICATION` pendiente.

---

## Apéndice: H8 — Portal Datos Abiertos Bogotá (org UAECD)

Hallazgo de investigación complementaria verificado el 2026-08-12, registrado como apéndice
al final del research: documenta el repositorio CKAN oficial de la UAECD como respaldo y
documentación de las fuentes de F3 (H1–H7). **No modifica** las decisiones D1–D5: la
consulta en vivo por `PRECHIP`/`BARMANPRE` sigue siendo la fuente de `economic_context`.

- El portal https://datosabiertos.bogota.gov.co/organization/uaecd es el repositorio CKAN
  **oficial de la UAECD** (33 datasets, todos CC BY 4.0, descargas sin registro ni API key).
- El dataset **"Predios. Bogotá D.C"** (datosabiertos.bogota.gov.co/dataset/predios-bogota)
  cuelga del **mismo servicio REST `catastro/lote/MapServer/3`** (capa 'Predio', 52 campos)
  que F3 ya consulta (H1) → valida que la fuente en vivo es la oficial publicada.
- Snapshots mensuales descargables del dataset Predios: **CSV 07.26 ≈ 142 MB, DBF 07.26 ≈
  149 MB** (históricos desde 12.18) — útiles para tests/demo offline, seed de copia local o
  reconstrucción de vigencias; **NO reemplazan la consulta en vivo**.
- Dataset **"Uso. Bogotá D.C"** (datosabiertos.bogota.gov.co/dataset/uso): DBF 9.2 MB,
  1.061.443 registros, campos `USOCLOTE`/`USOTUSO`/`USOAREA` — copia offline del dominio
  `D_UsoTUso`.
- Documentación autoritativa de dominios vía PDFs IDECA enlazados desde los metadatos:
  `CO_Predio_MR.pdf`, `CO_Uso_MR.pdf`, `CatalogoObjetosDR_V0920.zip` (HTTP 200) —
  referencia para las constantes `D_PreDestino`/`D_UsoTUso` de T003.
- `market_context`: `catastro/valorreferencia/MapServer/0` expone `MANCODIGO`, `V_REF`
  (COP), `ANO` (dataset "Mediana valor comercial m² terreno/manzana – Valor de referencia").
- **NO existen datasets dedicados** de "destino económico" ni "ficha predial": la vía
  correcta es `PRECDESTIN`/`PRECUSO` del Predio (en vivo o snapshot) — confirma la decisión
  D1.
- **OJO licencias**: la clasificación de suelo POT (org SDP, Decreto 555) es **CC BY-NC
  4.0** (no comercial) — solo contexto interno; la Unidad de Planeamiento Local POT (SDP)
  está disponible en GPKG/GeoJSON.

**Conclusión**: el portal aporta valor como respaldo y documentación, pero **no cambia la
arquitectura del plan**: la consulta en vivo por CHIP/`BARMANPRE` sigue siendo la fuente de
`economic_context` (D1 se mantiene intacta).
