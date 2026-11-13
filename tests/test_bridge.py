import threading
import time
from pathlib import Path

import pytest

from bricscad_mcp.bridge import Bridge
from bricscad_mcp.errors import BridgeTimeout, LispError, ProcessDied
from fake_listener import FakeListener


@pytest.fixture
def queue(tmp_path):
    return tmp_path


def test_round_trip(queue):
    with FakeListener(queue, lambda e: {"ok": True, "result": {"echo": e}}):
        assert Bridge(queue).send("(+ 1 1)") == {"echo": "(+ 1 1)"}


def test_files_are_removed_after_reply(queue):
    with FakeListener(queue, lambda e: {"ok": True, "result": 1}):
        Bridge(queue).send("x")
    assert list(queue.glob("*.lsp")) == [] and list(queue.glob("*.json")) == []


def test_lisp_error_is_raised(queue):
    with FakeListener(queue, lambda e: {"ok": False, "error": "bad"}):
        with pytest.raises(LispError, match="bad"):
            Bridge(queue).send("x")


def test_unreadable_reply_is_a_lisp_error(queue):
    b = Bridge(queue)

    def write_garbage():
        while not list(queue.glob("*.lsp")):
            time.sleep(0.005)
        request = next(queue.glob("*.lsp"))
        request.with_suffix(".json").write_text("not json", encoding="utf-8")

    threading.Thread(target=write_garbage, daemon=True).start()
    with pytest.raises(LispError, match="unreadable"):
        b.send("x", timeout=5)


def test_timeout_mentions_dialog_and_removes_unclaimed_request(queue):
    with pytest.raises(BridgeTimeout, match="dialog"):
        Bridge(queue).send("x", timeout=0.2)
    assert list(queue.glob("*.lsp")) == []


def test_timeout_says_a_started_request_keeps_running(queue):
    with pytest.raises(BridgeTimeout, match="keeps running"):
        Bridge(queue).send("x", timeout=0.1)


def test_timeout_reports_the_heartbeat_age(queue):
    (queue / "heartbeat").write_text("beat", encoding="utf-8")
    with pytest.raises(BridgeTimeout, match=r"[Ll]ast heartbeat \d"):
        Bridge(queue).send("x", timeout=0.1)


def test_process_death_fails_fast(queue):
    start = time.monotonic()
    with pytest.raises(ProcessDied, match="bricscad_start"):
        Bridge(queue, alive_check=lambda: False).send("x", timeout=30)
    assert time.monotonic() - start < 2
    assert list(queue.glob("*.lsp")) == []


def test_process_death_during_a_request_fails_fast(queue):
    alive = [True]
    b = Bridge(queue, alive_check=lambda: alive[0])
    threading.Timer(0.1, lambda: alive.__setitem__(0, False)).start()
    start = time.monotonic()
    with pytest.raises(ProcessDied):
        b.send("x", timeout=30)
    assert time.monotonic() - start < 2


def test_late_reply_to_a_timed_out_request_is_discarded(queue):
    b = Bridge(queue)
    with pytest.raises(BridgeTimeout):
        b.send("first", timeout=0.1)
    (queue / "stale-id.json").write_text('{"id":"stale-id","ok":true,"result":1}', encoding="utf-8")
    with FakeListener(queue, lambda e: {"ok": True, "result": 2}):
        assert b.send("second") == 2
    assert not (queue / "stale-id.json").exists()


def test_reply_with_another_id_is_refused(queue):
    b = Bridge(queue)
    with FakeListener(queue, lambda e: {"id": "someone-else", "ok": True, "result": 1}):
        with pytest.raises(LispError, match="unreadable"):
            b.send("x", timeout=5)


def test_request_file_is_never_seen_partial(queue):
    big = "x" * 100000
    with FakeListener(queue, lambda e: {"ok": e == big, "result": 1, "error": "partial"}):
        assert Bridge(queue).send(big) == 1


def test_non_ascii_round_trip(queue):
    with FakeListener(queue, lambda e: {"ok": True, "result": e}):
        assert Bridge(queue).send("Načrt čšž") == "Načrt čšž"


def test_reply_in_the_lisp_code_page_is_decoded(queue):
    # LISP without Unicode support, as on Windows, writes replies in its own code page.
    b = Bridge(queue)
    b.reply_encoding = "cp1250"
    with FakeListener(queue, lambda e: {"ok": True, "result": e}, encoding="cp1250"):
        assert b.send("Načrt čšž") == "Načrt čšž"


def test_a_locked_reply_is_read_once_it_is_released(queue, monkeypatch):
    # On Windows a new reply can stay locked for a moment, for example by a virus scanner.
    real_read_text = Path.read_text
    refusals = [3]

    def read_text(self, *args, **kwargs):
        if self.suffix == ".json" and refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    with FakeListener(queue, lambda e: {"ok": True, "result": 7}):
        assert Bridge(queue).send("x", timeout=5) == 7
    assert refusals == [0]


def test_a_reply_that_stays_locked_times_out(queue, monkeypatch):
    real_read_text = Path.read_text

    def read_text(self, *args, **kwargs):
        if self.suffix == ".json":
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    with FakeListener(queue, lambda e: {"ok": True, "result": 7}):
        with pytest.raises(BridgeTimeout):
            Bridge(queue).send("x", timeout=0.3)


def test_a_reply_that_cannot_be_deleted_yet_is_still_returned(queue, monkeypatch):
    real_unlink = Path.unlink
    refused = []

    def unlink(self, *args, **kwargs):
        if self.suffix == ".json" and not refused:
            refused.append(self.name)
            raise PermissionError(13, "Permission denied", str(self))
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    b = Bridge(queue)
    with FakeListener(queue, lambda e: {"ok": True, "result": e}):
        assert b.send("first") == "first"
        assert b.send("second") == "second"
    assert refused and list(queue.glob("*.json")) == []


def test_requests_sort_oldest_first(queue):
    names = []

    def capture():
        while len(names) < 2:
            for p in sorted(queue.glob("*.lsp")):
                if p.name not in names:
                    names.append(p.name)
            time.sleep(0.001)

    t = threading.Thread(target=capture, daemon=True)
    t.start()
    b = Bridge(queue)
    with pytest.raises(BridgeTimeout):
        b.send("a", timeout=0.05)
    with pytest.raises(BridgeTimeout):
        b.send("b", timeout=0.05)
    t.join(timeout=2)
    assert names == sorted(names) and len(names) == 2


def test_concurrent_sends_each_get_their_own_answer(queue):
    results = {}
    b = Bridge(queue)

    def send(i):
        results[i] = b.send(str(i))

    with FakeListener(queue, lambda e: {"ok": True, "result": e}, delay=0.01):
        threads = [threading.Thread(target=send, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
    assert results == {i: str(i) for i in range(5)}


def test_heartbeat_age(queue):
    b = Bridge(queue)
    assert b.heartbeat_age() is None
    (queue / "heartbeat").write_text("beat", encoding="utf-8")
    assert 0 <= b.heartbeat_age() < 5


def test_touch_and_expire_alive(queue):
    b = Bridge(queue)
    b.touch_alive()
    fresh = (queue / "server.alive").stat().st_mtime
    assert time.time() - fresh < 5
    b.expire_alive_for_test()
    assert time.time() - (queue / "server.alive").stat().st_mtime > 3000


def test_queue_dir_is_exposed(queue):
    assert Bridge(queue).queue_dir == queue
