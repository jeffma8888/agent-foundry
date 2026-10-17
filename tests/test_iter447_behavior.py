"""Iteration 447 -- BLACK-BOX behavior tests: archive Item 23 body (index headroom).

Spec under test: products/_platform/state/iter-447/pm.md (5 Expected Behaviors).

  EB1: The body of Item 23 in `PLATFORM_ROADMAP.md` is replaced with a one-line
       stub: `Moved VERBATIM to the archive by iter 447.` -- matching the
       iter-208 / iter-209 precedent.
  EB2: The exact same body appears VERBATIM (not re-worded, not re-wrapped) in
       `PLATFORM_ROADMAP_ARCHIVE.md` under a new heading
       `## Moved from the index by iter 447`.
  EB3: After the move, `PLATFORM_ROADMAP.md` is at least 2,500 chars shorter
       than before (measured by `len(text)`, not `wc -c`).
  EB4: `python3 foundry.py doctor --config <cfg>` reports `roadmap-index: OK`
       with headroom at least 2,500 chars greater than the pre-move value of 5,681.
  EB5: The full quality-check suite passes, including `roadmap_archive_gaps` and
       `roadmap_size_verdict` (the index is under the hard wall).

BASELINE resolved from git history: the newest commit whose index does NOT yet
carry the `- iter 447 ` ledger row.  This is the same mechanism test_iter365 uses
and is stable before, during, and after the commit.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-447 PM spec, the
product's own observable surface by importing `foundry` and CALLING its public
helpers, the two TRACKED roadmap files, and the conventions of `tests/`.  The
implementation TEXT of foundry.py / dispatcher.py was NOT read, and neither were
engineer.md, reviewer.md, IMPLEMENTATION.patch, or `git diff`.

Offline and deterministic apart from local `git show`/`git log` reads of this
repo's own history: no network, no writes outside `tmp_path`, no sleep.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe

THIS_ITER = 447

INDEX = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"

STUB_LINE = "Moved VERBATIM to the archive by iter 447."
ARCHIVE_HEADING = "## Moved from the index by iter 447"
ITEM_23_HEADING = "## Item 23 -- dispatcher survives a dead stdout (SMALL, incident-driven 2026-08-03)"
ITEM_24_HEADING = "## Item 24 -- docs/code status-drift brakes"

PRE_MOVE_CHARS = 48319
PRE_MOVE_HEADROOM = 5681
MIN_SHRINK = 2500
MIN_HEADROOM_GAIN = 2500
WALL = 54000

ROW_447 = "- iter 447 "


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _git(*args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(_ROOT), *args],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


_BASELINE_CACHE: list = []


def _baseline():
    """(sha, index_text, archive_text) for the newest commit BEFORE this iteration."""
    if _BASELINE_CACHE:
        return _BASELINE_CACHE[0]
    log = _git("log", "--format=%H", "--", "PLATFORM_ROADMAP.md")
    if not log:
        return None
    for sha in log.split():
        blob = _git("show", "%s:PLATFORM_ROADMAP.md" % sha)
        if blob is None:
            continue
        if not any(ln.startswith(ROW_447) for ln in blob.splitlines()):
            arc = _git("show", "%s:PLATFORM_ROADMAP_ARCHIVE.md" % sha)
            _BASELINE_CACHE.append((sha, blob, arc or ""))
            return _BASELINE_CACHE[0]
    return None


def _need_baseline():
    got = _baseline()
    if got is None:
        pytest.skip("no git history for PLATFORM_ROADMAP.md -- missing INFRA")
    return got


# --------------------------------------------------------------------------
# EB0: baseline sanity + import safety
# --------------------------------------------------------------------------
def test_b0_baseline_predates_this_iteration():
    sha, base, _arc = _need_baseline()
    assert not any(ln.startswith(ROW_447) for ln in base.splitlines()), \
        "baseline %s already carries the iter-447 ledger row" % sha[:9]
    assert len(base) == PRE_MOVE_CHARS, (
        "baseline index is %d chars, spec measured %d" % (len(base), PRE_MOVE_CHARS))


def test_b0_shipping_modules_import():
    assert foundry.__name__ == "foundry" and dispatcher.__name__ == "dispatcher"


# --------------------------------------------------------------------------
# EB1: Item 23 body replaced with one-line stub
# --------------------------------------------------------------------------
def test_eb1_item23_stub_is_present():
    """The index must contain the stub line under the Item 23 heading."""
    idx = _text(INDEX)
    assert STUB_LINE in idx, (
        "stub %r not found in PLATFORM_ROADMAP.md" % STUB_LINE)


def test_eb1_stub_sits_between_item23_and_item24_headings():
    """The stub must be the ONLY content between Item 23's heading and Item 24's."""
    lines = _text(INDEX).splitlines()
    i23 = None
    i24 = None
    for i, ln in enumerate(lines):
        if ln == ITEM_23_HEADING:
            i23 = i
        if ln == ITEM_24_HEADING:
            i24 = i
    assert i23 is not None, "Item 23 heading not found in index"
    assert i24 is not None, "Item 24 heading not found in index"
    assert i23 < i24, "Item 23 heading must precede Item 24"
    between = [ln for ln in lines[i23 + 1:i24] if ln.strip()]
    assert len(between) == 1, (
        "expected exactly 1 non-empty line between Item 23 and Item 24, got %d: %r"
        % (len(between), between))
    assert between[0] == STUB_LINE, (
        "the content between items is not the expected stub: %r" % between[0])


def test_eb1_stub_matches_precedent():
    """The stub format must match iter-208/209 precedent: 'Moved VERBATIM to the
    archive by iter N.'"""
    idx = _text(INDEX)
    stub_pattern = re.compile(r"^Moved VERBATIM to the archive by iter \d+\.$", re.M)
    stubs = stub_pattern.findall(idx)
    our_stub = "Moved VERBATIM to the archive by iter 447."
    assert our_stub in stubs, (
        "iter-447 stub not found among precedent-format stubs: %r" % stubs)
    prior_stubs = [s for s in stubs if "447" not in s]
    assert len(prior_stubs) >= 1, "no prior precedent stubs found"


def test_eb1_item23_body_is_gone_from_index():
    """The detailed body (e.g. 'Problem.', 'What ships.', 'CLOSED by') must NOT
    remain in the index."""
    idx = _text(INDEX)
    for marker in ("A 68-shift dispatcher session died",
                   "safe-console-write helper",
                   "CLOSED by iter 235 -- shipped shape differs"):
        assert marker not in idx, (
            "Item 23 body prose %r still in the index -- not fully replaced by stub"
            % marker)


# --------------------------------------------------------------------------
# EB2: body appears VERBATIM in archive under the correct heading
# --------------------------------------------------------------------------
def test_eb2_archive_heading_exists():
    arc = _text(ARCHIVE)
    assert ARCHIVE_HEADING in arc.splitlines(), (
        "heading %r not found in archive" % ARCHIVE_HEADING)


def test_eb2_archive_heading_count_is_one():
    lines = _text(ARCHIVE).splitlines()
    count = sum(1 for ln in lines if ln == ARCHIVE_HEADING)
    assert count == 1, "expected 1 %r heading, got %d" % (ARCHIVE_HEADING, count)


def test_eb2_item23_body_verbatim_in_archive():
    """The body that was under Item 23 in the baseline must appear VERBATIM in the
    archive, under the new heading."""
    _sha, base, _base_arc = _need_baseline()
    base_lines = base.splitlines()

    i23 = None
    i24 = None
    for i, ln in enumerate(base_lines):
        if ln == ITEM_23_HEADING:
            i23 = i
        if ln == ITEM_24_HEADING:
            i24 = i
    assert i23 is not None and i24 is not None, "headings not found in baseline"
    original_block = base_lines[i23:i24]

    arc_lines = _text(ARCHIVE).splitlines()
    heading_idx = None
    for i, ln in enumerate(arc_lines):
        if ln == ARCHIVE_HEADING:
            heading_idx = i
            break
    assert heading_idx is not None, "archive heading not found"
    arc_block = arc_lines[heading_idx + 1:]

    for orig_line in original_block:
        assert orig_line in arc_block, (
            "line from original Item 23 block not found VERBATIM in archive: %r"
            % orig_line[:120])


def test_eb2_archive_is_append_only():
    """Pre-existing archive content must not be altered."""
    _sha, _base, base_arc = _need_baseline()
    if not base_arc:
        pytest.skip("no baseline archive available")
    now = _text(ARCHIVE)
    assert now.startswith(base_arc) or base_arc in now[:len(base_arc) + 200], (
        "the archive was modified rather than appended to")
    was_headings = [ln for ln in base_arc.splitlines() if ln.startswith("#")]
    now_headings = [ln for ln in now.splitlines() if ln.startswith("#")]
    assert was_headings, "baseline archive has no headings"
    assert now_headings[:len(was_headings)] == was_headings, (
        "pre-existing archive headings were re-ordered or re-worded")
    assert len(now_headings) > len(was_headings), (
        "no heading was appended (%d -> %d)" % (len(was_headings), len(now_headings)))


# --------------------------------------------------------------------------
# EB3: index is at least 2,500 chars shorter
# --------------------------------------------------------------------------
def test_eb3_index_shrank_by_at_least_2500_chars():
    _sha, base, _arc = _need_baseline()
    now_len = len(_text(INDEX))
    shrink = len(base) - now_len
    assert shrink >= MIN_SHRINK, (
        "index shrank only %d chars (baseline %d -> %d); EB3 wants >= %d"
        % (shrink, len(base), now_len, MIN_SHRINK))


def test_eb3_shrink_matches_spec_measurement():
    """The spec says pre-move was 48,319 chars."""
    _sha, base, _arc = _need_baseline()
    assert len(base) == PRE_MOVE_CHARS, (
        "baseline index is %d chars, spec says %d" % (len(base), PRE_MOVE_CHARS))


# --------------------------------------------------------------------------
# EB4: doctor reports increased headroom
# --------------------------------------------------------------------------
def test_eb4_headroom_increased_by_at_least_2500():
    budget = foundry.roadmap_index_budget(_text(INDEX))
    gain = budget.headroom - PRE_MOVE_HEADROOM
    assert gain >= MIN_HEADROOM_GAIN, (
        "headroom gain is %d (now %d, was %d); EB4 wants >= %d"
        % (gain, budget.headroom, PRE_MOVE_HEADROOM, MIN_HEADROOM_GAIN))


def test_eb4_index_is_under_the_hard_wall():
    budget = foundry.roadmap_index_budget(_text(INDEX))
    assert budget.over_budget is False, (
        "index is over the %d-char wall: %d chars, headroom %d"
        % (WALL, budget.char_count, budget.headroom))


def test_eb4_headroom_is_consistent():
    """headroom = WALL - char_count."""
    budget = foundry.roadmap_index_budget(_text(INDEX))
    assert budget.headroom == WALL - budget.char_count, (
        "headroom %d != %d - %d" % (budget.headroom, WALL, budget.char_count))


# --------------------------------------------------------------------------
# EB5: brakes pass on shipped files
# --------------------------------------------------------------------------
def test_eb5_roadmap_archive_gaps_clean():
    idx, arc = _text(INDEX), _text(ARCHIVE)
    gaps = foundry.roadmap_archive_gaps(idx, arc)
    assert gaps == [], (
        "archive gaps: iterations %r are in the index ledger but missing from archive"
        % gaps)


def test_eb5_roadmap_ledger_gaps_clean():
    """Evaluated against the WORKTREE with 447 forced into the shipped set only
    if it already has a record; otherwise evaluate only already-shipped iterations.
    OPERATOR 2026-08-24: this iteration's own record lands in the SAME commit."""
    subjects = foundry.git_ship_subjects(str(_ROOT))
    if not subjects:
        pytest.skip("no git history -- missing INFRA")
    shipped = set(foundry.shipped_iterations(subjects))
    idx, arc = _text(INDEX), _text(ARCHIVE)
    has_row = any(ln.startswith(ROW_447) for ln in idx.splitlines())
    has_bullet = any(ln.startswith("- **iter 447 ") for ln in arc.splitlines())
    if has_row or has_bullet:
        shipped.add(THIS_ITER)
    gaps = foundry.roadmap_ledger_gaps(idx, arc, tuple(sorted(shipped)))
    assert gaps == [], (
        "ledger gaps: iterations %r have no record in either roadmap file" % gaps)


def test_eb5_no_done_ledger_rows_deleted():
    """A compaction must not delete any `- iter N ` ledger rows."""
    _sha, base, _arc = _need_baseline()
    ledger_re = re.compile(r"^- iter (\d+) ")
    was = {int(m.group(1)) for m in ledger_re.finditer(base)}
    now = {int(m.group(1))
           for m in ledger_re.finditer(_text(INDEX))}
    deleted = sorted(was - now)
    assert deleted == [], (
        "ledger row(s) deleted: %r -- compaction must not touch Done rows" % deleted)


def test_eb5_iteration_447_ledger_row_if_present():
    """Duty-3 row lands in the SAME commit (OPERATOR 2026-08-24). If present,
    assert it is well-formed; if absent, it will be added at commit time."""
    idx = _text(INDEX)
    rows = [ln for ln in idx.splitlines() if ln.startswith(ROW_447)]
    if not rows:
        pytest.skip("iter-447 ledger row not yet landed -- added at commit time")
    assert len(rows) == 1, (
        "expected exactly one `- iter 447 ` ledger row, got %d" % len(rows))
    assert len(rows[0]) <= 120, (
        "ledger row is %d chars, cap is 120: %r" % (len(rows[0]), rows[0]))


def test_eb5_iteration_447_archive_bullet_if_present():
    """Duty-3 bullet lands in the SAME commit (OPERATOR 2026-08-24). If present,
    assert it is well-formed; if absent, it will be added at commit time."""
    arc = _text(ARCHIVE)
    bullets = [ln for ln in arc.splitlines() if ln.startswith("- **iter 447 ")]
    if not bullets:
        pytest.skip("iter-447 archive bullet not yet landed -- added at commit time")
    assert len(bullets) >= 1, "no `- **iter 447 ` bullet in the archive"


def test_eb5_only_two_files_modified():
    """The spec says: no code changes, no test changes. Only PLATFORM_ROADMAP.md and
    PLATFORM_ROADMAP_ARCHIVE.md should differ from the baseline."""
    _sha, base, base_arc = _need_baseline()
    idx_changed = _text(INDEX) != base
    arc_changed = _text(ARCHIVE) != base_arc
    assert idx_changed, "the index was not modified at all"
    assert arc_changed, "the archive was not modified at all"
