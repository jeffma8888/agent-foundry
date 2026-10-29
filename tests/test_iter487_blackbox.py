"""Iteration 487 -- black-box tester checks for the iter-469 EB5/EB6 re-scope
and the suite-wide unscoped-HEAD-diff guard (tests/test_iter487_behavior.py).

Written from the spec only. Every git read here is either `git show` of a
fixed commit or a `git clone --shared` into tmp_path, so the module is
fresh-clone safe and never reads the live worktree's uncommitted state.
Needles are built by concatenation so the iter-487 guard scans this file clean.
"""
from __future__ import annotations

import ast
import importlib
import pathlib
import shutil
import subprocess
import sys
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"
ITER469 = "d9c40f7"
DIFF = "di" + "ff"
HEAD = "HE" + "AD"
SEP = "-" + "-"

if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))


def _guard():
    return importlib.import_module("test_iter487_behavior")


def _eb469():
    return importlib.import_module("test_iter469_behavior")


def _have_commit() -> bool:
    probe = subprocess.run(
        ["git", "cat-file", "-e", ITER469 + "^{commit}"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    return probe.returncode == 0


# ---------------------------------------------------------------------------
# EB1/EB2 -- EB5/EB6 green in a DIRTY worktree (real subprocess pytest run)
# ---------------------------------------------------------------------------

def test_eb1_eb2_pass_in_a_dirty_clone(tmp_path):
    if not _have_commit():
        pytest.skip("iter-469 commit not available")
    clone = tmp_path / "clone"
    r = subprocess.run(
        ["git", "clone", "-q", "--shared", str(REPO_ROOT), str(clone)],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stderr
    # Ship the CURRENT oracle module + its helpers into the clone.
    for name in ("test_iter469_behavior.py", "_shared.py", "conftest.py"):
        src = TESTS_DIR / name
        if src.is_file():
            shutil.copy(src, clone / "tests" / name)
    # Arbitrary uncommitted NON-test edits, plus a new untracked file.
    with open(clone / "foundry.py", "a", encoding="utf-8") as fh:
        fh.write("\n# dirty tester edit\n")
    with open(clone / "README.md", "a", encoding="utf-8") as fh:
        fh.write("\ndirty\n" * 500)
    (clone / "scratch_untracked.py").write_text("x = 1\n" * 50, encoding="utf-8")
    st = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                        text=True, cwd=str(clone))
    assert "foundry.py" in st.stdout and "README.md" in st.stdout
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider",
         "tests/test_iter469_behavior.py", "-k", "b5_git or b6_net"],
        capture_output=True, text=True, cwd=str(clone), timeout=300,
    )
    out = run.stdout + run.stderr
    assert run.returncode == 0, out[-3000:]
    assert "2 passed" in out, out[-3000:]
    assert "skipped" not in out, out[-3000:]


# ---------------------------------------------------------------------------
# EB1 -- independent recomputation of the commit's path set
# ---------------------------------------------------------------------------

def test_eb1_commit_touches_only_tests_and_ledger_files():
    if not _have_commit():
        pytest.skip("iter-469 commit not available")
    r = subprocess.run(["git", "show", "--name-only", "--format=", ITER469],
                       capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert r.returncode == 0, r.stderr
    paths = [p for p in r.stdout.splitlines() if p.strip()]
    assert paths, "commit lists no paths"
    outside = {p for p in paths if not p.startswith("tests/")}
    assert outside <= {"DIRECTIONS.md", "PLATFORM_ROADMAP.md",
                       "PLATFORM_ROADMAP_ARCHIVE.md"}, outside


# ---------------------------------------------------------------------------
# EB2 -- the oracle number is 399 and the failure message names its parts
# ---------------------------------------------------------------------------

def test_eb2_independent_net_is_399():
    if not _have_commit():
        pytest.skip("iter-469 commit not available")
    r = subprocess.run(["git", "show", "--numstat", "--format=", ITER469],
                       capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert r.returncode == 0, r.stderr
    ins = dels = 0
    for row in r.stdout.splitlines():
        parts = row.split("\t")
        if len(parts) != 3 or not parts[0].isdigit():
            continue
        if parts[2].startswith("tests/") and parts[2] != "tests/test_iter469_behavior.py":
            ins += int(parts[0])
            dels += int(parts[1])
    assert (ins, dels, dels - ins) == (117, 516, 399)


class _FakeRun:
    """Scripted stand-in for subprocess.run that records every argv."""

    def __init__(self, stdout: str, cat_rc: int = 0):
        self.calls: list[list[str]] = []
        self.stdout = stdout
        self.cat_rc = cat_rc

    def __call__(self, argv, *a, **kw):
        self.calls.append(list(argv))
        rc = self.cat_rc if "cat-file" in argv else 0
        return types.SimpleNamespace(returncode=rc, stdout=self.stdout, stderr="")


def test_eb2_failure_message_names_insertions_deletions_net(monkeypatch):
    mod = _eb469()
    fake = _FakeRun("100\t50\ttests/test_x.py\n5\t900\tfoundry.py\n"
                    "1\t999\ttests/test_iter469_behavior.py\n")
    monkeypatch.setattr(mod.subprocess, "run", fake)
    with pytest.raises(AssertionError) as exc:
        mod.TestEB6NetLineReduction().test_b6_net_reduction_at_least_350()
    msg = str(exc.value)
    # Only tests/ minus the oracle counts: ins=100, dels=50, net=-50.
    assert "100" in msg and "50" in msg and "-50" in msg, msg
    assert "insertions" in msg and "deletions" in msg, msg


def test_eb1_failure_names_a_production_path(monkeypatch):
    mod = _eb469()
    fake = _FakeRun("tests/test_a.py\nPLATFORM_ROADMAP.md\nfoundry.py\n")
    monkeypatch.setattr(mod.subprocess, "run", fake)
    with pytest.raises(AssertionError) as exc:
        mod.TestEB5NoProductionCodeModified().test_b5_git_diff_only_tests()
    assert "foundry.py" in str(exc.value)
    assert "PLATFORM_ROADMAP.md" not in str(exc.value)


# ---------------------------------------------------------------------------
# EB3 -- skip (not fail) without the commit; never runs a diff
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls,meth", [
    ("TestEB5NoProductionCodeModified", "test_b5_git_diff_only_tests"),
    ("TestEB6NetLineReduction", "test_b6_net_reduction_at_least_350"),
])
def test_eb3_missing_commit_skips(monkeypatch, cls, meth):
    mod = _eb469()
    fake = _FakeRun("", cat_rc=128)
    monkeypatch.setattr(mod.subprocess, "run", fake)
    with pytest.raises(pytest.skip.Exception):
        getattr(getattr(mod, cls)(), meth)()
    assert fake.calls, "no git probe was made"
    assert all(DIFF not in c for c in fake.calls), fake.calls


@pytest.mark.parametrize("cls,meth", [
    ("TestEB5NoProductionCodeModified", "test_b5_git_diff_only_tests"),
    ("TestEB6NetLineReduction", "test_b6_net_reduction_at_least_350"),
])
def test_eb3_present_commit_never_runs_diff(monkeypatch, cls, meth):
    mod = _eb469()
    fake = _FakeRun("400\t900\ttests/test_x.py\n" if "b6" in meth else "tests/a.py\n")
    monkeypatch.setattr(mod.subprocess, "run", fake)
    getattr(getattr(mod, cls)(), meth)()
    assert any("show" in c for c in fake.calls), fake.calls
    assert all(DIFF not in c for c in fake.calls), fake.calls


# ---------------------------------------------------------------------------
# EB4/EB5 -- the pure scanner, two-sided
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    (f"import subprocess\nsubprocess.run(['git', '{DIFF}', '--stat', '{HEAD}'])\n", [2]),
    (f"a = 1\n_git('{DIFF}', '--name-only', '{HEAD}')\n", [2]),
    (f"X = ('{DIFF}', '{HEAD}')\n", [1]),
    (f"X = ['git', '{DIFF}', '{HEAD}', '{SEP}', 'x.py']\n", []),
    ("X = ['git', 'show', '--numstat', 'd9c40f7']\n", []),
    (f"X = ['git', '{DIFF}', '{HEAD}~1']\n", []),
    (f"X = ['git', '{DIFF}', 'origin/{HEAD}']\n", []),
    (f"X = ['git', 'log', '{HEAD}']\n", []),
    ("def f(:", []),
    ("", []),
    ("x = '\x00'", []),
    # keyword args are not positional args
    (f"f(a='{DIFF}', b='{HEAD}')\n", []),
])
def test_eb4_eb5_scanner_cases(src, expected):
    got = _guard().unscoped_head_diff_lines(src)
    assert isinstance(got, list)
    assert got == expected


def test_eb4_lines_sorted_and_multi():
    src = (f"A = ['{DIFF}', '{HEAD}']\n"
           "B = 2\n"
           f"g('{DIFF}', '{HEAD}')\n"
           f"C = ['{DIFF}', '{HEAD}', '{SEP}']\n"
           f"D = ('{HEAD}', '{DIFF}')\n")
    assert _guard().unscoped_head_diff_lines(src) == [1, 3, 5]


def test_eb4_never_raises_on_garbage():
    fn = _guard().unscoped_head_diff_lines
    for bad in ("((((", "\x00\x00", "class:", "def f(:\n    pass", "\t\tx = 1"):
        assert fn(bad) == []


def test_eb4_guard_module_scans_clean_itself():
    path = TESTS_DIR / "test_iter487_behavior.py"
    assert _guard().unscoped_head_diff_lines(path.read_text(encoding="utf-8")) == []
    # and the needles really are absent as literal constants
    tree = ast.parse(path.read_text(encoding="utf-8"))
    consts = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)}
    assert HEAD not in consts


def test_this_blackbox_module_scans_clean():
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert _guard().unscoped_head_diff_lines(src) == []


# ---------------------------------------------------------------------------
# EB6/EB7 -- suite-wide guard, allowlist, anti-rot, messages
# ---------------------------------------------------------------------------

EXPECTED_ALLOW = {"test_iter151_behavior.py", "test_iter368_behavior.py",
                  "test_iter379_behavior.py", "test_iter420_behavior.py"}


def _independent_scan() -> dict[str, list[int]]:
    fn = _guard().unscoped_head_diff_lines
    out = {}
    for p in sorted(TESTS_DIR.glob("*.py")):
        hits = fn(p.read_text(encoding="utf-8"))
        if hits:
            out[p.name] = hits
    return out


def test_eb6_allowlist_exactly_four_reasoned():
    allow = _guard().ALLOWLIST
    assert isinstance(allow, dict)
    assert set(allow) == EXPECTED_ALLOW
    assert all(isinstance(v, str) and v.strip() for v in allow.values())


def test_eb6_live_tree_hits_are_exactly_the_allowlist():
    found = _independent_scan()
    assert set(found) == EXPECTED_ALLOW, found
    assert "test_iter469_behavior.py" not in found


def test_eb6_offender_message_names_path_and_line(tmp_path, monkeypatch):
    g = _guard()
    for name in EXPECTED_ALLOW:
        (tmp_path / name).write_text(f"X = ['{DIFF}', '{HEAD}']\n", encoding="utf-8")
    (tmp_path / "test_bad.py").write_text(
        f"a = 1\nb = 2\nX = ['git', '{DIFF}', '{HEAD}']\n", encoding="utf-8")
    monkeypatch.setattr(g, "TESTS_DIR", tmp_path)
    with pytest.raises(AssertionError) as exc:
        g.test_no_unscoped_head_diff_outside_allowlist()
    assert "test_bad.py:3" in str(exc.value)
    # allowlisted modules are not reported
    assert "test_iter151_behavior.py" not in str(exc.value)


def test_eb6_clean_tmp_tree_passes(tmp_path, monkeypatch):
    g = _guard()
    (tmp_path / "test_ok.py").write_text(
        f"X = ['git', '{DIFF}', '{HEAD}', '{SEP}', 'a.py']\n", encoding="utf-8")
    monkeypatch.setattr(g, "TESTS_DIR", tmp_path)
    assert g.test_no_unscoped_head_diff_outside_allowlist() is None


def test_eb7_stale_entry_fails_and_names_module(tmp_path, monkeypatch):
    g = _guard()
    names = sorted(EXPECTED_ALLOW)
    # first exists with a hit, second exists with 0 hits, the rest are missing
    (tmp_path / names[0]).write_text(f"X = ['{DIFF}', '{HEAD}']\n", encoding="utf-8")
    (tmp_path / names[1]).write_text("X = 1\n", encoding="utf-8")
    monkeypatch.setattr(g, "TESTS_DIR", tmp_path)
    with pytest.raises(AssertionError) as exc:
        g.test_allowlist_has_no_stale_entries()
    msg = str(exc.value)
    assert names[1] in msg and names[2] in msg and names[3] in msg
    assert names[0] not in msg


def test_eb7_all_allowlisted_modules_tracked_and_hit():
    found = _independent_scan()
    for name in EXPECTED_ALLOW:
        assert (TESTS_DIR / name).is_file(), name
        assert len(found.get(name, [])) >= 1, name
    tracked = subprocess.run(["git", "ls-files", "tests/"], capture_output=True,
                             text=True, cwd=str(REPO_ROOT)).stdout.split()
    assert {f"tests/{n}" for n in EXPECTED_ALLOW} <= set(tracked)


# ---------------------------------------------------------------------------
# Acceptance -- production modules stay importable in a fresh interpreter
# ---------------------------------------------------------------------------

def test_foundry_and_dispatcher_import_fresh():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120)
    assert r.returncode == 0, r.stderr
