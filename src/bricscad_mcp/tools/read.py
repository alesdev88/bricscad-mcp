"""Reading what is in the current drawing. Nothing here changes it."""

from typing import Any

from ..bridge import Bridge
from ..errors import BricsCADError
from ..lispgen import call
from ..server import mcp, session
from . import DEFAULT_LIMIT, READ_ONLY, in_thread, page_args

Page = dict[str, Any]


def list_layers(bridge: Bridge, limit: int = DEFAULT_LIMIT, offset: int = 0) -> Page:
    return bridge.send(call("mcp:list-layers", *page_args(limit, offset)))


def list_blocks(bridge: Bridge, include_anonymous: bool = False, limit: int = DEFAULT_LIMIT, offset: int = 0) -> Page:
    return bridge.send(call("mcp:list-blocks", include_anonymous, *page_args(limit, offset)))


def list_xrefs(bridge: Bridge, limit: int = DEFAULT_LIMIT, offset: int = 0) -> Page:
    return bridge.send(call("mcp:list-xrefs", *page_args(limit, offset)))


def list_layouts(bridge: Bridge, limit: int = DEFAULT_LIMIT, offset: int = 0) -> Page:
    return bridge.send(call("mcp:list-layouts", *page_args(limit, offset)))


def query_entities(
    bridge: Bridge,
    types: list[str] | None = None,
    layer: str | None = None,
    block: str | None = None,
    bbox: list[float] | None = None,
    layout: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    timeout: float = 30.0,
) -> Page:
    joined = ",".join(name.upper() for name in types) if types else None
    expr = call("mcp:query-entities", joined, layer, block, _checked_bbox(bbox), layout, *page_args(limit, offset))
    return bridge.send(expr, timeout)


def get_entity(bridge: Bridge, handle: str) -> dict[str, Any]:
    return bridge.send(call("mcp:get-entity", handle))


def read_attributes(
    bridge: Bridge,
    block: str | None = None,
    layout: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    timeout: float = 30.0,
) -> Page:
    return bridge.send(call("mcp:read-attributes", block, layout, *page_args(limit, offset)), timeout)


def find_text(
    bridge: Bridge,
    query: str,
    case_sensitive: bool = False,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    timeout: float = 30.0,
) -> Page:
    if not query:
        raise BricsCADError("The search text is empty.")
    return bridge.send(call("mcp:find-text", query, case_sensitive, *page_args(limit, offset)), timeout)


def _checked_bbox(bbox: list[float] | None) -> list[float] | None:
    if bbox is None:
        return None
    if len(bbox) != 4 or bbox[0] > bbox[2] or bbox[1] > bbox[3]:
        raise BricsCADError("bbox must be [min_x, min_y, max_x, max_y].")
    return [float(value) for value in bbox]


async def _run(function, *args) -> Any:
    return await in_thread(lambda: function(session().require_bridge(), *args))


@mcp.tool(annotations=READ_ONLY)
async def bricscad_list_layers(limit: int = DEFAULT_LIMIT, offset: int = 0) -> Page:
    """List layers with their on, frozen and locked state, color, linetype and entity count. Up to 2000 per call."""
    return await _run(list_layers, limit, offset)


@mcp.tool(annotations=READ_ONLY)
async def bricscad_list_blocks(include_anonymous: bool = False, limit: int = DEFAULT_LIMIT, offset: int = 0) -> Page:
    """List block definitions with insert counts, including inserts nested in other blocks. Up to 2000 per call."""
    return await _run(list_blocks, include_anonymous, limit, offset)


@mcp.tool(annotations=READ_ONLY)
async def bricscad_list_xrefs(limit: int = DEFAULT_LIMIT, offset: int = 0) -> Page:
    """List external references with their stored path and whether the file was found. Up to 2000 per call."""
    return await _run(list_xrefs, limit, offset)


@mcp.tool(annotations=READ_ONLY)
async def bricscad_list_layouts(limit: int = DEFAULT_LIMIT, offset: int = 0) -> Page:
    """List Model and the paper space layouts with their entity counts. Up to 2000 per call."""
    return await _run(list_layouts, limit, offset)


@mcp.tool(annotations=READ_ONLY)
async def bricscad_query_entities(
    types: list[str] | None = None,
    layer: str | None = None,
    block: str | None = None,
    bbox: list[float] | None = None,
    layout: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    timeout: float = 30.0,
) -> Page:
    """Find entities in the current drawing. Returns handle, type, layer, layout and bounding box. Up to 2000 per call.

    types: DXF names such as ["LINE", "CIRCLE"].
    layer, block: names, which may use the wildcards * and ?.
    bbox: [min_x, min_y, max_x, max_y]; entities overlapping it match.
    layout: "Model" or a layout name.
    """
    return await _run(query_entities, types, layer, block, bbox, layout, limit, offset, timeout)


@mcp.tool(annotations=READ_ONLY)
async def bricscad_get_entity(handle: str) -> dict[str, Any]:
    """Return one entity's type, layer and all its DXF group codes, as [code, value] pairs."""
    return await _run(get_entity, handle)


@mcp.tool(annotations=READ_ONLY)
async def bricscad_read_attributes(
    block: str | None = None,
    layout: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    timeout: float = 30.0,
) -> Page:
    """Read attribute values from block inserts, for example title block contents. Up to 2000 per call.

    block: a block name, which may use the wildcards * and ?.
    layout: "Model" or a layout name.
    """
    return await _run(read_attributes, block, layout, limit, offset, timeout)


@mcp.tool(annotations=READ_ONLY)
async def bricscad_find_text(
    query: str,
    case_sensitive: bool = False,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    timeout: float = 30.0,
) -> Page:
    """Search TEXT, MTEXT and block attribute values for literal text. Up to 2000 per call."""
    return await _run(find_text, query, case_sensitive, limit, offset, timeout)
