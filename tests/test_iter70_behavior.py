"""Black-box behaviour tests for iter 70 -- roadmap item 19, bite 3b-i of 2.

This bite adds a DORMANT module-level run_execution_plan(cfg, iteration, plan,
base) -> dict to the main module: the manifest-driven pipeline EXECUTOR that
drives an arbitrary derive_execution_plan sequence through the pipeline BY GATE
KIND (pm / build / review / test / release / bench, including the conditional
fix-review and fix-tests+retest passes and the release ship + postrelease
branch), with ZERO call site. run_iteration is UNCHANGED. Bite 3b-ii (a later
iteration) wires the executor into run_iteration behind an absent-or-default
manifest guard; this bite's executor faithfully executes whatever plan it is
given (a total function).

ISOLATION CONTRACT (honored, with one disclosed deviation below): every test
here encodes the iter-70 PM spec's Expected Behaviors (1-12), driven purely
against the PUBLIC interface -- the importable public callables/constants
(foundry.run_execution_plan, foundry.derive_execution_plan, foundry.StagePlan,
foundry.StageSpec, foundry.derive_stage_sequence, foundry._default_stage_sequence,
foundry.load_config), the committed scripts/leak_guard.py public API, and
inspect.getsource / the dispatcher module's file text (used ONLY to assert the
SPEC's dormancy Behavior 11 and the new-content-ASCII Behavior 12, both
spec-mandated observables -- NOT to mirror implementation logic). The executor
behaviours are exercised with SCRIPTED SEAMS (monkeypatch run_stage /
head_of_branch / revert_repo / postrelease_step / log / power_state /
next_iteration by BARE module name) exactly as the iter-03 / iter-68
run_iteration tester did -- fully offline, deterministic, no network, no real git
push, no clock. A fake run_stage returns a real temp-file Path whose CONTENT
carries the sentinel it wants the executor's file read to match, and records the
ordered (stage, role_file, out_name) triples. The engineer's / reviewer's notes
and git diff text were NOT read as design input; assertions encode the SPEC's
behaviors, not impl quirks. Every path is built at RUNTIME from the bare module's
__file__ (never a source-literal home path), so the committed leak-guard passes
on the ship commit. DISCLOSED DEVIATION: the runner supplied prior-role iter
notes in the context digest, so complete blindness was not possible; nonetheless
every assertion below is derived from the pm.md spec's Expected Behaviors, not
from those notes -- the notes changed no expected value.

NB on Behavior 11 (dormant / purely additive): the spec's "numstat 0 deletions"
clause is an out-of-band reviewer / final-gate check (it reads a git diff, which
a tester in isolation does not). Here dormancy is proven via the SPEC-mandated
observables: zero call site (inspect.getsource of the four orchestrators + the
dispatcher module's text contain NEITHER the substring run_execution_plan), a
fresh-subprocess import, and a byte-unchanged control path via a `git diff
--quiet` exit-code-only check (emits NO diff text) on the dispatcher module +
scripts/.

NB on Behavior 12 (pure ASCII): the spec's "new content is pure ASCII" clause
means the NEWLY-ADDED symbol run_execution_plan, not the whole module -- the main
module already contains legitimate pre-existing non-ASCII (em-dash-dense
docstrings from prior iters), so a whole-file ASCII scan would FALSE-fail. The
new-content ASCII property is checked via inspect.getsource of the new symbol;
the authoritative ship-gate leak-cleanliness is checked via the committed
leak-guard scan of the whole main module text.

NB on the iter-54 meta-scanner: this file contains a `git diff --quiet` call, so
it must not carry the quoted main-module filename token on any non-comment line.
The main module is located via the BARE module's __file__; it is NOT pinned
byte-unchanged (it legitimately grows this iter). Only the dispatcher module +
scripts/ are pinned byte-unchanged (the control path).
"""
import importlib.util
import inspect
import json
import pathlib
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths + fixed expected values (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

BASE = "base0000"
NEWHEAD = "newhead99"
POST_SENTINEL = "POSTRELEASE: OK verified"
SHIP_KEYS = {"status", "head", "iteration", "postrelease"}

# the default plan's ordered (stage, role_file, out_name) triples (Behavior 1) --
# these are the spec's verbatim mirror of run_iteration's five core run_stage calls
DEFAULT_TRIPLES = [
    ("pm", "pm.md", "pm.md"),
    ("engineer", "engineer.md", "engineer.md"),
    ("reviewer", "reviewer.md", "reviewer.md"),
    ("tester", "tester.md", "tester.md"),
    ("final", "final.md", "final.md"),
]
DEFAULT_LABELS = [t[0] for t in DEFAULT_TRIPLES]

_GIT_OK = subprocess.run(
    ["git", "rev-parse", "--is-inside-work-tree"],
    cwd=str(_ROOT), capture_output=True, text=True,
).returncode == 0


# --------------------------------------------------------------------------
# helpers / fixtures (mirror the iter-03 / iter-68 run_iteration seam harness)
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    data = {
        "name": "demo",
        "repo": "{FOUNDRY}/ZZ/repo",
        "allowed_push_repo": "demo",
        "vision": "{FOUNDRY}/ZZ/VISION.md",
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    n = len(list(tmp_path.glob("cfg_*.json")))
    p = tmp_path / f"cfg_{n}.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def cfg(tmp_path):
    return foundry.load_config(str(_write_cfg(tmp_path)))


def _spec(seat, stage=None, role_file=None, out_file=None):
    """A StageSpec with convention fields; stage/role_file/out_file default off seat."""
    st = seat if stage is None else stage
    rf = (seat + ".md") if role_file is None else role_file
    of = (seat + ".md") if out_file is None else out_file
    return foundry.StageSpec(seat=seat, stage=st, role_file=rf, out_file=of)


class _Post:
    """Stand-in for postrelease_step's return: any object exposing `.sentinel`."""

    def __init__(self, sentinel):
        self.sentinel = sentinel


def _make_run_stage(recorder, stage_dir, results, reports):
    """Scripted run_stage: record the ORDERED (stage, role_file, out_name) triple,
    write the requested report CONTENT to a real temp file (so the executor's file
    read of that path sees the sentinel), and return (ok, path). `results` maps a
    stage label -> ok bool (default True); `reports` maps a stage label -> the file
    content the executor will inspect (default empty -> no CHANGES_REQUIRED /
    RESULT: FAIL / ACTION: PUSHED sentinel)."""
    counter = {"n": 0}

    def _run_stage(cfg, iteration, stage, role_file, out_name, extra=""):
        recorder.append((stage, role_file, out_name))
        counter["n"] += 1
        p = stage_dir / f"s{counter['n']:02d}_{stage}.txt"
        p.write_text(reports.get(stage, "") + "\n")
        return results.get(stage, True), p

    return _run_stage


def _drive(cfg, monkeypatch, tmp_path, plan, iteration, base,
           *, results=None, reports=None, head=NEWHEAD):
    """Run the executor once with fully scripted seams. Returns
    (result_dict, ordered_triples, reverts, posts, logs)."""
    stage_dir = pathlib.Path(tempfile.mkdtemp(dir=str(tmp_path)))
    triples, reverts, posts, logs = [], [], [], []
    monkeypatch.setattr(foundry, "run_stage",
                        _make_run_stage(triples, stage_dir, results or {}, reports or {}))
    monkeypatch.setattr(foundry, "head_of_branch", lambda c: head)
    monkeypatch.setattr(foundry, "revert_repo", lambda *a, **k: reverts.append(a))
    monkeypatch.setattr(foundry, "postrelease_step",
                        lambda *a, **k: (posts.append(a), _Post(POST_SENTINEL))[1])
    monkeypatch.setattr(foundry, "log", lambda *a, **k: logs.append(a))
    monkeypatch.setattr(foundry, "power_state", lambda: "Now drawing from 'AC Power'")
    monkeypatch.setattr(foundry, "next_iteration", lambda *a, **k: iteration)
    res = foundry.run_execution_plan(cfg, iteration, plan, base)
    return res, triples, reverts, posts, logs


def _labels(triples):
    return [t[0] for t in triples]


def _default_plan():
    return foundry.derive_execution_plan(foundry._default_stage_sequence())


def _leak_guard():
    """Dynamically import the committed leak-guard, registering it in sys.modules
    BEFORE exec so its own import machinery works."""
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter70_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# B1 -- Signature + default-plan bit-for-bit reproduction (clean ship)
# ==========================================================================
def test_b1_signature():
    sig = inspect.signature(foundry.run_execution_plan)
    assert list(sig.parameters) == ["cfg", "iteration", "plan", "base"]


def test_b1_default_plan_clean_ship_reproduces_orchestrator(cfg, monkeypatch, tmp_path):
    res, triples, reverts, posts, _ = _drive(
        cfg, monkeypatch, tmp_path, _default_plan(), 70, BASE,
        reports={"final": "ACTION: PUSHED " + NEWHEAD})
    # EXACT ordered run_stage triples == run_iteration's five core stages
    assert triples == DEFAULT_TRIPLES
    # ship return dict, bit-for-bit
    assert res == {"status": "shipped", "head": NEWHEAD,
                   "iteration": 70, "postrelease": POST_SENTINEL}
    assert set(res) == SHIP_KEYS
    assert reverts == []            # a clean ship reverts nothing
    assert len(posts) == 1          # postrelease ran exactly once


# ==========================================================================
# B2 -- pm-gate failure -> infra-fail, NO revert (nothing built yet)
# ==========================================================================
def test_b2_pm_fail_infra_no_revert(cfg, monkeypatch, tmp_path):
    res, triples, reverts, posts, _ = _drive(
        cfg, monkeypatch, tmp_path, _default_plan(), 70, BASE,
        results={"pm": False})
    assert res == {"status": "infra-fail", "stage": "pm", "iteration": 70}
    assert reverts == []            # pm-gate is the ONLY non-reverting fail path
    assert _labels(triples) == ["pm"]   # short-circuits immediately
    assert posts == []


# ==========================================================================
# B3 -- reverting-gate failure -> revert exactly once + infra-fail
# ==========================================================================
@pytest.mark.parametrize("stage", ["engineer", "reviewer", "tester", "final"])
def test_b3_reverting_gate_fail(cfg, monkeypatch, tmp_path, stage):
    res, triples, reverts, posts, _ = _drive(
        cfg, monkeypatch, tmp_path, _default_plan(), 70, BASE,
        results={stage: False})
    assert res == {"status": "infra-fail", "stage": stage, "iteration": 70}
    assert len(reverts) == 1        # reverted exactly once
    assert _labels(triples)[-1] == stage   # stopped at the failing stage
    assert posts == []


def test_b3_bench_gate_fail_reverts(cfg, monkeypatch, tmp_path):
    # a bench seat is a reverting gate too: designer fail -> revert + infra-fail
    names = ["product_manager", "engineer", "reviewer",
             "designer", "qa_tester", "release_gate"]
    plan = foundry.derive_execution_plan(
        foundry.derive_stage_sequence(_manifest(names)))
    res, triples, reverts, posts, _ = _drive(
        cfg, monkeypatch, tmp_path, plan, 70, BASE, results={"designer": False})
    assert res == {"status": "infra-fail", "stage": "designer", "iteration": 70}
    assert len(reverts) == 1
    assert _labels(triples) == ["pm", "engineer", "reviewer", "designer"]


def _role_obj(name):
    return {"role": name, "model": "builder-class model", "gate": False,
            "done_criteria": "criteria"}


def _manifest(names):
    return {"product": "x", "iteration_budget": 5,
            "roles": [_role_obj(n) for n in names]}


# ==========================================================================
# B4 -- review gate CHANGES_REQUIRED -> fix-review
# ==========================================================================
def test_b4_changes_required_runs_fix_review_then_ships(cfg, monkeypatch, tmp_path):
    res, triples, reverts, posts, _ = _drive(
        cfg, monkeypatch, tmp_path, _default_plan(), 70, BASE,
        reports={"reviewer": "VERDICT: CHANGES_REQUIRED",
                 "final": "ACTION: PUSHED " + NEWHEAD})
    # fix-review runs right after the reviewer stage, then the pipeline continues
    assert _labels(triples) == ["pm", "engineer", "reviewer",
                                "fix-review", "tester", "final"]
    # fix-review is invoked with the (stage, role_file, out_name) triple per spec
    assert ("fix-review", "fix.md", "fix_review.md") in triples
    assert res["status"] == "shipped"
    assert reverts == []


def test_b4_fix_review_failure_reverts_and_infra_fails(cfg, monkeypatch, tmp_path):
    res, triples, reverts, posts, _ = _drive(
        cfg, monkeypatch, tmp_path, _default_plan(), 70, BASE,
        reports={"reviewer": "VERDICT: CHANGES_REQUIRED"},
        results={"fix-review": False})
    assert res == {"status": "infra-fail", "stage": "fix-review", "iteration": 70}
    assert len(reverts) == 1
    assert _labels(triples) == ["pm", "engineer", "reviewer", "fix-review"]
    assert posts == []


def test_b4_no_changes_required_runs_no_fix_stage(cfg, monkeypatch, tmp_path):
    res, triples, reverts, posts, _ = _drive(
        cfg, monkeypatch, tmp_path, _default_plan(), 70, BASE,
        reports={"reviewer": "VERDICT: APPROVE",
                 "final": "ACTION: PUSHED " + NEWHEAD})
    assert "fix-review" not in _labels(triples)
    assert _labels(triples) == DEFAULT_LABELS
    assert res["status"] == "shipped"


# ==========================================================================
# B5 -- test gate RESULT: FAIL -> fix-tests + tester-rerun
# ==========================================================================
def test_b5_result_fail_runs_fix_tests_and_rerun_then_ships(cfg, monkeypatch, tmp_path):
    res, triples, reverts, posts, _ = _drive(
        cfg, monkeypatch, tmp_path, _default_plan(), 70, BASE,
        reports={"tester": "RESULT: FAIL",
                 "final": "ACTION: PUSHED " + NEWHEAD})
    assert _labels(triples) == ["pm", "engineer", "reviewer", "tester",
                                "fix-tests", "tester-rerun", "final"]
    assert ("fix-tests", "fix.md", "fix_tests.md") in triples
    assert ("tester-rerun", "tester.md", "tester2.md") in triples
    assert res["status"] == "shipped"
    assert reverts == []


def test_b5_fix_tests_failure_reverts_no_rerun(cfg, monkeypatch, tmp_path):
    res, triples, reverts, posts, _ = _drive(
        cfg, monkeypatch, tmp_path, _default_plan(), 70, BASE,
        reports={"tester": "RESULT: FAIL"},
        results={"fix-tests": False})
    assert res == {"status": "infra-fail", "stage": "fix-tests", "iteration": 70}
    assert len(reverts) == 1
    # fix-tests failed -> the rerun is NOT attempted
    assert _labels(triples) == ["pm", "engineer", "reviewer", "tester", "fix-tests"]
    assert "tester-rerun" not in _labels(triples)


def test_b5_tester_rerun_failure_reverts_keyed_fix_tests(cfg, monkeypatch, tmp_path):
    res, triples, reverts, posts, _ = _drive(
        cfg, monkeypatch, tmp_path, _default_plan(), 70, BASE,
        reports={"tester": "RESULT: FAIL"},
        results={"tester-rerun": False})
    # EITHER the fix-tests OR the rerun failing keys the infra-fail on "fix-tests"
    assert res == {"status": "infra-fail", "stage": "fix-tests", "iteration": 70}
    assert len(reverts) == 1
    assert _labels(triples) == ["pm", "engineer", "reviewer", "tester",
                                "fix-tests", "tester-rerun"]


def test_b5_no_result_fail_runs_no_fix_stage(cfg, monkeypatch, tmp_path):
    res, triples, reverts, posts, _ = _drive(
        cfg, monkeypatch, tmp_path, _default_plan(), 70, BASE,
        reports={"tester": "RESULT: PASS",
                 "final": "ACTION: PUSHED " + NEWHEAD})
    assert "fix-tests" not in _labels(triples)
    assert "tester-rerun" not in _labels(triples)
    assert _labels(triples) == DEFAULT_LABELS
    assert res["status"] == "shipped"


# ==========================================================================
# B6 -- release gate ship: postrelease_step(cfg, iteration, new head) + dict
# ==========================================================================
def test_b6_release_ship_calls_postrelease_and_returns_shipped(cfg, monkeypatch, tmp_path):
    res, triples, reverts, posts, _ = _drive(
        cfg, monkeypatch, tmp_path, _default_plan(), 70, BASE,
        reports={"final": "ACTION: PUSHED " + NEWHEAD})
    assert len(posts) == 1
    # postrelease_step is called with (cfg, iteration, <new head>)
    assert posts[0] == (cfg, 70, NEWHEAD)
    assert res == {"status": "shipped", "head": NEWHEAD,
                   "iteration": 70, "postrelease": POST_SENTINEL}
    assert reverts == []


# ==========================================================================
# B7 -- release gate no-ship: revert once + no-ship dict + NO postrelease
# ==========================================================================
@pytest.mark.parametrize("label,reports,head", [
    ("no_action_pushed", {"final": "VERDICT: APPROVE"}, NEWHEAD),
    ("head_equals_base", {"final": "ACTION: PUSHED " + NEWHEAD}, BASE),
])
def test_b7_release_no_ship(cfg, monkeypatch, tmp_path, label, reports, head):
    res, triples, reverts, posts, _ = _drive(
        cfg, monkeypatch, tmp_path, _default_plan(), 70, BASE,
        reports=reports, head=head)
    assert res == {"status": "no-ship", "iteration": 70}
    assert len(reverts) == 1
    assert posts == []              # postrelease NOT called on a no-ship
    # ran through the full default plan, terminating at the release gate
    assert _labels(triples) == DEFAULT_LABELS


# ==========================================================================
# B8 -- release gate is terminal: plan steps AFTER a release gate never run
# ==========================================================================
def test_b8_release_gate_is_terminal(cfg, monkeypatch, tmp_path):
    # append a bench seat AFTER the release gate; it must NEVER run
    seq = list(foundry._default_stage_sequence()) + [
        _spec("designer", "designer", "bench/designer.md", "designer.md")]
    plan = foundry.derive_execution_plan(seq)
    res, triples, reverts, posts, _ = _drive(
        cfg, monkeypatch, tmp_path, plan, 70, BASE,
        reports={"final": "ACTION: PUSHED " + NEWHEAD})
    assert res["status"] == "shipped"
    assert "designer" not in _labels(triples)      # post-release step skipped
    assert _labels(triples) == DEFAULT_LABELS


# ==========================================================================
# B9 -- bench seat runs at its declared position (between reviewer and tester)
# ==========================================================================
def test_b9_bench_seat_runs_in_position_and_ships(cfg, monkeypatch, tmp_path):
    names = ["product_manager", "engineer", "reviewer",
             "designer", "qa_tester", "release_gate"]
    seq = foundry.derive_stage_sequence(_manifest(names))
    assert seq != foundry._default_stage_sequence()   # precondition: non-default
    plan = foundry.derive_execution_plan(seq)
    res, triples, reverts, posts, _ = _drive(
        cfg, monkeypatch, tmp_path, plan, 70, BASE,
        reports={"final": "ACTION: PUSHED " + NEWHEAD})
    # ordered stage labels for a clean ship of the full non-default plan
    assert _labels(triples) == ["pm", "engineer", "reviewer",
                                "designer", "tester", "final"]
    # the bench seat runs with its exact (stage, role_file, out_name) triple
    assert ("designer", "bench/designer.md", "designer.md") in triples
    assert res["status"] == "shipped"
    assert reverts == []


# ==========================================================================
# B10 -- no release gate + all pass -> no-ship fallback, NO revert (total fn)
# ==========================================================================
def test_b10_no_release_gate_no_ship_no_revert(cfg, monkeypatch, tmp_path):
    seq = [_spec("product_manager", "pm"), _spec("engineer", "engineer"),
           _spec("reviewer", "reviewer"), _spec("qa_tester", "tester")]
    plan = foundry.derive_execution_plan(seq)
    # precondition: no plan step is a release/ship gate
    assert not any(p.is_ship_gate for p in plan)
    res, triples, reverts, posts, _ = _drive(
        cfg, monkeypatch, tmp_path, plan, 70, BASE)
    assert res == {"status": "no-ship", "iteration": 70}
    assert reverts == []            # totality: no release gate reached -> no revert
    assert posts == []
    assert _labels(triples) == ["pm", "engineer", "reviewer", "tester"]


# ==========================================================================
# B11 -- dormant / zero call site + fresh import + control-path byte-unchanged
# ==========================================================================
def test_b11_zero_call_site():
    # iter-72 (item 19, bite 3b-ii) WIRED run_execution_plan into run_iteration (its
    # intended first call site), so run_iteration is no longer asserted
    # zero-reference; run_continuous / run_stage / build_prompt and dispatcher.py
    # still reference it NOWHERE.
    for fn in (foundry.run_continuous, foundry.run_stage, foundry.build_prompt):
        src = inspect.getsource(fn)
        assert "run_execution_plan" not in src, fn.__name__
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    assert "run_execution_plan" not in dtext


def test_b11_import_ok_fresh_subprocess():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(not _GIT_OK, reason="not inside a git work tree")
def test_b11_control_path_byte_unchanged():
    # `git diff --quiet` emits NO diff text (exit-code-only) -> honors isolation.
    # The main module legitimately grows this iter, so it is NOT pinned here; only
    # the dispatcher module + scripts/ (the control path) are pinned byte-unchanged.
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py", "scripts/"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, "dispatcher.py / scripts NOT byte-unchanged from HEAD"


# ==========================================================================
# B12 -- leak-safe (ship-blocker, armed matcher) + new symbol pure ASCII
# ==========================================================================
def test_b12_new_symbol_pure_ascii():
    # NEW symbol only (never a whole-file scan -- the module has pre-existing
    # non-ASCII em-dashes from prior iters that would false-fail).
    src = inspect.getsource(foundry.run_execution_plan)
    offenders = [(i, hex(ord(c))) for i, c in enumerate(src) if ord(c) >= 128]
    assert offenders == [], offenders[:5]
    # the whole new test file is pure ASCII too
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


def test_b12_leak_clean_with_armed_matcher():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    module_text = pathlib.Path(foundry.__file__).read_text(encoding="utf-8")
    assert mod.scan_text(module_text, denylist) == (), "main module leaks a denylisted token"
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "test file leaks a denylisted token"
    # matcher is ARMED (not inert): a RUNTIME-built home-path needle IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"
