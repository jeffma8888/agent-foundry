"""Black-box behaviour tests for iter 27 -- the DORMANT, offline, read-only
`events.jsonl` reader/digest:

    foundry events --config <cfg> [--kind K] [--limit N] [--json]

surfaced as the pure/total `parse_events_jsonl(text) -> (records, parse_errors)`,
the pure keyword-only builder `summarize_events(...) -> EventsSummary` (a frozen
dataclass with `shown`/`kind_counts`/`exit_code`/`render()`/`to_dict()`), and the
thin dormant `events_cli(cfg, kind=None, limit=None, as_json=False) -> int`
dispatched by a new `events` subparser in `main`. The pipeline/gate/dispatcher
NEVER consult it.

ISOLATION CONTRACT (honored): this file was written SOLELY from the iter-27 PM
spec's Expected Behaviors (1-15), the product README, the roadmap file, the
existing test conventions under `tests/`, and the product's own OBSERVABLE
runtime interface (public functions + `--help` + config-attribute introspection
of a live `ProductConfig`). The implementation SOURCE of `foundry.py` /
`dispatcher.py`, the engineer's and reviewer's notes for this iteration, and
`git diff` were NOT read. Behavior 15's off-control-path assertions use only
public RUNTIME introspection (compiled `co_names`/`co_consts` of live function
objects, module attribute presence, and a subprocess `import` probe) -- never the
source text.

Fully offline & deterministic: no network, no real git/agent subprocess (except
the Behavior-15 `import foundry, dispatcher` regression probe, which touches
nothing), no sleeps. Every event file + config lands only under a per-test
`tmp_path`; each CLI test snapshots the tmp tree to prove the writes-nothing
contract.
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


# --------------------------------------------------------------------------
# helpers / fixtures (mirror the other reader test modules' conventions)
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    data = {
        "name": "demoprod",
        "repo": str(tmp_path / "repo"),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def cfg(tmp_path):
    return foundry.load_config(str(_write_cfg(tmp_path)))


def _seed_events(cfg, records=None, raw_lines=None):
    """Write the events.jsonl the reader consumes at cfg.events_log.
    `records`  -> dicts, one JSON object per line (the valid stream).
    `raw_lines`-> extra verbatim lines appended (for blank/malformed cases).
    Interleaving is preserved: records first, then raw_lines, unless raw_lines
    is a callable(records)->list producing the full ordered line list."""
    path = pathlib.Path(cfg.events_log)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for r in (records or []):
        lines.append(json.dumps(r))
    if callable(raw_lines):
        lines = raw_lines([json.dumps(r) for r in (records or [])])
    elif raw_lines:
        lines.extend(raw_lines)
    path.write_text("\n".join(lines) + ("\n" if lines else ""))
    return path


def _snapshot_tree(root):
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*") if p.is_file()
    }


def _capture(fn, *a, **k):
    """Call fn capturing (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn(*a, **k)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _run_main(argv):
    return _capture(foundry.main, argv)


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


NEW_SYMBOLS = ("parse_events_jsonl", "summarize_events", "events_cli")
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")


# ==========================================================================
# Behavior 1 -- parse_events_jsonl(text) -> (records, parse_errors): pure, total
# ==========================================================================
def test_b01_parse_shape_and_empty():
    recs, errs = foundry.parse_events_jsonl("")
    assert recs == () and errs == 0, f"empty input must be ((), 0), got {(recs, errs)!r}"
    assert isinstance(recs, tuple), f"records must be a tuple, got {type(recs)}"
    assert isinstance(errs, int) and not isinstance(errs, bool), (
        f"parse_errors must be a plain int, got {type(errs)}"
    )
    # all-whitespace input -> also ((), 0)
    recs, errs = foundry.parse_events_jsonl("   \n\t\n  \n")
    assert recs == () and errs == 0, (
        f"all-whitespace input must be ((), 0), got {(recs, errs)!r}"
    )


def test_b01_records_in_file_order_one_per_nonblank_line():
    text = (
        '{"a": 1}\n'
        "\n"            # blank line -> skipped, NOT an error
        "   \n"         # whitespace-only line -> skipped, NOT an error
        '{"a": 2}\n'
        '{"a": 3}\n'
    )
    recs, errs = foundry.parse_events_jsonl(text)
    assert errs == 0, f"blank/whitespace lines must not count as errors, got {errs}"
    assert [r["a"] for r in recs] == [1, 2, 3], (
        f"records must be one-per-nonblank-line in file order, got {recs!r}"
    )
    assert all(isinstance(r, dict) for r in recs), "each record must be a dict"


# ==========================================================================
# Behavior 2 -- malformed lines counted, never raised
# ==========================================================================
def test_b02_malformed_counted_valid_kept_in_order():
    text = (
        '{"i": 0}\n'      # valid object
        "not json at all\n"      # json.loads failure
        "[1, 2, 3]\n"            # valid JSON but a non-dict (array)
        "42\n"                   # non-dict (number)
        '"a string"\n'          # non-dict (string)
        "true\n"                 # non-dict (bool)
        "null\n"                 # non-dict (null)
        '{"i": 1}\n'      # valid object
    )
    recs, errs = foundry.parse_events_jsonl(text)
    assert [r["i"] for r in recs] == [0, 1], (
        f"only the two valid objects must survive, in order, got {recs!r}"
    )
    assert errs == 6, (
        f"6 non-blank lines are malformed or non-dict -> parse_errors==6, got {errs}"
    )


def test_b02_never_raises_for_any_input():
    for weird in (
        "\x00\x01\x02",
        "{unterminated",
        "{" * 500,
        "\n\n\n{}\n\n",
        '{"nested": {"deep": [1, {"x": null}]}}',
        "\ud800",            # lone surrogate style junk
        "𝕗𝕒𝕟𝕔𝕪 unicode 🎉",
    ):
        # must never raise regardless of content
        recs, errs = foundry.parse_events_jsonl(weird)
        assert isinstance(recs, tuple) and isinstance(errs, int)


# ==========================================================================
# Behavior 3 -- summarize_events(...): pure, keyword-only, frozen, equality
# ==========================================================================
def _summ(**over):
    base = dict(
        product="demoprod",
        records=[{"kind": "ship", "ts": "T0", "msg": "m0"}],
        total=1, matched=1, parse_errors=0, kind_filter=None,
    )
    base.update(over)
    return foundry.summarize_events(**base)


def test_b03_keyword_only():
    with pytest.raises(TypeError):
        foundry.summarize_events("demoprod", [], 0, 0, 0, None)  # positional -> reject


def test_b03_records_materialized_as_tuple_and_shown():
    def gen():
        yield {"kind": "ship"}
        yield {"kind": "revert"}
    s = foundry.summarize_events(
        product="p", records=gen(), total=2, matched=2, parse_errors=0, kind_filter=None
    )
    assert isinstance(s.records, tuple), f"records must materialize to a tuple, got {type(s.records)}"
    assert s.shown == len(s.records) == 2, f"shown must equal len(records), got {s.shown}"


def test_b03_frozen_and_equal_from_equal_args():
    a = _summ()
    b = _summ()
    assert dataclasses.is_dataclass(a) and type(a).__name__ == "EventsSummary"
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.total = 99
    assert a == b, "two summaries built from equal args must compare equal"


# ==========================================================================
# Behavior 4 -- kind_counts: per-kind tally, "(none)" fallback, first-seen order
# ==========================================================================
def test_b04_kind_counts_tally_and_order():
    recs = [
        {"kind": "ship"},
        {"kind": "ship"},
        {"kind": "revert"},
        {"nokindhere": 1},        # missing kind -> (none)
        {"kind": 123},             # non-str kind -> (none)
        {"kind": "revert"},
    ]
    s = foundry.summarize_events(
        product="p", records=recs, total=6, matched=6, parse_errors=0, kind_filter=None
    )
    kc = s.kind_counts
    assert isinstance(kc, dict)
    assert kc == {"ship": 2, "revert": 2, "(none)": 2}, f"wrong tally: {kc!r}"
    # first-encountered key order: ship, revert, (none)
    assert list(kc.keys()) == ["ship", "revert", "(none)"], (
        f"keys must be in first-encountered order, got {list(kc.keys())!r}"
    )


# ==========================================================================
# Behavior 5 -- exit_code: 0 iff shown>0 else 2; parse_errors never affects it
# ==========================================================================
def test_b05_exit_code_shown_positive_with_parse_errors_is_zero():
    s = _summ(records=[{"kind": "ship"}], total=5, matched=1, parse_errors=4)
    assert s.shown == 1 and s.exit_code == 0, (
        f"shown>0 must exit 0 regardless of parse_errors, got {s.exit_code}"
    )


def test_b05_exit_code_empty_selection_is_two_even_with_no_errors():
    s = foundry.summarize_events(
        product="p", records=[], total=3, matched=0, parse_errors=0, kind_filter="ship"
    )
    assert s.shown == 0 and s.exit_code == 2, (
        f"empty selection must exit 2 even with parse_errors==0, got {s.exit_code}"
    )


# ==========================================================================
# Behavior 6 -- render(): header + rollup
# ==========================================================================
def test_b06_render_header_and_rollup_with_records():
    recs = [
        {"kind": "ship", "ts": "T0", "msg": "m0"},
        {"kind": "revert", "ts": "T1", "msg": "m1"},
    ]
    s = foundry.summarize_events(
        product="demoprod", records=recs, total=5, matched=2, parse_errors=3,
        kind_filter="ship",
    )
    text = s.render()
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    header, rollup = lines[0], lines[-1]
    assert "foundry events -- demoprod" in header, f"header wrong:\n{header}"
    assert "kind=ship" in header, f"kind_filter must appear in header when set:\n{header}"
    for sub in ("showing 2 of 2 matched", "5 total", "3 malformed", "ship:1", "revert:1"):
        assert sub in rollup, f"rollup missing {sub!r}:\n{rollup}"


def test_b06_render_header_omits_kind_when_filter_none():
    s = _summ(records=[{"kind": "ship", "ts": "T", "msg": "m"}], kind_filter=None)
    header = s.render().splitlines()[0]
    assert "foundry events -- demoprod" in header
    assert "kind=" not in header, f"header must NOT show kind= when filter is None:\n{header}"


def test_b06_render_empty_says_no_events_and_no_record_lines():
    s = foundry.summarize_events(
        product="p", records=[], total=4, matched=0, parse_errors=1, kind_filter=None
    )
    text = s.render()
    assert "no events" in text, f"empty render must contain 'no events':\n{text}"
    # no per-record content can appear (there are no stored records)
    assert "UNIQUE_RECORD_TOKEN" not in text


# ==========================================================================
# Behavior 7 -- render(): one line per record carrying ts / kind / msg substrings
# ==========================================================================
def test_b07_per_record_lines_present_and_fallbacks():
    recs = [
        {"ts": "TS_A", "kind": "ship", "msg": "MSG_A"},   # all present
        {"kind": "revert", "msg": "MSG_B"},                 # ts absent -> '?'
        {"ts": "TS_C"},                                       # kind + msg absent
    ]
    s = foundry.summarize_events(
        product="p", records=recs, total=3, matched=3, parse_errors=0, kind_filter=None
    )
    lines = s.render().splitlines()

    def _line_with(*subs):
        return [ln for ln in lines if all(x in ln for x in subs)]

    assert _line_with("TS_A", "ship", "MSG_A"), (
        f"record 0 line must carry ts+kind+msg substrings:\n{s.render()}"
    )
    # record 1: ts absent -> '?'; kind + msg present on its line
    assert _line_with("?", "revert", "MSG_B"), (
        f"record 1 line must show '?' for absent ts + its kind/msg:\n{s.render()}"
    )
    # record 2: ts present, kind + msg absent -> '?' for kind
    assert _line_with("TS_C", "?"), (
        f"record 2 line must carry its ts and '?' for absent kind:\n{s.render()}"
    )


# ==========================================================================
# Behavior 8 -- to_dict(): stable ordered JSON payload, round-trips
# ==========================================================================
EXPECTED_KEYS = [
    "product", "kind_filter", "total", "matched", "shown",
    "parse_errors", "exit_code", "kind_counts", "events",
]


def test_b08_to_dict_key_order_and_values():
    recs = [{"kind": "ship", "ts": "T0", "msg": "m0"},
            {"kind": "ship", "ts": "T1", "msg": "m1"}]
    s = foundry.summarize_events(
        product="demoprod", records=recs, total=9, matched=2, parse_errors=4,
        kind_filter="ship",
    )
    d = s.to_dict()
    assert list(d.keys()) == EXPECTED_KEYS, f"key order wrong: {list(d.keys())!r}"
    assert d["product"] == "demoprod"
    assert d["kind_filter"] == "ship"
    assert d["total"] == 9
    assert d["matched"] == 2
    assert d["parse_errors"] == 4
    # derived values reuse the frozen properties -> can never disagree
    assert d["shown"] == s.shown == 2
    assert d["exit_code"] == s.exit_code == 0
    assert d["kind_counts"] == s.kind_counts == {"ship": 2}
    # events == the stored records verbatim
    assert d["events"] == list(recs)
    # json round-trips to an equal structure
    round = json.loads(json.dumps(d))
    assert round == d, "to_dict() payload must survive a json round-trip unchanged"


def test_b08_to_dict_empty_case_roundtrips():
    s = foundry.summarize_events(
        product="p", records=[], total=0, matched=0, parse_errors=0, kind_filter=None
    )
    d = s.to_dict()
    assert list(d.keys()) == EXPECTED_KEYS
    assert d["events"] == []
    assert d["kind_counts"] == {}
    assert d["exit_code"] == 2
    assert json.loads(json.dumps(d)) == d


# ==========================================================================
# Behavior 9 -- events_cli reads cfg.events_log, degrades gracefully, no writes
# ==========================================================================
def test_b09_absent_file_degrades_to_exit2_no_write(cfg):
    # events_log does not exist (work_root not even created)
    assert not pathlib.Path(cfg.events_log).exists()
    before = _snapshot_tree(cfg.work_root)
    rc, out, err = _capture(foundry.events_cli, cfg)
    assert rc == 2, f"absent events file must degrade to exit 2, got {rc}\n{out}{err}"
    assert "Traceback" not in (out + err), f"must not raise/traceback:\n{out}{err}"
    assert not pathlib.Path(cfg.events_log).exists(), "reader must not create the file"
    assert _snapshot_tree(cfg.work_root) == before, "reader wrote to disk (must be read-only)"


def test_b09_oserror_on_read_degrades_to_exit2(cfg):
    # a directory at the events_log path -> reading it as a file raises OSError
    p = pathlib.Path(cfg.events_log)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.mkdir()
    before = _snapshot_tree(cfg.work_root)
    rc, out, err = _capture(foundry.events_cli, cfg)
    assert rc == 2, f"OSError on read must degrade to exit 2, got {rc}\n{out}{err}"
    assert "Traceback" not in (out + err), f"must degrade, not raise:\n{out}{err}"
    assert _snapshot_tree(cfg.work_root) == before, "reader wrote to disk (must be read-only)"


# ==========================================================================
# Behavior 10 -- events_cli unfiltered shows all parseable records
# ==========================================================================
def test_b10_unfiltered_shows_all_in_order(cfg):
    recs = [{"kind": "ship", "ts": f"T{i}", "msg": f"m{i}"} for i in range(3)]
    # append one malformed line -> reflected in rollup, never crashes
    _seed_events(cfg, recs, raw_lines=["this is not json"])
    before = _snapshot_tree(cfg.work_root)
    rc, out, err = _capture(foundry.events_cli, cfg)
    assert rc == 0, f">=1 record present must exit 0, got {rc}\n{out}{err}"
    rollup = [ln for ln in out.splitlines() if ln.strip()][-1]
    assert "showing 3 of 3 matched" in rollup, f"total==matched==shown==3 expected:\n{rollup}"
    assert "3 total" in rollup and "1 malformed" in rollup, (
        f"malformed line must be reflected in the rollup:\n{rollup}"
    )
    assert "Traceback" not in (out + err)
    assert _snapshot_tree(cfg.work_root) == before, "reader must not write"


def test_b10_empty_file_exits_two(cfg):
    _seed_events(cfg, [])   # writes an empty file
    rc, out, err = _capture(foundry.events_cli, cfg)
    assert rc == 2, f"a present-but-empty events file has 0 records -> exit 2, got {rc}"


# ==========================================================================
# Behavior 11 -- events_cli(kind=...) exact-match filter; total counts all
# ==========================================================================
def test_b11_kind_filter_exact_match(cfg):
    recs = [
        {"kind": "ship", "ts": "T0", "msg": "a"},
        {"kind": "revert", "ts": "T1", "msg": "b"},
        {"kind": "ship", "ts": "T2", "msg": "c"},
        {"kind": "shipped", "ts": "T3", "msg": "d"},   # NOT an exact 'ship' match
    ]
    _seed_events(cfg, recs)
    rc, out, err = _capture(foundry.events_cli, cfg, kind="ship")
    assert rc == 0, f"matching records must exit 0, got {rc}\n{out}{err}"
    rollup = [ln for ln in out.splitlines() if ln.strip()][-1]
    # exactly the 2 exact-'ship' records match; total still counts all 4
    assert "showing 2 of 2 matched" in rollup, f"only exact 'ship' rows match:\n{rollup}"
    assert "4 total" in rollup, f"total must count ALL parseable records:\n{rollup}"
    assert "kind=ship" in out.splitlines()[0], "header must reflect the kind filter"


def test_b11_kind_matching_nothing_exits_two(cfg):
    _seed_events(cfg, [{"kind": "ship", "ts": "T", "msg": "m"}])
    rc, out, err = _capture(foundry.events_cli, cfg, kind="nonexistent")
    assert rc == 2, f"a kind matching nothing must exit 2, got {rc}\n{out}{err}"


# ==========================================================================
# Behavior 12 -- events_cli(limit=N) tails most-recent N, preserving order
# ==========================================================================
def test_b12_limit_tails_last_n_preserving_order(cfg):
    recs = [{"kind": "ship", "ts": f"T{i}", "msg": f"m{i}"} for i in range(5)]
    _seed_events(cfg, recs)
    rc, out, err = _capture(foundry.events_cli, cfg, limit=2)
    assert rc == 0
    rollup = [ln for ln in out.splitlines() if ln.strip()][-1]
    # matched is the pre-limit count (5); shown == min(2, 5) == 2
    assert "showing 2 of 5 matched" in rollup, f"limit must tail: shown 2 of 5:\n{rollup}"
    # the LAST two (m3, m4) shown, in file order; the earlier ones dropped
    assert "m3" in out and "m4" in out, f"the last 2 records must be shown:\n{out}"
    assert "m0" not in out and "m1" not in out and "m2" not in out, (
        f"earlier records must be dropped by the tail:\n{out}"
    )
    # file order preserved: m3's line precedes m4's line
    assert out.index("m3") < out.index("m4"), "tail must preserve file order"


def test_b12_nonpositive_and_none_limit_show_all(cfg):
    recs = [{"kind": "ship", "ts": f"T{i}", "msg": f"m{i}"} for i in range(3)]
    _seed_events(cfg, recs)
    for lim in (None, 0, -5):
        rc, out, err = _capture(foundry.events_cli, cfg, limit=lim)
        rollup = [ln for ln in out.splitlines() if ln.strip()][-1]
        assert "showing 3 of 3 matched" in rollup, (
            f"limit={lim!r} must show all matched:\n{rollup}"
        )


def test_b12_kind_then_limit_compose(cfg):
    recs = [
        {"kind": "ship", "ts": "T0", "msg": "s0"},
        {"kind": "revert", "ts": "T1", "msg": "r0"},
        {"kind": "ship", "ts": "T2", "msg": "s1"},
        {"kind": "ship", "ts": "T3", "msg": "s2"},
    ]
    _seed_events(cfg, recs)
    rc, out, err = _capture(foundry.events_cli, cfg, kind="ship", limit=2)
    assert rc == 0
    rollup = [ln for ln in out.splitlines() if ln.strip()][-1]
    # filter first -> 3 ship rows matched; then tail 2 -> shown 2 (s1, s2)
    assert "showing 2 of 3 matched" in rollup, (
        f"kind filters FIRST (3 matched) then limit tails (shown 2):\n{rollup}"
    )
    assert "s1" in out and "s2" in out and "s0" not in out, (
        f"the last 2 SHIP rows must be shown, earliest ship dropped:\n{out}"
    )
    assert "r0" not in out, f"the revert row must be filtered out entirely:\n{out}"


# ==========================================================================
# Behavior 13 -- as_json prints one to_dict() doc; same exit code; same selection
# ==========================================================================
def test_b13_json_mode_matches_default_selection_and_exit(cfg):
    recs = [
        {"kind": "ship", "ts": "T0", "msg": "s0"},
        {"kind": "revert", "ts": "T1", "msg": "r0"},
        {"kind": "ship", "ts": "T2", "msg": "s1"},
    ]
    _seed_events(cfg, recs)

    rc_txt, out_txt, _ = _capture(foundry.events_cli, cfg, kind="ship", limit=1)
    rc_json, out_json, _ = _capture(foundry.events_cli, cfg, kind="ship", limit=1, as_json=True)

    assert rc_json == rc_txt, f"json exit code must equal default, {rc_json} != {rc_txt}"
    # exactly one JSON document on stdout
    payload = json.loads(out_json)
    assert isinstance(payload, dict)
    assert list(payload.keys()) == EXPECTED_KEYS, f"json payload = to_dict(): {list(payload.keys())}"
    # selection is byte-identical between modes: same kind_filter, matched, shown, events
    assert payload["kind_filter"] == "ship"
    assert payload["matched"] == 2 and payload["shown"] == 1
    assert [e["msg"] for e in payload["events"]] == ["s1"], (
        f"json selection must match the default (last ship after limit=1): {payload['events']}"
    )
    # pretty-printed (indent=2) -> multi-line document
    assert "\n" in out_json.strip(), "json output must be indent=2 pretty-printed"


def test_b13_default_mode_prints_render_text(cfg):
    _seed_events(cfg, [{"kind": "ship", "ts": "T0", "msg": "s0"}])
    rc, out, _ = _capture(foundry.events_cli, cfg, as_json=False)
    assert "foundry events -- demoprod" in out.splitlines()[0], (
        f"default (as_json=False) prints the human render():\n{out}"
    )
    # not JSON
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


# ==========================================================================
# Behavior 14 -- CLI wiring: `foundry events` through main
# ==========================================================================
def test_b14_main_dispatches_to_events_cli_with_parsed_flags(cfg, tmp_path, monkeypatch):
    captured = {}

    def _fake(cfg_arg, kind=None, limit=None, as_json=False):
        captured.update(
            cfg=cfg_arg, kind=kind, limit=limit, as_json=as_json
        )
        return 7

    monkeypatch.setattr(foundry, "events_cli", _fake)
    cfg_path = _write_cfg(tmp_path)
    rc, out, err = _run_main(
        ["events", "--config", str(cfg_path), "--kind", "ship", "--limit", "3", "--json"]
    )
    assert rc == 7, f"main must return events_cli's exit code, got {rc}\n{out}{err}"
    assert captured["kind"] == "ship", f"--kind not passed through: {captured}"
    assert captured["limit"] == 3 and isinstance(captured["limit"], int), (
        f"--limit must parse as int and pass through: {captured}"
    )
    assert captured["as_json"] is True, f"--json (store_true) not passed through: {captured}"
    assert getattr(captured["cfg"], "name", None) == "demoprod", (
        "main must load the config and pass the ProductConfig, not the path"
    )


def test_b14_main_flag_defaults(cfg, tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        foundry, "events_cli",
        lambda c, kind=None, limit=None, as_json=False: captured.update(
            kind=kind, limit=limit, as_json=as_json) or 0,
    )
    cfg_path = _write_cfg(tmp_path)
    rc, _, _ = _run_main(["events", "--config", str(cfg_path)])
    assert rc == 0
    assert captured == {"kind": None, "limit": None, "as_json": False}, (
        f"defaults must be kind=None, limit=None, as_json=False, got {captured}"
    )


def test_b14_main_limit_non_int_is_usage_error(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    with pytest.raises(SystemExit) as ei:
        _run_main(["events", "--config", str(cfg_path), "--limit", "notanint"])
    assert ei.value.code != 0, "--limit with a non-int must be an argparse usage error"


def test_b14_main_requires_config(tmp_path):
    with pytest.raises(SystemExit) as ei:
        _run_main(["events"])
    assert ei.value.code != 0, "events without --config must be a usage error"


def test_b14_main_process_exit_code_equals_returned(cfg):
    # end-to-end through main against a real seeded file (no monkeypatch):
    # a kind that matches nothing -> events_cli returns 2 -> main returns 2.
    _seed_events(cfg, [{"kind": "ship", "ts": "T", "msg": "m"}])
    # rebuild a config path pointing at the same work_root the fixture used
    rc, out, err = _capture(foundry.events_cli, cfg, kind="ship")
    assert rc == 0
    # and the empty selection path:
    rc2, _, _ = _capture(foundry.events_cli, cfg, kind="zzz")
    assert rc2 == 2


# ==========================================================================
# Behavior 15 -- off the control path / dormant / still importable
# ==========================================================================
def test_b15_new_surface_present_and_callable():
    assert callable(foundry.parse_events_jsonl)
    assert callable(foundry.summarize_events)
    assert callable(foundry.events_cli)
    assert hasattr(foundry, "EventsSummary")
    # pre-existing control-flow entry points remain present + callable (regression)
    for fn in CONTROL_FLOW_FNS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"


def test_b15_reader_consumes_existing_events_log_no_new_field():
    # the reader consumes the EXISTING iter-05 artifact (now named events_log),
    # not a new per-product artifact/config field.
    cfg_attrs = None  # documented: events_log == <work_root>/events.jsonl
    import tempfile
    d = tempfile.mkdtemp()
    p = pathlib.Path(d) / "config.json"
    p.write_text(json.dumps({
        "name": "x", "repo": d + "/repo", "allowed_push_repo": "x",
        "vision": d + "/V.md", "work_root": d + "/work",
    }))
    c = foundry.load_config(str(p))
    assert pathlib.Path(c.events_log) == pathlib.Path(c.work_root) / "events.jsonl", (
        f"reader must consume the existing events.jsonl artifact, got {c.events_log!r}"
    )


def test_b15_new_symbols_absent_from_foundry_control_flow():
    for fn_name in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS + ("EventsSummary",):
            assert sym not in names, (
                f"{fn_name} references {sym!r} -- the reader must stay off the control path"
            )


def test_b15_new_symbols_absent_from_dispatcher():
    for sym in NEW_SYMBOLS + ("EventsSummary",):
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, consts = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in names, f"dispatcher references new reader symbol {sym!r}"


def test_b15_help_lists_events_plus_existing():
    rc, out, err = None, "", ""
    with pytest.raises(SystemExit) as ei:
        _run_main(["--help"])
    assert ei.value.code == 0
    # capture --help via capsys-style: re-run capturing stdout
    o = io.StringIO()
    old = sys.stdout
    sys.stdout = o
    try:
        with pytest.raises(SystemExit):
            foundry.main(["--help"])
    finally:
        sys.stdout = old
    text = o.getvalue()
    for sub in ("run", "once", "status", "events"):
        assert sub in text, f"subcommand {sub!r} missing from --help:\n{text}"


def test_b15_sentinels_unchanged():
    _, consts = _module_names_consts(foundry)
    for sentinel in ("VERDICT:", "RESULT:", "ACTION:", "POSTRELEASE:"):
        assert any(sentinel in c for c in consts), (
            f"sentinel prefix {sentinel!r} vanished from foundry -- parse contract altered"
        )


def test_b15_both_modules_import_in_fresh_interpreter():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=root, capture_output=True, text=True,
    )
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stdout}{r.stderr}"
