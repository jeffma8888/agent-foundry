"""Black-box behaviour tests for iter 101 -- a machine-readable `--json` output
mode over the read-only, offline `foundry outcomes` per-iteration GATE-OUTCOME
LEDGER (iter 100 shipped the human CLI; this is the pre-declared bite 2). ALL
additive in foundry.py:

  * a PURE `IterationOutcome.to_dict() -> dict` (4 fixed-order keys: the 4 STORED
    fields `iteration`/`review`/`tester`/`action` verbatim -- NO derived key,
    UNLIKE history's `IterationRecord.to_dict` which appends a `label`),
  * a PURE `OutcomesSummary.to_dict() -> dict` (8 fixed-order keys: `product` +
    the five frozen counts `total`/`approved`/`changes_required`/`tester_passed`/
    `tester_failed` + `exit_code` REUSED verbatim from the iter-100 properties +
    `records`, a list of the per-record `to_dict()` dicts in stored order), all
    JSON-native,
  * an `outcomes_cli(cfg, limit=None, as_json: bool = False) -> int` -- on True it
    prints ONE JSON document (the WHOLE stdout) == the summary's `to_dict()` and
    returns the SAME exit code as the human path; on False/default it is
    byte-identical to iter 100,
  * an `outcomes --json` argparse flag (`store_true`, default off) routed by `main`.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-101 PM
spec's Expected Behaviors (1-18), the product README/roadmap, the `tests/`
conventions (esp. tests/test_iter100_behavior.py -- the human bite this clones --
and tests/test_iter20_behavior.py -- the `history --json` template), and the
product's own OBSERVABLE behaviour (via running it / public runtime
introspection: `inspect.signature`, module attributes, compiled
`__code__.co_names`/`co_consts`). The implementation source (foundry.py /
dispatcher.py internals), the engineer's and reviewer's notes, and `git diff`
were NOT read. Every check drives the PUBLIC interface: the pure `to_dict()` on
`foundry.IterationOutcome(...)` / `foundry.OutcomesSummary(...)` (built via
`foundry.summarize_outcomes(...)`), the seam `foundry.gather_outcomes(cfg[, limit])`,
and the CLI via `foundry.outcomes_cli(cfg, as_json=...)` / `foundry.main(["outcomes", ...])`
against a TMP-`work_root` config with real `state/iter-NN/{reviewer,tester,final}.md`
files (the real foundry repo/state is NEVER touched). The dormancy checks
(Behavior 18) use only public RUNTIME introspection (compiled name/const tables
+ module attributes), NOT the source text. Fully offline & deterministic: real
temp files only; ZERO real subprocess / git / network / clock (except the
`import` regression probe, which only imports the two modules).
"""
import inspect
import io
import json
import pathlib
import shutil
import subprocess
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


RECORD_KEYS = ("iteration", "review", "tester", "action")                  # Behavior 1
SUMMARY_KEYS = ("product", "total", "approved", "changes_required",
                "tester_passed", "tester_failed", "exit_code", "records")  # Behavior 5

# iter-101 value objects / CLI that must stay OFF the pipeline + dispatcher
# control path. `to_dict` is a GENERIC method name shared by ~30 value objects
# across foundry, so scanning orchestrator co_names for the bare `to_dict` would
# FALSE-POSITIVE; the meaningful dormancy proxy is the outcomes-SPECIFIC class /
# function names + the `outcomes` subcommand literal.
OUTCOMES_SYMBOLS = ("outcomes_cli", "IterationOutcome", "OutcomesSummary",
                    "summarize_outcomes", "gather_outcomes")
ORCHESTRATORS = ("build_prompt", "run_stage", "run_iteration", "run_continuous",
                 "run_execution_plan")
JSON_LEADS = {"{", "}", "[", "]", '"'}


# --------------------------------------------------------------------------
# helpers  (mirror tests/test_iter100_behavior.py + test_iter20_behavior.py)
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir. `repo`/`work_root` are TMP dirs so
    the real foundry repo/state is NEVER touched. mkdir tmp_path up front so a
    not-yet-created tmp subdir cannot FileNotFoundError the config write (a
    config-path failure would be a HARNESS bug, not the CLI, which writes
    nothing)."""
    pathlib.Path(tmp_path).mkdir(parents=True, exist_ok=True)
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


def _snapshot_tree(root):
    """Map {relative-path: bytes} for every file under root (no-write proof)."""
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*") if p.is_file()
    }


def _iter_dir(cfg, iteration):
    return pathlib.Path(cfg.state) / f"iter-{iteration:02d}"


def _write_outcome(cfg, iteration, *, review=None, tester=None, action=None):
    """Create state/iter-NN/{reviewer,tester,final}.md whose LAST non-empty line
    is the role-owned sentinel. Any of review/tester/action left None leaves that
    artifact ABSENT (so gather_outcomes reads None for that field)."""
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    tail = "\n\n   \n\t\n"
    if review is not None:
        (d / "reviewer.md").write_text(f"review notes\n\nVERDICT: {review}{tail}")
    if tester is not None:
        (d / "tester.md").write_text(f"test report\n\nRESULT: {tester}{tail}")
    if action is not None:
        (d / "final.md").write_text(f"final gate report\n\nACTION: {action}{tail}")
    return d


def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY; return (rc, out, err).
    Separate capture matters: Behaviors 11/16 require JSON to be the ENTIRE stdout."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


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
    """Union of names/str-consts across every function/method reachable from a
    module's public namespace (recursively into nested code objects)."""
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


def _mixed_records():
    """A record set exercising every field value + None in each slot:
    APPROVE / CHANGES_REQUIRED / PASS / FAIL / PUSHED / REVERTED / None.
    approved=2, changes_required=1, tester_passed=2, tester_failed=1, total=4."""
    IO = foundry.IterationOutcome
    return [
        IO(1, "APPROVE", "PASS", "PUSHED"),
        IO(2, "CHANGES_REQUIRED", "FAIL", "REVERTED"),
        IO(3, "APPROVE", "PASS", None),          # ship unknown
        IO(10, None, None, "PUSHED"),            # review/tester unknown
    ]


# ==========================================================================
# A. IterationOutcome.to_dict()                              (Behaviors 1-4)
# ==========================================================================
def test_b01_record_to_dict_keys_exact_and_ordered():
    IO = foundry.IterationOutcome
    for r in (IO(3, "APPROVE", "PASS", "PUSHED"),
              IO(0, "CHANGES_REQUIRED", "FAIL", "REVERTED"),
              IO(7, None, None, None),
              IO(2, "APPROVE", None, "PUSHED")):
        d = r.to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == list(RECORD_KEYS), (
            f"record to_dict keys/order wrong.\n got: {list(d.keys())}\n"
            f"want: {list(RECORD_KEYS)}")
        assert len(d) == 4, "exactly 4 stored keys"
        assert "label" not in d, "IterationOutcome has NO derived key (unlike history)"


def test_b01_record_values_verbatim():
    d = foundry.IterationOutcome(3, "APPROVE", "PASS", "PUSHED").to_dict()
    assert d == {"iteration": 3, "review": "APPROVE",
                 "tester": "PASS", "action": "PUSHED"}
    assert isinstance(d["iteration"], int)


def test_b02_record_none_verbatim():
    d = foundry.IterationOutcome(5, None, None, None).to_dict()
    assert d == {"iteration": 5, "review": None, "tester": None, "action": None}


def test_b03_record_json_native_and_round_trips():
    IO = foundry.IterationOutcome
    for r in (IO(3, "APPROVE", "PASS", "PUSHED"), IO(5, None, None, None),
              IO(2, "CHANGES_REQUIRED", "FAIL", "REVERTED"),
              IO(8, "APPROVE", None, "PUSHED")):
        d = r.to_dict()
        text = json.dumps(d)                       # must not raise
        assert json.loads(text) == d, "record to_dict must survive a json round-trip"
        d2 = json.loads(text)
        for field in ("review", "tester", "action"):
            if getattr(r, field) is None:
                assert d2[field] is None, f"None {field} must serialize to JSON null"
        assert isinstance(d2["iteration"], int)


def test_b04_record_returns_fresh_dict_each_call():
    r = foundry.IterationOutcome(3, "APPROVE", "PASS", "PUSHED")
    a, b = r.to_dict(), r.to_dict()
    assert a == b and a is not b, "two calls: equal-but-distinct dicts"
    a["iteration"] = 999
    a["review"] = "MUTATED"
    assert r.iteration == 3 and r.review == "APPROVE", \
        "mutating a returned dict must not touch the frozen record"
    assert r.to_dict() == {"iteration": 3, "review": "APPROVE",
                           "tester": "PASS", "action": "PUSHED"}, \
        "a later to_dict() must be unaffected by an earlier dict mutation"


# ==========================================================================
# B. OutcomesSummary.to_dict()                               (Behaviors 5-10)
# ==========================================================================
def test_b05_summary_to_dict_keys_exact_and_ordered():
    for recs in (_mixed_records(), [],
                 [foundry.IterationOutcome(1, "APPROVE", "PASS", "PUSHED")]):
        s = foundry.summarize_outcomes(product="demoprod", records=recs)
        d = s.to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == list(SUMMARY_KEYS), (
            f"summary to_dict keys/order wrong.\n got: {list(d.keys())}\n"
            f"want: {list(SUMMARY_KEYS)}")
        assert len(d) == 8


def test_b06_scalars_reuse_frozen_properties():
    s = foundry.summarize_outcomes(product="prodX", records=_mixed_records())
    d = s.to_dict()
    assert d["product"] == s.product and isinstance(d["product"], str)
    for key in ("total", "approved", "changes_required",
                "tester_passed", "tester_failed", "exit_code"):
        assert d[key] == getattr(s, key) and isinstance(d[key], int), \
            f"{key} must equal the frozen property (no re-derivation)"
    # known facts for the mixed fixture (informational -> exit 0)
    assert (d["total"], d["approved"], d["changes_required"],
            d["tester_passed"], d["tester_failed"], d["exit_code"]) == (4, 2, 1, 2, 1, 0)


def test_b07_records_is_list_of_per_record_dicts_in_order():
    s = foundry.summarize_outcomes(product="prodX", records=_mixed_records())
    d = s.to_dict()
    assert isinstance(d["records"], list)
    assert d["records"] == [r.to_dict() for r in s.records]
    assert [r["iteration"] for r in d["records"]] == [r.iteration for r in s.records]
    assert [r["iteration"] for r in d["records"]] == [1, 2, 3, 10]


def test_b08_empty_ledger_exact_dict():
    s = foundry.summarize_outcomes(product="demo", records=[])
    assert s.to_dict() == {
        "product": "demo", "total": 0, "approved": 0, "changes_required": 0,
        "tester_passed": 0, "tester_failed": 0, "exit_code": 2, "records": [],
    }


def test_b09_summary_json_native_and_round_trips():
    for recs in (_mixed_records(), [],
                 [foundry.IterationOutcome(1, "CHANGES_REQUIRED", "FAIL", "REVERTED")]):
        s = foundry.summarize_outcomes(product="demoprod", records=recs)
        d = s.to_dict()
        text = json.dumps(d)                       # must not raise
        assert json.loads(text) == d, "summary to_dict must survive a json round-trip"
        # records serializes to a plain LIST (no tuple/str-list leak)
        assert isinstance(json.loads(text)["records"], list)


def test_b10_summary_returns_fresh_dict_each_call():
    s = foundry.summarize_outcomes(product="p", records=_mixed_records())
    a, b = s.to_dict(), s.to_dict()
    assert a == b and a is not b, "two calls: equal-but-distinct dicts"
    a["total"] = 999
    a["records"].append({"iteration": 42})
    assert s.to_dict()["total"] == 4, \
        "mutating the returned dict must not affect a later to_dict()"
    assert [r["iteration"] for r in s.to_dict()["records"]] == [1, 2, 3, 10]


# ==========================================================================
# C. outcomes_cli(cfg, as_json=True) JSON path        (Behaviors 11, 14, 16)
# ==========================================================================
def test_b11_json_path_exact_bytes_and_exit_code(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_outcome(cfg, 1, review="APPROVE", tester="PASS", action="PUSHED abc1")
    _write_outcome(cfg, 2, review="CHANGES_REQUIRED", tester="FAIL", action="REVERTED")
    _write_outcome(cfg, 3, review="APPROVE")                    # tester+final absent
    before = _snapshot_tree(tmp_path)

    oracle = foundry.gather_outcomes(cfg, None).to_dict()
    expected = json.dumps(oracle, indent=2) + "\n"
    rc, out, err = _capture(lambda: foundry.outcomes_cli(cfg, limit=None, as_json=True))
    assert out == expected, \
        f"--json stdout must be json.dumps(to_dict, indent=2)+newline:\n{out!r}"
    assert rc == oracle["exit_code"] == 0, f"exit code must be the summary's exit_code: {rc}"
    d = json.loads(out)                                          # WHOLE stdout is JSON
    assert d == oracle
    assert d["product"] == cfg.name == "demoprod"
    assert [r["iteration"] for r in d["records"]] == [1, 2, 3]
    assert _snapshot_tree(tmp_path) == before, "outcomes --json wrote a file (must be read-only)"


def test_b14_json_and_human_share_exit_code(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_outcome(cfg, 1, review="APPROVE", tester="PASS", action="PUSHED a")
    rc_json, _, _ = _capture(lambda: foundry.outcomes_cli(cfg, as_json=True))
    rc_human, _, _ = _capture(lambda: foundry.outcomes_cli(cfg, as_json=False))
    assert rc_json == rc_human == 0, "populated ledger -> both exit 0"
    # empty state -> both exit 2
    shutil.rmtree(cfg.state, ignore_errors=True)
    pathlib.Path(cfg.state).mkdir(parents=True, exist_ok=True)
    rc_json2, out_json2, _ = _capture(lambda: foundry.outcomes_cli(cfg, as_json=True))
    rc_human2, _, _ = _capture(lambda: foundry.outcomes_cli(cfg))
    d = json.loads(out_json2)
    assert rc_json2 == rc_human2 == d["exit_code"] == 2, "empty ledger -> both exit 2"
    assert d["total"] == 0 and d["records"] == []


def test_b16_json_no_human_text_leak(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_outcome(cfg, 1, review="APPROVE", tester="PASS", action="PUSHED a")
    _write_outcome(cfg, 2, review="CHANGES_REQUIRED", tester="FAIL", action="REVERTED")
    _, out_json, _ = _capture(lambda: foundry.outcomes_cli(cfg, as_json=True))
    json.loads(out_json)                                        # single valid JSON doc
    assert "foundry outcomes --" not in out_json, "human header leaked into --json output"
    for ln in out_json.splitlines():
        if ln.strip():
            assert ln.strip()[0] in JSON_LEADS, \
                f"non-JSON line leaked into --json stdout: {ln!r}"
    # ARM the check (non-vacuous): the SAME input's human render leads with a
    # 'foundry' line whose lead char is NOT in the JSON structural set.
    _, out_human, _ = _capture(lambda: foundry.outcomes_cli(cfg))
    human_first = next(ln.strip() for ln in out_human.splitlines() if ln.strip())
    assert human_first.startswith("foundry"), f"human header changed: {human_first!r}"
    assert human_first[0] not in JSON_LEADS


# ==========================================================================
# D. outcomes_cli default / as_json=False human path   (Behaviors 12-13)
# ==========================================================================
def test_b12_default_equals_as_json_false_and_is_human_render(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_outcome(cfg, 1, review="APPROVE", tester="PASS", action="PUSHED a")
    _write_outcome(cfg, 2, review="CHANGES_REQUIRED", tester="FAIL", action="REVERTED")
    before = _snapshot_tree(tmp_path)

    rc_default, out_default, _ = _capture(lambda: foundry.outcomes_cli(cfg))
    rc_false, out_false, _ = _capture(lambda: foundry.outcomes_cli(cfg, as_json=False))
    # default == explicit as_json=False, byte-for-byte
    assert out_default == out_false, "default must equal as_json=False output byte-for-byte"
    assert rc_default == rc_false == 0
    # byte-for-byte the iter-100 human render + trailing newline (UNCHANGED)
    expected = foundry.gather_outcomes(cfg, None).render() + "\n"
    assert out_default == expected, "default is the iter-100 human render + newline"
    # the human output is NOT a single JSON document
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_default)
    assert "foundry outcomes -- demoprod" in out_default
    assert "iter-01" in out_default and "iter-02" in out_default
    assert _snapshot_tree(tmp_path) == before, "human outcomes wrote a file (must be read-only)"


def test_b12_default_param_value_is_false():
    sig = inspect.signature(foundry.outcomes_cli)
    assert "as_json" in sig.parameters, "outcomes_cli must gain an as_json parameter"
    assert sig.parameters["as_json"].default is False, \
        "as_json default must be False (byte-identical-by-default guarantee)"


def test_b13_json_honours_limit_same_selection_as_human(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    for n in range(1, 6):
        _write_outcome(cfg, n, review="APPROVE", tester="PASS", action=f"PUSHED s{n}")
    rc, out_json, _ = _capture(lambda: foundry.outcomes_cli(cfg, limit=2, as_json=True))
    d = json.loads(out_json)
    oracle = foundry.gather_outcomes(cfg, 2)
    assert d["total"] == oracle.total == 2
    assert len(d["records"]) == oracle.total
    iters = [r["iteration"] for r in d["records"]]
    assert iters == [4, 5], f"limit=2 -> highest-2 iterations, ascending: {iters}"
    # same selection as the human path with the same limit
    _, out_human, _ = _capture(lambda: foundry.outcomes_cli(cfg, limit=2))
    for tag in ("iter-04", "iter-05"):
        assert tag in out_human
    for tag in ("iter-01", "iter-02", "iter-03"):
        assert tag not in out_human, f"{tag} must NOT appear under limit=2 (human):\n{out_human}"
    assert rc == d["exit_code"] == 0


# ==========================================================================
# E. Read-only: writes nothing, creates no directories       (Behavior 15)
# ==========================================================================
def test_b15_json_writes_nothing_creates_no_files(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_outcome(cfg, 1, review="APPROVE", tester="PASS", action="PUSHED a")
    # run from an EMPTY temp cwd; snapshot it to prove no cwd file is created
    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    before_state = _snapshot_tree(cfg.state)
    rc, out, _ = _capture(lambda: foundry.outcomes_cli(cfg, as_json=True))
    assert rc == 0 and isinstance(json.loads(out), dict)
    assert _snapshot_tree(empty_cwd) == {}, "--json created a file in cwd"
    assert _snapshot_tree(cfg.state) == before_state, "--json mutated the state dir"


def test_b15_json_empty_state_creates_no_state_dir(tmp_path, monkeypatch):
    # distinguish load_config's own pre-creation of <work_root>/state from the CLI:
    # DELETE the state dir, then prove --json leaves it ABSENT (never mkdirs).
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    shutil.rmtree(cfg.state, ignore_errors=True)
    assert not pathlib.Path(cfg.state).exists()
    empty_cwd = tmp_path / "empty_cwd2"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    rc, out, _ = _capture(lambda: foundry.outcomes_cli(cfg, as_json=True))
    d = json.loads(out)
    assert rc == 2 == d["exit_code"] and d["total"] == 0 and d["records"] == []
    assert not pathlib.Path(cfg.state).exists(), \
        "outcomes_cli(as_json=True) must NOT create the state dir (read-only)"
    assert _snapshot_tree(empty_cwd) == {}, "--json created a file in cwd"


# ==========================================================================
# F. argparse / main dispatch                                (Behavior 17)
# ==========================================================================
def test_b17_main_passes_as_json_and_limit_via_spy(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    captured = {}

    def spy(cfg, limit=None, as_json=False):
        captured["limit"] = limit
        captured["as_json"] = as_json
        return 0

    monkeypatch.setattr(foundry, "outcomes_cli", spy)
    # --json present -> as_json True
    _capture(lambda: foundry.main(["outcomes", "--config", str(cfg_path), "--json"]))
    assert captured.get("as_json") is True, "--json must pass as_json=True"
    assert captured.get("limit") is None, "no --limit -> default None"
    # --json absent -> as_json False
    captured.clear()
    _capture(lambda: foundry.main(["outcomes", "--config", str(cfg_path)]))
    assert captured.get("as_json") is False, "no --json -> as_json False"
    # --limit N -> limit N (and as_json still False)
    captured.clear()
    _capture(lambda: foundry.main(["outcomes", "--config", str(cfg_path), "--limit", "7"]))
    assert captured.get("limit") == 7 and captured.get("as_json") is False


def test_b17_main_config_required_systemexit2():
    with pytest.raises(SystemExit) as ei:
        foundry.main(["outcomes", "--json"])
    assert ei.value.code == 2, "omitting --config must raise SystemExit(2)"


def test_b17_main_json_end_to_end(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_outcome(cfg, 1, review="APPROVE", tester="PASS", action="PUSHED s1")
    _write_outcome(cfg, 2, review="CHANGES_REQUIRED", tester="FAIL", action="REVERTED")
    rc_json, out_json, _ = _capture(
        lambda: foundry.main(["outcomes", "--config", str(cfg_path), "--json"]))
    d = json.loads(out_json)                       # whole stdout is JSON
    assert list(d.keys()) == list(SUMMARY_KEYS), "8-key dict"
    assert d["product"] == cfg.name == "demoprod"
    # without --json -> human render, SAME exit code
    rc_human, out_human, _ = _capture(
        lambda: foundry.main(["outcomes", "--config", str(cfg_path)]))
    assert rc_json == rc_human == d["exit_code"] == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_human)
    assert "foundry outcomes -- demoprod" in out_human


def test_b17_json_flag_store_true_default_off(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_outcome(cfg, 1, review="APPROVE", tester="PASS", action="PUSHED s1")
    _, out_default, _ = _capture(
        lambda: foundry.main(["outcomes", "--config", str(cfg_path)]))
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_default)
    _, out_flag, _ = _capture(
        lambda: foundry.main(["outcomes", "--config", str(cfg_path), "--json"]))
    assert isinstance(json.loads(out_flag), dict)


# ==========================================================================
# G. Dormancy, signature, import regression                  (Behavior 18)
# ==========================================================================
def test_b18_outcomes_cli_signature():
    sig = inspect.signature(foundry.outcomes_cli)
    assert list(sig.parameters) == ["cfg", "limit", "as_json"], \
        f"outcomes_cli signature must be (cfg, limit, as_json): {list(sig.parameters)}"
    assert sig.parameters["limit"].default is None
    assert sig.parameters["as_json"].default is False


def test_b18_to_dict_present_on_both_value_objects():
    assert hasattr(foundry.IterationOutcome, "to_dict") and \
        callable(foundry.IterationOutcome.to_dict)
    assert hasattr(foundry.OutcomesSummary, "to_dict") and \
        callable(foundry.OutcomesSummary.to_dict)


def test_b18_outcomes_symbols_off_the_orchestrator_control_path():
    # NOTE: `to_dict` is a GENERIC method name shared by ~30 value objects, so we
    # scan for the outcomes-SPECIFIC class/function names + the `outcomes`
    # subcommand literal (the meaningful dormancy proxy), NOT the bare `to_dict`.
    for fn_name in ORCHESTRATORS:
        assert callable(getattr(foundry, fn_name)), \
            f"orchestrator foundry.{fn_name} missing (regression)"
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in OUTCOMES_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references {sym!r} (outcomes must stay off the control path)"
        assert "outcomes" not in consts, \
            f"{fn_name} contains the 'outcomes' subcommand literal (off-control-path)"


def test_b18_outcomes_symbols_absent_from_dispatcher():
    for sym in OUTCOMES_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, consts = _module_names_consts(dispatcher)
    for sym in OUTCOMES_SYMBOLS:
        assert sym not in names, f"dispatcher references {sym!r} (must stay untouched)"
    assert "outcomes" not in consts, "dispatcher references the 'outcomes' subcommand literal"


def test_b18_both_modules_import():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"
