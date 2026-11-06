import pytest

from bricscad_mcp.tools import page_args

pytestmark = pytest.mark.anyio


async def test_tools_are_listed_with_annotations(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert tools["bricscad_status"].annotations.read_only_hint is True
    assert tools["bricscad_list_versions"].annotations.read_only_hint is True
    assert tools["bricscad_run_lisp"].annotations.destructive_hint is True
    assert tools["bricscad_stop"].annotations.destructive_hint is True
    assert all(name.startswith("bricscad_") for name in tools)


async def test_status_before_start(client):
    result = await client.call_tool("bricscad_status", {})
    assert result.structured_content["running"] is False


async def test_list_versions(client):
    result = await client.call_tool("bricscad_list_versions", {})
    assert result.structured_content["versions"][0]["version"] == "26"


async def test_start_then_status_then_stop(client, fake):
    started = await client.call_tool("bricscad_start", {})
    assert started.is_error is False and started.structured_content["pid"] == fake.pid
    status = await client.call_tool("bricscad_status", {})
    assert status.structured_content["running"] is True
    stopped = await client.call_tool("bricscad_stop", {})
    assert stopped.structured_content["stopped"] is True


async def test_stop_refusal_reaches_the_client(client, fake):
    fake.unsaved = 2
    await client.call_tool("bricscad_start", {})
    result = await client.call_tool("bricscad_stop", {})
    assert result.is_error and "discard=true" in result.content[0].text
    assert fake.alive


async def test_run_lisp_without_session_gives_guidance(client):
    result = await client.call_tool("bricscad_run_lisp", {"code": "(+ 1 1)"})
    assert result.is_error and "bricscad_start" in result.content[0].text


async def test_run_lisp_returns_the_value(client, fake):
    fake.responses["+"] = 2
    await client.call_tool("bricscad_start", {})
    result = await client.call_tool("bricscad_run_lisp", {"code": "(+ 1 1)"})
    assert result.structured_content["result"] == 2
    assert fake.requests[-1] == "(+ 1 1)"


async def test_run_lisp_error_reaches_the_client(client, fake):
    fake.responses["car"] = ValueError("bad argument type")
    await client.call_tool("bricscad_start", {})
    result = await client.call_tool("bricscad_run_lisp", {"code": "(car 1)"})
    assert result.is_error and "bad argument type" in result.content[0].text


@pytest.mark.parametrize(
    "limit,offset,expected",
    [(99999, -5, (2000, 0)), (0, 3, (1, 3)), (200, 0, (200, 0))],
)
async def test_page_args_clamp(limit, offset, expected):
    assert page_args(limit, offset) == expected
