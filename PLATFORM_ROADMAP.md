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

STATUS (iter 204): ledger and archive are current through 204 (193/194/199/201/203 never shipped, so none
owes a row).
STILL OPEN:
(c), (d), (g)'s `parse_triage_winner` half, (j), (k), and (o).
NEXT UP, in value order: (a) Only the OPTIONAL 25-guard
CONSOLIDATION remains, and it does NOT unblock strangler steps 2/3 (one guard still freezes
`dispatcher.py` and the meta-test requires it to); (c) repair a missing `tests/test_iterNN*.py` at the earliest
repairable stage (both iterations that lacked one, 121 and 125, REVERTED); (d) relax `roles/tester.md`'s
prose discipline around the two gate tokens, which iteration 127 makes safe but which MUST NOT ship in
the same iteration as 127 itself (a live loop holds the pre-127 `foundry.py` in memory). (f) SHIPPED iter 133 -- record in the archive. (g) **candidates half SHIPPING iter 131; the rest still open.** STILL OPEN, in order: the `parse_triage_winner` half (21 `pm.md` files carry a `## Triage` heading and still yield `None`), then rendering "present but unparsed" distinctly from "absent". (i) **DE-LISTED by iteration 130's scout A -- do NOT re-propose:** detail in the archive. ALSO STILL OPEN: the iteration-121 RETRY (its 51,824-byte
`products/_platform/state/iter-121/REVERTED_IMPLEMENTATION.patch` is preserved and its FINAL lesson
authorises the retry, plus the dispatcher restart that lesson demands), then scout A's per-product
`fast_test_cmd` for the build stages. DE-LISTED by iteration 126's spec on a measurement both its scouts
took independently: no product in the fleet has a slow suite (`_platform` 35.41 s, repolens 30.75 s) and
no product is retired for slowness, so the premise that it unblocks a slow repo is stale -- iteration 119
had already found the "repolens is retired with a 498 s suite" claim false.
THREE NEW items measured by iteration 136's scouts; FULL evidence in `products/_platform/state/iter-136/`
(`pm_scout_a.md`, `pm_scout_b.md`) -- read those before designing, do NOT re-measure. (j) ACTIVATE-ON-LAG,
biggest number on either slate: the live brain holds an Aug-5 `foundry.py`, so 14 shipped iterations (incl.
the 129/135 retry re-pricings) have NEVER executed = 2.43 h/day of fleet sleep (quote that RUN RATE, not a
total). Two bites; bite 2 edits a running loop's control flow, so it needs its own iteration. (k) the suite
is 46.58 s serial vs 17.02 s under `-n auto` (2.74x, zero verdict changes) BUT that mutates the declared
quality-check command the final gate and fresh clone consume, and 26 freeze guards would `git diff` from
many workers on ONE tree -- only for an iteration that can re-verify the fresh clone. (l) SHIPPED iter 160 -- detail in the archive.
(o) NEW, hoisted from 141's STATUS and named there as the recommended next feature: re-scope
the 26 every-suite guards asserting `git diff --quiet HEAD -- dispatcher.py scripts/ .gitignore` to an
AST/symbol invariant (dispatcher.py still imports foundry, still calls exactly load_config / run_iteration /
dispatch_progress_line in the shift loop, still honors both STOP files). PREREQUISITE for ANY dispatcher-side
change -- 141's flag shipped DORMANT because its one-line call site could not land -- and it also unblocks (j)
bite 2 and (k). TEST-OWNED and the highest blast radius on this list (it re-scopes the product's own safety net
over the running loop's control path), with `tests/test_control_path_freeze_scope.py` pinning a guard-count
FLOOR of 26 plus `FORBIDDEN = ("README.md", "roles/")`, so it wants its OWN iteration and must NOT be bundled
with a feature.
(p) SHIPPED iters 169/174/175 -- README verb-index gap now DERIVED and measured 0; detail in the archive.
(q) NEW (iter 153, successor to A1): 235 more redundant declared lines remain in the 9 `Company*` roll-up classes,
but each group covers a SUBSET (`exit_code` x4/x3, `to_dict` x3, `verdict` x5/x3, `n_flagged` x4, `files_scanned` x4,
`total_findings` x4, `total_parse_errors` x3, `total` x3) and each is the roll-up's decision/serialisation contract --
so ONE group per iteration behind golden-output comparison, never a blanket collapse. NEXT BITE, PROTOTYPED iter 164 scout B: `exit_code` x4 (57
redundant lines); a 2nd mixin AND extending `CompanyRollupCounts` each RED an iter-153 pin, so assign one module-level
fn as `exit_code = property(fn)` in the 4 class bodies -- MRO stays 3, fget identity holds, zero prior tests edited.
(r) DE-LISTED (iter 154) -- detail in the archive; do NOT re-propose.
(s) NEW (iter 155, the hotfix's deferred CLASS fix): iter 154 shipped green and turned post-release BROKEN because
a test asserted the ambient `products/` tree holds >6000 files -- true in this working tree, false in the fresh
clone the verifier builds (4 tracked files). A repo-wide guard over `tests/` banning ambient-tree COUNT
preconditions owes its own false-positive calibration: only 2 files define `_REAL_PRODUCTS`, and the many
legitimate `tmp_path` byte-walks must NOT be flagged. Calibrate two-sidedly, then ship.
(t) SHIPPED iter 156 -- detail in the archive.
(u) SHIPPED iter 181 -- detail in the archive.
(v) SHIPPED iter 163 -- detail in the archive.
(w) NEW (iter 165 scouts; FULL evidence in `products/_platform/state/iter-165/` + 165's archive bullet -- do NOT
re-measure). The company verdict hoist is item (q) and its OBVIOUS shape is KNOWN-RED: 164's scout B measured that
extending `CompanyRollupCounts` REDs an iter-153 pin, so only `exit_code = property(fn)` in the 4 class bodies is
green. 3 of the 5 gate parsers collapsed at iter 202 (54-cell matrix; archive); the `ACTION:` pair remains. THREE DE-LISTINGS: (k) is 0.8% of
an iteration (28.80s fresh-clone suite), so 2.74x buys ~18s -- it is NOT the throughput item; a digest share cap is
NOT restart-free (the budget is code in the frozen `foundry.py`), fold into (u); one-scout-per-iteration is 23.8% of
all agent time but sits behind (o).
(x) NEW (iter 183 scout A); evidence, method and rejected alternatives in 183's archive bullet -- do NOT re-measure.
Rank duplication by STATEMENTS, never lines. NEXT BITE, not bundled with 183 (same subsystem): the `render` triplet
on the three test-quality Summary classes -- 8 statements each differing in TWO string literals, uncovered by (q),
guarded by 18 literal assertions, so golden-capture it. C1 (`_head_region`) is HOT-PATH: its own iteration.
(y) NEW (iter 184 scout A; evidence + rejected alternatives in 184's archive bullet -- do NOT re-measure).
NEXT BITE RE-PRICED at 201 and DOWN-RANKED: the line ALREADY windows (`limit=20`) and WARNs naming the
worst stage + headroom, so a delta adds direction of travel only. Then scout A's `deadtail` report (12.0 min/iteration of
wall clock after the required artifact stops growing; 7.0 of it in prose-only stages). Item (i) already
DE-LISTED the stop-when-stable EARLY EXIT -- report only, never a kill.
(z) NEW (iter 186) -- DEFERRED reporting half of the 4th test-quality lens: the `unfailable-asserts` CLI
trio, then the fold into the FROZEN 3-lens `TestQualitySummary`. Detail in the archive.
INDEX BUDGET (a scheduling item, never a competitive candidate): the binding wall is now ONE constant,
`ROADMAP_INDEX_HARD_CHARS` (54,000) -- NOT the 60,000 `ROADMAP_SIZE_WARN_CHARS` -- and the two live tests that
read this file derive it from that constant, so crossing it turns the suite RED and REVERTS the iteration for a
docs-only reason. Since iter 145 `foundry doctor` prints a `roadmap-index:` line that WARNs within 3,000 chars
of the wall: ASK IT rather than measuring by hand. GROWTH, re-derived iter 166 with window+method (the figure
it replaces reproduced under none): the mean of the six per-ship deltas over iterations 159-165, paydowns excluded, is +594/iteration; worst ship seen is 165's +1,434, which left 222 chars of headroom at iter 166. Three rules that do not change: measure `len(text)`, never `wc -c`
(multibyte dashes read ~163 bytes high); NEVER delete an old `- iter N ` ledger row
(`tests/test_iter122_behavior.py:179` pins 98 frozen numbers, each needing exactly one row HERE)
or a frozen `- **iter N ` archive bullet; a move must DELETE the lines from this file, never copy them (iter
140's `## Item 16` brake). The only safe paydown is moving COMPLETED item prose and spent STATUS paragraphs
verbatim, and iter 166 UNBLOCKED it: behavior 8's `headings[-1]` pin is now an append-only PREFIX freeze, so a
NEW `## Compacted from the index by iter NNN` archive heading is legal. PAYDOWN DONE at 167 CLOSED blocks (f)/(l)/(t)/(v).

| # | Increment | Why | Done when |
|---|---|---|---|
| 1 | `prd.json`-style machine roadmap per product (id/title/criteria/passes) | Deterministic global stop + progress, vs parsing prose | dispatcher can report "N/M stories pass" via a jq-able file — **[iter 11, bite 1/3 = pure `prd_status(prd_text)` parser + frozen `PrdStatus` + on-demand `foundry prd --config <cfg>` CLI (dormant); iter 12, bite 2a/3 = wire `prd_status` into the dispatcher as a DIAGNOSTIC per-shift "N/M stories pass" log line via pure `dispatch_progress_line(cfg)` (dormant-until-data: no product has a `prd.json` yet); bite 2c = iter 143 ships the PRODUCER (`prd-init`), so the file is MAKEABLE; still unfed by design; bite 2b (future) = automatic global stop when a prd is complete → touches loop-termination/resume semantics, own iter + migration note → COMPLETES item 1]** |
| 2 | Consolidate LEARNINGS into a pinned `## Patterns` head section | COMPLETED | SHIPPED iter 08 -- prose in the archive (`Compacted from the index by iter 204`) |
| 3 | Emit an `AGENTS.md` into each product repo from its learnings | Fresh agents auto-read house rules; less re-learning | product repo has an up-to-date AGENTS.md — **[shipping iter 09, bite 1/2 = pure `render_agents_md` helper + on-demand `foundry agents` CLI; bite 2 (future) = auto-refresh AGENTS.md at ship time]** |
| 4 | Risk-split the final gate (test-only diff = light gate) | Cut gate latency ~half for coverage-only iterations | gate detects "no src/ change" and runs the light path — **[iter 15, bite 1/2 = pure `classify_gate_scope` + frozen `GateScope` + patchable `GATE_TEST_DIR_NAMES`/`GATE_DOC_SUFFIXES` + on-demand `foundry gate-scope` CLI (DORMANT; the final gate does NOT consult it, §3 full-suite-rerun invariant untouched); bite 2 (future) = wire the light path into the final gate while preserving the §3 invariant → COMPLETES item 4]** |
| 5 | Task-size guard: PM must confirm a feature fits <50% context | COMPLETED | SHIPPED iter 10 -- prose in the archive (`Compacted from the index by iter 204`) |
| 6 | Mutation-testing gate (mutmut) as a deterministic weak-assertion check | Agents emit assertions that pass without validating behavior | gate can optionally run mutation testing |
| 7 | Per-iteration suite wall-time in the log + auto-parallelize story when slow | COMPLETED | SHIPPED iter 14 -- prose in the archive (`Compacted from the index by iter 204`) |
| 8 | `scheduled` watchdog that relaunches the dispatcher if PID gone & no STOP | Survive reboots / crashes truly 24/7 | a documented, tested watchdog exists — **[shipping iter 06]** |
| 9 | `foundry.py doctor` preflight (AC power, agent CLI, uv, remote reachable) | Fail fast before burning a shift on a broken env | `doctor` subcommand returns actionable checks — **[shipping iter 01]** |
| 10 | Structured JSON event log alongside the markdown NIGHT_LOG | Machine-readable status for dashboards / the reporter | events.jsonl written per stage — **[shipping iter 05]** (retry; iter 04 was reverted by an external public-release STOP, not a feature defect) |
| 11 | **Post-release verification gate** (fresh-clone) + conventional revertable commit contract | The final gate checks the working TREE, never a clean-room checkout — this misses uncommitted files, lockfile drift, and dev-tree import leakage. For a project whose PRIMARY goal is trustworthy continuous release/deployment, a green working tree is not proof the release is deployable | a `postrelease` stage runs on every ship, clones `origin/<branch>` fresh, re-verifies, emits `POSTRELEASE: HEALTHY\|BROKEN`, and a BROKEN result raises a per-product hotfix flag the next PM must clear (see detailed spec below) — ✅ **SHIPPED (iter 02 bite 1/2 = config fields + dormant verify helper, `0fc54c1`; iter 03 bite 2/2 = wiring + `POSTRELEASE:` sentinel + hotfix-flag lifecycle + commit contract)** |
| 12 | Read-only `foundry status` company-health probe | COMPLETED | SHIPPED iter 16 -- prose in the archive (`Compacted from the index by iter 204`) |
| 13 | Read-only `foundry history` multi-iteration ship ledger | COMPLETED | SHIPPED iter 17 -- prose in the archive (`Compacted from the index by iter 204`) |
| 14 | Single-brain launch preflight (`foundry single-brain`) | The #1 OBSERVED live failure is two dispatchers on one model-API account starving the shared token budget (LEARNINGS `[PM iter01]`, VISION single-brain constraint); `foundry doctor` cannot cover it (its 4-check contract is pinned by iter-01 tests) and the iter-06 watchdog only guards RESURRECTION, not an operator's manual launch | `foundry single-brain [--pattern P]` scans for a running dispatcher and exits 0 SAFE / 1 CONFLICT / 2 UNKNOWN so a launch wrapper can gate on it — **[shipping iter 24 = read-only `running_dispatchers` seam + frozen `SingleBrainStatus` + pure `summarize_single_brain` + on-demand `foundry single-brain` CLI (off the control path, reports only — never kills/force-anything); successor = `--json`]** |

## Ship order (PM re-orders by value each iteration)

### Done ledger -- one line per shipped iteration

Full per-iteration detail lives VERBATIM in `PLATFORM_ROADMAP_ARCHIVE.md`; it is never
summarised and never read by a role. Keep this index terse: two suite tests fail this file at
`ROADMAP_INDEX_HARD_CHARS` (54,000 -- the BINDING wall, see INDEX BUDGET above), a third warns at
`ROADMAP_SIZE_WARN_CHARS` (60,000), and a fourth fails if any iteration named here has no bullet
in the archive.

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
- iter 136 -- retired 4 SPENT operator directives from the prompt head (-6,468 chars); doctor WARNs an over-budget head.
- iter 137 -- NEW `foundry new-product` scaffolder + immediate lint; fixes the `USAGE.md` cp on-ramp that exits 1.
- iter 138 -- steering head emits VERBATIM when it fits its budget; truncate only on real overflow.
- iter 139 -- both GATE cards carry their verify-first EXCEPTION; pure card audit + live suite brake stops drift.
- iter 140 -- lint-config NAMES a dispatcher roster and exits 2, instead of advising the `_` prefix that empties it.
- iter 141 -- RESTART_NEEDED.md flag + auto-clear, SHIPPED DORMANT: 26 freeze guards block the dispatcher call site.
- iter 142 -- roles/pm.md gets a RUNNABLE lint-spec invocation; two-sided brake on bare `foundry <verb>` in any card.
- iter 143 -- prd-init renders a schema-valid prd.json from EXPLICIT stories; producer for the live shift-loop meter.
- iter 144 -- NEW read-only `foundry prompt`: the EXACT bytes a stage receives, + a two-sided digest drift guard.
- iter 145 -- one roadmap-index wall constant + pure headroom verdict + a `doctor` WARN line.
- iter 146 -- six byte-identical `company_*_cli` bodies collapse to ONE shared body + thin wrappers (-124 lines).
- iter 147 -- both review gates route on the ANCHORED verdict; an APPROVE quoting the token no longer fires a fix pass.
- iter 148 -- stage-times splits every no-output attempt by failure KIND; the field named `timeouts` was 2.00x.
- iter 149 -- quality_bar cited 2 invariants with 0 hits in ARCHITECTURE.md; pure gap brake + live two-sided guard.
- iter 151 -- revert_repo saves the doomed tree to ABORTED_IMPLEMENTATION.patch before its reset; the reset stays total.
- iter 152 -- three extra-kwarg `company_*_cli` stragglers fold into the shared roll-up body; item (i) closed 9 of 9.
- iter 153 -- one `CompanyRollupCounts` mixin retires 27 hand-copied n_* props across the 9 roll-up dataclasses.
- iter 154 -- the read-only-CLI tree guard reads git-visible state, not 6574 files of bytes; 3.7s + a live flake gone.
- iter 155 -- HOTFIX: the bounded-snapshot oracle builds its own tmp_path fixture; fresh-clone suite green again.
- iter 156 -- `foundry preship` re-verifies the ship commit from a LOCAL clone between commit and push; exit 1 blocks.
- iter 157 -- every stage prompt names this product's own config path, name-verified, so card --config verbs run.
- iter 158 -- five spent blurbs + two tombstones leave the index (verbatim to archive); pure roadmap_spent_blocks.
- iter 159 -- the composite test-quality scan walks the repo once and parses each test file once; output byte-identical.
- iter 160 -- both docs price all THREE retry ladders, rendered by calling retry_delay; whole-line presence guard.
- iter 162 -- new `save-work` verb saves uncommitted work to a patch from a FRESH process; real git index untouched.
- iter 163 -- roles/engineer.md + roles/fix.md run `save-work`, so the iter-162 rescue fires; 20 reverts, 0 rescues.
- iter 164 -- doctor's 4th drift line prices the worst stage median vs the HARD 600s cap; engineer sat at 0.0s.
- iter 165 -- eight per-product --json CLI printers collapse onto ONE _thin_gather_cli body; seams stay call-time.
- iter 166 -- iter-158's last-heading archive pin becomes an append-only PREFIX freeze; index paydown unblocked.
- iter 167 -- the spent (l)/(t)/(v) bodies move VERBATIM to a new archive compaction; index drops below 52,000.
- iter 168 -- new rescues verb splits 600s kills into RESCUED vs LOST per stage; stage-times saw 45 of 232.
- iter 169 -- iter-167's three frozen index-size pins gain a derived per-row allowance; the brake had 8 chars left.
- iter 170 -- weak-test scans scope to the repo's own tests/ dir; 195 of 345 gathered files were gitignored state.
- iter 172 -- rescues rows gain kill_rate (kills/attempts); pm shows a 100% rescue rate while killed on 60 of 186.
- iter 173 -- re-lands iter 172; new losses verb splits no-output attempts by CAUSE; rescues saw 9 of 64.
- iter 174 -- lands the lost 172+173 patch; the README index pin drops POSITION; 5th team config ignored.
- iter 175 -- README index-number rule moves into foundry.py; a tests/-wide guard bans snapshot pins in any file.
- iter 176 -- roles/pm.md must quote doctor's measured `stage-budget:` line when sizing a bite; exit code is ADVISORY.
- iter 177 -- suite runs -n auto by default via pyproject addopts; a brake pairs each plugin addopt with its dep.
- iter 178 -- DIRECTIONS.md `ship:` takes git ship-truth as authority; a brake flags rows git proves shipped.
- iter 179 -- re-lands 178's git ship-truth labels; the healed-row proof moves off the live artifact onto a fixture.
- iter 180 -- outcomes reads the AUTHORITATIVE tester report (newest tester<N>.md), clearing 27 false FAIL rows.
- iter 181 -- doctor's learnings-head WARN names the WORST-elided head bullet (label + chars), not just how many.
- iter 182 -- agents refuses to clobber a hand-written AGENTS.md (exit 2, --force overrides); ignore line DEFERRED.
- iter 183 -- three gather_* test-quality scanners collapse onto ONE shared body; 26 redundant statements gone.
- iter 184 -- stage-times gains --limit N; doctor's mandatory stage-budget: line prices the RECENT window, not all-time.
- iter 185 -- roadmap CLI-verb figure becomes DERIVED; two frozen 48-verb pins retire; spent (p) archived.
- iter 186 -- 4th test-quality lens detects an assert that CANNOT fail; tests/ pinned at 0; iter-152 site repaired.
- iter 188 -- gap-radar phase 1: gather_gaps/gap_advice/pm_gap_block read the register from local JSON; ZERO call site.
- iter 189 -- ship_decision tells a CAP-KILLED final gate from an explicit REVERTED: SHIP/RETRY/REVERT, zero call site.
- iter 190 -- stage-times prices cap SATURATION per group: total_s/cap_hits/cap_seconds + cap_share_pct + one rollup.
- iter 191 -- ARCHITECTURE.md records the verdict-ABSENCE rule + the DORMANT ship_decision successor; parity brake.
- iter 192 -- gap-radar phase 2: build_prompt calls pm_gap_block and _platform opts in, so the PM feed goes LIVE.
- iter 195 -- re-land iter 194: ship_decision wired at the live final gate; a cap-killed round RETRIES, not reverts.
- iter 196 -- an expired session gets its own `auth` failure kind, ordered before `timeout` and priced identically.
- iter 197 -- gap-radar phase 2's missing half: `roles/pm.md` now REQUIRES the `GAP:` line; dormant verdict core.
- iter 198 -- preship discloses the sha it verified and the worktree it is blind to; report-only, verdict frozen.
- iter 200 -- re-land iter 199: `running_dispatchers` counts real python brains, not prompt-text mentions.
- iter 202 -- the tree-snapshot guard stops blaming lint-config for a concurrent worker's .pyc; iter 201 re-lands.
- iter 204 -- re-land 203's company-stops; the frozen newest-ness pin class that reverted it is retired.


### Migration notes (per §6 self-mod guardrail)
- iters 03, 14, 26, 52 — bodies ARCHIVED verbatim to `PLATFORM_ROADMAP_ARCHIVE.md` under `## Compacted from the index by iter 182`. Append NEW notes here.
- items 2, 5, 7, 12, 13 (COMPLETED table rows) — prose ARCHIVED verbatim by iter 204 under `## Compacted from the index by iter 204`; 4-column stubs remain.

## Guardrails for self-modification
- Never change iteration numbering, state layout, or the `VERDICT:`/`RESULT:`/
  `ACTION:` sentinel contract without a migration note in this file.
- Every change keeps `uv run --with pytest pytest -q` green and both modules
  importable (`python -c "import foundry, dispatcher"`).
- If an increment would touch a currently-running loop's resume behaviour,
  defer it or gate it behind a version flag.

## Item 16 (ARCHIVED by iter 140; SHIPPED: leak-guard committed, final gate step 6 runs it fail-closed)

Section moved VERBATIM to `PLATFORM_ROADMAP_ARCHIVE.md` under `## Moved from the index by iter 140`.

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
