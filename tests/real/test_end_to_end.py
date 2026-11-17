"""The whole read flow: real command, real MCP connection, real BricsCAD."""

import hashlib
import shutil
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from bricscad_mcp.lispgen import lisp_path
from bricscad_mcp.platforms.base import is_alive

pytestmark = [pytest.mark.bricscad, pytest.mark.anyio]


def untitled_files() -> set[Path]:
    found = set()
    for folder in (Path.home() / "Downloads", Path.home() / "Documents"):
        found.update(folder.glob("Drawing[0-9]*"))
    return found


async def test_stdio_server_full_read_flow(tmp_path, no_shared_session):
    before_untitled = untitled_files()
    path = tmp_path / "Načrt št 1.dwg"
    command = shutil.which("bricscad-mcp", path=str(Path(sys.executable).parent))

    async with Client(StdioServerParameters(command=command)) as client:
        async def ok(tool, arguments=None):
            result = await client.call_tool(tool, arguments or {})
            assert not result.is_error, (tool, result.content)
            return result.structured_content

        started = await ok("bricscad_start")
        pid = started["pid"]
        assert is_alive(pid)

        await ok("bricscad_run_lisp", {"code": (
            "(entmakex (list '(0 . \"LINE\") '(10 0.0 0.0 0.0) '(11 1.0 1.0 0.0)))\n"
            f'(command "_.SAVEAS" "" {lisp_path(path)})\n'
            '(getvar "DWGNAME")'
        )})
        await ok("bricscad_close_drawing")
        before = path.read_bytes()

        info = await ok("bricscad_open_drawing", {"path": str(path)})
        assert info["read_only"] is True and info["entity_count"] == 1

        layers = await ok("bricscad_list_layers")
        assert "0" in [item["name"] for item in layers["items"]]
        entities = await ok("bricscad_query_entities", {"types": ["LINE"]})
        assert entities["total"] == 1
        handle = entities["items"][0]["handle"]
        assert (await ok("bricscad_get_entity", {"handle": handle}))["type"] == "LINE"
        audit = await ok("bricscad_audit_report")
        assert audit["non_zero_elevation"]["count"] == 0

        assert (await ok("bricscad_status"))["drawing"] == "Načrt št 1.dwg"
        await ok("bricscad_close_drawing")
        stopped = await ok("bricscad_stop")
        assert stopped["forced"] is False

    assert not is_alive(pid)
    assert path.read_bytes() == before
    assert untitled_files() == before_untitled


async def test_stdio_server_full_edit_flow(tmp_path, no_shared_session):
    before_untitled = untitled_files()
    source = tmp_path / "Načrt št 1.dwg"
    copy = tmp_path / "kopija.dwg"
    command = shutil.which("bricscad-mcp", path=str(Path(sys.executable).parent))

    async with Client(StdioServerParameters(command=command)) as client:
        async def ok(tool, arguments=None):
            result = await client.call_tool(tool, arguments or {})
            assert not result.is_error, (tool, result.content)
            return result.structured_content

        await ok("bricscad_start")
        await ok("bricscad_create_entities", {"entities": [{"type": "line", "start": [0, 0], "end": [1, 1]}]})
        await ok("bricscad_save_drawing", {"path": str(source)})
        await ok("bricscad_close_drawing")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()

        assert (await ok("bricscad_open_drawing", {"path": str(source)}))["read_only"] is True
        await ok("bricscad_set_layer", {"name": "Stene", "color": 3})
        created = await ok(
            "bricscad_create_entities",
            {
                "entities": [
                    {"type": "polyline", "vertices": [[0, 0], [5, 0], [5, 5]], "closed": True, "layer": "Stene"},
                    {"type": "text", "position": [1, 1], "text": "Soba", "height": 2.5, "layer": "Stene"},
                ]
            },
        )
        text = created["created"][1]["handle"]
        await ok("bricscad_modify_entities", {"handles": [text], "text": "Kuhinja"})
        assert (await ok("bricscad_undo"))["undone"] == 1
        assert (await ok("bricscad_find_text", {"query": "Soba"}))["total"] == 1

        info = await ok("bricscad_save_drawing", {"path": str(copy)})
        assert info["name"] == "kopija.dwg" and info["read_only"] is False and info["modified"] is False
        plotted = await ok("bricscad_plot_pdf", {"path": str(tmp_path / "kopija.pdf")})
        assert plotted["layout"] == "Model"
        preview = await client.call_tool("bricscad_preview_image", {})
        assert not preview.is_error and preview.content[0].type == "image"
        assert (await ok("bricscad_stop"))["forced"] is False

    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    assert copy.exists()
    assert (tmp_path / "kopija.pdf").read_bytes().startswith(b"%PDF")
    assert untitled_files() == before_untitled
