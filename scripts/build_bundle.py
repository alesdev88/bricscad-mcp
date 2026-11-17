"""Build a self-contained .mcpb bundle: interpreter, dependencies, server.

Adapted from Archicad MCP's build_bundle.py. The bundle needs nothing on the target machine: no uv,
no Python and no network at first launch. Claude Desktop ships neither uv nor Python, so a bundle
of server type "uv" or "python" fails on a machine without them.

What goes in:

  runtime/       a relocatable CPython from astral-sh/python-build-standalone, with every
                 dependency installed into its own site-packages, so it runs isolated (-I).
  manifest.json  this repository's manifest with the server block pointed at that interpreter
                 and platforms narrowed to the one target the bundle was built for.

One bundle per platform, because dependencies such as pydantic-core and psutil are compiled.
Cross-building works: the Windows bundle builds on macOS or Linux.

Usage:
    uv run python scripts/build_bundle.py --target all
    uv run python scripts/build_bundle.py --target darwin-arm64 --no-pack
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Pinned: these decide what the shipped interpreter is. Same pins as Archicad MCP.
PBS_TAG = "20260825"
PYTHON_VERSION = "3.12.14"
MCPB = "@anthropic-ai/mcpb@2.1.2"

PBS_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    "{tag}/cpython-{ver}+{tag}-{triple}-install_only_stripped.tar.gz"
)

# uv_platform is what uv resolves wheels for; mcpb_platform is what Claude Desktop matches.
TARGETS = {
    "win32": {
        "triple": "x86_64-pc-windows-msvc",
        "uv_platform": "x86_64-pc-windows-msvc",
        "mcpb_platform": "win32",
        "interpreter": "runtime/python.exe",
        "site_packages": "runtime/Lib/site-packages",
        "sep": "\\",
    },
    "darwin-arm64": {
        "triple": "aarch64-apple-darwin",
        "uv_platform": "aarch64-apple-darwin",
        "mcpb_platform": "darwin",
        "interpreter": "runtime/bin/python3",
        "site_packages": f"runtime/lib/python{PYTHON_VERSION.rsplit('.', 1)[0]}/site-packages",
        "sep": "/",
    },
}

# No darwin-x86_64: Claude Desktop matches only "darwin", not the CPU, so an Intel bundle would
# also be offered to Apple silicon Macs. Intel Macs use the uvx install in README.


def run(cmd: list[str], **kw) -> None:
    print("  $", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def fetch_runtime(target: dict, cache: Path) -> Path:
    """Download the standalone interpreter, cached by its archive name, which pins everything."""
    url = PBS_URL.format(tag=PBS_TAG, ver=PYTHON_VERSION, triple=target["triple"])
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / url.rsplit("/", 1)[-1]
    if archive.exists():
        print(f"  cached {archive.name}")
        return archive
    print(f"  downloading {archive.name}")
    urllib.request.urlretrieve(url, archive)
    return archive


def build(target_name: str, out_dir: Path, cache: Path, keep_staging: bool, pack: bool) -> Path:
    target = TARGETS[target_name]
    manifest = json.loads((REPO / "manifest.json").read_text(encoding="utf-8"))
    version = manifest["version"]

    staging = REPO / "build" / target_name
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    print(f"[1/6] interpreter  CPython {PYTHON_VERSION} for {target['triple']}")
    with tarfile.open(fetch_runtime(target, cache)) as tf:
        tf.extractall(staging, filter="data")
    (staging / "python").rename(staging / "runtime")

    print("[2/6] wheel        building the project wheel")
    wheel_dir = staging / "_wheel"
    run(["uv", "build", "--wheel", "--out-dir", str(wheel_dir)], cwd=REPO)
    wheel = next(wheel_dir.glob("*.whl"))

    print("[3/6] lockfile     exporting runtime dependencies")
    reqs = staging / "_requirements.txt"
    # The project goes in as the wheel above, not as an editable reference to this checkout.
    run(["uv", "export", "--quiet", "--no-dev", "--no-hashes", "--no-emit-project",
         "--format", "requirements-txt", "-o", str(reqs)], cwd=REPO)

    site = staging / target["site_packages"]
    print(f"[4/6] dependencies installing into {target['site_packages']}")
    # Into the interpreter's own site-packages, so -I (which ignores PYTHONPATH) still finds them.
    # Wheels only: a source build would compile for this machine, not the target.
    base = ["uv", "pip", "install", "--quiet",
            "--python-platform", target["uv_platform"],
            "--python-version", PYTHON_VERSION.rsplit(".", 1)[0],
            "--only-binary", ":all:",
            "--target", str(site)]
    run([*base, "--requirement", str(reqs)], cwd=REPO)
    # --no-deps: the lock already pinned the tree.
    run([*base, "--no-deps", str(wheel)], cwd=REPO)
    for pycache in site.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)

    print("[5/6] manifest     rewriting the server block")
    sep = target["sep"]
    manifest["server"] = {
        # "binary", not "python": Claude Desktop reads "python" as needing a Python on the machine.
        "type": "binary",
        "entry_point": target["interpreter"],
        "mcp_config": {
            "command": "${__dirname}" + sep + target["interpreter"].replace("/", sep),
            # -I ignores PYTHONPATH and the user site, so nothing on the host leaks in.
            "args": ["-I", "-m", "bricscad_mcp"],
            "env": manifest["server"]["mcp_config"]["env"],
        },
    }
    manifest["compatibility"]["platforms"] = [target["mcpb_platform"]]
    manifest.pop("_meta", None)
    (staging / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for extra in ("icon.png", "LICENSE"):
        if (REPO / extra).exists():
            shutil.copy(REPO / extra, staging / extra)

    shutil.rmtree(wheel_dir)
    reqs.unlink()

    if target_name == host_target():
        print("verify        importing the server with the bundled interpreter")
        run([str(staging / target["interpreter"]), "-I", "-c", "import bricscad_mcp.server"])
    else:
        print(f"verify        skipped, {target_name} is not this host")

    if not pack:
        print(f"[6/6] pack         skipped, staging left in {staging.relative_to(REPO)}")
        return staging

    print("[6/6] pack")
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = out_dir / f"bricscad-mcp-{version}-{target_name}.mcpb"
    run(["npx", "--yes", MCPB, "validate", str(staging / "manifest.json")])
    run(["npx", "--yes", MCPB, "pack", str(staging), str(bundle)])
    print(f"\n{bundle.relative_to(REPO)}  {bundle.stat().st_size / 1_000_000:.1f} MB")
    if not keep_staging:
        shutil.rmtree(staging)
    return bundle


def host_target() -> str | None:
    """Which target, if any, this machine can run."""
    if sys.platform == "win32":
        return "win32"
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return "darwin-arm64"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target", choices=[*TARGETS, "all"], required=True)
    ap.add_argument("--out-dir", type=Path, default=REPO / "dist")
    ap.add_argument("--cache", type=Path, default=REPO / "build" / "_runtimes")
    ap.add_argument("--keep-staging", action="store_true",
                    help="leave build/<target>/ in place for inspection")
    ap.add_argument("--no-pack", action="store_true",
                    help="stop before validating and packing with the mcpb CLI; keeps the staging folder")
    a = ap.parse_args()
    for name in list(TARGETS) if a.target == "all" else [a.target]:
        print(f"\n=== {name} ===")
        build(name, a.out_dir, a.cache, a.keep_staging, pack=not a.no_pack)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
