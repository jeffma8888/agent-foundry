"""Iteration 412 behavior tests -- the Resilience invariant's `auth` claim is
scoped to what `run_stage` actually does since iter 411 (ONE `auth` attempt, then
an `AUTH_HOLD_SECONDS` hold), and a new pure, DORMANT brake
``foundry.auth_hold_claim_gaps`` polices that sentence in both live docs.

BLACK-BOX / ISOLATION (honored): every assertion below was derived from the PM
spec's Expected Behaviors 1-9 (``products/_platform/state/iter-412/pm.md``) and
from the conventions of the existing modules under ``tests/`` (iter160's
``_norm`` / ``_doc_text``, iter322's item-scope fixtures). The implementation
source, the engineer's notes, the reviewer's notes and ``git diff`` were NOT
read. The only implementation bytes touched are read MECHANICALLY by
``inspect.getsource`` (Behavior 8's purity ban) and a text scan of
``foundry.py`` / ``dispatcher.py`` (Behavior 9's dormancy claim).

Offline by construction: no subprocess, no git, no network, no clock, nothing
written anywhere. Filesystem reads are the two TRACKED docs the spec names plus
the two modules the dormancy scan reads, all located at RUNTIME from this file's
location (never a source-literal absolute path, never a gitignored ``state/``
path, never a count of ambient files).

HAZARD PIN (inherited from iter 159/160) -- always reach through ``foundry.``;
``from foundry import *`` re-exports a seam named ``test_tree`` that pytest then
collects as a zero-argument test.

HAZARD PIN (inherited from iter 160) -- the DOCS render the ladder with U+2192
while ``retry_ladder_lines`` emits ASCII ``->``; every doc-vs-line comparison
goes through :func:`_norm` on BOTH sides. This file stays pure ASCII.
"""

from __future__ import annotations

import inspect
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

FN_NAME = "auth_hold_claim_gaps"
ARROW = "\u2192"
DOCS = ("ARCHITECTURE.md", "CONTINUOUS.md")
ANCHOR = "auth:"

_ITEM_MARKER = re.compile(r"^(?:[-*+] |\d+\. )")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _fn():
    fn = getattr(foundry, FN_NAME, None)
    assert callable(fn), f"foundry.{FN_NAME} must be a module-level callable"
    return fn


def _doc_text(name: str) -> str:
    return (_ROOT / name).read_text(encoding="utf-8")


def _norm(text: str) -> str:
    """iter160's Behavior-8 normalisation: fold ``-->`` / U+2192 to ``->``,
    collapse whitespace."""
    return " ".join(text.replace("-->", "->").replace(ARROW, "->").split())


def _starts_item(line: str) -> bool:
    return bool(_ITEM_MARKER.match(line.strip()))


def _item_lines(doc: str, anchor: str) -> list[str]:
    """The `cooldown_claim_scope_gaps` scope rule, verbatim from the spec: the
    item holding the FIRST anchor = nearest preceding line whose stripped form
    starts with ``- ``, ``* ``, ``+ `` or ``<digits>. ``, through the last
    following non-blank line that does not itself start an item."""
    lines = doc.splitlines()
    hit = next(i for i, ln in enumerate(lines) if anchor in ln)
    start = hit
    while start >= 0 and not _starts_item(lines[start]):
        start -= 1
    assert start >= 0, f"anchor {anchor!r} sits in no list item"
    end = start + 1
    while end < len(lines) and lines[end].strip() and not _starts_item(lines[end]):
        end += 1
    return lines[start:end]


def _assert_str_tuple(got):
    assert isinstance(got, tuple), f"expected a tuple, got {type(got).__name__}: {got!r}"
    assert all(isinstance(x, str) for x in got), f"every member must be str: {got!r}"


# --------------------------------------------------------------------------
# fixtures (inline synthetic docs; ASCII arrows on purpose)
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Behavior 0 -- surface: signature the spec names
# --------------------------------------------------------------------------
def test_b0_signature_positional_doc_and_keyword_only_anchor_defaulting_to_auth():
    params = list(inspect.signature(_fn()).parameters.values())
    assert [p.name for p in params] == ["doc_text", "anchor"], params
    assert params[0].kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ), params[0].kind
    assert params[1].kind is inspect.Parameter.KEYWORD_ONLY, params[1].kind
    assert params[1].default == ANCHOR, params[1].default


# --------------------------------------------------------------------------
# Behavior 1 -- both live docs pass, with a NON-VACUITY floor inside the item
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", DOCS)
def test_b1_live_doc_is_clean(name):
    got = _fn()(_doc_text(name))
    _assert_str_tuple(got)
    assert got == (), f"{name}: {got!r}"


@pytest.mark.parametrize("name", DOCS)
def test_b1_non_vacuity_floor_name_figure_and_ONE_sit_inside_the_anchor_item(name):
    doc = _doc_text(name)
    item = "\n".join(_item_lines(doc, ANCHOR))
    for needle in ("AUTH_HOLD_SECONDS", "30 min", "ONE"):
        assert needle in item, f"{name}: {needle!r} missing from the auth: item:\n{item}"
    # the floor must be ITEM-scoped, so the fact the needles exist somewhere in
    # the file is not what passed it: the item is a strict subset of the doc.
    assert len(item) < len(doc)


def test_b1_the_floor_itself_discriminates_a_ladder_only_item():
    """Control: the same needle check over the B3 fixture FAILS, so a green
    floor on the live docs is not a vacuous string search."""
    item = "\n".join(_item_lines(LADDER_ONLY_ITEM, ANCHOR))
    assert "AUTH_HOLD_SECONDS" not in item
    assert "30 min" not in item
    assert "ONE" not in item


# --------------------------------------------------------------------------
# Behavior 2 -- ladder prose byte-preserved; new sentence AFTER the ladder line,
# same item, no blank between
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", DOCS)
def test_b2_every_rendered_ladder_line_is_still_in_the_doc(name):
    lines = foundry.retry_ladder_lines()
    assert lines, "retry_ladder_lines() rendered nothing -- floor broke"
    doc_n = _norm(_doc_text(name))
    for line in lines:
        assert _norm(line) in doc_n, f"{name} lost ladder line {line!r}"


@pytest.mark.parametrize("name", DOCS)
def test_b2_plain_doc_still_says_4_attempts(name):
    assert "4 attempts" in _doc_text(name), name


def test_b2_architecture_still_carries_the_bold_resilience_label():
    assert "**Resilience.**" in _doc_text("ARCHITECTURE.md")


@pytest.mark.parametrize("name", DOCS)
def test_b2_hold_sentence_follows_the_ladder_line_inside_the_same_item(name):
    item = _item_lines(_doc_text(name), ANCHOR)
    first_ladder = _norm(foundry.retry_ladder_lines()[0])
    ladder_idx = [i for i, ln in enumerate(item) if first_ladder in _norm(ln)]
    assert len(ladder_idx) == 1, f"{name}: ladder line not found exactly once in item: {ladder_idx}"
    hold_idx = [i for i, ln in enumerate(item) if "AUTH_HOLD_SECONDS" in ln]
    assert len(hold_idx) == 1, f"{name}: the name must sit on exactly one item line: {hold_idx}"
    since_idx = [i for i, ln in enumerate(item) if "Since iter 411" in ln]
    assert len(since_idx) == 1, f"{name}: 'Since iter 411' must occur once in item: {since_idx}"
    assert ladder_idx[0] < since_idx[0] <= hold_idx[0], (
        f"{name}: order must be ladder < 'Since iter 411' <= name; "
        f"got {ladder_idx[0]}, {since_idx[0]}, {hold_idx[0]}"
    )
    # _item_lines stops at the first blank line, so membership in the SAME item
    # already proves no blank line separates them; assert it explicitly too.
    assert all(ln.strip() for ln in item[ladder_idx[0] : hold_idx[0] + 1])


# --------------------------------------------------------------------------
# Behavior 3 -- missing sentence reds with exactly the two named gaps
# --------------------------------------------------------------------------
def test_b3_missing_sentence_reds_with_both_gaps():
    got = _fn()(LADDER_ONLY_ITEM)
    _assert_str_tuple(got)
    assert got, "expected a non-empty tuple"
    assert sum(1 for g in got if g.startswith("AUTH_HOLD_SECONDS")) == 1, got
    assert sum(1 for g in got if g.startswith("hold figure absent")) == 1, got
    assert list(got) == sorted(got), f"not sorted ascending: {got!r}"
    assert len(set(got)) == len(got), f"not de-duplicated: {got!r}"


# --------------------------------------------------------------------------
# Behavior 4 -- wrong figure reds naming BOTH figures; right figure is clean
# --------------------------------------------------------------------------
def test_b4_wrong_figure_names_both_and_right_figure_is_clean():
    assert foundry.AUTH_HOLD_SECONDS == 1800, foundry.AUTH_HOLD_SECONDS
    fn = _fn()
    assert fn(_item_with_hold(25)) == ("hold figure 25 min != 30 min",)
    assert fn(_item_with_hold(30)) == ()


def test_b4_figure_message_derives_M_from_the_constant_not_a_literal():
    m = foundry.AUTH_HOLD_SECONDS // 60
    got = _fn()(_item_with_hold(m + 5))
    assert got == (f"hold figure {m + 5} min != {m} min",), got


# --------------------------------------------------------------------------
# Behavior 5 -- AUTH_HOLD_SECONDS is read by BARE module name at CALL time
# --------------------------------------------------------------------------
def test_b5_patched_constant_reds_both_live_docs_and_unpatched_clears_them(monkeypatch):
    fn = _fn()
    docs = {name: _doc_text(name) for name in DOCS}
    for name, doc in docs.items():
        assert fn(doc) == (), f"{name} not clean BEFORE patching"
    monkeypatch.setattr(foundry, "AUTH_HOLD_SECONDS", 1500)
    for name, doc in docs.items():
        got = fn(doc)
        assert got == ("hold figure 30 min != 25 min",), f"{name}: {got!r}"
    monkeypatch.undo()
    assert foundry.AUTH_HOLD_SECONDS == 1800
    for name, doc in docs.items():
        assert fn(doc) == (), f"{name} not clean AFTER un-patching"


def test_b5_synthetic_item_tracks_the_patched_constant_too(monkeypatch):
    fn = _fn()
    doc = _item_with_hold(30)
    assert fn(doc) == ()
    monkeypatch.setattr(foundry, "AUTH_HOLD_SECONDS", 3600)
    assert fn(doc) == ("hold figure 30 min != 60 min",)
    assert fn(_item_with_hold(60)) == ()


# --------------------------------------------------------------------------
# Behavior 6 -- scope is the ITEM, not the file
# --------------------------------------------------------------------------
B6_DOC_BLANK_THEN_SECOND_BULLET = (
    LADDER_ONLY_ITEM
    + "\n"
    + "- Since iter 411 the `auth` rung is rendered but never walked: `run_stage` makes ONE\n"
    + "  `auth` attempt, then holds `AUTH_HOLD_SECONDS` (30 min) and returns the stage failed.\n"
)

B6_DOC_ADJACENT_SECOND_BULLET = (
    LADDER_ONLY_ITEM
    + "- Since iter 411 the `auth` rung is rendered but never walked: `run_stage` makes ONE\n"
    + "  `auth` attempt, then holds `AUTH_HOLD_SECONDS` (30 min) and returns the stage failed.\n"
)


@pytest.mark.parametrize(
    "doc", [B6_DOC_BLANK_THEN_SECOND_BULLET, B6_DOC_ADJACENT_SECOND_BULLET]
)
def test_b6_correct_sentence_in_another_item_does_not_count(doc):
    # the whole FILE carries every needle...
    for needle in ("AUTH_HOLD_SECONDS", "30 min", "ONE"):
        assert needle in doc
    # ...but the anchor's item does not, so the brake reds.
    got = _fn()(doc)
    _assert_str_tuple(got)
    assert got, "expected a non-empty tuple: name in another item must not count"
    assert any(g.startswith("AUTH_HOLD_SECONDS") for g in got), got


def test_b6_control_same_sentence_as_a_continuation_line_is_clean():
    """Two-sided control for B6: the identical sentence INSIDE the item passes."""
    assert _fn()(_item_with_hold(30)) == ()


# --------------------------------------------------------------------------
# Behavior 7 -- fail CLOSED on unusable input; never raises
# --------------------------------------------------------------------------
B7_UNUSABLE = [
    ("None", None, {}),
    ("empty string", "", {}),
    ("int", 42, {}),
    ("no anchor", "- no ladder here\n", {}),
    ("anchor in no list item", "auth: 1 -> 2 -> 4 min\n", {}),
    ("empty anchor", LADDER_ONLY_ITEM, {"anchor": ""}),
]


@pytest.mark.parametrize("label,doc,kw", B7_UNUSABLE, ids=[c[0] for c in B7_UNUSABLE])
def test_b7_unusable_input_reds_with_a_named_reason_and_never_raises(label, doc, kw):
    got = _fn()(doc, **kw)
    _assert_str_tuple(got)
    assert got, f"{label}: expected a non-empty (fail-closed) tuple"
    assert got[0].startswith(("anchor absent", "unusable")), f"{label}: {got!r}"


def test_b7_never_raises_on_other_odd_inputs_spec_acceptance_clause():
    """The Acceptance Criteria say 'Never raises'; probe beyond Behavior 7's
    list. Any outcome except an exception is accepted here."""
    fn = _fn()
    for doc, kw in (
        (b"- auth: x\n", {}),
        (LADDER_ONLY_ITEM, {"anchor": None}),
        (LADDER_ONLY_ITEM, {"anchor": 7}),
        (3.5, {}),
        (["- auth: x\n"], {}),
    ):
        got = fn(doc, **kw)
        _assert_str_tuple(got)
        assert got, f"odd input {doc!r} {kw!r} must fail closed, got {got!r}"


def test_b7_stalled_anchor_on_the_live_architecture_doc_is_the_same_bullet():
    assert _fn()(_doc_text("ARCHITECTURE.md"), anchor="stalled:") == ()
    assert _fn()(_doc_text("CONTINUOUS.md"), anchor="stalled:") == ()


# --------------------------------------------------------------------------
# Behavior 8 -- pure and stable
# --------------------------------------------------------------------------
def test_b8_two_calls_compare_equal_and_the_input_is_unchanged():
    fn = _fn()
    for doc in (LADDER_ONLY_ITEM, _item_with_hold(25), _doc_text("ARCHITECTURE.md")):
        before = doc
        first = fn(doc)
        second = fn(doc)
        assert first == second, (first, second)
        assert doc == before, "the argument was mutated"


def test_b8_source_references_no_io_clock_or_git_token():
    src = inspect.getsource(_fn())
    assert src.strip(), "getsource returned nothing"
    for tok in ("open", "Path", "subprocess", "os.environ", "time", "git"):
        assert tok not in src, f"purity ban: {tok!r} appears in the function source"


# --------------------------------------------------------------------------
# Behavior 9 -- DORMANT: no call site anywhere; both modules import
# --------------------------------------------------------------------------
def test_b9_no_call_site_in_foundry_outside_its_own_def_block():
    module_src = (_ROOT / "foundry.py").read_text(encoding="utf-8")
    block = inspect.getsource(_fn())
    assert module_src.count(block) == 1, "the def block must appear exactly once"
    remainder = module_src.replace(block, "", 1)
    assert remainder.count(f"{FN_NAME}(") == 0, (
        f"{FN_NAME}( is referenced outside its own def block -- not dormant"
    )
    # the def itself is a floor: the name is really in the module
    assert f"def {FN_NAME}(" in module_src


def test_b9_dispatcher_never_names_it():
    disp = (_ROOT / "dispatcher.py").read_text(encoding="utf-8")
    assert disp.count(FN_NAME) == 0, f"{FN_NAME} leaked into dispatcher.py"


def test_b9_both_modules_import_in_process():
    import importlib

    assert importlib.import_module("foundry") is foundry
    disp = importlib.import_module("dispatcher")
    assert disp is not None
    assert not hasattr(disp, FN_NAME)
