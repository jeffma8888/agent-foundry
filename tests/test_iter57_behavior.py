"""Black-box behaviour tests for iter 57 -- `foundry company-skipped-tests`:
the read-only, offline company-wide roll-up of the per-product iter-56
`skipped-tests` scan -- the 7th `company-*` family member (after
company-status/history/timing/weak-tests/events/constant-asserts). It folds
every ENABLED dispatch team's always-skipped-test scan into ONE report + a
scriptable GATE exit code, composed on top of the shipped `gather_skipped_tests`
seam + the frozen `SkippedTestSummary`. Purely additive in foundry.py:

  * a FROZEN dataclass `CompanySkippedTests(dispatch_path, products, disabled,
    errors)` with n_* count props + files_scanned/total_findings/
    total_parse_errors/n_flagged sums + findings-GATING exit_code/verdict +
    render() + to_dict(),
  * a PURE keyword-only `summarize_company_skipped_tests(*, dispatch_path,
    products, disabled, errors) -> CompanySkippedTests`,
  * a thin resilient `company_skipped_tests_cli(dispatch_path, as_json=False)
    -> int` wired to a new argparse subcommand `company-skipped-tests` (NO
    --limit, NO --files), reusing the shipped `parse_dispatch_work_items` +
    `gather_skipped_tests` + `SkippedTestSummary` seams.

ONE CORRECTNESS DIVERGENCE FROM THE `company-constant-asserts` REFERENCE
(re-derived from OBSERVED behaviour, NOT copied): `company-constant-asserts` is
DISJOINT from `company-weak-tests` by the detectors' construction (a constant
assert CARRIES an assert node, so an assertion-free scan can never also flag
it). But an ALWAYS-SKIPPED test CAN ALSO be assertion-free, so
`company-skipped-tests` findings CAN OVERLAP `company-weak-tests` /
`company-constant-asserts` -- a THIRD COMPLEMENTARY lens catching a DIFFERENT
antipattern (a test that never RUNS at all). Behavior 8 proves that overlap at
the detector level rather than copying iter-54's disjointness assertion.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-57 PM
spec's Expected Behaviors (1-8), the product README/roadmap, the tests/
conventions (esp. tests/test_iter54_behavior.py -- the structural mirror
company-constant-asserts -- and tests/test_iter56_behavior.py -- the per-product
skipped-tests foundation), and the product's own OBSERVABLE behaviour (building
the public objects and RUNNING them / --help). The implementation SOURCE
(foundry.py / dispatcher.py source text), the engineer's & reviewer's notes, and
`git diff` were NOT read. Every assertion is DERIVED from the spec's pinned
substrings + observed output, never copied from implementation phrasing. Every
check drives the PUBLIC interface against tiny JSON files in tmp_path,
monkeypatching foundry.load_config / foundry.gather_skipped_tests. The real
product repos / state / network are NEVER touched (except the read-only import,
--help probes, a byte-unchanged `git diff --quiet` exit-code check that reads NO
diff text, and a self-leak scan). Fully offline & deterministic.
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
# note these are the COMPANY tokens, NOT the per-product SkippedTestSummary token
# "ALWAYS-SKIPPED TESTS FOUND".
_VERDICT_FOR_CODE = {0: "clean", 1: "ATTENTION", 2: "no enabled products"}

# the genuinely-NEW iter-57 symbols
NEW_SYMBOLS = ("CompanySkippedTests", "summarize_company_skipped_tests",
               "company_skipped_tests_cli")
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")
SUBCMD = "company-skipped-tests"


# --------------------------------------------------------------------------
# helpers  (mirror tests/test_iter54_behavior.py)
# --------------------------------------------------------------------------
def _sk(product, files_scanned, findings=(), parse_errors=()):
    """Build a per-product SkippedTestSummary via the shipped pure factory."""
    return foundry.summarize_skipped_tests(
        product=product, files_scanned=files_scanned,
        findings=tuple(findings), parse_errors=tuple(parse_errors))


def _run_cst(dispatch_path, as_json=False):
    """Drive company_skipped_tests_cli directly, capturing (rc, stdout+stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.company_skipped_tests_cli(dispatch_path, as_json=as_json)
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


def _patch_cli(monkeypatch, sk_by_name):
    """Monkeypatch load_config (tags a cfg with the resolved path, records every
    load) + gather_skipped_tests (returns a SkippedTestSummary by matching a
    product-name substring of the config path)."""
    loaded = []

    class _Cfg:
        def __init__(self, path):
            self._path = path

    def fake_load(path):
        loaded.append(path)
        return _Cfg(path)

    def fake_gather(cfg, files=None):
        for name, sk in sk_by_name.items():
            if name in cfg._path:
                return sk
        return _sk("unknown", 1)

    monkeypatch.setattr(foundry, "load_config", fake_load)
    monkeypatch.setattr(foundry, "gather_skipped_tests", fake_gather)
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
# Behavior 1 -- pure keyword-only constructor + frozen roll-up + sums/counts
# ==========================================================================
def test_b1_worked_example_fields_sums_and_counts():
    pA = _sk("alpha", 3, findings=(("a.py", "test_x"),), parse_errors=())
    pB = _sk("beta", 2, findings=(), parse_errors=(("b.py", "SyntaxError: bad"),))
    cst = foundry.summarize_company_skipped_tests(
        dispatch_path="/d/fc.json", products=(pA, pB),
        disabled=("gamma", "delta"), errors=(("eps", "boom"),))
    assert dataclasses.is_dataclass(cst)
    assert type(cst).__name__ == "CompanySkippedTests"
    assert cst.dispatch_path == "/d/fc.json"
    assert cst.products == (pA, pB) and cst.disabled == ("gamma", "delta")
    assert cst.errors == (("eps", "boom"),)
    assert cst.files_scanned == 5 == sum(p.files_scanned for p in cst.products)
    assert cst.total_findings == 1 == sum(p.total_findings for p in cst.products)
    assert cst.total_parse_errors == 1 == sum(len(p.parse_errors) for p in cst.products)
    assert cst.n_flagged == 2
    assert cst.n_products == 2 == len(cst.products)
    assert cst.n_disabled == 2 == len(cst.disabled)
    assert cst.n_errors == 1 == len(cst.errors)


def test_b1_coerces_iterables_to_tuples_keyword_only():
    # lists in -> tuples stored (coercion); keyword-only, never raises well-formed
    cst = foundry.summarize_company_skipped_tests(
        dispatch_path="/d", products=[_sk("a", 1)], disabled=["x"],
        errors=[("e", "m")])
    assert isinstance(cst.products, tuple)
    assert isinstance(cst.disabled, tuple) and cst.disabled == ("x",)
    assert isinstance(cst.errors, tuple) and cst.errors == (("e", "m"),)


def test_b1_is_frozen():
    cst = foundry.summarize_company_skipped_tests(
        dispatch_path="/d", products=(_sk("a", 1),), disabled=(), errors=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        cst.dispatch_path = "/other"


def test_b1_empty_products_all_zero():
    cst = foundry.summarize_company_skipped_tests(
        dispatch_path="/d", products=(), disabled=(), errors=())
    assert cst.files_scanned == 0 and cst.total_findings == 0
    assert cst.total_parse_errors == 0 and cst.n_flagged == 0
    assert cst.n_products == 0 and cst.n_disabled == 0 and cst.n_errors == 0


# ==========================================================================
# Behavior 2 -- SUM + count properties (n_flagged semantics)
# ==========================================================================
def test_b2_n_flagged_counts_findings_or_parse_errors_only():
    p_find = _sk("f", 2, findings=(("x.py", "test_x"),))              # flagged
    p_parse = _sk("p", 2, parse_errors=(("y.py", "SyntaxError: y"),))  # flagged
    p_clean = _sk("c", 5)                                             # NOT flagged
    p_zero = _sk("z", 0)                                              # NOT flagged
    cst = foundry.summarize_company_skipped_tests(
        dispatch_path="/d", products=(p_find, p_parse, p_clean, p_zero),
        disabled=(), errors=())
    assert cst.n_products == 4
    assert cst.n_flagged == 2, \
        "only products with findings OR parse-errors are flagged (not clean/zero-file)"
    assert cst.files_scanned == 2 + 2 + 5 + 0 == 9
    assert cst.total_findings == 1
    assert cst.total_parse_errors == 1


# ==========================================================================
# Behavior 3 -- exit_code (findings-first GATE) + COMPANY verdict token
# ==========================================================================
def test_b3_exit_and_verdict_matrix():
    cases = (
        ((_sk("a", 5),), (), 0),                                          # clean
        ((_sk("a", 3, findings=(("t.py", "test_a"),)),), (), 1),          # findings
        ((_sk("a", 1, parse_errors=(("t.py", "SyntaxError: b"),)),), (), 1),  # parse
        ((_sk("a", 5),), (("boom", "load failed"),), 1),                  # struct err
        ((), (), 2),                                                      # no products
        ((), (("z", "bad"),), 1),                                         # err w/o prod
    )
    for products, errors, code in cases:
        cst = foundry.summarize_company_skipped_tests(
            dispatch_path="/d", products=products, disabled=(), errors=errors)
        assert cst.exit_code == code, (products, errors, cst.exit_code)
        assert cst.verdict == _VERDICT_FOR_CODE[code] == _VERDICT_FOR_CODE[cst.exit_code]


def test_b3_zero_file_product_does_not_force_exit2():
    zf = _sk("zf", 0)
    assert zf.exit_code == 2, "sanity: a zero-file SkippedTestSummary is itself exit 2"
    cst = foundry.summarize_company_skipped_tests(
        dispatch_path="/d", products=(zf,), disabled=(), errors=())
    assert cst.n_products == 1 and cst.files_scanned == 0
    assert cst.exit_code == 0 and cst.verdict == "clean", \
        "a product with no scanned files must NOT force company exit 2"


def test_b3_company_verdict_is_company_token_not_per_product_token():
    # a finding gives COMPANY verdict "ATTENTION", never the per-product
    # SkippedTestSummary token "ALWAYS-SKIPPED TESTS FOUND".
    p = _sk("a", 3, findings=(("t.py", "test_a"),))
    assert p.verdict == "ALWAYS-SKIPPED TESTS FOUND", \
        "sanity: the per-product summary carries its own verdict token"
    cst = foundry.summarize_company_skipped_tests(
        dispatch_path="/d", products=(p,), disabled=(), errors=())
    assert cst.verdict == "ATTENTION"
    assert cst.verdict != "ALWAYS-SKIPPED TESTS FOUND"
    assert cst.verdict in _VERDICT_FOR_CODE.values()


# ==========================================================================
# Behavior 4 -- render() substring contract
# ==========================================================================
def test_b4_render_header_path_counts_rollup_verdict():
    pA = _sk("alpha", 3, findings=(("a.py", "test_x"),))
    pB = _sk("beta", 2, parse_errors=(("b.py", "SyntaxError: bad"),))
    cst = foundry.summarize_company_skipped_tests(
        dispatch_path="/d/fc.json", products=(pA, pB),
        disabled=("gone",), errors=(("errp", "boom msg"),))
    r = cst.render()
    assert "foundry company-skipped-tests" in r
    assert "/d/fc.json" in r, "render must contain the dispatch path"
    assert f"{cst.n_products} gathered" in r
    assert f"{cst.n_disabled} disabled" in r
    assert f"{cst.n_errors} error" in r
    assert f"{cst.files_scanned} files scanned" in r
    assert f"{cst.total_findings} always-skipped tests" in r
    assert f"{cst.total_parse_errors} parse errors" in r
    assert _final_verdict_token(r) == cst.verdict == "ATTENTION"


def test_b4_render_one_line_per_gathered_product_with_own_counts():
    pA = _sk("alpha", 3, findings=(("a.py", "test_x"), ("a2.py", "test_y")))
    pB = _sk("beta", 2, parse_errors=(("b.py", "SyntaxError: bad"),))
    cst = foundry.summarize_company_skipped_tests(
        dispatch_path="/d", products=(pA, pB), disabled=(), errors=())
    la = _product_line(cst.render(), "alpha")
    assert f"{pA.files_scanned} files scanned" in la
    assert f"{pA.total_findings} always-skipped" in la
    assert f"{len(pA.parse_errors)} parse error" in la
    lb = _product_line(cst.render(), "beta")
    assert f"{pB.files_scanned} files scanned" in lb
    assert f"{pB.total_findings} always-skipped" in lb
    assert f"{len(pB.parse_errors)} parse error" in lb


def test_b4_render_disabled_and_error_lines():
    cst = foundry.summarize_company_skipped_tests(
        dispatch_path="/d", products=(_sk("okp", 5),),
        disabled=("dis1", "dis2"), errors=(("errp", "kaboom message here"),))
    lines = cst.render().splitlines()
    for name in ("dis1", "dis2"):
        assert any(name in ln and "disabled" in ln for ln in lines), \
            f"missing disabled line for {name!r}:\n{cst.render()}"
    assert any("errp" in ln and "ERROR" in ln and "kaboom message here" in ln
               for ln in lines), \
        f"missing error line (name+ERROR+message):\n{cst.render()}"


def test_b4_render_no_leaf_leak_and_deterministic():
    # per-product COUNTS only, NOT each (file :: test) finding/parse-error leaf
    pA = _sk("alpha", 3, findings=(("secretfile.py", "test_secretfn"),),
             parse_errors=(("crashfile.py", "SyntaxError: secretmsg"),))
    cst = foundry.summarize_company_skipped_tests(
        dispatch_path="/d", products=(pA,), disabled=("d",), errors=(("e", "m"),))
    r = cst.render()
    assert "secretfile.py" not in r and "test_secretfn" not in r, \
        "render() must NOT list individual (file :: test) findings (counts only)"
    assert "crashfile.py" not in r and "secretmsg" not in r, \
        "render() must NOT list individual parse-error leaves (counts only)"
    assert cst.render() == cst.render(), "render() must be deterministic"


# ==========================================================================
# Behavior 5 -- to_dict() JSON-safe, reuses frozen props, full per-product detail
# ==========================================================================
def test_b5_to_dict_keys_roundtrip_and_values():
    pA = _sk("alpha", 3, findings=(("a.py", "test_x"),))
    pB = _sk("beta", 2, parse_errors=(("b.py", "SyntaxError: bad"),))
    cst = foundry.summarize_company_skipped_tests(
        dispatch_path="/d/fc.json", products=(pA, pB),
        disabled=("gamma",), errors=(("eps", "boom"),))
    d = cst.to_dict()
    assert json.loads(json.dumps(d)) == d, "to_dict must survive a JSON round-trip"
    expected = {"dispatch_config", "products", "disabled", "errors",
                "n_products", "n_disabled", "n_errors", "n_flagged",
                "files_scanned", "total_findings", "total_parse_errors",
                "exit_code", "verdict"}
    assert expected <= set(d), f"missing keys: {expected - set(d)}"
    assert d["dispatch_config"] == "/d/fc.json" == cst.dispatch_path
    assert d["disabled"] == ["gamma"]
    assert d["errors"] == [{"product": "eps", "message": "boom"}]
    assert (d["n_products"], d["n_disabled"], d["n_errors"], d["n_flagged"]) == \
        (cst.n_products, cst.n_disabled, cst.n_errors, cst.n_flagged) == (2, 1, 1, 2)
    assert (d["files_scanned"], d["total_findings"], d["total_parse_errors"]) == \
        (cst.files_scanned, cst.total_findings, cst.total_parse_errors) == (5, 1, 1)
    assert d["exit_code"] == cst.exit_code == 1
    assert d["verdict"] == cst.verdict == "ATTENTION"


def test_b5_to_dict_products_carry_full_per_product_leaf_detail():
    pA = _sk("alpha", 3, findings=(("a.py", "test_x"),))
    pB = _sk("beta", 2, parse_errors=(("b.py", "SyntaxError: bad"),))
    cst = foundry.summarize_company_skipped_tests(
        dispatch_path="/d", products=(pA, pB), disabled=(), errors=())
    d = cst.to_dict()
    assert d["products"] == [pA.to_dict(), pB.to_dict()], \
        "products must be each gathered SkippedTestSummary.to_dict() IN ORDER"
    assert len(d["products"][0]) == 8, "full 8-key per-product detail"
    assert d["products"][0]["findings"], "per-product findings leaf must survive"
    assert d["products"][1]["parse_errors"], "per-product parse_errors leaf must survive"


def test_b5_to_dict_all_empty_serializes_without_raising():
    cst = foundry.summarize_company_skipped_tests(
        dispatch_path="/d", products=(), disabled=(), errors=())
    js = json.loads(json.dumps(cst.to_dict()))
    assert js["products"] == [] and js["disabled"] == [] and js["errors"] == []
    assert js["files_scanned"] == 0 and js["total_findings"] == 0
    assert js["exit_code"] == 2 and js["verdict"] == "no enabled products"


# ==========================================================================
# Behavior 6 -- company_skipped_tests_cli rolls up an enabled dispatch config
# ==========================================================================
def test_b6_enabled_gathered_disabled_recorded_never_loaded(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": False},
    ])
    loaded = _patch_cli(monkeypatch, {"alpha": _sk("alpha", 3, findings=(("a.py", "t"),))})
    rc, out = _run_cst(str(disp))
    assert rc == 1, "a gathered team with a finding must make the company exit 1"
    assert loaded == [str(tmp_path / "alpha.json")], \
        "only the ENABLED item is load_config'd; the disabled item is never loaded"
    assert "alpha" in out
    assert any("beta" in ln and "disabled" in ln for ln in out.splitlines()), \
        "the disabled item must still be listed as disabled"


def test_b6_clean_enabled_team_exits_0(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _sk("alpha", 5)})
    rc, out = _run_cst(str(disp))
    assert rc == 0, "a clean gathered team must exit 0"
    assert _final_verdict_token(out) == "clean"


def test_b6_foundry_token_substituted_before_load(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": "{FOUNDRY}/products/alpha/config.json",
         "enabled": True},
    ])
    loaded = _patch_cli(monkeypatch, {"alpha": _sk("alpha", 3)})
    _run_cst(str(disp))
    froot = str(pathlib.Path(foundry.__file__).resolve().parent)
    assert loaded == [f"{froot}/products/alpha/config.json"], \
        f"{{FOUNDRY}} must be substituted to the foundry root before load: {loaded}"
    assert "{FOUNDRY}" not in "".join(loaded)


def test_b6_gather_called_with_cfg_via_bare_name_seam(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    seen = []
    monkeypatch.setattr(foundry, "load_config",
                        lambda p: type("C", (), {"_path": p})())

    def fake_gather(cfg, files=None):
        seen.append(cfg._path)
        return _sk("x", 1)

    monkeypatch.setattr(foundry, "gather_skipped_tests", fake_gather)
    _run_cst(str(disp))
    assert seen == [str(tmp_path / "alpha.json"), str(tmp_path / "beta.json")], \
        f"gather_skipped_tests must be called by BARE name per enabled cfg: {seen}"


def test_b6_json_is_single_indent2_document_same_exit(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _sk("alpha", 3, findings=(("a.py", "t"),)),
                             "beta": _sk("beta", 2)})
    rc_h, _ = _run_cst(str(disp), as_json=False)
    rc_j, out_j = _run_cst(str(disp), as_json=True)
    doc = json.loads(out_j.strip())  # exactly ONE parseable JSON document
    assert out_j.strip() == json.dumps(doc, indent=2), \
        "the --json path must print exactly one json.dumps(to_dict(), indent=2) doc"
    assert rc_j == rc_h == doc["exit_code"] == 1
    assert [p["product"] for p in doc["products"]] == ["alpha", "beta"]


def test_b6_human_path_prints_render(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    skA = _sk("alpha", 3, findings=(("a.py", "t"),))
    skB = _sk("beta", 2)
    _patch_cli(monkeypatch, {"alpha": skA, "beta": skB})
    rc, out = _run_cst(str(disp), as_json=False)
    expected = foundry.summarize_company_skipped_tests(
        dispatch_path=str(disp), products=(skA, skB), disabled=(), errors=())
    assert out.rstrip("\n") == expected.render().rstrip("\n"), \
        f"human path must print render():\n{out}"
    assert rc == expected.exit_code


def test_b6_read_only_writes_nothing_to_disk(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _sk("alpha", 3)})
    before = _snapshot_tree(tmp_path)
    _run_cst(str(disp), as_json=False)
    _run_cst(str(disp), as_json=True)
    assert _snapshot_tree(tmp_path) == before, \
        "company-skipped-tests wrote to disk (must be read-only)"


# ==========================================================================
# Behavior 7 -- resilient to a bad dispatch config and to a bad team
# ==========================================================================
def test_b7_missing_dispatch_file_exit1_no_raise(tmp_path):
    rc, out = _run_cst(str(tmp_path / "does-not-exist.json"))
    assert rc == 1 and "ERROR" in out


def test_b7_invalid_json_exit1_no_raise(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json ]")
    rc, out = _run_cst(str(bad))
    assert rc == 1 and "ERROR" in out


def test_b7_not_a_json_object_exit1(tmp_path):
    lst = tmp_path / "list.json"
    lst.write_text("[1, 2, 3]")
    rc, _ = _run_cst(str(lst))
    assert rc == 1


def test_b7_synthetic_error_keyed_by_dispatch_path(tmp_path):
    missing = tmp_path / "nope.json"
    rc, out = _run_cst(str(missing), as_json=True)
    doc = json.loads(out.strip())  # still exactly one parseable JSON doc
    assert rc == 1 and doc["exit_code"] == 1 and len(doc["errors"]) == 1
    assert doc["errors"][0]["product"] == str(missing), \
        f"the ONE synthetic error must be keyed by the dispatch path: {doc['errors']}"


def test_b7_one_bad_team_recorded_rollup_continues(tmp_path, monkeypatch):
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
        foundry, "gather_skipped_tests",
        lambda cfg, files=None: _sk(
            "good" if "good.json" in cfg._path else "good2", 3))
    rc, out = _run_cst(str(disp), as_json=True)
    doc = json.loads(out.strip())
    assert rc == 1 and doc["exit_code"] == 1
    assert {"product": "bad", "message": "kaboom loading bad"} in doc["errors"], \
        f"the failing item + its message must be recorded: {doc['errors']}"
    assert [p["product"] for p in doc["products"]] == ["good", "good2"], \
        "gathering must CONTINUE past the failed team"


def test_b7_gather_error_recorded_as_name_and_str_exc(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "boomp", "config": str(tmp_path / "boomp.json"), "enabled": True},
    ])
    monkeypatch.setattr(foundry, "load_config", lambda p: type("C", (), {})())

    def fake_gather(cfg, files=None):
        raise ValueError("gather blew up")

    monkeypatch.setattr(foundry, "gather_skipped_tests", fake_gather)
    rc, out = _run_cst(str(disp), as_json=True)
    doc = json.loads(out.strip())
    assert rc == 1 and doc["exit_code"] == 1
    assert {"product": "boomp", "message": "gather blew up"} in doc["errors"], \
        f"error must be recorded as (name, str(exc)): {doc['errors']}"


# ==========================================================================
# Behavior 8 -- wiring, off-control-path, byte-unchanged, prior-iter maintenance,
#               and the OVERLAP-not-disjoint relationship (the iter-54 divergence)
# ==========================================================================
def test_b8_subcommand_help_has_config_json_but_no_limit_no_files():
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


def test_b8_default_config_is_repo_dispatch_config(monkeypatch):
    captured = {}

    def spy(dispatch_path, as_json=False):
        captured.update(dp=dispatch_path, js=as_json)
        return 0

    monkeypatch.setattr(foundry, "company_skipped_tests_cli", spy)
    rc = foundry.main([SUBCMD])
    assert rc == 0
    froot = pathlib.Path(foundry.__file__).resolve().parent
    assert captured["dp"] == str(froot / "foundry.config.json"), \
        "default --config must be the repo's DISPATCH config (foundry.config.json)"
    assert captured["js"] is False


def test_b8_json_flag_passes_through(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        foundry, "company_skipped_tests_cli",
        lambda dp, as_json=False: captured.update(dp=dp, js=as_json) or 0)
    foundry.main([SUBCMD, "--json"])
    assert captured["js"] is True


def test_b8_dispatched_before_load_config(monkeypatch):
    monkeypatch.setattr(foundry, "company_skipped_tests_cli",
                        lambda dp, as_json=False: 0)

    def boom(path):
        raise AssertionError(f"main called load_config(args.config)={path!r}")

    monkeypatch.setattr(foundry, "load_config", boom)
    assert foundry.main([SUBCMD, "--config", "whatever.json"]) == 0


def test_b8_both_modules_import():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"
    assert dispatcher is not None


def test_b8_new_surface_present_and_reuses_shipped_seams():
    for name in NEW_SYMBOLS:
        assert hasattr(foundry, name), f"missing new symbol {name!r}"
    assert callable(foundry.summarize_company_skipped_tests)
    assert callable(foundry.company_skipped_tests_cli)
    for name in ("parse_dispatch_work_items", "gather_skipped_tests",
                 "SkippedTestSummary", "summarize_skipped_tests",
                 "skipped_tests_cli", "find_always_skipped_tests",
                 "load_config"):
        assert hasattr(foundry, name), f"shipped seam {name!r} vanished"


def test_b8_new_symbols_absent_from_control_flow_and_dispatcher():
    for fn_name in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references new symbol {sym!r} (must stay off the control path)"
        assert SUBCMD not in consts, f"{fn_name} embeds the {SUBCMD!r} subcommand literal"
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    dnames, dconsts = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in dnames, f"dispatcher references {sym!r}"
    assert SUBCMD not in dconsts, f"dispatcher references the {SUBCMD!r} literal"


def test_b8_help_lists_company_skipped_tests_with_siblings(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    text = capsys.readouterr().out
    for sub in ("skipped-tests", "company-status", "company-history",
                "company-timing", "company-weak-tests", "company-events",
                "company-constant-asserts", SUBCMD):
        assert sub in text, f"subcommand {sub!r} missing from --help:\n{text}"


def test_b8_skipped_test_summary_to_dict_still_8_keys_unchanged():
    s = foundry.summarize_skipped_tests(
        product="p", files_scanned=2, findings=(("t.py", "test_a"),), parse_errors=())
    d = s.to_dict()
    assert len(d) == 8, f"SkippedTestSummary.to_dict must still have 8 keys: {list(d)}"
    assert list(d.keys()) == [
        "product", "files_scanned", "total_findings", "clean",
        "exit_code", "verdict", "findings", "parse_errors",
    ]


def test_b8_control_path_and_guard_scripts_byte_unchanged():
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
def test_b8_overlap_not_disjoint_skipped_can_also_be_assertionless():
    # THE iter-54 DIVERGENCE, re-derived from observed behaviour: unlike
    # constant-asserts (DISJOINT from weak-tests by construction), an ALWAYS-SKIPPED
    # test CAN ALSO be assertion-free, so company-skipped-tests findings CAN OVERLAP
    # company-weak-tests. Prove it at the detector level (both detectors flag the
    # SAME synthetic test) rather than copying a "disjoint" claim.
    src = (
        "import pytest\n"
        "@pytest.mark.skip\n"
        "def test_over():\n"
        "    x = 1\n"  # assertion-free AND unconditionally skipped
    )
    skipped = foundry.find_always_skipped_tests(src)
    assertionless = foundry.find_assertionless_tests(src)
    assert "test_over" in skipped, \
        "an unconditionally @skip-decorated test must be an always-skipped finding"
    assert "test_over" in assertionless, \
        "the same test is ALSO assertion-free -> the two lenses genuinely OVERLAP"


def test_b8_shipped_public_files_scan_clean_and_no_home_path():
    if not (_LEAK_GUARD.exists() and _DENYLIST.exists()):
        pytest.skip("leak-guard not present in this repo (repo-agnostic)")
    lg = _load_leak_guard()
    patterns = lg.load_denylist(_DENYLIST.read_text())  # API takes TEXT, not a Path
    home_prefix = "/" + "Users" + "/"  # built at runtime; never a source literal
    # liveness: the denylist is a LIVE matcher, not inert
    assert len(lg.scan_text(home_prefix + "somebody/x", patterns)) >= 1, \
        "denylist appears inert (a home-path probe did not match)"
    for rel in ("tests/test_iter57_behavior.py", "README.md", "PLATFORM_ROADMAP.md"):
        p = _ROOT / rel
        if not p.exists():
            continue
        txt = p.read_text()
        assert len(lg.scan_text(txt, patterns)) == 0, \
            f"{rel} contains a denylisted token (would BLOCK this iteration's ship)"
        assert home_prefix not in txt, f"{rel} contains an absolute home-directory path"


def test_b8_live_smoke_on_real_dispatch_config():
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
