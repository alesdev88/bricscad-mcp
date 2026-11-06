import time

import pytest

from bricscad_mcp.errors import BricsCADError, LispError, SafetyRefused
from bricscad_mcp.lispgen import call, lisp_path, lisp_value
from bricscad_mcp.platforms import get_platform
from bricscad_mcp.platforms.base import is_alive
from bricscad_mcp.session import Session
from real.helpers import add_line, save_as, wait_until

pytestmark = pytest.mark.bricscad


@pytest.mark.parametrize("text", ['a"b', "a\\b", "line1\nline2", "čšž", "tab\there", ""])
def test_json_round_trips_text(real_session, text):
    assert real_session.bridge.send(lisp_value(text)) == text


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("(+ 1 1)", 2),
        ("1.5", 1.5),
        ("-0.25", -0.25),
        ("nil", None),
        ("T", True),
        ("(list 1 2.5 \"a\" nil T)", [1, 2.5, "a", None, True]),
        ("(cons 1 2)", [1, 2]),
        ('(mcp:obj (list (cons "a" 1) (cons "b" (mcp:arr nil))))', {"a": 1, "b": []}),
        ('(mcp:obj nil)', {}),
        ("(mcp:bool nil)", False),
        ("(mcp:bool T)", True),
        ("(mcp:bool :vlax-false)", False),
        ("(mcp:bool :vlax-true)", True),
    ],
)
def test_json_encodes_values(real_session, expr, expected):
    assert real_session.bridge.send(expr) == expected


def test_a_long_string_survives(real_session):
    assert real_session.bridge.send(lisp_value("č" * 20000)) == "č" * 20000


def test_listener_survives_a_lisp_error(real_session):
    with pytest.raises(LispError):
        real_session.bridge.send("(car 1)")
    assert real_session.bridge.send("(+ 1 1)") == 2


def test_listener_survives_an_unfinished_command(real_session):
    real_session.bridge.send('(command "_.LINE")')
    assert real_session.bridge.send('(getvar "CMDACTIVE")') == 0


def test_listener_survives_a_syntax_error(real_session):
    with pytest.raises(LispError):
        real_session.bridge.send("(+ 1")
    assert real_session.bridge.send("(+ 1 1)") == 2


def test_variable_is_restored_after_an_error_in_a_request(real_session):
    before = real_session.bridge.send('(getvar "OSMODE")')
    changed = 1 if before != 1 else 2
    with pytest.raises(LispError):
        real_session.bridge.send(call("mcp:with-vars", [["OSMODE", changed]], "(car 1)"))
    assert real_session.bridge.send('(getvar "OSMODE")') == before


def test_with_vars_returns_the_result(real_session):
    assert real_session.bridge.send(call("mcp:with-vars", [["OSMODE", 1]], '(getvar "OSMODE")')) == 1


def test_heartbeat_advances(real_session):
    time.sleep(1.5)
    assert real_session.bridge.heartbeat_age() < 2


def test_status_reports_the_drawing(real_session):
    status = real_session.status()
    assert status["running"] is True and status["drawing"].lower().endswith(".dwg")


def test_quiet_server_leaves_a_copy_with_unsaved_work_open(own_session):
    add_line(own_session)
    own_session.bridge.expire_alive_for_test()
    assert wait_until(lambda: own_session.bridge.heartbeat_age() > 3, timeout=15)
    assert is_alive(own_session.pid)


def test_quiet_server_closes_a_copy_with_nothing_to_lose(own_session):
    pid = own_session.pid
    own_session.bridge.expire_alive_for_test()
    assert wait_until(lambda: not is_alive(pid), timeout=20)


def test_a_second_start_refuses_while_this_version_runs(real_session):
    second = Session(get_platform())
    with pytest.raises(BricsCADError, match=str(real_session.pid)):
        second.start()


def test_stop_refuses_unsaved_work_then_discard_leaves_the_file_unchanged(own_session, tmp_path):
    path = tmp_path / "keep me.dwg"
    add_line(own_session)
    save_as(own_session, path)
    before = path.read_bytes()
    add_line(own_session)

    with pytest.raises(SafetyRefused, match="discard=true"):
        own_session.stop()

    pid = own_session.pid
    assert own_session.stop(discard=True)["forced"] is False
    assert not is_alive(pid)
    assert path.read_bytes() == before


def test_discard_with_two_modified_drawings_exits_without_saving(own_session, tmp_path):
    first, second = tmp_path / "first.dwg", tmp_path / "second.dwg"
    add_line(own_session)
    save_as(own_session, first)
    add_line(own_session)
    save_as(own_session, second)
    add_line(own_session)
    own_session.bridge.send(f'(progn (vla-open (mcp:documents) {lisp_path(first)} :vlax-false) (getvar "DWGNAME"))')
    add_line(own_session)
    assert own_session.bridge.send(call("mcp:unsaved-count")) == 2
    sizes = first.read_bytes(), second.read_bytes()

    assert own_session.stop(discard=True)["forced"] is False
    assert (first.read_bytes(), second.read_bytes()) == sizes


def test_clean_stop_needs_no_force(own_session):
    pid = own_session.pid
    assert own_session.stop()["forced"] is False
    assert not is_alive(pid)
