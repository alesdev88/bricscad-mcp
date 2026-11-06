"""MCP tools, one module per phase."""

from typing import Any, Callable

import anyio
from mcp.types import ToolAnnotations

DEFAULT_LIMIT = 200
MAX_LIMIT = 2000

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False)
CHANGES_STATE = ToolAnnotations(read_only_hint=False, destructive_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True)


def page_args(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, MAX_LIMIT)), max(0, offset)


async def in_thread(function: Callable[..., Any], *args: Any) -> Any:
    """Run blocking BricsCAD work without stalling the MCP connection."""
    return await anyio.to_thread.run_sync(function, *args)
