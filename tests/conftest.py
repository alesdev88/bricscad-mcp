"""Shared fixtures: a fake BricsCAD that speaks the real queue protocol."""

import re
import threading
import time
from pathlib import Path

import pytest
from mcp import Client

from bricscad_mcp import server
from bricscad_mcp.platforms.base import Installation, Platform
from bricscad_mcp.session import Session
from fake_listener import FakeListener


class FakeBricsCAD(Platform):
    """Replaces the operating system and the LISP side for server tests."""

    pid = 424242

    def __init__(self, state_dir: Path):
        self._state_dir = state_dir
        self.alive = False
        self.ignore_quit = False
        self.never_ready = False
        self.other_pids: set[int] = set()
        self.unsaved = 0
        self.drawing = "Drawing1.dwg"
        self.requests: list[str] = []
        self.responses: dict = {}
        self.started_scripts: list[Path] = []
        self.terminated: list[int] = []
        self._listener: FakeListener | None = None
        self._stop = threading.Event()

    # Platform
    def find_installations(self, root=None):
        return [Installation("26", Path("/fake/BricsCAD V26.app"))]

    def launch_command(self, inst, script):
        return ["fake", str(script)]

    def state_dir(self):
        return self._state_dir

    def running_pids(self, inst):
        return set(self.other_pids)

    def start(self, inst, script):
        self.started_scripts.append(script)
        self.alive = True
        if not self.never_ready:
            queue = script.parent / "queue"
            self._listener = FakeListener(queue, self._handle)
            self._listener.__enter__()
            threading.Thread(target=self._watch_quit, args=(queue,), daemon=True).start()
        return self.pid

    # Test controls
    def die(self):
        self.alive = False
        self.close()

    def close(self):
        self._stop.set()
        if self._listener is not None:
            self._listener.__exit__()
            self._listener = None

    # Fake LISP
    def _handle(self, expr: str) -> dict:
        self.requests.append(expr)
        match = re.match(r"\(([^\s()]+)", expr)
        name = match.group(1) if match else expr
        if name in self.responses:
            value = self.responses[name]
            value = value(expr) if callable(value) else value
            if isinstance(value, Exception):
                return {"ok": False, "error": str(value)}
            return {"ok": True, "result": value}
        if name == "mcp:unsaved-count":
            return {"ok": True, "result": self.unsaved}
        if name == "mcp:current-drawing":
            return {"ok": True, "result": self.drawing}
        return {"ok": True, "result": None}

    def _watch_quit(self, queue: Path) -> None:
        while not self._stop.is_set():
            if (queue / "quit.flag").exists() and not self.ignore_quit:
                self.die_soon()
                return
            time.sleep(0.01)

    def die_soon(self):
        self.alive = False


@pytest.fixture
def fake(tmp_path, monkeypatch):
    bricscad = FakeBricsCAD(tmp_path / "state")
    monkeypatch.setattr("bricscad_mcp.session.is_alive", lambda pid: bricscad.alive and pid == bricscad.pid)

    def terminate(pid):
        bricscad.terminated.append(pid)
        bricscad.alive = False

    monkeypatch.setattr("bricscad_mcp.session.terminate", terminate)
    monkeypatch.delenv("BRICSCAD_EXECUTABLE", raising=False)
    monkeypatch.delenv("BRICSCAD_VERSION", raising=False)
    yield bricscad
    bricscad.close()


@pytest.fixture
def session(fake):
    s = Session(fake)
    s.stop_wait_seconds = 0.2
    yield s
    s.close()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(fake):
    """An MCP client connected to the real server, with BricsCAD faked."""
    s = Session(fake)
    s.stop_wait_seconds = 0.2
    server.set_session(s)
    async with Client(server.mcp) as connected:
        yield connected
    s.close()
    server.set_session(None)
