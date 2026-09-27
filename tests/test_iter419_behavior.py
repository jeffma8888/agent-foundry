"""Iteration 419 behavior tests -- the final gate's resumable ``VERIFIED:``
ledger (token, two-segment key, placement above ``ACTION:``, attempt-2+ carry
forward, key-mismatch void) is taught in ``roles/final.md`` under a new
``## Resumable evidence ledger`` heading, and a pure, DORMANT guard
``foundry.final_ledger_claim_gaps(card_text, *, anchor="VERIFIED:")`` names every
required element the card's ledger PARAGRAPH fails to state, driven by the
nine-row ``foundry.FINAL_LEDGER_CLAIMS`` table.

BLACK-BOX / ISOLATION (honored): every assertion below was derived from the PM
spec's Expected Behaviors 1-9 (``products/_platform/state/iter-419/pm.md``) and
from the conventions of the existing modules under ``tests/`` (iter418's
``dual_scout_default_claim_gaps`` suite, iter412's ``auth_hold_claim_gaps``
suite). The implementation source, the engineer's notes, the reviewer's notes
and ``git diff`` were NOT read. The only implementation bytes touched are read
MECHANICALLY by ``inspect.getsource`` (Behavior 8's purity ban) and a token
count over ``foundry.py`` / ``dispatcher.py`` (Behavior 8's dormancy pins).

Offline by construction: no subprocess, no git, no network, no clock, nothing
written anywhere. Filesystem reads are the one TRACKED card the spec names plus
the two modules the dormancy scan counts, all located at RUNTIME from this
file's location (never a source-literal absolute path, never a gitignored
``state/`` path, never a count of ambient files). The pre-iteration card
section (Behavior 3) and every claim paragraph (Behaviors 4-7) are held INLINE.

HAZARD PIN (inherited from iter 159/160) -- always reach through ``foundry.``;
``from foundry import *`` re-exports a seam named ``test_tree`` that pytest then
collects as a zero-argument test.

HAZARD PIN (iter 415/418) -- the spec's "paragraph" is the contiguous run of
NON-BLANK lines around the FIRST anchor hit; :func:`_paragraph_lines` below is
the test's OWN scoper (``split("\\n")``, never ``splitlines()``), so the
non-vacuity floor on the live card is measured against the spec's rule and the
product's private helper is asserted to AGREE with it, not the other way round.

HAZARD PIN (iter 416) -- matching is a verbatim substring / word-bounded regex,
so every inline fixture is built so that each required phrase occurs as ONE
unique marker the mutation tests can delete without touching its neighbours.
"""

from __future__ import annotations

import importlib
import inspect
import itertools
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

FN_NAME = "final_ledger_claim_gaps"
TABLE_NAME = "FINAL_LEDGER_CLAIMS"
DEFAULT_ANCHOR = "VERIFIED:"
CARD_REL = pathlib.Path("roles") / "final.md"

UNUSABLE = "unusable doc text"
ABSENT = "anchor absent: %s"
UNSTATED = "ledger claim unstated: %s"

# Behavior 1 -- the nine labels, in table order, with the spec's exact regex text
EXPECTED_TABLE = (
    ("VERIFIED: token", r"VERIFIED:"),
    ("HEAD sha", r"\bHEAD sha\b"),
    ("sha256", r"\bsha256\b"),
    ("untracked", r"\buntracked\b"),
    ("ACTION: placement", r"\bACTION:"),
    ("pre-commit segment", r"\bpre-commit\b"),
    ("post-commit segment", r"\bpost-commit\b"),
    ("carry forward", r"\bcarr(?:y|ied) forward\b"),
    ("void on mismatch", r"\bvoids?\b"),
)
LABELS = tuple(label for label, _ in EXPECTED_TABLE)
NON_TOKEN_LABELS = LABELS[1:]
TOKEN_LABEL = LABELS[0]

# Behavior 9 -- headings in required order, the retained exception line, the
# literal substrings the ledger paragraph must carry, and the retained last line
HEADINGS_IN_ORDER = (
    "## WRITE-EARLY (checkpoint-first)",
    "## Resumable evidence ledger",
    "## Gate checklist (ALL must hold to ship)",
    "## If ALL pass -- ship",
    "## If ANY fail -- revert",
)
EXCEPTION_LINE = "**EXCEPTION for this card -- the `ACTION:` line is VERIFY-FIRST, never write-early.**"
LEDGER_SUBSTRINGS = (
    "VERIFIED: <check>=<result> key=",
    "<HEAD sha>+<sha256 of git diff HEAD plus every untracked file>",
    "pre-commit segment",
    "post-commit segment",
    "carry forward",
    "never put progress in the",
)
LAST_LINE = "Append lessons to the foundry learnings log as `- [FINAL iterNN] ...`."
EXPECTED_VERBS = ("leak-check", "ledger-key", "preship", "staged-check")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _fn():
    fn = getattr(foundry, FN_NAME, None)
    assert callable(fn), f"foundry.{FN_NAME} must be a module-level callable"
    return fn


def _table():
    table = getattr(foundry, TABLE_NAME, None)
    assert isinstance(table, tuple), f"foundry.{TABLE_NAME} must be a tuple, got {type(table).__name__}"
    return table


def _card_text() -> str:
    return (_ROOT / CARD_REL).read_text(encoding="utf-8")


def _card_bytes() -> bytes:
    return (_ROOT / CARD_REL).read_bytes()


def _module_src(name: str) -> str:
    return (_ROOT / name).read_text(encoding="utf-8")


def _paragraph_lines(doc: str, anchor: str) -> list[str]:
    """The spec's scope rule, implemented independently: the contiguous run of
    non-blank lines holding the FIRST occurrence of ``anchor``."""
    lines = doc.split("\n")
    hit = next(i for i, ln in enumerate(lines) if anchor in ln)
    assert lines[hit].strip(), f"anchor {anchor!r} first hits a blank line"
    start = hit
    while start > 0 and lines[start - 1].strip():
        start -= 1
    end = hit
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    return lines[start : end + 1]


def _assert_str_tuple(got):
    assert isinstance(got, tuple), f"expected a tuple, got {type(got).__name__}: {got!r}"
    assert all(isinstance(x, str) for x in got), f"every member must be str: {got!r}"


def _assert_sorted_dedup(got):
    assert list(got) == sorted(got), f"not sorted ascending: {got!r}"
    assert len(set(got)) == len(got), f"not de-duplicated: {got!r}"


# --------------------------------------------------------------------------
# fixtures -- INLINE, the test's own wording (never read from the card)
# --------------------------------------------------------------------------
# Behavior 3: the PRE-iteration WRITE-EARLY section (two generic anchors and the
# EXCEPTION paragraph) followed by the checklist heading; no `VERIFIED:` anywhere.
PRE_ITERATION_CARD = (
    "# ROLE: Final gate\n"
    "\n"
    "## WRITE-EARLY (checkpoint-first)\n"
    "\n"
    "A stage counts as SUCCESS the moment its required output file is non-empty, and\n"
    "`run_stage` does not care WHEN it was written. So write a complete-but-minimal version\n"
    "of your required output file AS SOON AS your decision is made, then refine that same\n"
    "file in place. Under the per-stage cap, excellent-but-unwritten work scores ZERO.\n"
    "\n"
    "**EXCEPTION for this card -- the `ACTION:` line is VERIFY-FIRST, never write-early.**\n"
    "Write the token only once every check below has a real result behind it.\n"
    "\n"
    "## Gate checklist (ALL must hold to ship)\n"
    "\n"
    "1. The full suite is green.\n"
    "2. The status of the tree is clean.\n"
)

# Behavior 4: a CLEAN paragraph in the test's own words. Every required phrase
# appears as exactly ONE marker so a single str.replace removes one claim.
CLEAN_PARAGRAPH = (
    "Record each finished check as its own line placed ABOVE the ACTION: token,\n"
    "shaped `VERIFIED: name=outcome key=K` where K is the HEAD sha joined with the\n"
    "sha256 of the uncommitted tree including every untracked path. The commit\n"
    "retires the first K, so keep a pre-commit segment and a post-commit segment,\n"
    "each keyed. When retrying, carry forward the lines whose key still matches;\n"
    "a key mismatch voids that segment.\n"
)

# label -> the ONE marker in CLEAN_PARAGRAPH that satisfies it
MARKERS = {
    "HEAD sha": "HEAD sha",
    "sha256": "sha256",
    "untracked": "untracked",
    "ACTION: placement": "ACTION:",
    "pre-commit segment": "pre-commit",
    "post-commit segment": "post-commit",
    "carry forward": "carry forward",
    "void on mismatch": "voids",
}

# a paragraph reached by a custom anchor containing NONE of the ledger vocabulary
LOREM_DOC = (
    "Some card body about something else entirely.\n"
    "\n"
    "lorem ipsum dolor sit amet, a paragraph with nothing about ledgers in it,\n"
    "and a second continuation line that still says nothing relevant.\n"
    "\n"
    "A trailing paragraph.\n"
)


def _without(label: str) -> str:
    marker = MARKERS[label]
    assert CLEAN_PARAGRAPH.count(marker) == 1, (label, marker, CLEAN_PARAGRAPH.count(marker))
    return CLEAN_PARAGRAPH.replace(marker, "XX")


def _swap(label: str, replacement: str) -> str:
    marker = MARKERS[label]
    assert CLEAN_PARAGRAPH.count(marker) == 1, (label, marker)
    return CLEAN_PARAGRAPH.replace(marker, replacement)


# --------------------------------------------------------------------------
# Behavior 1 -- signature and the nine-row claim table
# --------------------------------------------------------------------------
def test_b1_signature_card_text_then_keyword_only_anchor_defaulting_to_token():
    params = list(inspect.signature(_fn()).parameters.values())
    assert [p.name for p in params] == ["card_text", "anchor"], params
    assert params[0].kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ), params[0].kind
    assert params[0].default is inspect.Parameter.empty, "`card_text` must have NO default"
    assert params[1].kind is inspect.Parameter.KEYWORD_ONLY, params[1].kind
    assert params[1].default == DEFAULT_ANCHOR, params[1].default


def test_b1_table_holds_exactly_nine_label_pattern_pairs_in_order():
    table = _table()
    assert len(table) == 9, len(table)
    for row in table:
        assert isinstance(row, tuple) and len(row) == 2, row
        label, rx = row
        assert isinstance(label, str), row
        assert isinstance(rx, re.Pattern), row
    assert tuple(label for label, _ in table) == LABELS, tuple(label for label, _ in table)


@pytest.mark.parametrize("label,pattern", EXPECTED_TABLE, ids=LABELS)
def test_b1_each_row_carries_the_spec_regex_text(label, pattern):
    table = dict(_table())
    assert table[label].pattern == pattern, (label, table[label].pattern)


def test_b1_token_regex_is_case_sensitive_every_other_row_is_case_insensitive():
    table = dict(_table())
    assert not (table[TOKEN_LABEL].flags & re.IGNORECASE), "VERIFIED: must be case-SENSITIVE"
    for label in NON_TOKEN_LABELS:
        assert table[label].flags & re.IGNORECASE, f"{label} must be case-insensitive"


def test_b1_token_regex_rejects_lower_case_and_other_rows_accept_it():
    table = dict(_table())
    assert table[TOKEN_LABEL].search("VERIFIED: x")
    assert not table[TOKEN_LABEL].search("verified: x")
    assert table["HEAD sha"].search("the head sha")
    assert table["void on mismatch"].search("VOID") and table["void on mismatch"].search("Voids")
    assert table["carry forward"].search("CARRIED FORWARD")


# --------------------------------------------------------------------------
# Behavior 2 -- the live card is clean and the anchor lands on prose
# --------------------------------------------------------------------------
def test_b2_live_card_returns_empty_tuple():
    got = _fn()(_card_text())
    _assert_str_tuple(got)
    assert got == (), got


def test_b2_first_token_hit_sits_between_write_early_and_gate_checklist():
    card = _card_text()
    i_we = card.find(HEADINGS_IN_ORDER[0])
    i_tok = card.find(DEFAULT_ANCHOR)
    i_gc = card.find(HEADINGS_IN_ORDER[2])
    assert i_we >= 0 and i_tok >= 0 and i_gc >= 0, (i_we, i_tok, i_gc)
    assert i_we < i_tok < i_gc, (i_we, i_tok, i_gc)


def test_b2_private_scoper_lands_on_a_long_prose_paragraph_carrying_key():
    helper = getattr(foundry, "_paragraph_around", None)
    assert callable(helper), "foundry._paragraph_around must exist"
    para = helper(_card_text(), DEFAULT_ANCHOR)
    assert isinstance(para, str), para
    assert not para.startswith("#"), para[:40]
    assert len(para) >= 400, len(para)
    assert "key=" in para, para


def test_b2_non_vacuity_floor_own_scoper_finds_every_claim_in_the_live_paragraph():
    """Independent oracle: the test's own scoper over the live card must see all
    nine claims, so a green guard on the live card is not a vacuous search."""
    card = _card_text()
    para = "\n".join(_paragraph_lines(card, DEFAULT_ANCHOR))
    for label, pattern in EXPECTED_TABLE:
        flags = 0 if label == TOKEN_LABEL else re.IGNORECASE
        assert re.search(pattern, para, flags), f"{label}: {pattern!r} missing from:\n{para}"
    assert len(para) < len(card)


def test_b2_private_scoper_agrees_with_the_spec_rule_on_the_live_card():
    card = _card_text()
    assert foundry._paragraph_around(card, DEFAULT_ANCHOR) == "\n".join(_paragraph_lines(card, DEFAULT_ANCHOR))


# --------------------------------------------------------------------------
# Behavior 3 -- a card without the ledger reds on the absent anchor
# --------------------------------------------------------------------------
def test_b3_pre_iteration_card_reports_exactly_anchor_absent():
    assert DEFAULT_ANCHOR not in PRE_ITERATION_CARD, "fixture must hold no VERIFIED: token"
    assert HEADINGS_IN_ORDER[0] in PRE_ITERATION_CARD
    assert HEADINGS_IN_ORDER[2] in PRE_ITERATION_CARD
    assert "**EXCEPTION for this card" in PRE_ITERATION_CARD
    got = _fn()(PRE_ITERATION_CARD)
    _assert_str_tuple(got)
    assert got == (ABSENT % DEFAULT_ANCHOR,), got


# --------------------------------------------------------------------------
# Behavior 4 -- every claim is two-sided on an inline fixture
# --------------------------------------------------------------------------
def test_b4_clean_inline_paragraph_returns_empty_tuple():
    got = _fn()(CLEAN_PARAGRAPH)
    _assert_str_tuple(got)
    assert got == (), got


@pytest.mark.parametrize("label", NON_TOKEN_LABELS)
def test_b4_deleting_one_phrase_yields_exactly_that_label(label):
    got = _fn()(_without(label))
    _assert_str_tuple(got)
    assert got == (UNSTATED % label,), (label, got)


def test_b4_deleting_all_eight_yields_eight_sorted_deduplicated_entries():
    doc = CLEAN_PARAGRAPH
    for label in NON_TOKEN_LABELS:
        doc = doc.replace(MARKERS[label], "XX")
    got = _fn()(doc)
    _assert_str_tuple(got)
    assert len(got) == 8, got
    assert got == tuple(sorted(UNSTATED % label for label in NON_TOKEN_LABELS)), got
    assert UNSTATED % TOKEN_LABEL not in got, "the anchor line itself still carries the token"
    _assert_sorted_dedup(got)


def test_b4_custom_anchor_on_a_vocabulary_free_paragraph_yields_all_nine():
    got = _fn()(LOREM_DOC, anchor="lorem")
    _assert_str_tuple(got)
    assert len(got) == 9, got
    assert UNSTATED % TOKEN_LABEL in got, got
    assert got == tuple(sorted(UNSTATED % label for label in LABELS)), got
    _assert_sorted_dedup(got)


# --------------------------------------------------------------------------
# Behavior 5 -- scope is the paragraph
# --------------------------------------------------------------------------
def test_b5_phrase_one_blank_line_away_does_not_count():
    doc = _without("sha256") + "\nThe sha256 digest is described here, one blank line away.\n"
    assert "sha256" in doc, "fixture must carry the phrase somewhere in the doc"
    got = _fn()(doc)
    assert got == (UNSTATED % "sha256",), got


def test_b5_control_same_phrase_as_a_continuation_line_is_clean():
    doc = _without("sha256") + "The sha256 digest is described here as a continuation line.\n"
    assert _fn()(doc) == ()


def test_b5_heading_separated_by_a_blank_line_is_outside_the_scoped_text():
    helper = foundry._paragraph_around
    with_gap = "## A heading\n\nVERIFIED: first line\nsecond line\n"
    assert helper(with_gap, DEFAULT_ANCHOR) == "VERIFIED: first line\nsecond line"
    assert helper(with_gap, DEFAULT_ANCHOR) == "\n".join(_paragraph_lines(with_gap, DEFAULT_ANCHOR))
    # control: no blank line -> the heading IS part of the run
    no_gap = "## A heading\nVERIFIED: first line\nsecond line\n"
    assert helper(no_gap, DEFAULT_ANCHOR).startswith("## A heading\n")


# --------------------------------------------------------------------------
# Behavior 6 -- vocabulary boundaries and case
# --------------------------------------------------------------------------
def test_b6_lower_case_verified_does_not_satisfy_the_token_claim():
    doc = CLEAN_PARAGRAPH.replace("VERIFIED:", "verified:")
    assert "VERIFIED:" not in doc
    got = _fn()(doc, anchor="verified:")
    assert got == (UNSTATED % TOKEN_LABEL,), got


@pytest.mark.parametrize(
    "label,spelling",
    [
        ("HEAD sha", "head SHA"),
        ("sha256", "Sha256"),
        ("carry forward", "Carried Forward"),
        ("void on mismatch", "VOIDS"),
    ],
    ids=["head-SHA", "Sha256", "Carried-Forward", "VOIDS"],
)
def test_b6_mixed_case_and_carried_spellings_satisfy_their_claims(label, spelling):
    assert _fn()(_swap(label, spelling)) == ()


@pytest.mark.parametrize(
    "label,spelling",
    [
        ("pre-commit segment", "pre-committed"),
        ("post-commit segment", "post-commits"),
        ("void on mismatch", "voided"),
        ("carry forward", "carry-forward"),
        ("untracked", "untrackedness"),
    ],
    ids=["pre-committed", "post-commits", "voided", "carry-hyphen-forward", "untrackedness"],
)
def test_b6_near_miss_spellings_satisfy_none_of_theirs(label, spelling):
    got = _fn()(_swap(label, spelling))
    assert got == (UNSTATED % label,), (spelling, got)


@pytest.mark.parametrize("spelling", ["void", "voids"])
def test_b6_void_and_voids_both_satisfy_void_on_mismatch(spelling):
    assert _fn()(_swap("void on mismatch", spelling)) == ()


# --------------------------------------------------------------------------
# Behavior 7 -- fail-closed, never raises, in order
# --------------------------------------------------------------------------
@pytest.mark.parametrize("doc", [None, b"", 0, "", [], 3.5, {"VERIFIED:": 1}])
def test_b7_non_str_or_empty_card_text_is_unusable(doc):
    assert _fn()(doc) == (UNUSABLE,)


@pytest.mark.parametrize("anchor", [None, "", "zzz", 0, 7.5, b"VERIFIED:"])
def test_b7_non_str_empty_or_missing_anchor_is_absent_rendered_with_percent_s(anchor):
    assert _fn()(CLEAN_PARAGRAPH, anchor=anchor) == (ABSENT % anchor,)


def test_b7_none_anchor_renders_as_the_word_None():
    assert _fn()(CLEAN_PARAGRAPH, anchor=None) == ("anchor absent: None",)


def test_b7_whitespace_only_anchor_or_blank_line_hit_is_unusable():
    fn = _fn()
    assert fn("alpha\n\nbeta\n", anchor="\n") == (UNUSABLE,)
    assert fn(CLEAN_PARAGRAPH + "\n\nVERIFIED: tail\n", anchor="\n") == (UNUSABLE,)
    assert fn("VERIFIED: x\n\n", anchor="\n") == (UNUSABLE,)


def test_b7_precedence_card_text_before_anchor():
    fn = _fn()
    assert fn(None, anchor="") == (UNUSABLE,)
    assert fn("", anchor=None) == (UNUSABLE,)
    assert fn(0, anchor=0) == (UNUSABLE,)
    assert fn("x" * 3, anchor="") == (ABSENT % "",)
    assert fn("x" * 3, anchor="zzz") == (ABSENT % "zzz",)


def test_b7_full_junk_product_never_raises_and_always_returns_a_str_tuple():
    fn = _fn()
    docs = (None, b"", 0, "", [], "x" * 3, CLEAN_PARAGRAPH)
    anchors = (None, "", "\n", DEFAULT_ANCHOR, "zzz", 0)
    seen = 0
    for doc, anchor in itertools.product(docs, anchors):
        got = fn(doc, anchor=anchor)
        _assert_str_tuple(got)
        if doc is not CLEAN_PARAGRAPH or anchor != DEFAULT_ANCHOR:
            assert got, f"{doc!r} / {anchor!r} must fail closed"
        else:
            assert got == (), got
        seen += 1
    assert seen == 42


# --------------------------------------------------------------------------
# Behavior 8 -- pure, deterministic, dormant
# --------------------------------------------------------------------------
def test_b8_source_references_no_io_clock_or_git_token_docstring_included():
    src = inspect.getsource(_fn())
    assert src.strip(), "getsource returned nothing"
    assert '"""' in src or "'''" in src, "the guard must carry a docstring (spec: docstring INCLUDED)"
    for tok in ("open", "Path", "subprocess", "os.environ", "time", "git"):
        assert tok not in src, f"purity ban: {tok!r} appears in the function source"


def test_b8_two_calls_compare_equal_and_the_input_is_unchanged():
    fn = _fn()
    live = _card_text()
    for doc, kw in (
        (live, {}),
        (CLEAN_PARAGRAPH, {}),
        (LOREM_DOC, {"anchor": "lorem"}),
        (PRE_ITERATION_CARD, {}),
        (_without("carry forward"), {}),
    ):
        before = doc
        first = fn(doc, **kw)
        second = fn(doc, **kw)
        assert first == second, (first, second)
        assert doc == before, "the argument was mutated"


def test_b8_token_appears_exactly_once_in_foundry_its_own_def_line():
    module_src = _module_src("foundry.py")
    assert module_src.count(f"{FN_NAME}(") == 1, module_src.count(f"{FN_NAME}(")
    assert f"def {FN_NAME}(" in module_src


def test_b8_no_call_site_outside_its_own_def_block():
    module_src = _module_src("foundry.py")
    block = inspect.getsource(_fn())
    assert module_src.count(block) == 1, "the def block must appear exactly once"
    remainder = module_src.replace(block, "", 1)
    assert remainder.count(f"{FN_NAME}(") == 0, f"{FN_NAME}( referenced outside its def -- not dormant"


def test_b8_helper_token_counts_list_item_three_paragraph_three():
    module_src = _module_src("foundry.py")
    assert module_src.count("_list_item_around(") == 3, module_src.count("_list_item_around(")
    assert module_src.count("_paragraph_around(") == 3, module_src.count("_paragraph_around(")


def test_b8_dispatcher_never_names_the_guard_or_the_table():
    disp = _module_src("dispatcher.py")
    assert disp.count(FN_NAME) == 0, f"{FN_NAME} leaked into dispatcher.py"
    assert disp.count(TABLE_NAME) == 0, f"{TABLE_NAME} leaked into dispatcher.py"


def test_b8_both_modules_import_in_process():
    assert importlib.import_module("foundry") is foundry
    disp = importlib.import_module("dispatcher")
    assert disp is not None
    assert not hasattr(disp, FN_NAME)


# --------------------------------------------------------------------------
# Behavior 9 -- card prose on disk
# --------------------------------------------------------------------------
def test_b9_headings_present_in_the_required_order():
    card = _card_text()
    idx = [card.find(h) for h in HEADINGS_IN_ORDER]
    assert all(i >= 0 for i in idx), dict(zip(HEADINGS_IN_ORDER, idx))
    assert idx == sorted(idx), dict(zip(HEADINGS_IN_ORDER, idx))
    for h in HEADINGS_IN_ORDER:
        assert card.count(h) == 1, (h, card.count(h))


def test_b9_exception_line_still_present_and_precedes_the_new_heading():
    card = _card_text()
    i_exc = card.find(EXCEPTION_LINE)
    i_new = card.find(HEADINGS_IN_ORDER[1])
    assert i_exc >= 0, "the EXCEPTION line was dropped"
    assert i_exc < i_new, (i_exc, i_new)


def test_b9_card_is_ascii_only():
    raw = _card_bytes()
    assert raw, "card is empty"
    assert all(b < 128 for b in raw), "non-ASCII byte in roles/final.md"


def test_b9_card_teaches_no_new_verb():
    verbs = foundry.role_card_verbs(_card_text())
    assert tuple(verbs) == EXPECTED_VERBS, verbs


@pytest.mark.parametrize("needle", LEDGER_SUBSTRINGS, ids=[s[:24] for s in LEDGER_SUBSTRINGS])
def test_b9_ledger_paragraph_carries_each_literal_substring(needle):
    para = "\n".join(_paragraph_lines(_card_text(), DEFAULT_ANCHOR))
    assert needle in para, f"{needle!r} missing from the ledger paragraph:\n{para}"


def test_b9_ledger_paragraph_sits_under_the_new_heading():
    card = _card_text()
    i_new = card.find(HEADINGS_IN_ORDER[1])
    i_tok = card.find(DEFAULT_ANCHOR)
    i_gc = card.find(HEADINGS_IN_ORDER[2])
    assert i_new < i_tok < i_gc, (i_new, i_tok, i_gc)


def test_b9_last_non_blank_line_is_unchanged():
    lines = [ln for ln in _card_text().split("\n") if ln.strip()]
    assert lines[-1] == LAST_LINE, lines[-1]


# --------------------------------------------------------------------------
# Acceptance criterion -- the ledger paragraph is ONE contiguous block of 10-15 lines
# and invokes exactly the key verb. Iteration 419 pinned 8-10 lines and NO
# `foundry.py <verb>` as a scope guard for THAT iteration ("the new paragraph
# teaches no verb"); iteration 420 added the one sentence naming `ledger-key`, so
# the bound admits the wrapped sentence and the verb assertion is inverted.
# --------------------------------------------------------------------------
def test_ac_ledger_paragraph_is_one_contiguous_block_naming_ledger_key():
    para = _paragraph_lines(_card_text(), DEFAULT_ANCHOR)
    assert 10 <= len(para) <= 15, len(para)
    assert all(ln.strip() for ln in para), "blank line inside the paragraph"
    joined = "\n".join(para)
    assert "foundry.py ledger-key" in joined, "the paragraph must name the ledger-key verb"
    assert foundry.role_card_verbs(joined) == ("ledger-key",), foundry.role_card_verbs(joined)
