"""Iteration 416 behavior tests -- the two verbatim markdown list-item scopers
inside ``cooldown_claim_scope_gaps`` (iter 322) and ``auth_hold_claim_gaps``
(iter 412) are folded onto ONE private pure helper
``foundry._list_item_around(doc_text, anchor) -> str | None``; both public
functions keep their signatures, return shapes and fail-closed sentinels.

BLACK-BOX / ISOLATION (honored): every assertion below was derived from the PM
spec's Expected Behaviors 1-6 (iteration 416) and from the conventions of the
existing modules under ``tests/`` (iter412's ``_item_with_hold`` fixture shape,
iter322's item-scope fixtures). The implementation source, the engineer's notes,
the reviewer's notes and ``git diff`` were NOT read. The only implementation
bytes touched are read MECHANICALLY by ``inspect.getsource`` (Behaviors 3, 5, 6)
and a text scan of ``foundry.py`` / ``dispatcher.py`` (Behaviors 5, 6).

Offline by construction: no subprocess, no git, no network, no clock, nothing
written anywhere. Filesystem reads are the two modules the dormancy scan reads,
located at RUNTIME from this file's location (never a source-literal absolute
path, never a gitignored path, never a count of ambient files).

HAZARD PIN (inherited from iter 159/160) -- always reach through ``foundry.``;
``from foundry import *`` re-exports a seam named ``test_tree`` that pytest then
collects as a zero-argument test.
"""

from __future__ import annotations

import inspect
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

HELPER = "_list_item_around"
COOLDOWN_FN = "cooldown_claim_scope_gaps"
AUTH_FN = "auth_hold_claim_gaps"
PURITY_BAN = ("open", "Path", "subprocess", "os.environ", "time", "git")
PIPELINE_SURFACES = (
    "run_stage",
    "run_iteration",
    "build_prompt",
    "postrelease_step",
    "run_continuous",
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _helper():
    fn = getattr(foundry, HELPER, None)
    assert callable(fn), f"foundry.{HELPER} must be a module-level callable"
    return fn


def _public(name: str):
    fn = getattr(foundry, name, None)
    assert callable(fn), f"foundry.{name} must be a module-level callable"
    return fn


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def _assert_str_tuple(got):
    assert isinstance(got, tuple), f"expected a tuple, got {type(got).__name__}: {got!r}"
    assert all(isinstance(x, str) for x in got), f"every member must be str: {got!r}"


# --------------------------------------------------------------------------
# Behavior 1 fixture -- paragraph, three `- ` bullets (one spanning 3
# continuation lines), one `1. ` item, one `* ` item
# --------------------------------------------------------------------------
B1_PARA = "Intro paragraph line one PARA_TOK.\nIntro paragraph line two.\n"
B1_BULLET_A = "- alpha item, single line with TOK_A and SHARED\n"
B1_BULLET_B = (
    "- beta item first line\n"
    "  beta continuation one carrying TOK_B\n"
    "  beta continuation two\n"
    "  beta continuation three\n"
)
B1_BULLET_C = "- gamma item, single line with SHARED again\n"
B1_NUMBERED = "1. numbered item carrying TOK_N\n   numbered continuation line\n"
B1_STAR = "* star item carrying TOK_S\n"
B1_DOC = (
    B1_PARA
    + "\n"
    + B1_BULLET_A
    + B1_BULLET_B
    + B1_BULLET_C
    + "\n"
    + B1_NUMBERED
    + "\n"
    + B1_STAR
)


def _item(text: str) -> str:
    """The spec's return shape: the item's lines joined by ``\\n``."""
    return "\n".join(text.splitlines())


def test_b1_fixture_has_the_shape_the_spec_names():
    # a paragraph, three `- ` bullets, one `1. ` item, one `* ` item
    lines = B1_DOC.splitlines()
    assert sum(1 for ln in lines if ln.startswith("- ")) == 3
    assert sum(1 for ln in lines if ln.startswith("1. ")) == 1
    assert sum(1 for ln in lines if ln.startswith("* ")) == 1
    assert lines[0].startswith("Intro paragraph")
    # the 3-continuation-line bullet really has 4 lines
    assert len(B1_BULLET_B.splitlines()) == 4


def test_b1_anchor_in_a_continuation_line_returns_exactly_the_three_line_bullet():
    got = _helper()(B1_DOC, "TOK_B")
    assert got == _item(B1_BULLET_B), repr(got)
    # exactness: nothing from the neighbours leaked in, and continuation lines
    # are all there (the item stops at the NEXT MARKER line, gamma)
    assert isinstance(got, str)
    assert got.count("\n") == 3, got
    assert "alpha" not in got and "gamma" not in got, got
    assert "beta continuation three" in got, got


def test_b1_anchor_in_the_numbered_item_returns_that_item_stopping_at_the_blank():
    got = _helper()(B1_DOC, "TOK_N")
    assert got == _item(B1_NUMBERED), repr(got)
    # the numbered item is followed by a BLANK line then the `* ` item; the
    # blank ends the item, so the star item is excluded
    assert "star item" not in got, got
    assert "numbered continuation line" in got, got


def test_b1_anchor_in_the_star_item_at_end_of_doc_returns_that_item():
    got = _helper()(B1_DOC, "TOK_S")
    assert got == _item(B1_STAR), repr(got)


def test_b1_anchor_in_a_single_line_bullet_returns_only_that_line():
    got = _helper()(B1_DOC, "TOK_A")
    assert got == _item(B1_BULLET_A), repr(got)


def test_b1_anchor_present_in_two_items_returns_the_first_occurrence_item():
    assert B1_DOC.count("SHARED") == 2, "fixture must carry the anchor twice"
    got = _helper()(B1_DOC, "SHARED")
    assert got == _item(B1_BULLET_A), repr(got)
    assert "gamma" not in got, got


def test_b1_the_item_is_a_strict_subset_of_the_doc_never_the_whole_doc():
    """Guard against the scoper silently becoming a file-wide search (the
    iter-412 tester lesson): every hit item is shorter than the doc and is a
    verbatim substring of it."""
    fn = _helper()
    for anchor in ("TOK_A", "TOK_B", "TOK_N", "TOK_S", "SHARED"):
        got = fn(B1_DOC, anchor)
        assert isinstance(got, str) and got, (anchor, got)
        assert len(got) < len(B1_DOC), (anchor, got)
        assert got in B1_DOC, (anchor, got)
        assert anchor in got, (anchor, got)


def test_b1_return_shape_is_newline_joined_without_trailing_newline():
    got = _helper()(B1_DOC, "TOK_B")
    assert not got.endswith("\n"), repr(got)
    assert got.splitlines() == B1_BULLET_B.splitlines()


# --------------------------------------------------------------------------
# Behavior 2 -- fail-closed None, never raises
# --------------------------------------------------------------------------
@pytest.mark.parametrize("doc", [None, "", 7, []], ids=["None", "empty", "int", "list"])
def test_b2_unusable_doc_text_returns_none(doc):
    assert _helper()(doc, "TOK_B") is None


@pytest.mark.parametrize("anchor", [None, "", 3], ids=["None", "empty", "int"])
def test_b2_unusable_anchor_returns_none(anchor):
    assert _helper()(B1_DOC, anchor) is None


def test_b2_anchor_absent_from_the_doc_returns_none():
    assert "ZZZ_NOT_HERE" not in B1_DOC
    assert _helper()(B1_DOC, "ZZZ_NOT_HERE") is None


def test_b2_anchor_only_in_a_paragraph_with_no_marker_at_or_before_returns_none():
    # PARA_TOK sits on the very first line, above every marker
    assert B1_DOC.count("PARA_TOK") == 1
    assert _helper()(B1_DOC, "PARA_TOK") is None
    # a doc that is ONLY a paragraph
    assert _helper()("auth: 1 -> 2 -> 4 min\n", "auth:") is None


def test_b2_never_raises_on_other_odd_inputs():
    fn = _helper()
    for doc, anchor in (
        (b"- auth: x\n", "auth:"),
        (3.5, "x"),
        (["- auth: x\n"], "auth:"),
        (B1_DOC, b"TOK_B"),
        (B1_DOC, 3.5),
        (object(), object()),
    ):
        got = fn(doc, anchor)
        assert got is None or isinstance(got, str), (doc, anchor, got)


def test_b2_two_sided_control_a_usable_pair_is_not_none():
    """So the None assertions above are not a helper that always returns None."""
    assert _helper()(B1_DOC, "TOK_B") is not None


# --------------------------------------------------------------------------
# Behavior 3 -- pure
# --------------------------------------------------------------------------
def test_b3_two_calls_compare_equal_and_arguments_are_unchanged():
    fn = _helper()
    for doc, anchor in ((B1_DOC, "TOK_B"), (B1_DOC, "SHARED"), (B1_DOC, "PARA_TOK")):
        doc_before, anchor_before = doc, anchor
        first = fn(doc, anchor)
        second = fn(doc, anchor)
        assert first == second, (first, second)
        assert doc == doc_before and anchor == anchor_before, "an argument was mutated"


def test_b3_source_references_no_io_clock_or_git_token():
    src = inspect.getsource(_helper())
    assert src.strip(), "getsource returned nothing"
    for tok in PURITY_BAN:
        assert tok not in src, f"purity ban: {tok!r} appears in the helper source"


# --------------------------------------------------------------------------
# Behavior 4 -- consumer parity (sentinels byte-identical)
# --------------------------------------------------------------------------
# anchor `30m` (iter322's) on purpose: matching is a case-sensitive verbatim
# substring, so the anchor itself must not contain an owner letter (`A`/`B`)
B4_COOLDOWN_DOC = (
    "- neighbour bullet naming A only\n"
    "- claim 30m sits here\n"
    "  continuation naming B only\n"
    "- trailing bullet\n"
)
B4_COOLDOWN_PARAGRAPH_DOC = "a paragraph with 30m and A and B\n\n- some bullet\n"


def test_b4_cooldown_reports_only_the_owner_missing_from_the_hit_item():
    got = _public(COOLDOWN_FN)(("A", "B"), B4_COOLDOWN_DOC, anchor="30m")
    _assert_str_tuple(got)
    assert got == ("A",), got


@pytest.mark.parametrize(
    "label,doc,anchor",
    [
        ("absent anchor", B4_COOLDOWN_DOC, "NOPE"),
        ("anchor in a paragraph", B4_COOLDOWN_PARAGRAPH_DOC, "30m"),
        ("empty doc", "", "30m"),
    ],
    ids=["absent", "paragraph", "empty"],
)
def test_b4_cooldown_fails_closed_with_the_full_sorted_owners_tuple(label, doc, anchor):
    got = _public(COOLDOWN_FN)(("A", "B"), doc, anchor=anchor)
    _assert_str_tuple(got)
    assert got == ("A", "B"), f"{label}: {got!r}"


def test_b4_cooldown_two_sided_control_both_owners_in_the_item_is_clean():
    doc = "- neighbour\n- claim 30m names A\n  and B too\n- tail\n"
    assert _public(COOLDOWN_FN)(("A", "B"), doc, anchor="30m") == ()


# iter412's `_item_with_hold(30)` shape, copied verbatim (ASCII arrows)
LADDER_ONLY_ITEM = (
    "- **Resilience.** Per stage: up to 4 attempts:\n"
    "  timeout, cli-error, auth: 1 -> 2 -> 4 min; stalled: 1 -> 5 -> 20 min.\n"
)
HOLD_SENTENCE = (
    "  Since iter 411 the `auth` rung is rendered but never walked: `run_stage` makes ONE\n"
    "  `auth` attempt, then holds `AUTH_HOLD_SECONDS` ({m} min) and returns the stage failed.\n"
)


def _item_with_hold(minutes: int) -> str:
    return LADDER_ONLY_ITEM + HOLD_SENTENCE.format(m=minutes)


def test_b4_auth_hold_constant_is_unpatched_at_1800():
    assert foundry.AUTH_HOLD_SECONDS == 1800, foundry.AUTH_HOLD_SECONDS


def test_b4_auth_hold_clean_on_the_30_min_bullet():
    got = _public(AUTH_FN)(_item_with_hold(30))
    _assert_str_tuple(got)
    assert got == (), got


def test_b4_auth_hold_anchor_absent_sentinel_is_byte_identical():
    got = _public(AUTH_FN)(_item_with_hold(30), anchor="zzz")
    assert got == ("anchor absent: zzz",), got


@pytest.mark.parametrize(
    "label,doc",
    [("empty string", ""), ("auth: only in a paragraph", "auth: 1 -> 2 -> 4 min\n")],
    ids=["empty", "paragraph"],
)
def test_b4_auth_hold_unusable_sentinel_is_byte_identical(label, doc):
    got = _public(AUTH_FN)(doc)
    assert got == ("unusable doc text",), f"{label}: {got!r}"


def test_b4_auth_hold_wrong_figure_sentinel_is_byte_identical():
    got = _public(AUTH_FN)(_item_with_hold(25))
    assert got == ("hold figure 25 min != 30 min",), got


def test_b4_auth_hold_signature_unchanged():
    params = list(inspect.signature(_public(AUTH_FN)).parameters.values())
    assert [p.name for p in params] == ["doc_text", "anchor"], params
    assert params[1].kind is inspect.Parameter.KEYWORD_ONLY
    assert params[1].default == "auth:"


def test_b4_cooldown_signature_unchanged():
    params = list(inspect.signature(_public(COOLDOWN_FN)).parameters.values())
    assert [p.name for p in params] == ["owners", "doc_text", "anchor"], params
    assert params[2].kind is inspect.Parameter.KEYWORD_ONLY


def test_b4_helper_scopes_the_auth_bullet_the_same_way_the_consumer_does():
    """Parity at the helper level: on the iter412 fixture the helper returns
    the whole bullet including the hold sentence, which is why the consumer
    reads `()`; on the ladder-only fixture it returns just the two lines."""
    fn = _helper()
    assert fn(_item_with_hold(30), "auth:") == _item(_item_with_hold(30))
    assert fn(LADDER_ONLY_ITEM, "auth:") == _item(LADDER_ONLY_ITEM)


# --------------------------------------------------------------------------
# Behavior 5 -- one scoper
# --------------------------------------------------------------------------
def test_b5_at_most_one_starts_item_closure_and_it_lives_inside_the_helper():
    module_src = _read("foundry.py")
    n = module_src.count("def starts_item")
    assert n <= 1, f"def starts_item appears {n} times -- the fold is incomplete"
    if n == 1:
        assert "def starts_item" in inspect.getsource(_helper()), (
            "the surviving starts_item closure must live inside the helper"
        )


@pytest.mark.parametrize("name", [COOLDOWN_FN, AUTH_FN])
def test_b5_each_consumer_calls_the_helper_once_and_owns_no_scoper(name):
    src = inspect.getsource(_public(name))
    assert src.count(f"{HELPER}(") == 1, f"{name}: {HELPER}( count != 1"
    assert "splitlines(" not in src, f"{name} still splits lines itself"
    assert "starts_item" not in src, f"{name} still carries starts_item"


def test_b5_the_helper_itself_owns_the_scoping_machinery():
    """Non-vacuity floor for B5: the machinery the consumers lost must exist
    SOMEWHERE, namely in the helper."""
    src = inspect.getsource(_helper())
    assert "splitlines(" in src, "the helper must split the doc into lines"
    assert f"def {HELPER}(" in src


# --------------------------------------------------------------------------
# Behavior 6 -- dormancy preserved
# --------------------------------------------------------------------------
def test_b6_helper_named_exactly_three_times_in_foundry():
    module_src = _read("foundry.py")
    assert module_src.count(f"{HELPER}(") == 3, module_src.count(f"{HELPER}(")
    assert module_src.count(f"def {HELPER}(") == 1


def test_b6_dispatcher_never_names_the_helper():
    disp = _read("dispatcher.py")
    assert HELPER not in disp, f"{HELPER} leaked into dispatcher.py"


@pytest.mark.parametrize("surface", PIPELINE_SURFACES)
def test_b6_pipeline_surfaces_name_none_of_the_three(surface):
    src = inspect.getsource(_public(surface))
    assert src.strip(), f"getsource({surface}) returned nothing"
    for symbol in (HELPER, COOLDOWN_FN, AUTH_FN):
        assert symbol not in src, f"{surface} names {symbol}"


def test_b6_both_modules_import_in_process():
    import importlib

    assert importlib.import_module("foundry") is foundry
    disp = importlib.import_module("dispatcher")
    assert disp is not None
    assert not hasattr(disp, HELPER)
