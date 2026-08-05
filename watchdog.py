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
import datetime as dt
import os
import pathlib
import subprocess
import sys

# STRANGLER step 4 (docs/STRANGLER_PLAN.md): the resurrect-if-down policy now
# lives in the published library, not inline here. This module keeps what is
# genuinely foundry-specific -- the process-scan / STOP-file / detached-relaunch
# seams and the DISPATCH_LOG line -- and delegates the DECISION and the tick
# ORCHESTRATION. Chosen as the first strangler slice because watchdog.py has
# ZERO non-test importers, so it is off the live dispatch/resume path entirely.
from resilient_agent_loop.watchdog import Decision
from resilient_agent_loop.watchdog import decide as _lib_decide
from resilient_agent_loop.watchdog import supervise as _lib_supervise

FOUNDRY = pathlib.Path(__file__).resolve().parent
DISPATCH_LOG = FOUNDRY / "DISPATCH_LOG.md"


def now() -> str:
    """Local timestamp for a `DISPATCH_LOG.md` line (mirrors dispatcher.now)."""
    return dt.datetime.now().strftime("%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- #
# The pure decision core -- single-brain + STOP-respect, no I/O.
# --------------------------------------------------------------------------- #
#: Historical name for the decision value object, kept as an ALIAS of the
#: library type so existing callers/tests that reference
#: ``watchdog.WatchdogDecision`` keep working while there is exactly ONE
#: definition of the type. Fields are unchanged: ``relaunch`` (bool) and
#: ``reason`` (non-empty str).
WatchdogDecision = Decision


def decide(*, is_running: bool, stopped: bool) -> Decision:
    """Decide whether to resurrect the dispatcher -- PURE, no I/O.

    DELEGATES to the library's ``decide``, which is now the single source of
    truth for the policy. The truth table is unchanged and still the whole
    safety story: relaunch IFF the dispatcher is down AND no STOP is present,
    with liveness checked FIRST so it DOMINATES a stray STOP file (never a
    second brain even if a STOP is also present); a deliberate STOP then blocks
    resurrection of a down company. Keyword-only args make the two booleans
    impossible to swap at a call site.

    Kept as a thin named wrapper rather than a bare re-export so this module's
    documented public surface is stable and a caller can monkeypatch
    ``watchdog.decide`` in isolation. The only observable change from the former
    inline implementation is the ``reason`` WORDING (the library emits short
    machine-friendly codes such as ``already_running`` instead of prose); the
    boolean verdict, field names, and immutability are identical.
    """
    return _lib_decide(is_running=is_running, stopped=stopped)


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
                 foundry_dir: pathlib.Path | str = FOUNDRY) -> Decision:
    """Run ONE watchdog check and act on it; return the decision.

    DELEGATES the tick orchestration (probe both signals -> decide -> relaunch
    only on a resurrect verdict -> log best-effort last) to the library's
    ``supervise``. This module supplies the four foundry-specific seams and
    keeps its own ``DISPATCH_LOG.md`` line format, so behavior is unchanged:
    both signals are probed every tick (no short-circuit), the relaunch fires at
    most once and only in the down-and-free case, and `config_path` is forwarded
    to the relaunch so the resurrected dispatcher runs the same company.

    Every seam is invoked through a closure that resolves the module-level name
    at CALL time, which is what keeps `monkeypatch.setattr(watchdog, "<seam>",
    ...)` effective -- the library never captures a reference of its own. The
    probed booleans are captured on the way through so the log line can still
    report `running=`/`stopped=` alongside the verdict.
    """
    probed: dict[str, bool] = {}

    def _probe_running() -> bool:
        probed["running"] = dispatcher_running()
        return probed["running"]

    def _probe_stopped() -> bool:
        probed["stopped"] = stop_present(foundry_dir=foundry_dir)
        return probed["stopped"]

    def _do_relaunch() -> None:
        relaunch_dispatcher(config_path, foundry_dir=foundry_dir)

    def _report(result) -> None:
        wlog(f"running={probed.get('running')} stopped={probed.get('stopped')} "
             f"relaunch={result.decision.relaunch} -- {result.decision.reason}")

    result = _lib_supervise(is_running=_probe_running,
                            is_stopped=_probe_stopped,
                            relaunch=_do_relaunch,
                            log=_report)
    return result.decision


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
