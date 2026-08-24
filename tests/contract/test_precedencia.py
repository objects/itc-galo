"""Contract tests F4 — precedencia temporal en el prompt del RAG (T015, US2, FR-006, SC-004).

Verifica el contrato de la regla de precedencia temporal del corpus consolidado
(contracts/ingesta-actos-modificatorios.md:153-164, research.md D7:136-150):
1. El prompt del RAG incluye la regla de precedencia temporal — texto canónico
   "el acto posterior PREVALECE... Cita ambas normas sin ocultar los artículos
   del 555 (coexistencia de fuentes)" (FR-006, SC-004).
2. Los fragmentos del contexto se ordenan por `fecha_vigencia` descendente
   (el acto más reciente primero: el Decreto 122 de 2023 antes que el 555 de 2021).
3. El citation forcing de F2 (citas literales verificables) se mantiene sin cambios (FR-003).

Patrón red-green (tasks.md:136): los tests 1 y 2 se escriben PRIMERO contra el
contrato y fallan hasta que T019 añade la regla y el orden en
`_generar_respuesta_llm`; el test 3 ya pasa con la implementación actual.
Sin red real ni Ollama: el POST /api/chat se captura con httpx.MockTransport
(mismo patrón de tests/conftest.py) y se inspecciona el prompt enviado al LLM.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.providers.normativa import ChunkRecuperado, NormativaProvider


# --- Helpers: captura del prompt sin red real ni Ollama ---


def _proveedor_con_captura() -> tuple[NormativaProvider, list[dict]]:
    """Provider cuyo POST /api/chat se captura en `peticiones` (httpx.MockTransport).

    `_generar_respuesta_llm` usa `_get_http_client`; inyectar `_http_client` con
    un MockTransport permite inspeccionar el payload real sin llamar a Ollama.
    """
    peticiones: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        peticiones.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"message": {"content": "Respuesta simulada con Artículo 233."}},
        )

    provider = NormativaProvider(base_url="http://ollama.test")
    provider._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.test",
        timeout=5.0,
    )
    return provider, peticiones


def _chunk(
    id_chunk: str,
    articulo: int,
    titulo: str,
    texto: str,
    fecha_vigencia: str | None = None,
) -> ChunkRecuperado:
    """ChunkRecuperado tipado con metadato `fecha_vigencia` opcional.

    T018/T019 añadirá `fecha_vigencia` al modelo (data-model.md:113-130); hoy se
    inyecta vía `object.__setattr__` para expresar el contrato — cada fragmento
    conoce la vigencia de su norma — sin depender de la implementación.
    """
    chunk = ChunkRecuperado(
        id=id_chunk,
        articulo=articulo,
        titulo=titulo,
        libro="III",
        parte="urbano",
        texto=texto,
        similitud=0.9,
    )
    if fecha_vigencia is not None:
        object.__setattr__(chunk, "fecha_vigencia", fecha_vigencia)
    return chunk


def _prompt_del_usuario(peticiones: list[dict]) -> str:
    """Prompt del usuario (messages[1].content) del primer POST /api/chat capturado."""
    assert peticiones, "El POST /api/chat debió capturarse"
    assert len(peticiones[0]["messages"]) >= 2
    return peticiones[0]["messages"][1]["content"]


def _chunk_decreto_555() -> ChunkRecuperado:
    """Artículo 233 del Decreto 555 de 2021 (vigencia 2021-12-30), norma base."""
    return _chunk(
        id_chunk="art-233",
        articulo=233,
        titulo="Vivienda colectiva (Decreto 555)",
        texto="SEÑAL_555 Texto original del artículo 233 del Decreto 555 de 2021.",
        fecha_vigencia="2021-12-30",
    )


def _chunk_decreto_122() -> ChunkRecuperado:
    """Artículo 233 del Decreto 122 de 2023 (vigencia 2023-03-31), acto posterior.

    Reglamenta el artículo 233 del 555 (vivienda colectiva): misma materia,
    norma más reciente — debe PREVALECER en el contexto (FR-006, D7).
    """
    return _chunk(
        id_chunk="Decreto_122_2023-art-233",
        articulo=233,
        titulo="Vivienda colectiva (Decreto 122 de 2023)",
        texto="SEÑAL_122 El presente decreto reglamenta el artículo 233 del Decreto 555.",
        fecha_vigencia="2023-03-31",
    )


# --- Tests del contrato de precedencia temporal (FR-006, SC-004) ---


@pytest.mark.asyncio
async def test_prompt_incluye_regla_de_precedencia_temporal():
    """FR-006/SC-004: el prompt del RAG incluye la regla canónica de precedencia.

    Texto canónico (contracts/ingesta-actos-modificatorios.md:153-164): "Cuando un
    acto posterior reglamente o modifique un artículo del 555, el acto posterior
    PREVALECE. Cita ambas normas sin ocultar los artículos del 555 (coexistencia
    de fuentes) e indica la norma de origen de cada cita."
    """
    provider, peticiones = _proveedor_con_captura()
    try:
        await provider._generar_respuesta_llm("vivienda colectiva", [_chunk_decreto_555()])
    finally:
        await provider.aclose()

    prompt = _prompt_del_usuario(peticiones)
    assert "PREVALECE" in prompt
    assert ("sin ocultar" in prompt) or ("coexistencia" in prompt)


@pytest.mark.asyncio
async def test_contexto_ordena_fragmentos_por_fecha_vigencia_descendente():
    """D7/FR-006: el acto más reciente (122, 2023-03-31) aparece PRIMERO en el contexto.

    Los chunks se entregan en orden de recuperación por similitud (555 primero);
    el contrato exige reordenar por `fecha_vigencia` descendente antes de armar
    el contexto: el 122 va antes que el 555 (research.md D7:136-150).
    """
    provider, peticiones = _proveedor_con_captura()
    try:
        await provider._generar_respuesta_llm(
            "vivienda colectiva",
            [_chunk_decreto_555(), _chunk_decreto_122()],
        )
    finally:
        await provider.aclose()

    prompt = _prompt_del_usuario(peticiones)
    assert "SEÑAL_122" in prompt and "SEÑAL_555" in prompt
    assert prompt.index("SEÑAL_122") < prompt.index("SEÑAL_555")


@pytest.mark.asyncio
async def test_payload_desactiva_thinking_de_modelos_razonadores():
    """El POST /api/chat incluye "think": false.

    Los modelos razonadores (p.ej. qwen3.5) tienen el modo thinking activo por
    defecto y generan miles de tokens de razonamiento que desbordan el timeout
    del provider o agotan el contexto antes del contenido final. Los modelos sin
    thinking ignoran el campo, así que es seguro enviarlo siempre.
    """
    provider, peticiones = _proveedor_con_captura()
    try:
        await provider._generar_respuesta_llm("vivienda colectiva", [_chunk_decreto_555()])
    finally:
        await provider.aclose()

    assert peticiones, "El POST /api/chat debió capturarse"
    assert peticiones[0].get("think") is False


@pytest.mark.asyncio
async def test_prompt_mantiene_citation_forcing_de_f2():
    """FR-003: se conserva la directriz de citas literales verificables de F2."""
    provider, peticiones = _proveedor_con_captura()
    try:
        await provider._generar_respuesta_llm("vivienda colectiva", [_chunk_decreto_555()])
    finally:
        await provider.aclose()

    prompt = _prompt_del_usuario(peticiones)
    assert "Cita el texto exacto" in prompt
    assert "NO la inventes" in prompt
