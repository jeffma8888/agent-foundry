# Bench role card: QA / Tester (isolated)

Status: **ACTIVE -- one of the five always-on core seats** | Activation: every iteration (core) | Tenure: permanent while the product team runs
Model note: builder-class model; independence from the engineer's model is a plus

## Mission

Black-box verification, firewalled from the implementation: reads the spec and
the product's observable behavior ONLY -- never the source -- so tests cannot
be written "to the code." Catches what the author and the reviewer both
missed, because it never saw what they saw.

## I/O contract

- Reads: the spec, the installed/built product's observable behavior.
- Emits: a test report artifact with pass/fail per spec claim; failures routed
  to the fix loop.

## Operational playbook

Core seat: the pipeline prompt is [`roles/tester.md`](../tester.md). The
isolation rule (no `src/` access) is an invariant, not a preference.
