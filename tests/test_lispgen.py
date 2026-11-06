from pathlib import Path, PureWindowsPath

import pytest

from bricscad_mcp.lispgen import call, lisp_path, lisp_str, lisp_value


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("plain", '"plain"'),
        ('a"b', '"a\\"b"'),
        ("a\\b", '"a\\\\b"'),
        ("line1\nline2", '"line1\\nline2"'),
        ("tab\there", '"tab\\there"'),
        ("čšž", '"čšž"'),
    ],
)
def test_lisp_str_escapes(raw, expected):
    assert lisp_str(raw) == expected


def test_lisp_str_cannot_break_out_of_the_string():
    assert lisp_str('") (startapp "x') == '"\\") (startapp \\"x"'


def test_lisp_path_uses_forward_slashes():
    assert lisp_path(PureWindowsPath(r"C:\Temp\Načrt 1.dwg")) == '"C:/Temp/Načrt 1.dwg"'


def test_lisp_path_makes_relative_paths_absolute():
    assert lisp_path("x.dwg") == lisp_str((Path.cwd() / "x.dwg").as_posix())


def test_lisp_path_escapes_quotes():
    assert lisp_path(PureWindowsPath(r'C:\a"b.dwg')) == '"C:/a\\"b.dwg"'


def test_lisp_value_maps_python_types():
    assert lisp_value(True) == "T"
    assert lisp_value(False) == "nil"
    assert lisp_value(None) == "nil"
    assert lisp_value(3) == "3"
    assert lisp_value(1.5) == "1.5"
    assert lisp_value("a") == '"a"'
    assert lisp_value([1, "a"]) == '(list 1 "a")'
    assert lisp_value([[1], []]) == "(list (list 1) nil)"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), {"a": 1}, object()])
def test_lisp_value_rejects_what_lisp_cannot_read(bad):
    with pytest.raises(ValueError):
        lisp_value(bad)


def test_call_builds_an_expression():
    assert call("mcp:list-layers", 0, 200) == "(mcp:list-layers 0 200)"
    assert call("mcp:ping") == "(mcp:ping)"
    assert call("mcp:find", 'a"b', None) == '(mcp:find "a\\"b" nil)'


@pytest.mark.parametrize("bad", ['(startapp "x")', "a b", "", "ok\n", "1abc", "č"])
def test_call_rejects_an_unsafe_function_name(bad):
    with pytest.raises(ValueError):
        call(bad)
