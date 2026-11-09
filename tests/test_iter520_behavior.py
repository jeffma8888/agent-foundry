"""Iteration 520 -- BLACK-BOX drift tests: roles/final.md's preship bullet and
README #50 name preship's fourth exit-2 cause (a red clone suite whose PARENT
fails the IDENTICAL set of tests), and the card says to record the failing-test
list and the interpreter for that case.

Reads only TRACKED files (roles/, README.md, roadmap files) plus an import of the
engine modules; no gitignored state is consulted.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
CARD = _ROOT / "roles" / "final.md"
README = _ROOT / "README.md"

EXIT1_RULE = (
    "exit `1` (PRESHIP: BROKEN) is decisive evidence about the tree and is a "
    "BLOCKING gate failure -- do NOT push, take the \"If ANY fail\" revert path."
)

# Inline copies of the pre-iter-520 (HEAD e1e6357) wording -- the can-fail fixtures.
OLD_CARD_LINE = (
    "- **Pre-ship local-clone gate (the ship tree, re-verified before it is public).** "
    "Run `python3 <checkout>/foundry.py preship --config PRODUCT_CONFIG` now. "
    "The rule is ASYMMETRIC, unlike the leak-guard above: " + EXIT1_RULE + " "
    "Exit `2` (PRESHIP: INCOMPLETE) is evidence about the MACHINE, not the tree "
    "(clone or dependency install could not complete, or the time budget ran out) "
    "-- it is NOT a gate failure: record it verbatim in your output file as an "
    "unverified ship and proceed, because the post-release check is still a backstop."
)
OLD_README_LINE = (
    "# 50. RE-VERIFY THE SHIP COMMIT FROM A CLONE (`preship`): the BLOCKING pre-push "
    "gate. Bounded by one `PRESHIP_BUDGET_SECONDS` knob. Exit 1 (suite failed / sha "
    "mismatch) BLOCKS the push; exit 2 (clone, install or budget) is ADVISORY on "
    "purpose -- `postrelease_step` is still the backstop:"
)


def _preship_lines(text):
    return [ln for ln in text.splitlines()
            if ln.startswith("-") and "preship" in ln.lower()]


def _card_line():
    lines = _preship_lines(CARD.read_text(encoding="utf-8"))
    assert len(lines) == 1, lines
    return lines[0]


def _readme50(text):
    lines = [ln for ln in text.splitlines() if ln.startswith("# 50.")]
    assert len(lines) == 1, lines
    return lines[0]


# ---- predicates shared by the live checks and the can-fail checks ----------

def b1_ok(line):
    return "PARENT" in line and "IDENTICAL" in line


def b3_ok(line):
    return "failing-test list" in line and "interpreter" in line


def b5_ok(line):
    return ("PARENT" in line and "identical set" in line and "ADVISORY" in line
            and "Exit 1 (suite failed / sha mismatch) BLOCKS the push" in line)


# ---- B1 ---------------------------------------------------------------------

def test_b1_single_preship_line_names_parent_identical():
    line = _card_line()
    assert b1_ok(line), line


# ---- B2 ---------------------------------------------------------------------

@pytest.mark.parametrize("needle", [
    "clone or dependency install could not complete",
    "the time budget ran out",
    "PRESHIP: BROKEN",
    "PRESHIP: INCOMPLETE",
])
def test_b2_existing_causes_verbatim(needle):
    assert needle in _card_line()


@pytest.mark.parametrize("needle", ["blocking", "not a gate failure"])
def test_b2_existing_rule_words_case_insensitive(needle):
    assert needle in _card_line().lower()


# ---- B3 ---------------------------------------------------------------------

def test_b3_record_failing_list_and_interpreter():
    line = _card_line()
    assert b3_ok(line), line


# ---- B4 ---------------------------------------------------------------------

def test_b4_exit1_rule_unchanged():
    assert EXIT1_RULE in _card_line()


# ---- B5 ---------------------------------------------------------------------

def test_b5_readme_50_names_parent_identical_set():
    line = _readme50(README.read_text(encoding="utf-8"))
    assert b5_ok(line), line


# ---- B6 ---------------------------------------------------------------------

@pytest.mark.parametrize("sentinel", [
    "- Output file final line: `ACTION: PUSHED <short-sha>`",
    "- Final line: `ACTION: REVERTED`",
])
def test_b6_ship_sentinel_lines_unchanged(sentinel):
    lines = [ln.rstrip() for ln in CARD.read_text(encoding="utf-8").splitlines()]
    assert sentinel in lines


# ---- B7 ---------------------------------------------------------------------

def test_b7_archived_span_still_present():
    texts = [(_ROOT / n).read_text(encoding="utf-8")
             for n in ("PLATFORM_ROADMAP.md", "PLATFORM_ROADMAP_ARCHIVE.md")]
    assert any("(clone, install or budget)" in t for t in texts)
    assert any("exit 2 (clone, install or budget) is ADVISORY" in t for t in texts)


def test_b7_no_other_role_card_names_preship():
    offenders = [p.name for p in sorted((_ROOT / "roles").glob("*"))
                 if p.is_file() and p.name != "final.md"
                 and "preship" in p.read_text(encoding="utf-8", errors="replace").lower()]
    assert offenders == []


# ---- B8: can-fail against the old wording ----------------------------------

def test_b8_old_card_line_fails_b1_and_b3():
    assert len(_preship_lines(OLD_CARD_LINE)) == 1
    assert EXIT1_RULE in OLD_CARD_LINE  # fixture is faithful on the unchanged part
    assert not b1_ok(OLD_CARD_LINE)
    assert not b3_ok(OLD_CARD_LINE)


def test_b8_old_readme_line_fails_b5():
    line = _readme50(OLD_README_LINE)
    assert "ADVISORY" in line
    assert not b5_ok(line)


# ---- B9 ---------------------------------------------------------------------

# The byte-unchanged half of B9 is checked by hand in tester.md: repo guards
# (test_iter54 b8, test_iter132 b8) forbid a test asserting the engine file unchanged.

@pytest.mark.parametrize("mod", ["foundry", "dispatcher"])
def test_b9_engine_modules_import(mod):
    r = subprocess.run([sys.executable, "-c", f"import {mod}"], cwd=str(_ROOT),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
