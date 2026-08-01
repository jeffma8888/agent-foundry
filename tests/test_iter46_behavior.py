"""Black-box behaviour tests for iter 46 -- `foundry company-events` BITE 2 of 2
(the CLI + core that COMPLETES the feature AND the 5-member `company-*` family):
a read-only, offline company-wide roll-up that folds every ENABLED dispatch team's
iter-27 events digest (via the shipped iter-44 `gather_events` seam + the frozen
iter-27 `EventsSummary`) into ONE company view -- summed
total/matched/shown/malformed + a merged per-`kind` tally + a per-product
breakdown -- with a scriptable INFORMATIONAL exit code, a human `render()`, and
`--json`. The 5th and LAST member after `company-status` (iter 30) /
`company-history` (iter 31) / `company-timing` (iter 40) / `company-weak-tests`
(iter 43). UNLIKE the GATING `company-weak-tests`, `company-events` is
INFORMATIONAL (like history/timing): a malformed line or a quiet team never
gates; only a STRUCTURAL gather failure gates (exit 1). RETRY of iter-45 (which
was reverted solely because the isolated tester environmentally stalled; the
design is re-issued verbatim).

ISOLATION CONTRACT (HONORED): this file was written SOLELY from the iter-46 PM
spec's Expected Behaviors (1-8), the product README/roadmap, the existing
`tests/` conventions (esp. tests/test_iter40_behavior.py -- the `company-timing`
structural mirror, tests/test_iter43_behavior.py -- the `company-weak-tests`
sibling, and tests/test_iter27_behavior.py / test_iter44_behavior.py -- the
frozen `EventsSummary` / `gather_events` seams), and the product's own OBSERVABLE
runtime interface (building the public objects via `summarize_company_events` /
`summarize_events`, RUNNING the CLI via `foundry.main([...])` /
`foundry.company_events_cli(...)`, `--help`, `inspect.signature`, and compiled
`__code__` name/const tables). The implementation SOURCE text of
foundry.py / dispatcher.py, the engineer's and reviewer's notes for this
iteration, and `git diff` were NOT read. Off-control-path checks use only public
RUNTIME introspection + a subprocess `import` probe, never the source text.

Fully offline & deterministic: real temp dispatch/product files under `tmp_path`,
`foundry.load_config`/`foundry.gather_events` monkeypatched for the CLI cases;
ZERO real git / agent subprocess / network / sleeps (except the documented
`import foundry, dispatcher` regression probe + an opt-in auto-skipping live
smoke).
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
_VERDICT_FOR_CODE = {0: "OK", 1: "ERRORS", 2: "no enabled products"}

# the genuinely-NEW iter-46 symbols
NEW_SYMBOLS = ("CompanyEvents", "summarize_company_events", "company_events_cli")
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")


# --------------------------------------------------------------------------
# helpers  (mirror tests/test_iter40_behavior.py + test_iter43_behavior.py)
# --------------------------------------------------------------------------
def _es(product, kinds=(), *, total=None, matched=None, parse_errors=0, kind_filter=None):
    """Build a REAL EventsSummary via the shipped iter-27 pure factory.
    `kinds` -> a sequence of kind strings; one record per kind (so
    shown == len(kinds) and kind_counts folds the kinds in order). total/matched
    default to len(kinds); each record carries a DISTINCTIVE msg so we can prove
    render() does NOT leak individual event lines."""
    records = tuple(
        {"kind": k, "ts": "T%d" % i, "msg": "%s-%d" % (product, i)}
        for i, k in enumerate(kinds)
    )
    n = len(records)
    return foundry.summarize_events(
        product=product,
        records=records,
        total=total if total is not None else n,
        matched=matched if matched is not None else n,
        parse_errors=parse_errors,
        kind_filter=kind_filter,
    )


def _capture(fn, *a, **k):
    """Call fn capturing (rc, stdout, stderr) SEPARATELY -- separate capture
    matters for the JSON path (the JSON must be the ENTIRE stdout)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn(*a, **k)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _run_cec(dispatch_path, kind=None, limit=None, as_json=False):
    return _capture(foundry.company_events_cli, dispatch_path,
                    kind=kind, limit=limit, as_json=as_json)


def _run_main(argv):
    return _capture(foundry.main, argv)


def _write_dispatch(tmp_path, work_items, name="foundry.config.json"):
    """Write a minimal DISPATCH config (a `work_items` list) to tmp."""
    p = pathlib.Path(tmp_path) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"work_items": work_items}))
    return p


def _snapshot_tree(root):
    """Map {relative-path: bytes} for every file under root (no-write proof)."""
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*") if p.is_file()
    }


def _final_verdict_token(text):
    """Return the token after the final `verdict:` line."""
    lines = [ln for ln in text.splitlines()
             if ln.strip().lower().startswith("verdict:")]
    assert lines, "no `verdict:` line found in:\n%s" % text
    return lines[-1].split(":", 1)[1].strip()


def _product_line(text, product):
    """The single `  - {product}:` line from a render()."""
    rows = [ln for ln in text.splitlines()
            if ln.strip().startswith("- %s:" % product)]
    assert len(rows) == 1, \
        "expected exactly one line for %r, got %r\n%s" % (product, rows, text)
    return rows[0]


def _patch_cli(monkeypatch, es_by_name):
    """Monkeypatch load_config (returns a cfg tagged with the resolved path,
    recording every load path) and gather_events (returns an EventsSummary by
    matching a product-name substring of the config path). Returns (loaded_paths,
    calls) where calls records the (path, kind, limit) of every gather call."""
    loaded, calls = [], []

    class _Cfg:
        def __init__(self, path):
            self._path = path

    def fake_load(path):
        loaded.append(path)
        return _Cfg(path)

    def fake_gather(cfg, kind=None, limit=None):
        calls.append({"path": cfg._path, "kind": kind, "limit": limit})
        for name, es in es_by_name.items():
            if name in cfg._path:
                return es
        return _es("unknown", ["ship"])

    monkeypatch.setattr(foundry, "load_config", fake_load)
    monkeypatch.setattr(foundry, "gather_events", fake_gather)
    return loaded, calls


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
# Behavior 1 -- CompanyEvents company sums + merged kind tally (frozen)
# ==========================================================================
def test_b1_worked_example_sums_and_merged_kind_counts():
    # the spec's exact worked example
    esA = _es("alpha", ["ship", "revert"], total=5, matched=3, parse_errors=1)
    esB = _es("beta", ["ship"], total=4, matched=4, parse_errors=0)
    # reused iter-27 EventsSummary preconditions (shown == len(records), folded kinds)
    assert esA.shown == 2 and esA.kind_counts == {"ship": 1, "revert": 1}
    assert esB.shown == 1 and esB.kind_counts == {"ship": 1}
    ce = foundry.summarize_company_events(
        dispatch_path="/d/fc.json", products=(esA, esB),
        disabled=(), errors=(), kind_filter=None)
    assert dataclasses.is_dataclass(ce)
    assert type(ce).__name__ == "CompanyEvents"
    assert ce.dispatch_path == "/d/fc.json"
    assert ce.products == (esA, esB)
    assert ce.total == 9 == sum(p.total for p in ce.products)
    assert ce.matched == 7 == sum(p.matched for p in ce.products)
    assert ce.shown == 3 == sum(p.shown for p in ce.products)
    assert ce.parse_errors == 1 == sum(p.parse_errors for p in ce.products)
    assert ce.kind_counts == {"ship": 2, "revert": 1}
    assert ce.n_active == 2
    assert ce.n_products == 2 == len(ce.products)


def test_b1_kind_counts_first_encountered_order_across_products():
    esA = _es("alpha", ["ship", "revert"])
    esB = _es("beta", ["backoff", "ship"])
    ce = foundry.summarize_company_events(
        dispatch_path="/d", products=(esA, esB),
        disabled=(), errors=(), kind_filter=None)
    assert list(ce.kind_counts.keys()) == ["ship", "revert", "backoff"], \
        "keys must be in first-encountered order across products in stored order"
    assert ce.kind_counts == {"ship": 2, "revert": 1, "backoff": 1}


def test_b1_n_active_counts_only_shown_gt_zero():
    esShown = _es("a", ["ship"])                 # shown 1
    esEmpty = _es("b", [], total=3, matched=0)   # shown 0
    ce = foundry.summarize_company_events(
        dispatch_path="/d", products=(esShown, esEmpty),
        disabled=(), errors=(), kind_filter=None)
    assert ce.n_products == 2
    assert ce.n_active == 1, "n_active counts only products with shown > 0"
    assert ce.shown == 1


def test_b1_frozen_kind_filter_and_count_props():
    ce = foundry.summarize_company_events(
        dispatch_path="/d", products=(_es("a", ["ship"]),),
        disabled=("x", "y"), errors=(("e", "m"),), kind_filter="ship")
    assert ce.kind_filter == "ship"
    assert ce.disabled == ("x", "y") and ce.errors == (("e", "m"),)
    assert ce.n_disabled == 2 == len(ce.disabled)
    assert ce.n_errors == 1 == len(ce.errors)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ce.total = 99  # frozen


# ==========================================================================
# Behavior 2 -- exit_code / verdict INFORMATIONAL (parse_errors never gate)
# ==========================================================================
def test_b2_clean_company_exit_0_ok():
    ce = foundry.summarize_company_events(
        dispatch_path="/d", products=(_es("a", ["ship"]),),
        disabled=(), errors=(), kind_filter=None)
    assert ce.exit_code == 0 and ce.verdict == "OK"


def test_b2_errors_gate_to_1():
    ce = foundry.summarize_company_events(
        dispatch_path="/d", products=(_es("a", ["ship"]),),
        disabled=(), errors=(("boom", "load failed"),), kind_filter=None)
    assert ce.exit_code == 1 and ce.verdict == "ERRORS"


def test_b2_no_enabled_products_exit_2():
    ce = foundry.summarize_company_events(
        dispatch_path="/d", products=(), disabled=("x", "y"),
        errors=(), kind_filter=None)
    assert ce.exit_code == 2 and ce.verdict == "no enabled products"


def test_b2_errors_beat_no_products():
    ce = foundry.summarize_company_events(
        dispatch_path="/d", products=(), disabled=(),
        errors=(("boom", "x"),), kind_filter=None)
    assert ce.exit_code == 1, \
        "a structural error must gate to 1 even with zero products"


def test_b2_zero_shown_product_does_not_force_exit_2():
    esEmpty = _es("z", [], total=5, matched=0, parse_errors=0)
    assert esEmpty.shown == 0 and esEmpty.exit_code == 2, \
        "reused EventsSummary: zero shown -> its OWN exit_code is 2"
    ce = foundry.summarize_company_events(
        dispatch_path="/d", products=(esEmpty,),
        disabled=(), errors=(), kind_filter=None)
    assert ce.n_products == 1, "a zero-shown product still counts in n_products"
    assert ce.exit_code == 0, \
        "a zero-shown gathered product must NOT force company exit 2"


def test_b2_parse_errors_never_change_exit_code():
    esPE = _es("z", [], total=5, matched=0, parse_errors=2)  # shown 0, pe 2
    ce = foundry.summarize_company_events(
        dispatch_path="/d", products=(esPE,),
        disabled=(), errors=(), kind_filter=None)
    assert ce.parse_errors == 2
    assert ce.exit_code == 0, "parse_errors must NEVER change the company exit_code"


# ==========================================================================
# Behavior 3 -- render() substrings (human report; counts only, no event lines)
# ==========================================================================
def test_b3_render_substrings_and_verdict():
    esA = _es("alpha", ["ship", "revert"], total=5, matched=3, parse_errors=1)
    esB = _es("beta", ["ship"], total=4, matched=4, parse_errors=0)
    ce = foundry.summarize_company_events(
        dispatch_path="/d/fc.json", products=(esA, esB),
        disabled=("gone",), errors=(("errp", "boom msg"),), kind_filter="ship")
    r = ce.render()
    assert "foundry company-events" in r
    assert "/d/fc.json" in r, "render must contain the dispatch path"
    assert "kind=ship" in r, "kind_filter not None -> render must show kind={filter}"
    # counts line
    assert "%d gathered" % ce.n_products in r
    assert "%d disabled" % ce.n_disabled in r
    assert "%d error" % ce.n_errors in r
    # company rollup (the malformed rollup and the kind tally are SEPARATE substrings)
    assert "%d shown of %d matched, %d total, %d malformed" % (
        ce.shown, ce.matched, ce.total, ce.parse_errors) in r
    for k, v in ce.kind_counts.items():
        assert " %s:%d" % (k, v) in r, "missing company kind tally ' %s:%d'" % (k, v)
    # per-product lines carry each product's OWN counts
    la = _product_line(r, "alpha")
    assert "%d shown of %d matched, %d total, %d malformed" % (
        esA.shown, esA.matched, esA.total, esA.parse_errors) in la
    lb = _product_line(r, "beta")
    assert "%d shown of %d matched, %d total, %d malformed" % (
        esB.shown, esB.matched, esB.total, esB.parse_errors) in lb
    # disabled + error lines
    assert any("- gone:" in ln and "disabled" in ln for ln in r.splitlines()), \
        "missing disabled line for 'gone':\n%s" % r
    assert any("errp" in ln and "ERROR" in ln and "boom msg" in ln
               for ln in r.splitlines()), \
        "missing error line (name+ERROR+message):\n%s" % r
    # final verdict line
    assert _final_verdict_token(r) == ce.verdict == "ERRORS"


def test_b3_no_kind_line_when_filter_none():
    ce = foundry.summarize_company_events(
        dispatch_path="/d", products=(_es("a", ["ship"]),),
        disabled=(), errors=(), kind_filter=None)
    assert "kind=" not in ce.render(), \
        "with kind_filter None the render must NOT show a kind={..} clause"


def test_b3_render_omits_individual_event_lines():
    esA = _es("alpha", ["ship", "revert"])  # msgs alpha-0, alpha-1
    ce = foundry.summarize_company_events(
        dispatch_path="/d", products=(esA,),
        disabled=(), errors=(), kind_filter=None)
    r = ce.render()
    assert "alpha-0" not in r and "alpha-1" not in r, \
        "render() must list per-product COUNTS only, never individual event lines"


# ==========================================================================
# Behavior 4 -- to_dict() JSON-safe, reuses props, carries full per-product detail
# ==========================================================================
def test_b4_to_dict_json_safe_and_reuses_frozen_props():
    esA = _es("alpha", ["ship", "revert"], total=5, matched=3, parse_errors=1)
    esB = _es("beta", ["ship"], total=4, matched=4, parse_errors=0)
    ce = foundry.summarize_company_events(
        dispatch_path="/d/fc.json", products=(esA, esB),
        disabled=("gamma",), errors=(("eps", "boom"),), kind_filter="ship")
    d = ce.to_dict()
    assert json.loads(json.dumps(d)) == d, "to_dict must survive a JSON round-trip"
    expected_keys = {
        "dispatch_config", "kind_filter", "products", "disabled", "errors",
        "n_products", "n_disabled", "n_errors", "n_active",
        "total", "matched", "shown", "parse_errors", "kind_counts",
        "exit_code", "verdict",
    }
    assert expected_keys <= set(d), "missing keys: %s" % (expected_keys - set(d))
    assert d["dispatch_config"] == "/d/fc.json" == ce.dispatch_path
    assert d["kind_filter"] == "ship"
    assert d["disabled"] == ["gamma"]
    assert d["errors"] == [{"product": "eps", "message": "boom"}]
    # every derived value EQUALS the frozen prop -> payload cannot disagree
    assert (d["n_products"], d["n_disabled"], d["n_errors"], d["n_active"]) == \
        (ce.n_products, ce.n_disabled, ce.n_errors, ce.n_active) == (2, 1, 1, 2)
    assert (d["total"], d["matched"], d["shown"], d["parse_errors"]) == \
        (ce.total, ce.matched, ce.shown, ce.parse_errors) == (9, 7, 3, 1)
    assert d["kind_counts"] == ce.kind_counts == {"ship": 2, "revert": 1}
    assert d["exit_code"] == ce.exit_code == 1   # errors non-empty -> 1
    assert d["verdict"] == ce.verdict == "ERRORS"


def test_b4_products_carry_full_per_product_to_dict():
    esA = _es("alpha", ["ship", "revert"])
    esB = _es("beta", ["ship"])
    ce = foundry.summarize_company_events(
        dispatch_path="/d", products=(esA, esB),
        disabled=(), errors=(), kind_filter=None)
    d = ce.to_dict()
    assert d["products"] == [esA.to_dict(), esB.to_dict()], \
        "products must be each gathered EventsSummary.to_dict() IN stored order"
    assert len(d["products"][0]) == 9, \
        "per-product payload must be the full 9-key EventsSummary.to_dict()"
    assert "events" in d["products"][0], \
        "the full per-product events leaf must survive in to_dict()"


def test_b4_empty_company_is_json_safe():
    ce = foundry.summarize_company_events(
        dispatch_path="/d", products=(), disabled=(), errors=(), kind_filter=None)
    d = ce.to_dict()
    assert d["kind_counts"] == {}
    assert d["products"] == [] and d["disabled"] == [] and d["errors"] == []
    assert json.loads(json.dumps(d)) == d, "empty company must be JSON-safe"
    assert d["exit_code"] == 2 and d["verdict"] == "no enabled products"


# ==========================================================================
# Behavior 5 -- company_events_cli rolls up enabled; disabled skipped;
#               {FOUNDRY} substituted; kind/limit passed through
# ==========================================================================
def test_b5_enabled_gathered_disabled_recorded_never_loaded(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": False},
    ])
    loaded, calls = _patch_cli(monkeypatch, {"alpha": _es("alpha", ["ship", "revert"])})
    rc, out, err = _run_cec(str(disp), kind="ship", limit=5)
    assert loaded == [str(tmp_path / "alpha.json")], \
        "only the ENABLED item is load_config'd; the disabled one is never loaded"
    assert len(calls) == 1
    assert calls[0]["kind"] == "ship" and calls[0]["limit"] == 5, \
        "kind and limit must pass THROUGH to each team's gather_events call"
    assert "alpha" in out
    assert any("beta" in ln and "disabled" in ln for ln in out.splitlines()), \
        "the disabled item must still be listed as disabled"
    assert "kind=ship" in out, "company kind_filter must be set to the passed kind"
    assert rc == 0, "alpha shown>0, no errors -> company exit 0"


def test_b5_kind_and_limit_flow_to_every_gather(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    _, calls = _patch_cli(monkeypatch, {
        "alpha": _es("alpha", ["ship"]), "beta": _es("beta", ["ship"])})
    _run_cec(str(disp), kind="revert", limit=3)
    assert [(c["kind"], c["limit"]) for c in calls] == [("revert", 3), ("revert", 3)], \
        "kind/limit must flow to EACH enabled team's gather_events: %r" % calls


def test_b5_foundry_token_substituted_before_load(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": "{FOUNDRY}/products/alpha/config.json",
         "enabled": True},
    ])
    loaded, _ = _patch_cli(monkeypatch, {"alpha": _es("alpha", ["ship"])})
    _run_cec(str(disp))
    froot = str(pathlib.Path(foundry.__file__).resolve().parent)
    assert loaded == ["%s/products/alpha/config.json" % froot], \
        "{FOUNDRY} must be substituted to the foundry root before load: %r" % loaded
    assert "{FOUNDRY}" not in "".join(loaded)


# ==========================================================================
# Behavior 6 -- company_events_cli resilience: no exception ever propagates
# ==========================================================================
def test_b6_missing_dispatch_file_exit1_no_raise(tmp_path):
    rc, out, err = _run_cec(str(tmp_path / "does-not-exist.json"))  # must NOT raise
    assert rc == 1 and "ERROR" in (out + err)


def test_b6_invalid_json_exit1_no_raise(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json ]")
    rc, out, err = _run_cec(str(bad))
    assert rc == 1 and "ERROR" in (out + err)


def test_b6_not_a_json_object_exit1(tmp_path):
    lst = tmp_path / "list.json"
    lst.write_text("[1, 2, 3]")
    rc, _, _ = _run_cec(str(lst))
    assert rc == 1


def test_b6_synthetic_error_keyed_by_dispatch_path(tmp_path):
    missing = tmp_path / "nope.json"
    rc, out, _ = _run_cec(str(missing), as_json=True)
    doc = json.loads(out.strip())  # still exactly one parseable JSON doc
    assert rc == 1 and doc["exit_code"] == 1 and len(doc["errors"]) == 1
    assert doc["errors"][0]["product"] == str(missing), \
        "the ONE synthetic error must be keyed by the dispatch path: %s" % doc["errors"]


def test_b6_one_bad_team_recorded_rollup_continues(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "good", "config": str(tmp_path / "good.json"), "enabled": True},
        {"name": "bad", "config": str(tmp_path / "bad.json"), "enabled": True},
        {"name": "good2", "config": str(tmp_path / "good2.json"), "enabled": True},
    ])
    monkeypatch.setattr(foundry, "load_config",
                        lambda p: type("C", (), {"_path": p})())

    def fake_gather(cfg, kind=None, limit=None):
        if "bad.json" in cfg._path:
            raise RuntimeError("kaboom gathering bad")
        return _es("good" if "good.json" in cfg._path else "good2", ["ship"])

    monkeypatch.setattr(foundry, "gather_events", fake_gather)
    rc, out, err = _run_cec(str(disp))
    text = out + err
    assert rc == 1, "a failing work item must make the company exit 1"
    assert "bad" in text and "ERROR" in text and "kaboom gathering bad" in text, \
        "the failing item + its message must be recorded:\n%s" % text
    assert "good" in text and "good2" in text, "gathering must CONTINUE past the failure"


def test_b6_gather_error_recorded_as_name_and_str_exc(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "boomp", "config": str(tmp_path / "boomp.json"), "enabled": True},
    ])
    monkeypatch.setattr(foundry, "load_config", lambda p: type("C", (), {})())

    def fake_gather(cfg, kind=None, limit=None):
        raise ValueError("gather blew up")

    monkeypatch.setattr(foundry, "gather_events", fake_gather)
    rc, out, _ = _run_cec(str(disp), as_json=True)
    doc = json.loads(out.strip())
    assert rc == 1 and doc["exit_code"] == 1
    assert {"product": "boomp", "message": "gather blew up"} in doc["errors"], \
        "error must be recorded as (name, str(exc)): %s" % doc["errors"]


def test_b6_load_config_error_recorded(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "lc", "config": str(tmp_path / "lc.json"), "enabled": True},
    ])

    def boom(path):
        raise OSError("cannot load lc")

    monkeypatch.setattr(foundry, "load_config", boom)
    monkeypatch.setattr(foundry, "gather_events",
                        lambda cfg, kind=None, limit=None: _es("x", ["ship"]))
    rc, out, err = _run_cec(str(disp))
    assert rc == 1
    assert "lc" in (out + err) and "ERROR" in (out + err)


# ==========================================================================
# Behavior 7 -- --json parity + read-only
# ==========================================================================
def test_b7_json_single_indent2_document_same_exit(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _es("alpha", ["ship", "revert"]),
                             "beta": _es("beta", ["ship"])})
    rc_h, _, _ = _run_cec(str(disp), as_json=False)
    rc_j, out_j, _ = _run_cec(str(disp), as_json=True)
    doc = json.loads(out_j.strip())  # exactly ONE parseable JSON document
    assert out_j.strip() == json.dumps(doc, indent=2), \
        "the --json path must print exactly one json.dumps(to_dict(), indent=2) doc"
    assert rc_j == rc_h == doc["exit_code"]
    assert [p["product"] for p in doc["products"]] == ["alpha", "beta"]


def test_b7_human_path_prints_render(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    esA = _es("alpha", ["ship", "revert"])
    esB = _es("beta", ["ship"])
    _patch_cli(monkeypatch, {"alpha": esA, "beta": esB})
    rc, out, _ = _run_cec(str(disp), as_json=False)
    expected = foundry.summarize_company_events(
        dispatch_path=str(disp), products=(esA, esB),
        disabled=(), errors=(), kind_filter=None)
    assert out.rstrip("\n") == expected.render().rstrip("\n"), \
        "human path must print render():\n%s" % out
    assert rc == expected.exit_code


def test_b7_read_only_writes_nothing_to_disk(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _es("alpha", ["ship"])})
    before = _snapshot_tree(tmp_path)
    _run_cec(str(disp), as_json=False)
    _run_cec(str(disp), as_json=True)
    assert _snapshot_tree(tmp_path) == before, \
        "company-events wrote to disk (must be read-only)"


# ==========================================================================
# Behavior 8 -- CLI wiring, read-only, off the control path; iter-44 guard flip
# ==========================================================================
def test_b8_subcommand_help_has_config_kind_limit_json():
    out = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = out
    try:
        with pytest.raises(SystemExit) as ei:
            foundry.main(["company-events", "--help"])
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    assert ei.value.code == 0
    text = out.getvalue()
    for flag in ("--config", "--kind", "--limit", "--json"):
        assert flag in text, "%s missing from company-events --help:\n%s" % (flag, text)


def test_b8_default_config_is_repo_dispatch_config(monkeypatch):
    captured = {}

    def spy(dispatch_path, kind=None, limit=None, as_json=False):
        captured.update(dp=dispatch_path, kind=kind, limit=limit, js=as_json)
        return 0

    monkeypatch.setattr(foundry, "company_events_cli", spy)
    rc = foundry.main(["company-events"])
    assert rc == 0
    froot = pathlib.Path(foundry.__file__).resolve().parent
    assert captured["dp"] == str(froot / "foundry.config.json"), \
        "default --config must be the repo's DISPATCH config (foundry.config.json)"
    assert captured["kind"] is None and captured["limit"] is None
    assert captured["js"] is False


def test_b8_flags_pass_through(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        foundry, "company_events_cli",
        lambda dp, kind=None, limit=None, as_json=False:
            captured.update(dp=dp, kind=kind, limit=limit, js=as_json) or 0)
    foundry.main(["company-events", "--config", "d.json",
                  "--kind", "ship", "--limit", "7", "--json"])
    assert captured["dp"] == "d.json"
    assert captured["kind"] == "ship"
    assert captured["limit"] == 7, "--limit must be parsed as int"
    assert captured["js"] is True


def test_b8_dispatched_before_load_config(monkeypatch):
    monkeypatch.setattr(foundry, "company_events_cli",
                        lambda dp, kind=None, limit=None, as_json=False: 0)

    def boom(path):
        raise AssertionError("main called load_config(args.config)=%r" % path)

    monkeypatch.setattr(foundry, "load_config", boom)
    assert foundry.main(["company-events", "--config", "whatever.json"]) == 0


def test_b8_both_modules_import():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, "`import foundry, dispatcher` failed:\n%s" % r.stderr
    assert dispatcher is not None


def test_b8_new_surface_present_and_reuses_shipped_seams():
    for name in NEW_SYMBOLS:
        assert hasattr(foundry, name), "missing new symbol %r" % name
    assert callable(foundry.summarize_company_events)
    assert callable(foundry.company_events_cli)
    # SHIPPED seams REUSED, not re-added:
    for name in ("parse_dispatch_work_items", "gather_events", "EventsSummary",
                 "summarize_events", "parse_events_jsonl", "events_cli"):
        assert hasattr(foundry, name), "shipped seam %r vanished" % name


def test_b8_new_symbols_absent_from_control_flow_and_dispatcher():
    for fn_name in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, \
                "%s references new symbol %r (must stay off the control path)" % (fn_name, sym)
        assert "company-events" not in consts, \
            "%s embeds the 'company-events' subcommand literal" % fn_name
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), "dispatcher must not expose %r" % sym
    dnames, dconsts = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in dnames, "dispatcher references %r" % sym
    assert "company-events" not in dconsts, \
        "dispatcher references the 'company-events' literal"


def test_b8_events_summary_to_dict_still_9_keys_unchanged():
    # bite 2 must NOT change the shipped iter-27 EventsSummary surface
    s = foundry.summarize_events(
        product="p", records=({"kind": "ship", "ts": "T0"},),
        total=1, matched=1, parse_errors=0, kind_filter=None)
    d = s.to_dict()
    assert len(d) == 9, "EventsSummary.to_dict must still have EXACTLY 9 keys: %s" % list(d)
    assert list(d.keys()) == [
        "product", "kind_filter", "total", "matched", "shown",
        "parse_errors", "exit_code", "kind_counts", "events",
    ]


def test_b8_help_lists_company_events_after_siblings(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for sub in ("events", "company-status", "company-history",
                "company-timing", "company-weak-tests", "company-events"):
        assert sub in out, "subcommand %r missing from --help:\n%s" % (sub, out)


def test_b8_running_writes_nothing_via_main(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _es("alpha", ["ship"])})
    before = _snapshot_tree(tmp_path)
    _run_main(["company-events", "--config", str(disp)])
    assert _snapshot_tree(tmp_path) == before, \
        "running company-events created/modified files (read-only violation)"


def test_b8_live_smoke_on_real_dispatch_config():
    froot = pathlib.Path(foundry.__file__).resolve().parent
    if not (froot / "foundry.config.json").exists():
        pytest.skip(
            "machine-local foundry.config.json absent at repo root (gitignored); "
            "live smoke needs the operator's real dispatch config"
        )
    rc_h, _, _ = _run_main(["company-events"])
    rc_j, out_j, _ = _run_main(["company-events", "--json"])
    doc = json.loads(out_j.strip())  # ONE parseable JSON document
    assert rc_j == rc_h == doc["exit_code"], "json/human exit codes must agree"
    assert doc["verdict"] == _VERDICT_FOR_CODE[doc["exit_code"]]
