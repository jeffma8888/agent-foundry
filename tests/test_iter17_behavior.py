"""Black-box behaviour tests for iter 17 -- the read-only, offline, one-command
MULTI-ITERATION SHIP LEDGER surface, ALL additive in foundry.py:

  * a PURE total `parse_ship_action(text) -> str | None`
    (last-non-empty-line `ACTION: PUSHED <sha>` -> "PUSHED" / `ACTION: REVERTED`
    -> "REVERTED"; else None; never raises),
  * a PURE total `iteration_numbers(names) -> list[int]`
    (sorted-ascending unique ints from exact `iter-<digits>` names),
  * a FROZEN dataclass `IterationRecord(iteration, action, postrelease)` with a
    `label` property,
  * a FROZEN dataclass `HistorySummary(product, records)` with
    `total`/`shipped`/`reverted`/`broken`/`exit_code` props + a `render()` string,
  * a PURE keyword-only `summarize_history(...) -> HistorySummary`,
  * a `history_cli(cfg, limit) -> int` wired to a new argparse subcommand
    `history`, reusing the iter-16 `parse_postrelease_verdict` verbatim.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-17 PM spec's
Expected Behaviors (1-12), the product README/roadmap, the `tests/` conventions,
and the product's own OBSERVABLE behaviour (via running it / public runtime
introspection). The implementation source (foundry.py / dispatcher.py internals),
the engineer's and reviewer's notes, and `git diff` were NOT read. Every check
drives the PUBLIC interface: the pure fns via `foundry.parse_ship_action(...)` /
`foundry.iteration_numbers(...)` / `foundry.summarize_history(...)`, the frozen
dataclasses via `foundry.IterationRecord(...)` / `foundry.HistorySummary(...)`, and
the CLI via `foundry.main(["history", "--config", <cfg>])` against a
TMP-`work_root` config with real `state/iter-NN/final.md` + optional
`postrelease.md` files (the real foundry repo/state is NEVER touched). The
additivity / off-control-path checks (Behavior 12) use only public RUNTIME
introspection -- module attributes, `--help` output, and compiled name/const
tables (`__code__.co_names` / `co_consts`) -- NOT the source text. Fully offline &
deterministic: real temp files only; ZERO real subprocess / git / network / clock
(except the `import`/`--help` regression probes, which only import + print usage).
"""
import dataclasses
import io
import pathlib
import re
import subprocess
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers  (mirror the suite's conventions, esp. tests/test_iter16_behavior.py)
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir. `repo`/`work_root` are TMP dirs so
    the real foundry repo/state is NEVER touched."""
    import json
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


def _iter_dir(cfg, iteration):
    return pathlib.Path(cfg.state) / f"iter-{iteration:02d}"


def _write_final(cfg, iteration, action_line, *, prose=True, trailing_blanks=True):
    """Create state/iter-NN/final.md whose LAST non-empty line is `action_line`
    (the `ACTION: ...` sentinel), optionally preceded by prose and followed by
    trailing blank lines."""
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    body = ""
    if prose:
        body += "final gate report for this iteration\n\n"
    body += action_line
    if trailing_blanks:
        body += "\n\n   \n\t\n"
    (d / "final.md").write_text(body)
    return d / "final.md"


def _write_postrelease(cfg, iteration, verdict, *, trailing_blanks=True):
    """Create state/iter-NN/postrelease.md whose LAST non-empty line is the
    `POSTRELEASE: <verdict>` sentinel (reused iter-16 sentinel)."""
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    body = f"post-release verification report\n\nPOSTRELEASE: {verdict}"
    if trailing_blanks:
        body += "\n\n   \n"
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
    """The single output line containing the exact `iter-NN` tag (the ledger row
    for that iteration). Fails loudly if 0 or >1 lines match -- keeps per-row
    assertions unambiguous."""
    rows = [ln for ln in out.splitlines() if tag in ln]
    assert len(rows) == 1, f"expected exactly one row containing {tag!r}, got {rows!r}\n{out}"
    return rows[0]


NEW_SYMBOLS = (
    "parse_ship_action", "iteration_numbers", "IterationRecord",
    "HistorySummary", "summarize_history", "history_cli",
)
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")


# ==========================================================================
# A. Pure  parse_ship_action(text) -> str | None            (Behaviors 1-2)
# ==========================================================================

# --- Behavior 1 -- recognized action on the last non-empty line ------------
def test_b01_pushed_returns_first_token_sha_ignored():
    assert foundry.parse_ship_action("ACTION: PUSHED 7bd0e02") == "PUSHED", \
        "PUSHED with a trailing sha must return the FIRST token 'PUSHED'"
    assert foundry.parse_ship_action("ACTION: REVERTED") == "REVERTED"


def test_b01_trailing_blank_lines_ignored_last_nonempty_wins():
    body = "final gate report\n\nACTION: PUSHED deadbeef\n\n   \n\t\n"
    assert foundry.parse_ship_action(body) == "PUSHED", \
        "trailing blank/whitespace lines ignored; last NON-empty line wins"
    body_r = "line1\nline2\nACTION: REVERTED\n"
    assert foundry.parse_ship_action(body_r) == "REVERTED"


def test_b01_surrounding_whitespace_tolerated():
    assert foundry.parse_ship_action("  ACTION:  REVERTED  ") == "REVERTED", \
        "leading/trailing whitespace on the sentinel line must be tolerated"
    assert foundry.parse_ship_action("\tACTION:   PUSHED   abc123\t\n") == "PUSHED"


# --- Behavior 2 -- no action -> None, never raises -------------------------
def test_b02_none_cases():
    cases = {
        "empty": "",
        "whitespace-only": "   \n\t\n  ",
        "no ACTION line": "just prose\nwith no sentinel at all\n",
        "unrecognized token": "ACTION: MAYBE",
        "sentinel-not-last (prose follows)":
            "ACTION: PUSHED abc1\nbut then more prose follows here\n",
    }
    for label, text in cases.items():
        assert foundry.parse_ship_action(text) is None, \
            f"{label!r} must parse to None, got {foundry.parse_ship_action(text)!r}"


def test_b02_never_raises_for_any_string():
    weird = [
        "ACTION:", "ACTION", "action: pushed", "ACTION: PUSHED",  # PUSHED w/o sha still ok
        "ACTION: PUSHED\n", "\x00\x01", "ACTION: PUSHED " + "X" * 500,
        "ACTION: PUSHED a\r\nACTION: REVERTED\r\n", "un\u00efcode ACTION: REVERTED",
    ]
    for t in weird:
        try:
            foundry.parse_ship_action(t)  # must not raise
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"parse_ship_action raised on {t!r}: {e!r}")


def test_b02_pushed_without_sha_is_still_pushed():
    # 'PUSHED' is the FIRST token after ACTION:; a sha is optional trailing detail.
    assert foundry.parse_ship_action("ACTION: PUSHED") == "PUSHED"


def test_b02_case_sensitive_lowercase_is_none():
    # recognized tokens are the upper-case PUSHED/REVERTED; a lower-case variant
    # is an unrecognized token -> None (most reasonable reading).
    assert foundry.parse_ship_action("ACTION: pushed abc") is None
    assert foundry.parse_ship_action("ACTION: reverted") is None


# ==========================================================================
# B. Pure  iteration_numbers(names) -> list[int]             (Behavior 3)
# ==========================================================================
def test_b03_spec_example_sorted_unique_filtered():
    names = ["iter-03", "iter-01", "iter-10", "foo", "iter-",
             "iter-xx", "iter-02", "iter-01"]
    assert foundry.iteration_numbers(names) == [1, 2, 3, 10], \
        "sorted-ascending unique ints from exact iter-<digits>; iter-10 sorts " \
        "numerically after iter-03; iter-/iter-xx/foo ignored; dup iter-01 de-duped"


def test_b03_empty_and_no_match_return_empty_list():
    assert foundry.iteration_numbers([]) == []
    assert foundry.iteration_numbers(["foo", "bar", "iter-", "iter-xx", ".git"]) == []


def test_b03_never_raises_and_is_list():
    for arg in ([], ["iter-99"], iter(["iter-05", "iter-05"]),
                ["ITER-01", "iter_01", "iter-01x", "iter-1a"]):
        try:
            r = foundry.iteration_numbers(arg)
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"iteration_numbers raised on {arg!r}: {e!r}")
        assert isinstance(r, list)
    # ITER-01 (wrong case), iter_01 (wrong sep), iter-01x / iter-1a (non-digit tail)
    # are all NOT the exact iter-<digits> form -> ignored.
    assert foundry.iteration_numbers(
        ["ITER-01", "iter_01", "iter-01x", "iter-1a"]) == []


def test_b03_accepts_any_iterable():
    assert foundry.iteration_numbers(iter(["iter-02", "iter-01", "iter-02"])) == [1, 2]


# ==========================================================================
# C. Frozen IterationRecord + label mapping                  (Behavior 4)
# ==========================================================================
def test_b04_frozen_record():
    r = foundry.IterationRecord(3, "PUSHED", "HEALTHY")
    assert dataclasses.is_dataclass(r) and type(r).__name__ == "IterationRecord"
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.action = "REVERTED"
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.iteration = 9


def test_b04_label_mapping_full_matrix():
    mk = foundry.IterationRecord
    assert mk(1, "REVERTED", None).label == "reverted"
    assert mk(2, "REVERTED", "HEALTHY").label == "reverted", \
        "REVERTED wins regardless of postrelease"
    assert mk(3, "PUSHED", "BROKEN").label == "shipped/BROKEN"
    assert mk(4, "PUSHED", "HEALTHY").label == "shipped/healthy"
    assert mk(5, "PUSHED", None).label == "shipped"
    assert mk(6, None, None).label == "no-ship"
    assert mk(7, None, "HEALTHY").label == "no-ship", \
        "no action -> no-ship regardless of postrelease"


# ==========================================================================
# D. Frozen HistorySummary + counts + exit_code + render     (Behaviors 5-6)
# ==========================================================================
def _records():
    R = foundry.IterationRecord
    return [
        R(1, "PUSHED", None),        # shipped
        R(2, "PUSHED", "HEALTHY"),   # shipped/healthy
        R(3, "PUSHED", "BROKEN"),    # shipped/BROKEN
        R(4, "REVERTED", None),      # reverted
        R(5, None, None),            # no-ship
    ]


def test_b05_frozen_summary_and_counts():
    s = foundry.HistorySummary("demoprod", tuple(_records()))
    assert dataclasses.is_dataclass(s) and type(s).__name__ == "HistorySummary"
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.product = "x"
    assert s.total == 5
    assert s.shipped == 3      # actions PUSHED
    assert s.reverted == 1     # actions REVERTED
    assert s.broken == 1       # only iter-03 has postrelease=="BROKEN"
    # confirm 'broken' counts ANY postrelease=="BROKEN" independent of action:
    R = foundry.IterationRecord
    s2 = foundry.HistorySummary("p", (R(1, "REVERTED", "BROKEN"),))
    assert s2.broken == 1 and s2.shipped == 0 and s2.reverted == 1


def test_b05_exit_code_zero_when_has_records_two_when_empty():
    s_has = foundry.HistorySummary("demoprod", tuple(_records()))
    assert s_has.exit_code == 0, "history with records is informational -> exit 0"
    s_empty = foundry.HistorySummary("demoprod", ())
    assert s_empty.exit_code == 2 and s_empty.total == 0, \
        "no iterations -> exit 2"
    # a past BROKEN never gates history (informational):
    R = foundry.IterationRecord
    s_broken = foundry.HistorySummary("p", (R(1, "PUSHED", "BROKEN"),))
    assert s_broken.exit_code == 0 and s_broken.broken == 1


def test_b06_render_contains_product_rows_and_rollup():
    recs = _records()
    s = foundry.HistorySummary("demoprod", tuple(recs))
    out = s.render()
    assert "demoprod" in out, f"product name missing:\n{out}"
    # each record's row: iter-NN + its label + post-release word, in stored order
    pr_word = {None: "unknown", "HEALTHY": "HEALTHY", "BROKEN": "BROKEN"}
    positions = []
    for rec in recs:
        tag = f"iter-{rec.iteration:02d}"
        row = _row_for(out, tag)
        assert rec.label in row, f"row for {tag} missing label {rec.label!r}:\n{row}"
        assert f"post-release: {pr_word[rec.postrelease]}" in row, \
            f"row for {tag} missing 'post-release: {pr_word[rec.postrelease]}':\n{row}"
        positions.append(out.index(tag))
    assert positions == sorted(positions), "rows must appear in stored order"
    # rollup line
    assert "5 iterations: 3 shipped, 1 reverted, 1 broken" in out, \
        f"rollup line wrong:\n{out}"


def test_b06_render_empty_history():
    s = foundry.HistorySummary("demoprod", ())
    out = s.render()
    assert "no iterations yet" in out, f"empty render must say 'no iterations yet':\n{out}"
    assert "0 iterations" in out, f"empty render must show '0 iterations':\n{out}"
    assert "demoprod" in out


# ==========================================================================
# E. Pure keyword-only summarize_history(...) -> HistorySummary  (Behavior 7)
# ==========================================================================
def test_b07_stores_records_as_tuple_equal_to_input_list():
    recs = _records()
    s = foundry.summarize_history(product="prodX", records=recs)
    assert isinstance(s, foundry.HistorySummary)
    assert s.product == "prodX"
    assert isinstance(s.records, tuple), "records must be stored as a tuple"
    assert list(s.records) == recs, "tuple must equal the input list element-wise"


def test_b07_is_keyword_only():
    with pytest.raises(TypeError):
        foundry.summarize_history("prodX", _records())  # positional -> TypeError


def test_b07_accepts_any_iterable_and_never_raises():
    try:
        s = foundry.summarize_history(product="", records=iter(_records()))
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"summarize_history raised on a generator of records: {e!r}")
    assert isinstance(s.records, tuple) and s.total == 5
    # empty iterable -> empty tuple, exit 2
    s0 = foundry.summarize_history(product="p", records=[])
    assert s0.records == () and s0.exit_code == 2


# ==========================================================================
# F. CLI  foundry history --config <cfg> [--limit N]        (Behaviors 8-11)
# ==========================================================================

# --- Behavior 8 -- mixed history, ascending -> exit 0, read-only -----------
def test_b08_mixed_history_ascending_exit0_read_only(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_final(cfg, 1, "ACTION: PUSHED abc1")            # shipped (no postrelease)
    _write_final(cfg, 2, "ACTION: PUSHED abc2")
    _write_postrelease(cfg, 2, "HEALTHY")                  # shipped/healthy
    _write_final(cfg, 3, "ACTION: REVERTED")               # reverted
    before = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["history", "--config", str(cfg_path)])
    assert rc == 0, f"a history with records must exit 0, got {rc}\n{out}"
    for tag in ("iter-01", "iter-02", "iter-03"):
        assert tag in out, f"report missing {tag}:\n{out}"
    assert out.index("iter-01") < out.index("iter-03"), \
        f"ascending order: iter-01 must precede iter-03:\n{out}"
    # per-row labels
    r1 = _row_for(out, "iter-01")
    assert "shipped" in r1 and "shipped/" not in r1, f"iter-01 must be bare 'shipped':\n{r1}"
    assert "post-release: unknown" in r1, f"iter-01 (no postrelease.md) must be 'unknown':\n{r1}"
    assert "shipped/healthy" in _row_for(out, "iter-02")
    assert "reverted" in _row_for(out, "iter-03")
    assert "3 iterations: 2 shipped, 1 reverted, 0 broken" in out, \
        f"rollup wrong:\n{out}"
    # read-only: nothing written anywhere under the temp tree
    assert _snapshot_tree(tmp_path) == before, "history wrote a file (must be read-only)"


# --- Behavior 9 -- --limit N shows the most-recent N -----------------------
def test_b09_limit_shows_most_recent_n(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    for n in range(1, 6):
        _write_final(cfg, n, f"ACTION: PUSHED sha{n}")
        _write_postrelease(cfg, n, "HEALTHY")
    rc, out = _run_cli(["history", "--config", str(cfg_path), "--limit", "2"])
    assert rc == 0, f"--limit over a real history exits 0, got {rc}\n{out}"
    assert "iter-04" in out and "iter-05" in out, f"most-recent 2 must be shown:\n{out}"
    for tag in ("iter-01", "iter-02", "iter-03"):
        assert tag not in out, f"{tag} must NOT be shown under --limit 2:\n{out}"
    assert "2 iterations:" in out, f"rollup must be over the 2-row window:\n{out}"
    assert "2 iterations: 2 shipped, 0 reverted, 0 broken" in out, f"rollup wrong:\n{out}"


def test_b09_no_limit_and_nonpositive_show_all(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    for n in range(1, 6):
        _write_final(cfg, n, f"ACTION: PUSHED sha{n}")
        _write_postrelease(cfg, n, "HEALTHY")
    # no --limit -> ALL 5
    rc, out = _run_cli(["history", "--config", str(cfg_path)])
    assert rc == 0
    for n in range(1, 6):
        assert f"iter-0{n}" in out, f"no --limit must show all: missing iter-0{n}:\n{out}"
    assert "5 iterations:" in out, f"rollup over all 5:\n{out}"
    # --limit 0 (non-positive) -> ALL
    rc0, out0 = _run_cli(["history", "--config", str(cfg_path), "--limit", "0"])
    assert rc0 == 0
    assert "iter-01" in out0 and "5 iterations:" in out0, \
        f"--limit 0 (non-positive) must show ALL:\n{out0}"


# --- Behavior 10 -- no iterations -> exit 2 --------------------------------
def test_b10_empty_state_dir_exit2(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    pathlib.Path(cfg.state).mkdir(parents=True, exist_ok=True)  # state/ exists, no iter-* dirs
    before = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["history", "--config", str(cfg_path)])
    assert rc == 2, f"no iterations must exit 2, got {rc}\n{out}"
    assert "no iterations yet" in out, f"report must say 'no iterations yet':\n{out}"
    assert _snapshot_tree(tmp_path) == before, "history wrote a file (must be read-only)"


def test_b10_absent_state_dir_exit2(tmp_path):
    # state/ dir does not exist at all -> the missing-dir GUARD -> exit 2.
    # (load_config / main eagerly create work/state, so drive the public
    # history_cli fn directly after deleting the dir to exercise the guard.)
    import shutil
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    shutil.rmtree(cfg.state, ignore_errors=True)
    assert not pathlib.Path(cfg.state).exists()
    out_io = io.StringIO()
    old = sys.stdout
    sys.stdout = out_io
    try:
        rc = foundry.history_cli(cfg)
    finally:
        sys.stdout = old
    out = out_io.getvalue()
    assert rc == 2, f"absent state dir must exit 2 (guarded), got {rc}\n{out}"
    assert "no iterations yet" in out, f"report must say 'no iterations yet':\n{out}"
    assert not pathlib.Path(cfg.state).exists(),          "history must NOT create the state dir (read-only guard)"


# --- Behavior 11 -- a BROKEN is counted but exit stays 0 -------------------
def test_b11_broken_counted_but_exit_stays_zero(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_final(cfg, 1, "ACTION: PUSHED s1")
    _write_postrelease(cfg, 1, "BROKEN")                   # shipped/BROKEN
    _write_final(cfg, 2, "ACTION: PUSHED s2")
    _write_postrelease(cfg, 2, "HEALTHY")                  # shipped/healthy
    rc, out = _run_cli(["history", "--config", str(cfg_path)])
    assert rc == 0, f"a PAST broken is informational, exit must stay 0, got {rc}\n{out}"
    r1 = _row_for(out, "iter-01")
    assert "post-release: BROKEN" in r1, f"iter-01 row must show BROKEN:\n{r1}"
    assert "1 broken" in out, f"rollup must count '1 broken':\n{out}"


# ==========================================================================
# G. Behavior 12 -- additive & off the control path (public introspection)
# ==========================================================================
def test_b12_both_modules_import():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b12_new_surface_present_and_callable():
    assert callable(foundry.parse_ship_action)
    assert callable(foundry.iteration_numbers)
    assert callable(foundry.summarize_history)
    assert callable(foundry.history_cli)
    assert hasattr(foundry, "IterationRecord")
    assert hasattr(foundry, "HistorySummary")
    # iter-16 helper reused verbatim, still present:
    assert callable(foundry.parse_postrelease_verdict)
    # pre-existing control-flow entry points remain present + callable (regression)
    for fn in CONTROL_FLOW_FNS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"


def test_b12_new_symbols_absent_from_foundry_control_flow():
    for fn_name in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references new symbol {sym!r} (must stay off the control path)"
        # the "history" subcommand string must not leak into the control path
        assert "history" not in consts, \
            f"{fn_name} contains the 'history' subcommand literal (must stay off the control path)"


def test_b12_new_symbols_absent_from_dispatcher():
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, consts = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in names, f"dispatcher references new symbol {sym!r}"
    assert "history" not in consts, "dispatcher references the 'history' subcommand literal"


def test_b12_help_lists_existing_plus_history():
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0


def test_b12_help_output_lists_all_subcommands(capsys):
    with pytest.raises(SystemExit):
        foundry.main(["--help"])
    out = capsys.readouterr().out
    for sub in ("run", "once", "doctor", "learnings", "agents",
                "lint-spec", "prd", "gate-scope", "status", "history"):
        assert sub in out, f"subcommand {sub!r} missing from --help:\n{out}"


def test_b12_sentinels_and_status_values_unchanged():
    # Non-regression: the additive bite must not remove/rename the release
    # sentinels or the ship-outcome status vocabulary. Public compiled-const
    # introspection (not source text).
    _, consts = _module_names_consts(foundry)
    for sentinel in ("VERDICT:", "RESULT:", "ACTION:", "POSTRELEASE:"):
        assert any(sentinel in c for c in consts), \
            f"sentinel prefix {sentinel!r} vanished from foundry"
    # AMBIGUITY / PM FEEDBACK: the spec lists res['status'] values
    # {shipped, no-ship, infra-fail, stopped}. The first three are directly
    # observable as compiled string consts; 'stopped' is NOT reachable as a bare
    # const via the public function-walk (it is produced elsewhere -- e.g. built
    # by the dispatcher / a variable), so we assert the three verifiable ones
    # (the same set iter-16's test proved) rather than a brittle bare-"stopped"
    # scan. The run-result-producing entry points are confirmed intact below.
    for status in ("shipped", "no-ship", "infra-fail"):
        assert status in consts, f"res['status'] value {status!r} vanished from foundry"
    for fn in ("run_iteration", "run_continuous"):
        assert callable(getattr(foundry, fn)), \
            f"foundry.{fn} missing (status-producer regression)"
