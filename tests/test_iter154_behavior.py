"""Black-box behaviour tests for iter 154 -- the read-only-CLI tree guard in
tests/test_iter61_behavior.py stops byte-walking the whole real products/ tree and
compares a BOUNDED, GIT-REPORTED snapshot instead.

Spec: products/_platform/state/iter-154/pm.md, Expected Behaviors 1-8.

  1. `_git_visible_snapshot(dir[, repo_root])` exists at module level and returns a
     value supporting == / != against another call's result.
  2. BOUNDED: repr() of a real-tree snapshot is <= 20,000 chars (the byte-walk it
     replaces yields > 40,000,000).
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
"""
import ast
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
def test_b2_snapshot_is_bounded_not_a_byte_walk():
    snap = _snap()
    n_files = sum(1 for p in _REAL_PRODUCTS.rglob("*") if p.is_file())
    assert n_files > 6000, (
        f"precondition for behavior 2: products/ should hold >6000 files, saw {n_files}"
    )
    text = repr(snap(_REAL_PRODUCTS))
    assert len(text) <= _REPR_CEILING, (
        f"iter-154 behavior 2: repr(_git_visible_snapshot(products/)) is {len(text)} "
        f"chars, over the {_REPR_CEILING}-char ceiling -- it is not bounded"
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
