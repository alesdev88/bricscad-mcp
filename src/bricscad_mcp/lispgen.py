"""Turns Python values into LISP source. All text reaches LISP through here."""

import math
import re
from pathlib import Path, PurePath
from typing import Any

_ESCAPES = str.maketrans({"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"})
_FUNCTION_NAME = re.compile(r"[A-Za-z_:\-][\w:\-]*", re.ASCII)


def lisp_str(value: str) -> str:
    """Quote text as a LISP string that cannot break out of its quotes."""
    return '"' + value.translate(_ESCAPES) + '"'


def lisp_path(path: str | PurePath) -> str:
    """Quote a path as an absolute, forward-slash LISP string."""
    if isinstance(path, str):
        path = Path(path)
    if isinstance(path, Path):
        path = path.absolute()
    return lisp_str(path.as_posix())


def lisp_value(value: Any) -> str:
    """Convert a string, number, bool, None or list to LISP source."""
    if value is None or value is False:
        return "nil"
    if value is True:
        return "T"
    if isinstance(value, str):
        return lisp_str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"LISP cannot represent {value}")
        return repr(value)
    if isinstance(value, list):
        if not value:
            return "nil"
        return "(list " + " ".join(lisp_value(item) for item in value) + ")"
    raise ValueError(f"LISP cannot represent a {type(value).__name__}")


def call(fn: str, *args: Any) -> str:
    """Build a call to a named LISP function with safely converted arguments."""
    if not _FUNCTION_NAME.fullmatch(fn):
        raise ValueError(f"Not a valid LISP function name: {fn!r}")
    return "(" + " ".join([fn, *(lisp_value(arg) for arg in args)]) + ")"
