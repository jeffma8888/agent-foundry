"""Iteration 457 -- BLACK-BOX behavior tests: roadmap STATUS paragraph currency + dormant guard.

Spec under test: products/_platform/state/iter-457/pm.md (5 Expected Behaviors).

  EB1: The PLATFORM_ROADMAP.md STATUS paragraph names an iteration >= 450 (was 323)
       and is otherwise structurally unchanged (still a parenthetical listing the
       known never-shipped iterations).
  EB2: A pure function `roadmap_status_currency_gaps(index_text, latest_iter)` exists
       at module level in `foundry.py`, callable by bare name.  It returns a list of
       gap descriptions (empty when the stated iteration is within 10 of latest_iter;
       non-empty when the lag exceeds 10).
  EB3: The function is DORMANT: no call site in foundry.py, dispatcher.py, or any
       role card.
  EB4: When the STATUS paragraph says "current through 450" and latest_iter is 457,
       the function returns an empty list (lag 7 <= 10).
  EB5: When the STATUS paragraph says "current through 323" and latest_iter is 457,
       the function returns a non-empty list (lag 134 > 10).

ISOLATION CONTRACT (HONORED): written ONLY from the iter-457 PM spec, the
module's public API (`roadmap_status_currency_gaps`), the roadmap file, and
existing test conventions under tests/.  The implementation source of
foundry.py / dispatcher.py was NOT read, and neither were engineer.md,
reviewer.md, IMPLEMENTATION.patch, or git diff.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

import foundry

THIS_ITER = 457
ROADMAP_PATH = pathlib.Path(__file__).resolve().parent.parent / "PLATFORM_ROADMAP.md"


# ---------------------------------------------------------------------------
# EB1 -- STATUS paragraph names iteration >= 450, structure preserved
# ---------------------------------------------------------------------------

class TestEB1StatusParagraphCurrency:
    """The STATUS paragraph names an iteration >= 450 and keeps its structure."""

    def test_b1_status_line_exists_and_names_iter_gte_450(self):
        text = ROADMAP_PATH.read_text(encoding="utf-8")
        m = re.search(r"^STATUS\s*\(iter\s+(\d+)\)", text, re.MULTILINE)
        assert m is not None, "STATUS (iter N) line not found in roadmap"
        stated_iter = int(m.group(1))
        assert stated_iter >= 450, (
            f"STATUS paragraph names iter {stated_iter}, expected >= 450"
        )

    def test_b1_parenthetical_never_shipped_list_present(self):
        text = ROADMAP_PATH.read_text(encoding="utf-8")
        m = re.search(r"^STATUS\s*\(iter\s+\d+\):\s*(.+)", text, re.MULTILINE)
        assert m is not None, "STATUS line not found"
        rest = m.group(1)
        assert "never" in rest.lower() or "shipped" in rest.lower(), (
            "STATUS paragraph lost its never-shipped parenthetical structure"
        )

    def test_b1_status_line_still_on_line_30_area(self):
        lines = ROADMAP_PATH.read_text(encoding="utf-8").splitlines()
        found = False
        for i, line in enumerate(lines, 1):
            if line.startswith("STATUS (iter"):
                found = True
                assert 25 <= i <= 40, (
                    f"STATUS line moved to line {i}, expected near line 30"
                )
                break
        assert found, "STATUS line not found at all"


# ---------------------------------------------------------------------------
# EB2 -- roadmap_status_currency_gaps exists, callable, returns list
# ---------------------------------------------------------------------------

class TestEB2FunctionExistsAndReturnsLst:
    """roadmap_status_currency_gaps is module-level, callable, returns list."""

    def test_b2_function_exists_at_module_level(self):
        assert hasattr(foundry, "roadmap_status_currency_gaps"), (
            "foundry module missing roadmap_status_currency_gaps"
        )

    def test_b2_function_is_callable(self):
        assert callable(foundry.roadmap_status_currency_gaps), (
            "roadmap_status_currency_gaps is not callable"
        )

    def test_b2_returns_list_on_normal_input(self):
        text = "STATUS (iter 450): ledger current through 450"
        result = foundry.roadmap_status_currency_gaps(text, 457)
        assert isinstance(result, list), (
            f"expected list, got {type(result)}"
        )

    def test_b2_returns_list_on_empty_input(self):
        result = foundry.roadmap_status_currency_gaps("", 457)
        assert isinstance(result, list), (
            f"expected list on empty input, got {type(result)}"
        )

    def test_b2_returns_list_on_missing_status_line(self):
        result = foundry.roadmap_status_currency_gaps("no status here", 100)
        assert isinstance(result, list), (
            f"expected list on missing STATUS, got {type(result)}"
        )


# ---------------------------------------------------------------------------
# EB3 -- dormant: no call site in foundry.py / dispatcher.py / roles/
# ---------------------------------------------------------------------------

class TestEB3Dormant:
    """roadmap_status_currency_gaps has no call site in production code."""

    def test_b3_no_call_site_in_foundry_py(self):
        repo = ROADMAP_PATH.parent
        src = (repo / "foundry.py").read_text(encoding="utf-8")
        calls = [
            line for line in src.splitlines()
            if "roadmap_status_currency_gaps" in line
            and not line.lstrip().startswith("def ")
            and not line.lstrip().startswith("#")
            and not line.lstrip().startswith("_STATUS")
        ]
        assert not calls, (
            f"unexpected call site(s) in foundry.py: {calls}"
        )

    def test_b3_no_call_site_in_dispatcher_py(self):
        repo = ROADMAP_PATH.parent
        dp = repo / "dispatcher.py"
        if dp.exists():
            src = dp.read_text(encoding="utf-8")
            hits = [
                line for line in src.splitlines()
                if "roadmap_status_currency_gaps" in line
            ]
            assert not hits, (
                f"unexpected call site(s) in dispatcher.py: {hits}"
            )

    def test_b3_no_call_site_in_roles(self):
        repo = ROADMAP_PATH.parent
        roles_dir = repo / "roles"
        if roles_dir.is_dir():
            for md in roles_dir.rglob("*.md"):
                text = md.read_text(encoding="utf-8")
                assert "roadmap_status_currency_gaps" not in text, (
                    f"unexpected reference in {md.name}"
                )


# ---------------------------------------------------------------------------
# EB4 -- lag 7 (450→457) returns empty list
# ---------------------------------------------------------------------------

class TestEB4SmallLagReturnsEmpty:
    """When stated iter is within 10 of latest_iter, result is empty."""

    def test_b4_lag_7_returns_empty(self):
        text = "STATUS (iter 450): ledger and archive are current through 450"
        result = foundry.roadmap_status_currency_gaps(text, 457)
        assert result == [], (
            f"lag 7: expected [], got {result}"
        )

    def test_b4_lag_10_returns_empty(self):
        text = "STATUS (iter 447): ledger and archive are current through 447"
        result = foundry.roadmap_status_currency_gaps(text, 457)
        assert result == [], (
            f"lag 10: expected [], got {result}"
        )

    def test_b4_lag_0_returns_empty(self):
        text = "STATUS (iter 457): current through 457"
        result = foundry.roadmap_status_currency_gaps(text, 457)
        assert result == [], (
            f"lag 0: expected [], got {result}"
        )

    def test_b4_negative_lag_returns_empty(self):
        text = "STATUS (iter 460): current through 460"
        result = foundry.roadmap_status_currency_gaps(text, 457)
        assert result == [], (
            f"negative lag: expected [], got {result}"
        )


# ---------------------------------------------------------------------------
# EB5 -- lag 134 (323→457) returns non-empty list
# ---------------------------------------------------------------------------

class TestEB5LargeLagReturnsNonEmpty:
    """When stated iter lags latest_iter by more than 10, result is non-empty."""

    def test_b5_lag_134_returns_non_empty(self):
        text = "STATUS (iter 323): ledger and archive are current through 323"
        result = foundry.roadmap_status_currency_gaps(text, 457)
        assert len(result) > 0, (
            f"lag 134: expected non-empty list, got {result}"
        )

    def test_b5_lag_11_returns_non_empty(self):
        text = "STATUS (iter 446): ledger and archive are current through 446"
        result = foundry.roadmap_status_currency_gaps(text, 457)
        assert len(result) > 0, (
            f"lag 11: expected non-empty list, got {result}"
        )

    def test_b5_result_items_are_strings(self):
        text = "STATUS (iter 323): ledger and archive are current through 323"
        result = foundry.roadmap_status_currency_gaps(text, 457)
        assert len(result) > 0
        for item in result:
            assert isinstance(item, str), (
                f"gap description should be str, got {type(item)}"
            )

    def test_b5_lag_50_returns_non_empty(self):
        text = "STATUS (iter 400): current through 400"
        result = foundry.roadmap_status_currency_gaps(text, 457)
        assert len(result) > 0, (
            f"lag 57: expected non-empty list, got {result}"
        )


# ---------------------------------------------------------------------------
# Boundary & robustness -- additional coverage
# ---------------------------------------------------------------------------

class TestBoundaryAndRobustness:
    """Boundary behavior at lag=10/11 and edge cases."""

    def test_boundary_lag_exactly_10_empty(self):
        text = "STATUS (iter 90): current through 90"
        result = foundry.roadmap_status_currency_gaps(text, 100)
        assert result == [], (
            f"lag exactly 10: expected [], got {result}"
        )

    def test_boundary_lag_exactly_11_non_empty(self):
        text = "STATUS (iter 89): current through 89"
        result = foundry.roadmap_status_currency_gaps(text, 100)
        assert len(result) > 0, (
            f"lag exactly 11: expected non-empty, got {result}"
        )

    def test_missing_status_returns_empty(self):
        result = foundry.roadmap_status_currency_gaps("some unrelated text", 457)
        assert result == [], (
            f"missing STATUS: expected [], got {result}"
        )

    def test_empty_string_returns_empty(self):
        result = foundry.roadmap_status_currency_gaps("", 457)
        assert result == [], (
            f"empty string: expected [], got {result}"
        )


# ---------------------------------------------------------------------------
# Import safety -- foundry and dispatcher remain importable
# ---------------------------------------------------------------------------

class TestImportSafety:
    """Both foundry and dispatcher modules import without error."""

    def test_foundry_importable(self):
        import foundry as f
        assert hasattr(f, "__file__")

    def test_dispatcher_importable(self):
        import dispatcher as d
        assert hasattr(d, "__file__")
