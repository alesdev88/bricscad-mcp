"""A summary of common problems in the current drawing."""

from typing import Any

from ..bridge import Bridge
from ..errors import BricsCADError
from ..lispgen import call
from ..server import mcp, session
from . import MAX_LIMIT, READ_ONLY, in_thread


def audit_report(
    bridge: Bridge,
    allowed_layers: list[str] | None = None,
    sample_limit: int = 50,
    timeout: float = 120.0,
) -> dict[str, Any]:
    if allowed_layers is not None and not allowed_layers:
        raise BricsCADError("allowed_layers is empty. Leave it out to skip the layer name check.")
    limit = max(0, min(sample_limit, MAX_LIMIT))
    return bridge.send(call("mcp:audit-report", allowed_layers, limit), timeout)


@mcp.tool(annotations=READ_ONLY)
async def bricscad_audit_report(
    allowed_layers: list[str] | None = None,
    sample_limit: int = 50,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Report empty layers, unused blocks, missing xrefs, entities not at zero elevation, and off-standard layer names.

    Each section has a total `count` and up to `sample_limit` `items`. Blocks and layers used only
    inside other blocks count as used, and a dynamic block counts as used through its anonymous
    states. Layers 0 and Defpoints are never reported.

    allowed_layers: name patterns such as ["A-*", "S-*"], ignoring case. Leave it out to skip this check.
    """

    def run() -> dict[str, Any]:
        return audit_report(session().require_bridge(), allowed_layers, sample_limit, timeout)

    return await in_thread(run)
