"""Iteration 210 -- ONE repo-wide public-safety brake over the ``tests/`` tree.

WHY THIS EXISTS: a banned token in a single test file has destroyed two whole
iterations of this loop. Iteration 199 was reverted for exactly that (recorded in
``tests/test_iter200_behavior.py``'s own docstring), and iteration 205 was
reverted by the final gate for an absolute home-directory literal in its behavior
module, whose work then had to be re-landed by a later iteration. Both times the
finding was ONE line and the cost was the whole iteration.

WHY A TREE BRAKE RATHER THAN THE EXISTING CONVENTION: the defence in place was a
per-module self-check that each author copy-pasted, so coverage was exactly the
set of files somebody remembered -- and it decayed to almost nothing. Every copy
scans only its OWN file. This module scans the tree instead, so a new behavior
module is covered by a check its author never has to remember to write.

WHY EARLIER MATTERS: the two remaining defences both act too late to save an
iteration -- the final gate REVERTS, and the pre-push hook is local and git does
not clone hooks. This brake turns that revert into a local red an engineer fixes
in one line, which is the highest-leverage hardening available here: move the
gate earlier.

WHY THE POPULATION IS THE FILESYSTEM AND NOT THE TRACKED SET: a tracked-only
enumeration is fail-open exactly where the cost is, because it cannot see the
behavior module the current iteration is still writing -- precisely the file that
carried the defect both times. Two properties make the filesystem walk correct
rather than merely broader. The final gate stages with ``git add -A`` before it
commits, so an untracked ``*.py`` under ``tests/`` IS part of the shipping
population: this walk scans what ships, not a superset. And in the post-release
fresh clone ``tests/`` on disk equals the tracked set, so the brake behaves
identically there. It reads no gitignored path -- ``tests/`` is tracked, and
``__pycache__`` holds only ``*.pyc``, which a ``*.py`` walk never sees -- which is
what the no-ambient-gitignored-state rule requires.

SELF-COVERING: this file sits inside the population it scans, so it must itself
be clean. Every banned needle it needs is therefore ASSEMBLED from fragments at
runtime (``_home_prefix``); writing the needle into the rule that bans it is the
self-defeating shape that reddens a correct file.

PROVENANCE: written in the ENGINEER stage, because for this iteration the shipped
FEATURE *is* a suite brake, so the brake is the deliverable rather than a test of
one. It therefore carries no tester-isolation claim; independent verification
belongs to the tester stage.

OFFLINE BY CONSTRUCTION: no subprocess, no git call, no network, no clock
dependence beyond one elapsed-time budget. Behaviors 2, 3, 5 and 7 run entirely
under ``tmp_path``; behaviors 1, 6 and 8 only READ the real tree.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import socket
import subprocess
import sys
import time
from typing import Sequence, Tuple

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import dispatcher  # noqa: E402  (import-safety probe)
import foundry  # noqa: E402  (import-safety probe)

_TESTS_DIR = pathlib.Path(__file__).resolve().parent
_SCRIPTS_DIR = _ROOT / "scripts"
_GUARD_BASENAME = "leak_guard.py"
_DENYLIST_BASENAME = "leak_denylist.txt"

# Upper bound for one whole-tree scan. Measured at 0.26s on this checkout, so
# this is a STALL detector -- it fires if the brake ever starts shelling out or
# reaching the network -- and NOT a performance pin a slower machine can trip.
_SCAN_BUDGET_S = 5.0


def _load_by_path(name: str, path: pathlib.Path):
    """Load a module from an explicit filesystem PATH.

    The module is registered in ``sys.modules`` BEFORE ``exec_module`` because
    the guard defines a frozen dataclass, and ``dataclasses`` resolves
    ``cls.__module__`` through ``sys.modules`` while processing the class: an
    unregistered module makes that lookup return ``None`` and the load dies with
    an ``AttributeError`` that says nothing about the real cause. Loading by path
    (rather than by import) keeps this file independent of any ``sys.path``
    insertion order, and the guard is a standalone script off the pipeline
    control path, so nothing imports it normally.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _home_prefix() -> str:
    """The banned absolute home-directory prefix, ASSEMBLED at runtime.

    Never a source literal: this module is inside the population it scans, so a
    contiguous copy of the needle would make the brake report itself and a
    CORRECT file would go red. Same reason the committed denylist stores its
    needles encoded.
    """
    return "/" + "Users" + "/"


def _enumerate_test_pys(root: pathlib.Path) -> Tuple[pathlib.Path, ...]:
    """Every ``*.py`` file under ROOT, taken from the FILESYSTEM, sorted.

    Deliberately consults nothing but the directory tree, so trackedness cannot
    exclude a file -- the whole point of the population choice recorded in the
    module docstring. ``__pycache__`` components are dropped: they hold only
    build artifacts, they are gitignored, and nothing there can ever ship.
    """
    return tuple(
        path
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts
    )


def _load_guard(scripts_dir: pathlib.Path):
    """Return ``(guard_module, patterns)`` for the committed leak guard under
    SCRIPTS_DIR, or SKIP when either committed file is absent.

    The foundry is repo-agnostic and points at arbitrary product repos, so a
    product that ships no leak guard must SKIP rather than go red: a red suite
    there would block every iteration of that product for a reason it cannot fix.
    """
    guard_path = scripts_dir / _GUARD_BASENAME
    denylist_path = scripts_dir / _DENYLIST_BASENAME
    if not (guard_path.is_file() and denylist_path.is_file()):
        pytest.skip("no committed leak guard in this repo (repo-agnostic)")
    guard = _load_by_path("leak_guard_iter210_probe", guard_path)
    patterns = guard.load_denylist(denylist_path.read_text(encoding="utf-8"))
    return guard, patterns


def _scan_tree(root: pathlib.Path, guard, patterns: Sequence["re.Pattern[str]"]):
    """Scan every enumerated ``*.py`` under ROOT with the committed scanner.

    Returns ``(findings, files_scanned, missing, paths)``. Absolute path strings
    are handed to the scanner so the reads are correct from ANY working
    directory (the suite runs from the repo root, the release gate from a
    throwaway clone); the reporting helper relativises them again.
    """
    paths = _enumerate_test_pys(root)
    findings, files_scanned, missing = guard.scan_paths(
        [str(path) for path in paths], patterns)
    return findings, files_scanned, missing, paths


def _render(findings, root: pathlib.Path) -> str:
    """One ``path:line: snippet`` line per finding, with paths made
    root-RELATIVE.

    The absolute paths are what the scanner was given, but printing them would
    put this machine's own home directory into a CI log -- the shape the guard
    exists to keep out of public output. The snippet is kept verbatim: it is the
    report.
    """
    lines = []
    for path, lineno, snippet in findings:
        candidate = pathlib.Path(path)
        try:
            shown = candidate.relative_to(root).as_posix()
        except ValueError:
            shown = candidate.name
        lines.append(f"{shown}:{lineno}: {snippet}")
    return "\n".join(lines)


# ==========================================================================
# Behavior 1 -- the tree-wide clean scan (the brake itself)
# ==========================================================================
def test_b1_every_python_file_under_tests_scans_clean_under_the_denylist():
    """The whole ``tests/`` tree on disk, scanned with the committed denylist."""
    guard, patterns = _load_guard(_SCRIPTS_DIR)
    assert len(patterns) >= 1, "the committed denylist decoded to no patterns"
    findings, files_scanned, missing, paths = _scan_tree(
        _TESTS_DIR, guard, patterns)
    assert missing == (), f"unreadable file(s) under tests/: {missing}"
    assert files_scanned == len(paths), (
        "the scanner silently skipped part of the enumerated population: "
        f"{files_scanned} scanned of {len(paths)} enumerated")
    assert findings == (), (
        f"public-safety: {len(findings)} banned token(s) under tests/ would "
        "BLOCK the ship (the final gate REVERTS the whole iteration for this). "
        "Fix the line(s) below:\n" + _render(findings, _ROOT))


# ==========================================================================
# Behavior 2 -- the population is filesystem-derived, so an untracked module
# is covered
# ==========================================================================
def test_b2_the_population_is_filesystem_derived_not_the_tracked_set(tmp_path):
    """Enumerating a tree that is not a git repository AT ALL still finds
    everything, so trackedness cannot exclude a file."""
    tree = tmp_path / "tests"
    (tree / "sub").mkdir(parents=True)
    (tree / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tree / "sub" / "b.py").write_text("y = 2\n", encoding="utf-8")
    (tree / "c.txt").write_text("not python\n", encoding="utf-8")
    assert not (tmp_path / ".git").exists(), "fixture must not be a git repo"

    got = [path.relative_to(tree).as_posix()
           for path in _enumerate_test_pys(tree)]
    assert got == ["a.py", "sub/b.py"], got
    assert "c.txt" not in got

    # Structural half: the enumerator names no process/VCS seam, so the result
    # above cannot have come from a tracked-set query that merely happened to
    # agree. The positive result and this check are two different measurements.
    referenced = tuple(
        name.lower() for name in _enumerate_test_pys.__code__.co_names)
    forbidden = ("subprocess", "run_git", "popen", "check_output", "system")
    assert [name for name in forbidden if name in referenced] == []


# ==========================================================================
# Behavior 3 -- build artifacts and non-Python files are excluded
# ==========================================================================
def test_b3_pycache_directories_and_non_python_files_are_excluded(tmp_path):
    """A ``*.py`` under ``__pycache__`` and a ``*.pyc`` are both outside the
    population: neither can ever ship, so neither may redden the brake."""
    tree = tmp_path / "tests"
    (tree / "sub").mkdir(parents=True)
    (tree / "__pycache__").mkdir()
    (tree / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tree / "sub" / "b.py").write_text("y = 2\n", encoding="utf-8")
    (tree / "c.txt").write_text("not python\n", encoding="utf-8")
    (tree / "__pycache__" / "d.py").write_text("z = 3\n", encoding="utf-8")
    (tree / "sub" / "e.pyc").write_bytes(b"\x00compiled")

    got = [path.relative_to(tree).as_posix()
           for path in _enumerate_test_pys(tree)]
    assert "__pycache__/d.py" not in got
    assert "sub/e.pyc" not in got
    assert got == ["a.py", "sub/b.py"], got


# ==========================================================================
# Behavior 4 -- armed matcher (anti-vacuity control)
# ==========================================================================
def test_b4_the_committed_denylist_is_armed_and_not_inert():
    """Prove the matcher is LIVE before any clean result is trusted.

    Without this, a scanner that reported clean on EVERYTHING would satisfy
    behavior 1 forever -- the fail-open shape that makes a green brake worthless.
    """
    guard, patterns = _load_guard(_SCRIPTS_DIR)
    probe = _home_prefix() + "somebody/project/file.py"
    hits = guard.scan_text(probe, patterns)
    assert len(hits) >= 1, (
        "the committed denylist is INERT against a synthesised absolute "
        "home-path prefix: behavior 1 cannot be trusted while this fails")


# ==========================================================================
# Behavior 5 -- a planted banned literal is reported, with file and line
# ==========================================================================
def test_b5_a_planted_banned_literal_is_reported_with_its_file_and_line(
        tmp_path):
    """Two-sided with behavior 4: 4 proves the matcher fires on text, 5 proves
    the tree-walking path SURFACES that hit instead of swallowing it.

    Planted under ``tmp_path`` on purpose -- never in the real tree, where it
    would be the very defect the brake exists to stop.
    """
    guard, patterns = _load_guard(_SCRIPTS_DIR)
    tree = tmp_path / "tests"
    tree.mkdir(parents=True)
    (tree / "a.py").write_text("x = 1\n", encoding="utf-8")
    planted = tree / "b.py"
    planted.write_text(
        "# first line, clean\n"
        "# second line, clean\n"
        "PROBE = " + repr(_home_prefix() + "somebody/x") + "\n",
        encoding="utf-8")

    findings, files_scanned, missing, _ = _scan_tree(tree, guard, patterns)
    assert missing == ()
    assert files_scanned == 2
    assert len(findings) >= 1, "the planted literal was not reported at all"
    assert str(planted) in {path for path, _lineno, _snip in findings}
    assert [lineno for path, lineno, _snip in findings
            if path == str(planted)] == [3]


# ==========================================================================
# Behavior 6 -- a FLOOR, never an ambient count
# ==========================================================================
def test_b6_the_brake_asserts_a_floor_and_pins_no_ambient_file_count():
    """A fresh clone with a different number of test modules must still pass.

    An ambient COUNT precondition is the trap that broke a shipped iteration
    once already: it holds in this working tree and fails in the throwaway clone
    the release gate verifies from.
    """
    guard, patterns = _load_guard(_SCRIPTS_DIR)
    _findings, files_scanned, _missing, _paths = _scan_tree(
        _TESTS_DIR, guard, patterns)
    assert files_scanned >= 1, "the brake scanned nothing at all"

    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    # The count is ASSEMBLED, for the same reason `_home_prefix` assembles its
    # needle: this module is inside the population, so spelling the number here
    # would BE the pin it forbids and a correct file would go red.
    pinned = re.search(r"\b" + str(100 + 83) + r"\b", source)
    assert pinned is None, (
        "this module pins today's test-file count; the brake must assert a "
        "floor so a clone with a different population still passes")


# ==========================================================================
# Behavior 7 -- repo-agnostic graceful skip
# ==========================================================================
def test_b7_a_repo_without_a_committed_leak_guard_skips_rather_than_failing(
        tmp_path):
    """Absence of the guard is a SKIP, and it stays a skip when only one of the
    two committed files is present -- a half-present guard cannot be loaded, so
    treating it as available would be a crash dressed up as a leak."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    with pytest.raises(pytest.skip.Exception):
        _load_guard(scripts)

    (scripts / _GUARD_BASENAME).write_text("# not the real guard\n",
                                           encoding="utf-8")
    with pytest.raises(pytest.skip.Exception):
        _load_guard(scripts)


# ==========================================================================
# Behavior 8 -- offline, and inside its time budget
# ==========================================================================
def test_b8_the_brake_is_offline_and_stays_inside_its_time_budget(monkeypatch):
    """Every process and socket seam is armed to RAISE for the duration, so
    "offline" is enforced rather than asserted in prose.

    The guard is loaded BEFORE the seams are armed: loading a module is not part
    of the scan, and importing under a poisoned ``subprocess`` would fail for a
    reason that has nothing to do with the brake.
    """
    guard, patterns = _load_guard(_SCRIPTS_DIR)

    def _forbidden(*_args, **_kwargs):
        raise AssertionError(
            "the brake must not start a process or open a socket")

    for name in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, _forbidden)
    monkeypatch.setattr(guard, "run_git", _forbidden)
    monkeypatch.setattr(socket, "socket", _forbidden)

    started = time.perf_counter()
    findings, files_scanned, missing, _paths = _scan_tree(
        _TESTS_DIR, guard, patterns)
    elapsed = time.perf_counter() - started

    assert missing == ()
    assert files_scanned >= 1
    assert findings == (), _render(findings, _ROOT)
    assert elapsed < _SCAN_BUDGET_S, (
        f"the tree scan took {elapsed:.3f}s against a {_SCAN_BUDGET_S}s "
        "budget: it is no longer a cheap always-on brake")


# ==========================================================================
# Acceptance criteria
# ==========================================================================
def test_ac_both_control_path_modules_still_import():
    """This iteration touches no control-path module; prove it, cheaply."""
    assert foundry.__file__ and dispatcher.__file__


def test_ac_this_module_is_inside_the_population_it_scans():
    """A brake outside its own population leaves one file of permanently
    unguarded surface -- and that file is the one an author edits most while
    writing the brake."""
    covered = set(_enumerate_test_pys(_TESTS_DIR))
    assert pathlib.Path(__file__).resolve() in covered
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert _home_prefix() not in source, (
        "this module contains an absolute home-directory prefix")
    assert str(pathlib.Path.home()) not in source, (
        "this module contains this machine's real home path")
