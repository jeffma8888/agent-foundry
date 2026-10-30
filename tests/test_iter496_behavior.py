"""Iteration 496 -- BLACK-BOX behavior tests: USAGE.md gains a
`## Product config reference` section whose table is kept two-way equal to the
`ProductConfig` dataclass (names, declaration order, defaults).

Spec under test (the iter-496 PM spec), Expected Behaviors 1-9:
   1. exactly one `## Product config reference` heading, after the cheat-sheet
   2. exactly one table in the section; header cells Field / Default / Meaning
   3. every data row has 3 cells; cell 0 is exactly one backticked identifier
   4. cell-0 names == list(config_field_names()) (order, no dups), two-sided
   5. default cell == `required` for MISSING else `json.dumps(default)` in
      backticks (tuple -> list), two-sided
   6. Meaning cells non-empty, single-line; load-time-filled fields name what an
      empty value resolves to
   7. section prose names config.local.json, the `_` prefix and `unknown`
   8. existing USAGE.md guards still hold; no absolute machine path
   9. foundry / dispatcher importable

ISOLATION HONORED: written from the spec, the repo's `tests/` conventions and the
product's RUNTIME surface only. No implementation source, engineer/reviewer note
or `git diff` was read.

Fresh-clone safe: reads only tracked files (USAGE.md, foundry.py); no git calls,
no gitignored state. The "cheat-sheet rows unchanged" pin is a literal sha256 of
the HEAD-before-this-iteration rows, so it stays meaningful after the ship.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import re
import subprocess
import sys

import pytest

import foundry

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_USAGE = (_ROOT / "USAGE.md").read_text(encoding="utf-8")
_HEADING = "## Product config reference"
_CHEAT = "## Controls cheat-sheet"
# sha256 of the 12 `|` lines of the cheat-sheet section at the pre-496 HEAD.
_CHEAT_ROWS_SHA = "5a1aa00f7137247dbd8d4cf85fde04e902fce3b0d75828f0f473c1b6859ae7f7"
_CHEAT_ROWS_N = 12


def _section(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    i = lines.index(heading)
    out = []
    for line in lines[i + 1:]:
        if line.startswith("## "):
            break
        out.append(line)
    return out


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip()[1:-1].split("|")]


def _is_sep(cells: list[str]) -> bool:
    return all(c and set(c) <= set("-: ") for c in cells)


def _parse_table(section_lines: list[str]):
    """Return (header_cells, data_rows) per spec behaviors 2-3."""
    table = [l for l in section_lines if l.strip().startswith("|")]
    header = _cells(table[0])
    rows = [_cells(l) for l in table[1:] if not _is_sep(_cells(l))]
    return header, rows


def _expected_default_cell(field: dataclasses.Field) -> str:
    if field.default is dataclasses.MISSING:
        return "required"
    d = field.default
    if isinstance(d, tuple):
        d = list(d)
    return "`" + json.dumps(d) + "`"


def _names_ok(rows) -> bool:
    return [r[0].strip("`") for r in rows] == list(foundry.config_field_names())


def _defaults_ok(rows) -> bool:
    fields = {f.name: f for f in dataclasses.fields(foundry.ProductConfig)}
    if [r[0].strip("`") for r in rows] != list(fields):
        return False
    return all(r[1] == _expected_default_cell(fields[r[0].strip("`")]) for r in rows)


_SEC = _section(_USAGE, _HEADING) if _HEADING in _USAGE.splitlines() else []


# ---- 1 ------------------------------------------------------------------
def test_b1_exactly_one_heading_after_cheat_sheet():
    lines = _USAGE.splitlines()
    assert lines.count(_HEADING) == 1
    assert lines.count(_CHEAT) == 1
    assert lines.index(_HEADING) > lines.index(_CHEAT)


# ---- 2 ------------------------------------------------------------------
def test_b2_one_table_with_field_default_meaning_header():
    assert _SEC, "section missing"
    # contiguous blocks of `|` lines == number of tables
    blocks, inside = 0, False
    for line in _SEC:
        is_row = line.strip().startswith("|")
        if is_row and not inside:
            blocks += 1
        inside = is_row
    assert blocks == 1
    header, _ = _parse_table(_SEC)
    assert header == ["Field", "Default", "Meaning"]


# ---- 3 ------------------------------------------------------------------
def test_b3_every_row_three_cells_and_backticked_identifier():
    _, rows = _parse_table(_SEC)
    assert rows
    for r in rows:
        assert len(r) == 3, r
        assert re.fullmatch(r"`[A-Za-z_][A-Za-z0-9_]*`", r[0]), r


# ---- 4 ------------------------------------------------------------------
def test_b4_names_equal_config_field_names_in_order():
    _, rows = _parse_table(_SEC)
    names = [r[0].strip("`") for r in rows]
    assert names == list(foundry.config_field_names())
    assert len(names) == len(set(names))
    assert names == [f.name for f in dataclasses.fields(foundry.ProductConfig)]


def test_b4_two_sided_drop_and_add_row_fail():
    _, rows = _parse_table(_SEC)
    assert _names_ok(rows)
    for i in range(len(rows)):
        assert not _names_ok(rows[:i] + rows[i + 1:])
    bogus = _cells('| `bogus_field` | `""` | x |')
    assert not _names_ok(rows + [bogus])
    assert not _names_ok([bogus] + rows)
    # swapping order also fails
    assert not _names_ok([rows[1], rows[0]] + rows[2:])
    # a duplicate row fails
    assert not _names_ok(rows + [rows[-1]])


# ---- 5 ------------------------------------------------------------------
def test_b5_default_cells_match_dataclass_defaults():
    _, rows = _parse_table(_SEC)
    fields = {f.name: f for f in dataclasses.fields(foundry.ProductConfig)}
    for r in rows:
        assert r[1] == _expected_default_cell(fields[r[0].strip("`")]), r


@pytest.mark.parametrize(
    "name,cell",
    [
        ("name", "required"),
        ("repo", "required"),
        ("allowed_push_repo", "required"),
        ("branch", '`"main"`'),
        ("push_enabled", "`true`"),
        ("smoke_cmd", "`null`"),
        ("gap_layers", "`[]`"),
        ("auth_resume_max", "`0`"),
        ("vision", '`""`'),
    ],
)
def test_b5_spec_examples_literal(name, cell):
    _, rows = _parse_table(_SEC)
    got = {r[0].strip("`"): r[1] for r in rows}
    assert got[name] == cell


def test_b5_required_set_is_exactly_missing_defaults():
    _, rows = _parse_table(_SEC)
    req = [r[0].strip("`") for r in rows if r[1] == "required"]
    assert req == ["name", "repo", "allowed_push_repo"]


def test_b5_two_sided_flip_any_default_fails():
    _, rows = _parse_table(_SEC)
    assert _defaults_ok(rows)
    flipped = [list(r) for r in rows]
    idx = [r[0] for r in rows].index("`branch`")
    flipped[idx][1] = '`"master"`'
    assert not _defaults_ok(flipped)
    for i in range(len(rows)):
        mutated = [list(r) for r in rows]
        mutated[i][1] = "`\"__drift__\"`"
        assert not _defaults_ok(mutated), rows[i]


# ---- 6 ------------------------------------------------------------------
def test_b6_meaning_cells_non_empty_single_line():
    _, rows = _parse_table(_SEC)
    for r in rows:
        assert r[2].strip(), r
        assert "\n" not in r[2]


@pytest.mark.parametrize(
    "name,needle",
    [
        ("roles_dir", "roles/"),
        ("work_root", "products/"),
        ("learnings", "LEARNINGS.md"),
        ("staffing", "staffing.json"),
        ("prd", "prd.json"),
    ],
)
def test_b6_load_time_filled_fields_name_resolution(name, needle):
    _, rows = _parse_table(_SEC)
    meaning = {r[0].strip("`"): r[2] for r in rows}[name]
    assert "empty" in meaning.lower(), meaning
    assert needle in meaning, meaning


# ---- 7 ------------------------------------------------------------------
def test_b7_prose_names_overlay_comment_prefix_and_unknown():
    prose = "\n".join(l for l in _SEC if not l.strip().startswith("|"))
    assert "config.local.json" in prose
    assert "`" + foundry.CONFIG_COMMENT_PREFIX + "`" in prose
    assert "`_`" in prose
    assert re.search(r"\bunknown\b", prose, re.IGNORECASE)
    assert "fail" in prose.lower()


# ---- 8 ------------------------------------------------------------------
def test_b8_cheatsheet_row_gaps_still_empty():
    src = (_ROOT / "foundry.py").read_text(encoding="utf-8")
    assert foundry.usage_cheatsheet_row_gaps(_USAGE, foundry.foundry_cli_verbs(src)) == ()


def test_b8_cheatsheet_rows_unchanged():
    rows = [l for l in _section(_USAGE, _CHEAT) if l.strip().startswith("|")]
    assert len(rows) == _CHEAT_ROWS_N
    assert hashlib.sha256("\n".join(rows).encode()).hexdigest() == _CHEAT_ROWS_SHA


def test_b8_machine_local_paragraph_stays_in_cheatsheet():
    cheat = "\n".join(_section(_USAGE, _CHEAT))
    assert "Machine-local operator knobs" in cheat
    assert "gitignored" in cheat
    assert "Machine-local operator knobs" not in "\n".join(_SEC)


def test_b8_no_absolute_machine_path_in_new_section():
    sec = "\n".join(_SEC)
    assert sec
    # built by concatenation so this file never trips the repo leak-guard denylist
    for bad in ["/" + seg + "/" for seg in ("Us" + "ers", "ho" + "me", "o" + "pt", "Applic" + "ations")]:
        assert bad not in sec, bad


# ---- 9 ------------------------------------------------------------------
def test_b9_foundry_and_dispatcher_import():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
