# Platform Roadmap — how the foundry improves itself

The `_platform` team (highest dispatcher priority) works this list one small,
reversible increment per iteration, keeping `tests/` green. Seeded from the
`ralph` and `ai-brownfield-practices` skills and the repolens build. The PM
re-orders by value each iteration; ship-order is a suggestion, not a contract.

| # | Increment | Why | Done when |
|---|---|---|---|
| 1 | `prd.json`-style machine roadmap per product (id/title/criteria/passes) | Deterministic global stop + progress, vs parsing prose | dispatcher can report "N/M stories pass" via a jq-able file |
| 2 | Consolidate LEARNINGS into a pinned `## Patterns` head section | Iteration agents can't read an ever-growing log; promote general rules | reporter/roles maintain a bounded top section — **[shipping iter 07, bite 1/2 = `learnings_digest` helper + `foundry learnings` CLI + curated `## Patterns` head; iter 08, bite 2/2 = digest inlined into `build_prompt` so every stage prompt carries the bounded head + N recent lessons → COMPLETES item 2]** |
| 3 | Emit an `AGENTS.md` into each product repo from its learnings | Fresh agents auto-read house rules; less re-learning | product repo has an up-to-date AGENTS.md — **[shipping iter 09, bite 1/2 = pure `render_agents_md` helper + on-demand `foundry agents` CLI; bite 2 (future) = auto-refresh AGENTS.md at ship time]** |
| 4 | Risk-split the final gate (test-only diff = light gate) | Cut gate latency ~half for coverage-only iterations | gate detects "no src/ change" and runs the light path |
| 5 | Task-size guard: PM must confirm a feature fits <50% context | The 3 engineer timeouts on repolens were oversized-iteration smells | PM spec includes a size self-check field — **[shipping iter 10 = pure `spec_lint` helper + on-demand `foundry lint-spec --file` CLI + `## Size self-check` made a REQUIRED section in `roles/pm.md` → COMPLETES item 5]** |
| 6 | Mutation-testing gate (mutmut) as a deterministic weak-assertion check | Agents emit assertions that pass without validating behavior | gate can optionally run mutation testing |
| 7 | Per-iteration suite wall-time in the log + auto-parallelize story when slow | Throughput is dominated by verify time, not reasoning | NIGHT_LOG records suite seconds; PM files a speed story past a threshold |
| 8 | `scheduled` watchdog that relaunches the dispatcher if PID gone & no STOP | Survive reboots / crashes truly 24/7 | a documented, tested watchdog exists — **[shipping iter 06]** |
| 9 | `foundry.py doctor` preflight (AC power, agent CLI, uv, remote reachable) | Fail fast before burning a shift on a broken env | `doctor` subcommand returns actionable checks — **[shipping iter 01]** |
| 10 | Structured JSON event log alongside the markdown NIGHT_LOG | Machine-readable status for dashboards / the reporter | events.jsonl written per stage — **[shipping iter 05]** (retry; iter 04 was reverted by an external public-release STOP, not a feature defect) |
| 11 | **Post-release verification gate** (fresh-clone) + conventional revertable commit contract | The final gate checks the working TREE, never a clean-room checkout — this misses uncommitted files, lockfile drift, and dev-tree import leakage. For a project whose PRIMARY goal is trustworthy continuous release/deployment, a green working tree is not proof the release is deployable | a `postrelease` stage runs on every ship, clones `origin/<branch>` fresh, re-verifies, emits `POSTRELEASE: HEALTHY\|BROKEN`, and a BROKEN result raises a per-product hotfix flag the next PM must clear (see detailed spec below) — ✅ **SHIPPED (iter 02 bite 1/2 = config fields + dormant verify helper, `0fc54c1`; iter 03 bite 2/2 = wiring + `POSTRELEASE:` sentinel + hotfix-flag lifecycle + commit contract)** |

## Ship order (PM re-orders by value each iteration)
- **iter 01 = item 9 (`foundry doctor`).** Re-ordered ahead of item 1 for the first increment: it is purely additive (a new CLI subcommand + pure helpers), touches none of the running-loop semantics (no change to iteration numbering, state layout, or the sentinel contract), and directly attacks the top unattended-run failure mode (shifts dying on battery / missing `uv` / agent CLI / unreachable remote). Establishes the safe, offline-testable increment pattern.
- Item 1 (`prd.json` machine roadmap) remains high value but is larger and touches dispatcher reporting; deferred to a later iteration after the additive-increment pattern is proven.
- Item 11 (post-release fresh-clone verification gate) was appended by a sibling factory and is arguably the most on-mission item, but it is a MULTI-iteration effort: it adds a new pipeline stage, a new `POSTRELEASE:` sentinel, and modifies `run_iteration` control flow. Per the size bar it must be SPLIT (e.g. config fields + fresh-clone verify helper first, then wiring + hotfix flag) and, per the self-mod guardrails, deferred behind a flag while a loop is in flight. Strong candidate for iter 02–04; not a safe first bite.
- **iter 02 = item 11, bite 1 of 2 (SPLIT as instructed above).** This bite is the purely-additive, offline-testable half: three backward-compatible `ProductConfig` fields (`postrelease_enabled`, `setup_cmd`, `smoke_cmd`) plus a dormant, fully unit-tested fresh-clone verification helper (`verify_fresh_clone` + the pure `postrelease_verdict` / `sha_matches` decision functions + a single `run_cmd` I/O seam). Nothing calls the helper from `run_iteration`/`run_continuous` yet, so it changes NO running-loop semantics (iteration numbering, state layout, `VERDICT:`/`RESULT:`/`ACTION:` sentinels all untouched) — resume-safe for a live loop, same additive pattern iter 01 proved.
- **iter 03 = item 11, bite 2 of 2 (DONE — completes item 11).** The running-loop-touching half: wired `verify_fresh_clone` into `run_iteration` after the `ACTION: PUSHED` ship branch as a DETERMINISTIC inline step `postrelease_step` (NOT an LLM agent role — bite 1 already built the mechanical verify, and the product quality bar demands deterministic + offline-testable), emit the new `POSTRELEASE: HEALTHY|BROKEN` sentinel to `state/iter-NN/postrelease.md`, create/clear the per-product `HOTFIX_NEEDED.md` flag (write on BROKEN, clear on genuine HEALTHY, untouched on infra-skip/disabled), formalize the revertable single-commit-message contract in `roles/final.md`, add the hotfix-first first-duty to `roles/pm.md`, and add the ARCHITECTURE.md §2 stage row + §3 gate-invariant extension. Resume-safe: purely additive to the post-push branch, gated by `postrelease_enabled` (default True), BROKEN never reverts and keeps `status==shipped` (fixed forward next iteration), and a long-lived `run_continuous` process only picks up the change on a clean restart — so it can never corrupt an in-flight iteration.
- **iter 05 = item 10 (structured JSON event log `events.jsonl`) — RETRY.** First built in iter 04; that iteration completed engineering but was ABANDONED/reverted at the reviewer boundary when an external public-release-scrubbing STOP landed two chore commits (`5505ad0`, `a75099e`) on `main` — a process interruption, NOT a feature defect (nothing failed review). Re-picked as the smallest SAFE additive increment still on the list: a brand-new per-product file (`events.jsonl`) written best-effort inside the single `log()` choke function, OFF the control path, introducing NO new sentinel and changing NONE of iteration numbering / `state/iter-NN` layout / the `VERDICT:`/`RESULT:`/`ACTION:`/`POSTRELEASE:` contract — resume-safe for a live loop (a running `run_continuous` holds the old `log()` in memory; the change activates only on a clean restart, then just appends to a fresh file). Reuses iter 04's validated design + engineer lessons (tz-aware ISO `ts`, reserved-key insertion order, `json.dumps(default=str)`, durable-write-first best-effort mirror). Deferred over items 1-8: items 1 (`prd.json`) and 4 (risk-split gate) touch dispatcher/gate control flow; items 2 (Patterns head) and 5 (size guard) are useful but lower product value than the machine-readable observability the VISION's unattended-run goal needs. NO migration note required (no sentinel / control-flow change); ARCHITECTURE.md §5 gains a one-line note on the new artifact.

- **iter 06 = item 8 (`scheduled` watchdog to resurrect the dispatcher).** Re-ordered to the front of the remaining list on value×safety×size. It is the SAFEST class of increment left: a brand-new standalone module (`watchdog.py`) that NOTHING imports, so it cannot regress a running loop, the dispatcher, `foundry.py`, or any invariant — even safer than iter 05's in-`foundry.py` helper. It is squarely on-mission (VISION: always-on "indefinitely, until told to stop"; ARCHITECTURE §3 Resilience has a real gap — nothing resurrects the dispatcher process after a crash/kill/restart) and the product's own CONTINUOUS.md already prescribes the exact design (lines 41-42 + the line-57 `pgrep -f dispatcher.py` liveness probe). Its two safety-critical guards — single-brain (never launch a second dispatcher) and STOP-respect (never resurrect a deliberately-stopped company) — are a pure decision function pinned by a black-box truth table; all I/O sits behind monkeypatchable seams, so it stays fully offline/deterministic-testable. Detection is a `pgrep`-style process scan (no PID-file), so `dispatcher.py`/`foundry.py` are NOT edited → purely additive, zero control-flow/sentinel/numbering/layout change → **NO migration note required** (a new standalone module is off the control path entirely). Deferred over the rest: items 1 (`prd.json`) and 4 (risk-split gate) touch dispatcher/gate control flow; item 6 (mutation testing) needs a network install and isn't offline-deterministic; items 2/5/7 are lower immediate product value than closing the 24/7-survival gap. **Next-highest value after this: item 2 (bound the ever-growing `LEARNINGS.md` into a pinned `## Patterns` head)** — at ~42KB it is now a live per-iteration context-budget drain for every fresh agent that reads it.

- **iter 07 = item 2, bite 1 of 2 (SPLIT — the pre-declared next-highest-value item).** Bounding the ~49KB `LEARNINGS.md` context drain. Split into an additive bite now + a wiring bite later, mirroring the endorsed item-11 split (iter 02 dormant helper → iter 03 wiring). **Bite 1 (this iter):** a PURE, offline-testable `learnings_digest(text, recent=12)` helper (pinned `## Patterns` head verbatim + only the N most-recent role-tagged lessons) + a `foundry learnings --config <cfg> [--recent N]` CLI that renders it + restructuring the live (gitignored) `_platform/LEARNINGS.md` into a `## Patterns` head (seeded with ~10 curated durable rules) over a `## Chronological lessons` tail + a one-line pm.md pointer at the head. It touches ZERO control flow (`build_prompt`/`run_iteration`/`run_continuous`/`run_stage` untouched), adds NO sentinel, and changes nothing about iteration numbering / `state/iter-NN` layout / the `VERDICT:`/`RESULT:`/`ACTION:`/`POSTRELEASE:` contract → **NO migration note required**; a live loop is unaffected (old code in memory; CLI is purely additive on a clean restart). **Bite 2 (future):** wire `learnings_digest` into `build_prompt` so every stage receives the bounded digest inline. Deferred over items 1 (`prd.json`) and 4 (risk-split gate), which touch dispatcher/gate control flow, and item 6 (mutation testing), which needs a network install and isn't offline-deterministic; higher value than items 3/5/7 because the context drain hits EVERY agent EVERY iteration. **Next-highest after this: item 2 bite 2 (wire the digest into `build_prompt`)**, then item 3 (emit `AGENTS.md` per product repo).

- **iter 08 = item 2, bite 2 of 2 (DONE — completes item 2).** The wiring bite the iter-07 split pre-declared. `learnings_digest` is now inlined into `build_prompt`, so EVERY stage prompt of EVERY iteration carries the bounded digest (pinned `## Patterns` head + the `PROMPT_LEARNINGS_RECENT` most-recent lessons) directly — a fresh agent gets high-signal history inline instead of reading the ~49 KB `LEARNINGS.md` off disk (or running `foundry learnings`). `build_prompt` reads `cfg.learnings` DEFENSIVELY (missing/unreadable → placeholder digest, never crashes the pipeline) and reads the `PROMPT_LEARNINGS_RECENT` bound at call time (patchable). Purely ADDITIVE to the prompt STRING: the append-path line is KEPT (agents still need the path to append their own lesson), no signature change, `run_iteration`/`run_continuous`/`run_stage` untouched → NO new sentinel; iteration numbering, `state/iter-NN` layout, and the `VERDICT:`/`RESULT:`/`ACTION:`/`POSTRELEASE:` contract all unchanged → **NO migration note required**. Resume-safe: a live loop holds the old `build_prompt` in memory; the change activates only on a clean restart. **Next-highest after this: item 3 (emit an up-to-date `AGENTS.md` into each product repo from its learnings)** — additive, offline-testable, on-mission (fresh agents auto-read house rules), and the pre-declared successor.

- **iter 09 = item 3, bite 1 of 2 (SPLIT — the pre-declared next-highest-value item).** Emitting an `AGENTS.md` house-rules file into a product repo from its learnings. Split like the endorsed item-11 (iter 02→03) and item-2 (iter 07→08) splits: an additive-mechanism bite now + a wiring bite later. **Bite 1 (this iter):** a PURE `render_agents_md(learnings_text, product_name, recent=12) -> str` helper (an auto-generated banner + the bounded `learnings_digest` embedded verbatim, so the house rules ARE the pinned `## Patterns` head + the N most-recent lessons) + a new on-demand `foundry agents --config <cfg> [--recent N] [--print]` CLI (`agents_cli`) that writes `<cfg.repo>/AGENTS.md` (or prints it). Same class as the shipped `foundry doctor` (iter 01) and `foundry learnings` (iter 07) subcommands: purely additive, offline-testable, and the pipeline NEVER calls it, so `build_prompt`/`run_iteration`/`run_continuous`/`run_stage` are untouched, NO sentinel is added, and iteration numbering / `state/iter-NN` layout / the `VERDICT:`/`RESULT:`/`ACTION:`/`POSTRELEASE:` contract are unchanged → **NO migration note required**; a live loop is unaffected (old code in memory; the subcommand exists only on a clean restart). It is NOT run inside this iteration's pipeline — invoking it would write `AGENTS.md` into the repo root (`cfg.repo` IS the foundry repo for `_platform`) and dirty the ship diff, so it stays on-demand and the ship diff remains exactly {foundry.py, README.md, roadmap edit, new test file}. **Bite 2 (future):** auto-refresh `<repo>/AGENTS.md` at ship time (final gate / post-release) so it stays current on every ship — that half touches control flow AND makes `AGENTS.md` a tracked, gate-committed file, so it earns its own iteration + migration note. Deferred over items 1 (`prd.json`) and 4 (risk-split gate), which touch dispatcher/gate control flow, and item 6 (mutation testing), which needs a network install and isn't offline-deterministic. **Next-highest after this: item 3 bite 2 (wire the AGENTS.md auto-refresh into the ship path)**, then item 5 (PM task-size self-check field — already practiced informally in recent specs) or item 4 (risk-split the final gate for test-only diffs).

- **iter 10 = item 5 (Task-size guard) — DONE, COMPLETES item 5.** The roadmap's own pre-declared alternative-next after item 3 bite 2 — chosen OVER item 3 bite 2 on safety: bite 2 auto-commits an `AGENTS.md` into the PUBLIC foundry repo on every ship (touches the final-gate/ship path AND makes `AGENTS.md` a tracked, gate-committed file), which iter-09's PM explicitly flagged as an operator decision, not a safe autonomous increment. Item 5's mechanism is naturally small and fully additive, so NO split was needed: a PURE `spec_lint(spec_text) -> SpecLint` scorer (required-section presence + char count + `## Expected Behaviors` count, verdict `OK`/`REVIEW` against patchable module thresholds `REQUIRED_SPEC_SECTIONS`/`SPEC_SIZE_WARN_CHARS`/`SPEC_MAX_BEHAVIORS`) + a new on-demand `foundry lint-spec --file <path>` CLI (`lint_spec_cli`, exit 0 ok / 1 incomplete-or-oversized / 2 file-not-found, writes nothing) + formalizing `## Size self-check` as a REQUIRED PM spec section in `roles/pm.md` (the item's literal 'done when'). Same purely-additive class as the shipped `foundry doctor` (iter 01), `foundry learnings` (iter 07), and `foundry agents` (iter 09) subcommands: the pipeline NEVER calls it, so `build_prompt`/`run_iteration`/`run_continuous`/`run_stage` are untouched, NO sentinel is added, and iteration numbering / `state/iter-NN` layout / the `VERDICT:`/`RESULT:`/`ACTION:`/`POSTRELEASE:` contract are unchanged → **NO migration note required**; a live loop is unaffected (old code in memory; the subcommand exists only on a clean restart). Directly attacks the foundry's #1 reliability failure mode (oversized iterations → engineer-stage timeouts, the repolens smell) with an OBJECTIVE, deterministic pre-flight guard instead of prose-only self-assessment. Ship diff = {`foundry.py`, `roles/pm.md`, `README.md`, roadmap edit, new `tests/test_iter10_behavior.py`}. **Deferred/next-highest after this:** item 3 bite 2 (auto-refresh `AGENTS.md` at ship time — gate-committed tracked file, earns operator sign-off + its own iteration + migration note), then item 4 (risk-split the final gate for test-only diffs) or item 1 (`prd.json` machine roadmap); item 6 (mutation testing) still deferred as it needs a network install and isn't offline-deterministic.

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
