"""Black-box behaviour tests for iter 554 -- OPERATOR 2026-11-21c: a tsc failure
names itself in the failing-test lists (`test_failure_lines`), display only; the
gate oracle (`failure_summary_line` / `failing_summary_set` /
`preship_parent_drift`) is unchanged.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-554 PM spec's Expected
Behaviors (1-8), existing tests under ``tests/`` (conventions of
test_iter525/551/552), and the product's public runtime surface.  The
implementation source, engineer/reviewer notes and ``git diff`` were NOT read.

OFFLINE / FRESH-CLONE SAFE: literal fixtures and tmp_path only; consumer arms
script ``run_cmd`` and trip on any real subprocess; no HEAD baseline, no sha,
no wall-clock bound.
"""
import contextlib
import io
import json
import pathlib
import shlex
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

TSC = "test/test_iter111_behavior.test.ts(138,61): error TS2769: No overload matches this call."
PY_LINE = "FAILED tests/a.py::t - x"
TSC2 = "src/a.ts(1,2): error TS2322: bad"
VITEST_RAW = " FAIL  test/x.test.ts > y"
VITEST = "FAIL  test/x.test.ts > y"
MIX = PY_LINE + "\n" + TSC2 + "\n" + VITEST_RAW + "\n"
NEAR_MISSES = [
    "src/a.ts:1:2 - error TS2322: pretty",
    "src/a.ts(1,2): warning TS6133: w",
    "Found 2 errors.",
    "error TS2322: no location",
    "src/a.ts(1,2): error TS: no number",
    "src/a.ts(1): error TS2322: no col",
    "  Overload 1 of 2, '(a: string)': ...",
]
TSC_ONLY_OUT = (
    "> pkg@1.0.0 typecheck\n> tsc --noEmit\n\n"
    + TSC + "\n"
    "  Overload 1 of 2, '(a: string)': ...\n"
    "Found 1 error in test/test_iter111_behavior.test.ts:138\n"
)
SHA = "b" * 40
PARENT = "a" * 40
CLAUSE = "; BROKEN -- no failing names parsed from "


# ==========================================================================
# B1 -- a lone tsc line is kept, stripped
# ==========================================================================
def test_b1_tsc_line_kept():
    assert foundry.test_failure_lines(TSC + "\n") == (TSC,)


def test_b1_leading_whitespace_is_stripped():
    assert foundry.test_failure_lines("   " + TSC + "\n") == (TSC,)


def test_b1_tsc_inside_noisy_output():
    assert foundry.test_failure_lines(TSC_ONLY_OUT) == (TSC,)


# ==========================================================================
# B2 -- mixed output keeps all three shapes in input order
# ==========================================================================
def test_b2_mixed_input_order():
    assert foundry.test_failure_lines(MIX) == (PY_LINE, TSC2, VITEST)


def test_b2_reverse_order_follows_input():
    rev = VITEST_RAW + "\n" + TSC2 + "\n" + PY_LINE + "\n"
    assert foundry.test_failure_lines(rev) == (VITEST, TSC2, PY_LINE)


# ==========================================================================
# B3 -- cap
# ==========================================================================
def _twelve():
    return ["src/f%d.ts(1,1): error TS1005: x" % i for i in range(12)]


def test_b3_default_limit_caps_at_ten():
    lines = _twelve()
    got = foundry.test_failure_lines("\n".join(lines) + "\n")
    assert len(got) == 11
    assert got == tuple(lines[:10]) + ("... and 2 more",)


def test_b3_limit_three():
    lines = _twelve()
    got = foundry.test_failure_lines("\n".join(lines) + "\n", limit=3)
    assert len(got) == 4
    assert got == tuple(lines[:3]) + ("... and 9 more",)


# ==========================================================================
# B4 -- 300-char cut
# ==========================================================================
def test_b4_long_tsc_line_cut_to_max():
    assert foundry.TEST_FAILURE_LINE_MAX == 300
    head = "src/a.ts(1,2): error TS2769: "
    line = head + "x" * (400 - len(head))
    assert len(line) == 400
    got = foundry.test_failure_lines(line + "\n")
    assert got == (line[:300],)
    assert len(got[0]) == 300


# ==========================================================================
# B5 -- near-misses are not kept
# ==========================================================================
@pytest.mark.parametrize("line", NEAR_MISSES)
def test_b5_near_miss_not_kept(line):
    assert foundry.test_failure_lines(line + "\n") == ()


# ==========================================================================
# B6 -- the gate oracle is unchanged
# ==========================================================================
@pytest.mark.parametrize("line", [TSC, "   " + TSC, TSC2,
                                  "src/a.ts(1,2): error TS2769: " + "x" * 371]
                         + _twelve() + NEAR_MISSES)
def test_b6_oracle_predicate_ignores_tsc(line):
    assert foundry.failure_summary_line(line) is None


def test_b6_oracle_predicate_still_keeps_runner_lines():
    assert foundry.failure_summary_line(PY_LINE) is not None
    assert foundry.failure_summary_line(VITEST_RAW) is not None


def test_b6_failing_summary_set_of_mix_has_no_tsc():
    assert foundry.failing_summary_set(MIX) == frozenset({PY_LINE, VITEST})


def test_b6_tsc_only_set_is_empty_and_no_drift():
    assert not foundry.failing_summary_set(TSC_ONLY_OUT)
    assert foundry.preship_parent_drift(TSC_ONLY_OUT, TSC_ONLY_OUT) is False


# ==========================================================================
# B7 -- non-tsc inputs unchanged (fixed literals, not a HEAD baseline)
# ==========================================================================
@pytest.mark.parametrize("out, want", [
    (None, ()),
    ("", ()),
    ("..F\nFAILED tests/a.py::t - x\nERROR tests/b.py - boom\n1 failed\n",
     ("FAILED tests/a.py::t - x", "ERROR tests/b.py - boom")),
    (" FAIL  test/x.test.ts > y\n Test Files  1 failed\n", ("FAIL  test/x.test.ts > y",)),
    ("TAP version 13\nok 1 - fine\nnot ok 2 - x\n", ("not ok - x",)),
    ("3 passed in 0.1s\n", ()),
])
def test_b7_non_tsc_outputs(out, want):
    assert foundry.test_failure_lines(out) == want


def test_b7_twelve_pytest_lines_limit_ten():
    lines = ["FAILED tests/t.py::test_%d - x" % i for i in range(12)]
    got = foundry.test_failure_lines("\n".join(lines) + "\n", limit=10)
    assert got == tuple(lines[:10]) + ("... and 2 more",)


@pytest.mark.parametrize("bad", [5, 10 ** 400, 3.5])
def test_b7_non_str_returns_empty(bad):
    assert foundry.test_failure_lines(bad) == ()


# ==========================================================================
# B8 -- consumers: commit-check, PreshipResult, _preship_parent_leg
# ==========================================================================
def _cfg(tmp_path, test="testcmd -q", setup="setupcmd"):
    wr = tmp_path / "wr"
    (wr / "state").mkdir(parents=True, exist_ok=True)
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "name": "fx", "repo": "example-repo", "allowed_push_repo": "example-repo",
        "branch": "main", "work_root": str(wr), "setup_cmd": setup, "test_cmd": test,
    }))
    return foundry.load_config(str(p))


def _install_commit_check(monkeypatch, cfg, test_out):
    test_argv = tuple(shlex.split(cfg.test_cmd))

    def fake_run_cmd(args, cwd=None, timeout=None, **kw):
        argv = tuple(str(a) for a in args)
        if argv == test_argv:
            return foundry.CmdResult(False, test_out)
        if "status" in argv and "--porcelain" in argv:
            return foundry.CmdResult(True, "")
        if "rev-parse" in argv or "diff" in argv or "ls-files" in argv:
            return foundry.CmdResult(True, "0123456789abcdef0123456789abcdef01234567\n")
        return foundry.CmdResult(True, "ok")

    def trip(*a, **k):
        raise AssertionError("real subprocess spawned: %r" % (a,))

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(foundry, "_try_cleanup_clone", lambda d: None)
    monkeypatch.setattr(subprocess, "run", trip)
    monkeypatch.setattr(subprocess, "Popen", trip)


def _cli(cfg, as_json):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.commit_check_cli(cfg, as_json=as_json)
    return rc, buf.getvalue()


def test_b8_commit_check_tsc_only_red_names_the_tsc_line(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _install_commit_check(monkeypatch, cfg, TSC_ONLY_OUT)
    res = foundry.commit_check(cfg, tmp_path / "cc")
    assert res.exit_code == 1 and res.verdict == "RED"
    assert tuple(res.failing_tests) == (TSC,)
    rc, out = _cli(cfg, as_json=True)
    doc = json.loads(out)
    assert rc == 1 and doc["exit_code"] == 1 and doc["verdict"] == "RED"
    assert doc["failing_tests"] == [TSC]
    rc2, text = _cli(cfg, as_json=False)
    assert rc2 == 1
    stripped = [ln.strip() for ln in text.splitlines()]
    assert "- " + TSC in stripped
    assert [ln for ln in text.splitlines() if ln.strip()][-1] == "COMMIT-CHECK: RED"


def test_b8_preship_result_failing_tests_names_tsc():
    r = foundry.PreshipResult(verified=False, incomplete=False,
                              detail=foundry.PRESHIP_SUITE_FAILED_DETAIL,
                              test_seconds=3.0, suite_output=TSC_ONLY_OUT, verified_sha=SHA)
    assert r.exit_code == 1
    assert tuple(r.failing_tests) == (TSC,)
    assert r.to_dict()["failing_tests"] == [TSC]
    assert "  - " + TSC in r.render().splitlines()


def _script_parent(monkeypatch, parent_out):
    def fake_run_cmd(args, cwd=None, timeout=None, **kw):
        argv = [str(a) for a in args]
        if "rev-parse" in argv and any(a.endswith("^") for a in argv):
            return foundry.CmdResult(True, PARENT + "\n")
        if "rev-parse" in argv:
            return foundry.CmdResult(True, SHA + "\n")
        return foundry.CmdResult(True, "")

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(foundry, "cleanup_clone", lambda *a, **k: None)
    monkeypatch.setattr(foundry, "rerun_suite_at_parent",
                        lambda cfg, parent_sha, clone_dir: (parent_out, "/usr/bin/python3"))


@pytest.mark.parametrize("parent_out", [None, TSC_ONLY_OUT])
def test_b8_parent_leg_tsc_only_broken_keeps_525_clause(tmp_path, monkeypatch, parent_out):
    _script_parent(monkeypatch, parent_out)
    repo = tmp_path / "repo"
    repo.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    test_cmd = "npm test --silent && npm run typecheck --silent"
    cfg = foundry.ProductConfig(name="demo", repo=str(repo), allowed_push_repo="demo",
                                work_root=str(work), test_cmd=test_cmd, setup_cmd="true")
    base = foundry.PreshipResult(verified=False, incomplete=False,
                                 detail=foundry.PRESHIP_SUITE_FAILED_DETAIL,
                                 test_seconds=7.5, suite_output=TSC_ONLY_OUT, verified_sha=SHA)
    got = foundry._preship_parent_leg(cfg, SHA, base)
    assert got.exit_code == 1
    assert got.incomplete is False and got.verified is False
    assert got.detail == (foundry.PRESHIP_SUITE_FAILED_DETAIL + CLAUSE
                          + foundry.preship_runner_label(test_cmd))
    assert tuple(got.failing_tests) == (TSC,)
