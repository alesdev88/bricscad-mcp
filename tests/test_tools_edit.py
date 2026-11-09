import pytest

from bricscad_mcp.errors import BricsCADError
from bricscad_mcp.tools import edit

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


async def test_set_layer_sends_switches_as_nil_0_or_1(started, fake):
    fake.responses["mcp:set-layer"] = {"layer": {}, "created": True}
    await started.call_tool("bricscad_set_layer", {"name": "A", "color": 3, "on": False, "locked": True})
    assert fake.requests[-1] == '(mcp:set-layer "A" nil 3 nil 0 nil 1)'


@pytest.mark.parametrize("name", ["", *'<>/\\":;?*|,=`'])
async def test_set_layer_refuses_bad_names(started, fake, name):
    await refused(started, fake, "bricscad_set_layer", {"name": f"a{name}b" if name else ""})


async def test_set_layer_refuses_a_bad_new_name(started, fake):
    await refused(started, fake, "bricscad_set_layer", {"name": "A", "new_name": "a*b"})


@pytest.mark.parametrize("color", [0, 256])
async def test_set_layer_refuses_a_bad_color(started, fake, color):
    await refused(started, fake, "bricscad_set_layer", {"name": "A", "color": color})


async def test_modify_sends_rotation_in_radians(started, fake):
    fake.responses["mcp:modify-entities"] = {"modified": 1}
    await started.call_tool(
        "bricscad_modify_entities", {"handles": ["1A"], "rotate": {"angle": 180, "base": [1, 2]}}
    )
    assert fake.requests[-1] == (
        '(mcp:modify-entities (list "1A") nil (list 3.141592653589793 (list 1.0 2.0 0.0)) nil nil nil nil nil)'
    )


async def test_modify_turns_line_breaks_into_mtext_codes(started, fake):
    fake.responses["mcp:modify-entities"] = {"modified": 1}
    await started.call_tool("bricscad_modify_entities", {"handles": ["1A"], "text": "a\nb"})
    assert '"a\\\\Pb"' in fake.requests[-1]


@pytest.mark.parametrize(
    "change",
    [{}, {"scale": {"factor": 0, "base": [0, 0]}}, {"move": [1]}, {"color": -1}, {"color": 257}],
)
async def test_modify_refuses_bad_changes(started, fake, change):
    await refused(started, fake, "bricscad_modify_entities", {"handles": ["1A"], **change})


async def test_set_attributes_sends_tags_and_values(started, fake):
    fake.responses["mcp:set-attributes"] = {"inserts": 1, "attributes": 1}
    await started.call_tool("bricscad_set_attributes", {"updates": [{"handle": "1a", "values": {"T": "v"}}]})
    assert fake.requests[-1] == '(mcp:set-attributes (list (list "1A" (list (list "T" "v")))))'


@pytest.mark.parametrize("updates", [[], [{"handle": "1A", "values": {}}], [{"handle": "x)", "values": {"T": "v"}}]])
async def test_set_attributes_refuses_bad_updates(started, fake, updates):
    await refused(started, fake, "bricscad_set_attributes", {"updates": updates})


LINE = {"type": "line", "start": [0, 0], "end": [5, 5]}


async def test_create_sends_full_points(started, fake):
    fake.responses["mcp:create-entities"] = {"created": [], "count": 0}
    await started.call_tool("bricscad_create_entities", {"entities": [LINE]})
    assert fake.requests[-1] == '(mcp:create-entities nil (list (list "line" "0" (list 0.0 0.0 0.0) (list 5.0 5.0 0.0))))'


@pytest.mark.parametrize(
    "entities",
    [
        [],
        [LINE] * 2001,
        [{"type": "circle", "center": [0, 0], "radius": 0}],
        [{"type": "text", "position": [0, 0], "text": "x", "height": 0}],
        [{"type": "nurb"}],
        [{**LINE, "colour": 3}],
        [{"type": "polyline", "vertices": [[0, 0]]}],
        [{"type": "polyline", "vertices": [[0, 0], [1, 1]], "bulges": [1]}],
        [{"type": "text", "position": [0, 0], "text": "a\nb", "height": 1}],
    ],
)
async def test_create_refuses_bad_items(started, fake, entities):
    await refused(started, fake, "bricscad_create_entities", {"entities": entities})


def test_create_refuses_a_point_that_is_not_finite():
    with pytest.raises(BricsCADError):
        edit.create_entities(None, [{"type": "line", "start": [float("nan"), 0], "end": [1, 1]}])
