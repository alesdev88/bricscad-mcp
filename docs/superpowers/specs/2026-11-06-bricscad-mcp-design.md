# BricsCAD MCP: design

Date: 2026-11-06
Status: approved

## Purpose

Let Claude, or any MCP client, work with BricsCAD through tools: read and audit
drawings, draw and edit in 2D, plot and export, and run jobs across many files.

No existing MCP server does this on macOS. `multiCAD-mcp` covers BricsCAD on
Windows through COM only. This project uses a LISP bridge instead, because LISP
is available at every licence level and on all three platforms.

## Success criteria

1. From an MCP client, start BricsCAD, open a drawing, read its contents, change
   it, save to a new path and export a PDF, with no human input and no dialogs.
2. An original drawing cannot be changed unless the call explicitly asks for it.
3. A failed or stuck command returns a clear error rather than hanging the client.
4. The same tools and the same behaviour apply on macOS, Windows and Linux.

## Platform support

There is one shared core and one small module per platform. All three platforms
are in scope from the start, but they differ in how far they can be verified.

| Platform | Server logic tests | Real BricsCAD tests | Status at first release |
|---|---|---|---|
| macOS | CI | Run locally on V26 | Supported |
| Windows | CI | Not run: no test machine yet | Experimental |
| Linux | CI | Not run: no test machine yet | Experimental |

A platform becomes "Supported" only when the real-BricsCAD test set passes on it.
The README must state this status. Passing CI does not make a platform supported,
because CI has no BricsCAD.

The platform module owns only:

- finding installed BricsCAD versions
- building and running the launch command
- checking whether the started process is alive and stopping it
- default folders, with file paths normalised to forward slashes for LISP

Install locations for Windows and Linux are unverified assumptions. Each can be
overridden with `BRICSCAD_EXECUTABLE`:

- macOS: `/Applications/BricsCAD V*.app`, launched with `open -n -a <app> --args -b <script>`
- Windows: `C:\Program Files\Bricsys\BricsCAD V* */bricscad.exe`, launched directly with `/B <script>`
- Linux: `/opt/bricsys/bricscad/v*/bricscad.sh`, launched directly with `-b <script>`

Windows uses the same LISP bridge rather than COM, so behaviour stays the same
everywhere.

## Licence levels

The design targets BricsCAD Lite, the level on the development machine. It uses
LISP only. BRX, BIMPYTHON and 3D modelling tools are out of scope.

## Findings this design relies on

Tested on BricsCAD V26.1.6 Lite, macOS:

- `-b script.lsp` starts BricsCAD and runs the script.
- A LISP loop can pick up a file dropped by another process and return a result.
- `_.SAVEAS` and `_.QSAVE` through `command` save without a dialog.
- `vla-save` opens a Save dialog on an unnamed drawing, and probably on a named
  one. It must not be used.
- `vla-saveas` fails with `E_INVALIDARG` regardless of path length. It must not
  be used.
- `FILEDIA` read `0` at the start of the script run. The cause is unconfirmed, so
  no code may assume a value for it.

These may differ on Windows and Linux. The real-BricsCAD test set checks them.

## Architecture

```
MCP client ── stdio ──> Python server ── queue folder ──> LISP listener in BricsCAD
                        (tools, safety,  <── JSON reply ──  (runs one request
                         platform module)                    at a time)
```

### Units

| Unit | Responsibility | Depends on |
|---|---|---|
| `server.py` | Registers tools, formats results | `tools/` |
| `tools/` | One module per phase; validates input, applies safety rules, builds LISP | `bridge.py` |
| `bridge.py` | Writes requests, waits for replies, handles timeouts | Queue folder only |
| `session.py` | Starts and stops BricsCAD, tracks listener health | `bridge.py`, `platforms/` |
| `platforms/` | `base.py`, `macos.py`, `windows.py`, `linux.py` | Operating system |
| `lisp/listener.lsp` | Polls the queue, runs requests, writes replies | BricsCAD |
| `lisp/json.lsp` | Encodes LISP values as JSON | Nothing |
| `lisp/*.lsp` | Tool helpers for read, edit, export | `json.lsp` |

### Request flow

1. A tool builds a LISP expression and assigns a unique request id.
2. `bridge.py` writes `<id>.tmp`, then renames it to `<id>.lsp`, so the listener
   never reads a partial file.
3. The listener finds the oldest `.lsp`, runs it under `vl-catch-all-apply`, and
   writes the reply to `<id>.tmp`, then renames it to `<id>.json`.
4. `bridge.py` reads the reply, removes both files and returns the result.

Reply format:

```json
{"id": "...", "ok": true, "result": {}, "error": null, "elapsed_ms": 12}
```

The queue folder lives in the per-user state folder with owner-only permissions,
because anything placed in it runs as LISP. Each session uses a new folder.

### Listener health

The listener updates a heartbeat file on every poll. `bricscad_status` reports the
process state, the heartbeat age and the current drawing.

A request timeout returns a distinct error. The error states that a dialog may be
blocking BricsCAD, how old the heartbeat is, and that the user should check the
BricsCAD window. Timeouts are 30 seconds by default and can be set per call.

## Tools

All tools use the `bricscad_` prefix. List tools take `limit` and `offset`, and
report the total. Every tool carries MCP read-only or destructive annotations.

### Phase 1: core and read/audit

- `bricscad_list_versions`, `bricscad_start`, `bricscad_stop`, `bricscad_status`
- `bricscad_open_drawing`, `bricscad_close_drawing`, `bricscad_drawing_info`
- `bricscad_list_layers`, `bricscad_list_blocks`, `bricscad_list_xrefs`,
  `bricscad_list_layouts`
- `bricscad_query_entities` (filter by type, layer, block and bounding box)
- `bricscad_get_entity`
- `bricscad_read_attributes` (for example, title block contents)
- `bricscad_find_text`
- `bricscad_audit_report` (summary: empty layers, unused blocks, missing xrefs,
  non-zero-elevation entities, off-standard layer names against an optional list)
- `bricscad_run_lisp` (destructive annotation; each call goes through the client's
  tool approval, because LISP can delete files and start programs)

### Phase 2: draw and edit

- `bricscad_create_entities` (line, polyline, circle, arc, text, mtext, dimension,
  hatch, block insert)
- `bricscad_modify_entities`, `bricscad_erase_entities`
- `bricscad_set_layer` (create or change layers)
- `bricscad_set_attributes`
- `bricscad_undo`
- `bricscad_save_drawing`

### Phase 3: plot and export

- `bricscad_export_dxf`
- `bricscad_plot_pdf`
- `bricscad_preview_image` (returns an image so Claude can check its own results)

### Phase 4: batch

- `bricscad_batch_run`: applies a named job or LISP expression to a list of files
  or a folder pattern. It has a dry-run option, a result per file, continues after
  a failure, and writes to an output folder by default.

## Safety rules

1. Saving over an existing file requires `overwrite=true`. The server checks this
   before sending anything to BricsCAD.
2. `bricscad_open_drawing` opens read-only by default. Edits on a read-only drawing
   must be saved to a new path.
3. `bricscad_batch_run` never writes to its source files unless `overwrite=true`.
4. Only `_.SAVEAS` and `_.QSAVE` are used for saving.
5. The server does not permanently change BricsCAD settings. Any variable changed
   during a command is restored in the same request, and is restored on error too.
6. `bricscad_start` always starts a new BricsCAD process and never attaches to one
   already running. `bricscad_stop` stops only the process that server started, and
   refuses if it has unsaved changes unless `discard=true`.
7. File paths from requests are passed as escaped LISP strings, never inserted as
   raw LISP.

## Phase 0: tests that come first

These unknowns can change the design, so they are tested before phase 1 code, on
macOS V26. Results are recorded in `docs/phase-0-results.md`.

| Question | Passes when | If it fails |
|---|---|---|
| Does opening another drawing stop the listener? | Listener answers after `_.OPEN` | Try `SDI=1`, then load the listener in each drawing with `/LD`, then a new process per file |
| Can a drawing open read-only without a dialog? | Opens, and `DWGWRITE` or equivalent reports read-only | Open a temporary copy; xref paths need handling |
| How does `_.SAVEAS` behave when the target exists? | Known prompt sequence, no dialog | Save to a temporary name, then replace the file from Python |
| Can PDF plotting run with no dialog? | PDF exists and is not empty | Investigate `-PLOT` and `-EXPORT`; descope if neither works |
| Do non-ASCII characters survive? (`č š ž` in paths, layer names, text) | Round trip is unchanged in both directions | Force a file encoding in `open`, or escape as `\U+XXXX` |
| Does the listener block the window? | Behaviour documented | Documentation only |
| Does the poll loop use noticeable CPU when idle? | Under about 5% of one core | Lengthen the delay |

## Error handling

| Case | Behaviour |
|---|---|
| LISP error in a request | `ok: false` with the message; the listener keeps running |
| Timeout | Error mentions a possible dialog and the heartbeat age; the request file is removed if it has not been picked up |
| Process has died | Error says so and suggests `bricscad_start`; pending requests fail immediately |
| BricsCAD not running | Error suggests `bricscad_start` |
| Save refused by safety rule | Error names the rule and the parameter that would allow it |
| Result too large | Truncated, with `total` and a suggested `offset` |

Late replies to requests that have already timed out are discarded, and every
reply is matched by id.

## Testing

- **Unit tests (CI on macOS, Windows, Linux through GitHub Actions):** safety rules,
  LISP string escaping, path normalisation, platform discovery with a fake file
  system, and bridge timeouts.
- **Fake listener (CI):** a Python stand-in that follows the queue protocol, so the
  server runs end to end without BricsCAD.
- **LISP tests:** `json.lsp` and tool helpers run inside BricsCAD.
- **Real-BricsCAD tests (local, `pytest -m bricscad`):** every tool, using only
  temporary drawings created by the test. They never open a user's file. This is
  the test set that makes a platform "Supported".

## Project setup

- Python 3.11 or newer, the official `mcp` SDK, `uv` for packaging, stdio transport
- Default target is the newest installed version; override with `BRICSCAD_VERSION`
- Repository: private, `alesdev88/bricscad-mcp`
- No licence file while the repository is private

## Out of scope

- Controlling a BricsCAD session the user is drawing in (a keystroke trigger could
  be added later)
- Hidden-window operation, including the Windows-only `/Automation` switch
- 3D modelling, BIM, BRX and BIMPYTHON
- Windows COM
- Remote or HTTP transport
- Parallel requests or more than one BricsCAD process per server

## Build order

Phase 0 tests, then phases 1 to 4 in order. Each phase ends with its real-BricsCAD
tests passing on macOS. Windows and Linux modules are written in phase 1 and stay
experimental until the same tests pass on those platforms.
