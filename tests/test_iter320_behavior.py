"""Black-box behaviour tests for iter 320 -- the `dual_pm_scouts` config DEFAULT flip.

The iteration's product is a one-line correctness fix on the foundry's own
ADOPTION surface: `ProductConfig.dual_pm_scouts` used to default to `False`
("dormant; wired in a later bite") long after the two-scout PM pre-phase
shipped, so a product scaffolded by `foundry new-product` -- which never emits
the key -- silently started on the superseded single-scout leg. After this
iteration the DECLARED default is `True`, an explicit `false` is still a working
opt-OUT, and the two stale claims (the field's inline comment, the spec doc's
"defaults off") are retired.

ISOLATION CONTRACT (honored): every assertion here was designed from the PM
spec's Expected Behaviors 1-8 (`pm.md`) and from the product's own OBSERVABLE
surface, exercised by RUNNING it. The engineer's notes, the reviewer's notes and
`git diff` were NOT read, and the implementation LOGIC of foundry.py was NOT
read. Behaviours 1-7 drive the PUBLIC interface only -- `foundry.ProductConfig`,
`dataclasses.fields`, `foundry.load_config`, `foundry.ProductConfig.resolve`,
`foundry.product_config_template`, `foundry.decide_scout_phase`. Behaviour 8 is
the MECHANICAL string scan the spec's acceptance criteria literally require: a
single-line token census of the field DECLARATION and a literal-absence scan of
one shipped doc, never a read of any implementation logic.

Fully offline and deterministic: no subprocess, no git, no network, no agent
run. Every filesystem write lands under pytest's `tmp_path`; the only reads
outside it are of two shipped, committed text assets located at RUNTIME from
`foundry.__file__` (never a source-literal absolute path).
"""
import dataclasses
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402


# --------------------------------------------------------------------------
# runtime-built paths (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
FOUNDRY_PY = pathlib.Path(foundry.__file__).resolve()
DUAL_SPEC_MD = _ROOT / "docs" / "DUAL_PM_SCOUT_SPEC.md"

FIELD = "dual_pm_scouts"
DECL_PREFIX = f"{FIELD}: bool ="


def _fields():
    return {f.name: f for f in dataclasses.fields(foundry.ProductConfig)}


def _write_cfg(tmp_path, **over):
    """Mirror the config-writing helper the other behaviour modules use. The
    TEMP work_root keeps load_config's mkdir(work_root/state) inside tmp_path so
    the real checkout is never touched."""
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
# Behavior 1 -- a FRESH instance defaults to dual (identity against the
# singleton True, not a truthiness check)
# ==========================================================================
def test_b01_fresh_instance_defaults_to_dual():
    cfg = foundry.ProductConfig(name="x", repo="/tmp/x", allowed_push_repo="x")
    assert cfg.dual_pm_scouts is True


# ==========================================================================
# Behavior 2 -- the DECLARED dataclass default is the flipped value, i.e. the
# flip lives in the field declaration and NOT in __post_init__ / resolve() /
# a default_factory
# ==========================================================================
def test_b02_declared_dataclass_default_is_true():
    fld = _fields()[FIELD]
    assert fld.default is True


def test_b02_default_is_a_plain_value_not_a_factory():
    """A default_factory would satisfy Behavior 1 while hiding the value from
    `dataclasses.fields(...).default` (which would read MISSING) -- the spec
    pins the declaration, so the negative twin is asserted too."""
    fld = _fields()[FIELD]
    assert fld.default_factory is dataclasses.MISSING


def test_b02_flip_is_not_a_post_init_or_resolve_coercion():
    """The other way to make Behavior 1 pass without moving the declaration is
    to coerce the value after construction. If anything did that, an explicit
    False would not survive construction or resolve()."""
    cfg = foundry.ProductConfig(
        name="x", repo="/tmp/x", allowed_push_repo="x", dual_pm_scouts=False
    )
    assert cfg.dual_pm_scouts is False
    assert cfg.resolve().dual_pm_scouts is False


# ==========================================================================
# Behavior 3 -- load_config on a config JSON that OMITS the key yields True
# (this is the whole bug: an old/scaffolded config inherits the shipped leg)
# ==========================================================================
def test_b03_load_config_omitting_the_key_yields_true(tmp_path):
    path = _write_cfg(tmp_path)
    assert FIELD not in json.loads(path.read_text())  # the precondition itself
    cfg = foundry.load_config(str(path))
    assert cfg.dual_pm_scouts is True


# ==========================================================================
# Behavior 4 -- the opt-OUT still works
# ==========================================================================
def test_b04_explicit_false_is_a_working_opt_out(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, dual_pm_scouts=False)))
    assert cfg.dual_pm_scouts is False


# ==========================================================================
# Behavior 5 -- the explicit opt-IN is unchanged
# ==========================================================================
def test_b05_explicit_true_is_unchanged(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, dual_pm_scouts=True)))
    assert cfg.dual_pm_scouts is True


# ==========================================================================
# Behavior 6 -- the scaffold on-ramp is fixed END TO END without the template
# ever naming the key
# ==========================================================================
def test_b06_scaffold_template_stays_silent_about_the_flag():
    template = foundry.product_config_template("demo", "/x/demo")
    assert FIELD not in template


def test_b06_scaffolded_config_loads_with_dual_enabled(tmp_path):
    """A config file holding EXACTLY the scaffold template (only work_root
    redirected under tmp_path so the loader's mkdir stays in the sandbox) must
    load with the flag on -- silence in the template, shipped leg at runtime."""
    template = dict(foundry.product_config_template("demo", "/x/demo"))
    template["work_root"] = str(tmp_path / "work")
    path = tmp_path / "config.json"
    path.write_text(json.dumps(template, indent=2))
    assert FIELD not in json.loads(path.read_text())
    cfg = foundry.load_config(str(path))
    assert cfg.dual_pm_scouts is True


# ==========================================================================
# Behavior 7 -- the DECISION function is untouched; only the default moved
# ==========================================================================
def test_b07_decide_scout_phase_still_honours_a_false_flag():
    plan = foundry.decide_scout_phase(False)
    assert plan.enabled is False
    assert plan.count == 0
    assert plan.stages == ()


def test_b07_decide_scout_phase_still_plans_two_scouts_when_true():
    plan = foundry.decide_scout_phase(True)
    assert plan.enabled is True
    assert plan.count == 2
    assert len(plan.stages) == 2


def test_b07_falsy_flags_still_disable_the_phase():
    """An engineer who "fixed" the default by coercing falsy inputs to enabled
    fails here: the flip belongs to the DEFAULT, not to the decision."""
    for falsy in (False, 0, "", None, ()):
        plan = foundry.decide_scout_phase(falsy)
        assert plan.enabled is False, falsy
        assert plan.count == 0, falsy


# ==========================================================================
# Behavior 8 -- the two stale claims are retired, checked MECHANICALLY.
# Only the RETIRED claims are pinned (no new wording), so a later rewording of
# either comment or doc cannot red this suite.
# ==========================================================================
def test_b08a_field_declaration_line_says_true_and_not_dormant():
    decls = [
        line
        for line in FOUNDRY_PY.read_text().splitlines()
        if line.strip().startswith(DECL_PREFIX)
    ]
    assert len(decls) == 1, f"expected exactly one `{DECL_PREFIX}` line, got {len(decls)}"
    decl = decls[0]
    assert "True" in decl
    assert "dormant" not in decl.lower()


def test_b08a_declaration_stays_a_single_short_trailing_comment():
    """The binding design constraint: one trailing `#` comment, <= 100 chars,
    no comment block hoisted above the field."""
    decl = next(
        line
        for line in FOUNDRY_PY.read_text().splitlines()
        if line.strip().startswith(DECL_PREFIX)
    )
    assert len(decl) <= 100
    assert decl.count("#") == 1


def test_b08b_spec_doc_no_longer_claims_the_flag_defaults_off():
    assert DUAL_SPEC_MD.is_file()
    assert "defaults off" not in DUAL_SPEC_MD.read_text().lower()
