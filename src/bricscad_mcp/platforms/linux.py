"""Linux: experimental. The default install folder is unverified."""

import re
from pathlib import Path

from . import base
from .base import Installation, Platform, sorted_newest_first

DEFAULT_ROOT = Path("/opt/bricsys/bricscad")
_FOLDER = re.compile(r"v(\d+)")


class Linux(Platform):
    def find_installations(self, root: Path | None = None) -> list[Installation]:
        root = root or DEFAULT_ROOT
        if not root.is_dir():
            return []
        found = []
        for item in root.iterdir():
            match = _FOLDER.fullmatch(item.name)
            executable = item / "bricscad.sh"
            if match and executable.is_file():
                found.append(Installation(match.group(1), executable))
        return sorted_newest_first(found)

    def launch_command(self, inst: Installation, script: Path) -> list[str]:
        return [str(inst.executable), "-b", str(script)]

    def running_pids(self, inst: Installation) -> set[int]:
        # bricscad.sh starts a program that lives beside it.
        return base.pids_running_from(inst.executable.parent)
