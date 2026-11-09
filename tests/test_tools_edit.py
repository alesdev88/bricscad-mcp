import sys

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
        [{"type": "dimension", "kind": "angular", "start": [0, 0], "end": [1, 0], "line_point": [1, 1]}],
        [{"type": "hatch", "points": [[0, 0], [1, 1]]}],
        [{"type": "hatch", "points": [[0, 0], [1, 0], [1, 1]], "scale": 0}],
        [{"type": "insert", "block": "*U1", "position": [0, 0]}],
    ],
)
async def test_create_refuses_bad_items(started, fake, entities):
    await refused(started, fake, "bricscad_create_entities", {"entities": entities})


def test_create_refuses_a_point_that_is_not_finite():
    with pytest.raises(BricsCADError):
        edit.create_entities(None, [{"type": "line", "start": [float("nan"), 0], "end": [1, 1]}])


SAVED = {"name": "x.dwg"}


def state(path="/nowhere/current.dwg", titled=1, read_only=False, other_open=()):
    return {"path": str(path), "titled": titled, "read_only": read_only, "other_open": [str(p) for p in other_open]}


async def save_refused(client, fake, arguments, match):
    result = await client.call_tool("bricscad_save_drawing", arguments)
    assert result.is_error and match in result.content[0].text
    assert not any("mcp:save-as" in request or "mcp:qsave" in request for request in fake.requests)


async def test_save_an_unnamed_drawing_needs_a_path(started, fake):
    fake.responses["mcp:save-state"] = state(titled=0)
    await save_refused(started, fake, {"overwrite": True}, "path")


async def test_a_read_only_drawing_cannot_be_saved_in_place(started, fake):
    fake.responses["mcp:save-state"] = state(read_only=True)
    await save_refused(started, fake, {"overwrite": True}, "new path")


async def test_saving_in_place_needs_overwrite(started, fake):
    fake.responses["mcp:save-state"] = state()
    await save_refused(started, fake, {}, "overwrite=true")


async def test_saving_in_place_with_overwrite_goes_through(started, fake):
    fake.responses["mcp:save-state"] = state()
    fake.responses["mcp:qsave"] = SAVED
    await started.call_tool("bricscad_save_drawing", {"overwrite": True})
    assert fake.requests[-1] == "(mcp:qsave)"


async def test_only_dwg_files_are_saved(started, fake, tmp_path):
    fake.responses["mcp:save-state"] = state()
    await save_refused(started, fake, {"path": str(tmp_path / "x.dxf")}, "bricscad_export_dxf")


async def test_the_target_cannot_be_a_folder(started, fake, tmp_path):
    fake.responses["mcp:save-state"] = state()
    (tmp_path / "x.dwg").mkdir()
    await save_refused(started, fake, {"path": str(tmp_path / "x.dwg")}, "folder")


async def test_the_target_folder_must_exist(started, fake, tmp_path):
    fake.responses["mcp:save-state"] = state()
    await save_refused(started, fake, {"path": str(tmp_path / "missing" / "x.dwg")}, "folder")


async def test_a_read_only_drawing_cannot_be_saved_over_its_own_file(started, fake, tmp_path):
    current = tmp_path / "a.dwg"
    current.write_bytes(b"AC1032")
    fake.responses["mcp:save-state"] = state(current, read_only=True)
    await save_refused(started, fake, {"path": str(current), "overwrite": True}, "new path")


async def test_a_file_open_as_another_drawing_is_refused(started, fake, tmp_path):
    other = tmp_path / "a.dwg"
    other.write_bytes(b"AC1032")
    fake.responses["mcp:save-state"] = state(other_open=[other])
    await save_refused(started, fake, {"path": str(other), "overwrite": True}, "open as another drawing")


async def test_an_existing_file_needs_overwrite(started, fake, tmp_path):
    target = tmp_path / "a.dwg"
    target.write_bytes(b"AC1032")
    fake.responses["mcp:save-state"] = state()
    await save_refused(started, fake, {"path": str(target)}, "overwrite=true")


@pytest.mark.skipif(sys.platform == "win32", reason="needs POSIX permissions")
async def test_a_file_that_is_not_writable_is_refused(started, fake, tmp_path):
    target = tmp_path / "a.dwg"
    target.write_bytes(b"AC1032")
    target.chmod(0o444)
    fake.responses["mcp:save-state"] = state()
    await save_refused(started, fake, {"path": str(target), "overwrite": True}, "not writable")


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges")
async def test_a_symlink_to_the_read_only_file_is_the_same_file(started, fake, tmp_path):
    real = tmp_path / "a.dwg"
    real.write_bytes(b"AC1032")
    link = tmp_path / "b.dwg"
    link.symlink_to(real)
    fake.responses["mcp:save-state"] = state(real, read_only=True)
    await save_refused(started, fake, {"path": str(link), "overwrite": True}, "new path")


async def test_a_new_file_goes_through(started, fake, tmp_path):
    fake.responses["mcp:save-state"] = state()
    fake.responses["mcp:save-as"] = SAVED
    target = tmp_path / "Načrt 1.dwg"
    await started.call_tool("bricscad_save_drawing", {"path": str(target)})
    assert fake.requests[-1] == f'(mcp:save-as "{target.as_posix()}" nil)'


async def test_overwrite_is_passed_on(started, fake, tmp_path):
    target = tmp_path / "a.dwg"
    target.write_bytes(b"AC1032")
    fake.responses["mcp:save-state"] = state()
    fake.responses["mcp:save-as"] = SAVED
    await started.call_tool("bricscad_save_drawing", {"path": str(target), "overwrite": True})
    assert fake.requests[-1] == f'(mcp:save-as "{target.as_posix()}" T)'
