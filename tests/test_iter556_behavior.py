"""Black-box behaviour tests for iter 556 -- the five SCAN-family `Company*`
roll-ups (`CompanyWeakTests`, `CompanyConstantAsserts`, `CompanySkippedTests`,
`CompanyTestQuality`, `CompanyConfigLint`) stop hand-copying their `verdict`
property and share ONE module-level `foundry._company_scan_verdict(rollup)`,
assigned in each class body as `verdict = property(_company_scan_verdict)`
(re-landed verbatim from the infra-aborted iter 555).

ISOLATION CONTRACT (HONORED): written ONLY from the iter-556 PM spec's Expected
Behaviors (1-8), the conventions under `tests/` (esp. tests/test_iter207 and
tests/test_iter153, the structural mirrors for this family, and
tests/test_iter61 for the config-lint constructors), and the product's own
OBSERVABLE behaviour (public factories, public attributes, render()/to_dict()).
The engineer's / reviewer's notes and `git diff` were NOT read. `foundry.py` is
opened only as `ast` input, because Behaviors 2 and 3 are structural claims the
spec directs be measured that way.

Fully offline: no subprocess, no network, no git. The ledger check (Behavior 8)
reads the two TRACKED roadmap files by repo-relative path.
"""
import ast
import dataclasses
import pathlib
import re
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

FIVE = (
    "CompanyWeakTests",
    "CompanyConstantAsserts",
    "CompanySkippedTests",
    "CompanyTestQuality",
    "CompanyConfigLint",
)
FINDINGS_GATED = FIVE[:4]
OTHER_SIX = (
    "CompanyStatus",
    "CompanyChangelog",
    "CompanyHistory",
    "CompanyTiming",
    "CompanyEvents",
    "CompanyStops",
)
EXPECTED_FIELDS = ["dispatch_path", "products", "disabled", "errors"]
TOKENS = {0: "clean", 1: "ATTENTION", 2: "no enabled products"}
FOUNDRY_SRC = _ROOT / "foundry.py"


def _helper():
    fn = getattr(foundry, "_company_scan_verdict", None)
    assert isinstance(fn, types.FunctionType), (
        "foundry._company_scan_verdict must be a module-level function, got %r" % (fn,))
    return fn


# --------------------------------------------------------------------------
# builders -- every roll-up goes through its OWN public factory
# --------------------------------------------------------------------------
def _leaf_weak(name, findings=()):
    return foundry.summarize_weak_tests(
        product=name, files_scanned=1, findings=tuple(findings), parse_errors=())


def _leaf_constant(name, findings=()):
    return foundry.summarize_constant_asserts(
        product=name, files_scanned=1, findings=tuple(findings), parse_errors=())


def _leaf_skipped(name, findings=()):
    return foundry.summarize_skipped_tests(
        product=name, files_scanned=1, findings=tuple(findings), parse_errors=())


def _leaf_quality(name, findings=()):
    return foundry.summarize_test_quality(
        product=name, weak=_leaf_weak(name, findings),
        constant=_leaf_constant(name), skipped=_leaf_skipped(name))


def _leaf_lint(name, findings=()):
    lint_findings = tuple(
        foundry.ConfigFinding(field="f", level="error", detail=d) for _, d in findings)
    return foundry.ConfigLint(config_path="%s/config.json" % name, findings=lint_findings)


FAMILY = {
    "CompanyWeakTests": (foundry.summarize_company_weak_tests, _leaf_weak),
    "CompanyConstantAsserts": (foundry.summarize_company_constant_asserts, _leaf_constant),
    "CompanySkippedTests": (foundry.summarize_company_skipped_tests, _leaf_skipped),
    "CompanyTestQuality": (foundry.summarize_company_test_quality, _leaf_quality),
    "CompanyConfigLint": (foundry.summarize_company_config_lint, _leaf_lint),
}

_FINDING = (("tests/t_a.py::test_x", "flagged"),)


def _build(cname, scenario):
    """scenario in {clean, findings, errors, empty} -> a real roll-up."""
    company, leaf = FAMILY[cname]
    products, disabled, errors = (), (), ()
    if scenario == "clean":
        products = (leaf("alpha"),)
    elif scenario == "findings":
        products = (leaf("alpha", _FINDING), leaf("beta"))
    elif scenario == "errors":
        products = (leaf("alpha"),)
        errors = (("gamma", "config load failed"),)
    elif scenario == "empty":
        disabled = ("delta",)
    else:  # pragma: no cover
        raise AssertionError(scenario)
    return company(dispatch_path="dispatch/fleet.json", products=products,
                   disabled=disabled, errors=errors)


SCENARIOS = (("clean", 0), ("findings", 1), ("errors", 1), ("empty", 2))


def _module_ast():
    return ast.parse(FOUNDRY_SRC.read_text(encoding="utf-8"))


def _class_nodes(names):
    found = {}
    for node in ast.walk(_module_ast()):
        if isinstance(node, ast.ClassDef) and node.name in names:
            found[node.name] = node
    assert set(found) == set(names), "missing classes in foundry.py: %r" % (
        sorted(set(names) - set(found)),)
    return found


# --------------------------------------------------------------------------
# Behavior 1 -- the helper maps exit_code to the company token
# --------------------------------------------------------------------------
@pytest.mark.parametrize("code,token", sorted(TOKENS.items()))
def test_b1_helper_maps_exit_code_to_token(code, token):
    fn = _helper()
    assert fn(types.SimpleNamespace(exit_code=code)) == token


def test_b1_helper_is_module_level_and_reads_only_exit_code():
    fn = _helper()
    assert fn.__module__ == "foundry"
    assert fn.__qualname__ == "_company_scan_verdict"

    class OnlyExitCode:
        __slots__ = ()
        exit_code = 1

    assert fn(OnlyExitCode()) == "ATTENTION"


# --------------------------------------------------------------------------
# Behavior 2 -- identity in all five, no `def verdict` left in their bodies
# --------------------------------------------------------------------------
@pytest.mark.parametrize("cname", FIVE)
def test_b2_verdict_property_fget_is_the_shared_helper(cname):
    C = getattr(foundry, cname)
    prop = vars(C).get("verdict")
    assert isinstance(prop, property), "%s.verdict must be a property declared in its body" % cname
    assert prop.fget is _helper(), "%s.verdict.fget is %r" % (cname, prop.fget)


def test_b2_no_def_verdict_in_any_of_the_five_class_bodies():
    for name, node in _class_nodes(FIVE).items():
        offenders = [x.lineno for x in node.body
                     if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and x.name == "verdict"]
        assert offenders == [], "%s still has `def verdict`" % name


def test_b2_defect_twin_value_correct_but_fails_identity():
    """Two-sided proof: an identical-body local copy returns the right token
    yet must FAIL the `fget is` check the shipped five pass."""
    def verdict(self):
        return {0: "clean", 1: "ATTENTION"}.get(self.exit_code, "no enabled products")

    Twin = type("DefectTwin", (), {"exit_code": 1, "verdict": property(verdict)})
    assert Twin().verdict == "ATTENTION" == _helper()(Twin())
    assert vars(Twin)["verdict"].fget is not _helper()
    # and the census side: a synthetic class with `def verdict` is detected
    tree = ast.parse("class X:\n    @property\n    def verdict(self):\n        return 'clean'\n")
    hits = [x.name for c in tree.body for x in c.body
            if isinstance(x, ast.FunctionDef) and x.name == "verdict"]
    assert hits == ["verdict"]
    assert all(vars(getattr(foundry, c))["verdict"].fget is _helper() for c in FIVE)


# --------------------------------------------------------------------------
# Behavior 3 -- not a dataclass field; plain Assign, not AnnAssign
# --------------------------------------------------------------------------
@pytest.mark.parametrize("cname", FIVE)
def test_b3_verdict_is_not_a_dataclass_field(cname):
    C = getattr(foundry, cname)
    assert [f.name for f in dataclasses.fields(C)] == EXPECTED_FIELDS


def test_b3_class_body_assignment_is_unannotated():
    for name, node in _class_nodes(FIVE).items():
        plain = [x for x in node.body if isinstance(x, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "verdict" for t in x.targets)]
        annotated = [x for x in node.body if isinstance(x, ast.AnnAssign)
                     and isinstance(x.target, ast.Name) and x.target.id == "verdict"]
        assert len(plain) == 1, "%s: expected one `verdict = ...` Assign, got %d" % (name, len(plain))
        assert annotated == [], "%s: verdict must not be an AnnAssign" % name
        value = plain[0].value
        assert isinstance(value, ast.Call) and ast.unparse(value) == \
            "property(_company_scan_verdict)", ast.unparse(value)


# --------------------------------------------------------------------------
# Behavior 4 -- observable output byte-identical for all codes
# --------------------------------------------------------------------------
@pytest.mark.parametrize("cname", FIVE)
@pytest.mark.parametrize("scenario,code", SCENARIOS)
def test_b4_verdict_render_and_dict_agree_with_exit_code(cname, scenario, code):
    r = _build(cname, scenario)
    token = TOKENS[code]
    assert r.exit_code == code, "%s/%s exit_code %r" % (cname, scenario, r.exit_code)
    assert r.verdict == token
    last = [ln for ln in r.render().splitlines() if ln.strip()][-1]
    assert last.endswith(token), "%s/%s last render line %r" % (cname, scenario, last)
    assert last == "verdict: %s" % token
    assert r.to_dict()["verdict"] == token


# --------------------------------------------------------------------------
# Behavior 5 -- the six others untouched; exit_code properties unchanged
# --------------------------------------------------------------------------
@pytest.mark.parametrize("cname", OTHER_SIX)
def test_b5_other_rollups_do_not_use_the_scan_helper(cname):
    C = getattr(foundry, cname)
    prop = getattr(C, "verdict", None)
    assert isinstance(prop, property), "%s.verdict should be a property" % cname
    assert prop.fget is not _helper(), "%s must not use _company_scan_verdict" % cname


def test_b5_exit_code_properties_unchanged():
    shared = foundry._company_findings_exit_code
    for cname in FINDINGS_GATED:
        assert vars(getattr(foundry, cname))["exit_code"].fget is shared, cname
    lint_prop = vars(foundry.CompanyConfigLint)["exit_code"]
    assert isinstance(lint_prop, property)
    assert lint_prop.fget is not shared
    assert lint_prop.fget is not _helper()
    # errors-gated: a WARN-only product stays clean, an ERROR-level one is ATTENTION
    warn = foundry.ConfigLint(config_path="a/config.json", findings=(
        foundry.ConfigFinding(field="f", level="warn", detail="d"),))
    r = foundry.summarize_company_config_lint(
        dispatch_path="d.json", products=(warn,), disabled=(), errors=())
    assert (r.exit_code, r.verdict) == (0, "clean")


# --------------------------------------------------------------------------
# Behavior 6 -- mixin surface and MRO unchanged
# --------------------------------------------------------------------------
def test_b6_mixin_keeps_exactly_three_properties():
    props = sorted(n for n, v in vars(foundry.CompanyRollupCounts).items()
                   if isinstance(v, property))
    assert props == ["n_disabled", "n_errors", "n_products"]


@pytest.mark.parametrize("cname", FIVE)
def test_b6_mro_length_three(cname):
    C = getattr(foundry, cname)
    assert [c.__name__ for c in C.__mro__] == [cname, "CompanyRollupCounts", "object"]


# --------------------------------------------------------------------------
# Behavior 7 -- documentation kept
# --------------------------------------------------------------------------
def test_b7_helper_doc_names_tokens_and_the_company_note():
    doc = _helper().__doc__ or ""
    for tok in ('"clean"', '"ATTENTION"', '"no enabled products"'):
        assert tok in doc, "helper doc lacks %s" % tok
    assert "COMPANY" in doc
    assert "ALWAYS-SKIPPED TESTS FOUND" in doc


@pytest.mark.parametrize("cname", FIVE)
def test_b7_each_class_verdict_has_a_doc(cname):
    assert (getattr(foundry, cname).verdict.__doc__ or "").strip()


# --------------------------------------------------------------------------
# Behavior 8 -- ledger rows for 556, no phantom 555 row
# --------------------------------------------------------------------------
def _ledger():
    idx = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    arc = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text(encoding="utf-8")
    return idx, arc


def test_b8_ledger_has_556_rows():
    idx, arc = _ledger()
    assert foundry.roadmap_ledger_gaps(idx, arc, (556,)) == []
    assert re.search(r"(?m)^- iter 556 ", idx), "PLATFORM_ROADMAP.md lacks `- iter 556 ` row"
    assert re.search(r"(?m)^- \*\*iter 556 ", arc), "archive lacks `- **iter 556 ` bullet"


def test_b8_no_phantom_555_row():
    idx, arc = _ledger()
    pat = re.compile(r"(?m)^- (\*\*)?iter 555 ")
    assert pat.findall(idx) == [], "phantom iter 555 row in PLATFORM_ROADMAP.md"
    assert pat.findall(arc) == [], "phantom iter 555 row in PLATFORM_ROADMAP_ARCHIVE.md"
    # the oracle itself can fire
    assert foundry.roadmap_ledger_gaps("", "", (556,)) == [556]
