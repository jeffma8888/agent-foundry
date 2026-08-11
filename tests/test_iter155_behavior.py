"""Black-box behaviour tests for iter 155 -- the HOTFIX that rebuilds the bounded-snapshot
oracle `test_b2_snapshot_is_bounded_not_a_byte_walk` on a hermetic fixture it BUILDS,
instead of asserting that the ambient, gitignored `products/` tree holds >6000 files.

Under test: `tests/test_iter154_behavior.py` -- specifically its behaviour-2 oracle, the
`_fill_ignored_state` fixture builder it now uses, and the non-vacuity floor test that the
oracle's `<=` / `==` assertions rest on. The DEFECT being fixed is that the old
precondition was true only in this machine's working tree (6584 files, almost all
gitignored runtime state) and false in the fresh clone that post-release verification
builds (`git ls-files products/` == 4), so the oracle passed here and failed there.

THE BLOCKING SHAPE (spec behaviours 3, 4 and 6): every assertion this hotfix adds is a
"small, equal, or ignored" shape, i.e. exactly the family that passes when the fixture is
broken. So this file does not merely re-run the rebuilt oracle -- it drives the oracle
through DEFECT TWINS in-process (`test_b3_*`, `test_b4_*`): a wrapper that lies about the
fixture's file count, and one that hands the oracle a probe path git does NOT ignore. Each
twin must make the rebuilt oracle FAIL, in the same session where the real fixture passes.
Behaviour 6 gets the same treatment from the other side: the does-not-scale claim is
re-derived at a 600x spread with fixture directory names of 1 and 24 characters, so neither
the on-disk count nor the path length can be carrying an accidental equality.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-155 PM spec's
Expected Behaviors 1-10, the conventions found under `tests/`, and the OBSERVABLE content
and behaviour of files under `tests/` -- which the role card explicitly permits reading and
which, this iteration, is where the whole change lives. `foundry.py` and `dispatcher.py`
source were NOT read, and neither the engineer's notes, the reviewer's notes, nor any
`git diff` was consulted.
"""

from __future__ import annotations

import ast
import os
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tests"))
sys.path.insert(0, str(_ROOT))

import test_iter61_behavior as t61  # noqa: E402
import test_iter154_behavior as t154  # noqa: E402

_TARGET = _ROOT / "tests" / "test_iter154_behavior.py"
_SRC = _TARGET.read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)
_B2 = "test_b2_snapshot_is_bounded_not_a_byte_walk"
_FLOOR_TEST = "test_nonvacuity_two_distinct_repos_do_not_snapshot_alike"
_REAL_PRODUCTS = _ROOT / "products"
_EXPECTED_TESTS = 12


def _fndef(name: str) -> ast.FunctionDef:
    for node in _TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"tests/test_iter154_behavior.py must define {name}()")


def _seg(name: str) -> str:
    return ast.get_source_segment(_SRC, _fndef(name)) or ""


def _snap():
    fn = getattr(t61, "_git_visible_snapshot", None)
    assert callable(fn), "tests/test_iter61_behavior.py must expose _git_visible_snapshot"
    return fn


def _built(root: pathlib.Path, count: int) -> tuple[int, str]:
    """Build one hermetic fixture repo and fill its committed-ignored state/ path."""
    t154._hermetic_repo(root)
    return t154._fill_ignored_state(root, count)


# ============================================================ behaviour 1
def test_b1_ambient_tree_tokens_are_gone_and_b2_takes_tmp_path():
    assert "rglob" not in _SRC, (
        "behaviour 1: tests/test_iter154_behavior.py must contain no rglob call -- the "
        "recursive walk over the ambient products/ tree IS the defect being removed"
    )
    assert "6000" not in _SRC, (
        "behaviour 1: the 6000 literal (the old ambient-tree file-count floor) must be "
        "gone from tests/test_iter154_behavior.py"
    )
    args = [a.arg for a in _fndef(_B2).args.args]
    assert "tmp_path" in args, (
        f"behaviour 1: {_B2} must take pytest's tmp_path fixture as a parameter, saw "
        f"{args}"
    )


# ============================================================ behaviour 2
def test_b2_oracle_builds_two_hermetic_fixtures_under_tmp_path():
    seg = _seg(_B2)
    assert seg.count("_hermetic_repo(") == 2, (
        f"behaviour 2: {_B2} must build TWO throwaway repos via _hermetic_repo, saw "
        f"{seg.count('_hermetic_repo(')} call(s)"
    )
    assert seg.count("tmp_path /") == 2, (
        f"behaviour 2: both fixture roots must live under tmp_path, saw "
        f"{seg.count('tmp_path /')} tmp_path-rooted path(s) in {_B2}"
    )
    assert seg.count("_fill_ignored_state(") == 2, (
        f"behaviour 2: {_B2} must fill BOTH fixtures, saw "
        f"{seg.count('_fill_ignored_state(')} fill call(s)"
    )


def test_b2_hermetic_repo_invariants_are_unchanged():
    helper = _seg("_hermetic_repo")
    assert '"state/' in helper, (
        "behaviour 2: _hermetic_repo's committed .gitignore must still carry the state/ "
        "rule -- it is what makes the bulk fill invisible to git"
    )
    assert "not clean after seed" in helper, (
        "behaviour 2: _hermetic_repo's post-seed CLEAN assertion must be unchanged -- "
        "without it a dirty fixture would grow the snapshot for an unrelated reason"
    )


def test_b2_fill_sizes_straddle_the_spec_bounds(tmp_path):
    small = tmp_path / "small"
    large = tmp_path / "large"
    n_small, probe_small = _built(small, t154._SMALL_FILL)
    n_large, probe_large = _built(large, t154._LARGE_FILL)
    assert t154._SMALL_FILL <= 50, (
        f"behaviour 2: the small fixture must be filled with at most 50 files, "
        f"_SMALL_FILL is {t154._SMALL_FILL}"
    )
    assert t154._LARGE_FILL >= 3000, (
        f"behaviour 2: the large fixture must be filled with at least 3000 files, "
        f"_LARGE_FILL is {t154._LARGE_FILL}"
    )
    assert n_small <= 50 and n_large >= 3000, (
        f"behaviour 2: the fill must actually land on disk under state/, saw "
        f"{n_small} small / {n_large} large"
    )
    assert probe_small.startswith("state/") and probe_large.startswith("state/"), (
        f"behaviour 2: the fill must land under the committed-ignored state/ path, "
        f"probes were {probe_small!r} / {probe_large!r}"
    )


# ============================================================ behaviour 3
def test_b3_fixture_floor_is_live_defect_twin_lying_about_the_count(monkeypatch, tmp_path):
    """The <=50 / >=3000 preconditions must be ENFORCED, not decorative."""
    real_fill = t154._fill_ignored_state

    def lying_low(root, count):
        n, probe = real_fill(root, count)
        return (0 if count >= 3000 else n), probe

    monkeypatch.setattr(t154, "_fill_ignored_state", lying_low)
    with pytest.raises(AssertionError) as err:
        t154.test_b2_snapshot_is_bounded_not_a_byte_walk(tmp_path)
    assert "3000" in str(err.value), (
        f"behaviour 3: a large fixture reporting 0 files must trip the >=3000 floor, "
        f"instead the oracle failed with: {str(err.value)[:200]!r}"
    )


def test_b3_small_ceiling_is_live_defect_twin_lying_high(monkeypatch, tmp_path):
    real_fill = t154._fill_ignored_state

    def lying_high(root, count):
        n, probe = real_fill(root, count)
        return (999999 if count < 3000 else n), probe

    monkeypatch.setattr(t154, "_fill_ignored_state", lying_high)
    with pytest.raises(AssertionError) as err:
        t154.test_b2_snapshot_is_bounded_not_a_byte_walk(tmp_path)
    assert "small" in str(err.value), (
        f"behaviour 3: a small fixture reporting 999999 files must trip the <=50 "
        f"ceiling, instead: {str(err.value)[:200]!r}"
    )


def test_b3_counts_come_from_the_fixture_not_the_ambient_tree():
    seg = _seg(_B2)
    body = ast.parse(seg.strip())
    real = [n.lineno for n in ast.walk(body) if isinstance(n, ast.Name)
            and n.id == "_REAL_PRODUCTS"]
    fills = [n.lineno for n in ast.walk(body) if isinstance(n, ast.Name)
             and n.id == "_fill_ignored_state"]
    assert len(fills) == 2, (
        f"behaviour 3: {_B2} must build its own floor from two fixture fills, saw "
        f"{len(fills)}"
    )
    assert len(real) == 1, (
        f"behaviour 3/7: {_B2} may touch the real tree exactly once (the unconditional "
        f"bound), saw {len(real)} reference(s)"
    )
    assert real[0] > max(fills), (
        f"behaviour 3: the fixture floor must be established BEFORE any real-tree "
        f"reference in {_B2} (fills at lines {fills}, real tree at line {real[0]})"
    )


# ============================================================ behaviour 4
def test_b4_check_ignore_proves_the_fill_is_invisible_to_git(tmp_path):
    root = tmp_path / "probe_repo"
    n, probe = _built(root, 5)
    g = t154._git(root)
    assert g("check-ignore", "-q", probe).returncode == 0, (
        f"behaviour 4: {probe} must be gitignored inside the hermetic fixture, so the "
        f"bulk fill can never reach the snapshot through git"
    )
    assert g("check-ignore", "-q", "tracked.txt").returncode != 0, (
        "behaviour 4 (two-sided): a COMMITTED file must NOT report as ignored, else "
        "check-ignore is answering yes to everything and proves nothing"
    )
    assert n == 5, f"behaviour 4: fixture fill should be 5 files, saw {n}"


def test_b4_check_ignore_gate_is_live_defect_twin_with_a_visible_probe(
    monkeypatch, tmp_path
):
    real_fill = t154._fill_ignored_state

    def visible_probe(root, count):
        n, _probe = real_fill(root, count)
        return n, "tracked.txt"

    monkeypatch.setattr(t154, "_fill_ignored_state", visible_probe)
    with pytest.raises(AssertionError) as err:
        t154.test_b2_snapshot_is_bounded_not_a_byte_walk(tmp_path)
    assert "gitignored" in str(err.value), (
        f"behaviour 4: handing the oracle a git-VISIBLE probe must trip its "
        f"check-ignore precondition, instead: {str(err.value)[:200]!r}"
    )


def test_b4_oracle_checks_both_fixtures_not_just_one():
    seg = _seg(_B2)
    assert "check-ignore" in seg, (
        f"behaviour 4: {_B2} must prove the fill is ignored via git check-ignore"
    )
    assert seg.count('"small"') >= 1 and seg.count('"large"') >= 1, (
        f"behaviour 4: the check-ignore proof must cover BOTH fixtures, not one"
    )


# ============================================================ behaviours 5 + 6
def test_b5_snapshot_of_the_large_fixture_is_within_the_repr_ceiling(tmp_path):
    snap = _snap()
    large = tmp_path / "big"
    n_large, _probe = _built(large, t154._LARGE_FILL)
    text = repr(snap(large, large))
    assert t154._REPR_CEILING == 20000, (
        f"behaviour 5: the repr ceiling must stay 20000, saw {t154._REPR_CEILING}"
    )
    assert len(text) <= t154._REPR_CEILING, (
        f"behaviour 5: repr(snapshot) is {len(text)} chars at {n_large} files on disk, "
        f"over the {t154._REPR_CEILING}-char ceiling"
    )


def test_b6_does_not_scale_at_600x_with_unequal_path_lengths(tmp_path):
    """Re-derive the EQUAL claim where BOTH suspects vary: count and path length.

    The shipped oracle compares `repo_b2_small` with `repo_b2_large` -- names of equal
    length -- so a snapshot that embedded its own root path would still compare EQUAL,
    for entirely the wrong reason. Here the roots are 1 and 24 characters and the fill
    differs 600x.
    """
    snap = _snap()
    tiny_root = tmp_path / "a"
    huge_root = tmp_path / ("b" * 24)
    n_tiny, _p1 = _built(tiny_root, 5)
    n_huge, _p2 = _built(huge_root, 3000)
    tiny = repr(snap(tiny_root, tiny_root))
    huge = repr(snap(huge_root, huge_root))
    assert n_huge >= 600 * n_tiny, (
        f"fixture: the spread must be at least 600x, saw {n_tiny} vs {n_huge}"
    )
    assert len(tiny) == len(huge), (
        f"behaviour 6: the snapshot must not SCALE with the tree it describes -- "
        f"{n_tiny} vs {n_huge} files on disk (600x) and roots of "
        f"{len(tiny_root.name)} vs {len(huge_root.name)} chars gave {len(tiny)} vs "
        f"{len(huge)} repr chars"
    )


def test_b6_oracle_asserts_equality_not_a_second_ceiling():
    seg = _seg(_B2)
    assert "len(large_text) == len(small_text)" in seg or (
        "len(small_text) == len(large_text)" in seg
    ), (
        f"behaviour 6: {_B2} must assert the two repr LENGTHS are EQUAL -- a second "
        f"<= ceiling comparison is a strictly weaker claim"
    )


# ============================================================ behaviour 7
def test_b7_real_tree_bound_holds_unconditionally_here_and_now():
    snap = _snap()
    text = repr(snap(_REAL_PRODUCTS))
    assert len(text) <= t154._REPR_CEILING, (
        f"behaviour 7: repr(snapshot(products/)) is {len(text)} chars, over the "
        f"{t154._REPR_CEILING}-char ceiling"
    )
    seg = _seg(_B2)
    big_int_compares = [
        n
        for n in ast.walk(ast.parse(seg.strip()))
        if isinstance(n, ast.Compare)
        and any(
            isinstance(c, ast.Constant) and isinstance(c.value, int) and c.value >= 1000
            for c in n.comparators
        )
    ]
    assert not big_int_compares, (
        f"behaviour 7: {_B2} must carry NO hard-coded four-digit file-count "
        f"precondition, found {len(big_int_compares)}"
    )


# ============================================================ behaviour 8
def test_b8_fresh_clone_simulation_four_tracked_files_only(monkeypatch, tmp_path):
    """The oracle must pass where post-release verification runs it: `products/` == 4."""
    fake = tmp_path / "clone_products"
    fake.mkdir()
    for name in (".gitignore", "a_config.json", "b_config.json", "c_staffing.json"):
        (fake / name).write_text("{}\n", encoding="utf-8")
    n = sum(len(files) for _, _, files in os.walk(fake))
    assert n == 4, f"simulation fixture must hold exactly 4 files, saw {n}"
    monkeypatch.setattr(t154, "_REAL_PRODUCTS", fake)
    t154.test_b2_snapshot_is_bounded_not_a_byte_walk(tmp_path / "run")


def test_b8_simulation_is_two_sided_the_patch_is_actually_consulted(monkeypatch, tmp_path):
    """If the oracle ignored the module global, behaviour 8 would prove nothing."""
    seen: list[pathlib.Path] = []
    fake = tmp_path / "sentinel_products"
    fake.mkdir()
    real_snap = t61._git_visible_snapshot

    def spy(root, repo_root=None, *a, **k):
        seen.append(pathlib.Path(root))
        if repo_root is None:
            return real_snap(root)
        return real_snap(root, repo_root)

    monkeypatch.setattr(t61, "_git_visible_snapshot", spy)
    monkeypatch.setattr(t154, "_REAL_PRODUCTS", fake)
    t154.test_b2_snapshot_is_bounded_not_a_byte_walk(tmp_path / "run2")
    assert fake in seen, (
        f"behaviour 8: the oracle must snapshot the module-global _REAL_PRODUCTS (so "
        f"monkeypatching it really simulates a fresh clone); snapshotted {seen}"
    )
    assert _REAL_PRODUCTS not in seen, (
        "behaviour 8: with _REAL_PRODUCTS patched the oracle must not reach the real "
        "products/ tree at all"
    )


# ============================================================ behaviour 9
def test_b9_file_still_holds_twelve_tests_including_the_nonvacuity_floor():
    names = [
        n.name
        for n in _TREE.body
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
    ]
    assert len(names) == _EXPECTED_TESTS, (
        f"behaviour 9: tests/test_iter154_behavior.py must still hold "
        f"{_EXPECTED_TESTS} tests, saw {len(names)}: {names}"
    )
    assert _FLOOR_TEST in names, (
        f"behaviour 9: the non-vacuity floor {_FLOOR_TEST} must NOT be deleted -- every "
        f"<= / == assertion in behaviours 5-7 rests on it"
    )
    assert "!=" in _seg(_FLOOR_TEST), (
        "behaviour 9: the non-vacuity floor must still assert two DIFFERENT repos "
        "snapshot UNEQUAL"
    )


def test_b9_nonvacuity_floor_still_passes_when_driven_directly(tmp_path):
    t154.test_nonvacuity_two_distinct_repos_do_not_snapshot_alike(tmp_path)


def test_b9_rebuilt_oracle_passes_on_the_real_tree_as_shipped(tmp_path):
    t154.test_b2_snapshot_is_bounded_not_a_byte_walk(tmp_path)


# ============================================================ behaviour 10 (proxy)
def test_b10_no_absolute_machine_paths_or_operator_identifiers_in_the_new_tests():
    # The needles are ASSEMBLED, never spelled: a scan test that embeds its own literal
    # trips on itself, which is a false positive that reads exactly like a real leak.
    needles = ("/" + "Users" + "/", "/" + "home" + "/", "jinc" + "m")
    for path in (_TARGET, pathlib.Path(__file__)):
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            assert needle not in text, (
                f"public-safety: {path.name} must carry no absolute machine path or "
                f"operator identifier, found {needle!r}"
            )


def test_b10_target_module_imports_in_a_clean_interpreter():
    """A rebuilt oracle that cannot be imported cold takes the whole suite with it."""
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'tests'); "
         "import test_iter154_behavior as m; print(m.__name__)"],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, (
        f"behaviour 10: tests/test_iter154_behavior.py must import in a clean "
        f"interpreter; exit={r.returncode} stderr={r.stderr[-400:]!r}"
    )
    assert "test_iter154_behavior" in r.stdout
