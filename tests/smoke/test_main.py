"""Smoke test de arranque (T031): el servidor inicia y registra exactamente las 7 tools (4 F1 + 2 F2 + 1 F3)."""

from __future__ import annotations

import pytest

TOOLS_ESPERADAS = {
    "resolve_lot_by_chip",
    "resolve_lot_by_address",
    "resolve_lot_by_coordinates",
    "get_lot_summary_by_chip",
    "get_upl",
    "consultar_normativa",
    "get_feasibility_report",
}


@pytest.mark.asyncio
async def test_el_servidor_registra_exactamente_las_7_tools():
    import app.main as modulo

    try:
        tools = await modulo.mcp.list_tools()
        nombres = {t.name for t in tools}
        assert nombres == TOOLS_ESPERADAS
        assert len(tools) == 7
    finally:
        await modulo.servidor_lotes.aclose()


@pytest.mark.asyncio
async def test_create_server_registra_las_7_tools_con_providers_simulados():
    from tests.conftest import construir_servidor

    servidor = construir_servidor()
    try:
        from app.main import crear_servidor_mcp

        mcp = crear_servidor_mcp(servidor)
        tools = await mcp.list_tools()
        nombres = {t.name for t in tools}
        assert nombres == TOOLS_ESPERADAS
        assert len(tools) == 7
    finally:
        await servidor.aclose()