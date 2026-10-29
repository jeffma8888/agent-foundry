"""Behaviour tests for iter 488 -- opt-in `auth_resume_max`: re-run the SAME
stage after a STOP-aware auth hold, up to N times (default 0 = today's loop).

Spec: products/_platform/state/iter-488/pm.md, Expected Behaviors 1-12.

ISOLATION: written by the tester stage under its black-box contract -- the
spec, tests/, README and the product's runtime output only; no implementation
source, no diff, no engineer/reviewer notes. run_stage is driven the way
tests/test_iter411_behavior.py drives it: build_prompt / stopping /
resolve_agent_endpoint patched, subprocess.run scripted, classification done by
the real classifier on scripted blobs (premise-asserted at import), and
sleep_interruptible recorded. time.sleep is armed to raise. Nothing real is
spawned or slept; every path is tmp_path-rooted and no gitignored state is read.
"""
import dataclasses
import json
import pathlib
import re
import subprocess
import sys
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import foundry  # noqa: E402
import dispatcher  # noqa: E402,F401  (import-safety probe)

ITERATION = 5
SENTINEL = "SENTINEL-PROMPT-488"

AUTH_BLOB = "agent run failed: auth failed"
TIMEOUT_BLOB = "agent run timed out after 600s"

# Premise asserts: fixtures classify as the kinds the behaviors assume.
assert foundry.classify_attempt_failure(AUTH_BLOB) == foundry.AUTH_LOSS_KIND
assert foundry.classify_attempt_failure(TIMEOUT_BLOB) == "timeout"
assert foundry.MAX_ATTEMPTS == 4  # the spec's worked examples assume 4

HOLD_MARK = "backing off"
RESUME_MARK = "auth resume"


# --------------------------------------------------------------------------
# harness
# --------------------------------------------------------------------------
class _FakeCP:
    def __init__(self, rc=1, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def _write_cfg(root, resume=None):
    root.mkdir(parents=True, exist_ok=True)
    repo = root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (root / "VISION.md").write_text("vision\n")
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(root / "VISION.md"),
        "work_root": str(root / "work"),
    }
    if resume is not None:
        data["auth_resume_max"] = resume
    p = root / "config.json"
    p.write_text(json.dumps(data))
    return p


def _make_cfg(root, resume=None):
    return foundry.load_config(str(_write_cfg(root, resume)))


def _role_file(root):
    r = root / "role.md"
    r.write_text("do the thing\n")
    return str(r)


def _patch_common(monkeypatch, stop=False):
    monkeypatch.setattr(foundry, "build_prompt", lambda *a, **k: SENTINEL)
    monkeypatch.setattr(foundry, "stopping", lambda _cfg: stop)
    monkeypatch.setattr(foundry, "resolve_agent_endpoint", lambda *a, **k: None)


def _no_time_sleep(*_a, **_k):
    raise AssertionError("time.sleep reached -- holds must use sleep_interruptible")


def _discover_out_path(monkeypatch, root, stage, out_name):
    cfg = _make_cfg(root)
    role = _role_file(root)
    _patch_common(monkeypatch, stop=True)
    spawns = []
    monkeypatch.setattr(foundry.subprocess, "run",
                        lambda *a, **k: spawns.append(1) or _FakeCP())
    ok, out = foundry.run_stage(cfg, ITERATION, stage, role, out_name)
    assert ok is False and not out.exists() and spawns == []
    return out.relative_to(root)


def _drive(monkeypatch, tmp_path, blobs, resume=None, sleep_ret=False,
           write_out_on=None, stage="engineer"):
    """attempt n returns blobs[n-1] (last repeats). write_out_on=n makes spawn
    n write a non-empty out_file. sleep_ret may be a bool or a list (per call)."""
    out_name = "%s.md" % stage
    root = tmp_path / "run"
    out_rel = None
    if write_out_on is not None:
        out_rel = _discover_out_path(monkeypatch, tmp_path / "probe", stage, out_name)
    cfg = _make_cfg(root, resume)
    role = _role_file(root)
    _patch_common(monkeypatch)
    monkeypatch.setattr(foundry.time, "sleep", _no_time_sleep)

    sleeps = []

    def fake_sleep(_cfg, seconds):
        sleeps.append(seconds)
        if isinstance(sleep_ret, list):
            return sleep_ret[len(sleeps) - 1]
        return sleep_ret

    monkeypatch.setattr(foundry, "sleep_interruptible", fake_sleep)
    calls = []

    def fake_run(*a, **k):
        calls.append(1)
        n = len(calls)
        if write_out_on is not None and n == write_out_on:
            target = root / out_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("STAGE OUTPUT\n")
        return _FakeCP(out=blobs[min(n, len(blobs)) - 1])

    monkeypatch.setattr(foundry.subprocess, "run", fake_run)
    ok, out = foundry.run_stage(cfg, ITERATION, stage, role, out_name)
    lines = (cfg.night_log.read_text().splitlines()
             if cfg.night_log.exists() else [])
    return types.SimpleNamespace(ok=ok, out=out, calls=calls, sleeps=sleeps,
                                 log_lines=lines, cfg=cfg, stage=stage)


def _hold_lines(d):
    return [ln for ln in d.log_lines
            if "%s 30 min (failure kind: auth)" % HOLD_MARK in ln and "auth hold" in ln]


def _resume_lines(d):
    return [ln for ln in d.log_lines if RESUME_MARK in ln]


def _from_iter(line):
    """Strip any timestamp prefix: compare lines from `iter NN` onward."""
    i = line.find("iter %02d" % ITERATION)
    assert i >= 0, line
    return line[i:]


def _rd(n):
    return foundry.retry_delay("timeout", n)


# ==========================================================================
# Behavior 1 -- config field
# ==========================================================================
def test_b1_field_in_config_field_names():
    assert "auth_resume_max" in foundry.config_field_names()


def test_b1_field_declared_last_after_notify_cmd():
    names = list(foundry.config_field_names())
    assert names[-1] == "auth_resume_max"
    assert names[-2] == "notify_cmd"
    assert names.count("auth_resume_max") == 1


def test_b1_dataclass_default_is_zero():
    f = {x.name: x for x in dataclasses.fields(foundry.ProductConfig)}
    assert f["auth_resume_max"].default == 0


def test_b1_config_without_key_loads_zero(tmp_path):
    cfg = _make_cfg(tmp_path)
    assert cfg.auth_resume_max == 0


def test_b1_config_with_key_loads_value_and_does_not_raise(tmp_path):
    cfg = _make_cfg(tmp_path, resume=2)
    assert cfg.auth_resume_max == 2


# ==========================================================================
# Behavior 2 -- pure budget helper
# ==========================================================================
@pytest.mark.parametrize("value,expected", [
    (0, 0), (1, 1), (2, 2), (7, 7),
    (-1, 0), (-5, 0),
    (True, 0), (False, 0),
    ("2", 0), (None, 0), (1.0, 0), (2.5, 0),
])
def test_b2_auth_resume_budget(value, expected):
    got = foundry.auth_resume_budget(types.SimpleNamespace(auth_resume_max=value))
    assert got == expected
    assert type(got) is int


def test_b2_missing_attribute_returns_zero_without_raising():
    assert foundry.auth_resume_budget(types.SimpleNamespace()) == 0
    assert foundry.auth_resume_budget(object()) == 0


def test_b2_reads_a_real_loaded_config(tmp_path):
    assert foundry.auth_resume_budget(_make_cfg(tmp_path / "a", resume=3)) == 3
    assert foundry.auth_resume_budget(_make_cfg(tmp_path / "b")) == 0


# ==========================================================================
# Behavior 3 -- default 0 is unchanged
# ==========================================================================
@pytest.mark.parametrize("resume", [None, 0], ids=["absent", "explicit-0"])
@pytest.mark.parametrize("sleep_ret", [False, True], ids=["no-stop", "stop"])
def test_b3_default_one_spawn_one_hold_false(tmp_path, monkeypatch, resume, sleep_ret):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB], resume=resume, sleep_ret=sleep_ret)
    assert d.ok is False
    assert isinstance(d.out, pathlib.Path) and not d.out.exists()
    assert len(d.calls) == 1
    assert d.sleeps == [foundry.AUTH_HOLD_SECONDS]
    assert len(_hold_lines(d)) == 1
    assert _resume_lines(d) == []


def test_b3_hold_line_identical_with_and_without_opt_in(tmp_path, monkeypatch):
    """The hold line must not change shape when the opt-in is set."""
    d0 = _drive(monkeypatch, tmp_path / "n0", [AUTH_BLOB])
    d1 = _drive(monkeypatch, tmp_path / "n1", [AUTH_BLOB], resume=1,
                write_out_on=2)
    (h0,) = _hold_lines(d0)
    (h1,) = _hold_lines(d1)
    assert _from_iter(h0) == _from_iter(h1)


# ==========================================================================
# Behavior 4 -- resume succeeds
# ==========================================================================
def test_b4_resume_then_output_written_returns_true(tmp_path, monkeypatch):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB, TIMEOUT_BLOB], resume=1,
               write_out_on=2)
    assert d.ok is True
    assert d.out.exists() and d.out.read_text().strip()
    assert len(d.calls) == 2
    assert d.sleeps == [foundry.AUTH_HOLD_SECONDS]


def test_b4_auth_on_last_attempt_with_budget_left_still_resumes(tmp_path, monkeypatch):
    """timeout x3 then auth on attempt MAX_ATTEMPTS: the resume must extend the
    bound so attempt 5 actually runs."""
    d = _drive(monkeypatch, tmp_path,
               [TIMEOUT_BLOB, TIMEOUT_BLOB, TIMEOUT_BLOB, AUTH_BLOB, TIMEOUT_BLOB],
               resume=1, write_out_on=5)
    assert d.ok is True
    assert len(d.calls) == 5
    assert d.sleeps == [_rd(1), _rd(2), _rd(3), foundry.AUTH_HOLD_SECONDS]


# ==========================================================================
# Behavior 5 -- STOP during the hold
# ==========================================================================
@pytest.mark.parametrize("resume", [1, 3])
def test_b5_stop_in_hold_returns_false_without_respawn(tmp_path, monkeypatch, resume):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB, TIMEOUT_BLOB], resume=resume,
               sleep_ret=True, write_out_on=2)
    assert d.ok is False
    assert len(d.calls) == 1
    assert d.sleeps == [foundry.AUTH_HOLD_SECONDS]
    assert _resume_lines(d) == []


def test_b5_stop_in_second_hold_stops_there(tmp_path, monkeypatch):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB], resume=3,
               sleep_ret=[False, True, False, False])
    assert d.ok is False
    assert len(d.calls) == 2
    assert d.sleeps == [foundry.AUTH_HOLD_SECONDS] * 2


# ==========================================================================
# Behavior 6 -- resumes exhausted
# ==========================================================================
@pytest.mark.parametrize("resume,spawns", [(1, 2), (2, 3), (3, 4)])
def test_b6_all_auth_exhausts_budget(tmp_path, monkeypatch, resume, spawns):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB], resume=resume)
    assert d.ok is False
    assert not d.out.exists()
    assert len(d.calls) == spawns
    assert d.sleeps == [foundry.AUTH_HOLD_SECONDS] * spawns
    assert len(_hold_lines(d)) == spawns
    assert len(_resume_lines(d)) == resume


# ==========================================================================
# Behavior 7 -- monotonic artifact names
# ==========================================================================
def test_b7_monotonic_attempt_logs_and_prompts(tmp_path, monkeypatch):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB], resume=2, stage="pm")
    sd = d.out.parent
    for n in (1, 2, 3):
        log = sd / ("pm.attempt%d.log" % n)
        assert log.exists(), sorted(p.name for p in sd.iterdir())
        assert AUTH_BLOB in log.read_text()
        m = foundry._ATTEMPT_LOG_RE.match(log.name)
        assert m, log.name
        assert m.group("stage") == "pm" and int(m.group("attempt")) == n
        assert (sd / ("pm.attempt%d.prompt" % n)).exists()
    assert not (sd / "pm.attempt4.log").exists()
    logs = sorted(p.name for p in sd.glob("pm*.log"))
    assert logs == ["pm.attempt1.log", "pm.attempt2.log", "pm.attempt3.log"]


def test_b7_each_attempt_log_holds_only_its_own_blob(tmp_path, monkeypatch):
    blobs = [AUTH_BLOB + " #1", AUTH_BLOB + " #2", AUTH_BLOB + " #3"]
    for b in blobs:
        assert foundry.classify_attempt_failure(b) == foundry.AUTH_LOSS_KIND
    d = _drive(monkeypatch, tmp_path, blobs, resume=2)
    sd = d.out.parent
    for n, b in enumerate(blobs, 1):
        text = (sd / ("engineer.attempt%d.log" % n)).read_text()
        assert b in text
        for other in blobs:
            if other != b:
                assert other not in text, (n, other)


# ==========================================================================
# Behavior 8 -- resume does not use up the non-auth budget
# ==========================================================================
def test_b8_auth_then_timeout_forever_gets_max_plus_one(tmp_path, monkeypatch):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB, TIMEOUT_BLOB], resume=1)
    assert d.ok is False
    assert len(d.calls) == foundry.MAX_ATTEMPTS + 1 == 5
    # hold, then the timeout ladder exactly as today, none after the last attempt
    assert d.sleeps == [foundry.AUTH_HOLD_SECONDS, _rd(1), _rd(2), _rd(3)]


def test_b8_unused_budget_never_adds_spawns(tmp_path, monkeypatch):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB, TIMEOUT_BLOB], resume=3)
    assert len(d.calls) == foundry.MAX_ATTEMPTS + 1
    assert len(_resume_lines(d)) == 1


# ==========================================================================
# Behavior 9 -- resume log line
# ==========================================================================
def test_b9_resume_line_shape_and_order(tmp_path, monkeypatch):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB], resume=2)
    res = _resume_lines(d)
    assert len(res) == 2
    assert "iter 05 · engineer auth resume 1/2: re-running stage after hold" in res[0]
    assert "iter 05 · engineer auth resume 2/2: re-running stage after hold" in res[1]
    idx = {i: ln for i, ln in enumerate(d.log_lines)}
    holds = [i for i, ln in idx.items() if ln in _hold_lines(d)]
    resumes = [i for i, ln in idx.items() if RESUME_MARK in ln]
    assert len(holds) == 3
    # each resume line comes right after the hold it follows
    assert resumes[0] > holds[0] and resumes[0] < holds[1]
    assert resumes[1] > holds[1] and resumes[1] < holds[2]
    # the final (exhausted) hold is not followed by a resume line
    assert all(r < holds[2] for r in resumes)


def test_b9_resume_line_names_the_stage(tmp_path, monkeypatch):
    d = _drive(monkeypatch, tmp_path, [AUTH_BLOB], resume=1, stage="pm")
    (line,) = _resume_lines(d)
    assert "pm auth resume 1/1: re-running stage after hold" in line


# ==========================================================================
# Behavior 10 -- non-auth kinds unchanged at any N
# ==========================================================================
def test_b10_timeout_identical_at_n3_and_n0(tmp_path, monkeypatch):
    d0 = _drive(monkeypatch, tmp_path / "n0", [TIMEOUT_BLOB])
    d3 = _drive(monkeypatch, tmp_path / "n3", [TIMEOUT_BLOB], resume=3)
    assert len(d0.calls) == len(d3.calls) == foundry.MAX_ATTEMPTS
    assert d3.sleeps == d0.sleeps == [_rd(n) for n in range(1, foundry.MAX_ATTEMPTS)]
    assert _resume_lines(d3) == [] and _resume_lines(d0) == []
    assert ([_from_iter(x) for x in d3.log_lines if HOLD_MARK in x]
            == [_from_iter(x) for x in d0.log_lines if HOLD_MARK in x])
    assert d3.ok is False and d0.ok is False


# ==========================================================================
# Behavior 11 -- docs stay honest
# ==========================================================================
def _resilience_text():
    return (REPO / "ARCHITECTURE.md").read_text()


def test_b11_auth_hold_claims_have_no_gaps():
    assert foundry.auth_hold_claim_gaps(_resilience_text()) == ()


def test_b11_architecture_names_opt_in_and_hold():
    flat = " ".join(_resilience_text().split())
    assert "auth_resume_max" in flat
    i = flat.find("auth_resume_max")
    window = flat[max(0, i - 300): i + 400]
    assert "opt-in" in window.lower()
    assert re.search(r"default\s*(=|:|is|of)?\s*0", window), window
    assert "AUTH_HOLD_SECONDS" in flat
    assert "30 min" in flat


# ==========================================================================
# Behavior 12 -- dormant by default + import safety
# ==========================================================================
def _tracked_configs():
    out = subprocess.run(["git", "ls-files", "products/*/config.json",
                          "foundry.config.json"],
                         cwd=REPO, capture_output=True, text=True, check=True)
    return [REPO / p for p in out.stdout.split()]


def test_b12_no_tracked_config_sets_auth_resume_max():
    paths = _tracked_configs()
    assert paths, "expected tracked product configs"
    for p in paths:
        data = json.loads(p.read_text())
        assert "auth_resume_max" not in data, p.name


def test_b12_fresh_interpreter_imports_both_modules():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=REPO, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_this_file_has_no_absolute_machine_paths():
    body = pathlib.Path(__file__).read_text().split('"""', 2)[2]
    for needle in ("/Us" + "ers/", "/ho" + "me/", "C:" + "\\"):
        assert needle not in body, needle
