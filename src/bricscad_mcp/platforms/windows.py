"""Windows: experimental. The default install folder is unverified."""

import re
from pathlib import Path

from .base import Installation, Platform, sorted_newest_first

DEFAULT_ROOT = Path("C:/Program Files/Bricsys")
_FOLDER = re.compile(r"BricsCAD V(\d+)( .*)?")


class Windows(Platform):
    def find_installations(self, root: Path | None = None) -> list[Installation]:
        root = root or DEFAULT_ROOT
        if not root.is_dir():
            return []
        found = []
        for item in root.iterdir():
            match = _FOLDER.fullmatch(item.name)
            executable = item / "bricscad.exe"
            if match and executable.is_file():
                found.append(Installation(match.group(1), executable))
        return sorted_newest_first(found)

    def launch_command(self, inst: Installation, script: Path) -> list[str]:
        return [str(inst.executable), "/B", str(script)]
