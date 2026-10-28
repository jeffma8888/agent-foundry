"""Behavior pins for `bench.py`, the offline two-arm equal-budget comparison seam.

What this module proves (all offline, all deterministic, every arm a SCRIPT):
  * a comparison is only VALID when both arms share base_sha, spec_sha and budget_s;
  * outcomes come from an INDEPENDENT acceptance process, never from an arm's own report;
  * missing, errored, over-budget or unrun results are REJECTED (`UNSCORED` /
    `INVALID_COMPARISON`), never turned into a winner;
  * cost and token usage are `UNKNOWN` unless a usage file was actually produced
    (unknown is not zero);
  * equal acceptance is a TIE, with wall-clock reported as THROUGHPUT, never as quality.

What it does NOT prove: anything about model quality. The arms here are shell
scripts; a real-model run is operator configuration outside this suite.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tarfile

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import bench  # noqa: E402


# --------------------------------------------------------------------------
# toy repo fixture: one module, one failing test, one-line spec
# --------------------------------------------------------------------------
_CALC = "def add(a, b):\n    return a - b\n"
_TEST = (
    "import unittest\n"
    "from calc import add\n\n"
    "class T(unittest.TestCase):\n"
    "    def test_add(self):\n"
    "        self.assertEqual(add(2, 3), 5)\n\n"
    "if __name__ == '__main__':\n"
    "    unittest.main()\n"
)
_FIX = "def add(a, b):\n    return a + b\n"


def _git(cwd: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def toy_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = tmp_path / "toy"
    repo.mkdir()
    (repo / "calc.py").write_text(_CALC, encoding="utf-8")
    (repo / "test_calc.py").write_text(_TEST, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "-q", "-m", "init")
    return repo


def _fix_cmd() -> list[str]:
    return [sys.executable, "-c",
            "import pathlib; pathlib.Path('calc.py').write_text(%r)" % _FIX]


def _noop_cmd() -> list[str]:
    return [sys.executable, "-c", "pass"]


def _break_cmd() -> list[str]:
    return [sys.executable, "-c",
            "import pathlib; pathlib.Path('calc.py').write_text('def add(a, b):\\n    return 0\\n')"]


def _accept_cmd() -> list[str]:
    return [sys.executable, "-m", "unittest", "-q", "test_calc"]


def _spec(tmp_path: pathlib.Path) -> pathlib.Path:
    p = tmp_path / "spec.md"
    p.write_text("Make add(a, b) return the sum.\n", encoding="utf-8")
    return p


def _run(tmp_path, toy_repo, baseline, candidate, budget=30, accept=None, solution=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    out = tmp_path / "out"
    return bench.run_bench(
        repo=toy_repo, spec_path=_spec(tmp_path), budget_s=budget,
        baseline_cmd=baseline, candidate_cmd=candidate,
        accept_cmd=_accept_cmd() if accept is None else accept, out_dir=out,
        check_files=["test_calc.py"],
        solution_files=["calc.py"] if solution is None else solution)


# --------------------------------------------------------------------------
# 1. equal-contract: mismatched sha / spec / budget is INVALID_COMPARISON
# --------------------------------------------------------------------------
def _arm(**over):
    base = dict(base_sha="abc", snapshot_sha="snap", spec_sha="s1", check_sha="chk",
                solution_sha="sol", budget_s=10, wall_s=1.0, exit_code=0, timed_out=False, output="DIFF",
                accept="PASS", cost_usd="UNKNOWN", tokens="UNKNOWN", error=None)
    base.update(over)
    if "accept_exit" not in over:  # consistent by default; tests override to break it
        base["accept_exit"] = {"PASS": 0, "FAIL": 1}.get(base["accept"])
    return base


def test_compare_rejects_mismatched_contract():
    for key, val in (("base_sha", "zzz"), ("spec_sha", "s2"), ("budget_s", 11)):
        rec = {"baseline": _arm(), "candidate": _arm(**{key: val})}
        v = bench.compare(rec)
        assert v["verdict"] == "INVALID_COMPARISON", (key, v)
        assert v["winner"] is None


def test_compare_rejects_missing_arm():
    v = bench.compare({"baseline": _arm()})
    assert v["verdict"] == "INVALID_COMPARISON"
    assert v["winner"] is None


# --------------------------------------------------------------------------
# 2. evidence rejection: NOT_RUN / ERROR / over-budget / arm error -> UNSCORED
# --------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    dict(accept="NOT_RUN"), dict(accept="ERROR"), dict(timed_out=True),
    dict(error="spawn failed"),
])
def test_compare_unscored_when_any_arm_evidence_is_invalid(bad):
    v = bench.compare({"baseline": _arm(), "candidate": _arm(**bad)})
    assert v["verdict"] == "UNSCORED", (bad, v)
    assert v["winner"] is None
    assert v["reasons"], "an UNSCORED verdict must name why"


# --------------------------------------------------------------------------
# 3. acceptance decides; equal acceptance is a TIE, wall_s is throughput only
# --------------------------------------------------------------------------
def test_compare_winner_only_on_acceptance_difference():
    v = bench.compare({"baseline": _arm(accept="FAIL"), "candidate": _arm(accept="PASS"),
                       "input_integrity": {"ok": True}})
    assert v["verdict"] == "WINNER_BY_ACCEPTANCE"
    assert v["winner"] == "candidate"
    assert v["quality_improvement"] == "UNMEASURED"


def test_compare_equal_acceptance_is_tie_not_speed_win():
    v = bench.compare({"baseline": _arm(wall_s=1.0), "candidate": _arm(wall_s=9.0),
                       "input_integrity": {"ok": True}})
    assert v["verdict"] == "TIE_ON_ACCEPTANCE"
    assert v["winner"] is None
    assert v["throughput_wall_s"] == {"baseline": 1.0, "candidate": 9.0}


# --------------------------------------------------------------------------
# 4. end-to-end toy trial (scripted arms, real subprocesses, real diff/accept)
# --------------------------------------------------------------------------
def test_e2e_fix_vs_noop_scores_by_external_acceptance(tmp_path, toy_repo):
    rec = _run(tmp_path, toy_repo, baseline=_noop_cmd(), candidate=_fix_cmd())
    b, c = rec["baseline"], rec["candidate"]
    assert b["base_sha"] == c["base_sha"] == _git(toy_repo, "rev-parse", "HEAD")
    assert b["spec_sha"] == c["spec_sha"] and len(b["spec_sha"]) == 64
    assert b["budget_s"] == c["budget_s"] == 30
    assert b["output"] == "NONE", "a no-op arm must be recorded as producing nothing"
    assert c["output"] == "DIFF"
    assert b["accept"] == "FAIL" and c["accept"] == "PASS"
    assert b["cost_usd"] == "UNKNOWN" and b["tokens"] == "UNKNOWN"
    assert b["wall_s"] >= 0 and c["wall_s"] >= 0
    v = rec["comparison"]
    assert v["verdict"] == "WINNER_BY_ACCEPTANCE" and v["winner"] == "candidate"
    assert v["quality_improvement"] == "UNMEASURED"
    # the source repo is untouched: arms ran in isolated copies
    assert (toy_repo / "calc.py").read_text(encoding="utf-8") == _CALC
    assert _git(toy_repo, "status", "--porcelain") == ""
    # the record is on disk and re-comparable from the file alone
    saved = json.loads((tmp_path / "out" / "record.json").read_text(encoding="utf-8"))
    assert bench.compare(saved)["verdict"] == "WINNER_BY_ACCEPTANCE"


def test_e2e_both_fix_is_tie(tmp_path, toy_repo):
    rec = _run(tmp_path, toy_repo, baseline=_fix_cmd(), candidate=_fix_cmd())
    assert rec["comparison"]["verdict"] == "TIE_ON_ACCEPTANCE"
    assert rec["comparison"]["winner"] is None


def test_e2e_over_budget_arm_is_rejected_not_beaten(tmp_path, toy_repo):
    slow = [sys.executable, "-c", "import time; time.sleep(5)"]
    rec = _run(tmp_path, toy_repo, baseline=_fix_cmd(), candidate=slow, budget=1)
    c = rec["candidate"]
    assert c["timed_out"] is True
    assert c["wall_s"] >= 1.0, "wall_s must be measured, not estimated"
    assert c["accept"] == "NOT_RUN", "acceptance is not run on an over-budget arm"
    assert rec["comparison"]["verdict"] == "UNSCORED"
    assert rec["comparison"]["winner"] is None


def test_e2e_accept_cmd_error_is_not_a_fail_or_pass(tmp_path, toy_repo):
    missing = [str(tmp_path / "no-such-acceptance-binary")]
    rec = _run(tmp_path, toy_repo, baseline=_fix_cmd(), candidate=_fix_cmd(), accept=missing)
    assert rec["baseline"]["accept"] == "ERROR"
    assert rec["comparison"]["verdict"] == "UNSCORED"


def test_e2e_usage_file_is_reported_only_when_produced(tmp_path, toy_repo):
    writes_usage = [sys.executable, "-c",
                    "import json, os; json.dump({'tokens': 123, 'cost_usd': 0.5},"
                    " open(os.environ['BENCH_USAGE_FILE'], 'w'))"]
    rec = _run(tmp_path, toy_repo, baseline=_noop_cmd(), candidate=writes_usage)
    assert rec["baseline"]["tokens"] == "UNKNOWN" and rec["baseline"]["cost_usd"] == "UNKNOWN"
    assert rec["candidate"]["tokens"] == 123 and rec["candidate"]["cost_usd"] == 0.5


# --------------------------------------------------------------------------
# 5. CLI surface: run + compare, exit codes, no winner on rejection
# --------------------------------------------------------------------------
def test_cli_run_and_compare_roundtrip(tmp_path, toy_repo, capsys):
    cfg = tmp_path / "bench.json"
    cfg.write_text(json.dumps({
        "repo": str(toy_repo), "spec": str(_spec(tmp_path)), "budget_s": 30,
        "baseline_cmd": _noop_cmd(), "candidate_cmd": _fix_cmd(),
        "accept_cmd": _accept_cmd(), "check_files": ["test_calc.py"],
        "solution_files": ["calc.py"],
    }), encoding="utf-8")
    out = tmp_path / "cli-out"
    rc = bench.main(["run", "--config", str(cfg), "--out", str(out)])
    assert rc == 0
    rc2 = bench.main(["compare", "--record", str(out / "record.json")])
    assert rc2 == 0
    text = capsys.readouterr().out
    assert "WINNER_BY_ACCEPTANCE" in text
    assert "UNMEASURED" in text


def test_cli_compare_exit_nonzero_on_rejection(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"baseline": _arm(), "candidate": _arm(budget_s=99)}),
                   encoding="utf-8")
    assert bench.main(["compare", "--record", str(bad)]) == 2
    assert "INVALID_COMPARISON" in capsys.readouterr().out


# --------------------------------------------------------------------------
# 6. input freezing: one frozen snapshot, no .git metadata, no external links
# --------------------------------------------------------------------------
def test_freeze_rejects_dirty_git_input(tmp_path, toy_repo):
    (toy_repo / "calc.py").write_text(_FIX, encoding="utf-8")  # uncommitted edit
    with pytest.raises(bench.BenchInputError):
        _run(tmp_path, toy_repo, baseline=_noop_cmd(), candidate=_noop_cmd())


def test_linked_worktree_input_leaves_no_git_pointer_in_arm_copies(tmp_path, toy_repo):
    wt = tmp_path / "wt"
    _git(toy_repo, "worktree", "add", "-q", str(wt))
    assert (wt / ".git").is_file(), "linked worktree .git is a pointer file"
    rec = _run(tmp_path, wt, baseline=_noop_cmd(), candidate=_fix_cmd())
    for arm in ("baseline", "candidate"):
        assert not (tmp_path / "out" / arm / ".git").exists(), arm
    assert rec["baseline"]["base_sha"] == rec["candidate"]["base_sha"] == _git(wt, "rev-parse", "HEAD")
    assert rec["comparison"]["verdict"] == "WINNER_BY_ACCEPTANCE"
    assert _git(wt, "status", "--porcelain") == "" and _git(toy_repo, "status", "--porcelain") == ""


def test_committed_candidate_change_is_still_counted_as_diff(tmp_path, toy_repo):
    commit_fix = [sys.executable, "-c",
                  "import pathlib, subprocess; pathlib.Path('calc.py').write_text(%r);"
                  "subprocess.run(['git','init','-q'],check=True);"
                  "subprocess.run(['git','add','-A'],check=True);"
                  "subprocess.run(['git','-c','user.name=t','-c','user.email=t@example.invalid',"
                  "'commit','-qm','x'],check=True)" % _FIX]
    rec = _run(tmp_path, toy_repo, baseline=_noop_cmd(), candidate=commit_fix)
    assert rec["candidate"]["output"] == "DIFF", "output is judged by content, not git status"
    assert rec["baseline"]["output"] == "NONE"


def test_arm_that_mutates_source_repo_cannot_feed_the_other_arm(tmp_path, toy_repo):
    # baseline writes the fix INTO THE ORIGINAL INPUT; a sequential copy would hand
    # that fix to the candidate. Both arms must start from bytes frozen before either ran.
    poison = [sys.executable, "-c",
              "import pathlib; pathlib.Path(%r).write_text(%r)" % (str(toy_repo / "calc.py"), _FIX)]
    rec = _run(tmp_path, toy_repo, baseline=poison, candidate=_noop_cmd())
    assert rec["candidate"]["accept"] != "PASS", "candidate must not inherit baseline's edit"
    assert rec["comparison"]["verdict"] in ("UNSCORED", "INVALID_COMPARISON")
    assert rec["comparison"]["winner"] is None
    assert any("input" in r for r in rec["comparison"]["reasons"]), rec["comparison"]


def test_symlink_to_outside_tree_is_not_followed_or_copied(tmp_path, toy_repo):
    secret = tmp_path / "outside-secret.txt"
    secret.write_text("do not copy\n", encoding="utf-8")
    (toy_repo / "ext").symlink_to(secret)
    _git(toy_repo, "add", "ext")
    _git(toy_repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "link")
    rec = _run(tmp_path, toy_repo, baseline=_noop_cmd(), candidate=_fix_cmd())
    for arm in ("baseline", "candidate"):
        p = tmp_path / "out" / arm / "ext"
        assert not p.is_symlink() and not p.exists(), arm
    assert rec["comparison"]["verdict"] == "WINNER_BY_ACCEPTANCE"


def test_out_dir_inside_input_tree_is_rejected(tmp_path, toy_repo):
    with pytest.raises(bench.BenchInputError):
        bench.run_bench(repo=toy_repo, spec_path=_spec(tmp_path), budget_s=5,
                        baseline_cmd=_noop_cmd(), candidate_cmd=_noop_cmd(),
                        accept_cmd=_accept_cmd(), out_dir=toy_repo / "out",
                        check_files=["test_calc.py"], solution_files=["calc.py"])


def test_prepopulated_out_dir_is_rejected(tmp_path, toy_repo):
    out = tmp_path / "out"
    out.mkdir()
    (out / "candidate.usage.json").write_text('{"tokens": 1, "cost_usd": 0}', encoding="utf-8")
    with pytest.raises(bench.BenchInputError):
        _run(tmp_path, toy_repo, baseline=_noop_cmd(), candidate=_noop_cmd())


# --------------------------------------------------------------------------
# 7. compare: invalid or incomplete evidence never wins, malformed input never crashes
# --------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    dict(exit_code=1), dict(exit_code=None), dict(exit_code="0"),
    dict(wall_s=None), dict(wall_s=float("nan")), dict(wall_s=float("inf")),
    dict(wall_s=11.0), dict(wall_s=-1.0),
    dict(accept="PASS", accept_exit=1), dict(accept="PASS", accept_exit=None),
    dict(accept="FAIL", accept_exit=0),
    dict(tokens=-5), dict(cost_usd=float("nan")), dict(tokens="lots"), dict(cost_usd=True),
])
def test_compare_candidate_with_bad_evidence_never_wins(bad):
    rec = {"baseline": _arm(accept="FAIL", accept_exit=1), "candidate": _arm(**bad)}
    v = bench.compare(rec)
    assert v["verdict"] in ("UNSCORED", "INVALID_COMPARISON"), (bad, v)
    assert v["winner"] is None, (bad, v)
    assert v["reasons"], (bad, v)


@pytest.mark.parametrize("record", [
    None, [], "x", 7, {"baseline": [], "candidate": _arm()},
    {"baseline": _arm(budget_s={1}), "candidate": _arm(budget_s={1})},
    {"baseline": _arm(budget_s="10"), "candidate": _arm(budget_s="10")},
    {"baseline": _arm(budget_s=0), "candidate": _arm(budget_s=0)},
    {"baseline": _arm(budget_s=-3), "candidate": _arm(budget_s=-3)},
    {"baseline": _arm(budget_s=True), "candidate": _arm(budget_s=True)},
    {"baseline": _arm(base_sha=""), "candidate": _arm(base_sha="")},
    {"baseline": _arm(spec_sha=None), "candidate": _arm(spec_sha=None)},
])
def test_compare_malformed_record_is_invalid_not_a_crash(record):
    v = bench.compare(record)
    assert v["verdict"] == "INVALID_COMPARISON", v
    assert v["winner"] is None


def test_compare_requires_check_and_snapshot_identity():
    for key in ("check_sha", "snapshot_sha"):
        v = bench.compare({"baseline": _arm(), "candidate": _arm(**{key: "other"})})
        assert v["verdict"] == "INVALID_COMPARISON", (key, v)
        a = _arm(); a.pop(key)
        v = bench.compare({"baseline": a, "candidate": _arm()})
        assert v["verdict"] == "INVALID_COMPARISON", (key, v)


def test_cli_compare_invalid_json_or_type_exits_2_without_traceback(tmp_path, capsys):
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("not json {", encoding="utf-8")
    assert bench.main(["compare", "--record", str(bad_json)]) == 2
    assert "INVALID_COMPARISON" in capsys.readouterr().out
    bad_type = tmp_path / "list.json"
    bad_type.write_text("[1, 2]", encoding="utf-8")
    assert bench.main(["compare", "--record", str(bad_type)]) == 2
    assert "INVALID_COMPARISON" in capsys.readouterr().out
    assert bench.main(["compare", "--record", str(tmp_path / "missing.json")]) == 2
    assert "INVALID_COMPARISON" in capsys.readouterr().out


def test_usage_is_labelled_producer_reported_and_validated(tmp_path, toy_repo):
    bad_usage = [sys.executable, "-c",
                 "import json, os; json.dump({'tokens': -1, 'cost_usd': 'free'},"
                 " open(os.environ['BENCH_USAGE_FILE'], 'w'))"]
    rec = _run(tmp_path, toy_repo, baseline=_noop_cmd(), candidate=bad_usage)
    assert rec["baseline"]["usage_source"] is None
    assert rec["candidate"]["usage_source"] == "producer-reported"
    assert rec["comparison"]["verdict"] == "UNSCORED"
    assert rec["comparison"]["winner"] is None


# --------------------------------------------------------------------------
# 8. pinned acceptance inputs: rewriting a check file rejects the arm, never wins
# --------------------------------------------------------------------------
def test_candidate_that_rewrites_pinned_check_is_rejected_not_winner(tmp_path, toy_repo):
    always_pass = "import unittest\nclass T(unittest.TestCase):\n    def test_add(self):\n        pass\n"
    cheat = [sys.executable, "-c",
             "import pathlib; pathlib.Path('test_calc.py').write_text(%r)" % always_pass]
    rec = _run(tmp_path, toy_repo, baseline=_noop_cmd(), candidate=cheat)
    assert rec["candidate"]["accept"] == "REJECTED", rec["candidate"]
    assert rec["candidate"]["accept_exit"] is None, "rejected checks are never executed"
    assert not (tmp_path / "out" / "candidate.accept.txt").exists()
    assert rec["comparison"]["verdict"] == "UNSCORED"
    assert rec["comparison"]["winner"] is None
    assert any("check" in r for r in rec["comparison"]["reasons"])


def test_check_files_must_be_declared_and_present(tmp_path, toy_repo):
    for files in ([], ["nope.py"], ["../spec.md"], "test_calc.py"):
        with pytest.raises(bench.BenchInputError):
            bench.run_bench(repo=toy_repo, spec_path=_spec(tmp_path), budget_s=5,
                            baseline_cmd=_noop_cmd(), candidate_cmd=_noop_cmd(),
                            accept_cmd=_accept_cmd(), out_dir=tmp_path / "out" / str(len(files)),
                            check_files=files, solution_files=["calc.py"])


def test_check_sha_binds_accept_cmd_and_check_content(tmp_path, toy_repo):
    r1 = _run(tmp_path / "a", toy_repo, baseline=_noop_cmd(), candidate=_noop_cmd())
    r2 = _run(tmp_path / "b", toy_repo, baseline=_noop_cmd(), candidate=_noop_cmd(),
              accept=_accept_cmd() + ["-v"])
    assert r1["baseline"]["check_sha"] == r1["candidate"]["check_sha"]
    assert r1["baseline"]["check_sha"] != r2["baseline"]["check_sha"]


# --------------------------------------------------------------------------
# 9. process-group bounding: timeouts and background grandchildren
# --------------------------------------------------------------------------
def _spawn_grandchild_cmd(marker: pathlib.Path, parent_sleep: float) -> list[str]:
    grand = ("import time, pathlib; time.sleep(1.0); "
             "pathlib.Path(%r).write_text('late')" % str(marker))
    return [sys.executable, "-c",
            "import subprocess, sys, time\n"
            "print('started', flush=True)\n"
            "subprocess.Popen([sys.executable, '-c', %r], stdout=subprocess.DEVNULL,"
            " stderr=subprocess.DEVNULL)\n"
            "time.sleep(%r)\n" % (grand, parent_sleep)]


def test_timeout_kills_process_group_and_captures_partial_output(tmp_path, toy_repo):
    import time
    marker = tmp_path / "late-marker.txt"
    rec = _run(tmp_path, toy_repo, baseline=_fix_cmd(),
               candidate=_spawn_grandchild_cmd(marker, parent_sleep=5.0), budget=1)
    c = rec["candidate"]
    assert c["timed_out"] is True and c["accept"] == "NOT_RUN"
    assert "started" in (tmp_path / "out" / "candidate.stdout.txt").read_text(encoding="utf-8")
    assert rec["comparison"]["verdict"] == "UNSCORED" and rec["comparison"]["winner"] is None
    time.sleep(1.6)
    assert not marker.exists(), "grandchild outlived the arm and wrote after return"


def test_background_grandchild_cannot_write_after_normal_exit(tmp_path, toy_repo):
    import time
    marker = tmp_path / "late-marker.txt"
    rec = _run(tmp_path, toy_repo, baseline=_fix_cmd(),
               candidate=_spawn_grandchild_cmd(marker, parent_sleep=0.0), budget=10)
    assert rec["candidate"]["exit_code"] == 0 and rec["candidate"]["timed_out"] is False
    time.sleep(1.6)
    assert not marker.exists(), "grandchild outlived the arm and wrote after return"


# --------------------------------------------------------------------------
# 10. the module must not claim properties it does not enforce
# --------------------------------------------------------------------------
def test_module_doc_does_not_overclaim():
    doc = " ".join(bench.__doc__.split()).lower()
    assert "neither arm sees the other's work" not in doc
    assert "not a security" in doc or "no security" in doc
    assert "not model-efficacy evidence" in doc
    assert "bench.py run --config" in doc, "a CLI example belongs in the module doc"


@pytest.mark.parametrize("integrity", [None, False, [], "ok", {}, {"ok": False}, {"ok": 1}])
def test_compare_requires_explicit_input_integrity(integrity, tmp_path, capsys):
    record = {"baseline": _arm(accept="FAIL"), "candidate": _arm()}
    if integrity is not None:
        record["input_integrity"] = integrity
    verdict = bench.compare(record)
    assert verdict["verdict"] == "UNSCORED"
    assert verdict["winner"] is None
    assert any("input" in reason for reason in verdict["reasons"])
    saved = tmp_path / "incomplete.json"
    saved.write_text(json.dumps(record), encoding="utf-8")
    assert bench.main(["compare", "--record", str(saved)]) == 2
    assert "UNSCORED" in capsys.readouterr().out


def test_compare_explicit_input_integrity_allows_acceptance_winner():
    record = {"baseline": _arm(accept="FAIL"), "candidate": _arm(),
              "input_integrity": {"ok": True}}
    verdict = bench.compare(record)
    assert verdict["verdict"] == "WINNER_BY_ACCEPTANCE"
    assert verdict["winner"] == "candidate"


# --------------------------------------------------------------------------
# 11. boundary defects reproduced against the first candidate
# --------------------------------------------------------------------------
# An acceptance command that dies by SIGKILL while calc.py is still the buggy
# original, and otherwise runs the real unittest. Real subprocess, real signal.
_SIGNAL_ACCEPT = [sys.executable, "-c",
                  "import os, signal, subprocess, sys\n"
                  "if 'a - b' in open('calc.py').read():\n"
                  "    os.kill(os.getpid(), signal.SIGKILL)\n"
                  "sys.exit(subprocess.call([sys.executable, '-m', 'unittest', '-q', 'test_calc']))\n"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal exit status")
def test_e2e_signal_killed_acceptance_is_error_not_fail(tmp_path, toy_repo, capsys):
    rec = _run(tmp_path, toy_repo, baseline=_noop_cmd(), candidate=_fix_cmd(),
               accept=_SIGNAL_ACCEPT)
    b, c = rec["baseline"], rec["candidate"]
    assert b["accept"] == "ERROR", b
    assert b["accept_exit"] == -9, b
    assert "signal" in (b["error"] or ""), b
    assert c["accept"] == "PASS" and c["accept_exit"] == 0, c
    v = rec["comparison"]
    assert v["verdict"] == "UNSCORED" and v["winner"] is None, v
    saved = tmp_path / "out" / "record.json"
    assert bench.main(["compare", "--record", str(saved)]) == 2
    assert "UNSCORED" in capsys.readouterr().out


def test_compare_negative_accept_exit_is_not_a_completed_fail():
    rec = {"baseline": _arm(accept="FAIL", accept_exit=-9), "candidate": _arm(),
           "input_integrity": {"ok": True}}
    v = bench.compare(rec)
    assert v["verdict"] == "UNSCORED" and v["winner"] is None, v
    assert any("signal" in r for r in v["reasons"]), v


def test_compare_positive_failing_exit_still_counts_as_fail():
    for ae in (1, 3, 255):
        rec = {"baseline": _arm(accept="FAIL", accept_exit=ae), "candidate": _arm(),
               "input_integrity": {"ok": True}}
        v = bench.compare(rec)
        assert v["verdict"] == "WINNER_BY_ACCEPTANCE" and v["winner"] == "candidate", (ae, v)


_HUGE = 10 ** 1000  # a valid JSON integer that no float can represent


@pytest.mark.parametrize("field", ["budget_s", "wall_s", "tokens", "cost_usd"])
@pytest.mark.parametrize("value", [_HUGE, -_HUGE, float("nan"), float("inf"), True, "10"],
                         ids=["huge", "neg-huge", "nan", "inf", "bool", "str"])
def test_compare_unrepresentable_or_nonnumeric_numbers_never_crash_or_win(field, value):
    if field == "budget_s":
        rec = {"baseline": _arm(budget_s=value), "candidate": _arm(budget_s=value),
               "input_integrity": {"ok": True}}
    else:
        rec = {"baseline": _arm(accept="FAIL"), "candidate": _arm(**{field: value}),
               "input_integrity": {"ok": True}}
    v = bench.compare(rec)
    assert v["verdict"] in ("UNSCORED", "INVALID_COMPARISON"), (field, value, v)
    assert v["winner"] is None


def test_cli_compare_huge_json_integers_exit_2_without_traceback(tmp_path, capsys):
    for field in ("budget_s", "wall_s", "tokens"):
        rec = {"baseline": _arm(accept="FAIL"), "candidate": _arm(),
               "input_integrity": {"ok": True}}
        rec["candidate"][field] = _HUGE
        if field == "budget_s":
            rec["baseline"][field] = _HUGE
        p = tmp_path / f"{field}.json"
        p.write_text(json.dumps(rec), encoding="utf-8")
        assert bench.main(["compare", "--record", str(p)]) == 2, field
        out = capsys.readouterr().out
        assert "UNSCORED" in out or "INVALID_COMPARISON" in out, (field, out)


def test_compare_ordinary_numbers_and_unknown_usage_keep_semantics():
    rec = {"baseline": _arm(accept="FAIL", budget_s=10, wall_s=2, tokens="UNKNOWN"),
           "candidate": _arm(budget_s=10, wall_s=9.5, tokens=10 ** 6, cost_usd=0.25),
           "input_integrity": {"ok": True}}
    v = bench.compare(rec)
    assert v["verdict"] == "WINNER_BY_ACCEPTANCE" and v["winner"] == "candidate", v
    big = {"baseline": _arm(budget_s=bench.MAX_BUDGET_S), "candidate": _arm(budget_s=bench.MAX_BUDGET_S),
           "input_integrity": {"ok": True}}
    assert bench.compare(big)["verdict"] == "TIE_ON_ACCEPTANCE"


@pytest.mark.parametrize("budget", [_HUGE, 1e300, bench.MAX_BUDGET_S + 1, float("nan"),
                                    float("inf"), True, "30"],
                         ids=["huge", "1e300", "cap+1", "nan", "inf", "bool", "str"])
def test_freeze_rejects_unrepresentable_or_unexecutable_budget(tmp_path, toy_repo, budget):
    with pytest.raises(bench.BenchInputError):
        _run(tmp_path, toy_repo, baseline=_noop_cmd(), candidate=_noop_cmd(), budget=budget)


def test_cli_run_huge_budget_is_rejected_input_not_traceback(tmp_path, toy_repo, capsys):
    cfg = tmp_path / "bench.json"
    cfg.write_text(json.dumps({
        "repo": str(toy_repo), "spec": str(_spec(tmp_path)), "budget_s": _HUGE,
        "baseline_cmd": _noop_cmd(), "candidate_cmd": _fix_cmd(),
        "accept_cmd": _accept_cmd(), "check_files": ["test_calc.py"],
        "solution_files": ["calc.py"]}), encoding="utf-8")
    assert bench.main(["run", "--config", str(cfg), "--out", str(tmp_path / "o")]) == 2
    assert "REJECTED_INPUT" in capsys.readouterr().out
    assert not (tmp_path / "o" / "baseline").exists(), "no arm may launch on a rejected budget"


def test_e2e_huge_producer_reported_usage_is_unscored_not_crash(tmp_path, toy_repo):
    huge_usage = [sys.executable, "-c",
                  "import os; open(os.environ['BENCH_USAGE_FILE'], 'w')"
                  ".write('{\"tokens\": 1' + '0' * 1000 + '}')"]
    rec = _run(tmp_path, toy_repo, baseline=_noop_cmd(), candidate=huge_usage)
    assert "invalid producer-reported usage" in (rec["candidate"]["error"] or "")
    assert rec["comparison"]["verdict"] == "UNSCORED"
    assert rec["comparison"]["winner"] is None


def _tree(root: pathlib.Path, files: dict) -> pathlib.Path:
    root.mkdir(parents=True)
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def test_tree_sha_record_boundary_pair_differs(tmp_path):
    one = _tree(tmp_path / "one", {"a": b"x\nb\0y"})
    two = _tree(tmp_path / "two", {"a": b"x", "b": b"y"})
    assert bench._tree_sha(one) != bench._tree_sha(two)


def test_tree_sha_stable_across_creation_order_and_ignores_git_dir(tmp_path):
    a = _tree(tmp_path / "a", {"x/1": b"1", "y": b"2", "x/z/3": b"3"})
    b = _tree(tmp_path / "b", {"x/z/3": b"3", "y": b"2", "x/1": b"1"})
    assert bench._tree_sha(a) == bench._tree_sha(b)
    before = bench._tree_sha(a)
    (a / ".git").mkdir()
    (a / ".git" / "HEAD").write_bytes(b"ref: refs/heads/main\n")
    assert bench._tree_sha(a) == before


def test_tree_sha_same_size_edit_and_exec_bit_change_hash(tmp_path):
    t = _tree(tmp_path / "t", {"f.py": b"abc"})
    h0 = bench._tree_sha(t)
    (t / "f.py").write_bytes(b"abd")
    h1 = bench._tree_sha(t)
    assert h1 != h0
    if sys.platform != "win32":
        (t / "f.py").chmod(0o755)
        assert bench._tree_sha(t) != h1


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation")
def test_tree_sha_hashes_symlinks_including_dir_links_without_following(tmp_path):
    outside1 = _tree(tmp_path / "o1", {"secret": b"1"})
    outside2 = _tree(tmp_path / "o2", {"secret": b"1"})
    t = _tree(tmp_path / "t", {"f": b"x"})
    (t / "dl").symlink_to(outside1, target_is_directory=True)
    (t / "fl").symlink_to("f")
    h0 = bench._tree_sha(t)
    (outside1 / "secret").write_bytes(b"2")
    assert bench._tree_sha(t) == h0, "a directory symlink must not be followed"
    (t / "dl").unlink()
    (t / "dl").symlink_to(outside2, target_is_directory=True)
    h1 = bench._tree_sha(t)
    assert h1 != h0, "a directory-symlink target change must change the hash"
    (t / "fl").unlink()
    (t / "fl").symlink_to("dl")
    assert bench._tree_sha(t) != h1, "a file-symlink target change must change the hash"


# --------------------------------------------------------------------------
# 12. acceptance boundary: only declared solution files reach acceptance
# --------------------------------------------------------------------------
# A candidate that leaves calc.py wrong and test_calc.py byte-identical, but ADDS a
# package `test_calc/` that `-m unittest test_calc` imports instead of the module.
_SHADOW_CMD = [sys.executable, "-c",
               "import pathlib; p = pathlib.Path('test_calc'); p.mkdir(); (p / '__init__.py')"
               ".write_text('import unittest\\nclass T(unittest.TestCase):\\n"
               "    def test_ok(self): pass\\n')"]
_PATCH_CONFTEST = "import calc\ncalc.add = lambda a, b: a + b\n"
_PYTEST_ACCEPT = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_calc.py"]


def _commit_all(repo: pathlib.Path, files: dict) -> None:
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "more")


def _write_cmd(files: dict) -> list[str]:
    return [sys.executable, "-c",
            "import pathlib\nfor k, v in %r.items():\n    pathlib.Path(k).write_text(v)\n" % files]


def test_shadow_package_cannot_win_without_a_solution_fix(tmp_path, toy_repo, capsys):
    rec = _run(tmp_path, toy_repo, baseline=_noop_cmd(), candidate=_SHADOW_CMD)
    out = tmp_path / "out"
    c = rec["candidate"]
    assert (out / "candidate" / "test_calc" / "__init__.py").is_file(), "artifact is kept"
    assert (out / "candidate" / "calc.py").read_text(encoding="utf-8") == _CALC
    assert (out / "candidate" / "test_calc.py").read_text(encoding="utf-8") == _TEST
    assert not (out / "candidate.accept-tree" / "test_calc").exists()
    assert c["output"] == "DIFF" and c["ignored_change_count"] == 1
    assert c["ignored_change_paths"] == ["test_calc/__init__.py"]
    assert c["accept"] == "FAIL" and c["projected"] == ["calc.py"]
    assert "Ran 1 test" in (out / "candidate.accept.txt").read_text(encoding="utf-8")
    v = rec["comparison"]
    assert v["verdict"] == "TIE_ON_ACCEPTANCE" and v["winner"] is None, v
    assert bench.main(["compare", "--record", str(out / "record.json")]) == 0
    assert "TIE_ON_ACCEPTANCE" in capsys.readouterr().out


def test_real_solution_fix_still_wins_through_the_boundary(tmp_path, toy_repo, capsys):
    rec = _run(tmp_path, toy_repo, baseline=_noop_cmd(), candidate=_fix_cmd())
    out = tmp_path / "out"
    b, c = rec["baseline"], rec["candidate"]
    assert b["accept"] == "FAIL" and c["accept"] == "PASS"
    assert c["projected"] == ["calc.py"] and c["ignored_change_count"] == 0
    assert (out / "candidate.accept-tree" / "calc.py").read_text(encoding="utf-8") == _FIX
    assert "Ran 1 test" in (out / "candidate.accept.txt").read_text(encoding="utf-8")
    assert b["accept_tree_sha"] != c["accept_tree_sha"]
    assert rec["comparison"]["winner"] == "candidate"
    assert bench.main(["compare", "--record", str(out / "record.json")]) == 0
    assert "WINNER_BY_ACCEPTANCE" in capsys.readouterr().out


@pytest.mark.parametrize("variant", ["added", "modified"])
def test_undeclared_conftest_cannot_replace_the_check(tmp_path, toy_repo, variant):
    if variant == "modified":  # an existing, undeclared, benign conftest.py in the snapshot
        _commit_all(toy_repo, {"conftest.py": "# shared fixtures\n"})
    patch = _write_cmd({"conftest.py": _PATCH_CONFTEST})
    rec = _run(tmp_path, toy_repo, baseline=_noop_cmd(), candidate=patch, accept=_PYTEST_ACCEPT)
    c = rec["candidate"]
    assert c["ignored_change_paths"] == ["conftest.py"], c
    assert c["accept"] == "FAIL" and rec["baseline"]["accept"] == "FAIL", c
    assert rec["comparison"]["verdict"] == "TIE_ON_ACCEPTANCE"
    # positive control: the same conftest DOES reach acceptance once declared, so the
    # boundary (not a broken probe) is what blocked it above.
    rec2 = _run(tmp_path / "declared", toy_repo, baseline=_noop_cmd(), candidate=patch,
                accept=_PYTEST_ACCEPT, solution=["calc.py", "conftest.py"])
    assert rec2["candidate"]["accept"] == "PASS", rec2["candidate"]
    assert rec2["comparison"]["winner"] == "candidate"


def test_multi_file_solution_with_declared_new_file(tmp_path, toy_repo):
    files = {"helpers.py": "def plus(a, b):\n    return a + b\n",
             "calc.py": "from helpers import plus\n\ndef add(a, b):\n    return plus(a, b)\n"}
    rec = _run(tmp_path / "declared", toy_repo, baseline=_noop_cmd(), candidate=_write_cmd(files),
               solution=["calc.py", "helpers.py"])
    b, c = rec["baseline"], rec["candidate"]
    assert c["projected"] == ["calc.py", "helpers.py"] and c["accept"] == "PASS", c
    assert b["projected"] == ["calc.py"] and b["accept"] == "FAIL", "absent declared file is absent"
    assert rec["comparison"]["winner"] == "candidate"
    # the same two-file fix with helpers.py NOT declared: calc.py reaches acceptance, its
    # undeclared dependency does not, so acceptance runs and fails
    rec2 = _run(tmp_path / "undeclared", toy_repo, baseline=_noop_cmd(),
                candidate=_write_cmd(files))
    c2 = rec2["candidate"]
    assert c2["ignored_change_paths"] == ["helpers.py"] and c2["accept"] == "FAIL", c2
    assert rec2["comparison"]["verdict"] == "TIE_ON_ACCEPTANCE"


def test_nested_declared_file_modification_and_deletion_are_reflected(tmp_path, toy_repo):
    _commit_all(toy_repo, {"pkg/__init__.py": "", "pkg/impl.py": "def add(a, b):\n    return a - b\n",
                           "calc.py": "from pkg.impl import add\n"})
    fix = _write_cmd({"pkg/impl.py": _FIX})
    rec = _run(tmp_path / "fix", toy_repo, baseline=_noop_cmd(), candidate=fix,
               solution=["pkg/impl.py"])
    assert rec["candidate"]["accept"] == "PASS" and rec["baseline"]["accept"] == "FAIL"
    delete = [sys.executable, "-c", "import os; os.remove('pkg/impl.py')"]
    rec2 = _run(tmp_path / "del", toy_repo, baseline=fix, candidate=delete,
                solution=["pkg/impl.py"])
    c2 = rec2["candidate"]
    assert c2["projected"] == [] and c2["accept"] == "FAIL", c2
    assert not (tmp_path / "del" / "out" / "candidate.accept-tree" / "pkg" / "impl.py").exists()
    assert rec2["comparison"]["winner"] == "baseline"


@pytest.mark.parametrize("solution", [
    None, [], "calc.py", [""], [5], ["calc.py", "calc.py"], ["test_calc.py"], ["./test_calc.py"],
    ["./calc.py"], ["../calc.py"], ["/tmp/calc.py"], ["a//calc.py"], ["calc.py/x"],
    [".git/config"], ["pkg"], ["new", "new/x.py"], ["x\0y"],
], ids=lambda s: repr(s))
def test_solution_files_declaration_is_validated(tmp_path, toy_repo, solution):
    _commit_all(toy_repo, {"pkg/m.py": "x = 1\n"})
    out = tmp_path / "out"
    with pytest.raises(bench.BenchInputError):
        bench.run_bench(repo=toy_repo, spec_path=_spec(tmp_path), budget_s=5,
                        baseline_cmd=_noop_cmd(), candidate_cmd=_noop_cmd(),
                        accept_cmd=_accept_cmd(), out_dir=out,
                        check_files=["test_calc.py"], solution_files=solution)
    assert not out.exists(), "no arm may launch on a rejected declaration"


def test_cli_config_without_solution_files_is_invalid_config(tmp_path, toy_repo, capsys):
    cfg = tmp_path / "bench.json"
    cfg.write_text(json.dumps({
        "repo": str(toy_repo), "spec": str(_spec(tmp_path)), "budget_s": 30,
        "baseline_cmd": _noop_cmd(), "candidate_cmd": _SHADOW_CMD,
        "accept_cmd": _accept_cmd(), "check_files": ["test_calc.py"]}), encoding="utf-8")
    assert bench.main(["run", "--config", str(cfg), "--out", str(tmp_path / "o")]) == 2
    assert "INVALID_CONFIG" in capsys.readouterr().out
    assert not (tmp_path / "o").exists()


# A glob character in a declaration is rejected before either arm runs: never expanded,
# and never read as a literal file name (which would silently drop the real fix).
@pytest.mark.parametrize("solution", [
    ["*.py"], ["calc.p?"], ["[c]alc.py"], ["pkg/*"], ["calc.py", "**/m.py"], ["c[1].py"],
], ids=lambda s: repr(s))
def test_glob_characters_in_solution_files_are_rejected(tmp_path, toy_repo, solution):
    _commit_all(toy_repo, {"pkg/m.py": "x = 1\n", "c[1].py": "y = 2\n"})  # literal names exist
    out = tmp_path / "out"
    with pytest.raises(bench.BenchInputError, match="glob"):
        bench.run_bench(repo=toy_repo, spec_path=_spec(tmp_path), budget_s=5,
                        baseline_cmd=_noop_cmd(), candidate_cmd=_fix_cmd(),
                        accept_cmd=_accept_cmd(), out_dir=out,
                        check_files=["test_calc.py"], solution_files=solution)
    assert not out.exists(), "no arm may launch on a glob declaration"


@pytest.mark.parametrize("glob", ["*.py", "calc.p?", "[c]alc.py"])
def test_cli_glob_solution_path_is_rejected_before_either_arm_runs(tmp_path, toy_repo, capsys,
                                                                    glob):
    spawned = {a: tmp_path / f"spawned-{a}" for a in bench.ARMS}
    mark = "import pathlib; pathlib.Path(%r).write_text('x')"

    def config(solution):
        cfg = tmp_path / "bench.json"
        cfg.write_text(json.dumps({
            "repo": str(toy_repo), "spec": str(_spec(tmp_path)), "budget_s": 30,
            "baseline_cmd": [sys.executable, "-c", mark % str(spawned["baseline"])],
            "candidate_cmd": [sys.executable, "-c", "%s; pathlib.Path('calc.py').write_text(%r)"
                              % (mark % str(spawned["candidate"]), _FIX)],
            "accept_cmd": _accept_cmd(), "check_files": ["test_calc.py"],
            "solution_files": solution}), encoding="utf-8")
        return cfg

    out = tmp_path / "o"
    assert bench.main(["run", "--config", str(config([glob])), "--out", str(out)]) == 2
    text = capsys.readouterr().out
    assert text.startswith("REJECTED_INPUT") and "glob" in text and "verdict" not in text, text
    assert not out.exists(), "nothing may be written for a rejected declaration"
    assert not any(p.exists() for p in spawned.values()), "no arm may be spawned"
    # positive control: the same arms under the literal path do spawn, and the fix wins
    assert bench.main(["run", "--config", str(config(["calc.py"])), "--out", str(out)]) == 0
    assert all(p.exists() for p in spawned.values())
    rec = json.loads((out / "record.json").read_text(encoding="utf-8"))
    assert rec["candidate"]["projected"] == ["calc.py"] and rec["comparison"]["winner"] == "candidate"


def test_glob_rejection_keeps_literal_and_declared_new_paths_working(tmp_path, toy_repo):
    rec = _run(tmp_path / "literal", toy_repo, baseline=_noop_cmd(), candidate=_fix_cmd(),
               solution=["calc.py"])
    assert rec["candidate"]["projected"] == ["calc.py"] and rec["comparison"]["winner"] == "candidate"
    files = {"helpers.py": "def plus(a, b):\n    return a + b\n",
             "calc.py": "from helpers import plus\n\ndef add(a, b):\n    return plus(a, b)\n"}
    rec2 = _run(tmp_path / "new", toy_repo, baseline=_noop_cmd(), candidate=_write_cmd(files),
                solution=["calc.py", "helpers.py"])
    c2 = rec2["candidate"]
    assert c2["projected"] == ["calc.py", "helpers.py"] and c2["accept"] == "PASS", c2
    assert rec2["comparison"]["winner"] == "candidate"
    with pytest.raises(bench.BenchInputError, match="glob"):
        _run(tmp_path / "glob", toy_repo, baseline=_noop_cmd(), candidate=_write_cmd(files),
             solution=["calc.py", "help*.py"])
    assert not (tmp_path / "glob" / "out").exists()


def test_solution_boundary_is_part_of_the_contract(tmp_path, toy_repo):
    f1 = bench.freeze_inputs(toy_repo, _spec(tmp_path), 5, _accept_cmd(), ["test_calc.py"], ["calc.py"])
    f2 = bench.freeze_inputs(toy_repo, _spec(tmp_path), 5, _accept_cmd(), ["test_calc.py"],
                             ["calc.py", "extra.py"])
    assert f1["check_sha"] != f2["check_sha"] and f1["solution_sha"] != f2["solution_sha"]
    v = bench.compare({"baseline": _arm(accept="FAIL"), "candidate": _arm(solution_sha="other"),
                       "input_integrity": {"ok": True}})
    assert v["verdict"] == "INVALID_COMPARISON" and v["winner"] is None
    legacy = _arm()
    legacy.pop("solution_sha")  # a record written before the boundary existed
    v = bench.compare({"baseline": _arm(accept="FAIL"), "candidate": legacy,
                       "input_integrity": {"ok": True}})
    assert v["verdict"] == "INVALID_COMPARISON" and v["winner"] is None


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation")
@pytest.mark.parametrize("where", ["leaf", "parent"])
def test_symlinked_solution_path_is_rejected_and_nothing_outside_is_read(tmp_path, toy_repo, where):
    _commit_all(toy_repo, {"pkg/__init__.py": "", "pkg/impl.py": "def add(a, b):\n    return a - b\n"})
    outside = _tree(tmp_path / "outside", {"calc.py": _FIX.encode(), "impl.py": _FIX.encode()})
    before = {p.name: p.read_bytes() for p in outside.iterdir()}
    link = ("import os; os.remove('calc.py'); os.symlink(%r, 'calc.py')" % str(outside / "calc.py")
            if where == "leaf" else
            "import os, shutil; shutil.rmtree('pkg'); os.symlink(%r, 'pkg')" % str(outside))
    rec = _run(tmp_path / "t", toy_repo, baseline=_noop_cmd(), candidate=[sys.executable, "-c", link],
               solution=["calc.py", "pkg/impl.py"])
    c = rec["candidate"]
    assert c["accept"] == "REJECTED" and "symlink" in c["error"], c
    assert not (tmp_path / "t" / "out" / "candidate.accept.txt").exists(), "acceptance never ran"
    assert rec["comparison"]["verdict"] == "UNSCORED" and rec["comparison"]["winner"] is None
    tree = tmp_path / "t" / "out" / "candidate.accept-tree"
    assert not any(p.is_symlink() for p in tree.rglob("*"))
    assert (tree / "calc.py").read_text(encoding="utf-8") == _CALC
    assert {p.name: p.read_bytes() for p in outside.iterdir()} == before, "outside fixture untouched"


@pytest.mark.skipif(sys.platform == "win32" or not hasattr(__import__("os"), "geteuid")
                    or __import__("os").geteuid() == 0, reason="POSIX permissions, non-root")
@pytest.mark.parametrize("target", ["calc.py", "test_calc.py"])
def test_unreadable_solution_or_check_file_fails_closed_without_verdict(tmp_path, toy_repo,
                                                                         capsys, target):
    cmd = [sys.executable, "-c",
           "import os, pathlib; pathlib.Path('calc.py').write_text(%r); os.chmod(%r, 0)"
           % (_FIX, target)]
    cfg = tmp_path / "bench.json"
    cfg.write_text(json.dumps({
        "repo": str(toy_repo), "spec": str(_spec(tmp_path)), "budget_s": 30,
        "baseline_cmd": _noop_cmd(), "candidate_cmd": cmd, "accept_cmd": _accept_cmd(),
        "check_files": ["test_calc.py"], "solution_files": ["calc.py"]}), encoding="utf-8")
    out = tmp_path / "o"
    try:
        assert bench.main(["run", "--config", str(cfg), "--out", str(out)]) == 2
    finally:
        (out / "candidate" / target).chmod(0o644)
    assert "UNSCORED" in capsys.readouterr().out
    c = json.loads((out / "record.json").read_text(encoding="utf-8"))["candidate"]
    assert c["accept"] == ("ERROR" if target == "calc.py" else "REJECTED"), c
    assert c["accept_exit"] is None and not (out / "candidate.accept.txt").exists()


# --------------------------------------------------------------------------
# 13. harness-owned output collisions: a controlled ERROR and a harness-written
#     record, never a traceback that leaves an arm-planted record.json behind.
#     Real CLI subprocesses; every fixture lives under tmp_path.
# --------------------------------------------------------------------------
_FORGED = {"baseline": _arm(accept="FAIL"), "candidate": _arm(), "input_integrity": {"ok": True}}


def _arm_script(*lines: str, fix: bool = True) -> list[str]:
    body = ["import json, os, pathlib"]
    if fix:
        body.append("pathlib.Path('calc.py').write_text(%r)" % _FIX)
    return [sys.executable, "-c", "\n".join([*body, *lines])]


def _stale_tree(marker: pathlib.Path) -> tuple[str, ...]:
    stale_test = "import pathlib\npathlib.Path(%r).write_text('ran')\n" % str(marker)
    return ("os.makedirs('../candidate.accept-tree')",
            "pathlib.Path('../candidate.accept-tree/STALE').write_text('stale')",
            "pathlib.Path('../candidate.accept-tree/test_calc.py').write_text(%r)" % stale_test)


def _cli_run(tmp_path, toy_repo, baseline, candidate):
    cfg = tmp_path / "bench.json"
    cfg.write_text(json.dumps({
        "repo": str(toy_repo), "spec": str(_spec(tmp_path)), "budget_s": 30,
        "baseline_cmd": baseline, "candidate_cmd": candidate, "accept_cmd": _accept_cmd(),
        "check_files": ["test_calc.py"], "solution_files": ["calc.py"]}), encoding="utf-8")
    out = tmp_path / "o"
    p = subprocess.run([sys.executable, str(_ROOT / "bench.py"), "run", "--config", str(cfg),
                        "--out", str(out)], capture_output=True, text=True, timeout=120)
    return p, out


def _cli_compare(path: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_ROOT / "bench.py"), "compare", "--record",
                           str(path)], capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("forge", [False, True])
def test_cli_precreated_accept_tree_is_error_with_fresh_harness_record(tmp_path, toy_repo, forge):
    marker = tmp_path / "stale-acceptance-ran"
    extra = ("json.dump(%r, open('../record.json', 'w'))" % _FORGED,) if forge else ()
    p, out = _cli_run(tmp_path, toy_repo, _noop_cmd(), _arm_script(*_stale_tree(marker), *extra))
    assert p.returncode == 2 and "Traceback" not in p.stderr, (p.returncode, p.stderr)
    assert "UNSCORED" in p.stdout and "WINNER" not in p.stdout, p.stdout
    rec = json.loads((out / "record.json").read_text(encoding="utf-8"))
    assert "frozen" in rec and rec != _FORGED, "the forged arm record must not survive"
    v = rec["comparison"]
    assert v["verdict"] == "UNSCORED" and v["winner"] is None, v
    hf = rec["harness_failure"]
    assert hf["arm"] == "candidate" and hf["stage"] == "acceptance_projection", hf
    assert hf["type"] == "FileExistsError" and "candidate.accept-tree" in hf["message"], hf
    b, c = rec["baseline"], rec["candidate"]
    assert b["accept"] == "FAIL" and b["accept_exit"] == 1 and b["exit_code"] == 0, b
    assert b["failure"] is None and b["accept_tree_sha"]
    assert c["exit_code"] == 0 and c["accept"] == "ERROR" and c["accept_exit"] is None, c
    assert c["projected"] == [] and c["accept_tree_sha"] is None
    assert "FileExistsError" in c["error"] and c["failure"]["stage"] == "acceptance_projection"
    assert not (out / "candidate.accept.txt").exists() and not marker.exists(), "no stale acceptance"
    assert (out / "candidate.accept-tree" / "STALE").read_text(encoding="utf-8") == "stale", \
        "the colliding tree is retained for diagnosis, not cleared"
    cp = _cli_compare(out / "record.json")
    assert cp.returncode == 2 and "UNSCORED" in cp.stdout and "WINNER" not in cp.stdout, cp.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation")
@pytest.mark.parametrize("collide", [False, True])
def test_cli_record_symlink_is_replaced_never_followed(tmp_path, toy_repo, collide):
    sentinel = tmp_path / "outside" / "sentinel.json"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"SENTINEL-BYTES")
    lines = (*(_stale_tree(tmp_path / "m") if collide else ()),
             "os.symlink(%r, '../record.json')" % str(sentinel))
    p, out = _cli_run(tmp_path, toy_repo, _noop_cmd(), _arm_script(*lines))
    assert sentinel.read_bytes() == b"SENTINEL-BYTES", "write went through the planted link"
    assert p.returncode == (2 if collide else 0) and "Traceback" not in p.stderr, p.stderr
    path = out / "record.json"
    assert not path.is_symlink() and path.is_file(), "the link itself is replaced"
    rec = json.loads(path.read_text(encoding="utf-8"))
    want = "UNSCORED" if collide else "WINNER_BY_ACCEPTANCE"
    assert rec["comparison"]["verdict"] == want, rec["comparison"]
    assert (rec["harness_failure"] is not None) is collide
    assert _cli_compare(path).returncode == (2 if collide else 0)


@pytest.mark.parametrize("planted", ["candidate", "baseline.accept-tree"])
def test_cli_earlier_arm_collision_stops_later_arm_without_deleting(tmp_path, toy_repo, planted):
    ran = tmp_path / "candidate-ran"
    baseline = _arm_script("os.makedirs('../%s')" % planted,
                           "pathlib.Path('../%s/KEEP').write_text('keep')" % planted, fix=False)
    candidate = _arm_script("pathlib.Path(%r).write_text('ran')" % str(ran))
    p, out = _cli_run(tmp_path, toy_repo, baseline, candidate)
    assert p.returncode == 2 and "Traceback" not in p.stderr, (p.returncode, p.stderr)
    assert "UNSCORED" in p.stdout and "WINNER" not in p.stdout
    assert not ran.exists(), "the later arm must not run after a harness failure"
    assert (out / planted / "KEEP").read_text(encoding="utf-8") == "keep", "collision kept"
    rec = json.loads((out / "record.json").read_text(encoding="utf-8"))
    hf, b, c = rec["harness_failure"], rec["baseline"], rec["candidate"]
    assert hf["type"] == "FileExistsError", hf
    assert c["exit_code"] is None and c["wall_s"] is None and c["accept_exit"] is None, c
    assert c["tokens"] == "UNKNOWN" and c["projected"] == [] and c["error"], c
    if planted == "candidate":
        assert hf["arm"] == "candidate" and hf["stage"] == "setup", hf
        assert c["accept"] == "ERROR" and c["tree_sha_start"] is None
        assert b["accept"] == "FAIL" and b["accept_exit"] == 1, b
    else:
        assert hf["arm"] == "baseline" and hf["stage"] == "acceptance_projection", hf
        assert b["exit_code"] == 0 and b["accept"] == "ERROR" and b["accept_exit"] is None, b
        assert c["accept"] == "NOT_RUN" and "not run" in c["error"], c
    assert rec["comparison"]["verdict"] == "UNSCORED"
    assert _cli_compare(out / "record.json").returncode == 2


def test_cli_record_path_directory_is_controlled_error_not_success(tmp_path, toy_repo):
    candidate = _arm_script("os.makedirs('../record.json')",
                            "pathlib.Path('../record.json/KEEP').write_text('keep')")
    p, out = _cli_run(tmp_path, toy_repo, _noop_cmd(), candidate)
    assert p.returncode == 2 and "Traceback" not in p.stderr, (p.returncode, p.stderr)
    assert "RECORD_NOT_WRITTEN" in p.stdout and "WINNER" not in p.stdout, p.stdout
    assert (out / "record.json" / "KEEP").read_text(encoding="utf-8") == "keep"
    assert not [x.name for x in out.iterdir() if x.name.startswith(".record.")], "temp left"
    cp = _cli_compare(out / "record.json")
    assert cp.returncode == 2 and "INVALID_COMPARISON" in cp.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation")
def test_cli_planted_artifact_link_is_not_written_through(tmp_path, toy_repo):
    sentinel = tmp_path / "outside" / "sentinel.txt"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"SENTINEL-BYTES")
    baseline = _arm_script("os.symlink(%r, '../candidate.stdout.txt')" % str(sentinel), fix=False)
    p, out = _cli_run(tmp_path, toy_repo, baseline, _fix_cmd())
    assert sentinel.read_bytes() == b"SENTINEL-BYTES"
    assert p.returncode == 2 and "Traceback" not in p.stderr, (p.returncode, p.stderr)
    rec = json.loads((out / "record.json").read_text(encoding="utf-8"))
    hf = rec["harness_failure"]
    assert hf["arm"] == "candidate" and hf["stage"] == "artifact_write", hf
    assert rec["candidate"]["accept"] == "ERROR" and rec["comparison"]["winner"] is None
    assert (out / "candidate.stdout.txt").is_symlink(), "collision retained for diagnosis"


# --------------------------------------------------------------------------
# 14. source-freeze provenance: an inherited GIT_* that could aim git at another
#     repository is refused (names only) before any git call, snapshot, arm or
#     out dir; the git dir/toplevel git resolves must be the selected repo's own.
# --------------------------------------------------------------------------
def _owned_env() -> dict:
    """Test env with every GIT_* stripped (lock-free status pinned), so fixture setup
    and before/after inspection never follow a variable a test exports."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _owned_git(cwd: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=_owned_env()).stdout.strip()


def _owned_repo(root: pathlib.Path, name: str, files: dict, remote: str | None = None):
    repo = root / name
    repo.mkdir()
    for rel, text in files.items():
        (repo / rel).write_text(text, encoding="utf-8")
    _owned_git(repo, "init", "-q")
    _owned_git(repo, "add", ".")
    _owned_git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
               "commit", "-q", "-m", f"fixture {name}")
    if remote is not None:
        _owned_git(repo, "remote", "add", "origin", remote)
    return repo


def _two_owned_repos(tmp_path: pathlib.Path, foreign_tree: str = "distinct", remote: bool = False):
    """source = the selected input; foreign = another owned repo with its own commit.
    `distinct`: foreign's content differs. `matching-worktree`: foreign tracks the same
    files as source's worktree (the probe shape: a dirty check cannot notice)."""
    third = tmp_path / "third-party"
    third.mkdir()
    (third / "sentinel.txt").write_bytes(b"THIRD-PARTY-SENTINEL")
    source = _owned_repo(tmp_path, "source", {"calc.py": _CALC, "test_calc.py": _TEST})
    files = ({"calc.py": _FIX, "test_calc.py": _TEST, "FOREIGN.txt": "foreign\n"}
             if foreign_tree == "distinct" else {"calc.py": _CALC, "test_calc.py": _TEST})
    foreign = _owned_repo(tmp_path, "foreign", files,
                          remote=str(third / "never-contacted.git") if remote else None)
    assert _owned_git(source, "rev-parse", "HEAD") != _owned_git(foreign, "rev-parse", "HEAD")
    return source, foreign, third


def _repo_state(repo: pathlib.Path) -> dict:
    return {"head": _owned_git(repo, "rev-parse", "HEAD"),
            "tree": _owned_git(repo, "rev-parse", "HEAD^{tree}"),
            "status": _owned_git(repo, "status", "--porcelain", "--untracked-files=all"),
            "index": hashlib.sha256((repo / ".git" / "index").read_bytes()).hexdigest(),
            "files": bench._tree_sha(repo),
            "config": (repo / ".git" / "config").read_bytes(),
            "remotes": _owned_git(repo, "remote", "-v")}


def _dir_bytes(root: pathlib.Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _spy_side_effects(m, calls: list) -> None:
    """Record (and still perform) every subprocess, tree snapshot, arm copy and arm run."""
    real_run, real_popen = subprocess.run, subprocess.Popen

    def run(*a, **k):
        calls.append(("run", list(a[0] if a else k.get("args"))))
        return real_run(*a, **k)

    class Popen(real_popen):
        def __init__(self, *a, **k):
            calls.append(("Popen", list(a[0] if a else k.get("args"))))
            super().__init__(*a, **k)

    m.setattr(bench.subprocess, "run", run)
    m.setattr(bench.subprocess, "Popen", Popen)
    for name in ("_tree_tar", "_materialize", "run_arm"):
        real = getattr(bench, name)

        def wrap(*a, _real=real, _name=name, **k):
            calls.append((_name, None))
            return _real(*a, **k)
        m.setattr(bench, name, wrap)


def _assert_names_only(msg: str, names: list[str], secrets: list[str]) -> None:
    assert re.findall(r"GIT_[A-Z0-9_]+", msg) == sorted(names), msg
    for s in secrets:
        assert s not in msg, "an inherited value leaked into the refusal"


def _freeze(repo: pathlib.Path, tmp_path: pathlib.Path) -> dict:
    return bench.freeze_inputs(repo=repo, spec_path=_spec(tmp_path), budget_s=30,
                               accept_cmd=_accept_cmd(), check_files=["test_calc.py"],
                               solution_files=["calc.py"])


@pytest.mark.parametrize("remote", [False, True], ids=["no-remote", "remote"])
@pytest.mark.parametrize("foreign_tree", ["distinct", "matching-worktree"])
def test_inherited_git_dir_to_foreign_repo_is_refused_before_any_git_call(
        tmp_path, monkeypatch, foreign_tree, remote):
    source, foreign, third = _two_owned_repos(tmp_path, foreign_tree, remote)
    before = {r: _repo_state(r) for r in (source, foreign)}
    third_before = _dir_bytes(third)
    spec, out, calls = _spec(tmp_path), tmp_path / "out", []
    with monkeypatch.context() as m:
        m.setenv("GIT_DIR", str(foreign / ".git"))
        _spy_side_effects(m, calls)
        try:
            rec = bench.run_bench(repo=source, spec_path=spec, budget_s=30,
                                  baseline_cmd=_noop_cmd(), candidate_cmd=_fix_cmd(),
                                  accept_cmd=_accept_cmd(), out_dir=out,
                                  check_files=["test_calc.py"], solution_files=["calc.py"])
        except bench.BenchInputError as e:
            err = e
        else:
            assert rec["frozen"]["base_sha"] != before[foreign]["head"], \
                "false provenance: source frozen with the foreign repo's HEAD"
            pytest.fail("inherited GIT_DIR was not refused")
    assert calls == [], f"git/snapshot/arm side effects before the refusal: {calls}"
    _assert_names_only(str(err), ["GIT_DIR"], [str(foreign), str(tmp_path)])
    assert not out.exists(), "no out dir, frozen copy or record before the refusal"
    assert {r: _repo_state(r) for r in (source, foreign)} == before
    assert _dir_bytes(third) == third_before and _owned_git(source, "remote") == ""


def test_cli_run_refuses_inherited_git_dir_by_name_without_writing(tmp_path):
    source, foreign, third = _two_owned_repos(tmp_path, "matching-worktree", remote=True)
    before = {r: _repo_state(r) for r in (source, foreign)}
    cfg, out = tmp_path / "bench.json", tmp_path / "o"
    cfg.write_text(json.dumps({
        "repo": str(source), "spec": str(_spec(tmp_path)), "budget_s": 30,
        "baseline_cmd": _noop_cmd(), "candidate_cmd": _fix_cmd(), "accept_cmd": _accept_cmd(),
        "check_files": ["test_calc.py"], "solution_files": ["calc.py"]}), encoding="utf-8")
    env = {**_owned_env(), "GIT_DIR": str(foreign / ".git")}
    p = subprocess.run([sys.executable, str(_ROOT / "bench.py"), "run", "--config", str(cfg),
                        "--out", str(out)], capture_output=True, text=True, timeout=120, env=env)
    assert p.returncode == 2 and "Traceback" not in p.stderr, (p.returncode, p.stdout, p.stderr)
    assert p.stdout.startswith("REJECTED_INPUT:"), p.stdout
    assert "WINNER" not in p.stdout and "TIE" not in p.stdout
    _assert_names_only(p.stdout + p.stderr, ["GIT_DIR"], [str(foreign), str(tmp_path)])
    assert not out.exists()
    assert {r: _repo_state(r) for r in (source, foreign)} == before
    assert _dir_bytes(third) == {"sentinel.txt": b"THIRD-PARTY-SENTINEL"}


@pytest.mark.parametrize("names", [
    ("GIT_WORK_TREE",), ("GIT_INDEX_FILE",), ("GIT_OBJECT_DIRECTORY",),
    ("GIT_ALTERNATE_OBJECT_DIRECTORIES",), ("GIT_COMMON_DIR",),
    ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"), ("GIT_CONFIG_PARAMETERS",),
    ("GIT_DIR", "GIT_OPTIONAL_LOCKS", "GIT_TRACE"),
], ids=lambda n: "+".join(n))
def test_repo_index_object_and_config_redirects_are_refused_by_name(tmp_path, monkeypatch, names):
    source, foreign, _ = _two_owned_repos(tmp_path, "matching-worktree")
    before = {r: _repo_state(r) for r in (source, foreign)}
    fg = foreign / ".git"
    values = {"GIT_DIR": str(fg), "GIT_WORK_TREE": str(foreign),
              "GIT_INDEX_FILE": str(fg / "index"), "GIT_OBJECT_DIRECTORY": str(fg / "objects"),
              "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(fg / "objects"), "GIT_COMMON_DIR": str(fg),
              "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.worktree",
              "GIT_CONFIG_VALUE_0": str(foreign),
              "GIT_CONFIG_PARAMETERS": "'core.worktree'='%s'" % foreign,
              "GIT_OPTIONAL_LOCKS": "0", "GIT_TRACE": "0"}
    spec, calls = _spec(tmp_path), []
    with monkeypatch.context() as m:
        for n in names:
            m.setenv(n, values[n])
        _spy_side_effects(m, calls)
        with pytest.raises(bench.BenchInputError) as exc:
            bench.freeze_inputs(repo=source, spec_path=spec, budget_s=30,
                                accept_cmd=_accept_cmd(), check_files=["test_calc.py"],
                                solution_files=["calc.py"])
    assert calls == [], calls
    refused = [n for n in names if n not in ("GIT_OPTIONAL_LOCKS", "GIT_TRACE")]
    _assert_names_only(str(exc.value), refused, [str(foreign), str(tmp_path)])
    assert {r: _repo_state(r) for r in (source, foreign)} == before
    assert _freeze(source, tmp_path)["base_sha"] == before[source]["head"], "fixture control"


def test_allowlisted_git_env_still_freezes_and_scores_the_source_repo(tmp_path, monkeypatch):
    source, foreign, _ = _two_owned_repos(tmp_path, "distinct", remote=True)
    head = _owned_git(source, "rev-parse", "HEAD")
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "0")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    frozen = _freeze(source, tmp_path)
    files = bench._tar_regular_files(frozen["_tar"])
    assert frozen["base_sha"] == head and frozen["repo"] == str(source.resolve())
    assert files == {"calc.py": _CALC.encode(), "test_calc.py": _TEST.encode()}
    assert frozen["spec_sha"] == hashlib.sha256(_spec(tmp_path).read_bytes()).hexdigest()
    assert frozen["check_files"] == {"test_calc.py": hashlib.sha256(_TEST.encode()).hexdigest()}
    assert frozen["accept_cmd"] == _accept_cmd() and frozen["solution_files"] == ["calc.py"]
    rec = _run(tmp_path / "run", source, baseline=_noop_cmd(), candidate=_fix_cmd())
    assert rec["baseline"]["base_sha"] == rec["candidate"]["base_sha"] == head
    assert rec["comparison"]["verdict"] == "WINNER_BY_ACCEPTANCE"
    assert rec["comparison"]["winner"] == "candidate"
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "calc.py").write_text(_CALC, encoding="utf-8")
    (plain / "test_calc.py").write_text(_TEST, encoding="utf-8")
    assert _freeze(plain, tmp_path)["base_sha"].startswith("tree:")
    import trial  # one names-only policy: an env bench freezes under is one an arm accepts
    assert bench.HARMLESS_GIT_ENV == trial.HARMLESS_GIT_ENV
    assert bench.HARMLESS_GIT_ENV_PREFIX == trial.HARMLESS_GIT_ENV_PREFIX


def test_repo_whose_git_toplevel_is_elsewhere_is_refused_before_status_or_archive(
        tmp_path, monkeypatch):
    source, foreign, _ = _two_owned_repos(tmp_path, "matching-worktree")
    _owned_git(source, "config", "core.worktree", str(foreign))
    before = {r: _repo_state(r) for r in (source, foreign)}
    spec, calls = _spec(tmp_path), []
    with monkeypatch.context() as m:
        _spy_side_effects(m, calls)
        with pytest.raises(bench.BenchInputError, match="identity") as exc:
            bench.freeze_inputs(repo=source, spec_path=spec, budget_s=30,
                                accept_cmd=_accept_cmd(), check_files=["test_calc.py"],
                                solution_files=["calc.py"])
    git_verbs = [c[1][1] for c in calls if c[0] == "run" and c[1][:1] == ["git"]]
    assert "status" not in git_verbs and "archive" not in git_verbs, git_verbs
    assert str(foreign) not in str(exc.value)
    assert {r: _repo_state(r) for r in (source, foreign)} == before


# --------------------------------------------------------------------------
# plain (non-git) input: the owner-exec bit survives the snapshot, normalized
# to 0755 / 0644 as git records file modes; no other mode bits or ownership
# --------------------------------------------------------------------------
_CHECK_SH = "#!/bin/sh\ngrep -q 'return a + b' calc.py\n"
_TOOL_SH = "#!/bin/sh\nprintf 'def add(a, b):\\n    return a + b\\n' > calc.py\n"
_posix_modes = pytest.mark.skipif(sys.platform == "win32", reason="POSIX exec bits")


def _plain(root: pathlib.Path, files: dict) -> pathlib.Path:
    """An owned NON-git input directory: {name: (text, mode)}."""
    root.mkdir(parents=True)
    for rel, (text, mode) in files.items():
        (root / rel).write_text(text, encoding="utf-8")
        (root / rel).chmod(mode)
    return root


def _modes(root: pathlib.Path) -> dict:
    return {p.name: p.lstat().st_mode & 0o7777 for p in sorted(root.iterdir())}


def _plain_state(root: pathlib.Path) -> dict:
    return {p.name: (p.read_bytes(), p.lstat().st_mode & 0o7777) for p in sorted(root.iterdir())}


def _plain_freeze(root: pathlib.Path, tmp_path: pathlib.Path) -> dict:
    return bench.freeze_inputs(repo=root, spec_path=_spec(tmp_path), budget_s=30,
                               accept_cmd=["./check.sh"], check_files=["check.sh"],
                               solution_files=["calc.py"])


@_posix_modes
def test_cli_plain_dir_executable_check_runs_from_snapshot_and_ties(tmp_path, capsys):
    src = _plain(tmp_path / "src", {"calc.py": (_FIX, 0o644), "check.sh": (_CHECK_SH, 0o755)})
    before = _plain_state(src)
    _spec(tmp_path)
    cfg = tmp_path / "bench.json"
    cfg.write_text(json.dumps({"repo": "src", "spec": "spec.md", "budget_s": 30,
                               "baseline_cmd": _noop_cmd(), "candidate_cmd": _noop_cmd(),
                               "accept_cmd": ["./check.sh"], "check_files": ["check.sh"],
                               "solution_files": ["calc.py"]}), encoding="utf-8")
    out = tmp_path / "out"
    rc = bench.main(["run", "--config", str(cfg), "--out", str(out)])
    rec = json.loads((out / "record.json").read_text(encoding="utf-8"))
    assert rc == 0 and rec["comparison"]["verdict"] == "TIE_ON_ACCEPTANCE", rec["comparison"]
    for arm in bench.ARMS:
        assert (rec[arm]["accept"], rec[arm]["accept_exit"], rec[arm]["error"]) == ("PASS", 0, None)
        for tree in (arm, f"{arm}.accept-tree"):
            assert _modes(out / tree) == {"calc.py": 0o644, "check.sh": 0o755}, tree
    assert _plain_state(src) == before, "the source is never modified"


@_posix_modes
def test_plain_dir_arm_runs_executable_helper_by_argv_then_is_scored_separately(tmp_path):
    src = _plain(tmp_path / "src", {"calc.py": (_CALC, 0o644), "check.sh": (_CHECK_SH, 0o755),
                                    "tool.sh": (_TOOL_SH, 0o755)})
    before = _plain_state(src)
    rec = bench.run_bench(repo=src, spec_path=_spec(tmp_path), budget_s=30,
                          baseline_cmd=_noop_cmd(), candidate_cmd=["./tool.sh"],
                          accept_cmd=["./check.sh"], out_dir=tmp_path / "out",
                          check_files=["check.sh"], solution_files=["calc.py"])
    cand = rec["candidate"]
    assert (cand["exit_code"], cand["error"], cand["output"]) == (0, None, "DIFF")
    assert (tmp_path / "out" / "candidate" / "calc.py").read_text(encoding="utf-8") == _FIX
    assert cand["projected"] == ["calc.py"] and cand["ignored_change_count"] == 0
    assert (cand["accept"], rec["baseline"]["accept"]) == ("PASS", "FAIL")
    assert rec["comparison"]["verdict"] == "WINNER_BY_ACCEPTANCE"
    assert rec["comparison"]["winner"] == "candidate"
    assert _plain_state(src) == before


@_posix_modes
@pytest.mark.parametrize("target,op", [("notes.txt", "|"), ("tool.sh", "&~")],
                         ids=["add-owner-exec", "drop-owner-exec"])
def test_plain_dir_owner_exec_only_source_mutation_fails_integrity(tmp_path, target, op):
    check_py = "import sys\nsys.exit(0 if 'return a + b' in open('calc.py').read() else 1)\n"
    src = _plain(tmp_path / "src", {"calc.py": (_FIX, 0o644), "check.py": (check_py, 0o644),
                                    "notes.txt": ("n\n", 0o644), "tool.sh": (_TOOL_SH, 0o755)})
    content = (src / target).read_bytes()
    flip = [sys.executable, "-c", "import os, stat; p = %r; "
            "os.chmod(p, stat.S_IMODE(os.lstat(p).st_mode) %s stat.S_IXUSR)" % (str(src / target), op)]
    rec = bench.run_bench(repo=src, spec_path=_spec(tmp_path), budget_s=30,
                          baseline_cmd=_noop_cmd(), candidate_cmd=flip,
                          accept_cmd=[sys.executable, "check.py"], out_dir=tmp_path / "out",
                          check_files=["check.py"], solution_files=["calc.py"])
    assert (src / target).read_bytes() == content, "only the mode changed"
    assert (src / target).lstat().st_mode & 0o100 == (0o100 if op == "|" else 0)
    assert rec["baseline"]["accept"] == rec["candidate"]["accept"] == "PASS"
    assert rec["input_integrity"]["ok"] is False
    assert rec["comparison"]["verdict"] == "UNSCORED", rec["comparison"]
    assert any("input integrity" in r for r in rec["comparison"]["reasons"])


@_posix_modes
def test_plain_dir_snapshot_keeps_only_owner_exec_deterministically(tmp_path):
    names = {"calc.py": _FIX, "check.sh": _CHECK_SH, "a.txt": "a\n", "b.sh": "b\n", "c.txt": "c\n"}
    odd_modes = {"calc.py": 0o600, "check.sh": 0o700, "a.txt": 0o664, "b.sh": 0o775, "c.txt": 0o611}
    want = {"calc.py": 0o644, "check.sh": 0o755, "a.txt": 0o644, "b.sh": 0o755, "c.txt": 0o644}
    odd = _plain(tmp_path / "odd", {n: (t, odd_modes[n]) for n, t in names.items()})
    try:
        (odd / "b.sh").chmod(0o4775)  # setuid, where the platform lets an owner set it
    except OSError:
        pass
    canon = _plain(tmp_path / "canon", {n: (t, want[n]) for n, t in names.items()})
    flat = _plain(tmp_path / "flat", {n: (t, 0o644) for n, t in names.items()})
    f1, f2 = _plain_freeze(odd, tmp_path), _plain_freeze(odd, tmp_path)
    with tarfile.open(fileobj=io.BytesIO(f1["_tar"])) as tar:
        members = tar.getmembers()
    assert {m.name: m.mode for m in members} == want
    assert {(m.uid, m.gid, m.uname, m.gname, m.mtime) for m in members} == {(0, 0, "", "", 0)}
    assert f1["_tar"] == f2["_tar"] and f1["base_sha"] == f2["base_sha"]
    assert f1["snapshot_sha"] == _plain_freeze(canon, tmp_path)["snapshot_sha"]
    assert f1["snapshot_sha"] != _plain_freeze(flat, tmp_path)["snapshot_sha"], \
        "the owner-exec bit is bound into the plain-tree snapshot hash"


# --------------------------------------------------------------------------
# pinned check files: the owner-exec bit is part of pinned integrity, taken from
# the frozen snapshot. Like git, only that bit counts: a group/other-only chmod
# is no change. Executables run by argv, never via sh/python.
# --------------------------------------------------------------------------
_EXIT0_SH = "#!/bin/sh\nexit 0\n"
_READ_INPUT = "import sys\nsys.exit(0 if open('check_input.sh').read() == %r else 1)\n" % _EXIT0_SH
# case: (pinned file, mode in source, candidate's chmod mode, accept_cmd)
_OWNER_EXEC_FLIPS = {
    "drop-owner-exec": ("check.sh", 0o755, "0644", ["./check.sh"]),
    "add-owner-exec": ("check_input.sh", 0o644, "0755", [sys.executable, "-c", _READ_INPUT]),
}
_SAME_OWNER_EXEC = {
    "same-0755": ("check.sh", 0o755, "0755", ["./check.sh"]),
    "0755-to-0700": ("check.sh", 0o755, "0700", ["./check.sh"]),
    "0644-to-0666": ("check_input.sh", 0o644, "0666", [sys.executable, "-c", _READ_INPUT]),
    "0644-to-0654": ("check_input.sh", 0o644, "0654", [sys.executable, "-c", _READ_INPUT]),
}


def _pinned_src(tmp_path: pathlib.Path, kind: str, pinned: str, mode: int) -> pathlib.Path:
    """An owned plain dir, or a clean owned git repo, holding `pinned` at `mode`."""
    src = _plain(tmp_path / "src", {pinned: (_EXIT0_SH, mode), "calc.py": (_FIX, 0o644)})
    if kind == "git":
        _owned_git(src, "init", "-q")
        _owned_git(src, "add", ".")
        _owned_git(src, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                   "commit", "-q", "-m", "fixture")
        assert _owned_git(src, "ls-files", "-s", pinned).startswith("100755" if mode & 0o100
                                                                    else "100644")
    return src


def _src_state(src: pathlib.Path) -> dict:
    st = {p.name: (p.read_bytes(), p.lstat().st_mode & 0o7777)
          for p in sorted(src.iterdir()) if p.name != ".git"}
    if (src / ".git").is_dir():
        st[".git"] = _repo_state(src)
    return st


def _pinned_run(tmp_path, src, pinned, new_mode, accept):
    return bench.run_bench(repo=src, spec_path=_spec(tmp_path), budget_s=30,
                           baseline_cmd=_noop_cmd(), candidate_cmd=["/bin/chmod", new_mode, pinned],
                           accept_cmd=accept, out_dir=tmp_path / "out", check_files=[pinned],
                           solution_files=["calc.py"])


@_posix_modes
@pytest.mark.parametrize("flip", sorted(_OWNER_EXEC_FLIPS))
@pytest.mark.parametrize("kind", ["plain", "git"])
def test_pinned_check_owner_exec_flip_rejects_arm_even_with_same_bytes(tmp_path, kind, flip):
    pinned, mode, new_mode, accept = _OWNER_EXEC_FLIPS[flip]
    src = _pinned_src(tmp_path, kind, pinned, mode)
    before = _src_state(src)
    out = tmp_path / "out"
    rec = _pinned_run(tmp_path, src, pinned, new_mode, accept)
    cand, base = rec["candidate"], rec["baseline"]
    assert (out / "candidate" / pinned).read_bytes() == _EXIT0_SH.encode(), "same bytes"
    assert (out / "candidate" / pinned).lstat().st_mode & 0o777 == int(new_mode, 8)
    assert (cand["exit_code"], cand["accept"], cand["accept_exit"]) == (0, "REJECTED", None), cand
    assert pinned in cand["error"]
    assert not (out / "candidate.accept.txt").exists(), "a rejected check is never executed"
    assert not (out / "candidate.accept-tree").exists()
    assert (base["accept"], base["accept_exit"], base["error"]) == ("PASS", 0, None), base
    assert rec["comparison"]["verdict"] == "UNSCORED" and rec["comparison"]["winner"] is None
    assert any("pinned check" in r for r in rec["comparison"]["reasons"])
    assert rec["input_integrity"]["ok"] is True
    persisted = json.loads((out / "record.json").read_text(encoding="utf-8"))["frozen"]
    assert persisted["check_files"] == {pinned: hashlib.sha256(_EXIT0_SH.encode()).hexdigest()}
    assert not [k for k in persisted if k.startswith("_")], "no private frozen metadata leaks"
    assert _src_state(src) == before, "source bytes, modes and git index are never modified"


@_posix_modes
@pytest.mark.parametrize("kind", ["plain", "git"])
def test_cli_pinned_check_chmod_0644_is_unscored_not_a_tie(tmp_path, kind):
    src = _pinned_src(tmp_path, kind, "check.sh", 0o755)
    before = _src_state(src)
    _spec(tmp_path)
    cfg = tmp_path / "bench.json"
    cfg.write_text(json.dumps({"repo": "src", "spec": "spec.md", "budget_s": 30,
                               "baseline_cmd": _noop_cmd(),
                               "candidate_cmd": ["/bin/chmod", "0644", "check.sh"],
                               "accept_cmd": ["./check.sh"], "check_files": ["check.sh"],
                               "solution_files": ["calc.py"]}), encoding="utf-8")
    out = tmp_path / "out"
    p = subprocess.run([sys.executable, str(_ROOT / "bench.py"), "run", "--config", str(cfg),
                        "--out", str(out)], capture_output=True, text=True, timeout=120,
                       env=_owned_env())
    assert p.returncode == 2 and p.stdout.startswith("verdict: UNSCORED"), p.stdout + p.stderr
    rec = json.loads((out / "record.json").read_text(encoding="utf-8"))
    assert (rec["candidate"]["accept"], rec["candidate"]["accept_exit"]) == ("REJECTED", None)
    assert (rec["baseline"]["accept"], rec["baseline"]["accept_exit"]) == ("PASS", 0)
    assert not (out / "candidate.accept.txt").exists()
    assert not (out / "candidate.accept-tree").exists()
    assert _cli_compare(out / "record.json").returncode == 2
    assert _src_state(src) == before


@_posix_modes
@pytest.mark.parametrize("case", sorted(_SAME_OWNER_EXEC))
@pytest.mark.parametrize("kind", ["plain", "git"])
def test_pinned_check_same_owner_exec_passes_and_group_other_bits_are_ignored(tmp_path, kind,
                                                                              case):
    pinned, mode, new_mode, accept = _SAME_OWNER_EXEC[case]
    src = _pinned_src(tmp_path, kind, pinned, mode)
    before = _src_state(src)
    rec = _pinned_run(tmp_path, src, pinned, new_mode, accept)
    assert (tmp_path / "out" / "candidate" / pinned).lstat().st_mode & 0o777 == int(new_mode, 8)
    for arm in bench.ARMS:
        assert (rec[arm]["accept"], rec[arm]["accept_exit"], rec[arm]["error"]) == ("PASS", 0, None)
    assert rec["candidate"]["ignored_change_paths"] == []
    assert rec["comparison"]["verdict"] == "TIE_ON_ACCEPTANCE", rec["comparison"]
    assert _src_state(src) == before


@_posix_modes
@pytest.mark.parametrize("change", ["edit-content", "same-bytes-symlink"])
@pytest.mark.parametrize("kind", ["plain", "git"])
def test_pinned_check_content_edit_or_symlink_still_rejects(tmp_path, kind, change):
    src = _pinned_src(tmp_path, kind, "check.sh", 0o755)
    before = _src_state(src)
    cmd = {"edit-content": [sys.executable, "-c", "open('check.sh', 'a').write('# edited\\n')"],
           "same-bytes-symlink": [sys.executable, "-c", "import os; os.rename('check.sh', "
                                  "'real.sh'); os.symlink('real.sh', 'check.sh')"]}[change]
    out = tmp_path / "out"
    rec = bench.run_bench(repo=src, spec_path=_spec(tmp_path), budget_s=30,
                          baseline_cmd=_noop_cmd(), candidate_cmd=cmd, accept_cmd=["./check.sh"],
                          out_dir=out, check_files=["check.sh"], solution_files=["calc.py"])
    assert (rec["candidate"]["accept"], rec["candidate"]["accept_exit"]) == ("REJECTED", None)
    assert not (out / "candidate.accept.txt").exists()
    assert rec["baseline"]["accept"] == "PASS"
    assert rec["comparison"]["verdict"] == "UNSCORED"
    assert _src_state(src) == before


# --------------------------------------------------------------------------
# git source with core.fileMode=false: `git status` cannot see an owner-exec
# change there, so the bench compares the source's tracked REGULAR files (lstat,
# no link followed, untracked/ignored files never walked) with the owner-exec bit
# of the frozen HEAD archive, at freeze (BenchInputError, no out dir, no arm) and
# after the run (input_integrity.ok=false -> UNSCORED).
# --------------------------------------------------------------------------
def _filemode_src(tmp_path: pathlib.Path, filemode: str, worktree: bool = False) -> pathlib.Path:
    """Clean owned git repo: check.sh 100755, calc.py 100644, tool-link -> check.sh
    (a tracked symlink, so the archive carries a symlink member); fixture-local
    core.fileMode only. `worktree=True` returns a linked worktree of it."""
    src = _plain(tmp_path / "src", {"check.sh": (_EXIT0_SH, 0o755), "calc.py": (_FIX, 0o644)})
    os.symlink("check.sh", src / "tool-link")
    _owned_git(src, "init", "-q")
    _owned_git(src, "add", ".")
    _owned_git(src, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
               "commit", "-q", "-m", "fixture")
    _owned_git(src, "config", "--local", "core.fileMode", filemode)
    assert _owned_git(src, "ls-files", "-s", "check.sh").startswith("100755")
    assert _owned_git(src, "ls-files", "-s", "tool-link").startswith("120000")
    if worktree:
        wt = tmp_path / "wt"
        _owned_git(src, "worktree", "add", "-q", str(wt))
        assert (wt / ".git").is_file()
        return wt
    return src


def _git_bytes_state(src: pathlib.Path) -> dict:
    """HEAD, index and tracked bytes: everything EXCEPT the mode a test changes."""
    gitdir = pathlib.Path(_owned_git(src, "rev-parse", "--absolute-git-dir"))
    return {"head": _owned_git(src, "rev-parse", "HEAD"),
            "index": hashlib.sha256((gitdir / "index").read_bytes()).hexdigest(),
            "bytes": {n: (src / n).read_bytes() for n in ("check.sh", "calc.py")},
            "link": os.readlink(src / "tool-link")}


def _chmod_src(path: pathlib.Path, mode: int) -> list[str]:
    return [sys.executable, "-c", "import os; os.chmod(%r, %d)" % (str(path), mode)]


def _filemode_run(tmp_path, src, baseline):
    tmp_path.mkdir(parents=True, exist_ok=True)
    return bench.run_bench(repo=src, spec_path=_spec(tmp_path), budget_s=30,
                           baseline_cmd=baseline, candidate_cmd=_noop_cmd(),
                           accept_cmd=["./check.sh"], out_dir=tmp_path / "out",
                           check_files=["check.sh"], solution_files=["calc.py"])


@_posix_modes
def test_cli_git_filemode_false_source_chmod_during_run_is_unscored_not_a_tie(tmp_path):
    src = _filemode_src(tmp_path, "false")
    before = _git_bytes_state(src)
    _spec(tmp_path)
    cfg = tmp_path / "bench.json"
    cfg.write_text(json.dumps({"repo": "src", "spec": "spec.md", "budget_s": 30,
                               "baseline_cmd": _chmod_src(src / "check.sh", 0o644),
                               "candidate_cmd": _noop_cmd(),
                               "accept_cmd": ["./check.sh"], "check_files": ["check.sh"],
                               "solution_files": ["calc.py"]}), encoding="utf-8")
    out = tmp_path / "out"
    p = subprocess.run([sys.executable, str(_ROOT / "bench.py"), "run", "--config", str(cfg),
                        "--out", str(out)], capture_output=True, text=True, timeout=120,
                       env=_owned_env())
    assert (src / "check.sh").lstat().st_mode & 0o777 == 0o644, "the arm changed the source mode"
    assert _git_bytes_state(src) == before, "HEAD, index and bytes are unchanged"
    assert _owned_git(src, "status", "--porcelain", "--untracked-files=all") == "", \
        "core.fileMode=false: git status cannot see the change"
    assert (out / "baseline.accept-tree" / "check.sh").lstat().st_mode & 0o100, "frozen 0755"
    assert p.returncode == 2 and p.stdout.startswith("verdict: UNSCORED"), p.stdout + p.stderr
    rec = json.loads((out / "record.json").read_text(encoding="utf-8"))
    assert rec["baseline"]["accept"] == rec["candidate"]["accept"] == "PASS"
    assert rec["input_integrity"]["ok"] is False
    assert rec["input_integrity"]["observed"]["mode_drift"] == ["check.sh"]
    assert rec["comparison"]["verdict"] == "UNSCORED" and rec["comparison"]["winner"] is None
    assert any("input integrity" in r for r in rec["comparison"]["reasons"])
    assert not [k for k in rec["frozen"] if k.startswith("_")], "no private frozen metadata leaks"
    assert _cli_compare(out / "record.json").returncode == 2


@_posix_modes
@pytest.mark.parametrize("worktree", [False, True], ids=["repo", "linked-worktree"])
@pytest.mark.parametrize("target,mode", [("check.sh", 0o644), ("calc.py", 0o755)],
                         ids=["drop-owner-exec", "add-owner-exec"])
def test_git_filemode_false_source_owner_exec_flip_during_run_fails_integrity(
        tmp_path, target, mode, worktree):
    src = _filemode_src(tmp_path, "false", worktree=worktree)
    before = _git_bytes_state(src)
    rec = _filemode_run(tmp_path, src, _chmod_src(src / target, mode))
    assert (src / target).lstat().st_mode & 0o777 == mode
    assert _git_bytes_state(src) == before
    assert _owned_git(src, "status", "--porcelain", "--untracked-files=all") == ""
    assert rec["baseline"]["accept"] == rec["candidate"]["accept"] == "PASS"
    assert rec["input_integrity"]["ok"] is False
    assert rec["input_integrity"]["observed"]["mode_drift"] == [target]
    assert rec["comparison"]["verdict"] == "UNSCORED" and rec["comparison"]["winner"] is None


@_posix_modes
@pytest.mark.parametrize("target,mode", [("check.sh", 0o644), ("calc.py", 0o755)],
                         ids=["drop-owner-exec", "add-owner-exec"])
def test_git_filemode_false_source_chmod_before_freeze_is_rejected_before_any_arm(
        tmp_path, target, mode, monkeypatch, capsys):
    src = _filemode_src(tmp_path, "false")
    (src / target).chmod(mode)
    before = _git_bytes_state(src)
    assert _owned_git(src, "status", "--porcelain", "--untracked-files=all") == ""
    calls: list = []
    out = tmp_path / "out"
    with monkeypatch.context() as m:
        _spy_side_effects(m, calls)
        with pytest.raises(bench.BenchInputError, match="owner-exec") as exc:
            _filemode_run(tmp_path, src, _noop_cmd())
    assert target in str(exc.value)
    assert not out.exists(), "no out dir, record or arm copy"
    assert not [c for c in calls if c[0] in ("run_arm", "_materialize")], calls
    assert {c[1][1] for c in calls if c[0] in ("run", "Popen")} <= {"rev-parse", "status",
                                                                     "archive"}, calls
    assert all(c[1][0] == "git" for c in calls if c[0] in ("run", "Popen")), "no arm process"
    cfg = tmp_path / "bench.json"
    cfg.write_text(json.dumps({"repo": "src", "spec": "spec.md", "budget_s": 30,
                               "baseline_cmd": _noop_cmd(), "candidate_cmd": _noop_cmd(),
                               "accept_cmd": ["./check.sh"], "check_files": ["check.sh"],
                               "solution_files": ["calc.py"]}), encoding="utf-8")
    capsys.readouterr()
    rc = bench.main(["run", "--config", str(cfg), "--out", str(out)])
    assert rc == 2 and capsys.readouterr().out.startswith("REJECTED_INPUT:")
    assert not out.exists()
    assert _git_bytes_state(src) == before and (src / target).lstat().st_mode & 0o777 == mode


# Controls: these already hold on the parent; they pin that the fix is not a
# blanket refusal and that git status / existing rejections still apply.
@_posix_modes
@pytest.mark.parametrize("worktree", [False, True], ids=["repo", "linked-worktree"])
@pytest.mark.parametrize("filemode", ["false", "true"])
def test_git_clean_executable_source_with_tracked_symlink_still_scores(tmp_path, filemode,
                                                                        worktree):
    src = _filemode_src(tmp_path, filemode, worktree=worktree)
    before = _git_bytes_state(src)
    rec = _filemode_run(tmp_path, src, _noop_cmd())
    assert rec["input_integrity"] == {"ok": True, "observed": {"head": before["head"], "dirty": ""}}
    assert rec["comparison"]["verdict"] == "TIE_ON_ACCEPTANCE", rec["comparison"]
    assert not (tmp_path / "out" / "baseline" / "tool-link").exists(), "links are never copied"
    assert _git_bytes_state(src) == before


@_posix_modes
@pytest.mark.parametrize("filemode", ["false", "true"])
def test_git_source_group_other_only_chmod_during_run_is_not_a_change(tmp_path, filemode):
    src = _filemode_src(tmp_path, filemode)
    rec = _filemode_run(tmp_path, src, _chmod_src(src / "check.sh", 0o700))
    assert (src / "check.sh").lstat().st_mode & 0o777 == 0o700
    assert rec["input_integrity"]["ok"] is True
    assert rec["comparison"]["verdict"] == "TIE_ON_ACCEPTANCE", rec["comparison"]


@_posix_modes
def test_git_filemode_true_source_chmod_keeps_existing_dirty_rejections(tmp_path):
    src = _filemode_src(tmp_path, "true")
    rec = _filemode_run(tmp_path / "during", src, _chmod_src(src / "check.sh", 0o644))
    assert "check.sh" in rec["input_integrity"]["observed"]["dirty"]
    assert rec["input_integrity"]["ok"] is False and rec["comparison"]["verdict"] == "UNSCORED"
    with pytest.raises(bench.BenchInputError, match="dirty"):
        _filemode_run(tmp_path / "before", src, _noop_cmd())


@_posix_modes
@pytest.mark.parametrize("change", ["delete", "same-bytes-symlink"])
@pytest.mark.parametrize("filemode", ["false", "true"])
def test_git_source_file_removed_or_replaced_by_symlink_fails_closed(tmp_path, filemode, change):
    src = _filemode_src(tmp_path, filemode)
    p = str(src / "check.sh")
    cmd = {"delete": [sys.executable, "-c", "import os; os.unlink(%r)" % p],
           "same-bytes-symlink": [sys.executable, "-c", "import os; os.rename(%r, %r); "
                                  "os.symlink('real.sh', %r)" % (p, str(src / "real.sh"), p)]}
    rec = _filemode_run(tmp_path, src, cmd[change])
    assert rec["input_integrity"]["ok"] is False
    assert rec["comparison"]["verdict"] == "UNSCORED" and rec["comparison"]["winner"] is None
