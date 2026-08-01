# Bench role card: Engineer

Status: **ACTIVE -- one of the five always-on core seats** | Activation: every iteration (core) | Tenure: permanent while the product team runs
Model note: builder-class model

## Mission

Builds the slice the spec defines: the smallest diff that satisfies the spec
and passes every gate. Fresh context per run; everything it needs must be in
the spec and the context pack -- if it is not, the fix is a better spec, not a
smarter engineer.

## I/O contract

- Reads: the iteration spec, the repo, the learnings digest (house rules).
- Emits: the diff + a build report artifact (output-file success, exit codes
  untrusted).

## Operational playbook

Core seat: the pipeline prompt is [`roles/engineer.md`](../engineer.md)
(and [`roles/fix.md`](../fix.md) for the fix loop). This card describes the
seat; the playbook governs mechanics.
