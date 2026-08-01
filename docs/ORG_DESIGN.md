# Org Design: a rich bench, a lean active team

Status: **adopted** (2026-08-01). This is the staffing blueprint for the foundry's
next growth phase. Implementation lands incrementally via `PLATFORM_ROADMAP.md`
items 17-22; until a bite ships, the current fixed pipeline
(PM -> Engineer -> Reviewer -> Tester -> Final gate) remains the behavior of record.

Evidence base: eight sourced research briefs in [`docs/research/`](research/README.md)
(multi-agent failure studies, product-gate patterns, skunkworks staffing history,
role-cost economics, dynamic team composition). Citations below point there.

---

## 1. The model in one line

> **Rich bench -> a cheap kickoff council staffs the minimum -> a lean always-on
> core -> everything else is trigger/cadence-activated -> re-staffing is bounded
> and clean.**

The org "knows" many roles but *runs* very few. Breadth lives in cheap, versioned
role definitions (a bench). Cost and failure surface live only in the roles that
actually execute (the active team). A short kickoff council decides, per product,
which bench roles activate; everyone else stays dormant until a written trigger
fires or a cadence review pulls them in.

```
            BENCH (definitions, ~zero cost)
  CEO . Biz/Finance . Legal . Designer . DevRel/Docs . TPM
  Product Manager . Product-gate PM . Engineer . QA . Release Gate
                          |
                   kickoff council            (one bounded session per product)
              CEO + PM + gate-PM + engineer   -> staffing manifest (JSON)
                          |
            ACTIVE CORE (always-on, per iteration)
     Product agent -> Engineer -> Reviewer -> isolated Tester -> Release Gate
                          |
        trigger- / cadence-activated specialists (bounded tenure)
              Legal, Designer, DevRel, TPM, Biz review, ...
```

## 2. Why lean: every role is a failure seam

The instinct when an autonomous org underperforms is to add roles. The evidence
says the opposite:

- **MAST** (arXiv:2503.13657; 1,600+ annotated multi-agent traces) finds that
  multi-agent gains over strong single-agent baselines are "often minimal," and
  that the dominant failure classes are **inter-agent misalignment** and **weak
  verification** -- not lack of specialist skill. Every additional active role is
  another handoff where context is dropped, assumptions diverge, and a wrong
  claim can pass unverified. ([brief](research/multi-agent-org-patterns.md))
- Practitioner reports (Cognition's "Don't Build Multi-Agents"; Anthropic's
  multi-agent engineering write-up) converge on the same rule: parallelize only
  work that is genuinely read-heavy and independent; serialize and *keep single-
  owner* anything that mutates shared state. Coding is low-parallelism. Token
  cost for chatty multi-agent setups runs ~15x a focused single agent.
  ([brief](research/role-cost-tradeoffs.md))
- Small-team history (Skunk Works, the Macintosh team, early-stage startups)
  shows the leverage is in a few empowered generalists plus *hard gates*, not in
  org-chart completeness. ([brief](research/skunkworks-small-teams.md))

So the design rule here: **a role earns always-on status only if it must act on
every iteration. Everything else activates on a written trigger, does bounded
work, and goes dormant again.** More roles means more communication, more
misalignment, and weaker verification -- the three things that actually kill
multi-agent systems.

## 3. The bench

Every bench role is a versioned role-card in [`roles/bench/`](../roles/bench/)
declaring: mission, activation trigger, tenure (when it deactivates), an I/O
contract (what it reads, what artifact it must produce), and a model note.
Dormant roles cost nothing -- a card is just a file.

| Role | One-line mission | Card |
|---|---|---|
| **CEO / Founder** | The single accountable decider: keeps every product on-mission, owns staffing manifests and the iteration budget (runway denominated in agent-runs), and is the only role that can escalate to the human operator. | [`ceo.md`](../roles/bench/ceo.md) |
| **Business / Finance lead** | Allocates the scarce resource (iterations) across bets: keeps a RICE-scored bet list, prices each Go decision in agent-runs, and gates spend like a default-alive seed-stage CFO. | [`business_finance.md`](../roles/bench/business_finance.md) |
| **Legal** | License compatibility, data/privacy exposure, IP hygiene. Trigger-activated: fires only when a change touches user data, licensing, or terms. | [`legal.md`](../roles/bench/legal.md) |
| **Designer** | UI/UX and interaction quality. Trigger-activated: fires only when a product ships a human-facing surface. | [`designer.md`](../roles/bench/designer.md) |
| **DevRel / Docs** | Public-facing docs, README quality, API reference. Trigger-activated: fires when a public API or onboarding path changes. | [`devrel_docs.md`](../roles/bench/devrel_docs.md) |
| **Product Manager** | The merged "why + what" product agent: owns the spec, goals/non-goals, and the smallest shippable slice. One person/agent, not a PM/PO split. | [`product_manager.md`](../roles/bench/product_manager.md) |
| **Product-gate PM** | The adversarial reviewer seat of the product gate: attacks the impact math and feasibility of a proposal before iterations are spent. Runs on a **different model** than the builder to break self-preference bias. | [`product_gate_pm.md`](../roles/bench/product_gate_pm.md) |
| **TPM** | Cross-module dependency coordination. Dormant until a countable threshold (N modules with cross-cutting changes in flight) makes coordination cheaper than collisions. | [`tpm.md`](../roles/bench/tpm.md) |
| **Engineer(s)** | Builds the slice the spec defines; smallest diff that passes the gates. | [`engineer.md`](../roles/bench/engineer.md) |
| **QA / Tester** | Isolated black-box verification: reads the spec and observable behavior only, never the source, so tests cannot be written "to the code." | [`qa_tester.md`](../roles/bench/qa_tester.md) |
| **Release Gate** | The only role allowed to touch irreversible actions (git, publish). Recomputes ground truth itself (full suite, leak scan), deterministic checks first, rejects on any doubt. Prefer a **different model** than the builder. | [`release_gate.md`](../roles/bench/release_gate.md) |

The five core roles' *operational* playbooks (the prompts the pipeline actually
runs) live in [`roles/`](../roles/); the bench cards for those roles describe the
seat and defer to the playbook for mechanics -- progressive disclosure in both
directions.

### 3.1 The bench is extensible: minting new roles

The bench is a registry, not a closed list. When the kickoff council or a
re-staffing review identifies a gap the current bench cannot cover -- say a
**Security Reviewer** for a product that starts handling auth, or a
**Performance Engineer** for a latency-critical service -- it *mints a new
role-card* into `roles/bench/` rather than overloading an existing seat.

A minted card must declare, like every other card:

1. **Mission** -- one paragraph, falsifiable ("done" is observable).
2. **Activation trigger** -- the written condition that wakes it.
3. **Tenure** -- when it deactivates (a project phase, a fixed iteration count,
   or "until trigger clears"). Temporary/specialized roles are the norm.
4. **I/O contract** -- exact inputs it may read, the artifact it must emit.
5. **Model note** -- same model as the builder, or decorrelated.

This keeps the structure dynamic without re-opening the lean-core rule: a new
role enters the *bench* by default, and only the council/re-staffing process can
activate it.

## 4. The always-on core

Exactly five seats run every iteration:

```
Product agent -> Engineer -> Reviewer -> isolated Tester -> Release Gate
```

Each stage is a fresh agent run; the only shared memory is on-disk artifacts
(spec, diff, test report, learnings). This core is the entire standing cost of
a product team. Everything in section 3 that is not one of these five seats is
dormant by default.

## 5. The kickoff council and the staffing manifest

When a product starts (or re-plans), a **kickoff council** -- CEO, Product
Manager, Product-gate PM, and a senior engineer -- runs one bounded session and
emits three artifacts:

- a **project charter** (mission, appetite, non-goals),
- a **context pack** (what every later fresh-context agent must know),
- a machine-checkable **staffing manifest** (JSON): which bench roles are ON,
  their sequence and gates, per-role model assignment, done-criteria, and the
  iteration budget.

A **trigger rubric** maps product traits to bench roles mechanically (ships a
UI -> Designer; touches user data -> Legal; public API -> DevRel; N-module
dependency count -> TPM), so staffing is auditable rather than vibes-based.
The pipeline then *reads the manifest* instead of hard-coding the team.

## 6. The tri-perspective product gate

Before iterations are spent on a proposal, three perspectives must sign -- the
same idea attacked from three different failure directions:

| Seat | Question it must answer | Kills the failure mode |
|---|---|---|
| **Business** | Is the problem real and worth it? Must state an impact number, the key assumption, a confidence level, and a one-line pre-mortem. | Building something nobody needs. |
| **Product** | Is this the right and *smallest* solution? Must state goals/non-goals, the appetite, and the alternatives considered. | Building the right thing the wrong (oversized) way. |
| **Senior engineer** | Is it feasible? Names the riskiest unknown and any knock-out constraint. | Approving what cannot be built inside the appetite. |

Mental model: a proposal that survives three *decorrelated* attacks is worth a
bounded bet; a proposal that cannot is killed **by default** (verdicts are
Go / Kill / Recycle, and the default is Kill). Two design details make the gate
cheap and honest:

- **Deterministic pre-checks run before any model call**: impact number present?
  appetite stated? alternatives listed? A proposal missing them is bounced for
  free.
- **Circuit-breaker**: every Go carries a fixed iteration bet. When the bet is
  spent, the proposal returns to the gate instead of silently absorbing runway.

The gate runs at kickoff and again on *strategic-surface triggers* (scope
change, budget exhaustion, direction pivot) -- not on every iteration.

## 7. Activation cadence: kickoff + trigger, with a fixed-N fallback

Primary mechanism: roles activate at **kickoff** (via the manifest) or when
their **written trigger** fires. This is the cheapest scheme and catches the
decisions that matter.

Fallback (adopted 2026-08-01): **if no trigger has fired for 5 consecutive
iterations, the CEO + PM proactively review the project anyway** -- read the
ship ledger and learnings, confirm the work still tracks the charter, steer if
needed. This bounds the failure mode where a quiet loop drifts for a long time
precisely *because* nothing looked anomalous. Start at N=5; relax toward N=10
once the review history shows steering is rarely needed.

## 8. Decorrelation: gates run on a different model

A reviewer sampled from the same model as the author systematically prefers the
author's output (self-preference bias, arXiv:2404.13076). Both adversarial
seats -- the **Product-gate PM** and the **Release Gate** -- should therefore
run on a *different model* than the builder roles. The staffing manifest
carries a per-role model assignment; the runner's agent-CLI env override
mechanism extends per-role (roadmap item 20).

## 9. CEO escalation: autonomous except five reserved categories

The CEO decides autonomously *except* where a deterministic diff predicate
detects one of five reserved categories, each of which escalates to the human
operator before anything ships:

1. security / credentials,
2. personal data / PII,
3. spending real money,
4. legal / licensing exposure,
5. changes to public visibility.

The committed leak-guard (`scripts/leak_guard.py`) is the first shipped
instance of this pattern (category 2, enforced at the release gate). Every gate
decision -- pass, kill, escalate -- is logged as structured data so the org's
judgment is auditable after the fact.

## 10. Bounded re-staffing

Team composition changes are proposals, not drift: a re-staffing review emits a
**diff against the staffing manifest**, and the diff is constrained by
hysteresis rules --

- a role must serve a **minimum tenure** (K iterations) before it can be
  deactivated,
- at most a **capped number of changes** per review,
- every change must cite the **logged trigger** that motivated it.

This keeps the org dynamic (roles come and go with the work) while preventing
thrash, the multi-agent equivalent of a re-org every sprint.

## 11. Implementation order

Shipped incrementally by the platform team (see `PLATFORM_ROADMAP.md`, items
17-22, smallest-safe-first):

1. Role-card format + the dormant bench (`roles/bench/*.md`).
2. Kickoff-council script emitting the JSON staffing manifest + trigger rubric.
3. Manifest-driven pipeline (foundry reads the manifest, not a fixed role list).
4. Tri-perspective product gate with Go/Kill/Recycle + decorrelated adversarial seat.
5. CEO escalation predicates (generalize the leak-guard pattern to all five categories).
6. Bounded re-staffing review + the N=5 no-trigger fallback.

## 12. Research base

| Brief | Feeds |
|---|---|
| [multi-agent-org-patterns](research/multi-agent-org-patterns.md) | Sections 2, 4 |
| [role-cost-tradeoffs](research/role-cost-tradeoffs.md) | Sections 2, 8 |
| [skunkworks-small-teams](research/skunkworks-small-teams.md) | Section 2 |
| [pm-vs-tpm-vs-po](research/pm-vs-tpm-vs-po.md) | Section 3 (PM, TPM seats) |
| [product-gate-patterns](research/product-gate-patterns.md) | Section 6 |
| [business-team-seed-stage](research/business-team-seed-stage.md) | Section 3 (CEO, Biz/Finance) |
| [ownership-escalation-models](research/ownership-escalation-models.md) | Section 9 |
| [dynamic-team-composition](research/dynamic-team-composition.md) | Sections 5, 7, 10 |
