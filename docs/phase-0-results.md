# Phase 0 results

Tested on 2026-11-06: BricsCAD V26.1.6 Lite, macOS (Intel build, `Mac OS X Version 27.0 (x86_64)`).
Probes live in `scripts/phase0/`. Run one with `python3 scripts/phase0/run_probe.py <probe>.lsp`.
All tests used temporary drawings. Nothing here has been checked on Windows or Linux.

## Summary

No spec fallback is needed. PDF plotting, read-only opening, switching drawings and
non-ASCII text all work without dialogs. Closing needs care, as set out below.

| Question | Answer |
|---|---|
| Does opening another drawing stop the listener? | No. LISP continues and moves to the newly opened drawing |
| Can a drawing open read-only without a dialog? | Yes, with `vla-open` |
| How does `_.SAVEAS` behave when the target exists? | Prompts once on the command line; answer `_Y` |
| Can PDF plotting run with no dialog? | Yes, with `_.-PLOT` |
| Do non-ASCII characters survive? | Yes: LISP source, files, layer names, text and paths |
| Does the listener block the window? | It repaints, but stops answering accessibility requests |
| Idle CPU of the poll loop | 2.5% of one core |

## Working sequences

### Opening

`(vla-open (vla-get-documents (vlax-get-acad-object)) path :vlax-true)` opens read-only.
Pass `:vlax-false` for read-write. LISP continues in the new document: `DWGNAME`,
`ssget` and `entmakex` all act on it.

Read back the state with `(vla-get-readonly (vla-get-activedocument (vlax-get-acad-object)))`,
which returns `:VLAX-TRUE`. `WRITESTAT` reports 0 and does not reflect this, and `READONLY`
does not exist. `-OPEN` does not exist.

A read-only document can still be edited in memory and saved to a new path with `_.SAVEAS`.
The source file's size stayed the same.

`(command "_.OPEN" path)` also works, without a dialog, but has no read-only option.

Opening does not close the previous document, so the count goes up. Close documents
explicitly.

### Closing

Use `(vla-close doc :vlax-false)`. It closes without saving, shows no dialog, and LISP moves
to the remaining document.

**Do not use `_.CLOSE`.** On a modified drawing it prompts, and `_Y` means **save**: the
probe's file changed and a `.bak` appeared.

**Never close the only open document.** LISP stops running and the listener is gone, while
BricsCAD stays open. In the probe, this hung until the process was terminated. To close the
last real drawing, make a blank one first with `(vla-add docs)`, then close the real one.
LISP moves to the new `Drawing2.dwg` and can draw there.

### Quitting

`(command "_.QUIT" "_Y")` **discards** changes and exits with no dialog. A modified named drawing
kept its size and got no `.bak`. This is the opposite of `_.CLOSE`, where `_Y` saves.

`(vla-get-saved doc)` returns `:VLAX-FALSE` once a document has changed, so it can be used to count
unsaved documents before quitting.

### Saving

- `(command "_.SAVEAS" "" path)` saves with no dialog. `""` accepts the default file version, 2018.
- If `path` exists, the command stays active (`CMDACTIVE` 1). Send `(command "_Y")` to replace it.
  This leaves a `.bak` beside the target.
- `(command "_.QSAVE")` saves a named drawing with no dialog, and writes a `.bak`.
- `vla-save` opens a dialog. `vla-saveas` fails with `E_INVALIDARG`. Do not use either.

### Plotting to PDF

Exact order of answers to `(command "_.-PLOT")`, each sent as `(command answer)`:

| # | Prompt | Answer |
|---|---|---|
| 1 | Detailed plot configuration? | `_Y` |
| 2 | Layout name | `Model` or the layout name |
| 3 | Output device | `Print As PDF.pc3` |
| 4 | Paper size | `""` for the current size (ISO A4 in the test) |
| 5 | Paper units | `""` |
| 6 | Orientation | `""` |
| 7 | Upside down? | `""` |
| 8 | Plot area | `_E` for extents |
| 9 | Scale | `_F` for fit |
| 10 | Offset | `_C` for centre |
| 11 | Plot styles? | `_Y` |
| 12 | Style table | `""` |
| 13 | Lineweights? | `_Y` |
| 14 | Shade plot | `""` |
| 15 | File name | full path |
| 16 | Save changes to layout? | `_N` |
| 17 | Proceed? | `_Y` |

The probe wrote a 1467-byte PDF. Its contents were not inspected. `Print As PDF.pc3` was found
in this user's `PlotConfig` folder; other installs may differ. `EXPORTPDF`, `EXPORT`, `PUBLISH`,
`-PUBLISH` and `PLOT` also exist, and `-EXPORT`, `PDFEXPORT` and `-PDFEXPORT` do not.

### Non-ASCII text

`č š ž Č Š Ž` round-tripped unchanged:

- Literal strings in a UTF-8 `.lsp`: `strlen` 6, code points 269, 353, 382, 268, 352, 381
- `open` for writing, default and with `"utf8"`: identical UTF-8 bytes, no byte order mark
- `open` for reading a UTF-8 file, default and with `"utf8"`
- Layer names, `TEXT` entities, and a path such as `Načrt št 1.dwg`

Use `(open path mode "utf8")` explicitly, because defaults on other platforms may differ.
`"ccs=UTF-8"` is rejected. `vle-file-encoding` reports `"ANSI"` for a UTF-8 file with no byte
order mark, so do not rely on it.

### Listener loop

- `(command "_.DELAY" 250)` gives about 2 loops per second (59 in 30 seconds), so a request waits
  about 0.25 to 0.5 seconds before it starts.
- Idle CPU is 2.5% of one core, including rewriting a heartbeat file on each loop.
- While looping, the window repaints, but it did not answer an accessibility request and the
  click test could not run. Whether a person can use it by hand was not checked. Treat the
  window as occupied.

### Helpers

| Form | Result |
|---|---|
| `(vle-getboundingbox ename)` | Works: `((0 0 0) (100 100 0))` |
| `(vle-getgeomextents ename)` | Works, with the same shape |
| `vla-getboundingbox` | Returned zeros. Do not use |
| `(ssget "_X" filter)` with no match | Returns `nil`, so guard before `sslength` |
| `(vl-file-rename a b)` | Returned `T` when `b` existed; the replacement was not confirmed, so use unique names |
| `(vle-file->list path)` | Needs more arguments; not used |
| `(layoutlist)` | Works, and excludes Model |
| `(vla-get-version ...)` | Does not exist |

## Found later, by the real test set

- Opening a drawing whose xref file is missing shows no dialog, and the audit reports it as missing.
- A relative xref path such as `./x.dwg` beside the drawing is found by `findfile`. Paths like
  `../x.dwg` have not been tested.
- A `.dxf` opens with `vla-open`, read-only, with no dialog.
- Opening a file that is already open shows no dialog.
- `_.QUIT _Y` answers for one document only. A second modified document blocks at its own prompt, so
  close the others with `vla-close` first. A modified read-only document discards without a prompt.
- Two copies of the same version: the second starts, but its `-b` script does not run.
- `vla-attachexternalreference` does not exist. `_.-XREF _A` attaches an xref, and `vla-put-path` changes
  its stored path.

## Found by the first real drawing, 06.11.2026

- Missing fonts show no dialog. BricsCAD prints the substitution on the command line.
- While the listener runs, the window can keep showing `Drawing1` with another drawing open and current.
- Each state of a dynamic block is an anonymous block such as `*U276`, and inserts use that name.
  The anonymous block's BLOCK_RECORD holds xdata `AcDbBlockRepBTag`, with group 1005 the handle of the
  source BLOCK_RECORD. On that drawing this matched `vla-get-effectivename` for all 38 anonymous inserts.
- `vla-get-effectivename` returns the anonymous name for a block that has this xdata but none of the
  dynamic block's other data. `vla-get-isdynamicblock` is then false.
- BricsCAD renames anonymous blocks when it loads a DXF, for example `*U1` to `*U4`.
- `entmod` returns nil on a BLOCK_RECORD. `vla-setxdata` failed on both a block and a line, with
  `DISP_E_PARAMNOTFOUND` or `E_INVALIDARG`. `entmake` of a BLOCK with xdata stores it on the BLOCK entity,
  not the BLOCK_RECORD. Tests use a DXF written with `ezdxf` instead.
- On a MULTILEADER, group 11 is a normal `(0 0 1)` and the last group 10 a scale `(1 1 1)`. Group 110 is its location.
- An insert of an anonymous block with no entities has no bounding box.

## Found while planning Phase 2, 09.11.2026

Probed on temporary drawings, before the draw and edit tools were written.

| Behaviour | Consequence |
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

## Open points

- `FILEDIA` read `0` at the start of every `-b` run. Whether that is the user's stored value or
  an effect of running a script is unknown. The tested calls work at that value, and the server
  must not rely on it or change it.
- A `-b` run starts with `Drawing1.dwg` as an open, unnamed document.
