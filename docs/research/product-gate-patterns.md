# Product review gates before building

Companies gate feature ideas before engineering starts to avoid the most expensive mistake in product development: building the wrong thing well. A gate is a decision ritual — a document, a meeting, and a set of pass/kill criteria — that a proposal must clear before code is written. The well-known variants differ sharply in ceremony and weight, but they converge on one job: force a proposal to be legible, testable, and *killable* early, while the cost of killing it is still just words on a page.

## Evidence: Amazon's PR-FAQ, six-pager, and OP planning

Amazon's "Working Backwards" process produces a PR-FAQ: a one-page mock press release announcing the *finished* product to its customer, plus internal and external FAQ sections. Per [ProductPlan's glossary](https://www.productplan.com/glossary/working-backward-amazon-method/), former Amazon director Ian McAllister lists the required elements — customer, problem, benefit, a leadership quote, a call to action — and stresses the release is revised repeatedly until it is short, clear, and compelling.

Colin Bryar and Bill Carr, who ran the process at Amazon, are explicit that the gate is *meant to kill things*. As quoted in [Commoncog's account of Working Backwards](https://commoncog.com/putting-amazons-pr-faq-to-practice/): "The fact that most PR/FAQs don't get approved is a feature, not a bug." Time spent up front determines "which products *not* to build ... preserving your company's resources to build products that will yield the highest impact." The document forces a small set of hard questions — who is the customer, what's the problem, what's the solution (explained *to the customer*, not to yourself), would they change behavior to adopt it, and is the addressable market big enough — and the FAQ is where teams "seek the truth around" the assumptions behind those answers (Commoncog). The press-release framing is deliberately unforgiving: it makes buzzword-driven or team-flattering ideas visibly hollow, because a customer "does not care about your technology stack."

The six-pager is the companion ritual. In his [2017 shareholder letter](https://www.aboutamazon.com/news/company-news/2017-letter-to-shareholders), Jeff Bezos describes replacing slide decks with "narratively structured six-page memos," silently read at the start of each meeting. The letter's most gate-relevant insight is about *scope realism*: weak memos usually fail not from bad writing but from "a wrong expectation on scope" — teams think a great memo takes a day when it takes a week of writing, sharing, and re-editing. "Unrealistic beliefs on scope ... kill high standards." Amazon also strips author names from memos so ideas are judged on merit, not politics (Bezos letter). Amazon's annual operating-plan process — widely reported as OP1 (a bottom-up narrative plan) and OP2 (revised after leadership guidance) — applies the same narrative discipline to resource and goal commitments, forcing teams to defend a written plan before headcount is allocated.

## Evidence: Google's design-doc and launch reviews (the "PRD" caveat)

Google is more codified around engineering design docs than around a single company-wide PRD gate; PRDs there are team-specific, so sources describing "the Google PRD review" as one canonical ritual should be read with caution. The durable, well-documented gate is the design doc. [Malte Ubl's "Design Docs at Google"](https://www.industrialempathy.com/posts/design-docs-at-google/) describes an informal document written *before coding* that captures the high-level strategy and, critically, the trade-offs considered. Two sections do the gating work: "Goals and non-goals" (things that could reasonably be goals but are explicitly excluded) and "Alternatives considered," which Ubl calls "one of the most important" because it shows why the chosen solution beats the others a reviewer would wonder about. Reviews "scale the knowledge of senior engineers into the organization" and force cross-cutting concerns (security, privacy, observability) to be addressed early "when it is still relatively cheap to make changes." Ubl is candid that reviews are "a dangerous trap of overhead," warns against blocking progress on wide review, and notes that a doc which just says "this is how we'll implement it" with no trade-offs is a signal you should have written the code instead. Google additionally gates *launches* via production/launch-readiness reviews later in the lifecycle.

## Evidence: Basecamp's Shape Up betting table

Basecamp's Shape Up gates ideas at a "betting table" held during the two-week cool-down between six-week cycles, per [the Shape Up book](https://basecamp.com/shapeup/2.2-chapter-08). Attendees are few and senior — at Basecamp, the CEO, CTO, a senior programmer, and a product strategist — and the meeting "rarely goes longer than an hour or two," because everyone studied the shaped pitches beforehand and "there's no grooming or backlog to organize." Two mechanisms make the gate real: the *appetite* set during shaping caps how much time a bet is worth, and the *circuit breaker* means unfinished projects get no automatic extension — "the most we can lose is six weeks." The betting language reframes the meeting from "a battle for resources or a plea for prioritization" into a place where leadership exercises "hands on the wheel" control, and betting only one cycle ahead keeps the slate clean (Shape Up).

## Evidence: The Linear method

[The Linear method](https://linear.app/method) is lightweight and anti-ceremony. Its gating artifact is a short project spec with a *named owner* that "briefly communicate[s] the why, what and how" and, crucially, forces teams to "scope out work so priorities are clear and teams avoid building the wrong thing." Linear explicitly rejects heavy backlog grooming ("keep a manageable backlog ... important ones will resurface, low priority ones will never get fixed"), warns against inventing new terms, and adopts "decide and move on ... sometimes the most important thing is to make a decision." Progress is measured by "actual work" — the diff — and issues are scoped as small as possible. The philosophy trades formal gatekeeping for tight scope, single ownership, and short cycles.

## Evidence: Classic Stage-Gate

Robert Cooper's Stage-Gate — in print since 1988 and, per [Stage-Gate International](https://www.stage-gate.com/blog/the-stage-gate-model-an-overview/), reported by benchmarking studies to be used by a majority of firms doing new-product development — divides development into stages separated by go/kill decision gates. Gates are "not backward-looking status reviews; they are forward-looking" points where senior cross-functional "Gatekeepers" who *own the resources* decide Go / Kill / Hold / Recycle and, on Go, commit the budget and headcount for the next stage (avoiding "approval without resources"). Cooper's canonical gate criteria, summarized in [Wikipedia's phase-gate article](https://en.wikipedia.org/wiki/Phase-gate_process), separate "must-meet" knock-out questions — including "reasonable likelihood of technical feasibility" and "positive return versus risk" — from scored "should-meet" criteria, and stress that gates need "teeth" to prune weak projects. Investment rises stage by stage as information improves, "like placing progressively larger bets in five-card stud" (Stage-Gate). Cooper also flags the danger: over-structured gates can "interfere with creativity and innovation," and gate financial data are "often uncertain or biased" (Wikipedia, Stage-Gate).

## Evidence: The second-reviewer pattern and catching inflated claims

Across these systems, the recurring defense against exaggerated impact and infeasible proposals is an *independent reviewer who is not the author and has no stake in shipping*. Stage-Gate builds this in via cross-functional gatekeepers and must-meet feasibility knock-outs (Wikipedia). Amazon strips author names so the reviewer judges the argument, not the person, and the FAQ format explicitly surfaces the assumptions behind impact and market-size claims (Bezos letter, Commoncog). Google's alternatives-considered section forces the author to defend against the options a skeptical reviewer would raise (Ubl). The general "dual-PM / second-reviewer" pattern — pairing the author's advocacy with an independent challenger empowered to say *kill* — is the same mechanism Amazon uses in hiring via its Bar Raiser role: a trained reviewer from outside the hiring team, holding veto power. Applied to product, a second PM whose only job is to test the impact math and feasibility (rather than defend the idea) catches the inflation the author is motivated not to see.

## Opinion (synthesis): What separates an effective gate from a bureaucratic one

Effective gates share a small set of properties, drawn from the evidence above:

- **Cheap to write, expensive to fake.** A press release or a scope-forcing spec is quick to draft yet hard to fake convincingly — a weak idea reads as hollow.
- **They actually kill, and everyone knows it.** Bryar/Carr's "most don't get approved," Cooper's "gates with teeth," and Shape Up's circuit breaker all make *No* real. A gate that never rejects anything is theater.
- **Few, senior, prepared people; one short meeting.** Shape Up's one-hour table and Ubl's warning against review-as-overhead point the same way.
- **They front-load the falsifiable claims** — customer, feasibility, scope, impact — and separate fact from opinion.
- **They cap downside explicitly** (appetite, a fixed bet, staged investment).

Bureaucratic gates invert each of these: forms nobody reads, reviews that only bless, large committees, endless backlog grooming, and unbounded scope. Bezos's scope-realism point and Cooper's creativity warning name the two failure modes to fear most.

## Opinion (synthesis): A minimal three-perspective gate

For a small org, use three reviewers, one page, one decision:

1. **Business — is the problem real and worth it?** Answers: who is the customer, what's the problem, and a single impact number *with its key assumption stated* (borrow the PR-FAQ's five questions and market-size discipline).
2. **Product — is this the right solution, and the smallest one?** Answers: goals/non-goals, the appetite (how much it's worth), and why *not* the obvious alternative (Google's alternatives-considered + Shape Up's appetite + Linear's scope-first spec).
3. **Senior-engineer feasibility — can it be built within the appetite, and what's the riskiest unknown?** A must-meet knock-out: "reasonable likelihood of technical feasibility" (Stage-Gate).

The output is a single verdict — Go / Kill / Recycle — with *No* genuinely on the table, decided by reviewers who did not write the proposal.

## Implications for an autonomous AI-agent dev org

- **Every review costs one model-API run against a shared token budget**, so make the gate the cheapest artifact that can still kill: a one-page proposal with the five business questions, an appetite, and one feasibility knock-out — not a five-role committee per idea.
- **Roles have no memory between iterations except files and git**, so the proposal *and its verdict* must be a committed file (e.g. `proposal.md` with a required `Verdict: GO|KILL|RECYCLE` line) that the next agent reads without re-deriving the decision.
- **Gates must be deterministically checkable**: encode must-meet criteria as machine-verifiable predicates (impact number present and non-empty; alternatives section present; appetite stated in iterations; feasibility verdict set) so a cheap script — not a second LLM run — rejects malformed proposals before any review run is spent.
- **Give the second-PM/reviewer agent an adversarial prompt and no stake in shipping**: its only job is to attack the impact math and name the riskiest infeasibility, mirroring the Bar Raiser and alternatives-considered patterns. Judge the argument, not the author (strip authorship, as Amazon does).
- **Default the gate to Kill/Recycle, not Go**: an idea advances only on an affirmative pass, matching "most PR-FAQs don't get approved." This is the cheapest guard against an eager generator agent flooding the pipeline.
- **Cap downside like Shape Up's circuit breaker**: bet a fixed number of iterations per accepted idea; if it isn't shippable by then it reverts and must be re-pitched, not extended — bounding wasted token spend on runaway projects.
- **Treat scope realism as a hard gate, not a nicety**: require the proposal to state its build appetite and forbid acceptance when the appetite is "unknown," since (per Bezos) unrealistic scope is the top killer of quality.
- **Human attention is the scarcest resource**, so route only ambiguous or high-cost bets to a human gatekeeper; let deterministic checks plus the adversarial reviewer auto-kill the clearly-weak and auto-pass the clearly-strong, summarizing each verdict in one skimmable line.
- **Keep the slate clean**: no persistent backlog of half-proposals accruing token cost. Kill or recycle, and let strong ideas resurface as fresh pitches (Linear + Shape Up).

BRIEF COMPLETE
