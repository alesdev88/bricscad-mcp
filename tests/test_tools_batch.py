import re
import time

import pytest

pytestmark = pytest.mark.anyio


def drawing(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"AC1032" + b"\0" * 64)
    return path


@pytest.fixture
def src(tmp_path):
    folder = tmp_path / "src"
    for name in ("a.dwg", "b.dwg", "c.dwg"):
        drawing(folder / name)
    return folder


@pytest.fixture
async def started(client, fake):
    await client.call_tool("bricscad_start", {})
    fake.responses["mcp:save-state"] = {"path": "/x/Drawing1.dwg", "titled": 0, "read_only": False, "other_open": []}
    fake.requests.clear()
    return client


def batch_calls(fake):
    return [r for r in fake.requests if r.startswith("(mcp:batch-file")]


def first_string(expr):
    return re.search(r'"((?:[^"\\]|\\.)*)"', expr).group(1)


async def run(client, **arguments):
    result = await client.call_tool("bricscad_batch_run", arguments)
    return result


async def test_dry_run_plans_without_sending(client, fake, src):
    result = await run(client, job={"type": "audit"}, folder=str(src), dry_run=True)
    assert not result.is_error, result.content
    out = result.structured_content
    assert out["dry_run"] is True and out["total"] == 3 and out["current_drawing"] is None
    assert [f["status"] for f in out["files"]] == ["planned"] * 3
    assert [f["source"] for f in out["files"]] == [(src / n).as_posix() for n in ("a.dwg", "b.dwg", "c.dwg")]
    assert fake.requests == []


async def test_folder_pattern_and_recursive(client, src):
    drawing(src / "sub" / "d.dwg")
    flat = await run(client, job={"type": "audit"}, folder=str(src), dry_run=True)
    deep = await run(client, job={"type": "audit"}, folder=str(src), recursive=True, dry_run=True)
    assert flat.structured_content["total"] == 3
    assert [f["source"] for f in deep.structured_content["files"]][-1] == (src / "sub" / "d.dwg").as_posix()


async def test_files_list_without_duplicates(client, src):
    files = [str(src / "a.dwg"), str(src / "a.dwg"), str(src / "b.dwg")]
    result = await run(client, job={"type": "audit"}, files=files, dry_run=True)
    assert result.structured_content["total"] == 2


@pytest.mark.parametrize("args", [{}, {"files": ["x.dwg"], "folder": "y"}, {"folder": "EMPTY"}])
async def test_bad_source_choices_refuse_the_batch(client, tmp_path, args):
    if args.get("folder") == "EMPTY":
        (tmp_path / "empty").mkdir()
        args = {"folder": str(tmp_path / "empty")}
    result = await run(client, job={"type": "audit"}, dry_run=True, **args)
    assert result.is_error


async def test_a_file_that_is_not_a_drawing_refuses_the_batch(client, src):
    (src / "z.dwg").write_bytes(b"not a drawing")
    result = await run(client, job={"type": "audit"}, folder=str(src), dry_run=True)
    assert result.is_error and "z.dwg" in result.content[0].text


async def test_more_than_500_files_refuses_the_batch(client, tmp_path):
    for n in range(501):
        drawing(tmp_path / "many" / f"{n}.dwg")
    result = await run(client, job={"type": "audit"}, folder=str(tmp_path / "many"), dry_run=True)
    assert result.is_error and "500" in result.content[0].text


async def test_same_output_name_from_two_folders_refuses_the_batch(client, tmp_path):
    files = [str(drawing(tmp_path / "a" / "x.dwg")), str(drawing(tmp_path / "b" / "x.dwg"))]
    (tmp_path / "out").mkdir()
    result = await run(client, job={"type": "export_dxf"}, files=files, output_folder=str(tmp_path / "out"), dry_run=True)
    assert result.is_error and "x.dxf" in result.content[0].text


async def test_writing_jobs_need_an_output_folder_and_read_jobs_refuse_one(client, src, tmp_path):
    (tmp_path / "out").mkdir()
    writing = await run(client, job={"type": "export_dxf"}, folder=str(src), dry_run=True)
    reading = await run(client, job={"type": "audit"}, folder=str(src), output_folder=str(tmp_path / "out"), dry_run=True)
    assert writing.is_error and "output_folder" in writing.content[0].text
    assert reading.is_error and "output_folder" in reading.content[0].text


async def test_an_existing_output_is_refused_in_the_plan(client, src, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "b.dxf").write_bytes(b"old")
    result = await run(client, job={"type": "export_dxf"}, folder=str(src), output_folder=str(out), dry_run=True)
    files = result.structured_content["files"]
    assert [f["status"] for f in files] == ["planned", "refused", "planned"]
    assert "overwrite=true" in files[1]["error"] and files[0]["outputs"] == [(out / "a.dxf").as_posix()]


async def test_an_open_source_is_refused_and_not_sent(started, fake, src):
    fake.responses["mcp:save-state"] = {
        "path": "/x/Drawing1.dwg", "titled": 0, "read_only": False, "other_open": [(src / "b.dwg").as_posix()],
    }
    fake.responses["mcp:batch-file"] = {"total": 0}
    result = await run(started, job={"type": "audit"}, folder=str(src))
    files = result.structured_content["files"]
    assert [f["status"] for f in files] == ["ok", "refused", "ok"]
    assert "open" in files[1]["error"]
    assert all("b.dwg" not in call for call in batch_calls(fake))


async def test_a_failed_file_does_not_stop_the_batch(started, fake, src):
    def answer(expr):
        return RuntimeError("could not open") if "b.dwg" in expr else {"total": 0}

    fake.responses["mcp:batch-file"] = answer
    fake.responses["getvar"] = "Drawing1.dwg"
    out = (await run(started, job={"type": "audit"}, folder=str(src))).structured_content
    assert [f["status"] for f in out["files"]] == ["ok", "failed", "ok"]
    assert "could not open" in out["files"][1]["error"]
    assert (out["succeeded"], out["failed"], out["stopped"]) == (2, 1, None)


async def test_a_timeout_stops_the_batch(started, fake, src):
    def answer(expr):
        if "b.dwg" in expr:
            time.sleep(1.5)
        return {"total": 0}

    fake.responses["mcp:batch-file"] = answer
    out = (await run(started, job={"type": "audit"}, folder=str(src), timeout=0.5)).structured_content
    assert [f["status"] for f in out["files"]] == ["ok", "failed", "not_run"]
    assert out["stopped"] and out["not_run"] == 1 and out["current_drawing"] is None


async def test_audit_and_find_text_send_their_workers(started, fake, src):
    fake.responses["mcp:batch-file"] = {"total": 0}
    await run(started, job={"type": "audit"}, files=[str(src / "a.dwg")])
    await run(started, job={"type": "find_text", "query": "Soba"}, files=[str(src / "a.dwg")])
    calls = batch_calls(fake)
    path = (src / "a.dwg").as_posix()
    assert calls == [
        f'(mcp:batch-file "{path}" "mcp:audit-report" (list nil 10))',
        f'(mcp:batch-file "{path}" "mcp:find-text" (list "Soba" nil 50 0))',
    ]


def strings(expr):
    return re.findall(r'"((?:[^"\\]|\\.)*)"', expr)


def writes_third_string(content):
    """A fake mcp:batch-file whose worker writes `content` to the temporary path it was given."""

    def answer(expr):
        with open(strings(expr)[2], "wb") as file:
            file.write(content)
        return True

    return answer


async def test_export_dxf_job_writes_each_output_through_a_temporary(started, fake, src, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    fake.responses["mcp:batch-file"] = writes_third_string(b"0\nSECTION\n")
    result = (await run(started, job={"type": "export_dxf"}, folder=str(src), output_folder=str(out))).structured_content
    assert [f["status"] for f in result["files"]] == ["ok"] * 3
    assert sorted(p.name for p in out.iterdir()) == ["a.dxf", "b.dxf", "c.dxf"]
    first = batch_calls(fake)[0]
    assert re.fullmatch(
        r'\(mcp:batch-file "[^"]+/src/a\.dwg" "mcp:export-dxf-now" \(list "[^"]+/out/\.a\.mcp-[0-9a-f]{8}\.dxf" "2018"\)\)',
        first,
    )
    assert result["files"][0]["outputs"] == [(out / "a.dxf").as_posix()]


async def test_an_existing_output_is_refused_without_overwrite(started, fake, src, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "b.dxf").write_bytes(b"old")
    fake.responses["mcp:batch-file"] = writes_third_string(b"new")
    result = (await run(started, job={"type": "export_dxf"}, folder=str(src), output_folder=str(out))).structured_content
    assert [f["status"] for f in result["files"]] == ["ok", "refused", "ok"]
    assert (out / "b.dxf").read_bytes() == b"old"


async def test_save_as_into_the_source_folder_needs_overwrite(started, fake, src):
    fake.responses["mcp:batch-file"] = writes_third_string(b"AC1032 new")
    refused = (await run(started, job={"type": "save_as"}, folder=str(src), output_folder=str(src))).structured_content
    assert [f["status"] for f in refused["files"]] == ["refused"] * 3
    assert batch_calls(fake) == []
    done = (await run(started, job={"type": "save_as"}, folder=str(src), output_folder=str(src), overwrite=True)).structured_content
    assert [f["status"] for f in done["files"]] == ["ok"] * 3
    assert (src / "a.dwg").read_bytes() == b"AC1032 new"
    assert sorted(p.name for p in src.iterdir()) == ["a.dwg", "b.dwg", "c.dwg"]


async def test_plot_pdf_job_checks_its_options_before_running(started, fake, src, tmp_path):
    (tmp_path / "out").mkdir()
    result = await run(started, job={"type": "plot_pdf", "scale": "1/100"}, folder=str(src), output_folder=str(tmp_path / "out"))
    assert result.is_error and batch_calls(fake) == []


async def test_plot_every_sheet_moves_each_pdf_to_its_name(started, fake, src, tmp_path):
    out = tmp_path / "out"
    out.mkdir()

    def answer(expr):
        folder = strings(expr)[2]
        for n in (1, 2):
            with open(f"{folder}/{n}.pdf", "wb") as file:
                file.write(b"%PDF")
        return ["Layout1", "A/B"]

    fake.responses["mcp:batch-file"] = answer
    result = (await run(started, job={"type": "plot_pdf", "layout": "*"}, files=[str(src / "a.dwg")], output_folder=str(out))).structured_content
    assert result["files"][0]["status"] == "ok"
    assert sorted(p.name for p in out.iterdir()) == ["a-A_B.pdf", "a-Layout1.pdf"]
    assert result["files"][0]["result"] == ["Layout1", "A/B"]
