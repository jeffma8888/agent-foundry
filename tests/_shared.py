"""Helpers shared by this repo's own suite (not a test module: no `test_` prefix, so
pytest never collects it; sibling test modules import it by bare name the way
`tests/test_iter155_behavior.py` imports `test_iter61_behavior`).

WHY THIS FILE EXISTS: `ast.get_source_segment(source, node)` re-splits the WHOLE
source string into lines on every call. Several guard tests walk every node of
foundry.py (1.5 MB, 800+ top-level statements) and ask for each node's text, so
the split is paid once per node -- quadratic in the size of the file, and the
three slowest in-process tests of the suite (iter 417 measurement: 8.1 s + 5.4 s
+ 3.1 s serially, paid on every tester, gate and preship run). Splitting ONCE
and slicing per node makes the same walk take milliseconds.

The slicer is a byte-for-byte mirror of the stdlib's own arithmetic, so a caller
that swaps `ast.get_source_segment(src, node)` for
`source_segment(split_source_lines(src), node)` sees IDENTICAL output for every
node, including the corner cases the stdlib handles: CRLF and lone-CR line
ends, form feeds (which the parser does NOT treat as line breaks), multi-byte
characters (`col_offset` / `end_col_offset` are UTF-8 BYTE offsets, so the slice
happens on the encoded line), and nodes with no position (-> None).
"""
from __future__ import annotations

import ast
import re
from typing import Sequence

# Copied verbatim from `ast._line_pattern` rather than imported: a private stdlib
# name may move between minor versions, and the whole point of this module is to
# match the parser's line-splitting EXACTLY, so the pattern is pinned here.
_LINE_PATTERN = re.compile(r"(.*?(?:\r\n|\n|\r|$))")


def split_source_lines(source: str) -> list[str]:
    """Split `source` into lines the way the parser counts them, ends kept.

    `\\r\\n`, `\\n` and a lone `\\r` each end a line; a form feed does not. The
    result always ends with one trailing empty string (the stdlib's does too),
    which is harmless because node line numbers never point at it. Call this
    ONCE per source and hand the list to `source_segment` for every node.
    """
    return [match[0] for match in _LINE_PATTERN.finditer(source)]


def source_segment(lines: Sequence[str], node: ast.AST) -> str | None:
    """`ast.get_source_segment(source, node)` over pre-split `lines`, O(1) per node.

    Returns None exactly when the stdlib does: the node lacks `lineno` /
    `col_offset` attributes, or its `end_lineno` / `end_col_offset` is None.
    Column offsets are UTF-8 byte offsets, so the first and last lines are
    sliced in encoded form and decoded back, as the stdlib does.
    """
    try:
        if node.end_lineno is None or node.end_col_offset is None:  # type: ignore[attr-defined]
            return None
        lineno: int = node.lineno - 1  # type: ignore[attr-defined]
        end_lineno: int = node.end_lineno - 1  # type: ignore[attr-defined]
        col_offset: int = node.col_offset  # type: ignore[attr-defined]
        end_col_offset: int = node.end_col_offset  # type: ignore[attr-defined]
    except AttributeError:
        return None
    if end_lineno == lineno:
        return lines[lineno].encode()[col_offset:end_col_offset].decode()
    first = lines[lineno].encode()[col_offset:].decode()
    last = lines[end_lineno].encode()[:end_col_offset].decode()
    return "".join([first, *lines[lineno + 1:end_lineno], last])
