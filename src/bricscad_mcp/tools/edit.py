"""Drawing and editing. Each edit tool call is one all-or-nothing undo step."""

import math
import re
from typing import Any

from pydantic import TypeAdapter, ValidationError

from ..bridge import Bridge
from ..errors import BricsCADError
from ..lispgen import call
from ..server import mcp
from . import DESTRUCTIVE, MAX_LIMIT
from .read import _run
from .shapes import AttributeUpdate, Point, Rotate, Scale, line_breaks, point3

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


def _validated(kind: Any, value: Any) -> Any:
    try:
        return TypeAdapter(kind).validate_python(value)
    except ValidationError as error:
        raise BricsCADError(f"Invalid input: {error}") from error


def modify_entities(
    bridge: Bridge,
    handles: list[str],
    move: list[float] | None = None,
    rotate: Rotate | dict[str, Any] | None = None,
    scale: Scale | dict[str, Any] | None = None,
    layer: str | None = None,
    color: int | None = None,
    linetype: str | None = None,
    text: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    cleaned = check_handles(handles)
    if all(value is None for value in (move, rotate, scale, layer, color, linetype, text)):
        raise BricsCADError("Nothing to change. Give at least one of move, rotate, scale, layer, color, linetype or text.")
    if color is not None and not 0 <= color <= 256:
        raise BricsCADError("color must be from 0 to 256, where 0 is by block and 256 is by layer.")
    move_wire = None if move is None else point3(_validated(Point, move))
    rotate_wire = None
    if rotate is not None:
        turn: Rotate = _validated(Rotate, rotate)
        rotate_wire = [math.radians(turn.angle), point3(turn.base)]
    scale_wire = None
    if scale is not None:
        resize: Scale = _validated(Scale, scale)
        scale_wire = [resize.factor, point3(resize.base)]
    text_wire = None if text is None else line_breaks(text)
    return bridge.send(
        call("mcp:modify-entities", cleaned, move_wire, rotate_wire, scale_wire, layer, color, linetype, text_wire),
        timeout,
    )


@mcp.tool(annotations=DESTRUCTIVE)
async def bricscad_modify_entities(
    handles: list[str],
    move: list[float] | None = None,
    rotate: Rotate | None = None,
    scale: Scale | None = None,
    layer: str | None = None,
    color: int | None = None,
    linetype: str | None = None,
    text: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Change entities by handle. Changes all of them or none, and refuses locked layers.

    move: a displacement, [dx, dy] or [dx, dy, dz].
    rotate: {"angle": degrees, "base": point}.
    scale: {"factor": number above 0, "base": point}.
    layer: an existing layer. color: 0 by block, 1 to 255, or 256 by layer.
    linetype: loaded from iso.lin if the drawing does not have it yet.
    text: new text for TEXT, MTEXT or MULTILEADER. Change attributes with bricscad_set_attributes.
    """
    return await _run(modify_entities, handles, move, rotate, scale, layer, color, linetype, text, timeout)


def set_attributes(
    bridge: Bridge, updates: list[AttributeUpdate | dict[str, Any]], timeout: float = 30.0
) -> dict[str, Any]:
    checked: list[AttributeUpdate] = _validated(list[AttributeUpdate], updates)
    if not checked:
        raise BricsCADError("No updates given.")
    wire = [
        [check_handles([update.handle])[0], [[tag, value] for tag, value in update.values.items()]]
        for update in checked
    ]
    return bridge.send(call("mcp:set-attributes", wire), timeout)


@mcp.tool(annotations=DESTRUCTIVE)
async def bricscad_set_attributes(updates: list[AttributeUpdate], timeout: float = 30.0) -> dict[str, Any]:
    """Set attribute values on block inserts, such as a title block. Changes all of them or none.

    updates: [{"handle": insert handle, "values": {tag: text}}]. Get handles and tags from
    bricscad_read_attributes. Tags match whatever their case.
    """
    return await _run(set_attributes, updates, timeout)
