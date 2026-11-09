import pytest
from ezdxf.math import Vec2
from ezdxf.render import mleader

from bricscad_mcp.lispgen import lisp_path, lisp_value
from bricscad_mcp.tools.audit import audit_report
from bricscad_mcp.tools.drawing import close_drawing, open_drawing
from bricscad_mcp.tools.read import list_layers, list_xrefs
from real.helpers import line_at, make_block_with_attributes, make_dwg

pytestmark = pytest.mark.bricscad


def make_layer(session, name):
    session.bridge.send(
        '(entmakex (list \'(0 . "LAYER") \'(100 . "AcDbSymbolTableRecord") \'(100 . "AcDbLayerTableRecord") '
        f"(cons 2 {lisp_value(name)}) '(70 . 0) '(62 . 7) '(6 . \"Continuous\")))"
    )


def line_on(session, layer, z=0.0):
    return session.bridge.send(
        f"(entmakex (list '(0 . \"LINE\") (cons 8 {lisp_value(layer)}) '(10 0.0 0.0 {float(z)}) '(11 1.0 1.0 {float(z)})))"
    )


def test_clean_drawing_reports_nothing(real_session, blank):
    report = audit_report(real_session.bridge)
    for section in ("empty_layers", "unused_blocks", "missing_xrefs", "non_zero_elevation"):
        assert report[section] == {"count": 0, "items": []}, section
    assert report["off_standard_layers"] is None


def test_finds_each_problem(real_session, blank, tmp_path):
    bridge = real_session.bridge
    make_layer(real_session, "EMPTY")
    make_layer(real_session, "BAD")
    make_layer(real_session, "A-OK")
    line_on(real_session, "BAD")
    line_on(real_session, "A-OK")
    raised = line_on(real_session, "A-OK", z=5.0)
    make_block_with_attributes(real_session, "UNUSED", {}, inserts=0)
    xref_file = tmp_path / "MISSING.dwg"
    # make_dwg saves and closes the current drawing, so build the xref in its own blank one.
    bridge.send('(progn (vla-activate (vla-add (mcp:documents))) (getvar "DWGNAME"))')
    make_dwg(real_session, xref_file)
    bridge.send(f'(command "_.-XREF" "_A" {lisp_path(xref_file)} "0,0,0" "1" "1" "0")')
    assert [item["name"] for item in list_xrefs(bridge)["items"]] == ["MISSING"]
    assert list_xrefs(bridge)["items"][0]["resolved"] is True
    report = audit_report(bridge, allowed_layers=["A-*"])
    assert "EMPTY" in report["empty_layers"]["items"]
    assert "UNUSED" in report["unused_blocks"]["items"]
    assert raised in [item["handle"] for item in report["non_zero_elevation"]["items"]]
    assert "BAD" in report["off_standard_layers"]["items"]
    assert "A-OK" not in report["off_standard_layers"]["items"]


def test_layer_zero_and_defpoints_are_not_reported(real_session, blank):
    bridge = real_session.bridge
    bridge.send('(command "_.-LAYER" "_N" "Defpoints" "")')
    report = audit_report(bridge, allowed_layers=["A-*"])
    assert report["empty_layers"]["count"] == 0
    assert report["off_standard_layers"]["count"] == 0


def test_a_layer_used_only_inside_a_block_is_not_empty(real_session, blank):
    bridge = real_session.bridge
    make_layer(real_session, "INNER")
    bridge.send("(entmake (list '(0 . \"BLOCK\") '(2 . \"HOLDER\") '(70 . 0) '(10 0.0 0.0 0.0)))")
    bridge.send("(entmake (list '(0 . \"LINE\") '(8 . \"INNER\") '(10 0.0 0.0 0.0) '(11 1.0 1.0 0.0)))")
    bridge.send("(entmake (list '(0 . \"ENDBLK\")))")
    assert "INNER" not in audit_report(bridge)["empty_layers"]["items"]


def test_a_block_used_only_inside_another_block_is_not_unused(real_session, blank):
    bridge = real_session.bridge
    make_block_with_attributes(real_session, "INNER", {}, inserts=0)
    bridge.send("(entmake (list '(0 . \"BLOCK\") '(2 . \"OUTER\") '(70 . 0) '(10 0.0 0.0 0.0)))")
    bridge.send("(entmake (list '(0 . \"INSERT\") '(2 . \"INNER\") '(10 0.0 0.0 0.0)))")
    bridge.send("(entmake (list '(0 . \"ENDBLK\")))")
    items = audit_report(bridge)["unused_blocks"]["items"]
    assert "INNER" not in items and "OUTER" in items


def test_an_elevated_polyline_is_found(real_session, blank):
    handle = real_session.bridge.send(
        "(entmakex (list '(0 . \"LWPOLYLINE\") '(100 . \"AcDbEntity\") '(100 . \"AcDbPolyline\") '(90 . 2) '(70 . 0) "
        "'(38 . 7.5) '(10 0.0 0.0) '(10 1.0 1.0)))"
    )
    item = audit_report(real_session.bridge)["non_zero_elevation"]["items"][0]
    assert item["handle"] == handle and item["elevation"] == 7.5


def test_a_line_with_one_raised_end_is_found(real_session, blank):
    handle = real_session.bridge.send(
        "(entmakex (list '(0 . \"LINE\") '(10 0.0 0.0 0.0) '(11 1.0 1.0 3.0)))"
    )
    assert handle in [i["handle"] for i in audit_report(real_session.bridge)["non_zero_elevation"]["items"]]


def test_a_direction_is_not_an_elevation(real_session, blank):
    real_session.bridge.send(
        "(entmakex (list '(0 . \"XLINE\") '(100 . \"AcDbEntity\") '(100 . \"AcDbXline\") '(10 0.0 0.0 0.0) '(11 0.0 0.6 0.8)))"
    )
    assert audit_report(real_session.bridge)["non_zero_elevation"]["count"] == 0


def test_a_raised_xline_is_found(real_session, blank):
    handle = real_session.bridge.send(
        "(entmakex (list '(0 . \"XLINE\") '(100 . \"AcDbEntity\") '(100 . \"AcDbXline\") '(10 0.0 0.0 2.0) '(11 1.0 0.0 0.0)))"
    )
    assert handle in [i["handle"] for i in audit_report(real_session.bridge)["non_zero_elevation"]["items"]]


def test_raised_text_is_found(real_session, blank):
    handle = real_session.bridge.send(
        "(entmakex (list '(0 . \"TEXT\") '(10 0.0 0.0 -648.75) '(40 . 1.0) '(1 . \"x\")))"
    )
    item = audit_report(real_session.bridge)["non_zero_elevation"]["items"][0]
    assert item["handle"] == handle and item["elevation"] == -648.75


def test_a_flat_multileader_is_not_reported(real_session, dxf_drawing):
    builder = dxf_drawing.modelspace().add_multileader_mtext("Standard")
    builder.set_content("Label")
    builder.add_leader_line(mleader.ConnectionSide.left, [Vec2(-5, 5)])
    builder.build(insert=Vec2(5, 5))
    dxf_drawing.open_in_bricscad()
    bridge = real_session.bridge
    assert bridge.send("(cdr (assoc 0 (entget (ssname (ssget \"_X\") 0))))") == "MULTILEADER"
    assert audit_report(bridge)["non_zero_elevation"]["count"] == 0


# Shortened from a real MULTILEADER: group 11 is a normal, the last group 10 a scale, group 110 its location.
def test_a_raised_multileader_has_its_elevation(real_session, blank):
    assert real_session.bridge.send(
        "(mcp:elevation-of '((0 . \"MULTILEADER\") (10 5.0 5.0 4.0) (11 0.0 0.0 1.0) (110 5.0 5.0 4.0) (10 1.0 1.0 1.0)))"
    ) == 4.0


def test_flat_geometry_is_not_reported(real_session, blank):
    line_at(real_session, 3, 3)
    assert audit_report(real_session.bridge)["non_zero_elevation"]["count"] == 0


def test_sample_limit_caps_items_but_not_count(real_session, blank):
    for index in range(100):
        make_layer(real_session, f"E{index}")
    section = audit_report(real_session.bridge, sample_limit=5)["empty_layers"]
    assert section["count"] == 100 and len(section["items"]) == 5


def test_slovene_layer_names_are_matched(real_session, blank):
    make_layer(real_session, "Načrt")
    line_on(real_session, "Načrt")
    assert audit_report(real_session.bridge, allowed_layers=["NAČRT"])["off_standard_layers"]["count"] == 0


def test_many_layers_are_counted_correctly(real_session, blank):
    bridge = real_session.bridge
    for index in range(300):
        make_layer(real_session, f"L{index}")
    bridge.send(
        "(setq i 0) (repeat 300 (entmakex (list '(0 . \"LINE\") (cons 8 (strcat \"L\" (itoa i))) "
        "'(10 0.0 0.0 0.0) '(11 1.0 1.0 0.0))) (setq i (1+ i)))"
    )
    assert audit_report(bridge)["empty_layers"]["count"] == 0
    layers = list_layers(bridge, limit=2000)["items"]
    assert sum(item["entity_count"] for item in layers) == 300


def test_an_xref_is_judged_by_what_bricscad_resolved(real_session, blank, tmp_path):
    bridge = real_session.bridge
    host, other = tmp_path / "host.dwg", tmp_path / "MISSING.dwg"
    bridge.send('(progn (vla-activate (vla-add (mcp:documents))) (getvar "DWGNAME"))')
    make_dwg(real_session, other)
    bridge.send(f'(command "_.-XREF" "_A" {lisp_path(other)} "0,0,0" "1" "1" "0")')
    # A relative path, as real projects store them. It only makes sense beside the host drawing.
    bridge.send('(vla-put-path (vla-item (vla-get-blocks (mcp:active-document)) "MISSING") "./MISSING.dwg")')
    bridge.send(f'(command "_.SAVEAS" "" {lisp_path(host)})')
    close_drawing(bridge, discard=True)

    # Found where BricsCAD looks, whichever way the path is stored.
    open_drawing(bridge, str(host))
    assert list_xrefs(bridge)["items"][0]["path"] == "./MISSING.dwg"
    assert audit_report(bridge)["missing_xrefs"]["count"] == 0
    close_drawing(bridge, discard=True)

    # Missing when the drawing opens: BricsCAD reports it, and no dialog stops the listener.
    other.unlink()
    open_drawing(bridge, str(host))
    assert [item["name"] for item in audit_report(bridge)["missing_xrefs"]["items"]] == ["MISSING"]
    close_drawing(bridge, discard=True)
