"""Black-box behaviour tests for iter 64 -- the NEW read-only
`foundry lint-manifest --file <path> [--bench-dir <dir>] [--json]` validator for
a product's staffing manifest (`staffing.json`) against a documented JSON schema.

It applies FOUR rules, each finding tagged with its `rule`: `schema` (top level is
an object with `product` [non-empty str] + `iteration_budget` [int > 0] + `roles`
[non-empty list of well-formed `{role,model,gate,done_criteria}` objects]),
`bench_card` (every well-formed role name has a `<bench-dir>/<name>.md` card),
`core_seat` (the five core seats product_manager/engineer/reviewer/qa_tester/
release_gate are all staffed, in that fixed order), and `budget` (`iteration_budget`
is a positive int, not a bool). It is the MANIFEST-facing sibling of `doctor`
(#0 env), `lint-spec` (#6 spec), `lint-config` (#27 config), and `lint-bench`
(#29 bench). Purely additive / dormant. Roadmap item 18, bite 1.

ISOLATION CONTRACT (honored): every test below encodes the iter-64 PM spec's
Expected Behaviors (1-17) and is driven purely against the PUBLIC interface --
the pure `foundry.lint_manifest(data, bench_dir, manifest_path=...)` core over
SYNTHETIC manifest dicts + tmp `.md` bench dirs, the `ManifestFinding`/
`ManifestLint` dataclasses' fields / `render()` / `to_dict()`, the
`foundry.lint_manifest_cli(...)` / `foundry.main(["lint-manifest", ...])` CLI,
plus public RUNTIME introspection (compiled `__code__.co_names`, `dispatcher`
attributes) and the documented `import foundry, dispatcher` subprocess probe.
The implementation SOURCE (foundry.py / dispatcher.py logic), the engineer's and
reviewer's notes, and `git diff` were NOT read as logic to mirror; assertions
encode the SPEC's behaviors, not impl quirks. Fully offline & deterministic: no
network, no git subprocess, no real push; the sole subprocess is the
`import foundry, dispatcher` dormancy probe. Every manifest is a SYNTHETIC dict
and every path is built at RUNTIME from the pytest `tmp_path` fixture (never a
source-literal home path), so the committed leak-guard passes on the ship commit.
"""
import io
import json
import os
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# constants / helpers
# --------------------------------------------------------------------------
NEW_SYMBOLS = ("ManifestFinding", "ManifestLint", "MANIFEST_CORE_SEATS",
               "lint_manifest", "lint_manifest_cli")
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")
TO_DICT_KEYS = ("manifest_path", "bench_dir", "roles", "findings", "n_findings",
                "core_seats_present", "clean", "exit_code", "verdict")
# the five core seats in the FIXED order the spec pins
CORE_SEATS = ("product_manager", "engineer", "reviewer", "qa_tester", "release_gate")


def _good_role(name):
    """A well-formed role object: role(str)/model(str)/gate(bool)/done_criteria(str)."""
    return {"role": name, "model": "default tier", "gate": True, "done_criteria": "done"}


def _bench(tmp_path, names):
    """Create a bench dir under tmp_path with a `<name>.md` card per name; return its str path."""
    d = tmp_path / "bench"
    d.mkdir(exist_ok=True)
    for n in names:
        (d / f"{n}.md").write_text("# Bench role card: " + n + "\n")
    return str(d)


def _valid_manifest(product="repolens", budget=10):
    """A fully valid manifest: all five core seats, each a well-formed role."""
    return {"product": product, "iteration_budget": budget,
            "roles": [_good_role(s) for s in CORE_SEATS]}


def _rules(r):
    return [f.rule for f in r.findings]


def _schema_findings(r):
    return [f for f in r.findings if f.rule == "schema"]


def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY; return (rc, out, err).
    Separate capture matters for --json: the JSON must be the ENTIRE stdout,
    uncontaminated by any stderr message."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _co_names_deep(fn):
    """Every name referenced by fn's code, recursing into nested code objects."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


# ==========================================================================
# Behavior 1 -- pure core signature: any-type data, never raises, offline
# ==========================================================================
@pytest.mark.parametrize("data", [None, 5, "str", [], [1, 2], {}, {"roles": [1]}, True])
def test_b1_never_raises_on_malformed(data, tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    r = foundry.lint_manifest(data, bench)  # must NOT raise
    assert type(r).__name__ == "ManifestLint"


def test_b1_accepts_manifest_path_label_and_pathlib_bench(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    # bench_dir as a pathlib.Path is accepted; manifest_path label is optional
    r = foundry.lint_manifest(_valid_manifest(), pathlib.Path(bench),
                              manifest_path="products/x/staffing.json")
    assert r.to_dict()["manifest_path"] == "products/x/staffing.json"


# ==========================================================================
# Behavior 2 -- a fully valid manifest is clean
# ==========================================================================
def test_b2_valid_manifest_is_clean(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    r = foundry.lint_manifest(_valid_manifest(), bench)
    assert r.findings == (), f"expected no findings; got {_rules(r)}"
    assert r.clean is True
    assert r.core_seats_present is True
    assert r.exit_code == 0
    assert r.verdict == "OK"


# ==========================================================================
# Behavior 3 -- non-object top-level -> single schema finding, hard stop
# ==========================================================================
@pytest.mark.parametrize("data", [[], ["a"], "str", 5, None, True])
def test_b3_non_object_single_schema_finding_hard_stop(data, tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    r = foundry.lint_manifest(data, bench)
    assert len(r.findings) == 1, f"expected exactly one finding; got {_rules(r)}"
    assert r.findings[0].rule == "schema"
    assert "not a JSON object" in r.findings[0].message
    assert r.roles == (), "a non-object top level contributes no roles"
    assert r.exit_code == 1
    assert r.verdict == "MANIFEST ISSUES FOUND"


# ==========================================================================
# Behavior 4 -- missing/wrong-type top-level keys -> one schema finding each
# ==========================================================================
@pytest.mark.parametrize("data", [
    {"iteration_budget": 1, "roles": [_good_role(s) for s in CORE_SEATS]},   # missing product
    {"product": "", "iteration_budget": 1, "roles": [_good_role(s) for s in CORE_SEATS]},  # empty product
    {"product": 5, "iteration_budget": 1, "roles": [_good_role(s) for s in CORE_SEATS]},   # non-str product
])
def test_b4_bad_product_one_schema_finding(data, tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    r = foundry.lint_manifest(data, bench)
    assert len(_schema_findings(r)) == 1, f"expected one schema finding; got {_rules(r)}"


@pytest.mark.parametrize("roles_val", [None, [], "x", 5])
def test_b4_missing_or_bad_roles_one_schema_finding(roles_val, tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    data = {"product": "p", "iteration_budget": 1}
    if roles_val is not None:
        data["roles"] = roles_val
    r = foundry.lint_manifest(data, bench)
    assert len(_schema_findings(r)) == 1, f"expected one schema finding; got {_rules(r)}"


def test_b4_missing_budget_is_budget_rule_not_schema(tmp_path):
    # a MISSING iteration_budget is reported by the BUDGET rule (B8), not schema
    bench = _bench(tmp_path, CORE_SEATS)
    r = foundry.lint_manifest({"product": "p", "roles": [_good_role(s) for s in CORE_SEATS]}, bench)
    assert _rules(r) == ["budget"], f"got {_rules(r)}"


# ==========================================================================
# Behavior 5 -- malformed role entry -> schema finding + contributes no name
# ==========================================================================
@pytest.mark.parametrize("bad", [
    "zeta-not-an-object",
    {"model": "m", "gate": True, "done_criteria": "d"},              # missing role
    {"role": "zeta", "gate": True, "done_criteria": "d"},            # missing model
    {"role": "zeta", "model": "m", "done_criteria": "d"},            # missing gate
    {"role": "zeta", "model": "m", "gate": True},                    # missing done_criteria
    {"role": "zeta", "model": "m", "gate": 1, "done_criteria": "d"}, # gate not bool
    {"role": 5, "model": "m", "gate": True, "done_criteria": "d"},   # role not str
])
def test_b5_malformed_role_one_schema_and_no_name(bad, tmp_path):
    # give the malformed role a real card (zeta.md) so IF it were counted, no
    # bench_card finding would fire -- proving it contributes no name
    bench = _bench(tmp_path, list(CORE_SEATS) + ["zeta"])
    data = {"product": "p", "iteration_budget": 1,
            "roles": [_good_role(s) for s in CORE_SEATS] + [bad]}
    r = foundry.lint_manifest(data, bench)
    assert len(_schema_findings(r)) == 1, f"expected one schema finding; got {_rules(r)}"
    assert "zeta" not in r.roles, "a malformed role must contribute NO name"
    # since it added no name, the other rules see only the five valid seats -> clean otherwise
    assert _rules(r) == ["schema"], f"malformed entry alone should be the only finding; got {_rules(r)}"


# ==========================================================================
# Behavior 6 -- bench_card rule: role names without a card, in manifest order
# ==========================================================================
def test_b6_missing_card_flagged(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)  # 'extra' has NO card
    data = {"product": "p", "iteration_budget": 1,
            "roles": [_good_role(s) for s in CORE_SEATS] + [_good_role("extra")]}
    r = foundry.lint_manifest(data, bench)
    bc = [f for f in r.findings if f.rule == "bench_card"]
    assert len(bc) == 1, f"got {_rules(r)}"
    assert "extra" in bc[0].message


def test_b6_bench_card_findings_in_manifest_order(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)  # neither 'aaa' nor 'zzz' has a card
    roles = [_good_role(s) for s in CORE_SEATS] + [_good_role("zzz"), _good_role("aaa")]
    r = foundry.lint_manifest({"product": "p", "iteration_budget": 1, "roles": roles}, bench)
    bc = [f for f in r.findings if f.rule == "bench_card"]
    # manifest order is zzz then aaa (NOT alphabetical)
    assert "zzz" in bc[0].message
    assert "aaa" in bc[1].message


# ==========================================================================
# Behavior 7 -- core_seat rule: fixed order, core_seats_present flag
# ==========================================================================
def test_b7_all_seats_present_no_finding(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    r = foundry.lint_manifest(_valid_manifest(), bench)
    assert [f for f in r.findings if f.rule == "core_seat"] == []
    assert r.core_seats_present is True


def test_b7_missing_seats_flagged_in_fixed_order(tmp_path):
    # drop engineer + qa_tester -> two core_seat findings in the FIXED seat order
    present = [s for s in CORE_SEATS if s not in ("engineer", "qa_tester")]
    bench = _bench(tmp_path, present)
    data = {"product": "p", "iteration_budget": 1, "roles": [_good_role(s) for s in present]}
    r = foundry.lint_manifest(data, bench)
    cs = [f for f in r.findings if f.rule == "core_seat"]
    assert len(cs) == 2
    # engineer precedes qa_tester in the fixed order
    assert "engineer" in cs[0].message
    assert "qa_tester" in cs[1].message
    assert r.core_seats_present is False


# ==========================================================================
# Behavior 8 -- budget rule: int > 0 and not bool
# ==========================================================================
@pytest.mark.parametrize("budget", [1, 5, 999])
def test_b8_valid_budget_no_finding(budget, tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    m = _valid_manifest(budget=budget)
    r = foundry.lint_manifest(m, bench)
    assert [f for f in r.findings if f.rule == "budget"] == [], f"budget={budget!r} should be valid"


@pytest.mark.parametrize("budget", [0, -1, True, False, 3.5, "5"])
def test_b8_bad_budget_one_finding(budget, tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    m = _valid_manifest()
    m["iteration_budget"] = budget
    r = foundry.lint_manifest(m, bench)
    bud = [f for f in r.findings if f.rule == "budget"]
    assert len(bud) == 1, f"budget={budget!r} should yield exactly one budget finding; got {_rules(r)}"


def test_b8_missing_budget_one_finding(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    r = foundry.lint_manifest({"product": "p", "roles": [_good_role(s) for s in CORE_SEATS]}, bench)
    assert len([f for f in r.findings if f.rule == "budget"]) == 1


# ==========================================================================
# Behavior 9 -- deterministic finding order: schema, bench_card, core_seat, budget
# ==========================================================================
def test_b9_multi_rule_group_order_and_determinism(tmp_path):
    # empty product (schema) + a role 'ghost' w/o card (bench_card) + drop 'reviewer'
    # (core_seat) + budget 0 (budget)
    present = [s for s in CORE_SEATS if s != "reviewer"]
    bench = _bench(tmp_path, present)  # no 'ghost', no 'reviewer' card
    roles = [_good_role(s) for s in present] + [_good_role("ghost")]
    data = {"product": "", "iteration_budget": 0, "roles": roles}
    r1 = foundry.lint_manifest(data, bench)
    r2 = foundry.lint_manifest(data, bench)
    rules = _rules(r1)
    # groups must appear in this order (schema first, budget last)
    assert rules[0] == "schema"
    assert rules[-1] == "budget"
    assert "bench_card" in rules and "core_seat" in rules
    assert rules.index("bench_card") < rules.index("core_seat")
    assert rules.index("schema") < rules.index("bench_card")
    assert rules.index("core_seat") < rules.index("budget")
    # deterministic across runs
    assert r1.to_dict() == r2.to_dict()


# ==========================================================================
# Behavior 10 -- derived fields
# ==========================================================================
def test_b10_derived_fields_when_dirty(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    r = foundry.lint_manifest([], bench)  # non-object -> one finding
    assert r.n_findings == len(r.findings)
    assert r.clean is (r.n_findings == 0)
    assert r.exit_code == (0 if r.clean else 1)
    assert r.verdict == ("OK" if r.clean else "MANIFEST ISSUES FOUND")


def test_b10_roles_tuple_is_wellformed_names_in_order(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    # order preserved; a malformed entry (missing model) contributes no name
    roles = [_good_role("release_gate"), {"role": "bad", "gate": True, "done_criteria": "d"},
             _good_role("engineer")]
    r = foundry.lint_manifest({"product": "p", "iteration_budget": 1, "roles": roles}, bench)
    assert r.roles == ("release_gate", "engineer"), f"got {r.roles}"


# ==========================================================================
# Behavior 11 -- to_dict() shape / order / round-trip
# ==========================================================================
def test_b11_to_dict_key_order(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    d = foundry.lint_manifest(_valid_manifest(), bench).to_dict()
    assert tuple(d.keys()) == TO_DICT_KEYS, f"key order wrong: {list(d.keys())}"


def test_b11_to_dict_shapes_and_roundtrip(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    # a dirty manifest so findings is non-empty
    r = foundry.lint_manifest({"product": "", "iteration_budget": 0,
                               "roles": [_good_role(s) for s in CORE_SEATS]}, bench)
    d = r.to_dict()
    assert isinstance(d["roles"], list) and all(isinstance(x, str) for x in d["roles"])
    assert isinstance(d["findings"], list) and d["findings"]
    for entry in d["findings"]:
        assert tuple(entry.keys()) == ("rule", "message"), entry
        assert isinstance(entry["rule"], str) and isinstance(entry["message"], str)
    assert json.loads(json.dumps(d)) == d, "to_dict must round-trip through JSON"


# ==========================================================================
# Behavior 12 -- render() layout: last non-empty line is `verdict: <TOKEN>`
# ==========================================================================
def test_b12_render_clean_last_line_verdict_ok(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    r = foundry.lint_manifest(_valid_manifest(), bench)
    text = r.render()
    assert text == r.render(), "render must be deterministic"
    assert bench in text, "render must name the bench dir"
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[-1] == "verdict: OK", f"last non-empty line: {lines[-1]!r}"


def test_b12_render_lists_findings_with_rule_tag(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    r = foundry.lint_manifest({"product": "", "iteration_budget": 0,
                               "roles": [_good_role(s) for s in CORE_SEATS]}, bench)
    text = r.render()
    # one indented line per finding tagged with its [rule]
    assert "[schema]" in text
    assert "[budget]" in text
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[-1] == "verdict: MANIFEST ISSUES FOUND", f"last line: {lines[-1]!r}"


def test_b12_render_names_manifest_path_and_role_count(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    r = foundry.lint_manifest(_valid_manifest(), bench, manifest_path="p/staffing.json")
    text = r.render()
    assert "p/staffing.json" in text, "render must show the manifest path"
    assert "5" in text, "render must show the role count"


def test_b12_render_carries_no_source_home_path(tmp_path):
    # build the home prefix at RUNTIME (never a source literal) so this
    # self-leak-safety assertion does not itself trip the committed leak-guard
    home_prefix = "/" + "Users" + "/"
    bench = _bench(tmp_path, CORE_SEATS)
    text = foundry.lint_manifest(_valid_manifest(), bench).render()
    assert home_prefix not in text, "render must not carry a home-path literal"


# ==========================================================================
# Behavior 13 -- lint_manifest_cli: happy/gate path + --json
# ==========================================================================
def test_b13_cli_human_prints_render_returns_exit_code(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    mf = tmp_path / "staffing.json"
    mf.write_text(json.dumps(_valid_manifest()))
    rc, out, err = _capture(lambda: foundry.lint_manifest_cli(str(mf), bench_dir=bench))
    assert rc == 0, f"stderr={err!r}"
    assert out.splitlines()[0].startswith("foundry lint-manifest")
    assert out.strip().splitlines()[-1] == "verdict: OK"


def test_b13_cli_gate_path_exit_1(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)  # no 'extra' card
    mf = tmp_path / "staffing.json"
    m = _valid_manifest()
    m["roles"].append(_good_role("extra"))
    mf.write_text(json.dumps(m))
    rc, out, err = _capture(lambda: foundry.lint_manifest_cli(str(mf), bench_dir=bench))
    assert rc == 1


def test_b13_cli_json_is_one_parseable_doc_same_exit(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    mf = tmp_path / "staffing.json"
    m = _valid_manifest()
    m["iteration_budget"] = 0  # dirty -> exit 1
    mf.write_text(json.dumps(m))
    rc, out, err = _capture(lambda: foundry.lint_manifest_cli(str(mf), bench_dir=bench, as_json=True))
    assert rc == 1
    doc = json.loads(out)  # the ENTIRE stdout must be one parseable JSON document
    assert tuple(doc.keys()) == TO_DICT_KEYS
    assert doc["verdict"] == "MANIFEST ISSUES FOUND"


# ==========================================================================
# Behavior 14 -- CLI unreadable / parse-error -> 2, never propagates
# ==========================================================================
def test_b14_cli_nonexistent_file_returns_2(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    missing = str(tmp_path / "nope.json")
    rc, out, err = _capture(lambda: foundry.lint_manifest_cli(missing, bench_dir=bench))
    assert rc == 2
    assert "lint-manifest" in (out + err)


def test_b14_cli_invalid_json_returns_2(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    badf = tmp_path / "bad.json"
    badf.write_text("{ this is not valid json ")
    rc, out, err = _capture(lambda: foundry.lint_manifest_cli(str(badf), bench_dir=bench))
    assert rc == 2, "invalid JSON is a read/parse error (exit 2), never raises"


def test_b14_cli_json_error_doc_shape(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    missing = str(tmp_path / "nope.json")
    rc, out, err = _capture(lambda: foundry.lint_manifest_cli(missing, bench_dir=bench, as_json=True))
    assert rc == 2
    doc = json.loads(out)  # single JSON document on stdout
    assert doc["exit_code"] == 2
    assert "manifest_path" in doc and "error" in doc


def test_b14_cli_unreadable_file_returns_2(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    mf = tmp_path / "staffing.json"
    mf.write_text(json.dumps(_valid_manifest()))
    os.chmod(mf, 0o000)
    if os.access(mf, os.R_OK):  # running as root -> chmod is a no-op; skip
        os.chmod(mf, 0o644)
        pytest.skip("cannot make a file unreadable (running as root)")
    try:
        rc, out, err = _capture(lambda: foundry.lint_manifest_cli(str(mf), bench_dir=bench))
        assert rc == 2, "an unreadable manifest is exit 2, never raises"
    finally:
        os.chmod(mf, 0o644)


# ==========================================================================
# Behavior 15 -- bare-name seam: monkeypatch foundry.lint_manifest changes the CLI
# ==========================================================================
def test_b15_bare_name_seam(tmp_path, monkeypatch):
    bench = _bench(tmp_path, CORE_SEATS)
    mf = tmp_path / "staffing.json"
    mf.write_text(json.dumps(_valid_manifest()))

    class _Stub:
        exit_code = 7
        def render(self):
            return "STUBBED\nverdict: OK"
        def to_dict(self):
            return {"stub": True}

    monkeypatch.setattr(foundry, "lint_manifest", lambda *a, **k: _Stub())
    rc, out, err = _capture(lambda: foundry.lint_manifest_cli(str(mf), bench_dir=bench))
    assert rc == 7, "CLI must call the core by its bare module name (seam)"
    assert "STUBBED" in out


# ==========================================================================
# Behavior 16 -- main dispatch before load_config; --bench-dir; --help
# ==========================================================================
def test_b16_main_valid_no_config_needed_returns_0(tmp_path):
    # lint-manifest needs NO product --config; if dispatched AFTER the top-level
    # load_config, a missing default config would raise instead of a clean exit.
    bench = _bench(tmp_path, CORE_SEATS)
    mf = tmp_path / "staffing.json"
    mf.write_text(json.dumps(_valid_manifest()))
    rc, out, err = _capture(lambda: foundry.main(["lint-manifest", "--file", str(mf), "--bench-dir", bench]))
    assert rc == 0, f"stderr={err!r}"
    assert "verdict: OK" in out


def test_b16_main_nonexistent_file_returns_2_no_raise(tmp_path):
    missing = str(tmp_path / "does-not-exist.json")
    rc, out, err = _capture(lambda: foundry.main(["lint-manifest", "--file", missing]))
    assert rc == 2, "a nonexistent --file returns 2, never raises"


def test_b16_bench_dir_override_changes_result(tmp_path):
    # same manifest: against a bench WITH all cards -> 0; against an empty bench -> 1
    full = _bench(tmp_path, CORE_SEATS)
    empty = str(tmp_path / "empty_bench")
    os.makedirs(empty, exist_ok=True)
    mf = tmp_path / "staffing.json"
    mf.write_text(json.dumps(_valid_manifest()))
    rc_full, _, _ = _capture(lambda: foundry.main(["lint-manifest", "--file", str(mf), "--bench-dir", full]))
    rc_empty, _, _ = _capture(lambda: foundry.main(["lint-manifest", "--file", str(mf), "--bench-dir", empty]))
    assert rc_full == 0
    assert rc_empty == 1, "with no cards in --bench-dir, every role trips bench_card -> exit 1"


def test_b16_help_lists_lint_manifest():
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        foundry.main(["--help"])
    except SystemExit:
        pass
    finally:
        sys.stdout = old
    assert "lint-manifest" in buf.getvalue()


# ==========================================================================
# Behavior 17 -- additivity / dormancy / positive wiring / import health
# ==========================================================================
def test_b17_control_flow_fns_do_not_reference_new_symbols():
    # iter-72 (item 19, bite 3b-ii) WIRED lint_manifest into run_iteration as part
    # of the manifest-driven executor delegation guard -- its intended first call
    # site -- so run_iteration is no longer asserted zero-reference for that ONE
    # name. Every OTHER new symbol stays dormant in run_iteration, and
    # build_prompt / run_stage / run_continuous reference NONE of the new symbols.
    wired_in_run_iteration = {"lint_manifest"}
    for fn_name in CONTROL_FLOW_FNS:
        refs = _co_names_deep(getattr(foundry, fn_name)) & set(NEW_SYMBOLS)
        allowed = wired_in_run_iteration if fn_name == "run_iteration" else set()
        assert not (refs - allowed), f"{fn_name} unexpectedly references {refs - allowed}"


def test_b17_positive_wiring_chain():
    assert "lint_manifest_cli" in _co_names_deep(foundry.main)
    assert "lint_manifest" in _co_names_deep(foundry.lint_manifest_cli)


def test_b17_dispatcher_has_none_of_the_new_symbols():
    for s in NEW_SYMBOLS:
        assert not hasattr(dispatcher, s), f"dispatcher unexpectedly exposes {s}"


def test_b17_core_seats_constant_is_fixed_order():
    assert tuple(foundry.MANIFEST_CORE_SEATS) == CORE_SEATS


def test_b17_findings_are_frozen(tmp_path):
    bench = _bench(tmp_path, CORE_SEATS)
    r = foundry.lint_manifest([], bench)
    with pytest.raises(Exception):
        r.findings[0].rule = "x"


def test_b17_import_foundry_and_dispatcher_ok():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=root, capture_output=True, text=True,
    )
    assert r.returncode == 0, f"import failed: {r.stderr}"
