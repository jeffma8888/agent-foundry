# Platform Roadmap — how the foundry improves itself

The `_platform` team (highest dispatcher priority) works this list one small,
reversible increment per iteration, keeping `tests/` green. Seeded from the
`ralph` and `ai-brownfield-practices` skills and the repolens build. The PM
re-orders by value each iteration; ship-order is a suggestion, not a contract.

## Roadmap file contract (added iter 122)

This file is the terse LIVE index. Per-iteration history lives VERBATIM in
`PLATFORM_ROADMAP_ARCHIVE.md`, which no role reads. Two suite tests enforce the split, so keep it:
`roadmap_size_verdict` fails if this file exceeds `ROADMAP_SIZE_WARN_CHARS` (60,000; this file was
312,487 chars before the split and 88.8% of it was done history), and `roadmap_archive_gaps` fails
if any iteration named in the Done ledger has no bullet in the archive. Therefore: **a new Done
ledger row and its verbatim archive bullet must land in the SAME commit**, the row must be one line
of at most 120 chars, and no archived bullet may ever be re-worded, re-wrapped or re-ordered. When
the index approaches the budget, archive more; do not raise the constant without a measurement.

WHO WRITES THE RECORD (changed iter 124, was the cause of two permanently lost iterations): each
iteration's PM writes its OWN record -- the one-line `- iter N ` Done-ledger row in THIS file AND the
verbatim `- **iter N ` bullet in `PLATFORM_ROADMAP_ARCHIVE.md` -- in the very commit that ships that
iteration. It is NOT deferred to a later iteration's PM. That deferral is exactly what silently lost
iterations 64 and 122: the record was owed by a successor, and a reverted successor drops it forever
(iteration 123 ended PENDING and took 122's record with it). A THIRD suite brake now enforces this
from GIT ship-truth (`roadmap_ledger_gaps`, iter 124): every iteration whose commit subject carries a
`(foundry iter N)` tag must have a ledger row here OR a bullet in the archive, with NO grace window --
because under this contract a shipped iteration is already recorded, so an exemption could only hide
the failure it is meant to catch.

STATUS (iter 126): the ledger and the archive are current through iteration 126 -- iterations 122 and
124 record themselves, and iteration 64's detail was recovered into the archive from its commit.
Iteration 126's two records were written BY THE RELEASE GATE, not by its PM: that stage was killed at
the 600 s cap after checkpointing its spec but before appending them, and this contract puts the record
in the SHIP COMMIT, which is the gate's own commit to make. A PM must still never plan on that.
STATUS (iters 127-129): current; each iteration's PM wrote its own two records in the ship commit,
per the contract above.
STATUS (iters 130-135): current through iteration 135; each PM wrote its own two records in the ship
commit (iteration 133's archive bullet was appended by a later stage of the same commit). Items (a),
(f), (b) and (e) shipped in iterations 132, 133, 134 and 135 respectively, each off a scout slate;
STILL OPEN: (c), (d), (g)'s `parse_triage_winner` half, (h), and (i) below.
NEXT UP, in value order: (a) SHIPPED iter 132 -- the freeze-guard SELECTOR now reads guard BEHAVIOR
(an in-function `git diff --quiet HEAD --` pathspec, element-form), so the meta-test polices all 26
every-suite guards instead of the 12 sharing one literal name. Only the OPTIONAL 25-guard
CONSOLIDATION remains, and it does NOT unblock strangler steps 2/3 (one guard still freezes
`dispatcher.py` and the meta-test requires it to); (b) SHIPPED iter 134 -- iteration 128's unknown-key
guard now has its SECOND consumer: on a `ConfigKeyError` `lint_config_cli` re-reads the raw dict and
emits one error-level `ConfigFinding` per unknown key (the offending key in the machine-readable
`field` slot, the `suggest_config_key` hint in `detail`), so a typo'd key exits 1 with the normal
findings document instead of 2 with a prose blob, while a missing or corrupt file still exits 2; (c) repair a missing `tests/test_iterNN*.py` at the earliest
repairable stage (both iterations that lacked one, 121 and 125, REVERTED); (d) relax `roles/tester.md`'s
prose discipline around the two gate tokens, which iteration 127 makes safe but which MUST NOT ship in
the same iteration as 127 itself (a live loop holds the pre-127 `foundry.py` in memory). (e) SHIPPED iter 135 -- the `"stalled"` failure kind now draws from its OWN ladder (`60/300/1200s`) through a new per-kind `KIND_RETRY_LADDERS` map that `retry_delay` consults BEFORE its existing fast/long choice, exactly the shape this item asked for (cheap first retry, slow retries 3-4, and `FAST_RETRY_KINDS` untouched). Iteration 129 had deferred it because the evidence that a stall is a transient LOCAL condition was "suggestive but unmeasured"; iteration 135's scout B measured it -- 9 of 9 stalled stage-runs are test-RUNNING stages, zero in pm/scout/engineer/reviewer/final -- and the measured 16-attempt population falls from 13,800s to 3,840s of FLEET-wide sleep (dispatcher.py is a single-threaded round-robin, so the sleep blocked all three products). Full record in the archive. (f) SHIPPED iter 133 -- all six `PM_SCOUT_LENS_POOL` lenses are now DEFINED in the scout role card, the retired fixed a/b mapping is gone from `roles/pm.md`, `ARCHITECTURE.md` and `docs/DUAL_PM_SCOUT_SPEC.md`, and a LIVE suite assertion over the new pure `scout_lens_audit` fails the ship if the pool and the card ever disagree, so a 7th lens cannot be added undocumented. (g) **candidates half SHIPPING iter 131; the rest still open.** Re-measured iter 131 over all 136 slates on disk: `parse_scout_candidates` accepted only `## Candidate `, so 32 slates rendered ZERO candidates and 6 of 27 COMMITTED `DIRECTIONS.md` blocks were incomplete (3 of them empty). Iter 131 makes it a UNION with an id-first rule (`## A1 --`), measured to admit 99 real candidate headings and ZERO of the 626 non-candidate `##` headings. STILL OPEN, in order: the `parse_triage_winner` half (21 `pm.md` files carry a `## Triage` heading and still yield `None`), then rendering "present but unparsed" distinctly from "absent". (h) paper-cut: `roles/pm.md` mandates `foundry lint-spec`, which is NOT on PATH inside a product stage -- VERIFIED this run that `python3 foundry.py lint-spec --file <path>` works from the foundry checkout root, so the card should carry that exact invocation for a non-foundry cwd. (i) NEW, measured by iteration 134's scout B: collapse the NINE near-identical `company_*_cli` bodies (547 lines, 95.8-100% identical; the whole variation is the `gather_*` seam, the `summarize_company_*` seam, one accumulator annotation and two extra kwargs) into ONE shared body plus nine thin wrappers keeping their public names, signatures, exit codes and docstrings -- est. -250 to -350 lines, entirely off the control path. The FIRST non-additive refactor of shipped code here, so it wants its own iteration; the `monkeypatch.setattr` census that makes it safe (and the `summarize_company` naming trap that breaks name-derived dispatch) is recorded verbatim in iteration 134's archive bullet -- read it before starting. **DE-LISTED by iteration 130's scout A, measured -- do not re-propose:** cutting `MAX_ATTEMPTS` for the timeout kind (12 of 17 timeout stage-runs RECOVER on a retry, so it trades 5.83 h of visible waste for lost iterations); and an "output file is stable, so stop the attempt" early exit (the 7.01 h of post-last-write agent time is concentrated in engineer and final, whose real work lands in git rather than in the state file, so stopping there destroys code and commits). ALSO STILL OPEN: the iteration-121 RETRY (its 51,824-byte
`products/_platform/state/iter-121/REVERTED_IMPLEMENTATION.patch` is preserved and its FINAL lesson
authorises the retry, plus the dispatcher restart that lesson demands), then scout A's per-product
`fast_test_cmd` for the build stages. DE-LISTED by iteration 126's spec on a measurement both its scouts
took independently: no product in the fleet has a slow suite (`_platform` 35.41 s, repolens 30.75 s) and
no product is retired for slowness, so the premise that it unblocks a slow repo is stale -- iteration 119
had already found the "repolens is retired with a 498 s suite" claim false.
DEADLINE (measured iteration 128 by its Scout B; a scheduling item, never a competitive candidate):
`tests/test_iter122_behavior.py` asserts `ROADMAP_SIZE_WARN_CHARS = 60000` against the LIVE file, so
whoever crosses it turns the suite RED and gets REVERTED for a docs-only reason. **RE-MEASURED iter 134, post-edit: this index is 56777 chars, leaving 3223. Iteration 134 is net
+757: it retired item (b)'s open paragraph and collapsed the iter-132/133 STATUS lines, which
partly paid for its own two records plus the new item (i). (The iter-128 note said "~51 KB": that was
BYTES from `wc -c`, and the guard counts CHARACTERS -- measure with `len(text)`.)** Compacting the index is
now the cheapest it will ever be; whoever picks it next should archive whole done rows wholesale.

| # | Increment | Why | Done when |
|---|---|---|---|
| 1 | `prd.json`-style machine roadmap per product (id/title/criteria/passes) | Deterministic global stop + progress, vs parsing prose | dispatcher can report "N/M stories pass" via a jq-able file — **[iter 11, bite 1/3 = pure `prd_status(prd_text)` parser + frozen `PrdStatus` + on-demand `foundry prd --config <cfg>` CLI (dormant); iter 12, bite 2a/3 = wire `prd_status` into the dispatcher as a DIAGNOSTIC per-shift "N/M stories pass" log line via pure `dispatch_progress_line(cfg)` (dormant-until-data: no product has a `prd.json` yet); bite 2b (future) = automatic global stop when a prd is complete → touches loop-termination/resume semantics, own iter + migration note → COMPLETES item 1]** |
| 2 | Consolidate LEARNINGS into a pinned `## Patterns` head section | Iteration agents can't read an ever-growing log; promote general rules | reporter/roles maintain a bounded top section — **[shipping iter 07, bite 1/2 = `learnings_digest` helper + `foundry learnings` CLI + curated `## Patterns` head; iter 08, bite 2/2 = digest inlined into `build_prompt` so every stage prompt carries the bounded head + N recent lessons → COMPLETES item 2]** |
| 3 | Emit an `AGENTS.md` into each product repo from its learnings | Fresh agents auto-read house rules; less re-learning | product repo has an up-to-date AGENTS.md — **[shipping iter 09, bite 1/2 = pure `render_agents_md` helper + on-demand `foundry agents` CLI; bite 2 (future) = auto-refresh AGENTS.md at ship time]** |
| 4 | Risk-split the final gate (test-only diff = light gate) | Cut gate latency ~half for coverage-only iterations | gate detects "no src/ change" and runs the light path — **[iter 15, bite 1/2 = pure `classify_gate_scope` + frozen `GateScope` + patchable `GATE_TEST_DIR_NAMES`/`GATE_DOC_SUFFIXES` + on-demand `foundry gate-scope` CLI (DORMANT; the final gate does NOT consult it, §3 full-suite-rerun invariant untouched); bite 2 (future) = wire the light path into the final gate while preserving the §3 invariant → COMPLETES item 4]** |
| 5 | Task-size guard: PM must confirm a feature fits <50% context | The 3 engineer timeouts on repolens were oversized-iteration smells | PM spec includes a size self-check field — **[shipping iter 10 = pure `spec_lint` helper + on-demand `foundry lint-spec --file` CLI + `## Size self-check` made a REQUIRED section in `roles/pm.md` → COMPLETES item 5]** |
| 6 | Mutation-testing gate (mutmut) as a deterministic weak-assertion check | Agents emit assertions that pass without validating behavior | gate can optionally run mutation testing |
| 7 | Per-iteration suite wall-time in the log + auto-parallelize story when slow | Throughput is dominated by verify time, not reasoning | NIGHT_LOG records suite seconds; PM files a speed story past a threshold — **[iter 13, bite 1/2 = record the fresh-clone suite wall-time per ship: pure `suite_timing_line` formatter + patchable `SUITE_SLOW_SECONDS` threshold + `PostReleaseResult.test_seconds` + a NIGHT_LOG/events line from `postrelease_step`; bite 2 = a per-product `SPEED_STORY_NEEDED.md` **advisory** flag (mirrors the `HOTFIX_NEEDED.md` lifecycle) raised on a SLOW ship + an advisory PM duty in `roles/pm.md` → **[shipping iter 14] → COMPLETES item 7**]** |
| 8 | `scheduled` watchdog that relaunches the dispatcher if PID gone & no STOP | Survive reboots / crashes truly 24/7 | a documented, tested watchdog exists — **[shipping iter 06]** |
| 9 | `foundry.py doctor` preflight (AC power, agent CLI, uv, remote reachable) | Fail fast before burning a shift on a broken env | `doctor` subcommand returns actionable checks — **[shipping iter 01]** |
| 10 | Structured JSON event log alongside the markdown NIGHT_LOG | Machine-readable status for dashboards / the reporter | events.jsonl written per stage — **[shipping iter 05]** (retry; iter 04 was reverted by an external public-release STOP, not a feature defect) |
| 11 | **Post-release verification gate** (fresh-clone) + conventional revertable commit contract | The final gate checks the working TREE, never a clean-room checkout — this misses uncommitted files, lockfile drift, and dev-tree import leakage. For a project whose PRIMARY goal is trustworthy continuous release/deployment, a green working tree is not proof the release is deployable | a `postrelease` stage runs on every ship, clones `origin/<branch>` fresh, re-verifies, emits `POSTRELEASE: HEALTHY\|BROKEN`, and a BROKEN result raises a per-product hotfix flag the next PM must clear (see detailed spec below) — ✅ **SHIPPED (iter 02 bite 1/2 = config fields + dormant verify helper, `0fc54c1`; iter 03 bite 2/2 = wiring + `POSTRELEASE:` sentinel + hotfix-flag lifecycle + commit contract)** |
| 12 | Read-only `foundry status` company-health probe | One command answers "is my company healthy right now?" instead of manually inspecting the newest `postrelease.md`, `ls`-ing for two flag files, and running `foundry prd` — the scattered babysitting the VISION says to eliminate | `foundry status --config <cfg>` prints the latest iteration + the last ship's `POSTRELEASE:` verdict + the `HOTFIX_NEEDED.md`/`SPEED_STORY_NEEDED.md` flags + the `prd.json` progress line, with a scriptable exit `0` healthy / `1` needs-attention / `2` nothing-shipped-yet — **[shipping iter 16 = pure `parse_postrelease_verdict` + frozen `StatusSummary` (`attention`/`ok`/`exit_code`/`render()`) + pure `summarize_status` + on-demand `foundry status --config` CLI (read-only, off the control path) → COMPLETES item 12]** |
| 13 | Read-only `foundry history` multi-iteration ship ledger | `foundry status` (iter 12) answers "healthy right NOW?" from the latest iteration; the complement — "what has my company done over its whole run?" — still needs manual `ls state/` + `tail` of a dozen `final.md`/`postrelease.md` files | `foundry history --config <cfg> [--limit N]` prints, in ascending iteration order, each iteration's ship action (`final.md` `ACTION:`) + post-release verdict (REUSING `parse_postrelease_verdict`) + a rollup (`N iterations: X shipped, Y reverted, Z broken`), exit 0 has-history / 2 none — **[shipping iter 17 = pure `parse_ship_action` + `iteration_numbers` + frozen `IterationRecord`(`label`) + frozen `HistorySummary`(counts/`exit_code`/`render()`) + pure `summarize_history` + on-demand `foundry history` CLI (read-only, off the control path) → COMPLETES item 13]** |
| 14 | Single-brain launch preflight (`foundry single-brain`) | The #1 OBSERVED live failure is two dispatchers on one model-API account starving the shared token budget (LEARNINGS `[PM iter01]`, VISION single-brain constraint); `foundry doctor` cannot cover it (its 4-check contract is pinned by iter-01 tests) and the iter-06 watchdog only guards RESURRECTION, not an operator's manual launch | `foundry single-brain [--pattern P]` scans for a running dispatcher and exits 0 SAFE / 1 CONFLICT / 2 UNKNOWN so a launch wrapper can gate on it — **[shipping iter 24 = read-only `running_dispatchers` seam + frozen `SingleBrainStatus` + pure `summarize_single_brain` + on-demand `foundry single-brain` CLI (off the control path, reports only — never kills/force-anything); successor = `--json`]** |

## Ship order (PM re-orders by value each iteration)
- Item 1 (`prd.json` machine roadmap) remains high value but is larger and touches dispatcher reporting; deferred to a later iteration after the additive-increment pattern is proven.
- Item 11 (post-release fresh-clone verification gate) was appended by a sibling factory and is arguably the most on-mission item, but it is a MULTI-iteration effort: it adds a new pipeline stage, a new `POSTRELEASE:` sentinel, and modifies `run_iteration` control flow. Per the size bar it must be SPLIT (e.g. config fields + fresh-clone verify helper first, then wiring + hotfix flag) and, per the self-mod guardrails, deferred behind a flag while a loop is in flight. Strong candidate for iter 02–04; not a safe first bite.
- **RESOLVED -- applied directly on 2026-08-03 outside the iteration loop (was spec-ed as iter 86): FIXED the iter-83/84 README-freeze systemic blocker (unblocks the entire org-design --json cadence + any doc-touching feature).** iter-85 (escalation-check --json) REVERTED because its README #35 note turned the full suite RED: tests/test_iter83_behavior.py AND tests/test_iter84_behavior.py each bake an over-broad test_ac_control_path_byte_unchanged that freezes README.md and roles/ byte-unchanged via `git diff --quiet HEAD -- dispatcher.py scripts/ .gitignore README.md roles/` -- a PERMANENT regression guard (it runs on EVERY future suite, comparing that iteration's working tree to HEAD) that trips whenever ANY later iteration legitimately edits README (gate 5's own mandate) or a role card (the dual-PM-scout wiring bite 3b-ii). README is DOCS, not the running-loop control path; roles/ edits are operator-gated wiring, not a dormant-iteration concern. This test-ONLY fix narrows BOTH pathspecs to `dispatcher.py scripts/ .gitignore` (matching iter-85's OWN correct probe), touching foundry.py / dispatcher.py ZERO -- so no dormancy question arises and no README edit is needed THIS iteration. Ship diff = {tests/test_iter83_behavior.py (-README.md/-roles/ + msg), tests/test_iter84_behavior.py (-README.md/-roles/), PLATFORM_ROADMAP.md (PM-applied), new tests/test_iter86_behavior.py}. Unblocks re-shipping escalation-check --json VERBATIM next, then the cadence-review/restaffing-review/scout-plan --json + composite gate-verdict/role-model/product-gate/gate-precheck --json cadence. **APPLIED:** both pathspecs narrowed to `dispatcher.py scripts/ .gitignore` (matching iter-85 own correct probe), and a NEW permanent meta-test `tests/test_control_path_freeze_scope.py` AST-scans EVERY test module and fails if any every-suite control-path guard freezes `README.md` or `roles/` again -- while also asserting the guard still covers `dispatcher.py`, so narrowing can never hollow it out. The next PM may re-ship escalation-check --json verbatim.

### Done ledger -- one line per shipped iteration

Full per-iteration detail lives VERBATIM in `PLATFORM_ROADMAP_ARCHIVE.md`; it is never
summarised and never read by a role. Keep this index terse: a suite test enforces
`ROADMAP_SIZE_WARN_CHARS` against this file, and a second test fails if any iteration named
here has no bullet in the archive.

- iter 1 -- item 9 (`foundry doctor`).
- iter 2 -- item 11, bite 1 of 2 (SPLIT as instructed above).
- iter 3 -- item 11, bite 2 of 2 (DONE — completes item 11).
- iter 5 -- item 10 (structured JSON event log `events.jsonl`) — RETRY.
- iter 6 -- item 8 (`scheduled` watchdog to resurrect the dispatcher).
- iter 7 -- item 2, bite 1 of 2 (SPLIT — the pre-declared next-highest-value item).
- iter 8 -- item 2, bite 2 of 2 (DONE — completes item 2).
- iter 9 -- item 3, bite 1 of 2 (SPLIT — the pre-declared next-highest-value item).
- iter 10 -- item 5 (Task-size guard) — DONE, COMPLETES item 5.
- iter 11 -- item 1, bite 1 of 2 (SPLIT — the roadmap's #1-value item, deferred every iteration until now because its...
- iter 12 -- item 1, bite 2a of (now) 3 — the reporting half of the iter-11 "bite 2".
- iter 13 -- item 7, bite 1 of 2 (SPLIT — chosen OVER the pre-declared item 1 bite 2b on the standing value×safety×si...
- iter 14 -- item 7, bite 2 of 2 (DONE — COMPLETES item 7).
- iter 15 -- item 4, bite 1 of 2 (SPLIT — the remaining safe additive item, chosen OVER the pre-declared item 1 bite...
- iter 16 -- item 12 (NEW — read-only `foundry status` company-health probe; DONE, COMPLETES item 12).
- iter 17 -- item 13 (NEW — read-only `foundry history` multi-iteration ship ledger; DONE, COMPLETES item 13).
- iter 18 -- NEW read-only `foundry timing` per-iteration suite wall-time digest (the successor iter 17 pre-declared).
- iter 19 -- NEW `foundry status --json` machine-readable health output (the alerting-grade complement of the iter-16...
- iter 20 -- NEW `foundry history --json` machine-readable ship-ledger output (the ledger half of the iter-19 pre-dec...
- iter 21 -- NEW `foundry timing --json` machine-readable throughput digest (the symmetric successor iter 20 pre-decl...
- iter 22 -- NEW `foundry weak-tests` — an offline, deterministic assertion-free-test detector (the offline slice of...
- iter 23 -- NEW `foundry weak-tests --json` — the machine-readable successor iter 22 pre-declared (completes the rea...
- iter 24 -- NEW `foundry single-brain` launch preflight (item 14 — the highest value × safety × size increment avail...
- iter 25 -- NEW `foundry single-brain --json` machine-readable launch-preflight verdict (the successor iter 24 pre-d...
- iter 26 -- NEW typed `events.jsonl` `kind` classifier (completes item 10's half-delivered "machine-readable status...
- iter 27 -- NEW read-only `foundry events` reader/digest over the typed `events.jsonl` (completes item 10's READ hal...
- iter 28 -- NEW `foundry preflight` composite LAUNCH gate (unifies the `doctor` (iter 01) + `single-brain` (iter 24)...
- iter 30 -- RETRY of iter 29 (`foundry company-status`) — infra-stalled, NOT a feature defect.
- iter 31 -- NEW `foundry company-history` — the company-wide roll-up of the iter-17 ship LEDGER (the symmetric TREND...
- iter 32 -- HOTFIX (post-release BROKEN from iter 31) — make the fresh-clone suite green; NO roadmap feature.
- iter 39 -- `foundry company-timing` BITE 1 of 2 — the pure foundation; SPLIT to break a 6-iteration tester-stall de...
- iter 40 -- `foundry company-timing` BITE 2 of 2 (COMPLETES the feature) — the company-wide roll-up CLI on top of th...
- iter 42 -- `foundry company-weak-tests` BITE 1 of 2 — the pure `gather_weak_tests` foundation; SPLIT to break an in...
- iter 43 -- `foundry company-weak-tests` BITE 2 of 2 (COMPLETES the feature) — the company-wide roll-up CLI on top o...
- iter 44 -- `foundry company-events` BITE 1 of 2 — the pure `gather_events` foundation; the last `company-*` member,...
- iter 46 -- `foundry company-events` BITE 2 of 2 (COMPLETES the feature AND the 5-member `company-*` family) — RETRY...
- iter 47 -- NEW pure `find_constant_assert_tests` offline weak-assertion detector (item 6 offline slice, BITE 1 of 2...
- iter 48 -- item 6 offline slice, BITE 2 of 2 (COMPLETES the offline slice) — NEW read-only `foundry constant-assert...
- iter 49 -- item 16, BITE 1 of 3 — NEW committed, portable, offline leak-guard CORE (`scripts/leak_guard.py`) + a SE...
- iter 50 -- item 16, BITE 2 of 3 — make the committed leak-guard RUNNABLE: a `main()` CLI + a single monkeypatchable...
- iter 51 -- item 16, BITE 2b of 3 — NEW `scripts/install_hooks.sh`: a portable, one-command pre-push hook installer...
- iter 52 -- item 16, BITE 3 of 3 (COMPLETES item 16) — final-gate integration: the `final` role runs the committed l...
- iter 54 -- RETRY of iter 53 (reverted for an ENVIRONMENTAL tester stall, NOT a review defect) -- NEW read-only `fou...
- iter 55 -- NEW pure `find_always_skipped_tests` offline always-skipped-test detector -- extends the item-6 offline...
- iter 56 -- NEW read-only `foundry skipped-tests` CLI (item 6 offline slice, BITE 2 of 2 -- surfaces the iter-55 dor...
- iter 57 -- NEW read-only `foundry company-skipped-tests` -- the company-wide roll-up of the per-product iter-56 `sk...
- iter 58 -- NEW read-only `foundry test-quality` -- a per-product COMPOSITE quality gate that folds all THREE offlin...
- iter 59 -- NEW read-only `foundry company-test-quality` -- the company-wide roll-up of the iter-58 per-product `tes...
- iter 60 -- NEW read-only `foundry lint-config --config <cfg> [--json]` -- an offline, deterministic PRODUCT-config...
- iter 61 -- NEW read-only `foundry company-lint-config --config <dispatch> [--json]` -- the company-wide roll-up of...
- iter 63 -- item 17 `foundry lint-bench [--dir <path>] [--json]` (RE-SPEC of the environmentally-interrupted iter 62...
- iter 65 -- item 18, bite 2 of 3 -- mint the missing core-seat bench card `roles/bench/reviewer.md` + ship the examp...
- iter 66 -- item 18, bite 3 of 3 (COMPLETES item 18) -- ship `docs/TRIGGER_RUBRIC.md`, the static committed trigger-...
- iter 67 -- item 19, bite 1 of 2 -- add a DORMANT pure `derive_stage_sequence(manifest)` (+ a frozen `StageSpec` dat...
- iter 68 -- item 19, bite 2 of 3 (item 19 RE-SPLIT to 3 bites for safety) -- wire the staffing-manifest READ into th...
- iter 69 -- item 19, bite 3a of 3 (bite 3 RE-SPLIT into 3a + 3b for safety) -- add a DORMANT pure `derive_execution_...
- iter 70 -- item 19, bite 3b-i of (now) 2 (bite 3b RE-SPLIT into 3b-i + 3b-ii for safety) -- add a DORMANT module-le...
- iter 72 -- item 19, bite 3b-ii of 2 (COMPLETES item 19) -- WIRE the dormant manifest-driven executor into `run_iter...
- iter 73 -- item 20, bite 1 of ~4 (SPLIT -- item 20 is a MEDIUM item bundling four distinct pieces: the deterministi...
- iter 74 -- item 20, bite 2 of ~4 -- a DORMANT pure verdict-AGGREGATION core for the tri-perspective product gate: `...
- iter 75 -- item 20, bite 3 of ~4 -- a DORMANT pure per-role MODEL-OVERRIDE resolver `resolve_role_model_argv(base_a...
- iter 76 -- item 20, bite 4a of ~5 (item 20 RE-SPLIT: bite 4 = the composite decision core THIS iter; the STAGE wiri...
- iter 77 -- item 21, bite 1 of ~2 (SPLIT -- ORG_DESIGN section 9 / org-design implementation-order step 5: CEO escal...
- iter 78 -- **iter 78 = item 22, bite 1 of ~3 (SPLIT -- ORG_DESIGN section 7 / section 10 / implementation-order ste...
- iter 79 -- item 22, bite 2 of ~3 (ORG_DESIGN section 10: bounded re-staffing hysteresis DIFF core).
- iter 80 -- NEW dual-PM-scout PHASE PLANNER (docs/DUAL_PM_SCOUT_SPEC.md, bite 1 of ~3 -- the pure DORMANT core).
- iter 81 -- dual-PM-scout feature (docs/DUAL_PM_SCOUT_SPEC.md), bite 2 of ~3 (additive-dormant prerequisites).
- iter 82 -- dual-PM-scout feature (docs/DUAL_PM_SCOUT_SPEC.md), bite 3a of ~4 (bite 3 RE-SPLIT into 3a + 3b for safe...
- iter 83 -- dual-PM-scout feature (docs/DUAL_PM_SCOUT_SPEC.md), bite 3b-i of ~4 (bite 3b RE-SPLIT into 3b-i + 3b-ii...
- iter 84 -- dual-PM-scout feature (docs/DUAL_PM_SCOUT_SPEC.md), bite 3b-ii-prep of ~4 (the LAST dormant slice before...
- iter 87 -- RE-SHIP `foundry escalation-check --json` VERBATIM from the reverted iter-85 design (now UNBLOCKED by th...
- iter 88 -- NEW `foundry cadence-review --json` -- the SECOND flat CLI in the org-design `--json` cadence, the direc...
- iter 89 -- NEW `foundry restaffing-review --json` -- the THIRD CLI in the org-design decision-CLI `--json` cadence...
- iter 90 -- NEW `foundry scout-plan --json` -- the FOURTH `--json` CLI in the org-design decision-CLI cadence and th...
- iter 91 -- NEW `foundry gate-verdict --json` -- the FIFTH `--json` CLI in the org-design decision-CLI observability...
- iter 92 -- NEW `foundry gate-precheck --json` -- the SIXTH `--json` CLI in the org-design decision-CLI observabilit...
- iter 93 -- NEW `foundry role-model --json` -- the SEVENTH `--json` CLI in the org-design decision-CLI observability...
- iter 94 -- NEW `foundry product-gate --json` -- the EIGHTH and LAST `--json` CLI in the org-design decision-CLI obs...
- iter 95 -- NEW `foundry prd --json` -- a machine-readable JSON payload for the read-only `prd` story-progress CLI (...
- iter 96 -- NEW `foundry lint-spec --json` -- the TENTH `--json` observability CLI and the THIRD NEW read-only incre...
- iter 97 -- NEW `foundry gate-scope --json` -- the ELEVENTH `--json` observability CLI overall and the FOURTH NEW re...
- iter 98 -- NEW `foundry learnings --json` -- the TWELFTH `--json` observability CLI overall and the FIFTH NEW read-...
- iter 99 -- NEW `foundry agents --json` -- the THIRTEENTH `--json` observability CLI; COMPLETES `--json` coverage of...
- iter 100 -- NEW read-only `foundry outcomes` per-iteration GATE-OUTCOME ledger (reviewer VERDICT + tester RESULT +...
- iter 101 -- NEW `foundry outcomes --json` -- the pre-declared bite 2 of the iter-100 `outcomes` per-iteration gate-...
- iter 104 -- HARDENING of item 2 -- give the inlined `learnings_digest` a real CHARACTER budget (operator-MEASURED h...
- iter 105 -- NEW `foundry novelty-check [--config C] [--limit N] [--json]` -- discovery bite 3 (docs/DISCOVERY_LOOP_...
- iter 106 -- discovery bite 3b (DISCOVERY_LOOP_PLAN.md section 5 "Then USE it") -- WIRE the novelty verdict into the...
- iter 107 -- discovery bite 2 (DISCOVERY_LOOP_PLAN.md sec 4, lens-rotation pool) -- BITE 1 of 2, the DORMANT foundat...
- iter 110 -- NEW reliability item R1 (IPC-self-healing), bite 1 of 2 = the DORMANT connect-probe resolver -- a VERBA...
- iter 112 -- reliability hardening (operator's declared #1 leverage) -- add the WRITE-EARLY (checkpoint-first) rule...
- iter 113 -- discovery bite 2 of 2 (DISCOVERY_LOOP_PLAN.md sec 4) -- WIRE the live scout-lens rotation into the runn...
- iter 114 -- reliability item R1 (IPC-self-healing), bite 2 of 2 = WIRE `resolve_agent_endpoint` into `run_stage`; C...
- iter 115 -- discovery bite 4a (DISCOVERY_LOOP_PLAN.md sec 6) — NEW read-only `foundry directions` decision-log rend...
- iter 116 -- discovery bite 4b (DISCOVERY_LOOP_PLAN.md sec 6) — SHIPPED: the live, TRACKED `DIRECTIONS.md` decision...
- iter 117 -- reliability observability (operator fix #2 of 3) -- NEW read-only `foundry stage-times` per-stage attem...
- iter 118 -- HARDENING of item 2, the SECOND and last half of the digest char budget -- close the `## Patterns` HEAD...
- iter 119 -- reliability: ATTEMPT-AWARE RETRY -- the retry loop stops re-sending a byte-identical prompt (attacks th...
- iter 122 -- roadmap index/archive split + `ROADMAP_SIZE_WARN_CHARS` + 2 pure suite-enforced brakes.
- iter 124 -- third roadmap brake from GIT ship-truth; recovered the lost 64/122 records; PM self-records.
- iter 126 -- test gate tells an UNFINISHED tester checkpoint from a RED suite; spends the repair round on the tester.
- iter 127 -- anchored test-gate trigger: only an earned tester PASS skips the repair round (kills 6/19 false fires).
- iter 128 -- product config fails CLOSED on an unknown key, naming the key and its nearest field.
- iter 129 -- retry delay reads the failure KIND: a cap-timeout waits 60s, not 10min (~8.4h/93h reclaimed).
- iter 130 -- read-only live-lag report + doctor WARN: names shipped iterations the running brain cannot execute.
- iter 131 -- decision log reads the id-first candidate headings scouts write; heals 5 of 27 committed blocks.
- iter 132 -- freeze-guard meta-test selects by BEHAVIOR, not one name: 12 -> 26 guards policed, 4 pathspec sets.
- iter 133 -- all 6 scout lenses DEFINED in the card, 3 docs de-hardcoded, suite brake on pool/card drift.
- iter 134 -- lint-config emits a finding + exit 1 for a typo'd config key; missing/corrupt file still exits 2.
- iter 135 -- per-kind retry ladder map: a "stalled" attempt waits 60/300/1200s, not 600/1200/2400 (-2.77h sleep).


### Migration note (per §6 self-mod guardrail) — iter 03
- **New sentinel introduced:** `POSTRELEASE: HEALTHY|BROKEN`, written to `products/<name>/state/iter-NN/postrelease.md` (last non-empty line). It does NOT participate in loop control flow — `run_iteration`/`run_continuous` branch only on `VERDICT:`/`RESULT:`/`ACTION:` and the `res["status"]` value; `POSTRELEASE:` is diagnostic and carried as an additive `res["postrelease"]` key.
- **New per-product artifact:** `products/<name>/HOTFIX_NEEDED.md` — a BROKEN post-release raises it (with the sha + evidence); a genuine-HEALTHY later ship clears it; the next PM must clear it before any new feature (now stated in `roles/pm.md`).
- **Unchanged:** iteration numbering, `state/iter-NN` layout, the `VERDICT:`/`RESULT:`/`ACTION:` sentinel strings, `run`/`once`/`doctor` CLI, and the `run_continuous` status branches {shipped, no-ship, infra-fail, stopped}.

### Migration note (per §6 self-mod guardrail) — iter 14
- **New per-product artifact:** `products/<name>/SPEED_STORY_NEEDED.md` — an **advisory** (NON-blocking) throughput flag raised on a genuine SLOW ship (`test_seconds > SUITE_SLOW_SECONDS`), auto-cleared on the next genuine fast ship, left untouched on infra-skip / disabled / errored. Git-ignored (`products/*/SPEED_STORY_NEEDED.md`).
- **New advisory PM duty** in `roles/pm.md` (after the hotfix check): consider a throughput/speed increment when the flag is present and no higher-value feature is warranted — subordinate to the blocking `HOTFIX_NEEDED.md` flag.
- **No new sentinel; ADDITIVE and off the control path:** `run_iteration`/`run_continuous` still branch only on `VERDICT:`/`RESULT:`/`ACTION:` and `res["status"]` ∈ {shipped, no-ship, infra-fail, stopped}; iteration numbering and `state/iter-NN` layout are unchanged. The advisory write/clear rides the existing post-release ship branch and is swallow-safe, so a live loop resumes cleanly on restart.

### Migration note (per §6 self-mod guardrail) — iter 26
- **No new sentinel; ADDITIVE schema enrichment only.** `events.jsonl` records gain one ADDITIVE `kind` field (a semantic type from the pure `classify_event`); the top-level `event` key stays `"log"` (backward-compatible — existing consumers filtering `event=="log"` keep working), and historical lines without `kind` remain valid JSON.
- **First change to `log()`'s emit call**, but strictly inside the EXISTING best-effort try/except mirror: the durable NIGHT_LOG write, all `VERDICT:`/`RESULT:`/`ACTION:`/`POSTRELEASE:` sentinels, iteration numbering, and `state/iter-NN` layout are UNCHANGED; `dispatcher.py` and every pipeline branch are untouched, and `kind` is never read on a control path — resume-safe (a live loop holds old code in memory; the change activates only on a clean restart). ARCHITECTURE.md §5 events bullet extended by one clause.

### Migration note (per §6 self-mod guardrail) — iter 52
- **No new sentinel; ADDITIVE gate-checklist step only.** `roles/final.md` gains a repo-agnostic leak-guard pre-push check (run `python3 <repo>/scripts/leak_guard.py --ref HEAD --repo <repo>` after the commit, before the push; a non-zero exit — 1 findings OR 2 error, fail-CLOSED — routes to the existing "If ANY fail — revert" path). It adds to the "ALL must hold to ship" set; it does NOT change iteration numbering, `state/iter-NN` layout, or the `VERDICT:`/`RESULT:`/`ACTION:`/`POSTRELEASE:` sentinel strings.
- **Resume-safe for an in-flight loop.** Role prompts are read fresh from disk each stage, so a running loop picks this up on its next `final` stage; the change is purely additive (can only ADD a revert-on-leak, never suppress a ship that would otherwise pass a clean scan) and produces the SAME ship/revert sentinels. `foundry.py` / `dispatcher.py` are byte-unchanged and every pipeline branch is untouched. Repo-agnostic: a product repo without `scripts/leak_guard.py` skips the check, so no other product's gate is affected.

## Guardrails for self-modification
- Never change iteration numbering, state layout, or the `VERDICT:`/`RESULT:`/
  `ACTION:` sentinel contract without a migration note in this file.
- Every change keeps `uv run --with pytest pytest -q` green and both modules
  importable (`python -c "import foundry, dispatcher"`).
- If an increment would touch a currently-running loop's resume behaviour,
  defer it or gate it behind a version flag.

## Detailed spec — item 11: post-release verification gate + revertable-commit contract

Added 2026-07-30 from a sibling continuous factory (`~/projects/proactive-factory/`)
that has shipped 15 iterations to a PUBLIC repo with this gate green on every ship —
so the design below is live-validated, not theoretical. Direct this item's PM to it.

### Why (on-mission for the foundry's continuous-deployment goal)
The Final Reviewer proves the *working tree* is green. It does NOT prove the *pushed
commit* is deployable. The gap is exactly the class of bugs that break real releases:
a file created but never `git add`-ed, `uv.lock` drift, an import that only resolves
because of leftover dev-tree state. A CD system's whole promise is "what landed on the
branch actually works from a clean checkout." This stage closes that gap.

### What the stage does (additive; slots in AFTER the `ACTION: PUSHED` branch)
Only runs when the final gate actually pushed (`push_enabled` True and remote head moved):
1. Clone `origin/<branch>` fresh, shallow, into the iteration state dir
   (a clean room — NOT the dev working tree).
2. Run, in the clone: `cfg.setup_cmd` (default `uv sync`) → `cfg.test_cmd` (full suite)
   → `cfg.smoke_cmd` (optional per-product demo/smoke, e.g. `make demo`; skip if unset).
3. Confirm the cloned HEAD sha == the sha the final gate reported.
4. Delete the throwaway clone.
5. Emit a new sentinel as the output file's final line:
   `POSTRELEASE: HEALTHY` / `POSTRELEASE: BROKEN`.

### Failure handling
- BROKEN → write `products/<name>/HOTFIX_NEEDED.md` (with the sha + verbatim evidence).
  The next iteration's PM MUST prioritize a hotfix over any new feature. HEALTHY on a
  later iteration clears the flag. The gate does NOT auto-fix and NEVER force-pushes —
  a bad public commit is fixed forward by the next iteration, not rewritten.
- Infra tolerance: a network failure during `git clone`/`uv sync` is INFRA, not a broken
  release. In that case emit `POSTRELEASE: HEALTHY` (verification skipped, note why) so a
  transient network blip never raises a false hotfix.

### Revertable-commit contract (the second half of this item)
Make the final gate's commit message a documented contract, not a convention:
`<type>: <summary> (foundry <product> iter NN)` where type ∈ feat/fix/chore/docs/test.
Every release is then greppable and single-commit-revertable — which is what makes
"fix forward, or revert one commit" a safe operation for a public repo.

### Config additions (default-on, backward compatible)
- `postrelease_enabled: bool = True`
- `setup_cmd: str = "uv sync"`, `smoke_cmd: str | None = None` (per product)
- All optional with safe defaults so existing product configs keep working.

### Invariant compliance (read §3 + the self-mod guardrails above)
- Purely ADDITIVE: runs only after a successful ship, so it does NOT change iteration
  numbering, state layout, or the `VERDICT:`/`RESULT:`/`ACTION:` sentinels → resume-safe
  for any loop already in flight.
- Introduces ONE new sentinel (`POSTRELEASE:`). When you implement, record it in
  ARCHITECTURE.md §2 (add the stage row) and §3 (extend the gate invariant) with a
  migration note here, per the self-modification guardrails.

### Reference implementation (copy/adapt, don't reinvent)
- Role playbook: `~/projects/proactive-factory/roles/postrelease.md` (the exact clone /
  setup / test / smoke / sha-match / delete / sentinel + infra-tolerance rules).
- Orchestration wiring: `~/projects/proactive-factory/factory_pla.py`
  → `run_pipeline_tail()` (the post-release branch after `ACTION: PUSHED`, plus the
  `HOTFIX_NEEDED.md` create-on-BROKEN / clear-on-HEALTHY logic).

### Done when
- [ ] A `postrelease` role + stage exist; stage runs on every ship, skipped on no-ship.
- [ ] Verifies on a FRESH clone (setup + full suite + optional smoke), matches the sha.
- [ ] Emits `POSTRELEASE: HEALTHY|BROKEN`; BROKEN writes the per-product hotfix flag.
- [ ] Network failure during clone/sync degrades to HEALTHY-skipped (no false hotfix).
- [ ] Final-gate commit-message contract documented and enforced in `roles/final.md`.
- [ ] ARCHITECTURE.md §2/§3 updated + migration note; `tests/` stay green; both modules
      still import.

---

## Item 16 — committed, portable pre-push leak-guard (HIGH: repo is public + auto-pushing)

**Problem.** This repo is public and the dispatcher auto-pushes on every successful ship
with NO human review in the loop. A drifted iteration can reintroduce sensitive strings
(the internal agent-CLI tool name, the model-provider service name, internal skill and
workflow names, internal credential-refresh command names, personal absolute home-directory
paths, and personal usernames) directly into a public commit. A local `.git/hooks/pre-push`
guard is installed today, but git hooks are NOT cloned — so a fresh checkout (including the
post-release fresh-clone verify, a new operator, or CI) ships with ZERO protection.

**What ships.**
- `scripts/leak_guard.py` — a stdlib-only, offline, deterministic scanner. Given a commit
  ref (or an explicit file list), it scans tracked blob content against a configurable
  denylist of *token-aware* patterns (each pattern flanked so ordinary English words that
  merely contain the fragment are never false-positives). Exits non-zero with a `file:line`
  report on any hit. Its OWN path is excluded from the scan so it can never self-trip on the
  denylist literals it necessarily contains.
- `scripts/install_hooks.sh` — one command a fresh clone runs to copy/symlink the scanner
  into `.git/hooks/pre-push` (documented in README setup).
- Final-gate integration — the `final` role runs the scanner as a hard pre-commit/pre-push
  check so the loop self-blocks a leaky ship even when the hook is not installed
  (belt-and-suspenders). A blocked ship fails the gate and reverts, same as any other gate
  failure.
- The denylist lives in a small committed config (e.g. `scripts/leak_denylist.txt`) so it is
  reviewable and extensible without editing code.

**Design / invariant compliance (read §3 + the self-mod guardrails).**
- Purely ADDITIVE and offline-deterministic (no network) — fits the test-speed + offline-CI
  invariants; does not change iteration numbering, state layout, or the
  `VERDICT:`/`RESULT:`/`ACTION:`/`POSTRELEASE:` sentinels → resume-safe for any loop in flight.
- Token-aware matching is mandatory (word-boundary / non-letter flanks) to avoid blocking
  legitimate prose the autonomous roles write every iteration.

**Done when.**
- [x] `scripts/leak_guard.py` exists, offline, stdlib-only, with unit tests covering: a clean
      tree passes; each denylist category is caught; a benign word containing a fragment is
      NOT flagged; the guard's own path is skipped. **(iters 49-50)**
- [x] `scripts/install_hooks.sh` arms the pre-push hook in one command; README documents it. **(iter 51)**
- [x] The `final` role invokes the scanner before pushing and treats a hit as a gate failure. **(iter 52)**
- [x] `tests/` stay green; both modules still import; ARCHITECTURE.md notes the new gate step. **(iter 52)**


---

# Org-design track (items 17-22) -- adopted 2026-08-01

Blueprint: **`docs/ORG_DESIGN.md`** (rich bench -> cheap kickoff council staffs
the minimum -> lean always-on core -> trigger/cadence-activated specialists ->
bounded re-staffing). Evidence: `docs/research/`. Ship these smallest-safe-first
and IN ORDER -- each item builds on the artifacts of the one before. Every item
is ADDITIVE and must not change iteration numbering, state layout, or the
`VERDICT:`/`RESULT:`/`ACTION:`/`POSTRELEASE:` sentinels (resume-safe for any
loop in flight), per the self-modification guardrails.

## Item 17 -- role-card bench: format validator + card lint (SMALL)

**Problem.** `roles/bench/` now holds 11 role-cards (+ README) written by hand.
Nothing enforces the card contract (Status/Activation/Tenure/Model-note header +
Mission + I/O contract sections), so cards will drift as they are edited and a
future manifest-driven pipeline cannot trust them as machine-readable.

**What ships.** A `foundry.py lint-bench` subcommand (offline, deterministic,
read-only, exit 0/1/2 like the other linters): parses every `roles/bench/*.md`,
checks the five declared fields + required sections exist, reports `file:line`
findings; `--json` for a machine-readable doc. Unit tests: a compliant card
passes; each missing field/section is caught; a non-card file (README.md) is
skipped.

**Done when.**
- [ ] `lint-bench` exists with tests; all 11 current cards pass (fix any card
      that does not rather than loosening the linter).
- [ ] README quickstart documents the command; `tests/` stay green.

## Item 18 -- kickoff council: staffing manifest schema + trigger rubric (MEDIUM)

**Problem.** ORG_DESIGN.md section 5 defines a kickoff council that emits a
machine-checkable staffing manifest, but no schema or rubric exists in code.

**What ships.**
- A documented JSON schema for `products/<name>/staffing.json`: active roles
  (subset of bench card names), sequence, gates, per-role model note,
  done-criteria, iteration budget.
- A `foundry.py lint-manifest` validator (offline, 0/1/2): schema-valid, every
  named role has a bench card, the five core seats are present, budget is a
  positive integer.
- A committed trigger rubric doc (`docs/TRIGGER_RUBRIC.md`): product trait ->
  bench role, mechanical and auditable (ships-a-UI -> designer; touches user
  data -> legal; public API -> devrel_docs; dependency count >= N -> tpm).
- An example manifest for repolens under `products/repolens/`.

**Done when.**
- [x] Schema + validator + rubric + example exist with tests; nothing in the
      running pipeline consults the manifest yet (that is item 19).

## Item 19 -- manifest-driven pipeline (MEDIUM, gated on 18)

**Problem.** The stage list is hard-coded; the org cannot actually staff
lean-or-wider per product.

**What ships.** `foundry.py` reads `staffing.json` when present and derives the
stage sequence from it (absent manifest = exact current fixed behavior, bit-for-
bit -- the default path must not change). A manifest naming only the five core
seats reproduces today's pipeline; extra activated seats insert their bounded
stage at their declared position. Stage success stays output-file-based.

**Done when.**
- [x] With no manifest, behavior is unchanged (regression-tested).
- [x] With a core-only manifest, behavior is unchanged.
- [x] With one extra seat activated, its stage runs at the declared point and
      its artifact is required; `tests/` green.

## Item 20 -- tri-perspective product gate + decorrelated adversarial seat (MEDIUM, gated on 19)

**Problem.** Proposals enter the loop without a Business/Product/Engineering
kill-gate, and every seat runs on the same model as the builder
(self-preference bias: a same-model reviewer favors its own author).

**What ships.**
- A `product-gate` stage runnable at kickoff and on strategic-surface triggers:
  three seat prompts (business, product-gate-pm, senior-engineer), verdicts
  Go / Kill / Recycle, **default Kill**; deterministic pre-checks (impact number
  present, appetite stated, alternatives listed) run before any agent call and
  bounce for free.
- Per-role model override: the manifest's model note maps to per-role agent-CLI
  env/args so the product-gate PM and the release gate can run a DIFFERENT
  model than the builder. Absent an override, current behavior is unchanged.
- Every verdict logged as structured data (events.jsonl kind: `gate`).

**Done when.**
- [ ] Gate + pre-checks + logging exist with tests; a Go carries a fixed
      iteration bet recorded in the manifest; per-role model override is
      exercised by at least one test (env-level, no real second model needed).

## Item 21 -- CEO escalation predicates (SMALL-MEDIUM, pattern exists)

**Problem.** ORG_DESIGN.md section 9 reserves five categories for human
escalation (security/credentials, personal data/PII, spending, legal/licensing,
public visibility). Only category 2 is enforced today (the leak-guard at the
release gate).

**What ships.** Generalize the leak-guard pattern: a deterministic diff-predicate
scanner (offline, stdlib-only) with one predicate per category (extensible
committed config), run by the final gate; any hit blocks the ship and writes a
structured escalation record (events.jsonl kind: `escalation`) + a per-product
`ESCALATION.md` flag for the human operator. No auto-page, no network.

**Done when.**
- [ ] Five predicate categories exist with unit tests (hit + benign near-miss
      each); a hit fails the gate to the revert path; the escalation record is
      written; leak-guard remains the category-2 implementation (no dup scan).

## Item 22 -- bounded re-staffing review + N=5 no-trigger fallback (SMALL, gated on 18/19)

**Problem.** Team composition can only change by hand-editing files (drift), and
a quiet loop can run indefinitely with no strategic look (ORG_DESIGN.md
section 7 adopts: if no trigger fires for 5 iterations, CEO + PM review anyway;
relax toward 10 once history shows steering is rarely needed).

**What ships.**
- A re-staffing review stage that emits a **diff against staffing.json** (never
  edits it directly) constrained by hysteresis: minimum tenure K iterations
  before deactivation, capped changes per review, every change citing a logged
  trigger. Applying the diff is a separate explicit step.
- An iteration counter since the last fired trigger; at 5, the pipeline queues
  the CEO+PM review (reads ship ledger + learnings, emits a steer-or-confirm
  record, resets the counter). N configurable, default 5.

**Done when.**
- [ ] Review emits a valid manifest diff under hysteresis rules with tests;
      the N=5 fallback fires in a simulated quiet run and resets; `tests/`
      green; ARCHITECTURE.md notes the new stages + a migration note here.

---

## Epic (added 2026-08-01): extract the resilience primitives into `resilient-agent-loop-primitives`, then depend on it (strangler)

**Goal:** make `github.com/jeffma8888/resilient-agent-loop-primitives` the single
source of truth for the three reliability primitives, and have this platform DEPEND
on it instead of keeping inline copies. Do this AFTER that library's product team
has shipped the corresponding modules (scheduler, runner, watchdog).

**STATUS 2026-08-03: UNBLOCKED and STARTED.** The gate in `docs/STRANGLER_PLAN.md`
is satisfied (the library repo is PUBLIC, verified via the gh CLI on 2026-08-03), and
step 1 is DONE: the dependency is declared in `pyproject.toml` pinned to the immutable
`v0.1.0` tag, the lock is refreshed, `import resilient_agent_loop` (all three
submodules) is proven, and the full suite is green (2678 passed). Steps 2-5 are NEXT
for this team -- read `docs/STRANGLER_PLAN.md` FIRST: it carries the verified v0.1.0
API signatures and the behavior traps each step must preserve (shift-vs-round
counting, per-round config re-read, log line ordering, output-file success predicate,
retry timing constants, single-brain relaunch invariant).

Strangler steps (each a small, separately-shippable, behavior-preserving iteration):
1. [x] Add `resilient-agent-loop-primitives` as a dependency of the foundry (pinned
   `@v0.1.0` git dependency; it is stdlib-only so no transitive weight). **(2026-08-03)**
2. **dispatcher.py -> scheduler:** replace the inline round-robin/STOP/priority loop
   with a call into the library's `scheduler`. Keep dispatcher.py's config parsing +
   logging; delegate only the scheduling core. Prove equivalence: existing dispatcher
   tests stay green byte-for-byte.
3. **foundry.run_stage -> runner:** replace the inline retry/backoff/timeout/
   output-file-success logic with the library's `runner`. Keep the stage prompt build
   + logging. Existing run_stage tests stay green.
4. **watchdog.py -> watchdog:** replace the inline decide/relaunch with the library's
   `watchdog`. Existing watchdog tests stay green.
5. Delete the now-dead inline copies. Confirm `python -c import foundry` and the full
   `tests/` suite are green, and ARCHITECTURE.md invariants still hold.

Invariant: NEVER regress behavior. Each step lands only if the full suite is green and
the change is a pure delegation (no semantic change). If the library's API is missing
something, prefer extending the LIBRARY (its own product team) over forking behavior here.

## Feature (added 2026-08-01): dual PM-scout candidate generation (optional, flag-gated)
See `docs/DUAL_PM_SCOUT_SPEC.md` for the full spec. Add an
optional two-scout pre-stage (config flag `dual_pm_scouts`, default off) before the PM
lead: `pm_scout_a` (new-capability lens) + `pm_scout_b` (hardening/DX lens) run
sequentially, then the PM lead triages both slates and picks one feature. Backward-
compatible; the disabled path must be byte-identical to today. Add tests.


---

## RESOLVED 2026-08-04 -- dual-PM-scout bite 3b-ii WIRED (operator sign-off received)

Jinchen signed off 2026-08-04; the operator applied the wiring during a global-STOP
quiescent window (dispatcher wound down gracefully, relaunched after). What changed:
- `run_iteration` now calls the iter-84 composition helper `scout_phase_outcome(cfg,
  iteration, "pm_scout.md")` immediately before the PM stage (the single sanctioned
  call site; a scout failure returns the PM-stage infra-fail dict, NO revert).
- `roles/pm.md` gained the scout-slate input + duty 1b (triage the combined slate,
  pick ONE, justify against the strongest alternative, diversity guard).
- BOTH tracked products opted in: `"dual_pm_scouts": true` in
  `products/_platform/config.json` and `products/repolens/config.json`.
- Dormancy tests legitimately revised per their own docstrings (iter-80 const-scan
  exemption for run_iteration's wiring literal; iter-81/82/83/84 role-file counts
  0 -> exactly 1; iter-84 zero-call-site -> run_iteration-only call site).
- Drive-by test-hygiene fix, same class as the iter-31 live-config snapshot:
  `test_stopping_respects_global_and_local` read the LIVE repo-root STOP sentinel
  (any operator quiesce window turned the machine's suite red and would have made
  the final gate revert good work); now isolates `global_stop` via monkeypatch.
- ARCHITECTURE.md section 2: stage-0 row + rationale (discovery degeneration,
  iters 90-101). Migration-safe: default-off path byte-identical; no sentinel,
  numbering, or state-layout change.

Remaining operator-gated wiring bites (item 21 bite 2, item 20 bite 4b, item 22
final) are UNCHANGED by this -- each still needs its own sign-off.

---

## Item 23 -- dispatcher survives a dead stdout (SMALL, incident-driven 2026-08-03)

**Problem.** A 68-shift dispatcher session died at 09:18 on `OSError(5, 'Input/output
error')` raised during a product shift and again on shutdown logging. Root cause: the
hosting terminal/PTY was torn down while the process kept running, so every later
`print()`/console write raised `OSError` -- the per-shift handler logged "continuing"
but the next console write killed the outer loop anyway. The durable log file
(`DISPATCH_LOG.md`) was fine; only the console stream was dead. An always-on brain must
not die because its terminal did.

**What ships.**
- A tiny safe-console-write helper in `dispatcher.py` (and `foundry.py` if it prints on
  the control path): wrap console writes so `OSError`/`ValueError` (closed stream) is
  swallowed after the first failure and console output is disabled for the rest of the
  session -- file logging is untouched and remains the record.
- The shutdown path ("dispatcher down; shifts this session=N") writes to the log FILE
  first, console second, so the summary always lands.
- Unit tests: a stream whose `write` raises `OSError` neither propagates nor stops shift
  scheduling; the log file still receives every line; console re-disable is one-shot
  (no per-line retry storm).

**Done when.**
- [ ] All dispatcher/foundry control-path console writes go through the helper; a dead
      stdout mid-session cannot terminate the loop (regression test simulates it).
- [ ] Shutdown summary reaches the log file even with a dead console; `tests/` green.
