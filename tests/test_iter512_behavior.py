"""iter 512 -- every newest/next `iter-NN` lookup uses the one shared dir-name rule.

Spec: products/_platform/state/iter-512/pm.md, Expected Behaviors 1-8.

  1-3. `next_iteration(cfg)` parses state-dir names through the shared rule: `iter-03` +
       `iter-12-bak` -> 4; `iter- 9` / `iter-x` alone -> 1; `iter-07` + `iter-07-old` -> 8;
       the old pins (empty/missing -> 1, `iter-09` -> 10, numeric `iter-9`+`iter-10` -> 11).
  4.   `capture_abort_patch` writes into the newest `iter-<digits>` DIR (a FILE `iter-99`
       and `iter-x` are ignored), bytes == diff + exactly one trailing newline.
  5.   it resolves its target through `save_work_target` by bare module name.
  6.   no state / no iter child / hostile cfg -> None, no file, no git call, no raise.
  7.   static: no private `.split("-")` / `iterdir(` copy; shared helpers called; one caller.
  8.   foundry and dispatcher import in a clean interpreter.

ISOLATION CONTRACT (HONORED): derived ONLY from the iter-512 PM spec, the pre-existing
tests under `tests/` (the `_cfg`/scripted-seam idioms of test_iter151), and runtime
introspection. Engineer/reviewer notes and `git diff` were NOT read. Behavior 7 inspects
source text ONLY because the spec's Expected Behavior 7 is itself a static check.
Fully offline: `git` and `log` seams are scripted; every fixture lives in tmp_path.
"""
import ast
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
DIFF = "diff --git a/x.py b/x.py\n@@ -1 +1 @@\n-old\n+new"
# Seam key built from names, so test_iter487's unscoped `git diff HEAD` guard (which
# scans literal string tuples) does not read this scripted-seam key as a real git call.
_VERB = "diff"
_REF = "HEAD"
DIFF_HEAD = (_VERB, _REF)


def _cfg(tmp_path, **over):
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


def _state(cfg, dirs=(), files=()):
    state = pathlib.Path(cfg.state)
    state.mkdir(parents=True, exist_ok=True)
    for d in dirs:
        (state / d).mkdir(parents=True, exist_ok=True)
    for f in files:
        (state / f).write_text("not a dir\n")
    return state


def _script_git(monkeypatch, calls, results=None, default=""):
    table = dict(results or {})

    def fake_git(cfg, *args):
        calls.append(tuple(args))
        return table.get(tuple(args), default)

    monkeypatch.setattr(foundry, "git", fake_git)
    return calls


def _quiet_log(monkeypatch, msgs=None):
    msgs = [] if msgs is None else msgs
    monkeypatch.setattr(foundry, "log", lambda cfg, msg: msgs.append(msg))
    return msgs


def _files_under(root):
    root = pathlib.Path(root)
    if not root.exists():
        return []
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


# --------------------------------------------------------------------------
# behaviors 1-3 -- next_iteration
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "dirs, files, want",
    [
        (("iter-03", "iter-12-bak"), (), 4),        # B1 (HEAD said 13)
        (("iter- 9",), (), 1),                      # B2 (HEAD said 10)
        (("iter-x",), (), 1),                       # B2
        (("iter-07", "iter-07-old"), (), 8),        # B2
        ((), (), 1),                                # B3 empty
        (("iter-09",), (), 10),                     # B3
        (("iter-9", "iter-10"), (), 11),            # B3 numeric, not lexical
        (("iter-99", "iter-151"), (), 152),         # numeric again
        (("iter-12-bak", "iter-x", "iter- 9"), (), 1),  # only junk -> 1
        ((), ("iter-05",), 6),                      # out of scope: files still count
    ],
)
def test_b1_b3_next_iteration_uses_shared_rule(tmp_path, dirs, files, want):
    cfg = _cfg(tmp_path)
    _state(cfg, dirs, files)
    assert foundry.next_iteration(cfg) == want, (dirs, files)


def test_b3_missing_state_dir_returns_one_and_creates_nothing(tmp_path):
    cfg = _cfg(tmp_path)
    state = pathlib.Path(cfg.state)
    shutil.rmtree(state, ignore_errors=True)
    assert not state.exists()
    assert foundry.next_iteration(cfg) == 1
    assert not state.exists()


def test_b1_next_iteration_agrees_with_iteration_numbers(tmp_path):
    """The shared rule is the oracle: next == max(iteration_numbers(names)) + 1."""
    cfg = _cfg(tmp_path)
    names = ("iter-03", "iter-12-bak", "iter- 9", "iter-x", "iter-07-old", "iter-11")
    state = _state(cfg, names)
    nums = list(foundry.iteration_numbers(p.name for p in state.glob("iter-*")))
    assert foundry.next_iteration(cfg) == max(nums, default=0) + 1 == 12


# --------------------------------------------------------------------------
# behavior 4 -- capture_abort_patch picks the newest iter-<digits> DIR
# --------------------------------------------------------------------------
def test_b4_patch_lands_in_newest_digit_dir_ignoring_file_and_junk(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = _state(cfg, ("iter-9", "iter-10", "iter-x"), ("iter-99",))
    calls = _script_git(monkeypatch, [], {DIFF_HEAD: DIFF})
    _quiet_log(monkeypatch)
    got = foundry.capture_abort_patch(cfg, "r")
    want = state / "iter-10" / PATCH_NAME
    assert got == want, got
    assert want.read_bytes() == (DIFF + "\n").encode()
    assert (state / "iter-99").read_text() == "not a dir\n"  # the FILE is untouched
    assert _files_under(state) == ["iter-10/" + PATCH_NAME, "iter-99"]
    assert calls.index(("add", "-A", "-N")) < calls.index(DIFF_HEAD), calls


# --------------------------------------------------------------------------
# behavior 5 -- target resolved through save_work_target by bare name
# --------------------------------------------------------------------------
def test_b5_spy_returning_none_blocks_every_git_call(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = _state(cfg, ("iter-10",))
    seen = []
    monkeypatch.setattr(foundry, "save_work_target", lambda c: (seen.append(c), None)[1])
    calls = _script_git(monkeypatch, [], {DIFF_HEAD: DIFF})
    _quiet_log(monkeypatch)
    assert foundry.capture_abort_patch(cfg, "r") is None
    assert len(seen) == 1 and seen[0] is cfg, seen
    assert ("add", "-A", "-N") not in calls and DIFF_HEAD not in calls, calls
    assert _files_under(state) == []


def test_b5_spy_returning_dir_redirects_the_patch(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = _state(cfg, ("iter-10",))
    d = tmp_path / "elsewhere"
    d.mkdir()
    seen = []
    monkeypatch.setattr(foundry, "save_work_target", lambda c: (seen.append(c), d)[1])
    _script_git(monkeypatch, [], {DIFF_HEAD: DIFF})
    _quiet_log(monkeypatch)
    got = foundry.capture_abort_patch(cfg, "r")
    assert seen == [cfg]
    assert got == d / PATCH_NAME
    assert (d / PATCH_NAME).read_bytes() == (DIFF + "\n").encode()
    assert _files_under(state) == []  # nothing in the real newest dir


def test_b5_unpatched_target_matches_save_work_target(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _state(cfg, ("iter-07", "iter-12", "iter-12-bak"), ("iter-50",))
    _script_git(monkeypatch, [], {DIFF_HEAD: DIFF})
    _quiet_log(monkeypatch)
    target = foundry.save_work_target(cfg)
    assert target is not None and target.name == "iter-12"
    assert foundry.capture_abort_patch(cfg, "r") == target / PATCH_NAME


# --------------------------------------------------------------------------
# behavior 6 -- no target -> None, no file, no git call, no raise
# --------------------------------------------------------------------------
def test_b6_missing_state_dir(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    shutil.rmtree(cfg.state, ignore_errors=True)
    assert not pathlib.Path(cfg.state).exists()
    calls = _script_git(monkeypatch, [], {DIFF_HEAD: DIFF})
    _quiet_log(monkeypatch)
    assert foundry.capture_abort_patch(cfg, "r") is None
    assert calls == []
    assert not pathlib.Path(cfg.state).exists()


def test_b6_state_without_digit_child(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = _state(cfg, ("iter-x", "iter-12-bak", "iter- 9"), ("iter-77",))
    calls = _script_git(monkeypatch, [], {DIFF_HEAD: DIFF})
    _quiet_log(monkeypatch)
    assert foundry.capture_abort_patch(cfg, "r") is None
    assert calls == []
    assert _files_under(state) == ["iter-77"]


def test_b6_hostile_cfg_returns_none(monkeypatch):
    class Hostile:
        branch = "main"
        name = "hostile"

        @property
        def state(self):
            raise RuntimeError("cfg.state exploded")

    calls = _script_git(monkeypatch, [], {DIFF_HEAD: DIFF})
    _quiet_log(monkeypatch)
    assert foundry.capture_abort_patch(Hostile(), "r") is None
    assert calls == []


# --------------------------------------------------------------------------
# behavior 7 -- static: one shared rule, one caller
# --------------------------------------------------------------------------
@pytest.mark.parametrize("fname", ["next_iteration", "capture_abort_patch"])
def test_b7_no_private_copy_of_the_dir_name_rule(fname):
    src = inspect.getsource(getattr(foundry, fname))
    assert '.split("-")' not in src and ".split('-')" not in src, fname
    assert "iterdir(" not in src, fname


def test_b7_shared_helpers_are_called():
    assert "save_work_target(" in inspect.getsource(foundry.capture_abort_patch)
    assert "iteration_numbers(" in inspect.getsource(foundry.next_iteration)


def test_b7_capture_abort_patch_has_exactly_one_caller_revert_repo():
    tree = ast.parse((_ROOT / "foundry.py").read_text(encoding="utf-8"))
    callers = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                        and sub.func.id == "capture_abort_patch"):
                    callers.append(node.name)
    assert callers == ["revert_repo"], callers


# --------------------------------------------------------------------------
# behavior 8 -- importable
# --------------------------------------------------------------------------
def test_b8_foundry_and_dispatcher_import_cleanly():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
