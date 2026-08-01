# Bench role card: Product Manager (the product agent)

Status: **ACTIVE -- one of the five always-on core seats** | Activation: every iteration (core) | Tenure: permanent while the product team runs
Model note: builder-class model

## Mission

The merged "why + what" seat: owns the spec, goals/non-goals, and the smallest
shippable slice for each iteration. Deliberately one seat, not a PM/PO split --
splitting why from what re-creates the misalignment seam the lean-core rule
exists to avoid (see docs/research/pm-vs-tpm-vs-po.md).

## I/O contract

- Reads: product vision, roadmap, learnings digest, ship ledger.
- Emits: the iteration spec (`pm.md`) -- passed through `lint-spec` before any
  engineering run.

## Operational playbook

This is a core seat: the prompt the pipeline actually runs is
[`roles/pm.md`](../pm.md). This card describes the seat; the playbook governs
mechanics.
