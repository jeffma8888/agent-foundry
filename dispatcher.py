#!/usr/bin/env python3
"""dispatcher.py -- the single always-on brain of agent-foundry.

The problem it solves: every `agent agent run` draws from ONE finite per-account
model-API token budget. Running several continuous product loops in parallel
starves that budget and they all stall ("Too many tokens" / 120s time-outs).

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

Launch (as ONE backgrounded Bash call, timeout: 0, machine on AC power):
    uv run python -X utf8 dispatcher.py --config foundry.config.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import time

import foundry

FOUNDRY = pathlib.Path(__file__).resolve().parent
DISPATCH_LOG = FOUNDRY / "DISPATCH_LOG.md"
STOP_FILE = FOUNDRY / "STOP"


def now() -> str:
    return dt.datetime.now().strftime("%m-%d %H:%M:%S")


def dlog(msg: str) -> None:
    line = f"- `{now()}` {msg}"
    with DISPATCH_LOG.open("a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def load_dispatch(path: str) -> dict:
    return json.loads(pathlib.Path(path).expanduser().read_text())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="agent-foundry single-brain dispatcher")
    ap.add_argument("--config", default=str(FOUNDRY / "foundry.config.json"))
    ap.add_argument("--max-shifts", type=int, default=0,
                    help="stop after N total shifts (0 = run forever)")
    args = ap.parse_args(argv)

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
    try:
        while not STOP_FILE.exists():
            progressed = False
            for w in items:
                if STOP_FILE.exists():
                    break
                cfg = foundry.load_config(str(
                    pathlib.Path(w["config"].replace("{FOUNDRY}", str(FOUNDRY)))
                    .expanduser()))
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
                if args.max_shifts and shifts >= args.max_shifts:
                    dlog(f"max-shifts {args.max_shifts} reached; stopping")
                    return 0
            if not progressed:
                dlog("all teams retired or stopped; idling 5 min")
                time.sleep(300)
        dlog(f"global STOP honored after {shifts} shifts")
    finally:
        dlog(f"dispatcher down; shifts this session={shifts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
