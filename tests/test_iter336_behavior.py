"""Iteration 336 -- BLACK-BOX behavior tests: doctor's SIXTH never-blocking drift line.

`losses` (#51) has classified `auth` since iteration 173 and `ATTEMPT_FAILURE_MARKERS`
has documented since iteration 196 that it is the ONE failure kind no retry, no sleep and
no smaller bite can heal -- only a human re-authenticating.  That verdict reached no
surface an operator runs unattended.  This iteration gives it one: `foundry doctor` prints
a sixth report-only drift line, `auth-loss:`.

SPEC UNDER TEST -- and the one ambiguity this module had to resolve.  The spec
(`products/_platform/state/iter-336/pm.md`) is a WRITE-EARLY CHECKPOINT: both PM scouts
and the PM stage were cap-killed, so its `## Expected Behaviors` section reads verbatim

    1. TBD -- refining.

and its only acceptance criterion is "full quality-check suite passes".  There is
therefore NO numbered fidelity checklist to encode.  Following the role card's rule for an
ambiguous spec ("test the most reasonable reading and note the ambiguity"), the behaviors
below are DERIVED -- and derived only from text this module's author is allowed to read:

  * the spec's `## Feature` paragraph, which is the whole contract: "One additional
    never-blocking `auth-loss:` line in `foundry doctor`, derived from the already-shipped
    attempt-log loss classification";
  * the spec's `## Why` ("the fact that a HUMAN must re-authenticate reaches the one
    command an operator actually runs") and its `## Out of Scope` (no change to the retry
    ladder, `run_stage` or the dispatcher control path; no flag file written from the live
    pipeline path);
  * the product's OWN DOCUMENTED SURFACE, read by RUNNING it -- `inspect.getdoc` on the
    public callables, exactly as `tests/test_iter230_behavior.py` pins
    `run_doctor_cli.__doc__`; and README `# 0.` plus the two roadmap files.

The behaviors:
   1. `AUTH_LOSS_PREFIX` is the non-empty grep anchor `"auth-loss:"`, pairwise-distinct
      from the five older drift prefixes; `AUTH_LOSS_KIND` is the shipped `losses` kind
      `"auth"`; the window and WARN-word constants are well-formed.
   2. `auth_loss_verdict` is PURE and TOTAL: an `AuthLossVerdict` comes back for every
      scripted digest -- real-shaped, empty, `None`, an int, a str, rows missing `kind`,
      rows with a non-numeric `lost` -- with `subprocess`/`socket` forbidden and the only
      I/O seam patched to raise.  It never raises.
   3. Selection semantics: `lost` is SUMMED across matching rows, `stage_count` counts
      DISTINCT stage labels, rows of every other kind are ignored, and `AUTH_LOSS_KIND`
      is read by BARE name at CALL time so a monkeypatch re-targets the selection.
   4. `auth_loss_line` is TOTAL: a non-empty, newline-free `str` starting with the prefix
      for every scripted `gather_losses` state including a raiser, `None` and an int.
   5. THREE distinct outcomes, fail-SAFE: WARN names count, denominator, share, distinct
      stage count and the RE-AUTHENTICATE remedy; OK only when something was scanned and
      nothing lost; nothing scanned (and every internal failure) degrades to UNKNOWN,
      which carries neither `AUTH_LOSS_WARN` nor an OK claim.
   6. Windowing: a positive `limit` is passed to `gather_losses` and NAMED in words in
      BOTH decided branches; `limit=None` omits the clause; the seam is composed by BARE
      module name exactly ONCE per call.
   7. COUNTS ONLY -- no stage label ever reaches the line, including hostile labels
      carrying an `ACTION:`/`PRESHIP:` sentinel or a path body, because `roles/pm.md`
      quotes doctor lines VERBATIM into specs.
   8. `run_doctor_cli` prints the line exactly ONCE, LAST of the six, with each older
      prefix still exactly once; the exit code is untouched over {all-pass, one-failing}
      x every scripted state; the summary still reads `out of 4`; `run_doctor` still
      returns exactly four `Check`s and its source names no new symbol; doctor reads
      `AUTH_LOSS_RECENT_ITERATIONS` at CALL time.
   9. REPORT-ONLY and RESUME-SAFE: `dispatcher.py`'s text and the sources of
      `run_iteration`, `run_stage` and `build_prompt` name NONE of the six new symbols,
      and `auth_loss_line` has exactly ONE call site -- so a loop in flight resumes
      byte-identically (the spec's Out of Scope).
  10. Writes NOTHING to disk, and an END-TO-END pass over a fabricated state dir (the
      REAL `gather_losses` seam, no monkeypatch) reproduces the count -- which is what
      "derived from the already-shipped attempt-log loss classification" means.
  11. Records, decidable from git-TRACKED text alone so every verdict still holds in the
      throwaway FRESH CLONE the release gate builds (OPERATOR 2026-08-11): README `# 0.`
      announces SIX drift lines, this iteration's ledger row and archive bullet land in
      the SAME diff as the code (`roadmap_ledger_gaps` is `[]`), and this module is on the
      iter-204 b15 allow-list.
  12. DISCRIMINATION (added by the retry round, because a guard that asserts only its
      GOOD arm on a REAL artifact is indistinguishable from a vacuous one).  The
      lost-record brake FIRES `[336]` once BOTH of this iteration's records are deleted
      in memory -- and deleting only ONE leaves it silent BY DESIGN, its own docstring
      saying a record in EITHER file counts, which is why behavior 11's `== []` is NOT
      what pins both files and the per-file row/bullet counts are (proved on both arms).
      The README count-word check is a FUNCTION proved on both arms; the two negative
      source scans are shown to be reading real text AND to fire where the symbol does
      belong; purity is re-proved with the FILESYSTEM banned too; the share is the ratio
      at one decimal over five ratios including a 1-in-1000 that still WARNs; every one
      of the six anchors is grep-unique as a SUBSTRING of doctor's whole stdout; the
      record itself carries counts only; and the line is deterministic.

ISOLATION CONTRACT (HONORED): the implementation TEXT of `foundry.py` was NOT read by the
author.  `engineer.md`, `reviewer.md`, `fix_review.md`, `IMPLEMENTATION.patch`,
`pm_scout_a.md`, `pm_scout_b.md` and `git diff` were NOT read.  Where a behavior is only
decidable from source text (behaviors 8 and 9) the text is handed to a machine scan and
never inspected by hand.

Offline and deterministic: every behavior either scripts `gather_losses` by BARE module
name or builds its own state dir under `tmp_path`, so no real network or git runs and no
assertion reads a gitignored path or counts files in the ambient tree.
"""

from __future__ import annotations

import builtins
import contextlib
import dataclasses
import inspect
import io
import pathlib
import re
import socket
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe

THIS_ITER = 336

README = _ROOT / "README.md"
ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
DISPATCHER = _ROOT / "dispatcher.py"
ALLOW_LIST_MODULE = _ROOT / "tests" / "test_iter204_behavior.py"

# A RELATIVE literal: an absolute machine path in a shipped test is a leak-guard finding
# (OPERATOR 2026-08-30, which reverted iteration 205 over exactly this shape).
REL_REPO = "products/_platform/state/iter-336"

# Names are FIXED by the feature paragraph's own vocabulary, so they are reached by string
# here: a rename must fail these tests loudly rather than silently stop testing anything.
PREFIX_NAME = "AUTH_LOSS_PREFIX"
KIND_NAME = "AUTH_LOSS_KIND"
WINDOW_NAME = "AUTH_LOSS_RECENT_ITERATIONS"
WARN_NAME = "AUTH_LOSS_WARN"
LINE_FN = "auth_loss_line"
VERDICT_FN = "auth_loss_verdict"
SEAM = "gather_losses"

NEW_SYMBOLS = (PREFIX_NAME, KIND_NAME, WINDOW_NAME, WARN_NAME, LINE_FN, VERDICT_FN)

OLDER_PREFIX_NAMES = (
    "LIVE_LAG_PREFIX",
    "LEARNINGS_HEAD_PREFIX",
    "ROADMAP_INDEX_PREFIX",
    "STAGE_BUDGET_PREFIX",
    "TEST_TOUCH_PREFIX",
)


# ========================================================================== #
# Stubs -- every one duck-typed, so no test needs the real dataclasses
# ========================================================================== #
class _Chk:
    """Minimal stand-in check result for the doctor-CLI guards (iter-145/230 shape)."""

    def __init__(self, name, ok, detail="detail-text"):
        self.name = name
        self.ok = ok
        self.detail = detail


class _G:
    """Stage-times group stub: the four attributes the iter-164 line consumes."""

    def __init__(self, stage, median_s, timeouts=0, count=1):
        self.stage = stage
        self.median_s = median_s
        self.timeouts = timeouts
        self.count = count


class _S:
    def __init__(self, *groups):
        self.groups = tuple(groups)


class _Row:
    """A loss row: the three attributes the verdict is documented to duck-type on."""

    def __init__(self, kind, lost, stages=()):
        self.kind = kind
        self.lost = lost
        self.stages = stages


class _NoKind:
    """A row-shaped object with NO `kind` -- must be SKIPPED, never fatal."""

    def __init__(self):
        self.lost = 99
        self.stages = ("ghost",)


class _Dig:
    """A loss digest: `attempts` plus a `rows` iterable."""

    def __init__(self, attempts, rows=()):
        self.attempts = attempts
        self.rows = tuple(rows)


def _cfg(**over):
    kw = dict(name="demo", repo=REL_REPO, allowed_push_repo="demo")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _prefix() -> str:
    return getattr(foundry, PREFIX_NAME)


def _line(cfg, **kw) -> str:
    return getattr(foundry, LINE_FN)(cfg, **kw)


def _verdict(digest):
    return getattr(foundry, VERDICT_FN)(digest)


def _seam(monkeypatch, result, calls=None):
    """Script `gather_losses` by BARE module name; record every call.

    `result` is either the value to return or an exception INSTANCE to raise.
    """

    def fake(*a, **kw):
        if calls is not None:
            calls.append((a, dict(kw)))
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(foundry, SEAM, fake)


def _forbid_outside_world(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the drift line reached the outside world")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)
    monkeypatch.setattr(socket, "socket", boom)


def _stub_checks(monkeypatch, *, fail=None):
    for nm in ("power", "agent", "uv", "remote"):
        monkeypatch.setattr(
            foundry, f"check_{nm}",
            lambda *a, _n=nm, **k: _Chk(_n, _n != fail))


def _patch_older_lines(monkeypatch):
    """Script the five OLDER drift lines' upstream seams so no test reads live state."""
    monkeypatch.setattr(foundry, "parse_brain_launch", lambda *a, **k: 1000.0)
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: ((1, 900.0),))
    monkeypatch.setattr(
        foundry, "gather_stage_times",
        lambda *a, **k: _S(_G("engineer", 100.0, 0, 9)))
    monkeypatch.setattr(
        foundry, "probe_test_touch",
        lambda *a, **k: "clean -- 0 uncommitted path(s), so no test-dir touch to report")


def _doctor_cfg(tmp_path):
    p = tmp_path / "IDX.md"
    p.write_text("# roadmap\n\nsome prose\n", encoding="utf-8")
    return _cfg(roadmap=str(p), learnings=str(tmp_path / "no-such-learnings.md"),
                work_root=str(tmp_path))


def _doctor_out(cfg):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.run_doctor_cli(cfg)
    return rc, buf.getvalue()


def _lines_with(out, prefix):
    return [ln for ln in out.splitlines() if ln.startswith(prefix)]


def _first_index(out, prefix):
    for i, ln in enumerate(out.splitlines()):
        if ln.startswith(prefix):
            return i
    return -1


# The scripted digest states every totality guard sweeps.  A raiser, a `None` and an int
# are the three shapes a real seam produces on a missing / unreadable / mis-derived state
# dir, and they are the ones a "never raises" claim has to survive.
SEAM_STATES = (
    ("warn", _Dig(9, [_Row("auth", 2, ("a", "b"))])),
    ("ok", _Dig(11, [_Row("timeout", 4, ("x",))])),
    ("empty", _Dig(0, [])),
    ("none", None),
    ("int", 17),
    ("no-kind-row", _Dig(5, [_NoKind()])),
    ("raiser", RuntimeError("seam exploded")),
)

JUNK_DIGESTS = (
    None,
    17,
    "a string",
    _Dig(0, []),
    _Dig(3, [None, 5, _Row("auth", "not-a-number", None)]),
    _Dig(4, [_NoKind()]),
)


# ========================================================================== #
# Behavior 1 -- the grep anchor and the constants
# ========================================================================== #
def test_b1_prefix_is_the_expected_nonempty_grep_anchor() -> None:
    prefix = _prefix()
    assert isinstance(prefix, str)
    assert prefix.strip(), "the grep anchor is empty or whitespace-only"
    assert prefix == "auth-loss:"


@pytest.mark.parametrize("other_name", OLDER_PREFIX_NAMES)
def test_b1_prefix_is_distinct_from_every_older_drift_prefix(other_name) -> None:
    """Six lines share one stdout, so a shared anchor would make `grep` ambiguous."""
    other = getattr(foundry, other_name)
    assert isinstance(other, str) and other, other_name
    assert _prefix() != other, f"{PREFIX_NAME} collides with {other_name}"


def test_b1_the_six_prefixes_are_all_pairwise_distinct() -> None:
    all_names = (PREFIX_NAME,) + OLDER_PREFIX_NAMES
    values = [getattr(foundry, n) for n in all_names]
    assert len(set(values)) == len(all_names), values


def test_b1_the_selected_kind_is_the_shipped_losses_kind() -> None:
    """The feature is a READER of the shipped classification, so the kind must be ITS."""
    kind = getattr(foundry, KIND_NAME)
    assert kind == "auth"
    shipped = {k for k, _needles in foundry.ATTEMPT_FAILURE_MARKERS}
    assert kind in shipped, \
        f"{KIND_NAME}={kind!r} is not a kind `classify_attempt_failure` can ever assign"


def test_b1_window_and_warn_constants_are_wellformed() -> None:
    window = getattr(foundry, WINDOW_NAME)
    assert isinstance(window, int) and window > 0, window
    warn = getattr(foundry, WARN_NAME)
    assert isinstance(warn, str) and warn.strip(), warn


# ========================================================================== #
# Behavior 2 -- the verdict is PURE and TOTAL
# ========================================================================== #
@pytest.mark.parametrize("digest", JUNK_DIGESTS, ids=lambda d: type(d).__name__)
def test_b2_verdict_returns_a_record_for_every_junk_digest(monkeypatch, digest) -> None:
    """A mis-derived input must yield an assertable RECORD, never a traceback."""
    _forbid_outside_world(monkeypatch)
    _seam(monkeypatch, AssertionError("the pure verdict called the I/O seam"))
    v = _verdict(digest)
    assert isinstance(v, foundry.AuthLossVerdict), type(v)
    assert isinstance(v.attempts, int) and v.attempts >= 0
    assert isinstance(v.lost, int) and v.lost >= 0
    assert isinstance(v.stage_count, int) and v.stage_count >= 0


def test_b2_verdict_never_touches_the_io_seam(monkeypatch) -> None:
    _forbid_outside_world(monkeypatch)
    _seam(monkeypatch, AssertionError("the pure verdict called the I/O seam"))
    v = _verdict(_Dig(9, [_Row("auth", 2, ("a", "b"))]))
    assert (v.attempts, v.lost, v.stage_count) == (9, 2, 2)


def test_b2_verdict_is_frozen_and_value_equal() -> None:
    a = _verdict(_Dig(9, [_Row("auth", 2, ("a", "b"))]))
    b = _verdict(_Dig(9, [_Row("auth", 2, ("b", "a"))]))
    assert a == b, "the record must be VALUE-equal, so two equal digests agree"
    assert hash(a) == hash(b), "the record must be hashable (frozen)"
    with pytest.raises(Exception):
        a.lost = 100  # frozen: no post-hoc mutation


# ========================================================================== #
# Behavior 3 -- selection semantics
# ========================================================================== #
def test_b3_lost_is_summed_across_every_matching_row() -> None:
    v = _verdict(_Dig(20, [_Row("auth", 2, ("a",)), _Row("auth", 5, ("b",))]))
    assert v.lost == 7, "a duck-typed multi-row digest must SUM, not report the first"


def test_b3_stage_count_counts_distinct_labels_only() -> None:
    v = _verdict(_Dig(20, [_Row("auth", 2, ("a", "b", "a")), _Row("auth", 1, ("b",))]))
    assert v.stage_count == 2, "labels must be DEDUPLICATED across rows"


def test_b3_rows_of_every_other_kind_are_ignored() -> None:
    v = _verdict(_Dig(20, [_Row("timeout", 9, ("t",)), _Row("stalled", 4, ("s",))]))
    assert (v.lost, v.stage_count) == (0, 0), \
        "real lost work of another kind is not work re-authenticating recovers"
    assert v.attempts == 20, "the denominator is every attempt SCANNED, not just matches"


def test_b3_the_kind_is_read_by_bare_name_at_call_time(monkeypatch) -> None:
    """A `monkeypatch.setattr(foundry, KIND, ...)` must re-target the selection."""
    digest = _Dig(20, [_Row("auth", 2, ("a",)), _Row("timeout", 9, ("t", "u"))])
    assert _verdict(digest).lost == 2
    monkeypatch.setattr(foundry, KIND_NAME, "timeout")
    re_targeted = _verdict(digest)
    assert (re_targeted.lost, re_targeted.stage_count) == (9, 2), \
        f"{KIND_NAME} was captured at def time, so the selection cannot be re-targeted"


# ========================================================================== #
# Behavior 4 -- the LINE is TOTAL
# ========================================================================== #
@pytest.mark.parametrize("state,result", SEAM_STATES, ids=[s for s, _ in SEAM_STATES])
def test_b4_line_is_one_nonempty_prefixed_line_in_every_state(
        monkeypatch, tmp_path, state, result) -> None:
    _forbid_outside_world(monkeypatch)
    _seam(monkeypatch, result)
    out = _line(_cfg(work_root=str(tmp_path)))
    assert isinstance(out, str), type(out)
    assert out.strip(), f"empty line for state {state}"
    assert "\n" not in out, f"embedded newline for state {state}: {out!r}"
    assert out.startswith(_prefix()), out


@pytest.mark.parametrize("state,result", SEAM_STATES, ids=[s for s, _ in SEAM_STATES])
def test_b4_line_never_raises_in_any_state(monkeypatch, tmp_path, state, result) -> None:
    """A diagnostic that can crash the preflight it decorates is worse than none."""
    _forbid_outside_world(monkeypatch)
    _seam(monkeypatch, result)
    try:
        _line(_cfg(work_root=str(tmp_path)), limit=5)
    except BaseException as exc:  # pragma: no cover -- only on a real defect
        pytest.fail(f"state {state} raised {type(exc).__name__}: {exc}")


# ========================================================================== #
# Behavior 5 -- three distinct outcomes, fail-SAFE
# ========================================================================== #
def _body(monkeypatch, result, **kw):
    _seam(monkeypatch, result)
    return _line(_cfg(), **kw)


def test_b5_warn_names_count_denominator_share_stages_and_the_remedy(
        monkeypatch) -> None:
    out = _body(monkeypatch, _Dig(9, [_Row("auth", 2, ("a", "b"))]))
    warn = getattr(foundry, WARN_NAME)
    assert warn in out, out
    assert "2/9" in out, f"the count and its denominator must both appear: {out}"
    assert "22.2%" in out, f"the SHARE makes it a rate an operator can act on: {out}"
    assert "2 distinct stage(s)" in out, out
    assert re.search(r"re-authenticat", out, re.I), \
        f"the WARN must name the remedy a HUMAN owes: {out}"
    assert "no retry" in out and "no sleep" in out, \
        f"the WARN must say why no automatic recovery applies: {out}"


def test_b5_ok_requires_something_scanned_and_nothing_lost(monkeypatch) -> None:
    out = _body(monkeypatch, _Dig(11, [_Row("timeout", 4, ("x",))]))
    assert "OK" in out, out
    assert "0/11" in out, out
    assert getattr(foundry, WARN_NAME) not in out.replace("OK", ""), out
    assert "UNKNOWN" not in out, out


@pytest.mark.parametrize("result", [_Dig(0, []), None, 17, RuntimeError("boom")],
                         ids=["empty", "none", "int", "raiser"])
def test_b5_nothing_scanned_degrades_to_unknown_never_to_ok(monkeypatch, result) -> None:
    """Reporting a clean window off a scan that did not run is the one banned direction."""
    out = _body(monkeypatch, result)
    assert "UNKNOWN" in out, out
    assert getattr(foundry, WARN_NAME) not in out, \
        f'"I cannot tell" is not evidence of harm: {out}'
    assert not re.search(r"\bOK\b", out), \
        f'"I cannot tell" is not evidence of health either: {out}'


def test_b5_the_three_outcome_bodies_are_pairwise_distinct(monkeypatch) -> None:
    bodies = {
        "warn": _body(monkeypatch, _Dig(9, [_Row("auth", 2, ("a",))])),
        "ok": _body(monkeypatch, _Dig(11, [])),
        "unknown": _body(monkeypatch, _Dig(0, [])),
    }
    assert len(set(bodies.values())) == 3, \
        f"three outcomes demand different actions, so they must read differently: {bodies}"


# ========================================================================== #
# Behavior 6 -- windowing, and ONE composed call
# ========================================================================== #
@pytest.mark.parametrize("result,label", [(_Dig(9, [_Row("auth", 2, ("a",))]), "warn"),
                                          (_Dig(11, []), "ok")])
def test_b6_a_positive_limit_is_named_in_words_in_both_decided_branches(
        monkeypatch, result, label) -> None:
    """No reader may mistake a RECENT rate for an all-time one."""
    out = _body(monkeypatch, result, limit=5)
    assert "5 most-recent iteration(s)" in out, f"{label} branch hid its window: {out}"


@pytest.mark.parametrize("result,label", [(_Dig(9, [_Row("auth", 2, ("a",))]), "warn"),
                                          (_Dig(11, []), "ok")])
def test_b6_limit_none_omits_the_window_clause(monkeypatch, result, label) -> None:
    out = _body(monkeypatch, result, limit=None)
    assert "most-recent" not in out, \
        f"an all-time scan must NOT claim a window: {out}"


def test_b6_the_limit_reaches_the_seam(monkeypatch) -> None:
    calls: list = []
    _seam(monkeypatch, _Dig(9, [_Row("auth", 2, ("a",))]), calls)
    _line(_cfg(), limit=5)
    assert len(calls) == 1, f"the seam must be composed exactly ONCE: {calls}"
    args, kwargs = calls[0]
    passed = list(args[1:]) + list(kwargs.values())
    assert 5 in passed, f"limit=5 never reached the seam: args={args} kwargs={kwargs}"


@pytest.mark.parametrize("state,result", SEAM_STATES, ids=[s for s, _ in SEAM_STATES])
def test_b6_the_seam_is_composed_exactly_once_per_call(
        monkeypatch, state, result) -> None:
    calls: list = []
    _seam(monkeypatch, result, calls)
    _line(_cfg())
    assert len(calls) == 1, f"state {state} composed the seam {len(calls)} time(s)"
    assert calls[0][0][:1] != (), "the config must be the seam's first argument"


# ========================================================================== #
# Behavior 7 -- COUNTS ONLY, never a stage label
# ========================================================================== #
HOSTILE_LABELS = (
    "pm_scout_a",
    "ACTION: PUSHED deadbeef",
    "PRESHIP: OK",
    "products/_platform/state/iter-336",
    "RESULT: PASS",
)


def test_b7_no_stage_label_ever_reaches_the_line(monkeypatch) -> None:
    """doctor's lines are quoted VERBATIM into PM specs, so this text ships."""
    out = _body(monkeypatch, _Dig(9, [_Row("auth", 2, HOSTILE_LABELS)]))
    for label in HOSTILE_LABELS:
        assert label not in out, f"stage label {label!r} leaked into the line: {out}"
    for sentinel in ("ACTION:", "PRESHIP:", "RESULT:"):
        assert sentinel not in out, f"sentinel {sentinel!r} leaked: {out}"
    assert "5 distinct stage(s)" in out, \
        f"the COUNT must still be reported, only the labels withheld: {out}"


def test_b7_hostile_labels_still_yield_exactly_one_line(monkeypatch) -> None:
    out = _body(monkeypatch, _Dig(9, [_Row("auth", 2, ("a\nb", "c\nd"))]))
    assert "\n" not in out, f"a label carrying a newline must not split the line: {out}"


# ========================================================================== #
# Behavior 8 -- doctor integration, and the exit code it may never touch
# ========================================================================== #
@pytest.mark.parametrize("state,result", SEAM_STATES, ids=[s for s, _ in SEAM_STATES])
def test_b8_doctor_prints_the_auth_loss_line_exactly_once(
        monkeypatch, tmp_path, state, result) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _seam(monkeypatch, result)
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    hits = _lines_with(out, _prefix())
    assert len(hits) == 1, f"state {state}: expected 1 line, got {hits}"


def test_b8_the_auth_loss_line_is_last_of_the_six(monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _seam(monkeypatch, _Dig(9, [_Row("auth", 2, ("a",))]))
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    mine = _first_index(out, _prefix())
    assert mine >= 0, out
    for name in OLDER_PREFIX_NAMES:
        older = _first_index(out, getattr(foundry, name))
        assert older >= 0, f"{name} vanished from doctor output:\n{out}"
        assert older < mine, f"{name} must come BEFORE the newest line:\n{out}"


@pytest.mark.parametrize("name", OLDER_PREFIX_NAMES)
def test_b8_each_older_drift_prefix_still_appears_exactly_once(
        monkeypatch, tmp_path, name) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _seam(monkeypatch, _Dig(9, [_Row("auth", 2, ("a",))]))
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    assert len(_lines_with(out, getattr(foundry, name))) == 1, out


@pytest.mark.parametrize("state,result", SEAM_STATES, ids=[s for s, _ in SEAM_STATES])
def test_b8_all_checks_passing_exits_zero_in_every_state(
        monkeypatch, tmp_path, state, result) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _seam(monkeypatch, result)
    rc, out = _doctor_out(_doctor_cfg(tmp_path))
    assert rc == 0, f"state {state} moved the exit code:\n{out}"


@pytest.mark.parametrize("state,result", SEAM_STATES, ids=[s for s, _ in SEAM_STATES])
def test_b8_one_failing_check_exits_one_in_every_state(
        monkeypatch, tmp_path, state, result) -> None:
    _stub_checks(monkeypatch, fail="uv")
    _patch_older_lines(monkeypatch)
    _seam(monkeypatch, result)
    rc, _out = _doctor_out(_doctor_cfg(tmp_path))
    assert rc == 1, f"state {state} moved the exit code"


@pytest.mark.parametrize("state,result", SEAM_STATES, ids=[s for s, _ in SEAM_STATES])
def test_b8_the_summary_still_reads_out_of_4(monkeypatch, tmp_path, state, result) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _seam(monkeypatch, result)
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    assert re.search(r"\b4/4 checks ok\b", out), \
        f"state {state}: a drift line became a fifth CHECK:\n{out}"


def test_b8_run_doctor_still_returns_exactly_four_checks(monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    checks = foundry.run_doctor(_doctor_cfg(tmp_path))
    assert len(list(checks)) == 4, f"run_doctor is pinned at four Checks: {checks}"


@pytest.mark.parametrize("symbol", NEW_SYMBOLS)
def test_b8_run_doctor_source_names_no_new_symbol(symbol) -> None:
    """Machine scan: the drift line lives in the CLI, never among the gating checks."""
    src = inspect.getsource(foundry.run_doctor)
    assert symbol not in src, f"{symbol} reached run_doctor, which gates the exit code"


def test_b8_doctor_reads_the_window_global_at_call_time(monkeypatch, tmp_path) -> None:
    """A `monkeypatch.setattr(foundry, WINDOW, ...)` must re-window the printed line."""
    calls: list = []
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _seam(monkeypatch, _Dig(9, [_Row("auth", 2, ("a",))]), calls)
    monkeypatch.setattr(foundry, WINDOW_NAME, 7)
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    assert "7 most-recent iteration(s)" in out, \
        f"{WINDOW_NAME} was captured at def time, so the window cannot move:\n{out}"
    assert len(calls) == 1 and 7 in list(calls[0][0][1:]) + list(calls[0][1].values()), \
        f"the window never reached the seam: {calls}"


# ========================================================================== #
# Behavior 9 -- REPORT-ONLY and RESUME-SAFE (the spec's Out of Scope)
# ========================================================================== #
@pytest.mark.parametrize("symbol", NEW_SYMBOLS)
def test_b9_the_dispatcher_text_names_no_new_symbol(symbol) -> None:
    """A loop in flight must resume byte-identically, so the control path cannot move."""
    assert symbol not in DISPATCHER.read_text(encoding="utf-8"), \
        f"{symbol} reached the dispatcher control path"


@pytest.mark.parametrize("fn_name", ["run_iteration", "run_stage", "build_prompt"])
@pytest.mark.parametrize("symbol", NEW_SYMBOLS)
def test_b9_the_control_path_functions_name_no_new_symbol(fn_name, symbol) -> None:
    src = inspect.getsource(getattr(foundry, fn_name))
    assert symbol not in src, f"{symbol} reached {fn_name}, which the spec puts out of scope"


def test_b9_the_line_has_exactly_one_call_site() -> None:
    """Dormant-except-for-one-reader: the CLI is the only caller."""
    src = pathlib.Path(inspect.getfile(foundry)).read_text(encoding="utf-8")
    calls = len(re.findall(rf"(?<!def ){LINE_FN}\(", src))
    assert calls == 1, f"{LINE_FN} has {calls} call sites in the module, expected 1"


def test_b9_the_dispatcher_still_imports() -> None:
    assert dispatcher is not None and hasattr(dispatcher, "__file__")


# ========================================================================== #
# Behavior 10 -- writes nothing, and the END-TO-END count through the REAL seam
# ========================================================================== #
def _tree(root: pathlib.Path):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _fabricate_state(tmp_path: pathlib.Path):
    """Build a state dir the REAL `gather_losses` walks: 3 attempts, 1 lost to auth."""
    cfg = _cfg(work_root=str(tmp_path))
    it = pathlib.Path(cfg.state) / "iter-300"
    it.mkdir(parents=True, exist_ok=True)
    # LOST to expired credentials: an auth marker, and NO output file.
    (it / "pm.attempt1.log").write_text("... auth failed ...\n", encoding="utf-8")
    # PRODUCED: its output file exists, so it is not lost at all.
    (it / "engineer.attempt1.log").write_text("all good\n", encoding="utf-8")
    (it / "engineer.md").write_text("work\n", encoding="utf-8")
    # LOST to another kind: must NOT be counted by this line.
    (it / "reviewer.attempt1.log").write_text("connection stalled\n", encoding="utf-8")
    return cfg


def test_b10_end_to_end_through_the_real_seam_reports_the_auth_loss_only(
        tmp_path) -> None:
    cfg = _fabricate_state(tmp_path)
    out = _line(cfg)
    assert out.startswith(_prefix()), out
    assert getattr(foundry, WARN_NAME) in out, out
    assert "1/3" in out, \
        f"one of three scanned attempts was lost to expired credentials: {out}"
    assert "1 distinct stage(s)" in out, out
    for label in ("pm.attempt1", "reviewer", "engineer"):
        assert label not in out, f"a stage/file label leaked: {out}"


def test_b10_end_to_end_agrees_with_the_shipped_classification(tmp_path) -> None:
    """"Derived from the already-shipped classification" -- so the two must agree."""
    cfg = _fabricate_state(tmp_path)
    digest = foundry.gather_losses(cfg)
    auth = [r for r in digest.rows if r.kind == getattr(foundry, KIND_NAME)]
    assert auth and auth[0].lost == 1, [(r.kind, r.lost) for r in digest.rows]
    v = _verdict(digest)
    assert (v.attempts, v.lost) == (digest.attempts, auth[0].lost), v
    assert f"{v.lost}/{v.attempts}" in _line(cfg), \
        "the line must carry the digest's own numbers, not numbers of its own"


def test_b10_the_line_writes_nothing_to_disk(tmp_path) -> None:
    cfg = _fabricate_state(tmp_path)
    before = _tree(tmp_path)
    _line(cfg)
    _line(cfg, limit=5)
    assert _tree(tmp_path) == before, \
        "a report-only diagnostic must not write a flag file or any other artifact"


def test_b10_doctor_writes_nothing_to_disk(monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    cfg = _fabricate_state(tmp_path)
    monkeypatch.setattr(cfg, "roadmap", str(tmp_path / "none.md"), raising=False)
    before = _tree(tmp_path)
    _doctor_out(cfg)
    assert _tree(tmp_path) == before, "doctor must stay a read-only preflight"


# ========================================================================== #
# Behavior 11 -- the records, decidable from git-TRACKED text alone
# ========================================================================== #
def test_b11_readme_announces_six_drift_lines() -> None:
    text = " ".join(README.read_text(encoding="utf-8").split())
    assert "PLUS SIX drift lines" in text, \
        "README `# 0.` must advance its count word to SIX"
    assert "PLUS FIVE drift lines" not in text, "the retired count word must be gone"


def test_b11_readme_names_this_line_and_its_remedy() -> None:
    text = " ".join(README.read_text(encoding="utf-8").split())
    assert "auth-loss" in text, "README must name the new grep anchor"
    assert re.search(r"re-authenticat", text, re.I), \
        "README must name the remedy the line exists to surface"


def test_b11_the_roadmap_records_land_in_the_same_diff_as_the_code() -> None:
    idx = ROADMAP.read_text(encoding="utf-8")
    arc = ARCHIVE.read_text(encoding="utf-8")
    assert foundry.roadmap_ledger_gaps(idx, arc, (THIS_ITER,)) == [], \
        f"iteration {THIS_ITER} owes a ledger row and an archive bullet"
    rows = [ln for ln in idx.splitlines() if ln.startswith(f"- iter {THIS_ITER} ")]
    assert len(rows) == 1, f"exactly one ledger row expected, got {rows}"
    assert len(rows[0]) <= 120, f"ledger row is {len(rows[0])} chars, cap is 120"
    bullets = [ln for ln in arc.splitlines()
               if ln.startswith(f"- **iter {THIS_ITER} ")]
    assert len(bullets) == 1, f"exactly one archive bullet expected, got {len(bullets)}"


def test_b11_no_older_ledger_row_was_evicted() -> None:
    """A +1/-1 row edit is the failure mode iteration 236's archive bullet exists for."""
    idx = ROADMAP.read_text(encoding="utf-8")
    arc = ARCHIVE.read_text(encoding="utf-8")
    for older in (335, 334, 236, 195):
        assert foundry.roadmap_ledger_gaps(idx, arc, (older,)) == [], \
            f"iteration {older}'s record was evicted by this iteration's row edit"


def test_b11_this_module_is_on_the_iter204_allow_list() -> None:
    """The b15 brake reds on any unlisted tests/ path the moment the gate stages."""
    text = ALLOW_LIST_MODULE.read_text(encoding="utf-8")
    mine = f"tests/test_iter{THIS_ITER}_behavior.py"
    assert mine in text, \
        f"{mine} must be allow-listed or the gate's `git add -A` reds iter 204's b15"


# ========================================================================== #
# Behavior 12 -- DISCRIMINATION: every guard above that asserts only its GOOD
# arm on a REAL artifact is re-proved to FIRE on a bad one.  A census that
# returns "no findings" on the shipped tree is indistinguishable from a census
# that returns "no findings" unconditionally, so each such claim below is
# backed by an in-memory mutation of the very artifact it grades.
# ========================================================================== #
def _forbid_the_filesystem(monkeypatch):
    """Ban the FILESYSTEM as well: "pure" is not proved by banning subprocess alone."""

    def boom(*a, **k):
        raise AssertionError("the pure verdict reached the filesystem")

    monkeypatch.setattr(builtins, "open", boom)
    monkeypatch.setattr(pathlib.Path, "open", boom)
    monkeypatch.setattr(pathlib.Path, "read_text", boom)
    monkeypatch.setattr(pathlib.Path, "read_bytes", boom)
    monkeypatch.setattr(pathlib.Path, "exists", boom)
    monkeypatch.setattr(pathlib.Path, "iterdir", boom)


def test_b12_verdict_never_reaches_the_filesystem_either(monkeypatch) -> None:
    _forbid_outside_world(monkeypatch)
    _forbid_the_filesystem(monkeypatch)
    _seam(monkeypatch, AssertionError("the pure verdict called the I/O seam"))
    v = _verdict(_Dig(9, [_Row("auth", 2, ("a", "b"))]))
    assert (v.attempts, v.lost, v.stage_count) == (9, 2, 2)


@pytest.mark.parametrize("digest", JUNK_DIGESTS, ids=lambda d: type(d).__name__)
def test_b12_verdict_is_total_with_the_filesystem_banned(monkeypatch, digest) -> None:
    _forbid_outside_world(monkeypatch)
    _forbid_the_filesystem(monkeypatch)
    _seam(monkeypatch, AssertionError("the pure verdict called the I/O seam"))
    assert isinstance(_verdict(digest), foundry.AuthLossVerdict)


# The share is the ONE number an operator acts on, so pin its arithmetic -- including a
# 1-in-1000 case, which is what rules out a silent tolerance threshold below which real
# lost work would be reported as OK.
SHARES = ((1, 1000, "0.1%"), (1, 3, "33.3%"), (1, 1, "100.0%"),
          (2, 9, "22.2%"), (36, 119, "30.3%"))


@pytest.mark.parametrize("lost,attempts,share", SHARES,
                         ids=[f"{l}-of-{a}" for l, a, _s in SHARES])
def test_b12_the_share_is_the_ratio_at_one_decimal_and_one_loss_always_warns(
        monkeypatch, lost, attempts, share) -> None:
    out = _body(monkeypatch, _Dig(attempts, [_Row("auth", lost, ("s",))]))
    assert f"{lost}/{attempts}" in out, out
    assert share in out, f"expected the share {share} in: {out}"
    assert getattr(foundry, WARN_NAME) in out, \
        f"{lost} lost attempt(s) must WARN -- no silent tolerance threshold: {out}"


@pytest.mark.parametrize("name", (PREFIX_NAME,) + OLDER_PREFIX_NAMES)
def test_b12_every_drift_anchor_is_grep_unique_in_the_whole_stdout(
        monkeypatch, tmp_path, name) -> None:
    """An operator greps the anchor, so it must match ONE line, not a body mention."""
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _seam(monkeypatch, _Dig(9, [_Row("auth", 2, ("a", "b"))]))
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    anchor = getattr(foundry, name).rstrip(":")
    assert out.count(anchor) == 1, \
        f"{name} anchor {anchor!r} matched {out.count(anchor)} time(s):\n{out}"


def test_b12_the_record_carries_counts_only_and_no_stage_label() -> None:
    """Pinned at the RECORD, so a later formatter change cannot leak a label."""
    names = tuple(f.name for f in dataclasses.fields(foundry.AuthLossVerdict))
    assert names == ("attempts", "lost", "stage_count"), names
    text = repr(_verdict(_Dig(9, [_Row("auth", 2, HOSTILE_LABELS)])))
    for label in HOSTILE_LABELS:
        assert label not in text, f"the record itself carries {label!r}: {text}"


def test_b12_the_line_is_deterministic_across_repeat_calls(tmp_path) -> None:
    """No clock and no set-ordering may reach the text: two calls must agree."""
    cfg = _fabricate_state(tmp_path)
    assert _line(cfg) == _line(cfg)
    assert _line(cfg, limit=5) == _line(cfg, limit=5)


def test_b12_the_gating_source_scan_reads_real_text_and_fires_where_it_should() -> None:
    """`symbol not in src` passes trivially if `src` is empty or the wrong text."""
    gated = inspect.getsource(foundry.run_doctor)
    assert len(gated) > 200 and "Check" in gated, \
        "the run_doctor negative scan is not reading the gating function at all"
    printer = inspect.getsource(foundry.run_doctor_cli)
    assert LINE_FN in printer or PREFIX_NAME in printer, \
        "the same scan finds no new symbol in the PRINTER either, so it proves nothing"


def test_b12_the_dispatcher_negative_scan_reads_real_text() -> None:
    text = DISPATCHER.read_text(encoding="utf-8")
    assert len(text) > 1000 and "def " in text, \
        "the dispatcher negative scan is reading nothing, so it proves nothing"


def _drop_lines_starting(text: str, prefix: str) -> str:
    lines = text.splitlines()
    kept = [ln for ln in lines if not ln.startswith(prefix)]
    assert len(kept) < len(lines), f"nothing started with {prefix!r}, mutation is a no-op"
    return "\n".join(kept) + "\n"


def _mutated_records():
    """The real roadmap texts, plus each with THIS iteration's record deleted."""
    idx = ROADMAP.read_text(encoding="utf-8")
    arc = ARCHIVE.read_text(encoding="utf-8")
    return (idx, arc,
            _drop_lines_starting(idx, f"- iter {THIS_ITER} "),
            _drop_lines_starting(arc, f"- **iter {THIS_ITER} "))


def test_b12_the_ledger_oracle_fires_only_when_BOTH_records_are_gone() -> None:
    """Measured contract, not the intuitive one: the brake's own docstring says a
    record in EITHER file counts, so deleting ONE leaves it silent BY DESIGN.  That
    is exactly why behavior 11's `== []` cannot be the assertion that pins both
    files -- the per-file counts below are.  Both arms are exercised here so the
    silence is a measured property and not an untested assumption."""
    idx, arc, no_row, no_bullet = _mutated_records()
    assert foundry.roadmap_ledger_gaps(no_row, arc, (THIS_ITER,)) == [], \
        "a record in EITHER file counts, so a missing index row alone is not a gap"
    assert foundry.roadmap_ledger_gaps(idx, no_bullet, (THIS_ITER,)) == [], \
        "a record in EITHER file counts, so a missing archive bullet alone is no gap"
    assert foundry.roadmap_ledger_gaps(no_row, no_bullet, (THIS_ITER,)) == [THIS_ITER], \
        "with NEITHER record present the lost-record brake must fire"
    assert foundry.roadmap_ledger_gaps("", "", (THIS_ITER,)) == [THIS_ITER], \
        "empty roadmap texts must fire, or the oracle is vacuous"


def _record_counts(index_text: str, archive_text: str) -> tuple:
    """The per-file predicate behavior 11 actually leans on, as a FUNCTION."""
    rows = [ln for ln in index_text.splitlines()
            if ln.startswith(f"- iter {THIS_ITER} ")]
    bullets = [ln for ln in archive_text.splitlines()
               if ln.startswith(f"- **iter {THIS_ITER} ")]
    return (len(rows), len(bullets))


def test_b12_the_per_file_record_counts_fire_on_either_deletion() -> None:
    idx, arc, no_row, no_bullet = _mutated_records()
    assert _record_counts(idx, arc) == (1, 1), _record_counts(idx, arc)
    assert _record_counts(no_row, arc) == (0, 1), \
        "the row count must drop when the ledger row is deleted"
    assert _record_counts(idx, no_bullet) == (1, 0), \
        "the bullet count must drop when the archive bullet is deleted"


def _readme_count_word_gaps(text: str) -> tuple:
    """The README count-word check as a FUNCTION, so it can be proved on both arms."""
    flat = " ".join(text.split())
    gaps = []
    if "PLUS SIX drift lines" not in flat:
        gaps.append("README `# 0.` does not announce SIX drift lines")
    if "PLUS FIVE drift lines" in flat:
        gaps.append("README still claims FIVE drift lines")
    return tuple(gaps)


def test_b12_the_readme_count_word_predicate_fires_on_the_retired_word() -> None:
    real = README.read_text(encoding="utf-8")
    assert _readme_count_word_gaps(real) == (), _readme_count_word_gaps(real)
    reverted = real.replace("PLUS SIX drift lines", "PLUS FIVE drift lines")
    assert reverted != real, "the mutation was a no-op, so the good arm proves nothing"
    assert len(_readme_count_word_gaps(reverted)) == 2, _readme_count_word_gaps(reverted)
