"""Black-box behaviour tests for iter 21 -- a machine-readable ``--json`` output
mode over the read-only, offline ``foundry timing`` PER-ITERATION SUITE
WALL-TIME DIGEST (iter 18). ALL additive in foundry.py:

  * a PURE ``TimingRecord.to_dict() -> dict`` (2 fixed-order keys:
    ``iteration`` (int) + ``seconds`` (float | None -- a measured ``0.0`` stays
    the float ``0.0``, distinct from ``None``), JSON-native, round-trips),
  * a PURE ``TimingSummary.to_dict() -> dict`` (11 fixed-order keys: ``product``
    + the eight frozen stats/counts (``total``/``measured``/``min_seconds``/
    ``max_seconds``/``avg_seconds``/``last_seconds``/``count_slow``/``exit_code``)
    REUSED verbatim from the iter-18 properties + ``threshold`` (stored) +
    ``records``, a list of the per-record ``to_dict()`` dicts in stored order),
    all JSON-native, round-trips (incl. all-None stats),
  * a ``timing_cli(cfg, limit=None, as_json: bool = False) -> int`` -- on True it
    prints ONE JSON document (the WHOLE stdout) == the summary's ``to_dict()`` and
    returns the SAME exit code as the human path; on False/default it is
    byte-identical to iter 18,
  * a ``timing --json`` argparse flag (``store_true``, default off) routed by
    ``main`` as ``as_json=args.json``.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-21 PM
spec's Expected Behaviors (1-8), the product README/roadmap, the ``tests/``
conventions (esp. tests/test_iter18_behavior.py + test_iter20_behavior.py), and
the product's own OBSERVABLE behaviour (via running it / public RUNTIME
introspection -- ``inspect.signature``, module attributes, ``--help``, compiled
``__code__.co_names`` / ``co_consts``). The implementation source (foundry.py /
dispatcher.py internals), the engineer's and reviewer's notes, and ``git diff``
were NOT read. Every check drives the PUBLIC interface: the pure ``to_dict()`` on
``foundry.TimingRecord(...)`` / ``foundry.TimingSummary(...)`` (built via
``foundry.summarize_timing(...)``), and the CLI via
``foundry.timing_cli(cfg, as_json=...)`` / ``foundry.main(["timing", ...])``
against a TMP-``work_root`` config with real ``state/iter-NN/postrelease.md``
files (the real foundry repo/state is NEVER touched). Fully offline &
deterministic: real temp files only; ZERO real subprocess / git / network
(except the ``import`` regression probe, which only imports).
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


# --------------------------------------------------------------------------
# helpers  (mirror tests/test_iter18_behavior.py + test_iter20_behavior.py)
# --------------------------------------------------------------------------
RECORD_KEYS = ("iteration", "seconds")                                    # Behavior 1
SUMMARY_KEYS = ("product", "total", "measured", "min_seconds", "max_seconds",
                "avg_seconds", "last_seconds", "count_slow", "threshold",
                "exit_code", "records")                                    # Behavior 2

# genuinely-new iter-21 JSON surface (must stay OFF the control path)
JSON_SURFACE_SYMBOLS = ("to_dict",)
# the iter-18 timing surface must likewise never leak onto the control path
TIMING_SYMBOLS = ("timing_cli", "summarize_timing", "TimingRecord",
                  "TimingSummary", "parse_suite_seconds")
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


def _write_postrelease(cfg, iteration, value):
    """state/iter-NN/postrelease.md carrying a `- suite_seconds: <value>` line
    (the durable per-iteration timing signal) + the trailing POSTRELEASE sentinel.
    `value` is written verbatim (e.g. '12.34', 'n/a')."""
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    (d / "postrelease.md").write_text(
        "post-release verification report\n\n"
        f"- suite_seconds: {value}\n"
        "POSTRELEASE: HEALTHY\n"
    )
    return d / "postrelease.md"


def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY; return (rc, out, err).
    Separate capture matters: Behaviors 3-7 require JSON to be the ENTIRE stdout."""
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
    """Rebuild a TimingSummary from the JSON's stored fields (records + product +
    threshold) and confirm its to_dict() == d. A black-box proof the CLI emitted
    a faithful, self-consistent serialization: the stats/counts/exit_code are the
    class's OWN derivations over the records, so any re-derivation drift breaks
    equality."""
    recs = [foundry.TimingRecord(r["iteration"], r["seconds"]) for r in d["records"]]
    s2 = foundry.summarize_timing(product=d["product"], records=recs,
                                  threshold=d["threshold"])
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


def _spec_records():
    """The iter-18 concrete example: seconds [None,10,30,None,20], iters 1..5."""
    R = foundry.TimingRecord
    return [R(1, None), R(2, 10.0), R(3, 30.0), R(4, None), R(5, 20.0)]


# ==========================================================================
# Behavior 1 -- TimingRecord.to_dict(): 2 keys in order, JSON-native, round-trips
# ==========================================================================
def test_b1_record_to_dict_keys_exact_and_ordered():
    R = foundry.TimingRecord
    for r in (R(3, 12.34), R(0, None), R(7, 0.0), R(2, 999.5)):
        d = r.to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == list(RECORD_KEYS), (
            f"record to_dict keys/order wrong.\n got: {list(d.keys())}\n"
            f"want: {list(RECORD_KEYS)}")
        assert len(d) == 2


def test_b1_record_values_verbatim():
    R = foundry.TimingRecord
    for r in (R(3, 12.34), R(1, None), R(5, 20.0), R(6, 0.0)):
        d = r.to_dict()
        assert d["iteration"] == r.iteration and isinstance(d["iteration"], int)
        assert d["seconds"] == r.seconds  # float | None verbatim


def test_b1_measured_zero_distinct_from_none():
    R = foundry.TimingRecord
    d_zero = R(4, 0.0).to_dict()
    d_none = R(4, None).to_dict()
    assert d_zero["seconds"] == 0.0 and isinstance(d_zero["seconds"], float), \
        "a measured 0.0 must serialize to the float 0.0, NOT None"
    assert d_zero["seconds"] is not None
    assert d_none["seconds"] is None, "an unmeasured record must serialize to null"


def test_b1_record_json_native_and_round_trips():
    R = foundry.TimingRecord
    for r in (R(3, 12.34), R(0, None), R(2, 0.0), R(8, 30.0)):
        d = r.to_dict()
        text = json.dumps(d)                       # must not raise
        assert json.loads(text) == d, "record to_dict must survive a json round-trip"
        d2 = json.loads(text)
        if r.seconds is None:
            assert d2["seconds"] is None, "None seconds must serialize to JSON null"
        assert isinstance(d2["iteration"], int)


# ==========================================================================
# Behavior 2 -- TimingSummary.to_dict(): 11 keys in order; stats/counts REUSE the
#               frozen properties; records is a list of per-record dicts in order
# ==========================================================================
def test_b2_summary_to_dict_keys_exact_and_ordered():
    R = foundry.TimingRecord
    for recs in (_spec_records(), [], [R(1, 5.0)], [R(1, None), R(2, None)]):
        s = foundry.summarize_timing(product="demoprod", records=recs, threshold=120.0)
        d = s.to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == list(SUMMARY_KEYS), (
            f"summary to_dict keys/order wrong.\n got: {list(d.keys())}\n"
            f"want: {list(SUMMARY_KEYS)}")
        assert len(d) == 11


def test_b2_values_reuse_frozen_properties_records_in_order():
    s = foundry.summarize_timing(product="prodX", records=_spec_records(), threshold=20.0)
    d = s.to_dict()
    # product + threshold equal the stored fields
    assert d["product"] == s.product and isinstance(d["product"], str)
    assert d["threshold"] == s.threshold == 20.0 and isinstance(d["threshold"], float)
    # every derived value EQUALS the corresponding frozen property (no re-derivation)
    assert d["total"] == s.total and isinstance(d["total"], int)
    assert d["measured"] == s.measured and isinstance(d["measured"], int)
    assert d["min_seconds"] == s.min_seconds
    assert d["max_seconds"] == s.max_seconds
    assert d["avg_seconds"] == s.avg_seconds
    assert d["last_seconds"] == s.last_seconds
    assert d["count_slow"] == s.count_slow and isinstance(d["count_slow"], int)
    assert d["exit_code"] == s.exit_code and isinstance(d["exit_code"], int)
    # known facts for the spec fixture (threshold 20 -> only 30.0 is slow)
    assert (d["total"], d["measured"]) == (5, 3)
    assert (d["min_seconds"], d["max_seconds"], d["avg_seconds"], d["last_seconds"]) == \
        (10.0, 30.0, 20.0, 20.0)
    assert d["count_slow"] == 1 and d["exit_code"] == 0
    # records is a JSON array of the per-record to_dict dicts, SAME order as s.records
    assert isinstance(d["records"], list)
    assert d["records"] == [r.to_dict() for r in s.records]
    assert [r["iteration"] for r in d["records"]] == [r.iteration for r in s.records]
    assert [r["seconds"] for r in d["records"]] == [None, 10.0, 30.0, None, 20.0]


def test_b2_summary_json_native_and_round_trips():
    R = foundry.TimingRecord
    for recs in (_spec_records(), [], [R(1, None), R(2, None)], [R(1, 0.0)]):
        s = foundry.summarize_timing(product="demoprod", records=recs, threshold=120.0)
        d = s.to_dict()
        text = json.dumps(d)                       # must not raise
        assert json.loads(text) == d, "summary to_dict must survive a json round-trip"


def test_b2_all_none_stats_serialize_null():
    R = foundry.TimingRecord
    s = foundry.summarize_timing(product="p", records=[R(1, None), R(2, None)],
                                 threshold=120.0)
    d = s.to_dict()
    assert d["total"] == 2 and d["measured"] == 0
    assert d["min_seconds"] is None and d["max_seconds"] is None
    assert d["avg_seconds"] is None and d["last_seconds"] is None
    assert d["count_slow"] == 0 and d["exit_code"] == 2
    # the four measured-only stats survive as JSON null through a round-trip
    d2 = json.loads(json.dumps(d))
    for k in ("min_seconds", "max_seconds", "avg_seconds", "last_seconds"):
        assert d2[k] is None
    assert d2 == d


def test_b2_empty_summary_dict():
    s = foundry.summarize_timing(product="demoprod", records=[], threshold=120.0)
    d = s.to_dict()
    assert d["total"] == 0 and d["measured"] == 0 and d["records"] == []
    assert d["exit_code"] == 2
    for k in ("min_seconds", "max_seconds", "avg_seconds", "last_seconds"):
        assert d[k] is None
    assert d["count_slow"] == 0


# ==========================================================================
# Behavior 3 -- timing_cli(cfg, as_json=True) prints ONE JSON doc == to_dict(),
#               returns summary.exit_code, parsed["exit_code"] == returned int
# ==========================================================================
def test_b3_json_path_single_doc_equals_to_dict(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 1, "10.00")
    _write_postrelease(cfg, 2, "n/a")                  # unmeasured
    _write_postrelease(cfg, 3, "30.00")
    _iter_dir(cfg, 4).mkdir(parents=True, exist_ok=True)  # dir, no postrelease.md
    _write_postrelease(cfg, 5, "20.00")
    before = _snapshot_tree(tmp_path)

    rc_json, out_json, err = _capture(lambda: foundry.timing_cli(cfg, as_json=True))
    # the WHOLE stdout parses as ONE JSON document into a dict
    d = json.loads(out_json)
    assert isinstance(d, dict)
    # same integer as the non-json path over identical state
    rc_human, _, _ = _capture(lambda: foundry.timing_cli(cfg))
    assert rc_json == rc_human == d["exit_code"] == 0, (
        f"json/human/parsed exit disagree: {rc_json} {rc_human} {d['exit_code']}")
    # parsed == to_dict() of a TimingSummary over the SAME gathered records
    assert d == _reconstruct_summary_dict(d), \
        "JSON payload is not a self-consistent TimingSummary serialization"
    # known facts of the gathered digest
    assert d["product"] == cfg.name == "demoprod"
    assert d["threshold"] == foundry.SUITE_SLOW_SECONDS == 120.0
    assert [r["iteration"] for r in d["records"]] == [1, 2, 3, 4, 5]
    secs = {r["iteration"]: r["seconds"] for r in d["records"]}
    assert secs == {1: 10.0, 2: None, 3: 30.0, 4: None, 5: 20.0}
    assert (d["total"], d["measured"]) == (5, 3)
    assert (d["min_seconds"], d["max_seconds"], d["last_seconds"]) == (10.0, 30.0, 20.0)
    # read-only: nothing written under the temp tree
    assert _snapshot_tree(tmp_path) == before, "timing --json wrote a file (must be read-only)"


def test_b3_threshold_read_from_global_at_call_time(monkeypatch, tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 1, "50.00")
    # default threshold 120 -> 50 is NOT slow, and the JSON threshold field is 120
    _, out, _ = _capture(lambda: foundry.timing_cli(cfg, as_json=True))
    d = json.loads(out)
    assert d["threshold"] == 120.0 and d["count_slow"] == 0
    # patch the module global LOW -> read AT CALL TIME (exactly like the human path)
    monkeypatch.setattr(foundry, "SUITE_SLOW_SECONDS", 1.0)
    _, out2, _ = _capture(lambda: foundry.timing_cli(cfg, as_json=True))
    d2 = json.loads(out2)
    assert d2["threshold"] == 1.0 and d2["count_slow"] == 1, \
        "the JSON path must read SUITE_SLOW_SECONDS at call time, like the human path"


# ==========================================================================
# Behavior 4 -- default / as_json=False is byte-identical to iter 18 (NOT JSON)
# ==========================================================================
def test_b4_default_equals_as_json_false_and_is_human_render(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 1, "10.00")
    _write_postrelease(cfg, 2, "30.00")
    before = _snapshot_tree(tmp_path)

    rc_default, out_default, _ = _capture(lambda: foundry.timing_cli(cfg))
    rc_false, out_false, _ = _capture(lambda: foundry.timing_cli(cfg, as_json=False))
    # default == explicit as_json=False, byte-for-byte (same code path)
    assert out_default == out_false, "default must equal as_json=False output byte-for-byte"
    assert rc_default == rc_false == 0
    # the human output is NOT a single JSON document (>=1 record) -> json.loads raises
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_default)
    # it IS the iter-18 human digest (regression guard on the timing surface)
    assert "demoprod" in out_default
    assert "iter-01" in out_default and "iter-02" in out_default
    assert "10.00s" in out_default and "30.00s" in out_default
    assert "measured 2/2" in out_default
    assert _snapshot_tree(tmp_path) == before, "human timing wrote a file (must be read-only)"


def test_b4_default_param_value_is_false():
    sig = inspect.signature(foundry.timing_cli)
    assert "as_json" in sig.parameters, "timing_cli must gain an as_json parameter"
    assert sig.parameters["as_json"].default is False, \
        "as_json default must be False (byte-identical-by-default guarantee)"


# ==========================================================================
# Behavior 5 -- foundry timing --config <cfg> [--json] end-to-end via main()
# ==========================================================================
def test_b5_main_json_flag_prints_payload_same_exit(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 1, "10.00")
    _write_postrelease(cfg, 2, "n/a")
    _write_postrelease(cfg, 3, "30.00")

    rc_json, out_json, _ = _capture(
        lambda: foundry.main(["timing", "--config", str(cfg_path), "--json"]))
    d = json.loads(out_json)                       # whole stdout is JSON
    rc_human, out_human, _ = _capture(
        lambda: foundry.main(["timing", "--config", str(cfg_path)]))
    # --json returns the SAME exit code as the human path
    assert rc_json == rc_human == d["exit_code"] == 0
    # payload equals the to_dict() (Behaviors 2-3)
    assert d == _reconstruct_summary_dict(d)
    assert [r["iteration"] for r in d["records"]] == [1, 2, 3]
    assert (d["total"], d["measured"]) == (3, 2)
    # no --json -> human digest (NOT json)
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_human)
    assert "demoprod" in out_human and "measured 2/3" in out_human


def test_b5_json_flag_is_store_true_default_off(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 1, "10.00")
    # default off: no --json -> human path (not parseable JSON)
    _, out_default, _ = _capture(
        lambda: foundry.main(["timing", "--config", str(cfg_path)]))
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_default)
    # flag on: --json -> parseable JSON document (a dict)
    _, out_flag, _ = _capture(
        lambda: foundry.main(["timing", "--config", str(cfg_path), "--json"]))
    assert isinstance(json.loads(out_flag), dict)


# ==========================================================================
# Behavior 6 -- empty / nothing-measured JSON is valid; non-json unchanged
# ==========================================================================
def test_b6_empty_state_dir_json(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    pathlib.Path(cfg.state).mkdir(parents=True, exist_ok=True)  # state/, no iter-* dirs
    before = _snapshot_tree(tmp_path)
    rc_json, out_json, _ = _capture(lambda: foundry.timing_cli(cfg, as_json=True))
    d = json.loads(out_json)                       # ONE valid JSON doc
    assert rc_json == 2 == d["exit_code"]
    assert d["total"] == 0 and d["measured"] == 0 and d["records"] == []
    assert d["count_slow"] == 0
    for k in ("min_seconds", "max_seconds", "avg_seconds", "last_seconds"):
        assert d[k] is None
    assert d == _reconstruct_summary_dict(d)
    # non-json empty-state human path unchanged (exit 2, 'no measured timings yet')
    rc_human, out_human, _ = _capture(lambda: foundry.timing_cli(cfg))
    assert rc_human == 2 and "no measured timings yet" in out_human
    assert _snapshot_tree(tmp_path) == before, "empty timing --json wrote a file"


def test_b6_absent_state_dir_json_is_read_only(tmp_path):
    # state/ does not exist at all -> the missing-dir guard -> valid empty JSON, exit 2.
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    shutil.rmtree(cfg.state, ignore_errors=True)
    assert not pathlib.Path(cfg.state).exists()
    rc, out, _ = _capture(lambda: foundry.timing_cli(cfg, as_json=True))
    d = json.loads(out)
    assert rc == 2 == d["exit_code"] and d["total"] == 0 and d["records"] == []
    assert not pathlib.Path(cfg.state).exists(), \
        "timing --json must NOT create the state dir (read-only guard)"


def test_b6_iterations_exist_but_none_measured_json(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 1, "n/a")
    _iter_dir(cfg, 2).mkdir(parents=True, exist_ok=True)  # dir, no postrelease.md
    _write_postrelease(cfg, 3, "n/a")
    rc, out, _ = _capture(lambda: foundry.timing_cli(cfg, as_json=True))
    d = json.loads(out)
    assert rc == 2 == d["exit_code"]
    assert d["total"] == 3 and d["measured"] == 0
    for k in ("min_seconds", "max_seconds", "avg_seconds", "last_seconds"):
        assert d[k] is None
    # records populated, every seconds is null
    assert [r["iteration"] for r in d["records"]] == [1, 2, 3]
    assert all(r["seconds"] is None for r in d["records"])
    assert d == _reconstruct_summary_dict(d)
    # non-json path unchanged: exit 2, degrades to the empty rollup
    rc_h, out_h, _ = _capture(lambda: foundry.timing_cli(cfg))
    assert rc_h == 2 and "no measured timings yet" in out_h


# ==========================================================================
# Behavior 7 -- --json honours --limit N (most-recent N, ascending; every field
#               computed over the limited set, identical selection to human path)
# ==========================================================================
def test_b7_json_limit_most_recent_n_ascending(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    for n in range(1, 6):
        _write_postrelease(cfg, n, f"{n * 10}.00")   # 10,20,30,40,50
    rc, out, _ = _capture(lambda: foundry.timing_cli(cfg, limit=2, as_json=True))
    d = json.loads(out)
    iters = [r["iteration"] for r in d["records"]]
    assert iters == [4, 5], f"most-recent 2, ascending (oldest-first): {iters}"
    # every field reflects only the limited window
    assert d["total"] == 2 and d["measured"] == 2
    assert (d["min_seconds"], d["max_seconds"], d["last_seconds"]) == (40.0, 50.0, 50.0)
    assert d["exit_code"] == rc == 0
    assert d == _reconstruct_summary_dict(d)
    # identical selection to the human path with the same limit
    _, out_human, _ = _capture(lambda: foundry.timing_cli(cfg, limit=2))
    assert iters == _iters_in_human(out_human)


def test_b7_main_json_limit_matches_human(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    for n in range(1, 6):
        _write_postrelease(cfg, n, f"{n * 10}.00")
    rc_json, out_json, _ = _capture(
        lambda: foundry.main(["timing", "--config", str(cfg_path), "--limit", "3", "--json"]))
    rc_human, out_human, _ = _capture(
        lambda: foundry.main(["timing", "--config", str(cfg_path), "--limit", "3"]))
    d = json.loads(out_json)
    assert [r["iteration"] for r in d["records"]] == [3, 4, 5] == _iters_in_human(out_human)
    assert d["total"] == 3 and rc_json == rc_human == d["exit_code"] == 0


def test_b7_json_nonpositive_limit_shows_all_like_human(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    for n in range(1, 4):
        _write_postrelease(cfg, n, f"{n * 10}.00")
    rc, out, _ = _capture(lambda: foundry.timing_cli(cfg, limit=0, as_json=True))
    d = json.loads(out)
    _, out_human, _ = _capture(lambda: foundry.timing_cli(cfg, limit=0))
    assert [r["iteration"] for r in d["records"]] == [1, 2, 3] == _iters_in_human(out_human), \
        "non-positive --limit must show ALL, identical selection to the human path"
    assert d["total"] == 3


# ==========================================================================
# Behavior 8 -- purely additive & off the control path (public introspection)
# ==========================================================================
def test_b8_both_modules_import():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b8_json_surface_present_and_callable():
    assert hasattr(foundry.TimingRecord, "to_dict") and callable(foundry.TimingRecord.to_dict)
    assert hasattr(foundry.TimingSummary, "to_dict") and callable(foundry.TimingSummary.to_dict)
    assert callable(foundry.timing_cli)
    assert callable(foundry.summarize_timing)
    # pre-existing control-flow entry points remain present + callable (regression)
    for fn in CONTROL_FLOW_FNS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"


def test_b8_new_surface_off_the_foundry_control_path():
    for fn_name in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in TIMING_SYMBOLS + JSON_SURFACE_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references {sym!r} (must stay off the control path)"
        # neither the 'timing' subcommand literal nor the '--json' flag may leak
        assert "timing" not in consts, \
            f"{fn_name} contains the 'timing' subcommand literal (off-control-path)"
        assert "--json" not in consts, \
            f"{fn_name} contains the '--json' flag literal (off-control-path)"


def test_b8_new_surface_absent_from_dispatcher():
    for sym in TIMING_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, consts = _module_names_consts(dispatcher)
    for sym in TIMING_SYMBOLS:
        assert sym not in names, f"dispatcher references {sym!r} (must stay untouched)"
    assert "timing" not in consts, "dispatcher references the 'timing' subcommand literal"
    assert "--json" not in consts, "dispatcher references the '--json' flag literal"


def test_b8_timing_cli_writes_nothing(tmp_path):
    # read-only guarantee across BOTH json and human paths on a populated digest
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 1, "10.00")
    _write_postrelease(cfg, 2, "n/a")
    before = _snapshot_tree(tmp_path)
    _capture(lambda: foundry.timing_cli(cfg, as_json=True))
    _capture(lambda: foundry.timing_cli(cfg))
    assert _snapshot_tree(tmp_path) == before, "timing_cli wrote to disk (must be read-only)"


def test_b8_sentinels_unchanged():
    # additive bite must not remove/rename the release sentinels (regression).
    _, consts = _module_names_consts(foundry)
    for sentinel in ("VERDICT:", "RESULT:", "ACTION:", "POSTRELEASE:"):
        assert any(sentinel in c for c in consts), \
            f"sentinel prefix {sentinel!r} vanished from foundry"


def test_b8_help_lists_timing_and_all_existing(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for sub in ("run", "once", "doctor", "learnings", "agents", "lint-spec",
                "prd", "gate-scope", "status", "history", "timing"):
        assert sub in out, f"subcommand {sub!r} missing from --help:\n{out}"
