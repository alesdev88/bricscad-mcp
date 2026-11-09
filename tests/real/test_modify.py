import pytest
from ezdxf.math import Vec2
from ezdxf.render import mleader

from bricscad_mcp.errors import LispError
from bricscad_mcp.tools import edit, read
from real.helpers import circle_at, dxf_value, line_at, locked_line, make_block_with_attributes, text_at

pytestmark = pytest.mark.bricscad


def test_move_shifts_an_entity(real_session, blank):
    handle = line_at(real_session, 0, 0)
    assert edit.modify_entities(real_session.bridge, [handle], move=[5, 7]) == {"modified": 1}
    assert dxf_value(real_session, handle, 10) == [5.0, 7.0, 0.0]


def test_move_carries_attributes(real_session, blank):
    make_block_with_attributes(real_session, "TB", {"A": "x"})
    insert = read.read_attributes(real_session.bridge)["items"][0]["handle"]
    edit.modify_entities(real_session.bridge, [insert], move=[5, 0])
    position = read.find_text(real_session.bridge, "x")["items"][0]["position"]
    assert position[0] == pytest.approx(5.0)


def test_rotate_takes_degrees(real_session, blank):
    handle = circle_at(real_session, 5, 0, radius=1)
    edit.modify_entities(real_session.bridge, [handle], rotate={"angle": 90, "base": [0, 0]})
    assert dxf_value(real_session, handle, 10) == pytest.approx([0.0, 5.0, 0.0], abs=1e-9)


def test_scale_works_about_its_base(real_session, blank):
    handle = circle_at(real_session, 5, 5, radius=2)
    edit.modify_entities(real_session.bridge, [handle], scale={"factor": 2, "base": [0, 0]})
    assert dxf_value(real_session, handle, 10) == pytest.approx([10.0, 10.0, 0.0])
    assert dxf_value(real_session, handle, 40) == pytest.approx(4.0)


def test_sets_layer_and_color(real_session, blank):
    edit.set_layer(real_session.bridge, "A")
    handle = line_at(real_session, 0, 0)
    edit.modify_entities(real_session.bridge, [handle], layer="A", color=3)
    assert dxf_value(real_session, handle, 8) == "A" and dxf_value(real_session, handle, 62) == 3


def test_a_missing_layer_is_refused_and_not_created(real_session, blank):
    handle = line_at(real_session, 0, 0)
    with pytest.raises(LispError, match="Nope.*does not exist"):
        edit.modify_entities(real_session.bridge, [handle], layer="Nope")
    assert real_session.bridge.send('(if (tblsearch "LAYER" "Nope") 1 0)') == 0


@pytest.mark.parametrize("stored", ['a"b', "a\\b", "Načrt"])
def test_changes_text_exactly(real_session, blank, stored):
    handle = text_at(real_session, 0, 0, "old")
    edit.modify_entities(real_session.bridge, [handle], text=stored)
    page = read.find_text(real_session.bridge, stored)
    assert page["total"] == 1 and page["items"][0]["text"] == stored


def test_changes_mtext_and_multileader_text(real_session, dxf_drawing):
    modelspace = dxf_drawing.modelspace()
    modelspace.add_mtext("old one")
    builder = modelspace.add_multileader_mtext("Standard")
    builder.set_content("old two")
    builder.add_leader_line(mleader.ConnectionSide.left, [Vec2(-5, 5)])
    builder.build(insert=Vec2(5, 5))
    dxf_drawing.open_in_bricscad()
    handles = [item["handle"] for item in read.find_text(real_session.bridge, "old")["items"]]
    edit.modify_entities(real_session.bridge, handles, text="changed")
    assert {item["type"] for item in read.find_text(real_session.bridge, "changed")["items"]} == {"MTEXT", "MULTILEADER"}


def test_a_line_break_is_refused_on_single_line_text(real_session, blank):
    handle = text_at(real_session, 0, 0, "old")
    with pytest.raises(LispError, match="one line"):
        edit.modify_entities(real_session.bridge, [handle], text="a\nb")


def test_text_is_refused_on_an_entity_without_text(real_session, blank):
    with pytest.raises(LispError, match="LINE.*no text"):
        edit.modify_entities(real_session.bridge, [line_at(real_session, 0, 0)], text="x")


def test_a_locked_layer_is_refused_even_for_a_move(real_session, blank):  # vla-move ignores the lock
    handle = locked_line(real_session)
    with pytest.raises(LispError, match="locked"):
        edit.modify_entities(real_session.bridge, [handle], move=[5, 0])
    assert dxf_value(real_session, handle, 10) == [0.0, 0.0, 0.0]


def test_a_failure_part_way_changes_nothing(real_session, blank):
    text = text_at(real_session, 0, 0, "old")
    line = line_at(real_session, 0, 0)
    with pytest.raises(LispError):
        edit.modify_entities(real_session.bridge, [text, line], text="new")
    assert dxf_value(real_session, text, 1) == "old"


def test_modify_is_one_undo_step(real_session, blank):
    edit.set_layer(real_session.bridge, "A")
    handle = line_at(real_session, 0, 0)
    edit.modify_entities(real_session.bridge, [handle], layer="A", move=[3, 0])
    assert edit.undo(real_session.bridge)["undone"] == 1
    assert dxf_value(real_session, handle, 8) == "0" and dxf_value(real_session, handle, 10) == [0.0, 0.0, 0.0]
