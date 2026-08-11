"""Black-box behaviour tests for iter 154 -- the read-only-CLI tree guard in
tests/test_iter61_behavior.py stops byte-walking the whole real products/ tree and
compares a BOUNDED, GIT-REPORTED snapshot instead.

Spec: products/_platform/state/iter-154/pm.md, Expected Behaviors 1-8.

  1. `_git_visible_snapshot(dir[, repo_root])` exists at module level and returns a
     value supporting == / != against another call's result.
  2. BOUNDED, and -- strictly stronger -- DOES NOT SCALE: two hermetic tmp_path repos
     differing 75x in gitignored files-on-disk snapshot to repr() strings of the SAME
     length, both <= 20,000 chars (the byte-walk it replaces yields > 40,000,000).
     The real products/ tree is still asserted bounded, now UNCONDITIONALLY.
     [HOTFIX iter 155] This behavior's non-vacuity precondition used to be a file
     COUNT over the ambient products/ tree, which holds thousands of files here but
     only 4 TRACKED ones -- so the oracle passed on this machine and failed in the
     fresh clone post-release verification builds. The fixture is now built by the
     test, so the floor cannot depend on any ambient tree.
  3. CHEAP: 20 consecutive real-tree calls finish in < 5.0 s wall clock.
  4. KNOWN-POSITIVE: a new git-visible (not-ignored) file makes it compare UNEQUAL.
  5. KNOWN-POSITIVE: an in-place edit of a committed tracked file -> UNEQUAL.
  6. KNOWN-POSITIVE: a staged addition (`git add`) -> UNEQUAL.
  7. KNOWN-NEGATIVE: gitignored runtime state (state/iter-999/out.txt) -> EQUAL.
     This is the exact case that turned the guard red this iteration.
  8. The live guard is rewired: test_b9_cli_writes_nothing_to_repo_tree passes, its
     before/after come from `_git_visible_snapshot`, no call in that file passes the
     real products/ dir to `_snapshot_tree`, and the now-unused `_snapshot_tree`
     definition is deleted from tests/test_iter61_behavior.py.

  Plus a NON-VACUITY FLOOR the spec does not name but that behaviors 4-7 rest on:
  a snapshot must actually reflect the repo it was asked about, so two DIFFERENT
  hermetic repos must not snapshot alike. Without it, a helper that silently
  returned a constant (git off PATH, a wrong pathspec, an ambient excludesFile)
  would satisfy every EQUAL assertion vacuously.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-154 PM spec's Expected
Behaviors, the tests/ conventions (tests/test_iter145_behavior.py's cross-module
import of a sibling test module, tests/test_iter132_behavior.py's AST-based
self-oracles and its practice of CALLING the test functions under test), and the
OBSERVABLE behaviour of the module under test -- importing it and CALLING the public
helper. The engineer's engineer.md, the reviewer's reviewer.md and `git diff` were
NOT read. Behaviors 4-7 build their own hermetic git repo under pytest's tmp_path
with LOCAL user.email / user.name / commit.gpgsign / core.excludesFile so `git
commit` and the ignore rules cannot depend on ambient config; nothing here writes,
creates or deletes any file inside the real products/ tree, and behavior 8 proves
that two-sidedly on the REAL tree.

PROVENANCE NOTE (iter 155): the isolation contract above describes the original
iter-154 authorship, which still holds for every test here EXCEPT behavior 2 --
`test_b2_snapshot_is_bounded_not_a_byte_walk` and its two fixture helpers were rebuilt
by the iter-155 ENGINEER under that iteration's hotfix spec, because the oracle as
written could only pass on a populated working tree. The independent oracles for that
rebuild are the iter-155 tester's, in tests/test_iter155_behavior.py.
"""
import ast
import os
import pathlib
import subprocess
import sys
import time

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tests"))
sys.path.insert(0, str(_ROOT))
import test_iter61_behavior as t61  # noqa: E402

_T61_SRC = _ROOT / "tests" / "test_iter61_behavior.py"
_REAL_PRODUCTS = _ROOT / "products"
_REPR_CEILING = 20000
_CALLS = 20
_CALLS_BUDGET_S = 5.0
# behavior 2's hermetic fixture sizes: a 75x spread in files-on-disk that the snapshot
# must not notice at all. Measured build cost of the pair: 0.40 s (0.01 s + 0.39 s).
_BULK_SUBDIR = "state/bulk"
_SMALL_FILL = 40
_LARGE_FILL = 3000
_SMALL_CEILING = 50
_LARGE_FLOOR = 3000


def _snap():
    """The helper under test, fetched by NAME at call time (behavior 1)."""
    fn = getattr(t61, "_git_visible_snapshot", None)
    assert callable(fn), (
        "iter-154 behavior 1: tests/test_iter61_behavior.py must define a "
        "module-level callable _git_visible_snapshot"
    )
    return fn


def _git(root):
    def run(*args):
        return subprocess.run(
            ("git",) + args, cwd=str(root), capture_output=True, text=True, check=False
        )

    return run


def _hermetic_repo(root, tracked_name="tracked.txt"):
    """A throwaway git repo under tmp_path: committed .gitignore (only rule
    `state/`) + one committed tracked file. All config is LOCAL."""
    root.mkdir(parents=True, exist_ok=True)
    g = _git(root)
    assert g("init", "-q").returncode == 0, "git init failed in tmp repo"
    (root / ".empty_excludes").write_text("", encoding="utf-8")
    for key, val in (
        ("user.email", "iter154@example.invalid"),
        ("user.name", "iter154 tester"),
        ("commit.gpgsign", "false"),
        ("core.excludesFile", str(root / ".empty_excludes")),
    ):
        assert g("config", key, val).returncode == 0, f"git config {key} failed"
    (root / ".gitignore").write_text("state/\n.empty_excludes\n", encoding="utf-8")
    (root / tracked_name).write_text("original\n", encoding="utf-8")
    assert g("add", ".gitignore", tracked_name).returncode == 0, "git add failed"
    committed = g("commit", "-q", "-m", "seed")
    assert committed.returncode == 0, f"git commit failed: {committed.stderr!r}"
    clean = g("status", "--porcelain", "--untracked-files=all")
    assert clean.stdout.strip() == "", f"tmp repo not clean after seed: {clean.stdout!r}"
    return g


# ---------------------------------------------------------------- behavior 1
def test_b1_helper_exists_and_results_compare(tmp_path):
    snap = _snap()
    a = snap(_REAL_PRODUCTS)
    b = snap(_REAL_PRODUCTS)
    assert (a == b) is True, "two snapshots of an unchanged tree must compare EQUAL"
    assert (a != b) is False, "!= must be the negation of == for snapshot values"
    # the optional SECOND argument names the git repository root
    root = tmp_path / "repo_b1"
    _hermetic_repo(root)
    two_arg = snap(root, root)
    assert two_arg == snap(root, root), "the 2-arg form must be callable and stable"
    # default second argument is the foundry checkout: 1-arg on a real subdir works
    assert snap(_REAL_PRODUCTS) == snap(_REAL_PRODUCTS)


# ---------------------------------------------------------------- behavior 2
def _count_files(root: pathlib.Path) -> int:
    """Count the files under ``root``.

    WHY os.walk and not a recursive-glob one-liner: the recursive walk this file used
    to run went over the ambient products/ tree, which is the defect iter 155 removed,
    and the hotfix's own oracle asserts that helper name no longer appears here. os.walk
    keeps the count explicit and scoped to a fixture the test itself built.
    """
    return sum(len(files) for _, _, files in os.walk(root))


def _fill_ignored_state(root: pathlib.Path, count: int) -> tuple[int, str]:
    """Write ``count`` bulk files under a hermetic repo's committed-ignored ``state/``.

    Returns the resulting on-disk file count under ``state/`` plus a repo-relative
    probe path, so the caller can PROVE the bulk is gitignored instead of assuming it.

    WHY the fill must land under ``state/`` only: ``_hermetic_repo`` asserts the seeded
    tree is CLEAN and ``state/`` is the sole rule in its committed ``.gitignore``. Bulk
    written anywhere else would be reported by ``git status``, grow the snapshot, and
    fail the does-not-scale assertion for a real reason in the wrong test.
    """
    bulk = root / _BULK_SUBDIR
    bulk.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (bulk / f"bulk_{i:05d}.txt").write_text("x" * 64, encoding="utf-8")
    return _count_files(root / "state"), f"{_BULK_SUBDIR}/bulk_00000.txt"


def test_b2_snapshot_is_bounded_not_a_byte_walk(tmp_path):
    """BOUNDED, and -- strictly stronger -- the snapshot does not SCALE with the tree.

    HOTFIX (iter 155): the precondition here used to count files under the ambient
    products/ tree. Those files are gitignored runtime state that exists only in a
    populated working tree, while the fresh clone post-release verification builds
    tracks exactly 4 -- so the oracle passed here and failed on the verifier. Building
    both trees makes the non-vacuity floor ours to guarantee AND lets us vary the
    on-disk count on purpose, which proves the claim that matters: a 75x difference in
    files-on-disk moves the snapshot's size by ZERO characters.
    """
    snap = _snap()
    small = tmp_path / "repo_b2_small"
    large = tmp_path / "repo_b2_large"
    g_small = _hermetic_repo(small)
    g_large = _hermetic_repo(large)
    n_small, probe_small = _fill_ignored_state(small, _SMALL_FILL)
    n_large, probe_large = _fill_ignored_state(large, _LARGE_FILL)

    # the non-vacuity floor comes from fixtures WE built, never from an ambient tree
    assert n_small <= _SMALL_CEILING, (
        f"fixture: the small repo must hold <={_SMALL_CEILING} files under state/, "
        f"saw {n_small}"
    )
    assert n_large >= _LARGE_FLOOR, (
        f"fixture: the large repo must hold >={_LARGE_FLOOR} files under state/, "
        f"saw {n_large}"
    )

    # ... and the bulk is genuinely INVISIBLE to git in BOTH repos, not merely absent
    for label, g, probe in (
        ("small", g_small, probe_small),
        ("large", g_large, probe_large),
    ):
        ignored = g("check-ignore", "-q", probe)
        assert ignored.returncode == 0, (
            f"precondition: {probe} must be gitignored in the {label} fixture, so the "
            f"fill cannot reach the snapshot through git"
        )

    small_text = repr(snap(small, small))
    large_text = repr(snap(large, large))
    assert len(large_text) <= _REPR_CEILING, (
        f"iter-154 behavior 2: repr(_git_visible_snapshot(...)) is {len(large_text)} "
        f"chars at {n_large} files on disk, over the {_REPR_CEILING}-char ceiling -- "
        f"it is not bounded"
    )
    assert len(large_text) == len(small_text), (
        f"iter-154 behavior 2: the snapshot must not SCALE with the tree it describes "
        f"-- {n_small} vs {n_large} files on disk gave {len(small_text)} vs "
        f"{len(large_text)} repr chars"
    )

    # The real-tree bound survives, but UNCONDITIONALLY: it holds at 4 tracked files
    # in a fresh clone and at thousands in a populated working tree alike.
    real_text = repr(snap(_REAL_PRODUCTS))
    assert len(real_text) <= _REPR_CEILING, (
        f"iter-154 behavior 2: repr(_git_visible_snapshot(products/)) is "
        f"{len(real_text)} chars, over the {_REPR_CEILING}-char ceiling -- "
        f"it is not bounded"
    )


# ---------------------------------------------------------------- behavior 3
def test_b3_snapshot_is_cheap():
    snap = _snap()
    start = time.monotonic()
    for _ in range(_CALLS):
        snap(_REAL_PRODUCTS)
    elapsed = time.monotonic() - start
    assert elapsed < _CALLS_BUDGET_S, (
        f"iter-154 behavior 3: {_CALLS} real-tree snapshots took {elapsed:.2f}s, "
        f"over the {_CALLS_BUDGET_S}s budget"
    )


# ------------------------------------------------- non-vacuity floor (4-7 rest on it)
def test_nonvacuity_two_distinct_repos_do_not_snapshot_alike(tmp_path):
    snap = _snap()
    one = tmp_path / "repo_one"
    two = tmp_path / "repo_two"
    _hermetic_repo(one, tracked_name="alpha.txt")
    _hermetic_repo(two, tracked_name="beta.txt")
    assert snap(one, one) != snap(two, two), (
        "non-vacuity floor: a snapshot that cannot distinguish two different repos "
        "is a constant, and every EQUAL assertion below would pass vacuously"
    )


# ---------------------------------------------------------------- behavior 4
def test_b4_new_git_visible_file_is_caught(tmp_path):
    snap = _snap()
    root = tmp_path / "repo_b4"
    _hermetic_repo(root)
    before = snap(root, root)
    (root / "brand_new.txt").write_text("appears in a ship diff\n", encoding="utf-8")
    after = snap(root, root)
    assert before != after, (
        "iter-154 behavior 4: a NEW not-ignored file must make the snapshot UNEQUAL"
    )


# ---------------------------------------------------------------- behavior 5
def test_b5_in_place_edit_of_tracked_file_is_caught(tmp_path):
    snap = _snap()
    root = tmp_path / "repo_b5"
    _hermetic_repo(root)
    before = snap(root, root)
    with (root / "tracked.txt").open("a", encoding="utf-8") as fh:
        fh.write("mutated in place\n")
    after = snap(root, root)
    assert before != after, (
        "iter-154 behavior 5: an in-place edit of a committed tracked file must "
        "make the snapshot UNEQUAL"
    )


# ---------------------------------------------------------------- behavior 6
def test_b6_staged_addition_is_caught(tmp_path):
    snap = _snap()
    root = tmp_path / "repo_b6"
    g = _hermetic_repo(root)
    before = snap(root, root)
    (root / "staged.txt").write_text("index mutation\n", encoding="utf-8")
    assert g("add", "staged.txt").returncode == 0, "git add failed"
    after = snap(root, root)
    assert before != after, (
        "iter-154 behavior 6: a STAGED addition must make the snapshot UNEQUAL"
    )


# ---------------------------------------------------------------- behavior 7
def test_b7_gitignored_runtime_state_is_invisible(tmp_path):
    snap = _snap()
    root = tmp_path / "repo_b7"
    g = _hermetic_repo(root)
    before = snap(root, root)
    state = root / "state" / "iter-999"
    state.mkdir(parents=True)
    out = state / "out.txt"
    out.write_text("x" * 4096, encoding="utf-8")
    with out.open("a", encoding="utf-8") as fh:
        fh.write("y" * 4096)
    after = snap(root, root)
    # the planted file really is ignored by the COMMITTED .gitignore, not merely absent
    ignored = g("check-ignore", "-q", "state/iter-999/out.txt")
    assert ignored.returncode == 0, "precondition: state/iter-999/out.txt must be gitignored"
    assert out.exists() and out.stat().st_size > 8000, "precondition: the write happened"
    assert before == after, (
        "iter-154 behavior 7: gitignored runtime state under state/ must be INVISIBLE "
        "to the guard -- this is the exact case that turned the guard red in iter 154"
    )


# ---------------------------------------------------------------- behavior 8
def _t61_tree():
    return ast.parse(_T61_SRC.read_text(encoding="utf-8"))


def _called_names(node):
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = sub.func
            if isinstance(fn, ast.Name):
                out.append(fn.id)
            elif isinstance(fn, ast.Attribute):
                out.append(fn.attr)
    return out


def test_b8_live_guard_is_rewired_and_snapshot_tree_is_gone(tmp_path, monkeypatch):
    tree = _t61_tree()

    # (a) the now-unused byte-walk definition is DELETED from the file
    defined = [
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert "_snapshot_tree" not in defined, (
        "iter-154 behavior 8: the now-unused _snapshot_tree definition must be "
        "deleted from tests/test_iter61_behavior.py"
    )
    assert not hasattr(t61, "_snapshot_tree"), (
        "iter-154 behavior 8: _snapshot_tree must no longer be importable from the module"
    )

    # (b) no call anywhere in that file passes the real products/ dir to _snapshot_tree
    assert "_snapshot_tree" not in _called_names(tree), (
        "iter-154 behavior 8: tests/test_iter61_behavior.py must contain NO call to "
        "_snapshot_tree (its only consumer was the rewired guard)"
    )

    # (c) the guard's before/after values come from _git_visible_snapshot
    guard = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef)
            and n.name == "test_b9_cli_writes_nothing_to_repo_tree"
        ),
        None,
    )
    assert guard is not None, "test_b9_cli_writes_nothing_to_repo_tree must still exist"
    assigned = {}
    for stmt in ast.walk(guard):
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
            fn = stmt.value.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name):
                    assigned[tgt.id] = name
    for var in ("before", "after"):
        assert assigned.get(var) == "_git_visible_snapshot", (
            f"iter-154 behavior 8: the guard's `{var}` must be assigned from "
            f"_git_visible_snapshot, saw {assigned.get(var)!r}"
        )

    # (d) the live guard PASSES, and running it leaves the REAL products/ tree
    #     git-identical (the real-tree two-sided control for behavior 7)
    snap = _snap()
    real_before = snap(_REAL_PRODUCTS)
    t61.test_b9_cli_writes_nothing_to_repo_tree(tmp_path, monkeypatch)
    real_after = snap(_REAL_PRODUCTS)
    assert real_before == real_after, (
        "running the live guard must leave the real products/ tree git-identical"
    )


# ------------------------------------------------- Acceptance Criteria oracles
def test_ac_control_path_sources_still_import():
    """The control path still imports cleanly (this iteration is test-owned).

    NOTE deliberately NOT asserted here: a `git diff --quiet ... foundry.py`
    byte-unchanged check. tests/test_iter54_behavior.py's
    test_b8_no_surviving_foundry_py_byte_unchanged_assertion FORBIDS it repo-wide
    (foundry.py is routinely extended additively, so such an assertion is a latent
    suite-breaker), and its sibling test_b8_control_path_and_guard_scripts_byte_unchanged
    already freezes dispatcher.py + the guard scripts. Adding one here duplicated the
    live guard AND broke it -- caught by the full suite in this stage.
    """
    rc = subprocess.run(
        (sys.executable, "-c", "import foundry, dispatcher"),
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert rc.returncode == 0, f"import probe failed: {rc.stderr[-800:]!r}"


def test_ac_roadmap_records_present():
    """The PM's Done-ledger row, archive bullet and de-listing item (r) ship."""
    road = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    arch = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text(encoding="utf-8")
    assert "- iter 154 " in road, "PLATFORM_ROADMAP.md must carry the `- iter 154 ` Done row"
    assert "- **iter 154 " in arch, (
        "PLATFORM_ROADMAP_ARCHIVE.md must carry the `- **iter 154 ` bullet"
    )
    assert "(r)" in road, "PLATFORM_ROADMAP.md must carry the new de-listing item (r)"


def test_ac_no_real_products_writes_in_this_module():
    """This module names no real products/ path it could write to (self-audit)."""
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    writers = {"write_text", "write_bytes", "mkdir", "touch", "unlink", "rmtree", "open"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in writers:
                seg = ast.dump(node)
                assert "_REAL_PRODUCTS" not in seg, (
                    f"a write call in this module targets the real products/ tree: {seg[:200]}"
                )
