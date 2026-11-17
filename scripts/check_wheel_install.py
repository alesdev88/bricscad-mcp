"""Install the built wheel the way a user does, without uv.lock, then start it.

The tests prove the locked dependency set. `uvx bricscad-mcp` never sees the lock: it resolves
every dependency to the newest release pyproject.toml allows. Adapted from Archicad MCP, where a
new release of a dependency once broke every fresh install while the tests stayed green.

Run after `uv build`. Standard library only:

    uv run --no-project python scripts/check_wheel_install.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

WINDOWS = os.name == "nt"


def run(cmd: list[str], stdin: str | None = None) -> str:
    print("+", " ".join(cmd), flush=True)
    done = subprocess.run(cmd, capture_output=True, text=True, input=stdin)
    if done.returncode != 0:
        sys.stdout.write(done.stdout)
        sys.stderr.write(done.stderr)
        raise SystemExit(f"failed ({done.returncode}): {' '.join(cmd)}")
    return done.stdout


def main() -> None:
    wheels = sorted(Path("dist").glob("bricscad_mcp-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected one bricscad_mcp wheel in dist/, found {len(wheels)}")
    wheel = wheels[0].resolve()
    with tempfile.TemporaryDirectory() as tmp:
        venv = Path(tmp) / "venv"
        run(["uv", "venv", str(venv)])
        bindir = venv / ("Scripts" if WINDOWS else "bin")
        python = bindir / ("python.exe" if WINDOWS else "python")
        run(["uv", "pip", "install", "--python", str(python), str(wheel)])
        # Every tool registers and the LISP files ship in the wheel.
        count = run([str(python), "-I", "-c",
                     "import asyncio; from importlib.resources import files; "
                     "from bricscad_mcp.server import mcp; "
                     "assert files('bricscad_mcp').joinpath('lisp', 'listener.lsp').is_file(); "
                     "print(len(asyncio.run(mcp.list_tools())))"])
        # The installed command starts and exits when its input closes.
        run([str(bindir / ("bricscad-mcp.exe" if WINDOWS else "bricscad-mcp"))], stdin="")
        mcp_version = run([str(python), "-c", "import importlib.metadata as m; print(m.version('mcp'))"])
    print(f"{wheel.name}: installs and starts without the lock "
          f"({count.strip()} tools, mcp {mcp_version.strip()})")


if __name__ == "__main__":
    main()
