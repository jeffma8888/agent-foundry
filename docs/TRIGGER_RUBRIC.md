# Trigger rubric: product trait -> bench role

This rubric is the kickoff council's mechanical, auditable staffing aid. It maps
an observable product trait to the bench role that trait activates, so a product
is staffed by rule rather than by vibes (see `docs/ORG_DESIGN.md` section 5).

The always-on core -- Product agent, Engineer, Reviewer, isolated Tester,
Release Gate -- runs on every iteration regardless of any trait. The rows below
cover only the *trigger-activated* specialists: each one stays dormant (a card
is just a file) until its trait predicate is true for the product, at which
point the kickoff council lists it in the product's `staffing.json` and it does
one bounded pass before going dormant again.

## How to read a row

For each row: if the trait predicate is TRUE for the product, activate the named
bench role in the staffing manifest at its declared point. If FALSE, the role
stays dormant and writes nothing. The predicate is meant to be decided
mechanically -- a yes/no a reviewer can check against the diff or the spec, not
a judgment call.

## Mappings

| Product trait (predicate) | Activation condition | Bench role | Bench card |
|---|---|---|---|
| Ships or changes a human-facing surface | a UI, CLI UX, or output-format change is in the diff | Designer | `roles/bench/designer.md` |
| Touches user data, licensing, IP, or terms | the diff reads or stores user data, adds a dependency, or changes a license or terms file | Legal | `roles/bench/legal.md` |
| Changes a public API, onboarding path, or README-level contract | a public entry point, quickstart, or README contract changes | DevRel / Docs | `roles/bench/devrel_docs.md` |
| Cross-cutting changes across N or more modules at once | the dependency count of in-flight cross-module changes reaches the threshold | TPM | `roles/bench/tpm.md` |

Each activation condition mirrors the `Activation:` line on the named bench card;
the card is the source of truth for the trigger, this table is the index.

## Extending the rubric

The bench is a registry, not a closed list (ORG_DESIGN section 3.1). To cover a
new trait -- say a security-sensitive surface or a latency-critical path -- mint
a new bench card in `roles/bench/` (mission, activation trigger, tenure, I/O
contract, model note) and add one row here mapping the trait to it. A row is
valid only when its bench card exists, so the rubric never points at a role the
org cannot actually run.

## Not yet wired to the runtime

This rubric guides the kickoff council's staffing decision, which is recorded in
`products/<name>/staffing.json`. The running pipeline does not consult the
manifest yet -- that is roadmap item 19 (the manifest-driven pipeline). Until
then the fixed five-seat core is the behavior of record.

## Worked example: repolens

repolens is an offline CLI with no stored user data and a documented public
command surface. Applying the rubric: the DevRel / Docs trait fires (it ships a
public CLI plus a README quickstart); Designer fires on any CLI-UX or
output-format change; Legal and TPM stay dormant (no user data, single-module
changes). Its example manifest lives at `products/repolens/staffing.json`.
