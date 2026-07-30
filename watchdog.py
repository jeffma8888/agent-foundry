#!/usr/bin/env python3
"""watchdog.py -- resurrect the single-brain dispatcher after a crash.

The one resilience gap the framework has today: `foundry.py` retries every
stage and `dispatcher.py` serializes every team, but if the DISPATCHER PROCESS
ITSELF dies (crash, OOM, kill, or a machine restart) the whole company stays
down until a human notices -- which defeats the VISION's promise of an
always-on org that runs "indefinitely, until told to stop".

This module is the fix CONTINUOUS.md already prescribes in prose (lines 41-42:
"add a `scheduled` watchdog that re-launches the dispatcher if its PID is gone
and no STOP file exists"; line 57 uses `pgrep -f dispatcher.py` as the liveness
probe). A `scheduled`/cron/launchd job invokes it periodically; on each
invocation it decides -- and only then acts -- whether to re-launch the
dispatcher. It re-launches IFF the dispatcher is NOT already alive AND no global
`STOP` file is present; otherwise it does nothing.

Two safety-critical guards keep that safe, and both are a PURE decision so they
can be pinned by a black-box truth table:
  * single-brain -- never launch a SECOND dispatcher (two brains starve the one
    finite model-API token budget and both stall).
  * STOP-respect -- never resurrect a company the operator deliberately stopped.

It is a brand-new STANDALONE module that nothing imports and that edits neither
`dispatcher.py` nor `foundry.py`: liveness is detected externally by a
`pgrep`-style process scan, exactly like the CONTINUOUS.md health-check. So it
is off the control path entirely -- it cannot regress a running loop, and a
live dispatcher is completely unaffected (it never runs the watchdog).

All I/O sits behind monkeypatchable module-level seams (`_pgrep`, `stop_present`,
`relaunch_dispatcher`, `wlog`) so every behavior is testable OFFLINE with no
real subprocess/pgrep/git/network and no real dispatcher launch -- the same
additive-seam pattern iters 01-05 proved.

Install (an operator step; not shipped as a registered schedule):
    # every 10 min, resurrect the brain if it died and no STOP is set:
    */10 * * * * cd /path/to/agent-foundry && \
        uv run python -X utf8 watchdog.py --config foundry.config.json
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import os
import pathlib
import subprocess
import sys

FOUNDRY = pathlib.Path(__file__).resolve().parent
DISPATCH_LOG = FOUNDRY / "DISPATCH_LOG.md"


def now() -> str:
    """Local timestamp for a `DISPATCH_LOG.md` line (mirrors dispatcher.now)."""
    return dt.datetime.now().strftime("%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- #
# The pure decision core -- single-brain + STOP-respect, no I/O.
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class WatchdogDecision:
    """The outcome of one watchdog check.

    Frozen so a decision can't be mutated after the fact. `.reason` is always a
    non-empty, human-readable string so `DISPATCH_LOG.md` records WHY the
    watchdog acted (or declined to), regardless of the verdict.
    """
    relaunch: bool
    reason: str


def decide(*, is_running: bool, stopped: bool) -> WatchdogDecision:
    """Decide whether to resurrect the dispatcher -- PURE, no I/O.

    The whole safety of the watchdog lives here, pinned by a truth table:
    relaunch IFF the dispatcher is down AND no STOP is present. Liveness is
    checked first so it DOMINATES a stray STOP file (never a second brain even
    if a STOP is also present); a deliberate STOP then blocks resurrection of a
    down company. Keyword-only args make the two booleans impossible to swap at
    a call site.
    """
    if is_running:
        # single-brain: a live dispatcher is the invariant we protect above all.
        return WatchdogDecision(
            False, "dispatcher already alive; single-brain rule holds -- no relaunch")
    if stopped:
        # STOP-respect: down, but the operator asked for down. Leave it down.
        return WatchdogDecision(
            False, "dispatcher down but a global STOP is present; "
                   "honoring the deliberate stop -- no relaunch")
    # the resurrection case: down and nobody asked for down.
    return WatchdogDecision(
        True, "dispatcher down and no STOP present; resurrecting the single brain")


# --------------------------------------------------------------------------- #
# I/O seams -- each monkeypatchable by BARE module name so the orchestrator is
# fully offline-testable (the seam-visibility pattern iters 01-05 proved).
# --------------------------------------------------------------------------- #
def stop_present(foundry_dir: pathlib.Path | str = FOUNDRY) -> bool:
    """True iff the global `STOP` sentinel exists under `foundry_dir`.

    Reuses the exact STOP sentinel the dispatcher honors (`<foundry>/STOP`);
    introduces no new file. Filesystem-only, so the tester drives it with a
    real `tmp_path` -- no monkeypatch needed.
    """
    return (pathlib.Path(foundry_dir) / "STOP").exists()


def _pgrep(pattern: str) -> list[int]:
    """Return PIDs whose full command line matches `pattern` (the scan seam).

    The single process-inspection seam: the tester monkeypatches
    `watchdog._pgrep` to script liveness offline, so the watchdog does zero real
    process scanning in tests. Never raises -- an unavailable/failed `pgrep`
    yields an empty list (treated as "nothing alive"), never a crash.
    """
    try:
        p = subprocess.run(["pgrep", "-f", pattern],
                           capture_output=True, text=True, timeout=15)
        return [int(tok) for tok in p.stdout.split() if tok.strip().isdigit()]
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []


def dispatcher_running(pattern: str = "dispatcher.py") -> bool:
    """True iff a dispatcher process (other than us) is alive.

    Liveness via the `_pgrep` seam, matching CONTINUOUS.md's
    `pgrep -f dispatcher.py` health-check -- no PID-file, so `dispatcher.py` is
    NOT edited. Excludes THIS process's own PID so a watchdog invocation is
    never mistaken for the dispatcher (e.g. if it were itself matched by the
    pattern), which would wrongly suppress a needed resurrection.
    """
    me = os.getpid()
    return any(pid != me for pid in _pgrep(pattern))


def relaunch_dispatcher(config_path: pathlib.Path | str,
                        foundry_dir: pathlib.Path | str = FOUNDRY) -> None:
    """Spawn the dispatcher DETACHED so it outlives this short-lived invocation.

    Uses the canonical launch command (`uv run python -X utf8 dispatcher.py
    --config <config>`). `start_new_session=True` puts the dispatcher in its own
    session/process group so the watchdog process (or its cron/launchd parent)
    exiting cannot reap it; stdio is detached to `/dev/null`. This is
    monkeypatched in every test and NEVER actually executed there.
    """
    subprocess.Popen(
        ["uv", "run", "python", "-X", "utf8", "dispatcher.py",
         "--config", str(config_path)],
        cwd=str(foundry_dir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def wlog(msg: str, log_path: pathlib.Path | str = DISPATCH_LOG) -> None:
    """Best-effort append of one timeline line to `DISPATCH_LOG.md`.

    Writes only to the already-git-ignored `DISPATCH_LOG.md` (no new runtime
    artifact). Deliberately swallows EVERY error: a scheduled watchdog's logging
    must never crash the invocation (e.g. `log_path` unwritable / a directory /
    a bad type), because a failed log line must not stop a needed resurrection.
    """
    try:
        with pathlib.Path(log_path).open("a") as f:
            f.write(f"- `{now()}` [watchdog] {msg}\n")
    except Exception:  # noqa: BLE001 -- logging must never propagate (Behavior 14)
        pass


# --------------------------------------------------------------------------- #
# Orchestration -- one check, seams called by BARE name so they monkeypatch.
# --------------------------------------------------------------------------- #
def run_watchdog(config_path: pathlib.Path | str,
                 foundry_dir: pathlib.Path | str = FOUNDRY) -> WatchdogDecision:
    """Run ONE watchdog check and act on it; return the decision.

    Probes liveness and STOP through the module-level seams (called by bare name
    so `monkeypatch.setattr(watchdog, "<seam>", ...)` takes effect), asks the
    pure `decide` for a verdict, relaunches only when the verdict says so, and
    records the outcome to `DISPATCH_LOG.md`. Forwards `config_path` to the
    relaunch so the resurrected dispatcher runs the same company.
    """
    running = dispatcher_running()
    stopped = stop_present(foundry_dir=foundry_dir)
    decision = decide(is_running=running, stopped=stopped)
    if decision.relaunch:
        relaunch_dispatcher(config_path, foundry_dir=foundry_dir)
    wlog(f"running={running} stopped={stopped} relaunch={decision.relaunch} "
         f"-- {decision.reason}")
    return decision


def main(argv: list[str] | None = None) -> int:
    """CLI entry: run one check, relaunch if warranted, exit 0.

    Designed for a sparse `scheduled`/cron/launchd entry (e.g. every 10 min).
    Returns 0 on a completed check regardless of whether it relaunched -- a
    relaunch is a NORMAL, expected outcome, not an error, so the scheduler never
    sees a spurious failure.
    """
    ap = argparse.ArgumentParser(
        description="agent-foundry dispatcher watchdog (resurrect if down & no STOP)")
    ap.add_argument("--config", default=str(FOUNDRY / "foundry.config.json"),
                    help="dispatcher config to relaunch with")
    ap.add_argument("--foundry-dir", default=str(FOUNDRY),
                    help="foundry root holding the STOP sentinel and dispatcher.py")
    args = ap.parse_args(argv)
    run_watchdog(args.config, foundry_dir=pathlib.Path(args.foundry_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
