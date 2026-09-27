"""Iteration 418 behavior tests -- the four stale "opt-in" sentences about the
dual-scout pre-stage in ARCHITECTURE.md / README.md are re-worded (default ON
since iter 320; ``"dual_pm_scouts": false`` opts OUT) and a pure, DORMANT guard
``foundry.dual_scout_default_claim_gaps(doc_text, default, *, anchor)`` reds a
doc PARAGRAPH whose stated polarity disagrees with the live ``ProductConfig``
default.

BLACK-BOX / ISOLATION (honored): every assertion below was derived from the PM
spec's Expected Behaviors 1-9 (``products/_platform/state/iter-418/pm.md``) and
from the conventions of the existing modules under ``tests/`` (iter412's
``auth_hold_claim_gaps`` suite, iter416's helper pins). The implementation
source, the engineer's notes, the reviewer's notes and ``git diff`` were NOT
read. The only implementation bytes touched are read MECHANICALLY by
``inspect.getsource`` (Behavior 8's purity ban) and a text scan of
``foundry.py`` / ``dispatcher.py`` (Behavior 8's dormancy + token pins).

Offline by construction: no subprocess, no git, no network, no clock, nothing
written anywhere. Filesystem reads are the two TRACKED docs the spec names plus
the two modules the dormancy scan reads, all located at RUNTIME from this file's
location (never a source-literal absolute path, never a gitignored ``state/``
path, never a count of ambient files). The HEAD stale prose is held INLINE
(Behavior 4), never read from git.

HAZARD PIN (inherited from iter 159/160) -- always reach through ``foundry.``;
``from foundry import *`` re-exports a seam named ``test_tree`` that pytest then
collects as a zero-argument test.

HAZARD PIN (iter 415) -- the spec's "paragraph" is the contiguous run of
NON-BLANK lines around the FIRST anchor hit; :func:`_paragraph_lines` below is
the test's OWN scoper (``split("\\n")``, never ``splitlines()``), so a green
non-vacuity floor is measured against the spec's rule, not the product's helper.
"""

from __future__ import annotations

import inspect
import itertools
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

FN_NAME = "dual_scout_default_claim_gaps"
ON_RE_NAME = "SCOUT_DEFAULT_ON_RE"
OFF_RE_NAME = "SCOUT_DEFAULT_OFF_RE"
DEFAULT_ANCHOR = "dual_pm_scouts"
FIELD = "dual_pm_scouts"

ON_UNSTATED = "default ON unstated"
OFF_UNSTATED = "default OFF unstated"
UNNAMED = "dual_pm_scouts unnamed in the claim paragraph"
UNUSABLE = "unusable doc text"
STALE = "stale wording for default=%s: %s"

# the four measured live sites, verbatim from the spec (doc, anchor)
LIVE_SITES = (
    ("ARCHITECTURE.md", "Dual PM scouts ("),
    ("ARCHITECTURE.md", "Stage 0 (dual-PM-scout pre-stage"),
    ("README.md", "scouts = "),
    ("README.md", "# 38. Plan the dual-PM-scout"),
)
SITE_IDS = ["arch-table-row", "arch-stage0-paragraph", "readme-diagram", "readme-38"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _fn():
    fn = getattr(foundry, FN_NAME, None)
    assert callable(fn), f"foundry.{FN_NAME} must be a module-level callable"
    return fn


def _rx(name: str) -> re.Pattern:
    rx = getattr(foundry, name, None)
    assert isinstance(rx, re.Pattern), f"foundry.{name} must be a compiled regex, got {rx!r}"
    return rx


def _doc_text(name: str) -> str:
    return (_ROOT / name).read_text(encoding="utf-8")


def _live_default() -> bool:
    return foundry.ProductConfig.__dataclass_fields__[FIELD].default


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
# fixtures -- HEAD's stale prose, INLINE and verbatim per the spec (Behavior 4)
# --------------------------------------------------------------------------
HEAD_TABLE_ROW = (
    "| 0 | Dual PM scouts (OPT-IN: `dual_pm_scouts` in config) | `pm_scout.md` x2 | "
    "`pm_scout_a.md`, `pm_scout_b.md` | no |\n"
)

HEAD_STAGE0_PARAGRAPH = (
    "Stage 0 (dual-PM-scout pre-stage, wired 2026-08-04 with operator sign-off) runs\n"
    'ONLY when a product opts in via `"dual_pm_scouts": true` in its config.json; the\n'
    "default-off path is byte-identical to the pre-existing single-PM pipeline.\n"
)

HEAD_DIAGRAM_LINES = (
    "                          (scouts = opt-in dual-lens candidate generation,\n"
    "                           `dual_pm_scouts` in config; the PM lead triages)\n"
)

# synthetic paragraphs for the floors / scope / case behaviors
NO_POLARITY = "The `dual_pm_scouts` pre-stage runs two scouts before the PM lead.\n"
CUSTOM_ANCHOR = "PIVOT"
CORRECT_ON_UNNAMED = f"{CUSTOM_ANCHOR} the pre-stage is default ON since iter 320.\n"
CONTRADICTION = "`dual_pm_scouts` is default ON, an OPT-IN pre-stage for every product.\n"
NEAR_MISS_VOCAB = "`dual_pm_scouts` runs by default only; opt-ins never mattered here.\n"


# --------------------------------------------------------------------------
# Behavior 1 -- signature and the two module-level regexes
# --------------------------------------------------------------------------
def test_b1_signature_doc_text_default_and_keyword_only_anchor():
    params = list(inspect.signature(_fn()).parameters.values())
    assert [p.name for p in params] == ["doc_text", "default", "anchor"], params
    assert params[0].kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ), params[0].kind
    assert params[1].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD, params[1].kind
    assert params[1].default is inspect.Parameter.empty, "`default` must have NO default"
    assert params[2].kind is inspect.Parameter.KEYWORD_ONLY, params[2].kind
    assert params[2].default == DEFAULT_ANCHOR, params[2].default


@pytest.mark.parametrize("name", [ON_RE_NAME, OFF_RE_NAME])
def test_b1_regexes_are_module_level_compiled_patterns(name):
    rx = _rx(name)
    assert rx.flags & re.IGNORECASE, f"{name} must be case-insensitive"


ON_PHRASES = ("opt-out", "opts out", "default on", "default-on")
OFF_PHRASES = ("opt-in", "opts in", "default off", "default-off")


@pytest.mark.parametrize("phrase", ON_PHRASES)
def test_b1_on_vocabulary_matches_and_off_does_not(phrase):
    assert _rx(ON_RE_NAME).search(f"x {phrase} y"), phrase
    assert not _rx(OFF_RE_NAME).search(f"x {phrase} y"), phrase


@pytest.mark.parametrize("phrase", OFF_PHRASES)
def test_b1_off_vocabulary_matches_and_on_does_not(phrase):
    assert _rx(OFF_RE_NAME).search(f"x {phrase} y"), phrase
    assert not _rx(ON_RE_NAME).search(f"x {phrase} y"), phrase


@pytest.mark.parametrize("phrase", ON_PHRASES + OFF_PHRASES)
def test_b1_vocabulary_is_case_insensitive(phrase):
    rx = _rx(ON_RE_NAME) if phrase in ON_PHRASES else _rx(OFF_RE_NAME)
    assert rx.search(phrase.upper()), phrase.upper()
    assert rx.search(phrase.title()), phrase.title()


@pytest.mark.parametrize(
    "text",
    ["by default only", "opt-ins", "opt-inward", "default onward", "opts outer", "opt-outs"],
)
def test_b1_vocabulary_is_word_bounded(text):
    assert not _rx(ON_RE_NAME).search(text), text
    assert not _rx(OFF_RE_NAME).search(text), text


# --------------------------------------------------------------------------
# Behavior 2 -- live docs are clean under the live default, non-vacuously
# --------------------------------------------------------------------------
def test_b2_live_default_is_true_today():
    live = _live_default()
    assert isinstance(live, bool), live
    assert live is True, "spec asserts the live `dual_pm_scouts` default is True"


@pytest.mark.parametrize("name,anchor", LIVE_SITES, ids=SITE_IDS)
def test_b2_live_site_is_clean_under_the_live_default(name, anchor):
    got = _fn()(_doc_text(name), _live_default(), anchor=anchor)
    _assert_str_tuple(got)
    assert got == (), f"{name} @ {anchor!r}: {got!r}"


@pytest.mark.parametrize("name,anchor", LIVE_SITES, ids=SITE_IDS)
def test_b2_non_vacuity_floor_paragraph_names_field_and_states_ON(name, anchor):
    doc = _doc_text(name)
    assert doc.count(anchor) >= 1, f"{name}: anchor {anchor!r} is gone from the doc"
    para = "\n".join(_paragraph_lines(doc, anchor))
    assert FIELD in para, f"{name} @ {anchor!r}: paragraph never names {FIELD}:\n{para}"
    assert _rx(ON_RE_NAME).search(para), f"{name} @ {anchor!r}: no ON vocabulary:\n{para}"
    # paragraph-scoped, not file-scoped: the paragraph is a strict subset
    assert len(para) < len(doc)


def test_b2_the_floor_itself_discriminates_the_HEAD_fixtures():
    """Control: the same floor over the HEAD stale fixtures FAILS on the ON
    vocabulary, so a green floor on the live docs is not a vacuous search."""
    for fixture, anchor in (
        (HEAD_TABLE_ROW, "Dual PM scouts ("),
        (HEAD_STAGE0_PARAGRAPH, "Stage 0 (dual-PM-scout pre-stage"),
        (HEAD_DIAGRAM_LINES, "scouts = "),
    ):
        para = "\n".join(_paragraph_lines(fixture, anchor))
        assert FIELD in para
        assert not _rx(ON_RE_NAME).search(para), para


# --------------------------------------------------------------------------
# Behavior 3 -- two-sided on the live docs
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name,anchor", LIVE_SITES, ids=SITE_IDS)
def test_b3_live_site_reds_under_the_opposite_polarity(name, anchor):
    got = _fn()(_doc_text(name), not _live_default(), anchor=anchor)
    _assert_str_tuple(got)
    assert got, f"{name} @ {anchor!r}: expected a non-empty tuple"
    assert OFF_UNSTATED in got, got
    assert any(g.startswith("stale wording for default=False: ") for g in got), got
    _assert_sorted_dedup(got)


# --------------------------------------------------------------------------
# Behavior 4 -- HEAD's stale prose reds (inline fixtures)
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "fixture", [HEAD_TABLE_ROW, HEAD_DIAGRAM_LINES], ids=["table-row", "diagram"]
)
def test_b4_head_row_and_diagram_red_on_opt_in(fixture):
    got = _fn()(fixture, True)
    _assert_str_tuple(got)
    assert STALE % (True, "opt-in") in got, got
    assert ON_UNSTATED in got, got
    _assert_sorted_dedup(got)


def test_b4_head_stage0_paragraph_reds_on_both_phrases():
    got = _fn()(HEAD_STAGE0_PARAGRAPH, True)
    _assert_str_tuple(got)
    assert STALE % (True, "opts in") in got, got
    assert STALE % (True, "default-off") in got, got
    assert ON_UNSTATED in got, got
    _assert_sorted_dedup(got)


def test_b4_entry_format_lower_cases_and_dedups_the_matched_phrase():
    doc = "`dual_pm_scouts` is OPT-IN; yes, Opt-In; truly opt-in.\n"
    got = _fn()(doc, True)
    stale = [g for g in got if g.startswith("stale wording")]
    assert stale == [STALE % (True, "opt-in")], got
    _assert_sorted_dedup(got)


def test_b4_entry_format_uses_the_repr_of_the_bool():
    got = _fn()("`dual_pm_scouts` opts out.\n", False)
    assert STALE % (False, "opts out") in got, got
    assert "stale wording for default=False: opts out" in got


# --------------------------------------------------------------------------
# Behavior 5 -- non-vacuity floors
# --------------------------------------------------------------------------
def test_b5a_no_polarity_paragraph_reds_with_exactly_the_unstated_entry():
    fn = _fn()
    assert fn(NO_POLARITY, True) == (ON_UNSTATED,)
    assert fn(NO_POLARITY, False) == (OFF_UNSTATED,)


def test_b5b_custom_anchor_paragraph_never_naming_the_field_reds_unnamed():
    got = _fn()(CORRECT_ON_UNNAMED, True, anchor=CUSTOM_ANCHOR)
    _assert_str_tuple(got)
    assert UNNAMED in got, got


def test_b5c_contradiction_is_a_gap_never_a_pass():
    got = _fn()(CONTRADICTION, True)
    _assert_str_tuple(got)
    assert STALE % (True, "opt-in") in got, got
    assert ON_UNSTATED not in got, got
    assert got, "a contradiction must red"


# --------------------------------------------------------------------------
# Behavior 6 -- scope is the paragraph; boundaries are words; case ignored
# --------------------------------------------------------------------------
B6_BLANK_SEPARATED = (
    "The `dual_pm_scouts` pre-stage runs two scouts.\n"
    "\n"
    "It is default ON since iter 320.\n"
)
B6_CONTINUATION = (
    "The `dual_pm_scouts` pre-stage runs two scouts.\n"
    "It is default ON since iter 320.\n"
)


def test_b6a_one_blank_line_breaks_the_paragraph_scope():
    fn = _fn()
    assert _rx(ON_RE_NAME).search(B6_BLANK_SEPARATED), "fixture must carry the ON phrase"
    got = fn(B6_BLANK_SEPARATED, True)
    assert ON_UNSTATED in got, got


def test_b6a_control_continuation_line_is_clean():
    assert _fn()(B6_CONTINUATION, True) == ()


def test_b6b_near_miss_vocabulary_matches_neither_side():
    assert _fn()(NEAR_MISS_VOCAB, True) == (ON_UNSTATED,)


@pytest.mark.parametrize("word,phrase", [("OPT-IN", "opt-in"), ("Opt-In", "opt-in"), ("DEFAULT-OFF", "default-off")])
def test_b6c_upper_and_title_case_off_words_red_under_default_true(word, phrase):
    got = _fn()(f"`dual_pm_scouts` is {word} for every product.\n", True)
    assert STALE % (True, phrase) in got, got
    assert ON_UNSTATED in got, got


@pytest.mark.parametrize("word", ["Default On", "opts OUT"])
def test_b6c_mixed_case_on_words_satisfy_default_true(word):
    assert _fn()(f"`dual_pm_scouts` {word} for every product.\n", True) == ()


# --------------------------------------------------------------------------
# Behavior 7 -- fail-closed, never raises, precedence doc -> default -> anchor
# --------------------------------------------------------------------------
@pytest.mark.parametrize("doc", [None, "", 42, b"dual_pm_scouts", 3.5, ["dual_pm_scouts"]])
def test_b7_unusable_doc_text(doc):
    assert _fn()(doc, True) == (UNUSABLE,)


@pytest.mark.parametrize("bad", [1, 0, None, "true"])
def test_b7_non_bool_default(bad):
    assert _fn()(NO_POLARITY, bad) == (f"default not a bool: {bad!r}",)


@pytest.mark.parametrize("anchor", ["", None, "no-such-anchor-zzz", 7])
def test_b7_absent_anchor(anchor):
    assert _fn()(NO_POLARITY, True, anchor=anchor) == (f"anchor absent: {anchor}",)


def test_b7_anchor_hitting_a_blank_line_is_unusable_doc_text():
    assert _fn()(NO_POLARITY, True, anchor="\n") == (UNUSABLE,)


def test_b7_precedence_doc_then_default_then_anchor():
    fn = _fn()
    assert fn(None, 1, anchor="") == (UNUSABLE,)
    assert fn(NO_POLARITY, 1, anchor="") == ("default not a bool: 1",)
    assert fn(NO_POLARITY, True, anchor="") == ("anchor absent: ",)


def test_b7_no_junk_combination_raises():
    fn = _fn()
    junk = (None, b"", 0, [], {})
    seen = 0
    for doc, default, anchor in itertools.product(junk, repeat=3):
        got = fn(doc, default, anchor=anchor)
        _assert_str_tuple(got)
        assert got, f"junk {doc!r} {default!r} {anchor!r} must fail closed"
        seen += 1
    assert seen == 125


# --------------------------------------------------------------------------
# Behavior 8 -- pure, deterministic, dormant
# --------------------------------------------------------------------------
def test_b8_source_references_no_io_clock_or_git_token_docstring_included():
    src = inspect.getsource(_fn())
    assert src.strip(), "getsource returned nothing"
    for tok in ("open", "Path", "subprocess", "os.environ", "time", "git"):
        assert tok not in src, f"purity ban: {tok!r} appears in the function source"


def test_b8_two_calls_compare_equal_and_the_input_is_unchanged():
    fn = _fn()
    live = _live_default()
    for doc, default, kw in (
        (HEAD_STAGE0_PARAGRAPH, True, {}),
        (NO_POLARITY, False, {}),
        (_doc_text("ARCHITECTURE.md"), live, {"anchor": "Stage 0 (dual-PM-scout pre-stage"}),
        (_doc_text("README.md"), not live, {"anchor": "scouts = "}),
    ):
        before = doc
        first = fn(doc, default, **kw)
        second = fn(doc, default, **kw)
        assert first == second, (first, second)
        assert doc == before, "the argument was mutated"


def test_b8_no_call_site_in_foundry_outside_its_own_def_block():
    module_src = (_ROOT / "foundry.py").read_text(encoding="utf-8")
    block = inspect.getsource(_fn())
    assert module_src.count(block) == 1, "the def block must appear exactly once"
    remainder = module_src.replace(block, "", 1)
    assert remainder.count(f"{FN_NAME}(") == 0, (
        f"{FN_NAME}( is referenced outside its own def block -- not dormant"
    )
    assert f"def {FN_NAME}(" in module_src


def test_b8_dispatcher_never_names_it():
    disp = (_ROOT / "dispatcher.py").read_text(encoding="utf-8")
    assert disp.count(FN_NAME) == 0, f"{FN_NAME} leaked into dispatcher.py"


def test_b8_both_modules_import_in_process():
    import importlib

    assert importlib.import_module("foundry") is foundry
    disp = importlib.import_module("dispatcher")
    assert disp is not None
    assert not hasattr(disp, FN_NAME)


def test_b8_list_item_around_token_count_is_still_exactly_three():
    module_src = (_ROOT / "foundry.py").read_text(encoding="utf-8")
    assert module_src.count("_list_item_around(") == 3, module_src.count("_list_item_around(")


# --------------------------------------------------------------------------
# Behavior 9 -- prose flip on disk
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "needle", ["OPT-IN: `dual_pm_scouts`", "opts in via", "default-off path"]
)
def test_b9_architecture_lost_the_stale_phrase(needle):
    assert needle not in _doc_text("ARCHITECTURE.md"), needle


@pytest.mark.parametrize(
    "needle", ["scouts = opt-in", "OPTIONAL two-scout pre-phase that, when enabled"]
)
def test_b9_readme_lost_the_stale_phrase(needle):
    assert needle not in _doc_text("README.md"), needle


def test_b9_architecture_still_has_the_stage_0_table_row():
    assert "| 0 | Dual PM scouts (" in _doc_text("ARCHITECTURE.md")


def test_b9_readme_38_still_names_the_live_flag():
    doc = _doc_text("README.md")
    para = "\n".join(_paragraph_lines(doc, "# 38. Plan the dual-PM-scout"))
    assert "--dual-pm-scouts" in para, para


def test_b9_architecture_stage0_paragraph_names_the_guard():
    doc = _doc_text("ARCHITECTURE.md")
    para = "\n".join(_paragraph_lines(doc, "Stage 0 (dual-PM-scout pre-stage"))
    assert f"foundry.{FN_NAME}" in para, para


@pytest.mark.parametrize("name,anchor", LIVE_SITES, ids=SITE_IDS)
def test_b9_every_reworded_paragraph_states_the_opt_out_config(name, anchor):
    """Acceptance criterion: each paragraph names `dual_pm_scouts` and says
    `"dual_pm_scouts": false` in config.json opts OUT."""
    para = "\n".join(_paragraph_lines(_doc_text(name), anchor))
    assert '"dual_pm_scouts": false' in para, f"{name} @ {anchor!r}:\n{para}"
    assert _rx(ON_RE_NAME).search(para), para
    assert not _rx(OFF_RE_NAME).search(para), para


# --------------------------------------------------------------------------
# Acceptance criterion -- the private paragraph scoper is total (None for odd)
# --------------------------------------------------------------------------
def test_ac_private_paragraph_helper_is_total_and_agrees_with_the_spec_rule():
    helper = getattr(foundry, "_paragraph_around", None)
    assert callable(helper), "foundry._paragraph_around must exist (Acceptance Criteria)"
    for doc, anchor in ((None, "x"), ("", "x"), (42, "x"), ("abc\n", None), ("abc\n", ""), ("abc\n", "zzz")):
        assert helper(doc, anchor) is None, (doc, anchor)
    for name, anchor in LIVE_SITES:
        doc = _doc_text(name)
        assert helper(doc, anchor) == "\n".join(_paragraph_lines(doc, anchor)), (name, anchor)
