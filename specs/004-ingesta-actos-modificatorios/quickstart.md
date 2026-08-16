# Quickstart: Ingesta de actos normativos que modifican el Decreto 555 (corpus consolidado)

**Fase**: Phase 1 del comando `/speckit.plan` | **Fecha**: 2026-08-14
**Feature**: [spec.md](spec.md)
**Naturaleza**: guía de **validación** (escenarios ejecutables + resultados esperados).
No es una especificación de implementación: para los contratos y el modelo de datos,
remitirse a [contracts/ingesta-actos-modificatorios.md](contracts/ingesta-actos-modificatorios.md)
y [data-model.md](data-model.md).

## Prerrequisitos

1. **Python 3.11+**.
2. Instalar el proyecto en modo editable con dependencias de desarrollo:
   ```bash
   pip install -e ".[dev]"
   ```
   (añade `pypdf>=5` y `python-docx>=1.1` para la ingesta de PDF/DOCX; ver `pyproject.toml`).
3. **Variables de entorno** (leídas del entorno; ver `.env.example`):
   - `OLLAMA_BASE_URL=http://localhost:11434` (endpoint legado que usa ChromaDB).
   - `OLLAMA_EMBEDDING_MODEL=bge-m3` (modelo de embeddings, 1024 dims).
   - `OLLAMA_CHAT_MODEL=qwen3:8b` (modelo de chat con citation forcing).
   - `VECTOR_DB_PATH=.data/chroma` (directorio del índice vectorial).
   - `CORPUS_URL=https://www.alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=119582` (555; no
     se re-descarga salvo cambio de modelo de embeddings, H3).
4. **Corpus base ingestado** (F2): `data/corpus/decreto_555_2021.jsonl` + `.sha256`
   versionados en git y el índice en `.data/chroma/` (si no existe: `python -m app.ingesta.corpus full`).
5. **Ollama corriendo localmente** (solo para `--indexar` y consultas; la extracción y
   validación de la ingesta NO requieren Ollama, FR-010):
   ```bash
   ollama serve
   ollama pull bge-m3
   ollama pull qwen3:8b
   ```

## Comandos de verificación automática

```bash
# Smoke test: el servidor inicia y las 7 tools siguen registradas (sin tools MCP nuevas)
pytest tests/smoke

# Contract tests: 185 tests de F1–F3 + nuevos de F4 (SC-005)
pytest tests/contract

# Tests específicos de F4
pytest tests/contract/test_ingesta_actos.py tests/contract/test_corpus_consolidado.py tests/contract/test_precedencia.py
```

## Ejecución de la ingesta (escenario principal)

```bash
# Ingestar el Decreto 122 de 2023 (vivienda colectiva) desde la URL sisjur y re-indexar
python -m app.ingesta.corpus acto --url https://www.alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=139499 --indexar
```

Resultado esperado:
- Escribe `data/corpus/actos_modificatorios/Decreto_122_2023.jsonl` (13 artículos) + `.sha256`.
- Actualiza `data/corpus/actos_modificatorios/.corpus_consolidado.json` con el hash y metadatos.
- Salida JSON con `documento_id`, `articulos: 13`, `relacion_con_555: "referencia_articulos"`,
  `articulos_referenciados: [233, 243, 384]` y `estado_documento: "derogado"` (banner sisjur, H7).
- Re-indexa la colección `decreto_555_2021` de forma aditiva (FR-008).

> La fecha de expedición del 122 (2023-03-30) es posterior a la vigencia del 555 (2021-12-30),
> por lo que la validación FR-014 pasa. Un acto anterior a 2021-12-30 se rechaza con
> `FECHA_ANTERIOR_AL_555` sin tocar el corpus.

## Escenarios de validación

### E1 — Ingesta de un acto real en HTML sisjur (SC-001)

- **Acción**: `python -m app.ingesta.corpus acto --url ...i=139499 --indexar`
- **Resultado esperado**: JSONL con 13 artículos del Decreto 122 (títulos en `<i>` y números
  ordinales `Nº.` parseados correctamente, research D4/H2); salida JSON con
  `"duplicado": false`; consulta "vivienda colectiva" devuelve fragmentos del 122 con
  `norma: "Decreto 122 de 2023"`.

### E2 — Deduplicación por hash (FR-007, SC-003)

- **Precondición**: E1 ejecutado.
- **Acción**: repetir el mismo comando.
- **Resultado esperado**: `"duplicado": true`, sin reescritura del JSONL ni re-indexación; el
  número de artículos consultables NO cambia.

### E3 — Formato no soportado con fallo atómico (FR-009, SC-006)

- **Acción**: `python -m app.ingesta.corpus acto --archivo acto.xls`
- **Resultado esperado**: error `FORMATO_NO_SOPORTADO` en stderr, exit code ≠ 0, y
  `data/corpus/actos_modificatorios/` idéntico al estado previo (sin escrituras parciales).

### E4 — PDF con texto nativo (FR-001, D5)

- **Acción**: `python -m app.ingesta.corpus acto --archivo Decreto_122_2023.pdf` (PDF oficial
  descargado de la página sisjur; 6 páginas con texto nativo).
- **Resultado esperado**: extracción con `pypdf` (o `pdfplumber` si el orden de lectura no se
  reconstruye), 13 artículos detectados, ingesta correcta. Un PDF escaneado sin texto → error
  `SIN_TEXTO_EXTRAIBLE` sugiriendo el formato HTML sisjur.

### E5 — Acto con fecha anterior al 555 (FR-014)

- **Acción**: ingestar un acto con `fecha_expedicion < 2021-12-30` (p. ej. un decreto de 2020).
- **Resultado esperado**: error `FECHA_ANTERIOR_AL_555`, el acto NO se integra, corpus intacto.

### E6 — Consulta consolidada con norma de origen y precedencia (FR-004/FR-005, SC-002/SC-004)

- **Precondición**: E1 ejecutado (corpus consolidado con 555 + 122) y Ollama disponible.
- **Acción**: `consultar_normativa("vivienda colectiva")` y `get_feasibility_report` para un
  lote con ese tema.
- **Resultado esperado**: cada ítem de `resultados`/`items` indica su norma de origen
  (`"Decreto 555 de 2021"` y/o `"Decreto 122 de 2023"` en `norma`/`source_name`); el prompt del
  RAG incluye la regla de precedencia (el 122 prevalece sobre el art. 233 del 555 sin ocultarlo);
  el `source_trace` de bloque de F3 se conserva intacto; los shapes exactos de los tests
  incluyen solo los campos nuevos (SC-005).

### E7 — Índice desactualizado se reconstruye (FR-008)

- **Acción**: borrar `.data/chroma/` (dato derivado) o cambiar `OLLAMA_EMBEDDING_MODEL` y
  re-indexar con `python -m app.ingesta.corpus indexar`.
- **Resultado esperado**: el índice se reconstruye con los 608 artículos del 555 + los actos
  registrados en `.corpus_consolidado.json`; la huella multi-documento se persiste en la
  metadata de la colección (no se mezclan vectores de modelos distintos).

## Ejecución del servidor MCP

```bash
python -m app.main
```

Las **7 tools** de F1–F3 se mantienen sin cambios de contrato (FR-011): `resolve_lot_by_chip`,
`resolve_lot_by_address`, `resolve_lot_by_coordinates`, `get_lot_summary_by_chip`, `get_upl`,
`consultar_normativa`, `get_feasibility_report`. F4 no añade tools MCP (research D1); la
alimentación del corpus es por CLI.
