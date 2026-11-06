"""Helpers for tests against a real BricsCAD."""

import time

from bricscad_mcp.lispgen import call, lisp_path, lisp_value


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


def line_at(session, x, y):
    """Draw a one-unit diagonal line and return its handle."""
    return session.bridge.send(
        f"(entmakex (list '(0 . \"LINE\") '(10 {float(x)} {float(y)} 0.0) '(11 {float(x + 1)} {float(y + 1)} 0.0)))"
    )


def make_block_with_attributes(session, name, attributes, inserts=1):
    """Define a block with attribute definitions and insert it with values."""
    send = session.bridge.send
    send(f"(entmake (list '(0 . \"BLOCK\") (cons 2 {lisp_value(name)}) '(70 . 2) '(10 0.0 0.0 0.0)))")
    for tag in attributes:
        send(
            "(entmake (list '(0 . \"ATTDEF\") '(10 0.0 0.0 0.0) '(40 . 1.0) '(1 . \"\") '(3 . \"?\") "
            f"(cons 2 {lisp_value(tag)}) '(70 . 0)))"
        )
    send("(entmake (list '(0 . \"ENDBLK\")))")
    for _ in range(inserts):
        send(f"(entmake (list '(0 . \"INSERT\") '(66 . 1) (cons 2 {lisp_value(name)}) '(10 0.0 0.0 0.0)))")
        for tag, value in attributes.items():
            send(
                "(entmake (list '(0 . \"ATTRIB\") '(10 0.0 0.0 0.0) '(40 . 1.0) "
                f"(cons 1 {lisp_value(value)}) (cons 2 {lisp_value(tag)}) '(70 . 0)))"
            )
        send("(entmake (list '(0 . \"SEQEND\")))")


def make_dwg(session, path, lines=1):
    """Create a temporary drawing, save it, and leave it closed."""
    for _ in range(lines):
        add_line(session)
    save_as(session, path)
    session.bridge.send(call("mcp:close-drawing"))
    return path


def add_line(session):
    return session.bridge.send("(entmakex (list '(0 . \"LINE\") '(10 0.0 0.0 0.0) '(11 100.0 100.0 0.0)))")
