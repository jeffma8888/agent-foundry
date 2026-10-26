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

import json
import pathlib
import subprocess
import sys

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
