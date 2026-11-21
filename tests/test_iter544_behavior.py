"""Black-box behaviour tests for iter 544 -- test_iter541's `_defs` (the b9
pinned-def map) is rebuilt on `_shared.split_source_lines` + `source_segment`
and memoized per source TEXT, so the 5 b9 params stop re-splitting foundry.py
per def.  Speed-only: same assertions, same node ids.

ISOLATION CONTRACT (honored): written solely from the iter-544 PM spec's
Expected Behaviors (1-10), the README, and the files under `tests/` (which the
contract allows). foundry.py / dispatcher.py source, the engineer's and
reviewer's notes and `git diff` were not read for design.

Fully offline, tracked files + tmp_path only.  HEAD-keyed arms skip when no git
is available (e.g. a `git archive` copy).  No wall-clock bound is asserted
(ship hazard H2): speed is proven structurally -- zero stdlib segment calls in
test_iter541, a cache-hit observable, and stdlib-oracle equality.
"""
import ast
import difflib
import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
import test_iter541_behavior as t541  # noqa: E402

T541 = REPO / "tests" / "test_iter541_behavior.py"
T204 = REPO / "tests" / "test_iter204_behavior.py"
DEF_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _oracle(src):
    """Stdlib reference: dict comprehension, last name wins."""
    return {n.name: ast.get_source_segment(src, n)
            for n in ast.parse(src).body if isinstance(n, DEF_TYPES)}


def _foundry_text():
    return (REPO / "foundry.py").read_text(encoding="utf-8")


def _git(*args):
    try:
        proc = subprocess.run(["git", "-C", str(REPO), *args],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _head_or_skip(relpath):
    text = _git("show", f"HEAD:{relpath}")
    if text is None:
        pytest.skip("no git HEAD available")
    return text


# --------------------------------------------------------------------------
# Behavior 1 -- stdlib-oracle equality over the current foundry.py
# --------------------------------------------------------------------------
def test_b1_defs_matches_stdlib_oracle_on_foundry():
    src = _foundry_text()
    got = t541._defs(src)
    nodes = {}
    for n in ast.parse(src).body:          # last name wins, as a dict comprehension
        if isinstance(n, DEF_TYPES):
            nodes[n.name] = n
    assert len(nodes) > 100
    assert set(got.keys()) == set(nodes.keys())
    # stdlib oracle on the 5 pinned names + every 16th def (the full stdlib pass
    # costs ~10 s of CPU -- the very cost this iteration removes)
    names = sorted(nodes)
    sample = set(t541.PINNED_DEFS) | set(names[::16]) | {names[-1]}
    assert len(sample) >= 40
    bad = [k for k in sorted(sample) if got[k] != ast.get_source_segment(src, nodes[k])]
    assert bad == []
    for name in t541.PINNED_DEFS:
        assert got[name] and got[name].startswith(("def ", "async def ", "class ", "@"))


def test_b1_duplicate_names_last_wins():
    src = "def f():\n    return 1\n\n\ndef f():\n    return 2\n"
    got = t541._defs(src)
    assert list(got.keys()) == ["f"]
    assert got["f"] == "def f():\n    return 2" == _oracle(src)["f"]


# --------------------------------------------------------------------------
# Behavior 2 -- synthetic edge-case source
# --------------------------------------------------------------------------
SYNTH = (
    "import os\r\n"
    "\r\n"
    "def plain(x):\r\n"
    "    return x + 1\r\n"
    "\n"
    "def naïve(s='héllo — wörld ✓'):\n"
    "    π = 3.14\n"
    "    return s, π\n"
    "\n"
    "async def fetch(url):\r\n"
    "    await something(url)\r\n"
    "\n"
    "\x0c\n"
    "@decorator\n"
    "@other(arg='日本語')\n"
    "def decorated():\n"
    "    pass\n"
    "\n"
    "class Klass(object):\n"
    "    '''doc ü'''\n"
    "    def method(self):\n"
    "        return 'ß'\n"
    "X = 1\n"
)


def test_b2_synthetic_edge_cases_byte_identical_to_stdlib():
    got = t541._defs(SYNTH)
    want = _oracle(SYNTH)
    assert set(want) == {"plain", "naïve", "fetch", "decorated", "Klass"}
    assert set(got) == set(want)
    for k in want:
        assert got[k] == want[k], k
        assert got[k].encode("utf-8") == want[k].encode("utf-8")
    assert "π = 3.14" in got["naïve"]
    assert got["Klass"].endswith("return 'ß'")


# --------------------------------------------------------------------------
# Behavior 3 -- a one-char mutation is caught (per-text cache key)
# --------------------------------------------------------------------------
def test_b3_mutation_inside_gather_resumable_is_caught():
    src = _foundry_text()
    original = t541._defs(src)
    seg = original["gather_resumable"]
    assert src.count(seg) == 1
    nl = seg.index("\n")
    mutated_seg = seg[:nl] + " " + seg[nl:]
    mutated = src.replace(seg, mutated_seg, 1)
    assert mutated != src
    after = t541._defs(mutated)
    assert after["gather_resumable"] != original["gather_resumable"]
    assert after["gather_resumable"] == mutated_seg
    assert after["run_iteration"] == original["run_iteration"]
    changed = sorted(k for k in original if after.get(k) != original[k])
    assert changed == ["gather_resumable"]
    # the original text still maps to the original segment afterwards
    assert t541._defs(src)["gather_resumable"] == seg


# --------------------------------------------------------------------------
# Behavior 4 -- memoized per text
# --------------------------------------------------------------------------
def test_b4_defs_is_memoized():
    assert hasattr(t541._defs, "cache_info")
    src = "def memo_probe_544():\n    return 'x'\n"
    first = t541._defs(src)
    hits = t541._defs.cache_info().hits
    second = t541._defs(src)
    assert second == first
    assert second is first
    assert t541._defs.cache_info().hits >= hits + 1
    maxsize = t541._defs.cache_info().maxsize
    assert maxsize is not None and 1 <= maxsize <= 16


# --------------------------------------------------------------------------
# Behavior 5 -- static: no stdlib segment call left, imports from _shared
# --------------------------------------------------------------------------
def _t541_tree():
    return ast.parse(T541.read_text(encoding="utf-8"))


def test_b5_no_get_source_segment_call_in_test_iter541():
    calls = [n for n in ast.walk(_t541_tree())
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "get_source_segment"]
    assert calls == []


def test_b5_imports_helpers_from_shared():
    names = set()
    for n in ast.walk(_t541_tree()):
        if isinstance(n, ast.ImportFrom) and n.module == "_shared":
            names |= {a.name for a in n.names}
    assert {"split_source_lines", "source_segment"} <= names


def test_b5_defs_is_lru_cached_on_src_argument():
    fn = next(n for n in _t541_tree().body
              if isinstance(n, ast.FunctionDef) and n.name == "_defs")
    assert [a.arg for a in fn.args.args] == ["src"]
    assert fn.decorator_list, "_defs must be memoized"
    dec_src = [ast.unparse(d) for d in fn.decorator_list]
    assert any("lru_cache" in d or "cache" in d for d in dec_src)


# --------------------------------------------------------------------------
# Behavior 6 -- unchanged surface vs HEAD
# --------------------------------------------------------------------------
def test_b6_pinned_defs_unchanged():
    assert t541.PINNED_DEFS == ("run_iteration", "build_prompt", "capture_abort_patch",
                                "gather_resumable", "resumable_open")


def _test_surface(src):
    """Top-level test names -> (unparsed decorators, unparsed body) except `_defs`."""
    out = {}
    for n in ast.parse(src).body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"):
            out[n.name] = ast.unparse(n)
    return out


def test_b6_test_functions_byte_identical_to_head():
    # iter 550: scope-gated (the test_iter379 pattern) so a later iteration's
    # forced edit to test_iter541 no longer turns this HEAD diff red.
    if not _pre_ship_scope_live():
        pytest.skip("iter 544 already shipped; its HEAD diff check is inert")
    head = _head_or_skip("tests/test_iter541_behavior.py")
    now = T541.read_text(encoding="utf-8")
    h, w = _test_surface(head), _test_surface(now)
    assert sorted(h) == sorted(w)
    assert [k for k in h if h[k] != w[k]] == []


def test_b6_only_defs_and_imports_moved_vs_head():
    # iter 550: scope-gated (the test_iter379 pattern) so a later iteration's
    # forced edit to test_iter541 no longer turns this HEAD diff red.
    if not _pre_ship_scope_live():
        pytest.skip("iter 544 already shipped; its HEAD diff check is inert")
    head = _head_or_skip("tests/test_iter541_behavior.py")
    now = T541.read_text(encoding="utf-8")

    def _rest(src):
        keep = []
        for n in ast.parse(src).body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                continue
            if isinstance(n, ast.FunctionDef) and n.name == "_defs":
                continue
            if (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                    and ast.unparse(n.value).startswith("sys.path.insert")):
                continue
            keep.append(ast.unparse(n))
        return keep

    assert _rest(head) == _rest(now)


# --------------------------------------------------------------------------
# Behavior 7 -- scoped b9 run green (no wall-clock bound: ship hazard H2)
# --------------------------------------------------------------------------
def test_b7_scoped_b9_run_is_green():
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(T541), "-q", "-k", "b9_pinned_def",
         "-p", "no:cacheprovider", "-n", "0"],
        capture_output=True, text=True, timeout=300, cwd=str(REPO), env=env)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-3000:]
    assert ("5 passed" in out) or ("5 skipped" in out), out[-3000:]


def test_b7_one_defs_call_on_foundry_never_uses_stdlib_segment(monkeypatch):
    calls = []
    real = ast.get_source_segment

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(ast, "get_source_segment", counting)
    src = _foundry_text() + "\n# iter544 fresh key\n"   # bypass any cached entry
    got = t541._defs(src)
    assert "run_iteration" in got
    assert calls == []


# --------------------------------------------------------------------------
# Behavior 9 -- test_iter204 b15 allow-list row
# --------------------------------------------------------------------------
def _b15_expected_set():
    tree = ast.parse(T204.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "test_b15_only_the_three_expected_test_files_differ_from_head")
    for n in ast.walk(fn):
        if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "expected"
                                              for t in n.targets)
                and isinstance(n.value, ast.Set)):
            return [e.value for e in n.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    raise AssertionError("b15 `expected` set literal not found")


def test_b9_b15_expected_set_names_test_iter541():
    rows = _b15_expected_set()
    assert "tests/test_iter541_behavior.py" in rows
    assert rows[-1] == "tests/test_iter541_behavior.py"
    assert rows.count("tests/test_iter541_behavior.py") == 1
    text = T204.read_text(encoding="utf-8")
    assert "# iter 544:" in text


def test_b9_b15_only_one_row_added_vs_head():
    head = _head_or_skip("tests/test_iter204_behavior.py")
    now = T204.read_text(encoding="utf-8")
    added = [l for l in difflib.unified_diff(head.splitlines(), now.splitlines(), lineterm="", n=0)
             if l.startswith("+") and not l.startswith("+++")]
    removed = [l for l in difflib.unified_diff(head.splitlines(), now.splitlines(), lineterm="", n=0)
               if l.startswith("-") and not l.startswith("---")]
    if head == now:
        pytest.skip("post-ship: HEAD already carries the row (content arm above holds)")
    if not _pre_ship_scope_live():
        pytest.skip("iter 544 already shipped; its one-row diff check is inert")
    code_added = [l for l in added if not l[1:].strip().startswith("#")]
    assert code_added == ['+                "tests/test_iter535_behavior.py",',
                          '+                "tests/test_iter541_behavior.py"}']
    assert removed == ['-                "tests/test_iter535_behavior.py"}']


# --------------------------------------------------------------------------
# Behavior 10 -- product importable and byte-unchanged
# --------------------------------------------------------------------------
def test_b10_foundry_and_dispatcher_import():
    proc = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                          capture_output=True, text=True, timeout=120, cwd=str(REPO))
    assert proc.returncode == 0, proc.stderr[-2000:]


def _pre_ship_scope_live():
    """True only while iter 544's own ledger row is not yet in HEAD's roadmap.

    WHY: "product files unchanged vs HEAD" is a scope check for THIS
    iteration's test-only change. Once 544 ships, HEAD carries its row and a
    LATER iteration's legitimate code edit must not turn this red (the
    test_iter379 pattern)."""
    text = _git("show", "HEAD:PLATFORM_ROADMAP.md")
    return text is not None and "- iter 544 " not in text


def test_b10_product_files_unchanged_vs_head():
    if not _pre_ship_scope_live():
        pytest.skip("iter 544 already shipped; scope check is inert")
    for rel in ("foundry.py", "dispatcher.py"):
        head = _head_or_skip(rel)
        assert (REPO / rel).read_text(encoding="utf-8") == head, rel
