"""Iteration 536 -- BLACK-BOX behavior tests: `await_known_base` holds an iteration whose
start head is unknown (`"?"` / `""`) on the iter-531 unreachable constants, and
`run_iteration` starts no stage until the head is known.

Spec under test (products/_platform/state/iter-536/pm.md), Expected Behaviors 1-8.

ISOLATION CONTRACT (HONORED): written from the iter-536 PM spec, the conventions of the
existing tests/ modules (test_iter531/535 harness shapes), and the product's OWN observable
surface (calling its public functions).  The implementation source, the engineer/reviewer
notes, IMPLEMENTATION.patch and `git diff` were NOT read.

OFFLINE + FRESH-CLONE SAFE: every seam (`head_of_branch`, `sleep_interruptible`, `log`,
`run_stage`, `postrelease_step`, `revert_repo`, `scout_phase_outcome`, ...) is scripted;
config, repo and work_root live in tmp_path.  No real git, network or sleep.  The
behavior-8 baseline is loaded from a PINNED pre-iteration sha and skipped if absent.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402,F401  (import-safety probe -- the product quality bar)

ITER = 536
BASE_SHA_PIN = "2a1a4a2"  # iter-535 ship: the pre-iteration baseline for behavior 8
POST_SENTINEL = "POSTRELEASE: HEALTHY"
NEWHEAD = "newhead99"
SHIP_BODY = "VERDICT: APPROVE\nRESULT: PASS\nACTION: PUSHED " + NEWHEAD + "\n"
HOLD_TAIL = ("start backing off 5 min (failure kind: unreachable) -- head unknown for "
             "origin/%s; holding before any stage runs")


def _write_cfg(tmp_path, **over):
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


def _cfg(tmp_path, mod=foundry):
    return mod.load_config(str(_write_cfg(tmp_path)))


@pytest.fixture
def cfg(tmp_path):
    return _cfg(tmp_path)


class _Script:
    """Pops scripted replies left to right (last sticks); counts calls."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        if len(self.replies) > 1:
            return self.replies.pop(0)
        return self.replies[0]


class _Sleep:
    def __init__(self, replies=(False,)):
        self.script = _Script(replies)
        self.seconds = []

    def __call__(self, cfg, seconds):
        self.seconds.append(seconds)
        return self.script()


def _seams(monkeypatch, heads, sleeps=(False,)):
    head = _Script(heads)
    sl = _Sleep(sleeps)
    logs = []
    monkeypatch.setattr(foundry, "head_of_branch", head)
    monkeypatch.setattr(foundry, "sleep_interruptible", sl)
    monkeypatch.setattr(foundry, "log", lambda c, msg: logs.append(str(msg)))
    return head, sl, logs


def _holds(logs):
    return [ln for ln in logs if "backing off" in ln]


def _pfx(n=ITER):
    return "iter %02d · " % n


# ===========================================================================
# Behavior 1 -- known base passes through untouched
# ===========================================================================
@pytest.mark.parametrize("base", ["base0000", "abc123456", "0123456789abcdef0123",
                                  "fatal:", "x"])
def test_b1_known_base_returned_unchanged(cfg, monkeypatch, base):
    head, sl, logs = _seams(monkeypatch, ["SHOULD-NOT-READ"])
    assert foundry.await_known_base(cfg, ITER, base) == base
    assert head.calls == 0
    assert sl.seconds == []
    assert logs == []


def test_b1_is_module_level_callable():
    assert callable(foundry.await_known_base)


# ===========================================================================
# Behavior 2 -- one hold line + one sleep + one re-read per hold
# ===========================================================================
@pytest.mark.parametrize("start", ["?", ""], ids=["q", "empty"])
def test_b2_single_hold_line_exact(cfg, monkeypatch, start):
    head, sl, logs = _seams(monkeypatch, ["abc123456"])
    assert foundry.await_known_base(cfg, ITER, start) == "abc123456"
    holds = _holds(logs)
    assert holds == [_pfx() + HOLD_TAIL % cfg.branch], logs
    assert sl.seconds == [foundry.UNREACHABLE_HOLD_SECONDS]
    assert head.calls == 1


def test_b2_iteration_number_zero_padded(cfg, monkeypatch):
    head, sl, logs = _seams(monkeypatch, ["abc123456"])
    foundry.await_known_base(cfg, 7, "?")
    assert _holds(logs) == ["iter 07 · " + HOLD_TAIL % cfg.branch]


def test_b2_minutes_read_from_hold_seconds_at_call_time(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "UNREACHABLE_HOLD_SECONDS", 120)
    head, sl, logs = _seams(monkeypatch, ["abc123456"])
    foundry.await_known_base(cfg, ITER, "?")
    assert sl.seconds == [120]
    holds = _holds(logs)
    assert len(holds) == 1 and "backing off 2 min" in holds[0], holds


# ===========================================================================
# Behavior 3 -- recovery
# ===========================================================================
def test_b3_recovers_after_two_holds(cfg, monkeypatch):
    head, sl, logs = _seams(monkeypatch, ["?", "abc123456"])
    assert foundry.await_known_base(cfg, ITER, "?") == "abc123456"
    assert sl.seconds == [foundry.UNREACHABLE_HOLD_SECONDS] * 2
    assert head.calls == 2
    assert len(_holds(logs)) == 2
    resumes = [ln for ln in logs if "unreachable resume" in ln]
    assert resumes == [_pfx() + "start unreachable resume 2/%d: origin/%s abc123456"
                       % (foundry.UNREACHABLE_RESUME_MAX, cfg.branch)], logs


def test_b3_resume_after_one_hold_counts_one(cfg, monkeypatch):
    head, sl, logs = _seams(monkeypatch, ["base0000"])
    assert foundry.await_known_base(cfg, ITER, "") == "base0000"
    resumes = [ln for ln in logs if "unreachable resume" in ln]
    assert resumes == [_pfx() + "start unreachable resume 1/%d: origin/%s base0000"
                       % (foundry.UNREACHABLE_RESUME_MAX, cfg.branch)]


# ===========================================================================
# Behavior 4 -- cap
# ===========================================================================
def _cap_line(logs, cfg):
    return [ln for ln in logs if "head still unknown" in ln
            and ("origin/%s" % cfg.branch) in ln and "not starting" in ln]


def test_b4_cap_default(cfg, monkeypatch):
    head, sl, logs = _seams(monkeypatch, ["?"])
    assert foundry.await_known_base(cfg, ITER, "?") is None
    m = foundry.UNREACHABLE_RESUME_MAX
    assert len(sl.seconds) == m
    assert head.calls == m
    assert len(_cap_line(logs, cfg)) == 1, logs
    assert not [ln for ln in logs if "unreachable resume" in ln]


def test_b4_cap_read_at_call_time_two(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "UNREACHABLE_RESUME_MAX", 2)
    head, sl, logs = _seams(monkeypatch, ["?", "", "?"])
    assert foundry.await_known_base(cfg, ITER, "?") is None
    assert len(sl.seconds) == 2 and head.calls == 2
    assert len(_cap_line(logs, cfg)) == 1


def test_b4_cap_zero_means_no_sleep_no_read(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "UNREACHABLE_RESUME_MAX", 0)
    head, sl, logs = _seams(monkeypatch, ["abc123456"])
    assert foundry.await_known_base(cfg, ITER, "?") is None
    assert sl.seconds == [] and head.calls == 0
    assert len(_cap_line(logs, cfg)) == 1


def test_b4_empty_reread_counts_as_unknown(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "UNREACHABLE_RESUME_MAX", 3)
    head, sl, logs = _seams(monkeypatch, [""])
    assert foundry.await_known_base(cfg, ITER, "?") is None
    assert head.calls == 3 and len(sl.seconds) == 3


def test_b4_hold_seconds_read_at_call_time(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "UNREACHABLE_RESUME_MAX", 2)
    monkeypatch.setattr(foundry, "UNREACHABLE_HOLD_SECONDS", 9)
    head, sl, logs = _seams(monkeypatch, ["?"])
    assert foundry.await_known_base(cfg, ITER, "?") is None
    assert sl.seconds == [9, 9]


# ===========================================================================
# Behavior 5 -- STOP
# ===========================================================================
def test_b5_stop_on_first_hold(cfg, monkeypatch):
    head, sl, logs = _seams(monkeypatch, ["abc123456"], sleeps=[True])
    assert foundry.await_known_base(cfg, ITER, "?") is None
    assert len(sl.seconds) == 1
    assert head.calls == 0


def test_b5_stop_on_second_hold(cfg, monkeypatch):
    head, sl, logs = _seams(monkeypatch, ["?", "abc123456"], sleeps=[False, True])
    assert foundry.await_known_base(cfg, ITER, "?") is None
    assert len(sl.seconds) == 2
    assert head.calls == 1


# ===========================================================================
# Behaviors 6/7/8 -- run_iteration wiring
# ===========================================================================
def _make_run_stage(body, calls):
    def run_stage(cfg, iteration, stage, role_file, out_name, extra=""):
        calls.append(stage)
        d = pathlib.Path(cfg.state) / ("iter-%02d" % iteration)
        d.mkdir(parents=True, exist_ok=True)
        out = d / out_name
        out.write_text(body)
        return True, out
    return run_stage


def _patch_iteration(monkeypatch, mod, heads, *, sleeps=(False,), body=SHIP_BODY,
                     hold=None):
    ev = {"post": [], "revert": [], "log": [], "stages": [], "scout": [],
          "staffing": [], "plan_base": [], "sleep": []}
    head = _Script(heads)
    ev["head"] = head
    sl = _Sleep(sleeps)
    ev["sleep_obj"] = sl
    monkeypatch.setattr(mod, "run_stage", _make_run_stage(body, ev["stages"]))
    monkeypatch.setattr(mod, "head_of_branch", head)
    monkeypatch.setattr(mod, "sleep_interruptible", sl)
    if hold is not None:
        monkeypatch.setattr(mod, "await_known_base", hold)
    monkeypatch.setattr(mod, "revert_repo",
                        lambda cfg, reason, *a, **k: ev["revert"].append(reason))

    def post(cfg, it, sha, *a, **k):
        ev["post"].append(sha)
        return mod.PostReleaseResult(True, False, POST_SENTINEL)
    monkeypatch.setattr(mod, "postrelease_step", post)
    monkeypatch.setattr(mod, "next_iteration", lambda *a, **k: ITER)
    monkeypatch.setattr(mod, "log", lambda c, msg: ev["log"].append(str(msg)))
    monkeypatch.setattr(mod, "power_state", lambda: "Now drawing from 'AC Power'")
    monkeypatch.setattr(mod, "iteration_is_scouted", lambda c, n: True)
    monkeypatch.setattr(mod, "refresh_directions_file", lambda c: True)
    monkeypatch.setattr(mod, "stage_attempt_killed", lambda *a, **k: False)

    real_scout = mod.scout_phase_outcome

    def scout(*a, **k):
        ev["scout"].append(1)
        return real_scout(*a, **k)
    monkeypatch.setattr(mod, "scout_phase_outcome", scout)
    real_staff = mod.load_staffing_manifest

    def staff(*a, **k):
        ev["staffing"].append(1)
        return real_staff(*a, **k)
    monkeypatch.setattr(mod, "load_staffing_manifest", staff)
    real_plan = mod.run_execution_plan

    def plan(cfg, iteration, p, base, *a, **k):
        ev["plan_base"].append(base)
        return real_plan(cfg, iteration, p, base, *a, **k)
    monkeypatch.setattr(mod, "run_execution_plan", plan)
    ev["moved"] = []
    if hasattr(mod, "heads_moved"):
        real_moved = mod.heads_moved

        def moved(a, b):
            ev["moved"].append((a, b))
            return real_moved(a, b)
        monkeypatch.setattr(mod, "heads_moved", moved)
    return ev


def _iter_dir(cfg, n=ITER):
    return pathlib.Path(cfg.state) / ("iter-%02d" % n)


@pytest.mark.parametrize("sleeps", [(False,), (True,)], ids=["cap", "stop"])
def test_b6_none_returns_infra_fail_before_any_stage(tmp_path, monkeypatch, sleeps):
    monkeypatch.setattr(foundry, "UNREACHABLE_RESUME_MAX", 2)
    cfg = _cfg(tmp_path)
    ev = _patch_iteration(monkeypatch, foundry, ["?"], sleeps=sleeps)
    res = foundry.run_iteration(cfg, ITER)
    assert res == {"status": "infra-fail", "stage": "start", "iteration": ITER}
    assert ev["stages"] == []
    assert ev["revert"] == []
    assert ev["scout"] == []
    assert ev["staffing"] == [], "hold must run BEFORE load_staffing_manifest"
    assert ev["post"] == []
    assert not _iter_dir(cfg).exists()


def test_b6_hold_called_by_bare_name_with_raw_first_read(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    seen = []

    def hold(c, i, b):
        seen.append((i, b, len(ev["staffing"])))
        return None
    ev = _patch_iteration(monkeypatch, foundry, ["?"], hold=hold)
    res = foundry.run_iteration(cfg, ITER)
    assert seen == [(ITER, "?", 0)]
    assert res == {"status": "infra-fail", "stage": "start", "iteration": ITER}
    begins = [ln for ln in ev["log"] if "begins" in ln]
    assert len(begins) == 1 and "?" in begins[0], ev["log"]


def test_b6_returned_head_becomes_base(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    ev = _patch_iteration(monkeypatch, foundry, ["?", NEWHEAD],
                          hold=lambda c, i, b: "replaced00")
    foundry.run_iteration(cfg, ITER)
    # The default (unstaffed) path gates inline; a staffed plan would get the base via
    # run_execution_plan.  Either way the release gate must compare the HELD head.
    assert ev["plan_base"] in ([], ["replaced00"])
    assert ev["moved"] and all(a == "replaced00" for a, _ in ev["moved"]), ev["moved"]
    assert ev["stages"], "a known head must let the run start"


def test_b7_end_to_end_recovers_and_ships(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    ev = _patch_iteration(monkeypatch, foundry, ["?", "base0000", NEWHEAD])
    res = foundry.run_iteration(cfg, ITER)
    assert res.get("status") == "shipped", (res, ev["log"])
    assert ev["post"] == [NEWHEAD]
    assert ev["plan_base"] in ([], ["base0000"])
    assert ev["moved"] == [("base0000", NEWHEAD)], ev["moved"]
    assert ev["sleep_obj"].seconds[:1] == [foundry.UNREACHABLE_HOLD_SECONDS]
    assert ev["revert"] == []


def test_b7_identity_hold_keeps_no_ship(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    ev = _patch_iteration(monkeypatch, foundry, ["?", NEWHEAD],
                          hold=lambda c, i, b: b)
    res = foundry.run_iteration(cfg, ITER)
    assert res.get("status") == "no-ship", res
    assert ev["post"] == []


def _load_baseline():
    try:
        src = subprocess.run(["git", "-C", str(_ROOT), "show", BASE_SHA_PIN + ":foundry.py"],
                             capture_output=True, text=True, timeout=30)
    except Exception:  # pragma: no cover
        return None
    if src.returncode != 0 or not src.stdout:
        return None
    name = "foundry_baseline_iter535_for536"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(_ROOT / "foundry.py")
    sys.modules[name] = mod
    exec(compile(src.stdout, mod.__file__, "exec"), mod.__dict__)
    return mod


def test_b8_known_head_same_reads_as_baseline_and_no_hold(tmp_path, monkeypatch):
    base_mod = _load_baseline()
    if base_mod is None:
        pytest.skip("pinned baseline %s not available" % BASE_SHA_PIN)
    assert not hasattr(base_mod, "await_known_base")
    cfg_new = _cfg(tmp_path / "new")
    ev_new = _patch_iteration(monkeypatch, foundry, ["base0000"])
    res_new = foundry.run_iteration(cfg_new, ITER)
    cfg_old = _cfg(tmp_path / "old", mod=base_mod)
    ev_old = _patch_iteration(monkeypatch, base_mod, ["base0000"])
    res_old = base_mod.run_iteration(cfg_old, ITER)
    assert ev_new["head"].calls == ev_old["head"].calls
    assert ev_new["sleep_obj"].seconds == ev_old["sleep_obj"].seconds
    assert res_new.get("status") == res_old.get("status")
    assert not [ln for ln in ev_new["log"] if "start backing off" in ln
                or "start unreachable resume" in ln]
    assert ev_new["stages"] == ev_old["stages"]


def test_b8_known_head_never_sleeps_in_hold(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    real = foundry.await_known_base
    sleeps_in_hold = []

    def spy(c, i, b):
        before = len(ev["sleep_obj"].seconds)
        r = real(c, i, b)
        sleeps_in_hold.append(len(ev["sleep_obj"].seconds) - before)
        return r
    ev = _patch_iteration(monkeypatch, foundry, ["base0000"], hold=spy)
    foundry.run_iteration(cfg, ITER)
    assert sleeps_in_hold == [0]


# ===========================================================================
# AC -- no tracking-ref fallback observable; import safety
# ===========================================================================
def test_ac_no_tracking_ref_fallback_in_hold(cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(foundry, "git", lambda c, *a, **k: calls.append(a) or "")
    monkeypatch.setattr(foundry, "UNREACHABLE_RESUME_MAX", 2)
    head, sl, logs = _seams(monkeypatch, ["?"])
    assert foundry.await_known_base(cfg, ITER, "?") is None
    assert not [a for a in calls if "rev-parse" in a], calls
