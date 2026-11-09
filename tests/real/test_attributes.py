import pytest

from bricscad_mcp.errors import LispError
from bricscad_mcp.tools import edit, read
from real.helpers import add_dynamic_block, line_at, make_block_with_attributes

pytestmark = pytest.mark.bricscad


def attrs(session):
    return read.read_attributes(session.bridge)["items"][0]


@pytest.mark.parametrize("value", ['a"b', "a\\b", "Načrt št. 1"])
def test_sets_a_value_exactly(real_session, blank, value):
    make_block_with_attributes(real_session, "TB", {"NASLOV": "old", "ST": "1"})
    result = edit.set_attributes(real_session.bridge, [{"handle": attrs(real_session)["handle"], "values": {"NASLOV": value}}])
    assert result == {"inserts": 1, "attributes": 1}
    assert attrs(real_session)["attributes"] == {"NASLOV": value, "ST": "1"}


def test_tags_match_whatever_the_case(real_session, blank):
    make_block_with_attributes(real_session, "TB", {"NASLOV": "old"})
    edit.set_attributes(real_session.bridge, [{"handle": attrs(real_session)["handle"], "values": {"naslov": "new"}}])
    assert attrs(real_session)["attributes"]["NASLOV"] == "new"


def test_an_unknown_tag_changes_nothing_and_lists_the_tags(real_session, blank):
    make_block_with_attributes(real_session, "TB", {"NASLOV": "old"})
    updates = [{"handle": attrs(real_session)["handle"], "values": {"NASLOV": "new", "NOPE": "x"}}]
    with pytest.raises(LispError, match="NOPE.*NASLOV"):
        edit.set_attributes(real_session.bridge, updates)
    assert attrs(real_session)["attributes"]["NASLOV"] == "old"


def test_a_handle_that_is_not_an_insert_is_refused(real_session, blank):
    updates = [{"handle": line_at(real_session, 0, 0), "values": {"A": "x"}}]
    with pytest.raises(LispError, match="not a block insert"):
        edit.set_attributes(real_session.bridge, updates)


def test_sets_attributes_on_a_dynamic_block(real_session, dxf_drawing):
    add_dynamic_block(dxf_drawing, "Glava", {"A": "old"})
    dxf_drawing.open_in_bricscad()
    handle = read.read_attributes(real_session.bridge, block="Glava")["items"][0]["handle"]
    edit.set_attributes(real_session.bridge, [{"handle": handle, "values": {"A": "new"}}])
    assert read.read_attributes(real_session.bridge, block="Glava")["items"][0]["attributes"] == {"A": "new"}


def test_set_attributes_is_one_undo_step(real_session, blank):
    make_block_with_attributes(real_session, "TB", {"A": "old a", "B": "old b"})
    handle = attrs(real_session)["handle"]
    edit.set_attributes(real_session.bridge, [{"handle": handle, "values": {"A": "new", "B": "new"}}])
    assert edit.undo(real_session.bridge)["undone"] == 1
    assert attrs(real_session)["attributes"] == {"A": "old a", "B": "old b"}
