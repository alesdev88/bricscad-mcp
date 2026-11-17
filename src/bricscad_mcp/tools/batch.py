"""One job across many drawings. Sources open read-only and are written only with overwrite=true."""

import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import Field, TypeAdapter

from ..bridge import Bridge
from ..errors import BricsCADError, BridgeTimeout, ProcessDied, SafetyRefused
from ..lispgen import call
from ..server import mcp, session
from . import DESTRUCTIVE, MAX_LIMIT, in_thread
from .drawing import check_drawing_file
from .edit import is_same_file
from .export import DxfVersion, PlotArea, check_output_target, check_plot_options, write_through_temporary
from .shapes import Strict

MAX_FILES = 500

# Before BricsCAD is asked, nothing is open as far as the target checks go.
_NOTHING_OPEN = {"path": "", "titled": 0, "read_only": False, "other_open": []}


class AuditJob(Strict):
    type: Literal["audit"]
    allowed_layers: list[str] | None = None
    sample_limit: int = Field(10, ge=0, le=MAX_LIMIT)


class FindTextJob(Strict):
    type: Literal["find_text"]
    query: str = Field(min_length=1)
    case_sensitive: bool = False
    limit: int = Field(50, ge=1, le=MAX_LIMIT)


class ExportDxfJob(Strict):
    type: Literal["export_dxf"]
    version: DxfVersion = "2018"


class PlotPdfJob(Strict):
    type: Literal["plot_pdf"]
    layout: str | None = None
    paper: str | None = None
    landscape: bool | None = None
    area: PlotArea | None = None
    window: list[float] | None = None
    scale: str | None = None
    style_table: str | None = None


class SaveAsJob(Strict):
    type: Literal["save_as"]


class LispJob(Strict):
    type: Literal["lisp"]
    code: str = Field(min_length=1)
    save: bool = False


Job = Annotated[
    Union[AuditJob, FindTextJob, ExportDxfJob, PlotPdfJob, SaveAsJob, LispJob], Field(discriminator="type")
]
_JOB = TypeAdapter(Job)


def parse_job(value: Any) -> Job:
    return _JOB.validate_python(value)


def output_suffix(job: Job) -> str | None:
    """The file type a job writes, or None if it writes nothing."""
    if isinstance(job, ExportDxfJob):
        return ".dxf"
    if isinstance(job, PlotPdfJob):
        return ".pdf"
    if isinstance(job, SaveAsJob) or (isinstance(job, LispJob) and job.save):
        return ".dwg"
    return None


def every_sheet(job: Job) -> bool:
    return isinstance(job, PlotPdfJob) and job.layout == "*"


@dataclass
class FilePlan:
    source: Path
    target: Path | None = None
    refused: str | None = None
    folder: Path | None = None  # where a writing job writes


def list_sources(
    files: list[str] | None, folder: str | None, pattern: str = "*.dwg", recursive: bool = False
) -> list[Path]:
    if (files is None) == (folder is None):
        raise BricsCADError("Give either files or folder.")
    if folder is not None:
        root = Path(folder).expanduser().absolute()
        if not root.is_dir():
            raise BricsCADError(f"The folder does not exist: {root}")
        found = root.rglob(pattern) if recursive else root.glob(pattern)
        candidates = sorted(path for path in found if path.is_file())
    else:
        candidates = [Path(path) for path in files]
    sources: list[Path] = []
    for candidate in candidates:
        checked = check_drawing_file(str(candidate))
        if not any(is_same_file(str(known), checked) for known in sources):
            sources.append(checked)
    if not sources:
        raise BricsCADError("No drawings found.")
    if len(sources) > MAX_FILES:
        raise BricsCADError(f"{len(sources)} drawings found. A batch takes up to {MAX_FILES}; split it.")
    return sources


def plan(sources: list[Path], job: Job, output_folder: str | None, overwrite: bool) -> list[FilePlan]:
    if isinstance(job, PlotPdfJob):
        layout = None if job.layout == "*" else job.layout
        job.window = check_plot_options(layout, job.paper, job.area, job.window, job.scale, job.style_table)
    suffix = output_suffix(job)
    if suffix is None:
        if output_folder is not None:
            raise BricsCADError("This job writes nothing, so leave out output_folder.")
        return [FilePlan(source) for source in sources]
    if output_folder is None:
        raise BricsCADError("This job writes files, so it needs output_folder.")
    out = Path(output_folder).expanduser().absolute()
    if not out.is_dir():
        raise BricsCADError(f"The output folder does not exist: {out}")
    if not os.access(out, os.W_OK):
        raise SafetyRefused(f"The output folder is not writable: {out}")
    if every_sheet(job):
        return [FilePlan(source, folder=out) for source in sources]
    plans = [FilePlan(source, out / f"{source.stem}{suffix}", folder=out) for source in sources]
    _refuse_shared_targets(plans)
    for item in plans:
        try:
            check_output_target(str(item.target), suffix, _NOTHING_OPEN, overwrite)
        except SafetyRefused as refusal:
            item.refused = str(refusal)
    return plans


def _refuse_shared_targets(plans: list[FilePlan]) -> None:
    seen: dict[str, Path] = {}
    for item in plans:
        key = item.target.name.casefold()
        if key in seen:
            raise BricsCADError(f"{seen[key]} and {item.source} would both write {item.target}.")
        seen[key] = item.source


def _plot_args(job: PlotPdfJob) -> list[Any]:
    side = None if job.landscape is None else int(job.landscape)
    return [job.paper, side, job.area, job.window, job.scale, job.style_table]


def _worker(job: Job, temporary: Path | None) -> tuple[str, list[Any]]:
    """The LISP worker and its arguments. temporary: where a writing job writes."""
    if isinstance(job, AuditJob):
        return "mcp:audit-report", [job.allowed_layers, job.sample_limit]
    if isinstance(job, FindTextJob):
        return "mcp:find-text", [job.query, job.case_sensitive, job.limit, 0]
    if isinstance(job, ExportDxfJob):
        return "mcp:export-dxf-now", [temporary.as_posix(), job.version]
    if isinstance(job, PlotPdfJob):
        return "mcp:plot-pdf-now", [temporary.as_posix(), job.layout, *_plot_args(job)]
    if isinstance(job, SaveAsJob):
        return "mcp:save-copy", [temporary.as_posix()]
    return "mcp:batch-lisp", [job.code, temporary.as_posix() if temporary else None]


def _send(bridge: Bridge, item: FilePlan, worker: str, args: list[Any], timeout: float) -> Any:
    return bridge.send(call("mcp:batch-file", item.source.as_posix(), worker, args), timeout)


def _run_one(
    bridge: Bridge, job: Job, item: FilePlan, state: dict[str, Any], overwrite: bool, timeout: float
) -> tuple[Any, list[str]]:
    suffix = output_suffix(job)
    if suffix is None:
        return _send(bridge, item, *_worker(job, None), timeout), []
    if every_sheet(job):
        return _plot_every_sheet(bridge, job, item, state, overwrite, timeout)
    # Checked again now that BricsCAD says which drawings are open.
    check_output_target(str(item.target), suffix, state, overwrite)
    results: list[Any] = []
    write_through_temporary(
        item.target, lambda temporary: results.append(_send(bridge, item, *_worker(job, temporary), timeout))
    )
    return (results[0] if isinstance(job, (PlotPdfJob, LispJob)) else None), [item.target.as_posix()]


_UNSAFE = re.compile(r'[<>:"/\\|?*]')


def _plot_every_sheet(
    bridge: Bridge, job: PlotPdfJob, item: FilePlan, state: dict[str, Any], overwrite: bool, timeout: float
) -> tuple[Any, list[str]]:
    out = item.folder
    folder = out / f".mcp-{uuid.uuid4().hex[:8]}"
    folder.mkdir()
    try:
        sheets = _send(bridge, item, "mcp:plot-sheets", [folder.as_posix(), *_plot_args(job)], timeout)
        moves = [
            (folder / f"{n}.pdf", out / f"{item.source.stem}-{_UNSAFE.sub('_', sheet)}.pdf")
            for n, sheet in enumerate(sheets, start=1)
        ]
        for _, target in moves:
            check_output_target(str(target), ".pdf", state, overwrite)
        for plotted, target in moves:
            if not plotted.exists() or plotted.stat().st_size == 0:
                raise BricsCADError(f"BricsCAD did not write {target}.")
        for plotted, target in moves:
            os.replace(plotted, target)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return sheets, [target.as_posix() for _, target in moves]


def _entry(item: FilePlan, status: str, outputs: list[str] | None = None, **fields: Any) -> dict[str, Any]:
    """outputs: what was written. Left out, it is what the plan would write."""
    if outputs is None:
        outputs = [item.target.as_posix()] if item.target is not None else []
    return {"source": item.source.as_posix(), "status": status, "outputs": outputs, "result": None, "error": None,
            **fields}


def batch_run(
    bridge: Bridge | None,
    job: Job,
    files: list[str] | None = None,
    folder: str | None = None,
    pattern: str = "*.dwg",
    recursive: bool = False,
    output_folder: str | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
    timeout: float = 120.0,
) -> dict[str, Any]:
    plans = plan(list_sources(files, folder, pattern, recursive), job, output_folder, overwrite)
    entries: list[dict[str, Any]] = []
    stopped: str | None = None
    current: str | None = None
    if dry_run:
        entries = [_entry(item, "refused" if item.refused else "planned", error=item.refused) for item in plans]
    else:
        if bridge is None:
            raise BricsCADError("BricsCAD is not running. Start it with bricscad_start, or use dry_run.")
        state = bridge.send(call("mcp:save-state"))
        open_now = ([state["path"]] if state["titled"] else []) + state["other_open"]
        for item in plans:
            if stopped:
                entries.append(_entry(item, "not_run"))
            elif item.refused:
                entries.append(_entry(item, "refused", error=item.refused))
            elif any(Path(known).is_absolute() and is_same_file(known, item.source) for known in open_now):
                entries.append(_entry(item, "refused", error="It is open in BricsCAD. Close it first, or leave it out."))
            else:
                try:
                    result, outputs = _run_one(bridge, job, item, state, overwrite, timeout)
                    entries.append(_entry(item, "ok", outputs, result=result))
                except (BridgeTimeout, ProcessDied) as error:
                    stopped = str(error)
                    entries.append(_entry(item, "failed", error=stopped))
                except BricsCADError as error:
                    entries.append(_entry(item, "failed", error=str(error)))
        if not stopped:
            current = bridge.send('(getvar "DWGNAME")')
    count = lambda status: sum(1 for entry in entries if entry["status"] == status)  # noqa: E731
    return {
        "dry_run": dry_run, "total": len(entries), "succeeded": count("ok"), "failed": count("failed"),
        "refused": count("refused"), "not_run": count("not_run"), "stopped": stopped, "current_drawing": current,
        "files": entries,
    }


@mcp.tool(annotations=DESTRUCTIVE)
async def bricscad_batch_run(
    job: Job,
    files: list[str] | None = None,
    folder: str | None = None,
    pattern: str = "*.dwg",
    recursive: bool = False,
    output_folder: str | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Run one job on many drawings, one at a time, and report a result per file. Try dry_run first.

    job: {"type": ...} with its options. audit and find_text write nothing. export_dxf, plot_pdf
    (layout "*" plots every sheet to <name>-<sheet>.pdf), save_as and lisp with save=true write
    <name>.dxf, .pdf or .dwg into output_folder. lisp runs code in each drawing and returns its value.
    files or folder: the drawings, up to 500. folder takes a glob pattern, and recursive for subfolders.
    Sources open read-only. A source is replaced only when output_folder is its own folder and
    overwrite=true. Drawings already open in BricsCAD are refused.
    timeout: seconds per file. A timeout stops the batch, since a dialog may be blocking BricsCAD.
    Afterwards the current drawing may be another open drawing.
    """

    def run() -> dict[str, Any]:
        bridge = None if dry_run else session().require_bridge()
        return batch_run(bridge, job, files, folder, pattern, recursive, output_folder, overwrite, dry_run, timeout)

    return await in_thread(run)
