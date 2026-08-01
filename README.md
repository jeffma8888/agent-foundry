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
uv run python foundry.py status --config products/repolens/config.json  # [--json for one machine-readable snapshot: dashboards/alerts; same 0/1/2 exit code]

# 10. Multi-iteration ship ledger: each iteration's ACTION + POSTRELEASE outcome, ascending, + a rollup (exit 0 has-history/2 nothing shipped); read-only:
uv run python foundry.py history --config products/repolens/config.json  # [--limit N] [--json for one machine-readable ledger doc: dashboards/reporter; same 0/2 exit code, honours --limit]

# 11. Per-iteration suite wall-time digest: each iter's fresh-clone suite seconds + a min/max/avg/last + slow-count rollup (exit 0 has-measured-timings/2 none measured); read-only:
uv run python foundry.py timing --config products/repolens/config.json  # [--limit N] [--json for one machine-readable digest doc: dashboards/reporter; same 0/2 exit code, honours --limit]

# 12. Scan test files for assertion-free `test*` functions (a test that passes without validating anything = false green); DORMANT -- the pipeline/gate never consults it (exit 0 clean/1 weak-or-unparseable/2 nothing to scan); read-only:
uv run python foundry.py weak-tests --config products/repolens/config.json  # [--files path ...] to scan exactly those files instead of walking the repo [--json for one machine-readable scan doc: dashboards/reporter/CI; same 0/1/2 exit code, honours --files]

# 13. Launch preflight: refuse to start a SECOND brain -- report whether a dispatcher is ALREADY running before you launch (exit 0 SAFE/1 CONFLICT/2 UNKNOWN); needs NO --config, read-only, writes nothing:
uv run python foundry.py single-brain  # [--pattern P] process-command pattern to scan for (default 'dispatcher.py'); gate a launch on `[ $? -eq 0 ]` [--json for one machine-readable verdict doc: launch-wrapper/CI; same 0/1/2 exit code]

# 14. Digest a product's typed events.jsonl: filter by kind, tail the most-recent N, count by kind (exit 0 something-shown/2 nothing shown); DORMANT -- the pipeline/dispatcher never call it, writes nothing; read-only:
uv run python foundry.py events --config products/repolens/config.json  # [--kind K] exact-match filter [--limit N] tail most-recent N [--json for one machine-readable digest doc: dashboards/reporter; same 0/2 exit code, honours --kind/--limit]

# 15. Composite LAUNCH gate: fold the env preflight (#0 doctor) AND the single-brain scan (#13) into ONE three-way GO / NO-GO / CAUTION verdict before starting the dispatcher (exit 0 GO / 1 NO-GO / 2 CAUTION); read-only, writes nothing, report-only (the operator decides):
uv run python foundry.py preflight --config products/repolens/config.json  # [--pattern P] process-command pattern to scan for a running dispatcher (default 'dispatcher.py'); a confirmed env blocker or a rival brain is NO-GO(1), an uncheckable scan on a ready env is CAUTION(2); gate a launch on `[ $? -eq 0 ]` [--json for one machine-readable composite verdict doc: launch-wrapper/CI; same 0/1/2 exit code]

# 16. Company-wide health roll-up (#9 status across the WHOLE company): read the DISPATCH config and roll every ENABLED product team's iter-16 `status` into ONE company verdict + a scriptable exit code (0 healthy / 1 needs-attention / 2 no-enabled-products); read-only, writes nothing:
uv run python foundry.py company-status  # --config points at the DISPATCH config (foundry.config.json), NOT a product config (default: the repo's foundry.config.json); a disabled work item is never loaded; one bad team is recorded and the roll-up continues [--json for one machine-readable company roll-up doc: dashboards/cron; same 0/1/2 exit code]

# 17. Company-wide ship-ledger roll-up (#10 history across the WHOLE company -- the TREND complement to #16): read the DISPATCH config and sum every ENABLED product team's iter-10 `history` ledger into ONE company total/shipped/reverted/broken + a per-product breakdown + a scriptable exit code (0 OK / 1 a team errored / 2 no-enabled-products); read-only, writes nothing:
uv run python foundry.py company-history  # --config points at the DISPATCH config (foundry.config.json), NOT a product config (default: the repo's foundry.config.json); a disabled work item is never loaded; one bad team is recorded and the roll-up continues; a past BROKEN in a team's ledger is informational and never gates [--limit N per team] [--json for one machine-readable company ledger doc: dashboards/cron; same 0/1/2 exit code, honours --limit]

# 18. Company-wide suite-wall-time roll-up (#11 timing across the WHOLE company -- the THROUGHPUT complement to #16/#17): read the DISPATCH config and fold every ENABLED product team's iter-11 `timing` digest into ONE company measured/total + pooled min/max/avg + summed slow-count + a per-product breakdown + a scriptable exit code (0 OK / 1 a team errored / 2 no-enabled-products); read-only, writes nothing:
uv run python foundry.py company-timing  # --config points at the DISPATCH config (foundry.config.json), NOT a product config (default: the repo's foundry.config.json); a disabled work item is never loaded; one bad team is recorded and the roll-up continues; a slow-but-fixed suite is informational and never gates [--limit N per team] [--json for one machine-readable company timing doc: dashboards/cron; same 0/1/2 exit code, honours --limit]

# 19. Company-wide weak-test roll-up (#6 weak-tests across the WHOLE company -- the QUALITY complement to #16/#17/#18): read the DISPATCH config and fold every ENABLED product team's iter-6 `weak-tests` scan into ONE company files-scanned/assertion-free-tests/parse-errors total + a per-product breakdown + a scriptable exit code; UNLIKE informational history/timing it GATES on findings (0 clean / 1 a worthless test OR an unparseable file OR a team errored ANYWHERE / 2 no-enabled-products); read-only, writes nothing:
uv run python foundry.py company-weak-tests  # --config points at the DISPATCH config (foundry.config.json), NOT a product config (default: the repo's foundry.config.json); a disabled work item is never loaded; one bad team is recorded and the roll-up continues; a worthless test anywhere gates the company (exit 1) [--json for one machine-readable company weak-test doc: dashboards/cron; same 0/1/2 exit code]

# 20. Company-wide event roll-up (#14 events across the WHOLE company -- the ACTIVITY complement to #16/#17/#18/#19; the 5th and LAST company-* member): read the DISPATCH config and fold every ENABLED product team's iter-14 `events` digest into ONE company total/matched/shown/malformed + a merged per-kind tally + a per-product breakdown + a scriptable exit code; INFORMATIONAL like history/timing -- a malformed line or a quiet team never gates (0 gathered-no-errors / 1 a team errored / 2 no-enabled-products); read-only, writes nothing:
uv run python foundry.py company-events  # --config points at the DISPATCH config (foundry.config.json), NOT a product config (default: the repo's foundry.config.json); a disabled work item is never loaded; one bad team is recorded and the roll-up continues; a malformed line or a quiet team is informational and never gates [--kind K exact-match filter per team] [--limit N tail most-recent N per team] [--json for one machine-readable company events doc: dashboards/cron; same 0/1/2 exit code, honours --kind/--limit]

# 21. Scan test files for `test*` functions whose ONLY assertion is a constant/tautological assert (`assert True`, `assert 1`, `assert "x"`) -- a false green that #12 `weak-tests` structurally MISSES (a constant assert CARRIES an assert node, so it reads as a signal); the first call site of the iter-47 `find_constant_assert_tests` detector, DISJOINT from #12 by construction. DORMANT -- the pipeline/gate never consults it (exit 0 clean/1 constant-assert-or-unparseable/2 nothing to scan); read-only:
uv run python foundry.py constant-asserts --config products/repolens/config.json  # [--files path ...] to scan exactly those files instead of walking the repo [--json for one machine-readable scan doc: dashboards/reporter/CI; same 0/1/2 exit code, honours --files]

# 22. Company-wide constant-assert roll-up (#21 constant-asserts across the WHOLE company -- the QUALITY complement to #19; the 6th and LAST company-* member): read the DISPATCH config and fold every ENABLED product team's iter-21 `constant-asserts` scan into ONE company files-scanned/constant-assert-tests/parse-errors total + a per-product breakdown + a scriptable exit code; UNLIKE informational history/timing/events it GATES on findings (0 clean / 1 a constant-assert test OR an unparseable file OR a team errored ANYWHERE / 2 no-enabled-products); read-only, writes nothing:
uv run python foundry.py company-constant-asserts  # --config points at the DISPATCH config (foundry.config.json), NOT a product config (default: the repo's foundry.config.json); a disabled work item is never loaded; one bad team is recorded and the roll-up continues; a constant-assert test anywhere gates the company (exit 1) [--json for one machine-readable company constant-assert doc: dashboards/cron; same 0/1/2 exit code]

# 23. Scan test files for `test*` functions that are UNCONDITIONALLY skipped (`@pytest.mark.skip`, `@unittest.skip`, a constant-condition `@skipif(True)`/`@skipUnless(False)`) -- a test that NEVER runs, validates nothing, yet reports the suite green, and no gate catches it (the #11 fresh-clone re-run passes a skipped test too); the first call site of the iter-55 `find_always_skipped_tests` detector, a THIRD complementary lens to #12/#21 that can OVERLAP them (a skipped test may also be assertion-free) by catching a DIFFERENT antipattern -- a test that never runs at all. DORMANT -- the pipeline/gate never consults it (exit 0 clean/1 always-skipped-or-unparseable/2 nothing to scan); read-only:
uv run python foundry.py skipped-tests --config products/repolens/config.json  # [--files path ...] to scan exactly those files instead of walking the repo [--json for one machine-readable scan doc: dashboards/reporter/CI; same 0/1/2 exit code, honours --files]
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
| `scripts/leak_guard.py` | Committed, portable leak-guard: scan a git tree or file list against a base64-encoded denylist and exit non-zero on any leaked token. Runnable — `python3 scripts/leak_guard.py --ref HEAD` (scans `HEAD` by default) or `--files <path>...`. A standalone script off the pipeline control path (nothing imports it). |
| `scripts/install_hooks.sh` | One-command installer that arms the committed leak-guard as a git `pre-push` hook (git does NOT clone hooks). Idempotent; backs up a foreign existing hook to `pre-push.backup` first. Run `sh scripts/install_hooks.sh` once per fresh clone. A standalone script off the pipeline control path (nothing imports it). |
| `roles/` | The 7 project-agnostic role playbooks (pm, engineer, reviewer, tester, fix, final, reporter). |
| `products/<name>/config.json` | One product's wiring (repo, vision, roadmap, quality bar, push target). |
| `foundry.config.example.json` | The dispatcher's work-item list. |
| `tests/` | The framework's own test suite (the platform team's feedback loop). |
| `ARCHITECTURE.md` / `USAGE.md` / `CONTINUOUS.md` | Design, recipes, operating contract. |
| `docs/artifacts.md` | Catalog of products the foundry has produced. |

## Public-safety: arm the leak-guard on a fresh clone

This repo is public and the dispatcher auto-pushes on every ship, so a
committed, portable leak-guard (`scripts/leak_guard.py` + a base64
`scripts/leak_denylist.txt`) scans each pushed commit tree for internal or
personal tokens. Git does **not** clone hooks, so arm it once per checkout with
one command:

```bash
sh scripts/install_hooks.sh   # arms .git/hooks/pre-push to run the committed guard
```

Idempotent (safe to re-run); a foreign existing `pre-push` hook is backed up to
`pre-push.backup` first. The hard in-loop final-gate pre-push check (the `final`
role runs the same guard against the pushed commit, so the loop self-blocks a leaky
ship even without the hook) is now wired into the final gate (roadmap item 16 bite 3,
complete). It is repo-agnostic (skipped for a product repo that does not carry the
guard) and fails closed to the revert path on any non-zero exit.

## Requirements

- An agent CLI on PATH, configured via `FOUNDRY_AGENT_BIN` / `FOUNDRY_AGENT_ARGS`.
- `uv` (Python ≥3.12). No runtime dependencies; `pytest` for the framework's own tests.
- **AC power** for unattended runs (battery maintenance-sleep kills long loops).

## Status

v0.1 — extracted and generalized from the `repolens` build (10 iterations, 9
features shipped overnight, 590 tests, one deadline-triggered auto-revert).
The platform team now improves the foundry itself; see `PLATFORM_ROADMAP.md`.
