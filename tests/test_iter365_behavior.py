"""Iteration 365 -- BLACK-BOX behavior tests (docs-only roadmap-index paydown).

Iteration 364 shipped the `roadmap-index:` gauge that WARNs when the index has too
little slack above the 4,120-char floor the quality suite binds to absorb ONE
mandatory `- iter N ` ledger row.  At 365 that WARN read 24 chars of slack against a
101-char row, so NO iteration could obey `roles/pm.md` duty 3 without reddening
`tests/test_iter185_behavior.py::test_b11_index_headroom_improved_and_is_legal`.
This iteration pays the budget down by moving spent per-item detail prose VERBATIM
into `PLATFORM_ROADMAP_ARCHIVE.md` behind a live stub per item, and lands its own
ledger row in the same commit.

ISOLATION CONTRACT (HONORED): written ONLY from this iteration's PM spec (`pm.md` in
the iter-365 state dir), the repo's own `tests/` conventions, the two TRACKED roadmap
files (which are the SUBJECT of every behavior here), and the product's OWN
OBSERVABLE OUTPUT by importing `foundry` and CALLING its public helpers.  The
implementation diff, the engineer's notes, the reviewer's notes and `git diff` were
NOT read.

Expected Behaviors, numbered as the spec numbers them:
  1. NET SHRINK: `BASE - IDX >= 3000`.
  2. RUNWAY RESTORED: `roadmap_index_paydown_owed(H)` is False,
     `roadmap_index_binding_slack(H) >= 1200`, `H >= 4120`.
  3. NOTHING IS LOST: every line dropped from the index is a VERBATIM line of the new
     archive, and the archive grows by at least what the index shrank.
  4. ARCHIVE HEADING CONVENTION: `## Compacted from the index by iter 365` exists, the
     pre-existing heading list is still a PREFIX of the new one (append-only), and every
     moved line sits UNDER that heading.
  5. LEDGER: no `- iter N ` row deleted, count == baseline + 1, the new one starts
     `- iter 365 ` and is <= 120 chars.
  6. ITER-167 RECEIPT SURVIVES: `(l) SHIPPED iter 160`, `(t) SHIPPED iter 156`,
     `(v) SHIPPED iter 163`, `detail in the archive.` -- including the SPLIT-LINE trap.
  7. NO ITEM SILENTLY VANISHES: every archived item keeps a live stub naming the item
     letter and the word `archive`; no item letter present at baseline is absent now.
  8. BOTH BRAKES CLEAN: `roadmap_ledger_gaps` (against the WORKTREE, with 365 itself in
     the shipped set -- `OPERATOR 2026-08-24`) and `roadmap_archive_gaps` report no gap.
  9. THE GAUGE READS CLEAN: exactly one `roadmap-index:` line, no `paydown` / `does not
     fit`, and no over/near-wall claim -- each "must not say" pinned TWO-SIDED against
     the sibling arm the literal was taken from (`[TEST iter364]`).

BASELINE (durability, `[REV iter365]`): every behavior above is stated against the
index as it stood BEFORE this paydown.  Reading that state as `git show HEAD:` INVERTS
or goes VACUOUS the instant the iteration commits (`49856 - 49856 = 0 >= 3000` is
False; `171 == 172` is False; the lost-line and heading checks scan clean because
nothing is missing any more), and the post-release gate re-runs this suite from a
FRESH CLONE whose HEAD *is* this commit (`OPERATOR 2026-08-11`).  So the baseline is
resolved by WALKING history for the newest commit whose index does NOT yet carry the
`- iter 365 ` row -- stable before the commit, after it, and forever after.

Offline and deterministic apart from local `git show`/`git log` reads of this repo's
own history: no network, no writes outside `tmp_path`, no sleep.
"""

from __future__ import annotations

import contextlib
import io
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe

THIS_ITER = 365

# A RELATIVE literal: an absolute machine path in a shipped test is a leak-guard
# finding (OPERATOR 2026-08-30, which reverted iteration 205 over exactly this shape).
REL_STATE = "products/_platform/state/iter-365"

INDEX = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"

# The spec's own numbers.  Literals on purpose: this file is the pin.
MIN_SHRINK = 3000            # behavior 1
MIN_SLACK = 1200             # behavior 2 -- 10 further mandatory rows
FLOOR = 4000                 # foundry.ROADMAP_INDEX_ABSOLUTE_FLOOR
ROW_CHARS = 120              # foundry.ROADMAP_INDEX_LEDGER_ROW_CHARS
BINDING = FLOOR + ROW_CHARS  # 4120 -- what test_iter185::test_b11 asserts
WALL = 54000                 # foundry.ROADMAP_INDEX_HARD_CHARS
BASE_CHARS = 49856           # the spec's stated `len(git show HEAD:PLATFORM_ROADMAP.md)`
ROW_365 = "- iter 365 "
ARCHIVE_HEADING = "## Compacted from the index by iter 365"
LEDGER_ROW_RE = re.compile(r"^- iter (\d+) ")
ITEM_TOKEN_RE = re.compile(r"\(([a-z]{1,2})\)")
ITEM_LINE_RE = re.compile(r"^\(([a-z]{1,2})\)\s")

# The eight blocks the spec moves.  (j)/(k) share one stub line.
ARCHIVED_ITEMS = ("aa", "o", "j", "k", "w", "q", "y", "s", "x")

# Two-letter parenthesised tokens in the index that are CODE FRAGMENTS, not item
# labels (`property(fn)`, `len(ln)`).  The item-label convention is a..z then aa, bb --
# i.e. a single letter or a DOUBLED letter -- so the census below excludes these by
# rule rather than by name, and behavior 7 additionally proves they were preserved.
CODE_FRAGMENT_TOKENS = {"fn", "ln"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _text(path: pathlib.Path) -> str:
    """Read as UTF-8 `str`.  NEVER `wc -c`: the em-dashes read ~95 bytes high."""
    return path.read_text(encoding="utf-8")


def _git(*args: str) -> str | None:
    """Local read-only git query; None when git or the history is unavailable."""
    try:
        proc = subprocess.run(["git", "-C", str(_ROOT), *args],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


_BASELINE_CACHE: list = []


def _baseline():
    """(sha, index_text, archive_text) for the newest commit BEFORE this paydown.

    Newest-first walk of the commits that touched the index, stopping at the first
    whose blob does not yet carry the `- iter 365 ` ledger row.  Resolves to the same
    commit whether or not iteration 365 has been committed yet, which is what keeps
    behaviors 1/3/4/5 meaningful in the post-release fresh clone.
    """
    if _BASELINE_CACHE:
        return _BASELINE_CACHE[0]
    log = _git("log", "--format=%H", "--", "PLATFORM_ROADMAP.md")
    if not log:
        return None
    for sha in log.split():
        blob = _git("show", "%s:PLATFORM_ROADMAP.md" % sha)
        if blob is None:
            continue
        if not any(ln.startswith(ROW_365) for ln in blob.splitlines()):
            arc = _git("show", "%s:PLATFORM_ROADMAP_ARCHIVE.md" % sha)
            _BASELINE_CACHE.append((sha, blob, arc or ""))
            return _BASELINE_CACHE[0]
    return None


def _need_baseline():
    got = _baseline()
    if got is None:
        pytest.skip("no git history for PLATFORM_ROADMAP.md -- missing INFRA, "
                    "not a lost paydown")
    return got


def _lost_lines():
    """Lines present in the baseline index and absent from the shipped index."""
    _sha, base, _arc = _need_baseline()
    now = set(_text(INDEX).splitlines())
    return [ln for ln in base.splitlines() if ln not in now]


def _headroom() -> int:
    return WALL - len(_text(INDEX))


def _item_letters(text: str) -> set:
    """Roadmap ITEM labels only: a single letter, or a doubled letter (aa, bb)."""
    return {tok for tok in ITEM_TOKEN_RE.findall(text)
            if len(tok) == 1 or tok[0] == tok[1]}


class _Chk:
    def __init__(self, name, ok, detail="detail-text"):
        self.name = name
        self.ok = ok
        self.detail = detail


def _cfg(**over):
    kw = dict(name="demo", repo="/no/such/repo", allowed_push_repo="demo")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _index_cfg(path, tmp_path):
    return _cfg(roadmap=str(path), learnings=str(tmp_path / "no-such-learnings.md"))


def _sized_line(tmp_path, chars, name):
    p = tmp_path / name
    p.write_text("x" * chars, encoding="utf-8")
    return foundry.roadmap_index_line(_index_cfg(p, tmp_path))


def _stub_checks(monkeypatch):
    for nm in ("power", "agent", "uv", "remote"):
        monkeypatch.setattr(foundry, "check_%s" % nm,
                            lambda *a, _n=nm, **k: _Chk(_n, True))


def _doctor_out(cfg):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.run_doctor_cli(cfg)
    return rc, buf.getvalue()


def _prefixed(out, prefix):
    return [ln for ln in out.splitlines() if ln.startswith(prefix)]


# --------------------------------------------------------------------- Behavior 0
# The baseline resolver itself, so no later behavior can pass by measuring the
# wrong commit (or by measuring the post-commit index against itself).
def test_b0_baseline_is_the_commit_immediately_BEFORE_the_paydown():
    sha, base, _arc = _need_baseline()
    assert not any(ln.startswith(ROW_365) for ln in base.splitlines()), \
        "baseline %s already carries the iter-365 ledger row" % sha[:9]
    assert any(ln.startswith("- iter 364 ") for ln in base.splitlines()), \
        ("baseline %s predates iteration 364, so the walk overshot: the newest "
         "commit without the 365 row should be 364's" % sha[:9])
    assert len(base) == BASE_CHARS, (
        "baseline index is %d chars, spec measured %d -- the resolver drifted or "
        "the pre-365 index was rewritten" % (len(base), BASE_CHARS))


def test_b0_the_shipping_modules_still_import():
    assert foundry.__name__ == "foundry" and dispatcher.__name__ == "dispatcher"


# --------------------------------------------------------------------- Behavior 1
def test_b1_index_shrank_by_at_least_3000_chars():
    _sha, base, _arc = _need_baseline()
    idx = len(_text(INDEX))
    shrink = len(base) - idx
    assert shrink >= MIN_SHRINK, (
        "index shrank only %d chars (baseline %d -> %d); behavior 1 wants >= %d"
        % (shrink, len(base), idx, MIN_SHRINK))


# --------------------------------------------------------------------- Behavior 2
def test_b2_paydown_is_no_longer_owed():
    h = _headroom()
    assert foundry.roadmap_index_paydown_owed(h) is False, (
        "the gauge still says a paydown is owed at headroom %d (slack %d)"
        % (h, foundry.roadmap_index_binding_slack(h)))


def test_b2_binding_slack_holds_ten_more_mandatory_rows():
    h = _headroom()
    slack = foundry.roadmap_index_binding_slack(h)
    assert slack >= MIN_SLACK, (
        "only %d chars of binding slack (headroom %d); behavior 2 wants >= %d "
        "so at least 10 further %d-char rows fit" % (slack, h, MIN_SLACK, ROW_CHARS))


def test_b2_headroom_still_clears_the_floor_the_suite_binds():
    h = _headroom()
    assert h >= BINDING, (
        "headroom %d is under the %d-char binding floor test_iter185::test_b11 "
        "asserts" % (h, BINDING))


def test_b2_the_headroom_the_test_measures_is_the_gauge_s_own():
    """No private arithmetic: the same number the shipped budget reports."""
    assert foundry.roadmap_index_budget(_text(INDEX)).headroom == _headroom()


# --------------------------------------------------------------------- Behavior 3
def test_b3_every_dropped_index_line_survives_verbatim_in_the_archive():
    lost = _lost_lines()
    arc_lines = set(_text(ARCHIVE).splitlines())
    missing = [ln for ln in lost if ln not in arc_lines]
    assert missing == [], (
        "%d of %d dropped index line(s) are in NEITHER file -- lost prose, "
        "not archived prose.  First 3: %r"
        % (len(missing), len(lost), [m[:110] for m in missing[:3]]))


def test_b3_the_lost_line_check_is_not_vacuous():
    """A paydown that dropped ~5,000 chars must drop real lines; if this shrinks to
    nothing the checks above scan clean while proving nothing (`[REV iter365]`)."""
    lost = _lost_lines()
    assert len(lost) >= 20, (
        "only %d line(s) left the index, so behaviors 3/4 are near-vacuous" % len(lost))


def test_b3_archive_grew_by_at_least_what_the_index_shed():
    _sha, base, base_arc = _need_baseline()
    shrink = len(base) - len(_text(INDEX))
    growth = len(_text(ARCHIVE)) - len(base_arc)
    assert growth >= shrink, (
        "archive grew %d chars while the index shed %d -- prose was condensed or "
        "dropped, not MOVED" % (growth, shrink))


# --------------------------------------------------------------------- Behavior 4
def test_b4_the_new_archive_heading_exists_exactly_once():
    lines = _text(ARCHIVE).splitlines()
    hits = [ln for ln in lines if ln == ARCHIVE_HEADING]
    assert len(hits) == 1, (
        "expected exactly one %r heading, found %d" % (ARCHIVE_HEADING, len(hits)))


def test_b4_the_archive_is_append_only():
    _sha, _base, base_arc = _need_baseline()
    was = [ln for ln in base_arc.splitlines() if ln.startswith("#")]
    now = [ln for ln in _text(ARCHIVE).splitlines() if ln.startswith("#")]
    assert was, "baseline archive has no headings -- the prefix check is vacuous"
    assert now[:len(was)] == was, (
        "pre-existing archive headings were re-ordered or re-worded; first "
        "divergence at index %d"
        % next((i for i, (a, b) in enumerate(zip(was, now)) if a != b), len(was)))
    assert len(now) > len(was), "no heading was appended (%d -> %d)" % (len(was), len(now))


def test_b4_every_moved_line_sits_under_the_new_heading():
    arc_lines = _text(ARCHIVE).splitlines()
    if ARCHIVE_HEADING not in arc_lines:
        pytest.fail("the %r heading is missing" % ARCHIVE_HEADING)
    below = set(arc_lines[arc_lines.index(ARCHIVE_HEADING) + 1:])
    stray = [ln for ln in _lost_lines() if ln not in below]
    assert stray == [], (
        "%d moved line(s) appear in the archive only ABOVE the iter-365 heading, so "
        "they were filed under someone else's section: %r"
        % (len(stray), [s[:110] for s in stray[:3]]))


# --------------------------------------------------------------------- Behavior 5
def _rows(text):
    return [ln for ln in text.splitlines() if LEDGER_ROW_RE.match(ln)]


def test_b5_no_pre_existing_ledger_row_was_deleted():
    _sha, base, _arc = _need_baseline()
    now = set(_rows(_text(INDEX)))
    dropped = [r for r in _rows(base) if r not in now]
    assert dropped == [], (
        "%d ledger row(s) were deleted, which this iteration puts OUT OF SCOPE: %r"
        % (len(dropped), [d[:110] for d in dropped[:3]]))


def test_b5_exactly_one_row_was_added():
    _sha, base, _arc = _need_baseline()
    was, now = len(_rows(base)), len(_rows(_text(INDEX)))
    assert now == was + 1, (
        "ledger rows went %d -> %d; duty 3 wants exactly one new row" % (was, now))


def test_b5_the_new_row_is_iteration_365_s_and_fits_the_cap():
    _sha, base, _arc = _need_baseline()
    old = set(_rows(base))
    added = [r for r in _rows(_text(INDEX)) if r not in old]
    assert len(added) == 1, "expected 1 new ledger row, got %r" % ([a[:80] for a in added],)
    row = added[0]
    assert row.startswith(ROW_365), "the new row is not iteration 365's: %r" % row
    # Measured in Python, never through `grep -n`, whose line-number prefix
    # inflates any width measurement (`[TEST iter360]`).
    assert len(row) <= ROW_CHARS, (
        "the iter-365 row is %d chars, over duty 3's %d-char cap: %r"
        % (len(row), ROW_CHARS, row))
    assert LEDGER_ROW_RE.match(row), (
        "the row does not match the brake's own pattern %r: %r"
        % (LEDGER_ROW_RE.pattern, row))


def test_b5_iteration_365_has_an_archive_bullet_the_brake_can_parse():
    """The history half of the record: `- **iter 365 ` -- note the SPACE the brake's
    pattern requires after the number (`[PM iter365]`)."""
    hits = [ln for ln in _text(ARCHIVE).splitlines() if ln.startswith("- **iter 365 ")]
    assert hits, ("no `- **iter 365 ` bullet in the archive; a `- **iter 365** --` "
                  "shape does NOT match the brake and reads as lost history")


# --------------------------------------------------------------------- Behavior 6
def test_b6_iteration_167_paydown_receipt_is_intact():
    idx = _text(INDEX)
    for pin in ("(l) SHIPPED iter 160", "(t) SHIPPED iter 156",
                "(v) SHIPPED iter 163", "detail in the archive."):
        assert pin in idx, (
            "%r left the index; it is pinned by tests/test_iter167_behavior.py and "
            "tests/test_iter185_behavior.py" % pin)


def test_b6_the_shared_line_was_SPLIT_not_swallowed():
    """The `(l)` stub shares its physical line with the TAIL of item (k)'s prose, so
    archiving (k) must split that line and keep (l)'s sentence in the index."""
    idx_lines = _text(INDEX).splitlines()
    hits = [ln for ln in idx_lines if "(l) SHIPPED iter 160" in ln]
    assert hits, "the (l) receipt line is gone from the index entirely"
    assert "(l) SHIPPED iter 160 -- detail in the archive." in idx_lines, (
        "the (l) receipt survives only as part of a longer line (%r), so the shared "
        "line was not split cleanly" % hits[0][:140])


# --------------------------------------------------------------------- Behavior 7
def test_b7_every_archived_item_keeps_a_live_stub_naming_the_archive():
    idx_lines = _text(INDEX).splitlines()
    for item in ARCHIVED_ITEMS:
        tok = "(%s)" % item
        stubs = [ln for ln in idx_lines if tok in ln and "archive" in ln]
        assert stubs, (
            "item %s lost its prose with no live stub pointing at the archive -- it "
            "vanished silently from the index" % tok)


def test_b7_no_item_whose_block_shrank_is_left_without_a_pointer():
    """Derived, not copied from the spec's list: attribute every dropped line to the
    item block it sat in, then demand a stub for each such item."""
    _sha, base, _arc = _need_baseline()
    lost = set(_lost_lines())
    owner, touched = None, set()
    for ln in base.splitlines():
        m = ITEM_LINE_RE.match(ln)
        if m:
            owner = m.group(1)
        elif ln.startswith("#"):
            owner = None
        if owner and ln in lost:
            touched.add(owner)
    assert touched, "no dropped line could be attributed to an item block"
    idx_lines = _text(INDEX).splitlines()
    orphans = [t for t in sorted(touched)
               if not [ln for ln in idx_lines if "(%s)" % t in ln and "archive" in ln]]
    assert orphans == [], (
        "item(s) %r lost prose but have no surviving line naming the archive" % (orphans,))


def test_b7_no_item_letter_present_at_baseline_is_absent_now():
    _sha, base, _arc = _need_baseline()
    gone = sorted(_item_letters(base) - _item_letters(_text(INDEX)))
    assert gone == [], (
        "item letter(s) %r are present at baseline and absent from the shipped "
        "index" % (gone,))


def test_b7_the_census_exclusion_is_exactly_the_known_code_fragments():
    """Two-sided guard on the census RULE.  A naive `\\([a-z]{1,2}\\)` sweep also
    flags `(fn)` and `(ln)` -- code fragments inside moved prose, not roadmap items.
    This pins that the exclusion covers only those, AND that both were preserved."""
    _sha, base, _arc = _need_baseline()
    raw = set(ITEM_TOKEN_RE.findall(base))
    excluded = raw - _item_letters(base)
    assert excluded == CODE_FRAGMENT_TOKENS, (
        "the item-letter census now excludes %r; if a REAL two-letter item label "
        "appeared, behavior 7 would stop watching it" % (sorted(excluded),))
    arc = _text(ARCHIVE)
    for tok in sorted(CODE_FRAGMENT_TOKENS):
        assert "(%s)" % tok in arc, (
            "code fragment (%s) left the index and is NOT in the archive either -- "
            "that is lost prose, whatever it is called" % tok)


# --------------------------------------------------------------------- Behavior 8
def _gap_inputs():
    return _text(INDEX), _text(ARCHIVE)


def test_b8_no_shipped_iteration_lost_its_record_including_365_itself():
    """Evaluated against the WORKTREE with 365 forced into the shipped set: `git show
    HEAD:` cannot see this commit (`OPERATOR 2026-08-24`)."""
    subjects = foundry.git_ship_subjects(str(_ROOT))
    if not subjects:
        pytest.skip("no git history available -- missing INFRA, not a lost record")
    shipped = set(foundry.shipped_iterations(subjects)) | {THIS_ITER}
    idx, arc = _gap_inputs()
    gaps = foundry.roadmap_ledger_gaps(idx, arc, tuple(sorted(shipped)))
    assert gaps == [], (
        "iteration(s) %r have no `- iter N ` row in PLATFORM_ROADMAP.md and no "
        "`- **iter N ` bullet in PLATFORM_ROADMAP_ARCHIVE.md" % (gaps,))


def test_b8_the_archive_brake_reports_no_lost_history():
    idx, arc = _gap_inputs()
    gaps = foundry.roadmap_archive_gaps(idx, arc)
    assert gaps == [], (
        "iteration(s) %r are in the index ledger but missing from the archive" % (gaps,))


def test_b8_the_skip_premise_is_real():
    idx, arc = _gap_inputs()
    assert foundry.shipped_iterations(()) == ()
    assert foundry.roadmap_ledger_gaps(idx, arc, ()) == []


# --------------------------------------------------------------------- Behavior 9
def test_b9_doctor_prints_exactly_one_clean_roadmap_index_line(monkeypatch, tmp_path):
    _stub_checks(monkeypatch)
    monkeypatch.setattr(foundry, "parse_brain_launch", lambda *a, **k: 1000.0)
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: ((1, 900.0),))
    monkeypatch.setattr(foundry, "stage_budget_line",
                        lambda *a, **k: foundry.STAGE_BUDGET_PREFIX + " scripted")
    _rc, out = _doctor_out(_index_cfg(INDEX, tmp_path))
    lines = _prefixed(out, foundry.ROADMAP_INDEX_PREFIX)
    assert len(lines) == 1, "expected one roadmap-index line, got %d:\n%s" % (
        len(lines), out)
    line = lines[0]
    assert foundry.ROADMAP_INDEX_WARN not in line, (
        "the gauge still WARNs on the paid-down index: %r" % line)
    for banned in ("paydown", "does not fit"):
        assert banned not in line, "the line still says %r: %r" % (banned, line)


def test_b9_the_must_not_say_pins_are_two_sided(monkeypatch, tmp_path):
    """A bare `assert claim not in line` rots silently the moment the sibling arm is
    reworded (`[TEST iter364]`), so assert each literal IS produced by the arm it was
    taken from, on tmp fixtures, before asserting it is absent from the live line."""
    over = _sized_line(tmp_path, WALL + 1, "over.md")
    near = _sized_line(tmp_path, WALL - foundry.ROADMAP_INDEX_NEAR_WALL_CHARS + 500,
                       "near.md")
    band = _sized_line(tmp_path, WALL - (BINDING + 113), "band.md")
    wall_claim = "against the %d-char wall" % WALL
    for name, sib in (("over", over), ("near", near)):
        assert wall_claim in sib, (
            "the pin has rotted: the %s arm no longer says %r -- %r"
            % (name, wall_claim, sib))
    assert "does not fit" in band, (
        "the pin has rotted: the paydown arm no longer says 'does not fit' -- %r" % band)
    live = foundry.roadmap_index_line(_index_cfg(INDEX, tmp_path))
    assert wall_claim not in live, (
        "the live line claims the index is at/near the wall: %r" % live)
    assert "does not fit" not in live and "paydown" not in live, live


def test_b9_the_live_verdict_agrees_with_the_shipped_oracles(tmp_path):
    """Derived, never a hardcoded char count: OK iff no oracle asks for anything."""
    budget = foundry.roadmap_index_budget(_text(INDEX))
    owed = foundry.roadmap_index_paydown_owed(budget.headroom)
    line = foundry.roadmap_index_line(_index_cfg(INDEX, tmp_path))
    warned = foundry.ROADMAP_INDEX_WARN in line
    assert warned is bool(budget.over_budget or budget.near_wall or owed), (
        "printed verdict disagrees with the oracles (over=%r near=%r owed=%r "
        "headroom=%r): %r"
        % (budget.over_budget, budget.near_wall, owed, budget.headroom, line))
    assert warned is False, "behavior 9 wants a clean gauge, got: %r" % line
