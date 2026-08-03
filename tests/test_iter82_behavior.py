"""Black-box behaviour tests for iter 82 -- dual-PM-scout feature (bite 3a of ~4):
the DORMANT pure per-scout execution-descriptor derivation core. This bite adds a
frozen `ScoutStageSpec` (fields `stage`, `out_name`, `lens`) plus
`derive_scout_stage_specs(plan: ScoutPhasePlan) -> tuple[ScoutStageSpec, ...]`,
which maps the iter-80 abstract scout plan (ordered `(stage_name, lens)` pairs)
into the concrete per-scout `run_stage` descriptors the operator-gated bite-3b
wiring will loop over -- pinning each scout's output-file-success contract to a
named file `stage + ".md"`. ZERO call site: nothing in the running pipeline
consults it this iteration. No CLI, no config field, no new module constant.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-16) and the product's own OBSERVABLE behaviour only (running it). The
implementation source (the module internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the pure derivation via
`foundry.derive_scout_stage_specs`, the abstract plan it consumes via
`foundry.decide_scout_phase`, the frozen result type `foundry.ScoutStageSpec`,
and the iter-80 call-time knob via the module attribute `foundry.PM_SCOUT_LENSES`.
The dormancy / off-control-path checks use only public RUNTIME introspection --
compiled function name tables (`__code__.co_names` recursed via `_co_names_deep`)
and a git `--quiet` exit-code probe -- plus, for the mechanical ASCII / leak-clean
/ `pm_scout.md`-count-0 acceptance criteria, `inspect.getsource` scoped to the NEW
symbols and a mechanical byte-count of the main module text (never reading
implementation LOGIC, never `git diff`). Fully offline and deterministic: NO
subprocess/git/network/agent-run except the fresh-import regression probe and the
control-path byte-unchanged git `--quiet` probe. Both new symbols
(`ScoutStageSpec`, `derive_scout_stage_specs`) are BRAND-NEW tokens this bite (no
partial pre-existence), so the deep `co_names` scan of the five orchestrators +
dispatcher.py is the authoritative dormancy proof.
"""
import dataclasses
import importlib.util
import inspect
import os
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths + constants (never a source-literal home path; the main
# module is located via the bare module object, never a quoted file-name token)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
_MAIN_MODULE = pathlib.Path(foundry.__file__).resolve()
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

# Fixed field order of the frozen per-scout descriptor.
SPEC_ORDER = ("stage", "out_name", "lens")

# The symbols this iteration ADDS. Both are BRAND-NEW tokens (unlike the iter-80/81
# command-string trap); they must be dormant -- no orchestrator and dispatcher.py
# reference either by name.
NEW_SYMBOLS = (
    "ScoutStageSpec",
    "derive_scout_stage_specs",
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
    spec = importlib.util.spec_from_file_location("leak_guard_iter82_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _specs(dual, lenses=None):
    """Convenience: build the abstract plan then derive the concrete specs."""
    if lenses is None:
        plan = foundry.decide_scout_phase(dual)
    else:
        plan = foundry.decide_scout_phase(dual, lenses=lenses)
    return plan, foundry.derive_scout_stage_specs(plan)


# ==========================================================================
# Behavior 1 -- disabled plan derives an empty tuple
# ==========================================================================
def test_b01_disabled_plan_empty_tuple():
    _plan, specs = _specs(False)
    assert specs == ()
    assert isinstance(specs, tuple)


# ==========================================================================
# Behavior 2 -- default enabled plan: 2 specs, exact stages + lenses
# ==========================================================================
def test_b02_default_enabled_two_specs():
    _plan, specs = _specs(True)
    assert len(specs) == 2
    assert specs[0].stage == "pm_scout_a"
    assert specs[0].lens == "new-capability"
    assert specs[1].stage == "pm_scout_b"
    assert specs[1].lens == "hardening/DX"


# ==========================================================================
# Behavior 3 -- out_name == stage + ".md" for every spec (named output file)
# ==========================================================================
def test_b03_out_name_is_stage_dot_md():
    _plan, specs = _specs(True)
    for spec in specs:
        assert spec.out_name == spec.stage + ".md"
    assert [s.out_name for s in specs] == ["pm_scout_a.md", "pm_scout_b.md"]


def test_b03_out_name_rule_holds_for_many_lens_counts():
    for lenses in [("a",), ("a", "b"), ("a", "b", "c"), ("a", "b", "c", "d")]:
        _plan, specs = _specs(True, lenses=lenses)
        for spec in specs:
            assert spec.out_name == spec.stage + ".md"


# ==========================================================================
# Behavior 4 -- order preserved from plan.stages; len == plan.count
# ==========================================================================
def test_b04_order_preserved_and_len_matches_count():
    for lenses in [(), ("solo",), ("x", "y"), ("x", "y", "z"), ("l1", "l2", "l3", "l4")]:
        plan, specs = _specs(True, lenses=lenses)
        assert len(specs) == plan.count
        for i, spec in enumerate(specs):
            assert spec.stage == plan.stages[i][0], f"stage mismatch at {i} for {lenses!r}"
            assert spec.lens == plan.stages[i][1], f"lens mismatch at {i} for {lenses!r}"


def test_b04_order_preserved_default_plan():
    plan, specs = _specs(True)
    assert tuple(s.stage for s in specs) == tuple(name for name, _ in plan.stages)
    assert tuple(s.lens for s in specs) == tuple(lens for _, lens in plan.stages)


# ==========================================================================
# Behavior 5 -- a 3-lens plan derives 3 specs a/b/c with matching out_names+lenses
# ==========================================================================
def test_b05_three_lens_plan():
    _plan, specs = _specs(True, lenses=("x", "y", "z"))
    assert tuple(s.stage for s in specs) == ("pm_scout_a", "pm_scout_b", "pm_scout_c")
    assert tuple(s.out_name for s in specs) == (
        "pm_scout_a.md", "pm_scout_b.md", "pm_scout_c.md",
    )
    assert tuple(s.lens for s in specs) == ("x", "y", "z")


# ==========================================================================
# Behavior 6 -- a 1-lens plan derives exactly one spec
# ==========================================================================
def test_b06_single_lens_plan():
    _plan, specs = _specs(True, lenses=("solo",))
    assert len(specs) == 1
    assert specs[0].stage == "pm_scout_a"
    assert specs[0].out_name == "pm_scout_a.md"
    assert specs[0].lens == "solo"


# ==========================================================================
# Behavior 7 -- degenerate enabled-but-empty plan -> () total, no exception
# ==========================================================================
def test_b07_enabled_empty_lenses_total_empty_tuple():
    plan, specs = _specs(True, lenses=())
    assert plan.enabled is True  # the FLAG is still enabled ...
    assert specs == ()           # ... yet zero stages derive zero specs
    assert isinstance(specs, tuple)


# ==========================================================================
# Behavior 8 -- lens carried verbatim, including a slash-bearing lens
# ==========================================================================
def test_b08_lens_carried_verbatim_slash_survives():
    _plan, specs = _specs(True)
    assert specs[1].lens == "hardening/DX"
    # an arbitrary punctuation-heavy lens survives untouched
    _p2, s2 = _specs(True, lenses=("a/b/c", "x:y", "  spaced  "))
    assert [s.lens for s in s2] == ["a/b/c", "x:y", "  spaced  "]


# ==========================================================================
# Behavior 9 -- return is a tuple; every element isinstance ScoutStageSpec
# ==========================================================================
def test_b09_returns_tuple_of_scout_stage_spec():
    _plan, specs = _specs(True, lenses=("x", "y", "z"))
    assert isinstance(specs, tuple)
    assert not isinstance(specs, list)
    assert all(isinstance(s, foundry.ScoutStageSpec) for s in specs)


def test_b09_empty_cases_still_tuple():
    assert isinstance(_specs(False)[1], tuple)
    assert isinstance(_specs(True, lenses=())[1], tuple)


# ==========================================================================
# Behavior 10 -- ScoutStageSpec is frozen: field assignment raises
# ==========================================================================
def test_b10_scout_stage_spec_is_frozen():
    assert dataclasses.is_dataclass(foundry.ScoutStageSpec)
    _plan, specs = _specs(True)
    for field in SPEC_ORDER:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(specs[0], field, "x")


def test_b10_field_names_and_order():
    got = tuple(f.name for f in dataclasses.fields(foundry.ScoutStageSpec))
    assert got == SPEC_ORDER


# ==========================================================================
# Behavior 11 -- value equality (tuples from equal args; specs with equal fields)
# ==========================================================================
def test_b11_derive_value_equality():
    a = foundry.derive_scout_stage_specs(foundry.decide_scout_phase(True, lenses=("p", "q")))
    b = foundry.derive_scout_stage_specs(foundry.decide_scout_phase(True, lenses=("p", "q")))
    assert a == b
    assert foundry.derive_scout_stage_specs(foundry.decide_scout_phase(False)) == ()


def test_b11_scout_stage_spec_value_equality():
    s1 = foundry.ScoutStageSpec(stage="pm_scout_a", out_name="pm_scout_a.md", lens="cap")
    s2 = foundry.ScoutStageSpec(stage="pm_scout_a", out_name="pm_scout_a.md", lens="cap")
    s3 = foundry.ScoutStageSpec(stage="pm_scout_a", out_name="pm_scout_a.md", lens="other")
    assert s1 == s2
    assert s1 != s3


# ==========================================================================
# Behavior 12 -- purity / totality
# ==========================================================================
def test_b12_writes_nothing_to_empty_cwd(tmp_path):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    prev = os.getcwd()
    os.chdir(cwd)
    try:
        before = sorted(x.name for x in cwd.iterdir())
        for dual, lenses in [(False, None), (True, None), (True, ()),
                             (True, ("x",)), (True, ("x", "y", "z"))]:
            _specs(dual, lenses=lenses)
        after = sorted(x.name for x in cwd.iterdir())
    finally:
        os.chdir(prev)
    assert before == after == [], f"derive wrote to the working dir: {before} -> {after}"


def test_b12_total_never_raises_for_any_scout_plan():
    """Reasonable reading of the spec's awkward 'raises for no ScoutPhasePlan
    input' clause: the function is TOTAL -- for every ScoutPhasePlan (enabled or
    disabled, any lens count) it returns a tuple and raises nothing."""
    plans = [
        foundry.decide_scout_phase(False),
        foundry.decide_scout_phase(True),
        foundry.decide_scout_phase(True, lenses=()),
        foundry.decide_scout_phase(True, lenses=("a",)),
        foundry.decide_scout_phase(True, lenses=("a", "b", "c", "d", "e")),
    ]
    for plan in plans:
        out = foundry.derive_scout_stage_specs(plan)
        assert isinstance(out, tuple)


def test_b12_pure_no_filesystem_access(monkeypatch):
    """Stronger purity guard: the derivation opens no file. Sabotage
    builtins.open; it must still succeed."""
    def _boom(*a, **k):
        raise AssertionError("derive_scout_stage_specs performed filesystem I/O")
    monkeypatch.setattr("builtins.open", _boom)
    _plan, specs = _specs(True)
    assert len(specs) == 2


# ==========================================================================
# Behavior 13 -- composition with the iter-80 call-time knob PM_SCOUT_LENSES
# ==========================================================================
def test_b13_composes_with_lens_knob(monkeypatch):
    # default: 2 specs
    assert len(_specs(True)[1]) == 2
    monkeypatch.setattr(foundry, "PM_SCOUT_LENSES", ("only",))
    _plan, specs = _specs(True)
    assert len(specs) == 1, "patched PM_SCOUT_LENSES not honored through the derivation"
    assert specs[0].stage == "pm_scout_a"
    assert specs[0].out_name == "pm_scout_a.md"
    assert specs[0].lens == "only"


def test_b13_restore_reverts_to_default(monkeypatch):
    # the monkeypatch from the previous test is undone -> the default returns
    assert foundry.PM_SCOUT_LENSES == ("new-capability", "hardening/DX")
    _plan, specs = _specs(True)
    assert len(specs) == 2
    assert tuple(s.lens for s in specs) == ("new-capability", "hardening/DX")


# ==========================================================================
# Behavior 14 -- dormancy: absent from the deep co_names of all five
# orchestrators AND from dispatcher.py's source text
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
# Behavior 15 -- public-safety + iter-81 role-file dormancy preserved
# ==========================================================================
def test_b15_new_symbols_ascii():
    """The NEW code is pure ASCII. Scoped to the new symbols via
    inspect.getsource -- NOT a whole-file scan (the module carries pre-existing
    non-ASCII elsewhere -- the iter-67 trap)."""
    for src in (inspect.getsource(foundry.ScoutStageSpec),
                inspect.getsource(foundry.derive_scout_stage_specs)):
        offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert offenders == [], offenders[:5]


def test_b15_new_symbols_leak_clean():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    combined = (inspect.getsource(foundry.ScoutStageSpec)
                + "\n" + inspect.getsource(foundry.derive_scout_stage_specs))
    assert mod.scan_text(combined, denylist) == (), "new source leaks a denylisted token"
    # matcher is ARMED (not inert): a RUNTIME-built home-path needle IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"


def test_b15_role_card_not_referenced():
    """iter-81 role-file dormancy preserved: the main module's count of the exact
    string pm_scout.md stays 0 (this bite does NOT reference the role card).
    A mechanical byte-count of the module text -- NOT a read of implementation
    logic (established iter-80/81 dormancy-hygiene convention)."""
    text = _MAIN_MODULE.read_text(encoding="utf-8")
    assert text.count("pm_scout.md") == 0, "this bite must not reference the role card"


# ==========================================================================
# Behavior 16 -- non-regression + fresh-subprocess import
# ==========================================================================
def test_b16_prior_surface_present_and_callable():
    for fn in ("decide_scout_phase", "load_config", "run_iteration",
               "run_execution_plan"):
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"
    assert dataclasses.is_dataclass(foundry.ScoutPhasePlan)
    lenses = foundry.PM_SCOUT_LENSES
    assert isinstance(lenses, tuple)
    assert lenses == ("new-capability", "hardening/DX")
    # this bite's own new surface is present + callable
    assert callable(foundry.derive_scout_stage_specs)
    assert dataclasses.is_dataclass(foundry.ScoutStageSpec)
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
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py", "scripts/", ".gitignore"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, "dispatcher.py / scripts / .gitignore NOT byte-unchanged from HEAD"
