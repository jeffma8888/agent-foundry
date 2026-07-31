"""Black-box behaviour tests for iter 18 -- ``foundry timing``, the read-only,
offline, on-demand PER-ITERATION SUITE WALL-TIME DIGEST surface, ALL additive in
foundry.py:

  * a PURE total ``parse_suite_seconds(text) -> float | None``
    (FIRST ``suite_seconds:`` key line -> float; ``n/a`` / absent / unparseable
    -> None; ``0.00`` -> 0.0; never raises for ANY string),
  * a FROZEN dataclass ``TimingRecord(iteration: int, seconds: float | None)``,
  * a FROZEN dataclass ``TimingSummary(product, records, threshold?)`` with
    ``total``/``measured``/``min_seconds``/``max_seconds``/``avg_seconds``/
    ``last_seconds``/``count_slow``/``exit_code`` + a ``render()`` string,
  * a PURE keyword-only ``summarize_timing(*, product, records, threshold)``,
  * a ``timing_cli(cfg, limit=None) -> int`` wired to a new argparse subcommand
    ``timing``, reusing the pre-existing ``iteration_numbers`` (iter 17) and the
    module global ``SUITE_SLOW_SECONDS`` (iter 13) as monkeypatchable seams.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-18 PM
spec's Expected Behaviors (1-12), the product README/roadmap, the ``tests/``
conventions (esp. tests/test_iter17_behavior.py), and the product's own
OBSERVABLE behaviour (via running it / public runtime introspection). The
implementation source (foundry.py / dispatcher.py internals), the engineer's and
reviewer's notes, and ``git diff`` were NOT read. Every check drives the PUBLIC
interface: the pure fns via ``foundry.parse_suite_seconds(...)`` /
``foundry.summarize_timing(...)``, the frozen dataclasses via
``foundry.TimingRecord(...)`` / ``foundry.TimingSummary(...)``, and the CLI via
``foundry.main(["timing", "--config", <cfg>])`` / ``foundry.timing_cli(cfg)``
against a TMP-``work_root`` config with real ``state/iter-NN/postrelease.md``
files (the real foundry repo/state is NEVER touched). The additivity /
off-control-path checks (Behavior 12) use only public RUNTIME introspection --
module attributes, ``--help`` output, and compiled name/const tables
(``__code__.co_names`` / ``co_consts``) -- NOT the source text. Fully offline &
deterministic: real temp files only; ZERO real subprocess / git / network / clock
(except the ``import``/``--help`` regression probes, which only import + print
usage).
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
# helpers  (mirror the suite's conventions, esp. tests/test_iter17_behavior.py)
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


def _write_postrelease(cfg, iteration, value, *, make_dir=True):
    """Create state/iter-NN/postrelease.md whose body carries a
    `- suite_seconds: <value>` line (the durable per-iteration timing signal),
    plus the trailing `POSTRELEASE:` sentinel (unrelated to timing but present in
    the real artifact). `value` is written verbatim (e.g. '12.34', 'n/a')."""
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
    """The single output line containing the exact `iter-NN` tag. Fails loudly if
    0 or >1 lines match -- keeps per-row assertions unambiguous."""
    rows = [ln for ln in out.splitlines() if tag in ln]
    assert len(rows) == 1, f"expected exactly one row containing {tag!r}, got {rows!r}\n{out}"
    return rows[0]


# The genuinely-NEW iter-18 symbols. `iteration_numbers` (iter 17) and
# `SUITE_SLOW_SECONDS` (iter 13) are PRE-EXISTING and legitimately live on the
# control path, so they are NOT in this off-path-absence set -- but they ARE the
# monkeypatchable seams asserted below.
NEW_SYMBOLS = (
    "parse_suite_seconds", "TimingRecord", "TimingSummary",
    "summarize_timing", "timing_cli",
)
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")


# ==========================================================================
# A. Pure  parse_suite_seconds(text) -> float | None        (Behaviors 1-4)
# ==========================================================================

# --- Behavior 1 -- FIRST matching line, bullet + whitespace tolerated -------
def test_b01_parses_measured_float():
    assert foundry.parse_suite_seconds("- suite_seconds: 12.34") == 12.34


def test_b01_bullet_optional():
    # a bare (no leading `- ` bullet) key line is still parsed.
    assert foundry.parse_suite_seconds("suite_seconds: 7.5") == 7.5


def test_b01_surrounding_whitespace_tolerated():
    assert foundry.parse_suite_seconds("-  suite_seconds:   12.34  ") == 12.34, \
        "leading/trailing whitespace and extra inner spaces must be tolerated"


def test_b01_first_matching_line_wins():
    body = "prose\n- suite_seconds: 3.00\n- suite_seconds: 99.00\nPOSTRELEASE: HEALTHY\n"
    assert foundry.parse_suite_seconds(body) == 3.00, \
        "the FIRST suite_seconds: line must win, not the last"


# --- Behavior 2 -- the `n/a` sentinel -> None ------------------------------
def test_b02_na_sentinel_is_none():
    assert foundry.parse_suite_seconds("- suite_seconds: n/a") is None


# --- Behavior 3 -- absent / unparseable / empty -> None, never raises ------
def test_b03_none_cases():
    cases = {
        "no key line": "just prose\nPOSTRELEASE: HEALTHY\n",
        "empty string": "",
        "whitespace only": "   \n\t\n  ",
        "unparseable value": "- suite_seconds: abc",
        "empty value": "- suite_seconds:",
        "empty value w/ trailing ws": "- suite_seconds:   ",
    }
    for label, text in cases.items():
        assert foundry.parse_suite_seconds(text) is None, \
            f"{label!r} must parse to None, got {foundry.parse_suite_seconds(text)!r}"


def test_b03_never_raises_for_any_string():
    weird = [
        "suite_seconds", "suite_seconds:", "- suite_seconds: 1.2.3",
        "- suite_seconds: n/a\n- suite_seconds: 5.0", "\x00\x01",
        "- suite_seconds: " + "9" * 500, "SUITE_SECONDS: 4.0",
        "\r\n- suite_seconds: 4.2\r\n", "un\u00efcode - suite_seconds: 4.2",
    ]
    for t in weird:
        try:
            foundry.parse_suite_seconds(t)  # must not raise
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"parse_suite_seconds raised on {t!r}: {e!r}")


# --- Behavior 4 -- zero is a REAL measured value (distinct from None) ------
def test_b04_zero_is_measured():
    r = foundry.parse_suite_seconds("- suite_seconds: 0.00")
    assert r == 0.0 and isinstance(r, float), \
        "0.00 is a real measured value (0.0), DISTINCT from None"
    assert r is not None


# ==========================================================================
# B. Digest counts -- summarize_timing / TimingSummary       (Behavior 5)
# ==========================================================================
def _spec_records():
    """The Behavior-6 concrete example: seconds [None,10,30,None,20], iters 1..5."""
    R = foundry.TimingRecord
    return [R(1, None), R(2, 10.0), R(3, 30.0), R(4, None), R(5, 20.0)]


def test_b05_total_and_measured_counts():
    s = foundry.summarize_timing(product="demo", records=_spec_records(), threshold=120.0)
    assert s.total == 5, "total == number of records"
    assert s.measured == 3, "measured == count of records whose seconds is not None"


# ==========================================================================
# C. Statistics over the measured subset                     (Behavior 6)
# ==========================================================================
def test_b06_stats_over_measured_only():
    s = foundry.summarize_timing(product="demo", records=_spec_records(), threshold=120.0)
    assert s.min_seconds == 10.0
    assert s.max_seconds == 30.0
    assert s.avg_seconds == 20.0, "arithmetic mean of the 3 measured (10+30+20)/3"
    assert s.last_seconds == 20.0, "seconds of the LAST measured record in the given order"


def test_b06_no_measured_all_stats_none():
    R = foundry.TimingRecord
    s = foundry.summarize_timing(product="demo", records=[R(1, None), R(2, None)],
                                 threshold=120.0)
    assert s.total == 2 and s.measured == 0
    assert s.min_seconds is None and s.max_seconds is None
    assert s.avg_seconds is None and s.last_seconds is None


def test_b06_last_measured_respects_given_order():
    # last_seconds must be the LAST *measured* record's seconds, even when a later
    # record is unmeasured (None) -- here iter-4 (None) must NOT overwrite last.
    R = foundry.TimingRecord
    s = foundry.summarize_timing(product="p", records=[R(1, 5.0), R(2, 9.0), R(3, None)],
                                 threshold=120.0)
    assert s.last_seconds == 9.0


# ==========================================================================
# D. Slow count -- STRICTLY greater than threshold           (Behavior 7)
# ==========================================================================
def test_b07_count_slow_strictly_greater():
    R = foundry.TimingRecord
    s = foundry.summarize_timing(
        product="p", records=[R(1, 10.0), R(2, 30.0), R(3, 20.0)], threshold=20.0)
    assert s.count_slow == 1, \
        "only 30.0 > 20.0; a record exactly AT the threshold (20.0) is NOT counted"


def test_b07_count_slow_ignores_unmeasured():
    R = foundry.TimingRecord
    s = foundry.summarize_timing(
        product="p", records=[R(1, None), R(2, 130.0), R(3, None)], threshold=120.0)
    assert s.count_slow == 1 and s.measured == 1


# ==========================================================================
# E. exit_code (informational) + frozen dataclasses          (Behavior 8)
# ==========================================================================
def test_b08_exit_code_two_iff_no_measured():
    R = foundry.TimingRecord
    s_measured = foundry.summarize_timing(product="p", records=_spec_records(), threshold=120.0)
    assert s_measured.exit_code == 0, "at least one measured -> exit 0"
    s_none = foundry.summarize_timing(product="p", records=[R(1, None)], threshold=120.0)
    assert s_none.exit_code == 2, "measured == 0 -> exit 2 (nothing to report)"
    s_empty = foundry.summarize_timing(product="p", records=[], threshold=120.0)
    assert s_empty.exit_code == 2 and s_empty.total == 0


def test_b08_slow_run_still_exits_zero():
    # A run FULL of slow-but-fixed timings is informational: never gates.
    R = foundry.TimingRecord
    s = foundry.summarize_timing(
        product="p", records=[R(1, 999.0), R(2, 888.0)], threshold=120.0)
    assert s.count_slow == 2 and s.exit_code == 0, \
        "timing NEVER gates on a slow suite (like history)"


def test_b08_timingrecord_frozen():
    R = foundry.TimingRecord
    r = R(3, 5.0)
    assert dataclasses.is_dataclass(r) and type(r).__name__ == "TimingRecord"
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.seconds = 9.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.iteration = 7
    # value equality
    assert R(3, 5.0) == R(3, 5.0)
    assert R(3, 5.0) != R(3, 6.0)


def test_b08_timingsummary_frozen_and_value_equality():
    s1 = foundry.summarize_timing(product="p", records=_spec_records(), threshold=120.0)
    assert dataclasses.is_dataclass(s1) and type(s1).__name__ == "TimingSummary"
    with pytest.raises(dataclasses.FrozenInstanceError):
        s1.product = "x"
    s2 = foundry.summarize_timing(product="p", records=_spec_records(), threshold=120.0)
    assert s1 == s2, "two summaries over equal inputs must compare equal (value equality)"


# ==========================================================================
# F. render() deterministic multi-line digest                (Behavior 9)
# ==========================================================================
def test_b09_render_measured_rows_and_rollup():
    recs = _spec_records()
    s = foundry.summarize_timing(product="demoprod", records=recs, threshold=20.0)
    out = s.render()
    assert "demoprod" in out, f"product name missing:\n{out}"
    # per-record rows: iter-NN (2-digit) + either NN.NNs or n/a, in stored order
    expect = {1: "n/a", 2: "10.00s", 3: "30.00s", 4: "n/a", 5: "20.00s"}
    positions = []
    for rec in recs:
        tag = f"iter-{rec.iteration:02d}"
        row = _row_for(out, tag)
        assert expect[rec.iteration] in row, \
            f"row for {tag} missing {expect[rec.iteration]!r}:\n{row}"
        positions.append(out.index(tag))
    assert positions == sorted(positions), "rows must appear in stored order"
    # rollup line: measured m/total + min/max/avg/last + slow(>thr)
    assert "measured 3/5" in out, f"rollup missing 'measured 3/5':\n{out}"
    for token in ("min", "max", "avg", "last"):
        assert token in out, f"rollup missing {token!r}:\n{out}"
    assert "10.00s" in out and "30.00s" in out and "20.00s" in out
    assert "slow (>20.00s): 1" in out, f"rollup slow-count wrong:\n{out}"


def test_b09_render_no_measured():
    R = foundry.TimingRecord
    s = foundry.summarize_timing(product="demoprod", records=[R(1, None), R(2, None)],
                                 threshold=120.0)
    out = s.render()
    assert "demoprod" in out
    assert "measured 0/2" in out, f"rollup must show 'measured 0/2':\n{out}"
    assert "no measured timings yet" in out, \
        f"measured==0 rollup must carry 'no measured timings yet':\n{out}"
    # each unmeasured row still shows n/a
    assert "n/a" in _row_for(out, "iter-01")
    assert "n/a" in _row_for(out, "iter-02")


def test_b09_render_two_decimal_wall_time_format():
    R = foundry.TimingRecord
    s = foundry.summarize_timing(product="p", records=[R(1, 5.0), R(2, 0.0)], threshold=120.0)
    out = s.render()
    assert "5.00s" in _row_for(out, "iter-01"), "wall-time formatted to two decimals + 's'"
    assert "0.00s" in _row_for(out, "iter-02"), "0.0 renders as 0.00s (measured), not n/a"


# ==========================================================================
# G. CLI  timing_cli / `foundry timing`                     (Behavior 10)
# ==========================================================================
def test_b10_reads_on_disk_ascending_read_only(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 1, "10.00")
    _write_postrelease(cfg, 2, "n/a")        # unmeasured sentinel
    _write_postrelease(cfg, 3, "30.00")
    _iter_dir(cfg, 4).mkdir(parents=True, exist_ok=True)  # iter-4 dir, NO postrelease.md
    _write_postrelease(cfg, 5, "20.00")
    before = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["timing", "--config", str(cfg_path)])
    assert rc == 0, f"a run with measured timings must exit 0, got {rc}\n{out}"
    for tag in ("iter-01", "iter-02", "iter-03", "iter-04", "iter-05"):
        assert tag in out, f"report missing {tag}:\n{out}"
    assert out.index("iter-01") < out.index("iter-05"), \
        f"ascending order: iter-01 must precede iter-05:\n{out}"
    assert "10.00s" in _row_for(out, "iter-01")
    assert "n/a" in _row_for(out, "iter-02"), "the n/a sentinel is unmeasured"
    assert "n/a" in _row_for(out, "iter-04"), "an absent postrelease.md -> n/a (guarded)"
    assert "30.00s" in _row_for(out, "iter-03")
    assert "measured 3/5" in out, f"rollup wrong:\n{out}"
    # read-only: nothing written anywhere under the temp tree
    assert _snapshot_tree(tmp_path) == before, "timing wrote a file (must be read-only)"


def test_b10_absent_state_dir_exit2_read_only(tmp_path):
    # state/ dir does not exist -> degrade to no iterations (never raise), exit 2,
    # and NEVER create the state dir. Drive the public fn directly (main eagerly
    # creates work/state, so exercise the guard on the bare cli fn).
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    shutil.rmtree(cfg.state, ignore_errors=True)
    assert not pathlib.Path(cfg.state).exists()
    rc, out = _run_fn(lambda: foundry.timing_cli(cfg))
    assert rc == 2, f"absent state dir must exit 2 (guarded), got {rc}\n{out}"
    assert "no measured timings yet" in out, f"report must degrade to empty:\n{out}"
    assert not pathlib.Path(cfg.state).exists(), \
        "timing must NOT create the state dir (read-only guard)"


def test_b10_empty_state_dir_exit2(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    pathlib.Path(cfg.state).mkdir(parents=True, exist_ok=True)  # exists, no iter-*
    before = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["timing", "--config", str(cfg_path)])
    assert rc == 2, f"no iterations must exit 2, got {rc}\n{out}"
    assert "no measured timings yet" in out
    assert _snapshot_tree(tmp_path) == before, "timing wrote a file (must be read-only)"


def test_b10_threshold_read_from_global_at_call_time(monkeypatch, tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 1, "50.00")
    # default threshold 120 -> 50 is NOT slow
    rc, out = _run_fn(lambda: foundry.timing_cli(cfg))
    assert rc == 0 and "slow (>120.00s): 0" in out, f"default threshold path:\n{out}"
    # patch the module global LOW -> read AT CALL TIME -> now 50 IS slow
    monkeypatch.setattr(foundry, "SUITE_SLOW_SECONDS", 1.0)
    rc2, out2 = _run_fn(lambda: foundry.timing_cli(cfg))
    assert rc2 == 0 and "slow (>1.00s): 1" in out2, \
        f"threshold must be read from SUITE_SLOW_SECONDS at call time:\n{out2}"


# ==========================================================================
# H. CLI  --limit N (most-recent N, ascending)              (Behavior 11)
# ==========================================================================
def test_b11_limit_shows_most_recent_n_ascending(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    for n in range(1, 6):
        _write_postrelease(cfg, n, f"{n * 10}.00")
    rc, out = _run_cli(["timing", "--config", str(cfg_path), "--limit", "2"])
    assert rc == 0, f"--limit over real timings exits 0, got {rc}\n{out}"
    assert "iter-04" in out and "iter-05" in out, f"most-recent 2 must be shown:\n{out}"
    for tag in ("iter-01", "iter-02", "iter-03"):
        assert tag not in out, f"{tag} must NOT be shown under --limit 2:\n{out}"
    assert out.index("iter-04") < out.index("iter-05"), \
        f"limit window must preserve ascending order:\n{out}"
    assert "measured 2/2" in out, f"rollup must be over the 2-row window:\n{out}"


def test_b11_no_limit_and_nonpositive_show_all(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    for n in range(1, 6):
        _write_postrelease(cfg, n, f"{n * 10}.00")
    # no --limit -> ALL 5
    rc, out = _run_cli(["timing", "--config", str(cfg_path)])
    assert rc == 0
    for n in range(1, 6):
        assert f"iter-0{n}" in out, f"no --limit must show all: missing iter-0{n}:\n{out}"
    assert "measured 5/5" in out, f"rollup over all 5:\n{out}"
    # --limit 0 (non-positive) -> ALL
    rc0, out0 = _run_cli(["timing", "--config", str(cfg_path), "--limit", "0"])
    assert rc0 == 0 and "iter-01" in out0 and "measured 5/5" in out0, \
        f"--limit 0 (non-positive) must show ALL:\n{out0}"
    # --limit -3 (negative) -> ALL
    rcm, outm = _run_cli(["timing", "--config", str(cfg_path), "--limit", "-3"])
    assert rcm == 0 and "iter-01" in outm and "measured 5/5" in outm, \
        f"negative --limit must show ALL:\n{outm}"


def test_b11_process_exit_status_equals_returned_code(tmp_path):
    # `uv run python foundry.py timing ...` process exit status == the CLI return.
    # empty state -> the cli returns 2 -> the process must exit 2. Drive the real
    # module as a subprocess (the only genuine subprocess in this file; offline).
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    pathlib.Path(cfg.state).mkdir(parents=True, exist_ok=True)  # exists, no iter-*
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run(
        [sys.executable, "foundry.py", "timing", "--config", str(cfg_path)],
        cwd=root, capture_output=True, text=True)
    assert r.returncode == 2, \
        f"process exit status must equal the cli return code (2 on empty):\n{r.stdout}\n{r.stderr}"
    assert "no measured timings yet" in (r.stdout + r.stderr)


# ==========================================================================
# I. Behavior 12 -- additive, isolated, off the control path, seams bite
# ==========================================================================
def test_b12_both_modules_import():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b12_new_surface_present_and_callable():
    assert callable(foundry.parse_suite_seconds)
    assert callable(foundry.summarize_timing)
    assert callable(foundry.timing_cli)
    assert hasattr(foundry, "TimingRecord")
    assert hasattr(foundry, "TimingSummary")
    # reused pre-existing seams still present:
    assert callable(foundry.iteration_numbers)
    assert isinstance(foundry.SUITE_SLOW_SECONDS, float)
    # pre-existing control-flow entry points remain present + callable (regression)
    for fn in CONTROL_FLOW_FNS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"


def test_b12_summarize_timing_is_keyword_only():
    with pytest.raises(TypeError):
        foundry.summarize_timing("p", _spec_records(), 120.0)  # positional -> TypeError


def test_b12_new_symbols_absent_from_foundry_control_flow():
    for fn_name in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references new symbol {sym!r} (must stay off the control path)"
        assert "timing" not in consts, \
            f"{fn_name} contains the 'timing' subcommand literal (must stay off the control path)"


def test_b12_new_symbols_absent_from_dispatcher():
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, consts = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in names, f"dispatcher references new symbol {sym!r}"
    assert "timing" not in consts, "dispatcher references the 'timing' subcommand literal"


def test_b12_help_lists_timing_plus_all_existing():
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0


def test_b12_help_output_lists_all_subcommands(capsys):
    with pytest.raises(SystemExit):
        foundry.main(["--help"])
    out = capsys.readouterr().out
    for sub in ("run", "once", "doctor", "learnings", "agents", "lint-spec",
                "prd", "gate-scope", "status", "history", "timing"):
        assert sub in out, f"subcommand {sub!r} missing from --help:\n{out}"


def test_b12_sentinels_unchanged():
    # Non-regression: the additive bite must not remove/rename the release
    # sentinels. Public compiled-const introspection (not source text).
    _, consts = _module_names_consts(foundry)
    for sentinel in ("VERDICT:", "RESULT:", "ACTION:", "POSTRELEASE:"):
        assert any(sentinel in c for c in consts), \
            f"sentinel prefix {sentinel!r} vanished from foundry"


def test_b12_seams_bite_inside_timing_cli(monkeypatch, tmp_path):
    # parse_suite_seconds / iteration_numbers / summarize_timing are each
    # referenced by BARE module name inside timing_cli, so setattr bites.
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 1, "50.00")

    # (a) patch parse_suite_seconds -> forced value flows into the digest
    monkeypatch.setattr(foundry, "parse_suite_seconds", lambda text: 999.0)
    rc, out = _run_fn(lambda: foundry.timing_cli(cfg))
    assert "999.00s" in out, f"patched parse_suite_seconds must bite:\n{out}"
    monkeypatch.undo()

    # (b) patch iteration_numbers -> controls which iterations appear
    monkeypatch.setattr(foundry, "iteration_numbers", lambda names: [7])
    rc, out = _run_fn(lambda: foundry.timing_cli(cfg))
    assert "iter-07" in out and "iter-01" not in out, \
        f"patched iteration_numbers must bite:\n{out}"
    monkeypatch.undo()

    # (c) patch summarize_timing -> its render()/exit_code are what the CLI emits
    class _Fake:
        exit_code = 7

        def render(self):
            return "FAKE-TIMING-RENDER"

    monkeypatch.setattr(foundry, "summarize_timing", lambda **kw: _Fake())
    rc, out = _run_fn(lambda: foundry.timing_cli(cfg))
    assert rc == 7 and "FAKE-TIMING-RENDER" in out, \
        f"patched summarize_timing must bite (render + exit_code):\n{out}"
