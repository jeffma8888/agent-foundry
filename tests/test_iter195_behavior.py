"""Iteration 195 -- BLACK-BOX behavior tests: this iteration's ROADMAP RECORD lands in the
SAME diff as the code, so the two git-history-keyed roadmap brakes are green in the clean
clone `preship` builds.

Spec under test (products/_platform/state/iter-195/pm.md), Expected Behaviors 6-9:
   6. `PLATFORM_ROADMAP.md` holds EXACTLY ONE `^- iter 195 ` line, at most 120 chars.
   7. `PLATFORM_ROADMAP_ARCHIVE.md` holds EXACTLY ONE `^- \\*\\*iter 195 ` line.
   8. PROSPECTIVE record check -- `roadmap_ledger_gaps(index, archive, (195,)) == []` for the
      two TRACKED roadmap files, so it holds in a fresh clone. Iteration 194 shipped BROKEN
      because this fact is only decidable AFTER the release commit for the brakes that read
      git history; keyed on the LITERAL iteration number it is decidable from tracked text
      alone, and it is proven TWO-SIDED here by removing the rows from in-memory copies.
   9. `roadmap_index_budget(index)` still reports `over_budget is False` and
      `headroom >= 4000` with the row in place.

Behaviors 1-5 are iteration 194's re-landed work; their authoritative pin is
`tests/test_iter194_behavior.py` (902 lines, re-run not rewritten), plus the inverted dormancy
assertions in `tests/test_iter189_behavior.py` / `tests/test_iter191_behavior.py`. This module
does NOT restate them; it adds only the record checks that were missing at iteration 194, and
one cross-cutting guard that the re-landed wiring is present at exactly one call site.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-195 PM spec's Expected Behaviors, the
conventions of tests/ (the `_index_text` / `_archive_text` / ASCII / fresh-import shape of
test_iter140_behavior.py and the live-brake shape of test_iter124_behavior.py), and the
OBSERVABLE surface of the product -- importing the modules, CALLING public functions, and
reading COMMITTED repo docs off disk. The implementation source text of foundry.py and
dispatcher.py, the engineer's notes (engineer.md), the reviewer's notes (reviewer.md) and
`git diff` were NOT read. Behavior 2's call-site count is measured by handing the source file
to the product's own `call_site_count`, never by reading that source here.

Offline and deterministic: no network, no git writes, no subprocess except one local
fresh-interpreter import probe, and nothing in the tree is mutated (every negative case is
built by editing an in-memory copy of the text).
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
import dispatcher  # noqa: E402

THIS_ITER = 195
INDEX_PATH = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE_PATH = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"

LEDGER_ROW_PREFIX = "- iter %d " % THIS_ITER
ARCHIVE_BULLET_PREFIX = "- **iter %d " % THIS_ITER
LEDGER_ROW_MAX_CHARS = 120
INDEX_HEADROOM_FLOOR = 4000


def _index_text():
    return INDEX_PATH.read_text()


def _archive_text():
    return ARCHIVE_PATH.read_text()


def _matching(text, pattern):
    return [ln for ln in text.splitlines() if re.match(pattern, ln)]


# ==========================================================================
# Behavior 6 -- exactly one ledger row in the index, within the row budget
# ==========================================================================
def test_b6_index_holds_exactly_one_ledger_row_for_this_iteration():
    rows = _matching(_index_text(), r"^- iter %d " % THIS_ITER)
    assert len(rows) == 1, (
        "expected EXACTLY ONE `%s` ledger row in PLATFORM_ROADMAP.md, got %d: %r"
        % (LEDGER_ROW_PREFIX, len(rows), rows))


def test_b6_the_ledger_row_is_within_the_120_char_budget():
    rows = _matching(_index_text(), r"^- iter %d " % THIS_ITER)
    assert rows, "no `%s` row to measure" % LEDGER_ROW_PREFIX
    assert len(rows[0]) <= LEDGER_ROW_MAX_CHARS, (
        "the ledger row is %d chars, budget is %d: %r"
        % (len(rows[0]), LEDGER_ROW_MAX_CHARS, rows[0]))


def test_b6_the_ledger_row_says_something_about_the_iteration():
    rows = _matching(_index_text(), r"^- iter %d " % THIS_ITER)
    body = rows[0][len(LEDGER_ROW_PREFIX):].strip()
    assert len(body) >= 20, "the ledger row carries no substance: %r" % (rows[0],)


# ==========================================================================
# Behavior 7 -- exactly one archive detail bullet
# ==========================================================================
def test_b7_archive_holds_exactly_one_detail_bullet_for_this_iteration():
    bullets = _matching(_archive_text(), r"^- \*\*iter %d " % THIS_ITER)
    assert len(bullets) == 1, (
        "expected EXACTLY ONE `%s` bullet in PLATFORM_ROADMAP_ARCHIVE.md, got %d"
        % (ARCHIVE_BULLET_PREFIX, len(bullets)))


def test_b7_the_archive_bullet_is_one_line_and_detailed():
    bullets = _matching(_archive_text(), r"^- \*\*iter %d " % THIS_ITER)
    assert bullets, "no `%s` bullet to measure" % ARCHIVE_BULLET_PREFIX
    assert len(bullets[0]) > len(_matching(_index_text(), r"^- iter %d " % THIS_ITER)[0]), (
        "the archive bullet must carry MORE detail than the one-line index row")


# ==========================================================================
# Behavior 8 -- the PROSPECTIVE record check, proven two-sided
# ==========================================================================
def test_b8_prospective_ledger_gap_check_is_clean_for_this_iteration():
    """The check iteration 194 lacked: decidable from TRACKED files BEFORE the commit."""
    gaps = foundry.roadmap_ledger_gaps(_index_text(), _archive_text(), (THIS_ITER,))
    assert gaps == [], (
        "roadmap_ledger_gaps reports gaps for this iteration: %r -- add the `%s` row to "
        "PLATFORM_ROADMAP.md and the `%s` bullet to PLATFORM_ROADMAP_ARCHIVE.md IN THIS "
        "COMMIT; the git-history-keyed brakes cannot see it before the release commit"
        % (gaps, LEDGER_ROW_PREFIX, ARCHIVE_BULLET_PREFIX))


def test_b8_the_prospective_check_is_two_sided_not_vacuous():
    """Strip this iteration's records from IN-MEMORY copies -- the oracle must FLIP to [195].

    Without this, a brake that silently stopped reporting anything would read as health.
    Nothing on disk is touched.
    """
    idx = "\n".join(ln for ln in _index_text().splitlines()
                    if not re.match(r"^- iter %d " % THIS_ITER, ln)) + "\n"
    arc = "\n".join(ln for ln in _archive_text().splitlines()
                    if not re.match(r"^- \*\*iter %d " % THIS_ITER, ln)) + "\n"
    assert foundry.roadmap_ledger_gaps(idx, arc, (THIS_ITER,)) == [THIS_ITER], (
        "with both records removed the oracle must report [%d]; it did not, so "
        "test_b8_prospective_ledger_gap_check_is_clean_for_this_iteration proves nothing"
        % THIS_ITER)


def test_b8_either_record_alone_satisfies_the_ledger_check():
    """roadmap_ledger_gaps is either-file by design (iter 124) -- pin that reading here so a
    future tightening to BOTH-files cannot land silently while behaviors 6 and 7 still pass."""
    idx_only = LEDGER_ROW_PREFIX + "x\n"
    arc_only = ARCHIVE_BULLET_PREFIX + "y\n"
    assert foundry.roadmap_ledger_gaps(idx_only, "", (THIS_ITER,)) == []
    assert foundry.roadmap_ledger_gaps("", arc_only, (THIS_ITER,)) == []
    assert foundry.roadmap_ledger_gaps("", "", (THIS_ITER,)) == [THIS_ITER]


def test_b8_archive_gap_brake_is_also_clean():
    idx, arc = _index_text(), _archive_text()
    assert foundry.roadmap_archive_gaps(idx, arc) == [], (
        "roadmap_archive_gaps reports gaps: %r"
        % (foundry.roadmap_archive_gaps(idx, arc),))


# ==========================================================================
# Behavior 9 -- the index is still inside its char budget after the row
# ==========================================================================
def test_b9_index_is_not_over_budget_after_the_row_lands():
    budget = foundry.roadmap_index_budget(_index_text())
    assert budget.over_budget is False, (
        "PLATFORM_ROADMAP.md is over budget: %r -- ARCHIVE spent prose, do not raise the wall"
        % (budget,))


def test_b9_index_keeps_at_least_4000_chars_of_headroom():
    budget = foundry.roadmap_index_budget(_index_text())
    assert budget.headroom >= INDEX_HEADROOM_FLOOR, (
        "index headroom is %d, floor is %d (char_count=%d, hard_budget=%d)"
        % (budget.headroom, INDEX_HEADROOM_FLOOR, budget.char_count, budget.hard_budget))


# ==========================================================================
# Cross-cutting: the re-landed wiring is present exactly once, modules import,
# this file is ASCII and reads no gitignored state
# ==========================================================================
def test_the_relanded_ship_decision_wiring_is_at_exactly_one_call_site():
    """Acceptance criterion for the re-apply, measured with the product's OWN counter so this
    test never reads the implementation source itself."""
    source = (_ROOT / "foundry.py").read_text()
    assert foundry.call_site_count(source, symbol="ship_decision") == 1, (
        "expected exactly 1 `ship_decision` call site in foundry.py, got %d"
        % foundry.call_site_count(source, symbol="ship_decision"))


def test_the_live_architecture_doc_reports_no_dormancy_gaps():
    """The DERIVED call-site count is fed in, so the doc's dormancy claim is checked against
    the tree as it actually is -- not against a number restated by hand in this test."""
    call_sites = foundry.call_site_count(
        (_ROOT / "foundry.py").read_text(), symbol="ship_decision")
    gaps = foundry.sentinel_dormancy_gaps(
        (_ROOT / "ARCHITECTURE.md").read_text(),
        tokens=foundry.SHIP_DECISION_TOKENS,
        symbol="ship_decision",
        call_sites=call_sites,
    )
    assert gaps == (), (
        "sentinel_dormancy_gaps over the live ARCHITECTURE.md with call_sites=%r: %r"
        % (call_sites, gaps))


def test_the_dormancy_oracle_is_two_sided_on_a_mutated_doc():
    """Drop one required token from an IN-MEMORY copy of ARCHITECTURE.md; the oracle must
    report that token as a gap. Otherwise the clean verdict above proves nothing."""
    doc = (_ROOT / "ARCHITECTURE.md").read_text()
    token = foundry.SHIP_DECISION_TOKENS[0]
    mutated = doc.replace("`%s`" % token, "%s" % token)
    gaps = foundry.sentinel_dormancy_gaps(
        mutated, tokens=foundry.SHIP_DECISION_TOKENS, symbol="ship_decision", call_sites=1)
    assert "token-not-cited:%s" % token in gaps, (
        "removing the backticked `%s` span did not produce a gap (got %r) -- the dormancy "
        "check cannot be trusted" % (token, gaps))


def test_both_modules_still_import_in_a_fresh_interpreter():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher; print('ok')"],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, "fresh import failed:\n%s\n%s" % (proc.stdout, proc.stderr)
    assert "ok" in proc.stdout


def test_this_module_reads_only_tracked_files():
    """A test whose precondition is gitignored local state passes here and REDS the clean
    clone (pinned OPERATOR 2026-08-11). Every repo path this module opens must be TRACKED,
    so the domain is DERIVED from this file's own source rather than restated by hand."""
    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    pattern = "_ROOT" + r' / "([^"]+)"'
    paths = sorted(set(re.findall(pattern, text)))
    assert paths, "derived an empty path set -- the extractor is broken, not the module clean"
    args = ["git", "ls-files", "--error-unmatch", "tests/" + pathlib.Path(__file__).name]
    args.extend(paths)
    tracked = subprocess.run(
        args, cwd=str(_ROOT), capture_output=True, text=True, timeout=120)
    if tracked.returncode != 0 and "not a git repository" in (tracked.stderr or "").lower():
        pytest.skip("no git available -- missing INFRA, not a lost record")
    assert tracked.returncode == 0, (
        "an untracked path is in this module\'s domain (%r):\n%s" % (paths, tracked.stderr))
    machine_local = ("/" + "Users/", "os." + "walk", "os." + "listdir",
                     "os." + "getcwd", "rg" + "lob")
    planted = "opened " + machine_local[0] + "someone/ambient/tree"
    assert [t for t in machine_local if t in planted] == [machine_local[0]], (
        "the machine-local-path detector does not fire on a planted sample, so its clean "
        "verdict on this module means nothing")
    hits = [t for t in machine_local if t in text]
    assert hits == [], (
        "this module names %r, which reads the ambient machine tree rather than the repo" % hits)


def test_this_test_file_is_pure_ascii():
    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    bad = [(i + 1, ln) for i, ln in enumerate(text.splitlines()) if not ln.isascii()]
    assert bad == [], "non-ASCII on line(s): %r" % ([n for n, _ in bad],)
