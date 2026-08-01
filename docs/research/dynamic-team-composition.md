# Dynamically staffing a team per project

How do you decide which roles a project actually needs, assemble them, and change the
mix as the work reveals itself? Four bodies of practice answer this from different
angles: an org-design pattern language (Team Topologies), two project-based staffing
industries (film and professional services), one famous-then-recanted agile model
(Spotify), and a fast-moving research thread on dynamic agent teams. This brief separates
what those sources actually say from a proposed protocol for an autonomous agent org.

## Evidence: Team Topologies gives a small vocabulary for flexible team boundaries

Matthew Skelton and Manuel Pais's *Team Topologies* (2019) reduces org design to four
fundamental team types and three interaction modes. The four types are **stream-aligned**
(owns an end-to-end slice of the business, "You Built It, You Run It," no hand-offs),
**enabling** (temporarily boosts skills in another team, then leaves), **complicated-subsystem**
(specialist knowledge, heavy mathematics/calculation), and **platform** (provides an internal
product that accelerates stream-aligned teams). Teams interact in exactly three ways:
**collaboration** (high-bandwidth, high-cost, for discovering new things), **X-as-a-Service**
(low-cost, clear boundaries), and **facilitating** (temporary help to remove obstacles)
([teamtopologies.com/key-concepts](https://teamtopologies.com/key-concepts)).

Two of its published principles bear directly on per-project staffing. "Keep teams together"
argues that stable teams beat freshly assembled rock stars because they carry shared context,
and it warns that reshuffling has an "astronomical" hidden cost. Yet "flexible team boundaries"
and "continuous adaptation" hold that boundaries "shouldn't be fixed permanently" and that org
design "is never done." The site is explicit that a topology diagram is "a snapshot in time" and
that "team relationships WILL change as new goals are set." The reconciling constraint is
**cognitive load**: like an overloaded CPU, a team given too many domains "make[s] poor decisions
and move[s] slowly." The concrete artifact for making a team's boundary legible is the **Team API**
(book pp. 47-49): a point-in-time spec of a team's type, the software it owns, its versioning
approach, service-level expectations it offers, what it is working on, and which teams it
interacts with and how ([Team-API-template](https://github.com/TeamTopologies/Team-API-template)).

## Evidence: The Hollywood model assembles, delivers, and disbands

In "What Hollywood Can Teach Us About the Future of Work" (New York Times, May 2015), Adam Davidson
defines the **Hollywood model**: "A project is identified; a team is assembled; it works together
for precisely as long as is needed to complete the task; then the team disbands"
([nytimes.com](https://www.nytimes.com/2015/05/10/magazine/what-hollywood-can-teach-us-about-the-future-of-work.html)).
He distinguishes it from the corporate model (capital first, then open-ended jobs) and from the
gig economy (one-person, sub-day tasks): the Hollywood model handles work that is "large and
complex, requiring many different people with complementary skills," and he reports it now being
used to "build bridges, design apps or start restaurants." Two mechanisms make it work: a small
pool of "proven, reliable craftspeople for any given task" whose scarcity gives them leverage, and
constant market signaling ("every weekend's box-office results provide new information about which
skills are valuable"). This is a recent inversion: through Hollywood's Golden Age the major studios
held creative personnel on long-term contracts, and only after the 1948 *Paramount* antitrust ruling
broke vertical integration did production shift decisively toward per-project assembly of freelance
talent ([Studio system](https://en.wikipedia.org/wiki/Studio_system)).

## Evidence: Professional-services firms staff to an engagement's shape

Consultancies solve the same problem with a pyramid. Firms including McKinsey, Bain, and BCG run an
"up or out" partnership system in which staff must reach a rank within a set time or leave, producing
a stable ratio of senior to junior people that is re-cut per engagement ([Up or out](https://en.wikipedia.org/wiki/Up_or_out)).
The economic rationale, per McKinsey's long-time director Marvin Bower, is a consultant's
"externality" (varied experience outside the client) and the fact that external experts can act as
"bridges for information and knowledge" more economically than clients staffing the capability
permanently ([Management consulting](https://en.wikipedia.org/wiki/Management_consulting)). In
practice a partner scopes the problem, then chooses the "leverage" (the junior-to-senior mix) by the
work's character: a novel diagnosis needs more senior judgement, a well-understood rollout can lean
junior. The role list is derived from the engagement, not fixed in advance.

## Evidence: The Spotify "squad" model and its published critiques

Henrik Kniberg and Anders Ivarsson's 2012 white paper described Spotify's structure as autonomous
cross-functional **squads** (mini-startups owning a mission and choosing their own working method),
grouped into **tribes** (kept under ~100 people, a Dunbar limit), with **chapters** (a competency line
within a tribe) and **guilds** (cross-cutting communities of interest)
([Scaling Agile @ Spotify](https://blog.crisp.se/wp-content/uploads/2012/11/SpotifyScaling.pdf)).
The model spread widely as a template. It has since been sharply critiqued, most influentially by
former Spotify employee Jeremiah Lee, whose "Failed #SquadGoals" (2020) argues that "the Spotify
model is revealed as a collection of cross-functional teams with too much autonomy and a poor
management structure," that Spotify itself never fully ran it and moved past it, and that
"collaboration was an assumed competency" that most teams lacked. He quotes agile coach Joakim
Sundén ("we should not be focusing so much on autonomy... maybe we should have a minimum viable
agility") and L. David Marquet ("control without competence is chaos")
([jeremiahlee.com](https://www.jeremiahlee.com/posts/failed-squad-goals/)). Note the direct conflict
with Team Topologies and the Spotify origin story: those celebrate team autonomy, while Lee and
Sundén conclude that autonomy without alignment, defined cross-team processes, and baseline
competence produces chaos. Both can be true: autonomy pays off only above a competence-and-alignment
floor.

## Evidence: Dynamic team formation in multi-agent AI research

The research analog is explicit. **AgentVerse** (Chen et al., arXiv Aug 2023) proposes a framework
that "collaboratively and dynamically adjust[s] its composition as a greater-than-the-sum-of-its-parts
system," shows the assembled group outperforming a single agent, and catalogues emergent social
behaviors to amplify or suppress ([arXiv:2308.10848](https://arxiv.org/abs/2308.10848)). **MetaGPT**
(Hong et al., arXiv Aug 2023) encodes standardized operating procedures into an assembly line that
assigns "diverse roles to various agents" (product manager, architect, engineer, QA) and has each
verify intermediate results to cut cascading errors ([arXiv:2308.00352](https://arxiv.org/abs/2308.00352)).
The sharpest match to "staff the team, then re-staff it" is **DyLAN** (Liu et al., arXiv Oct 2023;
COLM 2024): a two-stage system that first runs **Team Optimization**, selecting the best agents from a
candidate pool using an unsupervised "Agent Importance Score," then runs **Task Solving** with only
that team; on MMLU subjects the selection stage improved accuracy "by up to 25.0%" at "moderate
computational cost" ([arXiv:2310.02170](https://arxiv.org/abs/2310.02170)). The common finding: a
task-specific subteam beats both a single agent and a fixed maximal committee, and the selection can
be automated from a candidate bench.

## Synthesis (opinion): a concrete staffing protocol

The convergent lesson across all five sources is a **bench plus a selector plus bounded review**. Here
is a protocol tailored to an agent org.

**Base role bench.** Maintain a catalog of role definitions, each a versioned prompt file with a
declared input/output contract, in effect a "role API" mirroring the Team Topologies Team API. Bench
roles (founder, product manager, product-gate PM, technical program manager, engineer, reviewer, QA,
release gate, plus business/finance, legal, designer, DevRel/docs) cost nothing while dormant; they
consume budget only when a project activates them. Default to a lean stream-aligned pipeline
(PM to engineer to reviewer to tester to release gate) and treat every other role as an *enabling* or
*complicated-subsystem* add-on that must be triggered.

**Kickoff council.** Convene a fixed, cheap council once per product (for example founder + PM +
product-gate PM + TPM) whose only job is to emit a machine-checkable **staffing manifest**: which
bench roles are ON, in what sequence, with what gates and done-criteria. The council decides by a
trigger rubric mapping product traits to roles: ships a UI implies designer; touches user data or
licensing implies legal; exposes a public API implies DevRel/docs; heavy algorithmic core implies a
complicated-subsystem specialist. This is DyLAN's Team Optimization stage and Team Topologies' team
design done deliberately, once, up front. The council also writes a short **project charter** and a
**context pack** that any later role reads first.

**Periodic re-staffing review.** On a fixed cadence (every N iterations) or a defined trigger
(repeated gate failures, a scope change, a new artifact type), run a lightweight review (one or two
roles) that reads the charter, progress file, and git log and proposes a *diff* to the manifest: add
a role, retire one, or swap leverage. This is DyLAN's per-task re-selection and Team Topologies'
"continuous adaptation" made periodic rather than continuous.

## Synthesis (opinion): risks and mitigations

**Thrash.** Continuous re-staffing burns the shared budget and destabilizes context. Mitigate with
hysteresis: a newly activated role has a minimum tenure of K iterations; the manifest changes only at
the review cadence, never inside a normal iteration; each review has a hard cap on how many roles it
may add or drop; and every change must cite a logged trigger. Default to Team Topologies' "keep teams
together." Spotify's failure mode was the opposite of thrash (too little structure imposed too late),
but both stem from the same root: unbounded local reorganization. Bound it.

**Cold-start context loss.** Because roles have no memory between runs, every activation is a fresh
start with zero context, exactly the "reinvent the wheel" cost Sundén named. Mitigate by making
onboarding artifacts mandatory and machine-generated: the charter, a running decision log, the role
API contracts, and a single always-current "project brief" that each role updates on exit. Git plus
these files is the team's only shared memory, so the kickoff council's context pack and standardized
output locations are load-bearing, not documentation nice-to-haves.

**Subjective gates.** A staffing decision or an impact claim that only a human can adjudicate does not
scale. Make the manifest, done-criteria, and the product-gate PM's checks deterministic (files exist,
schema validates, tests pass, claims map to acceptance tests) so the council and review run without a
human in the loop except by exception.

## Implications for an autonomous AI-agent dev org

- **Activation is the unit of cost.** Every role you turn on is one model-API run against a shared
  budget, so default lean and require an explicit trigger to add a role; a maximal standing committee
  is the expensive anti-pattern DyLAN outperforms.
- **Make the kickoff council small and cheap.** Four roles emitting one JSON manifest is enough;
  the council's value is the decision, not deliberation, so cap its rounds.
- **Emit a machine-checkable staffing manifest, not prose.** Downstream gates and re-staffing reviews
  must diff it deterministically; roles with no memory cannot reconcile ambiguous intent.
- **Treat every add-on role as enabling or complicated-subsystem.** It joins, does its bounded job,
  writes its artifact, and leaves; the stream-aligned pipeline stays the backbone.
- **Ship a Team-API-style contract per role.** Fixed input/output locations and versioning are the
  only defense against cold-start context loss when the next fresh run must pick up the thread.
- **A single always-current project brief in git is the shared memory.** Mandate that each role reads
  it on entry and updates it on exit; without it, each activation reinvents context.
- **Bound re-staffing with hysteresis and a change cap.** Minimum role tenure plus a fixed review
  cadence prevents budget-burning thrash; changing the team every iteration is as damaging as never
  changing it.
- **Autonomy needs an alignment-and-competence floor.** Spotify's lesson: give roles freedom only
  atop defined cross-role processes and deterministic acceptance criteria, or you get "chaos."
- **Keep the product-gate PM's checks deterministic.** Feasibility and impact claims must resolve to
  tests or schema, since a subjective gate silently routes work back to the scarcest resource: a human.
- **Surface staffing decisions by exception only.** The council and reviews should escalate to a human
  solely when a trigger or gate fails, preserving human attention for the judgments no gate can encode.

BRIEF COMPLETE
