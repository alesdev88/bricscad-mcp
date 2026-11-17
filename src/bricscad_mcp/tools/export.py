"""Exporting and plotting the current drawing. Nothing here changes the drawing."""

import math
import os
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Literal

from ..bridge import Bridge
from ..errors import BricsCADError, SafetyRefused
from ..lispgen import call
from mcp.server.mcpserver import Image

from ..server import mcp, session
from . import DESTRUCTIVE, READ_ONLY, in_thread
from .edit import is_same_file
from .read import _run

DxfVersion = Literal["R12", "2000", "2004", "2007", "2010", "2013", "2018"]
PlotArea = Literal["extents", "layout", "window"]

_SCALE = re.compile(r"(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)", re.ASCII)


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


def check_window(window: list[float] | None) -> list[float] | None:
    if window is None:
        return None
    if len(window) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in window):
        raise BricsCADError("window must be [x1, y1, x2, y2] with finite numbers.")
    x1, y1, x2, y2 = (float(v) for v in window)
    if x1 == x2 or y1 == y2:
        raise BricsCADError("window must have a width and a height.")
    return [x1, y1, x2, y2]


def _check_answer(name: str, value: str | None) -> None:
    # Each answer is one line on BricsCAD's command line. A line break would answer the next question.
    if value is not None and ("\n" in value or "\r" in value):
        raise BricsCADError(f"{name} cannot hold a line break.")


def _check_scale(scale: str | None) -> None:
    if scale is None or scale == "fit":
        return
    match = _SCALE.fullmatch(scale)
    if not match or float(match.group(1)) == 0 or float(match.group(2)) == 0:
        raise BricsCADError(f'scale must be "fit" or plotted millimetres to drawing units, such as "1:100": {scale}')


def plot_pdf(
    bridge: Bridge,
    path: str,
    layout: str | None = None,
    paper: str | None = None,
    landscape: bool | None = None,
    area: str | None = None,
    window: list[float] | None = None,
    scale: str | None = None,
    style_table: str | None = None,
    overwrite: bool = False,
    timeout: float = 120.0,
) -> dict[str, Any]:
    for name, value in (("layout", layout), ("paper", paper), ("style_table", style_table)):
        _check_answer(name, value)
    _check_scale(scale)
    if area == "window" and window is None:
        raise BricsCADError('area="window" needs window=[x1, y1, x2, y2].')
    if window is not None and area != "window":
        raise BricsCADError('window is only used with area="window".')
    window = check_window(window)
    target = check_output_target(path, ".pdf", bridge.send(call("mcp:save-state")), overwrite)
    side = None if landscape is None else int(landscape)
    plotted: list[str] = []

    def produce(temporary: Path) -> None:
        plotted.append(
            bridge.send(
                call("mcp:plot-pdf", temporary.as_posix(), layout, paper, side, area, window, scale, style_table),
                timeout,
            )
        )

    return {**write_through_temporary(target, produce), "layout": plotted[0]}


@mcp.tool(annotations=DESTRUCTIVE)
async def bricscad_plot_pdf(
    path: str,
    layout: str | None = None,
    paper: str | None = None,
    landscape: bool | None = None,
    area: PlotArea | None = None,
    window: list[float] | None = None,
    scale: str | None = None,
    style_table: str | None = None,
    overwrite: bool = False,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Plot one layout of the current drawing to a PDF file, with Print As PDF.pc3. The drawing is not changed.

    path: a .pdf file in an existing folder.
    layout: "Model" or a sheet name. Defaults to the current layout.
    paper: BricsCAD's paper name, such as "ISO A3 (297.00 x 420.00 MM)". Defaults to the layout's current size.
    landscape: true or false. Defaults to the layout's current orientation.
    area: "extents", "layout" (sheets only) or "window". Defaults to extents for the model and layout for sheets.
    window: [x1, y1, x2, y2] in drawing units, with area="window".
    scale: "fit", or plotted millimetres to drawing units such as "1:100". Defaults to fit for the model
    and 1:1 for sheets.
    style_table: a plot style table such as "monochrome.ctb". Defaults to the layout's own.
    overwrite: true allows replacing an existing file. It is replaced only once the new one is complete.
    """
    return await _run(plot_pdf, path, layout, paper, landscape, area, window, scale, style_table, overwrite, timeout)


def preview_image(
    bridge: Bridge,
    preview_dir: Path,
    layout: str | None = None,
    window: list[float] | None = None,
    timeout: float = 60.0,
) -> bytes:
    _check_answer("layout", layout)
    window = check_window(window)
    preview_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = preview_dir / f"{uuid.uuid4().hex}.png"
    try:
        bridge.send(call("mcp:preview-image", path.as_posix(), layout, window), timeout)
        png = path.read_bytes() if path.exists() else b""
    finally:
        path.unlink(missing_ok=True)
    if not png:
        raise BricsCADError("BricsCAD made no preview image.")
    return png


@mcp.tool(annotations=READ_ONLY)
async def bricscad_preview_image(
    layout: str | None = None, window: list[float] | None = None, timeout: float = 60.0
) -> Image:
    """Return a PNG of the current drawing, to check work by eye. The drawing is not changed.

    layout: "Model" or a sheet name. Defaults to the current layout. The whole layout is shown.
    window: [x1, y1, x2, y2] in drawing units, to show only that area.
    The image is the size of the BricsCAD window. The model shows on black, as on screen.
    """

    def run() -> Image:
        bridge = session().require_bridge()
        return Image(data=preview_image(bridge, bridge.queue_dir.parent / "previews", layout, window, timeout), format="png")

    return await in_thread(run)
