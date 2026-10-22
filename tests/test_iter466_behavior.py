"""Iteration 466 -- BLACK-BOX behavior tests: delete the bare ``dispatcher.py``
launch recipe from the dispatcher docstring and README quickstart, replacing
both with ``./launch.sh``, and add a dormant ``launch_recipe_claim_gaps`` guard.

ISOLATION CONTRACT (HONORED).  Every assertion below was derived from this
iteration's PM spec (``pm.md``, Expected Behaviors 1-7) and from the conventions
of the existing test modules under ``tests/``.  I did NOT read ``foundry.py``'s
implementation text, ``engineer.md``, ``reviewer.md``, ``IMPLEMENTATION.patch``,
or ``git diff``.  Each EB is driven as a BLACK BOX: the dispatcher docstring
read via ``ast.get_docstring``, README.md read as text, the pure function
probed with synthetic inputs, and importability tested via subprocess.

OFFLINE + FRESH-CLONE SAFE.  No test reads the real ``products/*/state`` tree,
pins an ambient file count, spawns a network call, or reads the wall clock.
Paths are built from ``__file__`` at runtime.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

THIS_ITER = 466

GUARD_FN = "launch_recipe_claim_gaps"
DISPATCHER_PATH = _ROOT / "dispatcher.py"
README_PATH = _ROOT / "README.md"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _dispatcher_docstring() -> str:
    src = DISPATCHER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    return ast.get_docstring(tree) or ""


def _readme_text() -> str:
    return README_PATH.read_text(encoding="utf-8")


# ==========================================================================
# EB1: dispatcher.py docstring no longer teaches bare uv run ... dispatcher.py
# ==========================================================================
class TestEB1_DispatcherDocstringClean:
    def test_no_bare_dispatcher_recipe_in_docstring(self):
        doc = _dispatcher_docstring()
        lines = doc.lower().splitlines()
        for line in lines:
            stripped = line.strip()
            if "do not" in stripped or "not run" in stripped:
                continue
            if "foundry.py" in stripped and "dispatcher.py" in stripped:
                continue
            assert not (
                "uv run" in stripped
                and "dispatcher.py" in stripped
                and "launch.sh" not in stripped
            ), f"Bare dispatcher.py recipe still in docstring: {line!r}"

    def test_docstring_mentions_launch_sh(self):
        doc = _dispatcher_docstring()
        assert "launch.sh" in doc, (
            "Docstring should reference launch.sh as the launch path"
        )


# ==========================================================================
# EB2: README step #3 teaches launch.sh, not bare dispatcher.py
# ==========================================================================
class TestEB2_ReadmeQuickstartClean:
    def test_step3_teaches_launch_sh(self):
        text = _readme_text()
        step3_lines = []
        in_step3 = False
        for line in text.splitlines():
            if "# 3." in line and "company" in line.lower():
                in_step3 = True
                continue
            if in_step3 and line.strip().startswith("# 4."):
                break
            if in_step3:
                step3_lines.append(line)
        has_launch_sh = any(
            "launch.sh" in l and l.strip().startswith("./launch.sh")
            for l in step3_lines
        )
        assert has_launch_sh, (
            "README step #3 should teach ./launch.sh as the launch command"
        )

    def test_step3_no_bare_dispatcher_recipe(self):
        text = _readme_text()
        in_step3 = False
        for line in text.splitlines():
            if "# 3." in line and "company" in line.lower():
                in_step3 = True
                continue
            if in_step3 and line.strip().startswith("# 4."):
                break
            if in_step3:
                stripped = line.strip().lower()
                if stripped.startswith("#"):
                    continue
                assert not (
                    "uv run" in stripped
                    and "dispatcher.py" in stripped
                    and stripped.startswith("uv")
                ), f"Bare dispatcher.py recipe still in README step #3: {line!r}"


# ==========================================================================
# EB3: launch_recipe_claim_gaps returns empty on clean text
# ==========================================================================
class TestEB3_GuardCleanText:
    def test_function_exists(self):
        assert hasattr(foundry, GUARD_FN), (
            f"{GUARD_FN} must exist on the foundry module"
        )

    def test_callable(self):
        assert callable(getattr(foundry, GUARD_FN)), (
            f"{GUARD_FN} must be callable"
        )

    def test_clean_text_returns_empty(self):
        fn = getattr(foundry, GUARD_FN)
        result = fn("./launch.sh --config foundry.config.json",
                     "./launch.sh --config foundry.config.json")
        assert isinstance(result, list), "Must return a list"
        assert result == [], f"Clean text should yield no findings, got {result}"

    def test_empty_inputs_returns_empty(self):
        fn = getattr(foundry, GUARD_FN)
        result = fn("", "")
        assert result == [], "Empty inputs should yield no findings"

    def test_live_files_clean(self):
        fn = getattr(foundry, GUARD_FN)
        disp_doc = _dispatcher_docstring()
        readme = _readme_text()
        result = fn(disp_doc, readme)
        assert result == [], (
            f"Live dispatcher docstring and README should yield no findings, got {result}"
        )


# ==========================================================================
# EB4: guard detects bare recipe in dispatcher text
# ==========================================================================
class TestEB4_GuardDetectsDispatcherBare:
    def test_bare_recipe_detected(self):
        fn = getattr(foundry, GUARD_FN)
        result = fn("uv run python dispatcher.py --config foundry.config.json", "")
        assert len(result) >= 1, "Should detect bare recipe in dispatcher text"

    def test_old_docstring_form_detected(self):
        fn = getattr(foundry, GUARD_FN)
        result = fn("uv run python -X utf8 dispatcher.py --config foundry.config.json", "")
        assert len(result) >= 1, (
            "Should detect the old docstring form with -X utf8"
        )

    def test_do_not_exclusion(self):
        fn = getattr(foundry, GUARD_FN)
        result = fn("do not run uv run python dispatcher.py", "")
        assert result == [], (
            "'do not' context should not trigger a finding"
        )

    def test_foundry_py_not_flagged(self):
        fn = getattr(foundry, GUARD_FN)
        result = fn("uv run python foundry.py single-brain dispatcher.py", "")
        assert result == [], (
            "References to foundry.py with dispatcher.py as arg should not trigger"
        )


# ==========================================================================
# EB5: guard detects bare recipe in README text
# ==========================================================================
class TestEB5_GuardDetectsReadmeBare:
    def test_bare_recipe_in_readme_detected(self):
        fn = getattr(foundry, GUARD_FN)
        result = fn("", "uv run python dispatcher.py --config foundry.config.json")
        assert len(result) >= 1, "Should detect bare recipe in README text"

    def test_mixed_clean_dispatcher_bare_readme(self):
        fn = getattr(foundry, GUARD_FN)
        result = fn("./launch.sh --config x", "uv run python dispatcher.py --config x")
        assert len(result) >= 1, (
            "Should detect bare recipe in README even when dispatcher is clean"
        )

    def test_both_bare_yields_two_findings(self):
        fn = getattr(foundry, GUARD_FN)
        result = fn(
            "uv run python dispatcher.py --config x",
            "uv run python dispatcher.py --config x",
        )
        assert len(result) >= 2, (
            f"Both inputs bare should yield at least 2 findings, got {len(result)}"
        )


# ==========================================================================
# EB6: importability
# ==========================================================================
class TestEB6_Importability:
    def test_import_foundry_dispatcher(self):
        result = subprocess.run(
            [sys.executable, "-c", "import foundry, dispatcher"],
            capture_output=True,
            text=True,
            cwd=str(_ROOT),
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Import failed: {result.stderr[:500]}"
        )


# ==========================================================================
# EB3 dormancy: launch_recipe_claim_gaps has no non-test call sites
# ==========================================================================
class TestEB3_Dormancy:
    def test_no_call_sites_outside_tests(self):
        fn_name = GUARD_FN
        foundry_src = (_ROOT / "foundry.py").read_text(encoding="utf-8")
        hits = []
        for i, line in enumerate(foundry_src.splitlines(), 1):
            stripped = line.strip()
            if fn_name not in stripped:
                continue
            if stripped.startswith("def "):
                continue
            if stripped.startswith("#"):
                continue
            if stripped.startswith('"""') or stripped.startswith("'"):
                continue
            hits.append((i, stripped))
        assert hits == [], (
            f"{fn_name} should have no non-definition call sites in foundry.py: {hits}"
        )

    def test_not_called_in_dispatcher(self):
        fn_name = GUARD_FN
        disp_src = DISPATCHER_PATH.read_text(encoding="utf-8")
        call_sites = [
            line.strip()
            for line in disp_src.splitlines()
            if fn_name in line.strip() and not line.strip().startswith("#")
        ]
        assert call_sites == [], (
            f"{fn_name} should not be called in dispatcher.py: {call_sites}"
        )
