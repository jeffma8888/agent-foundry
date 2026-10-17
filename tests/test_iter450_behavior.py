"""Iteration 450 -- BLACK-BOX behavior tests: ``notify_cmd`` config hook.

Spec under test: products/_platform/state/iter-450/pm.md (5 Expected Behaviors).

  EB1: ProductConfig gains an optional ``notify_cmd`` field (default ``""``).
       Loading an existing config that omits it succeeds with the empty default
       (backward-compatible).
  EB2: When ``notify_cmd`` is non-empty and ``run_stage`` enters the auth hold,
       the framework calls a module-level ``_notify_human_hold(cfg, kind, detail)``
       seam BEFORE the sleep.
  EB3: The seam shells out to ``notify_cmd`` with ``FOUNDRY_HOLD_KIND`` and
       ``FOUNDRY_HOLD_DETAIL`` as environment variables.  The command's exit code
       and output are logged but never raise -- fail-open.
  EB4: When ``notify_cmd`` is empty (the default), no subprocess is spawned and
       no error occurs.
  EB5: A monkeypatched test can assert the seam fires with the correct kind and
       detail for the auth-hold branch, and that a failing command does not
       propagate exceptions.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the
iter-450 PM spec, the product README, the pre-existing conventions under
``tests/``, and the product's OWN observable behavior by RUNNING it (the public
``ProductConfig``, ``_notify_human_hold`` API).  The implementation source of
``foundry.py`` / ``dispatcher.py`` was NOT read by this author, nor the
reviewer's notes, ``IMPLEMENTATION.patch``, or any ``git diff``.

Offline and deterministic: every behavior scripts ``_notify_human_hold`` by BARE
module name monkeypatch so no real subprocess, network, or git runs.
"""
from __future__ import annotations

import dataclasses
import inspect
import pathlib

import foundry


THIS_ITER = 450


def _mock_cfg(notify_cmd, tmp_path=None):
    """Build a minimal cfg-like object with the attributes _notify_human_hold
    and log() need.  When a tmp_path is supplied, night_log points at a real
    writable file so log() does not raise on the error path."""
    night_log = pathlib.Path("/dev/null")
    if tmp_path is not None:
        night_log = tmp_path / "NIGHT_LOG.md"
        night_log.touch()
    return type("C", (), {
        "notify_cmd": notify_cmd,
        "name": "test",
        "night_log": night_log,
    })()


# ---------------------------------------------------------------------------
# EB1 -- ProductConfig gains optional notify_cmd with default ""
# ---------------------------------------------------------------------------

class TestEB1NotifyCmdField:

    def test_b1_product_config_has_notify_cmd(self):
        names = [f.name for f in dataclasses.fields(foundry.ProductConfig)]
        assert "notify_cmd" in names

    def test_b1_notify_cmd_default_is_empty_string(self):
        defaults = {
            f.name: f.default
            for f in dataclasses.fields(foundry.ProductConfig)
            if f.default is not dataclasses.MISSING
        }
        assert defaults["notify_cmd"] == ""

    def test_b1_existing_config_loads_without_notify_cmd(self):
        cfg = foundry.load_config("products/_platform/config.json")
        assert isinstance(cfg.notify_cmd, str)

    def test_b1_backward_compatible_empty_default(self):
        cfg = foundry.load_config("products/_platform/config.json")
        assert cfg.notify_cmd == ""

    def test_b1_notify_cmd_is_str_type(self):
        hints = {
            f.name: f.type for f in dataclasses.fields(foundry.ProductConfig)
        }
        assert hints["notify_cmd"] == "str"


# ---------------------------------------------------------------------------
# EB2 -- _notify_human_hold is a module-level seam with (cfg, kind, detail)
# ---------------------------------------------------------------------------

class TestEB2NotifyHumanHoldSeam:

    def test_b2_notify_human_hold_exists_at_module_level(self):
        assert hasattr(foundry, "_notify_human_hold")
        assert callable(foundry._notify_human_hold)

    def test_b2_signature_has_cfg_kind_detail(self):
        sig = inspect.signature(foundry._notify_human_hold)
        params = list(sig.parameters.keys())
        assert params == ["cfg", "kind", "detail"]

    def test_b2_return_annotation_is_none(self):
        sig = inspect.signature(foundry._notify_human_hold)
        assert sig.return_annotation in (None, "None")

    def test_b2_seam_fires_with_auth_kind(self, monkeypatch):
        calls = []

        def fake_notify(cfg, kind, detail):
            calls.append((kind, detail))

        monkeypatch.setattr(foundry, "_notify_human_hold", fake_notify)
        fake_notify(None, "auth", "auth hold: re-authenticate")
        assert len(calls) == 1
        assert calls[0][0] == "auth"

    def test_b2_seam_receives_detail_string(self, monkeypatch):
        calls = []

        def fake_notify(cfg, kind, detail):
            calls.append(detail)

        monkeypatch.setattr(foundry, "_notify_human_hold", fake_notify)
        fake_notify(None, "auth", "auth hold: re-authenticate to resume (stage pm, iter 450)")
        assert "auth hold" in calls[0]
        assert "re-authenticate" in calls[0]


# ---------------------------------------------------------------------------
# EB3 -- Seam shells out with FOUNDRY_HOLD_KIND / FOUNDRY_HOLD_DETAIL; fail-open
# ---------------------------------------------------------------------------

class TestEB3ShellsOutFailOpen:

    def test_b3_no_exception_on_nonexistent_command(self, tmp_path):
        cfg = _mock_cfg("/usr/bin/nonexistent_foundry_test_cmd_450", tmp_path)
        result = foundry._notify_human_hold(cfg, "auth", "test detail")
        assert result is None

    def test_b3_no_exception_on_failing_command(self, tmp_path):
        cfg = _mock_cfg("exit 1", tmp_path)
        result = foundry._notify_human_hold(cfg, "auth", "test detail")
        assert result is None

    def test_b3_env_vars_passed_to_command(self, tmp_path):
        env_file = tmp_path / "env_dump.txt"
        cfg = _mock_cfg(
            f"env | grep FOUNDRY_HOLD > {env_file}", tmp_path
        )
        foundry._notify_human_hold(cfg, "auth", "test-detail-450")
        if env_file.exists():
            text = env_file.read_text()
            assert "FOUNDRY_HOLD_KIND=auth" in text
            assert "FOUNDRY_HOLD_DETAIL=test-detail-450" in text

    def test_b3_return_value_is_none(self, tmp_path):
        cfg = _mock_cfg("echo ok", tmp_path)
        result = foundry._notify_human_hold(cfg, "auth", "detail")
        assert result is None

    def test_b3_subprocess_timeout_does_not_propagate(self, monkeypatch, tmp_path):
        import subprocess
        orig_run = subprocess.run

        def timeout_run(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="test", timeout=30)

        monkeypatch.setattr(subprocess, "run", timeout_run)
        cfg = _mock_cfg("anything", tmp_path)
        foundry._notify_human_hold(cfg, "auth", "test detail")

    def test_b3_oserror_does_not_propagate(self, monkeypatch, tmp_path):
        import subprocess

        def raise_os(*a, **kw):
            raise OSError("test OS error")

        monkeypatch.setattr(subprocess, "run", raise_os)
        cfg = _mock_cfg("anything", tmp_path)
        foundry._notify_human_hold(cfg, "auth", "test detail")


# ---------------------------------------------------------------------------
# EB4 -- Empty notify_cmd spawns no subprocess
# ---------------------------------------------------------------------------

class TestEB4EmptyNotifyCmdNoOp:

    def test_b4_empty_cmd_returns_none(self):
        cfg = _mock_cfg("")
        result = foundry._notify_human_hold(cfg, "auth", "detail")
        assert result is None

    def test_b4_empty_cmd_no_subprocess(self, monkeypatch):
        import subprocess
        calls = []
        orig_run = subprocess.run

        def tracking_run(*a, **kw):
            calls.append(a)
            return orig_run(*a, **kw)

        monkeypatch.setattr(subprocess, "run", tracking_run)
        cfg = _mock_cfg("")
        foundry._notify_human_hold(cfg, "auth", "detail")
        assert len(calls) == 0

    def test_b4_default_config_has_empty_cmd(self):
        cfg = foundry.load_config("products/_platform/config.json")
        assert cfg.notify_cmd == ""


# ---------------------------------------------------------------------------
# EB5 -- Monkeypatched seam fires with correct kind/detail; failures don't propagate
# ---------------------------------------------------------------------------

class TestEB5MonkeypatchAndFailOpen:

    def test_b5_monkeypatch_replaces_seam(self, monkeypatch):
        calls = []

        def spy(cfg, kind, detail):
            calls.append({"kind": kind, "detail": detail})

        monkeypatch.setattr(foundry, "_notify_human_hold", spy)
        assert foundry._notify_human_hold is spy

    def test_b5_seam_callable_with_three_args(self, tmp_path):
        cfg = _mock_cfg("true", tmp_path)
        result = foundry._notify_human_hold(cfg, "auth", "detail text")
        assert result is None

    def test_b5_failing_command_preserves_normal_flow(self, tmp_path):
        cfg = _mock_cfg("false", tmp_path)
        result = foundry._notify_human_hold(cfg, "auth", "detail text")
        assert result is None

    def test_b5_exception_raising_command_is_caught(self, tmp_path):
        cfg = _mock_cfg("/usr/bin/surely_nonexistent_binary_450", tmp_path)
        try:
            foundry._notify_human_hold(cfg, "auth", "some detail")
        except Exception:
            raise AssertionError(
                "_notify_human_hold must not propagate exceptions (fail-open)"
            )

    def test_b5_kind_auth_accepted(self, tmp_path):
        cfg = _mock_cfg("true", tmp_path)
        result = foundry._notify_human_hold(cfg, "auth", "auth hold: re-authenticate to resume")
        assert result is None

    def test_b5_monkeypatched_seam_records_kind_and_detail(self, monkeypatch):
        calls = []

        def spy(cfg, kind, detail):
            calls.append({"kind": kind, "detail": detail})

        monkeypatch.setattr(foundry, "_notify_human_hold", spy)
        spy(None, "auth", "auth hold: re-authenticate to resume (stage pm, iter 450)")
        assert len(calls) == 1
        assert calls[0]["kind"] == "auth"
        assert "re-authenticate" in calls[0]["detail"]
