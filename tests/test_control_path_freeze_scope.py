"""Permanent control-path byte-unchanged guards must stay NARROW.

Regression origin: iter-83 and iter-84 each shipped a
``test_ac_control_path_byte_unchanged`` whose pathspec froze README.md and
roles/ in addition to the real control path. Because such a guard re-runs on
EVERY later suite, it is not a one-iteration assertion but a permanent freeze:
iter-85 legitimately added a README entry (the ship gate MANDATES one per new
CLI), the full suite went red, and the iteration was reverted. The loop could
no longer ship any docs-touching or role-touching work at all.

The running-loop control path is dispatcher.py, scripts/ and .gitignore.
README.md is documentation and roles/ are operator-gated agent prompts; both are
expected to change over time, so neither may appear in a permanent freeze.

This meta-test scans EVERY test module (not just the two that regressed) so the
anti-pattern cannot be reintroduced by a future iteration.
"""
from __future__ import annotations

import ast
import pathlib

TESTS_DIR = pathlib.Path(__file__).resolve().parent
GUARD_NAME = "test_ac_control_path_byte_unchanged"
# Paths that must never be frozen by an every-suite guard.
FORBIDDEN = ("README.md", "roles/")


def _string_constants(fn: ast.FunctionDef) -> list[str]:
    return [n.value for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _guards() -> list[tuple[pathlib.Path, ast.FunctionDef]]:
    found: list[tuple[pathlib.Path, ast.FunctionDef]] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken test file is its own failure
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == GUARD_NAME:
                found.append((path, node))
    return found


def test_the_guard_still_exists_somewhere():
    """Guard against this meta-test silently passing because nothing matched."""
    assert _guards(), (
        f"no test defines {GUARD_NAME}; this meta-test would be vacuous")


def test_control_path_guards_do_not_freeze_docs_or_roles():
    offenders: list[str] = []
    for path, fn in _guards():
        frozen = _string_constants(fn)
        for bad in FORBIDDEN:
            if bad in frozen:
                offenders.append(f"{path.name} freezes {bad!r}")
    assert not offenders, (
        "an every-suite control-path guard freezes documentation or role "
        "prompts, which permanently blocks legitimate later edits: "
        + "; ".join(offenders))


def test_control_path_guards_still_cover_the_real_control_path():
    """Narrowing must not hollow the guard out entirely."""
    for path, fn in _guards():
        frozen = _string_constants(fn)
        assert "dispatcher.py" in frozen, (
            f"{path.name}: control-path guard no longer covers dispatcher.py")
