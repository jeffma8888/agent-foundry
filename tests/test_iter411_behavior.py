"""Behaviour tests for iter 411 -- one `auth` attempt, then a STOP-aware hold.

Spec: products/_platform/state/iter-411/pm.md, Expected Behaviors 1-8.

  1. AUTH_HOLD_SECONDS exists, is an int, equals 1800, and is strictly longer
     than both ladders it replaces (TIMEOUT_BACKOFFS and KIND_RETRY_LADDERS["auth"]).
  2. an auth blob on attempt 1 -> (False, out_file) after EXACTLY ONE spawn;
     attempt1.log holds the blob, attempt2.log does not exist, out_file absent.
  3. that run makes exactly one sleep_interruptible call carrying
     AUTH_HOLD_SECONDS, read at CALL time (a monkeypatch to 7 bites); time.sleep
     is never reached.
  4. the hold line: exactly one NIGHT_LOG line with `backing off 30 min (failure
     kind: auth)` AND `auth hold`, classify_event -> "backoff", and no
     `backing off 1 min` anywhere; with the hold patched to 120 s it reads
     `backing off 2 min (failure kind: auth)`.
  5. STOP inside the hold (sleep_interruptible returns True) still yields
     (False, out_file), one spawn, no attempt2.log.
  6. an auth blob whose spawn ALSO writes a non-empty out_file -> (True, out_file),
     one spawn, ZERO sleeps, no `backing off` line (output-file success wins).
  7. timeout / stalled / service / cli-error / other are byte-unchanged:
     MAX_ATTEMPTS spawns, MAX_ATTEMPTS-1 sleeps equal to retry_delay(kind, n),
     and no `auth hold` substring in NIGHT_LOG.
  8. auth on a LATER attempt holds from that attempt: [timeout, timeout, auth]
     -> 3 spawns, sleeps [rd(t,1), rd(t,2), HOLD], attempt3.log yes / attempt4.log
     no; [timeout, timeout, timeout, auth] -> 4 spawns, sleeps
     [rd(t,1), rd(t,2), rd(t,3), HOLD] (the hold fires on the LAST attempt too).

ISOLATION: written by the tester stage under its black-box contract -- the
spec, tests/, README and the product's runtime output only; no implementation
source, no diff, no engineer/reviewer notes. run_stage is driven exactly as
tests/test_iter129_behavior.py::_drive drives it: build_prompt / stopping /
resolve_agent_endpoint patched, subprocess.run scripted to return a blob (and
by default NEVER write the output file), sleep_interruptible recorded and
returning False unless a behavior says otherwise, time.sleep armed to raise.
Nothing real is spawned or slept; every path is tmp_path-rooted.
"""
import json
import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402,F401  (import-safety probe: both must import)

ITERATION = 5
SENTINEL = "SENTINEL-PROMPT-411"

# --------------------------------------------------------------------------
# fixture blobs -- one per failure kind the spec names, plus two auth shapes
# --------------------------------------------------------------------------
AUTH_BLOB_SHORT = "agent run failed: auth failed"
# The real on-disk shape, verbatim from tests/test_iter196_behavior.py (em dash
# is `\u2014`); it ALSO contains `timed out`, so it proves auth outranks timeout.
_REAL_PREFIX = (
    "agent run failed: subagent turn failed: Credential refresh failed \u2014 "
    "your session may have expired\n\n(detail: dispatch failure: other: "
)
AUTH_BLOB_TIMED_OUT = _REAL_PREFIX + (
    "an error occurred while loading credentials: "
    "credential refresh failed (Llm): authentication timed out)"
)
TIMEOUT_BLOB = "agent run timed out after 600s"
STALLED_BLOB = "Connection stalled - no data received for 120 s"
SERVICE_BLOB = "service is busy"
CLI_ERROR_BLOB = "native shortcut did not match"
OTHER_BLOB = "something nobody has a needle for"

NON_AUTH_KINDS = [
    ("timeout", TIMEOUT_BLOB),
    ("stalled", STALLED_BLOB),
    ("service", SERVICE_BLOB),
    ("cli-error", CLI_ERROR_BLOB),
    ("other", OTHER_BLOB),
]

# Import-time PREMISE asserts (iter 381 lesson): every fixture must classify as
# the kind its behavior assumes, or the tests below exercise the wrong branch.
assert foundry.classify_attempt_failure(AUTH_BLOB_SHORT) == foundry.AUTH_LOSS_KIND
assert foundry.classify_attempt_failure(AUTH_BLOB_TIMED_OUT) == foundry.AUTH_LOSS_KIND
for _kind, _blob in NON_AUTH_KINDS:
    assert foundry.classify_attempt_failure(_blob) == _kind, (_kind, _blob)
    assert _kind != foundry.AUTH_LOSS_KIND


# --------------------------------------------------------------------------
# offline run_stage drive harness (mirrors tests/test_iter129_behavior.py)
# --------------------------------------------------------------------------
class _FakeCP:
    """Stand-in for subprocess.CompletedProcess: only the attributes run_stage
    reads (.returncode / .stdout / .stderr)."""

    def __init__(self, rc=1, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def _make_cfg(root):
    """Minimal product config in a tmp dir; repo + work_root are TMP so the live
    foundry repo and products/ tree are NEVER touched."""
    root.mkdir(parents=True, exist_ok=True)
    repo = root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (root / "VISION.md").write_text("vision\n")
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(root / "VISION.md"),
        "work_root": str(root / "work"),
    }
    p = root / "config.json"
    p.write_text(json.dumps(data))
    return foundry.load_config(str(p))


def _role_file(root):
    r = root / "role.md"
    r.write_text("do the thing\n")
    return str(r)


def _patch_common(monkeypatch, stop=False):
    monkeypatch.setattr(foundry, "build_prompt", lambda *a, **k: SENTINEL)
    monkeypatch.setattr(foundry, "stopping", lambda _cfg: stop)
    monkeypatch.setattr(foundry, "resolve_agent_endpoint", lambda *a, **k: None)


def _time_sleep_is_never_reached(*_a, **_k):
    raise AssertionError("time.sleep was reached -- the hold must go through "
                         "the sleep_interruptible seam")


def _discover_out_path(monkeypatch, root):
    """Learn run_stage's out_file path black-box, with ZERO spawns, by driving a
    sibling config with STOP already requested (the documented short-circuit).
    Returns the path RELATIVE to that sibling root so the caller can map it onto
    its own root."""
    cfg = _make_cfg(root)
    role = _role_file(root)
    _patch_common(monkeypatch, stop=True)
    spawns = []
    monkeypatch.setattr(foundry.subprocess, "run",
                        lambda *a, **k: spawns.append(1) or _FakeCP())
    ok, out = foundry.run_stage(cfg, ITERATION, "engineer", role, "engineer.md")
    assert ok is False and not out.exists() and spawns == []
    return out.relative_to(root)


def _drive(monkeypatch, tmp_path, blobs, stop=False, sleep_ret=False,
           write_out_on=None):
    """Drive run_stage against a stage whose attempt N returns blobs[N-1] (the
    last blob repeats if the loop runs longer than the script). By default the
    stage NEVER writes its output file; write_out_on=N makes attempt N also
    write a non-empty out_file. Returns recorded spawns, seam sleeps and the
    NIGHT_LOG lines. Nothing real is spawned and nothing really sleeps."""
    blobs = list(blobs)
    assert blobs, "script at least one blob"
    root = tmp_path / "run"
    out_rel = None
    if write_out_on is not None:
        out_rel = _discover_out_path(monkeypatch, tmp_path / "probe")

    cfg = _make_cfg(root)
    role = _role_file(root)
    _patch_common(monkeypatch, stop=stop)
    monkeypatch.setattr(foundry.time, "sleep", _time_sleep_is_never_reached)

    sleeps = []

    def fake_sleep(_cfg, seconds):
        sleeps.append(seconds)
        return sleep_ret

    monkeypatch.setattr(foundry, "sleep_interruptible", fake_sleep)

    calls = []

    def fake_run(*a, **k):
        calls.append((a, dict(k)))
        n = len(calls)
        if write_out_on is not None and n == write_out_on:
            target = root / out_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("STAGE OUTPUT\n")
        return _FakeCP(out=blobs[min(n, len(blobs)) - 1])

    monkeypatch.setattr(foundry.subprocess, "run", fake_run)
    ok, out = foundry.run_stage(cfg, ITERATION, "engineer", role, "engineer.md")
    if out_rel is not None:
        assert out == root / out_rel, (out, root / out_rel)
    lines = (cfg.night_log.read_text().splitlines()
             if cfg.night_log.exists() else [])
    return types.SimpleNamespace(ok=ok, out=out, calls=calls, sleeps=sleeps,
                                 log_lines=lines, cfg=cfg)


def _attempt_log(drive, n):
    return drive.out.parent / ("engineer.attempt%d.log" % n)


def _backoff_lines(drive):
    return [ln for ln in drive.log_lines if "backing off" in ln]


def _hold_lines(drive):
    return [ln for ln in drive.log_lines if "auth hold" in ln]


# ==========================================================================
# Behavior 1 -- the constant
# ==========================================================================
def test_b1_constant_exists_is_int_and_is_1800():
    assert hasattr(foundry, "AUTH_HOLD_SECONDS")
    assert isinstance(foundry.AUTH_HOLD_SECONDS, int)
    assert not isinstance(foundry.AUTH_HOLD_SECONDS, bool)
    assert foundry.AUTH_HOLD_SECONDS == 1800


def test_b1_hold_is_strictly_longer_than_both_ladders_it_replaces():
    """A hold shorter than the ladder it replaces is a regression, not a hold."""
    assert foundry.AUTH_HOLD_SECONDS > max(foundry.TIMEOUT_BACKOFFS)
    assert foundry.AUTH_HOLD_SECONDS > max(foundry.KIND_RETRY_LADDERS["auth"])


def test_b1_hold_is_also_longer_than_every_rung_retry_delay_would_price():
    """Cross-check through the public pricer, not just the raw tables."""
    priced = [foundry.retry_delay(foundry.AUTH_LOSS_KIND, n)
              for n in range(1, foundry.MAX_ATTEMPTS)]
    assert foundry.AUTH_HOLD_SECONDS > max(priced)


# ==========================================================================
# Behavior 2 -- one spawn on auth
# ==========================================================================
@pytest.mark.parametrize("blob", [AUTH_BLOB_SHORT, AUTH_BLOB_TIMED_OUT],
                         ids=["short", "real-timed-out"])
def test_b2_auth_on_attempt_1_returns_false_after_exactly_one_spawn(
        tmp_path, monkeypatch, blob):
    d = _drive(monkeypatch, tmp_path, [blob])
    assert d.ok is False
    assert isinstance(d.out, pathlib.Path)
    assert d.out.name == "engineer.md"
    assert not d.out.exists()
    assert len(d.calls) == 1, "auth must not be retried (%d spawns)" % len(d.calls)


def test_b2_attempt1_log_holds_the_blob_and_attempt2_log_does_not_exist(
        tmp_path, monkeypatch):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB_SHORT])
    log1 = _attempt_log(d, 1)
    assert log1.exists(), "missing %s" % log1.name
    assert AUTH_BLOB_SHORT in log1.read_text()
    assert not _attempt_log(d, 2).exists()
    assert d.out.parent.name == "iter-%02d" % ITERATION


def test_b2_no_later_attempt_log_of_any_number(tmp_path, monkeypatch):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB_TIMED_OUT])
    for n in range(2, foundry.MAX_ATTEMPTS + 2):
        assert not _attempt_log(d, n).exists(), "attempt%d.log written" % n


# ==========================================================================
# Behavior 3 -- one hold through the seam, read at call time
# ==========================================================================
def test_b3_exactly_one_seam_sleep_of_auth_hold_seconds(tmp_path, monkeypatch):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB_SHORT])
    assert d.sleeps == [foundry.AUTH_HOLD_SECONDS]
    assert d.sleeps == [1800]


def test_b3_hold_length_is_read_at_call_time(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry, "AUTH_HOLD_SECONDS", 7)
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB_SHORT])
    assert d.sleeps == [7]
    assert len(d.calls) == 1


def test_b3_time_sleep_is_never_reached(tmp_path, monkeypatch):
    """_drive arms time.sleep to raise AssertionError; the run must complete."""
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB_TIMED_OUT])
    assert d.ok is False
    assert d.sleeps == [foundry.AUTH_HOLD_SECONDS]


# ==========================================================================
# Behavior 4 -- hold line shape
# ==========================================================================
def test_b4_exactly_one_hold_line_with_both_substrings(tmp_path, monkeypatch):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB_SHORT])
    hits = [ln for ln in d.log_lines
            if "backing off 30 min (failure kind: auth)" in ln
            and "auth hold" in ln]
    assert len(hits) == 1, d.log_lines
    assert _hold_lines(d) == hits
    assert _backoff_lines(d) == hits


def test_b4_hold_line_is_stamped_backoff_by_the_event_classifier(
        tmp_path, monkeypatch):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB_SHORT])
    (line,) = _hold_lines(d)
    assert foundry.classify_event(line) == "backoff"


def test_b4_hold_line_names_iteration_and_stage(tmp_path, monkeypatch):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB_SHORT])
    (line,) = _hold_lines(d)
    assert "iter %02d" % ITERATION in line
    assert "engineer" in line


def test_b4_fast_ladder_first_rung_never_consulted(tmp_path, monkeypatch):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB_TIMED_OUT])
    assert not any("backing off 1 min" in ln for ln in d.log_lines), d.log_lines
    assert not any("backing off 2 min" in ln for ln in d.log_lines), d.log_lines


def test_b4_hold_line_minutes_follow_the_patched_constant(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry, "AUTH_HOLD_SECONDS", 120)
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB_SHORT])
    hits = [ln for ln in d.log_lines
            if "backing off 2 min (failure kind: auth)" in ln]
    assert len(hits) == 1, d.log_lines
    assert "auth hold" in hits[0]
    assert not any("backing off 30 min" in ln for ln in d.log_lines)
    assert d.sleeps == [120]


# ==========================================================================
# Behavior 5 -- STOP wins inside the hold
# ==========================================================================
def test_b5_stop_mid_hold_still_returns_false_with_one_spawn(
        tmp_path, monkeypatch):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB_SHORT], sleep_ret=True)
    assert d.ok is False
    assert isinstance(d.out, pathlib.Path)
    assert not d.out.exists()
    assert len(d.calls) == 1
    assert d.sleeps == [foundry.AUTH_HOLD_SECONDS]
    assert _attempt_log(d, 1).exists()
    assert not _attempt_log(d, 2).exists()


def test_b5_stop_mid_hold_writes_no_second_attempt_even_when_script_has_more(
        tmp_path, monkeypatch):
    """If the loop wrongly continued past a STOPped hold, attempt 2 would
    return a timeout blob and leave attempt2.log behind."""
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB_SHORT, TIMEOUT_BLOB],
               sleep_ret=True)
    assert len(d.calls) == 1
    assert not _attempt_log(d, 2).exists()
    assert d.ok is False


# ==========================================================================
# Behavior 6 -- output file still wins over the blob
# ==========================================================================
@pytest.mark.parametrize("blob", [AUTH_BLOB_SHORT, AUTH_BLOB_TIMED_OUT],
                         ids=["short", "real-timed-out"])
def test_b6_written_output_file_beats_an_auth_blob(tmp_path, monkeypatch, blob):
    d = _drive(monkeypatch, tmp_path, [blob], write_out_on=1)
    assert d.ok is True
    assert d.out.exists() and d.out.read_text().strip()
    assert len(d.calls) == 1
    assert d.sleeps == []
    assert _backoff_lines(d) == []
    assert _hold_lines(d) == []


# ==========================================================================
# Behavior 7 -- non-auth kinds are byte-unchanged
# ==========================================================================
@pytest.mark.parametrize("kind,blob", NON_AUTH_KINDS,
                         ids=[k for k, _ in NON_AUTH_KINDS])
def test_b7_non_auth_kind_runs_the_full_ladder_unchanged(
        tmp_path, monkeypatch, kind, blob):
    d = _drive(monkeypatch, tmp_path, [blob])
    assert d.ok is False
    assert len(d.calls) == foundry.MAX_ATTEMPTS
    assert len(d.sleeps) == foundry.MAX_ATTEMPTS - 1
    assert d.sleeps == [foundry.retry_delay(kind, n)
                        for n in range(1, foundry.MAX_ATTEMPTS)]
    assert _hold_lines(d) == []
    assert not any(foundry.AUTH_HOLD_SECONDS == s for s in d.sleeps)


@pytest.mark.parametrize("kind,blob", NON_AUTH_KINDS,
                         ids=[k for k, _ in NON_AUTH_KINDS])
def test_b7_non_auth_backoff_lines_name_their_own_kind(
        tmp_path, monkeypatch, kind, blob):
    d = _drive(monkeypatch, tmp_path, [blob])
    lines = _backoff_lines(d)
    assert len(lines) == foundry.MAX_ATTEMPTS - 1
    for ln in lines:
        assert "(failure kind: %s)" % kind in ln
        assert "auth" not in ln.split("failure kind:")[1]
    for n in range(1, foundry.MAX_ATTEMPTS + 1):
        assert _attempt_log(d, n).exists()


# ==========================================================================
# Behavior 8 -- auth on a later attempt holds from THAT attempt
# ==========================================================================
def test_b8_auth_on_attempt_3_holds_after_two_timeout_rungs(
        tmp_path, monkeypatch):
    d = _drive(monkeypatch, tmp_path, [TIMEOUT_BLOB, TIMEOUT_BLOB, AUTH_BLOB_SHORT])
    assert d.ok is False
    assert isinstance(d.out, pathlib.Path) and not d.out.exists()
    assert len(d.calls) == 3
    assert d.sleeps == [foundry.retry_delay("timeout", 1),
                        foundry.retry_delay("timeout", 2),
                        foundry.AUTH_HOLD_SECONDS]
    assert _attempt_log(d, 3).exists()
    assert not _attempt_log(d, 4).exists()
    assert len(_hold_lines(d)) == 1
    assert "backing off 30 min (failure kind: auth)" in _hold_lines(d)[0]


def test_b8_auth_on_the_last_attempt_still_holds(tmp_path, monkeypatch):
    """The NEXT stage would fail the same way within seconds, so the hold must
    fire even when there is no attempt left to protect."""
    assert foundry.MAX_ATTEMPTS == 4  # the spec's 4-blob script assumes it
    d = _drive(monkeypatch, tmp_path,
               [TIMEOUT_BLOB, TIMEOUT_BLOB, TIMEOUT_BLOB, AUTH_BLOB_TIMED_OUT])
    assert d.ok is False
    assert len(d.calls) == foundry.MAX_ATTEMPTS
    assert d.sleeps == ([foundry.retry_delay("timeout", n) for n in (1, 2, 3)]
                        + [foundry.AUTH_HOLD_SECONDS])
    assert _attempt_log(d, 4).exists()
    assert not _attempt_log(d, 5).exists()
    assert len(_hold_lines(d)) == 1
    assert sum("backing off 1 min" in ln for ln in d.log_lines) == 1
    assert sum("backing off 2 min" in ln for ln in d.log_lines) == 1
    assert sum("backing off 4 min" in ln for ln in d.log_lines) == 1


def test_b8_hold_on_a_later_attempt_still_reads_the_constant_at_call_time(
        tmp_path, monkeypatch):
    monkeypatch.setattr(foundry, "AUTH_HOLD_SECONDS", 9)
    d = _drive(monkeypatch, tmp_path, [TIMEOUT_BLOB, AUTH_BLOB_SHORT])
    assert len(d.calls) == 2
    assert d.sleeps == [foundry.retry_delay("timeout", 1), 9]
    assert not _attempt_log(d, 3).exists()


# ==========================================================================
# Public-safety self-scan (this repo is public)
# ==========================================================================
def test_this_file_has_no_absolute_machine_paths():
    body = pathlib.Path(__file__).read_text().split('"""', 2)[2]
    for needle in ("/Us" + "ers/", "/ho" + "me/", "C:" + "\\"):
        assert needle not in body, needle
