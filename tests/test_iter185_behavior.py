"""Iteration 185 -- BLACK-BOX behavior tests: the roadmap CLI-verb figure brake.

Spec under test (products/_platform/state/iter-185/pm.md), Expected Behaviors 1-13:

   1. `roadmap_verb_figure_gaps(index_text, live_verb_count)` exists and returns a SORTED tuple
   2. a stale figure against a differing live count -> exactly ONE gap naming BOTH numbers
   3. a matching figure -> `()`
   4. BOTH a matching and a mismatching figure in ONE text -> exactly ONE gap (two-sided within
      a single input)
   5. PURE and TOTAL: no filesystem/subprocess/network/clock, no argument mutation, repeatable,
      and degenerate input (non-`str`, empty, no figure) returns `()` without raising
   6. LIVE-TREE anchor: the live index measures `()` against the live CLI-verb count
   7. the live index no longer carries the stale figure, and `(p)` is gone from `STILL OPEN:`
   8. the live index still carries the `(p) ` marker as ONE retired line of <= 120 chars
   9. the archive carries the retired body under a NEW FINAL `## ` heading, the move DELETED it
      from the index, and the pre-existing heading order is unchanged
  10. neither `tests/test_iter164_behavior.py` nor `tests/test_iter173_behavior.py` pins the frozen
      literal any more; each replacement derives from the new brake or from `foundry_cli_verbs`
  11. index headroom under the hard char cap leaves room for the NEXT mandatory ledger row
      above iter 182's absolute floor (see the comment on the test -- the original literal
      was an achievement pin, retired at the iteration-186 fix pass)
  12. DORMANT: zero call sites in the running pipeline; `foundry` + `dispatcher` still import
  13. the iteration record lands in THIS commit (ledger row, archive bullet, STATUS line)

  +  Acceptance criteria: TWO-SIDED calibration (a PLANTED known-bad is FLAGGED beside the clean
     live index), SCOPE calibration (the live ARCHIVE is NOT in the brake's domain -- pointing the
     brake at it would red frozen historical rows), and the retired pins really gone.

ISOLATION CONTRACT (HONORED): written from the iter-185 PM spec, the conventions of the existing
`tests/test_iter17*/18*_behavior.py` modules, and the product's OWN OBSERVABLE surface -- CALLING
its public function and reading the TRACKED DOCUMENTS the spec is about (`PLATFORM_ROADMAP.md`,
`PLATFORM_ROADMAP_ARCHIVE.md`, other test modules).  The implementation TEXT of `foundry.py` was NOT
read by the author, and neither were `engineer.md`, `reviewer.md`, `IMPLEMENTATION.patch`, nor
`git diff`.  The one place this module touches `foundry.py` at all is the MECHANICAL token scan that
enforces behavior 12's additive-dormant criterion (no human read), and that scan carries its own
anti-vacuous control -- the iter-177 convention.

OFFLINE + FRESH-CLONE SAFE: no network, no subprocess, no sleeps, no clock.  Every path asserted on
(`PLATFORM_ROADMAP.md`, `PLATFORM_ROADMAP_ARCHIVE.md`, `foundry.py`, `dispatcher.py`, two test
modules) is git-TRACKED, so nothing depends on gitignored ambient state.  Nothing is mutated.
"""
from __future__ import annotations

import builtins
import pathlib
import re
import socket
import subprocess
import sys
import time

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

THIS_ITER = 185

ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
GAPS = "roadmap_verb_figure_gaps"

# The two frozen literals iteration 185 retires.  BUILT from parts, never embedded whole, so a
# future `rg -F` sweep for a pinned assertion cannot mistake this module's PLANTED FIXTURE for
# one (iter-117 build-never-embed convention).
STALE = "48" + " CLI verbs"
OLDER = "46" + " CLI verbs"
CLEAN = "50" + " CLI verbs"

# The retired body's own heading in the archive, and the marker the index must keep.
ARCHIVE_HEADING = "## Compacted from the index by iter " + str(THIS_ITER)
P_MARKER = "(p) "

_PIPELINE_MODULES = ("foundry" + ".py", "dispatcher" + ".py")


def _boom(*a, **k):  # pragma: no cover - the trap must never be sprung
    raise AssertionError("purity violation: the function reached out to the world")


def _fn():
    fn = getattr(foundry, GAPS, None)
    assert callable(fn), f"foundry.{GAPS} must exist and be callable"
    return fn


def _live_verb_count():
    verbs = foundry.foundry_cli_verbs((_ROOT / "foundry" ".py").read_text(encoding="utf-8"))
    assert verbs, "control: the live CLI verb set failed to parse"
    return len(verbs)


def _numbers(gap):
    """Every integer a gap record reports, however it chooses to render itself."""
    return [int(n) for n in re.findall(r"-?\d+", repr(gap))]


def _still_open_block(index_text):
    """The `STILL OPEN:` list -- from its label up to the next top-level label."""
    lines = index_text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("STILL OPEN:"))
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("NEXT UP")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _archive_headings(archive_text):
    return [ln for ln in archive_text.splitlines() if ln.startswith("## ")]


def _archive_section(archive_text, heading):
    """The body lines under `heading`, up to the next `## ` heading or EOF."""
    lines = archive_text.splitlines()
    start = lines.index(heading)
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return [ln for ln in lines[start + 1:end] if ln.strip()]


# ============================================================== behavior 1
def test_b01_exists_returns_a_sorted_tuple():
    fn = _fn()
    out = fn("a document with no CLI-verb figure at all", 50)
    assert isinstance(out, tuple), f"must return a tuple, got {type(out).__name__}"
    assert out == (), f"a clean text must measure (), got {out!r}"

    many = fn(f"first {CLEAN}, then 60 CLI verbs, then {STALE}", 50)
    assert len(many) == 2, f"expected the two mismatching figures, got {many!r}"
    assert list(many) == sorted(many), f"the returned tuple is not SORTED: {many!r}"
    claimed = [_numbers(g)[0] for g in many]
    assert claimed == [48, 60], f"sorted order should be ascending by figure, got {claimed}"


# ============================================================== behavior 2
def test_b02_a_stale_figure_is_flagged_and_names_both_numbers():
    """PLANTED known-bad fixture -- the two-sided half of the calibration."""
    gaps = _fn()(f"TOP bite after the paydown: {STALE}, TWO absent from the index", 50)
    assert len(gaps) == 1, f"expected exactly ONE gap, got {gaps!r}"
    nums = _numbers(gaps[0])
    assert 48 in nums, f"the gap must name the CLAIMED figure 48: {gaps[0]!r}"
    assert 50 in nums, f"the gap must name the EXPECTED figure 50: {gaps[0]!r}"


# ============================================================== behavior 3
def test_b03_a_matching_figure_is_clean():
    assert _fn()(f"the index says {CLEAN} today", 50) == ()
    assert _fn()(f"the index says {OLDER} today", 46) == ()


# ============================================================== behavior 4
def test_b04_two_sided_within_one_input():
    gaps = _fn()(f"header claims {CLEAN}; the stale bite below still claims {STALE}", 50)
    assert len(gaps) == 1, f"only the MISMATCHING figure may be reported, got {gaps!r}"
    nums = _numbers(gaps[0])
    assert 48 in nums, f"the reported gap is not the stale one: {gaps[0]!r}"
    assert nums.count(50) == 1, (
        f"50 is the EXPECTED count, it must not also be reported as claimed: {gaps[0]!r}"
    )


# ============================================================== behavior 5
@pytest.mark.parametrize(
    "bad", [None, 123, 4.5, [], (), {}, STALE.encode(), object()],
    ids=["none", "int", "float", "list", "tuple", "dict", "bytes", "object"],
)
def test_b05a_total_on_non_str_input(bad):
    assert _fn()(bad, 50) == ()


def test_b05b_total_on_empty_and_figureless_text():
    fn = _fn()
    assert fn("", 50) == ()
    assert fn("\n\n", 50) == ()
    assert fn("verbs are mentioned but no figure precedes them", 50) == ()
    near_miss = fn(STALE + "omething", 50)  # a near-miss must not raise
    assert isinstance(near_miss, tuple)
    assert fn("plain prose", 0) == ()
    assert fn("plain prose", -1) == ()


def test_b05c_does_not_mutate_its_argument_and_is_repeatable():
    fn = _fn()
    text = f"before {STALE} after"
    snapshot = str(text)
    first = fn(text, 50)
    second = fn(text, 50)
    assert text == snapshot, "the argument text was mutated"
    assert first == second, f"repeated calls disagree: {first!r} vs {second!r}"
    assert first is not None and len(first) == 1


def test_b05d_touches_no_filesystem_subprocess_network_or_clock(monkeypatch, tmp_path):
    """Every door is booby-trapped, and the traps are dropped BEFORE the assertion so a
    failure report can still read files (iter-180 convention)."""
    fn = _fn()
    monkeypatch.chdir(tmp_path)
    with monkeypatch.context() as m:
        m.setattr(pathlib.Path, "read_text", _boom)
        m.setattr(pathlib.Path, "open", _boom)
        m.setattr(pathlib.Path, "exists", _boom)
        m.setattr(pathlib.Path, "is_file", _boom)
        m.setattr(builtins, "open", _boom)
        m.setattr(subprocess, "run", _boom)
        m.setattr(subprocess, "Popen", _boom)
        m.setattr(subprocess, "check_output", _boom)
        m.setattr(socket, "socket", _boom)
        m.setattr(time, "time", _boom)
        m.setattr(time, "monotonic", _boom)
        flagged = fn(f"stale: {STALE}", 50)
        clean = fn(f"fresh: {CLEAN}", 50)
    assert len(flagged) == 1
    assert clean == ()


# ============================================================== behavior 6
def test_b06_live_index_measures_clean():
    """LIVE-TREE anchor: the shipped index agrees with the live verb count."""
    assert _fn()(ROADMAP.read_text(encoding="utf-8"), _live_verb_count()) == ()


def test_b06b_live_anchor_is_not_vacuous_because_the_detector_fires_on_real_bytes():
    """Anti-vacuity control for behavior 6.

    MEASURED this run: the iter-185 move carried the index's ONLY `N CLI verbs` figure into
    the archive, so `findall` over the LIVE INDEX is empty and behavior 6 alone would stay
    green against a `lambda *a: ()` stub.  The teeth therefore come from real repository
    bytes: the ARCHIVE still holds the retired stale figure verbatim, and the same brake, at
    the same live verb count, FLAGS it.  Recorded as PM feedback in tester.md.
    """
    live = _live_verb_count()
    archive_gaps = _fn()(ARCHIVE.read_text(encoding="utf-8"), live)
    assert archive_gaps, (
        "the brake reported no gap on the archive, which still holds the retired stale "
        "figure -- the detector may be fail-open"
    )
    assert 48 in _numbers(archive_gaps[0])


# ============================================================== behavior 7
def test_b07_index_no_longer_pins_the_stale_figure_and_p_left_still_open():
    text = ROADMAP.read_text(encoding="utf-8")
    assert STALE not in text, "the live index still carries the retired stale figure"
    assert OLDER not in text, "the live index still carries the older frozen figure"
    block = _still_open_block(text)
    assert "(p)" not in block, f"(p) is still listed as open:\n{block}"
    # anti-vacuous control: the block really is the list, i.e. it names other open items.
    assert re.search(r"\([cdgjko]\)", block), f"STILL OPEN block did not parse:\n{block}"


# ============================================================== behavior 8
def test_b08_index_keeps_the_p_marker_as_one_short_retired_line():
    text = ROADMAP.read_text(encoding="utf-8")
    assert P_MARKER in text, (
        "the `(p) ` marker was DELETED -- tests/test_iter158_behavior.py SURVIVING_MARKERS "
        "requires it"
    )
    rows = [ln for ln in text.splitlines() if ln.startswith(P_MARKER)]
    assert len(rows) == 1, f"expected exactly ONE `(p) ` line, got {len(rows)}: {rows!r}"
    row = rows[0]
    assert len(row) <= 120, f"retired row is {len(row)} chars (max 120): {row!r}"
    assert row.startswith("(p) SHIPPED"), f"not in the retired form: {row!r}"
    assert row.rstrip().endswith("detail in the archive."), f"not in the retired form: {row!r}"


# ============================================================== behavior 9
def test_b09a_archive_carries_the_retired_body_under_a_new_final_heading():
    archive = ARCHIVE.read_text(encoding="utf-8")
    heads = _archive_headings(archive)
    assert heads, "the archive has no `## ` headings at all"
    assert heads[-1] == ARCHIVE_HEADING, (
        f"the iter-{THIS_ITER} heading must be the FINAL one; last is {heads[-1]!r}"
    )
    assert heads.count(ARCHIVE_HEADING) == 1, "the new heading is duplicated"
    body = _archive_section(archive, ARCHIVE_HEADING)
    assert len(body) >= 6, f"the retired body is too short to be the moved span: {body!r}"
    assert STALE in "\n".join(body), (
        "the moved span no longer holds the stale figure verbatim -- a move must copy the "
        "bytes, not correct them"
    )


def test_b09b_the_move_deleted_the_span_from_the_index():
    """A move DELETES from the index, never copies: no archived body line may survive there."""
    archive = ARCHIVE.read_text(encoding="utf-8")
    index = ROADMAP.read_text(encoding="utf-8")
    body = _archive_section(archive, ARCHIVE_HEADING)
    # The six index-order detail lines are the ones opening with the item marker or continuing
    # its prose; every non-empty body line must be absent from the index either way.
    survivors = [ln for ln in body if ln.strip() and ln.strip() in index]
    assert not survivors, f"{len(survivors)} archived line(s) still live in the index: {survivors!r}"


def test_b09c_pre_existing_heading_order_is_unchanged():
    """The iter-166 prefix freeze: earlier `Compacted ... by iter N` headings keep their order."""
    heads = _archive_headings(ARCHIVE.read_text(encoding="utf-8"))
    iters = [int(m.group(1))
             for m in (re.search(r"by iter (\d+)\s*$", h) for h in heads) if m]
    assert len(iters) >= 5, f"too few compaction headings to check ordering: {iters!r}"
    assert iters == sorted(iters), f"compaction headings are out of order: {iters!r}"
    assert iters[-1] == THIS_ITER, f"iter {THIS_ITER} is not the newest compaction: {iters!r}"


# ============================================================== behavior 10
@pytest.mark.parametrize("module", ["test_iter164_behavior.py", "test_iter173_behavior.py"])
def test_b10_retired_pins_are_derived_not_frozen(module):
    text = (_ROOT / "tests" / module).read_text(encoding="utf-8")
    assert STALE not in text, f"{module} still pins the frozen literal"
    assert OLDER not in text, f"{module} still pins the older frozen literal"
    assert GAPS in text or "foundry_cli_verbs" in text, (
        f"{module}'s replacement assertion is not derived from the brake or from the live "
        "verb set"
    )


def test_b10b_no_test_module_pins_the_literal_against_the_live_roadmap():
    """Acceptance criterion: the pins are RETIRED, not worked around.  This module's own
    PLANTED fixture is built from parts and never asserted against the live roadmap, so the
    only holders of the whole literal in `tests/` must be nothing at all."""
    holders = []
    for path in sorted((_ROOT / "tests").glob("*.py")):
        if path.name == pathlib.Path(__file__).name:
            continue
        if STALE in path.read_text(encoding="utf-8"):
            holders.append(path.name)
    assert not holders, f"the frozen literal survives in: {holders!r}"


# ============================================================== behavior 11
# The floor here WAS the headroom iteration 185 itself achieved (4,676) minus 76 -- an
# ACHIEVEMENT pin, not a threshold, and it fails BY CONSTRUCTION from iteration 186 onward:
# `roles/pm.md` duty 3 MANDATES one `- iter N ` ledger row of up to MAX_ROW_CHARS chars every
# iteration and FORBIDS deleting one, so 76 chars of allowance cannot hold a 115-char
# obligation.  It also contradicted its own author's recorded intent -- 185's archive bullet
# says the paydown "is what buys iteration 186 a mandatory ledger row at all".  Retired at the
# iteration-186 fix pass to the forward-looking property it was reaching for: the index must stay
# far enough under the wall to leave room for the NEXT mandatory row above iter 182's absolute
# floor.  Same defect class as the STATUS equality pin repaired below and as the README POSITION
# pin retired at iter 179.  Deliberately NOT lowered to the absolute floor alone: that would
# restate `tests/test_iter182_behavior.py::test_b13b_index_headroom_at_least_4000` and cost this
# module a real assertion, which is the vacuity trap iteration 186's own feature exists to catch.
ABSOLUTE_INDEX_FLOOR = 4000   # tests/test_iter182_behavior.py::test_b13b_index_headroom_at_least_4000
MAX_ROW_CHARS = 120           # `roles/pm.md` duty 3; the same contract cap iter 167 reads as MAX_STUB_CHARS


def test_b11_index_headroom_improved_and_is_legal():
    cap = getattr(foundry, "ROADMAP_INDEX_HARD_CHARS", 54000)
    size = len(ROADMAP.read_text(encoding="utf-8"))
    headroom = cap - size
    floor = ABSOLUTE_INDEX_FLOOR + MAX_ROW_CHARS
    assert headroom >= floor, (
        f"index headroom is {headroom} chars (cap {cap}, size {size}); it must stay >= {floor} "
        f"-- the {ABSOLUTE_INDEX_FLOOR}-char absolute floor plus ONE {MAX_ROW_CHARS}-char mandatory "
        "ledger row, so the NEXT iteration can still write its own record"
    )


# ============================================================== behavior 12
def test_b12a_brake_has_zero_call_sites_in_the_running_pipeline():
    """MECHANICAL token scan (no human read of the implementation), iter-177 convention."""
    call = re.compile(rf"(?<!def ){GAPS}\s*\(")
    # anti-vacuous control: the detector MUST be able to fire, and must not count the def.
    assert call.findall(f"    x = {GAPS}(text, n)\n"), "the call-site detector cannot fire"
    assert not call.findall(f"def {GAPS}(index_text, live_verb_count):\n"), (
        "the detector counts the definition itself"
    )
    for name in _PIPELINE_MODULES:
        src = (_ROOT / name).read_text(encoding="utf-8")
        hits = call.findall(src)
        assert not hits, f"{name} calls the dormant brake {len(hits)} time(s): {hits!r}"


def test_b12b_no_role_card_config_or_script_references_the_dormant_brake():
    scanned = 0
    for pattern in ("roles/*.md", "products/*/config.json", "scripts/*"):
        for path in sorted(_ROOT.glob(pattern)):
            if not path.is_file():
                continue
            scanned += 1
            assert GAPS not in path.read_text(encoding="utf-8", errors="replace"), (
                f"{path.name} references the dormant brake"
            )
    assert scanned >= 5, f"control: the dormancy scan saw only {scanned} file(s)"


def test_b12c_the_pipeline_modules_still_import():
    assert foundry.__name__ == "foundry"
    assert dispatcher.__name__ == "dispatcher"
    for attr in ("load_config", "run_iteration"):
        assert hasattr(dispatcher, attr) or hasattr(foundry, attr), (
            f"the pipeline lost {attr}"
        )


# ============================================================== behavior 13
def test_b13a_done_ledger_row_and_status_line():
    text = ROADMAP.read_text(encoding="utf-8")
    row_prefix = f"- iter {THIS_ITER} "
    rows = [ln for ln in text.splitlines() if ln.startswith(row_prefix)]
    assert len(rows) == 1, f"expected ONE `{row_prefix}` ledger row, got {rows!r}"
    assert len(rows[0]) <= 120, f"ledger row is {len(rows[0])} chars (max 120): {rows[0]!r}"
    status = [ln for ln in text.splitlines() if ln.startswith("STATUS (iter ")]
    assert status, "the index has no STATUS line"
    # ITERATION-RELATIVE, not pinned to THIS_ITER. The index convention REQUIRES
    # every later iteration to advance this line, so an equality pin fails BY
    # CONSTRUCTION from iter 186 onward (it did -- repaired at the iter-186
    # engineer stage, same defect class as the iter-169 README POSITION pin).
    # The durable intent is that the line is never left STALE, i.e. it names an
    # iteration at least as recent as this test's own.
    named = re.match(r"STATUS \(iter (\d+)\)", status[0])
    assert named, f"the STATUS line does not name an iteration: {status[0]!r}"
    assert int(named.group(1)) >= THIS_ITER, (
        f"the STATUS line is STALE -- it names iteration {named.group(1)}, "
        f"older than {THIS_ITER}: {status[0]!r}"
    )


def test_b13b_archive_bullet_is_present_exactly_once():
    archive = ARCHIVE.read_text(encoding="utf-8")
    bullet = f"- **iter {THIS_ITER} "
    assert archive.count(bullet) == 1, (
        f"expected exactly ONE `{bullet}` archive bullet, got {archive.count(bullet)}"
    )


# ============================================================== acceptance criteria
def test_ac_scope_calibration_the_archive_is_not_in_the_brakes_domain():
    """MEASURED: the archive holds historical `N verbs` figures the archive contract forbids
    re-wording, so the brake must read the INDEX ONLY.  Proof that the live archive is NOT in
    its domain: pointing the brake at the archive FLAGS it (the frozen rows would go red),
    while the index it IS pointed at is clean."""
    archive = ARCHIVE.read_text(encoding="utf-8")
    frozen = re.findall(r"\d+\s+verbs", archive)
    assert len(frozen) >= 15, (
        f"expected the >=15 frozen historical `N verbs` figures, found {len(frozen)}"
    )
    live = _live_verb_count()
    assert _fn()(archive, live), (
        "the archive would NOT go red -- the scope restriction cannot be demonstrated"
    )
    assert _fn()(ROADMAP.read_text(encoding="utf-8"), live) == (), (
        "the index, which the brake IS pointed at, is not clean"
    )


def test_ac_live_verb_count_is_the_derived_source_of_truth():
    """The whole point: the figure is DERIVED, so the brake must move with the live count."""
    live = _live_verb_count()
    assert live > 40, f"control: implausible live verb count {live}"
    text = f"the index would claim {live} CLI verbs"
    assert _fn()(text, live) == ()
    assert len(_fn()(text, live + 1)) == 1, (
        "the brake did not follow the live count -- it is still frozen"
    )
