import re

import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture
async def started(client, fake):
    await client.call_tool("bricscad_start", {})
    fake.requests.clear()
    return client


def first_string(expr: str) -> str:
    return re.search(r'"((?:[^"\\]|\\.)*)"', expr).group(1)


def state(path="/elsewhere/a.dwg", other_open=()):
    return {"path": path, "titled": 1, "read_only": False, "other_open": list(other_open)}


def writes(content: bytes):
    """A fake LISP worker that writes `content` to the path it was given."""

    def worker(expr):
        with open(first_string(expr), "wb") as file:
            file.write(content)
        return True

    return worker


@pytest.fixture
def folder(tmp_path):
    """Where files are written. tmp_path itself also holds the fake's state folder."""
    path = tmp_path / "out"
    path.mkdir()
    return path


@pytest.fixture
def exporting(fake):
    fake.responses["mcp:save-state"] = state()
    fake.responses["mcp:export-dxf"] = writes(b"0\nSECTION\n")
    return fake


async def test_export_dxf_writes_through_a_temporary_name(started, exporting, folder):
    target = folder / "out.dxf"
    result = await started.call_tool("bricscad_export_dxf", {"path": str(target)})
    assert not result.is_error
    assert target.read_bytes() == b"0\nSECTION\n"
    assert re.fullmatch(
        rf'\(mcp:export-dxf "{re.escape(folder.as_posix())}/\.out\.mcp-[0-9a-f]{{8}}\.dxf" "2018"\)',
        exporting.requests[-1],
    )
    assert [p.name for p in folder.iterdir()] == ["out.dxf"]
    assert result.structured_content == {"path": target.as_posix(), "bytes": 10, "version": "2018"}


async def test_export_dxf_refuses_an_existing_file_without_overwrite(started, exporting, folder):
    target = folder / "out.dxf"
    target.write_bytes(b"old")
    result = await started.call_tool("bricscad_export_dxf", {"path": str(target)})
    assert result.is_error and "overwrite=true" in result.content[0].text
    assert [r for r in exporting.requests if "export-dxf" in r] == []
    assert target.read_bytes() == b"old"


async def test_export_dxf_replaces_with_overwrite(started, exporting, folder):
    target = folder / "out.dxf"
    target.write_bytes(b"old")
    result = await started.call_tool("bricscad_export_dxf", {"path": str(target), "overwrite": True})
    assert not result.is_error
    assert target.read_bytes() == b"0\nSECTION\n"
    assert [p.name for p in folder.iterdir()] == ["out.dxf"]


@pytest.mark.parametrize("name, ok", [("out.DXF", True), ("out.dwg", False), ("out", False), ("missing/out.dxf", False)])
async def test_export_dxf_checks_the_target_name(started, exporting, folder, name, ok):
    result = await started.call_tool("bricscad_export_dxf", {"path": str(folder / name)})
    assert result.is_error is not ok
    if not ok:
        assert [r for r in exporting.requests if "export-dxf" in r] == []


async def test_export_dxf_refuses_a_folder(started, exporting, folder):
    (folder / "x.dxf").mkdir()
    result = await started.call_tool("bricscad_export_dxf", {"path": str(folder / "x.dxf"), "overwrite": True})
    assert result.is_error


async def test_export_dxf_refuses_the_open_drawing_and_other_open_files(started, exporting, folder):
    own = folder / "own.dxf"
    other = folder / "other.dxf"
    own.write_bytes(b"own")
    other.write_bytes(b"other")
    exporting.responses["mcp:save-state"] = state(own.as_posix(), [other.as_posix()])
    for target in (own, other):
        result = await started.call_tool("bricscad_export_dxf", {"path": str(target), "overwrite": True})
        assert result.is_error and "open" in result.content[0].text
    assert own.read_bytes() == b"own" and other.read_bytes() == b"other"


async def test_a_failed_export_keeps_the_old_file_and_removes_the_temporary(started, exporting, folder):
    target = folder / "out.dxf"
    target.write_bytes(b"old")

    def half_written(expr):
        writes(b"partial")(expr)
        return RuntimeError("DXFOUT failed")

    exporting.responses["mcp:export-dxf"] = half_written
    result = await started.call_tool("bricscad_export_dxf", {"path": str(target), "overwrite": True})
    assert result.is_error
    assert target.read_bytes() == b"old"
    assert [p.name for p in folder.iterdir()] == ["out.dxf"]


async def test_an_export_that_writes_nothing_is_an_error(started, exporting, folder):
    exporting.responses["mcp:export-dxf"] = True
    result = await started.call_tool("bricscad_export_dxf", {"path": str(folder / "out.dxf")})
    assert result.is_error and "did not write" in result.content[0].text
    assert list(folder.iterdir()) == []


async def test_export_dxf_refuses_an_unknown_version(started, exporting, folder):
    result = await started.call_tool("bricscad_export_dxf", {"path": str(folder / "out.dxf"), "version": "2019"})
    assert result.is_error
    assert exporting.requests == []


@pytest.fixture
def plotting(fake):
    fake.responses["mcp:save-state"] = state()
    fake.responses["mcp:plot-pdf"] = writes(b"%PDF-1.5")
    return fake


def plot_calls(fake):
    return [r for r in fake.requests if r.startswith("(mcp:plot-pdf")]


async def test_plot_pdf_sends_defaults_as_nil(started, plotting, folder):
    result = await started.call_tool("bricscad_plot_pdf", {"path": str(folder / "out.pdf")})
    assert not result.is_error
    assert re.fullmatch(r'\(mcp:plot-pdf "[^"]+/\.out\.mcp-[0-9a-f]{8}\.pdf" nil nil nil nil nil nil nil\)', plotting.requests[-1])
    assert (folder / "out.pdf").read_bytes() == b"%PDF-1.5"


async def test_plot_pdf_sends_a_window_and_the_rest(started, plotting, folder):
    arguments = {
        "path": str(folder / "out.pdf"), "layout": "Layout1", "paper": "ISO A3 (297.00 x 420.00 MM)",
        "landscape": False, "area": "window", "window": [0, 0, 50, 50], "scale": "1:100",
        "style_table": "monochrome.ctb",
    }
    result = await started.call_tool("bricscad_plot_pdf", arguments)
    assert not result.is_error
    assert plotting.requests[-1].endswith(
        '"Layout1" "ISO A3 (297.00 x 420.00 MM)" 0 "window" (list 0.0 0.0 50.0 50.0) "1:100" "monochrome.ctb")'
    )


@pytest.mark.parametrize("args", [
    {"area": "window"}, {"window": [0, 0, 1, 1]}, {"area": "window", "window": [0, 0, 0, 5]},
    {"area": "window", "window": [0, 0, 1]}, {"scale": "1:0"}, {"scale": "100"}, {"scale": "1/100"},
    {"paper": "A3\n_Y"}, {"style_table": "a\nb"}, {"layout": "x\ny"},
])
async def test_plot_pdf_refuses_bad_arguments(started, plotting, folder, args):
    result = await started.call_tool("bricscad_plot_pdf", {"path": str(folder / "out.pdf"), **args})
    assert result.is_error and plot_calls(plotting) == []


@pytest.mark.parametrize("scale", ["fit", "1:1", "1:100", "2.5:1"])
async def test_plot_pdf_accepts_scales(started, plotting, folder, scale):
    result = await started.call_tool("bricscad_plot_pdf", {"path": str(folder / "out.pdf"), "scale": scale})
    assert not result.is_error


async def test_plot_pdf_refuses_an_existing_file_without_overwrite(started, plotting, folder):
    (folder / "out.pdf").write_bytes(b"old")
    result = await started.call_tool("bricscad_plot_pdf", {"path": str(folder / "out.pdf")})
    assert result.is_error and "overwrite=true" in result.content[0].text and plot_calls(plotting) == []
