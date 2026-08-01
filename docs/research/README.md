# Org-design research briefs

These eight briefs are the evidence base for evolving agent-foundry from a fixed
five-role pipeline into a startup-like org with a **role bench** and **dynamic,
per-project team composition**. Each brief separates cited evidence from synthesis
and ends with implications specific to an autonomous LLM-agent dev org (every role
activation is one model-API run against a shared token budget; roles have no memory
between iterations except files and git; gates must be deterministically checkable;
human attention is the scarcest resource).

| Brief | Question it answers |
|---|---|
| [pm-vs-tpm-vs-po](pm-vs-tpm-vs-po.md) | How PM (Why), Product Owner (What), and TPM (How/When) differ, and when to split vs merge them |
| [product-gate-patterns](product-gate-patterns.md) | How companies gate ideas before building (PR-FAQ, six-pager, Shape Up, stage-gate) and detect inflated impact |
| [business-team-seed-stage](business-team-seed-stage.md) | What the business function actually does at a tiny startup; budget/bet allocation; when commercial roles appear |
| [skunkworks-small-teams](skunkworks-small-teams.md) | How famous small teams organized (Skunk Works, WhatsApp, Valve, Haier); the minimal viable org |
| [multi-agent-org-patterns](multi-agent-org-patterns.md) | Role structures in multi-agent AI frameworks; does adding roles improve output; static vs dynamic teams |
| [role-cost-tradeoffs](role-cost-tradeoffs.md) | The token/latency/reliability cost of each added role or reviewer; correlated-error risk; stage budgets |
| [ownership-escalation-models](ownership-escalation-models.md) | Decision-rights frameworks (RACI/DACI/RAPID), reversibility, and which decisions must escalate to a human |
| [dynamic-team-composition](dynamic-team-composition.md) | Staffing a team per project (Team Topologies, Hollywood/consulting models, DyLAN); a bench+council+re-staffing protocol |

Design synthesis that builds on these lives in `docs/ORG_DESIGN.md` (added separately).
