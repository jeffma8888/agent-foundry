# bench.py: offline two-arm comparison

`bench.py` runs two operator-supplied commands (a simpler **baseline** and a
**candidate**) against the same frozen input, under the same wall-clock budget,
and scores each arm with a separately executed acceptance check. It is a
standalone utility: nothing in the dispatcher, the pipeline or the release gate
calls it, and adding it changes no loop behaviour.

## Usage

```bash
cat > bench.json <<'EOF'
{"repo": "toy", "spec": "spec.md", "budget_s": 60,
 "baseline_cmd": ["python3", "-c", "pass"],
 "candidate_cmd": ["python3", "fix.py"],
 "accept_cmd": ["python3", "-m", "unittest", "-q", "test_calc"],
 "check_files": ["test_calc.py"]}
EOF
python3 bench.py run --config bench.json --out bench-out   # writes bench-out/record.json
python3 bench.py compare --record bench-out/record.json   # re-derives the verdict offline
```

- Paths in the config resolve relative to the config file. `repo` must be a
  clean git tree (or a plain directory); `out` must be outside it and empty of
  reserved names.
- Each arm runs in its own copy of the frozen snapshot with `BENCH_SPEC`,
  `BENCH_BUDGET_S` and `BENCH_USAGE_FILE` in its environment.
- Exit code: 0 for `WINNER_BY_ACCEPTANCE` or `TIE_ON_ACCEPTANCE`; 2 for
  `UNSCORED`, `INVALID_COMPARISON`, `INVALID_CONFIG` or `REJECTED_INPUT`.

## What it guarantees

- The source tree, spec and acceptance inputs are frozen once, before either arm
  runs, and identified by `base_sha`, `snapshot_sha`, `spec_sha` and `check_sha`.
- Both arms get the same `budget_s`, enforced by killing the arm's process group
  on timeout (and again after a normal exit).
- Acceptance runs as its own process after the arm exits; the arm's
  self-report is never read. Exit 0 is PASS and a positive exit is FAIL. A
  check killed by a signal (a negative return code on POSIX), timed out or
  unable to start is `ERROR`, which leaves the comparison `UNSCORED`. A shell
  wrapper that reports a child's signal as an ordinary positive status
  (128+N) still looks like FAIL.
- Numbers (`budget_s`, `wall_s`, `tokens`, `cost_usd`) count only if they are
  ints or floats, not booleans, that convert to a finite float. A valid JSON
  integer such as `10**1000` is rejected rather than raising. `budget_s` must
  also be at most `MAX_BUDGET_S` (2,147,483 s, about 24.8 days): the largest
  timeout Python's poll()-based subprocess wait accepts (2**31-1 ms). That is
  an executable-timeout limit, not an evaluation policy.
- An arm's `output` (`DIFF` or `NONE`) compares a sorted list of
  length-prefixed (kind, path, payload) records, so one file's bytes cannot
  imitate a second file. Regular files are recorded with their content
  digest and owner-exec bit; file and directory symlinks are recorded by
  target text without being followed; `.git` directories are skipped and
  empty directories are not recorded. This detects changes; it is not a
  tamper-proof seal.
- An arm that modifies a declared `check_files` entry is `REJECTED` and its
  acceptance is not run.
- `compare` names a winner only when both arms finished in budget with exit 0,
  acceptance is PASS/FAIL with a consistent exit code, contract fields match,
  and `input_integrity.ok` is explicitly `true`. Anything missing, malformed or
  errored yields `UNSCORED` or `INVALID_COMPARISON`, never a winner.
- `tokens` and `cost_usd` stay `UNKNOWN` unless the arm itself writes them to
  `$BENCH_USAGE_FILE`; such values are labelled producer-reported.

## What it does not do

- **No sandbox.** Arm and acceptance commands are trusted configuration. They
  run with the operator's own privileges and can read or write anywhere on the
  operator's filesystem and reach the network. Separate working copies and
  post-run integrity checks detect some tampering; they do not contain
  malicious code.
- **`check_files` is integrity pinning, not isolation.** Only the declared
  files are hashed. Undeclared dependencies of the acceptance command (for
  example a `conftest.py` that was not listed) are not checked, and a process
  that starts its own session can outlive the group kill.
- **No blinding.** Nothing hides one arm's existence or output from the other.
- **No model-quality or spend measurement.** `quality_improvement` is always
  `UNMEASURED`. One acceptance pass/fail on one task is not evidence that one
  model or agent configuration is better, and token spend is not independently
  measured. The test suite exercises scripted arms only.
