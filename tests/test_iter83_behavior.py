"""Black-box behaviour tests for iter 83 -- dual-PM-scout feature (bite 3b-i of ~4):
the DORMANT module-level scout-phase EXECUTOR. This bite adds a frozen
`ScoutPhaseResult` (fields `ok`, `outputs`, `failed_stage`) plus
`run_scout_phase(cfg, iteration, plan, role_file) -> ScoutPhaseResult`, which given
an iter-80 `ScoutPhasePlan` derives the iter-82 per-scout `ScoutStageSpec`s and runs
each scout stage SEQUENTIALLY (concurrency 1 preserved) via the `run_stage` seam,
keying each on its `out_name`, threading the passed-in `role_file` through verbatim,
and passing that scout's assigned lens in the prompt -- returning which scouts
produced output, with NO revert on any path. ZERO call site: no orchestrator calls
it, no CLI, no config field, no new module constant. The `role_file` is a PARAMETER,
so the literal card name never enters foundry.py and iters 81/82's role-file count-0
dormancy tests stay green.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-16) and the product's own OBSERVABLE behaviour only (running it and
introspecting its PUBLIC interface). The implementation source (the module
internals / how the executor is coded), the engineer's and reviewer's notes, and
`git diff` content were NOT read to design these behaviour tests. Every functional
check drives the PUBLIC interface: the executor `foundry.run_scout_phase`, the
abstract plan it consumes via `foundry.decide_scout_phase`, the frozen result type
`foundry.ScoutPhaseResult`, and the monkeypatchable module-level seams
`foundry.run_stage` / `foundry.revert_repo` / `foundry.derive_scout_stage_specs`
(installed as recording stubs). The dormancy / off-control-path checks use only
public RUNTIME introspection -- compiled function name tables
(`__code__.co_names` recursed via `_co_names_deep`) and a git `--quiet` exit-code
probe (exit status only, never diff content) -- plus, for the mechanical ASCII /
leak-clean / `pm_scout.md`-count-0 acceptance criteria, `inspect.getsource` scoped
to the NEW symbols and a mechanical byte-count of the main module text located via
the bare module object (never reading implementation LOGIC, never a quoted
main-module file-name literal). Fully offline and deterministic: NO
subprocess/git/network/agent-run except the fresh-import regression probe and the
control-path byte-unchanged git `--quiet` probe. Both new symbols
(`run_scout_phase`, `ScoutPhaseResult`) are BRAND-NEW tokens this bite (no partial
pre-existence from a sibling iteration), so the deep `co_names` scan of the five
orchestrators + dispatcher.py source count is the authoritative dormancy proof.
"""
import dataclasses
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

# a placeholder cfg (the executor threads it through, never inspects it) + a
# distinctive role-file sentinel (proves the card name is a PARAMETER, not baked in)
CFG = "PLACEHOLDER_CFG"
ITERATION = 83
ROLE = "CARD.md"

# fixed field order of the frozen phase-result value type
RESULT_ORDER = ("ok", "outputs", "failed_stage")

# The two symbols this iteration ADDS. Both are BRAND-NEW tokens (unlike the
# iter-80/81 command-string trap); they must be dormant -- no orchestrator and
# dispatcher.py reference either by name.
NEW_SYMBOLS = (
    "run_scout_phase",
    "ScoutPhaseResult",
)

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
    spec = importlib.util.spec_from_file_location("leak_guard_iter83_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


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


def _plan(dual, lenses=None):
    if lenses is None:
        return foundry.decide_scout_phase(dual)
    return foundry.decide_scout_phase(dual, lenses=lenses)


# ==========================================================================
# Behavior 1 -- DISABLED plan is a vacuous success with zero agent calls
# ==========================================================================
def test_b01_disabled_plan_vacuous_success_zero_calls(monkeypatch):
    rec, rev = _install(monkeypatch)
    res = foundry.run_scout_phase(CFG, ITERATION, _plan(False), ROLE)
    assert res.ok is True
    assert res.outputs == ()
    assert res.failed_stage is None
    assert rec.calls == [], "run_stage must not be called for a disabled plan"
    assert rev.calls == []


# ==========================================================================
# Behavior 2 -- DEFAULT enabled plan runs both scouts and succeeds
# ==========================================================================
def test_b02_default_enabled_runs_both_scouts_success(monkeypatch):
    rec, _rev = _install(monkeypatch)
    res = foundry.run_scout_phase(CFG, ITERATION, _plan(True), ROLE)
    assert res.ok is True
    assert res.outputs == ("pm_scout_a.md", "pm_scout_b.md")
    assert res.failed_stage is None
    assert len(rec.calls) == 2


# ==========================================================================
# Behavior 3 -- SEQUENTIAL ORDER preserved (never reversed)
# ==========================================================================
def test_b03_sequential_order_preserved(monkeypatch):
    rec, _rev = _install(monkeypatch)
    foundry.run_scout_phase(CFG, ITERATION, _plan(True), ROLE)
    assert [c.stage for c in rec.calls] == ["pm_scout_a", "pm_scout_b"]


# ==========================================================================
# Behavior 4 -- each scout's out_name argument equals that scout's spec.out_name
# ==========================================================================
def test_b04_out_name_matches_named_output_file(monkeypatch):
    rec, _rev = _install(monkeypatch)
    foundry.run_scout_phase(CFG, ITERATION, _plan(True), ROLE)
    assert [c.out_name for c in rec.calls] == ["pm_scout_a.md", "pm_scout_b.md"]
    # each call's out_name is exactly its stage + ".md"
    for c in rec.calls:
        assert c.out_name == c.stage + ".md"


# ==========================================================================
# Behavior 5 -- ROLE_FILE passed through verbatim to EVERY run_stage call
# ==========================================================================
def test_b05_role_file_passed_through_verbatim(monkeypatch):
    rec, _rev = _install(monkeypatch)
    foundry.run_scout_phase(CFG, ITERATION, _plan(True), ROLE)
    assert len(rec.calls) == 2
    for c in rec.calls:
        assert c.role_file == ROLE, "role_file must be threaded through unchanged"


def test_b05_a_different_role_file_sentinel_is_also_passed_through(monkeypatch):
    rec = RunStageRecorder()
    monkeypatch.setattr(foundry, "run_stage", rec)
    monkeypatch.setattr(foundry, "revert_repo", RevertRecorder())
    foundry.run_scout_phase(CFG, ITERATION, _plan(True), "OTHER_CARD.md")
    assert len(rec.calls) == 2
    assert all(c.role_file == "OTHER_CARD.md" for c in rec.calls)


# ==========================================================================
# Behavior 6 -- each scout carries its assigned LENS in the prompt (extra)
# ==========================================================================
def test_b06_each_scout_carries_its_lens_in_extra(monkeypatch):
    rec, _rev = _install(monkeypatch)
    foundry.run_scout_phase(CFG, ITERATION, _plan(True), ROLE)
    by_stage = {c.stage: c for c in rec.calls}
    assert "new-capability" in by_stage["pm_scout_a"].extra
    assert "hardening/DX" in by_stage["pm_scout_b"].extra


# ==========================================================================
# Behavior 7 -- FIRST-scout failure short-circuits WITHOUT reverting
# ==========================================================================
def test_b07_first_scout_failure_short_circuits_no_revert(monkeypatch):
    rec, rev = _install(monkeypatch, fail_stages=("pm_scout_a",))
    res = foundry.run_scout_phase(CFG, ITERATION, _plan(True), ROLE)
    assert res.ok is False
    assert res.failed_stage == "pm_scout_a"
    assert res.outputs == ()
    assert len(rec.calls) == 1, "the second scout must NOT run after the first fails"
    assert [c.stage for c in rec.calls] == ["pm_scout_a"]
    assert rev.calls == [], "revert_repo must never be called (scouts run pre-build)"


# ==========================================================================
# Behavior 8 -- LATER-scout failure retains earlier successes, no revert
# ==========================================================================
def test_b08_later_scout_failure_retains_earlier_no_revert(monkeypatch):
    rec, rev = _install(monkeypatch, fail_stages=("pm_scout_b",))
    res = foundry.run_scout_phase(CFG, ITERATION, _plan(True), ROLE)
    assert res.ok is False
    assert res.failed_stage == "pm_scout_b"
    assert res.outputs == ("pm_scout_a.md",), "the earlier success is retained"
    assert len(rec.calls) == 2
    assert rev.calls == []


# ==========================================================================
# Behavior 9 -- NO REVERT on the SUCCESS path either
# ==========================================================================
def test_b09_no_revert_on_success_path(monkeypatch):
    _rec, rev = _install(monkeypatch)
    res = foundry.run_scout_phase(CFG, ITERATION, _plan(True), ROLE)
    assert res.ok is True
    assert rev.calls == []


# ==========================================================================
# Behavior 10 -- VARIABLE scout count generalizes beyond 2
# ==========================================================================
def test_b10_variable_scout_count_generalizes(monkeypatch):
    rec, rev = _install(monkeypatch)
    plan = _plan(True, lenses=("alpha", "beta", "gamma"))
    res = foundry.run_scout_phase(CFG, ITERATION, plan, ROLE)
    assert res.ok is True
    assert [c.stage for c in rec.calls] == ["pm_scout_a", "pm_scout_b", "pm_scout_c"]
    assert res.outputs == ("pm_scout_a.md", "pm_scout_b.md", "pm_scout_c.md")
    by_stage = {c.stage: c for c in rec.calls}
    assert "alpha" in by_stage["pm_scout_a"].extra
    assert "beta" in by_stage["pm_scout_b"].extra
    assert "gamma" in by_stage["pm_scout_c"].extra
    assert rev.calls == []


# ==========================================================================
# Behavior 11 -- ScoutPhaseResult is a FROZEN value type
# ==========================================================================
def test_b11_result_is_frozen():
    assert dataclasses.is_dataclass(foundry.ScoutPhaseResult)
    r = foundry.ScoutPhaseResult(ok=True, outputs=("pm_scout_a.md",), failed_stage=None)
    for field in RESULT_ORDER:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(r, field, "x")


def test_b11_result_value_equality():
    a = foundry.ScoutPhaseResult(ok=True, outputs=("x.md",), failed_stage=None)
    b = foundry.ScoutPhaseResult(ok=True, outputs=("x.md",), failed_stage=None)
    c = foundry.ScoutPhaseResult(ok=False, outputs=(), failed_stage="pm_scout_a")
    assert a == b
    assert a != c


def test_b11_result_field_names_and_order():
    got = tuple(f.name for f in dataclasses.fields(foundry.ScoutPhaseResult))
    assert got == RESULT_ORDER


def test_b11_failed_stage_defaults_to_none():
    r = foundry.ScoutPhaseResult(ok=True, outputs=())
    assert r.failed_stage is None


# ==========================================================================
# Behavior 12 -- the executor performs NO direct I/O of its own
# ==========================================================================
def test_b12_executor_no_direct_io(monkeypatch, tmp_path):
    # run_stage replaced by a pure recording stub; derive_scout_stage_specs left
    # real/pure -- every external effect must be delegated to the run_stage seam.
    rec = RunStageRecorder()
    monkeypatch.setattr(foundry, "run_stage", rec)
    monkeypatch.setattr(foundry, "revert_repo", RevertRecorder())
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    prev = os.getcwd()
    os.chdir(cwd)
    try:
        before = sorted(x.name for x in cwd.iterdir())
        foundry.run_scout_phase(CFG, ITERATION, _plan(True), ROLE)
        foundry.run_scout_phase(CFG, ITERATION, _plan(False), ROLE)
        foundry.run_scout_phase(CFG, ITERATION, _plan(True, lenses=("x", "y", "z")), ROLE)
        after = sorted(x.name for x in cwd.iterdir())
    finally:
        os.chdir(prev)
    assert before == after == [], f"run_scout_phase wrote to the cwd: {before} -> {after}"


def test_b12_executor_opens_no_file(monkeypatch):
    """Stronger purity guard: with run_stage stubbed, the executor opens no file.
    Sabotage builtins.open; run_scout_phase must still succeed."""
    rec = RunStageRecorder()
    monkeypatch.setattr(foundry, "run_stage", rec)
    monkeypatch.setattr(foundry, "revert_repo", RevertRecorder())

    def _boom(*a, **k):
        raise AssertionError("run_scout_phase performed filesystem I/O of its own")

    monkeypatch.setattr("builtins.open", _boom)
    res = foundry.run_scout_phase(CFG, ITERATION, _plan(True), ROLE)
    assert res.ok is True
    assert len(rec.calls) == 2


# ==========================================================================
# Behavior 13 -- seams called by BARE MODULE NAME (monkeypatch bites)
# ==========================================================================
def test_b13_derive_seam_read_as_module_global(monkeypatch):
    rec, _rev = _install(monkeypatch)
    monkeypatch.setattr(foundry, "derive_scout_stage_specs", lambda plan: ())
    res = foundry.run_scout_phase(CFG, ITERATION, _plan(True), ROLE)
    assert res.ok is True
    assert res.outputs == ()
    assert len(rec.calls) == 0, "patched derive_scout_stage_specs not read at call time"


# ==========================================================================
# Behavior 14 -- DORMANCY / zero call site
# ==========================================================================
def test_b14_dormant_zero_call_site():
    new = set(NEW_SYMBOLS)
    orchestrators = (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
                     foundry.run_continuous, foundry.run_execution_plan)
    for fn in orchestrators:
        refs = _co_names_deep(fn) & new
        assert refs == set(), f"foundry.{fn.__name__} references dormant symbol(s): {refs}"
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in NEW_SYMBOLS:
        assert sym not in dtext, f"dispatcher.py references dormant symbol {sym!r}"


# ==========================================================================
# Behavior 15 -- iter-81/82 role-file dormancy preserved + public-safety
# ==========================================================================
def test_b15_role_card_not_referenced():
    """iter-81/82 role-file dormancy preserved: the main module's count of the
    exact string pm_scout.md stays 0, and dispatcher.py's count stays 0 (the
    executor takes the card name as a PARAMETER, never hardcodes it). A mechanical
    byte-count of the module text located via the bare module object -- NOT a read
    of implementation logic (established iter-80/81/82 dormancy-hygiene convention)."""
    mtext = _MAIN_MODULE.read_text(encoding="utf-8")
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    assert mtext.count("pm_scout.md") == 0, "this bite must not reference the role card"
    assert dtext.count("pm_scout.md") == 0


def test_b15_new_source_ascii():
    """The NEW code is pure ASCII. Scoped to the new symbols via inspect.getsource
    -- NOT a whole-file scan (the module carries pre-existing non-ASCII elsewhere,
    the iter-67 trap)."""
    for src in (inspect.getsource(foundry.ScoutPhaseResult),
                inspect.getsource(foundry.run_scout_phase)):
        offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert offenders == [], offenders[:5]


def test_b15_new_source_leak_clean():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    combined = (inspect.getsource(foundry.ScoutPhaseResult)
                + "\n" + inspect.getsource(foundry.run_scout_phase))
    assert mod.scan_text(combined, denylist) == (), "new source leaks a denylisted token"
    # matcher is ARMED (not inert): a RUNTIME-built home-path needle IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"


# ==========================================================================
# Behavior 16 -- non-regression + fresh-subprocess import
# ==========================================================================
def test_b16_prior_and_new_surface_present_and_callable():
    for fn in ("decide_scout_phase", "derive_scout_stage_specs", "run_iteration",
               "run_execution_plan", "run_scout_phase"):
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"
    assert dataclasses.is_dataclass(foundry.ScoutPhasePlan)
    assert dataclasses.is_dataclass(foundry.ScoutStageSpec)
    assert dataclasses.is_dataclass(foundry.ScoutPhaseResult)
    lenses = foundry.PM_SCOUT_LENSES
    assert isinstance(lenses, tuple)
    assert lenses == ("new-capability", "hardening/DX")
    assert dispatcher is not None


def test_b16_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


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
    # Scope is deliberately the RUNNING-LOOP control path only. README.md is
    # documentation (the ship gate REQUIRES a README entry for each new CLI, so
    # freezing it here would deadlock the loop) and roles/ are operator-gated
    # prompts -- neither is control path. This guard runs on every future suite,
    # so an over-broad pathspec becomes a permanent block on legitimate edits.
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--",
         "dispatcher.py", "scripts/", ".gitignore"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, (
        "control path (dispatcher.py/scripts/.gitignore) NOT byte-unchanged from HEAD")
