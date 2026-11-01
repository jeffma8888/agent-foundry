"""Iteration 502 -- black-box tester checks: the suite's one nested pytest run
disables xdist (`-n 0`), plus a two-sided AST brake over tests/*.py.

Written from the spec (pm.md) only. Fresh-clone safe: every git read is a
`git show` of a fixed commit or a `git clone --shared` into tmp_path, and every
commit-dependent check skips when its object is absent.

Brake boundary (what `nested_pytest_argv_gaps` does NOT match): a TUPLE argv
`(sys.executable, "-m", "pytest", ...)`, a list built by concatenation or with
`*args` unpacking in its first three slots, and a `uv run ... pytest` argv.
Only a literal `ast.List` whose first three elements are exactly
`sys.executable`, `"-m"`, `"pytest"` is in scope.
"""
from __future__ import annotations

import ast
import pathlib
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"
ITER469 = "d9c40f7"
PRE_CHANGE = "5400894"
BANNER = "bringing up nodes"


# ---------------------------------------------------------------------------
# EB4 -- the pure helper
# ---------------------------------------------------------------------------

def _is_str(node, value):
    return isinstance(node, ast.Constant) and isinstance(node.value, str) \
        and node.value == value


def _is_sys_executable(node):
    return (isinstance(node, ast.Attribute) and node.attr == "executable"
            and isinstance(node.value, ast.Name) and node.value.id == "sys")


def nested_pytest_argv_gaps(source: str, filename: str) -> list[str]:
    """Return `<filename>:<lineno>` for every literal list argv
    `[sys.executable, "-m", "pytest", ...]` lacking adjacent `"-n", "0"`."""
    gaps: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.List):
            continue
        elts = node.elts
        if len(elts) < 3:
            continue
        if not (_is_sys_executable(elts[0]) and _is_str(elts[1], "-m")
                and _is_str(elts[2], "pytest")):
            continue
        ok = any(_is_str(a, "-n") and _is_str(b, "0")
                 for a, b in zip(elts, elts[1:]))
        if not ok:
            gaps.append(f"{filename}:{node.lineno}")
    return gaps


def _in_scope_count(source: str) -> int:
    n = 0
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.List) and len(node.elts) >= 3 \
                and _is_sys_executable(node.elts[0]) \
                and _is_str(node.elts[1], "-m") \
                and _is_str(node.elts[2], "pytest"):
            n += 1
    return n


def _have(obj: str) -> bool:
    probe = subprocess.run(["git", "cat-file", "-e", obj],
                           capture_output=True, text=True, cwd=str(REPO_ROOT),
                           timeout=60)
    return probe.returncode == 0


# ---------------------------------------------------------------------------
# EB1 -- the nested argv in test_iter487_blackbox carries "-n", "0"
# ---------------------------------------------------------------------------

def _eb1_fn():
    path = TESTS_DIR / "test_iter487_blackbox.py"
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and \
                fn.name == "test_eb1_eb2_pass_in_a_dirty_clone":
            return src, fn
    raise AssertionError("test_eb1_eb2_pass_in_a_dirty_clone not found")


def _nested_call(fn):
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and node.args \
                and isinstance(node.args[0], ast.List):
            elts = node.args[0].elts
            if len(elts) >= 3 and _is_sys_executable(elts[0]) \
                    and _is_str(elts[2], "pytest"):
                return node
    raise AssertionError("no nested pytest call in the EB1 test")


def test_eb1_nested_argv_has_adjacent_n_0():
    _, fn = _eb1_fn()
    call = _nested_call(fn)
    vals = [e.value if isinstance(e, ast.Constant) else None
            for e in call.args[0].elts]
    assert any(a == "-n" and b == "0" for a, b in zip(vals, vals[1:])), vals


def test_eb1_rest_of_the_test_unchanged():
    src, fn = _eb1_fn()
    call = _nested_call(fn)
    vals = [e.value for e in call.args[0].elts if isinstance(e, ast.Constant)]
    assert "tests/test_iter469_behavior.py" in vals, vals
    i = vals.index("-k")
    assert vals[i + 1] == "b5_git or b6_net", vals
    kw = {k.arg: k.value for k in call.keywords}
    assert isinstance(kw.get("timeout"), ast.Constant) and kw["timeout"].value == 300
    body = ast.get_source_segment(src, fn)
    assert "assert run.returncode == 0" in body
    assert '"2 passed" in out' in body
    assert '"skipped" not in out' in body


# ---------------------------------------------------------------------------
# EB2 -- the test itself passes (or skips with the stated reason)
# ---------------------------------------------------------------------------

def test_eb2_the_nested_test_passes_or_skips_with_reason():
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider",
         "-n", "0",
         "tests/test_iter487_blackbox.py::test_eb1_eb2_pass_in_a_dirty_clone"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=300,
    )
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-3000:]
    if _have(ITER469 + "^{commit}"):
        assert "1 passed" in out, out[-3000:]
        assert "skipped" not in out, out[-3000:]
    else:
        assert "iter-469 commit not available" in out, out[-3000:]


# ---------------------------------------------------------------------------
# EB3 -- two-sided: the token is what removes the xdist worker banner
# ---------------------------------------------------------------------------

def test_eb3_minus_n_0_drops_the_worker_banner(tmp_path):
    if not _have(ITER469 + "^{commit}"):
        pytest.skip("iter-469 commit not available")
    clone = tmp_path / "clone"
    r = subprocess.run(
        ["git", "clone", "-q", "--shared", str(REPO_ROOT), str(clone)],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stderr
    for name in ("test_iter469_behavior.py", "_shared.py", "conftest.py"):
        src = TESTS_DIR / name
        if src.is_file():
            shutil.copy(src, clone / "tests" / name)
    with_token = [sys.executable, "-m", "pytest", "-q", "-rs", "-p",
                  "no:cacheprovider", "-n", "0",
                  "tests/test_iter469_behavior.py", "-k", "b5_git or b6_net"]
    i = with_token.index("-n")
    without_token = with_token[:i] + with_token[i + 2:]
    assert "-n" not in without_token and len(without_token) == len(with_token) - 2

    on = subprocess.run(with_token, capture_output=True, text=True,
                        cwd=str(clone), timeout=300)
    on_out = on.stdout + on.stderr
    assert on.returncode == 0, on_out[-3000:]
    assert "2 passed" in on_out, on_out[-3000:]
    assert BANNER not in on_out, on_out[-3000:]

    off = subprocess.run(without_token, capture_output=True, text=True,
                         cwd=str(clone), timeout=300)
    off_out = off.stdout + off.stderr
    assert off.returncode == 0, off_out[-3000:]
    assert BANNER in off_out, off_out[-3000:]


# ---------------------------------------------------------------------------
# EB5 -- two-sided synthetic sources
# ---------------------------------------------------------------------------

def test_eb5_missing_token_is_one_gap_with_lineno():
    src = 'import sys\nX = [sys.executable, "-m", "pytest", "-q"]\n'
    assert nested_pytest_argv_gaps(src, "bad.py") == ["bad.py:2"]


def test_eb5_adjacent_token_is_clean():
    src = 'import sys\nX = [sys.executable, "-m", "pytest", "-q", "-n", "0"]\n'
    assert nested_pytest_argv_gaps(src, "good.py") == []


def test_eb5_non_adjacent_token_is_a_gap():
    src = 'import sys\nX = [sys.executable, "-m", "pytest", "-n", "-q", "0"]\n'
    assert nested_pytest_argv_gaps(src, "x.py") == ["x.py:2"]


def test_eb5_other_module_is_out_of_scope():
    src = 'import sys\nX = [sys.executable, "-m", "foundry"]\n'
    assert nested_pytest_argv_gaps(src, "x.py") == []


def test_eb5_string_literal_text_is_out_of_scope():
    src = "S = '[sys.executable, \"-m\", \"pytest\"]'\n"
    assert nested_pytest_argv_gaps(src, "x.py") == []


@pytest.mark.parametrize("src", [
    'import sys\nX = (sys.executable, "-m", "pytest", "-q")\n',
    'import sys\nA = ["-q"]\nX = [*A, sys.executable, "-m", "pytest"]\n',
    'X = ["uv", "run", "pytest", "-q"]\n',
])
def test_eb4_documented_boundary_is_not_matched(src):
    assert nested_pytest_argv_gaps(src, "x.py") == []


def test_eb4_multiple_gaps_each_reported():
    src = ('import sys\n'
           'A = [sys.executable, "-m", "pytest"]\n'
           'B = [sys.executable, "-m", "pytest", "-n", "0"]\n'
           'C = [sys.executable, "-m", "pytest", "-n", "auto"]\n')
    assert nested_pytest_argv_gaps(src, "m.py") == ["m.py:2", "m.py:4"]


# ---------------------------------------------------------------------------
# EB6 -- the brake over the shipped tests/ tree
# ---------------------------------------------------------------------------

def test_eb6_tree_has_no_gaps_and_is_non_vacuous():
    gaps: list[str] = []
    in_scope = 0
    for path in sorted(TESTS_DIR.glob("*.py")):
        src = path.read_text(encoding="utf-8", errors="replace")
        try:
            gaps += nested_pytest_argv_gaps(src, path.name)
        except SyntaxError:
            continue
        in_scope += _in_scope_count(src)
    assert gaps == [], gaps
    assert in_scope >= 1
    eb1 = (TESTS_DIR / "test_iter487_blackbox.py").read_text(encoding="utf-8")
    assert _in_scope_count(eb1) >= 1


def test_eb6_pre_change_source_has_exactly_one_gap():
    obj = PRE_CHANGE + ":tests/test_iter487_blackbox.py"
    if not _have(obj):
        pytest.skip("pre-change object not available")
    r = subprocess.run(["git", "show", obj], capture_output=True, text=True,
                       cwd=str(REPO_ROOT), timeout=60)
    assert r.returncode == 0, r.stderr
    got = nested_pytest_argv_gaps(r.stdout, "test_iter487_blackbox.py")
    assert len(got) == 1, got


# ---------------------------------------------------------------------------
# EB7 -- both modules import; the iteration's archive bullet is recorded
# ---------------------------------------------------------------------------

def test_eb7_foundry_and_dispatcher_import():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       capture_output=True, text=True, cwd=str(REPO_ROOT),
                       timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stderr.strip() == "", r.stderr


def test_eb7_archive_bullet_recorded():
    text = (REPO_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text(encoding="utf-8")
    assert any(line.startswith("- **iter 502 --") for line in text.splitlines())
