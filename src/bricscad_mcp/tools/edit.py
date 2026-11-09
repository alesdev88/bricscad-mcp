"""Drawing and editing. Each edit tool call is one all-or-nothing undo step."""

import math
import os
import re
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from ..bridge import Bridge
from ..errors import BricsCADError, SafetyRefused
from ..lispgen import call
from ..server import mcp
from . import CHANGES_STATE, DESTRUCTIVE, MAX_LIMIT
from .read import _run
from .shapes import AttributeUpdate, Entity, Point, Rotate, Scale, line_breaks, point3

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


def create_entities(
    bridge: Bridge, entities: list[Any], layout: str | None = None, timeout: float = 30.0
) -> dict[str, Any]:
    checked = _validated(list[Entity], entities)
    if not checked:
        raise BricsCADError("No entities given.")
    if len(checked) > MAX_LIMIT:
        raise BricsCADError(f"At most {MAX_LIMIT} entities per call.")
    return bridge.send(call("mcp:create-entities", layout, [entity.to_wire() for entity in checked]), timeout)


@mcp.tool(annotations=CHANGES_STATE)
async def bricscad_create_entities(
    entities: list[Entity], layout: str | None = None, timeout: float = 30.0
) -> dict[str, Any]:
    """Draw entities and return their handles. Draws all of them or none, as one undo step.

    entities: up to 2000 items, each with a type and an optional layer, which must exist.
    Points are [x, y] or [x, y, z]. Angles are degrees.
    layout: a sheet name. The default is the model, whichever tab is current.
    """
    return await _run(create_entities, entities, layout, timeout)


def _is_same_file(known: str, target: Path) -> bool:
    """True however the two are spelled: through a link, in another letter case or Unicode form."""
    other = Path(known)
    if other.exists() and target.exists():
        return os.path.samefile(other, target)
    return other.absolute() == target


def _check_save_target(target: Path, state: dict[str, Any], overwrite: bool) -> None:
    if target.suffix.lower() != ".dwg":
        raise BricsCADError(
            f"Only .dwg files can be saved here: {target}. DXF export comes with bricscad_export_dxf in Phase 3."
        )
    if target.is_dir():
        raise BricsCADError(f"This is a folder, not a file: {target}")
    if not target.parent.is_dir():
        raise BricsCADError(f"The folder does not exist: {target.parent}")
    if state["titled"] and state["read_only"] and _is_same_file(state["path"], target):
        raise SafetyRefused("This drawing is read-only, so it must be saved to a new path.")
    if any(Path(path).is_absolute() and _is_same_file(path, target) for path in state["other_open"]):
        raise SafetyRefused(f"{target} is open as another drawing. Close it first.")
    if target.exists():
        if not overwrite:
            raise SafetyRefused(f"{target} already exists. Pass overwrite=true to replace it.")
        if not os.access(target, os.W_OK):
            raise SafetyRefused(f"{target} is not writable, so it was left alone.")


def save_drawing(
    bridge: Bridge, path: str | None = None, overwrite: bool = False, timeout: float = 120.0
) -> dict[str, Any]:
    state = bridge.send(call("mcp:save-state"))
    if path is not None:
        target = Path(path).expanduser().absolute()
        _check_save_target(target, state, overwrite)
        return bridge.send(call("mcp:save-as", target.as_posix(), overwrite), timeout)
    if not state["titled"]:
        raise BricsCADError("This drawing has no file yet. Give a path to save it to.")
    if state["read_only"]:
        raise SafetyRefused("This drawing is read-only, so it must be saved to a new path.")
    if not overwrite:
        raise SafetyRefused("Saving replaces the open file. Pass overwrite=true to do that, or give a new path.")
    return bridge.send(call("mcp:qsave"), timeout)


@mcp.tool(annotations=DESTRUCTIVE)
async def bricscad_save_drawing(
    path: str | None = None, overwrite: bool = False, timeout: float = 120.0
) -> dict[str, Any]:
    """Save the current drawing. Returns the same details as bricscad_drawing_info.

    path: a new .dwg path. The drawing then continues under that name, and is no longer read-only.
    Leave it out to save over the open file, which needs overwrite=true.
    overwrite: true allows replacing an existing file. BricsCAD leaves a .bak beside it.
    A read-only drawing cannot be saved over its own file, and a file open as another drawing
    cannot be replaced.
    """
    return await _run(save_drawing, path, overwrite, timeout)
