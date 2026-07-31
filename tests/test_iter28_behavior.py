"""Black-box behaviour tests for iter 28 -- the read-only `foundry preflight`
composite LAUNCH gate. It fuses the env preflight (`doctor`, iter 01) and the
single-brain preflight (`single-brain`, iter 24) into ONE three-way, exit-coded
GO / NO-GO / CAUTION verdict (human text + `--json`) that an operator or launch
wrapper runs before starting `dispatcher.py`. ALL additive in foundry.py, reusing
the EXISTING cores (`run_doctor`/`doctor_ok`/`Check` and `running_dispatchers`/
`summarize_single_brain`/`SingleBrainStatus`); no new I/O seam:

  * `PreflightSummary(checks, brain)` -- a frozen dataclass with derived props
    `env_ready`/`verdict`/`exit_code` + `render()`/`to_dict()`,
  * `summarize_preflight(*, checks, brain) -> PreflightSummary` -- a PURE,
    keyword-only builder,
  * `preflight_cli(cfg, pattern="dispatcher.py", as_json=False) -> int` -- a thin
    CLI that composes `run_doctor` + the `running_dispatchers` scan, prints the
    report (or one JSON doc), returns the composite exit code, writes nothing,
  * a `preflight [--config C] [--pattern P] [--json]` subparser routed by `main`.

Verdict rule (total, in order): NO-GO iff `not env_ready` OR `brain.conflict`;
else CAUTION iff `brain.unknown`; else GO. Exit map {GO:0, NO-GO:1, CAUTION:2}.

ISOLATION CONTRACT (honored): this file was written from the iter-28 PM spec's
Expected Behaviors (1-14) and the product's own OBSERVABLE behaviour ONLY. The
implementation source (foundry.py / dispatcher.py internals), the engineer's and
reviewer's notes, and `git diff` were NOT read. Every check drives the PUBLIC
interface: the pure `foundry.summarize_preflight(...)` builder + its dataclass
props/`render()`/`to_dict()`, and the `foundry.preflight_cli(...)` /
`foundry.main(["preflight", ...])` CLI with the two composed cores
(`foundry.run_doctor`, `foundry.running_dispatchers`) monkeypatched WHOLESALE
(forced offline -- zero real pgrep/subprocess/git/power/network). Inputs are built
via the product's own public constructors (`foundry.Check`,
`foundry.summarize_single_brain`). The off-control-path invariant checks use only
public RUNTIME introspection (compiled `__code__.co_names`/`co_consts` +
`dispatcher` attributes) and the documented `import foundry, dispatcher` subprocess
probe -- NOT the source text. Fully offline & deterministic; CLI tests snapshot
the work tree before/after to prove the writes-nothing contract.
"""
import dataclasses
import inspect
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


# --------------------------------------------------------------------------
# constants / helpers
# --------------------------------------------------------------------------
DOCTOR_NAMES = ("power", "agent", "uv", "remote")
EXIT_MAP = {"GO": 0, "NO-GO": 1, "CAUTION": 2}
NEW_SYMBOLS = ("PreflightSummary", "summarize_preflight", "preflight_cli")
# the control-flow / pipeline fns must reference NONE of the new surface
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")


def _checks(power=True, agent=True, uv=True, remote=True):
    """Build the four doctor `Check`s via the product's own public constructor."""
    oks = {"power": power, "agent": agent, "uv": uv, "remote": remote}
    return tuple(foundry.Check(n, oks[n], f"detail-{n}") for n in DOCTOR_NAMES)


def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir (mirrors the suite's convention)."""
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


def _snapshot_tree(root):
    """Map {relative-path: bytes} for every file under root (no-write proof)."""
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*") if p.is_file()
    }


def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY; return (rc, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _set_doctor(monkeypatch, checks):
    """Force the env-preflight core to return `checks` wholesale (offline)."""
    monkeypatch.setattr(foundry, "run_doctor", lambda cfg: list(checks))


def _set_scan(monkeypatch, ret=None, exc=None, spy=None):
    """Force the single-brain process-scan seam offline: return `ret` (a tuple)
    or raise `exc`. `spy` (a list) records each pattern the seam was called with."""
    def fake(pattern="dispatcher.py"):
        if spy is not None:
            spy.append(pattern)
        if exc is not None:
            raise exc
        return ret if ret is not None else ()
    monkeypatch.setattr(foundry, "running_dispatchers", fake)


@pytest.fixture
def cfg(tmp_path):
    return foundry.load_config(str(_write_cfg(tmp_path)))


def _last_nonempty_line(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


# ==========================================================================
# Behavior 1 -- GO (all green)
# ==========================================================================
def test_b1_go_all_green():
    s = foundry.summarize_preflight(
        checks=_checks(), brain=foundry.summarize_single_brain(()))
    assert s.verdict == "GO"
    assert s.exit_code == 0
    assert s.env_ready is True


# ==========================================================================
# Behavior 2 -- NO-GO on broken env (>=1 check .ok=False, brain SAFE)
# ==========================================================================
def test_b2_no_go_broken_env():
    s = foundry.summarize_preflight(
        checks=_checks(agent=False), brain=foundry.summarize_single_brain(()))
    assert s.verdict == "NO-GO"
    assert s.exit_code == 1
    assert s.env_ready is False


def test_b2_any_single_failing_check_forces_no_go():
    # each individual failing check independently forces NO-GO
    for bad in DOCTOR_NAMES:
        s = foundry.summarize_preflight(
            checks=_checks(**{bad: False}),
            brain=foundry.summarize_single_brain(()))
        assert s.verdict == "NO-GO" and s.exit_code == 1, bad


# ==========================================================================
# Behavior 3 -- NO-GO on competing brain (conflict), env all green
# ==========================================================================
def test_b3_no_go_competing_brain():
    s = foundry.summarize_preflight(
        checks=_checks(), brain=foundry.summarize_single_brain((123,)))
    assert s.verdict == "NO-GO"
    assert s.exit_code == 1
    assert s.env_ready is True  # env is fine; the rival brain is the blocker


# ==========================================================================
# Behavior 4 -- CAUTION (env ready, brain uncheckable -> UNKNOWN)
# ==========================================================================
def test_b4_caution_brain_uncheckable():
    s = foundry.summarize_preflight(
        checks=_checks(),
        brain=foundry.summarize_single_brain((), scan_error="no pgrep"))
    assert s.verdict == "CAUTION"
    assert s.exit_code == 2
    assert s.env_ready is True


# ==========================================================================
# Behavior 5 -- hard env blocker DOMINATES an UNKNOWN brain (never CAUTION)
# ==========================================================================
def test_b5_hard_blocker_dominates_unknown():
    s = foundry.summarize_preflight(
        checks=_checks(power=False),
        brain=foundry.summarize_single_brain((), scan_error="no pgrep"))
    assert s.verdict == "NO-GO"
    assert s.exit_code == 1
    assert s.env_ready is False


# ==========================================================================
# Behavior 6 -- both blockers (env bad AND conflict) still NO-GO
# ==========================================================================
def test_b6_both_blockers_no_go():
    s = foundry.summarize_preflight(
        checks=_checks(uv=False), brain=foundry.summarize_single_brain((99, 100)))
    assert s.verdict == "NO-GO"
    assert s.exit_code == 1
    assert s.env_ready is False


# ==========================================================================
# Behavior 7 -- env_ready semantics: all-ok True; any-fail False; empty vacuous True
# ==========================================================================
def test_b7_env_ready_all_ok_true():
    s = foundry.summarize_preflight(
        checks=_checks(), brain=foundry.summarize_single_brain(()))
    assert s.env_ready is True


def test_b7_env_ready_any_false_is_false():
    s = foundry.summarize_preflight(
        checks=_checks(remote=False), brain=foundry.summarize_single_brain(()))
    assert s.env_ready is False


def test_b7_env_ready_empty_is_vacuously_true():
    # matches doctor_ok([]) is True
    assert foundry.doctor_ok([]) is True
    s = foundry.summarize_preflight(
        checks=(), brain=foundry.summarize_single_brain(()))
    assert s.env_ready is True
    # empty env + safe brain -> GO
    assert s.verdict == "GO" and s.exit_code == 0


# ==========================================================================
# Behavior 8 -- verdict / exit-code self-consistency for EVERY constructible state
# ==========================================================================
def test_b8_verdict_exit_self_consistent_matrix():
    env_states = {
        "all-ok": _checks(),
        "one-bad": _checks(agent=False),
        "empty": (),
    }
    brain_states = {
        "safe": foundry.summarize_single_brain(()),
        "conflict": foundry.summarize_single_brain((7,)),
        "unknown": foundry.summarize_single_brain((), scan_error="e"),
    }
    for en, checks in env_states.items():
        for bn, brain in brain_states.items():
            s = foundry.summarize_preflight(checks=checks, brain=brain)
            # exit code is ALWAYS the map of the verdict -- can never disagree
            assert s.exit_code == EXIT_MAP[s.verdict], (en, bn, s.verdict, s.exit_code)
            assert s.verdict in EXIT_MAP
            # render's declared exit matches exit_code
            assert f"(exit {s.exit_code})" in _last_nonempty_line(s.render())


def test_b8_render_token_and_exit_never_disagree():
    for checks in (_checks(), _checks(uv=False), ()):
        for brain in (
            foundry.summarize_single_brain(()),
            foundry.summarize_single_brain((5,)),
            foundry.summarize_single_brain((), scan_error="x"),
        ):
            s = foundry.summarize_preflight(checks=checks, brain=brain)
            last = _last_nonempty_line(s.render())
            assert last == f"verdict: {s.verdict} (exit {s.exit_code})", last


# ==========================================================================
# Behavior 9 -- render(): non-empty, multi-line, names verdict, one prefixed
#               line per check, brain token, exact last line; never raises
# ==========================================================================
def test_b9_render_go_content():
    s = foundry.summarize_preflight(
        checks=_checks(), brain=foundry.summarize_single_brain(()))
    r = s.render()
    assert isinstance(r, str) and r.strip()
    assert "\n" in r, "render() must be multi-line"
    assert "GO" in r
    for name in DOCTOR_NAMES:
        assert name in r, f"render must name check {name!r}:\n{r}"
    assert "[PASS]" in r  # all four checks pass -> PASS prefixes present
    assert "SAFE" in r    # single-brain verdict token
    assert _last_nonempty_line(r) == "verdict: GO (exit 0)"


def test_b9_render_marks_failed_checks():
    s = foundry.summarize_preflight(
        checks=_checks(agent=False),
        brain=foundry.summarize_single_brain((), scan_error="no pgrep"))
    r = s.render()
    assert "[FAIL]" in r and "[PASS]" in r
    # the failing check name appears on a FAIL line
    fail_lines = [ln for ln in r.splitlines() if "[FAIL]" in ln]
    assert any("agent" in ln for ln in fail_lines), r
    assert "UNKNOWN" in r  # brain token
    assert _last_nonempty_line(r) == "verdict: NO-GO (exit 1)"


def test_b9_render_never_raises_across_branches():
    for checks in (_checks(), _checks(power=False), ()):
        for brain in (
            foundry.summarize_single_brain(()),
            foundry.summarize_single_brain((1, 2)),
            foundry.summarize_single_brain((), scan_error="err"),
        ):
            s = foundry.summarize_preflight(checks=checks, brain=brain)
            r = s.render()
            assert isinstance(r, str) and r.strip() and "\n" in r
            assert s.verdict in r


# ==========================================================================
# Behavior 10 -- to_dict(): exact keys, ordered checks, brain reuse, round-trips
# ==========================================================================
def test_b10_to_dict_exact_keys_and_shape():
    brain = foundry.summarize_single_brain((), scan_error="no pgrep")
    checks = _checks(agent=False)
    s = foundry.summarize_preflight(checks=checks, brain=brain)
    d = s.to_dict()
    assert list(d.keys()) == ["checks", "env_ready", "brain", "verdict", "exit_code"]
    # checks array: {name, ok, detail} in the SAME order as the stored checks
    assert [c["name"] for c in d["checks"]] == list(DOCTOR_NAMES)
    for src, obj in zip(checks, d["checks"]):
        assert obj == {"name": src.name, "ok": src.ok, "detail": src.detail}
    # brain equals the nested SingleBrainStatus.to_dict()
    assert d["brain"] == brain.to_dict()
    # env_ready / verdict / exit_code REUSE the frozen properties (not re-derived)
    assert d["env_ready"] == s.env_ready
    assert d["verdict"] == s.verdict
    assert d["exit_code"] == s.exit_code


def test_b10_to_dict_json_roundtrips():
    s = foundry.summarize_preflight(
        checks=_checks(remote=False), brain=foundry.summarize_single_brain((1, 2)))
    d = s.to_dict()
    dumped = json.dumps(d)  # must not raise
    assert json.loads(dumped) == d
    # payload can never disagree with render()/exit code
    assert d["verdict"] == s.verdict
    assert d["exit_code"] == s.exit_code
    assert f"(exit {d['exit_code']})" in _last_nonempty_line(s.render())


# ==========================================================================
# Behavior 11 -- summarize_preflight is PURE + TOTAL: keyword-only, normalizes
#                checks to tuple, stores brain verbatim, deterministic, no writes
# ==========================================================================
def test_b11_keyword_only_signature():
    sig = inspect.signature(foundry.summarize_preflight)
    assert list(sig.parameters) == ["checks", "brain"]
    for p in sig.parameters.values():
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, (p.name, p.kind)


def test_b11_normalizes_checks_to_tuple_and_stores_brain_verbatim():
    brain = foundry.summarize_single_brain((1,))
    s = foundry.summarize_preflight(checks=list(_checks()), brain=brain)  # a list in
    assert isinstance(s.checks, tuple)
    assert s.brain is brain  # stored verbatim (same object)


def test_b11_deterministic_equal_by_value():
    a = foundry.summarize_preflight(
        checks=list(_checks()), brain=foundry.summarize_single_brain(()))
    b = foundry.summarize_preflight(
        checks=tuple(_checks()), brain=foundry.summarize_single_brain(()))
    assert a == b, "same inputs must yield EQUAL PreflightSummary (frozen value eq)"


def test_b11_frozen_instance():
    s = foundry.summarize_preflight(
        checks=_checks(), brain=foundry.summarize_single_brain(()))
    assert dataclasses.is_dataclass(type(s))
    assert type(s).__dataclass_params__.frozen is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.checks = ()  # type: ignore[misc]


def test_b11_pure_no_writes_and_never_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = _snapshot_tree(tmp_path)
    for checks in (_checks(), _checks(uv=False), (), list(_checks())):
        for brain in (
            foundry.summarize_single_brain(()),
            foundry.summarize_single_brain((1, 2, 3)),
            foundry.summarize_single_brain((), scan_error="e"),
            foundry.summarize_single_brain((9,), scan_error="e"),  # unknown-with-pids
        ):
            s = foundry.summarize_preflight(checks=checks, brain=brain)
            s.render(); s.to_dict(); _ = (s.env_ready, s.verdict, s.exit_code)
    assert _snapshot_tree(tmp_path) == before, "summarize_preflight/props wrote to disk"


# ==========================================================================
# Behavior 12 -- CLI human path: composes both cores by BARE name (monkeypatch
#                bites), prints render(), returns exit_code, writes NOTHING
# ==========================================================================
def test_b12_cli_human_go(cfg, tmp_path, monkeypatch):
    _set_doctor(monkeypatch, _checks())
    _set_scan(monkeypatch, ret=())
    before = _snapshot_tree(tmp_path)
    rc, out, _ = _capture(lambda: foundry.preflight_cli(cfg))
    assert rc == 0
    assert "GO" in out and out.strip()
    assert _last_nonempty_line(out) == "verdict: GO (exit 0)"
    assert _snapshot_tree(tmp_path) == before, "preflight_cli wrote to disk (must be read-only)"


def test_b12_cli_returns_each_exit_code(cfg, monkeypatch):
    # NO-GO on env
    _set_doctor(monkeypatch, _checks(agent=False))
    _set_scan(monkeypatch, ret=())
    rc, out, _ = _capture(lambda: foundry.preflight_cli(cfg))
    assert rc == 1 and "NO-GO" in out
    # NO-GO on conflict
    _set_doctor(monkeypatch, _checks())
    _set_scan(monkeypatch, ret=(321,))
    rc, out, _ = _capture(lambda: foundry.preflight_cli(cfg))
    # spec B9: the composite render surfaces the single-brain VERDICT TOKEN, not PIDs
    assert rc == 1 and "NO-GO" in out and "CONFLICT" in out
    # CAUTION on unknown
    _set_scan(monkeypatch, ret=())
    _set_doctor(monkeypatch, _checks())
    _set_scan(monkeypatch, exc=RuntimeError("scan broke"))
    rc, out, _ = _capture(lambda: foundry.preflight_cli(cfg))
    assert rc == 2 and "CAUTION" in out


def test_b12_cli_output_equals_pure_summary(cfg, monkeypatch):
    _set_doctor(monkeypatch, _checks(uv=False))
    _set_scan(monkeypatch, ret=(555,))
    rc, out, _ = _capture(lambda: foundry.preflight_cli(cfg))
    expect = foundry.summarize_preflight(
        checks=_checks(uv=False), brain=foundry.summarize_single_brain((555,)))
    assert rc == expect.exit_code
    assert out.strip() == expect.render().strip()


def test_b12_cli_default_pattern_forwarded_to_scan(cfg, monkeypatch):
    _set_doctor(monkeypatch, _checks())
    spy = []
    _set_scan(monkeypatch, ret=(), spy=spy)
    _capture(lambda: foundry.preflight_cli(cfg))
    assert spy == ["dispatcher.py"], f"default scan pattern must be 'dispatcher.py': {spy}"


def test_b12_cli_signature_defaults():
    sig = inspect.signature(foundry.preflight_cli)
    assert sig.parameters["pattern"].default == "dispatcher.py"
    assert sig.parameters["as_json"].default is False


# ==========================================================================
# Behavior 13 -- CLI JSON path: EXACTLY one json.dumps(to_dict, indent=2), parses,
#                round-trips, SAME exit code as human; default stays human render
# ==========================================================================
def test_b13_cli_json_is_one_parseable_indented_doc(cfg, monkeypatch):
    _set_doctor(monkeypatch, _checks(agent=False))
    _set_scan(monkeypatch, ret=())
    rc, out, _ = _capture(lambda: foundry.preflight_cli(cfg, as_json=True))
    doc = json.loads(out)  # exactly one JSON doc -> parses
    assert list(doc.keys()) == ["checks", "env_ready", "brain", "verdict", "exit_code"]
    expect = foundry.summarize_preflight(
        checks=_checks(agent=False), brain=foundry.summarize_single_brain(()))
    assert out.strip() == json.dumps(expect.to_dict(), indent=2)
    assert rc == expect.exit_code
    assert json.loads(json.dumps(doc)) == doc  # round-trips


def test_b13_json_and_human_same_exit_code(cfg, monkeypatch):
    for doctor_checks, pids in (
        (_checks(), ()),
        (_checks(remote=False), ()),
        (_checks(), (12, 34)),
    ):
        _set_doctor(monkeypatch, doctor_checks)
        _set_scan(monkeypatch, ret=pids)
        rc_human, _, _ = _capture(lambda: foundry.preflight_cli(cfg))
        _set_doctor(monkeypatch, doctor_checks)
        _set_scan(monkeypatch, ret=pids)
        rc_json, out_json, _ = _capture(lambda: foundry.preflight_cli(cfg, as_json=True))
        assert rc_human == rc_json, (doctor_checks, pids)
        json.loads(out_json)  # json path emits valid JSON


def test_b13_default_path_is_human_not_json(cfg, monkeypatch):
    _set_doctor(monkeypatch, _checks())
    _set_scan(monkeypatch, ret=())
    _, out, _ = _capture(lambda: foundry.preflight_cli(cfg))
    # the human render is NOT a JSON document
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)
    assert _last_nonempty_line(out) == "verdict: GO (exit 0)"


def test_b13_json_writes_nothing(cfg, tmp_path, monkeypatch):
    _set_doctor(monkeypatch, _checks())
    _set_scan(monkeypatch, ret=())
    before = _snapshot_tree(tmp_path)
    _capture(lambda: foundry.preflight_cli(cfg, as_json=True))
    assert _snapshot_tree(tmp_path) == before, "JSON preflight_cli wrote to disk"


# ==========================================================================
# Behavior 14 -- scan failure degrades to UNKNOWN (never crashes) + --pattern fwd
# ==========================================================================
def test_b14_scan_raises_env_ready_degrades_to_caution(cfg, monkeypatch):
    _set_doctor(monkeypatch, _checks())
    _set_scan(monkeypatch, exc=RuntimeError("pgrep exploded"))
    rc, out, _ = _capture(lambda: foundry.preflight_cli(cfg))  # must NOT propagate
    assert rc == 2, "env ready + scan failure -> CAUTION exit 2"
    assert "CAUTION" in out and "UNKNOWN" in out


def test_b14_scan_raises_env_bad_stays_no_go(cfg, monkeypatch):
    _set_doctor(monkeypatch, _checks(power=False))
    _set_scan(monkeypatch, exc=RuntimeError("pgrep exploded"))
    rc, out, _ = _capture(lambda: foundry.preflight_cli(cfg))
    assert rc == 1, "confirmed env blocker is NEVER downgraded to CAUTION"
    assert "NO-GO" in out


def test_b14_pattern_forwarded_to_scan(cfg, monkeypatch):
    _set_doctor(monkeypatch, _checks())
    spy = []
    _set_scan(monkeypatch, ret=(), spy=spy)
    _capture(lambda: foundry.preflight_cli(cfg, pattern="myproc.py"))
    assert spy == ["myproc.py"], f"--pattern must reach running_dispatchers: {spy}"


# ==========================================================================
# Subparser wiring (AC): `preflight` registered in main with --config/--pattern/--json
# ==========================================================================
def test_main_help_lists_preflight():
    foundry_py = pathlib.Path(foundry.__file__).resolve()
    proc = subprocess.run(
        [sys.executable, str(foundry_py), "--help"],
        capture_output=True, text=True, cwd=str(foundry_py.parent),
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "preflight" in combined, f"preflight missing from --help:\n{combined}"


def test_preflight_subcommand_help_advertises_flags():
    foundry_py = pathlib.Path(foundry.__file__).resolve()
    proc = subprocess.run(
        [sys.executable, str(foundry_py), "preflight", "--help"],
        capture_output=True, text=True, cwd=str(foundry_py.parent),
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    for flag in ("--config", "--pattern", "--json"):
        assert flag in combined, f"preflight --help missing {flag}:\n{combined}"


def test_main_dispatches_and_returns_exit_code(cfg, tmp_path, monkeypatch):
    # GO branch (exit 0) disambiguates a real return from argparse's SystemExit(2)
    cfg_path = _write_cfg(tmp_path)
    _set_doctor(monkeypatch, _checks())
    _set_scan(monkeypatch, ret=())
    before = _snapshot_tree(tmp_path)
    rc, out, _ = _capture(lambda: foundry.main(["preflight", "--config", str(cfg_path)]))
    assert rc == 0, "preflight via main must return the composite exit code"
    assert "GO" in out
    assert _snapshot_tree(tmp_path) == before, "preflight via main wrote to disk"


def test_main_returns_nonzero_and_forwards_flags(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    # NO-GO on conflict, and confirm --pattern is forwarded through main
    _set_doctor(monkeypatch, _checks())
    spy = []
    _set_scan(monkeypatch, ret=(777,), spy=spy)
    rc, out, _ = _capture(
        lambda: foundry.main(["preflight", "--config", str(cfg_path), "--pattern", "x.py"]))
    assert rc == 1 and "NO-GO" in out and "CONFLICT" in out
    assert spy == ["x.py"], f"main must forward --pattern to the scan: {spy}"


def test_main_json_flag_emits_json(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    _set_doctor(monkeypatch, _checks())
    _set_scan(monkeypatch, ret=())
    rc, out, _ = _capture(
        lambda: foundry.main(["preflight", "--config", str(cfg_path), "--json"]))
    assert rc == 0
    doc = json.loads(out)  # --json must emit a parseable JSON document
    assert doc["verdict"] == "GO" and doc["exit_code"] == 0


# ==========================================================================
# Invariants (AC): purely additive, off the control path, cores untouched
# ==========================================================================
def _fn_names_consts(fn):
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


def _module_names_consts(module):
    names, consts = set(), set()
    for v in vars(module).values():
        if isinstance(v, types.FunctionType):
            n, c = _fn_names_consts(v)
            names |= n
            consts |= c
        elif isinstance(v, type):
            for m in vars(v).values():
                if isinstance(m, types.FunctionType):
                    n, c = _fn_names_consts(m)
                    names |= n
                    consts |= c
    return names, consts


def test_inv_both_modules_import():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_inv_control_flow_fns_do_not_reference_new_surface():
    for fn in CONTROL_FLOW_FNS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing (regression)"
        names, consts = _fn_names_consts(getattr(foundry, fn))
        for sym in NEW_SYMBOLS:
            assert sym not in names, (
                f"{fn} references {sym!r} -- the preflight surface must stay "
                "off the control path")
        assert "preflight" not in consts, f"{fn} embeds the 'preflight' subcommand string"


def test_inv_dispatcher_untouched_by_new_surface():
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, consts = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in names, f"dispatcher references new symbol {sym!r}"
    assert "preflight" not in consts, "dispatcher embeds the 'preflight' subcommand string"


def test_inv_run_doctor_still_four_checks_and_single_brain_intact(cfg, monkeypatch):
    # doctor's 4-check contract (iter 01) and single-brain (iter 24) survive
    import shutil
    monkeypatch.setattr(foundry, "power_state", lambda: "Now drawing from 'AC Power'")
    monkeypatch.setattr(shutil, "which", lambda *a, **k: "/opt/homebrew/bin/uv")
    monkeypatch.setattr(foundry, "head_of_branch", lambda *a, **k: "abc1234")
    ctor = type(foundry.AGENT_BIN)
    # a path that "exists" for the agent check: reuse the loaded module file
    existing = pathlib.Path(foundry.__file__)
    try:
        monkeypatch.setattr(foundry, "AGENT_BIN", ctor(str(existing)))
    except Exception:
        monkeypatch.setattr(foundry, "AGENT_BIN", str(existing))
    res = foundry.run_doctor(cfg)
    assert [c.name for c in res] == list(DOCTOR_NAMES), "run_doctor 4-check contract regressed"
    # single-brain core still returns its expected verdicts
    assert foundry.summarize_single_brain(()).verdict == "SAFE"
    assert foundry.summarize_single_brain((1,)).verdict == "CONFLICT"
    assert foundry.summarize_single_brain((), scan_error="e").verdict == "UNKNOWN"
