"""Iteration 557 behaviors: `pm_recoverable_block` omits every preserved patch that a
read-only `git apply -R --check` (ledger files excluded) proves is already in HEAD.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-557 PM spec's Expected
Behaviors 1-11, the `tests/` conventions (tests/test_iter218_behavior.py for the
cfg / row / summary fixture shape), and the product's OBSERVABLE behaviour obtained by
calling its public functions. The engineer's notes, the reviewer's notes and `git diff`
were NOT read. foundry.py / dispatcher.py are opened only as TEXT INPUT for Behavior
11, which is itself a structural claim about the shipped source.

Offline except Behavior 3 / 11's real git repo, which is built in `tmp_path`. Nothing
here asserts on gitignored or ambient state, pins a sha or a line number, or times
anything.
"""
import dataclasses
import io
import json
import os
import pathlib
import subprocess
import sys
from contextlib import redirect_stdout

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import foundry  # noqa: E402

NEW_NAMES = ("recoverable_patch_paths", "recoverable_ledger_excludes",
             "recoverable_landed")
PLATFORM_EXCLUDES = ("DIRECTIONS.md", "PLATFORM_ROADMAP.md",
                     "PLATFORM_ROADMAP_ARCHIVE.md")
LANDED_LINE = "landed: 1 preserved patch(es) already in HEAD, omitted"

# RELATIVE patch paths -- never an absolute machine path
X_PATH = "products/demoprod/state/iter-555/ABORTED_IMPLEMENTATION.patch"
Y_PATH = "products/demoprod/state/iter-554/REVERTED_WORK_iter554.patch"
A_PATH = "products/demoprod/state/iter-553/REVERTED_WORK_iter553.patch"
IN_FLIGHT_PATH = "products/demoprod/state/iter-557/IMPLEMENTATION.patch"
BASE_SHA = "0123abc"


# --------------------------------------------------------------------------
# fixtures -- mirror tests/test_iter218_behavior.py
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, roadmap_name="ROADMAP.md", sub="p"):
    root = pathlib.Path(tmp_path) / sub
    root.mkdir(parents=True, exist_ok=True)
    (root / "repo").mkdir(exist_ok=True)
    (root / "VISION.md").write_text("product vision text\n", encoding="utf-8")
    (root / roadmap_name).write_text("- a roadmap item\n", encoding="utf-8")
    data = {
        "name": "demoprod",
        "repo": str(root / "repo"),
        "allowed_push_repo": "demoprod",
        "vision": str(root / "VISION.md"),
        "roadmap": str(root / roadmap_name),
        "work_root": str(root / "work"),
    }
    p = root / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _cfg(tmp_path, roadmap_name="PLATFORM_ROADMAP.md", sub="p"):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, roadmap_name, sub)))
    lp = pathlib.Path(cfg.learnings)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text("## Patterns\n\n- a durable rule\n", encoding="utf-8")
    return cfg


def _row(path, kind, verdict, reasons=()):
    return foundry.RecoverableRow(path=path, kind=kind, verdict=verdict,
                                  reasons=tuple(reasons))


def _x():
    return _row(X_PATH, foundry.RECOVERABLE_KIND_PRESERVED,
                foundry.RECOVERABLE_VERDICT_THREE_WAY, ("patch does not apply",))


def _y():
    return _row(Y_PATH, foundry.RECOVERABLE_KIND_PRESERVED,
                foundry.RECOVERABLE_VERDICT_BLOCKED, ("already exists",))


def _applies():
    return _row(A_PATH, foundry.RECOVERABLE_KIND_PRESERVED,
                foundry.RECOVERABLE_VERDICT_APPLIES, ())


def _in_flight():
    return _row(IN_FLIGHT_PATH, foundry.RECOVERABLE_KIND_IN_FLIGHT,
                foundry.RECOVERABLE_VERDICT_BLOCKED, ("already exists",))


def _summary(*rows):
    return foundry.recoverable_summary(tuple(rows), BASE_SHA)


def _script_gather(monkeypatch, summary):
    monkeypatch.setattr(foundry, "gather_recoverable",
                        lambda cfg, *a, **k: summary)


class _LandedSpy:
    """Scripted `recoverable_landed`: True for paths ending in one of `landed`."""

    def __init__(self, landed=(), exc=None):
        self.landed = tuple(landed)
        self.exc = exc
        self.calls = []

    def __call__(self, *a, **k):
        self.calls.append((a, k))
        if self.exc is not None:
            raise self.exc
        path = a[0] if a else k.get("path")
        return any(str(path).replace(os.sep, "/").endswith(p) for p in self.landed)

    def probed_paths(self):
        out = []
        for a, k in self.calls:
            path = str(a[0] if a else k.get("path")).replace(os.sep, "/")
            out.append(next((p for p in (X_PATH, Y_PATH, A_PATH, IN_FLIGHT_PATH)
                             if path.endswith(p)), path))
        return out


def _spy(monkeypatch, **kw):
    spy = _LandedSpy(**kw)
    monkeypatch.setattr(foundry, "recoverable_landed", spy)
    return spy


class _RunSpy:
    def __init__(self, result=None, exc=None):
        self.result = result if result is not None else foundry.CmdResult(True, "")
        self.exc = exc
        self.calls = []

    def __call__(self, args, cwd=None, timeout=600, **k):
        self.calls.append((list(args), cwd))
        if self.exc is not None:
            raise self.exc
        return self.result


# --------------------------------------------------------------------------
# Behavior 1 -- recoverable_patch_paths is pure and never raises
# --------------------------------------------------------------------------
TWO_SECTIONS = (
    "diff --git a/foundry.py b/foundry.py\n"
    "index 1111111..2222222 100644\n"
    "--- a/foundry.py\n+++ b/foundry.py\n@@ -1 +1 @@\n-x\n+y\n"
    "diff --git a/PLATFORM_ROADMAP.md b/PLATFORM_ROADMAP.md\n"
    "--- a/PLATFORM_ROADMAP.md\n+++ b/PLATFORM_ROADMAP.md\n@@ -1 +1 @@\n-a\n+b\n"
)


def test_b1_two_sections_give_sorted_paths():
    assert foundry.recoverable_patch_paths(TWO_SECTIONS) == (
        "PLATFORM_ROADMAP.md", "foundry.py")


def test_b1_rename_contributes_both_sides_deduplicated():
    text = ("diff --git a/old.py b/new.py\nsimilarity index 90%\n"
            "diff --git a/new.py b/new.py\n")
    assert foundry.recoverable_patch_paths(text) == ("new.py", "old.py")


@pytest.mark.parametrize("bad", ["", "just prose\n--- a/x\n+++ b/x\n", None, 7,
                                 "  diff --git a/x b/x\n"])
def test_b1_degenerate_inputs_give_empty_tuple(bad):
    assert foundry.recoverable_patch_paths(bad) == ()


def test_b1_return_is_a_tuple_and_input_is_untouched():
    out = foundry.recoverable_patch_paths(TWO_SECTIONS)
    assert type(out) is tuple
    assert foundry.recoverable_patch_paths(TWO_SECTIONS) == out


# --------------------------------------------------------------------------
# Behavior 2 -- recoverable_ledger_excludes derives from cfg.roadmap
# --------------------------------------------------------------------------
def test_b2_platform_roadmap_excludes(tmp_path):
    cfg = _cfg(tmp_path, "PLATFORM_ROADMAP.md")
    assert foundry.recoverable_ledger_excludes(cfg) == PLATFORM_EXCLUDES


def test_b2_product_md_excludes(tmp_path):
    cfg = _cfg(tmp_path, "PRODUCT.md")
    assert foundry.recoverable_ledger_excludes(cfg) == (
        "DIRECTIONS.md", "PRODUCT.md", "PRODUCT_ARCHIVE.md")


def test_b2_empty_roadmap_excludes_only_directions(tmp_path):
    cfg = dataclasses.replace(_cfg(tmp_path), roadmap="")
    assert foundry.recoverable_ledger_excludes(cfg) == ("DIRECTIONS.md",)


# --------------------------------------------------------------------------
# Behavior 3 (+ 11c) -- real tmp_path git repo
# --------------------------------------------------------------------------
def _git(repo, *args):
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", HOME=str(repo.parent),
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    r = subprocess.run(["git", *args], cwd=str(repo), env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stdout, r.stderr)
    return r.stdout


def _landed_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "src.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    (repo / "PLATFORM_ROADMAP.md").write_text("- iter 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "A")
    a = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "src.py").write_text("x = 1\ny = 3\nz = 4\n", encoding="utf-8")
    (repo / "PLATFORM_ROADMAP.md").write_text("- iter 2\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "B")
    b = _git(repo, "rev-parse", "HEAD").strip()
    patch = tmp_path / "saved" / "ABORTED_IMPLEMENTATION.patch"
    patch.parent.mkdir()
    patch.write_text(_git(repo, "diff", a, b), encoding="utf-8")
    (repo / "PLATFORM_ROADMAP.md").write_text("- iter 3 rewritten\n",
                                              encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "C")
    return repo, a, patch


def test_b3_real_repo_landed_at_tip_and_not_after_checkout_a(tmp_path):
    repo, a, patch = _landed_repo(tmp_path)
    assert "diff --git a/src.py b/src.py" in patch.read_text(encoding="utf-8")
    got = foundry.recoverable_landed(patch, repo, PLATFORM_EXCLUDES)
    assert got is True
    _git(repo, "checkout", "-q", a)
    got = foundry.recoverable_landed(patch, repo, PLATFORM_EXCLUDES)
    assert got is False


def test_b3_ledger_exclusion_is_load_bearing(tmp_path):
    """Without excludes the rewritten ledger hunk blocks the reverse apply."""
    repo, _a, patch = _landed_repo(tmp_path)
    assert foundry.recoverable_landed(patch, repo, ()) is False


def test_b3_accepts_str_paths(tmp_path):
    repo, _a, patch = _landed_repo(tmp_path)
    assert foundry.recoverable_landed(str(patch), str(repo),
                                      list(PLATFORM_EXCLUDES)) is True


def test_b11_real_run_leaves_repo_status_and_head_unchanged(tmp_path):
    repo, a, patch = _landed_repo(tmp_path)
    (repo / "dirty.txt").write_text("untracked\n", encoding="utf-8")
    before = (_git(repo, "status", "--porcelain"), _git(repo, "rev-parse", "HEAD"),
              (repo / "src.py").read_text(encoding="utf-8"))
    foundry.recoverable_landed(patch, repo, PLATFORM_EXCLUDES)
    foundry.recoverable_landed(patch, repo, ())
    after = (_git(repo, "status", "--porcelain"), _git(repo, "rev-parse", "HEAD"),
             (repo / "src.py").read_text(encoding="utf-8"))
    assert after == before


# --------------------------------------------------------------------------
# Behavior 4 -- guards: False, no raise, ZERO run_cmd calls
# --------------------------------------------------------------------------
def test_b4_missing_patch_file(tmp_path, monkeypatch):
    spy = _RunSpy()
    monkeypatch.setattr(foundry, "run_cmd", spy)
    assert foundry.recoverable_landed(tmp_path / "nope.patch", tmp_path,
                                      PLATFORM_EXCLUDES) is False
    assert spy.calls == []


def test_b4_unreadable_patch_file_a_directory(tmp_path, monkeypatch):
    spy = _RunSpy()
    monkeypatch.setattr(foundry, "run_cmd", spy)
    d = tmp_path / "dir.patch"
    d.mkdir()
    assert foundry.recoverable_landed(d, tmp_path, PLATFORM_EXCLUDES) is False
    assert spy.calls == []


def test_b4_patch_with_no_diff_git_path(tmp_path, monkeypatch):
    spy = _RunSpy()
    monkeypatch.setattr(foundry, "run_cmd", spy)
    p = tmp_path / "x.patch"
    p.write_text("not a patch at all\n", encoding="utf-8")
    assert foundry.recoverable_landed(p, tmp_path, PLATFORM_EXCLUDES) is False
    assert spy.calls == []


def test_b4_all_paths_excluded_is_not_landed(tmp_path, monkeypatch):
    spy = _RunSpy()  # would say ok=True if it were (wrongly) called
    monkeypatch.setattr(foundry, "run_cmd", spy)
    p = tmp_path / "ledger.patch"
    p.write_text("diff --git a/PLATFORM_ROADMAP.md b/PLATFORM_ROADMAP.md\n"
                 "--- a/PLATFORM_ROADMAP.md\n+++ b/PLATFORM_ROADMAP.md\n"
                 "@@ -1 +1 @@\n-a\n+b\n", encoding="utf-8")
    assert foundry.recoverable_landed(p, tmp_path, PLATFORM_EXCLUDES) is False
    assert spy.calls == []


def _code_patch(tmp_path):
    p = tmp_path / "code.patch"
    p.write_text(TWO_SECTIONS, encoding="utf-8")
    return p


def test_b4_raising_run_cmd_reads_false(tmp_path, monkeypatch):
    spy = _RunSpy(exc=RuntimeError("boom"))
    monkeypatch.setattr(foundry, "run_cmd", spy)
    assert foundry.recoverable_landed(_code_patch(tmp_path), tmp_path,
                                      PLATFORM_EXCLUDES) is False
    assert len(spy.calls) == 1


def test_b4_not_ok_run_cmd_reads_false(tmp_path, monkeypatch):
    spy = _RunSpy(result=foundry.CmdResult(False, "error: patch failed"))
    monkeypatch.setattr(foundry, "run_cmd", spy)
    got = foundry.recoverable_landed(_code_patch(tmp_path), tmp_path,
                                     PLATFORM_EXCLUDES)
    assert got is False


# --------------------------------------------------------------------------
# Behavior 5 -- exactly ONE probe, exact argv, cwd=repo, result is .ok
# --------------------------------------------------------------------------
def test_b5_single_probe_exact_argv_and_cwd(tmp_path, monkeypatch):
    spy = _RunSpy(result=foundry.CmdResult(True, ""))
    monkeypatch.setattr(foundry, "run_cmd", spy)
    p = _code_patch(tmp_path)
    repo = tmp_path / "r"
    excludes = ("Z.md", "A.md", "DIRECTIONS.md")  # order must be preserved
    got = foundry.recoverable_landed(p, repo, excludes)
    assert got is True
    assert len(spy.calls) == 1
    argv, cwd = spy.calls[0]
    assert argv == ["git", "apply", "-R", "--check", "--exclude=Z.md",
                    "--exclude=A.md", "--exclude=DIRECTIONS.md", str(p)]
    assert str(cwd) == str(repo)


def test_b5_empty_excludes_has_no_exclude_flags(tmp_path, monkeypatch):
    spy = _RunSpy(result=foundry.CmdResult(False, ""))
    monkeypatch.setattr(foundry, "run_cmd", spy)
    p = _code_patch(tmp_path)
    assert foundry.recoverable_landed(p, tmp_path, ()) is False
    assert spy.calls[0][0] == ["git", "apply", "-R", "--check", str(p)]


# --------------------------------------------------------------------------
# Behavior 6 -- the only preserved row is landed -> block is ""
# --------------------------------------------------------------------------
def test_b6_only_preserved_row_landed_gives_empty_block(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _script_gather(monkeypatch, _summary(_x(), _in_flight()))
    spy = _spy(monkeypatch, landed=(X_PATH,))
    assert foundry.pm_recoverable_block(cfg, "pm") == ""
    assert spy.probed_paths() == [X_PATH], "seam must be read by bare name"


# --------------------------------------------------------------------------
# Behavior 7 -- mixed window: landed X omitted, blocked Y stays
# --------------------------------------------------------------------------
def test_b7_mixed_window_exact_block(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    x, z, y = _x(), _in_flight(), _y()
    summary = _summary(x, z, y)
    _script_gather(monkeypatch, summary)
    spy = _spy(monkeypatch, landed=(X_PATH,))
    block = foundry.pm_recoverable_block(cfg, "pm")
    kept = tuple(r for r in summary.rows if r is not x)
    expected = (foundry.PM_RECOVERABLE_LABEL + "\n" + LANDED_LINE + "\n"
                + foundry.recoverable_summary(kept, summary.base).render() + "\n")
    assert block == expected
    assert X_PATH not in block
    assert Y_PATH in block
    assert "preserved 1" in block
    assert sorted(spy.probed_paths()) == sorted([X_PATH, Y_PATH])


# --------------------------------------------------------------------------
# Behavior 8 -- nothing landed -> byte-identical to the pre-change form
# --------------------------------------------------------------------------
def test_b8_nothing_landed_is_byte_identical(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    summary = _summary(_x(), _in_flight(), _y())
    _script_gather(monkeypatch, summary)
    _spy(monkeypatch, landed=())
    block = foundry.pm_recoverable_block(cfg, "pm")
    assert block == foundry.PM_RECOVERABLE_LABEL + "\n" + summary.render() + "\n"
    assert "landed:" not in block


# --------------------------------------------------------------------------
# Behavior 9 -- the seam is never called for applies / in-flight / non-pm
# --------------------------------------------------------------------------
def test_b9_applies_only_window_never_probes(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    summary = _summary(_applies())
    _script_gather(monkeypatch, summary)
    spy = _spy(monkeypatch, landed=(A_PATH,))
    block = foundry.pm_recoverable_block(cfg, "pm")
    assert spy.calls == []
    assert block == foundry.PM_RECOVERABLE_LABEL + "\n" + summary.render() + "\n"


def test_b9_in_flight_row_never_probed(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _script_gather(monkeypatch, _summary(_in_flight(), _y()))
    spy = _spy(monkeypatch, landed=())
    foundry.pm_recoverable_block(cfg, "pm")
    assert IN_FLIGHT_PATH not in spy.probed_paths()
    assert spy.probed_paths() == [Y_PATH]


@pytest.mark.parametrize("stage", ["engineer", "reviewer", "tester", "final",
                                   "pm_scout"])
def test_b9_non_pm_stage_never_probes(tmp_path, monkeypatch, stage):
    cfg = _cfg(tmp_path)
    _script_gather(monkeypatch, _summary(_x(), _y()))
    spy = _spy(monkeypatch, landed=())
    assert foundry.pm_recoverable_block(cfg, stage) == ""
    assert spy.calls == []


def test_b9_raising_seam_degrades_to_empty(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _script_gather(monkeypatch, _summary(_x(), _y()))
    _spy(monkeypatch, exc=RuntimeError("probe exploded"))
    assert foundry.pm_recoverable_block(cfg, "pm") == ""


# --------------------------------------------------------------------------
# Behavior 10 -- the `recoverable` verb is unchanged / never probes landed
# --------------------------------------------------------------------------
def test_b10_verdict_constants_unchanged():
    assert (foundry.RECOVERABLE_VERDICT_APPLIES,
            foundry.RECOVERABLE_VERDICT_THREE_WAY,
            foundry.RECOVERABLE_VERDICT_BLOCKED) == ("applies", "three-way",
                                                      "blocked")


@pytest.mark.parametrize("as_json", [False, True])
def test_b10_recoverable_cli_never_consults_landed_seam(tmp_path, monkeypatch,
                                                        as_json):
    cfg = _cfg(tmp_path)
    summary = _summary(_x(), _in_flight(), _y())
    _script_gather(monkeypatch, summary)
    spy = _spy(monkeypatch, landed=(X_PATH, Y_PATH))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = foundry.recoverable_cli(cfg, as_json=as_json)
    out = buf.getvalue()
    assert spy.calls == []
    assert rc == summary.exit_code
    assert X_PATH in out and Y_PATH in out
    if as_json:
        assert json.loads(out) == summary.to_dict()
    else:
        assert summary.render() in out


def test_b10_summary_has_no_landed_vocabulary():
    summary = _summary(_x(), _in_flight(), _y())
    assert "landed" not in summary.render()
    assert "landed" not in json.dumps(summary.to_dict())


# --------------------------------------------------------------------------
# Behavior 11 -- read-only argv on one line; dispatcher untouched
# --------------------------------------------------------------------------
def test_b11_every_apply_line_carries_check():
    src = (REPO_ROOT / "foundry.py").read_text(encoding="utf-8")
    hits = [ln for ln in src.splitlines() if '"apply"' in ln]
    assert hits, "vacuous: foundry.py has no git-apply argv at all"
    assert [ln for ln in hits if "--check" not in ln] == []


def test_b11_dispatcher_mentions_none_of_the_new_names():
    src = (REPO_ROOT / "dispatcher.py").read_text(encoding="utf-8")
    assert [n for n in NEW_NAMES if n in src] == []


def test_b11_new_functions_are_documented_module_level_callables():
    for n in NEW_NAMES:
        fn = getattr(foundry, n)
        assert callable(fn) and (fn.__doc__ or "").strip(), n
