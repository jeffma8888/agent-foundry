# Platform Roadmap — how the foundry improves itself

The `_platform` team (highest dispatcher priority) works this list one small,
reversible increment per iteration, keeping `tests/` green. Seeded from the
`ralph` and `ai-brownfield-practices` skills and the repolens build. The PM
re-orders by value each iteration; ship-order is a suggestion, not a contract.

| # | Increment | Why | Done when |
|---|---|---|---|
| 1 | `prd.json`-style machine roadmap per product (id/title/criteria/passes) | Deterministic global stop + progress, vs parsing prose | dispatcher can report "N/M stories pass" via a jq-able file |
| 2 | Consolidate LEARNINGS into a pinned `## Patterns` head section | Iteration agents can't read an ever-growing log; promote general rules | reporter/roles maintain a bounded top section |
| 3 | Emit an `AGENTS.md` into each product repo from its learnings | Fresh agents auto-read house rules; less re-learning | product repo has an up-to-date AGENTS.md |
| 4 | Risk-split the final gate (test-only diff = light gate) | Cut gate latency ~half for coverage-only iterations | gate detects "no src/ change" and runs the light path |
| 5 | Task-size guard: PM must confirm a feature fits <50% context | The 3 engineer timeouts on repolens were oversized-iteration smells | PM spec includes a size self-check field |
| 6 | Mutation-testing gate (mutmut) as a deterministic weak-assertion check | Agents emit assertions that pass without validating behavior | gate can optionally run mutation testing |
| 7 | Per-iteration suite wall-time in the log + auto-parallelize story when slow | Throughput is dominated by verify time, not reasoning | NIGHT_LOG records suite seconds; PM files a speed story past a threshold |
| 8 | `scheduled` watchdog that relaunches the dispatcher if PID gone & no STOP | Survive reboots / crashes truly 24/7 | a documented, tested watchdog exists |
| 9 | `foundry.py doctor` preflight (AC power, agent auth, uv, remote reachable) | Fail fast before burning a shift on a broken env | `doctor` subcommand returns actionable checks |
| 10 | Structured JSON event log alongside the markdown NIGHT_LOG | Machine-readable status for dashboards / the reporter | events.jsonl written per stage |

## Guardrails for self-modification
- Never change iteration numbering, state layout, or the `VERDICT:`/`RESULT:`/
  `ACTION:` sentinel contract without a migration note in this file.
- Every change keeps `uv run --with pytest pytest -q` green and both modules
  importable (`python -c "import foundry, dispatcher"`).
- If an increment would touch a currently-running loop's resume behaviour,
  defer it or gate it behind a version flag.
