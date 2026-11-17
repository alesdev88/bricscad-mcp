# BricsCAD MCP

An MCP server that lets Claude, or any MCP client, read, audit, edit, plot and export drawings in BricsCAD,
one at a time or in batches.
It starts its own BricsCAD window and controls it through a small LISP listener, so it works
at every licence level, including Lite, and doesn't need Windows COM.

Status: all four phases are built: reading and auditing, drawing and editing, plotting and export,
and batch jobs.

## Platform support

| Platform | Server logic tests | Real BricsCAD tests | Status |
|---|---|---|---|
| macOS | CI | Passed on V26.1.6 Lite | Supported |
| Windows | CI | Passed on V25 Lite | Supported |
| Linux | CI | Not run: no test machine yet | Experimental |

A platform becomes Supported only when the real BricsCAD tests pass on it. CI has no BricsCAD.
The plot, export and batch tools (`bricscad_export_dxf`, `bricscad_plot_pdf`, `bricscad_preview_image`,
`bricscad_batch_run`) have so far passed them on macOS only; on Windows they are untested.
The Linux install location is unverified, so set `BRICSCAD_EXECUTABLE` if yours is not found.

## Install

You need BricsCAD in every case.

### Claude Desktop

Download the bundle for your computer from the
[latest release](https://github.com/alesdev88/bricscad-mcp/releases/latest) and open it:

- macOS with Apple silicon: `bricscad-mcp-<version>-darwin-arm64.mcpb`
- Windows: `bricscad-mcp-<version>-win32.mcpb`

The bundle brings its own Python, so there is nothing to install first. Its settings let you pick a
BricsCAD version, or point to the program if it isn't found. On an Intel Mac, use the `uvx` setup
below.

### Claude Code, Codex and other clients

These run the server from PyPI with [uv](https://docs.astral.sh/uv/), so install uv first.

Claude Code:

```bash
claude mcp add bricscad -- uvx bricscad-mcp
```

Codex (the CLI, the IDE extension and the ChatGPT desktop app share this setting):

```bash
codex mcp add bricscad -- uvx bricscad-mcp
```

Cursor, VS Code, Windsurf and other clients that take an `mcpServers` entry:

```json
{
  "mcpServers": {
    "bricscad": {
      "command": "uvx",
      "args": ["bricscad-mcp"],
      "env": { "BRICSCAD_VERSION": "26" }
    }
  }
}
```

`env` is optional. See [Environment variables](#environment-variables).

#### On a network that inspects HTTPS

Some office networks check HTTPS traffic with their own certificate. uv then can't download from
PyPI unless it uses the system's certificates, and the first start fails with
`invalid peer certificate: UnknownIssuer`, which a client may only report as a closed connection.
Setting `UV_SYSTEM_CERTS` in your shell isn't always enough, because some clients start servers
with only a few environment variables. Set it on the server entry instead:

```bash
claude mcp add -e UV_SYSTEM_CERTS=1 bricscad -- uvx bricscad-mcp
```

```bash
codex mcp add bricscad --env UV_SYSTEM_CERTS=1 -- uvx bricscad-mcp
```

In an `mcpServers` entry, add `"UV_SYSTEM_CERTS": "1"` to `env`. The Claude Desktop bundle downloads
nothing, so it doesn't need this.

### From source

```bash
git clone https://github.com/alesdev88/bricscad-mcp.git
```

```bash
cd bricscad-mcp && uv sync
```

Then register it, using the full path to your copy:

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
| `bricscad_export_dxf` | Writes the drawing as DXF, R12 or 2000 to 2018 |
| `bricscad_plot_pdf` | Plots the model or a sheet to PDF, with paper, orientation, area, scale and plot style |
| `bricscad_preview_image` | Returns a PNG of the model, a sheet or a window, so the client can check its work |
| `bricscad_batch_run` | Runs one job on up to 500 drawings: audit, find text, export DXF, plot PDF (one sheet or every sheet), save copies, or LISP code |
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
- **Batches.** Run `bricscad_batch_run` with `dry_run=true` first to see what it would do. A failed
  file doesn't stop the batch, but a timeout does, because a dialog may be blocking BricsCAD. Afterwards
  the current drawing may be another open drawing. A batch takes up to 500 drawings per call.

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
- Exporting, plotting and previews never change the drawing, not even its modified state. They refuse
  an existing file without `overwrite=true`, never write over an open drawing, and replace a file only
  once the new one is complete, with no `.bak`.
- Batch jobs open their drawings read-only and never write them unless the output folder is their own
  folder and `overwrite=true`. Drawings already open in BricsCAD are refused, and each output replaces
  a file only once it is complete.

## Environment variables

| Variable | Purpose |
|---|---|
| `BRICSCAD_VERSION` | The version to start, for example `26`. Defaults to the newest installed |
| `BRICSCAD_EXECUTABLE` | Full path to BricsCAD, if it isn't found automatically |

## Known limits

- So far it has only been tested on drawings its tests created. Real project drawings may bring up
  dialogs that haven't been seen yet, such as missing fonts or proxy objects.
- `vla-save` opens a dialog and `vla-saveas` fails on macOS, so use `_.QSAVE` and `_.SAVEAS` in LISP.
- On Windows, BricsCAD's LISP holds text in the Windows code page (`SYSCODEPAGE`), not Unicode.
  Slovenian and other text in that code page works. LISP would turn characters outside it, such as
  Chinese on a Central European system, into `?`, so the server refuses any call that contains them
  and names each one. It detects the code page when it starts BricsCAD.
- Don't close the only open drawing with your own LISP, because the listener stops. `bricscad_close_drawing`
  handles this for you.
- PDFs are plotted with `Print As PDF.pc3` only. Paper sizes go by BricsCAD's own name, such as
  `ISO A3 (297.00 x 420.00 MM)`; an unknown name is reported, not guessed.
- Previews are the size of the BricsCAD window, and the model shows on black, as on screen.

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

## Releasing

1. Set the new version in `pyproject.toml`, `manifest.json` and `server.json`, then run `uv lock`.
   A test checks that the three agree, and that `manifest.json` lists every tool.
2. Push a tag for it, such as `v0.1.0`. The `release` workflow tests the commit, checks a fresh
   install of the wheel, builds both bundles, creates the GitHub release, publishes to PyPI and then
   to the MCP registry.
3. Install each bundle on its platform before announcing the release. CI can't start them.

To build a bundle locally, `uv run python scripts/build_bundle.py --target darwin-arm64` (or `win32`
or `all`). It needs Node for the `mcpb` packer; `--no-pack` stops before packing and leaves the
unpacked bundle in `build/`.

PyPI publishing needs a trusted publisher on pypi.org for this repository, workflow `publish.yml`,
environment left blank.
