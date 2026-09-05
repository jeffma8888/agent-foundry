"""Iteration 233 -- BLACK-BOX behavior tests: the deciding seats are told their own
decision log is an INPUT, and every runnable-form CLI verb a role card names must be a
verb the CLI actually accepts.

Spec under test (products/_platform/state/iter-233/pm.md), Expected Behaviors 1-5:
   1. DIRECTION IS STATED IN BOTH CARDS -- ``roles/pm_scout.md`` and ``roles/pm.md``
      each contain the exact anchor phrase ``DIRECTIONS.md is an INPUT``.
   2. THE INSTRUCTION IS BOUNDED -- every markdown code span in every ``roles/*.md``
      whose text contains ``foundry.py directions`` also contains ``--limit``; at
      least two such spans exist (one per edited card).
   3. IT CANNOT DELAY A CHECKPOINT -- in ``roles/pm_scout.md`` the anchor phrase's
      first index is strictly GREATER than the ``## WRITE-EARLY`` heading's index.
   4. RUNNABLE-FORM CLI REACHABILITY (the new brake) -- every verb token immediately
      following ``foundry.py`` inside a code span of any ``roles/*.md`` is a member of
      ``foundry.foundry_cli_verbs(<text of foundry.py>)``.  Proved non-vacuous (>= 8
      (card, verb) pairs over the live cards) and failable (a planted
      ``python3 x/foundry.py no-such-verb`` span yields exactly that verb, which is
      NOT in the verb set).
   5. NO REGRESSION, NO NEW LEAK SHAPE -- ``foundry.bare_foundry_cli_findings(<card
      text>, foundry.foundry_cli_verbs(<text of foundry.py>))`` (TWO args, returns a
      LIST) is EMPTY for both edited cards, and neither edited card nor this test
      module contains an absolute machine-home-path shape.  The shape is assembled
      from pieces at runtime and proved STILL-DETECTING against a synthetic string
      (iteration 232 tester lesson: a leak assertion that can match its own source
      text is not an assertion).

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-233 PM spec, the
conventions of ``tests/``, and the product's OWN OBSERVABLE surface -- importing
``foundry`` and calling its two ALREADY-SHIPPED public oracles.  I did not read the
implementation source of ``foundry.py`` (it is passed to the oracle as opaque TEXT,
read programmatically inside the tests), nor ``engineer.md``, ``reviewer.md`` or
``git diff``.

Every path used below is GIT-TRACKED repo content (``roles/*.md``, ``foundry.py``), so
these preconditions hold in a throwaway fresh clone -- OPERATOR 2026-08-11: a shipped
iteration went post-release BROKEN on a precondition that was only true in one working
tree.  No subprocess, no git, no network, no clock.
"""

import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

_ROLES_DIR = _ROOT / "roles"
_EDITED_CARDS = ("pm_scout.md", "pm.md")

# Behavior 1's anchor phrase, that spelling, capitalised INPUT.
_ANCHOR = "DIRECTIONS.md is an INPUT"

# A markdown code span: a run of N backticks, content, the SAME run again
# (CommonMark's rule), which also covers a fenced block.
_SPAN_RE = re.compile(r"(`+)(.+?)\1", re.S)

# Behavior 4's extractor: the token immediately following `foundry.py`.
_VERB_AFTER_FOUNDRY_PY = re.compile(r"foundry\.py\s+([A-Za-z][A-Za-z0-9-]*)")


def _card_text(name):
    return (_ROLES_DIR / name).read_text(encoding="utf-8")


def _all_cards():
    """{name: text} for every role card -- sorted, so failures are deterministic."""
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(_ROLES_DIR.glob("*.md"))}


def _code_spans(text):
    """Every markdown code span's inner text, in document order."""
    return [m.group(2) for m in _SPAN_RE.finditer(text)]


def _cli_verb_pairs(cards):
    """PURE: [(card_name, verb)] for every runnable-form verb named in a code span."""
    pairs = []
    for name in sorted(cards):
        for span in _code_spans(cards[name]):
            for verb in _VERB_AFTER_FOUNDRY_PY.findall(span):
                pairs.append((name, verb))
    return pairs


def _foundry_source_text():
    """The CLI's own text, read as OPAQUE input for the shipped oracle."""
    return (_ROOT / "foundry.py").read_text(encoding="utf-8")


def _verb_set():
    return foundry.foundry_cli_verbs(_foundry_source_text())


# The banned absolute-home-path SHAPE, assembled from pieces so that this module can
# never match itself (iteration 205 was reverted for typing this literal in a test).
_HOME_PATH_RE = re.compile("/" + "(?:Users|home|root)" + "/" + "[A-Za-z0-9_.-]+")


# ==========================================================================
# Behavior 1 -- the direction is stated in BOTH deciding cards
# ==========================================================================
def test_b1_both_deciding_cards_state_that_the_log_is_an_input():
    for name in _EDITED_CARDS:
        text = _card_text(name)
        assert _ANCHOR in text, (
            f"roles/{name} must contain the exact anchor phrase {_ANCHOR!r}"
        )
    # roles/pm.md named DIRECTIONS zero times before this iteration; it must now.
    assert "DIRECTIONS" in _card_text("pm.md")


def test_b1_the_anchor_assertion_is_failable():
    """The same predicate over a card with the phrase deleted must be FALSE, so a
    green behavior 1 is evidence about the tree and not a tautology."""
    for name in _EDITED_CARDS:
        without = _card_text(name).replace(_ANCHOR, "the log is downstream of me")
        assert _ANCHOR not in without, f"mutant of roles/{name} still matches"


# ==========================================================================
# Behavior 2 -- the instruction is BOUNDED (no unbounded 1,238-line page)
# ==========================================================================
def test_b2_every_directions_invocation_span_carries_a_limit():
    cards = _all_cards()
    hits = []
    for name in sorted(cards):
        for span in _code_spans(cards[name]):
            if "foundry.py directions" in span:
                hits.append((name, span))
                assert "--limit" in span, (
                    f"roles/{name} names an UNBOUNDED directions read: {span!r}"
                )
    # Non-vacuity, asserted explicitly: at least two such spans, one per edited card.
    assert len(hits) >= 2, f"expected >= 2 bounded directions spans, got {hits!r}"
    naming = {name for name, _ in hits}
    for name in _EDITED_CARDS:
        assert name in naming, f"roles/{name} names no bounded directions invocation"


def test_b2_the_bounded_check_is_failable():
    """An unbounded span in the same shape must be reported by the same predicate."""
    planted = "python3 x/foundry.py directions --config c.json"
    spans = _code_spans(f"a card line: `{planted}` and prose\n")
    matched = [s for s in spans if "foundry.py directions" in s]
    assert matched == [planted]
    assert "--limit" not in matched[0], "the negative fixture must be UNbounded"


# ==========================================================================
# Behavior 3 -- the new duty cannot delay the write-early checkpoint
# ==========================================================================
def test_b3_the_new_duty_follows_the_write_early_section():
    text = _card_text("pm_scout.md")
    heading = text.find("## WRITE-EARLY")
    anchor = text.find(_ANCHOR)
    assert heading >= 0, "roles/pm_scout.md lost its ## WRITE-EARLY heading"
    assert anchor >= 0, "roles/pm_scout.md lacks the anchor phrase"
    assert anchor > heading, (
        "the DIRECTIONS duty is placed BEFORE the write-early checkpoint "
        f"(anchor at {anchor}, ## WRITE-EARLY at {heading})"
    )


# ==========================================================================
# Behavior 4 -- runnable-form CLI reachability (the new brake)
# ==========================================================================
def test_b4_every_runnable_form_verb_a_card_names_is_accepted_by_the_cli():
    verbs = _verb_set()
    assert isinstance(verbs, tuple) and verbs, "foundry_cli_verbs returned no verbs"
    pairs = _cli_verb_pairs(_all_cards())
    # Non-vacuity: the extractor must actually find the cards' instructions.
    assert len(pairs) >= 8, (
        f"extractor found only {len(pairs)} (card, verb) pairs: {pairs!r}"
    )
    unreachable = [(c, v) for c, v in pairs if v not in verbs]
    assert unreachable == [], (
        "role card(s) order a verb the CLI does not accept: "
        f"{unreachable!r} (accepted verbs: {len(verbs)})"
    )


def test_b4_the_brake_is_failable_on_a_planted_bad_verb():
    verbs = _verb_set()
    planted = {"planted.md": "Run `python3 x/foundry.py no-such-verb` now.\n"}
    pairs = _cli_verb_pairs(planted)
    assert [v for _, v in pairs] == ["no-such-verb"], f"extractor gave {pairs!r}"
    assert "no-such-verb" not in verbs
    unreachable = [(c, v) for c, v in pairs if v not in verbs]
    assert unreachable == [("planted.md", "no-such-verb")]


def test_b4_the_extractor_ignores_prose_and_flags():
    """Only a code span counts, and only a verb-shaped token counts."""
    assert _cli_verb_pairs({"a.md": "prose says foundry.py directions here\n"}) == []
    assert _cli_verb_pairs({"a.md": "`python3 foundry.py --help`\n"}) == []
    assert _cli_verb_pairs({"a.md": "`python3 p/foundry.py lint-spec x`\n"}) == [
        ("a.md", "lint-spec")
    ]


# ==========================================================================
# Behavior 5 -- no regression, no new leak shape
# ==========================================================================
def test_b5_the_edited_cards_introduce_no_bare_foundry_form():
    verbs = _verb_set()
    for name in _EDITED_CARDS:
        findings = foundry.bare_foundry_cli_findings(_card_text(name), verbs)
        assert isinstance(findings, list), "the oracle must return a LIST"
        assert findings == [], f"roles/{name} gained a bare `foundry <verb>` form: {findings!r}"


def test_b5_no_absolute_home_path_shape_in_the_edited_cards_or_this_module():
    # The detector must still detect -- proved on a string assembled from pieces.
    synthetic = "/" + "Users" + "/somebody/projects/x"
    assert _HOME_PATH_RE.search(synthetic), "the leak detector stopped detecting"
    assert _HOME_PATH_RE.search("/" + "home" + "/somebody/x")

    targets = {f"roles/{n}": _card_text(n) for n in _EDITED_CARDS}
    targets["tests/" + pathlib.Path(__file__).name] = pathlib.Path(__file__).read_text(
        encoding="utf-8"
    )
    for label, text in sorted(targets.items()):
        found = _HOME_PATH_RE.findall(text)
        assert found == [], f"{label} carries an absolute machine-path shape: {found!r}"
