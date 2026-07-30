"""Black-box behaviour tests for iter 01 -- the `foundry doctor` preflight.

ISOLATION: these tests were written from the PM spec (Expected Behaviors 1-9)
and the product's own observable output only. The implementation source, the
engineer/reviewer notes, and `git diff` were NOT read. Every check is forced
via the documented monkeypatchable seams (`foundry.power_state`, `foundry.AGENT_BIN`,
`foundry.head_of_branch`, `shutil.which`) so the suite is fully offline and
deterministic -- no real network, power query, or binary lookup.
"""
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    """Mirror the config-writing helper used by tests/test_foundry.py."""
    data = {
        "name": "demo",
        "repo": "{FOUNDRY}/products/demo/repo",
        "allowed_push_repo": "demo",
        "vision": "{FOUNDRY}/products/demo/VISION.md",
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def cfg(tmp_path):
    return foundry.load_config(str(_write_cfg(tmp_path)))


def _raise(*a, **k):
    raise RuntimeError("boom-from-seam")


def _set_agent(monkeypatch, value):
    """Set foundry.AGENT_BIN preserving its runtime type (str vs pathlib.Path)."""
    ctor = type(foundry.AGENT_BIN)
    try:
        monkeypatch.setattr(foundry, "AGENT_BIN", ctor(value))
    except Exception:
        monkeypatch.setattr(foundry, "AGENT_BIN", str(value))


def _force_all_pass(monkeypatch, tmp_path):
    """Push every seam into a passing state."""
    monkeypatch.setattr(foundry, "power_state", lambda: "Now drawing from 'AC Power'")
    agent_stub = tmp_path / "agent_bin"
    agent_stub.write_text("#!/bin/sh\n")
    _set_agent(monkeypatch, str(agent_stub))
    monkeypatch.setattr(shutil, "which", lambda *a, **k: "/opt/homebrew/bin/uv")
    monkeypatch.setattr(foundry, "head_of_branch", lambda *a, **k: "abc1234")


class _Chk:
    """Minimal stand-in check result: doctor_ok/CLI only need .name/.ok/.detail."""
    def __init__(self, name, ok, detail="detail-text"):
        self.name = name
        self.ok = ok
        self.detail = detail


# --------------------------------------------------------------------------
# Behavior 1 -- run_doctor returns exactly 4 named results in stable order
# --------------------------------------------------------------------------
def test_b1_run_doctor_shape_and_order(cfg, tmp_path, monkeypatch):
    _force_all_pass(monkeypatch, tmp_path)
    res = foundry.run_doctor(cfg)
    assert isinstance(res, list)
    assert [c.name for c in res] == ["power", "agent", "uv", "remote"]
    for c in res:
        assert isinstance(c.name, str)
        assert isinstance(c.ok, bool)
        assert isinstance(c.detail, str) and c.detail  # non-empty
    # all-pass state -> every check ok
    assert all(c.ok for c in res)


def test_b1_run_doctor_reports_mixed_states(cfg, tmp_path, monkeypatch):
    _force_all_pass(monkeypatch, tmp_path)
    # flip remote to failing; order + shape must hold, remote must be the failure
    monkeypatch.setattr(foundry, "head_of_branch", lambda *a, **k: "?")
    res = foundry.run_doctor(cfg)
    assert [c.name for c in res] == ["power", "agent", "uv", "remote"]
    by = {c.name: c for c in res}
    assert by["power"].ok is True
    assert by["agent"].ok is True
    assert by["uv"].ok is True
    assert by["remote"].ok is False


# --------------------------------------------------------------------------
# Behavior 2 -- doctor_ok is an all-truthy predicate over checks
# --------------------------------------------------------------------------
def test_b2_doctor_ok_empty_is_true():
    assert foundry.doctor_ok([]) is True


def test_b2_doctor_ok_all_truthy():
    assert foundry.doctor_ok([_Chk("a", True), _Chk("b", True)]) is True


def test_b2_doctor_ok_any_falsy_is_false():
    assert foundry.doctor_ok([_Chk("a", True), _Chk("b", False)]) is False
    assert foundry.doctor_ok([_Chk("a", False)]) is False


def test_b2_doctor_ok_uses_truthiness():
    assert foundry.doctor_ok([_Chk("a", 1), _Chk("b", "yes")]) is True
    assert foundry.doctor_ok([_Chk("a", 0)]) is False
    assert foundry.doctor_ok([_Chk("a", "")]) is False


# --------------------------------------------------------------------------
# Behavior 3 -- check_power keys off the "AC Power" substring
# --------------------------------------------------------------------------
def test_b3_check_power_ac_ok(monkeypatch):
    monkeypatch.setattr(foundry, "power_state", lambda: "Now drawing from 'AC Power'")
    c = foundry.check_power()
    assert c.name == "power"
    assert c.ok is True
    assert isinstance(c.detail, str) and c.detail


def test_b3_check_power_battery_fail(monkeypatch):
    monkeypatch.setattr(foundry, "power_state", lambda: "Now drawing from 'Battery Power'")
    c = foundry.check_power()
    assert c.name == "power"
    assert c.ok is False


# --------------------------------------------------------------------------
# Behavior 4 -- check_agent keys off whether foundry.AGENT_BIN path exists
# --------------------------------------------------------------------------
def test_b4_check_agent_exists_ok(monkeypatch, tmp_path):
    stub = tmp_path / "agent_bin"
    stub.write_text("#!/bin/sh\n")
    _set_agent(monkeypatch, str(stub))
    c = foundry.check_agent()
    assert c.name == "agent"
    assert c.ok is True
    assert isinstance(c.detail, str) and c.detail


def test_b4_check_agent_missing_fail(monkeypatch, tmp_path):
    _set_agent(monkeypatch, str(tmp_path / "does_not_exist_here"))
    c = foundry.check_agent()
    assert c.name == "agent"
    assert c.ok is False


# --------------------------------------------------------------------------
# Behavior 5 -- check_uv keys off shutil.which("uv")
# --------------------------------------------------------------------------
def test_b5_check_uv_present_ok(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda *a, **k: "/usr/local/bin/uv")
    c = foundry.check_uv()
    assert c.name == "uv"
    assert c.ok is True
    assert isinstance(c.detail, str) and c.detail


def test_b5_check_uv_absent_fail(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda *a, **k: None)
    c = foundry.check_uv()
    assert c.name == "uv"
    assert c.ok is False


# --------------------------------------------------------------------------
# Behavior 6 -- check_remote keys off head_of_branch != "?"
# --------------------------------------------------------------------------
def test_b6_check_remote_reachable_ok(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "head_of_branch", lambda *a, **k: "deadbeef")
    c = foundry.check_remote(cfg)
    assert c.name == "remote"
    assert c.ok is True
    assert isinstance(c.detail, str) and c.detail


def test_b6_check_remote_unreachable_fail(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "head_of_branch", lambda *a, **k: "?")
    c = foundry.check_remote(cfg)
    assert c.name == "remote"
    assert c.ok is False


# --------------------------------------------------------------------------
# Behavior 7 -- every probe + run_doctor is exception-safe
# --------------------------------------------------------------------------
def test_b7_check_power_seam_raises_is_safe(monkeypatch):
    monkeypatch.setattr(foundry, "power_state", _raise)
    c = foundry.check_power()
    assert c.name == "power"
    assert c.ok is False
    assert isinstance(c.detail, str) and c.detail


def test_b7_check_uv_seam_raises_is_safe(monkeypatch):
    monkeypatch.setattr(shutil, "which", _raise)
    c = foundry.check_uv()
    assert c.name == "uv"
    assert c.ok is False
    assert isinstance(c.detail, str) and c.detail


def test_b7_check_remote_seam_raises_is_safe(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "head_of_branch", _raise)
    c = foundry.check_remote(cfg)
    assert c.name == "remote"
    assert c.ok is False
    assert isinstance(c.detail, str) and c.detail


def test_b7_check_agent_bad_value_is_safe(monkeypatch):
    class _Boom:
        def __fspath__(self):
            raise RuntimeError("bad path object")
    monkeypatch.setattr(foundry, "AGENT_BIN", _Boom())
    c = foundry.check_agent()  # must not raise
    assert c.name == "agent"
    assert c.ok is False
    assert isinstance(c.detail, str) and c.detail


def test_b7_run_doctor_all_seams_raise_still_returns_four(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "power_state", _raise)
    monkeypatch.setattr(foundry, "head_of_branch", _raise)
    monkeypatch.setattr(shutil, "which", _raise)

    class _Boom:
        def __fspath__(self):
            raise RuntimeError("bad path object")
    monkeypatch.setattr(foundry, "AGENT_BIN", _Boom())

    res = foundry.run_doctor(cfg)  # must not propagate
    assert [c.name for c in res] == ["power", "agent", "uv", "remote"]
    for c in res:
        assert c.ok is False
        assert isinstance(c.detail, str) and c.detail


# --------------------------------------------------------------------------
# Behavior 8 -- the `doctor` CLI: per-check lines + summary + exit code
# --------------------------------------------------------------------------
def test_b8_cli_all_pass_exit_zero(tmp_path, capsys, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    monkeypatch.setattr(foundry, "check_power", lambda *a, **k: _Chk("power", True))
    monkeypatch.setattr(foundry, "check_agent", lambda *a, **k: _Chk("agent", True))
    monkeypatch.setattr(foundry, "check_uv", lambda *a, **k: _Chk("uv", True))
    monkeypatch.setattr(foundry, "check_remote", lambda *a, **k: _Chk("remote", True))

    rc = foundry.main(["doctor", "--config", str(cfg_path)])
    out = capsys.readouterr().out
    assert isinstance(rc, int)
    assert rc == 0
    for name in ("power", "agent", "uv", "remote"):
        assert name in out
    assert "PASS" in out


def test_b8_cli_any_fail_exit_nonzero(tmp_path, capsys, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    monkeypatch.setattr(foundry, "check_power", lambda *a, **k: _Chk("power", True))
    monkeypatch.setattr(foundry, "check_agent", lambda *a, **k: _Chk("agent", True))
    monkeypatch.setattr(foundry, "check_uv", lambda *a, **k: _Chk("uv", True))
    monkeypatch.setattr(foundry, "check_remote", lambda *a, **k: _Chk("remote", False))

    rc = foundry.main(["doctor", "--config", str(cfg_path)])
    out = capsys.readouterr().out
    assert isinstance(rc, int)
    assert rc != 0
    for name in ("power", "agent", "uv", "remote"):
        assert name in out
    assert "FAIL" in out


# --------------------------------------------------------------------------
# Behavior 9 -- doctor is strictly additive: run/once still exposed by the CLI
# (black-box: driving the product's own --help output, which the isolation
#  contract explicitly permits)
# --------------------------------------------------------------------------
def test_b9_cli_help_lists_run_once_and_doctor():
    foundry_py = pathlib.Path(foundry.__file__).resolve()
    proc = subprocess.run(
        [sys.executable, str(foundry_py), "--help"],
        capture_output=True, text=True, cwd=str(foundry_py.parent),
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    for sub in ("run", "once", "doctor"):
        assert sub in combined, f"subcommand {sub!r} missing from --help:\n{combined}"
