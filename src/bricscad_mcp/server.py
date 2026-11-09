"""The MCP server. Tool modules register themselves on `mcp`."""

import os
import signal

from mcp.server.mcpserver import MCPServer

from .platforms import get_platform
from .session import Session

mcp = MCPServer(
    "bricscad",
    instructions=(
        "Controls one BricsCAD process through a LISP listener. Call bricscad_start first. "
        "The BricsCAD window it opens is occupied while the listener runs."
    ),
)

_session: Session | None = None


def session() -> Session:
    global _session
    if _session is None:
        _session = Session(get_platform())
    return _session


def set_session(value: Session | None) -> None:
    global _session
    _session = value


def handle_termination(signum: int, frame: object) -> None:
    """Exit cleanly, so the listener is told to stop rather than waiting to notice."""
    if _session is not None:
        _session.close()
    _exit_now()


def _exit_now() -> None:
    # A normal exit would wait forever on the thread blocked reading stdin.
    os._exit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, handle_termination)
    mcp.run("stdio")


from .tools import audit, core, drawing, edit, read  # noqa: E402,F401  (registers the tools)
