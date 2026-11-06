"""Helpers for tests against a real BricsCAD."""

import time

from bricscad_mcp.lispgen import lisp_path


def wait_until(condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return False


def save_as(session, path):
    """Save the current drawing to a new path through the tested command."""
    return session.bridge.send(f'(progn (command "_.SAVEAS" "" {lisp_path(path)}) (getvar "DWGNAME"))')


def add_line(session):
    return session.bridge.send("(entmakex (list '(0 . \"LINE\") '(10 0.0 0.0 0.0) '(11 100.0 100.0 0.0)))")
