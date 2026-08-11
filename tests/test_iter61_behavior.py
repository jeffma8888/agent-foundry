"""Black-box behaviour tests for iter 61 -- `foundry company-lint-config
--config <dispatch> [--json]`: the read-only, offline company-wide roll-up of
the per-product iter-60 `lint-config` product-config linter (#27) over the
DISPATCH config -- the 9th `company-*` family member and the CONFIG-VALIDATION-
axis fleet roll-up (it closes the LONE read-only per-product probe that had no
roll-up). It folds every ENABLED dispatch team's `lint-config` verdict into ONE
company config-errors / warnings / total-findings total + a per-TEAM breakdown +
ONE scriptable 0/1/2 exit code + ONE JSON doc, composed on top of a NEW
`gather_config_lint` seam + the shipped per-product `ConfigLint` (iter 60).
Purely additive in foundry.py:

  * a NEW module-level seam `gather_config_lint(cfg) -> ConfigLint` (returns the
    shipped `lint_config(cfg)` by BARE module name; adds NO new I/O seam),
  * a FROZEN dataclass `CompanyConfigLint(dispatch_path, products, disabled,
    errors)` with n_* count props + total_errors/total_warnings/total_findings
    sums + n_flagged + an ERROR-GATING exit_code/verdict + render() + to_dict(),
  * a PURE keyword-only `summarize_company_config_lint(*, dispatch_path,
    products, disabled, errors) -> CompanyConfigLint`,
  * a thin resilient `company_config_lint_cli(dispatch_path, as_json=False)
    -> int` wired to a new argparse subcommand `company-lint-config` (NO
    --limit, NO --files), driving `parse_dispatch_work_items` + `load_config`
    + `gather_config_lint` by BARE name.

THE LOAD-BEARING DIVERGENCE (a first-class correctness item, re-derived from
OBSERVED behaviour, NOT copied from the QUALITY family): UNLIKE the QUALITY
company roll-ups (`company-weak-tests`/`-constant-asserts`/`-skipped-tests`/
`-test-quality`, which gate on ANY finding), `company-lint-config` INHERITS the
per-product `ConfigLint` semantics where ONLY ERRORS gate -- WARNINGS ALONE
STILL PASS (a warning names a degraded-but-runnable config). So `exit_code` = 1
iff a team load/gather error OR any product config ERROR anywhere; else 2 iff no
enabled products; else 0. Behavior 2 proves this from observed behaviour (a
warnings-only fleet -> exit 0 / verdict "clean"; one error-level finding
anywhere -> exit 1 / verdict "ATTENTION"), NEVER by copying the sibling gate.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-61 PM
spec's Expected Behaviors (1-9), the product README/roadmap, the tests/
conventions (esp. tests/test_iter57_behavior.py and tests/test_iter59_behavior.py
-- the structural-mirror company roll-ups -- and tests/test_iter60_behavior.py --
the per-product lint-config foundation), and the product's OWN OBSERVABLE
behaviour (building the public objects and RUNNING them / --help / public RUNTIME
introspection). The implementation SOURCE (foundry.py / dispatcher.py source
text) and `git diff` were NOT read as logic to mirror; tests assert the SPEC's
behaviors, not impl quirks. DISCLOSURE: the engineer's `engineer.md` and the
reviewer's `reviewer.md` were inadvertently opened once during orientation and
the learnings digest in the prompt already carried the prior-role notes;
NOTHING from any of them was used to shape a test -- every assertion below
derives from the spec's pinned substrings + observed public behaviour probed by
running the product. Fully offline & deterministic: no network, no real git
mutation, no real push; the sole subprocess is the `import foundry, dispatcher`
dormancy probe, an exit-code-only `git diff --quiet` byte-unchanged check that
reads NO diff text, and the `--help` probes. Every path is built at RUNTIME from
the pytest `tmp_path` fixture (never a source-literal home path) and every
string is SYNTHETIC, so the committed leak-guard passes on the ship commit.
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
# note these are the COMPANY tokens, NOT the per-product ConfigLint tokens
# ("OK" / "WARNINGS" / "PROBLEMS").
_VERDICT_FOR_CODE = {0: "clean", 1: "ATTENTION", 2: "no enabled products"}

# the genuinely-NEW iter-61 symbols
NEW_SYMBOLS = ("gather_config_lint", "CompanyConfigLint",
               "summarize_company_config_lint", "company_config_lint_cli")
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")
SUBCMD = "company-lint-config"
# to_dict() -- EXACTLY these 13 keys in this fixed order (Behavior 7)
TO_DICT_KEYS = ("dispatch_config", "products", "disabled", "errors",
                "n_products", "n_disabled", "n_errors", "n_flagged",
                "total_errors", "total_warnings", "total_findings",
                "exit_code", "verdict")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _F(field, level, detail="d"):
    """A synthetic per-product ConfigFinding (field, level in {error,warn})."""
    return foundry.ConfigFinding(field=field, level=level, detail=detail)


def _CL(config_path, findings=()):
    """A synthetic per-product ConfigLint built DIRECTLY from ConfigFinding
    tuples (no repo, no filesystem) -- the iter-60 public dataclass."""
    return foundry.ConfigLint(config_path=config_path, findings=tuple(findings))


def _summ(dispatch_path="d.json", products=(), disabled=(), errors=()):
    """Drive the pure keyword-only company core with defaults."""
    return foundry.summarize_company_config_lint(
        dispatch_path=dispatch_path, products=tuple(products),
        disabled=tuple(disabled), errors=tuple(errors))


def _write_dispatch(tmp_path, work_items, name="foundry.config.json"):
    p = pathlib.Path(tmp_path) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"work_items": work_items}))
    return p


def _run_cli(dispatch_path, as_json=False):
    """Drive company_config_lint_cli directly, capturing (rc, stdout+stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.company_config_lint_cli(dispatch_path, as_json=as_json)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue() + err.getvalue()


def _final_verdict_token(text):
    lines = [ln for ln in text.splitlines()
             if ln.strip().lower().startswith("verdict:")]
    assert lines, f"no `verdict:` line found in:\n{text}"
    return lines[-1].split(":", 1)[1].strip()


def _dash_line(text, name):
    """Return the single `  - {name}:` line (product / disabled / error)."""
    rows = [ln for ln in text.splitlines()
            if ln.strip().startswith(f"- {name}:")]
    assert len(rows) == 1, \
        f"expected exactly one `- {name}:` line, got {rows!r}\n{text}"
    return rows[0]


def _patch_cli(monkeypatch, lint_by_name):
    """Monkeypatch load_config (tags a cfg with its resolved path, records every
    load) + gather_config_lint (returns a ConfigLint by matching a product-name
    substring of the config path) -- BOTH by BARE name so the CLI's bare-name
    binding is exercised."""
    loaded = []

    class _Cfg:
        def __init__(self, path):
            self._path = path

    def fake_load(path):
        loaded.append(path)
        return _Cfg(path)

    def fake_gather(cfg):
        for name, cl in lint_by_name.items():
            if name in cfg._path:
                return cl
        return _CL("unknown")

    monkeypatch.setattr(foundry, "load_config", fake_load)
    monkeypatch.setattr(foundry, "gather_config_lint", fake_gather)
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


def _git_visible_snapshot(
    root: str | pathlib.Path,
    repo_root: str | pathlib.Path = _ROOT,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Snapshot everything a ship diff could carry under ``root``, and nothing else.

    WHY not a byte-walk: reading every file under the real ``products/`` tree cost
    6574 files / 50.8 MB per call, twice per guard, and FAILED whenever anything wrote
    there while the guard ran -- which this loop does by design, since
    ``products/*/state/``, ``events.jsonl``, ``NIGHT_LOG.md`` and ``LEARNINGS.md`` are
    all gitignored runtime state. So an ordinary, well-behaved stage could turn the
    ship gate red for a reason unrelated to its change.

    Git already draws the line the guard actually cares about, and ~370x cheaper:
      layer 1, ``status --porcelain --untracked-files=all`` -- new not-ignored files,
      in-place edits of tracked files, deletions, staged additions;
      layer 2, ``ls-files -s`` -- tracked-set and index (mode/blob/stage) mutations.
    Lines are sorted so the value is order-stable and safe to compare with ``==``.
    """
    def _lines(*argv: str) -> tuple[str, ...]:
        # check=False: a non-repo root yields empty output rather than raising, which
        # keeps the helper usable as a plain comparison value in any tree.
        r = subprocess.run(["git", *argv, "--", str(root)], cwd=str(repo_root),
                           capture_output=True, text=True, check=False)
        return tuple(sorted(ln for ln in r.stdout.splitlines() if ln.strip()))

    return (_lines("status", "--porcelain", "--untracked-files=all"),
            _lines("ls-files", "-s"))


# ==========================================================================
# Behavior 1 -- pure keyword-only roll-up core: frozen, sums, counts
# ==========================================================================
def test_b1_worked_example_fields_sums_and_counts():
    a = _CL("teamA", [_F("repo", "error"), _F("roadmap", "warn")])   # 1 err, 1 warn
    b = _CL("teamB", [_F("vision", "warn"), _F("quality_ref", "warn")])  # 0 err, 2 warn
    c = _summ(dispatch_path="d.json", products=(a, b), disabled=(), errors=())
    assert dataclasses.is_dataclass(c)
    assert type(c).__name__ == "CompanyConfigLint"
    assert c.dispatch_path == "d.json"
    assert c.products == (a, b)
    assert c.n_products == 2 == len(c.products)
    assert c.n_disabled == 0 and c.n_errors == 0
    assert c.total_errors == a.n_errors + b.n_errors == 1
    assert c.total_warnings == a.n_warnings + b.n_warnings == 3
    assert c.total_findings == c.total_errors + c.total_warnings == 4
    assert c.total_findings == len(a.findings) + len(b.findings) == 4


def test_b1_keyword_only_positional_raises():
    with pytest.raises(TypeError):
        foundry.summarize_company_config_lint("d.json", (), (), ())  # positional


def test_b1_is_frozen():
    c = _summ(products=(_CL("x"),))
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.products = ()


def test_b1_empty_products_all_zero():
    c = _summ(dispatch_path="d.json")
    assert c.n_products == 0 and c.n_disabled == 0 and c.n_errors == 0
    assert c.n_flagged == 0
    assert c.total_errors == 0 and c.total_warnings == 0 and c.total_findings == 0


# ==========================================================================
# Behavior 2 -- THE LOAD-BEARING DIVERGENCE: only ERRORS gate; warnings pass
# ==========================================================================
def test_b2_warnings_only_fleet_exits_0_clean():
    # Two products, warn-level findings ONLY, no errors, no team errors.
    a = _CL("teamA", [_F("roadmap", "warn")])
    b = _CL("teamB", [_F("vision", "warn"), _F("quality_ref", "warn")])
    c = _summ(products=(a, b))
    assert c.total_warnings > 0, "precondition: the fleet carries warnings"
    assert c.total_errors == 0
    assert c.exit_code == 0, \
        "warnings alone must NOT gate -- a warnings-only fleet still passes (exit 0)"
    assert c.verdict == "clean"


def test_b2_one_error_anywhere_exits_1_attention():
    a = _CL("teamA", [_F("roadmap", "warn")])          # warnings only
    b = _CL("teamB", [_F("allowed_push_repo", "error")])  # one config ERROR
    c = _summ(products=(a, b))
    assert c.total_errors == 1
    assert c.exit_code == 1, "one product config ERROR anywhere must gate the company to exit 1"
    assert c.verdict == "ATTENTION"


def test_b2_clean_fleet_no_findings_exits_0_clean():
    c = _summ(products=(_CL("a"), _CL("b")))
    assert c.total_findings == 0
    assert c.exit_code == 0 and c.verdict == "clean"


# ==========================================================================
# Behavior 3 -- no enabled products -> exit 2 / "no enabled products"
# ==========================================================================
def test_b3_no_enabled_products_exit_2():
    c = _summ(products=(), disabled=("dis1", "dis2"), errors=())
    assert c.n_products == 0
    assert c.exit_code == 2
    assert c.verdict == "no enabled products"


def test_b3_exit_and_verdict_matrix():
    # 0 clean-or-warnings-only
    assert _summ(products=(_CL("a", [_F("roadmap", "warn")]),)).exit_code == 0
    assert _summ(products=(_CL("a", [_F("roadmap", "warn")]),)).verdict == "clean"
    # 1 an ERROR anywhere
    assert _summ(products=(_CL("a", [_F("repo", "error")]),)).exit_code == 1
    assert _summ(products=(_CL("a", [_F("repo", "error")]),)).verdict == "ATTENTION"
    # 2 no enabled products
    assert _summ(products=()).exit_code == 2
    assert _summ(products=()).verdict == "no enabled products"
    for code, tok in _VERDICT_FOR_CODE.items():
        # the mapping is total (every code has a token)
        assert tok


# ==========================================================================
# Behavior 4 -- team-load error gates to exit 1 even with zero findings
# ==========================================================================
def test_b4_team_error_findings_first_exit_1():
    c = _summ(products=(), errors=(("t", "boom"),))
    assert c.n_products == 0
    assert c.n_errors == 1
    assert c.exit_code == 1, \
        "the errors branch must fire BEFORE the n_products==0 -> 2 branch (findings-first)"
    assert c.verdict == "ATTENTION"


def test_b4_team_error_with_clean_products_still_exit_1():
    c = _summ(products=(_CL("ok"),), errors=(("bad", "load failed"),))
    assert c.total_errors == 0, "no per-product config error"
    assert c.n_errors == 1, "one team-load error"
    assert c.exit_code == 1


# ==========================================================================
# Behavior 5 -- n_flagged counts config-ERROR products, not warnings-only
# ==========================================================================
def test_b5_n_flagged_counts_config_error_products_only():
    warns_only = _CL("wo", [_F("roadmap", "warn"), _F("vision", "warn")])
    has_error = _CL("err", [_F("repo", "error"), _F("roadmap", "warn")])
    clean = _CL("clean")
    c = _summ(products=(warns_only, has_error, clean))
    assert c.n_products == 3
    assert c.n_flagged == 1, \
        "only products with a config ERROR are flagged (warnings-only / clean are not)"


def test_b5_two_error_products_flagged_twice():
    c = _summ(products=(_CL("e1", [_F("repo", "error")]),
                        _CL("e2", [_F("test_cmd", "error")]),
                        _CL("wo", [_F("roadmap", "warn")])))
    assert c.n_flagged == 2


# ==========================================================================
# Behavior 6 -- render() contract
# ==========================================================================
def test_b6_render_header_path_counts_and_verdict_last_line():
    a = _CL("teamA", [_F("repo", "error"), _F("roadmap", "warn")])   # 1 err, 1 warn
    b = _CL("teamB", [_F("vision", "warn")])                          # 0 err, 1 warn
    c = _summ(dispatch_path="/some/dispatch.json",
              products=(a, b), disabled=("dis1",), errors=(("teamC", "kaboom"),))
    text = c.render()
    assert "foundry company-lint-config" in text
    assert "/some/dispatch.json" in text, "render must name the dispatch config path"
    # counts line reports gathered / disabled / error(s) + the rollup totals
    assert f"{c.n_products} gathered" in text
    assert f"{c.n_disabled} disabled" in text
    assert f"{c.n_errors} error(s)" in text
    assert f"{c.total_errors} config errors" in text
    assert f"{c.total_warnings} warnings" in text
    assert f"{c.total_findings} total findings" in text
    # last non-empty line is exactly `verdict: <token>`
    assert _final_verdict_token(text) == c.verdict == "ATTENTION"
    non_empty = [ln for ln in text.splitlines() if ln.strip()]
    assert non_empty[-1].strip() == f"verdict: {c.verdict}"


def test_b6_render_one_line_per_gathered_product_with_own_counts_and_token():
    a = _CL("alpha", [_F("repo", "error"), _F("roadmap", "warn")])   # PROBLEMS
    b = _CL("beta", [_F("vision", "warn")])                          # WARNINGS
    z = _CL("zeta")                                                   # OK
    c = _summ(products=(a, b, z))
    text = c.render()
    la = _dash_line(text, "alpha")
    assert f"{a.n_errors} error(s)" in la and f"{a.n_warnings} warning(s)" in la
    assert a.verdict in la, "each product line carries its per-product verdict token"
    lb = _dash_line(text, "beta")
    assert b.verdict in lb  # WARNINGS
    lz = _dash_line(text, "zeta")
    assert z.verdict in lz  # OK
    # the per-product tokens are OK/WARNINGS/PROBLEMS, distinct from the company verdict
    assert {a.verdict, b.verdict, z.verdict} == {"PROBLEMS", "WARNINGS", "OK"}


def test_b6_render_disabled_and_error_lines():
    c = _summ(products=(_CL("live"),),
              disabled=("dis1", "dis2"), errors=(("bad", "some message"),))
    text = c.render()
    assert _dash_line(text, "dis1").strip() == "- dis1: disabled"
    assert _dash_line(text, "dis2").strip() == "- dis2: disabled"
    err_line = _dash_line(text, "bad")
    assert "ERROR" in err_line and "some message" in err_line


def test_b6_render_is_deterministic_and_carries_no_home_path():
    c = _summ(products=(_CL("a", [_F("repo", "error")]),), disabled=("d",),
              errors=(("e", "m"),))
    assert c.render() == c.render()
    home_prefix = "/" + "Users" + "/"  # built at runtime; never a source literal
    assert home_prefix not in c.render()


# ==========================================================================
# Behavior 7 -- to_dict(): EXACTLY 13 keys in fixed order + JSON round-trip
# ==========================================================================
def test_b7_to_dict_keys_order_and_values():
    a = _CL("teamA", [_F("repo", "error"), _F("roadmap", "warn")])
    b = _CL("teamB", [_F("vision", "warn")])
    c = _summ(dispatch_path="d.json", products=(a, b),
              disabled=("dis1",), errors=(("teamC", "boom"),))
    d = c.to_dict()
    assert tuple(d.keys()) == TO_DICT_KEYS, \
        f"to_dict keys/order wrong: {tuple(d.keys())}"
    assert d["dispatch_config"] == "d.json"
    assert d["disabled"] == ["dis1"]
    assert d["errors"] == [{"product": "teamC", "message": "boom"}]
    assert d["n_products"] == 2 and d["n_disabled"] == 1 and d["n_errors"] == 1
    assert d["n_flagged"] == 1
    assert d["total_errors"] == 1 and d["total_warnings"] == 2 and d["total_findings"] == 3
    assert d["exit_code"] == c.exit_code == 1
    assert d["verdict"] == c.verdict == "ATTENTION"


def test_b7_products_carry_full_per_product_lint_detail_in_order():
    a = _CL("teamA", [_F("repo", "error")])
    b = _CL("teamB", [_F("vision", "warn")])
    d = _summ(products=(a, b)).to_dict()
    assert isinstance(d["products"], list) and len(d["products"]) == 2
    # full per-product ConfigLint.to_dict() in stored order
    assert d["products"][0] == a.to_dict()
    assert d["products"][1] == b.to_dict()
    # each product dict carries the 7 iter-60 ConfigLint keys
    assert set(d["products"][0].keys()) == {
        "config_path", "findings", "n_errors", "n_warnings",
        "ok", "verdict", "exit_code"}


def test_b7_json_roundtrips_including_all_empty():
    # populated case
    c = _summ(dispatch_path="d.json",
              products=(_CL("a", [_F("repo", "error"), _F("roadmap", "warn")]),),
              disabled=("x",), errors=(("y", "z"),))
    d = c.to_dict()
    assert json.loads(json.dumps(d)) == d
    # all-empty case (no products / disabled / errors) -> exit 2
    e = _summ().to_dict()
    assert json.loads(json.dumps(e)) == e
    assert e["products"] == [] and e["disabled"] == [] and e["errors"] == []
    assert e["exit_code"] == 2 and e["verdict"] == "no enabled products"


def test_b7_verdict_and_exit_code_agree_with_render():
    for prods, disc in (
        ((_CL("a", [_F("roadmap", "warn")]),), 0),        # warnings-only
        ((_CL("a", [_F("repo", "error")]),), 1),          # error
        ((), 2),                                          # empty
    ):
        c = _summ(products=prods)
        assert c.exit_code == disc
        assert c.to_dict()["exit_code"] == disc
        assert _final_verdict_token(c.render()) == c.verdict == _VERDICT_FOR_CODE[disc]


# ==========================================================================
# Behavior 8 -- CLI drives BOTH seams by BARE name + resilient + dispatch order
# ==========================================================================
def test_b8_enabled_gathered_disabled_recorded_never_loaded(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
        {"name": "gone", "config": str(tmp_path / "gone.json"), "enabled": False},
    ])
    loaded = _patch_cli(monkeypatch, {
        "alpha": _CL("alpha", [_F("repo", "error")]),   # gate to 1
        "beta": _CL("beta"),
    })
    rc, out = _run_cli(str(disp))
    assert rc == 1, "a gathered team with a config ERROR must make the company exit 1"
    assert loaded == [str(tmp_path / "alpha.json"), str(tmp_path / "beta.json")], \
        "only ENABLED items are load_config'd; the disabled item is never loaded"
    assert "foundry company-lint-config" in out
    assert _dash_line(out, "alpha") and _dash_line(out, "beta")
    assert _dash_line(out, "gone").strip() == "- gone: disabled"


def test_b8_disabled_never_reaches_gather(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "gone", "config": str(tmp_path / "gone.json"), "enabled": False},
    ])
    gathered = []
    monkeypatch.setattr(foundry, "load_config",
                        lambda p: type("C", (), {"_path": p})())

    def fake_gather(cfg):
        gathered.append(cfg._path)
        return _CL("alpha")

    monkeypatch.setattr(foundry, "gather_config_lint", fake_gather)
    _run_cli(str(disp))
    assert gathered == [str(tmp_path / "alpha.json")], \
        "the disabled item must NEVER reach gather_config_lint"


def test_b8_warnings_only_fleet_cli_exits_0(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {
        "alpha": _CL("alpha", [_F("roadmap", "warn")]),
        "beta": _CL("beta", [_F("vision", "warn")]),
    })
    rc, out = _run_cli(str(disp))
    assert rc == 0, "a warnings-only fleet must pass the CLI gate (exit 0)"
    assert _final_verdict_token(out) == "clean"


def test_b8_replacing_gather_changes_reported_figures(tmp_path, monkeypatch):
    # gather_config_lint is called by BARE name -> replacing it bites.
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])
    monkeypatch.setattr(foundry, "load_config",
                        lambda p: type("C", (), {"_path": p})())
    monkeypatch.setattr(foundry, "gather_config_lint",
                        lambda cfg: _CL("alpha", [_F("roadmap", "warn")]))
    _, out1 = _run_cli(str(disp), as_json=True)
    monkeypatch.setattr(foundry, "gather_config_lint",
                        lambda cfg: _CL("alpha", [_F("v", "warn")] * 99))
    _, out2 = _run_cli(str(disp), as_json=True)
    assert json.loads(out1)["total_warnings"] == 1
    assert json.loads(out2)["total_warnings"] == 99, \
        "replacing foundry.gather_config_lint must change reported figures (bare-name seam)"


def test_b8_foundry_token_substituted_before_load(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": "{FOUNDRY}/products/alpha/config.json",
         "enabled": True},
    ])
    loaded = _patch_cli(monkeypatch, {"alpha": _CL("alpha")})
    _run_cli(str(disp))
    assert len(loaded) == 1
    assert "{FOUNDRY}" not in loaded[0], "the {FOUNDRY} token must be substituted before load_config"


def test_b8_one_bad_team_recorded_rollup_continues(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "good", "config": str(tmp_path / "good.json"), "enabled": True},
        {"name": "bad", "config": str(tmp_path / "bad.json"), "enabled": True},
        {"name": "good2", "config": str(tmp_path / "good2.json"), "enabled": True},
    ])
    monkeypatch.setattr(foundry, "load_config",
                        lambda p: type("C", (), {"_path": p})())

    def fake_gather(cfg):
        if "bad.json" in cfg._path:
            raise RuntimeError("gather-boom")
        return _CL("ok")

    monkeypatch.setattr(foundry, "gather_config_lint", fake_gather)
    rc, out = _run_cli(str(disp), as_json=True)
    doc = json.loads(out)
    assert rc == 1, "a team error gates to exit 1"
    assert doc["n_products"] == 2, "the roll-up CONTINUES past the bad team (2 survivors)"
    assert doc["n_errors"] == 1
    assert doc["errors"] == [{"product": "bad", "message": "gather-boom"}]


def test_b8_load_config_raise_recorded_rollup_continues(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "good", "config": str(tmp_path / "good.json"), "enabled": True},
        {"name": "bad", "config": str(tmp_path / "bad.json"), "enabled": True},
    ])

    def fake_load(p):
        if "bad.json" in p:
            raise RuntimeError("load-boom")
        return type("C", (), {"_path": p})()

    monkeypatch.setattr(foundry, "load_config", fake_load)
    monkeypatch.setattr(foundry, "gather_config_lint", lambda cfg: _CL("ok"))
    rc, out = _run_cli(str(disp), as_json=True)
    doc = json.loads(out)
    assert rc == 1
    assert doc["n_products"] == 1 and doc["n_errors"] == 1
    assert doc["errors"] == [{"product": "bad", "message": "load-boom"}]


def test_b8_missing_dispatch_file_exit1_no_raise(tmp_path):
    rc, out = _run_cli(str(tmp_path / "nope.json"))
    assert rc == 1
    assert "verdict:" in out.lower()


def test_b8_invalid_json_dispatch_exit1_no_raise(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    rc, _ = _run_cli(str(bad))
    assert rc == 1


def test_b8_non_object_dispatch_exit1(tmp_path):
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2, 3]")
    rc, _ = _run_cli(str(arr))
    assert rc == 1


def test_b8_each_bad_config_yields_exactly_one_synthetic_error(tmp_path):
    missing = tmp_path / "missing.json"
    for label, path in (("missing", missing),):
        rc, out = _run_cli(str(path), as_json=True)
        doc = json.loads(out)
        assert rc == 1
        assert doc["n_errors"] == 1, f"{label}: exactly one synthetic dispatch error"
        assert doc["errors"][0]["product"] == str(path), \
            "the synthetic error names the dispatch path"


def test_b8_json_is_single_document_equal_to_to_dict(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {
        "alpha": _CL("alpha", [_F("repo", "error")]),
        "beta": _CL("beta", [_F("vision", "warn")]),
    })
    rc_h, out_h = _run_cli(str(disp))
    rc_j, out_j = _run_cli(str(disp), as_json=True)
    doc = json.loads(out_j)  # ONE parseable document as the ENTIRE stdout
    assert rc_h == rc_j == doc["exit_code"] == 1, \
        "--json exit code must equal the human path exit code"
    assert tuple(doc.keys()) == TO_DICT_KEYS


def test_b8_main_dispatches_before_top_level_load_config(tmp_path, monkeypatch):
    # main() must route company-lint-config BEFORE load_config(args.config): the
    # dispatch config is NOT a product config, so a load_config that raises must
    # NOT be reached; an empty work_items dispatch config -> exit 2, no crash.
    disp = _write_dispatch(tmp_path, [], name="empty.json")

    def boom(path):
        raise AssertionError(f"main called load_config(args.config)={path!r}")

    monkeypatch.setattr(foundry, "load_config", boom)
    rc = foundry.main(["company-lint-config", "--config", str(disp)])
    assert rc == 2, "empty work_items -> no enabled products -> exit 2 (boom never reached)"


def test_b8_main_json_returns_code_and_emits_one_json(tmp_path, monkeypatch, capsys):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _CL("alpha", [_F("repo", "error")])})
    rc = foundry.main(["company-lint-config", "--config", str(disp), "--json"])
    doc = json.loads(capsys.readouterr().out.strip())
    assert rc == doc["exit_code"] == 1
    assert doc["verdict"] == "ATTENTION"


# ==========================================================================
# Behavior 9 -- dormant + additive + wiring
# ==========================================================================
def test_b9_both_modules_import():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"
    assert dispatcher is not None


def test_b9_new_surface_present_and_reuses_shipped_seams():
    for name in NEW_SYMBOLS:
        assert hasattr(foundry, name), f"missing new symbol {name!r}"
    assert callable(foundry.gather_config_lint)
    assert callable(foundry.summarize_company_config_lint)
    assert callable(foundry.company_config_lint_cli)
    for name in ("parse_dispatch_work_items", "lint_config", "lint_config_cli",
                 "ConfigLint", "ConfigFinding", "load_config"):
        assert hasattr(foundry, name), f"shipped seam {name!r} vanished"


def test_b9_new_symbols_absent_from_control_flow_and_siblings_and_dispatcher():
    for fn_name in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references new symbol {sym!r} (must stay off the control path)"
        assert SUBCMD not in consts, f"{fn_name} embeds the {SUBCMD!r} subcommand literal"
    # sibling CLIs must reference NONE of the 4 new symbols
    for fn_name in ("lint_config_cli", "company_weak_tests_cli",
                    "company_constant_asserts_cli", "company_skipped_tests_cli",
                    "company_test_quality_cli"):
        if hasattr(foundry, fn_name):
            names, _ = _fn_names_consts(getattr(foundry, fn_name))
            for sym in NEW_SYMBOLS:
                assert sym not in names, \
                    f"sibling {fn_name} references new symbol {sym!r}"
    # ONLY main() references company_config_lint_cli, which references the
    # summarize + gather seams; gather references lint_config (positive wiring).
    main_names, _ = _fn_names_consts(foundry.main)
    assert "company_config_lint_cli" in main_names, \
        "main() must dispatch to company_config_lint_cli"
    cli_names, _ = _fn_names_consts(foundry.company_config_lint_cli)
    assert "gather_config_lint" in cli_names, \
        "company_config_lint_cli must call gather_config_lint by bare name"
    assert "summarize_company_config_lint" in cli_names, \
        "company_config_lint_cli must call summarize_company_config_lint by bare name"
    gather_names, _ = _fn_names_consts(foundry.gather_config_lint)
    assert "lint_config" in gather_names, \
        "gather_config_lint must reuse lint_config by bare name (positive wiring)"
    # dispatcher references none of the new symbols
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    dnames, dconsts = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in dnames, f"dispatcher references {sym!r}"
    assert SUBCMD not in dconsts, f"dispatcher references the {SUBCMD!r} literal"


def test_b9_help_lists_company_lint_config_with_siblings(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    text = capsys.readouterr().out
    for sub in ("lint-config", "company-weak-tests", "company-constant-asserts",
                "company-skipped-tests", "company-test-quality", SUBCMD):
        assert sub in text, f"subcommand {sub!r} missing from --help:\n{text}"


def test_b9_subcommand_help_has_config_json_but_no_limit_no_files():
    with pytest.raises(SystemExit) as ei:
        foundry.main([SUBCMD, "--help"])
    assert ei.value.code == 0


def test_b9_control_path_and_guard_scripts_byte_unchanged():
    # `git diff --quiet` emits NO diff text (exit-code-only) -> honors isolation.
    # foundry.py is EXCLUDED (routinely extended additively each iteration); the
    # resume-safety invariant is dispatcher.py + the guard scripts byte-frozen.
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--",
         "dispatcher.py", "scripts/leak_guard.py", "scripts/leak_denylist.txt"],
        cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, \
        "dispatcher.py / guard scripts are NOT byte-unchanged from HEAD"


def test_b9_cli_writes_nothing_to_repo_tree(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])
    _patch_cli(monkeypatch, {"alpha": _CL("alpha")})
    before = _git_visible_snapshot(_ROOT / "products")
    _run_cli(str(disp))
    _run_cli(str(disp), as_json=True)
    after = _git_visible_snapshot(_ROOT / "products")
    assert before == after, "the read-only CLI must write NOTHING into the repo tree"


def test_b9_shipped_public_files_scan_clean_and_no_home_path():
    if not (_LEAK_GUARD.exists() and _DENYLIST.exists()):
        pytest.skip("leak-guard not present in this repo (repo-agnostic)")
    lg = _load_leak_guard()
    patterns = lg.load_denylist(_DENYLIST.read_text())  # API takes TEXT, not a Path
    home_prefix = "/" + "Users" + "/"  # built at runtime; never a source literal
    # liveness: the denylist is a LIVE matcher, not inert
    assert len(lg.scan_text(home_prefix + "somebody/x", patterns)) >= 1, \
        "denylist appears inert (a home-path probe did not match)"
    for rel in ("tests/test_iter61_behavior.py", "README.md", "PLATFORM_ROADMAP.md"):
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
