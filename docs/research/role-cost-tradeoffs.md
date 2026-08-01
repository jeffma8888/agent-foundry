# The cost side of adding roles or stages to an LLM agent pipeline

Every role you add to an agent pipeline buys some quality and charges rent in three currencies: tokens, latency, and reliability. This brief surveys what the literature and production reports actually show about that rent, then gives budgeting guidance for a quality-gated shipping pipeline in which each role is one fresh LLM run that communicates only through files and version control.

## Evidence: the unit cost of a stage

Anthropic's engineering guidance is blunt about the base trade: "Agentic systems often trade latency and cost for better task performance, and you should consider when this tradeoff makes sense," and its first recommendation is to "find the simplest solution possible, and only increasing complexity when needed" ([Anthropic, Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)). The prompt-chaining pattern it describes (decompose a task into sequential LLM calls with programmatic gates between them) is explicitly framed as trading latency for accuracy.

The token multipliers are large and measured. In Anthropic's production research system, single tool-using agents used about 4x the tokens of a plain chat turn, and multi-agent configurations used about 15x ([Anthropic, How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)). The same report found that token usage alone explained 80% of the performance variance on a hard browsing benchmark, with tool-call count and model choice explaining most of the rest. That cuts both ways: more stages help largely because they spend more tokens, and they cost proportionally more. Anthropic's explicit conclusion is that multi-agent systems "require tasks where the value of the task is high enough to pay for the increased performance," and that dependency-heavy work such as most coding "involve[s] fewer truly parallelizable tasks than research."

Latency compounds differently from tokens. Sequential roles (plan, then engineer, then reviewer, then gate) each add roughly one full model round-trip to the critical path, so wall-clock time grows with pipeline depth even when each stage is cheap. Parallel roles (Anthropic's "sectioning" and "voting" patterns) hide latency but not token cost. Multi-round debate methods pay both: Du et al.'s multiagent debate runs several model instances proposing and critiquing "over multiple rounds," so cost scales roughly as agents x rounds x tokens-per-turn ([Du et al., Improving Factuality and Reasoning through Multiagent Debate](https://arxiv.org/abs/2305.14325)).

(Synthesis) In a file-and-git pipeline specifically, there is a second-order cost: each downstream role re-ingests the growing artifact set (spec, diff, prior reviews) as input tokens, so input cost per stage rises with pipeline depth rather than staying flat. A ten-role pipeline does not cost 10x a single role; the later roles are the most expensive ones.

## Evidence: do extra reviewers pay off?

The gains from stacking reviewers are real but bounded and task-dependent. Li et al. show that pure sampling-and-voting (instantiate the same agent many times and majority-vote) improves accuracy, but the improvement "is correlated to the task difficulty" and eventually saturates ([Li et al., More Agents Is All You Need](https://arxiv.org/abs/2402.05120), TMLR). This is redundancy (the same role repeated), not distinct roles; it buys variance reduction, not new capability.

At the system level the returns are often disappointing. Cemri et al. built MAST, a taxonomy from 1600+ annotated traces across seven popular multi-agent frameworks, and open with the observation that these systems' "performance gains on popular benchmarks are often minimal" ([Cemri et al., Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/abs/2503.13657)). They identify 14 failure modes in three families: system-design and specification issues, inter-agent misalignment, and task-verification failures. Adding roles adds surface area in exactly those three families. MetaGPT frames the same danger as "cascading hallucinations caused by naively chaining LLMs," and its fix is not more agents but more structure: encoding standard operating procedures so agents verify intermediate results ([Hong et al., MetaGPT](https://arxiv.org/abs/2308.00352)).

## Evidence: self-correction and critic reliability

Whether a reviewer role helps depends heavily on whether it has grounded feedback. Huang et al. tested intrinsic self-correction (a model revising its own answer with no external signal) and found that "LLMs struggle to self-correct their responses without external feedback, and at times, their performance even degrades after self-correction" on reasoning tasks ([Huang et al., Large Language Models Cannot Self-Correct Reasoning Yet](https://arxiv.org/abs/2310.01798), ICLR 2024). A reviewer that only re-reads and re-thinks can make things worse.

The counterweight is Self-Refine, where the same model generates, critiques, and revises iteratively and improves by about 20% absolute on average across seven tasks ([Madaan et al., Self-Refine](https://arxiv.org/abs/2303.17651)). The apparent conflict resolves on task type: Self-Refine's wins are largest on open-ended generation, where "better" is partly a matter of preference and the critique supplies concrete, actionable edits; Huang et al.'s failures are on reasoning problems with a single correct answer, where a model that got it wrong has no privileged way to know it. (Synthesis) The practical rule: a critic role earns its keep when it is wired to an external, checkable signal (test results, a compiler, a linter, a schema validator), and is a coin-flip or worse when asked to introspect on correctness it could not achieve in the first place.

## Evidence: correlated errors under a shared base model

The sharpest risk for a same-model org is that the reviewer shares the author's blind spots. Panickssery et al. show that LLM evaluators exhibit self-preference: they score their own generations higher than humans judge them to be, and the strength of that bias correlates linearly with the model's ability to recognize its own outputs ([Panickssery et al., LLM Evaluators Recognize and Favor Their Own Generations](https://arxiv.org/abs/2404.13076)). When author and reviewer are the same base model, the reviewer is disposed to approve.

Cognition frames the systems version of this: independently spawned agents "carry implicit decisions," and conflicting implicit decisions produce incoherent results that a final combiner cannot rescue ([Cognition, Don't Build Multi-Agents](https://cognition.ai/blog/dont-build-multi-agents)). Their recommendation is to prefer a single-threaded linear agent that shares full context, and they note that even Claude Code's subagents are restricted to answering questions rather than writing code in parallel, precisely to avoid conflicting decisions. (Synthesis) Correlated error is why "add another reviewer of the same model" gives diminishing returns the fastest: two draws from the same distribution miss the same things. Decorrelation (a different base model, a genuinely different adversarial prompt/persona, or a deterministic non-LLM check) buys far more than a duplicate.

## Synthesis and opinion: cadence and trigger-based activation

Running every role on every iteration is the expensive default and rarely the right one. Two mitigations follow directly from the evidence:

- Trigger-based activation. Route work to specialized reviewers only when a cheap signal fires, mirroring Anthropic's routing pattern (classify the input, dispatch to a specialized follow-up). A security reviewer runs only when the diff touches auth or crypto paths; a schema or API reviewer runs only when interface files change; the second, adversarial product-gate PM runs only when a change claims user-facing impact. The trigger itself should be deterministic (path globs, diff size, changed-file types) so activation is auditable and free.
- Cadence-based activation. Reserve expensive holistic roles (architecture review, cost audit, docs regeneration) for every Nth iteration or a fixed wall-clock cadence rather than every commit. This keeps the per-iteration critical path short while still amortizing deep review over time.

Both convert a fixed N-role cost per iteration into an expected cost far below N, and they concentrate scarce, high-value LLM runs on the changes that actually need them.

## Synthesis and opinion: stage-count budgets

A defensible budget for a quality-gated shipping pipeline:

- Keep the always-on critical path to about 3 to 5 LLM roles. A workable core is plan, build, review, release-gate, with the tester or verification wired to real execution. This matches Anthropic's "simplest thing that works," the linear-agent bias from Cognition, and stays under the failure-surface growth Cemri et al. document.
- Push as many gates as possible off the LLM. Tests, linters, type checks, coverage thresholds, and build success are deterministic, free after the first run, and immune to self-preference. Every deterministic gate you add lets you delete or downgrade an LLM reviewer. LLM review should be the exception layer for what compilers cannot judge (naming, design intent, exaggerated impact claims).
- Make at least one gate adversarial and, if possible, decorrelated. If the release gate and the author are the same base model, give the gate a different model, a strict rubric with mandatory failure criteria, and instruction to reject on doubt, because the default lean is to approve.
- Treat added roles as opt-in via triggers and cadence, not as standing headcount. A large council is fine to define; it is expensive to run every iteration.
- Cap parallel redundancy. Voting or duplicate reviewers help only on ambiguous, difficulty-scaled tasks and saturate quickly; two or three votes is usually the whole return.

## Implications for an autonomous AI-agent dev org

- Every role is a billed LLM run on a shared token budget, so treat the standing pipeline as a cost center: keep the always-on path near 3 to 5 roles and make everything else trigger- or cadence-gated. Expected roles-per-iteration, not defined roles, is the number to manage.
- Because roles remember nothing between iterations except files and git, the artifacts are the only context, so context-passing cost grows with pipeline depth (later roles re-read everything). Keep artifacts compact and canonical; a compression or summary step can be cheaper than paying every downstream role to re-read raw history.
- Gates must be deterministically checkable, and this is where reliability actually lives: prefer tests, lint, build, and schema gates over LLM judgment, and reserve LLM review for what those cannot express.
- A reviewer sharing the author's base model will tend to approve (self-preference bias) and miss the same errors (correlated error). Decorrelate the release gate with a different model, an adversarial rubric, and a reject-on-doubt default; this is worth more than a second same-model reviewer.
- An LLM critic without a grounded signal can degrade quality, so wire critic roles to external checks (execution, validators) rather than pure re-reading, per the self-correction results.
- The second product-gate PM (the feasibility and exaggerated-impact check) is high value precisely because it is adversarial and evaluates claims rather than code, but it needs a concrete rubric and a bias toward rejection to overcome the approve-lean.
- Dynamic per-project staffing should default small and add roles on evidence: let the kickoff council pick the minimal set and let deterministic triggers (diff content, claimed impact, changed file types) pull in specialists only when a cheap signal fires.
- Human attention is the scarcest input, so spend LLM roles to protect it: a reliable deterministic gate plus one strong adversarial reviewer removes more human review load than a wide, correlated committee that produces confident, agreeable, and wrong approvals.

BRIEF COMPLETE
