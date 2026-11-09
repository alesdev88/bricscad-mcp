import pytest

from bricscad_mcp.errors import LispError
from bricscad_mcp.tools import edit, read
from real.helpers import entity_count, line_at, locked_line, make_block_with_attributes

pytestmark = pytest.mark.bricscad


def test_erase_removes_entities(real_session, blank):
    handles = [line_at(real_session, 0, 0), line_at(real_session, 2, 2)]
    assert edit.erase_entities(real_session.bridge, handles) == {"erased": 2}
    assert entity_count(real_session) == 0


def test_erasing_twice_fails_and_does_not_restore(real_session, blank):
    handle = line_at(real_session, 0, 0)
    edit.erase_entities(real_session.bridge, [handle])
    with pytest.raises(LispError, match=handle):
        edit.erase_entities(real_session.bridge, [handle])
    assert entity_count(real_session) == 0


def test_an_unknown_handle_refuses_the_whole_request(real_session, blank):
    good = line_at(real_session, 0, 0)
    with pytest.raises(LispError, match="FFFFFF"):
        edit.erase_entities(real_session.bridge, [good, "FFFFFF"])
    assert entity_count(real_session) == 1


def test_erase_refuses_a_locked_layer(real_session, blank):
    handle = locked_line(real_session)
    with pytest.raises(LispError, match="LK.*locked"):
        edit.erase_entities(real_session.bridge, [handle])
    assert entity_count(real_session) == 1


def test_erase_refuses_an_attribute(real_session, blank):
    make_block_with_attributes(real_session, "TB", {"A": "x"})
    attribute = read.find_text(real_session.bridge, "x")["items"][0]["handle"]
    with pytest.raises(LispError, match="bricscad_set_attributes"):
        edit.erase_entities(real_session.bridge, [attribute])


def test_erase_is_one_undo_step(real_session, blank):
    handles = [line_at(real_session, 0, 0), line_at(real_session, 2, 2)]
    edit.erase_entities(real_session.bridge, handles)
    assert edit.undo(real_session.bridge)["undone"] == 1
    assert entity_count(real_session) == 2
