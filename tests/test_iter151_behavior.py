"""Black-box behaviour tests for iter 151 -- capture the uncommitted tree as a patch
before `revert_repo` hard-resets it.

Spec: products/_platform/state/iter-151/pm.md, Expected Behaviors 1-10.

  1.  `capture_abort_patch(cfg, reason)` is a module-level function returning the
      `pathlib.Path` it wrote, or `None` when it wrote nothing.
  2.  `revert_repo` invokes it by BARE module name BEFORE its first `git` call, so
      `monkeypatch.setattr(foundry, "capture_abort_patch", recorder)` intercepts it and
      one shared recording list proves capture-before-reset ordering.
  3.  BLOCKING INVARIANT -- with the seam monkeypatched to raise, `revert_repo` still
      issues ("reset", "--hard", "origin/<branch>") then ("clean", "-fd") in that order,
      still calls `log` exactly once, and itself raises nothing.
  4.  with a non-empty ("diff", "HEAD") result and a state dir holding `iter-07` and
      `iter-12`, the patch lands in `iter-12` and its text is the diff plus exactly one
      trailing newline; selection is NUMERIC, not lexical (iter-99 vs iter-151).
  5.  ("add", "-A", "-N") is recorded strictly BEFORE ("diff", "HEAD").
  6.  an empty or whitespace-only diff writes no file anywhere under `cfg.state` and
      returns None.
  7.  a missing `cfg.state`, or one with no `iter-*` dir, writes nothing, creates no
      directory, returns None and raises nothing.
  8.  a DIRECTORY occupying the patch path -> returns None, raises nothing.
  9.  an existing patch from an earlier abort in the same iteration is OVERWRITTEN.
  10. a written patch logs exactly once with a message containing
      `ABORTED_IMPLEMENTATION.patch`; behaviors 6/7/8 log zero times.
  11. (acceptance criterion) `foundry` and `dispatcher` import in a clean interpreter.

ISOLATION CONTRACT (HONORED): every check below was derived ONLY from the iter-151 PM
spec's Expected Behaviors, the pre-existing tests under `tests/` (chiefly
`tests/test_iter126_behavior.py` for the tmp-config helper and
`tests/test_iter116_behavior.py` for the tree-snapshot / raising-seam idioms), and the
product's OWN observable behaviour driven through its public interface plus runtime
introspection (`inspect.signature`). The implementation source of `foundry.py`, the
engineer's and reviewer's notes, and `git diff` were NOT read. Fully offline: the `git`
and `log` seams are scripted, no real git, no real subprocess except the one
clean-interpreter import probe, no network. Source is pure ASCII.
"""
import inspect
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH_NAME = "ABORTED_IMPLEMENTATION.patch"
DIFF = "diff --git a/foundry.py b/foundry.py\n@@ -1 +1 @@\n-old\n+new"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _cfg(tmp_path, **over):
    """A minimal product config whose repo/work_root live in tmp, so the real foundry
    repo and state tree are NEVER touched."""
    tmp_path = pathlib.Path(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "branch": "main",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    n = len(list(tmp_path.glob("cfg_*.json")))
    p = tmp_path / ("cfg_%d.json" % n)
    p.write_text(json.dumps(data))
    return foundry.load_config(str(p))


def _iters(cfg, *names):
    """Create the given iter-NN dirs under cfg.state and return the state Path."""
    state = pathlib.Path(cfg.state)
    for n in names:
        (state / n).mkdir(parents=True, exist_ok=True)
    return state


def _script_git(monkeypatch, calls, results=None, default=""):
    """Install a scripted `foundry.git` seam recording each argument tuple."""
    table = dict(results or {})

    def fake_git(cfg, *args):
        calls.append(tuple(args))
        return table.get(tuple(args), default)

    monkeypatch.setattr(foundry, "git", fake_git)
    return calls


def _script_log(monkeypatch, msgs):
    monkeypatch.setattr(foundry, "log", lambda cfg, msg: msgs.append(msg))
    return msgs


def _files_under(root):
    root = pathlib.Path(root)
    if not root.exists():
        return []
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def _boom(*a, **k):
    raise RuntimeError("seam raised on purpose")


# --------------------------------------------------------------------------
# behavior 1 -- the seam exists and has the documented shape
# --------------------------------------------------------------------------
def test_b1_capture_abort_patch_is_module_level_callable():
    fn = getattr(foundry, "capture_abort_patch", None)
    assert fn is not None, "foundry.capture_abort_patch is missing"
    assert inspect.isfunction(fn), "not a module-level function: %r" % (fn,)
    assert list(inspect.signature(fn).parameters)[:2] == ["cfg", "reason"]


def test_b1_returns_path_when_written_and_none_when_not(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _iters(cfg, "iter-04")
    _script_git(monkeypatch, [], {("diff", "HEAD"): DIFF})
    _script_log(monkeypatch, [])
    got = foundry.capture_abort_patch(cfg, "stage failed")
    assert isinstance(got, pathlib.Path), "expected a Path, got %r" % (got,)
    assert got.name == PATCH_NAME and got.is_file()

    cfg2 = _cfg(tmp_path, name="demoprod2", work_root=str(tmp_path / "work2"))
    _iters(cfg2, "iter-04")
    _script_git(monkeypatch, [], {("diff", "HEAD"): ""})
    assert foundry.capture_abort_patch(cfg2, "stage failed") is None


# --------------------------------------------------------------------------
# behavior 2 -- bare-name call, BEFORE the first git call
# --------------------------------------------------------------------------
def test_b2_revert_repo_captures_before_any_git_call(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    order = []
    monkeypatch.setattr(foundry, "capture_abort_patch",
                        lambda c, r: order.append(("capture", r)))
    monkeypatch.setattr(foundry, "git",
                        lambda c, *a: (order.append(("git",) + tuple(a)), "")[1])
    monkeypatch.setattr(foundry, "log", lambda c, m: order.append(("log", m)))

    foundry.revert_repo(cfg, "tester stalled")

    kinds = [e[0] for e in order]
    assert "capture" in kinds, "capture_abort_patch was never called: %r" % (order,)
    assert kinds.index("capture") == 0, "capture is not first: %r" % (kinds,)
    assert kinds.index("capture") < kinds.index("git"), kinds
    assert order[0] == ("capture", "tester stalled"), order[0]


# --------------------------------------------------------------------------
# behavior 3 -- BLOCKING: a raising capture cannot stop the revert
# --------------------------------------------------------------------------
def test_b3_raising_capture_still_resets_cleans_and_logs_once(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    calls, msgs = [], []
    monkeypatch.setattr(foundry, "capture_abort_patch", _boom)
    _script_git(monkeypatch, calls)
    _script_log(monkeypatch, msgs)

    foundry.revert_repo(cfg, "boom reason")  # must NOT raise

    assert ("reset", "--hard", "origin/main") in calls, calls
    assert ("clean", "-fd") in calls, calls
    assert calls.index(("reset", "--hard", "origin/main")) < calls.index(("clean", "-fd"))
    assert len(msgs) == 1, "log called %d times: %r" % (len(msgs), msgs)


def test_b3_raising_capture_matches_the_healthy_git_sequence(tmp_path, monkeypatch):
    """Two-sided: the raising path issues the SAME git tuples as a no-op capture."""
    cfg = _cfg(tmp_path)
    healthy, broken = [], []
    monkeypatch.setattr(foundry, "capture_abort_patch", lambda c, r: None)
    _script_git(monkeypatch, healthy)
    _script_log(monkeypatch, [])
    foundry.revert_repo(cfg, "r")
    monkeypatch.setattr(foundry, "capture_abort_patch", _boom)
    _script_git(monkeypatch, broken)
    foundry.revert_repo(cfg, "r")
    assert broken == healthy and healthy, (healthy, broken)


def test_b3_capture_abort_patch_is_total_against_a_hostile_cfg(monkeypatch):
    """Acceptance criterion: the body catches Exception and returns None."""
    class Hostile:
        branch = "main"

        @property
        def state(self):
            raise RuntimeError("cfg.state exploded")

    _script_log(monkeypatch, [])
    assert foundry.capture_abort_patch(Hostile(), "reason") is None


# --------------------------------------------------------------------------
# behaviors 4 + 5 + 10 -- where it lands, what it contains, what it logs
# --------------------------------------------------------------------------
def test_b4_writes_into_highest_numbered_iter_dir_with_one_trailing_newline(
        tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-07", "iter-12")
    calls, msgs = [], []
    _script_git(monkeypatch, calls, {("diff", "HEAD"): DIFF})
    _script_log(monkeypatch, msgs)

    got = foundry.capture_abort_patch(cfg, "stage failed")

    target = state / "iter-12" / PATCH_NAME
    assert got == target, "wrote %r, expected %r" % (got, target)
    assert not (state / "iter-07" / PATCH_NAME).exists()
    text = target.read_text()
    assert text == DIFF + "\n", repr(text)
    assert not text.endswith("\n\n")
    assert _files_under(state) == ["iter-12/" + PATCH_NAME], _files_under(state)
    # behavior 10 (written half)
    assert len(msgs) == 1, msgs
    assert PATCH_NAME in msgs[0], msgs[0]


def test_b4_iter_dir_selection_is_numeric_not_lexical(tmp_path, monkeypatch):
    """'iter-151' sorts BELOW 'iter-99' lexically but ABOVE it numerically."""
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-99", "iter-151")
    _script_git(monkeypatch, [], {("diff", "HEAD"): DIFF})
    _script_log(monkeypatch, [])

    got = foundry.capture_abort_patch(cfg, "r")

    assert got == state / "iter-151" / PATCH_NAME, got
    assert not (state / "iter-99" / PATCH_NAME).exists()


def test_b4_non_iter_dirs_and_files_are_ignored(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-03", "iter-xx", "iterations", "iter-")
    (state / "iter-9999.txt").write_text("not a dir")
    _script_git(monkeypatch, [], {("diff", "HEAD"): DIFF})
    _script_log(monkeypatch, [])

    got = foundry.capture_abort_patch(cfg, "r")

    assert got == state / "iter-03" / PATCH_NAME, got


def test_b5_records_intent_to_add_strictly_before_the_diff(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _iters(cfg, "iter-05")
    calls = []
    _script_git(monkeypatch, calls, {("diff", "HEAD"): DIFF})
    _script_log(monkeypatch, [])

    foundry.capture_abort_patch(cfg, "r")

    assert ("add", "-A", "-N") in calls, calls
    assert ("diff", "HEAD") in calls, calls
    assert calls.index(("add", "-A", "-N")) < calls.index(("diff", "HEAD")), calls


# --------------------------------------------------------------------------
# behaviors 6, 7, 8 -- the three write-nothing paths (each also logs zero times)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("diff_text", ["", "   ", "\n", " \n\t\n "])
def test_b6_empty_or_whitespace_diff_writes_nothing(tmp_path, monkeypatch, diff_text):
    cfg = _cfg(tmp_path, work_root=str(tmp_path / ("w_%d" % len(diff_text))))
    state = _iters(cfg, "iter-08")
    msgs = []
    _script_git(monkeypatch, [], {("diff", "HEAD"): diff_text})
    _script_log(monkeypatch, msgs)

    assert foundry.capture_abort_patch(cfg, "r") is None
    assert _files_under(state) == [], _files_under(state)
    assert msgs == [], msgs


def test_b7_missing_state_dir_writes_nothing_and_creates_nothing(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = pathlib.Path(cfg.state)
    if state.exists():
        shutil.rmtree(state)
    assert not state.exists()
    msgs = []
    _script_git(monkeypatch, [], {("diff", "HEAD"): DIFF})
    _script_log(monkeypatch, msgs)

    assert foundry.capture_abort_patch(cfg, "r") is None
    assert not state.exists(), "capture created the state dir"
    assert msgs == [], msgs


def test_b7_state_dir_without_any_iter_dir_writes_nothing(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = pathlib.Path(cfg.state)
    state.mkdir(parents=True, exist_ok=True)
    (state / "notes").mkdir(exist_ok=True)
    before = _files_under(state)
    msgs = []
    _script_git(monkeypatch, [], {("diff", "HEAD"): DIFF})
    _script_log(monkeypatch, msgs)

    assert foundry.capture_abort_patch(cfg, "r") is None
    assert _files_under(state) == before, _files_under(state)
    assert sorted(p.name for p in state.iterdir()) == ["notes"]
    assert msgs == [], msgs


def test_b8_directory_occupying_the_patch_path_returns_none(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-12")
    (state / "iter-12" / PATCH_NAME).mkdir()
    msgs = []
    _script_git(monkeypatch, [], {("diff", "HEAD"): DIFF})
    _script_log(monkeypatch, msgs)

    assert foundry.capture_abort_patch(cfg, "r") is None
    assert (state / "iter-12" / PATCH_NAME).is_dir()
    assert msgs == [], msgs


def test_b8_a_raising_git_seam_is_swallowed(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-12")
    monkeypatch.setattr(foundry, "git", _boom)
    msgs = []
    _script_log(monkeypatch, msgs)

    assert foundry.capture_abort_patch(cfg, "r") is None
    assert _files_under(state) == [], _files_under(state)
    assert msgs == [], msgs


# --------------------------------------------------------------------------
# behavior 9 -- overwrite, never append
# --------------------------------------------------------------------------
def test_b9_second_capture_overwrites_the_first(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-12")
    first, second = "FIRST-DIFF-BODY", "SECOND-DIFF-BODY-that-is-shorter"
    msgs = []
    _script_log(monkeypatch, msgs)

    _script_git(monkeypatch, [], {("diff", "HEAD"): first})
    p1 = foundry.capture_abort_patch(cfg, "first abort")
    _script_git(monkeypatch, [], {("diff", "HEAD"): second})
    p2 = foundry.capture_abort_patch(cfg, "second abort")

    assert p1 == p2 == state / "iter-12" / PATCH_NAME
    text = p2.read_text()
    assert text == second + "\n", repr(text)
    assert first not in text, "first diff survived: %r" % (text,)
    assert len(msgs) == 2, msgs


# --------------------------------------------------------------------------
# behavior 11 -- import safety (acceptance criterion)
# --------------------------------------------------------------------------
def test_b11_foundry_and_dispatcher_import_in_a_clean_interpreter():
    for mod in ("foundry", "dispatcher"):
        p = subprocess.run([sys.executable, "-c", "import %s" % mod],
                           cwd=str(_ROOT), capture_output=True, text=True)
        assert p.returncode == 0, "%s import failed: %s" % (mod, p.stderr[-800:])
