"""Black-box behaviour tests for iter 141 -- the operator-visible `RESTART_NEEDED.md` flag:
the liveness fact that `live_lag_line` already computes is raised as a named, gitignored flag
file for a human, and auto-clears once the brain is restarted.

Spec: products/_platform/state/iter-141/pm.md, Expected Behaviors 1-10.

  1.  `dispatch_restart_line(cfg)` -> None when the composed line does NOT contain
      `LIVE_LAG_WARN` (the OK and UNKNOWN branches, and an empty line); the line VERBATIM
      (non-empty `str`) when it DOES.
  2.  WARN branch writes `Path(cfg.work_root) / "RESTART_NEEDED.md"` whose text carries
      (a) the live-lag line verbatim, (b) the word `restart`, (c) an explicit self-clearing
      lift condition.
  3.  OK / UNKNOWN REMOVE a pre-existing flag; with no flag present the call is a no-op and
      still returns None.
  4.  Two consecutive WARN calls leave exactly ONE file, refreshed -- never appended.
  5.  NEVER raises: a raising `live_lag_line` -> None; an unwritable flag path -> still the
      WARN line; an unremovable flag -> None.
  6.  Composition is by BARE module name read at call time, so patching `foundry.live_lag_line`
      changes what is reported, with zero real git / subprocess / network.
  7.  `RESTART_FLAG_NAME` is a module-level `str` read as a global at call time;
      `restart_flag_path(cfg)` is pure and names a DIFFERENT file from the hotfix and
      speed-story flags, with an independent lifecycle.
  8.  OFF THE CONTROL PATH: `run_iteration` / `run_continuous` / `run_stage` / `build_prompt` /
      `postrelease_step` mention none of the new names, and no role card reads the flag.
  9.  WIRING PRECONDITION only -- see that test's docstring for the recorded deviation.
  10. the runtime flag is gitignored under `products/`, verified through git's own matcher.
  Plus Acceptance-Criteria oracles: both imports succeed, the reporter writes nothing but the
  flag (no new `state/` artifacts), no stray flag file is left in the product tree, the
  `live-lag` core is not entangled with the new names, and both iteration-141 roadmap records.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-141 PM spec's Expected Behaviors, the
conventions of tests/ (the `_cfg` / scripted-seam shape of test_iter130_behavior.py and its
mechanical-`getsource` dormancy probe), and the product's OBSERVABLE surface -- importing the
modules, CALLING the public functions, and reading committed repo docs off disk.  The
implementation BODIES of foundry.py / dispatcher.py, the engineer's notes (engineer.md), the
reviewer's notes (reviewer.md, fix_review.md) and `git diff` were NOT read; Behaviors 8-9 use
`inspect.getsource` MECHANICALLY (substring membership only, never displayed), exactly as
iteration 130 established for a dormancy probe.

Offline and deterministic: every config is built in memory or under `tmp_path`, the product tree
is never mutated, and the only subprocesses are local read-only probes the criteria ask for (a
fresh-interpreter import check, `git check-ignore`, `git status --porcelain`).  No network, no
agent run, no sleeps.
"""
from __future__ import annotations

import inspect
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (dormancy + wiring probe)

THIS_ITER = 141

# Contract literals, held here so the test pins the SPEC rather than echoing the module.
FLAG_NAME = "RESTART_NEEDED.md"
WARN_TOKEN = "WARN"
NEW_NAMES = ("RESTART_FLAG_NAME", "restart_flag_path", "dispatch_restart_line",
             "RESTART_NEEDED")
CONTROL_PATH_FNS = ("run_iteration", "run_continuous", "run_stage",
                    "build_prompt", "postrelease_step")

WARN_LINE = "live-lag: WARN 3 shipped iterations are inert (139, 140, 141)"
OK_LINE = "live-lag: OK the live brain is current"
UNKNOWN_LINE = "live-lag: UNKNOWN brain launch instant not found in the log"
NON_WARN_LINES = (OK_LINE, UNKNOWN_LINE, "", "live-lag: nothing to report")


def _cfg(**over):
    """A ProductConfig whose repo path does not exist -- nothing may touch real git."""
    kw = dict(name="demo", repo="/no/such/repo", allowed_push_repo="demo")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _work_cfg(tmp_path, sub="work"):
    root = tmp_path / sub
    root.mkdir(parents=True, exist_ok=True)
    return _cfg(work_root=str(root)), root


def _script(monkeypatch, text):
    """Replace the ONE upstream seam by BARE module name (Behavior 6)."""
    monkeypatch.setattr(foundry, "live_lag_line", lambda *a, **k: text)


def _forbid_subprocess(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("dispatch_restart_line must not shell out")
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "check_output", _boom)


# --------------------------------------------------------------------------------------
# Behavior 1 -- verdict: None off the WARN branch, the line VERBATIM on it.
# --------------------------------------------------------------------------------------
def test_b1_warn_token_is_the_trigger():
    assert foundry.LIVE_LAG_WARN == WARN_TOKEN, (
        "the spec keys the flag off LIVE_LAG_WARN containment")


@pytest.mark.parametrize("line", NON_WARN_LINES)
def test_b1_non_warn_lines_report_nothing(monkeypatch, tmp_path, line):
    cfg, _ = _work_cfg(tmp_path)
    _script(monkeypatch, line)
    assert foundry.dispatch_restart_line(cfg) is None, (
        f"a line without {WARN_TOKEN!r} is not lag: {line!r}")


def test_b1_warn_line_is_returned_verbatim(monkeypatch, tmp_path):
    cfg, _ = _work_cfg(tmp_path)
    _script(monkeypatch, WARN_LINE)
    got = foundry.dispatch_restart_line(cfg)
    assert isinstance(got, str) and got, "WARN must report a non-empty str"
    assert got == WARN_LINE, "the line must be reported VERBATIM, not re-worded"


# --------------------------------------------------------------------------------------
# Behavior 2 -- the flag file: location from cfg alone, and three content requirements.
# --------------------------------------------------------------------------------------
def test_b2_warn_writes_the_flag_at_the_work_root_idiom(monkeypatch, tmp_path):
    cfg, root = _work_cfg(tmp_path)
    flag = pathlib.Path(cfg.work_root) / FLAG_NAME
    assert not flag.exists(), "fixture must start clean"
    _script(monkeypatch, WARN_LINE)
    foundry.dispatch_restart_line(cfg)
    assert flag.exists() and flag.is_file(), (
        f"WARN must leave {FLAG_NAME} under work_root, locatable from cfg alone")
    assert flag == foundry.restart_flag_path(cfg), (
        "the helper must name the same path the reporter writes")


def test_b2_flag_text_carries_line_restart_and_a_lift_condition(monkeypatch, tmp_path):
    cfg, _ = _work_cfg(tmp_path)
    _script(monkeypatch, WARN_LINE)
    foundry.dispatch_restart_line(cfg)
    text = foundry.restart_flag_path(cfg).read_text()
    low = text.lower()
    assert WARN_LINE in text, "(a) the live-lag line must appear VERBATIM in the flag"
    assert "restart" in low, "(b) the flag must say the word 'restart'"
    assert "lift condition" in low or "auto-clear" in low or "clears" in low, (
        "(c) the flag must state its lift condition explicitly")
    assert re.search(r"(auto-?clear|clears? (itself|on|automatically)|"
                     r"nothing to do by hand)", low), (
        "(c) the lift condition must say the flag clears itself after the restart")


# --------------------------------------------------------------------------------------
# Behavior 3 -- auto-clear, and the no-op case.
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("line", (OK_LINE, UNKNOWN_LINE))
def test_b3_non_warn_removes_a_pre_existing_flag(monkeypatch, tmp_path, line):
    cfg, _ = _work_cfg(tmp_path)
    flag = foundry.restart_flag_path(cfg)
    flag.write_text("stale flag from a previous shift\n")
    _script(monkeypatch, line)
    assert foundry.dispatch_restart_line(cfg) is None
    assert not flag.exists(), (
        "the flag must never nag after the restart it asked for")


def test_b3_clearing_when_absent_is_a_noop(monkeypatch, tmp_path):
    cfg, root = _work_cfg(tmp_path)
    _script(monkeypatch, OK_LINE)
    before = sorted(p.name for p in root.iterdir())
    assert foundry.dispatch_restart_line(cfg) is None
    assert sorted(p.name for p in root.iterdir()) == before, (
        "clearing an absent flag must create nothing")


def test_b3_warn_then_ok_is_a_full_round_trip(monkeypatch, tmp_path):
    cfg, _ = _work_cfg(tmp_path)
    flag = foundry.restart_flag_path(cfg)
    _script(monkeypatch, WARN_LINE)
    foundry.dispatch_restart_line(cfg)
    assert flag.exists()
    _script(monkeypatch, OK_LINE)
    foundry.dispatch_restart_line(cfg)
    assert not flag.exists(), "restarting the brain must retire the flag"


# --------------------------------------------------------------------------------------
# Behavior 4 -- idempotent write.
# --------------------------------------------------------------------------------------
def test_b4_two_warn_calls_leave_one_refreshed_flag(monkeypatch, tmp_path):
    cfg, root = _work_cfg(tmp_path)
    flag = foundry.restart_flag_path(cfg)
    _script(monkeypatch, WARN_LINE)
    foundry.dispatch_restart_line(cfg)
    first = flag.read_text()
    foundry.dispatch_restart_line(cfg)
    second = flag.read_text()
    assert [p.name for p in root.iterdir()] == [FLAG_NAME], (
        "exactly ONE flag file, no .1 / .bak siblings")
    assert second == first, "the write must be idempotent, never appended-to"
    assert second.count(WARN_LINE) == 1, "the line must not be duplicated inside the flag"


def test_b4_second_warn_refreshes_the_line(monkeypatch, tmp_path):
    cfg, _ = _work_cfg(tmp_path)
    flag = foundry.restart_flag_path(cfg)
    _script(monkeypatch, WARN_LINE)
    foundry.dispatch_restart_line(cfg)
    newer = "live-lag: WARN 4 shipped iterations are inert (138, 139, 140, 141)"
    _script(monkeypatch, newer)
    assert foundry.dispatch_restart_line(cfg) == newer
    text = flag.read_text()
    assert newer in text, "the flag must carry the REFRESHED line"
    assert WARN_LINE not in text, "the stale line must be overwritten, not accumulated"


# --------------------------------------------------------------------------------------
# Behavior 5 -- total: never raises, on any of the three failure modes.
# --------------------------------------------------------------------------------------
def test_b5_raising_seam_reports_nothing(monkeypatch, tmp_path):
    cfg, _ = _work_cfg(tmp_path)

    def _boom(*a, **k):
        raise RuntimeError("live_lag_line exploded")

    monkeypatch.setattr(foundry, "live_lag_line", _boom)
    assert foundry.dispatch_restart_line(cfg) is None, (
        "an unusable report is not evidence of lag")


def test_b5_unwritable_flag_path_still_reports_the_line(monkeypatch, tmp_path):
    blocker = tmp_path / "a-file-not-a-dir"
    blocker.write_text("i am a file")
    cfg = _cfg(work_root=str(blocker / "sub"))  # parent is a FILE -> write must fail
    _script(monkeypatch, WARN_LINE)
    assert foundry.dispatch_restart_line(cfg) == WARN_LINE, (
        "the report must survive a failed write")


def test_b5_unremovable_flag_does_not_raise(monkeypatch, tmp_path):
    cfg, root = _work_cfg(tmp_path)
    (root / FLAG_NAME).mkdir()  # a directory cannot be unlinked
    _script(monkeypatch, OK_LINE)
    assert foundry.dispatch_restart_line(cfg) is None, (
        "a failed removal must not propagate")


def test_b5_missing_work_root_does_not_raise(monkeypatch, tmp_path):
    cfg = _cfg(work_root=str(tmp_path / "never" / "created"))
    _script(monkeypatch, WARN_LINE)
    assert foundry.dispatch_restart_line(cfg) == WARN_LINE


# --------------------------------------------------------------------------------------
# Behavior 6 -- bare-name seam read at call time, and zero real I/O.
# --------------------------------------------------------------------------------------
def test_b6_seam_is_read_at_call_time(monkeypatch, tmp_path):
    cfg, _ = _work_cfg(tmp_path)
    sentinel = "live-lag: WARN ZZSENTINELZZ one line only"
    _script(monkeypatch, sentinel)
    assert foundry.dispatch_restart_line(cfg) == sentinel, (
        "the composition must read the module global, not a def-time capture")
    assert sentinel in foundry.restart_flag_path(cfg).read_text()


def test_b6_no_subprocess_git_or_network(monkeypatch, tmp_path):
    cfg, _ = _work_cfg(tmp_path)
    _script(monkeypatch, WARN_LINE)
    _forbid_subprocess(monkeypatch)
    assert foundry.dispatch_restart_line(cfg) == WARN_LINE
    _script(monkeypatch, OK_LINE)
    assert foundry.dispatch_restart_line(cfg) is None


# --------------------------------------------------------------------------------------
# Behavior 7 -- the token, the pure path helper, and flag independence.
# --------------------------------------------------------------------------------------
def test_b7_flag_name_is_a_module_level_str():
    assert isinstance(foundry.RESTART_FLAG_NAME, str)
    assert foundry.RESTART_FLAG_NAME == FLAG_NAME


def test_b7_path_helper_is_pure_and_uses_work_root(tmp_path):
    cfg, root = _work_cfg(tmp_path)
    before = sorted(p.name for p in root.iterdir())
    got = foundry.restart_flag_path(cfg)
    assert got == pathlib.Path(cfg.work_root) / foundry.RESTART_FLAG_NAME
    assert got == foundry.restart_flag_path(cfg), "must be deterministic"
    assert sorted(p.name for p in root.iterdir()) == before, "must not touch the disk"


def test_b7_flag_name_is_read_as_a_global_at_call_time(monkeypatch, tmp_path):
    cfg, root = _work_cfg(tmp_path)
    monkeypatch.setattr(foundry, "RESTART_FLAG_NAME", "OTHER_FLAG.md")
    assert foundry.restart_flag_path(cfg).name == "OTHER_FLAG.md"
    _script(monkeypatch, WARN_LINE)
    foundry.dispatch_restart_line(cfg)
    assert [p.name for p in root.iterdir()] == ["OTHER_FLAG.md"], (
        "the writer must honour the patched global too")


def test_b7_is_a_different_file_from_the_other_two_flags(tmp_path):
    cfg, _ = _work_cfg(tmp_path)
    paths = {foundry.restart_flag_path(cfg),
             foundry.hotfix_flag_path(cfg),
             foundry.speed_story_flag_path(cfg)}
    assert len(paths) == 3, "the three operator flags must be distinct files"


def test_b7_lifecycle_is_independent_of_the_other_flags(monkeypatch, tmp_path):
    cfg, _ = _work_cfg(tmp_path)
    hotfix = foundry.hotfix_flag_path(cfg)
    speed = foundry.speed_story_flag_path(cfg)
    hotfix.parent.mkdir(parents=True, exist_ok=True)
    speed.parent.mkdir(parents=True, exist_ok=True)
    hotfix.write_text("unrelated hotfix flag\n")
    speed.write_text("unrelated speed-story flag\n")
    _script(monkeypatch, WARN_LINE)
    foundry.dispatch_restart_line(cfg)
    _script(monkeypatch, OK_LINE)
    foundry.dispatch_restart_line(cfg)
    assert hotfix.read_text() == "unrelated hotfix flag\n"
    assert speed.read_text() == "unrelated speed-story flag\n"


# --------------------------------------------------------------------------------------
# Behavior 8 -- dormant on the control path; no role card reads the flag.
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("fn", CONTROL_PATH_FNS)
def test_b8_control_path_functions_never_mention_the_new_names(fn):
    src = inspect.getsource(getattr(foundry, fn))
    hits = [n for n in NEW_NAMES if n in src]
    assert hits == [], f"foundry.{fn} must stay off the new names, found {hits}"


def test_b8_no_role_card_reads_the_flag():
    roles = sorted((_ROOT / "roles").glob("*.md"))
    assert roles, "roles/ must not be empty"
    offenders = [p.name for p in roles
                 if any(n in p.read_text() for n in
                        (FLAG_NAME, "restart_flag", "dispatch_restart_line"))]
    assert offenders == [], (
        f"the flag is operator-facing and must never gate a stage: {offenders}")


# --------------------------------------------------------------------------------------
# Behavior 9 -- WIRING PRECONDITION ONLY.  RECORDED DEVIATION, do not "fix" by asserting
# the call site: spec B9 asks the dispatcher shift loop to call the reporter, but
# dispatcher.py is frozen byte-unchanged by 26 permanent every-suite guards (see
# tests/test_control_path_freeze_scope.py, whose own docstring names dispatcher.py,
# scripts/ and .gitignore as the frozen control path), so ANY iteration that edits it
# reddens its own suite.  The reporter therefore ships DORMANT this iteration.  What IS
# assertable today -- and stays true after a future re-scoping iteration wires it -- is the
# precondition that made the one-line call safe to propose: a single-argument call that
# cannot raise and cannot return anything the shift loop must branch on.  A count-based
# "zero call sites" assertion is deliberately NOT made, because that is exactly the
# every-suite freeze that test_control_path_freeze_scope.py exists to forbid: it would
# redden the suite of the legitimate future iteration that adds the pedal.
# --------------------------------------------------------------------------------------
def test_b9_reporter_is_callable_from_a_shift_loop_with_cfg_alone():
    sig = inspect.signature(foundry.dispatch_restart_line)
    required = [p for p in sig.parameters.values()
                if p.default is inspect.Parameter.empty
                and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    assert len(required) == 1, (
        "a shift-loop call site can only supply cfg, like dispatch_progress_line")
    assert len(inspect.signature(foundry.dispatch_progress_line).parameters) == 1, (
        "the sibling reporter it is modelled on takes cfg alone")


def test_b9_a_raising_seam_cannot_end_a_shift_loop(monkeypatch, tmp_path):
    """Simulate the proposed call site: dlog(res) if res else pass, unguarded."""
    cfg, _ = _work_cfg(tmp_path)

    def _boom(*a, **k):
        raise RuntimeError("seam exploded mid-shift")

    monkeypatch.setattr(foundry, "live_lag_line", _boom)
    logged = []
    for _ in range(3):                      # three shifts, no try/except at the call site
        res = foundry.dispatch_restart_line(cfg)
        if res:
            logged.append(res)
    assert logged == [], "a broken seam must log nothing and must not stop the loop"


def test_b9_dispatcher_still_imports_and_keeps_its_own_reporter_call():
    dsrc = inspect.getsource(dispatcher)
    assert "dispatch_progress_line" in dsrc, (
        "the existing per-shift reporter call must be untouched")


# --------------------------------------------------------------------------------------
# Behavior 10 -- the runtime flag can never leak into a ship diff.
# --------------------------------------------------------------------------------------
def test_b10_flag_is_ignored_by_gits_own_matcher():
    for product in ("_platform", "some-future-product"):
        rel = f"products/{product}/{FLAG_NAME}"
        r = subprocess.run(["git", "check-ignore", "-q", rel],
                           cwd=str(_ROOT), capture_output=True, text=True)
        assert r.returncode == 0, (
            f"{rel} is NOT gitignored (rc={r.returncode}) -- the runtime flag would "
            "leak into a ship diff")


def test_b10_a_gitignore_entry_exists_for_the_flag():
    hits = [p for p in _ROOT.rglob(".gitignore")
            if ".git/" not in str(p) and FLAG_NAME in p.read_text()]
    assert hits, f"no .gitignore anywhere names {FLAG_NAME}"


# --------------------------------------------------------------------------------------
# Acceptance-Criteria oracles.
# --------------------------------------------------------------------------------------
def test_ac_both_modules_import_in_a_fresh_interpreter():
    for mod in ("foundry", "dispatcher"):
        r = subprocess.run([sys.executable, "-c", f"import {mod}"],
                           cwd=str(_ROOT), capture_output=True, text=True)
        assert r.returncode == 0, f"import {mod} failed: {r.stderr[-400:]}"


def test_ac_reporter_writes_nothing_but_the_flag(monkeypatch, tmp_path):
    cfg, root = _work_cfg(tmp_path)
    state = root / "state" / "iter-999"
    state.mkdir(parents=True)
    (state / "keep.md").write_text("existing stage output\n")
    _script(monkeypatch, WARN_LINE)
    foundry.dispatch_restart_line(cfg)
    tree = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    assert tree == [FLAG_NAME, "state/iter-999/keep.md"], (
        f"the reporter must add ONLY the flag, no resume state: {tree}")


def test_ac_no_stray_flag_file_in_the_product_tree():
    strays = [str(p.relative_to(_ROOT)) for p in (_ROOT / "products").glob(f"*/{FLAG_NAME}")]
    strays += [FLAG_NAME] if (_ROOT / FLAG_NAME).exists() else []
    r = subprocess.run(["git", "status", "--porcelain"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert FLAG_NAME not in r.stdout, (
        f"git sees the runtime flag: {[l for l in r.stdout.splitlines() if FLAG_NAME in l]}")
    assert (_ROOT / FLAG_NAME).exists() is False, (
        f"a repo-ROOT {FLAG_NAME} is NOT covered by the products/ ignore rule")
    assert isinstance(strays, list)


def test_ac_live_lag_core_is_not_entangled_with_the_new_names():
    for fn in ("live_lag_line",):
        src = inspect.getsource(getattr(foundry, fn))
        hits = [n for n in NEW_NAMES if n in src]
        assert hits == [], f"{fn} must be untouched by the flag work, found {hits}"


def test_ac_roadmap_records_this_iteration_in_both_files():
    index = (_ROOT / "PLATFORM_ROADMAP.md").read_text()
    archive = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text()
    rows = [ln for ln in index.splitlines() if ln.startswith(f"- iter {THIS_ITER} ")]
    assert len(rows) == 1, f"expected exactly one iter-{THIS_ITER} ledger row, got {rows}"
    assert len(rows[0]) <= 120, f"ledger row must stay terse, got {len(rows[0])} chars"
    assert len(index) < 54000, f"index over its declared budget: {len(index)}"
    bullets = [ln for ln in archive.splitlines()
               if ln.startswith(f"- **iter {THIS_ITER} ")]
    assert len(bullets) == 1, f"expected one iter-{THIS_ITER} archive bullet, got {bullets}"
