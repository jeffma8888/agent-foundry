"""Black-box behaviour tests for iter 148 -- per-KIND attribution in `stage-times`.

Spec: products/_platform/state/iter-148/pm.md, Expected Behaviors 1-11.

  1.  `StageAttempt` gains a TRAILING `kind: str` field defaulting to `""`, so every
      pre-existing positional or keyword construction keeps working.
  2.  a `produced` terminal line parses to `kind == ""`.
  3.  a `no output file` terminal line takes its `kind` from
      `classify_attempt_failure`, invoked by BARE module name (a monkeypatch bites).
  4.  the four measured markers map to timeout / stalled / service / cli-error, and an
      UNMARKED no-output line falls back to `ATTEMPT_FAILURE_DEFAULT`.
  5.  `StageAttempt.to_dict()` carries `kind` and stays JSON-native.
  6.  `StageTimesGroup` gains a TRAILING `kind_counts: tuple[tuple[str, int], ...]`
      defaulting to `()`: ascending by kind, zero counts excluded, and
      `sum(counts) == timeouts` for every group.
  7.  `StageTimesGroup.to_dict()` emits `kind_counts` as a JSON-native array of
      `[kind, count]` pairs and the whole summary still round-trips through
      `json.loads(json.dumps(...))`.
  8.  `render()` keeps every pre-existing per-group substring AND adds a `kinds `
      fragment listing that group's `kind=count` pairs in ascending kind order.
  9.  a group with ZERO no-output attempts has `kind_counts == ()` and renders no
      `kinds ` fragment.
  10. purely additive: count / median_s / max_s / timeouts / over_budget / group
      ordering / total / over_budget_count / budget / exit_code are unchanged, and the
      empty-log report still says `no stage timings` with exit_code 2.
  11. totality preserved: `parse_stage_attempts` never raises and still returns the
      well-formed subset.

ISOLATION CONTRACT (HONORED): every check below was derived ONLY from the iter-148 PM
spec's Expected Behaviors, the pre-existing tests under `tests/` (chiefly
`tests/test_iter117_behavior.py` for the `dispatcher.out` line shapes and the
group/render/to_dict access conventions, and `tests/test_iter129_behavior.py` for the
four MEASURED failure-tail blobs), and the product's OWN observable behaviour by
driving its public interface. The implementation source of `foundry.py`, the
engineer's and reviewer's notes, and `git diff` were NOT read. All fixtures are
hand-built `dispatcher.out` text -- NEVER the live `dispatcher.out`, whose contents
change under a running loop. Zero subprocess/git/network except the two-module import
probe. Source is pure-ASCII: the U+00B7 separator emitted by log() is built from an
escape, never embedded.
"""
import dataclasses
import io
import json
import pathlib
import subprocess
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)

REPO = pathlib.Path(__file__).resolve().parents[1]

# The MIDDLE DOT (U+00B7) separator emitted by log(); built, never embedded, so this
# source file stays pure-ASCII bytes.
MID = "\u00b7"

# The four MEASURED failure-tail shapes (tests/test_iter129_behavior.py conventions);
# deliberately generic -- the real service tails name a vendor that is on the
# committed denylist for this public repo.
TAIL_TIMEOUT = "agent run failed: agent run timed out after 600s"
TAIL_STALLED = "Connection stalled -- no data received for 120 s"
TAIL_SERVICE = "upstream internal error ... The service is busy"
TAIL_CLI_ERROR = "the native shortcut did not match -- check syntax"

NEW_NAMES = ("kind_counts", "StageTimesGroup", "parse_stage_attempts",
             "summarize_stage_times")
ORCHESTRATORS = ("run_iteration", "run_stage")


# --------------------------------------------------------------------------
# fixture builders -- the EXACT dispatcher.out line shapes
# --------------------------------------------------------------------------
def _start(ts, team, it, stage, attempt):
    return f"- `{ts}` [{team}] iter {it} {MID} **{stage}** attempt {attempt} started"


def _produced(ts, team, it, stage, fname="out.md"):
    return f"- `{ts}` [{team}] iter {it} {MID} {stage} produced `{fname}`"


def _nooutput(ts, team, it, stage, attempt, tail=None, maxa=4):
    """A no-output terminal. With `tail`, the real shape that carries evidence;
    without it, the bare `; retrying` shape (no recognizable marker)."""
    base = (f"- `{ts}` [{team}] iter {it} {MID} {stage} "
            f"no output file (attempt {attempt}/{maxa})")
    return base + (f"; tail: '{tail}'" if tail else "; retrying")


def _mk(*lines):
    return "\n".join(lines) + "\n"


def _run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _groups(summary):
    return summary.to_dict()["groups"]


def _grp(summary, team, stage):
    for g in _groups(summary):
        if g["team"] == team and g["stage"] == stage:
            return g
    return None


def _obj_grp(summary, team, stage):
    """The GROUP OBJECT (for the declared tuple-typed field), not its dict."""
    for g in summary.groups:
        if g.team == team and g.stage == stage:
            return g
    return None


def _fn_names_consts(fn):
    """Compiled-bytecode introspection (co_names/co_consts), NOT source text --
    honors the tester isolation firewall (tests/test_iter115_behavior.py)."""
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


# The MIXED corpus: one clean group, one group holding all four markers plus one
# UNMARKED no-output line, and a second team. Reused by several behaviors.
def _mixed_fixture():
    return _mk(
        # alpha/pm -- 1 clean produced attempt (300s), ZERO no-output (Behavior 9)
        _start("08-05 01:00:00", "alpha", 1, "pm", 1),
        _produced("08-05 01:05:00", "alpha", 1, "pm", "pm.md"),
        # alpha/engineer -- 4 no-output attempts: timeout, stalled, service, UNMARKED
        _start("08-05 02:00:00", "alpha", 2, "engineer", 1),
        _nooutput("08-05 02:10:00", "alpha", 2, "engineer", 1, TAIL_TIMEOUT),
        _start("08-05 02:11:00", "alpha", 2, "engineer", 2),
        _nooutput("08-05 02:21:00", "alpha", 2, "engineer", 2, TAIL_STALLED),
        _start("08-05 02:22:00", "alpha", 2, "engineer", 3),
        _nooutput("08-05 02:32:00", "alpha", 2, "engineer", 3, TAIL_SERVICE),
        _start("08-05 02:33:00", "alpha", 2, "engineer", 4),
        _nooutput("08-05 02:43:00", "alpha", 2, "engineer", 4),          # unmarked
        # beta/tester -- 1 cli-error no-output
        _start("08-05 03:00:00", "beta", 1, "tester", 1),
        _nooutput("08-05 03:10:00", "beta", 1, "tester", 1, TAIL_CLI_ERROR),
    )


# ==========================================================================
# Behavior 1 -- StageAttempt gains a TRAILING `kind` field defaulting to ""
# ==========================================================================
def test_b1_kind_is_the_trailing_field_defaulting_to_empty():
    names = [f.name for f in dataclasses.fields(foundry.StageAttempt)]
    assert names[-1] == "kind", f"`kind` must be the TRAILING field, got {names}"
    fld = dataclasses.fields(foundry.StageAttempt)[-1]
    assert fld.default == "", f"`kind` default must be '' , got {fld.default!r}"


def test_b1_preexisting_positional_construction_still_works():
    # the 6-argument positional call every pre-148 caller could make
    a = foundry.StageAttempt("alpha", 7, "engineer", 1, 540, True)
    assert a.kind == ""
    assert (a.team, a.iteration, a.stage, a.attempt, a.duration_s, a.produced) == \
        ("alpha", 7, "engineer", 1, 540, True)


def test_b1_preexisting_keyword_construction_still_works():
    a = foundry.StageAttempt(team="beta", iteration=3, stage="pm", attempt=2,
                             duration_s=600, produced=False)
    assert a.kind == ""


def test_b1_kind_is_accepted_explicitly_and_group_stays_hashable():
    a = foundry.StageAttempt("t", 1, "s", 1, 10, False, "timeout")
    assert a.kind == "timeout"
    # a TUPLE-typed field (not a dict) keeps the frozen dataclasses hashable, so a
    # group/attempt can still go in a set -- the property a dict field would silently
    # remove. (Robustness reading of Behavior 6's declared tuple type.)
    assert isinstance(hash(a), int)
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(_mixed_fixture()))
    assert isinstance(hash(_obj_grp(s, "alpha", "engineer")), int)


# ==========================================================================
# Behavior 2 -- a produced terminal parses to kind == ""
# ==========================================================================
def test_b2_produced_attempt_kind_is_empty_string():
    text = _mk(_start("08-05 10:00:00", "alpha", 7, "engineer", 1),
               _produced("08-05 10:09:00", "alpha", 7, "engineer", "engineer.md"))
    atts = foundry.parse_stage_attempts(text)
    assert len(atts) == 1
    assert atts[0].produced is True
    assert atts[0].kind == ""


def test_b2_produced_kind_stays_empty_even_with_a_patched_classifier(monkeypatch):
    # Behavior 2 is unconditional: a produced attempt is not classified at all.
    monkeypatch.setattr(foundry, "classify_attempt_failure", lambda _b: "invented")
    text = _mk(_start("08-05 10:00:00", "alpha", 7, "pm", 1),
               _produced("08-05 10:01:00", "alpha", 7, "pm"))
    assert foundry.parse_stage_attempts(text)[0].kind == ""


# ==========================================================================
# Behavior 3 -- kind comes from classify_attempt_failure, called by BARE NAME
# ==========================================================================
def test_b3_patching_the_classifier_changes_the_parsed_kind(monkeypatch):
    text = _mk(_start("08-05 11:00:00", "beta", 3, "pm", 1),
               _nooutput("08-05 11:10:00", "beta", 3, "pm", 1, TAIL_TIMEOUT))
    # control: unpatched, the real classifier answers "timeout"
    assert foundry.parse_stage_attempts(text)[0].kind == "timeout"
    # the narrowing claim: the seam is a BARE module-name call, so a patch bites
    monkeypatch.setattr(foundry, "classify_attempt_failure", lambda _b: "invented")
    a = foundry.parse_stage_attempts(text)[0]
    assert a.kind == "invented", \
        "classify_attempt_failure must be invoked by BARE module name"
    assert a.produced is False and a.duration_s == 600  # nothing else moved


def test_b3_classifier_receives_the_line_remainder_carrying_the_tail_evidence(monkeypatch):
    seen = []

    def recording(blob):
        seen.append(blob)
        return "recorded"

    monkeypatch.setattr(foundry, "classify_attempt_failure", recording)
    text = _mk(_start("08-05 11:00:00", "beta", 3, "pm", 1),
               _nooutput("08-05 11:10:00", "beta", 3, "pm", 1, TAIL_SERVICE))
    assert foundry.parse_stage_attempts(text)[0].kind == "recorded"
    assert len(seen) == 1, f"classifier called {len(seen)} times, expected once"
    assert "The service is busy" in seen[0], \
        "the classified remainder must carry the line's tail evidence"


def test_b3_remainder_excludes_the_stage_name_prefix():
    """AMBIGUITY NOTE: Behavior 3 says "that line's remainder text" without fixing
    where the remainder starts. The reading tested here is the only one that is
    stable, because stage names come from a product's own config.json: a stage whose
    NAME contains a marker word must not classify its own failures by that word."""
    text = _mk(_start("08-05 12:00:00", "gamma", 1, "stalled-check", 1),
               _nooutput("08-05 12:10:00", "gamma", 1, "stalled-check", 1, TAIL_TIMEOUT))
    a = foundry.parse_stage_attempts(text)[0]
    assert a.stage == "stalled-check"
    assert a.kind == "timeout", \
        "a marker word in the STAGE NAME must not drive the classification"


# ==========================================================================
# Behavior 4 -- the four measured markers, plus the unmarked fallback
# ==========================================================================
@pytest.mark.parametrize("tail,expected", [
    (TAIL_TIMEOUT, "timeout"),
    (TAIL_STALLED, "stalled"),
    (TAIL_SERVICE, "service"),
    (TAIL_CLI_ERROR, "cli-error"),
])
def test_b4_marker_tails_parse_to_their_kind(tail, expected):
    text = _mk(_start("08-05 01:00:00", "t", 1, "s", 1),
               _nooutput("08-05 01:10:00", "t", 1, "s", 1, tail))
    assert foundry.parse_stage_attempts(text)[0].kind == expected


def test_b4_unmarked_no_output_line_falls_back_to_the_default_kind():
    assert foundry.ATTEMPT_FAILURE_DEFAULT, "ATTEMPT_FAILURE_DEFAULT must be non-empty"
    text = _mk(_start("08-05 01:00:00", "t", 1, "s", 1),
               _nooutput("08-05 01:10:00", "t", 1, "s", 1))  # bare `; retrying`
    a = foundry.parse_stage_attempts(text)[0]
    assert a.produced is False
    assert a.kind == foundry.ATTEMPT_FAILURE_DEFAULT


def test_b4_all_four_kinds_plus_default_appear_in_one_corpus():
    """POSITIVE CONTROL for the whole iteration: a dead classifier, or a `kind` that
    is never populated, would make every narrowing check below vacuous."""
    atts = foundry.parse_stage_attempts(_mixed_fixture())
    failed = [a for a in atts if not a.produced]
    assert len(failed) == 5, f"fixture must hold 5 no-output attempts, got {len(failed)}"
    kinds = {a.kind for a in failed}
    assert kinds == {"timeout", "stalled", "service", "cli-error",
                     foundry.ATTEMPT_FAILURE_DEFAULT}, kinds
    assert len(kinds) >= 2, "at least two DISTINCT kinds must be present"
    assert all(a.kind == "" for a in atts if a.produced)


# ==========================================================================
# Behavior 5 -- StageAttempt.to_dict() carries `kind` and stays JSON-native
# ==========================================================================
def test_b5_attempt_to_dict_has_kind_and_roundtrips():
    text = _mk(_start("08-05 01:00:00", "t", 1, "s", 1),
               _nooutput("08-05 01:10:00", "t", 1, "s", 1, TAIL_STALLED))
    d = foundry.parse_stage_attempts(text)[0].to_dict()
    assert "kind" in d
    assert d["kind"] == "stalled"
    assert json.loads(json.dumps(d)) == d
    # pre-existing keys survive (superset check, iter-117 convention)
    assert set(d) >= {"team", "iteration", "stage", "attempt", "duration_s", "produced"}


def test_b5_produced_attempt_to_dict_kind_is_empty():
    text = _mk(_start("08-05 01:00:00", "t", 1, "s", 1),
               _produced("08-05 01:05:00", "t", 1, "s"))
    assert foundry.parse_stage_attempts(text)[0].to_dict()["kind"] == ""


# ==========================================================================
# Behavior 6 -- StageTimesGroup.kind_counts: trailing tuple, ascending, exact cover
# ==========================================================================
def test_b6_kind_counts_is_the_trailing_field_defaulting_to_empty_tuple():
    names = [f.name for f in dataclasses.fields(foundry.StageTimesGroup)]
    assert names[-1] == "kind_counts", \
        f"`kind_counts` must be the TRAILING field, got {names}"
    assert dataclasses.fields(foundry.StageTimesGroup)[-1].default == ()


def test_b6_preexisting_group_construction_still_works():
    g = foundry.StageTimesGroup("alpha", "pm", 3, 420.0, 600, 1, False)
    assert g.kind_counts == ()


def test_b6_kind_counts_ascending_zero_counts_excluded_and_covers_the_group():
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(_mixed_fixture()))
    eng = _obj_grp(s, "alpha", "engineer")
    assert isinstance(eng.kind_counts, tuple)
    # exactly the group's own no-output attempts: 1 each of 4 distinct kinds,
    # ASCENDING by kind name, with no zero-count entry for the absent `cli-error`
    assert eng.kind_counts == (("other", 1), ("service", 1),
                               ("stalled", 1), ("timeout", 1))
    assert [k for k, _c in eng.kind_counts] == sorted(k for k, _c in eng.kind_counts)
    assert all(c > 0 for _k, c in eng.kind_counts), "zero counts must be excluded"
    assert "cli-error" not in dict(eng.kind_counts), \
        "a kind absent from THIS group must not appear (it is beta/tester's)"


def test_b6_sum_of_kind_counts_equals_timeouts_for_every_group():
    """Narrowing claim + its positive control in ONE block: the per-group tally must
    account for exactly the no-output attempts, and the corpus must actually hold
    more than one distinct kind (else a dead tally would pass vacuously)."""
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(_mixed_fixture()))
    seen_kinds, total_counted = set(), 0
    for g in s.groups:
        assert sum(c for _k, c in g.kind_counts) == g.timeouts, \
            f"[{g.team}] {g.stage}: kind_counts {g.kind_counts} != timeouts {g.timeouts}"
        seen_kinds |= {k for k, _c in g.kind_counts}
        total_counted += sum(c for _k, c in g.kind_counts)
    assert total_counted == 5, "the fixture's 5 no-output attempts must all be counted"
    assert len(seen_kinds) >= 2, "at least two DISTINCT kinds with count > 0"


def test_b6_repeated_kind_accumulates_into_one_entry():
    text = _mk(
        _start("08-05 01:00:00", "t", 1, "engineer", 1),
        _nooutput("08-05 01:10:00", "t", 1, "engineer", 1, TAIL_TIMEOUT),
        _start("08-05 01:11:00", "t", 1, "engineer", 2),
        _nooutput("08-05 01:21:00", "t", 1, "engineer", 2, TAIL_TIMEOUT),
        _start("08-05 01:22:00", "t", 1, "engineer", 3),
        _nooutput("08-05 01:32:00", "t", 1, "engineer", 3, TAIL_STALLED),
    )
    g = _obj_grp(foundry.summarize_stage_times(foundry.parse_stage_attempts(text)),
                 "t", "engineer")
    assert g.kind_counts == (("stalled", 1), ("timeout", 2))
    assert sum(c for _k, c in g.kind_counts) == g.timeouts == 3


def test_b6_kind_counts_are_per_group_not_fleet_wide():
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(_mixed_fixture()))
    assert _obj_grp(s, "beta", "tester").kind_counts == (("cli-error", 1),)


# ==========================================================================
# Behavior 7 -- to_dict emits JSON-native [kind, count] pairs and round-trips
# ==========================================================================
def test_b7_group_to_dict_kind_counts_is_a_json_native_pair_array():
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(_mixed_fixture()))
    eng = _grp(s, "alpha", "engineer")
    assert "kind_counts" in eng
    kc = eng["kind_counts"]
    assert isinstance(kc, list), f"kind_counts must be a LIST, got {type(kc).__name__}"
    for pair in kc:
        assert isinstance(pair, list) and len(pair) == 2, f"bad pair {pair!r}"
        assert isinstance(pair[0], str) and isinstance(pair[1], int)
    assert kc == [["other", 1], ["service", 1], ["stalled", 1], ["timeout", 1]]


def test_b7_whole_summary_to_dict_still_roundtrips_through_json():
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(_mixed_fixture()))
    d = s.to_dict()
    # tuples would survive dumps->loads as LISTS and break this equality
    assert json.loads(json.dumps(d)) == d
    # and the pre-existing per-group key set is still a subset (iter-117 stays green)
    for g in d["groups"]:
        assert set(g) >= {"team", "stage", "count", "median_s", "max_s",
                          "timeouts", "over_budget", "kind_counts"}


def test_b7_kind_counts_reaches_the_cli_json_document(tmp_path):
    p = tmp_path / "dispatcher.out"
    p.write_text(_mixed_fixture(), encoding="utf-8")
    rc, out, _ = _run_cli(["stage-times", "--log", str(p), "--json"])
    doc = json.loads(out)
    assert rc == doc["exit_code"]
    by = {(g["team"], g["stage"]): g["kind_counts"] for g in doc["groups"]}
    assert by[("alpha", "engineer")] == [["other", 1], ["service", 1],
                                        ["stalled", 1], ["timeout", 1]]
    assert by[("beta", "tester")] == [["cli-error", 1]]
    assert by[("alpha", "pm")] == []


# ==========================================================================
# Behavior 8 -- render keeps every old substring and adds the `kinds ` fragment
# ==========================================================================
def _group_line(rendered, team, stage):
    for ln in rendered.splitlines():
        if "WARN" in ln:
            continue
        if f"[{team}]" in ln and stage in ln:
            return ln
    return None


def test_b8_render_group_line_keeps_the_preexisting_substrings():
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(_mixed_fixture()))
    out = s.render()
    assert "foundry stage-times" in out
    for team, stage in [("alpha", "engineer"), ("alpha", "pm"), ("beta", "tester")]:
        ln = _group_line(out, team, stage)
        assert ln is not None, f"no rendered line for [{team}] {stage}"
        for token in ("count", "median", "max", "timeouts"):
            assert token in ln, f"[{team}] {stage} line lost the {token!r} substring"


def test_b8_render_adds_kinds_fragment_with_ascending_pairs():
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(_mixed_fixture()))
    out = s.render()
    ln = _group_line(out, "alpha", "engineer")
    assert "kinds " in ln, f"missing `kinds ` fragment: {ln!r}"
    frag = ln.split("kinds ", 1)[1]
    positions = []
    for kind, count in (("other", 1), ("service", 1), ("stalled", 1), ("timeout", 1)):
        token = f"{kind}={count}"
        assert token in frag, f"render lost {token!r}: {frag!r}"
        positions.append(frag.index(token))
    assert positions == sorted(positions), \
        f"`kind=count` pairs must be ASCENDING by kind name: {frag!r}"
    # the tally rendered must be the group's own tally
    assert "cli-error" not in frag


def test_b8_every_group_with_no_output_attempts_renders_a_kinds_fragment():
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(_mixed_fixture()))
    out = s.render()
    for g in s.groups:
        ln = _group_line(out, g.team, g.stage)
        if g.timeouts:
            assert "kinds " in ln, f"[{g.team}] {g.stage} has {g.timeouts} no-output " \
                                   f"attempts but no `kinds ` fragment"
        else:
            assert "kinds " not in ln


def test_b8_render_kind_fragment_reaches_the_cli_text_report(tmp_path):
    p = tmp_path / "dispatcher.out"
    p.write_text(_mixed_fixture(), encoding="utf-8")
    _rc, out, _ = _run_cli(["stage-times", "--log", str(p)])
    assert "kinds " in out
    assert "timeout=1" in out and "cli-error=1" in out


# ==========================================================================
# Behavior 9 -- a clean group has () and renders no `kinds ` fragment
# ==========================================================================
def test_b9_clean_group_has_empty_kind_counts_and_no_kinds_fragment():
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(_mixed_fixture()))
    pm = _obj_grp(s, "alpha", "pm")
    assert pm.timeouts == 0
    assert pm.kind_counts == ()
    assert _grp(s, "alpha", "pm")["kind_counts"] == []
    assert "kinds " not in _group_line(s.render(), "alpha", "pm")


def test_b9_all_clean_corpus_renders_no_kinds_anywhere():
    text = _mk(_start("08-05 01:00:00", "z", 1, "pm", 1),
               _produced("08-05 01:01:00", "z", 1, "pm"))
    s = foundry.summarize_stage_times(foundry.parse_stage_attempts(text))
    assert "kinds " not in s.render()
    assert all(g.kind_counts == () for g in s.groups)


# ==========================================================================
# Behavior 10 -- purely additive: every pre-existing number is unchanged
# ==========================================================================
def _iter117_metrics_fixture():
    """The iter-117 metrics fixture VERBATIM: alpha/pm 300,420,600 (median 420, 0
    no-output); alpha/engineer 600(no-output),420 (median 510, 1 no-output)."""
    return _mk(
        _start("08-05 01:00:00", "alpha", 1, "pm", 1),
        _produced("08-05 01:05:00", "alpha", 1, "pm"),
        _start("08-05 02:00:00", "alpha", 2, "pm", 1),
        _produced("08-05 02:07:00", "alpha", 2, "pm"),
        _start("08-05 03:00:00", "alpha", 3, "pm", 1),
        _produced("08-05 03:10:00", "alpha", 3, "pm"),
        _start("08-05 04:00:00", "alpha", 4, "engineer", 1),
        _nooutput("08-05 04:10:00", "alpha", 4, "engineer", 1),
        _start("08-05 04:11:00", "alpha", 4, "engineer", 2),
        _produced("08-05 04:18:00", "alpha", 4, "engineer"),
    )


def test_b10_preexisting_group_metrics_are_byte_for_byte_the_iter117_values():
    s = foundry.summarize_stage_times(
        foundry.parse_stage_attempts(_iter117_metrics_fixture()))
    pm, eng = _grp(s, "alpha", "pm"), _grp(s, "alpha", "engineer")
    assert (pm["count"], pm["median_s"], pm["max_s"], pm["timeouts"],
            pm["over_budget"]) == (3, 420, 600, 0, False)
    assert (eng["count"], eng["median_s"], eng["max_s"], eng["timeouts"],
            eng["over_budget"]) == (2, 510, 600, 1, True)


def test_b10_summary_level_numbers_and_group_ordering_unchanged():
    s = foundry.summarize_stage_times(
        foundry.parse_stage_attempts(_iter117_metrics_fixture()))
    d = s.to_dict()
    assert [(g["team"], g["stage"]) for g in d["groups"]] == \
        [("alpha", "engineer"), ("alpha", "pm")]     # ascending team, then stage
    assert d["total"] == 5
    assert d["over_budget_count"] == 1
    assert d["budget"] == foundry.STAGE_SOFT_BUDGET == 420
    assert d["exit_code"] == 1 == s.exit_code


def test_b10_empty_log_report_unchanged():
    s = foundry.summarize_stage_times([])
    assert s.exit_code == 2
    assert "no stage timings" in s.render()
    assert s.to_dict()["groups"] == []


def test_b10_budget_is_still_read_at_call_time(monkeypatch):
    text = _mk(_start("08-05 01:00:00", "z", 1, "pm", 1),
               _produced("08-05 01:01:00", "z", 1, "pm"))          # 60s
    atts = foundry.parse_stage_attempts(text)
    monkeypatch.setattr(foundry, "STAGE_SOFT_BUDGET", 10)
    assert _grp(foundry.summarize_stage_times(atts), "z", "pm")["over_budget"] is True
    assert foundry.summarize_stage_times(atts, budget=999).to_dict()["budget"] == 999


def test_b10_report_stays_off_the_control_path():
    for fn_name in ORCHESTRATORS:
        fn = getattr(foundry, fn_name)
        names, _consts = _fn_names_consts(fn)
        for sym in NEW_NAMES:
            assert sym not in names, \
                f"{fn_name} references {sym!r} -- the report must stay OFF the control path"
    dnames = set()
    for v in vars(dispatcher).values():
        if isinstance(v, types.FunctionType):
            dnames |= _fn_names_consts(v)[0]
        elif isinstance(v, type):
            for m in vars(v).values():
                if isinstance(m, types.FunctionType):
                    dnames |= _fn_names_consts(m)[0]
    for sym in NEW_NAMES:
        assert sym not in dnames, f"dispatcher references {sym!r}"


def test_b10_both_modules_still_import():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(REPO), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ==========================================================================
# Behavior 11 -- totality: never raises, still returns the well-formed subset
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
    # NEW shapes this iteration can meet: a truncated tail, an empty tail, and a
    # no-output terminal with no start to pair against.
    "- `08-05 10:00:00` [x] iter 1 " + MID + " pm no output file (attempt 1/4); tail: '",
    "- `08-05 10:00:00` [x] iter 1 " + MID + " pm no output file (attempt 1/4); tail: ''",
    "- `08-05 10:00:00` [x] iter 1 " + MID + " pm no output file",
])
def test_b11_parser_never_raises(bad):
    result = foundry.parse_stage_attempts(bad)
    assert isinstance(result, list)
    assert all(isinstance(a.kind, str) for a in result)


def test_b11_malformed_lines_do_not_lose_the_well_formed_subset():
    text = _mk(
        "garbage line with no structure",
        "- `08-05 10:00:00` [x] iter NaN " + MID + " **pm** attempt 1 started",
        _start("08-05 05:00:00", "alpha", 1, "engineer", 1),
        _nooutput("08-05 05:10:00", "alpha", 1, "engineer", 1, TAIL_STALLED),
        "- `08-05 06:00:00` [y] iter 2 " + MID + " truncat",
        _start("08-05 07:00:00", "alpha", 1, "pm", 1),
        _produced("08-05 07:03:00", "alpha", 1, "pm"),
    )
    atts = foundry.parse_stage_attempts(text)
    assert [(a.team, a.stage, a.kind) for a in atts] == \
        [("alpha", "engineer", "stalled"), ("alpha", "pm", "")]


def test_b11_truncated_tail_still_classifies_totally():
    # the marker is present but the quote never closes -- must still classify, and
    # must never raise
    text = _mk(_start("08-05 01:00:00", "t", 1, "s", 1),
               "- `08-05 01:10:00` [t] iter 1 " + MID +
               " s no output file (attempt 1/4); tail: 'Connection stalled -- no data")
    atts = foundry.parse_stage_attempts(text)
    assert len(atts) == 1
    assert atts[0].produced is False
    assert isinstance(atts[0].kind, str) and atts[0].kind != ""
