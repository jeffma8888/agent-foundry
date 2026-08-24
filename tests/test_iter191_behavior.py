"""Iteration 191 behaviors: two pure functions behind a docs-parity dormancy brake.

Spec: products/_platform/state/iter-191/pm.md, Expected Behaviors 1-12.

   1. `call_site_count(source, *, symbol)` counts CALLS; `x = ship_decision(action=None)`
      is 1.
   2. A `def symbol(...)` statement is NOT a call; nor is a docstring, string-literal or
      `#` comment mention -- all 0.
   3. Attribute calls count and totals add: `foundry.ship_decision(x)` +
      `ship_decision(y)` + `self.ship_decision(z)` is 3 (the callee's TRAILING name).
   4. A different symbol does not match: the same source is 0 for `parse_ship_action`.
   5. Undecidable, never fail-open: source that does not parse returns `None` and does
      NOT raise; `""` returns 0.
   6. `sentinel_dormancy_gaps(doc, *, tokens, symbol, call_sites)` is `()` when every
      token is cited as an exact backticked span AND (for `call_sites == 0`) `DORMANT`
      sits within `SENTINEL_DORMANCY_WINDOW_CHARS` of `symbol` in the collapsed text.
   7. A bare-prose token does not count: `SHIPPED` + backticked RETRY/REVERT + a valid
      claim is exactly `("token-not-cited:SHIP",)`; missing tokens come in `tokens` order.
   8. `call_sites=0`, all tokens cited, claim absent OR farther than the window is
      exactly `("dormant-claim-missing",)`; 50 chars away is accepted, 900 is not.
   9. `call_sites=1` (or any positive count) with the claim still present is exactly
      `("stale-dormant-claim",)`; with the claim removed it is `()`.
  10. `call_sites=None` carries exactly `("call-sites-undecidable",)` for the dormancy
      class; at most ONE dormancy-class gap ever appears.
  11. `SENTINEL_DORMANCY_WINDOW_CHARS` is a module int read INSIDE the function at call
      time, so a `monkeypatch.setattr` moves a subsequent verdict on unchanged input.
  12. Non-vacuous and LIVE: an empty doc yields the three `token-not-cited:` gaps; on the
      real tree `sentinel_dormancy_gaps(ARCHITECTURE.md, tokens=SHIP_DECISION_TOKENS,
      symbol="ship_decision", call_sites=<derived>)` is `()`; both new functions are
      themselves dormant; `python -c "import foundry, dispatcher"` still succeeds.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-191 PM spec's Expected Behaviors,
the conventions of tests/test_iter190_behavior.py and tests/test_iter184_behavior.py, and
the product's OWN OBSERVABLE surface -- calling its public functions and reading its module
constants.  The author did NOT read `foundry.py`'s or `dispatcher.py`'s implementation TEXT,
the engineer's notes, the reviewer's notes, `IMPLEMENTATION.patch`, nor `git diff`.  The two
tracked documents this file reads (`ARCHITECTURE.md`, and the two module SOURCES fed to
`call_site_count` as DATA) are read programmatically as inputs, never inspected by the
author.

Offline and deterministic: no network, no git, no agent run, no sleeps, no clock.  One
subprocess: the spec's literal `python -c "import foundry, dispatcher"` import probe, which
returns in about a second (the module-scope import below is the in-process form of it).
CLONE-SAFETY (OPERATOR 2026-08-11): every path asserted here -- `ARCHITECTURE.md`,
`foundry.py`, `dispatcher.py` -- is TRACKED by git, so this file passes in the throwaway
fresh clone the post-release verifier builds; no assertion touches `products/`, a
`state/iter-NN` dir, `LEARNINGS.md`, `dispatcher.out`, or any other gitignored path.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402,F401  (import-safety probe -- the product quality bar)

THIS_ITER = 191

# The spec's own token vocabulary, spelled out here so the fixtures do not inherit whatever
# the module happens to hold; behavior 12 is the only place the live constant is used.
TOKENS = ("SHIP", "RETRY", "REVERT")

# The two modules whose call sites decide the dormancy verdict, and the document under it.
_MODULES = ("foundry.py", "dispatcher.py")
_ARCH_NAME = "ARCHITECTURE.md"

DORMANCY_CLASS = ("dormant-claim-missing", "stale-dormant-claim", "call-sites-undecidable")


# ------------------------------------------------------------------ fixtures


def _cited(tokens=TOKENS):
    """Every token as an EXACT backticked span, which is the only citation that counts."""
    return " ".join("`" + t + "`" for t in tokens)


def _doc(gap=10, *, symbol="ship_decision", tokens=TOKENS, claim=True):
    """Cites every token, then names `symbol`, then puts `DORMANT` `gap`+2 collapsed
    characters later.  `claim=False` drops the literal entirely (lower-case prose only,
    since the match is case-SENSITIVE)."""
    body = _cited(tokens) + " " + symbol
    if claim:
        return body + " " + ("x" * gap) + " DORMANT"
    return body + " is wired at one live call site and the note is gone"


def _gaps(doc, *, tokens=TOKENS, symbol="ship_decision", call_sites=0):
    return foundry.sentinel_dormancy_gaps(doc, tokens=tokens, symbol=symbol,
                                          call_sites=call_sites)


def _token_gaps(tokens=TOKENS):
    return tuple("token-not-cited:" + t for t in tokens)


def _read(name):
    return (_ROOT / name).read_text(encoding="utf-8")


def _derived_call_sites(symbol):
    """Sum `call_site_count` over the two live modules, propagating undecidability."""
    total = 0
    for mod in _MODULES:
        n = foundry.call_site_count(_read(mod), symbol=symbol)
        if n is None:
            return None
        total += n
    return total


def _dormancy_members(gaps):
    return [g for g in gaps if g in DORMANCY_CLASS]


# =====================================================================
# Behavior 1 -- call_site_count counts CALLS
# =====================================================================
def test_b1_the_specs_own_example_counts_one():
    src = "x = ship_decision(action=None)\n"
    assert foundry.call_site_count(src, symbol="ship_decision") == 1


def test_b1_two_calls_count_two():
    src = "ship_decision(1)\nship_decision(2)\n"
    assert foundry.call_site_count(src, symbol="ship_decision") == 2


def test_b1_a_call_nested_inside_a_function_body_still_counts():
    src = "def outer():\n    return ship_decision(action=None)\n"
    assert foundry.call_site_count(src, symbol="ship_decision") == 1


def test_b1_the_count_is_a_plain_int_never_a_bool():
    n = foundry.call_site_count("ship_decision(1)", symbol="ship_decision")
    assert isinstance(n, int) and not isinstance(n, bool), type(n).__name__


def test_b1_is_deterministic_across_repeat_calls():
    src = "ship_decision(1)\nfoundry.ship_decision(2)\n"
    first = foundry.call_site_count(src, symbol="ship_decision")
    assert first == foundry.call_site_count(src, symbol="ship_decision") == 2


# =====================================================================
# Behavior 2 -- a def, a docstring, a string literal and a comment are NOT calls
# =====================================================================
def test_b2_a_def_statement_is_not_a_call():
    src = "def ship_decision(a): return a\n"
    assert foundry.call_site_count(src, symbol="ship_decision") == 0


def test_b2_a_docstring_mention_is_not_a_call():
    src = '"""ship_decision(x) is described here."""\n'
    assert foundry.call_site_count(src, symbol="ship_decision") == 0


def test_b2_a_string_literal_mention_is_not_a_call():
    src = 's = "ship_decision(1)"\n'
    assert foundry.call_site_count(src, symbol="ship_decision") == 0


def test_b2_a_comment_mention_is_not_a_call():
    src = "# ship_decision(2)\n"
    assert foundry.call_site_count(src, symbol="ship_decision") == 0


def test_b2_all_three_non_call_mentions_together_are_still_zero():
    src = ('"""ship_decision is mentioned here."""\n'
           'def ship_decision(a):\n'
           '    """ship_decision(a) again."""\n'
           '    s = "ship_decision(1)"\n'
           '    # ship_decision(2)\n'
           '    return s\n')
    assert foundry.call_site_count(src, symbol="ship_decision") == 0


def test_b2_a_def_PLUS_a_real_call_counts_only_the_call():
    """Two-sided: proves the def is EXCLUDED rather than the whole source ignored."""
    src = "def ship_decision(a): return a\n\nx = ship_decision(1)\n"
    assert foundry.call_site_count(src, symbol="ship_decision") == 1


def test_b2_a_bare_name_reference_without_parens_is_not_a_call():
    src = "handler = ship_decision\n"
    assert foundry.call_site_count(src, symbol="ship_decision") == 0


# =====================================================================
# Behavior 3 -- attribute calls count; the callee's TRAILING name matches
# =====================================================================
SRC_THREE = ("foundry.ship_decision(x)\n"
             "ship_decision(y)\n"
             "self.ship_decision(z)\n")


def test_b3_the_specs_own_three_call_source_counts_three():
    assert foundry.call_site_count(SRC_THREE, symbol="ship_decision") == 3


def test_b3_a_call_through_a_deeper_owner_chain_still_counts():
    src = "pkg.mod.helper.ship_decision(x)\n"
    assert foundry.call_site_count(src, symbol="ship_decision") == 1


def test_b3_an_owner_named_like_the_symbol_is_not_itself_a_call_site():
    """`ship_decision.other(x)` calls `other`, not `ship_decision`."""
    src = "ship_decision.other(x)\n"
    assert foundry.call_site_count(src, symbol="ship_decision") == 0


# =====================================================================
# Behavior 4 -- a different symbol does not match
# =====================================================================
def test_b4_the_three_call_source_is_zero_for_a_different_symbol():
    assert foundry.call_site_count(SRC_THREE, symbol="parse_ship_action") == 0


def test_b4_the_other_direction_also_holds():
    src = "parse_ship_action(text)\nfinal.parse_ship_action(text)\n"
    assert foundry.call_site_count(src, symbol="parse_ship_action") == 2
    assert foundry.call_site_count(src, symbol="ship_decision") == 0


def test_b4_matching_is_whole_name_equality_not_a_substring():
    """A suffixed or prefixed neighbour must not be mistaken for the symbol."""
    src = "ship_decision_v2(x)\ny = my_ship_decision(z)\n"
    assert foundry.call_site_count(src, symbol="ship_decision") == 0


# =====================================================================
# Behavior 5 -- undecidable rather than fail-open
# =====================================================================
def test_b5_unparseable_source_returns_None_and_does_not_raise():
    assert foundry.call_site_count("def (:", symbol="ship_decision") is None


def test_b5_None_is_returned_not_zero_so_undecidable_is_distinguishable():
    """The fail-CLOSED property: an undecidable source must NOT read as `dormant`."""
    got = foundry.call_site_count("def (:", symbol="ship_decision")
    assert got is None
    assert got != 0
    assert foundry.call_site_count("", symbol="ship_decision") == 0


@pytest.mark.parametrize("bad", [
    "def (:",
    "(((",
    "print('unclosed",
    "\x00",                      # ValueError from compile(), not SyntaxError
    "x = 1\n  y = 2\n",          # unexpected indent
    "class:",
    "def f(:\n    pass\n",
])
def test_b5_every_undecidable_source_is_None_and_total(bad):
    assert foundry.call_site_count(bad, symbol="ship_decision") is None


def test_b5_decidability_is_PARSE_level_not_COMPILE_level():
    """FIXTURE CORRECTION, recorded rather than hidden: I first asserted that
    `return ship_decision(1)` at module level is undecidable.  It is not -- a bare
    `return` is rejected by the COMPILER, not by the parser, so the source parses and the
    call is counted.  Pinned deliberately: counting must stay parse-level, because a
    `compile()`-based implementation would return `None` for many valid module FRAGMENTS
    and undecidability is meant to mean 'the text is not Python', not 'not a whole
    module'."""
    assert foundry.call_site_count("return ship_decision(1)\n", symbol="ship_decision") == 1


@pytest.mark.parametrize("ok", ["", "\n", "   \n\t\n", "\u03bb = 1\n", "pass\n"])
def test_b5_parseable_sources_without_the_symbol_are_zero(ok):
    assert foundry.call_site_count(ok, symbol="ship_decision") == 0


# =====================================================================
# Behavior 6 -- the clean verdict
# =====================================================================
def test_b6_a_doc_citing_every_token_with_a_close_claim_is_clean():
    assert _gaps(_doc(), call_sites=0) == ()


def test_b6_the_return_value_is_a_tuple_of_str():
    got = _gaps("", call_sites=0)
    assert isinstance(got, tuple)
    assert all(isinstance(g, str) for g in got), got


def test_b6_matching_is_whitespace_collapsed_so_a_hard_wrapped_doc_is_clean():
    """A markdown paragraph hard-wrapped across lines must still satisfy the window."""
    wrapped = "`SHIP`\n`RETRY`\n`REVERT`\nship_decision\nis\n**DORMANT**\n"
    assert _gaps(wrapped, call_sites=0) == ()


def test_b6_is_deterministic_across_repeat_calls():
    doc = _doc()
    assert _gaps(doc, call_sites=0) == _gaps(doc, call_sites=0) == ()


# =====================================================================
# Behavior 7 -- a bare-prose token is not a citation; order follows `tokens`
# =====================================================================
def test_b7_the_specs_own_fixture_reports_exactly_the_uncited_token():
    doc = "SHIPPED `RETRY` `REVERT` ship_decision is DORMANT"
    assert _gaps(doc, call_sites=0) == ("token-not-cited:SHIP",)


def test_b7_a_longer_backticked_span_does_not_satisfy_the_short_token():
    """The short-token trap: `` `SHIPPED` `` must not count as `` `SHIP` ``."""
    doc = "`SHIPPED` `RETRY` `REVERT` ship_decision is DORMANT"
    assert _gaps(doc, call_sites=0) == ("token-not-cited:SHIP",)


def test_b7_citation_matching_is_case_sensitive():
    doc = "`ship` `RETRY` `REVERT` ship_decision is DORMANT"
    assert _gaps(doc, call_sites=0) == ("token-not-cited:SHIP",)


def test_b7_missing_tokens_are_reported_in_tokens_order():
    """FIXTURE CORRECTION: my first version paired an uncited doc that DOES carry a near
    `DORMANT` with `call_sites=1`, so the extra `stale-dormant-claim` was correct
    behaviour, not a defect.  The order claim needs a doc with no claim in it."""
    doc = "ship_decision is wired"
    assert _gaps(doc, call_sites=1) == _token_gaps(TOKENS)


def test_b7_a_reordered_tokens_argument_reorders_the_gaps():
    order = ("REVERT", "SHIP", "RETRY")
    assert _gaps("", tokens=order, call_sites=1) == _token_gaps(order)


def test_b7_token_gaps_come_before_the_dormancy_gap():
    got = _gaps("`SHIP` `RETRY`", call_sites=0)
    assert got == ("token-not-cited:REVERT", "dormant-claim-missing"), got


def test_b7_an_empty_tokens_tuple_contributes_no_token_gaps():
    assert _gaps(_doc(), tokens=(), call_sites=0) == ()


# =====================================================================
# Behavior 8 -- dormant-claim-missing: absent, or outside the window
# =====================================================================
def test_b8_all_tokens_cited_but_no_claim_at_all():
    assert _gaps(_doc(claim=False), call_sites=0) == ("dormant-claim-missing",)


def test_b8_a_claim_fifty_characters_away_is_accepted():
    assert _gaps(_doc(50), call_sites=0) == ()


def test_b8_the_same_claim_nine_hundred_characters_away_is_not():
    assert _gaps(_doc(900), call_sites=0) == ("dormant-claim-missing",)


def test_b8_the_literal_is_matched_case_sensitively():
    doc = _cited() + " ship_decision is dormant"
    assert _gaps(doc, call_sites=0) == ("dormant-claim-missing",)


def test_b8_a_claim_with_no_symbol_anywhere_is_not_a_claim():
    """PROXIMITY, not co-presence -- the reason the window exists at all."""
    doc = _cited() + " the loop is DORMANT somewhere else entirely"
    assert _gaps(doc, call_sites=0) == ("dormant-claim-missing",)


def test_b8_a_far_claim_plus_a_near_one_is_clean():
    """ANY occurrence of the symbol may carry the claim, so a stray far mention of
    `DORMANT` earlier in the document cannot make a valid paragraph red."""
    doc = "DORMANT-UNTIL-DATA " + ("y" * 900) + " " + _doc(5)
    assert _gaps(doc, call_sites=0) == ()


def test_b8_the_window_constant_brackets_the_specs_two_anchors():
    """The spec SUGGESTS 400; behaviors 8's two anchors are what it must satisfy."""
    w = foundry.SENTINEL_DORMANCY_WINDOW_CHARS
    assert isinstance(w, int) and not isinstance(w, bool), type(w).__name__
    assert 52 <= w <= 900, w


# =====================================================================
# Behavior 9 -- a positive call count makes the SAME claim stale
# =====================================================================
def test_b9_one_call_site_with_the_claim_still_present_is_stale():
    assert _gaps(_doc(), call_sites=1) == ("stale-dormant-claim",)


def test_b9_removing_the_claim_makes_a_wired_symbol_clean_again():
    assert _gaps(_doc(claim=False), call_sites=1) == ()


@pytest.mark.parametrize("n", [1, 2, 7, 999])
def test_b9_any_positive_count_is_stale(n):
    assert _gaps(_doc(), call_sites=n) == ("stale-dormant-claim",)


def test_b9_the_same_document_flips_verdict_on_call_sites_alone():
    """Wiring reds the build until the prose is updated -- the whole point of the brake."""
    doc = _doc()
    assert _gaps(doc, call_sites=0) == ()
    assert _gaps(doc, call_sites=1) == ("stale-dormant-claim",)


def test_b9_a_far_away_claim_is_not_stale_because_it_is_not_a_claim():
    """With a positive count, a claim OUTSIDE the window must not be reported stale --
    and must not be reported missing either, since dormancy is no longer expected."""
    assert _gaps(_doc(900), call_sites=1) == ()


# =====================================================================
# Behavior 10 -- undecidable, and at most ONE dormancy-class gap
# =====================================================================
def test_b10_None_call_sites_yields_exactly_the_undecidable_gap():
    assert _gaps(_doc(), call_sites=None) == ("call-sites-undecidable",)


def test_b10_undecidable_wins_even_when_the_claim_is_absent():
    assert _gaps(_doc(claim=False), call_sites=None) == ("call-sites-undecidable",)


def test_b10_undecidable_composes_with_token_gaps_but_stays_a_single_member():
    got = _gaps("", call_sites=None)
    assert got == _token_gaps() + ("call-sites-undecidable",), got
    assert _dormancy_members(got) == ["call-sites-undecidable"]


@pytest.mark.parametrize("call_sites", [0, 1, 2, None])
@pytest.mark.parametrize("doc_key", ["clean", "noclaim", "far", "empty", "partial"])
def test_b10_at_most_one_dormancy_class_gap_for_every_combination(call_sites, doc_key):
    docs = {"clean": _doc(), "noclaim": _doc(claim=False), "far": _doc(900),
            "empty": "", "partial": "`SHIP` ship_decision is DORMANT"}
    got = _gaps(docs[doc_key], call_sites=call_sites)
    assert len(_dormancy_members(got)) <= 1, (doc_key, call_sites, got)


# =====================================================================
# Behavior 11 -- the window is a module global read AT CALL TIME
# =====================================================================
def test_b11_shrinking_the_window_reds_a_previously_clean_doc(monkeypatch):
    doc = _doc(50)
    assert _gaps(doc, call_sites=0) == (), "baseline: 50 chars is inside the real window"
    monkeypatch.setattr(foundry, "SENTINEL_DORMANCY_WINDOW_CHARS", 5)
    assert _gaps(doc, call_sites=0) == ("dormant-claim-missing",)


def test_b11_widening_the_window_greens_a_previously_red_doc(monkeypatch):
    doc = _doc(900)
    assert _gaps(doc, call_sites=0) == ("dormant-claim-missing",), "baseline: 900 is outside"
    monkeypatch.setattr(foundry, "SENTINEL_DORMANCY_WINDOW_CHARS", 5000)
    assert _gaps(doc, call_sites=0) == ()


def test_b11_the_constant_is_restored_after_the_monkeypatched_tests():
    """Guards against a leaked module mutation making a later test vacuous."""
    assert foundry.SENTINEL_DORMANCY_WINDOW_CHARS == 400


# =====================================================================
# Behavior 12 -- non-vacuous by construction, and LIVE on the real tree
# =====================================================================
def test_b12_an_empty_doc_yields_the_three_token_gaps():
    """The spec's literal claim, read with a POSITIVE count -- the only reading under
    which the result is EXACTLY three, since behavior 8 mandates a fourth gap at 0."""
    assert _gaps("", call_sites=1) == _token_gaps()


def test_b12_a_blanked_document_can_never_read_clean_for_any_call_count():
    for cs in (0, 1, 2, None):
        got = _gaps("", call_sites=cs)
        assert _token_gaps() == got[:3], (cs, got)
        assert got != (), cs


def test_b12_AMBIGUITY_empty_doc_at_zero_call_sites_carries_a_fourth_gap():
    """AMBIGUITY NOTED (PM feedback): behavior 12 says an empty doc returns EXACTLY the
    three token gaps, but behavior 8 mandates `dormant-claim-missing` whenever
    `call_sites == 0` and the claim is absent -- and an empty doc has no claim.  Both
    cannot hold at `call_sites=0`.  The observed resolution keeps behavior 8's rule and
    scopes behavior 12's "exactly three" to a positive count, which is the FAIL-CLOSED
    reading: special-casing the empty doc to force a 3-tuple would make a BLANKED
    document read cleaner than a merely incomplete one.  Pinned here so a later edit
    cannot silently introduce that vacuity."""
    assert _gaps("", call_sites=0) == _token_gaps() + ("dormant-claim-missing",)


def test_b12_live_architecture_doc_is_clean_under_the_derived_call_count():
    """THE LIVE BRAKE.  `call_sites` is DERIVED from the two modules' sources, never
    hardcoded, so this stays honest the day `ship_decision` is wired AND its prose
    updated -- and reds if only one of the two happens."""
    call_sites = _derived_call_sites("ship_decision")
    assert call_sites is not None, "both live modules must parse"
    gaps = foundry.sentinel_dormancy_gaps(_read(_ARCH_NAME),
                                          tokens=foundry.SHIP_DECISION_TOKENS,
                                          symbol="ship_decision",
                                          call_sites=call_sites)
    assert gaps == (), (call_sites, gaps)


def test_b12_the_live_token_vocabulary_is_the_shipped_constant():
    assert tuple(foundry.SHIP_DECISION_TOKENS) == TOKENS


def test_b12_live_brake_is_not_vacuous_stripping_the_citations_reds_it():
    """Two-sided proof against the SHIPPING document: remove every backtick and the same
    call returns three token gaps, so `()` above is earned by the prose, not by a check
    that measures nothing (the trap the iter-149 quality-bar docstring names).

    ITERATION 194 re-pinned `call_sites`: it was hardcoded `0`, which was true only while
    `ship_decision` was dormant.  Now that the document correctly does NOT claim dormancy,
    a hardcoded `0` would add a `dormant-claim-missing` gap and this test would be
    measuring the dormancy half by accident.  It is DERIVED from the two live module
    sources instead -- the same honest source `test_b12_live_architecture_doc_is_clean...`
    uses -- so the assertion stays EXACTLY the three token gaps and keeps isolating the
    citation half, which is what "not vacuous" is about here.
    """
    stripped = _read(_ARCH_NAME).replace("`", "")
    call_sites = _derived_call_sites("ship_decision")
    assert call_sites, ("the citation half is only isolated while a call site exists",
                        call_sites)
    gaps = foundry.sentinel_dormancy_gaps(stripped,
                                          tokens=foundry.SHIP_DECISION_TOKENS,
                                          symbol="ship_decision",
                                          call_sites=call_sites)
    assert gaps == _token_gaps(foundry.SHIP_DECISION_TOKENS), gaps


def test_b12_live_brake_reds_when_the_dormancy_claim_is_lower_cased():
    """The other half of the two-sided proof: the dormancy branch is CASE-SENSITIVE on the
    real document, not just on synthetic fixtures.

    ITERATION 194 NOTE -- this test still PASSED unchanged after the wiring, but for the
    WRONG REASON: the shipping document no longer claims dormancy about `ship_decision` at
    all, so `.replace("DORMANT", "dormant")` became a no-op near the symbol and the
    expected `dormant-claim-missing` arrived from the ABSENCE of a claim rather than from
    its case.  A test that passes for a reason it does not name is exactly the fail-open
    vacuity the iter-149 docstring warns about, so the claim is re-inserted first and the
    lower-casing is then proved to be what flips the verdict -- with the `call_sites=0`
    control asserted in the same call.
    """
    reinstated = _arch_with_dormancy_claim_reinstated()
    assert foundry.sentinel_dormancy_gaps(
        reinstated, tokens=foundry.SHIP_DECISION_TOKENS,
        symbol="ship_decision", call_sites=0) == (), "control: the claim must be SEEN"
    doc = reinstated.replace("DORMANT", "dormant")
    assert doc != reinstated, "lower-casing was a no-op -- the proof would be vacuous"
    gaps = foundry.sentinel_dormancy_gaps(doc, tokens=foundry.SHIP_DECISION_TOKENS,
                                          symbol="ship_decision", call_sites=0)
    assert gaps == ("dormant-claim-missing",), gaps


# The exact phrase iteration 194 REMOVED from ARCHITECTURE.md when it wired the gate.
# Re-inserting it is how the two tests below keep proving the dormancy half of the brake
# bites on the REAL shipping document rather than on a synthetic fixture.  Both tests
# assert the mutation actually changed the text, so a later prose rewrite that makes this
# phrase unfindable REDS them instead of silently making them vacuous.
_RETIRED_DORMANCY_CLAIM = "`ship_decision` is **DORMANT** -- nothing calls it. "
_ARCH_WIRED_ANCHOR = "**Iteration 194 WIRED it at the live final gate"


def _arch_with_dormancy_claim_reinstated():
    doc = _read(_ARCH_NAME)
    assert doc.count(_ARCH_WIRED_ANCHOR) == 1, "the wired paragraph moved; re-anchor this"
    mutated = doc.replace(_ARCH_WIRED_ANCHOR,
                          _RETIRED_DORMANCY_CLAIM + _ARCH_WIRED_ANCHOR, 1)
    assert mutated != doc, "mutation was a no-op -- the proof below would be vacuous"
    return mutated


def test_b12_live_brake_reds_if_a_call_site_arrives_without_a_prose_update():
    """The forcing function the spec claims, INVERTED at iteration 194.

    It used to read the shipping document as-is with `call_sites=1`, because the prose
    still claimed dormancy.  Iteration 194 wired the gate AND updated the prose, so that
    exact call is now correctly `()` -- pinned by
    `test_b12_live_architecture_doc_is_clean_under_the_derived_call_count`.  The property
    worth keeping is the FORCING one: if a dormancy claim about `ship_decision` ever
    reappears next to a live call site, the brake must red.  So the claim is re-inserted
    into the real document and the same exact verdict is demanded.
    """
    gaps = foundry.sentinel_dormancy_gaps(_arch_with_dormancy_claim_reinstated(),
                                          tokens=foundry.SHIP_DECISION_TOKENS,
                                          symbol="ship_decision", call_sites=1)
    assert gaps == ("stale-dormant-claim",), gaps


@pytest.mark.parametrize("symbol", ["call_site_count", "sentinel_dormancy_gaps"])
def test_b12_both_new_functions_are_themselves_dormant(symbol):
    """Zero call site in the running pipeline: no existing control path is touched, so a
    running loop's resume semantics are byte-identical."""
    for mod in _MODULES:
        assert foundry.call_site_count(_read(mod), symbol=symbol) == 0, (symbol, mod)


def test_b12_both_new_names_are_reachable_at_module_level():
    for name in ("call_site_count", "sentinel_dormancy_gaps",
                 "SENTINEL_DORMANCY_WINDOW_CHARS"):
        assert hasattr(foundry, name), name
    assert callable(foundry.call_site_count)
    assert callable(foundry.sentinel_dormancy_gaps)


def test_b12_import_probe_in_a_fresh_interpreter_succeeds():
    """The spec's literal `python -c "import foundry, dispatcher"` -- the product quality
    bar.  The module-scope import at the top of this file is the in-process form."""
    proc = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                          cwd=str(_ROOT), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
