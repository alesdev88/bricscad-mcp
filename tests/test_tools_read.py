import pytest

pytestmark = pytest.mark.anyio

PAGE = {"items": [], "total": 0, "limit": 200, "offset": 0}


@pytest.fixture
async def started(client, fake):
    for name in (
        "mcp:list-layers", "mcp:list-blocks", "mcp:list-xrefs", "mcp:list-layouts",
        "mcp:query-entities", "mcp:read-attributes", "mcp:find-text",
    ):
        fake.responses[name] = PAGE
    fake.responses["mcp:get-entity"] = {"handle": "1A", "type": "LINE", "layer": "0", "dxf": []}
    await client.call_tool("bricscad_start", {})
    fake.requests.clear()
    return client


@pytest.mark.parametrize(
    "tool,function",
    [
        ("bricscad_list_layers", "mcp:list-layers"),
        ("bricscad_list_xrefs", "mcp:list-xrefs"),
        ("bricscad_list_layouts", "mcp:list-layouts"),
    ],
)
async def test_list_tools_default_to_200(started, fake, tool, function):
    result = await started.call_tool(tool, {})
    assert not result.is_error
    assert fake.requests[-1] == f"({function} 200 0)"


async def test_limit_above_the_maximum_is_clamped(started, fake):
    await started.call_tool("bricscad_list_layers", {"limit": 99999, "offset": -1})
    assert fake.requests[-1] == "(mcp:list-layers 2000 0)"


async def test_list_blocks_hides_anonymous_by_default(started, fake):
    await started.call_tool("bricscad_list_blocks", {})
    assert fake.requests[-1] == "(mcp:list-blocks nil 200 0)"
    await started.call_tool("bricscad_list_blocks", {"include_anonymous": True})
    assert fake.requests[-1] == "(mcp:list-blocks T 200 0)"


async def test_query_passes_every_filter(started, fake):
    await started.call_tool(
        "bricscad_query_entities",
        {"types": ["LINE", "CIRCLE"], "layer": 'A"B', "block": "B", "bbox": [0, 1, 2, 3],
         "layout": "Layout1", "limit": 10, "offset": 20},
    )
    assert fake.requests[-1] == (
        '(mcp:query-entities "LINE,CIRCLE" "A\\"B" "B" (list 0.0 1.0 2.0 3.0) "Layout1" 10 20)'
    )


async def test_query_with_no_filters(started, fake):
    await started.call_tool("bricscad_query_entities", {})
    assert fake.requests[-1] == "(mcp:query-entities nil nil nil nil nil 200 0)"


@pytest.mark.parametrize(
    "bbox", [[0, 0, 1], [0, 0, 1, 1, 1], [5, 0, 1, 1], [0, 5, 1, 1]],
)
async def test_bad_bbox_is_refused_before_bricscad(started, fake, bbox):
    result = await started.call_tool("bricscad_query_entities", {"bbox": bbox})
    assert result.is_error and "bbox" in result.content[0].text
    assert fake.requests == []


async def test_get_entity_passes_the_handle_as_a_string(started, fake):
    result = await started.call_tool("bricscad_get_entity", {"handle": '1A") (startapp "x'})
    assert not result.is_error
    assert fake.requests[-1] == '(mcp:get-entity "1A\\") (startapp \\"x")'


async def test_read_attributes_passes_filters(started, fake):
    await started.call_tool("bricscad_read_attributes", {"block": "TB", "layout": "L"})
    assert fake.requests[-1] == '(mcp:read-attributes "TB" "L" 200 0)'


async def test_find_text_defaults_to_case_insensitive(started, fake):
    await started.call_tool("bricscad_find_text", {"query": "načrt"})
    assert fake.requests[-1] == '(mcp:find-text "načrt" nil 200 0)'


async def test_find_text_refuses_an_empty_query(started, fake):
    result = await started.call_tool("bricscad_find_text", {"query": ""})
    assert result.is_error and fake.requests == []


async def test_read_tools_are_read_only(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in (
        "bricscad_list_layers", "bricscad_list_blocks", "bricscad_list_xrefs", "bricscad_list_layouts",
        "bricscad_query_entities", "bricscad_get_entity", "bricscad_read_attributes", "bricscad_find_text",
    ):
        assert tools[name].annotations.read_only_hint is True
