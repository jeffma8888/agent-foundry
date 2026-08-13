"""Black-box behaviour tests for iteration 166 -- iteration 158's LAST-heading
archive pin is re-scoped to an append-only PREFIX freeze, and the roadmap index's
INDEX BUDGET paragraph states a reproducible growth figure plus the now-unblocked
next paydown.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-166 PM spec's
Expected Behaviors 1-12, the conventions found under `tests/`, the pre-existing
pins under `tests/` that the spec names, the two git-TRACKED markdown
deliverables the behaviors are ABOUT (`PLATFORM_ROADMAP.md` and
`PLATFORM_ROADMAP_ARCHIVE.md` -- those files ARE the artifact under test, not
implementation source), and the product's own OBSERVABLE behaviour (importing a
public name, calling it, and running a fresh interpreter). `foundry.py` /
`dispatcher.py` SOURCE was not read. The engineer's notes, the reviewer's notes
and `git diff` content were not consulted.

WHY THIS FILE IMPORTS A SIBLING TEST MODULE: the spec's THE RULE is defined over
archive TEXT, and behaviors 3-5 demand that the SHIPPED rule -- not a private
re-implementation of it -- accept a future paydown and reject tampering. A copy
of the rule written here could pass while the rule that actually guards the
tracked archive deadlocks, which is the exact failure this iteration repairs. So
behaviors 3-5 drive the shipped callables through the tree's sibling-import
convention (`import test_iter140_behavior as t140`, iter 145/154/155), while
behaviors 1-2 are computed INDEPENDENTLY here from the spec's own nine literals,
so the ambient facts are proven from the spec rather than from the guard.

Every synthetic fixture is built in-process or in `tmp_path`; no assertion
depends on gitignored local state, on git history, or on the network (2026-08-11
operator rule). The only ambient files touched are git-TRACKED ones the spec
names.
"""

from __future__ import annotations

import inspect
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tests"))
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402  -- CALLED as a public interface, source never read
import test_iter158_behavior as t158  # noqa: E402  -- owns the re-scoped rule

THIS_ITER = 166

ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ROADMAP_ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"

# The spec's FROZEN_PREFIX, transcribed from the spec's own code block. The em
# dashes of items 2 and 4 are written as escapes so this file stays pure ASCII on
# the wire and cannot be corrupted in transport.
_EM = "\u2014"
FROZEN_PREFIX = (
    "## Moved from the index by iter 139",
    "## Detailed spec %s item 11: post-release verification gate + revertable-commit contract" % _EM,
    "## Moved from the index by iter 140",
    "## Item 16 %s committed, portable pre-push leak-guard (HIGH: repo is public + auto-pushing)" % _EM,
    "## Moved from the index by iter 141",
    "## RESOLVED 2026-08-04 -- dual-PM-scout bite 3b-ii WIRED (operator sign-off received)",
    "## Compacted from the index by iter 142",
    "## Compacted from the index by iter 145",
    "## Compacted from the index by iter 158",
)
COMPACTION_158 = "## Compacted from the index by iter 158"


def _index_text() -> str:
    return ROADMAP.read_text(encoding="utf-8")


def _archive_text() -> str:
    return ROADMAP_ARCHIVE.read_text(encoding="utf-8")


def _headings(text: str) -> list[str]:
    """The spec's *archive headings*, computed HERE from the spec's definition."""
    return [ln for ln in text.splitlines() if ln.startswith("## ")]


def _rule(text: str):
    """THE RULE as SHIPPED (behaviors 1+2 taken together), driven over text."""
    return t158.archive_rule_violations(text)


def _synthetic_clean() -> str:
    """Behavior 3's fixture: the nine frozen headings, each with a body line,
    THEN a later compaction section, THEN a later moved section whose BODY itself
    contains a line beginning with the heading marker."""
    parts = ["%s\nbody line %d\n\n" % (h, i) for i, h in enumerate(FROZEN_PREFIX)]
    parts.append("## Compacted from the index by iter 167\nmoved prose for iter 167\n\n")
    parts.append(
        "## Moved from the index by iter 168\n"
        "the body of this section quotes a heading-shaped line verbatim:\n"
        "## Roadmap file contract\n"
        "and continues afterwards\n"
    )
    return "".join(parts)


# --------------------------------------------------------------------------
# behavior 1 -- the real archive's headings BEGIN with FROZEN_PREFIX
# --------------------------------------------------------------------------

def test_behavior1_real_archive_headings_begin_with_frozen_prefix():
    headings = _headings(_archive_text())
    assert len(headings) >= len(FROZEN_PREFIX), (
        "archive holds %d `## ` headings, fewer than the %d frozen ones"
        % (len(headings), len(FROZEN_PREFIX))
    )
    for pos, expected in enumerate(FROZEN_PREFIX):
        assert headings[pos] == expected, (
            "frozen archive heading %d changed: expected %r, got %r"
            % (pos + 1, expected, headings[pos])
        )


def test_behavior1_the_shipped_rule_agrees_with_the_spec_on_the_real_archive():
    # The independent computation above and the SHIPPED rule must reach the same
    # verdict on the tracked file; if they disagree, one of them is not the rule
    # the spec describes.
    assert _rule(_archive_text()) == [], (
        "the shipped rule reports violations on the real archive: %r" % (_rule(_archive_text()),)
    )


def test_behavior1_positions_ten_and_beyond_are_not_constrained_by_this_behavior():
    # The real archive currently holds EXACTLY nine headings, so behavior 1 is
    # degenerate on it (prefix == whole list) and cannot prove the freedom clause.
    # Proven synthetically instead: extending PAST the prefix stays clean.
    headings = _headings(_archive_text())
    assert len(headings) >= len(FROZEN_PREFIX), "archive lost frozen headings"
    extended = _synthetic_clean()
    assert len(_headings(extended)) > len(FROZEN_PREFIX), "fixture did not extend past the prefix"
    assert _rule(extended) == [], (
        "headings at position ten and beyond must be unconstrained, got %r" % (_rule(extended),)
    )


# --------------------------------------------------------------------------
# behavior 2 -- exactly one iter-158 compaction HEADING
# --------------------------------------------------------------------------

def test_behavior2_iter158_compaction_heading_occurs_exactly_once_among_headings():
    headings = _headings(_archive_text())
    found = [h for h in headings if h == COMPACTION_158]
    assert len(found) == 1, "expected exactly one %r heading, got %d" % (COMPACTION_158, len(found))


def test_behavior2_is_heading_scoped_not_substring_scoped():
    # The archive is verbatim history, so a per-iteration bullet may legitimately
    # QUOTE the heading inside prose. Behavior 2 counts HEADINGS, so a quotation
    # must not read as a second section.
    archive = _archive_text()
    assert archive.count(COMPACTION_158) >= 1
    quoted = _synthetic_clean() + "- **iter 999 -- prose quoting %s inline.**\n" % COMPACTION_158
    assert _rule(quoted) == [], (
        "a heading quoted inside a bullet was miscounted as a section: %r" % (_rule(quoted),)
    )


# --------------------------------------------------------------------------
# behavior 3 -- THE RULE ACCEPTS A FUTURE PAYDOWN (the deadlock being broken)
# --------------------------------------------------------------------------

def test_behavior3_the_rule_accepts_a_future_paydown_in_process():
    assert _rule(_synthetic_clean()) == [], (
        "THE RULE forbids a later compaction section -- the deadlock is NOT broken: %r"
        % (_rule(_synthetic_clean()),)
    )


def test_behavior3_the_rule_accepts_a_future_paydown_from_tmp_path(tmp_path):
    p = tmp_path / "PLATFORM_ROADMAP_ARCHIVE.md"
    p.write_text(_synthetic_clean(), encoding="utf-8")
    assert _rule(p.read_text(encoding="utf-8")) == [], "THE RULE rejected a legal future paydown"


def test_behavior3_the_rule_accepts_many_successive_future_paydowns():
    # A rule that accepted exactly ONE later heading would deadlock at iteration
    # 168 instead of 167 -- a postponed deadlock is still a deadlock.
    text = _synthetic_clean()
    for n in range(169, 175):
        text += "## Compacted from the index by iter %d\nbody\n\n" % n
        assert _rule(text) == [], "THE RULE deadlocked at heading for iter %d: %r" % (n, _rule(text))


def test_behavior3_no_allowlist_or_per_iteration_exemption_is_consulted():
    names = (
        "archive_headings",
        "frozen_prefix_violations",
        "compaction_heading_count",
        "archive_rule_violations",
    )
    banned = ("allowlist", "allow_list", "whitelist", "exempt", "exception", "special_case", "xfail")
    for name in names:
        fn = getattr(t158, name, None)
        assert fn is not None and callable(fn), "the rule callable %r is missing" % name
        src = inspect.getsource(fn).lower()
        hits = [b for b in banned if b in src]
        assert hits == [], "%s() consults an exemption mechanism %r" % (name, hits)
        # a per-iteration special case would have to name an iteration number
        nums = set(re.findall(r"\b1[5-9][0-9]\b", src))
        assert nums <= {"158"}, "%s() hard-codes iteration numbers %r" % (name, sorted(nums))


# --------------------------------------------------------------------------
# behavior 4 -- THE RULE REJECTS AN INSERTION
# --------------------------------------------------------------------------

def test_behavior4_an_inserted_mid_history_heading_violates_behavior1():
    inserted = _synthetic_clean().replace(
        COMPACTION_158, "## Inserted mid-history\nbody\n\n" + COMPACTION_158, 1
    )
    headings = _headings(inserted)
    assert headings[8] != COMPACTION_158, "fixture did not actually displace the ninth heading"
    violations = t158.frozen_prefix_violations(inserted)
    assert violations != [], "an INSERTED mid-history heading was accepted"
    assert _rule(inserted) != [], "THE RULE accepted an INSERTED mid-history heading"
    # behavior 2's half must NOT be what fired: the count is still one.
    assert t158.compaction_heading_count(inserted) == 1
    assert any("9" in v for v in violations), (
        "the violation does not name the ninth frozen position: %r" % (violations,)
    )


def test_behavior4_a_rewritten_frozen_heading_is_also_rejected():
    tampered = _synthetic_clean().replace(FROZEN_PREFIX[0], "## Moved from the index by iter 1390", 1)
    assert t158.frozen_prefix_violations(tampered) != [], "a REWRITTEN frozen heading was accepted"


# --------------------------------------------------------------------------
# behavior 5 -- THE RULE REJECTS LOSS AND DUPLICATION
# --------------------------------------------------------------------------

def test_behavior5_a_deleted_frozen_heading_violates_behavior1():
    dropped = _synthetic_clean().replace(COMPACTION_158 + "\n", "", 1)
    assert COMPACTION_158 not in _headings(dropped), "fixture did not delete the heading"
    assert t158.frozen_prefix_violations(dropped) != [], "a LOST frozen heading was accepted"
    assert _rule(dropped) != [], "THE RULE accepted a LOST frozen heading"


def test_behavior5_a_duplicated_compaction_heading_violates_behavior2():
    duped = _synthetic_clean() + COMPACTION_158 + "\nbody\n"
    assert t158.compaction_heading_count(duped) == 2, "fixture did not duplicate the heading"
    # behavior 1 still holds here -- the frozen prefix is untouched -- so it must
    # be behavior 2's half that rejects. That split is the point of THE RULE.
    assert t158.frozen_prefix_violations(duped) == [], "duplication must not read as a prefix breach"
    assert _rule(duped) != [], "THE RULE accepted a DUPLICATED compaction heading"


# --------------------------------------------------------------------------
# behavior 6 -- THE OLD PIN IS GONE, PROVEN TWO-SIDED
# --------------------------------------------------------------------------

# Assembled from fragments so the forbidden shape never appears contiguously in
# THIS file: the matcher must return zero over `tests/`, and this file is scanned.
_LAST_INDEX = "[" + "-1]"
_NEG_LITERALS = ("headings" + _LAST_INDEX, _LAST_INDEX + " == COMPACTION_HEADING")
_NEG_REGEX = re.compile(r"\[" + "-1\\]" + r"\s*==\s*\w*COMPACTION_HEADING")


def test_behavior6_no_test_file_asserts_the_iter158_heading_is_last():
    hits = []
    for path in sorted((_ROOT / "tests").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for lit in _NEG_LITERALS:
            if lit in text:
                hits.append((path.name, lit))
        if _NEG_REGEX.search(text):
            hits.append((path.name, "regex"))
    assert hits == [], "the old LAST-heading pin still lives under tests/: %r" % (hits,)


def test_behavior6_positive_control_the_matcher_can_hit_at_all():
    # Establishing an ABSENCE requires proving the search works. Control 1: the
    # literal the spec names must appear at least four times in the pin's file.
    src = (_ROOT / "tests" / "test_iter158_behavior.py").read_text(encoding="utf-8")
    assert src.count("COMPACTION_HEADING") >= 4, (
        "control failed: COMPACTION_HEADING appears %d times, matcher may be broken"
        % src.count("COMPACTION_HEADING")
    )
    # Control 2: the same matchers used above DO fire on a planted known-bad
    # sample, so a zero above means absence and not a dead matcher.
    planted = "    assert headings" + _LAST_INDEX + " == COMPACTION_HEADING\n"
    assert any(lit in planted for lit in _NEG_LITERALS), "negative literals cannot match"
    assert _NEG_REGEX.search(planted) is not None, "negative regex cannot match"


def test_behavior6_the_pin_was_replaced_not_disabled():
    src = (_ROOT / "tests" / "test_iter158_behavior.py").read_text(encoding="utf-8")
    assert "xfail" not in src, "the pin was neutered with xfail instead of replaced"
    assert "skip" not in src.lower().replace("skipped", ""), "the pin's file now skips work"
    assert "archive_rule_violations(" in src, "no replacement invariant is called in that file"


# --------------------------------------------------------------------------
# behavior 7 -- NO SIBLING ASSERTION IS WEAKENED
# --------------------------------------------------------------------------

def test_behavior7_exactly_one_iter158_archive_bullet_and_one_item16_heading():
    archive = _archive_text()
    bullets = [ln for ln in archive.splitlines() if ln.startswith("- **iter 158 ")]
    assert len(bullets) == 1, "expected exactly one iter-158 archive bullet, got %d" % len(bullets)
    item16 = [ln for ln in archive.splitlines() if ln.startswith("## Item 16")]
    assert len(item16) == 1, "iter 140 pins exactly one `## Item 16` heading, got %d" % len(item16)


def test_behavior7_the_compaction_body_still_names_every_moved_span():
    body = _archive_text().split(COMPACTION_158, 1)[1]
    assert len(body.strip()) > 500, "compaction body is only %d chars" % len(body.strip())
    missing = [lbl for lbl in ("(a)", "(b)", "(e)", "(f)", "(h)", "(i)", "(m)")
               if "-- %s iter" % lbl not in body]
    assert missing == [], "the compaction body no longer names moved spans %r" % (missing,)


def test_behavior7_every_deleted_index_span_is_still_recoverable():
    body = _archive_text().split(COMPACTION_158, 1)[1]
    required = ("(b) SHIPPED iter 128", "(e) SHIPPED iter 135", "(h) SHIPPED iter 142",
                "(m) SHIPPED iter 149", "(a) SHIPPED iter 132", "(i) SHIPPED iter 152",
                "PM_SCOUT_LENS_POOL")
    missing = [s for s in required if s not in body]
    assert missing == [], "these deleted spans are no longer recoverable: %r" % (missing,)


def test_behavior7_no_archive_iteration_bullet_is_duplicated():
    bullets = [ln for ln in _archive_text().splitlines() if ln.startswith("- **iter ")]
    nums = [re.match(r"- \*\*iter (\d+) ", ln).group(1) for ln in bullets
            if re.match(r"- \*\*iter (\d+) ", ln)]
    dupes = sorted({n for n in nums if nums.count(n) > 1})
    assert dupes == [], "archive bullets duplicated for iterations %r" % (dupes,)


def test_behavior7_the_sibling_pins_are_still_present_in_their_file():
    src = (_ROOT / "tests" / "test_iter158_behavior.py").read_text(encoding="utf-8")
    for needle in ('startswith("- **iter 158 ")', 'startswith("## Item 16")',
                   "PM_SCOUT_LENS_POOL", "roadmap_archive_gaps", "ROADMAP_INDEX_HARD_CHARS"):
        assert needle in src, "iteration 158's file lost its %r assertion" % needle


# --------------------------------------------------------------------------
# behaviors 8-10 -- the INDEX BUDGET paragraph
# --------------------------------------------------------------------------

def _budget_paragraph() -> str:
    text = _index_text()
    start = text.index("INDEX BUDGET")
    tail = text[start:]
    end = tail.find("\n\n")
    return tail if end == -1 else tail[:end]


def test_behavior8_the_index_no_longer_claims_the_paydown_is_blocked():
    text = _index_text()
    for gone in ("THAT PAYDOWN IS BLOCKED", "~988 chars/iteration"):
        assert gone not in text, "the index still contains %r" % gone
    # two-sided: the paragraph these literals lived in is still there.
    assert "INDEX BUDGET" in text, "control failed: INDEX BUDGET paragraph is missing entirely"


def test_behavior9_the_growth_figure_states_its_window_and_method():
    para = _budget_paragraph()
    missing = [lit for lit in ("594", "159", "165", "mean", "1,434", "222") if lit not in para]
    assert missing == [], "the INDEX BUDGET paragraph omits %r" % (missing,)


def test_behavior9_paydown_iterations_are_stated_as_excluded_from_the_mean():
    para = _budget_paragraph().lower()
    assert "exclud" in para, "the paragraph does not say paydowns are excluded from the mean"
    assert "paydown" in para or "compaction" in para, "no paydown/compaction term near the exclusion"


def test_behavior10_the_next_paydown_is_named_as_unblocked():
    para = _budget_paragraph()
    assert "UNBLOCKED" in para.upper(), "the paragraph does not state the paydown is unblocked"
    for block in ("(f)", "(l)", "(t)", "(v)"):
        assert block in para, "the next paydown does not name block %s" % block
    assert "167" in para, "the next paydown is not pre-declared for an iteration"


def test_behavior10_the_legal_move_is_restated():
    para = _budget_paragraph()
    up = para.upper()
    assert "DELETE" in up, "the legal move does not say DELETE from the index"
    assert "## Compacted from the index by iter" in para, "no NEW archive heading form is restated"
    assert "never copy" in para.lower() or "never copie" in para.lower(), (
        "the paragraph does not forbid COPYING"
    )
    assert "- **iter " in para and "- iter " in para, (
        "the paragraph does not name the frozen archive bullet and ledger row it must not touch"
    )


def test_behavior10_the_four_named_blocks_are_the_ones_the_detector_reports():
    # Cross-check the prose against the product's own detector, called (not read).
    blocks = foundry.roadmap_spent_blocks(_index_text(), _archive_text())
    labels = set()
    for b in blocks:
        for attr in ("label", "item", "name", "block"):
            val = getattr(b, attr, None)
            if isinstance(val, str):
                labels.add(val)
    named = {"(f)", "(l)", "(t)", "(v)"}
    if labels:
        hit = {lbl for lbl in named if any(lbl in s for s in labels)}
        assert hit, "the detector names %r, the prose names %r" % (sorted(labels)[:8], sorted(named))


# --------------------------------------------------------------------------
# behavior 11 -- this iteration's own record lands in the ship commit
# --------------------------------------------------------------------------

def test_behavior11_exactly_one_index_ledger_row_of_at_most_120_chars():
    rows = [ln for ln in _index_text().splitlines() if ln.startswith("- iter %d " % THIS_ITER)]
    assert len(rows) == 1, "expected exactly one `- iter 166 ` ledger row, got %d" % len(rows)
    assert len(rows[0]) <= 120, "ledger row is %d chars (max 120)" % len(rows[0])


def test_behavior11_exactly_one_archive_detail_bullet():
    rows = [ln for ln in _archive_text().splitlines() if ln.startswith("- **iter %d " % THIS_ITER)]
    assert len(rows) == 1, "expected exactly one `- **iter 166 ` archive bullet, got %d" % len(rows)


def test_behavior11_archive_has_no_gaps_for_the_index():
    gaps = foundry.roadmap_archive_gaps(_index_text(), _archive_text())
    assert list(gaps) == [], "roadmap_archive_gaps reported %r" % (gaps,)


def test_behavior11_index_is_inside_the_existing_hard_wall():
    size = len(_index_text())
    wall = foundry.ROADMAP_INDEX_HARD_CHARS
    assert size < wall, "index is %d chars, hard wall %d" % (size, wall)


# --------------------------------------------------------------------------
# behavior 12 -- NOTHING IN THE MODULES MOVED
# --------------------------------------------------------------------------

def test_behavior12_both_modules_import_in_a_fresh_interpreter():
    result = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher; print('ok')"],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, "import failed: %s" % (result.stderr[-2000:],)
    assert "ok" in result.stdout


@pytest.mark.parametrize("name", ["archive_headings", "frozen_prefix_violations",
                                  "compaction_heading_count", "archive_rule_violations",
                                  "FROZEN_ARCHIVE_HEADING_PREFIX"])
def test_behavior12_the_rescoped_guard_did_not_leak_into_the_modules(name):
    import dispatcher  # local: keeps the module out of collection-time import cost
    assert not hasattr(foundry, name), "foundry.py gained a new module-level %r" % name
    assert not hasattr(dispatcher, name), "dispatcher.py gained a new module-level %r" % name
