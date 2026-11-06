import pytest

from bricscad_mcp.errors import SafetyRefused
from bricscad_mcp.lispgen import call, lisp_path
from bricscad_mcp.tools.drawing import close_drawing, drawing_info, open_drawing
from real.helpers import add_line, make_dwg

pytestmark = pytest.mark.bricscad


def test_open_read_only_leaves_the_file_unchanged(real_session, tmp_path):
    path = make_dwg(real_session, tmp_path / "sample.dwg", lines=2)
    before = path.read_bytes()
    info = open_drawing(real_session.bridge, str(path))
    assert info["read_only"] is True and info["entity_count"] == 2
    add_line(real_session)
    close_drawing(real_session.bridge, discard=True)
    assert path.read_bytes() == before


def test_open_read_write_is_reported(real_session, tmp_path):
    path = make_dwg(real_session, tmp_path / "rw.dwg")
    info = open_drawing(real_session.bridge, str(path), read_only=False)
    assert info["read_only"] is False and info["modified"] is False
    close_drawing(real_session.bridge)


def test_open_path_with_slovene_characters_and_spaces(real_session, tmp_path):
    path = make_dwg(real_session, tmp_path / "Načrt št 1.dwg")
    assert open_drawing(real_session.bridge, str(path))["name"] == "Načrt št 1.dwg"
    close_drawing(real_session.bridge)


def test_open_path_with_a_quote(real_session, tmp_path):
    path = make_dwg(real_session, tmp_path / 'a"b.dwg')
    assert open_drawing(real_session.bridge, str(path))["name"] == 'a"b.dwg'
    close_drawing(real_session.bridge)


def test_listener_answers_after_open_and_close(real_session, tmp_path):
    path = make_dwg(real_session, tmp_path / "s.dwg")
    open_drawing(real_session.bridge, str(path))
    close_drawing(real_session.bridge)
    assert real_session.bridge.send("(+ 1 1)") == 2


def test_closing_the_last_drawing_keeps_the_listener(own_session, tmp_path):
    bridge = own_session.bridge
    assert bridge.send("(vla-get-count (mcp:documents))") == 1
    close_drawing(bridge, discard=True)
    assert bridge.send("(vla-get-count (mcp:documents))") == 1
    assert bridge.send("(+ 1 1)") == 2


def test_info_reports_modified_extents_and_layouts(real_session, tmp_path):
    path = make_dwg(real_session, tmp_path / "info.dwg")
    open_drawing(real_session.bridge, str(path), read_only=False)
    add_line(real_session)
    info = drawing_info(real_session.bridge)
    assert info["modified"] is True and info["path"].endswith("info.dwg")
    assert info["layouts"][0] == "Model" and len(info["layouts"]) >= 2
    assert isinstance(info["units"], int) and len(info["extents"]) == 2
    with pytest.raises(SafetyRefused, match="discard=true"):
        close_drawing(real_session.bridge)
    close_drawing(real_session.bridge, discard=True)


def test_unsaved_count_is_zero_for_a_new_session(own_session):
    assert own_session.bridge.send(call("mcp:unsaved-count")) == 0


def test_open_a_real_dxf(real_session, tmp_path, blank):
    bridge = real_session.bridge
    path = tmp_path / "exported.dxf"
    add_line(real_session)
    bridge.send(f'(command "_.SAVEAS" "DXF" "" {lisp_path(path)})')
    assert path.stat().st_size > 0
    info = open_drawing(bridge, str(path))
    assert info["entity_count"] == 1
    close_drawing(bridge, discard=True)


def test_opening_a_file_that_is_already_open_does_not_block(real_session, tmp_path):
    path = make_dwg(real_session, tmp_path / "twice.dwg")
    open_drawing(real_session.bridge, str(path))
    assert open_drawing(real_session.bridge, str(path))["name"] == "twice.dwg"
    close_drawing(real_session.bridge)
    if real_session.bridge.send('(getvar "DWGNAME")') == "twice.dwg":
        close_drawing(real_session.bridge)
    assert real_session.bridge.send("(+ 1 1)") == 2
