"""Behaviour tests for iter 129 -- failure-kind-aware retry delay in run_stage.

Spec: products/_platform/state/iter-129/pm.md, Expected Behaviors 1-15.

  classify_attempt_failure(blob) -> kind
  1.  a `timed out` blob -> "timeout", covering BOTH measured shapes (the agent
      CLI's own kill message and run_stage's internal `(stage attempt timed out)`).
  2.  `native shortcut did not match` -> "cli-error".
  3.  `service is busy` / `too many tokens` / `throttl` -> "service".
  4.  `connection stalled` -> "stalled".
  5.  empty string and any unmatched blob -> "other".
  6.  precedence is CONSERVATIVE-FIRST and order-insensitive: service or stalled
      markers beat a timeout marker in EITHER concatenation order.
  7.  classification is case-insensitive.
  retry_delay(kind, attempt) -> int
  8.  FAST_RETRY_KINDS draw from TIMEOUT_BACKOFFS; every other kind, including an
      unknown one, draws from BACKOFFS (so "service" stays 600/1200/2400).
  9.  attempt 1/2/3 -> ladder index 0/1/2; beyond the ladder clamps to the LAST
      entry (the same clamp the old inline call site performed).
  10. never below RETRY_DELAY_FLOOR, and an EMPTY ladder returns that floor
      instead of raising IndexError.
  11. every constant is read from module globals AT CALL TIME (a monkeypatch
      bites), and run_stage references both new functions BY BARE NAME.
  run_stage wiring, driven offline
  12. a cap-timeout blob with no output file sleeps 60/120/240 (was 600/1200/2400).
  13. a `service is busy` blob still sleeps 600/1200/2400, byte-identical to before.
  14. the backoff log line still carries `backing off` (so the event-kind rules
      still stamp it "backoff") and now also NAMES the classified kind.
  15. unchanged: attempt count == MAX_ATTEMPTS; STOP short-circuits; a truthy
      sleep_interruptible abandons the stage; attempt 1's argv is byte-identical;
      BACKOFFS / MAX_ATTEMPTS / COOLDOWNS keep their literal values.

PROVENANCE (stated plainly rather than claiming an isolation this file does not
have): behaviours 1-15 above are the PM spec's, and Behaviors 1 and 8 were
written by the tester stage under its isolation contract. The remaining
behaviours were added by the FIX pass, which DID read the iteration's diff, so
this file's coverage claim is not an independent-derivation claim. Every
assertion is still stated in SPEC terms and observed at RUNTIME: run_stage is
driven as a black box with build_prompt / subprocess.run / stopping /
sleep_interruptible / resolve_agent_endpoint monkeypatched -- no real agent
subprocess, socket, git, network or sleep, and nothing written outside tmp_path.
The only introspection used is the compiled-name table (the iter-107 convention)
and inspect.getsource of the two NEW functions for the public-safety scan; no
assertion reads control-path source text.
"""
import importlib.util
import inspect
import json
import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)

_ROOT = pathlib.Path(foundry.__file__).resolve().parent
THIS_TEST = pathlib.Path(__file__).resolve()
_LEAK_GUARD = _ROOT / "scripts" / "leak_guard.py"
_DENYLIST = _ROOT / "scripts" / "leak_denylist.txt"

ITERATION = 129
SENTINEL = "SENTINEL-PROMPT-129"

# The four MEASURED failure shapes from the spec's clustering of the live
# dispatcher log. Deliberately generic: the model-vendor name that appears in the
# real service tails is on the committed denylist (this repo is public), and the
# spec proved `service is busy` alone was present in all 10 service failures.
CAP_TIMEOUT_BLOB = "agent run failed: agent run timed out after 600s"
INTERNAL_TIMEOUT_BLOB = "(stage attempt timed out)"
CLI_ERROR_BLOB = "the native shortcut did not match -- check syntax"
SERVICE_BLOB = "upstream internal error ... The service is busy"
STALLED_BLOB = "Connection stalled -- no data received for 120 s"
UNMATCHED_BLOB = "stage wrote nothing and said nothing useful"


# --------------------------------------------------------------------------
# helpers (pure runtime introspection -- never a read of control-path source)
# --------------------------------------------------------------------------
def _co_names_deep(fn):
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _load_leak_guard():
    spec = importlib.util.spec_from_file_location(
        "leak_guard_iter129_probe", _LEAK_GUARD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# offline run_stage drive harness
# --------------------------------------------------------------------------
class _FakeCP:
    """Stand-in for subprocess.CompletedProcess: only the attributes run_stage
    reads (.returncode / .stdout / .stderr)."""

    def __init__(self, rc=1, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def _make_cfg(tmp_path):
    """Minimal product config in a tmp dir; repo + work_root are TMP so the live
    foundry repo and products/ tree are NEVER touched."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (tmp_path / "VISION.md").write_text("vision\n")
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return foundry.load_config(str(p))


def _role_file(tmp_path):
    r = tmp_path / "role.md"
    r.write_text("do the thing\n")
    return str(r)


def _drive(monkeypatch, tmp_path, blob, stop=False, sleep_ret=False,
           prompt=SENTINEL):
    """Drive run_stage against a stage that NEVER writes its output file, so the
    full retry loop runs. Returns the recorded argv calls, backoff sleeps and
    NIGHT_LOG lines. Nothing real is spawned and nothing really sleeps."""
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    monkeypatch.setattr(foundry, "build_prompt", lambda *a, **k: prompt)
    monkeypatch.setattr(foundry, "stopping", lambda _cfg: stop)
    monkeypatch.setattr(foundry, "resolve_agent_endpoint", lambda *a, **k: None)

    sleeps = []

    def fake_sleep(_cfg, seconds):
        sleeps.append(seconds)
        return sleep_ret

    monkeypatch.setattr(foundry, "sleep_interruptible", fake_sleep)

    calls = []

    def fake_run(*a, **k):
        calls.append((a, dict(k)))
        return _FakeCP(out=blob)

    monkeypatch.setattr(foundry.subprocess, "run", fake_run)
    ok, out = foundry.run_stage(cfg, ITERATION, "engineer", role, "engineer.md")
    lines = (cfg.night_log.read_text().splitlines()
             if cfg.night_log.exists() else [])
    return types.SimpleNamespace(ok=ok, out=out, calls=calls, sleeps=sleeps,
                                 log_lines=lines, cfg=cfg)


def _argv(call):
    args = call[0]
    assert args, "subprocess.run was called with no positional argv"
    argv = args[0]
    assert isinstance(argv, (list, tuple)), "argv is not a list/tuple: %r" % (argv,)
    return list(argv)


def _backoff_lines(drive):
    return [ln for ln in drive.log_lines if "backing off" in ln]


# ==========================================================================
# Behavior 1 -- a `timed out` blob classifies as "timeout" (both shapes)
# ==========================================================================
def test_b1_cap_timeout_blob_classifies_as_timeout():
    assert foundry.classify_attempt_failure(
        "agent run failed: agent run timed out after 600s"
    ) == "timeout"


def test_b1_internal_timeout_sentinel_also_classifies_as_timeout():
    """run_stage's own `except subprocess.TimeoutExpired` writes this blob, so it
    must price the same as the CLI's kill message."""
    assert foundry.classify_attempt_failure(INTERNAL_TIMEOUT_BLOB) == "timeout"


# ==========================================================================
# Behavior 2 -- the dead-endpoint CLI help text classifies as "cli-error"
# ==========================================================================
def test_b2_cli_help_text_classifies_as_cli_error():
    assert foundry.classify_attempt_failure(CLI_ERROR_BLOB) == "cli-error"


# ==========================================================================
# Behavior 3 -- the three rate-limit markers classify as "service"
# ==========================================================================
@pytest.mark.parametrize("blob", [
    SERVICE_BLOB,
    "request rejected: too many tokens, please wait",
    "throttling exception raised upstream",
])
def test_b3_rate_limit_markers_classify_as_service(blob):
    assert foundry.classify_attempt_failure(blob) == "service"


# ==========================================================================
# Behavior 4 -- a stream stall classifies as "stalled"
# ==========================================================================
def test_b4_stream_stall_classifies_as_stalled():
    assert foundry.classify_attempt_failure(STALLED_BLOB) == "stalled"


# ==========================================================================
# Behavior 5 -- empty and unmatched blobs classify as "other"
# ==========================================================================
@pytest.mark.parametrize("blob", ["", UNMATCHED_BLOB, "   \n\t "])
def test_b5_no_evidence_classifies_as_other(blob):
    assert foundry.classify_attempt_failure(blob) == "other"


def test_b5_classifier_is_total_and_never_raises():
    """It runs on the failure path, where an exception would abandon the stage."""
    for blob in (None, "", "x" * 50000, "\x00\x01", UNMATCHED_BLOB):
        assert isinstance(foundry.classify_attempt_failure(blob), str)


# ==========================================================================
# Behavior 6 -- CONSERVATIVE-FIRST precedence, in either textual order
# ==========================================================================
@pytest.mark.parametrize("long_blob,expected", [
    (SERVICE_BLOB, "service"),
    (STALLED_BLOB, "stalled"),
])
def test_b6_long_ladder_marker_beats_a_timeout_marker_in_both_orders(
        long_blob, expected):
    """Mis-pricing a struggling backend as a cap timeout is the one error that
    could hammer a service, so ambiguity must always land on the LONG ladder --
    and must not depend on which marker the log happened to print first."""
    assert foundry.classify_attempt_failure(
        long_blob + " " + CAP_TIMEOUT_BLOB) == expected
    assert foundry.classify_attempt_failure(
        CAP_TIMEOUT_BLOB + " " + long_blob) == expected


def test_b6_two_long_ladder_markers_are_deterministic_either_way():
    a = foundry.classify_attempt_failure(SERVICE_BLOB + " " + STALLED_BLOB)
    b = foundry.classify_attempt_failure(STALLED_BLOB + " " + SERVICE_BLOB)
    assert a == b == "service"


# ==========================================================================
# Behavior 7 -- classification is case-insensitive
# ==========================================================================
@pytest.mark.parametrize("blob,expected", [
    (CAP_TIMEOUT_BLOB, "timeout"),
    (INTERNAL_TIMEOUT_BLOB, "timeout"),
    (CLI_ERROR_BLOB, "cli-error"),
    (SERVICE_BLOB, "service"),
    (STALLED_BLOB, "stalled"),
])
def test_b7_classification_is_case_insensitive(blob, expected):
    assert foundry.classify_attempt_failure(blob.upper()) == expected
    assert foundry.classify_attempt_failure(blob.lower()) == expected


# ==========================================================================
# Behavior 8 -- fast ladder for FAST_RETRY_KINDS, BACKOFFS for everything else
# ==========================================================================
def test_b8_timeout_kind_draws_from_the_fast_ladder():
    assert [foundry.retry_delay("timeout", n) for n in (1, 2, 3)] == [60, 120, 240]
    assert [foundry.retry_delay("service", n) for n in (1, 2, 3)] == [600, 1200, 2400]


def test_b8_cli_error_is_the_other_fast_kind():
    assert [foundry.retry_delay("cli-error", n) for n in (1, 2, 3)] == [60, 120, 240]
    assert set(foundry.FAST_RETRY_KINDS) == {"timeout", "cli-error"}


@pytest.mark.parametrize("kind", ["stalled", "other", "brand-new-kind-nobody-ships"])
def test_b8_every_other_kind_including_an_unknown_one_keeps_the_long_ladder(kind):
    """The DEFAULT is today's behaviour, so a classifier that stops recognising a
    marker degrades to a long sleep, never to a hot loop against a sick backend.
    `stalled` staying here is the spec's explicit out-of-scope decision."""
    assert [foundry.retry_delay(kind, n) for n in (1, 2, 3)] == [600, 1200, 2400]


# ==========================================================================
# Behavior 9 -- 1-based index, clamped to the LAST ladder entry
# ==========================================================================
@pytest.mark.parametrize("kind,ladder", [
    ("timeout", [60, 120, 240]),
    ("service", [600, 1200, 2400]),
])
def test_b9_attempt_selects_index_and_clamps_beyond_the_ladder(kind, ladder):
    assert [foundry.retry_delay(kind, n) for n in (1, 2, 3)] == ladder
    for beyond in (4, 5, 99):
        assert foundry.retry_delay(kind, beyond) == ladder[-1]


def test_b9_a_bogus_non_positive_attempt_is_total_and_never_the_longest_wait():
    """The spec requires only totality here; a 0/negative attempt must not index
    backwards into the LONGEST delay, which would be the opposite of `retry
    sooner`."""
    for bogus in (0, -1, -99):
        assert foundry.retry_delay("service", bogus) == 600
        assert foundry.retry_delay("timeout", bogus) == 60


# ==========================================================================
# Behavior 10 -- the floor, and an EMPTY ladder returns it instead of raising
# ==========================================================================
def test_b10_floor_constant_is_sixty_and_clamps_a_shorter_ladder(monkeypatch):
    assert foundry.RETRY_DELAY_FLOOR == 60
    monkeypatch.setattr(foundry, "TIMEOUT_BACKOFFS", [1, 2, 5])
    assert [foundry.retry_delay("timeout", n) for n in (1, 2, 3)] == [60, 60, 60]


@pytest.mark.parametrize("name,kind", [
    ("TIMEOUT_BACKOFFS", "timeout"),
    ("BACKOFFS", "service"),
])
def test_b10_empty_ladder_returns_the_floor_and_never_raises(monkeypatch, name, kind):
    monkeypatch.setattr(foundry, name, [])
    assert foundry.retry_delay(kind, 1) == foundry.RETRY_DELAY_FLOOR
    assert foundry.retry_delay(kind, 9) == foundry.RETRY_DELAY_FLOOR


# ==========================================================================
# Behavior 11 -- globals read AT CALL TIME; run_stage calls both by BARE NAME
# ==========================================================================
def test_b11_ladders_are_read_at_call_time(monkeypatch):
    """NOTE the spec's illustrative `TIMEOUT_BACKOFFS = [7]` is floor-clamped to
    60 by Behavior 10, so the call-time proof uses a value ABOVE the floor, then
    patches the floor too."""
    monkeypatch.setattr(foundry, "TIMEOUT_BACKOFFS", [999, 1000])
    assert foundry.retry_delay("timeout", 1) == 999
    monkeypatch.setattr(foundry, "RETRY_DELAY_FLOOR", 1)
    monkeypatch.setattr(foundry, "TIMEOUT_BACKOFFS", [7])
    assert foundry.retry_delay("timeout", 1) == 7
    monkeypatch.setattr(foundry, "BACKOFFS", [11111])
    assert foundry.retry_delay("service", 1) == 11111


def test_b11_fast_kind_set_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "FAST_RETRY_KINDS", ("service",))
    assert foundry.retry_delay("service", 1) == 60      # now the fast ladder
    assert foundry.retry_delay("timeout", 1) == 600     # now the default ladder


def test_b11_marker_table_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "ATTEMPT_FAILURE_MARKERS",
                        (("invented", ("zz-probe-marker",)),))
    assert foundry.classify_attempt_failure("... zz-probe-marker ...") == "invented"
    # the real markers are gone while patched -> everything else is the default
    assert foundry.classify_attempt_failure(CAP_TIMEOUT_BLOB) == "other"


def test_b11_run_stage_references_both_new_functions_by_bare_name():
    names = _co_names_deep(foundry.run_stage)
    for symbol in ("classify_attempt_failure", "retry_delay"):
        assert symbol in names, (
            "run_stage must call %s by BARE module name so a monkeypatch bites"
            % symbol)


def test_b11_both_functions_are_pure_and_touch_no_filesystem(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for _ in range(3):
        assert foundry.classify_attempt_failure(SERVICE_BLOB) == "service"
        assert foundry.retry_delay("timeout", 2) == 120
    assert list(tmp_path.iterdir()) == [], "a pure function wrote to the filesystem"


# ==========================================================================
# Behavior 12 -- a cap timeout now sleeps 60/120/240 (was 600/1200/2400)
# ==========================================================================
@pytest.mark.parametrize("blob", [CAP_TIMEOUT_BLOB, INTERNAL_TIMEOUT_BLOB,
                                  CLI_ERROR_BLOB])
def test_b12_no_wait_helps_kinds_use_the_fast_ladder_end_to_end(
        monkeypatch, tmp_path, blob):
    d = _drive(monkeypatch, tmp_path, blob)
    assert d.ok is False
    assert d.sleeps == [60, 120, 240], (
        "expected the fast ladder for a no-wait-helps failure, got %r" % (d.sleeps,))


# ==========================================================================
# Behavior 13 -- a genuine service failure is byte-identical to before
# ==========================================================================
@pytest.mark.parametrize("blob", [SERVICE_BLOB, STALLED_BLOB, UNMATCHED_BLOB, ""])
def test_b13_wait_helps_kinds_keep_todays_backoff_end_to_end(
        monkeypatch, tmp_path, blob):
    d = _drive(monkeypatch, tmp_path, blob)
    assert d.sleeps == [600, 1200, 2400], (
        "a long-ladder kind must sleep exactly as it did before iter 129, got %r"
        % (d.sleeps,))


# ==========================================================================
# Behavior 14 -- the log line keeps `backing off` AND now names the kind
# ==========================================================================
@pytest.mark.parametrize("blob,kind", [
    (CAP_TIMEOUT_BLOB, "timeout"),
    (CLI_ERROR_BLOB, "cli-error"),
    (SERVICE_BLOB, "service"),
    (STALLED_BLOB, "stalled"),
    (UNMATCHED_BLOB, "other"),
])
def test_b14_backoff_line_still_classifies_as_backoff_and_names_the_kind(
        monkeypatch, tmp_path, blob, kind):
    """This is the SECOND observable the decision needs: because the fallback
    kind draws from the DEFAULT ladder, a delay assertion alone cannot tell
    'classified correctly' from 'classifier is dead'. The printed kind can."""
    d = _drive(monkeypatch, tmp_path, blob)
    lines = _backoff_lines(d)
    assert len(lines) == foundry.MAX_ATTEMPTS - 1, (
        "expected one backoff line per non-final attempt, got %r" % (lines,))
    for ln in lines:
        assert foundry.classify_event(ln) == "backoff"
        assert ("kind: %s" % kind) in ln, (
            "the backoff line must name the classified kind; got %r" % ln)


def test_b14_backoff_line_still_reports_the_delay_in_whole_minutes(
        monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path, CAP_TIMEOUT_BLOB)
    mins = [ln for ln in _backoff_lines(d)]
    assert "backing off 1 min" in mins[0]
    assert "backing off 2 min" in mins[1]
    assert "backing off 4 min" in mins[2]


# ==========================================================================
# Behavior 15 -- everything else about the attempt loop is unchanged
# ==========================================================================
def test_b15_attempt_count_is_still_max_attempts(monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path, CAP_TIMEOUT_BLOB)
    assert len(d.calls) == foundry.MAX_ATTEMPTS
    assert len(d.sleeps) == foundry.MAX_ATTEMPTS - 1, "the FINAL attempt never sleeps"


def test_b15_stop_short_circuits_before_any_spawn(monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path, CAP_TIMEOUT_BLOB, stop=True)
    assert d.ok is False and d.calls == [] and d.sleeps == []


def test_b15_a_truthy_sleep_abandons_the_stage(monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path, CAP_TIMEOUT_BLOB, sleep_ret=True)
    assert d.ok is False
    assert len(d.calls) == 1 and d.sleeps == [60]


def test_b15_attempt_one_argv_is_still_byte_identical(monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path, CAP_TIMEOUT_BLOB)
    hits = [a for a in _argv(d.calls[0])
            if isinstance(a, str) and a.startswith(SENTINEL)]
    assert hits == [SENTINEL], (
        "attempt 1's prompt argv element must equal build_prompt's return exactly")


def test_b15_the_frozen_retry_constants_keep_their_literal_values():
    assert foundry.BACKOFFS == [600, 1200, 2400]
    assert foundry.MAX_ATTEMPTS == 4
    assert foundry.COOLDOWNS == [1800, 3600, 7200, 14400]
    assert foundry.TIMEOUT_BACKOFFS == [60, 120, 240]


# ==========================================================================
# Acceptance criteria -- import safety and public safety of the new code
# ==========================================================================
def test_ac_import_safety_of_both_modules():
    assert foundry.__file__ and dispatcher.__file__


def test_ac_new_code_and_this_test_scan_clean_under_the_committed_denylist():
    if not (_LEAK_GUARD.exists() and _DENYLIST.exists()):
        pytest.skip("leak-guard not present in this repo (repo-agnostic)")
    lg = _load_leak_guard()
    patterns = lg.load_denylist(_DENYLIST.read_text())
    home_prefix = "/" + "Users" + "/"  # built at runtime; never a source literal
    # two-sided: prove the matcher is LIVE before trusting a clean result
    assert len(lg.scan_text(home_prefix + "somebody/x", patterns)) >= 1, \
        "denylist appears inert (a home-path probe did not match)"
    texts = {
        "this test file": THIS_TEST.read_text(),
        "classify_attempt_failure": inspect.getsource(foundry.classify_attempt_failure),
        "retry_delay": inspect.getsource(foundry.retry_delay),
    }
    for label, txt in texts.items():
        assert len(lg.scan_text(txt, patterns)) == 0, \
            "%s contains a denylisted token (would BLOCK this iteration's ship)" % label
        assert home_prefix not in txt, \
            "%s contains an absolute home-directory path" % label


# ==========================================================================
# Acceptance criteria -- the NEUTERED-CLASSIFIER CONTROL, as a permanent test
#
# The spec asks for this control to be run once by hand against a scratch copy
# with the classifier body replaced by `return "other"`. Monkeypatching the
# module attribute reproduces exactly that condition (the call site resolves the
# name at call time), needs no scratch copy, and -- unlike a one-off manual run
# -- keeps proving on every suite run that the delay is wired to the DECISION
# and not merely to the attempt index. Added by the re-run tester round.
# ==========================================================================
def test_ac_control_neutered_classifier_flips_the_fast_ladder_back_to_the_long_one(
        monkeypatch, tmp_path):
    monkeypatch.setattr(foundry, "classify_attempt_failure", lambda _blob: "other")
    d = _drive(monkeypatch, tmp_path, CAP_TIMEOUT_BLOB)
    assert d.sleeps == [600, 1200, 2400], (
        "with the classifier neutered a cap timeout must fall back to the long "
        "ladder; got %r -- if this stays 60/120/240 the fast ladder is NOT wired "
        "to the classifier and Behavior 12 is vacuous" % (d.sleeps,))
    for ln in _backoff_lines(d):
        assert "kind: other" in ln, (
            "the logged kind must follow the live classifier, not a constant: %r" % ln)


def test_ac_control_the_live_classifier_is_what_makes_behavior_12_pass(
        monkeypatch, tmp_path):
    """Two-sided partner of the control above: the SAME harness, the SAME blob,
    with the real classifier in place, must give the fast ladder. A control that
    only ever fires red proves nothing about the green case."""
    d = _drive(monkeypatch, tmp_path, CAP_TIMEOUT_BLOB)
    assert d.sleeps == [60, 120, 240]


def test_ac_run_stage_feeds_the_real_failure_text_and_the_attempt_index(
        monkeypatch, tmp_path):
    """Pins the call contract at the seam: the classifier receives the attempt's
    own failure text (not a constant), and retry_delay receives that kind paired
    with the 1-based attempt number."""
    seen_blobs = []
    seen_calls = []

    def recording_classify(blob):
        seen_blobs.append(blob)
        return "timeout"

    def recording_delay(kind, attempt):
        seen_calls.append((kind, attempt))
        return 1

    monkeypatch.setattr(foundry, "classify_attempt_failure", recording_classify)
    monkeypatch.setattr(foundry, "retry_delay", recording_delay)
    d = _drive(monkeypatch, tmp_path, CAP_TIMEOUT_BLOB)

    assert seen_calls == [("timeout", 1), ("timeout", 2), ("timeout", 3)], (
        "retry_delay must be called once per non-final attempt with the "
        "classified kind and the 1-based attempt index; got %r" % (seen_calls,))
    assert d.sleeps == [1, 1, 1], "the delay actually slept must be retry_delay's"
    assert len(seen_blobs) >= foundry.MAX_ATTEMPTS - 1
    for blob in seen_blobs:
        assert "timed out after 600s" in blob, (
            "the classifier must be handed the attempt's own failure text; got %r"
            % (blob,))
