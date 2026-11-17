import subprocess
import sys
from pathlib import Path

import psutil
import pytest

from bricscad_mcp.errors import BricsCADError
from bricscad_mcp.platforms import get_platform, select_installation
from bricscad_mcp.platforms.base import Installation, Platform, is_alive, pids_running_from, terminate
from bricscad_mcp.platforms.linux import Linux
from bricscad_mcp.platforms.macos import MacOS
from bricscad_mcp.platforms.windows import Windows


def test_macos_finds_versions_newest_first(tmp_path):
    (tmp_path / "BricsCAD V25.app").mkdir()
    (tmp_path / "BricsCAD V26.app").mkdir()
    (tmp_path / "BricsCAD V9.app").mkdir()
    (tmp_path / "Other.app").mkdir()
    assert [i.version for i in MacOS().find_installations(tmp_path)] == ["26", "25", "9"]


def test_windows_finds_exe(tmp_path):
    d = tmp_path / "BricsCAD V26 en_US"
    d.mkdir()
    (d / "bricscad.exe").touch()
    (tmp_path / "BricsCAD V25 en_US").mkdir()  # no exe inside
    found = Windows().find_installations(tmp_path)
    assert [i.version for i in found] == ["26"]
    assert found[0].executable == d / "bricscad.exe"


def test_linux_finds_launcher(tmp_path):
    d = tmp_path / "v26"
    d.mkdir()
    (d / "bricscad.sh").touch()
    found = Linux().find_installations(tmp_path)
    assert [i.version for i in found] == ["26"]
    assert found[0].executable == d / "bricscad.sh"


def test_a_missing_install_folder_finds_nothing(tmp_path):
    for platform in (MacOS(), Windows(), Linux()):
        assert platform.find_installations(tmp_path / "nope") == []


def test_launch_commands():
    s = Path("/q/my boot.lsp")
    app = Path("/Applications/BricsCAD V26.app")
    assert MacOS().launch_command(Installation("26", app), s) == [
        "open", "-n", "-a", str(app), "--args", "-b", str(s),
    ]
    assert Windows().launch_command(Installation("26", Path("b.exe")), s) == ["b.exe", "/B", str(s)]
    assert Linux().launch_command(Installation("26", Path("b.sh")), s) == ["b.sh", "-b", str(s)]


def test_macos_launch_accepts_a_binary_inside_the_bundle_from_the_override():
    binary, script = Path("/x/custom"), Path("/q/b.lsp")
    assert MacOS().launch_command(Installation("custom", binary), script) == [
        str(binary), "-b", str(script),
    ]


class Only25(Platform):
    def find_installations(self, root=None):
        return [Installation("25", Path("/a/25"))]

    def launch_command(self, inst, script):
        return []

    def start(self, inst, script):
        return 0

    def state_dir(self):
        return Path("/tmp")


def test_select_defaults_to_the_newest(monkeypatch):
    monkeypatch.delenv("BRICSCAD_EXECUTABLE", raising=False)
    monkeypatch.delenv("BRICSCAD_VERSION", raising=False)
    assert select_installation(Only25()).version == "25"


def test_env_executable_overrides(monkeypatch, tmp_path):
    exe = tmp_path / "custom"
    exe.touch()
    monkeypatch.setenv("BRICSCAD_EXECUTABLE", str(exe))
    assert select_installation(MacOS()).executable == exe


def test_env_executable_that_is_missing_is_reported(monkeypatch, tmp_path):
    monkeypatch.setenv("BRICSCAD_EXECUTABLE", str(tmp_path / "nope"))
    with pytest.raises(BricsCADError, match="BRICSCAD_EXECUTABLE"):
        select_installation(MacOS())


def test_env_version_selects(monkeypatch):
    monkeypatch.delenv("BRICSCAD_EXECUTABLE", raising=False)
    monkeypatch.setenv("BRICSCAD_VERSION", "99")
    with pytest.raises(BricsCADError, match="25"):
        select_installation(Only25())


def test_blank_env_settings_count_as_unset(monkeypatch):
    # An install dialog, such as Claude Desktop's for the MCPB bundle, passes blank fields as "".
    monkeypatch.setenv("BRICSCAD_EXECUTABLE", "")
    monkeypatch.setenv("BRICSCAD_VERSION", " ")
    assert select_installation(Only25()).version == "25"


def test_explicit_version_beats_env(monkeypatch):
    monkeypatch.delenv("BRICSCAD_EXECUTABLE", raising=False)
    monkeypatch.setenv("BRICSCAD_VERSION", "99")
    assert select_installation(Only25(), version="25").version == "25"


def test_select_missing_version_lists_found(monkeypatch):
    monkeypatch.delenv("BRICSCAD_EXECUTABLE", raising=False)
    monkeypatch.delenv("BRICSCAD_VERSION", raising=False)
    with pytest.raises(BricsCADError, match="25"):
        select_installation(Only25(), version="99")


def test_select_with_nothing_installed_mentions_the_override(monkeypatch, tmp_path):
    monkeypatch.delenv("BRICSCAD_EXECUTABLE", raising=False)
    monkeypatch.delenv("BRICSCAD_VERSION", raising=False)

    class Nothing(Only25):
        def find_installations(self, root=None):
            return []

    with pytest.raises(BricsCADError, match="BRICSCAD_EXECUTABLE"):
        select_installation(Nothing())


@pytest.mark.parametrize(
    "name,cls",
    [("darwin", MacOS), ("win32", Windows), ("linux", Linux)],
)
def test_get_platform_by_name(name, cls):
    assert isinstance(get_platform(name), cls)


def test_get_platform_rejects_unknown():
    with pytest.raises(BricsCADError, match="sunos"):
        get_platform("sunos")


def test_is_alive_for_this_process_and_a_dead_pid():
    import os

    assert is_alive(os.getpid()) is True
    assert is_alive(99999999) is False


def test_terminate_a_dead_pid_is_not_an_error():
    terminate(99999999)


@pytest.mark.skipif(sys.platform == "win32", reason="needs POSIX signals")
def test_terminate_forces_a_process_that_ignores_the_request():
    code = (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print('ready', flush=True)\n"
        "time.sleep(60)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    child.stdout.readline()
    terminate(child.pid, grace_seconds=0.2)
    assert is_alive(child.pid) is False


def test_pids_running_from_matches_a_file_or_a_folder_above_it():
    import os

    exe = Path(psutil.Process().exe())
    assert os.getpid() in pids_running_from(exe)
    assert os.getpid() in pids_running_from(exe.parent)
    assert pids_running_from(exe.parent / "no-such-program") == set()


def test_linux_looks_for_running_copies_in_the_install_folder(monkeypatch):
    seen = []
    monkeypatch.setattr("bricscad_mcp.platforms.base.pids_running_from", lambda p: seen.append(p) or set())
    Linux().running_pids(Installation("26", Path("/opt/bricsys/bricscad/v26/bricscad.sh")))
    assert seen == [Path("/opt/bricsys/bricscad/v26")]


def test_macos_identifies_the_new_process_only(monkeypatch):
    # Another copy already running must never be taken for the one just started.
    groups = [{111}, {111, 222}]
    monkeypatch.setattr("bricscad_mcp.platforms.macos.bundle_pids", lambda app: groups.pop(0))
    monkeypatch.setattr("bricscad_mcp.platforms.macos.subprocess.run", lambda *a, **k: None)
    assert MacOS().start(Installation("26", Path("/A/B.app")), Path("/q/b.lsp")) == 222


def test_macos_start_reports_failure_when_no_process_appears(monkeypatch):
    monkeypatch.setattr("bricscad_mcp.platforms.macos.bundle_pids", lambda app: {111})
    monkeypatch.setattr("bricscad_mcp.platforms.macos.subprocess.run", lambda *a, **k: None)
    monkeypatch.setattr("bricscad_mcp.platforms.macos.START_WAIT_SECONDS", 0.05)
    with pytest.raises(BricsCADError, match="did not start"):
        MacOS().start(Installation("26", Path("/A/B.app")), Path("/q/b.lsp"))
