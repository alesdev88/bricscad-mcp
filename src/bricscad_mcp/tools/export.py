"""Exporting and plotting the current drawing. Nothing here changes the drawing."""

import os
import uuid
from pathlib import Path
from typing import Any, Callable, Literal

from ..bridge import Bridge
from ..errors import BricsCADError, SafetyRefused
from ..lispgen import call
from ..server import mcp
from . import DESTRUCTIVE
from .edit import is_same_file
from .read import _run

DxfVersion = Literal["R12", "2000", "2004", "2007", "2010", "2013", "2018"]


def check_output_target(path: str, suffix: str, state: dict[str, Any], overwrite: bool) -> Path:
    """Refuse a target before BricsCAD is involved. BricsCAD itself replaces files without asking."""
    if os.name != "nt" and "\\" in path:
        # Python sees one odd file name, and BricsCAD might see a folder, so no check would hold.
        raise BricsCADError(f"A file path cannot hold a backslash here: {path}")
    target = Path(path).expanduser().absolute()
    if target.suffix.lower() != suffix:
        raise BricsCADError(f"The file name must end in {suffix}: {target}")
    if target.is_dir():
        raise BricsCADError(f"This is a folder, not a file: {target}")
    if not target.parent.is_dir():
        raise BricsCADError(f"The folder does not exist: {target.parent}")
    open_files = [state["path"]] if state["titled"] else []
    open_files += state["other_open"]
    if any(Path(known).is_absolute() and is_same_file(known, target) for known in open_files):
        raise SafetyRefused(f"{target} is an open drawing, so it was left alone.")
    if target.exists():
        if not overwrite:
            raise SafetyRefused(f"{target} already exists. Pass overwrite=true to replace it.")
        if not os.access(target, os.W_OK):
            raise SafetyRefused(f"{target} is not writable, so it was left alone.")
    return target


def write_through_temporary(target: Path, produce: Callable[[Path], None]) -> dict[str, Any]:
    """Have BricsCAD write a new file beside the target, then move it into place.

    An existing target changes only once the new file is complete, and BricsCAD leaves no .bak,
    which could otherwise replace another file's backup.
    """
    temporary = target.with_name(f".{target.stem}.mcp-{uuid.uuid4().hex[:8]}{target.suffix}")
    try:
        produce(temporary)
        if not temporary.exists() or temporary.stat().st_size == 0:
            raise BricsCADError(f"BricsCAD did not write {target}.")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": target.as_posix(), "bytes": target.stat().st_size}


def export_dxf(
    bridge: Bridge, path: str, version: str = "2018", overwrite: bool = False, timeout: float = 120.0
) -> dict[str, Any]:
    target = check_output_target(path, ".dxf", bridge.send(call("mcp:save-state")), overwrite)
    result = write_through_temporary(
        target, lambda temporary: bridge.send(call("mcp:export-dxf", temporary.as_posix(), version), timeout)
    )
    return {**result, "version": version}


@mcp.tool(annotations=DESTRUCTIVE)
async def bricscad_export_dxf(
    path: str, version: DxfVersion = "2018", overwrite: bool = False, timeout: float = 120.0
) -> dict[str, Any]:
    """Write the current drawing as a DXF file. The drawing keeps its name and state.

    path: a .dxf file in an existing folder. It cannot be an open drawing.
    version: DXF version, R12 or 2000 to 2018.
    overwrite: true allows replacing an existing file. It is replaced only once the new one is complete.
    """
    return await _run(export_dxf, path, version, overwrite, timeout)
