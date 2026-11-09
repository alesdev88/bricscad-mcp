import time

import pytest

from bricscad_mcp.errors import LispError
from bricscad_mcp.tools import edit
from real.helpers import entity_count, line_at

pytestmark = pytest.mark.bricscad

LINE = '(entmakex (list (quote (0 . "LINE")) (quote (10 0.0 0.0 0.0)) (quote (11 1.0 1.0 0.0))))'
EDIT_LINE = f"(mcp:edit (function (lambda () {LINE})) nil)"


def test_undo_removes_one_edit_at_a_time(real_session, blank):
    send = real_session.bridge.send
    send(EDIT_LINE)
    send(EDIT_LINE)
    time.sleep(1.5)  # the listener runs _.DELAY meanwhile, which must not count as a step
    assert edit.undo(real_session.bridge) == {"undone": 1, "requested": 1}
    assert entity_count(real_session) == 1


def test_undo_stops_at_the_oldest_step(real_session, blank):
    real_session.bridge.send(EDIT_LINE)
    assert edit.undo(real_session.bridge, steps=5) == {"undone": 1, "requested": 5}


def test_undo_with_no_steps_left_keeps_the_drawing(real_session, blank):
    line_at(real_session, 0, 0)  # made outside mcp:edit, as bricscad_run_lisp would
    assert edit.undo(real_session.bridge)["undone"] == 0
    assert entity_count(real_session) == 1
    assert real_session.bridge.send('(getvar "CMDACTIVE")') == 0


def test_a_failed_edit_changes_nothing_and_keeps_earlier_steps(real_session, blank):
    send = real_session.bridge.send
    send(EDIT_LINE)
    with pytest.raises(LispError, match="Second item is bad."):
        send(f'(mcp:edit (function (lambda () {LINE} (mcp:fail "Second item is bad."))) nil)')
    assert entity_count(real_session) == 1
    assert edit.undo(real_session.bridge)["undone"] == 1
    assert entity_count(real_session) == 0


def test_a_lisp_error_in_an_edit_reports_its_message(real_session, blank):
    with pytest.raises(LispError, match="bad argument"):
        real_session.bridge.send("(mcp:edit (function (lambda () (car 5))) nil)")
