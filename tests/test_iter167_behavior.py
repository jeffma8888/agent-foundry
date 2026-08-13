"""Black-box behaviour tests for iteration 167 -- the pre-declared roadmap INDEX
PAYDOWN: the three SPENT item bodies (l)/(t)/(v) move out of
`PLATFORM_ROADMAP.md` into a new `## Compacted from the index by iter 167`
archive section, verbatim and byte-recoverable, each leaving a <=120-char stub.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-167 PM spec's
Expected Behaviors 1-14, the conventions found under `tests/`, the pre-existing
pins under `tests/` that the spec names, the two git-TRACKED markdown
deliverables the behaviors are ABOUT (`PLATFORM_ROADMAP.md` and
`PLATFORM_ROADMAP_ARCHIVE.md` -- those files ARE the artifact under test, not
implementation source), and the product's own OBSERVABLE behaviour (importing a
public name, calling it, running a fresh interpreter). `foundry.py` /
`dispatcher.py` SOURCE was not read. The engineer's notes, the reviewer's notes
and code `git diff` were not consulted.

NO GIT AT RUNTIME, AND THAT IS THE LOAD-BEARING DESIGN CHOICE HERE. Behavior 6
demands the three deleted spans be recoverable VERBATIM, which needs the PRE-move
text -- and the obvious `git show HEAD:PLATFORM_ROADMAP.md` is self-defeating:
while this file is being written HEAD is still the PRE-paydown commit, but the
moment the iteration commits, HEAD IS the compacted file and the identical
extraction returns the 47-char stub, so the recovery assertion silently inverts
from true to false. Preship re-runs this suite from a THROWAWAY FRESH CLONE at
exactly that commit. So each pre-move span is EMBEDDED below as a module literal,
which also pins the archived copy against any later re-wrap, re-indent or
paraphrase.

Every synthetic fixture is built in-process or in `tmp_path`; no assertion
depends on gitignored local state, on git history, or on the network (2026-08-11
operator rule). The only ambient files read are the two git-TRACKED markdown
files the spec names, plus a fresh-interpreter import smoke.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tests"))
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402  -- CALLED as a public interface, source never read
import test_iter158_behavior as t158  # noqa: E402  -- owns the archive rule + the pins

THIS_ITER = 167

ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ROADMAP_ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"

HEADING167 = "## Compacted from the index by iter 167"

# The spec's own pre-paydown measurement of the index, and its acceptance bounds.
# BOTH are now read THROUGH `index_growth_allowance` -- see the comment on it for
# why an absolute ceiling here was a scheduled revert. `ACCEPTED_MIN_HEADROOM` is
# GONE (iter 169): it expanded to `54000 - n >= 2000`, i.e. `n <= 52000`, which is
# `ACCEPTED_INDEX_CHARS` restated, so it pinned the same wall twice and carried no
# independent evidence.
PRE_PAYDOWN_INDEX_CHARS = 52570
ACCEPTED_INDEX_CHARS = 52000

# The maximum size the spec allows a retired item's remaining stub to be. It is
# ALSO the contract's cap on one ledger row, which is why the allowance below can
# reuse it rather than invent a second number.
MAX_STUB_CHARS = 120

# A ledger row, the one index edit the contract MANDATES every iteration.
_LEDGER_ROW_RE = re.compile(r"^- iter (\d+) ", re.M)


def post_paydown_ledger_rows(index_text: str) -> tuple[int, ...]:
    """Iteration numbers of ledger rows appended AFTER this iteration's paydown.

    Counted from the index TEXT itself, so the allowance below is derived from
    the file under test rather than from a number a maintainer has to remember
    to bump. Pure and total: a non-`str` yields `()`.
    """
    if not isinstance(index_text, str):
        return ()
    return tuple(sorted(
        int(number) for number in _LEDGER_ROW_RE.findall(index_text)
        if int(number) > THIS_ITER
    ))


def index_growth_allowance(index_text: str) -> int:
    """Chars the MANDATORY ledger-row contract is allowed to have added since the paydown.

    WHY THIS EXISTS (iter 169): `roles/pm.md` duty 3 REQUIRES every iteration to
    append one `- iter N ` row of at most `MAX_STUB_CHARS` chars to this index and
    FORBIDS ever deleting one, so the file grows monotonically by contract. A
    ceiling frozen at one commit's outcome is therefore a scheduled revert, not a
    threshold: iteration 169 measured the index 8 chars under
    `ACCEPTED_INDEX_CHARS`, so its own mandatory row RED'd this file and would
    have reverted a fully green iteration over a documentation-size figure --
    whatever feature it carried. That is the same defect shape iteration 166 fixed
    in the archive rule, which pinned the LAST heading and so encoded "this
    heading was appended last" as "it is last forever". (Named in prose, not as
    the code literal: iteration 166 also ships a substring guard forbidding that
    literal anywhere under `tests/`, and this docstring tripped it on the first
    full-suite run.)

    The allowance keeps iteration 167's REAL intent (the index must not reshuffle
    instead of net-reducing, and spent prose must not re-accumulate) by tolerating
    EXACTLY the growth the contract mandates and no more: the contract's own
    per-row cap times the number of post-paydown rows the index itself holds. Any
    OTHER growth -- a bloated new item body, spent prose creeping back -- still
    fails, which is the property a blanket bump to 54000 would have thrown away.

    Deliberately NOT applied to `foundry.ROADMAP_INDEX_HARD_CHARS`: that wall stays
    ABSOLUTE, because it is the backstop that says "archive spent prose" and an
    allowance on it would let the index grow forever one mandatory row at a time.
    """
    return MAX_STUB_CHARS * len(post_paydown_ledger_rows(index_text))

# behaviors 1-3 -- (item marker, the NEXT item marker that bounds its span).
STUB_BOUNDS = (
    ("(l) SHIPPED iter 160", "(o) "),
    ("(t) SHIPPED iter 156", "(u) "),
    ("(v) SHIPPED iter 163", "(w) "),
)

# behavior 4 -- one distinctive literal per moved body. Each is prose that ONLY
# ever appeared inside the body that moved, so its presence in the index means
# the body (or part of it) is still there.
MOVED_BODY_LITERALS = ("retry_ladder_lines", "PRESHIP_BUDGET_SECONDS", "fix_review.md")

# behavior 6 -- the three spans as they stood in the index BEFORE the move,
# byte-for-byte including internal newlines. Embedded, never re-extracted; see
# the module docstring for why git cannot be the source at runtime.
PRE_MOVE_SPAN_L = '(l) SHIPPED iter 160 -- `retry_ladder_lines()` derives every DISTINCT per-kind ladder by CALLING `retry_delay`, both docs\ncarry the rendered lines, and the guard asserts whole-line PRESENCE under arrow/whitespace normalisation (never a bare\ninteger). Detail in the archive.\n'
PRE_MOVE_SPAN_T = '(t) SHIPPED iter 156 -- `foundry preship` re-verifies the ship commit from a clone of the LOCAL repo between commit and push, bounded by one `PRESHIP_BUDGET_SECONDS` knob. Exit 1 (suite failed / sha mismatch) BLOCKS; exit 2 (clone, install or budget) is ADVISORY -- `postrelease_step` is still the backstop and a false block destroys a green iteration. Cited in `roles/final.md`. Detail in the archive.\n'
PRE_MOVE_SPAN_V = '(v) SHIPPED iter 163 -- `roles/engineer.md` + `roles/fix.md` (NOT `fix_review.md`, which does not exist) carry one\nrunnable `save-work` checkpoint line, so the iter-162 rescue finally FIRES; the every-suite bare-CLI brake polices it.\nCard edits need no dispatcher restart, which was the whole point of (v) over (j). Detail in the archive.\n'
PRE_MOVE_SPANS = (
    ("(l)", PRE_MOVE_SPAN_L),
    ("(t)", PRE_MOVE_SPAN_T),
    ("(v)", PRE_MOVE_SPAN_V),
)

# behavior 14 -- every literal iteration 166's five pins hold inside the
# INDEX BUDGET paragraph. Transcribed from the iteration-167 spec's behavior 14.
INDEX_BUDGET_LITERALS = (
    "594", "159", "165", "mean", "1,434", "222", "exclud", "paydown", "UNBLOCKED",
    "(f)", "(l)", "(t)", "(v)", "167", "DELETE",
    "## Compacted from the index by iter", "never copy", "- **iter ", "- iter ",
)


def _index_text() -> str:
    return ROADMAP.read_text(encoding="utf-8")


def _archive_text() -> str:
    return ROADMAP_ARCHIVE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Matchers -- TEXT in, verdict out. Every one takes a string and never a path,
# so the same code path judges the real tracked files and the synthetic
# fixtures of behavior 12. A matcher that can only ever see the real (green)
# file is not a guard, it is a decoration.
# --------------------------------------------------------------------------

def stub_span(index_text: str, marker: str, next_marker: str) -> str:
    """Return the text from `marker` up to the following `next_marker`.

    Raises ValueError naming the missing side, so a vanished item marker is a
    distinguishable failure from an oversized stub.
    """
    at = index_text.find(marker)
    if at < 0:
        raise ValueError("item marker %r is absent from the index" % marker)
    end = index_text.find(next_marker, at)
    if end < 0:
        raise ValueError("bounding marker %r not found after %r" % (next_marker, marker))
    return index_text[at:end]


def moved_body_literals_present(index_text: str) -> list[str]:
    """behavior 4's matcher: which moved-body literals the index STILL carries.

    Empty means every body really left. Non-empty names the offenders, because
    "one of three came back" and "all three were never moved" are different bugs.
    """
    return [lit for lit in MOVED_BODY_LITERALS if lit in index_text]


def archive_section(archive_text: str, heading: str) -> str:
    """Return the text of `heading`'s section: the heading up to the NEXT `## `.

    Bounded rather than "everything after the heading" so this stays correct
    once a later iteration appends its own compaction section below.
    """
    lines = archive_text.splitlines(keepends=True)
    out: list[str] = []
    inside = False
    for ln in lines:
        if ln.rstrip("\n") == heading:
            inside = True
            out.append(ln)
            continue
        if inside and ln.startswith("## "):
            break
        if inside:
            out.append(ln)
    return "".join(out)


def index_budget_paragraph(index_text: str) -> str:
    """The INDEX BUDGET paragraph: from the literal to the first blank line.

    The paragraph boundary IS the assertion surface for behavior 14 -- inserting
    a blank line mid-paragraph would silently truncate it, and the literal checks
    below would then report the trailing literals missing rather than passing.
    """
    at = index_text.find("INDEX BUDGET")
    if at < 0:
        raise ValueError("the INDEX BUDGET paragraph is absent from the index")
    end = index_text.find("\n\n", at)
    if end < 0:
        return index_text[at:]
    return index_text[at:end]


# --------------------------------------------------------------------------
# behaviors 1-3 -- each retired item keeps its marker and a <=120-char stub
# --------------------------------------------------------------------------

@pytest.mark.parametrize("marker,next_marker", STUB_BOUNDS)
def test_behaviors1to3_retired_item_keeps_its_marker(marker, next_marker):
    index = _index_text()
    assert marker in index, "the index no longer carries the item marker %r" % marker
    assert next_marker in index, "the bounding item marker %r vanished" % next_marker


@pytest.mark.parametrize("marker,next_marker", STUB_BOUNDS)
def test_behaviors1to3_stub_span_is_at_most_120_chars(marker, next_marker):
    span = stub_span(_index_text(), marker, next_marker)
    assert len(span) <= MAX_STUB_CHARS, (
        "stub for %r is %d chars, over the %d bound:\n%r"
        % (marker, len(span), MAX_STUB_CHARS, span)
    )


# --------------------------------------------------------------------------
# behavior 4 -- the moved bodies are ABSENT from the index
# --------------------------------------------------------------------------

def test_behavior4_moved_bodies_are_absent_from_the_index():
    still = moved_body_literals_present(_index_text())
    assert still == [], "the index still carries moved-body prose: %r" % (still,)


# --------------------------------------------------------------------------
# behavior 5 -- exactly ONE archive HEADING LINE is iteration 167's
# --------------------------------------------------------------------------

def test_behavior5_exactly_one_iter167_compaction_heading_line():
    headings = t158.archive_headings(_archive_text())
    found = [h for h in headings if h == HEADING167]
    assert len(found) == 1, (
        "expected exactly 1 %r HEADING line, found %d (headings: %r)"
        % (HEADING167, len(found), headings)
    )


def test_behavior5_counted_over_headings_not_raw_substrings():
    """A prose bullet may legitimately QUOTE the heading; that must not count."""
    synthetic = (
        HEADING167
        + "\n\nbody\n\n- **iter 900 -- a later bullet mentioning "
        + HEADING167
        + " in prose.**\n"
    )
    assert synthetic.count(HEADING167) == 2, "fixture should embed the string twice"
    headings = [h for h in t158.archive_headings(synthetic) if h == HEADING167]
    assert len(headings) == 1, (
        "heading-line counting must ignore the in-prose quote, got %d" % len(headings)
    )


# --------------------------------------------------------------------------
# behavior 6 -- every deleted span is recoverable VERBATIM from the section
# --------------------------------------------------------------------------

@pytest.mark.parametrize("label,span", PRE_MOVE_SPANS)
def test_behavior6_deleted_span_is_recoverable_verbatim(label, span):
    section = archive_section(_archive_text(), HEADING167)
    assert section, "the iter-167 archive section is empty or missing"
    hits = section.count(span)
    assert hits == 1, (
        "pre-move span for %s appears %d times (want exactly 1) in the iter-167 "
        "archive section; %d chars expected verbatim:\n%r"
        % (label, hits, len(span), span)
    )


@pytest.mark.parametrize("label,span", PRE_MOVE_SPANS)
def test_behavior6_internal_newlines_survived_byte_for_byte(label, span):
    """Re-wrapping is the likely corruption, so assert the line SHAPE too."""
    section = archive_section(_archive_text(), HEADING167)
    want_lines = span.splitlines()
    for line in want_lines:
        assert line in section, (
            "line from %s did not survive verbatim (re-wrapped?): %r" % (label, line)
        )
    assert len(want_lines) >= 1, "fixture span should be non-empty"
    joined = "\n".join(want_lines)
    assert joined in section, (
        "the %s body's lines are all present but not CONTIGUOUS in the section -- "
        "the paragraph was re-ordered or split" % label
    )


# --------------------------------------------------------------------------
# behavior 7 -- the frozen prefix is undisturbed; the iter-158 heading is unique.
# Driven through iteration 158's OWN shipped rule, imported not re-implemented.
# --------------------------------------------------------------------------

def test_behavior7_real_archive_passes_iteration158s_own_rule():
    violations = t158.archive_rule_violations(_archive_text())
    assert violations == [], "iter-158 archive rule reports: %r" % (violations,)


def test_behavior7_frozen_nine_heading_prefix_is_intact_and_still_nine():
    assert len(t158.FROZEN_ARCHIVE_HEADING_PREFIX) == 9, (
        "the frozen prefix should still be the nine iteration-158 headings, is %d"
        % len(t158.FROZEN_ARCHIVE_HEADING_PREFIX)
    )
    headings = t158.archive_headings(_archive_text())
    assert tuple(headings[:9]) == t158.FROZEN_ARCHIVE_HEADING_PREFIX, (
        "frozen prefix disturbed: %r" % (headings[:9],)
    )
    assert t158.compaction_heading_count(_archive_text()) == 1, (
        "expected exactly one iteration-158 compaction heading"
    )


def test_behavior7_the_new_section_was_APPENDED_after_the_frozen_prefix():
    headings = t158.archive_headings(_archive_text())
    assert HEADING167 in headings, "the iter-167 heading is not a heading line"
    assert headings.index(HEADING167) >= 9, (
        "the new section must sit at position ten or later, is at %d"
        % (headings.index(HEADING167) + 1)
    )


# --------------------------------------------------------------------------
# behavior 8 -- the index NET-REDUCED, measured with len() and never `wc -c`
# --------------------------------------------------------------------------

def test_behavior8_index_net_reduced_under_the_hard_wall():
    n = len(_index_text())
    assert n < foundry.ROADMAP_INDEX_HARD_CHARS, (
        "index is %d chars, at/over the %d hard wall" % (n, foundry.ROADMAP_INDEX_HARD_CHARS)
    )
    bound = PRE_PAYDOWN_INDEX_CHARS + index_growth_allowance(_index_text())
    assert n < bound, (
        "index is %d chars, not below the pre-paydown %d plus the mandatory-row "
        "allowance (= %d) -- the iteration reshuffled rather than net-reduced"
        % (n, PRE_PAYDOWN_INDEX_CHARS, bound)
    )


def test_behavior8_meets_the_specs_acceptance_bounds_for_this_paydown():
    n = len(_index_text())
    allowance = index_growth_allowance(_index_text())
    bound = ACCEPTED_INDEX_CHARS + allowance
    assert n <= bound, (
        "index is %d chars, over the accepted %d plus the mandatory-row allowance "
        "%d (= %d) -- growth beyond the contract's own ledger rows must be paid "
        "down into PLATFORM_ROADMAP_ARCHIVE.md, not allowanced"
        % (n, ACCEPTED_INDEX_CHARS, allowance, bound)
    )
    # The old second assert here (`headroom >= ACCEPTED_MIN_HEADROOM`) expanded to
    # `n <= ACCEPTED_INDEX_CHARS` -- the line above, restated. This replaces it with
    # the FORWARD-LOOKING property it never had: the NEXT mandatory ledger row must
    # still fit under the ABSOLUTE hard wall, so this brake reports the deadlock
    # one iteration BEFORE it reverts somebody's green shift.
    headroom = foundry.ROADMAP_INDEX_HARD_CHARS - n
    assert headroom >= MAX_STUB_CHARS, (
        "headroom to the %d hard wall is %d chars, under the %d one mandatory "
        "ledger row needs -- the NEXT iteration cannot record itself; archive spent "
        "prose now" % (foundry.ROADMAP_INDEX_HARD_CHARS, headroom, MAX_STUB_CHARS)
    )


# --------------------------------------------------------------------------
# behavior 9 -- the shipped detector still NAMES the three, now as minimal stubs
# --------------------------------------------------------------------------

def test_behavior9_spent_block_detector_still_names_the_three_labels():
    blocks = foundry.roadmap_spent_blocks(_index_text(), _archive_text())
    by_label = {b.label: b for b in blocks}
    for label in ("(l)", "(t)", "(v)"):
        assert label in by_label, (
            "roadmap_spent_blocks no longer names %r (named: %r)"
            % (label, sorted(by_label))
        )
        assert by_label[label].chars <= MAX_STUB_CHARS, (
            "detector reports %d chars for %s, over the %d stub bound"
            % (by_label[label].chars, label, MAX_STUB_CHARS)
        )


# --------------------------------------------------------------------------
# behavior 10 -- nothing the PREVIOUS compaction protected regressed
# --------------------------------------------------------------------------

def test_behavior10_iteration158_live_clauses_all_still_present():
    index = _index_text()
    missing = [c for c in t158.LIVE_CLAUSES if c not in index]
    assert missing == [], "hoisted live clauses lost from the index: %r" % (missing,)


def test_behavior10_every_surviving_item_marker_still_present():
    index = _index_text()
    missing = [m for m in t158.SURVIVING_MARKERS if m not in index]
    assert missing == [], "item markers dropped or renumbered: %r" % (missing,)


def test_behavior10_every_retired_substring_still_absent():
    index = _index_text()
    back = [s for s in t158.RETIRED_SUBSTRINGS if s in index]
    assert back == [], "previously retired prose reappeared in the index: %r" % (back,)


# --------------------------------------------------------------------------
# behavior 11 -- the ledger row / archive bullet pair for THIS iteration
# --------------------------------------------------------------------------

def test_behavior11_exactly_one_iter167_ledger_row_at_most_120_chars():
    rows = [ln for ln in _index_text().splitlines() if ln.startswith("- iter 167 ")]
    assert len(rows) == 1, "expected exactly 1 `- iter 167 ` ledger row, found %d" % len(rows)
    assert len(rows[0]) <= MAX_STUB_CHARS, (
        "ledger row is %d chars, over the %d bound: %r" % (len(rows[0]), MAX_STUB_CHARS, rows[0])
    )


def test_behavior11_exactly_one_iter167_archive_bullet():
    bullets = [ln for ln in _archive_text().splitlines() if ln.startswith("- **iter 167 ")]
    assert len(bullets) == 1, (
        "expected exactly 1 `- **iter 167 ` archive bullet, found %d" % len(bullets)
    )


def test_behavior11_no_archive_gaps_reported():
    gaps = foundry.roadmap_archive_gaps(_index_text(), _archive_text())
    assert list(gaps) == [], "roadmap_archive_gaps reports: %r" % (gaps,)


# --------------------------------------------------------------------------
# behavior 12 -- TWO-SIDED. A matcher that cannot fail is not a guard.
# All fixtures synthetic: built in-process or in tmp_path, never by editing a
# real file, so nothing here depends on gitignored or ambient state.
# --------------------------------------------------------------------------

def _synthetic_archive(headings) -> str:
    """A minimal archive carrying exactly `headings`, in order, each with a body."""
    return "".join("%s\nbody line %d\n\n" % (h, i) for i, h in enumerate(headings))


def test_behavior12_rule_ACCEPTS_a_faithful_synthetic_archive():
    """The accepting side, so a later rejection proves discrimination, not blanket refusal."""
    good = _synthetic_archive(t158.FROZEN_ARCHIVE_HEADING_PREFIX + (HEADING167,))
    assert t158.archive_rule_violations(good) == [], (
        "the rule rejected a faithful prefix + appended iter-167 section"
    )


def test_behavior12_rule_REJECTS_a_reordered_frozen_prefix():
    frozen = list(t158.FROZEN_ARCHIVE_HEADING_PREFIX)
    frozen[0], frozen[1] = frozen[1], frozen[0]
    bad = _synthetic_archive(tuple(frozen) + (HEADING167,))
    violations = t158.archive_rule_violations(bad)
    assert violations, "a REORDERED frozen prefix was accepted -- the guard is fail-open"


def test_behavior12_rule_REJECTS_a_deleted_frozen_heading(tmp_path):
    frozen = list(t158.FROZEN_ARCHIVE_HEADING_PREFIX)
    del frozen[4]
    bad = _synthetic_archive(tuple(frozen) + (HEADING167,))
    fixture = tmp_path / "PLATFORM_ROADMAP_ARCHIVE.md"
    fixture.write_text(bad, encoding="utf-8")
    violations = t158.archive_rule_violations(fixture.read_text(encoding="utf-8"))
    assert violations, "a DELETED frozen heading was accepted -- the guard is fail-open"


@pytest.mark.parametrize("label,span", PRE_MOVE_SPANS)
def test_behavior12_matcher_FLAGS_an_index_that_reinstated_a_moved_body(label, span):
    reinstated = "some unrelated live roadmap prose\n" + span + "(zz) the next item.\n"
    still = moved_body_literals_present(reinstated)
    assert still, (
        "behavior 4's matcher did not flag a reinstated %s body -- it cannot fail, "
        "so it proves nothing about the real index" % label
    )


def test_behavior12_matcher_is_clean_on_prose_that_never_held_a_body():
    assert moved_body_literals_present("(l) SHIPPED iter 160 -- detail in the archive.\n") == []


def test_behavior12_stub_span_raises_when_an_item_marker_vanishes():
    with pytest.raises(ValueError):
        stub_span("nothing here at all\n", "(l) SHIPPED iter 160", "(o) ")


# --------------------------------------------------------------------------
# behavior 13 -- markdown-only: both modules import in a FRESH interpreter
# --------------------------------------------------------------------------

def test_behavior13_foundry_and_dispatcher_import_in_a_fresh_interpreter():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher; print('OK')"],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, (
        "fresh-interpreter import failed (rc=%d)\nSTDOUT:%s\nSTDERR:%s"
        % (proc.returncode, proc.stdout, proc.stderr)
    )
    assert "OK" in proc.stdout, "import smoke printed %r" % proc.stdout


def test_behavior13_both_module_files_exist_and_are_non_empty():
    for name in ("foundry.py", "dispatcher.py"):
        path = _ROOT / name
        assert path.is_file(), "%s is missing" % name
        assert path.stat().st_size > 0, "%s is empty" % name


# --------------------------------------------------------------------------
# behavior 14 -- the INDEX BUDGET paragraph reads TRUE and keeps every pin
# --------------------------------------------------------------------------

def test_behavior14_paragraph_keeps_every_literal_iteration166_pinned():
    para = index_budget_paragraph(_index_text())
    missing = [lit for lit in INDEX_BUDGET_LITERALS if lit not in para]
    assert missing == [], (
        "INDEX BUDGET paragraph lost pinned literals %r -- either they were edited "
        "out or a blank line was introduced mid-paragraph, truncating it at %d chars"
        % (missing, len(para))
    )


def test_behavior14_paragraph_holds_no_blank_line():
    para = index_budget_paragraph(_index_text())
    assert "\n\n" not in para, "a blank line inside the paragraph splits it"
    assert all(ln.strip() for ln in para.splitlines()), (
        "a whitespace-only line inside the paragraph reads as a blank line to most renderers"
    )


def test_behavior14_paragraph_states_the_paydown_is_DONE_not_pending():
    para = index_budget_paragraph(_index_text())
    done = re.search(
        r"(?i)paydown[^.]{0,40}\b(?:done|complete|completed|executed|landed|shipped|paid)\b"
        r"[^.]{0,60}167",
        para,
    ) or re.search(
        r"(?i)167[^.]{0,60}\b(?:done|complete|completed|executed|landed|shipped)\b", para
    )
    assert done, (
        "the paragraph does not state that iteration 167 PERFORMED the paydown; "
        "it must not still pre-declare it as pending. Paragraph:\n%s" % para
    )
    pending = re.search(
        r"(?i)(?:next|upcoming|pending|planned|pre-declared|will be)[^.]{0,60}"
        r"paydown[^.]{0,60}167",
        para,
    ) or re.search(r"(?i)167[^.]{0,40}\b(?:is pending|will|remains open)\b", para)
    assert not pending, (
        "the paragraph still pre-declares iteration 167's paydown as future work: %r"
        % (pending.group(0),)
    )
