"""Export and plot against a real BricsCAD, on temporary drawings only."""

import ezdxf
import pytest

from bricscad_mcp.tools import edit, export
from bricscad_mcp.tools.drawing import drawing_info
from real.helpers import line_at

pytestmark = pytest.mark.bricscad

TEXT = "Načrt čšž"


@pytest.fixture
def drawing(real_session, blank, tmp_path):
    """A saved drawing with a line, a circle and a text, as the current drawing."""
    bridge = real_session.bridge
    edit.create_entities(
        bridge,
        [
            {"type": "line", "start": [0, 0], "end": [100, 50]},
            {"type": "circle", "center": [50, 25], "radius": 20},
            {"type": "text", "position": [10, 60], "text": TEXT, "height": 5},
        ],
    )
    edit.save_drawing(bridge, str(tmp_path / "src.dwg"))
    return bridge


def state(bridge):
    info = drawing_info(bridge)
    return {key: info[key] for key in ("name", "path", "read_only", "modified")}


def test_export_dxf_matches_the_drawing(drawing, tmp_path):
    target = tmp_path / "out" / "Načrt 1.dxf"
    target.parent.mkdir()
    result = export.export_dxf(drawing, str(target))
    doc = ezdxf.readfile(target)
    assert result["bytes"] == target.stat().st_size > 0
    assert doc.dxfversion == "AC1032"
    assert {e.dxftype() for e in doc.modelspace()} >= {"LINE", "CIRCLE", "TEXT"}
    assert [e.dxf.text for e in doc.modelspace().query("TEXT")] == [TEXT]


def test_export_dxf_r12(drawing, tmp_path):
    target = tmp_path / "r12.dxf"
    export.export_dxf(drawing, str(target), version="R12")
    assert ezdxf.readfile(target).dxfversion == "AC1009"


def test_export_dxf_leaves_the_drawing_as_it_was(real_session, drawing, tmp_path):
    before = state(drawing)
    export.export_dxf(drawing, str(tmp_path / "a.dxf"))
    assert state(drawing) == before
    line_at(real_session, 5, 5)
    edited = state(drawing)
    export.export_dxf(drawing, str(tmp_path / "b.dxf"))
    assert edited["modified"] is True and state(drawing) == edited


def test_export_dxf_over_an_existing_file_leaves_only_that_file(drawing, tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    (folder / "out.dxf").write_bytes(b"old")
    (folder / "out.bak").write_bytes(b"another file's backup")
    export.export_dxf(drawing, str(folder / "out.dxf"), overwrite=True)
    assert {p.name for p in folder.iterdir()} == {"out.dxf", "out.bak"}
    assert (folder / "out.bak").read_bytes() == b"another file's backup"
    assert ezdxf.readfile(folder / "out.dxf").dxfversion == "AC1032"
