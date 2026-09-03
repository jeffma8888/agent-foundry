"""Iteration 219 -- INDEPENDENT verification that the whole-population leak brake
tells an INFRASTRUCTURE condition apart from a real leak, and that no test writes
a transient artifact into the shared repo root.

TESTER ISOLATION: written from the iteration-219 PM spec's Expected Behaviors
only. The engineer's notes, the reviewer's notes and `git diff` were NOT read.
Everything below is driven through the brake module's own public surface, or
observed by RUNNING the target test -- both are files under `tests/`, which the
isolation contract explicitly permits.

WHY THE TWO-SIDED SHAPE IS NOT CEREMONY: a red suite is an unconditional ship
blocker (an honest tester writes the FAIL sentinel, the gate reverts, and a fully
verified iteration is destroyed), so a brake that reds for a non-leak is the most
expensive shape in this loop. But a tolerance that reds for NOTHING is just as bad
in the other direction -- it would mean the leak scan silently covered less than
the shipping tree. Every tolerance here is therefore asserted as a PAIR whose two
arms differ in exactly one input.

SELF-COVERING: this module sits inside the population the brake scans, so it must
itself be clean under the committed scanner. Any banned needle is ASSEMBLED from
fragments at runtime and no absolute machine path appears as a literal.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import pathlib
import socket
import subprocess
import sys
from typing import Sequence, Tuple

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_TESTS_DIR = pathlib.Path(__file__).resolve().parent
_BRAKE_PATH = _TESTS_DIR / "test_iter214_behavior.py"
_WRITER_PATH = _TESTS_DIR / "test_iter25_behavior.py"
_WRITER_TEST = "test_b10_pattern_and_json_subprocess"


def _load_by_path(name: str, path: pathlib.Path):
    """Load a module from an explicit PATH, registered in ``sys.modules`` FIRST.

    Registration must precede ``exec_module``: both target modules resolve
    ``sys.modules[__name__]`` in their own module body, so an unregistered load
    dies with a ``KeyError`` that says nothing about the real cause. Loading by
    path (rather than reusing pytest's own import) means this module owns the
    object it drives and cannot be perturbed by collection order under ``-n auto``.
    """
    if not path.is_file():
        pytest.skip(f"absent in this repo: {path.name}")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _brake():
    return _load_by_path("_iter219_brake_probe", _BRAKE_PATH)


def _classifier(mod):
    fn = getattr(mod, "_classify_missing", None)
    assert callable(fn), (
        "the brake must expose a module-level classifier splitting unreadable "
        f"population members into (fatal, vanished); found {fn!r}")
    return fn


def _banned_prefix() -> str:
    """The banned absolute home-directory prefix, ASSEMBLED at runtime.

    Never a source literal: this module is inside the population the scanner
    walks, so a contiguous copy of the needle would make a CORRECT file report
    itself -- the self-defeating shape that has cost this loop whole iterations.
    """
    return "/" + "Users" + "/"


def _brake_verdict(mod, findings, missing: Sequence[str],
                   tracked: Sequence[str], root: pathlib.Path) -> Tuple[str, ...]:
    """Replay the brake's own verdict, in the brake's own ORDER.

    The unreadable-member decision runs first and the leak assertion runs
    second, so a raised ``AssertionError`` names WHICH of the two reddened. That
    ordering is the whole point of Behavior 6: tolerating a vanished path must
    never stop the findings assertion from running.
    """
    vanished = mod._assert_no_fatal_missing(missing, tracked, root)
    assert findings == (), mod._render(findings, root)
    return vanished


# ==========================================================================
# Behavior 1 -- the classifier is pure and splits by tracked-ness
# ==========================================================================
def test_b1_classifier_splits_by_tracked_ness_and_preserves_input_order():
    mod = _brake()
    classify = _classifier(mod)
    root = pathlib.PurePath("/nowhere/in/particular")
    missing = ("z/tracked_last.py", "gone/one.txt",
               "a/tracked_first.py", "gone/two.txt")
    tracked = ("a/tracked_first.py", "z/tracked_last.py", "never/missing.py")

    fatal, vanished = classify(missing, tracked, root=pathlib.Path(root))

    assert isinstance(fatal, tuple) and isinstance(vanished, tuple)
    assert fatal == ("z/tracked_last.py", "a/tracked_first.py"), (
        "the fatal bucket must preserve INPUT order (not sort), so a report "
        f"reads in scan order; got {fatal}")
    assert vanished == ("gone/one.txt", "gone/two.txt"), vanished
    assert set(fatal) | set(vanished) == set(missing), (
        "the split must be TOTAL -- every missing member lands in exactly one "
        "bucket, or an unreadable member is silently dropped")
    assert not (set(fatal) & set(vanished))


def test_b1_classifier_is_pure_under_armed_io_seams(monkeypatch):
    """The purity claim is the cheapest claim in the spec to actually TEST, so
    arm every I/O seam to raise and assert the answer is IDENTICAL.

    This is not box-ticking: the classifier is invoked INSIDE the existing
    offline brake's armed window, so a stray stat or git call would not be a
    style defect -- it would red that brake.
    """
    mod = _brake()
    classify = _classifier(mod)
    missing = ("tracked/a.py", "vanished/b.txt")
    tracked = ("tracked/a.py",)
    root = pathlib.Path(_ROOT)

    unarmed = classify(missing, tracked, root=root)

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("the classifier must perform no I/O")

    for name in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, _forbidden)
    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(pathlib.Path, "exists", _forbidden)
    monkeypatch.setattr(pathlib.Path, "is_file", _forbidden)
    monkeypatch.setattr(pathlib.Path, "read_text", _forbidden)
    monkeypatch.setattr(pathlib.Path, "stat", _forbidden)
    if hasattr(mod, "_run_git_ls"):
        monkeypatch.setattr(mod, "_run_git_ls", _forbidden)

    armed = classify(missing, tracked, root=root)

    # DISARM BEFORE ASSERTING, and this is not tidiness. pytest builds a failure
    # report by walking the traceback, and that walk calls `pathlib.Path.exists`
    # on each frame's file. With the seams still armed, ANY failure inside this
    # window raises out of pytest's own reporting code as an INTERNALERROR, which
    # aborts the WHOLE session -- so a one-test purity regression would present as
    # a total collapse with no other result, exactly the infrastructure-vs-defect
    # confusion this iteration exists to remove. Measured, not guessed: an
    # out-of-repo mutant that breaks purity turned this file's 14 results into
    # `1 failed` plus INTERNALERROR until this line was added.
    monkeypatch.undo()

    assert armed == unarmed == (("tracked/a.py",), ("vanished/b.txt",))


# ==========================================================================
# Behavior 2 -- absolute-vs-relative is handled; this is the fail-open leg
# ==========================================================================
def test_b2_an_absolute_missing_path_is_normalised_before_the_tracked_lookup(
        tmp_path):
    """The scanner is handed ABSOLUTE strings while the tracked set is
    repo-relative. A classifier comparing the two spellings directly would put
    EVERY missing path in `vanished` and fail open on all of them, so this arm
    is the one that decides whether the fix is a narrowing or a hole.
    """
    mod = _brake()
    classify = _classifier(mod)
    rel = "pkg/sub/mod.py"
    absolute = str(tmp_path / rel)

    fatal, vanished = classify((absolute,), (rel,), root=tmp_path)

    assert fatal == (absolute,), (
        "an ABSOLUTE missing path whose repo-relative form is TRACKED must be "
        f"fatal; it was classified {('vanished' if vanished else '?')}")
    assert vanished == ()

    # Same absolute path, tracked set EMPTY: the only changed input.
    fatal_b, vanished_b = classify((absolute,), (), root=tmp_path)
    assert fatal_b == () and vanished_b == (absolute,)

    # An absolute path OUTSIDE the root can never match a repo-relative entry.
    outside = str(tmp_path.parent / "elsewhere" / rel)
    fatal_c, vanished_c = classify((outside,), (rel,), root=tmp_path)
    assert fatal_c == () and vanished_c == (outside,), (
        "a path outside the repo root cannot be tracked BY this repo")


# ==========================================================================
# Behaviors 3 + 4 -- the tolerance is a TWO-SIDED pair over one classifier
# ==========================================================================
def test_b3_b4_two_sided_pair_only_tracked_ness_differs(tmp_path):
    """The acceptance criterion's explicit pair: identical scripted population,
    identical root, differing ONLY in whether the unreadable member is tracked.
    A one-sided tolerance is a fail-open hole.
    """
    mod = _brake()
    rel = "shipped/thing.md"
    absolute = str(tmp_path / rel)

    # ARM 3 -- TRACKED and unreadable: the scan covered LESS than the shipping
    # tree, which is a real coverage hole. The brake must red.
    with pytest.raises(AssertionError) as excinfo:
        _brake_verdict(mod, (), (absolute,), (rel,), tmp_path)
    message = str(excinfo.value)
    assert "TRACKED" in message, message
    assert pathlib.PurePath(absolute).name in message, (
        f"the failure must NAME the unreadable member; got: {message}")

    # ARM 4 -- the SAME path, untracked: it can neither ship nor leak.
    vanished = _brake_verdict(mod, (), (absolute,), (), tmp_path)
    assert vanished == (absolute,), vanished


def test_b3_an_unreadable_tracked_member_reds_even_beside_a_vanished_one(
        tmp_path):
    """A vanished neighbour must not launder a tracked coverage hole."""
    mod = _brake()
    classify = _classifier(mod)
    tracked_rel = "core/keeper.py"
    tracked_abs = str(tmp_path / tracked_rel)
    gone_abs = str(tmp_path / "scratch/transient.txt")

    fatal, vanished = classify((gone_abs, tracked_abs), (tracked_rel,),
                               root=tmp_path)
    assert fatal == (tracked_abs,) and vanished == (gone_abs,)

    with pytest.raises(AssertionError):
        _brake_verdict(mod, (), (gone_abs, tracked_abs), (tracked_rel,), tmp_path)


def test_b4_a_vanished_untracked_member_does_not_red_the_brake(tmp_path):
    """The race this iteration exists to stop: another worker unlinks its own
    transient artifact between the enumeration and the read.
    """
    mod = _brake()
    classify = _classifier(mod)
    gone = str(tmp_path / "spy_of_another_worker.txt")
    tracked = ("core/keeper.py", "docs/note.md")

    fatal, vanished = classify((gone,), tracked, root=tmp_path)
    assert fatal == ()
    assert vanished == (gone,)

    assert _brake_verdict(mod, (), (gone,), tracked, tmp_path) == (gone,)


# ==========================================================================
# Behavior 5 -- the tolerance is DISCLOSED, never silent
# ==========================================================================
def test_b5_every_tolerated_path_is_named_in_a_report(tmp_path, capsys):
    mod = _brake()
    first = str(tmp_path / "scratch/one.txt")
    second = str(tmp_path / "deeper/nest/two.txt")

    vanished = mod._assert_no_fatal_missing((first, second), (), tmp_path)
    assert vanished == (first, second)

    err = capsys.readouterr().err
    for path in (first, second):
        assert pathlib.PurePath(path).name in err, (
            f"a tolerated path was NOT disclosed: {pathlib.PurePath(path).name}"
            f"\nreport was: {err!r}")
    assert str(len(vanished)) in err, (
        "the report must disclose HOW MANY members were tolerated so a "
        f"degraded scan is measurable; report was: {err!r}")
    assert str(tmp_path) not in err, (
        "the report must not print an absolute machine path -- that is the very "
        "shape the leak guard exists to keep out of public output")


def test_b5_a_clean_scan_discloses_nothing(tmp_path, capsys):
    """Two-sided half: with nothing tolerated the brake stays SILENT, so the
    disclosure means something when it appears.
    """
    mod = _brake()
    assert mod._assert_no_fatal_missing((), ("core/keeper.py",), tmp_path) == ()
    assert capsys.readouterr().err == ""


# ==========================================================================
# Behavior 6 -- leak-detection strength is untouched
# ==========================================================================
def test_b6_a_real_finding_survives_the_tolerance(tmp_path):
    """A banned literal in a readable file AND a vanished untracked path, in one
    scripted population. Tolerating the vanished path must never suppress the
    finding, and the brake must still red -- on the FINDING, not on the race.
    """
    mod = _brake()
    guard, patterns = mod._load_guard(mod._SCRIPTS_DIR)

    planted = tmp_path / "docs_note.md"
    planted.write_text(
        "# a readable file that ships\n"
        "\n"
        "see " + _banned_prefix() + "somebody/project/x for context\n",
        encoding="utf-8")
    gone = tmp_path / "scratch_transient.txt"
    assert not gone.exists()

    findings, files_scanned, missing = guard.scan_paths(
        [str(planted), str(gone)], patterns)

    assert files_scanned == 1, files_scanned
    assert missing == (str(gone),), missing
    assert len(findings) == 1, (
        "the banned literal must still be reported alongside a vanished member; "
        f"got {[(pathlib.PurePath(p).name, n) for p, n, _s in findings]}")
    found_path, found_lineno, found_snippet = findings[0]
    assert found_path == str(planted)
    assert found_lineno == 3
    assert "for context" in found_snippet

    # The vanished path is tolerated ...
    assert mod._classify_missing(missing, (), root=tmp_path) == ((), (str(gone),))
    # ... and the brake still reds, on the finding.
    with pytest.raises(AssertionError) as excinfo:
        _brake_verdict(mod, findings, missing, (), tmp_path)
    message = str(excinfo.value)
    assert planted.name in message, message
    assert "TRACKED" not in message, (
        "the brake must red on the FINDING here, not on the unreadable member; "
        f"got: {message}")


# ==========================================================================
# Behavior 7 -- no test writes a transient file into the shared repo root
# ==========================================================================
def test_b7_the_observed_writer_no_longer_targets_the_shared_repo_root(tmp_path):
    """Driven by RUNNING the target test with a temp dir this test owns.

    The discriminating leg is that the spy artifact appears under OUR temp dir:
    "no artifact at the repo root AFTERWARDS" would pass even against a writer
    that created one and unlinked it, which is exactly the window that reddened
    the brake. Deliberately NOT a scan of the whole repo root -- under `-n auto`
    a cross-worker filesystem census is itself racy, and a race is no way to
    verify a race fix.
    """
    writer = _load_by_path("_iter219_writer_probe", _WRITER_PATH)
    target = getattr(writer, _WRITER_TEST, None)
    assert callable(target), f"{_WRITER_TEST} is absent from {_WRITER_PATH.name}"

    params = inspect.signature(target).parameters
    assert "tmp_path" in params, (
        "the writer must take the pytest-provided temp dir as a fixture; its "
        f"signature is ({', '.join(params)})")

    stray = _ROOT / "spy.txt"
    assert not stray.exists(), (
        "a transient artifact is already sitting in the shared repo root before "
        "this test ran")

    target(tmp_path)  # its own assertions on the spy payload and verdict run here

    assert not stray.exists(), (
        "the writer created a transient artifact in the shared repo root, where "
        "a concurrent worker can enumerate it and then fail to read it")

    payloads = []
    for candidate in sorted(tmp_path.rglob("*")):
        if not candidate.is_file():
            continue
        try:
            payloads.append(json.loads(candidate.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    assert ["mine.py"] in payloads, (
        "the spy artifact must land under the pytest-provided temp dir and "
        f"still record the forwarded pattern; found payloads {payloads}")


# ==========================================================================
# Acceptance criteria
# ==========================================================================
def test_ac_the_population_is_still_not_narrowed(monkeypatch):
    """`-o --exclude-standard` must remain: tracked + untracked-not-ignored is
    exactly what the final gate stages, so narrowing the population would trade
    an intermittent false red for a permanent coverage hole.
    """
    mod = _brake()
    calls = []

    def _record(args, *, root):
        calls.append(list(args))
        return ""

    monkeypatch.setattr(mod, "_run_git_ls", _record)
    mod._enumerate_split(pathlib.Path(_ROOT))

    assert ["ls-files", "-z"] in calls, calls
    untracked_query = [c for c in calls if "-o" in c]
    assert untracked_query, f"the untracked half is no longer enumerated: {calls}"
    assert "--exclude-standard" in untracked_query[0], untracked_query


def test_ac_the_scanner_soft_skip_contract_is_unchanged(tmp_path):
    """The fix belongs in the brake, not the scanner: `scan_paths` must still
    RETURN an unreadable path rather than raising or counting it as scanned.
    """
    mod = _brake()
    guard, patterns = mod._load_guard(mod._SCRIPTS_DIR)
    clean = tmp_path / "clean.md"
    clean.write_text("nothing banned here\n", encoding="utf-8")
    gone = tmp_path / "never_created.md"

    findings, files_scanned, missing = guard.scan_paths(
        [str(clean), str(gone)], patterns)

    assert findings == ()
    assert files_scanned == 1
    assert missing == (str(gone),)


def test_ac_the_control_path_modules_still_import():
    """No control-path semantics change, so resume is unaffected."""
    probe = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True)
    assert probe.returncode == 0, probe.stderr


def test_ac_this_module_carries_no_absolute_machine_path():
    """This module is inside the population the scanner walks."""
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert _banned_prefix() not in source
    assert str(pathlib.Path.home()) not in source
