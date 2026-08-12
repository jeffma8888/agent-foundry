"""Black-box behaviour tests for iter 163 -- `roles/engineer.md` and `roles/fix.md`
each carry ONE RUNNABLE `save-work` checkpoint invocation, so the iter-162 rescue
verb finally has a consumer at the two seats that leave an uncommitted
implementation behind, immediately before the stage most often killed.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-163 PM spec's Expected
Behaviors 1-10, the conventions found under `tests/`, and the product's own
OBSERVABLE surface (importing the public names and calling them).  The two role
cards are the DELIVERABLE under test, and they are read by the assertions here,
never quoted from the engineer's notes -- the iter-142/157 convention.
`foundry.py` / `dispatcher.py` SOURCE was not read: `foundry.py`'s bytes are fed
to `foundry_cli_verbs` as opaque INPUT DATA.  Neither the engineer's notes, the
reviewer's notes, nor any `git diff` was consulted.

Every test here is OFFLINE: no subprocess, git, clone or network call, and -- per
the 2026-08-11 operator rule -- no assertion depends on gitignored local state.
The only ambient files read are git-TRACKED ones the spec names (`roles/*.md`,
`foundry.py` as opaque input bytes).
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402

THIS_ITER = 163

ROLES_DIR = _ROOT / "roles"
FOUNDRY_SRC = _ROOT / "foundry.py"
ENGINEER_CARD = ROLES_DIR / "engineer.md"
FIX_CARD = ROLES_DIR / "fix.md"
FINAL_CARD = ROLES_DIR / "final.md"
EDITED_CARDS = (ENGINEER_CARD, FIX_CARD)
CARD_IDS = tuple(c.name for c in EDITED_CARDS)

# behavior 1 -- the three tokens that together make the invocation RUNNABLE from
# inside a stage (the `foundry` command is NOT on PATH there).
RUNNABLE_TOKENS = ("python3", "foundry.py save-work", "--config")

# behavior 6 -- exit 2 is the BENIGN clean-tree outcome, not the stage's failure.
# The status is matched as an ISOLATED 2: a plain "2" substring would also be
# satisfied by "2026-08-12" or "20 reverts", neither of which says anything about
# an exit code, so the loose form would be quietly fail-open.
BENIGN_WORDS = ("nothing", "benign")
EXIT_TWO_RE = re.compile(r"(?<![0-9])2(?![0-9])")

# behavior 7 -- the Context line is not guaranteed, so a derivation fallback is
# mandatory; `roles/final.md` already ships this two-branch wording shape.
FALLBACK_MARKERS = ("fall back", "fallback", "no such line", "if absent", "otherwise", "else")

# behavior 8 -- a checkpoint that may be repeated, never a final snapshot.
REPEAT_MARKERS = ("repeat", "again", "re-run", "rerun", "stale", "last one wins", "overwrit")

# behavior 9 -- both strings were read off disk in the PM stage.  engineer.md
# uses U+2014 EM DASH, so a literal-ASCII assertion would fail on the real file.
ENGINEER_COMMIT_LINE = "- Commit nothing \u2014 the Final Reviewer owns git."
FIX_COMMIT_PREFIX = "- Commit nothing."
GIT_WRITE_COMMANDS = ("git add", "git commit", "git push")


def _text(card: pathlib.Path) -> str:
    return card.read_text(encoding="utf-8")


def runnable_save_work_lines(text: str) -> list:
    """PURE detector, proven two-sided by behavior 5: a line instructs a runnable
    `save-work` iff it carries ALL of RUNNABLE_TOKENS."""
    return [ln for ln in text.splitlines() if all(tok in ln for tok in RUNNABLE_TOKENS)]


def _section(text: str) -> str:
    """The whole markdown SECTION that holds the invocation line: from the nearest
    preceding `## ` heading (or file start) to the next `## ` heading (or EOF).

    A fixed +/- N line window is the WRONG shape for a card -- it makes the oracle
    depend on how the author happened to reflow the bullets under the heading, and
    a correct card whose closing bullet sits N+1 lines away reads as red.  A
    section boundary is structural, so it is stable under reflow while still
    LOCAL: wording that lives under a different heading does not count."""
    lines = text.splitlines()
    hits = [i for i, ln in enumerate(lines) if all(t in ln for t in RUNNABLE_TOKENS)]
    if not hits:
        return ""
    lo = 0
    for i in range(hits[0], -1, -1):
        if lines[i].startswith("## "):
            lo = i
            break
    hi = len(lines)
    for i in range(hits[-1] + 1, len(lines)):
        if lines[i].startswith("## "):
            hi = i
            break
    return "\n".join(lines[lo:hi])


def _named_verb(line: str):
    """The verb token immediately after `.../foundry.py` on an invocation line."""
    toks = line.replace("`", " ").split()
    for i, tok in enumerate(toks):
        if tok.endswith("foundry.py"):
            return toks[i + 1] if i + 1 < len(toks) else None
    return None


def _names_benign_exit_two(text: str) -> bool:
    """behavior 6 -- names exit status 2 AND says it is benign / means NOTHING."""
    lower = text.lower()
    return bool(EXIT_TWO_RE.search(text)) and all(w in lower for w in BENIGN_WORDS)


def _verbs():
    """foundry.py's bytes are INPUT DATA for the function under test, never read here."""
    return foundry.foundry_cli_verbs(FOUNDRY_SRC.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# non-vacuity floor -- every ambient file this module reads must be real
# --------------------------------------------------------------------------
def test_the_cards_under_test_exist_and_are_substantial():
    for card in EDITED_CARDS + (FINAL_CARD,):
        assert card.is_file(), card
        assert len(_text(card)) > 500, (card.name, len(_text(card)))


# --------------------------------------------------------------------------
# behaviors 1 + 2 -- each edited card carries a RUNNABLE save-work instruction
# --------------------------------------------------------------------------
@pytest.mark.parametrize("card", EDITED_CARDS, ids=CARD_IDS)
def test_b1_b2_card_has_a_runnable_save_work_invocation(card):
    hits = runnable_save_work_lines(_text(card))
    assert hits, "%s: no line carries all of %r" % (card.name, RUNNABLE_TOKENS)


@pytest.mark.parametrize("card", EDITED_CARDS, ids=CARD_IDS)
def test_b1_b2_each_required_token_is_present_on_one_line(card):
    text = _text(card)
    line = runnable_save_work_lines(text)[0]
    for tok in RUNNABLE_TOKENS:
        assert tok in line, (card.name, tok, line)


# --------------------------------------------------------------------------
# behavior 3 -- neither card introduces a bare-CLI command position
# --------------------------------------------------------------------------
@pytest.mark.parametrize("card", EDITED_CARDS, ids=CARD_IDS)
def test_b3_card_yields_zero_bare_cli_findings(card):
    verbs = _verbs()
    assert len(verbs) >= 20, len(verbs)
    found = foundry.bare_foundry_cli_findings(_text(card), verbs)
    assert found == [], "%s: %r" % (card.name, found)


def test_b3_the_brake_is_two_sided_it_still_fires_on_a_bare_invocation():
    """Control: the green results above must not come from a fail-open matcher."""
    assert foundry.bare_foundry_cli_findings("first run `foundry save-work` here", _verbs())


def test_b3_the_live_brake_over_every_role_card_stays_green():
    verbs = _verbs()
    cards = sorted(p for p in ROLES_DIR.rglob("*.md") if p.is_file())
    assert len(cards) >= 8, len(cards)
    offenders = {}
    for card in cards:
        found = foundry.bare_foundry_cli_findings(_text(card), verbs)
        if found:
            offenders[str(card.relative_to(_ROOT))] = found
    assert offenders == {}, offenders


# --------------------------------------------------------------------------
# behavior 4 -- the verb each card names is a REAL CLI verb (typo -> red)
# --------------------------------------------------------------------------
def test_b4_verb_tuple_is_non_vacuous_and_contains_save_work():
    verbs = _verbs()
    assert len(verbs) >= 20, len(verbs)
    assert "save-work" in verbs, verbs


@pytest.mark.parametrize("card", EDITED_CARDS, ids=CARD_IDS)
def test_b4_the_verb_named_by_the_card_is_a_real_cli_verb(card):
    verbs = _verbs()
    line = runnable_save_work_lines(_text(card))[0]
    verb = _named_verb(line)
    assert verb == "save-work", (card.name, verb, line)
    assert verb in verbs, (card.name, verb)


# --------------------------------------------------------------------------
# behavior 5 -- the detector of behaviors 1-2 is two-sided on in-memory samples
# --------------------------------------------------------------------------
def test_b5_a_card_without_the_instruction_is_reported_missing():
    sample = "# ROLE: Engineer\n\n- Implement the spec.\n- Commit nothing.\n"
    assert runnable_save_work_lines(sample) == []


def test_b5_a_card_with_the_instruction_is_not_reported_missing():
    sample = (
        "# ROLE: Engineer\n\n"
        "Checkpoint: python3 <checkout>/foundry.py save-work --config <PRODUCT_CONFIG>\n"
    )
    assert len(runnable_save_work_lines(sample)) == 1


@pytest.mark.parametrize("dropped", RUNNABLE_TOKENS)
def test_b5_dropping_any_single_required_token_is_reported_missing(dropped):
    line = "Checkpoint: python3 <checkout>/foundry.py save-work --config <PRODUCT_CONFIG>"
    assert runnable_save_work_lines(line.replace(dropped, "X")) == [], dropped


# --------------------------------------------------------------------------
# behavior 6 -- exit 2 (`NOTHING`) is named BENIGN, not the stage's failure
# --------------------------------------------------------------------------
@pytest.mark.parametrize("card", EDITED_CARDS, ids=CARD_IDS)
def test_b6_card_names_the_benign_exit_two_outcome_on_one_line(card):
    """Per-LINE: prose that is right in meaning but split across a line boundary
    reads as a separate claim about a separate status."""
    hits = [ln for ln in _text(card).splitlines() if _names_benign_exit_two(ln)]
    assert hits, "%s: no single line names exit 2 AND %r" % (card.name, BENIGN_WORDS)


@pytest.mark.parametrize("card", EDITED_CARDS, ids=CARD_IDS)
def test_b6_the_benign_wording_sits_in_the_invocation_section(card):
    section = _section(_text(card))
    assert section, card.name
    assert _names_benign_exit_two(section), card.name


def test_b5_the_section_extractor_is_local_not_whole_file():
    """Control: the section scope used by behaviors 6-8 must not silently widen to
    the whole card, or wording under an unrelated heading would satisfy them."""
    sample = "\n".join([
        "## OTHER",
        "you may repeat this checkpoint whenever you like",
        "## SAVE-WORK",
        "run python3 <checkout>/foundry.py save-work --config <PRODUCT_CONFIG>",
        "## AFTER",
        "config.json lives elsewhere",
    ])
    section = _section(sample)
    assert "save-work" in section
    assert "OTHER" not in section, section
    assert "repeat" not in section, section
    assert "AFTER" not in section, section


def test_b5_the_section_extractor_returns_empty_when_there_is_no_invocation():
    assert _section("## A\nno invocation here\n") == ""


def test_b6_the_benign_detector_is_two_sided():
    assert not _names_benign_exit_two("exit 0 means SAVED, exit 1 means FAILED")
    assert not _names_benign_exit_two("measured 2026-08-12: 20 reverts, nothing benign")
    assert _names_benign_exit_two("exit 2 (save-work: NOTHING) is BENIGN, not a failure")


# --------------------------------------------------------------------------
# behavior 7 -- a config-path FALLBACK, because the Context line is not
# guaranteed in a live stage prompt (the running brain predates iter 157)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("card", EDITED_CARDS, ids=CARD_IDS)
def test_b7_card_names_the_context_line_source(card):
    near = _section(_text(card)).lower()
    assert near, card.name
    assert "context" in near, card.name


@pytest.mark.parametrize("card", EDITED_CARDS, ids=CARD_IDS)
def test_b7_card_names_a_derivation_fallback(card):
    near = _section(_text(card)).lower()
    assert near, card.name
    assert "config.json" in near, card.name
    assert any(m in near for m in FALLBACK_MARKERS), (card.name, FALLBACK_MARKERS)


def test_b7_the_mirrored_wording_shape_exists_in_final_card():
    """Non-vacuity for 'mirroring roles/final.md': that card really does ship a
    two-branch config-path clause, so the shape being copied is real."""
    text = _text(FINAL_CARD).lower()
    assert "context" in text
    assert any(m in text for m in FALLBACK_MARKERS)


# --------------------------------------------------------------------------
# behavior 8 -- presented as a REPEATABLE checkpoint, not a final snapshot
# --------------------------------------------------------------------------
@pytest.mark.parametrize("card", EDITED_CARDS, ids=CARD_IDS)
def test_b8_card_frames_the_call_as_a_repeatable_checkpoint(card):
    near = _section(_text(card)).lower()
    assert near, card.name
    assert "checkpoint" in near, card.name
    assert any(m in near for m in REPEAT_MARKERS), (card.name, REPEAT_MARKERS)


# --------------------------------------------------------------------------
# behavior 9 -- the existing commit prohibition survives VERBATIM, and no card
# instructs a git write.  The two strings DIFFER; assert each as it really is.
# --------------------------------------------------------------------------
def test_b9_engineer_commit_prohibition_survives_verbatim_with_its_em_dash():
    lines = [ln.strip() for ln in _text(ENGINEER_CARD).splitlines()]
    assert ENGINEER_COMMIT_LINE in lines, \
        "roles/engineer.md lost %r" % (ENGINEER_COMMIT_LINE,)


def test_b9_engineer_prohibition_really_uses_u2014_not_two_hyphens():
    """Control on the assertion above: the literal-ASCII form must NOT be there."""
    ascii_form = ENGINEER_COMMIT_LINE.replace("\u2014", "--")
    assert ascii_form not in _text(ENGINEER_CARD)


def test_b9_fix_commit_prohibition_survives_and_has_no_reviewer_clause():
    lines = [ln.strip() for ln in _text(FIX_CARD).splitlines()]
    assert any(ln.startswith(FIX_COMMIT_PREFIX) for ln in lines), \
        "roles/fix.md lost %r" % (FIX_COMMIT_PREFIX,)


@pytest.mark.parametrize("card", EDITED_CARDS, ids=CARD_IDS)
def test_b9_no_card_instructs_a_git_write(card):
    lower = _text(card).lower()
    for cmd in GIT_WRITE_COMMANDS:
        assert cmd not in lower, (card.name, cmd)


# --------------------------------------------------------------------------
# behavior 10 -- the control path is untouched: both modules still import
# --------------------------------------------------------------------------
def test_b10_foundry_and_dispatcher_are_importable_from_the_repo():
    assert pathlib.Path(foundry.__file__).resolve() == FOUNDRY_SRC.resolve()
    assert pathlib.Path(dispatcher.__file__).resolve() == (_ROOT / "dispatcher.py").resolve()


def test_b10_the_public_names_this_iteration_relies_on_are_still_callable():
    for name in ("foundry_cli_verbs", "bare_foundry_cli_findings"):
        assert callable(getattr(foundry, name)), name
