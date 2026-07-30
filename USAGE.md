# Usage — pointing the foundry at work

Three recipes. All you ever write by hand is a `VISION.md` and a `config.json`;
the PM writes the roadmap on iteration 1 and the teams do the rest.

## Recipe A — build a brand-new product from an idea

```bash
# 1. Make the product repo (private first — trial-and-error freedom).
mkdir -p ~/projects/mytool && cd ~/projects/mytool
git init -b main
gh repo create mytool --private --source=. --remote=origin
# 2. Write the fixed intent. Keep it short; it is the guardrail, not the plan.
cat > VISION.md <<'V'
# mytool — <one-line what it is>
<2-4 sentences: who it's for, the single job it does, the quality bar,
 and any hard constraints (offline-only? deterministic? language?).>
V
git add -A && git commit -m "chore: seed vision" && git push -u origin main

# 3. Wire it into the foundry.
cd ~/projects/agent-foundry
cp products/repolens/config.json products/mytool/config.json
#   edit: name, repo, allowed_push_repo, vision, roadmap, quality_ref,
#         quality_bar, test_cmd  (see products/repolens/config.json as a model)

# 4. Run it.
uv run python foundry.py run --config products/mytool/config.json
```

The PM creates `PRODUCT.md` (the roadmap) on iteration 1 from your VISION, then
picks one small feature per iteration forever.

## Recipe B — improve an existing project

Same as A, but skip repo creation and set `repo` to the existing checkout. Two
cautions for brownfield code (see the `ai-brownfield-practices` skill):

- **Feedback loops first.** If the test suite is slow or thin, the teams are
  blind. Give the PM an early roadmap item to speed the suite and/or generate
  tests from real usage before piling on features. Set `test_cmd` to the
  project's actual fast check.
- **Steering.** Point `quality_ref` at a sibling repo whose conventions you
  want mirrored, and put hard constraints in `quality_bar`. Consider adding an
  `AGENTS.md` to the product repo so every fresh agent auto-reads the house rules.

## Recipe C — run the whole company continuously (recommended)

```bash
cd ~/projects/agent-foundry
cp foundry.config.example.json foundry.config.json
#   enable/disable teams, set priority (lower = earlier each round).
uv run python dispatcher.py --config foundry.config.json
```

The dispatcher runs the platform team (improves the foundry) and every enabled
product team, one iteration at a time, until you `touch STOP`. This is the
quota-safe way to have more than one team "always on."

## Invoking from your agent, in plain language

Once this repo exists you can just say things like:

- *"Use the foundry to build a new CLI that does X"* → follow Recipe A.
- *"Use the foundry to keep improving <existing repo>"* → Recipe B.
- *"Run the foundry"* / *"keep the company running"* → Recipe C (launch the
  dispatcher as one backgrounded task; see CONTINUOUS.md).
- *"Stop the foundry"* → `touch STOP`.

## Controls cheat-sheet

| Want | Do |
|---|---|
| Stop everything | `touch ~/projects/agent-foundry/STOP` |
| Retire one team | `touch ~/projects/agent-foundry/products/<name>/STOP` |
| One iteration only | `foundry.py once --config <cfg>` |
| Dry-run (no push) | set `"push_enabled": false` in the product config |
| See a team's status | `cat products/<name>/STATUS_REPORT.md` |
| See what shipped | `git -C <product repo> log --oneline` |
| See the shift log | `cat DISPATCH_LOG.md` |
