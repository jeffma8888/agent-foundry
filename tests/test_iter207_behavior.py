"""Black-box behaviour tests for iter 207 -- the four `Company*` FINDINGS-GATING
roll-ups stop hand-copying an AST-identical `exit_code` decision and share ONE
module-level function, assigned as `exit_code = property(FN)` in each of the four
class bodies.

TARGETS = (CompanyWeakTests, CompanyConstantAsserts, CompanySkippedTests,
CompanyTestQuality). This is a pure de-duplication: the observable exit status of
the `company-weak-tests` / `company-constant-asserts` / `company-skipped-tests` /
`company-test-quality` gates must not move, the four classes must stay frozen
4-field dataclasses with a 3-long MRO, and the property must remain DECLARED in
each class body (never inherited from the `CompanyRollupCounts` mixin, which is
what keeps iteration 153's pins green).

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-207 PM
spec's Expected Behaviors (1-8), the `tests/` conventions (esp.
tests/test_iter43_behavior.py -- the structural mirror for this family), and the
product's own OBSERVABLE behaviour, which was established by BUILDING the public
objects through their shipped pure factories and reading their public values /
class surface. The engineer's and reviewer's notes and `git diff` were NOT read.
The implementation's prose/source was not read for design; `foundry.py` is opened
here ONLY as `ast` INPUT, because Behavior 4 is itself a structural claim about
the shipped module that the spec directs be measured that way -- the value oracle
in Behavior 1 is derived from the spec's stated decision rules, never from the
implementation.

Every check drives the PUBLIC interface: the pure company factories
`foundry.summarize_company_{weak_tests,constant_asserts,skipped_tests,
test_quality}(...)` fed by the shipped per-product factories
`foundry.summarize_{weak_tests,constant_asserts,skipped_tests,test_quality}(...)`.
Fully offline and deterministic: no subprocess, no network, no filesystem writes,
no real product repo / state / git. The only file read is the tracked
`foundry.py` (relative path), for Behavior 4's `ast` census.
"""
import ast
import copy
import dataclasses
import pathlib
import pickle
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# the four roll-ups this iteration collapses (spec's TARGETS)
TARGET_NAMES = (
    "CompanyWeakTests",
    "CompanyConstantAsserts",
    "CompanySkippedTests",
    "CompanyTestQuality",
)

# the 4-field frozen shape every one of them must keep (Behavior 6)
EXPECTED_FIELDS = ["dispatch_path", "products", "disabled", "errors"]

# fixed exit-code <-> verdict mapping this family has carried since iter 43
_VERDICT_FOR_CODE = {0: "clean", 1: "ATTENTION", 2: "no enabled products"}

# relative repo-root-anchored path -- NEVER an absolute machine path (iter 205)
FOUNDRY_SRC = pathlib.Path(__file__).resolve().parents[1] / "foundry.py"

# sample payloads (relative literals only)
_FINDINGS = (("tests/t_a.py::test_nothing", "no assertion"),)
_PARSE_ERRS = (("tests/t_b.py", "SyntaxError: bad token"),)
_ERRORS = (("eps", "config load failed"),)


def _targets():
    return tuple(getattr(foundry, n) for n in TARGET_NAMES)


# --------------------------------------------------------------------------
# helpers -- build each family member through its OWN real public factory
# --------------------------------------------------------------------------
def _leaf_weak(name, findings=(), parse_errors=(), files=1):
    return foundry.summarize_weak_tests(
        product=name, files_scanned=files,
        findings=tuple(findings), parse_errors=tuple(parse_errors))


def _leaf_constant(name, findings=(), parse_errors=(), files=1):
    return foundry.summarize_constant_asserts(
        product=name, files_scanned=files,
        findings=tuple(findings), parse_errors=tuple(parse_errors))


def _leaf_skipped(name, findings=(), parse_errors=(), files=1):
    return foundry.summarize_skipped_tests(
        product=name, files_scanned=files,
        findings=tuple(findings), parse_errors=tuple(parse_errors))


def _leaf_quality(name, findings=(), parse_errors=(), files=1):
    """A TestQualitySummary carries its findings/parse-errors in its WEAK leg.

    This matters: `CompanyTestQuality.total_parse_errors` is NOT the same
    expression as its three siblings' (the composite summary exposes its own
    `total_parse_errors`), so the shared decision must be driven through the
    real composite -- not a look-alike -- for the collapse to be tested at all.
    """
    return foundry.summarize_test_quality(
        product=name,
        weak=_leaf_weak(name, findings=findings, parse_errors=parse_errors, files=files),
        constant=_leaf_constant(name, files=files),
        skipped=_leaf_skipped(name, files=files))


# class name -> (company factory, per-product leaf factory)
FAMILY = {
    "CompanyWeakTests": (
        lambda **kw: foundry.summarize_company_weak_tests(**kw), _leaf_weak),
    "CompanyConstantAsserts": (
        lambda **kw: foundry.summarize_company_constant_asserts(**kw), _leaf_constant),
    "CompanySkippedTests": (
        lambda **kw: foundry.summarize_company_skipped_tests(**kw), _leaf_skipped),
    "CompanyTestQuality": (
        lambda **kw: foundry.summarize_company_test_quality(**kw), _leaf_quality),
}


def _build(cname, *, n_products=1, findings=(), parse_errors=(), errors=(),
           disabled=(), extra_clean=0):
    """Build one real roll-up of class `cname` via its own public factory."""
    company, leaf = FAMILY[cname]
    products = []
    if n_products:
        products.append(leaf("alpha", findings=findings, parse_errors=parse_errors))
    for i in range(extra_clean):
        products.append(leaf("clean%d" % i))
    return company(dispatch_path="dispatch/fleet.json",
                   products=tuple(products), disabled=tuple(disabled),
                   errors=tuple(errors))


# The decision table, written straight off the SPEC's stated rules:
#   non-empty errors -> 1; total_findings>0 -> 1; total_parse_errors>0 -> 1;
#   n_products==0 and otherwise empty -> 2; else 0.
#   (label, kwargs for _build, expected exit_code)
DECISION_TABLE = (
    ("errors dominate",        dict(n_products=1, errors=_ERRORS), 1),
    ("errors, zero products",  dict(n_products=0, errors=_ERRORS), 1),
    ("findings gate",          dict(n_products=1, findings=_FINDINGS), 1),
    ("parse-errors gate",      dict(n_products=1, parse_errors=_PARSE_ERRS), 1),
    ("findings + parse-errors", dict(n_products=1, findings=_FINDINGS,
                                     parse_errors=_PARSE_ERRS), 1),
    ("flagged among clean",    dict(n_products=1, findings=_FINDINGS,
                                    extra_clean=2), 1),
    ("no enabled products",    dict(n_products=0, disabled=("gamma", "delta")), 2),
    ("clean",                  dict(n_products=1), 0),
    ("clean, several products", dict(n_products=1, extra_clean=2), 0),
)


# --------------------------------------------------------------------------
# Behavior 1 -- value preserved, all four classes, real constructors
# --------------------------------------------------------------------------
@pytest.mark.parametrize("cname", TARGET_NAMES)
def test_b1_decision_table_value_preserved_per_class(cname):
    for label, kw, expected in DECISION_TABLE:
        rollup = _build(cname, **kw)
        assert rollup.exit_code == expected, (
            "%s / %r: expected exit_code %d, got %d "
            "(errors=%d findings=%d parse_errors=%d n_products=%d)" % (
                cname, label, expected, rollup.exit_code, len(rollup.errors),
                rollup.total_findings, rollup.total_parse_errors,
                rollup.n_products))
        # the exit code and the human verdict must stay in lock-step
        assert rollup.verdict == _VERDICT_FOR_CODE[expected], (
            "%s / %r: verdict %r does not match exit_code %d"
            % (cname, label, rollup.verdict, expected))


def test_b1_all_four_agree_on_every_row():
    """Same input SHAPE -> same value from all four roll-ups."""
    for label, kw, expected in DECISION_TABLE:
        got = {c: _build(c, **kw).exit_code for c in TARGET_NAMES}
        assert set(got.values()) == {expected}, (
            "row %r must give %d from all four, got %r" % (label, expected, got))


def test_b1_composite_parse_error_operand_is_really_exercised():
    """CompanyTestQuality's `total_parse_errors` is its OWN expression.

    The three simple roll-ups count `len(p.parse_errors)` per product while the
    composite exposes `total_parse_errors`; this pins that the parse-error row
    above genuinely reaches a non-zero count on the composite, so row 4 is not
    silently passing on a zero.
    """
    r = _build("CompanyTestQuality", n_products=1, parse_errors=_PARSE_ERRS)
    assert r.total_parse_errors == 1 and r.total_findings == 0
    assert r.exit_code == 1
    for cname in ("CompanyWeakTests", "CompanyConstantAsserts", "CompanySkippedTests"):
        s = _build(cname, n_products=1, parse_errors=_PARSE_ERRS)
        assert s.total_parse_errors == 1 and s.total_findings == 0
        assert s.exit_code == 1


# --------------------------------------------------------------------------
# Behavior 2 -- ONE shared implementation, by identity
# --------------------------------------------------------------------------
def test_b2_all_four_share_one_exit_code_fget_object():
    for C in _targets():
        prop = C.__dict__["exit_code"]
        assert isinstance(prop, property), (
            "%s.exit_code must be a property, got %r" % (C.__name__, type(prop)))
    fgets = {C.__dict__["exit_code"].fget for C in _targets()}
    assert len(fgets) == 1, (
        "expected ONE shared fget across %r, found %d distinct: %r"
        % (list(TARGET_NAMES), len(fgets), sorted(f.__name__ for f in fgets)))


def test_b2_the_shared_fget_is_a_module_level_function():
    fget = _targets()[0].__dict__["exit_code"].fget
    assert isinstance(fget, types.FunctionType), (
        "the shared decision must be a plain function, got %r" % (type(fget),))
    assert getattr(foundry, fget.__name__, None) is fget, (
        "%r must be reachable at module level on foundry" % (fget.__name__,))
    # a de-duplication that loses the explanation is not an improvement:
    # property() inherits its doc from fget, so the class surface keeps one.
    for C in _targets():
        assert (C.__dict__["exit_code"].__doc__ or "").strip(), (
            "%s.exit_code lost its documentation" % C.__name__)


# --------------------------------------------------------------------------
# Behavior 3 -- still DECLARED in each class body (never inherited)
# --------------------------------------------------------------------------
def test_b3_exit_code_is_declared_in_each_class_body_not_inherited():
    for C in _targets():
        assert "exit_code" in vars(C), (
            "%s must DECLARE exit_code in its own class body" % C.__name__)
    assert "exit_code" not in vars(foundry.CompanyRollupCounts), (
        "exit_code must NOT move onto the CompanyRollupCounts mixin "
        "(iteration 153 pins that mixin's property set)")


# --------------------------------------------------------------------------
# Behavior 4 -- no `def exit_code` left in those bodies; ONE decision in module
# --------------------------------------------------------------------------
def _module_ast():
    return ast.parse(FOUNDRY_SRC.read_text(encoding="utf-8"))


def _body_signature(fn):
    """AST signature of a function body, docstring dropped and the RECEIVER
    parameter's name normalised.

    Without the normalisation a method (`self.errors`) and the module-level
    function it became (`rollup.errors`) never compare equal, so a duplicate
    census reports a clean zero whether or not the collapse happened.
    """
    body = list(fn.body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    args = list(fn.args.posonlyargs) + list(fn.args.args)
    if not args or not body:
        return None
    recv = args[0].arg
    mod = ast.parse(ast.unparse(ast.Module(body=body, type_ignores=[])))
    for node in ast.walk(mod):
        if isinstance(node, ast.Name) and node.id == recv:
            node.id = "__RECV__"
    return ast.dump(mod)


def test_b4_no_def_exit_code_remains_in_the_four_class_bodies():
    tree = _module_ast()
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in TARGET_NAMES:
            seen.add(node.name)
            offenders = [x.name for x in node.body
                         if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and x.name == "exit_code"]
            assert not offenders, (
                "%s still defines `def exit_code` in its class body" % node.name)
            # and it IS assigned there (the structural half of Behavior 3)
            assigned = [t.id for x in node.body if isinstance(x, ast.Assign)
                        for t in x.targets
                        if isinstance(t, ast.Name) and t.id == "exit_code"]
            assert assigned == ["exit_code"], (
                "%s must assign exit_code exactly once in its class body, got %r"
                % (node.name, assigned))
    assert seen == set(TARGET_NAMES), (
        "did not find all four target classes in foundry.py, only %r" % (sorted(seen),))


def test_b4_exactly_one_function_carries_the_shared_decision_body():
    fget = _targets()[0].__dict__["exit_code"].fget
    tree = _module_ast()
    defs = [n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == fget.__name__]
    assert len(defs) == 1, (
        "expected exactly one module-level `def %s`, found %d"
        % (fget.__name__, len(defs)))
    target_sig = _body_signature(defs[0])
    assert target_sig is not None
    carriers = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _body_signature(node) == target_sig:
                carriers.append(node.name)
    assert carriers == [fget.__name__], (
        "the findings-gate decision body must live in exactly ONE function; "
        "found it in %r" % (carriers,))


def test_b4_census_detects_a_hand_copy_two_sided():
    """The Behavior-4 census must be able to FIRE, or its clean result is a
    fail-open. Driven against a synthetic module holding the very hand-copy
    this iteration removed (two class bodies, identical decision, DIFFERENT
    receiver names) -- the census must group them and the class-body scan must
    see `def exit_code`.
    """
    synthetic = (
        "class A:\n"
        "    @property\n"
        "    def exit_code(self):\n"
        "        \"\"\"doc a.\"\"\"\n"
        "        if self.errors:\n"
        "            return 1\n"
        "        return 0\n"
        "\n"
        "class B:\n"
        "    @property\n"
        "    def exit_code(rollup):\n"
        "        \"\"\"doc b.\"\"\"\n"
        "        if rollup.errors:\n"
        "            return 1\n"
        "        return 0\n"
    )
    tree = ast.parse(synthetic)
    sigs = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            sigs.setdefault(_body_signature(node), []).append(node.name)
    assert list(sigs.values()) == [["exit_code", "exit_code"]], (
        "receiver-normalised census failed to group two hand-copies: %r" % (sigs,))
    # and the class-body scan (the other half of Behavior 4) sees them
    found = [c.name for c in tree.body if isinstance(c, ast.ClassDef)
             and any(isinstance(x, ast.FunctionDef) and x.name == "exit_code"
                     for x in c.body)]
    assert found == ["A", "B"], found


# --------------------------------------------------------------------------
# Behavior 5 -- MRO unchanged
# --------------------------------------------------------------------------
@pytest.mark.parametrize("cname", TARGET_NAMES)
def test_b5_mro_unchanged(cname):
    C = getattr(foundry, cname)
    assert len(C.__mro__) == 3, (
        "%s.__mro__ must stay 3 long, got %r"
        % (cname, [c.__name__ for c in C.__mro__]))
    assert [c.__name__ for c in C.__mro__] == [cname, "CompanyRollupCounts", "object"]


# --------------------------------------------------------------------------
# Behavior 6 -- dataclass shape unchanged
# --------------------------------------------------------------------------
@pytest.mark.parametrize("cname", TARGET_NAMES)
def test_b6_dataclass_shape_unchanged(cname):
    C = getattr(foundry, cname)
    assert dataclasses.is_dataclass(C)
    names = [f.name for f in dataclasses.fields(C)]
    assert names == EXPECTED_FIELDS, "%s fields drifted: %r" % (cname, names)
    assert "exit_code" not in names, (
        "%s: the unannotated `exit_code = property(...)` must NOT become a "
        "dataclass field" % cname)
    assert C.__dataclass_params__.frozen is True, "%s must stay frozen" % cname


# --------------------------------------------------------------------------
# Behavior 7 -- frozen / eq / pickle / deepcopy still hold
# --------------------------------------------------------------------------
@pytest.mark.parametrize("cname", TARGET_NAMES)
def test_b7_frozen_eq_pickle_deepcopy(cname):
    kw = dict(n_products=1, findings=_FINDINGS, disabled=("gamma",), errors=_ERRORS)
    x = _build(cname, **kw)
    y = _build(cname, **kw)
    assert x == y, "%s: equal-argument instances must compare equal" % cname
    for field in EXPECTED_FIELDS:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(x, field, getattr(x, field))
    assert pickle.loads(pickle.dumps(x)) == x, "%s must survive pickle" % cname
    assert copy.deepcopy(x) == x, "%s must survive deepcopy" % cname
    # the round-trips must preserve the gate itself, not just equality
    assert pickle.loads(pickle.dumps(x)).exit_code == x.exit_code == 1


# --------------------------------------------------------------------------
# Behavior 8 -- Behavior 2 is two-sided: it detects the hand-copy it removed
# --------------------------------------------------------------------------
def _twin_decision(rollup):
    if rollup.errors:
        return 1
    if rollup.total_findings or rollup.total_parse_errors:
        return 1
    return 2 if rollup.n_products == 0 else 0


def _make_defect_twins():
    """Four value-correct classes, each with its OWN separately-defined copy of
    an equivalent decision -- i.e. exactly the hand-copy iteration 207 removes.
    """
    twins = []
    for i in range(4):
        def _copy(rollup, _i=i):
            if rollup.errors:
                return 1
            if rollup.total_findings or rollup.total_parse_errors:
                return 1
            return 2 if rollup.n_products == 0 else 0
        twins.append(type("DefectTwin%d" % i, (), {"exit_code": property(_copy)}))
    return tuple(twins)


class _FakeRollup:
    """Minimal stand-in exposing only what the decision reads."""

    def __init__(self, errors=(), total_findings=0, total_parse_errors=0,
                 n_products=1):
        self.errors = tuple(errors)
        self.total_findings = total_findings
        self.total_parse_errors = total_parse_errors
        self.n_products = n_products


def _fake_for(kw):
    """Project a DECISION_TABLE row onto the four values the decision reads."""
    n = kw.get("n_products", 1) + kw.get("extra_clean", 0)
    return _FakeRollup(errors=kw.get("errors", ()),
                       total_findings=len(kw.get("findings", ())),
                       total_parse_errors=len(kw.get("parse_errors", ())),
                       n_products=n)


def test_b8_defect_twin_is_value_correct_but_fails_the_identity_check():
    twins = _make_defect_twins()
    # (a) VALUE-CORRECT: the twins reproduce every row of the decision table.
    for label, kw, expected in DECISION_TABLE:
        fake = _fake_for(kw)
        for T in twins:
            got = T.exit_code.fget(fake)
            assert got == expected, (
                "defect twin %s must still be value-correct on %r: "
                "expected %d, got %d" % (T.__name__, label, expected, got))
    # (b) IDENTITY-WRONG: Behavior 2's check must REJECT them.
    twin_fgets = {T.__dict__["exit_code"].fget for T in twins}
    assert len(twin_fgets) == 4, (
        "the defect twin must carry four distinct fgets to be a hand-copy")
    assert len(twin_fgets) != 1, (
        "Behavior 2's fget-identity check would not discriminate: a "
        "value-correct hand-copy must FAIL it")
    # and the same check PASSES on the shipped four -- both halves, one place.
    assert len({C.__dict__["exit_code"].fget for C in _targets()}) == 1


def test_b8_twin_oracle_agrees_with_the_spec_table():
    """The twin's decision is an independent re-statement of the spec rules."""
    for label, kw, expected in DECISION_TABLE:
        assert _twin_decision(_fake_for(kw)) == expected, (
            "independent oracle disagrees on %r" % (label,))


# --------------------------------------------------------------------------
# regression guards -- the modules must still import (Acceptance Criteria)
# --------------------------------------------------------------------------
def test_modules_still_import():
    assert hasattr(foundry, "main") and hasattr(dispatcher, "__file__")
    for name in TARGET_NAMES:
        assert hasattr(foundry, name)
