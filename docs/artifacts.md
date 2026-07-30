# Artifacts the foundry has produced

A running catalog of products built by agent-foundry teams.

## 1. repolens — repo-analysis CLI  *(flagship, first artifact)*

- **Repo:** https://github.com/jeffma8888/repolens
- **What:** an offline-first CLI that x-rays any codebase into human-readable
  briefings — layout, file tree, line counts, entry points, dependencies
  (incl. PEP 735 groups), test posture, and a composite `arch` brief.
- **Built by:** the product pipeline over 10 iterations in one overnight run,
  before the framework was generalized into this repo.
- **Result:** 9 features shipped to `main`, 0→590 passing tests, 3 engineer
  timeouts absorbed by retry/backoff, and one deadline-triggered auto-revert
  (iteration 10) — the gate refusing to ship is the system working.
- **Config here:** `products/repolens/config.json`.

_When the dispatcher builds more, add them here (name, repo, what, result)._
