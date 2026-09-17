"""Iteration 369 -- BLACK-BOX behavior tests: the `stage-budget` gauge stops
counting CREDENTIAL-LOSS attempts in its medians.

Spec under test: products/_platform/state/iter-369/pm.md, Expected Behaviors 1-9.

  1. `drop_excluded_kind_attempts(attempts, ("auth",))` keeps exactly the rows whose
     `kind` is not `"auth"`, in INPUT ORDER.
  2. NO-OP for `kinds` of `None` / empty; the input sequence is never mutated and a
     tuple input is accepted.
  3. BLACKOUT GUARD: when EVERY row would be dropped, all of them are returned; an
     empty input returns an empty list.
  4. TOTALITY over the enumerated shapes: a row with no `kind`, a `None` kind or a
     non-string kind is KEPT; a string / int / non-iterable `kinds` degrades to
     behavior 2's no-op.
  5. The keyword DEFAULTS OFF -- `gather_stage_times(...)` and the same call with
     `exclude_kinds=None` agree, and both agree with `summarize_stage_times` over the
     unfiltered parsed attempts, so `stage-times` output is unchanged.
  6. `exclude_kinds=("auth",)` drops the auth population per (team, stage): the
     4-auth stage reports `count == 1` / `median_s == 600`, the auth-free stage is
     reported IDENTICALLY, and the filter runs AFTER the `team` filter.
  7. `stage_budget_line` OPTS IN -- it forwards `exclude_kinds` read as a LIVE module
     global (a monkeypatch of the global changes the NEXT call), while the
     `stage-times` CLI forwards no `exclude_kinds` at all.
  8. `STAGE_BUDGET_EXCLUDED_KINDS` is a non-empty tuple of `str`, equals
     `(AUTH_LOSS_KIND,)`, and every member is a key of `ATTEMPT_FAILURE_MARKERS`.
  9. END-TO-END on the real shape: the filter flips `stage_budget_line` from `1/2` to
     `2/2` stages near the wall on one synthetic log -- two-sided, not a tautology.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-369
PM spec, the pre-existing conventions under `tests/` (chiefly
`tests/test_iter117_behavior.py` and `tests/test_iter148_behavior.py` for the
`dispatcher.out` line shapes, and `tests/test_iter184_behavior.py` for the `_cfg` /
windowing fixtures), and the product's OWN observable behavior by importing and
CALLING its public names.  The implementation SOURCE of `foundry.py` / `dispatcher.py`
was NOT read, nor the engineer's notes, the reviewer's notes, or any `git diff`.

OFFLINE + FRESH-CLONE SAFE: every fixture log is hand-built under `tmp_path` -- the
live (gitignored) `dispatcher.out` is never read, and nothing is asserted about the
ambient tree or `products/*/state` (the trap that lost iteration 154).  No subprocess,
no git, no network, no clock.  Source is pure-ASCII: the U+00B7 separator that log()
emits is built from an escape, never embedded.
"""
from __future__ import annotations

import io
import json
import pathlib
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe (the quality bar)

THIS_ITER = 369

# The MIDDLE DOT (U+00B7) separator dispatcher's log() emits; BUILT, never embedded,
# so this source file stays pure-ASCII bytes (iter-117 convention).
MID = "\u00b7"

# A generic failure tail carrying the shipped `auth` needle (iter-148 convention:
# tails are generic, never a vendor's real wording).
TAIL_AUTH = "agent run failed: credential refresh failed"
TAIL_TIMEOUT = "agent run failed: agent run timed out after 600s"

AUTH = "auth"
CONST_NAME = "STAGE_BUDGET_EXCLUDED_KINDS"
HELPER_NAME = "drop_excluded_kind_attempts"
SEAM = "gather_stage_times"

# Resume safety: the control path must not learn either new name (Acceptance).
RESUME_CRITICAL = ("run_stage", "run_iteration", "build_prompt", "run_continuous",
                   "postrelease_step", "preship_cli")


# ========================================================================== #
# fixture builders -- the EXACT dispatcher.out line shapes
# ========================================================================== #
def _start(ts, team, it, stage, attempt=1):
    return f"- `{ts}` [{team}] iter {it} {MID} **{stage}** attempt {attempt} started"


def _produced(ts, team, it, stage, fname="out.md"):
    return f"- `{ts}` [{team}] iter {it} {MID} {stage} produced `{fname}`"


def _nooutput(ts, team, it, stage, attempt=1, tail=None, maxa=4):
    base = (f"- `{ts}` [{team}] iter {it} {MID} {stage} "
            f"no output file (attempt {attempt}/{maxa})")
    return base + (f"; tail: '{tail}'" if tail else "; retrying")


def _log(tmp_path, rows, name="dispatcher.out"):
    """Build a fixture log from (team, iteration, stage, seconds, produced, tail) rows.

    The start line sits at HH:00:00 and the terminal line HH:MM:SS later, so the
    parsed duration is exactly `seconds`.
    """
    lines = []
    for team, it, stage, dur, produced, tail in rows:
        hour = 1 + (it % 20)
        st = f"08-05 {hour:02d}:00:00"
        en = (f"08-05 {hour + dur // 3600:02d}:"
              f"{(dur % 3600) // 60:02d}:{dur % 60:02d}")
        lines.append(_start(st, team, it, stage))
        lines.append(_produced(en, team, it, stage) if produced
                     else _nooutput(en, team, it, stage, 1, tail))
    p = pathlib.Path(tmp_path) / name
    p.write_text("\n".join(lines) + "\n")
    return p


def _cfg(**over):
    """A ProductConfig with RELATIVE placeholders -- an absolute machine path in a
    shipped test is a leak-guard finding (the shape that reverted iteration 205)."""
    kw = dict(name="demo", repo="demo-repo", allowed_push_repo="demo")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _grp(summary, stage, team="demo"):
    for g in summary.to_dict()["groups"]:
        if g["team"] == team and g["stage"] == stage:
            return g
    return None


def _fn_names(fn):
    """Compiled-bytecode introspection (co_names), NOT source text -- this is the
    convention that keeps the tester firewall intact (tests/test_iter115, /148)."""
    stack, seen, names = [fn.__code__], set(), set()
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names |= set(code.co_names)
        for c in code.co_consts:
            if isinstance(c, types.CodeType):
                stack.append(c)
    return names


def _run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


# ========================================================================== #
# duck-typed attempt rows -- no test needs the real dataclass
# ========================================================================== #
class _Row:
    """An attempt-shaped row carrying exactly a `kind`."""

    def __init__(self, kind):
        self.kind = kind

    def __repr__(self):  # readable assertion messages
        return "_Row(%r)" % (self.kind,)


class _NoKind:
    """A row with NO `kind` attribute at all -- behavior 4 says KEEP it."""

    def __repr__(self):
        return "_NoKind()"


def _drop(attempts, kinds):
    return foundry.drop_excluded_kind_attempts(attempts, kinds)


# ========================================================================== #
# Behavior 1 -- the filter keeps the non-matching rows, in INPUT ORDER
# ========================================================================== #
def test_b1_keeps_exactly_the_non_matching_rows_in_input_order():
    a, t, ok = _Row(AUTH), _Row("timeout"), _Row("")
    got = _drop([a, t, ok], (AUTH,))
    assert got == [t, ok], got
    assert [r.kind for r in got] == ["timeout", ""], got


def test_b1_the_survivors_are_the_same_objects_and_a_new_list():
    src = [_Row(AUTH), _Row("timeout"), _Row("")]
    got = _drop(src, (AUTH,))
    assert got is not src
    assert all(any(r is s for s in src) for r in got), got
    assert isinstance(got, list), type(got)


def test_b1_order_is_input_order_not_sorted_by_kind():
    rows = [_Row("timeout"), _Row(AUTH), _Row(""), _Row("service")]
    assert [r.kind for r in _drop(rows, (AUTH,))] == ["timeout", "", "service"]


def test_b1_several_excluded_kinds_are_all_dropped():
    rows = [_Row(AUTH), _Row("timeout"), _Row("service"), _Row("")]
    assert [r.kind for r in _drop(rows, (AUTH, "service"))] == ["timeout", ""]


# ========================================================================== #
# Behavior 2 -- NO-OP for None / empty, and never mutates the input
# ========================================================================== #
@pytest.mark.parametrize("kinds", [None, (), [], set(), frozenset()])
def test_b2_empty_or_none_kinds_is_a_no_op(kinds):
    src = [_Row(AUTH), _Row("timeout"), _Row("")]
    got = _drop(src, kinds)
    assert got == src, (kinds, got)
    assert [r.kind for r in got] == [AUTH, "timeout", ""], (kinds, got)


def test_b2_the_input_list_is_never_mutated():
    a, t = _Row(AUTH), _Row("timeout")
    src = [a, t]
    before = list(src)
    _drop(src, (AUTH,))
    assert src == before and len(src) == 2, src


def test_b2_a_tuple_input_is_accepted_and_the_original_object_is_unchanged():
    a, t = _Row(AUTH), _Row("timeout")
    src = (a, t)
    got = _drop(src, (AUTH,))
    assert isinstance(got, list), type(got)
    assert got == [t], got
    assert src == (a, t) and len(src) == 2, src


def test_b2_no_op_still_returns_a_fresh_list_the_caller_may_own():
    src = [_Row(AUTH)]
    got = _drop(src, None)
    assert got == src
    got.append(_Row("timeout"))
    assert len(src) == 1, "the no-op leaked the caller's own list object"


# ========================================================================== #
# Behavior 3 -- blackout guard
# ========================================================================== #
def test_b3_when_every_row_would_be_dropped_all_are_returned():
    rows = [_Row(AUTH), _Row(AUTH), _Row(AUTH)]
    got = _drop(rows, (AUTH,))
    assert got == rows, got
    assert len(got) == 3, got


def test_b3_a_single_matching_row_is_a_blackout_too():
    only = _Row(AUTH)
    assert _drop([only], (AUTH,)) == [only]


def test_b3_an_empty_input_returns_an_empty_list():
    got = _drop([], (AUTH,))
    assert got == [] and isinstance(got, list), got


def test_b3_the_blackout_guard_is_per_call_and_never_sticky():
    """A blackout call must not disable filtering for the NEXT, mixed call."""
    dead = _Row(AUTH)
    assert _drop([dead], (AUTH,)) == [dead]
    mixed = [_Row(AUTH), _Row("timeout")]
    assert [r.kind for r in _drop(mixed, (AUTH,))] == ["timeout"]


def test_b3_blackout_survives_a_mix_of_two_excluded_kinds():
    rows = [_Row(AUTH), _Row("service")]
    assert _drop(rows, (AUTH, "service")) == rows


# ========================================================================== #
# Behavior 4 -- totality over the enumerated shapes
# ========================================================================== #
@pytest.mark.parametrize("row", [_NoKind(), _Row(None), _Row(7), _Row(3.5),
                                 _Row(b"auth"), _Row(("auth",))])
def test_b4_a_row_whose_kind_is_absent_or_not_a_string_is_kept(row):
    keeper = _Row("timeout")
    got = _drop([row, keeper], (AUTH,))
    assert got == [row, keeper], got


def test_b4_a_missing_kind_is_kept_even_when_it_is_the_only_row():
    row = _NoKind()
    assert _drop([row], (AUTH,)) == [row]


@pytest.mark.parametrize("kinds", ["auth", 5, 3.5, True, object()])
def test_b4_a_non_iterable_or_string_kinds_degrades_to_the_no_op(kinds):
    src = [_Row(AUTH), _Row("timeout")]
    got = _drop(src, kinds)
    assert got == src, (kinds, got)
    assert [r.kind for r in got] == [AUTH, "timeout"], (kinds, got)


@pytest.mark.parametrize("kinds", [(AUTH,), [AUTH], {AUTH}, frozenset({AUTH}),
                                   (None, AUTH), (7, AUTH)])
def test_b4_any_iterable_of_kinds_works_and_junk_members_are_ignored(kinds):
    a, t = _Row(AUTH), _Row("timeout")
    assert _drop([a, t], kinds) == [t], kinds


def test_b4_matching_is_exact_so_a_differently_cased_kind_does_not_match():
    """The kinds vocabulary is the shipped lower-case `ATTEMPT_FAILURE_MARKERS` keys;
    an upper-case argument is simply not one of them (noted as PM feedback)."""
    a, t = _Row(AUTH), _Row("timeout")
    assert _drop([a, t], ("AUTH",)) == [a, t]


def test_b4_the_function_is_pure_and_repeatable():
    src = [_Row(AUTH), _Row("timeout")]
    first = _drop(src, (AUTH,))
    second = _drop(src, (AUTH,))
    assert first == second, (first, second)
    assert first is not second


# ========================================================================== #
# Behavior 5 -- the keyword DEFAULTS OFF: stage-times output is unchanged
# ========================================================================== #
def _b5_log(tmp_path):
    """One team, three produced `pm` attempts and one auth loss on `eng`."""
    rows = [("demo", i + 1, "pm", 60 * (i + 1), True, None) for i in range(3)]
    rows.append(("demo", 2, "eng", 3, False, TAIL_AUTH))
    return _log(tmp_path, rows)


def test_b5_default_equals_exclude_kinds_none(tmp_path):
    p = _b5_log(tmp_path)
    base = foundry.gather_stage_times(str(p), team="demo", limit=5).to_dict()
    same = foundry.gather_stage_times(str(p), team="demo", limit=5,
                                      exclude_kinds=None).to_dict()
    assert same == base, json.dumps([base, same])


def test_b5_default_equals_summarize_over_the_unfiltered_attempts(tmp_path):
    p = _b5_log(tmp_path)
    got = foundry.gather_stage_times(str(p), team="demo").to_dict()
    attempts = [a for a in foundry.parse_stage_attempts(p.read_text())
                if a.team == "demo"]
    expected = foundry.summarize_stage_times(attempts).to_dict()
    assert got == expected, json.dumps([got, expected])


def test_b5_the_auth_attempt_is_still_counted_by_default(tmp_path):
    """Two-sided: the census MUST keep counting auth deaths (Out of Scope)."""
    p = _b5_log(tmp_path)
    eng = _grp(foundry.gather_stage_times(str(p), team="demo"), "eng")
    assert eng["count"] == 1 and eng["timeouts"] == 1, eng
    assert ["auth", 1] in eng["kind_counts"], eng


def test_b5_rendered_output_is_identical_with_the_keyword_defaulted(tmp_path):
    p = _b5_log(tmp_path)
    plain = foundry.gather_stage_times(str(p), team="demo").render()
    explicit = foundry.gather_stage_times(str(p), team="demo",
                                          exclude_kinds=None).render()
    assert plain == explicit, (plain, explicit)


def test_b5_the_cli_output_is_byte_identical_with_and_without_an_auth_row(tmp_path):
    """The CLI never opts in, so its JSON matches the unfiltered summary exactly."""
    p = _b5_log(tmp_path)
    rc, out, _err = _run_cli(["stage-times", "--log", str(p), "--team", "demo",
                              "--json"])
    assert rc in (0, 1, 2), rc
    payload = json.loads(out)
    assert payload == foundry.gather_stage_times(str(p), team="demo").to_dict(), out


# ========================================================================== #
# Behavior 6 -- the opt-in filter, applied per group and AFTER the team filter
# ========================================================================== #
def _b6_log(tmp_path):
    """`s1`: 4 no-output auth attempts at 3s + 1 produced at 600s.
    `s2`: 2 produced attempts at 500s, no auth attempt.
    Plus a FOREIGN team whose auth attempts land on both stage labels."""
    rows = [("demo", i + 1, "s1", 3, False, TAIL_AUTH) for i in range(4)]
    rows.append(("demo", 5, "s1", 600, True, None))
    rows += [("demo", 6, "s2", 500, True, None), ("demo", 7, "s2", 500, True, None)]
    rows += [("other", 8, "s1", 3, False, TAIL_AUTH),
             ("other", 9, "s2", 3, False, TAIL_AUTH)]
    return _log(tmp_path, rows)


def test_b6_the_auth_population_is_dropped_from_the_noisy_stage(tmp_path):
    p = _b6_log(tmp_path)
    filtered = foundry.gather_stage_times(str(p), team="demo", exclude_kinds=(AUTH,))
    s1 = _grp(filtered, "s1")
    assert s1["count"] == 1, s1
    assert s1["median_s"] == 600, s1


def test_b6_the_unfiltered_view_of_the_same_log_still_shows_the_bimodal_median(tmp_path):
    """Two-sided control: without the keyword the median is the 3s auth mode."""
    p = _b6_log(tmp_path)
    s1 = _grp(foundry.gather_stage_times(str(p), team="demo"), "s1")
    assert s1["count"] == 5, s1
    assert s1["median_s"] == 3, s1


def test_b6_the_auth_free_stage_is_reported_identically(tmp_path):
    p = _b6_log(tmp_path)
    plain = _grp(foundry.gather_stage_times(str(p), team="demo"), "s2")
    filtered = _grp(foundry.gather_stage_times(str(p), team="demo",
                                              exclude_kinds=(AUTH,)), "s2")
    assert filtered == plain, (plain, filtered)


def test_b6_the_filter_runs_after_the_team_filter(tmp_path):
    """The foreign team's auth rows share both stage labels; they may not appear in,
    nor influence, either group of the filtered per-team view."""
    p = _b6_log(tmp_path)
    filtered = foundry.gather_stage_times(str(p), team="demo", exclude_kinds=(AUTH,))
    teams = {g["team"] for g in filtered.to_dict()["groups"]}
    assert teams == {"demo"}, teams
    assert _grp(filtered, "s1")["count"] == 1
    assert _grp(filtered, "s2")["count"] == 2
    # ...and the foreign team, asked for on its own, is untouched by the same call.
    other = foundry.gather_stage_times(str(p), team="other", exclude_kinds=(AUTH,))
    assert {g["team"] for g in other.to_dict()["groups"]} == {"other"}


def test_b6_an_all_auth_TEAM_is_reported_identically_via_the_blackout(tmp_path):
    """Behavior 3 seen through the public seam.  The guard is GLOBAL over the helper's
    INPUT -- which at this seam is the team's whole attempt list -- so when every
    attempt the team logged is a credential loss the filtered view is byte-identical
    to the unfiltered one and no stage is lost."""
    rows = [("demo", 1, "a", 3, False, TAIL_AUTH), ("demo", 2, "a", 3, False, TAIL_AUTH),
            ("demo", 3, "b", 5, False, TAIL_AUTH)]
    p = _log(tmp_path, rows)
    plain = foundry.gather_stage_times(str(p), team="demo").to_dict()
    filtered = foundry.gather_stage_times(str(p), team="demo",
                                          exclude_kinds=(AUTH,)).to_dict()
    assert filtered == plain, json.dumps([plain, filtered])
    assert {g["stage"] for g in filtered["groups"]} == {"a", "b"}, filtered["groups"]


def test_b6_an_all_auth_STAGE_leaves_the_census_when_another_stage_worked(tmp_path):
    """The MEASURED consequence of filtering the population UPSTREAM of the grouping
    (spec design contract 3): the guard is global, NOT per (team, stage), so a stage
    whose every windowed attempt is a credential loss drops out of the group census
    entirely rather than being reported with zero worked attempts.  Two-sided and
    pinned here because it is a semantic the spec does not name -- reported as PM
    feedback for a successor, not as a failure of any Expected Behavior."""
    rows = [("demo", 1, "dead", 3, False, TAIL_AUTH),
            ("demo", 2, "dead", 3, False, TAIL_AUTH),
            ("demo", 3, "alive", 500, True, None)]
    p = _log(tmp_path, rows)
    plain = foundry.gather_stage_times(str(p), team="demo")
    filtered = foundry.gather_stage_times(str(p), team="demo", exclude_kinds=(AUTH,))
    assert {g["stage"] for g in plain.to_dict()["groups"]} == {"alive", "dead"}
    assert {g["stage"] for g in filtered.to_dict()["groups"]} == {"alive"}
    # ...and the surviving stage's own numbers are untouched by the deletion.
    assert _grp(filtered, "alive") == _grp(plain, "alive")


def test_b6_only_the_excluded_kind_is_dropped_and_a_timeout_stays_in(tmp_path):
    """Out of Scope pins `timeout` IN: a timeout at the cap is the signal itself."""
    rows = [("demo", 1, "mix", 3, False, TAIL_AUTH),
            ("demo", 2, "mix", 600, False, TAIL_TIMEOUT),
            ("demo", 3, "mix", 600, True, None)]
    p = _log(tmp_path, rows)
    mix = _grp(foundry.gather_stage_times(str(p), team="demo",
                                          exclude_kinds=(AUTH,)), "mix")
    assert mix["count"] == 2, mix
    assert mix["median_s"] == 600, mix
    assert ["timeout", 1] in mix["kind_counts"], mix


# ========================================================================== #
# Behavior 7 -- stage_budget_line opts in; the CLI does not
# ========================================================================== #
def _spy_seam(monkeypatch):
    """Record every kwargs dict the seam is called with, keeping real behavior."""
    calls = []
    real = foundry.gather_stage_times

    def spy(*a, **kw):
        calls.append(dict(kw))
        return real(*a, **kw)

    monkeypatch.setattr(foundry, SEAM, spy)
    return calls


def test_b7_stage_budget_line_forwards_the_module_global(tmp_path, monkeypatch):
    p = _b6_log(tmp_path)
    calls = _spy_seam(monkeypatch)
    foundry.stage_budget_line(_cfg(), log_path=p)
    assert calls, "stage_budget_line did not reach the gather seam"
    assert calls[-1].get("exclude_kinds") == foundry.STAGE_BUDGET_EXCLUDED_KINDS, \
        calls[-1]


def test_b7_the_global_is_read_at_call_time_not_captured_at_def_time(tmp_path,
                                                                    monkeypatch):
    p = _b6_log(tmp_path)
    calls = _spy_seam(monkeypatch)
    foundry.stage_budget_line(_cfg(), log_path=p)
    first = calls[-1].get("exclude_kinds")
    monkeypatch.setattr(foundry, CONST_NAME, ("timeout",))
    foundry.stage_budget_line(_cfg(), log_path=p)
    assert calls[-1].get("exclude_kinds") == ("timeout",), calls[-1]
    assert first != ("timeout",), first


def test_b7_the_stage_times_cli_forwards_no_exclude_kinds(tmp_path, monkeypatch):
    p = _b6_log(tmp_path)
    calls = _spy_seam(monkeypatch)
    rc, _out, _err = _run_cli(["stage-times", "--log", str(p), "--json"])
    assert rc in (0, 1, 2), rc
    assert calls, "the CLI did not reach the gather seam"
    assert calls[-1].get("exclude_kinds") is None, calls[-1]


def test_b7_the_line_still_carries_its_prefix_when_the_seam_is_scripted(tmp_path,
                                                                       monkeypatch):
    """The opt-in must not change the line's SHAPE: one prefixed line, no newline."""
    p = _b6_log(tmp_path)
    _spy_seam(monkeypatch)
    line = foundry.stage_budget_line(_cfg(), log_path=p)
    assert line.startswith(foundry.STAGE_BUDGET_PREFIX), line
    assert "\n" not in line, line


def test_b7_a_patched_empty_global_is_forwarded_verbatim(tmp_path, monkeypatch):
    """An operator emptying the tuple must reach the seam as the no-op, not vanish."""
    p = _b6_log(tmp_path)
    calls = _spy_seam(monkeypatch)
    monkeypatch.setattr(foundry, CONST_NAME, ())
    foundry.stage_budget_line(_cfg(), log_path=p)
    assert calls[-1].get("exclude_kinds") == (), calls[-1]


# ========================================================================== #
# Behavior 8 -- the constant is pinned to the shipped failure-kind vocabulary
# ========================================================================== #
def test_b8_excluded_kinds_is_a_non_empty_tuple_of_strings():
    ks = getattr(foundry, CONST_NAME)
    assert isinstance(ks, tuple), type(ks)
    assert ks, "the filter must not ship empty"
    assert all(isinstance(k, str) for k in ks), ks


def test_b8_excluded_kinds_equals_the_auth_loss_kind():
    assert getattr(foundry, CONST_NAME) == (foundry.AUTH_LOSS_KIND,), \
        getattr(foundry, CONST_NAME)


def test_b8_every_member_is_a_shipped_failure_kind():
    shipped = {kind for kind, _needles in foundry.ATTEMPT_FAILURE_MARKERS}
    for k in getattr(foundry, CONST_NAME):
        assert k in shipped, (k, sorted(shipped))


def test_b8_the_constant_is_not_the_generic_default_kind():
    """`other` is the fallback bucket; excluding it would blind the gauge."""
    assert foundry.ATTEMPT_FAILURE_DEFAULT not in getattr(foundry, CONST_NAME)


def test_b8_the_helper_and_the_constant_are_public_module_names():
    for name in (CONST_NAME, HELPER_NAME):
        assert hasattr(foundry, name), name
    assert callable(getattr(foundry, HELPER_NAME))


# ========================================================================== #
# Behavior 9 -- end-to-end, two-sided, on the real shape
# ========================================================================== #
def _b9_log(tmp_path):
    """`slow_a`: 40 no-output auth attempts at 3s + 10 produced at 600s.
    `slow_b`: 10 produced attempts at 601s."""
    rows = [("demo", 1 + (i % 20), "slow_a", 3, False, TAIL_AUTH) for i in range(40)]
    rows += [("demo", 1 + i, "slow_a", 600, True, None) for i in range(10)]
    rows += [("demo", 1 + i, "slow_b", 601, True, None) for i in range(10)]
    return _log(tmp_path, rows)


def test_b9_the_filter_makes_both_stages_near_the_wall(tmp_path):
    line = foundry.stage_budget_line(_cfg(), log_path=_b9_log(tmp_path))
    assert line.startswith(foundry.STAGE_BUDGET_PREFIX), line
    assert foundry.STAGE_BUDGET_WARN in line, line
    assert "2/2 stage(s)" in line, line
    assert "slow_b" in line, line


def test_b9_without_the_filter_only_one_stage_is_near_the_wall(tmp_path,
                                                              monkeypatch):
    monkeypatch.setattr(foundry, CONST_NAME, ())
    line = foundry.stage_budget_line(_cfg(), log_path=_b9_log(tmp_path))
    assert "1/2 stage(s)" in line, line
    assert "slow_b" in line, line


def test_b9_the_two_runs_differ_so_the_test_is_not_a_tautology(tmp_path,
                                                               monkeypatch):
    p = _b9_log(tmp_path)
    live = foundry.stage_budget_line(_cfg(), log_path=p)
    monkeypatch.setattr(foundry, CONST_NAME, ())
    off = foundry.stage_budget_line(_cfg(), log_path=p)
    assert live != off, live
    assert live.replace("2/2", "N/2") == off.replace("1/2", "N/2"), (live, off)


def test_b9_the_named_worst_stage_and_its_headroom_do_not_move(tmp_path,
                                                               monkeypatch):
    """The gauge's HEADLINE is unchanged by the filter here; only the census of
    stages near the wall moves.  That is the spec's own two-sided prediction."""
    p = _b9_log(tmp_path)
    live = foundry.stage_budget_line(_cfg(), log_path=p)
    assert "601.0s median" in live, live
    assert "-1.0s headroom" in live, live
    monkeypatch.setattr(foundry, CONST_NAME, ())
    off = foundry.stage_budget_line(_cfg(), log_path=p)
    assert "601.0s median" in off and "-1.0s headroom" in off, off


def test_b9_the_hidden_stage_median_is_the_real_one_under_the_filter(tmp_path):
    """The same log, read through the seam: `slow_a`'s median is 600s, not 3s."""
    p = _b9_log(tmp_path)
    filtered = _grp(foundry.gather_stage_times(str(p), team="demo",
                                               exclude_kinds=(AUTH,)), "slow_a")
    plain = _grp(foundry.gather_stage_times(str(p), team="demo"), "slow_a")
    assert filtered["median_s"] == 600, filtered
    assert plain["median_s"] == 3, plain
    assert plain["count"] - filtered["count"] == 40, (plain, filtered)


def test_b9_the_line_is_total_for_a_missing_log_with_the_filter_live(tmp_path):
    line = foundry.stage_budget_line(_cfg(), log_path=tmp_path / "absent.out")
    assert line.startswith(foundry.STAGE_BUDGET_PREFIX), line
    assert "\n" not in line, line


# ========================================================================== #
# Acceptance guards -- import safety, resume safety, purity
# ========================================================================== #
def test_acceptance_both_modules_import_cleanly():
    assert foundry.__name__ == "foundry" and dispatcher.__name__ == "dispatcher"


@pytest.mark.parametrize("fname", RESUME_CRITICAL)
def test_acceptance_the_control_path_never_learns_the_new_names(fname):
    fn = getattr(foundry, fname, None)
    if fn is None:
        pytest.skip("%s is not a module-level function in this build" % fname)
    seen = _fn_names(fn)
    for forbidden in (CONST_NAME, HELPER_NAME):
        assert forbidden not in seen, (fname, forbidden)


def test_acceptance_dispatcher_does_not_expose_the_new_names():
    for forbidden in (CONST_NAME, HELPER_NAME):
        assert forbidden not in dir(dispatcher), forbidden


def test_acceptance_the_helper_touches_no_filesystem(tmp_path):
    before = sorted(q.name for q in tmp_path.iterdir())
    _drop([_Row(AUTH), _Row("timeout")], (AUTH,))
    assert sorted(q.name for q in tmp_path.iterdir()) == before


def test_acceptance_the_seam_keyword_is_optional_in_the_signature():
    import inspect
    sig = inspect.signature(foundry.gather_stage_times)
    param = sig.parameters.get("exclude_kinds")
    assert param is not None, sorted(sig.parameters)
    assert param.default is None, param.default
    assert param.kind is inspect.Parameter.KEYWORD_ONLY, param.kind


# ========================================================================== #
# EXTENSIONS -- tester-retry round (iteration 369, second tester attempt)
#
# The first round's file covered Expected Behaviors 1-9 and the Acceptance list.
# Everything below closes gaps that round did not reach, each one MEASURED on the
# live tree through the public names before it was written down:
#   * behavior 4's "any iterable" against the shapes that fail SILENTLY -- a
#     one-shot iterator, a mapping, and bytes;
#   * behavior 6 against the LIMIT WINDOW, whose side of the filter the spec's
#     design contract 3 does not fix;
#   * the filter's effect in the RENDERED view and in the soft-budget verdict,
#     not only in `to_dict()`;
#   * the two population-DELETION semantics (all-teams view, total blackout)
#     that decide whether the filter can ever blind the gauge.
# ========================================================================== #


# -- behavior 4, the iterable shapes that would fail silently ---------------- #
def test_b4_a_one_shot_iterator_of_kinds_filters_every_row():
    """A GENERATOR must not be exhausted by the first row.  A lazily consumed `kinds`
    would drop row 1 and silently KEEP every later auth row -- the failure shape that
    looks green in a two-row fixture, so the fixture here carries three auth rows at
    positions 1, 2 and 4."""
    rows = [_Row(AUTH), _Row(AUTH), _Row("timeout"), _Row(AUTH), _Row("")]
    kept = _drop(rows, (k for k in (AUTH,)))
    assert [r.kind for r in kept] == ["timeout", ""], [r.kind for r in kept]
    again = _drop(rows, iter([AUTH]))
    assert [r.kind for r in again] == ["timeout", ""], [r.kind for r in again]


def test_b4_a_mapping_of_kinds_matches_on_its_keys():
    """A dict is an iterable of its KEYS, so behavior 4's "any iterable" includes it."""
    rows = [_Row(AUTH), _Row("timeout"), _Row("")]
    kept = _drop(rows, {AUTH: "excluded-because-it-is-a-machine-fact"})
    assert [r.kind for r in kept] == ["timeout", ""], [r.kind for r in kept]


def test_b4_a_bytes_kinds_is_total_and_matches_nothing():
    """`bytes` / `bytearray` iterate as INTS, so no `str` kind can ever match them.
    Behavior 4's totality then means the call returns every row rather than raising --
    the same observable as behavior 2's no-op, reached by a different route."""
    rows = [_Row(AUTH), _Row("timeout")]
    for kinds in (AUTH.encode("ascii"), bytearray(AUTH.encode("ascii"))):
        kept = _drop(rows, kinds)
        assert [r.kind for r in kept] == [AUTH, "timeout"], (kinds, kept)


# -- behavior 6 against the LIMIT window ------------------------------------- #
def _b6_window_log(tmp_path):
    """The 4 OLDEST iterations worked (600s each); the 6 NEWEST are credential deaths
    at 3s.  A window narrower than 7 therefore holds auth attempts ONLY."""
    rows = [("demo", i, "s1", 600, True, None) for i in range(1, 5)]
    rows += [("demo", i, "s1", 3, False, TAIL_AUTH) for i in range(5, 11)]
    return _log(tmp_path, rows)


@pytest.mark.parametrize("limit", [None, 3, 6, 10])
def test_b6_the_filter_never_grows_the_population_at_any_window(tmp_path, limit):
    """Reading-INDEPENDENT invariant: whichever side of the window the filter sits on,
    it may only ever remove rows, it may never invent one, and any row it did remove
    must be gone from `kind_counts` too.  The median rises rather than falls because in
    THIS fixture the excluded rows are the fastest ones."""
    p = _b6_window_log(tmp_path)
    plain = _grp(foundry.gather_stage_times(str(p), team="demo", limit=limit), "s1")
    filtered = _grp(foundry.gather_stage_times(str(p), team="demo", limit=limit,
                                               exclude_kinds=(AUTH,)), "s1")
    assert filtered is not None and plain is not None, (plain, filtered)
    assert filtered["count"] <= plain["count"], (limit, plain, filtered)
    assert filtered["median_s"] >= plain["median_s"], (limit, plain, filtered)
    if filtered["count"] < plain["count"]:
        assert AUTH not in {k for k, _n in filtered["kind_counts"]}, filtered


def test_b6_the_window_runs_before_the_filter_so_the_guard_fires_inside_it(tmp_path):
    """MEASURED semantic the spec does not name.  Design contract 3 places the filter
    "AFTER the existing team filter and BEFORE `summarize_stage_times`", which leaves
    the LIMIT window's side of it unspecified -- and the two readings are different
    features.  Measured order is window-THEN-filter: with `limit=3` the window holds
    nothing but credential deaths, behavior 3's blackout guard fires INSIDE that window
    and the filtered view is byte-identical to the unfiltered one (median stays 3s).
    Filter-first would instead have windowed the 3 most-recent WORKED attempts and
    reported 600s.  With the window open the same log filters to the 4 worked attempts.
    Pinned two-sided so moving the call site is loud rather than silent."""
    p = _b6_window_log(tmp_path)
    narrow_plain = _grp(foundry.gather_stage_times(str(p), team="demo", limit=3), "s1")
    narrow_filt = _grp(foundry.gather_stage_times(str(p), team="demo", limit=3,
                                                 exclude_kinds=(AUTH,)), "s1")
    assert narrow_filt == narrow_plain, (narrow_plain, narrow_filt)
    assert narrow_filt["median_s"] == 3, narrow_filt
    assert [AUTH, 3] in narrow_filt["kind_counts"], narrow_filt
    wide = _grp(foundry.gather_stage_times(str(p), team="demo",
                                           exclude_kinds=(AUTH,)), "s1")
    assert (wide["count"], wide["median_s"]) == (4, 600), wide


# -- the filter is visible in the RENDERED view and in the verdict ----------- #
def test_b6_the_renderer_reports_the_worked_median_under_the_filter(tmp_path):
    """`to_dict()` is not the only observable: once the credential deaths stop holding
    `s1`'s median down, the bimodal stage earns its OWN soft-budget WARN line in the
    human render, and the auth-free stage's WARN is unchanged."""
    p = _b6_log(tmp_path)
    plain = foundry.gather_stage_times(str(p), team="demo").render()
    filtered = foundry.gather_stage_times(str(p), team="demo",
                                          exclude_kinds=(AUTH,)).render()
    warn_plain = [ln for ln in plain.splitlines() if "WARN" in ln]
    warn_filt = [ln for ln in filtered.splitlines() if "WARN" in ln]
    assert len(warn_filt) == len(warn_plain) + 1, (warn_plain, warn_filt)
    gained = [ln for ln in warn_filt if ln not in warn_plain]
    assert len(gained) == 1 and "s1" in gained[0], gained
    assert all("s2" in ln for ln in warn_plain), warn_plain


def test_b6_the_soft_budget_verdict_flips_for_the_bimodal_stage(tmp_path):
    """The gauge-relevant consequence in one group: `s1` is UNDER the soft budget while
    its 4 credential deaths are counted and OVER it once they are not."""
    p = _b6_log(tmp_path)
    plain = _grp(foundry.gather_stage_times(str(p), team="demo"), "s1")
    filtered = _grp(foundry.gather_stage_times(str(p), team="demo",
                                               exclude_kinds=(AUTH,)), "s1")
    assert plain["over_budget"] is False, plain
    assert filtered["over_budget"] is True, filtered
    assert (plain["timeouts"], filtered["timeouts"]) == (4, 0), (plain, filtered)


# -- the two population-DELETION semantics ---------------------------------- #
def test_b6_an_all_auth_TEAM_vanishes_from_the_ALL_TEAMS_view(tmp_path):
    """The team-scoped escalation of the first round's finding 1, MEASURED here: with
    no `team` argument there is no team filter to run first, so the blackout guard is
    evaluated over EVERY team at once.  A team whose whole population is credential
    deaths is therefore deleted from the all-teams census while another team's worked
    rows survive.  No shipped caller opts in without a team (behavior 7 pins the gauge
    passing one and the CLI passing none), so this is PM feedback for a successor, not
    a failure of any Expected Behavior -- pinned both ways so a change is loud."""
    p = _b6_log(tmp_path)

    def _proj(summary):
        return [(g["team"], g["stage"], g["count"], g["median_s"])
                for g in summary.to_dict()["groups"]]

    plain = _proj(foundry.gather_stage_times(str(p)))
    filtered = _proj(foundry.gather_stage_times(str(p), exclude_kinds=(AUTH,)))
    assert ("other", "s1", 1, 3) in plain and ("other", "s2", 1, 3) in plain, plain
    assert {row[0] for row in filtered} == {"demo"}, filtered
    # ...and what survives is exactly the per-team filtered view of the survivor.
    assert filtered == _proj(foundry.gather_stage_times(str(p), team="demo",
                                                        exclude_kinds=(AUTH,))), filtered


def test_b9_a_total_credential_blackout_reports_the_SAME_line_as_the_filter_off(
        tmp_path, monkeypatch):
    """The failure mode this feature could plausibly have introduced: the filter
    BLINDING the gauge.  When every attempt in the window is a credential loss on every
    stage, behavior 3's guard keeps the whole population, so the emitted line is
    byte-identical to the filter-off line and the census is never emptied."""
    rows = [("demo", i, "dead", 3, False, TAIL_AUTH) for i in range(1, 11)]
    rows += [("demo", i, "dead2", 5, False, TAIL_AUTH) for i in range(11, 15)]
    p = _log(tmp_path, rows)
    live = foundry.stage_budget_line(_cfg(), log_path=p)
    monkeypatch.setattr(foundry, CONST_NAME, ())
    off = foundry.stage_budget_line(_cfg(), log_path=p)
    assert live == off, (live, off)
    assert live.startswith(foundry.STAGE_BUDGET_PREFIX), live
    assert "0/2" in live, live
