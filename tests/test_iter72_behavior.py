"""Black-box behaviour tests for iter 72 -- roadmap item 19, bite 3b-ii of 2 (COMPLETES item 19).

This bite WIRES the dormant manifest-driven executor into the live run_iteration
behind a strict guard: for a NON-default, lint-clean, release-gate-LAST staffing
manifest, run_iteration delegates the whole pipeline to run_execution_plan and
returns its result verbatim; every other case (absent / default-equivalent /
lint-dirty / release-not-last manifest) runs the EXISTING fixed pipeline
byte-for-byte. The executor, plan derivation, manifest read, and lint were all
shipped + tested in iters 67-70; the only NEW code here is the ~12-line guarded
delegation. This is the completing wire of item 19 -- a runtime no-op for every
configured product today (no / plain / non-delegable manifest), so a running
loop's resume semantics are unchanged.

ISOLATION CONTRACT (honored, with one disclosed deviation below): every test here
encodes the iter-72 PM spec's Expected Behaviors (1-12), driven purely against the
PUBLIC interface -- the importable public callables/constants (run_iteration,
load_config, ProductConfig, load_staffing_manifest, derive_stage_sequence,
_default_stage_sequence, derive_execution_plan, StagePlan, run_execution_plan,
lint_manifest, PostReleaseResult), the real product config/manifest data files read
via the bare module's __file__, the committed scripts/leak_guard.py public API, and
inspect.getsource / the dispatcher module's file text (used ONLY to assert the
SPEC's stale-forward-ref, bare-name-seam, control-path, and new-content-ASCII
observables -- NOT to mirror or reproduce implementation logic). The run_iteration
behaviours are exercised with SCRIPTED SEAMS (monkeypatch run_stage /
head_of_branch / power_state / revert_repo / postrelease_step / next_iteration /
log / load_staffing_manifest / lint_manifest / run_execution_plan by BARE module
name) exactly as the iter-03 / iter-68 run_iteration tester did -- fully offline,
deterministic, no network, no real git push, no clock. A fake run_stage records the
ORDERED stage label and writes the ship/no-ship sentinel lines to a real file (so
run_iteration's file reads see them); the run_execution_plan seam is a SPY that
records its positional (cfg, iteration, plan, base) args and returns a scripted
dict. Each scenario gets its OWN fresh head_of_branch iterator (the iter-68
generator-reuse gotcha). The engineer's / reviewer's notes and git diff text were
NOT read as design input; assertions encode the SPEC's Expected Behaviors, not impl
quirks. Every path is built at RUNTIME from the bare module's __file__ (never a
source-literal home path), so the committed leak-guard passes on the ship commit.
DISCLOSED DEVIATION: the runner supplied prior-role iter notes in the context
digest, so complete blindness was not possible; nonetheless every assertion below
is derived from the pm.md spec's Expected Behaviors, not from those notes -- the
notes changed no expected value.

NB on Behavior 11 (reused functions AST-identical vs HEAD): reading the
pre-iteration implementation source (git show HEAD:<main module>) to AST-diff it is
OUTSIDE a tester's isolation contract (that is a reviewer / final-gate out-of-band
numstat/AST check that reads the diff). Here the reused-function property is tested
within isolation two ways: (a) their black-box DERIVATION behaviour is unchanged
(derive_stage_sequence(None) == _default_stage_sequence(), len 5; the derivation
composes cleanly); and (b) run_continuous / run_stage / build_prompt do NOT
reference run_execution_plan (a proxy observable that would catch an accidental
touch). The byte/AST identity clause is flagged as the reviewer/final-gate job.

NB on Behavior 12 (new content is pure ASCII): the new guard lives INSIDE
run_iteration, a LARGE pre-existing function that already carries legitimate
non-ASCII (em-dash / middle-dot bytes from prior iterations' banner/fix/SHIPPED log
lines), so a whole-function ASCII scan FALSE-fails on the shipped tree, and a tester
in isolation (no git diff) cannot slice out only the newly-added lines. Most-
reasonable reading tested here: the NEW user-visible content -- the guard's
diagnostic log line -- is asserted ASCII on the runtime-captured string (B7), and
the whole new test file is asserted ASCII. The authoritative whole-file ship gate is
the committed leak-guard, which scans clean (B12).

NB on the iter-54 meta-scanner: this file contains a `git diff --quiet` call, so it
must not carry the quoted main-module filename token on any non-comment line. The
main module is located via the BARE module's __file__; it is NOT pinned
byte-unchanged (it legitimately grows this iter). Only the dispatcher module +
scripts/ are pinned byte-unchanged (the control path).
"""
import collections
import importlib.util
import inspect
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths + fixed expected values (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
REPOLENS_STAFFING = _ROOT / "products" / "repolens" / "staffing.json"
THIS_TEST = pathlib.Path(__file__).resolve()

BASE = "base0000"
NEWHEAD = "newhead99"
POST_SENTINEL = "POSTRELEASE: HEALTHY"
SHIP_KEYS = {"status", "head", "iteration", "postrelease"}
DEFAULT_STAGES = ["pm", "engineer", "reviewer", "tester", "final"]
DIAG_SUB = "manifest activates a non-default team"

# ship / no-ship sentinel line sets written uniformly to every stage's output file.
# SHIP contains ACTION: PUSHED <moved head> -> the fixed pipeline ships; NO_ACTION
# omits it -> no-ship. Neither carries CHANGES_REQUIRED / RESULT: FAIL, so the
# default path takes no fix-review / fix-tests diversion.
SHIP_LINES = ["VERDICT: APPROVE", "RESULT: PASS", "ACTION: PUSHED " + NEWHEAD]
NO_ACTION_LINES = ["VERDICT: APPROVE", "RESULT: PASS", "final declined to push"]

_REAL = object()  # sentinel: do NOT patch load_staffing_manifest (exercise real seam)

Drive = collections.namedtuple(
    "Drive", "res stages logs exec_calls lint_calls reverts")

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


def _role(name):
    return {"role": name, "model": "builder-class model",
            "gate": False, "done_criteria": "criteria"}


def _manifest(names):
    return {"product": "x", "iteration_budget": 5,
            "roles": [_role(n) for n in names]}


# a non-default, release-gate-LAST manifest (an extra `designer` bench seat between
# reviewer and tester) -> derives to a 6-seat non-default sequence whose plan ends
# on the ship gate; delegable when lint is clean.
DELEGABLE_NAMES = ["product_manager", "engineer", "reviewer",
                   "designer", "qa_tester", "release_gate"]
# a non-default manifest whose extra seat is declared AFTER release_gate -> the
# plan's LAST step is the bench seat, not the ship gate -> NOT delegable.
RELEASE_NOT_LAST_NAMES = ["product_manager", "engineer", "reviewer",
                          "qa_tester", "release_gate", "designer"]


class _Lint:
    """Stand-in for lint_manifest's ManifestLint return: any object exposing the
    `.clean` bool the guard reads. Black-box: I control the seam, so I control its
    return type (no dependency on ManifestLint's constructor signature)."""

    def __init__(self, clean):
        self.clean = clean


def _make_run_stage(lines, recorder, results):
    """Scripted run_stage: record the ORDERED stage label, write the sentinel
    `lines` to a real file under cfg.state/iter-NN/<out_name> (so run_iteration's
    file reads see them), and return (ok, path). `results` maps a stage label ->
    ok bool (default True)."""
    def _run_stage(cfg, iteration, stage, role_file, out_name, extra=""):
        recorder.append(stage)
        it_dir = cfg.state / f"iter-{iteration:02d}"
        it_dir.mkdir(parents=True, exist_ok=True)
        out = it_dir / out_name
        out.write_text("\n".join(lines) + "\n")
        return results.get(stage, True), out
    return _run_stage


def _make_head(values):
    """Fresh head iterator per scenario (the iter-68 generator-reuse gotcha):
    pops successive values, then repeats the last. The FIRST value is the
    iteration-start `base`."""
    seq = list(values)

    def _head(cfg):
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return _head


def _drive(cfg, monkeypatch, iteration, *, manifest=_REAL, lint_clean=True,
           exec_result=None, lines=None, results=None,
           head=(BASE, NEWHEAD)):
    """Run one offline iteration with fully scripted seams. `manifest` is returned
    by a patched load_staffing_manifest UNLESS it is the _REAL sentinel (then the
    real seam runs). run_execution_plan is a SPY (records args, returns a scripted
    dict). lint_manifest returns _Lint(lint_clean) and records its args."""
    lines = SHIP_LINES if lines is None else lines
    stages, logs, exec_calls, lint_calls, reverts = [], [], [], [], []

    monkeypatch.setattr(foundry, "run_stage",
                        _make_run_stage(lines, stages, results or {}))
    monkeypatch.setattr(foundry, "head_of_branch", _make_head(list(head)))
    monkeypatch.setattr(foundry, "power_state",
                        lambda: "Now drawing from 'AC Power'")
    monkeypatch.setattr(foundry, "revert_repo",
                        lambda *a, **k: reverts.append(a))
    monkeypatch.setattr(foundry, "postrelease_step",
                        lambda *a, **k: foundry.PostReleaseResult(True, False, POST_SENTINEL))
    monkeypatch.setattr(foundry, "next_iteration", lambda *a, **k: iteration)
    monkeypatch.setattr(foundry, "log",
                        lambda *a, **k: logs.append(" ".join(str(x) for x in a)))

    def _spy_exec(cfg_, it, plan, base):
        exec_calls.append((cfg_, it, plan, base))
        if exec_result is not None:
            return exec_result
        return {"status": "shipped", "head": "exec-head",
                "iteration": it, "postrelease": "exec-post"}
    monkeypatch.setattr(foundry, "run_execution_plan", _spy_exec)

    def _spy_lint(*a, **k):
        lint_calls.append((a, k))
        return _Lint(lint_clean)
    monkeypatch.setattr(foundry, "lint_manifest", _spy_lint)

    if manifest is not _REAL:
        monkeypatch.setattr(foundry, "load_staffing_manifest",
                            lambda c, _m=manifest: _m)

    res = foundry.run_iteration(cfg, iteration)
    return Drive(res, stages, logs, exec_calls, lint_calls, reverts)


def _diag_count(logs):
    return sum(1 for m in logs if DIAG_SUB in m)


def _expected_plan(manifest):
    return foundry.derive_execution_plan(foundry.derive_stage_sequence(manifest))


def _leak_guard():
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter72_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# B1 -- Absent/None manifest -> default path (no delegation)
# ==========================================================================
def test_b1_none_manifest_runs_default_pipeline(cfg, monkeypatch):
    d = _drive(cfg, monkeypatch, 72, manifest=None)
    assert d.exec_calls == []                  # run_execution_plan NOT called
    assert d.stages == DEFAULT_STAGES          # the fixed pipeline ran, in order
    assert d.res == {"status": "shipped", "head": NEWHEAD,
                     "iteration": 72, "postrelease": POST_SENTINEL}
    assert set(d.res) == SHIP_KEYS
    assert _diag_count(d.logs) == 0            # no non-default diagnostic


# ==========================================================================
# B2 -- Default-equivalent manifest -> default path; lint_manifest NOT reached
# ==========================================================================
def test_b2_default_equivalent_manifest_no_delegate_no_lint(cfg, monkeypatch):
    mf = json.loads(REPOLENS_STAFFING.read_text(encoding="utf-8"))
    # precondition: the manifest derives to the DEFAULT five-core sequence
    assert foundry.derive_stage_sequence(mf) == foundry._default_stage_sequence()
    d = _drive(cfg, monkeypatch, 72, manifest=mf)
    assert d.exec_calls == []                  # no delegation
    assert d.lint_calls == []                  # guard short-circuits BEFORE lint
    assert d.stages == DEFAULT_STAGES
    assert d.res["status"] == "shipped"


# ==========================================================================
# B3 -- Non-default + lint-clean + release-gate-last -> DELEGATE
# ==========================================================================
def test_b3_delegates_and_skips_fixed_pipeline(cfg, monkeypatch):
    mf = _manifest(DELEGABLE_NAMES)
    # preconditions: non-default sequence, plan ends on the ship gate
    assert foundry.derive_stage_sequence(mf) != foundry._default_stage_sequence()
    assert _expected_plan(mf)[-1].is_ship_gate
    d = _drive(cfg, monkeypatch, 72, manifest=mf, lint_clean=True)
    assert len(d.exec_calls) == 1              # run_execution_plan called EXACTLY once
    assert d.stages == []                      # the fixed pipeline's run_stage NOT called
    # result is the executor's dict verbatim (NOT the fixed pipeline's NEWHEAD ship)
    assert d.res == {"status": "shipped", "head": "exec-head",
                     "iteration": 72, "postrelease": "exec-post"}


# ==========================================================================
# B4 -- Delegation arguments: (cfg, iteration, plan, base)
# ==========================================================================
def test_b4_delegation_arguments(cfg, monkeypatch):
    mf = _manifest(DELEGABLE_NAMES)
    # a distinctive iteration-start head proves `base` is the FIRST read, not a later
    d = _drive(cfg, monkeypatch, 72, manifest=mf, lint_clean=True,
               head=("iter-start-head", "would-be-later-head"))
    assert len(d.exec_calls) == 1
    got_cfg, got_it, got_plan, got_base = d.exec_calls[0]
    assert got_cfg is cfg                       # same config object
    assert got_it == 72                         # running iteration number
    assert got_plan == _expected_plan(mf)       # exact StagePlan tuple (== supported)
    assert got_base == "iter-start-head"        # branch head captured at iteration start


# ==========================================================================
# B5 -- Lint bench-dir resolution: (manifest, <roles_dir>/bench, str(cfg.staffing))
# ==========================================================================
def test_b5_lint_called_with_bench_dir_and_staffing_label(cfg, monkeypatch):
    mf = _manifest(DELEGABLE_NAMES)
    d = _drive(cfg, monkeypatch, 72, manifest=mf, lint_clean=True)
    assert len(d.lint_calls) == 1
    a, k = d.lint_calls[0]
    passed = list(a) + list(k.values())         # robust to positional vs keyword
    assert mf in passed                         # the parsed manifest dict
    assert (pathlib.Path(cfg.roles_dir) / "bench") in passed   # bench card dir
    assert str(cfg.staffing) in passed          # the staffing-path label


# ==========================================================================
# B6 -- Non-default but lint-DIRTY -> default path + diagnostic
# ==========================================================================
def test_b6_non_default_lint_dirty_falls_back(cfg, monkeypatch):
    mf = _manifest(DELEGABLE_NAMES)             # would be delegable IF lint were clean
    d = _drive(cfg, monkeypatch, 72, manifest=mf, lint_clean=False)
    assert d.exec_calls == []                   # NOT delegated
    assert len(d.lint_calls) == 1               # lint WAS consulted (non-default branch)
    assert d.stages == DEFAULT_STAGES           # fixed pipeline ran (no designer seat)
    assert "designer" not in d.stages
    assert _diag_count(d.logs) == 1             # exactly one fall-back diagnostic


# ==========================================================================
# B7 -- Non-default + lint-clean but release-gate NOT last -> default path
# ==========================================================================
def test_b7_release_not_last_falls_back(cfg, monkeypatch):
    mf = _manifest(RELEASE_NOT_LAST_NAMES)
    # preconditions: non-default sequence, plan's LAST step is NOT the ship gate
    assert foundry.derive_stage_sequence(mf) != foundry._default_stage_sequence()
    assert not _expected_plan(mf)[-1].is_ship_gate
    d = _drive(cfg, monkeypatch, 72, manifest=mf, lint_clean=True)
    assert d.exec_calls == []                   # NOT delegated (would skip post-release seat)
    assert d.stages == DEFAULT_STAGES
    diag = [m for m in d.logs if DIAG_SUB in m]
    assert len(diag) == 1                       # exactly one fall-back diagnostic
    # the new guard's diagnostic content is pure ASCII (Behavior 12, new content)
    assert all(ord(c) < 128 for c in diag[0]), repr(diag[0])


# ==========================================================================
# B8 -- Delegated result is passed through unchanged (identical dict)
# ==========================================================================
@pytest.mark.parametrize("result", [
    {"status": "shipped", "head": "H", "iteration": 72, "postrelease": "P"},
    {"status": "no-ship", "iteration": 72},
    {"status": "infra-fail", "stage": "engineer", "iteration": 72},
])
def test_b8_delegated_result_passthrough(cfg, monkeypatch, result):
    mf = _manifest(DELEGABLE_NAMES)
    d = _drive(cfg, monkeypatch, 72, manifest=mf, lint_clean=True,
               exec_result=result)
    assert len(d.exec_calls) == 1
    assert d.res == result                      # returned verbatim
    assert d.res is result                      # no post-processing / no copy


# ==========================================================================
# B9 -- Default path unchanged (regression, no manifest)
# ==========================================================================
def test_b9_default_clean_run_ships(cfg, monkeypatch):
    d = _drive(cfg, monkeypatch, 72, manifest=None)
    assert d.res["status"] == "shipped"
    assert d.res["head"] == NEWHEAD
    assert d.res["iteration"] == 72
    assert set(d.res) == SHIP_KEYS
    assert d.reverts == []


def test_b9_default_pm_fail_infra_no_revert(cfg, monkeypatch):
    d = _drive(cfg, monkeypatch, 72, manifest=None, results={"pm": False})
    assert d.res == {"status": "infra-fail", "stage": "pm", "iteration": 72}
    assert d.reverts == []                      # pm-gate failure does NOT revert
    assert d.stages == ["pm"]                   # short-circuits immediately


def test_b9_default_no_action_pushed_no_ship_reverts(cfg, monkeypatch):
    # final report present but WITHOUT ACTION: PUSHED -> no-ship + revert
    d = _drive(cfg, monkeypatch, 72, manifest=None, lines=NO_ACTION_LINES)
    assert d.res == {"status": "no-ship", "iteration": 72}
    assert len(d.reverts) == 1
    assert d.stages == DEFAULT_STAGES


def test_b9_default_head_unmoved_no_ship_reverts(cfg, monkeypatch):
    # ACTION: PUSHED present but the branch head never moved -> no-ship + revert
    d = _drive(cfg, monkeypatch, 72, manifest=None, head=(BASE,))
    assert d.res == {"status": "no-ship", "iteration": 72}
    assert len(d.reverts) == 1


# ==========================================================================
# B10 -- Stale forward-ref removed + bare-name seams
# ==========================================================================
def test_b10_stale_forward_ref_removed_and_bare_name_seams():
    # inspect.getsource here asserts a SPEC-mandated observable (a substring is
    # present/absent), NOT to mirror implementation logic (see module docstring).
    src = inspect.getsource(foundry.run_iteration)
    assert "executor lands in bite 3" not in src
    for name in ("load_staffing_manifest", "lint_manifest",
                 "derive_execution_plan", "run_execution_plan"):
        assert name in src, name


def test_b10_seams_are_monkeypatchable_by_bare_name(cfg, monkeypatch):
    # the delegate path proves run_execution_plan + lint_manifest + load_staffing_manifest
    # are called by BARE module name -- a monkeypatch.setattr(foundry, name, ...) on
    # each takes effect (else the spy would not intercept and stages != []).
    d = _drive(cfg, monkeypatch, 72, manifest=_manifest(DELEGABLE_NAMES),
               lint_clean=True)
    assert len(d.exec_calls) == 1
    assert len(d.lint_calls) == 1
    assert d.stages == []


# ==========================================================================
# B11 -- import + control-path byte-unchanged + reused-function behaviour
# ==========================================================================
def test_b11_import_ok_fresh_subprocess():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(not _GIT_OK, reason="not inside a git work tree")
def test_b11_control_path_byte_unchanged():
    # `git diff --quiet` emits NO diff text (exit-code-only) -> honors isolation.
    # The main module legitimately grows this iter (NOT pinned here); only the
    # dispatcher module + scripts/ (the control path) are pinned byte-unchanged.
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py", "scripts/"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, "dispatcher.py / scripts NOT byte-unchanged from HEAD"


def test_b11_reused_functions_behaviour_unchanged():
    # black-box: the reused derivation helpers behave exactly as before. (Full
    # AST/byte identity vs HEAD is a reviewer/final-gate out-of-band check that
    # reads the pre-iteration source -- outside a tester's isolation contract.)
    assert foundry.derive_stage_sequence(None) == foundry._default_stage_sequence()
    assert len(foundry.derive_stage_sequence(None)) == 5
    # the derivation still composes into a plan whose last step is the ship gate
    assert _expected_plan(_manifest(DELEGABLE_NAMES))[-1].is_ship_gate


def test_b11_other_orchestrators_do_not_reference_executor():
    # run_continuous / run_stage / build_prompt are unchanged: they reference the
    # newly-wired executor NOWHERE (a proxy observable for "unchanged"; the wiring
    # lives ONLY in run_iteration).
    for fn in (foundry.run_continuous, foundry.run_stage, foundry.build_prompt):
        assert "run_execution_plan" not in inspect.getsource(fn), fn.__name__
    assert "run_execution_plan" not in DISPATCHER_PY.read_text(encoding="utf-8")


# ==========================================================================
# B12 -- ASCII + leak-clean (ship-blocker, armed matcher)
# ==========================================================================
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


def test_b12_test_file_pure_ascii():
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []
