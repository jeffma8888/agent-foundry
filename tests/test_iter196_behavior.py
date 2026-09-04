"""Iteration 196 -- BLACK-BOX behavior tests: an EXPIRED SESSION gets its own `auth`
failure kind, classified BEFORE the `timeout` needle and priced IDENTICALLY to it.

Spec under test (products/_platform/state/iter-196/pm.md), Expected Behaviors 1-8:
   1. `classify_attempt_failure` returns "auth" for each of the three REAL on-disk shapes,
      carried here as INLINE literals in python escape notation.  The separator after
      `failed` is U+2014 EM DASH (so no needle may span it), and matching stays
      case-insensitive -- the real blobs capitalise `Credential`, and fixture 2's ONLY
      occurrence of the wording is the capitalised one.
   2. The two long-ladder kinds still win an ambiguous blob: service+auth -> "service",
      stalled+auth -> "stalled" (the second is 1 of the 365 real logs).  `auth` therefore
      sits at index 2 of `ATTEMPT_FAILURE_MARKERS`, after `service` and `stalled`.
   3. `auth` beats `timeout` AND `cli-error` -- the 363-log case and the point of the order.
   4. The relabel is COST-NEUTRAL, proved against the INCUMBENT rather than literals:
      `retry_delay("auth", n) == retry_delay("timeout", n)` for every n in 1..MAX_ATTEMPTS.
      Anti-vacuous companion: it must NOT equal the ladderless `BACKOFFS` price, which is
      the ten-fold regression this behavior exists to forbid.
   5. The extension point is `KIND_RETRY_LADDERS`, not `FAST_RETRY_KINDS`: "auth" is a key
      of the map, `FAST_RETRY_KINDS` still equals ("timeout", "cli-error"), and `BACKOFFS`,
      `TIMEOUT_BACKOFFS`, `RETRY_DELAY_FLOOR` are unchanged.
   6. The derived table and both shipped docs stay consistent: `retry_ladder_lines()` still
      returns EXACTLY 3 lines, exactly one of them names `auth`, and that fast line names
      `auth` alongside `timeout, cli-error` and appears in ARCHITECTURE.md and CONTINUOUS.md
      (arrows normalised, because the docs use U+2192 and the render uses ASCII `->`).
   7. TWO-SIDED, so the check cannot be vacuous: with the `auth` entry removed from
      `ATTEMPT_FAILURE_MARKERS` by monkeypatch, fixture 1 classifies "timeout" again --
      proving the NEW ENTRY, not some other rule, produces the verdict.  A blob with no
      auth wording classifies exactly as it does today, patched or not.
   8. Totality on the retry path is preserved: "" and None still return
      `ATTEMPT_FAILURE_DEFAULT`, the function does no file I/O, and it raises with no input.

Also guarded, from the spec's ACCEPTANCE CRITERIA rather than its Expected Behaviors, and
decidable from TRACKED text alone so it holds in the clean clone `preship` builds
(iteration 194 shipped BROKEN because its roadmap record was only decidable after commit):
   A. `ATTEMPT_FAILURE_MARKERS` gained EXACTLY one entry; the other four are byte-identical
      and in the same relative order, and the new entry carries exactly ONE needle.
   B. This iteration's roadmap record lands in the SAME diff as the code: exactly one
      `- iter 196 ` ledger row (<= 120 chars) in PLATFORM_ROADMAP.md, exactly one
      `- **iter 196 ` bullet in PLATFORM_ROADMAP_ARCHIVE.md, and
      `roadmap_ledger_gaps(index, archive, (196,)) == []` -- proved TWO-SIDED by removing
      the rows from in-memory copies.  The index stays inside its budget.
   C. `import foundry` and `import dispatcher` still succeed in a FRESH interpreter.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-196 PM spec's Expected Behaviors
and Acceptance Criteria, the conventions of tests/ (the docstring/fixture shape of
test_iter190_behavior.py and the `_index_text` / fresh-import shape of
test_iter195_behavior.py), and the product's OWN OBSERVABLE surface -- importing the
modules, reading their PUBLIC constants and CALLING their public functions.  The
implementation TEXT of foundry.py / dispatcher.py was NOT read, and neither were
engineer.md, reviewer.md, fix_review.md, IMPLEMENTATION.patch nor `git diff`.

The three fixtures were confirmed byte-exact against the real attempt logs OUT OF BAND
(326 + 33 + 1 files at 236 / 171 / 244 chars) and are then carried INLINE: per OPERATOR
2026-08-11 no assertion in this module reads `products/**/state/` or anything else
gitignored, so every one of them is decidable in the fresh clone the release gate builds.

Offline and deterministic: no network, no git writes, no sleeps, no clock, and exactly one
subprocess -- the local fresh-interpreter import probe.  Nothing in the tree is mutated
(every negative case edits an in-memory copy of the text).
"""
from __future__ import annotations

import builtins
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe

THIS_ITER = 196
AUTH = "auth"
AUTH_NEEDLE = "credential refresh failed"

# ---------------------------------------------------------------------------
# The three REAL on-disk shapes, verbatim, in PYTHON ESCAPE NOTATION.
# `\u2014` is the EM DASH the real blobs use; the common prefix is identical in
# all three, which is why the spec elides it with `...` for fixtures 2 and 3.
# ---------------------------------------------------------------------------
_REAL_PREFIX = (
    "agent run failed: subagent turn failed: Credential refresh failed \u2014 "
    "your session may have expired\n\n(detail: dispatch failure: other: "
)
# 326 files on disk.  Also contains `timed out`, so today it is labelled `timeout`.
AUTH_BLOB_TIMED_OUT = _REAL_PREFIX + (
    "an error occurred while loading credentials: "
    "credential refresh failed (Llm): authentication timed out)"
)
# 33 files.  Its ONLY occurrence of the wording is the capitalised one in the prefix,
# so this fixture is what makes case-insensitive matching load-bearing.
AUTH_BLOB_IDENTITY_RESOLVER = _REAL_PREFIX + "identity resolver timed out after 30s)"
# 1 file.  Carries NO `timed out`, so without the new entry it falls through to the default.
AUTH_BLOB_CANCELLED = _REAL_PREFIX + (
    "an error occurred while loading credentials: "
    "credential refresh failed (Llm): authentication cancelled by user)"
)
REAL_AUTH_BLOBS = (
    ("timed-out", AUTH_BLOB_TIMED_OUT, 236),
    ("identity-resolver", AUTH_BLOB_IDENTITY_RESOLVER, 171),
    ("cancelled-by-user", AUTH_BLOB_CANCELLED, 244),
)

# What each real shape classified as BEFORE this iteration, i.e. what it must fall back to
# when the `auth` entry is removed.  This is the two-sided control for behavior 7.
PRE_196_VERDICTS = {
    "timed-out": "timeout",
    "identity-resolver": "timeout",
    "cancelled-by-user": foundry.ATTEMPT_FAILURE_DEFAULT,
}

# The four pre-196 entries, in their pre-196 relative order (Acceptance guard A).
PRE_196_ENTRIES = (
    ("service", ("service is busy", "too many tokens", "throttl")),
    ("stalled", ("connection stalled",)),
    ("cli-error", ("native shortcut did not match",)),
    ("timeout", ("timed out",)),
)

INDEX_PATH = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE_PATH = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
DOC_PATHS = (_ROOT / "ARCHITECTURE.md", _ROOT / "CONTINUOUS.md")

LEDGER_ROW_PREFIX = "- iter %d " % THIS_ITER
ARCHIVE_BULLET_PREFIX = "- **iter %d " % THIS_ITER
LEDGER_ROW_MAX_CHARS = 120
INDEX_HEADROOM_FLOOR = 4000


def _kinds():
    return tuple(kind for kind, _ in foundry.ATTEMPT_FAILURE_MARKERS)


def _entries_without_auth():
    return tuple(e for e in foundry.ATTEMPT_FAILURE_MARKERS if e[0] != AUTH)


def _normalize_arrows(text):
    return text.replace("\u2192", "->")


def _lines_with(prefix, text):
    return [ln for ln in text.splitlines() if ln.startswith(prefix)]


# ===========================================================================
# Behavior 1 -- the new kind exists and fires on the real wording
# ===========================================================================
@pytest.mark.parametrize("name,blob,length", REAL_AUTH_BLOBS)
def test_b1_each_real_expired_session_shape_classifies_auth(name, blob, length):
    assert len(blob) == length, (
        "fixture %r drifted from the real on-disk blob: %d chars, expected %d"
        % (name, len(blob), length))
    assert foundry.classify_attempt_failure(blob) == AUTH, (
        "real shape %r must classify as %r, got %r"
        % (name, AUTH, foundry.classify_attempt_failure(blob)))


def test_b1_the_separator_is_an_em_dash_and_no_needle_spans_it():
    # The real wording is split by U+2014; a needle containing it would match nothing.
    assert "\u2014" in AUTH_BLOB_TIMED_OUT
    assert " - your session" not in AUTH_BLOB_TIMED_OUT
    auth_needles = dict(foundry.ATTEMPT_FAILURE_MARKERS)[AUTH]
    for needle in auth_needles:
        assert "\u2014" not in needle, "needle %r spans the em dash" % (needle,)


def test_b1_matching_is_case_insensitive_on_the_real_capitalisation():
    # Fixture 2's only occurrence is `Credential refresh failed` (capital C).
    assert AUTH_NEEDLE not in AUTH_BLOB_IDENTITY_RESOLVER
    assert AUTH_NEEDLE in AUTH_BLOB_IDENTITY_RESOLVER.lower()
    for blob in (AUTH_BLOB_IDENTITY_RESOLVER,
                 AUTH_BLOB_IDENTITY_RESOLVER.lower(),
                 AUTH_BLOB_IDENTITY_RESOLVER.upper()):
        assert foundry.classify_attempt_failure(blob) == AUTH


# ===========================================================================
# Behavior 2 -- the long ladders still win an ambiguous blob
# ===========================================================================
@pytest.mark.parametrize("other_marker,expected", [
    ("service is busy", "service"),
    ("connection stalled", "stalled"),
])
def test_b2_long_ladder_kinds_outrank_auth_in_an_ambiguous_blob(other_marker, expected):
    blob = AUTH_BLOB_TIMED_OUT + "\n" + other_marker
    assert foundry.classify_attempt_failure(blob) == expected
    # ...and the order does not depend on which text came first.
    blob_reversed = other_marker + "\n" + AUTH_BLOB_TIMED_OUT
    assert foundry.classify_attempt_failure(blob_reversed) == expected


def test_b2_auth_sits_at_index_two_of_the_marker_table():
    kinds = _kinds()
    assert kinds.index(AUTH) == 2, "expected auth at index 2, table is %r" % (kinds,)
    assert kinds == ("service", "stalled", AUTH, "cli-error", "timeout")


# ===========================================================================
# Behavior 3 -- auth beats timeout and cli-error
# ===========================================================================
@pytest.mark.parametrize("weaker_marker", ["timed out", "native shortcut did not match"])
def test_b3_auth_outranks_the_fast_ladder_kinds(weaker_marker):
    blob = "%s :: %s" % (AUTH_NEEDLE, weaker_marker)
    assert foundry.classify_attempt_failure(blob) == AUTH
    assert foundry.classify_attempt_failure("%s :: %s" % (weaker_marker, AUTH_NEEDLE)) == AUTH


# ===========================================================================
# Behavior 4 -- the relabel is COST-NEUTRAL against the incumbent
# ===========================================================================
def test_b4_auth_is_priced_exactly_like_the_label_it_takes_over_from():
    for n in range(1, foundry.MAX_ATTEMPTS + 1):
        assert foundry.retry_delay(AUTH, n) == foundry.retry_delay("timeout", n), (
            "attempt %d: auth %ds != timeout %ds -- the relabel must be cost-neutral"
            % (n, foundry.retry_delay(AUTH, n), foundry.retry_delay("timeout", n)))


def test_b4_auth_does_not_fall_through_to_the_ten_fold_default_ladder():
    # Anti-vacuous: a new kind with NO ladder would draw BACKOFFS instead, which is the
    # ten-fold cost regression on 8.5% of all attempts that behavior 4 exists to forbid.
    default_kind = foundry.ATTEMPT_FAILURE_DEFAULT
    assert foundry.retry_delay(AUTH, 1) < foundry.retry_delay(default_kind, 1)
    assert foundry.retry_delay(AUTH, 1) * 5 <= foundry.retry_delay(default_kind, 1)


# ===========================================================================
# Behavior 5 -- the extension point is KIND_RETRY_LADDERS
# ===========================================================================
def test_b5_auth_is_a_key_of_the_ladder_map():
    assert AUTH in foundry.KIND_RETRY_LADDERS
    assert set(foundry.KIND_RETRY_LADDERS) == {"stalled", AUTH}
    assert list(foundry.KIND_RETRY_LADDERS[AUTH]) == list(foundry.TIMEOUT_BACKOFFS)


def test_b5_the_pinned_sets_and_ladders_are_unchanged():
    assert tuple(foundry.FAST_RETRY_KINDS) == ("timeout", "cli-error")
    assert AUTH not in foundry.FAST_RETRY_KINDS
    assert list(foundry.BACKOFFS) == [600, 1200, 2400]
    assert list(foundry.TIMEOUT_BACKOFFS) == [60, 120, 240]
    assert foundry.RETRY_DELAY_FLOOR == 60


def test_b5_patching_the_map_moves_auth_and_nothing_else():
    # Two-sided proof that the map -- not the set -- is what prices `auth`.
    patched = dict(foundry.KIND_RETRY_LADDERS)
    patched[AUTH] = [111, 222, 333]
    original = foundry.KIND_RETRY_LADDERS
    try:
        foundry.KIND_RETRY_LADDERS = patched
        assert foundry.retry_delay(AUTH, 1) == 111
        assert foundry.retry_delay("timeout", 1) == 60
    finally:
        foundry.KIND_RETRY_LADDERS = original
    assert foundry.retry_delay(AUTH, 1) == 60


# ===========================================================================
# Behavior 6 -- the derived table and both docs stay consistent
# ===========================================================================
def test_b6_the_rendered_ladder_table_still_has_three_lines_naming_auth_once():
    lines = foundry.retry_ladder_lines()
    assert len(lines) == 3, "expected 3 rendered ladder lines, got %r" % (lines,)
    naming_auth = [ln for ln in lines if AUTH in ln]
    assert len(naming_auth) == 1, "expected exactly one line naming auth, got %r" % (naming_auth,)
    fast = naming_auth[0]
    for kind in ("timeout", "cli-error", AUTH):
        assert kind in fast, "fast line %r must name %r" % (fast, kind)
    assert fast.startswith("timeout, cli-error, %s:" % AUTH), (
        "auth must MERGE onto the existing fast line, got %r" % (fast,))
    assert "1 -> 2 -> 4 min" in fast


@pytest.mark.parametrize("doc_path", DOC_PATHS, ids=lambda p: p.name)
def test_b6_both_shipped_docs_carry_the_rendered_fast_line(doc_path):
    fast = [ln for ln in foundry.retry_ladder_lines() if AUTH in ln][0]
    text = _normalize_arrows(doc_path.read_text())
    assert _normalize_arrows(fast) in text, (
        "%s does not carry the rendered fast ladder line %r" % (doc_path.name, fast))


# ===========================================================================
# Behavior 7 -- two-sided, so the check cannot be vacuous
# ===========================================================================
@pytest.mark.parametrize("name,blob,length", REAL_AUTH_BLOBS)
def test_b7_removing_the_auth_entry_restores_the_pre_196_verdict(monkeypatch, name, blob, length):
    monkeypatch.setattr(foundry, "ATTEMPT_FAILURE_MARKERS", _entries_without_auth())
    assert foundry.classify_attempt_failure(blob) == PRE_196_VERDICTS[name], (
        "with the auth entry removed, %r must fall back to %r"
        % (name, PRE_196_VERDICTS[name]))


def test_b7_the_table_is_read_at_call_time_not_captured_at_import(monkeypatch):
    monkeypatch.setattr(foundry, "ATTEMPT_FAILURE_MARKERS", _entries_without_auth())
    assert foundry.classify_attempt_failure(AUTH_BLOB_TIMED_OUT) == "timeout"
    monkeypatch.undo()
    assert foundry.classify_attempt_failure(AUTH_BLOB_TIMED_OUT) == AUTH


@pytest.mark.parametrize("blob,expected", [
    ("agent run timed out after 600s", "timeout"),
    ("agent run failed: service is busy, try again later", "service"),
    ("Connection stalled - no data received for 120 s", "stalled"),
    ("native shortcut did not match any known verb", "cli-error"),
    ("something nobody has a needle for", foundry.ATTEMPT_FAILURE_DEFAULT),
])
def test_b7_a_blob_with_no_auth_wording_classifies_exactly_as_it_does_today(
        monkeypatch, blob, expected):
    assert AUTH_NEEDLE not in blob.lower()
    assert foundry.classify_attempt_failure(blob) == expected
    # ...and removing the new entry cannot change any of them.
    monkeypatch.setattr(foundry, "ATTEMPT_FAILURE_MARKERS", _entries_without_auth())
    assert foundry.classify_attempt_failure(blob) == expected


# ===========================================================================
# Behavior 8 -- totality is preserved on the retry path
# ===========================================================================
@pytest.mark.parametrize("blob", ["", None])
def test_b8_empty_and_none_still_return_the_default_kind(blob):
    assert foundry.classify_attempt_failure(blob) == foundry.ATTEMPT_FAILURE_DEFAULT


def test_b8_classification_does_no_file_io(monkeypatch):
    def _no_open(*a, **k):
        raise AssertionError("classify_attempt_failure must be pure -- it opened a file")
    monkeypatch.setattr(builtins, "open", _no_open)
    assert foundry.classify_attempt_failure(AUTH_BLOB_TIMED_OUT) == AUTH
    assert foundry.classify_attempt_failure("") == foundry.ATTEMPT_FAILURE_DEFAULT


def test_b8_it_still_raises_with_no_input():
    with pytest.raises(TypeError):
        foundry.classify_attempt_failure()


# ===========================================================================
# Acceptance guard A -- exactly one entry added, the other four untouched
# ===========================================================================
def test_a_the_marker_table_gained_exactly_one_entry_and_kept_the_other_four():
    table = tuple((kind, tuple(needles)) for kind, needles in foundry.ATTEMPT_FAILURE_MARKERS)
    assert len(table) == len(PRE_196_ENTRIES) + 1
    assert tuple(e for e in table if e[0] != AUTH) == PRE_196_ENTRIES
    # Relaxed by iteration 226: the agent CLI changed its wording, so the `auth`
    # entry now also carries `auth failed`. Iteration 196's real claim was that
    # ITS measured needle is present and classifies `auth` (b1/b2 above), never
    # that no later measurement may add a second one.
    assert AUTH_NEEDLE in dict(table)[AUTH], (
        "the entry must still carry iteration 196's measured needle, got %r"
        % (dict(table)[AUTH],))


# ===========================================================================
# Acceptance guard B -- this iteration's roadmap record ships in THIS diff
# ===========================================================================
def test_b_the_ledger_row_and_archive_bullet_exist_exactly_once():
    rows = _lines_with(LEDGER_ROW_PREFIX, INDEX_PATH.read_text())
    assert len(rows) == 1, "expected exactly one %r row, got %d" % (LEDGER_ROW_PREFIX, len(rows))
    assert len(rows[0]) <= LEDGER_ROW_MAX_CHARS, (
        "ledger row is %d chars, over the %d limit: %r"
        % (len(rows[0]), LEDGER_ROW_MAX_CHARS, rows[0]))
    bullets = _lines_with(ARCHIVE_BULLET_PREFIX, ARCHIVE_PATH.read_text())
    assert len(bullets) == 1, (
        "expected exactly one %r bullet, got %d" % (ARCHIVE_BULLET_PREFIX, len(bullets)))


def test_b_the_roadmap_record_check_is_green_and_two_sided():
    index_text = INDEX_PATH.read_text()
    archive_text = ARCHIVE_PATH.read_text()
    assert foundry.roadmap_ledger_gaps(index_text, archive_text, (THIS_ITER,)) == []
    stripped_index = "\n".join(
        ln for ln in index_text.splitlines() if not ln.startswith(LEDGER_ROW_PREFIX))
    stripped_archive = "\n".join(
        ln for ln in archive_text.splitlines() if not ln.startswith(ARCHIVE_BULLET_PREFIX))
    # Two-sided: with the record gone from BOTH tracked files the same call reports the gap,
    # so the green verdict above is evidence about the record and not a vacuous pass.
    assert foundry.roadmap_ledger_gaps(
        stripped_index, stripped_archive, (THIS_ITER,)) == [THIS_ITER]
    # MEASURED CONTRACT of the oracle, so no reader mistakes it for a per-file check: it is an
    # OR over the two files -- either record alone satisfies it.  "Both files carry the record",
    # which the Acceptance Criteria actually requires, is pinned by the per-file counts above.
    assert foundry.roadmap_ledger_gaps(stripped_index, archive_text, (THIS_ITER,)) == []
    assert foundry.roadmap_ledger_gaps(index_text, stripped_archive, (THIS_ITER,)) == []


def test_b_the_index_stays_inside_its_budget_with_the_row_in_place():
    budget = foundry.roadmap_index_budget(INDEX_PATH.read_text())
    assert budget.over_budget is False
    assert budget.near_wall is False
    assert budget.headroom >= INDEX_HEADROOM_FLOOR, (
        "index headroom is %d, under the %d floor" % (budget.headroom, INDEX_HEADROOM_FLOOR))


# ===========================================================================
# Acceptance guard C -- both modules still import in a FRESH interpreter
# ===========================================================================
def test_c_both_modules_import_in_a_fresh_interpreter():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher; print('ok')"],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, "fresh import failed:\n%s\n%s" % (proc.stdout, proc.stderr)
    assert "ok" in proc.stdout
