"""Iteration 553 (OPERATOR 2026-11-21b bite 2) -- BLACK-BOX behavior tests: `foundry preship`
sizes its clean-clone budget per product with the iter-552 sizer (`preship_budget`), passes
`budget=` to `verify_local_clone` ONLY when the sized value beats the floor, and
roles/final.md cites the live STAGE_TIMEOUT and says preship is never skipped for stage time.

Spec under test: products/_platform/state/iter-553/pm.md, Expected Behaviors 1-10.

ISOLATION HONORED: written from `pm.md`, the repo's own `tests/` conventions (chiefly
tests/test_iter550/552/525_behavior.py's scripted-seam harnesses) and the product's RUNTIME
surface (public names, signatures, CLI stdout) ONLY.  No implementation source, no engineer
/ reviewer note and no `git diff` output was read.  The HEAD-comparison arms import the HEAD
revision of foundry.py as a second module and compare RUNTIME outputs only.

OFFLINE: every external effect goes through scripted `run_cmd` / `cleanup_clone` /
`_monotonic` / `verify_local_clone` / `rerun_suite_at_parent` stand-ins set by BARE module
name, with `subprocess.run` / `Popen` tripwired inside the offline arms.  The only real
subprocesses are the gated HEAD-revision reads.

FRESH-CLONE SAFE: every fixture lives under `tmp_path`; nothing asserts on gitignored state,
a commit sha or a line number.  HEAD-baseline arms SKIP once HEAD's roadmap index or archive
carries iter 553.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import math
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

SHA = "c" * 40
PARENT = "d" * 40
_REV = "HEAD" + ":"


# ==========================================================================
# helpers
# ==========================================================================
def _head_text(rel):
    try:
        proc = subprocess.run(["git", "-C", str(_ROOT), "show", _REV + rel],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def _pre_ship_scope_live():
    idx = _head_text("PLATFORM_ROADMAP.md")
    arc = _head_text("PLATFORM_ROADMAP_ARCHIVE.md")
    if not idx and not arc:
        return False
    return "- iter 553 " not in idx and "- **iter 553 " not in arc


@pytest.fixture(scope="module")
def head_foundry(tmp_path_factory):
    if not _pre_ship_scope_live():
        pytest.skip("iter 553 already shipped (or no git history); HEAD is no longer the "
                    "pre-change baseline")
    src = _head_text("foundry.py")
    if not src.strip():
        pytest.skip("no git history (archive copy?)")
    d = tmp_path_factory.mktemp("head_foundry_553")
    path = d / "foundry_head_iter553.py"
    path.write_text(src, encoding="utf-8")
    name = "foundry_head_iter553"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    yield mod
    sys.modules.pop(name, None)


def _no_real_subprocess(*a, **k):  # pragma: no cover - tripwire
    raise AssertionError("real subprocess call during an offline behavior: %r" % (a,))


def _cfg(tmp_path, sub="p"):
    base = tmp_path / sub
    repo = base / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    work = base / "work"
    (work / "state").mkdir(parents=True, exist_ok=True)
    return foundry.ProductConfig(name="demo", repo=str(repo), allowed_push_repo="demo",
                                 work_root=str(work), test_cmd="uv run pytest -q",
                                 setup_cmd="uv sync")


def _write_postrelease(cfg, iteration, seconds):
    d = pathlib.Path(cfg.state) / ("iter-%02d" % iteration)
    d.mkdir(parents=True, exist_ok=True)
    (d / "postrelease.md").write_text(
        "post-release verification report\n\n"
        "- suite_seconds: %.2f\n"
        "POSTRELEASE: HEALTHY\n" % seconds)


def _sized_cfg(tmp_path, values=(99.0, 274.0, 150.0), sub="sized"):
    cfg = _cfg(tmp_path, sub)
    for i, s in enumerate(values, start=1):
        _write_postrelease(cfg, i, s)
    return cfg


def _generic_run_cmd(calls, mod=None):
    mod = mod or foundry

    def fake_run_cmd(args, cwd=None, timeout=None, **kw):
        argv = [str(a) for a in args]
        calls.append({"argv": argv, "cwd": cwd, "timeout": timeout})
        if "rev-parse" in argv and any(a.endswith("^") for a in argv):
            return mod.CmdResult(True, PARENT + "\n")
        if "rev-parse" in argv:
            return mod.CmdResult(True, SHA + "\n")
        if "--porcelain" in argv or "--shortstat" in argv:
            return mod.CmdResult(True, "")
        return mod.CmdResult(True, "ok\n3 passed in 0.1s\n")

    return fake_run_cmd


def _install_offline(monkeypatch, mod=None, clock=None):
    mod = mod or foundry
    calls = []
    monkeypatch.setattr(mod, "run_cmd", _generic_run_cmd(calls, mod))
    monkeypatch.setattr(mod, "cleanup_clone", lambda *a, **k: None)
    if hasattr(mod, "_try_cleanup_clone"):
        monkeypatch.setattr(mod, "_try_cleanup_clone", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_monotonic", clock or (lambda: 0.0))
    monkeypatch.setattr(mod, "rerun_suite_at_parent",
                        lambda cfg, parent_sha, clone_dir: (None, "/usr/bin/python3"))
    monkeypatch.setattr(subprocess, "run", _no_real_subprocess)
    monkeypatch.setattr(subprocess, "Popen", _no_real_subprocess)
    return calls


class _Spy:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, *a, **k):
        self.calls.append((a, dict(k)))
        return self.result


def _run_cli(mod, cfg, as_json=False):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.preship_cli(cfg, as_json=as_json)
    return rc, buf.getvalue()


def _results(mod):
    """One PreshipResult per verdict family, built in `mod`."""
    return {
        "verified": mod.PreshipResult(True, False, "clean clone verified", 3.0,
                                      suite_output="3 passed in 0.1s\n", verified_sha=SHA),
        "incomplete": mod.PreshipResult(False, True, "budget exhausted; no verdict", 0.0,
                                        suite_output="", verified_sha=""),
        "broken": mod.PreshipResult(False, False, mod.PRESHIP_SUITE_FAILED_DETAIL, 4.0,
                                    suite_output="FAILED tests/test_a.py::test_x - boom\n"
                                                 "1 failed in 0.2s\n",
                                    verified_sha=SHA),
    }


# ==========================================================================
# EB1 -- preship_budget: degenerate input -> None, never raises
# ==========================================================================
@pytest.mark.parametrize("x", [(), None, "junk", [float("nan"), -1, True], [], [0.0],
                               object(), [float("inf")]])
def test_eb1_degenerate_inputs_return_none(x):
    assert foundry.preship_budget(x) is None


# ==========================================================================
# EB2 -- sized values, floor -> None, ceiling, == commit_check_budget
# ==========================================================================
def test_eb2_named_values():
    assert foundry.preship_budget([200.0, 241.0]) == 362.0
    assert foundry.preship_budget([200.0, 241.0]) == float(math.ceil(1.25 * 241 + 60))
    assert foundry.preship_budget([100.0]) is None
    assert foundry.preship_budget([99, 274]) == 403.0
    assert foundry.preship_budget([531.0]) == 480.0
    assert isinstance(foundry.preship_budget([99, 274]), float)


@pytest.mark.parametrize("x", [(), None, "junk", [float("nan"), -1, True], [100.0], [144.0],
                               [144.01], [145.0], [200.0, 241.0], [99, 274], [531.0],
                               [10.0] * 20, [1e9], [300.0, 1.0, 2.0]])
def test_eb2_none_or_equal_to_commit_check_budget(x):
    got = foundry.preship_budget(x)
    assert got is None or got == foundry.commit_check_budget(x)
    if got is not None:
        assert got > float(foundry.COMMIT_CHECK_BUDGET_SECONDS)


def test_eb2_floor_boundary():
    # ceil(1.25*144+60) == 240 == floor -> None; just above -> sized
    assert foundry.preship_budget([144.0]) is None
    assert foundry.preship_budget([145.0]) == float(math.ceil(1.25 * 145 + 60)) == 242.0


# ==========================================================================
# EB3 -- knobs read at call time
# ==========================================================================
def test_eb3_ceiling_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "COMMIT_CHECK_BUDGET_CEILING_SECONDS", 300.0)
    assert foundry.preship_budget([531.0]) == 300.0


def test_eb3_floor_read_at_call_time(monkeypatch):
    assert foundry.preship_budget([200.0, 241.0]) == 362.0
    monkeypatch.setattr(foundry, "COMMIT_CHECK_BUDGET_SECONDS", 400.0)
    assert foundry.preship_budget([200.0, 241.0]) is None


def test_eb3_preship_budget_never_raises_when_sizer_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("sizer boom 553")

    monkeypatch.setattr(foundry, "commit_check_budget", boom)
    assert foundry.preship_budget([531.0]) is None


# ==========================================================================
# EB4 -- verify_local_clone budget plumbing
# ==========================================================================
def test_eb4_signature_has_optional_budget():
    import inspect
    sig = inspect.signature(foundry.verify_local_clone)
    assert list(sig.parameters)[:3] == ["cfg", "expected_sha", "clone_dir"]
    assert sig.parameters["budget"].default is None


def test_eb4_no_budget_uses_global_at_call_time(monkeypatch, tmp_path):
    calls = _install_offline(monkeypatch)
    monkeypatch.setattr(foundry, "PRESHIP_BUDGET_SECONDS", 12.0)
    foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "clone")
    assert calls, "no step issued"
    assert calls[0]["argv"][:2] == ["git", "clone"]
    assert calls[0]["timeout"] == foundry.preship_step_timeout(12.0)


def test_eb4_numeric_budget_replaces_global(monkeypatch, tmp_path):
    calls = _install_offline(monkeypatch)
    monkeypatch.setattr(foundry, "PRESHIP_BUDGET_SECONDS", 12.0)
    res = foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "clone", budget=500.0)
    assert calls[0]["argv"][:2] == ["git", "clone"]
    assert calls[0]["timeout"] == foundry.preship_step_timeout(500.0)
    assert calls[0]["timeout"] != foundry.preship_step_timeout(12.0)
    assert res.verified is True, res.detail


def test_eb4_budget_none_explicit_equals_omitted(monkeypatch, tmp_path):
    calls = _install_offline(monkeypatch)
    monkeypatch.setattr(foundry, "PRESHIP_BUDGET_SECONDS", 12.0)
    a = foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "clone")
    first = [(c["argv"], c["timeout"]) for c in calls]
    calls.clear()
    b = foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "clone", budget=None)
    assert [(c["argv"], c["timeout"]) for c in calls] == first
    assert (a.verified, a.incomplete, a.detail, a.exit_code) == (
        b.verified, b.incomplete, b.detail, b.exit_code)


def test_eb4_step_argv_unchanged_by_budget(monkeypatch, tmp_path):
    calls = _install_offline(monkeypatch)
    foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "clone")
    plain = [c["argv"] for c in calls]
    calls.clear()
    foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "clone", budget=403.0)
    assert [c["argv"] for c in calls] == plain
    assert len(plain) == 4


# ==========================================================================
# EB5 -- budget exhaustion detail
# ==========================================================================
def _jump_clock(after):
    state = {"n": 0}

    def clock():
        state["n"] += 1
        return 0.0 if state["n"] == 1 else after

    return clock


def test_eb5_sized_exhaustion_names_sized_budget(monkeypatch, tmp_path):
    calls = _install_offline(monkeypatch, clock=_jump_clock(10_000.0))
    res = foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "clone", budget=403.0)
    assert res.exit_code == 2
    assert res.incomplete is True and res.verified is False
    assert "403.0" in res.detail
    assert "PRESHIP_BUDGET_SECONDS=" not in res.detail
    assert calls == []


def test_eb5_default_exhaustion_names_global(monkeypatch, tmp_path):
    _install_offline(monkeypatch, clock=_jump_clock(10_000.0))
    monkeypatch.setattr(foundry, "PRESHIP_BUDGET_SECONDS", 12.0)
    res = foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "clone")
    assert res.exit_code == 2
    assert "PRESHIP_BUDGET_SECONDS=" in res.detail
    assert "12" in res.detail


def test_eb5_default_exhaustion_detail_byte_identical_to_head(monkeypatch, tmp_path,
                                                              head_foundry):
    _install_offline(monkeypatch, clock=_jump_clock(10_000.0))
    _install_offline(monkeypatch, mod=head_foundry, clock=_jump_clock(10_000.0))
    cfg = _cfg(tmp_path)
    new = foundry.verify_local_clone(cfg, SHA, tmp_path / "clone")
    hcfg = head_foundry.ProductConfig(name=cfg.name, repo=cfg.repo,
                                      allowed_push_repo=cfg.allowed_push_repo,
                                      work_root=cfg.work_root, test_cmd=cfg.test_cmd,
                                      setup_cmd=cfg.setup_cmd)
    old = head_foundry.verify_local_clone(hcfg, SHA, tmp_path / "clone")
    assert new.detail == old.detail
    assert (new.exit_code, new.verified, new.incomplete) == (
        old.exit_code, old.verified, old.incomplete)


# ==========================================================================
# EB6-EB8 -- preship_cli wiring
# ==========================================================================
def test_eb6_sized_history_passes_budget_keyword(monkeypatch, tmp_path):
    cfg = _sized_cfg(tmp_path)
    assert foundry.gather_timing(cfg).measured_seconds  # the fixture is measured
    _install_offline(monkeypatch)
    spy = _Spy(_results(foundry)["verified"])
    monkeypatch.setattr(foundry, "verify_local_clone", spy)
    rc, out = _run_cli(foundry, cfg)
    assert rc == 0, out
    assert len(spy.calls) == 1
    a, k = spy.calls[0]
    assert (len(a), k) == (3, {"budget": 403.0})
    assert a[1] == SHA


@pytest.mark.parametrize("values", [(), (144.0,), (100.0, 144.0, 20.0)])
def test_eb7_floor_or_no_history_passes_no_keyword(monkeypatch, tmp_path, values):
    cfg = _sized_cfg(tmp_path, values=values, sub="floor")
    _install_offline(monkeypatch)
    spy = _Spy(_results(foundry)["verified"])
    monkeypatch.setattr(foundry, "verify_local_clone", spy)
    rc, out = _run_cli(foundry, cfg)
    assert rc == 0, out
    assert len(spy.calls) == 1
    a, k = spy.calls[0]
    assert (len(a), k) == (3, {})
    assert a[1] == SHA


def test_eb7_positional_only_fake_still_works(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path)
    _install_offline(monkeypatch)
    base = _results(foundry)["verified"]
    monkeypatch.setattr(foundry, "verify_local_clone", lambda c, s, d: base)
    rc, out = _run_cli(foundry, cfg)
    assert rc == 0, out
    assert _nonempty(out)[-1] == "PRESHIP: VERIFIED"


@pytest.mark.parametrize("kind,want_rc", [("verified", 0), ("incomplete", 2)])
def test_eb8_gather_timing_raise_falls_back(monkeypatch, tmp_path, kind, want_rc):
    cfg = _sized_cfg(tmp_path)
    _install_offline(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("gather boom 553")

    monkeypatch.setattr(foundry, "gather_timing", boom)
    spy = _Spy(_results(foundry)[kind])
    monkeypatch.setattr(foundry, "verify_local_clone", spy)
    rc, out = _run_cli(foundry, cfg)
    assert rc == want_rc, out
    assert len(spy.calls) == 1
    a, k = spy.calls[0]
    assert (len(a), k) == (3, {})


# ==========================================================================
# EB9 -- CLI output unchanged for every verdict
# ==========================================================================
def _nonempty(text):
    return [ln for ln in text.splitlines() if ln.strip()]


@pytest.mark.parametrize("kind,want_rc,sentinel", [
    ("verified", 0, "PRESHIP: VERIFIED"),
    ("incomplete", 2, "PRESHIP: INCOMPLETE"),
    ("broken", 1, "PRESHIP: BROKEN"),
])
@pytest.mark.parametrize("as_json", [False, True])
def test_eb9_sized_and_floor_output_identical(monkeypatch, tmp_path, kind, want_rc,
                                              sentinel, as_json):
    _install_offline(monkeypatch)
    res = _results(foundry)[kind]
    outs = []
    for cfg in (_sized_cfg(tmp_path), _cfg(tmp_path, "floor")):
        spy = _Spy(res)
        monkeypatch.setattr(foundry, "verify_local_clone", spy)
        rc, out = _run_cli(foundry, cfg, as_json=as_json)
        assert rc == want_rc, out
        outs.append(out.replace(str(cfg.work_root), "<WR>").replace(str(cfg.repo), "<R>"))
    assert outs[0] == outs[1]
    if as_json:
        doc = json.loads(outs[0])
        assert doc["sentinel"] == sentinel and doc["exit_code"] == want_rc
    else:
        assert _nonempty(outs[0])[-1] == sentinel


@pytest.mark.parametrize("kind", ["verified", "incomplete", "broken"])
@pytest.mark.parametrize("as_json", [False, True])
def test_eb9_cli_output_byte_identical_to_head(monkeypatch, tmp_path, head_foundry, kind,
                                               as_json):
    _install_offline(monkeypatch)
    _install_offline(monkeypatch, mod=head_foundry)
    new_cfg = _sized_cfg(tmp_path)
    old_cfg = head_foundry.ProductConfig(name=new_cfg.name, repo=new_cfg.repo,
                                         allowed_push_repo=new_cfg.allowed_push_repo,
                                         work_root=new_cfg.work_root,
                                         test_cmd=new_cfg.test_cmd,
                                         setup_cmd=new_cfg.setup_cmd)
    new_spy = _Spy(_results(foundry)[kind])
    old_res = _results(head_foundry)[kind]
    monkeypatch.setattr(foundry, "verify_local_clone", new_spy)
    monkeypatch.setattr(head_foundry, "verify_local_clone", lambda c, s, d: old_res)
    rc_new, out_new = _run_cli(foundry, new_cfg, as_json=as_json)
    rc_old, out_old = _run_cli(head_foundry, old_cfg, as_json=as_json)
    assert rc_new == rc_old
    assert out_new == out_old
    if as_json:
        assert list(json.loads(out_new)) == list(json.loads(out_old))
    assert new_spy.calls[0][1] == {"budget": 403.0}


# ==========================================================================
# EB10 -- roles/final.md edits; no other card touched
# ==========================================================================
def _final_text():
    return (_ROOT / "roles" / "final.md").read_text(encoding="utf-8")


def test_eb10_final_card_cites_stage_timeout():
    text = _final_text()
    assert "STAGE_TIMEOUT (%d s)" % foundry.STAGE_TIMEOUT in text
    assert "STAGE_TIMEOUT (1800 s)" in text
    assert "never skip it for stage time" in text
    assert "~600s" not in text


def test_eb10_other_cards_byte_unchanged_vs_head():
    if not _pre_ship_scope_live():
        pytest.skip("iter 553 already shipped (or no git history)")
    cards = sorted(p for p in (_ROOT / "roles").glob("*.md") if p.name != "final.md")
    assert cards
    for p in cards:
        head = _head_text("roles/" + p.name)
        if not head:
            continue  # untracked card: not this bite's concern
        assert p.read_text(encoding="utf-8") == head, p.name
    assert _final_text() != _head_text("roles/final.md")
