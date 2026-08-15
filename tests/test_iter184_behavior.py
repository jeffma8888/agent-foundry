"""Iteration 184 -- BLACK-BOX behavior tests: windowed stage-times.

Spec under test (products/_platform/state/iter-184/pm.md):
  1. positive `limit` windows gather_stage_times by the N highest DISTINCT iterations
  2. unwindowed default unchanged (None / 0 / -3 all == today)
  3. the window is applied AFTER the team filter
  4. StageTimesSummary.to_dict() carries a JSON-native "limit" key
  5. render() states the window and never mislabels it
  6. `--limit` is routable and typed; passed through by BARE module name
  7. stage_budget_line(cfg, log_path=..., limit=N) honors the window
  8. doctor windows the line from a call-time-read STAGE_BUDGET_RECENT_ITERATIONS
  9. stage_budget_line stays TOTAL on every degenerate path

ISOLATION: written from pm.md + the repo's tests/ conventions ONLY.  No
implementation source, no engineer/reviewer notes, no `git diff` was read.

OFFLINE + FRESH-CLONE SAFE: every assertion uses a tmp_path fixture log or an
explicit log_path.  Nothing reads the gitignored real dispatcher.out, and
nothing asserts on the ambient repo tree.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

THIS_ITER = 184

# The MIDDLE DOT (U+00B7) dispatcher's log() emits; BUILT, never embedded, so
# this source file stays pure-ASCII bytes (iter-117 convention).
MID = "\u00b7"


def _start(ts, team, it, stage, attempt=1):
    return f"- `{ts}` [{team}] iter {it} {MID} **{stage}** attempt {attempt} started"


def _produced(ts, team, it, stage, fname="out.md"):
    return f"- `{ts}` [{team}] iter {it} {MID} {stage} produced `{fname}`"


def _log(tmp_path, spec, name="dispatcher.out"):
    """Build a fixture dispatcher log from (team, iteration, stage, seconds) rows."""
    lines = []
    for team, it, stage, dur in spec:
        hour = 1 + (it % 20)
        lines.append(_start(f"08-05 {hour:02d}:00:00", team, it, stage))
        lines.append(
            _produced(f"08-05 {hour:02d}:{dur // 60:02d}:{dur % 60:02d}", team, it, stage)
        )
    p = pathlib.Path(tmp_path) / name
    p.write_text("\n".join(lines) + "\n")
    return p


def _cfg(**over):
    kw = dict(name="demo", repo="/no/such/repo", allowed_push_repo="demo")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _five(tmp_path, stage="pm", team="alpha", name="dispatcher.out"):
    """One stage, iterations 1..5, each 60s -- the plain windowing fixture."""
    return _log(tmp_path, [(team, i, stage, 60) for i in (1, 2, 3, 4, 5)], name=name)


def _skew(tmp_path, team="demo", stage="engineer"):
    """OLD iterations fast (60s), NEWEST TWO slow (500s) -- behavior 7's fixture."""
    return _log(
        tmp_path,
        [(team, 1, stage, 60), (team, 2, stage, 60), (team, 3, stage, 60),
         (team, 4, stage, 500), (team, 5, stage, 500)],
    )


# ---------------------------------------------------------------- behavior 1

def test_b1_positive_limit_windows_by_iteration_number(tmp_path):
    """limit=2 over iterations 1..5 keeps exactly the attempts from 4 and 5."""
    p = _five(tmp_path)
    s = foundry.gather_stage_times(str(p), limit=2)
    groups = s.to_dict()["groups"]
    assert len(groups) == 1, groups
    assert groups[0]["count"] == 2, groups[0]


def test_b1_windowed_median_and_max_come_from_the_window_only(tmp_path):
    """The N highest iterations are slow; the window must report THEIR numbers."""
    p = _skew(tmp_path, team="alpha")
    s = foundry.gather_stage_times(str(p), limit=2)
    g = s.to_dict()["groups"][0]
    assert g["count"] == 2, g
    assert g["median_s"] == 500, g
    assert g["max_s"] == 500, g
    # ...and the unwindowed view of the SAME log still sees all five.
    allg = foundry.gather_stage_times(str(p)).to_dict()["groups"][0]
    assert allg["count"] == 5, allg
    assert allg["median_s"] == 60, allg


def test_b1_window_counts_distinct_iterations_not_attempts(tmp_path):
    """Two attempts of iteration 5 are ONE distinct iteration, so limit=1 keeps both."""
    p = _log(tmp_path, [("alpha", 4, "pm", 60), ("alpha", 5, "pm", 60), ("alpha", 5, "pm", 90)])
    g = foundry.gather_stage_times(str(p), limit=1).to_dict()["groups"][0]
    assert g["count"] == 2, g


# ---------------------------------------------------------------- behavior 2

@pytest.mark.parametrize("kwargs", [{}, {"limit": None}, {"limit": 0}, {"limit": -3}])
def test_b2_non_positive_limits_are_all_the_unwindowed_default(tmp_path, kwargs):
    p = _five(tmp_path)
    base = foundry.gather_stage_times(str(p)).to_dict()
    got = foundry.gather_stage_times(str(p), **kwargs).to_dict()
    assert got["groups"] == base["groups"], (kwargs, got["groups"])
    assert got["budget"] == base["budget"], (kwargs, got["budget"])
    assert got["groups"][0]["count"] == 5, got["groups"][0]


def test_b2_unwindowed_limit_key_is_none_for_every_non_positive_form(tmp_path):
    p = _five(tmp_path)
    for kwargs in ({}, {"limit": None}, {"limit": 0}, {"limit": -3}):
        assert foundry.gather_stage_times(str(p), **kwargs).to_dict()["limit"] is None, kwargs


# ---------------------------------------------------------------- behavior 3

def test_b3_window_is_applied_after_the_team_filter(tmp_path):
    """alpha at 1,2 and beta at 8,9: team='alpha', limit=1 must keep alpha iter 2."""
    p = _log(tmp_path, [("alpha", 1, "pm", 60), ("alpha", 2, "pm", 120),
                        ("beta", 8, "pm", 60), ("beta", 9, "pm", 60)])
    groups = foundry.gather_stage_times(str(p), team="alpha", limit=1).to_dict()["groups"]
    assert len(groups) == 1, groups
    assert groups[0]["team"] == "alpha", groups[0]
    assert groups[0]["count"] == 1, groups[0]
    # iteration 2 is alpha's newest -- proves the window used alpha's OWN numbers,
    # not the log's global max (9), which would have emptied the digest.
    assert groups[0]["median_s"] == 120, groups[0]


# ---------------------------------------------------------------- behavior 4

def test_b4_to_dict_carries_limit_and_keeps_every_preexisting_key(tmp_path):
    p = _five(tmp_path)
    base = foundry.gather_stage_times(str(p)).to_dict()
    win = foundry.gather_stage_times(str(p), limit=2).to_dict()
    assert "limit" in base and "limit" in win
    assert base["limit"] is None
    assert win["limit"] == 2
    assert set(base) == set(win), (sorted(base), sorted(win))
    assert set(base["groups"][0]) == set(win["groups"][0])
    for key in ("budget", "groups", "total", "over_budget_count", "exit_code"):
        assert key in win, key


def test_b4_windowed_summary_is_json_round_trippable(tmp_path):
    d = foundry.gather_stage_times(str(_five(tmp_path)), limit=2).to_dict()
    assert json.loads(json.dumps(d)) == d


# ---------------------------------------------------------------- behavior 5

def test_b5_unwindowed_render_first_line_is_unchanged(tmp_path):
    first = foundry.gather_stage_times(str(_five(tmp_path))).render().splitlines()[0]
    assert "foundry stage-times" in first, first
    assert str(foundry.STAGE_SOFT_BUDGET) in first, first


def test_b5_windowed_render_states_window_and_distinct_count(tmp_path):
    p = _five(tmp_path)
    plain = foundry.gather_stage_times(str(p)).render()
    win = foundry.gather_stage_times(str(p), limit=2).render()
    first = win.splitlines()[0]
    assert "foundry stage-times" in first, first
    assert "2" in first, first
    assert win != plain
    assert first != plain.splitlines()[0]


def test_b5_render_does_not_overstate_a_window_larger_than_the_data(tmp_path):
    """limit=7 over 5 iterations must not claim 7 iterations were included."""
    first = foundry.gather_stage_times(str(_five(tmp_path)), limit=7).render().splitlines()[0]
    assert "5" in first, first


# ---------------------------------------------------------------- behavior 6

def test_b6_main_routes_limit_to_stage_times_cli(tmp_path, monkeypatch):
    seen = {}

    def recorder(*a, **kw):
        seen.update(kw)
        return 0

    monkeypatch.setattr(foundry, "stage_times_cli", recorder)
    p = _five(tmp_path)
    assert foundry.main(["stage-times", "--log", str(p), "--limit", "2"]) == 0
    assert seen.get("limit") == 2, seen


def test_b6_omitting_limit_passes_none(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(foundry, "stage_times_cli", lambda *a, **kw: (seen.update(kw), 0)[1])
    p = _five(tmp_path)
    assert foundry.main(["stage-times", "--log", str(p)]) == 0
    assert seen.get("limit", "<<MISSING>>") is None, seen


def test_b6_stage_times_cli_composes_gather_by_bare_module_name(tmp_path, monkeypatch, capsys):
    """monkeypatch.setattr(foundry, "gather_stage_times", ...) must be observed."""
    p = _five(tmp_path)
    real = foundry.gather_stage_times
    seen = {}

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(foundry, "gather_stage_times", spy)
    foundry.main(["stage-times", "--log", str(p), "--limit", "2"])
    capsys.readouterr()
    assert seen.get("limit") == 2, seen


def test_b6_non_integer_limit_exits_two(tmp_path):
    p = _five(tmp_path)
    with pytest.raises(SystemExit) as exc:
        foundry.main(["stage-times", "--log", str(p), "--limit", "abc"])
    assert exc.value.code == 2


# ---------------------------------------------------------------- behavior 7

def test_b7_windowed_budget_line_reports_higher_median_and_less_headroom(tmp_path):
    cfg = _cfg()
    p = _skew(tmp_path)
    plain = foundry.stage_budget_line(cfg, log_path=p)
    win = foundry.stage_budget_line(cfg, log_path=p, limit=2)
    assert plain.startswith(foundry.STAGE_BUDGET_PREFIX), plain
    assert win.startswith(foundry.STAGE_BUDGET_PREFIX), win
    assert "60.0s median" in plain, plain
    assert "500.0s median" in win, win
    assert "540.0s clear" in plain, plain
    assert "100.0s clear" in win, win
    assert win != plain


def test_b7_limit_none_reproduces_todays_line_byte_for_byte(tmp_path):
    cfg = _cfg()
    p = _skew(tmp_path)
    assert foundry.stage_budget_line(cfg, log_path=p, limit=None) == \
        foundry.stage_budget_line(cfg, log_path=p)


def test_b7_windowed_line_names_its_window_in_words(tmp_path):
    win = foundry.stage_budget_line(_cfg(), log_path=_skew(tmp_path), limit=2)
    assert "most-recent" in win, win
    assert "window 2" in win, win


# ---------------------------------------------------------------- behavior 8

def _stub_doctor_environment(monkeypatch):
    """Make run_doctor_cli offline: no power/agent/uv/remote/git probes."""
    class _Chk:
        def __init__(self, name, ok=True, detail="fine"):
            self.name, self.ok, self.detail = name, ok, detail

    factory = getattr(foundry, "Check", _Chk)
    for seam in ("check_power", "check_agent", "check_uv", "check_remote"):
        if hasattr(foundry, seam):
            monkeypatch.setattr(foundry, seam,
                                lambda *a, _s=seam, **k: factory(_s, True, "fine"))
    for seam in ("live_lag_line", "learnings_head_line", "roadmap_index_line"):
        if hasattr(foundry, seam):
            monkeypatch.setattr(foundry, seam, lambda *a, _s=seam, **k: f"{_s}: stub")


def test_b8_doctor_reads_the_window_constant_at_call_time(tmp_path, monkeypatch, capsys):
    assert isinstance(foundry.STAGE_BUDGET_RECENT_ITERATIONS, int)
    assert foundry.STAGE_BUDGET_RECENT_ITERATIONS > 0
    _stub_doctor_environment(monkeypatch)
    seen = []
    monkeypatch.setattr(foundry, "stage_budget_line",
                        lambda cfg, *a, **kw: (seen.append(kw), "stage-budget: SENTINEL")[1])
    monkeypatch.setattr(foundry, "STAGE_BUDGET_RECENT_ITERATIONS", 4)
    foundry.run_doctor_cli(_cfg(repo=str(tmp_path)))
    capsys.readouterr()
    assert seen and seen[0].get("limit") == 4, seen
    seen.clear()
    monkeypatch.setattr(foundry, "STAGE_BUDGET_RECENT_ITERATIONS", 9)
    foundry.run_doctor_cli(_cfg(repo=str(tmp_path)))
    capsys.readouterr()
    assert seen and seen[0].get("limit") == 9, seen


def test_b8_doctor_prints_a_line_that_names_its_window(tmp_path, monkeypatch, capsys):
    """The window doctor chooses reaches the REAL line-builder, and the printed
    line names it in words.

    doctor's default log location is not derivable from `cfg` (it is neither
    `cfg.repo`, `cfg.work_root` nor the cwd -- measured), and asserting on the
    ambient gitignored real `dispatcher.out` would not survive a fresh clone
    (the iter-154 trap).  So the ONLY seam substituted here redirects the log to
    a tmp fixture while forwarding doctor's own `limit` untouched -- the line
    itself is still built by the real implementation.
    """
    log = _skew(tmp_path)
    _stub_doctor_environment(monkeypatch)
    real_line = foundry.stage_budget_line

    def line_from_fixture(cfg, log_path=None, **kw):
        return real_line(cfg, log_path=log, **kw)

    monkeypatch.setattr(foundry, "stage_budget_line", line_from_fixture)
    monkeypatch.setattr(foundry, "STAGE_BUDGET_RECENT_ITERATIONS", 2)
    foundry.run_doctor_cli(_cfg(repo=str(tmp_path)))
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if foundry.STAGE_BUDGET_PREFIX in ln]
    assert len(lines) == 1, out
    assert "most-recent" in lines[0], lines[0]
    assert "window 2" in lines[0], lines[0]
    assert "500.0s median" in lines[0], lines[0]
    # ...and the unwindowed builder on the SAME log would have said 60.0s, so the
    # printed number really is the windowed one, not an all-time median.
    assert "60.0s median" not in lines[0], lines[0]


# ---------------------------------------------------------------- behavior 9

def _assert_total(line):
    assert isinstance(line, str)
    body = [ln for ln in line.splitlines() if ln.strip()]
    assert len(body) == 1, body
    assert body[0].startswith(foundry.STAGE_BUDGET_PREFIX), body[0]


def test_b9_missing_log_is_total(tmp_path):
    _assert_total(foundry.stage_budget_line(_cfg(), log_path=tmp_path / "nope.out", limit=3))


def test_b9_unparsable_text_is_total(tmp_path):
    junk = tmp_path / "junk.out"
    junk.write_text("total garbage\nnothing parsable here\n")
    _assert_total(foundry.stage_budget_line(_cfg(), log_path=junk, limit=3))


def test_b9_raising_gather_seam_is_total(tmp_path, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("seam blew up")

    monkeypatch.setattr(foundry, "gather_stage_times", boom)
    _assert_total(foundry.stage_budget_line(_cfg(), log_path=_skew(tmp_path), limit=3))


def test_b9_limit_larger_than_history_degrades_to_all_available_not_unknown(tmp_path):
    line = foundry.stage_budget_line(_cfg(), log_path=_skew(tmp_path), limit=99)
    _assert_total(line)
    assert "UNKNOWN" not in line, line
    assert "engineer" in line, line
    assert "all available" in line, line
    assert "60.0s median" in line, line


# -------------------------------------------------- resume-semantics dormancy

def _reachable_names(fn):
    import types as _t
    stack, seen, out = [fn.__code__], set(), set()
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        out |= set(code.co_names)
        for const in code.co_consts:
            if isinstance(const, _t.CodeType):
                stack.append(const)
    return out


@pytest.mark.parametrize("orchestrator", ["run_stage", "run_iteration", "build_prompt"])
def test_resume_path_never_references_the_new_window_machinery(orchestrator):
    """Acceptance: no call site in run_stage/run_iteration/build_prompt changed."""
    fn = getattr(foundry, orchestrator, None)
    if fn is None:
        pytest.skip(f"{orchestrator} absent")
    names = _reachable_names(fn)
    for forbidden in ("STAGE_BUDGET_RECENT_ITERATIONS", "gather_stage_times",
                      "stage_budget_line", "stage_times_cli"):
        assert forbidden not in names, (orchestrator, forbidden)


def test_modules_still_import():
    assert foundry is not None and dispatcher is not None
