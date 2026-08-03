"""Black-box behaviour tests for iter 84 -- dual-PM-scout feature (bite 3b-ii-prep
of ~4): the DORMANT config-gated scout-phase COMPOSITION helper
`scout_phase_outcome(cfg, iteration, role_file) -> dict | None`. It reads
`cfg.dual_pm_scouts` (return None when falsy), builds the plan via
`decide_scout_phase(cfg.dual_pm_scouts)`, runs the iter-83 executor
`run_scout_phase(cfg, iteration, plan, role_file)`, and maps a scout failure to
`run_iteration`'s PM-stage infra-fail dict `{"status": "infra-fail", "stage":
<failed scout>, "iteration": iteration}` -- else returns None (disabled OR all
scouts succeeded = proceed to the PM lead). ZERO call site: no orchestrator calls
it, no CLI, no config field, no new module constant. The `role_file` is a
PARAMETER, so the literal card name never enters foundry.py and iters 81/82/83's
role-file count-0 dormancy tests stay green.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-16) and the product's own OBSERVABLE behaviour only (running it and
introspecting its PUBLIC interface). The implementation source (the module
internals / how the helper is coded), the engineer's and reviewer's notes, and
`git diff` content were NOT read to design these behaviour tests. Every functional
check drives the PUBLIC interface: the helper `foundry.scout_phase_outcome`, a real
`foundry.ProductConfig` (only its `dual_pm_scouts` field is set), and the
monkeypatchable module-level seams `foundry.run_stage` / `foundry.revert_repo` /
`foundry.run_scout_phase` / `foundry.PM_SCOUT_LENSES` (installed as recording
stubs / patched values). The dormancy / off-control-path checks use only public
RUNTIME introspection -- compiled function name tables (`__code__.co_names` recursed
via `_co_names_deep`) and a git `--quiet` exit-code probe (exit status only, never
diff content) -- plus, for the mechanical ASCII / leak-clean / `pm_scout.md`-count-0
acceptance criteria, `inspect.getsource` scoped to the NEW symbol and a mechanical
byte-count of the main module text located via the bare module object (never reading
implementation LOGIC, never a quoted main-module file-name literal). Fully offline
and deterministic: NO subprocess/git/network/agent-run except the fresh-import
regression probe and the control-path byte-unchanged git `--quiet` probe.
`scout_phase_outcome` is a BRAND-NEW token this bite (no partial pre-existence from a
sibling iteration), so the deep `co_names` scan of the five orchestrators +
dispatcher.py source count is the authoritative dormancy proof.
"""
import importlib.util
import inspect
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
# runtime-built paths + constants (the main module is located via the bare
# module object, never a quoted file-name token -- the iter-54 meta-scanner)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
_MAIN_MODULE = pathlib.Path(foundry.__file__).resolve()
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

ITERATION = 84
ROLE = "CARD.md"

# The symbol this iteration ADDS. It is a BRAND-NEW token (unlike the iter-80/81
# command-string trap); it must be dormant -- no orchestrator and dispatcher.py
# reference it by name.
NEW_SYMBOL = "scout_phase_outcome"

# run_iteration's PM-stage infra-fail dict has exactly these keys.
FAILURE_KEYS = {"status", "stage", "iteration"}

_GIT_OK = subprocess.run(
    ["git", "rev-parse", "--is-inside-work-tree"],
    cwd=str(_ROOT), capture_output=True, text=True,
).returncode == 0


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
    """Dynamically import the committed leak-guard, registering the module in
    sys.modules BEFORE exec so its own import machinery works."""
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter84_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cfg(dual):
    """A real ProductConfig with only the load-bearing field toggled. The helper
    reads `cfg.dual_pm_scouts` and threads cfg opaquely to run_stage (stubbed)."""
    return foundry.ProductConfig(
        name="p", repo="/x", allowed_push_repo="r", dual_pm_scouts=dual)


class RunStageRecorder:
    """A recording stub with run_stage's real signature
    (cfg, iteration, stage, role_file, out_name, extra="") -> (ok, out_file).
    Records every call; returns (False, ...) for any stage listed in fail_stages,
    (True, ...) otherwise. Performs no I/O of its own."""

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
    """Records every invocation so a test can assert revert was NEVER called."""

    def __init__(self):
        self.calls = []

    def __call__(self, *a, **k):
        self.calls.append((a, k))


def _install(monkeypatch, fail_stages=()):
    """Install recording run_stage + revert_repo seams; return (rec, rev)."""
    rec = RunStageRecorder(fail_stages=fail_stages)
    rev = RevertRecorder()
    monkeypatch.setattr(foundry, "run_stage", rec)
    monkeypatch.setattr(foundry, "revert_repo", rev)
    return rec, rev


# ==========================================================================
# Behavior 1 -- DISABLED: falsy dual_pm_scouts -> None, ZERO run_stage calls
# ==========================================================================
def test_b01_disabled_returns_none_zero_calls(monkeypatch):
    rec, rev = _install(monkeypatch)
    res = foundry.scout_phase_outcome(_cfg(False), ITERATION, ROLE)
    assert res is None, "disabled must signal proceed-to-PM-lead via None"
    assert rec.calls == [], "no scout machinery may run when disabled"
    assert rev.calls == []


# ==========================================================================
# Behavior 2 -- ENABLED + ALL SUCCEED (default 2 lenses) -> None, 2 calls in order
# ==========================================================================
def test_b02_enabled_all_succeed_returns_none_two_calls_in_order(monkeypatch):
    rec, _rev = _install(monkeypatch)
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)
    assert res is None, "all-succeed must signal proceed-to-PM-lead via None"
    assert [c.stage for c in rec.calls] == ["pm_scout_a", "pm_scout_b"]


# ==========================================================================
# Behavior 3 -- ROLE_FILE passed through verbatim to EVERY run_stage call
# ==========================================================================
def test_b03_role_file_passed_through_verbatim(monkeypatch):
    rec, _rev = _install(monkeypatch)
    foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)
    assert len(rec.calls) == 2
    for c in rec.calls:
        assert c.role_file == ROLE, "role_file must thread through unchanged"


def test_b03_a_different_role_file_sentinel_is_also_passed_through(monkeypatch):
    rec, _rev = _install(monkeypatch)
    foundry.scout_phase_outcome(_cfg(True), ITERATION, "OTHER_CARD.md")
    assert len(rec.calls) == 2
    assert all(c.role_file == "OTHER_CARD.md" for c in rec.calls)


# ==========================================================================
# Behavior 4 -- out_name == stage + ".md" and each scout's LENS is in `extra`
# ==========================================================================
def test_b04_out_name_and_lens_in_extra(monkeypatch):
    rec, _rev = _install(monkeypatch)
    foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)
    assert [c.out_name for c in rec.calls] == ["pm_scout_a.md", "pm_scout_b.md"]
    for c in rec.calls:
        assert c.out_name == c.stage + ".md"
    by_stage = {c.stage: c for c in rec.calls}
    assert "new-capability" in by_stage["pm_scout_a"].extra
    assert "hardening/DX" in by_stage["pm_scout_b"].extra


# ==========================================================================
# Behavior 5 -- FIRST scout fails -> infra-fail dict, 1 call, no revert
# ==========================================================================
def test_b05_first_scout_fails(monkeypatch):
    rec, rev = _install(monkeypatch, fail_stages=("pm_scout_a",))
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)
    assert res == {"status": "infra-fail", "stage": "pm_scout_a",
                   "iteration": ITERATION}
    assert len(rec.calls) == 1, "the second scout must NOT run after the first fails"
    assert rev.calls == [], "revert_repo must never be called (scouts run pre-build)"


# ==========================================================================
# Behavior 6 -- SECOND scout fails -> infra-fail dict, 2 calls, no revert
# ==========================================================================
def test_b06_second_scout_fails(monkeypatch):
    rec, rev = _install(monkeypatch, fail_stages=("pm_scout_b",))
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)
    assert res == {"status": "infra-fail", "stage": "pm_scout_b",
                   "iteration": ITERATION}
    assert len(rec.calls) == 2
    assert rev.calls == []


# ==========================================================================
# Behavior 7 -- FAILURE-DICT SHAPE: exact keys, status, iteration threaded
# ==========================================================================
def test_b07_failure_dict_shape(monkeypatch):
    it = 4242  # a distinctive iteration value proves it is threaded, not hardcoded
    rec, _rev = _install(monkeypatch, fail_stages=("pm_scout_a",))
    res = foundry.scout_phase_outcome(_cfg(True), it, ROLE)
    assert isinstance(res, dict)
    assert set(res.keys()) == FAILURE_KEYS, "exactly {status, stage, iteration}"
    assert res["status"] == "infra-fail"
    assert res["iteration"] == it
    assert res["stage"] == "pm_scout_a"


# ==========================================================================
# Behavior 8 -- NEVER REVERTS on any path (disabled/success/first-fail/later-fail)
# ==========================================================================
def test_b08_never_reverts_any_path(monkeypatch):
    # disabled
    _rec, rev = _install(monkeypatch)
    foundry.scout_phase_outcome(_cfg(False), ITERATION, ROLE)
    assert rev.calls == []
    # full success
    _rec, rev = _install(monkeypatch)
    foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)
    assert rev.calls == []
    # first-scout fail
    _rec, rev = _install(monkeypatch, fail_stages=("pm_scout_a",))
    foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)
    assert rev.calls == []
    # later-scout fail
    _rec, rev = _install(monkeypatch, fail_stages=("pm_scout_b",))
    foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)
    assert rev.calls == []


# ==========================================================================
# Behavior 9 -- RETURN CONTRACT: None in exactly two cases, distinguished by count
# ==========================================================================
def test_b09_return_contract_none_two_cases(monkeypatch):
    # disabled -> None with ZERO run_stage calls
    rec, _rev = _install(monkeypatch)
    assert foundry.scout_phase_outcome(_cfg(False), ITERATION, ROLE) is None
    assert len(rec.calls) == 0
    # full success -> None with >= 1 run_stage call
    rec, _rev = _install(monkeypatch)
    assert foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE) is None
    assert len(rec.calls) >= 1
    # a scout failure -> a status dict, never None
    rec, _rev = _install(monkeypatch, fail_stages=("pm_scout_a",))
    assert isinstance(foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE), dict)


# ==========================================================================
# Behavior 10 -- ITER-80 KNOB read at CALL time via config->plan->execute path
# ==========================================================================
def test_b10_knob_three_lenses(monkeypatch):
    rec, _rev = _install(monkeypatch)
    monkeypatch.setattr(foundry, "PM_SCOUT_LENSES", ("a-lens", "b-lens", "c-lens"))
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)
    assert res is None
    assert [c.stage for c in rec.calls] == ["pm_scout_a", "pm_scout_b", "pm_scout_c"]


def test_b10_knob_one_lens(monkeypatch):
    rec, _rev = _install(monkeypatch)
    monkeypatch.setattr(foundry, "PM_SCOUT_LENSES", ("only",))
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)
    assert res is None
    assert [c.stage for c in rec.calls] == ["pm_scout_a"]


def test_b10_knob_restores_to_default_two(monkeypatch):
    # after monkeypatch auto-restore, the default 2-lens count returns.
    rec, _rev = _install(monkeypatch)
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)
    assert res is None
    assert len(rec.calls) == 2, "default PM_SCOUT_LENSES yields exactly 2 scouts"


# ==========================================================================
# Behavior 11 -- BARE-NAME SEAMS: patching run_scout_phase / run_stage bites
# ==========================================================================
def test_b11_run_scout_phase_seam_bites(monkeypatch):
    """scout_phase_outcome invokes run_scout_phase by BARE module name, so a
    patched stub is read at call time. A stub returning a not-ok result must be
    mapped to the infra-fail dict carrying that stub's failed_stage."""
    monkeypatch.setattr(foundry, "run_stage", RunStageRecorder())
    monkeypatch.setattr(foundry, "revert_repo", RevertRecorder())
    monkeypatch.setattr(
        foundry, "run_scout_phase",
        lambda cfg, it, plan, rf: foundry.ScoutPhaseResult(
            ok=False, outputs=(), failed_stage="STUB_STAGE"))
    res = foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)
    assert res == {"status": "infra-fail", "stage": "STUB_STAGE",
                   "iteration": ITERATION}


def test_b11_run_stage_seam_bites(monkeypatch):
    """scout_phase_outcome -> run_scout_phase -> run_stage, all by bare name, so a
    recording run_stage stub receives the scout calls."""
    rec, _rev = _install(monkeypatch)
    foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)
    assert len(rec.calls) == 2


# ==========================================================================
# Behavior 12 -- NO DIRECT I/O of its own (run_stage stubbed)
# ==========================================================================
def test_b12_no_direct_io(monkeypatch, tmp_path):
    rec = RunStageRecorder()
    monkeypatch.setattr(foundry, "run_stage", rec)
    monkeypatch.setattr(foundry, "revert_repo", RevertRecorder())
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    prev = os.getcwd()
    os.chdir(cwd)
    try:
        before = sorted(x.name for x in cwd.iterdir())
        foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE)
        foundry.scout_phase_outcome(_cfg(False), ITERATION, ROLE)
        after = sorted(x.name for x in cwd.iterdir())
    finally:
        os.chdir(prev)
    assert before == after == [], f"scout_phase_outcome wrote to cwd: {before} -> {after}"


def test_b12_opens_no_file(monkeypatch):
    """Sabotage builtins.open; scout_phase_outcome must still return on the
    enabled path (all I/O is delegated to the run_stage seam)."""
    monkeypatch.setattr(foundry, "run_stage", RunStageRecorder())
    monkeypatch.setattr(foundry, "revert_repo", RevertRecorder())

    def _boom(*a, **k):
        raise AssertionError("scout_phase_outcome performed filesystem I/O of its own")

    monkeypatch.setattr("builtins.open", _boom)
    assert foundry.scout_phase_outcome(_cfg(True), ITERATION, ROLE) is None


# ==========================================================================
# Behavior 13 -- DORMANT / ZERO CALL SITE
# ==========================================================================
def test_b13_dormant_zero_call_site():
    orchestrators = (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
                     foundry.run_continuous, foundry.run_execution_plan)
    for fn in orchestrators:
        assert NEW_SYMBOL not in _co_names_deep(fn), \
            f"foundry.{fn.__name__} references dormant symbol {NEW_SYMBOL!r}"
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    assert dtext.count(NEW_SYMBOL) == 0, \
        f"dispatcher.py references dormant symbol {NEW_SYMBOL!r}"


# ==========================================================================
# Behavior 14 -- ROLE-FILE DORMANCY PRESERVED (pm_scout.md count 0 in both)
# ==========================================================================
def test_b14_role_card_not_referenced():
    """iters 81/82/83 role-file dormancy preserved: foundry.py's count of the exact
    string pm_scout.md stays 0 and dispatcher.py's stays 0 (role_file is a
    PARAMETER, the literal appears nowhere). A mechanical byte-count of the module
    text located via the bare module object -- NOT a read of implementation logic
    (established iter-80/81/82/83 dormancy-hygiene convention)."""
    mtext = _MAIN_MODULE.read_text(encoding="utf-8")
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    assert mtext.count("pm_scout.md") == 0, "this bite must not reference the role card"
    assert dtext.count("pm_scout.md") == 0


# ==========================================================================
# Behavior 15 -- ASCII (scoped) + fresh-subprocess import + prior surface intact
# ==========================================================================
def test_b15_new_source_ascii():
    """The NEW code is pure ASCII. Scoped to the new symbol via inspect.getsource
    -- NOT a whole-file scan (the module carries pre-existing non-ASCII elsewhere,
    the iter-67 divider-comment em-dash trap)."""
    src = inspect.getsource(foundry.scout_phase_outcome)
    offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
    assert offenders == [], offenders[:5]


def test_b15_new_source_leak_clean():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    src = inspect.getsource(foundry.scout_phase_outcome)
    assert mod.scan_text(src, denylist) == (), "new source leaks a denylisted token"
    # matcher is ARMED (not inert): a RUNTIME-built home-path needle IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"


def test_b15_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_b15_prior_and_new_surface_present_and_callable():
    for fn in ("decide_scout_phase", "derive_scout_stage_specs", "run_scout_phase",
               "scout_phase_outcome", "run_iteration", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable"
    import dataclasses
    assert dataclasses.is_dataclass(foundry.ScoutPhasePlan)
    assert dataclasses.is_dataclass(foundry.ScoutStageSpec)
    assert dataclasses.is_dataclass(foundry.ScoutPhaseResult)
    assert foundry.PM_SCOUT_LENSES == ("new-capability", "hardening/DX")
    assert dispatcher is not None


# ==========================================================================
# Acceptance-criteria block (offline) -- this file public-safety + control path
# ==========================================================================
def test_ac_this_test_file_ascii():
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


def test_ac_this_test_file_leak_clean():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "this test file leaks a denylisted token"


@pytest.mark.skipif(not _GIT_OK, reason="not inside a git work tree")
def test_ac_control_path_byte_unchanged():
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--",
         "dispatcher.py", "scripts/", ".gitignore", "README.md", "roles/"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, "control path NOT byte-unchanged from HEAD"
