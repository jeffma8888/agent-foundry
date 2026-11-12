"""Behaviour tests for iter 531 -- a connect failure is an `unreachable` HOLD
(5-min hold, re-run the SAME stage, own cap 12), not a `stalled` ladder walk.

Spec: products/_platform/state/iter-531/pm.md, Expected Behaviors 1-12.

ISOLATION: written by the tester stage under its black-box contract -- the
spec, tests/, README and the product's runtime output only; no implementation
source, no diff, no engineer/reviewer notes. run_stage is driven the way
tests/test_iter488_behavior.py drives it: build_prompt / stopping /
resolve_agent_endpoint patched, subprocess.run scripted, classification done
by the real classifier, sleep_interruptible recorded, time.sleep armed to
raise. The pre-iteration baseline module (behaviors 3/10/11) is loaded from
`git show <BASELINE>:foundry.py` -- the commit that preceded iter 531 -- so
the golden stays a real HEAD-vs-tree comparison after the iter-531 commit.
Every path is tmp_path-rooted; no gitignored state is read.
"""
import importlib.util
import json
import pathlib
import subprocess
import sys
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import foundry  # noqa: E402
import dispatcher  # noqa: E402,F401  (import-safety probe)

ITERATION = 7
SENTINEL = "SENTINEL-PROMPT-531"
BASELINE = "82608eb66d73187be32cb907d7c87a29fd4c76db"  # iter 530 ship, pre-531

CONNECT = ('foundry-engine: connection stalled: Could not connect to the '
           'endpoint URL: "https://example.invalid/model"')
STALL = "Connection stalled, no data received for 120 s"
AUTH = "agent run failed: auth failed"
UNREACH_MARK = "backing off 5 min (failure kind: unreachable)"

assert foundry.MAX_ATTEMPTS == 4  # the spec's worked examples assume 4


# --------------------------------------------------------------------------
# harness
# --------------------------------------------------------------------------
class _FakeCP:
    def __init__(self, rc=1, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


_BASE_MOD = {}


def _baseline():
    if "m" in _BASE_MOD:
        return _BASE_MOD["m"]
    r = subprocess.run(["git", "-C", str(REPO), "show", "%s:foundry.py" % BASELINE],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("baseline commit not available in this clone")
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp(prefix="iter531-base-"))
    p = d / "foundry_base531.py"
    p.write_text(r.stdout)
    spec = importlib.util.spec_from_file_location("foundry_base531", str(p))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["foundry_base531"] = mod
    spec.loader.exec_module(mod)
    _BASE_MOD["m"] = mod
    return mod


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


def _no_time_sleep(*_a, **_k):
    raise AssertionError("time.sleep reached -- holds must use sleep_interruptible")


def _drive(monkeypatch, tmp_path, blobs, mod=foundry, resume=None,
           sleep_ret=False, write_out_on=None, stage="engineer", sub="run"):
    """attempt n returns blobs[n-1] (last repeats); write_out_on=n makes spawn
    n write a non-empty out_file (path learned from the cfg's state dir)."""
    root = tmp_path / sub
    cfg = mod.load_config(str(_write_cfg(root, resume)))
    role = root / "role.md"
    role.write_text("do the thing\n")
    monkeypatch.setattr(mod, "build_prompt", lambda *a, **k: SENTINEL)
    monkeypatch.setattr(mod, "stopping", lambda _cfg: False)
    monkeypatch.setattr(mod, "resolve_agent_endpoint", lambda *a, **k: None)
    monkeypatch.setattr(mod.time, "sleep", _no_time_sleep)
    notes = []
    monkeypatch.setattr(mod, "_notify_human_hold",
                        lambda *a, **k: notes.append((a, k)))
    sleeps = []

    def fake_sleep(_cfg, seconds):
        sleeps.append(seconds)
        if isinstance(sleep_ret, list):
            return sleep_ret[len(sleeps) - 1]
        return sleep_ret

    monkeypatch.setattr(mod, "sleep_interruptible", fake_sleep)
    calls = []
    out_name = "%s.md" % stage
    probe_root = tmp_path / ("probe-" + sub)
    real_target = root / _probe_out(mod, probe_root, stage).relative_to(probe_root)

    def run_writer(*a, **k):
        calls.append(1)
        n = len(calls)
        if write_out_on is not None and n == write_out_on:
            real_target.parent.mkdir(parents=True, exist_ok=True)
            real_target.write_text("STAGE OUTPUT\n")
        return _FakeCP(out=blobs[min(n, len(blobs)) - 1])

    monkeypatch.setattr(mod.subprocess, "run", run_writer)
    ok, out = mod.run_stage(cfg, ITERATION, stage, str(role), out_name)
    lines = (cfg.night_log.read_text().splitlines()
             if cfg.night_log.exists() else [])
    return types.SimpleNamespace(ok=ok, out=out, calls=calls, sleeps=sleeps,
                                 log=lines, notes=notes, stage=stage)


def _probe_out(mod, root, stage):
    """Resolve where run_stage puts out_file: stopping()==True returns at once."""
    cfg = mod.load_config(str(_write_cfg(root)))
    role = root / "role.md"
    role.write_text("x\n")
    saved_stop = mod.stopping
    saved_run = mod.subprocess.run
    mod.stopping = lambda _cfg: True
    mod.subprocess.run = lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawned"))
    try:
        ok, out = mod.run_stage(cfg, ITERATION, stage, str(role), "%s.md" % stage)
    finally:
        mod.stopping = saved_stop
        mod.subprocess.run = saved_run
    assert ok is False
    return out


def _tail(line):
    i = line.find("iter %02d" % ITERATION)
    assert i >= 0, line
    return line[i:]


def _resume(d, kind="unreachable"):
    return [ln for ln in d.log if "%s resume" % kind in ln]


# ==========================================================================
# Behavior 1 -- classifier
# ==========================================================================
@pytest.mark.parametrize("blob", [CONNECT, CONNECT.lower(), CONNECT.upper()])
def test_b1_connect_blob_classifies_unreachable(blob):
    assert foundry.classify_attempt_failure(blob) == "unreachable"


# ==========================================================================
# Behavior 2 -- plain stall unchanged
# ==========================================================================
def test_b2_plain_stall_is_still_stalled_with_its_ladder():
    assert foundry.classify_attempt_failure(STALL) == "stalled"
    assert foundry.classify_attempt_failure("foundry-engine: connection stalled") == "stalled"
    assert [foundry.retry_delay("stalled", n) for n in (1, 2, 3)] == [60, 300, 1200]


# ==========================================================================
# Behavior 3 -- marker table order and byte-identity of the other rows
# ==========================================================================
def test_b3_marker_table_order():
    assert [k for k, _ in foundry.ATTEMPT_FAILURE_MARKERS] == [
        "service", "unreachable", "stalled", "auth", "cli-error", "timeout"]
    row = foundry.ATTEMPT_FAILURE_MARKERS[1]
    assert any("could not connect to the endpoint url" in m for m in row[1])


def test_b3_other_rows_byte_identical_to_baseline():
    base = _baseline()
    now = [r for r in foundry.ATTEMPT_FAILURE_MARKERS if r[0] != "unreachable"]
    assert repr(now) == repr(list(base.ATTEMPT_FAILURE_MARKERS))


def test_b3_service_outranks_connect_phrase():
    assert foundry.classify_attempt_failure("service is busy; " + CONNECT) == "service"
    assert foundry.classify_attempt_failure(CONNECT + " service is busy") == "service"


# ==========================================================================
# Behavior 4 -- constants
# ==========================================================================
def test_b4_constants():
    assert foundry.UNREACHABLE_HOLD_KIND == "unreachable"
    assert foundry.UNREACHABLE_HOLD_SECONDS == 300
    assert foundry.UNREACHABLE_RESUME_MAX == 12
    assert foundry.AUTH_HOLD_SECONDS == 1800


# ==========================================================================
# Behavior 5 -- two holds then output
# ==========================================================================
def test_b5_two_holds_then_output_succeeds(monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path, [CONNECT, CONNECT, "ok"], write_out_on=3)
    assert d.ok is True
    assert d.out.exists() and d.out.read_text().strip()
    assert d.sleeps == [300, 300]
    assert len(d.calls) == 3
    holds = [ln for ln in d.log if UNREACH_MARK in ln]
    assert len(holds) == 2
    tails = [_tail(ln) for ln in d.log]
    assert "iter 07 · engineer unreachable resume 1/12: re-running stage after hold" in tails
    assert "iter 07 · engineer unreachable resume 2/12: re-running stage after hold" in tails
    assert not any("backing off 1 min" in ln for ln in d.log)
    assert not any("failure kind: stalled" in ln for ln in d.log)
    for n in (1, 2, 3):
        assert (d.out.parent / ("engineer.attempt%d.log" % n)).exists(), n


def test_b5_hold_line_text(monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path, [CONNECT, "ok"], write_out_on=2)
    holds = [_tail(ln) for ln in d.log if UNREACH_MARK in ln]
    assert holds == [
        "iter 07 · engineer backing off 5 min (failure kind: unreachable) -- "
        "unreachable hold: the endpoint could not be reached; re-running the "
        "same stage after the hold"]


# ==========================================================================
# Behavior 6 -- cap, monkeypatchable constants
# ==========================================================================
def test_b6_connect_every_attempt_exhausts_after_13(monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path, [CONNECT])
    assert d.ok is False and not d.out.exists()
    assert len(d.calls) == 13
    assert d.sleeps == [300] * 13
    tails = [_tail(ln) for ln in _resume(d)]
    assert tails == ["iter 07 · engineer unreachable resume %d/12: re-running "
                     "stage after hold" % i for i in range(1, 13)]


def test_b6_cap_constant_read_at_call_time(monkeypatch, tmp_path):
    monkeypatch.setattr(foundry, "UNREACHABLE_RESUME_MAX", 2)
    d = _drive(monkeypatch, tmp_path, [CONNECT])
    assert d.ok is False
    assert len(d.calls) == 3
    assert len(_resume(d)) == 2


def test_b6_hold_seconds_read_at_call_time(monkeypatch, tmp_path):
    monkeypatch.setattr(foundry, "UNREACHABLE_HOLD_SECONDS", 7)
    d = _drive(monkeypatch, tmp_path, [CONNECT])
    assert d.sleeps and set(d.sleeps) == {7}
    assert len(d.calls) == 13


# ==========================================================================
# Behavior 7 -- STOP during hold
# ==========================================================================
def test_b7_stop_during_hold_returns_immediately(monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path, [CONNECT], sleep_ret=True)
    assert d.ok is False and not d.out.exists()
    assert len(d.calls) == 1
    assert d.sleeps == [300]
    assert _resume(d) == []


# ==========================================================================
# Behavior 8 -- no human notification
# ==========================================================================
def test_b8_unreachable_hold_never_notifies_human(monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path, [CONNECT, CONNECT, "ok"], write_out_on=3)
    assert d.ok is True
    assert d.notes == []
    holds = [ln for ln in d.log if UNREACH_MARK in ln]
    assert holds and not any("re-authenticate" in ln for ln in holds)


# ==========================================================================
# Behavior 9 -- separate budget, ladder not shifted
# ==========================================================================
def test_b9_interleaved_holds_do_not_shift_the_ladder(monkeypatch, tmp_path):
    seq = [CONNECT, "Connection stalled, no data received", CONNECT, STALL, STALL, STALL]
    d = _drive(monkeypatch, tmp_path, seq)
    assert d.ok is False
    assert d.sleeps == [300, 60, 300, 300, 1200]
    assert len(d.calls) == 6
    assert len(_resume(d)) == 2


def test_b9_plain_stall_only_keeps_four_attempt_ladder(monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path, [STALL])
    assert d.ok is False
    assert d.sleeps == [60, 300, 1200]
    assert len(d.calls) == 4
    assert _resume(d) == []


# ==========================================================================
# Behavior 10 -- auth byte-identical, separate accounting
# ==========================================================================
def test_b10_auth_only_matches_baseline(monkeypatch, tmp_path):
    base = _baseline()
    d = _drive(monkeypatch, tmp_path, [AUTH], resume=1, sub="now")
    h = _drive(monkeypatch, tmp_path, [AUTH], mod=base, resume=1, sub="base")
    assert d.ok is False and h.ok is False
    assert len(d.calls) == 2 == len(h.calls)
    assert d.sleeps == [1800, 1800] == h.sleeps
    assert len(_resume(d, "auth")) == 1
    assert "iter 07 · engineer auth resume 1/1: re-running stage after hold" in [
        _tail(ln) for ln in d.log]
    assert [_tail(ln) for ln in d.log] == [_tail(ln) for ln in h.log]
    assert len(d.notes) == len(h.notes) >= 1


def test_b10_unreachable_holds_do_not_spend_auth_budget(monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path, [CONNECT, AUTH, "ok"], resume=1, write_out_on=3)
    assert d.ok is True
    assert d.sleeps == [300, 1800]
    assert len(_resume(d, "auth")) == 1 and len(_resume(d)) == 1


def test_b10_auth_after_many_unreachable_still_resumes(monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path, [CONNECT, CONNECT, CONNECT, AUTH, "ok"],
               resume=1, write_out_on=5)
    assert d.ok is True
    assert len(d.calls) == 5


# ==========================================================================
# Behavior 11 -- ladder renderer unchanged
# ==========================================================================
def test_b11_retry_ladder_lines_identical_to_baseline():
    base = _baseline()
    assert foundry.retry_ladder_lines() == base.retry_ladder_lines()
    assert "unreachable" not in " ".join(foundry.retry_ladder_lines())


# ==========================================================================
# Behavior 12 -- import + docs
# ==========================================================================
def test_b12_imports_in_fresh_interpreter():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(REPO), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("doc", ["ARCHITECTURE.md", "CONTINUOUS.md"])
def test_b12_docs_mention_the_hold(doc):
    text = (REPO / doc).read_text()
    assert "unreachable" in text
    assert "UNREACHABLE_HOLD_SECONDS" in text
