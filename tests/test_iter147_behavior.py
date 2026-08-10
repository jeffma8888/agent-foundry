"""Black-box behaviour tests for iter 147 -- BOTH review gates route on the ANCHORED
reviewer verdict (the last non-empty line) instead of an unanchored substring scan for
the fail token, mirroring the iter-127 test gate.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-147 PM spec
(products/_platform/state/iter-147/pm.md, Expected Behaviors 1-11), the conventions of
this tests/ tree (the twin module tests/test_iter127_behavior.py supplies both scripted
drivers and the harness shape; everything under tests/ is readable under the contract),
and the product's OWN OBSERVABLE surface -- importing the bare modules, calling the
public names, DRIVING both public orchestrators through the established module-level
seams, and reading public docstrings. The implementation source of foundry.py /
dispatcher.py, the engineer's notes, the reviewer's notes and any git-diff content were
NOT read, and no inspect.getsource appears anywhere in this file.

Every expected value here was MEASURED against the public surface with throwaway probes
in the gitignored state dir before being asserted, never guessed -- including the four
non-obvious ones: a bare fail token with no VERDICT prefix classifies NONE, a
VERDICT line that is not last classifies NONE, the I/O seam degrades to NONE (the
OPPOSITE token from its test-gate twin, on purpose), and the seams bite on the CONTROL
PATH of both orchestrators, not merely on direct calls.

Fully offline and deterministic: scripted seams only -- no git, no network, no clock, no
real agent run. The single subprocess is the import-safety probe. Every path is built at
RUNTIME from the bare module's __file__, so no machine-specific home path is ever a
source literal.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)

# --------------------------------------------------------------------------
# runtime-built paths + fixed values (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent

ITER = 147
BASE = "base0000"
NEWHEAD = "newhead99"
POST_SENTINEL = "POSTRELEASE: HEALTHY"
RELEASE_NEEDLE = "ACTION: PUSHED"
FAIL_TOKEN = "CHANGES_REQUIRED"
OK_TOKEN = "APPROVE"
NO_VERDICT = "NONE"
TOKENS = (OK_TOKEN, FAIL_TOKEN, NO_VERDICT)

# default body for any stage the test does not script: approves, passes, ships.
SHIP_BODY = "VERDICT: " + OK_TOKEN + "\nRESULT: PASS\n" + RELEASE_NEEDLE + " " + NEWHEAD + "\n"

# the anchored fail verdict -- the ONLY shape that may earn a fix-review round
CR_BODY = ("Isolation contract honored.\n"
           "[BLOCKING] the seam swallows a decode error.\n"
           "VERDICT: " + FAIL_TOKEN + "\n")

# THE false alarm this iteration removes: an APPROVE whose prose quotes the fail token
# because the reviewer was describing the review gate ITSELF (the measured shape of both
# spurious fleet fires, iter-146 and iter-70).
FALSE_ALARM_BODY = ("Isolation contract honored.\n"
                    "The gate routes review " + FAIL_TOKEN + " -> the fix-review triple,\n"
                    "which is exactly what this iteration anchors.\n"
                    "VERDICT: " + OK_TOKEN + "\n")

# quiet shapes: every one of these classifies NONE and must run NO fix pass
BARE_TOKEN_BODY = FAIL_TOKEN
NOT_LAST_BODY = "VERDICT: " + FAIL_TOKEN + "\naddendum prose follows\n"
EMPTY_BODY = ""
WS_BODY = "   \n\t\n"
MAYBE_BODY = "VERDICT: MAYBE\n"
BARE_VERDICT_BODY = "VERDICT:\n"
NO_VERDICT_BODY = "just prose, no verdict line\n"
LOWER_BODY = "verdict: changes_required\n"
QUIET_BODIES = (BARE_TOKEN_BODY, NOT_LAST_BODY, EMPTY_BODY, WS_BODY, MAYBE_BODY,
                BARE_VERDICT_BODY, NO_VERDICT_BODY, LOWER_BODY, SHIP_BODY)
QUIET_IDS = ("bare_token", "verdict_not_last", "empty", "whitespace", "unknown_token",
             "bare_verdict", "no_verdict_line", "lowercase", "ship_body")

DEFAULT_LABELS = ["pm", "engineer", "reviewer", "tester", "final"]
FIX_LABELS = ["pm", "engineer", "reviewer", "fix-review", "tester", "final"]
FIX_TRIPLE = ("fix-review", "fix.md", "fix_review.md")


# --------------------------------------------------------------------------
# helpers (shape follows tests/test_iter127_behavior.py)
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


def _make_run_stage(triples, results, reports, missing):
    """Scripted run_stage: record the ORDERED (stage, role_file, out_name) triple, write
    the scripted report CONTENT to the real out file (so the orchestrator's own read of
    that path sees the verdict), and return (ok, path). A stage named in `missing` is
    handed back a path that does NOT exist -- behavior 4 on the control path."""
    def run_stage(cfg, iteration, stage, role_file, out_name, extra=""):
        triples.append((stage, role_file, out_name))
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


def _patch_seams(monkeypatch, triples, reverts, results, reports, missing, *, head,
                 also=None):
    monkeypatch.setattr(foundry, "run_stage",
                        _make_run_stage(triples, results, reports, missing))
    monkeypatch.setattr(foundry, "head_of_branch", head)
    monkeypatch.setattr(foundry, "revert_repo", lambda *a, **k: reverts.append(a))
    monkeypatch.setattr(
        foundry, "postrelease_step",
        lambda *a, **k: foundry.PostReleaseResult(True, False, POST_SENTINEL))
    monkeypatch.setattr(foundry, "next_iteration", lambda *a, **k: ITER)
    monkeypatch.setattr(foundry, "log", lambda *a, **k: None)
    monkeypatch.setattr(foundry, "power_state",
                        lambda: "Now drawing from 'AC Power'")
    for name, value in (also or {}).items():
        monkeypatch.setattr(foundry, name, value)


def _drive_iteration(monkeypatch, tmp_path, *, reports=None, results=None,
                     missing=(), also=None):
    """LIVE PATH 1 -- foundry.run_iteration through its default fixed pipeline."""
    cfg = _cfg(tmp_path)
    triples, reverts = [], []
    seq = [BASE, NEWHEAD]

    def head(c):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    _patch_seams(monkeypatch, triples, reverts, results or {}, reports or {},
                 set(missing), head=head, also=also)
    monkeypatch.setattr(foundry, "iteration_is_scouted", lambda c, n: True)
    monkeypatch.setattr(foundry, "refresh_directions_file", lambda c: True)
    res = foundry.run_iteration(cfg, ITER)
    return res, triples, reverts


def _drive_plan(monkeypatch, tmp_path, *, reports=None, results=None,
                missing=(), also=None):
    """LIVE PATH 2 -- foundry.run_execution_plan on the DEFAULT derived plan."""
    cfg = _cfg(tmp_path)
    triples, reverts = [], []
    _patch_seams(monkeypatch, triples, reverts, results or {}, reports or {},
                 set(missing), head=lambda c: NEWHEAD, also=also)
    plan = foundry.derive_execution_plan(foundry._default_stage_sequence())
    res = foundry.run_execution_plan(cfg, ITER, plan, BASE)
    return res, triples, reverts


DRIVERS = [_drive_iteration, _drive_plan]
DRIVER_IDS = ["run_iteration", "run_execution_plan"]


def _labels(triples):
    return [t[0] for t in triples]


# ==========================================================================
# Behavior 1 -- classify_review_report is PURE, TOTAL and three-valued
# ==========================================================================
def test_b01_classifier_exists_at_module_level_with_a_docstring():
    assert hasattr(foundry, "classify_review_report"), "missing classify_review_report"
    assert callable(foundry.classify_review_report)
    doc = (foundry.classify_review_report.__doc__ or "").strip()
    assert doc, "classify_review_report needs a docstring saying WHY it exists"
    assert FAIL_TOKEN in doc and OK_TOKEN in doc


@pytest.mark.parametrize("text,expected", [
    ("", NO_VERDICT),
    ("   \n\t\n", NO_VERDICT),
    ("VERDICT: " + OK_TOKEN + "\n", OK_TOKEN),
    ("VERDICT: " + OK_TOKEN + "\n\n\n", OK_TOKEN),
    ("   VERDICT: " + OK_TOKEN + "   \n", OK_TOKEN),
    ("VERDICT: " + FAIL_TOKEN + "\n", FAIL_TOKEN),
    ("prose quoting " + FAIL_TOKEN + "\nVERDICT: " + FAIL_TOKEN + "\n", FAIL_TOKEN),
    (FALSE_ALARM_BODY, OK_TOKEN),
    (NO_VERDICT_BODY, NO_VERDICT),
    (MAYBE_BODY, NO_VERDICT),
    (BARE_VERDICT_BODY, NO_VERDICT),
    (NOT_LAST_BODY, NO_VERDICT),
    (BARE_TOKEN_BODY, NO_VERDICT),
    (LOWER_BODY, NO_VERDICT),
    (SHIP_BODY, NO_VERDICT),
], ids=["empty", "ws_only", "approve", "approve_trailing_blanks", "approve_lead_ws",
        "changes", "changes_with_prose_above", "approve_that_quotes_the_token",
        "no_verdict_line", "unknown_token", "bare_verdict", "verdict_not_last",
        "bare_token_only", "lowercase", "multi_sentinel_ship_body"])
def test_b01_classifier_truth_table(text, expected):
    assert foundry.classify_review_report(text) == expected


@pytest.mark.parametrize("text", [
    "", "\n", "   ", "\x00\x00", "VERDICT: " + OK_TOKEN,
    "VERDICT: " + OK_TOKEN + "\r\n", "\u4e2d\u6587\nVERDICT: " + OK_TOKEN + "\n",
    "x" * 50000 + "\nVERDICT: " + FAIL_TOKEN + "\n",
    "VERDICT: VERDICT: " + FAIL_TOKEN + "\n",
    "VERDICT: " + FAIL_TOKEN + " (with a trailing note)\n",
], ids=["empty", "newline", "spaces", "nul_bytes", "no_trailing_newline", "crlf",
        "unicode", "100k_body", "doubled_prefix", "token_plus_note"])
def test_b01_classifier_is_total_and_only_ever_returns_one_of_three_tokens(text):
    out = foundry.classify_review_report(text)
    assert out in TOKENS, (out, TOKENS)
    assert isinstance(out, str)


def test_b01_classifier_is_pure_and_repeatable():
    """Same input twice, and interleaved with other inputs, gives the same answer --
    no hidden module state, no memo that leaks between calls."""
    first = foundry.classify_review_report(CR_BODY)
    foundry.classify_review_report(FALSE_ALARM_BODY)
    foundry.classify_review_report(EMPTY_BODY)
    assert foundry.classify_review_report(CR_BODY) == first == FAIL_TOKEN


# ==========================================================================
# Behavior 2 -- the classifier delegates to parse_review_verdict by BARE name
# ==========================================================================
def test_b02_classifier_delegates_to_parse_review_verdict_by_bare_name(monkeypatch):
    monkeypatch.setattr(foundry, "parse_review_verdict", lambda t: FAIL_TOKEN)
    assert foundry.classify_review_report("VERDICT: " + OK_TOKEN + "\n") == FAIL_TOKEN
    monkeypatch.setattr(foundry, "parse_review_verdict", lambda t: OK_TOKEN)
    assert foundry.classify_review_report(CR_BODY) == OK_TOKEN


@pytest.mark.parametrize("rogue", ["MAYBE", "", "changes_required", None, 7],
                         ids=["unknown_token", "empty", "wrong_case", "none", "int"])
def test_b02_a_rogue_seam_value_cannot_leak_a_fourth_disposition(monkeypatch, rogue):
    """Behavior 1's enumeration is a promise about the FUNCTION, not about its
    collaborator: even a patched seam handing back something outside the token set must
    normalize, or a fourth disposition reaches a control-path gate."""
    monkeypatch.setattr(foundry, "parse_review_verdict", lambda t: rogue)
    out = foundry.classify_review_report("VERDICT: " + OK_TOKEN + "\n")
    assert out in TOKENS, out
    assert out != rogue or rogue in TOKENS
    assert foundry.needs_review_repair(out) is False


def test_b02_parse_review_verdict_itself_is_unchanged():
    """Acceptance criterion: this iteration WIRES the anchored parser, it does not edit
    it. Spot-check its own contract (18 assertions live in test_iter100_behavior.py)."""
    assert foundry.parse_review_verdict("VERDICT: " + OK_TOKEN + "\n") == OK_TOKEN
    assert foundry.parse_review_verdict("VERDICT: " + FAIL_TOKEN + "\n") == FAIL_TOKEN
    assert foundry.parse_review_verdict(MAYBE_BODY) is None
    assert foundry.parse_review_verdict("") is None
    assert foundry.parse_review_verdict(BARE_TOKEN_BODY) is None


# ==========================================================================
# Behavior 3 -- read_review_disposition is the single I/O seam
# ==========================================================================
@pytest.mark.parametrize("body,expected", [
    (CR_BODY, FAIL_TOKEN),
    (FALSE_ALARM_BODY, OK_TOKEN),
    (EMPTY_BODY, NO_VERDICT),
    (NO_VERDICT_BODY, NO_VERDICT),
    (NOT_LAST_BODY, NO_VERDICT),
    (BARE_TOKEN_BODY, NO_VERDICT),
], ids=["changes_required", "approve_quoting_token", "empty", "no_verdict",
        "verdict_not_last", "bare_token"])
def test_b03_seam_reads_the_file_and_returns_the_classifier_verdict(tmp_path, body, expected):
    p = pathlib.Path(tmp_path) / "review.md"
    p.write_text(body)
    assert foundry.read_review_disposition(p) == expected
    assert foundry.read_review_disposition(p) == foundry.classify_review_report(body)


def test_b03_seam_calls_the_classifier_by_bare_name(monkeypatch, tmp_path):
    p = pathlib.Path(tmp_path) / "review.md"
    p.write_text(CR_BODY)
    monkeypatch.setattr(foundry, "classify_review_report", lambda t: "SENTINEL_FROM_PATCH")
    assert foundry.read_review_disposition(p) == "SENTINEL_FROM_PATCH"


def test_b03_seam_has_a_docstring_that_names_the_split():
    doc = foundry.read_review_disposition.__doc__ or ""
    assert doc.strip(), "read_review_disposition needs a docstring"
    assert "classify_review_report" in doc


# ==========================================================================
# Behavior 4 -- a missing/unreadable path DEGRADES to NONE (no fix pass)
# ==========================================================================
def test_b04_missing_path_degrades_to_none(tmp_path):
    assert foundry.read_review_disposition(pathlib.Path(tmp_path) / "nope.md") == NO_VERDICT


def test_b04_unreadable_path_degrades_to_none(tmp_path):
    d = pathlib.Path(tmp_path) / "a_directory"
    d.mkdir()
    assert foundry.read_review_disposition(d) == NO_VERDICT


def test_b04_the_asymmetry_with_the_test_gate_twin_is_deliberate(tmp_path):
    """Positive control for the two tests above: the SAME unreadable inputs make the
    iter-127 twin return RED, so NONE here is a real decision (each seam degrades to
    ITS OWN pre-change route), not an accident of my inputs being readable."""
    missing = pathlib.Path(tmp_path) / "nope.md"
    d = pathlib.Path(tmp_path) / "dir2"
    d.mkdir()
    for arg in (missing, d):
        assert foundry.read_review_disposition(arg) == NO_VERDICT
        assert foundry.read_test_disposition(arg) == "RED"


def test_b04_docstring_says_why_it_degrades_to_none():
    doc = foundry.read_review_disposition.__doc__ or ""
    assert NO_VERDICT in doc
    assert "read_test_disposition" in doc, "must explain the opposite-token twin"


# ==========================================================================
# Behavior 5 -- the repair-disposition constant
# ==========================================================================
def test_b05_constant_is_exactly_the_fail_token():
    assert foundry.REVIEW_GATE_REPAIR_DISPOSITIONS == (FAIL_TOKEN,)


def test_b05_constant_is_an_immutable_tuple_of_str():
    c = foundry.REVIEW_GATE_REPAIR_DISPOSITIONS
    assert isinstance(c, tuple)
    assert all(isinstance(x, str) for x in c)
    with pytest.raises(TypeError):
        c[0] = "x"  # type: ignore[index]


# ==========================================================================
# Behavior 6 -- needs_review_repair is a PURE, TOTAL membership test
# ==========================================================================
@pytest.mark.parametrize("disp,expected", [
    (FAIL_TOKEN, True), (OK_TOKEN, False), (NO_VERDICT, False),
    ("", False), ("changes_required", False), ("MAYBE", False),
], ids=["changes_required", "approve", "none", "empty", "wrong_case", "unknown"])
def test_b06_predicate_truth_table(disp, expected):
    assert foundry.needs_review_repair(disp) is expected


def test_b06_none_is_out_of_the_repair_set():
    """The measured reason iter-127 kept NONE out: routing drivers write an unscripted
    stage report as the empty string, which classifies NONE."""
    assert NO_VERDICT not in foundry.REVIEW_GATE_REPAIR_DISPOSITIONS
    assert foundry.needs_review_repair(NO_VERDICT) is False
    assert foundry.needs_review_repair(foundry.classify_review_report("")) is False


@pytest.mark.parametrize("value", [None, 0, 7, ("CHANGES_REQUIRED",), [], object()],
                         ids=["none", "zero", "int", "tuple", "list", "object"])
def test_b06_predicate_is_total_and_never_raises(value):
    assert foundry.needs_review_repair(value) is False  # type: ignore[arg-type]


def test_b06_predicate_reads_the_constant_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "REVIEW_GATE_REPAIR_DISPOSITIONS", (OK_TOKEN,))
    assert foundry.needs_review_repair(OK_TOKEN) is True
    assert foundry.needs_review_repair(FAIL_TOKEN) is False


def test_b06_an_empty_constant_disables_every_repair(monkeypatch):
    monkeypatch.setattr(foundry, "REVIEW_GATE_REPAIR_DISPOSITIONS", ())
    for d in TOKENS:
        assert foundry.needs_review_repair(d) is False


# ==========================================================================
# Behaviors 7 + 9 -- an ANCHORED fail verdict still routes the fix-review round,
# on BOTH orchestrators
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b07_anchored_changes_required_runs_fix_review_then_continues(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(monkeypatch, tmp_path, reports={"reviewer": CR_BODY})
    labels = _labels(triples)
    assert labels == FIX_LABELS, labels
    assert labels.index("fix-review") == labels.index("reviewer") + 1, labels
    assert FIX_TRIPLE in triples, triples
    assert res["status"] == "shipped", res
    assert reverts == []


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b07_bare_anchored_verdict_line_is_enough(drive, monkeypatch, tmp_path):
    _res, triples, _reverts = drive(
        monkeypatch, tmp_path, reports={"reviewer": "VERDICT: " + FAIL_TOKEN + "\n"})
    assert _labels(triples) == FIX_LABELS, _labels(triples)


# ==========================================================================
# Behavior 8 -- THE DEFECT: an APPROVE that merely MENTIONS the fail token in
# prose runs NO fix-review round (the single most important assertion here)
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b08_approve_that_quotes_the_fail_token_runs_no_fix_review(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(
        monkeypatch, tmp_path, reports={"reviewer": FALSE_ALARM_BODY})
    labels = _labels(triples)
    assert "fix-review" not in labels, labels
    assert labels == DEFAULT_LABELS, labels
    assert res["status"] == "shipped", res
    assert reverts == []


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b08_positive_control_the_same_prose_ending_in_the_fail_token_does_route(
        drive, monkeypatch, tmp_path):
    """Two-sided proof the test above is not vacuous: move the verdict of the very same
    prose to the fail token and the fix-review round must reappear."""
    body = FALSE_ALARM_BODY.replace("VERDICT: " + OK_TOKEN, "VERDICT: " + FAIL_TOKEN)
    _res, triples, _reverts = drive(monkeypatch, tmp_path, reports={"reviewer": body})
    assert _labels(triples) == FIX_LABELS, _labels(triples)


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
@pytest.mark.parametrize("body", QUIET_BODIES, ids=QUIET_IDS)
def test_b08_every_unanchored_shape_stays_quiet(drive, monkeypatch, tmp_path, body):
    _res, triples, _reverts = drive(monkeypatch, tmp_path, reports={"reviewer": body})
    assert "fix-review" not in _labels(triples), (body, _labels(triples))


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b08_a_missing_reviewer_report_runs_no_fix_review(drive, monkeypatch, tmp_path):
    """Behavior 4 on the CONTROL PATH, not just a direct seam call."""
    res, triples, reverts = drive(monkeypatch, tmp_path, missing=("reviewer",))
    assert _labels(triples) == DEFAULT_LABELS, _labels(triples)
    assert res["status"] == "shipped", res
    assert reverts == []


# ==========================================================================
# Behaviors 7 + 9 -- the gate is WIRED through the new names (patching each of
# them on the control path changes the routing), and a fix-review failure still
# reverts with the unchanged status dict
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
@pytest.mark.parametrize("name,value", [
    ("read_review_disposition", staticmethod(lambda p: FAIL_TOKEN)),
    ("classify_review_report", staticmethod(lambda t: FAIL_TOKEN)),
    ("needs_review_repair", staticmethod(lambda d: True)),
    ("REVIEW_GATE_REPAIR_DISPOSITIONS", (OK_TOKEN,)),
], ids=["io_seam", "classifier", "predicate", "constant"])
def test_b09_each_new_name_can_force_the_gate_on(drive, monkeypatch, tmp_path, name, value):
    """The only evidence separating "the new reader works" from "the new reader is
    CALLED": force each name in turn over a body whose real verdict is APPROVE."""
    v = value.__func__ if isinstance(value, staticmethod) else value
    _res, triples, _reverts = drive(
        monkeypatch, tmp_path, reports={"reviewer": "VERDICT: " + OK_TOKEN + "\n"},
        also={name: v})
    assert _labels(triples) == FIX_LABELS, (name, _labels(triples))


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
@pytest.mark.parametrize("name,value", [
    ("read_review_disposition", staticmethod(lambda p: NO_VERDICT)),
    ("needs_review_repair", staticmethod(lambda d: False)),
    ("REVIEW_GATE_REPAIR_DISPOSITIONS", ()),
], ids=["io_seam", "predicate", "constant"])
def test_b09_each_new_name_can_force_the_gate_off(drive, monkeypatch, tmp_path, name, value):
    v = value.__func__ if isinstance(value, staticmethod) else value
    _res, triples, _reverts = drive(
        monkeypatch, tmp_path, reports={"reviewer": CR_BODY}, also={name: v})
    assert _labels(triples) == DEFAULT_LABELS, (name, _labels(triples))


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b09_fix_review_failure_still_reverts_and_infra_fails(drive, monkeypatch, tmp_path):
    res, triples, reverts = drive(
        monkeypatch, tmp_path, reports={"reviewer": CR_BODY},
        results={"fix-review": False})
    assert res["status"] == "infra-fail", res
    assert res["stage"] == "fix-review", res
    assert res["iteration"] == ITER, res
    assert len(reverts) == 1, reverts
    assert _labels(triples) == ["pm", "engineer", "reviewer", "fix-review"], _labels(triples)


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b09_status_dict_shape_is_unchanged_on_the_quiet_path(drive, monkeypatch, tmp_path):
    res, _triples, _reverts = drive(
        monkeypatch, tmp_path, reports={"reviewer": FALSE_ALARM_BODY})
    assert set(res) >= {"status", "iteration"}, res
    assert res["iteration"] == ITER, res


# ==========================================================================
# Behavior 10 -- STRICTLY NARROWING: a new fire implies the old substring
# trigger would also have fired
# ==========================================================================
def _narrowing_corpus():
    tokens = [OK_TOKEN, FAIL_TOKEN, "MAYBE", "", "changes_required",
              FAIL_TOKEN + " extra"]
    shapes = ["VERDICT: %s\n", "VERDICT: %s", "  VERDICT: %s  \n\n",
              "prose\nVERDICT: %s\n", "VERDICT: %s\ntrailing prose\n", "%s\n",
              "text %s text\n", "VERDICT: %s\nVERDICT: " + OK_TOKEN + "\n",
              "VERDICT: " + OK_TOKEN + "\nVERDICT: %s\n", "- verdict %s -\n\n\n"]
    corpus = [s % t for t in tokens for s in shapes]
    corpus += ["", "\n\n", "   ", NO_VERDICT_BODY, BARE_VERDICT_BODY, SHIP_BODY,
               CR_BODY, FALSE_ALARM_BODY]
    return corpus


def test_b10_new_gate_never_fires_where_the_old_substring_trigger_did_not():
    corpus = _narrowing_corpus()
    new_fires, old_fires, violations = 0, 0, []
    for t in corpus:
        fires = foundry.needs_review_repair(foundry.classify_review_report(t))
        old = FAIL_TOKEN in t
        new_fires += bool(fires)
        old_fires += bool(old)
        if fires and not old:
            violations.append(t)
    assert violations == [], violations
    # positive controls: a matcher that matched NOTHING also reports zero violations
    assert old_fires > 0, old_fires
    assert new_fires > 0, new_fires
    assert new_fires < old_fires, (new_fires, old_fires)


def test_b10_the_narrowing_is_strict_on_the_measured_false_alarm_shape():
    """The gap between the two triggers is exactly the false-alarm class."""
    assert FAIL_TOKEN in FALSE_ALARM_BODY                      # old trigger fires
    assert foundry.classify_review_report(FALSE_ALARM_BODY) == OK_TOKEN
    assert foundry.needs_review_repair(
        foundry.classify_review_report(FALSE_ALARM_BODY)) is False   # new one does not


# ==========================================================================
# Behavior 11 -- neither gate hands the fail token to the shared contains seam
# ==========================================================================
@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
@pytest.mark.parametrize("body,expected_labels",
                         [(CR_BODY, FIX_LABELS), (FALSE_ALARM_BODY, DEFAULT_LABELS)],
                         ids=["gate_fires", "gate_quiet"])
def test_b11_no_gate_substring_scans_for_the_fail_token(drive, monkeypatch, tmp_path,
                                                        body, expected_labels):
    """Spy on the shared `contains` seam. The release gate still uses it, so the release
    needle is the positive control proving the spy was installed and this assertion
    cannot fail open."""
    real = foundry.contains
    needles = []

    def spy(path, needle):
        needles.append(needle)
        return real(path, needle)

    monkeypatch.setattr(foundry, "contains", spy)
    _res, triples, _reverts = drive(monkeypatch, tmp_path, reports={"reviewer": body})
    assert FAIL_TOKEN not in needles, needles
    assert RELEASE_NEEDLE in needles, needles      # positive control
    assert _labels(triples) == expected_labels, _labels(triples)


# ==========================================================================
# Acceptance criteria that are observable black-box
# ==========================================================================
def test_ac_bare_modules_import_in_a_clean_interpreter():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_ac_public_signatures_are_unchanged():
    import inspect
    assert str(inspect.signature(foundry.run_iteration)) == \
        "(cfg: 'ProductConfig', iteration: 'int | None' = None) -> 'dict'"
    assert str(inspect.signature(foundry.parse_review_verdict)) == \
        "(text: 'str') -> 'str | None'"
    assert list(inspect.signature(foundry.run_execution_plan).parameters) == \
        ["cfg", "iteration", "plan", "base"]


def test_ac_the_new_names_mirror_the_iter127_test_gate_shape():
    """Naming/shape parity is a spec requirement so the two gates stay legible as one
    pattern: same arity, same return kinds."""
    import inspect
    pairs = [("classify_review_report", "classify_test_report"),
             ("read_review_disposition", "read_test_disposition"),
             ("needs_review_repair", "needs_test_repair")]
    for review_name, test_name in pairs:
        rf = getattr(foundry, review_name)
        tf = getattr(foundry, test_name)
        assert list(inspect.signature(rf).parameters) == \
            list(inspect.signature(tf).parameters), (review_name, test_name)
    assert isinstance(foundry.TEST_GATE_REPAIR_DISPOSITIONS, tuple)
    assert isinstance(foundry.REVIEW_GATE_REPAIR_DISPOSITIONS, tuple)
