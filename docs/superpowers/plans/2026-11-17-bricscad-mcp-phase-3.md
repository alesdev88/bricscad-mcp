# BricsCAD MCP Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `bricscad_export_dxf`, `bricscad_plot_pdf` and `bricscad_preview_image`, so a client can export and plot the current drawing and look at its own results, with no dialog and no change to the drawing.

**Architecture:** Same pattern as Phase 2: a plain Python function per tool that checks input and safety rules before anything reaches BricsCAD, an `@mcp.tool` wrapper, and one LISP worker per tool in a new `export.lsp`. Files are written by BricsCAD to a fresh temporary name in the target folder and moved onto the target by Python, so an existing file is only replaced on success and no `.bak` appears.

**Tech Stack:** Python 3.11+, MCP SDK 2.x (`MCPServer`, `Image`), AutoLISP commands `DXFOUT`, `-PLOT`, `PNGOUT`, pytest, ezdxf for checking DXF output.

**Spec:** `docs/superpowers/specs/2026-11-06-bricscad-mcp-design.md`, section "Phase 3: plot and export". Probe results: `docs/phase-0-results.md`, sections "Plotting to PDF" and "Found while planning Phase 3, 17.11.2026".

## Global Constraints

- Tool names use the `bricscad_` prefix, and every tool carries MCP read-only or destructive annotations.
- Saving over an existing file requires `overwrite=true`. The server checks this before sending anything to BricsCAD. This applies to exported and plotted files too.
- The server does not permanently change BricsCAD settings. Any variable changed during a command is restored in the same request, and is restored on error too.
- File paths from requests are passed as escaped LISP strings (`lispgen.call`), never inserted as raw LISP.
- A failed or stuck command returns a clear error rather than hanging the client. Every command started in a request finishes or is cancelled in that request.
- Real tests use only temporary drawings. At most one BricsCAD copy per version.
- No new runtime dependency.

## Review Focus

1. Exporting or plotting must not mark the drawing as modified, and a drawing that was already modified must stay modified. Tests: Tasks 1, 2, 3.
2. A rejected answer (unknown paper, style table, layout) must cancel the plot and leave no command waiting, so the next request is not eaten as an answer. Tests: Task 2.
3. Replacing an existing DXF or PDF must not leave a `.bak` or touch any other file in that folder, and a failed export must leave the old file as it was. Tests: Tasks 1, 2.
4. A target that is the open drawing itself, or a drawing open in another document, under any spelling, is refused. Tests: Task 1.
5. Previewing a sheet never used before must not add its viewports or change the current layout. Tests: Task 3.

---

## File structure

| File | Responsibility |
|---|---|
| `src/bricscad_mcp/lisp/export.lsp` (new) | `mcp:keep-clean`, `mcp:answer-all`, and the three workers. Loaded automatically |
| `src/bricscad_mcp/tools/export.py` (new) | Output target checks, the temporary-file move, the three tools |
| `src/bricscad_mcp/tools/edit.py` | Export `_is_same_file` as `is_same_file` for reuse; update the `.dxf` refusal text in `_check_save_target` to name `bricscad_export_dxf` without "in Phase 3" |
| `src/bricscad_mcp/server.py` | Add `export` to the tool import |
| `tests/test_tools_export.py` (new) | Fast tests through the fake listener |
| `tests/real/test_export.py` (new) | Real tests |
| `tests/test_stdio.py`, `manifest.json` | New tool names (a test checks the manifest lists every registered tool) |
| `README.md` | Tools table, Safety, Known limits, status line |

Annotations: `export_dxf` and `plot_pdf` are `DESTRUCTIVE` (they can replace files with `overwrite=true`). `preview_image` is `READ_ONLY`.

---

### Task 1: Output targets and `bricscad_export_dxf`

**Files:**
- Create: `src/bricscad_mcp/lisp/export.lsp`, `src/bricscad_mcp/tools/export.py`, `tests/test_tools_export.py`, `tests/real/test_export.py`
- Modify: `src/bricscad_mcp/tools/edit.py`, `src/bricscad_mcp/server.py`, `tests/test_stdio.py`, `manifest.json`

**Interfaces:**
- Consumes: LISP `mcp:save-state` (edit.lsp) returning `{"path", "titled", "read_only", "other_open"}`; `mcp:fail`, `mcp:cancel-command`, `mcp:obj`.
- Produces:
  - Python `check_output_target(path: str, suffix: str, state: dict, overwrite: bool) -> Path` in `tools/export.py`. Refusals, in order: backslash in path where `os.name != "nt"` (`BricsCADError`); suffix not `suffix` in any letter case (`BricsCADError`, naming the suffix wanted); target is a folder; parent folder missing; target is the current drawing's file or one in `state["other_open"]`, by `is_same_file` (`SafetyRefused`, always, overwrite or not); target exists without `overwrite` (`SafetyRefused` naming `overwrite=true`); target exists and not writable (`SafetyRefused`).
  - Python `write_through_temporary(target: Path, produce: Callable[[Path], None]) -> dict` in `tools/export.py`: picks `target.with_name(f".{target.stem}.mcp-{uuid4().hex[:8]}{target.suffix}")`, calls `produce(temp)`, requires `temp` to exist with size > 0 (else `BricsCADError("BricsCAD did not write <target>.")`), then `os.replace(temp, target)`. On any error it removes `temp` if present and re-raises. The temporary name is new, so BricsCAD leaves no `.bak`. Returns `{"path": target.as_posix(), "bytes": size}`.
  - LISP `(mcp:keep-clean worker args)`: `acad-push-dbmod`, runs `worker` under `vl-catch-all-apply`, `mcp:cancel-command`, `acad-pop-dbmod`, then re-raises a failure the way `mcp:edit` does (`*mcp-pending-error*` then `(exit)`).
  - LISP `(mcp:export-dxf path version)` returning `T`, run through `mcp:keep-clean`.
  - Python `export_dxf(bridge, path: str, version: str = "2018", overwrite: bool = False, timeout: float = 120.0) -> dict` returning `{"path", "bytes", "version"}`. `version` is `Literal["R12", "2000", "2004", "2007", "2010", "2013", "2018"]` in the tool signature.

- [ ] **Step 1: Write the failing fast tests** in `tests/test_tools_export.py`, using the `started` and `refused` helpers of `tests/test_tools_edit.py` (copy them). `fake.responses["mcp:save-state"]` returns a state dict; `fake.responses["mcp:export-dxf"]` is a callable that writes bytes to the path in the request (parse the first LISP string).

```python
async def test_export_dxf_writes_through_a_temporary_name(started, fake, tmp_path): ...
    # target appears with the fake's bytes; request is (mcp:export-dxf "<dir>/.out.mcp-xxxxxxxx.dxf" "2018"); no other file left in tmp_path
async def test_export_dxf_refuses_an_existing_file_without_overwrite(started, fake, tmp_path): ...  # only mcp:save-state was sent; file unchanged
async def test_export_dxf_replaces_with_overwrite(started, fake, tmp_path): ...  # out.dxf holds the new bytes; it is the only file in tmp_path
@pytest.mark.parametrize("name", ["out.DXF", "out.dwg", "out", "missing/out.dxf"])
async def test_export_dxf_refuses_bad_targets(started, fake, tmp_path, name): ...  # .DXF is accepted: assert not is_error for it, is_error for the rest
async def test_export_dxf_refuses_the_open_drawing_and_other_open_files(started, fake, tmp_path): ...  # both, with overwrite=true
async def test_a_failed_export_keeps_the_old_file_and_removes_the_temporary(started, fake, tmp_path): ...  # fake writes temp then returns an error
async def test_export_dxf_refuses_an_unknown_version(started, fake, tmp_path): ...  # "2019"
```

- [ ] **Step 2: Write the failing real tests** in `tests/real/test_export.py`, with a fixture `drawing` that yields the bridge of a `blank` drawing holding a line and a TEXT `Načrt čšž` made with `edit.create_entities`, then saved with `edit.save_drawing` to `tmp_path / "src.dwg"`:

```python
def test_export_dxf_matches_the_drawing(drawing, tmp_path): ...
    # ezdxf.readfile: dxfversion "AC1032", modelspace types include LINE and TEXT, text == "Načrt čšž"
def test_export_dxf_r12(drawing, tmp_path): ...  # dxfversion "AC1009"
def test_export_dxf_leaves_the_drawing_as_it_was(drawing, tmp_path): ...
    # drawing_info before == after for name, path, read_only, modified; also with an unsaved edit first: modified stays True
def test_export_dxf_over_an_existing_file_leaves_only_that_file(drawing, tmp_path): ...
    # out folder holds old.bak beforehand; after overwrite=true: files == {"old.bak", "out.dxf"}, old.bak bytes unchanged
```

- [ ] **Step 3: Run both and see them fail**

Run: `uv run pytest tests/test_tools_export.py -v` and, with V26 closed, `uv run pytest -m bricscad tests/real/test_export.py -v`
Expected: FAIL, no module `bricscad_mcp.tools.export`.

- [ ] **Step 4: Implement** `export.lsp`, `tools/export.py`, the `edit.py` rename and text, the server import, the tool name in `tests/test_stdio.py` and `manifest.json`. LISP: `(command "_.DXFOUT" path "_V" version "")`. Docstring for `bricscad_export_dxf` states: writes the current drawing as DXF; the drawing keeps its name and state; `path` must end in `.dxf`; `overwrite=true` replaces a file; versions offered.

- [ ] **Step 5: Run the tests and see them pass**

Run: `uv run pytest` and `uv run pytest -m bricscad tests/real/test_export.py tests/real/test_save.py`
Expected: all pass. `test_save.py` still passes after the `edit.py` change.

- [ ] **Step 6: Commit**

```bash
git add -A src tests manifest.json && git commit -m "feat: add bricscad_export_dxf"
```

---

### Task 2: `bricscad_plot_pdf`

**Files:**
- Modify: `src/bricscad_mcp/lisp/export.lsp`, `src/bricscad_mcp/tools/export.py`, `tests/test_tools_export.py`, `tests/real/test_export.py`, `tests/test_stdio.py`, `manifest.json`

**Interfaces:**
- Consumes: `check_output_target`, `write_through_temporary`, `mcp:keep-clean` from Task 1.
- Produces:
  - LISP `(mcp:answer-all answers)`: sends each answer with `(command answer)`. After each, if `LASTPROMPT` matches `*not found*` (any case), or `CMDACTIVE` is 0 while answers remain, it cancels and fails with BricsCAD's own `LASTPROMPT` text. After the last answer `CMDACTIVE` must be 0, else cancel and fail the same way.
  - LISP `(mcp:plot-pdf path layout paper landscape area window scale style-table)` returning `T`. `layout` nil means `CTAB`. Fails with `"No layout named <x>. Layouts: Model, ..."` when the name matches none of `(cons "Model" (layoutlist))` case-insensitively, and uses the stored spelling. `area` nil means `"extents"` on the model and `"layout"` on a sheet; `"layout"` on the model fails. `scale` nil means `"fit"` on the model and `"1:1"` on a sheet.
  - Python `plot_pdf(bridge, path: str, layout: str | None = None, paper: str | None = None, landscape: bool | None = None, area: Literal["extents", "layout", "window"] | None = None, window: list[float] | None = None, scale: str | None = None, style_table: str | None = None, overwrite: bool = False, timeout: float = 120.0) -> dict` returning `{"path", "bytes", "layout"}`.

Answer lists, from `docs/phase-0-results.md`. Device is always `Print As PDF.pc3`, units always `_M`, upside down `_N`, plot styles `_Y`, lineweights `_Y`, save layout changes `_N`, proceed `_Y`. `paper` nil is `""`. `landscape` nil is `""`, true `_L`, false `_P`. `area` is `_E`, `_L`, or `_W` followed by two points from `window`. `scale` is `_F` for `"fit"`, else the text such as `1:100`. Offset is `_C`, except `""` with `area` `"layout"`. `style_table` nil is `""`.

| | Model | Sheet |
|---|---|---|
| Order | `_Y`, layout, device, paper, units, orientation, upside down, area, scale, offset, styles, table, lineweights, shade `""`, file, save, proceed | `_Y`, layout, device, paper, units, orientation, upside down, area, scale, offset, styles, table, lineweights, scale lineweights `_N`, paper space last `_Y`, hide paper space objects `_N`, file, save, proceed |

Python checks before sending: `window` is required with `area="window"` and forbidden otherwise, and is `[x1, y1, x2, y2]` with finite numbers and a non-zero width and height; `scale` is `"fit"` or matches `^\d+(\.\d+)?:\d+(\.\d+)?$` with neither side zero; `paper` and `style_table` hold no newline.

- [ ] **Step 1: Write the failing fast tests**

```python
async def test_plot_pdf_sends_defaults_as_nil(started, fake, tmp_path): ...
    # request == (mcp:plot-pdf "<temp>" nil nil nil nil nil nil nil)
async def test_plot_pdf_sends_a_window(started, fake, tmp_path): ...
    # area="window", window=[0, 0, 50, 50], scale="1:100" -> ... "window" (list 0 0 50 50) "1:100" nil)
@pytest.mark.parametrize("args", [
    {"area": "window"}, {"window": [0, 0, 1, 1]}, {"area": "window", "window": [0, 0, 0, 5]},
    {"scale": "1:0"}, {"scale": "100"}, {"scale": "1/100"}, {"paper": "A3\n_Y"},
])
async def test_plot_pdf_refuses_bad_arguments(started, fake, tmp_path, args): ...
async def test_plot_pdf_refuses_an_existing_file_without_overwrite(started, fake, tmp_path): ...
```

- [ ] **Step 2: Write the failing real tests**, on the drawing from Task 1:

```python
def test_plot_pdf_model_defaults(drawing, tmp_path): ...  # bytes start b"%PDF"; one /MediaBox [0 0 595 842]
def test_plot_pdf_a3_landscape(drawing, tmp_path): ...  # paper="ISO A3 (297.00 x 420.00 MM)", landscape=True -> /MediaBox [0 0 1191 842]
def test_plot_pdf_sheet_layout_window_and_style(drawing, tmp_path): ...
    # layout="layout1" (other case) -> result["layout"] == "Layout1"; then area="window", window=[0,0,50,50], scale="1:1", style_table="monochrome.ctb" on Model
@pytest.mark.parametrize("args, words", [
    ({"paper": "Nope"}, "not found"), ({"style_table": "nope.ctb"}, "not found"),
    ({"layout": "Nope"}, "No layout named Nope"), ({"layout": "Model", "area": "layout"}, "layout"),
])
def test_plot_pdf_rejections_cancel_cleanly(drawing, tmp_path, args, words): ...
    # BricsCADError containing words; then (getvar "CMDACTIVE") == 0; no PDF and no temporary in tmp_path; drawing_info()["modified"] is False
def test_plot_pdf_keeps_the_modified_flag(drawing, tmp_path): ...  # clean stays clean; after an edit, modified stays True
def test_plot_pdf_replaces_an_existing_pdf_with_overwrite(drawing, tmp_path): ...
```

- [ ] **Step 3: Run them and see them fail**

Run: `uv run pytest tests/test_tools_export.py -v -k plot` and `uv run pytest -m bricscad tests/real/test_export.py -v -k plot`
Expected: FAIL, unknown tool `bricscad_plot_pdf`.

- [ ] **Step 4: Implement** `mcp:answer-all`, `mcp:plot-pdf` (through `mcp:keep-clean`), `plot_pdf`, the tool, its name in `tests/test_stdio.py` and `manifest.json`. Docstring for `bricscad_plot_pdf` states: plots one layout to PDF with `Print As PDF.pc3`; the defaults for each argument per model and sheet; paper sizes by BricsCAD's name such as `ISO A3 (297.00 x 420.00 MM)`, with the current size when left out; `scale` in plotted millimetres to drawing units; the drawing is not changed.

- [ ] **Step 5: Run the tests and see them pass**

Run: `uv run pytest` and `uv run pytest -m bricscad tests/real/test_export.py`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A src tests manifest.json && git commit -m "feat: add bricscad_plot_pdf"
```

---

### Task 3: `bricscad_preview_image`

**Files:**
- Modify: `src/bricscad_mcp/lisp/export.lsp`, `src/bricscad_mcp/tools/export.py`, `tests/test_tools_export.py`, `tests/real/test_export.py`, `tests/test_stdio.py`, `manifest.json`

**Interfaces:**
- Consumes: `mcp:keep-clean` from Task 1; the layout lookup `mcp:plot-pdf` uses (factor it into `(mcp:layout-named name)` returning the stored spelling or failing).
- Produces:
  - LISP `(mcp:preview-image path layout window)` returning `T`. Inside `mcp:keep-clean`: `_.UNDO _Mark`; if `layout`, `(setvar "CTAB" stored-name)`; `_.ZOOM _E`, or `_.ZOOM _W` with the two corners of `window`; `_.PNGOUT path`; then `_.UNDO _Back`, which also runs when a step fails, so layout, view and any new viewports go back.
  - Python `preview_image(bridge, preview_dir: Path, layout: str | None = None, window: list[float] | None = None, timeout: float = 60.0) -> bytes`. Writes to `preview_dir / f"{uuid4().hex}.png"`, reads the bytes, always deletes the file, and fails with `BricsCADError` if no PNG was written. `preview_dir` is `bridge.queue_dir.parent / "previews"`, made with mode `0o700`. Same `window` checks as Task 2.
  - Tool `bricscad_preview_image(layout: str | None = None, window: list[float] | None = None, timeout: float = 60.0) -> Image`, returning `Image(data=png, format="png")`.

- [ ] **Step 1: Write the failing fast tests**

```python
async def test_preview_returns_the_png_and_removes_the_file(started, fake): ...
    # fake writes b"\x89PNG..." to the requested path; result.content[0].type == "image", mime "image/png"; previews folder empty afterwards
async def test_preview_without_a_png_is_an_error(started, fake): ...
async def test_preview_refuses_a_bad_window(started, fake): ...  # [0, 0, 0, 5]
```

- [ ] **Step 2: Write the failing real tests**

```python
def test_preview_of_the_model_is_a_png(drawing): ...  # bytes start b"\x89PNG"; modified stays False
def test_preview_of_an_unused_sheet_adds_nothing(drawing): ...
    # (command "_.LAYOUT" "_N" "Fresh") first via bridge, then save; entity_count and CTAB before == after preview(layout="Fresh"); modified False
def test_preview_of_a_window(drawing): ...
def test_preview_of_an_unknown_layout_fails_cleanly(drawing): ...  # "No layout named"; CMDACTIVE 0; CTAB unchanged
```

- [ ] **Step 3: Run them and see them fail**

Run: `uv run pytest tests/test_tools_export.py -v -k preview` and `uv run pytest -m bricscad tests/real/test_export.py -v -k preview`
Expected: FAIL, unknown tool `bricscad_preview_image`.

- [ ] **Step 4: Implement** as in Interfaces, with the name in `tests/test_stdio.py` and `manifest.json`. Docstring states: returns a PNG of the model or a sheet at extents, or of a window, so the client can check its work; the size follows the BricsCAD window; the model shows on black; the drawing is not changed.

- [ ] **Step 5: Run the tests and see them pass**

Run: `uv run pytest` and `uv run pytest -m bricscad tests/real/test_export.py`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A src tests manifest.json && git commit -m "feat: add bricscad_preview_image"
```

---

### Task 4: Documentation and the full real run

**Files:**
- Modify: `README.md`, `tests/real/test_end_to_end.py`

- [ ] **Step 1: Extend the end-to-end test** so spec success criterion 1 runs whole: after its save to a new path, `plot_pdf` to `tmp_path / "out.pdf"` and check the file starts with `%PDF`.

- [ ] **Step 2: README.** Status line: Phases 1 to 3 of 4 built; batch jobs planned. Add the three tools to `## Tools`. To `## Safety`: export and plot never change the drawing, refuse an existing file without `overwrite=true`, never write over the open drawing or another open one, and replace a file only once the new one is complete, with no `.bak`. To `## Known limits`: PDF uses `Print As PDF.pc3` only; paper sizes go by BricsCAD's name; previews are the size of the BricsCAD window, with the model on black.

- [ ] **Step 3: Run everything**

Run: `uv run pytest` then, with V26 closed, `uv run pytest -m bricscad`, then `pgrep -f 'BricsCAD V26.app/Contents/MacOS/bricscad'`
Expected: all pass; `pgrep` prints nothing.

- [ ] **Step 4: Commit**

```bash
git add README.md tests docs && git commit -m "docs: describe the plot and export tools"
```
