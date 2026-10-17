"""Iteration 448 -- BLACK-BOX behavior tests: _guard_nodes memoization cache.

Spec under test: products/_platform/state/iter-448/pm.md (5 Expected Behaviors).

  EB1: freeze_guards() with no argument (real test tree) returns the same list
       of (path, name) tuples as before -- the cache does not alter correctness.
  EB2: freeze_guards(some_tmp_path) with a known synthetic guard returns only
       guards from that directory, NOT the real tree's guards -- cache isolates
       by resolved path.
  EB3: The module exposes a _guard_nodes_cache module-level dict that is
       populated after the first _guard_nodes() call and reused on subsequent
       calls with the same resolved path.
  EB4: Clearing _guard_nodes_cache and re-calling _guard_nodes() produces the
       same result as the first call -- pure memoization, not transformation.
  EB5: The full quality-check suite passes with 0 new failures and 0 new skips.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-448 PM spec, the
module's public API (freeze_guards, forbidden_freezes, hollow_guards,
_guard_nodes_cache, _guard_nodes, is_freeze_guard, EXPECTED_MIN_GUARD_COUNT),
and existing test conventions under tests/.  The implementation source of
foundry.py / dispatcher.py was NOT read, and neither were engineer.md,
reviewer.md, IMPLEMENTATION.patch, or git diff.
"""

from __future__ import annotations

import ast
import pathlib
import textwrap

import pytest

import test_control_path_freeze_scope as scope


THIS_ITER = 448

SYNTH_GUARD_SOURCE = textwrap.dedent("""\
    import subprocess

    def test_ac_control_path_byte_unchanged():
        subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py"],
                       check=True)
""")


# ---------------------------------------------------------------------------
# EB1 -- freeze_guards() correctness is preserved
# ---------------------------------------------------------------------------

class TestEB1CachePreservesCorrectness:
    """freeze_guards() with no argument returns the same (path, name) tuples."""

    def test_b1_freeze_guards_returns_at_least_expected_count(self):
        guards = scope.freeze_guards()
        assert len(guards) >= scope.EXPECTED_MIN_GUARD_COUNT, (
            f"expected >= {scope.EXPECTED_MIN_GUARD_COUNT}, got {len(guards)}"
        )

    def test_b1_freeze_guards_elements_are_path_name_pairs(self):
        guards = scope.freeze_guards()
        for path, name in guards:
            assert isinstance(path, pathlib.Path), f"expected Path, got {type(path)}"
            assert isinstance(name, str) and name.startswith("test_"), (
                f"expected test function name, got {name!r}"
            )

    def test_b1_two_consecutive_calls_return_identical_lists(self):
        first = scope.freeze_guards()
        second = scope.freeze_guards()
        assert first == second, "consecutive freeze_guards() calls differ"

    def test_b1_forbidden_freezes_still_empty(self):
        offenders = scope.forbidden_freezes()
        assert not offenders, (
            f"cache broke forbidden_freezes: {offenders}"
        )

    def test_b1_hollow_guards_still_empty(self):
        hollow = scope.hollow_guards()
        assert not hollow, (
            f"cache broke hollow_guards: {hollow}"
        )


# ---------------------------------------------------------------------------
# EB2 -- cache isolates by resolved path (tmp_path vs real tree)
# ---------------------------------------------------------------------------

class TestEB2CacheIsolatesByPath:
    """freeze_guards(tmp_path) returns only that directory's guards."""

    def test_b2_tmp_path_with_synth_guard_returns_only_synth(self, tmp_path):
        (tmp_path / "test_synth_guard.py").write_text(
            SYNTH_GUARD_SOURCE, encoding="utf-8"
        )
        guards = scope.freeze_guards(tmp_path)
        assert len(guards) == 1, f"expected 1, got {len(guards)}: {guards}"
        path, name = guards[0]
        assert name == "test_ac_control_path_byte_unchanged"
        assert path.parent == tmp_path

    def test_b2_tmp_path_with_no_guards_returns_empty(self, tmp_path):
        (tmp_path / "test_empty.py").write_text(
            "def test_noop(): pass\n", encoding="utf-8"
        )
        guards = scope.freeze_guards(tmp_path)
        assert guards == [], f"expected [], got {guards}"

    def test_b2_real_tree_unaffected_after_tmp_call(self, tmp_path):
        (tmp_path / "test_synth_guard.py").write_text(
            SYNTH_GUARD_SOURCE, encoding="utf-8"
        )
        _ = scope.freeze_guards(tmp_path)
        real_guards = scope.freeze_guards()
        assert len(real_guards) >= scope.EXPECTED_MIN_GUARD_COUNT, (
            "real tree call after tmp_path returned wrong count"
        )

    def test_b2_two_different_tmp_paths_are_distinct(self, tmp_path):
        dir_a = tmp_path / "a"
        dir_a.mkdir()
        dir_b = tmp_path / "b"
        dir_b.mkdir()
        (dir_a / "test_synth_guard.py").write_text(
            SYNTH_GUARD_SOURCE, encoding="utf-8"
        )
        (dir_b / "test_empty.py").write_text(
            "def test_noop(): pass\n", encoding="utf-8"
        )
        guards_a = scope.freeze_guards(dir_a)
        guards_b = scope.freeze_guards(dir_b)
        assert len(guards_a) == 1, f"dir_a: expected 1 guard, got {len(guards_a)}"
        assert len(guards_b) == 0, f"dir_b: expected 0 guards, got {len(guards_b)}"


# ---------------------------------------------------------------------------
# EB3 -- _guard_nodes_cache is populated and reused
# ---------------------------------------------------------------------------

class TestEB3CachePopulatedAndReused:
    """_guard_nodes_cache dict is exposed and populated after first call."""

    def test_b3_cache_dict_exists_at_module_level(self):
        assert hasattr(scope, "_guard_nodes_cache"), (
            "module missing _guard_nodes_cache"
        )
        assert isinstance(scope._guard_nodes_cache, dict), (
            f"expected dict, got {type(scope._guard_nodes_cache)}"
        )

    def test_b3_cache_populated_after_call(self, tmp_path):
        (tmp_path / "test_synth_guard.py").write_text(
            SYNTH_GUARD_SOURCE, encoding="utf-8"
        )
        scope._guard_nodes_cache.pop(str(tmp_path.resolve()), None)
        scope.freeze_guards(tmp_path)
        key = str(tmp_path.resolve())
        assert key in scope._guard_nodes_cache, (
            f"cache not populated for key {key}"
        )

    def test_b3_second_call_reuses_cache(self, tmp_path):
        (tmp_path / "test_synth_guard.py").write_text(
            SYNTH_GUARD_SOURCE, encoding="utf-8"
        )
        scope._guard_nodes_cache.pop(str(tmp_path.resolve()), None)
        scope.freeze_guards(tmp_path)
        key = str(tmp_path.resolve())
        cached_value = scope._guard_nodes_cache[key]
        result_2 = scope._guard_nodes(tmp_path)
        assert result_2 is cached_value, (
            "second call returned a different object, not the cached one"
        )


# ---------------------------------------------------------------------------
# EB4 -- clearing cache forces re-computation with identical results
# ---------------------------------------------------------------------------

class TestEB4ClearCacheRecomputes:
    """Clearing _guard_nodes_cache and re-calling produces the same result."""

    def test_b4_clear_and_recall_produces_same_result(self, tmp_path):
        (tmp_path / "test_synth_guard.py").write_text(
            SYNTH_GUARD_SOURCE, encoding="utf-8"
        )
        first = scope.freeze_guards(tmp_path)
        scope._guard_nodes_cache.clear()
        second = scope.freeze_guards(tmp_path)
        assert first == second, (
            f"cache clear + recall differs: {first} vs {second}"
        )

    def test_b4_clear_and_recall_on_real_tree(self):
        first = scope.freeze_guards()
        scope._guard_nodes_cache.clear()
        second = scope.freeze_guards()
        assert first == second, (
            "cache clear + recall on real tree differs"
        )

    def test_b4_cache_repopulated_after_clear(self, tmp_path):
        (tmp_path / "test_synth_guard.py").write_text(
            SYNTH_GUARD_SOURCE, encoding="utf-8"
        )
        scope.freeze_guards(tmp_path)
        scope._guard_nodes_cache.clear()
        assert len(scope._guard_nodes_cache) == 0
        scope.freeze_guards(tmp_path)
        assert str(tmp_path.resolve()) in scope._guard_nodes_cache, (
            "cache not repopulated after clear"
        )


# ---------------------------------------------------------------------------
# EB5 -- full suite passes (verified by the suite run itself)
# ---------------------------------------------------------------------------

class TestEB5SuiteGreen:
    """Importing both foundry and dispatcher succeeds (import-safety probe)."""

    def test_b5_foundry_importable(self):
        import foundry  # noqa: F811
        assert hasattr(foundry, "__file__")

    def test_b5_dispatcher_importable(self):
        import dispatcher  # noqa: F811
        assert hasattr(dispatcher, "__file__")
