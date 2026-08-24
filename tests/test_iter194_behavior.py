"""Iteration 194 -- BLACK-BOX behavior tests: `ship_decision` WIRED at the live final gate.

Spec under test (products/_platform/state/iter-194/pm.md), Expected Behaviors 1-12:
   1. `stage_attempt_killed` -> True iff newest attempt log classifies as `timeout`
   2. it is TOTAL: missing dir / no log / unreadable log / non-int iteration -> False
   3. newest attempt chosen NUMERICALLY (attempt10 > attempt9); delegates by BARE name
   4. `run_iteration` calls `ship_decision` exactly once per final round, kwargs only,
      with head_moved=(head_of_branch(cfg) != base)
   5. action = "PUSHED" / "REVERTED" / None by SUBSTRING (`contains`), not last-line
   6. SHIP verdict -> same SHIPPED log line, postrelease_step, same shipped dict
   7. REVERT verdict -> revert_repo(cfg, "final gate declined to ship") + no-ship dict
   8. RETRY verdict -> re-runs `final`, does NOT revert first, tree left intact
   9. RETRY copies (never moves) final.md + newest attempt log; failures never raise
  10. at most FINAL_GATE_MAX_ROUNDS rounds; LAST round gets retries_remaining=False
  11. TODAY-EQUIVALENCE: with kill forced False, every outcome matches the old rule
  12. `sentinel_dormancy_gaps` over the LIVE ARCHITECTURE.md returns (); the three
      SHIP_DECISION_TOKENS stay cited as backticked spans; `run_execution_plan`'s
      mirror release gate is asserted UNCHANGED (deliberate, greppable divergence)

ISOLATION CONTRACT (HONORED): written from the iter-194 PM spec, the conventions of the
existing `tests/test_iter18*_behavior.py` / `test_iter189_behavior.py` modules, and the
product's OWN OBSERVABLE surface (calling its public functions, `inspect.signature`, and
`ast` walks the spec itself mandates).  `foundry.py`'s implementation TEXT was NOT read by
the author, and neither were `engineer.md`, `reviewer.md`, `IMPLEMENTATION.patch`, nor
`git diff`.

OFFLINE + FRESH-CLONE SAFE: every assertion is a pure in-memory call, a `tmp_path`
fixture, or an `ast` walk of the module under test.  No subprocess, no git, no network, no
clock.  No assertion about the ambient tree, a directory basename, a file count under a
gitignored path, or an absolute machine path.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

THIS_ITER = 194

# --------------------------------------------------------------------------
# runtime-built paths + fixed values (never a source-literal home path)
# --------------------------------------------------------------------------
_MOD_DIR = pathlib.Path(foundry.__file__).resolve().parent

ITER = 194
BASE = "base0000"
NEWHEAD = "newhead99"
POST_SENTINEL = "POSTRELEASE: HEALTHY"

PUSHED = "ACTION: PUSHED"
REVERTED = "ACTION: REVERTED"
REVERT_REASON = "final gate declined to ship"

# the agent CLI's REAL kill line -- the spec measured this in 1,368 attempt logs
KILL_LOG = "agent run failed: agent run timed out after 600s"
QUIET_LOG = "stage attempt completed and wrote its report"

SHIP_BODY = "VERDICT: APPROVE\nRESULT: PASS\n" + PUSHED + " " + NEWHEAD + "\n"
REVERT_BODY = "VERDICT: APPROVE\nRESULT: PASS\n" + REVERTED + " nothing to ship\n"
MUTE_BODY = ("VERDICT: APPROVE\nRESULT: PASS\n"
             "verification was still in flight when the cap fired\n")


def _write_cfg(tmp_path, **over):
    """Minimal product config in a tmp dir: repo/work_root are TMP so the real repo
    and state tree are NEVER touched."""
    import json
    tmp_path = pathlib.Path(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    n = len(list(tmp_path.glob("cfg_*.json")))
    p = tmp_path / ("cfg_%d.json" % n)
    p.write_text(json.dumps(data))
    return p


def _cfg(tmp_path, **over):
    return foundry.load_config(str(_write_cfg(tmp_path, **over)))


def _iter_dir(cfg, iteration):
    """The SAME expression run_stage uses (spec reconnaissance 1)."""
    return pathlib.Path(cfg.state) / ("iter-%02d" % iteration)


# ===========================================================================
# behavior 1/2/3 -- `stage_attempt_killed` is a total, numeric-newest reader
# ===========================================================================
def test_b1_helper_exists_and_is_callable():
    fn = getattr(foundry, "stage_attempt_killed", None)
    assert callable(fn), "spec behavior 1: foundry.stage_attempt_killed must exist"


def test_b10_final_gate_max_rounds_is_a_module_level_int():
    val = getattr(foundry, "FINAL_GATE_MAX_ROUNDS", None)
    assert isinstance(val, int) and not isinstance(val, bool), (
        "spec AC: FINAL_GATE_MAX_ROUNDS must be a module-level int, got %r" % (val,)
    )
    assert val >= 2, "a max-rounds of <2 makes the RETRY cell unreachable"


def test_b4_ship_decision_has_exactly_one_call_site_inside_run_iteration():
    """Inverted twin of iter189's dormancy freeze -- EXACT count, not >=."""
    tree = ast.parse((_ROOT / "foundry.py").read_text(encoding="utf-8"))
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if name == "ship_decision":
                sites.append(node)
    assert len(sites) == 1, (
        "spec behavior 4: exactly ONE ship_decision call site, found %d" % len(sites)
    )


# --------------------------------------------------------------------------
# scripted seams -- fully offline: no git, no network, no clock, no agent run
# --------------------------------------------------------------------------
def _make_run_stage(events, bodies, logs, default_body):
    """Scripted run_stage. Records ("stage", name) in `events`, writes the scripted
    report AND an attempt log (real `run_stage` writes both), returns (True, path).

    `bodies` maps stage -> list of per-round bodies (popped left, last one sticks),
    so round 1 and round 2 of the SAME stage can be told apart by content.
    """
    def run_stage(cfg, iteration, stage, role_file, out_name, extra=""):
        events.append(("stage", stage))
        d = _iter_dir(cfg, iteration)
        d.mkdir(parents=True, exist_ok=True)
        out = d / out_name
        seq = bodies.get(stage)
        if isinstance(seq, list) and seq:
            body = seq.pop(0) if len(seq) > 1 else seq[0]
        elif isinstance(seq, str):
            body = seq
        else:
            body = default_body
        out.write_text(body)
        lseq = logs.get(stage)
        if lseq is not None:
            log_body = lseq.pop(0) if (isinstance(lseq, list) and len(lseq) > 1) else (
                lseq[0] if isinstance(lseq, list) else lseq)
            (d / ("%s.attempt1.log" % stage)).write_text(log_body)
        return True, out
    return run_stage


def _patch_seams(monkeypatch, events, *, head, bodies=None, logs=None,
                 default_body=SHIP_BODY, also=None):
    monkeypatch.setattr(foundry, "run_stage",
                        _make_run_stage(events, bodies or {}, logs or {}, default_body))
    monkeypatch.setattr(foundry, "head_of_branch", head)
    monkeypatch.setattr(foundry, "revert_repo",
                        lambda cfg, reason: events.append(("revert", reason)))
    monkeypatch.setattr(
        foundry, "postrelease_step",
        lambda *a, **k: foundry.PostReleaseResult(True, False, POST_SENTINEL))
    monkeypatch.setattr(foundry, "next_iteration", lambda *a, **k: ITER)
    monkeypatch.setattr(foundry, "log",
                        lambda *a, **k: events.append(("log", " ".join(str(x) for x in a))))
    monkeypatch.setattr(foundry, "power_state", lambda: "Now drawing from 'AC Power'")
    monkeypatch.setattr(foundry, "iteration_is_scouted", lambda c, n: True)
    monkeypatch.setattr(foundry, "refresh_directions_file", lambda c: True)
    for name, value in (also or {}).items():
        monkeypatch.setattr(foundry, name, value)


class _SpyShipDecision:
    """Records every call to `ship_decision` and DELEGATES to the real function, so the
    live verdict semantics shipped at iter 189 are exercised, not re-implemented."""

    def __init__(self, real, verdicts=None):
        self._real = real
        self.calls = []          # list of (args, kwargs)
        self._verdicts = verdicts

    def __call__(self, *args, **kwargs):
        self.calls.append((args, dict(kwargs)))
        out = self._real(*args, **kwargs)
        return out

    @property
    def kwargs(self):
        return [k for (_a, k) in self.calls]

    @property
    def positional(self):
        return [a for (a, _k) in self.calls]


def _drive(monkeypatch, tmp_path, *, final_body=None, killed=None, head_moves=True,
           bodies=None, logs=None, max_rounds=None, also=None, cfg=None):
    """LIVE PATH -- foundry.run_iteration through its default fixed pipeline."""
    cfg = cfg if cfg is not None else _cfg(tmp_path)
    events = []
    seq = [BASE, NEWHEAD] if head_moves else [BASE]

    def head(c):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    bodies = dict(bodies or {})
    if final_body is not None:
        bodies["final"] = final_body if isinstance(final_body, list) else [final_body]
    extra = dict(also or {})
    if killed is not None:
        extra["stage_attempt_killed"] = (
            killed if callable(killed) else (lambda *a, **k: killed))
    if max_rounds is not None:
        extra["FINAL_GATE_MAX_ROUNDS"] = max_rounds
    spy = _SpyShipDecision(foundry.ship_decision)
    extra["ship_decision"] = spy
    _patch_seams(monkeypatch, events, head=head, bodies=bodies, logs=logs, also=extra)
    res = foundry.run_iteration(cfg, ITER)
    return res, events, spy, cfg


def _stages(events):
    return [n for (k, n) in events if k == "stage"]


def _reverts(events):
    return [n for (k, n) in events if k == "revert"]


def _logs(events):
    return [n for (k, n) in events if k == "log"]


def test_harness_smoke_default_ships(monkeypatch, tmp_path):
    """PRECONDITION: the harness must be able to reach a SHIP, or every negative test
    below is vacuously green (the tester card's precondition rule)."""
    res, events, spy, _cfgo = _drive(monkeypatch, tmp_path, final_body=SHIP_BODY,
                                     killed=False)
    assert res.get("status") == "shipped", (res, _stages(events), _reverts(events))
    assert _reverts(events) == []
    assert _stages(events).count("final") == 1
    assert len(spy.calls) == 1, spy.calls


# ==========================================================================
# Behavior 1 -- `stage_attempt_killed` reads the kill fact from the newest log
# ==========================================================================
def _seed_log(cfg, iteration, stage, attempt, body):
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    p = d / ("%s.attempt%d.log" % (stage, attempt))
    p.write_text(body)
    return p


def test_b1_helper_is_documented():
    doc = (foundry.stage_attempt_killed.__doc__ or "").strip()
    assert doc, "AC: stage_attempt_killed must be documented"
    assert "KILLED" in doc.upper()


@pytest.mark.parametrize("body,expected", [
    (KILL_LOG, True),
    ("agent run failed: agent run timed out after 600s\n", True),
    (QUIET_LOG, False),
    ("", False),
    ("VERDICT: APPROVE\nRESULT: PASS\nACTION: PUSHED abc\n", False),
], ids=["real_600s_kill", "kill_with_newline", "quiet", "empty_log", "a_full_report"])
def test_b1_kill_fact_tracks_the_classifier(tmp_path, body, expected):
    cfg = _cfg(tmp_path)
    _seed_log(cfg, ITER, "final", 1, body)
    assert foundry.stage_attempt_killed(cfg, ITER, "final") is expected


def test_b1_kill_fact_is_per_stage(tmp_path):
    """A killed ENGINEER round must not make the FINAL gate look killed."""
    cfg = _cfg(tmp_path)
    _seed_log(cfg, ITER, "engineer", 1, KILL_LOG)
    _seed_log(cfg, ITER, "final", 1, QUIET_LOG)
    assert foundry.stage_attempt_killed(cfg, ITER, "final") is False
    assert foundry.stage_attempt_killed(cfg, ITER, "engineer") is True


def test_b1_kill_fact_is_per_iteration(tmp_path):
    cfg = _cfg(tmp_path)
    _seed_log(cfg, ITER, "final", 1, KILL_LOG)
    assert foundry.stage_attempt_killed(cfg, ITER, "final") is True
    assert foundry.stage_attempt_killed(cfg, ITER + 1, "final") is False


# ==========================================================================
# Behavior 2 -- TOTAL: it can never raise, and False is the fail-CLOSED answer
# ==========================================================================
def test_b2_missing_state_dir_returns_false(tmp_path):
    cfg = _cfg(tmp_path)                      # nothing created under cfg.state
    assert foundry.stage_attempt_killed(cfg, ITER, "final") is False


def test_b2_dir_exists_but_no_matching_log_returns_false(tmp_path):
    cfg = _cfg(tmp_path)
    d = _iter_dir(cfg, ITER)
    d.mkdir(parents=True, exist_ok=True)
    (d / "final.md").write_text(MUTE_BODY)          # a report, not an attempt log
    (d / "engineer.attempt1.log").write_text(KILL_LOG)
    (d / "final.attempt.log").write_text(KILL_LOG)  # no attempt NUMBER
    (d / "finality.attempt1.log").write_text(KILL_LOG)  # different stage name
    assert foundry.stage_attempt_killed(cfg, ITER, "final") is False


def test_b2_unreadable_log_returns_false(tmp_path):
    """The log path is a DIRECTORY -- any read of it raises. Must degrade to False."""
    cfg = _cfg(tmp_path)
    d = _iter_dir(cfg, ITER)
    d.mkdir(parents=True, exist_ok=True)
    (d / "final.attempt1.log").mkdir()
    assert foundry.stage_attempt_killed(cfg, ITER, "final") is False


def test_b2_non_utf8_log_never_raises(tmp_path):
    cfg = _cfg(tmp_path)
    d = _iter_dir(cfg, ITER)
    d.mkdir(parents=True, exist_ok=True)
    (d / "final.attempt1.log").write_bytes(b"\xff\xfe\x00\x80 not decodable\xff")
    out = foundry.stage_attempt_killed(cfg, ITER, "final")
    assert out is False or out is True     # the contract is "does not raise"
    assert isinstance(out, bool)


@pytest.mark.parametrize("iteration", [
    None, "194", "iter-194", 3.5, -1, 0, [], {}, object(),
], ids=["none", "str_int", "str_dirname", "float", "negative", "zero", "list",
        "dict", "object"])
def test_b2_non_integer_iteration_returns_false(tmp_path, iteration):
    cfg = _cfg(tmp_path)
    _seed_log(cfg, ITER, "final", 1, KILL_LOG)
    out = foundry.stage_attempt_killed(cfg, iteration, "final")
    assert out is False, "non-integer iteration must be False, got %r" % (out,)


@pytest.mark.parametrize("stage", [None, "", 7, [], object()],
                         ids=["none", "empty", "int", "list", "object"])
def test_b2_bad_stage_argument_returns_false(tmp_path, stage):
    cfg = _cfg(tmp_path)
    _seed_log(cfg, ITER, "final", 1, KILL_LOG)
    assert foundry.stage_attempt_killed(cfg, ITER, stage) is False


@pytest.mark.parametrize("cfg", [None, object(), 7, "cfg"],
                         ids=["none", "object", "int", "str"])
def test_b2_cfg_without_state_returns_false(cfg):
    assert foundry.stage_attempt_killed(cfg, ITER, "final") is False


def test_b2_a_raising_classifier_returns_false(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path)
    _seed_log(cfg, ITER, "final", 1, KILL_LOG)

    def boom(blob):
        raise RuntimeError("classifier exploded")

    monkeypatch.setattr(foundry, "classify_attempt_failure", boom)
    assert foundry.stage_attempt_killed(cfg, ITER, "final") is False


# ==========================================================================
# Behavior 3 -- NUMERIC newest attempt + BARE-NAME delegation
# ==========================================================================
def test_b3_attempt10_beats_attempt9_numerically(tmp_path):
    """A lexicographic max would pick attempt9 in BOTH directions; both assertions
    together are only satisfiable by a NUMERIC max."""
    cfg = _cfg(tmp_path)
    _seed_log(cfg, ITER, "final", 9, QUIET_LOG)
    _seed_log(cfg, ITER, "final", 10, KILL_LOG)
    assert foundry.stage_attempt_killed(cfg, ITER, "final") is True

    cfg2 = _cfg(tmp_path)
    _seed_log(cfg2, ITER, "final", 9, KILL_LOG)
    _seed_log(cfg2, ITER, "final", 10, QUIET_LOG)
    assert foundry.stage_attempt_killed(cfg2, ITER, "final") is False


def test_b3_delegates_to_the_classifier_by_bare_module_name(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path)
    _seed_log(cfg, ITER, "final", 1, QUIET_LOG)     # a QUIET log ...
    seen = []

    def fake(blob):
        seen.append(blob)
        return "timeout"                            # ... forced to classify as killed

    monkeypatch.setattr(foundry, "classify_attempt_failure", fake)
    assert foundry.stage_attempt_killed(cfg, ITER, "final") is True
    assert len(seen) == 1, "exactly one classifier call, got %d" % len(seen)
    assert QUIET_LOG in seen[0]


@pytest.mark.parametrize("kind,expected", [
    ("timeout", True), ("other", False), ("auth", False), ("stale-ipc", False),
    ("", False), (None, False),
], ids=["timeout", "other", "auth", "stale_ipc", "empty", "none"])
def test_b3_only_the_timeout_kind_is_a_kill(monkeypatch, tmp_path, kind, expected):
    cfg = _cfg(tmp_path)
    _seed_log(cfg, ITER, "final", 1, QUIET_LOG)
    monkeypatch.setattr(foundry, "classify_attempt_failure", lambda blob: kind)
    assert foundry.stage_attempt_killed(cfg, ITER, "final") is expected


def test_b3_performs_at_most_one_file_read(monkeypatch, tmp_path):
    """AC: at most ONE file read. Counted through pathlib itself."""
    cfg = _cfg(tmp_path)
    _seed_log(cfg, ITER, "final", 1, QUIET_LOG)
    _seed_log(cfg, ITER, "final", 2, KILL_LOG)
    _seed_log(cfg, ITER, "engineer", 1, KILL_LOG)
    reads = []
    real_rt = pathlib.Path.read_text
    real_rb = pathlib.Path.read_bytes

    def rt(self, *a, **k):
        reads.append(str(self))
        return real_rt(self, *a, **k)

    def rb(self, *a, **k):
        reads.append(str(self))
        return real_rb(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", rt)
    monkeypatch.setattr(pathlib.Path, "read_bytes", rb)
    assert foundry.stage_attempt_killed(cfg, ITER, "final") is True
    assert len(reads) <= 1, "expected <=1 file read, got %d: %r" % (len(reads), reads)


# ==========================================================================
# Behavior 4 -- run_iteration calls ship_decision ONCE per round, KWARGS only
# ==========================================================================
SHIP_KWARGS = {"action", "head_moved", "attempt_killed", "retries_remaining"}


def test_b4_called_exactly_once_per_final_round_with_kwargs_only(monkeypatch, tmp_path):
    res, events, spy, _c = _drive(monkeypatch, tmp_path, final_body=SHIP_BODY,
                                  killed=False)
    assert _stages(events).count("final") == 1
    assert len(spy.calls) == 1, spy.calls
    assert spy.positional == [()], (
        "AC: ship_decision must be called with KEYWORD arguments only, got positional %r"
        % (spy.positional,))
    assert set(spy.kwargs[0]) == SHIP_KWARGS, spy.kwargs[0]


@pytest.mark.parametrize("head_moves,expected", [(True, True), (False, False)],
                         ids=["head_moved", "head_unmoved"])
def test_b4_head_moved_is_derived_from_head_of_branch(monkeypatch, tmp_path,
                                                      head_moves, expected):
    _res, _ev, spy, _c = _drive(monkeypatch, tmp_path, final_body=SHIP_BODY,
                                killed=False, head_moves=head_moves)
    assert spy.kwargs[0]["head_moved"] is expected


@pytest.mark.parametrize("killed", [True, False], ids=["killed", "not_killed"])
def test_b4_attempt_killed_is_sourced_from_the_helper(monkeypatch, tmp_path, killed):
    _res, _ev, spy, _c = _drive(monkeypatch, tmp_path, final_body=SHIP_BODY,
                                killed=killed)
    assert spy.kwargs[0]["attempt_killed"] is killed


def test_b4_attempt_killed_comes_from_the_real_helper_reading_a_real_log(
        monkeypatch, tmp_path):
    """End to end with NO kill stub: the scripted run_stage writes a REAL 600s kill log
    and the gate must see attempt_killed=True through the shipped reader."""
    _res, _ev, spy, _c = _drive(monkeypatch, tmp_path, final_body=MUTE_BODY,
                                logs={"final": [KILL_LOG]}, max_rounds=1)
    assert spy.kwargs[0]["attempt_killed"] is True


def test_b4_a_quiet_real_log_reads_as_not_killed(monkeypatch, tmp_path):
    _res, _ev, spy, _c = _drive(monkeypatch, tmp_path, final_body=MUTE_BODY,
                                logs={"final": [QUIET_LOG]}, max_rounds=1)
    assert spy.kwargs[0]["attempt_killed"] is False


# ==========================================================================
# Behavior 5 -- `action` is a SUBSTRING test (`contains`), NOT parse_ship_action
# ==========================================================================
PUSHED_THEN_PROSE = SHIP_BODY + "postscript: one more note after the token\n"
REVERTED_THEN_PROSE = REVERT_BODY + "postscript: one more note after the token\n"
BOTH_TOKENS = "ACTION: REVERTED first\nthen\n" + PUSHED + " " + NEWHEAD + "\n"


@pytest.mark.parametrize("body,expected", [
    (SHIP_BODY, "PUSHED"),
    (PUSHED_THEN_PROSE, "PUSHED"),
    (REVERT_BODY, "REVERTED"),
    (REVERTED_THEN_PROSE, "REVERTED"),
    (BOTH_TOKENS, "PUSHED"),
    (MUTE_BODY, None),
    ("", None),
    ("action: pushed\n", None),
    ("ACTION:PUSHED\n", None),
    ("ACTION: PENDING\n", None),
], ids=["pushed", "pushed_then_prose", "reverted", "reverted_then_prose",
        "both_tokens_pushed_wins", "mute", "empty", "lowercase", "no_space",
        "pending"])
def test_b5_action_truth_table(monkeypatch, tmp_path, body, expected):
    _res, _ev, spy, _c = _drive(monkeypatch, tmp_path, final_body=body, killed=False)
    assert spy.kwargs[0]["action"] == expected, spy.kwargs[0]


def test_b5_substring_semantics_are_kept_a_trailing_line_still_ships(monkeypatch,
                                                                    tmp_path):
    """THE regression this behavior guards: `parse_ship_action` requires the token to be
    the LAST NON-EMPTY LINE, so adopting it here would REVERT reports that ship today."""
    res, events, spy, _c = _drive(monkeypatch, tmp_path,
                                  final_body=PUSHED_THEN_PROSE, killed=False)
    assert spy.kwargs[0]["action"] == "PUSHED"
    assert res.get("status") == "shipped", (res, _reverts(events))
    # and the tighter parser really would have disagreed -- two-sided evidence
    assert foundry.parse_ship_action(PUSHED_THEN_PROSE) is None


# ==========================================================================
# Behavior 6 -- a SHIP verdict ships exactly as today
# ==========================================================================
def test_b6_ship_returns_the_same_dict_shape_and_logs_shipped(monkeypatch, tmp_path):
    res, events, spy, _c = _drive(monkeypatch, tmp_path, final_body=SHIP_BODY,
                                  killed=False)
    assert set(res) == {"status", "head", "iteration", "postrelease"}, res
    assert res["status"] == "shipped"
    assert res["head"] == NEWHEAD
    assert res["iteration"] == ITER
    assert res["postrelease"] is not None
    assert _reverts(events) == [], "a SHIP must never revert"
    assert any("SHIPPED" in line for line in _logs(events)), _logs(events)


@pytest.mark.parametrize("killed", [True, False], ids=["killed", "not_killed"])
def test_b6_ship_is_reached_regardless_of_the_kill_fact(monkeypatch, tmp_path, killed):
    """A gate that wrote PUSHED and moved the head ships whether or not it was later
    cut off -- cell 1 of the iter-189 table, unchanged by this bite."""
    res, events, _spy, _c = _drive(monkeypatch, tmp_path, final_body=SHIP_BODY,
                                   killed=killed)
    assert res.get("status") == "shipped"
    assert _stages(events).count("final") == 1, "a SHIP must not retry"


# ==========================================================================
# Behavior 7 -- a REVERT verdict is byte-identical to today
# ==========================================================================
@pytest.mark.parametrize("body,head_moves", [
    (REVERT_BODY, True), (REVERT_BODY, False),
    (SHIP_BODY, False),                       # PUSHED but the head never moved
    (MUTE_BODY, True), (MUTE_BODY, False),
], ids=["reverted_moved", "reverted_unmoved", "pushed_unmoved", "mute_moved",
        "mute_unmoved"])
def test_b7_revert_calls_revert_repo_with_the_exact_reason(monkeypatch, tmp_path,
                                                           body, head_moves):
    res, events, _spy, _c = _drive(monkeypatch, tmp_path, final_body=body,
                                   killed=False, head_moves=head_moves)
    assert res == {"status": "no-ship", "iteration": ITER}, res
    assert _reverts(events) == [REVERT_REASON], _reverts(events)


def test_b7_an_explicit_reverted_never_retries_even_when_killed(monkeypatch, tmp_path):
    """iter-189 cell 3: an explicit REVERTED is evidence about the TREE, so the kill
    fact must NOT buy it a retry."""
    res, events, spy, _c = _drive(monkeypatch, tmp_path, final_body=REVERT_BODY,
                                  killed=True)
    assert res == {"status": "no-ship", "iteration": ITER}, res
    assert _stages(events).count("final") == 1, _stages(events)
    assert _reverts(events) == [REVERT_REASON]


# ==========================================================================
# Behavior 8 -- a RETRY re-runs `final` and does NOT revert first
# ==========================================================================
MUTE_R1 = MUTE_BODY + "round one partial: the cap fired mid-checklist\n"
MUTE_R2 = MUTE_BODY + "round two partial: still no verdict\n"


def test_b8_retry_reruns_the_final_stage(monkeypatch, tmp_path):
    res, events, spy, _c = _drive(monkeypatch, tmp_path, final_body=MUTE_BODY,
                                  killed=True)
    stages = _stages(events)
    assert stages.count("final") == 2, stages
    assert len(spy.calls) == 2, spy.calls


def test_b8_no_revert_happens_before_the_rerun(monkeypatch, tmp_path):
    """THE bug this iteration removes: today's rule reverts the tree here."""
    _res, events, _spy, _c = _drive(monkeypatch, tmp_path, final_body=MUTE_BODY,
                                    killed=True)
    kinds = [(k, n) for (k, n) in events if k in ("stage", "revert")]
    final_positions = [i for i, (k, n) in enumerate(kinds)
                       if k == "stage" and n == "final"]
    revert_positions = [i for i, (k, _n) in enumerate(kinds) if k == "revert"]
    assert len(final_positions) == 2, kinds
    assert all(rp > final_positions[1] for rp in revert_positions), (
        "the tree was reverted BEFORE the retry re-ran: %r" % (kinds,))


def test_b8_a_retry_that_then_ships_never_reverts(monkeypatch, tmp_path):
    """The whole point: round 1 is cut off mute, round 2 writes PUSHED -> SHIP, and the
    green tree survives."""
    res, events, spy, _c = _drive(monkeypatch, tmp_path,
                                  final_body=[MUTE_R1, SHIP_BODY], killed=True)
    assert _stages(events).count("final") == 2, _stages(events)
    assert res.get("status") == "shipped", (res, _reverts(events))
    assert _reverts(events) == [], "a retry that ships must never revert"
    assert [k["action"] for k in spy.kwargs] == [None, "PUSHED"], spy.kwargs


def test_b8_mute_and_not_killed_never_retries(monkeypatch, tmp_path):
    """iter-189 cell 7: the stage COMPLETED and stayed mute -> REVERT, no retry."""
    res, events, spy, _c = _drive(monkeypatch, tmp_path, final_body=MUTE_BODY,
                                  killed=False)
    assert _stages(events).count("final") == 1, _stages(events)
    assert res == {"status": "no-ship", "iteration": ITER}
    assert _reverts(events) == [REVERT_REASON]


def test_b8_no_new_infra_fail_path_at_the_final_gate(monkeypatch, tmp_path):
    """AC: the reachable outcomes stay exactly `shipped` / `no-ship`."""
    seen = set()
    for body, killed, moves in ((SHIP_BODY, False, True), (SHIP_BODY, True, True),
                                (SHIP_BODY, False, False), (REVERT_BODY, True, True),
                                (MUTE_BODY, True, True), (MUTE_BODY, False, True),
                                (MUTE_BODY, True, False), (MUTE_BODY, False, False)):
        res, _ev, _spy, _c = _drive(monkeypatch, tmp_path, final_body=body,
                                    killed=killed, head_moves=moves)
        seen.add(res.get("status"))
    assert seen <= {"shipped", "no-ship"}, seen
    assert "infra-fail" not in seen


# ==========================================================================
# Behavior 9 -- the round's artifacts are COPIED aside, never MOVED
# ==========================================================================
def test_b9_originals_survive_and_a_content_preserving_copy_appears(monkeypatch,
                                                                   tmp_path):
    res, events, _spy, cfg = _drive(monkeypatch, tmp_path,
                                    final_body=[MUTE_R1, MUTE_R2], killed=True,
                                    logs={"final": [KILL_LOG]})
    assert _stages(events).count("final") == 2, _stages(events)
    d = _iter_dir(cfg, ITER)
    report = d / "final.md"
    log = d / "final.attempt1.log"
    assert report.exists(), "the ORIGINAL final.md must still exist (copy, not move)"
    assert log.exists(), "the ORIGINAL attempt log must still exist (copy, not move)"
    assert report.read_text() == MUTE_R2, "round 2 must own final.md"

    others = [p for p in sorted(d.iterdir())
              if p.is_file() and p.name.startswith("final")
              and p.name not in ("final.md", "final.attempt1.log")]
    assert others, ("no sibling copy of the round's artifacts was made; iter dir holds %r"
                    % ([p.name for p in sorted(d.iterdir())],))
    texts = []
    for p in others:
        try:
            texts.append(p.read_text())
        except OSError:
            pass
    assert MUTE_R1 in texts, (
        "round 1's partial report was not preserved by content; copies hold %r" % (texts,))
    assert KILL_LOG in texts, (
        "round 1's attempt log was not preserved by content; copies hold %r" % (texts,))


def test_b9_a_failing_copy_never_raises_and_never_changes_the_verdict(monkeypatch,
                                                                     tmp_path):
    """Force every plausible copy mechanism to raise. The gate must still retry and
    reach the SAME verdict -- the copy is forensics, not control flow."""
    import shutil

    def boom(*a, **k):
        raise OSError("copy denied by the test")

    monkeypatch.setattr(shutil, "copy2", boom)
    monkeypatch.setattr(shutil, "copyfile", boom)
    monkeypatch.setattr(shutil, "copy", boom)
    monkeypatch.setattr(pathlib.Path, "write_bytes", boom)
    res, events, spy, _c = _drive(monkeypatch, tmp_path,
                                  final_body=[MUTE_R1, SHIP_BODY], killed=True,
                                  logs={"final": [KILL_LOG]})
    assert _stages(events).count("final") == 2, _stages(events)
    assert res.get("status") == "shipped", (res, _reverts(events))
    assert _reverts(events) == []
    assert [k["action"] for k in spy.kwargs] == [None, "PUSHED"]


def test_b9_no_copies_are_made_when_there_is_no_retry(monkeypatch, tmp_path):
    """Non-vacuity control for behavior 9: the SHIP path leaves the iter dir alone."""
    _res, _ev, _spy, cfg = _drive(monkeypatch, tmp_path, final_body=SHIP_BODY,
                                  killed=False, logs={"final": [QUIET_LOG]})
    d = _iter_dir(cfg, ITER)
    others = [p.name for p in sorted(d.iterdir())
              if p.is_file() and p.name.startswith("final")
              and p.name not in ("final.md", "final.attempt1.log")]
    assert others == [], others


# ==========================================================================
# Behavior 10 -- bounded rounds; the LAST round can never be a RETRY
# ==========================================================================
@pytest.mark.parametrize("rounds", [1, 2, 3, 5], ids=["r1", "r2", "r3", "r5"])
def test_b10_gate_runs_at_most_max_rounds(monkeypatch, tmp_path, rounds):
    res, events, spy, _c = _drive(monkeypatch, tmp_path, final_body=MUTE_BODY,
                                  killed=True, max_rounds=rounds)
    assert _stages(events).count("final") == rounds, _stages(events)
    assert len(spy.calls) == rounds, spy.calls
    assert res == {"status": "no-ship", "iteration": ITER}, res
    assert _reverts(events) == [REVERT_REASON], _reverts(events)


@pytest.mark.parametrize("rounds", [1, 2, 3, 5], ids=["r1", "r2", "r3", "r5"])
def test_b10_last_round_is_passed_retries_remaining_false(monkeypatch, tmp_path,
                                                          rounds):
    _res, _ev, spy, _c = _drive(monkeypatch, tmp_path, final_body=MUTE_BODY,
                                killed=True, max_rounds=rounds)
    flags = [k["retries_remaining"] for k in spy.kwargs]
    assert flags == [True] * (rounds - 1) + [False], flags


def test_b10_the_constant_is_read_at_call_time(monkeypatch, tmp_path):
    """A default-argument or def-time capture would ignore the monkeypatch; three
    different values producing three different round counts proves a call-time read."""
    counts = []
    for rounds in (1, 2, 4):
        _res, events, _spy, _c = _drive(monkeypatch, tmp_path, final_body=MUTE_BODY,
                                        killed=True, max_rounds=rounds)
        counts.append(_stages(events).count("final"))
    assert counts == [1, 2, 4], counts


def test_b10_the_gate_can_never_spin(monkeypatch, tmp_path):
    """Round budget exhausted while STILL killed and STILL mute -> terminates in
    REVERT, never in a RETRY verdict."""
    _res, _ev, spy, _c = _drive(monkeypatch, tmp_path, final_body=MUTE_BODY,
                                killed=True, max_rounds=2)
    verdicts = [foundry.ship_decision(**k).verdict for k in spy.kwargs]
    assert verdicts[-1] == "REVERT", verdicts
    assert verdicts.count("RETRY") == len(verdicts) - 1, verdicts


# ==========================================================================
# Behavior 11 -- TODAY-EQUIVALENCE oracle: kill forced False changes NOTHING
# ==========================================================================
def _todays_rule(final_body, head_moved):
    """The rule this iteration replaces, re-implemented from the spec's own words:
    `contains(final, "ACTION: PUSHED") and new_head != base`."""
    return "shipped" if (PUSHED in final_body and head_moved) else "no-ship"


TODAY_BODIES = (SHIP_BODY, PUSHED_THEN_PROSE, REVERT_BODY, REVERTED_THEN_PROSE,
                BOTH_TOKENS, MUTE_BODY, "", "action: pushed\n", "ACTION: PENDING\n")
TODAY_IDS = ("pushed", "pushed_then_prose", "reverted", "reverted_then_prose",
             "both_tokens", "mute", "empty", "lowercase", "pending")


@pytest.mark.parametrize("body", TODAY_BODIES, ids=TODAY_IDS)
@pytest.mark.parametrize("head_moves", [True, False], ids=["moved", "unmoved"])
def test_b11_today_equivalence_when_the_stage_was_not_killed(monkeypatch, tmp_path,
                                                             body, head_moves):
    res, events, _spy, _c = _drive(monkeypatch, tmp_path, final_body=body,
                                   killed=False, head_moves=head_moves)
    expected = _todays_rule(body, head_moves)
    assert res.get("status") == expected, (body, head_moves, res)
    assert _stages(events).count("final") == 1, (
        "a NOT-killed gate must never retry: %r" % (_stages(events),))
    if expected == "no-ship":
        assert _reverts(events) == [REVERT_REASON]
    else:
        assert _reverts(events) == []


@pytest.mark.parametrize("body", TODAY_BODIES, ids=TODAY_IDS)
@pytest.mark.parametrize("head_moves", [True, False], ids=["moved", "unmoved"])
def test_b11_the_delta_is_exactly_the_mute_plus_killed_cells(monkeypatch, tmp_path,
                                                             body, head_moves):
    """With kill TRUE, the ONLY cells that may differ from today are the ones with no
    usable ACTION token -- and there the difference is a RETRY, never a worse outcome."""
    res, events, _spy, _c = _drive(monkeypatch, tmp_path, final_body=body,
                                   killed=True, head_moves=head_moves)
    today = _todays_rule(body, head_moves)
    rounds = _stages(events).count("final")
    has_token = (PUSHED in body) or (REVERTED in body)
    if has_token:
        assert rounds == 1, (body, _stages(events))
        assert res.get("status") == today, (body, head_moves, res)
    else:
        assert rounds == foundry.FINAL_GATE_MAX_ROUNDS, (body, _stages(events))
        # never SHIPS what today would not
        assert not (res.get("status") == "shipped" and today == "no-ship"), res


def test_b11_never_ships_something_today_would_refuse(monkeypatch, tmp_path):
    """The one-directional safety property: the wiring may SAVE work, never invent a
    ship. Swept over every body x head x kill combination."""
    for body in TODAY_BODIES:
        for head_moves in (True, False):
            for killed in (True, False):
                res, _ev, _spy, _c = _drive(monkeypatch, tmp_path, final_body=body,
                                            killed=killed, head_moves=head_moves)
                if res.get("status") == "shipped":
                    assert _todays_rule(body, head_moves) == "shipped", (
                        "INVENTED A SHIP: body=%r head_moves=%r killed=%r"
                        % (body, head_moves, killed))


# ==========================================================================
# Behavior 12 -- the dormancy brake is satisfied and the divergence is pinned
# ==========================================================================
def _live_source():
    return (_MOD_DIR / "foundry.py").read_text(encoding="utf-8")


def _live_arch():
    return (_MOD_DIR / "ARCHITECTURE.md").read_text(encoding="utf-8")


def test_b12_sentinel_dormancy_gaps_over_the_live_doc_is_empty():
    n = foundry.call_site_count(_live_source(), symbol="ship_decision")
    assert n == 1, "expected exactly 1 derived call site, got %r" % (n,)
    gaps = foundry.sentinel_dormancy_gaps(
        _live_arch(), tokens=foundry.SHIP_DECISION_TOKENS,
        symbol="ship_decision", call_sites=n)
    assert gaps == (), gaps


def test_b12_the_dormancy_brake_is_non_vacuous():
    """Two-sided: the SAME doc against a call_sites=0 claim must FIRE. A brake that
    cannot fire is indistinguishable from a clean bill of health."""
    gaps = foundry.sentinel_dormancy_gaps(
        _live_arch(), tokens=foundry.SHIP_DECISION_TOKENS,
        symbol="ship_decision", call_sites=0)
    assert gaps != (), "the dormancy brake never fires -- it proves nothing"


@pytest.mark.parametrize("token", ["SHIP", "RETRY", "REVERT"])
def test_b12_architecture_cites_each_token_as_a_backticked_span(token):
    assert token in foundry.SHIP_DECISION_TOKENS
    assert ("`" + token + "`") in _live_arch(), (
        "ARCHITECTURE.md must cite `%s` as an exact backticked span" % token)


def test_b12_architecture_no_longer_claims_the_symbol_is_dormant_at_the_gate():
    doc = _live_arch()
    lower = doc.lower()
    i = lower.find("ship_decision")
    assert i >= 0, "ARCHITECTURE.md must mention ship_decision"
    window = doc[max(0, i - 400):i + 400]
    assert "DORMANT" not in window.upper() or "WIRED" in window.upper(), window


def _drive_plan(monkeypatch, tmp_path, *, final_body, logs=None):
    """LIVE PATH 2 -- run_execution_plan's MIRROR release gate. Spec reconnaissance 8
    declares it OUT OF SCOPE, so the divergence must be PINNED, not left silent."""
    cfg = _cfg(tmp_path)
    events = []
    spy = _SpyShipDecision(foundry.ship_decision)
    _patch_seams(monkeypatch, events, head=lambda c: NEWHEAD,
                 bodies={"final": [final_body]}, logs=logs or {},
                 also={"ship_decision": spy,
                       "stage_attempt_killed": lambda *a, **k: True})
    plan = foundry.derive_execution_plan(foundry._default_stage_sequence())
    res = foundry.run_execution_plan(cfg, ITER, plan, BASE)
    return res, events, spy


def test_b12_run_execution_plan_release_gate_is_UNCHANGED(monkeypatch, tmp_path):
    """It must NOT consult ship_decision and must NOT retry -- deliberate, greppable."""
    res, events, spy = _drive_plan(monkeypatch, tmp_path, final_body=MUTE_BODY,
                                   logs={"final": [KILL_LOG]})
    assert spy.calls == [], (
        "run_execution_plan's mirror gate was wired too -- out of scope this bite: %r"
        % (spy.calls,))
    assert _stages(events).count("final") == 1, _stages(events)
    assert res.get("status") != "shipped", res


def test_b12_run_execution_plan_still_ships_a_pushed_report(monkeypatch, tmp_path):
    """Non-vacuity control: the mirror driver is reachable and can still ship."""
    res, events, spy = _drive_plan(monkeypatch, tmp_path, final_body=SHIP_BODY,
                                   logs={"final": [QUIET_LOG]})
    assert res.get("status") == "shipped", res
    assert spy.calls == []


def test_b12_the_default_pipeline_is_the_one_run_iteration_uses():
    """Why the mirror gate is unreachable today (spec reconnaissance 8): every derived
    sequence equals the default, so run_iteration never delegates to the plan driver."""
    assert (foundry.derive_stage_sequence(None)
            == foundry._default_stage_sequence())
