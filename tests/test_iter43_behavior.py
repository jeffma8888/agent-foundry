"""Black-box behaviour tests for iter 43 -- `foundry company-weak-tests` BITE 2
(the CLI + core that COMPLETES the feature): a read-only, offline company-wide
roll-up that folds every ENABLED dispatch team's iter-22 assertion-free-test
scan into ONE report + a scriptable GATE exit code, composed on top of the
iter-42 `gather_weak_tests` seam + the iter-22 frozen `WeakTestSummary`. The 4th
`company-*` family member, after `company-status` (iter 30) / `company-history`
(iter 31) / `company-timing` (iter 40). UNLIKE the informational history/timing
roll-ups, `company-weak-tests` GATES on findings/parse-errors (a worthless test
or an unparseable file ANYWHERE -> exit 1). ALL additive in foundry.py:

  * a FROZEN dataclass `CompanyWeakTests(dispatch_path, products, disabled,
    errors)` with `n_*` count props + `files_scanned`/`total_findings`/
    `total_parse_errors`/`n_flagged` company sums + findings-GATING
    `exit_code`/`verdict` + `render()` + `to_dict()`,
  * a PURE keyword-only `summarize_company_weak_tests(*, dispatch_path, products,
    disabled, errors) -> CompanyWeakTests`,
  * a thin resilient `company_weak_tests_cli(dispatch_path, as_json=False) -> int`
    wired to a new argparse subcommand `company-weak-tests` (NO `--limit`),
    reusing the iter-30 `parse_dispatch_work_items` + the iter-42
    `gather_weak_tests` + iter-22 `WeakTestSummary` seams.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-43 PM
spec's Expected Behaviors (1-8), the product README/roadmap, the `tests/`
conventions (esp. tests/test_iter40_behavior.py -- the structural mirror -- and
test_iter42_behavior.py -- the `gather_weak_tests` foundation), and the
product's own OBSERVABLE behaviour (building the public objects and RUNNING them
/ `--help`). The implementation SOURCE (foundry.py / dispatcher.py source text),
the engineer's & reviewer's notes, and `git diff` were NOT read. Every check
drives the PUBLIC interface: the pure fn via
`foundry.summarize_company_weak_tests(...)`, the dataclass via
`foundry.CompanyWeakTests(...)` / `foundry.WeakTestSummary(...)`
(via `summarize_weak_tests`), and the CLI via
`foundry.main(["company-weak-tests", ...])` / `foundry.company_weak_tests_cli(...)`
against tiny dispatch/product JSON files in `tmp_path`, monkeypatching
`foundry.load_config` / `foundry.gather_weak_tests`. The real product repos /
state / git / network are NEVER touched (except the read-only import + `--help`
regression probes + an opt-in, auto-skipping live smoke). Fully offline &
deterministic.
"""
import dataclasses
import io
import json
import pathlib
import subprocess
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# fixed exit-code <-> verdict mapping asserted throughout (Behavior 2)
_VERDICT_FOR_CODE = {0: "clean", 1: "ATTENTION", 2: "no enabled products"}

# the genuinely-NEW iter-43 symbols
NEW_SYMBOLS = ("CompanyWeakTests", "summarize_company_weak_tests",
               "company_weak_tests_cli")
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")


# --------------------------------------------------------------------------
# helpers  (mirror tests/test_iter40_behavior.py + test_iter42_behavior.py)
# --------------------------------------------------------------------------
def _ws(product, files_scanned, findings=(), parse_errors=()):
    """Build a WeakTestSummary via the shipped iter-22 pure factory."""
    return foundry.summarize_weak_tests(
        product=product, files_scanned=files_scanned,
        findings=tuple(findings), parse_errors=tuple(parse_errors))


def _run_cli(argv):
    """Drive foundry.main capturing (rc, stdout+stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue() + err.getvalue()


def _run_cwt(dispatch_path, as_json=False):
    """Drive company_weak_tests_cli directly, capturing (rc, stdout+stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.company_weak_tests_cli(dispatch_path, as_json=as_json)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue() + err.getvalue()


def _snapshot_tree(root):
    """Map {relative-path: bytes} for every file under root (no-write proof)."""
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*") if p.is_file()
    }


def _write_dispatch(tmp_path, work_items, name="foundry.config.json"):
    """Write a minimal DISPATCH config (a `work_items` list) to tmp."""
    p = pathlib.Path(tmp_path) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"work_items": work_items}))
    return p


def _final_verdict_token(text):
    """Return the token after the final `verdict:` line."""
    lines = [ln for ln in text.splitlines()
             if ln.strip().lower().startswith("verdict:")]
    assert lines, f"no `verdict:` line found in:\n{text}"
    return lines[-1].split(":", 1)[1].strip()


def _product_line(text, product):
    """The single `  - {product}:` line from a render()."""
    rows = [ln for ln in text.splitlines()
            if ln.strip().startswith(f"- {product}:")]
    assert len(rows) == 1, \
        f"expected exactly one line for {product!r}, got {rows!r}\n{text}"
    return rows[0]


def _patch_cli(monkeypatch, ws_by_name):
    """Monkeypatch load_config (returns a cfg tagged with the resolved path,
    recording every load path) and gather_weak_tests (returns a WeakTestSummary
    by matching a product-name substring of the config path)."""
    loaded = []

    class _Cfg:
        def __init__(self, path):
            self._path = path

    def fake_load(path):
        loaded.append(path)
        return _Cfg(path)

    def fake_gather(cfg, files=None):
        for name, ws in ws_by_name.items():
            if name in cfg._path:
                return ws
        return _ws("unknown", 1)

    monkeypatch.setattr(foundry, "load_config", fake_load)
    monkeypatch.setattr(foundry, "gather_weak_tests", fake_gather)
    return loaded


def _fn_names_consts(fn):
    """Recursively gather (co_names set, str-consts set) reachable from fn's
    compiled code object -- public runtime introspection, not source text."""
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


# ==========================================================================
# Behavior 1 -- CompanyWeakTests company sums (frozen dataclass + counts)
# ==========================================================================
def test_b1_company_sums_and_counts_worked_example():
    # the spec's exact worked example
    pA = _ws("alpha", 3, findings=(("a.py", "test_x"),), parse_errors=())
    pB = _ws("beta", 2, findings=(), parse_errors=(("b.py", "SyntaxError: bad"),))
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d/fc.json", products=(pA, pB),
        disabled=("gamma", "delta"), errors=(("eps", "boom"),))
    assert dataclasses.is_dataclass(cwt)
    assert type(cwt).__name__ == "CompanyWeakTests"
    assert cwt.dispatch_path == "/d/fc.json"
    assert cwt.products == (pA, pB) and cwt.disabled == ("gamma", "delta")
    assert cwt.errors == (("eps", "boom"),)
    # company sums are the per-product sums (the spec's worked example)
    assert cwt.files_scanned == 5 == sum(p.files_scanned for p in cwt.products)
    assert cwt.total_findings == 1 == sum(p.total_findings for p in cwt.products)
    assert cwt.total_parse_errors == 1 == sum(len(p.parse_errors) for p in cwt.products)
    # n_flagged: products with findings OR non-empty parse_errors
    assert cwt.n_flagged == 2
    # n_* are the lengths of the tuples
    assert cwt.n_products == 2 == len(cwt.products)
    assert cwt.n_disabled == 2 == len(cwt.disabled)
    assert cwt.n_errors == 1 == len(cwt.errors)


def test_b1_companyweaktests_is_frozen():
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d", products=(_ws("a", 1),), disabled=(), errors=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        cwt.dispatch_path = "/other"


def test_b1_n_flagged_counts_findings_or_parse_errors_only():
    p_find = _ws("f", 2, findings=(("x.py", "test_x"),))       # flagged (findings)
    p_parse = _ws("p", 2, parse_errors=(("y.py", "SyntaxError: y"),))  # flagged (parse err)
    p_clean = _ws("c", 5)                                      # NOT flagged
    p_zero = _ws("z", 0)                                       # NOT flagged (no files)
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d", products=(p_find, p_parse, p_clean, p_zero),
        disabled=(), errors=())
    assert cwt.n_products == 4
    assert cwt.n_flagged == 2, \
        "only products with findings OR parse-errors are flagged (not clean/zero-file)"
    assert cwt.files_scanned == 2 + 2 + 5 + 0 == 9
    assert cwt.total_findings == 1
    assert cwt.total_parse_errors == 1


def test_b1_empty_products_sums_are_zero():
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d", products=(), disabled=(), errors=())
    assert cwt.files_scanned == 0 and cwt.total_findings == 0
    assert cwt.total_parse_errors == 0 and cwt.n_flagged == 0
    assert cwt.n_products == 0 and cwt.n_disabled == 0 and cwt.n_errors == 0


# ==========================================================================
# Behavior 2 -- exit_code / verdict GATE on findings/parse-errors/errors
# ==========================================================================
def test_b2_all_clean_exit0():
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d", products=(_ws("a", 5),), disabled=(), errors=())
    assert cwt.exit_code == 0 and cwt.verdict == "clean"


def test_b2_findings_gate_exit1():
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d",
        products=(_ws("a", 3, findings=(("t.py", "test_a"),)),),
        disabled=(), errors=())
    assert cwt.total_findings == 1
    assert cwt.exit_code == 1 and cwt.verdict == "ATTENTION"


def test_b2_parse_errors_gate_exit1():
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d",
        products=(_ws("a", 1, parse_errors=(("t.py", "SyntaxError: bad"),)),),
        disabled=(), errors=())
    assert cwt.total_parse_errors == 1
    assert cwt.exit_code == 1 and cwt.verdict == "ATTENTION"


def test_b2_structural_errors_gate_exit1():
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d", products=(_ws("a", 5),),
        disabled=(), errors=(("boom", "load failed"),))
    assert cwt.exit_code == 1 and cwt.verdict == "ATTENTION"


def test_b2_no_products_no_errors_exit2():
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d", products=(), disabled=("x", "y"), errors=())
    assert cwt.exit_code == 2 and cwt.verdict == "no enabled products"


def test_b2_errors_without_products_is_attention_not_noproducts():
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d", products=(), disabled=(), errors=(("z", "bad"),))
    assert cwt.exit_code == 1 and cwt.verdict == "ATTENTION", \
        "a structural error must gate to 1 even with zero products"


def test_b2_zero_file_product_does_not_force_exit2():
    # a gathered product that scanned ZERO test files (its own exit_code == 2)
    # still COUNTS as a product; with no findings/parse-errors/errors the
    # company exits 0 clean (mirroring iter-40 company-timing).
    zf = _ws("zf", 0)
    assert zf.exit_code == 2, "sanity: a zero-file WeakTestSummary is itself exit 2"
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d", products=(zf,), disabled=(), errors=())
    assert cwt.n_products == 1 and cwt.files_scanned == 0
    assert cwt.exit_code == 0 and cwt.verdict == "clean", \
        "a product with no scanned files must NOT force company exit 2"


def test_b2_verdict_matches_fixed_mapping():
    for products, errors, code in (
        ((_ws("a", 5),), (), 0),
        ((_ws("a", 3, findings=(("t.py", "test_a"),)),), (), 1),
        ((_ws("a", 5),), (("e", "m"),), 1),
        ((), (), 2),
    ):
        cwt = foundry.summarize_company_weak_tests(
            dispatch_path="/d", products=products, disabled=(), errors=errors)
        assert cwt.verdict == _VERDICT_FOR_CODE[cwt.exit_code] == _VERDICT_FOR_CODE[code]


# ==========================================================================
# Behavior 3 -- render() substrings (human report)
# ==========================================================================
def test_b3_render_contains_header_path_counts_rollup_and_verdict():
    pA = _ws("alpha", 3, findings=(("a.py", "test_x"),))
    pB = _ws("beta", 2, parse_errors=(("b.py", "SyntaxError: bad"),))
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d/fc.json", products=(pA, pB),
        disabled=("gone",), errors=(("errp", "boom msg"),))
    r = cwt.render()
    assert "foundry company-weak-tests" in r
    assert "/d/fc.json" in r, "render must contain the dispatch path"
    # counts line
    assert f"{cwt.n_products} gathered" in r
    assert f"{cwt.n_disabled} disabled" in r
    assert f"{cwt.n_errors} error" in r
    # company rollup
    assert f"{cwt.files_scanned} files scanned" in r
    assert f"{cwt.total_findings} assertion-free tests" in r
    assert f"{cwt.total_parse_errors} parse errors" in r
    # final verdict line
    assert _final_verdict_token(r) == cwt.verdict == "ATTENTION"


def test_b3_render_one_line_per_gathered_product_with_own_counts():
    pA = _ws("alpha", 3, findings=(("a.py", "test_x"), ("a2.py", "test_y")))
    pB = _ws("beta", 2, parse_errors=(("b.py", "SyntaxError: bad"),))
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d", products=(pA, pB), disabled=(), errors=())
    la = _product_line(cwt.render(), "alpha")
    assert f"{pA.files_scanned} files scanned" in la
    assert f"{pA.total_findings} assertion-free" in la
    assert f"{len(pA.parse_errors)} parse error" in la
    lb = _product_line(cwt.render(), "beta")
    assert f"{pB.files_scanned} files scanned" in lb
    assert f"{pB.total_findings} assertion-free" in lb
    assert f"{len(pB.parse_errors)} parse error" in lb


def test_b3_render_disabled_and_error_lines():
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d", products=(_ws("okp", 5),),
        disabled=("dis1", "dis2"), errors=(("errp", "kaboom message here"),))
    lines = cwt.render().splitlines()
    for name in ("dis1", "dis2"):
        assert any(name in ln and "disabled" in ln for ln in lines), \
            f"missing disabled line for {name!r}:\n{cwt.render()}"
    assert any("errp" in ln and "ERROR" in ln and "kaboom message here" in ln
               for ln in lines), \
        f"missing error line (name+ERROR+message):\n{cwt.render()}"


def test_b3_render_does_not_leak_per_finding_leaf_detail():
    # per-product COUNTS only, NOT each (file :: test) finding (bounded report)
    pA = _ws("alpha", 3, findings=(("secretfile.py", "test_secretfn"),),
             parse_errors=(("crashfile.py", "SyntaxError: secretmsg"),))
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d", products=(pA,), disabled=(), errors=())
    r = cwt.render()
    assert "secretfile.py" not in r and "test_secretfn" not in r, \
        "render() must NOT list individual (file :: test) findings (counts only)"
    assert "crashfile.py" not in r and "secretmsg" not in r, \
        "render() must NOT list individual parse-error leaves (counts only)"


def test_b3_render_is_deterministic():
    pA = _ws("alpha", 3, findings=(("a.py", "test_x"),))
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d", products=(pA,), disabled=("d",), errors=(("e", "m"),))
    assert cwt.render() == cwt.render(), "render() must be deterministic"


# ==========================================================================
# Behavior 4 -- to_dict() JSON-safe, reuses frozen props, full per-product detail
# ==========================================================================
def test_b4_to_dict_keys_roundtrip_and_values():
    pA = _ws("alpha", 3, findings=(("a.py", "test_x"),))
    pB = _ws("beta", 2, parse_errors=(("b.py", "SyntaxError: bad"),))
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d/fc.json", products=(pA, pB),
        disabled=("gamma",), errors=(("eps", "boom"),))
    d = cwt.to_dict()
    assert json.loads(json.dumps(d)) == d, "to_dict must survive a JSON round-trip"
    expected_keys = {
        "dispatch_config", "products", "disabled", "errors",
        "n_products", "n_disabled", "n_errors", "n_flagged",
        "files_scanned", "total_findings", "total_parse_errors",
        "exit_code", "verdict",
    }
    assert expected_keys <= set(d), f"missing keys: {expected_keys - set(d)}"
    assert d["dispatch_config"] == "/d/fc.json" == cwt.dispatch_path
    assert d["disabled"] == ["gamma"]
    assert d["errors"] == [{"product": "eps", "message": "boom"}]
    # every derived value EQUALS the frozen prop -> payload can't disagree
    assert (d["n_products"], d["n_disabled"], d["n_errors"], d["n_flagged"]) == \
        (cwt.n_products, cwt.n_disabled, cwt.n_errors, cwt.n_flagged) == (2, 1, 1, 2)
    assert (d["files_scanned"], d["total_findings"], d["total_parse_errors"]) == \
        (cwt.files_scanned, cwt.total_findings, cwt.total_parse_errors) == (5, 1, 1)
    assert d["exit_code"] == cwt.exit_code == 1
    assert d["verdict"] == cwt.verdict == "ATTENTION"


def test_b4_to_dict_products_carry_full_per_product_leaf_detail():
    pA = _ws("alpha", 3, findings=(("a.py", "test_x"),))
    pB = _ws("beta", 2, parse_errors=(("b.py", "SyntaxError: bad"),))
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d", products=(pA, pB), disabled=(), errors=())
    d = cwt.to_dict()
    assert d["products"] == [pA.to_dict(), pB.to_dict()], \
        "products must be each gathered WeakTestSummary.to_dict() IN ORDER"
    # the full 8-key per-product payload, INCLUDING the findings/parse_errors leaves
    assert len(d["products"][0]) == 8
    assert d["products"][0]["findings"], "per-product findings leaf must survive in to_dict"
    assert d["products"][1]["parse_errors"], "per-product parse_errors leaf must survive"


def test_b4_to_dict_all_empty_serializes_without_raising():
    cwt = foundry.summarize_company_weak_tests(
        dispatch_path="/d", products=(), disabled=(), errors=())
    d = cwt.to_dict()
    js = json.loads(json.dumps(d))  # must not raise, even fully empty
    assert js["products"] == [] and js["disabled"] == [] and js["errors"] == []
    assert js["files_scanned"] == 0 and js["total_findings"] == 0
    assert js["exit_code"] == 2 and js["verdict"] == "no enabled products"


# ==========================================================================
# Behavior 5 -- company_weak_tests_cli rolls up enabled; disabled skipped;
#               {FOUNDRY} substituted; bare-name seams bite
# ==========================================================================
def test_b5_enabled_gathered_disabled_recorded_never_loaded(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": False},
    ])
    loaded = _patch_cli(monkeypatch, {"alpha": _ws("alpha", 3, findings=(("a.py", "t"),))})
    rc, out = _run_cwt(str(disp))
    assert rc == 1, "a gathered team with a finding must make the company exit 1"
    assert loaded == [str(tmp_path / "alpha.json")], \
        "only the ENABLED item is load_config'd; the disabled item is never loaded"
    assert "alpha" in out
    assert any("beta" in ln and "disabled" in ln for ln in out.splitlines()), \
        "the disabled item must still be listed as disabled"


def test_b5_clean_enabled_team_exits_0(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _ws("alpha", 5)})
    rc, out = _run_cwt(str(disp))
    assert rc == 0, "a clean gathered team must exit 0"
    assert _final_verdict_token(out) == "clean"


def test_b5_foundry_token_substituted_before_load(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": "{FOUNDRY}/products/alpha/config.json",
         "enabled": True},
    ])
    loaded = _patch_cli(monkeypatch, {"alpha": _ws("alpha", 3)})
    _run_cwt(str(disp))
    froot = str(pathlib.Path(foundry.__file__).resolve().parent)
    assert loaded == [f"{froot}/products/alpha/config.json"], \
        f"{{FOUNDRY}} must be substituted to the foundry root before load: {loaded}"
    assert "{FOUNDRY}" not in "".join(loaded)


def test_b5_gather_called_with_cfg_via_bare_name_seam(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    seen_cfgs = []
    monkeypatch.setattr(foundry, "load_config",
                        lambda p: type("C", (), {"_path": p})())

    def fake_gather(cfg, files=None):
        seen_cfgs.append(cfg._path)
        return _ws("x", 1)

    monkeypatch.setattr(foundry, "gather_weak_tests", fake_gather)
    _run_cwt(str(disp))
    assert seen_cfgs == [str(tmp_path / "alpha.json"), str(tmp_path / "beta.json")], \
        f"gather_weak_tests must be called (by bare name) per enabled cfg: {seen_cfgs}"


# ==========================================================================
# Behavior 6 -- resilience: no exception ever propagates
# ==========================================================================
def test_b6_missing_dispatch_file_exit1_no_raise(tmp_path):
    rc, out = _run_cwt(str(tmp_path / "does-not-exist.json"))
    assert rc == 1 and "ERROR" in out


def test_b6_invalid_json_exit1_no_raise(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json ]")
    rc, out = _run_cwt(str(bad))
    assert rc == 1 and "ERROR" in out


def test_b6_not_a_json_object_exit1(tmp_path):
    lst = tmp_path / "list.json"
    lst.write_text("[1, 2, 3]")
    rc, _ = _run_cwt(str(lst))
    assert rc == 1


def test_b6_synthetic_error_keyed_by_dispatch_path(tmp_path):
    missing = tmp_path / "nope.json"
    rc, out = _run_cwt(str(missing), as_json=True)
    doc = json.loads(out.strip())  # still exactly one parseable JSON doc
    assert rc == 1 and doc["exit_code"] == 1 and len(doc["errors"]) == 1
    assert doc["errors"][0]["product"] == str(missing), \
        f"the ONE synthetic error must be keyed by the dispatch path: {doc['errors']}"


def test_b6_one_bad_team_recorded_rollup_continues(tmp_path, monkeypatch):
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
        foundry, "gather_weak_tests",
        lambda cfg, files=None: _ws(
            "good" if "good.json" in cfg._path else "good2", 3))
    rc, out = _run_cwt(str(disp))
    assert rc == 1, "a failing work item must make the company exit 1"
    assert "bad" in out and "ERROR" in out and "kaboom loading bad" in out, \
        f"the failing item + its message must be recorded:\n{out}"
    assert "good" in out and "good2" in out, "gathering must CONTINUE past the failure"


def test_b6_gather_error_recorded_as_name_and_str_exc(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "boomp", "config": str(tmp_path / "boomp.json"), "enabled": True},
    ])
    monkeypatch.setattr(foundry, "load_config", lambda p: type("C", (), {})())

    def fake_gather(cfg, files=None):
        raise ValueError("gather blew up")

    monkeypatch.setattr(foundry, "gather_weak_tests", fake_gather)
    rc, out = _run_cwt(str(disp), as_json=True)
    doc = json.loads(out.strip())
    assert rc == 1 and doc["exit_code"] == 1
    assert {"product": "boomp", "message": "gather blew up"} in doc["errors"], \
        f"error must be recorded as (name, str(exc)): {doc['errors']}"


# ==========================================================================
# Behavior 7 -- --json parity + read-only
# ==========================================================================
def test_b7_json_is_single_indent2_document_same_exit(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _ws("alpha", 3, findings=(("a.py", "t"),)),
                             "beta": _ws("beta", 2)})
    rc_h, _ = _run_cwt(str(disp), as_json=False)
    rc_j, out_j = _run_cwt(str(disp), as_json=True)
    doc = json.loads(out_j.strip())  # exactly ONE parseable JSON document
    assert out_j.strip() == json.dumps(doc, indent=2), \
        "the --json path must print exactly one json.dumps(to_dict(), indent=2) doc"
    assert rc_j == rc_h == doc["exit_code"] == 1
    assert [p["product"] for p in doc["products"]] == ["alpha", "beta"]


def test_b7_human_path_prints_render(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    wsA = _ws("alpha", 3, findings=(("a.py", "t"),))
    wsB = _ws("beta", 2)
    _patch_cli(monkeypatch, {"alpha": wsA, "beta": wsB})
    rc, out = _run_cwt(str(disp), as_json=False)
    expected = foundry.summarize_company_weak_tests(
        dispatch_path=str(disp), products=(wsA, wsB), disabled=(), errors=())
    assert out.rstrip("\n") == expected.render().rstrip("\n"), \
        f"human path must print render():\n{out}"
    assert rc == expected.exit_code


def test_b7_read_only_writes_nothing_to_disk(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _ws("alpha", 3)})
    before = _snapshot_tree(tmp_path)
    _run_cwt(str(disp), as_json=False)
    _run_cwt(str(disp), as_json=True)
    assert _snapshot_tree(tmp_path) == before, \
        "company-weak-tests wrote to disk (must be read-only)"


# ==========================================================================
# Behavior 8 -- CLI wiring, read-only, off the control path
# ==========================================================================
def test_b8_subcommand_help_has_config_json_but_no_limit():
    out = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = out
    try:
        with pytest.raises(SystemExit) as ei:
            foundry.main(["company-weak-tests", "--help"])
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    assert ei.value.code == 0
    text = out.getvalue()
    assert "--config" in text and "--json" in text
    assert "--limit" not in text, "company-weak-tests must NOT expose a --limit flag"


def test_b8_default_config_is_repo_dispatch_config(monkeypatch):
    captured = {}

    def spy(dispatch_path, as_json=False):
        captured.update(dp=dispatch_path, js=as_json)
        return 0

    monkeypatch.setattr(foundry, "company_weak_tests_cli", spy)
    rc = foundry.main(["company-weak-tests"])
    assert rc == 0
    froot = pathlib.Path(foundry.__file__).resolve().parent
    assert captured["dp"] == str(froot / "foundry.config.json"), \
        "default --config must be the repo's DISPATCH config (foundry.config.json)"
    assert captured["js"] is False


def test_b8_json_flag_passes_through(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        foundry, "company_weak_tests_cli",
        lambda dp, as_json=False: captured.update(dp=dp, js=as_json) or 0)
    foundry.main(["company-weak-tests", "--json"])
    assert captured["js"] is True


def test_b8_dispatched_before_load_config(monkeypatch):
    monkeypatch.setattr(foundry, "company_weak_tests_cli",
                        lambda dp, as_json=False: 0)

    def boom(path):
        raise AssertionError(f"main called load_config(args.config)={path!r}")

    monkeypatch.setattr(foundry, "load_config", boom)
    assert foundry.main(["company-weak-tests", "--config", "whatever.json"]) == 0


def test_b8_both_modules_import():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"
    assert dispatcher is not None


def test_b8_new_surface_present_and_reuses_shipped_seams():
    for name in NEW_SYMBOLS:
        assert hasattr(foundry, name), f"missing new symbol {name!r}"
    assert callable(foundry.summarize_company_weak_tests)
    assert callable(foundry.company_weak_tests_cli)
    # SHIPPED seams REUSED, not re-added:
    for name in ("parse_dispatch_work_items", "gather_weak_tests", "WeakTestSummary",
                 "summarize_weak_tests", "weak_tests_cli",
                 "find_assertionless_tests", "_gather_weak_test_files"):
        assert hasattr(foundry, name), f"shipped seam {name!r} vanished"


def test_b8_new_symbols_absent_from_control_flow_and_dispatcher():
    for fn_name in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references new symbol {sym!r} (must stay off the control path)"
        assert "company-weak-tests" not in consts, \
            f"{fn_name} embeds the 'company-weak-tests' subcommand literal"
    # dispatcher must not reference any of the new company-weak-tests symbols
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    dnames, dconsts = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in dnames, f"dispatcher references {sym!r}"
    assert "company-weak-tests" not in dconsts, \
        "dispatcher references the 'company-weak-tests' literal"


def test_b8_weak_test_summary_to_dict_still_8_keys_unchanged():
    # bite 2 must NOT change the shipped iter-22 WeakTestSummary surface
    s = foundry.summarize_weak_tests(
        product="p", files_scanned=2, findings=(("t.py", "test_a"),), parse_errors=())
    d = s.to_dict()
    assert len(d) == 8, f"WeakTestSummary.to_dict must still have EXACTLY 8 keys: {list(d)}"
    assert list(d.keys()) == [
        "product", "files_scanned", "total_findings", "clean",
        "exit_code", "verdict", "findings", "parse_errors",
    ]


def test_b8_help_lists_company_weak_tests_after_siblings(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for sub in ("weak-tests", "company-status", "company-history",
                "company-timing", "company-weak-tests"):
        assert sub in out, f"subcommand {sub!r} missing from --help:\n{out}"


def test_b8_live_smoke_on_real_dispatch_config():
    froot = pathlib.Path(foundry.__file__).resolve().parent
    if not (froot / "foundry.config.json").exists():
        pytest.skip(
            "machine-local foundry.config.json absent at repo root (gitignored); "
            "live smoke needs the operator's real dispatch config"
        )
    rc_h, _ = _run_cli(["company-weak-tests"])
    rc_j, out_j = _run_cli(["company-weak-tests", "--json"])
    doc = json.loads(out_j.strip())  # ONE parseable JSON document
    assert rc_j == rc_h == doc["exit_code"], "json/human exit codes must agree"
    assert doc["verdict"] == _VERDICT_FOR_CODE[doc["exit_code"]]
