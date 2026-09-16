"""Iteration 364 -- BLACK-BOX behavior tests.

`doctor`'s `roadmap-index:` line gains a FOURTH outcome: WARN when the index is clear
of both the 54,000-char hard wall and the near-wall margin, yet has too little
headroom above the floor the QUALITY SUITE actually binds
(`ROADMAP_INDEX_ABSOLUTE_FLOOR + ROADMAP_INDEX_LEDGER_ROW_CHARS` = 4000 + 120 = 4120)
to absorb ONE mandatory 120-char ledger row.

ISOLATION CONTRACT (HONORED): written ONLY from this iteration's PM spec
(`pm.md` in the iter-364 state dir), the repo's own `tests/` conventions, the tracked
roadmap files, `README.md` / `roles/pm.md` (both are the SUBJECT of behavior 10), and
the product's OWN OBSERVABLE OUTPUT by importing the module and CALLING it.  The
implementation source of `foundry.py` / `dispatcher.py`, the engineer's notes, the
reviewer's notes and `git diff` were NOT read.

Expected Behaviors, numbered as the spec numbers them:
  1. `roadmap_index_binding_slack(headroom)` == headroom - (FLOOR + ROW); pinned at
     4233 -> 113, 4120 -> 0, 0 -> -4120.
  2. Both constants are read AT CALL TIME (never a default arg, never import-captured).
  3. Both new functions are PURE and TOTAL for any `int` input (incl. bool/negatives).
  4. `roadmap_index_paydown_owed(headroom)` is True iff slack < ROW.
  5. NEW FOURTH OUTCOME on a 49,767-char band fixture: one line, prefixed, WARN,
     names 4120 and 113, names `archive`, and does NOT claim over/near the wall.
  6. The three PRE-EXISTING outcomes are untouched (OK / near+over WARN / UNKNOWN).
  7. SEAM VISIBILITY: `roadmap_index_line` calls `roadmap_index_paydown_owed` by its
     BARE module name, both directions.
  8. `roadmap_index_budget` is BYTE-COMPATIBLE: same six fields, same construction,
     same over/near verdicts at the wall.
  9. `doctor` still prints exactly ONE `roadmap-index:` line, still BEFORE
     `stage-budget:`, and on the LIVE tracked index it WARNs iff the shipped oracles
     say a paydown is owed (derived, never a hardcoded char count).
 10. PROSE AGREES WITH CODE: README drops the stale "three outcomes" literal and
     `roles/pm.md` names `roadmap-index:`.

Fully offline and deterministic: synthetic strings and `tmp_path` files only -- no
subprocess, no git, no network, no sleep, and nothing written outside `tmp_path`.
"""

from __future__ import annotations

import contextlib
import dataclasses
import inspect
import io
import pathlib
import socket
import subprocess
import sys
import time

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe

THIS_ITER = 364

# A RELATIVE literal: an absolute machine path in a shipped test is a leak-guard
# finding (OPERATOR 2026-08-30, which reverted iteration 205 over exactly this shape).
REL_STATE = "products/_platform/state/iter-364"

ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
README = _ROOT / "README.md"
PM_CARD = _ROOT / "roles" / "pm.md"

# The spec's own numbers.  Kept as literals here on purpose: this file is the pin.
FLOOR = 4000            # tests/test_iter185_behavior.py:353
ROW = 120               # tests/test_iter185_behavior.py:354
BINDING = FLOOR + ROW   # 4120 -- the floor the suite actually binds
WALL = 54000            # ROADMAP_INDEX_HARD_CHARS
BAND_CHARS = WALL - 4233  # 49767 -- headroom 4233, slack 113: the gap band
FIELDS = ["char_count", "hard_budget", "near_wall_margin",
          "headroom", "over_budget", "near_wall"]


# --------------------------------------------------------------------------
# helpers -- mirror tests/test_iter145_behavior.py, the gauge's own conventions
# --------------------------------------------------------------------------
class _Chk:
    def __init__(self, name, ok, detail="detail-text"):
        self.name = name
        self.ok = ok
        self.detail = detail


def _cfg(**over):
    kw = dict(name="demo", repo="/no/such/repo", allowed_push_repo="demo")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _roadmap_cfg(tmp_path, text, *, name="IDX.md"):
    p = tmp_path / name
    p.write_text(text)
    return _cfg(roadmap=str(p), learnings=str(tmp_path / "no-such-learnings.md"))


def _stub_checks(monkeypatch, *, fail=None):
    for nm in ("power", "agent", "uv", "remote"):
        monkeypatch.setattr(
            foundry, f"check_{nm}",
            lambda *a, _n=nm, **k: _Chk(_n, _n != fail))


def _patch_lag(monkeypatch):
    monkeypatch.setattr(foundry, "parse_brain_launch", lambda *a, **k: 1000.0)
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: ((1, 900.0),))


def _doctor_out(cfg):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.run_doctor_cli(cfg)
    return rc, buf.getvalue()


def _prefixed(out, prefix):
    return [ln for ln in out.splitlines() if ln.startswith(prefix)]


def _snapshot(root):
    files, dirs = {}, set()
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_dir():
            dirs.add(rel)
        else:
            files[rel] = p.read_bytes()
    return files, dirs


# --------------------------------------------------------------------- Behavior 1
def test_b1_the_two_new_constants_are_plain_pinned_ints():
    for nm, want in (("ROADMAP_INDEX_ABSOLUTE_FLOOR", FLOOR),
                     ("ROADMAP_INDEX_LEDGER_ROW_CHARS", ROW)):
        val = getattr(foundry, nm)
        assert isinstance(val, int) and not isinstance(val, bool), (nm, val)
        assert val == want, (
            "%s is %r -- the binding floor is a MEASURED restatement of "
            "tests/test_iter185_behavior.py, not a tunable" % (nm, val))


def test_b1_binding_slack_is_headroom_minus_the_binding_floor():
    assert foundry.roadmap_index_binding_slack(4233) == 113
    assert foundry.roadmap_index_binding_slack(4120) == 0
    assert foundry.roadmap_index_binding_slack(0) == -4120


@pytest.mark.parametrize("headroom", [0, 1, 113, 119, 120, 4000, 4119, 4120,
                                      4233, 4239, 4240, 54000, -1, -9999])
def test_b1_binding_slack_matches_the_arithmetic_everywhere(headroom):
    assert foundry.roadmap_index_binding_slack(headroom) == headroom - BINDING


# --------------------------------------------------------------------- Behavior 2
def test_b2_neither_new_function_hides_a_constant_in_a_default_argument():
    """A default argument freezes the value at def-time, so a later patch of the
    global would appear to work only through some other path."""
    for fn in (foundry.roadmap_index_binding_slack,
               foundry.roadmap_index_paydown_owed):
        sig = inspect.signature(fn)
        assert list(sig.parameters) == ["headroom"], (fn.__name__, sig)
        for p in sig.parameters.values():
            assert p.default is inspect.Parameter.empty, (fn.__name__, sig)


def test_b2_absolute_floor_is_read_at_call_time(monkeypatch):
    before = foundry.roadmap_index_binding_slack(4233)
    monkeypatch.setattr(foundry, "ROADMAP_INDEX_ABSOLUTE_FLOOR", 0)
    assert before == 113, before
    assert foundry.roadmap_index_binding_slack(4233) == 4113, \
        "the floor was captured at import time, not read live"


def test_b2_ledger_row_chars_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "ROADMAP_INDEX_LEDGER_ROW_CHARS", 0)
    assert foundry.roadmap_index_binding_slack(4233) == 233, \
        "the row size was captured at import time, not read live"


def test_b2_paydown_owed_also_reads_both_globals_live(monkeypatch):
    assert foundry.roadmap_index_paydown_owed(4233) is True
    monkeypatch.setattr(foundry, "ROADMAP_INDEX_ABSOLUTE_FLOOR", 0)
    assert foundry.roadmap_index_paydown_owed(4233) is False, \
        "the verdict did not follow the patched floor"


# --------------------------------------------------------------------- Behavior 3
@pytest.mark.parametrize("headroom", [0, 1, -1, True, False, 4233,
                                      -10 ** 9, 10 ** 9])
def test_b3_both_functions_are_total_over_int_inputs(headroom):
    slack = foundry.roadmap_index_binding_slack(headroom)
    owed = foundry.roadmap_index_paydown_owed(headroom)
    assert isinstance(slack, int), (headroom, slack)
    assert isinstance(owed, bool), (headroom, owed)


def test_b3_no_filesystem_effect(monkeypatch, tmp_path):
    (tmp_path / "seed").mkdir()
    (tmp_path / "seed" / "a.txt").write_text("keep me")
    monkeypatch.chdir(tmp_path)
    before = _snapshot(tmp_path)
    for h in (0, 113, 4233, -50):
        foundry.roadmap_index_binding_slack(h)
        foundry.roadmap_index_paydown_owed(h)
    assert _snapshot(tmp_path) == before, "a 'pure' verdict touched the tmp tree"


def test_b3_no_subprocess_no_socket_no_clock(monkeypatch):
    """Scoped tightly with monkeypatch.context so the teardown path is unaffected."""
    def boom(*a, **k):                      # pragma: no cover -- must never run
        raise AssertionError("impure: external effect from a pure verdict")

    with monkeypatch.context() as m:
        m.setattr(subprocess, "run", boom)
        m.setattr(subprocess, "Popen", boom)
        m.setattr(subprocess, "check_output", boom)
        m.setattr(socket, "socket", boom)
        m.setattr(time, "time", boom)
        m.setattr(time, "monotonic", boom)
        for h in (0, 113, 4233):
            foundry.roadmap_index_binding_slack(h)
            foundry.roadmap_index_paydown_owed(h)


# --------------------------------------------------------------------- Behavior 4
@pytest.mark.parametrize("headroom,expected", [
    (4240, False), (4239, True), (4233, True), (0, True), (54000, False)])
def test_b4_paydown_owed_pins(headroom, expected):
    assert foundry.roadmap_index_paydown_owed(headroom) is expected


def test_b4_boundary_is_strictly_less_than_one_row():
    """4240 is the first headroom that fits a row; 4239 is the last that does not.
    An inclusive `<=` here would call a fitting row unfittable."""
    assert foundry.roadmap_index_paydown_owed(BINDING + ROW) is False
    assert foundry.roadmap_index_paydown_owed(BINDING + ROW - 1) is True


def test_b4_verdict_is_exactly_slack_under_one_row_across_the_band():
    for headroom in range(BINDING - 5, BINDING + ROW + 6):
        slack = foundry.roadmap_index_binding_slack(headroom)
        assert foundry.roadmap_index_paydown_owed(headroom) is (slack < ROW), \
            (headroom, slack)


# --------------------------------------------------------------------- Behavior 5
# The near/over arms' own wall claim, captured as a literal and pinned TWO-SIDED
# below: asserted PRESENT in the near and over lines and ABSENT from the band line,
# so a reworded near/over arm fails loudly instead of passing vacuously.
_WALL_CLAIM = "against the %d-char wall" % WALL


def _band_line(tmp_path):
    return foundry.roadmap_index_line(
        _roadmap_cfg(tmp_path, "x" * BAND_CHARS, name="band.md"))


def test_b5_band_fixture_really_is_clear_of_both_wall_flags(tmp_path):
    """The premise of the fourth outcome: this size trips NEITHER old flag."""
    v = foundry.roadmap_index_budget("x" * BAND_CHARS)
    assert v.char_count == 49767 and v.headroom == 4233, v
    assert v.over_budget is False and v.near_wall is False, v
    assert v.headroom > v.near_wall_margin, v
    assert foundry.roadmap_index_paydown_owed(v.headroom) is True, v


def test_b5_fourth_outcome_is_one_prefixed_warn_line(tmp_path):
    line = _band_line(tmp_path)
    assert isinstance(line, str) and line.strip()
    assert "\n" not in line.rstrip("\n"), "embedded newline: %r" % (line,)
    assert len(line.rstrip("\n").splitlines()) == 1, line
    assert line.startswith(foundry.ROADMAP_INDEX_PREFIX), line
    assert foundry.ROADMAP_INDEX_WARN in line, \
        "the gap band still reads clean -- the fourth outcome is missing: %r" % (line,)


def test_b5_fourth_outcome_names_the_binding_floor_and_the_real_slack(tmp_path):
    line = _band_line(tmp_path)
    assert "4120" in line, "the BINDING floor is unnamed: %r" % (line,)
    assert "113" in line, "the real slack is unnamed: %r" % (line,)
    assert str(BAND_CHARS) in line, "the char count is unnamed: %r" % (line,)


def test_b5_fourth_outcome_names_archiving_as_the_remedy(tmp_path):
    line = _band_line(tmp_path)
    assert "archive" in line.lower(), "remedy not named: %r" % (line,)


def test_b5_fourth_outcome_does_not_claim_the_wall_is_near_or_breached(tmp_path):
    """Two-sided: the same literal must be PRESENT in the near/over arms."""
    near = foundry.roadmap_index_line(
        _roadmap_cfg(tmp_path, "x" * (WALL - 100), name="near.md"))
    over = foundry.roadmap_index_line(
        _roadmap_cfg(tmp_path, "x" * (WALL + 500), name="over.md"))
    assert _WALL_CLAIM in near, (
        "the pin has rotted -- the near arm no longer says %r: %r"
        % (_WALL_CLAIM, near))
    assert _WALL_CLAIM in over, (
        "the pin has rotted -- the over arm no longer says %r: %r"
        % (_WALL_CLAIM, over))
    band = _band_line(tmp_path)
    assert _WALL_CLAIM not in band, \
        "the band WARN mis-reports a wall problem it does not have: %r" % (band,)


def test_b5_all_four_outcomes_are_distinct_strings(tmp_path):
    ok = foundry.roadmap_index_line(_roadmap_cfg(tmp_path, "x" * 10, name="a.md"))
    band = _band_line(tmp_path)
    near = foundry.roadmap_index_line(
        _roadmap_cfg(tmp_path, "x" * (WALL - 100), name="n.md"))
    unknown = foundry.roadmap_index_line(_cfg(roadmap=""))
    assert len({ok, band, near, unknown}) == 4, (ok, band, near, unknown)


# --------------------------------------------------------------------- Behavior 6
def test_b6_tiny_index_still_reads_ok_and_never_mentions_the_binding_floor(tmp_path):
    line = foundry.roadmap_index_line(_roadmap_cfg(tmp_path, "x" * 10))
    assert "OK" in line, line
    assert foundry.ROADMAP_INDEX_WARN not in line, \
        "the fourth outcome leaked into the OK arm: %r" % (line,)
    assert "4120" not in line, \
        "the OK text was REWRITTEN rather than left alone: %r" % (line,)
    assert "slack" not in line.lower(), \
        "the OK text was REWRITTEN rather than left alone: %r" % (line,)
    assert "10" in line and str(WALL - 10) in line, line


@pytest.mark.parametrize("size,label", [(WALL - 100, "near"), (WALL + 500, "over")])
def test_b6_near_and_over_still_warn_with_archive(tmp_path, size, label):
    line = foundry.roadmap_index_line(
        _roadmap_cfg(tmp_path, "x" * size, name="%s.md" % label))
    assert foundry.ROADMAP_INDEX_WARN in line, "%s: %r" % (label, line)
    assert str(size) in line, "%s: char count missing: %r" % (label, line)
    assert str(WALL - size) in line, "%s: headroom missing: %r" % (label, line)
    assert "archive" in line.lower(), "%s: remedy not named: %r" % (label, line)


def test_b6_missing_path_still_reads_unknown_without_warn(tmp_path):
    for cfg in (_cfg(roadmap=""),
                _cfg(roadmap=str(tmp_path / "nope.md"))):
        line = foundry.roadmap_index_line(cfg)
        assert line.startswith(foundry.ROADMAP_INDEX_PREFIX), line
        assert "UNKNOWN" in line, line
        assert foundry.ROADMAP_INDEX_WARN not in line, \
            "'I cannot tell' must never be reported as a problem: %r" % (line,)


# --------------------------------------------------------------------- Behavior 7
def test_b7_forced_true_makes_a_tiny_index_warn(monkeypatch, tmp_path):
    cfg = _roadmap_cfg(tmp_path, "x" * 10)
    monkeypatch.setattr(foundry, "roadmap_index_paydown_owed", lambda h: True)
    line = foundry.roadmap_index_line(cfg)
    assert foundry.ROADMAP_INDEX_WARN in line, (
        "the stand-in did not bite -- roadmap_index_paydown_owed is not called by "
        "its BARE module name: %r" % (line,))
    assert "4120" in line, "not the paydown wording: %r" % (line,)


def test_b7_forced_false_makes_the_band_read_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(foundry, "roadmap_index_paydown_owed", lambda h: False)
    line = _band_line(tmp_path)
    assert "OK" in line and foundry.ROADMAP_INDEX_WARN not in line, \
        "the stand-in did not bite: %r" % (line,)


def test_b7_the_seam_is_consulted_with_the_measured_headroom(monkeypatch, tmp_path):
    seen = []

    def spy(headroom):
        seen.append(headroom)
        return False

    monkeypatch.setattr(foundry, "roadmap_index_paydown_owed", spy)
    _band_line(tmp_path)
    assert seen == [4233], \
        "the seam was handed %r, not the band fixture's headroom" % (seen,)


# --------------------------------------------------------------------- Behavior 8
# Captured at import so a scripted stand-in cannot recurse into a patched seam --
# the convention tests/test_iter145_behavior.py's `_fake` established.
_RESULT_TYPE = type(foundry.roadmap_index_budget(""))
_SIX = dict(char_count=123, hard_budget=WALL, near_wall_margin=3000,
            headroom=WALL - 123, over_budget=False, near_wall=False)


def test_b8_budget_still_carries_exactly_the_six_original_fields():
    v = foundry.roadmap_index_budget("abc")
    assert dataclasses.is_dataclass(v), type(v)
    assert [f.name for f in dataclasses.fields(v)] == FIELDS, \
        [f.name for f in dataclasses.fields(v)]
    assert type(v).__dataclass_params__.frozen is True


def test_b8_still_constructible_from_exactly_those_six_keywords():
    """tests/test_iter145_behavior.py's `_fake` builds this type by keyword; a new
    field (or a renamed one) breaks that stand-in and the whole gauge suite."""
    v = _RESULT_TYPE(**_SIX)
    for k, want in _SIX.items():
        assert getattr(v, k) == want, (k, getattr(v, k), want)
    with pytest.raises(TypeError):
        _RESULT_TYPE(**dict(_SIX, extra_field=1))
    for drop in FIELDS:
        with pytest.raises(TypeError):
            _RESULT_TYPE(**{k: v2 for k, v2 in _SIX.items() if k != drop})


@pytest.mark.parametrize("size,over,near", [
    (WALL - 100, False, True), (WALL, True, False), (WALL + 500, True, False)])
def test_b8_wall_verdicts_are_unchanged(size, over, near):
    v = foundry.roadmap_index_budget("x" * size)
    assert v.over_budget is over and v.near_wall is near, (size, v)
    assert v.char_count == size and v.headroom == WALL - size, v
    assert v.hard_budget == foundry.ROADMAP_INDEX_HARD_CHARS, v
    assert v.near_wall_margin == foundry.ROADMAP_INDEX_NEAR_WALL_CHARS, v


def test_b8_budget_signature_is_unchanged():
    sig = inspect.signature(foundry.roadmap_index_budget)
    assert list(sig.parameters) == ["text"], sig


# --------------------------------------------------------------------- Behavior 9
def _live_cfg(tmp_path):
    """doctor driven against the LIVE tracked index; every other seam scripted."""
    return _cfg(roadmap=str(ROADMAP), learnings=str(tmp_path / "no-such.md"))


def test_b9_doctor_prints_one_roadmap_index_line_before_stage_budget(
        monkeypatch, tmp_path):
    _stub_checks(monkeypatch)
    _patch_lag(monkeypatch)
    sentinel = foundry.STAGE_BUDGET_PREFIX + " SENTINEL-iter364-marker"
    monkeypatch.setattr(foundry, "stage_budget_line", lambda *a, **k: sentinel)
    rc, out = _doctor_out(_live_cfg(tmp_path))
    idx_lines = _prefixed(out, foundry.ROADMAP_INDEX_PREFIX)
    assert len(idx_lines) == 1, out
    lines = out.splitlines()
    assert lines.index(idx_lines[0]) < lines.index(sentinel), \
        "the roadmap-index line must still print BEFORE stage-budget:\n%s" % out
    assert rc == 0, out


def test_b9_live_index_verdict_is_derived_from_the_shipped_oracles(
        monkeypatch, tmp_path):
    """No hardcoded char count: the expectation is recomputed from the same public
    oracles the gauge uses, so this test cannot rot as the roadmap grows."""
    text = ROADMAP.read_text(encoding="utf-8")
    budget = foundry.roadmap_index_budget(text)
    owed = foundry.roadmap_index_paydown_owed(budget.headroom)
    _stub_checks(monkeypatch)
    _patch_lag(monkeypatch)
    monkeypatch.setattr(
        foundry, "stage_budget_line",
        lambda *a, **k: foundry.STAGE_BUDGET_PREFIX + " scripted")
    rc, out = _doctor_out(_live_cfg(tmp_path))
    line = _prefixed(out, foundry.ROADMAP_INDEX_PREFIX)[0]
    warned = foundry.ROADMAP_INDEX_WARN in line
    assert warned is bool(budget.over_budget or budget.near_wall or owed), (
        "the printed verdict disagrees with the oracles "
        "(over=%r near=%r paydown_owed=%r headroom=%r): %r"
        % (budget.over_budget, budget.near_wall, owed, budget.headroom, line))
    if owed and not (budget.over_budget or budget.near_wall):
        assert str(foundry.ROADMAP_INDEX_ABSOLUTE_FLOOR
                   + foundry.ROADMAP_INDEX_LEDGER_ROW_CHARS) in line, line
        assert str(foundry.roadmap_index_binding_slack(budget.headroom)) in line, line


def test_b9_doctor_exit_code_is_unchanged_by_the_fourth_outcome(
        monkeypatch, tmp_path):
    _patch_lag(monkeypatch)
    monkeypatch.setattr(foundry, "roadmap_index_paydown_owed", lambda h: True)
    monkeypatch.setattr(
        foundry, "stage_budget_line",
        lambda *a, **k: foundry.STAGE_BUDGET_PREFIX + " scripted")
    _stub_checks(monkeypatch)
    rc_ok, out_ok = _doctor_out(_roadmap_cfg(tmp_path, "x" * 10))
    assert foundry.ROADMAP_INDEX_WARN in _prefixed(
        out_ok, foundry.ROADMAP_INDEX_PREFIX)[0], out_ok
    assert rc_ok == 0, "an advisory WARN must not fail doctor:\n%s" % out_ok
    _stub_checks(monkeypatch, fail="uv")
    rc_bad, _ = _doctor_out(_roadmap_cfg(tmp_path, "x" * 10, name="B.md"))
    assert rc_bad == 1, "a failing check must still fail doctor"


# --------------------------------------------------------------------- Behavior 10
def test_b10_readme_dropped_the_stale_three_outcomes_claim():
    text = README.read_text(encoding="utf-8")
    stale = "with three outcomes: UNKNOWN when the index is missing/unreadable"
    assert stale not in text, \
        "README still advertises three outcomes for a line that now has four"


def test_b10_pm_card_names_the_roadmap_index_line():
    text = PM_CARD.read_text(encoding="utf-8")
    assert "roadmap-index:" in text, \
        "roles/pm.md never names the gauge the PM is now supposed to read"


# ------------------------------------------------------- AC oracles (derived)
_ROW = ("- iter 364 -- roadmap-index WARNs when the index cannot absorb one "
        "mandatory ledger row.")


def test_ac_roadmap_ledger_row_is_verbatim_and_88_chars():
    assert len(_ROW) == 88, len(_ROW)
    rows = [ln.rstrip("\n") for ln in ROADMAP.read_text(encoding="utf-8").splitlines()]
    assert rows.count(_ROW) == 1, \
        "the iteration-364 ledger row is missing or duplicated in the index"
    arc = ARCHIVE.read_text(encoding="utf-8")
    assert arc.count("- **iter 364") == 1, \
        "the iteration-364 detail bullet is missing or duplicated in the archive"


def test_ac_live_index_still_clears_the_binding_floor():
    """The wall this iteration teaches the gauge to report is the one it must
    itself respect; archiving is the remedy, raising the budget is not."""
    budget = foundry.roadmap_index_budget(ROADMAP.read_text(encoding="utf-8"))
    assert budget.over_budget is False, budget
    assert budget.headroom >= BINDING, (
        "index headroom %d is under the %d-char BINDING FLOOR the suite asserts -- "
        "archive spent prose; raising the budget is NOT the remedy"
        % (budget.headroom, BINDING))


def test_ac_both_entry_points_still_import():
    assert foundry.__name__ == "foundry"
    assert dispatcher.__name__ == "dispatcher"
    assert hasattr(foundry, "run_iteration") and hasattr(foundry, "run_stage")
