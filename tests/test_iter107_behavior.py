"""Black-box behaviour tests for iter 107 -- discovery bite 2 (lens-rotation
pool) BITE 1 of 2, the DORMANT foundation (DISCOVERY_LOOP_PLAN sec 4). This
iteration adds a deterministic scout-lens rotation POOL
(`foundry.PM_SCOUT_LENS_POOL`, 6 lenses) + a pure selector
`foundry.select_scout_lenses(iteration) -> tuple[str, str]` (sliding window over
the pool, read at CALL time) + surfaces the rotation via a read-only
`scout-plan --iteration N` mode. It is DORMANT: no orchestrator and no dispatcher
function calls the selector or the pool; the ONLY in-module caller is
`scout_plan_cli`. `scout_phase_outcome` and every live loop control path stay
byte-identical (they still read the fixed `PM_SCOUT_LENSES` pair, NOT the pool).

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-14) and the product's own OBSERVABLE behaviour only -- running the
CLI and driving/introspecting its PUBLIC runtime interface. The implementation
source (foundry.py internals / how the selector is coded), the engineer's and
reviewer's notes, and `git diff` content were NOT read to design these tests.
Every functional check drives the PUBLIC interface: the pure `select_scout_lenses`
+ `PM_SCOUT_LENS_POOL` module attributes, the CLI via `foundry.main(["scout-plan",
...])` and `foundry.scout_plan_cli(...)`, and the composition helper
`foundry.scout_phase_outcome` with its monkeypatchable module seams
(`run_stage` / `revert_repo` / `run_scout_phase` / `PM_SCOUT_LENSES`). The
dormancy / call-site proof uses only public RUNTIME introspection -- compiled
function name tables (`__code__.co_names` recursed via `_co_names_deep`) + a
`dispatcher.py` source symbol-count -- and the mechanical ASCII/leak-clean
acceptance checks use `inspect.getsource` SCOPED to the two new/changed symbols
only (the established suite convention: a mechanical byte-scan, never a read of
implementation LOGIC, never a whole-file scan, never `git diff`). Fully offline
and deterministic: NO subprocess/git/network except the fresh-import regression
probe.
"""
import contextlib
import importlib.util
import inspect
import io
import json
import os
import pathlib
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths + constants (the module is located via the BARE module
# object, never a quoted source-literal file-name -- the iter-54 meta-scanner)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

ITERATION = 107

# The exact default pool the spec fixes (Behavior 1). The mappings in Behaviors
# 3/9/10/11/13 are computed against THIS tuple.
EXPECTED_POOL = (
    "new-capability",
    "hardening/DX",
    "integration-and-adoption",
    "simplification-and-deletion",
    "performance-and-throughput",
    "narrative-and-docs",
)

# The two NEW symbols this iteration adds. Both are BRAND-NEW tokens (no partial
# pre-existence from a sibling iteration), so a `dispatcher.py` source count and a
# deep `co_names` scan are unambiguous dormancy proofs.
NEW_SELECTOR = "select_scout_lenses"
NEW_POOL = "PM_SCOUT_LENS_POOL"


def _co_names_deep(fn):
    """Every name referenced by fn's code, recursing into nested code objects.
    Pure runtime introspection -- does NOT read the module source text."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _module_functions(mod):
    """Every module-level function + every method defined on a module-level class
    that owns a __code__ object. Pure runtime introspection."""
    out = {}
    for name in dir(mod):
        obj = getattr(mod, name)
        if callable(obj) and hasattr(obj, "__code__"):
            out[name] = obj
        elif isinstance(obj, type):
            for mname, m in vars(obj).items():
                if callable(m) and hasattr(m, "__code__"):
                    out["%s.%s" % (name, mname)] = m
    return out


def _leak_guard():
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter107_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cap(fn):
    """Run a callable, capturing stdout + the returned code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    return rc, buf.getvalue()


def _cfg(dual):
    """A real ProductConfig with only the load-bearing field toggled (iter-84
    convention). The scout composition helper reads `cfg.dual_pm_scouts`."""
    return foundry.ProductConfig(
        name="p", repo="/x", allowed_push_repo="r", dual_pm_scouts=dual)


class RunStageRecorder:
    """Recording stub with run_stage's real signature
    (cfg, iteration, stage, role_file, out_name, extra="") -> (ok, out_file)."""

    def __init__(self, fail_stages=()):
        self.calls = []
        self.fail_stages = set(fail_stages)

    def __call__(self, cfg, iteration, stage, role_file, out_name, extra=""):
        self.calls.append(SimpleNamespace(
            cfg=cfg, iteration=iteration, stage=stage,
            role_file=role_file, out_name=out_name, extra=extra))
        ok = stage not in self.fail_stages
        return (ok, pathlib.Path(out_name))


class RevertRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *a, **k):
        self.calls.append((a, k))


def _install(monkeypatch, fail_stages=()):
    rec = RunStageRecorder(fail_stages=fail_stages)
    rev = RevertRecorder()
    monkeypatch.setattr(foundry, "run_stage", rec)
    monkeypatch.setattr(foundry, "revert_repo", rev)
    return rec, rev


# ==========================================================================
# Behavior 1 -- PM_SCOUT_LENS_POOL is the EXACT 6-tuple in the EXACT order
# ==========================================================================
def test_b01_pool_is_exact_6_tuple_in_order():
    pool = foundry.PM_SCOUT_LENS_POOL
    assert isinstance(pool, tuple), "PM_SCOUT_LENS_POOL must be a tuple"
    assert pool == EXPECTED_POOL, "pool contents/order != spec"
    assert len(pool) == 6
    # all entries are distinct strings (rotation guarantees depend on this)
    assert all(isinstance(x, str) for x in pool)
    assert len(set(pool)) == 6, "pool must have 6 distinct lenses"


# ==========================================================================
# Behavior 2 -- select_scout_lenses is a module-level callable; returns a
#               2-tuple whose members both belong to the pool
# ==========================================================================
def test_b02_selector_returns_pair_of_pool_members():
    assert callable(foundry.select_scout_lenses)
    for n in (-2, 0, 1, 7, 42, 107, 1000):
        res = foundry.select_scout_lenses(n)
        assert isinstance(res, tuple), "select_scout_lenses must return a tuple"
        assert len(res) == 2, "must return EXACTLY 2 lenses"
        for lens in res:
            assert lens in foundry.PM_SCOUT_LENS_POOL, (
                "lens %r not a member of the pool" % (lens,))


# ==========================================================================
# Behavior 3 -- EXACT default mapping (against the default 6-lens pool)
# ==========================================================================
def test_b03_exact_default_mapping():
    s = foundry.select_scout_lenses
    assert s(0) == ("new-capability", "hardening/DX")
    assert s(1) == ("hardening/DX", "integration-and-adoption")
    assert s(2) == ("integration-and-adoption", "simplification-and-deletion")
    assert s(3) == ("simplification-and-deletion", "performance-and-throughput")
    assert s(4) == ("performance-and-throughput", "narrative-and-docs")
    assert s(5) == ("narrative-and-docs", "new-capability")
    assert s(6) == s(0), "must cycle every len(pool)==6"
    assert s(107) == ("narrative-and-docs", "new-capability"), "107 % 6 == 5"


def test_b03_mapping_matches_the_documented_rule():
    # Independently re-derive the spec's rule and check every window matches.
    pool = EXPECTED_POOL
    for n in range(-6, 40):
        i = n % len(pool)
        expected = (pool[i], pool[(i + 1) % len(pool)])
        assert foundry.select_scout_lenses(n) == expected, (
            "n=%d: selector != documented rotation rule" % n)


# ==========================================================================
# Behavior 4 -- deterministic: same input -> same output, always
# ==========================================================================
def test_b04_deterministic():
    for n in (-10, -1, 0, 3, 6, 100, 107, 9999):
        assert foundry.select_scout_lenses(n) == foundry.select_scout_lenses(n)


# ==========================================================================
# Behavior 5 -- consecutive iterations differ, ordered AND unordered
# ==========================================================================
def test_b05_consecutive_iterations_differ():
    s = foundry.select_scout_lenses
    for n in range(-3, 31):  # inclusive of -3..30
        a, b = s(n), s(n + 1)
        assert a != b, (
            "consecutive iterations %d,%d gave the SAME ordered pair %r" % (n, n + 1, a))
        assert set(a) != set(b), (
            "consecutive iterations %d,%d gave the same UNORDERED lens set %r"
            % (n, n + 1, set(a)))


# ==========================================================================
# Behavior 6 -- reads the pool at CALL time (not import-captured / default arg)
# ==========================================================================
def test_b06_reads_pool_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "PM_SCOUT_LENS_POOL", ("x", "y"))
    assert foundry.select_scout_lenses(0) == ("x", "y")
    assert foundry.select_scout_lenses(1) == ("y", "x")
    assert foundry.select_scout_lenses(2) == ("x", "y")


def test_b06_call_time_read_restores_after_patch():
    # After monkeypatch auto-restore, the default pool mapping returns.
    assert foundry.select_scout_lenses(0) == ("new-capability", "hardening/DX")


# ==========================================================================
# Behavior 7 -- total + pure: never raises for ANY int (incl. negatives),
#               no FS/subprocess/network/clock, returns a fresh tuple each call
# ==========================================================================
def test_b07_negatives_and_total():
    assert foundry.select_scout_lenses(-1) == ("narrative-and-docs", "new-capability")
    for n in (-1000000, -7, -6, -1, 0, 1, 6, 7, 1000000, 2 ** 40):
        # must not raise for any int
        res = foundry.select_scout_lenses(n)
        assert isinstance(res, tuple) and len(res) == 2


def test_b07_fresh_tuple_each_call():
    a = foundry.select_scout_lenses(0)
    b = foundry.select_scout_lenses(0)
    assert a == b
    assert a is not b, "must build a fresh tuple each call, not return a cached object"


def test_b07_no_io(monkeypatch):
    """Sabotage every I/O primitive the selector could reach; it must still
    return, proving it touches no filesystem / subprocess / network / clock."""
    def _boom(*a, **k):
        raise AssertionError("select_scout_lenses performed I/O")

    monkeypatch.setattr("builtins.open", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    import time as _time
    monkeypatch.setattr(_time, "time", _boom)
    monkeypatch.setattr(_time, "sleep", _boom)
    assert foundry.select_scout_lenses(3) == (
        "simplification-and-deletion", "performance-and-throughput")


def test_b07_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = sorted(x.name for x in tmp_path.iterdir())
    for n in range(-3, 10):
        foundry.select_scout_lenses(n)
    after = sorted(x.name for x in tmp_path.iterdir())
    assert before == after == []


# ==========================================================================
# Behavior 8 -- DORMANT: no orchestrator + no dispatcher function references the
#               selector or the pool; the ONLY in-module caller is scout_plan_cli
# ==========================================================================
def test_b08_orchestrators_do_not_reference_new_symbols():
    new = {NEW_SELECTOR, NEW_POOL}
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan,
               foundry.scout_phase_outcome, foundry.run_scout_phase):
        refs = _co_names_deep(fn) & new
        assert refs == set(), (
            "orchestrator foundry.%s references %r" % (fn.__name__, refs))


def test_b08_only_scout_plan_cli_calls_selector():
    callers = sorted(
        name for name, fn in _module_functions(foundry).items()
        if NEW_SELECTOR in _co_names_deep(fn))
    assert callers == ["scout_plan_cli"], (
        "the ONLY in-module caller of %s must be scout_plan_cli, got %r"
        % (NEW_SELECTOR, callers))


def test_b08_scout_plan_cli_really_calls_selector():
    # non-vacuity: prove the wire is real (scout_plan_cli DOES reference it).
    assert NEW_SELECTOR in _co_names_deep(foundry.scout_plan_cli)


def test_b08_dispatcher_has_zero_references():
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    assert dtext.count(NEW_SELECTOR) == 0, "dispatcher.py references the selector"
    assert dtext.count(NEW_POOL) == 0, "dispatcher.py references the pool"
    # belt-and-suspenders: no dispatcher function/method references them at runtime
    for name, fn in _module_functions(dispatcher).items():
        refs = _co_names_deep(fn) & {NEW_SELECTOR, NEW_POOL}
        assert refs == set(), "dispatcher.%s references %r" % (name, refs)


# ==========================================================================
# Behavior 9 -- scout_phase_outcome is UNCHANGED: it still reads PM_SCOUT_LENSES
#               (NOT the new pool). Guards against accidental live-path wiring.
# ==========================================================================
def test_b09_scout_phase_outcome_uses_pm_scout_lenses_default(monkeypatch):
    rec, _rev = _install(monkeypatch)
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, "CARD.md")
    assert res is None
    assert [c.stage for c in rec.calls] == ["pm_scout_a", "pm_scout_b"]
    by_stage = {c.stage: c for c in rec.calls}
    assert "new-capability" in by_stage["pm_scout_a"].extra
    assert "hardening/DX" in by_stage["pm_scout_b"].extra


def test_b09_scout_phase_outcome_reads_lenses_knob_not_pool(monkeypatch):
    # Patch PM_SCOUT_LENSES to 3 lenses -> 3 scouts (still reads the KNOB)...
    rec, _rev = _install(monkeypatch)
    monkeypatch.setattr(foundry, "PM_SCOUT_LENSES", ("a-lens", "b-lens", "c-lens"))
    # ...AND scramble the POOL to prove scout_phase_outcome IGNORES it.
    monkeypatch.setattr(foundry, "PM_SCOUT_LENS_POOL", ("Z1", "Z2", "Z3", "Z4", "Z5", "Z6"))
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, "CARD.md")
    assert res is None
    assert [c.stage for c in rec.calls] == ["pm_scout_a", "pm_scout_b", "pm_scout_c"]
    lenses_used = [c.extra for c in rec.calls]
    assert any("a-lens" in e for e in lenses_used), "scout_phase_outcome ignored PM_SCOUT_LENSES"
    for e in lenses_used:
        for zpool in ("Z1", "Z2", "Z3"):
            assert zpool not in e, "scout_phase_outcome LEAKED the rotation pool into a live scout"


# ==========================================================================
# Behavior 10 -- scout-plan --iteration N (human render), dual + no --lens
# ==========================================================================
def test_b10_scout_plan_iteration_human():
    rc, out = _cap(lambda: foundry.main(["scout-plan", "--dual-pm-scouts", "--iteration", "2"]))
    assert rc == 1
    lines = out.splitlines()
    assert lines[0].startswith("scout-plan: dual_pm_scouts=True count=2")
    assert "pm_scout_a (lens: integration-and-adoption)" in out
    assert "pm_scout_b (lens: simplification-and-deletion)" in out
    assert lines[-1] == "verdict: DUAL"


def test_b10_cli_iteration_matches_selector():
    # the CLI's chosen lenses for --iteration N equal select_scout_lenses(N)
    _rc, out = _cap(lambda: foundry.main(["scout-plan", "--dual-pm-scouts", "--iteration", "4"]))
    a, b = foundry.select_scout_lenses(4)
    assert ("pm_scout_a (lens: %s)" % a) in out
    assert ("pm_scout_b (lens: %s)" % b) in out


# ==========================================================================
# Behavior 11 -- scout-plan --json reflects the rotation
# ==========================================================================
def test_b11_scout_plan_iteration_json():
    rc, out = _cap(lambda: foundry.main(
        ["scout-plan", "--dual-pm-scouts", "--iteration", "2", "--json"]))
    assert rc == 1
    d = json.loads(out)
    assert d["stages"] == [
        {"stage": "pm_scout_a", "lens": "integration-and-adoption"},
        {"stage": "pm_scout_b", "lens": "simplification-and-deletion"},
    ]
    assert d["count"] == 2
    assert d["verdict"] == "DUAL"


def test_b11_json_rotation_generalizes():
    for n in (0, 1, 5, 107):
        _rc, out = _cap(lambda: foundry.main(
            ["scout-plan", "--dual-pm-scouts", "--iteration", str(n), "--json"]))
        d = json.loads(out)
        a, b = foundry.select_scout_lenses(n)
        assert d["stages"] == [
            {"stage": "pm_scout_a", "lens": a},
            {"stage": "pm_scout_b", "lens": b},
        ], "json rotation wrong for n=%d" % n


# ==========================================================================
# Behavior 12 -- --lens wins over --iteration
# ==========================================================================
def test_b12_lens_wins_over_iteration_cli():
    rc, out = _cap(lambda: foundry.main(
        ["scout-plan", "--dual-pm-scouts", "--iteration", "2", "--lens", "P", "--lens", "Q"]))
    assert rc == 1
    assert "pm_scout_a (lens: P)" in out
    assert "pm_scout_b (lens: Q)" in out
    # the rotation lenses for iteration 2 must NOT appear
    assert "integration-and-adoption" not in out
    assert "simplification-and-deletion" not in out


def test_b12_lens_wins_at_function_level():
    rc, out = _cap(lambda: foundry.scout_plan_cli(True, ["P", "Q"], iteration=2))
    assert rc == 1
    assert "pm_scout_a (lens: P)" in out
    assert "pm_scout_b (lens: Q)" in out


# ==========================================================================
# Behavior 13 -- byte-identical default path + disabled-ignores-iteration
# ==========================================================================
def test_b13_default_path_byte_identical_to_no_iteration():
    # No --iteration, no --lens: identical output to the direct no-override call
    # (which reads PM_SCOUT_LENSES), i.e. unchanged from before this bite.
    rc_cli, out_cli = _cap(lambda: foundry.main(["scout-plan", "--dual-pm-scouts"]))
    rc_fn, out_fn = _cap(lambda: foundry.scout_plan_cli(True, None))
    assert (rc_cli, out_cli) == (rc_fn, out_fn)
    assert rc_cli == 1
    assert "pm_scout_a (lens: new-capability)" in out_cli
    assert "pm_scout_b (lens: hardening/DX)" in out_cli
    assert out_cli.splitlines()[-1] == "verdict: DUAL"


def test_b13_default_iteration_none_equals_no_kwarg():
    # scout_plan_cli(..., iteration=None) must be byte-identical to the pre-bite
    # 3-arg call (trailing optional kwarg is transparent to direct callers).
    rc_a, out_a = _cap(lambda: foundry.scout_plan_cli(True, None))
    rc_b, out_b = _cap(lambda: foundry.scout_plan_cli(True, None, iteration=None))
    assert (rc_a, out_a) == (rc_b, out_b)


def test_b13_disabled_ignores_iteration():
    for extra in (["--iteration", "2"], ["--iteration", "5"], []):
        rc, out = _cap(lambda: foundry.main(["scout-plan"] + extra))
        assert rc == 0, "disabled plan must exit 0 regardless of --iteration"
        assert "count=0" in out
        assert out.splitlines()[-1] == "verdict: SINGLE"


# ==========================================================================
# Behavior 14 -- import cleanliness + ASCII (this file + new symbols)
# ==========================================================================
def test_b14_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_b14_this_test_file_ascii():
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


def test_b14_new_symbols_ascii():
    """The new/changed code is pure ASCII. Scoped to the new symbols via
    inspect.getsource -- a MECHANICAL byte-scan, NOT a read of logic, and NOT a
    whole-file scan (foundry.py carries pre-existing non-ASCII elsewhere -- the
    iter-67 divider em-dash trap). Established suite convention."""
    srcs = [
        inspect.getsource(foundry.select_scout_lenses),
        inspect.getsource(foundry.scout_plan_cli),
    ]
    for src in srcs:
        offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert offenders == [], offenders[:5]


# ==========================================================================
# Acceptance-criteria / non-regression block (offline)
# ==========================================================================
def test_ac_public_surface_intact():
    assert callable(foundry.select_scout_lenses)
    assert isinstance(foundry.PM_SCOUT_LENS_POOL, tuple)
    assert callable(foundry.scout_plan_cli)
    assert callable(foundry.scout_phase_outcome)
    assert foundry.PM_SCOUT_LENSES == ("new-capability", "hardening/DX")
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage",
               "run_execution_plan", "run_scout_phase"):
        assert callable(getattr(foundry, fn)), "foundry.%s missing (regression)" % fn
    assert dispatcher is not None


def test_ac_scout_plan_signature_trailing_iteration_kwarg():
    sig = inspect.signature(foundry.scout_plan_cli)
    params = list(sig.parameters)
    assert "iteration" in sig.parameters, "scout_plan_cli must gain an iteration kwarg"
    assert sig.parameters["iteration"].default is None
    assert params[-1] == "iteration", "iteration must be the TRAILING parameter"


def test_ac_scout_plan_subparser_help_has_iteration(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["scout-plan", "--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "--iteration" in out, "--iteration absent from scout-plan subparser help"
    assert "--dual-pm-scouts" in out
    assert "--lens" in out


def test_ac_this_test_file_leak_clean():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "this test file leaks a denylisted token"
    # matcher is ARMED (not inert): a runtime-built home-path needle IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"


def test_ac_new_symbols_leak_clean():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    for src in (inspect.getsource(foundry.select_scout_lenses),
                inspect.getsource(foundry.scout_plan_cli)):
        assert mod.scan_text(src, denylist) == (), "new source leaks a denylisted token"
