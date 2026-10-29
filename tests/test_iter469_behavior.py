"""Iteration 469 -- BLACK-BOX behavior tests: consolidate _co_names_deep into _shared.py.

Spec under test: products/_platform/state/iter-469/pm.md (6 Expected Behaviors).

  EB1: tests/_shared.py exports _co_names_deep that accepts a code object and
       returns set[str] of all names reachable by recursively walking co_consts.
  EB2: Each of the 41 test modules that previously had a local _co_names_deep now
       imports from _shared and has NO local definition.
  EB3: The canonical definition is a SUPERSET of the 12 variants (type guards,
       recursion depth, co_consts filtering).
  EB4: The full suite passes with zero new failures.
  EB5: No production code is modified.
  EB6: Net line count across all 41 files decreases by at least 350 lines.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-469 PM spec, the
public API of _shared.py, and existing test conventions under tests/.  The
implementation source of foundry.py / dispatcher.py was NOT read, and neither
were engineer.md, reviewer.md, IMPLEMENTATION.patch, or git diff.
"""

from __future__ import annotations

import inspect
import pathlib
import subprocess
import types

import pytest

THIS_ITER = 469
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"

# The commit that shipped iter 469; EB5/EB6 measure it rather than the live tree.
ITER469_COMMIT = "d9c40f7"
LEDGER_FILES = frozenset({"DIRECTIONS.md", "PLATFORM_ROADMAP.md", "PLATFORM_ROADMAP_ARCHIVE.md"})
ORACLE_PATH = "tests/test_iter469_behavior.py"


def _require_iter469_commit() -> None:
    """Skip, not fail, where the commit is absent (e.g. a shallow clone)."""
    probe = subprocess.run(
        ["git", "cat-file", "-e", ITER469_COMMIT + "^{commit}"],
        capture_output=True, text=True,
        cwd=str(REPO_ROOT),
    )
    if probe.returncode != 0:
        pytest.skip(f"iter-469 commit {ITER469_COMMIT} not available")


# ---------------------------------------------------------------------------
# EB1 -- _co_names_deep defined in _shared.py, callable, returns set[str]
# ---------------------------------------------------------------------------

class TestEB1CanonicalInShared:
    """_co_names_deep lives in _shared.py, accepts a callable, returns set[str]."""

    def test_b1_importable_from_shared(self):
        from _shared import _co_names_deep
        assert callable(_co_names_deep)

    def test_b1_returns_set_of_str(self):
        from _shared import _co_names_deep

        def sample():
            print("hello")
            return len([1, 2])

        result = _co_names_deep(sample)
        assert isinstance(result, set)
        for item in result:
            assert isinstance(item, str), f"expected str, got {type(item).__name__}: {item!r}"

    def test_b1_finds_referenced_names(self):
        from _shared import _co_names_deep

        def sample():
            print("hello")
            return len([1, 2])

        names = _co_names_deep(sample)
        assert "print" in names, f"'print' not in {names}"
        assert "len" in names, f"'len' not in {names}"

    def test_b1_recurses_into_nested_code_objects(self):
        from _shared import _co_names_deep

        def outer():
            def inner():
                return sorted([3, 1, 2])
            return inner()

        names = _co_names_deep(outer)
        assert "sorted" in names, f"'sorted' not in {names}"

    def test_b1_deeply_nested_functions(self):
        from _shared import _co_names_deep

        def level0():
            def level1():
                def level2():
                    return isinstance(42, int)
                return level2()
            return level1()

        names = _co_names_deep(level0)
        assert "isinstance" in names, f"'isinstance' not in {names}"

    def test_b1_empty_function_returns_set(self):
        from _shared import _co_names_deep

        def noop():
            pass

        result = _co_names_deep(noop)
        assert isinstance(result, set)

    def test_b1_signature_has_parameter(self):
        from _shared import _co_names_deep
        sig = inspect.signature(_co_names_deep)
        params = list(sig.parameters.keys())
        assert len(params) >= 1, "expected at least one parameter"


# ---------------------------------------------------------------------------
# EB2 -- 41 test modules import from _shared, no local definition anywhere
# ---------------------------------------------------------------------------

class TestEB2NoLocalDefinitions:
    """No test file other than _shared.py defines its own _co_names_deep."""

    def test_b2_no_def_outside_shared(self):
        hits = []
        for py in sorted(TESTS_DIR.glob("*.py")):
            if py.name == "_shared.py":
                continue
            text = py.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                stripped = line.lstrip()
                if stripped.startswith("def _co_names_deep"):
                    hits.append(f"{py.name}:{i}")
        assert hits == [], (
            f"found _co_names_deep definitions outside _shared.py: {hits}"
        )

    def test_b2_shared_does_define_it(self):
        shared = TESTS_DIR / "_shared.py"
        text = shared.read_text(encoding="utf-8")
        assert "def _co_names_deep" in text, (
            "_shared.py does not define _co_names_deep"
        )

    def test_b2_grep_single_definition(self):
        import re as _re
        hits = []
        for py in sorted(TESTS_DIR.glob("*.py")):
            text = py.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                if _re.match(r"^\s*def _co_names_deep\b", line):
                    hits.append(f"{py.name}:{i}: {line.strip()}")
        assert len(hits) == 1, (
            f"expected exactly 1 def site, got {len(hits)}: {hits}"
        )
        assert "_shared.py" in hits[0], (
            f"the single hit should be in _shared.py, got: {hits[0]}"
        )

    def test_b2_at_least_41_importers(self):
        """At least 41 test modules import _co_names_deep from _shared."""
        import_count = 0
        for py in sorted(TESTS_DIR.glob("test_iter*_behavior.py")):
            text = py.read_text(encoding="utf-8")
            if "from _shared import" in text and "_co_names_deep" in text:
                for line in text.splitlines():
                    stripped = line.strip()
                    if (stripped.startswith("from _shared import")
                            and "_co_names_deep" in stripped
                            and not stripped.startswith("#")
                            and not stripped.startswith('"')
                            and not stripped.startswith("'")):
                        import_count += 1
                        break
        assert import_count >= 41, (
            f"expected at least 41 test modules importing _co_names_deep from "
            f"_shared, found {import_count}"
        )


# ---------------------------------------------------------------------------
# EB3 -- canonical is SUPERSET (type guards, recursion, co_consts filtering)
# ---------------------------------------------------------------------------

class TestEB3SupersetBehavior:
    """The canonical handles all variant behaviors."""

    def test_b3_handles_function_with_no_nested_code(self):
        from _shared import _co_names_deep

        def flat():
            return max(1, 2)

        names = _co_names_deep(flat)
        assert "max" in names

    def test_b3_handles_lambda(self):
        from _shared import _co_names_deep
        fn = lambda x: str(x) + repr(x)  # noqa: E731
        names = _co_names_deep(fn)
        assert "str" in names
        assert "repr" in names

    def test_b3_handles_comprehension_nested_code(self):
        from _shared import _co_names_deep

        def with_comp():
            return [str(x) for x in range(10)]

        names = _co_names_deep(with_comp)
        assert "str" in names or "range" in names

    def test_b3_type_guard_filters_non_code_consts(self):
        """The function should not crash on co_consts containing non-code objects."""
        from _shared import _co_names_deep

        def has_various_consts():
            x = 42
            y = "hello"
            z = (1, 2, 3)
            return print(x, y, z)

        names = _co_names_deep(has_various_consts)
        assert "print" in names

    def test_b3_recursion_handles_class_defs(self):
        from _shared import _co_names_deep

        def with_class():
            class Inner:
                def method(self):
                    return enumerate([])
            return Inner()

        names = _co_names_deep(with_class)
        assert "enumerate" in names


# ---------------------------------------------------------------------------
# EB4 -- suite passes (tested by the full-suite run itself; we just verify
#         the consolidation is behavior-preserving by exercising the import)
# ---------------------------------------------------------------------------

class TestEB4BehaviorPreserving:
    """The canonical _co_names_deep preserves behavior for all callers."""

    def test_b4_result_is_deterministic(self):
        from _shared import _co_names_deep

        def sample():
            return open("x").read()

        r1 = _co_names_deep(sample)
        r2 = _co_names_deep(sample)
        assert r1 == r2

    def test_b4_does_not_include_local_vars(self):
        """co_names holds global/attribute names, not locals."""
        from _shared import _co_names_deep

        def sample():
            local_var = 42
            return print(local_var)

        names = _co_names_deep(sample)
        assert "local_var" not in names
        assert "print" in names

    def test_b4_includes_attribute_lookups(self):
        from _shared import _co_names_deep

        def sample():
            return "hello".upper()

        names = _co_names_deep(sample)
        assert "upper" in names


# ---------------------------------------------------------------------------
# EB5 -- no production code is modified
# ---------------------------------------------------------------------------

class TestEB5NoProductionCodeModified:
    """All changes are confined to test files."""

    def test_b5_git_diff_only_tests(self):
        """The iter-469 commit itself touches only tests/ plus the ledger files.

        Scoped to ITER469_COMMIT (iter 487): an unscoped `git diff HEAD` read
        whatever a LATER iteration had uncommitted, so it was red in every
        worktree after 469 and green only in a fresh clone.
        """
        _require_iter469_commit()
        result = subprocess.run(
            ["git", "show", "--name-only", "--format=", ITER469_COMMIT],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, result.stderr
        changed_files = [f for f in result.stdout.strip().splitlines() if f.strip()]
        non_test_files = [
            f for f in changed_files
            if not f.startswith("tests/") and f not in LEDGER_FILES
        ]
        assert non_test_files == [], (
            f"production code was modified: {non_test_files}"
        )


# ---------------------------------------------------------------------------
# EB6 -- net line reduction >= 350
# ---------------------------------------------------------------------------

class TestEB6NetLineReduction:
    """The consolidation removes at least 350 net lines."""

    def test_b6_net_reduction_at_least_350(self):
        """Net reduction over the iter-469 commit's consolidated test modules.

        Counts only tests/ rows minus this oracle file: the commit also added
        this module and edited the ledger files, which are not the
        consolidation being measured.
        """
        _require_iter469_commit()
        result = subprocess.run(
            ["git", "show", "--numstat", "--format=", ITER469_COMMIT],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, result.stderr
        insertions = 0
        deletions = 0
        for row in result.stdout.strip().splitlines():
            parts = row.split("\t")
            if len(parts) != 3:
                continue
            ins, dels, path = parts
            if not path.startswith("tests/") or path == ORACLE_PATH:
                continue
            if ins.isdigit() and dels.isdigit():
                insertions += int(ins)
                deletions += int(dels)
        net_reduction = deletions - insertions
        assert net_reduction >= 350, (
            f"net reduction is {net_reduction} (expected >= 350); "
            f"insertions={insertions}, deletions={deletions}"
        )
