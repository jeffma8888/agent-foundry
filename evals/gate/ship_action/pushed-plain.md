# FINAL — iter-08 — `repolens symbols`

DECISION: SHIP (checkpoint written before push; refined after).

## Gate checklist (all hold)
1. Reviewer verdict = APPROVE (no BLOCKING findings; 3 NITs, all justified). ✓
2. Tester result = PASS (43 new tests; full suite 2731 passed). ✓
3. Independent full-suite run: `uv run pytest` -> **2731 passed, exit 0, 98.78s**
   (xdist `-n auto`; = iter-07's 2688 + 43 new; no regression). ✓
4. `git status` = only intended changes: modified PRODUCT.md, src/repolens/cli.py,
   src/repolens/models.py; untracked src/repolens/symbols.py + the iter-08 test file.
   No stray/cache/state files. No DIRECTIONS.md in this repo (n/a). ✓
5. README still accurate: usage of existing commands unchanged; the README usage block is a
   curated representative subset (tags/toolchain also shipped without being listed there),
   roadmap section points to PRODUCT.md with no hard-coded verb count -> no update needed. ✓
6. Leak-guard: repo has no `scripts/leak_guard.py` -> gate skipped (its absence is not a failure). ✓

## Independent black-box re-verification (real `.venv` CLI on temp fixtures)
- Worked-example golden byte-exact: core(1,2,3) before utils(3,0,3) on the total-3 tie
  (path asc), main(1,1,2) last, `pkg/__init__.py` omitted, main's indented `def method`
  NOT counted, single trailing newline.
- Empty-state byte-exact `None found.` (no table).
- Error contract: nonexistent path -> exit 2, empty stdout, `Error: path does not exist: ...`
  on stderr, no traceback; a FILE path -> exit 2, empty stdout, `Error: not a directory: ...`.
- No absolute path anywhere in the body.

## Ship result
Commit `dd3949c` pushed `b5d3ff3..dd3949c` to repolens/main (push_enabled=True). origin/main == HEAD == dd3949c.

ACTION: PUSHED dd3949c
