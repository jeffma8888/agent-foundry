# FINAL -- iteration 164 (ships as `factory iter 170`)

Feature under gate: `pla signals --fail-on-kind K` now **fails closed** when the collector that
owns an armed kind degraded mid-scan -- exit **1** with one `error: ` line naming the degraded
collector's registry name and the armed kind, instead of a green `0` over signals it never got to
see. Diff: `src/proactive_loop/cli.py`, `src/proactive_loop/collectors/base.py`, README reference
sections, `ROADMAP.md`, `DIRECTIONS.md`, plus the tester's new
`tests/test_iter170_behavior.py`.

## Gate checklist

1. **Reviewer verdict: APPROVE**, `reviewer.md:131`. BLOCKING: 0, NIT: 5 (second absorption site
   in `cli.py:1713-1731` unreachable for all 17 shipped collectors; `--fail-over` stays
   degradation-blind; the `--collector X --fail-on-kind Y` sibling false-green; `record_degradations`
   not on the package facade; behavior-5 ordering discards the blindspot). No BLOCKING item to
   re-verify.
2. **Tester result: PASS**, and WHICH report is authoritative was decided by the module, not by
   hand: `foundry.read_authoritative_tester_result(iter-164)` -> `PASS`, over
   `authoritative_tester_report(['tester.md'])` -> `tester.md`. Note `tester.attempt1.log` is the
   48-byte `agent run timed out after 600s` signature -- the stage was cap-killed AFTER writing a
   complete report, which is the checkpoint-first contract working as designed.
3. **Quality check: GREEN, but only after a fix pass I had to make at this gate.** See below.
4. `git status` showed only intended changes (5 modified tracked files + the new test module);
   no state dirs, no caches, no stray files. `DIRECTIONS.md` committed with the ship as required.
5. README: the human-owned PORTFOLIO INTRO marker is at line 23 and both README edits are at
   lines 189 and 411, i.e. BELOW it (`git diff --numstat README.md` -> `2 2`). The `signals` row
   now documents the fail-closed behavior and exit code 1's row names it. Accurate.
6. Leak-guard: this repo carries no `scripts/leak_guard.py` -> check correctly SKIPPED (absence is
   not a gate failure).

## The fix pass at this gate -- a real ship blocker the tester's own suite run missed

`make check-matrix` (both CI legs) FAILED on my first independent run:

```
FAILED tests/test_iter25_behavior.py::test_b4_verbose_attaches_exactly_one_stderr_handler_idempotent
FAILED tests/test_iter25_behavior.py::test_b4_never_touches_the_root_logger
... 14 failed, 4109 passed in 35.46s
make: *** [check-matrix] Error 1
```

Diagnosis, measured rather than guessed:

- `uv run pytest tests/test_iter25_behavior.py` ALONE -> exit 0. So the failure is cross-test
  pollution, not a broken test.
- `uv run pytest tests/test_iter170_behavior.py tests/test_iter25_behavior.py -n 0` -> **exit 1,
  14 failures** in the second module, with `--- Logging error ---` noise. Order-dependency
  confirmed: the new module runs first (alphabetically `iter170` < `iter25`) and poisons the rest.
- Cause: the new module's `test_b06_error_line_is_verbosity_invariant` drives `main([... '-v'])`
  and `-vv` in-process. `_configure_logging` attaches a `StreamHandler` to the CURRENT
  `sys.stderr`, which under `capsys` is a capture object that is torn down at test end. The
  handler is left on the process-global `proactive_loop` logger, so every later test in that
  worker sees an extra handler, a mutated level, and a dead stream.
- `tests/test_iter25_behavior.py` documents this exact hazard in its own docstring and defends
  against it with an autouse snapshot/restore fixture. The new module had no such fixture.

Fix (test-only, no `src/` change, mirrors the in-repo precedent verbatim): added the autouse
`_restore_package_logger` fixture + `Iterator` import to `tests/test_iter170_behavior.py`
(465 lines now, was 435).

`uv run pytest tests/test_iter170_behavior.py tests/test_iter25_behavior.py -n 0` after the fix:
`36 passed`, exit 0.

**Why this was not caught upstream, and why it is worth recording:** `uv run pytest` uses
`-n auto` (declared in `pyproject.toml`), so xdist distributes files across workers and the leak
only breaks tests that land on the SAME worker AFTER the new module. My own first full-suite run
in the default `.venv` exited 0 while `check-matrix` exited 1 minutes later on the same tree --
the same defect presenting as suite flakiness. A single green suite run is therefore NOT evidence
that a new test module is isolation-clean.
