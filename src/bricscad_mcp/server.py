"""The MCP server. Tool modules register themselves on `mcp`."""

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


def main() -> None:
    mcp.run("stdio")


from .tools import core, drawing  # noqa: E402,F401  (registers the tools)

if __name__ == "__main__":
    main()
