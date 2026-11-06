"""Operating system support. Everything platform-specific stays in this package."""

import os
import sys
from pathlib import Path

from ..errors import BricsCADError
from .base import Installation, Platform


def get_platform(name: str | None = None) -> Platform:
    name = name or sys.platform
    if name == "darwin":
        from .macos import MacOS

        return MacOS()
    if name == "win32":
        from .windows import Windows

        return Windows()
    if name.startswith("linux"):
        from .linux import Linux

        return Linux()
    raise BricsCADError(f"Unsupported platform: {name}. Supported: macOS, Windows, Linux.")


def select_installation(platform: Platform, version: str | None = None) -> Installation:
    """Choose what to start: an explicit version, then the environment, then the newest found."""
    if version is None:
        override = os.environ.get("BRICSCAD_EXECUTABLE")
        if override:
            path = Path(override)
            if not path.exists():
                raise BricsCADError(f"BRICSCAD_EXECUTABLE points to a missing path: {override}")
            return Installation("custom", path)
        version = os.environ.get("BRICSCAD_VERSION")

    found = platform.find_installations()
    if not found:
        raise BricsCADError("No BricsCAD installation found. Set BRICSCAD_EXECUTABLE to its path.")
    if version is None:
        return found[0]
    for inst in found:
        if inst.version == version:
            return inst
    versions = ", ".join(inst.version for inst in found)
    raise BricsCADError(f"BricsCAD V{version} is not installed. Found: {versions}.")
