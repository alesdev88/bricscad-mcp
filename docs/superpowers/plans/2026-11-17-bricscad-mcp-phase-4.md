# BricsCAD MCP Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `bricscad_batch_run`, which applies one job to many drawings: `audit`, `find_text`, `export_dxf`, `plot_pdf`, `save_as` or LISP code, with a dry run, a result per file, and outputs in a separate folder.

**Architecture:** Python owns the batch. It lists the sources, plans every output and refuses what it must before BricsCAD is involved, then sends one request per file. That request, `mcp:batch-file`, opens the drawing read-only, runs one LISP worker and closes it without saving, so a file costs one round trip and a source is never written by BricsCAD. Every output, including a saved DWG, is written to a temporary name and moved into place by Python, reusing Phase 3's `write_through_temporary`. That covers replacing a source too (`overwrite=true`). A failed file is reported and the batch goes on; a timeout or a dead process stops it.

**Tech Stack:** Python 3.11+, MCP SDK 2.x, Pydantic job models, AutoLISP, pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-bricscad-mcp-design.md`, section "Phase 4: batch" and safety rule 3. Builds on Phase 3 (`tools/export.py`, `lisp/export.lsp`), so this branch starts from `feat/phase-3-plot-export`. Probe results: `docs/phase-0-results.md`, sections "Found while planning Phase 3" (last rows) and "Found while planning Phase 4".

## Global Constraints

- `bricscad_batch_run` never writes to its source files unless `overwrite=true`, and writes to an output folder by default.
- It has a dry-run option, a result per file, and continues after a failure.
- Saving over an existing file requires `overwrite=true`, checked before anything is sent to BricsCAD.
- File paths go through `lispgen`. LISP job code is passed as a string and read with `read`, never spliced into other LISP.
- Only `_.SAVEAS` saves here. Drawings close with `vla-close`, never `_.CLOSE`.
- Tests use temporary drawings only, with at most one BricsCAD per version.

## Jobs (chosen by Aleš, 17.11.2026)

`job` is one of these Pydantic models, discriminated by `type`, in the `Strict` style of `tools/shapes.py`:

| `type` | Fields | Writes | Per-file `result` |
|---|---|---|---|
| `audit` | `allowed_layers: list[str] \| None = None`, `sample_limit: int = 10` (0 to 2000) | nothing | the audit report |
| `find_text` | `query: str` (min length 1), `case_sensitive: bool = False`, `limit: int = 50` (1 to 2000) | nothing | the `find_text` page |
| `export_dxf` | `version: DxfVersion = "2018"` | `<stem>.dxf` | none |
| `plot_pdf` | `layout`, `paper`, `landscape`, `area`, `window`, `scale`, `style_table` as in `plot_pdf`; `layout="*"` means every sheet | `<stem>.pdf`, or `<stem>-<sheet>.pdf` per sheet | the layout names plotted |
| `save_as` | none | `<stem>.dwg` | none |
| `lisp` | `code: str` (min length 1), `save: bool = False` | `<stem>.dwg` when `save` | the value of the code |

In `<stem>-<sheet>.pdf`, each of `<>:"/\|?*` in the sheet name becomes `_`.

## Result

```
{"dry_run": bool, "total": int, "succeeded": int, "failed": int, "refused": int, "not_run": int,
 "stopped": str | None, "current_drawing": str | None,
 "files": [{"source": str, "status": "planned" | "ok" | "failed" | "refused" | "not_run",
            "outputs": [str], "result": Any, "error": str | None}]}
```

`current_drawing` is `None` on a dry run. After a run it is BricsCAD's current drawing, which may differ from before: `vla-activate` cannot switch back (see the probe results).

## Review Focus

1. A source already open in BricsCAD is refused for that file and stays open; closing it would lose the user's work. Tests: Task 1.
2. Two sources whose outputs share a name, such as the same stem in two folders, refuse the whole batch before anything runs. Tests: Task 1.
3. A timeout stops the batch; the rest are `not_run`, not `failed`. Tests: Task 1.
4. With `overwrite=true` and the output folder equal to the source folder, `save_as` and `lisp` with `save=true` replace the source only once the new file is complete; without `overwrite`, each such file is `refused` and unchanged. Tests: Tasks 2, 3.
5. LISP code that is unbalanced, raises, leaves a command waiting or closes the drawing fails that file only; the next file still runs. Tests: Task 3.

---

## File structure

| File | Responsibility |
|---|---|
| `src/bricscad_mcp/tools/batch.py` (new) | Job models, source listing, planning, the run loop, the tool |
| `src/bricscad_mcp/lisp/batch.lsp` (new) | `mcp:batch-file` and the job workers not already in other files |
| `src/bricscad_mcp/server.py` | Add `batch` to the tool import |
| `tests/test_tools_batch.py` (new), `tests/real/test_batch.py` (new) | Fast and real tests |
| `tests/test_stdio.py`, `manifest.json`, `README.md`, `docs/phase-0-results.md` | Tool name, docs, probe rows |

Annotation: `DESTRUCTIVE`.

---

### Task 1: The batch loop, dry run, and the read-only jobs

**Files:** Create `tools/batch.py`, `lisp/batch.lsp`, both test files. Modify `server.py`, `tests/test_stdio.py`, `manifest.json`, `docs/phase-0-results.md` (add "Found while planning Phase 4, 17.11.2026": a truncated or scrambled DWG makes `vla-open` fail with `Automation Error E_FAIL` and no dialog; open, edit, `_.SAVEAS` to another folder and `vla-close` in one request works, also with `č š ž` in the name).

**Interfaces:**
- Consumes: `check_drawing_file` (tools/drawing.py), `is_same_file` (tools/edit.py), LISP `mcp:audit-report (patterns sample-limit)`, `mcp:find-text (query case-sensitive limit offset)`, `mcp:save-state`, `mcp:cancel-command`, `mcp:fail`.
- Produces:
  - `MAX_FILES = 500`.
  - `list_sources(files: list[str] | None, folder: str | None, pattern: str = "*.dwg", recursive: bool = False) -> list[Path]`. Exactly one of `files` and `folder`, else `BricsCADError`. `folder` uses `glob`, or `rglob` with `recursive`; only files, sorted by path. Each goes through `check_drawing_file`, and the first bad one refuses the batch, naming it. The same file twice, by `is_same_file`, is listed once. None found, or more than `MAX_FILES`, is a `BricsCADError`.
  - `FilePlan` dataclass: `source: Path`, `target: Path | None`, `refused: str | None`.
  - `plan(sources: list[Path], job: Job, output_folder: str | None, overwrite: bool) -> list[FilePlan]`. Jobs that write need `output_folder`, an existing folder that can be written to; read-only jobs refuse one. The target is `output_folder / (source.stem + suffix)`, with `None` for read-only jobs and for `plot_pdf` with `layout="*"`. Two sources with the same target refuse the batch, naming both. A target that exists without `overwrite` gives that file `refused` with the `overwrite=true` hint.
  - LISP `(mcp:batch-file path worker args)`: `worker` is a function name as a string beginning `mcp:`. It opens `path` with `vla-open` read-only; an open error fails with `"BricsCAD could not open <path>: <message>"`. It applies `(read worker)` to `args` under `vl-catch-all-apply`, runs `mcp:cancel-command`, closes the document with `vla-close :vlax-false` under `vl-catch-all-apply`, then returns the result or re-raises the error.
  - `batch_run(bridge: Bridge | None, job: Job, files=None, folder=None, pattern="*.dwg", recursive=False, output_folder=None, overwrite=False, dry_run=False, timeout=120.0) -> dict` returning the Result above. A dry run needs no bridge and sends nothing. A run reads `mcp:save-state` once and refuses, per file, a source that is the current drawing or in `other_open`. `BridgeTimeout` or `ProcessDied` fails that file, sets `stopped` to its message, and marks the rest `not_run`. Any other `BricsCADError` fails that file only. At the end it reads `(getvar "DWGNAME")` for `current_drawing`.

- [ ] **Step 1: Write the failing fast tests** (`tests/test_tools_batch.py`, fake listener, drawings made as files with an `AC1032` header):

```python
async def test_dry_run_plans_without_sending(client, fake, tmp_path): ...  # no bricscad_start needed; statuses "planned"; fake.requests == []
async def test_folder_pattern_and_recursive(client, fake, tmp_path): ...  # *.dwg in a/ and a/sub/; recursive lists both, sorted
@pytest.mark.parametrize("args", [{}, {"files": ["x"], "folder": "y"}, {"folder": "<empty dir>"}])
async def test_bad_source_choices_refuse_the_batch(...): ...
async def test_a_file_that_is_not_a_drawing_refuses_the_batch(...): ...
async def test_more_than_500_files_refuses_the_batch(...): ...
async def test_same_output_name_from_two_folders_refuses_the_batch(...): ...  # export_dxf, a/x.dwg and b/x.dwg
async def test_writing_jobs_need_an_output_folder_and_read_jobs_refuse_one(...): ...
async def test_an_open_source_is_refused_and_not_sent(...): ...  # save-state other_open holds it; no mcp:batch-file for it
async def test_a_failed_file_does_not_stop_the_batch(...): ...  # second of three returns an error; statuses ok, failed, ok
async def test_a_timeout_stops_the_batch(...): ...  # fake.delay on the second file > timeout; statuses ok, failed, not_run; stopped set
async def test_audit_and_find_text_send_their_workers(...): ...  # (mcp:batch-file "<path>" "mcp:audit-report" (list nil 10)) and "mcp:find-text" (list "Soba" nil 50 0)
```

- [ ] **Step 2: Write the failing real tests** (`tests/real/test_batch.py`; a fixture saves three temporary drawings, one with the text `Soba`, into `tmp_path / "src"`):

```python
def test_find_text_across_files(real_session, sources): ...  # one file with total 1, two with 0; every source's digest unchanged
def test_audit_across_files_leaves_the_current_drawing_open(real_session, blank, sources): ...  # document count before == after
def test_a_damaged_file_fails_and_the_rest_run(real_session, sources): ...  # a truncated copy fails with "could not open"; others ok
def test_an_open_source_is_refused(real_session, sources): ...  # open one with open_drawing first; it stays open
```

- [ ] **Step 3: Run both and see them fail** with `uv run pytest tests/test_tools_batch.py -v` and `uv run pytest -m bricscad tests/real/test_batch.py -v`. Expected: FAIL, no module `bricscad_mcp.tools.batch`.

- [ ] **Step 4: Implement** as in Interfaces, with the tool `bricscad_batch_run(job: Job, files=None, folder=None, pattern="*.dwg", recursive=False, output_folder=None, overwrite=False, dry_run=False, timeout=120.0)` registered under `DESTRUCTIVE`, and its name in `tests/test_stdio.py` and `manifest.json`. The docstring states: one job across files; sources are opened read-only and never written unless `overwrite=true`; outputs go to `output_folder`; use `dry_run` first; a timeout stops the batch; up to 500 files; the current drawing afterwards may be another open drawing.

- [ ] **Step 5: Run the tests and see them pass**: `uv run pytest`, then `uv run pytest -m bricscad tests/real/test_batch.py`. Expected: all pass.

- [ ] **Step 6: Commit** `feat: add bricscad_batch_run with audit and find_text`.

---

### Task 2: Writing jobs: `export_dxf`, `plot_pdf`, `save_as`

**Interfaces:**
- Consumes: `write_through_temporary`, `check_window`, the plot checks from `plot_pdf` (factor them into `check_plot_options(layout, paper, area, window, scale, style_table) -> list[float] | None`, which returns the checked window, and call it from both), LISP `mcp:export-dxf-now`, `mcp:plot-pdf-now`.
- Produces:
  - LISP `(mcp:save-copy path)`: `(command "_.SAVEAS" "" path)`, then fails unless `CMDACTIVE` is 0 and `(findfile path)`.
  - LISP `(mcp:plot-sheets folder paper landscape area window scale style-table)`: plots each name in `(layoutlist)` with `mcp:plot-pdf-now` to `<folder>/<n>.pdf`, n from 1, and returns the names in order. It fails `"This drawing has no sheets."` when there are none.
  - A run of each writing job sends `mcp:batch-file` from inside `write_through_temporary`'s `produce`, so the output appears only on success. For `layout="*"`, Python makes a fresh `output_folder / f".mcp-{hex8}"` folder, moves each `<n>.pdf` to `<stem>-<sheet>.pdf` after its own `check_output_target` (an existing one without `overwrite` fails that file, naming it), and always removes the folder.
  - The `export_dxf` plan uses `mcp:export-dxf-now (temp version)`, `plot_pdf` uses `mcp:plot-pdf-now (temp layout paper side area window scale style-table)`, and `save_as` uses `mcp:save-copy (temp)`. `outputs` lists the final paths.

- [ ] **Step 1: Write the failing fast tests**

```python
async def test_export_dxf_job_writes_each_output_through_a_temporary(...): ...
async def test_an_existing_output_is_refused_without_overwrite(...): ...  # that file "refused", others ok, its output unchanged
async def test_save_as_into_the_source_folder_needs_overwrite(...): ...  # output_folder == source folder: refused; with overwrite: ok, source replaced
async def test_plot_pdf_job_checks_its_options_before_running(...): ...  # scale "1/100" refuses the batch, nothing sent
```

- [ ] **Step 2: Write the failing real tests**

```python
def test_export_dxf_job(real_session, sources, tmp_path): ...  # three .dxf readable by ezdxf; sources unchanged
def test_plot_pdf_job_every_sheet(real_session, sources, tmp_path): ...  # layout="*": <stem>-Layout1.pdf and <stem>-Layout2.pdf per source, all %PDF
def test_save_as_job_replaces_sources_only_with_overwrite(real_session, sources): ...
    # output_folder = sources folder: all refused, digests unchanged; with overwrite=true: all ok, no .bak, files open in BricsCAD afterwards: none
```

- [ ] **Step 3: Run them and see them fail.** Expected: validation error on the unknown job types, or a missing worker.

- [ ] **Step 4: Implement** as in Interfaces.

- [ ] **Step 5: Run the tests and see them pass**: `uv run pytest`, then `uv run pytest -m bricscad tests/real/test_batch.py tests/real/test_export.py`.

- [ ] **Step 6: Commit** `feat: add export, plot and save jobs to bricscad_batch_run`.

---

### Task 3: The `lisp` job

**Interfaces:**
- Produces: LISP `(mcp:batch-lisp code save-path)`: evaluates `(read (strcat "(progn\n" code "\n)"))`. A read error fails with `"The LISP code could not be read: <message>"`. When `save-path` is non-nil it then runs `mcp:save-copy`. It returns the code's value. With `save`, the job goes through `write_through_temporary` like `save_as`.

- [ ] **Step 1: Write the failing fast tests**

```python
async def test_lisp_code_is_sent_as_a_string(...): ...  # code '(setq a "x") (strlen a)' arrives as one escaped LISP string
async def test_lisp_save_needs_an_output_folder(...): ...
```

- [ ] **Step 2: Write the failing real tests**

```python
def test_lisp_job_returns_a_value_per_file(real_session, sources): ...  # '(sslength (ssget "_X"))' -> entity counts
def test_lisp_job_with_save_writes_copies(real_session, sources, tmp_path): ...  # code draws a circle; each copy has one more entity; sources unchanged
@pytest.mark.parametrize("code, status", [
    ("(+ 1", "failed"), ("(/ 1 0)", "failed"), ('(command "_.LINE")', "ok"),
    ("(vla-close (mcp:active-document) :vlax-false)", "ok"),
])
def test_bad_lisp_leaves_the_session_working(real_session, blank, sources, code, status): ...
    # every file gets `status`; afterwards CMDACTIVE is 0, the document count is as before,
    # and a second batch with "(+ 1 2)" gives 3 for every file
```

- [ ] **Step 3: Run them and see them fail.**

- [ ] **Step 4: Implement** as in Interfaces.

- [ ] **Step 5: Run the tests and see them pass**: `uv run pytest`, then `uv run pytest -m bricscad tests/real/test_batch.py`.

- [ ] **Step 6: Commit** `feat: add the lisp job to bricscad_batch_run`.

---

### Task 4: Documentation and the full real run

- [ ] **Step 1: README.** Status line: all four phases built. Add `bricscad_batch_run` to `## Tools` with its jobs. To `## Safety`: batch jobs open sources read-only, never write them without `overwrite=true`, refuse sources open in BricsCAD, and replace a file only once the new one is complete. To `## Good to know`: try `dry_run` first; a timeout stops the batch; up to 500 files per call; the current drawing afterwards may be another open drawing.

- [ ] **Step 2: Run everything**: `uv run pytest`, then with V26 closed `uv run pytest -m bricscad`, then `pgrep -f 'BricsCAD V26.app/Contents/MacOS/bricscad'`. Expected: all pass, `pgrep` prints nothing.

- [ ] **Step 3: Commit** `docs: describe bricscad_batch_run`.
