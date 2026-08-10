"""Black-box behaviour tests for iter 127 -- the pipeline's test gate routes on the
ANCHORED tester disposition instead of an unanchored substring scan of the report.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-127 PM spec
(products/_platform/state/iter-127/pm.md, Expected Behaviors 1-13) plus the product's
own OBSERVABLE surface -- importing the bare modules, DRIVING their public orchestrators
through the established module-level seams, reading public docstrings, and running the
CLI's own --help. The implementation source of foundry.py / dispatcher.py, the
engineer's notes, the reviewer's notes and any git-diff content were NOT read.
Conventions and the two scripted drivers follow the sibling module
tests/test_iter126_behavior.py (everything under tests/ is readable under the contract).

Every expected classification in this module was MEASURED against the public
classifier before being asserted (throwaway probe in the gitignored state dir), not
guessed -- including the two nonobvious ones: a body carrying the checkpoint marker but
ALSO an earned pass sentinel classifies PASS (so the marker alone does not buy a retry),
and a fail sentinel that is not the last non-empty line classifies as no-verdict.

Fully offline and deterministic: scripted seams only -- no git, no network, no clock, no
real agent run. The single subprocess is behavior 12's own literal import probe. Every
path is built at RUNTIME from the bare module's __file__, so no machine-specific home
path is ever a source literal.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (behavior 12 import-safety probe)

# --------------------------------------------------------------------------
# runtime-built paths + fixed values (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent

ITER = 127
BASE = "base0000"
NEWHEAD = "newhead99"
POST_SENTINEL = "POSTRELEASE: HEALTHY"
MARKER = "PROGRESS: CHECKPOINT"
FAIL_SENTINEL = "RESULT: FAIL"
PASS_SENTINEL = "RESULT: PASS"
RELEASE_NEEDLE = "ACTION: PUSHED"

# default body for any stage the test does not script: approves, passes, ships.
SHIP_BODY = "VERDICT: APPROVE\n" + PASS_SENTINEL + "\n" + RELEASE_NEEDLE + " " + NEWHEAD + "\n"

# THE false alarm this iteration removes: an EARNED pass whose prose happens to quote
# the fail sentinel (6 of 19 fires in the PM's fleet measurement were this shape).
FALSE_ALARM_BODY = (
    "Isolation contract honored.\n"
    "Note for the PM: a report whose last line is " + FAIL_SENTINEL + " is what\n"
    "triggers the repair round; this round did not need one.\n"
    + PASS_SENTINEL + "\n"
)
# THE new rescue: a killed round that checkpointed the marker and never got to write
# any verdict sentinel at all.
MARKER_ONLY_BODY = (
    "Isolation contract honored.\n"
    "Covered behaviors 1-3; 4-13 still missing, round cut short.\n"
    + MARKER + "\n"
)
# unchanged classes
UNFINISHED_BODY = (
    "Isolation contract honored.\n"
    "Round cut short.\n" + MARKER + "\n" + FAIL_SENTINEL + "\n"
)
RED_BODY = (
    "Isolation contract honored.\n"
    "test_b04_false_alarm FAILED: assert 'a' == 'b'\n" + FAIL_SENTINEL + "\n"
)
PASS_BODY = "Isolation contract honored.\n" + PASS_SENTINEL + "\n"

# the three no-verdict shapes: empty, unknown token, fail sentinel not last.
EMPTY_BODY = ""
UNKNOWN_TOKEN_BODY = "Isolation contract honored.\nRESULT: MAYBE\n"
FAIL_NOT_LAST_BODY = (
    "Isolation contract honored.\n" + FAIL_SENTINEL + "\n"
    "Addendum: the table above lists the classes.\n"
)

DEFAULT_LABELS = ["pm", "engineer", "reviewer", "tester", "final"]
RED_LABELS = ["pm", "engineer", "reviewer", "tester",
              "fix-tests", "tester-rerun", "final"]
UNFINISHED_LABELS = ["pm", "engineer", "reviewer", "tester",
                     "tester-retry", "final"]
REPAIR_LABELS = ("fix-tests", "tester-rerun")


# --------------------------------------------------------------------------
# helpers (shape follows tests/test_iter126_behavior.py)
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


def _make_run_stage(triples, results, reports, extras, missing):
    """Scripted run_stage: record the ORDERED (stage, role_file, out_name) triple and
    the extra prompt, write the scripted report CONTENT to the real out file (so the
    orchestrator's own read of that path sees the marker/sentinel), and return
    (ok, path). A stage named in `missing` is handed back a path that does NOT exist,
    which is behavior 9's unreadable-report drive."""
    def run_stage(cfg, iteration, stage, role_file, out_name, extra=""):
        triples.append((stage, role_file, out_name))
        extras.append((stage, extra))
        d = _iter_dir(cfg, iteration)
        d.mkdir(parents=True, exist_ok=True)
        out = d / out_name
        if stage in missing:
            if out.exists():
                out.unlink()
            return results.get(stage, True), out
        out.write_text(reports.get(stage, SHIP_BODY))
        return results.get(stage, True), out
    return run_stage


def _patch_seams(monkeypatch, triples, reverts, results, reports, extras, missing,
                 *, head):
    monkeypatch.setattr(foundry, "run_stage",
                        _make_run_stage(triples, results, reports, extras, missing))
    monkeypatch.setattr(foundry, "head_of_branch", head)
    monkeypatch.setattr(foundry, "revert_repo", lambda *a, **k: reverts.append(a))
    monkeypatch.setattr(
        foundry, "postrelease_step",
        lambda *a, **k: foundry.PostReleaseResult(True, False, POST_SENTINEL))
    monkeypatch.setattr(foundry, "next_iteration", lambda *a, **k: ITER)
    monkeypatch.setattr(foundry, "log", lambda *a, **k: None)
    monkeypatch.setattr(foundry, "power_state",
                        lambda: "Now drawing from 'AC Power'")


def _drive_iteration(monkeypatch, tmp_path, *, reports=None, results=None,
                     missing=(), extras=None):
    """LIVE PATH 1 -- foundry.run_iteration through its default fixed pipeline."""
    cfg = _cfg(tmp_path)
    triples, reverts = [], []
    if extras is None:
        extras = []
    seq = [BASE, NEWHEAD]

    def head(c):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    _patch_seams(monkeypatch, triples, reverts, results or {}, reports or {},
                 extras, set(missing), head=head)
    monkeypatch.setattr(foundry, "iteration_is_scouted", lambda c, n: True)
    monkeypatch.setattr(foundry, "refresh_directions_file", lambda c: True)
    res = foundry.run_iteration(cfg, ITER)
    res["_state_root"] = cfg.state
    return res, triples, reverts


def _drive_plan(monkeypatch, tmp_path, *, reports=None, results=None,
                missing=(), extras=None):
    """LIVE PATH 2 -- foundry.run_execution_plan on the DEFAULT derived plan."""
    cfg = _cfg(tmp_path)
    triples, reverts = [], []
    if extras is None:
        extras = []
    _patch_seams(monkeypatch, triples, reverts, results or {}, reports or {},
                 extras, set(missing), head=lambda c: NEWHEAD)
    plan = foundry.derive_execution_plan(foundry._default_stage_sequence())
    res = foundry.run_execution_plan(cfg, ITER, plan, BASE)
    res["_state_root"] = cfg.state
    return res, triples, reverts


DRIVERS = [_drive_iteration, _drive_plan]
DRIVER_IDS = ["run_iteration", "run_execution_plan"]


def _labels(triples):
    return [t[0] for t in triples]


def _retries(labels):
    return [x for x in labels if x.startswith("tester-retry")]


# ==========================================================================
# Behavior 1 -- the predicate exists at module level, is PURE and TOTAL
# ==========================================================================
def test_b01_predicate_exists_at_module_level_and_is_callable():
    assert hasattr(foundry, "needs_test_repair"), (
        "behavior 1: foundry.needs_test_repair must exist at module level")
    assert callable(foundry.needs_test_repair)


def test_b01_predicate_name_is_not_pytest_collectable():
    """The spec forbids a test_-prefixed name: pytest would try to collect it."""
    assert not foundry.needs_test_repair.__name__.startswith("test_")


def test_b01_predicate_has_a_docstring_saying_why():
    doc = (foundry.needs_test_repair.__doc__ or "")
    assert doc.strip(), "behavior 1/acceptance: the predicate must be documented"


@pytest.mark.parametrize(
    "value",
    ["", " ", "\n", "\t\t", "PASS", "RED", "UNFINISHED", "NONE",
     "pass", "red", "unfinished", "MAYBE", "RESULT: FAIL",
     "UNFINISHED\nRED", "RED ", " RED", "0", "None",
     "\u00fcnicode-disposition", "\u4e2d\u6587", "\U0001f600",
     "x" * 100000],
    ids=lambda v: "len%d" % len(v))
def test_b01_predicate_is_total_never_raises_and_returns_a_bool(value):
    out = foundry.needs_test_repair(value)
    assert isinstance(out, bool), (value[:40], type(out))


def test_b01_predicate_is_pure_no_state_and_no_mutation():
    before = foundry.TEST_GATE_REPAIR_DISPOSITIONS
    first = [foundry.needs_test_repair(v) for v in ("RED", "PASS", "", "RED")]
    second = [foundry.needs_test_repair(v) for v in ("RED", "PASS", "", "RED")]
    assert first == second == [True, False, False, True]
    assert foundry.TEST_GATE_REPAIR_DISPOSITIONS is before


# ==========================================================================
# Behavior 2 -- the repair set is exactly the two dispositions that earned it
# ==========================================================================
def test_b02_repair_dispositions_constant_is_unfinished_and_red():
    assert foundry.TEST_GATE_REPAIR_DISPOSITIONS == ("UNFINISHED", "RED")


def test_b02_constant_is_an_immutable_tuple():
    assert isinstance(foundry.TEST_GATE_REPAIR_DISPOSITIONS, tuple)


@pytest.mark.parametrize("disp,expected", [
    ("UNFINISHED", True), ("RED", True),
    ("PASS", False), ("NONE", False), ("", False),
    ("pass", False), ("red", False), ("MAYBE", False),
])
def test_b02_predicate_truth_table(disp, expected):
    assert foundry.needs_test_repair(disp) is expected, disp


@pytest.mark.parametrize(
    "disp", ["UNFINISHED", "RED", "PASS", "NONE", "", "MAYBE", "unfinished"])
def test_b02_predicate_is_true_iff_member_of_the_constant(disp):
    assert (foundry.needs_test_repair(disp)
            is (disp in foundry.TEST_GATE_REPAIR_DISPOSITIONS))


def test_b02_an_earned_pass_is_the_only_class_that_skips_repair():
    """The whole point: PASS and NONE are quiet, the other two are not."""
    quiet = [d for d in ("PASS", "NONE", "UNFINISHED", "RED")
             if not foundry.needs_test_repair(d)]
    assert quiet == ["PASS", "NONE"]


# ==========================================================================
# Behavior 3 -- the constant is read at CALL time, not captured at def time
# ==========================================================================
def test_b03_constant_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "TEST_GATE_REPAIR_DISPOSITIONS", ("PASS",))
    assert foundry.needs_test_repair("PASS") is True
    assert foundry.needs_test_repair("RED") is False


def test_b03_empty_constant_disables_every_repair(monkeypatch):
    monkeypatch.setattr(foundry, "TEST_GATE_REPAIR_DISPOSITIONS", ())
    assert [foundry.needs_test_repair(d)
            for d in ("UNFINISHED", "RED", "PASS", "NONE")] == [False] * 4


# ==========================================================================
# Behavior 4 -- FALSE-ALARM FIX: an earned PASS that merely quotes the fail
# sentinel in prose spends NO repair round (32% of today's fires)
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b04_earned_pass_quoting_the_sentinel_runs_no_repair(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(
        monkeypatch, tmp_path, reports={"tester": FALSE_ALARM_BODY})
    labels = _labels(triples)
    assert labels == DEFAULT_LABELS, labels
    for lab in REPAIR_LABELS:
        assert lab not in labels, labels
    assert _retries(labels) == [], labels
    assert res["status"] == "shipped", res
    assert reverts == []


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b04_positive_control_the_same_prose_ending_red_does_route(drive, monkeypatch, tmp_path):
    """Two-sided proof the b04 test is not vacuous: move the sentinel to the LAST
    line of the very same prose and the repair pair must appear."""
    body = FALSE_ALARM_BODY.replace(PASS_SENTINEL + "\n", FAIL_SENTINEL + "\n")
    _res, triples, _reverts = drive(monkeypatch, tmp_path, reports={"tester": body})
    labels = _labels(triples)
    assert labels == RED_LABELS, labels


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
@pytest.mark.parametrize("body,extra_disp", [
    (FALSE_ALARM_BODY, "PASS"), (EMPTY_BODY, "NONE")],
    ids=["earned_pass", "no_verdict"])
def test_b04_teeth_the_quiet_classes_are_quiet_because_of_the_new_constant(
        drive, body, extra_disp, monkeypatch, tmp_path):
    """CONTROL TEST for behaviors 4 and 8: admit the quiet disposition into the live
    repair set and the SAME report must now route into a repair round. Without this,
    a green b04/b08 could not be told apart from a gate that never routes at all."""
    monkeypatch.setattr(foundry, "TEST_GATE_REPAIR_DISPOSITIONS",
                        foundry.TEST_GATE_REPAIR_DISPOSITIONS + (extra_disp,))
    _res, triples, _reverts = drive(monkeypatch, tmp_path, reports={"tester": body})
    labels = _labels(triples)
    assert labels != DEFAULT_LABELS, labels
    assert ("fix-tests" in labels) or _retries(labels), labels


# ==========================================================================
# Behavior 5 -- NEW RESCUE: marker present, fail sentinel absent -> tester retry
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b05_marker_without_the_sentinel_buys_a_tester_retry(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(
        monkeypatch, tmp_path,
        reports={"tester": MARKER_ONLY_BODY, "tester-retry": PASS_BODY})
    labels = _labels(triples)
    assert labels == UNFINISHED_LABELS, labels
    assert ("tester-retry", "tester.md", "tester2.md") in triples, triples
    for lab in REPAIR_LABELS:
        assert lab not in labels, labels
    assert res["status"] == "shipped", res
    assert reverts == []


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b05_rescue_round_carries_the_unfinished_retry_prompt(drive, monkeypatch, tmp_path):
    extras = []
    drive(monkeypatch, tmp_path,
          reports={"tester": MARKER_ONLY_BODY, "tester-retry": PASS_BODY},
          extras=extras)
    got = dict(extras)
    assert got["tester-retry"] == foundry.UNFINISHED_TEST_RETRY_PROMPT, got["tester-retry"][:200]


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b05_rescue_stops_as_soon_as_a_retry_is_no_longer_unfinished(drive, monkeypatch, tmp_path):
    _res, triples, _reverts = drive(
        monkeypatch, tmp_path,
        reports={"tester": MARKER_ONLY_BODY, "tester-retry": PASS_BODY,
                 "tester-retry2": PASS_BODY})
    assert _retries(_labels(triples)) == ["tester-retry"], _labels(triples)


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b05_two_marker_only_rounds_buy_both_retries_then_final(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(
        monkeypatch, tmp_path,
        reports={"tester": MARKER_ONLY_BODY, "tester-retry": MARKER_ONLY_BODY,
                 "tester-retry2": PASS_BODY})
    labels = _labels(triples)
    assert _retries(labels) == ["tester-retry", "tester-retry2"], labels
    assert ("tester-retry2", "tester.md", "tester3.md") in triples, triples
    assert labels[-1] == "final"
    assert res["status"] == "shipped", res
    assert reverts == []


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b05_marker_with_an_earned_pass_is_still_a_pass(drive, monkeypatch, tmp_path):
    """MEASURED nuance worth pinning: the marker does NOT override an earned pass
    sentinel on the last line, so a finished round that mentions the marker in prose
    does not buy itself extra rounds."""
    body = MARKER_ONLY_BODY + "all behaviors now covered\n" + PASS_SENTINEL + "\n"
    _res, triples, _reverts = drive(monkeypatch, tmp_path, reports={"tester": body})
    assert _labels(triples) == DEFAULT_LABELS, _labels(triples)


# ==========================================================================
# Behavior 6 -- RED is byte-for-byte the same pair as before this iteration
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b06_red_report_runs_todays_exact_fix_tests_pair(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(monkeypatch, tmp_path, reports={"tester": RED_BODY})
    labels = _labels(triples)
    assert labels == RED_LABELS, labels
    assert ("fix-tests", "fix.md", "fix_tests.md") in triples, triples
    assert ("tester-rerun", "tester.md", "tester2.md") in triples, triples
    assert _retries(labels) == [], labels
    assert res["status"] == "shipped", res
    assert reverts == []


def test_b06_both_twins_send_identical_repair_prompts(monkeypatch, tmp_path):
    """The two call sites are mirrors: same labels, same role files, same out files
    and the SAME extra prompt strings for the RED pair. The prompts embed the gate
    file's own absolute path, so each twin's tmp state root is normalised away first."""
    seen = []
    for i, drive in enumerate(DRIVERS):
        extras = []
        res, triples, _reverts = drive(
            monkeypatch, tmp_path / ("d%d" % i), reports={"tester": RED_BODY},
            extras=extras)
        root = str(res["_state_root"])
        seen.append((triples,
                     {k: v.replace(root, "<STATE>") for k, v in dict(extras).items()}))
    assert seen[0][0] == seen[1][0], seen
    for lab in REPAIR_LABELS:
        assert seen[0][1][lab] == seen[1][1][lab], lab
        assert seen[0][1][lab].strip(), lab
    assert seen[0][1]["tester-rerun"] != foundry.UNFINISHED_TEST_RETRY_PROMPT


# ==========================================================================
# Behavior 7 -- UNFINISHED (marker + anchored sentinel) unchanged
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b07_unfinished_runs_one_retry_and_ships(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(
        monkeypatch, tmp_path,
        reports={"tester": UNFINISHED_BODY, "tester-retry": PASS_BODY})
    labels = _labels(triples)
    assert labels == UNFINISHED_LABELS, labels
    for lab in REPAIR_LABELS:
        assert lab not in labels, labels
    assert res["status"] == "shipped", res
    assert reverts == []


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b07_all_unfinished_reaches_final_and_never_reverts_itself(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(
        monkeypatch, tmp_path,
        reports={"tester": UNFINISHED_BODY, "tester-retry": UNFINISHED_BODY,
                 "tester-retry2": UNFINISHED_BODY})
    labels = _labels(triples)
    assert _retries(labels) == ["tester-retry", "tester-retry2"], labels
    assert "tester-retry3" not in labels
    assert labels[-1] == "final"
    assert reverts == [], reverts
    assert res["status"] == "shipped", res


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b07_retry_chain_breaks_on_the_first_non_unfinished_round(drive, monkeypatch, tmp_path):
    _res, triples, _reverts = drive(
        monkeypatch, tmp_path,
        reports={"tester": UNFINISHED_BODY, "tester-retry": RED_BODY})
    assert _retries(_labels(triples)) == ["tester-retry"], _labels(triples)


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b07_retry_stage_list_is_still_read_from_the_patchable_constant(drive, monkeypatch, tmp_path):
    monkeypatch.setattr(foundry, "UNFINISHED_TEST_RETRY_STAGES",
                        (("tester-probe", "testerp.md"),))
    _res, triples, _reverts = drive(
        monkeypatch, tmp_path,
        reports={"tester": UNFINISHED_BODY, "tester-probe": PASS_BODY})
    assert ("tester-probe", "tester.md", "testerp.md") in triples, triples
    assert _retries(_labels(triples)) == []


# ==========================================================================
# Behavior 8 -- NO-VERDICT stays quiet (this is what keeps pre-127 tests green)
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
@pytest.mark.parametrize("body", [EMPTY_BODY, UNKNOWN_TOKEN_BODY, FAIL_NOT_LAST_BODY],
                         ids=["empty", "unknown_token", "sentinel_not_last"])
def test_b08_no_verdict_runs_no_repair_stage(drive, body, monkeypatch, tmp_path):
    res, triples, reverts = drive(monkeypatch, tmp_path, reports={"tester": body})
    labels = _labels(triples)
    assert labels == DEFAULT_LABELS, labels
    for lab in REPAIR_LABELS:
        assert lab not in labels, labels
    assert _retries(labels) == [], labels
    assert res["status"] == "shipped", res
    assert reverts == []


# ==========================================================================
# Behavior 9 -- FAIL-CLOSED: an unreadable report is RED, not silence
# ==========================================================================
def test_b09_missing_report_path_yields_red(tmp_path):
    assert foundry.read_test_disposition(tmp_path / "nope.md") == "RED"


def test_b09_unreadable_report_path_yields_red(tmp_path):
    d = tmp_path / "a_directory_not_a_file"
    d.mkdir()
    assert foundry.read_test_disposition(d) == "RED"


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b09_missing_tester_report_routes_the_red_path(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(monkeypatch, tmp_path, missing=("tester",))
    labels = _labels(triples)
    assert labels == RED_LABELS, labels
    assert ("fix-tests", "fix.md", "fix_tests.md") in triples, triples
    assert res["status"] == "shipped", res
    assert reverts == []


# ==========================================================================
# Behavior 10 -- routing is derived ONLY from the read_test_disposition seam
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b10_seam_forces_red_over_an_unfinished_looking_body(drive, monkeypatch, tmp_path):
    monkeypatch.setattr(foundry, "read_test_disposition", lambda p: "RED")
    _res, triples, _reverts = drive(
        monkeypatch, tmp_path, reports={"tester": MARKER_ONLY_BODY})
    assert _labels(triples) == RED_LABELS, _labels(triples)


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b10_seam_forces_retries_over_a_body_with_no_marker(drive, monkeypatch, tmp_path):
    monkeypatch.setattr(foundry, "read_test_disposition", lambda p: "UNFINISHED")
    _res, triples, _reverts = drive(
        monkeypatch, tmp_path, reports={"tester": PASS_BODY})
    labels = _labels(triples)
    assert _retries(labels) == ["tester-retry", "tester-retry2"], labels
    for lab in REPAIR_LABELS:
        assert lab not in labels, labels


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b10_seam_forces_quiet_over_a_red_body(drive, monkeypatch, tmp_path):
    monkeypatch.setattr(foundry, "read_test_disposition", lambda p: "PASS")
    _res, triples, _reverts = drive(
        monkeypatch, tmp_path, reports={"tester": RED_BODY})
    assert _labels(triples) == DEFAULT_LABELS, _labels(triples)


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b10_test_gate_no_longer_substring_scans_for_the_fail_sentinel(drive, monkeypatch, tmp_path):
    """Spy on the shared `contains` seam: the release gate still uses it, the test
    gate must not. The positive control (the release needle IS seen) proves the spy
    is wired and the assertion cannot fail open. iter-147 moved the REVIEW gate off
    `contains` onto the anchored verdict too, so the review needle is no longer a
    valid control here -- the release needle alone carries that job now."""
    real = foundry.contains
    needles = []

    def spy(path, needle):
        needles.append(needle)
        return real(path, needle)

    monkeypatch.setattr(foundry, "contains", spy)
    _res, triples, _reverts = drive(
        monkeypatch, tmp_path, reports={"tester": RED_BODY})
    assert FAIL_SENTINEL not in needles, needles
    assert RELEASE_NEEDLE in needles, needles     # positive control
    assert _labels(triples) == RED_LABELS, _labels(triples)


# ==========================================================================
# Behavior 11 -- infra-fail keying and revert accounting unchanged
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b11_failed_fix_tests_keys_on_fix_tests_and_reverts_once(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(
        monkeypatch, tmp_path, reports={"tester": RED_BODY},
        results={"fix-tests": False})
    assert res["status"] == "infra-fail", res
    assert res["stage"] == "fix-tests", res
    assert res["iteration"] == ITER, res
    assert len(reverts) == 1, reverts
    labels = _labels(triples)
    assert "tester-rerun" not in labels, labels


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b11_failed_tester_rerun_also_keys_on_fix_tests(drive, monkeypatch, tmp_path):
    """Behavior 11 as written: a failing fix-tests OR tester-rerun both report
    stage == "fix-tests". MEASURED and pinned here because it reads like a defect but
    is the pre-127 behavior the spec requires to stay unchanged -- only the RESCUE
    round keys on its own label (next test)."""
    res, _triples, reverts = drive(
        monkeypatch, tmp_path, reports={"tester": RED_BODY},
        results={"tester-rerun": False})
    assert res["status"] == "infra-fail", res
    assert res["stage"] == "fix-tests", res
    assert len(reverts) == 1, reverts


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b11_failed_rescue_round_keys_on_the_retry_label(drive, monkeypatch, tmp_path):
    res, _triples, reverts = drive(
        monkeypatch, tmp_path, reports={"tester": MARKER_ONLY_BODY},
        results={"tester-retry": False})
    assert res["status"] == "infra-fail", res
    assert res["stage"] == "tester-retry", res
    assert len(reverts) == 1, reverts


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b11_failed_pm_still_does_not_revert(drive, monkeypatch, tmp_path):
    res, _triples, reverts = drive(
        monkeypatch, tmp_path, results={"pm": False})
    assert res["status"] == "infra-fail", res
    assert res["stage"] == "pm", res
    assert reverts == [], reverts


# ==========================================================================
# Behavior 12 -- import safety and NO new surface
# ==========================================================================
def test_b12_bare_modules_import_in_a_clean_interpreter():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]


def test_b12_no_new_config_field():
    fields = list(foundry.ProductConfig.__dataclass_fields__)
    assert len(fields) == 19, fields
    for f in fields:
        low = f.lower()
        assert "disposition" not in low and "repair" not in low, f


def test_b12_no_new_cli_verb():
    h = subprocess.run([sys.executable, "foundry.py", "--help"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert h.returncode == 0, h.stderr[-2000:]
    low = h.stdout.lower()
    assert "disposition" not in low
    assert "needs-test-repair" not in low and "needs_test_repair" not in low


def test_b12_no_new_module_level_verdict_sentinel_string():
    consts = sorted(k for k, v in vars(foundry).items()
                    if k.isupper() and isinstance(v, str) and "RESULT:" in v)
    assert consts == [], consts


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b12_state_layout_and_iteration_numbering_unchanged(drive, monkeypatch, tmp_path):
    res, _triples, _reverts = drive(
        monkeypatch, tmp_path, reports={"tester": MARKER_ONLY_BODY,
                                        "tester-retry": PASS_BODY})
    root = pathlib.Path(res["_state_root"])
    dirs = sorted(p.name for p in root.iterdir() if p.is_dir())
    assert dirs == ["iter-127"], dirs
    assert (root / "iter-127" / "tester2.md").exists()


# ==========================================================================
# Behavior 13 -- both twins document the anchored trigger truthfully
# ==========================================================================
@pytest.mark.parametrize("fn", [foundry.run_iteration, foundry.run_execution_plan],
                         ids=["run_iteration", "run_execution_plan"])
def test_b13_twin_docstring_no_longer_claims_a_substring_scan(fn):
    doc = fn.__doc__ or ""
    stale = "contains(report, \"" + FAIL_SENTINEL + "\")"
    assert stale not in doc, fn.__name__
    assert "contains(report, '" + FAIL_SENTINEL + "')" not in doc, fn.__name__


@pytest.mark.parametrize("fn", [foundry.run_iteration, foundry.run_execution_plan],
                         ids=["run_iteration", "run_execution_plan"])
def test_b13_twin_docstring_names_the_anchored_disposition(fn):
    doc = (fn.__doc__ or "").lower()
    assert "disposition" in doc, fn.__name__
    assert "read_test_disposition" in doc, fn.__name__
