"""Drawing and editing. Each edit tool call is one all-or-nothing undo step."""

import re
from typing import Any

from ..bridge import Bridge
from ..errors import BricsCADError
from ..lispgen import call
from ..server import mcp
from . import DESTRUCTIVE, MAX_LIMIT
from .read import _run

MAX_UNDO_STEPS = 100
_HANDLE = re.compile(r"[0-9A-F]+")


def undo(bridge: Bridge, steps: int = 1, timeout: float = 30.0) -> dict[str, Any]:
    if not 1 <= steps <= MAX_UNDO_STEPS:
        raise BricsCADError(f"steps must be between 1 and {MAX_UNDO_STEPS}.")
    return bridge.send(call("mcp:undo", steps), timeout)


@mcp.tool(annotations=DESTRUCTIVE)
async def bricscad_undo(steps: int = 1, timeout: float = 30.0) -> dict[str, Any]:
    """Undo the last edits to the current drawing. Returns how many steps were undone.

    One step is one successful edit tool call. Edits made through bricscad_run_lisp have no
    step of their own, so they go back with the step before them.
    steps: how many steps to undo, from 1 to 100. It stops at the oldest step.
    """
    return await _run(undo, steps, timeout)


def check_handles(handles: list[str]) -> list[str]:
    """Uppercase the handles and drop repeats, keeping their order."""
    cleaned = list(dict.fromkeys(handle.strip().upper() for handle in handles))
    if not cleaned:
        raise BricsCADError("No handles given.")
    if len(cleaned) > MAX_LIMIT:
        raise BricsCADError(f"At most {MAX_LIMIT} handles per call.")
    for handle in cleaned:
        if not _HANDLE.fullmatch(handle):
            raise BricsCADError(f"Not an entity handle: {handle!r}")
    return cleaned


def erase_entities(bridge: Bridge, handles: list[str], timeout: float = 30.0) -> dict[str, Any]:
    return bridge.send(call("mcp:erase-entities", check_handles(handles)), timeout)


@mcp.tool(annotations=DESTRUCTIVE)
async def bricscad_erase_entities(handles: list[str], timeout: float = 30.0) -> dict[str, Any]:
    """Erase entities by handle. Erases all of them or none. bricscad_undo restores them.

    Refuses entities on locked layers and attributes, which belong to their block insert.
    """
    return await _run(erase_entities, handles, timeout)
