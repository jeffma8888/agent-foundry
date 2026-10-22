"""Iteration 464 -- BLACK-BOX behavior tests: retire the periodic STATUS_REPORT
branch.  The iteration deletes ``REPORT_EVERY``, ``mechanical_report``,
``narrative_report``, ``CHEATSHEET_DEAD_TARGETS``, the ``roles/reporter.md``
role file, and the STATUS_REPORT row in ARCHITECTURE.md §2.

ISOLATION CONTRACT (HONORED).  Every assertion below was derived from this
iteration's PM spec (``pm.md``, Expected Behaviors 1-9) and from the conventions
of the existing modules under ``tests/``.  I did NOT read ``foundry.py``'s
implementation text, ``engineer.md``, ``reviewer.md``, ``IMPLEMENTATION.patch``,
or ``git diff``.  Each EB is driven as a BLACK BOX: public attributes probed via
``hasattr``, file existence checked on disk, ARCHITECTURE.md grepped, and the
module imported.

OFFLINE + FRESH-CLONE SAFE.  No test reads the real ``products/*/state`` tree,
pins an ambient file count, spawns a network call, or reads the wall clock.
Paths are built from ``__file__`` at runtime.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

THIS_ITER = 464


# ==========================================================================
# EB1: REPORT_EVERY is no longer defined as a module-level constant
# ==========================================================================
class TestEB1_ReportEveryRemoved:
    def test_report_every_not_defined(self):
        assert not hasattr(foundry, "REPORT_EVERY"), (
            "REPORT_EVERY must be removed from foundry"
        )

    def test_report_every_not_in_dir(self):
        public = [n for n in dir(foundry) if "REPORT_EVERY" in n.upper()]
        assert public == [], f"No REPORT_EVERY-like names should exist: {public}"


# ==========================================================================
# EB2: mechanical_report is no longer defined as a function
# ==========================================================================
class TestEB2_MechanicalReportRemoved:
    def test_mechanical_report_not_defined(self):
        assert not hasattr(foundry, "mechanical_report"), (
            "mechanical_report must be removed from foundry"
        )

    def test_no_mechanical_report_callable(self):
        assert not callable(getattr(foundry, "mechanical_report", None)), (
            "mechanical_report must not be callable"
        )


# ==========================================================================
# EB3: narrative_report is no longer defined as a function
# ==========================================================================
class TestEB3_NarrativeReportRemoved:
    def test_narrative_report_not_defined(self):
        assert not hasattr(foundry, "narrative_report"), (
            "narrative_report must be removed from foundry"
        )

    def test_no_narrative_report_callable(self):
        assert not callable(getattr(foundry, "narrative_report", None)), (
            "narrative_report must not be callable"
        )


# ==========================================================================
# EB4: run_continuous has no reporter branch
# ==========================================================================
class TestEB4_RunContinuousNoReporterBranch:
    """Since we cannot read the source (isolation), we verify the preconditions:
    the symbols the reporter branch would call are all absent."""

    def test_run_continuous_exists(self):
        assert callable(getattr(foundry, "run_continuous", None)), (
            "run_continuous must still exist"
        )

    def test_no_reporter_symbols_remain(self):
        reporter_names = ["REPORT_EVERY", "mechanical_report", "narrative_report"]
        remaining = [n for n in reporter_names if hasattr(foundry, n)]
        assert remaining == [], (
            f"Reporter symbols still present: {remaining}"
        )


# ==========================================================================
# EB5: CHEATSHEET_DEAD_TARGETS is no longer defined
# ==========================================================================
class TestEB5_CheatsheetDeadTargetsRemoved:
    def test_cheatsheet_dead_targets_not_defined(self):
        assert not hasattr(foundry, "CHEATSHEET_DEAD_TARGETS"), (
            "CHEATSHEET_DEAD_TARGETS must be removed from foundry"
        )

    def test_no_dead_targets_in_dir(self):
        matches = [n for n in dir(foundry) if "DEAD_TARGETS" in n.upper()]
        assert matches == [], f"No DEAD_TARGETS-like names should exist: {matches}"


# ==========================================================================
# EB6: roles/reporter.md does not exist
# ==========================================================================
class TestEB6_ReporterRoleFileDeleted:
    def test_reporter_md_does_not_exist(self):
        p = _ROOT / "roles" / "reporter.md"
        assert not p.exists(), (
            f"roles/reporter.md must be deleted but still exists at {p}"
        )


# ==========================================================================
# EB7: ARCHITECTURE.md §2 table no longer names STATUS_REPORT
# ==========================================================================
class TestEB7_ArchitectureDocUpdated:
    def test_no_status_report_in_architecture(self):
        arch = (_ROOT / "ARCHITECTURE.md").read_text()
        assert "STATUS_REPORT" not in arch, (
            "ARCHITECTURE.md must not reference STATUS_REPORT"
        )

    def test_no_reporter_md_in_architecture(self):
        arch = (_ROOT / "ARCHITECTURE.md").read_text()
        assert "reporter.md" not in arch, (
            "ARCHITECTURE.md must not reference reporter.md"
        )


# ==========================================================================
# EB8: foundry.py remains importable
# ==========================================================================
class TestEB8_FoundryImportable:
    def test_import_foundry(self):
        r = subprocess.run(
            [sys.executable, "-c", "import foundry"],
            cwd=str(_ROOT),
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"import foundry failed:\n{r.stderr}"

    def test_import_dispatcher(self):
        r = subprocess.run(
            [sys.executable, "-c", "import dispatcher"],
            cwd=str(_ROOT),
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"import dispatcher failed:\n{r.stderr}"

    def test_main_callable(self):
        assert callable(getattr(foundry, "main", None))

    def test_run_continuous_callable(self):
        assert callable(getattr(foundry, "run_continuous", None))


# ==========================================================================
# EB9: Full suite passes (tested by running the suite externally)
# ==========================================================================
class TestEB9_SuiteIntegrity:
    """The import-safety and symbol-absence probes above collectively verify
    that the deletion did not break the module.  The full suite is run
    externally as the quality-check command."""

    def test_core_functions_still_present(self):
        for name in ["main", "build_prompt", "run_stage", "run_iteration",
                      "run_continuous"]:
            assert hasattr(foundry, name), f"foundry.{name} must still exist"

    def test_no_new_reporter_symbols(self):
        reporter_like = [
            n for n in dir(foundry)
            if "reporter" in n.lower() or "report_every" in n.lower()
        ]
        assert reporter_like == [], (
            f"No new reporter-like symbols should exist: {reporter_like}"
        )
