"""Black-box behaviour tests for iter 20 -- a machine-readable `--json` output
mode over the read-only, offline `foundry history` multi-iteration ship LEDGER
(iter 17). ALL additive in foundry.py:

  * a PURE `IterationRecord.to_dict() -> dict` (4 fixed-order keys: the 3 stored
    fields `iteration`/`action`/`postrelease` verbatim + the derived `label`),
  * a PURE `HistorySummary.to_dict() -> dict` (7 fixed-order keys: `product` +
    the four frozen counts `total`/`shipped`/`reverted`/`broken` + `exit_code`
    REUSED verbatim from the iter-17 properties + `records`, a list of the
    per-record `to_dict()` dicts in stored order), all JSON-native,
  * a `history_cli(cfg, limit=None, as_json: bool = False) -> int` -- on True it
    prints ONE JSON document (the WHOLE stdout) == the summary's `to_dict()` and
    returns the SAME exit code as the human path; on False/default it is
    byte-identical to iter 17,
  * a `history --json` argparse flag (`store_true`, default off) routed by `main`.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-20 PM
spec's Expected Behaviors (1-8), the product README/roadmap, the `tests/`
conventions, and the product's own OBSERVABLE behaviour (via running it / public
runtime introspection -- `inspect.signature`, module attributes, `--help`,
compiled `__code__.co_names`/`co_consts`). The implementation source (foundry.py /
dispatcher.py internals), the engineer's and reviewer's notes, and `git diff`
were NOT read. Every check drives the PUBLIC interface: the pure `to_dict()` on
`foundry.IterationRecord(...)` / `foundry.HistorySummary(...)`, and the CLI via
`foundry.history_cli(cfg, as_json=...)` / `foundry.main(["history", ...])`
against a TMP-`work_root` config with real `state/iter-NN/final.md` + optional
`postrelease.md` files (the real foundry repo/state is NEVER touched). Fully
offline & deterministic: real temp files only; ZERO real subprocess / git /
network (except the `import` regression probe, which only imports).
"""
import dataclasses
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


# --------------------------------------------------------------------------
# helpers  (mirror tests/test_iter17_behavior.py + test_iter19_behavior.py)
# --------------------------------------------------------------------------
RECORD_KEYS = ("iteration", "action", "postrelease", "label")            # Behavior 1
SUMMARY_KEYS = ("product", "total", "shipped", "reverted", "broken",
                "exit_code", "records")                                   # Behavior 2

# iter-20 additions that must stay OFF the pipeline/dispatcher control path
HISTORY_SYMBOLS = ("history_cli", "summarize_history",
                   "IterationRecord", "HistorySummary")
JSON_SURFACE_SYMBOLS = ("to_dict",)
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")


def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir. `repo`/`work_root` are TMP dirs so
    the real foundry repo/state is NEVER touched."""
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


def _write_final(cfg, iteration, action_line):
    """state/iter-NN/final.md whose LAST non-empty line is `action_line`."""
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    (d / "final.md").write_text(f"final gate report\n\n{action_line}\n\n   \n")
    return d / "final.md"


def _write_postrelease(cfg, iteration, verdict):
    """state/iter-NN/postrelease.md whose LAST non-empty line is the sentinel."""
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    (d / "postrelease.md").write_text(
        f"post-release verification report\n\nPOSTRELEASE: {verdict}\n")
    return d / "postrelease.md"


def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY; return (rc, out, err).
    Separate capture matters: Behaviors 3-6 require JSON to be the ENTIRE stdout."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _iters_in_human(out):
    """The sorted iteration ints whose `iter-NN` row appears in human render text."""
    found = set()
    for ln in out.splitlines():
        for tok in ln.split():
            if tok.startswith("iter-") and tok[5:].isdigit():
                found.add(int(tok[5:]))
    return sorted(found)


def _reconstruct_summary_dict(d):
    """Rebuild a HistorySummary from the JSON's stored fields and confirm its
    to_dict() == d. A black-box proof the CLI emitted a faithful, self-consistent
    serialization: the counts/exit_code/labels are the class's own derivations
    over the records, so any re-derivation drift would break equality."""
    recs = [foundry.IterationRecord(r["iteration"], r["action"], r["postrelease"])
            for r in d["records"]]
    s2 = foundry.summarize_history(product=d["product"], records=recs)
    return s2.to_dict()


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


def _records_mixed():
    R = foundry.IterationRecord
    return [
        R(1, "PUSHED", None),        # shipped
        R(2, "PUSHED", "HEALTHY"),   # shipped/healthy
        R(3, "REVERTED", None),      # reverted
        R(4, "PUSHED", "BROKEN"),    # shipped/BROKEN
        R(5, None, None),            # no-ship
    ]


# ==========================================================================
# Behavior 1 -- IterationRecord.to_dict(): 4 keys in order, JSON-native, round-trips
# ==========================================================================
def test_b1_record_to_dict_keys_exact_and_ordered():
    R = foundry.IterationRecord
    for r in (R(3, "PUSHED", "HEALTHY"),
              R(0, "REVERTED", None),
              R(7, None, "BROKEN"),
              R(2, "PUSHED", None),
              R(9, None, None)):
        d = r.to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == list(RECORD_KEYS), (
            f"record to_dict keys/order wrong.\n got: {list(d.keys())}\n"
            f"want: {list(RECORD_KEYS)}")
        assert len(d) == 4


def test_b1_record_values_verbatim_and_label_matches_property():
    R = foundry.IterationRecord
    cases = [
        R(3, "PUSHED", "HEALTHY"),
        R(1, "REVERTED", "BROKEN"),
        R(5, "PUSHED", None),
        R(6, None, "HEALTHY"),
        R(4, "PUSHED", "BROKEN"),
    ]
    for r in cases:
        d = r.to_dict()
        assert d["iteration"] == r.iteration and isinstance(d["iteration"], int)
        assert d["action"] == r.action           # str | None verbatim
        assert d["postrelease"] == r.postrelease  # str | None verbatim
        assert d["label"] == r.label and isinstance(d["label"], str), (
            f"label must equal the record's derived label verbatim: "
            f"{d['label']!r} != {r.label!r}")


def test_b1_record_json_native_and_round_trips():
    R = foundry.IterationRecord
    for r in (R(3, "PUSHED", "HEALTHY"), R(0, None, None),
              R(2, "REVERTED", "BROKEN"), R(8, "PUSHED", None)):
        d = r.to_dict()
        text = json.dumps(d)                       # must not raise
        assert json.loads(text) == d, "record to_dict must survive a json round-trip"
        d2 = json.loads(text)
        if r.action is None:
            assert d2["action"] is None, "None action must serialize to JSON null"
        if r.postrelease is None:
            assert d2["postrelease"] is None, "None postrelease must serialize to null"
        assert isinstance(d2["iteration"], int)


# ==========================================================================
# Behavior 2 -- HistorySummary.to_dict(): 7 keys in order; counts REUSE the
#               frozen properties; records is a list of per-record dicts in order
# ==========================================================================
def test_b2_summary_to_dict_keys_exact_and_ordered():
    for recs in (_records_mixed(), [], [foundry.IterationRecord(1, "PUSHED", None)]):
        s = foundry.HistorySummary("demoprod", tuple(recs))
        d = s.to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == list(SUMMARY_KEYS), (
            f"summary to_dict keys/order wrong.\n got: {list(d.keys())}\n"
            f"want: {list(SUMMARY_KEYS)}")
        assert len(d) == 7


def test_b2_counts_reuse_frozen_properties_records_in_order():
    recs = _records_mixed()
    s = foundry.HistorySummary("prodX", tuple(recs))
    d = s.to_dict()
    assert d["product"] == s.product and isinstance(d["product"], str)
    # every count value EQUALS the corresponding frozen property (no re-derivation)
    assert d["total"] == s.total and isinstance(d["total"], int)
    assert d["shipped"] == s.shipped and isinstance(d["shipped"], int)
    assert d["reverted"] == s.reverted and isinstance(d["reverted"], int)
    assert d["broken"] == s.broken and isinstance(d["broken"], int)
    assert d["exit_code"] == s.exit_code and isinstance(d["exit_code"], int)
    # known facts for the mixed fixture
    assert (d["total"], d["shipped"], d["reverted"], d["broken"], d["exit_code"]) == \
        (5, 3, 1, 1, 0)
    # records is a JSON array of the per-record to_dict dicts, SAME order as s.records
    assert isinstance(d["records"], list)
    assert d["records"] == [r.to_dict() for r in s.records]
    assert [r["iteration"] for r in d["records"]] == [r.iteration for r in s.records]


def test_b2_summary_json_native_and_round_trips():
    for recs in (_records_mixed(), [],
                 [foundry.IterationRecord(1, "REVERTED", "BROKEN")]):
        s = foundry.HistorySummary("demoprod", tuple(recs))
        d = s.to_dict()
        text = json.dumps(d)                       # must not raise
        assert json.loads(text) == d, "summary to_dict must survive a json round-trip"


def test_b2_empty_summary_dict():
    s = foundry.HistorySummary("demoprod", ())
    d = s.to_dict()
    assert d["total"] == 0 and d["records"] == [] and d["exit_code"] == 2
    assert d["shipped"] == d["reverted"] == d["broken"] == 0


# ==========================================================================
# Behavior 3 -- history_cli(cfg, as_json=True) prints ONE JSON doc == to_dict(),
#               returns summary.exit_code, parsed["exit_code"] == returned int
# ==========================================================================
def test_b3_json_path_single_doc_equals_to_dict(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_final(cfg, 1, "ACTION: PUSHED abc1")            # shipped
    _write_final(cfg, 2, "ACTION: PUSHED abc2"); _write_postrelease(cfg, 2, "HEALTHY")
    _write_final(cfg, 3, "ACTION: REVERTED")               # reverted
    _write_final(cfg, 4, "ACTION: PUSHED abc4"); _write_postrelease(cfg, 4, "BROKEN")
    before = _snapshot_tree(tmp_path)

    rc_json, out_json, err = _capture(lambda: foundry.history_cli(cfg, as_json=True))
    # the WHOLE stdout parses as ONE JSON document into a dict
    d = json.loads(out_json)
    assert isinstance(d, dict)
    # same integer as the non-json path over identical state
    rc_human, _, _ = _capture(lambda: foundry.history_cli(cfg))
    assert rc_json == rc_human == d["exit_code"] == 0, (
        f"json/human/parsed exit disagree: {rc_json} {rc_human} {d['exit_code']}")
    # parsed == to_dict() of a HistorySummary over the SAME gathered records
    assert d == _reconstruct_summary_dict(d), \
        "JSON payload is not a self-consistent HistorySummary serialization"
    # known facts of the gathered ledger
    assert d["product"] == cfg.name == "demoprod"
    assert (d["total"], d["shipped"], d["reverted"], d["broken"]) == (4, 3, 1, 1)
    assert [r["iteration"] for r in d["records"]] == [1, 2, 3, 4]
    labels = {r["iteration"]: r["label"] for r in d["records"]}
    assert labels == {1: "shipped", 2: "shipped/healthy",
                      3: "reverted", 4: "shipped/BROKEN"}
    # read-only: nothing written under the temp tree, no stray stderr noise
    assert _snapshot_tree(tmp_path) == before, "history --json wrote a file (must be read-only)"


def test_b3_json_records_match_human_selection(tmp_path):
    """Cross-check: the JSON records are exactly the iterations the human path lists,
    and the JSON rollup counts match the human rollup text."""
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_final(cfg, 1, "ACTION: PUSHED s1"); _write_postrelease(cfg, 1, "BROKEN")
    _write_final(cfg, 2, "ACTION: PUSHED s2"); _write_postrelease(cfg, 2, "HEALTHY")
    rc_json, out_json, _ = _capture(lambda: foundry.history_cli(cfg, as_json=True))
    rc_human, out_human, _ = _capture(lambda: foundry.history_cli(cfg))
    d = json.loads(out_json)
    assert rc_json == rc_human == 0, "a PAST broken is informational -> exit 0 on both"
    assert [r["iteration"] for r in d["records"]] == _iters_in_human(out_human)
    # the human rollup words match the JSON counts
    assert f"{d['total']} iterations: {d['shipped']} shipped, " \
           f"{d['reverted']} reverted, {d['broken']} broken" in out_human
    assert d["broken"] == 1


# ==========================================================================
# Behavior 4 -- default / as_json=False is byte-identical to iter 17 (NOT JSON)
# ==========================================================================
def test_b4_default_equals_as_json_false_and_is_human_render(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_final(cfg, 1, "ACTION: PUSHED s1")
    _write_final(cfg, 2, "ACTION: PUSHED s2"); _write_postrelease(cfg, 2, "HEALTHY")
    before = _snapshot_tree(tmp_path)

    rc_default, out_default, _ = _capture(lambda: foundry.history_cli(cfg))
    rc_false, out_false, _ = _capture(lambda: foundry.history_cli(cfg, as_json=False))
    # default == explicit as_json=False, byte-for-byte (same code path)
    assert out_default == out_false, "default must equal as_json=False output byte-for-byte"
    assert rc_default == rc_false == 0
    # the human output is NOT a single JSON document (>=1 record) -> json.loads raises
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_default)
    # it IS the iter-17 human render (regression guard on the ledger surface)
    assert "foundry history -- demoprod" in out_default
    assert "iter-01" in out_default and "iter-02" in out_default
    assert "shipped/healthy" in out_default
    assert "2 iterations: 2 shipped, 0 reverted, 0 broken" in out_default
    assert _snapshot_tree(tmp_path) == before, "human history wrote a file (must be read-only)"


def test_b4_default_param_value_is_false():
    # the new parameter's default is False (acceptance criterion)
    sig = inspect.signature(foundry.history_cli)
    assert "as_json" in sig.parameters, "history_cli must gain an as_json parameter"
    assert sig.parameters["as_json"].default is False, \
        "as_json default must be False (byte-identical-by-default guarantee)"


# ==========================================================================
# Behavior 5 -- foundry history --config <cfg> [--json] end-to-end via main()
# ==========================================================================
def test_b5_main_json_flag_prints_payload_same_exit(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_final(cfg, 1, "ACTION: PUSHED s1")
    _write_final(cfg, 2, "ACTION: REVERTED")
    _write_final(cfg, 3, "ACTION: PUSHED s3"); _write_postrelease(cfg, 3, "HEALTHY")

    rc_json, out_json, _ = _capture(
        lambda: foundry.main(["history", "--config", str(cfg_path), "--json"]))
    d = json.loads(out_json)                       # whole stdout is JSON
    rc_human, out_human, _ = _capture(
        lambda: foundry.main(["history", "--config", str(cfg_path)]))
    # --json returns the SAME exit code as the human path
    assert rc_json == rc_human == d["exit_code"] == 0
    # payload equals the to_dict() (Behaviors 2-3)
    assert d == _reconstruct_summary_dict(d)
    assert [r["iteration"] for r in d["records"]] == [1, 2, 3]
    # no --json -> human ledger (NOT json)
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_human)
    assert "foundry history -- demoprod" in out_human


def test_b5_json_flag_is_store_true_default_off(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_final(cfg, 1, "ACTION: PUSHED s1"); _write_postrelease(cfg, 1, "HEALTHY")
    # default off: no --json -> human path (not parseable JSON)
    _, out_default, _ = _capture(
        lambda: foundry.main(["history", "--config", str(cfg_path)]))
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_default)
    # flag on: --json -> parseable JSON document
    _, out_flag, _ = _capture(
        lambda: foundry.main(["history", "--config", str(cfg_path), "--json"]))
    assert isinstance(json.loads(out_flag), dict)


# ==========================================================================
# Behavior 6 -- empty-state JSON is valid (total 0, records [], exit 2 -> 2);
#               non-json empty-state human output/exit unchanged from iter 17
# ==========================================================================
def test_b6_empty_state_dir_json(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    pathlib.Path(cfg.state).mkdir(parents=True, exist_ok=True)  # state/, no iter-* dirs
    before = _snapshot_tree(tmp_path)
    rc_json, out_json, _ = _capture(lambda: foundry.history_cli(cfg, as_json=True))
    d = json.loads(out_json)                       # ONE valid JSON doc
    assert rc_json == 2 == d["exit_code"]
    assert d["total"] == 0 and d["records"] == []
    assert d == _reconstruct_summary_dict(d)
    # non-json empty-state human path unchanged (exit 2, 'no iterations yet')
    rc_human, out_human, _ = _capture(lambda: foundry.history_cli(cfg))
    assert rc_human == 2 and "no iterations yet" in out_human
    assert _snapshot_tree(tmp_path) == before, "empty history --json wrote a file"


def test_b6_absent_state_dir_json_is_read_only(tmp_path):
    # state/ does not exist at all -> the missing-dir guard -> valid empty JSON, exit 2.
    # (main eagerly creates work/state, so drive history_cli directly after delete.)
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    shutil.rmtree(cfg.state, ignore_errors=True)
    assert not pathlib.Path(cfg.state).exists()
    rc, out, _ = _capture(lambda: foundry.history_cli(cfg, as_json=True))
    d = json.loads(out)
    assert rc == 2 == d["exit_code"] and d["total"] == 0 and d["records"] == []
    assert not pathlib.Path(cfg.state).exists(), \
        "history --json must NOT create the state dir (read-only guard)"


# ==========================================================================
# Behavior 7 -- --json honours --limit N (most-recent N, ascending; every field
#               computed over the limited set, identical selection to human path)
# ==========================================================================
def test_b7_json_limit_most_recent_n_ascending(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    for n in range(1, 6):
        _write_final(cfg, n, f"ACTION: PUSHED sha{n}")
        _write_postrelease(cfg, n, "HEALTHY")
    # via history_cli
    rc, out, _ = _capture(lambda: foundry.history_cli(cfg, limit=2, as_json=True))
    d = json.loads(out)
    iters = [r["iteration"] for r in d["records"]]
    assert iters == [4, 5], f"most-recent 2, ascending (oldest-first): {iters}"
    # every field reflects only the limited window
    assert d["total"] == 2 and d["shipped"] == 2 and d["reverted"] == 0 and d["broken"] == 0
    assert d["exit_code"] == rc == 0
    assert d == _reconstruct_summary_dict(d)
    # identical selection to the human path with the same limit
    _, out_human, _ = _capture(lambda: foundry.history_cli(cfg, limit=2))
    assert iters == _iters_in_human(out_human)


def test_b7_main_json_limit_matches_human(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    for n in range(1, 6):
        _write_final(cfg, n, f"ACTION: PUSHED sha{n}")
    rc_json, out_json, _ = _capture(
        lambda: foundry.main(["history", "--config", str(cfg_path), "--limit", "3", "--json"]))
    rc_human, out_human, _ = _capture(
        lambda: foundry.main(["history", "--config", str(cfg_path), "--limit", "3"]))
    d = json.loads(out_json)
    assert [r["iteration"] for r in d["records"]] == [3, 4, 5] == _iters_in_human(out_human)
    assert d["total"] == 3 and rc_json == rc_human == d["exit_code"] == 0


def test_b7_json_nonpositive_limit_shows_all_like_human(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    for n in range(1, 4):
        _write_final(cfg, n, f"ACTION: PUSHED sha{n}")
    rc, out, _ = _capture(lambda: foundry.history_cli(cfg, limit=0, as_json=True))
    d = json.loads(out)
    _, out_human, _ = _capture(lambda: foundry.history_cli(cfg, limit=0))
    assert [r["iteration"] for r in d["records"]] == [1, 2, 3] == _iters_in_human(out_human), \
        "non-positive --limit must show ALL, identical selection to the human path"


# ==========================================================================
# Behavior 8 -- purely additive & off the control path (public introspection)
# ==========================================================================
def test_b8_both_modules_import():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b8_json_surface_present_and_callable():
    assert hasattr(foundry.IterationRecord, "to_dict") and callable(foundry.IterationRecord.to_dict)
    assert hasattr(foundry.HistorySummary, "to_dict") and callable(foundry.HistorySummary.to_dict)
    assert callable(foundry.history_cli)
    assert callable(foundry.summarize_history)
    # pre-existing control-flow entry points remain present + callable (regression)
    for fn in CONTROL_FLOW_FNS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"


def test_b8_new_surface_off_the_foundry_control_path():
    for fn_name in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in HISTORY_SYMBOLS + JSON_SURFACE_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references {sym!r} (must stay off the control path)"
        # neither the 'history' subcommand literal nor the '--json' flag may leak
        assert "history" not in consts, \
            f"{fn_name} contains the 'history' subcommand literal (off-control-path)"
        assert "--json" not in consts, \
            f"{fn_name} contains the '--json' flag literal (off-control-path)"


def test_b8_new_surface_absent_from_dispatcher():
    for sym in HISTORY_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, consts = _module_names_consts(dispatcher)
    for sym in HISTORY_SYMBOLS:
        assert sym not in names, f"dispatcher references {sym!r} (must stay untouched)"
    assert "history" not in consts, "dispatcher references the 'history' subcommand literal"
    assert "--json" not in consts, "dispatcher references the '--json' flag literal"


def test_b8_history_cli_writes_nothing(tmp_path):
    # read-only guarantee across BOTH json and human paths on a populated ledger
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_final(cfg, 1, "ACTION: PUSHED s1"); _write_postrelease(cfg, 1, "HEALTHY")
    _write_final(cfg, 2, "ACTION: REVERTED")
    before = _snapshot_tree(tmp_path)
    _capture(lambda: foundry.history_cli(cfg, as_json=True))
    _capture(lambda: foundry.history_cli(cfg))
    assert _snapshot_tree(tmp_path) == before, "history_cli wrote to disk (must be read-only)"


def test_b8_sentinels_unchanged():
    # additive bite must not remove/rename the release sentinels (regression).
    _, consts = _module_names_consts(foundry)
    for sentinel in ("VERDICT:", "RESULT:", "ACTION:", "POSTRELEASE:"):
        assert any(sentinel in c for c in consts), \
            f"sentinel prefix {sentinel!r} vanished from foundry"


def test_b8_help_lists_history_subcommand(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for sub in ("run", "once", "doctor", "learnings", "agents",
                "lint-spec", "prd", "gate-scope", "status", "history"):
        assert sub in out, f"subcommand {sub!r} missing from --help:\n{out}"
