"""Black-box behaviour tests for iter 126 -- an UNFINISHED (killed-and-checkpointed)
tester report routes to further TESTER rounds instead of the `fix-tests` pass.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-126 PM spec
(products/_platform/state/iter-126/pm.md -- Expected Behaviors 7-12, the tester's half
of the mandated test routing) plus the product's own OBSERVABLE surface: importing the
bare modules and DRIVING their public orchestrators through the established
monkeypatchable module-level seams, and reading the SHIPPED role card `roles/tester.md`
(which for behavior 12 IS the deliverable). The implementation source of foundry.py /
dispatcher.py, the engineer's notes, the reviewer's notes and any `git diff` content
were NOT read. Fully offline and deterministic: scripted seams only -- no subprocess, no
git, no network, no clock, no real agent run. Every path is built at RUNTIME from the
bare module's __file__, so no machine-specific home path is ever a source literal.

Behaviors 1-6 (the two pure helpers + the constant) are the ENGINEER's unit-test half
per the spec's mandatory Test routing section; this file deliberately does not duplicate
them, and instead proves the constant is the LIVE source of the retry stage list by
patching it and observing the stage order change.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)

# --------------------------------------------------------------------------
# runtime-built paths + fixed values (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
TESTER_CARD = _ROOT / "roles" / "tester.md"

ITER = 126
BASE = "base0000"
NEWHEAD = "newhead99"
POST_SENTINEL = "POSTRELEASE: HEALTHY"
MARKER = "PROGRESS: CHECKPOINT"

# default body for any stage the test does not script: approves, passes, ships.
SHIP_BODY = "VERDICT: APPROVE\nRESULT: PASS\nACTION: PUSHED " + NEWHEAD + "\n"

# a killed tester round's checkpoint: the marker AND the required sentinel.
UNFINISHED_BODY = (
    "Isolation contract honored.\n"
    "Covered behaviors 7-8; 9-12 still missing, round cut short.\n"
    + MARKER + "\n"
    "RESULT: FAIL\n"
)
# a genuinely red suite: the sentinel, no marker.
RED_BODY = (
    "Isolation contract honored.\n"
    "test_b09_red FAILED: assert 'a' == 'b'\n"
    "RESULT: FAIL\n"
)
PASS_BODY = "Isolation contract honored.\nRESULT: PASS\n"

DEFAULT_LABELS = ["pm", "engineer", "reviewer", "tester", "final"]
RED_LABELS = ["pm", "engineer", "reviewer", "tester",
              "fix-tests", "tester-rerun", "final"]
UNFINISHED_LABELS = ["pm", "engineer", "reviewer", "tester",
                     "tester-retry", "final"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir: repo/work_root are TMP so the real
    foundry repo and state tree are NEVER touched."""
    tmp_path = pathlib.Path(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    n = len(list(tmp_path.glob("cfg_*.json")))
    p = tmp_path / ("cfg_%d.json" % n)
    p.write_text(json.dumps(data))
    return p


def _cfg(tmp_path, **over):
    return foundry.load_config(str(_write_cfg(tmp_path, **over)))


def _iter_dir(cfg, iteration):
    return pathlib.Path(cfg.state) / ("iter-%02d" % iteration)


def _make_run_stage(triples, results, reports):
    """Scripted run_stage: record the ORDERED (stage, role_file, out_name) triple,
    write the scripted report CONTENT to the real out file (so the orchestrator's
    own read of that path sees the marker/sentinel), and return (ok, path).
    `results` maps stage label -> ok bool (default True); `reports` maps stage
    label -> file content (default SHIP_BODY)."""
    def run_stage(cfg, iteration, stage, role_file, out_name, extra=""):
        triples.append((stage, role_file, out_name))
        d = _iter_dir(cfg, iteration)
        d.mkdir(parents=True, exist_ok=True)
        out = d / out_name
        out.write_text(reports.get(stage, SHIP_BODY))
        return results.get(stage, True), out
    return run_stage


def _patch_seams(monkeypatch, triples, reverts, results, reports, *, head):
    monkeypatch.setattr(foundry, "run_stage",
                        _make_run_stage(triples, results, reports))
    monkeypatch.setattr(foundry, "head_of_branch", head)
    monkeypatch.setattr(foundry, "revert_repo", lambda *a, **k: reverts.append(a))
    monkeypatch.setattr(
        foundry, "postrelease_step",
        lambda *a, **k: foundry.PostReleaseResult(True, False, POST_SENTINEL))
    monkeypatch.setattr(foundry, "next_iteration", lambda *a, **k: ITER)
    monkeypatch.setattr(foundry, "log", lambda *a, **k: None)
    monkeypatch.setattr(foundry, "power_state",
                        lambda: "Now drawing from 'AC Power'")


def _drive_iteration(monkeypatch, tmp_path, *, reports=None, results=None):
    """LIVE PATH 1 -- foundry.run_iteration through its default fixed pipeline."""
    cfg = _cfg(tmp_path)
    triples, reverts = [], []
    seq = [BASE, NEWHEAD]

    def head(c):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    _patch_seams(monkeypatch, triples, reverts, results or {}, reports or {},
                 head=head)
    monkeypatch.setattr(foundry, "iteration_is_scouted", lambda c, n: True)
    monkeypatch.setattr(foundry, "refresh_directions_file", lambda c: True)
    res = foundry.run_iteration(cfg, ITER)
    return res, triples, reverts


def _drive_plan(monkeypatch, tmp_path, *, reports=None, results=None):
    """LIVE PATH 2 -- foundry.run_execution_plan on the DEFAULT derived plan."""
    cfg = _cfg(tmp_path)
    triples, reverts = [], []
    _patch_seams(monkeypatch, triples, reverts, results or {}, reports or {},
                 head=lambda c: NEWHEAD)
    plan = foundry.derive_execution_plan(foundry._default_stage_sequence())
    res = foundry.run_execution_plan(cfg, ITER, plan, BASE)
    return res, triples, reverts


DRIVERS = [_drive_iteration, _drive_plan]
DRIVER_IDS = ["run_iteration", "run_execution_plan"]


def _labels(triples):
    return [t[0] for t in triples]


def _retries(labels):
    return [x for x in labels if x.startswith("tester-retry")]


# ==========================================================================
# Behavior 12 -- the card contract that makes the marker MANDATED, not emergent
# ==========================================================================
def test_b12_card_mandates_the_checkpoint_marker():
    card = TESTER_CARD.read_text(encoding="utf-8")
    assert MARKER in card, (
        "roles/tester.md must carry the literal marker %r that the classifier "
        "reads; without it the marker stays an emergent convention" % MARKER)


def test_b12_card_mandates_the_behavior_test_file_before_prose():
    card = TESTER_CARD.read_text(encoding="utf-8")
    upper = card.upper()
    assert "FILE FIRST" in upper, (
        "roles/tester.md duty 1 must be FILE-FIRST (create the behavior-test "
        "file before writing prose)")
    assert "tests/test_iter" in card, (
        "roles/tester.md must name the tests/test_iter<NN>_behavior.py file the "
        "round has to create first")


def test_b12_card_still_requires_the_result_sentinel():
    card = TESTER_CARD.read_text(encoding="utf-8")
    assert "RESULT: PASS" in card and "RESULT: FAIL" in card, (
        "the checkpoint contract ADDS the marker and KEEPS the sentinel: a "
        "report with no RESULT: FAIL never reaches the repair branch at all")


# ==========================================================================
# Behavior 7 -- UNFINISHED routes to ONE tester retry, not fix-tests
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b07_unfinished_runs_one_tester_retry_and_ships(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(
        monkeypatch, tmp_path,
        reports={"tester": UNFINISHED_BODY, "tester-retry": PASS_BODY})
    labels = _labels(triples)
    assert labels == UNFINISHED_LABELS, labels
    assert "fix-tests" not in labels
    assert "tester-rerun" not in labels
    assert res["status"] == "shipped"
    assert reverts == []


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b07_retry_uses_the_tester_card_and_tester2_outfile(drive, monkeypatch, tmp_path):
    _res, triples, _reverts = drive(
        monkeypatch, tmp_path,
        reports={"tester": UNFINISHED_BODY, "tester-retry": PASS_BODY})
    assert ("tester-retry", "tester.md", "tester2.md") in triples, triples


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b07_a_red_first_retry_still_stops_the_retry_chain(drive, monkeypatch, tmp_path):
    """Stop EARLY as soon as a round no longer classifies UNFINISHED -- including
    when that round is a genuinely RED report (not only when it is PASS)."""
    _res, triples, _reverts = drive(
        monkeypatch, tmp_path,
        reports={"tester": UNFINISHED_BODY, "tester-retry": RED_BODY})
    labels = _labels(triples)
    assert _retries(labels) == ["tester-retry"], labels


# ==========================================================================
# Behavior 8 -- a second UNFINISHED buys a SECOND retry, and never a third
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b08_second_unfinished_runs_tester_retry2(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(
        monkeypatch, tmp_path,
        reports={"tester": UNFINISHED_BODY, "tester-retry": UNFINISHED_BODY,
                 "tester-retry2": PASS_BODY})
    labels = _labels(triples)
    assert _retries(labels) == ["tester-retry", "tester-retry2"], labels
    assert labels.index("tester-retry") < labels.index("tester-retry2")
    assert ("tester-retry2", "tester.md", "tester3.md") in triples, triples
    assert "fix-tests" not in labels and "tester-rerun" not in labels
    assert res["status"] == "shipped"
    assert reverts == []


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b08_all_unfinished_never_runs_a_third_retry(drive, monkeypatch, tmp_path):
    _res, triples, _reverts = drive(
        monkeypatch, tmp_path,
        reports={"tester": UNFINISHED_BODY, "tester-retry": UNFINISHED_BODY,
                 "tester-retry2": UNFINISHED_BODY})
    labels = _labels(triples)
    assert _retries(labels) == ["tester-retry", "tester-retry2"], labels
    assert "tester-retry3" not in labels
    assert labels.count("tester") == 1


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b08_retry_stage_list_is_read_from_the_patchable_constant(drive, monkeypatch, tmp_path):
    """The module-level constant is the LIVE source of the retry stages, so a
    patched list changes the observable stage order."""
    monkeypatch.setattr(foundry, "UNFINISHED_TEST_RETRY_STAGES",
                        (("tester-probe", "testerp.md"),))
    _res, triples, _reverts = drive(
        monkeypatch, tmp_path,
        reports={"tester": UNFINISHED_BODY, "tester-probe": PASS_BODY})
    labels = _labels(triples)
    assert "tester-probe" in labels, labels
    assert ("tester-probe", "tester.md", "testerp.md") in triples, triples
    assert _retries(labels) == []


# ==========================================================================
# Behavior 9 -- byte-identical RED regression guard
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b09_red_report_runs_todays_exact_fix_tests_pair(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(
        monkeypatch, tmp_path, reports={"tester": RED_BODY})
    labels = _labels(triples)
    assert labels == RED_LABELS, labels
    assert ("fix-tests", "fix.md", "fix_tests.md") in triples, triples
    assert ("tester-rerun", "tester.md", "tester2.md") in triples, triples
    assert _retries(labels) == []
    assert res["status"] == "shipped"
    assert reverts == []


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b09_red_fix_tests_failure_reverts_once_as_today(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(
        monkeypatch, tmp_path, reports={"tester": RED_BODY},
        results={"fix-tests": False})
    assert res["status"] == "infra-fail"
    assert res["iteration"] == ITER
    assert len(reverts) == 1
    assert "tester-rerun" not in _labels(triples)


# ==========================================================================
# Behavior 10 -- an earned PASS runs no repair stage of any kind
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b10_pass_runs_no_repair_or_retry_stage(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(
        monkeypatch, tmp_path, reports={"tester": PASS_BODY})
    labels = _labels(triples)
    assert labels == DEFAULT_LABELS, labels
    assert "fix-tests" not in labels and "tester-rerun" not in labels
    assert _retries(labels) == []
    assert res["status"] == "shipped"
    assert reverts == []


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b10_earned_pass_outranks_a_stale_checkpoint_marker(drive, monkeypatch, tmp_path):
    """A report that carries the marker but ENDS in RESULT: PASS is a finished
    round: no retry, no fix pass (spec behavior 1, observed on the live path)."""
    body = "Notes.\n" + MARKER + "\nRecovered in this round.\nRESULT: PASS\n"
    res, triples, reverts = drive(
        monkeypatch, tmp_path, reports={"tester": body})
    labels = _labels(triples)
    assert labels == DEFAULT_LABELS, labels
    assert res["status"] == "shipped"
    assert reverts == []


# ==========================================================================
# Behavior 11 -- a failing retry reverts exactly once, and never more than RED
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b11_first_retry_failure_reverts_once_and_infra_fails(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(
        monkeypatch, tmp_path, reports={"tester": UNFINISHED_BODY},
        results={"tester-retry": False})
    labels = _labels(triples)
    assert res["status"] == "infra-fail"
    assert res["iteration"] == ITER
    assert set(res) == {"status", "stage", "iteration"}
    assert isinstance(res["stage"], str) and res["stage"]
    assert len(reverts) == 1
    assert "final" not in labels
    assert "tester-retry2" not in labels


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b11_second_retry_failure_reverts_once(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(
        monkeypatch, tmp_path,
        reports={"tester": UNFINISHED_BODY, "tester-retry": UNFINISHED_BODY},
        results={"tester-retry2": False})
    assert res["status"] == "infra-fail"
    assert len(reverts) == 1
    assert "final" not in _labels(triples)


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b11_unfinished_never_reverts_more_than_red(drive, monkeypatch, tmp_path):
    """The UNFINISHED class adds NO new revert path: under the SAME failing-stage
    script it can never revert more often than today's RED class."""
    script = {"fix-tests": False, "tester-rerun": False,
              "tester-retry": False, "tester-retry2": False}
    _r1, _t1, red_reverts = drive(
        monkeypatch, tmp_path, reports={"tester": RED_BODY}, results=script)
    _r2, _t2, unf_reverts = drive(
        monkeypatch, tmp_path, reports={"tester": UNFINISHED_BODY},
        results=script)
    assert len(unf_reverts) <= len(red_reverts), (
        "UNFINISHED reverted %d times vs RED %d"
        % (len(unf_reverts), len(red_reverts)))
    assert len(unf_reverts) == 1


# ==========================================================================
# import safety (ARCHITECTURE invariant: both modules stay importable)
# ==========================================================================
def test_both_modules_import():
    assert hasattr(foundry, "run_iteration")
    assert hasattr(foundry, "run_execution_plan")
    assert hasattr(dispatcher, "__file__")


# ==========================================================================
# TEETH PROOFS -- the disposition SEAM (not the substring) decides the route.
# Without these, every UNFINISHED assertion above could in principle pass for
# the wrong reason; with them, a broken/ignored classifier is observable.
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_teeth_disposition_seam_red_forces_todays_fix_pass(drive, monkeypatch, tmp_path):
    """Seam says RED for a body that LOOKS unfinished -> today's exact fix pair.
    This is the control for the whole UNFINISHED suite: it proves the routing is
    read from read_test_disposition by BARE name and is not hardcoded."""
    monkeypatch.setattr(foundry, "read_test_disposition", lambda p: "RED")
    res, triples, reverts = drive(
        monkeypatch, tmp_path, reports={"tester": UNFINISHED_BODY})
    labels = _labels(triples)
    assert labels == RED_LABELS, labels
    assert _retries(labels) == []
    assert res["status"] == "shipped"
    assert reverts == []


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_teeth_disposition_seam_unfinished_forces_retries(drive, monkeypatch, tmp_path):
    """Seam says UNFINISHED for a body with NO marker -> retries run anyway, so
    the branch is driven by the classification and not by a raw substring test."""
    monkeypatch.setattr(foundry, "read_test_disposition", lambda p: "UNFINISHED")
    _res, triples, _reverts = drive(
        monkeypatch, tmp_path,
        reports={"tester": RED_BODY, "tester-retry": PASS_BODY})
    labels = _labels(triples)
    assert "tester-retry" in labels, labels
    assert "fix-tests" not in labels


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_exhausted_retries_still_reach_the_final_gate(drive, monkeypatch, tmp_path):
    """When BOTH retries are themselves unfinished the pipeline does not revert on
    its own: it reaches `final`, whose gate item 2 (last tester report must be
    PASS) is the single place that decision belongs -- identical to a still-red
    RED class today."""
    _res, triples, reverts = drive(
        monkeypatch, tmp_path,
        reports={"tester": UNFINISHED_BODY, "tester-retry": UNFINISHED_BODY,
                 "tester-retry2": UNFINISHED_BODY})
    labels = _labels(triples)
    assert labels == ["pm", "engineer", "reviewer", "tester",
                      "tester-retry", "tester-retry2", "final"], labels
    assert reverts == []
