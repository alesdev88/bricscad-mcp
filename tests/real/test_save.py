import hashlib

import pytest

from bricscad_mcp.errors import LispError, SafetyRefused
from bricscad_mcp.lispgen import call
from bricscad_mcp.tools import edit
from bricscad_mcp.tools.drawing import close_drawing, open_drawing
from real.helpers import entity_count, line_at, make_dwg

pytestmark = pytest.mark.bricscad

LINE = {"type": "line", "start": [0, 0], "end": [1, 1]}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_save_as_writes_the_file_and_adopts_it(real_session, blank, tmp_path):
    line_at(real_session, 0, 0)
    target = tmp_path / "Načrt št 1.dwg"
    info = edit.save_drawing(real_session.bridge, str(target))
    assert target.exists() and info["name"] == target.name and info["modified"] is False


def test_read_only_source_is_untouched_by_saving_a_copy(real_session, tmp_path):  # no blank: make_dwg saves and closes the current drawing
    source = make_dwg(real_session, tmp_path / "a.dwg")
    before = digest(source)
    open_drawing(real_session.bridge, str(source))
    line_at(real_session, 2, 2)
    info = edit.save_drawing(real_session.bridge, str(tmp_path / "b.dwg"))
    close_drawing(real_session.bridge)
    assert info["read_only"] is False and digest(source) == before and (tmp_path / "b.dwg").exists()


def test_saving_in_place_needs_overwrite_and_then_works(real_session, blank, tmp_path):
    target = tmp_path / "a.dwg"
    edit.save_drawing(real_session.bridge, str(target))
    before = digest(target)
    line_at(real_session, 0, 0)
    with pytest.raises(SafetyRefused, match="overwrite"):
        edit.save_drawing(real_session.bridge)
    assert digest(target) == before
    assert edit.save_drawing(real_session.bridge, overwrite=True)["modified"] is False
    assert digest(target) != before


def test_overwrite_replaces_another_file(real_session, blank, tmp_path):
    target = tmp_path / "a.dwg"
    target.write_bytes(b"AC1032 placeholder")
    size = target.stat().st_size
    line_at(real_session, 0, 0)
    edit.save_drawing(real_session.bridge, str(target), overwrite=True)
    assert target.stat().st_size != size and real_session.bridge.send('(getvar "CMDACTIVE")') == 0


def test_lisp_refuses_a_file_that_appeared_after_the_check(real_session, blank, tmp_path):
    target = tmp_path / "late.dwg"
    target.write_bytes(b"AC1032 placeholder")
    size = target.stat().st_size
    with pytest.raises(LispError, match="exists"):
        real_session.bridge.send(call("mcp:save-as", target.as_posix(), False))
    assert target.stat().st_size == size and real_session.bridge.send('(getvar "CMDACTIVE")') == 0


def test_lisp_reports_a_save_that_did_not_happen(real_session, blank, tmp_path):
    with pytest.raises(LispError, match="did not save"):
        real_session.bridge.send(call("mcp:save-as", (tmp_path / "missing" / "x.dwg").as_posix(), False))


def test_saving_onto_a_drawing_open_in_this_session_is_refused(real_session, blank, tmp_path):
    held = tmp_path / "held.dwg"
    edit.save_drawing(real_session.bridge, str(held))
    real_session.bridge.send('(progn (vla-activate (vla-add (mcp:documents))) (getvar "DWGNAME"))')
    before = digest(held)
    with pytest.raises(SafetyRefused, match="open"):
        edit.save_drawing(real_session.bridge, str(held), overwrite=True)
    real_session.bridge.send(call("mcp:close-drawing"))
    assert digest(held) == before


def test_undo_still_works_after_a_save(real_session, blank, tmp_path):
    edit.create_entities(real_session.bridge, [LINE])
    edit.save_drawing(real_session.bridge, str(tmp_path / "a.dwg"))
    assert edit.undo(real_session.bridge)["undone"] == 1
    assert entity_count(real_session) == 0
