"""Strangler step 4 (docs/STRANGLER_PLAN.md): watchdog.py delegates to the library.

The epic's goal is ONE definition of each resilience primitive, owned by the
published `resilient-agent-loop-primitives` library, with this platform importing
it instead of keeping an inline copy. Step 4 moves the resurrect-if-down
watchdog. It was chosen as the FIRST slice because `watchdog.py` has zero
non-test importers, so it is off the live dispatch/resume path and cannot regress
a running loop.

These tests are the RATCHET. `tests/test_iter06_behavior.py` still pins the
observable behavior (truth table, seam monkeypatchability, config forwarding,
best-effort logging) and stays green UNCHANGED -- that is the behavior-
preservation proof. What this file adds is that the behavior is achieved by
DELEGATION and not by a re-inlined copy, so a future iteration cannot quietly
grow the duplication back (the failure mode the strangler plan warns about).

Offline and deterministic: no subprocess, no process scan, no real relaunch.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import watchdog  # noqa: E402

from resilient_agent_loop.watchdog import Decision as LibDecision  # noqa: E402
from resilient_agent_loop.watchdog import decide as lib_decide  # noqa: E402

WATCHDOG_PY = _ROOT / "watchdog.py"
_ALL_COMBOS = ((True, True), (True, False), (False, True), (False, False))


# ==========================================================================
# Behavior 1 -- the library owns the TYPE (exactly one definition)
# ==========================================================================
def test_b1_decision_type_is_the_library_type():
    assert watchdog.WatchdogDecision is LibDecision, (
        "watchdog.WatchdogDecision must be an ALIAS of the library Decision, "
        "not a second local dataclass"
    )


def test_b1_decide_returns_the_library_type():
    for is_running, stopped in _ALL_COMBOS:
        d = watchdog.decide(is_running=is_running, stopped=stopped)
        assert isinstance(d, LibDecision), (
            f"decide(is_running={is_running}, stopped={stopped}) returned "
            f"{type(d)!r}, expected the library Decision"
        )


# ==========================================================================
# Behavior 2 -- the library owns the POLICY (verdict AND reason match exactly)
# ==========================================================================
def test_b2_decide_matches_the_library_verbatim():
    for is_running, stopped in _ALL_COMBOS:
        mine = watchdog.decide(is_running=is_running, stopped=stopped)
        theirs = lib_decide(is_running=is_running, stopped=stopped)
        assert mine == theirs, (
            f"decide diverged from the library at "
            f"(is_running={is_running}, stopped={stopped}): {mine!r} != {theirs!r}"
        )


def test_b2_safety_invariants_survive_delegation():
    """The two guards the whole watchdog exists for, re-asserted post-delegation."""
    # single-brain: never relaunch while one is alive, even with a STOP present.
    assert watchdog.decide(is_running=True, stopped=False).relaunch is False
    assert watchdog.decide(is_running=True, stopped=True).relaunch is False
    # STOP-respect: never resurrect a deliberately stopped company.
    assert watchdog.decide(is_running=False, stopped=True).relaunch is False
    # the ONLY resurrect case.
    assert watchdog.decide(is_running=False, stopped=False).relaunch is True


# ==========================================================================
# Behavior 3 -- no re-inlined copy remains in the module source
# ==========================================================================
def test_b3_module_imports_the_library():
    text = WATCHDOG_PY.read_text(encoding="utf-8")
    assert "from resilient_agent_loop.watchdog import" in text, (
        "watchdog.py must IMPORT the library primitives (step 4 delegation)"
    )


def test_b3_no_local_dataclass_decision_remains():
    text = WATCHDOG_PY.read_text(encoding="utf-8")
    assert "dataclasses.dataclass" not in text, (
        "watchdog.py declares a local dataclass again -- the decision type must "
        "come from the library (strangler duplication regrew)"
    )
    assert "import dataclasses" not in text, (
        "watchdog.py re-imported dataclasses -- nothing local needs it now"
    )


def test_b3_no_reinlined_truth_table():
    """The policy branches must not reappear in this module."""
    text = WATCHDOG_PY.read_text(encoding="utf-8")
    assert "if is_running:" not in text, (
        "watchdog.py re-implements the liveness branch -- policy belongs to the library"
    )
    assert "if stopped:" not in text, (
        "watchdog.py re-implements the STOP branch -- policy belongs to the library"
    )


# ==========================================================================
# Behavior 4 -- run_watchdog delegates the TICK to the library's supervise
# ==========================================================================
def test_b4_run_watchdog_calls_library_supervise(tmp_path, monkeypatch):
    seen: dict = {}

    def fake_supervise(*, is_running, is_stopped, relaunch, log):
        seen["kwargs"] = ("is_running", "is_stopped", "relaunch", "log")
        seen["callables"] = all(callable(x) for x in (is_running, is_stopped, relaunch, log))
        return type("R", (), {"decision": LibDecision(relaunch=False, reason="stub"),
                              "relaunched": False})()

    monkeypatch.setattr(watchdog, "_lib_supervise", fake_supervise)
    d = watchdog.run_watchdog(tmp_path / "cfg.json", foundry_dir=tmp_path)

    assert seen.get("callables") is True, "all four seams must be passed as callables"
    assert d.reason == "stub", "run_watchdog must return the library result's decision"


def test_b4_returns_decision_not_supervise_result(tmp_path, monkeypatch):
    """Contract preserved: run_watchdog returns a Decision, never a SuperviseResult."""
    monkeypatch.setattr(watchdog, "dispatcher_running", lambda *a, **k: True)
    monkeypatch.setattr(watchdog, "stop_present", lambda *a, **k: False)
    monkeypatch.setattr(watchdog, "wlog", lambda *a, **k: None)
    d = watchdog.run_watchdog(tmp_path / "cfg.json", foundry_dir=tmp_path)
    assert isinstance(d, LibDecision)
    assert not hasattr(d, "relaunched"), "returned a SuperviseResult, expected a Decision"


# ==========================================================================
# Behavior 5 -- the foundry-specific parts are NOT delegated away
# ==========================================================================
def test_b5_seams_still_monkeypatchable_through_the_closures():
    """The library must never capture its own seam references."""
    calls: list[str] = []

    class _Spy:
        def __init__(self, name): self.name = name
        def __call__(self, *a, **k):
            calls.append(self.name)
            return False

    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(watchdog, "dispatcher_running", _Spy("running"))
        mp.setattr(watchdog, "stop_present", _Spy("stopped"))
        mp.setattr(watchdog, "relaunch_dispatcher", _Spy("relaunch"))
        mp.setattr(watchdog, "wlog", _Spy("wlog"))
        watchdog.run_watchdog("cfg.json")
    finally:
        mp.undo()

    # both probes consulted every tick (no short-circuit), relaunch fired once
    # (down + free), and the foundry's own log line was emitted.
    assert calls.count("running") == 1, f"liveness probe calls: {calls}"
    assert calls.count("stopped") == 1, f"stop probe calls: {calls}"
    assert calls.count("relaunch") == 1, f"relaunch calls: {calls}"
    assert calls.count("wlog") == 1, f"log calls: {calls}"


def test_b5_log_line_keeps_the_foundry_format(tmp_path, monkeypatch):
    """DISPATCH_LOG stays the foundry's own presentation, not the library's."""
    lines: list[str] = []
    monkeypatch.setattr(watchdog, "dispatcher_running", lambda *a, **k: False)
    monkeypatch.setattr(watchdog, "stop_present", lambda *a, **k: True)
    monkeypatch.setattr(watchdog, "relaunch_dispatcher", lambda *a, **k: None)
    monkeypatch.setattr(watchdog, "wlog", lambda msg, *a, **k: lines.append(msg))

    watchdog.run_watchdog(tmp_path / "cfg.json", foundry_dir=tmp_path)

    assert len(lines) == 1, f"expected exactly one log line, got {lines!r}"
    msg = lines[0]
    for token in ("running=False", "stopped=True", "relaunch=False"):
        assert token in msg, f"log line lost {token!r}: {msg!r}"


def test_b5_public_surface_unchanged():
    for name in ("decide", "stop_present", "dispatcher_running",
                 "relaunch_dispatcher", "run_watchdog", "main",
                 "wlog", "now", "WatchdogDecision"):
        assert hasattr(watchdog, name), f"watchdog.{name} disappeared"
