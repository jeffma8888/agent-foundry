"""Iteration 214 -- ONE repo-wide public-safety brake over the WHOLE shipping
population, plus a PIN on the scanner's silently-skipped set.

WHY THIS EXISTS: the committed leak guard is the only ship check that has
destroyed whole iterations TWICE -- once for two denylisted tokens in a new test
module, and once (iteration 205) for a single absolute home-path literal on one
line, whose work had to be re-landed by a later iteration. Each cost a full
iteration; ``PLATFORM_ROADMAP_ARCHIVE.md`` carries both iteration numbers.
Iteration 210 correctly moved that check earlier, but chose the population
``tests/**/*.py``. Measured against the tree this module was written on, that
leaves 61 files of the 248 that ``git add -A`` would stage entirely UNSCANNED
until the gate reverts -- and every one of the last 25 ship commits touched at
least one of them.

WHY THIS POPULATION: the shipping population is exactly what the final gate
stages, i.e. tracked files plus untracked-and-not-ignored files, which is what
``git ls-files -c -o --exclude-standard`` enumerates. That set is the honest
denominator for a pre-ship leak scan: everything in it can reach a public commit,
and nothing outside it can. It deliberately contains no gitignored path, so this
brake reads no ambient local state -- the precondition rule that broke a shipped
iteration once already.

WHY THE UNCOVERED FILES MATTER MORE THAN "BROADER IS BETTER": ``DIRECTIONS.md``
is auto-built from agent prose written inside a state directory whose every path
is absolute, and it ships on nearly every commit. Iteration 205 died for an
absolute home-path literal in a TEST file; the identical literal in
``DIRECTIONS.md`` is invisible to every earlier brake.

WHY THE SKIP SET IS PINNED: ``scan_paths`` excludes ``_should_skip`` paths
SILENTLY (its own docstring says so). Today that set is exactly the guard's own
two committed files, which is correct and necessary. But it is a suffix match
with nothing pinning it, so appending a real source path -- or a broad suffix --
would remove real files from EVERY scan while every brake stayed green. That is a
fail-open hole at exactly the place the cost is. Behavior 4 pins the set;
Behavior 5 is its two-sided half, proving the pin actually reds when the set
widens rather than passing for any list that happens to match two files.

RELATION TO ITERATION 210: neither brake subsumes the other on every edge. This
one covers the whole shipping population; iteration 210 walks the FILESYSTEM and
so also covers a gitignored ``*.py`` under ``tests/``, which
``--exclude-standard`` drops by design. Behavior 3 asserts the containment that
DOES hold -- every non-ignored ``*.py`` under ``tests/`` is in this population --
and explicitly tolerates an ignored one, because a file git ignores cannot ship
and must never redden a suite.

WHY AN UNREADABLE MEMBER IS CLASSIFIED RATHER THAN FATAL: ``scan_paths``
documents `missing` as "a SOFT skip -- the caller notes them on STDERR but they
do NOT change the exit code", yet this module hard-asserted ``missing == ()``,
i.e. it was STRICTER than the scanner it wraps. That surplus strictness turns an
INFRASTRUCTURE condition into a ship blocker: under ``-n auto`` another worker can
unlink its own temporary artifact between this brake's enumeration and its read,
the brake reds, an honest tester writes ``RESULT: FAIL`` -- an unconditional ship
blocker -- and the gate REVERTS a green iteration. So the two cases are now told
apart by TRACKED-NESS (``_classify_missing``): a tracked member that cannot be
read means the scan silently covered LESS than the shipping tree and stays fatal;
an untracked path that no longer exists can neither ship nor leak, so it is
tolerated and DISCLOSED on stderr. The population itself is NOT narrowed --
``-o --exclude-standard`` stays, because tracked + untracked-not-ignored is
exactly what the final gate stages.

SELF-COVERING: this module sits inside the population it scans, so it must
itself be clean. Every banned needle is ASSEMBLED from fragments at runtime
(``_home_prefix``); writing the needle into the rule that bans it is the
self-defeating shape that reddens a correct file.

PROVENANCE: written in the ENGINEER stage, because for this iteration the shipped
FEATURE *is* a suite brake, so the brake is the deliverable rather than a test of
one. It carries no tester-isolation claim; independent verification belongs to the
tester stage.

BOUNDED AND ALMOST OFFLINE: the ONLY external effect is read-only git plumbing,
funnelled through the single ``_run_git_ls`` seam so a test can force the
enumeration to fail. The scan itself opens no process and no socket (Behavior 8
arms those seams to raise), and Behaviors 6 and 7 run entirely under ``tmp_path``.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import socket
import subprocess
import sys
import time
from typing import List, Optional, Sequence, Tuple

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import dispatcher  # noqa: E402  (import-safety probe)
import foundry  # noqa: E402  (import-safety probe)

_THIS_MODULE = sys.modules[__name__]
_TESTS_DIR = pathlib.Path(__file__).resolve().parent
_SCRIPTS_DIR = _ROOT / "scripts"
_GUARD_BASENAME = "leak_guard.py"
_DENYLIST_BASENAME = "leak_denylist.txt"

# The guard's own two committed files: the ONLY population members the scanner
# may drop silently. Spelled here rather than read from the scanner, because
# reading it from the scanner is exactly what would make the pin vacuous --
# Behavior 5 depends on this list NOT following a widened skip list.
_EXPECTED_SKIPS: Tuple[str, ...] = (
    "scripts/" + _GUARD_BASENAME,
    "scripts/" + _DENYLIST_BASENAME,
)

# Files that ship on nearly every commit and that the iteration-210 brake could
# never see. Named individually so a regression in the ENUMERATION (not just in
# the scan) is caught by name rather than by a count.
_MUST_COVER: Tuple[str, ...] = (
    "foundry.py",
    "dispatcher.py",
    "DIRECTIONS.md",
    "PLATFORM_ROADMAP.md",
    "PLATFORM_ROADMAP_ARCHIVE.md",
    "README.md",
)

# FLOOR on population members outside ``tests/**/*.py`` -- 61 when written. A
# floor, never the measured count, so adding or removing a doc cannot red this
# (the exact-count trap that iteration 210's own B6 lesson names).
_OUTSIDE_FLOOR = 55

# Upper bound for one whole-population scan. Measured under a second on this
# checkout, so this is a STALL detector -- it fires if the brake ever starts
# shelling out per file or reaching the network -- and explicitly NOT a
# performance pin a slower machine can trip.
_SCAN_BUDGET_S = 20.0


def _load_by_path(name: str, path: pathlib.Path):
    """Load a module from an explicit filesystem PATH.

    Registered in ``sys.modules`` BEFORE ``exec_module`` because the guard
    defines a frozen dataclass and ``dataclasses`` resolves ``cls.__module__``
    through ``sys.modules`` while processing the class; an unregistered module
    makes that lookup return ``None`` and the load dies with an
    ``AttributeError`` that says nothing about the real cause. Loading by path
    keeps this file independent of ``sys.path`` order, and the guard is a
    standalone script off the pipeline control path, so nothing imports it
    normally.
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


def _load_guard(scripts_dir: pathlib.Path):
    """Return ``(guard_module, patterns)`` for the committed leak guard under
    SCRIPTS_DIR, or SKIP when either committed file is absent.

    The foundry is repo-agnostic and points at arbitrary product repos, so a
    product that ships no leak guard must SKIP rather than go red: a red suite
    there would block every iteration of that product for a reason that repo
    cannot fix.
    """
    guard_path = scripts_dir / _GUARD_BASENAME
    denylist_path = scripts_dir / _DENYLIST_BASENAME
    if not (guard_path.is_file() and denylist_path.is_file()):
        pytest.skip("no committed leak guard in this repo (repo-agnostic)")
    guard = _load_by_path("leak_guard_iter214_probe", guard_path)
    patterns = guard.load_denylist(denylist_path.read_text(encoding="utf-8"))
    return guard, patterns


def _run_git_ls(args: Sequence[str], *, root: pathlib.Path) -> str:
    """The ONE external-effect seam: run read-only ``git <args>`` inside ROOT and
    return stdout.

    Every enumeration call funnels through here and is invoked by BARE module
    name, so a test's ``monkeypatch.setattr`` bites and Behavior 7 can force the
    "no git / not a work tree" branch without touching the machine. Read-only by
    construction: the only arguments this module ever passes are ``ls-files``
    queries. ``errors="replace"`` so an exotic path encoding cannot crash the
    enumeration.
    """
    completed = subprocess.run(
        ["git", *args],
        cwd=str(root),
        check=True,
        capture_output=True,
        text=True,
        errors="replace",
    )
    return completed.stdout


def _split_nul(raw: str) -> List[str]:
    """Split NUL-separated git output, dropping the empty trailing entry."""
    return [entry for entry in raw.split("\0") if entry]


def _enumerate_split(root: pathlib.Path) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """The shipping population's two halves at ROOT: ``(tracked, untracked)``.

    Split out of ``_enumerate_population``, which already ran these two queries
    SEPARATELY and then threw the provenance away. Nothing new is gathered: the
    tracked half is what tells an infrastructure condition from a real coverage
    hole when a member cannot be read (see ``_classify_missing``), and getting it
    from the same enumeration means the two answers cannot disagree.

    Both halves are repo-relative, sorted and de-duplicated; NEITHER is filtered,
    so their union is byte-for-byte the population this module has always scanned.
    """
    tracked = _split_nul(_run_git_ls(["ls-files", "-z"], root=root))
    untracked = _split_nul(
        _run_git_ls(["ls-files", "-o", "--exclude-standard", "-z"], root=root))
    return tuple(sorted(set(tracked))), tuple(sorted(set(untracked)))


def _enumerate_population(root: pathlib.Path) -> Tuple[str, ...]:
    """Every repo-relative path ``git add -A`` would stage at ROOT, sorted.

    Tracked files UNION untracked-and-not-ignored files, which is the set the
    final gate commits. Two separate queries rather than the single combined
    ``-c -o`` form on purpose: the combined form is then available to Behavior 1
    as an INDEPENDENT cross-check of this result, instead of the test re-running
    the code it is checking. The split itself now lives in ``_enumerate_split``
    because the tracked half has a second consumer; this function's result is
    unchanged.
    """
    tracked, untracked = _enumerate_split(root)
    return tuple(sorted(set(tracked) | set(untracked)))


def _population_or_skip(root: pathlib.Path) -> Tuple[str, ...]:
    """The shipping population, or SKIP when it cannot be enumerated.

    A repo that is not a git work tree, or a machine with no ``git``, cannot
    support this check at all -- and a red suite there would block every
    iteration for a reason the repo cannot fix, exactly like a missing guard.
    So the failure mode is a skip, never a red.
    """
    try:
        population = _enumerate_population(root)
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"cannot enumerate the shipping population: {exc}")
    if not population:
        pytest.skip("the shipping population is empty (not a git work tree?)")
    return population


def _population_and_tracked_or_skip(
        root: pathlib.Path) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """``(population, tracked)`` from ONE enumeration, or SKIP.

    Same skip-not-red contract as ``_population_or_skip`` and the same cost: one
    pair of read-only git queries. Deliberately not two calls -- re-querying git
    for the tracked half would open a window in which the two answers disagree,
    which is the very race this brake now has to report accurately.
    """
    try:
        tracked, untracked = _enumerate_split(root)
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"cannot enumerate the shipping population: {exc}")
    population = tuple(sorted(set(tracked) | set(untracked)))
    if not population:
        pytest.skip("the shipping population is empty (not a git work tree?)")
    return population, tracked


def _scan_population(
    root: pathlib.Path,
    population: Sequence[str],
    guard,
    patterns: Sequence["re.Pattern[str]"],
):
    """Scan every population member with the committed scanner.

    ABSOLUTE path strings are handed to the scanner so the reads are correct from
    ANY working directory (the suite runs from the repo root, the release gate
    from a throwaway clone). ``_should_skip`` is a POSIX-suffix match, so
    absolutising changes nothing about which files it drops.
    """
    absolute = [str(root / rel) for rel in population]
    findings, files_scanned, missing = guard.scan_paths(absolute, patterns)
    return findings, files_scanned, missing


def _repo_relative(path: str, root: pathlib.Path) -> str:
    """`path` spelled the way ``git ls-files`` spells it: repo-relative POSIX.

    Pure string arithmetic, no filesystem call -- which is the point, since the
    path being classified is one that is no longer THERE. An absolute path that is
    not under `root` comes back unchanged: it can never match a repo-relative
    entry, which is the correct answer for a path this repo cannot be tracking.
    """
    candidate = pathlib.PurePath(path)
    if candidate.is_absolute():
        try:
            return candidate.relative_to(pathlib.PurePath(root)).as_posix()
        except ValueError:
            return candidate.as_posix()
    return candidate.as_posix()


def _classify_missing(
    missing: Sequence[str],
    tracked: Sequence[str],
    *,
    root: Optional[pathlib.Path] = None,
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """Split unreadable population members into ``(fatal, vanished)``.

    WHY: a tracked path is a committed, stable property of the tree, so a tracked
    member that cannot be read means the leak scan silently covered LESS than the
    shipping tree -- a real coverage hole, and precisely the fail-open shape this
    module's skip-set pin exists to prevent. Untracked EXISTENCE is not stable
    under a concurrent suite, and a file that no longer exists can neither ship
    nor leak; reddening the suite for it destroys a green iteration for a
    non-defect.

    THE FAIL-OPEN LEG: `missing` arrives as the ABSOLUTE strings
    ``_scan_population`` handed the scanner, while `tracked` is repo-relative, so
    every member is normalised through ``_repo_relative`` FIRST. Comparing the two
    spellings directly would classify EVERY missing path as vanished and fail open
    on all of them.

    PURE and total: no filesystem, subprocess, git, network or clock. Input order
    is preserved within each bucket so a report reads in scan order, and paths are
    returned AS PASSED so a message names exactly what the scanner was given.
    `root` defaults to this repo's root, read INSIDE the call so a test may pass
    its own.
    """
    base = _ROOT if root is None else root
    tracked_set = frozenset(tracked)
    fatal: List[str] = []
    vanished: List[str] = []
    for path in missing:
        bucket = fatal if _repo_relative(path, base) in tracked_set else vanished
        bucket.append(path)
    return tuple(fatal), tuple(vanished)


def _render_vanished(vanished: Sequence[str], root: pathlib.Path) -> str:
    """One STDERR line disclosing every tolerated path, root-RELATIVE.

    A tolerance nobody can see is indistinguishable from a scan that silently got
    narrower, which is the fail-open shape this module exists to close. Paths are
    relativised (basename as the fallback) for the same reason ``_render`` does it:
    printing an absolute path would put this machine's own home directory into a
    public log -- the shape the guard exists to keep out.
    """
    shown: List[str] = []
    for path in vanished:
        rel = pathlib.PurePath(_repo_relative(path, root))
        shown.append(rel.name if rel.is_absolute() else rel.as_posix())
    return ("leak brake: TOLERATED %d untracked population member(s) that could "
            "not be read (untracked and no longer on disk, so they can neither "
            "ship nor leak): %s" % (len(shown), ", ".join(shown)))


def _assert_no_fatal_missing(
    missing: Sequence[str],
    tracked: Sequence[str],
    root: pathlib.Path,
) -> Tuple[str, ...]:
    """Red on an unreadable TRACKED member; tolerate and DISCLOSE a vanished
    untracked one. Returns the tolerated paths so a caller can reconcile counts.

    One shared helper for all three whole-population brakes: the race is identical
    at each of them, so fixing one site and leaving the others would just move the
    false red to a different test name.
    """
    fatal, vanished = _classify_missing(missing, tracked, root=root)
    if vanished:
        print(_render_vanished(vanished, root), file=sys.stderr)
    assert fatal == (), (
        "unreadable TRACKED population member(s): "
        f"{[pathlib.PurePath(m).name for m in fatal]}. A tracked path is a "
        "committed, stable property of this tree, so the leak scan just covered "
        "LESS than the shipping tree: that is a real coverage hole, not a race.")
    return vanished


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


def _skipped_members(population: Sequence[str], guard) -> Tuple[str, ...]:
    """Population members the scanner would drop SILENTLY, in population order.

    Asks the scanner's own predicate rather than re-deriving the suffix rule, so
    the answer tracks whatever ``LEAK_GUARD_SKIP_PATHS`` currently holds -- which
    is what makes Behavior 5 able to red.
    """
    return tuple(rel for rel in population if guard._should_skip(rel))


def _assert_skip_set_is_pinned(
    population: Sequence[str], guard
) -> Tuple[str, ...]:
    """Assert the silently-skipped set is EXACTLY the guard's own two files.

    Returns the skipped members so a caller can price the scan against them.
    Raises ``AssertionError`` NAMING every unexpected skipped path, because the
    failure this guards against is invisible by construction: a widened skip list
    shrinks every scan while leaving every brake green.
    """
    skipped = _skipped_members(population, guard)
    unexpected = [rel for rel in skipped if rel not in _EXPECTED_SKIPS]
    assert unexpected == [], (
        "the scanner would SILENTLY skip population member(s) that must be "
        f"scanned: {unexpected}. Widening LEAK_GUARD_SKIP_PATHS removes real "
        "files from every scan while every other brake stays green.")
    expected_present = [rel for rel in _EXPECTED_SKIPS if rel in population]
    assert sorted(skipped) == sorted(expected_present), (
        f"skipped set {sorted(skipped)} != the guard's own committed files "
        f"{sorted(expected_present)}")
    return skipped


# ==========================================================================
# Behavior 1 -- the population IS the `git add -A` set
# ==========================================================================
def test_b1_the_population_is_the_git_add_all_set():
    """Cross-checked against the single combined git query, proven free of
    gitignored paths, and proven to contain the files that ship most often."""
    population = _population_or_skip(_ROOT)

    combined = set(_split_nul(_run_git_ls(
        ["ls-files", "-c", "-o", "--exclude-standard", "-z"], root=_ROOT)))
    assert set(population) == combined, (
        "the enumerated population disagrees with git's own combined "
        f"cached+others query: only-here={sorted(set(population) - combined)} "
        f"only-there={sorted(combined - set(population))}")

    # No gitignored member, asserted two independent ways: a structural check on
    # the one path shape that dominates this repo's ignored bytes, and git's own
    # verdict over the whole set.
    state_members = [rel for rel in population
                     if re.match(r"products/[^/]+/state/", rel)]
    assert state_members == [], (
        f"gitignored iteration state leaked into the population: "
        f"{state_members[:5]}")
    ignored = subprocess.run(
        ["git", "check-ignore", "--stdin", "-z"],
        cwd=str(_ROOT), input="\0".join(population),
        capture_output=True, text=True,
    )
    assert _split_nul(ignored.stdout) == [], (
        "git claims these population members are ignored, so they cannot ship "
        f"and must not be scanned as if they could: {_split_nul(ignored.stdout)[:5]}")

    absent = [rel for rel in _MUST_COVER if rel not in population]
    assert absent == [], (
        f"files that ship on nearly every commit are missing from the "
        f"population: {absent}")


# ==========================================================================
# Behavior 2 -- the whole population scans clean under the committed denylist
# ==========================================================================
def test_b2_the_whole_shipping_population_scans_clean():
    """The brake itself. On failure the message names every offending line, so
    an engineer fixes a named line instead of re-running a scan."""
    population, tracked = _population_and_tracked_or_skip(_ROOT)
    guard, patterns = _load_guard(_SCRIPTS_DIR)
    assert len(patterns) >= 1, "the committed denylist decoded to no patterns"

    findings, files_scanned, missing = _scan_population(
        _ROOT, population, guard, patterns)

    _assert_no_fatal_missing(missing, tracked, _ROOT)
    assert files_scanned >= 1, "the brake scanned nothing at all"
    assert findings == (), (
        f"public-safety: {len(findings)} banned token(s) in the shipping "
        "population would BLOCK the ship (the final gate REVERTS the whole "
        "iteration for this). Fix the line(s) below:\n"
        + _render(findings, _ROOT))


# ==========================================================================
# Behavior 3 -- coverage strictly exceeds the iteration-210 population
# ==========================================================================
def test_b3_coverage_strictly_exceeds_the_tests_only_population():
    """Containment plus a FLOOR on the widening, never an exact count.

    The containment asserted is the one that actually holds: every non-ignored
    ``*.py`` under ``tests/`` is a population member. A gitignored one is
    tolerated on purpose -- it cannot ship, so requiring it would red a suite for
    local scratch state, which is the precondition trap that broke a shipped
    iteration once already.
    """
    population = _population_or_skip(_ROOT)
    on_disk = {
        path.relative_to(_ROOT).as_posix()
        for path in _TESTS_DIR.rglob("*.py")
        if "__pycache__" not in path.parts
    }
    assert on_disk, "no python file under tests/ at all"

    gap = sorted(on_disk - set(population))
    if gap:
        ignored = subprocess.run(
            ["git", "check-ignore", "--stdin", "-z"],
            cwd=str(_ROOT), input="\0".join(gap),
            capture_output=True, text=True,
        )
        unexplained = sorted(set(gap) - set(_split_nul(ignored.stdout)))
        assert unexplained == [], (
            "these iteration-210 population members are NOT in this brake's "
            f"population and git does not ignore them: {unexplained}")

    outside = [rel for rel in population
               if not (rel.startswith("tests/") and rel.endswith(".py"))]
    assert len(outside) >= _OUTSIDE_FLOOR, (
        f"only {len(outside)} population member(s) lie outside tests/**/*.py, "
        f"below the floor of {_OUTSIDE_FLOOR}: this brake would no longer widen "
        "coverage beyond iteration 210's")


# ==========================================================================
# Behavior 4 -- the silently-skipped set is PINNED
# ==========================================================================
def test_b4_the_silently_skipped_set_is_pinned_to_the_scanners_own_files():
    """Exactly the guard's two committed files are dropped, and the scan's own
    file count reconciles with that -- so no third file can vanish unnoticed."""
    population, tracked = _population_and_tracked_or_skip(_ROOT)
    guard, patterns = _load_guard(_SCRIPTS_DIR)

    skipped = _assert_skip_set_is_pinned(population, guard)
    assert len(skipped) == len(_EXPECTED_SKIPS), (
        f"the guard's own {len(_EXPECTED_SKIPS)} committed files should be the "
        f"skipped set; got {sorted(skipped)}")

    _findings, files_scanned, missing = _scan_population(
        _ROOT, population, guard, patterns)
    vanished = _assert_no_fatal_missing(missing, tracked, _ROOT)
    # The reconciliation subtracts the DISCLOSED tolerance rather than ignoring
    # it: a member that vanished mid-scan is one fewer file read, so leaving it
    # out of this arithmetic would recreate the same false red one line lower.
    assert files_scanned == len(population) - len(skipped) - len(vanished), (
        f"{files_scanned} file(s) scanned of {len(population)} enumerated with "
        f"{len(skipped)} pinned skip(s) and {len(vanished)} disclosed vanished: "
        "the scanner dropped "
        f"{len(population) - len(skipped) - len(vanished) - files_scanned} "
        "file(s) silently")


# ==========================================================================
# Behavior 5 -- widening the skip list cannot silently shrink coverage
# ==========================================================================
def test_b5_widening_the_skip_list_cannot_silently_shrink_coverage(monkeypatch):
    """The two-sided half of Behavior 4.

    Without this, Behavior 4 would pass for ANY skip list that happened to match
    two files. Mutates only a module object loaded in-process; nothing on disk
    changes.
    """
    population = _population_or_skip(_ROOT)
    guard, patterns = _load_guard(_SCRIPTS_DIR)

    victim = "foundry.py"
    assert victim in population, "fixture needs a real source file to hide"
    before_skipped = set(_skipped_members(population, guard))
    _findings, before, missing_before = _scan_population(
        _ROOT, population, guard, patterns)

    monkeypatch.setattr(
        guard, "LEAK_GUARD_SKIP_PATHS",
        tuple(guard.LEAK_GUARD_SKIP_PATHS) + (victim,))

    with pytest.raises(AssertionError) as excinfo:
        _assert_skip_set_is_pinned(population, guard)
    message = str(excinfo.value)
    assert victim in message, (
        "the pin failed without naming the newly hidden path, so an engineer "
        f"could not tell WHICH file left the scan: {message}")

    # The widening really does shrink coverage -- otherwise the pin would be
    # reddening for a difference that costs nothing. The dropped set is DERIVED,
    # never assumed to be one file: the skip rule is a POSIX-SUFFIX match, so a
    # single added entry also hides every path ending in it (adding `foundry.py`
    # hides `tests/test_foundry.py` too, measured). That collateral reach is
    # itself the fail-open the pin closes, so every dropped path must be named.
    newly_hidden = sorted(
        rel for rel in population
        if rel not in before_skipped and guard._should_skip(rel))
    assert len(newly_hidden) >= 1, "the fixture hid nothing at all"
    unnamed = [rel for rel in newly_hidden if rel not in message]
    assert unnamed == [], (
        f"the pin hid {newly_hidden} but its message named none of {unnamed}")

    _findings2, after, missing_after = _scan_population(
        _ROOT, population, guard, patterns)
    # The reconciliation is stated on the DELTA of UNREADABLE members, not on the
    # assumption that it is zero: a member another worker unlinks between the two
    # scans is one fewer file read for a reason that has nothing to do with the
    # skip list, and `after == before - len(newly_hidden)` would red for it. A
    # path that was unreadable first and is skipped second cancels correctly,
    # because a skipped path never reaches the read and so never counts missing.
    drift = len(missing_after) - len(missing_before)
    assert after == before - len(newly_hidden) - drift, (
        f"expected the widened skip list to drop exactly {newly_hidden} from "
        f"the scan; scanned {before} then {after} with an unreadable-member "
        f"drift of {drift}")


# ==========================================================================
# Behavior 6 -- a planted literal in a NON-test file is reported with its line
# ==========================================================================
def test_b6_a_planted_literal_in_a_non_test_file_is_reported_with_its_line(
        tmp_path):
    """Proves the scan SURFACES a hit in the newly covered file classes rather
    than swallowing it.

    Planted under ``tmp_path`` on purpose -- never in the real tree, where it
    would be the very defect this brake exists to stop -- and the needle is
    assembled at runtime for the same reason.
    """
    guard, patterns = _load_guard(_SCRIPTS_DIR)
    docs = tmp_path / "docs"
    docs.mkdir()
    clean = tmp_path / "README.md"
    clean.write_text("# clean\n\nnothing banned here\n", encoding="utf-8")
    planted = docs / "note.md"
    planted.write_text(
        "# a doc that is not a test file\n"
        "\n"
        "see " + _home_prefix() + "somebody/project/x for context\n"
        "\n"
        "trailing clean line\n",
        encoding="utf-8")

    findings, files_scanned, missing = guard.scan_paths(
        [str(clean), str(planted)], patterns)

    assert missing == ()
    assert files_scanned == 2
    assert len(findings) == 1, (
        "expected exactly one finding from the planted doc; got "
        f"{[(pathlib.Path(p).name, n) for p, n, _s in findings]}")
    got_path, got_lineno, got_snippet = findings[0]
    assert got_path == str(planted)
    assert got_lineno == 3
    assert "for context" in got_snippet


# ==========================================================================
# Behavior 7 -- degrades to SKIP, never to red
# ==========================================================================
def test_b7_an_unsupported_repo_skips_rather_than_failing(tmp_path,
                                                          monkeypatch):
    """Two unsupported-repo cases, both a skip.

    (a) either committed guard file absent -- including HALF present, since a
    half-present guard cannot be loaded and treating it as available would be a
    crash dressed up as a leak; (b) the enumeration cannot run, forced through
    the seam for both realistic causes (no ``git`` binary, and not a work tree).
    """
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    with pytest.raises(pytest.skip.Exception):
        _load_guard(scripts)
    (scripts / _GUARD_BASENAME).write_text("# not the real guard\n",
                                           encoding="utf-8")
    with pytest.raises(pytest.skip.Exception):
        _load_guard(scripts)

    def _no_git(_args, *, root):
        raise FileNotFoundError("git")

    monkeypatch.setattr(_THIS_MODULE, "_run_git_ls", _no_git)
    with pytest.raises(pytest.skip.Exception):
        _population_or_skip(_ROOT)

    def _not_a_work_tree(args, *, root):
        raise subprocess.CalledProcessError(128, ["git", *args])

    monkeypatch.setattr(_THIS_MODULE, "_run_git_ls", _not_a_work_tree)
    with pytest.raises(pytest.skip.Exception):
        _population_or_skip(_ROOT)

    def _empty(_args, *, root):
        return ""

    monkeypatch.setattr(_THIS_MODULE, "_run_git_ls", _empty)
    with pytest.raises(pytest.skip.Exception):
        _population_or_skip(_ROOT)


# ==========================================================================
# Behavior 8 -- offline, bounded, and the control path still imports
# ==========================================================================
def test_b8_the_scan_is_offline_bounded_and_the_control_path_imports(
        monkeypatch):
    """Every process and socket seam is armed to RAISE for the duration of the
    SCAN, so "offline" is enforced rather than asserted in prose.

    The population AND its tracked half are enumerated, and the guard loaded,
    BEFORE the seams are armed: the enumeration is legitimately read-only git
    plumbing, and loading a module under a poisoned ``subprocess`` would fail for
    a reason that has nothing to do with the brake. The tracked half is therefore
    in hand before ``run_git`` is armed to raise, so classifying an unreadable
    member costs the armed window no git call at all.
    """
    population, tracked = _population_and_tracked_or_skip(_ROOT)
    guard, patterns = _load_guard(_SCRIPTS_DIR)

    def _forbidden(*_args, **_kwargs):
        raise AssertionError(
            "the scan must not start a process or open a socket")

    for name in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, _forbidden)
    monkeypatch.setattr(guard, "run_git", _forbidden)
    monkeypatch.setattr(socket, "socket", _forbidden)

    started = time.perf_counter()
    findings, files_scanned, missing = _scan_population(
        _ROOT, population, guard, patterns)
    elapsed = time.perf_counter() - started

    _assert_no_fatal_missing(missing, tracked, _ROOT)
    assert files_scanned >= 1
    assert findings == (), _render(findings, _ROOT)
    assert elapsed < _SCAN_BUDGET_S, (
        f"the population scan took {elapsed:.3f}s against a {_SCAN_BUDGET_S}s "
        "stall budget: it is no longer a cheap always-on brake")
    assert foundry.__file__ and dispatcher.__file__


# ==========================================================================
# Acceptance criteria
# ==========================================================================
def test_ac_both_control_path_modules_still_import():
    """This iteration touches no control-path module; prove it, cheaply."""
    assert foundry.__file__ and dispatcher.__file__


def test_ac_this_module_is_inside_the_population_it_scans_and_is_clean():
    """A brake outside its own population leaves one file of permanently
    unguarded surface -- and that file is the one an author edits most while
    writing the brake."""
    population = _population_or_skip(_ROOT)
    own = pathlib.Path(__file__).resolve().relative_to(_ROOT).as_posix()
    assert own in population, f"{own} is outside the population it scans"

    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert _home_prefix() not in source, (
        "this module contains an absolute home-directory prefix")
    assert str(pathlib.Path.home()) not in source, (
        "this module contains this machine's real home path")


def test_ac_the_brake_pins_no_ambient_file_count():
    """A fresh clone with a different number of files must still pass.

    An ambient COUNT precondition is the trap that broke a shipped iteration
    once already: it holds in this working tree and fails in the throwaway clone
    the release gate verifies from. The counts are computed and searched for
    here, never spelled -- spelling one would BE the pin it forbids.

    THE SEARCH IS OVER CODE ONLY (``foundry.prose_stripped_source``), because a
    precondition can only live in code, while PROSE legitimately names iteration
    numbers -- and one of those numbers eventually EQUALS an ambient count. That
    coincidence reverted a whole behavior-complete iteration once, so the domain
    of this brake, not the prose, was the defect. Stripping is fail-closed: an
    untokenisable source comes back unchanged, so this can never search less.
    """
    population = _population_or_skip(_ROOT)
    on_disk = [path for path in _TESTS_DIR.rglob("*.py")
               if "__pycache__" not in path.parts]
    source = foundry.prose_stripped_source(
        pathlib.Path(__file__).read_text(encoding="utf-8"))
    for label, count in (("population size", len(population)),
                         ("tests/**/*.py count", len(on_disk))):
        assert re.search(r"\b" + str(count) + r"\b", source) is None, (
            f"this module spells today's {label} ({count}); the brake must "
            "assert a floor so a clone with a different population still passes")
