"""Iteration 524 -- BLACK-BOX behavior tests: one shared, total failing-line predicate
`failure_summary_line(line)` learns vitest ` FAIL  ...` and TAP `not ok N - ...` lines
(number stripped), and both extractors (`test_failure_lines`, `failing_summary_set`)
feed through it, so the preship parent leg and post-release `failures` see non-pytest
failures.

Spec under test: products/_platform/state/iter-524/pm.md, Expected Behaviors 1-13.

ISOLATION HONORED: written from `pm.md`, the repo's own `tests/` conventions (chiefly
tests/test_iter510_behavior.py and tests/test_iter517_behavior.py) and the product's
RUNTIME surface (public names, signatures) ONLY.  No implementation source, no
engineer / reviewer note and no `git diff` output was read.

OFFLINE: literal fixtures, scripted `run_cmd` / `cleanup_clone` / `rerun_suite_at_parent`
seams set by BARE module name; no real git, subprocess, node or vitest binary.
FRESH-CLONE SAFE: every fixture lives in this module or under `tmp_path`.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

SHA = "b" * 40
PARENT = "a" * 40

V1 = " FAIL  test/a.test.ts > suite one > fails here"
V2 = " FAIL  test/a.test.ts > top level fail"
V3 = " FAIL  test/b.test.ts [ test/b.test.ts ]"
X1 = "   × suite one > fails here 3ms"
X2 = "   × top level fail 0ms"
KEPT = ("FAIL  test/a.test.ts > suite one > fails here",
        "FAIL  test/a.test.ts > top level fail",
        "FAIL  test/b.test.ts [ test/b.test.ts ]")


def _vitest(x1="3ms", x2="0ms", drop=None):
    lines = [
        "",
        " RUN  v2.1.9 /tmp/proj",
        "",
        "   × suite one > fails here " + x1,
        "   × top level fail " + x2,
        " ❯ test/a.test.ts (2 tests | 2 failed)",
        "",
        "⎯⎯⎯⎯⎯⎯ Failed Tests 2 ⎯⎯⎯⎯⎯⎯⎯",
        "",
        V1,
        "AssertionError: expected 1 to be 2",
        V2,
        "AssertionError: expected 3 to be 4",
        V3,
        "Error: Failed to load url",
        "",
        " Test Files  2 failed (2)",
        "      Tests  2 failed (2)",
    ]
    if drop is not None:
        lines.remove(drop)
    return "\n".join(lines) + "\n"


VITEST_FIXTURE = "\n".join([V1, V2, V3, X1, X2]) + "\n"
VITEST_OUT = _vitest()


def _tap(n):
    return "\n".join(["TAP version 13", "ok 1 - node good", "not ok %d - x" % n,
                      "  ---", "  ...", "1..2", "# fail 1"]) + "\n"


# ==========================================================================
# Behavior 1 -- module-level, total, str|None
# ==========================================================================
TOTAL_INPUTS = ["", " ", "\n", "\t\t", "not ok", "FAIL ", "FAILED ", "ERROR ",
                "not ok 99999999999999999999 - big", "×", "❯", "\x00\x01", "a" * 10000,
                "not ok\tx", "  FAIL\t", "ok", "FAIL  " + "y" * 5000]


@pytest.mark.parametrize("line", TOTAL_INPUTS)
def test_b1_total_returns_str_or_none(line):
    got = foundry.failure_summary_line(line)
    assert got is None or isinstance(got, str)


def test_b1_module_level_function():
    f = foundry.failure_summary_line
    assert callable(f) and f.__module__ == "foundry"
    assert foundry.failure_summary_line("") is None


# ==========================================================================
# Behavior 2 -- pytest unchanged
# ==========================================================================
@pytest.mark.parametrize("line,want", [
    ("FAILED tests/t.py::test_a - assert 0  ", "FAILED tests/t.py::test_a - assert 0"),
    ("   FAILED tests/t.py::test_b", "FAILED tests/t.py::test_b"),
    ("ERROR tests/x.py - ImportError", "ERROR tests/x.py - ImportError"),
    ("\tERROR tests/x.py::t  \n", "ERROR tests/x.py::t"),
])
def test_b2_pytest_lines_stripped(line, want):
    assert foundry.failure_summary_line(line) == want


# ==========================================================================
# Behavior 3 -- vitest FAIL
# ==========================================================================
@pytest.mark.parametrize("line,want", list(zip((V1, V2, V3), KEPT)) + [
    ("FAIL  x > y   ", "FAIL  x > y"),
])
def test_b3_vitest_fail_lines_kept_double_space_preserved(line, want):
    got = foundry.failure_summary_line(line)
    assert got == want
    if "  " in want:
        assert "FAIL  " in got


# ==========================================================================
# Behavior 4 -- TAP not ok, number stripped
# ==========================================================================
@pytest.mark.parametrize("line,want", [
    ("not ok 2 - node bad", "not ok - node bad"),
    ("    not ok 1 - nested sub", "not ok - nested sub"),
    ("not ok 17", "not ok"),
    ("not ok - no number", "not ok - no number"),
    ("not ok", "not ok"),
])
def test_b4_tap_number_stripped(line, want):
    assert foundry.failure_summary_line(line) == want


def test_b4_tap_numbers_only_difference_equal():
    assert (foundry.failure_summary_line("not ok 2 - same")
            == foundry.failure_summary_line("not ok 41 - same")
            == "not ok - same")


# ==========================================================================
# Behavior 5 -- non-matches
# ==========================================================================
@pytest.mark.parametrize("line", [
    X1, X2, "ok 1 - node good", "=== FAILURES ===", "1 failed, 2 passed",
    " Test Files  1 failed (2)", " ❯ test/a.test.ts (2 tests | 2 failed)", "FAIL",
    "fail  x > y", "# fail 1", "not okay", "",
])
def test_b5_non_matches_return_none(line):
    assert foundry.failure_summary_line(line) is None


# ==========================================================================
# Behavior 6 -- failing_summary_set on vitest
# ==========================================================================
def test_b6_vitest_set_exact():
    assert foundry.failing_summary_set(VITEST_FIXTURE) == frozenset(KEPT)


def test_b6_vitest_set_from_realistic_output():
    assert foundry.failing_summary_set(VITEST_OUT) == frozenset(KEPT)


# ==========================================================================
# Behavior 7 -- drift oracle, vitest
# ==========================================================================
def test_b7_timing_only_difference_is_drift():
    a = _vitest("3ms", "0ms")
    b = _vitest("41ms", "9ms")
    assert a != b
    assert foundry.failing_summary_set(a) == foundry.failing_summary_set(b)
    assert foundry.preship_parent_drift(a, b) is True


def test_b7_fixture_level_timing_only_difference_is_drift():
    a = VITEST_FIXTURE
    b = VITEST_FIXTURE.replace("3ms", "41ms").replace("0ms", "9ms")
    assert foundry.preship_parent_drift(a, b) is True


@pytest.mark.parametrize("drop", [V1, V2, V3])
def test_b7_losing_one_fail_line_not_drift(drop):
    assert foundry.preship_parent_drift(_vitest(), _vitest("41ms", "9ms", drop=drop)) is False


# ==========================================================================
# Behavior 8 -- drift oracle, TAP
# ==========================================================================
def test_b8_tap_renumbered_is_drift():
    assert foundry.preship_parent_drift(_tap(2), _tap(5)) is True


def test_b8_tap_different_description_not_drift():
    assert foundry.preship_parent_drift(_tap(2), _tap(2).replace("- x", "- z")) is False


# ==========================================================================
# Behavior 9 -- test_failure_lines on vitest, contract unchanged
# ==========================================================================
def test_b9_vitest_lines_in_order_tuple():
    got = foundry.test_failure_lines(VITEST_FIXTURE)
    assert isinstance(got, tuple) and got == KEPT
    assert foundry.test_failure_lines(VITEST_OUT) == KEPT


def test_b9_cap_applies_to_vitest_line():
    long = " FAIL  test/a.test.ts > " + "z" * 600
    got = foundry.test_failure_lines(long + "\n")
    assert len(got) == 1
    assert len(got[0]) <= foundry.TEST_FAILURE_LINE_MAX
    assert got[0].startswith("FAIL  test/a.test.ts > zzz")


def test_b9_limit_with_more_marker_on_vitest():
    out = "\n".join(" FAIL  t/f.test.ts > case %02d" % i for i in range(7)) + "\n"
    got = foundry.test_failure_lines(out, limit=3)
    assert got[:3] == tuple("FAIL  t/f.test.ts > case %02d" % i for i in range(3))
    assert len(got) == 4 and got[3] == "... and 4 more"


@pytest.mark.parametrize("empty", [None, ""])
def test_b9_and_b13_empty_inputs(empty):
    assert foundry.test_failure_lines(empty) == ()
    assert foundry.failing_summary_set(empty) == frozenset()


# ==========================================================================
# Behavior 10 -- mixed output
# ==========================================================================
MIXED = "\n".join(["collected 3", "FAILED tests/t.py::test_a - boom", "noise",
                   " FAIL  test/a.test.ts > top level fail", "ok 1 - fine",
                   "not ok 3 - t", "done"]) + "\n"
MIXED_KEPT = ("FAILED tests/t.py::test_a - boom", "FAIL  test/a.test.ts > top level fail",
              "not ok - t")


def test_b10_mixed_lines_in_order():
    assert foundry.test_failure_lines(MIXED) == MIXED_KEPT


def test_b10_mixed_set_holds_all_three():
    assert foundry.failing_summary_set(MIXED) == frozenset(MIXED_KEPT)


# ==========================================================================
# Behavior 11 -- parent leg downgrades a vitest BROKEN to INCOMPLETE
# ==========================================================================
def _cfg(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    return foundry.ProductConfig(name="demo", repo=str(repo), allowed_push_repo="demo",
                                 work_root=str(work), test_cmd="sh -c 'npm test --silent'",
                                 setup_cmd="npm ci")


def _script_parent(monkeypatch, parent_out):
    calls = {"cmd": [], "rerun": []}

    def fake_run_cmd(args, cwd=None, timeout=None, **kw):
        argv = [str(a) for a in args]
        calls["cmd"].append(argv)
        if "rev-parse" in argv and any(a.endswith("^") for a in argv):
            return foundry.CmdResult(True, PARENT + "\n")
        if "rev-parse" in argv:
            return foundry.CmdResult(True, SHA + "\n")
        return foundry.CmdResult(True, "")

    def fake_rerun(cfg, parent_sha, clone_dir):
        calls["rerun"].append(parent_sha)
        return parent_out, "/opt/node/bin/node"

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(foundry, "cleanup_clone", lambda *a, **k: None)
    monkeypatch.setattr(foundry, "rerun_suite_at_parent", fake_rerun)
    return calls


def _broken(out):
    return foundry.PreshipResult(verified=False, incomplete=False, detail="d-baseline",
                                 test_seconds=4.0, suite_output=out)


def test_b11_vitest_broken_becomes_incomplete(monkeypatch, tmp_path):
    base = _broken(_vitest("3ms", "0ms"))
    assert base.exit_code == 1
    calls = _script_parent(monkeypatch, _vitest("41ms", "9ms"))
    got = foundry._preship_parent_leg(_cfg(tmp_path), SHA, base)
    assert calls["rerun"] == [PARENT]
    assert got.exit_code == 2 and got.incomplete is True and got.verified is False
    assert "IDENTICAL set of 3 test(s)" in got.detail, got.detail
    assert "FAIL  test/a.test.ts > top level fail" in got.detail


def test_b11_vitest_differing_parent_stays_broken(monkeypatch, tmp_path):
    base = _broken(_vitest())
    _script_parent(monkeypatch, _vitest("41ms", "9ms", drop=V2))
    got = foundry._preship_parent_leg(_cfg(tmp_path), SHA, base)
    assert got.exit_code == 1 and got.detail == "d-baseline"


def test_b11_preship_cli_json_exit_2_for_vitest(monkeypatch, tmp_path):
    import contextlib
    import io
    _script_parent(monkeypatch, _vitest("41ms", "9ms"))
    base = foundry.PreshipResult(False, False, "d-baseline", 4.0,
                                 suite_output=_vitest(), verified_sha=SHA)
    monkeypatch.setattr(foundry, "verify_local_clone", lambda c, s, d: base)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.preship_cli(_cfg(tmp_path), as_json=True)
    d = json.loads(buf.getvalue())
    assert rc == 2 and d["exit_code"] == 2 and d["incomplete"] is True
    assert "IDENTICAL set of 3 test(s)" in d["detail"]


# ==========================================================================
# Behavior 12 -- post-release failures name vitest tests
# ==========================================================================
SETUP_CMD = "npm ci"
TEST_CMD = "npm test"


def _pr_cfg(tmp_path):
    data = {"name": "demo", "repo": "{FOUNDRY}/products/demo/repo",
            "allowed_push_repo": "demo", "vision": "{FOUNDRY}/products/demo/VISION.md",
            "work_root": str(tmp_path / "work"), "setup_cmd": SETUP_CMD,
            "test_cmd": TEST_CMD}
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return foundry.load_config(str(p))


def test_b12_postrelease_failures_carry_vitest_names(monkeypatch, tmp_path):
    def fake_run_cmd(args, cwd=None, timeout=None, **k):
        a = [str(x) for x in args]
        if "remote" in a and "get-url" in a:
            return foundry.CmdResult(True, "https://example.test/r.git")
        if "clone" in a:
            return foundry.CmdResult(True, "cloned")
        if "rev-parse" in a:
            return foundry.CmdResult(True, SHA)
        if a == SETUP_CMD.split():
            return foundry.CmdResult(True, "setup")
        if a == TEST_CMD.split():
            return foundry.CmdResult(False, VITEST_FIXTURE)
        return foundry.CmdResult(False, "UNEXPECTED:" + " ".join(a))

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(foundry, "cleanup_clone", lambda *a, **k: None)
    r = foundry.verify_fresh_clone(_pr_cfg(tmp_path), SHA, str(tmp_path / "clone"))
    assert r.healthy is False and r.skipped_infra is False
    assert r.sentinel == "POSTRELEASE: BROKEN"
    assert "FAIL  test/a.test.ts > top level fail" in r.failures
    assert tuple(r.failures) == KEPT


# ==========================================================================
# Behavior 13 -- pytest byte-identical
# ==========================================================================
PYTEST_OUT = "\n".join(["=== short test summary info ===",
                        "FAILED tests/a.py::t1 - AssertionError  ",
                        "  ERROR tests/b.py - ImportError",
                        "=== 1 failed, 1 error in 0.1s ==="]) + "\n"


def test_b13_pytest_extractors_unchanged():
    assert foundry.test_failure_lines(PYTEST_OUT) == (
        "FAILED tests/a.py::t1 - AssertionError", "ERROR tests/b.py - ImportError")
    assert foundry.failing_summary_set(PYTEST_OUT) == frozenset(
        {"FAILED tests/a.py::t1 - AssertionError", "ERROR tests/b.py - ImportError"})
