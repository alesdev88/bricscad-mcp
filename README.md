# BricsCAD MCP

An MCP server that lets Claude, or any MCP client, read and audit drawings in BricsCAD.
It starts its own BricsCAD window and controls it through a small LISP listener, so it works
at every licence level, including Lite, and doesn't need Windows COM.

Status: Phase 1 of 4. Reading and auditing work. Drawing and editing, plotting, and batch jobs
are planned.

## Platform support

| Platform | Server logic tests | Real BricsCAD tests | Status |
|---|---|---|---|
| macOS | CI | Passed on V26.1.6 Lite | Supported |
| Windows | CI | Not run: no test machine yet | Experimental |
| Linux | CI | Not run: no test machine yet | Experimental |

A platform becomes Supported only when the real BricsCAD tests pass on it. CI has no BricsCAD.
The Windows and Linux install locations are unverified, so set `BRICSCAD_EXECUTABLE` if yours is
not found.

## Install

You need [uv](https://docs.astral.sh/uv/) and BricsCAD.

```bash
git clone https://github.com/alesdev88/bricscad-mcp.git
```

```bash
cd bricscad-mcp && uv sync
```

Register it with Claude Code, using the full path to your copy:

```bash
claude mcp add bricscad -- uv --directory "/full/path/to/bricscad-mcp" run bricscad-mcp
```

## Tools

| Tool | What it does |
|---|---|
| `bricscad_list_versions` | Lists installed versions |
| `bricscad_start` / `bricscad_stop` | Starts or closes the server's own BricsCAD |
| `bricscad_status` | Reports whether it's running, listener health and the current drawing |
| `bricscad_open_drawing` / `bricscad_close_drawing` | Opens a DWG or DXF (read-only by default), or closes it |
| `bricscad_drawing_info` | Name, path, state, units, entity count, layouts, and the limits and extents of the current layout |
| `bricscad_list_layers` / `_blocks` / `_xrefs` / `_layouts` | Lists what's in the drawing |
| `bricscad_query_entities` | Finds entities by type, layer, block, layout or bounding box |
| `bricscad_get_entity` | Returns all DXF values for one entity |
| `bricscad_read_attributes` | Reads block attributes, such as title block contents |
| `bricscad_find_text` | Searches TEXT, MTEXT, MULTILEADER, table cell and attribute text |
| `bricscad_audit_report` | Empty layers, unused blocks, missing xrefs, raised entities, off-standard layer names |
| `bricscad_create_entities` | Draws lines, polylines, circles, arcs, text, MTEXT, dimensions, hatches and block inserts |
| `bricscad_modify_entities` | Moves, rotates, scales, or changes layer, color, linetype or text |
| `bricscad_erase_entities` | Erases entities by handle |
| `bricscad_set_layer` | Creates or changes a layer |
| `bricscad_set_attributes` | Sets block attribute values, such as title block contents |
| `bricscad_undo` | Undoes edit tool calls, one step each |
| `bricscad_save_drawing` | Saves to a new path, or over the open file with `overwrite=true` |
| `bricscad_run_lisp` | Runs LISP for anything the other tools don't cover |

List tools take `limit` and `offset` and report `total`. The default limit is 200 and the maximum
is 2000.

## Good to know

- **One copy per version.** `bricscad_start` refuses if that BricsCAD version is already running,
  because a second copy of the same version doesn't start its listener. Close it first, or choose
  another version with `BRICSCAD_VERSION`.
- **The window is occupied.** While the listener runs, its BricsCAD window isn't meant for hand use,
  and it may not show the open drawing. Trust the tools, not the window. Draw in a copy of another
  version, or stop the server first.
- **Dynamic blocks go by their own name.** Their inserts are stored under anonymous names such as
  `*U12`. Block filters, insert counts and attribute results use the name you know.
- **`bricscad_run_lisp` is powerful.** LISP can change or delete files and start programs, so every
  call goes through your client's tool approval.
- **Timeouts.** If a dialog blocks BricsCAD, the call fails after its timeout (30 seconds by default)
  and says to check the window.

## Safety

- Drawings open read-only by default.
- Closing or stopping refuses if there are unsaved changes, unless you pass `discard=true`.
- `bricscad_stop` only ever closes the copy this server started.
- If the client exits, a copy with nothing unsaved closes by itself. A copy with unsaved work stays
  open so you can save it.
- The server doesn't permanently change BricsCAD settings.
- Each edit tool call is all-or-nothing and one undo step. Edits made through `bricscad_run_lisp` have
  no step of their own, so they go back with the step before them.
- Entities on locked layers are refused, and missing layers are never created by drawing on them.
- Saving over an existing file needs `overwrite=true`, and the server checks that before BricsCAD is
  involved. A read-only drawing can only be saved to a new path, a file open as another drawing or
  marked read-only is never replaced, and a replaced file leaves a `.bak` beside it.

## Environment variables

| Variable | Purpose |
|---|---|
| `BRICSCAD_VERSION` | The version to start, for example `26`. Defaults to the newest installed |
| `BRICSCAD_EXECUTABLE` | Full path to BricsCAD, if it isn't found automatically |

## Known limits

- So far it has only been tested on drawings its tests created. Real project drawings may bring up
  dialogs that haven't been seen yet, such as missing fonts or proxy objects.
- `vla-save` opens a dialog and `vla-saveas` fails on macOS, so use `_.QSAVE` and `_.SAVEAS` in LISP.
- Don't close the only open drawing with your own LISP, because the listener stops. `bricscad_close_drawing`
  handles this for you.

## Development

```bash
uv run pytest
```

These tests need no BricsCAD. To run the real tests, close that version of BricsCAD first. They open
one copy at a time and use only temporary drawings:

```bash
uv run pytest -m bricscad
```

Passing them on Windows or Linux is what moves that platform to Supported.

Design and test results are in `docs/`: start with `docs/superpowers/specs/2026-11-06-bricscad-mcp-design.md`
and `docs/phase-0-results.md`.
