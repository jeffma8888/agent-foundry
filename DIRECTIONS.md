# Foundry directions

foundry directions -- _platform
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
15 scouted iterations
