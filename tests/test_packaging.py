"""The MCPB bundle's manifest has to stay in step with the package it ships."""

import asyncio
import json
import re
import tomllib
from pathlib import Path

from bricscad_mcp.server import mcp

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
SERVER_JSON = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))


def test_versions_and_licence_agree():
    version = PYPROJECT["project"]["version"]
    assert MANIFEST["version"] == version
    assert SERVER_JSON["version"] == version
    for package in SERVER_JSON["packages"]:
        assert package["version"] == version
        assert bundle_target(package["identifier"], version)
    assert MANIFEST["license"] == PYPROJECT["project"]["license"]


def test_manifest_lists_every_tool_the_server_registers():
    registered = {tool.name for tool in asyncio.run(mcp.list_tools())}
    listed = [tool["name"] for tool in MANIFEST["tools"]]
    assert len(listed) == len(set(listed))
    assert set(listed) == registered


def test_manifest_starts_the_bundled_interpreter_isolated():
    # Claude Desktop ships no uv or Python, so the bundle brings its own interpreter.
    server = MANIFEST["server"]
    assert server["type"] == "binary"
    assert server["mcp_config"]["command"] == "${__dirname}/" + server["entry_point"]
    assert server["mcp_config"]["args"] == ["-I", "-m", "bricscad_mcp"]


def test_every_setting_reaches_the_server_and_blank_is_the_default():
    env = MANIFEST["server"]["mcp_config"]["env"]
    used = {m for value in env.values() for m in re.findall(r"\$\{user_config\.(\w+)\}", value)}
    assert used == set(MANIFEST["user_config"])
    # Without a default, an unset field reaches the server as the literal "${user_config...}".
    for option in MANIFEST["user_config"].values():
        assert option.get("required") is not True
        assert option["default"] == ""


def test_registry_bundles_are_the_platforms_the_manifest_offers():
    version = SERVER_JSON["version"]
    targets = {bundle_target(package["identifier"], version) for package in SERVER_JSON["packages"]}
    assert targets == {"darwin-arm64", "win32"}
    assert sorted(MANIFEST["compatibility"]["platforms"]) == ["darwin", "win32"]


def bundle_target(url: str, version: str) -> str | None:
    """The platform a release download URL names, if it is one of this version's bundles."""
    escaped = re.escape(version)
    found = re.search(rf"/v{escaped}/bricscad-mcp-{escaped}-([a-z0-9-]+)\.mcpb$", url)
    return found.group(1) if found else None
