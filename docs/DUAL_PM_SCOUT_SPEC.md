# Platform enhancement: dual PM-scout candidate generation

Source pattern: an earlier two-scout prototype loop ran TWO PM scouts per iteration
before the PM lead, each with a distinct LENS, then the lead triaged their combined
slate and selected exactly one feature. This produced more diverse, higher-quality
candidate features than a single PM. Port that pattern into the foundry's shared
pipeline so ALL product teams benefit.

## What to build (for the _platform team)
Add an OPTIONAL two-scout pre-stage to `foundry.run_iteration`, gated by a config flag
so existing single-PM products are unaffected:

1. New role file `roles/pm_scout.md` (adapted from the two-scout prototype, made
   product-agnostic): a scout PROPOSES 2-3 candidate features in an assigned LENS;
   it decides nothing. (Shipped with two fixed lenses; since iteration 113 the lens
   pair is ROTATED per iteration by `select_scout_lenses` over `PM_SCOUT_LENS_POOL`,
   whose six entries are each defined in `roles/pm_scout.md`.)
2. New config field on `ProductConfig`, e.g. `dual_pm_scouts: bool = False`
   (backward-compatible default off). When true, `run_iteration` runs `pm_scout_a`
   then `pm_scout_b` SEQUENTIALLY (concurrency 1 preserved), each on its own rotated
   lens, writing `pm_scout_a.md` / `pm_scout_b.md` into the iteration state dir.
3. The existing `pm` (PM lead) stage then reads both scout files as inputs and TRIAGES:
   picks exactly one feature, justifying it against the strongest alternative. Update
   `roles/pm.md` to consume the scout files when present.

## Invariants to preserve (from ARCHITECTURE.md)
- Output-file success (each scout stage succeeds iff its output file exists, non-empty).
- Sequential stages -> at most one agent-CLI call in flight (single-brain quota safety).
- Anti-delegation clause in every scout prompt.
- Fully backward-compatible: `dual_pm_scouts` defaults off; no behavior change for existing
  products unless they opt in.
- Add tests: scout stages run in order when enabled; PM lead consumes both files;
  disabled path is byte-identical to today.

## How to enable for a product
Set `"dual_pm_scouts": true` in that product's `config.json`.

> Seeded 2026-08-01 during a consolidation of predecessor loops into the foundry. The
> _platform team should implement this with tests rather than a hand-edit, since
> foundry.py is the platform team's own domain.
