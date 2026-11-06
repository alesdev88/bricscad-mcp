"""Opening and closing drawings."""

from pathlib import Path
from typing import Any

from ..bridge import Bridge
from ..errors import BricsCADError, SafetyRefused
from ..lispgen import call
from ..server import mcp, session
from . import CHANGES_STATE, DESTRUCTIVE, READ_ONLY, in_thread


def check_drawing_file(path: str) -> Path:
    """Refuse anything BricsCAD could answer with a dialog, before it gets there."""
    resolved = Path(path).expanduser().absolute()
    if not resolved.exists():
        raise BricsCADError(f"File not found: {resolved}")
    if resolved.is_dir():
        raise BricsCADError(f"This is a folder, not a drawing: {resolved}")
    if resolved.suffix.lower() == ".dxf":
        return resolved
    with resolved.open("rb") as file:
        if not file.read(3) == b"AC1":
            raise BricsCADError(f"This is not a drawing file (DWG or DXF): {resolved}")
    return resolved


def open_drawing(bridge: Bridge, path: str, read_only: bool = True) -> dict[str, Any]:
    return bridge.send(call("mcp:open-drawing", check_drawing_file(path).as_posix(), read_only))


def close_drawing(bridge: Bridge, discard: bool = False) -> dict[str, Any]:
    if not discard and bridge.send(call("mcp:active-modified-p")):
        raise SafetyRefused("This drawing has unsaved changes. Save it, or pass discard=true to lose them.")
    return {"closed": True, "current_drawing": bridge.send(call("mcp:close-drawing"))}


def drawing_info(bridge: Bridge) -> dict[str, Any]:
    return bridge.send(call("mcp:drawing-info"))


@mcp.tool(annotations=CHANGES_STATE)
async def bricscad_open_drawing(path: str, read_only: bool = True) -> dict[str, Any]:
    """Open a DWG or DXF and make it the current drawing. Returns the same details as bricscad_drawing_info.

    path: full path to the file.
    read_only: true by default, so the file cannot be overwritten by accident.
    """

    def run() -> dict[str, Any]:
        check_drawing_file(path)
        return open_drawing(session().require_bridge(), path, read_only)

    return await in_thread(run)


@mcp.tool(annotations=DESTRUCTIVE)
async def bricscad_close_drawing(discard: bool = False) -> dict[str, Any]:
    """Close the current drawing. Refuses if it has unsaved changes.

    discard: true closes it anyway and loses the unsaved changes.
    """

    def run() -> dict[str, Any]:
        return close_drawing(session().require_bridge(), discard)

    return await in_thread(run)


@mcp.tool(annotations=READ_ONLY)
async def bricscad_drawing_info() -> dict[str, Any]:
    """Describe the current drawing: name, path, read-only and modified state, units, limits, extents, entity count and layouts."""

    def run() -> dict[str, Any]:
        return drawing_info(session().require_bridge())

    return await in_thread(run)
