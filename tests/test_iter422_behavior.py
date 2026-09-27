"""Iteration 422 -- BLACK-BOX behavior tests: USAGE.md's Controls cheat-sheet migrates its
status row from the never-produced `STATUS_REPORT.md` to the live `status` verb (plus one
`history` re-grounding row), ARCHITECTURE.md states the Reporter seat's real reachability,
and a DORMANT pure guard `usage_cheatsheet_row_gaps` pins that every cheat-sheet `Do` cell
names a shipped verb and no dead artifact.

Spec under test: products/_platform/state/iter-422/pm.md, Expected Behaviors 1-10.

  1.  USAGE.md cheat-sheet row `See a team's status` -> Do cell is exactly
      `foundry.py status --config <cfg>`; `STATUS_REPORT` appears nowhere in USAGE.md.
  2.  Exactly one new row `Re-ground after an absence` -> `foundry.py history --config <cfg>
      --limit 12` placed IMMEDIATELY after the status row; 10 data rows total; exactly one
      `./launch.sh` row; `uv run python dispatcher.py` absent (test_iter236 b7 pins).
  3.  ARCHITECTURE.md pipeline-table row whose `Role file` cell is `` `reporter.md` `` has a
      Stage cell equal to the behavior-3 string, pure ASCII, and the row still has 5 cells.
  4.  `CHEATSHEET_DEAD_TARGETS == ("STATUS_REPORT.md",)`; `usage_cheatsheet_row_gaps(usage_text,
      verbs, *, dead_targets=CHEATSHEET_DEAD_TARGETS) -> tuple[str, ...]` (via
      `inspect.signature`), module-level, docstring carries DORMANT, placed after
      `final_ledger_claim_gaps` and before `pytest_addopts_plugin_gaps` (line-number census).
  5.  TOTAL + PURE: `""`, `None`, a text with no heading -> `()`; `verbs` may be any iterable
      of str; deterministic; arguments unmutated; no filesystem / subprocess / clock reached.
  6.  Worktree half of the two-sided proof: `verbs = foundry_cli_verbs(<foundry.py text>)`
      over the tracked USAGE.md -> `()`; regressing the status row IN MEMORY to the dead
      artifact flips the same call to `("See a team's status",)` (non-vacuity).
  7.  The spec's synthetic table -> `("X", "Y")`; with `dead_targets=()` -> `("X",)`.
  8.  Section scoping: rows under `## Something else` -> `()`; a row after a following
      `## Next` heading is not reported.
  9.  DORMANT: the token `usage_cheatsheet_row_gaps` is absent from `dispatcher.py`'s source
      and namespace, from every pipeline / gate host, and from every `*_cli` verb handler
      and `main` (machine census by `inspect.getsource`).
  10. This module: generic identifiers, repo-relative paths, tracked files only.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-422 PM
spec, the tracked user docs (USAGE.md, ARCHITECTURE.md), the pre-existing conventions under
`tests/` (test_iter236 b7, test_iter373 DORMANT_HOSTS), and the product's OWN observable
behavior by importing and CALLING its public names.  The implementation SOURCE of the new
guard was NOT read by this author, nor the engineer's or reviewer's notes,
`IMPLEMENTATION.patch`, or any `git diff`.  Behavior 9's census and behavior 4's placement
check are MACHINE scans (`inspect.getsource` / `inspect.getsourcelines` inside the test),
the convention iterations 336, 361 and 373 already use for the same invariant.

FRESH-CLONE SAFE / OFFLINE: the only ambient files read are TRACKED (`USAGE.md`,
`ARCHITECTURE.md`, `foundry.py`, `dispatcher.py`) and are reached through
`pathlib.Path(__file__).resolve().parents[1]`, never an absolute machine path.  No real
subprocess, git, network or clock: the HEAD half of behavior 6 is measured ONCE in the
tester report, not pinned here (a HEAD-relative assertion is vacuous in the re-verify clone).
"""
from __future__ import annotations

import builtins
import inspect
import os
import pathlib
import subprocess
import sys
import time
import typing

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe (the quality bar)

THIS_ITER = 422

CHEATSHEET_HEADING = "## Controls cheat-sheet"
STATUS_WANT = "See a team's status"
STATUS_DO = "`foundry.py status --config <cfg>`"
HISTORY_WANT = "Re-ground after an absence"
HISTORY_DO = "`foundry.py history --config <cfg> --limit 12`"
DEAD_ARTIFACT_TOKEN = "STATUS_REPORT"
EXPECTED_DATA_ROWS = 10
LAUNCHER_TOKEN = "./launch.sh"
FOREGROUND_FORM = "uv run python dispatcher.py"

REPORTER_ROLE_CELL = "`reporter.md`"
REPORTER_STAGE_CELL = (
    "Reporter (every 5 iters; `run` verb via `run_continuous` only, never under `dispatcher.py`)"
)
REPORTER_OLD_STAGE_CELL = "Reporter (every 5 iters)"

GUARD = "usage_cheatsheet_row_gaps"
CONSTANT = "CHEATSHEET_DEAD_TARGETS"
NEW_SYMBOLS = (GUARD, CONSTANT)

# Hosts whose source must not name the new symbols (test_iter373 DORMANT_HOSTS shape).
DORMANT_HOSTS = (
    "run_iteration", "run_stage", "build_prompt", "run_continuous",
    "postrelease_step", "preship_cli", "run_doctor", "run_doctor_cli", "main",
)

SPEC_VERBS = ("once", "status", "history")
SPEC_TABLE = (
    "## Controls cheat-sheet\n"
    "\n"
    "| Want | Do |\n"
    "|---|---|\n"
    "| X | `foundry.py nosuchverb --config c` |\n"
    "| Y | `cat products/n/STATUS_REPORT.md` |\n"
    "| Z | `./launch.sh` |\n"
    "| W | see foundry.py |\n"
    "| V | `foundry.py once --config <cfg>` |\n"
)
SPEC_ROWS = {
    "X": "| X | `foundry.py nosuchverb --config c` |",
    "Y": "| Y | `cat products/n/STATUS_REPORT.md` |",
    "Z": "| Z | `./launch.sh` |",
    "W": "| W | see foundry.py |",
    "V": "| V | `foundry.py once --config <cfg>` |",
}
TABLE_HEAD = "## Controls cheat-sheet\n\n| Want | Do |\n|---|---|\n"


# ---------------------------------------------------------------- helpers (the test's OWN scoper)


def _usage_text() -> str:
    return (_ROOT / "USAGE.md").read_text(encoding="utf-8")


def _arch_text() -> str:
    return (_ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")


def _foundry_text() -> str:
    return (_ROOT / "foundry.py").read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """Lines from the `## <heading>` line up to (not including) the next `## ` line."""
    out: list[str] = []
    inside = False
    for ln in text.splitlines():
        if inside and ln.startswith("## "):
            break
        if ln.rstrip() == heading:
            inside = True
            continue
        if inside:
            out.append(ln)
    assert inside, f"heading {heading!r} not found"
    return "\n".join(out)


def _table_rows(section: str) -> list[list[str]]:
    """Data rows as stripped cell lists: header (first table line) and separators dropped."""
    table_lines = [ln.strip() for ln in section.splitlines() if ln.strip().startswith("|")]
    rows: list[list[str]] = []
    for i, s in enumerate(table_lines):
        cells = [c.strip() for c in s.strip("|").split("|")]
        if i == 0:
            continue  # header row
        if set("".join(cells)) <= set("-: "):
            continue  # separator row
        rows.append(cells)
    return rows


def _cheatsheet_rows() -> list[list[str]]:
    return _table_rows(_section(_usage_text(), CHEATSHEET_HEADING))


def _rows_by_want(rows: list[list[str]]) -> dict[str, list[str]]:
    return {r[0]: r for r in rows}


def _guard():
    return getattr(foundry, GUARD)


def _live_verbs():
    return foundry.foundry_cli_verbs(_foundry_text())


def _without_row(table: str, key: str) -> str:
    line = SPEC_ROWS[key]
    assert table.count(line) == 1, f"row {key} must appear exactly once to be deleted"
    return table.replace(line + "\n", "")


# ---------------------------------------------------------------- behavior 1


def test_b1_status_row_names_the_live_status_verb() -> None:
    rows = _rows_by_want(_cheatsheet_rows())
    assert STATUS_WANT in rows, f"cheat-sheet lost the {STATUS_WANT!r} row: {sorted(rows)}"
    assert rows[STATUS_WANT][1] == STATUS_DO, rows[STATUS_WANT]


def test_b1_status_row_uses_the_same_cfg_placeholder_as_the_once_row() -> None:
    rows = _rows_by_want(_cheatsheet_rows())
    once_do = rows["One iteration only"][1]
    assert "<cfg>" in once_do, once_do
    assert "<cfg>" in rows[STATUS_WANT][1], rows[STATUS_WANT][1]
    assert once_do.startswith("`foundry.py ") and rows[STATUS_WANT][1].startswith("`foundry.py ")


def test_b1_dead_artifact_token_is_absent_from_usage() -> None:
    text = _usage_text()
    offenders = [(n, ln) for n, ln in enumerate(text.splitlines(), 1) if DEAD_ARTIFACT_TOKEN in ln]
    assert offenders == [], f"{DEAD_ARTIFACT_TOKEN} still named in USAGE.md: {offenders}"


# ---------------------------------------------------------------- behavior 2


def test_b2_history_row_is_present_with_the_exact_do_cell() -> None:
    rows = _rows_by_want(_cheatsheet_rows())
    assert HISTORY_WANT in rows, sorted(rows)
    assert rows[HISTORY_WANT][1] == HISTORY_DO, rows[HISTORY_WANT]


def test_b2_history_row_sits_immediately_after_the_status_row() -> None:
    wants = [r[0] for r in _cheatsheet_rows()]
    assert wants.count(STATUS_WANT) == 1 and wants.count(HISTORY_WANT) == 1, wants
    assert wants.index(HISTORY_WANT) == wants.index(STATUS_WANT) + 1, wants


def test_b2_cheatsheet_has_exactly_ten_data_rows() -> None:
    rows = _cheatsheet_rows()
    assert len(rows) == EXPECTED_DATA_ROWS, [r[0] for r in rows]


def test_b2_every_data_row_has_a_want_and_a_do_cell() -> None:
    for row in _cheatsheet_rows():
        assert len(row) == 2, row
        assert row[0] and row[1], row


def test_b2_want_cells_are_unique() -> None:
    wants = [r[0] for r in _cheatsheet_rows()]
    assert len(set(wants)) == len(wants), wants


def test_b2_exactly_one_row_invokes_the_launcher() -> None:
    hits = [r for r in _cheatsheet_rows() if LAUNCHER_TOKEN in r[1]]
    assert len(hits) == 1, hits


def test_b2_foreground_launch_form_is_absent_from_usage() -> None:
    offenders = [n for n, ln in enumerate(_usage_text().splitlines(), 1) if FOREGROUND_FORM in ln]
    assert offenders == [], offenders


# ---------------------------------------------------------------- behavior 3


def _reporter_row() -> list[str]:
    hits = []
    for ln in _arch_text().splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) >= 3 and cells[2] == REPORTER_ROLE_CELL:
            hits.append(cells)
    assert len(hits) == 1, f"expected exactly one `reporter.md` row, got {hits}"
    return hits[0]


def test_b3_architecture_table_header_still_names_stage_and_role_file() -> None:
    lines = [ln for ln in _arch_text().splitlines() if ln.startswith("| # | Stage | Role file |")]
    assert len(lines) == 1, lines
    cells = [c.strip() for c in lines[0].strip("|").split("|")]
    assert cells[1] == "Stage" and cells[2] == "Role file", cells
    assert len(cells) == 5, cells


def test_b3_reporter_row_stage_cell_is_the_spec_string() -> None:
    row = _reporter_row()
    assert row[1] == REPORTER_STAGE_CELL, row[1]


def test_b3_reporter_row_stage_cell_is_ascii() -> None:
    row = _reporter_row()
    assert row[1].isascii(), [c for c in row[1] if not c.isascii()]


def test_b3_reporter_row_still_has_five_cells() -> None:
    row = _reporter_row()
    assert len(row) == 5, row


def test_b3_old_bare_stage_wording_is_gone_from_the_reporter_row() -> None:
    row = _reporter_row()
    assert row[1] != REPORTER_OLD_STAGE_CELL, row[1]
    assert row[1].startswith("Reporter (every 5 iters;"), row[1]
    assert REPORTER_OLD_STAGE_CELL not in _arch_text(), "the bare `(every 5 iters)` wording survives somewhere"


def test_b3_reporter_row_names_both_the_run_verb_and_the_dispatcher() -> None:
    row = _reporter_row()
    assert "`run` verb" in row[1] and "run_continuous" in row[1] and "dispatcher.py" in row[1], row[1]


def test_b3_architecture_names_the_reporter_reachability_exactly_once() -> None:
    text = _arch_text()
    assert text.count(REPORTER_STAGE_CELL) == 1, text.count(REPORTER_STAGE_CELL)


# ---------------------------------------------------------------- behavior 4


def test_b4_constant_is_the_spec_tuple() -> None:
    value = getattr(foundry, CONSTANT)
    assert isinstance(value, tuple), type(value)
    assert value == ("STATUS_REPORT.md",), value


def test_b4_guard_is_a_module_level_function_of_foundry() -> None:
    fn = _guard()
    assert inspect.isfunction(fn), fn
    assert fn.__module__ == foundry.__name__
    assert fn.__qualname__ == GUARD, fn.__qualname__


def test_b4_signature_parameters_names_and_kinds() -> None:
    sig = inspect.signature(_guard())
    params = list(sig.parameters.values())
    assert [p.name for p in params] == ["usage_text", "verbs", "dead_targets"], params
    assert params[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params[1].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params[2].kind is inspect.Parameter.KEYWORD_ONLY
    assert params[0].default is inspect.Parameter.empty
    assert params[1].default is inspect.Parameter.empty


def test_b4_dead_targets_default_is_the_constant() -> None:
    sig = inspect.signature(_guard())
    default = sig.parameters["dead_targets"].default
    assert default == getattr(foundry, CONSTANT), default
    assert default == ("STATUS_REPORT.md",), default


def test_b4_annotations_via_type_hints() -> None:
    hints = typing.get_type_hints(_guard())
    assert hints.get("usage_text") is str, hints
    assert hints.get("return") == tuple[str, ...], hints


def test_b4_signature_annotations_read_as_str_and_tuple() -> None:
    sig = inspect.signature(_guard())
    ann = sig.parameters["usage_text"].annotation
    assert ann in (str, "str"), ann
    ret = sig.return_annotation
    assert ret in (tuple[str, ...], "tuple[str, ...]"), ret


def test_b4_docstring_declares_dormancy() -> None:
    doc = inspect.getdoc(_guard()) or ""
    assert "DORMANT" in doc, doc[:200]


def test_b4_guard_sits_between_its_two_named_neighbours() -> None:
    before = foundry.final_ledger_claim_gaps
    after = foundry.pytest_addopts_plugin_gaps
    b_lines, b_start = inspect.getsourcelines(before)
    g_lines, g_start = inspect.getsourcelines(_guard())
    _a_lines, a_start = inspect.getsourcelines(after)
    b_end = b_start + len(b_lines) - 1
    g_end = g_start + len(g_lines) - 1
    assert b_end < g_start < g_end < a_start, (b_end, g_start, g_end, a_start)


def test_b4_constant_is_defined_directly_after_final_ledger_claim_gaps() -> None:
    import re

    lines = _foundry_text().splitlines()
    define = re.compile(rf"^{CONSTANT}\b")
    hits = [n for n, ln in enumerate(lines, 1) if define.match(ln)]
    assert len(hits) == 1, hits
    _b, b_start = inspect.getsourcelines(foundry.final_ledger_claim_gaps)
    b_end = b_start + len(_b) - 1
    _g, g_start = inspect.getsourcelines(_guard())
    _a, a_start = inspect.getsourcelines(foundry.pytest_addopts_plugin_gaps)
    assert b_end < hits[0] < g_start < a_start, (b_end, hits[0], g_start, a_start)
    # "directly after": no other top-level def sits between the neighbour's end and the constant.
    between = [ln for ln in lines[b_end:hits[0] - 1] if ln.startswith("def ")]
    assert between == [], between


# ---------------------------------------------------------------- behavior 5


@pytest.mark.parametrize("text", ["", None, "# Title\n\n| Want | Do |\n|---|---|\n| X | `foundry.py nosuchverb` |\n"])
def test_b5_total_over_degenerate_texts(text) -> None:
    assert _guard()(text, ()) == ()


def test_b5_returns_a_tuple_of_str() -> None:
    out = _guard()(SPEC_TABLE, SPEC_VERBS)
    assert isinstance(out, tuple), type(out)
    assert all(isinstance(x, str) for x in out), out


@pytest.mark.parametrize("wrap", [tuple, list, set, frozenset, iter])
def test_b5_verbs_may_be_any_iterable_of_str(wrap) -> None:
    assert _guard()(SPEC_TABLE, wrap(SPEC_VERBS)) == ("X", "Y")


def test_b5_deterministic_on_equal_inputs() -> None:
    first = _guard()(SPEC_TABLE, SPEC_VERBS)
    second = _guard()(str(SPEC_TABLE), tuple(SPEC_VERBS))
    assert first == second == ("X", "Y")


def test_b5_arguments_are_not_mutated() -> None:
    verbs = list(SPEC_VERBS)
    dead = list(getattr(foundry, CONSTANT))
    text = SPEC_TABLE
    _guard()(text, verbs, dead_targets=dead)
    assert verbs == list(SPEC_VERBS)
    assert dead == list(getattr(foundry, CONSTANT))
    assert text == SPEC_TABLE
    assert getattr(foundry, CONSTANT) == ("STATUS_REPORT.md",)


def test_b5_reaches_no_filesystem_subprocess_or_clock(monkeypatch) -> None:
    def _boom(*_a, **_k):
        raise AssertionError("guard reached an I/O or clock seam")

    monkeypatch.setattr(builtins, "open", _boom)
    monkeypatch.setattr(os, "listdir", _boom)
    monkeypatch.setattr(os, "stat", _boom)
    monkeypatch.setattr(os.path, "exists", _boom)
    monkeypatch.setattr(pathlib.Path, "read_text", _boom)
    monkeypatch.setattr(pathlib.Path, "exists", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "check_output", _boom)
    monkeypatch.setattr(time, "time", _boom)
    monkeypatch.setattr(time, "monotonic", _boom)
    assert _guard()(SPEC_TABLE, SPEC_VERBS) == ("X", "Y")
    assert _guard()("", ()) == ()


def test_b5_dead_targets_keyword_accepts_any_iterable() -> None:
    assert _guard()(SPEC_TABLE, SPEC_VERBS, dead_targets=["STATUS_REPORT.md"]) == ("X", "Y")
    assert _guard()(SPEC_TABLE, SPEC_VERBS, dead_targets=frozenset()) == ("X",)


# ---------------------------------------------------------------- behavior 6 (worktree half)


def test_b6_live_verbs_include_the_migrated_row_verbs() -> None:
    verbs = _live_verbs()
    assert isinstance(verbs, tuple), type(verbs)
    for v in ("once", "status", "history", "new-product"):
        assert v in verbs, (v, verbs)


def test_b6_worktree_usage_has_no_cheatsheet_gaps() -> None:
    assert _guard()(_usage_text(), _live_verbs()) == ()


def test_b6_regressing_the_status_row_in_memory_flips_the_guard() -> None:
    text = _usage_text()
    live_row = f"| {STATUS_WANT} | {STATUS_DO} |"
    assert text.count(live_row) == 1, text.count(live_row)
    regressed = text.replace(live_row, f"| {STATUS_WANT} | `cat products/<name>/STATUS_REPORT.md` |")
    assert _guard()(regressed, _live_verbs()) == (STATUS_WANT,)


def test_b6_an_unknown_verb_in_any_live_row_is_reported_by_want() -> None:
    text = _usage_text()
    live_row = f"| {HISTORY_WANT} | {HISTORY_DO} |"
    assert text.count(live_row) == 1
    broken = text.replace(live_row, f"| {HISTORY_WANT} | `foundry.py nosuchverb --config <cfg>` |")
    assert _guard()(broken, _live_verbs()) == (HISTORY_WANT,)


def test_b6_every_cheatsheet_verb_token_is_a_live_verb() -> None:
    """Independent oracle: the test's own scoper + regex agree the table is clean."""
    import re

    verbs = set(_live_verbs())
    token = re.compile(r"foundry\.py\s+([a-z][a-z0-9-]*)")
    for row in _cheatsheet_rows():
        for m in token.finditer(row[1]):
            assert m.group(1) in verbs, (row, m.group(1))
        for dead in getattr(foundry, CONSTANT):
            assert dead not in row[1], row


# ---------------------------------------------------------------- behavior 7


def test_b7_spec_table_reports_the_unknown_verb_and_the_dead_target() -> None:
    assert _guard()(SPEC_TABLE, SPEC_VERBS) == ("X", "Y")


def test_b7_spec_table_with_no_dead_targets_reports_only_the_unknown_verb() -> None:
    assert _guard()(SPEC_TABLE, SPEC_VERBS, dead_targets=()) == ("X",)


@pytest.mark.parametrize("key,expected", [("X", ("X",)), ("Y", ("Y",)), ("Z", ()), ("W", ()), ("V", ())])
def test_b7_each_spec_row_alone_has_its_own_verdict(key, expected) -> None:
    table = TABLE_HEAD + SPEC_ROWS[key] + "\n"
    assert _guard()(table, SPEC_VERBS) == expected


@pytest.mark.parametrize("key,expected", [("X", ("Y",)), ("Y", ("X",)), ("Z", ("X", "Y")), ("W", ("X", "Y")), ("V", ("X", "Y"))])
def test_b7_deleting_one_row_removes_exactly_its_verdict(key, expected) -> None:
    assert _guard()(_without_row(SPEC_TABLE, key), SPEC_VERBS) == expected


def test_b7_results_are_in_document_order() -> None:
    swapped = TABLE_HEAD + SPEC_ROWS["Y"] + "\n" + SPEC_ROWS["X"] + "\n"
    assert _guard()(swapped, SPEC_VERBS) == ("Y", "X")


def test_b7_known_verb_becomes_a_gap_when_removed_from_verbs() -> None:
    assert _guard()(SPEC_TABLE, ("status", "history")) == ("X", "Y", "V")


def test_b7_header_row_is_never_reported() -> None:
    table = "## Controls cheat-sheet\n| foundry.py bogus | STATUS_REPORT.md |\n|---|---|\n| A | ok |\n"
    assert _guard()(table, SPEC_VERBS) == ()


def test_b7_separator_variants_are_never_reported() -> None:
    table = "## Controls cheat-sheet\n| Want | Do |\n|:---|---:|\n| : | - |\n| A | `foundry.py bogus` |\n"
    assert _guard()(table, SPEC_VERBS) == ("A",)


def test_b7_dead_target_in_the_want_cell_only_is_not_a_gap() -> None:
    assert _guard()(TABLE_HEAD + "| STATUS_REPORT.md | ok |\n", SPEC_VERBS) == ()


@pytest.mark.parametrize("do_cell", ["`foundry.py Status`", "`foundry.py 9abc`", "`foundry.pystatus`", "see foundry.py"])
def test_b7_non_matching_tokens_are_not_gaps(do_cell) -> None:
    assert _guard()(TABLE_HEAD + f"| A | {do_cell} |\n", SPEC_VERBS) == ()


@pytest.mark.parametrize("do_cell", ["`foundry.py new-thing`", "`foundry.py once` then `foundry.py bogus`", "`foundry.py\tbogus`"])
def test_b7_matching_unknown_tokens_are_gaps(do_cell) -> None:
    assert _guard()(TABLE_HEAD + f"| A | {do_cell} |\n", SPEC_VERBS) == ("A",)


def test_b7_want_cells_are_stripped_and_duplicates_kept() -> None:
    table = TABLE_HEAD + "|   A   | `foundry.py bogus` |\n| A | `foundry.py nope` |\n"
    assert _guard()(table, SPEC_VERBS) == ("A", "A")


def test_b7_extra_cells_do_not_hide_the_do_cell() -> None:
    assert _guard()(TABLE_HEAD + "| A | `foundry.py bogus` | note |\n", SPEC_VERBS) == ("A",)


def test_b7_crlf_and_indented_rows_are_parsed() -> None:
    crlf = TABLE_HEAD.replace("\n", "\r\n") + "| A | `foundry.py bogus` |\r\n"
    assert _guard()(crlf, SPEC_VERBS) == ("A",)
    assert _guard()(TABLE_HEAD + "   | A | `foundry.py bogus` |\n", SPEC_VERBS) == ("A",)


# ---------------------------------------------------------------- behavior 8


def test_b8_rows_under_another_heading_are_out_of_scope() -> None:
    other = SPEC_TABLE.replace("## Controls cheat-sheet", "## Something else")
    assert "## Controls cheat-sheet" not in other
    assert _guard()(other, SPEC_VERBS) == ()


def test_b8_a_row_after_the_next_h2_heading_is_not_reported() -> None:
    text = SPEC_TABLE + "\n## Next\n\n| Want | Do |\n|---|---|\n| Q | `foundry.py bogus` |\n"
    assert _guard()(text, SPEC_VERBS) == ("X", "Y")


def test_b8_only_the_next_h2_ends_the_section() -> None:
    text = TABLE_HEAD + "| A | `foundry.py bogus` |\n### Sub\n| B | `foundry.py nope` |\n# Big\n| C | `foundry.py nah` |\n"
    assert _guard()(text, SPEC_VERBS) == ("A", "B", "C")


def test_b8_heading_must_match_exactly() -> None:
    for heading in ("## Controls cheat-sheetX", "## controls cheat-sheet", "# Controls cheat-sheet"):
        text = SPEC_TABLE.replace("## Controls cheat-sheet", heading)
        assert _guard()(text, SPEC_VERBS) == (), heading


def test_b8_heading_with_no_table_returns_empty() -> None:
    assert _guard()("## Controls cheat-sheet\n\ntext only\n\n## Next\n", SPEC_VERBS) == ()
    assert _guard()("## Controls cheat-sheet", SPEC_VERBS) == ()


def test_b8_table_before_the_heading_is_out_of_scope() -> None:
    text = "| Want | Do |\n|---|---|\n| P | `foundry.py bogus` |\n\n" + SPEC_TABLE
    assert _guard()(text, SPEC_VERBS) == ("X", "Y")


# ---------------------------------------------------------------- behavior 9


@pytest.mark.parametrize("symbol", NEW_SYMBOLS)
def test_b9_dispatcher_names_none_of_the_new_symbols(symbol) -> None:
    src = inspect.getsource(dispatcher)
    assert symbol not in src, f"{symbol} reached dispatcher.py -- resume semantics moved"
    assert not hasattr(dispatcher, symbol), f"{symbol} is bound in the dispatcher namespace"


def test_b9_dispatcher_file_text_names_none_of_the_new_symbols() -> None:
    text = (_ROOT / "dispatcher.py").read_text(encoding="utf-8")
    for symbol in NEW_SYMBOLS:
        assert symbol not in text, symbol


@pytest.mark.parametrize("host", DORMANT_HOSTS)
@pytest.mark.parametrize("symbol", NEW_SYMBOLS)
def test_b9_pipeline_and_gate_hosts_stay_dormant(host, symbol) -> None:
    fn = getattr(foundry, host, None)
    assert fn is not None, f"foundry.{host} disappeared"
    src = inspect.getsource(fn)
    assert symbol not in src, f"{symbol} reached {host}: the guard is no longer dormant"


def test_b9_no_cli_verb_handler_names_the_guard() -> None:
    handlers = [
        n for n in dir(foundry)
        if n.endswith("_cli") and inspect.isfunction(getattr(foundry, n))
    ]
    assert len(handlers) >= 40, handlers  # positive control: the census saw the verb handlers
    offenders = [n for n in handlers if GUARD in inspect.getsource(getattr(foundry, n))]
    assert offenders == [], offenders


def test_b9_guard_is_named_by_no_other_foundry_function() -> None:
    """Zero call sites: the only function whose source names the guard is the guard itself."""
    callers = []
    for name, obj in vars(foundry).items():
        if not inspect.isfunction(obj) or obj.__module__ != foundry.__name__:
            continue
        try:
            src = inspect.getsource(obj)
        except (OSError, TypeError):
            continue
        if GUARD in src and name != GUARD:
            callers.append(name)
    assert callers == [], callers


def test_b9_both_modules_import_in_process() -> None:
    assert foundry is not None and dispatcher is not None
    assert hasattr(foundry, "run_iteration") and hasattr(foundry, "run_continuous")
