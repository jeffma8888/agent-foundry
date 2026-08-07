"""Black-box behaviour tests for iter 02 -- the DORMANT post-release
fresh-clone verification helper.

Covers Expected Behaviors 1-12 of the iter-02 PM spec: three backward-compatible
`ProductConfig` fields, the `run_cmd`/`cleanup_clone` I/O seams, the pure
`sha_matches`/`postrelease_verdict` decision functions, and the
`verify_fresh_clone` orchestrator.

ISOLATION: written from the PM spec (Expected Behaviors 1-12) and the product's
own observable RUNTIME behaviour ONLY. The implementation source, the
engineer/reviewer notes, and `git diff` were NOT read. Every external effect is
forced through the two documented module-level seams (`foundry.run_cmd`,
`foundry.cleanup_clone`), so the suite is fully offline and deterministic: no
real network, git clone, or subprocess execution.

  (The single real `run_cmd` call below (Behavior 2) targets a binary that
  cannot exist, so it fails at the exec syscall -- NO child process is launched
  and no network is touched -- which exercises the launch-failure return
  contract without "shelling out for real". The return-code -> `.ok` mapping is
  a real-subprocess property the spec explicitly puts out of scope for offline
  tests; it is instead exercised indirectly via the scripted seam in
  Behaviors 8-11. See tester.md for the ambiguity note.)
"""
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (imported to assert it still loads, Behavior 12)


# --------------------------------------------------------------------------
# helpers / fixtures
# --------------------------------------------------------------------------
SETUP_CMD = "do-setup --now"
TEST_CMD = "do-test --all"
SMOKE_CMD = "do-smoke --demo"


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
    """A config with all three verify commands set to distinctive tokens."""
    return foundry.load_config(str(_write_cfg(
        tmp_path, setup_cmd=SETUP_CMD, test_cmd=TEST_CMD, smoke_cmd=SMOKE_CMD)))


def _tokstr(args):
    return " ".join(str(x) for x in args)


def _assoc(val, args, cwd):
    """True if `val` is the command's cwd or appears in its argv (tolerates
    both `cwd=` and `-C <dir>` styles for the two pure git-read commands)."""
    return str(cwd) == str(val) or str(val) in _tokstr(args)


class _Res:
    """Stand-in for the run_cmd result type: only `.ok`/`.out` are contracted."""
    def __init__(self, ok, out="out"):
        self.ok = bool(ok)
        self.out = out


def make_run_cmd(recorder, *, remote_ok=True, clone_ok=True, setup_ok=True,
                 test_ok=True, rev_ok=True, smoke_ok=True,
                 cloned_sha="abcdef123456", url="https://example.test/r.git"):
    """A scripted, offline replacement for foundry.run_cmd.

    Classifies each command by its argv tokens and returns a `.ok`/`.out`
    result so the tester can force any verify_fresh_clone path deterministically.
    """
    def _run_cmd(args, cwd=None, timeout=None):
        a = list(args)
        recorder.append({"args": a, "cwd": cwd})
        if "remote" in a and "get-url" in a:
            return _Res(remote_ok, url if remote_ok else "no-remote")
        if "clone" in a:
            return _Res(clone_ok, "cloned" if clone_ok else "clone-failed")
        if "rev-parse" in a:
            return _Res(rev_ok, cloned_sha if rev_ok else "?")
        if a == SETUP_CMD.split():
            return _Res(setup_ok, "setup")
        if a == TEST_CMD.split():
            return _Res(test_ok, "tests")
        if a == SMOKE_CMD.split():
            return _Res(smoke_ok, "smoke")
        return _Res(False, "UNEXPECTED:" + _tokstr(a))
    return _run_cmd


def _verdict(**over):
    base = dict(remote_ok=True, clone_ok=True, setup_ok=True,
                test_ok=True, sha_ok=True, smoke_ran=False, smoke_ok=True)
    base.update(over)
    return foundry.postrelease_verdict(**base)


# ==========================================================================
# Behavior 1 -- three backward-compatible ProductConfig fields
# ==========================================================================
def test_b1_config_defaults_when_omitted(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))  # omits all three
    assert cfg.postrelease_enabled is True
    assert cfg.setup_cmd == "uv sync"
    assert cfg.smoke_cmd is None


def test_b1_config_honours_overrides(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(
        tmp_path, postrelease_enabled=False,
        setup_cmd="make setup", smoke_cmd="make demo")))
    assert cfg.postrelease_enabled is False
    assert cfg.setup_cmd == "make setup"
    assert cfg.smoke_cmd == "make demo"


def test_b1_unknown_keys_now_rejected(tmp_path):
    # Contract INVERTED by iter 128: this used to assert that an unknown key was
    # silently dropped while the new fields still defaulted. Silently dropping it is
    # the defect (a mistyped `push_enabled` pushed anyway), so the loader now raises.
    with pytest.raises(foundry.ConfigKeyError) as exc:
        foundry.load_config(str(_write_cfg(tmp_path, bogus_iter02_key="x")))
    assert "bogus_iter02_key" in str(exc.value)


def test_b1_shipped_platform_config_loads_with_defaults():
    # the existing products/_platform/config.json omits the three new fields
    real = foundry.FOUNDRY / "products" / "_platform" / "config.json"
    cfg = foundry.load_config(str(real))
    assert cfg.postrelease_enabled is True
    assert cfg.setup_cmd == "uv sync"
    assert cfg.smoke_cmd is None


# ==========================================================================
# Behavior 2 -- run_cmd seam return contract
# ==========================================================================
def test_b2_run_cmd_is_module_level_callable():
    assert callable(foundry.run_cmd)


def test_b2_run_cmd_launch_failure_is_not_ok_and_does_not_propagate():
    # A binary that cannot exist fails at exec -> no process launched, no
    # network. run_cmd must swallow the OSError and return .ok False + non-empty
    # .out (Behavior 2's launch-failure clause). If it propagates, this test
    # fails, which is the correct signal.
    res = foundry.run_cmd(["__foundry_no_such_binary_zqx__", "--nope"])
    assert res.ok is False
    assert isinstance(res.out, str) and res.out


# ==========================================================================
# Behavior 3 -- sha_matches (pure)
# ==========================================================================
def test_b3_sha_matches_prefix_true_both_orders():
    full = "7bb2cddd2e8a46a25baa9f95af49fe9c69dd295c"
    assert foundry.sha_matches("7bb2cdd", full) is True
    assert foundry.sha_matches(full, "7bb2cdd") is True      # order independent
    assert foundry.sha_matches("abc123", "abc123") is True   # exact equal


def test_b3_sha_matches_disagree_false():
    assert foundry.sha_matches("7bb2cdd", "deadbeef0000") is False


def test_b3_sha_matches_empty_or_unknown_false():
    assert foundry.sha_matches("", "abc123") is False
    assert foundry.sha_matches("abc123", "") is False
    assert foundry.sha_matches("?", "abc123") is False
    assert foundry.sha_matches("abc123", "?") is False


# ==========================================================================
# Behavior 4 -- postrelease_verdict result shape + sentinel<->healthy mapping
# ==========================================================================
def test_b4_result_shape_and_sentinel_mapping():
    r = _verdict()  # all good, smoke skipped -> healthy
    assert isinstance(r, foundry.PostReleaseResult)
    assert isinstance(r.healthy, bool)
    assert isinstance(r.skipped_infra, bool)
    assert isinstance(r.detail, str) and r.detail
    assert r.sentinel == "POSTRELEASE: HEALTHY"

    b = _verdict(test_ok=False)  # a real failure -> broken
    assert b.healthy is False
    assert b.sentinel == "POSTRELEASE: BROKEN"


# ==========================================================================
# Behavior 5 -- infra tolerance (precedence over failure checks)
# ==========================================================================
@pytest.mark.parametrize("infra_field", ["remote_ok", "clone_ok", "setup_ok"])
def test_b5_infra_failure_is_skipped_and_takes_precedence(infra_field):
    # test/sha also failing -> infra check must still win => HEALTHY skipped
    r = _verdict(**{infra_field: False}, test_ok=False, sha_ok=False)
    assert r.healthy is True
    assert r.skipped_infra is True
    assert r.sentinel == "POSTRELEASE: HEALTHY"


# ==========================================================================
# Behavior 6 -- real failure => BROKEN (network-boundary steps all passed)
# ==========================================================================
def test_b6_test_failure_broken():
    r = _verdict(test_ok=False)
    assert r.healthy is False
    assert r.skipped_infra is False
    assert r.sentinel == "POSTRELEASE: BROKEN"


def test_b6_sha_failure_broken():
    r = _verdict(sha_ok=False)  # test_ok True
    assert r.healthy is False
    assert r.skipped_infra is False
    assert r.sentinel == "POSTRELEASE: BROKEN"


def test_b6_smoke_ran_and_failed_broken():
    r = _verdict(smoke_ran=True, smoke_ok=False)  # test+sha ok
    assert r.healthy is False
    assert r.sentinel == "POSTRELEASE: BROKEN"


# ==========================================================================
# Behavior 7 -- all good => HEALTHY (not skipped); skipped smoke never breaks
# ==========================================================================
def test_b7_all_good_smoke_skipped_healthy_not_skipped():
    r = _verdict(smoke_ran=False)
    assert r.healthy is True
    assert r.skipped_infra is False
    assert r.sentinel == "POSTRELEASE: HEALTHY"


def test_b7_all_good_smoke_passed_healthy_not_skipped():
    r = _verdict(smoke_ran=True, smoke_ok=True)
    assert r.healthy is True
    assert r.skipped_infra is False
    assert r.sentinel == "POSTRELEASE: HEALTHY"


def test_b7_skipped_smoke_never_broken_even_if_smoke_ok_false():
    r = _verdict(smoke_ran=False, smoke_ok=False)  # smoke not run -> irrelevant
    assert r.healthy is True
    assert r.sentinel == "POSTRELEASE: HEALTHY"


# ==========================================================================
# Behavior 8 -- verify_fresh_clone issues the expected commands via the seams
# ==========================================================================
def test_b8_verify_issues_expected_commands(cfg, tmp_path, monkeypatch):
    clone_dir = str(tmp_path / "clone")
    rec = []
    monkeypatch.setattr(foundry, "run_cmd",
                        make_run_cmd(rec, cloned_sha="abcdef123456"))
    monkeypatch.setattr(foundry, "cleanup_clone", lambda *a, **k: None)
    foundry.verify_fresh_clone(cfg, "abcdef123456", clone_dir)

    remote = [c for c in rec if "remote" in c["args"] and "get-url" in c["args"]]
    assert remote, "no `git remote get-url` command issued"
    assert _assoc(cfg.repo, remote[0]["args"], remote[0]["cwd"]), \
        "remote get-url not associated with cfg.repo"

    clone = [c for c in rec if "clone" in c["args"]]
    assert clone, "no `git clone` command issued"
    assert str(clone_dir) in _tokstr(clone[0]["args"]), \
        "clone did not target clone_dir"

    setup = [c for c in rec if c["args"] == SETUP_CMD.split()]
    assert setup, "setup_cmd not issued"
    assert str(setup[0]["cwd"]) == str(clone_dir), "setup cwd != clone_dir"

    test = [c for c in rec if c["args"] == TEST_CMD.split()]
    assert test, "test_cmd not issued"
    assert str(test[0]["cwd"]) == str(clone_dir), "test cwd != clone_dir"

    rev = [c for c in rec if "rev-parse" in c["args"]]
    assert rev, "no `git rev-parse` command issued"
    assert _assoc(clone_dir, rev[0]["args"], rev[0]["cwd"]), \
        "rev-parse not associated with clone_dir"

    smoke = [c for c in rec if c["args"] == SMOKE_CMD.split()]
    assert smoke, "smoke_cmd not issued when cfg.smoke_cmd is set"
    assert str(smoke[0]["cwd"]) == str(clone_dir), "smoke cwd != clone_dir"


# ==========================================================================
# Behavior 9 -- verify_fresh_clone end-to-end verdicts
# ==========================================================================
def _run_verify(cfg, monkeypatch, clone_dir, expected="abcdef123456", **kw):
    rec = []
    monkeypatch.setattr(foundry, "run_cmd", make_run_cmd(rec, **kw))
    monkeypatch.setattr(foundry, "cleanup_clone", lambda *a, **k: None)
    return foundry.verify_fresh_clone(cfg, expected, clone_dir), rec


def test_b9_all_success_and_sha_match_healthy(cfg, tmp_path, monkeypatch):
    r, _ = _run_verify(cfg, monkeypatch, str(tmp_path / "c"),
                       cloned_sha="abcdef123456")
    assert r.healthy is True
    assert r.skipped_infra is False
    assert r.sentinel == "POSTRELEASE: HEALTHY"


def test_b9_clone_fail_infra_skipped(cfg, tmp_path, monkeypatch):
    r, _ = _run_verify(cfg, monkeypatch, str(tmp_path / "c"), clone_ok=False)
    assert r.healthy is True
    assert r.skipped_infra is True
    assert r.sentinel == "POSTRELEASE: HEALTHY"


def test_b9_setup_fail_infra_skipped(cfg, tmp_path, monkeypatch):
    r, _ = _run_verify(cfg, monkeypatch, str(tmp_path / "c"), setup_ok=False)
    assert r.healthy is True
    assert r.skipped_infra is True
    assert r.sentinel == "POSTRELEASE: HEALTHY"


def test_b9_test_fail_broken(cfg, tmp_path, monkeypatch):
    r, _ = _run_verify(cfg, monkeypatch, str(tmp_path / "c"), test_ok=False)
    assert r.healthy is False
    assert r.skipped_infra is False
    assert r.sentinel == "POSTRELEASE: BROKEN"


def test_b9_sha_mismatch_broken(cfg, tmp_path, monkeypatch):
    r, _ = _run_verify(cfg, monkeypatch, str(tmp_path / "c"),
                       cloned_sha="999999999999")  # != expected abcdef123456
    assert r.healthy is False
    assert r.sentinel == "POSTRELEASE: BROKEN"


def test_b9_no_smoke_cmd_healthy_and_no_smoke_issued(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_cfg(
        tmp_path, setup_cmd=SETUP_CMD, test_cmd=TEST_CMD)))  # smoke_cmd -> None
    assert cfg.smoke_cmd is None
    rec = []
    monkeypatch.setattr(foundry, "run_cmd", make_run_cmd(rec))
    monkeypatch.setattr(foundry, "cleanup_clone", lambda *a, **k: None)
    r = foundry.verify_fresh_clone(cfg, "abcdef123456", str(tmp_path / "c"))
    assert r.healthy is True
    assert r.sentinel == "POSTRELEASE: HEALTHY"
    assert not any("do-smoke" in _tokstr(c["args"]) for c in rec), \
        "smoke command issued despite smoke_cmd being None"


# ==========================================================================
# Behavior 10 -- cleanup always attempted; cleanup failure never flips verdict
# ==========================================================================
@pytest.mark.parametrize("kw,expect_healthy", [
    ({}, True),                    # success
    ({"test_ok": False}, False),   # BROKEN
    ({"clone_ok": False}, True),   # infra-skipped
])
def test_b10_cleanup_called_on_every_path(cfg, tmp_path, monkeypatch,
                                          kw, expect_healthy):
    clone_dir = str(tmp_path / "c")
    calls = []
    monkeypatch.setattr(foundry, "run_cmd", make_run_cmd([], **kw))
    monkeypatch.setattr(foundry, "cleanup_clone",
                        lambda d, *a, **k: calls.append(d))
    r = foundry.verify_fresh_clone(cfg, "abcdef123456", clone_dir)
    assert r.healthy is expect_healthy
    assert calls, "cleanup_clone was not called"
    assert str(calls[0]) == str(clone_dir)


def test_b10_cleanup_raise_does_not_change_verdict(cfg, tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("cleanup boom")
    monkeypatch.setattr(foundry, "run_cmd", make_run_cmd([]))  # all success
    monkeypatch.setattr(foundry, "cleanup_clone", _boom)
    r = foundry.verify_fresh_clone(cfg, "abcdef123456", str(tmp_path / "c"))
    assert r.healthy is True
    assert r.sentinel == "POSTRELEASE: HEALTHY"


# ==========================================================================
# Behavior 11 -- exception-safe: run_cmd raising => infra-skipped, cleanup tried
# ==========================================================================
def test_b11_run_cmd_raises_is_infra_skipped_and_cleanup_attempted(
        cfg, tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("run_cmd boom")
    calls = []
    monkeypatch.setattr(foundry, "run_cmd", _boom)
    monkeypatch.setattr(foundry, "cleanup_clone",
                        lambda d, *a, **k: calls.append(d))
    r = foundry.verify_fresh_clone(cfg, "abcdef123456", str(tmp_path / "c"))
    assert r.healthy is True
    assert r.skipped_infra is True
    assert isinstance(r.detail, str) and r.detail
    assert calls, "cleanup not attempted after run_cmd raised"


# ==========================================================================
# Behavior 12 -- the helper is DORMANT; existing surface unchanged
# ==========================================================================
def test_b12_foundry_and_dispatcher_importable():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        capture_output=True, text=True,
        cwd=str(pathlib.Path(foundry.__file__).resolve().parent))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_b12_cli_help_still_lists_run_once_doctor():
    foundry_py = pathlib.Path(foundry.__file__).resolve()
    proc = subprocess.run(
        [sys.executable, str(foundry_py), "--help"],
        capture_output=True, text=True, cwd=str(foundry_py.parent))
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    for sub in ("run", "once", "doctor"):
        assert sub in combined, f"subcommand {sub!r} missing from --help"


def test_b12_new_names_and_pipeline_names_coexist():
    for name in ("run_cmd", "cleanup_clone", "sha_matches",
                 "postrelease_verdict", "verify_fresh_clone",
                 "PostReleaseResult"):
        assert hasattr(foundry, name), f"missing new name {name}"
    for name in ("run_iteration", "run_continuous", "run_stage",
                 "narrative_report", "mechanical_report", "main"):
        assert hasattr(foundry, name), f"pipeline name {name} vanished"


def test_b12_doctor_cli_path_does_not_invoke_helper(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    called = []
    monkeypatch.setattr(foundry, "verify_fresh_clone",
                        lambda *a, **k: called.append(1))

    class _Chk:
        def __init__(self, n):
            self.name, self.ok, self.detail = n, True, "detail"

    monkeypatch.setattr(foundry, "check_power", lambda *a, **k: _Chk("power"))
    monkeypatch.setattr(foundry, "check_agent", lambda *a, **k: _Chk("agent"))
    monkeypatch.setattr(foundry, "check_uv", lambda *a, **k: _Chk("uv"))
    monkeypatch.setattr(foundry, "check_remote", lambda *a, **k: _Chk("remote"))

    rc = foundry.main(["doctor", "--config", str(cfg_path)])
    assert isinstance(rc, int)
    assert called == [], "verify_fresh_clone was invoked by the doctor CLI path"
