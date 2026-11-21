"""Black-box behaviour tests for iter 551 -- ``foundry commit-check``: commit the
source worktree (untracked files included) inside a throwaway clone and run the
declared suite there, never touching the real index or refs.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-551 PM spec's Expected
Behaviors (1-10), the README, existing tests under ``tests/``, and the product's
OBSERVABLE behaviour (public functions, ``--help``, running the CLI).  The
implementation source, engineer/reviewer notes and ``git diff`` were NOT read.
B2-B7 run with a scripted ``run_cmd`` seam (zero real subprocess); B8/B9 build a
real-git fixture in tmp_path.  Nothing here depends on gitignored ambient state,
on HEAD's sha, or on a ``git show HEAD:`` baseline.
"""
import contextlib
import inspect
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

SETUP = "setupcmd --flag one"
TEST = "testcmd -q tests"
SENTINELS = {0: "COMMIT-CHECK: GREEN", 1: "COMMIT-CHECK: RED",
             2: "COMMIT-CHECK: INCOMPLETE"}
RED_OUT = (
    "..F.F\n"
    "=========================== short test summary info ===========================\n"
    "FAILED tests/test_alpha.py::test_one - assert 1 == 2\n"
    "FAILED tests/test_beta.py::test_two[x] - AssertionError: nope\n"
    "2 failed, 3 passed in 0.12s\n"
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
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
    assert pathlib.Path(cfg.state) == wr / "state"
    return cfg, str(p)


def _kind(argv, cfg):
    if argv[:2] == ["git", "clone"]:
        return "clone"
    if argv == shlex.split(cfg.setup_cmd):
        return "setup"
    if argv == shlex.split(cfg.test_cmd):
        return "test"
    for k, word in (("stage", "add"), ("commit", "commit"),
                    ("materialize", "reset"), ("scope", "status")):
        if word in argv:
            return k
    return "other"


class _H:
    def __init__(self):
        self.calls = []
        self.events = []

    @property
    def kinds(self):
        return [c["kind"] for c in self.calls]


def _install(monkeypatch, cfg, *, fail=(), scope_out="", test_ok=True,
             test_out="5 passed in 0.1s\n", raise_kind=None, step_cost=0.0,
             test_cost=None):
    h = _H()
    clock = {"t": 0.0}

    def fake_run_cmd(args, cwd=None, timeout=None, **kw):
        argv = [str(a) for a in args]
        kind = _kind(argv, cfg)
        h.calls.append({"argv": argv, "cwd": cwd, "timeout": timeout, "kind": kind})
        h.events.append(("cmd", kind))
        if raise_kind == kind:
            raise RuntimeError("boom-seam-551")
        if kind == "test":
            clock["t"] += test_cost(timeout) if test_cost else step_cost
            return foundry.CmdResult(test_ok, test_out)
        clock["t"] += step_cost
        if kind in fail:
            return foundry.CmdResult(False, kind + " failed xyz")
        if kind == "scope":
            return foundry.CmdResult(True, scope_out)
        return foundry.CmdResult(True, kind + " ok")

    def fake_cleanup(clone_dir):
        h.events.append(("cleanup", str(clone_dir)))

    def tripwire(*a, **k):
        raise AssertionError("real subprocess spawned: %r" % (a,))

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(foundry, "_try_cleanup_clone", fake_cleanup)
    monkeypatch.setattr(foundry, "_monotonic", lambda: clock["t"])
    monkeypatch.setattr(subprocess, "run", tripwire)
    monkeypatch.setattr(subprocess, "Popen", tripwire)
    return h


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


def _last(text):
    return [ln for ln in text.splitlines() if ln.strip()][-1]


def _run_cli(cfg, as_json=False):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.commit_check_cli(cfg, as_json=as_json)
    return rc, buf.getvalue()


# ==========================================================================
# B1 -- the verb exists
# ==========================================================================
def test_b1_help_exits_zero():
    r = subprocess.run([sys.executable, str(_ROOT / "foundry.py"), "commit-check", "--help"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "--config" in r.stdout and "--json" in r.stdout


def test_b1_verb_in_cli_verbs():
    src = (_ROOT / "foundry.py").read_text(encoding="utf-8")
    assert "commit-check" in foundry.foundry_cli_verbs(src)


# ==========================================================================
# B2 -- exact 7-command sequence, cwd, cleanup before and after
# ==========================================================================
def test_b2_happy_path_argv_sequence(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    clone = tmp_path / "cc"
    h = _install(monkeypatch, cfg)
    res = foundry.commit_check(cfg, clone)
    assert [c["argv"] for c in h.calls] == _expected_argv(cfg, clone)
    assert res.exit_code == 0
    assert res.verdict == "GREEN"
    assert list(res.failing_tests) == []


def test_b2_setup_and_test_run_in_clone(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    clone = tmp_path / "cc"
    h = _install(monkeypatch, cfg)
    foundry.commit_check(cfg, clone)
    by = {c["kind"]: c for c in h.calls}
    assert str(by["setup"]["cwd"]) == str(clone)
    assert str(by["test"]["cwd"]) == str(clone)


@pytest.mark.parametrize("mode", ["green", "red", "fail-stage", "raise"])
def test_b2_cleanup_first_and_last(tmp_path, monkeypatch, mode):
    cfg, _ = _cfg(tmp_path)
    clone = tmp_path / "cc"
    kw = {"green": {}, "red": {"test_ok": False, "test_out": RED_OUT},
          "fail-stage": {"fail": ("stage",)}, "raise": {"raise_kind": "commit"}}[mode]
    h = _install(monkeypatch, cfg, **kw)
    foundry.commit_check(cfg, clone)
    assert h.events[0] == ("cleanup", str(clone))
    assert h.events[-1] == ("cleanup", str(clone))
    first_cmd = next(i for i, e in enumerate(h.events) if e[0] == "cmd")
    assert first_cmd >= 1


# ==========================================================================
# B3 -- a failed step stops the run, exit 2, step named
# ==========================================================================
STEPS = ["clone", "stage", "commit", "materialize", "scope", "setup"]
ORDER = STEPS + ["test"]


@pytest.mark.parametrize("step", STEPS)
def test_b3_failed_step_stops_and_is_named(tmp_path, monkeypatch, step):
    cfg, _ = _cfg(tmp_path)
    h = _install(monkeypatch, cfg, fail=(step,))
    res = foundry.commit_check(cfg, tmp_path / "cc")
    assert h.kinds == ORDER[:ORDER.index(step) + 1]
    assert res.exit_code == 2
    assert res.verdict == "INCOMPLETE"
    assert step in res.detail
    assert list(res.failing_tests) == []


def test_b3_nonempty_scope_is_never_green(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    h = _install(monkeypatch, cfg, scope_out="?? stray.txt\n")
    res = foundry.commit_check(cfg, tmp_path / "cc")
    assert h.kinds == ORDER[:5]
    assert res.exit_code == 2
    assert "scope" in res.detail


# ==========================================================================
# B4 -- red suite: exit 1, failing ids listed as bullets
# ==========================================================================
def test_b4_red_names_failing_tests(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    _install(monkeypatch, cfg, test_ok=False, test_out=RED_OUT)
    res = foundry.commit_check(cfg, tmp_path / "cc")
    ids = foundry.test_failure_lines(RED_OUT)
    assert ids  # the oracle parsed something
    assert res.exit_code == 1 and res.verdict == "RED"
    assert list(res.failing_tests) == list(ids)
    lines = res.render().splitlines()
    for fid in ids:
        assert "- " + fid in [ln.strip() for ln in lines]


def test_b4_green_when_suite_ok(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    _install(monkeypatch, cfg, test_ok=True)
    res = foundry.commit_check(cfg, tmp_path / "cc")
    assert res.exit_code == 0


def test_b4_bullets_are_capped(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    many = "".join("FAILED tests/test_m.py::test_%d - x\n" % i for i in range(40))
    _install(monkeypatch, cfg, test_ok=False, test_out=many)
    res = foundry.commit_check(cfg, tmp_path / "cc")
    assert res.exit_code == 1
    assert 0 < len(res.failing_tests) < 40
    assert list(res.failing_tests) == list(foundry.test_failure_lines(many))


# ==========================================================================
# B5 -- budget read at call time, timeouts recomputed, exceptions contained
# ==========================================================================
def test_b5_budget_default():
    assert foundry.COMMIT_CHECK_BUDGET_SECONDS == 240.0


def test_b5_timeouts_recomputed_from_call_time_budget(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "COMMIT_CHECK_BUDGET_SECONDS", 200.0)
    h = _install(monkeypatch, cfg, step_cost=10.0)
    res = foundry.commit_check(cfg, tmp_path / "cc")
    assert res.exit_code == 0
    want = [foundry.preship_step_timeout(200.0 - 10.0 * i) for i in range(7)]
    assert [c["timeout"] for c in h.calls] == want


def test_b5_exhausted_budget_issues_no_more_commands(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "COMMIT_CHECK_BUDGET_SECONDS", 100.0)
    h = _install(monkeypatch, cfg, step_cost=30.0)
    res = foundry.commit_check(cfg, tmp_path / "cc")
    # remaining before commands: 100, 70, 40, 10, -20 -> only 4 issued
    assert h.kinds == ORDER[:4]
    assert res.exit_code == 2


def test_b5_suite_using_whole_slice_is_incomplete_not_red(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    h = _install(monkeypatch, cfg, test_ok=False, test_out=RED_OUT,
                 test_cost=lambda timeout: float(timeout))
    res = foundry.commit_check(cfg, tmp_path / "cc")
    assert h.kinds == ORDER
    assert res.exit_code == 2
    assert res.verdict == "INCOMPLETE"


@pytest.mark.parametrize("kind", ORDER)
def test_b5_seam_exception_is_exit2_with_repr(tmp_path, monkeypatch, kind):
    cfg, _ = _cfg(tmp_path)
    h = _install(monkeypatch, cfg, raise_kind=kind)
    res = foundry.commit_check(cfg, tmp_path / "cc")  # must not raise
    assert res.exit_code == 2
    assert repr(RuntimeError("boom-seam-551")) in res.detail
    assert h.kinds[-1] == kind


# ==========================================================================
# B6 -- detail-then-sentinel text output
# ==========================================================================
@pytest.mark.parametrize("mode,code", [("green", 0), ("red", 1), ("fail", 2)])
def test_b6_last_line_is_sentinel(tmp_path, monkeypatch, mode, code):
    cfg, _ = _cfg(tmp_path)
    kw = {"green": {}, "red": {"test_ok": False, "test_out": RED_OUT},
          "fail": {"fail": ("commit",)}}[mode]
    _install(monkeypatch, cfg, **kw)
    rc, out = _run_cli(cfg)
    assert rc == code
    assert _last(out) == SENTINELS[code]
    res = foundry.commit_check(cfg, tmp_path / "cc2")
    assert _last(res.render()) == SENTINELS[code]
    assert res.sentinel == SENTINELS[code] or SENTINELS[code].endswith(str(res.sentinel))


def test_b6_suite_seconds_na_when_suite_never_ran(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    _install(monkeypatch, cfg, fail=("clone",))
    res = foundry.commit_check(cfg, tmp_path / "cc")
    text = res.render()
    assert "n/a" in text
    assert "clone" in text


def test_b6_suite_seconds_shown_when_suite_ran(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    _install(monkeypatch, cfg, test_cost=lambda t: 7.0)
    res = foundry.commit_check(cfg, tmp_path / "cc")
    assert res.exit_code == 0
    assert res.test_seconds == pytest.approx(7.0)
    assert "n/a" not in res.render()
    assert "7" in res.render()


# ==========================================================================
# B7 -- --json document
# ==========================================================================
@pytest.mark.parametrize("mode,code,verdict", [("green", 0, "GREEN"), ("red", 1, "RED"),
                                               ("fail", 2, "INCOMPLETE")])
def test_b7_json_document(tmp_path, monkeypatch, mode, code, verdict):
    cfg, _ = _cfg(tmp_path)
    kw = {"green": {}, "red": {"test_ok": False, "test_out": RED_OUT},
          "fail": {"fail": ("scope",)}}[mode]
    _install(monkeypatch, cfg, **kw)
    rc, out = _run_cli(cfg, as_json=True)
    doc = json.loads(out)
    # iter 552: FORCED re-pin (OPERATOR 2026-11-21b) -- the CLI doc gains
    # `tree_key` and `budget_seconds`; `to_dict()` itself keeps its five keys.
    assert set(doc) == {"verdict", "exit_code", "detail", "failing_tests", "test_seconds",
                        "tree_key", "budget_seconds"}
    assert rc == code and doc["exit_code"] == code and doc["verdict"] == verdict
    assert isinstance(doc["failing_tests"], list)
    if code == 1:
        assert doc["failing_tests"] == list(foundry.test_failure_lines(RED_OUT))
    else:
        assert doc["failing_tests"] == []


def test_b7_cli_clone_dir_is_under_state(tmp_path, monkeypatch):
    cfg, _ = _cfg(tmp_path)
    h = _install(monkeypatch, cfg)
    _run_cli(cfg)
    want = str(pathlib.Path(cfg.state) / "commit_check_clone")
    # iter 552: FORCED re-pin -- the CLI reads the tree key before the run, so
    # the clone is the first CLONE call, no longer calls[0].
    clones = [c for c in h.calls if c["kind"] == "clone"]
    assert clones[0]["argv"] == ["git", "clone", str(cfg.repo), want]


# ==========================================================================
# B8/B9 -- real git, offline, in tmp_path
# ==========================================================================
def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                        *args], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


FAILING = "def test_bad():\n    assert 1 == 2\n"
PASSING = "def test_ok():\n    assert True\n"


@pytest.fixture
def real_repo(tmp_path):
    src = tmp_path / "src"
    (src / "tests").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(src)], check=True, timeout=60)
    (src / "tests" / "test_ok.py").write_text(PASSING)
    (src / ".gitignore").write_text("tests/test_ignored.py\n__pycache__/\n.pytest_cache/\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "init")
    # worktree changes: an untracked failing test, plus failing files hidden by
    # .gitignore and by .git/info/exclude
    (src / "tests" / "test_new_bad.py").write_text(FAILING)
    (src / "tests" / "test_ignored.py").write_text(FAILING.replace("test_bad", "test_ign"))
    (src / "tests" / "test_excluded.py").write_text(FAILING.replace("test_bad", "test_exc"))
    excl = src / ".git" / "info" / "exclude"
    excl.parent.mkdir(parents=True, exist_ok=True)
    excl.write_text(excl.read_text() + "\ntests/test_excluded.py\n" if excl.exists()
                    else "tests/test_excluded.py\n")
    test_cmd = "%s -m pytest -q -p no:cacheprovider tests" % shlex.quote(sys.executable)
    setup_cmd = "%s -c pass" % shlex.quote(sys.executable)
    cfg, cfg_path = _cfg(tmp_path, repo=src, setup=setup_cmd, test=test_cmd)
    return src, cfg, cfg_path


def _snap(src):
    return (_git(src, "status", "--porcelain"), _git(src, "rev-parse", "HEAD"),
            _git(src, "stash", "list"), _git(src, "ls-files", "-s"))


def _cli(cfg_path, *extra):
    return subprocess.run([sys.executable, str(_ROOT / "foundry.py"), "commit-check",
                           "--config", cfg_path, *extra],
                          capture_output=True, text=True, timeout=300)


def test_b8_real_git_red_then_green(real_repo):
    src, cfg, cfg_path = real_repo
    before = _snap(src)
    r = _cli(cfg_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert _last(r.stdout) == "COMMIT-CHECK: RED"
    assert "test_new_bad.py::test_bad" in r.stdout
    # hidden files never reach the clone
    assert "test_ign" not in r.stdout
    assert "test_exc" not in r.stdout
    assert _snap(src) == before
    assert _git(src, "stash", "list") == ""
    assert not (pathlib.Path(cfg.state) / "commit_check_clone").exists()
    # fix the untracked failure -> green
    (src / "tests" / "test_new_bad.py").write_text(PASSING.replace("test_ok", "test_new"))
    before2 = _snap(src)
    r2 = _cli(cfg_path, "--json")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    doc = json.loads(r2.stdout)
    assert doc["verdict"] == "GREEN" and doc["failing_tests"] == []
    assert isinstance(doc["test_seconds"], (int, float))
    assert _snap(src) == before2
    assert not (pathlib.Path(cfg.state) / "commit_check_clone").exists()


def test_b8_tracked_deletion_is_reflected_no_false_red(real_repo):
    """A tracked failing test DELETED in the worktree is absent from the committed
    tree, so it must not be reported (Mechanism: step 2 stages deletions)."""
    src, cfg, cfg_path = real_repo
    (src / "tests" / "test_new_bad.py").unlink()  # leave only the deletion + hidden files
    (src / "tests" / "test_doomed.py").write_text(FAILING.replace("test_bad", "test_doomed"))
    _git(src, "add", "tests/test_doomed.py")
    _git(src, "commit", "-q", "-m", "doomed")
    (src / "tests" / "test_doomed.py").unlink()
    r = _cli(cfg_path)
    assert "test_doomed" not in r.stdout, r.stdout
    assert r.returncode == 0, r.stdout + r.stderr
    assert _last(r.stdout) == "COMMIT-CHECK: GREEN"


def test_b8_deleted_dependency_is_never_green(real_repo):
    """Deleting a tracked module a committed test imports is red once committed;
    the committed-tree run must not report GREEN."""
    src, cfg, cfg_path = real_repo
    (src / "tests" / "test_new_bad.py").unlink()
    (src / "helper551.py").write_text("X = 1\n")
    (src / "tests" / "test_uses.py").write_text(
        "import sys, pathlib\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))\n"
        "from helper551 import X\n\n\ndef test_uses():\n    assert X == 1\n")
    _git(src, "add", "helper551.py", "tests/test_uses.py")
    _git(src, "commit", "-q", "-m", "helper")
    (src / "helper551.py").unlink()
    assert _git(src, "status", "--porcelain").splitlines().count(" D helper551.py") == 1
    r = _cli(cfg_path)
    assert r.returncode != 0, r.stdout + r.stderr
    assert _last(r.stdout) != "COMMIT-CHECK: GREEN"


def test_b9_clone_location_and_cleanup(real_repo):
    src, cfg, cfg_path = real_repo
    clone = pathlib.Path(cfg.state) / "commit_check_clone"
    clone.mkdir(parents=True)
    (clone / "stale.txt").write_text("leftover")  # cleaned before the clone step
    r = _cli(cfg_path)
    assert r.returncode in (0, 1), r.stdout + r.stderr  # decided, not INCOMPLETE
    assert not clone.exists()


def test_b9_preship_does_not_call_commit_check():
    for fn in (foundry.preship_cli, foundry.verify_local_clone):
        assert "commit_check(" not in inspect.getsource(fn)


# ==========================================================================
# B10 -- the tester card line
# ==========================================================================
STEP2 = "2. Run the FULL suite (the quality-check command from Context)."


def test_b10_card_line_appended_under_step2():
    lines = (_ROOT / "roles" / "tester.md").read_text(encoding="utf-8").splitlines()
    assert lines.count(STEP2) == 1
    nxt = lines[lines.index(STEP2) + 1]
    assert nxt.isascii()
    assert "python3 <checkout>/foundry.py commit-check --config <PRODUCT_CONFIG>" in nxt
    assert "COMMIT-CHECK:" in nxt
    assert "plain suite" in nxt


def test_b10_card_verbs():
    card = (_ROOT / "roles" / "tester.md").read_text(encoding="utf-8")
    assert foundry.role_card_verbs(card) == ("commit-check", "test-quality")
