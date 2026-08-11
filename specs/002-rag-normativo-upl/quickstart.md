# Quickstart: RAG normativo del POT (Decreto 555/2021) + UPL

**Fase**: Phase 1 del comando `/speckit.plan` | **Fecha**: 2026-08-10
**Feature**: [spec.md](spec.md)
**Naturaleza**: guía de **validación** (escenarios ejecutables + resultados esperados).
No es una especificación de implementación: para los contratos y el modelo de datos,
remitirse a [contracts/](contracts/) y [data-model.md](data-model.md).

## Prerrequisitos

1. **Python 3.11+**.
2. Instalar el proyecto en modo editable con dependencias de desarrollo:
   ```bash
   pip install -e ".[dev]"
   ```
   (instala `mcp>=1.0.0`, `httpx`, `pydantic`, `chromadb`, `pytest` según `pyproject.toml`).
3. **Variables de entorno** (leídas desde `.env`; ver `.env.example`):
   - `OLLAMA_BASE_URL=http://192.168.40.91:11434` (endpoint legado que usa ChromaDB).
   - `OLLAMA_EMBEDDING_MODEL=bge-m3` (modelo de embeddings, 1024 dims).
   - `OLLAMA_CHAT_MODEL=qwen3:8b` (modelo de chat para generación de respuesta).
   - `VECTOR_DB_PATH=.data/chroma` (directorio del índice vectorial).
   - `CORPUS_URL=https://www.sisjur.gov.co/decreto-555-2021` (URL sisjur del Decreto 555/2021).
   - `MAPAS_BOGOTA_APIKEY` (opcional): obligatoria solo para `get_upl` por dirección.
4. **Ollama corriendo localmente** con modelos descargados:
   ```bash
   ollama serve
   ollama pull bge-m3
   ollama pull qwen3:8b
   # Alternativas de chat: ollama pull gemma4:e4b (8-16 GB RAM) o gemma4:26b (16 GB+ VRAM, 256K ctx)
   ```
5. **Ingesta del corpus** (genera JSONL versionado + índice ChromaDB):
   ```bash
   python -m app.ingesta.corpus full
   ```
   Esto produce `data/corpus/decreto_555_2021.jsonl` + `.sha256` y el índice en `.data/chroma/`.

   > **Cambiar de modelo de embeddings**: la ingesta persiste el modelo usado en la
   > metadata de la colección (`embedding_model`). Si cambias `OLLAMA_EMBEDDING_MODEL`,
   > al re-indexar se detecta el cambio y el índice se reconstruye automáticamente
   > (no se mezclan vectores de modelos distintos). Con clientes externos, borra
   > `.data/` manualmente antes de re-indexar.

## Comandos de verificación automática

```bash
# Smoke test de arranque: el servidor inicia y las 6 tools quedan registradas
pytest tests/smoke

# Contract tests: validan los contratos de las 6 tools y los estados de error
# (respuestas simuladas para los casos deterministas; ver contracts/)
pytest tests/contract

# Tests específicos de ingesta F2 (parseo, chunking, hash, indexación, consulta)
pytest tests/contract/test_ingesta_f2.py tests/contract/test_upl_provider.py tests/contract/test_normativa_provider.py tests/contract/test_get_upl.py tests/contract/test_consultar_normativa.py
```

## Ejecución del servidor MCP

Iniciar el servidor para consumirlo con un cliente MCP por stdio (p. ej. el Inspector de MCP):

```bash
python -m app.main
```

Las **6 tools expuestas**:
- F1: `resolve_lot_by_chip`, `resolve_lot_by_address`, `resolve_lot_by_coordinates`, `get_lot_summary_by_chip`
- F2: `get_upl`, `consultar_normativa`

Sus contratos completos están en [contracts/](contracts/).

## Escenarios de validación contra servicios reales

> **Nota**: Los tests de ingesta (R2) y providers (R3) usan mocks. Los siguientes escenarios validan el pipeline completo con servicios reales (requieren Ollama, red y API key donde aplique).

### Escenario 1 — Ingesta completa (offline-first)

- **Precondición**: Ollama corriendo con `bge-m3` y `qwen3:8b`.
- **Acción**: `python -m app.ingesta.corpus full`
- **Resultado esperado**:
  - Se genera `data/corpus/decreto_555_2021.jsonl` (≈608 artículos) + `.sha256` con hash determinista.
  - Se indexa en ChromaDB (`.data/chroma/`) idempotentemente (re-ejecutar no duplica chunks).
  - Log muestra: `Artículos: N | Chunks: M | Hash: abc123... | Índice: .data/chroma (OK)`.
- **Referencias**: CLI `app.ingesta.corpus`, FR-009 (corpus versionado), FR-003 (texto literal).

### Escenario 2 — Consulta normativa básica (sin filtro UPL)

- **Precondición**: Ingesta completada (escenario 1).
- **Acción**: invocar `consultar_normativa` con `{"consulta": "¿qué se puede construir en suelo urbano?", "top_k": 3}`
- **Resultado esperado**:
  - Respuesta generada por LLM con **citas literales** y números de artículo (FR-003).
  - `sin_resultados: false`, `resultados` con hasta 3 artículos, cada uno con `articulo`, `titulo`, `libro`, `parte`, `texto_cita`, `similitud` (≥ 0.35).
  - `trazabilidad` con 5 campos: `source_name`="Decreto 555 de 2021 (POT Bogotá)", `layer_id`="Decreto_555_2021", `service_url` (sisjur), `data_vigencia`="2021-12-30", `query_timestamp` (ISO 8601).
- **Referencias**: contrato [consultar-normativa.md](contracts/consultar-normativa.md), FR-001, FR-003, FR-006.

### Escenario 3 — Consulta normativa con filtro UPL estricto

- **Precondición**: Ingesta completada.
- **Acción**: invocar `consultar_normativa` con `{"consulta": "normas de usos industriales", "upl": "UPL17", "top_k": 3}`
- **Resultado esperado**:
  - `resultados` contienen **solo** artículos aplicables a UPL17 (por `parte`=urbano o mención explícita `upls_mencionadas`).
  - Filtro aplicado via ChromaDB `where={"upls": {"$contains": "UPL17"}}`.
  - Mismo formato de respuesta y trazabilidad que escenario 2.
- **Referencias**: FR-002 (filtro estricto por UPL), Historia de Usuario 3.

### Escenario 4 — Consulta sin resultados relevantes → abstención explícita

- **Precondición**: Ingesta completada.
- **Acción**: invocar `consultar_normativa` con `{"consulta": "¿cuántos árboles hay en la Avenida El Dorado?", "top_k": 3}`
- **Resultado esperado**:
  - `sin_resultados: true`, `resultados: []`.
  - `respuesta`: "No se encontraron resultados relevantes en el POT 555/2021." (no inventa contenido, FR-004).
  - `trazabilidad` presente.
- **Referencias**: FR-004, SC-003, contrato consultar-normativa.md (ejemplo abstención).

### Escenario 5 — get_upl por CHIP válido

- **Precondición**: `MAPAS_BOGOTA_APIKEY` configurada (opcional para CHIP).
- **Acción**: invocar `get_upl` con `{"chip": "AAA0072LRYN"}`
- **Resultado esperado**:
  - `upl`: `{codigo: "UPL17", nombre: "Chapinero", localidad: "Chapinero"}`.
  - `trazabilidad`: `source_name`="IDECA Catastro — Unidad de Planeamiento Local", `layer_id`="unidadplaneamientolocal.0", `service_url` (ArcGIS), `data_vigencia`="2021-12-30", `query_timestamp`.
  - Respuesta en < 10 s (SC-004).
- **Referencias**: contrato [get-upl.md](contracts/get-upl.md), FR-005, FR-006.

### Escenario 6 — get_upl por dirección (requiere API key)

- **Precondición**: `MAPAS_BOGOTA_APIKEY` configurada.
- **Acción**: invocar `get_upl` con `{"direccion": "Calle 26 # 69-76"}`
- **Resultado esperado**: mismo formato que escenario 5, usando geocodificación + resolver de lote F1 + join espacial UPL.

### Escenario 7 — get_upl por coordenadas

- **Acción**: invocar `get_upl` con `{"coordenadas": {"lat": 4.65, "lon": -74.07}}`
- **Resultado esperado**: mismo formato, usando join espacial punto-en-polígono contra capa UPL (layer 0).

### Escenario 8 — get_upl sin UPL asignada → `LOTE_SIN_UPL`

- **Acción**: invocar `get_upl` con coordenadas/lote sin UPL en la capa.
- **Resultado esperado**: error canónico `LOTE_SIN_UPL` con mensaje "El lote <codigo> no tiene UPL asignada (dato no encontrado)." (FR-007, distinto de `LOTE_NO_ENCONTRADO`).

### Escenario 9 — Validación de parámetros (fail-fast)

| Tool | Parámetro inválido | Error esperado |
|------|-------------------|----------------|
| `consultar_normativa` | `consulta=""` | `PARAMETROS_INVALIDOS` |
| `consultar_normativa` | `consulta` > 500 chars | `PARAMETROS_INVALIDOS` |
| `consultar_normativa` | `top_k=0` o `7` | `PARAMETROS_INVALIDOS` |
| `consultar_normativa` | `upl="UPL99"` | `PARAMETROS_INVALIDOS` |
| `get_upl` | sin criterio / >1 criterio | `PARAMETROS_INVALIDOS` |
| `get_upl` | `chip` mal formado | `PARAMETROS_INVALIDOS` |
| `get_upl` | `direccion` sin API key | `CREDENCIAL_FALTANTE` |
| `get_upl` | `coordenadas` fuera de rango WGS84 | `PARAMETROS_INVALIDOS` |

### Escenario 10 — Corpus no ingestado → `CORPUS_NO_INGESTADO`

- **Precondición**: Borrar/mover `.data/chroma/`.
- **Acción**: invocar `consultar_normativa` con cualquier consulta válida.
- **Resultado esperado**: error canónico `CORPUS_NO_INGESTADO` con mensaje accionable ("Ejecuta el script de ingesta antes de consultar.").

### Escenario 11 — Ollama no disponible → `OLLAMA_NO_DISPONIBLE`

- **Precondición**: Detener `ollama serve`.
- **Acción**: invocar `consultar_normativa` o `get_upl` (que usa embeddings vía ChromaDB).
- **Resultado esperado**: error canónico `OLLAMA_NO_DISPONIBLE` con modelo faltante y instrucción `ollama pull <modelo>` (FR-011, fail-fast).

## Criterios de éxito verificables con esta guía

| Criterio | Cómo se verifica |
|----------|------------------|
| Ingesta genera JSONL + .sha256 + índice idempotente | Escenario 1. |
| Consulta RAG con citas literales y trazabilidad 5 campos | Escenarios 2, 3. |
| Filtro UPL estricto (parte + mención explícita) | Escenario 3. |
| Abstención explícita sin inventar contenido | Escenario 4. |
| UPL por CHIP/dirección/coordenadas con localidad derivada | Escenarios 5, 6, 7. |
| `LOTE_SIN_UPL` distinto de `LOTE_NO_ENCONTRADO` | Escenario 8. |
| Validación fail-fast en todas las tools | Escenario 9. |
| `CORPUS_NO_INGESTADO` y `OLLAMA_NO_DISPONIBLE` accionables | Escenarios 10, 11. |
| Tests automatizados: 88 passed | `pytest -q` |

## Comandos de desarrollo útiles

```bash
# Solo descargar y versionar corpus (sin indexar - útil si Ollama no está disponible)
python -m app.ingesta.corpus descargar

# Solo indexar corpus ya versionado
python -m app.ingesta.corpus indexar

# Consulta directa al índice (para debugging)
python -m app.ingesta.corpus consultar "usos del suelo" --top-k 5 --umbral 0.35 --upl UPL17

# Ver hash del corpus actual
cat data/corpus/decreto_555_2021.jsonl.sha256
```