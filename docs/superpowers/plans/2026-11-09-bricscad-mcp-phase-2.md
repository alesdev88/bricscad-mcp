# BricsCAD MCP Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an MCP client draw and edit in 2D, undo its edits and save to a new path, with no dialogs and no accidental change to an original file.

**Architecture:** Seven new tools in one Python module, `tools/edit.py`, with entity shapes validated by pydantic in `tools/shapes.py`. Each builds one LISP call through `lispgen`. A new `lisp/edit.lsp` runs every edit inside `mcp:edit`, which sets an undo mark first and rolls back to it on any failure, so a tool call is all-or-nothing and is one undo step.

**Tech Stack:** Python 3.11+, MCP SDK 2.x (`MCPServer`), pydantic (already installed with the SDK), AutoLISP / Visual LISP, `uv`, `pytest`, `ezdxf` for test fixtures.

**Spec:** `docs/superpowers/specs/2026-11-06-bricscad-mcp-design.md`

**Scope:** Spec section "Phase 2: draw and edit" only. Plotting and PDF (spec success criterion 1, last step) are Phase 3.

## Global Constraints

- Tool names use the `bricscad_` prefix. Every tool carries MCP read-only or destructive annotations.
- Save only with `_.SAVEAS` and `_.QSAVE`. Never use `vla-save`, `vla-saveas` or `_.CLOSE`.
- Saving over an existing file requires `overwrite=true`. The server checks this before sending anything to BricsCAD.
- Edits on a read-only drawing must be saved to a new path.
- Never assume a value for `FILEDIA`, and do not change it. Any variable changed during a request is restored in that request, including on error.
- Text and paths reach LISP only through `lispgen`, never as raw LISP.
- A safety refusal raises `SafetyRefused`, naming the rule and the parameter that would allow it.
- Request timeout: 30 seconds by default, settable per call. Saving defaults to 120 seconds, like opening.
- Real tests are marked `bricscad`, use only temporary drawings they create, and run with at most one copy of V26 open. Leave a running V25 alone.
- Angles in the tool API are degrees. Python converts them to radians. Coordinates are drawing units.
- Real tests need V26 closed: `uv run pytest -m bricscad -k <name>`. Fast tests: `uv run pytest`.

## Probed behaviour this plan relies on

Run on BricsCAD V26.1.6 Lite, macOS, 09.11.2026, on temporary drawings. Task 9 copies this table into `docs/phase-0-results.md`.

| Behaviour | Consequence in this plan |
|---|---|
| `_.UNDO 1` undoes the listener's own `_.DELAY`, not the last edit, also after `_Begin`/`_End` or `vla-startundomark` | Undo uses `_Mark` and `_Back` only |
| `_.UNDO _Mark` then `_Back` reverts entities, layer creation and layer changes, one mark at a time, also after `_.SAVEAS` | `mcp:edit` marks; `bricscad_undo` goes back |
| `_Back` with no mark left prompts on the command line; answering `_N` keeps the drawing | `mcp:undo` answers `_N` and stops |
| `(exit)` or a LISP error inside `vl-catch-all-apply` is caught; `_Back` then rolls back and earlier marks survive | All-or-nothing edits |
| `entmake` with an unknown layer creates it. An unknown text style or layout is accepted silently. A zero radius is accepted | Validate before making |
| `entmake` of MTEXT takes 806 characters in one group 1 and reads back complete. A newline is stored raw | No chunking. Python turns newlines into `\P` |
| `vla-adddimrotated`, `vla-adddimaligned`, `vla-addhatch` and `vla-insertblock` work on Lite, on a layout's block too. `vla-get-measurement` does not exist | Use these for dimension, hatch and insert |
| A non-associative hatch keeps its area after its boundary is erased. An unknown pattern raises an error with no dialog | Temporary boundary, erased after evaluate |
| `vla-insertblock` adds attributes with default values and no prompt. They move with the insert. `(vlax-invoke obj 'GetAttributes)` works | Insert and attribute writes |
| On a locked layer `vla-move` still moves, `entmod` and `entdel` return nil and do nothing, `vla-delete` errors | Server refuses locked targets itself |
| `entdel` on an erased entity restores it. `entdel` on an ATTRIB returns nil | Check `entget` first; refuse sub-entities |
| `vla-add` on the Layers collection returns an existing layer, case-insensitive. `vla-put-freeze` on the current layer takes effect | Create-or-change is one call; refuse freezing the current layer |
| Renaming layer 0, or onto an existing name, raises a raw automation error | Check first and say why |
| `vla-load` of `CENTER` works from `iso.lin`; `bricscad.lin` does not exist | Linetypes load from `iso.lin` |
| `_.SAVEAS` to `c.dxf` writes `c.dxf.dwg`. To a missing folder it does nothing and raises nothing | Python requires `.dwg` and a real folder; LISP confirms the new name |
| `_.SAVEAS` over the drawing's own file shows no prompt. Over another file it prompts once. With `_Y` it replaces a file open as another drawing, and a read-only (chmod 444) file | Python refuses both cases |
| `_.QSAVE` on a read-only drawing ends in `Function cancelled`, file unchanged. `_.SAVEAS` from one writes the copy and the document becomes writable under the new name | Refuse in-place save when read-only |
| `DWGTITLED` is 0 on a new drawing | Unnamed drawings need a path |

## Review Focus

1. A batch where a later item is bad leaves nothing behind and keeps earlier undo steps. Tests: Tasks 1, 6.
2. Erasing the same handle twice must fail, not bring the entity back. Tests: Task 2.
3. Undo with no step left, or after edits made through `bricscad_run_lisp`, must not offer to undo everything or hang. Tests: Task 1.
4. A save path that names the current or an open file by another spelling (symlink, letter case, Unicode form) gets the same refusal. Tests: Task 8.
5. Text with quotes, backslashes, newlines and `č š ž` round-trips in create, modify and attributes. Tests: Tasks 4, 5, 6.

---

## File structure

| File | Responsibility |
|---|---|
| `src/bricscad_mcp/lisp/edit.lsp` (new) | `mcp:edit`, undo, target checks, all edit workers. Loaded automatically: `session.py` globs `lisp/*.lsp` |
| `src/bricscad_mcp/tools/shapes.py` (new) | Pydantic entity models and their wire lists |
| `src/bricscad_mcp/tools/edit.py` (new) | The seven tools and their plain functions |
| `src/bricscad_mcp/server.py` | Add `edit` to the tool import at the bottom |
| `tests/test_tools_edit.py` (new) | Fast tests through the fake listener |
| `tests/real/test_undo.py`, `test_erase.py`, `test_layers.py`, `test_modify.py`, `test_attributes.py`, `test_create.py`, `test_save.py` (new) | Real tests per tool |
| `tests/real/helpers.py` | `entity_count`, `dxf_value`, `locked_line` |
| `tests/test_stdio.py` | Expected tool names |

Each tool follows the existing pattern: a plain function `name(bridge, ...)` that tests call directly, and an `@mcp.tool` wrapper using `_run` imported from `.read`. Each LISP entry point is `(defun mcp:<tool> (args) (mcp:edit 'mcp:<tool>-now (list args)))`, so only the worker is written per tool. `mcp:fail` from `read.lsp` raises a message to the client.

Annotations: `create_entities` is `CHANGES_STATE`. All six others are `DESTRUCTIVE`.

---

### Task 1: Edit transaction and undo

**Files:**
- Create: `src/bricscad_mcp/lisp/edit.lsp`, `src/bricscad_mcp/tools/edit.py`, `tests/real/test_undo.py`, `tests/test_tools_edit.py`
- Modify: `src/bricscad_mcp/server.py:51`, `tests/real/helpers.py`, `tests/test_stdio.py:19-27`

**Interfaces:**
- Produces: LISP `(mcp:edit worker args)`, `(mcp:undo steps)`. Python `undo(bridge, steps: int = 1, timeout: float = 30.0) -> dict` returning `{"undone": int, "requested": int}`. Test helpers `entity_count(session) -> int` (`(mcp:count-selection (ssget "_X"))`), `dxf_value(session, handle, code)` (first value of that group from `read.get_entity`).

- [ ] **Step 1: Create the branch**

```bash
git switch -c feat/phase-2-draw-edit
```

- [ ] **Step 2: Write the failing tests**

`tests/real/test_undo.py`, with `edit_line = '(mcp:edit (function (lambda () (entmakex (list (quote (0 . "LINE")) (quote (10 0.0 0.0 0.0)) (quote (11 1.0 1.0 0.0)))))) nil)'`:

```python
def test_undo_removes_one_edit_at_a_time(real_session, blank):
    send = real_session.bridge.send
    send(edit_line); send(edit_line)
    time.sleep(1.5)  # the listener runs _.DELAY meanwhile, which must not count as a step
    assert edit.undo(real_session.bridge) == {"undone": 1, "requested": 1}
    assert entity_count(real_session) == 1

def test_undo_stops_at_the_oldest_step(real_session, blank):
    real_session.bridge.send(edit_line)
    assert edit.undo(real_session.bridge, steps=5) == {"undone": 1, "requested": 5}

def test_undo_with_no_steps_left_keeps_the_drawing(real_session, blank):
    line_at(real_session, 0, 0)  # made outside mcp:edit, as bricscad_run_lisp would
    assert edit.undo(real_session.bridge)["undone"] == 0
    assert entity_count(real_session) == 1
    assert real_session.bridge.send('(getvar "CMDACTIVE")') == 0

def test_a_failed_edit_changes_nothing_and_keeps_earlier_steps(real_session, blank):
    send = real_session.bridge.send
    send(edit_line)
    failing = '(mcp:edit (function (lambda () (entmakex (list (quote (0 . "LINE")) (quote (10 0.0 0.0 0.0)) (quote (11 1.0 1.0 0.0)))) (mcp:fail "Second item is bad."))) nil)'
    with pytest.raises(LispError, match="Second item is bad."):
        send(failing)
    assert entity_count(real_session) == 1
    assert edit.undo(real_session.bridge)["undone"] == 1
    assert entity_count(real_session) == 0

def test_a_lisp_error_in_an_edit_reports_its_message(real_session, blank):
    with pytest.raises(LispError, match="bad argument"):
        real_session.bridge.send("(mcp:edit (function (lambda () (car 5))) nil)")
```

`tests/test_tools_edit.py`, with a `started` fixture as in `tests/test_tools_read.py` (start through `client`, then clear `fake.requests`). In this file and every later task, a fast refusal means `result = await started.call_tool(...)`, then `assert result.is_error and fake.requests == []`. Set `fake.responses` for any LISP function whose reply the tool returns.

```python
async def test_undo_sends_steps(started, fake):
    fake.responses["mcp:undo"] = {"undone": 3, "requested": 3}
    await started.call_tool("bricscad_undo", {"steps": 3})
    assert fake.requests[-1] == "(mcp:undo 3)"

@pytest.mark.parametrize("steps", [0, -1, 101])
async def test_undo_refuses_a_bad_step_count(started, fake, steps):
    result = await started.call_tool("bricscad_undo", {"steps": steps})
    assert result.is_error and fake.requests == []
```

In `tests/test_stdio.py`, rename the test to `test_the_installed_command_serves_every_tool` and add `"bricscad_undo"`. Later tasks add their own names.

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/test_tools_edit.py tests/test_stdio.py -q` and `uv run pytest -m bricscad tests/real/test_undo.py -q`
Expected: FAIL (no `edit` module).

- [ ] **Step 4: Implement `edit.lsp`, `edit.py` and the server import**

```lisp
;; Every edit runs through here: one undo step on success, no change at all on failure.
;; Only marks work. _.UNDO with a count undoes the listener's own _.DELAY instead.
(defun mcp:edit (worker args / result message)
  (command "_.UNDO" "_Mark")
  (setq *mcp-pending-error* nil
        result (vl-catch-all-apply worker args))
  (if (vl-catch-all-error-p result)
    (progn
      (setq message (cond (*mcp-pending-error*) ((vl-catch-all-error-message result))))
      (mcp:cancel-command)
      (command "_.UNDO" "_Back")
      (setq *mcp-pending-error* message)
      (exit)
    )
  )
  result
)
```

`mcp:undo`: repeat up to `steps` times `(command "_.UNDO" "_Back")`. If `CMDACTIVE` is then above 0, no mark is left: `(command "_N")` and stop. Otherwise count one undone. Python refuses `steps` outside 1 to 100. The tool docstring says a step is one successful edit tool call, and that `bricscad_run_lisp` edits have no step of their own, so they go back with the step before them.

- [ ] **Step 5: Run them to verify they pass**

Run the Step 3 commands. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src tests
git commit -m "feat: add all-or-nothing edits and undo"
```

### Task 2: Erase and target checks

**Files:**
- Modify: `edit.lsp`, `edit.py`, `tests/real/helpers.py`, `tests/test_tools_edit.py`, `tests/test_stdio.py`
- Create: `tests/real/test_erase.py`

**Interfaces:**
- Consumes: `mcp:edit`.
- Produces: LISP `(mcp:edit-targets handles)` returning enames. Python `check_handles(handles: list[str]) -> list[str]` and `erase_entities(bridge, handles, timeout=30.0) -> {"erased": int}`. Test helper `locked_line(session) -> handle` (makes layer `LK` with group 70 = 4 and a line on it).

- [ ] **Step 1: Write the failing tests** in `tests/real/test_erase.py`

```python
def test_erase_removes_entities(real_session, blank):
    handles = [line_at(real_session, 0, 0), line_at(real_session, 2, 2)]
    assert edit.erase_entities(real_session.bridge, handles) == {"erased": 2}
    assert entity_count(real_session) == 0

def test_erasing_twice_fails_and_does_not_restore(real_session, blank):
    handle = line_at(real_session, 0, 0)
    edit.erase_entities(real_session.bridge, [handle])
    with pytest.raises(LispError, match=handle):
        edit.erase_entities(real_session.bridge, [handle])
    assert entity_count(real_session) == 0

def test_an_unknown_handle_refuses_the_whole_request(real_session, blank):
    good = line_at(real_session, 0, 0)
    with pytest.raises(LispError, match="FFFFFF"):
        edit.erase_entities(real_session.bridge, [good, "FFFFFF"])
    assert entity_count(real_session) == 1

def test_erase_refuses_a_locked_layer(real_session, blank):
    handle = locked_line(real_session)
    with pytest.raises(LispError, match="LK.*locked"):
        edit.erase_entities(real_session.bridge, [handle])
    assert entity_count(real_session) == 1

def test_erase_refuses_an_attribute(real_session, blank):
    make_block_with_attributes(real_session, "TB", {"A": "x"})
    attribute = read.find_text(real_session.bridge, "x")["items"][0]["handle"]
    with pytest.raises(LispError, match="bricscad_set_attributes"):
        edit.erase_entities(real_session.bridge, [attribute])

def test_erase_is_one_undo_step(real_session, blank):
    handles = [line_at(real_session, 0, 0), line_at(real_session, 2, 2)]
    edit.erase_entities(real_session.bridge, handles)
    assert edit.undo(real_session.bridge)["undone"] == 1
    assert entity_count(real_session) == 2
```

Fast: `["1a", "1A", "2B"]` sends `(mcp:erase-entities (list "1A" "2B"))`. An empty list, more than 2000 handles, and `"1A) (x"` raise `BricsCADError` with nothing sent.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -m bricscad tests/real/test_erase.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement**

`check_handles`: strip, uppercase, drop repeats keeping order, each must match `[0-9A-F]+`, at most 2000.

`mcp:edit-targets`: for each handle, `(handent h)`, then `(entget ename)`. Fail with `No entity has the handle <h>.` if either is empty, which is what stops `entdel` from toggling an erased entity back. Fail on type ATTRIB (`Change attribute values with bricscad_set_attributes.`), VERTEX or SEQEND (part of another entity). Fail on layer flag bit 4: `Layer <name> is locked. Unlock it with bricscad_set_layer.` Check every handle before returning, so nothing is changed on a refusal.

`mcp:erase-entities-now`: `entdel` each target. A nil return is `mcp:fail`.

- [ ] **Step 4: Run them to verify they pass**, plus `uv run pytest -q`. Expected: PASS.

- [ ] **Step 5: Commit** with `feat: add bricscad_erase_entities`.

### Task 3: Layers

**Files:** Modify `edit.lsp`, `edit.py`, `tests/test_tools_edit.py`, `tests/test_stdio.py`. Create `tests/real/test_layers.py`.

**Interfaces:**
- Consumes: `mcp:edit`, `mcp:layer-item` from `read.lsp`.
- Produces: `(mcp:ensure-linetype name)`, `(mcp:require-layer name)`. Python `set_layer(bridge, name, new_name=None, color=None, linetype=None, on=None, frozen=None, locked=None, timeout=30.0) -> {"layer": <layer item>, "created": bool}`.

- [ ] **Step 1: Write the failing tests** in `tests/real/test_layers.py`

```python
def test_creates_a_layer_with_properties(real_session, blank):
    result = edit.set_layer(real_session.bridge, "Načrt A", color=3, locked=True)
    assert result["created"] is True
    assert (result["layer"]["name"], result["layer"]["color"], result["layer"]["locked"]) == ("Načrt A", 3, True)

def test_changes_an_existing_layer_whatever_the_case(real_session, blank):
    edit.set_layer(real_session.bridge, "Plan")
    result = edit.set_layer(real_session.bridge, "PLAN", on=False, frozen=True)
    assert result["created"] is False and result["layer"]["name"] == "Plan"
    assert result["layer"]["on"] is False and result["layer"]["frozen"] is True

def test_false_turns_a_lock_off(real_session, blank):
    edit.set_layer(real_session.bridge, "A", locked=True)
    assert edit.set_layer(real_session.bridge, "A", locked=False)["layer"]["locked"] is False

def test_loads_a_linetype_from_iso_lin(real_session, blank):
    assert edit.set_layer(real_session.bridge, "A", linetype="CENTER")["layer"]["linetype"] == "CENTER"

def test_an_unknown_linetype_fails_and_makes_nothing(real_session, blank):
    with pytest.raises(LispError, match="NOPE.*iso.lin"):
        edit.set_layer(real_session.bridge, "A", color=5, linetype="NOPE")
    assert real_session.bridge.send('(if (tblsearch "LAYER" "A") 1 0)') == 0

def test_cannot_freeze_the_current_layer(real_session, blank):
    with pytest.raises(LispError, match="current layer"):
        edit.set_layer(real_session.bridge, "0", frozen=True)
    assert real_session.bridge.send('(logand 1 (cdr (assoc 70 (tblsearch "LAYER" "0"))))') == 0

def test_renames_a_layer(real_session, blank):
    edit.set_layer(real_session.bridge, "Old")
    assert edit.set_layer(real_session.bridge, "Old", new_name="New")["layer"]["name"] == "New"

def test_rename_onto_an_existing_name_is_refused(real_session, blank):
    edit.set_layer(real_session.bridge, "A"); edit.set_layer(real_session.bridge, "B")
    with pytest.raises(LispError, match="already"):
        edit.set_layer(real_session.bridge, "A", new_name="B")

@pytest.mark.parametrize("name", ["0", "defpoints"])
def test_special_layers_cannot_be_renamed(real_session, blank, name): ...  # match "cannot be renamed"; create defpoints first

def test_undo_removes_a_new_layer(real_session, blank):
    edit.set_layer(real_session.bridge, "A")
    edit.undo(real_session.bridge)
    assert real_session.bridge.send('(if (tblsearch "LAYER" "A") 1 0)') == 0
```

Fast: `set_layer(name="A", color=3, on=False, locked=True)` sends `(mcp:set-layer "A" nil 3 nil 0 nil 1)`: the three switches go as nil (leave alone), 0 (false) or 1 (true), because `lisp_value(False)` is nil. Names containing any of `< > / \ " : ; ? * | , = backtick`, an empty name, and color outside 1 to 255 raise `BricsCADError` with nothing sent. The same character check applies to `new_name`.

- [ ] **Step 2: Run them to verify they fail.** Run: `uv run pytest -m bricscad tests/real/test_layers.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement**

`mcp:set-layer-now`: note whether `tblsearch` finds the layer, then `vla-add` (it returns an existing one). Apply color, linetype, then the three switches, then rename. Before freezing, fail with `Layer <name> is the current layer and cannot be frozen.` when it matches `CLAYER` (case-insensitive). Before renaming, fail for `0` and `DEFPOINTS` (`cannot be renamed`) and when the new name exists as a different layer (`already exists`). A rename differing only in case is allowed.

`mcp:ensure-linetype`: if `tblsearch "LTYPE"` finds nothing, `vla-load` it from `iso.lin` under `vl-catch-all-apply`, and on error fail with `Linetype <name> is not in this drawing or in iso.lin.`

`mcp:require-layer`: return the name if `tblsearch` finds it, else fail with `Layer <name> does not exist. Create it with bricscad_set_layer.`

- [ ] **Step 4: Run them to verify they pass.** Expected: PASS.

- [ ] **Step 5: Commit** with `feat: add bricscad_set_layer`.

### Task 4: Modify

**Files:** Modify `edit.lsp`, `edit.py`, `tests/test_tools_edit.py`, `tests/test_stdio.py`. Create `tests/real/test_modify.py`.

**Interfaces:**
- Consumes: `check_handles`, `mcp:edit-targets`, `mcp:require-layer`, `mcp:ensure-linetype`.
- Produces: `point3(p: list[float]) -> list[float]` in `shapes.py`. Python `modify_entities(bridge, handles, move=None, rotate=None, scale=None, layer=None, color=None, linetype=None, text=None, timeout=30.0) -> {"modified": int}`. `rotate` is `{"angle": degrees, "base": point}`, `scale` is `{"factor": >0, "base": point}`, `move` is a displacement. Tool parameters use pydantic models `Rotate` and `Scale`.

- [ ] **Step 1: Write the failing tests** in `tests/real/test_modify.py`

```python
def test_move_shifts_an_entity(real_session, blank):
    handle = line_at(real_session, 0, 0)
    edit.modify_entities(real_session.bridge, [handle], move=[5, 7])
    assert dxf_value(real_session, handle, 10) == [5.0, 7.0, 0.0]

def test_move_carries_attributes(real_session, blank):
    make_block_with_attributes(real_session, "TB", {"A": "x"})
    insert = read.read_attributes(real_session.bridge)["items"][0]["handle"]
    edit.modify_entities(real_session.bridge, [insert], move=[5, 0])
    position = read.find_text(real_session.bridge, "x")["items"][0]["position"]
    assert position[0] == pytest.approx(5.0)

def test_rotate_takes_degrees(real_session, blank):
    handle = circle_at(real_session, 5, 0, radius=1)
    edit.modify_entities(real_session.bridge, [handle], rotate={"angle": 90, "base": [0, 0]})
    assert dxf_value(real_session, handle, 10) == pytest.approx([0.0, 5.0, 0.0], abs=1e-9)

def test_scale_works_about_its_base(real_session, blank):
    handle = circle_at(real_session, 5, 5, radius=2)
    edit.modify_entities(real_session.bridge, [handle], scale={"factor": 2, "base": [0, 0]})
    assert dxf_value(real_session, handle, 10) == pytest.approx([10.0, 10.0, 0.0])
    assert dxf_value(real_session, handle, 40) == pytest.approx(4.0)

def test_sets_layer_and_color(real_session, blank):
    edit.set_layer(real_session.bridge, "A")
    handle = line_at(real_session, 0, 0)
    edit.modify_entities(real_session.bridge, [handle], layer="A", color=3)
    assert dxf_value(real_session, handle, 8) == "A" and dxf_value(real_session, handle, 62) == 3

def test_a_missing_layer_is_refused_and_not_created(real_session, blank):
    handle = line_at(real_session, 0, 0)
    with pytest.raises(LispError, match="Nope.*does not exist"):
        edit.modify_entities(real_session.bridge, [handle], layer="Nope")
    assert real_session.bridge.send('(if (tblsearch "LAYER" "Nope") 1 0)') == 0

@pytest.mark.parametrize("stored", ['a"b', "a\\b", "Načrt"])
def test_changes_text_exactly(real_session, blank, stored): ...  # entmake TEXT "old"; modify text=stored; find_text total 1 with text == stored

def test_changes_mtext_and_multileader_text(real_session, dxf_drawing): ...  # ezdxf one MTEXT, one text multileader; modify both to "changed"; find_text("changed") types are {"MTEXT", "MULTILEADER"}

def test_a_line_break_is_refused_on_single_line_text(real_session, blank): ...  # TEXT entity, text="a\nb", LispError match "one line"

def test_text_is_refused_on_an_entity_without_text(real_session, blank):
    with pytest.raises(LispError, match="LINE.*no text"):
        edit.modify_entities(real_session.bridge, [line_at(real_session, 0, 0)], text="x")

def test_a_locked_layer_is_refused_even_for_a_move(real_session, blank):  # vla-move ignores the lock
    handle = locked_line(real_session)
    with pytest.raises(LispError, match="locked"):
        edit.modify_entities(real_session.bridge, [handle], move=[5, 0])
    assert dxf_value(real_session, handle, 10) == [0.0, 0.0, 0.0]

def test_a_failure_part_way_changes_nothing(real_session, blank): ...  # one TEXT then one LINE, text="x"; LispError; the TEXT keeps its old value

def test_modify_is_one_undo_step(real_session, blank): ...  # layer, color and move in one call; one undo restores position and layer
```

Add `circle_at(session, x, y, radius=1.0)` to `tests/real/helpers.py`, and have `locked_line` draw from the origin.

Fast: `rotate={"angle": 180, "base": [1, 2]}` sends `(list 3.141592653589793 (list 1.0 2.0 0.0))` as its rotate argument. No change given, `scale` factor 0, a `move` of one number, and color outside 0 to 256 raise `BricsCADError` with nothing sent. Text `"a\nb"` is sent as `"a\\Pb"`.

- [ ] **Step 2: Run them to verify they fail.** Run: `uv run pytest -m bricscad tests/real/test_modify.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement**

Wire: `(mcp:modify-entities handles move rotate scale layer color linetype text)`, with absent values nil. Python normalises points with `point3`, converts degrees, and replaces `\r\n` and `\n` in `text` with `\P`.

`mcp:modify-entities-now`: validate targets, `require-layer` and `ensure-linetype` first. For each object, apply in this order: `vla-put-layer`, `vla-put-color`, `vla-put-linetype`, text, `vla-move`, `vla-rotate`, `vla-scaleentity`, with points through `vlax-3d-point`. For text, check `(vlax-property-available-p object 'TextString)` and fail with `<TYPE> has no text.` Fail with `TEXT holds one line. Use MTEXT for line breaks.` when the entity is TEXT and the text contains `\P`.

- [ ] **Step 4: Run them to verify they pass.** Expected: PASS.

- [ ] **Step 5: Commit** with `feat: add bricscad_modify_entities`.

### Task 5: Attributes

**Files:** Modify `edit.lsp`, `edit.py`, `tests/test_tools_edit.py`, `tests/test_stdio.py`. Create `tests/real/test_attributes.py`.

**Interfaces:**
- Consumes: `mcp:edit-targets`, `check_handles`.
- Produces: LISP `(mcp:apply-attribute-values object pairs)` returning the number of attributes set. Python `set_attributes(bridge, updates: list[dict], timeout=30.0) -> {"inserts": int, "attributes": int}`. Each update is `{"handle": str, "values": {tag: text}}`. Tool parameter uses a pydantic model `AttributeUpdate`.

- [ ] **Step 1: Write the failing tests** in `tests/real/test_attributes.py`

```python
def attrs(session):
    return read.read_attributes(session.bridge)["items"][0]

@pytest.mark.parametrize("value", ['a"b', "a\\b", "Načrt št. 1"])
def test_sets_a_value_exactly(real_session, blank, value):
    make_block_with_attributes(real_session, "TB", {"NASLOV": "old", "ST": "1"})
    result = edit.set_attributes(real_session.bridge, [{"handle": attrs(real_session)["handle"], "values": {"NASLOV": value}}])
    assert result == {"inserts": 1, "attributes": 1}
    assert attrs(real_session)["attributes"] == {"NASLOV": value, "ST": "1"}

def test_tags_match_whatever_the_case(real_session, blank): ...  # values={"naslov": "new"} changes NASLOV

def test_an_unknown_tag_changes_nothing_and_lists_the_tags(real_session, blank):
    make_block_with_attributes(real_session, "TB", {"NASLOV": "old"})
    updates = [{"handle": attrs(real_session)["handle"], "values": {"NASLOV": "new", "NOPE": "x"}}]
    with pytest.raises(LispError, match="NOPE.*NASLOV"):
        edit.set_attributes(real_session.bridge, updates)
    assert attrs(real_session)["attributes"]["NASLOV"] == "old"

def test_a_handle_that_is_not_an_insert_is_refused(real_session, blank): ...  # line handle, match "not a block insert"

def test_sets_attributes_on_a_dynamic_block(real_session, dxf_drawing): ...  # add_dynamic_block(dxf_drawing, "Glava", {"A": "old"}); set A; read_attributes block "Glava" shows new

def test_set_attributes_is_one_undo_step(real_session, blank): ...  # two tags; one undo restores both
```

Fast: an empty `updates` list or empty `values` raises with nothing sent. Wire is `(mcp:set-attributes (list (list "1A" (list (list "T" "v")))))`.

- [ ] **Step 2: Run them to verify they fail.** Expected: FAIL.

- [ ] **Step 3: Implement** `mcp:set-attributes-now`: `mcp:edit-targets` on the handles, fail with `<handle> is not a block insert with attributes.` unless type is INSERT and `vla-get-hasattributes` is true. `mcp:apply-attribute-values` then, for each given tag, sets every attribute from `(vlax-invoke object 'GetAttributes)` whose `vla-get-tagstring` matches case-insensitively, using `vla-put-textstring`. An unmatched tag fails with `No attribute <tag> on this insert. It has: <tags>.`

- [ ] **Step 4: Run them to verify they pass.** Expected: PASS.

- [ ] **Step 5: Commit** with `feat: add bricscad_set_attributes`.

### Task 6: Create geometry and text

**Files:** Create `src/bricscad_mcp/tools/shapes.py`, `tests/real/test_create.py`. Modify `edit.lsp`, `edit.py`, `tests/test_tools_edit.py`, `tests/test_stdio.py`.

**Interfaces:**
- Consumes: `mcp:require-layer`, `mcp:entity-item`.
- Produces: `shapes.Entity`, a union discriminated on `type`. Each model has `layer: str = "0"`, `extra="forbid"`, finite floats only, and `to_wire() -> list`. Python `create_entities(bridge, entities: list[dict | Entity], layout: str | None = None, timeout=30.0) -> {"created": [entity item], "count": int}`, validating with a `TypeAdapter` and raising `BricsCADError` on `ValidationError`. LISP `(mcp:space-groups layout)`, `(mcp:layout-name layout)`, and a dispatch `(mcp:make item layout)` that Task 7 extends.

| `type` | Fields (angles in degrees) | Wire list after type and layer |
|---|---|---|
| `line` | `start`, `end` | start3, end3 |
| `polyline` | `vertices` (2D, 2 or more), `bulges=None` (same length), `closed=False`, `elevation=0.0` | vertices, bulges, closed, elevation |
| `circle` | `center`, `radius > 0` | center3, radius |
| `arc` | `center`, `radius > 0`, `start_angle`, `end_angle` | center3, radius, start radians, end radians |
| `text` | `position`, `text`, `height > 0`, `rotation=0.0`, `style=None` | position3, text, height, radians, style |
| `mtext` | `position`, `text`, `height > 0`, `width=0.0`, `style=None` | position3, text with `\P`, height, width, style |

- [ ] **Step 1: Write the failing tests** in `tests/real/test_create.py`

```python
def make(session, *items, **kwargs):
    return edit.create_entities(session.bridge, list(items), **kwargs)

def test_creates_a_line_and_reports_it(real_session, blank):
    result = make(real_session, {"type": "line", "start": [0, 0], "end": [5, 5]})
    assert result["count"] == 1 and result["created"][0]["type"] == "LINE" and result["created"][0]["layout"] == "Model"

def test_creates_a_polyline_with_bulges(real_session, blank):
    handle = make(real_session, {"type": "polyline", "vertices": [[0, 0], [5, 0], [5, 5]], "bulges": [1, 0, 0], "closed": True, "elevation": 2.5})["created"][0]["handle"]
    assert dxf_value(real_session, handle, 70) == 1 and dxf_value(real_session, handle, 38) == 2.5
    assert dxf_value(real_session, handle, 42) == 1.0

def test_arc_angles_are_degrees(real_session, blank):
    handle = make(real_session, {"type": "arc", "center": [0, 0], "radius": 2, "start_angle": 0, "end_angle": 90})["created"][0]["handle"]
    assert dxf_value(real_session, handle, 51) == pytest.approx(math.pi / 2)

@pytest.mark.parametrize("stored", ['a"b', "a\\b", "Načrt št. 1"])
def test_text_round_trips(real_session, blank, stored):
    make(real_session, {"type": "text", "position": [1, 2], "text": stored, "height": 2.5})
    item = read.find_text(real_session.bridge, stored)["items"][0]
    assert item["text"] == stored and item["position"] == [1.0, 2.0, 0.0]

def test_long_mtext_round_trips(real_session, blank):
    text = "a" * 400 + " č " + "b" * 400
    make(real_session, {"type": "mtext", "position": [0, 0], "text": text, "height": 1, "width": 20})
    assert read.find_text(real_session.bridge, "č")["items"][0]["text"] == text

def test_mtext_newlines_become_line_breaks(real_session, blank):
    make(real_session, {"type": "mtext", "position": [0, 0], "text": "a\nb", "height": 1})
    assert read.find_text(real_session.bridge, "a")["items"][0]["text"] == "a\\Pb"

def test_a_missing_layer_is_refused_and_not_created(real_session, blank):
    with pytest.raises(LispError, match="Nope.*does not exist"):
        make(real_session, {"type": "line", "start": [0, 0], "end": [1, 1], "layer": "Nope"})
    assert real_session.bridge.send('(if (tblsearch "LAYER" "Nope") 1 0)') == 0

def test_a_missing_text_style_is_refused(real_session, blank): ...  # style="NoStyle", match "NoStyle"

def test_a_missing_layout_is_refused(real_session, blank): ...  # layout="NoLayout", match "NoLayout", entity_count 0

def test_draws_on_a_named_layout(real_session, blank):
    result = make(real_session, {"type": "line", "start": [0, 0], "end": [1, 1]}, layout="Layout1")
    assert result["created"][0]["layout"] == "Layout1"

def test_the_default_is_the_model_even_on_a_sheet(real_session, blank):
    real_session.bridge.send('(setvar "CTAB" "Layout1")')
    assert make(real_session, {"type": "line", "start": [0, 0], "end": [1, 1]})["created"][0]["layout"] == "Model"

def test_a_bad_item_leaves_nothing_behind(real_session, blank):
    good = {"type": "line", "start": [0, 0], "end": [1, 1]}
    with pytest.raises(LispError, match="Nope"):
        make(real_session, good, good, {**good, "layer": "Nope"})
    assert entity_count(real_session) == 0

def test_a_batch_is_one_undo_step(real_session, blank): ...  # three lines; one undo; entity_count 0
```

Fast, each raising `BricsCADError` with nothing sent: `radius` 0, `height` 0, NaN in a point, unknown `type`, unknown field, empty list, more than 2000 items, a one-vertex polyline, `bulges` of the wrong length, `text` type containing a newline. Wire: a line sends `(mcp:create-entities nil (list (list "line" "0" (list 0.0 0.0 0.0) (list 5.0 5.0 0.0))))`.

- [ ] **Step 2: Run them to verify they fail.** Run: `uv run pytest -m bricscad tests/real/test_create.py -q` and `uv run pytest tests/test_tools_edit.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `shapes.py`, the tool and the LISP**

`mcp:layout-name`: nil gives `"Model"`. Otherwise return the matching name from `(cons "Model" (layoutlist))`, compared case-insensitively, or fail with `Layout <name> does not exist.` `mcp:space-groups`: `((67 . 0) (410 . "Model"))` for the model, `((67 . 1) (410 . name))` for a sheet. `entmakex` for all six types, adding `(8 . layer)` and the space groups. A nil result fails with the item's type. Before making, `mcp:require-layer` always, and `style` must exist in `tblsearch "STYLE"`. Build the reply with `mcp:entity-item`.

- [ ] **Step 4: Run them to verify they pass.** Expected: PASS.

- [ ] **Step 5: Commit** with `feat: add bricscad_create_entities for geometry and text`.

### Task 7: Create dimensions, hatches and inserts

**Files:** Modify `shapes.py`, `edit.lsp`, `tests/real/test_create.py`, `tests/test_tools_edit.py`.

**Interfaces:**
- Consumes: `mcp:make`, `mcp:layout-name`, `mcp:space-groups`, `mcp:require-layer`.
- Produces: three more `shapes.Entity` members, and LISP `(mcp:space-object layout)` returning `(vla-get-block (vla-item (vla-get-layouts document) layout))`.

| `type` | Fields | Wire list after type and layer |
|---|---|---|
| `dimension` | `kind: "linear"\|"aligned" = "linear"`, `start`, `end`, `line_point`, `rotation=0.0` | kind, start3, end3, line_point3, radians |
| `hatch` | `points` (2D, 3 or more), `pattern="SOLID"`, `scale > 0 = 1.0`, `angle=0.0` | points, pattern, scale, radians |
| `insert` | `block` (not starting with `*`), `position`, `scale > 0 = 1.0`, `rotation=0.0`, `attributes: dict[str, str] = {}` | block, position3, scale, radians, tag and value pairs |

- [ ] **Step 1: Write the failing tests**, added to `tests/real/test_create.py`

```python
def test_linear_dimension_measures_its_points(real_session, blank):
    item = make(real_session, {"type": "dimension", "start": [0, 0], "end": [10, 0], "line_point": [5, 4]})["created"][0]
    assert item["type"] == "DIMENSION"
    assert dxf_value(real_session, item["handle"], 13) == [0.0, 0.0, 0.0]
    assert dxf_value(real_session, item["handle"], 14) == [10.0, 0.0, 0.0]

def test_aligned_dimension_is_aligned(real_session, blank):
    handle = make(real_session, {"type": "dimension", "kind": "aligned", "start": [0, 0], "end": [10, 5], "line_point": [5, 8]})["created"][0]["handle"]
    subclasses = [value for code, value in read.get_entity(real_session.bridge, handle)["dxf"] if code == 100]
    assert "AcDbAlignedDimension" in subclasses and "AcDbRotatedDimension" not in subclasses

def test_hatch_leaves_only_the_hatch(real_session, blank):
    item = make(real_session, {"type": "hatch", "points": [[0, 0], [10, 0], [10, 10], [0, 10]], "pattern": "ANSI31", "scale": 2, "angle": 45})["created"][0]
    assert entity_count(real_session) == 1 and item["type"] == "HATCH"
    assert dxf_value(real_session, item["handle"], 2) == "ANSI31" and dxf_value(real_session, item["handle"], 41) == 2.0
    assert dxf_value(real_session, item["handle"], 52) == pytest.approx(math.pi / 4)

def test_an_unknown_hatch_pattern_leaves_nothing(real_session, blank):
    with pytest.raises(LispError, match="NOPE99"):
        make(real_session, {"type": "hatch", "points": [[0, 0], [1, 0], [1, 1]], "pattern": "NOPE99"})
    assert entity_count(real_session) == 0 and real_session.bridge.send('(getvar "CMDACTIVE")') == 0

def test_inserts_a_block_with_attributes(real_session, blank):
    define_block_with_attribute_definitions(real_session, "TB", ["NASLOV", "ST"])
    make(real_session, {"type": "insert", "block": "TB", "position": [3, 4], "scale": 2, "attributes": {"naslov": "Načrt"}})
    item = read.read_attributes(real_session.bridge)["items"][0]
    assert item["block"] == "TB" and item["attributes"]["NASLOV"] == "Načrt"

def test_an_unknown_block_leaves_nothing(real_session, blank): ...  # match "Nope", entity_count 0

def test_an_unknown_attribute_tag_leaves_nothing(real_session, blank): ...  # match "NOPE", entity_count 0

@pytest.mark.parametrize("item", [dimension_item, hatch_item])
def test_dimensions_and_hatches_land_on_the_layout(real_session, blank, item): ...  # layout="Layout1"; created layout == "Layout1"; layer "A" reported when given
```

`define_block_with_attribute_definitions` is the block-definition half of `make_block_with_attributes` in `tests/real/helpers.py`; split that helper so both use it.

Fast: `kind="angular"`, a two-point hatch, `block="*U1"` and hatch `scale` 0 raise with nothing sent.

- [ ] **Step 2: Run them to verify they fail.** Expected: FAIL.

- [ ] **Step 3: Implement** in `mcp:make`, with each new object taking its layer through `vla-put-layer` and its handle turned into an ename with `vlax-vla-object->ename`.

- Dimension: `vla-adddimrotated` (three `vlax-3d-point`s and rotation) or `vla-adddimaligned` on `mcp:space-object`.
- Hatch: `entmakex` a closed LWPOLYLINE boundary with the space groups. `vla-addhatch` (pattern type 1, name, `:vlax-false`) under `vl-catch-all-apply`, failing with `Hatch pattern <name> was not found.` Then `vla-put-patternscale`, `vla-put-patternangle`, `vla-appendouterloop` with a one-object `vlax-vbobject` safearray, `vla-evaluate`, and `entdel` the boundary.
- Insert: `tblsearch "BLOCK"` or fail with `Block <name> does not exist in this drawing.` `vla-insertblock`, then `mcp:apply-attribute-values`.

- [ ] **Step 4: Run them to verify they pass.** Run: `uv run pytest -m bricscad tests/real/test_create.py -q`. Expected: PASS.

- [ ] **Step 5: Commit** with `feat: add dimensions, hatches and block inserts`.

### Task 8: Save

**Files:** Modify `edit.lsp`, `edit.py`, `tests/test_tools_edit.py`, `tests/test_stdio.py`. Create `tests/real/test_save.py`.

**Interfaces:**
- Consumes: `mcp:drawing-info`, `mcp:cancel-command`.
- Produces: Python `save_drawing(bridge, path: str | None = None, overwrite: bool = False, timeout: float = 120.0) -> dict`, returning `mcp:drawing-info`. LISP `(mcp:save-state)` returning `{"path", "titled", "read_only", "other_open": [paths]}`, `(mcp:save-as path overwrite)`, `(mcp:qsave)`.

Checks in `save_drawing`, in order, each raising before any save request:

| Case | Result |
|---|---|
| No path, drawing unnamed | `BricsCADError`: give a path |
| No path, read-only | `SafetyRefused`: must be saved to a new path |
| No path, `overwrite` false | `SafetyRefused`: pass `overwrite=true` to save over the open file |
| Suffix is not `.dwg` (any case) | `BricsCADError`, naming `bricscad_export_dxf` in Phase 3 |
| Target is a folder, or its parent is not a folder | `BricsCADError` |
| Target is the current file and the drawing is read-only | `SafetyRefused`, even with `overwrite=true` |
| Target is open as another drawing | `SafetyRefused`, even with `overwrite=true`: close it first |
| Target exists and `overwrite` false | `SafetyRefused`: pass `overwrite=true` |
| Target exists and is not writable (`os.access`) | `SafetyRefused`, even with `overwrite=true` |

"The same file" means `os.path.samefile` when both exist, else equal absolute paths.

- [ ] **Step 1: Write the failing tests**

`tests/test_tools_edit.py`: one test per row above, each through `started.call_tool`, asserting `result.is_error`, that the message names the parameter or rule, and that no `mcp:save-as` or `mcp:qsave` reached `fake.requests`. Set `fake.responses["mcp:save-state"]` per case. Plus:

```python
async def test_a_symlink_to_the_read_only_file_is_the_same_file(started, fake, tmp_path):
    real = tmp_path / "a.dwg"; real.write_bytes(b"AC1032")
    link = tmp_path / "b.dwg"; link.symlink_to(real)
    fake.responses["mcp:save-state"] = {"path": str(real), "titled": 1, "read_only": True, "other_open": []}
    result = await started.call_tool("bricscad_save_drawing", {"path": str(link), "overwrite": True})
    assert result.is_error and not any("mcp:save-as" in r for r in fake.requests)

async def test_a_new_file_goes_through(started, fake, tmp_path):
    fake.responses["mcp:save-state"] = {"path": "/x/y.dwg", "titled": 1, "read_only": False, "other_open": []}
    fake.responses["mcp:save-as"] = {"name": "Načrt 1.dwg"}
    target = tmp_path / "Načrt 1.dwg"
    await started.call_tool("bricscad_save_drawing", {"path": str(target)})
    assert fake.requests[-1] == f'(mcp:save-as "{target.as_posix()}" nil)'
```

`tests/real/test_save.py`:

```python
def test_save_as_writes_the_file_and_adopts_it(real_session, blank, tmp_path):
    line_at(real_session, 0, 0)
    target = tmp_path / "Načrt št 1.dwg"
    info = edit.save_drawing(real_session.bridge, str(target))
    assert target.exists() and info["name"] == target.name and info["modified"] is False

def test_read_only_source_is_untouched_by_saving_a_copy(real_session, tmp_path):  # no blank: make_dwg saves and closes the current drawing
    source = make_dwg(real_session, tmp_path / "a.dwg")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    open_drawing(real_session.bridge, str(source))
    line_at(real_session, 2, 2)
    info = edit.save_drawing(real_session.bridge, str(tmp_path / "b.dwg"))
    close_drawing(real_session.bridge)
    assert info["read_only"] is False and hashlib.sha256(source.read_bytes()).hexdigest() == digest

def test_saving_in_place_needs_overwrite_and_then_works(real_session, blank, tmp_path): ...  # save as new; add line; no path refused; overwrite=True saves; modified False

def test_overwrite_replaces_another_file(real_session, blank, tmp_path): ...  # target holds b"AC1032 placeholder"; overwrite=True; size changes; CMDACTIVE 0

def test_lisp_refuses_a_file_that_appeared_after_the_check(real_session, blank, tmp_path):
    target = tmp_path / "late.dwg"; target.write_bytes(b"AC1032 placeholder")
    size = target.stat().st_size
    with pytest.raises(LispError, match="exists"):
        real_session.bridge.send(call("mcp:save-as", target.as_posix(), False))
    assert target.stat().st_size == size and real_session.bridge.send('(getvar "CMDACTIVE")') == 0

def test_lisp_reports_a_save_that_did_not_happen(real_session, blank, tmp_path):
    with pytest.raises(LispError, match="did not save"):
        real_session.bridge.send(call("mcp:save-as", (tmp_path / "missing" / "x.dwg").as_posix(), False))

def test_undo_still_works_after_a_save(real_session, blank, tmp_path): ...  # create a line; save; undo undone == 1; entity_count 0
```

Mark the symlink and not-writable fast tests `skipif(sys.platform == "win32")`.

- [ ] **Step 2: Run them to verify they fail.** Run: `uv run pytest tests/test_tools_edit.py -q -k save` and `uv run pytest -m bricscad tests/real/test_save.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement**

`mcp:save-state`: `path` from `DWGPREFIX` plus `DWGNAME`, `titled` from `DWGTITLED`, `read_only` from `vla-get-readonly`, and `other_open` from `vla-get-fullname` of every other document with a non-empty path (`vlax-for` over `mcp:documents`).

`mcp:save-as`: `(command "_.SAVEAS" "" path)`. If `CMDACTIVE` is then above 0, send `(command "_Y")` when `overwrite` is true, or else `mcp:cancel-command` and fail with `<path> already exists.` Afterwards compare `DWGPREFIX` plus `DWGNAME` with `path`, case-insensitively, and fail with `BricsCAD did not save to <path>.` on a mismatch. Return `(mcp:drawing-info)`. Saving is not wrapped in `mcp:edit`, so it adds no undo step.

`mcp:qsave`: `(command "_.QSAVE")`, fail with `BricsCAD did not save the drawing.` unless `vla-get-saved` is true, return `(mcp:drawing-info)`.

The tool docstring says a save leaves a `.bak` beside an overwritten file.

- [ ] **Step 4: Run them to verify they pass.** Expected: PASS.

- [ ] **Step 5: Commit** with `feat: add bricscad_save_drawing`.

### Task 9: End to end, docs and full run

**Files:** Modify `tests/real/test_end_to_end.py`, `README.md`, `docs/phase-0-results.md`.

**Interfaces:**
- Consumes: all seven tools over stdio.

- [ ] **Step 1: Write the failing test** `test_stdio_server_full_edit_flow` in `tests/real/test_end_to_end.py`, over the real command as in `test_stdio_server_full_read_flow`:

Start, make a source drawing and save it as `Načrt št 1.dwg`, close it, open it read-only, `bricscad_set_layer` `Stene`, `bricscad_create_entities` a closed polyline and a text on it, `bricscad_modify_entities` the text, `bricscad_undo` once and assert the text is back, `bricscad_save_drawing` to `kopija.dwg`, `bricscad_stop`. Assert the source's SHA-256 is unchanged, `kopija.dwg` exists, and no `Drawing[0-9]*` files appeared in `~/Documents` or `~/Downloads`.

- [ ] **Step 2: Run it to verify it fails, then fix anything it finds, test first.** Run: `uv run pytest -m bricscad tests/real/test_end_to_end.py -q`.

- [ ] **Step 3: Update the docs**

`README.md`: add the seven tools to the table at `## Tools`, and to `## Safety` add: edits are all-or-nothing and one undo step each; `bricscad_run_lisp` edits have no step of their own; locked layers are refused; saving rules. `docs/phase-0-results.md`: add `## Found while planning Phase 2, 09.11.2026` with the probed behaviour table from this plan.

- [ ] **Step 4: Run everything**

Run: `uv run pytest -q` then `uv run pytest -m bricscad -q`, in the background, about 15 minutes.
Expected: all pass. Check no V26 is left running and any V25 is untouched.

- [ ] **Step 5: Commit** with `docs: describe the draw and edit tools`.
