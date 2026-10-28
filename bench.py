#!/usr/bin/env python3
"""bench.py -- offline two-arm, equal-budget comparison seam with external scoring.

WHY THIS FILE EXISTS: the pipeline records per-stage binary verdicts (tester
RESULT, reviewer VERDICT, gate ACTION) and ship/revert counts, but nothing in
the repo ever runs the SAME task twice -- a simpler baseline arm against the
multi-role candidate arm -- on the same frozen snapshot under the same budget,
and scores both from OUTSIDE the generating process. `docs/ORG_DESIGN.md`
states the hypothesis ("multi-agent gains over strong single-agent baselines
are often minimal"); this module is the smallest executable thing that can
measure it.

WHAT IS FROZEN, ONCE, BEFORE EITHER ARM RUNS:
  * the input tree. A git input must be CLEAN (no modified or untracked files);
    `git archive <HEAD>` is taken once and the same bytes are unpacked into each
    arm's working directory. No `.git` metadata (including a linked worktree's
    `.git` pointer file) reaches an arm. Only a source with NO `.git` marker
    (lstat: a dir, a pointer file or even a broken symlink counts) is a non-git
    tree; a marked source whose HEAD cannot be read as one object ID (git
    missing or failing, unborn or corrupt HEAD, malformed output) is refused
    before any arm or out dir, never snapshotted as a plain tree, and the same
    failure after the run fails input integrity (UNSCORED). A non-git tree is
    tarred the same way, each file's mode normalized to 0755 (owner-exec) or
    0644 as git records it.
    Symbolic and hard links are never followed and never copied.
    `base_sha` = the resolved commit (or `tree:<sha256>` for a non-git tree),
    `snapshot_sha` = sha256 of the exact archived bytes.
    Provenance: an inherited `GIT_*` variable outside a small harmless allowlist
    (the one trial.py uses) is refused by NAME before any git call, snapshot or
    out dir, since it can aim git at another repository, index, object store,
    config or hooks and so attribute a foreign commit to the input. After HEAD
    is found and before status/archive, git's dir and toplevel must be the
    input's own (its `.git` directory, or the target of its `.git` pointer).
    `git status` cannot see an owner-exec change when `core.fileMode=false`,
    so every REGULAR file in the HEAD archive is also lstat-ed in the input
    (no link followed; symlink members skipped; untracked or ignored files are
    never walked): a path that is missing, not a regular file, or whose
    owner-exec bit differs from the archive is refused before any arm or out
    dir, and the same check after the run fails input integrity (UNSCORED).
    `git status` also skips index entries marked assume-unchanged or
    skip-worktree, so an edit there leaves it clean. Any such entry (read with
    `git ls-files -v -z`; never set, cleared or refreshed here) is refused
    before any arm or out dir even when the file is unchanged, so sparse
    checkouts are unsupported; a flag present after the run fails input
    integrity (UNSCORED) whatever `git status` says. A flag set and cleared
    again before the post-run check is not seen. If that read fails it is
    refused the same way (no git output echoed), or UNSCORED after the run.
  * the task spec: `spec_sha` = sha256 of its bytes; arms read a frozen copy.
  * the acceptance inputs: `check_sha` = sha256 over the acceptance command,
    the pinned content of every operator-declared `check_files` entry AND the
    declared `solution_files` list. Before an arm's acceptance runs, each check
    file in the arm copy is re-hashed and its owner-exec bit compared with the
    frozen snapshot's (the one mode bit git records, so a group/other-only chmod
    is no change); any change (or an unreadable file) REJECTS that arm
    (`accept = REJECTED`, never a verdict in its favour).
  * the acceptance boundary: `solution_files` (REQUIRED) = the exact relative
    paths of the regular files an arm may change for scoring. No glob
    characters (a path containing `*`, `?` or `[` is rejected, never expanded
    or read as a literal name), no directories, no `..`/absolute/`.git`
    paths, no duplicates or nesting, no overlap with `check_files`. New files
    are allowed only if declared here.
    `solution_sha` = sha256 of the sorted list; it is a contract key, so arms
    scored under different boundaries never compare as equal.
  * the budget: `budget_s` wall-clock cap, ENFORCED here with a process-group
    timeout (distinct from any budget the arm's own policy claims to honour).

SCORING is an INDEPENDENT acceptance command run AFTER the arm exits, in a FRESH
acceptance tree: the frozen snapshot plus ONLY the declared solution files as
they are in the arm copy (a declared file the arm left absent is absent). Any
other change -- an added package that shadows a test module, a new
`conftest.py`, an edited undeclared config file -- stays in the arm copy as
artifact metadata (`output`, `ignored_change_count`, `ignored_change_paths`)
and never reaches acceptance. A declared path that is, or lies under, a symlink
or a non-regular file REJECTS the arm; an unreadable declared file is ERROR.
Its exit code is the only quality signal: 0 -> PASS, positive -> FAIL.
A check that did not complete -- killed by a signal (negative return code on
POSIX), timed out, or failed to start -- is ERROR, never FAIL, so it cannot
hand the other arm a win. A shell wrapper that reports its child's signal as an
ordinary positive status (128+N) is indistinguishable from a failing test here.
An arm's self-report is never read. `compare()` forms the only verdict:
  * missing arm / unequal or malformed contract fields  -> INVALID_COMPARISON
  * over budget, non-zero or missing arm exit, missing or non-finite wall_s,
    acceptance not PASS/FAIL, inconsistent or negative (signal) accept_exit,
    invalid usage report,
    input tree modified during the run                  -> UNSCORED
  * equal acceptance   -> TIE_ON_ACCEPTANCE (wall-clock is THROUGHPUT, not quality)
  * acceptance differs -> WINNER_BY_ACCEPTANCE
  No path produces a winner from missing, unequal, malformed or errored evidence.

HARNESS-PATH COLLISIONS: an arm tree, acceptance tree or log file that already
exists when the harness creates it (an arm can plant one: there is no sandbox)
is never reused, cleared or written through. The arm is ERROR with a `failure`
{stage, type, message} (`setup`, `acceptance_projection`, `artifact_write`), the
record's `harness_failure` names it, later arms are not run (their fields stay
unknown), and the verdict is UNSCORED. The colliding path is kept for diagnosis.
record.json is written to a temp sibling and moved into place with os.replace,
so a planted regular file or leaf symlink there is replaced, never followed. If
it cannot be written (e.g. a directory sits at that name) the CLI prints
RECORD_NOT_WRITTEN and exits 2 with no verdict. Records are NOT signed: any
process with write access can still forge one after the run.
  Malformed records (wrong JSON types, sets, strings for numbers) are
  INVALID_COMPARISON, never an exception. A number counts only if it is an int
  or float (not bool) that converts to a finite float: a valid JSON integer like
  10**1000 is rejected as unrepresentable, not raised as OverflowError.
  `budget_s` must also be <= MAX_BUDGET_S (2**31-1 ms, about 24.8 days), the
  largest timeout subprocess's poll()-based wait can execute on POSIX. That is
  an executable-timeout limit, not an evaluation policy.

USAGE AND COST: `tokens` and `cost_usd` are the string `UNKNOWN` unless the arm
command itself wrote a JSON object to `$BENCH_USAGE_FILE`. When present they
are labelled `usage_source = "producer-reported"`: the arm's own claim, NOT an
independent measurement. Supplied values must be finite, non-negative numbers
or the arm is UNSCORED. Unknown is never reported as zero.

WHAT THIS DOES NOT DO, stated plainly:
  * no security isolation: arm and acceptance commands are trusted operator
    configuration executed with the operator's own privileges and network. Each
    arm gets a SEPARATE working copy, but nothing prevents a command from
    reading or writing paths outside it. The input tree is re-verified after the
    run and a mutation marks the comparison UNSCORED; that is integrity
    verification, not an OS sandbox.
  * no blinding: nothing here hides one arm's existence or output from the other.
  * the solution boundary is artifact filtering, not isolation or proof that the
    checker is independent of the arm: declared solution files are arbitrary
    code that runs inside acceptance (e.g. on import) and can subvert it, and
    the acceptance command can still read paths, environment or network outside
    its tree, where an arm may have left state.
  * on timeout the arm's process group is killed (POSIX `start_new_session` +
    `killpg`); a descendant that created its own session is outside that bound.
    Any process group members still alive after a normal exit are also killed.
  * `quality_improvement` is always `UNMEASURED`: an acceptance pass/fail on one
    task is not model-efficacy evidence. Scripted arms (the test suite) prove the
    harness mechanics, nothing about any model.

CLI EXAMPLE (paths in the config resolve relative to the config file):
    bench.json:
      {"repo": "toy", "spec": "spec.md", "budget_s": 60,
       "baseline_cmd": ["python3", "-c", "pass"],
       "candidate_cmd": ["python3", "fix.py"],
       "accept_cmd": ["python3", "-m", "unittest", "-q", "test_calc"],
       "check_files": ["test_calc.py"], "solution_files": ["calc.py"]}
    python3 bench.py run --config bench.json --out bench-out
    python3 bench.py compare --record bench-out/record.json
  Exit 0 only for TIE_ON_ACCEPTANCE / WINNER_BY_ACCEPTANCE; 2 for any rejection
  (including RECORD_NOT_WRITTEN).
  A config without `solution_files` is INVALID_CONFIG; a record without
  `solution_sha` (written before the boundary existed) is INVALID_COMPARISON.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import pathlib
import posixpath
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

UNKNOWN = "UNKNOWN"
# Largest wall-clock timeout that subprocess can execute on POSIX: its wait uses
# poll(), which takes the timeout as a C int of milliseconds (2**31-1 ms).
MAX_BUDGET_S = (2 ** 31 - 1) // 1000
ARMS = ("baseline", "candidate")
CONTRACT_KEYS = ("base_sha", "snapshot_sha", "spec_sha", "check_sha", "solution_sha", "budget_s")
_RESERVED_OUT = {"record.json", "frozen", *ARMS}
# Characters that make a path a glob pattern (the set glob.has_magic checks). A
# declaration containing one is rejected, so a pattern is never silently read as a
# literal file name that matches nothing.
_GLOB_CHARS = frozenset("*?[")
_DRAIN_S = 2.0
# The only inherited GIT_* names freezing accepts; any other one (repo, work tree,
# index, objects, common dir, discovery, injected config, hooks, exec path, ...) is
# refused by name, never cleared. Kept equal to trial.py's allowlist (a test pins it).
HARMLESS_GIT_ENV = frozenset({"GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
                              "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE",
                              "GIT_TERMINAL_PROMPT", "GIT_OPTIONAL_LOCKS", "GIT_PAGER",
                              "GIT_EDITOR"})
HARMLESS_GIT_ENV_PREFIX = "GIT_TRACE"


class BenchInputError(ValueError):
    """Raised before any arm runs when the inputs cannot be frozen safely."""


class BenchRecordError(OSError):
    """Raised when the final record.json cannot be persisted; no verdict is issued."""


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _finite(x) -> bool:
    """int/float (not bool) that converts to a finite float; huge ints are False."""
    if not isinstance(x, (int, float)) or isinstance(x, bool):
        return False
    try:
        return math.isfinite(float(x))
    except OverflowError:
        return False


def _short(v, n: int = 40) -> str:
    """repr for messages; never raises on ints too long for str() (3.11+ limit)."""
    try:
        return repr(v)[:n]
    except ValueError:
        return f"<{type(v).__name__} too large to display>"


def _budget_ok(x) -> bool:
    return _finite(x) and 0 < x <= MAX_BUDGET_S


def _nonempty_str(x) -> bool:
    return isinstance(x, str) and bool(x)


def _git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=False, check=True)


_HEX = frozenset("0123456789abcdef")
_OBJECT_ID_LENGTHS = (40, 64)  # git's two object formats: SHA-1 and SHA-256
_HEAD_UNREADABLE = ("input repo HEAD could not be read (git rev-parse HEAD failed or did "
                    "not print one object ID); refusing to treat a git-marked source as a "
                    "plain directory")


def _git_marker(repo: pathlib.Path) -> bool:
    """True if `repo/.git` exists in ANY form: directory, pointer file, or symlink, even a
    broken one (lstat, never stat). Only a source with no marker is a plain directory."""
    try:
        os.lstat(repo / ".git")
    except FileNotFoundError:
        return False
    except OSError:
        raise BenchInputError("input repo .git marker could not be inspected; refusing to "
                              "treat a possibly git-marked source as a plain "
                              "directory") from None
    return True


def _git_head(repo: pathlib.Path) -> str | None:
    """None ONLY when `repo` has no `.git` marker. A git-marked source whose HEAD cannot
    be read as exactly one object ID (git missing or failing, unborn or corrupt HEAD,
    empty or malformed output) raises BenchInputError with a static message."""
    if not _git_marker(repo):
        return None
    try:
        out = _git(repo, "rev-parse", "HEAD").stdout
    except (OSError, subprocess.CalledProcessError):
        raise BenchInputError(_HEAD_UNREADABLE) from None
    head = out.decode("ascii", "replace").strip()
    if len(head) not in _OBJECT_ID_LENGTHS or not set(head) <= _HEX:
        raise BenchInputError(_HEAD_UNREADABLE)
    return head


def _git_dirty(repo: pathlib.Path) -> str:
    return _git(repo, "status", "--porcelain", "--untracked-files=all").stdout.decode()


def _git_env_refusal() -> str | None:
    """Names (never values) of inherited GIT_* variables outside the allowlist."""
    bad = sorted(k for k in os.environ if k.startswith("GIT_") and k not in HARMLESS_GIT_ENV
                 and not k.startswith(HARMLESS_GIT_ENV_PREFIX))
    if not bad:
        return None
    return ("refusing inherited git environment that can redirect the repository, its "
            f"index/objects, discovery, config or hooks; unset it and rerun: {', '.join(bad)}")


def _check_git_identity(repo: pathlib.Path) -> None:
    """git's dir must be `repo`'s own `.git` (or the target of its `.git` pointer file,
    e.g. a linked worktree) and its toplevel must be `repo`, so `base_sha` and the
    dirty check describe the selected input. Paths are not echoed."""
    dotgit = repo / ".git"
    own = None
    if dotgit.is_file():
        try:
            line = dotgit.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            line = ""
        if line.startswith("gitdir:"):
            own = (repo / line[len("gitdir:"):].strip()).resolve()
    elif dotgit.is_dir():
        own = dotgit.resolve()
    try:
        lines = _git(repo, "rev-parse", "--absolute-git-dir",
                     "--show-toplevel").stdout.decode().splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        lines = []
    if (own is None or len(lines) != 2 or not all(lines)
            or pathlib.Path(lines[0]).resolve() != own or pathlib.Path(lines[1]).resolve() != repo):
        raise BenchInputError("input repo identity check failed: git's dir or toplevel is not "
                              "the selected repo's own; refusing to attribute its snapshot")


def _tree_tar(root: pathlib.Path) -> tuple[bytes, int]:
    """Deterministic tar of regular files/dirs under `root` (no links followed, no
    `.git`). Mode is 0755 if owner-exec else 0644 (the bit _tree_entries/_project
    use); no other permission bits, ownership or timestamps. Returns (bytes, skipped_links)."""
    buf = io.BytesIO()
    skipped = 0
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if d != ".git"
                                 and not os.path.islink(os.path.join(dirpath, d)))
            skipped += sum(1 for d in os.listdir(dirpath)
                           if os.path.islink(os.path.join(dirpath, d)))
            for f in sorted(filenames):
                p = pathlib.Path(dirpath) / f
                if p.is_symlink() or not p.is_file():
                    continue
                info = tarfile.TarInfo(p.relative_to(root).as_posix())
                data = p.read_bytes()
                exe = p.lstat().st_mode & stat.S_IXUSR
                info.size, info.mtime, info.mode = len(data), 0, 0o755 if exe else 0o644
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue(), skipped


def _frame(b: bytes) -> bytes:
    return len(b).to_bytes(8, "big") + b


def _tree_sha(root: pathlib.Path) -> str:
    return _entries_sha(_tree_entries(root))


def _tree_entries(root: pathlib.Path) -> dict[bytes, tuple[bytes, bytes]]:
    """Change detector for a working copy; judges `output`, not `git status`.

    One record per entry, sorted by path: (kind, path, payload), each field
    length-prefixed so no file content can imitate a record boundary. Kinds:
    `file` / `exec` (owner-exec bit) with payload sha256(bytes); `link` with the
    raw link target (file AND directory symlinks; never followed); `other` for
    non-regular files; `unreadable` for a regular file that cannot be read.
    Directories named `.git` are skipped; empty directories are not recorded.
    A content fingerprint, not a tamper-proof seal."""
    entries: dict[bytes, tuple[bytes, bytes]] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        links = [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]
        dirnames[:] = sorted(d for d in dirnames if d not in links)
        for f in [*filenames, *links]:
            p = pathlib.Path(dirpath) / f
            rel = os.fsencode(p.relative_to(root).as_posix())
            st = p.lstat()
            if p.is_symlink():
                kind, payload = b"link", os.fsencode(os.readlink(p))
            elif p.is_file():
                kind = b"exec" if st.st_mode & 0o100 else b"file"
                try:
                    payload = hashlib.sha256(p.read_bytes()).digest()
                except OSError:
                    kind, payload = b"unreadable", b""
            else:
                kind, payload = b"other", b""
            entries[rel] = (kind, payload)
    return entries


def _entries_sha(entries: dict[bytes, tuple[bytes, bytes]]) -> str:
    h = hashlib.sha256(_frame(b"bench-tree-v2"))
    for rel, (kind, payload) in sorted(entries.items()):
        h.update(_frame(kind) + _frame(rel) + _frame(payload))
    return h.hexdigest()


def _tar_owner_exec(tar_bytes: bytes) -> dict[str, bool]:
    """Owner-exec bit of each regular file AS FROZEN (not as the input now is)."""
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
        return {posixpath.normpath(m.name): bool(m.mode & stat.S_IXUSR)
                for m in tar.getmembers() if m.isreg()}


def _tar_regular_files(tar_bytes: bytes) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
        for m in tar.getmembers():
            if m.isreg():
                out[posixpath.normpath(m.name)] = tar.extractfile(m).read()
    return out


def _source_mode_drift(repo: pathlib.Path, tar_bytes: bytes) -> list[str]:
    """Archived REGULAR files whose path in `repo` is missing, reached through a
    link or non-directory, not a regular file, or has an owner-exec bit different
    from the frozen archive. lstat only: nothing is followed, read or executed, and
    only archive members are visited (symlink members are skipped). Covers what
    `git status` misses when core.fileMode=false; it is not a content check."""
    drift = []
    for rel, exe in sorted(_tar_owner_exec(tar_bytes).items()):
        parts = rel.split("/")
        try:
            if posixpath.isabs(rel) or any(p in ("", ".", "..", ".git") for p in parts):
                raise ValueError(rel)
            p = repo
            for part in parts[:-1]:
                p = p / part
                if not stat.S_ISDIR(os.lstat(p).st_mode):
                    raise NotADirectoryError(rel)
            st = os.lstat(p / parts[-1])
            ok = stat.S_ISREG(st.st_mode) and bool(st.st_mode & stat.S_IXUSR) == exe
        except (OSError, ValueError):
            ok = False
        if not ok:
            drift.append(rel)
    return drift


def _index_flags(repo: pathlib.Path) -> dict[str, str]:
    """Index entries `git status` does not compare with the working tree: tag
    lowercase in `git ls-files -v` (assume-unchanged) or `S`/`s` (skip-worktree).
    Read only; NUL-separated, so a newline in a path cannot forge an entry. An
    entry that does not parse is reported too (fail closed). path -> flag names."""
    flagged: dict[str, str] = {}
    for entry in _git(repo, "ls-files", "-v", "-z").stdout.split(b"\0"):
        if not entry:
            continue
        tag, path = entry[:1], entry[2:]
        if entry[1:2] != b" " or not path:
            flagged[os.fsdecode(entry)] = "unparsed index entry"
            continue
        kinds = [k for k, hit in (("assume-unchanged", tag.islower()),
                                  ("skip-worktree", tag in (b"S", b"s"))) if hit]
        if kinds:
            flagged[os.fsdecode(path)] = ", ".join(kinds)
    return flagged


# --------------------------------------------------------------------------
# freezing
# --------------------------------------------------------------------------
def _check_solution_files(solution_files, files: dict[str, bytes], pinned: dict) -> list[str]:
    """Validate the declared acceptance boundary against the frozen snapshot."""
    if not (isinstance(solution_files, list) and solution_files
            and all(_nonempty_str(s) for s in solution_files)):
        raise BenchInputError("solution_files is required: a non-empty list of exact relative "
                              "paths of the files an arm may change for acceptance")
    if len(set(solution_files)) != len(solution_files):
        raise BenchInputError("solution_files contains duplicates")
    snapshot_dirs = {"/".join(f.split("/")[:i]) for f in files for i in range(1, f.count("/") + 1)}
    for s in solution_files:
        parts = s.split("/")
        if ("\0" in s or posixpath.isabs(s) or posixpath.normpath(s) != s
                or any(p in ("", ".", "..", ".git") for p in parts)):
            raise BenchInputError(f"solution file must be an exact normalized relative path: {_short(s)}")
        if _GLOB_CHARS & set(s):
            raise BenchInputError("solution file must be an exact path, not a glob pattern "
                                  f"(no '*', '?' or '['): {_short(s)}")
        if s in pinned:
            raise BenchInputError(f"solution file overlaps check_files: {s}")
        if s in snapshot_dirs:
            raise BenchInputError(f"solution file is a directory in the snapshot: {s}")
        ancestors = {"/".join(parts[:i]) for i in range(1, len(parts))}
        if ancestors & (set(files) | set(solution_files)):
            raise BenchInputError(f"solution file lies under a file path: {s}")
    return sorted(solution_files)


def freeze_inputs(repo: pathlib.Path, spec_path: pathlib.Path, budget_s, accept_cmd,
                  check_files, solution_files) -> dict:
    """Resolve and pin every input ONCE. Raises BenchInputError on anything unsafe."""
    refusal = _git_env_refusal()  # before any git call, snapshot or out dir
    if refusal:
        raise BenchInputError(refusal)
    repo = pathlib.Path(repo).resolve()
    spec_path = pathlib.Path(spec_path).resolve()
    if not repo.is_dir():
        raise BenchInputError(f"repo is not a directory: {repo}")
    if not spec_path.is_file():
        raise BenchInputError(f"spec is not a file: {spec_path}")
    if not _budget_ok(budget_s):
        raise BenchInputError("budget_s must be a positive number representable as a "
                              f"finite float and <= {MAX_BUDGET_S}s (executable timeout "
                              f"limit), got {_short(budget_s)}")
    for label, cmd in (("accept_cmd", accept_cmd),):
        if not (isinstance(cmd, list) and cmd and all(_nonempty_str(c) for c in cmd)):
            raise BenchInputError(f"{label} must be a non-empty list of strings")
    if not (isinstance(check_files, list) and check_files
            and all(_nonempty_str(c) for c in check_files)):
        raise BenchInputError("check_files must be a non-empty list of relative paths")
    head = _git_head(repo)
    if head:
        _check_git_identity(repo)  # after HEAD is found, before status and archive
        try:
            dirty = _git_dirty(repo)
        except (OSError, subprocess.CalledProcessError):
            raise BenchInputError("input repo status could not be read (git status "
                                  "--porcelain failed); refusing a source whose dirty "
                                  "state is unknown") from None
        if dirty.strip():
            raise BenchInputError("input repo is dirty; commit or stash first:\n" + dirty)
        try:
            tar_bytes = _git(repo, "archive", "--format=tar", head).stdout
        except (OSError, subprocess.CalledProcessError):
            raise BenchInputError("input repo snapshot could not be read (git archive "
                                  "failed); refusing a source whose HEAD cannot be "
                                  "frozen") from None
        drift = _source_mode_drift(repo, tar_bytes)
        if drift:
            raise BenchInputError("input repo working tree differs from HEAD in file type or "
                                  "owner-exec mode (git status cannot see a mode change when "
                                  "core.fileMode=false); restore or commit it first: "
                                  + ", ".join(drift[:20]))
        try:
            flags = _index_flags(repo)
        except (OSError, subprocess.CalledProcessError):
            raise BenchInputError("input repo index flags could not be read (git ls-files "
                                  "-v -z failed); refusing a source whose assume-unchanged "
                                  "or skip-worktree entries are unknown") from None
        if flags:
            raise BenchInputError("input repo index marks tracked files assume-unchanged or "
                                  "skip-worktree, so git status does not compare them with "
                                  "the working tree (sparse checkouts are not supported); "
                                  "clear the flag and rerun: " + ", ".join(
                                      f"{p} ({k})" for p, k in sorted(flags.items())[:20]))
        base_sha, skipped = head, 0
    else:
        tar_bytes, skipped = _tree_tar(repo)
        base_sha = "tree:" + _sha256(tar_bytes)
    files, owner_exec = _tar_regular_files(tar_bytes), _tar_owner_exec(tar_bytes)
    pinned: dict[str, str] = {}
    for cf in check_files:
        norm = posixpath.normpath(cf)
        if norm.startswith("..") or posixpath.isabs(norm) or norm not in files:
            raise BenchInputError(f"check file not a regular file inside the snapshot: {cf}")
        pinned[norm] = _sha256(files[norm])
    solution = _check_solution_files(solution_files, files, pinned)
    spec_bytes = spec_path.read_bytes()
    check_sha = _sha256(json.dumps({"accept_cmd": accept_cmd, "files": pinned,
                                    "solution_files": solution}, sort_keys=True).encode())
    return {"repo": str(repo), "spec": str(spec_path), "base_sha": base_sha,
            "snapshot_sha": _sha256(tar_bytes), "spec_sha": _sha256(spec_bytes),
            "check_sha": check_sha, "check_files": pinned, "accept_cmd": list(accept_cmd),
            "solution_files": solution, "solution_sha": _sha256(json.dumps(solution).encode()),
            "budget_s": budget_s, "skipped_links": skipped,
            "_tar": tar_bytes, "_spec": spec_bytes,
            "_check_exec": {rel: owner_exec[rel] for rel in pinned}}


def _validate_out_dir(out_dir: pathlib.Path, frozen: dict) -> pathlib.Path:
    out_dir = pathlib.Path(out_dir).resolve()
    repo = pathlib.Path(frozen["repo"])
    spec = pathlib.Path(frozen["spec"])
    if out_dir == repo or repo in out_dir.parents:
        raise BenchInputError(f"out_dir is inside the input repo: {out_dir}")
    if out_dir in repo.parents or out_dir in spec.parents:
        raise BenchInputError(f"an input lives inside out_dir: {out_dir}")
    if out_dir.exists():
        if not out_dir.is_dir():
            raise BenchInputError(f"out_dir is not a directory: {out_dir}")
        clash = [p.name for p in out_dir.iterdir()
                 if p.name in _RESERVED_OUT or p.name.startswith(tuple(a + "." for a in ARMS))]
        if clash:
            raise BenchInputError(f"out_dir is prepopulated: {sorted(clash)}")
    return out_dir


def _materialize(frozen: dict, dest: pathlib.Path) -> int:
    """Unpack the frozen bytes into a fresh `dest`; only regular files and
    directories are extracted (links skipped). Returns skipped link count."""
    dest.mkdir(parents=True, exist_ok=False)
    skipped = frozen["skipped_links"]
    with tarfile.open(fileobj=io.BytesIO(frozen["_tar"]), mode="r") as tar:
        keep = []
        for m in tar.getmembers():
            if m.isreg() or m.isdir():
                keep.append(m)
            else:
                skipped += 1
        tar.extractall(dest, members=keep, filter="data")
    return skipped


def _write_new(path: pathlib.Path, text: str) -> None:
    """Create a harness artifact that must not exist yet. Never follows a planted
    symlink and never overwrites: a collision raises an OSError."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def _persist_record(out_dir: pathlib.Path, record: dict) -> None:
    """Write record.json via a fresh temp sibling + os.replace, so a regular file or
    a leaf symlink already at that name is replaced (never followed or appended to).
    A directory there (or an unwritable out_dir) raises BenchRecordError; nothing
    at the destination is deleted."""
    data = json.dumps(record, indent=2, sort_keys=True).encode("utf-8")
    dest = out_dir / "record.json"
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=".record.", suffix=".tmp", dir=out_dir)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, dest)
        tmp = None
    except OSError as exc:
        raise BenchRecordError(f"cannot write {dest}: {type(exc).__name__}: {exc}") from exc
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _project(frozen: dict, arm_dir: pathlib.Path, dest: pathlib.Path):
    """Build the acceptance tree: a fresh copy of the frozen snapshot plus ONLY the
    declared solution files as they are in `arm_dir`. Returns (projected paths,
    reject reason, error). Nothing outside `dest` is written."""
    _materialize(frozen, dest)
    projected: list[str] = []
    for rel in frozen["solution_files"]:
        parts, src, st = rel.split("/"), arm_dir, None
        for i, part in enumerate(parts):
            src = src / part
            try:
                st = os.lstat(src)
            except FileNotFoundError:
                st = None
                break
            except OSError as exc:
                return projected, None, f"solution file {rel}: {type(exc).__name__}: {exc}"
            if stat.S_ISLNK(st.st_mode):
                return projected, f"solution file {rel} is or lies under a symlink", None
            if i < len(parts) - 1 and not stat.S_ISDIR(st.st_mode):
                return projected, f"solution file {rel} lies under a non-directory", None
        target = dest / rel
        if st is None:  # declared but absent in the arm copy -> absent for acceptance
            if target.is_file():
                target.unlink()
            continue
        if not stat.S_ISREG(st.st_mode):
            return projected, f"solution file {rel} is not a regular file", None
        try:
            fd = os.open(src, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            return projected, None, f"solution file {rel} unreadable: {type(exc).__name__}: {exc}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if st.st_mode & 0o100 else 0o644)
        projected.append(rel)
    return projected, None, None


def _input_integrity(frozen: dict) -> dict:
    repo = pathlib.Path(frozen["repo"])
    try:
        head = _git_head(repo)
        if head:
            now = {"head": head, "dirty": _git_dirty(repo).strip()}
            drift = _source_mode_drift(repo, frozen["_tar"])
            if drift:  # key present only on failure, so a clean record keeps its shape
                now["mode_drift"] = drift[:20]
            flags = _index_flags(repo)
            if flags:  # likewise only on failure
                now["index_flags"] = sorted(flags)[:20]
            ok = head == frozen["base_sha"] and not now["dirty"] and not drift and not flags
        else:
            now = {"tree": "tree:" + _sha256(_tree_tar(repo)[0])}
            ok = now["tree"] == frozen["base_sha"]
    except BenchInputError as exc:  # git-marked but HEAD unreadable: static message only
        now, ok = {"error": f"{type(exc).__name__}: {exc}"}, False
    except (OSError, subprocess.CalledProcessError) as exc:
        now, ok = {"error": f"{type(exc).__name__}: {exc}"}, False
    return {"ok": ok, "observed": now}


# --------------------------------------------------------------------------
# bounded process execution (whole process group on POSIX)
# --------------------------------------------------------------------------
def _killpg(p: subprocess.Popen) -> None:
    if os.name != "posix":
        return
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _run_bounded(cmd: list[str], cwd: pathlib.Path, env: dict, timeout) -> dict:
    """Run `cmd` as the leader of its own session; kill the whole group on timeout
    and again after exit so lingering descendants cannot outlive the arm."""
    res = {"exit_code": None, "stdout": "", "stderr": "", "timed_out": False, "error": None}
    try:
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, errors="replace",
                             start_new_session=(os.name == "posix"))
    except (OSError, ValueError, TypeError) as exc:
        res["error"] = f"{type(exc).__name__}: {exc}"
        return res
    try:
        out, err = p.communicate(timeout=timeout)
        res["exit_code"] = p.returncode
    except subprocess.TimeoutExpired:
        res["timed_out"] = True
        _killpg(p)
        try:
            out, err = p.communicate(timeout=_DRAIN_S)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = "", ""
            res["error"] = "output pipes still held after group kill; output dropped"
    finally:
        _killpg(p)
    res["stdout"], res["stderr"] = out or "", err or ""
    return res


# --------------------------------------------------------------------------
# one arm
# --------------------------------------------------------------------------
def _arm_record(name: str, cmd, frozen: dict) -> dict:
    """An arm record whose unrun fields stay unknown (None / NOT_RUN / UNKNOWN)."""
    return {"arm": name, "cmd": cmd, "base_sha": frozen["base_sha"],
            "snapshot_sha": frozen["snapshot_sha"], "spec_sha": frozen["spec_sha"],
            "check_sha": frozen["check_sha"], "solution_sha": frozen["solution_sha"],
            "budget_s": frozen["budget_s"], "tree_sha_start": None, "skipped_links": None,
            "wall_s": None, "exit_code": None, "timed_out": False, "output": "NONE",
            "ignored_change_count": None, "ignored_change_paths": [],
            "projected": [], "accept_tree_sha": None,
            "accept": "NOT_RUN", "accept_exit": None,
            "tokens": UNKNOWN, "cost_usd": UNKNOWN, "usage_source": None, "error": None,
            "failure": None}


def _harness_failure(rec: dict, stage: str, exc: OSError) -> dict:
    """Mark a filesystem failure in a harness-owned path: ERROR, never scored. Any
    colliding path is left in place for diagnosis."""
    rec["failure"] = {"stage": stage, "type": type(exc).__name__, "message": str(exc)}
    msg = f"harness {stage}: {type(exc).__name__}: {exc}"
    rec["error"] = f"{rec['error']}; {msg}" if rec["error"] else msg
    rec["accept"] = "ERROR"
    return rec


def run_arm(name: str, cmd: list[str], frozen: dict, out_dir: pathlib.Path) -> dict:
    rec = _arm_record(name, cmd, frozen)
    arm_dir = out_dir / name
    try:  # a pre-existing arm tree (e.g. planted by an earlier arm) is never reused
        rec["skipped_links"] = _materialize(frozen, arm_dir)
    except OSError as exc:
        return _harness_failure(rec, "setup", exc)
    start = _tree_entries(arm_dir)
    start_tree = rec["tree_sha_start"] = _entries_sha(start)
    spec_file = out_dir / "frozen" / "spec"
    usage_file = out_dir / f"{name}.usage.json"
    budget_s = frozen["budget_s"]
    env = dict(os.environ)
    env.update({"BENCH_SPEC": str(spec_file), "BENCH_BUDGET_S": str(budget_s),
                "BENCH_USAGE_FILE": str(usage_file)})
    if not (isinstance(cmd, list) and cmd and all(_nonempty_str(c) for c in cmd)):
        rec["error"] = "arm cmd must be a non-empty list of strings"
        return rec
    t0 = time.monotonic()
    res = _run_bounded(cmd, arm_dir, env, budget_s)
    rec["wall_s"] = round(time.monotonic() - t0, 3)
    rec["exit_code"], rec["timed_out"], rec["error"] = res["exit_code"], res["timed_out"], res["error"]
    try:
        _write_new(out_dir / f"{name}.stdout.txt", res["stdout"])
        _write_new(out_dir / f"{name}.stderr.txt", res["stderr"])
    except OSError as exc:
        return _harness_failure(rec, "artifact_write", exc)
    errors = [rec["error"]] if rec["error"] else []
    if not spec_file.is_file() or _sha256(spec_file.read_bytes()) != frozen["spec_sha"]:
        errors.append("frozen spec modified during arm")
    end = _tree_entries(arm_dir)
    rec["output"] = "DIFF" if _entries_sha(end) != start_tree else "NONE"
    declared = set(frozen["solution_files"])
    ignored = sorted(os.fsdecode(k) for k in start.keys() | end.keys()
                     if start.get(k) != end.get(k) and os.fsdecode(k) not in declared)
    rec["ignored_change_count"], rec["ignored_change_paths"] = len(ignored), ignored[:20]
    if usage_file.is_file():
        rec["usage_source"] = "producer-reported"
        try:
            usage = json.loads(usage_file.read_text(encoding="utf-8"))
            if not isinstance(usage, dict):
                raise ValueError("usage file is not a JSON object")
            for k in ("tokens", "cost_usd"):
                if k in usage:
                    v = usage[k]
                    if not (_finite(v) and v >= 0):
                        raise ValueError(f"{k} must be a finite non-negative number, "
                                         f"got {_short(v)}")
                    rec[k] = v
        except (ValueError, OSError) as exc:
            errors.append(f"invalid producer-reported usage: {exc}")
    tampered = []
    for rel, sha in frozen["check_files"].items():
        p = arm_dir / rel
        try:
            intact = (not p.is_symlink() and p.is_file() and _sha256(p.read_bytes()) == sha
                      and bool(p.lstat().st_mode & stat.S_IXUSR) == frozen["_check_exec"][rel])
        except OSError:
            intact = False
        if not intact:
            tampered.append(rel)
    if tampered:
        rec["accept"] = "REJECTED"
        errors.append("pinned check file(s) modified by arm: " + ", ".join(sorted(tampered)))
    rec["error"] = "; ".join(errors) or None
    if rec["timed_out"] or rec["error"] or rec["accept"] == "REJECTED":
        return rec
    # Independent acceptance: a SEPARATE process, only on an in-budget, intact arm,
    # in a fresh tree that holds the snapshot plus ONLY the declared solution files.
    accept_dir = out_dir / f"{name}.accept-tree"
    try:  # never score against a pre-existing tree; a collision is kept, not cleared
        rec["projected"], reject, perr = _project(frozen, arm_dir, accept_dir)
    except OSError as exc:
        rec["projected"] = []
        return _harness_failure(rec, "acceptance_projection", exc)
    if reject or perr:
        rec["accept"] = "REJECTED" if reject else "ERROR"
        rec["error"] = "acceptance boundary: " + (reject or perr)
        return rec
    rec["accept_tree_sha"] = _tree_sha(accept_dir)
    a = _run_bounded(frozen["accept_cmd"], accept_dir, dict(os.environ), budget_s)
    try:
        _write_new(out_dir / f"{name}.accept.txt", a["stdout"] + a["stderr"])
    except OSError as exc:
        return _harness_failure(rec, "artifact_write", exc)
    if a["error"] or a["timed_out"]:
        rec["accept"] = "ERROR"
        rec["error"] = "accept: " + (a["error"] or f"timed out after {budget_s}s")
    else:
        rec["accept_exit"] = a["exit_code"]
        if a["exit_code"] < 0:  # POSIX: killed by signal -> the check never completed
            rec["accept"] = "ERROR"
            rec["error"] = f"accept: killed by signal {-a['exit_code']}, not a completed FAIL"
        else:
            rec["accept"] = "PASS" if a["exit_code"] == 0 else "FAIL"
    return rec


# --------------------------------------------------------------------------
# pure comparison (no I/O) -- the only place a verdict is formed
# --------------------------------------------------------------------------
def compare(record) -> dict:
    out = {"verdict": None, "winner": None, "reasons": [],
           "quality_improvement": "UNMEASURED",
           "note": ("acceptance-only comparison of scripted/offline arms; usage figures are "
                    "producer-reported, not independently measured; not model-efficacy evidence"),
           "throughput_wall_s": {}}

    def invalid(msg: str) -> dict:
        out["verdict"] = "INVALID_COMPARISON"
        out["reasons"].append(msg)
        return out

    if not isinstance(record, dict):
        return invalid(f"record is not a JSON object: {type(record).__name__}")
    arms = {a: record.get(a) for a in ARMS}
    missing = [a for a, v in arms.items() if not isinstance(v, dict)]
    if missing:
        return invalid("missing arm: " + ", ".join(missing))
    for key in CONTRACT_KEYS:
        vals = [arms[a].get(key) for a in ARMS]
        if key == "budget_s":
            ok = all(_budget_ok(v) for v in vals)
        else:
            ok = all(_nonempty_str(v) for v in vals)
        if not ok:
            invalid(f"{key} missing or invalid")
        elif vals[0] != vals[1]:
            invalid(f"{key} differs between arms")
    if out["verdict"]:
        return out
    budget = arms["baseline"]["budget_s"]
    reasons = out["reasons"]
    for a in ARMS:
        r = arms[a]
        wall, ec, acc, ae = r.get("wall_s"), r.get("exit_code"), r.get("accept"), r.get("accept_exit")
        out["throughput_wall_s"][a] = wall if _finite(wall) else None
        timed_out = r.get("timed_out")
        if timed_out is True:
            reasons.append(f"{a}: over budget ({_short(wall)}s > {budget}s)")
        elif timed_out is not False:
            reasons.append(f"{a}: timed_out flag missing or invalid")
        if r.get("error"):
            err = r["error"]
            reasons.append(f"{a}: error {err if isinstance(err, str) else _short(err)}")
        if not _finite(wall) or wall < 0:
            reasons.append(f"{a}: wall_s missing or not a finite non-negative number")
        elif wall > budget and timed_out is not True:
            reasons.append(f"{a}: wall_s {wall}s exceeds budget {budget}s")
        if not (isinstance(ec, int) and not isinstance(ec, bool)):
            reasons.append(f"{a}: exit_code missing or invalid")
        elif ec != 0:
            reasons.append(f"{a}: arm exited non-zero ({_short(ec)})")
        if acc not in ("PASS", "FAIL"):
            reasons.append(f"{a}: acceptance {acc}")
        elif not (isinstance(ae, int) and not isinstance(ae, bool)):
            reasons.append(f"{a}: accept_exit missing or invalid")
        elif ae < 0:
            reasons.append(f"{a}: acceptance killed by signal {_short(-ae)}; "
                           "execution failure, not a completed FAIL")
        elif (acc == "PASS") != (ae == 0):
            reasons.append(f"{a}: accept {acc} inconsistent with accept_exit {_short(ae)}")
        for k in ("tokens", "cost_usd"):
            v = r.get(k)
            if v != UNKNOWN and not (_finite(v) and v >= 0):
                reasons.append(f"{a}: {k} invalid producer-reported usage {_short(v)}")
    hf = record.get("harness_failure")
    if hf is not None:
        reasons.append(f"harness failure during run: {_short(hf, 200)}")
    integ = record.get("input_integrity")
    if not isinstance(integ, dict) or integ.get("ok") is not True:
        reasons.append("input integrity evidence missing, invalid, or failed during run")
    if reasons:
        out["verdict"] = "UNSCORED"
        return out
    acc = {a: arms[a]["accept"] for a in ARMS}
    if acc["baseline"] == acc["candidate"]:
        out["verdict"] = "TIE_ON_ACCEPTANCE"
        return out
    out["verdict"] = "WINNER_BY_ACCEPTANCE"
    out["winner"] = "candidate" if acc["candidate"] == "PASS" else "baseline"
    return out


# --------------------------------------------------------------------------
# orchestration + CLI
# --------------------------------------------------------------------------
def run_bench(repo: pathlib.Path, spec_path: pathlib.Path, budget_s,
              baseline_cmd: list[str], candidate_cmd: list[str], accept_cmd: list[str],
              out_dir: pathlib.Path, check_files: list[str], solution_files: list[str]) -> dict:
    frozen = freeze_inputs(repo, spec_path, budget_s, accept_cmd, check_files, solution_files)
    out_dir = _validate_out_dir(out_dir, frozen)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "frozen").mkdir()
    (out_dir / "frozen" / "spec").write_bytes(frozen["_spec"])
    public = {k: v for k, v in frozen.items() if not k.startswith("_")}
    record: dict = {"frozen": public, "budget_s": budget_s, "harness_failure": None}
    for name, cmd in (("baseline", baseline_cmd), ("candidate", candidate_cmd)):
        hf = record["harness_failure"]
        if hf is not None:  # terminal: a later arm never runs after a harness failure
            record[name] = _arm_record(name, cmd, frozen)
            record[name]["error"] = f"not run: harness failure in {hf['arm']} ({hf['stage']})"
            continue
        record[name] = run_arm(name, cmd, frozen, out_dir)
        if record[name]["failure"] is not None:
            record["harness_failure"] = {"arm": name, **record[name]["failure"]}
    record["input_integrity"] = _input_integrity(frozen)
    record["comparison"] = compare(record)
    _persist_record(out_dir, record)
    return record


def _print_verdict(v: dict) -> None:
    print(f"verdict: {v['verdict']}  winner: {v['winner']}")
    print(f"quality_improvement: {v['quality_improvement']}")
    print(f"throughput_wall_s: {json.dumps(v['throughput_wall_s'])}")
    for r in v["reasons"]:
        print(f"  - {r}")
    print(v["note"])


def _rc(v: dict) -> int:
    return 0 if v["verdict"] in ("WINNER_BY_ACCEPTANCE", "TIE_ON_ACCEPTANCE") else 2


def _load_json(path: str):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="freeze inputs, run both arms in separate copies, score externally")
    run.add_argument("--config", required=True,
                     help="JSON: repo, spec, budget_s, baseline_cmd, candidate_cmd, accept_cmd, "
                          "check_files, solution_files")
    run.add_argument("--out", required=True, help="output directory for copies and record.json")
    cmp_ = sub.add_parser("compare", help="re-derive the verdict from a saved record.json")
    cmp_.add_argument("--record", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "run":
        cfg, err = _load_json(args.config)
        if err or not isinstance(cfg, dict):
            print(f"INVALID_CONFIG: {err or 'config is not a JSON object'}")
            return 2
        need = ("repo", "spec", "budget_s", "baseline_cmd", "candidate_cmd", "accept_cmd",
                "check_files", "solution_files")
        missing = [k for k in need if k not in cfg]
        if missing:
            print(f"INVALID_CONFIG: missing keys {missing}")
            return 2
        base = pathlib.Path(args.config).resolve().parent
        try:
            rec = run_bench(repo=base / str(cfg["repo"]), spec_path=base / str(cfg["spec"]),
                            budget_s=cfg["budget_s"], baseline_cmd=cfg["baseline_cmd"],
                            candidate_cmd=cfg["candidate_cmd"], accept_cmd=cfg["accept_cmd"],
                            out_dir=pathlib.Path(args.out), check_files=cfg["check_files"],
                            solution_files=cfg["solution_files"])
        except BenchInputError as exc:
            print(f"REJECTED_INPUT: {exc}")
            return 2
        except BenchRecordError as exc:
            print(f"RECORD_NOT_WRITTEN: {exc}; no verdict issued")
            return 2
        _print_verdict(rec["comparison"])
        return _rc(rec["comparison"])
    rec, err = _load_json(args.record)
    v = compare(rec) if err is None else compare(None)
    if err:
        v["reasons"].insert(0, f"record unreadable: {err}")
    _print_verdict(v)
    return _rc(v)


if __name__ == "__main__":
    sys.exit(main())
