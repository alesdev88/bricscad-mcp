import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture
async def started(client, fake):
    await client.call_tool("bricscad_start", {})
    fake.requests.clear()
    return client


async def refused(client, fake, tool, arguments):
    result = await client.call_tool(tool, arguments)
    assert result.is_error and fake.requests == []
    return result


async def test_undo_sends_steps(started, fake):
    fake.responses["mcp:undo"] = {"undone": 3, "requested": 3}
    await started.call_tool("bricscad_undo", {"steps": 3})
    assert fake.requests[-1] == "(mcp:undo 3)"


@pytest.mark.parametrize("steps", [0, -1, 101])
async def test_undo_refuses_a_bad_step_count(started, fake, steps):
    await refused(started, fake, "bricscad_undo", {"steps": steps})
