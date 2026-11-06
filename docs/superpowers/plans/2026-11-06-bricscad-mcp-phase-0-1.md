# BricsCAD MCP Phase 0 and 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer the Phase 0 unknowns, then ship a working MCP server that starts BricsCAD, opens drawings and reads and audits them.

**Architecture:** A Python stdio MCP server writes LISP requests into a per-session queue folder. A LISP listener running inside a BricsCAD process it started runs them one at a time and writes JSON replies. One platform module per operating system handles discovery and launching.

**Tech Stack:** Python 3.11+, official `mcp` SDK (`FastMCP`), `psutil`, `platformdirs`, `uv`, `pytest`, AutoLISP/Visual LISP, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-06-bricscad-mcp-design.md`

**Scope:** Phases 2 to 4 get their own plans after Task 1, because its results can change how they are built.

## Global Constraints

- Python 3.11 or newer; `uv` for packaging; stdio transport; tool names use the `bricscad_` prefix.
- Save only with `_.SAVEAS` and `_.QSAVE`. Never use `vla-save` or `vla-saveas`.
- Never assume a value for `FILEDIA`. Any variable changed during a request is restored in that request, including on error.
- `bricscad_start` always starts a new process. `bricscad_stop` stops only that process and refuses on unsaved changes unless `discard=true`.
- Drawings open read-only by default.
- Paths reach LISP only as escaped strings from `lispgen`, never as raw LISP.
- Queue folder: per-user state folder, new for each session, owner-only permissions.
- Request timeout: 30 seconds by default, settable per call.
- List tools take `limit` and `offset` and report `total`. Default `limit` 200, maximum 2000.
- Real-BricsCAD tests are marked `bricscad`, use only temporary drawings they create, and never open a user's file. They run one at a time.
- macOS is "Supported" once these tests pass. Windows and Linux stay "Experimental" until the same tests pass there.

## Review Focus

1. Text and paths containing `č š ž`, spaces, quotes, backslashes and newlines should round-trip unchanged. Tests: Tasks 2, 5, 9.
2. A drawing with no entities or no matches should return an empty list and `total: 0`, not a LISP error from `(sslength nil)`. Tests: Task 9.
3. BricsCAD quitting or crashing during a request should fail promptly with a clear error, not after the full timeout. Tests: Task 4.
4. The MCP client exiting or being killed should not leave a listener polling forever. Tests: Tasks 5, 6.
5. A missing file, a folder, or a non-DWG passed to `bricscad_open_drawing` should return an error with no dialog in BricsCAD. Tests: Task 8.

---

## File structure

```
pyproject.toml, .gitignore, README.md, .github/workflows/ci.yml
scripts/phase0/run_probe.py, scripts/phase0/*.lsp
docs/phase-0-results.md
src/bricscad_mcp/
  server.py        FastMCP instance, entry point
  lispgen.py       LISP string, path and expression generation
  bridge.py        queue protocol, timeouts
  session.py       BricsCAD lifecycle, bootstrap, health
  errors.py        exception types
  platforms/       base.py macos.py windows.py linux.py __init__.py
  lisp/            json.lsp listener.lsp read.lsp audit.lsp
  tools/           core.py drawing.py read.py audit.py
tests/
  fake_listener.py, conftest.py, test_*.py, real/test_*.py
```

---

### Task 1: Phase 0 probes

**Files:**
- Create: `scripts/phase0/run_probe.py`, `scripts/phase0/*.lsp`, `docs/phase-0-results.md`

**Interfaces:**
- Produces: `docs/phase-0-results.md`, which later tasks and plans read for the confirmed call sequences.

- [ ] **Step 1: Write `run_probe.py <probe.lsp>`**

macOS only. Creates a temp folder, passes it to the probe through a generated bootstrap `.lsp`, launches V26 with `open -n -a ... --args -b`, waits up to 60 seconds for `done`, and prints the log. If blocked, it reports `BLOCKED`, captures the window state for inspection and stops only the process it started. Each log line carries `CDATE` so pauses are visible.

- [ ] **Step 2: Write and run one probe per spec question**

| Probe | Records |
|---|---|
| `open_second.lsp` | Whether the loop keeps running after `_.OPEN`, with `SDI=0`, then `SDI=1`, then `/LD` |
| `open_readonly.lsp` | Command sequence for a read-only open, and how to read that state back |
| `saveas_existing.lsp` | Exact prompt sequence when the target exists |
| `plot_pdf.lsp` | Whether `-PLOT` or `-EXPORT` writes a non-empty PDF with no dialog |
| `unicode.lsp` | `č š ž` round trip in file paths, layer names and text through `open`/`read-line`/`write-line`, with and without an explicit encoding |
| `idle_cpu` | CPU use of the poll loop over 30 seconds, using `psutil` from the runner |
| `blocking` | Manual note from the user: whether the window is usable while listening |

Also record which `vle-getboundingbox` and `vle-file-encoding` forms work, as Tasks 5 and 9 use them.

Expected: every question has an observed answer. A probe that is `BLOCKED` is an answer, not a failure of the task.

- [ ] **Step 3: Write `docs/phase-0-results.md`**

For each probe: question, what was observed, exact working sequence, and which spec fallback applies.

- [ ] **Step 4: Stop and report if a result changes the design**

If drawings cannot switch without losing the listener, or a read-only open is impossible, stop and raise it before Task 2. Otherwise, continue.

- [ ] **Step 5: Commit**

```bash
git add scripts/phase0 docs/phase-0-results.md
git commit -m "test: record Phase 0 probe results"
```

---

### Task 2: Project scaffold, LISP generation and CI

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `README.md`, `.github/workflows/ci.yml`, `src/bricscad_mcp/__init__.py`, `src/bricscad_mcp/errors.py`, `src/bricscad_mcp/lispgen.py`
- Test: `tests/test_lispgen.py`

**Interfaces:**
- Produces:
  - `lispgen.lisp_str(value: str) -> str`
  - `lispgen.lisp_path(path: str | Path) -> str` (absolute, forward slashes, escaped)
  - `lispgen.lisp_value(value: str | int | float | bool | None | list) -> str`
  - `lispgen.call(fn: str, *args) -> str`, for example `call("mcp:list-layers", 0, 200)`
  - `errors.BricsCADError`, with subclasses `BridgeTimeout`, `LispError`, `ProcessDied`, `NotRunning`, `SafetyRefused`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("raw,expected", [
    ('plain', '"plain"'),
    ('a"b', '"a\\"b"'),
    ('a\\b', '"a\\\\b"'),
    ('line1\nline2', '"line1\\nline2"'),
    ('čšž', '"čšž"'),
])
def test_lisp_str_escapes(raw, expected):
    assert lisp_str(raw) == expected

def test_lisp_path_uses_forward_slashes():
    assert lisp_path(PureWindowsPath(r"C:\Temp\Načrt 1.dwg")) == '"C:/Temp/Načrt 1.dwg"'

def test_lisp_value_maps_python_types():
    assert lisp_value(True) == "T"
    assert lisp_value(None) == "nil"
    assert lisp_value([1, "a"]) == '(list 1 "a")'

def test_call_rejects_an_unsafe_function_name():
    with pytest.raises(ValueError):
        call('(startapp "x")')
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_lispgen.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Write the scaffold and `lispgen.py`**

`pyproject.toml` declares `mcp`, `psutil`, `platformdirs`, a `bricscad-mcp` console script, the `bricscad` pytest marker, and `addopts = "-m 'not bricscad'"`. `call` accepts only names matching `^[A-Za-z_:\-][\w:\-]*$`. `.gitignore` covers `.venv`, caches and `*.bak`, `*.dwl*`.

CI runs `uv run pytest` on `macos-latest`, `windows-latest` and `ubuntu-latest`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_lispgen.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore README.md .github src tests uv.lock
git commit -m "feat: add project scaffold and LISP generation"
```

---

### Task 3: Platform modules

**Files:**
- Create: `src/bricscad_mcp/platforms/__init__.py`, `base.py`, `macos.py`, `windows.py`, `linux.py`
- Test: `tests/test_platforms.py`

**Interfaces:**
- Produces:
  - `Installation(version: str, executable: Path)`, frozen dataclass; `version` such as `"26"`
  - `Platform.find_installations(self, root: Path | None = None) -> list[Installation]`, newest first
  - `Platform.launch_command(self, inst: Installation, script: Path) -> list[str]`
  - `Platform.start(self, inst: Installation, script: Path) -> int`, returns the PID
  - `Platform.state_dir(self) -> Path`
  - `base.is_alive(pid: int) -> bool`, `base.terminate(pid: int) -> None`, both using `psutil`
  - `platforms.get_platform(name: str | None = None) -> Platform`
  - `platforms.select_installation(platform, version=None) -> Installation`, which honours `BRICSCAD_EXECUTABLE` and `BRICSCAD_VERSION`

- [ ] **Step 1: Write the failing tests**

```python
def test_macos_finds_versions_newest_first(tmp_path):
    (tmp_path / "BricsCAD V25.app").mkdir()
    (tmp_path / "BricsCAD V26.app").mkdir()
    assert [i.version for i in MacOS().find_installations(tmp_path)] == ["26", "25"]

def test_windows_finds_exe(tmp_path):
    d = tmp_path / "BricsCAD V26 en_US"; d.mkdir(); (d / "bricscad.exe").touch()
    assert Windows().find_installations(tmp_path)[0].version == "26"

def test_linux_finds_launcher(tmp_path):
    d = tmp_path / "v26"; d.mkdir(); (d / "bricscad.sh").touch()
    assert Linux().find_installations(tmp_path)[0].version == "26"

def test_launch_commands():
    s = Path("/q/boot.lsp")
    assert MacOS().launch_command(Installation("26", Path("/Applications/BricsCAD V26.app")), s) == \
        ["open", "-n", "-a", "/Applications/BricsCAD V26.app", "--args", "-b", "/q/boot.lsp"]
    assert Windows().launch_command(Installation("26", Path("b.exe")), s)[1] == "/B"
    assert Linux().launch_command(Installation("26", Path("b.sh")), s)[1] == "-b"

def test_env_overrides(monkeypatch, tmp_path):
    exe = tmp_path / "custom"; exe.touch()
    monkeypatch.setenv("BRICSCAD_EXECUTABLE", str(exe))
    assert select_installation(MacOS()).executable == exe

def test_select_missing_version_lists_found(tmp_path, monkeypatch):
    with pytest.raises(BricsCADError, match="25"):
        select_installation(FakeOnly25(), version="99")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_platforms.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement the modules**

`macos.start` uses `open`, which does not return the app's PID. It records `psutil` PIDs whose `exe()` lies in the bundle before launch, then waits up to 30 seconds for a new one. `windows` and `linux` use `subprocess.Popen(...).pid`. Discovery patterns come from the spec's Platform support section, and `state_dir` from `platformdirs.user_state_path("bricscad-mcp")`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_platforms.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bricscad_mcp/platforms tests/test_platforms.py
git commit -m "feat: add platform discovery and launching"
```

---

### Task 4: Bridge and fake listener

**Files:**
- Create: `src/bricscad_mcp/bridge.py`, `tests/fake_listener.py`
- Test: `tests/test_bridge.py`

**Interfaces:**
- Consumes: `errors.*` from Task 2.
- Produces:
  - `Bridge(queue_dir: Path, alive_check: Callable[[], bool] = lambda: True, poll_interval: float = 0.05)`
  - `Bridge.send(self, expr: str, timeout: float = 30.0) -> Any`, returning `result` or raising `LispError`, `BridgeTimeout`, `ProcessDied`
  - `Bridge.heartbeat_age(self) -> float | None`
  - `Bridge.touch_alive(self) -> None`, which refreshes `server.alive` for the listener
  - `Bridge.expire_alive_for_test(self) -> None`, which back-dates `server.alive` by 1 hour
  - `Bridge.queue_dir -> Path`
  - `fake_listener.FakeListener(queue_dir, handler: Callable[[str], dict])`, a context manager running a thread that follows the protocol

- [ ] **Step 1: Write the failing tests**

```python
def test_round_trip(queue):
    with FakeListener(queue, lambda e: {"ok": True, "result": {"echo": e}}):
        assert Bridge(queue).send("(+ 1 1)") == {"echo": "(+ 1 1)"}

def test_files_are_removed_after_reply(queue):
    with FakeListener(queue, lambda e: {"ok": True, "result": 1}):
        Bridge(queue).send("x")
    assert list(queue.glob("*.lsp")) == [] and list(queue.glob("*.json")) == []

def test_lisp_error_is_raised(queue):
    with FakeListener(queue, lambda e: {"ok": False, "error": "bad"}):
        with pytest.raises(LispError, match="bad"):
            Bridge(queue).send("x")

def test_timeout_mentions_dialog_and_removes_unclaimed_request(queue):
    with pytest.raises(BridgeTimeout, match="dialog"):
        Bridge(queue).send("x", timeout=0.2)
    assert list(queue.glob("*.lsp")) == []

def test_process_death_fails_fast(queue):
    start = time.monotonic()
    with pytest.raises(ProcessDied):
        Bridge(queue, alive_check=lambda: False).send("x", timeout=30)
    assert time.monotonic() - start < 2

def test_late_reply_to_a_timed_out_request_is_discarded(queue):
    b = Bridge(queue)
    with pytest.raises(BridgeTimeout):
        b.send("first", timeout=0.1)
    (queue / "stale-id.json").write_text('{"id":"stale-id","ok":true,"result":1}')
    with FakeListener(queue, lambda e: {"ok": True, "result": 2}):
        assert b.send("second") == 2

def test_request_file_is_never_seen_partial(queue):
    # The fake listener fails on any .lsp that is not complete.
    with FakeListener(queue, lambda e: {"ok": e == "x" * 100000, "result": 1}):
        assert Bridge(queue).send("x" * 100000) == 1

def test_non_ascii_round_trip(queue):
    with FakeListener(queue, lambda e: {"ok": True, "result": e}):
        assert Bridge(queue).send("Načrt čšž") == "Načrt čšž"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_bridge.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `bridge.py` and `fake_listener.py`**

Request ids use `uuid4().hex`. Write `<id>.tmp`, then `os.replace` to `<id>.lsp`. Use the encoding from `docs/phase-0-results.md` for request and reply files. Check `alive_check` on every poll. On timeout, remove the `.lsp` if present and include the heartbeat age in the message. Serialise `send` with a lock. Delete stale `.json` files whose id is not the current one.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_bridge.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bricscad_mcp/bridge.py tests/fake_listener.py tests/test_bridge.py
git commit -m "feat: add file queue bridge"
```

---

### Task 5: LISP listener and JSON encoder

**Files:**
- Create: `src/bricscad_mcp/lisp/json.lsp`, `src/bricscad_mcp/lisp/listener.lsp`, `tests/real/conftest.py`
- Test: `tests/real/test_listener.py`

**Interfaces:**
- Consumes: `Bridge` from Task 4; Phase 0 file encoding.
- Produces, in LISP:
  - `(mcp:obj '(("k" . v) ...))` and `(mcp:arr lst)` tagged constructors
  - `(mcp:json v)`, where strings, numbers, `T` to `true`, `nil` to `null`, and tagged values encode to JSON text
  - `(mcp:listen queue-dir)`, the blocking poll loop
  - `(mcp:with-vars pairs expr-string)`, which sets variables, evaluates the expression and always restores them; every tool that changes a variable uses it
- Produces, in pytest: `real_session` fixture (a running `Session` on a blank drawing) and `blank_drawing` fixture

The reply is `{"id","ok","result","error","elapsed_ms"}` as specified.

The listener exits its loop and leaves the command line free when `quit.flag` appears, or when `server.alive` is older than 120 seconds. It does not close BricsCAD itself in that case, so unsaved work survives.

- [ ] **Step 1: Write the failing real tests**

```python
@pytest.mark.bricscad
@pytest.mark.parametrize("text", ['a"b', "a\\b", "line1\nline2", "čšž", "tab\there"])
def test_json_round_trips_text(real_session, text):
    assert real_session.bridge.send(lisp_value(text)) == text

@pytest.mark.bricscad
def test_listener_survives_a_lisp_error(real_session):
    with pytest.raises(LispError):
        real_session.bridge.send("(car 1)")
    assert real_session.bridge.send("(+ 1 1)") == 2

@pytest.mark.bricscad
def test_variable_is_restored_after_an_error_in_a_request(real_session):
    before = real_session.bridge.send('(getvar "OSMODE")')
    with pytest.raises(LispError):
        real_session.bridge.send(call("mcp:with-vars", [["OSMODE", 0]], "(car 1)"))
    assert real_session.bridge.send('(getvar "OSMODE")') == before

@pytest.mark.bricscad
def test_heartbeat_advances(real_session):
    a = real_session.bridge.heartbeat_age(); time.sleep(1.5)
    assert real_session.bridge.heartbeat_age() < 2 and a is not None

@pytest.mark.bricscad
def test_listener_stops_when_the_server_goes_quiet(real_session):
    real_session.bridge.expire_alive_for_test()
    wait_until(lambda: real_session.bridge.heartbeat_age() > 3, timeout=10)
    assert is_alive(real_session.pid)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest -m bricscad tests/real/test_listener.py -v`
Expected: FAIL; fixtures depend on Task 6, so write Tasks 5 and 6 together and run this after Task 6, Step 3.

- [ ] **Step 3: Implement `json.lsp` and `listener.lsp`**

Each request runs under `vl-catch-all-apply` and a `*error*` handler that restores variables. Poll with `(command "_.DELAY" 250)`, or the interval Phase 0 chose. Update the heartbeat on each poll, and pick up requests oldest first by file name order with a time prefix.

- [ ] **Step 4: Commit with Task 6**

---

### Task 6: Session lifecycle

**Files:**
- Create: `src/bricscad_mcp/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `Platform`, `select_installation`, `is_alive`, `terminate` from Task 3; `Bridge` from Task 4; LISP from Task 5.
- Produces:
  - `Session(platform: Platform, base_dir: Path | None = None)`
  - `Session.start(self, version: str | None = None, timeout: float = 120.0) -> dict`
  - `Session.stop(self, discard: bool = False) -> dict`
  - `Session.status(self) -> dict`, with keys `running`, `pid`, `version`, `heartbeat_age`, `drawing`
  - `Session.bridge -> Bridge`, `Session.pid -> int | None`
  - `Session.require_bridge(self) -> Bridge`, raising `NotRunning` or `ProcessDied`

- [ ] **Step 1: Write the failing tests**

Use a `FakePlatform` whose `start` launches `FakeListener` and returns the test's own PID stand-in.

```python
def test_start_creates_owner_only_new_queue(session):
    session.start()
    q = session.bridge.queue_dir
    assert q.is_dir()
    if os.name == "posix":
        assert stat.S_IMODE(q.stat().st_mode) == 0o700

def test_each_session_gets_a_new_folder(session_factory):
    a, b = session_factory(), session_factory()
    a.start(); b.start()
    assert a.bridge.queue_dir != b.bridge.queue_dir

def test_second_start_refuses_while_running(session):
    session.start()
    with pytest.raises(BricsCADError, match="already"):
        session.start()

def test_stop_refuses_on_unsaved_changes(session, fake):
    fake.dbmod = 1; session.start()
    with pytest.raises(SafetyRefused, match="discard=true"):
        session.stop()

def test_stop_terminates_only_its_own_pid(session, fake, monkeypatch):
    killed = []; monkeypatch.setattr("bricscad_mcp.session.terminate", killed.append)
    session.start(); fake.ignore_quit = True; session.stop(discard=True)
    assert killed == [fake.pid]

def test_require_bridge_when_not_started(session):
    with pytest.raises(NotRunning, match="bricscad_start"):
        session.require_bridge()

def test_process_exit_is_reported(session, fake):
    session.start(); fake.die()
    with pytest.raises(ProcessDied):
        session.require_bridge()

def test_start_times_out_with_guidance(session, fake):
    fake.never_ready = True
    with pytest.raises(BridgeTimeout, match="dialog"):
        session.start(timeout=0.3)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_session.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `session.py`**

`start` makes `<state_dir>/sessions/<uuid>` with mode `0700`, writes a `bootstrap.lsp` that loads the packaged LISP and calls `mcp:listen`, launches, and waits for the first heartbeat. A daemon thread calls `touch_alive` every 30 seconds. `stop` writes `quit.flag` and the listener quits BricsCAD once `DBMOD` is 0, or with `_.QUIT _Y` when `discard=true`. If the PID is still alive after 15 seconds, `terminate` it. `atexit` writes `quit.flag`. Old session folders with no live process are removed on start.

- [ ] **Step 4: Run all tests, including Task 5 real tests**

Run: `uv run pytest tests/test_session.py -v && uv run pytest -m bricscad tests/real/test_listener.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bricscad_mcp/session.py src/bricscad_mcp/lisp tests/test_session.py tests/real
git commit -m "feat: add LISP listener and session lifecycle"
```

---

### Task 7: MCP server and core tools

**Files:**
- Create: `src/bricscad_mcp/server.py`, `src/bricscad_mcp/tools/__init__.py`, `tools/core.py`
- Test: `tests/test_tools_core.py`

**Interfaces:**
- Consumes: `Session`, `get_platform`.
- Produces:
  - `server.mcp: FastMCP`, `server.main() -> None`, `server.session() -> Session`
  - `tools.page_args(limit: int, offset: int) -> tuple[int, int]`, which clamps `limit` to 1..2000 and `offset` to 0 or more
  - Tools: `bricscad_list_versions`, `bricscad_start(version?)`, `bricscad_stop(discard=False)`, `bricscad_status`, `bricscad_run_lisp(code, timeout=30)`
  - Pattern for later tasks: each tool module registers on `server.mcp`, and `BricsCADError` becomes an MCP tool error carrying the message

- [ ] **Step 1: Write the failing tests**

Use `mcp.shared.memory.create_connected_server_and_client_session` with `FakePlatform`.

```python
async def test_tools_are_listed_with_annotations(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert tools["bricscad_status"].annotations.readOnlyHint is True
    assert tools["bricscad_run_lisp"].annotations.destructiveHint is True
    assert all(n.startswith("bricscad_") for n in tools)

async def test_status_before_start(client):
    r = await client.call_tool("bricscad_status", {})
    assert r.structuredContent["running"] is False

async def test_run_lisp_without_session_gives_guidance(client):
    r = await client.call_tool("bricscad_run_lisp", {"code": "(+ 1 1)"})
    assert r.isError and "bricscad_start" in r.content[0].text

async def test_page_args_clamp():
    assert page_args(99999, -5) == (2000, 0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_tools_core.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `server.py` and `tools/core.py`**

Each tool returns a dict for structured output. Annotations: `status` and `list_versions` read-only; `run_lisp` and `stop` destructive.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_tools_core.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bricscad_mcp/server.py src/bricscad_mcp/tools tests/test_tools_core.py
git commit -m "feat: add MCP server and core tools"
```

---

### Task 8: Drawing tools

**Files:**
- Create: `src/bricscad_mcp/tools/drawing.py`, additions to `src/bricscad_mcp/lisp/read.lsp`
- Test: `tests/test_tools_drawing.py`, `tests/real/test_drawing.py`

**Interfaces:**
- Consumes: `Session.require_bridge`, `lisp_path`; working sequences from `docs/phase-0-results.md`.
- Produces: `bricscad_open_drawing(path, read_only=True)`, `bricscad_close_drawing(discard=False)`, `bricscad_drawing_info`. Info keys: `name`, `path`, `read_only`, `modified`, `units`, `limits`, `extents`, `entity_count`, `layouts`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_open_missing_file_never_reaches_bricscad(client, fake):
    r = await client.call_tool("bricscad_open_drawing", {"path": "/nope/x.dwg"})
    assert r.isError and "not found" in r.content[0].text and fake.requests == []

async def test_open_folder_is_refused(client, fake, tmp_path):
    r = await client.call_tool("bricscad_open_drawing", {"path": str(tmp_path)})
    assert r.isError and fake.requests == []

async def test_open_non_dwg_is_refused(client, fake, tmp_path):
    p = tmp_path / "x.txt"; p.write_text("hi")
    r = await client.call_tool("bricscad_open_drawing", {"path": str(p)})
    assert r.isError and fake.requests == []

async def test_open_defaults_to_read_only(client, fake, dwg):
    await client.call_tool("bricscad_open_drawing", {"path": str(dwg)})
    assert fake.requests[-1].startswith("(mcp:open-drawing ") and fake.requests[-1].endswith(" T)")

async def test_close_with_unsaved_changes_refuses(client, fake):
    fake.dbmod = 1
    r = await client.call_tool("bricscad_close_drawing", {})
    assert r.isError and "discard=true" in r.content[0].text

@pytest.mark.bricscad
def test_open_read_only_leaves_the_file_unchanged(real_session, sample_dwg):
    before = sample_dwg.read_bytes()
    open_and_close(real_session, sample_dwg)
    assert sample_dwg.read_bytes() == before

@pytest.mark.bricscad
def test_open_path_with_slovene_characters_and_spaces(real_session, tmp_path):
    p = make_dwg(real_session, tmp_path / "Načrt št 1.dwg")
    assert info_after_open(real_session, p)["name"] == "Načrt št 1.dwg"

@pytest.mark.bricscad
def test_listener_answers_after_open(real_session, sample_dwg):
    open_and_close(real_session, sample_dwg)
    assert real_session.bridge.send("(+ 1 1)") == 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_tools_drawing.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Check existence and that the file starts with the `AC10` DWG signature, or is a `.dxf`, in Python before sending anything.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_tools_drawing.py -v && uv run pytest -m bricscad tests/real/test_drawing.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bricscad_mcp/tools/drawing.py src/bricscad_mcp/lisp/read.lsp tests
git commit -m "feat: add open, close and drawing info tools"
```

---

### Task 9: Read tools

**Files:**
- Create: `src/bricscad_mcp/tools/read.py`; extend `src/bricscad_mcp/lisp/read.lsp`
- Test: `tests/test_tools_read.py`, `tests/real/test_read.py`

**Interfaces:**
- Consumes: `page_args`, `lispgen.call`.
- Produces tools, all read-only and returning `{items, total, limit, offset}` where they list:
  - `bricscad_list_layers` items: `name, on, frozen, locked, color, linetype, entity_count`
  - `bricscad_list_blocks` items: `name, insert_count, entity_count, is_xref, is_anonymous` (anonymous excluded unless `include_anonymous=true`)
  - `bricscad_list_xrefs` items: `name, path, resolved`
  - `bricscad_list_layouts` items: `name, entity_count, is_model`
  - `bricscad_query_entities(types?, layer?, block?, bbox?, layout?, limit, offset)` items: `handle, type, layer, layout, bbox`
  - `bricscad_get_entity(handle)` returns type, layer and all DXF pairs as `[code, value]`
  - `bricscad_read_attributes(block?, layout?, limit, offset)` items: `handle, block, layout, attributes: {tag: value}`
  - `bricscad_find_text(query, case_sensitive=False, limit, offset)` items: `handle, type, text, layer, layout, position`

- [ ] **Step 1: Write the failing tests**

Fake-listener tests assert the LISP call and paging. The behaviour tests run on the real app:

```python
@pytest.mark.bricscad
def test_empty_drawing_returns_empty_lists(real_session):
    r = query(real_session)
    assert r["items"] == [] and r["total"] == 0

@pytest.mark.bricscad
def test_filter_with_no_match_returns_empty(real_session, populated):
    assert query(real_session, types=["ARC"], layer="NO_SUCH")["total"] == 0

@pytest.mark.bricscad
def test_query_pages_cover_every_entity(real_session, large):  # 5000 lines
    a = query(real_session, limit=2000, offset=0)
    b = query(real_session, limit=2000, offset=2000)
    c = query(real_session, limit=2000, offset=4000)
    assert a["total"] == 5000
    assert len({e["handle"] for e in a["items"] + b["items"] + c["items"]}) == 5000

@pytest.mark.bricscad
def test_bbox_filter(real_session, populated):
    assert handles(query(real_session, bbox=[0, 0, 10, 10])) == populated.inside_handles

@pytest.mark.bricscad
def test_reads_title_block_attributes_with_slovene_text(real_session, titled):
    assert read_attrs(real_session)["items"][0]["attributes"]["NASLOV"] == "Načrt št. 1"

@pytest.mark.bricscad
def test_find_text_handles_quotes_and_newlines_in_content(real_session, texty):
    r = find(real_session, 'a"b')
    assert r["items"][0]["text"] == 'a"b\nc'

@pytest.mark.bricscad
def test_entities_in_paper_space_report_their_layout(real_session, papered):
    assert query(real_session, layout="Layout1")["items"][0]["layout"] == "Layout1"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_tools_read.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Page in LISP so large drawings are not serialised whole: `ssget "_X"` with a filter list for type, layer, block and layout, guard against `nil`, then walk from `offset` to `offset + limit`. Apply `bbox` in LISP with the bounding-box form Phase 0 confirmed; with a `bbox`, `total` counts matches after the filter. Fixtures build drawings by `entmakex` through the bridge and save with `_.SAVEAS` to a temp folder.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_tools_read.py -v && uv run pytest -m bricscad tests/real/test_read.py -v`
Expected: PASS, and the 5000-entity page each returns inside the 30-second timeout.

- [ ] **Step 5: Commit**

```bash
git add src/bricscad_mcp/tools/read.py src/bricscad_mcp/lisp/read.lsp tests
git commit -m "feat: add layer, block, entity, attribute and text read tools"
```

---

### Task 10: Audit report

**Files:**
- Create: `src/bricscad_mcp/tools/audit.py`, `src/bricscad_mcp/lisp/audit.lsp`
- Test: `tests/test_tools_audit.py`, `tests/real/test_audit.py`

**Interfaces:**
- Consumes: read tools' LISP helpers.
- Produces: `bricscad_audit_report(allowed_layers: list[str] | None = None, sample_limit: int = 50)`, read-only. Returns one section each for `empty_layers`, `unused_blocks`, `missing_xrefs`, `non_zero_elevation`, `off_standard_layers`. Each section is `{count, items}`, with `items` capped at `sample_limit`. `off_standard_layers` is `null` when `allowed_layers` is omitted. Entries in `allowed_layers` are `wcmatch` patterns.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.bricscad
def test_clean_drawing_reports_nothing(real_session):
    r = audit(real_session)
    assert r["empty_layers"]["count"] == 0 and r["unused_blocks"]["count"] == 0

@pytest.mark.bricscad
def test_finds_each_problem(real_session, dirty):
    r = audit(real_session, allowed_layers=["A-*"])
    assert "EMPTY" in r["empty_layers"]["items"]
    assert "UNUSED" in r["unused_blocks"]["items"]
    assert "MISSING" in names(r["missing_xrefs"]["items"])
    assert dirty.raised_handle in handles(r["non_zero_elevation"]["items"])
    assert "BAD" in r["off_standard_layers"]["items"]

@pytest.mark.bricscad
def test_layer_zero_and_defpoints_are_not_reported_empty(real_session):
    items = audit(real_session)["empty_layers"]["items"]
    assert "0" not in items and "DEFPOINTS" not in [i.upper() for i in items]

@pytest.mark.bricscad
def test_sample_limit_caps_items_but_not_count(real_session, many_empty):  # 100 layers
    s = audit(real_session, sample_limit=5)["empty_layers"]
    assert s["count"] == 100 and len(s["items"]) == 5
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest -m bricscad tests/real/test_audit.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `audit.lsp` and `tools/audit.py`**

Xref state comes from block table group 70 bits and a file check on the stored path. Entity elevation comes from the group 38 value or the Z of group 10.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_tools_audit.py -v && uv run pytest -m bricscad tests/real/test_audit.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bricscad_mcp/tools/audit.py src/bricscad_mcp/lisp/audit.lsp tests
git commit -m "feat: add audit report tool"
```

---

### Task 11: End-to-end check and README

**Files:**
- Create: `tests/real/test_end_to_end.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the end-to-end test**

`test_stdio_server_full_read_flow(tmp_path)`, marked `bricscad`, launches `bricscad-mcp` over stdio with the real MCP client and calls `bricscad_start`, `bricscad_open_drawing` on a temp drawing, `bricscad_list_layers`, `bricscad_query_entities`, `bricscad_audit_report` and `bricscad_stop`. It asserts that:

- no call has `isError` set
- the started PID no longer exists at the end
- the temp drawing's bytes are unchanged
- no new `Drawing1*` file appears in the user's Downloads or Documents folders

- [ ] **Step 2: Run the whole test set**

Run: `uv run pytest -v && uv run pytest -m bricscad -v`
Expected: PASS on macOS V26. Then confirm that GitHub Actions passes on all three operating systems.

- [ ] **Step 3: Write the README**

Include the platform status table copied from the spec, install steps, registration with `claude mcp add bricscad -- uv --directory "<path>" run bricscad-mcp`, the environment variables, safety rules, the note that the BricsCAD window is occupied while listening, and how to run the real tests to promote Windows or Linux.

- [ ] **Step 4: Commit**

```bash
git add README.md tests/real/test_end_to_end.py
git commit -m "docs: add README and end-to-end test"
```
