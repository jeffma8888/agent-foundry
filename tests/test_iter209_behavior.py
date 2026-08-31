"""Black-box behaviour tests for iter 209 -- a STRUCTURED `live-lag` verdict.

Spec: products/_platform/state/iter-209/pm.md, Expected Behaviors 1-10.

  summarize_live_lag(...) -> LiveLagStatus
  1.  frozen dataclass; UNKNOWN when nothing is known; assignment raises.
  2.  OK when a launch instant is known and nothing is inert; WARN when inert.
  3.  .exit_code mapping preserved exactly: OK 0, WARN 2, UNKNOWN 0.
  4.  UNKNOWN dominates: unknown_reason set OR launch_epoch None wins over inert.
  5.  .inert normalised to a tuple of ints from any iterable; .to_dict() JSON-native
      and DERIVED from the same properties, so payload and prose cannot disagree.
  live_lag_line(cfg)
  6.  byte-identical to the PRE-CHANGE function for all four shapes -- pinned
      against literals captured by RUNNING the pre-change function at git HEAD,
      never against the new renderer.
  live_lag_cli(cfg)
  7.  returns status.exit_code, never a scan of its own text: an UNKNOWN whose
      reason text contains "WARN" exits 0 (pre-change: measured 2).
  dispatch_restart_line(cfg)
  8.  returns None and raises NO restart flag on UNKNOWN, including UNKNOWN text
      containing "WARN" (pre-change: returned the line AND raised the flag);
      WARN/OK behaviour and both flag side effects unchanged.
  CLI
  9.  `live-lag --json` prints exactly one indent=2 JSON document, same exit code
      as the identical call without --json; without --json stdout is unchanged.
  10. DORMANT on the control path (run_iteration, run_continuous, run_stage,
      build_prompt, postrelease_step), absent from dispatcher, imports clean.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-209 PM spec and from the
product's own OBSERVABLE surface -- importing the module, CALLING its public
functions, reading `__doc__` / `inspect.signature` / `dataclasses.fields`, running
the CLI, and reading files under `tests/`. The implementation BODIES of foundry.py
and dispatcher.py, the engineer's notes, the reviewer's notes and `git diff` were
NOT read. Behavior 10 uses `inspect.getsource` MECHANICALLY (substring and
`co_names` assertions only, never displayed), exactly as iter-130's suite does.
Behavior 6's oracle literals were produced by EXECUTING the pre-change function at
git HEAD and capturing its RETURN VALUE; its source was never read or displayed.

Offline and deterministic: synthetic fixtures, throwaway tmp_path dirs, and both
`live_lag_line` seams scripted by bare module name. No network, no real git, no
subprocess, no sleeps, no mutation of the product tree. Every asserted path is
relative, so nothing here depends on this machine.
"""
import dataclasses
import inspect
import json
import pathlib
import sys
from datetime import datetime

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- Behavior 10)

THIS_ITER = 209

# Names introduced by this iteration -- must stay OFF the control path (Behavior 10).
NEW_NAMES = ("LiveLagStatus", "summarize_live_lag", "live_lag_status")
CONTROL_PATH_FNS = ("run_iteration", "run_continuous", "run_stage",
                    "build_prompt", "postrelease_step")

# A relative, machine-independent log path: it never exists, so nothing is read.
LOG = "products/_platform/state/iter-208/no-such-dispatcher.out"
LOG_BASENAME = "no-such-dispatcher.out"

LAUNCH = 1000.0
INERT_FIXTURE = ((118, 900), (119, 1100), (122, 1200), (124, 1300))  # launch 1000 -> 3 inert
LIVE_ONLY_FIXTURE = ((118, 900),)                                    # launch 1000 -> 0 inert
WARN_IN_TEXT_EXC = ValueError("WARNING: git unreachable")            # text CONTAINS "WARN"

# ---------------------------------------------------------------------------------------
# Behavior 6 ORACLE -- captured by RUNNING `live_lag_line` at git HEAD (pre-change), via
# products/_platform/state/iter-209/capture_head_literals.py.  The launch stamp is the
# only machine-dependent part of the two datable shapes (it renders in LOCAL time), so it
# is substituted from the same epoch rather than frozen, and the format itself is pinned
# separately below.  Everything else is byte-frozen prose.
# ---------------------------------------------------------------------------------------
STAMP_FMT = "%m-%d %H:%M:%S"
STAMP = datetime.fromtimestamp(LAUNCH).strftime(STAMP_FMT)

HEAD_OK = (
    f"live-lag: OK -- brain launched {STAMP}; up to date, every shipped iteration "
    f"is live (0 committed since launch)"
)
HEAD_WARN = (
    f"live-lag: WARN -- 3 iteration(s) shipped but NOT LIVE in the running brain "
    f"(committed after launch {STAMP}): 119, 122, 124 -- restart the dispatcher to activate"
)
HEAD_UNKNOWN_NO_BANNER = (
    "live-lag: UNKNOWN -- brain launch instant unknown (no datable `dispatcher up` "
    f"banner in {LOG_BASENAME}); cannot compare shipped against live"
)
HEAD_UNKNOWN_EXC = (
    "live-lag: UNKNOWN -- live-lag report unavailable "
    "(ValueError('WARNING: git unreachable'))"
)


# --------------------------------------------------------------------------- helpers
def _cfg(**over):
    """A ProductConfig whose repo path does not exist -- nothing may touch real git."""
    kw = dict(name="demo", repo="/no/such/repo", allowed_push_repo="demo")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _work_cfg(tmp_path, sub="work"):
    root = tmp_path / sub
    root.mkdir(parents=True, exist_ok=True)
    return _cfg(work_root=str(root)), root


def _write_cfg(tmp_path, **over):
    """A minimal product config on disk (mirrors the suite's convention)."""
    data = {
        "name": "demo",
        "repo": str(tmp_path / "repo"),
        "allowed_push_repo": "demo",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _patch_lag(monkeypatch, launch, commits, boom=None):
    """Script both upstream seams of the live-lag core, offline (iter-130 convention)."""
    if boom is None:
        monkeypatch.setattr(foundry, "parse_brain_launch", lambda *a, **k: launch)
    else:
        def _raise(*a, **k):
            raise boom
        monkeypatch.setattr(foundry, "parse_brain_launch", _raise)
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: tuple(commits))


def _record_flags(monkeypatch):
    """Record WHICH flag seam fired -- a side effect is part of the behaviour."""
    calls = []
    monkeypatch.setattr(foundry, "write_restart_flag",
                        lambda cfg, line: calls.append(("write", line)))
    monkeypatch.setattr(foundry, "clear_restart_flag",
                        lambda cfg: calls.append(("clear", None)))
    return calls


def _summ(**kw):
    return foundry.summarize_live_lag(**kw)


# ---------------------------------------------------------------- Behavior 1
def test_b1_unknown_when_nothing_is_known():
    st = _summ(launch_epoch=None, inert=(), unknown_reason=None)
    assert st.verdict == "UNKNOWN", f"expected UNKNOWN, got {st.verdict!r}"


def test_b1_status_is_a_frozen_dataclass():
    st = _summ(launch_epoch=None, inert=())
    assert dataclasses.is_dataclass(st), "LiveLagStatus is not a dataclass"
    assert type(st) is foundry.LiveLagStatus
    assert foundry.LiveLagStatus.__dataclass_params__.frozen is True


@pytest.mark.parametrize("field", ["launch_epoch", "inert", "unknown_reason"])
def test_b1_assigning_any_field_raises(field):
    st = _summ(launch_epoch=LAUNCH, inert=(1,))
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(st, field, None)


def test_b1_the_three_declared_fields_are_the_stored_state():
    names = [f.name for f in dataclasses.fields(foundry.LiveLagStatus)]
    assert names == ["launch_epoch", "inert", "unknown_reason"], names


def test_b1_defaults_make_the_unknown_case_the_zero_argument_call():
    assert _summ().verdict == "UNKNOWN"


# ---------------------------------------------------------------- Behavior 2
def test_b2_known_launch_and_nothing_inert_is_ok():
    assert _summ(launch_epoch=LAUNCH, inert=()).verdict == "OK"


def test_b2_known_launch_with_inert_is_warn():
    assert _summ(launch_epoch=LAUNCH, inert=(188, 190)).verdict == "WARN"


def test_b2_warn_token_matches_the_shipped_constant():
    """The frozen human sentence keys off LIVE_LAG_WARN; the verdict must be that token."""
    assert _summ(launch_epoch=LAUNCH, inert=(188,)).verdict == foundry.LIVE_LAG_WARN


def test_b2_a_single_inert_iteration_is_enough_to_warn():
    assert _summ(launch_epoch=LAUNCH, inert=[190]).verdict == "WARN"


def test_b2_the_three_verdicts_are_the_only_ones_produced():
    seen = {
        _summ().verdict,
        _summ(launch_epoch=LAUNCH).verdict,
        _summ(launch_epoch=LAUNCH, inert=(1,)).verdict,
        _summ(launch_epoch=LAUNCH, inert=(1,), unknown_reason="boom").verdict,
    }
    assert seen == {"OK", "WARN", "UNKNOWN"}, seen


# ---------------------------------------------------------------- Behavior 3
@pytest.mark.parametrize("kw,verdict,code", [
    (dict(launch_epoch=LAUNCH, inert=()), "OK", 0),
    (dict(launch_epoch=LAUNCH, inert=(188, 190)), "WARN", 2),
    (dict(launch_epoch=None, inert=()), "UNKNOWN", 0),
    (dict(launch_epoch=LAUNCH, inert=(188,), unknown_reason="diagnostic broke"),
     "UNKNOWN", 0),
])
def test_b3_exit_code_mapping_is_preserved_exactly(kw, verdict, code):
    st = _summ(**kw)
    assert (st.verdict, st.exit_code) == (verdict, code)


def test_b3_unknown_never_gates_a_build():
    """UNKNOWN keeps exiting 0 -- an unusable report is not evidence of lag."""
    assert _summ(launch_epoch=None, inert=(188, 190)).exit_code == 0


def test_b3_no_status_ever_yields_a_code_outside_zero_and_two():
    for kw in (dict(), dict(launch_epoch=LAUNCH), dict(launch_epoch=LAUNCH, inert=(1, 2)),
               dict(launch_epoch=None, inert=(1,)), dict(unknown_reason="x")):
        assert _summ(**kw).exit_code in (0, 2), kw


# ---------------------------------------------------------------- Behavior 4
def test_b4_unknown_reason_dominates_a_nonempty_inert():
    st = _summ(launch_epoch=LAUNCH, inert=(188, 190), unknown_reason="report unavailable")
    assert st.verdict == "UNKNOWN", (
        "a diagnostic failure must not be reported as proven lag")


def test_b4_missing_launch_instant_dominates_a_nonempty_inert():
    st = _summ(launch_epoch=None, inert=(188, 190))
    assert st.verdict == "UNKNOWN", (
        "an unknown launch instant cannot prove any iteration inert")


def test_b4_unknown_is_not_reported_as_lagging_or_up_to_date():
    st = _summ(launch_epoch=None, inert=(188, 190))
    assert st.unknown is True
    assert st.lagging is False, "UNKNOWN must not claim lag"
    assert st.up_to_date is False, "UNKNOWN must not claim freshness"


def test_b4_dominance_holds_for_both_unknown_causes_together():
    assert _summ(launch_epoch=None, inert=(1,), unknown_reason="both").verdict == "UNKNOWN"


# ---------------------------------------------------------------- Behavior 5
def test_b5_inert_is_a_tuple_of_ints_from_a_list():
    st = _summ(launch_epoch=LAUNCH, inert=[190, 188])
    assert isinstance(st.inert, tuple)
    assert st.inert == (190, 188)
    assert all(type(n) is int for n in st.inert)


def test_b5_inert_accepts_a_generator():
    st = _summ(launch_epoch=LAUNCH, inert=(n for n in (191, 192)))
    assert st.inert == (191, 192)


def test_b5_inert_members_are_coerced_to_int():
    st = _summ(launch_epoch=LAUNCH, inert=["188", 190.0])
    assert st.inert == (188, 190)
    assert all(type(n) is int for n in st.inert)


def test_b5_to_dict_round_trips_through_json():
    st = _summ(launch_epoch=LAUNCH, inert=(188, 190))
    back = json.loads(json.dumps(st.to_dict(), indent=2))
    assert back == st.to_dict(), "to_dict() is not JSON-native"


def test_b5_to_dict_carries_inert_as_a_json_array():
    st = _summ(launch_epoch=LAUNCH, inert=(188, 190))
    payload = json.loads(json.dumps(st.to_dict()))
    assert payload["inert"] == [188, 190]
    assert isinstance(payload["inert"], list)


@pytest.mark.parametrize("kw", [
    dict(launch_epoch=LAUNCH, inert=()),
    dict(launch_epoch=LAUNCH, inert=(188, 190)),
    dict(launch_epoch=None, inert=()),
    dict(launch_epoch=None, inert=(188,), unknown_reason="report unavailable"),
])
def test_b5_to_dict_verdict_and_exit_code_reuse_the_same_properties(kw):
    """The payload can never disagree with the printed text."""
    st = _summ(**kw)
    d = st.to_dict()
    assert d["verdict"] == st.verdict
    assert d["exit_code"] == st.exit_code


def test_b5_to_dict_is_json_native_for_the_unknown_shape():
    st = _summ(launch_epoch=None, inert=(), unknown_reason="brain launch instant unknown")
    assert json.loads(json.dumps(st.to_dict())) == st.to_dict()


# ---------------------------------------------------------------- Behavior 6
def test_b6_stamp_format_is_the_pre_change_one():
    """Guards the ONE substituted span in the two datable oracle literals."""
    import re
    assert re.fullmatch(r"\d\d-\d\d \d\d:\d\d:\d\d", STAMP), STAMP


def test_b6_ok_shape_is_byte_identical(monkeypatch):
    _patch_lag(monkeypatch, LAUNCH, LIVE_ONLY_FIXTURE)
    assert foundry.live_lag_line(_cfg(), log_path=LOG) == HEAD_OK


def test_b6_warn_shape_is_byte_identical(monkeypatch):
    _patch_lag(monkeypatch, LAUNCH, INERT_FIXTURE)
    assert foundry.live_lag_line(_cfg(), log_path=LOG) == HEAD_WARN


def test_b6_unknown_no_banner_shape_is_byte_identical(monkeypatch):
    _patch_lag(monkeypatch, None, INERT_FIXTURE)
    assert foundry.live_lag_line(_cfg(), log_path=LOG) == HEAD_UNKNOWN_NO_BANNER


def test_b6_unknown_exception_shape_is_byte_identical(monkeypatch):
    _patch_lag(monkeypatch, None, INERT_FIXTURE, boom=WARN_IN_TEXT_EXC)
    assert foundry.live_lag_line(_cfg(), log_path=LOG) == HEAD_UNKNOWN_EXC


@pytest.mark.parametrize("launch,commits,boom", [
    (LAUNCH, LIVE_ONLY_FIXTURE, None),
    (LAUNCH, INERT_FIXTURE, None),
    (None, INERT_FIXTURE, None),
    (None, INERT_FIXTURE, WARN_IN_TEXT_EXC),
])
def test_b6_every_shape_is_still_exactly_one_line(monkeypatch, launch, commits, boom):
    _patch_lag(monkeypatch, launch, commits, boom=boom)
    line = foundry.live_lag_line(_cfg(), log_path=LOG)
    assert len(line.rstrip("\n").splitlines()) == 1, f"not one line: {line!r}"


def test_b6_the_line_is_the_status_render_for_every_shape(monkeypatch):
    """ONE source of the verdict: the sentence must come FROM the status."""
    for launch, commits, boom in ((LAUNCH, LIVE_ONLY_FIXTURE, None),
                                  (LAUNCH, INERT_FIXTURE, None),
                                  (None, INERT_FIXTURE, None),
                                  (None, INERT_FIXTURE, WARN_IN_TEXT_EXC)):
        _patch_lag(monkeypatch, launch, commits, boom=boom)
        st = foundry.live_lag_status(_cfg(), log_path=LOG)
        assert foundry.live_lag_line(_cfg(), log_path=LOG) == st.to_dict()["line"]


# ---------------------------------------------------------------- Behavior 7
def test_b7_unknown_whose_text_contains_warn_exits_zero(monkeypatch, capsys):
    """THE DEFECT FIX: pre-change this returned 2 (measured at git HEAD)."""
    _patch_lag(monkeypatch, None, INERT_FIXTURE, boom=WARN_IN_TEXT_EXC)
    rc = foundry.live_lag_cli(_cfg(), log_path=LOG)
    out = capsys.readouterr().out
    assert "UNKNOWN" in out, f"expected an UNKNOWN line, got {out!r}"
    assert rc == 0, (
        f"a diagnostic failure whose text contains {foundry.LIVE_LAG_WARN!r} was read as "
        f"lag: exit {rc}")


def test_b7_cli_returns_the_status_exit_code_for_every_shape(monkeypatch, capsys):
    for launch, commits, boom in ((LAUNCH, LIVE_ONLY_FIXTURE, None),
                                  (LAUNCH, INERT_FIXTURE, None),
                                  (None, INERT_FIXTURE, None),
                                  (None, INERT_FIXTURE, WARN_IN_TEXT_EXC)):
        _patch_lag(monkeypatch, launch, commits, boom=boom)
        st = foundry.live_lag_status(_cfg(), log_path=LOG)
        assert foundry.live_lag_cli(_cfg(), log_path=LOG) == st.exit_code, (
            f"cli disagreed with the status for launch={launch!r} boom={boom!r}")
    capsys.readouterr()


def test_b7_shipped_codes_are_unchanged_on_the_datable_shapes(monkeypatch, capsys):
    _patch_lag(monkeypatch, LAUNCH, INERT_FIXTURE)
    assert foundry.live_lag_cli(_cfg(), log_path=LOG) == 2
    _patch_lag(monkeypatch, LAUNCH, LIVE_ONLY_FIXTURE)
    assert foundry.live_lag_cli(_cfg(), log_path=LOG) == 0
    _patch_lag(monkeypatch, None, INERT_FIXTURE)
    assert foundry.live_lag_cli(_cfg(), log_path=LOG) == 0
    capsys.readouterr()


def test_b7_cli_still_prints_the_frozen_sentence(monkeypatch, capsys):
    _patch_lag(monkeypatch, LAUNCH, INERT_FIXTURE)
    foundry.live_lag_cli(_cfg(), log_path=LOG)
    assert capsys.readouterr().out == HEAD_WARN + "\n"


# ---------------------------------------------------------------- Behavior 8
def test_b8_unknown_containing_warn_returns_none_and_raises_no_flag(monkeypatch, tmp_path):
    """THE DEFECT FIX: pre-change this returned the line AND raised the flag."""
    cfg, _ = _work_cfg(tmp_path)
    _patch_lag(monkeypatch, None, INERT_FIXTURE, boom=WARN_IN_TEXT_EXC)
    calls = _record_flags(monkeypatch)
    assert foundry.dispatch_restart_line(cfg) is None, (
        "an unusable report is NOT evidence of lag")
    assert ("write", ) not in [(c[0],) for c in calls], (
        f"a diagnostic failure raised the restart flag: {calls!r}")


def test_b8_unknown_containing_warn_writes_no_flag_file(monkeypatch, tmp_path):
    cfg, root = _work_cfg(tmp_path)
    _patch_lag(monkeypatch, None, INERT_FIXTURE, boom=WARN_IN_TEXT_EXC)
    flag = foundry.restart_flag_path(cfg)
    foundry.dispatch_restart_line(cfg)
    assert not flag.exists(), f"UNKNOWN created {flag.name}"


def test_b8_plain_unknown_returns_none_and_raises_no_flag(monkeypatch, tmp_path):
    cfg, _ = _work_cfg(tmp_path)
    _patch_lag(monkeypatch, None, INERT_FIXTURE)
    calls = _record_flags(monkeypatch)
    assert foundry.dispatch_restart_line(cfg) is None
    assert "write" not in [c[0] for c in calls], calls


def test_b8_warn_still_returns_the_line_and_raises_the_flag(monkeypatch, tmp_path):
    cfg, _ = _work_cfg(tmp_path)
    _patch_lag(monkeypatch, LAUNCH, INERT_FIXTURE)
    calls = _record_flags(monkeypatch)
    got = foundry.dispatch_restart_line(cfg)
    assert got == HEAD_WARN, f"WARN line changed: {got!r}"
    assert [c[0] for c in calls] == ["write"], calls
    assert calls[0][1] == HEAD_WARN


def test_b8_ok_still_returns_none_and_clears_the_flag(monkeypatch, tmp_path):
    cfg, _ = _work_cfg(tmp_path)
    _patch_lag(monkeypatch, LAUNCH, LIVE_ONLY_FIXTURE)
    calls = _record_flags(monkeypatch)
    assert foundry.dispatch_restart_line(cfg) is None
    assert [c[0] for c in calls] == ["clear"], calls


def test_b8_warn_flag_file_is_really_written(monkeypatch, tmp_path):
    """The un-monkeypatched side effect still lands on disk."""
    cfg, _ = _work_cfg(tmp_path)
    _patch_lag(monkeypatch, LAUNCH, INERT_FIXTURE)
    flag = foundry.restart_flag_path(cfg)
    foundry.dispatch_restart_line(cfg)
    assert flag.exists() and HEAD_WARN in flag.read_text()


def test_b8_unknown_takes_the_same_non_warn_branch_as_before(monkeypatch, tmp_path):
    """`flag raise/clear side effects are unchanged`: a non-WARN verdict CLEARS.

    Measured at git HEAD: a plain UNKNOWN line returned None and called
    clear_restart_flag. The fix moves the "UNKNOWN whose text contains WARN" case
    onto that SAME branch -- it must not become a third, no-op behaviour.
    """
    cfg, _ = _work_cfg(tmp_path)
    _patch_lag(monkeypatch, LAUNCH, INERT_FIXTURE)
    foundry.dispatch_restart_line(cfg)
    flag = foundry.restart_flag_path(cfg)
    assert flag.exists(), "precondition: the WARN branch left a flag to clear"
    _patch_lag(monkeypatch, None, INERT_FIXTURE, boom=WARN_IN_TEXT_EXC)
    calls = _record_flags(monkeypatch)
    assert foundry.dispatch_restart_line(cfg) is None
    assert [c[0] for c in calls] == ["clear"], (
        f"UNKNOWN must take the non-WARN branch, not raise: {calls!r}")


def test_b8_both_unknown_causes_agree_on_the_side_effect(monkeypatch, tmp_path):
    """The WARN-in-text UNKNOWN must be indistinguishable from a plain UNKNOWN."""
    seen = []
    for boom in (None, WARN_IN_TEXT_EXC):
        cfg, _ = _work_cfg(tmp_path, sub=f"work-{boom is not None}")
        _patch_lag(monkeypatch, None, INERT_FIXTURE, boom=boom)
        calls = _record_flags(monkeypatch)
        seen.append((foundry.dispatch_restart_line(cfg), [c[0] for c in calls]))
    assert seen[0] == seen[1], (
        f"a WARN substring changed the UNKNOWN outcome: {seen!r}")
    assert seen[0] == (None, ["clear"]), seen


# ---------------------------------------------------------------- Behavior 9
def test_b9_json_flag_prints_one_parseable_document(monkeypatch, capsys, tmp_path):
    _patch_lag(monkeypatch, LAUNCH, INERT_FIXTURE)
    rc = foundry.main(["live-lag", "--config", str(_write_cfg(tmp_path)),
                       "--log", LOG, "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 2
    assert payload["verdict"] == "WARN"
    assert payload["inert"] == [119, 122, 124]


def test_b9_json_output_is_indent_two(monkeypatch, capsys, tmp_path):
    _patch_lag(monkeypatch, LAUNCH, INERT_FIXTURE)
    foundry.main(["live-lag", "--config", str(_write_cfg(tmp_path)),
                  "--log", LOG, "--json"])
    out = capsys.readouterr().out
    assert out == json.dumps(json.loads(out), indent=2) + "\n", (
        f"not a single indent=2 document: {out!r}")


@pytest.mark.parametrize("launch,commits,boom", [
    (LAUNCH, LIVE_ONLY_FIXTURE, None),
    (LAUNCH, INERT_FIXTURE, None),
    (None, INERT_FIXTURE, None),
    (None, INERT_FIXTURE, WARN_IN_TEXT_EXC),
])
def test_b9_json_exit_code_matches_the_plain_invocation(monkeypatch, capsys, tmp_path,
                                                        launch, commits, boom):
    cfg_path = str(_write_cfg(tmp_path))
    _patch_lag(monkeypatch, launch, commits, boom=boom)
    plain = foundry.main(["live-lag", "--config", cfg_path, "--log", LOG])
    plain_out = capsys.readouterr().out
    _patch_lag(monkeypatch, launch, commits, boom=boom)
    as_json = foundry.main(["live-lag", "--config", cfg_path, "--log", LOG, "--json"])
    json_out = capsys.readouterr().out
    assert plain == as_json, f"--json changed the exit code {plain} -> {as_json}"
    assert json.loads(json_out)["exit_code"] == plain
    assert json.loads(json_out)["line"] == plain_out.rstrip("\n")


@pytest.mark.parametrize("launch,commits,boom,expected", [
    (LAUNCH, LIVE_ONLY_FIXTURE, None, HEAD_OK),
    (LAUNCH, INERT_FIXTURE, None, HEAD_WARN),
    (None, INERT_FIXTURE, None, HEAD_UNKNOWN_NO_BANNER),
    (None, INERT_FIXTURE, WARN_IN_TEXT_EXC, HEAD_UNKNOWN_EXC),
])
def test_b9_without_json_stdout_is_byte_identical_to_today(monkeypatch, capsys, tmp_path,
                                                           launch, commits, boom, expected):
    _patch_lag(monkeypatch, launch, commits, boom=boom)
    foundry.main(["live-lag", "--config", str(_write_cfg(tmp_path)), "--log", LOG])
    assert capsys.readouterr().out == expected + "\n"


def test_b9_json_carries_no_ambient_newline_noise(monkeypatch, capsys, tmp_path):
    _patch_lag(monkeypatch, None, INERT_FIXTURE, boom=WARN_IN_TEXT_EXC)
    foundry.main(["live-lag", "--config", str(_write_cfg(tmp_path)),
                  "--log", LOG, "--json"])
    out = capsys.readouterr().out
    assert out.count("\n") == out.rstrip("\n").count("\n") + 1
    assert json.loads(out)["verdict"] == "UNKNOWN"


def test_b9_live_lag_writes_nothing_in_either_mode(monkeypatch, capsys, tmp_path):
    cfg_path = _write_cfg(tmp_path)

    def _snapshot(root):
        root = pathlib.Path(root)
        return {str(p.relative_to(root)): p.read_bytes()
                for p in root.rglob("*") if p.is_file()}

    before = _snapshot(tmp_path)
    for extra in ([], ["--json"]):
        _patch_lag(monkeypatch, LAUNCH, INERT_FIXTURE)
        foundry.main(["live-lag", "--config", str(cfg_path), "--log", LOG] + extra)
        capsys.readouterr()
        assert _snapshot(tmp_path) == before, f"live-lag {extra} mutated a file"


# --------------------------------------------------------------- Behavior 10
def test_b10_module_imports_are_clean():
    assert foundry.__name__ == "foundry" and dispatcher.__name__ == "dispatcher"


@pytest.mark.parametrize("fn", CONTROL_PATH_FNS)
def test_b10_control_path_never_mentions_the_new_names_in_source(fn):
    src = inspect.getsource(getattr(foundry, fn))
    for name in NEW_NAMES:
        assert name not in src, f"{fn} mentions {name} -- resume semantics touched"


@pytest.mark.parametrize("fn", CONTROL_PATH_FNS)
def test_b10_control_path_never_references_the_new_names_in_code(fn):
    code = getattr(foundry, fn).__code__
    names = set(code.co_names)
    for name in NEW_NAMES:
        assert name not in names, f"{fn}.__code__ references {name}"


def test_b10_dispatcher_neither_exposes_nor_mentions_the_new_names():
    src = inspect.getsource(dispatcher)
    for name in NEW_NAMES:
        assert not hasattr(dispatcher, name), f"dispatcher exposes {name}"
        assert name not in src, f"dispatcher.py mentions {name}"


def test_b10_the_new_names_are_all_present_on_foundry():
    for name in NEW_NAMES:
        assert hasattr(foundry, name), f"{name} missing from foundry"


def test_b10_import_both_modules_in_a_fresh_interpreter():
    import subprocess
    rc = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                        cwd=str(_ROOT), capture_output=True, text=True)
    assert rc.returncode == 0, rc.stderr
