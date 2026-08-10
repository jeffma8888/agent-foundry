# Foundry directions

foundry directions -- _platform
  iter-148
    lenses: performance-and-throughput, narrative-and-docs -- iteration 148
    - Candidate B1 -- two design docs price a retry ladder that misdescribes 130 of 151 real retries
    - Candidate B2 -- the ~600s agent-CLI cap, the constraint that shaped all 8 role cards, is explained in no design doc
    - Candidate B3 -- the prompt-inlined quality_bar names two invariants ARCHITECTURE.md does not have
    winner: A1
    ship: unknown
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
    winner: B2
    ship: PUSHED f2e5239
  iter-136
    lenses: performance-and-throughput (iteration 136), narrative-and-docs
    - Candidate B1 -- Retire the spent operator directives; both artifacts still say the discovery loop was never built
    - Candidate B2 -- The invariants doc still prices a retry ladder the code stopped using two iterations ago
    - Candidate B3 -- The PM role card mandates a command that cannot run
    winner: B1
    ship: PUSHED 1c4568a
  iter-135
    lenses: simplification-and-deletion (iteration 135), performance-and-throughput
    winner: B2
    ship: PUSHED 9dc9849
  iter-134
    lenses: integration-and-adoption (iteration 134), simplification-and-deletion (iteration 134)
    - Candidate A1 -- `lint-config` reports a typo'd config key as a FINDING (exit 1), not as "cannot read config" (exit 2)
    - Candidate A2 -- name the runnable foundry CLI in every stage prompt, so 40 shipped verbs stop being unreachable
    - Candidate A3 -- the committed decision log records WHICH candidate won (and refuses to invent one)
    winner: A1
    ship: PUSHED d4b1599
  iter-133
    lenses: hardening/DX, integration-and-adoption
    winner: A2
    ship: PUSHED b6774f9
  iter-132
    lenses: new-capability (iteration 132), hardening/DX
    - Candidate A1 -- Finish the decision log's WINNER half: a strict-fallback, cross-validated triage-winner rule
    - Candidate A2 -- `foundry new-product`: turn the VISION's "point it at any git repo" into an actual command
    - Candidate A3 -- Record the REJECTED alternative and the reason it lost -- the half of bite 4 that never shipped
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
    winner: C2
    ship: unknown
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
45 scouted iterations
