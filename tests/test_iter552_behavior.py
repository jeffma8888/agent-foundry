"""Black-box behaviour tests for iter 552 -- OPERATOR 2026-11-21b pin, bite 1:
``foundry commit-check`` sizes its whole-run budget per product from post-release
suite times and reports the source worktree's ledger key; roles/tester.md says
``COMMIT-CHECK: INCOMPLETE`` is no verdict.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-552 PM spec's Expected
Behaviors (1-8), the README, existing tests under ``tests/``, the tester role
card, and the product's OBSERVABLE behaviour (public functions, running the
CLI).  The implementation source, engineer/reviewer notes and ``git diff`` were
NOT read.  Every fixture (git repos, postrelease.md files) is built in
tmp_path; nothing depends on gitignored ambient state, HEAD's sha, a
``git show HEAD:`` baseline, or wall-clock timing.
"""
import ast
import contextlib
import io
import json
import math
import pathlib
import shlex
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

SETUP = "setupcmd --flag one"
TEST = "testcmd -q tests"
SENTINELS = {0: "COMMIT-CHECK: GREEN", 1: "COMMIT-CHECK: RED",
             2: "COMMIT-CHECK: INCOMPLETE"}
RED_OUT = (
    "..F\n"
    "=========================== short test summary info ===========================\n"
    "FAILED tests/test_alpha.py::test_one - assert 1 == 2\n"
    "1 failed, 2 passed in 0.12s\n"
)
_REAL_RUN_CMD = foundry.run_cmd


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                        *args], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _real_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    subprocess.run(["git", "init", "-q", str(src)], check=True, timeout=60)
    (src / "a.txt").write_text("one\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "init")
    (src / "a.txt").write_text("one\ntwo\n")      # a tracked edit
    (src / "new.txt").write_text("untracked\n")   # an untracked file
    return src


def _cfg(tmp_path, repo="example-repo", setup=SETUP, test=TEST):
    wr = tmp_path / "wr"
    (wr / "state").mkdir(parents=True, exist_ok=True)
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "name": "fx", "repo": str(repo), "allowed_push_repo": "example-repo",
        "branch": "main", "work_root": str(wr),
        "setup_cmd": setup, "test_cmd": test,
    }))
    cfg = foundry.load_config(str(p))
    return cfg, str(p)


def _expected_argv(cfg, clone):
    c, r = str(clone), str(cfg.repo)
    return [
        ["git", "clone", r, c],
        ["git", "--git-dir=%s/.git" % c, "--work-tree=%s" % r, "add", "-A"],
        ["git", "-C", c, "-c", "user.name=foundry", "-c", "user.email=foundry@localhost",
         "commit", "-q", "--allow-empty", "-m", "commit-check"],
        ["git", "-C", c, "reset", "-q", "--hard"],
        ["git", "--git-dir=%s/.git" % c, "--work-tree=%s" % r, "status", "--porcelain"],
        shlex.split(cfg.setup_cmd),
        shlex.split(cfg.test_cmd),
    ]


PIPE_KINDS = ["clone", "stage", "commit", "materialize", "scope", "setup", "test"]


class _H:
    def __init__(self):
        self.calls = []
        self.phase = "before"

    def kinds(self):
        return [c["kind"] for c in self.calls]


def _install(monkeypatch, cfg, *, clone=None, test_ok=True, test_out="3 passed in 0.1s\n",
             key="script", step_cost=0.0, on_test=None, tripwire=True):
    """Script the 7 pipeline commands exactly (by argv); every OTHER command is
    a tree-key read.  key='script' answers it with a fixed ok output, 'fail'
    makes it fail, 'raise' makes it raise, 'real' passes it through to the real
    run_cmd (used with a real git repo).  Key-read failure can be confined to
    one phase with key='fail-after' / 'raise-before'."""
    h = _H()
    clock = {"t": 0.0}
    clone = clone or (pathlib.Path(cfg.state) / "commit_check_clone")
    pipe = {tuple(a): k for a, k in zip(_expected_argv(cfg, clone), PIPE_KINDS)}

    def fake_run_cmd(args, cwd=None, timeout=None, **kw):
        argv = [str(a) for a in args]
        kind = pipe.get(tuple(argv), "key")
        h.calls.append({"argv": argv, "cwd": cwd, "timeout": timeout, "kind": kind,
                        "phase": h.phase})
        if kind == "key":
            mode = key
            if mode == "real":
                return _REAL_RUN_CMD(args, cwd=cwd, timeout=timeout, **kw)
            if mode == "fail" or (mode == "fail-after" and h.phase == "after"):
                return foundry.CmdResult(False, "fatal: not a git repository")
            if mode == "raise" or (mode == "raise-before" and h.phase == "before"):
                raise RuntimeError("boom-key-552")
            return foundry.CmdResult(True, "0123456789abcdef0123456789abcdef01234567\n")
        clock["t"] += step_cost
        if kind == "clone":
            h.phase = "during"
        if kind == "test":
            h.phase = "after"
            if on_test:
                on_test()
            return foundry.CmdResult(test_ok, test_out)
        if kind == "scope":
            return foundry.CmdResult(True, "")
        return foundry.CmdResult(True, kind + " ok")

    def trip(*a, **k):
        raise AssertionError("real subprocess spawned: %r" % (a,))

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(foundry, "_try_cleanup_clone", lambda d: None)
    monkeypatch.setattr(foundry, "_monotonic", lambda: clock["t"])
    if tripwire:
        monkeypatch.setattr(subprocess, "run", trip)
        monkeypatch.setattr(subprocess, "Popen", trip)
    return h


def _run_cli(cfg, as_json=False):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.commit_check_cli(cfg, as_json=as_json)
    return rc, buf.getvalue()


def _nonempty(text):
    return [ln for ln in text.splitlines() if ln.strip()]


def _line(text, label):
    hits = [ln for ln in text.splitlines() if ln.startswith("  %s:" % label)]
    assert len(hits) == 1, (label, text)
    return hits[0]


def _write_postrelease(cfg, iteration, seconds):
    d = pathlib.Path(cfg.state) / ("iter-%02d" % iteration)
    d.mkdir(parents=True, exist_ok=True)
    (d / "postrelease.md").write_text(
        "post-release verification report\n\n"
        "- suite_seconds: %s\n"
        "POSTRELEASE: HEALTHY\n" % seconds)


# ==========================================================================
# B1 -- pure commit_check_budget
# ==========================================================================
def test_b1_module_globals():
    assert foundry.COMMIT_CHECK_BUDGET_WINDOW == 8
    assert foundry.COMMIT_CHECK_BUDGET_FACTOR == 1.25
    assert foundry.COMMIT_CHECK_BUDGET_MARGIN_SECONDS == 60.0
    assert foundry.COMMIT_CHECK_BUDGET_CEILING_SECONDS == 480.0
    assert foundry.COMMIT_CHECK_BUDGET_SECONDS == 240.0


@pytest.mark.parametrize("seconds,want", [
    ([241.01], 362.0), ([167.07], 269.0), ([135.44], 240.0), ([], 240.0),
    ([1000], 480.0), ([500, 1, 1, 1, 1, 1, 1, 1, 1], 240.0),
    ([100, 241.01, 50], 362.0), ((167.07,), 269.0), ([0], 240.0),
])
def test_b1_spec_examples(seconds, want):
    got = foundry.commit_check_budget(seconds)
    assert isinstance(got, float)
    assert got == want


def test_b1_generator_input():
    assert foundry.commit_check_budget(x for x in [241.01]) == 362.0


def test_b1_window_counts_only_valid_entries():
    # filter first, THEN window: 8 valid entries remain, so the 500 is inside it
    assert foundry.commit_check_budget([500, None, 1, 1, 1, 1, 1, 1, 1]) == 480.0
    assert foundry.commit_check_budget([500, "x", float("nan"), 1, 1, 1, 1, 1, 1, 1]) == 480.0


@pytest.mark.parametrize("junk", [
    [True], [False], [None], ["300"], [float("nan")], [float("inf")],
    [float("-inf")], [-100], [-0.5, None, "x", True],
])
def test_b1_invalid_entries_are_dropped(monkeypatch, junk):
    # floor 0 + a huge margin: any KEPT entry would push the result to the
    # ceiling; with every entry dropped the result is the bare floor global.
    monkeypatch.setattr(foundry, "COMMIT_CHECK_BUDGET_SECONDS", 0.0)
    monkeypatch.setattr(foundry, "COMMIT_CHECK_BUDGET_MARGIN_SECONDS", 1000.0)
    got = foundry.commit_check_budget(junk)
    assert isinstance(got, float)
    assert got == 0.0


def test_b1_valid_ints_and_floats_are_kept(monkeypatch):
    monkeypatch.setattr(foundry, "COMMIT_CHECK_BUDGET_SECONDS", 0.0)
    assert foundry.commit_check_budget([100]) == 185.0
    assert foundry.commit_check_budget([100.0, True]) == 185.0


@pytest.mark.parametrize("bad", [None, 5, 3.5, object(), "abc", b"\xff", {"a": 1},
                                 [10 ** 400], [[1]], [complex(1, 2)]])
def test_b1_never_raises(bad):
    got = foundry.commit_check_budget(bad)
    assert isinstance(got, float)
    assert 240.0 <= got <= 480.0


def test_b1_non_iterable_is_floor():
    assert foundry.commit_check_budget(None) == 240.0
    assert foundry.commit_check_budget(5) == 240.0


def test_b1_globals_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "COMMIT_CHECK_BUDGET_WINDOW", 1)
    assert foundry.commit_check_budget([1000, 100]) == 240.0  # only the 100 counts
    monkeypatch.setattr(foundry, "COMMIT_CHECK_BUDGET_FACTOR", 2.0)
    monkeypatch.setattr(foundry, "COMMIT_CHECK_BUDGET_MARGIN_SECONDS", 0.5)
    assert foundry.commit_check_budget([150]) == 301.0  # ceil(300.5)
    monkeypatch.setattr(foundry, "COMMIT_CHECK_BUDGET_SECONDS", 400.0)
    assert foundry.commit_check_budget([150]) == 400.0
    assert foundry.commit_check_budget([]) == 400.0
    monkeypatch.setattr(foundry, "COMMIT_CHECK_BUDGET_CEILING_SECONDS", 450.0)
    assert foundry.commit_check_budget([1000]) == 450.0


def test_b1_rounds_up_to_whole_seconds():
    got = foundry.commit_check_budget([200.001])
    assert got == float(math.ceil(1.25 * 200.001 + 60)) == 311.0


# ==========================================================================
# B2 -- commit_check(cfg, clone_dir, budget=None)
# ==========================================================================
def test_b2_default_budget_reads_global_at_call_time(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    clone = tmp_path / "cc"
    monkeypatch.setattr(foundry, "COMMIT_CHECK_BUDGET_SECONDS", 200.0)
    h = _install(monkeypatch, cfg, clone=clone, step_cost=10.0)
    res = foundry.commit_check(cfg, clone, budget=None)
    assert res.exit_code == 0
    want = [foundry.preship_step_timeout(200.0 - 10.0 * i) for i in range(7)]
    assert [c["timeout"] for c in h.calls] == want
    assert h.kinds() == PIPE_KINDS  # the inner verb reads no tree key


def test_b2_numeric_budget_replaces_global(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    clone = tmp_path / "cc"
    h = _install(monkeypatch, cfg, clone=clone, step_cost=10.0)
    res = foundry.commit_check(cfg, clone, budget=362.0)
    assert res.exit_code == 0
    want = [foundry.preship_step_timeout(362.0 - 10.0 * i) for i in range(7)]
    assert [c["timeout"] for c in h.calls] == want
    assert [c["timeout"] for c in h.calls] != [
        foundry.preship_step_timeout(240.0 - 10.0 * i) for i in range(7)]


def test_b2_exhausted_numeric_budget_is_incomplete_and_echoed(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    clone = tmp_path / "cc"
    h = _install(monkeypatch, cfg, clone=clone, step_cost=30.0)
    res = foundry.commit_check(cfg, clone, budget=100.0)
    # remaining before commands: 100, 70, 40, 10, -20 -> only 4 issued
    assert h.kinds() == PIPE_KINDS[:4]
    assert res.exit_code == 2 and res.verdict == "INCOMPLETE"
    assert "100" in res.detail


def test_b2_to_dict_keeps_five_keys(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    _install(monkeypatch, cfg, clone=tmp_path / "cc")
    res = foundry.commit_check(cfg, tmp_path / "cc", budget=300.0)
    assert set(res.to_dict()) == {"verdict", "exit_code", "detail", "failing_tests",
                                  "test_seconds"}


# ==========================================================================
# B3 -- the CLI sizes the budget from gather_timing
# ==========================================================================
def test_b3_no_postrelease_runs_with_floor(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    h = _install(monkeypatch, cfg)
    rc, out = _run_cli(cfg, as_json=True)
    doc = json.loads(out)
    assert rc == 0
    assert doc["budget_seconds"] == 240.0 and isinstance(doc["budget_seconds"], float)
    clone = next(c for c in h.calls if c["kind"] == "clone")
    assert clone["timeout"] == foundry.preship_step_timeout(240.0)


def test_b3_postrelease_history_sizes_the_budget(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    for i, s in enumerate([204.4, 241.01, 220.0], start=10):
        _write_postrelease(cfg, i, s)
    assert foundry.gather_timing(cfg).measured_seconds  # the fixture is measured
    h = _install(monkeypatch, cfg)
    rc, out = _run_cli(cfg, as_json=True)
    doc = json.loads(out)
    assert rc == 0
    assert doc["budget_seconds"] == 362.0
    clone = next(c for c in h.calls if c["kind"] == "clone")
    assert clone["timeout"] == foundry.preship_step_timeout(362.0)
    _, text = _run_cli(cfg)
    assert _line(text, "budget") == "  budget:        362s"


def test_b3_gather_timing_raising_falls_back_to_floor(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    _write_postrelease(cfg, 10, 241.01)

    def boom(*a, **k):
        raise RuntimeError("timing-boom")

    monkeypatch.setattr(foundry, "gather_timing", boom)
    _install(monkeypatch, cfg)
    rc, out = _run_cli(cfg, as_json=True)
    assert rc == 0
    assert json.loads(out)["budget_seconds"] == 240.0


# ==========================================================================
# B4 -- tree key read before and after the run
# ==========================================================================
def test_b4_equal_keys_match_ledger_key_verb(tmp_path, monkeypatch):
    src = _real_repo(tmp_path)
    cfg, cfg_path = _cfg(tmp_path, repo=src)
    lk = subprocess.run([sys.executable, str(_ROOT / "foundry.py"), "ledger-key",
                         "--config", cfg_path, "--json"],
                        capture_output=True, text=True, timeout=120)
    want = json.loads(lk.stdout)["key"]
    assert want and "+" in want
    h = _install(monkeypatch, cfg, key="real", tripwire=False)
    rc, out = _run_cli(cfg, as_json=True)
    doc = json.loads(out)
    assert rc == 0 and doc["verdict"] == "GREEN"
    assert doc["tree_key"] == want
    phases = [c["phase"] for c in h.calls if c["kind"] == "key"]
    assert "before" in phases and "after" in phases  # read once before, once after
    rc2, text = _run_cli(cfg)
    assert rc2 == 0
    assert _line(text, "tree key") == "  tree key:      " + want


@pytest.mark.parametrize("ok,code", [(True, 0), (False, 1)])
def test_b4_worktree_changed_during_run_is_incomplete(tmp_path, monkeypatch, ok, code):
    src = _real_repo(tmp_path)
    cfg, _ = _cfg(tmp_path, repo=src)
    counter = {"n": 0}

    def touch():
        counter["n"] += 1
        (src / ("touched%d.txt" % counter["n"])).write_text("changed mid-run\n")

    _install(monkeypatch, cfg, key="real", tripwire=False, test_ok=ok,
             test_out="3 passed\n" if ok else RED_OUT, on_test=touch)
    rc, out = _run_cli(cfg, as_json=True)
    doc = json.loads(out)
    assert rc == 2 and doc["exit_code"] == 2 and doc["verdict"] == "INCOMPLETE"
    assert "worktree changed during the run" in doc["detail"]
    rc2, text = _run_cli(cfg)
    assert rc2 == 2
    assert _nonempty(text)[-1] == SENTINELS[2]
    assert "worktree changed during the run" in text


def test_b4_unchanged_real_tree_with_red_suite_stays_red(tmp_path, monkeypatch):
    src = _real_repo(tmp_path)
    cfg, _ = _cfg(tmp_path, repo=src)
    _install(monkeypatch, cfg, key="real", tripwire=False, test_ok=False, test_out=RED_OUT)
    rc, out = _run_cli(cfg, as_json=True)
    doc = json.loads(out)
    assert rc == 1 and doc["verdict"] == "RED"
    assert isinstance(doc["tree_key"], str) and doc["tree_key"]
    assert "worktree changed" not in doc["detail"]


@pytest.mark.parametrize("key", ["fail", "raise", "fail-after", "raise-before"])
@pytest.mark.parametrize("ok,code", [(True, 0), (False, 1)])
def test_b4_unreadable_key_is_unknown_verdict_unchanged(tmp_path, monkeypatch, key, ok, code):
    cfg, _ = _cfg(tmp_path)
    _install(monkeypatch, cfg, key=key, test_ok=ok, test_out="3 passed\n" if ok else RED_OUT)
    rc, out = _run_cli(cfg, as_json=True)
    doc = json.loads(out)
    assert rc == code and doc["exit_code"] == code
    assert doc["verdict"] == ("GREEN" if ok else "RED")
    assert doc["tree_key"] is None
    rc2, text = _run_cli(cfg)
    assert rc2 == code
    assert _line(text, "tree key").startswith("  tree key:      UNKNOWN -- ")
    assert len(_line(text, "tree key")) > len("  tree key:      UNKNOWN -- ")
    assert _nonempty(text)[-1] == SENTINELS[code]


def test_b4_real_cli_end_to_end_reports_ledger_key(tmp_path):
    """No seams at all: a real clone + a trivial suite; the reported key equals
    the one `foundry ledger-key` prints for the same tree."""
    src = _real_repo(tmp_path)
    py = shlex.quote(sys.executable)
    cfg, cfg_path = _cfg(tmp_path, repo=src, setup="%s -c pass" % py,
                         test="%s -c pass" % py)
    lk = subprocess.run([sys.executable, str(_ROOT / "foundry.py"), "ledger-key",
                         "--config", cfg_path, "--json"],
                        capture_output=True, text=True, timeout=120)
    want = json.loads(lk.stdout)["key"]
    r = subprocess.run([sys.executable, str(_ROOT / "foundry.py"), "commit-check",
                        "--config", cfg_path],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "  tree key:      " + want in r.stdout.splitlines()
    assert _nonempty(r.stdout)[-1] == SENTINELS[0]


# ==========================================================================
# B5 -- text output: budget + tree key lines above the sentinel
# ==========================================================================
@pytest.mark.parametrize("ok,code", [(True, 0), (False, 1)])
def test_b5_text_lines_above_sentinel(tmp_path, monkeypatch, ok, code):
    cfg, _ = _cfg(tmp_path)
    _install(monkeypatch, cfg, test_ok=ok, test_out="3 passed\n" if ok else RED_OUT)
    rc, text = _run_cli(cfg)
    assert rc == code
    lines = text.splitlines()
    b = lines.index(_line(text, "budget"))
    k = lines.index(_line(text, "tree key"))
    s = lines.index(SENTINELS[code])
    assert b < s and k < s
    assert _line(text, "budget") == "  budget:        240s"
    assert _nonempty(text)[-1] == SENTINELS[code]


def test_b5_incomplete_inner_run_still_prints_lines(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    _install(monkeypatch, cfg, step_cost=100.0)  # 240 s budget exhausted mid-run
    rc, text = _run_cli(cfg)
    assert rc == 2
    assert _line(text, "budget") == "  budget:        240s"
    _line(text, "tree key")
    assert _nonempty(text)[-1] == SENTINELS[2]


# ==========================================================================
# B6 -- --json is one document with 7 keys
# ==========================================================================
@pytest.mark.parametrize("ok,code", [(True, 0), (False, 1)])
def test_b6_json_seven_keys_same_exit(tmp_path, monkeypatch, ok, code):
    cfg, _ = _cfg(tmp_path)
    _install(monkeypatch, cfg, test_ok=ok, test_out="3 passed\n" if ok else RED_OUT)
    rc_t, _ = _run_cli(cfg)
    rc, out = _run_cli(cfg, as_json=True)
    doc = json.loads(out)  # exactly one document
    assert set(doc) == {"verdict", "exit_code", "detail", "failing_tests", "test_seconds",
                        "tree_key", "budget_seconds"}
    assert rc == rc_t == code == doc["exit_code"]
    assert isinstance(doc["budget_seconds"], float)
    assert doc["tree_key"] is None or isinstance(doc["tree_key"], str)


# ==========================================================================
# B7 -- roles/tester.md INCOMPLETE line
# ==========================================================================
STEP2 = "2. Run the FULL suite (the quality-check command from Context)."


def _card_lines():
    return (_ROOT / "roles" / "tester.md").read_text(encoding="utf-8").splitlines()


def test_b7_new_line_directly_after_commit_check_line():
    lines = _card_lines()
    i = lines.index(STEP2)
    cc_line = lines[i + 1]
    assert "python3 <checkout>/foundry.py commit-check --config <PRODUCT_CONFIG>" in cc_line
    new = lines[i + 2]
    assert new.isascii()
    assert "COMMIT-CHECK: INCOMPLETE" in new
    assert "no verdict" in new.lower()
    assert "RESULT: FAIL" in new
    assert "plain suite" in new
    assert "ONCE" in new or "once" in new
    assert "tree key:" in new
    assert "verbatim" in new
    assert "GREEN" in new
    assert "foundry.py" not in new


def test_b7_card_verbs_unchanged():
    card = (_ROOT / "roles" / "tester.md").read_text(encoding="utf-8")
    assert foundry.role_card_verbs(card) == ("commit-check", "test-quality")


# ==========================================================================
# B8 -- forced re-pins and the b15 allow-list row
# ==========================================================================
def _b15_expected_set():
    tree = ast.parse((_ROOT / "tests" / "test_iter204_behavior.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "test_b15_only_the_three_expected_test_files_differ_from_head")
    for n in ast.walk(fn):
        if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "expected"
                                              for t in n.targets)
                and isinstance(n.value, ast.Set)):
            return [e.value for e in n.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    raise AssertionError("b15 `expected` set literal not found")


def test_b8_b15_expected_set_gains_the_551_row():
    rows = _b15_expected_set()
    assert rows.count("tests/test_iter551_behavior.py") == 1
    assert rows[-1] == "tests/test_iter541_behavior.py"
    assert rows.index("tests/test_iter551_behavior.py") == len(rows) - 2


def test_b8_iter551_b7_repins():
    text = (_ROOT / "tests" / "test_iter551_behavior.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    fns = {n.name: ast.get_source_segment(text, n) for n in tree.body
           if isinstance(n, ast.FunctionDef)}
    assert '"tree_key"' in fns["test_b7_json_document"]
    assert '"budget_seconds"' in fns["test_b7_json_document"]
    assert "h.calls[0]" not in fns["test_b7_cli_clone_dir_is_under_state"]
    assert "test_b5_budget_default" in fns
    assert "== 240.0" in fns["test_b5_budget_default"]
