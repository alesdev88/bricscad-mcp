"""What the rest of the server needs from an operating system."""

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import platformdirs
import psutil


@dataclass(frozen=True)
class Installation:
    version: str
    executable: Path


class Platform(ABC):
    @abstractmethod
    def find_installations(self, root: Path | None = None) -> list[Installation]:
        """Return installed versions, newest first. `root` replaces the default install folder."""

    @abstractmethod
    def launch_command(self, inst: Installation, script: Path) -> list[str]:
        """Return the command that starts BricsCAD and runs `script`."""

    def start(self, inst: Installation, script: Path) -> int:
        """Start BricsCAD and return its process id."""
        return spawn(self.launch_command(inst, script))

    def running_pids(self, inst: Installation) -> set[int]:
        """Return the ids of copies of this version that are already running."""
        return pids_running_from(inst.executable)

    def state_dir(self) -> Path:
        return platformdirs.user_state_path("bricscad-mcp")


def pids_running_from(path: Path) -> set[int]:
    """Return the ids of processes whose program is `path` or lies inside it."""
    target = str(path)
    found = set()
    for process in psutil.process_iter(["pid", "exe"]):
        exe = process.info.get("exe") or ""
        if exe == target or exe.startswith(target + "/") or exe.startswith(target + "\\"):
            found.add(process.info["pid"])
    return found


def spawn(command: list[str]) -> int:
    """Start a detached process. Its stdio must stay away from the MCP stdio stream."""
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return process.pid


def sorted_newest_first(found: list[Installation]) -> list[Installation]:
    return sorted(found, key=lambda inst: int(inst.version), reverse=True)


def is_alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def terminate(pid: int, grace_seconds: float = 5.0) -> None:
    """Ask a process to exit, and force it if it has not gone after the grace period."""
    try:
        process = psutil.Process(pid)
        process.terminate()
        try:
            process.wait(timeout=grace_seconds)
        except psutil.TimeoutExpired:
            process.kill()
            process.wait(timeout=grace_seconds)
    except (psutil.NoSuchProcess, psutil.TimeoutExpired):
        pass
