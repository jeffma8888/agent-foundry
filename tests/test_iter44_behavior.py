"""Black-box behaviour tests for iter 44 -- `foundry company-events` BITE 1 of 2
(the pure foundation): a NEW module-level, dormant, purely-additive,
output-preserving

    foundry.gather_events(cfg, kind=None, limit=None) -> EventsSummary

extracted from `events_cli`'s inline read->parse->filter->tail->summarize
gathering, which now DELEGATES to it. This completes the
`gather_status` / `gather_history` / `gather_timing` / `gather_weak_tests` /
`gather_events` symmetry so the coming company events roll-up (bite 2, next iter)
folds over ONE shared, tested gathering seam. A STRUCTURAL MIRROR of the shipped
iter-39 `gather_timing` / iter-42 `gather_weak_tests` bites.

NO `CompanyEvents`, NO `summarize_company_events`, NO `company-events`
subcommand, NO `--json` for it, NO new CLI/sentinel/config field this bite --
all deferred to bite 2.

ISOLATION CONTRACT (HONORED): this file was written SOLELY from the iter-44 PM
spec's Expected Behaviors (1-5), the product README/roadmap, the existing
`tests/` conventions (esp. tests/test_iter27_behavior.py -- the frozen
`EventsSummary` / `parse_events_jsonl` / `summarize_events` / `events_cli` seam --
and tests/test_iter39_behavior.py / tests/test_iter42_behavior.py -- the
`gather_*` mirrors), and the product's own OBSERVABLE runtime interface (public
functions, `--help` output, `inspect.signature`, compiled
`__code__.co_names`/`co_consts` tables, and RUNNING the CLI). The implementation
SOURCE text of foundry.py / dispatcher.py, the engineer's and reviewer's notes
for this iteration, and `git diff` were NOT read. Behavior-5 off-control-path
checks use only public RUNTIME introspection + a subprocess `import` probe, never
the source text.

Fully offline & deterministic: real temp files only (each event stream + config
lands under a per-test `tmp_path`); ZERO real git / agent subprocess / network /
sleeps (except the documented `import foundry, dispatcher` regression probe,
which touches nothing).
"""
import dataclasses
import inspect
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
# helpers / fixtures (mirror tests/test_iter27_behavior.py conventions)
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir; `repo`/`work_root` are TMP dirs so
    the real foundry repo is NEVER touched."""
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
    `records`   -> dicts, one JSON object per line (the valid stream).
    `raw_lines` -> a list of verbatim lines appended, OR a callable
                   (json_lines)->list producing the full ordered line list."""
    path = pathlib.Path(cfg.events_log)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r) for r in (records or [])]
    if callable(raw_lines):
        lines = raw_lines([json.dumps(r) for r in (records or [])])
    elif raw_lines:
        lines.extend(raw_lines)
    path.write_text("\n".join(lines) + ("\n" if lines else ""))
    return path


def _snapshot_tree(root):
    """Map {relative-path: bytes} for every file under root (no-write proof)."""
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*") if p.is_file()
    }


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


# the frozen iter-27 EventsSummary.to_dict() 9-key contract (reused, not changed)
EXPECTED_KEYS = [
    "product", "kind_filter", "total", "matched", "shown",
    "parse_errors", "exit_code", "kind_counts", "events",
]
NEW_SYMBOLS = ("gather_events",)
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")


# ==========================================================================
# Behavior 1 -- gather_events base mode (no filter, no limit); output-preserving
# ==========================================================================
def test_b1_base_mode_no_filter_no_limit(cfg):
    recs = [{"kind": "ship", "ts": "T0", "msg": "m0"},
            {"kind": "revert", "ts": "T1", "msg": "m1"},
            {"kind": "ship", "ts": "T2", "msg": "m2"}]
    _seed_events(cfg, recs)
    s = foundry.gather_events(cfg)
    assert type(s).__name__ == "EventsSummary"
    assert s.total == 3, f"total must count all parseable records, got {s.total}"
    assert s.matched == 3, f"no filter -> matched == total, got {s.matched}"
    assert s.shown == 3, f"no limit -> shown == matched, got {s.shown}"
    assert s.parse_errors == 0, f"clean stream -> 0 parse_errors, got {s.parse_errors}"
    assert s.kind_filter is None, f"kind_filter must be None, got {s.kind_filter!r}"
    # records equal to the 3 parsed dicts IN FILE ORDER
    assert list(s.records) == recs, f"records must be the parsed dicts in file order, got {list(s.records)!r}"


def test_b1_default_args_are_none(cfg):
    """kind=None, limit=None are the documented defaults (calling with no
    filter args is equivalent to explicit Nones)."""
    _seed_events(cfg, [{"kind": "ship", "ts": "T0"}])
    a = foundry.gather_events(cfg)
    b = foundry.gather_events(cfg, kind=None, limit=None)
    assert a == b, "default (kind=None, limit=None) must equal explicit Nones"


def test_b1_writes_nothing_to_disk(cfg):
    _seed_events(cfg, [{"kind": "ship", "ts": "T0"}])
    before = _snapshot_tree(pathlib.Path(cfg.events_log).parent)
    foundry.gather_events(cfg)
    after = _snapshot_tree(pathlib.Path(cfg.events_log).parent)
    assert after == before, "gather_events must write NOTHING to disk"


def test_b1_reads_events_log_via_read_text(cfg):
    """The stream is read from cfg.events_log (the iter-27 attribute) -- pointing
    a different content there changes the result, proving it is the source."""
    _seed_events(cfg, [{"kind": "ship", "ts": "A"}, {"kind": "ship", "ts": "B"}])
    assert foundry.gather_events(cfg).total == 2
    _seed_events(cfg, [{"kind": "ship", "ts": "C"}])
    assert foundry.gather_events(cfg).total == 1


def test_b1_delegates_to_parse_events_jsonl_by_bare_name(cfg, monkeypatch):
    """gather_events must call parse_events_jsonl by BARE module name, so a
    monkeypatch on foundry.parse_events_jsonl bites (records + parse_errors both
    flow through from the patched return)."""
    _seed_events(cfg, [{"kind": "ship", "ts": "REAL"}])
    monkeypatch.setattr(
        foundry, "parse_events_jsonl",
        lambda text: (({"kind": "FORCED", "ts": "Z"},), 9),
    )
    s = foundry.gather_events(cfg)
    assert s.total == 1 and s.matched == 1
    assert list(s.records) == [{"kind": "FORCED", "ts": "Z"}], \
        "monkeypatching foundry.parse_events_jsonl must control the records"
    assert s.parse_errors == 9, \
        "the parse_errors count from parse_events_jsonl must flow through"


def test_b1_delegates_to_summarize_events_by_bare_name(cfg, monkeypatch):
    """gather_events must RETURN summarize_events(...) called by BARE name with
    exactly the spec's keyword arguments."""
    recs = [{"kind": "ship", "ts": "T0"}, {"kind": "revert", "ts": "T1"}]
    _seed_events(cfg, recs)
    captured = {}
    sentinel = foundry.summarize_events(
        product="SENTINEL", records=[], total=0, matched=0, parse_errors=0, kind_filter=None)

    def fake_sum(*, product, records, total, matched, parse_errors, kind_filter):
        captured.update(product=product, records=tuple(records), total=total,
                        matched=matched, parse_errors=parse_errors, kind_filter=kind_filter)
        return sentinel

    monkeypatch.setattr(foundry, "summarize_events", fake_sum)
    got = foundry.gather_events(cfg)
    assert got is sentinel, "gather_events must RETURN summarize_events(...)"
    assert captured["product"] == cfg.name, "product must be cfg.name"
    assert captured["total"] == 2
    assert captured["matched"] == 2, "base mode -> matched == total"
    assert captured["kind_filter"] is None
    assert captured["parse_errors"] == 0
    assert list(captured["records"]) == recs


# ==========================================================================
# Behavior 2 -- kind filter FIRST, then limit tail (file order preserved)
# ==========================================================================
def test_b2_kind_filter_exact_match(cfg):
    recs = [{"kind": "ship", "ts": "T0"}, {"kind": "revert", "ts": "T1"},
            {"kind": "ship", "ts": "T2"}, {"kind": "backoff", "ts": "T3"}]
    _seed_events(cfg, recs)
    s = foundry.gather_events(cfg, kind="ship")
    assert s.total == 4, "total still counts ALL parseable records"
    assert s.matched == 2, "only the two ship records match"
    assert s.kind_filter == "ship"
    assert all(r.get("kind") == "ship" for r in s.records), "every stored record kind == 'ship'"
    assert [r["ts"] for r in s.records] == ["T0", "T2"]


def test_b2_kind_then_limit_composes_spec_example(cfg):
    """Spec Behavior-2 example: kinds ['ship','revert','ship','backoff'],
    gather_events(kind='ship', limit=1) -> total 4, matched 2, shown 1, the
    single stored record is the SECOND (later) ship."""
    recs = [{"kind": "ship", "ts": "A", "msg": "s0"},
            {"kind": "revert", "ts": "B", "msg": "r0"},
            {"kind": "ship", "ts": "C", "msg": "s1"},
            {"kind": "backoff", "ts": "D", "msg": "b0"}]
    _seed_events(cfg, recs)
    s = foundry.gather_events(cfg, kind="ship", limit=1)
    assert s.total == 4
    assert s.matched == 2
    assert s.shown == 1
    assert [r["msg"] for r in s.records] == ["s1"], \
        "filter FIRST (2 ships) then tail last 1 -> the later ship 's1'"


def test_b2_limit_tails_last_n_preserving_file_order(cfg):
    recs = [{"kind": "ship", "ts": f"T{i}", "msg": f"m{i}"} for i in range(5)]
    _seed_events(cfg, recs)
    s = foundry.gather_events(cfg, limit=2)
    assert s.matched == 5, "matched is the pre-limit count"
    assert s.shown == 2, "shown == min(limit, matched)"
    assert [r["msg"] for r in s.records] == ["m3", "m4"], \
        "the LAST 2 records, still in file order (oldest-first among shown)"


def test_b2_nonpositive_and_none_limit_keep_all_matched(cfg):
    recs = [{"kind": "ship", "ts": f"T{i}"} for i in range(3)]
    _seed_events(cfg, recs)
    for lim in (None, 0, -5):
        s = foundry.gather_events(cfg, limit=lim)
        assert s.shown == s.matched == 3, f"limit={lim!r} must keep all matched"


def test_b2_kind_matching_nothing_is_empty(cfg):
    _seed_events(cfg, [{"kind": "ship", "ts": "T0"}, {"kind": "revert", "ts": "T1"}])
    s = foundry.gather_events(cfg, kind="nope")
    assert s.total == 2 and s.matched == 0 and s.shown == 0
    assert s.records == ()
    assert s.kind_filter == "nope"


def test_b2_limit_larger_than_matched_shows_all(cfg):
    recs = [{"kind": "ship", "ts": f"T{i}"} for i in range(2)]
    _seed_events(cfg, recs)
    s = foundry.gather_events(cfg, limit=99)
    assert s.matched == 2 and s.shown == 2, "shown == min(N, matched)"


# ==========================================================================
# Behavior 3 -- absent/unreadable stream + malformed tolerance; never raises
# ==========================================================================
def test_b3_absent_file_degrades_never_raises(cfg):
    # events_log does not exist (work_root not even created)
    assert not pathlib.Path(cfg.events_log).exists()
    before = _snapshot_tree(pathlib.Path(cfg.events_log).parent)
    s = foundry.gather_events(cfg)  # must NOT raise
    assert s.total == 0 and s.matched == 0 and s.shown == 0
    assert s.parse_errors == 0
    assert s.records == ()
    assert s.exit_code == 2, "empty selection -> exit 2"
    assert not pathlib.Path(cfg.events_log).exists(), "must not create the file"
    assert _snapshot_tree(pathlib.Path(cfg.events_log).parent) == before


def test_b3_oserror_on_read_degrades_never_raises(cfg):
    # a DIRECTORY at the events_log path -> read_text() raises OSError
    p = pathlib.Path(cfg.events_log)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.mkdir()
    s = foundry.gather_events(cfg)  # must NOT raise
    assert s.total == 0 and s.matched == 0 and s.shown == 0
    assert s.parse_errors == 0 and s.records == ()
    assert s.exit_code == 2


def test_b3_malformed_lines_counted_not_stored(cfg):
    """A file mixing valid objects with junk (bad JSON, a JSON array, a scalar,
    and null) returns exactly the valid records IN ORDER + the correct
    parse_errors count; never raises. Blank/whitespace lines are skipped and are
    NOT parse errors."""
    lines = [
        json.dumps({"kind": "ship", "ts": "X"}),
        "",                    # blank -> skipped, not an error
        "   ",                 # whitespace-only -> skipped, not an error
        "this is not json",    # parse error
        "[1, 2, 3]",           # non-object (array) -> parse error
        "42",                  # non-object (scalar) -> parse error
        "null",                # non-object (null) -> parse error
        json.dumps({"kind": "revert", "ts": "Y"}),
    ]
    _seed_events(cfg, raw_lines=lambda _: lines)
    s = foundry.gather_events(cfg)
    assert [r["ts"] for r in s.records] == ["X", "Y"], \
        "only the valid objects are stored, in file order"
    assert s.total == 2 and s.matched == 2 and s.shown == 2
    assert s.parse_errors == 4, \
        f"exactly 4 malformed lines (junk/array/scalar/null); blanks skipped, got {s.parse_errors}"


def test_b3_parse_errors_never_change_exit_code(cfg):
    """A shown-nonempty selection exits 0 even with parse_errors > 0."""
    lines = [json.dumps({"kind": "ship", "ts": "A"}), "junk", "morejunk"]
    _seed_events(cfg, raw_lines=lambda _: lines)
    s = foundry.gather_events(cfg)
    assert s.shown == 1 and s.parse_errors == 2
    assert s.exit_code == 0, "parse_errors must NOT flip a non-empty selection to exit 2"


# ==========================================================================
# Behavior 4 -- events_cli delegates to gather_events; output-preserving
# ==========================================================================
def test_b4_events_cli_delegates_to_gather_events_by_bare_name(cfg, monkeypatch):
    _seed_events(cfg, [{"kind": "ship", "ts": "T0"}])
    called = {}
    sentinel = foundry.summarize_events(
        product="SENT", records=[{"kind": "ship", "ts": "Z"}],
        total=1, matched=1, parse_errors=0, kind_filter=None)

    def fake_gather(cfg_arg, kind=None, limit=None):
        called.update(cfg=cfg_arg, kind=kind, limit=limit)
        return sentinel

    monkeypatch.setattr(foundry, "gather_events", fake_gather)
    rc = foundry.events_cli(cfg, kind="ship", limit=5)
    assert called["cfg"] is cfg, "events_cli must pass cfg through"
    assert called["kind"] == "ship" and called["limit"] == 5, \
        "events_cli must forward kind/limit to gather_events"
    assert rc == sentinel.exit_code, "events_cli must return summary.exit_code"


def test_b4_human_output_byte_identical_to_gathered_summary_render(cfg):
    recs = [{"kind": "ship", "ts": "T0", "msg": "m0"},
            {"kind": "revert", "ts": "T1", "msg": "m1"},
            {"kind": "ship", "ts": "T2", "msg": "m2"}]
    _seed_events(cfg, recs)
    for kind, limit in [(None, None), ("ship", None), ("ship", 1), (None, 2)]:
        summary = foundry.gather_events(cfg, kind, limit)
        rc, out, _ = _capture(foundry.events_cli, cfg, kind=kind, limit=limit, as_json=False)
        assert rc == summary.exit_code, f"exit code diverged for kind={kind} limit={limit}"
        assert out == summary.render() + "\n", \
            f"human output must be print(render()) for kind={kind} limit={limit}:\n{out!r}"


def test_b4_json_output_is_gathered_summary_to_dict(cfg):
    recs = [{"kind": "ship", "ts": "T0", "msg": "s0"},
            {"kind": "revert", "ts": "T1", "msg": "r0"},
            {"kind": "ship", "ts": "T2", "msg": "s1"}]
    _seed_events(cfg, recs)
    summary = foundry.gather_events(cfg, kind="ship", limit=1)
    rc, out, _ = _capture(foundry.events_cli, cfg, kind="ship", limit=1, as_json=True)
    assert rc == summary.exit_code
    payload = json.loads(out)  # exactly one JSON document on stdout
    assert list(payload.keys()) == EXPECTED_KEYS, f"json must be to_dict(): {list(payload.keys())!r}"
    assert payload == summary.to_dict(), "--json must be json.dumps(gather_events(...).to_dict())"
    assert "\n" in out.strip(), "json output must be indent=2 pretty-printed"


def test_b4_end_to_end_via_main_selection_preserved(cfg, tmp_path):
    recs = [{"kind": "ship", "ts": "T0", "msg": "s0"},
            {"kind": "revert", "ts": "T1", "msg": "r0"},
            {"kind": "ship", "ts": "T2", "msg": "s1"},
            {"kind": "ship", "ts": "T3", "msg": "s2"}]
    _seed_events(cfg, recs)
    cfg_path = _write_cfg(tmp_path)  # same tmp_path -> same work_root/events_log as fixture
    rc, out, err = _run_main(["events", "--config", str(cfg_path), "--kind", "ship", "--limit", "1"])
    assert rc == 0, f"events via main should exit 0 for a non-empty selection:\n{out}{err}"
    assert "Traceback" not in (out + err)
    # kind-then-limit selection preserved end-to-end: only the last ship's msg shown
    assert "s2" in out and "s0" not in out and "s1" not in out, \
        f"kind='ship' limit=1 must show only the last ship 's2':\n{out}"
    assert "r0" not in out, "the revert row must be filtered out"


def test_b4_reused_pure_symbols_unchanged():
    """The frozen iter-27 EventsSummary core (9-key to_dict / render / kind_counts
    / exit_code) and the reused helpers are UNCHANGED by this extraction."""
    s = foundry.summarize_events(
        product="demoprod",
        records=[{"kind": "ship", "ts": "T0", "msg": "m0"},
                 {"kind": "ship", "ts": "T1", "msg": "m1"}],
        total=9, matched=2, parse_errors=4, kind_filter="ship")
    assert dataclasses.is_dataclass(s) and type(s).__name__ == "EventsSummary"
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.total = 99  # frozen
    d = s.to_dict()
    assert list(d.keys()) == EXPECTED_KEYS and len(d) == 9
    assert d["exit_code"] == s.exit_code == 0
    assert d["kind_counts"] == s.kind_counts == {"ship": 2}
    assert d["shown"] == s.shown == 2
    assert json.loads(json.dumps(d)) == d, "to_dict must survive a json round-trip"
    assert "foundry events -- demoprod" in s.render().splitlines()[0]
    # reused helpers still present + callable, signatures preserved
    for name in ("parse_events_jsonl", "summarize_events", "events_cli", "EventsSummary"):
        assert hasattr(foundry, name), f"reused symbol {name!r} vanished"
    assert list(inspect.signature(foundry.events_cli).parameters) == ["cfg", "kind", "limit", "as_json"]
    assert inspect.signature(foundry.events_cli).parameters["as_json"].default is False
    # summarize_events stays keyword-only (positional call rejected)
    with pytest.raises(TypeError):
        foundry.summarize_events("p", [], 0, 0, 0, None)


# ==========================================================================
# Behavior 5 -- dormant, off the control path, import-safe, no new surface
# ==========================================================================
def test_b5_both_modules_import_in_fresh_interpreter():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b5_new_surface_present_and_callable():
    assert callable(foundry.gather_events)
    sig = inspect.signature(foundry.gather_events)
    assert list(sig.parameters) == ["cfg", "kind", "limit"], f"unexpected signature: {sig}"
    assert sig.parameters["kind"].default is None
    assert sig.parameters["limit"].default is None
    # pre-existing control-flow entry points remain (regression)
    for fn in CONTROL_FLOW_FNS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"


def test_b5_gather_events_absent_from_foundry_control_flow():
    for fn_name in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references {sym!r} (must stay off the control path)"
        assert "company-events" not in consts, \
            f"{fn_name} embeds the 'company-events' literal (that is bite 2)"


def test_b5_gather_events_absent_from_dispatcher():
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, consts = _module_names_consts(dispatcher)
    assert "gather_events" not in names, "dispatcher references gather_events"
    assert "company-events" not in consts, "dispatcher references the 'company-events' literal"


def test_b5_only_caller_of_gather_events_is_events_cli():
    names, _ = _fn_names_consts(foundry.events_cli)
    assert "gather_events" in names, "events_cli is the sole caller of gather_events"


def test_b5_company_events_subcommand_present_after_bite2(capsys):
    """Bite 2 SHIPS the subcommand: --help still lists `events` + the existing
    company-* members AND now `company-events` too (this guard was flipped from
    its bite-1 "absent" assertion, mirroring how iter 40/43 flipped the iter
    39/42 guards -- the sanctioned, precedented scope-guard flip). The OTHER two
    iter-44 off-control-path guards (the `company-events` literal absent from
    CONTROL_FLOW_FNS + from dispatcher) stay UNTOUCHED and green."""
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for sub in ("events", "company-status", "company-history", "company-timing", "company-weak-tests"):
        assert sub in out, f"existing subcommand {sub!r} missing from --help:\n{out}"
    assert "company-events" in out, \
        "bite 2 must ADD the company-events subcommand"


def test_b5_running_events_writes_nothing(cfg, tmp_path):
    _seed_events(cfg, [{"kind": "ship", "ts": "T0"}])
    cfg_path = _write_cfg(tmp_path)
    before = _snapshot_tree(tmp_path)
    rc, out, err = _run_main(["events", "--config", str(cfg_path)])
    assert rc in (0, 2), f"events exit code should be 0/2, got {rc}\n{out}{err}"
    assert _snapshot_tree(tmp_path) == before, "events created/modified files (read-only violation)"


def test_b5_release_sentinels_unchanged():
    _, consts = _module_names_consts(foundry)
    for sentinel in ("VERDICT:", "RESULT:", "ACTION:", "POSTRELEASE:"):
        assert any(sentinel in c for c in consts), \
            f"sentinel prefix {sentinel!r} vanished from foundry"
    for status in ("shipped", "no-ship", "infra-fail"):
        assert status in consts, f"res['status'] value {status!r} vanished from foundry"
