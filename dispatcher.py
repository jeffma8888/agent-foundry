#!/usr/bin/env python3
"""dispatcher.py -- the single always-on brain of agent-foundry.

The problem it solves: every agent-CLI run draws from ONE finite per-account
model-API token budget. Running several continuous product loops in parallel
starves that budget and they all stall (rate-limit errors / 120s time-outs).

The dispatcher fixes this by running work items ROUND-ROBIN at global
concurrency 1: exactly one product-team iteration executes at a time, so the
whole quota is always behind a single stream of model calls. It is the
"chief of staff" of a synthetic startup -- it decides which team gets the next
shift, never lets two teams talk to the model at once, and keeps going 24/7
until told to stop.

Work items (see `foundry.config.json`):
  * `_platform`  -- the team that improves agent-foundry ITSELF (highest
                    priority by default: the framework is the compounding asset).
  * one entry per product (e.g. `repolens`).

Each work item points at a `foundry.py` product config. The dispatcher calls
`foundry.run_iteration(cfg)` for one item, then advances to the next enabled
item, forever, until a STOP sentinel appears:
  * `<foundry>/STOP`             -> stop the whole company
  * `<work_root>/STOP`           -> retire one team (dispatcher skips it)

STOP abandons the iteration in flight. To restart the brain WITHOUT losing
work (e.g. to make freshly shipped code live), send a graceful DRAIN instead:
    kill -USR1 <pid>      # pid is on the `drain armed` dispatch-log line
The dispatcher finishes the shift in flight, logs `drain honored after N
shifts` and exits 0 at the next shift boundary; the watchdog (or a fresh
./launch.sh) then brings up a brain running the new code. A drain is a
signal, not a file, because root `.gitignore` is frozen and an unignored
sentinel would ride a ship's `git add -A`. CAVEAT: a dispatcher launched
before this ship has no handler, and SIGUSR1's default action KILLS it
mid-shift -- restart such a brain once with STOP first.

Launch (via launch.sh, which runs preflight before detaching):
    ./launch.sh --config foundry.config.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

import foundry

FOUNDRY = pathlib.Path(__file__).resolve().parent
DISPATCH_LOG = FOUNDRY / "DISPATCH_LOG.md"
STOP_FILE = FOUNDRY / "STOP"
# The graceful-drain signal; None where the platform has no SIGUSR1 (Windows),
# in which case main() installs nothing and STOP remains the only halt.
DRAIN_SIGNAL = getattr(signal, "SIGUSR1", None)
_drain_flag = False


def now() -> str:
    return dt.datetime.now().strftime("%m-%d %H:%M:%S")


def dlog(msg: str) -> None:
    """Append one dispatch-log line. NEVER raises.

    Logging must never be able to kill the always-on brain. The real failure
    this guards against: the dispatcher inherits stdout from whatever session
    launched it, and once that session goes away, writing to the now-dead
    terminal raises OSError(EIO) on macOS. That exception previously escaped
    the main loop and terminated the whole company mid-shift.
    """
    line = f"- `{now()}` {msg}"
    try:
        with DISPATCH_LOG.open("a") as f:
            f.write(line + "\n")
    except OSError:
        pass  # disk / permission trouble must not stop the loop
    try:
        print(line, flush=True)
    except (OSError, ValueError):
        pass  # dead or closed stdout must not stop the loop


def request_drain(signum: int | None = None, frame: object = None) -> None:
    """Signal handler: ask main() to exit at the next shift boundary.

    It only flips a flag -- the shift in flight is never interrupted, which is
    the whole point versus STOP (that abandons the running iteration). Being a
    signal handler, it must do nothing that can raise.
    """
    global _drain_flag
    _drain_flag = True


def drain_requested() -> bool:
    """True once a drain was requested in this main() run."""
    return _drain_flag


def _arm_drain() -> tuple[bool, object]:
    """Install request_drain for DRAIN_SIGNAL; return (armed, previous handler).

    Never raises: signal.signal raises ValueError off the main thread, and a
    missing drain must never stop the company from running.
    """
    if DRAIN_SIGNAL is None:
        return False, None
    try:
        prev = signal.getsignal(DRAIN_SIGNAL)
        signal.signal(DRAIN_SIGNAL, request_drain)
    except (ValueError, OSError, TypeError):
        return False, None
    dlog(f"drain armed: kill -USR1 {os.getpid()}")
    return True, prev


def _disarm_drain(armed: bool, prev: object) -> None:
    """Restore the handler that was in place before _arm_drain. Never raises."""
    if not armed or DRAIN_SIGNAL is None:
        return
    try:
        # getsignal returns None for a handler not installed from Python;
        # signal.signal rejects None, so the closest restorable value is SIG_DFL.
        signal.signal(DRAIN_SIGNAL, signal.SIG_DFL if prev is None else prev)
    except (ValueError, OSError, TypeError):
        pass


def load_dispatch(path: str) -> dict:
    return json.loads(pathlib.Path(path).expanduser().read_text())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="agent-foundry single-brain dispatcher")
    ap.add_argument("--config", default=str(FOUNDRY / "foundry.config.json"))
    ap.add_argument("--max-shifts", type=int, default=0,
                    help="stop after N total shifts (0 = run forever)")
    args = ap.parse_args(argv)
    global _drain_flag
    _drain_flag = False  # a drain is per-run; never inherit a stale request

    if STOP_FILE.exists():
        print("Global STOP present; remove <foundry>/STOP to run.")
        return 1

    conf = load_dispatch(args.config)
    items = [w for w in conf.get("work_items", []) if w.get("enabled", True)]
    if not items:
        print("No enabled work items in config.")
        return 1

    # priority: lower number goes first each round (platform default 0)
    items.sort(key=lambda w: w.get("priority", 100))

    with DISPATCH_LOG.open("a") as f:
        f.write(f"\n## Dispatcher session — started {dt.datetime.now():%Y-%m-%d %H:%M}\n\n")
    # hold the machine awake for the dispatcher's lifetime (AC power required)
    subprocess.Popen(["caffeinate", "-i", "-s", "-w", str(os.getpid())])
    dlog(f"dispatcher up; {len(items)} team(s): "
         f"{', '.join(w['name'] for w in items)}; concurrency=1")

    shifts = 0
    armed, prev_handler = _arm_drain()
    try:
        while not STOP_FILE.exists():
            progressed = False
            for w in items:
                if STOP_FILE.exists():
                    break
                if drain_requested():
                    dlog(f"drain honored after {shifts} shifts")
                    return 0
                # Resolving ONE team's config must never kill the company. A
                # missing / malformed config (or an I/O error reading it) skips
                # just that team for this round instead of propagating out of
                # the main loop, matching the run_iteration guard below.
                try:
                    cfg = foundry.load_config(str(
                        pathlib.Path(w["config"].replace("{FOUNDRY}", str(FOUNDRY)))
                        .expanduser()))
                except Exception as exc:
                    dlog(f"config load failed for {w.get('name', '?')}: "
                         f"{exc!r}; skipping this team")
                    continue
                if cfg.stop_file.exists():
                    continue  # this team is retired
                progressed = True
                shifts += 1
                dlog(f"shift {shifts}: **{cfg.name}** takes the next iteration")
                try:
                    res = foundry.run_iteration(cfg)
                    dlog(f"shift {shifts}: {cfg.name} -> {res.get('status')} "
                         f"(iter {res.get('iteration')})")
                except Exception as exc:  # never let one team kill the company
                    dlog(f"shift {shifts}: {cfg.name} raised {exc!r}; continuing")
                # Diagnostic-only prd progress (item 1, bite 2a): a runtime no-op
                # unless this product has a prd.json. `dispatch_progress_line`
                # never raises and is OFF the control path -- it cannot affect the
                # round-robin order, STOP handling, or res["status"] branching.
                prog = foundry.dispatch_progress_line(cfg)
                if prog:
                    dlog(prog)
                if args.max_shifts and shifts >= args.max_shifts:
                    dlog(f"max-shifts {args.max_shifts} reached; stopping")
                    return 0
            if not progressed:
                dlog("all teams retired or stopped; idling 5 min")
                time.sleep(300)
        dlog(f"global STOP honored after {shifts} shifts")
    finally:
        _disarm_drain(armed, prev_handler)
        dlog(f"dispatcher down; shifts this session={shifts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
