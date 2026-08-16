"""Iteration 190 behaviors: `stage-times` reports cap SATURATION in seconds.

Spec: products/_platform/state/iter-190/pm.md, Expected Behaviors 1-11.

  1. Three new per-group numbers: total_s / cap_hits / cap_seconds (ints); empty input is
     an empty digest that does not raise.
  2. The cap threshold is `>=` and the module constant is read AT CALL TIME; an explicit
     `cap=N` keyword overrides it. 599/600/601 against 600 -> cap_hits 2, cap_seconds 1201.
  3. `cap_hits` (a DURATION population) and `timeouts` (a NO-OUTPUT population) are
     disjoint in both directions; `timeouts` and `kind_counts` keep their meaning.
  4. `StageTimesGroup.cap_share_pct` is a derived PROPERTY, never a field; 100.0 / 0.0 and
     an all-zero-duration group returns 0.0 instead of raising ZeroDivisionError.
  5. `StageTimesSummary` carries the effective `cap` and three derived rollup properties;
     every pre-190 positional AND keyword construction still works and still compares equal.
  6. `render()` names the numbers per group (appended AFTER `timeouts N` and after any
     `kinds ` fragment) and EXACTLY ONCE as a rollup; every pre-existing substring survives;
     an empty digest still says `no stage timings` and emits no rollup.
  7. `render()` reads every new group attribute defensively, so a group stub carrying only
     the pre-190 attributes renders without AttributeError.
  8. Both `to_dict()`s carry the new numbers, are JSON-native by EQUALITY, reuse the frozen
     property, and keep every pre-existing key and value.
  9. No verdict moves: `exit_code` / `over_budget` / `over_budget_count` are unchanged, and a
     100%-saturated group under the SOFT budget still yields exit 0.
 10. `gather_stage_times` forwards `cap=` and is otherwise unchanged; a missing path is still
     an empty digest (exit 2); no new CLI flag was added.
 11. A `tmp_path` `dispatcher.out` fixture in the observed LIVE shape (one team, stage `pm`,
     several PRODUCED attempts each at the full cap, zero no-output) reports
     cap_hits == attempt count, timeouts == 0, cap_share_pct == 100.0.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-190 PM spec's Expected Behaviors, the
conventions of tests/test_iter117_behavior.py / test_iter148_behavior.py / test_iter164_behavior.py
/ test_iter184_behavior.py, and the product's OWN OBSERVABLE surface -- constructing its public
dataclasses, CALLING its public functions and driving its CLI in-process.  `foundry.py`'s and
`dispatcher.py`'s implementation TEXT was NOT read by the author, and neither were the engineer's
notes, the reviewer's notes, the fix notes, `IMPLEMENTATION.patch`, nor `git diff`.

Offline and deterministic: no network, no subprocess, no git, no agent run, no sleeps, no clock.
CLONE-SAFETY (OPERATOR 2026-08-11): no assertion touches the ambient `products/` tree, the live
`dispatcher.out`, or any other gitignored path -- every fixture is built in `tmp_path` or in
memory.  `import dispatcher` at module scope is the in-process import-safety probe.
"""
from __future__ import annotations

import dataclasses
import io
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402,F401  (import-safety probe -- the product quality bar)

THIS_ITER = 190

# The MIDDLE DOT (U+00B7) dispatcher's log() emits; BUILT, never embedded, so this source
# file stays pure-ASCII bytes (iter-117 convention).
MID = "\u00b7"

# Pre-iteration-190 field/key names, so "unchanged" is asserted against a frozen list.
PRE190_GROUP_FIELDS = ("team", "stage", "count", "median_s", "max_s", "timeouts",
                       "over_budget", "kind_counts")
PRE190_GROUP_KEYS = frozenset(PRE190_GROUP_FIELDS)
PRE190_SUMMARY_KEYS = frozenset({"budget", "limit", "iterations", "total",
                                 "over_budget_count", "exit_code", "groups"})


# ------------------------------------------------------------------ fixtures


def _start(ts, team, it, stage, attempt=1):
    return f"- `{ts}` [{team}] iter {it} {MID} **{stage}** attempt {attempt} started"


def _produced(ts, team, it, stage, fname="out.md"):
    return f"- `{ts}` [{team}] iter {it} {MID} {stage} produced `{fname}`"


def _nooutput(ts, team, it, stage, attempt, maxa=4):
    return (f"- `{ts}` [{team}] iter {it} {MID} {stage} "
            f"no output file (attempt {attempt}/{maxa}); retrying")


def _rows(spec):
    """(team, iteration, stage, seconds, produced) rows -> dispatcher-log TEXT."""
    lines = []
    for i, (team, it, stage, dur, produced) in enumerate(spec):
        hour = 1 + (i % 20)
        lines.append(_start(f"08-05 {hour:02d}:00:00", team, it, stage))
        end = f"08-05 {hour:02d}:{dur // 60:02d}:{dur % 60:02d}"
        lines.append(_produced(end, team, it, stage) if produced
                     else _nooutput(end, team, it, stage, 1))
    return "\n".join(lines) + "\n"


def _summ(spec, **kw):
    return foundry.summarize_stage_times(foundry.parse_stage_attempts(_rows(spec)), **kw)


def _log(tmp_path, spec, name="dispatcher.out"):
    p = pathlib.Path(tmp_path) / name
    p.write_text(_rows(spec), encoding="utf-8")
    return p


def _groups(summary):
    return summary.to_dict()["groups"]


def _grp(summary, team, stage):
    for g in _groups(summary):
        if g["team"] == team and g["stage"] == stage:
            return g
    raise AssertionError(f"no group ({team}, {stage}) in {_groups(summary)}")


def _obj_grp(summary, team, stage):
    for g in summary.groups:
        if g.team == team and g.stage == stage:
            return g
    raise AssertionError(f"no group ({team}, {stage})")


def _run_cli(argv):
    """Drive foundry.main IN-PROCESS capturing (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


# The threshold fixture the spec names verbatim: 599 / 600 / 601 in ONE group.
STRADDLE = [("alpha", 1, "pm", 599, True),
            ("alpha", 2, "pm", 600, True),
            ("alpha", 3, "pm", 601, True)]

# Behavior 3's second direction: a single NO-OUTPUT attempt lasting 12s.
NOOUT = [("beta", 4, "tester", 12, False)]


# =====================================================================
# Behavior 1 -- three new per-group numbers, ints, empty input is empty
# =====================================================================
def test_b1_group_exposes_total_s_cap_hits_cap_seconds_as_fields():
    names = {f.name for f in dataclasses.fields(foundry.StageTimesGroup)}
    assert {"total_s", "cap_hits", "cap_seconds"} <= names, names


def test_b1_total_s_is_the_sum_of_kept_durations():
    g = _grp(_summ(STRADDLE), "alpha", "pm")
    assert g["total_s"] == 599 + 600 + 601 == 1800, g


def test_b1_cap_seconds_sums_only_the_cap_hit_attempts():
    g = _grp(_summ(STRADDLE), "alpha", "pm")
    assert g["cap_seconds"] == 600 + 601 == 1201, g


def test_b1_all_three_numbers_are_ints():
    g = _obj_grp(_summ(STRADDLE), "alpha", "pm")
    for name in ("total_s", "cap_hits", "cap_seconds"):
        v = getattr(g, name)
        assert isinstance(v, int) and not isinstance(v, bool), (name, type(v).__name__)


def test_b1_empty_attempts_is_an_empty_digest_and_does_not_raise():
    s = foundry.summarize_stage_times([])
    assert s.groups == ()
    assert s.total_seconds == 0
    assert s.cap_seconds == 0
    assert s.cap_share_pct == 0.0
    assert s.exit_code == 2


# =====================================================================
# Behavior 2 -- `>=` threshold, module constant read AT CALL TIME, cap= override
# =====================================================================
def test_b2_threshold_is_inclusive_599_600_601_gives_two_hits():
    """The spec's own worked example: 600 and 601 count, 599 does not."""
    g = _grp(_summ(STRADDLE), "alpha", "pm")
    assert g["cap_hits"] == 2, g
    assert g["cap_seconds"] == 1201, g


def test_b2_module_constant_is_read_at_call_time(monkeypatch):
    """Same parsed attempts, no re-import: dropping the cap to 300 must add hits."""
    attempts = foundry.parse_stage_attempts(_rows(STRADDLE))
    before = foundry.summarize_stage_times(attempts)
    assert _grp(before, "alpha", "pm")["cap_hits"] == 2
    monkeypatch.setattr(foundry, "STAGE_HARD_CAP_SECONDS", 300)
    after = foundry.summarize_stage_times(attempts)
    assert _grp(after, "alpha", "pm")["cap_hits"] == 3, "all three durations exceed 300"
    assert _grp(after, "alpha", "pm")["cap_seconds"] == 1800


def test_b2_explicit_cap_keyword_overrides_the_module_value(monkeypatch):
    monkeypatch.setattr(foundry, "STAGE_HARD_CAP_SECONDS", 300)
    g = _grp(_summ(STRADDLE, cap=601), "alpha", "pm")
    assert g["cap_hits"] == 1, "only the 601s attempt is at/over an explicit cap of 601"
    assert g["cap_seconds"] == 601, g


def test_b2_default_effective_cap_is_the_module_constant():
    assert foundry.STAGE_HARD_CAP_SECONDS == 600
    assert _summ(STRADDLE).cap == 600
    assert _summ(STRADDLE, cap=123).cap == 123


# =====================================================================
# Behavior 3 -- cap_hits and timeouts are DISJOINT populations, both directions
# =====================================================================
def test_b3_produced_attempt_at_the_cap_is_a_cap_hit_with_zero_timeouts():
    """The live `pm ... median 600s max 600s timeouts 0` case."""
    g = _grp(_summ([("alpha", 1, "pm", 600, True)]), "alpha", "pm")
    assert (g["cap_hits"], g["timeouts"]) == (1, 0), g


def test_b3_short_no_output_attempt_is_a_timeout_with_zero_cap_hits():
    g = _grp(_summ(NOOUT), "beta", "tester")
    assert (g["timeouts"], g["cap_hits"]) == (1, 0), g


def test_b3_timeouts_keeps_its_value_on_a_mixed_corpus():
    s = _summ(STRADDLE + NOOUT)
    assert _grp(s, "alpha", "pm")["timeouts"] == 0
    assert _grp(s, "beta", "tester")["timeouts"] == 1


def test_b3_kind_counts_invariant_still_holds_for_every_group():
    for g in _summ(STRADDLE + NOOUT).groups:
        assert sum(c for _k, c in g.kind_counts) == g.timeouts, (g.team, g.stage,
                                                                 g.kind_counts, g.timeouts)


# =====================================================================
# Behavior 4 -- cap_share_pct is a derived PROPERTY on the group, with a zero guard
# =====================================================================
def test_b4_group_cap_share_pct_is_a_property_not_a_field():
    names = {f.name for f in dataclasses.fields(foundry.StageTimesGroup)}
    assert "cap_share_pct" not in names, "must be DERIVED, never a stored field"
    assert isinstance(getattr(foundry.StageTimesGroup, "cap_share_pct"), property)
    assert isinstance(_obj_grp(_summ(STRADDLE), "alpha", "pm").cap_share_pct, float)


def test_b4_group_share_is_the_rounded_seconds_ratio():
    g = _obj_grp(_summ(STRADDLE), "alpha", "pm")
    assert g.cap_share_pct == round(100.0 * 1201 / 1800, 1) == 66.7


def test_b4_fully_saturated_group_reports_100_and_a_clean_group_reports_0():
    hot = _obj_grp(_summ([("z", 1, "pm", 600, True), ("z", 2, "pm", 700, True)]), "z", "pm")
    assert (hot.cap_hits, hot.cap_share_pct) == (2, 100.0)
    cold = _obj_grp(_summ([("z", 1, "pm", 60, True)]), "z", "pm")
    assert (cold.cap_hits, cold.cap_share_pct) == (0, 0.0)


def test_b4_all_zero_duration_group_returns_zero_not_zero_division():
    g = _obj_grp(_summ([("z", 1, "pm", 0, True), ("z", 2, "pm", 0, True)]), "z", "pm")
    assert g.total_s == 0
    assert g.cap_share_pct == 0.0, "the total_s == 0 guard must fire, not ZeroDivisionError"


def test_b4_zero_guard_holds_even_when_every_attempt_is_a_cap_hit():
    """cap=0 makes 0s durations cap HITS, so the guard is exercised with hits present."""
    g = _obj_grp(_summ([("z", 1, "pm", 0, True)], cap=0), "z", "pm")
    assert g.cap_hits == 1 and g.total_s == 0
    assert g.cap_share_pct == 0.0


# =====================================================================
# Behavior 5 -- the summary carries `cap` and rolls the groups up; back-compat
# =====================================================================
def test_b5_summary_cap_is_a_trailing_field_with_a_default():
    fields = dataclasses.fields(foundry.StageTimesSummary)
    assert fields[-1].name == "cap", [f.name for f in fields]
    assert fields[-1].default == 0


def test_b5_summary_rollup_properties_are_properties_not_fields():
    names = {f.name for f in dataclasses.fields(foundry.StageTimesSummary)}
    for prop in ("total_seconds", "cap_seconds", "cap_share_pct"):
        assert prop not in names, f"{prop} must be DERIVED"
        assert isinstance(getattr(foundry.StageTimesSummary, prop), property), prop


def test_b5_rollup_sums_the_stored_groups():
    s = _summ(STRADDLE + NOOUT)
    assert s.total_seconds == 1800 + 12 == 1812
    assert s.cap_seconds == 1201
    assert s.cap_share_pct == round(100.0 * 1201 / 1812, 1) == 66.3


def test_b5_rollup_share_zero_guard():
    s = _summ([("z", 1, "pm", 0, True)])
    assert s.total_seconds == 0
    assert s.cap_share_pct == 0.0


def test_b5_pre190_group_construction_positional_and_keyword_still_work():
    pos = foundry.StageTimesGroup("alpha", "pm", 3, 420.0, 600, 1, False)
    kw = foundry.StageTimesGroup(team="alpha", stage="pm", count=3, median_s=420.0,
                                 max_s=600, timeouts=1, over_budget=False)
    assert pos == kw, "a pre-190 instance must compare equal to one built the old way"
    assert (pos.total_s, pos.cap_hits, pos.cap_seconds) == (0, 0, 0)
    assert pos.kind_counts == ()
    assert pos.cap_share_pct == 0.0


def test_b5_pre190_summary_construction_positional_and_keyword_still_work():
    g = foundry.StageTimesGroup("alpha", "pm", 3, 420.0, 600, 1, False)
    pos = foundry.StageTimesSummary((g,), 420)
    kw = foundry.StageTimesSummary(groups=(g,), budget=420)
    assert pos == kw
    assert (pos.limit, pos.iterations, pos.cap) == (None, 0, 0)
    assert pos.total_seconds == 0 and pos.cap_share_pct == 0.0


def test_b5_pre190_shaped_instances_still_render():
    g = foundry.StageTimesGroup("alpha", "pm", 3, 420.0, 600, 1, False)
    out = foundry.StageTimesSummary(groups=(g,), budget=420).render()
    assert "[alpha] pm" in out
    assert "cap-hits" in out, "the group line must still carry the new fragment"
    assert len([ln for ln in out.splitlines() if "cap-saturation" in ln]) == 1


def test_b5_new_group_fields_keep_kind_counts_trailing():
    """AMBIGUITY NOTED (PM feedback): the spec says the three new GROUP fields TRAIL, but
    tests/test_iter148_behavior.py:329 pins `kind_counts` as the trailing field with default
    (). Both cannot hold. The observed resolution inserts the three DEFAULTED fields BEFORE
    `kind_counts`, which serves the spec's stated REASON for trailing (compatibility, pinned
    above) while keeping iteration 148 green. Pinned here so a later edit cannot silently
    reorder them and break a positional caller."""
    names = [f.name for f in dataclasses.fields(foundry.StageTimesGroup)]
    assert names[-1] == "kind_counts", names
    assert names[:7] == list(PRE190_GROUP_FIELDS[:7]), names
    assert names.index("total_s") < names.index("cap_hits") < names.index("cap_seconds")
    assert names.index("cap_seconds") < names.index("kind_counts")
    for f in dataclasses.fields(foundry.StageTimesGroup):
        if f.name in ("total_s", "cap_hits", "cap_seconds"):
            assert f.default == 0, f.name


# =====================================================================
# Behavior 6 -- render() names the numbers per group and ONCE as a rollup
# =====================================================================
def test_b6_group_line_carries_cap_hits_after_timeouts():
    line = [ln for ln in _summ(STRADDLE).render().splitlines() if "[alpha] pm" in ln][0]
    assert "timeouts 0" in line
    assert "cap-hits " in line
    assert line.index("cap-hits ") > line.index("timeouts "), line


def test_b6_group_line_names_the_count_and_the_share():
    line = [ln for ln in _summ(STRADDLE).render().splitlines() if "[alpha] pm" in ln][0]
    assert "cap-hits 2" in line, line
    assert "66.7" in line, line


def test_b6_cap_hits_fragment_follows_any_kinds_fragment():
    line = [ln for ln in _summ(NOOUT).render().splitlines() if "[beta] tester" in ln][0]
    assert "kinds " in line and "cap-hits " in line, line
    assert line.index("cap-hits ") > line.index("kinds "), line


def test_b6_exactly_one_rollup_line_naming_cap_total_and_share():
    out = _summ(STRADDLE + NOOUT).render()
    roll = [ln for ln in out.splitlines() if "cap-saturation" in ln]
    assert len(roll) == 1, roll
    assert "600" in roll[0], roll[0]      # the effective cap
    assert "1812s" in roll[0], roll[0]    # total seconds
    assert "66.3" in roll[0], roll[0]     # overall share


def test_b6_preexisting_substrings_of_header_group_and_warn_lines_are_unchanged():
    out = _summ(STRADDLE + NOOUT).render()
    assert "foundry stage-times" in out
    assert f"soft budget {foundry.STAGE_SOFT_BUDGET}s" in out
    for frag in ("count 3", "median 600s", "max 601s", "timeouts 0"):
        assert frag in out, frag
    warn = [ln for ln in out.splitlines() if "WARN" in ln]
    assert len(warn) == 1, warn
    assert "exceeds soft budget 420s" in warn[0], warn[0]


def test_b6_empty_digest_says_no_stage_timings_and_emits_no_rollup():
    out = foundry.summarize_stage_times([]).render()
    assert "no stage timings" in out
    assert "cap-saturation" not in out, out
    assert "cap-hits" not in out, out


# =====================================================================
# Behavior 7 -- defensive attribute reads in render()
# =====================================================================
class _PreG:
    """Group stub carrying EXACTLY the pre-iteration-190 attributes render() reads."""

    def __init__(self, stage="pm", median_s=500.0, timeouts=0, count=1,
                 team="alpha", max_s=500, over_budget=True):
        self.team = team
        self.stage = stage
        self.count = count
        self.median_s = median_s
        self.max_s = max_s
        self.timeouts = timeouts
        self.over_budget = over_budget


class _G4:
    """The narrower iter-164 stub: only stage/median_s/timeouts/count."""

    def __init__(self):
        self.stage = "pm"
        self.median_s = 500.0
        self.timeouts = 0
        self.count = 1


def test_b7_pre190_group_stub_renders_without_attribute_error():
    out = foundry.StageTimesSummary(groups=(_PreG(),), budget=420).render()
    assert "[alpha] pm" in out
    assert "cap-hits 0" in out, "missing new attributes must default, not raise"
    assert len([ln for ln in out.splitlines() if "cap-saturation" in ln]) == 1


def test_b7_rollup_path_also_survives_the_missing_attributes():
    """The rollup sums g.total_s over the stored groups, so the guard must cover BOTH
    the group line and the summary property -- not just the line."""
    s = foundry.StageTimesSummary(groups=(_PreG(), _PreG(stage="engineer")), budget=420)
    assert s.total_seconds == 0
    assert s.cap_seconds == 0
    assert s.cap_share_pct == 0.0
    # NOT asserted here: summary.to_dict(), which calls g.to_dict() on every stored group.
    # That read is UNCONDITIONAL and predates iteration 190 (a duck-typed stub has no
    # to_dict), so behavior 7's guarantee is scoped to render() and the rollup properties.


def test_b7_narrower_iter164_stub_still_fails_on_a_PRE190_attribute_only():
    """AMBIGUITY NOTED (PM feedback): behavior 7 names a stub of `stage, median_s, timeouts,
    count` and says it must render. It cannot, and NOT because of this iteration: the group
    line reads `team` unconditionally, which predates iteration 190. Pinned so the failure
    stays attributable -- the error must name a PRE-190 attribute, never a new one."""
    with pytest.raises(AttributeError) as ei:
        foundry.StageTimesSummary(groups=(_G4(),), budget=420).render()
    msg = str(ei.value)
    assert "team" in msg, msg
    for new in ("total_s", "cap_hits", "cap_seconds", "cap_share_pct"):
        assert new not in msg, f"a NEW attribute leaked into the failure: {msg}"


# =====================================================================
# Behavior 8 -- both to_dict()s round-trip the new numbers
# =====================================================================
def test_b8_group_to_dict_gains_the_four_keys():
    g = _grp(_summ(STRADDLE), "alpha", "pm")
    assert {"total_s", "cap_hits", "cap_seconds", "cap_share_pct"} <= set(g), sorted(g)
    assert (g["total_s"], g["cap_hits"], g["cap_seconds"], g["cap_share_pct"]) == \
        (1800, 2, 1201, 66.7)


def test_b8_summary_to_dict_gains_the_four_keys():
    d = _summ(STRADDLE + NOOUT).to_dict()
    assert {"cap", "total_seconds", "cap_seconds", "cap_share_pct"} <= set(d), sorted(d)
    assert (d["cap"], d["total_seconds"], d["cap_seconds"], d["cap_share_pct"]) == \
        (600, 1812, 1201, 66.3)


def test_b8_whole_payload_is_json_native_by_equality():
    d = _summ(STRADDLE + NOOUT).to_dict()
    assert json.loads(json.dumps(d)) == d


def test_b8_every_derived_value_reuses_the_frozen_property():
    s = _summ(STRADDLE + NOOUT)
    d = s.to_dict()
    assert d["cap_share_pct"] == s.cap_share_pct
    assert d["total_seconds"] == s.total_seconds
    assert d["cap_seconds"] == s.cap_seconds
    for obj, payload in zip(s.groups, d["groups"]):
        assert payload["cap_share_pct"] == obj.cap_share_pct
        assert payload["cap_seconds"] == obj.cap_seconds
        assert payload["total_s"] == obj.total_s


def test_b8_every_preexisting_key_keeps_its_name_and_value():
    s = _summ(STRADDLE + NOOUT)
    d = s.to_dict()
    assert PRE190_SUMMARY_KEYS <= set(d), sorted(PRE190_SUMMARY_KEYS - set(d))
    assert (d["budget"], d["limit"], d["iterations"]) == (foundry.STAGE_SOFT_BUDGET, None, 4)
    assert (d["total"], d["over_budget_count"], d["exit_code"]) == (4, 1, 1)
    for g in d["groups"]:
        assert PRE190_GROUP_KEYS <= set(g), sorted(PRE190_GROUP_KEYS - set(g))
    pm = _grp(s, "alpha", "pm")
    assert (pm["count"], pm["median_s"], pm["max_s"]) == (3, 600, 601)
    assert (pm["timeouts"], pm["over_budget"], pm["kind_counts"]) == (0, True, [])


# =====================================================================
# Behavior 9 -- no verdict moves
# =====================================================================
def test_b9_exit_code_2_iff_nothing_parsed():
    assert foundry.summarize_stage_times([]).exit_code == 2
    assert _summ([("z", 1, "pm", 60, True)]).exit_code == 0


def test_b9_exit_code_1_iff_a_group_is_over_the_SOFT_budget():
    assert _summ([("z", 1, "pm", 600, True)]).exit_code == 1
    assert _summ([("z", 1, "pm", 419, True)]).exit_code == 0


def test_b9_fully_saturated_group_under_the_soft_budget_still_exits_0():
    """The saturation numbers must not become a gating axis."""
    s = _summ([("z", 1, "pm", 300, True), ("z", 2, "pm", 300, True)], cap=100)
    g = _obj_grp(s, "z", "pm")
    assert (g.cap_hits, g.cap_share_pct) == (2, 100.0), "the group IS 100% saturated"
    assert g.over_budget is False, "median 300 is under the 420s soft budget"
    assert s.over_budget_count == 0
    assert s.exit_code == 0, "a saturated group must NOT move the verdict"


def test_b9_over_budget_is_untouched_by_the_cap_knob():
    attempts = foundry.parse_stage_attempts(_rows(STRADDLE))
    base = [g["over_budget"] for g in _groups(foundry.summarize_stage_times(attempts))]
    for cap in (1, 100, 600, 10_000):
        got = foundry.summarize_stage_times(attempts, cap=cap)
        assert [g["over_budget"] for g in _groups(got)] == base, cap
        assert got.exit_code == 1, cap


# =====================================================================
# Behavior 10 -- gather_stage_times forwards cap= and is otherwise unchanged
# =====================================================================
def test_b10_gather_forwards_the_cap_keyword(tmp_path):
    p = _log(tmp_path, STRADDLE)
    assert _grp(foundry.gather_stage_times(str(p)), "alpha", "pm")["cap_hits"] == 2
    tight = foundry.gather_stage_times(str(p), cap=300)
    assert _grp(tight, "alpha", "pm")["cap_hits"] == 3
    assert tight.cap == 300


def test_b10_gather_without_cap_is_unchanged_on_every_preexisting_field(tmp_path):
    p = _log(tmp_path, STRADDLE + NOOUT)
    d = foundry.gather_stage_times(str(p)).to_dict()
    ref = _summ(STRADDLE + NOOUT).to_dict()
    for key in sorted(PRE190_SUMMARY_KEYS - {"groups"}):
        assert d[key] == ref[key], key
    for got, want in zip(d["groups"], ref["groups"]):
        for key in sorted(PRE190_GROUP_KEYS):
            assert got[key] == want[key], key


def test_b10_gather_still_honours_team_and_limit(tmp_path):
    p = _log(tmp_path, [("alpha", 1, "pm", 60, True), ("beta", 2, "pm", 60, True)])
    both = [(g["team"], g["stage"]) for g in _groups(foundry.gather_stage_times(str(p)))]
    only = [(g["team"], g["stage"])
            for g in _groups(foundry.gather_stage_times(str(p), team="alpha"))]
    assert both == [("alpha", "pm"), ("beta", "pm")]
    assert only == [("alpha", "pm")]
    win = foundry.gather_stage_times(str(p), limit=1)
    assert win.limit == 1
    assert [g["team"] for g in _groups(win)] == ["beta"]


def test_b10_missing_path_is_still_an_empty_digest_and_never_raises(tmp_path):
    s = foundry.gather_stage_times(str(tmp_path / "does_not_exist.out"))
    assert s.exit_code == 2
    assert "no stage timings" in s.render()
    assert s.cap_share_pct == 0.0


def test_b10_cli_still_works_with_its_current_flags(tmp_path):
    p = _log(tmp_path, STRADDLE)
    rc, out, _ = _run_cli(["stage-times", "--log", str(p)])
    assert rc == 1, out
    assert "cap-hits " in out and "cap-saturation" in out, out
    rc2, out2, _ = _run_cli(["stage-times", "--log", str(p), "--team", "alpha", "--limit", "2"])
    assert rc2 == 1, out2


def test_b10_json_document_carries_the_new_numbers(tmp_path):
    p = _log(tmp_path, STRADDLE)
    rc, out, _ = _run_cli(["stage-times", "--log", str(p), "--json"])
    doc = json.loads(out)
    assert rc == doc["exit_code"]
    assert doc["cap"] == 600
    assert doc["cap_seconds"] == 1201
    assert doc["groups"][0]["cap_hits"] == 2


def test_b10_no_new_cli_flag_was_added(tmp_path):
    """Out of Scope: no `--cap` flag. argparse must reject it."""
    p = _log(tmp_path, STRADDLE)
    with pytest.raises(SystemExit) as ei:
        _run_cli(["stage-times", "--log", str(p), "--cap", "100"])
    assert ei.value.code == 2


# =====================================================================
# Behavior 11 -- fixture proof of the LIVE shape, built in tmp_path
# =====================================================================
def test_b11_live_shaped_fixture_reports_full_saturation_with_zero_timeouts(tmp_path):
    """One team, stage `pm`, four PRODUCED attempts each at the full 600s cap, zero
    no-output attempts -- the shape `stage-times` reports today as `timeouts 0`."""
    spec = [("_platform", i, "pm", 600, True) for i in (1, 2, 3, 4)]
    p = _log(tmp_path, spec)
    s = foundry.gather_stage_times(str(p))
    g = _grp(s, "_platform", "pm")
    assert g["count"] == 4
    assert g["cap_hits"] == 4, "every attempt ran to the cap"
    assert g["timeouts"] == 0, "and every one of them PRODUCED a file"
    assert g["cap_share_pct"] == 100.0, g
    assert g["total_s"] == g["cap_seconds"] == 2400


def test_b11_that_fixtures_report_carries_the_fragment_and_the_rollup(tmp_path):
    spec = [("_platform", i, "pm", 600, True) for i in (1, 2, 3, 4)]
    out = foundry.gather_stage_times(str(_log(tmp_path, spec))).render()
    assert "cap-hits 4" in out, out
    roll = [ln for ln in out.splitlines() if "cap-saturation" in ln]
    assert len(roll) == 1, roll
    assert "100.0" in roll[0] and "2400s" in roll[0], roll[0]


def test_b11_the_fixture_is_built_here_and_never_read_from_the_ambient_tree(tmp_path):
    """Clone-safety guard: the fixture path lives under tmp_path, not the repo."""
    p = _log(tmp_path, [("_platform", 1, "pm", 600, True)])
    assert p.is_file()
    assert _ROOT not in p.parents, p
