"""Black-box behaviour tests for iter 324 -- the WIDENED pure parser
`foundry.parse_triage_winner(text) -> str | None`, which now resolves a
SCOUT-QUALIFIED winner reference ("PM_SCOUT_B Candidate 1", "scout A candidate
C", "scout-A H1") instead of returning None, so the loop's own decision log can
name what BEAT the field instead of only what was considered.

Two rules, applied IN ORDER to the text after a `## Triage` heading, first match
wins:
  * Rule 1 (unchanged, runs FIRST): first `\b[ABC][0-9]\b`, uppercased.
  * Rule 2 (NEW, SCOUT-QUALIFIED ONLY): a case-insensitive `scout` keyword, one
    or more separators, a single-letter designator, then EITHER (2a) a
    `candidate` keyword plus `[A-Z1-9]` within 40 same-line chars -> composed
    `<DESIGNATOR><index>` (letter -> 1-based alphabet position), OR (2b) an
    explicit `\b[A-Z][0-9]\b` token within 20 same-line chars -> returned
    VERBATIM.
An UNQUALIFIED letter+digit token must STILL yield None: a wrong winner is
strictly worse than `unknown`, because it silently misreports history.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-324 PM
spec's Expected Behaviors (1-9), the `tests/` conventions (esp. the five
`test_b03_*` tests in tests/test_iter115_behavior.py, which own this same
function and are this iteration's zero-regression oracle, and
tests/test_iter323_behavior.py for the current header/import shape), and the
product's OWN OBSERVABLE behaviour, obtained by CALLING its public function.
The implementation source of foundry.py / dispatcher.py was NOT read by this
author, nor were the engineer's notes, the reviewer's notes, or `git diff`.

Fully offline and deterministic: EVERY fixture is a PURE IN-MEMORY STRING. No
test here reads `DIRECTIONS.md`, any `products/*/state/` path, or ANY ambient
repo file (the iter-154 fresh-clone trap and the iter-178 revert), and there is
zero subprocess, git, network, clock-dependence or tmp_path -- except the
documented `import foundry, dispatcher` regression probe and one coarse
upper-bound timing assertion (Behavior 9) that only fails if the parser hangs.
"""
from __future__ import annotations

import pathlib
import sys
import time

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


def winner(text):
    """Drive the PUBLIC parser exactly as the reporting path does."""
    return foundry.parse_triage_winner(text)


# ==========================================================================
# Behavior 1 -- Rule 1 is preserved EXACTLY (the zero-regression contract)
# ==========================================================================
@pytest.mark.parametrize(
    "text,expected",
    [
        ("## Triage\n**Pick: C1 (Scout A)** for sequencing reasons.\n\n"
         "## Feature\nbody mentioning A4 later\n", "C1"),
        ("## triage\nPick: B2\n", "B2"),
        ("Candidate A9 was rejected earlier in prose.\n## Triage\nPick: C1\n", "C1"),
    ],
)
def test_b1_rule_one_ids_resolve_exactly_as_before(text, expected):
    assert winner(text) == expected


def test_b1_rule_one_beats_a_scout_qualified_phrase_in_the_same_text():
    t = "## Triage\nPick: B2, over PM_SCOUT_A Candidate C\n"
    assert winner(t) == "B2"


def test_b1_rule_ones_id_class_stays_uppercase_only():
    # The spec's "uppercased" describes the RETURNED token, not a case-insensitive
    # id class ("a blanket re.IGNORECASE would let lowercase prose satisfy the
    # deliberately uppercase-only id classes"). Measured on the PREVIOUS RELEASE
    # too: a lowercase bare id was None before this iteration and is None now, so
    # this asserts an UNCHANGED property, not a new one.
    assert winner("## Triage\nPick: c1 for sequencing.\n") is None
    # ... but a lowercase DESIGNATOR is uppercased when Rule 2 composes the id.
    assert winner("## Triage\nPick: v (scout a candidate 2)\n") == "A2"


# ==========================================================================
# Behavior 2 -- a worded scout+candidate reference COMPOSES the id
# ==========================================================================
@pytest.mark.parametrize(
    "text,expected",
    [
        ("## Triage\n**PICK: PM_SCOUT_B Candidate 1** -- x\n", "B1"),
        ("## Triage\nPick: scout B candidate A -- x\n", "B1"),
        ("## Triage\n**PICK: scout A candidate C** -- x\n", "A3"),
        ("## Triage\nPICK: PM_SCOUT_A Candidate A\n", "A1"),
    ],
)
def test_b2_worded_scout_candidate_composes(text, expected):
    assert winner(text) == expected


# ==========================================================================
# Behavior 3 -- separator, punctuation and case variants all compose
# ==========================================================================
@pytest.mark.parametrize(
    "text,expected",
    [
        ("## Triage\n**Pick: v** (PM_SCOUT_A candidate #2 -- x)\n", "A2"),
        ("## Triage\nPICK: PM_SCOUT_B\'s Candidate B -- x\n", "B2"),
        ("## Triage\n**PICK: SCOUT B candidate 2** -- x\n", "B2"),
        ("## Triage\n**Pick: v** (Scout B, candidate 1).\n", "B1"),
    ],
)
def test_b3_separator_and_case_variants_compose(text, expected):
    assert winner(text) == expected


# ==========================================================================
# Behavior 4 -- a scout-qualified explicit id OUTSIDE [ABC] is VERBATIM
# ==========================================================================
@pytest.mark.parametrize(
    "text,expected",
    [
        ("## Triage\n**PICK: scout-A H1** -- x\n", "H1"),
        ("## Triage\n**PICK: scout B\'s I1** -- x\n", "I1"),
        ("## Triage\n**PICK: scout B\'s candidate S1 -- x**\n", "S1"),
    ],
)
def test_b4_scout_qualified_explicit_id_is_returned_verbatim(text, expected):
    assert winner(text) == expected


# ==========================================================================
# Behavior 5 -- an UNQUALIFIED letter+digit token outside [ABC] is still None
# ==========================================================================
@pytest.mark.parametrize(
    "text",
    [
        "## Triage\nPICK: roadmap #218 -- pin the H1 distribution mode.\n",
        "## Triage\nsee H1 and L0 and S3 in the prose below.\n",
    ],
)
def test_b5_unqualified_letter_digit_token_is_not_a_winner(text):
    assert winner(text) is None


# ==========================================================================
# Behavior 6 -- all five real "no winner" shapes keep returning None
# ==========================================================================
@pytest.mark.parametrize(
    "text",
    [
        "## Triage\n**HOTFIX FLAG PRESENT, so there is no candidate contest.**\n",
        "## Triage\n**No scout candidate won, so a `winner: unknown` record is "
        "CORRECT here.**\n",
        "## Triage\nNo hotfix flag, and no scout slates in this state dir -- a "
        "straight PM pick.\n",
        "## Triage\n**PICK: a new roadmap row 96 -- this overrides both scout "
        "slates.**\n",
        "## Triage\nPICK: roadmap #218, first and possibly ONLY slice -- pin the "
        "mode.\n",
    ],
)
def test_b6_real_no_winner_shapes_stay_none(text):
    assert winner(text) is None


# ==========================================================================
# Behavior 7 -- plural/prose guard: >=1 separator before a 1-letter designator
# ==========================================================================
@pytest.mark.parametrize(
    "text",
    [
        "## Triage\nscouts proposed candidate 2 each\n",
        "## Triage\nScout slates present. Scout A delivered a measured slate of "
        "three.\n",
    ],
)
def test_b7_plural_and_bare_designator_prose_stay_none(text):
    assert winner(text) is None


# ==========================================================================
# Behavior 8 -- binding is SAME-LINE and BOUNDED
# ==========================================================================
def test_b8_a_candidate_on_a_later_line_does_not_bind():
    t = ("## Triage\nScout A was cap-killed at 600s.\n\n"
         "So I took candidate 2 from the roadmap.\n")
    assert winner(t) is None


def test_b8_a_candidate_beyond_the_same_line_budget_does_not_bind():
    t = "## Triage\nScout A " + "x" * 60 + " candidate 1\n"
    assert winner(t) is None


# ==========================================================================
# Behavior 9 -- totality: pure, total, never raises, heading rule unchanged
# ==========================================================================
@pytest.mark.parametrize(
    "bad",
    [
        None,
        "",
        "\x00## Triage\x00",
        "## Triage",
        "#" * 4000,
        "no triage here\nPick: C1",
        "no heading\nPM_SCOUT_B Candidate 1",
    ],
)
def test_b9_adversarial_and_headingless_inputs_return_none(bad):
    assert winner(bad) is None


def test_b9_result_is_always_none_or_str_and_the_parser_is_pure():
    fixtures = (
        "## Triage\nPick: C1\n",
        "## Triage\n**PICK: PM_SCOUT_B Candidate 1** -- x\n",
        "## Triage\nnothing here\n",
        "",
    )
    for t in fixtures:
        first = winner(t)
        assert first is None or isinstance(first, str)
        # pure: same input, same answer, no accumulated state
        assert winner(t) == first


def test_b9_does_not_hang_on_a_large_pathological_body():
    big = "## Triage\n" + "scout " * 40000 + "\n"
    started = time.monotonic()
    assert winner(big) is None
    assert time.monotonic() - started < 10.0


# ==========================================================================
# Regression probe -- the two modules still import (design invariant)
# ==========================================================================
def test_modules_still_import_and_expose_the_parser():
    assert callable(foundry.parse_triage_winner)
    assert pathlib.Path(dispatcher.__file__).name == "dispatcher.py"
