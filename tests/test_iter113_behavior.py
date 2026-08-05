"""Black-box behaviour tests for iter 113 -- discovery bite 2 LIVE WIRING
(DISCOVERY_LOOP_PLAN sec 4). The prior bite (iter 107) shipped a DORMANT
deterministic scout-lens rotation (`select_scout_lenses` + `PM_SCOUT_LENS_POOL`);
this iteration WIRES it into the live scout pre-phase by giving
`scout_phase_outcome` an ADDITIVE optional trailing `lenses=None` parameter and
passing `list(select_scout_lenses(iteration))` at the single `run_iteration`
call site. The `lenses=None` (default / no-arg) path stays byte-identical to
today: it reads the fixed module-level `PM_SCOUT_LENSES` pair at CALL time.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-9) and the product's own OBSERVABLE behaviour only -- driving the
PUBLIC composition helper `foundry.scout_phase_outcome` and the orchestrator
`foundry.run_iteration` through their monkeypatchable module-level seams
(`run_stage` / `revert_repo` / `run_scout_phase` / `scout_phase_outcome` /
`head_of_branch` / `power_state` / `log` / `PM_SCOUT_LENSES` /
`PM_SCOUT_LENS_POOL`), plus pure runtime introspection (compiled
`__code__.co_names` recursed via `_co_names_deep`) for the wiring proof. The
implementation LOGIC in foundry.py, the engineer's and reviewer's notes, and
`git diff` content were NOT read to design these tests. The mechanical
ASCII/leak checks use `inspect.getsource` SCOPED to the one changed symbol
(`scout_phase_outcome`) -- a byte-scan, never a read of logic, never a
whole-file scan, never `git diff` (established suite convention). Fully offline
and deterministic: NO real subprocess/git/network except the fresh-import
regression probe.
"""
import importlib.util
import inspect
import pathlib
import subprocess
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths + constants (located via the BARE module object, never a
# quoted source-literal file-name -- the iter-54 meta-scanner convention)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
THIS_TEST = pathlib.Path(__file__).resolve()

ITERATION = 113
ROLE = "CARD.md"

# run_iteration's PM-stage infra-fail dict has EXACTLY these keys (iter-84).
FAILURE_KEYS = {"status", "stage", "iteration"}

# The default fixed pair the no-lenses path must read (unchanged by this bite).
DEFAULT_LENSES = ("new-capability", "hardening/DX")


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


def _leak_guard():
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter113_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cfg(dual):
    """A real ProductConfig with only the load-bearing field toggled (iter-84
    convention). scout_phase_outcome reads `cfg.dual_pm_scouts`."""
    return foundry.ProductConfig(
        name="p", repo="/x", allowed_push_repo="r", dual_pm_scouts=dual)


class RunStageRecorder:
    """Recording stub with run_stage's real signature
    (cfg, iteration, stage, role_file, out_name, extra="") -> (ok, out_file).
    Returns (False, ...) for any stage in fail_stages, (True, ...) otherwise.
    Performs no I/O of its own."""

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
# Behavior 1 -- explicit non-None lenses of K strings runs exactly K scouts in
#               input order, named by position pm_scout_a, pm_scout_b, ... , the
#               i-th paired with lenses[i] (lens in extra); None on all-succeed.
# ==========================================================================
def test_b01_three_lenses_run_three_scouts_in_order(monkeypatch):
    rec, _rev = _install(monkeypatch)
    lenses = ["L0", "L1", "L2"]
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE, lenses)
    assert res is None, "all-succeed must return None"
    assert [c.stage for c in rec.calls] == ["pm_scout_a", "pm_scout_b", "pm_scout_c"]
    for i, c in enumerate(rec.calls):
        assert lenses[i] in c.extra, "scout i must carry lenses[i] in extra"
        assert c.out_name == c.stage + ".md"


def test_b01_five_lenses_name_positions_a_through_e(monkeypatch):
    rec, _rev = _install(monkeypatch)
    lenses = ["m0", "m1", "m2", "m3", "m4"]
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE, lenses)
    assert res is None
    assert [c.stage for c in rec.calls] == [
        "pm_scout_a", "pm_scout_b", "pm_scout_c", "pm_scout_d", "pm_scout_e"]
    for i, c in enumerate(rec.calls):
        assert lenses[i] in c.extra


def test_b01_single_lens_runs_one_scout(monkeypatch):
    rec, _rev = _install(monkeypatch)
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE, ["solo-lens"])
    assert res is None
    assert [c.stage for c in rec.calls] == ["pm_scout_a"]
    assert "solo-lens" in rec.calls[0].extra


def test_b01_accepts_any_iterable_not_just_list(monkeypatch):
    rec, _rev = _install(monkeypatch)
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE, ("tup-a", "tup-b"))
    assert res is None
    assert [c.stage for c in rec.calls] == ["pm_scout_a", "pm_scout_b"]
    assert "tup-a" in rec.calls[0].extra
    assert "tup-b" in rec.calls[1].extra


def test_b01_role_file_threads_through_every_scout(monkeypatch):
    rec, _rev = _install(monkeypatch)
    foundry.scout_phase_outcome(_cfg(True), ITERATION, "OTHER_CARD.md", ["a", "b", "c"])
    assert all(c.role_file == "OTHER_CARD.md" for c in rec.calls)
    assert len(rec.calls) == 3


# ==========================================================================
# Behavior 2 -- NO lenses arg (equivalently lenses=None) is BYTE-IDENTICAL to
#               today: it reads module-level PM_SCOUT_LENSES at CALL time and
#               IGNORES PM_SCOUT_LENS_POOL entirely.
# ==========================================================================
def test_b02_no_lenses_arg_reads_default_pm_scout_lenses(monkeypatch):
    rec, _rev = _install(monkeypatch)
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)  # no lenses arg
    assert res is None
    assert [c.stage for c in rec.calls] == ["pm_scout_a", "pm_scout_b"]
    by_stage = {c.stage: c for c in rec.calls}
    assert DEFAULT_LENSES[0] in by_stage["pm_scout_a"].extra
    assert DEFAULT_LENSES[1] in by_stage["pm_scout_b"].extra


def test_b02_explicit_none_equals_no_arg(monkeypatch):
    rec_none, _r1 = _install(monkeypatch)
    foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE, None)
    a = [(c.stage, c.extra) for c in rec_none.calls]
    rec_noarg, _r2 = _install(monkeypatch)
    foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)
    b = [(c.stage, c.extra) for c in rec_noarg.calls]
    assert a == b, "lenses=None must be byte-identical to omitting the arg"


def test_b02_no_lenses_reads_knob_at_call_time_and_ignores_pool(monkeypatch):
    rec, _rev = _install(monkeypatch)
    # Patch the KNOB to 3 lenses -> 3 scouts (proves call-time read of the knob)...
    monkeypatch.setattr(foundry, "PM_SCOUT_LENSES", ("a-lens", "b-lens", "c-lens"))
    # ...AND scramble the POOL to prove the no-lenses path IGNORES the pool.
    monkeypatch.setattr(
        foundry, "PM_SCOUT_LENS_POOL", ("Z1", "Z2", "Z3", "Z4", "Z5", "Z6"))
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)  # no lenses
    assert res is None
    assert [c.stage for c in rec.calls] == ["pm_scout_a", "pm_scout_b", "pm_scout_c"]
    used = [c.extra for c in rec.calls]
    assert any("a-lens" in e for e in used), "no-lenses path ignored PM_SCOUT_LENSES"
    for e in used:
        for z in ("Z1", "Z2", "Z3"):
            assert z not in e, "no-lenses path LEAKED the rotation pool"


# ==========================================================================
# Behavior 3 -- an explicit lenses override wins over PM_SCOUT_LENSES for that
#               call only, and mutates NEITHER PM_SCOUT_LENSES nor the pool.
# ==========================================================================
def test_b03_explicit_lenses_win_over_knob(monkeypatch):
    rec, _rev = _install(monkeypatch)
    monkeypatch.setattr(foundry, "PM_SCOUT_LENSES", ("knob-x", "knob-y"))
    foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE, ["ov-a", "ov-b"])
    used = " ".join(c.extra for c in rec.calls)
    assert "ov-a" in used and "ov-b" in used, "explicit lenses must be used"
    assert "knob-x" not in used and "knob-y" not in used, "knob must be overridden"


def test_b03_override_does_not_mutate_module_globals(monkeypatch):
    rec, _rev = _install(monkeypatch)
    before_knob = foundry.PM_SCOUT_LENSES
    before_pool = foundry.PM_SCOUT_LENS_POOL
    foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE, ["x1", "x2", "x3"])
    assert foundry.PM_SCOUT_LENSES == before_knob, "override must not mutate PM_SCOUT_LENSES"
    assert foundry.PM_SCOUT_LENS_POOL == before_pool, "override must not mutate the pool"


# ==========================================================================
# Behavior 4 -- dual_pm_scouts falsy -> None, ZERO scout stages, regardless of
#               whether a lenses argument is passed (disabled is byte-identical).
# ==========================================================================
def test_b04_disabled_zero_scouts_no_lenses(monkeypatch):
    rec, rev = _install(monkeypatch)
    assert foundry.scout_phase_outcome(_cfg(False), ITERATION, ROLE) is None
    assert rec.calls == [], "disabled must run zero scouts"
    assert rev.calls == []


def test_b04_disabled_ignores_explicit_lenses(monkeypatch):
    rec, rev = _install(monkeypatch)
    assert foundry.scout_phase_outcome(
        _cfg(False), ITERATION, ROLE, ["a", "b", "c"]) is None
    assert rec.calls == [], "disabled path must ignore lenses and run zero scouts"
    assert rev.calls == []


# ==========================================================================
# Behavior 5 -- return/side-effect contract on every path: None on disabled OR
#               all-succeed; the 3-key infra-fail dict on a scout failure,
#               stopping before later scouts; NEVER reverts on any path.
# ==========================================================================
def test_b05_first_scout_fail_stops_and_reports(monkeypatch):
    rec, rev = _install(monkeypatch, fail_stages=("pm_scout_a",))
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE, ["a", "b", "c"])
    assert res == {"status": "infra-fail", "stage": "pm_scout_a",
                   "iteration": ITERATION}
    assert len(rec.calls) == 1, "must stop before later scouts on first failure"
    assert rev.calls == []


def test_b05_middle_scout_fail_stops_and_reports(monkeypatch):
    rec, rev = _install(monkeypatch, fail_stages=("pm_scout_b",))
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE, ["a", "b", "c"])
    assert res == {"status": "infra-fail", "stage": "pm_scout_b",
                   "iteration": ITERATION}
    assert [c.stage for c in rec.calls] == ["pm_scout_a", "pm_scout_b"], \
        "pm_scout_c must NOT run after pm_scout_b fails"
    assert rev.calls == []


def test_b05_failure_dict_has_exactly_three_keys_and_threads_iteration(monkeypatch):
    rec, rev = _install(monkeypatch, fail_stages=("pm_scout_a",))
    it = 4242
    res = foundry.scout_phase_outcome(_cfg(True), it, ROLE, ["a", "b"])
    assert set(res.keys()) == FAILURE_KEYS, "exactly {status, stage, iteration}"
    assert res["status"] == "infra-fail"
    assert res["iteration"] == it
    assert rev.calls == []


def test_b05_revert_never_called_on_any_path(monkeypatch):
    # disabled
    rec, rev = _install(monkeypatch)
    foundry.scout_phase_outcome(_cfg(False), ITERATION, ROLE, ["a", "b"])
    assert rev.calls == []
    # all-succeed
    rec, rev = _install(monkeypatch)
    foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE, ["a", "b"])
    assert rev.calls == []
    # first-scout-fail
    rec, rev = _install(monkeypatch, fail_stages=("pm_scout_a",))
    foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE, ["a", "b"])
    assert rev.calls == []
    # later-scout-fail
    rec, rev = _install(monkeypatch, fail_stages=("pm_scout_b",))
    foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE, ["a", "b"])
    assert rev.calls == []


# ==========================================================================
# Behavior 6 -- NO direct FS/subprocess/network I/O of its own; all external
#               effects flow through run_scout_phase / run_stage seams invoked
#               by BARE module name (so monkeypatch.setattr takes effect).
# ==========================================================================
def test_b06_run_scout_phase_seam_bites(monkeypatch):
    monkeypatch.setattr(foundry, "run_stage", RunStageRecorder())
    monkeypatch.setattr(foundry, "revert_repo", RevertRecorder())
    monkeypatch.setattr(
        foundry, "run_scout_phase",
        lambda cfg, it, plan, rf: foundry.ScoutPhaseResult(
            ok=False, outputs=(), failed_stage="SEAM_STAGE"))
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE, ["a", "b"])
    assert res == {"status": "infra-fail", "stage": "SEAM_STAGE",
                   "iteration": ITERATION}


def test_b06_run_stage_seam_bites_with_explicit_lenses(monkeypatch):
    rec, _rev = _install(monkeypatch)
    foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE, ["a", "b", "c"])
    assert len(rec.calls) == 3, "each scout must flow through the run_stage seam"


def test_b06_no_direct_filesystem_writes(monkeypatch, tmp_path):
    monkeypatch.setattr(foundry, "run_stage", RunStageRecorder())
    monkeypatch.setattr(foundry, "revert_repo", RevertRecorder())
    monkeypatch.chdir(tmp_path)
    before = sorted(x.name for x in tmp_path.iterdir())
    foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE, ["a", "b"])
    foundry.scout_phase_outcome(_cfg(False), ITERATION, ROLE, ["a", "b"])
    after = sorted(x.name for x in tmp_path.iterdir())
    assert before == after == [], "scout_phase_outcome wrote to cwd"


def test_b06_performs_no_open_of_its_own(monkeypatch):
    monkeypatch.setattr(foundry, "run_stage", RunStageRecorder())
    monkeypatch.setattr(foundry, "revert_repo", RevertRecorder())

    def _boom(*a, **k):
        raise AssertionError("scout_phase_outcome performed its own open()")

    monkeypatch.setattr("builtins.open", _boom)
    assert foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE, ["a", "b"]) is None


# ==========================================================================
# Behavior 7 -- WIRING PROOF: run_iteration now references select_scout_lenses,
#               and still references scout_phase_outcome (bite-1 wiring intact).
# ==========================================================================
def test_b07_run_iteration_references_selector_and_helper():
    names = _co_names_deep(foundry.run_iteration)
    assert "select_scout_lenses" in names, \
        "run_iteration must reference select_scout_lenses (bite-2 wiring)"
    assert "scout_phase_outcome" in names, \
        "run_iteration must still reference scout_phase_outcome (bite-1 intact)"


# ==========================================================================
# Behavior 8 -- LIVE ROTATION MATCHES THE SELECTOR.
# ==========================================================================
def test_b08_scout_phase_outcome_honors_selector_pair(monkeypatch):
    for n in (0, 1, 5, 6, 113):
        rec, _rev = _install(monkeypatch)
        pair = foundry.select_scout_lenses(n)
        res = foundry.scout_phase_outcome(_cfg(True), n, ROLE, list(pair))
        assert res is None
        assert [c.stage for c in rec.calls] == ["pm_scout_a", "pm_scout_b"]
        assert pair[0] in rec.calls[0].extra, "n=%d scout_a lens" % n
        assert pair[1] in rec.calls[1].extra, "n=%d scout_b lens" % n


def test_b08_selector_consecutive_differ_and_wrap_at_pool_len():
    length = len(foundry.PM_SCOUT_LENS_POOL)
    for n in range(0, 2 * length + 3):
        assert foundry.select_scout_lenses(n) != foundry.select_scout_lenses(n + 1), \
            "consecutive iterations %d,%d must differ" % (n, n + 1)
        assert foundry.select_scout_lenses(n) == foundry.select_scout_lenses(n + length), \
            "iterations %d and %d must match (period=pool len)" % (n, n + length)


def test_b08_run_iteration_passes_selector_output_live(monkeypatch):
    """Strongest live-wiring proof: drive run_iteration itself (all real seams
    patched, fully offline), capture the lenses it forwards to
    scout_phase_outcome, and assert it equals list(select_scout_lenses(N))."""
    captured = {}

    def rec_spo(cfg, iteration, role_file, lenses=None):
        captured["lenses"] = lenses
        return {"status": "infra-fail", "stage": "pm_scout_a", "iteration": iteration}

    # scout_phase_outcome is called by bare name (bite-1), so patching bites and
    # the returned infra-fail dict short-circuits run_iteration before any build.
    monkeypatch.setattr(foundry, "scout_phase_outcome", rec_spo)
    # Neutralise the pre-scout logging/git/power probes so the driven path is
    # fully offline (no real subprocess/git).
    monkeypatch.setattr(foundry, "head_of_branch", lambda *a, **k: "deadbeef")
    monkeypatch.setattr(foundry, "power_state", lambda *a, **k: "AC")
    monkeypatch.setattr(foundry, "log", lambda *a, **k: None)

    def _boom(*a, **k):
        raise AssertionError("run_iteration hit real subprocess before scout short-circuit")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    cfg = _cfg(True)
    for n in (0, 1, 5, 6, 113):
        res = foundry.run_iteration(cfg, n)
        assert res == {"status": "infra-fail", "stage": "pm_scout_a", "iteration": n}
        assert captured["lenses"] == list(foundry.select_scout_lenses(n)), (
            "run_iteration passed %r, expected %r"
            % (captured["lenses"], list(foundry.select_scout_lenses(n))))


# ==========================================================================
# Behavior 9 -- import safety: import foundry AND dispatcher in a fresh process.
# ==========================================================================
def test_b09_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


# ==========================================================================
# Acceptance-criteria / non-regression block (offline)
# ==========================================================================
def test_ac_lenses_is_trailing_optional_kwarg_default_none():
    sig = inspect.signature(foundry.scout_phase_outcome)
    params = list(sig.parameters)
    assert "lenses" in sig.parameters, "scout_phase_outcome must gain a lenses param"
    assert sig.parameters["lenses"].default is None, "lenses default must be None"
    assert params[-1] == "lenses", "lenses must be the TRAILING parameter (additive)"


def test_ac_public_surface_intact():
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage",
               "run_execution_plan", "run_scout_phase", "scout_phase_outcome",
               "decide_scout_phase", "select_scout_lenses"):
        assert callable(getattr(foundry, fn)), "foundry.%s missing (regression)" % fn
    assert isinstance(foundry.PM_SCOUT_LENS_POOL, tuple)
    assert foundry.PM_SCOUT_LENSES == DEFAULT_LENSES
    assert dispatcher is not None


def test_ac_this_test_file_ascii():
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


def test_ac_changed_symbol_source_ascii():
    """The changed source is pure ASCII. Scoped to scout_phase_outcome via
    inspect.getsource -- a MECHANICAL byte-scan, NOT a read of logic, NOT a
    whole-file scan (foundry.py carries pre-existing non-ASCII elsewhere)."""
    src = inspect.getsource(foundry.scout_phase_outcome)
    offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
    assert offenders == [], offenders[:5]


def test_ac_this_test_file_leak_clean():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "this test file leaks a denylisted token"
    # matcher is ARMED (not inert): a runtime-built home-path needle IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"


def test_ac_changed_symbol_source_leak_clean():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(
        inspect.getsource(foundry.scout_phase_outcome), denylist) == (), \
        "changed source leaks a denylisted token"
