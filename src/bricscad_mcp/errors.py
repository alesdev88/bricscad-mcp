"""Errors the server reports to MCP clients. Messages say what to do next."""


class BricsCADError(Exception):
    """Base class for every error this server reports."""


class BridgeTimeout(BricsCADError):
    """BricsCAD did not answer a request in time."""


class LispError(BricsCADError):
    """A request ran and raised a LISP error."""


class ProcessDied(BricsCADError):
    """The BricsCAD process this server started is no longer running."""


class NotRunning(BricsCADError):
    """No BricsCAD session has been started."""


class SafetyRefused(BricsCADError):
    """A safety rule refused the call."""
