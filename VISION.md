# agent-foundry — vision (fixed intent; the platform team stays inside this)

**What it is:** a reusable, always-on autonomous product organization. You point
it at any git repo and a team of fresh single-shot AI agents (PM, engineer,
reviewer, isolated tester, release gate) builds it feature by feature, shipping
only work that passes every gate, indefinitely, until told to stop.

**Who it's for:** a solo builder who wants a "startup in a box" — to turn a
loosely-defined idea or a weekly-defined goal into continuously shipped software
without babysitting each step.

**The single job:** reliably convert *intent* (a VISION + a repo) into *shipped,
tested increments*, safely and unattended.

**Quality bar for the framework itself:**
- Repo-agnostic: no product-specific assumptions baked into `foundry.py`,
  `dispatcher.py`, or `roles/`. Everything specific lives in a product config.
- The five invariants in ARCHITECTURE.md are inviolable (output-file success,
  independent pessimistic gate, tester isolation, anti-delegation, resilience).
- Safe by construction: sandboxed autonomy, production behind a human/gate;
  never force-push; never touch credentials.
- Its own tests stay green; `foundry.py`/`dispatcher.py` stay importable.

**Hard constraints:**
- Single-brain: one foundry per model-API account (dispatcher serializes teams).
- macOS + an agent CLI + uv; AC power for unattended runs.
- Small, reversible increments only — the framework must never break its own
  resume/restart semantics.

**Out of scope (for now):** multi-machine distribution, alternative agent backends,
a hosted service, and any product-specific logic.
