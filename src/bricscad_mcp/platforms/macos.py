"""macOS: BricsCAD is an app bundle started through `open`."""

import re
import subprocess
import time
from pathlib import Path

import psutil

from ..errors import BricsCADError
from .base import Installation, Platform, sorted_newest_first, spawn

DEFAULT_ROOT = Path("/Applications")
START_WAIT_SECONDS = 30.0
_BUNDLE = re.compile(r"BricsCAD V(\d+)\.app")


def bundle_pids(app: Path) -> set[int]:
    """Return the ids of processes running from inside an app bundle."""
    prefix = f"{app}/"
    found = set()
    for process in psutil.process_iter(["pid", "exe"]):
        if (process.info.get("exe") or "").startswith(prefix):
            found.add(process.info["pid"])
    return found


class MacOS(Platform):
    def find_installations(self, root: Path | None = None) -> list[Installation]:
        root = root or DEFAULT_ROOT
        if not root.is_dir():
            return []
        found = []
        for item in root.iterdir():
            match = _BUNDLE.fullmatch(item.name)
            if match and item.is_dir():
                found.append(Installation(match.group(1), item))
        return sorted_newest_first(found)

    def launch_command(self, inst: Installation, script: Path) -> list[str]:
        if inst.executable.suffix == ".app":
            return ["open", "-n", "-a", str(inst.executable), "--args", "-b", str(script)]
        return [str(inst.executable), "-b", str(script)]

    def start(self, inst: Installation, script: Path) -> int:
        command = self.launch_command(inst, script)
        if inst.executable.suffix != ".app":
            return spawn(command)

        # `open` does not report the app's id, so look for the process that is new.
        before = bundle_pids(inst.executable)
        subprocess.run(command, check=True, stdin=subprocess.DEVNULL, capture_output=True)
        deadline = time.monotonic() + START_WAIT_SECONDS
        while True:
            new = bundle_pids(inst.executable) - before
            if new:
                return min(new)
            if time.monotonic() >= deadline:
                raise BricsCADError(f"{inst.executable.name} did not start within {START_WAIT_SECONDS:g} seconds.")
            time.sleep(0.2)
