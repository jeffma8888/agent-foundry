"""Iteration 360 -- BLACK-BOX behavior tests: the `auth` failure kind learns the agent
CLI's CURRENT expired-session wording, so the 162 no-output attempt logs carrying that
blob stop being filed as cap timeouts (a `timeout` tells an operator "the work did not fit
the budget"; only `auth` says "a human must re-authenticate").

Spec under test (products/_platform/state/iter-360/pm.md), Expected Behaviors 1-7:
   1. `classify_attempt_failure(<measured blob>)` -> "auth" (it returned "timeout" before).
   2. Case does not decide: the same blob with the sentence upper-cased -> "auth".
   3. Conservative-first ORDERING survives: blob + the 600s cap marker -> "auth", in
      either textual order, because the `auth` entry precedes `timeout` in the table.
   4. Nothing else is stolen from `timeout`: the bare cap marker still -> "timeout", and
      the blob's own second line alone (`identity resolver timed out after 30s`, no
      credentials sentence) still -> "timeout"; the other four kinds are untouched.
   5. Table SHAPE unchanged: 5 entries, same order, same 5 labels, every non-`auth` entry
      byte-identical to the pre-360 table, and the `auth` entry carries exactly 3 needles
      including iteration 196's `credential refresh failed` and iteration 226's
      `auth failed`.
   6. Retry cost unchanged by the re-label: `retry_delay("auth", n) == retry_delay(
      "timeout", n)` for n in 1..5, and this blob's own priced backoff does not move.
   7. The ship-path predicate is explicit: `stage_attempt_killed` is False for a stage
      whose newest attempt log is this blob (`auth` is deliberately NOT a machine kill --
      iteration 194's `test_b3_only_the_timeout_kind_is_a_kill` froze that).

Also guarded, from the spec's ACCEPTANCE CRITERIA rather than its Expected Behaviors, and
decidable from TRACKED text alone so it still holds in the clean clone the release gate
builds (iteration 194 shipped BROKEN because its roadmap record was only decidable after
commit):
   A. This iteration's roadmap record lands in the SAME diff as the code -- exactly one
      `- iter 360 ` ledger row (<= 120 chars, the wall `test_iter124`/`test_iter140` pin),
      exactly one `- **iter 360 ` archive bullet, `roadmap_ledger_gaps(...)` green and
      proved TWO-SIDED against stripped in-memory copies, and the index inside its budget.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-360 PM spec, the conventions
of tests/ (the docstring / frozen-literal / mutation-control shape of
`test_iter226_behavior.py`, which owns the same constant, and the `tmp_path` config +
seeded-attempt-log fixtures of `test_iter194_behavior.py`, which owns
`stage_attempt_killed`), and the product's OWN OBSERVABLE surface -- importing the
modules, reading their PUBLIC constants and CALLING their public functions.  The
implementation TEXT of foundry.py / dispatcher.py was NOT read, and neither were
engineer.md, reviewer.md, IMPLEMENTATION.patch nor `git diff`.

FIXTURE PROVENANCE (measured OUT OF BAND, then carried INLINE): over all files matching
`products/*/state/iter-*/*.attempt*.log`, 162 logs contain this wording and all 162 are
BYTE-IDENTICAL -- 199 characters / 201 utf-8 bytes, three lines (125 / 0 / 72 chars), no
trailing newline, sha256 67c0e59592b6616bf7875b36cf54127140edb322c320ba4d8a92a527d071162c.
Two honest deltas from the spec's prose quote of the same blob, both harmless to the
needle: the byte count is 201 (199 is the CHARACTER count -- the dash is a 3-byte em
dash), and the real separator before `try again` is an EM DASH, not the ASCII hyphen the
spec typed.  Per OPERATOR 2026-08-11 nothing here READS that corpus at test time: it is
gitignored and absent from the fresh clone the release gate builds, so the blob, its
length and its sha256 are frozen literals below.

NEEDLE FRAGMENTATION (deliberate): the measured needle is assembled from two source
fragments, so this module's TEXT never carries it contiguously while its runtime VALUE is
byte-exact.  The rule under test re-classifies any blob containing that phrase, and stage
logs / reports quote test text; keeping the phrase split means no artifact of this
iteration can be mis-read by the very classifier it is grading.

Offline and deterministic: no network, no subprocess, no sleeps, no clock, no git.  Every
file write happens under `tmp_path`; nothing in the tree is mutated (every negative case
edits an in-memory copy of the table).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

THIS_ITER = 360

AUTH = "auth"
TIMEOUT = "timeout"

NEEDLE_196 = "credential refresh failed"   # iteration 196's measured needle
NEEDLE_226 = "auth failed"                 # iteration 226's measured needle

# --- the measured wording, split on purpose (see NEEDLE FRAGMENTATION above) ----------
_FRAG_A = "Credentials were still"
_FRAG_B = "being renewed"
SENTENCE = _FRAG_A + " " + _FRAG_B
NEEDLE_360 = SENTENCE.lower()              # iteration 360's measured needle

# The REAL blob: the ENTIRE content of all 162 matching attempt logs (FIXTURE PROVENANCE).
REAL_BLOB = (
    "agent run failed: subagent turn failed: "
    + SENTENCE
    + " when the request gave up \u2014 try again in a moment\n"
    + "\n"
    + "(detail: dispatch failure: other: identity resolver timed out after 30s)"
)
BLOB_CHARS = 199
BLOB_BYTES = 201
BLOB_SHA256 = "67c0e59592b6616bf7875b36cf54127140edb322c320ba4d8a92a527d071162c"
BLOB_LINE_LENGTHS = [125, 0, 72]

# The blob's OWN second line, alone: it carries `timed out` and NO credentials sentence,
# so it is what must still read `timeout` (spec behavior 4).
DETAIL_LINE_ONLY = "(detail: dispatch failure: other: identity resolver timed out after 30s)"

# the agent CLI's REAL cap-kill line (frozen by iteration 194's own fixtures)
CAP_KILL_LOG = "agent run failed: agent run timed out after 600s"
QUIET_LOG = "stage attempt completed and wrote its report"

# The four NON-auth entries, frozen as literals (spec behavior 5).  A frozen literal is
# the point: "byte-identical to the pre-360 table" read against the LIVE table is
# self-referential (any table equals itself), so only a literal can fail.  A later
# iteration that legitimately edits one of these four is EXPECTED to trip this pin and
# re-pin it deliberately -- that is the brake working, not a false positive.
FROZEN_NON_AUTH_ENTRIES = (
    ("service", ("service is busy", "too many tokens", "throttl")),
    ("stalled", ("connection stalled",)),
    ("cli-error", ("native shortcut did not match",)),
    ("timeout", ("timed out",)),
)
FROZEN_KIND_ORDER = ("service", "stalled", AUTH, "cli-error", TIMEOUT)
AUTH_INDEX = 2
TABLE_LEN = 5
AUTH_NEEDLE_COUNT = 3

ATTEMPTS = (1, 2, 3, 4, 5)

INDEX_PATH = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE_PATH = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
LEDGER_ROW_PREFIX = "- iter %d " % THIS_ITER
ARCHIVE_BULLET_PREFIX = "- **iter %d " % THIS_ITER
LEDGER_ROW_MAX_CHARS = 120
INDEX_HEADROOM_FLOOR = 4000


# --------------------------------------------------------------------------
# helpers -- in-memory table variants + tmp_path config/log fixtures
# --------------------------------------------------------------------------
def _table():
    """The shipped table, normalised to plain tuples so it compares by value."""
    return tuple((kind, tuple(needles)) for kind, needles in foundry.ATTEMPT_FAILURE_MARKERS)


def _pre360_table():
    """The PRE-360 table: same 5 entries, same order, `auth` carrying its two OLD needles.

    This is the mutation control.  It isolates the NEEDLE, not the entry: the `auth`
    tuple shrinks to iterations 196 + 226 and everything else is copied verbatim.
    """
    return tuple(
        (kind, (NEEDLE_196, NEEDLE_226) if kind == AUTH else tuple(needles))
        for kind, needles in foundry.ATTEMPT_FAILURE_MARKERS
    )


def _use_pre360_table(monkeypatch):
    monkeypatch.setattr(foundry, "ATTEMPT_FAILURE_MARKERS", _pre360_table())


def _write_cfg(tmp_path, **over):
    """Minimal product config in a tmp dir: repo/work_root are TMP so the real repo and
    state tree are NEVER touched (iteration 194's fixture shape)."""
    tmp_path = pathlib.Path(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    n = len(list(tmp_path.glob("cfg_*.json")))
    p = tmp_path / ("cfg_%d.json" % n)
    p.write_text(json.dumps(data))
    return p


def _cfg(tmp_path, **over):
    return foundry.load_config(str(_write_cfg(tmp_path, **over)))


def _iter_dir(cfg, iteration):
    return pathlib.Path(cfg.state) / ("iter-%02d" % iteration)


def _seed_log(cfg, iteration, stage, attempt, body):
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    p = d / ("%s.attempt%d.log" % (stage, attempt))
    p.write_text(body, encoding="utf-8")
    return p


def _lines_with(prefix, text):
    return [ln for ln in text.splitlines() if ln.startswith(prefix)]


# ===========================================================================
# Behavior 1 -- the measured expired-session blob classifies `auth`
# ===========================================================================
def test_b1_fixture_is_the_measured_corpus_blob():
    """Anti-drift: if this fails, the fixture -- not the product -- is wrong."""
    assert len(REAL_BLOB) == BLOB_CHARS
    assert len(REAL_BLOB.encode("utf-8")) == BLOB_BYTES
    assert hashlib.sha256(REAL_BLOB.encode("utf-8")).hexdigest() == BLOB_SHA256
    assert [len(ln) for ln in REAL_BLOB.split("\n")] == BLOB_LINE_LENGTHS
    assert not REAL_BLOB.endswith("\n")
    assert NEEDLE_360 in REAL_BLOB.lower()


def test_b1_the_measured_blob_classifies_auth():
    assert foundry.classify_attempt_failure(REAL_BLOB) == AUTH


def test_b1_before_this_change_the_same_blob_classified_timeout(monkeypatch):
    """The other half of behavior 1, and the anti-vacuous control for the whole file:
    with ONLY the two older needles the blob is claimed by the generic `timed out`."""
    _use_pre360_table(monkeypatch)
    assert foundry.classify_attempt_failure(REAL_BLOB) == TIMEOUT


def test_b1_the_wording_also_wins_inside_a_larger_blob():
    # The needle is a SUBSTRING rule, so it must survive the CLI wrapping it in context.
    assert foundry.classify_attempt_failure(
        "stage failed after 3s: " + SENTENCE + " -- see the login flow") == AUTH


# ===========================================================================
# Behavior 2 -- case does not decide
# ===========================================================================
@pytest.mark.parametrize("blob", [
    REAL_BLOB.replace(SENTENCE, SENTENCE.upper()),
    REAL_BLOB.upper(),
    REAL_BLOB.lower(),
    REAL_BLOB.replace(SENTENCE, SENTENCE.swapcase()),
], ids=["sentence_upper", "whole_blob_upper", "whole_blob_lower", "sentence_swapcase"])
def test_b2_classification_is_case_insensitive(blob):
    assert NEEDLE_360 in blob.lower(), "fixture must still carry the wording"
    assert foundry.classify_attempt_failure(blob) == AUTH


def test_b2_the_case_variants_are_really_different_text():
    """Anti-vacuous companion: at least one variant must differ from the raw blob."""
    variants = {REAL_BLOB.replace(SENTENCE, SENTENCE.upper()), REAL_BLOB.upper(),
                REAL_BLOB.lower()}
    assert REAL_BLOB not in variants


# ===========================================================================
# Behavior 3 -- conservative-first ordering is preserved
# ===========================================================================
@pytest.mark.parametrize("blob", [
    REAL_BLOB + "\n" + CAP_KILL_LOG,
    CAP_KILL_LOG + "\n" + REAL_BLOB,
], ids=["needle_first", "cap_marker_first"])
def test_b3_the_auth_entry_wins_a_blob_carrying_both_markers(blob):
    assert NEEDLE_360 in blob.lower() and "timed out" in blob.lower(), \
        "fixture must actually be ambiguous"
    assert foundry.classify_attempt_failure(blob) == AUTH


def test_b3_the_ordering_is_a_property_of_the_table_not_of_text_position():
    first = foundry.classify_attempt_failure(REAL_BLOB + "\n" + CAP_KILL_LOG)
    second = foundry.classify_attempt_failure(CAP_KILL_LOG + "\n" + REAL_BLOB)
    assert first == second == AUTH


def test_b3_the_auth_entry_still_precedes_the_timeout_entry_in_the_table():
    kinds = [kind for kind, _ in _table()]
    assert kinds.index(AUTH) < kinds.index(TIMEOUT)


def test_b3_without_the_new_needle_the_ambiguous_blob_flips_to_timeout(monkeypatch):
    """Proves behavior 3 is decided by the NEW needle plus table order, not by luck."""
    _use_pre360_table(monkeypatch)
    assert foundry.classify_attempt_failure(REAL_BLOB + "\n" + CAP_KILL_LOG) == TIMEOUT


# ===========================================================================
# Behavior 4 -- nothing else is stolen from `timeout` (or any other kind)
# ===========================================================================
def test_b4_the_bare_cap_kill_marker_still_classifies_timeout():
    assert NEEDLE_360 not in CAP_KILL_LOG.lower()
    assert foundry.classify_attempt_failure(CAP_KILL_LOG) == TIMEOUT


def test_b4_the_blobs_own_detail_line_alone_still_classifies_timeout():
    assert DETAIL_LINE_ONLY in REAL_BLOB, "fixture must be the blob's real second line"
    assert NEEDLE_360 not in DETAIL_LINE_ONLY.lower()
    assert foundry.classify_attempt_failure(DETAIL_LINE_ONLY) == TIMEOUT


@pytest.mark.parametrize("blob,expected", [
    ("agent run failed: agent run timed out after 600s", TIMEOUT),
    ("agent run timed out", TIMEOUT),
    ("agent run failed: service is busy, try again later", "service"),
    ("too many tokens in the request", "service"),
    ("Connection stalled - no data received for 120 s", "stalled"),
    ("native shortcut did not match any known verb", "cli-error"),
    ("credential refresh failed (Llm): authentication timed out)", AUTH),
    ("agent run failed: auth failed, please re-run the login flow", AUTH),
    ("some other failure", "other"),
], ids=["cap_kill", "bare_timed_out", "service", "tokens", "stalled", "cli_error",
        "iter196_needle", "iter226_needle", "unclassified"])
def test_b4_every_other_kinds_verdict_is_unchanged(blob, expected):
    assert foundry.classify_attempt_failure(blob) == expected


@pytest.mark.parametrize("blob", ["", None, QUIET_LOG])
def test_b4_empty_none_and_a_quiet_log_still_return_the_default_kind(blob):
    assert foundry.classify_attempt_failure(blob) == foundry.ATTEMPT_FAILURE_DEFAULT


def test_b4_the_default_kind_is_still_other():
    assert foundry.ATTEMPT_FAILURE_DEFAULT == "other"


def test_b4_the_re_label_only_moves_blobs_that_carry_the_new_needle(monkeypatch):
    """Two-sided: for a corpus of non-needle blobs the pre-360 and post-360 tables agree
    verdict-for-verdict, so the needle is the ONLY thing that reassigns anything."""
    corpus = [CAP_KILL_LOG, DETAIL_LINE_ONLY, QUIET_LOG, "", None,
              "agent run failed: service is busy", "connection stalled",
              "native shortcut did not match", NEEDLE_196, NEEDLE_226, "some other failure"]
    after = [foundry.classify_attempt_failure(b) for b in corpus]
    _use_pre360_table(monkeypatch)
    before = [foundry.classify_attempt_failure(b) for b in corpus]
    assert before == after
    # ... while the needle-carrying blob DOES move, in exactly one direction.
    assert foundry.classify_attempt_failure(REAL_BLOB) == TIMEOUT


# ===========================================================================
# Behavior 5 -- the table's shape is unchanged, the change is one needle
# ===========================================================================
def test_b5_the_table_still_has_exactly_five_entries():
    assert len(_table()) == TABLE_LEN


def test_b5_the_five_kind_labels_are_unchanged_and_in_the_same_order():
    assert tuple(kind for kind, _ in _table()) == FROZEN_KIND_ORDER
    assert _table()[AUTH_INDEX][0] == AUTH


def test_b5_every_non_auth_entry_is_byte_identical_to_the_pre_360_table():
    assert tuple(e for e in _table() if e[0] != AUTH) == FROZEN_NON_AUTH_ENTRIES


def test_b5_the_auth_entry_carries_exactly_three_needles():
    needles = dict(_table())[AUTH]
    assert len(needles) == AUTH_NEEDLE_COUNT, \
        "expected %d auth needles, got %d" % (AUTH_NEEDLE_COUNT, len(needles))
    assert all(isinstance(n, str) and n for n in needles)


def test_b5_the_auth_entry_still_carries_both_older_measured_needles():
    needles = dict(_table())[AUTH]
    assert NEEDLE_196 in needles, "iteration 196's needle must survive"
    assert NEEDLE_226 in needles, "iteration 226's needle must survive"


def test_b5_the_auth_entry_carries_this_iterations_needle():
    assert NEEDLE_360 in dict(_table())[AUTH]


@pytest.mark.parametrize("blob,label", [
    ("credential refresh failed (Llm): authentication timed out)", "iter196"),
    ("agent run failed: auth failed, please re-run the login flow", "iter226"),
])
def test_b5_the_older_needles_still_classify_auth(blob, label):
    assert foundry.classify_attempt_failure(blob) == AUTH


def test_b5_the_control_table_differs_from_the_shipped_one_only_in_the_auth_tuple():
    control = _pre360_table()
    assert tuple(k for k, _ in control) == tuple(k for k, _ in _table())
    assert tuple(e for e in control if e[0] != AUTH) == FROZEN_NON_AUTH_ENTRIES
    assert dict(control)[AUTH] == (NEEDLE_196, NEEDLE_226)
    assert dict(_table())[AUTH] != dict(control)[AUTH]


def test_b5_the_monkeypatch_never_leaks_out_of_a_control_test():
    assert len(dict(_table())[AUTH]) == AUTH_NEEDLE_COUNT
    assert NEEDLE_360 in dict(_table())[AUTH]


# ===========================================================================
# Behavior 6 -- retry cost is unchanged by the re-label
# ===========================================================================
@pytest.mark.parametrize("n", ATTEMPTS)
def test_b6_the_auth_and_timeout_ladders_are_equal_at_every_attempt_index(n):
    assert foundry.retry_delay(AUTH, n) == foundry.retry_delay(TIMEOUT, n)


def test_b6_that_equality_is_not_all_ladders_being_equal():
    """Anti-vacuous: the default kind's ladder is a DIFFERENT, slower one."""
    default = foundry.ATTEMPT_FAILURE_DEFAULT
    assert foundry.retry_delay(default, 1) != foundry.retry_delay(AUTH, 1)
    assert foundry.retry_delay(AUTH, 1) < foundry.retry_delay(default, 1)


def test_b6_this_blobs_own_priced_backoff_does_not_move(monkeypatch):
    after = [foundry.retry_delay(foundry.classify_attempt_failure(REAL_BLOB), n)
             for n in ATTEMPTS]
    _use_pre360_table(monkeypatch)
    before = [foundry.retry_delay(foundry.classify_attempt_failure(REAL_BLOB), n)
              for n in ATTEMPTS]
    assert before == after, "the re-label moved this blob's backoff: %r -> %r" % (
        before, after)


def test_b6_a_needle_only_blob_does_move_off_the_default_ladder(monkeypatch):
    """AMBIGUITY NOTED (PM feedback): the spec's "no blob's backoff moves" holds for the
    measured corpus, every member of which ALSO carries `timed out`.  A hypothetical blob
    with the wording and NO timeout marker was `other` before and is `auth` now, so its
    backoff DOES move -- to the FASTER ladder, i.e. in the safe direction.  Pinned here
    relationally so the record is explicit rather than silent."""
    needle_only = "stage failed: " + SENTENCE
    assert "timed out" not in needle_only.lower()
    assert foundry.classify_attempt_failure(needle_only) == AUTH
    after = foundry.retry_delay(AUTH, 1)
    _use_pre360_table(monkeypatch)
    assert foundry.classify_attempt_failure(needle_only) == foundry.ATTEMPT_FAILURE_DEFAULT
    before = foundry.retry_delay(foundry.ATTEMPT_FAILURE_DEFAULT, 1)
    assert after < before, "the re-label must only ever shorten this wait, %r vs %r" % (
        after, before)


# ===========================================================================
# Behavior 7 -- the ship-path predicate: this blob is NOT a machine kill
# ===========================================================================
def test_b7_a_final_attempt_log_of_this_blob_is_not_a_kill(tmp_path):
    cfg = _cfg(tmp_path)
    _seed_log(cfg, THIS_ITER, "final", 1, REAL_BLOB)
    assert foundry.stage_attempt_killed(cfg, THIS_ITER, "final") is False


def test_b7_the_cap_kill_marker_is_still_a_kill(tmp_path):
    """Anti-vacuous twin: the predicate has NOT been flattened to always-False."""
    cfg = _cfg(tmp_path)
    _seed_log(cfg, THIS_ITER, "final", 1, CAP_KILL_LOG)
    assert foundry.stage_attempt_killed(cfg, THIS_ITER, "final") is True


def test_b7_without_the_new_needle_the_same_log_read_as_a_kill(monkeypatch, tmp_path):
    """The mutation control on the SHIP PATH: the False above is produced by the new
    needle, and this is exactly the mis-reading iteration 360 exists to remove."""
    cfg = _cfg(tmp_path)
    _seed_log(cfg, THIS_ITER, "final", 1, REAL_BLOB)
    _use_pre360_table(monkeypatch)
    assert foundry.stage_attempt_killed(cfg, THIS_ITER, "final") is True


@pytest.mark.parametrize("stage", ["final", "engineer", "tester", "pm_scout_a"])
def test_b7_the_verdict_is_false_for_this_blob_in_any_stage(tmp_path, stage):
    cfg = _cfg(tmp_path)
    _seed_log(cfg, THIS_ITER, stage, 1, REAL_BLOB)
    assert foundry.stage_attempt_killed(cfg, THIS_ITER, stage) is False


def test_b7_the_verdict_stays_per_stage(tmp_path):
    cfg = _cfg(tmp_path)
    _seed_log(cfg, THIS_ITER, "pm_scout_a", 1, REAL_BLOB)
    _seed_log(cfg, THIS_ITER, "final", 1, CAP_KILL_LOG)
    assert foundry.stage_attempt_killed(cfg, THIS_ITER, "pm_scout_a") is False
    assert foundry.stage_attempt_killed(cfg, THIS_ITER, "final") is True


def test_b7_the_newest_attempt_still_decides(tmp_path):
    cfg = _cfg(tmp_path)
    _seed_log(cfg, THIS_ITER, "final", 1, CAP_KILL_LOG)
    _seed_log(cfg, THIS_ITER, "final", 2, REAL_BLOB)
    assert foundry.stage_attempt_killed(cfg, THIS_ITER, "final") is False


def test_b7_the_newest_attempt_decides_in_the_other_direction_too(tmp_path):
    cfg = _cfg(tmp_path)
    _seed_log(cfg, THIS_ITER, "final", 1, REAL_BLOB)
    _seed_log(cfg, THIS_ITER, "final", 2, CAP_KILL_LOG)
    assert foundry.stage_attempt_killed(cfg, THIS_ITER, "final") is True


def test_b7_a_missing_log_is_still_not_a_kill(tmp_path):
    cfg = _cfg(tmp_path)
    assert foundry.stage_attempt_killed(cfg, THIS_ITER, "final") is False


# ===========================================================================
# Acceptance guard A -- this iteration's roadmap record ships in THIS diff
# ===========================================================================
def test_a_the_ledger_row_and_archive_bullet_exist_exactly_once():
    rows = _lines_with(LEDGER_ROW_PREFIX, INDEX_PATH.read_text(encoding="utf-8"))
    assert len(rows) == 1, \
        "expected exactly one %r row, got %d" % (LEDGER_ROW_PREFIX, len(rows))
    assert len(rows[0]) <= LEDGER_ROW_MAX_CHARS, \
        "ledger row is %d chars, over the %d wall: %r" % (
            len(rows[0]), LEDGER_ROW_MAX_CHARS, rows[0])
    bullets = _lines_with(ARCHIVE_BULLET_PREFIX, ARCHIVE_PATH.read_text(encoding="utf-8"))
    assert len(bullets) == 1, \
        "expected exactly one %r bullet, got %d" % (ARCHIVE_BULLET_PREFIX, len(bullets))


def test_a_the_roadmap_record_check_is_green_and_two_sided():
    index_text = INDEX_PATH.read_text(encoding="utf-8")
    archive_text = ARCHIVE_PATH.read_text(encoding="utf-8")
    assert foundry.roadmap_ledger_gaps(index_text, archive_text, (THIS_ITER,)) == []
    stripped_index = "\n".join(
        ln for ln in index_text.splitlines() if not ln.startswith(LEDGER_ROW_PREFIX))
    stripped_archive = "\n".join(
        ln for ln in archive_text.splitlines() if not ln.startswith(ARCHIVE_BULLET_PREFIX))
    assert foundry.roadmap_ledger_gaps(
        stripped_index, stripped_archive, (THIS_ITER,)) == [THIS_ITER]


def test_a_the_index_stays_inside_its_budget_with_the_row_in_place():
    budget = foundry.roadmap_index_budget(INDEX_PATH.read_text(encoding="utf-8"))
    assert budget.over_budget is False
    assert budget.near_wall is False
    assert budget.headroom >= INDEX_HEADROOM_FLOOR, \
        "index headroom is %d, under the %d floor" % (budget.headroom, INDEX_HEADROOM_FLOOR)


def test_a_both_modules_import_in_process():
    assert foundry is not None
    assert dispatcher is not None
