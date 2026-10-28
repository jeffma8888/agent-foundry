"""Black-box behaviour tests for iter 483 -- WEAK_TEST_ROOT_DIRS extended with
"test" so the weak-test scanner walks Node.js-convention test/ directories
instead of falling back to a full-repo walk.

Spec: products/_platform/state/iter-483/pm.md, Expected Behaviors 1-7.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-483 PM spec's Expected
Behaviors, the conventions of tests/ (test_iter170_behavior.py's shape), and the
product's OBSERVABLE surface -- importing the module and CALLING the public
functions. The implementation source of foundry.py / dispatcher.py, the
engineer's notes (engineer.md), the reviewer's notes (reviewer.md),
IMPLEMENTATION.patch and git diff were NOT read.

Offline and deterministic: every fixture is built in tmp_path, the real foundry
repo is never mutated, and the only subprocess is the fresh-interpreter import
probe.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

THIS_ITER = 483

EXPECTED_ROOTS = ("tests", "test")
EXPECTED_GLOBS = ("test_*.py", "*_test.py")

_WEAK_SRC = "def test_x():\n    pass\n"


# --------------------------------------------------------------------------
# helpers (mirror iter-170 conventions)
# --------------------------------------------------------------------------
def _repo(tmp_path, *rels, name="repo"):
    repo = tmp_path / name
    repo.mkdir(parents=True, exist_ok=True)
    for rel in rels:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_WEAK_SRC)
    return repo


def _gather(repo):
    out = foundry._gather_weak_test_files(str(repo))
    assert isinstance(out, list), f"return type must be list, got {type(out).__name__}"
    assert all(isinstance(p, pathlib.Path) for p in out)
    assert out == sorted(out), f"must be sorted: {out!r}"
    assert len(set(out)) == len(out), f"must be deduped: {out!r}"
    return out


def _rel(repo, paths):
    repo = pathlib.Path(repo)
    return [pathlib.Path(p).relative_to(repo).as_posix() for p in paths]


# ==========================================================================
# Behavior 1 -- WEAK_TEST_ROOT_DIRS contains both "tests" and "test"
# ==========================================================================
def test_b1_roots_tuple_contains_both_tests_and_test():
    roots = foundry.WEAK_TEST_ROOT_DIRS
    assert isinstance(roots, tuple), f"must be a tuple, got {type(roots).__name__}"
    assert roots == EXPECTED_ROOTS, f"expected {EXPECTED_ROOTS!r}, got {roots!r}"
    assert "tests" in roots, "'tests' must be an element"
    assert "test" in roots, "'test' must be an element"


# ==========================================================================
# Behavior 2 -- test/-only product is walked without the full-repo fallback
# ==========================================================================
def test_b2_test_only_product_walks_test_dir(tmp_path):
    repo = _repo(tmp_path, "test/test_a.py", "src/test_b.py", "lib/test_c.py")
    assert not (repo / "tests").exists(), "precondition: no tests/ dir"
    assert (repo / "test").is_dir(), "precondition: test/ dir exists"
    got = _rel(repo, _gather(repo))
    assert got == ["test/test_a.py"], (
        f"test/-only product must walk test/ not the whole repo, got {got}"
    )


def test_b2_test_only_product_with_nested_files(tmp_path):
    repo = _repo(tmp_path, "test/unit/test_deep.py", "other/test_stray.py")
    got = _rel(repo, _gather(repo))
    assert got == ["test/unit/test_deep.py"], (
        f"nested files under test/ must be found, got {got}"
    )


# ==========================================================================
# Behavior 3 -- dual-root product walks both and deduplicates
# ==========================================================================
def test_b3_dual_root_walks_both_and_deduplicates(tmp_path):
    repo = _repo(tmp_path,
                 "tests/test_py.py",
                 "test/test_node.py",
                 "src/test_stray.py")
    assert (repo / "tests").is_dir() and (repo / "test").is_dir()
    got = _rel(repo, _gather(repo))
    assert got == ["test/test_node.py", "tests/test_py.py"], (
        f"both roots must be walked, got {got}"
    )
    assert "src/test_stray.py" not in got, "stray file outside both roots must be excluded"


def test_b3_overlapping_file_in_both_roots_is_deduped(tmp_path):
    repo = _repo(tmp_path,
                 "tests/test_a.py",
                 "test/test_b.py")
    got = _rel(repo, _gather(repo))
    assert len(got) == len(set(got)), f"result must be deduped: {got}"
    assert "test/test_b.py" in got
    assert "tests/test_a.py" in got


# ==========================================================================
# Behavior 4 -- tests/-only product is unchanged
# ==========================================================================
def test_b4_tests_only_product_unchanged(tmp_path):
    repo = _repo(tmp_path, "tests/test_a.py", "state/test_b.py")
    assert not (repo / "test").exists(), "precondition: no test/ dir"
    got = _rel(repo, _gather(repo))
    assert got == ["tests/test_a.py"], (
        f"tests/-only product must work as before, got {got}"
    )


# ==========================================================================
# Behavior 5 -- neither test/ nor tests/ -> full-repo fallback
# ==========================================================================
def test_b5_no_matching_root_falls_back_to_full_repo(tmp_path):
    repo = _repo(tmp_path, "test_a.py", "pkg/test_b.py")
    assert not (repo / "tests").exists() and not (repo / "test").exists()
    got = _rel(repo, _gather(repo))
    assert got == ["pkg/test_b.py", "test_a.py"], (
        f"with no matching roots the full-repo fallback must fire, got {got}"
    )


# ==========================================================================
# Behavior 6 -- glob patterns unchanged in the new root
# ==========================================================================
def test_b6_globs_unchanged():
    assert foundry.WEAK_TEST_GLOBS == EXPECTED_GLOBS, (
        f"globs must be unchanged: {foundry.WEAK_TEST_GLOBS!r}"
    )


def test_b6_both_globs_apply_under_test_root(tmp_path):
    repo = _repo(tmp_path,
                 "test/test_a.py",
                 "test/b_test.py",
                 "test/helper.py",
                 "test/not_a_test.txt")
    (repo / "test" / "not_a_test.txt").write_text("not python")
    got = _rel(repo, _gather(repo))
    assert "test/test_a.py" in got, "test_*.py glob must match"
    assert "test/b_test.py" in got, "*_test.py glob must match"
    assert "test/helper.py" not in got, "non-matching file must be excluded"


def test_b6_no_false_positives_from_test_root(tmp_path):
    repo = _repo(tmp_path, "test/test_real.py")
    (repo / "test" / "README.md").write_text("# readme")
    (repo / "test" / "conftest.py").write_text("import pytest")
    got = _rel(repo, _gather(repo))
    assert got == ["test/test_real.py"], (
        f"only glob-matched files should appear, got {got}"
    )


# ==========================================================================
# Behavior 7 -- import + suite (the suite run is the full-suite gate)
# ==========================================================================
def test_b7_modules_import_in_a_fresh_interpreter():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
