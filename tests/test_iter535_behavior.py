"""Iteration 535 -- BLACK-BOX behavior tests: `head_of_branch` accepts only a real
40-hex ls-remote sha; both release gates and `postrelease_step` treat `"?"` as an
UNKNOWN head (never "moved", never cloned).

Spec under test (products/_platform/state/iter-535/pm.md), Expected Behaviors 1-11.

ISOLATION CONTRACT (HONORED): written from the iter-535 PM spec, the conventions of the
existing tests/ modules (test_iter01/03/127/194 harness shapes), and the product's OWN
observable surface (calling its public functions).  The implementation source, the
engineer/reviewer notes, IMPLEMENTATION.patch and `git diff` were NOT read.

OFFLINE + FRESH-CLONE SAFE: every seam (`git`, `time.sleep`, `run_stage`,
`head_of_branch`, `postrelease_step`, `verify_fresh_clone`, `revert_repo`, `log`) is
scripted; config, repo and work_root live in tmp_path.  No subprocess, no network.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402,F401  (import-safety probe -- the product quality bar)

ITER = 535
SHA_A = "0123456789abcdef0123456789abcdef01234567"
SHA_B = "fedcba9876543210fedcba9876543210fedcba98"
FATAL = "fatal: Could not read from remote repository."
BASE = "abc123456"
NEWHEAD = "def987654"
POST_SENTINEL = "POSTRELEASE: HEALTHY"
SHIP_BODY = "VERDICT: APPROVE\nRESULT: PASS\nACTION: PUSHED " + NEWHEAD + "\n"


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


def _cfg(tmp_path, **over):
    return foundry.load_config(str(_write_cfg(tmp_path, **over)))


@pytest.fixture
def cfg(tmp_path):
    return _cfg(tmp_path)


def _iter_dir(cfg, iteration):
    return pathlib.Path(cfg.state) / ("iter-%02d" % iteration)


class _GitScript:
    """Scripted `git` seam: pops replies left to right (last sticks); records argv."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, cfg, *args, **kw):
        self.calls.append(args)
        if len(self.replies) > 1:
            return self.replies.pop(0)
        return self.replies[0]


def _seam_git(monkeypatch, replies):
    g = _GitScript(replies)
    sleeps = []
    monkeypatch.setattr(foundry, "git", g)
    monkeypatch.setattr(foundry.time, "sleep", lambda s: sleeps.append(s))
    return g, sleeps


# ===========================================================================
# Behavior 1 -- is_remote_sha
# ===========================================================================
@pytest.mark.parametrize("tok,expected", [
    (SHA_A, True),
    (SHA_B, True),
    ("0" * 40, True),
    ("fatal:", False),
    ("", False),
    ("?", False),
    (SHA_A[:9], False),
    (SHA_A + "a", False),
    ("g" + SHA_A[1:], False),
    (SHA_A.upper(), False),
    (" " + SHA_A, False),
    (SHA_A + "\n", False),
    (None, False),
    (12345, False),
    (["a" * 40], False),
], ids=["sha_a", "sha_b", "zeros", "fatal", "empty", "q", "prefix9", "hex41", "has_g",
        "upper", "lead_space", "trail_nl", "none", "int", "list"])
def test_b1_is_remote_sha(tok, expected):
    assert foundry.is_remote_sha(tok) is expected


# ===========================================================================
# Behavior 2 -- clean reply
# ===========================================================================
def test_b2_clean_reply_returns_prefix_after_one_call(cfg, monkeypatch):
    g, sleeps = _seam_git(monkeypatch, [SHA_A + "\trefs/heads/main"])
    assert foundry.head_of_branch(cfg) == SHA_A[:9]
    assert len(g.calls) == 1
    assert sleeps == []
    assert "ls-remote" in g.calls[0]


# ===========================================================================
# Behavior 3 -- persistent failure -> "?" after 1 + RETRIES calls, RETRIES sleeps
# ===========================================================================
def test_b3_module_globals_defaults():
    assert foundry.HEAD_OF_BRANCH_RETRIES == 2
    assert foundry.HEAD_OF_BRANCH_RETRY_SECONDS == 5


def test_b3_persistent_failure_default(cfg, monkeypatch):
    g, sleeps = _seam_git(monkeypatch, [FATAL])
    assert foundry.head_of_branch(cfg) == "?"
    assert len(g.calls) == 3
    assert sleeps == [5, 5]


@pytest.mark.parametrize("retries,secs", [(1, 0.25), (4, 7)])
def test_b3_globals_read_at_call_time(cfg, monkeypatch, retries, secs):
    monkeypatch.setattr(foundry, "HEAD_OF_BRANCH_RETRIES", retries)
    monkeypatch.setattr(foundry, "HEAD_OF_BRANCH_RETRY_SECONDS", secs)
    g, sleeps = _seam_git(monkeypatch, ["error: something else broke"])
    assert foundry.head_of_branch(cfg) == "?"
    assert len(g.calls) == 1 + retries
    assert sleeps == [secs] * retries


def test_b3_fatal_never_leaks_as_a_head(cfg, monkeypatch):
    _seam_git(monkeypatch, [FATAL])
    out = foundry.head_of_branch(cfg)
    assert "fatal" not in out
    assert out == "?"


# ===========================================================================
# Behavior 4 -- transient failure recovers
# ===========================================================================
def test_b4_transient_failure_recovers(cfg, monkeypatch):
    g, sleeps = _seam_git(monkeypatch, [FATAL, SHA_B + "\trefs/heads/main"])
    assert foundry.head_of_branch(cfg) == SHA_B[:9]
    assert len(g.calls) == 2
    assert len(sleeps) == 1


# ===========================================================================
# Behavior 5 -- empty reply is never retried; RETRIES=0 means one call
# ===========================================================================
def test_b5_empty_reply_one_call_no_sleep(cfg, monkeypatch):
    g, sleeps = _seam_git(monkeypatch, ["", SHA_A + "\trefs/heads/main"])
    assert foundry.head_of_branch(cfg) == "?"
    assert len(g.calls) == 1
    assert sleeps == []


def test_b5_zero_retries_fatal_one_call(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "HEAD_OF_BRANCH_RETRIES", 0)
    g, sleeps = _seam_git(monkeypatch, [FATAL, SHA_A + "\trefs/heads/main"])
    assert foundry.head_of_branch(cfg) == "?"
    assert len(g.calls) == 1
    assert sleeps == []


# ===========================================================================
# Behavior 6 -- check_remote over the real head_of_branch
# ===========================================================================
def test_b6_check_remote_fatal_is_not_ok(cfg, monkeypatch):
    _seam_git(monkeypatch, [FATAL])
    c = foundry.check_remote(cfg)
    assert c.ok is False
    assert c.detail == "origin/%s unreachable (ls-remote failed)" % cfg.branch
    assert "fatal" not in c.detail


def test_b6_check_remote_sha_is_ok(cfg, monkeypatch):
    _seam_git(monkeypatch, [SHA_A + "\trefs/heads/main"])
    c = foundry.check_remote(cfg)
    assert c.ok is True
    assert c.detail == "origin/%s at %s" % (cfg.branch, SHA_A[:9])


# ===========================================================================
# Behavior 7 -- heads_moved
# ===========================================================================
@pytest.mark.parametrize("base,new,expected", [
    ("abc123456", "def987654", True),
    ("abc123456", "abc123456", False),
    ("?", "def987654", False),
    ("abc123456", "?", False),
    ("?", "?", False),
    ("", "def987654", False),
    ("abc123456", "", False),
    ("", "", False),
    ("base0000", "newhead99", True),
    ("base0000", "base0000", False),
])
def test_b7_heads_moved(base, new, expected):
    assert foundry.heads_moved(base, new) is expected


# ===========================================================================
# Behaviors 8/9/10 -- both release gates
# ===========================================================================
def _make_run_stage(body):
    def run_stage(cfg, iteration, stage, role_file, out_name, extra=""):
        d = _iter_dir(cfg, iteration)
        d.mkdir(parents=True, exist_ok=True)
        out = d / out_name
        out.write_text(body)
        return True, out
    return run_stage


def _patch_gate(monkeypatch, *, head, body=SHIP_BODY):
    ev = {"post": [], "revert": [], "log": []}
    monkeypatch.setattr(foundry, "run_stage", _make_run_stage(body))
    monkeypatch.setattr(foundry, "head_of_branch", head)
    monkeypatch.setattr(foundry, "revert_repo",
                        lambda cfg, reason, *a, **k: ev["revert"].append(reason))

    def post(cfg, it, sha, *a, **k):
        ev["post"].append(sha)
        return foundry.PostReleaseResult(True, False, POST_SENTINEL)
    monkeypatch.setattr(foundry, "postrelease_step", post)
    monkeypatch.setattr(foundry, "next_iteration", lambda *a, **k: ITER)
    monkeypatch.setattr(foundry, "log",
                        lambda *a, **k: ev["log"].append(" ".join(str(x) for x in a)))
    monkeypatch.setattr(foundry, "power_state", lambda: "Now drawing from 'AC Power'")
    monkeypatch.setattr(foundry, "iteration_is_scouted", lambda c, n: True)
    monkeypatch.setattr(foundry, "refresh_directions_file", lambda c: True)
    monkeypatch.setattr(foundry, "stage_attempt_killed", lambda *a, **k: False)
    return ev


def _drive_iteration(monkeypatch, tmp_path, base, new, body=SHIP_BODY):
    cfg = _cfg(tmp_path)
    seq = [base, new]

    def head(c):
        return seq.pop(0) if len(seq) > 1 else seq[0]
    ev = _patch_gate(monkeypatch, head=head, body=body)
    res = foundry.run_iteration(cfg, ITER)
    return res, ev, cfg


def _drive_plan(monkeypatch, tmp_path, base, new, body=SHIP_BODY):
    cfg = _cfg(tmp_path)
    ev = _patch_gate(monkeypatch, head=lambda c: new, body=body)
    plan = foundry.derive_execution_plan(foundry._default_stage_sequence())
    assert any(foundry.is_ship_gate(p) if hasattr(foundry, "is_ship_gate")
               else getattr(p, "gate", None) == "release" for p in plan)
    res = foundry.run_execution_plan(cfg, ITER, plan, base)
    return res, ev, cfg


DRIVERS = [_drive_iteration, _drive_plan]
DRIVER_IDS = ["run_iteration", "run_execution_plan"]


def _shipped_logs(ev):
    return [ln for ln in ev["log"] if "SHIPPED" in ln]


def _unknown_logs(ev, cfg):
    return [ln for ln in ev["log"]
            if "head unknown" in ln and ("origin/%s" % cfg.branch) in ln]


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b8_b9_known_moved_head_ships(monkeypatch, tmp_path, drive):
    """Positive control: the harness CAN reach a ship, so the negatives are not vacuous."""
    res, ev, cfg = drive(monkeypatch, tmp_path, BASE, NEWHEAD)
    assert res.get("status") == "shipped", (res, ev)
    assert ev["post"] == [NEWHEAD]
    assert ev["revert"] == []
    assert _shipped_logs(ev)
    assert _unknown_logs(ev, cfg) == []


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
@pytest.mark.parametrize("base,new", [(BASE, "?"), ("?", NEWHEAD), ("?", "?")],
                         ids=["new_unknown", "base_unknown", "both_unknown"])
def test_b8_b9_unknown_head_never_ships(monkeypatch, tmp_path, drive, base, new):
    res, ev, cfg = drive(monkeypatch, tmp_path, base, new)
    assert res.get("status") == "no-ship", (res, ev)
    assert ev["post"] == [], "postrelease_step must not clone an unknown head"
    assert len(ev["revert"]) == 1
    assert _shipped_logs(ev) == [], ev["log"]


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
@pytest.mark.parametrize("base,new", [(BASE, "?"), ("?", NEWHEAD), ("?", "?")],
                         ids=["new_unknown", "base_unknown", "both_unknown"])
def test_b10_unknown_head_logs_one_diagnostic(monkeypatch, tmp_path, drive, base, new):
    res, ev, cfg = drive(monkeypatch, tmp_path, base, new)
    assert len(_unknown_logs(ev, cfg)) == 1, ev["log"]


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b10_real_did_not_move_has_no_unknown_line(monkeypatch, tmp_path, drive):
    res, ev, cfg = drive(monkeypatch, tmp_path, BASE, BASE)
    assert res.get("status") == "no-ship"
    assert ev["post"] == []
    assert _unknown_logs(ev, cfg) == [], ev["log"]


@pytest.mark.parametrize("drive", DRIVERS, ids=DRIVER_IDS)
def test_b10_reverted_action_with_unknown_head_has_no_unknown_line(monkeypatch, tmp_path,
                                                                   drive):
    body = "VERDICT: APPROVE\nRESULT: PASS\nACTION: REVERTED nothing to ship\n"
    res, ev, cfg = drive(monkeypatch, tmp_path, BASE, "?", body=body)
    assert res.get("status") == "no-ship"
    assert ev["post"] == []
    assert _unknown_logs(ev, cfg) == [], ev["log"]


# ===========================================================================
# Behavior 11 -- postrelease_step short-circuits on "?"
# ===========================================================================
def _spy_verify(monkeypatch, result):
    calls = []

    def v(cfg, expected_sha, clone_dir, *a, **k):
        calls.append(expected_sha)
        return result
    monkeypatch.setattr(foundry, "verify_fresh_clone", v)
    return calls


def test_b11_unknown_head_skips_clone_and_keeps_flag(cfg, monkeypatch):
    assert cfg.postrelease_enabled is True
    foundry.write_hotfix_flag(cfg, "realsha", "a real earlier breakage")
    flag = foundry.hotfix_flag_path(cfg)
    before = flag.read_bytes()
    calls = _spy_verify(monkeypatch, foundry.PostReleaseResult(False, False, "BROKEN"))
    r = foundry.postrelease_step(cfg, ITER, "?")
    assert calls == [], "verify_fresh_clone must not run for an unknown head"
    assert r.healthy is True and r.skipped_infra is True
    assert flag.read_bytes() == before, "hotfix flag must be neither written nor cleared"
    assert (_iter_dir(cfg, ITER) / "postrelease.md").exists()
    assert (_iter_dir(cfg, ITER) / "postrelease.md").read_text().strip()


def test_b11_unknown_head_raises_no_flag(cfg, monkeypatch):
    _spy_verify(monkeypatch, foundry.PostReleaseResult(False, False, "BROKEN"))
    foundry.postrelease_step(cfg, ITER, "?")
    assert not foundry.hotfix_flag_path(cfg).exists()


def test_b11_real_head_still_verifies(cfg, monkeypatch):
    calls = _spy_verify(monkeypatch, foundry.PostReleaseResult(True, False, "ok"))
    r = foundry.postrelease_step(cfg, ITER, "abc123456")
    assert calls == ["abc123456"]
    assert r.healthy is True and r.skipped_infra is False


# ===========================================================================
# AC -- import safety, git() / ship_decision untouched surface
# ===========================================================================
def test_ac_helpers_are_module_level_callables():
    assert callable(foundry.is_remote_sha)
    assert callable(foundry.heads_moved)
    assert callable(foundry.ship_decision)
    assert callable(foundry.git)
