#!/usr/bin/env python3
"""watchdog.py -- resurrect the single-brain dispatcher after a crash.

The one resilience gap the framework has today: `foundry.py` retries every
stage and `dispatcher.py` serializes every team, but if the DISPATCHER PROCESS
ITSELF dies (crash, OOM, kill, or a machine restart) the whole company stays
down until a human notices -- which defeats the VISION's promise of an
always-on org that runs "indefinitely, until told to stop".

This module is the fix CONTINUOUS.md prescribes in its "extra safety across
machine reboots" bullet: re-launch the dispatcher IFF its process is gone AND no
STOP file exists. That bullet is cited by SECTION, not by line number -- the
line numbers the previous version of this docstring named have since moved, and
the doc's own liveness one-liner is a HAND-RUN health check, not this module's
probe. A `scheduled`/cron/launchd job invokes it periodically; on each
invocation it decides -- and only then acts -- whether to re-launch the
dispatcher. It re-launches IFF the dispatcher is NOT already alive AND no global
`STOP` file is present; otherwise it does nothing.

Two safety-critical guards keep that safe, and both are a PURE decision so they
can be pinned by a black-box truth table:
  * single-brain -- never launch a SECOND dispatcher (two brains starve the one
    finite model-API token budget and both stall).
  * STOP-respect -- never resurrect a company the operator deliberately stopped.

It is a STANDALONE module that nothing imports and that edits neither
`dispatcher.py` nor `foundry.py`. Liveness is still detected EXTERNALLY, but no
longer by a raw SUBSTRING process scan: the seam now runs the shipped
`foundry.py single-brain --json` launch preflight as a SUBPROCESS and reads its
verdict payload, so ONE accurate rule answers "is a brain alive?" for the whole
repo. Measured on this machine with exactly ONE brain alive, the substring scan
this replaces returned THREE pids -- the brain, the brain's own `uv run` launch
WRAPPER, and an unrelated agent process matched on its own PROMPT TEXT (which
merely names the pattern). That is the worst polarity for THIS module: a stray
match reports a brain that is not there and so SUPPRESSES the resurrection this
file exists to perform, on the one path that makes the VISION's "runs
indefinitely" true. `foundry.dispatcher_proc_match` already fixes that (it
requires the row's FIRST token to be a python interpreter AND a later token's
basename to equal the pattern EXACTLY) and is the owner behind `single-brain`.

WHY A SUBPROCESS AND NOT `import foundry`: coupling resurrection to a
23k-line module's import health would mean a `foundry.py` that fails to import
keeps the whole company down -- so the delegation crosses a PROCESS boundary,
exactly as the shipped launcher does it. The preflight is read-only, needs no
`--config` (it is dispatched before the config load, so it also works on a fresh
clone) and costs ~0.2s, which a sparse schedule never notices.

WHY THE PAYLOAD AND NOT THE EXIT CODE: `single-brain` exits 1 for CONFLICT and
ALSO 1 for a crashed interpreter, so the code alone cannot separate "a brain is
alive" from "I could not ask". The 7-key `--json` document can (`unknown` /
`pids`), and it is the published machine contract.

So it is off the control path entirely -- it cannot regress a running loop, and a
live dispatcher is completely unaffected (it never runs the watchdog).

All I/O sits behind monkeypatchable module-level seams (`run_probe`, `_pgrep`,
`stop_present`, `relaunch_dispatcher`, `wlog`) so every behavior is testable
OFFLINE with no real subprocess/process-scan/git/network and no real dispatcher
launch -- the same additive-seam pattern iters 01-05 proved.

Install (an operator step; not shipped as a registered schedule):
    # every 10 min, resurrect the brain if it died and no STOP is set:
    */10 * * * * cd /path/to/agent-foundry && \
        uv run python -X utf8 watchdog.py --config foundry.config.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
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


def single_brain_argv(pattern: str = "dispatcher.py", *,
                      foundry_dir: pathlib.Path | str = FOUNDRY) -> list[str]:
    """Build the argv that asks the shipped preflight whether a brain is alive.

    PURE: pure string/path composition, no filesystem access, no subprocess, and
    it never raises for a `str`/`Path` input -- so the tester can pin the exact
    command this module will run without running anything. Two calls with equal
    arguments return equal lists.

    Shape and WHY each part is there:
      * `sys.executable` -- the SAME interpreter that is running the watchdog, so
        the probe cannot pick a different/absent python than the one that already
        works here (a bare `python3` would).
      * `<foundry_dir>/foundry.py` as an ABSOLUTE path -- so the probe is
        independent of the process's cwd, which a cron/launchd invocation does
        not control.
      * `single-brain --json` -- the read-only launch preflight, asked for its
        MACHINE contract rather than its human report; `--json` is what makes
        `unknown` distinguishable from `conflict` (see the module docstring).
      * `--pattern <pattern>` -- forwards this module's own pattern, so
        `dispatcher_running("other.py")` still asks about `other.py` and the two
        layers can never silently disagree about what a brain is called.
    """
    return [sys.executable,
            str(pathlib.Path(foundry_dir) / "foundry.py"),
            "single-brain", "--json",
            "--pattern", pattern]


def parse_single_brain_pids(payload: str) -> list[int]:
    """Extract the live-dispatcher PIDs from a `single-brain --json` document.

    PURE and TOTAL: every input maps to a `list[int]` and NOTHING raises, because
    a scheduled watchdog must never die on a malformed probe. The empty list is
    the "nothing alive" answer, which preserves this module's existing polarity
    exactly -- `_pgrep` has always degraded to `[]` on any probe failure (see
    `run_probe`), and the decision core then treats that as "down".

    Four guards, each rejecting a payload that cannot honestly report brains:
      * not JSON at all (empty, whitespace, truncated output) -> `[]`;
      * JSON that is not an OBJECT (a bare list/str/number) -> `[]`;
      * an object with NO `unknown` key -- not this contract's document, so its
        `pids` mean nothing here -> `[]`;
      * `unknown` TRUE -> `[]`, including the self-inconsistent
        `{"unknown": true, "pids": [7]}`: a probe that could not run cannot also
        report brains, and believing its pids would fabricate liveness.

    Members of an otherwise valid `pids` list that are not ints are DROPPED
    rather than raised on (one odd member must not blind the whole check).
    `bool` is excluded even though it subclasses `int`: `true` is a JSON boolean
    that got into the wrong field, never a process id.
    """
    try:
        doc = json.loads(payload)
    except (TypeError, ValueError):
        return []
    if not isinstance(doc, dict) or "unknown" not in doc or doc["unknown"]:
        return []
    pids = doc.get("pids")
    if not isinstance(pids, list):
        return []
    return [pid for pid in pids
            if isinstance(pid, int) and not isinstance(pid, bool)]


#: PID of the child `run_probe` most recently SPAWNED, or `None` when this call
#: spawned none. Written ONLY by `run_probe`, and reset to `None` by `_pgrep`
#: both before and after it reads the value, so a value can never be consumed
#: twice or leak between calls. WHY it exists: see `_pgrep`'s "self-match" note
#: -- the probe's own command line necessarily carries `--pattern dispatcher.py`,
#: so the probe is itself a python process holding that exact token and the
#: (correct, exact-basename) `dispatcher_proc_match` rule counts it as a brain.
#: Subtracting it is provably safe: the child was ALIVE during the very scan that
#: produced the pid list, so its pid cannot also belong to a real dispatcher.
#: Single-shot CLI, no threads -- there is no concurrent writer.
_PROBE_PID: int | None = None

#: Outer bound on one probe. The preflight measures ~0.2s and its own process
#: scan already caps at 15s, so this only bounds a wedged interpreter; a hung
#: probe must not pin a scheduled invocation open until the next tick.
PROBE_TIMEOUT = 30.0


def run_probe(argv: list[str]) -> str:
    """Run `argv` and return its STDOUT verbatim -- the single I/O seam.

    The only place this module performs process I/O for liveness, so patching
    `watchdog.run_probe` takes every real subprocess out of the tester's way.

    TOTAL: never raises. A missing/unexecutable binary, a spawn error or a wedged
    child all yield `""`, which `parse_single_brain_pids` maps to "nothing
    alive" -- the polarity this module has always had on a failed probe.

    Reads STDOUT ONLY, deliberately ignoring the exit status: `single-brain`
    exits 1 for CONFLICT, so a NON-ZERO child is the NORMAL case here and its
    payload must still be returned. Stderr is discarded (it is never part of the
    machine contract) rather than merged, so it cannot corrupt the JSON.

    `Popen` rather than `subprocess.run` for ONE reason: the caller needs the
    child's pid (`_PROBE_PID`) to subtract the probe's own self-match.
    """
    global _PROBE_PID
    proc = None
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True)
        _PROBE_PID = proc.pid
        out, _ = proc.communicate(timeout=PROBE_TIMEOUT)
        return out or ""
    except subprocess.TimeoutExpired:
        proc.kill()          # never leave a wedged child holding the pipe open
        proc.communicate()
        return ""
    except (OSError, ValueError):
        return ""


def _pgrep(pattern: str) -> list[int]:
    """Return the PIDs of live dispatcher brains matching `pattern` (scan seam).

    Keeps its HISTORICAL name (and its one-positional-arg / `list` contract) on
    purpose even though it no longer runs a raw substring scan: it is the seam
    two already-frozen test modules monkeypatch by this exact name, and renaming
    it would force edits to files an allow-list brake requires to be unchanged.
    The name is now the only thing left of the old mechanism.

    Composes the three pieces above by BARE module name -- build the argv, run
    the one I/O seam, parse the payload -- so `monkeypatch.setattr(watchdog,
    "run_probe", ...)` bites and the whole path is drivable offline. Never
    raises, because none of the three does.

    SELF-MATCH SUBTRACTION (measured, not theoretical): the argv necessarily
    carries `--pattern <pattern>`, so the probe child is a python process one of
    whose tokens has basename EXACTLY `pattern` -- which is precisely what
    `dispatcher_proc_match` looks for, so the probe reports ITSELF. Measured
    here: the same probe returns `[65827]` without the flag and
    `[<probe pid>, 65827]` with it. Left in, every tick would see a brain and
    `dispatcher_running` would be permanently True -- the exact fail-SHUT this
    iteration removes, made unconditional. So the child's own pid is dropped.
    `_PROBE_PID` is cleared BEFORE the probe, so when `run_probe` is patched (no
    child spawned) the value is `None` and nothing is subtracted.
    """
    global _PROBE_PID
    _PROBE_PID = None
    pids = parse_single_brain_pids(run_probe(single_brain_argv(pattern)))
    probe_pid, _PROBE_PID = _PROBE_PID, None
    return [pid for pid in pids if pid != probe_pid]


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
