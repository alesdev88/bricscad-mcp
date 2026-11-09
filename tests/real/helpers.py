"""Helpers for tests against a real BricsCAD."""

import time

from bricscad_mcp.lispgen import call, lisp_path, lisp_value
from bricscad_mcp.tools import read


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


def add_dynamic_block(doc, source, attributes=None, inserts=1):
    """Add a dynamic block to an ezdxf document as a DWG stores it, and return its anonymous name.

    Each state of a dynamic block is an anonymous block whose BLOCK_RECORD names the
    source block in AcDbBlockRepBTag xdata. Inserts use the anonymous name.
    LISP cannot write this xdata: entmod refuses a BLOCK_RECORD and vla-setxdata fails.
    BricsCAD renames anonymous blocks when it loads the file, so the returned name is good
    only inside this document.
    """
    attributes = attributes or {}
    definitions = [doc.blocks.new(source), doc.blocks.new_anonymous_block("U")]
    for definition in definitions:
        for tag in attributes:
            definition.add_attdef(tag, (0, 0))
    anonymous = definitions[1]
    doc.appids.add("AcDbBlockRepBTag")
    anonymous.block_record.set_xdata(
        "AcDbBlockRepBTag", [(1070, 1), (1005, definitions[0].block_record.dxf.handle)]
    )
    for _ in range(inserts):
        insert = doc.modelspace().add_blockref(anonymous.name, (0, 0))
        for tag, value in attributes.items():
            insert.add_attrib(tag, value, (0, 0))
    return anonymous.name


def add_table(session, rows, columns, cells):
    """Add a table at (10, 20) and fill the given {(row, column): text} cells."""
    send = session.bridge.send
    send(
        "(setq test:table (vla-addtable (vla-get-modelspace (mcp:active-document)) "
        f"(vlax-3d-point (list 10.0 20.0 0.0)) {rows} {columns} 5.0 30.0))"
    )
    for (row, column), text in cells.items():
        send(f"(vla-settext test:table {row} {column} {lisp_value(text)})")


def make_dwg(session, path, lines=1):
    """Create a temporary drawing, save it, and leave it closed."""
    for _ in range(lines):
        add_line(session)
    save_as(session, path)
    session.bridge.send(call("mcp:close-drawing"))
    return path


def add_line(session):
    return session.bridge.send("(entmakex (list '(0 . \"LINE\") '(10 0.0 0.0 0.0) '(11 100.0 100.0 0.0)))")


def entity_count(session):
    return session.bridge.send('(mcp:count-selection (ssget "_X"))')


def dxf_value(session, handle, code):
    """The first value of a DXF group on an entity."""
    return next(value for group, value in read.get_entity(session.bridge, handle)["dxf"] if group == code)
