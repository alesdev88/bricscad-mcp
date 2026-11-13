import os
import stat

import pytest

from bricscad_mcp.errors import BricsCADError, BridgeTimeout, NotRunning, ProcessDied, SafetyRefused
from bricscad_mcp.session import Session


def test_start_creates_owner_only_new_queue(session):
    session.start()
    q = session.bridge.queue_dir
    assert q.is_dir()
    if os.name == "posix":
        assert stat.S_IMODE(q.stat().st_mode) == 0o700


def test_each_session_gets_a_new_folder(fake):
    a = Session(fake)
    a.start()
    first = a.bridge.queue_dir
    fake.die()
    a.close()
    fake._stop.clear()
    b = Session(fake)
    b.start()
    assert b.bridge.queue_dir != first
    b.close()


def test_start_returns_what_it_started(session, fake):
    result = session.start()
    assert result["pid"] == fake.pid and result["version"] == "26"


def test_bootstrap_loads_the_lisp_and_starts_the_listener(session, fake):
    session.start()
    text = fake.started_scripts[0].read_text(encoding="utf-8")
    assert "json.lsp" in text and "listener.lsp" in text
    assert text.rstrip().endswith(f'(mcp:listen "{session.bridge.queue_dir.as_posix()}/")')


def test_bootstrap_is_never_seen_as_a_request(session, fake):
    session.start()
    assert fake.started_scripts[0].parent != session.bridge.queue_dir
    assert not any("mcp:listen" in request for request in fake.requests)


@pytest.mark.parametrize(
    "probe, expected",
    [
        ([269, "ANSI_1252"], "utf-8"),  # Unicode LISP, as on macOS
        ([232, "ANSI_1250"], "cp1250"),  # LISP without Unicode, as on Windows
        ([232, "ANSI_1252"], "cp1252"),
        ([63, "ANSI_874"], "cp874"),
        (None, "utf-8"),  # no answer: keep the default
        ([232, "UNKNOWN"], "utf-8"),
    ],
)
def test_start_reads_replies_in_the_lisp_text_encoding(session, fake, probe, expected):
    fake.responses["mcp:text-encoding"] = probe
    session.start()
    assert session.bridge.reply_encoding == expected
    assert fake.requests == ["(mcp:text-encoding)"]


def test_start_keeps_utf8_when_the_encoding_check_fails(session, fake):
    fake.responses["mcp:text-encoding"] = RuntimeError("no such function")
    session.start()
    assert session.bridge.reply_encoding == "utf-8"


def test_second_start_refuses_while_running(session):
    session.start()
    with pytest.raises(BricsCADError, match="already"):
        session.start()


def test_start_works_again_after_the_process_died(session, fake):
    session.start()
    fake.die()
    fake._stop.clear()
    assert session.start()["pid"] == fake.pid


def test_stop_refuses_on_unsaved_changes(session, fake):
    fake.unsaved = 1
    session.start()
    with pytest.raises(SafetyRefused, match="discard=true"):
        session.stop()
    assert fake.alive


def test_stop_with_discard_leaves_a_discard_flag(session, fake):
    fake.unsaved = 1
    session.start()
    queue = session.bridge.queue_dir
    session.stop(discard=True)
    assert (queue / "discard.flag").exists() and (queue / "quit.flag").exists()


def test_stop_is_clean_with_nothing_unsaved(session, fake):
    session.start()
    assert session.stop()["stopped"] is True
    assert fake.terminated == []
    assert session.pid is None


def test_stop_terminates_only_its_own_pid(session, fake):
    session.start()
    fake.ignore_quit = True
    session.stop(discard=True)
    assert fake.terminated == [fake.pid]


def test_stop_refuses_when_it_cannot_check_for_unsaved_work(session, fake):
    session.start()
    fake.close()  # listener no longer answers, but the process is alive
    session.unsaved_check_timeout = 0.1
    with pytest.raises(SafetyRefused, match="discard=true"):
        session.stop()


def test_stop_when_never_started_is_a_clear_error(session):
    with pytest.raises(NotRunning, match="bricscad_start"):
        session.stop()


def test_require_bridge_when_not_started(session):
    with pytest.raises(NotRunning, match="bricscad_start"):
        session.require_bridge()


def test_process_exit_is_reported(session, fake):
    session.start()
    fake.die()
    with pytest.raises(ProcessDied):
        session.require_bridge()


def test_start_times_out_with_guidance(session, fake):
    fake.never_ready = True
    with pytest.raises(BridgeTimeout, match="dialog"):
        session.start(timeout=0.3)


def test_failed_start_closes_the_copy_it_started(session, fake):
    fake.never_ready = True
    with pytest.raises(BridgeTimeout):
        session.start(timeout=0.1)
    assert fake.terminated == [fake.pid]
    assert session.pid is None


def test_start_refuses_when_that_version_is_already_running(session, fake):
    fake.other_pids = {555}
    with pytest.raises(BricsCADError, match="555"):
        session.start()
    assert fake.started_scripts == []
    assert fake.terminated == []


def test_status_before_start(session):
    assert session.status() == {
        "running": False, "pid": None, "version": None, "heartbeat_age": None, "drawing": None,
    }


def test_status_while_running(session, fake):
    fake.drawing = "Načrt.dwg"
    session.start()
    status = session.status()
    assert status["running"] is True and status["pid"] == fake.pid
    assert status["drawing"] == "Načrt.dwg" and status["heartbeat_age"] is not None


def test_status_after_the_process_died(session, fake):
    session.start()
    fake.die()
    assert session.status()["running"] is False


def test_status_when_the_listener_is_stuck_still_answers(session, fake):
    session.start()
    fake.close()
    session.status_timeout = 0.1
    status = session.status()
    assert status["running"] is True and status["drawing"] is None


def test_alive_file_exists_before_launch_and_is_refreshed(session, fake):
    session.alive_interval_seconds = 0.05
    session.start()
    alive = session.bridge.queue_dir / "server.alive"
    assert alive.exists()
    os.utime(alive, (1, 1))
    import time

    deadline = time.monotonic() + 3
    while alive.stat().st_mtime == 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert alive.stat().st_mtime != 1


def test_close_asks_the_listener_to_stop(session, fake):
    session.start()
    queue = session.bridge.queue_dir
    session.close()
    assert (queue / "quit.flag").exists()


def test_old_session_folders_are_removed_on_start(fake):
    old = fake.state_dir() / "sessions" / "old"
    old.mkdir(parents=True)
    (old / "pid").write_text("99999999", encoding="utf-8")
    s = Session(fake)
    s.start()
    assert not old.exists()
    s.close()


def test_folder_of_a_live_process_is_kept(fake, monkeypatch):
    live = fake.state_dir() / "sessions" / "live"
    live.mkdir(parents=True)
    (live / "pid").write_text("777", encoding="utf-8")
    monkeypatch.setattr("bricscad_mcp.session.is_alive", lambda pid: pid in (777, fake.pid) and fake.alive or pid == 777)
    s = Session(fake)
    s.start()
    assert live.exists()
    s.close()
