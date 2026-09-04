"""Iteration 226 -- BLACK-BOX behavior tests: the `auth` failure kind learns the agent
CLI's CURRENT auth-failure wording, `auth failed`, so an auth-failed stage attempt is
classified `auth` and priced on the fast 60/120/240 ladder that kind already owns
instead of the `other` default's 600/1200/2400.

Spec under test (products/_platform/state/iter-226/pm.md), Expected Behaviors 1-8:
   1. `classify_attempt_failure("auth failed")` -> "auth" -- the REAL 11-byte attempt-log
      blob, verbatim, carried INLINE (see the fixture note below).
   2. `classify_attempt_failure("AUTH FAILED")` -> "auth": the table's documented
      lowercase-substring convention is unchanged, so case does not decide.
   3. PURELY ADDITIVE: the `auth` entry carries BOTH `credential refresh failed` and
      `auth failed`, and iteration 196's own needle still classifies `auth`.
   4. The table's SHAPE is untouched: exactly 5 entries, `auth` still at index 2, and the
      other four entries byte-identical to today's (frozen literals below).
   5. Conservative-first ordering survives: a blob carrying `auth failed` AND a
      long-ladder marker classifies to the LONG-ladder kind in EITHER textual order --
      service+auth -> "service", stalled+auth -> "stalled".  First-rule-wins is a
      property of the TABLE ORDER, so text position must not matter.
   6. `retry_delay("auth", a)` for a in (1,2,3) is [60,120,240], and an `auth failed`
      blob now prices to exactly that through
      `retry_delay(classify_attempt_failure(blob), a)`.
   7. MUTATION CONTROL: with `ATTEMPT_FAILURE_MARKERS` monkeypatched back to an `auth`
      entry holding ONLY `credential refresh failed`, behaviors 1 and 6 go RED -- the
      blob returns "other" and prices [600,1200,2400] again.  So neither can pass
      vacuously, and the NEW NEEDLE (not some other rule) is what produces the verdict.
   8. Non-matching blobs are untouched: "some other failure" -> "other" and
      "agent run timed out" -> "timeout".

Also guarded, from the spec's ACCEPTANCE CRITERIA rather than its Expected Behaviors, and
decidable from TRACKED text alone so it still holds in the clean clone the release gate
builds (iteration 194 shipped BROKEN because its roadmap record was only decidable after
commit):
   A. This iteration's roadmap record lands in the SAME diff as the code: exactly one
      `- iter 226 ` ledger row (<= 120 chars) in PLATFORM_ROADMAP.md, exactly one
      `- **iter 226 ` bullet in PLATFORM_ROADMAP_ARCHIVE.md, `roadmap_ledger_gaps(...)`
      green and proved TWO-SIDED against stripped in-memory copies, and the index inside
      its budget.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-226 PM spec's Expected
Behaviors and Acceptance Criteria, the conventions of tests/ (the docstring / frozen-
literal / two-sided-control shape of test_iter196_behavior.py, which owns the same
constant), and the product's OWN OBSERVABLE surface -- importing the modules, reading
their PUBLIC constants and CALLING their public functions.  The implementation TEXT of
foundry.py / dispatcher.py was NOT read, and neither were engineer.md, reviewer.md,
IMPLEMENTATION.patch nor `git diff`.

FIXTURE PROVENANCE: `auth failed` was confirmed OUT OF BAND to be the entire content of
the 11-byte attempt logs this iteration exists for (`products/_platform/state/iter-221/
pm_scout_a.attempt1..4.log`, 11 bytes each) and is then carried INLINE.  Per OPERATOR
2026-08-11 no assertion in this module reads `products/**/state/` or anything else
gitignored -- that corpus is absent from a fresh clone, so an assertion over it would be
a test that passes only on one machine.

Offline and deterministic: no network, no subprocess, no sleeps, no clock, no git, no
file writes.  Nothing in the tree is mutated (every negative case edits an in-memory
copy of the table).
"""

import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe

THIS_ITER = 226
AUTH = "auth"
OLD_NEEDLE = "credential refresh failed"   # iteration 196's measured needle
NEW_NEEDLE = "auth failed"                 # iteration 226's measured needle

# The REAL blob: the ENTIRE content of the 11-byte attempt logs (see FIXTURE PROVENANCE).
REAL_AUTH_BLOB = "auth failed"

# A real iteration-196-era blob, in python escape notation, which ALSO carries `timed out`
# -- so it doubles as proof that the `auth` entry still wins over `timeout`.
OLD_WORDING_BLOB = (
    "credential refresh failed (Llm): authentication timed out)"
)

# The four NON-auth entries, frozen as literals (Expected Behavior 4).  A frozen literal
# is the point here: the claim is that this iteration touched NOTHING but the `auth`
# entry's needle tuple, and "byte-identical to today's" read against the LIVE table is
# self-referential (any table equals itself), so only a literal can fail.  A LATER
# iteration that legitimately edits one of these four needles is EXPECTED to trip this
# pin and re-pin it deliberately -- that is the brake working, not a false positive.
FROZEN_NON_AUTH_ENTRIES = (
    ("service", ("service is busy", "too many tokens", "throttl")),
    ("stalled", ("connection stalled",)),
    ("cli-error", ("native shortcut did not match",)),
    ("timeout", ("timed out",)),
)
AUTH_INDEX = 2
TABLE_LEN = 5

AUTH_LADDER = [60, 120, 240]
OTHER_LADDER = [600, 1200, 2400]
ATTEMPTS = (1, 2, 3)

INDEX_PATH = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE_PATH = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
LEDGER_ROW_PREFIX = "- iter %d " % THIS_ITER
ARCHIVE_BULLET_PREFIX = "- **iter %d " % THIS_ITER
LEDGER_ROW_MAX_CHARS = 120
INDEX_HEADROOM_FLOOR = 4000


def _table():
    """The shipped table, normalised to plain tuples so it compares by value."""
    return tuple((kind, tuple(needles)) for kind, needles in foundry.ATTEMPT_FAILURE_MARKERS)


def _table_with_only_old_auth_needle():
    """The PRE-226 table: same 5 entries, same order, `auth` carrying ONE needle."""
    return tuple(
        (kind, (OLD_NEEDLE,) if kind == AUTH else tuple(needles))
        for kind, needles in foundry.ATTEMPT_FAILURE_MARKERS
    )


def _lines_with(prefix, text):
    return [ln for ln in text.splitlines() if ln.startswith(prefix)]


# ===========================================================================
# Behavior 1 -- the real 11-byte blob classifies `auth`
# ===========================================================================
def test_b1_the_real_eleven_byte_blob_classifies_auth():
    assert len(REAL_AUTH_BLOB.encode("utf-8")) == 11, \
        "fixture drifted from the real 11-byte attempt log"
    assert foundry.classify_attempt_failure(REAL_AUTH_BLOB) == AUTH


def test_b1_the_wording_also_classifies_auth_inside_a_larger_blob():
    # The needle is a SUBSTRING rule, so the same wording must win when the CLI
    # eventually wraps it in context.
    assert foundry.classify_attempt_failure(
        "agent run failed: auth failed, please re-run the login flow") == AUTH


# ===========================================================================
# Behavior 2 -- case does not decide (lowercase-substring convention unchanged)
# ===========================================================================
@pytest.mark.parametrize("blob", ["AUTH FAILED", "Auth Failed", "aUtH fAiLeD", "auth failed"])
def test_b2_classification_is_case_insensitive(blob):
    assert foundry.classify_attempt_failure(blob) == AUTH


# ===========================================================================
# Behavior 3 -- purely ADDITIVE: both needles present, the old one still works
# ===========================================================================
def test_b3_the_auth_entry_carries_both_measured_needles():
    needles = dict(_table())[AUTH]
    assert OLD_NEEDLE in needles, \
        "iteration 196's measured needle must survive, got %r" % (needles,)
    assert NEW_NEEDLE in needles, \
        "iteration 226's measured needle is missing, got %r" % (needles,)


def test_b3_the_older_needle_still_classifies_auth():
    assert foundry.classify_attempt_failure(OLD_WORDING_BLOB) == AUTH


def test_b3_the_older_needle_still_beats_the_timeout_needle():
    # OLD_WORDING_BLOB carries `timed out` too; `auth` sits BEFORE `timeout`, so the
    # additive change must not have disturbed that verdict.
    assert "timed out" in OLD_WORDING_BLOB
    assert foundry.classify_attempt_failure(OLD_WORDING_BLOB) != "timeout"


# ===========================================================================
# Behavior 4 -- the table's SHAPE is untouched
# ===========================================================================
def test_b4_the_table_still_has_exactly_five_entries():
    assert len(_table()) == TABLE_LEN


def test_b4_the_auth_entry_is_still_at_index_two():
    assert _table()[AUTH_INDEX][0] == AUTH


def test_b4_the_other_four_entries_are_byte_identical_to_todays():
    assert tuple(e for e in _table() if e[0] != AUTH) == FROZEN_NON_AUTH_ENTRIES


def test_b4_no_kind_was_added_or_renamed():
    assert tuple(kind for kind, _ in _table()) == \
        ("service", "stalled", AUTH, "cli-error", "timeout")


# ===========================================================================
# Behavior 5 -- conservative-first ordering, in EITHER textual order
# ===========================================================================
@pytest.mark.parametrize("blob,expected", [
    ("service is busy: auth failed", "service"),
    ("auth failed: service is busy", "service"),
    ("connection stalled - no data received for 120 s: auth failed", "stalled"),
    ("auth failed: connection stalled - no data received for 120 s", "stalled"),
])
def test_b5_a_long_ladder_marker_still_wins_an_ambiguous_blob(blob, expected):
    assert NEW_NEEDLE in blob, "fixture must actually be ambiguous"
    assert foundry.classify_attempt_failure(blob) == expected


def test_b5_the_ordering_is_a_property_of_the_table_not_of_text_position():
    # Same two markers, mirrored -- identical verdict.  If the classifier ever scanned by
    # text position instead of table order, exactly one of these would flip.
    first = foundry.classify_attempt_failure("service is busy: auth failed")
    second = foundry.classify_attempt_failure("auth failed: service is busy")
    assert first == second == "service"


# ===========================================================================
# Behavior 6 -- the blob now prices on the FAST ladder
# ===========================================================================
def test_b6_the_auth_ladder_is_sixty_one_twenty_two_forty():
    assert [foundry.retry_delay(AUTH, a) for a in ATTEMPTS] == AUTH_LADDER


def test_b6_the_real_blob_prices_through_the_classifier_to_the_fast_ladder():
    kind = foundry.classify_attempt_failure(REAL_AUTH_BLOB)
    assert [foundry.retry_delay(kind, a) for a in ATTEMPTS] == AUTH_LADDER


def test_b6_the_fast_ladder_is_not_the_default_it_replaces():
    # Anti-vacuous companion: the whole point is that these two ladders DIFFER.
    assert [foundry.retry_delay(foundry.ATTEMPT_FAILURE_DEFAULT, a) for a in ATTEMPTS] \
        == OTHER_LADDER
    assert AUTH_LADDER != OTHER_LADDER


# ===========================================================================
# Behavior 7 -- MUTATION CONTROL: behaviors 1 and 6 are red without the new needle
# ===========================================================================
def test_b7_without_the_new_needle_the_blob_falls_back_to_other(monkeypatch):
    monkeypatch.setattr(
        foundry, "ATTEMPT_FAILURE_MARKERS", _table_with_only_old_auth_needle())
    assert foundry.classify_attempt_failure(REAL_AUTH_BLOB) == \
        foundry.ATTEMPT_FAILURE_DEFAULT


def test_b7_without_the_new_needle_the_blob_prices_on_the_slow_ladder(monkeypatch):
    monkeypatch.setattr(
        foundry, "ATTEMPT_FAILURE_MARKERS", _table_with_only_old_auth_needle())
    kind = foundry.classify_attempt_failure(REAL_AUTH_BLOB)
    assert [foundry.retry_delay(kind, a) for a in ATTEMPTS] == OTHER_LADDER
    assert foundry.retry_delay(kind, 1) == 600


def test_b7_the_control_table_is_otherwise_identical_to_the_shipped_one(monkeypatch):
    # The control must isolate the NEEDLE, not the entry: same kinds, same order,
    # same other-four needles -- only the `auth` tuple shrinks.
    control = _table_with_only_old_auth_needle()
    assert tuple(k for k, _ in control) == tuple(k for k, _ in _table())
    assert tuple(e for e in control if e[0] != AUTH) == FROZEN_NON_AUTH_ENTRIES
    assert dict(control)[AUTH] == (OLD_NEEDLE,)


def test_b7_the_control_leaves_the_older_needle_working(monkeypatch):
    monkeypatch.setattr(
        foundry, "ATTEMPT_FAILURE_MARKERS", _table_with_only_old_auth_needle())
    assert foundry.classify_attempt_failure(OLD_WORDING_BLOB) == AUTH


def test_b7_the_monkeypatch_is_undone_after_the_control_tests():
    # Guards against a leaked patch making the positive cases vacuous in another order.
    assert dict(_table())[AUTH] != (OLD_NEEDLE,)
    assert NEW_NEEDLE in dict(_table())[AUTH]


# ===========================================================================
# Behavior 8 -- non-matching blobs are untouched
# ===========================================================================
@pytest.mark.parametrize("blob,expected", [
    ("some other failure", "other"),
    ("agent run timed out", "timeout"),
    ("agent run failed: service is busy, try again later", "service"),
    ("Connection stalled - no data received for 120 s", "stalled"),
    ("native shortcut did not match any known verb", "cli-error"),
])
def test_b8_a_blob_matching_neither_auth_needle_is_untouched(blob, expected):
    assert NEW_NEEDLE not in blob.lower()
    assert OLD_NEEDLE not in blob.lower()
    assert foundry.classify_attempt_failure(blob) == expected


def test_b8_the_default_kind_is_still_other():
    assert foundry.ATTEMPT_FAILURE_DEFAULT == "other"


@pytest.mark.parametrize("blob", ["", None])
def test_b8_empty_and_none_still_return_the_default_kind(blob):
    assert foundry.classify_attempt_failure(blob) == foundry.ATTEMPT_FAILURE_DEFAULT


# ===========================================================================
# Acceptance guard A -- this iteration's roadmap record ships in THIS diff
# ===========================================================================
def test_a_the_ledger_row_and_archive_bullet_exist_exactly_once():
    rows = _lines_with(LEDGER_ROW_PREFIX, INDEX_PATH.read_text())
    assert len(rows) == 1, \
        "expected exactly one %r row, got %d" % (LEDGER_ROW_PREFIX, len(rows))
    assert len(rows[0]) <= LEDGER_ROW_MAX_CHARS, \
        "ledger row is %d chars, over the %d limit: %r" % (
            len(rows[0]), LEDGER_ROW_MAX_CHARS, rows[0])
    bullets = _lines_with(ARCHIVE_BULLET_PREFIX, ARCHIVE_PATH.read_text())
    assert len(bullets) == 1, \
        "expected exactly one %r bullet, got %d" % (ARCHIVE_BULLET_PREFIX, len(bullets))


def test_a_the_roadmap_record_check_is_green_and_two_sided():
    index_text = INDEX_PATH.read_text()
    archive_text = ARCHIVE_PATH.read_text()
    assert foundry.roadmap_ledger_gaps(index_text, archive_text, (THIS_ITER,)) == []
    stripped_index = "\n".join(
        ln for ln in index_text.splitlines() if not ln.startswith(LEDGER_ROW_PREFIX))
    stripped_archive = "\n".join(
        ln for ln in archive_text.splitlines() if not ln.startswith(ARCHIVE_BULLET_PREFIX))
    assert foundry.roadmap_ledger_gaps(
        stripped_index, stripped_archive, (THIS_ITER,)) == [THIS_ITER]


def test_a_the_index_stays_inside_its_budget_with_the_row_in_place():
    budget = foundry.roadmap_index_budget(INDEX_PATH.read_text())
    assert budget.over_budget is False
    assert budget.near_wall is False
    assert budget.headroom >= INDEX_HEADROOM_FLOOR, \
        "index headroom is %d, under the %d floor" % (budget.headroom, INDEX_HEADROOM_FLOOR)


def test_a_dispatcher_imported_in_process_alongside_foundry():
    # No subprocess (this iteration's test is spec'd offline/no-subprocess), so the
    # import-safety claim is carried by the module-level imports above.
    assert dispatcher is not None
    assert foundry is not None
