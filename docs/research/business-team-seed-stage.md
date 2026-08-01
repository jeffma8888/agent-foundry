# What the business function actually does in a tiny startup (pre-seed to Series A)

## Scope and the central question

At pre-seed and seed, there is rarely a "business function" in the org-chart sense. There is a founder (or two) doing everything commercial in the seams between building the product. The useful question is not "who owns business?" but "what work must get done, who does it, and when does it justify a dedicated hire?" Two lenses answer most of it: cash (are we default alive?) and the economics of each bet (will this use of scarce build-time pay back?).

## Evidence: the business lead's job compresses to three things

The most durable job description for a company's business lead comes from Fred Wilson, who relays a veteran VC's answer to "what exactly does a CEO do?": "A CEO does only three things. Sets the overall vision and strategy of the company and communicates it to all stakeholders. Recruits, hires, and retains the very best talent for the company. Makes sure there is always enough cash in the bank." Everything else is delegated ([Fred Wilson, "What A CEO Does," 2010](https://avc.com/2010/08/what-a-ceo-does/)). At a two-person company all three land on a founder, and the third, cash, is the hard constraint that governs the rest.

## Evidence: founder-led, not dedicated roles, until product-market fit

Paul Graham is explicit that early growth is manufactured by founders doing unscalable work: "for a startup to succeed, at least one founder (usually the CEO) will have to spend a lot of time on sales and marketing," and "the most common unscalable thing founders have to do at the start is to recruit users manually" ([Paul Graham, "Do Things That Don't Scale," 2013](https://www.paulgraham.com/ds.html)). His named examples: Stripe's founders set up users on the spot ("Collison installation"); Airbnb's founders went door-to-door in New York. That is the seed-stage sales, growth, and customer-success function, performed by the same people who write the code.

The corollary is that hiring dedicated roles too early is dangerous. Graham calls hiring too fast "by far the biggest killer of startups that raise money," and notes Airbnb waited four months after raising money to hire its first employee ([Paul Graham, "Default Alive or Default Dead?," 2015](https://www.paulgraham.com/aord.html)). Sam Altman, quoted in the same essay, adds that YC's most successful companies "have never been the fastest to hire."

Fred Wilson gives the staging where dedicated commercial roles first appear. He describes three pre-scale stages with recommended burn ceilings: Building Product (team ~5, under $50k/month), Building Usage (team ~10, under $100k/month), and Building The Business, which is "when you've determined that your product market fit has been obtained": "You start to hire a management team, a revenue focused team, and some finance people... keep the burn below $250k per month" (team ~25) ([Fred Wilson, "Burn Rates: How Much?," 2011](https://avc.com/2011/12/burn-rates-how-much/)). So the first salespeople and the first finance people appear together, after PMF is claimed, roughly at the Series A boundary, not before.

## Evidence: runway and burn-rate math

The runway frame is Graham's: "Startup funding is measured in time. Every startup that isn't profitable... has a certain amount of time left before the money runs out." Take enough to reach the next visible milestone, a prototype, a launch, then significant growth ([Paul Graham, "The 18 Mistakes That Kill Startups," 2006](https://www.paulgraham.com/startupmistakes.html)). The failure mode is the "fatal pinch": default dead + slow growth + not enough time to fix it ([PG, "Default Alive," 2015](https://www.paulgraham.com/aord.html)).

a16z defines burn precisely and warns against a common sloppiness: burn rate is the rate at which cash decreases; net burn (cash out minus reliable cash in) is the real number that tells you how long the bank balance lasts, and it is what investors watch, not gross burn ([Andreessen Horowitz, "16 Startup Metrics," 2015](https://a16z.com/16-startup-metrics/)). Fred Wilson's practical shortcut: multiply headcount by roughly $10k/month "fully burdened" to estimate burn, which is why his stage ceilings map to team sizes of 5, 10, and 25 ([Fred Wilson, 2011](https://avc.com/2011/12/burn-rates-how-much/)).

## Evidence: unit economics gate which bets get build-time

Once revenue exists, the business lead judges bets by unit economics. David Skok frames it as one question, "Can I make more profit from my customers than it costs me to acquire them?", answered with two numbers: LTV (lifetime value) and CAC (cost to acquire a customer). His validated guidelines: the best SaaS businesses run an LTV:CAC ratio above 3 (sometimes 7-8) and recover CAC in 5-7 months, and profitability is "anemic" once CAC payback stretches past 12 months ([David Skok, "SaaS Metrics 2.0"](https://www.forentrepreneurs.com/saas-metrics-2/)). He shows the mechanical use: if a customer pays $500/month and you want CAC back within ~12 months, you can afford up to ~$6,000 to acquire them, and spending less means you can push harder. a16z adds the discipline that the number that matters is paid CAC (isolating paid channels), not blended CAC, if you want to know whether spend scales profitably ([a16z, 2015](https://a16z.com/16-startup-metrics/)).

The strategic point in both sources: unit economics tell the business lead when to hit the accelerator on a segment or channel and when to keep fixing the product first. Skok warns of the SaaS "cash flow trough," where faster growth deepens near-term losses, so growing before the economics work simply burns runway faster.

## Evidence: prioritization frameworks applied at the company level

Two named frameworks recur. Intercom's RICE scores each candidate as Reach x Impact x Confidence / Effort, where effort is counted in person-months and the resulting number is described as "total impact per time worked, exactly what we'd like to maximize." Intercom is candid about limits: dependencies and "table stakes" features can justify working out of score order ([Intercom, "RICE: Simple prioritization for product managers"](https://www.intercom.com/blog/rice-simple-prioritization-for-product-managers/)). ICE, coined by Sean Ellis for growth experiments, is simpler: Impact x Confidence x Ease, each scored 1 to 10. It is faster but more subjective, and, per ProductPlan's summary, better for triaging opportunities than for prioritizing a whole roadmap; RICE differs by adding Reach and by dividing by Effort rather than multiplying by Ease ([ProductPlan, "ICE Scoring Model"](https://www.productplan.com/glossary/ice-scoring-model/)). ProductPlan is a vendor glossary (a secondary source); the ICE-to-Ellis attribution is theirs.

## Opinion (synthesis): the seed-stage business function is a scarce-resource allocator

Read together, the sources describe a single role, not a department. The seed-stage business function is the person who allocates the two scarcest resources, cash and founder/engineer build-time, across a small portfolio of bets, subject to a hard survival constraint. Its concrete jobs, in priority order:

1. Keep the company default alive. Track runway in months, net burn, and growth rate, and know the plan B if the next raise slips (Graham's "separate facts from hopes"). This is the non-delegable job because it caps everything else.
2. Manufacture the first growth manually. Founder-led sales and hand recruitment of users, both to close revenue and to generate the feedback that fixes the product.
3. Decide which bets get build-time. This is where RICE/ICE and unit economics combine: RICE/ICE rank candidate bets by expected value per person-month; unit economics (LTV:CAC, payback) decide whether the winning bet is even worth scaling, or whether the product still needs fixing first.
4. Hire dedicated commercial roles only when the economics justify them, that is, at Fred Wilson's "Building The Business" stage, once PMF is claimed and payback math works.

A useful reframing for a tiny team: a "bet" costs person-months, not dollars. At seed you can run only a handful of concurrent bets, so the effort denominator in RICE is the binding one. The portfolio should be skewed: most build-time on the one or two bets with the clearest reach and best confidence, a little reserved for cheap high-upside experiments (the ICE "low-hanging fruit"), and near-zero on anything whose payback exceeds the runway.

## Synthesis: the order dedicated roles appear

Sequencing the evidence: growth/sales is founder-led from day one and stays that way until there is a repeatable motion to hand off; the first dedicated salesperson or growth hire comes after PMF (Wilson's Building-the-Business stage). Finance appears as fractional or bookkeeping help early (someone must own the runway model and the raise), with a first real finance hire arriving alongside the revenue team, again post-PMF. A dedicated product-marketing or developer-relations function typically trails both. The through-line: no dedicated commercial role is justified until the founders have proven the motion by doing it themselves.

## Implications for an autonomous AI-agent dev org

- Treat the business lead as a persistent allocator role whose single output each iteration is a ranked, RICE/ICE-scored bet list written to a file. Because roles have no memory between runs, that score file plus a short rationale is the only state the next iteration can trust.
- Make "default alive" a deterministic gate, not a judgment. The shared token budget is this org's runway; express it as remaining-runs and let a cheap check block new bets when projected spend exceeds the budget, mirroring net-burn versus runway.
- Denominate every bet in runs, not vague effort. RICE's Effort term maps directly onto "how many agent runs will this cost"; since each role activation is one run against the shared budget, the effort estimate is the most consequential input and should be biased conservative.
- Gate scaling on a checkable payback proxy. Before the org "hits the accelerator" on a project (more roles, more iterations), require a machine-verifiable signal that the last increment paid back (tests green, an artifact shipped, a metric moved), the automatable analog of LTV:CAC above 3 and CAC payback under a threshold.
- Keep the org founder-led by default. Prefer having the CEO/PM agent do the "unscalable" commercial work (deciding, prospecting the next bet) inline rather than spawning dedicated sales/finance agents, since every extra role is a run spent. Add a dedicated role only when a deterministic PMF-like trigger fires (for example, a project has shipped N consecutive green iterations).
- Encode the three-job CEO checklist as the kickoff council's rubric: vision/strategy (is this bet on-mission?), talent/staffing (which roles does this bet actually need?), and cash (does it fit the run budget?). If any of the three fails, the bet does not start.
- Reserve human attention like the scarcest resource it is. Route only two things to a person: a "fatal pinch" alert (budget nearly exhausted with no shipped value) and irreversible commercial actions. Everything else should resolve against files and deterministic gates.
- Beware premature scaling and over-hiring, the failure modes both Graham and Paul Buchheit name. The agent-org version is spinning up many concurrent teams before one team's economics work, which starves the shared budget and deepens the "cash flow trough" without shipping.

BRIEF COMPLETE
