"""Inserts of a dynamic block use an anonymous name, such as *U12, not the block's own name."""

import pytest

from bricscad_mcp.tools import read
from bricscad_mcp.tools.audit import audit_report
from real.helpers import add_dynamic_block

pytestmark = pytest.mark.bricscad


def test_the_fixture_names_its_source_as_a_real_dwg_does(real_session, dxf_drawing):
    add_dynamic_block(dxf_drawing, "FRAME")
    dxf_drawing.open_in_bricscad()
    send = real_session.bridge.send
    anonymous = send("(cdr (assoc 2 (entget (ssname (ssget \"_X\" '((0 . \"INSERT\"))) 0))))")
    assert anonymous.startswith("*U")
    record = f'(entget (cdr (assoc 330 (entget (tblobjname "BLOCK" "{anonymous}")))) (list "*"))'
    xdata = send(f"(vl-princ-to-string (assoc -3 {record}))")
    source = send('(cdr (assoc 5 (entget (cdr (assoc 330 (entget (tblobjname "BLOCK" "FRAME")))))))')
    assert "AcDbBlockRepBTag" in xdata and f"(1005 . {source})" in xdata


def test_inserts_count_towards_the_source_block(real_session, dxf_drawing):
    add_dynamic_block(dxf_drawing, "FRAME", inserts=2)
    dxf_drawing.open_in_bricscad()
    blocks = {b["name"]: b for b in read.list_blocks(real_session.bridge)["items"]}
    assert blocks["FRAME"]["insert_count"] == 2


def test_an_anonymous_block_still_counts_its_own_inserts(real_session, dxf_drawing):
    add_dynamic_block(dxf_drawing, "FRAME", inserts=2)
    dxf_drawing.open_in_bricscad()
    items = read.list_blocks(real_session.bridge, include_anonymous=True)["items"]
    assert [b["insert_count"] for b in items if b["name"].startswith("*U")] == [2]


def test_nested_inserts_count_towards_the_source_block(real_session, dxf_drawing):
    anonymous = add_dynamic_block(dxf_drawing, "FRAME", inserts=0)
    dxf_drawing.blocks.new("OUTER").add_blockref(anonymous, (0, 0))
    dxf_drawing.open_in_bricscad()
    blocks = {b["name"]: b for b in read.list_blocks(real_session.bridge)["items"]}
    assert blocks["FRAME"]["insert_count"] == 1


def test_the_audit_does_not_call_an_inserted_dynamic_block_unused(real_session, dxf_drawing):
    add_dynamic_block(dxf_drawing, "FRAME")
    dxf_drawing.open_in_bricscad()
    assert "FRAME" not in audit_report(real_session.bridge)["unused_blocks"]["items"]


def test_the_audit_calls_a_dynamic_block_without_inserts_unused(real_session, dxf_drawing):
    add_dynamic_block(dxf_drawing, "FRAME", inserts=0)
    dxf_drawing.open_in_bricscad()
    assert "FRAME" in audit_report(real_session.bridge)["unused_blocks"]["items"]


def test_attributes_can_be_read_by_the_source_name(real_session, dxf_drawing):
    add_dynamic_block(dxf_drawing, "TITLE", {"NUMBER": "12"})
    dxf_drawing.open_in_bricscad()
    items = read.read_attributes(real_session.bridge, block="TITLE")["items"]
    assert [item["attributes"] for item in items] == [{"NUMBER": "12"}]


def test_attributes_report_the_source_name(real_session, dxf_drawing):
    add_dynamic_block(dxf_drawing, "TITLE", {"NUMBER": "12"})
    dxf_drawing.open_in_bricscad()
    assert read.read_attributes(real_session.bridge)["items"][0]["block"] == "TITLE"


def test_the_attribute_filter_accepts_wildcards_and_ignores_case(real_session, dxf_drawing):
    add_dynamic_block(dxf_drawing, "TITLE", {"NUMBER": "12"})
    dxf_drawing.open_in_bricscad()
    assert read.read_attributes(real_session.bridge, block="tit*")["total"] == 1


def test_the_attribute_filter_skips_other_dynamic_blocks(real_session, dxf_drawing):
    add_dynamic_block(dxf_drawing, "TITLE", {"NUMBER": "12"})
    add_dynamic_block(dxf_drawing, "MARK", {"AX": "1"})
    dxf_drawing.open_in_bricscad()
    items = read.read_attributes(real_session.bridge, block="MARK")["items"]
    assert [item["block"] for item in items] == ["MARK"]


def test_the_attribute_filter_still_finds_ordinary_blocks(real_session, dxf_drawing):
    dxf_drawing.blocks.new("PLAIN").add_attdef("NUMBER", (0, 0))
    dxf_drawing.modelspace().add_blockref("PLAIN", (0, 0)).add_attrib("NUMBER", "3", (0, 0))
    add_dynamic_block(dxf_drawing, "TITLE", {"NUMBER": "12"})
    dxf_drawing.open_in_bricscad()
    items = read.read_attributes(real_session.bridge, block="PLAIN")["items"]
    assert [item["block"] for item in items] == ["PLAIN"]


def test_the_attribute_filter_pages_after_matching(real_session, dxf_drawing):
    add_dynamic_block(dxf_drawing, "MARK", {"AX": "1"}, inserts=3)
    add_dynamic_block(dxf_drawing, "OTHER", {"AX": "2"}, inserts=2)
    dxf_drawing.open_in_bricscad()
    page = read.read_attributes(real_session.bridge, block="MARK", limit=1, offset=2)
    assert page["total"] == 3 and len(page["items"]) == 1


def test_entities_can_be_queried_by_the_source_name(real_session, dxf_drawing):
    add_dynamic_block(dxf_drawing, "FRAME")
    add_dynamic_block(dxf_drawing, "OTHER")
    dxf_drawing.modelspace().add_line((0, 0), (1, 1))
    dxf_drawing.open_in_bricscad()
    page = read.query_entities(real_session.bridge, block="FRAME")
    assert page["total"] == 1 and page["items"][0]["type"] == "INSERT"


def test_the_entity_query_pages_after_matching(real_session, dxf_drawing):
    add_dynamic_block(dxf_drawing, "FRAME", inserts=3)
    add_dynamic_block(dxf_drawing, "OTHER", inserts=2)
    dxf_drawing.open_in_bricscad()
    page = read.query_entities(real_session.bridge, block="FRAME", limit=2, offset=2)
    assert page["total"] == 3 and len(page["items"]) == 1


def test_a_block_filter_combines_with_a_layer_filter(real_session, dxf_drawing):
    add_dynamic_block(dxf_drawing, "FRAME")
    dxf_drawing.open_in_bricscad()
    assert read.query_entities(real_session.bridge, block="FRAME", layer="NO_SUCH")["total"] == 0
    assert read.query_entities(real_session.bridge, block="FRAME", layer="0")["total"] == 1
