"""Black-box behaviour tests for iter 59 -- `foundry company-test-quality`: the
read-only, offline company-wide roll-up of the per-product iter-58 `test-quality`
COMPOSITE (#25) over the DISPATCH config -- the 8th `company-*` family member and
the QUALITY-axis capstone of the company family. It folds every ENABLED dispatch
team's composite scan of all THREE offline "validates-nothing" antipatterns
(assertion-free / constant-assert / always-skipped) into ONE company verdict + a
per-CATEGORY + per-TEAM triage breakdown + ONE scriptable 0/1/2 exit code + ONE
JSON doc, composed on top of a NEW `gather_test_quality` seam + the frozen
per-product `TestQualitySummary` (iter 58). Purely additive in foundry.py:

  * a NEW module-level seam `gather_test_quality(cfg, files=None) ->
    TestQualitySummary` (composes the shipped `gather_weak_tests` /
    `gather_constant_asserts` / `gather_skipped_tests` via `summarize_test_quality`),
  * a FROZEN dataclass `CompanyTestQuality(dispatch_path, products, disabled,
    errors)` with n_* count props + files_scanned/total_weak_findings/
    total_constant_findings/total_skipped_findings/total_findings/
    total_parse_errors sums + n_flagged + findings-GATING exit_code/verdict +
    render() + to_dict(),
  * a PURE keyword-only `summarize_company_test_quality(*, dispatch_path,
    products, disabled, errors) -> CompanyTestQuality`,
  * a thin resilient `company_test_quality_cli(dispatch_path, as_json=False)
    -> int` wired to a new argparse subcommand `company-test-quality` (NO
    --limit, NO --files), driving `parse_dispatch_work_items` + `load_config`
    + `gather_test_quality` by BARE name.

OVERLAP (a first-class correctness item, the load-bearing iter-56/57/58 lesson at
the COMPANY-composite layer -- re-derived from OBSERVED behaviour, NOT copied):
`constant-asserts` is DISJOINT from `weak-tests` by the detectors' construction
(a constant assert CARRIES an assert node, so an assertion-free scan can never
also flag it), BUT an ALWAYS-SKIPPED test CAN also be assertion-free AND can carry
a constant assert -- so a skipped finding CAN OVERLAP the weak/constant lenses.
Therefore the company `total_findings` (and its per-category components) is a
per-CATEGORY triage total in which a test flagged by two lenses counts once in
EACH category, INHERITING #25's category-weighting -- intentionally NOT a
de-duplicated distinct-test count. Behavior 5 proves this from observed behaviour
(a synthetic test flagged by BOTH the weak and skipped lenses yields
total_findings==2), NEVER by asserting any disjointness.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-59 PM
spec's Expected Behaviors (1-9), the product README/roadmap, the tests/
conventions (esp. tests/test_iter57_behavior.py -- the structural mirror
company-skipped-tests -- and tests/test_iter58_behavior.py -- the per-product
test-quality composite foundation), and the product's OWN OBSERVABLE behaviour
(building the public objects and RUNNING them / --help / public RUNTIME
introspection). The implementation SOURCE (foundry.py / dispatcher.py source
text), the engineer's & reviewer's notes, and `git diff` were NOT read. Every
assertion is DERIVED from the spec's pinned substrings + observed output, never
copied from implementation phrasing. Every check drives the PUBLIC interface
against tiny JSON files in tmp_path, monkeypatching foundry.load_config /
foundry.gather_test_quality. The real product repos / state / network are NEVER
touched (except the read-only import, --help probes, an exit-code-only
`git diff --quiet` byte-unchanged check that reads NO diff text, and a self-leak
scan). Fully offline & deterministic.
"""
import dataclasses
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402

_LEAK_GUARD = _ROOT / "scripts" / "leak_guard.py"
_DENYLIST = _ROOT / "scripts" / "leak_denylist.txt"

# fixed COMPANY exit-code <-> verdict mapping asserted throughout (Behavior 3);
# note these are the COMPANY tokens, NOT the per-product TestQualitySummary tokens
# ("clean" / "QUALITY ISSUES FOUND" / "nothing to scan").
_VERDICT_FOR_CODE = {0: "clean", 1: "ATTENTION", 2: "no enabled products"}

# the genuinely-NEW iter-59 symbols
NEW_SYMBOLS = ("gather_test_quality", "CompanyTestQuality",
               "summarize_company_test_quality", "company_test_quality_cli")
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")
SUBCMD = "company-test-quality"


# --------------------------------------------------------------------------
# helpers  (mirror tests/test_iter57_behavior.py + tests/test_iter58_behavior.py)
# --------------------------------------------------------------------------
def _W(**over):
    """Build a frozen sub-`WeakTestSummary` (assertion-free lens)."""
    base = {"product": "p", "files_scanned": 0, "findings": (), "parse_errors": ()}
    base.update(over)
    return foundry.summarize_weak_tests(**base)


def _C(**over):
    """Build a frozen sub-`ConstantAssertSummary` (constant-assert lens)."""
    base = {"product": "p", "files_scanned": 0, "findings": (), "parse_errors": ()}
    base.update(over)
    return foundry.summarize_constant_asserts(**base)


def _S(**over):
    """Build a frozen sub-`SkippedTestSummary` (always-skipped lens)."""
    base = {"product": "p", "files_scanned": 0, "findings": (), "parse_errors": ()}
    base.update(over)
    return foundry.summarize_skipped_tests(**base)


def _tq(product="p", weak=None, constant=None, skipped=None, files_scanned=0):
    """Build a per-product `TestQualitySummary` composite via the shipped pure
    factory. Unspecified lenses default to a clean sub-summary sharing
    `files_scanned` (the three lenses walk the identical file set in a real run)."""
    return foundry.summarize_test_quality(
        product=product,
        weak=weak if weak is not None else _W(product=product, files_scanned=files_scanned),
        constant=constant if constant is not None else _C(product=product, files_scanned=files_scanned),
        skipped=skipped if skipped is not None else _S(product=product, files_scanned=files_scanned),
    )


def _run_ctq(dispatch_path, as_json=False):
    """Drive company_test_quality_cli directly, capturing (rc, stdout+stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.company_test_quality_cli(dispatch_path, as_json=as_json)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue() + err.getvalue()


def _snapshot_tree(root):
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def _write_dispatch(tmp_path, work_items, name="foundry.config.json"):
    p = pathlib.Path(tmp_path) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"work_items": work_items}))
    return p


def _final_verdict_token(text):
    lines = [ln for ln in text.splitlines()
             if ln.strip().lower().startswith("verdict:")]
    assert lines, f"no `verdict:` line found in:\n{text}"
    return lines[-1].split(":", 1)[1].strip()


def _product_line(text, product):
    rows = [ln for ln in text.splitlines()
            if ln.strip().startswith(f"- {product}:")]
    assert len(rows) == 1, \
        f"expected exactly one line for {product!r}, got {rows!r}\n{text}"
    return rows[0]


def _patch_cli(monkeypatch, tq_by_name):
    """Monkeypatch load_config (tags a cfg with the resolved path, records every
    load) + gather_test_quality (returns a TestQualitySummary by matching a
    product-name substring of the config path)."""
    loaded = []

    class _Cfg:
        def __init__(self, path):
            self._path = path

    def fake_load(path):
        loaded.append(path)
        return _Cfg(path)

    def fake_gather(cfg, files=None):
        for name, tq in tq_by_name.items():
            if name in cfg._path:
                return tq
        return _tq("unknown", files_scanned=1)

    monkeypatch.setattr(foundry, "load_config", fake_load)
    monkeypatch.setattr(foundry, "gather_test_quality", fake_gather)
    return loaded


def _fn_names_consts(fn):
    stack, seen = [fn.__code__], set()
    names, consts = set(), set()
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names |= set(code.co_names)
        for c in code.co_consts:
            if isinstance(c, str):
                consts.add(c)
            elif isinstance(c, types.CodeType):
                stack.append(c)
    return names, consts


def _module_names_consts(module):
    names, consts = set(), set()
    for v in vars(module).values():
        if isinstance(v, types.FunctionType):
            n, c = _fn_names_consts(v)
            names |= n
            consts |= c
        elif isinstance(v, type):
            for m in vars(v).values():
                if isinstance(m, types.FunctionType):
                    n, c = _fn_names_consts(m)
                    names |= n
                    consts |= c
    return names, consts


def _load_leak_guard():
    spec = importlib.util.spec_from_file_location("leak_guard", _LEAK_GUARD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["leak_guard"] = mod
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# Behavior 1 -- pure keyword-only roll-up core: frozen, sums, counts
# ==========================================================================
def test_b1_worked_example_fields_sums_and_counts():
    pA = _tq("alpha",
             weak=_W(product="alpha", files_scanned=3, findings=(("a.py", "test_x"),)),
             constant=_C(product="alpha", files_scanned=3),
             skipped=_S(product="alpha", files_scanned=3))
    pB = _tq("beta",
             weak=_W(product="beta", files_scanned=2),
             constant=_C(product="beta", files_scanned=2),
             skipped=_S(product="beta", files_scanned=2,
                        parse_errors=(("b.py", "SyntaxError: bad"),)))
    cst = foundry.summarize_company_test_quality(
        dispatch_path="d.json", products=(pA, pB), disabled=(), errors=())
    assert dataclasses.is_dataclass(cst)
    assert type(cst).__name__ == "CompanyTestQuality"
    assert cst.dispatch_path == "d.json"
    assert cst.products == (pA, pB)
    assert cst.n_products == 2 == len(cst.products)
    assert cst.n_disabled == 0 and cst.n_errors == 0
    assert cst.files_scanned == pA.files_scanned + pB.files_scanned == 5
    assert cst.total_weak_findings == pA.weak_findings + pB.weak_findings == 1
    assert cst.total_constant_findings == pA.constant_findings + pB.constant_findings == 0
    assert cst.total_skipped_findings == pA.skipped_findings + pB.skipped_findings == 0
    assert cst.total_findings == pA.total_findings + pB.total_findings == 1
    assert cst.total_parse_errors == pA.total_parse_errors + pB.total_parse_errors == 1


def test_b1_keyword_only_positional_raises():
    with pytest.raises(TypeError):
        foundry.summarize_company_test_quality("d.json", (), (), ())


def test_b1_coerces_iterables_to_tuples_and_never_raises_well_formed():
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=[_tq("a", files_scanned=1)],
        disabled=["x"], errors=[("e", "m")])
    assert isinstance(cst.products, tuple)
    assert isinstance(cst.disabled, tuple) and cst.disabled == ("x",)
    assert isinstance(cst.errors, tuple) and cst.errors == (("e", "m"),)
    assert cst.n_disabled == 1 and cst.n_errors == 1


def test_b1_is_frozen():
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=(_tq("a", files_scanned=1),),
        disabled=(), errors=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        cst.dispatch_path = "/other"


def test_b1_empty_products_all_zero():
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=(), disabled=(), errors=())
    assert cst.files_scanned == 0
    assert cst.total_weak_findings == 0 and cst.total_constant_findings == 0
    assert cst.total_skipped_findings == 0 and cst.total_findings == 0
    assert cst.total_parse_errors == 0 and cst.n_flagged == 0
    assert cst.n_products == 0 and cst.n_disabled == 0 and cst.n_errors == 0


# ==========================================================================
# Behavior 2 -- n_flagged semantics + clean exit 0
# ==========================================================================
def test_b2_all_clean_products_exit_0_verdict_clean():
    products = (_tq("a", files_scanned=5), _tq("b", files_scanned=2))
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=products, disabled=(), errors=())
    assert cst.n_flagged == 0
    assert cst.exit_code == 0
    assert cst.verdict == "clean"


def test_b2_n_flagged_counts_findings_or_parse_errors_only():
    p_find = _tq("f", weak=_W(product="f", files_scanned=2, findings=(("x.py", "test_x"),)),
                 constant=_C(product="f", files_scanned=2), skipped=_S(product="f", files_scanned=2))
    p_parse = _tq("p", weak=_W(product="p", files_scanned=2),
                  constant=_C(product="p", files_scanned=2,
                              parse_errors=(("y.py", "SyntaxError: y"),)),
                  skipped=_S(product="p", files_scanned=2))
    p_clean = _tq("c", files_scanned=5)     # NOT flagged
    p_zero = _tq("z", files_scanned=0)      # NOT flagged
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=(p_find, p_parse, p_clean, p_zero),
        disabled=(), errors=())
    assert cst.n_products == 4
    assert cst.n_flagged == 2, \
        "only products with findings OR parse-errors are flagged (not clean/zero-file)"
    assert cst.files_scanned == 2 + 2 + 5 + 0 == 9
    assert cst.total_findings == 1
    assert cst.total_parse_errors == 1


# ==========================================================================
# Behavior 3 -- findings-first exit 1 (three INDEPENDENT gates) + verdict token
# ==========================================================================
def test_b3_any_category_finding_gives_exit_1():
    for lens, sub in (("weak", "weak"), ("constant", "constant"), ("skipped", "skipped")):
        kwargs = {"product": "a", "files_scanned": 3}
        subs = {
            "weak": _W(product="a", files_scanned=3),
            "constant": _C(product="a", files_scanned=3),
            "skipped": _S(product="a", files_scanned=3),
        }
        if sub == "weak":
            subs["weak"] = _W(product="a", files_scanned=3, findings=(("t.py", "tw"),))
        elif sub == "constant":
            subs["constant"] = _C(product="a", files_scanned=3, findings=(("t.py", "tc"),))
        else:
            subs["skipped"] = _S(product="a", files_scanned=3, findings=(("t.py", "ts"),))
        p = foundry.summarize_test_quality(product="a", **subs)
        cst = foundry.summarize_company_test_quality(
            dispatch_path="/d", products=(p,), disabled=(), errors=())
        assert cst.total_findings > 0, f"{lens} lens finding must contribute"
        assert cst.exit_code == 1, f"a {lens} finding must gate the company to exit 1"
        assert cst.verdict == "ATTENTION"


def test_b3_parse_error_only_gives_exit_1():
    p = _tq("a", weak=_W(product="a", files_scanned=1,
                         parse_errors=(("t.py", "SyntaxError: b"),)),
            constant=_C(product="a", files_scanned=1),
            skipped=_S(product="a", files_scanned=1))
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=(p,), disabled=(), errors=())
    assert cst.total_findings == 0 and cst.total_parse_errors > 0
    assert cst.exit_code == 1 and cst.verdict == "ATTENTION"


def test_b3_team_error_only_gives_exit_1():
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=(_tq("a", files_scanned=5),),
        disabled=(), errors=(("boom", "load failed"),))
    assert cst.total_findings == 0 and cst.total_parse_errors == 0
    assert cst.n_errors == 1
    assert cst.exit_code == 1 and cst.verdict == "ATTENTION"


def test_b3_exit_and_verdict_matrix():
    clean = _tq("a", files_scanned=5)
    findp = _tq("a", weak=_W(product="a", files_scanned=3, findings=(("t.py", "ta"),)),
                constant=_C(product="a", files_scanned=3), skipped=_S(product="a", files_scanned=3))
    parsep = _tq("a", weak=_W(product="a", files_scanned=1),
                 constant=_C(product="a", files_scanned=1),
                 skipped=_S(product="a", files_scanned=1,
                            parse_errors=(("t.py", "SyntaxError: c"),)))
    cases = (
        ((clean,), (), 0),                       # clean
        ((findp,), (), 1),                       # findings
        ((parsep,), (), 1),                      # parse error
        ((clean,), (("boom", "load failed"),), 1),  # struct err
        ((), (), 2),                             # no products
        ((), (("z", "bad"),), 1),                # err w/o product
    )
    for products, errors, code in cases:
        cst = foundry.summarize_company_test_quality(
            dispatch_path="/d", products=products, disabled=(), errors=errors)
        assert cst.exit_code == code, (products, errors, cst.exit_code)
        assert cst.verdict == _VERDICT_FOR_CODE[code] == _VERDICT_FOR_CODE[cst.exit_code]


def test_b3_company_verdict_is_company_token_not_per_product_token():
    p = _tq("a", weak=_W(product="a", files_scanned=3, findings=(("t.py", "test_a"),)),
            constant=_C(product="a", files_scanned=3), skipped=_S(product="a", files_scanned=3))
    assert p.verdict == "QUALITY ISSUES FOUND", \
        "sanity: the per-product composite carries its own verdict token"
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=(p,), disabled=(), errors=())
    assert cst.verdict == "ATTENTION"
    assert cst.verdict != "QUALITY ISSUES FOUND"
    assert cst.verdict in _VERDICT_FOR_CODE.values()


# ==========================================================================
# Behavior 4 -- no-enabled-products exit 2, and zero-file products do NOT force it
# ==========================================================================
def test_b4_no_products_no_errors_exit_2():
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=(), disabled=("d1", "d2"), errors=())
    assert cst.n_products == 0
    assert cst.exit_code == 2
    assert cst.verdict == "no enabled products"


def test_b4_zero_file_product_does_not_force_exit2():
    zf = _tq("zf", files_scanned=0)
    assert zf.exit_code == 2, "sanity: a zero-file TestQualitySummary is itself exit 2"
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=(zf,), disabled=(), errors=())
    assert cst.n_products == 1 and cst.files_scanned == 0
    assert cst.exit_code == 0 and cst.verdict == "clean", \
        "a product with no scanned files must NOT force company exit 2 (findings-first)"


# ==========================================================================
# Behavior 5 -- CATEGORY-WEIGHTED total (OVERLAP, re-derived from behaviour)
# ==========================================================================
def test_b5_overlap_total_is_category_weighted_not_deduped():
    # A single synthetic test flagged by BOTH the weak lens (assertion-free) AND
    # the skipped lens (never runs). The composite counts it once PER CATEGORY, so
    # the product total is 2 -- NOT a de-duplicated distinct-test count of 1.
    over = _tq("over",
               weak=_W(product="over", files_scanned=1, findings=(("t.py", "test_over"),)),
               constant=_C(product="over", files_scanned=1),
               skipped=_S(product="over", files_scanned=1, findings=(("t.py", "test_over"),)))
    assert over.total_findings == 2, \
        "a test in TWO lenses must count once per CATEGORY (2), not de-duped to 1"
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=(over,), disabled=(), errors=())
    assert cst.total_weak_findings == 1
    assert cst.total_skipped_findings == 1
    assert cst.total_constant_findings == 0
    assert cst.total_findings == 2, \
        "company total INHERITS #25's category-weighting (once per category), not de-duped"


def test_b5_triple_overlap_counts_three():
    # A test flagged by all three lenses totals 3 at the product AND company level.
    triple = _tq("tri",
                 weak=_W(product="tri", files_scanned=1, findings=(("t.py", "test_all"),)),
                 constant=_C(product="tri", files_scanned=1, findings=(("t.py", "test_all"),)),
                 skipped=_S(product="tri", files_scanned=1, findings=(("t.py", "test_all"),)))
    assert triple.total_findings == 3
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=(triple,), disabled=(), errors=())
    assert (cst.total_weak_findings, cst.total_constant_findings,
            cst.total_skipped_findings, cst.total_findings) == (1, 1, 1, 3)


# ==========================================================================
# Behavior 6 -- render() substring contract + to_dict() key/roundtrip contract
# ==========================================================================
def test_b6_render_header_path_counts_rollup_verdict():
    pA = _tq("alpha",
             weak=_W(product="alpha", files_scanned=3, findings=(("a.py", "test_x"),)),
             constant=_C(product="alpha", files_scanned=3),
             skipped=_S(product="alpha", files_scanned=3))
    pB = _tq("beta",
             weak=_W(product="beta", files_scanned=2),
             constant=_C(product="beta", files_scanned=2,
                         parse_errors=(("b.py", "SyntaxError: bad"),)),
             skipped=_S(product="beta", files_scanned=2))
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d/fc.json", products=(pA, pB),
        disabled=("gone",), errors=(("errp", "boom msg"),))
    r = cst.render()
    assert "foundry company-test-quality" in r
    assert "/d/fc.json" in r, "render must contain the dispatch path"
    assert f"{cst.n_products} gathered" in r
    assert f"{cst.n_disabled} disabled" in r
    assert f"{cst.n_errors} error" in r
    # the rollup counts line carries all per-category substrings
    assert f"{cst.files_scanned} files scanned" in r
    assert "assertion-free" in r
    assert "constant-assert" in r
    assert "always-skipped" in r
    assert f"{cst.total_findings} total quality findings" in r
    assert "parse errors" in r
    assert _final_verdict_token(r) == cst.verdict == "ATTENTION"


def test_b6_render_one_line_per_gathered_product_with_own_counts():
    pA = _tq("alpha",
             weak=_W(product="alpha", files_scanned=3, findings=(("a.py", "test_x"),)),
             constant=_C(product="alpha", files_scanned=3, findings=(("a.py", "test_c"),)),
             skipped=_S(product="alpha", files_scanned=3))
    pB = _tq("beta",
             weak=_W(product="beta", files_scanned=2),
             constant=_C(product="beta", files_scanned=2),
             skipped=_S(product="beta", files_scanned=2,
                        parse_errors=(("b.py", "SyntaxError: bad"),)))
    r = cst_render = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=(pA, pB), disabled=(), errors=()).render()
    la = _product_line(r, "alpha")
    assert f"{pA.files_scanned} files scanned" in la
    assert f"{pA.weak_findings} assertion-free" in la
    assert f"{pA.constant_findings} constant-assert" in la
    assert f"{pA.skipped_findings} always-skipped" in la
    assert f"{pA.total_findings} total" in la
    assert f"{pA.total_parse_errors} parse error" in la
    lb = _product_line(r, "beta")
    assert f"{pB.files_scanned} files scanned" in lb
    assert f"{pB.total_parse_errors} parse error" in lb


def test_b6_render_disabled_and_error_lines():
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=(_tq("okp", files_scanned=5),),
        disabled=("dis1", "dis2"), errors=(("errp", "kaboom message here"),))
    lines = cst.render().splitlines()
    for name in ("dis1", "dis2"):
        assert any(name in ln and "disabled" in ln for ln in lines), \
            f"missing disabled line for {name!r}:\n{cst.render()}"
    assert any("errp" in ln and "ERROR" in ln and "kaboom message here" in ln
               for ln in lines), \
        f"missing error line (name+ERROR+message):\n{cst.render()}"


def test_b6_render_no_leaf_leak_and_deterministic():
    pA = _tq("alpha",
             weak=_W(product="alpha", files_scanned=3, findings=(("secretfile.py", "test_secretfn"),)),
             constant=_C(product="alpha", files_scanned=3),
             skipped=_S(product="alpha", files_scanned=3,
                        parse_errors=(("crashfile.py", "SyntaxError: secretmsg"),)))
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=(pA,), disabled=("d",), errors=(("e", "m"),))
    r = cst.render()
    assert "secretfile.py" not in r and "test_secretfn" not in r, \
        "render() must NOT list individual (file :: test) findings (counts only)"
    assert "crashfile.py" not in r and "secretmsg" not in r, \
        "render() must NOT list individual parse-error leaves (counts only)"
    assert cst.render() == cst.render(), "render() must be deterministic"


def test_b6_to_dict_keys_order_roundtrip_and_values():
    pA = _tq("alpha",
             weak=_W(product="alpha", files_scanned=3, findings=(("a.py", "test_x"),)),
             constant=_C(product="alpha", files_scanned=3),
             skipped=_S(product="alpha", files_scanned=3))
    pB = _tq("beta",
             weak=_W(product="beta", files_scanned=2),
             constant=_C(product="beta", files_scanned=2,
                         parse_errors=(("b.py", "SyntaxError: bad"),)),
             skipped=_S(product="beta", files_scanned=2))
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d/fc.json", products=(pA, pB),
        disabled=("gamma",), errors=(("eps", "boom"),))
    d = cst.to_dict()
    assert json.loads(json.dumps(d)) == d, "to_dict must survive a JSON round-trip"
    assert list(d.keys()) == [
        "dispatch_config", "products", "disabled", "errors",
        "n_products", "n_disabled", "n_errors", "n_flagged",
        "files_scanned", "total_weak_findings", "total_constant_findings",
        "total_skipped_findings", "total_findings", "total_parse_errors",
        "exit_code", "verdict",
    ], f"to_dict keys/order mismatch: {list(d.keys())}"
    assert d["dispatch_config"] == "/d/fc.json" == cst.dispatch_path
    assert d["disabled"] == ["gamma"]
    assert d["errors"] == [{"product": "eps", "message": "boom"}]
    assert (d["n_products"], d["n_disabled"], d["n_errors"], d["n_flagged"]) == \
        (cst.n_products, cst.n_disabled, cst.n_errors, cst.n_flagged) == (2, 1, 1, 2)
    assert (d["files_scanned"], d["total_weak_findings"], d["total_constant_findings"],
            d["total_skipped_findings"], d["total_findings"], d["total_parse_errors"]) == \
        (cst.files_scanned, cst.total_weak_findings, cst.total_constant_findings,
         cst.total_skipped_findings, cst.total_findings, cst.total_parse_errors) == \
        (5, 1, 0, 0, 1, 1)
    assert d["exit_code"] == cst.exit_code == 1
    assert d["verdict"] == cst.verdict == "ATTENTION"


def test_b6_to_dict_products_carry_full_per_product_composite_detail():
    pA = _tq("alpha",
             weak=_W(product="alpha", files_scanned=3, findings=(("a.py", "test_x"),)),
             constant=_C(product="alpha", files_scanned=3),
             skipped=_S(product="alpha", files_scanned=3))
    pB = _tq("beta", files_scanned=2)
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=(pA, pB), disabled=(), errors=())
    d = cst.to_dict()
    assert d["products"] == [pA.to_dict(), pB.to_dict()], \
        "products must be each gathered TestQualitySummary.to_dict() IN ORDER"
    # the per-product composite payload carries its own documented key set
    assert d["products"][0].keys() == pA.to_dict().keys()
    assert "weak" in d["products"][0] and "constant" in d["products"][0] \
        and "skipped" in d["products"][0], "per-product composite lens detail must survive"


def test_b6_to_dict_all_empty_serializes_without_raising():
    cst = foundry.summarize_company_test_quality(
        dispatch_path="/d", products=(), disabled=(), errors=())
    js = json.loads(json.dumps(cst.to_dict()))
    assert js["products"] == [] and js["disabled"] == [] and js["errors"] == []
    assert js["files_scanned"] == 0 and js["total_findings"] == 0
    assert js["exit_code"] == 2 and js["verdict"] == "no enabled products"


# ==========================================================================
# Behavior 7 -- company_test_quality_cli rolls up an enabled dispatch config
# ==========================================================================
def test_b7_enabled_gathered_disabled_recorded_never_loaded(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
        {"name": "gone", "config": str(tmp_path / "gone.json"), "enabled": False},
    ])
    loaded = _patch_cli(monkeypatch, {
        "alpha": _tq("alpha", weak=_W(product="alpha", files_scanned=3,
                                      findings=(("a.py", "test_a"),)),
                     constant=_C(product="alpha", files_scanned=3),
                     skipped=_S(product="alpha", files_scanned=3)),
        "beta": _tq("beta", files_scanned=2),
    })
    rc, out = _run_ctq(str(disp))
    assert rc == 1, "a gathered team with a finding must make the company exit 1"
    assert loaded == [str(tmp_path / "alpha.json"), str(tmp_path / "beta.json")], \
        "only the ENABLED items are load_config'd; the disabled item is never loaded"
    assert "foundry company-test-quality" in out
    assert _product_line(out, "alpha")
    assert _product_line(out, "beta")
    assert any("gone" in ln and "disabled" in ln for ln in out.splitlines()), \
        "the disabled item must still be listed as disabled"


def test_b7_disabled_never_passed_to_gather(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "gone", "config": str(tmp_path / "gone.json"), "enabled": False},
    ])
    gathered = []
    monkeypatch.setattr(foundry, "load_config",
                        lambda p: type("C", (), {"_path": p})())

    def fake_gather(cfg, files=None):
        gathered.append(cfg._path)
        return _tq("alpha", files_scanned=1)

    monkeypatch.setattr(foundry, "gather_test_quality", fake_gather)
    _run_ctq(str(disp))
    assert gathered == [str(tmp_path / "alpha.json")], \
        "the disabled item must NEVER reach gather_test_quality"


def test_b7_json_is_single_indent2_document_equal_to_to_dict(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    skA = _tq("alpha", weak=_W(product="alpha", files_scanned=3,
                               findings=(("a.py", "t"),)),
              constant=_C(product="alpha", files_scanned=3),
              skipped=_S(product="alpha", files_scanned=3))
    skB = _tq("beta", files_scanned=2)
    _patch_cli(monkeypatch, {"alpha": skA, "beta": skB})
    rc_h, _ = _run_ctq(str(disp), as_json=False)
    rc_j, out_j = _run_ctq(str(disp), as_json=True)
    doc = json.loads(out_j.strip())  # the ENTIRE stdout is ONE parseable JSON doc
    expected = foundry.summarize_company_test_quality(
        dispatch_path=str(disp), products=(skA, skB), disabled=(), errors=())
    assert doc == expected.to_dict(), "the --json doc must equal the roll-up's to_dict()"
    assert out_j.strip() == json.dumps(doc, indent=2), \
        "the --json path must print exactly one json.dumps(to_dict(), indent=2) doc"
    assert rc_j == rc_h == doc["exit_code"] == 1
    assert [p["product"] for p in doc["products"]] == ["alpha", "beta"]


def test_b7_human_path_prints_render(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    skA = _tq("alpha", weak=_W(product="alpha", files_scanned=3,
                               findings=(("a.py", "t"),)),
              constant=_C(product="alpha", files_scanned=3),
              skipped=_S(product="alpha", files_scanned=3))
    skB = _tq("beta", files_scanned=2)
    _patch_cli(monkeypatch, {"alpha": skA, "beta": skB})
    rc, out = _run_ctq(str(disp), as_json=False)
    expected = foundry.summarize_company_test_quality(
        dispatch_path=str(disp), products=(skA, skB), disabled=(), errors=())
    assert out.rstrip("\n") == expected.render().rstrip("\n"), \
        f"human path must print render():\n{out}"
    assert rc == expected.exit_code


def test_b7_replacing_gather_changes_reported_figures(tmp_path, monkeypatch):
    # gather_test_quality is called by BARE name -> replacing it bites.
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])
    monkeypatch.setattr(foundry, "load_config",
                        lambda p: type("C", (), {"_path": p})())
    monkeypatch.setattr(foundry, "gather_test_quality",
                        lambda cfg, files=None: _tq("alpha", files_scanned=7))
    _, out_a = _run_ctq(str(disp), as_json=True)
    assert json.loads(out_a.strip())["files_scanned"] == 7
    monkeypatch.setattr(foundry, "gather_test_quality",
                        lambda cfg, files=None: _tq("alpha", files_scanned=99))
    _, out_b = _run_ctq(str(disp), as_json=True)
    assert json.loads(out_b.strip())["files_scanned"] == 99, \
        "replacing foundry.gather_test_quality must change reported figures (bare-name seam)"


def test_b7_foundry_token_substituted_before_load(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": "{FOUNDRY}/products/alpha/config.json",
         "enabled": True},
    ])
    loaded = _patch_cli(monkeypatch, {"alpha": _tq("alpha", files_scanned=3)})
    _run_ctq(str(disp))
    froot = str(pathlib.Path(foundry.__file__).resolve().parent)
    assert loaded == [f"{froot}/products/alpha/config.json"], \
        f"{{FOUNDRY}} must be substituted to the foundry root before load: {loaded}"
    assert "{FOUNDRY}" not in "".join(loaded)


def test_b7_read_only_writes_nothing_to_disk(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _tq("alpha", files_scanned=3)})
    before = _snapshot_tree(tmp_path)
    _run_ctq(str(disp), as_json=False)
    _run_ctq(str(disp), as_json=True)
    assert _snapshot_tree(tmp_path) == before, \
        "company-test-quality wrote to disk (must be read-only)"


# ==========================================================================
# Behavior 8 -- CLI resilience to a bad dispatch config + dispatch order
# ==========================================================================
def test_b8_missing_dispatch_file_exit1_no_raise(tmp_path):
    rc, out = _run_ctq(str(tmp_path / "does-not-exist.json"))
    assert rc == 1 and "ERROR" in out


def test_b8_invalid_json_exit1_no_raise(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json ]")
    rc, out = _run_ctq(str(bad))
    assert rc == 1 and "ERROR" in out


def test_b8_not_a_json_object_exit1(tmp_path):
    lst = tmp_path / "list.json"
    lst.write_text("[1, 2, 3]")
    rc, _ = _run_ctq(str(lst))
    assert rc == 1


def test_b8_each_bad_config_yields_exactly_one_synthetic_error(tmp_path):
    # missing / non-JSON / non-object each -> EXACTLY ONE (dispatch_path, msg) error.
    missing = tmp_path / "nope.json"
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json ]")
    lst = tmp_path / "list.json"
    lst.write_text("[1, 2, 3]")
    for p in (missing, bad, lst):
        rc, out = _run_ctq(str(p), as_json=True)
        doc = json.loads(out.strip())  # still exactly one parseable JSON doc
        assert rc == 1 and doc["exit_code"] == 1
        assert len(doc["errors"]) == 1, f"expected 1 synthetic error for {p.name}: {doc['errors']}"
        assert doc["errors"][0]["product"] == str(p), \
            f"the ONE synthetic error must be keyed by the dispatch path: {doc['errors']}"


def test_b8_one_bad_team_recorded_rollup_continues(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "good", "config": str(tmp_path / "good.json"), "enabled": True},
        {"name": "bad", "config": str(tmp_path / "bad.json"), "enabled": True},
        {"name": "good2", "config": str(tmp_path / "good2.json"), "enabled": True},
    ])

    def fake_load(path):
        if "bad.json" in path:
            raise RuntimeError("kaboom loading bad")
        return type("C", (), {"_path": path})()

    monkeypatch.setattr(foundry, "load_config", fake_load)
    monkeypatch.setattr(
        foundry, "gather_test_quality",
        lambda cfg, files=None: _tq(
            "good" if "good.json" in cfg._path else "good2", files_scanned=3))
    rc, out = _run_ctq(str(disp), as_json=True)
    doc = json.loads(out.strip())
    assert rc == 1 and doc["exit_code"] == 1
    assert {"product": "bad", "message": "kaboom loading bad"} in doc["errors"], \
        f"the failing item + its message must be recorded: {doc['errors']}"
    assert [p["product"] for p in doc["products"]] == ["good", "good2"], \
        "gathering must CONTINUE past the failed team"


def test_b8_gather_raise_recorded_rollup_continues(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "boomp", "config": str(tmp_path / "boomp.json"), "enabled": True},
        {"name": "okp", "config": str(tmp_path / "okp.json"), "enabled": True},
    ])
    monkeypatch.setattr(foundry, "load_config",
                        lambda p: type("C", (), {"_path": p})())

    def fake_gather(cfg, files=None):
        if "boomp.json" in cfg._path:
            raise ValueError("gather blew up")
        return _tq("okp", files_scanned=3)

    monkeypatch.setattr(foundry, "gather_test_quality", fake_gather)
    rc, out = _run_ctq(str(disp), as_json=True)
    doc = json.loads(out.strip())
    assert rc == 1 and doc["exit_code"] == 1
    assert {"product": "boomp", "message": "gather blew up"} in doc["errors"], \
        f"a raising gather must be recorded as (name, str(exc)): {doc['errors']}"
    assert [p["product"] for p in doc["products"]] == ["okp"], \
        "roll-up must continue to the remaining enabled team"


def test_b8_main_dispatches_before_top_level_load_config(tmp_path, monkeypatch):
    # main() must route company-test-quality BEFORE load_config(args.config): the
    # dispatch config is NOT a product config, so a load_config that raises must
    # never be reached on the args.config path.
    disp = _write_dispatch(tmp_path, [], name="empty.json")

    def boom(path):
        raise AssertionError(f"main called load_config(args.config)={path!r}")

    monkeypatch.setattr(foundry, "load_config", boom)
    # empty work_items -> no enabled products -> exit 2, and boom never reached
    rc = foundry.main([SUBCMD, "--config", str(disp)])
    assert rc == 2


# ==========================================================================
# Behavior 9 -- wiring, dormancy, no command regression
# ==========================================================================
def test_b9_main_json_returns_code_and_emits_json(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])
    monkeypatch.setattr(foundry, "load_config",
                        lambda p: type("C", (), {"_path": p})())
    monkeypatch.setattr(
        foundry, "gather_test_quality",
        lambda cfg, files=None: _tq("alpha", weak=_W(product="alpha", files_scanned=3,
                                                     findings=(("a.py", "t"),)),
                                    constant=_C(product="alpha", files_scanned=3),
                                    skipped=_S(product="alpha", files_scanned=3)))
    out = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = out
    try:
        rc = foundry.main([SUBCMD, "--config", str(disp), "--json"])
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    doc = json.loads(out.getvalue().strip())
    assert rc == doc["exit_code"] == 1
    assert doc["verdict"] == "ATTENTION"


def test_b9_subcommand_help_has_config_json_but_no_limit_no_files():
    out = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = out
    try:
        with pytest.raises(SystemExit) as ei:
            foundry.main([SUBCMD, "--help"])
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    assert ei.value.code == 0
    text = out.getvalue()
    assert "--config" in text and "--json" in text
    assert "--limit" not in text, f"{SUBCMD} must NOT expose a --limit flag"
    assert "--files" not in text, f"{SUBCMD} must NOT expose a --files flag"


def test_b9_default_config_is_repo_dispatch_config(monkeypatch):
    captured = {}

    def spy(dispatch_path, as_json=False):
        captured.update(dp=dispatch_path, js=as_json)
        return 0

    monkeypatch.setattr(foundry, "company_test_quality_cli", spy)
    rc = foundry.main([SUBCMD])
    assert rc == 0
    froot = pathlib.Path(foundry.__file__).resolve().parent
    assert captured["dp"] == str(froot / "foundry.config.json"), \
        "default --config must be the repo's DISPATCH config (foundry.config.json)"
    assert captured["js"] is False


def test_b9_json_flag_passes_through(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        foundry, "company_test_quality_cli",
        lambda dp, as_json=False: captured.update(dp=dp, js=as_json) or 0)
    foundry.main([SUBCMD, "--json"])
    assert captured["js"] is True


def test_b9_both_modules_import():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"
    assert dispatcher is not None


def test_b9_new_surface_present_and_reuses_shipped_seams():
    for name in NEW_SYMBOLS:
        assert hasattr(foundry, name), f"missing new symbol {name!r}"
    assert callable(foundry.gather_test_quality)
    assert callable(foundry.summarize_company_test_quality)
    assert callable(foundry.company_test_quality_cli)
    for name in ("parse_dispatch_work_items", "gather_weak_tests",
                 "gather_constant_asserts", "gather_skipped_tests",
                 "summarize_test_quality", "TestQualitySummary",
                 "test_quality_cli", "load_config"):
        assert hasattr(foundry, name), f"shipped seam {name!r} vanished"


def test_b9_new_symbols_absent_from_control_flow_and_siblings_and_dispatcher():
    # control-flow fns must reference NONE of the 4 new symbols, and must not
    # embed the subcommand literal.
    for fn_name in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references new symbol {sym!r} (must stay off the control path)"
        assert SUBCMD not in consts, f"{fn_name} embeds the {SUBCMD!r} subcommand literal"
    # Sibling CLIs must reference NONE of the 4 new symbols -- with ONE pair
    # deliberately RETIRED by iter 212, which de-duplicated the composite
    # composition policy: `test_quality_cli` now composes THROUGH the
    # `gather_test_quality` seam instead of carrying a second, DIVERGED copy of
    # it (only the seam ever gained iter 159's resolve-once / shared
    # TEST_TREE_CACHE speed-up). `gather_test_quality`'s own docstring had
    # recorded that refactor as an owed "separate future bite" since iter 59, so
    # this clause was a stale pin of iter 59's historical additive-dormancy, not
    # a live invariant. It is retired as ONE (sibling, symbol) pair rather than
    # by dropping the sibling: every OTHER pair stays forbidden, and the exempt
    # pair is asserted POSITIVELY so the brake still pins the shipped design
    # (a bare-name call is what keeps `monkeypatch.setattr(foundry, ...)` biting).
    RETIRED_PAIRS = {("test_quality_cli", "gather_test_quality")}
    for fn_name in ("company_weak_tests_cli", "company_constant_asserts_cli",
                    "company_skipped_tests_cli", "test_quality_cli",
                    "weak_tests_cli", "constant_asserts_cli", "skipped_tests_cli"):
        if hasattr(foundry, fn_name):
            names, _ = _fn_names_consts(getattr(foundry, fn_name))
            for sym in NEW_SYMBOLS:
                if (fn_name, sym) in RETIRED_PAIRS:
                    assert sym in names, \
                        f"{fn_name} must call {sym!r} by BARE name (iter 212)"
                    continue
                assert sym not in names, \
                    f"sibling {fn_name} references new symbol {sym!r}"
    # ONLY main() references company_test_quality_cli, which references the
    # gather + summarize seams.
    main_names, _ = _fn_names_consts(foundry.main)
    assert "company_test_quality_cli" in main_names, \
        "main() must dispatch to company_test_quality_cli"
    cli_names, _ = _fn_names_consts(foundry.company_test_quality_cli)
    assert "gather_test_quality" in cli_names, \
        "company_test_quality_cli must call gather_test_quality by bare name"
    assert "summarize_company_test_quality" in cli_names, \
        "company_test_quality_cli must call summarize_company_test_quality by bare name"
    # dispatcher references none of the new symbols
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    dnames, dconsts = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in dnames, f"dispatcher references {sym!r}"
    assert SUBCMD not in dconsts, f"dispatcher references the {SUBCMD!r} literal"


def test_b9_help_lists_company_test_quality_with_siblings(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    text = capsys.readouterr().out
    for sub in ("test-quality", "company-weak-tests", "company-constant-asserts",
                "company-skipped-tests", "company-status", "company-history",
                "company-timing", "company-events", SUBCMD):
        assert sub in text, f"subcommand {sub!r} missing from --help:\n{text}"


def test_b9_control_path_and_guard_scripts_byte_unchanged():
    # `git diff --quiet` emits NO diff text (exit-code-only) -> honors isolation.
    # foundry.py is EXCLUDED (it is routinely extended additively each iteration);
    # the resume-safety invariant is dispatcher.py + the guard scripts byte-frozen
    # + a clean import + an additive-only diff.
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--",
         "dispatcher.py", "scripts/leak_guard.py", "scripts/leak_denylist.txt"],
        cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, \
        "dispatcher.py / guard scripts are NOT byte-unchanged from HEAD"


def test_b9_shipped_public_files_scan_clean_and_no_home_path():
    if not (_LEAK_GUARD.exists() and _DENYLIST.exists()):
        pytest.skip("leak-guard not present in this repo (repo-agnostic)")
    lg = _load_leak_guard()
    patterns = lg.load_denylist(_DENYLIST.read_text())  # API takes TEXT, not a Path
    home_prefix = "/" + "Users" + "/"  # built at runtime; never a source literal
    # liveness: the denylist is a LIVE matcher, not inert
    assert len(lg.scan_text(home_prefix + "somebody/x", patterns)) >= 1, \
        "denylist appears inert (a home-path probe did not match)"
    for rel in ("tests/test_iter59_behavior.py", "README.md", "PLATFORM_ROADMAP.md"):
        p = _ROOT / rel
        if not p.exists():
            continue
        txt = p.read_text()
        assert len(lg.scan_text(txt, patterns)) == 0, \
            f"{rel} contains a denylisted token (would BLOCK this iteration's ship)"
        assert home_prefix not in txt, f"{rel} contains an absolute home-directory path"


def test_b9_live_smoke_on_real_dispatch_config():
    froot = pathlib.Path(foundry.__file__).resolve().parent
    if not (froot / "foundry.config.json").exists():
        pytest.skip(
            "machine-local foundry.config.json absent at repo root (gitignored); "
            "live smoke needs the operator's real dispatch config")
    out = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = out
    try:
        rc = foundry.main([SUBCMD, "--json"])
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    doc = json.loads(out.getvalue().strip())  # ONE parseable JSON document
    assert rc == doc["exit_code"]
    assert doc["verdict"] == _VERDICT_FOR_CODE[doc["exit_code"]]
