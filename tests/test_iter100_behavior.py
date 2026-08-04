"""Black-box behaviour tests for iter 100 -- the read-only, offline, one-command
per-iteration GATE-OUTCOME LEDGER surface (bite 1 of 2, human CLI only; the
machine-readable `--json` is the pre-declared bite 2), ALL additive in foundry.py:

  * two PURE total parsers mirroring `parse_ship_action`:
      - `parse_review_verdict(text) -> str | None`
        (last-non-empty-line `VERDICT: APPROVE` -> "APPROVE" /
        `VERDICT: CHANGES_REQUIRED` -> "CHANGES_REQUIRED"; else None; never raises),
      - `parse_tester_result(text) -> str | None`
        (last-non-empty-line `RESULT: PASS` -> "PASS" / `RESULT: FAIL` -> "FAIL";
        else None; never raises),
  * a FROZEN dataclass `IterationOutcome(iteration, review, tester, action)`,
  * a FROZEN dataclass `OutcomesSummary(product, records)` with
    `total`/`approved`/`changes_required`/`tester_passed`/`tester_failed`/`exit_code`
    props + a `render()` string,
  * a PURE keyword-only `summarize_outcomes(*, product, records) -> OutcomesSummary`,
  * an I/O seam `gather_outcomes(cfg, limit=None) -> OutcomesSummary`,
  * an `outcomes_cli(cfg, limit=None) -> int` wired to a new argparse subcommand
    `outcomes`.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-100 PM
spec's Expected Behaviors (1-17), the product README/roadmap, the `tests/`
conventions (esp. tests/test_iter17_behavior.py, the `history` template this
iteration clones), and the product's own OBSERVABLE behaviour (via running it /
public runtime introspection). The implementation source (foundry.py /
dispatcher.py internals), the engineer's and reviewer's notes, and `git diff`
were NOT read. Every check drives the PUBLIC interface: the pure fns via
`foundry.parse_review_verdict(...)` / `foundry.parse_tester_result(...)` /
`foundry.summarize_outcomes(...)`, the frozen dataclasses via
`foundry.IterationOutcome(...)` / `foundry.OutcomesSummary(...)`, the seam via
`foundry.gather_outcomes(cfg)` against a TMP-`work_root` config with real
`state/iter-NN/{reviewer,tester,final}.md` files, and the CLI via
`foundry.main(["outcomes","--config",<cfg>])`. The real foundry repo/state is
NEVER touched. The dormancy checks (Behavior 16) use only public RUNTIME
introspection -- compiled name/const tables (`__code__.co_names` / `co_consts`)
and module attributes -- NOT the source text. Fully offline & deterministic:
real temp files only; ZERO real subprocess / git / network / clock (except the
`import` regression probe, which only imports the two modules).
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
# helpers  (mirror tests/test_iter17_behavior.py, the `history` template)
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir. `repo`/`work_root` are TMP dirs so
    the real foundry repo/state is NEVER touched. mkdir the tmp_path up front so a
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


def _write_outcome(cfg, iteration, *, review=None, tester=None, action=None,
                   trailing_blanks=True):
    """Create state/iter-NN/{reviewer,tester,final}.md whose LAST non-empty line
    is the role-owned sentinel. Any of review/tester/action left None leaves that
    artifact ABSENT (so gather_outcomes reads None for that field)."""
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    tail = "\n\n   \n\t\n" if trailing_blanks else ""
    if review is not None:
        (d / "reviewer.md").write_text(f"review notes for this iteration\n\nVERDICT: {review}{tail}")
    if tester is not None:
        (d / "tester.md").write_text(f"test report for this iteration\n\nRESULT: {tester}{tail}")
    if action is not None:
        (d / "final.md").write_text(f"final gate report\n\nACTION: {action}{tail}")
    return d


def _row_for(out, tag):
    """The single output line containing the exact `iter-NN` tag (the ledger row
    for that iteration). Fails loudly if 0 or >1 lines match."""
    rows = [ln for ln in out.splitlines() if tag in ln]
    assert len(rows) == 1, f"expected exactly one row containing {tag!r}, got {rows!r}\n{out}"
    return rows[0]


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


NEW_SYMBOLS = (
    "parse_review_verdict", "parse_tester_result", "IterationOutcome",
    "OutcomesSummary", "summarize_outcomes", "gather_outcomes", "outcomes_cli",
)
ORCHESTRATORS = (
    "build_prompt", "run_stage", "run_iteration", "run_continuous",
    "run_execution_plan",
)


def _mixed_records():
    """A record set exercising every field value + None in each slot."""
    IO = foundry.IterationOutcome
    return [
        IO(1, "APPROVE", "PASS", "PUSHED"),
        IO(2, "CHANGES_REQUIRED", "FAIL", "REVERTED"),
        IO(3, "APPROVE", "PASS", None),          # ship unknown
        IO(10, None, None, "PUSHED"),            # review/tester unknown
    ]


# ==========================================================================
# A. Pure parse_review_verdict(text) -> str | None          (Behaviors 1-2)
# ==========================================================================
def test_b01_review_recognized_last_nonempty_line():
    assert foundry.parse_review_verdict("VERDICT: APPROVE") == "APPROVE"
    assert foundry.parse_review_verdict("VERDICT: CHANGES_REQUIRED") == "CHANGES_REQUIRED"


def test_b01_review_trailing_blanks_ignored_last_nonempty_wins():
    body = "review notes\n\nVERDICT: APPROVE\n\n   \n\t\n"
    assert foundry.parse_review_verdict(body) == "APPROVE", \
        "trailing blank/whitespace lines ignored; last NON-empty line wins"
    body_c = "line1\nline2\nVERDICT: CHANGES_REQUIRED\n"
    assert foundry.parse_review_verdict(body_c) == "CHANGES_REQUIRED"


def test_b01_review_surrounding_whitespace_tolerated():
    assert foundry.parse_review_verdict("  VERDICT:  APPROVE  ") == "APPROVE", \
        "leading/trailing whitespace on the sentinel line must be tolerated"
    assert foundry.parse_review_verdict("\tVERDICT:   CHANGES_REQUIRED\t\n") == "CHANGES_REQUIRED"


def test_b02_review_none_cases():
    cases = {
        "empty": "",
        "whitespace-only": "   \n\t\n  ",
        "no VERDICT line": "just prose\nwith no sentinel at all\n",
        "unrecognized token": "VERDICT: MAYBE",
        "bare VERDICT": "VERDICT:",
        "sentinel-not-last (prose follows)":
            "VERDICT: APPROVE\nbut then more prose follows here\n",
    }
    for label, text in cases.items():
        assert foundry.parse_review_verdict(text) is None, \
            f"{label!r} must parse to None, got {foundry.parse_review_verdict(text)!r}"


def test_b02_review_case_sensitive_lowercase_is_none():
    # recognized tokens are the upper-case sentinel values; a lower-case variant
    # is an unrecognized token -> None (most reasonable reading).
    assert foundry.parse_review_verdict("VERDICT: approve") is None
    assert foundry.parse_review_verdict("VERDICT: changes_required") is None


def test_b02_review_multitoken_is_none_AMBIGUITY_NOTE():
    # SPEC AMBIGUITY (PM feedback): behaviors 1-2 define the surrounding-whitespace
    # tolerance and the recognized/unrecognized tokens, but do NOT explicitly
    # define a trailing extra word (e.g. `VERDICT: APPROVE extra`). The most
    # reasonable reading, consistent with the whitelisted-token semantics + the
    # surrounding-whitespace-ONLY tolerance example (`  VERDICT:  APPROVE  `), is
    # that the whole stripped remainder must equal a whitelist token, so a trailing
    # word makes it unrecognized -> None. Asserted as the most reasonable reading.
    assert foundry.parse_review_verdict("VERDICT: APPROVE extra") is None


def test_b02_review_never_raises_for_any_string():
    weird = [
        "VERDICT:", "VERDICT", "verdict: approve", "VERDICT: APPROVE",
        "VERDICT: APPROVE\n", "\x00\x01", "VERDICT: APPROVE " + "X" * 500,
        "VERDICT: APPROVE\r\nVERDICT: CHANGES_REQUIRED\r\n",
        "un\u00efcode VERDICT: CHANGES_REQUIRED", "\n\n\n", "VERDICT:APPROVE",
    ]
    for t in weird:
        try:
            r = foundry.parse_review_verdict(t)
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"parse_review_verdict raised on {t!r}: {e!r}")
        assert r in (None, "APPROVE", "CHANGES_REQUIRED")


# ==========================================================================
# B. Pure parse_tester_result(text) -> str | None           (Behaviors 3-4)
# ==========================================================================
def test_b03_tester_recognized_last_nonempty_line():
    assert foundry.parse_tester_result("RESULT: PASS") == "PASS"
    assert foundry.parse_tester_result("RESULT: FAIL") == "FAIL"


def test_b03_tester_trailing_blanks_ignored_last_nonempty_wins():
    body = "test report\n\nRESULT: PASS\n\n   \n\t\n"
    assert foundry.parse_tester_result(body) == "PASS", \
        "trailing blank/whitespace lines ignored; last NON-empty line wins"
    assert foundry.parse_tester_result("a\nb\nRESULT: FAIL\n") == "FAIL"


def test_b03_tester_surrounding_whitespace_tolerated():
    assert foundry.parse_tester_result("  RESULT:  PASS  ") == "PASS", \
        "leading/trailing whitespace on the sentinel line must be tolerated"
    assert foundry.parse_tester_result("\tRESULT:   FAIL\t\n") == "FAIL"


def test_b04_tester_none_cases():
    cases = {
        "empty": "",
        "whitespace-only": "   \n\t\n  ",
        "no RESULT line": "just prose\nno sentinel here\n",
        "unrecognized token": "RESULT: MAYBE",
        "bare RESULT": "RESULT:",
        "sentinel-not-last (prose follows)":
            "RESULT: PASS\nbut then more prose follows\n",
    }
    for label, text in cases.items():
        assert foundry.parse_tester_result(text) is None, \
            f"{label!r} must parse to None, got {foundry.parse_tester_result(text)!r}"


def test_b04_tester_case_sensitive_lowercase_is_none():
    assert foundry.parse_tester_result("RESULT: pass") is None
    assert foundry.parse_tester_result("RESULT: fail") is None


def test_b04_tester_multitoken_is_none_AMBIGUITY_NOTE():
    # Same spec ambiguity as behavior 2 (trailing extra word); asserted as the
    # most reasonable whole-token-whitelist reading. PM feedback noted in tester.md.
    assert foundry.parse_tester_result("RESULT: PASS extra") is None


def test_b04_tester_never_raises_for_any_string():
    weird = [
        "RESULT:", "RESULT", "result: pass", "RESULT: PASS",
        "RESULT: PASS\n", "\x00\x01", "RESULT: PASS " + "Y" * 500,
        "RESULT: PASS\r\nRESULT: FAIL\r\n", "un\u00efcode RESULT: FAIL",
        "\n\n\n", "RESULT:PASS",
    ]
    for t in weird:
        try:
            r = foundry.parse_tester_result(t)
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"parse_tester_result raised on {t!r}: {e!r}")
        assert r in (None, "PASS", "FAIL")


# ==========================================================================
# C. Frozen IterationOutcome                                 (Behavior 5)
# ==========================================================================
def test_b05_iteration_outcome_frozen_fields_in_order():
    io_ = foundry.IterationOutcome(3, "APPROVE", "PASS", "PUSHED")
    assert dataclasses.is_dataclass(io_) and type(io_).__name__ == "IterationOutcome"
    assert [f.name for f in dataclasses.fields(io_)] == \
        ["iteration", "review", "tester", "action"], \
        "four readable fields in declaration order"
    # readable
    assert io_.iteration == 3 and io_.review == "APPROVE"
    assert io_.tester == "PASS" and io_.action == "PUSHED"


def test_b05_iteration_outcome_equality_and_frozen():
    IO = foundry.IterationOutcome
    assert IO(1, "APPROVE", "PASS", "PUSHED") == IO(1, "APPROVE", "PASS", "PUSHED"), \
        "two instances with equal fields compare equal"
    assert IO(1, "APPROVE", "PASS", "PUSHED") != IO(2, "APPROVE", "PASS", "PUSHED")
    r = IO(1, "APPROVE", "PASS", "PUSHED")
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.review = "CHANGES_REQUIRED"
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.iteration = 9


# ==========================================================================
# D. Pure keyword-only summarize_outcomes(...)               (Behavior 6)
# ==========================================================================
def test_b06_summarize_is_keyword_only():
    with pytest.raises(TypeError):
        foundry.summarize_outcomes("prodX", _mixed_records())  # positional -> TypeError


def test_b06_records_stored_as_tuple_product_passed():
    recs = _mixed_records()
    s = foundry.summarize_outcomes(product="prodX", records=recs)
    assert isinstance(s, foundry.OutcomesSummary)
    assert s.product == "prodX"
    assert isinstance(s.records, tuple), "records must be stored as a tuple"
    assert list(s.records) == recs, "tuple must equal the input list element-wise"


def test_b06_caller_list_not_mutated_and_cannot_mutate_summary():
    recs = _mixed_records()
    n = len(recs)
    s = foundry.summarize_outcomes(product="p", records=recs)
    recs.append(foundry.IterationOutcome(99, None, None, None))  # mutate caller list
    assert len(recs) == n + 1
    assert s.total == n, "summary must snapshot the records; caller mutation must not leak in"


def test_b06_accepts_generator_and_never_raises():
    try:
        s = foundry.summarize_outcomes(product="", records=iter(_mixed_records()))
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"summarize_outcomes raised on a generator of records: {e!r}")
    assert isinstance(s.records, tuple) and s.total == 4


# ==========================================================================
# E. OutcomesSummary total / exit_code / counts              (Behaviors 7-8)
# ==========================================================================
def test_b07_total_and_exit_code():
    s = foundry.summarize_outcomes(product="p", records=_mixed_records())
    assert s.total == 4
    assert s.exit_code == 0, "a summary with records is informational -> exit 0"
    s0 = foundry.summarize_outcomes(product="p", records=[])
    assert s0.total == 0 and s0.exit_code == 2, "no iterations -> exit 2"


def test_b08_count_properties_over_records():
    s = foundry.summarize_outcomes(product="p", records=_mixed_records())
    # _mixed_records: reviews APPROVE/CHANGES_REQUIRED/APPROVE/None
    #                 testers PASS/FAIL/PASS/None
    assert s.approved == 2, f"approved must count review=='APPROVE': {s.approved}"
    assert s.changes_required == 1, f"changes_required must count 'CHANGES_REQUIRED': {s.changes_required}"
    assert s.tester_passed == 2, f"tester_passed must count tester=='PASS': {s.tester_passed}"
    assert s.tester_failed == 1, f"tester_failed must count tester=='FAIL': {s.tester_failed}"


def test_b08_counts_ignore_none_and_unknown_values():
    IO = foundry.IterationOutcome
    recs = [
        IO(1, None, None, None),
        IO(2, "MAYBE", "MAYBE", "PUSHED"),   # non-whitelist values never counted
        IO(3, "APPROVE", "FAIL", "PUSHED"),
    ]
    s = foundry.summarize_outcomes(product="p", records=recs)
    assert s.approved == 1 and s.changes_required == 0
    assert s.tester_passed == 0 and s.tester_failed == 1
    assert s.total == 3


# ==========================================================================
# F. OutcomesSummary.render()                                (Behaviors 9-10)
# ==========================================================================
def test_b09_render_header_rows_rollup():
    recs = _mixed_records()
    s = foundry.summarize_outcomes(product="demoprod", records=recs)
    out = s.render()
    assert "foundry outcomes -- demoprod" in out, f"header line missing:\n{out}"
    field_word = lambda v: "unknown" if v is None else v
    positions = []
    for rec in recs:
        tag = f"iter-{rec.iteration:02d}"
        row = _row_for(out, tag)
        assert f"review: {field_word(rec.review)}" in row, f"{tag} review wrong:\n{row}"
        assert f"tester: {field_word(rec.tester)}" in row, f"{tag} tester wrong:\n{row}"
        assert f"ship: {field_word(rec.action)}" in row, f"{tag} ship wrong:\n{row}"
        positions.append(out.index(tag))
    assert positions == sorted(positions), "rows must appear in stored order"
    assert "4 iterations: 2 approved, 1 changes-required, 2 tester-pass, 1 tester-fail" in out, \
        f"rollup line wrong:\n{out}"


def test_b09_render_unknown_for_none_fields():
    IO = foundry.IterationOutcome
    s = foundry.summarize_outcomes(product="p", records=[IO(7, None, None, None)])
    row = _row_for(s.render(), "iter-07")
    assert "review: unknown" in row and "tester: unknown" in row and "ship: unknown" in row, \
        f"None fields must render as 'unknown':\n{row}"


def test_b09_render_two_digit_zero_pad():
    IO = foundry.IterationOutcome
    s = foundry.summarize_outcomes(product="p", records=[IO(5, "APPROVE", "PASS", "PUSHED")])
    out = s.render()
    assert "iter-05" in out, f"iteration must be 2-digit zero-padded:\n{out}"


def test_b10_render_empty_summary():
    s = foundry.summarize_outcomes(product="demoprod", records=[])
    out = s.render()
    assert "no iterations yet" in out, f"empty render must say 'no iterations yet':\n{out}"
    assert "0 iterations: 0 approved, 0 changes-required, 0 tester-pass, 0 tester-fail" in out, \
        f"empty rollup wrong:\n{out}"
    assert "foundry outcomes -- demoprod" in out


# ==========================================================================
# G. gather_outcomes(cfg[, limit])                           (Behaviors 11-13)
# ==========================================================================
def test_b11_reads_three_sentinels_absent_is_none_ascending(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_outcome(cfg, 1, review="APPROVE", tester="PASS", action="PUSHED abc1")
    _write_outcome(cfg, 2, review="CHANGES_REQUIRED", tester="FAIL", action="REVERTED")
    _write_outcome(cfg, 3, review="APPROVE")                    # tester + final ABSENT -> None
    _write_outcome(cfg, 10, tester="PASS", action="PUSHED z")   # reviewer ABSENT -> None
    s = foundry.gather_outcomes(cfg)
    assert s.product == cfg.name == "demoprod"
    got = [(r.iteration, r.review, r.tester, r.action) for r in s.records]
    assert got == [
        (1, "APPROVE", "PASS", "PUSHED"),
        (2, "CHANGES_REQUIRED", "FAIL", "REVERTED"),
        (3, "APPROVE", None, None),
        (10, None, "PASS", "PUSHED"),
    ], f"ascending INTEGER order (iter-10 after iter-03) + absent-artifact -> None:\n{got}"


def test_b11_unreadable_artifact_is_none_never_raises(tmp_path):
    # an iter-NN dir with a reviewer.md that has NO recognizable sentinel ->
    # review None; the row still appears (dir exists), never raising.
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    d = _iter_dir(cfg, 1)
    d.mkdir(parents=True, exist_ok=True)
    (d / "reviewer.md").write_text("prose only, no verdict sentinel\n")
    (d / "tester.md").write_text("prose only, no result sentinel\n")
    (d / "final.md").write_text("prose only, no action sentinel\n")
    s = foundry.gather_outcomes(cfg)
    assert s.total == 1
    r = s.records[0]
    assert (r.iteration, r.review, r.tester, r.action) == (1, None, None, None)


def test_b12_limit_positive_keeps_highest_n_ascending(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    for n in range(1, 6):
        _write_outcome(cfg, n, review="APPROVE", tester="PASS", action=f"PUSHED s{n}")
    s = foundry.gather_outcomes(cfg, limit=2)
    assert [r.iteration for r in s.records] == [4, 5], \
        "limit=2 keeps the highest-2 iterations, ascending order preserved"
    assert s.total == 2


def test_b12_none_and_nonpositive_limit_return_all(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    for n in range(1, 6):
        _write_outcome(cfg, n, review="APPROVE", tester="PASS", action=f"PUSHED s{n}")
    assert [r.iteration for r in foundry.gather_outcomes(cfg).records] == [1, 2, 3, 4, 5]
    assert [r.iteration for r in foundry.gather_outcomes(cfg, limit=None).records] == [1, 2, 3, 4, 5]
    assert [r.iteration for r in foundry.gather_outcomes(cfg, limit=0).records] == [1, 2, 3, 4, 5]
    assert [r.iteration for r in foundry.gather_outcomes(cfg, limit=-3).records] == [1, 2, 3, 4, 5]


def test_b13_missing_state_dir_returns_empty_never_raises(tmp_path):
    # load_config eagerly creates <work_root>/state; DELETE it, then prove
    # gather_outcomes tolerates the absent dir (empty summary, no re-create).
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    shutil.rmtree(cfg.state, ignore_errors=True)
    assert not pathlib.Path(cfg.state).exists()
    try:
        s = foundry.gather_outcomes(cfg)
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"gather_outcomes raised on a missing state dir: {e!r}")
    assert s.total == 0 and s.product == cfg.name
    assert not pathlib.Path(cfg.state).exists(), \
        "gather_outcomes must NOT create the state dir (read-only)"


def test_b13_file_where_state_dir_belongs_returns_empty(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    shutil.rmtree(cfg.state, ignore_errors=True)
    pathlib.Path(cfg.state).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(cfg.state).write_text("i am a file, not a directory")
    try:
        s = foundry.gather_outcomes(cfg)
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"gather_outcomes raised on a FILE where a dir belongs: {e!r}")
    assert s.total == 0


# ==========================================================================
# H. outcomes_cli(cfg[, limit])                              (Behavior 14)
# ==========================================================================
def test_b14_cli_prints_render_returns_exit_and_read_only(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_outcome(cfg, 1, review="APPROVE", tester="PASS", action="PUSHED a")
    _write_outcome(cfg, 2, review="CHANGES_REQUIRED", tester="FAIL", action="REVERTED")
    before = _snapshot_tree(tmp_path)
    out_io = io.StringIO()
    old = sys.stdout
    sys.stdout = out_io
    try:
        rc = foundry.outcomes_cli(cfg)
    finally:
        sys.stdout = old
    out = out_io.getvalue()
    # prints exactly gather_outcomes(cfg).render() (+ a trailing newline from print)
    expected = foundry.gather_outcomes(cfg).render()
    assert out == expected + "\n", f"CLI must print render()+newline:\n{out!r}\n!=\n{expected!r}"
    assert rc == 0, f"a ledger with iterations must exit 0, got {rc}"
    assert _snapshot_tree(tmp_path) == before, "outcomes wrote a file (must be read-only)"


def test_b14_cli_empty_exit2_creates_no_directories(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    shutil.rmtree(cfg.state, ignore_errors=True)
    assert not pathlib.Path(cfg.state).exists()
    out_io = io.StringIO()
    old = sys.stdout
    sys.stdout = out_io
    try:
        rc = foundry.outcomes_cli(cfg)
    finally:
        sys.stdout = old
    out = out_io.getvalue()
    assert rc == 2, f"empty ledger must exit 2, got {rc}\n{out}"
    assert "no iterations yet" in out
    assert not pathlib.Path(cfg.state).exists(), \
        "outcomes_cli must NOT create the state dir (read-only)"


def test_b14_cli_limit_passthrough(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    for n in range(1, 6):
        _write_outcome(cfg, n, review="APPROVE", tester="PASS", action=f"PUSHED s{n}")
    out_io = io.StringIO()
    old = sys.stdout
    sys.stdout = out_io
    try:
        rc = foundry.outcomes_cli(cfg, limit=2)
    finally:
        sys.stdout = old
    out = out_io.getvalue()
    assert rc == 0
    assert "iter-04" in out and "iter-05" in out, f"limit=2 -> highest 2:\n{out}"
    for tag in ("iter-01", "iter-02", "iter-03"):
        assert tag not in out, f"{tag} must NOT appear under limit=2:\n{out}"
    assert "2 iterations:" in out


# ==========================================================================
# I. foundry.main(["outcomes", ...]) dispatch                (Behavior 15)
# ==========================================================================
def test_b15_main_dispatches_and_returns_exit_code(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_outcome(cfg, 1, review="APPROVE", tester="PASS", action="PUSHED a")
    rc, out = _run_cli(["outcomes", "--config", str(cfg_path)])
    assert rc == 0, f"main must return outcomes_cli's exit code, got {rc}\n{out}"
    assert "iter-01" in out and "foundry outcomes -- demoprod" in out
    # empty -> exit 2
    shutil.rmtree(cfg.state, ignore_errors=True)
    pathlib.Path(cfg.state).mkdir(parents=True, exist_ok=True)
    rc2, out2 = _run_cli(["outcomes", "--config", str(cfg_path)])
    assert rc2 == 2, f"empty ledger via main must exit 2, got {rc2}\n{out2}"


def test_b15_main_limit_passthrough_via_spy(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    captured = {}

    def spy(cfg, limit=None):
        captured["limit"] = limit
        return 0

    monkeypatch.setattr(foundry, "outcomes_cli", spy)
    _run_cli(["outcomes", "--config", str(cfg_path), "--limit", "7"])
    assert captured.get("limit") == 7, "--limit N must pass through to outcomes_cli"
    captured.clear()
    _run_cli(["outcomes", "--config", str(cfg_path)])
    assert captured.get("limit") is None, "no --limit -> default None"


def test_b15_main_config_required_systemexit2():
    with pytest.raises(SystemExit) as ei:
        foundry.main(["outcomes"])
    assert ei.value.code == 2, "omitting --config must raise SystemExit(2)"


# ==========================================================================
# J. Dormancy + import regression                            (Behaviors 16-17)
# ==========================================================================
def test_b16_new_symbols_absent_from_orchestrators():
    for fn_name in ORCHESTRATORS:
        assert callable(getattr(foundry, fn_name)), \
            f"orchestrator foundry.{fn_name} missing (regression)"
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references new symbol {sym!r} (must stay off the control path)"
        assert "outcomes" not in consts, \
            f"{fn_name} contains the 'outcomes' subcommand literal (must stay off the control path)"


def test_b16_new_symbols_absent_from_dispatcher():
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, consts = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in names, f"dispatcher references new symbol {sym!r}"
    assert "outcomes" not in consts, "dispatcher references the 'outcomes' subcommand literal"


def test_b17_both_modules_import():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b17_new_surface_present_and_callable():
    for s in ("parse_review_verdict", "parse_tester_result", "summarize_outcomes",
              "gather_outcomes", "outcomes_cli"):
        assert callable(getattr(foundry, s)), f"foundry.{s} missing/not callable"
    assert hasattr(foundry, "IterationOutcome") and hasattr(foundry, "OutcomesSummary")
    # the reused ship-action parser stays present (gather_outcomes reads final.md via it)
    assert callable(foundry.parse_ship_action)


def test_b17_help_lists_outcomes_subcommand(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for sub in ("run", "once", "doctor", "status", "history", "outcomes"):
        assert sub in out, f"subcommand {sub!r} missing from --help:\n{out}"
