"""Black-box behaviour tests for iter 13 -- recording the fresh-clone test-suite
wall-time per ship (roadmap item 7, bite 1 of 2). New public surface: a pure
formatter `foundry.suite_timing_line(seconds, threshold) -> str`, a module
constant `foundry.SUITE_SLOW_SECONDS` (float, default 120.0), a monkeypatchable
clock seam `foundry._monotonic`, and an optional inert `test_seconds` field on
`foundry.PostReleaseResult`. Additive-only: the timing rides the existing
post-release path (`verify_fresh_clone` / `postrelease_step` /
`_write_postrelease_artifact`) and the existing NIGHT_LOG / postrelease.md
artifacts.

ISOLATION CONTRACT (honored): these tests were written from the iter-13 PM spec's
Expected Behaviors (1-12) and the product's own OBSERVABLE behaviour ONLY. The
implementation source of `foundry.py` / `dispatcher.py` was NOT opened/read while
authoring; the engineer's and reviewer's notes and `git diff` were NOT read.
Every check drives the PUBLIC surface: the pure `suite_timing_line`, the
`verify_fresh_clone` / `postrelease_step` orchestrators forced through the
documented module-level seams (`foundry.run_cmd`, `foundry.cleanup_clone`,
`foundry.verify_fresh_clone`, and the new `foundry._monotonic` clock seam), and
the resulting NIGHT_LOG / postrelease.md artifacts. The single structural
behaviour (12 -- additivity / off-the-control-path) is asserted PROGRAMMATICALLY
at runtime via `inspect.getsource` of the named public functions + the dispatcher
module, encoding the spec's stated additivity contract, NOT any implementation
quirk (the same technique iter 12 used for its structural behaviour). Fully
offline & deterministic: real temp dirs only, NO real subprocess/git/network/
agent-run (the only subprocess is the Behavior-12 `import` probe, which touches
no network). The real foundry repo / real product configs are NEVER used.
"""
import dataclasses
import inspect
import json
import pathlib
import re
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
    verify_fresh_clone end-to-end (smoke omitted -> None)."""
    return foundry.load_config(str(_write_cfg(
        tmp_path, setup_cmd=SETUP_CMD, test_cmd=TEST_CMD)))


class _Res:
    """Stand-in for the run_cmd result type: only `.ok`/`.out` are contracted."""
    def __init__(self, ok, out="out"):
        self.ok = bool(ok)
        self.out = out


def make_run_cmd(recorder=None, *, remote_ok=True, clone_ok=True, setup_ok=True,
                 test_ok=True, rev_ok=True, cloned_sha=EXPECTED_SHA,
                 url="https://example.test/r.git"):
    """Scripted, offline replacement for foundry.run_cmd, classifying each
    command by its argv tokens (mirrors tests/test_iter02_behavior.py)."""
    def _run_cmd(args, cwd=None, timeout=None):
        a = list(args)
        if recorder is not None:
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
        return _Res(False, "UNEXPECTED:" + " ".join(map(str, a)))
    return _run_cmd


def make_monotonic(*values):
    """A deterministic clock seam: returns `values` in order; after the last is
    consumed keeps returning the final value (so the measurement is robust to
    any extra reads). `box['n']` records how many times it was called."""
    seq = list(values)
    box = {"n": 0}
    def _m():
        i = box["n"]
        box["n"] += 1
        return seq[i] if i < len(seq) else seq[-1]
    return _m, box


def make_verify(result, recorder=None):
    """Scripted replacement for foundry.verify_fresh_clone returning a fixed
    PostReleaseResult (records the args it was given)."""
    def _v(cfg, expected_sha, clone_dir, *a, **k):
        if recorder is not None:
            recorder.append({"expected_sha": expected_sha, "clone_dir": clone_dir})
        return result
    return _v


def _iter_dir(cfg, iteration):
    return cfg.state / f"iter-{iteration:02d}"


def _artifact(cfg, iteration):
    return _iter_dir(cfg, iteration) / "postrelease.md"


def _nonempty_lines(path):
    if not pathlib.Path(path).exists():
        return []
    return [ln for ln in pathlib.Path(path).read_text().splitlines() if ln.strip()]


def _last_nonempty_line(path):
    lines = _nonempty_lines(path)
    return lines[-1] if lines else ""


def _timing_lines(path):
    return [ln for ln in _nonempty_lines(path) if "suite wall-time" in ln]


# ==========================================================================
# Behavior 1 -- not-slow format is EXACT, 2 decimals, no "SLOW"
# ==========================================================================
def test_b1_not_slow_exact_format():
    assert foundry.suite_timing_line(4.2, 120.0) == \
        "fresh-clone suite wall-time: 4.20s"


# ==========================================================================
# Behavior 2 -- slow format is EXACT (both numbers 2 decimals; token SLOW)
# ==========================================================================
def test_b2_slow_exact_format():
    out = foundry.suite_timing_line(130.0, 120.0)
    assert out == ("fresh-clone suite wall-time: 130.00s SLOW "
                   "(>120.00s threshold; consider a speed story)")
    assert "SLOW" in out


# ==========================================================================
# Behavior 3 -- boundary (seconds == threshold) is NOT slow (strictly >)
# ==========================================================================
def test_b3_boundary_is_not_slow():
    out = foundry.suite_timing_line(120.0, 120.0)
    assert "SLOW" not in out
    assert out == "fresh-clone suite wall-time: 120.00s"


def test_b3_just_over_is_slow():
    out = foundry.suite_timing_line(120.01, 120.0)
    assert "SLOW" in out


# ==========================================================================
# Behavior 4 -- total (never raises for non-negative floats) + always 2 decimals
# ==========================================================================
def test_b4_zero_and_five_contain_two_decimal_seconds():
    assert "0.00s" in foundry.suite_timing_line(0.0, 120.0)
    assert "5.00s" in foundry.suite_timing_line(5.0, 120.0)


@pytest.mark.parametrize("seconds", [0.0, 0.001, 1.0, 4.2, 5.0, 42.4242,
                                     119.999, 120.0, 130.0, 1e6, 1e9])
def test_b4_total_and_two_decimals(seconds):
    # never raises for any non-negative float ...
    out = foundry.suite_timing_line(seconds, 120.0)
    assert isinstance(out, str) and out
    # ... and the wall-time is always rendered with EXACTLY two decimals.
    m = re.search(r"wall-time: (\d+)\.(\d+)s", out)
    assert m, f"no 2-decimal wall-time token in {out!r}"
    assert len(m.group(2)) == 2, f"seconds not rendered to exactly 2 decimals: {out!r}"


# ==========================================================================
# Behavior 5 -- SUITE_SLOW_SECONDS is a module float (default 120.0) READ AT
# CALL TIME by postrelease_step (patch it -> the SLOW flag tracks the patch).
# ==========================================================================
def test_b5_constant_is_module_float_default_120():
    assert isinstance(foundry.SUITE_SLOW_SECONDS, float)
    assert foundry.SUITE_SLOW_SECONDS == 120.0


def test_b5_low_threshold_makes_modest_elapsed_log_slow(cfg, monkeypatch):
    result = foundry.PostReleaseResult(True, False, "green", test_seconds=4.2)
    monkeypatch.setattr(foundry, "verify_fresh_clone", make_verify(result))
    monkeypatch.setattr(foundry, "SUITE_SLOW_SECONDS", 1.0)  # patched threshold
    foundry.postrelease_step(cfg, 3, "sha")
    tls = _timing_lines(cfg.night_log)
    assert tls, "no `suite wall-time` line logged"
    assert any("SLOW" in ln for ln in tls), \
        f"4.2s not flagged SLOW under a 1.0s threshold: {tls!r}"
    # exact substring recomputed via the pure fn at the patched threshold
    assert any(foundry.suite_timing_line(4.2, 1.0) in ln for ln in tls)


def test_b5_high_threshold_makes_large_elapsed_log_not_slow(cfg, monkeypatch):
    result = foundry.PostReleaseResult(True, False, "green", test_seconds=4.2)
    monkeypatch.setattr(foundry, "verify_fresh_clone", make_verify(result))
    monkeypatch.setattr(foundry, "SUITE_SLOW_SECONDS", 1e9)  # huge threshold
    foundry.postrelease_step(cfg, 3, "sha")
    tls = _timing_lines(cfg.night_log)
    assert tls, "no `suite wall-time` line logged"
    assert not any("SLOW" in ln for ln in tls), \
        f"4.2s wrongly flagged SLOW under a 1e9 threshold: {tls!r}"


# ==========================================================================
# Behavior 6 -- PostReleaseResult.test_seconds is optional & INERT
# ==========================================================================
def test_b6_positional_construct_defaults_none():
    r = foundry.PostReleaseResult(True, True, "x")
    assert r.test_seconds is None


def test_b6_test_seconds_does_not_affect_sentinel_healthy_skipped():
    healthy = foundry.PostReleaseResult(True, False, "ok", test_seconds=999.0)
    assert healthy.sentinel == "POSTRELEASE: HEALTHY"
    assert healthy.healthy is True
    assert healthy.skipped_infra is False

    broken = foundry.PostReleaseResult(False, False, "boom", test_seconds=999.0)
    assert broken.sentinel == "POSTRELEASE: BROKEN"
    assert broken.healthy is False

    skipped = foundry.PostReleaseResult(True, True, "infra", test_seconds=999.0)
    assert skipped.sentinel == "POSTRELEASE: HEALTHY"
    assert skipped.skipped_infra is True


# ==========================================================================
# Behavior 7 -- timing wraps ONLY the fresh-clone test command (test-ran path)
# ==========================================================================
def test_b7_test_seconds_equals_clock_delta_on_test_ran_path(vcfg, tmp_path,
                                                             monkeypatch):
    D = 7.5
    mono, box = make_monotonic(100.0, 100.0 + D)
    monkeypatch.setattr(foundry, "run_cmd", make_run_cmd())  # all success
    monkeypatch.setattr(foundry, "cleanup_clone", lambda *a, **k: None)
    monkeypatch.setattr(foundry, "_monotonic", mono)
    r = foundry.verify_fresh_clone(vcfg, EXPECTED_SHA, str(tmp_path / "clone"))
    assert r.healthy is True
    assert isinstance(r.test_seconds, float)
    assert r.test_seconds == pytest.approx(D)
    assert r.test_seconds >= 0
    # the clock was consumed (brackets the measurement) on the test-ran path
    assert box["n"] >= 2, "clock seam not read to bracket the test command"


# ==========================================================================
# Behavior 8 -- NO timing on an infra-skip (test command never runs)
# ==========================================================================
def test_b8_no_timing_on_infra_skip(vcfg, tmp_path, monkeypatch):
    mono, box = make_monotonic(100.0, 200.0)
    monkeypatch.setattr(foundry, "run_cmd", make_run_cmd(clone_ok=False))  # infra fail
    monkeypatch.setattr(foundry, "cleanup_clone", lambda *a, **k: None)
    monkeypatch.setattr(foundry, "_monotonic", mono)
    r = foundry.verify_fresh_clone(vcfg, EXPECTED_SHA, str(tmp_path / "clone"))
    assert r.test_seconds is None
    assert r.healthy is True          # infra-skip stays HEALTHY (unchanged)
    assert r.skipped_infra is True
    # clock never consumed because the test command never ran
    assert box["n"] == 0, "clock read even though the test command never ran"


# ==========================================================================
# Behavior 9 -- NO timing when disabled, or when verify errors (treated infra)
# ==========================================================================
def test_b9_disabled_result_has_no_timing(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, postrelease_enabled=False)))
    assert cfg.postrelease_enabled is False
    r = foundry.postrelease_step(cfg, 3, "sha")
    assert r.test_seconds is None


def test_b9_verify_error_result_has_no_timing(cfg, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("clone blew up")
    monkeypatch.setattr(foundry, "verify_fresh_clone", _boom)
    r = foundry.postrelease_step(cfg, 3, "sha")   # must NOT raise
    assert r.skipped_infra is True                # treated as infra
    assert r.test_seconds is None


# ==========================================================================
# Behavior 10 -- postrelease_step LOGS the timing when test_seconds set, OMITS
# it (no `suite wall-time` line) when None.
# ==========================================================================
def test_b10_logs_timing_line_on_genuine_ship(cfg, monkeypatch):
    D = 7.5
    result = foundry.PostReleaseResult(True, False, "green", test_seconds=D)
    monkeypatch.setattr(foundry, "verify_fresh_clone", make_verify(result))
    foundry.postrelease_step(cfg, 3, "shipsha")
    expected = foundry.suite_timing_line(D, foundry.SUITE_SLOW_SECONDS)
    assert any(expected in ln for ln in _nonempty_lines(cfg.night_log)), \
        f"NIGHT_LOG missing the exact timing line {expected!r}"


def test_b10_omits_timing_line_on_infra_skip(cfg, monkeypatch):
    result = foundry.PostReleaseResult(True, True, "infra skip", test_seconds=None)
    monkeypatch.setattr(foundry, "verify_fresh_clone", make_verify(result))
    foundry.postrelease_step(cfg, 3, "sha")
    assert _timing_lines(cfg.night_log) == [], \
        "timing line logged even though test_seconds is None (infra-skip)"


def test_b10_omits_timing_line_when_disabled(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, postrelease_enabled=False)))
    foundry.postrelease_step(cfg, 3, "sha")
    assert _timing_lines(cfg.night_log) == [], \
        "timing line logged on the disabled path"


# ==========================================================================
# Behavior 11 -- artifact records `suite_seconds`; sentinel is STILL the last line
# ==========================================================================
def test_b11_artifact_records_seconds_and_keeps_sentinel_when_timed(cfg, monkeypatch):
    result = foundry.PostReleaseResult(True, False, "green", test_seconds=7.5)
    monkeypatch.setattr(foundry, "verify_fresh_clone", make_verify(result))
    foundry.postrelease_step(cfg, 3, "sha")
    art = _artifact(cfg, 3)
    txt = art.read_text()
    assert "suite_seconds" in txt, "artifact body missing `suite_seconds`"
    assert "7.5" in txt, "artifact does not record the measured seconds value"
    assert _last_nonempty_line(art) == "POSTRELEASE: HEALTHY", \
        "sentinel no longer the last non-empty line of the artifact"


def test_b11_artifact_records_seconds_when_none(cfg, monkeypatch):
    result = foundry.PostReleaseResult(True, True, "infra skip", test_seconds=None)
    monkeypatch.setattr(foundry, "verify_fresh_clone", make_verify(result))
    foundry.postrelease_step(cfg, 3, "sha")
    art = _artifact(cfg, 3)
    txt = art.read_text()
    assert "suite_seconds" in txt, "artifact body missing `suite_seconds` on the None path"
    low = txt.lower()
    assert ("n/a" in low) or ("none" in low), \
        "un-timed artifact does not record n/a / None for suite_seconds"
    assert _last_nonempty_line(art) == "POSTRELEASE: HEALTHY"


def test_b11_broken_result_keeps_broken_sentinel_last(cfg, monkeypatch):
    result = foundry.PostReleaseResult(False, False, "tests failed", test_seconds=7.5)
    monkeypatch.setattr(foundry, "verify_fresh_clone", make_verify(result))
    foundry.postrelease_step(cfg, 3, "sha")
    art = _artifact(cfg, 3)
    assert "suite_seconds" in art.read_text()
    assert _last_nonempty_line(art) == "POSTRELEASE: BROKEN"


# ==========================================================================
# Behavior 12 -- additive & OFF the control path
# ==========================================================================
NEW_SYMBOLS = ["suite_timing_line", "SUITE_SLOW_SECONDS", "_monotonic", "test_seconds"]
CONTROL_PATH_FNS = ["build_prompt", "run_stage", "run_iteration", "run_continuous"]


def test_b12_both_modules_import():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        capture_output=True, text=True,
        cwd=str(pathlib.Path(__file__).resolve().parents[1]))
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
    # positive control: the additivity assertions above are only meaningful if
    # the timing IS wired somewhere -- it must live in the post-release path.
    joined = "".join(
        inspect.getsource(getattr(foundry, name))
        for name in ("verify_fresh_clone", "postrelease_step",
                     "_write_postrelease_artifact")
        if hasattr(foundry, name))
    assert "test_seconds" in joined, \
        "test_seconds not referenced anywhere in the post-release path"


def test_b12_postrelease_sentinels_unchanged():
    assert foundry.PostReleaseResult(True, False, "x").sentinel == "POSTRELEASE: HEALTHY"
    assert foundry.PostReleaseResult(False, False, "x").sentinel == "POSTRELEASE: BROKEN"
