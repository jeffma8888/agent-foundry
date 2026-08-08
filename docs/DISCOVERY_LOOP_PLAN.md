# Continuous discovery loop — operator-approved plan (2026-08-03)

Audience: the `_platform` PM. This document is an OPERATOR DIRECTIVE. It outranks
the roadmap's ordering for the next few iterations. Ship the bites below in order.

## STATUS -- every bite below has SHIPPED (verified 2026-08-08, iteration 136)

READ THIS FIRST. Sections 2-8 are preserved verbatim as the historical record of
what was asked for and why, but their PRESENT-TENSE claims are now FALSE and this
document no longer directs any work. Concretely: section 2's "the dual-PM-scout
machinery is complete and DORMANT" and "`scout_phase_outcome` has ZERO callers in
`run_iteration`" were true on 2026-08-03 and are wrong today, and section 8's
embargo has had its release condition met since roughly iteration 113.

Each line below names the SYMBOL first and the line number second: the symbol is
the authoritative anchor (`rg -n "<symbol>" foundry.py`), the line number is a
convenience that drifts with every edit to `foundry.py`.

- Bite 1 (wire the scout pre-phase) -- **SHIPPED**. `run_iteration` calls
  `scout_phase_outcome(cfg, iteration, "pm_scout.md", ...)` immediately before the
  `pm` stage: `foundry.py:13086`. Every iteration's `pm_scout_a.md` /
  `pm_scout_b.md` state files are the running proof.
- Bite 2 (widen and ROTATE the lens pool) -- **SHIPPED**. The six-lens pool is
  `PM_SCOUT_LENS_POOL` (`foundry.py:5239`); the deterministic, iteration-seeded
  2-of-6 rotation is `select_scout_lenses(iteration)` (`foundry.py:5249`), supplied
  at the single call site `foundry.py:13087`. Iteration 133 additionally put a
  suite brake on pool/card drift.
- Bite 3 (`novelty-check`, the repetition brake) -- **SHIPPED**, including the
  WIRING that made it a brake rather than a read-only verb. CLI:
  `novelty_check_cli` (`foundry.py:8344`). Wiring: `pm_novelty_block`
  (`foundry.py:8384`) is inlined into the PM stage prompt by `build_prompt`
  (`foundry.py:12829`) and consumed by the card at `roles/pm.md:91`. Note for the
  record: this document's own evidence line "`rg novelty roles/` finds NOTHING"
  was a CASE-SENSITIVITY false negative -- the card says `NOVELTY CHECK`.
- Bite 4 (`DIRECTIONS.md`, the human-readable digest) -- **SHIPPED**.
  `refresh_directions_file(cfg)` (`foundry.py:9232`) regenerates the tracked
  `DIRECTIONS.md` from `gather_directions` + `render_directions_doc`, called from
  `run_iteration` on a scouted iteration only (`foundry.py:13178`).
- Bite 5 (the strangler epic) -- still OPEN and still the highest-VALUE item; it
  was never gated on bites 1-4. It lives on `PLATFORM_ROADMAP.md`; follow
  `docs/STRANGLER_PLAN.md`.
- Section 8's embargo ("do not ship another `--json` flag or another `company-*`
  clone until bites 1-4 are done") -- **SATISFIED**. Its release condition was met
  when bites 1-4 landed; it constrains nothing now. The roadmap's ordering is
  authoritative again, and a PM should not cite this document as outranking it.

## 1. Why this exists (the observed failure)

Iterations 90-101 shipped TWELVE consecutive `<command> --json` increments
(scout-plan, gate-verdict, gate-precheck, role-model, product-gate, prd,
lint-spec, gate-scope, learnings, agents, outcomes). Iterations 102 and 103 then
picked `company-outcomes`, which the PM's own lesson describes as "a DIRECT
STRUCTURAL CLONE of the shipped company-history".

Every one of those iterations was correct: tests green, reviewer APPROVE, gate
shipped. That is the point. The pipeline measures whether work is CORRECT and
never whether it is WORTH DOING. With an exhausted roadmap, the lowest-risk pick
that still passes the size self-check is always a clone of the previous shape, so
the loop converges on producing near-zero marginal value at full throughput.

This is a DISCOVERY failure, not an execution failure. Do not fix it by trying
harder inside the current pipeline. Fix it by giving the loop a discovery phase
and a repetition brake.

## 2. What already exists — do NOT rebuild any of it

The dual-PM-scout machinery is complete and DORMANT. Verify before designing:
`rg -n "scout_phase_outcome|run_scout_phase|PM_SCOUT_LENSES" foundry.py`

- `roles/pm_scout.md` — product-agnostic scout role card (iter 81).
- `ScoutPhasePlan` + `decide_scout_phase(dual_pm_scouts, lenses=None)` (iter 80).
  Reads module-level `PM_SCOUT_LENSES` AT CALL TIME; supports ANY lens count;
  names stages `pm_scout_a`, `pm_scout_b`, ... by position.
- `ProductConfig.dual_pm_scouts: bool = False` (iter 81).
- `ScoutStageSpec` + `derive_scout_stage_specs` (iter 82).
- `ScoutPhaseResult` + `run_scout_phase` (iter 83).
- `scout_phase_outcome(cfg, iteration, role_file)` (iter 84) — the composition
  helper, already shaped to return `None` when disabled.
- `foundry scout-plan [--json]` (iter 90).

The ONLY thing missing is the call site. `scout_phase_outcome` has ZERO callers
in `run_iteration`. The spec deferred that wiring pending operator sign-off.

## 3. Bite 1 — wire the scout pre-phase. OPERATOR SIGN-OFF: GRANTED 2026-08-03.

The wiring bite `docs/DUAL_PM_SCOUT_SPEC.md` deferred is hereby APPROVED. Ship it.

- Call `scout_phase_outcome(cfg, iteration, <scout role file>)` in `run_iteration`
  immediately BEFORE the `pm` stage. A non-`None` falsy/failed outcome ends the
  iteration exactly as any other failed stage does (it already maps to that).
- Update `roles/pm.md`: when `pm_scout_*.md` files exist in the iteration state
  dir, they are the PM lead's PRIMARY input. The lead TRIAGES to exactly one
  feature and MUST justify the pick against the strongest rejected alternative,
  naming it.
- Preserve every invariant: sequential stages (one agent call in flight),
  output-file success (exists AND non-empty), anti-delegation clause in each
  scout prompt, and a byte-identical disabled path.
- Done when: enabled path runs scouts in order then the PM lead; disabled path is
  byte-identical to today; `dual_pm_scouts: true` in `products/_platform/config.json`
  is set by the OPERATOR after this bite ships (not by you).

## 4. Bite 2 — widen and ROTATE the lens pool (the exploration mechanism)

Two fixed lenses will re-converge. Replace `PM_SCOUT_LENSES` with a POOL and
select per iteration:

    new-capability | hardening/DX | integration-and-adoption |
    simplification-and-deletion | performance-and-throughput | narrative-and-docs

- Selection must be DETERMINISTIC, seeded by the iteration number (e.g. a stable
  rotation or an index derived from `iteration`), NOT `random.random()`. Rationale:
  the product quality bar demands offline deterministic tests, and a reproducible
  iteration -> lens mapping is testable and debuggable while still producing
  variety across iterations. Deterministic rotation buys the exploration; true
  randomness buys only flaky tests.
- Keep 2-3 scouts per iteration (quota safety), drawn from the pool, never the
  same pair two iterations running.
- `simplification-and-deletion` is a first-class lens on purpose: after 100
  iterations of additive work, removing a surface can be the highest-value change.
- Done when: the lens set for iteration N is deterministic and tested; consecutive
  iterations get different lens pairs; `scout-plan --json` reflects the rotation.

## 5. Bite 3 — `foundry novelty-check [--json]`, the repetition brake

The mechanism that would have caught iterations 90-101 at iteration 92.

- Read-only. Inputs: the last N (default 5) shipped commit SUBJECTS on the branch
  plus the newest N roadmap entries.
- Emit a verdict: `RUT` when >= 3 of the last N increments share a shape (same
  trailing token such as `--json`, or the same verb+noun family, or the entry
  text self-describes as a "clone"/"mirror"/"same shape as"), else `VARIED`.
- Exit-coded like the other decision CLIs, with `--json`.
- Then USE it: when the verdict is `RUT`, the PM MUST select from a lens not used
  in the last N iterations, and must state in the spec which rut it is breaking.
- Done when: a synthetic 12-`--json`-commit history returns `RUT`; a varied
  history returns `VARIED`; verdict is derived from real branch data, not a flag.

## 6. Bite 4 — `DIRECTIONS.md`, the human-readable digest

The operator needs to read, in one place, what the loop considered and rejected.

- On every iteration with scouts, append one dated block to `DIRECTIONS.md` in the
  product repo root: iteration number, the lenses used, every candidate proposed
  (one line each), the winner, and the strongest rejected alternative with the
  reason it lost.
- Tracked (not gitignored) — it is the project's decision log, and for `_platform`
  it doubles as a public artifact showing how the loop chooses work.
- Keep it append-only and bounded: newest block first, or a stable append with a
  digest command if it grows past a few hundred lines.
- Done when: an iteration with scouts appends exactly one block; an iteration
  without scouts appends nothing.

## 7. Bite 5 — the strangler epic is UNBLOCKED as of 2026-08-03

`resilient-agent-loop-primitives` is now PUBLIC:
https://github.com/jeffma8888/resilient-agent-loop-primitives (tag v0.1.0).

Any `BLOCKED` / operator-blocked marker on the strangler epic in
`PLATFORM_ROADMAP.md` is STALE. You own the roadmap: clear it when you pick this up.
Follow `docs/STRANGLER_PLAN.md`, which already contains the gate check, the exact
pinned dependency line, the verified v0.1.0 API signatures, and the
behavior-preservation traps. Re-run its gate check first; it now passes.

Offline note, since it will be raised as an objection: adding a pinned git
dependency does NOT weaken the offline posture, because the test command is
already `uv run --with pytest pytest -q`, which resolves `pytest` from the network
or the uv cache on a fresh clone. One more resolved, zero-runtime-dependency,
pure-Python package is the same class of requirement, not a new one.

## 8. Priority

Bite 1 first — it is small, approved, and unlocks everything else. Then 3 (the
brake stops further waste immediately), then 2, then 4. Bite 5 may be taken at any
point after bite 1 and is the highest-VALUE work on the board; if a bite above it
would be a clone-shaped increment, take bite 5 instead.

Do not ship another `--json` flag or another `company-*` clone until bites 1-4 are
done. If you believe an exception is warranted, say so explicitly in the spec and
name this document.
