"""Behaviour tests for iter 135 -- a per-kind retry ladder map (`KIND_RETRY_LADDERS`).

Spec: products/_platform/state/iter-135/pm.md, Expected Behaviors 1-13.

BLACK BOX. Written under the tester isolation contract: the only inputs were the
spec, the repo README/roadmap and everything under `tests/`. The implementation
source was NOT read, no `git diff` was read, and neither the engineer's nor the
reviewer's notes were read. Every assertion is stated in SPEC terms and observed
at RUNTIME by driving the public interface (`foundry.KIND_RETRY_LADDERS`,
`foundry.retry_delay`, `foundry.run_stage`) -- no real agent subprocess, socket,
git, network or sleep, and nothing written outside `tmp_path`.

  retry_delay pricing (pure)
  1.  `KIND_RETRY_LADDERS` is a module-level dict whose keys are exactly
      {"stalled"}, mapped to the measured ladder [60, 300, 1200].
  2.  the stalled ladder is USED: retry_delay("stalled", 1..3) -> 60/300/1200.
  3.  beyond the ladder clamps to the LAST entry (1200), like every other kind.
  4.  a bogus attempt number is total and returns the FIRST entry (60), never the
      longest wait -- the opposite of "retry sooner".
  5.  every other kind is byte-identical to iteration 129, and the three frozen
      constants keep their literal values.
  6.  the map takes PRECEDENCE over FAST_RETRY_KINDS.
  7.  the map is read from the module global AT CALL TIME by bare name, in BOTH
      directions: a new key is honoured, and emptying the map restores iteration
      129's 600s exactly (so the change is one dict entry away from undone).
  8.  fall-through is unchanged for kinds the map does not name.
  9.  TOTALITY: an explicit-but-EMPTY mapped ladder returns RETRY_DELAY_FLOOR and
      does NOT fall through to BACKOFFS -- 60, not 600.
  10. RETRY_DELAY_FLOOR clamps a mapped ladder too.
  run_stage wiring, driven fully offline
  11. a stalled failure with no output file sleeps [60, 300, 1200] (was
      [600, 1200, 2400]); a service failure still sleeps [600, 1200, 2400].
  12. the decision stays observable: each backoff line still says `backing off`,
      still classifies as the "backoff" event kind, still names
      `failure kind: stalled`, and reports whole minutes 1 / 5 / 20.
  13. the two iteration-129 assertions that pinned `stalled` to the long ladder
      are NARROWED, never deleted: both function names survive, both docstrings
      record the iteration-135 reversal, STALLED_BLOB still exists and still
      drives the CLASSIFICATION behaviours, and what each test was really about
      (an unknown kind / a busy backend keeping the long ladder) still holds.
"""
import importlib.util
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)

_ROOT = pathlib.Path(foundry.__file__).resolve().parent
THIS_TEST = pathlib.Path(__file__).resolve()
_TESTS = THIS_TEST.parent
_ITER129 = _TESTS / "test_iter129_behavior.py"
_LEAK_GUARD = _ROOT / "scripts" / "leak_guard.py"
_DENYLIST = _ROOT / "scripts" / "leak_denylist.txt"

# The measured ladder this iteration ships, and the ladder it replaces.
STALLED_LADDER = [60, 300, 1200]
LONG_LADDER = [600, 1200, 2400]
FAST_LADDER = [60, 120, 240]

# The measured stall shape, identical to the string iteration 129 clustered from
# the live dispatcher log. Deliberately generic -- this repo is public.
STALLED_BLOB = "Connection stalled -- no data received for 120 s"
SERVICE_BLOB = "upstream internal error ... The service is busy"


def _load_by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# Behaviours 11/12 reuse the OFFLINE `_drive` harness that already exists in the
# iteration-129 behaviour file (per the spec's test-cost note) rather than
# cloning 60 lines of fake subprocess/sleep plumbing. Loaded by explicit path so
# this file does not depend on pytest's sys.path insertion order.
_i129 = _load_by_path("iter129_harness_for_135", _ITER129)
_drive = _i129._drive
_backoff_lines = _i129._backoff_lines


def _parametrize_values(fn, argname):
    """The values a pytest.mark.parametrize applies to `fn` for `argname`.

    Runtime introspection of the mark, so behaviour 13 is checked against what
    pytest will actually run rather than against the file's source text."""
    for mark in getattr(fn, "pytestmark", []):
        if mark.name != "parametrize":
            continue
        names = [n.strip() for n in mark.args[0].split(",")]
        if argname not in names:
            continue
        idx = names.index(argname)
        out = []
        for row in mark.args[1]:
            out.append(row[idx] if len(names) > 1 else row)
        return out
    raise AssertionError(
        "%s has no parametrize over %r (marks: %r)"
        % (fn.__name__, argname, [m.name for m in getattr(fn, "pytestmark", [])]))


# ==========================================================================
# Behavior 1 -- the map exists and is minimal
# ==========================================================================
def test_b1_map_exists_and_is_minimal():
    """One key only: `timeout`/`cli-error` already have a measured fast ladder and
    `service` must keep the long one, so a second entry would be out of scope."""
    assert isinstance(foundry.KIND_RETRY_LADDERS, dict)
    assert set(foundry.KIND_RETRY_LADDERS) == {"stalled"}
    assert foundry.KIND_RETRY_LADDERS["stalled"] == STALLED_LADDER


# ==========================================================================
# Behavior 2 -- the stalled ladder is actually used
# ==========================================================================
def test_b2_stalled_kind_draws_from_its_own_ladder():
    assert [foundry.retry_delay("stalled", n) for n in (1, 2, 3)] == STALLED_LADDER


def test_b2_the_first_stalled_retry_is_no_longer_a_ten_minute_sleep():
    """The whole point of the iteration: retry 1 is cheap. Stated as a REGRESSION
    guard so a silent revert to iteration 129's pricing cannot pass quietly."""
    assert foundry.retry_delay("stalled", 1) == 60
    assert foundry.retry_delay("stalled", 1) != LONG_LADDER[0]


def test_b2_but_attempts_three_and_four_are_still_deliberately_slow():
    """The spec declines the faster [60, 120, 240] on purpose: attempt 3 must
    still wait 20 minutes so a stall that is really a network/system-sleep event
    is still given real time before the final attempt."""
    assert foundry.retry_delay("stalled", 3) == 1200
    assert foundry.retry_delay("stalled", 3) > FAST_LADDER[-1]


# ==========================================================================
# Behavior 3 -- beyond the ladder clamps to the LAST entry
# ==========================================================================
@pytest.mark.parametrize("beyond", [4, 5, 99])
def test_b3_beyond_the_ladder_clamps_to_the_last_entry(beyond):
    assert foundry.retry_delay("stalled", beyond) == 1200


# ==========================================================================
# Behavior 4 -- a bogus attempt is total and never the longest wait
# ==========================================================================
@pytest.mark.parametrize("bogus", [0, -1, -99])
def test_b4_a_bogus_attempt_is_total_and_never_the_longest_wait(bogus):
    """A negative index must not wrap backwards into the 20-minute entry."""
    assert foundry.retry_delay("stalled", bogus) == 60


# ==========================================================================
# Behavior 5 -- every other kind is byte-identical to today
# ==========================================================================
@pytest.mark.parametrize("kind", ["timeout", "cli-error"])
def test_b5_the_fast_kinds_are_untouched(kind):
    assert [foundry.retry_delay(kind, n) for n in (1, 2, 3)] == FAST_LADDER


@pytest.mark.parametrize("kind", ["service", "other", "brand-new-kind-nobody-ships"])
def test_b5_the_long_ladder_kinds_are_untouched(kind):
    """`service` is the one failure where a long sleep is CORRECT, and an unknown
    kind must keep degrading to a long sleep, never to a hot loop."""
    assert [foundry.retry_delay(kind, n) for n in (1, 2, 3)] == LONG_LADDER


def test_b5_the_three_frozen_constants_keep_their_literal_values():
    assert set(foundry.FAST_RETRY_KINDS) == {"timeout", "cli-error"}
    assert foundry.BACKOFFS == LONG_LADDER
    assert foundry.TIMEOUT_BACKOFFS == FAST_LADDER
    assert foundry.RETRY_DELAY_FLOOR == 60
    # resume-semantics guard: the attempt/cooldown ladders are out of scope
    assert foundry.MAX_ATTEMPTS == 4
    assert foundry.COOLDOWNS == [1800, 3600, 7200, 14400]


def test_b5_stalled_was_not_moved_into_the_fast_kind_set():
    """Explicitly forbidden by the roadmap's requested shape -- the ladder must
    come from the MAP, not from membership of FAST_RETRY_KINDS."""
    assert "stalled" not in set(foundry.FAST_RETRY_KINDS)


# ==========================================================================
# Behavior 6 -- the map takes PRECEDENCE over FAST_RETRY_KINDS
# ==========================================================================
def test_b6_the_map_wins_over_the_fast_kind_set(monkeypatch):
    monkeypatch.setattr(foundry, "KIND_RETRY_LADDERS", {"timeout": [900, 1000]})
    assert "timeout" in set(foundry.FAST_RETRY_KINDS), "premise of the test"
    assert foundry.retry_delay("timeout", 1) == 900
    assert foundry.retry_delay("timeout", 2) == 1000


# ==========================================================================
# Behavior 7 -- read from the module global AT CALL TIME, by bare name
# ==========================================================================
def test_b7a_a_monkeypatched_new_key_is_honoured(monkeypatch):
    monkeypatch.setattr(foundry, "KIND_RETRY_LADDERS", {"invented-kind": [700]})
    assert foundry.retry_delay("invented-kind", 1) == 700


def test_b7b_emptying_the_map_restores_iteration_129_behaviour_exactly(monkeypatch):
    """The revert proof: one dict entry away from the old pricing. If this fails
    the ladder was hard-coded into the branch instead of being data."""
    monkeypatch.setattr(foundry, "KIND_RETRY_LADDERS", {})
    assert [foundry.retry_delay("stalled", n) for n in (1, 2, 3)] == LONG_LADDER


def test_b7_the_map_is_not_captured_as_a_def_time_default():
    """A `def retry_delay(kind, attempt, ladders=KIND_RETRY_LADDERS)` shape would
    freeze the map at import time and make 7a/7b vacuous."""
    fn = foundry.retry_delay
    frozen = [d for d in (fn.__defaults__ or ()) if isinstance(d, dict)]
    assert frozen == [], (
        "retry_delay captures a dict default (%r) -- the map must be read from the "
        "module global inside the body" % (frozen,))
    assert "KIND_RETRY_LADDERS" in _i129._co_names_deep(fn), (
        "retry_delay must reference KIND_RETRY_LADDERS by BARE module name so a "
        "monkeypatch bites")


# ==========================================================================
# Behavior 8 -- fall-through is unchanged for kinds the map does not name
# ==========================================================================
def test_b8_an_unmapped_kind_still_consults_the_default_ladder(monkeypatch):
    monkeypatch.setattr(foundry, "KIND_RETRY_LADDERS", {"stalled": [60]})
    monkeypatch.setattr(foundry, "BACKOFFS", [11111])
    assert foundry.retry_delay("service", 1) == 11111


def test_b8_an_unmapped_fast_kind_still_consults_the_fast_ladder(monkeypatch):
    """Two-sided partner: the map must shadow neither branch of the old choice."""
    monkeypatch.setattr(foundry, "KIND_RETRY_LADDERS", {"stalled": [60]})
    monkeypatch.setattr(foundry, "TIMEOUT_BACKOFFS", [222, 333])
    assert [foundry.retry_delay("timeout", n) for n in (1, 2)] == [222, 333]


# ==========================================================================
# Behavior 9 -- an EMPTY mapped ladder returns the floor, and does NOT fall through
# ==========================================================================
@pytest.mark.parametrize("attempt", [1, 9])
def test_b9_an_explicit_but_empty_mapped_ladder_returns_the_floor(monkeypatch, attempt):
    """`[]` is falsy, so the tempting `MAP.get(kind) or <old choice>` one-liner
    would silently return 600 here. An explicit-but-empty entry is NOT the same
    as an absent one: it must be the floor, and it must not raise."""
    monkeypatch.setattr(foundry, "KIND_RETRY_LADDERS", {"stalled": []})
    got = foundry.retry_delay("stalled", attempt)
    assert got == foundry.RETRY_DELAY_FLOOR == 60
    assert got != LONG_LADDER[0], (
        "an empty mapped ladder fell through to BACKOFFS -- the spec forbids it")


# ==========================================================================
# Behavior 10 -- the floor clamps a mapped ladder too
# ==========================================================================
def test_b10_the_floor_clamps_a_mapped_ladder(monkeypatch):
    monkeypatch.setattr(foundry, "KIND_RETRY_LADDERS", {"stalled": [1, 2, 5]})
    assert [foundry.retry_delay("stalled", n) for n in (1, 2, 3)] == [60, 60, 60]


def test_b10_the_floor_is_read_at_call_time_on_the_mapped_path(monkeypatch):
    """Otherwise behaviour 10 could be satisfied by a hard-coded `max(x, 60)`."""
    monkeypatch.setattr(foundry, "KIND_RETRY_LADDERS", {"stalled": [1, 2, 5]})
    monkeypatch.setattr(foundry, "RETRY_DELAY_FLOOR", 1)
    assert [foundry.retry_delay("stalled", n) for n in (1, 2, 3)] == [1, 2, 5]


# ==========================================================================
# Behavior 11 -- run_stage wiring, fully offline
# ==========================================================================
def test_b11_a_stalled_stage_sleeps_the_new_ladder_end_to_end(monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path, STALLED_BLOB)
    assert d.ok is False
    assert d.sleeps == STALLED_LADDER, (
        "a stalled attempt must sleep 60/300/1200 end-to-end (was 600/1200/2400); "
        "got %r" % (d.sleeps,))
    assert len(d.calls) == foundry.MAX_ATTEMPTS, "the attempt count is out of scope"


def test_b11_a_service_stage_still_sleeps_the_long_ladder_end_to_end(
        monkeypatch, tmp_path):
    """The control that makes the assertion above mean something: the SAME harness
    with a different failure text must be byte-identical to iteration 129."""
    d = _drive(monkeypatch, tmp_path, SERVICE_BLOB)
    assert d.sleeps == LONG_LADDER, (
        "a busy backend is the one failure where a long sleep is correct; got %r"
        % (d.sleeps,))


def test_b11_control_a_neutered_classifier_puts_a_stall_back_on_the_long_ladder(
        monkeypatch, tmp_path):
    """Proves the new delay is wired to the classified DECISION and not to the
    attempt index: with the classifier neutered the same blob must sleep long."""
    monkeypatch.setattr(foundry, "classify_attempt_failure", lambda _blob: "other")
    d = _drive(monkeypatch, tmp_path, STALLED_BLOB)
    assert d.sleeps == LONG_LADDER, (
        "with the classifier neutered a stall must fall back to the long ladder; "
        "got %r -- if it stays 60/300/1200 behaviour 11 is vacuous" % (d.sleeps,))


def test_b11_control_emptying_the_map_restores_the_old_sleeps_end_to_end(
        monkeypatch, tmp_path):
    """Behaviour 7b at the run_stage level: the revert is one dict entry."""
    monkeypatch.setattr(foundry, "KIND_RETRY_LADDERS", {})
    d = _drive(monkeypatch, tmp_path, STALLED_BLOB)
    assert d.sleeps == LONG_LADDER


# ==========================================================================
# Behavior 12 -- the decision stays observable in the log
# ==========================================================================
def test_b12_each_backoff_line_still_classifies_as_backoff_and_names_the_kind(
        monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path, STALLED_BLOB)
    lines = _backoff_lines(d)
    assert len(lines) == foundry.MAX_ATTEMPTS - 1, (
        "expected one backoff line per non-final attempt, got %r" % (lines,))
    for ln in lines:
        assert "backing off" in ln
        assert foundry.classify_event(ln) == "backoff", (
            "the event-kind rules must still stamp this line `backoff`: %r" % ln)
        assert "failure kind: stalled" in ln, (
            "the backoff line must still name the classified kind: %r" % ln)


def test_b12_the_three_lines_report_whole_minutes_one_five_and_twenty(
        monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path, STALLED_BLOB)
    lines = _backoff_lines(d)
    assert len(lines) == 3
    assert "backing off 1 min" in lines[0], lines[0]
    assert "backing off 5 min" in lines[1], lines[1]
    assert "backing off 20 min" in lines[2], lines[2]


# ==========================================================================
# Behavior 13 -- the iteration-129 assertions are NARROWED, never deleted
# ==========================================================================
def test_b13a_the_iter129_long_ladder_test_dropped_only_stalled():
    fn = getattr(_i129, "test_b8_every_other_kind_including_an_unknown_one_keeps_the_long_ladder")
    kinds = _parametrize_values(fn, "kind")
    assert "stalled" not in kinds, (
        "iteration 129 pinned `stalled` to the long ladder; iteration 135 must "
        "narrow that parametrize, got %r" % (kinds,))
    for survivor in ("other", "brand-new-kind-nobody-ships"):
        assert survivor in kinds, (
            "%r must SURVIVE the narrowing -- an unknown kind keeping the long "
            "ladder is what that test is really about; got %r" % (survivor, kinds))


def test_b13b_the_iter129_end_to_end_test_dropped_only_the_stalled_blob():
    fn = getattr(_i129, "test_b13_wait_helps_kinds_keep_todays_backoff_end_to_end")
    blobs = _parametrize_values(fn, "blob")
    assert _i129.STALLED_BLOB not in blobs, (
        "the stalled blob no longer sleeps the long ladder end-to-end; got %r"
        % (blobs,))
    for survivor in (_i129.SERVICE_BLOB, _i129.UNMATCHED_BLOB, ""):
        assert survivor in blobs, (
            "%r must SURVIVE the narrowing; got %r" % (survivor, blobs))


def test_b13_the_stalled_blob_constant_still_exists_and_still_drives_classification():
    """Deleting STALLED_BLOB would have been the cheapest green, and it would have
    silently dropped the CLASSIFICATION coverage that iteration 135 does not touch."""
    assert _i129.STALLED_BLOB == STALLED_BLOB
    assert foundry.classify_attempt_failure(_i129.STALLED_BLOB) == "stalled"
    still_using = [
        _parametrize_values(_i129.test_b6_long_ladder_marker_beats_a_timeout_marker_in_both_orders, "long_blob"),
        _parametrize_values(_i129.test_b7_classification_is_case_insensitive, "blob"),
        _parametrize_values(_i129.test_b14_backoff_line_still_classifies_as_backoff_and_names_the_kind, "blob"),
    ]
    for values in still_using:
        assert _i129.STALLED_BLOB in values, (
            "a classification behaviour stopped exercising STALLED_BLOB: %r" % (values,))


def test_b13_both_narrowed_tests_document_the_iteration_135_reversal():
    """A narrowing without a recorded reason reads as a weakened suite later."""
    for name in ("test_b8_every_other_kind_including_an_unknown_one_keeps_the_long_ladder",
                 "test_b13_wait_helps_kinds_keep_todays_backoff_end_to_end"):
        doc = (getattr(_i129, name).__doc__ or "")
        assert "135" in doc, "%s docstring must record the reversal: %r" % (name, doc)
    header = _i129.__doc__ or ""
    assert header.count("iter 135") >= 2, (
        "the file header's behaviour-8 and behaviour-13 lines must both record "
        "that iteration 135 reversed iteration 129's deferral")


# ==========================================================================
# Acceptance criteria -- import safety and public safety
# ==========================================================================
def test_ac_both_modules_still_import():
    assert foundry.__file__ and dispatcher.__file__


def test_ac_this_test_file_scans_clean_under_the_committed_denylist():
    if not (_LEAK_GUARD.exists() and _DENYLIST.exists()):
        pytest.skip("leak-guard not present in this repo (repo-agnostic)")
    lg = _load_by_path("leak_guard_iter135_probe", _LEAK_GUARD)
    patterns = lg.load_denylist(_DENYLIST.read_text())
    home_prefix = "/" + "Users" + "/"  # built at runtime; never a source literal
    # two-sided: prove the matcher is LIVE before trusting a clean result
    assert len(lg.scan_text(home_prefix + "somebody/x", patterns)) >= 1, \
        "denylist appears inert (a home-path probe did not match)"
    txt = THIS_TEST.read_text()
    assert len(lg.scan_text(txt, patterns)) == 0, \
        "this test file contains a denylisted token (would BLOCK the ship)"
    assert home_prefix not in txt, \
        "this test file contains an absolute home-directory path"
