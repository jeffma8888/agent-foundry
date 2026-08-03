"""Black-box behaviour tests for iter 80 -- dual-PM-scout feature (bite 1 of ~3):
the DORMANT pure PM-scout PHASE PLANNER
`decide_scout_phase(dual_pm_scouts, lenses=None) -> ScoutPhasePlan` (frozen
`ScoutPhasePlan` with fields enabled/stages + pure props count/stage_names/
verdict), driven by a patchable module-level
`PM_SCOUT_LENSES = ("new-capability", "hardening/DX")` read at CALL time, plus an
on-demand read-only `foundry scout-plan [--dual-pm-scouts] [--lens L ...]` CLI
(exit 1 DUAL / 0 SINGLE, no file arg). Per docs/DUAL_PM_SCOUT_SPEC.md: an
OPTIONAL two-scout pre-stage the eventual wiring bite will call to know WHICH
scout stages to run, in what ORDER, with which LENS. ZERO call site: nothing in
the running pipeline consults it this iteration.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-16) and the product's own OBSERVABLE behaviour only (running it). The
implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the pure core via `foundry.decide_scout_phase`, the
patchable lens tuple via the module attribute `foundry.PM_SCOUT_LENSES`, and the
CLI via `foundry.main(["scout-plan", ...])`. The dormancy / off-control-path
checks use only public RUNTIME introspection -- module attributes, compiled
function name tables (`__code__.co_names` recursed via `_co_names_deep`),
`--help` output, and a git `--quiet` exit-code probe -- plus, for the mechanical
ASCII / leak-clean acceptance criteria, `inspect.getsource` scoped to the NEW
symbols only (the established suite convention; never a whole-file scan / never
`git diff`). Fully offline and deterministic: NO subprocess/git/network/agent-run
except the fresh-import + `--help` regression probes and the control-path
byte-unchanged git `--quiet` probe. The dormancy proof is scoped to the SYMBOLS
and the `scout-plan` / `pm_scout` command/stage strings in the five orchestrators
+ dispatcher.py ONLY -- never a bare `rg scout-plan foundry.py`, which now
self-matches the new CLI code.
"""
import dataclasses
import importlib.util
import inspect
import io
import contextlib
import os
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths + constants (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

# Fixed field order of the frozen result dataclass.
PLAN_ORDER = ("enabled", "stages")

# The symbols this iteration ADDS. They must be dormant: no orchestrator and
# dispatcher.py reference any of them by name.
NEW_SYMBOLS = (
    "decide_scout_phase",
    "ScoutPhasePlan",
    "PM_SCOUT_LENSES",
    "scout_plan_cli",
)

# Command / stage strings introduced by this bite. Free everywhere before it,
# they now legitimately appear in the new CLI code -- so the dormancy proof
# scans the orchestrators + dispatcher.py for them, never a whole-file grep.
NEW_STRINGS = ("scout-plan", "pm_scout")

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


def _co_consts_deep(fn):
    """Every constant (incl. nested-code constants) referenced by fn's code,
    recursed. Used to prove the command/stage STRINGS are absent too."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        for c in code.co_consts:
            if hasattr(c, "co_names"):
                stack.append(c)
            elif isinstance(c, str):
                seen.add(c)
    return seen


def _leak_guard():
    """Dynamically import the committed leak-guard, registering the module in
    sys.modules BEFORE exec so its own import machinery works."""
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter80_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cli(args):
    """Drive the CLI via foundry.main, capturing stdout + exit code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.main(list(args))
    return rc, buf.getvalue()


def _stage_line_present(out, name, lens):
    """True iff SOME output line contains BOTH the stage name and its lens."""
    return any(name in line and lens in line for line in out.splitlines())


# ==========================================================================
# Behavior 1 -- disabled: enabled False, empty stages, count 0, SINGLE
# ==========================================================================
def test_b01_disabled_plan():
    d = foundry.decide_scout_phase(False)
    assert d.enabled is False
    assert d.stages == ()
    assert d.count == 0
    assert d.stage_names == ()
    assert d.verdict == "SINGLE"


def test_b01_total_never_raises_and_typed():
    cases = [False, True, 0, 1, None, "", "x", [], [1], (True, ("a",)),
             (True, ()), (True, ("a", "b", "c"))]
    for c in cases:
        if isinstance(c, tuple):
            r = foundry.decide_scout_phase(c[0], lenses=c[1])
        else:
            r = foundry.decide_scout_phase(c)
        assert type(r).__name__ == "ScoutPhasePlan", (
            f"decide_scout_phase did not return ScoutPhasePlan for {c!r}"
        )


def test_b01_pure_no_filesystem_access(monkeypatch):
    """Pure: the core opens no file. Sabotage builtins.open; it still works."""
    def _boom(*a, **k):
        raise AssertionError("decide_scout_phase performed filesystem I/O")
    monkeypatch.setattr("builtins.open", _boom)
    d = foundry.decide_scout_phase(True)
    assert d.verdict == "DUAL" and d.count == 2


# ==========================================================================
# Behavior 2 -- default enabled: 2 stages, correct names, lenses, DUAL
# ==========================================================================
def test_b02_default_enabled_plan():
    d = foundry.decide_scout_phase(True)
    assert d.enabled is True
    assert d.count == 2
    assert d.stage_names == ("pm_scout_a", "pm_scout_b")
    assert d.verdict == "DUAL"
    assert d.stages == (
        ("pm_scout_a", "new-capability"),
        ("pm_scout_b", "hardening/DX"),
    )


def test_b02_count_matches_len_stages():
    d = foundry.decide_scout_phase(True)
    assert d.count == len(d.stages)
    assert d.stage_names == tuple(name for name, _ in d.stages)


# ==========================================================================
# Behavior 3 -- bool coercion of dual_pm_scouts
# ==========================================================================
def test_b03_falsy_inputs_disabled():
    for falsy in (0, "", None, []):
        d = foundry.decide_scout_phase(falsy)
        assert d.enabled is False, f"{falsy!r} should coerce to disabled"
        assert d.verdict == "SINGLE"
        assert d.stages == ()
        assert d.count == 0


def test_b03_truthy_inputs_enabled():
    for truthy in (1, "x", [1], object()):
        d = foundry.decide_scout_phase(truthy)
        assert d.enabled is True, f"{truthy!r} should coerce to enabled"
        assert d.verdict == "DUAL"


def test_b03_enabled_is_real_bool():
    # `enabled` is a genuine bool (bool(...) coercion), not the raw input object
    assert foundry.decide_scout_phase("x").enabled is True
    assert foundry.decide_scout_phase("").enabled is False


# ==========================================================================
# Behavior 4 -- stage names assigned by position a, b, c, ...
# ==========================================================================
def test_b04_positional_stage_names_and_pairing():
    d = foundry.decide_scout_phase(True, lenses=("cap", "harden", "docs"))
    assert d.stage_names == ("pm_scout_a", "pm_scout_b", "pm_scout_c")
    assert d.stages[2] == ("pm_scout_c", "docs")
    assert d.stages[0] == ("pm_scout_a", "cap")
    assert d.stages[1] == ("pm_scout_b", "harden")
    assert d.count == 3


# ==========================================================================
# Behavior 5 -- exactly one explicit lens
# ==========================================================================
def test_b05_single_lens():
    d = foundry.decide_scout_phase(True, lenses=("solo",))
    assert d.count == 1
    assert d.stage_names == ("pm_scout_a",)
    assert d.stages == (("pm_scout_a", "solo"),)
    assert d.verdict == "DUAL"


# ==========================================================================
# Behavior 6 -- degenerate but TOTAL: enabled with empty lenses
# ==========================================================================
def test_b06_enabled_empty_lenses_total():
    d = foundry.decide_scout_phase(True, lenses=())
    assert d.enabled is True
    assert d.stages == ()
    assert d.count == 0
    assert d.stage_names == ()
    assert d.verdict == "DUAL", "verdict must mirror the flag, not the stage count"


def test_b06_verdict_and_count_are_decoupled():
    # enabled-but-empty: verdict DUAL yet count 0 -- verdict tracks the FLAG,
    # not count>0 (a naive keying off count would diverge here).
    d = foundry.decide_scout_phase(True, lenses=())
    assert (d.verdict == "DUAL") == d.enabled
    assert d.count == 0


# ==========================================================================
# Behavior 7 -- explicit lenses OVERRIDE the module default
# ==========================================================================
def test_b07_explicit_lenses_override_default():
    d = foundry.decide_scout_phase(True, lenses=("x", "y", "z"))
    assert d.count == 3
    assert d.stage_names == ("pm_scout_a", "pm_scout_b", "pm_scout_c")
    # NOT the two module-default lenses
    assert "new-capability" not in [lens for _, lens in d.stages]


# ==========================================================================
# Behavior 8 -- call-time knob: monkeypatch PM_SCOUT_LENSES flips a subsequent
# decide; restore reverts (proves read INSIDE the function, not def-time capture)
# ==========================================================================
def test_b08_lens_knob_call_time_read(monkeypatch):
    orig = foundry.PM_SCOUT_LENSES
    # default: 2 lenses
    assert foundry.decide_scout_phase(True).count == 2
    monkeypatch.setattr(foundry, "PM_SCOUT_LENSES", ("only",))
    d = foundry.decide_scout_phase(True)
    assert d.count == 1, "patched PM_SCOUT_LENSES not honored (def-time capture?)"
    assert d.stage_names == ("pm_scout_a",)
    assert d.stages == (("pm_scout_a", "only"),)
    # sanity: the original was the 2-lens default
    assert orig == ("new-capability", "hardening/DX")


def test_b08_restore_reverts():
    # after the previous test's monkeypatch is undone, the default returns
    assert foundry.PM_SCOUT_LENSES == ("new-capability", "hardening/DX")
    d = foundry.decide_scout_phase(True)
    assert d.count == 2
    assert d.stages == (
        ("pm_scout_a", "new-capability"),
        ("pm_scout_b", "hardening/DX"),
    )


def test_b08_patched_three_lens_knob(monkeypatch):
    monkeypatch.setattr(foundry, "PM_SCOUT_LENSES", ("l1", "l2", "l3"))
    d = foundry.decide_scout_phase(True)
    assert d.count == 3
    assert d.stage_names == ("pm_scout_a", "pm_scout_b", "pm_scout_c")


# ==========================================================================
# Behavior 9 -- lenses=None identical to omitting lenses
# ==========================================================================
def test_b09_none_equals_omitted():
    assert foundry.decide_scout_phase(True, lenses=None) == foundry.decide_scout_phase(True)
    assert foundry.decide_scout_phase(True, lenses=None).count == 2


# ==========================================================================
# Behavior 10 -- lenses accepts any iterable (list, tuple, one-shot generator)
# ==========================================================================
def test_b10_list_and_tuple_iterables():
    from_list = foundry.decide_scout_phase(True, lenses=["l1", "l2"])
    from_tuple = foundry.decide_scout_phase(True, lenses=("l1", "l2"))
    assert from_list == from_tuple
    assert from_list.stages == (("pm_scout_a", "l1"), ("pm_scout_b", "l2"))


def test_b10_one_shot_generator_iterable():
    gen = (x for x in ("g1", "g2", "g3"))
    d = foundry.decide_scout_phase(True, lenses=gen)
    # a one-shot generator must be materialized once, in order, without dropping
    assert d.count == 3
    assert d.stage_names == ("pm_scout_a", "pm_scout_b", "pm_scout_c")
    assert d.stages == (
        ("pm_scout_a", "g1"), ("pm_scout_b", "g2"), ("pm_scout_c", "g3"),
    )


# ==========================================================================
# Behavior 11 -- ScoutPhasePlan is frozen
# ==========================================================================
def test_b11_frozen_plan():
    assert dataclasses.is_dataclass(foundry.ScoutPhasePlan)
    d = foundry.decide_scout_phase(True)
    for field, value in (("enabled", False), ("stages", ())):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(d, field, value)


def test_b11_field_names_and_order():
    assert tuple(f.name for f in dataclasses.fields(foundry.ScoutPhasePlan)) == PLAN_ORDER


# ==========================================================================
# Behavior 12 -- value equality
# ==========================================================================
def test_b12_value_equality():
    assert foundry.decide_scout_phase(True) == foundry.decide_scout_phase(True)
    assert foundry.decide_scout_phase(False) == foundry.decide_scout_phase(False)
    assert foundry.decide_scout_phase(True) != foundry.decide_scout_phase(False)


def test_b12_equal_repr_for_equal_inputs():
    a = foundry.decide_scout_phase(True, lenses=("p", "q"))
    b = foundry.decide_scout_phase(True, lenses=("p", "q"))
    assert a == b
    assert repr(a) == repr(b)


# ==========================================================================
# Behavior 13 -- CLI SINGLE: exit 0, verdict SINGLE, count=0, no per-stage lines
# ==========================================================================
def test_b13_cli_single_exit0():
    rc, out = _cli(["scout-plan"])
    assert rc == 0, f"SINGLE returned {rc!r}, expected 0\n{out}"
    assert "verdict: SINGLE" in out, f"verdict line missing/wrong:\n{out}"
    assert "count=0" in out, f"count=0 figure missing:\n{out}"


def test_b13_cli_single_has_no_stage_lines():
    rc, out = _cli(["scout-plan"])
    assert rc == 0
    assert "pm_scout_a" not in out, f"SINGLE printed a per-stage line:\n{out}"
    assert "pm_scout_b" not in out


# ==========================================================================
# Behavior 14 -- CLI DUAL: exit 1, verdict DUAL, count 2, per-stage lines
# ==========================================================================
def test_b14_cli_dual_exit1():
    rc, out = _cli(["scout-plan", "--dual-pm-scouts"])
    assert rc == 1, f"DUAL returned {rc!r}, expected 1\n{out}"
    assert "verdict: DUAL" in out, f"verdict line missing/wrong:\n{out}"
    assert "count=2" in out, f"count=2 figure missing:\n{out}"


def test_b14_cli_dual_per_stage_lines_carry_name_and_lens():
    rc, out = _cli(["scout-plan", "--dual-pm-scouts"])
    assert rc == 1
    assert _stage_line_present(out, "pm_scout_a", "new-capability"), (
        f"pm_scout_a / new-capability not on one line:\n{out}"
    )
    assert _stage_line_present(out, "pm_scout_b", "hardening/DX"), (
        f"pm_scout_b / hardening/DX not on one line:\n{out}"
    )


# ==========================================================================
# Behavior 15 -- CLI --lens repeatable + OVERRIDES the default
# ==========================================================================
def test_b15_cli_lens_override_three():
    rc, out = _cli(["scout-plan", "--dual-pm-scouts",
                    "--lens", "alpha", "--lens", "beta", "--lens", "gamma"])
    assert rc == 1, f"expected DUAL exit 1\n{out}"
    assert "count=3" in out, f"count=3 figure missing:\n{out}"
    assert "verdict: DUAL" in out
    assert _stage_line_present(out, "pm_scout_a", "alpha")
    assert _stage_line_present(out, "pm_scout_b", "beta")
    assert _stage_line_present(out, "pm_scout_c", "gamma")
    # the default lenses are OVERRIDDEN, not appended
    assert "new-capability" not in out


def test_b15_cli_lens_ignored_without_dual_flag():
    # --lens without --dual-pm-scouts is still SINGLE (flag governs enablement)
    rc, out = _cli(["scout-plan", "--lens", "alpha"])
    assert rc == 0
    assert "verdict: SINGLE" in out


# ==========================================================================
# Behavior 16 -- the CLI writes NOTHING (empty temp cwd stays empty)
# ==========================================================================
def test_b16_cli_writes_nothing(tmp_path):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    prev = os.getcwd()
    os.chdir(cwd)
    try:
        before = sorted(x.name for x in cwd.iterdir())
        for args in (["scout-plan"],
                     ["scout-plan", "--dual-pm-scouts"],
                     ["scout-plan", "--dual-pm-scouts", "--lens", "a", "--lens", "b"]):
            _cli(args)
        after = sorted(x.name for x in cwd.iterdir())
    finally:
        os.chdir(prev)
    assert before == after == [], f"CLI wrote to the working dir: {before} -> {after}"


def test_b16_cli_dispatched_before_load_config():
    # no product --config / --file is required; the CLI runs standalone
    rc, _out = _cli(["scout-plan", "--dual-pm-scouts"])
    assert rc == 1, "scout-plan needed a --config (not dispatched before load_config)?"


# ==========================================================================
# --help -- lists scout-plan; prior subcommands intact; subparser args present
# ==========================================================================
def test_help_lists_scout_plan_and_prior_subcommands(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "scout-plan" in out, f"scout-plan missing from --help:\n{out}"
    for sub in ("restaffing-review", "cadence-review", "escalation-check",
                "product-gate", "gate-verdict", "gate-precheck", "role-model",
                "gate-scope", "lint-spec"):
        assert sub in out, f"prior subcommand {sub!r} missing from --help (regression)"


def test_scout_plan_subparser_help_ok(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["scout-plan", "--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "--dual-pm-scouts" in out, f"--dual-pm-scouts absent from subparser help:\n{out}"
    assert "--lens" in out, f"--lens absent from subparser help:\n{out}"


# ==========================================================================
# Acceptance-criteria / non-regression block (offline)
# ==========================================================================
def test_ac_public_surface_and_import_intact():
    assert callable(foundry.decide_scout_phase)
    assert callable(foundry.scout_plan_cli)
    assert dataclasses.is_dataclass(foundry.ScoutPhasePlan)
    lenses = foundry.PM_SCOUT_LENSES
    assert isinstance(lenses, tuple)
    assert lenses == ("new-capability", "hardening/DX"), (
        "PM_SCOUT_LENSES default should be the two documented lenses"
    )
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage",
               "run_execution_plan"):
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"
    # reused prior-bite cores remain present (no regression to the item-20/21/22 family)
    assert callable(foundry.decide_restaffing)
    assert callable(foundry.decide_cadence_review)
    assert callable(foundry.classify_escalation)
    assert callable(foundry.product_gate_precheck)
    assert dispatcher is not None


def test_ac_dormant_zero_call_site():
    """No orchestrator and no dispatcher-module reference references any new
    symbol by name (compiled name tables + string constants -- no source text
    read), nor names the `scout-plan` / `pm_scout` strings."""
    new = set(NEW_SYMBOLS)
    orchestrators = (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
                     foundry.run_continuous, foundry.run_execution_plan)
    for fn in orchestrators:
        refs = _co_names_deep(fn) & new
        assert refs == set(), f"foundry.{fn.__name__} references dormant symbol(s): {refs}"
        consts = _co_consts_deep(fn)
        for s in NEW_STRINGS:
            hits = [c for c in consts if s in c]
            assert hits == [], f"foundry.{fn.__name__} embeds dormant string {s!r}: {hits}"
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in NEW_SYMBOLS:
        assert sym not in dtext, f"dispatcher.py references dormant symbol {sym!r}"
    for s in NEW_STRINGS:
        assert s not in dtext, f"dispatcher.py names the dormant string {s!r}"


def test_ac_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_ac_new_symbols_ascii():
    """The NEW code is pure ASCII. Scoped to the new symbols via
    inspect.getsource -- NOT a whole-file scan (foundry.py carries pre-existing
    non-ASCII elsewhere -- the iter-67 trap)."""
    new_sources = [
        inspect.getsource(foundry.decide_scout_phase),
        inspect.getsource(foundry.ScoutPhasePlan),
        inspect.getsource(foundry.scout_plan_cli),
    ]
    for src in new_sources:
        offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert offenders == [], offenders[:5]


def test_ac_leak_clean_and_matcher_armed():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "this test file leaks a denylisted token"
    # matcher is ARMED (not inert): a RUNTIME-built home-path needle IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"


def test_ac_this_test_file_ascii():
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


@pytest.mark.skipif(not _GIT_OK, reason="not inside a git work tree")
def test_ac_control_path_byte_unchanged():
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py", "scripts/", ".gitignore"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, "dispatcher.py / scripts / .gitignore NOT byte-unchanged from HEAD"
