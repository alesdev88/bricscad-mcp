import math

import pytest

from bricscad_mcp.errors import LispError
from bricscad_mcp.tools import edit, read
from real.helpers import define_block_with_attribute_definitions, dxf_value, entity_count

pytestmark = pytest.mark.bricscad

LINE = {"type": "line", "start": [0, 0], "end": [1, 1]}


def make(session, *items, **kwargs):
    return edit.create_entities(session.bridge, list(items), **kwargs)


def test_creates_a_line_and_reports_it(real_session, blank):
    result = make(real_session, {"type": "line", "start": [0, 0], "end": [5, 5]})
    assert result["count"] == 1 and result["created"][0]["type"] == "LINE" and result["created"][0]["layout"] == "Model"


def test_creates_a_polyline_with_bulges(real_session, blank):
    item = {"type": "polyline", "vertices": [[0, 0], [5, 0], [5, 5]], "bulges": [1, 0, 0], "closed": True, "elevation": 2.5}
    handle = make(real_session, item)["created"][0]["handle"]
    assert dxf_value(real_session, handle, 70) == 1 and dxf_value(real_session, handle, 38) == 2.5
    assert dxf_value(real_session, handle, 42) == 1.0


def test_creates_a_circle(real_session, blank):
    handle = make(real_session, {"type": "circle", "center": [3, 4], "radius": 2})["created"][0]["handle"]
    assert dxf_value(real_session, handle, 10) == [3.0, 4.0, 0.0] and dxf_value(real_session, handle, 40) == 2.0


def test_arc_angles_are_degrees(real_session, blank):
    item = {"type": "arc", "center": [0, 0], "radius": 2, "start_angle": 0, "end_angle": 90}
    handle = make(real_session, item)["created"][0]["handle"]
    assert dxf_value(real_session, handle, 51) == pytest.approx(math.pi / 2)


@pytest.mark.parametrize("stored", ['a"b', "a\\b", "Načrt št. 1"])
def test_text_round_trips(real_session, blank, stored):
    make(real_session, {"type": "text", "position": [1, 2], "text": stored, "height": 2.5})
    item = read.find_text(real_session.bridge, stored)["items"][0]
    assert item["text"] == stored and item["position"] == [1.0, 2.0, 0.0]


def test_long_mtext_round_trips(real_session, blank):
    text = "a" * 400 + " č " + "b" * 400
    make(real_session, {"type": "mtext", "position": [0, 0], "text": text, "height": 1, "width": 20})
    assert read.find_text(real_session.bridge, "č")["items"][0]["text"] == text


def test_mtext_newlines_become_line_breaks(real_session, blank):
    make(real_session, {"type": "mtext", "position": [0, 0], "text": "a\nb", "height": 1})
    assert read.find_text(real_session.bridge, "a")["items"][0]["text"] == "a\\Pb"


def test_a_missing_layer_is_refused_and_not_created(real_session, blank):
    with pytest.raises(LispError, match="Nope.*does not exist"):
        make(real_session, {**LINE, "layer": "Nope"})
    assert real_session.bridge.send('(if (tblsearch "LAYER" "Nope") 1 0)') == 0


def test_a_missing_text_style_is_refused(real_session, blank):
    with pytest.raises(LispError, match="NoStyle"):
        make(real_session, {"type": "text", "position": [0, 0], "text": "x", "height": 1, "style": "NoStyle"})
    assert entity_count(real_session) == 0


def test_a_missing_layout_is_refused(real_session, blank):
    with pytest.raises(LispError, match="NoLayout"):
        make(real_session, LINE, layout="NoLayout")
    assert entity_count(real_session) == 0


def test_draws_on_a_named_layout(real_session, blank):
    assert make(real_session, LINE, layout="layout1")["created"][0]["layout"] == "Layout1"


def test_the_default_is_the_model_even_on_a_sheet(real_session, blank):
    real_session.bridge.send('(setvar "CTAB" "Layout1")')
    assert make(real_session, LINE)["created"][0]["layout"] == "Model"


def test_a_bad_item_leaves_nothing_behind(real_session, blank):
    with pytest.raises(LispError, match="Nope"):
        make(real_session, LINE, LINE, {**LINE, "layer": "Nope"})
    assert entity_count(real_session) == 0


def test_a_batch_is_one_undo_step(real_session, blank):
    make(real_session, LINE, LINE, LINE)
    assert edit.undo(real_session.bridge)["undone"] == 1
    assert entity_count(real_session) == 0


def test_linear_dimension_measures_its_points(real_session, blank):
    item = make(real_session, {"type": "dimension", "start": [0, 0], "end": [10, 0], "line_point": [5, 4]})["created"][0]
    assert item["type"] == "DIMENSION"
    assert dxf_value(real_session, item["handle"], 13) == [0.0, 0.0, 0.0]
    assert dxf_value(real_session, item["handle"], 14) == [10.0, 0.0, 0.0]


def test_aligned_dimension_is_aligned(real_session, blank):
    item = {"type": "dimension", "kind": "aligned", "start": [0, 0], "end": [10, 5], "line_point": [5, 8]}
    handle = make(real_session, item)["created"][0]["handle"]
    subclasses = [value for code, value in read.get_entity(real_session.bridge, handle)["dxf"] if code == 100]
    assert "AcDbAlignedDimension" in subclasses and "AcDbRotatedDimension" not in subclasses


def test_hatch_leaves_only_the_hatch(real_session, blank):
    item = make(
        real_session,
        {"type": "hatch", "points": [[0, 0], [10, 0], [10, 10], [0, 10]], "pattern": "ANSI31", "scale": 2, "angle": 45},
    )["created"][0]
    assert entity_count(real_session) == 1 and item["type"] == "HATCH"
    assert dxf_value(real_session, item["handle"], 2) == "ANSI31" and dxf_value(real_session, item["handle"], 41) == 2.0
    assert dxf_value(real_session, item["handle"], 52) == pytest.approx(math.pi / 4)


def test_a_solid_hatch_is_the_default(real_session, blank):
    handle = make(real_session, {"type": "hatch", "points": [[0, 0], [1, 0], [1, 1]]})["created"][0]["handle"]
    assert dxf_value(real_session, handle, 2) == "SOLID"


def test_an_unknown_hatch_pattern_leaves_nothing(real_session, blank):
    with pytest.raises(LispError, match="NOPE99"):
        make(real_session, {"type": "hatch", "points": [[0, 0], [1, 0], [1, 1]], "pattern": "NOPE99"})
    assert entity_count(real_session) == 0 and real_session.bridge.send('(getvar "CMDACTIVE")') == 0


def test_inserts_a_block_with_attributes(real_session, blank):
    define_block_with_attribute_definitions(real_session, "TB", ["NASLOV", "ST"])
    handle = make(
        real_session,
        {"type": "insert", "block": "TB", "position": [3, 4], "scale": 2, "attributes": {"naslov": "Načrt"}},
    )["created"][0]["handle"]
    item = read.read_attributes(real_session.bridge)["items"][0]
    assert item["block"] == "TB" and item["attributes"]["NASLOV"] == "Načrt"
    assert dxf_value(real_session, handle, 10) == [3.0, 4.0, 0.0] and dxf_value(real_session, handle, 41) == 2.0


def test_an_unknown_block_leaves_nothing(real_session, blank):
    with pytest.raises(LispError, match="Nope"):
        make(real_session, LINE, {"type": "insert", "block": "Nope", "position": [0, 0]})
    assert entity_count(real_session) == 0


def test_an_unknown_attribute_tag_leaves_nothing(real_session, blank):
    define_block_with_attribute_definitions(real_session, "TB", ["NASLOV"])
    with pytest.raises(LispError, match="NOPE"):
        make(real_session, {"type": "insert", "block": "TB", "position": [0, 0], "attributes": {"NOPE": "x"}})
    assert entity_count(real_session) == 0


@pytest.mark.parametrize(
    "item",
    [
        {"type": "dimension", "start": [0, 0], "end": [10, 0], "line_point": [5, 4]},
        {"type": "hatch", "points": [[0, 0], [1, 0], [1, 1]]},
    ],
)
def test_dimensions_and_hatches_land_on_the_layout(real_session, blank, item):
    edit.set_layer(real_session.bridge, "A")
    created = make(real_session, {**item, "layer": "A"}, layout="Layout1")["created"][0]
    assert created["layout"] == "Layout1" and created["layer"] == "A"
