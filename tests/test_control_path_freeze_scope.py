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

SELECTOR (iter-132): guards are found by BEHAVIOR, not by name. Until iter-132
this module matched the single literal name ``GUARD_NAME``, so it saw 12 of the
26 every-suite freeze guards actually on disk; the other 14 live under 9 further
names (``test_b8_*`` through ``test_b12_*`` and
``test_ac_guard_and_control_path_byte_unchanged``) in test_iter50 through
test_iter72 and were INVISIBLE -- a planted known-bad guard under any other name
passed this test, which is fail-open against the very regression above. A guard
is now anything that INVOKES ``git diff --quiet HEAD -- <pathspec>``: every
token of ``GIT_DIFF_TOKENS`` must appear as a STANDALONE string constant inside
the function, which is the shape a real argv list has.

WHY element form rather than a substring or contiguous-phrase match: all three
select the same 26 guards today, so recall cannot choose between them and
precision must. A test whose only string constant is a docstring saying it
deliberately does NOT run that command is selected by the looser rules, and
``test_control_path_guards_still_cover_the_real_control_path`` would then force
that innocent test to freeze dispatcher.py -- a red suite manufactured out of a
healthy test. Element form rejects prose, because prose is one long constant.

Residual holes, recorded rather than chased (iter-132):
  * FORBIDDEN is checked by element membership, so a pathspec written as a
    single joined string would slip through. All 26 live guards use list-element
    literals, and widening to whitespace-tokenised matching risks flagging a
    guard whose ASSERT MESSAGE names a forbidden path in prose -- a real but
    unfired residual.
  * A guard that builds its pathspec from a module-level constant or a shared
    helper is still invisible: only string constants inside the function body
    are read. This narrows the hole; it does not close it.

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
# The one file a control-path guard must still cover, or it is hollow.
CONTROL_PATH_FILE = "dispatcher.py"
# What a freeze guard DOES: shells out to `git diff --quiet HEAD -- <pathspec>`.
# Each token is matched as its own string constant (argv element form); see the
# module docstring for why substring and phrase matching were rejected.
GIT_DIFF_TOKENS = ("git", "diff", "--quiet", "HEAD", "--")
# Measured over 4,383 test functions in this directory: 26 guards under 10
# distinct names. A FLOOR, not an equality -- nothing repo-wide forbids a future
# iteration from adding one more legitimate narrow guard, and pinning the count
# would redden that iteration's suite for a bookkeeping reason. Module-level and
# read inside the assertion, so a test can shrink it to prove the floor fires.
# Re-derive it from the repo root with the one-liner in the floor assertion's
# own failure message below, so the number can never be checked from memory.
EXPECTED_MIN_GUARD_COUNT = 26

# A guard may legitimately be either flavour of function definition.
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _string_constants(fn: ast.AST) -> list[str]:
    """Every string constant anywhere inside `fn`, docstrings included.

    Semantics deliberately unchanged from the pre-132 helper: a guard's frozen
    pathspec is a list of plain literals, so reading them all is what lets
    FORBIDDEN and CONTROL_PATH_FILE be checked by element membership.
    """
    return [n.value for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def is_freeze_guard(fn: ast.AST) -> bool:
    """True when `fn` INVOKES ``git diff --quiet HEAD -- <pathspec>``.

    Mention is not invocation: every GIT_DIFF_TOKENS entry must be a standalone
    constant, so a docstring that merely names the command (one constant that
    happens to contain all the tokens as substrings) is not selected.
    """
    constants = set(_string_constants(fn))
    return all(token in constants for token in GIT_DIFF_TOKENS)


def guard_names_in_source(source: str) -> list[str]:
    """Names of the freeze guards defined in `source`, in source-text order.

    Pure over a string so the selector can be exercised against synthesized
    modules under tmp_path; planting a sample guard in tests/ would leave a
    landmine for any later broader pytest invocation. Total by design: bad input
    yields [] instead of raising, because one unparsable module must never mask
    the scan of every other.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    guards = [node for node in ast.walk(tree)
              if isinstance(node, _FUNCTION_NODES) and is_freeze_guard(node)]
    # ast.walk is breadth-first, so sort back into text order: callers read the
    # result as "the guards in this file", and a stable order keeps failure
    # messages diffable across runs.
    return [node.name
            for node in sorted(guards, key=lambda n: (n.lineno, n.col_offset))]


def _guard_nodes(
    tests_dir: pathlib.Path | None = None,
) -> list[tuple[pathlib.Path, ast.AST]]:
    """(file, node) for every freeze guard under `tests_dir`, file then text order.

    Keeps the node so the callers below can read its pathspec constants; the
    public :func:`freeze_guards` exposes only the (file, name) pairs.

    `None` means TESTS_DIR, resolved by reading the module global HERE rather
    than capturing it as a default argument value: a default is bound at def
    time, so `monkeypatch.setattr(mod, "TESTS_DIR", tmp)` would silently scan
    the real tests/ instead -- a probe that then passes for the wrong reason,
    which is the exact fail-open class this module exists to catch.
    """
    root = pathlib.Path(TESTS_DIR if tests_dir is None else tests_dir)
    found: list[tuple[pathlib.Path, ast.AST]] = []
    for path in sorted(root.glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken test file is its own failure
            continue
        guards = [node for node in ast.walk(tree)
                  if isinstance(node, _FUNCTION_NODES) and is_freeze_guard(node)]
        for node in sorted(guards, key=lambda n: (n.lineno, n.col_offset)):
            found.append((path, node))
    return found


def freeze_guards(
    tests_dir: pathlib.Path | None = None,
) -> list[tuple[pathlib.Path, str]]:
    """The policed population: (file, guard name) for every guard under `tests_dir`.

    Directory-parameterized so behaviour can be proved on a temp tree instead of
    on the live suite, which is the only way to test the known-bad case.
    """
    return [(path, node.name) for path, node in _guard_nodes(tests_dir)]


def forbidden_freezes(tests_dir: pathlib.Path | None = None) -> list[str]:
    """One entry per (guard, FORBIDDEN path) violation, naming file and path."""
    offenders: list[str] = []
    for path, node in _guard_nodes(tests_dir):
        frozen = _string_constants(node)
        for bad in FORBIDDEN:
            if bad in frozen:
                offenders.append(f"{path.name}::{node.name} freezes {bad!r}")
    return offenders


def hollow_guards(tests_dir: pathlib.Path | None = None) -> list[str]:
    """Guards that no longer freeze the real control path -- the other failure mode.

    The mirror of :func:`forbidden_freezes`: narrowing a guard must not empty it
    out, or the resume-safety invariant stops being asserted at all.
    """
    return [f"{path.name}::{node.name} no longer covers {CONTROL_PATH_FILE}"
            for path, node in _guard_nodes(tests_dir)
            if CONTROL_PATH_FILE not in _string_constants(node)]


def test_the_guard_still_exists_somewhere():
    """Guard against this meta-test silently passing because nothing matched."""
    guards = freeze_guards()
    assert len(guards) >= EXPECTED_MIN_GUARD_COUNT, (
        f"found {len(guards)} every-suite freeze guards but expected at least "
        f"{EXPECTED_MIN_GUARD_COUNT}; the selector matches too little and this "
        "meta-test is under-policing. Re-derive from the repo root with: "
        "python3 -c \"import sys; sys.path.insert(0, 'tests'); import "
        "test_control_path_freeze_scope as m; print(len(m.freeze_guards()))\"")


def test_control_path_guards_do_not_freeze_docs_or_roles():
    offenders = forbidden_freezes()
    assert not offenders, (
        "an every-suite control-path guard freezes documentation or role "
        "prompts, which permanently blocks legitimate later edits: "
        + "; ".join(offenders))


def test_control_path_guards_still_cover_the_real_control_path():
    """Narrowing must not hollow the guard out entirely."""
    hollow = hollow_guards()
    assert not hollow, (
        "an every-suite control-path guard stopped covering the real control "
        "path: " + "; ".join(hollow))
