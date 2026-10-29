"""Iteration 486 -- BLACK-BOX behavior tests for the OPERATOR-pin routing rule.

The un-retired OPERATOR pin is candidate 1 of every slate and the PM's pick
until it ships. That rule is now written into `roles/pm.md` duty 1b and into
`roles/pm_scout.md` `## Your assigned lens`, additively (no old sentence is
reworded).

Expected Behaviors (from pm.md):
  1. pm.md 1b paragraph (line starting `1b.` up to, excluding, the next line
     starting `2. `) contains `OPERATOR`.
  2. That paragraph contains `candidate 1` (case-insensitive) and `until it ships`.
  3. That paragraph names `## Archive of completed operator directives`.
  4. The sentence carrying `OPERATOR` contains `whether or not` or `even if`.
  5. pm_scout.md `## Your assigned lens` section (heading line up to the next line
     STARTING `## `) contains `OPERATOR`, `candidate 1`, and `regardless of` or
     `whatever the lens`.
  6. Additive: pre-existing sentences of both sections survive verbatim.
  7. (covered by the existing card-reading modules in the full suite)
  8. This module reads only TRACKED cards relative to the repo root, and carries
     a negative check proving the extractors can fail.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
PM_CARD = _ROOT / "roles" / "pm.md"
SCOUT_CARD = _ROOT / "roles" / "pm_scout.md"
ARCHIVE_HEADING = "## Archive of completed operator directives"


def _norm(text: str) -> str:
    """Collapse whitespace so a sentence wrapped across card lines still matches."""
    return re.sub(r"\s+", " ", text).strip()


def _section_1b(card: str) -> str:
    lines = card.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        if not inside:
            if line.startswith("1b."):
                inside = True
                out.append(line)
            continue
        if line.startswith("2. "):
            break
        out.append(line)
    return "\n".join(out)


def _lens_section(card: str) -> str:
    lines = card.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        if not inside:
            if line.strip() == "## Your assigned lens":
                inside = True
                out.append(line)
            continue
        if line.startswith("## "):
            break
        out.append(line)
    return "\n".join(out)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", _norm(text)) if s]


@pytest.fixture(scope="module")
def pm_1b() -> str:
    sec = _section_1b(PM_CARD.read_text(encoding="utf-8"))
    assert sec, "pm.md has no line starting '1b.'"
    return sec


@pytest.fixture(scope="module")
def lens() -> str:
    sec = _lens_section(SCOUT_CARD.read_text(encoding="utf-8"))
    assert sec, "pm_scout.md has no '## Your assigned lens' heading"
    return sec


# --- EB8: inputs are tracked files, not gitignored local state -------------

@pytest.mark.parametrize("rel", ["roles/pm.md", "roles/pm_scout.md"])
def test_eb8_cards_are_tracked(rel):
    proc = subprocess.run(
        ["git", "ls-files", "--error-unmatch", rel],
        cwd=_ROOT, capture_output=True, text=True,
    )
    if proc.returncode != 0 and "not a git repository" in proc.stderr:
        pytest.skip("not running inside a git checkout")
    assert proc.returncode == 0, f"{rel} is not tracked: {proc.stderr}"


# --- EB1 ------------------------------------------------------------------

def test_eb1_1b_contains_operator(pm_1b):
    assert "OPERATOR" in pm_1b


def test_eb1_1b_section_is_bounded_before_duty_2(pm_1b):
    # The extractor stops at the next `2. ` line, so duty 2 text is excluded.
    assert not any(l.startswith("2. ") for l in pm_1b.splitlines())
    assert pm_1b.splitlines()[0].startswith("1b.")


# --- EB2 ------------------------------------------------------------------

def test_eb2_1b_says_candidate_1(pm_1b):
    assert "candidate 1" in _norm(pm_1b).lower()


def test_eb2_1b_says_until_it_ships(pm_1b):
    assert "until it ships" in _norm(pm_1b)


# --- EB3 ------------------------------------------------------------------

def test_eb3_1b_names_archive_heading(pm_1b):
    assert ARCHIVE_HEADING in _norm(pm_1b)


# --- EB4 ------------------------------------------------------------------

def test_eb4_operator_sentence_says_pick_without_slate(pm_1b):
    carrying = [s for s in _sentences(pm_1b) if "OPERATOR" in s]
    assert carrying, "no sentence in 1b carries OPERATOR"
    assert any(
        ("whether or not" in s.lower()) or ("even if" in s.lower())
        for s in carrying
    ), carrying


# --- EB5 ------------------------------------------------------------------

def test_eb5_lens_section_contains_operator(lens):
    assert "OPERATOR" in lens


def test_eb5_lens_section_says_candidate_1(lens):
    assert "candidate 1" in _norm(lens).lower()


def test_eb5_lens_section_says_regardless_of_lens(lens):
    low = _norm(lens).lower()
    assert ("regardless of" in low) or ("whatever the lens" in low)


def test_eb5_lens_section_bounded_by_line_start(lens):
    body = lens.splitlines()[1:]
    assert not any(l.startswith("## ") for l in body)


# --- EB6: additive ---------------------------------------------------------

PM_1B_OLD = [
    "1b. **Triage the scout slates when they exist.**",
    "If `pm_scout_a.md` / `pm_scout_b.md` are in your state dir, your candidate "
    "pool is their COMBINED slate (you may add a candidate of your own only if "
    "every scout candidate is clearly unfit).",
    "Pick exactly ONE, and open your spec with a short `## Triage` section: the "
    "pick, plus 1-2 lines justifying it AGAINST THE STRONGEST ALTERNATIVE from "
    "the other slate (name it).",
    "Lead the section with `PICK: **<id>**` on its own line: the decision log "
    "(`directions` / `DIRECTIONS.md`) reads that uppercase label first, before "
    "any other id in the section.",
    "Diversity guard: do not pick a near-clone of the previous 2 shipped features "
    "when a viable candidate from the other lens exists.",
]

LENS_OLD = [
    "Exactly one lens is assigned to you for this run (named in the prompt above).",
    "The assignment ROTATES by iteration number over a pool of six, so do not "
    "assume the lens you had last time; read the one named in your prompt.",
    "Stay inside the single lens you were assigned.",
    "A candidate belonging to any DIFFERENT lens in the pool is out of scope for "
    "you -- the PM lead reads a second scout's slate for that -- and a slate "
    "that wanders is graded down.",
    '"new-capability" -- propose features that add NEW user-facing capability',
    '"narrative-and-docs" -- propose features that make the product EXPLAIN '
    "itself correctly",
]


@pytest.mark.parametrize("sentence", PM_1B_OLD)
def test_eb6_pm_1b_old_sentences_verbatim(pm_1b, sentence):
    assert _norm(sentence) in _norm(pm_1b)


@pytest.mark.parametrize("sentence", LENS_OLD)
def test_eb6_lens_old_sentences_verbatim(lens, sentence):
    assert _norm(sentence) in _norm(lens)


def test_eb6_pick_label_line_still_present(pm_1b):
    assert "`PICK: **<id>**`" in pm_1b


# --- EB8 negative checks: the extractors CAN fail ---------------------------

_SYNTH_PM = """# ROLE: PM
1. Read things.
1b. **Triage the scout slates when they exist.** Your candidate pool is
    their COMBINED slate. Pick exactly ONE.
2. Write the spec. OPERATOR candidate 1 until it ships (duty 2, out of 1b).
"""

_SYNTH_SCOUT = """# ROLE: scout
## Your assigned lens
Stay inside the single lens you were assigned.
## Next section
OPERATOR candidate 1 regardless of lens.
"""


def test_eb8_negative_1b_extractor_lacks_operator():
    sec = _section_1b(_SYNTH_PM)
    assert sec.startswith("1b.")
    assert "OPERATOR" not in sec
    assert "candidate 1" not in sec.lower()


def test_eb8_negative_lens_extractor_lacks_operator():
    sec = _lens_section(_SYNTH_SCOUT)
    assert sec.startswith("## Your assigned lens")
    assert "OPERATOR" not in sec
    assert "regardless of" not in sec.lower()


def test_eb8_negative_missing_section_is_empty():
    assert _section_1b("# no duty here\n2. two\n") == ""
    assert _lens_section("# nothing\n## Other\n") == ""


# --- import safety (quality bar) --------------------------------------------

def test_import_foundry_and_dispatcher_fresh_interpreter():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
