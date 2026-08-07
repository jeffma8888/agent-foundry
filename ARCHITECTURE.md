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
| 0 | Dual PM scouts (OPT-IN: `dual_pm_scouts` in config) | `pm_scout.md` x2 | `pm_scout_a.md` (new-capability lens), `pm_scout_b.md` (hardening/DX lens) | no |
| 1 | PM / TPM (triages the scout slates when present) | `pm.md` | `pm.md` (the spec) | no |
| 2 | Engineer | `engineer.md` | `engineer.md` | no |
| 3 | Reviewer | `reviewer.md` | `reviewer.md` (`VERDICT:` line) | no |
| 3b| Fix (if CHANGES_REQUIRED) | `fix.md` | `fix_review.md` | no |
| 4 | Isolated Tester | `tester.md` | `tester.md` (`RESULT:` line) | no |
| 4b| Fix + re-test (if RED: `RESULT: FAIL`, no checkpoint marker) | `fix.md` + `tester.md` | `fix_tests.md`, `tester2.md` | no |
| 4c| Tester retry x2 max (if UNFINISHED: report carries `PROGRESS: CHECKPOINT`) | `tester.md` | `tester2.md`, `tester3.md` | no |
| 5 | Final Reviewer (gate) | `final.md` | `final.md` (`ACTION:` line) | **YES — only role** |
| 6 | Post-release verify (deterministic; **not** an agent) | — (`postrelease_step`) | `state/iter-NN/postrelease.md` (`POSTRELEASE:` line) | no — read-only clone/verify |
| — | Reporter (every 5 iters) | `reporter.md` | `reporter_done_NN.md` + STATUS_REPORT | no |

The loop reads the `VERDICT:` / `RESULT:` / `ACTION:` sentinel lines to branch,
plus the one mandated marker line `PROGRESS: CHECKPOINT` that distinguishes a
tester round cut short from a genuinely red suite (stage 4b vs 4c); it never
parses free-form prose for control flow.

Stage 6 runs **only after `ACTION: PUSHED`** (the ship branch); it is SKIPPED on a
no-ship iteration. It is a deterministic inline step, not an agent-CLI run
(bite 1 built the whole verify as a mechanical helper, and the quality bar demands
deterministic + offline-testable — an agent stage is neither). It never touches
git write state: its only git is the read-only clone inside `verify_fresh_clone`.

Stage 0 (dual-PM-scout pre-stage, wired 2026-08-04 with operator sign-off) runs
ONLY when a product opts in via `"dual_pm_scouts": true` in its config.json; the
default-off path is byte-identical to the pre-wiring pipeline. Two scouts run
SEQUENTIALLY (single-brain concurrency preserved), each proposing 2-3 candidates
in its assigned lens; they decide nothing. The PM lead then triages the combined
slate and picks exactly ONE feature, justifying it against the strongest
alternative (see `roles/pm.md`). A failed scout maps to the PM-stage infra-fail
idiom -- no revert, since nothing is built yet. Rationale: single-PM discovery
degenerates into shape-clones once a roadmap is exhausted (observed iters
90-101); two decorrelated lenses restore candidate diversity.

As of iter 72 the stage SEQUENCE is manifest-derivable: a product may drop a
`staffing.json` to activate an extra (or reordered) seat, and `run_iteration`
delegates the whole pipeline to the manifest-driven executor
(`run_execution_plan`) ONLY when that manifest is non-default, `lint_manifest`-clean,
and ends on the ship gate. An absent / default-equivalent / lint-dirty /
release-not-last manifest -- i.e. every configured product today -- runs the five
core stages above byte-for-byte, so the default path is unchanged.

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
  sentinel is honored between every stage and during every sleep. An external
  `scheduled` watchdog (`watchdog.py`) closes the one gap this cannot: if the
  dispatcher PROCESS itself dies (crash/OOM/kill/restart), the watchdog
  resurrects it -- but only IFF it is truly down AND no STOP is present, so it
  never violates single-brain (§4) or STOP-respect. It is a standalone module
  off the control path (process-scan liveness, no PID-file, no edit to
  `dispatcher.py`/`foundry.py`).
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
  A pinned `## Patterns` head holds the durable curated rules; `foundry learnings
  --config <cfg> [--recent N]` renders a bounded digest (that head + the N most-recent
  lessons) so a fresh agent reads high-signal history without slurping the whole log.
  That same bounded digest (newest `PROMPT_LEARNINGS_RECENT` lessons) is ALSO inlined
  into EVERY stage prompt by `build_prompt`, so each fresh agent receives it inline —
  not just on demand via the CLI. Because the prompt path pays that cost on every
  stage of every iteration, `build_prompt` — and ONLY `build_prompt` — also bounds the
  digest by CHARACTERS: each lesson line is capped at `PROMPT_LEARNINGS_LESSON_CHARS`
  and the tail admitted newest-first within `PROMPT_LEARNINGS_BUDGET_CHARS`, and the
  pinned head is bounded the same way — each head BULLET BLOCK capped at
  `PROMPT_LEARNINGS_HEAD_BULLET_CHARS` and blocks admitted top-down (so the
  highest-precedence leading rules survive) within `PROMPT_LEARNINGS_HEAD_BUDGET_CHARS`.
  The head was originally exempt from that bound as "curated and small"; it grew to 63%
  of the digest, so the exemption is closed. Any elision emits ONE loud
  `> [head bounded: ...]` notice line, never a silent cut. The `foundry learnings`
  CLI/`--json` view and the `AGENTS.md` renderer pass NONE of these caps, so operator-
  facing renderings still show the head and the lessons in FULL.
- `products/<name>/NIGHT_LOG.md` — the event timeline; `DISPATCH_LOG.md` — shifts.
  The dispatcher also surfaces prd progress ("N/M stories pass") into `DISPATCH_LOG.md`
  per shift for any product that has a `prd.json` (item 1); a no-op until one exists.
- `products/<name>/events.jsonl` — a machine-readable JSONL mirror of the
  NIGHT_LOG timeline (one `{ts, event, ...}` JSON object per line, `ts` is a
  tz-aware UTC ISO-8601 instant). Each record emitted from `log()` also carries a
  semantic `kind` (one of ship / revert / postrelease / timing / backoff / stop /
  lifecycle / fix / iteration / stage / info) derived by the pure
  `classify_event(msg)` (item 10), so the stream is FILTERABLE by event type
  without re-parsing the free-form `msg`; `event` stays `"log"` (backward
  compatible) and historical lines without `kind` remain valid JSON. Written
  best-effort alongside every NIGHT_LOG line; purely diagnostic (never read on a
  control path) and git-ignored.
- Per-ship suite wall-time (item 7): on every genuine ship `postrelease_step`
  records the fresh-clone test-suite seconds — a `fresh-clone suite wall-time:
  N.NNs` line in NIGHT_LOG/events (flagged `SLOW` past `SUITE_SLOW_SECONDS`) and
  a `suite_seconds:` body line in `state/iter-NN/postrelease.md` — so unattended
  throughput is measurable. Diagnostic only, off every control path.
  (item 7 bite 2) When that measured wall-time exceeds `SUITE_SLOW_SECONDS` on a
  genuine ship, `postrelease_step` also raises a per-product advisory
  `SPEED_STORY_NEEDED.md` flag (auto-cleared on the next genuine fast ship) so
  the next single-shot PM sees the throughput signal — ADVISORY / NON-blocking
  and subordinate to `HOTFIX_NEEDED.md`, off every control path.

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
- *iter 12:* the FIRST `dispatcher.py` edit — a per-shift diagnostic
  `foundry.dispatch_progress_line(cfg)` call whose non-`None` result is `dlog`-ged
  (item 1, bite 2a). ADDITIVE and off the control path: it introduces NO sentinel,
  does not touch the round-robin order / STOP handling / `res["status"]` branching /
  iteration numbering / `state/iter-NN` layout, and is a runtime no-op (returns
  `None`) for every product until an operator adds a `prd.json`. So the live loop
  is byte-identical today and resumes cleanly on restart. The automatic global-stop
  half (bite 2b), which WOULD touch loop-termination/resume semantics, is deferred.
- *iter 14:* item 7 bite 2 (COMPLETES item 7) — a new per-product advisory
  `SPEED_STORY_NEEDED.md` flag raised inside `postrelease_step` when a genuine
  ship's measured fresh-clone suite wall-time exceeds `SUITE_SLOW_SECONDS`
  (auto-cleared on the next genuine fast ship), plus an ADVISORY `roles/pm.md`
  duty (0b). ADDITIVE and off the control path: it introduces NO new sentinel,
  its flag write/clear is swallow-wrapped so it never changes the returned
  `PostReleaseResult` / `POSTRELEASE:` sentinel, and it does not touch the
  `VERDICT:`/`RESULT:`/`ACTION:` contract, `res["status"]` branching,
  iteration numbering, or the `state/iter-NN` layout. So a live loop is
  byte-identical today and resumes cleanly on restart — the advisory activates
  only on a clean restart.
- *iter 68:* item 19 bite 2 -- the FIRST `run_iteration` control-flow touch for
  the manifest-driven pipeline. `run_iteration` now READS the product's staffing
  manifest each iteration (`load_staffing_manifest(cfg)` -> `dict | None`,
  resolved to `<work_root>/staffing.json` by default) and derives a stage
  sequence. This bite only DETECTS a non-default team (an extra/reordered seat):
  it logs one diagnostic and still runs the existing fixed pipeline; the
  manifest-driven EXECUTOR is deferred to bite 3. ADDITIVE and a runtime no-op
  for every product today -- an absent OR default-equivalent manifest derives to
  `_default_stage_sequence()`, so the guard changes nothing until an operator
  adds a non-default `staffing.json`. It introduces NO new sentinel and NO new
  state artifact; iteration numbering, the `state/iter-NN` layout, and the
  `VERDICT:`/`RESULT:`/`ACTION:`/`POSTRELEASE:` contract are unchanged, so a live
  loop is byte-identical today and resumes cleanly on restart.

- *iter 72:* item 19 bite 3b-ii (COMPLETES item 19) -- WIRE the manifest-driven
  executor into `run_iteration`. The iter-68 detect-only guard is REPLACED: for a
  NON-default staffing manifest that `lint_manifest`-clean AND whose execution
  plan ENDS on the ship gate, `run_iteration` delegates the whole pipeline to
  `run_execution_plan(cfg, iteration, plan, base)` and returns its result
  verbatim; every other case (absent / default-equivalent / lint-dirty /
  release-not-last -- every configured product today) runs the existing fixed
  pipeline byte-for-byte. DORMANT-UNTIL-DATA and off the real control path today:
  no configured product ships a non-default `staffing.json`, so a live loop is
  byte-identical and resumes cleanly on restart; delegation activates only when an
  operator adds a valid non-default manifest. It introduces NO new sentinel and NO
  new state artifact; iteration numbering, the `state/iter-NN` layout, and the
  `VERDICT:`/`RESULT:`/`ACTION:`/`POSTRELEASE:` contract are unchanged.

## 7. Public-safety: the committed portable leak-guard

This repository is public and the dispatcher auto-pushes on every ship with no
human in the review loop, so a drifted iteration could reintroduce an internal
or personal token into a public commit. Two committed, portable, standalone
scripts guard against that, both OFF the pipeline control path (nothing imports
them, so `foundry.py` / `dispatcher.py` / `roles/` are untouched):

- `scripts/leak_guard.py` (+ a base64-encoded `scripts/leak_denylist.txt`) scans
  a git tree or an explicit file list against the denylist and exits non-zero on
  any hit (item 16 bites 1–2).
- `scripts/install_hooks.sh` arms that guard as a `.git/hooks/pre-push` hook in
  one command (`sh scripts/install_hooks.sh`) — git does NOT clone hooks, so
  each fresh checkout must arm it. Idempotent; a foreign existing hook is backed
  up first; the armed hook fails CLOSED on a finding/error and OPEN only if the
  guard script is entirely absent (item 16 bite 2b).

The armed hook blocks a leaky push locally. The **hard in-loop final-gate
pre-push check** — the `final` role running the scanner (`python3 <repo>/scripts/leak_guard.py --ref HEAD --repo <repo>`) after the commit and
before the push, so the loop self-blocks a leaky ship even without a hook — is now
**WIRED** into `roles/final.md` as a repo-agnostic gate step: it is skipped when the
product repo lacks the scanner, and a non-zero exit fails CLOSED to the revert path.
This is the belt-and-suspenders second block; the installed git `pre-push` hook is the
primary. This completes roadmap item 16 (bite 3 of 3).
