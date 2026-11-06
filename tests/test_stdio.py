"""The installed command, over a real stdio MCP connection. No BricsCAD needed."""

import shutil
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

pytestmark = pytest.mark.anyio


def server_command() -> str:
    return shutil.which("bricscad-mcp", path=str(Path(sys.executable).parent))


async def test_the_installed_command_serves_every_phase_1_tool():
    async with Client(StdioServerParameters(command=server_command())) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert names == {
        "bricscad_list_versions", "bricscad_start", "bricscad_stop", "bricscad_status", "bricscad_run_lisp",
        "bricscad_open_drawing", "bricscad_close_drawing", "bricscad_drawing_info",
        "bricscad_list_layers", "bricscad_list_blocks", "bricscad_list_xrefs", "bricscad_list_layouts",
        "bricscad_query_entities", "bricscad_get_entity", "bricscad_read_attributes", "bricscad_find_text",
        "bricscad_audit_report",
    }


async def test_status_works_before_start_over_stdio():
    async with Client(StdioServerParameters(command=server_command())) as client:
        result = await client.call_tool("bricscad_status", {})
    assert result.structured_content["running"] is False
