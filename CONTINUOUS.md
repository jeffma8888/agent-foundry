# The always-on operating contract

agent-foundry is meant to run 24/7 and stop only when told. This file is the
contract that makes "always on" actually survive a real machine.

## The one hard prerequisite: AC power

`caffeinate` can only hold the machine awake on **AC power**. On battery,
macOS runs maintenance-sleep cycles that no `caffeinate` flag can block, and a
sleeping machine stalls every in-flight agent-CLI run ("Connection stalled —
no data received for 120s"). **Unattended runs require AC power and lid open**
(Apple Silicon sleeps on lid-close even on AC unless clamshell + external
display). Nuclear option (needs sudo): `sudo pmset -a disablesleep 1`
(revert with `0`). Both `foundry.py` and `dispatcher.py` already spawn a
`caffeinate -i -s` pinned to their PID — it just needs AC to bite.

## Launch it as a real background task

Launch the dispatcher (or a single `foundry.py run`) as ONE detached background
process so it outlives the launching shell (e.g. `nohup ... &`, or your agent
runner's own background-task mechanism). The process self-daemonizes nothing;
the background job IS the supervisor.

## Stopping is a file, not a signal

- `touch STOP` — the whole company drains: the current stage finishes or is
  abandoned at the next check, and the loop exits cleanly with a final report.
- `touch products/<name>/STOP` — retire just that team; the dispatcher skips it.
- Remove the STOP file(s) before relaunching.

Sentinels are checked between every stage and during every backoff/cooldown
sleep, so a stop takes effect within ~30s, never mid-git-push.

## Crash resilience and resume

- Iteration numbering continues across restarts (scans `state/iter-*`), so a
  relaunch never re-does or clobbers a completed iteration.
- Infra failures (throttle/stall/timeout) are absorbed: 4 attempts/stage with the backoff
  priced per failure kind (`foundry.retry_ladder_lines`, rendered from `retry_delay`) —
  timeout, cli-error: 1 → 2 → 4 min; stalled: 1 → 5 → 20 min; service, other: 10 → 20 → 40 min —
  then a 30m→1h→2h→4h loop-level cooldown. The loop does not die on
  infra problems — only on STOP.
- For extra safety across machine reboots, a `scheduled` watchdog is shipped:
  `watchdog.py` re-launches the dispatcher IFF its process is gone AND no STOP
  file exists (single-brain: never a second dispatcher; STOP-respect: never
  resurrect a deliberately-stopped company). Register it as a sparse schedule,
  e.g. every 10 min via cron:

  ```bash
  */10 * * * * cd /path/to/agent-foundry && uv run python -X utf8 watchdog.py --config foundry.config.json
  ```

  Keep the interval sparse enough that invocations do not overlap (a lock to
  close the two-checks-both-see-down race is a future bite).

## The single-brain rule (repeat, because it bites)

Run **one** foundry brain per model-API account. The dispatcher already
serializes all teams to concurrency 1. Do NOT additionally run a separate
`foundry.py run`, a second dispatcher, or an unrelated continuous agent loop on
the same account — they will starve each other's token budget and all stall.
If a dedicated product loop is already running elsewhere, either let the
dispatcher take over that product (disable the standalone loop) or leave that
product disabled in the dispatcher config.

## Health checks

```bash
pgrep -fl "dispatcher.py|foundry.py"          # is the brain alive?
pmset -g batt | head -1                        # on AC?
tail -5 DISPATCH_LOG.md                         # last shifts
tail -5 products/*/NIGHT_LOG.md                 # per-team heartbeat
```
