#!/usr/bin/env python3
"""Run one Phase 0 probe on BricsCAD (macOS only). See docs/phase-0-results.md.

usage: run_probe.py PROBE.lsp [--version 26] [--timeout 60] [--measure-cpu SECONDS]
                              [--keep-open SECONDS] [--extra ARG ...]
"""
import argparse
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent


def lisp_str(path: Path | str) -> str:
    return '"' + str(path).replace("\\", "/").replace('"', '\\"') + '"'


def bricscad_pids(app: Path) -> set[int]:
    found = set()
    for proc in psutil.process_iter(["pid", "exe"]):
        exe = proc.info.get("exe") or ""
        if exe.startswith(str(app) + "/"):
            found.add(proc.info["pid"])
    return found


def window_names(pid: int) -> str:
    script = (
        'tell application "System Events" to tell '
        f"(first process whose unix id is {pid}) to get name of every window"
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return (result.stdout or result.stderr).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("probe")
    parser.add_argument("--version", default="26")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--measure-cpu", type=int, default=0)
    parser.add_argument("--keep-open", type=int, default=0)
    parser.add_argument("--extra", nargs="*", default=[])
    args = parser.parse_args()

    app = Path(f"/Applications/BricsCAD V{args.version}.app")
    work = Path(tempfile.mkdtemp(prefix="bcad-probe-"))
    log = work / "log.txt"

    bootstrap = work / "bootstrap.lsp"
    bootstrap.write_text(
        f"(setq *dir* {lisp_str(str(work) + '/')})\n"
        f"(setq *here* {lisp_str(str(HERE) + '/')})\n"
        f"(load {lisp_str(HERE / 'common.lsp')})\n"
        f"(load {lisp_str(HERE / args.probe)})\n",
        encoding="utf-8",
    )

    before = bricscad_pids(app)
    subprocess.run(
        ["open", "-n", "-a", str(app), "--args", "-b", str(bootstrap), *args.extra],
        check=True,
    )

    pid = None
    deadline = time.monotonic() + 30
    while pid is None and time.monotonic() < deadline:
        new = bricscad_pids(app) - before
        pid = next(iter(new), None)
        time.sleep(0.2)
    print(f"pid: {pid}")
    if pid is None:
        print("NO PROCESS")
        return 1

    started = time.monotonic()
    state = "BLOCKED"
    while time.monotonic() - started < args.timeout:
        if log.exists() and any(l.startswith("done") or " done = " in l for l in log.read_text(errors="replace").splitlines()):
            state = "finished"
            break
        if not psutil.pid_exists(pid):
            state = "process exited before done"
            break
        if args.measure_cpu and log.exists() and "ready" in log.read_text(errors="replace"):
            state = "measuring"
            break
        time.sleep(0.25)

    if state == "measuring":
        proc = psutil.Process(pid)
        proc.cpu_percent(None)
        time.sleep(args.measure_cpu)
        print(f"cpu_percent_of_one_core_over_{args.measure_cpu}s: {proc.cpu_percent(None):.1f}")
        state = "measured"

    if args.keep_open and psutil.pid_exists(pid):
        print(f"keeping open for {args.keep_open}s; windows: {window_names(pid)}")
        time.sleep(args.keep_open)

    if state == "measured":
        (work / "quit.flag").touch()

    print(f"state: {state} after {time.monotonic() - started:.1f}s")
    if state == "BLOCKED":
        print(f"windows: {window_names(pid)}")

    # Let the probe quit by itself, then stop only the process started here.
    deadline = time.monotonic() + 20
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.25)
    if psutil.pid_exists(pid):
        print(f"still running after quit; windows: {window_names(pid)}; terminating {pid}")
        psutil.Process(pid).terminate()
    else:
        print("exited by itself")

    print("--- log")
    print(log.read_text(errors="replace") if log.exists() else "(no log)")
    print("--- files")
    for item in sorted(work.iterdir()):
        print(f"{item.stat().st_size:>9}  {item.name}")
        if item.suffix == ".raw":
            print(f"           bytes: {item.read_bytes()!r}")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
