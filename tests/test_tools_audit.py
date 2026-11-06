import pytest

pytestmark = pytest.mark.anyio

REPORT = {
    "empty_layers": {"count": 0, "items": []},
    "unused_blocks": {"count": 0, "items": []},
    "missing_xrefs": {"count": 0, "items": []},
    "non_zero_elevation": {"count": 0, "items": []},
    "off_standard_layers": None,
}


@pytest.fixture
async def started(client, fake):
    fake.responses["mcp:audit-report"] = REPORT
    await client.call_tool("bricscad_start", {})
    fake.requests.clear()
    return client


async def test_audit_defaults(started, fake):
    result = await started.call_tool("bricscad_audit_report", {})
    assert not result.is_error and result.structured_content["off_standard_layers"] is None
    assert fake.requests[-1] == "(mcp:audit-report nil 50)"


async def test_audit_passes_allowed_layers(started, fake):
    await started.call_tool("bricscad_audit_report", {"allowed_layers": ["A-*", 'B"C'], "sample_limit": 5})
    assert fake.requests[-1] == '(mcp:audit-report (list "A-*" "B\\"C") 5)'


async def test_an_empty_allowed_list_is_refused(started, fake):
    result = await started.call_tool("bricscad_audit_report", {"allowed_layers": []})
    assert result.is_error and "allowed_layers" in result.content[0].text
    assert fake.requests == []


async def test_sample_limit_is_clamped(started, fake):
    await started.call_tool("bricscad_audit_report", {"sample_limit": 999999})
    assert fake.requests[-1] == "(mcp:audit-report nil 2000)"


async def test_audit_is_read_only(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert tools["bricscad_audit_report"].annotations.read_only_hint is True
