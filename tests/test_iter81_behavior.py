"""Black-box behaviour tests for iter 81 -- dual-PM-scout feature (bite 2 of ~3):
the ADDITIVE-DORMANT PREREQUISITES. Two purely additive-dormant pieces, per
docs/DUAL_PM_SCOUT_SPEC.md:
  (1) a backward-compatible ProductConfig field `dual_pm_scouts: bool = False`
      (the opt-in flag a product will set in its config.json), and
  (2) a product-agnostic role file `roles/pm_scout.md` (the scout prompt the
      eventual wiring bite will run before the PM lead).
BOTH are dormant this iteration: NO pipeline orchestrator reads the field, and
the role-file name `pm_scout.md` is referenced NOWHERE in foundry.py /
dispatcher.py, so the disabled/default path is byte-identical and resume
semantics are preserved. Wiring (the two-scout pre-stage + the roles/pm.md
triage edit) is the operator-gated bite 3, out of scope here.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-15) and the product's own OBSERVABLE surface only. The engineer's and
reviewer's notes and `git diff` were NOT read, and the implementation LOGIC of
foundry.py was NOT read to design these tests. Every field/config behaviour drives
the PUBLIC interface: `foundry.ProductConfig`, `foundry.load_config`, and
`dataclasses.fields`. Dormancy of the field uses only public RUNTIME
introspection -- the compiled function name tables of the five orchestrators
(`__code__.co_names` recursed via `_co_names_deep`). The role-file behaviours read
the shipped asset `roles/pm_scout.md` (a permitted product artifact) and run the
committed leak-guard via its public API. The only source-text touches are the
MECHANICAL string-absence byte-scans of foundry.py + dispatcher.py that the
dormancy acceptance criteria (behaviors 9 and 15) literally require -- a
leak/dormancy hygiene scan for a literal token, never a read of the
implementation's logic (the string "dual_pm_scouts" and the "pm_scout" prefix both
legitimately exist in foundry.py from the iter-80 planner, so a whole-file grep
proves nothing about the field/asset dormancy; the proof scopes the field to the
five orchestrators' compiled names and asserts the exact `.md`-suffixed file-name
string is absent). Fully offline and deterministic: the only subprocess calls are
the fresh-import probe and the control-path byte-unchanged git `--quiet` probe;
no network, no agent-run, no git mutation.
"""
import dataclasses
import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
FOUNDRY_PY = pathlib.Path(foundry.__file__).resolve()
DISPATCHER_PY = _ROOT / "dispatcher.py"
PM_SCOUT_MD = _ROOT / "roles" / "pm_scout.md"
THIS_TEST = pathlib.Path(__file__).resolve()

# The exact role-file name string whose ABSENCE proves the asset is dormant.
# NB: the bare "pm_scout" prefix legitimately appears in foundry.py (iter-80's
# runtime stage-name generation f"pm_scout_{...}"), so the dormancy assertion is
# on the .md-suffixed file name, NOT the prefix.
ROLE_FILE_NAME = "pm_scout.md"

# The config attribute this iteration adds -- must be dormant across the five
# pipeline orchestrators. The bare string exists elsewhere in foundry.py (the
# iter-80 planner param / argparse dest), so the proof scopes to compiled names.
FIELD = "dual_pm_scouts"

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
    spec = importlib.util.spec_from_file_location("leak_guard_iter81_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_cfg(tmp_path, **over):
    """Mirror the config-writing helper used by the other test modules. Sets a
    TEMP work_root under the pytest tmp dir so load_config's mkdir(work_root/
    state) writes only under tmp and never pollutes the real repo (spec B3)."""
    data = {
        "name": "demo",
        "repo": "{FOUNDRY}/products/demo/repo",
        "allowed_push_repo": "demo",
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


# ==========================================================================
# Behavior 1 -- default off; the three positional-required fields still work
# ==========================================================================
def test_b01_default_off_on_fresh_instance():
    cfg = foundry.ProductConfig(name="x", repo="/tmp/x", allowed_push_repo="x")
    assert hasattr(cfg, "dual_pm_scouts")
    assert cfg.dual_pm_scouts is False
    # the existing positional-required fields are unchanged / still bind
    assert cfg.name == "x"
    assert cfg.repo == "/tmp/x"
    assert cfg.allowed_push_repo == "x"


# ==========================================================================
# Behavior 2 -- declared dataclass field; runtime value is a bool
# ==========================================================================
def test_b02_declared_field_and_isinstance_bool():
    field_names = {f.name for f in dataclasses.fields(foundry.ProductConfig)}
    assert "dual_pm_scouts" in field_names
    cfg = foundry.ProductConfig(name="x", repo="/tmp/x", allowed_push_repo="x")
    # annotations stringize in this module -> assert the runtime VALUE is a bool,
    # never compare field.type (a str 'bool') to the bool type object.
    assert isinstance(cfg.dual_pm_scouts, bool)


def test_b02_field_is_last_and_has_a_default():
    # a defaulted bool -- constructible with ONLY the three required positionals
    # (proves it carries a default and sits after the required fields).
    cfg = foundry.ProductConfig(name="x", repo="/tmp/x", allowed_push_repo="x")
    assert cfg.dual_pm_scouts is False
    fld = {f.name: f for f in dataclasses.fields(foundry.ProductConfig)}["dual_pm_scouts"]
    assert fld.default is False


# ==========================================================================
# Behavior 3 -- load_config OMITting the key yields False (old configs load)
# ==========================================================================
def test_b03_load_config_omit_defaults_false(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    assert cfg.dual_pm_scouts is False


# ==========================================================================
# Behavior 4 -- load_config with "dual_pm_scouts": true yields True (opt-in)
# ==========================================================================
def test_b04_load_config_true_opts_in(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, dual_pm_scouts=True)))
    assert cfg.dual_pm_scouts is True


# ==========================================================================
# Behavior 5 -- load_config with "dual_pm_scouts": false yields False
# ==========================================================================
def test_b05_load_config_false_stays_false(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, dual_pm_scouts=False)))
    assert cfg.dual_pm_scouts is False


# ==========================================================================
# Behavior 6 -- regression: the known-field filter is intact
# ==========================================================================
def test_b06_unknown_key_filtered_no_error(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, bogus_unknown_key=1)))
    assert not hasattr(cfg, "bogus_unknown_key"), "unknown key leaked onto the config"
    # known fields still set correctly
    assert cfg.name == "demo"
    assert cfg.dual_pm_scouts is False


def test_b06_unknown_key_with_optin_together(tmp_path):
    # an unknown key coexisting with a real opt-in still filters + opts in
    cfg = foundry.load_config(
        str(_write_cfg(tmp_path, dual_pm_scouts=True, bogus_unknown_key="junk")))
    assert cfg.dual_pm_scouts is True
    assert not hasattr(cfg, "bogus_unknown_key")


# ==========================================================================
# Behavior 7 -- resolve() does NOT alter dual_pm_scouts (plain bool, no path)
# ==========================================================================
def test_b07_resolve_preserves_the_bool():
    cfg = foundry.ProductConfig(
        name="x", repo="{FOUNDRY}/products/x/repo",
        allowed_push_repo="x", dual_pm_scouts=True)
    resolved = cfg.resolve()
    # resolve() may return self or a new instance -- check the returned object
    target = resolved if resolved is not None else cfg
    assert target.dual_pm_scouts is True, "resolve() altered the dormant bool"


def test_b07_resolve_preserves_false_too():
    cfg = foundry.ProductConfig(
        name="x", repo="{FOUNDRY}/products/x/repo", allowed_push_repo="x")
    resolved = cfg.resolve()
    target = resolved if resolved is not None else cfg
    assert target.dual_pm_scouts is False


# ==========================================================================
# Behavior 8 -- field dormancy: NO orchestrator references dual_pm_scouts
# ==========================================================================
def test_b08_field_dormant_across_five_orchestrators():
    orchestrators = (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
                     foundry.run_continuous, foundry.run_execution_plan)
    for fn in orchestrators:
        names = _co_names_deep(fn)
        assert FIELD not in names, (
            f"foundry.{fn.__name__} references dormant config attr {FIELD!r} "
            f"(should be wired only in bite 3)"
        )


# ==========================================================================
# Behavior 9 -- dispatcher.py source does not contain dual_pm_scouts
# ==========================================================================
def test_b09_dispatcher_source_has_no_field():
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    assert dtext.count(FIELD) == 0, (
        f"dispatcher.py references {FIELD!r} -- its config handling changed"
    )


# ==========================================================================
# Behavior 10 -- roles/pm_scout.md exists and is a non-empty regular file
# ==========================================================================
def test_b10_role_file_exists_nonempty():
    assert PM_SCOUT_MD.exists(), f"{PM_SCOUT_MD} does not exist"
    assert PM_SCOUT_MD.is_file(), f"{PM_SCOUT_MD} is not a regular file"
    assert PM_SCOUT_MD.stat().st_size > 0, "roles/pm_scout.md is empty"


# ==========================================================================
# Behavior 11 -- roles/pm_scout.md is pure ASCII (public-safety / no-leak)
# ==========================================================================
def test_b11_role_file_pure_ascii():
    raw = PM_SCOUT_MD.read_bytes()
    offenders = [(i, b) for i, b in enumerate(raw) if b >= 128]
    assert offenders == [], f"non-ASCII byte(s) in roles/pm_scout.md: {offenders[:5]}"


# ==========================================================================
# Behavior 12 -- roles/pm_scout.md passes the committed leak-guard (0 findings)
# ==========================================================================
def test_b12_role_file_leak_clean():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    findings = mod.scan_text(PM_SCOUT_MD.read_text(encoding="utf-8"), denylist)
    assert findings == (), f"roles/pm_scout.md leaks denylisted token(s): {findings}"


def test_b12_leak_matcher_is_armed():
    # guard against a false-clean: the matcher must flag a RUNTIME-built home path
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"


# ==========================================================================
# Behavior 13 -- content declares the scout PROPOSES and decides nothing
# ==========================================================================
def test_b13_role_file_proposes_not_decides():
    text = PM_SCOUT_MD.read_text(encoding="utf-8")
    low = text.lower()
    for lit in ("propose", "candidate", "assigned"):
        assert lit in low, f"roles/pm_scout.md missing case-insensitive literal {lit!r}"
    assert "decides nothing" in text, "roles/pm_scout.md missing exact phrase 'decides nothing'"


# ==========================================================================
# Behavior 14 -- content names the candidate count and BOTH lenses
# ==========================================================================
def test_b14_role_file_names_count_and_both_lenses():
    text = PM_SCOUT_MD.read_text(encoding="utf-8")
    for lit in ("2-3", "new-capability", "hardening/DX"):
        assert lit in text, f"roles/pm_scout.md missing literal {lit!r}"


# ==========================================================================
# Behavior 15 -- role-file dormancy: pm_scout.md referenced NOWHERE in code
# ==========================================================================
def test_b15_role_file_name_absent_from_foundry():
    ftext = FOUNDRY_PY.read_text(encoding="utf-8")
    # the exact .md-suffixed file-name string, NOT the bare pm_scout prefix
    # (the prefix legitimately exists from iter-80's runtime stage naming).
    assert ftext.count(ROLE_FILE_NAME) == 0, (
        f"foundry.py references the role-file name {ROLE_FILE_NAME!r} -- not dormant"
    )


def test_b15_role_file_name_absent_from_dispatcher():
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    assert dtext.count(ROLE_FILE_NAME) == 0, (
        f"dispatcher.py references the role-file name {ROLE_FILE_NAME!r} -- not dormant"
    )


# ==========================================================================
# Acceptance-criteria / non-regression block (offline)
# ==========================================================================
def test_ac_public_surface_and_prior_features_intact():
    # the pipeline entrypoints remain callable (no regression from the field add)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage",
               "run_execution_plan", "load_config"):
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable"
    assert dataclasses.is_dataclass(foundry.ProductConfig)
    # the iter-80 planner (bite 1) and prior dormant cores are still present
    assert callable(foundry.decide_scout_phase)
    assert dataclasses.is_dataclass(foundry.ScoutPhasePlan)
    assert foundry.PM_SCOUT_LENSES == ("new-capability", "hardening/DX")
    assert callable(foundry.decide_restaffing)
    assert callable(foundry.decide_cadence_review)
    assert dispatcher is not None


def test_ac_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


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
