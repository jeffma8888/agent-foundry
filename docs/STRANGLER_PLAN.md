# Strangler plan: depend on `resilient-agent-loop-primitives`

Goal: make the extracted library the single source of truth for the three
reliability primitives, and have this platform IMPORT them instead of keeping
inline copies. Behavior-preserving throughout.

## Gate (check this FIRST)

The library repo must be PUBLIC before step 1. This repo is public and has no CI,
so the only consumer is the local `uv run` that every iteration's test command
uses. Declaring a dependency on a PRIVATE repo makes that resolve step require
credentials, which would fail every iteration and stop the loop.

Verify the gate, and STOP if it is not satisfied:

```
gh repo view jeffma8888/resilient-agent-loop-primitives --json visibility -q .visibility
```

Must print `PUBLIC`. If it prints `PRIVATE`, do NOT start; skip this epic and pick
other work. Do NOT work around the gate by vendoring the source, by adding a
filesystem path dependency (it breaks fresh clones and the committed leak guard
rejects home-path prefixes), or by weakening the leak guard.

## Step 1 - declare the dependency (small, do alone)

Add to `pyproject.toml` `[project].dependencies`, pinned to the immutable tag:

```
"resilient-agent-loop-primitives @ git+https://github.com/jeffma8888/resilient-agent-loop-primitives@v0.1.0"
```

The library is stdlib-only, so this adds no transitive weight. Refresh the lock,
then prove `import resilient_agent_loop` works and the full suite is still green.
Ship this ALONE so a resolution problem is isolated from any refactor.

## Library API (v0.1.0, verified signatures)

```
from resilient_agent_loop.scheduler import Scheduler, WorkItem, RoundResult, DriveResult
Scheduler.register(name: str, run: RunFn, priority: int = 100, *, is_retired: RetirePredicate | None = None) -> None
Scheduler.run_round() -> RoundResult
Scheduler.run_until_stopped(*, should_stop: StopPredicate, idle: IdleFn, max_rounds: int | None = None) -> DriveResult

from resilient_agent_loop.runner import run_with_retry, backoff_delay, RunOutcome
run_with_retry(work, *, attempts, is_success, base_delay=0.0, factor=2.0, max_delay=None,
               jitter=None, sleep=time.sleep, timeout=None, call_with_timeout=None) -> RunOutcome

from resilient_agent_loop.watchdog import decide, supervise, Decision, SuperviseResult
decide(*, is_running: bool, stopped: bool) -> Decision
supervise(*, is_running: Probe, is_stopped: Probe, relaunch: RelaunchSeam, log: LogSeam) -> SuperviseResult
```

## Step 2 - `dispatcher.py` delegates scheduling

Replace the hand-rolled priority round-robin with `Scheduler`. Keep dispatcher.py
owning config parsing and all logging; delegate ONLY the scheduling core.

Mapping: priority sort -> `register(..., priority=)`; per-team STOP -> the
`is_retired` predicate (a predicate, so it is re-evaluated every round, which
preserves today's behavior of re-reading the sentinel each round); global STOP ->
`should_stop`; the all-retired idle -> `idle`; per-item crash isolation is already
the library's contract.

Behaviour traps that MUST be preserved (each deserves a test):
1. `--max-shifts` counts SHIFTS (one per item execution) and returns IMMEDIATELY
   mid-round when reached. The library's `max_rounds` caps ROUNDS, which is NOT
   equivalent once more than one team is enabled. Keep the shift counter in the
   dispatcher and stop via `should_stop`; do not silently swap in `max_rounds`.
2. The product config is re-read every round today, so an edited product config is
   picked up without restarting. Load it inside the registered callback, not once
   at registration.
3. Log lines and their ORDER: the "takes the next iteration" line is emitted
   BEFORE the run, the status line after, and the diagnostic progress line after
   that. Keep them inside the callback.
4. A team whose config fails to load is skipped with a logged reason, and one
   team's exception never aborts the round.

## Step 3 - the stage retry path delegates to the runner module

Replace the inline retry/backoff/timeout in the stage runner with
`run_with_retry`. Keep prompt construction and logging here.

Traps:
1. Success is the OUTPUT-FILE predicate, never an exit code: the output file must
   exist AND be non-empty. Pass exactly that as `is_success`.
2. Read the CURRENT base delay, factor and cap out of the existing code and pass
   them through so retry timing is unchanged. Do not adopt the library defaults.
3. Per-attempt timeout maps to `timeout` + `call_with_timeout`; they are
   both-or-neither.

## Step 4 - `watchdog.py` delegates to `decide`/`supervise`

Replace the inline decide/relaunch with the library's. The invariant to preserve:
relaunch only when down AND not deliberately stopped, and never start a second
brain.

## Step 5 - delete the now-dead inline copies

Remove the superseded inline implementations. Confirm `import foundry, dispatcher`
succeeds, the full suite is green, and the ARCHITECTURE invariants still hold.

## Invariant

Each step lands only if the full suite is green and the change is a pure
delegation with no semantic change. If the library is missing something, prefer
extending the LIBRARY over forking behavior back into this repo -- otherwise the
duplication this epic exists to remove simply grows back.
