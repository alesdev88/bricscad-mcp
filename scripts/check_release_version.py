"""Check that a release tag names the version every file states.

pyproject.toml, manifest.json and server.json must agree with each other (tests/test_packaging.py
checks that on every run) and with the tag being released. Standard library only:

    uv run --no-project python scripts/check_release_version.py v0.1.0
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def versions() -> dict[str, str]:
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    found = {
        "pyproject.toml": tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"],
        "manifest.json": json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))["version"],
        "server.json": server["version"],
    }
    for index, package in enumerate(server["packages"]):
        found[f"server.json packages[{index}]"] = package["version"]
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    tag = argv[0].removeprefix("v")
    wrong = {where: version for where, version in versions().items() if version != tag}
    if wrong:
        for where, version in wrong.items():
            print(f"{where} says {version}, the tag says {tag}")
        return 1
    print(f"Every file says {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
