import time

import pytest
from ezdxf.math import Vec2
from ezdxf.render import mleader

from bricscad_mcp.errors import LispError
from bricscad_mcp.lispgen import lisp_value
from bricscad_mcp.tools import read
from real.helpers import add_table, line_at, make_block_with_attributes

pytestmark = pytest.mark.bricscad


def handles(page):
    return {item["handle"] for item in page["items"]}


def test_blank_starts_empty(real_session, blank):
    assert read.query_entities(real_session.bridge)["total"] == 0


def test_empty_drawing_returns_empty_lists(real_session, blank):
    bridge = real_session.bridge
    page = read.query_entities(bridge)
    assert page["items"] == [] and page["total"] == 0
    assert read.read_attributes(bridge)["items"] == []
    assert read.find_text(bridge, "x")["items"] == []
    assert read.list_xrefs(bridge)["items"] == []
    assert read.list_blocks(bridge)["items"] == []


def test_filter_with_no_match_returns_empty(real_session, blank):
    line_at(real_session, 0, 0)
    assert read.query_entities(real_session.bridge, types=["ARC"], layer="NO_SUCH")["total"] == 0


def test_query_by_type(real_session, blank):
    line = line_at(real_session, 0, 0)
    real_session.bridge.send("(entmakex (list '(0 . \"CIRCLE\") '(10 0.0 0.0 0.0) '(40 . 1.0)))")
    page = read.query_entities(real_session.bridge, types=["LINE"])
    assert page["total"] == 1 and handles(page) == {line}
    item = page["items"][0]
    assert item["type"] == "LINE" and item["layer"] == "0" and item["layout"] == "Model"
    assert item["bbox"] == [[0.0, 0.0, 0.0], [1.0, 1.0, 0.0]]


def test_query_pages_cover_every_entity(real_session, blank):
    bridge = real_session.bridge
    bridge.send("(repeat 5000 (entmakex (list '(0 . \"LINE\") '(10 0.0 0.0 0.0) '(11 1.0 1.0 0.0))))", timeout=120)
    started = time.monotonic()
    a = read.query_entities(bridge, limit=2000, offset=0)
    elapsed = time.monotonic() - started
    b = read.query_entities(bridge, limit=2000, offset=2000)
    c = read.query_entities(bridge, limit=2000, offset=4000)
    assert a["total"] == 5000 and elapsed < 30
    assert len(handles(a) | handles(b) | handles(c)) == 5000
    assert len(c["items"]) == 1000
    assert read.query_entities(bridge, limit=10, offset=5000)["items"] == []


def test_bbox_filter(real_session, blank):
    inside = line_at(real_session, 1, 1)
    line_at(real_session, 500, 500)
    page = read.query_entities(real_session.bridge, bbox=[0, 0, 10, 10])
    assert page["total"] == 1 and handles(page) == {inside}


def test_get_entity_returns_dxf_pairs(real_session, blank):
    line = line_at(real_session, 2, 3)
    entity = read.get_entity(real_session.bridge, line)
    assert entity["type"] == "LINE" and entity["handle"] == line
    assert [10, [2.0, 3.0, 0.0]] in entity["dxf"]


def test_get_entity_with_an_unknown_handle_is_a_clear_error(real_session, blank):
    with pytest.raises(LispError, match="FFFFFF"):
        read.get_entity(real_session.bridge, "FFFFFF")


def test_list_layers_with_slovene_name_and_states(real_session, blank):
    bridge = real_session.bridge
    bridge.send('(entmakex (list \'(0 . "LAYER") \'(100 . "AcDbSymbolTableRecord") \'(100 . "AcDbLayerTableRecord") '
                '(cons 2 "Načrt-čšž") \'(70 . 4) \'(62 . -3) \'(6 . "Continuous")))')
    bridge.send("(entmakex (list '(0 . \"LINE\") (cons 8 \"Načrt-čšž\") '(10 0.0 0.0 0.0) '(11 1.0 1.0 0.0)))")
    layers = {item["name"]: item for item in read.list_layers(bridge)["items"]}
    layer = layers["Načrt-čšž"]
    assert layer["locked"] is True and layer["on"] is False and layer["frozen"] is False
    assert layer["color"] == 3 and layer["linetype"] == "Continuous" and layer["entity_count"] == 1


def test_list_blocks_counts_top_level_and_nested_inserts(real_session, blank):
    make_block_with_attributes(real_session, "TB", {"NASLOV": "x"}, inserts=2)
    bridge = real_session.bridge
    bridge.send("(entmake (list '(0 . \"BLOCK\") '(2 . \"OUTER\") '(70 . 0) '(10 0.0 0.0 0.0)))")
    bridge.send("(entmake (list '(0 . \"INSERT\") '(2 . \"TB\") '(10 0.0 0.0 0.0) '(66 . 0)))")
    bridge.send("(entmake (list '(0 . \"ENDBLK\")))")
    blocks = {item["name"]: item for item in read.list_blocks(bridge)["items"]}
    assert blocks["TB"]["insert_count"] == 3 and blocks["TB"]["is_xref"] is False
    assert blocks["OUTER"]["insert_count"] == 0 and blocks["OUTER"]["entity_count"] == 1


def test_list_layouts(real_session, blank):
    layouts = read.list_layouts(real_session.bridge)["items"]
    assert layouts[0]["name"] == "Model" and layouts[0]["is_model"] is True
    assert all(item["is_model"] is False for item in layouts[1:]) and len(layouts) >= 2


def test_reads_title_block_attributes_with_slovene_text(real_session, blank):
    make_block_with_attributes(real_session, "TB", {"NASLOV": "Načrt št. 1", "ST": "7"})
    items = read.read_attributes(real_session.bridge, block="TB")["items"]
    assert items[0]["block"] == "TB" and items[0]["layout"] == "Model"
    assert items[0]["attributes"] == {"NASLOV": "Načrt št. 1", "ST": "7"}


def test_inserts_without_attributes_are_not_listed(real_session, blank):
    make_block_with_attributes(real_session, "TB", {"A": "1"})
    real_session.bridge.send("(entmake (list '(0 . \"INSERT\") '(2 . \"TB\") '(10 5.0 5.0 0.0)))")
    assert read.read_attributes(real_session.bridge)["total"] == 1


@pytest.mark.parametrize(
    "stored,query", [('a"b c', 'a"b'), ("a\\b", "a\\b"), ("Načrt", "načrt"), ("100%", "100%"), ("x*y", "x*y")]
)
def test_find_text_is_literal_and_handles_special_characters(real_session, blank, stored, query):
    real_session.bridge.send(f"(entmakex (list '(0 . \"TEXT\") '(10 0.0 0.0 0.0) '(40 . 1.0) (cons 1 {lisp_value(stored)})))")
    real_session.bridge.send("(entmakex (list '(0 . \"TEXT\") '(10 9.0 9.0 0.0) '(40 . 1.0) '(1 . \"other\")))")
    page = read.find_text(real_session.bridge, query)
    assert page["total"] == 1 and page["items"][0]["text"] == stored
    assert page["items"][0]["type"] == "TEXT" and page["items"][0]["position"] == [0.0, 0.0, 0.0]


def test_find_text_case_sensitive(real_session, blank):
    real_session.bridge.send("(entmakex (list '(0 . \"TEXT\") '(10 0.0 0.0 0.0) '(40 . 1.0) '(1 . \"Abc\")))")
    assert read.find_text(real_session.bridge, "abc", case_sensitive=True)["total"] == 0
    assert read.find_text(real_session.bridge, "Abc", case_sensitive=True)["total"] == 1


def test_find_text_reads_long_mtext(real_session, blank):
    long_text = "a" * 400 + "needle" + "b" * 400
    chunks = f'(cons 3 {lisp_value(long_text[:250])}) (cons 3 {lisp_value(long_text[250:500])}) (cons 1 {lisp_value(long_text[500:])})'
    real_session.bridge.send(
        "(entmakex (list '(0 . \"MTEXT\") '(100 . \"AcDbEntity\") '(100 . \"AcDbMText\") "
        f"'(10 0.0 0.0 0.0) '(40 . 1.0) {chunks}))"
    )
    page = read.find_text(real_session.bridge, "needle")
    assert page["total"] == 1 and page["items"][0]["text"] == long_text


def test_find_text_finds_attribute_values(real_session, blank):
    make_block_with_attributes(real_session, "TB", {"NASLOV": "needle here"})
    page = read.find_text(real_session.bridge, "needle")
    assert page["total"] == 1 and page["items"][0]["type"] == "ATTRIB"


def add_text_multileader(doc, content):
    builder = doc.modelspace().add_multileader_mtext("Standard")
    builder.set_content(content)
    builder.add_leader_line(mleader.ConnectionSide.left, [Vec2(-5, 5)])
    builder.build(insert=Vec2(5, 5))


def test_find_text_finds_multileader_text(real_session, dxf_drawing):
    add_text_multileader(dxf_drawing, "needle Načrt")
    dxf_drawing.open_in_bricscad()
    page = read.find_text(real_session.bridge, "NAČRT")
    assert page["total"] == 1
    item = page["items"][0]
    assert item["type"] == "MULTILEADER" and item["text"] == "needle Načrt"
    assert item["layout"] == "Model" and item["position"] == [5.0, 5.0, 0.0]


def test_find_text_reads_long_multileader_text(real_session, dxf_drawing):
    long_text = "a" * 400 + "needle" + "b" * 400
    add_text_multileader(dxf_drawing, long_text)
    dxf_drawing.open_in_bricscad()
    page = read.find_text(real_session.bridge, "needle")
    assert page["total"] == 1 and page["items"][0]["text"] == long_text


# Group 304 also holds section markers such as LEADER_LINE{, which are not text.
def test_find_text_does_not_match_multileader_section_markers(real_session, dxf_drawing):
    add_text_multileader(dxf_drawing, "needle")
    block = dxf_drawing.blocks.new("MARK")
    block.add_line((0, 0), (1, 1))
    builder = dxf_drawing.modelspace().add_multileader_block("Standard")
    builder.set_content("MARK")
    builder.add_leader_line(mleader.ConnectionSide.left, [Vec2(-5, 5)])
    builder.build(insert=Vec2(5, 5))
    dxf_drawing.open_in_bricscad()
    assert read.find_text(real_session.bridge, "LEADER_LINE")["total"] == 0
    assert read.find_text(real_session.bridge, "needle")["total"] == 1


def test_find_text_finds_table_cells(real_session, blank):
    add_table(real_session, 3, 2, {(1, 0): "other", (2, 1): "needle Načrt"})
    page = read.find_text(real_session.bridge, "NAČRT")
    assert page["total"] == 1
    item = page["items"][0]
    assert item["type"] == "ACAD_TABLE" and item["text"] == "needle Načrt"
    assert (item["row"], item["column"]) == (2, 1)
    assert item["layout"] == "Model" and item["position"] == [10.0, 20.0, 0.0]


def test_find_text_returns_each_matching_table_cell(real_session, blank):
    add_table(real_session, 3, 2, {(1, 0): "needle one", (1, 1): "needle two", (2, 0): "other"})
    page = read.find_text(real_session.bridge, "needle")
    assert [(item["row"], item["column"]) for item in page["items"]] == [(1, 0), (1, 1)]


def test_find_text_reads_long_table_cells(real_session, blank):
    long_text = "a" * 400 + "needle" + "b" * 400
    add_table(real_session, 3, 2, {(1, 1): long_text})
    page = read.find_text(real_session.bridge, "needle")
    assert page["total"] == 1 and page["items"][0]["text"] == long_text


# A new table's first row is one title cell merged across all columns.
def test_find_text_reports_a_merged_table_cell_once(real_session, blank):
    add_table(real_session, 3, 2, {(0, 0): "needle title"})
    page = read.find_text(real_session.bridge, "needle")
    assert page["total"] == 1 and (page["items"][0]["row"], page["items"][0]["column"]) == (0, 0)


def test_entities_in_paper_space_report_their_layout(real_session, blank):
    real_session.bridge.send(
        "(entmakex (list '(0 . \"LINE\") '(67 . 1) '(410 . \"Layout1\") '(10 0.0 0.0 0.0) '(11 1.0 1.0 0.0)))"
    )
    page = read.query_entities(real_session.bridge, layout="Layout1")
    assert page["total"] == 1 and page["items"][0]["layout"] == "Layout1"
    assert read.query_entities(real_session.bridge, layout="Model")["total"] == 0


def test_a_layer_name_with_wildcard_characters_counts_only_itself(real_session, blank):
    bridge = real_session.bridge
    for name in ("A#1", "AB1"):
        bridge.send(f'(entmakex (list \'(0 . "LAYER") \'(100 . "AcDbSymbolTableRecord") \'(100 . "AcDbLayerTableRecord") '
                    f'(cons 2 {lisp_value(name)}) \'(70 . 0) \'(62 . 7) \'(6 . "Continuous")))')
    bridge.send("(entmakex (list '(0 . \"LINE\") '(8 . \"AB1\") '(10 0.0 0.0 0.0) '(11 1.0 1.0 0.0)))")
    layers = {item["name"]: item for item in read.list_layers(bridge)["items"]}
    assert layers["A#1"]["entity_count"] == 0 and layers["AB1"]["entity_count"] == 1
