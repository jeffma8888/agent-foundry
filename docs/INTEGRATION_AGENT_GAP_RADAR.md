# Integrating `agent-gap-radar` into the pipeline

Status: SPEC, not yet implemented. Written 2026-08-16.
Provider: `agent-gap-radar` (https://github.com/jeffma8888/agent-gap-radar) - an
evidence-backed register of gaps in AI-agent infrastructure, with a closed
taxonomy (11 stack layers, 8 gap types), a 9-rung evidence-credibility ladder,
and two deliberately UNBLENDED scores: `priority` (severity x frequency x
tractability) and `confidence` (derived from evidence class only; a
`model-output` source weighs 0).

## Why connect them at all

The foundry already answers "is this work correct?" with a verifiable reward.
It has never answered "is this work WORTH DOING?" except through the roadmap
and the novelty brake - and both of those are internal. Iterations 90-101 are
the standing proof: twelve consecutive `--json` clones, every one correct,
because correctness was the only thing measured. The novelty brake stops
repetition; it cannot point at a real unmet need.

The radar supplies exactly the missing axis: an external, evidence-ranked
statement of what is broken in this problem domain. So the connection runs in
BOTH directions, and the second one is what makes it more than a feed:

- **radar -> foundry.** The register becomes a standing input to the PM stage,
  so a candidate feature can be argued against an outside gap with a citation,
  not only against the roadmap.
- **foundry -> radar.** The loop is a continuous generator of first-party
  failure evidence (stage kills, reverts, role lessons). That evidence is
  precisely what the register's credibility ladder ranks highest, and no other
  register has it. The loop feeds its own prioritiser.

## What the radar provides (the consumed contract)

Four verbs, all offline, all read-only, all with machine-readable output:

| Verb | Use in the pipeline |
|---|---|
| `radar list --json [--layer L] [--floor N]` | ranked open gaps for the PM block |
| `radar show <ID>` | full brief when the PM picks a gap |
| `radar prd <repo> --gap <ID>` | a loop-shaped `prd.json` whose FIRST story is a failing reproduction of the gap |
| `radar audit <repo>` | (TO BUILD) static detection of structurally-checkable gaps, for the gate |

`radar prd` is the hinge. Its `US-001` is always "reproduce the gap as a failing
test" with the acceptance criterion "the test FAILS on the current code and the
failure message names the gap". That converts a research finding into the one
artifact this pipeline already knows how to grade.

## Integration point: the PM gap block (discovery)

Mirror `pm_novelty_block` exactly - it is the proven, race-free shape for
injecting a computed block into one stage's prompt.

    def pm_gap_block(cfg: ProductConfig, stage: str) -> str:
        """Read-only injection seam: the external gap register for build_prompt."""
        if stage != "pm":
            return ""
        try:
            return gap_advice(gather_gaps(cfg)) + "\n"
        except Exception:
            return ""

Invariants inherited from the novelty block, and all four matter:

- Returns `""` for every non-`pm` stage, so all other prompts stay
  BYTE-IDENTICAL and no existing prompt test moves.
- Any error degrades to `""`. A missing register, a broken CLI, a malformed
  JSON payload can NEVER crash the PM stage.
- `gather_gaps` / `gap_advice` are called by BARE module name so a
  `monkeypatch.setattr` bites at call time.
- Reads config AT CALL TIME, writes nothing.

Two new product-config fields, both optional, both defaulting to off - so every
product that does not set them keeps a byte-identical prompt:

    "gap_register": "~/projects/agent-gap-radar",
    "gap_layers": ["orchestration", "eval-verification", "observability"]

`gap_layers` is the scoping that keeps this honest: a repo-analysis CLI should
not be shown multi-agent coordination gaps. Absent `gap_layers` means all
layers.

The injected block carries, per gap and capped at the top 5: id, title, layer,
gap type, priority, confidence, the one-line problem statement, and the
strongest evidence locator. Nothing else - the PM can run `radar show` itself.

### The PM's new obligation (the discussion the register is for)

`roles/pm.md` gains one required line in the spec it writes:

    GAP: GAP-00N            (this feature closes or narrows that register gap)
    GAP: none -- <reason>   (deliberate: roadmap item, hygiene, or no gap fits)

That single line is the whole point. It forces the gap question to be ANSWERED
every iteration instead of being available, and `GAP: none` with a reason is a
perfectly good answer - the failure mode to avoid is silence. It also makes the
decision auditable after the fact, which a prompt suggestion never is.

## Integration point: a `gap-register` scout lens (candidate generation)

Add a 7th lens to `PM_SCOUT_LENS_POOL`, whose brief is: read the register
filtered to this product's layers, pick the highest-priority gap this product
could plausibly narrow, and propose 2-3 candidate features that would narrow
it. On the deterministic 2-of-6 rotation this lens draws roughly every third
iteration, which is the right cadence - a gap is a bigger swing than a hygiene
item and should not crowd out the roadmap.

This is a CONTROL-PATH change (it moves the rotation period from 6 to 7 and
there are drift tests pinning the pool and the card), so it must be its own
later bite with its own tests. Do NOT bundle it with the PM block.

## Integration point: the release gate (gatekeeping)

Two checks, and the ORDER of introduction is the safety property.

### Check one - the traceability assertion (decidable, ship-blocking)

If and only if the iteration's spec carries `GAP: GAP-00N`, the final gate
asserts:

1. `GAP-00N` exists in the register;
2. its `status` is `open` (not already closed by someone else);
3. its `confidence` is at or above the floor (default 2) - so a low-credibility
   record can never be cited as justification;
4. the iteration added at least one test whose failure message names the gap
   id, per the `radar prd` US-001 contract.

This blocks a FALSE claim, never a missing one. A `GAP: none` spec passes
untouched. It is offline, deterministic, and costs one register read.

### Check two - the gap-regression audit (report-only first)

`radar audit <repo>` statically detects the register's structurally-checkable
gaps. The seed register already contains five that are decidable from code:

- GAP-006 a machine-parsed verdict whose absent value defaults to the
  destructive branch (this repo's own `parse_ship_action` history);
- GAP-003 a step running under a hard wall-clock cap with no checkpoint-first
  write;
- GAP-007 concurrent agents sharing a working tree and a git index with no
  protocol;
- GAP-004 steering context assumed delivered with nothing verifying delivery;
- GAP-009 "shipped is not live" - a long-running process still executing code
  that git reports as shipped.

Introduce it DORMANT: the gate runs it and records the verdict in `final.md`,
and the verdict does not affect shipping. Promote it to a blocker only after it
has produced BOTH a proven true positive (it fired on a planted known-bad
sample) and a proven true negative (it stayed silent on a known-good one). An
audit that has only ever returned "clean" is not evidence of health - it is an
unproven detector, and a fail-open gate is worse than no gate.

## What must NEVER be gated

**Do not gate on "this iteration closed a gap", and do not score a team on gaps
closed per iteration.** That is the twelve-clone failure in a new costume: the
loop would farm whatever the register makes easiest to claim, and the register
would decay into a scoreboard. Gate on HONESTY (the claim matches the register)
and on NON-REGRESSION (the diff did not reintroduce a known gap). Never on
throughput.

Corollary for the register itself: a gap record whose only evidence is
`model-output` weighs 0 confidence by construction, so it can inform a PM
discussion but can never justify a ship or block one.

## Integration point: the reverse direction (loop evidence -> register)

The loop writes thousands of role lessons and a per-stage kill/rescue ledger.
A `radar ingest` (radar-side, offline) reads a product's `LEARNINGS.md` plus
`dispatcher.out` and proposes DRAFT register records for recurring failures,
tagged `source_class: first-party-field`.

The discipline that keeps this from polluting the register: an ingested draft
enters BELOW the confidence floor and is displayed but never ranked until a
human promotes it. The register's value is the credibility ladder; an
auto-appended record that skipped it would destroy exactly the property that
makes the register worth consulting.

## Phasing

| Phase | Change | Risk |
|---|---|---|
| 1 | `gather_gaps` + `gap_advice` + `pm_gap_block` as pure functions with ZERO call site, plus config fields with off-by-default. Tests only. | none - additive-dormant |
| 2 | Wire `pm_gap_block` into `build_prompt` for the `pm` stage; `roles/pm.md` requires the `GAP:` line. | low - one stage's prompt |
| 3 | Final-gate traceability assertion on a `GAP:` claim. | low - blocks only false claims |
| 4 | `radar audit` consumed by the gate in report-only mode. | none while dormant |
| 5 | Promote the audit to a blocker, once two-sided proof exists. | medium - do last |
| 6 | `gap-register` scout lens (7th lens, rotation period 6 -> 7). | medium - control path |

Phase 1 is one iteration's work and changes no behaviour. Phases 5 and 6 are
the only ones that can stall the loop, and both are last on purpose.

## Verification for each phase

- Phase 1: unit tests force every branch offline with a scripted register; a
  missing/corrupt register returns `""`.
- Phase 2: assert a non-`pm` prompt is byte-identical to the pre-change prompt,
  and that a product with no `gap_register` set gets a byte-identical `pm`
  prompt too.
- Phase 3: a spec citing a nonexistent, closed, or below-floor gap must FAIL
  the gate in a test; a `GAP: none` spec must pass.
- Phase 4: the audit is proven two-sided against planted samples BEFORE it is
  consulted at all.
