"""The file queue between this server and the LISP listener.

A request is `<id>.lsp`, a reply is `<id>.json`. Both appear by rename, so neither
side reads a partial file. The listener renames a request to `<id>.run` while it
works on it. Ids start with a timestamp, so sorting by name gives the oldest first.
"""

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .errors import BridgeTimeout, LispError, ProcessDied

ENCODING = "utf-8"

# Requests are always UTF-8: BricsCAD converts them on load. Replies come back in LISP's own
# text encoding, which is UTF-8 only where LISP supports Unicode. See Session for the check.


class Bridge:
    def __init__(
        self,
        queue_dir: Path,
        alive_check: Callable[[], bool] = lambda: True,
        poll_interval: float = 0.05,
    ):
        self.queue_dir = Path(queue_dir)
        self._alive_check = alive_check
        self._poll_interval = poll_interval
        self._lock = threading.Lock()
        self.reply_encoding = ENCODING

    def send(self, expr: str, timeout: float = 30.0) -> Any:
        """Run a LISP expression in BricsCAD and return its result."""
        with self._lock:
            self._raise_if_dead()
            self._discard_old_replies()
            request_id = f"{time.time_ns():020d}-{uuid.uuid4().hex}"
            request = self.queue_dir / f"{request_id}.lsp"
            temporary = self.queue_dir / f"{request_id}.tmp"
            temporary.write_text(expr, encoding=ENCODING)
            os.replace(temporary, request)
            return self._wait_for_reply(request_id, request, timeout)

    def heartbeat_age(self) -> float | None:
        """Seconds since the listener last reported in, or None if it never has."""
        try:
            return max(0.0, time.time() - (self.queue_dir / "heartbeat").stat().st_mtime)
        except FileNotFoundError:
            return None

    def touch_alive(self) -> None:
        """Tell the listener this server is still here."""
        (self.queue_dir / "server.alive").write_text("alive", encoding=ENCODING)

    def expire_alive_for_test(self) -> None:
        then = time.time() - 3600
        os.utime(self.queue_dir / "server.alive", (then, then))

    def _wait_for_reply(self, request_id: str, request: Path, timeout: float) -> Any:
        reply = request.with_suffix(".json")
        deadline = time.monotonic() + timeout
        while True:
            if reply.exists():
                try:
                    return self._read_reply(request_id, reply)
                except PermissionError:
                    # Windows can keep a new file locked for a moment. Try again until the deadline.
                    pass
            if not self._alive_check():
                request.unlink(missing_ok=True)
                self._raise_if_dead()
            if time.monotonic() >= deadline:
                request.unlink(missing_ok=True)
                raise BridgeTimeout(self._timeout_message(timeout))
            time.sleep(self._poll_interval)

    def _read_reply(self, request_id: str, reply: Path) -> Any:
        text = reply.read_text(encoding=self.reply_encoding, errors="replace")
        _remove(reply)
        try:
            data = json.loads(text)
            if data["id"] != request_id:
                raise ValueError("wrong id")
        except (ValueError, KeyError, TypeError):
            raise LispError(f"BricsCAD sent an unreadable reply: {text[:200]!r}") from None
        if not data.get("ok"):
            raise LispError(str(data.get("error") or "Unknown LISP error."))
        return data.get("result")

    def _discard_old_replies(self) -> None:
        # Anything here belongs to a request that already timed out.
        for old in self.queue_dir.glob("*.json"):
            _remove(old)

    def _raise_if_dead(self) -> None:
        if not self._alive_check():
            raise ProcessDied("The BricsCAD process has stopped. Start a new one with bricscad_start.")

    def _timeout_message(self, timeout: float) -> str:
        age = self.heartbeat_age()
        heartbeat = "No heartbeat received." if age is None else f"Last heartbeat {age:.1f} seconds ago."
        return (
            f"BricsCAD did not answer within {timeout:g} seconds. A dialog may be blocking it, "
            f"so check the BricsCAD window. {heartbeat} If it had already started this request, "
            "it keeps running and its result is lost, so check the current state before retrying."
        )


def _remove(path: Path) -> None:
    """Delete a reply. One that is still locked is left for the next request to clear."""
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        pass
