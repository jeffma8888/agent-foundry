#!/usr/bin/env python3
"""Portable, committed leak-guard CORE (roadmap item 16, bite 1 of 3).

WHY this lives in tracked source rather than a git hook: this repository is
public and the autonomous dispatcher auto-pushes on every successful ship with no
human in the review loop. A drifted iteration could reintroduce internal or
personal tokens -- an internal agent-CLI name (and its .app / _BIN variants), a
model-provider service name, two internal skill names, an internal auth command,
a personal home-path prefix, a personal username -- into a public commit. The
only guard today is a LOCAL pre-push hook, and git does NOT clone hooks, so a
fresh checkout, a new operator, CI, and the post-release fresh-clone verify all
run with ZERO leak protection. A committed scanner is portable and therefore
always armed.

WHY the denylist is base64-encoded: a committed scanner that embedded its needles
as raw literals would ITSELF leak them -- the exact thing it guards against -- to
GitHub code search, automated secret scanners, and casual browsing. So the
committed denylist stores every needle URL-safe-base64-encoded; the plaintext
file reveals no secret, and a self-scan meta-test proves both committed files are
clean.

This bite ships ONLY the pure, offline, stdlib-only core -- encode_pattern /
load_denylist / scan_text -- DORMANT, with zero call site anywhere in the running
pipeline. A later bite wires a runnable CLI + a git-tree scan seam + an install
hook; a final bite integrates it into the ship gate.
"""
from __future__ import annotations

import base64
import binascii
import pathlib
import re
from typing import List, Sequence, Tuple

# Path to the committed denylist, resolved at runtime from this module's own
# location so NO literal home path ever appears in this (public) source file.
DENYLIST_PATH = pathlib.Path(__file__).resolve().parent / "leak_denylist.txt"

# Longest snippet kept in a finding record, so report lines stay bounded.
_SNIPPET_MAX = 90

# A denylist line must be pure URL-safe base64 (A-Z a-z 0-9 - _) with optional
# trailing '=' padding -- no '+' or '/'. Anchored so a stray disallowed char (a
# common non-base64 line) is rejected loudly rather than silently stripped.
_URLSAFE_B64_RE = re.compile(r"\A[A-Za-z0-9_-]*={0,2}\Z")


def encode_pattern(pattern: str) -> str:
    """URL-safe-base64-encode a regex PATTERN so the raw token never appears in
    committed plaintext.

    Round-trips exactly: ``urlsafe_b64decode(encode_pattern(p)).decode() == p``.
    The URL-safe alphabet (A-Z a-z 0-9 - _ =) contains no '/' or '+', so an
    encoded blob can never accidentally contain a home-path prefix, and the
    transform hides the literal token from casual reading / code search.
    """
    return base64.urlsafe_b64encode(pattern.encode("utf-8")).decode("ascii")


def _decode_pattern(encoded: str, lineno: int) -> str:
    """Reverse :func:`encode_pattern`, raising ``ValueError`` (naming the 1-based
    LINE NUMBER) on anything that is not valid URL-safe base64 or not UTF-8 --
    the guard fails loud and never silently drops a needle."""
    if not _URLSAFE_B64_RE.match(encoded):
        raise ValueError(
            f"leak_denylist line {lineno}: not valid URL-safe base64"
        )
    try:
        raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            f"leak_denylist line {lineno}: not valid URL-safe base64: {exc}"
        ) from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"leak_denylist line {lineno}: decoded bytes are not UTF-8: {exc}"
        ) from exc


def load_denylist(text: str) -> Tuple["re.Pattern[str]", ...]:
    """Parse denylist TEXT into an ordered tuple of compiled, case-insensitive
    regex patterns.

    Blank lines and lines whose first non-blank char is ``#`` are ignored; every
    other line must be a base64-encoded regex (see :func:`encode_pattern`). A
    line that is not valid URL-safe base64, or whose decoded text is not a valid
    regex, raises ``ValueError`` naming the offending 1-based line number -- a
    broken denylist is a hard error, never a quietly weakened guard.

    Patterns are compiled case-insensitively (a leaked token is a leak in any
    casing), preserving file order in the returned tuple.
    """
    patterns: List["re.Pattern[str]"] = []
    for lineno, raw_line in enumerate(text.splitlines(), 1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        decoded = _decode_pattern(stripped, lineno)
        try:
            patterns.append(re.compile(decoded, re.IGNORECASE))
        except re.error as exc:
            raise ValueError(
                f"leak_denylist line {lineno}: decoded text is not a valid "
                f"regex: {exc}"
            ) from exc
    return tuple(patterns)


def scan_text(
    text: str, patterns: Sequence["re.Pattern[str]"]
) -> Tuple[Tuple[int, str], ...]:
    """Scan TEXT line by line, returning ``((lineno, snippet), ...)`` for every
    line that matches at least one pattern.

    Line numbers are 1-based and ascending; AT MOST ONE record per matching line
    (the first match short-circuits -- we report the offending line, not each
    individual hit); each snippet is the line stripped of surrounding whitespace
    and truncated to 90 characters. Clean text yields the empty tuple.
    """
    findings: List[Tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for rx in patterns:
            if rx.search(line):
                findings.append((lineno, line.strip()[:_SNIPPET_MAX]))
                break
    return tuple(findings)
