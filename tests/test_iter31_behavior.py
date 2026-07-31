"""Black-box behaviour tests for iter 31 -- `foundry company-history`, a read-only,
offline CLI that rolls EVERY enabled dispatch team's per-product iter-17 ship
ledger into ONE company-wide rollup (total iterations / shipped / reverted /
broken across all teams), human or `--json`, with a scriptable
`0` has-history-no-errors / `1` errors / `2` no-enabled-products exit code. ALL
additive in foundry.py:

  * a NEW module-level seam `gather_history(cfg, limit=None) -> HistorySummary`
    that `history_cli` now delegates to (output-preserving refactor of iter 17),
  * a FROZEN dataclass `CompanyHistory(dispatch_path, products, disabled, errors)`
    with `n_*` count props + `total`/`shipped`/`reverted`/`broken` rollup props +
    `exit_code`/`verdict` + `render()` + `to_dict()`,
  * a PURE keyword-only `summarize_company_history(...) -> CompanyHistory`,
  * a `company_history_cli(dispatch_path, limit=None, as_json=False) -> int` wired
    to a new argparse subcommand `company-history`, reusing the iter-30
    `parse_dispatch_work_items` verbatim.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-31 PM spec's
Expected Behaviors (1-14), the product README/roadmap, the `tests/` conventions,
and the product's own OBSERVABLE behaviour (running `foundry company-history`
/ `--help` / `--json` and public runtime introspection). The implementation
source (foundry.py / dispatcher.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read. Every check drives the PUBLIC interface: the
seam via `foundry.gather_history(...)`, the pure fn via
`foundry.summarize_company_history(...)`, the dataclass via
`foundry.CompanyHistory(...)` / `foundry.HistorySummary(...)`, and the CLI via
`foundry.main(["company-history", ...])` / `foundry.company_history_cli(...)`
against tiny dispatch/product JSON files in `tmp_path`, monkeypatching
`foundry.load_config` / `foundry.gather_history` / `foundry.summarize_history` /
`foundry.parse_ship_action` (the real product repos / state / git / network are
NEVER touched, except the read-only Behavior-13 live-smoke against the repo's own
`foundry.config.json` and the Behavior-14 `import` regression probe). Fully
offline & deterministic.
"""
import dataclasses
import io
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# fixed exit-code <-> verdict mapping asserted throughout (Behavior 4)
_VERDICT_FOR_CODE = {0: "OK", 1: "ERRORS", 2: "no enabled products"}


# --------------------------------------------------------------------------
# helpers  (mirror tests/test_iter30_behavior.py + tests/test_iter17_behavior.py)
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


def _run_chc(dispatch_path, limit=None, as_json=False):
    """Drive company_history_cli directly, capturing (rc, stdout+stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.company_history_cli(dispatch_path, limit=limit, as_json=as_json)
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


def _write_product_cfg(base, **over):
    """A minimal product config in `base` (mirrors iter16/17 convention); repo /
    work_root are TMP so the real foundry repo/state is NEVER touched."""
    base = pathlib.Path(base)
    base.mkdir(parents=True, exist_ok=True)
    repo = base / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(base / "VISION.md"),
        "work_root": str(base / "work"),
    }
    data.update(over)
    p = base / "config.json"
    p.write_text(json.dumps(data))
    return p


def _iter_dir(cfg, iteration):
    return pathlib.Path(cfg.state) / f"iter-{iteration:02d}"


def _write_final(cfg, iteration, action_line):
    """Create state/iter-NN/final.md whose LAST non-empty line is `action_line`."""
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    (d / "final.md").write_text(f"final gate report\n\n{action_line}\n\n   \n")
    return d / "final.md"


def _write_postrelease(cfg, iteration, verdict):
    """Create state/iter-NN/postrelease.md whose LAST non-empty line is the
    `POSTRELEASE: <verdict>` sentinel (reused iter-16 sentinel)."""
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    (d / "postrelease.md").write_text(f"post-release report\n\nPOSTRELEASE: {verdict}\n")
    return d / "postrelease.md"


def _hs(product="alpha", shipped=0, reverted=0, broken=0, plain=0):
    """Build a HistorySummary with EXACTLY the given counts (counts are the frozen
    props confirmed in iter-17: shipped=#PUSHED, reverted=#REVERTED,
    broken=#postrelease-BROKEN [independent of action], total=#records)."""
    R = foundry.IterationRecord
    recs, i = [], 1
    for _ in range(shipped):
        recs.append(R(i, "PUSHED", "HEALTHY")); i += 1
    for _ in range(reverted):
        recs.append(R(i, "REVERTED", None)); i += 1
    for _ in range(broken):
        recs.append(R(i, None, "BROKEN")); i += 1
    for _ in range(plain):
        recs.append(R(i, None, None)); i += 1
    return foundry.HistorySummary(product, tuple(recs))


def _product_rollup(p):
    return (f"{p.total} iterations: {p.shipped} shipped, "
            f"{p.reverted} reverted, {p.broken} broken")


def _company_rollup(cs):
    return (f"{cs.total} iterations: {cs.shipped} shipped, "
            f"{cs.reverted} reverted, {cs.broken} broken")


def _final_verdict_token(text):
    """Return the token after the final `verdict:` line."""
    lines = [ln for ln in text.splitlines()
             if ln.strip().lower().startswith("verdict:")]
    assert lines, f"no `verdict:` line found in:\n{text}"
    return lines[-1].split(":", 1)[1].strip()


def _patch_cli(monkeypatch, hs_by_name):
    """Monkeypatch load_config (returns a cfg tagged with the resolved path,
    recording every load path) and gather_history (returns a HistorySummary by
    matching a product name substring of the config path)."""
    loaded = []

    class _Cfg:
        def __init__(self, path):
            self._path = path

    def fake_load(path):
        loaded.append(path)
        return _Cfg(path)

    def fake_gather(cfg, limit=None):
        for name, hs in hs_by_name.items():
            if name in cfg._path:
                return hs
        return _hs("unknown", shipped=1)

    monkeypatch.setattr(foundry, "load_config", fake_load)
    monkeypatch.setattr(foundry, "gather_history", fake_gather)
    return loaded


# ==========================================================================
# A. gather_history seam  (Behavior 1)
# ==========================================================================
def test_b01_real_state_counts_and_ascending_order(tmp_path):
    cfg = foundry.load_config(str(_write_product_cfg(tmp_path)))
    _write_final(cfg, 1, "ACTION: PUSHED s1")                      # shipped
    _write_final(cfg, 2, "ACTION: PUSHED s2"); _write_postrelease(cfg, 2, "HEALTHY")
    _write_final(cfg, 3, "ACTION: PUSHED s3"); _write_postrelease(cfg, 3, "BROKEN")
    _write_final(cfg, 4, "ACTION: REVERTED")                       # reverted
    _write_final(cfg, 5, "prose with no action sentinel")          # no-ship
    s = foundry.gather_history(cfg)
    assert isinstance(s, foundry.HistorySummary)
    assert s.product == cfg.name
    assert [r.iteration for r in s.records] == [1, 2, 3, 4, 5], "ASCENDING iter order"
    assert (s.total, s.shipped, s.reverted, s.broken) == (5, 3, 1, 1)


def test_b01_missing_state_dir_empty_ledger_never_raises(tmp_path):
    cfg = foundry.load_config(str(_write_product_cfg(tmp_path)))
    shutil.rmtree(cfg.state, ignore_errors=True)
    assert not pathlib.Path(cfg.state).exists()
    s = foundry.gather_history(cfg)  # must NOT raise
    assert isinstance(s, foundry.HistorySummary) and s.total == 0
    assert not pathlib.Path(cfg.state).exists(), \
        "gather_history must not create the state dir (read-only)"


def test_b01_limit_keeps_most_recent_n_ascending(tmp_path):
    cfg = foundry.load_config(str(_write_product_cfg(tmp_path)))
    for n in range(1, 6):
        _write_final(cfg, n, f"ACTION: PUSHED s{n}")
    assert [r.iteration for r in foundry.gather_history(cfg, 2).records] == [4, 5]
    assert [r.iteration for r in foundry.gather_history(cfg, limit=3).records] == [3, 4, 5]
    for lim in (None, 0, -2):
        assert foundry.gather_history(cfg, lim).total == 5, \
            f"None / non-positive limit ({lim!r}) must keep ALL"


def test_b01_delegates_to_summarize_history_by_bare_name(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_product_cfg(tmp_path)))
    for n in (2, 1, 3):  # written out of order to prove ASCENDING assembly
        _write_final(cfg, n, f"ACTION: PUSHED s{n}")
    captured = {}
    sentinel = foundry.HistorySummary("SENTINEL", ())

    def fake_sum(*, product, records):
        captured["product"] = product
        captured["iters"] = [r.iteration for r in records]
        return sentinel

    monkeypatch.setattr(foundry, "summarize_history", fake_sum)
    got = foundry.gather_history(cfg)
    assert got is sentinel, "gather_history must RETURN summarize_history(...)"
    assert captured["product"] == cfg.name
    assert captured["iters"] == [1, 2, 3], "records passed in ascending iter order"


def test_b01_uses_parse_ship_action_seam_by_bare_name(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_product_cfg(tmp_path)))
    for n in (1, 2, 3):
        _write_final(cfg, n, "ACTION: REVERTED")   # real action would be REVERTED
    monkeypatch.setattr(foundry, "parse_ship_action", lambda text: "PUSHED")
    s = foundry.gather_history(cfg)
    assert (s.total, s.shipped, s.reverted) == (3, 3, 0), \
        "monkeypatching foundry.parse_ship_action must bite gather_history"


# ==========================================================================
# B. history_cli delegates to gather_history, output-preserving  (Behavior 2)
# ==========================================================================
def test_b02_history_cli_delegates_to_gather_history(tmp_path, monkeypatch):
    cfg_path = _write_product_cfg(tmp_path)
    sentinel = foundry.HistorySummary("demoprod", (
        foundry.IterationRecord(1, "PUSHED", "BROKEN"),
        foundry.IterationRecord(2, "REVERTED", None),
    ))
    monkeypatch.setattr(foundry, "gather_history", lambda cfg, limit=None: sentinel)
    rc, out = _run_cli(["history", "--config", str(cfg_path)])
    assert rc == sentinel.exit_code
    assert out.rstrip("\n") == sentinel.render().rstrip("\n"), \
        f"history human output must equal gather_history().render():\n{out}"
    rc2, out2 = _run_cli(["history", "--config", str(cfg_path), "--json"])
    assert rc2 == sentinel.exit_code
    assert json.loads(out2.strip()) == sentinel.to_dict(), \
        "history --json must be json of gather_history().to_dict()"


def test_b02_history_output_and_exit_code_preserved(tmp_path):
    cfg_path = _write_product_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_final(cfg, 1, "ACTION: PUSHED a1")
    _write_final(cfg, 2, "ACTION: PUSHED a2"); _write_postrelease(cfg, 2, "HEALTHY")
    _write_final(cfg, 3, "ACTION: REVERTED")
    rc, out = _run_cli(["history", "--config", str(cfg_path)])
    assert rc == 0
    for tag in ("iter-01", "iter-02", "iter-03"):
        assert tag in out, f"missing {tag}:\n{out}"
    assert "3 iterations: 2 shipped, 1 reverted, 0 broken" in out, f"rollup wrong:\n{out}"
    # empty state -> exit 2 unchanged
    cfg2_path = _write_product_cfg(tmp_path / "second")
    cfg2 = foundry.load_config(str(cfg2_path))
    pathlib.Path(cfg2.state).mkdir(parents=True, exist_ok=True)
    rc2, _ = _run_cli(["history", "--config", str(cfg2_path)])
    assert rc2 == 2, "empty state history must still exit 2"


# ==========================================================================
# C. CompanyHistory frozen dataclass + counts + rollup  (Behavior 3)
# ==========================================================================
def test_b03_frozen_dataclass_fields_and_rollup_is_sum():
    pA = _hs("alpha", shipped=2, reverted=1, broken=1)  # total 4
    pB = _hs("beta", shipped=3)                          # total 3
    cs = foundry.summarize_company_history(
        dispatch_path="/d/fc.json", products=(pA, pB),
        disabled=("gamma", "delta"), errors=(("eps", "boom"),))
    assert dataclasses.is_dataclass(cs) and type(cs).__name__ == "CompanyHistory"
    assert cs.dispatch_path == "/d/fc.json"
    assert cs.products == (pA, pB) and cs.disabled == ("gamma", "delta")
    assert cs.errors == (("eps", "boom"),)
    assert cs.n_products == 2 and cs.n_disabled == 2 and cs.n_errors == 1
    assert cs.total == 7 == sum(p.total for p in cs.products)
    assert cs.shipped == 5 == sum(p.shipped for p in cs.products)
    assert cs.reverted == 1 == sum(p.reverted for p in cs.products)
    assert cs.broken == 1 == sum(p.broken for p in cs.products)


def test_b03_companyhistory_is_frozen():
    cs = foundry.summarize_company_history(
        dispatch_path="/d", products=(_hs("a", shipped=1),), disabled=(), errors=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        cs.dispatch_path = "/other"


# ==========================================================================
# D. exit_code + verdict  (Behavior 4)
# ==========================================================================
def test_b04_products_no_errors_exit0_ok():
    cs = foundry.summarize_company_history(
        dispatch_path="/d", products=(_hs("a", shipped=2),), disabled=(), errors=())
    assert cs.exit_code == 0 and cs.verdict == "OK"


def test_b04_past_broken_does_not_gate():
    cs = foundry.summarize_company_history(
        dispatch_path="/d",
        products=(_hs("a", shipped=1, broken=5), _hs("b", broken=2)),
        disabled=(), errors=())
    assert cs.broken == 7 and cs.exit_code == 0 and cs.verdict == "OK", \
        "a past BROKEN in a team ledger is informational -- must NOT gate"


def test_b04_errors_force_exit1_errors():
    cs = foundry.summarize_company_history(
        dispatch_path="/d", products=(_hs("a", shipped=3),),
        disabled=(), errors=(("boom", "load failed"),))
    assert cs.exit_code == 1 and cs.verdict == "ERRORS"


def test_b04_no_products_no_errors_exit2():
    cs = foundry.summarize_company_history(
        dispatch_path="/d", products=(), disabled=("x", "y"), errors=())
    assert cs.exit_code == 2 and cs.verdict == "no enabled products"
    assert cs.disabled == ("x", "y")


def test_b04_errors_without_products_is_errors_not_noproducts():
    cs = foundry.summarize_company_history(
        dispatch_path="/d", products=(), disabled=(), errors=(("z", "bad"),))
    assert cs.exit_code == 1 and cs.verdict == "ERRORS"


def test_b04_render_and_dict_verdict_agree_with_exit_code():
    cases = (
        foundry.summarize_company_history(dispatch_path="/d",
            products=(_hs("a", shipped=1),), disabled=(), errors=()),           # OK
        foundry.summarize_company_history(dispatch_path="/d",
            products=(_hs("a", shipped=1),), disabled=(), errors=(("e", "m"),)),  # ERRORS
        foundry.summarize_company_history(dispatch_path="/d",
            products=(), disabled=("d",), errors=()),                            # no enabled
    )
    for cs in cases:
        assert _final_verdict_token(cs.render()) == cs.verdict
        assert cs.to_dict()["verdict"] == cs.verdict
        assert _VERDICT_FOR_CODE[cs.exit_code] == cs.verdict


# ==========================================================================
# E. CompanyHistory.render()  (Behavior 5)
# ==========================================================================
def test_b05_render_contains_path_counts_rollup_and_verdict():
    pA = _hs("alpha", shipped=2, reverted=1, broken=1)  # total 4
    pB = _hs("beta", shipped=3)                          # total 3
    cs = foundry.summarize_company_history(
        dispatch_path="/d/fc.json", products=(pA, pB), disabled=(), errors=())
    r = cs.render()
    assert "/d/fc.json" in r, "render must contain the dispatch path"
    assert f"{cs.n_products} gathered" in r
    assert f"{cs.n_disabled} disabled" in r
    assert f"{cs.n_errors} error" in r
    assert _company_rollup(cs) in r, f"company rollup line wrong:\n{r}"
    assert _final_verdict_token(r) == cs.verdict == "OK"
    assert _VERDICT_FOR_CODE[cs.exit_code] == cs.verdict


def test_b05_render_one_line_per_product_with_own_rollup():
    pA = _hs("alpha", shipped=2, reverted=1, broken=1)  # 4 iters
    pB = _hs("beta", shipped=3)                          # 3 iters
    cs = foundry.summarize_company_history(
        dispatch_path="/d", products=(pA, pB), disabled=(), errors=())
    lines = cs.render().splitlines()
    for p in (pA, pB):
        want = _product_rollup(p)
        assert any(p.product in ln and want in ln for ln in lines), \
            f"missing line for product {p.product!r} with its own rollup {want!r}:\n{cs.render()}"


def test_b05_render_disabled_and_error_lines():
    cs = foundry.summarize_company_history(
        dispatch_path="/d", products=(_hs("okp", shipped=1),),
        disabled=("dis1", "dis2"), errors=(("errp", "kaboom message here"),))
    lines = cs.render().splitlines()
    for name in ("dis1", "dis2"):
        assert any(name in ln and "disabled" in ln for ln in lines), \
            f"missing disabled line for {name!r}:\n{cs.render()}"
    assert any("errp" in ln and "ERROR" in ln and "kaboom message here" in ln
               for ln in lines), f"missing error line (name+ERROR+message):\n{cs.render()}"
    assert _final_verdict_token(cs.render()) == cs.verdict == "ERRORS"


def test_b05_render_no_enabled_products_verdict():
    cs = foundry.summarize_company_history(
        dispatch_path="/d", products=(), disabled=("only",), errors=())
    assert _final_verdict_token(cs.render()) == cs.verdict == "no enabled products"


# ==========================================================================
# F. CompanyHistory.to_dict()  (Behavior 6)
# ==========================================================================
def test_b06_to_dict_keys_roundtrip_and_values():
    pA = _hs("alpha", shipped=2, reverted=1, broken=1)  # total 4
    pB = _hs("beta", shipped=3)                          # total 3
    cs = foundry.summarize_company_history(
        dispatch_path="/d/fc.json", products=(pA, pB),
        disabled=("gamma",), errors=(("eps", "boom"),))
    d = cs.to_dict()
    assert json.loads(json.dumps(d)) == d, "to_dict must survive a JSON round-trip"
    expected_keys = {
        "dispatch_config", "products", "disabled", "errors",
        "n_products", "n_disabled", "n_errors",
        "total", "shipped", "reverted", "broken", "exit_code", "verdict",
    }
    assert expected_keys <= set(d), f"missing keys: {expected_keys - set(d)}"
    assert d["dispatch_config"] == "/d/fc.json"
    assert d["products"] == [p.to_dict() for p in (pA, pB)], \
        "products must be each gathered HistorySummary.to_dict() IN ORDER"
    assert d["disabled"] == ["gamma"]
    assert d["errors"] == [{"product": "eps", "message": "boom"}]
    # count/rollup values REUSE the frozen props
    assert (d["n_products"], d["n_disabled"], d["n_errors"]) == \
        (cs.n_products, cs.n_disabled, cs.n_errors) == (2, 1, 1)
    assert (d["total"], d["shipped"], d["reverted"], d["broken"]) == \
        (cs.total, cs.shipped, cs.reverted, cs.broken) == (7, 5, 1, 1)
    assert d["exit_code"] == cs.exit_code == 1
    assert d["verdict"] == cs.verdict == "ERRORS"


# ==========================================================================
# G. PURE keyword-only summarize_company_history(...)  (Behavior 7)
# ==========================================================================
def test_b07_keyword_only_and_materializes_tuples():
    with pytest.raises(TypeError):
        foundry.summarize_company_history("/d", (), (), ())  # positional -> keyword-only
    cs = foundry.summarize_company_history(
        dispatch_path="/d",
        products=[_hs("a", shipped=1)],     # list, not tuple
        disabled=["x", "y"],
        errors=[("p", "msg")])
    assert isinstance(cs.products, tuple)
    assert isinstance(cs.disabled, tuple) and cs.disabled == ("x", "y")
    assert isinstance(cs.errors, tuple) and cs.errors == (("p", "msg"),)
    assert all(isinstance(e, tuple) and len(e) == 2 for e in cs.errors)


def test_b07_never_raises_for_wellformed_and_no_filesystem(tmp_path):
    probe = tmp_path / "cfg.json"
    try:
        foundry.summarize_company_history(dispatch_path="/d", products=(),
                                          disabled=(), errors=())
        foundry.summarize_company_history(dispatch_path=str(probe),
                                          products=(_hs("a"),), disabled=("d",),
                                          errors=(("p", "m"),))
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"summarize_company_history raised for well-formed inputs: {e!r}")
    assert not probe.exists(), "pure constructor must touch NO filesystem"


# ==========================================================================
# H. company_history_cli mechanics  (Behavior 8)
# ==========================================================================
def test_b08_enabled_loaded_disabled_recorded_never_loaded(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": False},
        {"name": "gamma", "config": str(tmp_path / "gamma.json"), "enabled": True},
    ])
    loaded = _patch_cli(monkeypatch, {"alpha": _hs("alpha", shipped=1),
                                      "gamma": _hs("gamma", shipped=2)})
    rc, out = _run_chc(str(disp))
    assert rc == 0
    assert set(loaded) == {str(tmp_path / "alpha.json"), str(tmp_path / "gamma.json")}
    assert str(tmp_path / "beta.json") not in loaded, \
        "a DISABLED work item must NOT be load_config'd"
    assert "alpha" in out and "gamma" in out
    assert any("beta" in ln and "disabled" in ln for ln in out.splitlines()), \
        "the disabled item must still be listed as disabled"


def test_b08_foundry_token_substituted_before_load(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": "{FOUNDRY}/products/alpha/config.json",
         "enabled": True},
    ])
    loaded = _patch_cli(monkeypatch, {"alpha": _hs("alpha", shipped=1)})
    _run_chc(str(disp))
    froot = str(pathlib.Path(foundry.__file__).resolve().parent)
    assert loaded == [f"{froot}/products/alpha/config.json"], \
        f"{{FOUNDRY}} must be substituted to the foundry root before load: {loaded}"
    assert "{FOUNDRY}" not in "".join(loaded)


# ==========================================================================
# I. one bad team never sinks the roll-up  (Behavior 9)
# ==========================================================================
def test_b09_load_error_recorded_continues_exit1(tmp_path, monkeypatch):
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
    monkeypatch.setattr(foundry, "gather_history",
                        lambda cfg, limit=None: _hs(
                            "good" if "good.json" in cfg._path else "good2", shipped=1))
    rc, out = _run_chc(str(disp))
    assert rc == 1, "a failing work item must make the company exit 1"
    assert "bad" in out and "ERROR" in out and "kaboom loading bad" in out, \
        f"the failing item + its message must be recorded:\n{out}"
    assert "good" in out and "good2" in out, "gathering must CONTINUE past the failure"


def test_b09_gather_error_recorded(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "boomp", "config": str(tmp_path / "boomp.json"), "enabled": True},
    ])
    monkeypatch.setattr(foundry, "load_config", lambda p: type("C", (), {})())

    def fake_gather(cfg, limit=None):
        raise ValueError("gather blew up")

    monkeypatch.setattr(foundry, "gather_history", fake_gather)
    rc, out = _run_chc(str(disp))
    assert rc == 1
    assert "boomp" in out and "ERROR" in out and "gather blew up" in out


def test_b09_error_recorded_as_name_and_str_exc(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "bad", "config": str(tmp_path / "bad.json"), "enabled": True},
    ])

    def fake_load(path):
        raise RuntimeError("explode")

    monkeypatch.setattr(foundry, "load_config", fake_load)
    rc, out = _run_chc(str(disp), as_json=True)
    doc = json.loads(out.strip())
    assert doc["exit_code"] == 1
    assert {"product": "bad", "message": "explode"} in doc["errors"], \
        f"error must be recorded as (name, str(exc)): {doc['errors']}"


# ==========================================================================
# J. malformed dispatch config surfaced, not crashed  (Behavior 10)
# ==========================================================================
def test_b10_missing_dispatch_file_exit1_no_raise(tmp_path):
    rc, out = _run_chc(str(tmp_path / "does-not-exist.json"))
    assert rc == 1 and "ERROR" in out


def test_b10_invalid_json_exit1_no_raise(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json ]")
    rc, out = _run_chc(str(bad))
    assert rc == 1 and "ERROR" in out


def test_b10_not_a_json_object_exit1(tmp_path):
    lst = tmp_path / "list.json"
    lst.write_text("[1, 2, 3]")
    rc, _ = _run_chc(str(lst))
    assert rc == 1


def test_b10_synthetic_error_keyed_by_dispatch_path(tmp_path):
    missing = tmp_path / "nope.json"
    rc, out = _run_chc(str(missing), as_json=True)
    doc = json.loads(out.strip())  # still exactly one parseable JSON doc
    assert rc == 1 and doc["exit_code"] == 1 and len(doc["errors"]) >= 1
    assert any(e["product"] == str(missing) for e in doc["errors"]), \
        f"the ONE synthetic error must be keyed by the dispatch path: {doc['errors']}"


# ==========================================================================
# K. --limit flows to EACH product  (Behavior 11)
# ==========================================================================
def test_b11_limit_flows_to_every_product(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    seen = []
    monkeypatch.setattr(foundry, "load_config",
                        lambda p: type("C", (), {"_path": p})())

    def fake_gather(cfg, limit=None):
        seen.append(limit)
        return _hs("x", shipped=1)

    monkeypatch.setattr(foundry, "gather_history", fake_gather)
    _run_chc(str(disp), limit=2)
    assert seen == [2, 2], f"--limit must flow to EACH gather_history call: {seen}"


# ==========================================================================
# L. --json vs human + read-only  (Behavior 12)
# ==========================================================================
def test_b12_json_is_single_indent2_document_same_exit(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _hs("alpha", shipped=1),
                             "beta": _hs("beta", shipped=2, broken=1)})
    rc_h, _ = _run_chc(str(disp), as_json=False)
    rc_j, out_j = _run_chc(str(disp), as_json=True)
    doc = json.loads(out_j.strip())  # exactly ONE parseable JSON document
    assert out_j.strip() == json.dumps(doc, indent=2), \
        "the --json path must print exactly one json.dumps(to_dict(), indent=2) doc"
    assert rc_j == rc_h == doc["exit_code"] == 0
    assert [p["product"] for p in doc["products"]] == ["alpha", "beta"]


def test_b12_human_path_prints_render(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    hsA = _hs("alpha", shipped=1)
    hsB = _hs("beta", shipped=2, broken=1)
    _patch_cli(monkeypatch, {"alpha": hsA, "beta": hsB})
    rc, out = _run_chc(str(disp), as_json=False)
    expected = foundry.summarize_company_history(
        dispatch_path=str(disp), products=(hsA, hsB), disabled=(), errors=())
    assert out.rstrip("\n") == expected.render().rstrip("\n"), \
        f"human path must print render():\n{out}"
    assert rc == expected.exit_code


def test_b12_read_only_writes_nothing_to_disk(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _hs("alpha", shipped=1)})
    before = _snapshot_tree(tmp_path)
    _run_chc(str(disp), as_json=False)
    _run_chc(str(disp), as_json=True)
    assert _snapshot_tree(tmp_path) == before, \
        "company-history wrote to disk (must be read-only)"


# ==========================================================================
# M. CLI registration + live smoke  (Behavior 13)
# ==========================================================================
def test_b13_subcommand_help_has_config_limit_json():
    out = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = out
    try:
        with pytest.raises(SystemExit) as ei:
            foundry.main(["company-history", "--help"])
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    assert ei.value.code == 0
    text = out.getvalue()
    assert "--config" in text and "--limit" in text and "--json" in text


def test_b13_default_config_is_repo_dispatch_config(monkeypatch):
    captured = {}

    def spy(dispatch_path, limit=None, as_json=False):
        captured.update(dp=dispatch_path, limit=limit, js=as_json)
        return 0

    monkeypatch.setattr(foundry, "company_history_cli", spy)
    rc = foundry.main(["company-history"])
    assert rc == 0
    froot = pathlib.Path(foundry.__file__).resolve().parent
    assert captured["dp"] == str(froot / "foundry.config.json"), \
        "default --config must be the repo's DISPATCH config (foundry.config.json)"
    assert captured["limit"] is None and captured["js"] is False


def test_b13_limit_is_int_and_json_flag_pass_through(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        foundry, "company_history_cli",
        lambda dp, limit=None, as_json=False:
            captured.update(dp=dp, limit=limit, js=as_json) or 0)
    foundry.main(["company-history", "--limit", "5", "--json"])
    assert captured["limit"] == 5 and isinstance(captured["limit"], int)
    assert captured["js"] is True


def test_b13_dispatched_before_load_config(monkeypatch):
    monkeypatch.setattr(foundry, "company_history_cli",
                        lambda dp, limit=None, as_json=False: 0)

    def boom(path):
        raise AssertionError(f"main called load_config(args.config)={path!r}")

    monkeypatch.setattr(foundry, "load_config", boom)
    assert foundry.main(["company-history", "--config", "whatever.json"]) == 0


def test_b13_live_smoke_on_real_dispatch_config():
    froot = pathlib.Path(foundry.__file__).resolve().parent
    if not (froot / "foundry.config.json").exists():
        pytest.skip(
            "machine-local foundry.config.json absent at repo root (gitignored); "
            "live smoke needs the operator's real dispatch config"
        )
    rc_h, _ = _run_cli(["company-history"])
    rc_j, out_j = _run_cli(["company-history", "--json"])
    doc = json.loads(out_j.strip())  # ONE parseable JSON document
    assert rc_j == rc_h == doc["exit_code"], "json/human exit codes must agree"
    assert doc["verdict"] == _VERDICT_FOR_CODE[doc["exit_code"]]
    names = [p["product"] for p in doc["products"]]
    assert "_platform" in names, f"the enabled _platform team must be gathered: {names}"
    assert "repolens" in doc["disabled"], f"repolens is disabled: {doc['disabled']}"


# ==========================================================================
# N. invariants intact  (Behavior 14)
# ==========================================================================
def test_b14_imports_and_control_flow_functions_intact():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"
    assert dispatcher is not None
    for fn in ("build_prompt", "run_stage", "run_iteration", "run_continuous"):
        assert callable(getattr(foundry, fn, None)), f"missing control-flow fn {fn}"


def test_b14_new_surface_present_and_reuses_parser():
    for name in ("gather_history", "summarize_company_history", "company_history_cli"):
        assert callable(getattr(foundry, name, None)), f"missing {name}"
    assert hasattr(foundry, "CompanyHistory")
    # iter-30 parser REUSED, not re-added:
    assert callable(foundry.parse_dispatch_work_items)
