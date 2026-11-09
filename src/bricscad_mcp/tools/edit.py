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
_LAYER_NAME_FORBIDDEN = set('<>/\\":;?*|,=`')


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


def _check_layer_name(name: str) -> None:
    if not name or _LAYER_NAME_FORBIDDEN.intersection(name):
        raise BricsCADError(f"Not a valid layer name: {name!r}. It cannot be empty or hold any of < > / \\ \" : ; ? * | , = `")


def _switch(value: bool | None) -> int | None:
    """LISP has no false: nil means leave it alone, so a switch goes as nil, 0 or 1."""
    return None if value is None else int(value)


def set_layer(
    bridge: Bridge,
    name: str,
    new_name: str | None = None,
    color: int | None = None,
    linetype: str | None = None,
    on: bool | None = None,
    frozen: bool | None = None,
    locked: bool | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    _check_layer_name(name)
    if new_name is not None:
        _check_layer_name(new_name)
    if color is not None and not 1 <= color <= 255:
        raise BricsCADError("color must be a color number from 1 to 255.")
    return bridge.send(
        call("mcp:set-layer", name, new_name, color, linetype, _switch(on), _switch(frozen), _switch(locked)), timeout
    )


@mcp.tool(annotations=DESTRUCTIVE)
async def bricscad_set_layer(
    name: str,
    new_name: str | None = None,
    color: int | None = None,
    linetype: str | None = None,
    on: bool | None = None,
    frozen: bool | None = None,
    locked: bool | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Create a layer, or change one that exists. Only the values you give are changed.

    new_name: rename the layer. Layers 0 and Defpoints cannot be renamed.
    color: a color number from 1 to 255.
    linetype: loaded from iso.lin if the drawing does not have it yet.
    on, frozen, locked: true or false. The current layer cannot be frozen.
    """
    return await _run(set_layer, name, new_name, color, linetype, on, frozen, locked, timeout)
