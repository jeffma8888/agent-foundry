"""Black-box behaviour tests for iter 117 -- `foundry stage-times`.

A read-only, offline observability CLI that parses the shared `dispatcher.out`
log into per-(team,stage) attempt DURATIONS (count / median / max / no-output
count) and WARNs on any stage whose median exceeds a patchable
`STAGE_SOFT_BUDGET` (default 420s), so a creeping stage is flagged days before it
hard-fails at the ~600s agent-CLI cap.

Public surface under test (module-level in foundry.py):
  * STAGE_SOFT_BUDGET                      (int const, default 420, read at call time)
  * parse_stage_attempts(text) -> list     (pure; each item exposes
        team/iteration/stage/attempt/duration_s/produced)
  * summarize_stage_times(attempts, *, budget=None) -> summary
        (.exit_code / .render() / .to_dict())
  * gather_stage_times(log_path, *, budget=None, team=None) -> summary
  * CLI `foundry stage-times [--log P] [--team N] [--budget K] [--json]`
        dispatched via foundry.main(...) BEFORE load_config.

ISOLATION CONTRACT (HONORED, original tester deliverable): every check below was
derived ONLY from the iter-117 PM spec's Expected Behaviors (1-10), the existing
tests/ conventions (esp. tests/test_iter115_behavior.py for the CLI-drive +
compiled-bytecode dormancy helpers), the product README command index, and the
product's OWN observable behaviour by driving its PUBLIC interface. The
implementation SOURCE of foundry.py, the engineer's/reviewer's notes, and
`git diff` were NOT read. Fixtures are hand-built `dispatcher.out` text strings;
zero real subprocess/git/network (except the fresh-import regression probe, which
only imports the two modules). Source is pure-ASCII: the U+00B7 middot separator
emitted by log() is constructed via an escape, never embedded.
"""
import io
import json
import pathlib
import subprocess
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]
README = REPO / "README.md"

# The MIDDLE DOT (U+00B7) separator emitted by log(); built, never embedded, so
# this source file stays pure-ASCII bytes.
MID = "\u00b7"

# names the spec's Acceptance Criteria pin firmly (Behaviors 1/2/5/7 + AC list).
NEW_SYMBOLS = (
    "STAGE_SOFT_BUDGET",
    "parse_stage_attempts",
    "summarize_stage_times",
    "gather_stage_times",
)
ORCHESTRATORS = ("run_iteration", "run_stage")


# --------------------------------------------------------------------------
# fixture builders -- emit the three EXACT dispatcher.out line shapes (Behavior 2)
# --------------------------------------------------------------------------
def _start(ts, team, it, stage, attempt):
    return f"- `{ts}` [{team}] iter {it} {MID} **{stage}** attempt {attempt} started"


def _produced(ts, team, it, stage, fname="out.md"):
    return f"- `{ts}` [{team}] iter {it} {MID} {stage} produced `{fname}`"


def _nooutput(ts, team, it, stage, attempt, maxa=4):
    return (f"- `{ts}` [{team}] iter {it} {MID} {stage} "
            f"no output file (attempt {attempt}/{maxa}); retrying")


def _mk(*lines):
    return "\n".join(lines) + "\n"


def _run_cli(argv):
    """Drive foundry.main capturing (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _fn_names_consts(fn):
    """Compiled-bytecode introspection (co_names/co_consts), NOT source text --
    honors the tester isolation firewall (see tests/test_iter115_behavior.py)."""
    stack, seen = [fn.__code__], set()
    names, consts = set(), set()
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names |= set(code.co_names)
        for c in code.co_consts:
            if isinstance(c, str):
                consts.add(c)
            elif isinstance(c, types.CodeType):
                stack.append(c)
    return names, consts


def _groups(summary):
    """The per-group dict list, taken from the documented .to_dict() surface."""
    return summary.to_dict()["groups"]


def _grp(summary, team, stage):
    for g in _groups(summary):
        if g["team"] == team and g["stage"] == stage:
            return g
    return None


# ==========================================================================
# Behavior 1 -- STAGE_SOFT_BUDGET module constant (default 420, read at call time)
# ==========================================================================
def test_b1_stage_soft_budget_default_is_420_int():
    assert hasattr(foundry, "STAGE_SOFT_BUDGET")
    assert isinstance(foundry.STAGE_SOFT_BUDGET, int)
    assert foundry.STAGE_SOFT_BUDGET == 420


def test_b1_budget_read_at_call_time(monkeypatch):
    # a 60s attempt: over budget only if the soft budget drops below 60.
    text = _mk(_start("08-05 01:00:00", "z", 1, "pm", 1),
               _produced("08-05 01:01:00", "z", 1, "pm"))
    atts = foundry.parse_stage_attempts(text)
    monkeypatch.setattr(foundry, "STAGE_SOFT_BUDGET", 10)
    assert _grp(foundry.summarize_stage_times(atts), "z", "pm")["over_budget"] is True
    monkeypatch.setattr(foundry, "STAGE_SOFT_BUDGET", 10000)
    assert _grp(foundry.summarize_stage_times(atts), "z", "pm")["over_budget"] is False


# ==========================================================================
# Behavior 2 -- pure parser: three line shapes + exposed fields
# ==========================================================================
def test_b2_parse_produced_attempt_fields():
    text = _mk(_start("08-05 10:00:00", "alpha", 7, "engineer", 1),
               _produced("08-05 10:09:00", "alpha", 7, "engineer", "engineer.md"))
    atts = foundry.parse_stage_attempts(text)
    assert len(atts) == 1
    a = atts[0]
    assert a.team == "alpha"
    assert a.iteration == 7 and isinstance(a.iteration, int)
    assert a.stage == "engineer"
    assert a.attempt == 1 and isinstance(a.attempt, int)
    assert a.duration_s == 540 and isinstance(a.duration_s, int)
    assert a.produced is True


def test_b2_parse_no_output_attempt_is_produced_false():
    text = _mk(_start("08-05 11:00:00", "beta", 3, "pm", 1),
               _nooutput("08-05 11:10:00", "beta", 3, "pm", 1))
    atts = foundry.parse_stage_attempts(text)
    assert len(atts) == 1
    assert atts[0].produced is False
    assert atts[0].duration_s == 600


def test_b2_attempts_returned_in_first_seen_order():
    text = _mk(
        _start("08-05 10:00:00", "alpha", 1, "pm", 1),
        _produced("08-05 10:01:00", "alpha", 1, "pm"),
        _start("08-05 10:02:00", "alpha", 1, "engineer", 1),
        _produced("08-05 10:03:00", "alpha", 1, "engineer"),
    )
    atts = foundry.parse_stage_attempts(text)
    assert [a.stage for a in atts] == ["pm", "engineer"]


# ==========================================================================
# Behavior 3 -- pairing / duration / retries / dangling / midnight
# ==========================================================================
def test_b3_duration_is_whole_seconds():
    text = _mk(_start("08-05 09:00:00", "t", 1, "s", 1),
               _produced("08-05 09:07:30", "t", 1, "s"))
    assert foundry.parse_stage_attempts(text)[0].duration_s == 450


def test_b3_retry_yields_two_ordered_attempts():
    text = _mk(
        _start("08-05 11:00:00", "alpha", 1, "engineer", 1),
        _nooutput("08-05 11:10:00", "alpha", 1, "engineer", 1),
        _start("08-05 11:10:30", "alpha", 1, "engineer", 2),
        _produced("08-05 11:17:30", "alpha", 1, "engineer"),
    )
    atts = foundry.parse_stage_attempts(text)
    assert len(atts) == 2
    assert (atts[0].attempt, atts[0].produced, atts[0].duration_s) == (1, False, 600)
    assert (atts[1].attempt, atts[1].produced, atts[1].duration_s) == (2, True, 420)


def test_b3_start_without_terminal_yields_no_attempt():
    text = _mk(_start("08-05 12:00:00", "alpha", 1, "tester", 1))  # in-flight
    assert foundry.parse_stage_attempts(text) == []


def test_b3_terminal_without_start_is_ignored():
    text = _mk(_produced("08-05 13:00:00", "beta", 1, "final"))
    assert foundry.parse_stage_attempts(text) == []


def test_b3_midnight_cross_never_negative():
    # terminal time-of-day earlier than start -> +86400 once -> 300s, never < 0.
    text = _mk(_start("08-05 23:59:00", "beta", 1, "pm", 1),
               _produced("08-05 00:04:00", "beta", 1, "pm"))
    a = foundry.parse_stage_attempts(text)[0]
    assert a.duration_s >= 0
    assert a.duration_s == 300


def test_b3_pairs_next_terminal_for_same_key_when_interleaved():
    # two teams' pm stages interleaved: each start pairs with its OWN terminal.
    text = _mk(
        _start("08-05 01:00:00", "alpha", 1, "pm", 1),
        _start("08-05 01:00:10", "beta", 1, "pm", 1),
        _produced("08-05 01:05:00", "beta", 1, "pm"),   # beta: 290s
        _produced("08-05 01:10:00", "alpha", 1, "pm"),  # alpha: 600s
    )
    atts = foundry.parse_stage_attempts(text)
    by = {a.team: a.duration_s for a in atts}
    assert by == {"alpha": 600, "beta": 290}


# ==========================================================================
# Behavior 4 -- robustness: never raises for any input
# ==========================================================================
@pytest.mark.parametrize("bad", [
    "",
    "   \n\t  \n",
    "just some unrelated log text\nno timestamps here",
    "- `08-05 10:00:00` [x] iter NaN " + MID + " **pm** attempt 1 started",
    "- `08-05 10:00:00` [x] iter 1 " + MID + " **pm** attempt Q started",
    "- `garbled` [x] iter 1 " + MID + " **pm** attempt 1 started",
    "- `08-05 10:00:00` [x] iter 1 " + MID + " **pm** attempt",
    "- [x] iter 1 " + MID + " pm produced `f`",
])
def test_b4_parser_never_raises(bad):
    result = foundry.parse_stage_attempts(bad)
    assert isinstance(result, list)


# ==========================================================================
# Behavior 5 -- pure summariser: grouping + metrics + effective budget
# ==========================================================================
def _summ_metrics_fixture():
    # alpha/pm: 3 attempts durations 300,420,600 (odd -> median 420, all produced)
    # alpha/engineer: 2 attempts 600(noout),420(produced) (even -> median 510)
    return _mk(
        _start("08-05 01:00:00", "alpha", 1, "pm", 1),
        _produced("08-05 01:05:00", "alpha", 1, "pm"),           # 300
        _start("08-05 02:00:00", "alpha", 2, "pm", 1),
        _produced("08-05 02:07:00", "alpha", 2, "pm"),           # 420
        _start("08-05 03:00:00", "alpha", 3, "pm", 1),
        _produced("08-05 03:10:00", "alpha", 3, "pm"),           # 600
        _start("08-05 04:00:00", "alpha", 4, "engineer", 1),
        _nooutput("08-05 04:10:00", "alpha", 4, "engineer", 1),  # 600 noout
        _start("08-05 04:11:00", "alpha", 4, "engineer", 2),
        _produced("08-05 04:18:00", "alpha", 4, "engineer"),     # 420
    )


def test_b5_group_metrics_count_median_max_timeouts():
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(_summ_metrics_fixture()))
    pm = _grp(s, "alpha", "pm")
    assert pm["count"] == 3
    assert pm["median_s"] == 420   # odd -> middle value
    assert pm["max_s"] == 600
    assert pm["timeouts"] == 0
    eng = _grp(s, "alpha", "engineer")
    assert eng["count"] == 2
    assert eng["median_s"] == 510  # even -> mean of two middle (600,420)
    assert eng["max_s"] == 600
    assert eng["timeouts"] == 1


def test_b5_median_even_count_is_mean_of_two_middle():
    # durations 100,200,300,500 -> median 250
    text = _mk(
        _start("08-05 00:00:00", "g", 1, "eng", 1), _produced("08-05 00:01:40", "g", 1, "eng"),
        _start("08-05 01:00:00", "g", 2, "eng", 1), _produced("08-05 01:03:20", "g", 2, "eng"),
        _start("08-05 02:00:00", "g", 3, "eng", 1), _produced("08-05 02:05:00", "g", 3, "eng"),
        _start("08-05 03:00:00", "g", 4, "eng", 1), _produced("08-05 03:08:20", "g", 4, "eng"),
    )
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(text))
    assert _grp(s, "g", "eng")["median_s"] == 250


def test_b5_explicit_budget_overrides_and_default_reads_constant(monkeypatch):
    text = _mk(_start("08-05 01:00:00", "z", 1, "pm", 1),   # 300s
               _produced("08-05 01:05:00", "z", 1, "pm"))
    atts = foundry.parse_stage_attempts(text)
    # explicit budget wins over the module constant
    assert _grp(foundry.summarize_stage_times(atts, budget=100), "z", "pm")["over_budget"] is True
    assert _grp(foundry.summarize_stage_times(atts, budget=999), "z", "pm")["over_budget"] is False
    assert foundry.summarize_stage_times(atts, budget=999).to_dict()["budget"] == 999
    # default (budget=None) reads STAGE_SOFT_BUDGET at call time
    monkeypatch.setattr(foundry, "STAGE_SOFT_BUDGET", 250)
    assert _grp(foundry.summarize_stage_times(atts), "z", "pm")["over_budget"] is True
    assert foundry.summarize_stage_times(atts).to_dict()["budget"] == 250


def test_b5_groups_ordered_by_team_stage_ascending():
    text = _mk(
        _start("08-05 05:00:00", "beta", 1, "pm", 1), _produced("08-05 05:01:00", "beta", 1, "pm"),
        _start("08-05 01:00:00", "alpha", 1, "pm", 1), _produced("08-05 01:01:00", "alpha", 1, "pm"),
        _start("08-05 02:00:00", "alpha", 1, "engineer", 1), _produced("08-05 02:01:00", "alpha", 1, "engineer"),
    )
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(text))
    order = [(g["team"], g["stage"]) for g in _groups(s)]
    assert order == [("alpha", "engineer"), ("alpha", "pm"), ("beta", "pm")]


# ==========================================================================
# Behavior 6 -- summary object: exit_code, render, to_dict
# ==========================================================================
def test_b6_exit_code_2_when_no_attempts():
    s = foundry.summarize_stage_times([])
    assert s.exit_code == 2


def test_b6_exit_code_1_when_at_least_one_over_budget():
    # 600s attempt, default budget 420 -> over budget
    text = _mk(_start("08-05 01:00:00", "z", 1, "pm", 1),
               _produced("08-05 01:10:00", "z", 1, "pm"))
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(text))
    assert _grp(s, "z", "pm")["over_budget"] is True
    assert s.exit_code == 1


def test_b6_exit_code_0_when_data_and_none_over_budget():
    text = _mk(_start("08-05 01:00:00", "z", 1, "pm", 1),
               _produced("08-05 01:01:00", "z", 1, "pm"))  # 60s < 420
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(text))
    assert s.exit_code == 0


def test_b6_render_header_and_per_group_lines():
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(_summ_metrics_fixture()))
    out = s.render()
    assert "foundry stage-times" in out
    lines = out.splitlines()
    # a line for each (team,stage) group naming team+stage
    assert any("alpha" in ln and "pm" in ln for ln in lines)
    assert any("alpha" in ln and "engineer" in ln for ln in lines)


def test_b6_render_warn_line_per_over_budget_group():
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(_summ_metrics_fixture()))
    warn = [ln for ln in s.render().splitlines() if "WARN" in ln]
    # alpha/pm (median 420) is NOT over 420; alpha/engineer (median 510) IS.
    assert any("engineer" in ln and "alpha" in ln for ln in warn)
    assert all("pm" not in ln for ln in warn)  # pm median 420 not > 420
    # the effective budget appears in a WARN line
    assert any("420" in ln for ln in warn)


def test_b6_render_no_stage_timings_when_empty():
    s = foundry.summarize_stage_times([])
    assert "no stage timings" in s.render()


def test_b6_to_dict_roundtrips_and_carries_keys():
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(_summ_metrics_fixture()))
    d = s.to_dict()
    assert json.loads(json.dumps(d)) == d          # JSON-native round-trip
    assert d["budget"] == foundry.STAGE_SOFT_BUDGET  # effective budget recorded
    for g in d["groups"]:
        assert set(g) >= {"team", "stage", "count", "median_s",
                          "max_s", "timeouts", "over_budget"}


# ==========================================================================
# Behavior 7 -- gather seam: reads file, --team filter, degrades on missing path
# ==========================================================================
def test_b7_gather_reads_and_summarizes(tmp_path):
    p = tmp_path / "dispatcher.out"
    p.write_text(_mk(_start("08-05 01:00:00", "alpha", 1, "pm", 1),
                     _produced("08-05 01:10:00", "alpha", 1, "pm")))
    s = foundry.gather_stage_times(str(p))
    assert _grp(s, "alpha", "pm")["max_s"] == 600


def test_b7_gather_team_filter(tmp_path):
    p = tmp_path / "dispatcher.out"
    p.write_text(_mk(
        _start("08-05 01:00:00", "alpha", 1, "pm", 1), _produced("08-05 01:10:00", "alpha", 1, "pm"),
        _start("08-05 02:00:00", "beta", 1, "pm", 1), _produced("08-05 02:10:00", "beta", 1, "pm"),
    ))
    both = [(g["team"], g["stage"]) for g in _groups(foundry.gather_stage_times(str(p)))]
    only = [(g["team"], g["stage"]) for g in _groups(foundry.gather_stage_times(str(p), team="alpha"))]
    assert both == [("alpha", "pm"), ("beta", "pm")]
    assert only == [("alpha", "pm")]


def test_b7_gather_missing_path_is_empty_and_never_raises(tmp_path):
    s = foundry.gather_stage_times(str(tmp_path / "does_not_exist.out"))
    assert s.exit_code == 2
    assert "no stage timings" in s.render()


# ==========================================================================
# Behavior 8 -- CLI foundry stage-times (dispatched before load_config)
# ==========================================================================
def _cli_log(tmp_path):
    p = tmp_path / "dispatcher.out"
    p.write_text(_mk(
        _start("08-05 01:00:00", "alpha", 1, "pm", 1), _produced("08-05 01:10:00", "alpha", 1, "pm"),
        _start("08-05 02:00:00", "beta", 1, "pm", 1), _produced("08-05 02:10:00", "beta", 1, "pm"),
    ))
    return p


def test_b8_cli_prints_report_and_returns_exit_code(tmp_path):
    p = _cli_log(tmp_path)
    rc, out, _ = _run_cli(["stage-times", "--log", str(p)])
    assert rc == 1  # both pm groups median 600 > 420
    assert "foundry stage-times" in out
    assert "WARN" in out


def test_b8_cli_json_emits_one_json_document(tmp_path):
    p = _cli_log(tmp_path)
    rc, out, _ = _run_cli(["stage-times", "--log", str(p), "--json"])
    doc = json.loads(out)  # parses as a single JSON document
    assert rc == 1
    assert doc["exit_code"] == 1
    assert {g["team"] for g in doc["groups"]} == {"alpha", "beta"}


def test_b8_cli_team_filter(tmp_path):
    p = _cli_log(tmp_path)
    rc, out, _ = _run_cli(["stage-times", "--log", str(p), "--team", "alpha", "--json"])
    doc = json.loads(out)
    assert {g["team"] for g in doc["groups"]} == {"alpha"}


def test_b8_cli_budget_override(tmp_path):
    p = _cli_log(tmp_path)
    # a huge budget makes nothing over-budget -> exit 0
    rc, _, _ = _run_cli(["stage-times", "--log", str(p), "--budget", "5000"])
    assert rc == 0


def test_b8_cli_missing_log_exit_2_no_stage_timings(tmp_path):
    rc, out, _ = _run_cli(["stage-times", "--log", str(tmp_path / "nope.out")])
    assert rc == 2
    assert "no stage timings" in out


def test_b8_cli_needs_no_config(tmp_path):
    # dispatched BEFORE load_config: must not error about a missing --config.
    rc, out, err = _run_cli(["stage-times", "--log", str(tmp_path / "nope.out")])
    assert rc == 2
    assert "config" not in (out + err).lower()


# ==========================================================================
# Behavior 9 -- README command index gains entry `# 42.` for stage-times
# ==========================================================================
def test_b9_readme_has_stage_times_index_entry():
    text = README.read_text(encoding="utf-8", errors="replace")
    assert "# 42." in text, "README command index is missing the `# 42.` entry"
    assert "stage-times" in text, "README does not mention the `stage-times` verb"
    # the `# 42.` heading itself must be the stage-times entry, with an example line
    lines = text.splitlines()
    heads = [i for i, ln in enumerate(lines) if ln.strip().startswith("# 42.")]
    assert heads, "no `# 42.` command-index heading found"
    block = "\n".join(lines[heads[0]:heads[0] + 3])
    assert "stage-times" in block, "`# 42.` heading is not the stage-times entry"
    assert "foundry.py stage-times" in text, "README lacks a `foundry.py stage-times` example"


# ==========================================================================
# Behavior 10 -- importable + additive-dormant (no control-path call site)
# ==========================================================================
def test_b10_both_modules_still_import():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(REPO), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_b10_new_symbols_absent_from_orchestrators():
    for fn_name in ORCHESTRATORS:
        fn = getattr(foundry, fn_name)
        assert callable(fn), f"orchestrator foundry.{fn_name} missing (regression)"
        names, consts = _fn_names_consts(fn)
        for sym in NEW_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references {sym!r} -- must stay OFF the control path"
        assert "stage-times" not in consts, \
            f"{fn_name} contains the 'stage-times' subcommand literal"


def test_b10_new_symbols_absent_from_dispatcher():
    names = set()
    for v in vars(dispatcher).values():
        if isinstance(v, types.FunctionType):
            names |= _fn_names_consts(v)[0]
        elif isinstance(v, type):
            for m in vars(v).values():
                if isinstance(m, types.FunctionType):
                    names |= _fn_names_consts(m)[0]
    for sym in NEW_SYMBOLS:
        assert sym not in names, f"dispatcher references new symbol {sym!r}"
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
