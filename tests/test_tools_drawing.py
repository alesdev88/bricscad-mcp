import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture
def dwg(tmp_path):
    path = tmp_path / "x.dwg"
    path.write_bytes(b"AC1032" + b"\0" * 32)
    return path


@pytest.fixture
async def started(client, fake):
    fake.responses["mcp:open-drawing"] = {"name": "x.dwg"}
    fake.responses["mcp:close-drawing"] = "Drawing2.dwg"
    fake.responses["mcp:drawing-info"] = {"name": "x.dwg"}
    await client.call_tool("bricscad_start", {})
    fake.requests.clear()
    return client


async def test_open_missing_file_never_reaches_bricscad(started, fake):
    result = await started.call_tool("bricscad_open_drawing", {"path": "/nope/x.dwg"})
    assert result.is_error and "not found" in result.content[0].text
    assert fake.requests == []


async def test_open_folder_is_refused(started, fake, tmp_path):
    result = await started.call_tool("bricscad_open_drawing", {"path": str(tmp_path)})
    assert result.is_error and "folder" in result.content[0].text
    assert fake.requests == []


async def test_open_non_dwg_is_refused(started, fake, tmp_path):
    path = tmp_path / "x.txt"
    path.write_text("hi")
    result = await started.call_tool("bricscad_open_drawing", {"path": str(path)})
    assert result.is_error and "not a drawing" in result.content[0].text
    assert fake.requests == []


async def test_a_text_file_named_dwg_is_refused(started, fake, tmp_path):
    path = tmp_path / "fake.dwg"
    path.write_text("hello")
    result = await started.call_tool("bricscad_open_drawing", {"path": str(path)})
    assert result.is_error and "not a drawing" in result.content[0].text
    assert fake.requests == []


async def test_dxf_is_accepted(started, fake, tmp_path):
    path = tmp_path / "x.DXF"
    path.write_text("0\nSECTION\n")
    result = await started.call_tool("bricscad_open_drawing", {"path": str(path)})
    assert not result.is_error and fake.requests[-1].startswith("(mcp:open-drawing ")


async def test_open_defaults_to_read_only(started, fake, dwg):
    await started.call_tool("bricscad_open_drawing", {"path": str(dwg)})
    assert fake.requests[-1].startswith("(mcp:open-drawing ") and fake.requests[-1].endswith(" T)")


async def test_open_can_be_read_write(started, fake, dwg):
    await started.call_tool("bricscad_open_drawing", {"path": str(dwg), "read_only": False})
    assert fake.requests[-1].endswith(" nil)")


async def test_open_escapes_the_path(started, fake, tmp_path):
    path = tmp_path / 'we"ird č.dwg'
    path.write_bytes(b"AC1032")
    await started.call_tool("bricscad_open_drawing", {"path": str(path)})
    assert 'we\\"ird č.dwg' in fake.requests[-1]


async def test_open_without_a_session_gives_guidance(client, dwg):
    result = await client.call_tool("bricscad_open_drawing", {"path": str(dwg)})
    assert result.is_error and "bricscad_start" in result.content[0].text


async def test_close_with_unsaved_changes_refuses(started, fake):
    fake.responses["mcp:active-modified-p"] = True
    result = await started.call_tool("bricscad_close_drawing", {})
    assert result.is_error and "discard=true" in result.content[0].text
    assert not any(r.startswith("(mcp:close-drawing") for r in fake.requests)


async def test_close_with_discard_closes(started, fake):
    fake.responses["mcp:active-modified-p"] = True
    result = await started.call_tool("bricscad_close_drawing", {"discard": True})
    assert not result.is_error and fake.requests[-1] == "(mcp:close-drawing)"
    assert result.structured_content["current_drawing"] == "Drawing2.dwg"


async def test_close_when_saved_closes(started, fake):
    fake.responses["mcp:active-modified-p"] = None
    result = await started.call_tool("bricscad_close_drawing", {})
    assert not result.is_error and fake.requests[-1] == "(mcp:close-drawing)"


async def test_drawing_tools_are_annotated(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert tools["bricscad_drawing_info"].annotations.read_only_hint is True
    assert tools["bricscad_close_drawing"].annotations.destructive_hint is True
