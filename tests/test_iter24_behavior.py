"""Black-box behaviour tests for iter 24 -- the read-only `foundry single-brain`
launch-preflight subcommand: it reports whether a dispatcher is ALREADY running so
an operator/launch-script can refuse to start a SECOND competing brain (which would
starve the shared model-API token budget). ALL additive in foundry.py:

  * `running_dispatchers(pattern="dispatcher.py") -> tuple[int, ...]` -- the ONE
    monkeypatchable process-scan seam (like iter 01's `power_state`/`head_of_branch`);
    its real subprocess behaviour is out of offline scope and is monkeypatched
    WHOLESALE here (never invoked for real),
  * `SingleBrainStatus` -- a frozen dataclass (fields `pids`, `scan_error`) with the
    derived `unknown`/`safe`/`conflict`/`verdict`/`exit_code` props + `render()`,
  * `summarize_single_brain(pids=(), *, scan_error=None) -> SingleBrainStatus` -- a
    PURE builder,
  * `single_brain_cli(pattern="dispatcher.py") -> int` -- guards the seam, prints
    `status.render()`, returns `status.exit_code`, writes nothing,
  * a `single-brain [--pattern P]` subparser (needs NO `--config`) routed by `main`.

ISOLATION CONTRACT (honored): this file was written from the iter-24 PM spec's
Expected Behaviors (1-11) and the product's own OBSERVABLE behaviour ONLY. The
implementation source (foundry.py / dispatcher.py internals), the engineer's and
reviewer's notes, and `git diff` were NOT read. Every check drives the PUBLIC
interface: the pure `foundry.summarize_single_brain(...)` builder + its dataclass
props/`render()`, the `foundry.single_brain_cli(...)` / `foundry.main(["single-brain",
...])` CLI with the process-scan seam `foundry.running_dispatchers` monkeypatched
WHOLESALE (forced offline -- zero real pgrep/subprocess), and the product's `--help`.
The off-control-path checks (Behavior 11) use only public RUNTIME introspection
(compiled `__code__.co_names`/`co_consts` + `dispatcher` attributes) and the
documented `import foundry, dispatcher` subprocess probe -- NOT the source text.
Fully offline & deterministic: no real network/git/power/pgrep; CLI tests run in a
chdir'd tmp dir and snapshot it before/after to prove the writes-nothing contract.
"""
import dataclasses
import inspect
import io
import json
import pathlib
import shutil
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
NEW_SYMBOLS = (
    "running_dispatchers", "SingleBrainStatus",
    "summarize_single_brain", "single_brain_cli",
)
# these MUST reference none of the new surface (Behavior 11)
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")


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


def _set_scan(monkeypatch, ret=None, exc=None, spy=None):
    """Force the ONE process-scan seam offline. Either return `ret` (a tuple), or
    raise `exc`. `spy` (a list) records each pattern the seam was called with."""
    def fake(pattern="dispatcher.py"):
        if spy is not None:
            spy.append(pattern)
        if exc is not None:
            raise exc
        return ret if ret is not None else ()
    monkeypatch.setattr(foundry, "running_dispatchers", fake)


class _Chk:
    """Minimal stand-in check result for the doctor-CLI regression guard."""
    def __init__(self, name, ok, detail="detail-text"):
        self.name = name
        self.ok = ok
        self.detail = detail


# ==========================================================================
# Behavior 1 -- running_dispatchers is a module-level fn, optional `pattern`
#               defaulting to "dispatcher.py", -> tuple. (Real subprocess out
#               of offline scope: signature-only, never invoked for real.)
# ==========================================================================
def test_b1_running_dispatchers_exists_and_signature():
    assert callable(foundry.running_dispatchers)
    sig = inspect.signature(foundry.running_dispatchers)
    assert list(sig.parameters) == ["pattern"], (
        f"running_dispatchers must take exactly one optional `pattern` arg: {sig}")
    assert sig.parameters["pattern"].default == "dispatcher.py", (
        f"pattern default must be 'dispatcher.py', got {sig.parameters['pattern'].default!r}")


def test_b1_seam_is_monkeypatchable_wholesale(monkeypatch):
    # the contract: the tester replaces the seam wholesale; a patched value is used.
    spy = []
    _set_scan(monkeypatch, ret=(7,), spy=spy)
    assert foundry.running_dispatchers("whatever.py") == (7,)
    assert spy == ["whatever.py"]


# ==========================================================================
# Behavior 2 -- SingleBrainStatus is a frozen dataclass with EXACTLY the two
#               stored fields pids / scan_error
# ==========================================================================
def test_b2_frozen_dataclass_two_fields():
    cls = foundry.SingleBrainStatus
    assert dataclasses.is_dataclass(cls), "SingleBrainStatus must be a dataclass"
    assert cls.__dataclass_params__.frozen is True, "SingleBrainStatus must be frozen"
    assert [f.name for f in dataclasses.fields(cls)] == ["pids", "scan_error"], (
        "SingleBrainStatus must store exactly (pids, scan_error) in that order")


def test_b2_fields_hold_given_values_and_pids_is_tuple():
    s = foundry.summarize_single_brain((111, 222), scan_error=None)
    assert s.pids == (111, 222) and isinstance(s.pids, tuple)
    assert s.scan_error is None
    u = foundry.summarize_single_brain((), scan_error="boom")
    assert u.pids == () and u.scan_error == "boom"


def test_b2_instance_is_frozen():
    s = foundry.summarize_single_brain((1,))
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.pids = (9,)          # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.scan_error = "x"     # type: ignore[misc]


# ==========================================================================
# Behavior 3 -- .unknown is True iff scan_error is not None
# ==========================================================================
def test_b3_unknown_tracks_scan_error():
    assert foundry.summarize_single_brain(()).unknown is False
    assert foundry.summarize_single_brain((1, 2)).unknown is False
    assert foundry.summarize_single_brain((), scan_error="no pgrep").unknown is True
    # even WITH pids, a scan_error still means unknown
    assert foundry.summarize_single_brain((1,), scan_error="partial").unknown is True
    # empty string is "not None" -> unknown (boundary of the `is not None` contract)
    assert foundry.summarize_single_brain((), scan_error="").unknown is True


# ==========================================================================
# Behavior 4 -- conflict/safe partition when known; both False when unknown
# ==========================================================================
def test_b4_known_partition_conflict_vs_safe():
    safe = foundry.summarize_single_brain(())
    assert safe.conflict is False and safe.safe is True
    assert safe.conflict ^ safe.safe          # exactly one True

    for pids in [(1,), (1, 2), (1, 2, 3)]:
        c = foundry.summarize_single_brain(pids)
        assert c.conflict is True and c.safe is False
        assert c.conflict ^ c.safe


def test_b4_unknown_neither_conflict_nor_safe():
    for pids in [(), (1, 2)]:
        u = foundry.summarize_single_brain(pids, scan_error="err")
        assert u.conflict is False and u.safe is False


# ==========================================================================
# Behavior 5 -- verdict string
# ==========================================================================
def test_b5_verdict_precedence():
    assert foundry.summarize_single_brain(()).verdict == "SAFE"
    assert foundry.summarize_single_brain((1, 2)).verdict == "CONFLICT"
    assert foundry.summarize_single_brain((), scan_error="e").verdict == "UNKNOWN"
    # UNKNOWN wins over pids present
    assert foundry.summarize_single_brain((1,), scan_error="e").verdict == "UNKNOWN"


# ==========================================================================
# Behavior 6 -- exit_code mapping (2 unknown / 1 conflict / 0 safe)
# ==========================================================================
def test_b6_exit_code_mapping():
    assert foundry.summarize_single_brain(()).exit_code == 0
    assert foundry.summarize_single_brain((1,)).exit_code == 1
    assert foundry.summarize_single_brain((1, 2, 3)).exit_code == 1
    assert foundry.summarize_single_brain((), scan_error="e").exit_code == 2
    assert foundry.summarize_single_brain((5,), scan_error="e").exit_code == 2


def test_b6_props_never_disagree():
    # every property triple must be internally consistent (AC: never disagree)
    cases = [(), (1,), (1, 2), None]  # None -> use scan_error branch
    for pids in cases:
        if pids is None:
            s = foundry.summarize_single_brain((3, 4), scan_error="oops")
        else:
            s = foundry.summarize_single_brain(pids)
        # verdict <-> exit_code
        assert (s.verdict, s.exit_code) in {("SAFE", 0), ("CONFLICT", 1), ("UNKNOWN", 2)}
        # bool flags map 1:1 to verdict
        if s.verdict == "SAFE":
            assert s.safe and not s.conflict and not s.unknown
        elif s.verdict == "CONFLICT":
            assert s.conflict and not s.safe and not s.unknown
        else:
            assert s.unknown and not s.safe and not s.conflict


# ==========================================================================
# Behavior 7 -- render(): non-empty, multi-line, names verdict; lists PIDs on
#               CONFLICT; includes scan_error on UNKNOWN; says "no dispatcher"
#               on SAFE; never raises
# ==========================================================================
def test_b7_render_safe():
    r = foundry.summarize_single_brain(()).render()
    assert isinstance(r, str) and r.strip()
    assert "\n" in r, "render() must be multi-line"
    assert "SAFE" in r
    assert "dispatcher" in r.lower(), "SAFE render must state no dispatcher is running"


def test_b7_render_conflict_lists_every_pid():
    r = foundry.summarize_single_brain((111, 222, 4242)).render()
    assert isinstance(r, str) and r.strip() and "\n" in r
    assert "CONFLICT" in r
    for pid in ("111", "222", "4242"):
        assert pid in r, f"CONFLICT render must list PID {pid}:\n{r}"


def test_b7_render_unknown_includes_scan_error():
    msg = "pgrep: command not found (xyzzy)"
    r = foundry.summarize_single_brain((), scan_error=msg).render()
    assert isinstance(r, str) and r.strip() and "\n" in r
    assert "UNKNOWN" in r
    assert msg in r, f"UNKNOWN render must include the scan_error text:\n{r}"


def test_b7_render_never_raises_across_branches():
    for s in (
        foundry.summarize_single_brain(()),
        foundry.summarize_single_brain((1, 2)),
        foundry.summarize_single_brain((), scan_error="x"),
        foundry.summarize_single_brain((9,), scan_error="y"),
    ):
        assert isinstance(s.render(), str) and s.render().strip()
        # verdict token is always present in its own render
        assert s.verdict in s.render()


# ==========================================================================
# Behavior 8 -- summarize_single_brain is a PURE builder
# ==========================================================================
def test_b8_examples_from_spec():
    c = foundry.summarize_single_brain((123, 456))
    assert c.conflict is True and c.exit_code == 1
    u = foundry.summarize_single_brain((), scan_error="no pgrep")
    assert u.unknown is True and u.exit_code == 2


def test_b8_pids_normalized_to_tuple_and_scan_error_preserved():
    s = foundry.summarize_single_brain([1, 2, 3])   # a list in
    assert s.pids == (1, 2, 3) and isinstance(s.pids, tuple)
    assert s.scan_error is None
    s2 = foundry.summarize_single_brain((), scan_error="err-text")
    assert s2.scan_error == "err-text"


def test_b8_scan_error_is_keyword_only():
    sig = inspect.signature(foundry.summarize_single_brain)
    assert sig.parameters["scan_error"].kind is inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["pids"].default == ()
    assert sig.parameters["scan_error"].default is None


def test_b8_pure_no_side_effects_and_never_raises(tmp_path, monkeypatch):
    # a pure builder must not touch fs/subprocess; run in a chdir'd tmp + snapshot
    monkeypatch.chdir(tmp_path)
    before = _snapshot_tree(tmp_path)
    # calling it many times with varied inputs must never raise
    for pids, err in [((), None), ((1,), None), ((1, 2), "e"), ((), "e2")]:
        foundry.summarize_single_brain(pids, scan_error=err)
    assert _snapshot_tree(tmp_path) == before, "summarize_single_brain wrote to disk"


# ==========================================================================
# Behavior 9 -- single_brain_cli guards the seam, prints render(), returns
#               exit_code, writes nothing. Forced offline via the seam.
# ==========================================================================
def test_b9_cli_safe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _set_scan(monkeypatch, ret=())
    before = _snapshot_tree(tmp_path)
    rc, out, _ = _capture(lambda: foundry.single_brain_cli())
    assert rc == 0
    assert "SAFE" in out and out.strip()
    assert _snapshot_tree(tmp_path) == before, "single_brain_cli wrote to disk (must be read-only)"


def test_b9_cli_conflict_names_both_pids(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _set_scan(monkeypatch, ret=(111, 222))
    before = _snapshot_tree(tmp_path)
    rc, out, _ = _capture(lambda: foundry.single_brain_cli())
    assert rc == 1
    assert "CONFLICT" in out
    assert "111" in out and "222" in out
    assert _snapshot_tree(tmp_path) == before


def test_b9_cli_unknown_on_seam_exception(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _set_scan(monkeypatch, exc=RuntimeError("no pgrep"))
    before = _snapshot_tree(tmp_path)
    rc, out, _ = _capture(lambda: foundry.single_brain_cli())
    assert rc == 2
    assert "UNKNOWN" in out
    assert "no pgrep" in out, f"UNKNOWN must include the exception text:\n{out}"
    assert _snapshot_tree(tmp_path) == before


def test_b9_cli_matches_summary_render_and_exit(monkeypatch):
    # the CLI's output/exit must equal the pure summary for the same forced state
    _set_scan(monkeypatch, ret=(111, 222))
    rc, out, _ = _capture(lambda: foundry.single_brain_cli())
    expect = foundry.summarize_single_brain((111, 222))
    assert rc == expect.exit_code
    assert out.strip() == expect.render().strip()


def test_b9_cli_default_pattern_and_forwarding(monkeypatch):
    # default pattern is forwarded to the seam
    spy = []
    _set_scan(monkeypatch, ret=(), spy=spy)
    _capture(lambda: foundry.single_brain_cli())
    assert spy == ["dispatcher.py"], f"default pattern must be 'dispatcher.py', got {spy}"
    # a custom pattern is forwarded verbatim
    spy2 = []
    _set_scan(monkeypatch, ret=(), spy=spy2)
    _capture(lambda: foundry.single_brain_cli(pattern="myproc.py"))
    assert spy2 == ["myproc.py"]


def test_b9_cli_signature_default():
    sig = inspect.signature(foundry.single_brain_cli)
    assert sig.parameters["pattern"].default == "dispatcher.py"


# ==========================================================================
# Behavior 10 -- the `single-brain` subcommand: in --help, needs NO --config,
#                dispatches to single_brain_cli(pattern=...), returns its code
# ==========================================================================
def test_b10_help_lists_single_brain():
    foundry_py = pathlib.Path(foundry.__file__).resolve()
    proc = subprocess.run(
        [sys.executable, str(foundry_py), "--help"],
        capture_output=True, text=True, cwd=str(foundry_py.parent),
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "single-brain" in combined, f"single-brain missing from --help:\n{combined}"


def test_b10_subcommand_help_advertises_pattern():
    foundry_py = pathlib.Path(foundry.__file__).resolve()
    proc = subprocess.run(
        [sys.executable, str(foundry_py), "single-brain", "--help"],
        capture_output=True, text=True, cwd=str(foundry_py.parent),
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "--pattern" in combined, f"single-brain --help missing --pattern:\n{combined}"


def test_b10_main_needs_no_config_and_returns_exit_code(tmp_path, monkeypatch):
    # SAFE branch (exit 0) disambiguates a real return from argparse's SystemExit(2)
    monkeypatch.chdir(tmp_path)
    _set_scan(monkeypatch, ret=())
    before = _snapshot_tree(tmp_path)
    rc, out, _ = _capture(lambda: foundry.main(["single-brain"]))
    assert rc == 0, "single-brain must run WITHOUT --config and return 0 in the SAFE branch"
    assert "SAFE" in out
    assert _snapshot_tree(tmp_path) == before, "single-brain wrote to disk (must be read-only)"


def test_b10_main_returns_conflict_and_unknown_codes(monkeypatch):
    _set_scan(monkeypatch, ret=(111, 222))
    rc, out, _ = _capture(lambda: foundry.main(["single-brain"]))
    assert rc == 1 and "CONFLICT" in out and "111" in out and "222" in out

    _set_scan(monkeypatch, exc=RuntimeError("scan broke"))
    rc2, out2, _ = _capture(lambda: foundry.main(["single-brain"]))
    assert rc2 == 2 and "UNKNOWN" in out2 and "scan broke" in out2


def test_b10_main_forwards_pattern_flag(monkeypatch):
    spy = []
    _set_scan(monkeypatch, ret=(), spy=spy)
    _capture(lambda: foundry.main(["single-brain", "--pattern", "custom.py"]))
    assert spy == ["custom.py"], f"--pattern must reach the seam via single_brain_cli: {spy}"


# ==========================================================================
# Behavior 11 -- purely additive / off the control path / invariants preserved
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


def test_b11_both_modules_import():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b11_control_flow_fns_do_not_reference_new_surface():
    for fn in CONTROL_FLOW_FNS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"
        names, consts = _fn_names_consts(getattr(foundry, fn))
        for sym in NEW_SYMBOLS + ("render", "unknown", "conflict"):
            assert sym not in names, (
                f"{fn} references {sym!r} -- the single-brain surface must stay off the control path")
        assert "single-brain" not in consts, f"{fn} embeds the 'single-brain' subcommand string"


def test_b11_dispatcher_untouched_by_new_surface():
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, consts = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in names, f"dispatcher references new symbol {sym!r}"
    assert "single-brain" not in consts, "dispatcher embeds the 'single-brain' subcommand string"


def test_b11_run_doctor_still_four_checks(tmp_path, monkeypatch):
    # doctor's 4-check contract is byte-identical (spec: no 5th check added)
    monkeypatch.setattr(foundry, "power_state", lambda: "Now drawing from 'AC Power'")
    stub = tmp_path / "agent_bin"
    stub.write_text("#!/bin/sh\n")
    ctor = type(foundry.AGENT_BIN)
    try:
        monkeypatch.setattr(foundry, "AGENT_BIN", ctor(str(stub)))
    except Exception:
        monkeypatch.setattr(foundry, "AGENT_BIN", str(stub))
    monkeypatch.setattr(shutil, "which", lambda *a, **k: "/opt/homebrew/bin/uv")
    monkeypatch.setattr(foundry, "head_of_branch", lambda *a, **k: "abc1234")

    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    res = foundry.run_doctor(cfg)
    assert [c.name for c in res] == ["power", "agent", "uv", "remote"], (
        "run_doctor's 4-check contract regressed")


def test_b11_doctor_cli_still_four_checks(tmp_path, capsys, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    monkeypatch.setattr(foundry, "check_power", lambda *a, **k: _Chk("power", True))
    monkeypatch.setattr(foundry, "check_agent", lambda *a, **k: _Chk("agent", True))
    monkeypatch.setattr(foundry, "check_uv", lambda *a, **k: _Chk("uv", True))
    monkeypatch.setattr(foundry, "check_remote", lambda *a, **k: _Chk("remote", True))
    rc = foundry.main(["doctor", "--config", str(cfg_path)])
    out = capsys.readouterr().out
    assert rc == 0
    for name in ("power", "agent", "uv", "remote"):
        assert name in out


def test_b11_sentinels_and_status_vocab_unchanged():
    _, consts = _module_names_consts(foundry)
    for sentinel in ("VERDICT:", "RESULT:", "ACTION:", "POSTRELEASE:"):
        assert any(sentinel in c for c in consts), f"sentinel prefix {sentinel!r} vanished from foundry"
    for status in ("shipped", "no-ship", "infra-fail"):
        assert status in consts, f"res['status'] value {status!r} vanished from foundry"
