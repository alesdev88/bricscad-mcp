"""Fixtures for tests against a real BricsCAD. They use only temporary drawings.

Only one BricsCAD runs at a time: tests share it, and a test that needs its own
closes the shared one first.
"""

import ezdxf
import pytest

from bricscad_mcp.lispgen import call
from bricscad_mcp.platforms import get_platform
from bricscad_mcp.platforms.base import is_alive
from bricscad_mcp.session import Session
from bricscad_mcp.tools.drawing import open_drawing

_shared: Session | None = None


def _close(session: Session | None) -> None:
    if session is not None and session.pid is not None and is_alive(session.pid):
        session.stop(discard=True)


def _close_shared() -> None:
    global _shared
    _close(_shared)
    _shared = None


@pytest.fixture
def real_session():
    global _shared
    if _shared is None or _shared.pid is None or not is_alive(_shared.pid):
        _shared = Session(get_platform())
        _shared.start()
    return _shared


@pytest.fixture
def blank(real_session):
    """Make a new empty drawing current, and discard it afterwards."""
    bridge = real_session.bridge
    bridge.send('(progn (vla-activate (vla-add (mcp:documents))) (getvar "DWGNAME"))')
    yield
    bridge.send(call("mcp:close-drawing"))


@pytest.fixture
def dxf_drawing(real_session, tmp_path):
    """An ezdxf document, for what LISP cannot make. Call `.open_in_bricscad()` once it is filled."""
    doc = ezdxf.new("R2013", setup=True)
    opened = []

    def open_in_bricscad():
        path = tmp_path / "fixture.dxf"
        doc.saveas(path)
        open_drawing(real_session.bridge, str(path))
        opened.append(path)

    doc.open_in_bricscad = open_in_bricscad
    yield doc
    if opened:
        real_session.bridge.send(call("mcp:close-drawing"))


@pytest.fixture
def own_session():
    """A fresh BricsCAD for tests that end or damage the session."""
    _close_shared()
    session = Session(get_platform())
    session.start()
    yield session
    _close(session)


@pytest.fixture
def no_shared_session():
    """For tests that start BricsCAD another way, through the real command."""
    _close_shared()


@pytest.fixture(scope="session", autouse=True)
def close_bricscad_at_the_end():
    yield
    _close_shared()
