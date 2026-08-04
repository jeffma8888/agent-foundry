# agent-foundry

**An always-on autonomous product org.** Point it at any git repo and a lean
core team of AI agents — a product agent, an engineer, a reviewer, an isolated
QA engineer, and an independent release gate — builds it feature by feature,
around the clock, shipping only work that passes every gate. Behind that lean
core sits a **rich bench** of dormant specialist roles (legal, design, finance,
DevRel, TPM, ...) that activate only when a written trigger fires.

> The foundry pours raw ideas in and casts working software out.
> Its first artifact is **[repolens](https://github.com/jeffma8888/repolens)** —
> a repo-analysis CLI it built and shipped 9 features for, overnight, unattended.

## The org chart

```
                 ┌─────────────┐
                 │  Dispatcher │  the always-on "chief of staff":
                 │ (single brain)│  round-robins one team at a time so they
                 └──────┬──────┘  never split the model-token budget
          ┌────────────┼────────────┐
   ┌──────▼─────┐              ┌─────▼──────┐
   │  Platform  │              │  Product   │   (repolens, and any repo you add)
   │    team    │              │   team(s)  │
   │ improves   │              └─────┬──────┘
   │ the foundry│                    │
   └────────────┘         per iteration, one small feature:
                          PM → Engineer → Reviewer → [Fix]
                              → Isolated Tester → [Fix → Tester]
                              → Final Reviewer (ships or reverts)
```

Each stage is a **fresh** agent-CLI run (clean context, no memory bloat).
The only memory between stages/iterations lives on disk: the spec, the diff,
the commit history, and the learnings log.

## The org model: a rich bench, a lean active team

Most multi-agent systems fail by *over-staffing*: every extra active role is a
handoff seam where context drops, agents misalign, and wrong claims pass
unverified — the dominant failure classes in the largest study of multi-agent
traces (MAST, arXiv:2503.13657: gains over single agents are “often minimal”;
failures concentrate in inter-agent misalignment and weak verification). More
roles means more communication, more misalignment, and weaker verification.
So the foundry inverts the instinct. The model:

> **Rich bench → a cheap kickoff council staffs the minimum → a lean always-on
> core → everything else is trigger/cadence-activated → re-staffing is bounded
> and clean.**

Breadth lives in cheap, versioned **role-cards** (a bench that costs nothing
while dormant). Cost and failure surface live only in the roles that actually
run. A role earns always-on status only if it must act on *every* iteration.

**The always-on core (the entire standing cost of a product team):**

```
Product agent → Engineer → Reviewer → isolated Tester → Release Gate
```

**The bench** — every seat is a role-card in [`roles/bench/`](roles/bench/)
declaring its mission, activation trigger, tenure, I/O contract, and model note:

| Seat | In one line |
|---|---|
| [CEO / Founder](roles/bench/ceo.md) | Single accountable decider: mission, staffing, budget in agent-runs; sole escalation path to the human. |
| [Business / Finance](roles/bench/business_finance.md) | Allocates iterations like a default-alive CFO; prices every bet, demands an impact number. |
| [Legal](roles/bench/legal.md) | Licenses, data/privacy, IP — wakes only when a change touches them. |
| [Designer](roles/bench/designer.md) | Human-facing surface quality — wakes when a UI or UX contract ships. |
| [DevRel / Docs](roles/bench/devrel_docs.md) | Public docs and onboarding — wakes when a public API changes. |
| [Product Manager](roles/bench/product_manager.md) | The merged “why + what” product agent; owns the spec and the smallest slice. **Core.** |
| [Product-gate PM](roles/bench/product_gate_pm.md) | Adversarial gate seat; attacks impact math and scope. Runs on a *different model* than the builder. |
| [TPM](roles/bench/tpm.md) | Cross-module dependency coordination; dormant until a countable dependency threshold. |
| [Engineer](roles/bench/engineer.md) | Smallest diff that passes every gate. **Core.** |
| [QA / Tester](roles/bench/qa_tester.md) | Black-box, spec-only, firewalled from the source. **Core.** |
| [Release Gate](roles/bench/release_gate.md) | Only role touching git; recomputes ground truth; rejects on doubt. **Core.** |

The bench is **extensible by design**: when the kickoff council or a
re-staffing review finds a gap — a Security Reviewer for a product that grows
auth, a Performance Engineer for a latency-critical service — it mints a new
role-card into the bench (mission, trigger, tenure, I/O contract, model note)
instead of overloading an existing seat. New roles enter dormant by default.

**The tri-perspective product gate.** Before iterations are spent, a proposal
survives three decorrelated attacks or dies (default verdict: Kill):
*Business* — is the problem worth it? (impact number + key assumption +
pre-mortem); *Product* — is this the smallest right solution? (goals/non-goals
+ appetite + alternatives); *Senior engineer* — can it be built? (riskiest
unknown + knock-outs). The mental model: one reviewer approves a bad idea from
its own blind side; three perspectives with different failure directions,
running on a different model than the author (self-preference bias,
arXiv:2404.13076), rarely share one. Deterministic pre-checks run before any
model call, and every Go carries a fixed iteration bet.

**Cadence.** Roles activate at kickoff or on written triggers — the cheapest
scheme that still catches the decisions that matter — with a fixed-N fallback:
if no trigger fires for 5 iterations, the CEO + PM review the project anyway,
so a quiet loop cannot drift unexamined.

Full blueprint — kickoff council, JSON staffing manifest, trigger rubric,
escalation predicates, bounded re-staffing — in
**[docs/ORG_DESIGN.md](docs/ORG_DESIGN.md)**, built on eight sourced research
briefs in [docs/research/](docs/research/README.md).

## Why it works — five hard-won invariants

1. **Trust artifacts, not claims.** A stage succeeds only if its output file
   exists and is non-empty. Exit codes and agent self-reports are ignored.
2. **The gate is independent and pessimistic.** The Final Reviewer re-runs the
   full test suite itself and is the *only* role allowed to touch git. On any
   doubt it reverts to `origin/<branch>` rather than ship half-done work.
3. **QA is firewalled.** The Tester may not read `src/` — only the spec and the
   product's observable behavior. Black-box tests can't "test to the code," so
   they catch what the author and reviewer both missed.
4. **Anti-delegation, everywhere.** Every role prompt forbids nested agent runs
   / re-delegation, so sub-agents do the work instead of spawning more loops.
5. **Infra failures never kill the loop.** Throttling, stalls, and 600s timeouts
   are absorbed by per-stage retry + exponential backoff and an infra-cooldown;
   the loop runs until you tell it to stop.

## Quickstart

```bash
# 0. Preflight the box before committing a shift (AC power, agent CLI, uv, remote):
uv run python foundry.py doctor --config products/repolens/config.json

# 1. Run one product team on an existing repo, a single iteration:
uv run python foundry.py once --config products/repolens/config.json

# 2. Run one product team continuously (until you `touch STOP`):
uv run python foundry.py run  --config products/repolens/config.json

# 3. Run the whole company (platform + all products) as one quota-safe brain:
cp foundry.config.example.json foundry.config.json      # edit enabled/priority
uv run python dispatcher.py --config foundry.config.json
#    (the dispatcher logs "N/M stories pass" into DISPATCH_LOG.md each shift for
#     any product that has a prd.json; a no-op for products without one.)

# 4. Read the bounded learnings digest (pinned `## Patterns` head + recent tail):
uv run python foundry.py learnings --config products/repolens/config.json  # [--recent N] [--json for one machine-readable learnings view: dashboards/reporters/CI; same exit 0 both modes]

# 5. Emit an AGENTS.md house-rules file into the product repo from its learnings:
uv run python foundry.py agents --config products/repolens/config.json  # [--recent N] [--print]

# 6. Lint a PM spec for completeness + size before an iteration (exit 1 = REVIEW):
uv run python foundry.py lint-spec --file products/repolens/state/iter-NN/pm.md  # [--json for one machine-readable lint verdict: release-gate/CI/operator; same 0/1/2 exit code (2 = file-not-found, always plain-text)]

# 7. Report "N/M stories pass" from a product prd.json (exit 0 complete/1 incomplete/2 missing|invalid):
uv run python foundry.py prd --config products/repolens/config.json  # [--json for one machine-readable prd-status doc: dashboards/reporter/CI; same 0/1/2 exit code; a missing file stays the plain-text error]

# 8. Classify a diff's scope (coverage-only "light" vs "full"); DORMANT — the gate does not consult it yet:
uv run python foundry.py gate-scope --config products/repolens/config.json  # [--base REF] [--files path ...] [--json for one machine-readable scope classification: dashboards/CI/gate-wiring; same 0/1/2 exit code (2 = git-diff-seam failure, only without --files, always plain-text)]

# 9. Company-health probe: latest iter + last ship's POSTRELEASE verdict + the HOTFIX/SPEED flags + prd (exit 0 healthy/1 attention/2 nothing shipped):
uv run python foundry.py status --config products/repolens/config.json  # [--json for one machine-readable snapshot: dashboards/alerts; same 0/1/2 exit code]

# 10. Multi-iteration ship ledger: each iteration's ACTION + POSTRELEASE outcome, ascending, + a rollup (exit 0 has-history/2 nothing shipped); read-only:
uv run python foundry.py history --config products/repolens/config.json  # [--limit N] [--json for one machine-readable ledger doc: dashboards/reporter; same 0/2 exit code, honours --limit]

# 11. Per-iteration suite wall-time digest: each iter's fresh-clone suite seconds + a min/max/avg/last + slow-count rollup (exit 0 has-measured-timings/2 none measured); read-only:
uv run python foundry.py timing --config products/repolens/config.json  # [--limit N] [--json for one machine-readable digest doc: dashboards/reporter; same 0/2 exit code, honours --limit]

# 12. Scan test files for assertion-free `test*` functions (a test that passes without validating anything = false green); DORMANT -- the pipeline/gate never consults it (exit 0 clean/1 weak-or-unparseable/2 nothing to scan); read-only:
uv run python foundry.py weak-tests --config products/repolens/config.json  # [--files path ...] to scan exactly those files instead of walking the repo [--json for one machine-readable scan doc: dashboards/reporter/CI; same 0/1/2 exit code, honours --files]

# 13. Launch preflight: refuse to start a SECOND brain -- report whether a dispatcher is ALREADY running before you launch (exit 0 SAFE/1 CONFLICT/2 UNKNOWN); needs NO --config, read-only, writes nothing:
uv run python foundry.py single-brain  # [--pattern P] process-command pattern to scan for (default 'dispatcher.py'); gate a launch on `[ $? -eq 0 ]` [--json for one machine-readable verdict doc: launch-wrapper/CI; same 0/1/2 exit code]

# 14. Digest a product's typed events.jsonl: filter by kind, tail the most-recent N, count by kind (exit 0 something-shown/2 nothing shown); DORMANT -- the pipeline/dispatcher never call it, writes nothing; read-only:
uv run python foundry.py events --config products/repolens/config.json  # [--kind K] exact-match filter [--limit N] tail most-recent N [--json for one machine-readable digest doc: dashboards/reporter; same 0/2 exit code, honours --kind/--limit]

# 15. Composite LAUNCH gate: fold the env preflight (#0 doctor) AND the single-brain scan (#13) into ONE three-way GO / NO-GO / CAUTION verdict before starting the dispatcher (exit 0 GO / 1 NO-GO / 2 CAUTION); read-only, writes nothing, report-only (the operator decides):
uv run python foundry.py preflight --config products/repolens/config.json  # [--pattern P] process-command pattern to scan for a running dispatcher (default 'dispatcher.py'); a confirmed env blocker or a rival brain is NO-GO(1), an uncheckable scan on a ready env is CAUTION(2); gate a launch on `[ $? -eq 0 ]` [--json for one machine-readable composite verdict doc: launch-wrapper/CI; same 0/1/2 exit code]

# 16. Company-wide health roll-up (#9 status across the WHOLE company): read the DISPATCH config and roll every ENABLED product team's iter-16 `status` into ONE company verdict + a scriptable exit code (0 healthy / 1 needs-attention / 2 no-enabled-products); read-only, writes nothing:
uv run python foundry.py company-status  # --config points at the DISPATCH config (foundry.config.json), NOT a product config (default: the repo's foundry.config.json); a disabled work item is never loaded; one bad team is recorded and the roll-up continues [--json for one machine-readable company roll-up doc: dashboards/cron; same 0/1/2 exit code]

# 17. Company-wide ship-ledger roll-up (#10 history across the WHOLE company -- the TREND complement to #16): read the DISPATCH config and sum every ENABLED product team's iter-10 `history` ledger into ONE company total/shipped/reverted/broken + a per-product breakdown + a scriptable exit code (0 OK / 1 a team errored / 2 no-enabled-products); read-only, writes nothing:
uv run python foundry.py company-history  # --config points at the DISPATCH config (foundry.config.json), NOT a product config (default: the repo's foundry.config.json); a disabled work item is never loaded; one bad team is recorded and the roll-up continues; a past BROKEN in a team's ledger is informational and never gates [--limit N per team] [--json for one machine-readable company ledger doc: dashboards/cron; same 0/1/2 exit code, honours --limit]

# 18. Company-wide suite-wall-time roll-up (#11 timing across the WHOLE company -- the THROUGHPUT complement to #16/#17): read the DISPATCH config and fold every ENABLED product team's iter-11 `timing` digest into ONE company measured/total + pooled min/max/avg + summed slow-count + a per-product breakdown + a scriptable exit code (0 OK / 1 a team errored / 2 no-enabled-products); read-only, writes nothing:
uv run python foundry.py company-timing  # --config points at the DISPATCH config (foundry.config.json), NOT a product config (default: the repo's foundry.config.json); a disabled work item is never loaded; one bad team is recorded and the roll-up continues; a slow-but-fixed suite is informational and never gates [--limit N per team] [--json for one machine-readable company timing doc: dashboards/cron; same 0/1/2 exit code, honours --limit]

# 19. Company-wide weak-test roll-up (#6 weak-tests across the WHOLE company -- the QUALITY complement to #16/#17/#18): read the DISPATCH config and fold every ENABLED product team's iter-6 `weak-tests` scan into ONE company files-scanned/assertion-free-tests/parse-errors total + a per-product breakdown + a scriptable exit code; UNLIKE informational history/timing it GATES on findings (0 clean / 1 a worthless test OR an unparseable file OR a team errored ANYWHERE / 2 no-enabled-products); read-only, writes nothing:
uv run python foundry.py company-weak-tests  # --config points at the DISPATCH config (foundry.config.json), NOT a product config (default: the repo's foundry.config.json); a disabled work item is never loaded; one bad team is recorded and the roll-up continues; a worthless test anywhere gates the company (exit 1) [--json for one machine-readable company weak-test doc: dashboards/cron; same 0/1/2 exit code]

# 20. Company-wide event roll-up (#14 events across the WHOLE company -- the ACTIVITY complement to #16/#17/#18/#19; the 5th and LAST company-* member): read the DISPATCH config and fold every ENABLED product team's iter-14 `events` digest into ONE company total/matched/shown/malformed + a merged per-kind tally + a per-product breakdown + a scriptable exit code; INFORMATIONAL like history/timing -- a malformed line or a quiet team never gates (0 gathered-no-errors / 1 a team errored / 2 no-enabled-products); read-only, writes nothing:
uv run python foundry.py company-events  # --config points at the DISPATCH config (foundry.config.json), NOT a product config (default: the repo's foundry.config.json); a disabled work item is never loaded; one bad team is recorded and the roll-up continues; a malformed line or a quiet team is informational and never gates [--kind K exact-match filter per team] [--limit N tail most-recent N per team] [--json for one machine-readable company events doc: dashboards/cron; same 0/1/2 exit code, honours --kind/--limit]

# 21. Scan test files for `test*` functions whose ONLY assertion is a constant/tautological assert (`assert True`, `assert 1`, `assert "x"`) -- a false green that #12 `weak-tests` structurally MISSES (a constant assert CARRIES an assert node, so it reads as a signal); the first call site of the iter-47 `find_constant_assert_tests` detector, DISJOINT from #12 by construction. DORMANT -- the pipeline/gate never consults it (exit 0 clean/1 constant-assert-or-unparseable/2 nothing to scan); read-only:
uv run python foundry.py constant-asserts --config products/repolens/config.json  # [--files path ...] to scan exactly those files instead of walking the repo [--json for one machine-readable scan doc: dashboards/reporter/CI; same 0/1/2 exit code, honours --files]

# 22. Company-wide constant-assert roll-up (#21 constant-asserts across the WHOLE company -- the QUALITY complement to #19; the 6th and LAST company-* member): read the DISPATCH config and fold every ENABLED product team's iter-21 `constant-asserts` scan into ONE company files-scanned/constant-assert-tests/parse-errors total + a per-product breakdown + a scriptable exit code; UNLIKE informational history/timing/events it GATES on findings (0 clean / 1 a constant-assert test OR an unparseable file OR a team errored ANYWHERE / 2 no-enabled-products); read-only, writes nothing:
uv run python foundry.py company-constant-asserts  # --config points at the DISPATCH config (foundry.config.json), NOT a product config (default: the repo's foundry.config.json); a disabled work item is never loaded; one bad team is recorded and the roll-up continues; a constant-assert test anywhere gates the company (exit 1) [--json for one machine-readable company constant-assert doc: dashboards/cron; same 0/1/2 exit code]

# 23. Scan test files for `test*` functions that are UNCONDITIONALLY skipped (`@pytest.mark.skip`, `@unittest.skip`, a constant-condition `@skipif(True)`/`@skipUnless(False)`) -- a test that NEVER runs, validates nothing, yet reports the suite green, and no gate catches it (the #11 fresh-clone re-run passes a skipped test too); the first call site of the iter-55 `find_always_skipped_tests` detector, a THIRD complementary lens to #12/#21 that can OVERLAP them (a skipped test may also be assertion-free) by catching a DIFFERENT antipattern -- a test that never runs at all. DORMANT -- the pipeline/gate never consults it (exit 0 clean/1 always-skipped-or-unparseable/2 nothing to scan); read-only:
uv run python foundry.py skipped-tests --config products/repolens/config.json  # [--files path ...] to scan exactly those files instead of walking the repo [--json for one machine-readable scan doc: dashboards/reporter/CI; same 0/1/2 exit code, honours --files]

# 24. Company-wide always-skipped-test roll-up (#23 skipped-tests across the WHOLE company -- the QUALITY complement to #19/#22; the 7th company-* member): read the DISPATCH config and fold every ENABLED product team's iter-23 `skipped-tests` scan into ONE company files-scanned/always-skipped-tests/parse-errors total + a per-product breakdown + a scriptable exit code; UNLIKE informational history/timing/events it GATES on findings (0 clean / 1 an always-skipped test OR an unparseable file OR a team errored ANYWHERE / 2 no-enabled-products). UNLIKE the DISJOINT #22, an always-skipped test may ALSO be assertion-free, so its findings can OVERLAP #19 `company-weak-tests` / #22 `company-constant-asserts` -- a THIRD complementary company lens catching a DIFFERENT antipattern (a test that never RUNS at all); read-only, writes nothing:
uv run python foundry.py company-skipped-tests  # --config points at the DISPATCH config (foundry.config.json), NOT a product config (default: the repo's foundry.config.json); a disabled work item is never loaded; one bad team is recorded and the roll-up continues; an always-skipped test anywhere gates the company (exit 1) [--json for one machine-readable company skipped-test doc: dashboards/cron; same 0/1/2 exit code]

# 25. Per-product COMPOSITE test-quality gate: fold all THREE offline "validates-nothing" scans -- #12 `weak-tests` (assertion-free), #21 `constant-asserts` (constant/tautological assert), #23 `skipped-tests` (never runs) -- into ONE scan / ONE 0/1/2 exit code / ONE three-way verdict / ONE JSON doc, so certifying a product against all three test antipatterns takes ONE command with a per-CATEGORY breakdown instead of three (each re-walking the repo, whose 0/1/2 codes a shell `weak-tests && constant-asserts && skipped-tests` would collapse into one undifferentiated non-zero). The QUALITY-axis parallel of the #15 launch `preflight` composite. #21 is DISJOINT from #12 by construction, but a #23 always-skipped test may ALSO be assertion-free AND carry a constant assert, so its findings can OVERLAP #12/#21 -- therefore `total quality findings` is a per-CATEGORY triage total (a test flagged by two lenses counts once per category), NOT a de-duplicated distinct-test count. DORMANT -- the pipeline/gate never consults it (exit 0 clean/1 quality-issues-found/2 nothing to scan); read-only:
uv run python foundry.py test-quality --config products/repolens/config.json  # [--files path ...] to scan exactly those files instead of walking the repo [--json for one machine-readable composite doc embedding the three sub-scans: dashboards/reporter/CI; same 0/1/2 exit code, honours --files]
# 26. Company-wide COMPOSITE test-quality roll-up (#25 test-quality across the WHOLE company -- the COMPANY-axis parallel of the per-product #25 composite and the QUALITY-axis capstone of the company family; the 8th company-* member): read the DISPATCH config and fold every ENABLED product team's iter-25 `test-quality` composite into ONE company files-scanned/per-category-findings/total-findings/parse-errors total + a per-product breakdown + a scriptable exit code; UNLIKE informational history/timing/events it GATES on findings (0 clean / 1 a quality finding of ANY category OR an unparseable file OR a team errored ANYWHERE / 2 no-enabled-products). It folds the three company quality axes #19 `company-weak-tests` / #22 `company-constant-asserts` / #24 `company-skipped-tests` into ONE view, INHERITING #25's category-weighting: #22 is DISJOINT from #19 by construction, but a #24 always-skipped test may ALSO be assertion-free AND carry a constant assert, so its findings can OVERLAP #19/#22 -- therefore `total quality findings` is a per-CATEGORY triage total (a test flagged by two lenses counts once per category), NOT a de-duplicated distinct-test count; read-only, writes nothing:
uv run python foundry.py company-test-quality  # --config points at the DISPATCH config (foundry.config.json), NOT a product config (default: the repo's foundry.config.json); a disabled work item is never loaded; one bad team is recorded and the roll-up continues; a quality finding of any category anywhere gates the company (exit 1) [--json for one machine-readable company composite doc embedding the per-product test-quality scans: dashboards/cron; same 0/1/2 exit code]
# 27. Lint a PRODUCT config for the misconfigurations that silently waste a shift or defeat the push guard -- the CONFIG-validation complement to #0 `doctor` (env) and #6 `lint-spec` (spec); an offline, deterministic linter that inspects a resolved `ProductConfig` and reports leveled findings: a missing/non-git `repo`, an empty `test_cmd`, a missing `roles_dir`, a missing `vision` FILE, or -- the SAFETY case -- an empty `allowed_push_repo` while `push_enabled` is true (which makes the push guard block EVERY ship) are ERRORS, while an unset `vision` or a missing `roadmap`/`quality_ref` FILE are WARNINGS (warnings alone still pass). DORMANT -- the pipeline/gate/dispatcher never call it and it writes nothing (exit 0 OK-or-warnings-only / 1 config-errors / 2 unreadable-config); read-only:
uv run python foundry.py lint-config --config products/repolens/config.json  # points at a PRODUCT config (NOT the dispatch config); an unreadable/invalid-JSON config maps to exit 2, distinct from a lint PROBLEMS=1 [--json for one machine-readable lint doc: launch wrappers/cron; same 0/1/2 exit code]
# 28. Company-wide product-config lint roll-up (#27 lint-config across the WHOLE company -- the CONFIG-VALIDATION-axis fleet roll-up; the 9th company-* member, closing the LONE read-only per-product probe that had no roll-up): read the DISPATCH config and fold every ENABLED product team's iter-27 `lint-config` verdict into ONE company config-errors/warnings/total-findings total + a per-team breakdown + a scriptable exit code, so an operator gates the whole fleet on `[ $? -eq 0 ]` (highest-value finding: the SAFETY case -- a team whose `allowed_push_repo` is empty while `push_enabled` is true would silently block EVERY ship). KEY divergence from the QUALITY roll-ups #19/#22/#24/#26 (which gate on ANY finding): ONLY config ERRORS gate -- a team load/gather error OR any product config ERROR anywhere -> exit 1; WARNINGS ALONE STILL PASS (a warning names a degraded-but-runnable config), surfaced in the counts but non-gating; else 0 clean-or-warnings-only / 2 no-enabled-products. DORMANT -- the pipeline/gate/dispatcher never call it and it writes nothing; read-only:
uv run python foundry.py company-lint-config  # --config points at the DISPATCH config (foundry.config.json), NOT a product config (default: the repo's foundry.config.json); a disabled work item is never loaded; one bad team is recorded and the roll-up continues; only config ERRORS gate the company (exit 1) -- warnings alone still pass [--json for one machine-readable company doc embedding the per-product lint verdicts: dashboards/cron; same 0/1/2 exit code]
# 29. Lint the hand-written bench role-cards (`roles/bench/*.md`) against the fixed card contract -- the BENCH-facing sibling of #0 `doctor` (env), #6 `lint-spec` (spec), and #27 `lint-config` (config), and the FIRST org-design-track item (roadmap 17), which the later manifest-driven items (18 `lint-manifest`, 19 the manifest-driven pipeline) need so they can trust a card as machine-readable. An offline, deterministic linter: each `*.md` file (basename `README.md` is SKIPPED, it is docs not a card) must carry all 7 required markers in a FIXED check order -- a `# Bench role card:` title H1, `Status:`/`Model note:` line-start header fields, `Activation:`/`Tenure:` inline substrings, and the `## Mission` + `## I/O contract` section headings (exact-heading match) -- and each missing marker is one `card:line` finding (line 1, the deterministic convention). DORMANT -- the pipeline/gate/dispatcher never call it and it writes nothing (exit 0 OK / 1 card-issues-or-unreadable / 2 no-card-files); read-only:
uv run python foundry.py lint-bench  # --dir defaults to the foundry's OWN roles/bench (validates the live bench; all shipped cards pass); a nonexistent --dir is treated as 'no cards' (exit 2), never raises; needs NO product --config [--json for one machine-readable lint doc: cron/dashboards; same 0/1/2 exit code]
# 30. Lint a product's STAFFING MANIFEST (`staffing.json`) against the documented schema -- the MANIFEST-facing sibling of #0 `doctor` (env), #6 `lint-spec` (spec), #27 `lint-config` (config), and #29 `lint-bench` (bench), and the SECOND org-design-track item (roadmap 18, bite 1), which the manifest-driven pipeline (item 19) needs so it can trust a `staffing.json` before consuming it. An offline, deterministic validator applying FOUR rules, each finding tagged with its `rule`: `schema` (top level is an object with `product` [non-empty str] + `iteration_budget` [int > 0] + `roles` [non-empty list of well-formed `{role,model,gate,done_criteria}` objects in run order]); `bench_card` (every well-formed role name has a `<bench-dir>/<name>.md` card); `core_seat` (the five core seats product_manager/engineer/reviewer/qa_tester/release_gate are all staffed, in that fixed order); `budget` (`iteration_budget` is a positive int, not a bool). Findings are deterministically ordered schema -> bench_card -> core_seat -> budget. DORMANT -- the pipeline/gate/dispatcher never call it and it writes nothing (exit 0 OK / 1 manifest-findings / 2 unreadable-or-invalid-JSON file); read-only:
uv run python foundry.py lint-manifest --file products/<name>/staffing.json  # --bench-dir defaults to the foundry's OWN roles/bench (each named role must have a card there); a nonexistent/unreadable/invalid-JSON --file is exit 2, never raises; needs NO product --config [--json for one machine-readable lint doc: cron/dashboards; same 0/1/2 exit code]
# 31. Run the tri-perspective product gate's DETERMINISTIC pre-checks on a proposal file (item 20 bite 1, the deterministic slice) -- the PROPOSAL-facing sibling of #6 `lint-spec` (spec) and #8 `gate-scope` (diff scope): bounce a proposal FOR FREE, before any model call, if it is missing an impact NUMBER (an impact keyword co-located with a digit on one line), a stated appetite, or a listed alternative, with a default-Kill verdict. The three keyword vocabularies are module-level + patchable (read at call time). DORMANT -- the pipeline/gate/dispatcher never call it and it writes nothing (exit 0 PROCEED / 1 KILL / 2 file-not-found); read-only:
uv run python foundry.py gate-precheck --file products/<name>/proposal.md  # takes a proposal PATH (--file), NOT a product --config, so like `lint-spec` it is dispatched before load_config; a KILL report names the missing checks; a nonexistent --file is exit 2, never raises [--json for one machine-readable gate-precheck doc: release-gate/CI/operator; same 0/1/2 exit code]
# 32. Aggregate the three tri-perspective product-gate seat verdicts into ONE gate verdict (item 20 bite 2) -- the AGGREGATION sibling of #31 `gate-precheck` (deterministic pre-checks): fold the Business / Product / Senior-engineer seats' raw Go/Kill/Recycle votes by precedence KILL > RECYCLE > GO (any KILL kills, else any RECYCLE recycles, else all-GO is a Go), so a proposal advances only on unanimous Go minus any veto -- the gate's default-Kill rule. Verdicts are normalized case-insensitively / whitespace-tolerantly by exact membership against three module-level + patchable token vocabularies (read at call time); an unrecognized or empty seat verdict is KILL. DORMANT -- the pipeline/gate/dispatcher never call it and it writes nothing (exit 0 GO / 1 KILL / 2 RECYCLE); read-only:
uv run python foundry.py gate-verdict --business go --product recycle --engineering go  # takes three raw verdict strings, NOT a product --config, so like `gate-precheck`/`lint-spec` it is dispatched before load_config; prints the normalized seats + killer/recycler rosters ("(none)" when empty) + a final verdict: line; no --file, writes nothing [--json for one machine-readable gate-verdict doc: release-gate/CI/operator; same 0/1/2 exit code]
# 33. Resolve a per-role MODEL-OVERRIDE note into the agent-CLI argv a launcher would use (item 20 bite 3) -- the per-role-model sibling of #31 `gate-precheck` and #32 `gate-verdict`: map a staffing-manifest `model` note (e.g. `opus`) onto the base launcher argv (`AGENT_RUN_ARGS`) with the model args APPENDED via the module-level + patchable `MODEL_ARG_TEMPLATE` (default `("--model", "{model}")`, `{model}` substituted; both read at call time), so the product-gate PM and the release gate can run a DIFFERENT model than the builder (a decorrelated adversarial seat). An empty/whitespace note is passthrough: the base argv is returned byte-identical (the "absent an override, current behavior is unchanged" invariant). DORMANT -- the pipeline/gate/dispatcher never call it and it writes nothing (exit 0 override-applied / 1 passthrough); read-only:
uv run python foundry.py role-model --model opus  # takes an optional --model NOTE, NOT a product --config, so like `gate-verdict`/`lint-spec` it is dispatched before load_config; prints the resolved argv + the applied model + overridden: true|false; omit --model (or pass a whitespace note) for passthrough (exit 1), writes nothing [--json for one machine-readable role-model doc: release-gate/CI/operator; same 0/1 exit code]
# 34. Run the COMPOSITE tri-perspective product gate on a proposal file (item 20 bite 4a) -- the COMPOSITION sibling of #31 `gate-precheck` (deterministic pre-checks) and #32 `gate-verdict` (seat aggregation): fold the two shipped cores in the ORG_DESIGN section-6 ORDER -- run the free deterministic pre-check FIRST and, if it fails (missing impact number / appetite / alternative), bounce the proposal FOR FREE before the three seats are ever consulted (default-Kill), else aggregate the Business / Product / Senior-engineer seat verdicts into the composite Go/Kill/Recycle verdict. A thin read-only wrapper (adds no gate logic beyond decide -> format), it reuses the two cores' call-time-patchable knobs. DORMANT -- the pipeline/gate/dispatcher never call it and it writes nothing (exit 0 GO / 1 KILL / 2 RECYCLE / 3 file-not-found); read-only:
uv run python foundry.py product-gate --file products/<name>/proposal.md --business go --product recycle --engineering go  # takes a proposal PATH (--file) + three raw seat verdicts, NOT a product --config, so like `gate-verdict`/`gate-precheck`/`lint-spec` it is dispatched before load_config; a failing pre-check bounces for free (seats not consulted, verdict KILL); a nonexistent --file is exit 3, never raises; writes nothing [--json for one machine-readable product-gate doc: release-gate/CI/operator; same 0/1/2/3 exit code]
# 35. Classify a file/diff's content for the five RESERVED CEO-escalation categories (item 21, org-design section 9) -- the escalation sibling of #31 `gate-precheck` and #34 `product-gate`: report which of security (credentials/keys), pii (personal data), money (real spending), legal (licensing/IP), or visibility (making something public) a change touches, so a human operator can sign off before anything ships. This GENERALIZES the committed `scripts/leak_guard.py` (section 9's first instance -- PII, enforced at the release gate) to all five categories. Matching is case-insensitive over the full text against five module-level + patchable keyword vocabularies (read at call time); it only REPORTS (no auto-remediation, no unified-diff parsing). DORMANT -- the pipeline/gate/dispatcher never call it and it writes nothing (exit 1 ESCALATE / 0 CLEAR / 2 file-not-found); read-only:
uv run python foundry.py escalation-check --file products/<name>/proposal.md  # takes a file PATH (--file), NOT a product --config, so like `product-gate`/`gate-verdict`/`gate-precheck`/`lint-spec` it is dispatched before load_config; prints the triggered category labels (or (none)) + a verdict: line; ESCALATE is exit 1, CLEAR exit 0, a nonexistent --file exit 2 (never raises); writes nothing [--json for one machine-readable classification doc: release-gate/CI/operator; same 0/1/2 exit code]
# 36. Review the fixed-N no-trigger cadence-review fallback (item 22 bite 1, org-design section 7) -- the bounded-re-staffing sibling of #34 `product-gate` and #35 `escalation-check`: even when no anomaly trigger fires, a quiet loop can silently drift precisely because nothing looked wrong, so after N consecutive quiet iterations the CEO + PM proactively review the project anyway. Given the current quiet-streak `--counter` and whether a trigger fired this iteration (`--trigger-fired`), decide whether the fallback FIRES (REVIEW) and what counter to carry forward (`next_counter`): a real trigger breaks the streak and resets to 0 without firing; else the streak grows by one and fires + resets once `counter + 1` reaches the threshold N (default 5, the module-level + patchable `CADENCE_REVIEW_N` read at call time, or an explicit `--n`). DORMANT -- the pipeline/gate/dispatcher never call it and it writes nothing (exit 1 REVIEW / 0 CONTINUE); read-only:
uv run python foundry.py cadence-review --counter 4  # takes a --counter (and optional --trigger-fired / --n), NOT a product --config, so like `escalation-check`/`product-gate`/`lint-spec` it is dispatched before load_config; prints the counter/trigger_fired/threshold/fires/next_counter figures + a verdict: line; REVIEW is exit 1, CONTINUE exit 0; --trigger-fired always CONTINUEs (resets to 0); writes nothing [--json for one machine-readable cadence decision doc: release-gate/CI/operator; same 0/1 exit code]
# 37. Review a hysteresis-constrained re-staffing DIFF for a JSON review (item 22 bite 2, org-design section 10) -- the bounded-re-staffing sibling of #36 `cadence-review`: team-composition changes are PROPOSALS, not drift, so a review emits a DIFF against `staffing.json` (never editing it) partitioned by three hysteresis rules that prevent thrash -- every change must cite a LOGGED trigger (else rule `trigger`), a `deactivate` needs minimum tenure K before it can be deactivated (else rule `tenure`; an `activate` is never tenure-gated), and at most `cap` changes are ACCEPTED per review in input order (overflow -> rule `cap`; only otherwise-valid changes consume a slot). Given a `--file` JSON review object (keys `changes` / `tenures` role->int / `logged_triggers`, plus optional `k` / `cap` integer overrides -- else the module-level + patchable `RESTAFFING_MIN_TENURE_K` (3) / `RESTAFFING_MAX_CHANGES` (2) read at call time), it partitions the proposed changes into an ACCEPTED diff plus tagged REJECTIONS. DORMANT -- the pipeline/gate/dispatcher never call it and it writes nothing (exit 1 DIFF / 0 NOOP / 2 file-not-found-or-invalid-JSON); read-only:
uv run python foundry.py restaffing-review --file products/<name>/restaffing.json  # takes a JSON review PATH (--file), NOT a product --config, so like `cadence-review`/`escalation-check`/`product-gate`/`lint-spec` it is dispatched before load_config; prints the k/cap/accepted/rejected figures + one line per accepted (+) and rejected (rule) change + a verdict: line; DIFF is exit 1, NOOP exit 0, a nonexistent/invalid --file exit 2 (never raises); writes nothing [--json for one machine-readable re-staffing diff doc: release-gate/CI/operator; same 0/1/2 exit code]
# 38. Plan the dual-PM-scout pre-stage sequence for an iteration (dual-PM-scout feature bite 1, docs/DUAL_PM_SCOUT_SPEC.md) -- the candidate-generation sibling of #36 `cadence-review` and #37 `restaffing-review`: an OPTIONAL two-scout pre-phase that, when enabled, runs `pm_scout_a` (new-capability lens) then `pm_scout_b` (hardening/DX lens) sequentially before the PM lead, which then triages both slates, so every product team gets more diverse candidate features than a single PM produces. Given the `--dual-pm-scouts` flag (and optional repeatable `--lens` overrides -- else the module-level + patchable `PM_SCOUT_LENSES` (new-capability, hardening/DX) read at call time), it computes the ordered plan of `(stage_name, lens)` pairs, stage names assigned by position pm_scout_a/b/c/.... DORMANT -- the pipeline/gate/dispatcher never call it and it writes nothing (exit 1 DUAL / 0 SINGLE); read-only:
uv run python foundry.py scout-plan --dual-pm-scouts  # takes a --dual-pm-scouts flag (and optional repeatable --lens), NOT a product --config or --file, so like `cadence-review`/`restaffing-review`/`escalation-check`/`lint-spec` it is dispatched before load_config; prints the dual_pm_scouts flag + a count figure + one line per scout stage (name + lens) + a verdict: line; DUAL is exit 1, SINGLE exit 0; writes nothing [--json for one machine-readable scout-plan doc: release-gate/CI/operator; same 0/1 exit code]
```

Stop any time: `touch STOP` (whole company) or `touch products/<name>/STOP`
(retire one team). See **[USAGE.md](USAGE.md)** for pointing it at a brand-new
idea or an existing project, and **[CONTINUOUS.md](CONTINUOUS.md)** for the
always-on operating contract (AC power, the single-brain rule, the STOP files).

## Repo map

| Path | What |
|---|---|
| `foundry.py` | Runs ONE product team's loop on any repo (via a JSON config). |
| `dispatcher.py` | The single-brain scheduler across many teams (concurrency 1). |
| `watchdog.py` | A `scheduled`/cron probe that resurrects the dispatcher if its process died and no STOP is set (single-brain + STOP-respecting). |
| `scripts/leak_guard.py` | Committed, portable leak-guard: scan a git tree or file list against a base64-encoded denylist and exit non-zero on any leaked token. Runnable — `python3 scripts/leak_guard.py --ref HEAD` (scans `HEAD` by default) or `--files <path>...`. A standalone script off the pipeline control path (nothing imports it). |
| `scripts/install_hooks.sh` | One-command installer that arms the committed leak-guard as a git `pre-push` hook (git does NOT clone hooks). Idempotent; backs up a foreign existing hook to `pre-push.backup` first. Run `sh scripts/install_hooks.sh` once per fresh clone. A standalone script off the pipeline control path (nothing imports it). |
| `roles/` | The 7 project-agnostic role playbooks (pm, engineer, reviewer, tester, fix, final, reporter). |
| `roles/bench/` | The full role bench: 11 versioned role-cards (mission, trigger, tenure, I/O contract, model note), most dormant. |
| `docs/ORG_DESIGN.md` | The org blueprint: rich bench, lean core, kickoff council, tri-perspective gate, bounded re-staffing. |
| `docs/research/` | Eight sourced research briefs the org design is derived from. |
| `products/<name>/config.json` | One product's wiring (repo, vision, roadmap, quality bar, push target). |
| `foundry.config.example.json` | The dispatcher's work-item list. |
| `tests/` | The framework's own test suite (the platform team's feedback loop). |
| `ARCHITECTURE.md` / `USAGE.md` / `CONTINUOUS.md` | Design, recipes, operating contract. |
| `docs/artifacts.md` | Catalog of products the foundry has produced. |

## Public-safety: arm the leak-guard on a fresh clone

This repo is public and the dispatcher auto-pushes on every ship, so a
committed, portable leak-guard (`scripts/leak_guard.py` + a base64
`scripts/leak_denylist.txt`) scans each pushed commit tree for internal or
personal tokens. Git does **not** clone hooks, so arm it once per checkout with
one command:

```bash
sh scripts/install_hooks.sh   # arms .git/hooks/pre-push to run the committed guard
```

Idempotent (safe to re-run); a foreign existing `pre-push` hook is backed up to
`pre-push.backup` first. The hard in-loop final-gate pre-push check (the `final`
role runs the same guard against the pushed commit, so the loop self-blocks a leaky
ship even without the hook) is now wired into the final gate (roadmap item 16 bite 3,
complete). It is repo-agnostic (skipped for a product repo that does not carry the
guard) and fails closed to the revert path on any non-zero exit.

## Requirements

- An agent CLI on PATH, configured via `FOUNDRY_AGENT_BIN` / `FOUNDRY_AGENT_ARGS`.
- `uv` (Python ≥3.12). No runtime dependencies; `pytest` for the framework's own tests.
- **AC power** for unattended runs (battery maintenance-sleep kills long loops).

## Status

v0.1 — extracted and generalized from the `repolens` build (10 iterations, 9
features shipped overnight, 590 tests, one deadline-triggered auto-revert).
The platform team now improves the foundry itself; see `PLATFORM_ROADMAP.md`.
