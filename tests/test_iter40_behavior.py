"""Black-box behaviour tests for iter 40 -- `foundry company-timing` BITE 2 (the
CLI + core that COMPLETES the feature): a read-only, offline company-wide roll-up
that folds every enabled dispatch team's iter-18 suite-wall-time DIGEST into ONE
report + a scriptable exit code, composed on top of the iter-39 foundation
(`gather_timing` + `TimingSummary.measured_seconds`). Third `company-*` member,
after `company-status` (iter 30) / `company-history` (iter 31). ALL additive in
foundry.py:

  * a FROZEN dataclass `CompanyTiming(dispatch_path, products, disabled, errors,
    threshold)` with `n_*` count props + `total`/`measured`/`count_slow` company
    sums + POOLED `min_seconds`/`max_seconds`/`avg_seconds` + `exit_code`/`verdict`
    + `render()` + `to_dict()` (NO company-level `last_seconds`),
  * a PURE keyword-only `summarize_company_timing(*, dispatch_path, products,
    disabled, errors, threshold) -> CompanyTiming`,
  * a `company_timing_cli(dispatch_path, limit=None, as_json=False) -> int` wired
    to a new argparse subcommand `company-timing`, reusing the iter-30
    `parse_dispatch_work_items` + the iter-39 `gather_timing`/`TimingSummary`
    + `SUITE_SLOW_SECONDS` (read at call time).

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-40 PM
spec's Expected Behaviors (1-10), the product README/roadmap, the `tests/`
conventions (esp. tests/test_iter31_behavior.py -- the structural mirror -- and
test_iter39_behavior.py -- the timing foundation), and the product's own
OBSERVABLE behaviour (building the public objects and RUNNING them / `--help`).
The implementation SOURCE (foundry.py / dispatcher.py source text), the
engineer's & reviewer's notes, and `git diff` were NOT read. Every check drives
the PUBLIC interface: the pure fn via `foundry.summarize_company_timing(...)`,
the dataclass via `foundry.CompanyTiming(...)` / `foundry.TimingSummary(...)`,
and the CLI via `foundry.main(["company-timing", ...])` /
`foundry.company_timing_cli(...)` against tiny dispatch/product JSON files in
`tmp_path`, monkeypatching `foundry.load_config` / `foundry.gather_timing` (the
real product repos / state / git / network are NEVER touched, except the
read-only import + `--help` regression probes). Fully offline & deterministic.
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


# fixed exit-code <-> verdict mapping asserted throughout (Behavior 3)
_VERDICT_FOR_CODE = {0: "OK", 1: "ERRORS", 2: "no enabled products"}

R = foundry.TimingRecord

# the genuinely-NEW iter-40 symbols
NEW_SYMBOLS = ("CompanyTiming", "summarize_company_timing", "company_timing_cli")
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")


# --------------------------------------------------------------------------
# helpers  (mirror tests/test_iter31_behavior.py + test_iter39_behavior.py)
# --------------------------------------------------------------------------
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


def _run_ctc(dispatch_path, limit=None, as_json=False):
    """Drive company_timing_cli directly, capturing (rc, stdout+stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.company_timing_cli(dispatch_path, limit=limit, as_json=as_json)
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


def _ts(product, seconds, threshold=25.0):
    """Build a TimingSummary with the given per-iteration seconds (None ==
    unmeasured) via the shipped iter-18/39 pure factory."""
    recs = [R(i + 1, s) for i, s in enumerate(seconds)]
    return foundry.summarize_timing(product=product, records=recs, threshold=threshold)


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
    assert len(rows) == 1, f"expected exactly one line for {product!r}, got {rows!r}\n{text}"
    return rows[0]


def _patch_cli(monkeypatch, ts_by_name):
    """Monkeypatch load_config (returns a cfg tagged with the resolved path,
    recording every load path) and gather_timing (returns a TimingSummary by
    matching a product-name substring of the config path)."""
    loaded = []

    class _Cfg:
        def __init__(self, path):
            self._path = path

    def fake_load(path):
        loaded.append(path)
        return _Cfg(path)

    def fake_gather(cfg, limit=None):
        for name, ts in ts_by_name.items():
            if name in cfg._path:
                return ts
        return _ts("unknown", [10.0])

    monkeypatch.setattr(foundry, "load_config", fake_load)
    monkeypatch.setattr(foundry, "gather_timing", fake_gather)
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
# Behavior 1 -- CompanyTiming company sums (frozen dataclass + counts)
# ==========================================================================
def test_b1_company_sums_and_counts():
    pA = _ts("alpha", [10.0, 30.0], threshold=25.0)      # measured 2, slow 1 (30>25)
    pB = _ts("beta", [None, 50.0], threshold=25.0)        # measured 1, slow 1 (50>25)
    ct = foundry.summarize_company_timing(
        dispatch_path="/d/fc.json", products=(pA, pB),
        disabled=("gamma", "delta"), errors=(("eps", "boom"),), threshold=25.0)
    assert dataclasses.is_dataclass(ct) and type(ct).__name__ == "CompanyTiming"
    assert ct.dispatch_path == "/d/fc.json"
    assert ct.products == (pA, pB) and ct.disabled == ("gamma", "delta")
    assert ct.errors == (("eps", "boom"),) and ct.threshold == 25.0
    # company sums are the per-product sums (the spec's worked example)
    assert ct.total == 4 == sum(p.total for p in ct.products)
    assert ct.measured == 3 == sum(p.measured for p in ct.products)
    assert ct.count_slow == 2 == sum(p.count_slow for p in ct.products), \
        "30.0 and 50.0 are strictly over the 25.0 threshold"
    # n_* are the lengths of the tuples
    assert ct.n_products == 2 == len(ct.products)
    assert ct.n_disabled == 2 == len(ct.disabled)
    assert ct.n_errors == 1 == len(ct.errors)


def test_b1_companytiming_is_frozen():
    ct = foundry.summarize_company_timing(
        dispatch_path="/d", products=(_ts("a", [10.0]),),
        disabled=(), errors=(), threshold=25.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ct.dispatch_path = "/other"


# ==========================================================================
# Behavior 2 -- pooled min/max/avg over ALL products' measured seconds
# ==========================================================================
def test_b2_pooled_min_max_avg():
    pA = _ts("alpha", [10.0, 30.0], threshold=25.0)
    pB = _ts("beta", [None, 50.0], threshold=25.0)
    ct = foundry.summarize_company_timing(
        dispatch_path="/d", products=(pA, pB), disabled=(), errors=(), threshold=25.0)
    # pool == [10.0, 30.0, 50.0]  (each product's measured_seconds, in order)
    assert ct.min_seconds == 10.0
    assert ct.max_seconds == 50.0
    assert ct.avg_seconds == 30.0 == sum([10.0, 30.0, 50.0]) / 3


def test_b2_pool_is_all_products_in_stored_order():
    pA = _ts("alpha", [5.0, 7.0], threshold=25.0)
    pB = _ts("beta", [1.0, 100.0], threshold=25.0)
    ct = foundry.summarize_company_timing(
        dispatch_path="/d", products=(pA, pB), disabled=(), errors=(), threshold=25.0)
    pool = list(pA.measured_seconds) + list(pB.measured_seconds)
    assert ct.min_seconds == min(pool) == 1.0
    assert ct.max_seconds == max(pool) == 100.0
    assert ct.avg_seconds == sum(pool) / len(pool)


def test_b2_no_measured_anywhere_all_none_and_no_company_last():
    pN = _ts("np", [None, None], threshold=25.0)
    ct = foundry.summarize_company_timing(
        dispatch_path="/d", products=(pN,), disabled=(), errors=(), threshold=25.0)
    assert ct.min_seconds is None and ct.max_seconds is None and ct.avg_seconds is None
    # spec: NO company-level last_seconds (ill-defined across teams)
    assert not hasattr(ct, "last_seconds"), \
        "CompanyTiming must NOT expose a company-level last_seconds"


# ==========================================================================
# Behavior 3 -- exit_code / verdict are errors-first, never gate on slow
# ==========================================================================
def test_b3_products_no_errors_exit0_ok():
    ct = foundry.summarize_company_timing(
        dispatch_path="/d", products=(_ts("a", [10.0]),),
        disabled=(), errors=(), threshold=25.0)
    assert ct.exit_code == 0 and ct.verdict == "OK"


def test_b3_errors_force_exit1_errors():
    ct = foundry.summarize_company_timing(
        dispatch_path="/d", products=(_ts("a", [10.0]),),
        disabled=(), errors=(("boom", "load failed"),), threshold=25.0)
    assert ct.exit_code == 1 and ct.verdict == "ERRORS"


def test_b3_no_products_no_errors_exit2():
    ct = foundry.summarize_company_timing(
        dispatch_path="/d", products=(), disabled=("x", "y"), errors=(), threshold=25.0)
    assert ct.exit_code == 2 and ct.verdict == "no enabled products"


def test_b3_errors_without_products_is_errors_not_noproducts():
    ct = foundry.summarize_company_timing(
        dispatch_path="/d", products=(), disabled=(), errors=(("z", "bad"),),
        threshold=25.0)
    assert ct.exit_code == 1 and ct.verdict == "ERRORS"


def test_b3_zero_measured_product_does_not_force_exit2():
    # a gathered product with ZERO measured timings still counts as a product
    ct = foundry.summarize_company_timing(
        dispatch_path="/d", products=(_ts("np", [None, None]),),
        disabled=(), errors=(), threshold=25.0)
    assert ct.n_products == 1 and ct.measured == 0
    assert ct.exit_code == 0 and ct.verdict == "OK", \
        "a product with no measured timings must NOT force exit 2"


def test_b3_all_slow_but_fixed_still_exit0():
    # timing is informational -- a company full of slow suites never gates
    pSlow = _ts("s", [999.0, 1000.0], threshold=25.0)
    ct = foundry.summarize_company_timing(
        dispatch_path="/d", products=(pSlow,), disabled=(), errors=(), threshold=25.0)
    assert ct.count_slow == 2 and ct.exit_code == 0 and ct.verdict == "OK", \
        "slow timings are informational -- must NOT gate the company exit code"


def test_b3_verdict_matches_fixed_mapping():
    for products, errors, code in (
        ((_ts("a", [10.0]),), (), 0),
        ((_ts("a", [10.0]),), (("e", "m"),), 1),
        ((), (), 2),
    ):
        ct = foundry.summarize_company_timing(
            dispatch_path="/d", products=products, disabled=(), errors=errors,
            threshold=25.0)
        assert ct.verdict == _VERDICT_FOR_CODE[ct.exit_code] == _VERDICT_FOR_CODE[code]


# ==========================================================================
# Behavior 4 -- render() substrings (human report)
# ==========================================================================
def test_b4_render_contains_header_path_counts_rollup_and_verdict():
    pA = _ts("alpha", [10.0, 30.0], threshold=25.0)
    pB = _ts("beta", [None, 50.0], threshold=25.0)
    ct = foundry.summarize_company_timing(
        dispatch_path="/d/fc.json", products=(pA, pB),
        disabled=("gone",), errors=(("errp", "boom msg"),), threshold=25.0)
    r = ct.render()
    assert "foundry company-timing" in r
    assert "/d/fc.json" in r, "render must contain the dispatch path"
    # counts line
    assert f"{ct.n_products} gathered" in r
    assert f"{ct.n_disabled} disabled" in r
    assert f"{ct.n_errors} error" in r
    # company rollup (measured > 0)
    assert f"measured {ct.measured}/{ct.total}" in r
    assert f"min {ct.min_seconds:.2f}s" in r
    assert f"max {ct.max_seconds:.2f}s" in r
    assert f"avg {ct.avg_seconds:.2f}s" in r
    assert f"slow (>{ct.threshold:.2f}s): {ct.count_slow}" in r
    # final verdict line
    assert _final_verdict_token(r) == ct.verdict == "ERRORS"


def test_b4_render_one_line_per_gathered_product_with_own_digest():
    pA = _ts("alpha", [10.0, 30.0], threshold=25.0)
    pB = _ts("beta", [None, 50.0], threshold=25.0)
    ct = foundry.summarize_company_timing(
        dispatch_path="/d", products=(pA, pB), disabled=(), errors=(), threshold=25.0)
    la = _product_line(ct.render(), "alpha")
    assert f"measured {pA.measured}/{pA.total}" in la
    assert f"min {pA.min_seconds:.2f}s" in la
    assert f"max {pA.max_seconds:.2f}s" in la
    assert f"avg {pA.avg_seconds:.2f}s" in la
    assert f"last {pA.last_seconds:.2f}s" in la
    assert f"slow: {pA.count_slow}" in la
    lb = _product_line(ct.render(), "beta")
    assert f"measured {pB.measured}/{pB.total}" in lb
    assert f"last {pB.last_seconds:.2f}s" in lb


def test_b4_render_product_with_no_measured_timings_line():
    pN = _ts("np", [None, None], threshold=25.0)
    pM = _ts("mp", [12.0], threshold=25.0)
    ct = foundry.summarize_company_timing(
        dispatch_path="/d", products=(pN, pM), disabled=(), errors=(), threshold=25.0)
    ln = _product_line(ct.render(), "np")
    assert "measured 0/2" in ln
    assert "no measured timings yet" in ln, \
        "a product with no measured timings shows the literal sentinel"
    # the measured digest markers must be absent for a no-timings product
    assert "avg " not in ln and "slow:" not in ln


def test_b4_render_disabled_and_error_lines():
    ct = foundry.summarize_company_timing(
        dispatch_path="/d", products=(_ts("okp", [10.0]),),
        disabled=("dis1", "dis2"), errors=(("errp", "kaboom message here"),),
        threshold=25.0)
    lines = ct.render().splitlines()
    for name in ("dis1", "dis2"):
        assert any(name in ln and "disabled" in ln for ln in lines), \
            f"missing disabled line for {name!r}:\n{ct.render()}"
    assert any("errp" in ln and "ERROR" in ln and "kaboom message here" in ln
               for ln in lines), f"missing error line (name+ERROR+message):\n{ct.render()}"


def test_b4_render_is_deterministic():
    pA = _ts("alpha", [10.0, 30.0], threshold=25.0)
    ct = foundry.summarize_company_timing(
        dispatch_path="/d", products=(pA,), disabled=("d",), errors=(("e", "m"),),
        threshold=25.0)
    assert ct.render() == ct.render(), "render() must be deterministic"


# ==========================================================================
# Behavior 5 -- render() nothing-measured rollup
# ==========================================================================
def test_b5_render_nothing_measured_rollup():
    pN = _ts("np", [None, None], threshold=25.0)
    ct = foundry.summarize_company_timing(
        dispatch_path="/d", products=(pN,), disabled=(), errors=(), threshold=25.0)
    r = ct.render()
    assert "no measured timings yet" in r
    # no min/max/avg company substrings when nothing is measured
    assert "min " not in r and "max " not in r and "avg " not in r, \
        f"nothing-measured rollup must carry no min/max/avg:\n{r}"
    assert ct.exit_code == 0


# ==========================================================================
# Behavior 6 -- to_dict() JSON-safe, reuses frozen props
# ==========================================================================
def test_b6_to_dict_keys_roundtrip_and_values():
    pA = _ts("alpha", [10.0, 30.0], threshold=25.0)
    pB = _ts("beta", [None, 50.0], threshold=25.0)
    ct = foundry.summarize_company_timing(
        dispatch_path="/d/fc.json", products=(pA, pB),
        disabled=("gamma",), errors=(("eps", "boom"),), threshold=25.0)
    d = ct.to_dict()
    assert json.loads(json.dumps(d)) == d, "to_dict must survive a JSON round-trip"
    expected_keys = {
        "dispatch_config", "products", "disabled", "errors",
        "n_products", "n_disabled", "n_errors",
        "total", "measured", "count_slow",
        "min_seconds", "max_seconds", "avg_seconds",
        "threshold", "exit_code", "verdict",
    }
    assert expected_keys <= set(d), f"missing keys: {expected_keys - set(d)}"
    assert d["dispatch_config"] == "/d/fc.json" == ct.dispatch_path
    assert d["products"] == [p.to_dict() for p in (pA, pB)], \
        "products must be each gathered TimingSummary.to_dict() IN ORDER"
    assert d["disabled"] == ["gamma"]
    assert d["errors"] == [{"product": "eps", "message": "boom"}]
    # every derived value EQUALS the frozen prop -> payload can't disagree
    assert (d["n_products"], d["n_disabled"], d["n_errors"]) == \
        (ct.n_products, ct.n_disabled, ct.n_errors) == (2, 1, 1)
    assert (d["total"], d["measured"], d["count_slow"]) == \
        (ct.total, ct.measured, ct.count_slow) == (4, 3, 2)
    assert (d["min_seconds"], d["max_seconds"], d["avg_seconds"]) == \
        (ct.min_seconds, ct.max_seconds, ct.avg_seconds) == (10.0, 50.0, 30.0)
    assert d["threshold"] == ct.threshold == 25.0
    assert d["exit_code"] == ct.exit_code == 1
    assert d["verdict"] == ct.verdict == "ERRORS"


def test_b6_to_dict_nothing_measured_serializes_null():
    pN = _ts("np", [None], threshold=25.0)
    ct = foundry.summarize_company_timing(
        dispatch_path="/d", products=(pN,), disabled=(), errors=(), threshold=25.0)
    d = ct.to_dict()
    js = json.loads(json.dumps(d))
    assert js["min_seconds"] is None
    assert js["max_seconds"] is None
    assert js["avg_seconds"] is None
    assert js["exit_code"] == 0 and js["verdict"] == "OK"


# ==========================================================================
# Behavior 7 -- company_timing_cli rolls up enabled teams; disabled skipped;
#               --limit flows through; {FOUNDRY} substituted; threshold at call
# ==========================================================================
def test_b7_enabled_gathered_disabled_recorded_never_loaded(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": False},
    ])
    loaded = _patch_cli(monkeypatch, {"alpha": _ts("alpha", [10.0, 30.0])})
    rc, out = _run_ctc(str(disp))
    assert rc == 0
    assert loaded == [str(tmp_path / "alpha.json")], \
        "only the ENABLED item is load_config'd; the disabled item is never loaded"
    assert "alpha" in out
    assert any("beta" in ln and "disabled" in ln for ln in out.splitlines()), \
        "the disabled item must still be listed as disabled"


def test_b7_limit_flows_to_every_gather_call(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    seen = []
    monkeypatch.setattr(foundry, "load_config",
                        lambda p: type("C", (), {"_path": p})())

    def fake_gather(cfg, limit=None):
        seen.append(limit)
        return _ts("x", [10.0])

    monkeypatch.setattr(foundry, "gather_timing", fake_gather)
    _run_ctc(str(disp), limit=3)
    assert seen == [3, 3], f"--limit must flow to EACH gather_timing call: {seen}"


def test_b7_foundry_token_substituted_before_load(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": "{FOUNDRY}/products/alpha/config.json",
         "enabled": True},
    ])
    loaded = _patch_cli(monkeypatch, {"alpha": _ts("alpha", [10.0])})
    _run_ctc(str(disp))
    froot = str(pathlib.Path(foundry.__file__).resolve().parent)
    assert loaded == [f"{froot}/products/alpha/config.json"], \
        f"{{FOUNDRY}} must be substituted to the foundry root before load: {loaded}"
    assert "{FOUNDRY}" not in "".join(loaded)


def test_b7_company_threshold_read_from_suite_slow_seconds_at_call_time(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _ts("alpha", [10.0])})
    monkeypatch.setattr(foundry, "SUITE_SLOW_SECONDS", 7.5)
    _, out = _run_ctc(str(disp), as_json=True)
    doc = json.loads(out.strip())
    assert doc["threshold"] == 7.5, \
        "the company threshold must be read from SUITE_SLOW_SECONDS at call time"


# ==========================================================================
# Behavior 8 -- resilience: no exception ever propagates
# ==========================================================================
def test_b8_missing_dispatch_file_exit1_no_raise(tmp_path):
    rc, out = _run_ctc(str(tmp_path / "does-not-exist.json"))
    assert rc == 1 and "ERROR" in out


def test_b8_invalid_json_exit1_no_raise(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json ]")
    rc, out = _run_ctc(str(bad))
    assert rc == 1 and "ERROR" in out


def test_b8_not_a_json_object_exit1(tmp_path):
    lst = tmp_path / "list.json"
    lst.write_text("[1, 2, 3]")
    rc, _ = _run_ctc(str(lst))
    assert rc == 1


def test_b8_synthetic_error_keyed_by_dispatch_path(tmp_path):
    missing = tmp_path / "nope.json"
    rc, out = _run_ctc(str(missing), as_json=True)
    doc = json.loads(out.strip())  # still exactly one parseable JSON doc
    assert rc == 1 and doc["exit_code"] == 1 and len(doc["errors"]) == 1
    assert doc["errors"][0]["product"] == str(missing), \
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
        foundry, "gather_timing",
        lambda cfg, limit=None: _ts(
            "good" if "good.json" in cfg._path else "good2", [10.0]))
    rc, out = _run_ctc(str(disp))
    assert rc == 1, "a failing work item must make the company exit 1"
    assert "bad" in out and "ERROR" in out and "kaboom loading bad" in out, \
        f"the failing item + its message must be recorded:\n{out}"
    assert "good" in out and "good2" in out, "gathering must CONTINUE past the failure"


def test_b8_gather_error_recorded_as_name_and_str_exc(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "boomp", "config": str(tmp_path / "boomp.json"), "enabled": True},
    ])
    monkeypatch.setattr(foundry, "load_config", lambda p: type("C", (), {})())

    def fake_gather(cfg, limit=None):
        raise ValueError("gather blew up")

    monkeypatch.setattr(foundry, "gather_timing", fake_gather)
    rc, out = _run_ctc(str(disp), as_json=True)
    doc = json.loads(out.strip())
    assert rc == 1 and doc["exit_code"] == 1
    assert {"product": "boomp", "message": "gather blew up"} in doc["errors"], \
        f"error must be recorded as (name, str(exc)): {doc['errors']}"


# ==========================================================================
# Behavior 9 -- --json parity + read-only
# ==========================================================================
def test_b9_json_is_single_indent2_document_same_exit(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _ts("alpha", [10.0, 30.0]),
                             "beta": _ts("beta", [None, 50.0])})
    rc_h, _ = _run_ctc(str(disp), as_json=False)
    rc_j, out_j = _run_ctc(str(disp), as_json=True)
    doc = json.loads(out_j.strip())  # exactly ONE parseable JSON document
    assert out_j.strip() == json.dumps(doc, indent=2), \
        "the --json path must print exactly one json.dumps(to_dict(), indent=2) doc"
    assert rc_j == rc_h == doc["exit_code"] == 0
    assert [p["product"] for p in doc["products"]] == ["alpha", "beta"]


def test_b9_human_path_prints_render(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    tsA = _ts("alpha", [10.0, 30.0])
    tsB = _ts("beta", [None, 50.0])
    _patch_cli(monkeypatch, {"alpha": tsA, "beta": tsB})
    rc, out = _run_ctc(str(disp), as_json=False)
    expected = foundry.summarize_company_timing(
        dispatch_path=str(disp), products=(tsA, tsB), disabled=(), errors=(),
        threshold=foundry.SUITE_SLOW_SECONDS)
    assert out.rstrip("\n") == expected.render().rstrip("\n"), \
        f"human path must print render():\n{out}"
    assert rc == expected.exit_code


def test_b9_read_only_writes_nothing_to_disk(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _ts("alpha", [10.0])})
    before = _snapshot_tree(tmp_path)
    _run_ctc(str(disp), as_json=False)
    _run_ctc(str(disp), as_json=True)
    assert _snapshot_tree(tmp_path) == before, \
        "company-timing wrote to disk (must be read-only)"


# ==========================================================================
# Behavior 10 -- CLI wiring, read-only, off the control path
# ==========================================================================
def test_b10_subcommand_help_has_config_limit_json():
    out = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = out
    try:
        with pytest.raises(SystemExit) as ei:
            foundry.main(["company-timing", "--help"])
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    assert ei.value.code == 0
    text = out.getvalue()
    assert "--config" in text and "--limit" in text and "--json" in text


def test_b10_default_config_is_repo_dispatch_config(monkeypatch):
    captured = {}

    def spy(dispatch_path, limit=None, as_json=False):
        captured.update(dp=dispatch_path, limit=limit, js=as_json)
        return 0

    monkeypatch.setattr(foundry, "company_timing_cli", spy)
    rc = foundry.main(["company-timing"])
    assert rc == 0
    froot = pathlib.Path(foundry.__file__).resolve().parent
    assert captured["dp"] == str(froot / "foundry.config.json"), \
        "default --config must be the repo's DISPATCH config (foundry.config.json)"
    assert captured["limit"] is None and captured["js"] is False


def test_b10_limit_is_int_and_json_flag_pass_through(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        foundry, "company_timing_cli",
        lambda dp, limit=None, as_json=False:
            captured.update(dp=dp, limit=limit, js=as_json) or 0)
    foundry.main(["company-timing", "--limit", "5", "--json"])
    assert captured["limit"] == 5 and isinstance(captured["limit"], int)
    assert captured["js"] is True


def test_b10_dispatched_before_load_config(monkeypatch):
    monkeypatch.setattr(foundry, "company_timing_cli",
                        lambda dp, limit=None, as_json=False: 0)

    def boom(path):
        raise AssertionError(f"main called load_config(args.config)={path!r}")

    monkeypatch.setattr(foundry, "load_config", boom)
    assert foundry.main(["company-timing", "--config", "whatever.json"]) == 0


def test_b10_both_modules_import():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"
    assert dispatcher is not None


def test_b10_new_surface_present_and_reuses_shipped_seams():
    for name in NEW_SYMBOLS:
        assert hasattr(foundry, name), f"missing new symbol {name!r}"
    assert callable(foundry.summarize_company_timing)
    assert callable(foundry.company_timing_cli)
    # SHIPPED seams REUSED, not re-added:
    for name in ("parse_dispatch_work_items", "gather_timing", "TimingSummary",
                 "summarize_timing", "SUITE_SLOW_SECONDS"):
        assert hasattr(foundry, name), f"shipped seam {name!r} vanished"
    probe = foundry.summarize_timing(product="p", records=[], threshold=1.0)
    assert hasattr(probe, "measured_seconds"), \
        "the iter-39 TimingSummary.measured_seconds accessor must still exist"


def test_b10_new_symbols_absent_from_control_flow_and_dispatcher():
    for fn_name in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references new symbol {sym!r} (must stay off the control path)"
    # dispatcher must not reference any of the new company-timing symbols
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    dnames, dconsts = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in dnames, f"dispatcher references {sym!r}"
    assert "company-timing" not in dconsts, "dispatcher references the 'company-timing' literal"


def test_b10_timing_to_dict_still_11_keys_unchanged():
    # bite 2 must NOT change the shipped iter-18/39 TimingSummary surface
    s = foundry.summarize_timing(
        product="p", records=[R(1, 10.0), R(2, None)], threshold=20.0)
    d = s.to_dict()
    assert len(d) == 11, f"TimingSummary.to_dict must still have EXACTLY 11 keys: {list(d)}"
    assert list(d.keys()) == [
        "product", "total", "measured", "min_seconds", "max_seconds",
        "avg_seconds", "last_seconds", "count_slow", "threshold", "exit_code",
        "records",
    ]


def test_b10_live_smoke_on_real_dispatch_config():
    froot = pathlib.Path(foundry.__file__).resolve().parent
    if not (froot / "foundry.config.json").exists():
        pytest.skip(
            "machine-local foundry.config.json absent at repo root (gitignored); "
            "live smoke needs the operator's real dispatch config"
        )
    rc_h, _ = _run_cli(["company-timing"])
    rc_j, out_j = _run_cli(["company-timing", "--json"])
    doc = json.loads(out_j.strip())  # ONE parseable JSON document
    assert rc_j == rc_h == doc["exit_code"], "json/human exit codes must agree"
    assert doc["verdict"] == _VERDICT_FOR_CODE[doc["exit_code"]]
