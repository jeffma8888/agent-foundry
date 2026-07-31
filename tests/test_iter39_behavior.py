"""Black-box behaviour tests for iter 39 -- `foundry company-timing` BITE 1 (the
pure foundation): the two dormant, purely-additive building blocks the eventual
company-wide timing roll-up needs, ALL additive in foundry.py:

  * a NEW module-level `gather_timing(cfg, limit=None) -> TimingSummary`
    (an OUTPUT-PRESERVING extraction of `timing_cli`'s inline gather, mirroring
    iter-30 `gather_status` / iter-31 `gather_history`): lists `cfg.state`'s dir
    names (GUARDED -- a missing/unreadable state dir yields no names and NEVER
    raises), derives iteration numbers via `iteration_numbers`, applies `limit`
    (positive int -> most-recent N ascending; None/non-positive -> all), reads
    each `state/iter-NN/postrelease.md` through `parse_suite_seconds` via
    `_read_sentinel`, and returns `summarize_timing(product=cfg.name,
    records=..., threshold=SUITE_SLOW_SECONDS)` -- reading `SUITE_SLOW_SECONDS`
    AT CALL TIME and every dependency by BARE module name (so a monkeypatch on
    any of them bites). Writes NOTHING to disk.
  * `timing_cli` now DELEGATES its gather to `gather_timing(cfg, limit)`, then
    prints `render()` (or `json.dumps(to_dict(), indent=2)` with `as_json=True`)
    and returns `summary.exit_code` -- byte-identical to iter-18/21.
  * a NEW pure `TimingSummary.measured_seconds` accessor: measured wall-times in
    record order as a `tuple[float, ...]`, unmeasured (`None`) dropped, a
    measured `0.0` KEPT; purely additive (render()/to_dict()/exit_code unchanged,
    to_dict() still EXACTLY 11 keys).

NO `CompanyTiming`, NO `company-timing` subcommand, NO `--json` for it, NO new
CLI this bite -- all deferred to bite 2.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-39 PM
spec's Expected Behaviors (1-4), the product README/roadmap, the `tests/`
conventions (esp. tests/test_iter18_behavior.py, test_iter21_behavior.py, and the
iter-30/31 `gather_*` seam tests), and the product's own OBSERVABLE behaviour
(via running it / public RUNTIME introspection -- module attrs, `--help` output,
compiled `__code__.co_names`/`co_consts` tables). The implementation SOURCE
(foundry.py / dispatcher.py source text), the engineer's & reviewer's notes, and
`git diff` were NOT read. Every check drives the PUBLIC interface: the pure fns
via `foundry.summarize_timing(...)` / `foundry.gather_timing(...)`, the accessor
via `TimingSummary.measured_seconds`, and the CLI via `foundry.timing_cli(...)` /
`foundry.main(["timing", ...])` against a TMP-`work_root` config with real
`state/iter-NN/postrelease.md` files (the real foundry repo/state is NEVER
touched). Fully offline & deterministic: real temp files only; ZERO real git /
network / clock (except the import + `--help` regression probes).
"""
import dataclasses
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
# helpers  (mirror the suite's conventions, esp. tests/test_iter18_behavior.py)
# --------------------------------------------------------------------------
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


def _run_fn(fn):
    """Drive a bare callable capturing (rc, stdout)."""
    out = io.StringIO()
    old = sys.stdout
    sys.stdout = out
    try:
        rc = fn()
    finally:
        sys.stdout = old
    return rc, out.getvalue()


def _iter_dir(cfg, iteration):
    return pathlib.Path(cfg.state) / f"iter-{iteration:02d}"


def _write_postrelease(cfg, iteration, value):
    """Create state/iter-NN/postrelease.md carrying a `- suite_seconds: <value>`
    line (the durable per-iteration timing signal). `value` is written verbatim
    (e.g. '12.34', 'n/a')."""
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    body = (
        "post-release verification report\n\n"
        f"- suite_seconds: {value}\n"
        "POSTRELEASE: HEALTHY\n"
    )
    (d / "postrelease.md").write_text(body)
    return d / "postrelease.md"


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


def _row_for(out, tag):
    rows = [ln for ln in out.splitlines() if tag in ln]
    assert len(rows) == 1, f"expected exactly one row containing {tag!r}, got {rows!r}\n{out}"
    return rows[0]


R = foundry.TimingRecord

# The genuinely-NEW iter-39 symbols. `iteration_numbers`, `parse_suite_seconds`,
# `summarize_timing`, `TimingRecord`, `SUITE_SLOW_SECONDS` are PRE-EXISTING and
# some legitimately live on the control path, so they are NOT in this new-set.
NEW_SYMBOLS = ("gather_timing", "measured_seconds")
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")


# ==========================================================================
# Behavior 1 -- gather_timing is an output-preserving extraction
# ==========================================================================
def test_b1_gather_timing_real_state_counts_and_ascending(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    _write_postrelease(cfg, 1, "10.00")
    _write_postrelease(cfg, 2, "n/a")                          # unmeasured sentinel
    _write_postrelease(cfg, 3, "30.00")
    _iter_dir(cfg, 4).mkdir(parents=True, exist_ok=True)       # dir, NO postrelease.md
    _write_postrelease(cfg, 5, "20.00")
    s = foundry.gather_timing(cfg)
    assert isinstance(s, foundry.TimingSummary)
    assert type(s).__name__ == "TimingSummary"
    assert s.product == cfg.name, "summary product == cfg.name"
    assert [r.iteration for r in s.records] == [1, 2, 3, 4, 5], "ASCENDING iter order"
    # iter-2 (n/a) and iter-4 (absent postrelease.md) are unmeasured
    assert s.total == 5 and s.measured == 3
    by_iter = {r.iteration: r.seconds for r in s.records}
    assert by_iter[1] == 10.0 and by_iter[3] == 30.0 and by_iter[5] == 20.0
    assert by_iter[2] is None, "the `n/a` sentinel -> unmeasured (None)"
    assert by_iter[4] is None, "an absent postrelease.md -> unmeasured (None), guarded"


def test_b1_gather_timing_equals_inline_timing_cli_output(tmp_path):
    """The load-bearing 'output-preserving' claim: what gather_timing returns is
    exactly what `foundry timing` renders -- same rows, rollup and exit code."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    _write_postrelease(cfg, 1, "10.00")
    _write_postrelease(cfg, 2, "n/a")
    _write_postrelease(cfg, 3, "30.00")
    s = foundry.gather_timing(cfg)
    rc, cli_out = _run_fn(lambda: foundry.timing_cli(cfg))
    assert rc == s.exit_code, "timing_cli exit code == gather_timing().exit_code"
    assert cli_out.rstrip("\n") == s.render().rstrip("\n"), \
        f"timing human output must equal gather_timing().render():\n{cli_out}"


def test_b1_gather_timing_missing_state_dir_never_raises_readonly(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    shutil.rmtree(cfg.state, ignore_errors=True)
    assert not pathlib.Path(cfg.state).exists()
    s = foundry.gather_timing(cfg)   # must NOT raise
    assert isinstance(s, foundry.TimingSummary) and s.total == 0
    assert s.measured == 0
    assert not pathlib.Path(cfg.state).exists(), \
        "gather_timing must not create the state dir (read-only guard)"


def test_b1_gather_timing_limit_most_recent_n_ascending(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    for n in range(1, 6):
        _write_postrelease(cfg, n, f"{n * 10}.00")
    assert [r.iteration for r in foundry.gather_timing(cfg, 2).records] == [4, 5], \
        "positive limit keeps the most-recent N, ascending"
    assert [r.iteration for r in foundry.gather_timing(cfg, limit=3).records] == [3, 4, 5]
    for lim in (None, 0, -2):
        assert foundry.gather_timing(cfg, lim).total == 5, \
            f"None / non-positive limit ({lim!r}) must keep ALL"


def test_b1_gather_timing_writes_nothing(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    for n in range(1, 4):
        _write_postrelease(cfg, n, f"{n * 10}.00")
    before = _snapshot_tree(tmp_path)
    foundry.gather_timing(cfg)
    foundry.gather_timing(cfg, 2)
    assert _snapshot_tree(tmp_path) == before, "gather_timing wrote to disk (must be read-only)"


def test_b1_gather_timing_reads_suite_slow_seconds_at_call_time(monkeypatch, tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    _write_postrelease(cfg, 1, "50.00")
    # default threshold 120 -> 50 is NOT slow
    assert foundry.gather_timing(cfg).count_slow == 0
    # patch the module global LOW -> read AT CALL time -> now 50 IS slow
    monkeypatch.setattr(foundry, "SUITE_SLOW_SECONDS", 1.0)
    s = foundry.gather_timing(cfg)
    assert s.count_slow == 1, "threshold must be read from SUITE_SLOW_SECONDS at call time"
    assert s.threshold == 1.0, "the patched threshold must flow into the summary"


def test_b1_gather_timing_delegates_to_summarize_timing_by_bare_name(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    for n in (2, 1, 3):  # written out of order to prove ASCENDING assembly
        _write_postrelease(cfg, n, f"{n * 10}.00")
    captured = {}
    sentinel = foundry.summarize_timing(product="SENTINEL", records=[], threshold=1.0)

    def fake_sum(*, product, records, threshold):
        captured["product"] = product
        captured["iters"] = [r.iteration for r in records]
        captured["threshold"] = threshold
        return sentinel

    monkeypatch.setattr(foundry, "summarize_timing", fake_sum)
    got = foundry.gather_timing(cfg)
    assert got is sentinel, "gather_timing must RETURN summarize_timing(...)"
    assert captured["product"] == cfg.name
    assert captured["iters"] == [1, 2, 3], "records passed in ascending iter order"
    assert captured["threshold"] == foundry.SUITE_SLOW_SECONDS


def test_b1_gather_timing_uses_parse_suite_seconds_seam(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    for n in (1, 2, 3):
        _write_postrelease(cfg, n, "n/a")   # real value would parse to None
    monkeypatch.setattr(foundry, "parse_suite_seconds", lambda text: 999.0)
    s = foundry.gather_timing(cfg)
    assert s.measured == 3 and s.measured_seconds == (999.0, 999.0, 999.0), \
        "monkeypatching foundry.parse_suite_seconds must bite gather_timing"


def test_b1_gather_timing_uses_iteration_numbers_seam(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    _write_postrelease(cfg, 1, "10.00")
    monkeypatch.setattr(foundry, "iteration_numbers", lambda names: [7])
    s = foundry.gather_timing(cfg)
    assert [r.iteration for r in s.records] == [7], \
        "monkeypatching foundry.iteration_numbers must control which iterations appear"


# ==========================================================================
# Behavior 2 -- timing_cli delegates to gather_timing, byte-identically
# ==========================================================================
def test_b2_timing_cli_human_uses_gather_timing_return(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    scripted = foundry.summarize_timing(
        product="scriptedprod",
        records=[R(1, 11.0), R(2, None), R(3, 33.0)],
        threshold=120.0,
    )
    monkeypatch.setattr(foundry, "gather_timing", lambda cfg, limit=None: scripted)
    rc, out = _run_fn(lambda: foundry.timing_cli(cfg))
    assert rc == scripted.exit_code, "timing_cli must return gather_timing().exit_code"
    assert out.rstrip("\n") == scripted.render().rstrip("\n"), \
        f"timing human output must equal gather_timing().render():\n{out}"


def test_b2_timing_cli_json_uses_gather_timing_return(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    scripted = foundry.summarize_timing(
        product="scriptedprod",
        records=[R(1, 11.0), R(2, None), R(3, 33.0)],
        threshold=120.0,
    )
    monkeypatch.setattr(foundry, "gather_timing", lambda cfg, limit=None: scripted)
    rc, out = _run_fn(lambda: foundry.timing_cli(cfg, as_json=True))
    assert rc == scripted.exit_code
    assert json.loads(out.strip()) == scripted.to_dict(), \
        "timing --json must be json of gather_timing().to_dict()"
    assert json.dumps(scripted.to_dict(), indent=2) in out, \
        "the JSON doc must be indent=2 pretty-printed (byte-identical to before)"


def test_b2_timing_cli_delegation_is_a_single_seam(tmp_path, monkeypatch):
    """A fully-scripted duck object proves timing_cli blindly consumes whatever
    gather_timing returns -- render() for human, exit_code for the return."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))

    class _Fake:
        exit_code = 7

        def render(self):
            return "FAKE-TIMING-RENDER"

        def to_dict(self):
            return {"scripted": True}

    monkeypatch.setattr(foundry, "gather_timing", lambda cfg, limit=None: _Fake())
    rc, out = _run_fn(lambda: foundry.timing_cli(cfg))
    assert rc == 7 and "FAKE-TIMING-RENDER" in out, \
        f"patched gather_timing must be the single gathering seam:\n{out}"
    rc2, out2 = _run_fn(lambda: foundry.timing_cli(cfg, as_json=True))
    assert rc2 == 7 and json.loads(out2.strip()) == {"scripted": True}


def test_b2_timing_cli_forwards_limit_to_gather_timing(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    seen = []
    scripted = foundry.summarize_timing(product="p", records=[], threshold=120.0)

    def fake_gather(cfg, limit=None):
        seen.append(limit)
        return scripted

    monkeypatch.setattr(foundry, "gather_timing", fake_gather)
    _run_cli(["timing", "--config", str(cfg_path), "--limit", "3"])
    assert seen == [3], f"--limit must flow through to gather_timing: {seen}"


def test_b2_timing_cli_output_preserved_end_to_end(tmp_path):
    """Regression: with real files, human + --json + --limit + exit code are the
    same as iter-18/21 (no observable drift from the extraction)."""
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 1, "10.00")
    _write_postrelease(cfg, 2, "n/a")
    _write_postrelease(cfg, 3, "30.00")
    before = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["timing", "--config", str(cfg_path)])
    assert rc == 0
    for tag in ("iter-01", "iter-02", "iter-03"):
        assert tag in out, f"missing {tag}:\n{out}"
    assert out.index("iter-01") < out.index("iter-03"), "ascending order preserved"
    assert "10.00s" in _row_for(out, "iter-01")
    assert "n/a" in _row_for(out, "iter-02")
    assert "30.00s" in _row_for(out, "iter-03")
    assert "measured 2/3" in out, f"rollup wrong:\n{out}"
    # --json path is a single JSON document
    rc_j, out_j = _run_cli(["timing", "--config", str(cfg_path), "--json"])
    assert rc_j == 0
    doc = json.loads(out_j.strip())
    assert doc["total"] == 3 and doc["measured"] == 2 and len(doc) == 11
    # read-only: neither the human nor the --json path wrote anything (assert
    # BEFORE creating any further fixtures under tmp_path)
    assert _snapshot_tree(tmp_path) == before, "timing wrote a file (must be read-only)"
    # empty state -> exit 2 unchanged (separate cfg, outside the read-only snapshot)
    cfg2_path = _write_cfg(tmp_path / "second")
    cfg2 = foundry.load_config(str(cfg2_path))
    pathlib.Path(cfg2.state).mkdir(parents=True, exist_ok=True)
    rc2, out2 = _run_cli(["timing", "--config", str(cfg2_path)])
    assert rc2 == 2 and "no measured timings yet" in out2


# ==========================================================================
# Behavior 3 -- TimingSummary.measured_seconds pure accessor
# ==========================================================================
def test_b3_measured_seconds_drops_none_keeps_order():
    s = foundry.summarize_timing(
        product="p", records=[R(1, 10.0), R(2, None), R(3, 30.0)], threshold=120.0)
    ms = s.measured_seconds
    assert ms == (10.0, 30.0), "unmeasured (None) records dropped, record order preserved"
    assert isinstance(ms, tuple), "measured_seconds must be a tuple"
    assert all(isinstance(x, float) for x in ms), "elements are floats"


def test_b3_measured_seconds_empty_when_nothing_measured():
    s = foundry.summarize_timing(
        product="p", records=[R(1, None), R(2, None)], threshold=120.0)
    assert s.measured_seconds == (), "empty tuple when nothing is measured"
    s_none = foundry.summarize_timing(product="p", records=[], threshold=120.0)
    assert s_none.measured_seconds == (), "empty tuple for zero records"


def test_b3_measured_seconds_keeps_zero_distinct_from_none():
    s = foundry.summarize_timing(
        product="p", records=[R(1, 0.0), R(2, None), R(3, 5.0)], threshold=120.0)
    assert s.measured_seconds == (0.0, 5.0), \
        "a measured 0.0 is KEPT (distinct from an unmeasured None)"


def test_b3_measured_seconds_matches_records_order_general():
    recs = [R(1, None), R(2, 10.0), R(3, 30.0), R(4, None), R(5, 20.0)]
    s = foundry.summarize_timing(product="demo", records=recs, threshold=120.0)
    assert s.measured_seconds == (10.0, 30.0, 20.0), "in stored record order"
    # consistency with the digest stats over the same measured subset
    assert min(s.measured_seconds) == s.min_seconds
    assert max(s.measured_seconds) == s.max_seconds
    assert s.measured_seconds[-1] == s.last_seconds
    assert len(s.measured_seconds) == s.measured


def test_b3_measured_seconds_is_purely_additive():
    """render(), to_dict() (still EXACTLY 11 keys, same order + values) and
    exit_code are UNCHANGED by the new accessor -- measured_seconds must NOT leak
    into the serialized surface."""
    recs = [R(1, 10.0), R(2, None), R(3, 30.0)]
    s = foundry.summarize_timing(product="demoprod", records=recs, threshold=20.0)
    d = s.to_dict()
    assert len(d) == 11, f"to_dict must still have EXACTLY 11 keys, got {list(d.keys())}"
    assert list(d.keys()) == [
        "product", "total", "measured", "min_seconds", "max_seconds",
        "avg_seconds", "last_seconds", "count_slow", "threshold", "exit_code",
        "records",
    ], f"to_dict key order changed: {list(d.keys())}"
    assert "measured_seconds" not in d, "measured_seconds must NOT leak into to_dict()"
    # value equality of the whole digest across two equal builds (accessor is pure)
    s2 = foundry.summarize_timing(product="demoprod", records=recs, threshold=20.0)
    assert s == s2 and s.to_dict() == s2.to_dict()
    assert s.render() == s2.render()
    assert s.exit_code == s2.exit_code
    # render still carries its established rollup markers (unchanged)
    out = s.render()
    assert "demoprod" in out and "measured 2/3" in out
    # calling the accessor does not mutate the (frozen) summary or its records
    _ = s.measured_seconds
    assert s.to_dict() == d


def test_b3_measured_seconds_returns_immutable_tuple():
    s = foundry.summarize_timing(product="p", records=[R(1, 10.0)], threshold=120.0)
    with pytest.raises((TypeError, AttributeError)):
        s.measured_seconds[0] = 99.0   # a tuple can't be item-assigned


# ==========================================================================
# Behavior 4 -- imports clean; off the control path; nothing else touched
# ==========================================================================
def test_b4_both_modules_import():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b4_new_surface_present_and_callable():
    assert callable(foundry.gather_timing)
    s = foundry.summarize_timing(product="p", records=[], threshold=120.0)
    assert hasattr(s, "measured_seconds"), "TimingSummary.measured_seconds must exist"
    # pre-existing seams + control-flow entry points remain (regression)
    for name in ("timing_cli", "summarize_timing", "iteration_numbers",
                 "parse_suite_seconds", "TimingRecord", "TimingSummary"):
        assert hasattr(foundry, name), f"pre-existing symbol {name!r} vanished"
    for fn in CONTROL_FLOW_FNS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"


def test_b4_new_symbols_absent_from_foundry_control_flow():
    for fn_name in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references new symbol {sym!r} (must stay off the control path)"
        assert "company-timing" not in consts, \
            f"{fn_name} contains the 'company-timing' subcommand literal (no new subcommand this bite)"


def test_b4_new_symbols_absent_from_dispatcher():
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, consts = _module_names_consts(dispatcher)
    assert "gather_timing" not in names, "dispatcher references gather_timing"
    assert "company-timing" not in consts, "dispatcher references the 'company-timing' literal"


def test_b4_company_timing_subcommand_present_after_bite2(capsys):
    # iter 39 (bite 1) shipped ONLY the foundation and this guard asserted the
    # `company-timing` subcommand was still absent ("deferred to bite 2"). iter 40
    # (bite 2) is that deferred bite: it legitimately ships the subcommand, so the
    # guard's retirement condition has now occurred. The regression half (every
    # pre-existing subcommand still present) is kept; the negative half is flipped
    # to assert the now-shipped `company-timing` subcommand appears in --help.
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    # every pre-existing subcommand (incl. the earlier company-* members) survives
    for sub in ("timing", "status", "history", "company-status", "company-history"):
        assert sub in out, f"existing subcommand {sub!r} missing from --help:\n{out}"
    # ... and bite 2 has now added the `company-timing` subcommand
    assert "company-timing" in out, \
        "bite 2 (iter 40) must add the company-timing subcommand"


def test_b4_release_sentinels_unchanged():
    _, consts = _module_names_consts(foundry)
    for sentinel in ("VERDICT:", "RESULT:", "ACTION:", "POSTRELEASE:"):
        assert any(sentinel in c for c in consts), \
            f"sentinel prefix {sentinel!r} vanished from foundry"
