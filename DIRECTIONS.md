# Foundry directions

foundry directions -- _platform
  iter-220
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 -- stop re-reading and re-parsing the whole tree once per tree-wide brake
    - Candidate A2 -- the stage prompt states this attempt's wall-clock deadline
    - Candidate A3 -- the UNFINISHED tester retry resumes from its own checkpoint instead of restarting
    - Candidate B1 -- two docs describe a reporter seat the live company has never run
    - Candidate B2 -- the public catalog of what the foundry has built is frozen at day one
    - Candidate B3 -- the PM card never states the id contract the committed decision log parses
    winner: A3
    ship: pending (not yet decided)
  iter-219
    lenses: simplification-and-deletion (iteration 219), performance-and-throughput
    - Candidate A1 -- collapse the ten near-duplicate company roll-up constructors onto one shared body
    - Candidate B1 -- delete the roadmap tombstones the spent-block detector cannot see, and fix its inverted recall
    - Candidate C1 -- evict the spent operator directives from the 10,000-char prompt head
    - Candidate B1 -- stop the cross-worker repo-root race that turns the green suite red
    - Candidate B2 -- bound prompt assembly so a hung pre-launch probe cannot stall the fleet
    - Candidate B3 -- make the tester's machine-checkable verdict a checkpoint, not a gamble
    winner: B1
    ship: PUSHED 490bf35
  iter-218
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- the shipped product-gate pre-check gets its first producer: `roles/pm.md`
    - Candidate A2 -- `recoverable` gets its first consumer, on the retry path it was built for
    - Candidate A3 -- the scout prompt gets the repetition brake only the PM lead has
    - Candidate B1 -- collapse the weak/constant/skipped `render` triplet onto one renderer parameterised by its two literals
    - Candidate B2 -- replace nine hand-written `Company*.verdict` label dicts with one general rule
    - Candidate B3 -- retire the dominated second roadmap budget (two budgets become one)
    winner: A2
    ship: PUSHED b6792a7
  iter-217
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- make the TWO live readers of `ACTION:` disclose when they disagree (report-only; do NOT tighten)
    - Candidate A2 -- `recoverable` proves a preserved patch APPLIES; make it also say whether it carries its own oracle
    - Candidate A3 -- lint an artifact for colliding with the sentinels this product itself ships
    - Candidate B1 -- `status` reads the liveness verdict, so `company-status` answers "is my brain behind its own code?"
    - Candidate B2 -- re-scope the 26 dispatcher byte-freezes to an AST/symbol invariant (roadmap item (o))
    - Candidate B3 -- the `agents` renderer gets its first consumer: an AGENTS.md drift line
    winner: B1
    ship: PUSHED 7a2bc85
  iter-216
    lenses: new-capability, hardening/DX
    - Candidate A1 -- `foundry roster-lag`: teams registered in config the LIVE brain never loaded
    - Candidate A2 -- `foundry company-losses`: fleet-wide lost work, by cause, one row per team
    - Candidate A3 -- `foundry company-recoverable`: fleet view of whether preserved work still applies
    - Candidate B1 -- anchor the unfinished-tester marker to a line START, not a bare substring
    - Candidate B2 -- `foundry ledger-check`: the mandated two-tree roadmap-record oracle, as one verb
    - Candidate B3 -- a brake tying every runtime-flag constant to real `git check-ignore` coverage
    winner: B1
    ship: PUSHED d4c8aa8
  iter-215
    lenses: narrative-and-docs (iteration 215), new-capability (iteration 215)
    - Candidate A1 -- the roadmap STATUS line's freshness guard is a FROZEN FLOOR (>= 202) while the derivable rule sits in the same file
    - Candidate A2 -- README calls `company-constant-asserts` "the 6th and LAST company-* member"; three later README lines and the registry all contradict it
    - Candidate A3 -- ARCHITECTURE.md presents `PROMPT_LEARNINGS_BUDGET_CHARS` as an active bound; it is arithmetically unreachable on the live path
    - Candidate B1 -- `foundry recover`: does the work this loop PRESERVED still apply?
    - Candidate B2 -- `foundry roadmap-record`: ask the record brakes BEFORE committing
    - Candidate B3 -- `foundry now`: distinguish an iteration IN FLIGHT from one that finished
    winner: B1
    ship: PUSHED 100cf2f
  iter-214
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 -- extend the on-disk leak brake from `tests/**/*.py` to the whole shipping population
    - Candidate A2 -- deliver a role-addressed operator directive only to the role it names
    - Candidate A3 -- (placeholder, being measured) price the idle tail of a cap-killed stage
    - Candidate B1 -- the pinned LEARNINGS head tells every stage that a LIVE product is retired
    - Candidate B2 -- the pinned head's ARCHIVE boundary does not survive rendering, so 16 of the 19 bullets every stage reads are spent directives that look live
    - Candidate B3 -- pin the README's negative-existence claims so the next artifact cannot silently falsify them
    winner: A1
    ship: PUSHED 5624fac
  iter-213
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- collapse the three code-identical test-quality summary dataclasses onto one shared base
    - Candidate A2 -- the same collapse one rung up: the three `Company*` per-axis roll-up classes
    - Candidate A3 -- TBD (measuring)
    - Candidate B1 -- a per-product FAST test command for the non-tester stages
    - Candidate B2 -- shrink the fresh-clone cost the final gate pays twice per iteration
    - Candidate B3 -- TBD (measuring stalled-attempt waste)
    winner: B1
    ship: PUSHED 2678ad5
  iter-212
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- the release gate reads the `GAP:` claim that `roles/pm.md` already forces every PM to write
    - Candidate A2 -- the ten `company-*` roll-ups say "no enabled products" when you hand them the wrong config
    - Candidate A3 -- route `losses` to the owner each cause names, on a surface a human already runs
    - Candidate B1 -- collapse `test_quality_cli`'s duplicated inline composition onto the existing `gather_test_quality` seam
    - Candidate B2 -- extract the 4x byte-identical iteration-window preamble into one `_iteration_window` seam
    - Candidate B3 -- retire the three per-axis company roll-up verbs in favour of the general `company-test-quality`
    winner: B1
    ship: PUSHED 96f1f47
  iter-211
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- the only sanctioned dispatcher launcher is untracked, hidden in `.git/info/exclude`, while two tracked docs teach the invocation that killed a 68-shift brain
    - Candidate A2 -- a year-less `strptime` makes the stage-duration digest silently empty on leap day, and Python 3.15 turns that into every day
    - Candidate A3 -- `foundry doctor`, the one verb a role card runs every iteration, reports NOT READY from inside every stage, on a check no stage can satisfy
    - Candidate B1 -- roles/reviewer.md runs the composite test-quality scan on this iteration's own new test file
    - Candidate B2 -- roles/pm.md consults `live-lag --json`, so the stage that CHOOSES the next feature knows which surfaces are live
    - Candidate B3 -- `save-work --json`: give the one verb the loop actually runs a machine-readable payload, and correct its stale adoption comment
    winner: B1
    ship: PUSHED 467dc68
  iter-210
    lenses: new-capability, hardening/DX
    - Candidate A1 -- `foundry recoverable`: which preserved never-shipped work can still be retried
    - Candidate A2 -- `foundry unfailable-asserts`: the 4th test-quality lens gets a surface
    - Candidate A3 -- `foundry deadtail`: name the wall clock spent after a stage's artifact stopped growing
    - Candidate B1 -- a repo-wide public-safety brake over `tests/`, because the per-module self-check convention collapsed after iter 140
    - Candidate B2 -- `foundry doctor`'s roadmap-index advisory reports OK inside a 1,120-char band where the suite is already RED
    - Candidate B3 -- the record obligation has no operator surface at all: both oracles are consumed only by the suite
    winner: B1
    ship: PUSHED 615b435
  iter-209
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- the roadmap advertises a SHIPPED item as open work, and contradicts its own ledger doing it
    - Candidate B1 -- a spec doc still headed "not yet implemented" after 2.5 of its 6 phases went live
    - Candidate C1 -- five product-config fields exist only in code, including both knobs that switch on the gap feed
    - Candidate B1 -- a structured live-lag verdict + `foundry live-lag --json`
    - Candidate B2 -- `foundry unfailable-asserts [--json]`: the 4th test-quality lens, dormant since iter 186
    - Candidate B3 -- a tri-state triage verdict: tell "no contest" apart from "winner unreadable"
    winner: B1
    ship: PUSHED b30b00a
  iter-208
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 -- price the stalled-tester tax and make the declared test command non-silent
    - Candidate A2 -- cap-saturation ranking replaces a WARN that fires on 9 of 10 stages
    - Candidate A3 -- resumable tester evidence ledger (mirror the final gate's VERIFIED: ledger)
    - Candidate A1 -- README's per-verb DORMANT status field misreports live call sites
    - Candidate B1 -- "the five invariants" has three rosters and no resolvable one
    - Candidate C1 -- a stale verb-count figure that every existing brake is blind to
    winner: A1
    ship: PUSHED 7e8e6a5
  iter-207
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- collapse the `exit_code` x4 hand-copy onto one module-level function
    - Candidate A2 -- one anchored-sentinel TOKENIZER retires the last 2 of the 5 gate parsers
    - Candidate A3 -- collapse the `to_dict` x3 duplicate (the largest single deletion available)
    - Candidate B1 -- the prompt pays 8,000 chars for 10 truncated lessons when 9,615 buys 7 whole ones under the SAME budget
    - Candidate B2 -- stage-times splits cap-saturated seconds into dead tail vs destroyed-at-the-wall
    - Candidate B3 -- optional per-product fast stage check command, dormant, full suite reserved for the isolated tester and the gate
    winner: A1
    ship: PUSHED 8d66a1e
  iter-206
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- the public-safety scan gains a consumer BEFORE the gate
    - Candidate B1 -- doctor reports whether the committed leak-guard is actually armed
    - Candidate C1 -- the release gate gets its first GAP: consumer (documented phase 3)
    - Candidate A -- collapse the `exit_code` x4 roll-up group (roadmap item (q)'s named next bite)
    - Candidate B -- collapse the `render` triplet on the three test-quality Summary classes (item (x)'s named next bite)
    - Candidate C -- extract the shared `ACTION:` prologue, and do NOT reuse the sentinel core
    winner: A1
    ship: PUSHED 6752dcb
  iter-205
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- the gate's tester-verdict helper answers "no tester report" when handed a directory path
    - Candidate A2 -- a reviewer CHANGES_REQUIRED with no BLOCKING finding still buys a fix round
    - Candidate A3 -- the repo-root read-only guard watches three files the running loop itself writes
    - Candidate B1 -- every subparser gets a one-line `help=`, kept honest by a derived brake
    - Candidate B2 -- `doctor --json`, so the one verb a role card runs every iteration stops being scraped
    - Candidate B3 -- tester.md consumes the four test-quality detectors that exist to grade its own output
    winner: A1
    ship: REVERTED
  iter-204
    lenses: new-capability, hardening/DX
    - Candidate A1 -- `foundry behavior-trace`: report which numbered spec behaviors shipped with no test that names them
    - Candidate A2 -- `foundry retry-debt`: name the preserved-but-unlanded work, because today only a human remembers it
    - Candidate A3 -- `foundry shifts`: read the dispatcher's own ledger, which 658 shifts later nothing has ever read
    - Candidate B1 -- a meta-brake on "newest-ness" pins in tests/, keyed on LAST/MAX claims rather than on iteration literals
    - Candidate B2 -- the outcomes ledger stops recording a cap-killed checkpoint as a red suite
    - Candidate B3 -- enforce the one rule roles/reviewer.md already states: no CHANGES_REQUIRED without a BLOCKING finding
    winner: A1
    ship: PUSHED 9a70305
  iter-203
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- commit the canonical dispatcher launch, and make the docs stop teaching the invocation that killed a 68-shift brain
    - Candidate A2 -- make the invariant SET derived, so "five hard-won invariants" cannot disagree with the six bullets it points at
    - Candidate A3 -- `docs/artifacts.md` claims to be a running catalog; it has one entry and has never been updated
    - Candidate B1 -- classify the SHIP DIFF's added lines, the escalation bite the code itself names as next
    - Candidate B2 -- `foundry stops`: name every halt sentinel, its age, and the reason inside it
    - Candidate B3 -- `foundry relands`: a ledger of preserved rescue patches and which still apply
    winner: B2
    ship: REVERTED
  iter-202
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 -- move the gate's cold-clone verification earlier so a revert becomes a fix
    - Candidate A2 -- retire dead chars from the pinned digest head
    - Candidate A3 -- price and cut redundant full-suite runs per iteration
    - Candidate B1 -- the roadmap STATUS line is 3 iterations stale, and its brake is a floor pinned to iteration 185
    - Candidate B2 -- README says the CLI has 48 verbs; it has 50, and the existing figure brake cannot see the sentence
    - Candidate B3 -- three artifacts name three different sets of "the invariants", and one of them is in every stage prompt
    winner: B1
    ship: PUSHED 890d4cf
  iter-201
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- three byte-identical sentinel verdict parsers collapse onto one rule
    - Candidate A2 -- one `company-*` subparser helper replaces 9 hand-copied flag declarations
    - Candidate A3 -- retire the quadratic `company-*` preamble comments, which have already decayed into two contradictory claims
    - Candidate A -- recent-vs-all-time DELTA on the `stage-budget:` line
    - Candidate B -- a prose-only deadtail advisory in the stage prompt (dormant first bite)
    - Candidate C -- put SECONDS on the lost-work accounting
    winner: A1
    ship: REVERTED
  iter-200
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- the watchdog's resurrection writes the `dispatcher.out` that four shipped surfaces read
    - Candidate A2 -- `roles/pm.md` must answer the repetition brake, the way iter 197 made it answer `GAP:`
    - Candidate A3 -- give `foundry agents` its first consumer, so house rules reach the repo fresh agents read
    - Candidate B1 -- placeholder pending measurement
    winner: A1
    ship: PUSHED 16857fe
  iter-199
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- the brain scan stops reporting 3 dispatchers when ONE brain is running
    - Candidate A2 -- a failed process scan must not license a second brain
    - Candidate A3 -- the loop's own freeze brake gives two different answers in one iteration
    - Candidate B1 -- grade the GAP: answer inside the linter the PM card ALREADY runs, instead of minting a verb
    - Candidate B2 -- the mandated GAP: answer is recorded ONLY in a gitignored file
    - Candidate B3 -- the layer filter every PM prompt is scoped by is unvalidated and was set against a 16-record register
    winner: A1
    ship: REVERTED
  iter-198
    lenses: new-capability, hardening/DX
    - Candidate A1 -- `foundry gap-check`: print the gap-claim verdict for an iteration's spec
    - Candidate A2 -- `foundry unfailable-asserts` (+ `--json`): give the 4th test-quality lens a surface
    - Candidate A3 -- a committed `evals/` corpus + pure replay runner for the loop's own gate parsers
    - Candidate B1 -- the brain scan stops reporting 3 dispatchers when ONE brain is running
    - Candidate B2 -- ship a TRACKED, repo-agnostic launcher under `scripts/` that fails CLOSED
    - Candidate B3 -- `preship` names the revision it verified and the uncommitted work it is blind to
    winner: B3
    ship: PUSHED d4172e9
  iter-197
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- ARCHITECTURE.md credits iteration 194 twice for the gate wiring that shipped as 195
    - Candidate A2 -- `docs/artifacts.md` calls itself "a running catalog" and reports 1 of 5 products, at 10 iterations
    - Candidate A3 -- the invariants doc never names `preship`, the only step that can BLOCK a push, nor its asymmetric rule
    - Candidate B1 -- `foundry unfailable-asserts [--json]`: give the 4th test-quality lens a CLI
    - Candidate B2 -- `foundry gap-check --config <cfg> --spec <file> [--json]`: is a `GAP:` claim traceable?
    - Candidate B3 -- a role-targeted operator directive channel with its own budget
    winner: B2
    ship: PUSHED 642ae0b
  iter-196
    lenses: performance-and-throughput, narrative-and-docs
    - A1 -- an expired session gets its own failure kind, checked BEFORE the `timeout` needle
    - A2 -- stop buying attempts 2-4 for a failure no retry can heal
    - A3 -- `retry-value`: price every ladder rung by what it has ever rescued
    - Candidate A1 -- ARCHITECTURE.md credits the live final gate to iteration 194, which never shipped
    - Candidate B1 -- the roadmap's own STATUS line is stale by two shipped iterations
    - Candidate C1 -- the index lists item (k) as STILL OPEN and, 50 lines later, as DE-LISTED
    winner: A1
    ship: PUSHED a72c8aa
  iter-195
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- collapse the `exit_code` x4 identical Company roll-up bodies onto one shared body
    - Candidate A2 -- collapse the `to_dict` x3 identical bodies -- the same win with no `property()` trick
    - Candidate A3 -- retire the SECOND roadmap budget: two constants, two dataclasses, two verdicts become one
    - Candidate C1 -- stage-times prices the post-checkpoint tail (wall clock burned after the deliverable's last write)
    - Candidate A1 -- audit the write-early OUTCOME, not the card: the contract holds everywhere except the remediation stages
    - Candidate B1 -- price the digest payload every attempt pays for, and make digest_truncations > 0 visible
    winner: unknown
    ship: PUSHED e63e14b
  iter-194
    lenses: integration-and-adoption, simplification-and-deletion
    - A1 -- the PM card must ANSWER the gap feed it already receives (`GAP:` line, graded by the linter the card already runs)
    - A2 -- the committed decision log says `winner: unknown` for iterations that DID pick, and cannot tell that from "no contest"
    - A3 -- the lag reporter that would ask the operator to restart has no caller, and its own iteration-scoped guard forbids one
    - B1 -- collapse the 5 anchored-sentinel gate parsers onto one shared rule
    - B2 -- the `Company*` `render` triplet, which no roadmap item owns
    - B3 -- retire the 2 SPENT operator directives riding in every stage prompt
    winner: B1
    ship: REVERTED
  iter-193
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- a pre-bulk-verb stray inventory: name every untracked+unignored path that `git add -A` would stage and `git clean -fd` would destroy
    - Candidate B1 -- an atomic write seam, starting with the rescue patch that `revert_repo` writes seconds before it destroys the tree
    - Candidate C1 -- a tested enumerator for the reviewer's BLOCKING findings, so the release gate stops hand-rolling the query
    - Candidate B1 -- the PM must ANSWER the gap register it now reads, and the decision log records the answer
    - Candidate B2 -- `foundry gaps [--config C] [--limit N] [--json]` plus a `doctor` gap-register line
    - Candidate B3 -- feed the dispatcher's live-but-silent story meter, using the producer verb that already ships
    winner: B1
    ship: unknown
  iter-192
    lenses: new-capability, hardening/DX
    - Candidate A1 -- wire `pm_gap_block` into `build_prompt` and opt `_platform` in
    - Candidate A2 -- `foundry gaps [--config C] [--layer L] [--limit N] [--json]`
    - Candidate A3 -- `gap-evidence`: emit DRAFT register records from the loop's own kills
    - Candidate B1 -- retire the gate's ad-hoc substring rule: wire `ship_decision`, reading the kill fact off the attempt logs
    - Candidate B2 -- a PROBE HYGIENE rule in all 8 role cards, enforced by a pure card audit + live brake
    - Candidate B3 -- close the tester-verdict helper pair's argument-type trap
    winner: A1
    ship: PUSHED de9d946
  iter-191
    lenses: narrative-and-docs, new-capability
    - Candidate A -- retire the 4 stale `foundry.py:NNNN` line pointers for symbol anchors, plus a brake
    - Candidate B -- `docs/artifacts.md` claims to be a running catalog and reports one product with pre-generalization figures
    - Candidate C -- ARCHITECTURE.md never records the gate rule with the largest measured cost, nor its dormant successor
    - Candidate A -- `foundry steer`: the first WRITE path to the steering channel, with a delivery proof
    - Candidate B -- `foundry recurrence`: the 431 losing scout candidates nothing has ever read
    - Candidate C -- grade a role's ARTIFACT against its own card, the way `lint-spec` grades the PM's
    winner: unknown
    ship: PUSHED 648f5b3
  iter-190
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 -- stage-times reports cap saturation in SECONDS, and says so in its verdict
    - Candidate A2 -- wire the dormant ship_decision so a cap-killed final gate retries instead of reverting
    - Candidate A3 -- every stage prompt carries its own measured pacing line on attempt 1
    - Candidate B1 -- ARCHITECTURE's gate invariant documents the post-push verify and never names `preship`, the only step that can BLOCK a push
    - Candidate B2 -- `roles/final.md` credits `parse_ship_action` for a branch the loop actually takes with a whole-file substring test
    - Candidate B3 -- "five hard-won invariants" disagrees with the six the doc it summarises actually lists
    winner: A1
    ship: PUSHED 23f32c2
  iter-189
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- two argparse helpers retire 33 duplicated `--config` declarations
    - Candidate A2 -- collapse the byte-identical methods in the 10-class `Company*` roll-up family
    - Candidate A3 -- retire the 6 spent roadmap index blocks the detector already names
    - Candidate B1 -- `stage-burn`: measure the wall-clock spent AFTER the output file stops changing
    - Candidate B2 -- price the digest, the one payload every stage pays for
    - Candidate B3 -- derive a per-stage wall-clock deadline from measured medians (the `final` precedent)
    winner: B1
    ship: PUSHED 35919b4
  iter-188
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- teach the story meter the register's `prd.json` key, so the dispatcher's already-live hook stops reading "unparseable"
    - Candidate A2 -- gap-radar phase 1, built on measured bytes: FIVE contract corrections, three of them new
    - Candidate A3 -- give the fleet's highest-kill stage the diff-scoping verb it already ships: `gate-scope` into `roles/tester.md`
    - Candidate B1 -- three of the five gate-sentinel parsers collapse onto one anchored-token helper
    - Candidate B2 -- the `exit_code` property written four times becomes one module-level function
    - Candidate B3 -- retire the dominated 60,000-char roadmap budget, so ONE wall guards the index
    winner: A2
    ship: PUSHED 8634b02
  iter-187
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- a pure "killed mid-verification" vs "refused to ship" disposition for the ship gate
    - Candidate B1 -- report an enabled team that the RUNNING dispatcher never saw
    - Candidate C1 -- make `rescues` say WHEN work was last lost, so a healthy loop stops reading red
    - Candidate B2 -- gap-radar phase 1 (`gather_gaps` / `gap_advice` / `pm_gap_block`), read the register JSON directly rather than the uninstalled CLI
    - Candidate B3 -- an adoption ratchet: 45 of 50 shipped CLI verbs have no in-loop consumer
    - Candidate B4 -- inject the test-quality verdict into the tester prompt: 9 scanners the test-writing stage never consults
    winner: unknown
    ship: unknown
  iter-186
    lenses: new-capability, hardening/DX
    - Candidate A1 -- `foundry mutation-probe`: the offline, deterministic half of roadmap item 6
    - Candidate A2 -- `foundry heartbeat`: is the IN-FLIGHT stage still writing, or alive-but-broken?
    - Candidate A3 -- `foundry deadtail`: the wall clock burned after a stage's artifact stops growing
    - Candidate B1 -- `unfailable-asserts`: the 4th test-quality lens, with a LIVE known-bad in tests/
    - Candidate B2 -- guard the ambient-tree PRECONDITION class that turned a green ship post-release BROKEN
    - Candidate B3 -- fold the leak guard into a foundry verb so its exit code cannot be lost in a pipe
    winner: B1
    ship: PUSHED b291238
  iter-185
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- retire roadmap item (p): its stated defect is measurably closed and its figure drifted twice
    - Candidate A2 -- docs must anchor on symbols, not line numbers: 10 of 10 source line citations in docs/ are wrong
    - Candidate A3 -- the decision log asserts ignorance it does not have: 4 of 4 unknown winners are parse failures
    - Candidate B1 -- the push-target guard is PROSE, not code: nothing compares the declared target to the repo's real remote
    - Candidate B2 -- price the DEAD TAIL: the wall clock a stage burns after its required artifact stops growing
    - Candidate B3 -- the story meter has a producer and a reader but NOTHING can advance it
    winner: A1
    ship: PUSHED d1c4589
  iter-184
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A -- `stage-times --limit N`, so the PM's required sizing line prices the CURRENT loop
    - Candidate B -- a `deadtail` report: wall-clock paid AFTER the required artifact stopped growing
    - Candidate C -- price live-lag as a RUN RATE, not a count
    - Candidate B1 -- the invariant doc never names 4 of the 5 verbs the role cards order, incl. `preship`, the one gate that can BLOCK a push
    - Candidate B2 -- "the five invariants" contradicts the six bullets it points at, on four surfaces, with no check
    - Candidate B3 -- five stale present-tense figures in README index prose; make the verb count derived
    winner: B1
    ship: PUSHED 7a8e388
  iter-183
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- collapse the three `gather_*` test-quality scanners onto one shared body
    - Candidate B1 -- collapse the `render` triplet on the three test-quality Summary classes
    - Candidate C1 -- delete the duplicated pinned-head region scan behind `learnings_digest`
    - Candidate B1 -- dispatcher re-execs itself when its loaded foundry.py is stale
    - Candidate B2 -- surface each product's measured suite wall-time to the tester
    - Candidate B3 -- ration the lessons window per role so it covers >1 iteration
    winner: A1
    ship: PUSHED a11b0c0
  iter-182
    lenses: integration-and-adoption (iteration 182), simplification-and-deletion (iteration 182)
    - Candidate A1 -- the reporter seat and STATUS_REPORT.md are unreachable on the path this company actually runs
    - Candidate B1 -- make `foundry agents` non-destructive so item 3's on-ramp becomes runnable at all
    - Candidate C1 -- the tester card consumes the shipped weak-assertion scan it currently ignores
    - Candidate B1 -- one anchored-sentinel rule instead of five
    - Candidate B2 -- the `exit_code` property written four times becomes one function
    - Candidate B3 -- archive the four spent migration notes before the index wall reverts an iteration
    winner: B1
    ship: PUSHED ae0dbd3
  iter-181
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- doctor's learnings-head WARN names the WORST truncated bullet
    - Candidate A2 -- reconcile the two gauges that price the 600s wall and disagree ~7x
    - Candidate A3 -- (placeholder, refining) tests whose domain is `git ls-files`
    - Candidate B1 -- the periodic reporter hand-parses what 8 ledger verbs already answer
    - Candidate B2 -- the reviewer has never been shown the test-quality scanner
    - Candidate B3 -- the `agents` default mode would clobber TRACKED source, and it blocks item 3
    winner: A1
    ship: PUSHED ec0ade8
  iter-180
    lenses: new-capability, hardening/DX
    - Candidate A1 -- `doctor` gains a 5th drift line: the live brain's TEAM ROSTER is stale, and nothing can say so
    - Candidate A2 -- `restore-work`: the framework saves the work its abort path destroys and still cannot give it back
    - Candidate A3 -- make the ship ledger tell in-flight, stranded, and forbidden-token apart
    - Candidate B1 -- the gate ledger reads the wrong tester report: 27 iterations render `tester: FAIL` for rounds that PASSED and shipped
    - Candidate B2 -- re-scope the 27 every-suite byte-freeze guards to an AST/symbol invariant (roadmap item (o))
    - Candidate B3 -- the roadmap index sits 869 chars from a hard wall that reverts a verified iteration for a docs-only reason, and the automated paydown is exhausted
    winner: B1
    ship: PUSHED 55d6640
  iter-179
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- Commit the revert-and-re-land runbook; today its only copy is gitignored
    - Candidate A2 -- ARCHITECTURE.md prices the 30-minute timeout and never mentions the 600-second kill the loop actually survives
    - Candidate A3 -- Three committed artifacts, three different rosters of "the invariants" -- and the divergent one is inlined into every stage prompt
    - Candidate B1 -- `restore-work`: the framework can SAVE the work its abort path destroys and cannot RESTORE it
    - Candidate B2 -- `push-target`: nothing in 18,352 lines checks that the declared push target is the repo git would actually push to
    - Candidate B3 -- name the committed artifacts the pipeline rewrites, so a test stops pinning a moving target
    winner: B1
    ship: PUSHED c32d099
  iter-178
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A2 -- stop the unfinished-checkpoint tester chain from re-paying a whole stage
    - Candidate A3 -- price post-deliverable agent time, and re-scope de-listed item (i) to the report-only stages
    - Candidate A1 -- the learnings digest is 87% of every prompt, and it is over budget while truncating
    - Candidate B1 -- the committed decision log tells GitHub that two shipped iterations never shipped
    - Candidate B2 -- ARCHITECTURE.md never names 4 of the 5 verbs the role cards mandate
    - Candidate B3 -- the roadmap-record duty is named in the PM's card and in no card that outlives it
    winner: B1
    ship: REVERTED
  iter-177
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- collapse `exit_code` x4 in the findings-family roll-ups onto one shared function
    - Candidate B1 -- one anchored-sentinel helper behind the 5 gate parsers
    - Candidate C1 -- two flag helpers retire 33 hand-copied `--config` and 13 `--json` declarations in `main()`
    - Candidate A2 -- inherit `-n auto` from `pyproject.toml` addopts: 71.21 s -> 24.17 s suite, measured green
    - Candidate B2 -- re-price the post-last-write tail: it is 23.56 h and it is NOT where item (i) says it is
    - Candidate C2 -- price the per-stage prompt, the one cost paid on every single attempt
    winner: A2
    ship: PUSHED a5da0f7
  iter-176
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- `foundry adoption`: a derived verb-consumption ledger
    - Candidate B1 -- make `foundry agents` stop silently planting a file in the release diff
    - Candidate C1 -- give the PM's size self-check the measured stage budget, via a role-card line
    - Candidate A1 -- collapse the three `gather_*` test-scanners onto one parametrised gatherer
    - Candidate B1 -- one anchored-sentinel parser instead of four hand-maintained ones
    - Candidate C1 -- retire the frozen-literal allowlist that gates the README-index brake
    winner: C1
    ship: PUSHED 59ce9f4
  iter-175
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- One shared README-index rule in foundry.py, plus a tests/-WIDE guard whose domain is not one file
    - Candidate A2 -- Report WHICH steering bullets never reach a stage prompt (3,198 chars are being cut right now)
    - Candidate A3 -- A calibrated tests/ guard against preconditions on gitignored or ambient tree state
    - Candidate B1 -- roles/pm.md runs `foundry doctor` before it specs (apply the proven preship wiring to the best unconsumed verb)
    - Candidate B2 -- write the one missing file that four shipped consumers are all waiting on (`prd.json`)
    - Candidate B3 -- `--json` on `doctor`, closing the machine-readable contract where it matters
    winner: A1
    ship: PUSHED dff23fc
  iter-174
    lenses: new-capability, hardening/DX
    - Candidate A1 -- `foundry roster`: one verb that says whether every configured team can actually load
    - Candidate A2 -- `foundry delisted`: surface the "do not re-propose" record the scouts cannot see
    - Candidate A3 -- `foundry ignore-source`: is a path ignored PORTABLY, or only on this machine?
    - Candidate B1 -- a genuinely RED retry report must re-enter the fix-tests repair pair, not fall through to the release gate
    - Candidate B2 -- the revert path must name the FOREIGN untracked paths `git clean -fd` is about to delete
    - Candidate B3 -- fail fast on the stale-IPC attempt signature instead of burning the whole retry ladder
    winner: B3
    ship: PUSHED c51c6e3
  iter-173
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- VISION claims "five invariants"; ARCHITECTURE documents six
    - Candidate A2 -- the rescue-recovery runbook exists nowhere a future reader looks
    - Candidate A3 -- `DIRECTIONS.md` prints `ship: unknown` where it knows something narrower
    - Candidate B1 (primary) -- `foundry losses`: name WHY work was lost, not just how often
    - Candidate B2 -- `foundry iteration --iter NN`: one command for "what happened in that iteration"
    - Candidate B3 -- `company-rescues`: the fleet sibling the iter-168 docstring already deferred
    winner: B1
    ship: REVERTED
  iter-172
    lenses: performance-and-throughput (iteration 172), narrative-and-docs (iteration 172)
    - Candidate A1 -- per-stage CAP-PINNED RATE, because the shipped median gauge is saturated
    - Candidate A2 -- (see refined file)
    - Candidate A3 -- (see refined file)
    - Candidate B1 -- the artifact catalog has no entry for the biggest artifact the foundry has built
    - Candidate B2 -- the committed decision log says "unknown" about ships the repo can prove
    - Candidate B3 -- three code comments still name the fixed scout lens pair the rotation retired
    winner: A1
    ship: unknown
  iter-171
    lenses: simplification-and-deletion, performance-and-throughput (iteration 171)
    - Candidate A1 -- collapse the five gate sentinel parsers onto one anchored-last-line rule
    - Candidate A2 -- roadmap item (q) next bite: hoist the x4 identical scanner `exit_code`
    - Candidate A3 -- one order-preserving `to_dict` template for the 7 roll-ups whose key order matches
    - Candidate B1 (primary) -- Price the stale-brain lag in reclaimable hours, from the log the loop already writes
    - Candidate B2 -- Re-measure post-last-write dead time PER STAGE, because the de-listing that killed it may be narrower than written
    - Candidate B3 -- Charge the tester's 120 s-stall retries to the suite, not to the ladder
    winner: B1
    ship: unknown
  iter-170
    lenses: integration-and-adoption (iter 170), simplification-and-deletion
    - Candidate A1 -- fold the dormant `roadmap_spent_blocks` into `doctor`'s `roadmap-index:` line
    - Candidate A2 -- name the foundry checkout in every stage prompt's `## Context` block
    - Candidate A3 -- make `test-quality` trustworthy enough for a role card to consume
    - Candidate B1 -- one arity-explicit sentinel helper replaces the rule written 5 times in the gate parsers
    - Candidate B2 -- collapse the x4 identical `exit_code` bodies onto one shared function (roadmap item (q)'s next bite)
    - Candidate B3 -- the 9 company verbs' identical flag declarations collapse onto two helpers, proven by byte-exact `--help`
    winner: A3
    ship: PUSHED a9a982e
  iter-169
    lenses: hardening/DX -- iteration 169, integration-and-adoption -- iteration 169
    - Candidate A1 -- `foundry ship-landed`: ask the SERVER whether the ship commit is public, so an ambiguous push is never read as a gate failure
    - Candidate A2 -- the steering-head budget gets a NEAR-WALL band: warn at 122 chars of headroom, not after the operator directives are already gone
    - Candidate A3 -- catch the missing per-iteration oracle at the earliest repairable stage (roadmap item (c))
    - Candidate B1 -- make the README verb index a DERIVED contract, and land the two entries it is missing (roadmap item (p))
    - Candidate B2 -- `foundry doctor --json`, and put the framework's own health verb into the documented health-check recipe
    - Candidate B3 -- the reporter seat has never run in the dispatcher era; give the re-grounding report a producer that is not the frozen dispatcher
    winner: B1
    ship: PUSHED b7febf2
  iter-168
    lenses: new-capability, hardening/DX
    - Candidate A1 (primary) -- `foundry salvage`: the rescue patches nothing has ever read, now growing one per iteration
    - Candidate A2 -- the health surface reports 26% of the hard kills, because a rescued kill looks like a clean success
    - Candidate A3 -- `foundry inflight`: which stage is running right now, and how much of its 600 seconds is gone
    - Candidate B1 (primary) -- the committed decision log names the REJECTED candidate as the winner in 7 of 64 rows, and the PM card is why
    - Candidate B2 -- the head row of the decision log can never say whether it shipped, and it says "unknown" rather than "pending"
    - Candidate B3 -- give the final gate a verb that writes the ship token, so a placeholder cannot be typed
    winner: A2
    ship: PUSHED be7d6eb
  iter-167
    lenses: narrative-and-docs, new-capability
    - Candidate A -- the pinned steering head broadcasts a claim this repo falsified 48 iterations ago
    - Candidate B -- retire two false dormancy claims inside ProductConfig, gated by a claim-vs-reader scan
    - Candidate C -- close the README command index against the shipped verb extractor
    - Candidate B1 -- `foundry salvage`: an inventory of the rescue patches nothing has ever read
    - Candidate B2 -- `foundry sentinels`: read the control plane instead of trusting a claim about it
    - Candidate B3 -- `foundry plan`: price the next iteration before spending the shift on it
    winner: B1
    ship: PUSHED 0253a24
  iter-166
    lenses: performance-and-throughput (iter 166), narrative-and-docs (iter 166)
    - Candidate A1 -- suite headroom and slope, priced against the 120s wall before it is crossed
    - Candidate A2 -- the four live-smoke fleet scans cost 22% of the suite and contribute nothing in a clone
    - Candidate A3 -- re-price the parallel suite (roadmap item k), whose stated precondition has since shipped
    - Candidate B1 -- close the README verb index with ONE derived rule; two shipped verbs are documented nowhere
    - Candidate B2 -- the roadmap index is ~3 iterations from reverting an iteration for a docs-only reason, and its own growth figure is unreproducible
    - Candidate B3 -- the committed decision log cannot say which scout won, and its own card is why
    winner: B2
    ship: PUSHED 44c80b1
  iter-165
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- eight per-product CLI printers collapse onto one shared thin-printer body
    - Candidate B1 -- one anchored-sentinel reader replaces five hand-copied gate parsers
    - Candidate C1 -- eight company verdict methods hoist onto the base class they already share
    - Candidate B1 -- price the stale brain in EXCESS SLEEP HOURS, and let a restart zero it
    - Candidate B2 -- the learnings digest is 88% of every stage prompt; budget it by SHARE
    - Candidate B3 -- the two scouts are 23.8% of all agent time for a slate that is 5/6 discarded
    winner: A1
    ship: PUSHED 349c77e
  iter-164
    lenses: integration-and-adoption (iter 164), simplification-and-deletion (iter 164)
    - Candidate A1 -- Close the README verb index with ONE derived rule (two shipped verbs are documented NOWHERE)
    - Candidate A2 -- A role card runs the composite test-quality scan on THIS iteration's own new test file
    - Candidate A3 -- Doctor gains a stage-budget headroom line, so the #1 cause of lost shifts reaches the preflight
    - Candidate B1 -- Retire the `exit_code` x4 hand-copy via a shared property, WITHOUT touching the MRO (roadmap item (q), next bite)
    - Candidate B2 -- One `tests/_shared.py` retires 38 hand-copied `_snapshot_tree` definitions
    - Candidate B3 -- Retire the `FAST_RETRY_KINDS` special case into the general `KIND_RETRY_LADDERS` rule
    winner: A3
    ship: PUSHED a552767
  iter-163
    lenses: hardening/DX -- iteration 163, integration-and-adoption (iteration 163)
    - Candidate A1 (primary) -- a near-wall WARN band for the pinned steering head, mirroring the shipped roadmap-index shape
    - Candidate A2 -- a decidably-scoped fresh-clone-safety guard over tests/, calibrated two-sidedly
    - Candidate A3 -- doctor's oldest check tells the operator a variable name, and separates "never configured" from "configured but gone"
    - Candidate B1 (primary) -- give the dormant `save-work` verb its first real consumer: one runnable line in `roles/engineer.md` (+ `roles/fix.md`)
    - Candidate B2 -- the adopter's status on-ramp points at a file no mode ever writes; re-route it to the shipped `status` verb and brake the class
    - Candidate B3 -- a TRACKED, repo-agnostic launcher that gates on `single-brain` (fail-CLOSED), so a fresh clone can start the loop safely
    winner: B1
    ship: PUSHED fb3e1d1
  iter-162
    lenses: new-capability, hardening/DX
    - Candidate A1 (primary) -- `foundry save-work`: an abort rescue that runs in a fresh process, so live-lag cannot mute it
    - Candidate A2 -- the ship ledger gets a category for an ABANDONED iteration, so destroyed work is countable
    - Candidate A3 -- verbatim retry of iteration 161's `doctor stops:` line, with both known defects pre-solved
    - Candidate B1 -- the steering-head doctor line gets the headroom WARN its sibling already has
    - Candidate B2 -- an assertion-shaped brake on ambient-tree preconditions (roadmap item (s))
    - Candidate B3 -- one whole-output WARN assertion becomes line-scoped, plus a meta-brake
    winner: A1
    ship: PUSHED 8d01fb5
  iter-161
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- retire the four DORMANT claims their own wiring outran, behind a call-site checker
    - Candidate A2 -- the two shipped CLI verbs that no human-facing doc names, plus a coverage guard
    - Candidate A3 -- stop the two frozen figures that git can already contradict
    - Candidate B1 -- the health surface cannot see a STOP sentinel, so a halted team reports OK
    - Candidate B2 -- `foundry attempts`: read the attempt EVIDENCE in the state dir, not the dispatcher log
    - Candidate B3 -- `foundry salvage`: is any reverted iteration's work still recoverable?
    winner: B1
    ship: unknown
  iter-160
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 -- share one AST parse across the 4 live-smoke CLI tests
    - Candidate A2 -- re-price roadmap item (k) parallel suite now that preship exists
    - Candidate A3 -- stage-times reports wasted agent-SECONDS, not just attempt counts
    - Candidate B1 -- the retry ladder is DERIVED from `retry_delay` into both docs, checked line-by-line
    - Candidate B2 -- README's `# N.` command index gains its two missing verbs, behind ONE derived completeness rule
    - Candidate B3 -- ARCHITECTURE.md's ship sequence names the pre-push clone gate, guarded by "a verb a role card orders a stage to run must be documented"
    winner: B1
    ship: PUSHED 9fca86e
  iter-159
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- collapse the nine `company-*` argparse registrations onto one flat loop
    - Candidate A2 -- cap the README Quickstart entry prose against its own `--help`
    - Candidate A3 -- replace the 28-case pre-`load_config` if-chain with one dispatch table
    - Candidate B1 -- parse each test file ONCE and share the tree across the three test-quality lenses
    - Candidate B2 -- gather the test-file list once per product instead of three times
    - Candidate B3 -- retire the two spent 2026-08-04 OPERATOR-SET blocks from the pinned steering head
    winner: B1
    ship: PUSHED fa6483e
  iter-158
    lenses: integration-and-adoption, simplification-and-deletion
    - A1 -- `live-lag` is the only high-value verb whose report exists ONLY as prose: give it `--json` over a frozen record
    - A2 -- `new-product` births a product with a live story meter (the `prd.json` consumer chain has been starved since iter 12)
    - A3 -- wire the dormant config lint into `preflight`, the launch surface an operator already runs
    - B1 -- Retire the roadmap index's superseded blocks: it sits 2,902 chars from a live suite wall
    - B2 -- One sentinel grammar is implemented four times: collapse the verdict parsers
    - B3 -- Three false-green scan gatherers differ only in the detector: parameterise one
    winner: B1
    ship: PUSHED 66bb1f8
  iter-157
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- `foundry roadmap-archive`: a measured, verbatim section-move verb for the index budget
    - Candidate A2 -- the stage prompt carries the product config path, so `--config` verbs in role cards are runnable
    - Candidate A3 -- a timed-out stage attempt keeps the child's partial output instead of a 25-char stub
    - Candidate B1 -- `launch_dispatcher.sh` gates on the shipped `preflight` verb instead of its own fail-open `pgrep`
    - Candidate B2 -- the USAGE.md controls cheat-sheet migrates off raw-file reading, and one row points at a file that has NEVER existed
    - Candidate B3 -- `live-lag` is the one verb whose machine verdict must be scraped from its own prose; give it a structured payload + `--json`
    winner: A2
    ship: PUSHED 6895601
  iter-156
    lenses: new-capability (iter 156), hardening/DX (iter 156)
    - Candidate A1 -- `foundry steer`: a supported writer for the pinned operator steering head, delivery proven by the consumer's own parser
    - Candidate A2 -- `foundry stop`: a structured pause verb over the two STOP sentinels, with `--list` across the fleet
    - Candidate A3 -- `foundry resume-work`: surface and re-apply the abort patches the loop already saves
    - Candidate B1 -- `preship`: run the verifier's environment as a gate BETWEEN the commit and the push
    - Candidate B2 -- a calibrated brake on ambient-tree preconditions in `tests/` (roadmap item (s))
    - Candidate B3 -- make the per-iteration behavior test a CHECKED precondition (roadmap item (c))
    winner: B1
    ship: PUSHED 9ba9b4b
  iter-155
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- Derive the retry-ladder figures in ARCHITECTURE.md / CONTINUOUS.md from the constants, plus a live drift brake
    - Candidate B1 -- One derived README-verb-index rule, replacing iteration 117's hand-written per-verb assertion, and the missing `new-product` entry
    - Candidate C1 -- Correct the two stale claims iteration 154's release gate deferred, at their exact recorded sites
    - Candidate A1 -- `foundry sentinels [--json]`: make the control plane's CONTENT readable, and give it a consumer
    - Candidate B1 -- A forensic witness block on every no-output attempt log -- plus a MEASURED FALSIFICATION of the standing fix
    - Candidate C1 -- `foundry recover [--json]`: make a reverted iteration's preserved patch findable and its retry decidable
    winner: unknown
    ship: PUSHED c82e5c9
  iter-154
    lenses: performance-and-throughput (iteration 154), narrative-and-docs
    - A1 -- Make the tree-snapshot test bounded: 6574-file double walk, 3rd slowest test, and flaky by design
    - B1 -- Parallel suite for the build stages only, on a fresh 2.63x measurement (roadmap item (k))
    - C1 -- Shrink the payload every attempt pays: the pinned head is 92.5% full and part of it is spent
    - A1 -- ARCHITECTURE.md and CONTINUOUS.md price ONE retry ladder; the code ships THREE, and the documented one fires for 17% of real retries
    - B1 -- 46 CLI verbs, 46 numbered README entries, and `new-product` appears NOWHERE in the README
    - C1 -- the budget that actually kills stages is documented in 8 agent prompts and 0 human-facing docs
    winner: A1
    ship: PUSHED 18d28ee
  iter-153
    lenses: simplification-and-deletion, performance-and-throughput (iteration 153)
    - A1 -- one counts mixin retires 27 hand-copied properties across the 9 company roll-up classes
    - B1 -- state the dispatch-order rule once, delete the 20 restatements accreted inside main()
    - C1 -- the eight single-product report printers collapse onto one shared printer
    - Candidate B1 -- collapse the 5 near-duplicate live-smoke tests onto one cached fixture
    - Candidate B2 -- a measured suite wall-time budget with a doctor line
    - Candidate B3 -- TBD (refining)
    winner: A1
    ship: PUSHED 6430ba4
  iter-152
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- doctor grows a fourth drift line so the stage-budget WARN reaches the operator
    - Candidate A2 -- the brain scan counts processes that only MENTION the dispatcher
    - Candidate A3 -- the launch wrapper gates on the shipped preflight instead of its own pgrep
    - Candidate B1 -- the shared roll-up body absorbs the three `company_*_cli` stragglers
    - Candidate B2 -- 39 byte-identical copies of `_snapshot_tree` become one shared test helper
    - Candidate B3 -- retire the `FAST_RETRY_KINDS` special case into the general per-kind ladder
    winner: B1
    ship: PUSHED 4067258
  iter-151
    lenses: hardening/DX -- iteration 151, integration-and-adoption (iteration 151)
    - Candidate A1 -- capture the implementation diff before `revert_repo` hard-resets it
    - Candidate A2 -- one total text-read seam, replacing four inconsistent guard idioms
    - Candidate A3 -- price the 120s silence watchdog, the wall that is actually killing stages
    - Candidate B1 -- one derived rule for the README command index, plus the one verb missing from it
    - Candidate B2 -- one dispatcher-liveness probe, and make the launcher consult the gate that exists
    - Candidate B3 -- feed the story meter the dispatcher already reads every shift
    winner: A1
    ship: PUSHED bc86d58
  iter-150
    lenses: new-capability, hardening/DX
    - Candidate A1 -- read-only `foundry stops`: make a PAUSED company visible
    - Candidate A2 -- `foundry exhaustion`: flag a team that has run out of real work
    - Candidate A3 -- product build-readiness probe before a new repo burns shifts
    - Candidate B1 -- name the 120 s stall ceiling as a constant and give the suite a countdown to it
    - Candidate B2 -- put the anti-stall testing discipline into roles/tester.md, policed by a live brake
    - Candidate B3 -- a foundry-side forensic header on every attempt log
    winner: A1
    ship: unknown
  iter-149
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- ARCHITECTURE section 3 "Resilience" tells the truth about retry timing: real per-kind ladders plus the binding ~600s cap
    - Candidate A2 -- the prompt-inlined quality_bar stops naming two invariants that do not exist
    - Candidate A3 -- one derived README verb-index rule, replacing a per-verb literal that can only ever police one verb
    - Candidate B1 -- `foundry stop` / `foundry resume`: give the STOP control plane a CLI that forces owner, reason and lift condition
    - Candidate B2 -- `foundry retry-advice`: name WHY an iteration did not ship, and whether it is re-doable verbatim
    - Candidate B3 -- `foundry roadmap-record`: write BOTH roadmap records atomically, or write neither
    winner: A2
    ship: PUSHED d47275a
  iter-148
    lenses: performance-and-throughput, narrative-and-docs -- iteration 148
    - A1 -- stage-times reports a failure-KIND ledger and prices the retry sleep
    - A2 -- a slope-triggered suite-growth advisory, not a fixed 120 s wall
    - A3 -- bound the digest share of the stage prompt
    - Candidate B1 -- two design docs price a retry ladder that misdescribes 130 of 151 real retries
    - Candidate B2 -- the ~600s agent-CLI cap, the constraint that shaped all 8 role cards, is explained in no design doc
    - Candidate B3 -- the prompt-inlined quality_bar names two invariants ARCHITECTURE.md does not have
    winner: A1
    ship: PUSHED 525783a
  iter-147
    lenses: simplification-and-deletion (iteration 147), performance-and-throughput
    - Candidate A1 -- finish iteration 146: the last three `company_*_cli` bodies become thin wrappers too
    - Candidate A2 -- one shared body behind the three test-scan gatherers
    - Candidate A3 -- one pure `sentinel_remainder` behind the five gate-sentinel parsers
    - Candidate B1 -- anchored review-gate trigger: stop firing a fix-review pass on an APPROVE
    - Candidate B2 -- live-lag is 25 iterations, so every shipped throughput fix is inert
    - Candidate B3 -- reclaim the engineer stage's in-stage verification cost
    winner: B1
    ship: PUSHED 5811610
  iter-146
    lenses: integration-and-adoption (iteration 146), simplification-and-deletion
    - Candidate A1 -- the reviewer card runs a shipped test-quality diagnostic
    - Candidate A2 -- `live-lag --json`, with the WARN outcome derived from the same token as the exit code
    - Candidate A3 -- the dormant RESTART_NEEDED flag gets its first LEGAL producer, in `watchdog.py`
    - Candidate B1 -- collapse the six byte-identical `company_*_cli` bodies into one shared body + six thin wrappers
    - Candidate B2 -- delete 27 byte-identical copies of `_snapshot_tree` into one shared test helper module
    - Candidate B3 -- retire the superseded 60,000 wall's three live-index brakes, so one file has one wall
    winner: B1
    ship: PUSHED b8116d9
  iter-145
    lenses: hardening/DX, integration-and-adoption (iteration 145)
    - Candidate A1 -- the roadmap brake that actually reverts an iteration is a bare literal; the budget the tools report is 7,313 chars too generous
    - Candidate A2 -- `build_prompt` still recomputes the digest that iteration 144 extracted; make the drift IMPOSSIBLE instead of merely detectable
    - Candidate A3 -- `foundry stage-times` never says WHY a stage died, and the retry waits it cannot see cost 13.25 h of sleep in 6.35 days
    - Candidate B1 -- `foundry status` reports the stage-budget WARN it already has an alarm for
    - Candidate B2 -- give iteration 24/28's launch gate its first real consumer: a tracked, portable launcher
    - Candidate B3 -- the operator cheat-sheet migrates from the manual way to the shipped verbs, with a drift brake
    winner: A1
    ship: PUSHED e461577
  iter-144
    lenses: new-capability (iteration 144), hardening/DX
    - Candidate A1 -- read-only `foundry prompt`: render the exact bytes a stage receives
    - Candidate A2 -- read-only `foundry stops`: enumerate and validate the STOP control plane
    - Candidate A3 -- preserve partial stage output: dormant streaming attempt-log core (bite 1 of 2)
    - Candidate B1 -- the anti-stall test discipline moves from the rotating learnings head into the four cards that mandate a suite run
    - Candidate B2 -- a missing `tests/test_iterNN*.py` becomes repairable instead of fatal (roadmap item (c), still open)
    - Candidate B3 -- re-scope the 27 control-path freeze guards from a path byte-diff to a symbol invariant (roadmap item (o))
    winner: A1
    ship: PUSHED a001c40
  iter-143
    lenses: narrative-and-docs (iteration 143), new-capability
    - Candidate A -- ARCHITECTURE's Resilience invariant states a retry ladder the code stopped using two shipped iterations ago
    - Candidate B -- four artifacts claim "five invariants" and name three different sets, including the one every platform prompt carries
    - Candidate C -- the README command index, the record of every shipped CLI verb, silently skipped the verb iteration 137 shipped
    - Candidate B1 -- stage-level resume of an abandoned iteration (report-only bite 1)
    - Candidate B2 -- give the fleet's shipped progress meter its first data: generate a `prd.json`
    - Candidate B3 -- a machine-readable per-attempt evidence envelope
    winner: B2
    ship: PUSHED ad632e0
  iter-142
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 -- optional fast in-stage test command; the gates keep the declared serial one
    - Candidate A2 -- bounded open-items view of the roadmap, so the repeated read stops costing 53,415 chars
    - Candidate A3 -- a timed-out attempt keeps its transcript
    - Candidate B1 -- the card mandates a `foundry` command that does not exist
    - Candidate B2 -- the Resilience bullet still prices one retry ladder, and never names the cap that actually kills stages
    - Candidate B3 -- the prompt-inlined `quality_bar` names two invariants that exist in no document
    winner: B1
    ship: PUSHED ad23b2c
  iter-141
    lenses: simplification-and-deletion (iteration 141), performance-and-throughput (iteration 141)
    - Candidate A1 -- restore the 583 over-moved chars and pay for them by archiving a superseded section
    - Candidate A2 -- collapse seven byte-identical rollup constructors into one general rule
    - Candidate A3 -- compact eight stacked STATUS paragraphs into one watermark line plus live clauses
    - Candidate B1 -- restart-on-lag detector: 19 shipped iterations are NOT executing in the live brain
    - Candidate B2 -- concurrent scout stages behind a default-off flag (measured 476s = 14.1% of an iteration)
    - Candidate B3 -- windowed throughput report so a per-stage regression is visible while it happens
    winner: B1
    ship: PUSHED 7042af6
  iter-140
    lenses: integration-and-adoption (iteration 140), simplification-and-deletion (iteration 140)
    - Candidate A1 -- preflight, the launch gate, drops both drift lines doctor prints, incl. an 18-iteration-stale brain
    - Candidate A2 -- the dispatcher roster is the one config nothing lints, and the only linter gives it destructive advice
    - Candidate A3 -- iter-09's AGENTS.md renderer has produced zero artifacts in 131 iterations
    - Candidate B1 -- collapse the nine company_*_cli bodies; the executable variation is 5 lines, not 37
    - Candidate B2 -- archive the completed roadmap prose; the index is 4.5 iterations from failing the suite
    - Candidate B3 -- one general last-line sentinel parser replaces five special cases (139 lines)
    winner: A2
    ship: PUSHED a621ade
  iter-139
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- the two gate role cards still order the behavior that lost four iterations
    - Candidate A2 -- parse_triage_winner reads the winner ids the PMs actually write
    - Candidate A3 -- an attempt log that describes itself, so a 600s kill leaves evidence
    - Candidate A1 -- every stage prompt carries the one foundry-CLI invocation that actually works
    - Candidate B1 -- the operator's launcher gates on the composite preflight verdict
    - Candidate C1 -- foundry agents renders an AGENTS.md that exists nowhere; give it a real reader
    winner: A1
    ship: PUSHED 3e17d63
  iter-138
    lenses: new-capability, hardening/DX
    - Candidate A -- foundry trust: name the verdicts no transcript ever backed
    - Candidate B -- foundry verify: is main deployable RIGHT NOW, without waiting for a ship
    - Candidate C -- foundry sentinels: the pause control plane has no read-out
    - Candidate B1 -- make the PM card's two MANDATED foundry commands actually runnable from a stage
    - Candidate B2 -- doctor reports NOT READY on a healthy fleet (false alarm in the pre-flight verb)
    - Candidate B3 -- the pinned prompt head is CORRUPTED in delivery, not merely over budget
    winner: B3
    ship: PUSHED ff0aa10
  iter-137
    lenses: narrative-and-docs, new-capability
    - A1 -- Docs price the retry ladder at one ladder; 83.6% of real failures now draw a different one
    - B1 -- The quality bar inlined into every stage prompt names two invariants ARCHITECTURE.md has never defined
    - C1 -- The public artifacts catalog credits the foundry with 1 product; it has shipped 4, one of them to completion
    - B1 -- `foundry pin`: delivery-verified operator steering, because a hand-written pin can silently delete the entire steering channel
    - B2 -- `foundry new-product`: the VISION's headline promise has no command, and the documented recipe fails with exit 1
    - B3 -- `foundry retire`: the sentinel control plane is invisible to git and to the health probe
    winner: B2
    ship: PUSHED f2e5239
  iter-136
    lenses: performance-and-throughput (iteration 136), narrative-and-docs
    - A1 -- Activate-on-lag: make the live brain execute the retry pricing it already shipped
    - A2 -- Run the two independent PM scouts concurrently instead of back-to-back
    - A3 -- Cut the suite from 46.6 s to 17.0 s so the silent-command stall cannot reach 120 s
    - Candidate B1 -- Retire the spent operator directives; both artifacts still say the discovery loop was never built
    - Candidate B2 -- The invariants doc still prices a retry ladder the code stopped using two iterations ago
    - Candidate B3 -- The PM role card mandates a command that cannot run
    winner: B1
    ship: PUSHED 1c4568a
  iter-135
    lenses: simplification-and-deletion (iteration 135), performance-and-throughput
    - A1 -- Collapse the Company{WeakTests,ConstantAsserts,SkippedTests} triplet onto one shared frozen base
    - A2 -- Replace the duplicated argparse flag boilerplate in main() with three shared arg-adders
    - A3 -- Roadmap item (i), narrowed to the six same-signature company_*_cli bodies
    - B1 -- Make the quality-check command parallel: 46.84s -> 16.76s per verify
    - B2 -- Put the `stalled` failure kind on the fast retry ladder: 3.8h of fleet-wide sleep -> 0.4h
    - B3 -- Give the inlined learnings digest a TOTAL character budget, not two stacked ones
    winner: B2
    ship: PUSHED 9dc9849
  iter-134
    lenses: integration-and-adoption (iteration 134), simplification-and-deletion (iteration 134)
    - Candidate A1 -- `lint-config` reports a typo'd config key as a FINDING (exit 1), not as "cannot read config" (exit 2)
    - Candidate A2 -- name the runnable foundry CLI in every stage prompt, so 40 shipped verbs stop being unreachable
    - Candidate A3 -- the committed decision log records WHICH candidate won (and refuses to invent one)
    - B1 -- collapse the nine near-identical `company_*` roll-up CLI bodies into one shared seam
    - B2 -- consolidate the 26 every-suite control-path freeze guards into one
    - B3 -- retire the completed discovery-loop directive to a short, accurate stub
    winner: A1
    ship: PUSHED d4b1599
  iter-133
    lenses: hardening/DX, integration-and-adoption
    - A1 -- Finish the decision log's WINNER half: marker precedence, and drop the cross-validation nobody needs
    - A2 -- Two of the six live scout lenses are defined; the other scout in THIS iteration is running an undefined one
    - A3 -- Name the auth failure kind: the loop currently retries, and then re-enters, a wall only a human can move
    - B1 -- The push contract with an adopted repo is prompt-only: verify it against the real remote before the shift
    - B2 -- The house rules never reach the adopted repo: wire the AGENTS.md refresh (roadmap item 3, bite 2)
    - B3 -- Strangler step 3: the stage retry path delegates to the public library (integration, not a copy)
    winner: A2
    ship: PUSHED b6774f9
  iter-132
    lenses: new-capability (iteration 132), hardening/DX
    - Candidate A1 -- Finish the decision log's WINNER half: a strict-fallback, cross-validated triage-winner rule
    - Candidate A2 -- `foundry new-product`: turn the VISION's "point it at any git repo" into an actual command
    - Candidate A3 -- Record the REJECTED alternative and the reason it lost -- the half of bite 4 that never shipped
    - B1 -- Re-anchor the every-suite freeze-guard meta-test on guard BEHAVIOR, not the exact guard name
    - B2 -- Define the 4 undefined scout lenses in roles/pm_scout.md, bound to the pool by a suite test
    - B3 -- Ground-truth the test gate: an earned PASS with no oracle file on disk
    winner: A1
    ship: PUSHED 65c428e
  iter-131
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- Teach the decision log the candidate-heading shapes scouts actually write (32 of 135 slates currently render as zero candidates)
    - Candidate A2 -- Define the 4 undefined scout lenses, and retire the fixed a/b mapping three tracked docs still assert as fact
    - Candidate A3 -- Pin the README verb catalog with a suite test, so a missing verb fails at the tester instead of at the gate
    - Candidate B1 -- Recover a killed stage's real transcript from the agent CLI's own artifact store, since streaming its stdout provably cannot work
    - Candidate B2 -- Let the loop say "this box needs a human": name an auth failure kind and stop the product instead of burning the shift
    - Candidate B3 -- `foundry new-product`: make the VISION's "point it at any git repo" an actual command
    winner: A1
    ship: PUSHED 1f9353a
  iter-130
    lenses: performance-and-throughput (iteration 130), narrative-and-docs
    - Candidate A -- give `stalled` its own retry ladder (fast first retry, long thereafter)
    - Candidate B -- first-write telemetry: probe whether the deliverable exists mid-attempt
    - Candidate C -- fix the mandatory-tooling tax every PM stage pays (verified live this run)
    - Candidate B1 -- The scout role card defines 2 of the 6 live lenses; half of all iterations run BOTH scouts on an undefined lens
    - Candidate B2 -- The decision log silently drops what it cannot parse: 8 of 54 scout slates render as ZERO candidates
    - Candidate B3 -- "Shipped" is not "live": 8 shipped iterations are inert in the running brain and no artifact says so
    winner: B3
    ship: PUSHED a734465
  iter-129
    lenses: simplification-and-deletion, performance-and-throughput
    - A1 -- Collapse the nine `company_*_cli` bodies onto ONE generic roll-up driver (bite 1 = the six uniform ones)
    - A2 -- Table-driven registration for the nine `company-*` argparse blocks in `main()`
    - A3 -- Consolidate the 26 every-suite control-path freeze guards to one canonical guard (I MEASURED AWAY ITS MAIN SELLING POINT)
    - B1 -- Failure-kind-aware retry delay: stop paying a 10/20/40-minute rate-limit sleep for a stage that was killed by the 600 s cap
    - B2 -- Run the full-suite gate command in parallel (`-n auto`), and ONLY the full-suite command (I measured the obvious version and it is 5.7x SLOWER)
    - B3 -- Flatten the useless retry tail: attempts 3 and 4 won 2 of 547 stage-runs while costing 8.33 h of sleep
    winner: B1
    ship: PUSHED c9eb30d
  iter-128
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- fail-closed unknown-key guard at config LOAD time
    - Candidate A2 -- deliver roadmap item 3's payoff: refresh AGENTS.md at ship time, leak-safely
    - Candidate A3 -- `foundry adopt`: one-command onboarding for a new repo
    - Candidate B1 -- collapse 26 duplicated every-suite freeze guards into ONE, and stop the meta-test that polices them from failing open
    - Candidate B2 -- delete the fail-silent winner heuristic in `parse_triage_winner`; read the PM's own PICK line
    - Candidate B3 -- collapse the 9-member `company_*_cli` clone family behind one parameterized fan-out
    winner: A1
    ship: PUSHED 54a8ecb
  iter-127
    lenses: hardening/DX — iteration 127 (CHECKPOINT, refining in place), integration-and-adoption -- iteration 127
    - Candidate A — route the test-gate trigger through ONE anchored seam
    - Candidate B — make every command a role card mandates actually runnable in a stage
    - Candidate C — repair a missing iteration test file at the earliest repairable stage
    - Candidate B1 -- surface the config keys `load_config` silently swallows
    - Candidate B2 -- refresh the product repo's AGENTS.md on ship (roadmap item 3, bite 2 of 2)
    - Candidate B3 -- `foundry init-product`: the missing onramp for a new repo
    winner: B1
    ship: PUSHED a476d7e
  iter-126
    lenses: new-capability -- iteration 126, hardening/DX -- iteration 126
    - Candidate A -- a first-class operator directive inbox (`DIRECTIVES.md`), race-free, injected into the PM lead prompt
    - Candidate B -- reverted-but-verified work becomes a platform artifact (`RETRY_AVAILABLE` advisory flag)
    - Candidate C -- `foundry adopt`: one-command product onboarding
    - Candidate B1 -- teach the test gate the difference between RED and UNFINISHED, and spend the repair round on the tester
    - Candidate B2 -- one anchored test-gate predicate instead of two unanchored copies
    - Candidate B3 -- make the checkpoint contract real in the cards: the TEST FILE is the artifact, and never emit a sentinel you have not earned
    winner: B1
    ship: PUSHED 2ee80ca
  iter-125
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- The scout role card defines 2 of the 6 rotated lenses, and three tracked docs still assert the retired fixed a/b lens mapping
    - Candidate A2 -- The decision log records `ship: unknown` for iterations that git PROVES shipped
    - Candidate A3 -- 7 of the 18 pinned-head directives will be delivered cut mid-sentence the moment the dispatcher restarts
    - Candidate B1 -- Retry iteration 121: its preserved patch still applies cleanly to HEAD, and only the missing test file blocked it
    - Candidate B2 -- A per-product FAST test command for the build stages, so the full suite stops being every stage's tax
    - Candidate B3 -- Make every stage budget-aware: give the prompt its wall-clock deadline plus this stage's own measured attempt history
    winner: B1
    ship: REVERTED
  iter-124
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate C1 -- Parallelise the suite: `-n auto` via pytest-xdist in the quality bar
    - Candidate C2 -- Per-product `fast_test_cmd` for the build stages
    - Candidate C3 -- Bounded in-prompt code map (cut agent time-to-context)
    - Candidate B1 -- Close the roadmap contract's missing third leg: a shipped iteration with no Done-ledger row
    - Candidate B2 -- The decision log records `ship: unknown` for iterations that provably PUSHED
    - Candidate B3 -- The scout card defines 2 of 6 rotated lenses, and two tracked docs state the wrong mapping
    winner: B1
    ship: PUSHED 0b26349
  iter-123
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- Collapse the 9 near-identical `summarize_company_*` roll-ups behind one parameterized helper
    - Candidate A2 -- Replace the 9 hand-copied `company-*` argparse blocks in `main()` with one declarative table
    - Candidate A3 -- Put a consumer registry on the CLI surface so the 39 verbs stop multiplying
    - Candidate B1 -- Failure-cause-aware retry delay (dormant classifier + policy + waste digest)
    - Candidate B2 -- Per-product `fast_test_cmd` for the build stages (dormant config field)
    - Candidate B3 -- Make the loop consume its own stage-times WARN (advisory flag, proven lifecycle)
    winner: B1
    ship: unknown
  iter-122
    lenses: integration-and-adoption (iteration 122), simplification-and-deletion (iteration 122)
    - Candidate A1 -- per-product FAST stage test command (`fast_test_cmd`) in the stage prompt
    - Candidate A2 -- make the foundry CLI actually invocable from inside a stage
    - Candidate A3 -- repair the adoption on-ramp (`USAGE.md` Recipe A), optionally behind a print-only `foundry onboard`
    - Candidate B1 -- Split PLATFORM_ROADMAP.md into a terse INDEX + PLATFORM_ROADMAP_ARCHIVE.md, with a char budget the SUITE enforces
    - Candidate B2 -- Collapse the 9 near-identical `summarize_company_*` roll-ups into one parameterized helper (bite 1 of the company-* de-duplication)
    - Candidate B3 -- Put a lid on the CLI surface: every registered verb must have a named consumer, or be an explicitly allow-listed human-operator tool
    winner: B1
    ship: PUSHED efddc28
  iter-121
    lenses: hardening/DX, integration-and-adoption
    - CANDIDATE A -- teach `run_stage` that a self-declared provisional artifact from a CRASHED attempt is not a finished stage
    - CANDIDATE B -- retry iteration 120 (the dispatcher stale-import adoption advisory), re-derived rather than re-applied
    - CANDIDATE C -- bound the 2.66 MB `LEARNINGS.md` by rotation into `LEARNINGS_ARCHIVE.md`
    - CANDIDATE A -- `stage_test_cmd`: let a product declare a stage-budget-safe check for the CAPPED agent stages
    - CANDIDATE B -- make the foundry's own CLI invocable from inside a stage
    - CANDIDATE C -- close the ACTIVATION gap on the shipped IPC endpoint self-heal (doc + `doctor` check)
    winner: unknown
    ship: REVERTED
  iter-120
    lenses: new-capability, hardening/DX
    - Candidate C1 -- The loop cannot adopt its own shipped code: surface stale-import drift
    - Candidate C2 -- Never-silent unattended runs: a `notify_cmd` outbound hook
    - Candidate C3 -- `foundry goal`: an operator-intent channel with its own budget
    - H1 -- Name the CAUSE of a zero-output stage attempt (pure classifier + recorded elapsed/exit)
    - H2 -- Ship the WORKING `foundry` CLI invocation into every stage prompt
    - H3 -- Make the shipped IPC self-heal's DORMANCY visible (config-drift check via `preflight`)
    winner: C1
    ship: REVERTED
  iter-119
    lenses: narrative-and-docs, new-capability
    - Candidate C1 -- Define all six scout lenses in the scout card, and retire the dead two-lens mapping (with a pool-vs-card oracle)
    - Candidate C2 -- Stop the decision log silently dropping candidate slates (heading contract + a precise candidate-heading predicate)
    - Candidate C3 -- Split the README front door from its 37KB command reference (with a verb-coverage + size oracle)
    - Candidate B1 -- Attempt-aware retry: escalate the stage prompt after a zero-output attempt
    - Candidate B2 -- Per-product FAST build-stage test command (with its motivating evidence honestly expired)
    - Candidate B3 -- `foundry init`: scaffold a new product from a repo path in one command
    winner: B1
    ship: PUSHED 1fedfb5
  iter-118
    lenses: performance-and-throughput, narrative-and-docs
    - C1 -- Cause-aware retry backoff (classify the attempt failure, then pick the ladder)
    - C2 -- Close the `## Patterns` head exemption in the prompt char budget
    - C3 -- Per-product FAST build-stage test command (operator-proposed 2026-08-04)
    - B1 -- Make the tracked DIRECTIONS.md decision log survive the ship (defect fix)
    - B2 -- `foundry lint-docs`: a mechanical oracle for gate 5's "README is accurate"
    - B3 -- Split the README front door from the 43-entry command reference
    winner: C2
    ship: PUSHED (per git)
  iter-117
    lenses: new-capability, hardening/DX
    - Candidate C1 -- `foundry init`: the product-onboarding front door (bite 1 = pure scaffold renderer + read-only preview)
    - Candidate C2 -- `foundry pause <product> [--reason R]`: a guarded, well-formed per-team STOP writer (the offboarding verb, symmetric to init)
    - Candidate C3 -- `foundry goal "<text>"`: an append-only operator steering channel for the "weekly-defined goal"
    - Candidate B1 -- `foundry stage-times`: per-stage duration observability CLI (operator fix #2, priority-2 of three)
    - Candidate B2 -- `foundry doctor` stale-IPC-endpoint advisory (completes the iter-114 self-heal)
    - Candidate B3 -- fix `roles/pm.md` lint-spec invocation (kill a recurring per-PM-turn tax)
    winner: B1
    ship: PUSHED 705388a
  iter-116
    lenses: new-capability, hardening/DX
    - Candidate C1 -- Wire discovery bite 4b: append a dated decision block to a TRACKED DIRECTIONS.md on every scouted iteration
    - Candidate C2 -- `foundry init <repo> [--name N]`: the product-onboarding front door
    - Candidate C3 -- `foundry goal "<text>"`: an operator steering channel for the "weekly-defined goal"
    - B1 — `foundry doctor` stale-IPC-endpoint advisory (completes the iter-114 self-heal)
    - B2 — role-card `foundry lint-spec` invocation fix (DX paper-cut, prose + content-test)
    - B3 — preserve partial stage output on a 600s kill (operator fix #3)
    winner: C1
    ship: PUSHED ebcaff9
  iter-115
    lenses: new-capability, hardening/DX
    - Candidate C1 -- `foundry directions`: the DIRECTIONS.md decision-log render CLI (discovery bite 4a)
    - Candidate C2 -- `foundry init <target>`: one-command product onboarding scaffolder
    - Candidate C3 -- `foundry vision-check`: the INTENT-doc (VISION.md) linter
    - Candidate B1 — `foundry stage-times [--config C] [--json]`: per-STAGE attempt-duration digest + `STAGE_SOFT_BUDGET` WARN
    - Candidate B2 — extend `foundry doctor` with a stale-IPC-endpoint WARN check
    - Candidate B3 — prose-only DX fix: give `roles/pm.md` the WORKING `lint-spec` invocation
    winner: C1
    ship: PUSHED e54b5ab
  iter-114
    lenses: new-capability (iter 114), hardening/DX
    - Candidate 1 -- `foundry directions` : the human-readable decision log (bite 4)
    - Candidate 2 -- `foundry init <target>` : scaffold a new product onto any repo
    - Candidate 3 -- `foundry vision-check [--config C]` : validate a product's intent doc
    - Candidate B1 — Wire the dormant `resolve_agent_endpoint` into `run_stage` (self-healing agent IPC endpoint)
    - Candidate B2 — `foundry stage-times [--json]` read-only per-stage duration digest + `STAGE_SOFT_BUDGET` WARN
    - Candidate B3 — Fix the `roles/pm.md` `foundry lint-spec` PATH paper-cut (prose-only card fix)
    winner: B1
    ship: PUSHED 27b2bbb
  iter-113
    lenses: unknown
    - Candidate 1 -- Wire live lens rotation into the scout pre-phase (complete discovery bite 2)
    - Candidate 2 -- `foundry directions` + `DIRECTIONS.md` decision log (discovery bite 4)
    - Candidate 3 -- `foundry init <name> --repo <url>` product scaffolder
    - Candidate B1 -- `foundry stage-times [--json]`: read-only per-stage attempt-duration digest + soft-budget WARN
    - Candidate B2 -- Preserve partial stage output on timeout in `run_stage` (operator fix #3)
    - Candidate B3 -- Fix the `roles/pm.md` `foundry lint-spec` PATH paper-cut (prose-only)
    winner: B1
    ship: PUSHED 6956a53
  iter-112
    lenses: new-capability (iteration 112), hardening/DX (iteration 112)
    - Candidate C1 -- `foundry directions [--json]`: the decision-digest renderer (bite 4a, dormant-first)
    - Candidate C2 -- wire the 6-lens rotation into the LIVE scout phase (bite 2 completion)
    - Candidate C3 -- `foundry new-product --dry-run`: scaffold a product config for any repo
    - Candidate B1 -- put the WRITE-EARLY checkpoint rule in EVERY role card (roles/*.md)
    - Candidate B2 -- `foundry stage-times [--json]`: per-stage attempt-duration digest + soft-budget WARN
    - Candidate B3 -- re-wire `resolve_agent_endpoint` into run_stage's subprocess `env=` (the reverted-but-correct iter-111 fix)
    winner: B1
    ship: PUSHED e81b95e
  iter-111
    lenses: new-capability, hardening/DX
    - C1 (primary) — Bite 4a: DORMANT `render_directions_block` pure renderer + frozen `DirectionsRecord`
    - C2 — Bite 4a data source (prose-scan): DORMANT `directions_record_from_state(state_dir, plan)`
    - C3 — Bite 4a data source (structured contract): PM decision-footer + DORMANT `parse_decision_footer`
    - C1 — Wire `resolve_agent_endpoint` into `run_stage`'s subprocess env (IPC self-healing) [highest value]
    - C2 — `fast_test_cmd` per-product config field (DORMANT foundation)
    - C3 — Surface a stale inherited IPC endpoint as an operator early-warning (read-only) [weakest]
    winner: C1
    ship: REVERTED
  iter-110
    lenses: new-capability (iter 110), hardening/DX (iter 110)
    - Candidate slate (new-capability lens)
    - Candidate slate (hardening/DX lens)
    winner: C1
    ship: PUSHED d1becb6
  iter-109
    lenses: hardening/DX (iter 109)
    - Candidate C1 — Wire lens rotation into the LIVE scout pre-phase (discovery bite 2, the "pedal")
    - Candidate C2 — `DIRECTIONS.md` decision log, fully wired (discovery bite 4)
    - Candidate C3 — `DIRECTIONS.md` DORMANT foundation only (resume-safe de-risk split of C2)
    - Candidate C1 -- `resolve_agent_endpoint` pure resolver (DORMANT foundation, no wiring)
    - Candidate C2 -- strangler STEP 4: watchdog delegates to the library `decide`/`supervise`
    - Candidate C3 -- per-product `fast_test_cmd` config field (DORMANT foundation)
    winner: C1
    ship: unknown
  iter-108
    lenses: new-capability (iter 108)
    - Candidate C1 -- WIRE the lens rotation into the live scout pre-phase (bite 2 of 2)
    - Candidate C2 -- DIRECTIONS.md live decision-log append (bite 4)
    - Candidate C3 -- make the RUT directive actionable via recent-lens history
    - Candidate C1 -- Strangler STEP 4: watchdog.py delegates `decide` to the library
    - Candidate C2 -- Strangler STEP 2: dispatcher.py delegates scheduling to `Scheduler`
    - Candidate C3 -- Write-side lesson-size cap (directive + patchable constant)
    winner: C1
    ship: unknown
  iter-107
    lenses: new-capability (iter 107), hardening/DX (iter 107)
    - Candidate C1 -- Bite 2: deterministic lens-rotation pool (FULL slice)
    - Candidate C2 -- Bite 2 as a SPLIT: dormant foundation only (BITE 1 of 2)
    - Candidate C3 -- Bite 4: DIRECTIONS.md decision-log builder + read-only `foundry directions` reader (dormant)
    - Candidate C1 -- Strangler STEP 4: delegate watchdog decide/relaunch to the library
    - Candidate C2 -- Write-side lesson-size cap directive (constant + prompt-inline, NO CLI)
    - Candidate C3 -- Strangler STEP 2: dispatcher round-robin -> library Scheduler (high-value, higher-risk)
    winner: C1
    ship: PUSHED 1231993
  iter-106
    lenses: new-capability, hardening/DX
    - Candidate C1 -- Bite 3b: wire the novelty verdict into the PM stage (the pedal)
    - Candidate C2 -- Bite 2: deterministic 6-lens rotation pool
    - Candidate C3 -- Bite 4: DIRECTIONS.md decision log + `foundry directions` reader
    - Candidate C1 -- Strangler STEP 4: delegate `watchdog.decide` to the library
    - Candidate C2 -- Regression test: build_prompt inlines a CHARACTER-BOUNDED digest
    - Candidate C3 -- Cap new lesson-bullet size at the WRITE side (root-cause DX)
    winner: C1
    ship: PUSHED 875caed
  iter-105
    lenses: new-capability, hardening/DX
    - Candidate 1 -- `foundry novelty-check [--json]` (discovery bite 3, the repetition brake)
    - Candidate 2 -- `DIRECTIONS.md` decision log + `foundry directions [--json]` reader (discovery bite 4)
    - Candidate 3 -- deterministic lens-rotation pool (`PM_SCOUT_LENS_POOL` + iteration-seeded selector) (discovery bite 2)
    - Candidate 1 -- strangler STEP 4: watchdog.decide delegates to the library (the SAFEST single step)
    - Candidate 2 -- strangler STEP 3: the stage retry path delegates to run_with_retry (higher value, medium resume-risk)
    - Candidate 3 -- _truncate_lesson robustness guard + stale-comment correction (the diversity pick; honestly low-but-real value)
    winner: unknown
    ship: PUSHED 21410d8
  iter-104
    lenses: new-capability (iter 104), hardening/DX (iter 104)
    - Candidate 1 (my strongest): `foundry novelty-check [--json]` -- the repetition brake
    - Candidate 2: `DIRECTIONS.md` decision log + `foundry directions [--json]` reader
    - Candidate 3: deterministic lens-rotation pool (the exploration mechanism)
    - Candidate 1 (my strongest): give `learnings_digest` a real CHARACTER budget
    - Candidate 2: strangler -- delegate ONE reliability primitive to the library
    - Candidate 3: cap lesson length at WRITE time (root-cause, defense in depth)
    winner: unknown
    ship: PUSHED 2f6dd82
117 scouted iterations
