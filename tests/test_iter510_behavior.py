"""Black-box behaviour tests for iter 510 -- post-release names the failing tests.

ISOLATION: written from the iter-510 PM spec (Expected Behaviors 1-9), the
existing tests under tests/ (conventions for the run_cmd / cleanup_clone /
verify_fresh_clone seams were mirrored from test_iter02/test_iter03), and
runtime introspection of public signatures only. The implementation source of
foundry.py, the engineer/reviewer notes and `git diff` were NOT read.

Every external effect goes through module-level seams (`foundry.run_cmd`,
`foundry.cleanup_clone`, `foundry.verify_fresh_clone`): no real subprocess,
git clone or network.
"""
import dataclasses
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402

SETUP_CMD = "do-setup --x"
TEST_CMD = "do-test --all"
SHA = "abcdef123456"
FAIL_LINE = "FAILED tests/x.py::test_y - boom"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    data = {
        "name": "demo",
        "repo": "{FOUNDRY}/products/demo/repo",
        "allowed_push_repo": "demo",
        "vision": "{FOUNDRY}/products/demo/VISION.md",
        "work_root": str(tmp_path / "work"),
        "setup_cmd": SETUP_CMD,
        "test_cmd": TEST_CMD,
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def cfg(tmp_path):
    return foundry.load_config(str(_write_cfg(tmp_path)))


def make_run_cmd(recorder, *, remote_ok=True, clone_ok=True, setup_ok=True,
                 test_ok=True, test_out="1 passed in 0.1s", cloned_sha=SHA):
    def _run_cmd(args, cwd=None, timeout=None, **k):
        a = list(args)
        recorder.append(a)
        if "remote" in a and "get-url" in a:
            return foundry.CmdResult(remote_ok, "https://example.test/r.git"
                                     if remote_ok else "no-remote")
        if "clone" in a:
            return foundry.CmdResult(clone_ok, "cloned" if clone_ok else "nope")
        if "rev-parse" in a:
            return foundry.CmdResult(True, cloned_sha)
        if a == SETUP_CMD.split():
            return foundry.CmdResult(setup_ok, "setup")
        if a == TEST_CMD.split():
            return foundry.CmdResult(test_ok, test_out)
        return foundry.CmdResult(False, "UNEXPECTED:" + " ".join(a))
    return _run_cmd


def _verify(cfg, tmp_path, monkeypatch, **kw):
    rec = []
    monkeypatch.setattr(foundry, "run_cmd", make_run_cmd(rec, **kw))
    monkeypatch.setattr(foundry, "cleanup_clone", lambda *a, **k: None)
    r = foundry.verify_fresh_clone(cfg, SHA, str(tmp_path / "clone"))
    return r, rec


def _verdict_tuple(r):
    return (r.healthy, r.skipped_infra, r.detail, r.sentinel)


def _last_nonempty(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _artifact_text(tmp_path, result, name="pr.md"):
    p = tmp_path / name
    foundry._write_postrelease_artifact(p, SHA, result)
    return p.read_text()


# ==========================================================================
# Behavior 1 -- extraction of FAILED / ERROR lines
# ==========================================================================
def test_b1_extracts_failed_and_error_lines():
    out = "x\nFAILED tests/a.py::t - assert 1 == 2\n  ERROR tests/b.py - ImportError\n"
    got = foundry.test_failure_lines(out)
    assert got == (
        "FAILED tests/a.py::t - assert 1 == 2",
        "ERROR tests/b.py - ImportError",
    )
    assert type(got) is tuple


def test_b1_input_order_and_strip_trailing():
    out = "ERROR e1  \nnoise\n\tFAILED f1 \t\nFAILED f2"
    assert foundry.test_failure_lines(out) == ("ERROR e1", "FAILED f1", "FAILED f2")


def test_b1_pure_same_input_same_output():
    out = "FAILED a\nERROR b\n"
    assert foundry.test_failure_lines(out) == foundry.test_failure_lines(out)
    assert out == "FAILED a\nERROR b\n"


# ==========================================================================
# Behavior 2 -- non-matching lines, None, "" and never raising
# ==========================================================================
@pytest.mark.parametrize("out", [
    "1 failed in 0.1s",
    "=== FAILURES ===",
    "FAILED",
    "error: something",
    "Failed to fetch: http://x",
    "failed tests/a.py::t",
    "Error tests/a.py",
    "FAILEDtests/a.py",
    "",
    None,
])
def test_b2_non_matching_gives_empty(out):
    assert foundry.test_failure_lines(out) == ()


def test_b2_mixed_noise_only_keeps_real_lines():
    out = ("=== FAILURES ===\nFAILED\n1 failed in 0.1s\n"
           "Failed to fetch: http://x\nFAILED tests/z.py::q - x\n")
    assert foundry.test_failure_lines(out) == ("FAILED tests/z.py::q - x",)


@pytest.mark.parametrize("out", ["\x00\x01", "\r\n\r\n", "FAILED \n", "  \n  ERROR ",
                                 "\u2603 FAILED x", "FAILED x\r\nERROR y\r\n"])
def test_b2_never_raises_returns_tuple_of_str(out):
    got = foundry.test_failure_lines(out)
    assert isinstance(got, tuple)
    assert all(isinstance(s, str) for s in got)


# ==========================================================================
# Behavior 3 -- cap with "... and N more"
# ==========================================================================
def _n_lines(n):
    return "\n".join(f"FAILED tests/t.py::t{i}" for i in range(n)) + "\n"


def test_b3_thirteen_matches_capped_to_eleven():
    got = foundry.test_failure_lines(_n_lines(13))
    assert len(got) == 11
    assert got[:10] == tuple(f"FAILED tests/t.py::t{i}" for i in range(10))
    assert got[-1] == "... and 3 more"


def test_b3_default_limit_is_ten():
    assert foundry.test_failure_lines(_n_lines(13)) == \
        foundry.test_failure_lines(_n_lines(13), limit=10)


def test_b3_exactly_limit_has_no_more_marker():
    got = foundry.test_failure_lines(_n_lines(10))
    assert len(got) == 10
    assert not any(s.startswith("... and") for s in got)


def test_b3_custom_limit():
    got = foundry.test_failure_lines(_n_lines(5), limit=2)
    assert got == ("FAILED tests/t.py::t0", "FAILED tests/t.py::t1", "... and 3 more")


def test_b3_eleven_matches_one_more():
    got = foundry.test_failure_lines(_n_lines(11))
    assert len(got) == 11 and got[-1] == "... and 1 more"


# ==========================================================================
# Behavior 4 -- per-line 300-char cut
# ==========================================================================
def test_b4_long_line_cut_to_300():
    line = "FAILED tests/a.py::t - " + "x" * 1000
    got = foundry.test_failure_lines(line)
    assert got == (line[:300],)
    assert len(got[0]) == 300


def test_b4_line_of_exactly_300_kept_whole():
    line = "ERROR " + "y" * 294
    assert len(line) == 300
    assert foundry.test_failure_lines(line) == (line,)


# ==========================================================================
# Behavior 5 -- PostReleaseResult.failures field, inert to the verdict
# ==========================================================================
def test_b5_field_defaults_to_empty_tuple():
    names = [f.name for f in dataclasses.fields(foundry.PostReleaseResult)]
    assert "failures" in names
    r = foundry.PostReleaseResult(False, False, "d")
    assert r.failures == ()
    r2 = foundry.PostReleaseResult(True, False, "d", 1.5)
    assert r2.test_seconds == 1.5 and r2.failures == ()
    r3 = foundry.PostReleaseResult(healthy=True, skipped_infra=True, detail="d")
    assert r3.failures == ()


@pytest.mark.parametrize("healthy,skipped", [(True, False), (True, True), (False, False)])
def test_b5_failures_inert_to_verdict(healthy, skipped):
    a = foundry.PostReleaseResult(healthy, skipped, "d")
    b = foundry.PostReleaseResult(healthy, skipped, "d", failures=(FAIL_LINE, "ERROR z"))
    assert b.failures == (FAIL_LINE, "ERROR z")
    assert (a.healthy, a.skipped_infra, a.sentinel) == (b.healthy, b.skipped_infra, b.sentinel)


# ==========================================================================
# Behavior 6 -- verify_fresh_clone threads failures only from a failed test cmd
# ==========================================================================
def test_b6_failed_tests_threaded(cfg, tmp_path, monkeypatch):
    out = f"collected 3\n{FAIL_LINE}\nERROR tests/b.py - ImportError\n1 failed in 1s\n"
    r, _ = _verify(cfg, tmp_path, monkeypatch, test_ok=False, test_out=out)
    assert r.healthy is False and r.skipped_infra is False
    assert r.sentinel == "POSTRELEASE: BROKEN"
    assert r.failures == foundry.test_failure_lines(out)
    assert r.failures == (FAIL_LINE, "ERROR tests/b.py - ImportError")


def test_b6_failed_without_ids_gives_empty(cfg, tmp_path, monkeypatch):
    r, _ = _verify(cfg, tmp_path, monkeypatch, test_ok=False,
                   test_out="Failed to fetch: http://x\n")
    assert r.sentinel == "POSTRELEASE: BROKEN"
    assert r.failures == ()


def test_b6_passing_suite_ignores_failed_text(cfg, tmp_path, monkeypatch):
    # .ok True wins even if the out text happens to contain a FAILED line
    r, _ = _verify(cfg, tmp_path, monkeypatch, test_ok=True,
                   test_out=f"{FAIL_LINE}\n1 passed\n")
    assert r.sentinel == "POSTRELEASE: HEALTHY" and r.skipped_infra is False
    assert r.failures == ()


@pytest.mark.parametrize("kw", [dict(clone_ok=False), dict(setup_ok=False),
                                dict(remote_ok=False)])
def test_b6_infra_skip_has_no_failures(cfg, tmp_path, monkeypatch, kw):
    r, _ = _verify(cfg, tmp_path, monkeypatch, test_ok=False,
                   test_out=FAIL_LINE + "\n", **kw)
    assert r.skipped_infra is True
    assert r.failures == ()


def test_b6_verify_error_has_no_failures(cfg, tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("seam exploded")
    monkeypatch.setattr(foundry, "run_cmd", _boom)
    monkeypatch.setattr(foundry, "cleanup_clone", lambda *a, **k: None)
    r = foundry.verify_fresh_clone(cfg, SHA, str(tmp_path / "clone"))
    assert r.skipped_infra is True
    assert r.failures == ()


def test_b6_failure_text_does_not_change_verdict_or_calls(cfg, tmp_path, monkeypatch):
    r_ids, rec_ids = _verify(cfg, tmp_path, monkeypatch, test_ok=False,
                             test_out=_n_lines(13))
    r_none, rec_none = _verify(cfg, tmp_path, monkeypatch, test_ok=False,
                               test_out="nothing useful")
    assert len(r_ids.failures) == 11 and r_none.failures == ()
    assert _verdict_tuple(r_ids) == _verdict_tuple(r_none)
    assert rec_ids == rec_none
    assert [TEST_CMD.split()] == [c for c in rec_ids if c == TEST_CMD.split()]


# ==========================================================================
# Behavior 7 -- postrelease.md artifact
# ==========================================================================
def _block(header, entries):
    return [header] + [f"  - {e}" for e in entries]


def test_b7_artifact_bullets_after_detail(tmp_path):
    fails = (FAIL_LINE, "ERROR tests/b.py - ImportError")
    base = foundry.PostReleaseResult(False, False, "fresh-clone test suite failed", 12.5)
    with_f = dataclasses.replace(base, failures=fails)
    plain = _artifact_text(tmp_path, base, "a.md")
    rich = _artifact_text(tmp_path, with_f, "b.md")

    plain_lines = plain.splitlines()
    rich_lines = rich.splitlines()
    di = [i for i, ln in enumerate(rich_lines) if ln.startswith("- detail: ")]
    assert len(di) == 1
    i = di[0]
    assert rich_lines[i + 1:i + 1 + 3] == _block("- failing tests:", fails)
    # exactly the block was inserted; everything else identical
    assert rich_lines[:i + 1] + rich_lines[i + 4:] == plain_lines
    assert "failing tests" not in plain


def test_b7_sentinel_last_and_parsers_unchanged(tmp_path):
    fails = foundry.test_failure_lines(_n_lines(13))
    base = foundry.PostReleaseResult(False, False, "fresh-clone test suite failed", 42.25)
    plain = _artifact_text(tmp_path, base, "a.md")
    rich = _artifact_text(tmp_path, dataclasses.replace(base, failures=fails), "b.md")
    assert _last_nonempty(rich) == _last_nonempty(plain) == "POSTRELEASE: BROKEN"
    assert foundry.parse_postrelease_verdict(rich) == foundry.parse_postrelease_verdict(plain)
    assert foundry.parse_postrelease_verdict(rich) is not None
    assert foundry.parse_suite_seconds(rich) == foundry.parse_suite_seconds(plain)
    assert foundry.parse_suite_seconds(plain) == pytest.approx(42.25)
    assert "  - ... and 3 more" in rich.splitlines()


@pytest.mark.parametrize("healthy,skipped", [(True, False), (True, True), (False, False)])
def test_b7_empty_failures_identical_to_default(tmp_path, healthy, skipped):
    a = foundry.PostReleaseResult(healthy, skipped, "d", 3.0)
    b = foundry.PostReleaseResult(healthy, skipped, "d", 3.0, ())
    ta, tb = _artifact_text(tmp_path, a, "a.md"), _artifact_text(tmp_path, b, "b.md")
    assert ta == tb
    assert "failing tests" not in ta


# ==========================================================================
# Behavior 8 -- HOTFIX_NEEDED.md flag
# ==========================================================================
def _flag_text(cfg, *args, **kw):
    foundry.write_hotfix_flag(cfg, *args, **kw)
    return foundry.hotfix_flag_path(cfg).read_text()


def test_b8_flag_bullets_after_evidence(cfg):
    fails = (FAIL_LINE, "ERROR tests/b.py - ImportError")
    plain = _flag_text(cfg, "sha999", "fresh-clone test suite failed")
    rich = _flag_text(cfg, "sha999", "fresh-clone test suite failed", fails)
    rl = rich.splitlines()
    ei = [i for i, ln in enumerate(rl) if ln == "- Evidence: fresh-clone test suite failed"]
    assert len(ei) == 1
    i = ei[0]
    assert rl[i + 1:i + 4] == _block("- Failing tests:", fails)
    assert rl[:i + 1] + rl[i + 4:] == plain.splitlines()
    assert "Failing tests" not in plain


def test_b8_keyword_and_empty_forms_identical(cfg):
    three = _flag_text(cfg, "sha1", "det")
    empty_pos = _flag_text(cfg, "sha1", "det", ())
    empty_kw = _flag_text(cfg, "sha1", "det", failures=())
    assert three == empty_pos == empty_kw
    kw = _flag_text(cfg, "sha1", "det", failures=("ERROR q",))
    assert "  - ERROR q" in kw.splitlines()
    assert "- Failing tests:" in kw.splitlines()


# ==========================================================================
# Behavior 9 -- postrelease_step threads failures end to end
# ==========================================================================
def test_b9_broken_step_writes_line_to_flag_and_artifact(cfg, monkeypatch):
    rec = []
    out = f"collected 1\n{FAIL_LINE}\n1 failed in 1s\n"
    monkeypatch.setattr(foundry, "run_cmd", make_run_cmd(rec, test_ok=False, test_out=out))
    monkeypatch.setattr(foundry, "cleanup_clone", lambda *a, **k: None)
    ret = foundry.postrelease_step(cfg, 7, SHA)
    assert ret.sentinel == "POSTRELEASE: BROKEN"
    assert ret.failures == (FAIL_LINE,)
    flag = foundry.hotfix_flag_path(cfg)
    assert flag.exists()
    assert f"  - {FAIL_LINE}" in flag.read_text().splitlines()
    art = cfg.state / "iter-07" / "postrelease.md"
    atext = art.read_text()
    assert f"  - {FAIL_LINE}" in atext.splitlines()
    assert _last_nonempty(atext) == "POSTRELEASE: BROKEN"


def test_b9_spy_flag_receives_result_failures(cfg, monkeypatch):
    fails = (FAIL_LINE, "ERROR e")
    res = foundry.PostReleaseResult(False, False, "fresh-clone test suite failed", None, fails)
    monkeypatch.setattr(foundry, "verify_fresh_clone", lambda *a, **k: res)
    calls = []
    real = foundry.write_hotfix_flag

    def _spy(*a, **k):
        calls.append((a, k))
        return real(*a, **k)
    monkeypatch.setattr(foundry, "write_hotfix_flag", _spy)
    foundry.postrelease_step(cfg, 8, SHA)
    assert len(calls) == 1
    a, k = calls[0]
    passed = k.get("failures", a[3] if len(a) > 3 else ())
    assert tuple(passed) == fails


def test_b9_lifecycle_healthy_clears_infra_keeps(cfg, monkeypatch):
    foundry.write_hotfix_flag(cfg, "old", "old detail", ("ERROR x",))
    flag = foundry.hotfix_flag_path(cfg)
    assert flag.exists()
    before = flag.read_text()
    monkeypatch.setattr(foundry, "verify_fresh_clone",
                        lambda *a, **k: foundry.PostReleaseResult(True, True, "clone failed"))
    foundry.postrelease_step(cfg, 9, SHA)
    assert flag.exists() and flag.read_text() == before
    monkeypatch.setattr(foundry, "verify_fresh_clone",
                        lambda *a, **k: foundry.PostReleaseResult(True, False, "ok", 1.0))
    foundry.postrelease_step(cfg, 10, SHA)
    assert not flag.exists()


def test_b9_broken_without_ids_flag_has_no_failing_block(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "run_cmd",
                        make_run_cmd([], test_ok=False, test_out="Failed to fetch: x"))
    monkeypatch.setattr(foundry, "cleanup_clone", lambda *a, **k: None)
    foundry.postrelease_step(cfg, 11, SHA)
    txt = foundry.hotfix_flag_path(cfg).read_text()
    assert "Failing tests" not in txt
    assert SHA in txt
