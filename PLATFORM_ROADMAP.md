# Platform Roadmap — how the foundry improves itself

The `_platform` team (highest dispatcher priority) works this list one small,
reversible increment per iteration, keeping `tests/` green. Seeded from the
`ralph` and `ai-brownfield-practices` skills and the repolens build. The PM
re-orders by value each iteration; ship-order is a suggestion, not a contract.

| # | Increment | Why | Done when |
|---|---|---|---|
| 1 | `prd.json`-style machine roadmap per product (id/title/criteria/passes) | Deterministic global stop + progress, vs parsing prose | dispatcher can report "N/M stories pass" via a jq-able file |
| 2 | Consolidate LEARNINGS into a pinned `## Patterns` head section | Iteration agents can't read an ever-growing log; promote general rules | reporter/roles maintain a bounded top section |
| 3 | Emit an `AGENTS.md` into each product repo from its learnings | Fresh agents auto-read house rules; less re-learning | product repo has an up-to-date AGENTS.md |
| 4 | Risk-split the final gate (test-only diff = light gate) | Cut gate latency ~half for coverage-only iterations | gate detects "no src/ change" and runs the light path |
| 5 | Task-size guard: PM must confirm a feature fits <50% context | The 3 engineer timeouts on repolens were oversized-iteration smells | PM spec includes a size self-check field |
| 6 | Mutation-testing gate (mutmut) as a deterministic weak-assertion check | Agents emit assertions that pass without validating behavior | gate can optionally run mutation testing |
| 7 | Per-iteration suite wall-time in the log + auto-parallelize story when slow | Throughput is dominated by verify time, not reasoning | NIGHT_LOG records suite seconds; PM files a speed story past a threshold |
| 8 | `scheduled` watchdog that relaunches the dispatcher if PID gone & no STOP | Survive reboots / crashes truly 24/7 | a documented, tested watchdog exists |
| 9 | `foundry.py doctor` preflight (AC power, agent auth, uv, remote reachable) | Fail fast before burning a shift on a broken env | `doctor` subcommand returns actionable checks — **[shipping iter 01]** |
| 10 | Structured JSON event log alongside the markdown NIGHT_LOG | Machine-readable status for dashboards / the reporter | events.jsonl written per stage |
| 11 | **Post-release verification gate** (fresh-clone) + conventional revertable commit contract | The final gate checks the working TREE, never a clean-room checkout — this misses uncommitted files, lockfile drift, and dev-tree import leakage. For a project whose PRIMARY goal is trustworthy continuous release/deployment, a green working tree is not proof the release is deployable | a `postrelease` stage runs on every ship, clones `origin/<branch>` fresh, re-verifies, emits `POSTRELEASE: HEALTHY\|BROKEN`, and a BROKEN result raises a per-product hotfix flag the next PM must clear (see detailed spec below) — ✅ **SHIPPED (iter 02 bite 1/2 = config fields + dormant verify helper, `0fc54c1`; iter 03 bite 2/2 = wiring + `POSTRELEASE:` sentinel + hotfix-flag lifecycle + commit contract)** |

## Ship order (PM re-orders by value each iteration)
- **iter 01 = item 9 (`foundry doctor`).** Re-ordered ahead of item 1 for the first increment: it is purely additive (a new CLI subcommand + pure helpers), touches none of the running-loop semantics (no change to iteration numbering, state layout, or the sentinel contract), and directly attacks the top unattended-run failure mode (shifts dying on battery / missing `uv`/`agent` / unreachable remote). Establishes the safe, offline-testable increment pattern.
- Item 1 (`prd.json` machine roadmap) remains high value but is larger and touches dispatcher reporting; deferred to a later iteration after the additive-increment pattern is proven.
- Item 11 (post-release fresh-clone verification gate) was appended by a sibling factory and is arguably the most on-mission item, but it is a MULTI-iteration effort: it adds a new pipeline stage, a new `POSTRELEASE:` sentinel, and modifies `run_iteration` control flow. Per the size bar it must be SPLIT (e.g. config fields + fresh-clone verify helper first, then wiring + hotfix flag) and, per the self-mod guardrails, deferred behind a flag while a loop is in flight. Strong candidate for iter 02–04; not a safe first bite.
- **iter 02 = item 11, bite 1 of 2 (SPLIT as instructed above).** This bite is the purely-additive, offline-testable half: three backward-compatible `ProductConfig` fields (`postrelease_enabled`, `setup_cmd`, `smoke_cmd`) plus a dormant, fully unit-tested fresh-clone verification helper (`verify_fresh_clone` + the pure `postrelease_verdict` / `sha_matches` decision functions + a single `run_cmd` I/O seam). Nothing calls the helper from `run_iteration`/`run_continuous` yet, so it changes NO running-loop semantics (iteration numbering, state layout, `VERDICT:`/`RESULT:`/`ACTION:` sentinels all untouched) — resume-safe for a live loop, same additive pattern iter 01 proved.
- **iter 03 = item 11, bite 2 of 2 (DONE — completes item 11).** The running-loop-touching half: wired `verify_fresh_clone` into `run_iteration` after the `ACTION: PUSHED` ship branch as a DETERMINISTIC inline step `postrelease_step` (NOT an LLM agent role — bite 1 already built the mechanical verify, and the product quality bar demands deterministic + offline-testable), emit the new `POSTRELEASE: HEALTHY|BROKEN` sentinel to `state/iter-NN/postrelease.md`, create/clear the per-product `HOTFIX_NEEDED.md` flag (write on BROKEN, clear on genuine HEALTHY, untouched on infra-skip/disabled), formalize the revertable single-commit-message contract in `roles/final.md`, add the hotfix-first first-duty to `roles/pm.md`, and add the ARCHITECTURE.md §2 stage row + §3 gate-invariant extension. Resume-safe: purely additive to the post-push branch, gated by `postrelease_enabled` (default True), BROKEN never reverts and keeps `status==shipped` (fixed forward next iteration), and a long-lived `run_continuous` process only picks up the change on a clean restart — so it can never corrupt an in-flight iteration.

### Migration note (per §6 self-mod guardrail) — iter 03
- **New sentinel introduced:** `POSTRELEASE: HEALTHY|BROKEN`, written to `products/<name>/state/iter-NN/postrelease.md` (last non-empty line). It does NOT participate in loop control flow — `run_iteration`/`run_continuous` branch only on `VERDICT:`/`RESULT:`/`ACTION:` and the `res["status"]` value; `POSTRELEASE:` is diagnostic and carried as an additive `res["postrelease"]` key.
- **New per-product artifact:** `products/<name>/HOTFIX_NEEDED.md` — a BROKEN post-release raises it (with the sha + evidence); a genuine-HEALTHY later ship clears it; the next PM must clear it before any new feature (now stated in `roles/pm.md`).
- **Unchanged:** iteration numbering, `state/iter-NN` layout, the `VERDICT:`/`RESULT:`/`ACTION:` sentinel strings, `run`/`once`/`doctor` CLI, and the `run_continuous` status branches {shipped, no-ship, infra-fail, stopped}.

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
