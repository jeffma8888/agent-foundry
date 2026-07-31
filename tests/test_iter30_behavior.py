"""Black-box behaviour tests for iter 30 -- `foundry company-status`, a read-only,
offline COMPANY-scope health roll-up over the DISPATCH config
(`foundry.config.json`), aggregating each ENABLED product team's existing iter-16
`StatusSummary` into ONE verdict + a `0` healthy / `1` needs-attention /
`2` no-enabled-products exit code (human or `--json`). ALL additive in foundry.py:

  * a PURE `parse_dispatch_work_items(dispatch) -> tuple[(name, config, enabled)]`,
  * a NEW module-level seam `gather_status(cfg) -> StatusSummary` that `status_cli`
    now prints (output-preserving refactor of iter 16),
  * a FROZEN dataclass `CompanyStatus(dispatch_path, products, disabled, errors)`
    with `n_*`/`attention`/`ok`/`exit_code`/`verdict` props + `render()` + `to_dict()`,
  * a PURE keyword-only `summarize_company(...) -> CompanyStatus`,
  * a `company_status_cli(dispatch_path, as_json=False) -> int` wired to a new
    argparse subcommand `company-status`.

ISOLATION CONTRACT (honored): this file was written from the iter-30 PM spec's
Expected Behaviors (1-14) and the product's own OBSERVABLE behaviour ONLY. The
implementation source (foundry.py / dispatcher.py internals), the engineer's and
reviewer's notes, and `git diff` were NOT read. Every check drives the PUBLIC
interface: the pure fns via `foundry.parse_dispatch_work_items(...)` /
`foundry.summarize_company(...)`, the dataclasses via `foundry.CompanyStatus(...)`
/ `foundry.StatusSummary(...)`, and the CLI via `foundry.main(["company-status",
...])` / `foundry.company_status_cli(...)` against tiny dispatch JSON files in
`tmp_path`, monkeypatching `foundry.load_config` / `foundry.gather_status` (the
real product repos / state / git / network are NEVER touched). The wiring /
default-config / dispatch-before-load-config checks (Behavior 14) use only public
RUNTIME introspection -- `--help` output and a spy on the public
`company_status_cli` -- NOT the source text. Fully offline & deterministic.
"""
import dataclasses
import io
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers
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


def _run_csc(dispatch_path, as_json=False):
    """Drive company_status_cli directly, capturing (rc, stdout+stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.company_status_cli(dispatch_path, as_json=as_json)
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
    p = tmp_path / name
    p.write_text(json.dumps({"work_items": work_items}))
    return p


def _write_product_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir (mirrors iter16 convention);
    `repo`/`work_root` are TMP so the real foundry repo/state is NEVER touched."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _ss(product="alpha", repo="/r", branch="main", latest_iter=3,
        postrelease="HEALTHY", hotfix=False, speed_story=False, prd_line=None):
    """Build a StatusSummary positionally in the spec's field order."""
    return foundry.StatusSummary(product, repo, branch, latest_iter,
                                 postrelease, hotfix, speed_story, prd_line)


# fixed exit-code <-> verdict mapping asserted throughout
_VERDICT_FOR_CODE = {0: "OK", 1: "ATTENTION", 2: "no enabled products"}


# ==========================================================================
# A. PURE  parse_dispatch_work_items(dispatch)  (Behaviors 1-2)
# ==========================================================================

# --- Behavior 1 -- triples in file order; sensible defaults ----------------
def test_b01_triples_in_file_order_with_defaults():
    pdw = foundry.parse_dispatch_work_items
    got = pdw({"work_items": [
        {"name": "a", "config": "ca", "enabled": True},
        {"name": "b", "config": "cb"},                     # enabled defaults True
        {"name": "c", "config": "cc", "enabled": False},
    ]})
    assert got == (("a", "ca", True), ("b", "cb", True), ("c", "cc", False)), \
        f"must be (name, config, enabled) triples IN FILE ORDER, got {got!r}"


def test_b01_missing_name_config_default_empty_string():
    pdw = foundry.parse_dispatch_work_items
    assert pdw({"work_items": [{}]}) == (("", "", True),), \
        "absent name/config default to '' and absent enabled defaults to True"
    assert pdw({"work_items": [{"enabled": False}]}) == (("", "", False),)


# --- Behavior 2 -- tolerant / never raises for any dict input --------------
def test_b02_missing_none_or_non_list_work_items_is_empty():
    pdw = foundry.parse_dispatch_work_items
    assert pdw({}) == ()
    assert pdw({"work_items": None}) == ()
    assert pdw({"work_items": "not-a-list"}) == ()
    assert pdw({"work_items": 123}) == ()
    assert pdw({"work_items": {"name": "x"}}) == ()  # a dict is not a list


def test_b02_skips_non_dict_entries_never_raises():
    pdw = foundry.parse_dispatch_work_items
    got = pdw({"work_items": [1, "x", None, {"name": "ok", "config": "c"}, ["nested"]]})
    assert got == (("ok", "c", True),), \
        f"non-dict list entries must be SKIPPED, keeping only dict items: {got!r}"


def test_b02_never_raises_for_any_dict_input():
    pdw = foundry.parse_dispatch_work_items
    weird = [
        {}, {"work_items": []}, {"work_items": [{}]},
        {"work_items": [{"name": 42, "config": None}]},   # odd value types
        {"work_items": [{"enabled": "yes"}]},
        {"unrelated": "key"},
        {"work_items": [{"name": "a"}, 5, {"config": "c"}]},
    ]
    for d in weird:
        try:
            pdw(d)
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"parse_dispatch_work_items raised on {d!r}: {e!r}")


# ==========================================================================
# B. gather_status seam + status_cli output-preserving refactor  (Behavior 3)
# ==========================================================================

# --- Behavior 3 -- gather_status returns the iter-16 StatusSummary ---------
def test_b03_gather_status_returns_status_summary_for_real_state(tmp_path):
    cfg = foundry.load_config(str(_write_product_cfg(tmp_path)))
    st = pathlib.Path(cfg.state) / "iter-05"
    st.mkdir(parents=True)
    (st / "postrelease.md").write_text("report\n\nPOSTRELEASE: HEALTHY\n")
    ss = foundry.gather_status(cfg)
    assert isinstance(ss, foundry.StatusSummary)
    assert ss.latest_iter == 5 and ss.postrelease == "HEALTHY"
    assert ss.verdict == "OK" and ss.exit_code == 0


def test_b03_gather_status_signal_seams_are_monkeypatchable(tmp_path, monkeypatch):
    """gather_status must call its signal seams by BARE module name so a
    monkeypatch bites (the spec's Behavior-3 seam contract)."""
    cfg = foundry.load_config(str(_write_product_cfg(tmp_path)))
    monkeypatch.setattr(foundry, "next_iteration", lambda c: 99)  # latest = 98
    assert foundry.gather_status(cfg).latest_iter == 98, \
        "patching foundry.next_iteration must change gather_status().latest_iter"
    hf = tmp_path / "HF.md"
    hf.write_text("hotfix needed")
    monkeypatch.setattr(foundry, "hotfix_flag_path", lambda c: hf)
    ss = foundry.gather_status(cfg)
    assert ss.hotfix is True and ss.attention is True, \
        "patching foundry.hotfix_flag_path to a raised flag must bite gather_status"


def test_b03_status_cli_is_thin_printer_over_gather_status(tmp_path, monkeypatch):
    """The extraction must not change `foundry status`: status_cli prints exactly
    gather_status(cfg).render() and returns its exit_code (human + --json)."""
    cfg = foundry.load_config(str(_write_product_cfg(tmp_path)))
    sentinel = _ss(product="demoprod", latest_iter=7, postrelease="BROKEN",
                   prd_line="prd 2/5")
    monkeypatch.setattr(foundry, "gather_status", lambda c: sentinel)
    rc, out = _run_cli(["status", "--config", str(_write_product_cfg(tmp_path))])
    assert rc == sentinel.exit_code == 1
    assert out.rstrip("\n") == sentinel.render().rstrip("\n"), \
        f"human status output must equal gather_status().render():\n{out}"
    # --json path also routes through the same seam
    rc2, out2 = _run_cli(["status", "--config", str(_write_product_cfg(tmp_path)),
                          "--json"])
    assert rc2 == sentinel.exit_code
    assert json.loads(out2.strip()) == sentinel.to_dict(), \
        "status --json must be json.dumps(gather_status().to_dict())"


# ==========================================================================
# C. PURE  summarize_company(...)  (Behaviors 4-7)
# ==========================================================================

# --- Behavior 4 -- healthy company -> exit 0 / OK --------------------------
def test_b04_all_healthy_no_errors_exit0_ok():
    cs = foundry.summarize_company(
        dispatch_path="/d/foundry.config.json",
        products=(_ss("alpha"), _ss("beta", latest_iter=2)),
        disabled=("gamma",), errors=())
    assert cs.attention is False and cs.ok is True
    assert cs.exit_code == 0 and cs.verdict == "OK"


def test_b04_summarize_company_is_keyword_only():
    with pytest.raises(TypeError):
        foundry.summarize_company("/d", (), (), ())  # positional -> keyword-only


def test_b04_summarize_company_never_raises_for_wellformed():
    try:
        foundry.summarize_company(dispatch_path="/d", products=(), disabled=(),
                                  errors=())
        foundry.summarize_company(dispatch_path="/d", products=(_ss(),),
                                  disabled=("x", "y"),
                                  errors=(("p", "msg"),))
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"summarize_company raised for well-formed inputs: {e!r}")


# --- Behavior 5 -- any attention product -> exit 1 / ATTENTION -------------
def test_b05_broken_product_makes_company_attention():
    cs = foundry.summarize_company(
        dispatch_path="/d", products=(_ss("ok"), _ss("bad", postrelease="BROKEN")),
        disabled=(), errors=())
    assert cs.attention is True and cs.ok is False
    assert cs.exit_code == 1 and cs.verdict == "ATTENTION"


def test_b05_hotfix_product_makes_company_attention():
    cs = foundry.summarize_company(
        dispatch_path="/d", products=(_ss("ok"), _ss("hf", hotfix=True)),
        disabled=(), errors=())
    assert cs.attention is True and cs.exit_code == 1 and cs.verdict == "ATTENTION"


# --- Behavior 6 -- non-empty errors -> exit 1 regardless of healthy --------
def test_b06_errors_force_attention_even_with_healthy_products():
    cs = foundry.summarize_company(
        dispatch_path="/d", products=(_ss("ok1"), _ss("ok2")),
        disabled=(), errors=(("boom", "load failed"),))
    assert cs.attention is True and cs.ok is False and cs.exit_code == 1


def test_b06_errors_only_no_products_is_attention_not_noproducts():
    # errors present but no gathered products -> still exit 1 (not the exit-2
    # "no enabled products" verdict, which requires NO errors)
    cs = foundry.summarize_company(dispatch_path="/d", products=(), disabled=(),
                                   errors=(("z", "bad"),))
    assert cs.exit_code == 1 and cs.verdict == "ATTENTION"


# --- Behavior 7 -- no products AND no errors -> exit 2 ---------------------
def test_b07_no_products_no_errors_exit2_disabled_preserved():
    cs = foundry.summarize_company(dispatch_path="/d", products=(),
                                   disabled=("a", "b"), errors=())
    assert cs.attention is False and cs.exit_code == 2
    assert cs.verdict == "no enabled products"
    assert cs.disabled == ("a", "b"), "disabled names must be preserved"


def test_b07_empty_work_items_is_no_enabled_products():
    cs = foundry.summarize_company(dispatch_path="/d", products=(), disabled=(),
                                   errors=())
    assert cs.exit_code == 2 and cs.verdict == "no enabled products"


# ==========================================================================
# D. CompanyStatus.render()  (Behavior 8)
# ==========================================================================
def _final_verdict_token(text):
    """Return the token after the final `verdict:` line."""
    lines = [ln for ln in text.splitlines() if ln.strip().lower().startswith("verdict:")]
    assert lines, f"no `verdict:` line found in:\n{text}"
    return lines[-1].split(":", 1)[1].strip()


def test_b08_render_contains_path_counts_and_verdict():
    cs = foundry.summarize_company(
        dispatch_path="/d/fc.json",
        products=(_ss("alpha"), _ss("beta", postrelease="BROKEN"),
                  _ss("gamma", hotfix=True)),
        disabled=("delta",), errors=(("eps", "boom: load failed"),))
    r = cs.render()
    assert "/d/fc.json" in r, "render must contain the dispatch path"
    # counts line: gathered / ok / attention / disabled / error counts
    assert f"{cs.n_products} gathered" in r
    assert f"{cs.n_ok} ok" in r
    assert f"{cs.n_attention} attention" in r
    assert f"{cs.n_disabled} disabled" in r
    assert f"{cs.n_errors} error" in r
    # final verdict line token EQUALS verdict (and therefore matches exit_code)
    assert _final_verdict_token(r) == cs.verdict == "ATTENTION"
    assert _VERDICT_FOR_CODE[cs.exit_code] == cs.verdict


def test_b08_render_one_line_per_gathered_product_with_verdict_token():
    prods = (_ss("alpha"), _ss("beta", postrelease="BROKEN"),
             _ss("gamma", hotfix=True))
    cs = foundry.summarize_company(dispatch_path="/d", products=prods,
                                   disabled=(), errors=())
    lines = cs.render().splitlines()
    for p in prods:
        matched = [ln for ln in lines if p.product in ln and p.verdict in ln
                   and "disabled" not in ln and "ERROR" not in ln]
        assert matched, f"missing a line for gathered product {p.product!r} " \
                        f"with its verdict token {p.verdict!r}:\n{cs.render()}"


def test_b08_attention_product_line_marks_broken_and_hotfix():
    both = _ss("omega", postrelease="BROKEN", hotfix=True)
    cs = foundry.summarize_company(dispatch_path="/d", products=(_ss("okp"), both),
                                   disabled=(), errors=())
    lines = cs.render().splitlines()
    omega_line = [ln for ln in lines if "omega" in ln][0]
    assert "BROKEN" in omega_line, "a BROKEN product's line must contain 'BROKEN'"
    assert "hotfix" in omega_line, "a hotfix product's line must contain 'hotfix'"
    okp_line = [ln for ln in lines if "okp" in ln][0]
    assert "BROKEN" not in okp_line and "hotfix" not in okp_line, \
        "a healthy product's line must not carry attention markers"


def test_b08_render_one_line_per_disabled_and_per_error():
    cs = foundry.summarize_company(
        dispatch_path="/d", products=(_ss("okp"),),
        disabled=("dis1", "dis2"),
        errors=(("errp", "kaboom message here"),))
    lines = cs.render().splitlines()
    for name in ("dis1", "dis2"):
        assert any(name in ln and "disabled" in ln for ln in lines), \
            f"missing disabled line for {name!r}:\n{cs.render()}"
    err_lines = [ln for ln in lines
                 if "errp" in ln and "ERROR" in ln and "kaboom message here" in ln]
    assert err_lines, f"missing error line with name+ERROR+message:\n{cs.render()}"


def test_b08_render_no_enabled_products_final_verdict_matches():
    cs = foundry.summarize_company(dispatch_path="/d", products=(),
                                   disabled=("only",), errors=())
    assert _final_verdict_token(cs.render()) == cs.verdict == "no enabled products"


# ==========================================================================
# E. CompanyStatus.to_dict()  (Behavior 9)
# ==========================================================================
def test_b09_to_dict_json_roundtrips_with_expected_keys():
    prods = (_ss("alpha"), _ss("beta", postrelease="BROKEN"))
    cs = foundry.summarize_company(dispatch_path="/d/fc.json", products=prods,
                                   disabled=("gamma",),
                                   errors=(("eps", "boom"),))
    d = cs.to_dict()
    # JSON-native: round-trips unchanged
    assert json.loads(json.dumps(d)) == d
    expected_keys = {
        "dispatch_config", "products", "disabled", "errors",
        "n_products", "n_ok", "n_attention", "n_disabled", "n_errors",
        "attention", "ok", "exit_code", "verdict",
    }
    assert expected_keys <= set(d), f"missing keys: {expected_keys - set(d)}"
    assert d["dispatch_config"] == "/d/fc.json"
    # products is each StatusSummary.to_dict() IN ORDER
    assert d["products"] == [p.to_dict() for p in prods]
    assert d["disabled"] == ["gamma"]
    assert d["errors"] == [{"product": "eps", "message": "boom"}]


def test_b09_to_dict_reuses_frozen_props_agrees_with_render_and_exit():
    cs = foundry.summarize_company(
        dispatch_path="/d", products=(_ss("ok"), _ss("hf", hotfix=True)),
        disabled=("x",), errors=())
    d = cs.to_dict()
    assert d["attention"] == cs.attention
    assert d["ok"] == cs.ok
    assert d["exit_code"] == cs.exit_code
    assert d["verdict"] == cs.verdict == _final_verdict_token(cs.render())
    assert d["n_products"] == cs.n_products == 2
    assert d["n_attention"] == cs.n_attention == 1
    assert _VERDICT_FOR_CODE[d["exit_code"]] == d["verdict"]


def test_b09_companystatus_is_frozen():
    cs = foundry.summarize_company(dispatch_path="/d", products=(_ss(),),
                                   disabled=(), errors=())
    assert dataclasses.is_dataclass(cs) and type(cs).__name__ == "CompanyStatus"
    with pytest.raises(dataclasses.FrozenInstanceError):
        cs.dispatch_path = "/other"


# ==========================================================================
# F. company_status_cli(...)  (Behaviors 10-13)
# ==========================================================================
def _patch_cli(monkeypatch, verdict_by_name):
    """Monkeypatch load_config (returns a cfg tagged with the resolved path) and
    gather_status (returns a StatusSummary per product name). Records the paths
    load_config was called with in the returned list."""
    loaded = []

    class _Cfg:
        def __init__(self, path):
            self._path = path

    def fake_load(path):
        loaded.append(path)
        return _Cfg(path)

    def fake_gather(cfg):
        # map the config path back to a product via verdict_by_name lookup order:
        # tests build cfgs whose path encodes the product name.
        for name, ss in verdict_by_name.items():
            if name in cfg._path:
                return ss
        return _ss("unknown")

    monkeypatch.setattr(foundry, "load_config", fake_load)
    monkeypatch.setattr(foundry, "gather_status", fake_gather)
    return loaded


# --- Behavior 10 -- human path, disabled skipped, {FOUNDRY} substituted ----
def test_b10_cli_human_prints_render_returns_exit_code(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    loaded = _patch_cli(monkeypatch, {
        "alpha": _ss("alpha"),
        "beta": _ss("beta", postrelease="BROKEN"),
    })
    before = _snapshot_tree(tmp_path)
    rc, out = _run_csc(str(disp))
    assert rc == 1, f"a BROKEN product must make the company exit 1:\n{out}"
    assert "alpha" in out and "beta" in out and "ATTENTION" in out
    assert _final_verdict_token(out) == "ATTENTION"
    # read-only: writes no artifact of its own
    assert _snapshot_tree(tmp_path) == before, "company-status wrote a file"
    assert len(loaded) == 2, "both enabled items loaded exactly once"


def test_b10_disabled_item_is_never_loaded(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": False},
    ])
    loaded = _patch_cli(monkeypatch, {"alpha": _ss("alpha")})
    rc, out = _run_csc(str(disp))
    assert rc == 0
    assert str(tmp_path / "beta.json") not in loaded, \
        "a DISABLED work item must NOT be load_config'd"
    assert "beta" in out and "disabled" in out, "disabled item still listed"


def test_b10_foundry_token_substituted_before_load(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": "{FOUNDRY}/products/alpha/config.json",
         "enabled": True},
    ])
    loaded = _patch_cli(monkeypatch, {"alpha": _ss("alpha")})
    rc, out = _run_csc(str(disp))
    froot = str(pathlib.Path(foundry.__file__).resolve().parent)
    assert loaded == [f"{froot}/products/alpha/config.json"], \
        f"{{FOUNDRY}} must be substituted to the foundry root before load: {loaded}"
    assert "{FOUNDRY}" not in "".join(loaded)


# --- Behavior 11 -- --json path -------------------------------------------
def test_b11_cli_json_one_document_same_exit_code(tmp_path, monkeypatch):
    items = [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ]
    disp = _write_dispatch(tmp_path, items)
    _patch_cli(monkeypatch, {"alpha": _ss("alpha"),
                             "beta": _ss("beta", hotfix=True)})
    rc_h, _ = _run_csc(str(disp), as_json=False)
    rc_j, out_j = _run_csc(str(disp), as_json=True)
    doc = json.loads(out_j.strip())  # exactly ONE parseable JSON document
    assert rc_j == rc_h == 1, "json exit code must equal the human path's"
    assert doc["exit_code"] == rc_j
    assert doc["verdict"] == _VERDICT_FOR_CODE[rc_j]
    assert [p["product"] for p in doc["products"]] == ["alpha", "beta"]


# --- Behavior 12 -- a work item raises -> recorded, continue, exit 1 -------
def test_b12_load_or_gather_error_recorded_continues_exit1(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "good", "config": str(tmp_path / "good.json"), "enabled": True},
        {"name": "bad", "config": str(tmp_path / "bad.json"), "enabled": True},
    ])

    def fake_load(path):
        if "bad.json" in path:
            raise RuntimeError("kaboom loading bad")
        return type("C", (), {"_path": path})()

    monkeypatch.setattr(foundry, "load_config", fake_load)
    monkeypatch.setattr(foundry, "gather_status",
                        lambda cfg: _ss("good"))
    rc, out = _run_csc(str(disp))
    assert rc == 1, "a failing work item must make the company exit 1"
    assert "bad" in out and "ERROR" in out and "kaboom loading bad" in out, \
        f"the failing item + message must be recorded:\n{out}"
    assert "good" in out, "gathering must CONTINUE past the failure"


def test_b12_gather_error_also_recorded(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "boomp", "config": str(tmp_path / "boomp.json"), "enabled": True},
    ])
    monkeypatch.setattr(foundry, "load_config",
                        lambda p: type("C", (), {})())

    def fake_gather(cfg):
        raise ValueError("gather blew up")

    monkeypatch.setattr(foundry, "gather_status", fake_gather)
    rc, out = _run_csc(str(disp))
    assert rc == 1
    assert "boomp" in out and "ERROR" in out and "gather blew up" in out


# --- Behavior 13 -- bad dispatch config -> synthetic error, exit 1 ---------
def test_b13_missing_dispatch_file_exit1_no_raise(tmp_path):
    rc, out = _run_csc(str(tmp_path / "does-not-exist.json"))
    assert rc == 1 and "ERROR" in out


def test_b13_invalid_json_exit1_no_raise(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json ]")
    rc, out = _run_csc(str(bad))
    assert rc == 1 and "ERROR" in out


def test_b13_not_a_json_object_exit1(tmp_path):
    lst = tmp_path / "list.json"
    lst.write_text("[1, 2, 3]")
    rc, out = _run_csc(str(lst))
    assert rc == 1


def test_b13_bad_dispatch_json_path_still_one_document(tmp_path):
    rc, out = _run_csc(str(tmp_path / "nope.json"), as_json=True)
    assert rc == 1
    doc = json.loads(out.strip())  # still exactly one parseable JSON doc
    assert doc["exit_code"] == 1 and len(doc["errors"]) >= 1


# ==========================================================================
# G. main wiring / additivity  (Behavior 14)
# ==========================================================================
def test_b14_subcommand_wired_with_config_and_json_flags():
    # argparse --help prints usage then raises SystemExit(0)
    out = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = out
    try:
        with pytest.raises(SystemExit) as ei:
            foundry.main(["company-status", "--help"])
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    assert ei.value.code == 0
    text = out.getvalue()
    assert "--config" in text and "--json" in text


def test_b14_default_config_is_repo_dispatch_config(monkeypatch):
    captured = {}

    def spy(dispatch_path, as_json=False):
        captured["dp"] = dispatch_path
        captured["json"] = as_json
        return 0

    monkeypatch.setattr(foundry, "company_status_cli", spy)
    rc = foundry.main(["company-status"])
    assert rc == 0
    froot = pathlib.Path(foundry.__file__).resolve().parent
    assert captured["dp"] == str(froot / "foundry.config.json"), \
        "default --config must be the repo's DISPATCH config (foundry.config.json)"
    assert captured["json"] is False


def test_b14_json_flag_passes_through(monkeypatch):
    captured = {}
    monkeypatch.setattr(foundry, "company_status_cli",
                        lambda dp, as_json=False: captured.update(dp=dp, j=as_json) or 0)
    foundry.main(["company-status", "--json"])
    assert captured["j"] is True


def test_b14_dispatched_before_load_config_of_args_config(monkeypatch):
    """company-status must be dispatched BEFORE main calls load_config(args.config)
    (like single-brain / lint-spec): with company_status_cli spied and load_config
    booby-trapped, main must route to the spy without ever calling load_config."""
    monkeypatch.setattr(foundry, "company_status_cli",
                        lambda dp, as_json=False: 0)

    def boom(path):
        raise AssertionError(f"main called load_config(args.config)={path!r}")

    monkeypatch.setattr(foundry, "load_config", boom)
    assert foundry.main(["company-status", "--config", "whatever.json"]) == 0


def test_b14_imports_and_control_flow_functions_intact():
    # acceptance: `python -c "import foundry, dispatcher"` succeeds, and the
    # pipeline control-flow surface still exists (purely additive, off the path).
    assert dispatcher is not None
    for fn in ("run_iteration", "run_continuous", "run_stage", "build_prompt"):
        assert callable(getattr(foundry, fn, None)), f"missing control-flow fn {fn}"
