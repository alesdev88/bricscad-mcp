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


async def test_erase_normalises_handles(started, fake):
    fake.responses["mcp:erase-entities"] = {"erased": 2}
    await started.call_tool("bricscad_erase_entities", {"handles": ["1a", "1A", "2B"]})
    assert fake.requests[-1] == '(mcp:erase-entities (list "1A" "2B"))'


@pytest.mark.parametrize("handles", [[], ["1A) (x"], [format(n, "X") for n in range(2001)]])
async def test_erase_refuses_bad_handles(started, fake, handles):
    await refused(started, fake, "bricscad_erase_entities", {"handles": handles})
