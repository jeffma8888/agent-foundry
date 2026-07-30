"""Black-box behaviour tests for iter 06 -- `watchdog.py`, the external
resurrector that relaunches the single-brain dispatcher after a crash while
honoring the two safety invariants: single-brain (never a second dispatcher)
and STOP-respect (never resurrect a deliberately stopped company). Roadmap
item 8.

ISOLATION: written SOLELY from the iter-06 PM spec (Expected Behaviors 1-16),
the existing test conventions under `tests/`, and the product's own public
interface discovered by runtime introspection / driving it (permitted). The
implementation source of `watchdog.py`, `foundry.py`, and `dispatcher.py`, the
engineer's/reviewer's notes for this iteration, and `git diff` were NOT read.

Every effect is offline and deterministic: `decide` is a pure boolean->value
function; `stop_present` reads only a caller-supplied `tmp_path`; process
liveness is forced through the monkeypatchable `watchdog._pgrep` seam;
`relaunch_dispatcher` is ALWAYS a spy and is NEVER actually executed; `wlog`
writes only to a caller-supplied path. No real subprocess / pgrep / git /
network / agent-run and no real dispatcher launch occur.
"""
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import watchdog  # noqa: E402


# --------------------------------------------------------------------------
# helpers / fixtures
# --------------------------------------------------------------------------
def _write_cfg(tmp_path):
    """A minimal on-disk config path; relaunch is always spied, never run,
    so the contents are never actually consumed by a real dispatcher."""
    p = tmp_path / "config.json"
    p.write_text('{"name": "demo"}')
    return p


class _Spy:
    """Records every call so tests can assert call count and forwarded args."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))

    @property
    def count(self):
        return len(self.calls)


def _all_combos():
    return [(r, s) for r in (True, False) for s in (True, False)]


# ==========================================================================
# Pure decision decide(*, is_running, stopped) -- the safety core (Beh 1-5)
# ==========================================================================

# Behavior 1 -- dispatcher already alive -> do NOT relaunch (single-brain)
def test_b1_alive_no_stop_does_not_relaunch():
    d = watchdog.decide(is_running=True, stopped=False)
    assert d.relaunch is False


# Behavior 2 -- down and no STOP -> relaunch (the resurrection case)
def test_b2_down_no_stop_relaunches():
    d = watchdog.decide(is_running=False, stopped=False)
    assert d.relaunch is True


# Behavior 3 -- down but STOP present -> do NOT relaunch (respect a stop)
def test_b3_down_with_stop_does_not_relaunch():
    d = watchdog.decide(is_running=False, stopped=True)
    assert d.relaunch is False


# Behavior 4 -- alive AND STOP present -> do NOT relaunch (liveness dominates)
def test_b4_alive_with_stop_does_not_relaunch():
    d = watchdog.decide(is_running=True, stopped=True)
    assert d.relaunch is False


# Behavior 5 -- relaunch is True in EXACTLY the down-and-not-stopped case,
# and every decision carries a non-empty reason string.
def test_b5_truth_table_and_reasons():
    for is_running, stopped in _all_combos():
        d = watchdog.decide(is_running=is_running, stopped=stopped)
        expected = (is_running is False) and (stopped is False)
        assert d.relaunch is expected, (
            f"decide(is_running={is_running}, stopped={stopped}).relaunch "
            f"was {d.relaunch!r}, expected {expected!r}")
        assert isinstance(d.reason, str) and d.reason.strip(), (
            f"reason for (is_running={is_running}, stopped={stopped}) "
            f"must be a non-empty str, got {d.reason!r}")


# The value object exposes the two documented fields.
def test_b5b_decision_value_object_fields():
    d = watchdog.decide(is_running=False, stopped=False)
    assert hasattr(d, "relaunch") and hasattr(d, "reason")
    assert isinstance(d.relaunch, bool)
    assert isinstance(d.reason, str)


# ==========================================================================
# stop_present(foundry_dir) -- offline STOP-file check (Beh 6-7)
# ==========================================================================

# Behavior 6 -- no STOP file -> False
def test_b6_no_stop_file_is_false(tmp_path):
    assert watchdog.stop_present(foundry_dir=tmp_path) is False


# Behavior 7 -- STOP file present -> True
def test_b7_stop_file_present_is_true(tmp_path):
    (tmp_path / "STOP").touch()
    assert watchdog.stop_present(foundry_dir=tmp_path) is True


# ==========================================================================
# dispatcher_running(pattern) -- process-scan liveness, self-excluded (8-10)
# ==========================================================================

# Behavior 8 -- no matching process -> False
def test_b8_no_match_is_false(monkeypatch):
    monkeypatch.setattr(watchdog, "_pgrep", lambda pattern: [])
    assert watchdog.dispatcher_running() is False


# Behavior 9 -- a matching FOREIGN pid -> True
def test_b9_foreign_pid_is_true(monkeypatch):
    foreign = 999999
    assert foreign != os.getpid()
    monkeypatch.setattr(watchdog, "_pgrep", lambda pattern: [foreign])
    assert watchdog.dispatcher_running() is True


# Behavior 10 -- only its OWN pid matches -> False (self is filtered out)
def test_b10_only_own_pid_is_false(monkeypatch):
    monkeypatch.setattr(watchdog, "_pgrep", lambda pattern: [os.getpid()])
    assert watchdog.dispatcher_running() is False


# Own pid mixed with a foreign one still counts the foreign -> True.
def test_b10b_own_plus_foreign_is_true(monkeypatch):
    monkeypatch.setattr(watchdog, "_pgrep", lambda pattern: [os.getpid(), 999999])
    assert watchdog.dispatcher_running() is True


# ==========================================================================
# run_watchdog(config_path, foundry_dir) -- orchestration end-to-end (11-13)
# ==========================================================================

# Behavior 11 -- dispatcher alive -> no relaunch, spy called ZERO times
def test_b11_alive_no_relaunch(tmp_path, monkeypatch):
    cfg = _write_cfg(tmp_path)
    spy = _Spy()
    monkeypatch.setattr(watchdog, "dispatcher_running", lambda *a, **k: True)
    monkeypatch.setattr(watchdog, "stop_present", lambda *a, **k: False)
    monkeypatch.setattr(watchdog, "relaunch_dispatcher", spy)
    monkeypatch.setattr(watchdog, "wlog", lambda *a, **k: None)

    d = watchdog.run_watchdog(cfg)
    assert d.relaunch is False
    assert spy.count == 0, f"relaunch spy called {spy.count} times, expected 0"


# Behavior 12 -- down but STOP present -> no relaunch, spy called ZERO times
def test_b12_down_but_stopped_no_relaunch(tmp_path, monkeypatch):
    cfg = _write_cfg(tmp_path)
    spy = _Spy()
    monkeypatch.setattr(watchdog, "dispatcher_running", lambda *a, **k: False)
    monkeypatch.setattr(watchdog, "stop_present", lambda *a, **k: True)
    monkeypatch.setattr(watchdog, "relaunch_dispatcher", spy)
    monkeypatch.setattr(watchdog, "wlog", lambda *a, **k: None)

    d = watchdog.run_watchdog(cfg)
    assert d.relaunch is False
    assert spy.count == 0, f"relaunch spy called {spy.count} times, expected 0"


# Behavior 13 -- down and no STOP -> relaunch EXACTLY once, config forwarded
def test_b13_down_no_stop_relaunches_once_with_config(tmp_path, monkeypatch):
    cfg = _write_cfg(tmp_path)
    spy = _Spy()
    monkeypatch.setattr(watchdog, "dispatcher_running", lambda *a, **k: False)
    monkeypatch.setattr(watchdog, "stop_present", lambda *a, **k: False)
    monkeypatch.setattr(watchdog, "relaunch_dispatcher", spy)
    monkeypatch.setattr(watchdog, "wlog", lambda *a, **k: None)

    d = watchdog.run_watchdog(cfg)
    assert d.relaunch is True
    assert spy.count == 1, f"relaunch spy called {spy.count} times, expected 1"

    # the config_path value handed to run_watchdog is forwarded to relaunch
    args, kwargs = spy.calls[0]
    forwarded = list(args) + list(kwargs.values())
    assert any(str(v) == str(cfg) for v in forwarded), (
        f"config_path {cfg!r} was not forwarded to relaunch_dispatcher; "
        f"spy saw args={args!r} kwargs={kwargs!r}")


# ==========================================================================
# wlog best-effort resilience (Behavior 14)
# ==========================================================================

# Behavior 14 -- wlog never propagates a write failure (log_path unopenable)
def test_b14_wlog_never_raises_on_write_failure(tmp_path):
    # a directory can never be opened for text append -> write must fail
    unwritable = tmp_path  # tmp_path itself is an existing directory
    assert unwritable.is_dir()
    # must return normally (None), never raise
    assert watchdog.wlog("anything", log_path=unwritable) is None


# ==========================================================================
# main CLI (Behavior 15)
# ==========================================================================

# Behavior 15 -- main runs one check, relaunches when warranted, returns 0
def test_b15_main_relaunches_and_returns_zero(tmp_path, monkeypatch):
    cfg = _write_cfg(tmp_path)
    spy = _Spy()
    monkeypatch.setattr(watchdog, "dispatcher_running", lambda *a, **k: False)
    monkeypatch.setattr(watchdog, "stop_present", lambda *a, **k: False)
    monkeypatch.setattr(watchdog, "relaunch_dispatcher", spy)
    monkeypatch.setattr(watchdog, "wlog", lambda *a, **k: None)

    rc = watchdog.main(["--config", str(cfg)])
    assert rc == 0, f"main returned {rc!r}, expected 0"
    assert spy.count == 1, f"relaunch spy called {spy.count} times, expected 1"


# main does NOT relaunch when the dispatcher is alive, and still returns 0.
def test_b15b_main_no_relaunch_when_alive_returns_zero(tmp_path, monkeypatch):
    cfg = _write_cfg(tmp_path)
    spy = _Spy()
    monkeypatch.setattr(watchdog, "dispatcher_running", lambda *a, **k: True)
    monkeypatch.setattr(watchdog, "stop_present", lambda *a, **k: False)
    monkeypatch.setattr(watchdog, "relaunch_dispatcher", spy)
    monkeypatch.setattr(watchdog, "wlog", lambda *a, **k: None)

    rc = watchdog.main(["--config", str(cfg)])
    assert rc == 0, f"main returned {rc!r}, expected 0"
    assert spy.count == 0, f"relaunch spy called {spy.count} times, expected 0"


# ==========================================================================
# Module hygiene / non-regression (Behavior 16)
# ==========================================================================

# Behavior 16 -- new module imports, siblings still import, public API callable
def test_b16_imports_and_public_api_callable():
    import foundry  # noqa: F401
    import dispatcher  # noqa: F401

    for name in (
        "decide",
        "stop_present",
        "dispatcher_running",
        "relaunch_dispatcher",
        "run_watchdog",
        "main",
    ):
        fn = getattr(watchdog, name)
        assert callable(fn), f"watchdog.{name} is not callable"
