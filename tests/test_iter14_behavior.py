"""Black-box behaviour tests for iter 14 -- roadmap item 7, bite 2 of 2: raise a
per-product advisory ``SPEED_STORY_NEEDED.md`` flag when a genuine ship's
fresh-clone suite wall-time exceeds ``foundry.SUITE_SLOW_SECONDS``, mirroring the
proven ``HOTFIX_NEEDED.md`` lifecycle; auto-clear it on the next genuine fast
ship. Advisory (NON-blocking) and off every control path.

New public surface (all in ``foundry``): pure fn
``speed_story_needed(test_seconds, threshold) -> bool``;
``speed_story_flag_path(cfg) -> pathlib.Path``;
``write_speed_story_flag(cfg, sha, seconds, threshold) -> None``;
``clear_speed_story_flag(cfg) -> None``; plus lifecycle wiring inside
``postrelease_step``.

ISOLATION CONTRACT (honored): these tests were written from the iter-14 PM spec's
Expected Behaviors (1-12), the product README/roadmap, and the product's own
OBSERVABLE behaviour ONLY. The implementation source bodies of ``foundry.py`` /
``dispatcher.py`` were NOT opened/read while authoring, and neither the
engineer's nor the reviewer's notes nor ``git diff`` were read. Every functional
check drives the PUBLIC surface: the pure ``speed_story_needed``, the flag
read/write/clear helpers, and the ``postrelease_step`` orchestrator forced
through the documented module-level seams (``foundry.verify_fresh_clone``,
``foundry.run_cmd``, ``foundry.cleanup_clone``, ``foundry._monotonic``) with a
monkeypatched ``foundry.SUITE_SLOW_SECONDS`` -- exactly as iter 02/03/13 drove
the post-release path. The single structural behaviour (12 -- additivity /
off-the-control-path) is asserted PROGRAMMATICALLY at runtime via
``inspect.getsource`` of the named control-path functions + the dispatcher
module, encoding the spec's stated additivity contract (the same technique iter
12/13 used), NOT any implementation quirk. Fully offline & deterministic: real
temp dirs only, NO real network/agent-run (the only subprocesses are the
Behavior-12 ``import`` probe and the spec-mandated ``git check-ignore`` probe,
neither of which touches the network). The real foundry repo / real product
configs are NEVER mutated.
"""
import inspect
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (imported to assert it still loads, Behavior 12)


# --------------------------------------------------------------------------
# helpers / fixtures  (mirror the conventions in the other test modules)
# --------------------------------------------------------------------------
SETUP_CMD = "do-setup --now"
TEST_CMD = "do-test --all"
EXPECTED_SHA = "abcdef123456"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _write_cfg(tmp_path, **over):
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
    """A plain product config in a tmp dir (real repo never touched)."""
    return foundry.load_config(str(_write_cfg(tmp_path)))


@pytest.fixture
def vcfg(tmp_path):
    """A config with setup+test commands set to distinctive tokens, for driving
    postrelease_step through the REAL verify_fresh_clone end-to-end (offline)."""
    return foundry.load_config(str(_write_cfg(
        tmp_path, setup_cmd=SETUP_CMD, test_cmd=TEST_CMD)))


class _Res:
    """Stand-in for the run_cmd result type: only `.ok`/`.out` are contracted."""
    def __init__(self, ok, out="out"):
        self.ok = bool(ok)
        self.out = out


def make_run_cmd(*, remote_ok=True, clone_ok=True, setup_ok=True, test_ok=True,
                 rev_ok=True, cloned_sha=EXPECTED_SHA,
                 url="https://example.test/r.git"):
    """Scripted, offline replacement for foundry.run_cmd, classifying each
    command by its argv tokens (mirrors tests/test_iter02/13_behavior.py)."""
    def _run_cmd(args, cwd=None, timeout=None):
        a = list(args)
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
        return _Res(False, "UNEXPECTED:" + " ".join(map(str, a)))
    return _run_cmd


def make_monotonic(*values):
    """Deterministic clock seam: returns `values` in order; after the last is
    consumed keeps returning the final value."""
    seq = list(values)
    box = {"n": 0}
    def _m():
        i = box["n"]
        box["n"] += 1
        return seq[i] if i < len(seq) else seq[-1]
    return _m, box


def make_verify(result, recorder=None):
    """Scripted replacement for foundry.verify_fresh_clone returning a fixed
    PostReleaseResult (optionally recording the args it was given)."""
    def _v(cfg, expected_sha, clone_dir, *a, **k):
        if recorder is not None:
            recorder.append({"expected_sha": expected_sha, "clone_dir": clone_dir})
        return result
    return _v


def _sp(cfg):
    return foundry.speed_story_flag_path(cfg)


# ==========================================================================
# Behavior 1 -- Decision: slow -> True (strictly greater than threshold)
# ==========================================================================
def test_b1_slow_is_true():
    assert foundry.speed_story_needed(130.0, 120.0) is True
    assert foundry.speed_story_needed(120.01, 120.0) is True


# ==========================================================================
# Behavior 2 -- Decision: boundary (seconds == threshold) -> False (strictly >)
# ==========================================================================
def test_b2_boundary_equals_is_false():
    assert foundry.speed_story_needed(120.0, 120.0) is False


# ==========================================================================
# Behavior 3 -- Decision: fast -> False
# ==========================================================================
def test_b3_fast_is_false():
    assert foundry.speed_story_needed(4.2, 120.0) is False
    assert foundry.speed_story_needed(0.0, 120.0) is False


# ==========================================================================
# Behavior 4 -- Decision: None -> False, and the fn is TOTAL (never raises for
# None or any non-negative float) with a correct `seconds > threshold` verdict.
# ==========================================================================
def test_b4_none_is_false():
    assert foundry.speed_story_needed(None, 120.0) is False


@pytest.mark.parametrize("seconds", [0.0, 0.001, 1.0, 4.2, 5.0, 42.4242,
                                     119.999, 120.0, 120.01, 130.0, 1e6, 1e9])
def test_b4_total_and_matches_strict_gt(seconds):
    out = foundry.speed_story_needed(seconds, 120.0)
    assert isinstance(out, bool)
    assert out == (seconds > 120.0)


def test_b4_none_total_across_thresholds():
    for thr in (0.0, 1.0, 120.0, 1e9):
        assert foundry.speed_story_needed(None, thr) is False


# ==========================================================================
# Behavior 5 -- Flag path: <work_root>/SPEED_STORY_NEEDED.md, distinct from the
# hotfix flag path.
# ==========================================================================
def test_b5_flag_path_shape(cfg):
    p = foundry.speed_story_flag_path(cfg)
    assert isinstance(p, pathlib.Path)
    assert p.name == "SPEED_STORY_NEEDED.md"
    assert p.parent == pathlib.Path(cfg.work_root)


def test_b5_flag_path_differs_from_hotfix(cfg):
    assert foundry.speed_story_flag_path(cfg) != foundry.hotfix_flag_path(cfg)


# ==========================================================================
# Behavior 6 -- write creates an ADVISORY flag with evidence; newest-wins
# overwrite (no append pile-up).
# ==========================================================================
def test_b6_write_creates_advisory_flag_with_evidence(cfg):
    foundry.write_speed_story_flag(cfg, "abc1234", 200.0, 120.0)
    p = _sp(cfg)
    assert p.exists()
    txt = p.read_text()
    assert "abc1234" in txt                    # sha verbatim
    assert "200.00" in txt                     # seconds -> 2 decimals
    assert "120.00" in txt                     # threshold -> 2 decimals
    assert "advisory" in txt.lower()           # case-insensitive advisory marker
    # body states it is NON-blocking and subordinate to HOTFIX_NEEDED.md
    low = txt.lower()
    assert ("non-block" in low) or ("nonblock" in low) or ("not block" in low), \
        "advisory body does not state it is non-blocking"
    assert "HOTFIX_NEEDED.md" in txt, \
        "advisory body does not state it is subordinate to HOTFIX_NEEDED.md"


def test_b6_write_overwrites_no_append_pileup(cfg):
    foundry.write_speed_story_flag(cfg, "abc1234", 200.0, 120.0)
    foundry.write_speed_story_flag(cfg, "def5678", 305.0, 120.0)
    txt = _sp(cfg).read_text()
    assert "def5678" in txt and "305.00" in txt
    assert "abc1234" not in txt, "old sha leaked -> file appended, not overwritten"
    assert "200.00" not in txt, "old seconds leaked -> file appended, not overwritten"


# ==========================================================================
# Behavior 7 -- clear removes the flag; idempotent (silent no-op when absent).
# ==========================================================================
def test_b7_clear_removes_existing(cfg):
    foundry.write_speed_story_flag(cfg, "s", 200.0, 120.0)
    assert _sp(cfg).exists()
    foundry.clear_speed_story_flag(cfg)
    assert not _sp(cfg).exists()


def test_b7_clear_absent_is_silent_noop(cfg):
    assert not _sp(cfg).exists()
    foundry.clear_speed_story_flag(cfg)   # must NOT raise
    foundry.clear_speed_story_flag(cfg)   # still a no-op
    assert not _sp(cfg).exists()


# ==========================================================================
# Behavior 8 -- postrelease_step RAISES the flag on a genuine SLOW ship, even
# when the result is BROKEN (the advisory tracks measured wall-time vs the
# threshold, independent of `healthy`).
# ==========================================================================
def test_b8_slow_healthy_ship_raises_flag(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "verify_fresh_clone",
                        make_verify(foundry.PostReleaseResult(True, False, "green",
                                                              test_seconds=4.2)))
    monkeypatch.setattr(foundry, "SUITE_SLOW_SECONDS", 1.0)  # patched low
    ret = foundry.postrelease_step(cfg, 8, "shipsha")
    p = _sp(cfg)
    assert p.exists(), "genuine SLOW ship did not raise SPEED_STORY_NEEDED.md"
    txt = p.read_text()
    assert "shipsha" in txt
    assert f"{ret.test_seconds:.2f}" in txt      # measured seconds
    assert "1.00" in txt                          # patched threshold
    assert ret.sentinel == "POSTRELEASE: HEALTHY"


def test_b8_slow_broken_ship_still_raises_flag(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "verify_fresh_clone",
                        make_verify(foundry.PostReleaseResult(False, False,
                                                              "tests failed",
                                                              test_seconds=4.2)))
    monkeypatch.setattr(foundry, "SUITE_SLOW_SECONDS", 1.0)
    ret = foundry.postrelease_step(cfg, 8, "brokensha")
    p = _sp(cfg)
    assert p.exists(), "a slow-but-BROKEN ship did not raise the speed advisory"
    assert "brokensha" in p.read_text()
    assert ret.sentinel == "POSTRELEASE: BROKEN"   # verdict unchanged by advisory


def test_b8_slow_ship_end_to_end_through_real_verify(vcfg, monkeypatch):
    """End-to-end: postrelease_step -> the REAL verify_fresh_clone driven only
    through the documented offline seams (run_cmd/cleanup_clone/_monotonic). A
    measured ~4.2s suite under a patched 1.0s threshold raises the flag."""
    D = 4.2
    mono, box = make_monotonic(100.0, 100.0 + D)
    monkeypatch.setattr(foundry, "run_cmd", make_run_cmd())     # all success
    monkeypatch.setattr(foundry, "cleanup_clone", lambda *a, **k: None)
    monkeypatch.setattr(foundry, "_monotonic", mono)
    monkeypatch.setattr(foundry, "SUITE_SLOW_SECONDS", 1.0)
    ret = foundry.postrelease_step(vcfg, 8, "e2esha")
    assert box["n"] >= 2, "clock seam not read to bracket the test command"
    p = _sp(vcfg)
    assert p.exists(), "measured-slow ship did not raise the advisory end-to-end"
    txt = p.read_text()
    assert "e2esha" in txt
    assert f"{ret.test_seconds:.2f}" in txt


# ==========================================================================
# Behavior 9 -- postrelease_step CLEARS the flag on a genuine FAST ship.
# ==========================================================================
def test_b9_fast_ship_clears_preexisting_flag(cfg, monkeypatch):
    foundry.write_speed_story_flag(cfg, "stale", 999.0, 120.0)  # pre-existing
    assert _sp(cfg).exists()
    monkeypatch.setattr(foundry, "verify_fresh_clone",
                        make_verify(foundry.PostReleaseResult(True, False, "green",
                                                              test_seconds=4.2)))
    # default 120.0 threshold; 4.2 is NOT slow -> flag must be cleared
    ret = foundry.postrelease_step(cfg, 9, "fastsha")
    assert not _sp(cfg).exists(), "a genuine FAST ship did not clear the advisory"
    assert ret.sentinel == "POSTRELEASE: HEALTHY"


def test_b9_fast_broken_ship_also_clears_flag(cfg, monkeypatch):
    # a fast suite that FAILED is still not-slow -> advisory cleared regardless
    foundry.write_speed_story_flag(cfg, "stale", 999.0, 120.0)
    monkeypatch.setattr(foundry, "verify_fresh_clone",
                        make_verify(foundry.PostReleaseResult(False, False, "boom",
                                                              test_seconds=4.2)))
    ret = foundry.postrelease_step(cfg, 9, "sha")
    assert not _sp(cfg).exists()
    assert ret.sentinel == "POSTRELEASE: BROKEN"


# ==========================================================================
# Behavior 10 -- postrelease_step LEAVES the flag UNTOUCHED when the suite did
# not run (test_seconds is None): infra-skip, disabled, or verify errored.
# ==========================================================================
def test_b10_infra_skip_leaves_existing_flag(cfg, monkeypatch):
    foundry.write_speed_story_flag(cfg, "keep", 999.0, 120.0)
    before = _sp(cfg).read_text()
    monkeypatch.setattr(foundry, "verify_fresh_clone",
                        make_verify(foundry.PostReleaseResult(True, True,
                                                              "infra skip",
                                                              test_seconds=None)))
    foundry.postrelease_step(cfg, 10, "sha")
    assert _sp(cfg).exists(), "infra-skip wrongly cleared a pre-existing advisory"
    assert _sp(cfg).read_text() == before


def test_b10_infra_skip_does_not_create_flag(cfg, monkeypatch):
    assert not _sp(cfg).exists()
    monkeypatch.setattr(foundry, "verify_fresh_clone",
                        make_verify(foundry.PostReleaseResult(True, True,
                                                              "infra skip",
                                                              test_seconds=None)))
    foundry.postrelease_step(cfg, 10, "sha")
    assert not _sp(cfg).exists(), "infra-skip raised a false speed advisory"


def test_b10_disabled_leaves_flag_untouched(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, postrelease_enabled=False)))
    assert cfg.postrelease_enabled is False
    foundry.write_speed_story_flag(cfg, "keep", 999.0, 120.0)
    before = _sp(cfg).read_text()
    foundry.postrelease_step(cfg, 10, "sha")   # must not raise
    assert _sp(cfg).exists()
    assert _sp(cfg).read_text() == before, "disabled path mutated the advisory"


def test_b10_verify_error_leaves_flag_untouched(cfg, monkeypatch):
    foundry.write_speed_story_flag(cfg, "keep", 999.0, 120.0)
    before = _sp(cfg).read_text()

    def _boom(*a, **k):
        raise RuntimeError("clone blew up")
    monkeypatch.setattr(foundry, "verify_fresh_clone", _boom)
    ret = foundry.postrelease_step(cfg, 10, "sha")   # treated as infra; no raise
    assert ret.skipped_infra is True
    assert _sp(cfg).exists(), "verify-error (infra) wrongly touched the advisory"
    assert _sp(cfg).read_text() == before


# ==========================================================================
# Behavior 11 -- the advisory never affects the verdict and never crashes a
# shipped iteration; a flag I/O error is SWALLOWED; the iter-03 hotfix lifecycle
# is unchanged (and its write stays UN-wrapped).
# ==========================================================================
def test_b11_sentinel_identical_with_or_without_flag_write(cfg, monkeypatch):
    # slow ship (writes the advisory) -> still HEALTHY sentinel
    monkeypatch.setattr(foundry, "verify_fresh_clone",
                        make_verify(foundry.PostReleaseResult(True, False, "green",
                                                              test_seconds=4.2)))
    monkeypatch.setattr(foundry, "SUITE_SLOW_SECONDS", 1.0)
    ret = foundry.postrelease_step(cfg, 11, "sha")
    assert ret.sentinel == "POSTRELEASE: HEALTHY"
    assert ret.healthy is True and ret.skipped_infra is False


def test_b11_write_error_is_swallowed(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "verify_fresh_clone",
                        make_verify(foundry.PostReleaseResult(True, False, "green",
                                                              test_seconds=4.2)))
    monkeypatch.setattr(foundry, "SUITE_SLOW_SECONDS", 1.0)   # slow -> attempts write

    def _boom_write(*a, **k):
        raise RuntimeError("disk full while writing advisory")
    monkeypatch.setattr(foundry, "write_speed_story_flag", _boom_write)
    ret = foundry.postrelease_step(cfg, 11, "sha")   # must NOT raise
    assert ret.sentinel == "POSTRELEASE: HEALTHY", \
        "swallowed advisory write still changed the verdict/sentinel"


def test_b11_clear_error_is_swallowed(cfg, monkeypatch):
    foundry.write_speed_story_flag(cfg, "stale", 999.0, 120.0)
    monkeypatch.setattr(foundry, "verify_fresh_clone",
                        make_verify(foundry.PostReleaseResult(True, False, "green",
                                                              test_seconds=4.2)))
    # default threshold; 4.2 not slow -> attempts a clear

    def _boom_clear(*a, **k):
        raise RuntimeError("permission denied clearing advisory")
    monkeypatch.setattr(foundry, "clear_speed_story_flag", _boom_clear)
    ret = foundry.postrelease_step(cfg, 11, "sha")   # must NOT raise
    assert ret.sentinel == "POSTRELEASE: HEALTHY", \
        "swallowed advisory clear still changed the verdict/sentinel"


def test_b11_hotfix_lifecycle_unchanged_broken_writes(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "verify_fresh_clone",
                        make_verify(foundry.PostReleaseResult(False, False,
                                                              "broke", test_seconds=None)))
    foundry.postrelease_step(cfg, 11, "brk")
    assert foundry.hotfix_flag_path(cfg).exists(), \
        "BROKEN ship no longer writes HOTFIX_NEEDED.md (hotfix lifecycle regressed)"


def test_b11_hotfix_lifecycle_unchanged_genuine_healthy_clears(cfg, monkeypatch):
    foundry.write_hotfix_flag(cfg, "stale", "old breakage")
    monkeypatch.setattr(foundry, "verify_fresh_clone",
                        make_verify(foundry.PostReleaseResult(True, False, "green",
                                                              test_seconds=None)))
    foundry.postrelease_step(cfg, 11, "ok")
    assert not foundry.hotfix_flag_path(cfg).exists(), \
        "genuine-HEALTHY ship no longer clears HOTFIX_NEEDED.md"


def test_b11_hotfix_lifecycle_unchanged_infra_skip_leaves(cfg, monkeypatch):
    foundry.write_hotfix_flag(cfg, "keep", "real breakage")
    before = foundry.hotfix_flag_path(cfg).read_text()
    monkeypatch.setattr(foundry, "verify_fresh_clone",
                        make_verify(foundry.PostReleaseResult(True, True,
                                                              "infra", test_seconds=None)))
    foundry.postrelease_step(cfg, 11, "sha")
    assert foundry.hotfix_flag_path(cfg).exists()
    assert foundry.hotfix_flag_path(cfg).read_text() == before


# ==========================================================================
# Behavior 12 -- additive & OFF the control path.
# ==========================================================================
NEW_SYMBOLS = ["speed_story_needed", "speed_story_flag_path",
               "write_speed_story_flag", "clear_speed_story_flag",
               "SPEED_STORY_NEEDED.md"]
CONTROL_PATH_FNS = ["build_prompt", "run_stage", "run_iteration", "run_continuous"]


def test_b12_both_modules_import():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0, \
        f"`import foundry, dispatcher` failed:\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"


@pytest.mark.parametrize("fn_name", CONTROL_PATH_FNS)
def test_b12_new_symbols_absent_from_control_path_functions(fn_name):
    fn = getattr(foundry, fn_name, None)
    if fn is None:
        pytest.skip(f"foundry.{fn_name} not present")
    src = inspect.getsource(fn)
    for sym in NEW_SYMBOLS:
        assert sym not in src, \
            f"new symbol {sym!r} leaked into control-path function {fn_name!r}"


def test_b12_new_symbols_absent_from_dispatcher_module():
    src = inspect.getsource(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in src, f"new symbol {sym!r} leaked into dispatcher.py"


def test_b12_new_symbols_live_in_the_postrelease_path():
    # positive control: the additivity assertions are only meaningful if the
    # advisory IS wired into the post-release path.
    joined = "".join(
        inspect.getsource(getattr(foundry, name))
        for name in ("postrelease_step", "write_speed_story_flag",
                     "clear_speed_story_flag")
        if hasattr(foundry, name))
    assert "speed_story" in joined, \
        "speed-story advisory not referenced in the post-release path"


def test_b12_postrelease_sentinels_unchanged():
    assert foundry.PostReleaseResult(True, False, "x").sentinel == "POSTRELEASE: HEALTHY"
    assert foundry.PostReleaseResult(False, False, "x").sentinel == "POSTRELEASE: BROKEN"
    assert foundry.PostReleaseResult(True, True, "x").sentinel == "POSTRELEASE: HEALTHY"


def test_b12_speed_flag_is_git_ignored():
    # spec-mandated: products/*/SPEED_STORY_NEEDED.md must be ignored so the
    # per-run advisory never leaks into a ship diff.
    from shutil import which
    if which("git") is None:
        pytest.skip("git not available")
    proc = subprocess.run(
        ["git", "check-ignore", "products/_platform/SPEED_STORY_NEEDED.md"],
        capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0, \
        ("products/_platform/SPEED_STORY_NEEDED.md is NOT git-ignored "
         f"(check-ignore rc={proc.returncode}); it would leak into the ship diff")
