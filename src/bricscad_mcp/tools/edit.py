"""Drawing and editing. Each edit tool call is one all-or-nothing undo step."""

from typing import Any

from ..bridge import Bridge
from ..errors import BricsCADError
from ..lispgen import call
from ..server import mcp
from . import DESTRUCTIVE
from .read import _run

MAX_UNDO_STEPS = 100


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
