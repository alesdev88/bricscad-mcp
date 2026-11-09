import pytest

from bricscad_mcp.errors import LispError
from bricscad_mcp.tools import edit

pytestmark = pytest.mark.bricscad


def layer_exists(session, name):
    return session.bridge.send(f'(if (tblsearch "LAYER" "{name}") 1 0)') == 1


def test_creates_a_layer_with_properties(real_session, blank):
    result = edit.set_layer(real_session.bridge, "Načrt A", color=3, locked=True)
    assert result["created"] is True
    assert (result["layer"]["name"], result["layer"]["color"], result["layer"]["locked"]) == ("Načrt A", 3, True)


def test_changes_an_existing_layer_whatever_the_case(real_session, blank):
    edit.set_layer(real_session.bridge, "Plan")
    result = edit.set_layer(real_session.bridge, "PLAN", on=False, frozen=True)
    assert result["created"] is False and result["layer"]["name"] == "Plan"
    assert result["layer"]["on"] is False and result["layer"]["frozen"] is True


def test_false_turns_a_lock_off(real_session, blank):
    edit.set_layer(real_session.bridge, "A", locked=True)
    assert edit.set_layer(real_session.bridge, "A", locked=False)["layer"]["locked"] is False


def test_loads_a_linetype_from_iso_lin(real_session, blank):
    assert edit.set_layer(real_session.bridge, "A", linetype="CENTER")["layer"]["linetype"] == "CENTER"


def test_an_unknown_linetype_fails_and_makes_nothing(real_session, blank):
    with pytest.raises(LispError, match="NOPE.*iso.lin"):
        edit.set_layer(real_session.bridge, "A", color=5, linetype="NOPE")
    assert not layer_exists(real_session, "A")


def test_cannot_freeze_the_current_layer(real_session, blank):
    with pytest.raises(LispError, match="current layer"):
        edit.set_layer(real_session.bridge, "0", frozen=True)
    assert real_session.bridge.send('(logand 1 (cdr (assoc 70 (tblsearch "LAYER" "0"))))') == 0


def test_renames_a_layer(real_session, blank):
    edit.set_layer(real_session.bridge, "Old")
    assert edit.set_layer(real_session.bridge, "Old", new_name="New")["layer"]["name"] == "New"
    assert not layer_exists(real_session, "Old")


def test_rename_onto_an_existing_name_is_refused(real_session, blank):
    edit.set_layer(real_session.bridge, "A")
    edit.set_layer(real_session.bridge, "B")
    with pytest.raises(LispError, match="already"):
        edit.set_layer(real_session.bridge, "A", new_name="B")


@pytest.mark.parametrize("name", ["0", "defpoints"])
def test_special_layers_cannot_be_renamed(real_session, blank, name):
    edit.set_layer(real_session.bridge, name)
    with pytest.raises(LispError, match="cannot be renamed"):
        edit.set_layer(real_session.bridge, name, new_name="Other")


def test_undo_removes_a_new_layer(real_session, blank):
    edit.set_layer(real_session.bridge, "A")
    edit.undo(real_session.bridge)
    assert not layer_exists(real_session, "A")
