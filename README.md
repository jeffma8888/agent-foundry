# agent-foundry

**An always-on autonomous product org.** Point it at any git repo and a team of
AI agents — a TPM, two engineers, an isolated QA engineer, and an independent
release gate — builds it feature by feature, around the clock, shipping only
work that passes every gate.

> The foundry pours raw ideas in and casts working software out.
> Its first artifact is **[repolens](https://github.com/jeffma8888/repolens)** —
> a repo-analysis CLI it built and shipped 9 features for, overnight, unattended.

## The org chart

```
                 ┌─────────────┐
                 │  Dispatcher │  the always-on "chief of staff":
                 │ (single brain)│  round-robins one team at a time so they
                 └──────┬──────┘  never split the model-token budget
          ┌────────────┼────────────┐
   ┌──────▼─────┐              ┌─────▼──────┐
   │  Platform  │              │  Product   │   (repolens, and any repo you add)
   │    team    │              │   team(s)  │
   │ improves   │              └─────┬──────┘
   │ the foundry│                    │
   └────────────┘         per iteration, one small feature:
                          PM → Engineer → Reviewer → [Fix]
                              → Isolated Tester → [Fix → Tester]
                              → Final Reviewer (ships or reverts)
```

Each stage is a **fresh** agent-CLI run (clean context, no memory bloat).
The only memory between stages/iterations lives on disk: the spec, the diff,
the commit history, and the learnings log.

## Why it works — five hard-won invariants

1. **Trust artifacts, not claims.** A stage succeeds only if its output file
   exists and is non-empty. Exit codes and agent self-reports are ignored.
2. **The gate is independent and pessimistic.** The Final Reviewer re-runs the
   full test suite itself and is the *only* role allowed to touch git. On any
   doubt it reverts to `origin/<branch>` rather than ship half-done work.
3. **QA is firewalled.** The Tester may not read `src/` — only the spec and the
   product's observable behavior. Black-box tests can't "test to the code," so
   they catch what the author and reviewer both missed.
4. **Anti-delegation, everywhere.** Every role prompt forbids nested agent runs
   / re-delegation, so sub-agents do the work instead of spawning more loops.
5. **Infra failures never kill the loop.** Throttling, stalls, and 600s timeouts
   are absorbed by per-stage retry + exponential backoff and an infra-cooldown;
   the loop runs until you tell it to stop.

## Quickstart

```bash
# 0. Preflight the box before committing a shift (AC power, agent CLI, uv, remote):
uv run python foundry.py doctor --config products/repolens/config.json

# 1. Run one product team on an existing repo, a single iteration:
uv run python foundry.py once --config products/repolens/config.json

# 2. Run one product team continuously (until you `touch STOP`):
uv run python foundry.py run  --config products/repolens/config.json

# 3. Run the whole company (platform + all products) as one quota-safe brain:
cp foundry.config.example.json foundry.config.json      # edit enabled/priority
uv run python dispatcher.py --config foundry.config.json
#    (the dispatcher logs "N/M stories pass" into DISPATCH_LOG.md each shift for
#     any product that has a prd.json; a no-op for products without one.)

# 4. Read the bounded learnings digest (pinned `## Patterns` head + recent tail):
uv run python foundry.py learnings --config products/repolens/config.json  # [--recent N]

# 5. Emit an AGENTS.md house-rules file into the product repo from its learnings:
uv run python foundry.py agents --config products/repolens/config.json  # [--recent N] [--print]

# 6. Lint a PM spec for completeness + size before an iteration (exit 1 = REVIEW):
uv run python foundry.py lint-spec --file products/repolens/state/iter-NN/pm.md

# 7. Report "N/M stories pass" from a product prd.json (exit 0 complete/1 incomplete/2 missing|invalid):
uv run python foundry.py prd --config products/repolens/config.json

# 8. Classify a diff's scope (coverage-only "light" vs "full"); DORMANT — the gate does not consult it yet:
uv run python foundry.py gate-scope --config products/repolens/config.json  # [--base REF] [--files path ...]

# 9. Company-health probe: latest iter + last ship's POSTRELEASE verdict + the HOTFIX/SPEED flags + prd (exit 0 healthy/1 attention/2 nothing shipped):
uv run python foundry.py status --config products/repolens/config.json

# 10. Multi-iteration ship ledger: each iteration's ACTION + POSTRELEASE outcome, ascending, + a rollup (exit 0 has-history/2 nothing shipped); read-only:
uv run python foundry.py history --config products/repolens/config.json  # [--limit N]
```

Stop any time: `touch STOP` (whole company) or `touch products/<name>/STOP`
(retire one team). See **[USAGE.md](USAGE.md)** for pointing it at a brand-new
idea or an existing project, and **[CONTINUOUS.md](CONTINUOUS.md)** for the
always-on operating contract (AC power, the single-brain rule, the STOP files).

## Repo map

| Path | What |
|---|---|
| `foundry.py` | Runs ONE product team's loop on any repo (via a JSON config). |
| `dispatcher.py` | The single-brain scheduler across many teams (concurrency 1). |
| `watchdog.py` | A `scheduled`/cron probe that resurrects the dispatcher if its process died and no STOP is set (single-brain + STOP-respecting). |
| `roles/` | The 7 project-agnostic role playbooks (pm, engineer, reviewer, tester, fix, final, reporter). |
| `products/<name>/config.json` | One product's wiring (repo, vision, roadmap, quality bar, push target). |
| `foundry.config.example.json` | The dispatcher's work-item list. |
| `tests/` | The framework's own test suite (the platform team's feedback loop). |
| `ARCHITECTURE.md` / `USAGE.md` / `CONTINUOUS.md` | Design, recipes, operating contract. |
| `docs/artifacts.md` | Catalog of products the foundry has produced. |

## Requirements

- An agent CLI on PATH, configured via `FOUNDRY_AGENT_BIN` / `FOUNDRY_AGENT_ARGS`.
- `uv` (Python ≥3.12). No runtime dependencies; `pytest` for the framework's own tests.
- **AC power** for unattended runs (battery maintenance-sleep kills long loops).

## Status

v0.1 — extracted and generalized from the `repolens` build (10 iterations, 9
features shipped overnight, 590 tests, one deadline-triggered auto-revert).
The platform team now improves the foundry itself; see `PLATFORM_ROADMAP.md`.
