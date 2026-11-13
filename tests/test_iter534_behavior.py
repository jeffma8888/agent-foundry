"""Iteration 534 -- BLACK-BOX behavior tests: the three yearless-stamp walkers
(`parse_stage_attempts`, `pending_stage_starts`, `open_holds`) measure the TRUE span
when a December stamp is followed by a January stamp (a year crossing), instead of
clamping it to 0 or skipping the line -- while staying month-scoped and leaving the
same-year midnight rule and the reversed-ghost rule (iter 528) unchanged.

Spec under test: products/_platform/state/iter-534/pm.md, Expected Behaviors 1-9.

ISOLATION CONTRACT (HONORED): written ONLY from that PM spec and the conventions under
`tests/` (the `dispatcher.out` line builders of tests/test_iter528_behavior.py /
test_iter234_behavior.py), driving the product's PUBLIC functions.  I did NOT read the
implementation source, engineer.md, reviewer.md, or any `git diff`.

Every log fixture is a SYNTHETIC STRING built in-process: no git, no network, no
gitignored state, no real clock (`now` is always passed explicitly).
"""

import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

MID = "\u00b7"
TEAM = "_platform"
ITER = 534


# --------------------------------------------------------------------------
# fixture builders -- the EXACT dispatcher.out line shapes (test_iter528 `_pre`)
# --------------------------------------------------------------------------
def _pre(ts, team=TEAM, it=ITER):
    return f"- `{ts}` [{team}] iter {it} {MID} "


def _start(ts, stage="tester", attempt=1):
    return _pre(ts) + f"**{stage}** attempt {attempt} started"


def _produced(ts, stage="tester", fname="tester.md"):
    return _pre(ts) + f"{stage} produced `{fname}`"


def _backoff(ts, stage="tester", mins=30, kind="auth"):
    return _pre(ts) + f"{stage} backing off {mins} min (failure kind: {kind})"


def _mk(*lines):
    return "\n".join(lines) + "\n"


def _one_attempt(start_ts, end_ts):
    got = foundry.parse_stage_attempts(_mk(_start(start_ts), _produced(end_ts)))
    assert len(got) == 1, got
    return got[0]


def _one_pending(start_ts, now, cap=600):
    got = foundry.pending_stage_starts(_mk(_start(start_ts)), now, cap=cap)
    assert len(got) == 1, got
    return got[0]


# --------------------------------------------------------------------------
# Behavior 1 -- parse_stage_attempts across Dec 31 -> Jan 1
# --------------------------------------------------------------------------
def test_b1_attempt_duration_across_year_crossing_is_900():
    att = _one_attempt("12-31 23:55:00", "01-01 00:10:00")
    assert att.duration_s == 900
    assert att.stage == "tester"
    assert att.iteration == ITER


# --------------------------------------------------------------------------
# Behavior 2 -- pending start past cap across the crossing is STALE
# --------------------------------------------------------------------------
def test_b2_pending_across_year_crossing_is_stale_at_900():
    rec = _one_pending("12-31 23:55:00", "01-01 00:10:00", cap=600)
    assert rec.elapsed_s == 900
    assert rec.headroom_s == -300
    assert rec.stale is True


# --------------------------------------------------------------------------
# Behavior 3 -- pending start under cap across the crossing is FRESH
# --------------------------------------------------------------------------
def test_b3_pending_across_year_crossing_under_cap_is_fresh_540():
    rec = _one_pending("12-31 23:55:00", "01-01 00:04:00", cap=600)
    assert rec.elapsed_s == 540
    assert rec.headroom_s == 60
    assert rec.stale is False


# --------------------------------------------------------------------------
# Behaviors 4 & 5 -- open_holds across the crossing
# --------------------------------------------------------------------------
def test_b4_open_hold_across_year_crossing_is_reported():
    got = foundry.open_holds(_mk(_backoff("12-31 23:55:00")), "01-01 00:10:00")
    assert len(got) == 1, got
    hold = got[0]
    assert isinstance(hold, foundry.PendingHold)
    assert hold.elapsed_s == 900
    assert hold.wait_s == 1800
    assert hold.remaining_s == 900
    assert hold.kind == "auth"
    assert hold.stage == "tester"


def test_b5_expired_hold_across_year_crossing_is_closed():
    assert foundry.open_holds(_mk(_backoff("12-31 23:55:00")),
                              "01-01 00:30:00") == ()


# --------------------------------------------------------------------------
# Behavior 6 -- an ordinary same-year midnight crossing is unchanged (60 s)
# --------------------------------------------------------------------------
def test_b6_same_year_midnight_crossing_unchanged_in_all_three():
    a, b = "09-06 23:59:30", "09-07 00:00:30"
    assert _one_attempt(a, b).duration_s == 60
    assert _one_pending(a, b, cap=600).elapsed_s == 60
    holds = foundry.open_holds(_mk(_backoff(a)), b)
    assert len(holds) == 1, holds
    assert holds[0].elapsed_s == 60
    assert holds[0].remaining_s == 1740


# --------------------------------------------------------------------------
# Behavior 7 -- a same-year reversed ghost (>1 day later than now) stays as before
# --------------------------------------------------------------------------
def test_b7_same_year_reversed_ghost_stays_zero_or_skipped():
    later, now = "03-10 10:00:00", "03-08 10:00:00"
    assert _one_pending(later, now, cap=600).elapsed_s == 0
    assert foundry.open_holds(_mk(_backoff(later)), now) == ()
    assert _one_attempt(later, now).duration_s == 0


def test_b7b_december_same_year_reversed_ghost_is_not_revived():
    # neighbour of the fixed case: both stamps December, start later than now --
    # the guard is Dec -> Jan only, so this must not be year-shifted into a span.
    later, now = "12-20 10:00:00", "12-18 10:00:00"
    assert _one_pending(later, now, cap=600).elapsed_s == 0
    assert foundry.open_holds(_mk(_backoff(later)), now) == ()
    assert _one_attempt(later, now).duration_s == 0


# --------------------------------------------------------------------------
# Behavior 8 -- the guard is month-scoped (Nov -> Jan keeps today's value)
# --------------------------------------------------------------------------
def test_b8_november_to_january_keeps_todays_zero():
    assert _one_pending("11-30 23:55:00", "01-01 00:10:00",
                        cap=600).elapsed_s == 0


# --------------------------------------------------------------------------
# Behavior 9 -- a multi-day Dec -> Jan gap is measured truthfully
# --------------------------------------------------------------------------
def test_b9_multi_day_december_to_january_gap():
    rec = _one_pending("12-30 12:00:00", "01-01 12:00:00", cap=600)
    assert rec.elapsed_s == 172800
    assert rec.stale is True


@pytest.mark.parametrize("start,end,want", [
    ("12-31 23:59:30", "01-01 00:00:10", 40),   # test_iter234 b3c re-pin
    ("12-31 23:59:00", "01-01 00:01:00", 120),  # test_iter240 b2 re-pin
    ("12-31 00:00:00", "01-01 00:00:00", 86400),
])
def test_b1_b2_year_crossing_spans_agree_across_walkers(start, end, want):
    assert _one_attempt(start, end).duration_s == want
    assert _one_pending(start, end, cap=None).elapsed_s == want
