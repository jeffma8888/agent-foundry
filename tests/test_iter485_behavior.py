"""Iteration 485 -- BLACK-BOX behavior tests for the launch.sh preflight fix.

`_preflight_dispatch` accepts both dispatcher configs (containing `work_items`)
and product configs, so `launch.sh`'s documented path no longer crashes with
`ConfigKeyError`.

Expected Behaviors (from pm.md):
  1. Dispatcher config runs to completion without ConfigKeyError.
  2. Dispatcher config path still runs the single-brain scan.
  3. Product config path unchanged (no regression).
  4. Product config --json produces the same structure as before.
  5. No enabled work items → doctor FAIL, exit 1 (NO-GO), not a crash.
  6. {FOUNDRY} placeholder is resolved before load_config.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-485 PM spec's Expected
Behaviors, the conventions of tests/ (test_iter484_behavior.py, test_iter28_behavior.py),
and the product's OBSERVABLE surface -- importing the module and CALLING the public
functions. The implementation source of foundry.py / dispatcher.py, the
engineer's notes (engineer.md), the reviewer's notes (reviewer.md),
IMPLEMENTATION.patch and git diff were NOT read.

Offline and deterministic: every fixture is built in tmp_path, the real foundry
repo is never mutated, and the only subprocess is the fresh-interpreter import
probe.
"""
from __future__ import annotations

import io
import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

THIS_ITER = 485

DISPATCHER_CFG = str(_ROOT / "foundry.config.example.json")
PRODUCT_CFG = str(_ROOT / "products" / "_platform" / "config.json")


def _capture(fn):
    buf = io.StringIO()
    old_out = sys.stdout
    sys.stdout = buf
    try:
        rc = fn()
    finally:
        sys.stdout = old_out
    return rc, buf.getvalue()


def _set_doctor(monkeypatch, checks):
    monkeypatch.setattr(foundry, "run_doctor", lambda cfg: list(checks))


def _set_scan(monkeypatch, ret=(), exc=None):
    def fake(pattern="dispatcher.py"):
        if exc:
            raise exc
        return ret
    monkeypatch.setattr(foundry, "running_dispatchers", fake)


def _good_checks():
    return (
        foundry.Check("agent", True, "ok"),
        foundry.Check("uv", True, "ok"),
        foundry.Check("remote", True, "ok"),
    )


def _fail_checks():
    return (
        foundry.Check("doctor", False, "no product to probe"),
    )


# ==========================================================================
# Behavior 1 -- dispatcher config runs without ConfigKeyError
# ==========================================================================
def test_b1_dispatcher_config_no_crash(monkeypatch):
    _set_doctor(monkeypatch, _good_checks())
    _set_scan(monkeypatch, ret=())
    rc, out = _capture(lambda: foundry._preflight_dispatch(DISPATCHER_CFG))
    assert isinstance(rc, int), f"exit code must be int, got {type(rc).__name__}"
    assert rc in (0, 1, 2), f"exit code must be 0/1/2, got {rc}"


def test_b1_dispatcher_config_no_configkeyerror(monkeypatch):
    _set_doctor(monkeypatch, _good_checks())
    _set_scan(monkeypatch, ret=())
    try:
        foundry._preflight_dispatch(DISPATCHER_CFG)
    except Exception as e:
        cls = type(e).__name__
        assert "ConfigKeyError" not in cls, f"must not raise ConfigKeyError, got {cls}: {e}"
        assert "unknown key" not in str(e).lower(), f"must not raise unknown-key error: {e}"


def test_b1_dispatcher_config_exit_0_when_all_green(monkeypatch):
    _set_doctor(monkeypatch, _good_checks())
    _set_scan(monkeypatch, ret=())
    rc, _ = _capture(lambda: foundry._preflight_dispatch(DISPATCHER_CFG))
    assert rc == 0, f"all checks pass + no brain conflict → exit 0, got {rc}"


# ==========================================================================
# Behavior 2 -- dispatcher config path still runs the single-brain scan
# ==========================================================================
def test_b2_dispatcher_config_runs_brain_scan(monkeypatch):
    _set_doctor(monkeypatch, _good_checks())
    scan_called = []
    def fake_scan(pattern="dispatcher.py"):
        scan_called.append(pattern)
        return ()
    monkeypatch.setattr(foundry, "running_dispatchers", fake_scan)
    _capture(lambda: foundry._preflight_dispatch(DISPATCHER_CFG))
    assert len(scan_called) >= 1, "brain scan must be called for dispatcher config"


def test_b2_brain_conflict_shows_in_output(monkeypatch):
    _set_doctor(monkeypatch, _good_checks())
    _set_scan(monkeypatch, ret=(12345,))
    rc, out = _capture(lambda: foundry._preflight_dispatch(DISPATCHER_CFG))
    assert rc == 1, f"brain conflict should yield exit 1, got {rc}"
    assert "CONFLICT" in out.upper() or "conflict" in out.lower() or "single-brain" in out.lower(), \
        f"brain conflict must appear in output, got: {out[:200]}"


# ==========================================================================
# Behavior 3 -- product config path unchanged (no regression)
# ==========================================================================
def test_b3_product_config_no_crash(monkeypatch):
    _set_doctor(monkeypatch, _good_checks())
    _set_scan(monkeypatch, ret=())
    rc, out = _capture(lambda: foundry._preflight_dispatch(PRODUCT_CFG))
    assert isinstance(rc, int)
    assert rc in (0, 1, 2), f"product config exit code must be 0/1/2, got {rc}"


def test_b3_product_config_exit_0_when_green(monkeypatch):
    _set_doctor(monkeypatch, _good_checks())
    _set_scan(monkeypatch, ret=())
    rc, _ = _capture(lambda: foundry._preflight_dispatch(PRODUCT_CFG))
    assert rc == 0, f"product config + all green → exit 0, got {rc}"


def test_b3_product_config_exit_1_when_check_fails(monkeypatch):
    _set_doctor(monkeypatch, (
        foundry.Check("agent", False, "missing"),
        foundry.Check("uv", True, "ok"),
    ))
    _set_scan(monkeypatch, ret=())
    rc, _ = _capture(lambda: foundry._preflight_dispatch(PRODUCT_CFG))
    assert rc == 1, f"product config + failing check → exit 1, got {rc}"


# ==========================================================================
# Behavior 4 -- product config --json produces the same structure
# ==========================================================================
def test_b4_product_config_json_structure(monkeypatch):
    _set_doctor(monkeypatch, _good_checks())
    _set_scan(monkeypatch, ret=())
    rc, out = _capture(lambda: foundry._preflight_dispatch(PRODUCT_CFG, as_json=True))
    data = json.loads(out)
    for key in ("brain", "checks", "env_ready", "exit_code", "verdict"):
        assert key in data, f"JSON must contain '{key}', got keys: {list(data.keys())}"
    assert isinstance(data["exit_code"], int)
    assert isinstance(data["checks"], list)


def test_b4_dispatcher_config_json_structure(monkeypatch):
    _set_doctor(monkeypatch, _good_checks())
    _set_scan(monkeypatch, ret=())
    rc, out = _capture(lambda: foundry._preflight_dispatch(DISPATCHER_CFG, as_json=True))
    data = json.loads(out)
    for key in ("brain", "checks", "env_ready", "exit_code", "verdict"):
        assert key in data, f"JSON must contain '{key}', got keys: {list(data.keys())}"


def test_b4_json_exit_code_matches_return(monkeypatch):
    _set_doctor(monkeypatch, _good_checks())
    _set_scan(monkeypatch, ret=())
    rc, out = _capture(lambda: foundry._preflight_dispatch(PRODUCT_CFG, as_json=True))
    data = json.loads(out)
    assert data["exit_code"] == rc, f"JSON exit_code ({data['exit_code']}) != return ({rc})"


# ==========================================================================
# Behavior 5 -- no enabled work items → doctor FAIL, exit 1, not crash
# ==========================================================================
def test_b5_no_enabled_items_no_crash(tmp_path, monkeypatch):
    cfg = tmp_path / "disabled.json"
    cfg.write_text(json.dumps({
        "work_items": [
            {"name": "x", "config": "/fake/path.json", "priority": 0, "enabled": False},
        ]
    }))
    _set_scan(monkeypatch, ret=())
    rc, out = _capture(lambda: foundry._preflight_dispatch(str(cfg)))
    assert isinstance(rc, int), f"must return int, got {type(rc).__name__}"
    assert rc == 1, f"no enabled items → exit 1 (NO-GO), got {rc}"


def test_b5_no_enabled_items_shows_nogo(tmp_path, monkeypatch):
    cfg = tmp_path / "disabled2.json"
    cfg.write_text(json.dumps({
        "work_items": [
            {"name": "x", "config": "/fake/path.json", "priority": 0, "enabled": False},
        ]
    }))
    _set_scan(monkeypatch, ret=())
    rc, out = _capture(lambda: foundry._preflight_dispatch(str(cfg)))
    assert "NO-GO" in out.upper() or "no-go" in out.lower(), \
        f"no enabled items must show NO-GO, got: {out[:300]}"


def test_b5_empty_work_items_no_crash(tmp_path, monkeypatch):
    cfg = tmp_path / "empty.json"
    cfg.write_text(json.dumps({"work_items": []}))
    _set_scan(monkeypatch, ret=())
    rc, out = _capture(lambda: foundry._preflight_dispatch(str(cfg)))
    assert rc == 1, f"empty work_items → exit 1, got {rc}"


# ==========================================================================
# Behavior 6 -- {FOUNDRY} placeholder resolved before load_config
# ==========================================================================
def test_b6_foundry_placeholder_resolved(tmp_path, monkeypatch):
    product_cfg_path = tmp_path / "product.json"
    product_cfg_path.write_text("{}")
    dispatcher_cfg = tmp_path / "dispatch.json"
    dispatcher_cfg.write_text(json.dumps({
        "work_items": [
            {
                "name": "test_prod",
                "config": str(product_cfg_path),
                "priority": 0,
                "enabled": True,
            }
        ]
    }))
    fake_cfg = foundry.ProductConfig(
        name="test_prod", repo=str(tmp_path), allowed_push_repo="test",
    )
    loaded_paths = []
    orig_load = foundry.load_config
    def fake_load(path):
        loaded_paths.append(path)
        return fake_cfg
    monkeypatch.setattr(foundry, "load_config", fake_load)
    _set_doctor(monkeypatch, _good_checks())
    _set_scan(monkeypatch, ret=())
    rc, out = _capture(lambda: foundry._preflight_dispatch(str(dispatcher_cfg)))
    assert isinstance(rc, int), f"must return int, got {type(rc).__name__}"
    assert rc in (0, 1, 2), f"valid exit code expected, got {rc}"
    assert len(loaded_paths) == 1, f"load_config called {len(loaded_paths)} times"
    assert loaded_paths[0] == str(product_cfg_path), (
        f"load_config received {loaded_paths[0]!r}, expected {str(product_cfg_path)!r} — "
        f"{{FOUNDRY}} placeholder must be resolved before load_config is called"
    )


def test_b6_foundry_token_in_config_path(tmp_path, monkeypatch):
    dispatcher_cfg = tmp_path / "dispatch_token.json"
    dispatcher_cfg.write_text(json.dumps({
        "work_items": [
            {
                "name": "token_test",
                "config": "{FOUNDRY}/products/_platform/config.json",
                "priority": 0,
                "enabled": True,
            }
        ]
    }))
    loaded_paths = []
    fake_cfg = foundry.ProductConfig(
        name="token_test", repo=str(tmp_path), allowed_push_repo="test",
    )
    def fake_load(path):
        loaded_paths.append(path)
        return fake_cfg
    monkeypatch.setattr(foundry, "load_config", fake_load)
    _set_doctor(monkeypatch, _good_checks())
    _set_scan(monkeypatch, ret=())
    rc, _ = _capture(lambda: foundry._preflight_dispatch(str(dispatcher_cfg)))
    assert rc in (0, 1, 2), f"must resolve {{FOUNDRY}} token without error, got exit {rc}"
    assert len(loaded_paths) == 1
    expected = str(foundry.FOUNDRY / "products" / "_platform" / "config.json")
    assert loaded_paths[0] == expected, (
        f"{{FOUNDRY}} not resolved: load_config got {loaded_paths[0]!r}, "
        f"expected {expected!r}"
    )


# ==========================================================================
# Structural guards
# ==========================================================================
def test_structural_dispatch_roster_key():
    assert foundry.DISPATCH_ROSTER_KEY == "work_items"


def test_structural_preflight_dispatch_exists():
    assert callable(foundry._preflight_dispatch)


def test_structural_preflight_dispatch_signature():
    import inspect
    sig = inspect.signature(foundry._preflight_dispatch)
    params = list(sig.parameters.keys())
    assert "config_path" in params, f"must accept config_path, got {params}"


def test_structural_import_probe():
    result = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"import probe failed: {result.stderr[:300]}"
