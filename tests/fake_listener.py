"""A Python stand-in for lisp/listener.lsp that follows the same queue protocol."""

import json
import os
import threading
import time
from pathlib import Path
from typing import Callable


class FakeListener:
    def __init__(
        self,
        queue_dir: Path,
        handler: Callable[[str], dict],
        delay: float = 0.0,
        encoding: str = "utf-8",
    ):
        """`encoding` is how replies are written: LISP on Windows writes its own code page."""
        self.queue_dir = Path(queue_dir)
        self.handler = handler
        self.delay = delay
        self.encoding = encoding
        self.requests: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> "FakeListener":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            (self.queue_dir / "heartbeat").write_text("beat", encoding="utf-8")
            for request in sorted(self.queue_dir.glob("*.lsp")):
                self._answer(request)
            time.sleep(0.005)

    def _answer(self, request: Path) -> None:
        running = request.with_suffix(".run")
        try:
            os.replace(request, running)
        except FileNotFoundError:
            return
        expr = running.read_text(encoding="utf-8")
        self.requests.append(expr)
        if self.delay:
            time.sleep(self.delay)
        reply = {"id": request.stem, "ok": True, "result": None, "error": None, "elapsed_ms": 0}
        reply.update(self.handler(expr))
        temporary = request.with_suffix(".reply")
        temporary.write_text(json.dumps(reply, ensure_ascii=False), encoding=self.encoding)
        os.replace(temporary, request.with_suffix(".json"))
        running.unlink()
