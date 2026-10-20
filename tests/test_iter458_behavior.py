"""Iteration 458 -- BLACK-BOX behavior tests: consolidate _snapshot_tree into _shared.py.

Spec under test: products/_platform/state/iter-458/pm.md (4 Expected Behaviors).

  EB1: A function named `_snapshot_tree` is defined in `tests/_shared.py` with a
       signature that is a superset of all 5 existing variant signatures
       (backward-compatible defaults for any extra keyword arguments).
  EB2: No test module under `tests/` other than `_shared.py` defines its own
       `_snapshot_tree` -- every file that previously defined it imports from
       `tests/_shared.py` instead.
  EB3: Running `grep -rn "def _snapshot_tree" tests/` returns exactly one hit,
       in `tests/_shared.py`.
  EB4: The full quality-check suite passes with zero new failures, proving the
       consolidation is behavior-preserving.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-458 PM spec, the
module's public API, and existing test conventions under tests/.  The
implementation source of foundry.py / dispatcher.py was NOT read, and neither
were engineer.md, IMPLEMENTATION.patch, or git diff.
"""

from __future__ import annotations

import inspect
import pathlib
import subprocess

import pytest

THIS_ITER = 458
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"


# ---------------------------------------------------------------------------
# EB1 -- _snapshot_tree defined in _shared.py with superset signature
# ---------------------------------------------------------------------------

class TestEB1SupersetSignature:
    """_snapshot_tree lives in _shared.py and accepts at least a root path arg."""

    def test_b1_importable_from_shared(self):
        from _shared import _snapshot_tree
        assert callable(_snapshot_tree)

    def test_b1_accepts_str_root(self, tmp_path):
        from _shared import _snapshot_tree
        (tmp_path / "a.txt").write_bytes(b"hello")
        result = _snapshot_tree(str(tmp_path))
        assert isinstance(result, dict)
        assert result["a.txt"] == b"hello"

    def test_b1_accepts_pathlib_root(self, tmp_path):
        from _shared import _snapshot_tree
        (tmp_path / "b.bin").write_bytes(b"\x00\x01")
        result = _snapshot_tree(tmp_path)
        assert isinstance(result, dict)
        assert result["b.bin"] == b"\x00\x01"

    def test_b1_returns_dict_str_bytes(self, tmp_path):
        from _shared import _snapshot_tree
        (tmp_path / "f.txt").write_bytes(b"data")
        result = _snapshot_tree(tmp_path)
        for k, v in result.items():
            assert isinstance(k, str), f"key {k!r} is not str"
            assert isinstance(v, bytes), f"value for {k!r} is not bytes"

    def test_b1_recurses_into_subdirs(self, tmp_path):
        sub = tmp_path / "d" / "e"
        sub.mkdir(parents=True)
        (sub / "nested.txt").write_bytes(b"deep")
        from _shared import _snapshot_tree
        result = _snapshot_tree(tmp_path)
        nested_key = str(pathlib.PurePosixPath("d/e/nested.txt"))
        assert nested_key in result or "d/e/nested.txt" in result

    def test_b1_empty_dir_returns_empty(self, tmp_path):
        from _shared import _snapshot_tree
        result = _snapshot_tree(tmp_path)
        assert result == {}

    def test_b1_nonexistent_dir_returns_empty(self, tmp_path):
        from _shared import _snapshot_tree
        result = _snapshot_tree(tmp_path / "no_such_dir")
        assert result == {}

    def test_b1_signature_has_root_param(self):
        from _shared import _snapshot_tree
        sig = inspect.signature(_snapshot_tree)
        params = list(sig.parameters.keys())
        assert len(params) >= 1, "expected at least one parameter (root)"


# ---------------------------------------------------------------------------
# EB2 -- no other test module defines _snapshot_tree
# ---------------------------------------------------------------------------

class TestEB2NoDuplicateDefinitions:
    """No test file other than _shared.py defines its own _snapshot_tree."""

    def test_b2_no_def_snapshot_tree_outside_shared(self):
        hits = []
        for py in sorted(TESTS_DIR.glob("*.py")):
            if py.name == "_shared.py":
                continue
            text = py.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith("def _snapshot_tree"):
                    hits.append(f"{py.name}:{i}")
        assert hits == [], (
            f"found _snapshot_tree definitions outside _shared.py: {hits}"
        )

    def test_b2_shared_does_define_it(self):
        shared = TESTS_DIR / "_shared.py"
        text = shared.read_text(encoding="utf-8")
        assert "def _snapshot_tree" in text, (
            "_shared.py does not define _snapshot_tree"
        )


# ---------------------------------------------------------------------------
# EB3 -- grep returns exactly one hit
# ---------------------------------------------------------------------------

class TestEB3SingleGrepHit:
    """grep -rn 'def _snapshot_tree' tests/ returns exactly one hit."""

    def test_b3_grep_single_hit(self):
        import re as _re
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "def _snapshot_tree", str(TESTS_DIR)],
            capture_output=True, text=True,
        )
        actual_defs = []
        for l in result.stdout.strip().splitlines():
            if not l.strip():
                continue
            m = _re.match(r"^(.+?):(\d+):(.*)$", l)
            if m and m.group(3).startswith("def _snapshot_tree"):
                actual_defs.append(l)
        assert len(actual_defs) == 1, (
            f"expected exactly 1 def site, got {len(actual_defs)}: {actual_defs}"
        )
        assert "_shared.py" in actual_defs[0], (
            f"the single hit should be in _shared.py, got: {actual_defs[0]}"
        )


# ---------------------------------------------------------------------------
# EB4 -- suite passes (tested by the full-suite run itself; here we verify
#         the consolidation is behavior-preserving by importing from _shared
#         and exercising the canonical implementation)
# ---------------------------------------------------------------------------

class TestEB4BehaviorPreserving:
    """The canonical _snapshot_tree preserves the behavior of all 5 variants."""

    def test_b4_multiple_files_captured(self, tmp_path):
        (tmp_path / "x.txt").write_bytes(b"x")
        (tmp_path / "y.txt").write_bytes(b"y")
        from _shared import _snapshot_tree
        result = _snapshot_tree(tmp_path)
        assert len(result) == 2
        assert result["x.txt"] == b"x"
        assert result["y.txt"] == b"y"

    def test_b4_binary_content_preserved(self, tmp_path):
        data = bytes(range(256))
        (tmp_path / "bin.dat").write_bytes(data)
        from _shared import _snapshot_tree
        result = _snapshot_tree(tmp_path)
        assert result["bin.dat"] == data

    def test_b4_relative_paths_are_strings(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "f.txt").write_bytes(b"v")
        from _shared import _snapshot_tree
        result = _snapshot_tree(tmp_path)
        keys = list(result.keys())
        assert all(isinstance(k, str) for k in keys)
        assert any("sub" in k for k in keys)

    def test_b4_dirs_not_included_as_keys(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "f.txt").write_bytes(b"v")
        from _shared import _snapshot_tree
        result = _snapshot_tree(tmp_path)
        assert "sub" not in result, "directories should not appear as keys"


# ---------------------------------------------------------------------------
# Import safety
# ---------------------------------------------------------------------------

class TestImportSafety:
    """Module-level imports do not crash."""

    def test_import_shared(self):
        import _shared
        assert hasattr(_shared, "_snapshot_tree")
