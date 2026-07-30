# Architecture

agent-foundry is a **synthetic startup**: a dispatcher (chief of staff), a
platform team that improves the company's tooling, and product teams that ship
software. This document is the source of truth for the design invariants; the
platform team must preserve them.

## 1. The three layers

```
L2  Dispatcher (dispatcher.py) ── decides which team works next; concurrency 1
L1  Product team loop (foundry.run_iteration) ── one small feature, fully gated
L0  Stage runner (foundry.run_stage) ── one fresh agent-CLI run + retry/backoff
```

This mirrors a proven autonomy stack
(discovery → goal loop → resilient execution); here it is packaged as a
reusable, repo-agnostic org.

## 2. The product pipeline (one iteration)

| # | Stage | Role file | Output file (success = it exists) | Can touch git? |
|---|---|---|---|---|
| 1 | PM / TPM | `pm.md` | `pm.md` (the spec) | no |
| 2 | Engineer | `engineer.md` | `engineer.md` | no |
| 3 | Reviewer | `reviewer.md` | `reviewer.md` (`VERDICT:` line) | no |
| 3b| Fix (if CHANGES_REQUIRED) | `fix.md` | `fix_review.md` | no |
| 4 | Isolated Tester | `tester.md` | `tester.md` (`RESULT:` line) | no |
| 4b| Fix + re-test (if FAIL) | `fix.md` + `tester.md` | `fix_tests.md`, `tester2.md` | no |
| 5 | Final Reviewer (gate) | `final.md` | `final.md` (`ACTION:` line) | **YES — only role** |
| 6 | Post-release verify (deterministic; **not** an agent) | — (`postrelease_step`) | `state/iter-NN/postrelease.md` (`POSTRELEASE:` line) | no — read-only clone/verify |
| — | Reporter (every 5 iters) | `reporter.md` | `reporter_done_NN.md` + STATUS_REPORT | no |

The loop reads the `VERDICT:` / `RESULT:` / `ACTION:` sentinel lines to branch;
it never parses free-form prose for control flow.

Stage 6 runs **only after `ACTION: PUSHED`** (the ship branch); it is SKIPPED on a
no-ship iteration. It is a deterministic inline step, not an agent-CLI run
(bite 1 built the whole verify as a mechanical helper, and the quality bar demands
deterministic + offline-testable — an agent stage is neither). It never touches
git write state: its only git is the read-only clone inside `verify_fresh_clone`.

## 3. Invariants (do not regress these)

- **Output-file success.** `run_stage` returns success iff the named output file
  exists and is non-empty. Rationale: agents (and processes) report success
  unreliably; a written artifact is the only trustworthy signal.
- **Independent, pessimistic gate.** The Final Reviewer re-runs the full suite,
  checks the working tree is clean of stray files, and is the sole git-writer.
  Ship requires `ACTION: PUSHED <sha>` AND a changed remote head; otherwise the
  loop reverts to `origin/<branch>`. **Post-release re-verification:** after a
  ship, `postrelease_step` re-verifies the *pushed* commit from a throwaway
  fresh clone (clone → setup → test → sha-match → optional smoke) and emits
  `POSTRELEASE: HEALTHY|BROKEN`. This closes the gap the gate cannot: it proves
  the release is deployable from a clean checkout, not just that the working tree
  was green (catches a file never `git add`-ed, lockfile drift, dev-tree-only
  imports). A BROKEN result NEVER reverts or force-pushes the public commit — it
  raises a per-product `HOTFIX_NEEDED.md` flag that the next PM must clear by
  fixing forward; a transient network-boundary failure is treated as infra
  (skipped, HEALTHY) and never raises a false hotfix.
- **Tester isolation.** The Tester may read the spec, README, roadmap, `tests/`,
  and the product's observable output — never `src/`, notes, or diffs. Its tests
  encode the spec, not the implementation.
- **Anti-delegation clause** is appended to every stage prompt (see
  `foundry.ANTI_DELEGATION`). Without it a general-purpose sub-agent inherits the
  heavy-work gate and recursively launches another runner instead of working.
- **Resilience.** Per stage: up to 4 attempts, backoff 10→20→40 min. Per loop:
  after 2 consecutive infra-failing iterations, cool down 30m→1h→2h→4h. A STOP
  sentinel is honored between every stage and during every sleep.
- **Iteration numbering** continues across restarts by scanning `state/iter-*`.

## 4. The single-brain rule (why the dispatcher exists)

Every agent-CLI run draws from ONE finite per-account model-API token budget.
Two continuous loops in parallel starve it and both stall ("Too many tokens" /
120s time-to-first-token). The dispatcher therefore runs **exactly one team
iteration at a time**, round-robin by priority, so the entire budget always
backs a single stream of model calls. Adding teams slows each team's cadence;
it never causes mutual starvation. **Never run two foundry loops (or a foundry
loop plus another continuous agent loop) against the same account concurrently.**

## 5. Memory model

Nothing is remembered in-context across stages. Durable memory is:
- `products/<name>/state/iter-NN/*` — every stage's inputs/outputs/logs.
- the product repo's git history + README + roadmap file.
- `products/<name>/LEARNINGS.md` — role-tagged lessons (`- [PM iterNN] ...`).
- `products/<name>/NIGHT_LOG.md` — the event timeline; `DISPATCH_LOG.md` — shifts.

## 6. Extending the foundry (platform team's charter)

Small, safe, reversible increments that keep `tests/` green and keep
`foundry.py` / `dispatcher.py` importable. Candidate work lives in
`PLATFORM_ROADMAP.md`. Never change a running loop's resume semantics
(iteration numbering, state layout, sentinel lines) without a migration note.

**Migration notes**
- *iter 03:* new diagnostic sentinel `POSTRELEASE: HEALTHY|BROKEN` (written to
  `state/iter-NN/postrelease.md`) and a new per-product `HOTFIX_NEEDED.md` flag.
  Both are ADDITIVE and off the control path — `run_iteration`/`run_continuous`
  still branch only on `VERDICT:`/`RESULT:`/`ACTION:` and `res["status"]`
  ∈ {shipped, no-ship, infra-fail, stopped}; `POSTRELEASE:` rides along as an
  additive `res["postrelease"]` key. Iteration numbering and `state/iter-NN`
  layout are unchanged, so a live loop resumes cleanly on restart.
