"""Starts and stops the one BricsCAD process this server owns."""

import atexit
import shutil
import threading
import time
import uuid
from pathlib import Path

from .bridge import Bridge
from .errors import BricsCADError, BridgeTimeout, NotRunning, ProcessDied, SafetyRefused
from .lispgen import call, lisp_path, lisp_str
from .platforms import select_installation
from .platforms.base import Platform, is_alive, terminate

LISP_DIR = Path(__file__).parent / "lisp"
LISP_FIRST = ["json.lsp", "listener.lsp"]


class Session:
    def __init__(self, platform: Platform, base_dir: Path | None = None):
        self._platform = platform
        self._base_dir = Path(base_dir) if base_dir else platform.state_dir() / "sessions"
        self._bridge: Bridge | None = None
        self._pid: int | None = None
        self._version: str | None = None
        self._stop_alive = threading.Event()
        self.stop_wait_seconds = 15.0
        self.unsaved_check_timeout = 10.0
        self.status_timeout = 5.0
        self.alive_interval_seconds = 30.0
        atexit.register(self.close)

    @property
    def platform(self) -> Platform:
        return self._platform

    @property
    def bridge(self) -> Bridge | None:
        return self._bridge

    @property
    def pid(self) -> int | None:
        return self._pid

    def start(self, version: str | None = None, timeout: float = 120.0) -> dict:
        """Start a new BricsCAD process and wait for its listener."""
        if self._pid is not None and is_alive(self._pid):
            raise BricsCADError(f"BricsCAD is already running as process {self._pid}. Use bricscad_stop first.")
        self._clear()

        installation = select_installation(self._platform, version)
        running = self._platform.running_pids(installation)
        if running:
            raise BricsCADError(
                f"BricsCAD V{installation.version} is already running as process "
                f"{', '.join(str(pid) for pid in sorted(running))}. A second copy of the same version "
                "does not start its listener. Close that copy first, or choose another version."
            )
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._remove_old_sessions()
        # The startup script stays out of the queue, or the listener would run it as a request.
        folder = self._base_dir / uuid.uuid4().hex
        folder.mkdir(mode=0o700)
        queue = folder / "queue"
        queue.mkdir(mode=0o700)

        bridge = Bridge(queue, alive_check=lambda: self._pid is not None and is_alive(self._pid))
        bridge.touch_alive()
        script = folder / "bootstrap.lsp"
        script.write_text(_bootstrap(queue), encoding="utf-8")

        self._pid = self._platform.start(installation, script)
        self._version = installation.version
        self._bridge = bridge
        (folder / "pid").write_text(str(self._pid), encoding="utf-8")
        self._start_alive_thread(bridge)
        self._wait_for_listener(bridge, timeout)
        return {"pid": self._pid, "version": self._version, "executable": str(installation.executable)}

    def stop(self, discard: bool = False) -> dict:
        """Close the process this session started. Refuses to lose work unless told to."""
        bridge = self.require_bridge()
        if not discard:
            self._refuse_if_unsaved(bridge)
        if discard:
            (bridge.queue_dir / "discard.flag").touch()
        (bridge.queue_dir / "quit.flag").touch()

        pid = self._pid
        deadline = time.monotonic() + self.stop_wait_seconds
        while is_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        forced = is_alive(pid)
        if forced:
            terminate(pid)
        self._clear()
        return {"stopped": True, "forced": forced}

    def status(self) -> dict:
        running = self._pid is not None and is_alive(self._pid)
        status = {
            "running": running,
            "pid": self._pid if running else None,
            "version": self._version if running else None,
            "heartbeat_age": None,
            "drawing": None,
        }
        if running:
            status["heartbeat_age"] = self._bridge.heartbeat_age()
            try:
                status["drawing"] = self._bridge.send(call("mcp:current-drawing"), timeout=self.status_timeout)
            except BricsCADError:
                pass
        return status

    def require_bridge(self) -> Bridge:
        if self._pid is None:
            raise NotRunning("BricsCAD is not running. Start it with bricscad_start.")
        if not is_alive(self._pid):
            self._clear()
            raise ProcessDied("The BricsCAD process has stopped. Start a new one with bricscad_start.")
        return self._bridge

    def close(self) -> None:
        """Called when the server exits: ask the listener to stop, keeping any unsaved work."""
        self._stop_alive.set()
        if self._bridge is not None and self._bridge.queue_dir.is_dir():
            (self._bridge.queue_dir / "quit.flag").touch()

    def _refuse_if_unsaved(self, bridge: Bridge) -> None:
        try:
            unsaved = bridge.send(call("mcp:unsaved-count"), timeout=self.unsaved_check_timeout)
        except BridgeTimeout:
            raise SafetyRefused(
                "Could not check for unsaved changes because BricsCAD is not answering. "
                "Check its window, or pass discard=true to close it and lose any changes."
            ) from None
        if unsaved:
            raise SafetyRefused(
                f"{unsaved} open drawing(s) have unsaved changes. Save them, or pass discard=true to lose them."
            )

    def _wait_for_listener(self, bridge: Bridge, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while bridge.heartbeat_age() is None:
            if not is_alive(self._pid):
                self._clear()
                raise ProcessDied("BricsCAD exited during startup. Check its licence and try bricscad_start again.")
            if time.monotonic() >= deadline:
                # This copy was started moments ago for the server, so it holds no work.
                terminate(self._pid)
                self._clear()
                raise BridgeTimeout(
                    f"BricsCAD started, but its listener did not report within {timeout:g} seconds, "
                    "so that copy was closed. A dialog may have been blocking it, such as a licence "
                    "prompt. Open BricsCAD by hand to check, close it, then try bricscad_start again."
                )
            time.sleep(0.1)

    def _start_alive_thread(self, bridge: Bridge) -> None:
        self._stop_alive = threading.Event()
        stop = self._stop_alive

        def keep_alive() -> None:
            while not stop.wait(self.alive_interval_seconds):
                try:
                    bridge.touch_alive()
                except OSError:
                    return

        threading.Thread(target=keep_alive, daemon=True).start()

    def _remove_old_sessions(self) -> None:
        for folder in self._base_dir.iterdir():
            if folder.is_dir() and not _has_live_process(folder):
                shutil.rmtree(folder, ignore_errors=True)

    def _clear(self) -> None:
        self._stop_alive.set()
        self._bridge = None
        self._pid = None
        self._version = None


def _has_live_process(folder: Path) -> bool:
    try:
        return is_alive(int((folder / "pid").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return False


def _bootstrap(queue: Path) -> str:
    others = sorted(p.name for p in LISP_DIR.glob("*.lsp") if p.name not in LISP_FIRST)
    loads = "".join(f"(load {lisp_path(LISP_DIR / name)})\n" for name in [*LISP_FIRST, *others])
    return f"{loads}(mcp:listen {lisp_str(queue.as_posix() + '/')})\n"
