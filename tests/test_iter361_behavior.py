"""Iteration 361 -- BLACK-BOX behavior tests.

doctor's `auth-loss:` WARN learns TENSE.  The digest already answers "how much did
expired credentials cost"; a second, read-only RECENCY reader answers "is that still
true", so a window whose newest loss is OLDER than its newest scanned iteration names
the iteration it cleared at instead of telling a human to re-authenticate again.

ISOLATION: written from the PM stage's artifacts only (`pm.md` plus the same stage's
`archive_bullet.txt`, since `pm.md`'s `## Expected Behaviors` section is the literal
placeholder `(refining -- see the final version below)` -- that stage was cap-killed).
No implementation source, no `git diff`, no engineer/reviewer notes were read.  Every
assertion drives the public interface and grades observable output.

Expected Behaviors, numbered as the report numbers them:
   1. The four new symbols exist and are well-formed: one `AUTH_LOSS_HEALED` token,
      one frozen `AuthRecency` record, one pure total `auth_recency_verdict`, one
      read-only `gather_auth_recency(cfg, limit=None)` seam.
   2. `AuthRecency` is frozen, value-equal and hashable, and its three properties are
      an EXHAUSTIVE, MUTUALLY EXCLUSIVE truth table over (newest_scanned, newest_loss).
   3. `auth_recency_verdict` is PURE (no filesystem, no subprocess, no socket) and
      TOTAL: real 5-sequences, attribute-carrying objects, junk and non-iterables all
      yield an assertable record instead of a traceback.
   4. HEALED arm: when the newest loss is older than the newest scanned iteration the
      WARN carries `AUTH_LOSS_HEALED`, NAMES BOTH iteration numbers, and drops the
      present-tense remedy.
   5. ACTIVE arm is BYTE-IDENTICAL to the shipped sentence, proved two ways: against
      the recency reader forced to "no data" (dormancy) and against HEAD's own build.
   6. FAIL-SAFE DIRECTION: a raise, a `None`, an empty window, and a digest that says
      LOST while the reader finds no auth record ALL degrade to ACTIVE -- never HEALED.
   7. ZERO NEW I/O in the undecided arms: the recency seam is composed exactly once in
      the WARN arm and NOT AT ALL in the OK and UNKNOWN arms.
   8. Windowing: the same `limit` reaches BOTH readers, and both are read by bare
      module name at call time.
   9. END-TO-END through the REAL seams over a fabricated state dir: a two-iteration
      tree renders HEALED naming both numbers, a one-iteration tree renders ACTIVE.
  10. The doctor CLI is untouched: six drift lines each exactly once, `out of 4`, exit
      codes over {all-pass, one-failing}, `run_doctor` still four `Check`s.
  11. REPORT-ONLY and RESUME-SAFE: `dispatcher.py` and the sources of `run_iteration`,
      `run_stage`, `build_prompt` and `run_continuous` name NONE of the four new
      symbols; `gather_auth_recency` has exactly ONE call site; the dispatcher imports.
  12. Records, decidable from git-TRACKED text alone (OPERATOR 2026-08-11): the ledger
      row and archive bullet land in the SAME diff as the code, the three shed rows
      (242/243/244) kept their archive bullets, no older record was evicted, and the
      README count word stays SIX because no SEVENTH drift line was added.
  13. Report-only: neither the line nor the doctor writes anything to disk.
  14. DISCRIMINATION: each guard above that asserts only its GOOD arm is re-proved to
      FIRE on a mutated input, so a vacuous check is distinguishable from a real one.
"""

from __future__ import annotations

import contextlib
import dataclasses
import importlib.util
import inspect
import io
import itertools
import os
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

THIS_ITER = 361

README = _ROOT / "README.md"
ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
DISPATCHER = _ROOT / "dispatcher.py"

# A RELATIVE literal: an absolute machine path in a shipped test is a leak-guard
# finding (OPERATOR 2026-08-30, which reverted iteration 205 over exactly this shape).
REL_REPO = "products/_platform/state/iter-361"

# Names are FIXED by the spec's own vocabulary, so they are reached by STRING here: a
# rename must fail loudly rather than silently stop testing anything.
HEALED_NAME = "AUTH_LOSS_HEALED"
RECORD_NAME = "AuthRecency"
VERDICT_FN = "auth_recency_verdict"
SEAM = "gather_auth_recency"
NEW_SYMBOLS = (HEALED_NAME, RECORD_NAME, VERDICT_FN, SEAM)

# Iteration 336's shipped names this iteration composes but must not edit.
LINE_FN = "auth_loss_line"
LOSS_SEAM = "gather_losses"
WARN_NAME = "AUTH_LOSS_WARN"
PREFIX_NAME = "AUTH_LOSS_PREFIX"
KIND_NAME = "AUTH_LOSS_KIND"
WINDOW_NAME = "AUTH_LOSS_RECENT_ITERATIONS"

REMEDY = "a HUMAN must re-authenticate"


# ========================================================================== #
# Stubs -- duck-typed, so no test needs the real dataclasses
# ========================================================================== #
class _Chk:
    def __init__(self, name, ok, detail="detail-text"):
        self.name = name
        self.ok = ok
        self.detail = detail


class _G:
    def __init__(self, stage, median_s, timeouts=0, count=1):
        self.stage = stage
        self.median_s = median_s
        self.timeouts = timeouts
        self.count = count


class _S:
    def __init__(self, *groups):
        self.groups = tuple(groups)


class _Row:
    def __init__(self, kind, lost, stages=()):
        self.kind = kind
        self.lost = lost
        self.stages = stages


class _Dig:
    def __init__(self, attempts, rows=()):
        self.attempts = attempts
        self.rows = tuple(rows)


class _Rec:
    """A loss RECORD carrying the five attribute names, not a 5-sequence."""

    def __init__(self, stage, iteration, attempt, produced, kind):
        self.stage = stage
        self.iteration = iteration
        self.attempt = attempt
        self.produced = produced
        self.kind = kind


def _cfg(**over):
    kw = dict(name="demo", repo=REL_REPO, allowed_push_repo="demo")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _healed() -> str:
    return getattr(foundry, HEALED_NAME)


def _prefix() -> str:
    return getattr(foundry, PREFIX_NAME)


def _rec(scanned, loss):
    return getattr(foundry, RECORD_NAME)(newest_scanned=scanned, newest_loss=loss)


def _line(cfg, **kw) -> str:
    return getattr(foundry, LINE_FN)(cfg, **kw)


def _verdict(records):
    return getattr(foundry, VERDICT_FN)(records)


def _script(monkeypatch, name, result, calls=None):
    """Script a seam by BARE module name; record every call.

    `result` is either the value to return or an exception INSTANCE to raise.
    """

    def fake(*a, **kw):
        if calls is not None:
            calls.append((a, dict(kw)))
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(foundry, name, fake)
    return calls


WARN_DIGEST = _Dig(9, [_Row("auth", 7, ("pm",))])
OK_DIGEST = _Dig(11, [_Row("timeout", 4, ("x",))])
EMPTY_DIGEST = _Dig(0, [])

# Every shape a real recency reader can hand back, plus the shapes a MIS-DERIVED one
# can: the fail-safe claim has to survive all of them.
UNDECIDED_RECENCIES = (
    ("raiser", RuntimeError("recency reader exploded")),
    ("none", None),
    ("no-data", "SENTINEL-NO-DATA"),           # replaced with a real record below
    ("loss-unknown", "SENTINEL-LOSS-UNKNOWN"),  # scanned but no auth record found
)


def _undecided(tag):
    if tag == "no-data":
        return _rec(None, None)
    if tag == "loss-unknown":
        return _rec(361, None)
    return None


# ========================================================================== #
# Behavior 1 -- the four new symbols exist and are well-formed
# ========================================================================== #
@pytest.mark.parametrize("name", NEW_SYMBOLS)
def test_b1_every_new_symbol_exists(name) -> None:
    assert hasattr(foundry, name), f"foundry has no {name}"


def test_b1_the_healed_token_is_a_nonempty_string_distinct_from_warn() -> None:
    tok = _healed()
    assert isinstance(tok, str) and tok.strip() == tok and tok, repr(tok)
    assert tok != getattr(foundry, WARN_NAME), \
        "the healed token must be distinguishable from the WARN token"
    assert REMEDY not in tok, "the healed token must not carry the present-tense remedy"


def test_b1_the_seam_takes_a_config_and_an_optional_limit() -> None:
    sig = inspect.signature(getattr(foundry, SEAM))
    names = list(sig.parameters)
    assert names[:2] == ["cfg", "limit"], names
    assert sig.parameters["limit"].default is None, sig.parameters["limit"].default


def test_b1_the_record_carries_exactly_the_two_iteration_numbers() -> None:
    rec_cls = getattr(foundry, RECORD_NAME)
    assert dataclasses.is_dataclass(rec_cls)
    assert [f.name for f in dataclasses.fields(rec_cls)] == \
        ["newest_scanned", "newest_loss"], [f.name for f in dataclasses.fields(rec_cls)]


@pytest.mark.parametrize("prop", ["has_data", "active", "healed"])
def test_b1_the_three_properties_are_properties_not_fields(prop) -> None:
    rec_cls = getattr(foundry, RECORD_NAME)
    assert isinstance(getattr(rec_cls, prop, None), property), \
        f"{prop} must be a derived property, so it can never disagree with the fields"


# ========================================================================== #
# Behavior 2 -- the record: frozen, value-equal, and an exhaustive truth table
# ========================================================================== #
def test_b2_the_record_is_frozen_value_equal_and_hashable() -> None:
    a, b = _rec(301, 300), _rec(301, 300)
    assert a == b and hash(a) == hash(b) and a is not b
    assert a != _rec(301, 301)
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.newest_loss = 999


_TABLE_VALUES = (None, 0, 1, 300, 301)


@pytest.mark.parametrize("scanned,loss", list(itertools.product(_TABLE_VALUES, repeat=2)))
def test_b2_the_truth_table_is_exhaustive_and_derived(scanned, loss) -> None:
    """Every one of the 25 combinations, graded against the documented meaning."""
    r = _rec(scanned, loss)
    assert r.has_data is (scanned is not None), (scanned, loss, r.has_data)
    expect_active = scanned is not None and loss is not None and loss >= scanned
    expect_healed = scanned is not None and loss is not None and loss < scanned
    assert r.active is expect_active, (scanned, loss, r.active)
    assert r.healed is expect_healed, (scanned, loss, r.healed)


@pytest.mark.parametrize("scanned,loss", list(itertools.product(_TABLE_VALUES, repeat=2)))
def test_b2_active_and_healed_are_mutually_exclusive(scanned, loss) -> None:
    r = _rec(scanned, loss)
    assert not (r.active and r.healed), (scanned, loss)
    if r.active or r.healed:
        assert r.has_data, "no window can be decided without something scanned"


def test_b2_an_unscanned_window_is_never_healed() -> None:
    """The banned direction: nothing scanned may never read as 'already cleared'."""
    for loss in _TABLE_VALUES:
        assert _rec(None, loss).healed is False, loss


# ========================================================================== #
# Behavior 3 -- the pure total reduction
# ========================================================================== #
def _forbid_the_outside_world(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a pure reduction reached the outside world")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)
    monkeypatch.setattr(socket, "socket", boom)


def _forbid_the_filesystem(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a pure reduction reached the filesystem")

    monkeypatch.setattr(io, "open", boom, raising=False)
    monkeypatch.setattr(os, "listdir", boom)
    monkeypatch.setattr(os, "scandir", boom)
    monkeypatch.setattr(pathlib.Path, "read_text", boom)
    monkeypatch.setattr(pathlib.Path, "glob", boom)


JUNK_RECORDS = (
    None,
    17,
    "a string",
    (),
    [None, 5, "x"],
    [("pm",)],
    [("pm", "not-an-int", 1, False, "auth")],
    [("pm", None, 1, False, "auth")],
    [_Rec("pm", None, 1, False, "auth")],
    object(),
)


@pytest.mark.parametrize("records", JUNK_RECORDS)
def test_b3_the_reduction_is_total_over_junk(monkeypatch, records) -> None:
    _forbid_the_outside_world(monkeypatch)
    _forbid_the_filesystem(monkeypatch)
    out = _verdict(records)
    assert isinstance(out, getattr(foundry, RECORD_NAME)), (records, out)
    assert out.healed is False, \
        f"an undecidable input must never read as already-cleared: {records} -> {out}"


def test_b3_the_reduction_reads_real_5_sequences(monkeypatch) -> None:
    _forbid_the_outside_world(monkeypatch)
    _forbid_the_filesystem(monkeypatch)
    recs = [("pm", 300, 1, False, "auth"), ("pm", 301, 1, True, None)]
    out = _verdict(recs)
    assert (out.newest_scanned, out.newest_loss) == (301, 300), out
    assert out.healed is True and out.active is False, out


def test_b3_the_reduction_reads_attribute_carrying_records(monkeypatch) -> None:
    _forbid_the_outside_world(monkeypatch)
    _forbid_the_filesystem(monkeypatch)
    out = _verdict([_Rec("pm", 300, 1, False, "auth"),
                    _Rec("pm", 302, 1, True, None)])
    assert (out.newest_scanned, out.newest_loss) == (302, 300), out


def test_b3_the_reduction_takes_the_NEWEST_of_each_regardless_of_order(monkeypatch) -> None:
    _forbid_the_outside_world(monkeypatch)
    recs = [("pm", 305, 1, True, None), ("pm", 299, 1, False, "auth"),
            ("pm", 301, 1, False, "auth"), ("pm", 300, 1, True, None)]
    out = _verdict(recs)
    assert (out.newest_scanned, out.newest_loss) == (305, 301), out
    assert _verdict(list(reversed(recs))) == out, "the reduction must be order-free"


def test_b3_a_non_auth_loss_never_counts_as_an_auth_loss(monkeypatch) -> None:
    out = _verdict([("pm", 300, 1, False, "timeout"), ("pm", 301, 1, False, "cap")])
    assert out.newest_scanned == 301, out
    assert out.newest_loss is None, \
        "only credential losses may set the newest-loss iteration"
    assert out.healed is False and out.active is False, out


# ========================================================================== #
# Behavior 4 -- the HEALED arm
# ========================================================================== #
def _warn_line(monkeypatch, recency, loss_calls=None, rec_calls=None, **kw):
    _script(monkeypatch, LOSS_SEAM, WARN_DIGEST, loss_calls)
    _script(monkeypatch, SEAM, recency, rec_calls)
    return _line(_cfg(), **kw)


def test_b4_a_healed_window_names_the_token_and_both_numbers(monkeypatch) -> None:
    out = _warn_line(monkeypatch, _rec(361, 359))
    assert out.startswith(_prefix()), out
    assert getattr(foundry, WARN_NAME) in out, out
    assert _healed() in out, f"the healed clause is missing: {out}"
    assert "359" in out and "361" in out, \
        f"a healed clause must name the loss iteration AND the clean frontier: {out}"


def test_b4_a_healed_window_drops_the_present_tense_remedy(monkeypatch) -> None:
    out = _warn_line(monkeypatch, _rec(361, 359))
    assert REMEDY not in out, \
        f"the whole point of the iteration: no false present-tense remedy: {out}"


def test_b4_a_healed_window_still_reports_the_cost(monkeypatch) -> None:
    """HEALED changes the TENSE, not the accounting: the counts must survive."""
    out = _warn_line(monkeypatch, _rec(361, 359))
    assert "7/9" in out, f"the digest's own numbers must survive the new clause: {out}"
    assert "1 distinct stage(s)" in out, out


def test_b4_the_healed_line_is_exactly_one_line(monkeypatch) -> None:
    out = _warn_line(monkeypatch, _rec(361, 359))
    assert out and "\n" not in out.strip(), repr(out)


def test_b4_no_stage_label_leaks_into_the_healed_clause(monkeypatch) -> None:
    """`roles/pm.md` quotes doctor lines VERBATIM into specs, so counts only."""
    _script(monkeypatch, LOSS_SEAM, _Dig(9, [_Row("auth", 7, ("ACTION: PUSHED", "x/y"))]))
    _script(monkeypatch, SEAM, _rec(361, 359))
    out = _line(_cfg())
    for hostile in ("ACTION:", "x/y", "PRESHIP:"):
        assert hostile not in out, f"a hostile stage label leaked: {out}"


# ========================================================================== #
# Behavior 5 -- the ACTIVE arm is BYTE-IDENTICAL
# ========================================================================== #
def test_b5_an_active_window_keeps_the_remedy_and_gains_no_token(monkeypatch) -> None:
    out = _warn_line(monkeypatch, _rec(359, 359))
    assert REMEDY in out, f"a live credential wall must still say so: {out}"
    assert _healed() not in out, out


def test_b5_the_active_sentence_equals_the_dormant_rendering(monkeypatch) -> None:
    """Dormancy: with the reader undecided the line must be byte-identical to the
    live-but-active rendering, so the new clause is a pure ADDITION to one arm."""
    active = _warn_line(monkeypatch, _rec(359, 359))
    dormant = _warn_line(monkeypatch, _rec(None, None))
    assert active == dormant, f"active:\n{active}\ndormant:\n{dormant}"


def _head_build(tmp_path):
    """Import the build at HEAD~1 (the previous ship) as a separate module.

    Black-box: the older build is EXECUTED, never read.  This is the only oracle that
    can prove "byte-identical" about a sentence no shipped test pins as a literal.
    """
    src = subprocess.run(["git", "show", "HEAD:foundry.py"], cwd=str(_ROOT),
                         capture_output=True, text=True, check=True).stdout
    p = tmp_path / "foundry_head.py"
    p.write_text(src, encoding="utf-8")
    name = "foundry_head_361"
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    # `dataclasses` resolves string annotations through `sys.modules[cls.__module__]`,
    # so the older build must be REGISTERED before its class bodies execute.
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


def test_b5_the_active_sentence_is_byte_identical_to_the_shipped_build(
        monkeypatch, tmp_path) -> None:
    head = _head_build(tmp_path)
    monkeypatch.setattr(head, LOSS_SEAM, lambda *a, **k: WARN_DIGEST)
    before = getattr(head, LINE_FN)(
        head.ProductConfig(name="demo", repo=REL_REPO, allowed_push_repo="demo"))
    after = _warn_line(monkeypatch, _rec(359, 359))
    assert after == before, f"HEAD:\n{before}\nnow:\n{after}"
    assert REMEDY in before, "sanity: HEAD's WARN really did carry the remedy"


def test_b5_the_ok_and_unknown_bodies_are_byte_identical_to_the_shipped_build(
        monkeypatch, tmp_path) -> None:
    head = _head_build(tmp_path)
    for label, digest in (("ok", OK_DIGEST), ("empty", EMPTY_DIGEST),
                          ("unknown", RuntimeError("seam exploded"))):
        monkeypatch.setattr(
            head, LOSS_SEAM,
            (lambda *a, _d=digest, **k: (_ for _ in ()).throw(_d))
            if isinstance(digest, BaseException) else (lambda *a, _d=digest, **k: _d))
        before = getattr(head, LINE_FN)(
            head.ProductConfig(name="demo", repo=REL_REPO, allowed_push_repo="demo"))
        _script(monkeypatch, LOSS_SEAM, digest)
        _script(monkeypatch, SEAM, _rec(361, 359))
        after = _line(_cfg())
        assert after == before, f"[{label}] HEAD:\n{before}\nnow:\n{after}"


# ========================================================================== #
# Behavior 6 -- the FAIL-SAFE DIRECTION
# ========================================================================== #
@pytest.mark.parametrize("tag,payload", UNDECIDED_RECENCIES)
def test_b6_every_undecided_reader_degrades_to_active_never_healed(
        monkeypatch, tag, payload) -> None:
    recency = payload if isinstance(payload, BaseException) else _undecided(tag)
    out = _warn_line(monkeypatch, recency)
    assert _healed() not in out, \
        f"[{tag}] silently suppressing a real credential wall is the banned direction: {out}"
    assert REMEDY in out, f"[{tag}] the WARN must keep its remedy: {out}"
    assert getattr(foundry, WARN_NAME) in out, f"[{tag}] the WARN was lost: {out}"


def test_b6_a_digest_that_says_lost_while_the_reader_finds_no_loss_stays_active(
        monkeypatch) -> None:
    """The disagreement case the spec names explicitly."""
    out = _warn_line(monkeypatch, _rec(400, None))
    assert REMEDY in out and _healed() not in out, out


@pytest.mark.parametrize("tag,payload", UNDECIDED_RECENCIES)
def test_b6_the_line_never_raises_with_an_undecided_reader(monkeypatch, tag, payload) -> None:
    recency = payload if isinstance(payload, BaseException) else _undecided(tag)
    out = _warn_line(monkeypatch, recency)
    assert out.startswith(_prefix()) and "\n" not in out.strip(), (tag, repr(out))


def test_b6_the_line_is_deterministic_across_repeat_calls(monkeypatch) -> None:
    _script(monkeypatch, LOSS_SEAM, WARN_DIGEST)
    _script(monkeypatch, SEAM, _rec(361, 359))
    cfg = _cfg()
    assert _line(cfg) == _line(cfg) == _line(cfg)


# ========================================================================== #
# Behavior 7 -- ZERO NEW I/O in the undecided arms
# ========================================================================== #
@pytest.mark.parametrize("label,digest,expected", [
    ("warn", WARN_DIGEST, 1),
    ("ok", OK_DIGEST, 0),
    ("empty", EMPTY_DIGEST, 0),
    ("unknown-raiser", RuntimeError("seam exploded"), 0),
    ("unknown-none", None, 0),
    ("unknown-int", 17, 0),
])
def test_b7_the_recency_seam_is_composed_only_when_the_digest_warns(
        monkeypatch, label, digest, expected) -> None:
    _script(monkeypatch, LOSS_SEAM, digest)
    calls = _script(monkeypatch, SEAM, _rec(361, 359), calls=[])
    out = _line(_cfg())
    assert len(calls) == expected, \
        f"[{label}] recency seam composed {len(calls)}x, expected {expected}: {out}"


def test_b7_the_loss_seam_is_still_composed_exactly_once(monkeypatch) -> None:
    calls = _script(monkeypatch, LOSS_SEAM, WARN_DIGEST, calls=[])
    _script(monkeypatch, SEAM, _rec(361, 359))
    _line(_cfg())
    assert len(calls) == 1, f"iteration 336's own invariant moved: {calls}"


# ========================================================================== #
# Behavior 8 -- windowing
# ========================================================================== #
def test_b8_the_same_limit_reaches_both_readers(monkeypatch) -> None:
    loss_calls = _script(monkeypatch, LOSS_SEAM, WARN_DIGEST, calls=[])
    rec_calls = _script(monkeypatch, SEAM, _rec(361, 359), calls=[])
    _line(_cfg(), limit=7)

    def _seen(calls):
        (args, kwargs), = calls
        return list(args[1:]) + list(kwargs.values())

    assert 7 in _seen(loss_calls), loss_calls
    assert 7 in _seen(rec_calls), \
        f"the window must not differ between the two readers: {rec_calls}"


def test_b8_the_recency_seam_is_read_by_bare_name_at_call_time(monkeypatch) -> None:
    """A def-time capture would make the seam unpatchable and the arm untestable."""
    _script(monkeypatch, LOSS_SEAM, WARN_DIGEST)
    _script(monkeypatch, SEAM, _rec(361, 359))
    assert _healed() in _line(_cfg())
    _script(monkeypatch, SEAM, _rec(359, 359))
    assert _healed() not in _line(_cfg())


# ========================================================================== #
# Behavior 9 -- END-TO-END through the REAL seams
# ========================================================================== #
def _fabricate(tmp_path, spec):
    """Build a state dir the REAL readers walk. `spec` maps iteration -> kind."""
    cfg = _cfg(work_root=str(tmp_path))
    for it, kind in spec.items():
        d = pathlib.Path(cfg.state) / f"iter-{it}"
        d.mkdir(parents=True, exist_ok=True)
        if kind == "auth":
            (d / "pm.attempt1.log").write_text("... auth failed ...\n", encoding="utf-8")
        elif kind == "clean":
            (d / "pm.attempt1.log").write_text("all good\n", encoding="utf-8")
            (d / "pm.md").write_text("work\n", encoding="utf-8")
        elif kind == "other":
            (d / "pm.attempt1.log").write_text("connection stalled\n", encoding="utf-8")
    return cfg


def test_b9_end_to_end_a_healed_window_names_both_numbers(tmp_path) -> None:
    cfg = _fabricate(tmp_path, {300: "auth", 301: "clean"})
    out = _line(cfg)
    assert out.startswith(_prefix()), out
    assert getattr(foundry, WARN_NAME) in out and _healed() in out, out
    assert "1/2" in out, f"the digest's own numbers: {out}"
    assert "300" in out and "301" in out, out
    assert REMEDY not in out, out


def test_b9_end_to_end_a_still_active_window_keeps_the_remedy(tmp_path) -> None:
    cfg = _fabricate(tmp_path, {300: "auth"})
    out = _line(cfg)
    assert REMEDY in out and _healed() not in out, out


def test_b9_end_to_end_a_newer_loss_after_a_clean_iteration_is_active(tmp_path) -> None:
    cfg = _fabricate(tmp_path, {300: "clean", 301: "auth"})
    out = _line(cfg)
    assert REMEDY in out and _healed() not in out, out


def test_b9_end_to_end_a_newer_NON_auth_loss_still_heals(tmp_path) -> None:
    """A cap-kill after the credentials were fixed is not a credential wall."""
    cfg = _fabricate(tmp_path, {300: "auth", 301: "other"})
    out = _line(cfg)
    assert _healed() in out and REMEDY not in out, out
    assert "1/2" in out, out


def test_b9_the_two_readers_agree_on_the_same_corpus(tmp_path) -> None:
    """The shared-classifier claim: the annotation can never contradict the digest."""
    cfg = _fabricate(tmp_path, {300: "auth", 301: "clean", 302: "other"})
    digest = getattr(foundry, LOSS_SEAM)(cfg)
    rec = getattr(foundry, SEAM)(cfg)
    auth = [r for r in digest.rows if r.kind == getattr(foundry, KIND_NAME)]
    assert auth and auth[0].lost == 1, [(r.kind, r.lost) for r in digest.rows]
    assert (rec.newest_scanned, rec.newest_loss) == (302, 300), rec
    assert rec.healed is True, rec


def test_b9_the_gatherer_is_total_over_a_hostile_tree(tmp_path) -> None:
    cfg = _cfg(work_root=str(tmp_path))
    rec = getattr(foundry, SEAM)(cfg)
    assert rec == _rec(None, None), f"a missing state dir must be no-data: {rec}"
    bad = pathlib.Path(cfg.state) / "iter-not-a-number"
    bad.mkdir(parents=True)
    (bad / "pm.attempt1.log").write_text("auth failed\n", encoding="utf-8")
    rec = getattr(foundry, SEAM)(cfg)
    assert rec.healed is False, f"an unparseable iteration name must not heal: {rec}"


def test_b9_the_gatherer_windows_the_same_way_the_digest_does(tmp_path) -> None:
    cfg = _fabricate(tmp_path, {300: "auth", 301: "clean", 302: "clean"})
    assert getattr(foundry, SEAM)(cfg, limit=1) == _rec(302, None), "newest only"
    assert getattr(foundry, SEAM)(cfg, limit=3) == _rec(302, 300)
    assert getattr(foundry, SEAM)(cfg, None) == _rec(302, 300)


# ========================================================================== #
# Behavior 10 -- the doctor CLI is untouched
# ========================================================================== #
OLDER_PREFIX_NAMES = ("LIVE_LAG_PREFIX", "LEARNINGS_HEAD_PREFIX", "ROADMAP_INDEX_PREFIX",
                      "STAGE_BUDGET_PREFIX", "TEST_TOUCH_PREFIX")


def _stub_checks(monkeypatch, *, fail=None):
    for nm in ("power", "agent", "uv", "remote"):
        monkeypatch.setattr(foundry, f"check_{nm}",
                            lambda *a, _n=nm, **k: _Chk(_n, _n != fail))


def _patch_older_lines(monkeypatch):
    monkeypatch.setattr(foundry, "parse_brain_launch", lambda *a, **k: 1000.0)
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: ((1, 900.0),))
    monkeypatch.setattr(foundry, "gather_stage_times",
                        lambda *a, **k: _S(_G("engineer", 100.0, 0, 9)))
    monkeypatch.setattr(
        foundry, "probe_test_touch",
        lambda *a, **k: "clean -- 0 uncommitted path(s), so no test-dir touch to report")


def _doctor_out(cfg):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.run_doctor_cli(cfg)
    return rc, buf.getvalue()


def _doctor_cfg(tmp_path, spec):
    cfg = _fabricate(tmp_path, spec)
    p = tmp_path / "IDX.md"
    p.write_text("# roadmap\n\nsome prose\n", encoding="utf-8")
    return _cfg(work_root=str(tmp_path), roadmap=str(p),
                learnings=str(tmp_path / "no-such-learnings.md"))


@pytest.mark.parametrize("spec,healed", [({300: "auth", 301: "clean"}, True),
                                         ({300: "auth"}, False)])
def test_b10_doctor_prints_the_auth_line_once_with_the_right_tense(
        monkeypatch, tmp_path, spec, healed) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _rc, out = _doctor_out(_doctor_cfg(tmp_path, spec))
    hits = [ln for ln in out.splitlines() if ln.startswith(_prefix())]
    assert len(hits) == 1, out
    assert (_healed() in hits[0]) is healed, hits[0]
    assert (REMEDY in hits[0]) is (not healed), hits[0]


def test_b10_all_six_drift_prefixes_still_appear_exactly_once(monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _rc, out = _doctor_out(_doctor_cfg(tmp_path, {300: "auth", 301: "clean"}))
    for name in OLDER_PREFIX_NAMES + (PREFIX_NAME,):
        pref = getattr(foundry, name)
        hits = [ln for ln in out.splitlines() if ln.startswith(pref)]
        assert len(hits) == 1, f"{name} appeared {len(hits)}x:\n{out}"


@pytest.mark.parametrize("fail,rc", [(None, 0), ("uv", 1)])
def test_b10_the_exit_code_is_untouched(monkeypatch, tmp_path, fail, rc) -> None:
    _stub_checks(monkeypatch, fail=fail)
    _patch_older_lines(monkeypatch)
    got, out = _doctor_out(_doctor_cfg(tmp_path, {300: "auth", 301: "clean"}))
    assert got == rc, out
    assert re.search(r"\b\d+/4 checks ok\b", out), \
        f"the doctor summary must still be denominated in FOUR checks:\n{out}"


def test_b10_run_doctor_still_returns_exactly_four_checks(monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    checks = foundry.run_doctor(_doctor_cfg(tmp_path, {300: "auth"}))
    assert len(list(checks)) == 4, list(checks)


@pytest.mark.parametrize("symbol", NEW_SYMBOLS)
def test_b10_run_doctor_source_names_no_new_symbol(symbol) -> None:
    """The new reader lives behind the LINE, not in the check list."""
    assert symbol not in inspect.getsource(foundry.run_doctor), \
        f"{symbol} reached run_doctor, which must stay four Checks"


def test_b10_doctor_reads_the_window_global_at_call_time(monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    monkeypatch.setattr(foundry, WINDOW_NAME, 1)
    _rc, out = _doctor_out(_doctor_cfg(tmp_path, {300: "auth", 301: "clean"}))
    assert "1 most-recent iteration(s)" in out, out


# ========================================================================== #
# Behavior 11 -- REPORT-ONLY and RESUME-SAFE
# ========================================================================== #
@pytest.mark.parametrize("symbol", NEW_SYMBOLS)
def test_b11_the_dispatcher_text_names_no_new_symbol(symbol) -> None:
    assert symbol not in DISPATCHER.read_text(encoding="utf-8"), \
        f"{symbol} reached the dispatcher control path"


@pytest.mark.parametrize("fn_name", ["run_iteration", "run_stage", "build_prompt",
                                     "run_continuous"])
@pytest.mark.parametrize("symbol", NEW_SYMBOLS)
def test_b11_the_control_path_functions_name_no_new_symbol(fn_name, symbol) -> None:
    assert symbol not in inspect.getsource(getattr(foundry, fn_name)), \
        f"{symbol} reached {fn_name}: a loop in flight would not resume byte-identically"


@pytest.mark.parametrize("name", [SEAM, VERDICT_FN])
def test_b11_each_new_function_has_exactly_one_call_site(name) -> None:
    src = pathlib.Path(inspect.getfile(foundry)).read_text(encoding="utf-8")
    n = len(re.findall(rf"(?<!def ){name}\(", src))
    assert n == 1, f"{name} has {n} call sites, expected 1"


def test_b11_the_line_still_has_exactly_one_call_site() -> None:
    src = pathlib.Path(inspect.getfile(foundry)).read_text(encoding="utf-8")
    n = len(re.findall(rf"(?<!def ){LINE_FN}\(", src))
    assert n == 1, f"{LINE_FN} has {n} call sites, expected 1"


def test_b11_both_modules_still_import() -> None:
    assert dispatcher is not None and hasattr(dispatcher, "__file__")
    assert hasattr(foundry, "run_iteration") and hasattr(foundry, "run_stage")


# ========================================================================== #
# Behavior 12 -- the records, decidable from git-TRACKED text alone
# ========================================================================== #
def test_b12_this_iteration_owes_no_record() -> None:
    idx, arc = ROADMAP.read_text(encoding="utf-8"), ARCHIVE.read_text(encoding="utf-8")
    assert foundry.roadmap_ledger_gaps(idx, arc, (THIS_ITER,)) == [], \
        f"iteration {THIS_ITER} owes a ledger row and an archive bullet"
    rows = [ln for ln in idx.splitlines() if ln.startswith(f"- iter {THIS_ITER} ")]
    assert len(rows) == 1 and len(rows[0]) <= 120, rows
    bullets = [ln for ln in arc.splitlines() if ln.startswith(f"- **iter {THIS_ITER} ")]
    assert len(bullets) == 1, len(bullets)


@pytest.mark.parametrize("shed", [242, 243, 244])
def test_b12_every_shed_row_kept_its_archive_bullet(shed) -> None:
    """The paydown may only shed rows the archive already covers."""
    idx, arc = ROADMAP.read_text(encoding="utf-8"), ARCHIVE.read_text(encoding="utf-8")
    assert foundry.roadmap_ledger_gaps(idx, arc, (shed,)) == [], \
        f"iteration {shed}'s row was shed with no archive bullet behind it"
    assert [ln for ln in arc.splitlines() if ln.startswith(f"- **iter {shed} ")], shed


@pytest.mark.parametrize("older", [360, 339, 336, 195])
def test_b12_no_older_record_was_evicted(older) -> None:
    idx, arc = ROADMAP.read_text(encoding="utf-8"), ARCHIVE.read_text(encoding="utf-8")
    assert foundry.roadmap_ledger_gaps(idx, arc, (older,)) == [], \
        f"iteration {older}'s record was evicted by this iteration's row edit"


def test_b12_the_readme_count_word_stays_six() -> None:
    """This iteration changed one ARM of an existing line; there is no seventh line."""
    text = " ".join(README.read_text(encoding="utf-8").split())
    assert "PLUS SIX drift lines" in text, text[:200]
    assert "PLUS SEVEN drift lines" not in text, "no seventh drift line was added"


def test_b12_the_roadmap_index_is_inside_its_own_budget() -> None:
    idx = ROADMAP.read_text(encoding="utf-8")
    assert foundry.roadmap_archive_gaps(
        idx, ARCHIVE.read_text(encoding="utf-8")) == [], "an index row lost its bullet"


# ========================================================================== #
# Behavior 13 -- report-only: nothing is written
# ========================================================================== #
def _tree(root: pathlib.Path):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_b13_neither_reader_writes_anything(tmp_path) -> None:
    cfg = _fabricate(tmp_path, {300: "auth", 301: "clean"})
    before = _tree(tmp_path)
    _line(cfg)
    _line(cfg, limit=5)
    getattr(foundry, SEAM)(cfg)
    getattr(foundry, SEAM)(cfg, limit=2)
    assert _tree(tmp_path) == before, "a report-only diagnostic must write nothing"


def test_b13_doctor_writes_nothing(monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    cfg = _doctor_cfg(tmp_path, {300: "auth", 301: "clean"})
    before = _tree(tmp_path)
    _doctor_out(cfg)
    assert _tree(tmp_path) == before, "doctor must stay a read-only preflight"


def test_b13_the_gatherer_touches_no_subprocess_or_socket(monkeypatch, tmp_path) -> None:
    cfg = _fabricate(tmp_path, {300: "auth", 301: "clean"})
    _forbid_the_outside_world(monkeypatch)
    assert getattr(foundry, SEAM)(cfg).healed is True


# ========================================================================== #
# Behavior 14 -- DISCRIMINATION: every good-arm-only guard is proved to FIRE
# ========================================================================== #
def test_b14_the_healed_predicate_really_discriminates(monkeypatch) -> None:
    """Both arms of the same call, one seam value apart."""
    healed = _warn_line(monkeypatch, _rec(361, 359))
    active = _warn_line(monkeypatch, _rec(359, 359))
    assert healed != active, "the two arms must not render the same text"
    assert _healed() in healed and _healed() not in active


def test_b14_the_ledger_oracle_fires_when_this_iterations_row_is_removed() -> None:
    idx, arc = ROADMAP.read_text(encoding="utf-8"), ARCHIVE.read_text(encoding="utf-8")
    broken_idx = "\n".join(
        ln for ln in idx.splitlines() if not ln.startswith(f"- iter {THIS_ITER} "))
    broken_arc = "\n".join(
        ln for ln in arc.splitlines() if not ln.startswith(f"- **iter {THIS_ITER} "))
    assert foundry.roadmap_ledger_gaps(broken_idx, broken_arc, (THIS_ITER,)) == [THIS_ITER], \
        "the record oracle is vacuous: it does not fire when BOTH records are gone"


def test_b14_the_readme_count_predicate_reads_real_text() -> None:
    text = " ".join(README.read_text(encoding="utf-8").split())
    mutated = text.replace("PLUS SIX drift lines", "PLUS SEVEN drift lines")
    assert mutated != text, "the count-word check is reading text that is not there"
    assert "PLUS SEVEN drift lines" in mutated


@pytest.mark.parametrize("symbol", NEW_SYMBOLS)
def test_b14_the_negative_source_scan_fires_where_the_symbol_does_belong(symbol) -> None:
    """A scan that finds nothing everywhere is indistinguishable from a broken scan."""
    src = pathlib.Path(inspect.getfile(foundry)).read_text(encoding="utf-8")
    assert symbol in src, f"{symbol} is not in the module at all, so every scan is vacuous"


def test_b14_the_end_to_end_fixture_really_produces_an_auth_loss(tmp_path) -> None:
    cfg = _fabricate(tmp_path, {300: "clean", 301: "clean"})
    out = _line(cfg)
    assert getattr(foundry, WARN_NAME) not in out, \
        f"a clean tree must not WARN, or every HEALED assertion above is vacuous: {out}"
