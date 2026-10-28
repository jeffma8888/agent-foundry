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
 "check_files": ["test_calc.py"], "solution_files": ["calc.py"]}
EOF
python3 bench.py run --config bench.json --out bench-out   # writes bench-out/record.json
python3 bench.py compare --record bench-out/record.json   # re-derives the verdict offline
```

- Paths in the config resolve relative to the config file. `repo` must be a
  clean git tree (or a plain directory); `out` must be outside it and empty of
  reserved names.
- A plain-directory `repo` is snapshotted with each file's mode normalized to
  0755 (owner-executable) or 0644, the same rule a git snapshot follows, so an
  executable `./check.sh` stays executable and an owner-exec change to the
  source is caught by the post-run integrity check.
- `run` refuses (`REJECTED_INPUT`, names only) any inherited `GIT_*` variable
  outside the allowlist trial.py uses (author/committer identity, `GIT_TRACE*`,
  `GIT_TERMINAL_PROMPT`, `GIT_OPTIONAL_LOCKS`, `GIT_PAGER`, `GIT_EDITOR`) before
  any git call or output, so `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, object
  or config overrides cannot attribute another repository's commit to `repo`. A
  git `repo` must also be git's own dir and toplevel (a linked worktree is fine).
- Each arm runs in its own copy of the frozen snapshot with `BENCH_SPEC`,
  `BENCH_BUDGET_S` and `BENCH_USAGE_FILE` in its environment.
- Exit code: 0 for `WINNER_BY_ACCEPTANCE` or `TIE_ON_ACCEPTANCE`; 2 for
  `UNSCORED`, `INVALID_COMPARISON`, `INVALID_CONFIG`, `REJECTED_INPUT` or
  `RECORD_NOT_WRITTEN`.
- `solution_files` is required: the exact relative paths of the regular files
  an arm may change for scoring (see below).

## Compatibility

`solution_files` is a breaking addition. A config without it is
`INVALID_CONFIG`; a present but invalid list is `REJECTED_INPUT` before any
arm runs. In Python, `run_bench` and `freeze_inputs` take it as a required
argument and raise `BenchInputError` for `None` or an invalid list. A
`record.json` written before this field existed has no `solution_sha`, and
`compare` reports it as `INVALID_COMPARISON`: its acceptance ran on the whole
arm copy, so it cannot be trusted under the new contract.

## Acceptance boundary

- Acceptance never runs in the arm's working copy. After an arm exits, bench
  builds a fresh acceptance tree from the frozen snapshot and copies in ONLY the
  declared `solution_files` as they are in the arm copy. A declared file the
  arm left absent (deleted, or a declared new file never created) is absent
  from the acceptance tree.
- Every other change stays in the arm copy as artifact metadata: `output`
  (`DIFF`/`NONE`), `ignored_change_count` and up to 20 `ignored_change_paths`.
  An added package that shadows a test module, a new or edited `conftest.py`,
  or any other undeclared file cannot influence acceptance. `projected` lists
  the declared files that were copied; `accept_tree_sha` fingerprints the tree
  acceptance actually ran in.
- Declarations are exact paths, never patterns. A path containing `*`, `?`
  or `[` is `REJECTED_INPUT`: it is neither expanded nor read as a literal
  name, so a file whose name contains one of these characters cannot be
  declared. Also rejected: absolute paths; `..`, `.`, empty or `.git`
  components; non-normalized spellings; duplicates; one declared path under
  another; a path under a snapshot file; a snapshot directory; and overlap
  with `check_files`. New files are allowed only when declared before the run.
- A declared path that is, or lies under, a symlink or a non-regular file
  `REJECTS` the arm; an unreadable declared file is `ERROR`. Neither runs
  acceptance, and the comparison is `UNSCORED`.
- The sorted list is bound into `check_sha` and recorded as `solution_sha`, a
  contract key: arms scored under different boundaries are
  `INVALID_COMPARISON`.

## Harness-path collisions and the record file

- bench creates each arm tree, each acceptance tree and each log file
  (`<arm>.stdout.txt`, `<arm>.stderr.txt`, `<arm>.accept.txt`) fresh. If one
  already exists, for example because an earlier arm created
  `../candidate` or an arm created `../candidate.accept-tree`, bench never
  runs in it, never scores against it, never writes through a planted
  symlink and never deletes it: the path is kept for diagnosis.
- That arm becomes `ERROR` with `failure` = `{stage, type, message}`, where
  `stage` is `setup`, `acceptance_projection` or `artifact_write`. The top-level
  `harness_failure` names the arm, and the run stops: a later arm is recorded
  as not run, with `wall_s`, `exit_code` and `accept_exit` left `null` and usage
  `UNKNOWN`. A completed earlier arm keeps its real results. The verdict is
  `UNSCORED`, and `compare` on the saved record agrees.
- Only filesystem errors (`OSError`) on these harness-owned paths are handled
  this way. Any other exception still surfaces as a crash.
- `record.json` is written to a temporary sibling and moved into place with
  `os.replace`. A regular file or a leaf symlink an arm planted at that name is
  replaced by the harness record; the symlink's target is not touched. If the
  record cannot be written (a directory at that name, or an unwritable `out`),
  the CLI prints `RECORD_NOT_WRITTEN` and exits 2 without a verdict; nothing
  at that path is removed.
- Records are not signed. A process still running after bench exits, or anyone
  with write access to `out`, can replace `record.json` afterwards. An arm that
  swaps the `out` directory itself for a symlink is also outside this handling.

## What it guarantees

- The source tree, spec, acceptance inputs and solution boundary are frozen
  once, before either arm runs, and identified by `base_sha`, `snapshot_sha`,
  `spec_sha`, `check_sha` and `solution_sha`.
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
- An arm that modifies a declared `check_files` entry (or leaves it unreadable)
  is `REJECTED` and its acceptance is not run; the pinned file is not silently
  restored. The owner-exec bit is part of that pin, compared with the frozen
  snapshot: `chmod 0644 check.sh` (or `chmod 0755` on a pinned non-executable
  file) rejects the arm even when the bytes are unchanged. As in git, group and
  other permission bits are not pinned.
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
- **The solution boundary is artifact filtering, not isolation.** It keeps
  undeclared arm files out of acceptance; it does not prove the checker is
  independent of the arm. Declared solution files are arbitrary code that runs
  inside acceptance (for example on import) and can subvert it. The acceptance
  command can still read paths, environment variables or network state
  outside its tree, where an arm may have left something, and a process that
  starts its own session can outlive the group kill.
- **No blinding.** Nothing hides one arm's existence or output from the other.
- **No model-quality or spend measurement.** `quality_improvement` is always
  `UNMEASURED`. One acceptance pass/fail on one task is not evidence that one
  model or agent configuration is better, and token spend is not independently
  measured. The test suite exercises scripted arms only.

## Trial arms (`trial.py`)

`trial.py` is an optional bench arm command that runs real Foundry stages on the frozen task. bench.py stays the only scorer.

- Arm: `trial.py arm --arm baseline|candidate --state-root ABS --agent-argv-json JSON`, run by bench with cwd = the arm copy.
- baseline runs one `engineer` stage. candidate runs `engineer`, then `reviewer`, then `fix-review` only when the reviewer gate requires changes. No pm, tester, final, revert, push or release stage can run.
- Both arms seed the exact `$BENCH_SPEC` bytes as `state/iter-01/pm.md` under their own empty state root. They write a private `config.json` there, so the role cards' `Product config` line never falls back to `products/`.
- The arm copy becomes its own git root with one snapshot commit, made through the effective hooks. A hook refusal fails the arm.
- An arm or plan refuses (exit 2, names only) any inherited `GIT_*` variable that could aim git or the agent at another repository, index, object store, config or hooks (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE` and the like); only author/committer identity, `GIT_TRACE*`, `GIT_TERMINAL_PROMPT`, `GIT_OPTIONAL_LOCKS`, `GIT_PAGER` and `GIT_EDITOR` pass. After `git init` and before staging, the arm checks that git's dir is the copy's own `.git`, its toplevel is the copy, and it has no remote.
- One attempt per stage, no auth-hold sleep, and each stage timeout is capped by the remaining `$BENCH_BUDGET_S`. bench's process-group kill stays the outer bound. A stage that writes no output exits nonzero with no retry and no revert.
- The agent argv must be explicit, with exactly one `{prompt}`. There is no fallback to `FOUNDRY_AGENT_*`.
- `trial.py plan ...` is a dry run. It spawns nothing, writes nothing, and prints the first stage's attempt-1 prompt sha.
- Inputs are refused before anything is created: paths that are relative, non-normalized or symlinked; a repo or state root overlapping the checkout, each other, another arm's state or a git worktree; a non-empty state root; a bad budget.
- This is not a sandbox. The agent runs with the operator's privileges. A real agent run needs separate explicit operator approval and a budget.
- The tests use scripted spy agents only, so they show plumbing, not model quality.
