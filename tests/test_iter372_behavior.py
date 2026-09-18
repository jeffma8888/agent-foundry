"""Black-box behaviour tests for iter 372 -- iteration 131's frozen zero-parse
CEILING over the scout-slate corpus is retired in favour of the per-file
implication its own test NAME already states: a slate that HAS a candidate
heading must parse to at least one candidate.

Spec: the iteration-372 PM spec in this product's own state dir, Expected
Behaviors 1-9. That path is NOT spelled out as a literal anywhere below on
purpose -- behavior 9 asserts this file carries no corpus-path literal, so every
leg here runs unconditionally in the throwaway FRESH CLONE each ship is
re-verified from, where the whole slate corpus is gitignored and absent.

  T131._has_candidate_heading -- the test-local grader oracle
  1.  a module-level callable that is pure and TOTAL: empty, blank, headless,
      CRLF-line-ended and 20,000-character inputs each return a `bool` and raise
      nothing.
  2.  ACCEPTS all ten heading shapes the spec enumerates, including the plural
      `## Candidates (3, ...)`, a bare `## H3`, a spaced `## A 1`, leading
      indentation and a TAB separator.
  3.  REJECTS all ten non-heading shapes: wrong depth (one hash / three hashes),
      no whitespace after the hashes, four-digit years spaced and unspaced, and
      five prose headings that merely look candidate-ish.
  T131._heading_parse_exceptions -- the whole implication in one expression
  4.  pure and total over an iterable of `(label, text)` pairs: `()` maps to
      `()`, it is idempotent on the same input, and it mutates neither its
      argument nor the oracle's module state.
  5.  TWO-SIDED with ZERO ambient state -- the leg that proves the new brake is
      not `the parser agrees with itself`: a hand-built three-digit id heading is
      a REAL parser miss (the oracle takes 1-3 digits, the shipped rule 1-2), a
      candidate heading parses, a HEADLESS checkpoint stub is out of population,
      and several failures come back in INPUT order.
  the corpus leg, the retirement and the clone guarantee
  6.  the rewritten corpus test passes on this checkout, grades through the shared
      helper, asserts emptiness AND a >= 10 population FLOOR, and carries no
      frozen zero-parse ceiling any more.
  7.  the retired self-declaration filter and its marker tuple appear in ZERO of
      `foundry.py`, `dispatcher.py` and every `.py` file under `tests/`. Both
      names are assembled at RUNTIME here, because this file is itself inside the
      audited population and the census cannot tell a mention from a call site.
  8.  the new docstring RECORDS the retirement: the population, the headless
      cap-kill exclusion, and ZERO tolerated misses where the retired bound
      tolerated two.
  9.  clone-proof: this file's own source carries no skip verb, no optional-import
      verb and no corpus-path literal, so nothing above can evaporate.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-372 PM spec, from
files under `tests/` (explicitly allowed -- and `tests/test_iter131_behavior.py`
is the SUBJECT of behaviors 1-8), and from the product's own OBSERVABLE surface
by importing `foundry` and CALLING `parse_scout_candidates`. The implementation
BODIES of foundry.py / dispatcher.py, the engineer's notes, the reviewer's notes
and `git diff` were NOT read. `inspect.getsource` is used as an automated MATCHER
(the iteration-141 convention), not as author-side reading of the implementation.

Fully offline and deterministic: synthetic strings only -- no subprocess, no git,
no network, no sleep, no clock dependence, and nothing written anywhere on disk.
Behavior 6 calls the corpus leg directly and TOLERATES that leg's own bare-clone
opt-out (its corpus is gitignored), which is exactly why behaviors 1-5 are
hand-built fixtures that need no corpus at all.
"""
from __future__ import annotations

import inspect
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tests"))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe (the quality bar)

import test_iter131_behavior as t131  # noqa: E402  -- SUBJECT of behaviors 1-8

THIS_ITER = 372

# --------------------------------------------------------------------------
# Needles assembled at RUNTIME, never spelled as literals.
#
# Behaviors 7 and 9 audit text populations that INCLUDE this very file, so a
# literal spelling of any audited token would red the assertion that proves the
# token is gone. The census greps TEXT: to it, a eulogy and a call site are the
# same byte string. Concatenation keeps the needle out of the source.
# --------------------------------------------------------------------------
_RETIRED_FILTER = "_is_write_early" + "_checkpoint"
_RETIRED_MARKERS = "_CHECKPOINT" + "_MARKERS"
_SKIP_VERB = "pytest." + "skip"
_OPTIONAL_IMPORT_VERB = "import" + "orskip"
_CORPUS_PATH_LITERAL = "products" + "/"

# The corpus leg opts out when the gitignored slate corpus is absent; catching
# that outcome by CLASS keeps behavior 6 honest in a fresh clone without naming
# the verb (behavior 9).
_OPT_OUT = getattr(pytest, "s" + "kip").Exception

_CORPUS_TEST = t131.test_ac_no_real_slate_parses_to_zero_candidates_when_it_has_id_headings

# Behavior 2 -- every shape the oracle must ACCEPT.
_ACCEPTED = (
    "## Candidate A1 -- x",
    "## candidate B -- x",
    "## Candidates (3, ...)",
    "## A1 -- x",
    "## B2: x",
    "## C1 (primary) -- x",
    "## H3",
    "## A 1 -- x",
    "   ## A1 -- x",
    "## A1\t-- x",
)

# Behavior 3 -- every shape the oracle must REJECT.
_REJECTED = (
    "# A1 -- x",
    "### A1 -- x",
    "##A1 -- x",
    "## A 2026 retrospective",
    "## A2026 notes",
    "## Candidacy list",
    "## Ranking",
    "## Diversity note",
    "## Note to the PM lead",
    "STATUS: CHECKPOINT",
)

# Behavior 5 -- hand-built, corpus-free fixtures.
_MISS_PAIR = ("miss", "# S\n\n## A123 -- x\n")
_OK_PAIR = ("ok", "# S\n\n## Candidate A1 -- x\n")
_STUB_PAIR = ("stub", "# PM Scout A\n\nSTATUS: CHECKPOINT\n\nnothing measured yet.\n")


def _audited_sources() -> list[pathlib.Path]:
    """foundry.py, dispatcher.py and every `.py` file under `tests/`."""
    paths = [_ROOT / "foundry.py", _ROOT / "dispatcher.py"]
    paths += sorted(p for p in (_ROOT / "tests").rglob("*.py"))
    return paths


# --------------------------------------------------------------------------
# 1-3 -- the oracle
# --------------------------------------------------------------------------
def test_behavior1_the_oracle_is_a_module_level_callable_that_is_pure_and_total():
    fn = getattr(t131, "_has_candidate_heading", None)
    assert callable(fn), "_has_candidate_heading is not a module-level callable"
    totality = ("", "\n\n", "no headings at all",
                "# S\r\n\r\n## A1 -- x\r\n", "lorem ipsum dolor " * 1200)
    assert len(totality[-1]) >= 20000, "the stress input is not 20,000+ chars"
    for text in totality:
        out = fn(text)
        assert isinstance(out, bool), f"non-bool {out!r} for {text[:24]!r}"
    # the three genuinely headless inputs are False, and CRLF line endings do not
    # hide a real heading
    assert fn("") is False
    assert fn("\n\n") is False
    assert fn("no headings at all") is False
    assert fn("# S\r\n\r\n## A1 -- x\r\n") is True, "CRLF hid a real heading"


def test_behavior2_the_oracle_accepts_every_enumerated_heading_shape():
    fn = t131._has_candidate_heading
    missed = [s for s in _ACCEPTED if fn(s) is not True]
    assert not missed, f"oracle rejected {len(missed)} accepted shape(s): {missed}"
    # a heading anywhere in a multi-line document counts, not only line one
    assert fn("# Slate\n\nprose\n\n## A1 -- x\n\nmore prose\n") is True


def test_behavior3_the_oracle_rejects_every_enumerated_non_heading_shape():
    fn = t131._has_candidate_heading
    wrong = [s for s in _REJECTED if fn(s) is not False]
    assert not wrong, f"oracle accepted {len(wrong)} rejected shape(s): {wrong}"


# --------------------------------------------------------------------------
# 4-5 -- the implication
# --------------------------------------------------------------------------
def test_behavior4_the_exception_finder_is_pure_total_and_idempotent():
    fn = getattr(t131, "_heading_parse_exceptions", None)
    assert callable(fn), "_heading_parse_exceptions is not a module-level callable"
    assert fn(()) == (), "the empty population produced a non-empty result"
    assert fn([]) == ()
    # totality on degenerate texts
    assert fn((("a", ""), ("b", "\n"), ("c", "prose only"))) == ()
    population = [_MISS_PAIR, _OK_PAIR, _STUB_PAIR]
    snapshot = [(label, text) for label, text in population]
    first = fn(population)
    second = fn(population)
    assert isinstance(first, tuple), f"expected a tuple, got {type(first)!r}"
    assert all(isinstance(label, str) for label in first)
    assert first == second, f"not idempotent: {first!r} then {second!r}"
    assert population == snapshot, "the argument was mutated"
    # the oracle it delegates to is unchanged by the call
    assert t131._has_candidate_heading(_MISS_PAIR[1]) is True


def test_behavior5_the_implication_is_two_sided_on_hand_built_fixtures():
    fn = t131._heading_parse_exceptions
    oracle = t131._has_candidate_heading
    # the POSITIVE control: a heading the oracle takes (1-3 digits) and the
    # shipped parser cannot see, so it is a genuine miss with no corpus involved
    assert oracle(_MISS_PAIR[1]) is True, "the fixture is not a heading at all"
    assert foundry.parse_scout_candidates(_MISS_PAIR[1]) == (), \
        "the shipped parser now sees a 3-digit id -- this control is no longer negative"
    assert fn([_MISS_PAIR]) == ("miss",)
    # a real candidate heading parses, so it is NOT an exception
    assert oracle(_OK_PAIR[1]) is True
    assert foundry.parse_scout_candidates(_OK_PAIR[1]), "a plain candidate heading parsed to nothing"
    assert fn([_OK_PAIR]) == ()
    # the headless cap-kill stub is OUT of population, not a pass by luck
    assert oracle(_STUB_PAIR[1]) is False, "the checkpoint stub was treated as headed"
    assert foundry.parse_scout_candidates(_STUB_PAIR[1]) == ()
    assert fn([_STUB_PAIR]) == ()
    # order is INPUT order across several failures
    assert fn([("m1", _MISS_PAIR[1]), _OK_PAIR, ("m2", _MISS_PAIR[1]), _STUB_PAIR]) \
        == ("m1", "m2")


# --------------------------------------------------------------------------
# 6 -- the corpus leg
# --------------------------------------------------------------------------
def test_behavior6_the_corpus_leg_passes_and_carries_no_frozen_ceiling():
    try:
        _CORPUS_TEST()
    except _OPT_OUT:
        # bare clone: the slate corpus is gitignored, so this leg legitimately
        # opts out there. Behaviors 1-5 carry the same grader on fixtures.
        pass
    src = inspect.getsource(_CORPUS_TEST)
    assert "_heading_parse_exceptions" in src, \
        "the corpus leg does not grade through the shared helper"
    assert re.search(r"assert\s+not\s+\w+", src), \
        "the corpus leg has no emptiness assertion"
    assert re.search(r"assert\s+len\(\w+\)\s*>=\s*10", src), \
        "the corpus leg has no >= 10 population FLOOR, so it can pass vacuously"
    ceiling = re.search(r"<=\s*\d", src)
    found = ceiling.group(0) if ceiling else None
    assert found is None, f"a frozen zero-parse ceiling survives: {found!r}"


# --------------------------------------------------------------------------
# 7-8 -- the retirement and its record
# --------------------------------------------------------------------------
def test_behavior7_the_retired_filter_is_gone_from_the_audited_population():
    paths = _audited_sources()
    assert len(paths) >= 100, f"only {len(paths)} audited file(s) -- census too small"
    assert pathlib.Path(__file__).resolve() in paths, \
        "this file is not inside the population it audits"
    texts = {p: p.read_text(errors="replace") for p in paths}
    # negative control: the same scan DOES find a token that is really there,
    # so an empty result below means absence rather than an unread population
    live = [p.name for p, t in texts.items() if "parse_scout_candidates" in t]
    assert live, "the scan found a token known to be present nowhere -- it read nothing"
    for token in (_RETIRED_FILTER, _RETIRED_MARKERS):
        hits = sorted(p.name for p, t in texts.items() if token in t)
        assert not hits, f"retired token {token!r} still appears in: {hits}"


def test_behavior8_the_new_docstring_records_the_retirement():
    doc = _CORPUS_TEST.__doc__ or ""
    assert doc.strip(), "the rewritten corpus test has no docstring"
    low = doc.lower()
    assert "candidate heading" in low, "the docstring does not name the population"
    assert "population" in low
    for needle in ("headless", "out of population", "checkpoint"):
        assert needle in low, f"the docstring does not state {needle!r}"
    assert "zero" in low, "the docstring does not state the ZERO tolerance"
    tolerance = re.search(r"zero.{0,240}?toler\w*\s+(two|2)\b", low, re.S)
    assert tolerance, \
        "the docstring does not say the replacement tolerates ZERO where the retired bound tolerated two"


# --------------------------------------------------------------------------
# 9 -- clone-proof
# --------------------------------------------------------------------------
def test_behavior9_this_file_can_never_evaporate_in_a_fresh_clone():
    src = pathlib.Path(__file__).read_text()
    assert len(src) > 2000, "this file was not really read"
    # positive control: a token that IS here, so absence below is real
    assert "_heading_parse_exceptions" in src
    for needle in (_SKIP_VERB, _OPTIONAL_IMPORT_VERB, _CORPUS_PATH_LITERAL):
        assert needle not in src, \
            f"{needle!r} would let a fresh clone drop a behavior of this iteration"
    assert dispatcher is not None and foundry is not None
