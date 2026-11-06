"""Starting, stopping and raw LISP."""

from typing import Any

from ..server import mcp, session
from . import CHANGES_STATE, DESTRUCTIVE, READ_ONLY, in_thread


@mcp.tool(annotations=READ_ONLY)
async def bricscad_list_versions() -> dict[str, Any]:
    """List the BricsCAD versions installed on this computer, newest first."""
    found = await in_thread(session().platform.find_installations)
    return {"versions": [{"version": item.version, "path": str(item.executable)} for item in found]}


@mcp.tool(annotations=CHANGES_STATE)
async def bricscad_start(version: str | None = None) -> dict[str, Any]:
    """Start BricsCAD in its own window and connect to it. Refuses if that version is already running.

    version: for example "26". Defaults to BRICSCAD_VERSION, then the newest installed.
    """
    return await in_thread(session().start, version)


@mcp.tool(annotations=DESTRUCTIVE)
async def bricscad_stop(discard: bool = False) -> dict[str, Any]:
    """Close the BricsCAD this server started. Refuses if drawings have unsaved changes.

    discard: true closes it anyway and loses the unsaved changes.
    """
    return await in_thread(session().stop, discard)


@mcp.tool(annotations=READ_ONLY)
async def bricscad_status() -> dict[str, Any]:
    """Report whether BricsCAD is running, how recently its listener reported, and the current drawing."""
    return await in_thread(session().status)


@mcp.tool(annotations=DESTRUCTIVE)
async def bricscad_run_lisp(code: str, timeout: float = 30.0) -> dict[str, Any]:
    """Run LISP in BricsCAD and return the value of its last expression.

    LISP can change or delete files and start programs, so use a dedicated tool where one exists.
    Do not use vla-save or vla-saveas: they open a dialog or fail. Use _.QSAVE or _.SAVEAS.
    Do not close the only open drawing: the listener stops.

    code: one or more LISP expressions.
    timeout: seconds to wait for an answer.
    """

    def run() -> Any:
        return session().require_bridge().send(code, timeout)

    return {"result": await in_thread(run)}
