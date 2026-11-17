"""Export and plot against a real BricsCAD, on temporary drawings only."""

import re

import ezdxf
import pytest

from bricscad_mcp.errors import BricsCADError
from bricscad_mcp.lispgen import lisp_path
from bricscad_mcp.tools import edit, export
from bricscad_mcp.tools.drawing import drawing_info
from real.helpers import entity_count, line_at

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


def media_boxes(path):
    return re.findall(rb"/MediaBox *\[([^\]]*)\]", path.read_bytes())


def test_plot_pdf_model_defaults(drawing, tmp_path):
    target = tmp_path / "Načrt model.pdf"
    result = export.plot_pdf(drawing, str(target))
    assert target.read_bytes().startswith(b"%PDF")
    assert result["layout"] == "Model" and result["bytes"] == target.stat().st_size
    assert [box.split() for box in media_boxes(target)] == [[b"0", b"0", b"595", b"842"]]


def test_plot_pdf_a3_landscape(drawing, tmp_path):
    target = tmp_path / "a3.pdf"
    export.plot_pdf(drawing, str(target), paper="ISO A3 (297.00 x 420.00 MM)", landscape=True)
    assert [box.split() for box in media_boxes(target)] == [[b"0", b"0", b"1191", b"842"]]


def test_plot_pdf_sheet_layout(drawing, tmp_path):
    result = export.plot_pdf(drawing, str(tmp_path / "sheet.pdf"), layout="layout1")
    assert result["layout"] == "Layout1" and (tmp_path / "sheet.pdf").read_bytes().startswith(b"%PDF")


def test_plot_pdf_window_scale_and_style(drawing, tmp_path):
    target = tmp_path / "window.pdf"
    export.plot_pdf(
        drawing, str(target), layout="Model", area="window", window=[0, 0, 50, 50], scale="1:1",
        style_table="monochrome.ctb",
    )
    assert target.read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize("args, words", [
    ({"paper": "Nope"}, "not found"),
    ({"style_table": "nope.ctb"}, "not found"),
    ({"layout": "Nope"}, "No layout named Nope"),
    ({"layout": "Model", "area": "layout"}, "layout"),
])
def test_plot_pdf_rejections_cancel_cleanly(drawing, tmp_path, args, words):
    with pytest.raises(BricsCADError, match=words):
        export.plot_pdf(drawing, str(tmp_path / "out.pdf"), **args)
    assert drawing.send('(getvar "CMDACTIVE")') == 0
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".pdf"] == []
    assert drawing_info(drawing)["modified"] is False


def test_plot_pdf_keeps_the_modified_flag(real_session, drawing, tmp_path):
    export.plot_pdf(drawing, str(tmp_path / "a.pdf"), layout="Layout1")
    assert drawing_info(drawing)["modified"] is False
    line_at(real_session, 5, 5)
    export.plot_pdf(drawing, str(tmp_path / "b.pdf"))
    assert drawing_info(drawing)["modified"] is True


def test_plot_pdf_replaces_an_existing_pdf_with_overwrite(drawing, tmp_path):
    target = tmp_path / "out.pdf"
    target.write_bytes(b"old")
    export.plot_pdf(drawing, str(target), overwrite=True)
    assert target.read_bytes().startswith(b"%PDF")


def test_preview_of_the_model_is_a_png(drawing):
    png = export.preview_image(drawing, preview_dir(drawing))
    assert png.startswith(b"\x89PNG") and drawing_info(drawing)["modified"] is False


def test_preview_of_an_unused_sheet_adds_nothing(real_session, drawing):
    drawing.send('(command "_.LAYOUT" "_N" "Fresh")')
    edit.save_drawing(drawing, overwrite=True)
    assert drawing.send('(getvar "CTAB")') != "Fresh"
    assert drawing.send('(ssget "_X" (list (cons 0 "VIEWPORT") (cons 410 "Fresh")))') is None
    before = (entity_count(real_session), drawing.send('(getvar "CTAB")'))
    png = export.preview_image(drawing, preview_dir(drawing), layout="fresh")
    assert png.startswith(b"\x89PNG")
    assert (entity_count(real_session), drawing.send('(getvar "CTAB")')) == before
    assert drawing_info(drawing)["modified"] is False


def test_preview_of_a_window(drawing):
    assert export.preview_image(drawing, preview_dir(drawing), window=[0, 0, 50, 50]).startswith(b"\x89PNG")


def test_preview_of_an_unknown_layout_fails_cleanly(drawing):
    ctab = drawing.send('(getvar "CTAB")')
    with pytest.raises(BricsCADError, match="No layout named Nope"):
        export.preview_image(drawing, preview_dir(drawing), layout="Nope")
    assert drawing.send('(getvar "CMDACTIVE")') == 0 and drawing.send('(getvar "CTAB")') == ctab


def preview_dir(bridge):
    return bridge.queue_dir.parent / "previews"


MODEL_ANSWERS_WITHOUT_SHADE_PLOT = '(list "_Y" "Model" "Print As PDF.pc3" "" "_M" "" "_N" "_E" "_F" "_C" "_Y" "" "_Y")'


def test_a_plot_question_missing_from_the_answers_writes_nothing(drawing, tmp_path):
    # As if a BricsCAD version asked one question fewer: the file name must not go to the wrong question.
    target = tmp_path / "x.pdf"
    with pytest.raises(BricsCADError, match="file name"):
        drawing.send(f"(mcp:plot-run {MODEL_ANSWERS_WITHOUT_SHADE_PLOT} {lisp_path(target)})")
    assert drawing.send('(getvar "CMDACTIVE")') == 0
    assert sorted(p.name for p in tmp_path.iterdir() if p.suffix.lower() == ".pdf") == []


def test_upper_case_extensions(drawing, tmp_path):
    export.export_dxf(drawing, str(tmp_path / "OUT.DXF"))
    export.plot_pdf(drawing, str(tmp_path / "OUT.PDF"))
    assert ezdxf.readfile(tmp_path / "OUT.DXF").dxfversion == "AC1032"
    assert (tmp_path / "OUT.PDF").read_bytes().startswith(b"%PDF")
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.upper().startswith(("OUT", ".OUT"))) == ["OUT.DXF", "OUT.PDF"]
