"""Iteration 228 -- BLACK-BOX behavior tests: the Done ledger becomes PAYABLE DOWN.

Two pure helpers name the `- iter N ` ledger rows the ARCHIVE already covers and no
caller has pinned (`roadmap_redundant_rows`) and delete exactly those rows, line-exact
(`roadmap_rows_removed`); the iteration then EXECUTES that paydown on the shipped
`PLATFORM_ROADMAP.md`, buying the index headroom the roadmap's own contract demands be
bought by archiving rather than by raising `ROADMAP_INDEX_HARD_CHARS`.

Spec under test (products/_platform/state/iter-228/pm.md), Expected Behaviors 1-8:
   1. `roadmap_redundant_rows(index_text, archive_text, pinned)` -> tuple of FROZEN
      records in ASCENDING ITERATION order, one per Done-ledger row, each exposing
      `iteration` (int), `row` (no trailing newline) and `chars` == `len(row) + 1`
      (a row costs the newline it owns).
   2. A row is EXCLUDED when its iteration has no `- **iter N ` archive bullet
      (history-loss guard): index names 5 and 6, archive carries only 5 -> just 5.
   3. A row is EXCLUDED when its iteration is in `pinned`; `pinned` is REQUIRED
      (never derived, never defaulted); an empty index yields `()`.
   4. `roadmap_rows_removed(index_text, iterations)` deletes exactly those rows WITH
      their newline and leaves EVERY other byte alone; a missing row is a silent no-op.
   5. Composition identity: deleting the detected rows raises `headroom` by exactly
      `sum(r.chars)`.
   6. The SHIPPED index no longer carries a Done row for the compacted iterations, and
      still carries one for every PINNED iteration and for the two frozen pin sets.
   7. The SHIPPED files satisfy every roadmap brake; the headroom FIGURE is reported,
      never re-asserted as a tighter floor (iteration 158's lesson).
   8. History survives in the SHIPPED archive text alone, with no git call, behind ONE
      stub pointer line naming the compacted range and the archive file.

Also guarded, from the spec's ACCEPTANCE CRITERIA rather than its Expected Behaviors, and
decidable from TRACKED text alone so it still holds in the clean clone the release gate
builds (iteration 194 shipped BROKEN because its roadmap record was only decidable after
commit):
   A. This iteration's roadmap record lands in the SAME diff as the code -- exactly one
      `- iter 228 ` ledger row of at most 120 chars and exactly one `- **iter 228 `
      archive bullet.

TWO SPEC DEVIATIONS ARE ENCODED HERE DELIBERATELY (see tester.md for the PM feedback):
Behavior 6 as written says the shipped index holds NO `- iter N ` row for ANY N in
126..198 and the Feature paragraph says 67 rows are compacted.  That premise is FALSE and
the spec contradicts itself: Behavior 3 says a PINNED iteration is excluded, and 28 of the
67 rows in that span ARE pinned by a live behavior module (derivation and per-row citation
below), so the largest legal paydown is 39 rows.  This module therefore tests the
reconciled reading -- every UNPINNED archive-covered row in the span is gone, every PINNED
one survives -- which is the reading Behavior 3, the helper's fail-closed contract and the
acceptance criterion "no test outside the known pin sets asserts a deleted row" all agree
on.  Likewise Behavior 8 says the archive holds a bullet for EVERY N in 126..198; six of
those iterations (150, 161, 171, 187, 193, 194) have no bullet AND never had an index row,
so nothing is lost -- the tested reading is that every iteration that HAD a row has a
bullet, which is what "history is not LOST" means.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-228 PM spec's Expected
Behaviors and Acceptance Criteria, the conventions of `tests/` (the docstring /
frozen-literal / two-sided-control shape of test_iter167 and test_iter185, which own the
same index budget), the sibling test modules' PUBLIC pin constants, and the product's OWN
OBSERVABLE surface -- importing the modules, calling their public functions and reading
the two roadmap files, which this card explicitly allows.  The implementation TEXT of
foundry.py / dispatcher.py was NOT read, and neither were engineer.md, reviewer.md,
fix_review.md, IMPLEMENTATION.patch nor `git diff`.

Offline and deterministic: no network, no subprocess, no sleeps, no clock, no git, no file
writes.  Nothing in the tree is mutated -- every negative case edits an in-memory copy of
the text.  Per OPERATOR 2026-08-11 no assertion reads `products/**/state/` or anything
else gitignored: the only files read are the two TRACKED roadmap files and TRACKED test
modules, so every verdict here also holds in a fresh clone.
"""

import ast
import dataclasses
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe

THIS_ITER = 228

ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
TESTS_DIR = _ROOT / "tests"

# The span this iteration paid down, as the spec names it.
SPAN_LO, SPAN_HI = 126, 198

# The binding wall is NOT `ROADMAP_INDEX_HARD_CHARS`: tests/test_iter185_behavior.py:361
# asserts `headroom >= ABSOLUTE_INDEX_FLOOR + MAX_ROW_CHARS`.  Quoted, not re-derived.
ABSOLUTE_INDEX_FLOOR = 4000   # tests/test_iter185_behavior.py:353
MAX_ROW_CHARS = 120           # tests/test_iter185_behavior.py:354, `roles/pm.md` duty 3
BINDING_FLOOR = ABSOLUTE_INDEX_FLOOR + MAX_ROW_CHARS

# ---------------------------------------------------------------------------
# The pin census, frozen.  DERIVED INDEPENDENTLY IN THIS STAGE by walking every module in
# tests/ for all four row-pin idioms the suite actually uses -- a literal `- iter N ` row
# prefix, a `THIS_ITER`-interpolated one (`%d`, f-string or `+ str(...)`), and a
# module-level iteration TUPLE driving a row assertion -- because a census of "modules
# that pin their OWN row" is structurally blind to a cross-module pin: iteration 172's
# only pin lives in test_iter174_behavior.py:91 `LANDED_ITERS = (172, 173, 174)`.
# Frozen as a literal rather than re-derived at test time on purpose: a derivation can go
# blind to a fifth idiom, whereas a literal that a future paydown must edit DELIBERATELY
# cannot.  Citation per row.
PINNED_IN_SPAN = (
    130, 131, 132, 133, 137, 140,   # literal `- iter N ` row in tests/test_iterN_behavior.py
    141, 142, 145,                  # THIS_ITER-interpolated row pin in their own module
    143, 154,                       # literal
    157, 158,                       # THIS_ITER-interpolated ("- iter %d " % THIS_ITER)
    164, 166, 167,                  # literal (166 also THIS_ITER)
    169, 170,                       # THIS_ITER-interpolated
    172,                            # CROSS-MODULE: test_iter174_behavior.py:91 LANDED_ITERS
    173, 174,                       # LANDED_ITERS + own-module pins
    183,                            # literal
    185, 186,                       # THIS_ITER-interpolated
    195, 196,                       # literal + THIS_ITER
    197, 198,                       # THIS_ITER-interpolated
)

# The 39 rows this iteration COMPACTED: every iteration in the span that has an archive
# bullet and is NOT pinned.  Written as bare ints, never as a `- iter N ` row literal, so
# that this module can never be mistaken for a NEW pin on a row it asserts is GONE.
COMPACTED_ITERS = (
    126, 127, 128, 129, 134, 135, 136, 138, 139, 144, 146, 147, 148, 149, 151, 152, 153,
    155, 156, 159, 160, 162, 163, 165, 168, 175, 176, 177, 178, 179, 180, 181, 182, 184,
    188, 189, 190, 191, 192,
)

# Iterations in the span with NO archive bullet -- they never landed an index row either,
# so nothing is lost (see the Behavior-8 deviation note in the module docstring).
NEVER_LANDED_IN_SPAN = (150, 161, 171, 187, 193, 194)

_ROW_RE = re.compile(r"(?m)^- iter (\d+) ")
_BULLET_RE = re.compile(r"(?m)^- \*\*iter (\d+) ")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _index_text():
    return ROADMAP.read_text(encoding="utf-8")


def _archive_text():
    return ARCHIVE.read_text(encoding="utf-8")


def _row_iterations(text):
    return sorted(int(n) for n in _ROW_RE.findall(text))


def _bullet_iterations(text):
    return sorted({int(n) for n in _BULLET_RE.findall(text)})


def _sibling_constant(module_name, const_name):
    """Read a module-level literal out of a sibling TEST module without importing it.

    `ast.literal_eval` on the parsed assignment: no import side effects, no duplication
    of a pin set this module does not own (the spec names both sets by file::CONST).
    """
    tree = ast.parse((TESTS_DIR / module_name).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == const_name:
                    return ast.literal_eval(node.value)
    raise AssertionError("%s::%s not found" % (module_name, const_name))


# A tiny, generic fixture pair.  Iteration numbers 5/6/7 are deliberately far from any
# real one, and the text is relative-only (no machine paths).
FIX_INDEX = (
    "## Done ledger\n"
    "- iter 7 -- seven landed\n"
    "- iter 5 -- five landed\n"
    "notes about - iter 6 - mid-line prose that is NOT a row\n"
    "  - iter 5 -- an INDENTED mention, also not a row\n"
    "- iter 6 -- six landed\n"
)
FIX_ARCHIVE = (
    "## Archive\n"
    "- **iter 5 -- five, in full\n"
    "- **iter 6 -- six, in full\n"
    "- **iter 7 -- seven, in full\n"
)


# ---------------------------------------------------------------------------
# 1. record shape, ascending iteration order, chars == len(row) + 1
# ---------------------------------------------------------------------------
def test_b1_records_are_frozen_ascending_and_priced_with_their_newline():
    rows = foundry.roadmap_redundant_rows(FIX_INDEX, FIX_ARCHIVE, ())

    assert isinstance(rows, tuple), "must return a tuple, got %r" % type(rows)
    # ASCENDING ITERATION order, not document order: the fixture lists 7 before 5.
    assert [r.iteration for r in rows] == [5, 6, 7], (
        "expected ascending iteration order [5, 6, 7], got %r"
        % [r.iteration for r in rows]
    )

    by_iter = {r.iteration: r for r in rows}
    assert by_iter[5].row == "- iter 5 -- five landed", repr(by_iter[5].row)
    assert by_iter[7].row == "- iter 7 -- seven landed", repr(by_iter[7].row)
    for r in rows:
        assert isinstance(r.iteration, int) and not isinstance(r.iteration, bool)
        assert isinstance(r.row, str)
        assert not r.row.endswith("\n"), "row must carry NO trailing newline: %r" % r.row
        # A row costs its own newline -- the off-by-one that decides whether the NEXT
        # mandatory ledger row is legal.
        assert r.chars == len(r.row) + 1, (
            "chars must price the newline the row owns: %d != %d + 1"
            % (r.chars, len(r.row))
        )

    # FROZEN record (the spec says "frozen records").
    assert dataclasses.is_dataclass(rows[0])
    assert dataclasses.fields(rows[0])  # a real record, not an opaque object
    with pytest.raises(dataclasses.FrozenInstanceError):
        rows[0].iteration = 999

    # Anchored: neither the indented mention nor the mid-line prose is a row.
    assert len(rows) == 3, "prose/indented mentions must not be counted: %r" % (rows,)


# ---------------------------------------------------------------------------
# 2. history-loss guard -- no archive bullet means NOT deletable
# ---------------------------------------------------------------------------
def test_b2_row_excluded_when_the_archive_has_no_bullet():
    archive_missing_6 = "## Archive\n- **iter 5 -- five, in full\n"
    index = "- iter 5 -- five landed\n- iter 6 -- six landed\n"

    rows = foundry.roadmap_redundant_rows(index, archive_missing_6, ())
    assert [r.iteration for r in rows] == [5], (
        "iteration 6 has no archive bullet, so its row is the ONLY copy of that history "
        "and must NOT be reported deletable; got %r" % [r.iteration for r in rows]
    )

    # Two-sided: add the bullet back and 6 becomes deletable.  Without this the guard
    # could pass by never reporting anything.
    rows2 = foundry.roadmap_redundant_rows(
        index, archive_missing_6 + "- **iter 6 -- six, in full\n", ()
    )
    assert [r.iteration for r in rows2] == [5, 6]


# ---------------------------------------------------------------------------
# 3. `pinned` is honored, REQUIRED, and an empty index yields ()
# ---------------------------------------------------------------------------
def test_b3_pinned_is_honored_required_and_empty_index_is_empty():
    rows = foundry.roadmap_redundant_rows(FIX_INDEX, FIX_ARCHIVE, (5, 7))
    assert [r.iteration for r in rows] == [6], (
        "pinned iterations must be excluded; got %r" % [r.iteration for r in rows]
    )

    # A set, a list and a generator are all acceptable iterables of ints.
    assert [r.iteration for r in foundry.roadmap_redundant_rows(FIX_INDEX, FIX_ARCHIVE, [6])] == [5, 7]
    assert [r.iteration for r in foundry.roadmap_redundant_rows(FIX_INDEX, FIX_ARCHIVE, {6})] == [5, 7]
    assert [r.iteration for r in foundry.roadmap_redundant_rows(FIX_INDEX, FIX_ARCHIVE, iter([6]))] == [5, 7]

    # REQUIRED: a defaulted empty pin set would make the UNSAFE call the convenient one.
    with pytest.raises(TypeError):
        foundry.roadmap_redundant_rows(FIX_INDEX, FIX_ARCHIVE)

    assert foundry.roadmap_redundant_rows("", FIX_ARCHIVE, ()) == ()
    assert foundry.roadmap_redundant_rows("", "", ()) == ()
    # Pinning everything is the same as an empty index.
    assert foundry.roadmap_redundant_rows(FIX_INDEX, FIX_ARCHIVE, (5, 6, 7)) == ()


# ---------------------------------------------------------------------------
# 4. `roadmap_rows_removed` is line-exact and byte-conservative
# ---------------------------------------------------------------------------
def test_b4_rows_removed_is_line_exact_and_byte_conservative():
    out = foundry.roadmap_rows_removed(FIX_INDEX, [6])
    expected = "".join(
        ln for ln in FIX_INDEX.splitlines(keepends=True)
        if not ln.startswith("- iter 6 ")
    )
    assert out == expected, "line-exact deletion expected:\n%r\ngot:\n%r" % (expected, out)
    # The row took its own newline with it, and NOTHING else moved.
    assert len(out) == len(FIX_INDEX) - len("- iter 6 -- six landed\n")
    # The non-row mentions of 6 survive verbatim.
    assert "notes about - iter 6 - mid-line prose that is NOT a row\n" in out
    assert "  - iter 5 -- an INDENTED mention, also not a row\n" in out

    # Silent no-op for an iteration with no row -- a caller re-applying a list to an
    # already-compacted file must get the same file back.
    assert foundry.roadmap_rows_removed(out, [6]) == out
    assert foundry.roadmap_rows_removed(FIX_INDEX, []) == FIX_INDEX
    assert foundry.roadmap_rows_removed(FIX_INDEX, [4242]) == FIX_INDEX
    assert foundry.roadmap_rows_removed("", [5]) == ""

    # Removing every row leaves exactly the non-row lines.
    stripped = foundry.roadmap_rows_removed(FIX_INDEX, [5, 6, 7])
    assert _row_iterations(stripped) == []
    assert stripped.startswith("## Done ledger\n")

    # A missing final newline survives (no normalisation).
    no_nl = "- iter 5 -- five\n- iter 6 -- six"
    assert foundry.roadmap_rows_removed(no_nl, [5]) == "- iter 6 -- six"
    assert foundry.roadmap_rows_removed(no_nl, [6]) == "- iter 5 -- five\n"

    # CRLF line endings survive on the lines that are kept.
    crlf = "## D\r\n- iter 5 -- five\r\n- iter 6 -- six\r\n"
    assert foundry.roadmap_rows_removed(crlf, [5]) == "## D\r\n- iter 6 -- six\r\n"


# ---------------------------------------------------------------------------
# 5. composition identity, on the SHIPPED files (in memory only)
# ---------------------------------------------------------------------------
def test_b5_composition_raises_headroom_by_exactly_the_rows_deleted():
    index, archive = _index_text(), _archive_text()
    rows = foundry.roadmap_redundant_rows(index, archive, ())
    assert rows, "the shipped index still holds Done rows, so this must not be vacuous"

    new = foundry.roadmap_rows_removed(index, [r.iteration for r in rows])
    before = foundry.roadmap_index_budget(index).headroom
    after = foundry.roadmap_index_budget(new).headroom
    assert after == before + sum(r.chars for r in rows), (
        "headroom must rise by exactly sum(r.chars): %d != %d + %d"
        % (after, before, sum(r.chars for r in rows))
    )
    # And on the fixture, where the arithmetic is checkable by eye.
    fx_rows = foundry.roadmap_redundant_rows(FIX_INDEX, FIX_ARCHIVE, ())
    fx_new = foundry.roadmap_rows_removed(FIX_INDEX, [r.iteration for r in fx_rows])
    assert len(FIX_INDEX) - len(fx_new) == sum(r.chars for r in fx_rows)


# ---------------------------------------------------------------------------
# 6. the paydown LANDED in the shipped index
# ---------------------------------------------------------------------------
def test_b6_shipped_index_shed_every_unpinned_row_in_the_span():
    index = _index_text()
    present = set(_row_iterations(index))

    still_there = sorted(n for n in COMPACTED_ITERS if n in present)
    assert still_there == [], (
        "these archive-covered, unpinned Done rows were supposed to be compacted out of "
        "the index: %r" % still_there
    )

    missing_pins = sorted(n for n in PINNED_IN_SPAN if n not in present)
    assert missing_pins == [], (
        "a PINNED Done row was deleted -- the fail-closed exclusion in Behavior 3 exists "
        "precisely to prevent this: %r" % missing_pins
    )
    for n in PINNED_IN_SPAN:
        rows = [ln for ln in index.splitlines() if ln.startswith("- iter %d " % n)]
        assert len(rows) == 1, "expected exactly one iter-%d row, got %d" % (n, len(rows))

    # The span now holds EXACTLY the pinned rows -- no stragglers either way.
    in_span = sorted(n for n in present if SPAN_LO <= n <= SPAN_HI)
    assert in_span == sorted(PINNED_IN_SPAN), (
        "the span must hold exactly the pinned rows; got %r" % in_span
    )

    # The two frozen pin sets the spec names by file::CONST, read from those files.
    frozen = _sibling_constant("test_iter122_behavior.py", "FROZEN")
    recovered = _sibling_constant("test_iter124_behavior.py", "RECOVERED_LEDGER")
    assert max(frozen) <= 119 and tuple(recovered) == (122, 124)
    outside = sorted(n for n in set(frozen) | set(recovered) if n not in present)
    assert outside == [], "rows outside the compacted span must be untouched: %r" % outside

    # And every iteration the spec names as still-live above the span.
    for n in (200, 202, 204, *range(206, 221), 226, 227, THIS_ITER):
        assert n in present, "iter-%d row must survive the paydown" % n


def test_b6b_mutation_control_the_detector_and_the_paydown_agree():
    """Neither half of Behavior 6 can pass vacuously.

    Re-insert one compacted row into an in-memory copy and the detector must name it
    again (so the rows really were deletable), while every PINNED row must stay
    un-named when the live pin set is supplied (so survival is the pin, not luck).
    """
    index, archive = _index_text(), _archive_text()
    victim = COMPACTED_ITERS[0]
    revived = index.replace(
        "\n- iter %d " % PINNED_IN_SPAN[0],
        "\n- iter %d -- a re-inserted redundant row\n- iter %d " % (victim, PINNED_IN_SPAN[0]),
        1,
    )
    assert victim in _row_iterations(revived), "fixture must actually re-insert the row"
    named = [r.iteration for r in foundry.roadmap_redundant_rows(revived, archive, PINNED_IN_SPAN)]
    assert victim in named, (
        "the detector must name the re-inserted row as redundant -- otherwise the "
        "paydown's premise is untested"
    )
    assert not (set(named) & set(PINNED_IN_SPAN)), (
        "no pinned iteration may ever be named redundant: %r"
        % sorted(set(named) & set(PINNED_IN_SPAN))
    )
    # On the SHIPPED text the span is already fully paid down.
    named_live = [
        r.iteration
        for r in foundry.roadmap_redundant_rows(index, archive, PINNED_IN_SPAN)
        if SPAN_LO <= r.iteration <= SPAN_HI
    ]
    assert named_live == [], "no unpinned row may remain in the span: %r" % named_live


# ---------------------------------------------------------------------------
# 7. every roadmap brake is green on the SHIPPED files
# ---------------------------------------------------------------------------
def test_b7_shipped_files_satisfy_every_roadmap_brake():
    index, archive = _index_text(), _archive_text()

    assert foundry.roadmap_archive_gaps(index, archive) == []
    assert foundry.roadmap_ledger_gaps(index, archive, (195,)) == []

    budget = foundry.roadmap_index_budget(index)
    assert budget.over_budget is False, budget
    # REPORTED, never asserted as a tighter floor: iteration 158's lesson is to not
    # install a new wall tighter than the one you just escaped.  Only the EXISTING
    # binding floor is asserted.
    assert budget.headroom >= BINDING_FLOOR, (
        "headroom %d is below the binding floor %d (= %d + %d); the paydown did not buy "
        "enough" % (budget.headroom, BINDING_FLOOR, ABSOLUTE_INDEX_FLOOR, MAX_ROW_CHARS)
    )
    print(
        "iter 228 index budget: char_count=%d headroom=%d binding_floor=%d slack=%d"
        % (budget.char_count, budget.headroom, BINDING_FLOOR, budget.headroom - BINDING_FLOOR)
    )
    # DELIBERATELY NOT ASSERTED: "headroom >= BINDING_FLOOR + MAX_ROW_CHARS", i.e. room
    # for one mandatory row BEYOND the floor.  It holds today with room to spare, but
    # Behavior 7 forbids it in as many words -- the figure is REPORTED, never re-asserted
    # as a tighter floor -- and it would be exactly iteration 158's mistake: a NEW wall
    # 120 chars tighter than the one this paydown just escaped, tripping one iteration
    # sooner than the brake that actually owns the rule (test_iter185:361).  That the
    # paydown bought real room is proved by Behavior 6 (39 rows gone) and the Behavior-5
    # identity, not by moving the wall.


def test_b7b_the_brakes_are_two_sided_not_vacuous():
    """Strip a record from an in-memory copy and each oracle must FLIP."""
    index, archive = _index_text(), _archive_text()

    # Drop a surviving row from the index -> ledger gap (the archive still has it, so
    # `roadmap_ledger_gaps` is the oracle that must notice, per its own contract that a
    # record in EITHER file counts).
    victim = PINNED_IN_SPAN[0]
    stripped_archive = "".join(
        ln for ln in archive.splitlines(keepends=True)
        if not ln.startswith("- **iter %d " % victim)
    )
    assert stripped_archive != archive, "fixture must actually strip a bullet"
    assert foundry.roadmap_archive_gaps(index, stripped_archive) != [], (
        "removing iter-%d's archive bullet must produce an archive gap" % victim
    )

    # And the budget oracle flips when the index is padded past the wall.
    padded = index + ("x" * foundry.ROADMAP_INDEX_HARD_CHARS)
    assert foundry.roadmap_index_budget(padded).over_budget is True


# ---------------------------------------------------------------------------
# 8. history survives in the ARCHIVE TEXT alone, behind ONE stub pointer
# ---------------------------------------------------------------------------
def test_b8_history_survives_in_the_archive_text_with_no_git_call():
    archive = _archive_text()
    bullets = set(_bullet_iterations(archive))

    lost = sorted(n for n in COMPACTED_ITERS if n not in bullets)
    assert lost == [], (
        "a compacted row's history is GONE -- these iterations have no `- **iter N ` "
        "archive bullet: %r" % lost
    )
    # Pinned rows are archived too, so the archive alone carries the whole span that
    # ever landed.
    lost_pinned = sorted(n for n in PINNED_IN_SPAN if n not in bullets)
    assert lost_pinned == [], lost_pinned

    # The six iterations with no bullet never landed a row either, so nothing is lost.
    index = _index_text()
    present = set(_row_iterations(index))
    for n in NEVER_LANDED_IN_SPAN:
        assert n not in bullets, "iter %d unexpectedly gained an archive bullet" % n
        assert n not in present, "iter %d unexpectedly has an index row" % n
    covered = set(COMPACTED_ITERS) | set(PINNED_IN_SPAN) | set(NEVER_LANDED_IN_SPAN)
    assert covered == set(range(SPAN_LO, SPAN_HI + 1)), (
        "the three frozen sets must partition the span exactly; missing %r"
        % sorted(set(range(SPAN_LO, SPAN_HI + 1)) - covered)
    )
    assert len(COMPACTED_ITERS) == 39 and len(PINNED_IN_SPAN) == 28


def test_b8b_exactly_one_stub_pointer_names_the_compacted_range():
    index = _index_text()
    stubs = [
        ln for ln in index.splitlines()
        if ln.startswith("- iters ") and str(SPAN_LO) in ln and str(SPAN_HI) in ln
    ]
    assert len(stubs) == 1, (
        "expected exactly ONE stub pointer line for the compacted range, got %d: %r"
        % (len(stubs), stubs)
    )
    stub = stubs[0]
    assert "%d-%d" % (SPAN_LO, SPAN_HI) in stub, stub
    assert "PLATFORM_ROADMAP_ARCHIVE.md" in stub, (
        "the stub must point a reader at the file that now holds the detail: %r" % stub
    )
    # The stub is a POINTER, not a replacement history: it must not smuggle the deleted
    # rows back in as a list.
    assert not _ROW_RE.search(stub + "\n")


# ---------------------------------------------------------------------------
# A. this iteration's own roadmap record, in the SAME diff as the code
# ---------------------------------------------------------------------------
def test_a_iteration_228_roadmap_record_lands_with_the_code():
    index, archive = _index_text(), _archive_text()

    rows = [ln for ln in index.splitlines() if ln.startswith("- iter %d " % THIS_ITER)]
    assert len(rows) == 1, "expected exactly one `- iter %d ` ledger row, got %r" % (
        THIS_ITER, rows,
    )
    assert len(rows[0]) <= MAX_ROW_CHARS, (
        "ledger row is %d chars, cap is %d: %r" % (len(rows[0]), MAX_ROW_CHARS, rows[0])
    )

    bullets = [ln for ln in archive.splitlines() if ln.startswith("- **iter %d " % THIS_ITER)]
    assert len(bullets) == 1, "expected exactly one `- **iter %d ` archive bullet, got %d" % (
        THIS_ITER, len(bullets),
    )

    # Both helpers are importable public surface, and dispatcher imports cleanly (the
    # module-level `import dispatcher` above is that probe).
    assert callable(foundry.roadmap_redundant_rows)
    assert callable(foundry.roadmap_rows_removed)
    assert dispatcher is not None
# ---------------------------------------------------------------------------
# 4b. depth on Behavior 4: the helpers are PURE and duplicate-tolerant
# ---------------------------------------------------------------------------
def test_b4b_helpers_are_pure_duplicate_tolerant_and_write_no_file():
    """A paydown caller composes lists; deleting a row twice must not eat a second line."""
    once = foundry.roadmap_rows_removed(FIX_INDEX, [6])
    assert isinstance(once, str)
    assert foundry.roadmap_rows_removed(FIX_INDEX, [6, 6]) == once, (
        "a duplicated iteration must delete ONE row, not two"
    )
    assert foundry.roadmap_rows_removed(FIX_INDEX, [7, 5]) == foundry.roadmap_rows_removed(
        FIX_INDEX, [5, 7]
    ), "the result must not depend on the caller's ordering"
    # Deleting in two passes == deleting in one.
    assert foundry.roadmap_rows_removed(once, [5]) == foundry.roadmap_rows_removed(
        FIX_INDEX, [5, 6]
    )

    # PURE: on the SHIPPED files, reading is the only effect.  Byte-compared, because a
    # helper that "fixed" the file itself would make every other assertion here circular.
    before_index, before_archive = ROADMAP.read_bytes(), ARCHIVE.read_bytes()
    index, archive = before_index.decode("utf-8"), before_archive.decode("utf-8")
    rows = foundry.roadmap_redundant_rows(index, archive, PINNED_IN_SPAN)
    foundry.roadmap_rows_removed(index, [r.iteration for r in rows])
    assert ROADMAP.read_bytes() == before_index, "the helpers must not write the index"
    assert ARCHIVE.read_bytes() == before_archive, "the helpers must not write the archive"
    # And the caller's own strings are untouched (str is immutable, so this pins that the
    # helper returns a NEW text rather than reporting success on the original).
    assert index == before_index.decode("utf-8")


# ---------------------------------------------------------------------------
# 6c. STATIC census: no sibling test module pins a row this iteration deleted
# ---------------------------------------------------------------------------
# The acceptance criterion "no test outside the two known pin sets asserts a deleted row"
# is proved by the FULL suite, but only after ~7.7k tests run.  This decides the same
# question statically, over the three pin idioms the suite actually uses, so a future
# paydown gets a NAMED module instead of a red assertion three files away.
#
# The `PLATFORM_ROADMAP.md` filter is what makes the collection idiom usable rather than
# noisy: tests/test_iter179_behavior.py holds `GIT_PROVEN_SHIPPED = (118, 177)` and 177 IS
# compacted, but that module never reads the shipped index -- it builds its own directions
# log fixtures in memory, so its ints cannot pin a shipped ledger row.
_ROW_IDIOM_RE = re.compile(r"""(?:["']- iter %d |f["']- iter \{|["']- iter ["']\s*\+)""")


def _module_level_int_collections(tree):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            try:
                value = ast.literal_eval(node.value)
            except Exception:
                continue
            if isinstance(value, (tuple, list, set, frozenset)):
                ints = {v for v in value if isinstance(v, int) and not isinstance(v, bool)}
                if ints:
                    yield [t.id for t in node.targets if isinstance(t, ast.Name)], ints


def _module_this_iter(tree):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "THIS_ITER":
                    try:
                        return ast.literal_eval(node.value)
                    except Exception:
                        return None
    return None


def _pin_census(compacted):
    """{module_name: [reasons]} for every sibling module that pins a COMPACTED row."""
    compacted = set(compacted)
    self_name = pathlib.Path(__file__).name
    hits = {}
    for path in sorted(TESTS_DIR.glob("*.py")):
        if path.name == self_name:
            continue
        text = path.read_text(encoding="utf-8")
        literal = sorted(n for n in compacted if "- iter %d " % n in text)
        if literal:
            hits.setdefault(path.name, []).append(("literal row prefix", literal))
        if "PLATFORM_ROADMAP.md" not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:  # pragma: no cover -- the suite would already be red
            continue
        for names, ints in _module_level_int_collections(tree):
            shared = sorted(ints & compacted)
            if shared:
                hits.setdefault(path.name, []).append((names or ["<unnamed>"], shared))
        if _ROW_IDIOM_RE.search(text):
            this = _module_this_iter(tree)
            if this in compacted:
                hits.setdefault(path.name, []).append(("interpolated THIS_ITER", [this]))
    return hits


def test_b6c_no_sibling_test_module_pins_a_compacted_row():
    hits = _pin_census(COMPACTED_ITERS)
    assert hits == {}, (
        "these sibling test modules still pin a Done row this iteration deleted, so the "
        "paydown over-reached: %r" % hits
    )


def test_b6c_control_the_census_catches_a_cross_module_tuple_pin():
    """Non-vacuous: iteration 172's ONLY pin is another module's tuple.

    `tests/test_iter174_behavior.py` reads the shipped index and holds
    `LANDED_ITERS = (172, 173, 174)` at module level -- 172 is the iteration whose lost
    patch 173/174 re-landed, so reasoning about "modules that pin their OWN row" is
    structurally blind to it.  Feed the census a compacted set that wrongly includes 172
    and it must NAME that module; that is the difference between this guard and a census
    that passes by looking in the wrong place.
    """
    control = _pin_census(tuple(COMPACTED_ITERS) + (172,))
    assert "test_iter174_behavior.py" in control, (
        "the census must catch a cross-module tuple pin; it reported %r" % control
    )
    assert 172 not in COMPACTED_ITERS and 172 in PINNED_IN_SPAN, (
        "172 must be PINNED, not compacted -- its row survives in the shipped index"
    )
