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

## Open points

- `FILEDIA` read `0` at the start of every `-b` run. Whether that is the user's stored value or
  an effect of running a script is unknown. The tested calls work at that value, and the server
  must not rely on it or change it.
- A `-b` run starts with `Drawing1.dwg` as an open, unnamed document.
