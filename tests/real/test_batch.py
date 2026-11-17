"""Batch jobs against a real BricsCAD, on temporary drawings only."""

import hashlib

import ezdxf
import pytest

from bricscad_mcp.lispgen import call
from bricscad_mcp.tools import batch
from bricscad_mcp.tools.drawing import open_drawing
from real.helpers import add_line, save_as, text_at

pytestmark = pytest.mark.bricscad


def digests(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir())}


def document_count(session):
    return session.bridge.send("(vla-get-count (mcp:documents))")


@pytest.fixture
def sources(real_session, tmp_path):
    """Three saved, closed drawings in tmp_path/src. b.dwg holds the text Soba."""
    folder = tmp_path / "src"
    folder.mkdir()
    bridge = real_session.bridge
    for name in ("a.dwg", "b.dwg", "c.dwg"):
        bridge.send('(progn (vla-activate (vla-add (mcp:documents))) (getvar "DWGNAME"))')
        add_line(real_session)
        if name == "b.dwg":
            text_at(real_session, 0, 0, "Soba")
        save_as(real_session, folder / name)
        bridge.send(call("mcp:close-drawing"))
    return folder


def job(kind, **options):
    return {"type": kind, **options}


def run(session, kind, **arguments):
    options = arguments.pop("options", {})
    return batch.batch_run(session.bridge, batch.parse_job(job(kind, **options)), **arguments)


def test_find_text_across_files(real_session, sources):
    before = digests(sources)
    out = run(real_session, "find_text", folder=str(sources), options={"query": "Soba"})
    assert [f["status"] for f in out["files"]] == ["ok"] * 3
    assert [f["result"]["total"] for f in out["files"]] == [0, 1, 0]
    assert digests(sources) == before


def test_audit_across_files_leaves_the_current_drawing_open(real_session, blank, sources):
    count = document_count(real_session)
    out = run(real_session, "audit", folder=str(sources))
    assert out["succeeded"] == 3 and "empty_layers" in out["files"][0]["result"]
    assert document_count(real_session) == count and out["current_drawing"]


def test_a_damaged_file_fails_and_the_rest_run(real_session, sources):
    damaged = sources / "d.dwg"
    damaged.write_bytes((sources / "a.dwg").read_bytes()[:6000])
    out = run(real_session, "audit", folder=str(sources))
    assert [f["status"] for f in out["files"]] == ["ok", "ok", "ok", "failed"]
    assert "could not open" in out["files"][3]["error"]
    assert real_session.bridge.send('(getvar "CMDACTIVE")') == 0


def open_paths(session):
    state = session.bridge.send("(mcp:save-state)")
    return [state["path"], *state["other_open"]]


def test_an_open_source_is_refused(real_session, sources):
    open_drawing(real_session.bridge, str(sources / "b.dwg"))
    try:
        out = run(real_session, "audit", folder=str(sources))
        assert [f["status"] for f in out["files"]] == ["ok", "refused", "ok"]
        assert (sources / "b.dwg").as_posix() in open_paths(real_session)
    finally:
        real_session.bridge.send(
            "(vlax-for d (mcp:documents) (if (wcmatch (strcase (vla-get-fullname d)) \"*/B.DWG\") (vla-close d :vlax-false)))"
        )


def test_export_dxf_job(real_session, sources, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    before = digests(sources)
    result = run(real_session, "export_dxf", folder=str(sources), output_folder=str(out))
    assert result["succeeded"] == 3
    assert [ezdxf.readfile(out / f"{n}.dxf").dxfversion for n in "abc"] == ["AC1032"] * 3
    assert digests(sources) == before


def test_plot_pdf_job_every_sheet(real_session, sources, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    result = run(real_session, "plot_pdf", folder=str(sources), output_folder=str(out), options={"layout": "*"})
    assert result["succeeded"] == 3 and result["files"][0]["result"] == ["Layout1", "Layout2"]
    names = sorted(p.name for p in out.iterdir())
    assert names == sorted(f"{n}-{sheet}.pdf" for n in "abc" for sheet in ("Layout1", "Layout2"))
    assert all((out / name).read_bytes().startswith(b"%PDF") for name in names)


def test_save_as_job_replaces_sources_only_with_overwrite(real_session, sources):
    before = digests(sources)
    refused = run(real_session, "save_as", folder=str(sources), output_folder=str(sources))
    assert refused["refused"] == 3 and digests(sources) == before
    count = document_count(real_session)
    done = run(real_session, "save_as", folder=str(sources), output_folder=str(sources), overwrite=True)
    assert done["succeeded"] == 3
    assert sorted(p.name for p in sources.iterdir()) == ["a.dwg", "b.dwg", "c.dwg"]
    assert document_count(real_session) == count
    out = run(real_session, "find_text", folder=str(sources), options={"query": "Soba"})
    assert [f["result"]["total"] for f in out["files"]] == [0, 1, 0]
