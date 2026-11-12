"""iter 532 -- `find_constant_assert_tests` stops walking a test function at its
first real assertion signal, via `_assert_signals(f, *, stop_on_real=False)`.

Spec (products/_platform/state/iter-532/pm.md). Black-box: drives the public
finder / helper and compares against the PINNED pre-iteration foundry.py
(`git show a1671da...:foundry.py`) loaded under a distinct module name. The
early exit is proven with a node COUNT (a counting `ast.walk` wrapper), never a
clock.
"""
import ast
import importlib.util
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import foundry  # noqa: E402

BASE_SHA = "a1671da3d63ee709434fb5b1246059f34236d902"
_CACHE = {}


def _baseline(tmp_path_factory):
    """Load the pinned pre-iteration foundry.py as `foundry_base_iter532`."""
    if "mod" in _CACHE:
        return _CACHE["mod"]
    if shutil.which("git") is None:
        pytest.skip("git unavailable: cannot load the baseline foundry.py")
    r = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_SHA}:foundry.py"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"baseline sha {BASE_SHA} absent: {r.stderr.strip()}")
    d = tmp_path_factory.mktemp("base_foundry")
    p = d / "foundry_base_iter532.py"
    p.write_text(r.stdout)
    name = "foundry_base_iter532"
    spec = importlib.util.spec_from_file_location(name, str(p))
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(p)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _CACHE["mod"] = mod
    return mod


@pytest.fixture
def base(tmp_path_factory):
    return _baseline(tmp_path_factory)


FIXTURES = {
    "a": ("def test_a():\n    assert True\n", ("test_a",)),
    "b": ("def test_b(x):\n    assert x\n    assert True\n", ()),
    "c": ("def test_c(x):\n    assert True\n    assert x == 1\n", ()),
    "d": ("def test_d(x):\n    assert True\n"
          "    def inner():\n        assert x == 2\n    inner()\n", ()),
    "e": ('def test_e():\n    assert True, "msg"\n', ("test_e",)),
    "f": ("def test_f():\n    assert True\n    raise ValueError('x')\n", ()),
    "g": ("class TestG:\n    def test_g(self, a, b):\n"
          "        assert True\n        self.assertEqual(a, b)\n", ()),
    "h": ("import pytest\n\ndef test_h():\n    assert True\n"
          "    with pytest.raises(ValueError):\n        f()\n", ()),
    "i": ("def test_i():\n    x = 1\n    print(x)\n", ()),
}
MIXED = (
    "import pytest\n\n"
    "def test_m1():\n    assert True\n\n"
    "def test_m2(x):\n    assert x\n    assert True\n\n"
    "def test_m3():\n    assert 1, 'always'\n\n"
    "def test_m4(x):\n    assert True\n    assert x == 1\n\n"
    "def test_m5():\n    assert True\n    raise ValueError\n\n"
    "def test_m6():\n    assert 'yes'\n"
)
MIXED_EXPECTED = ("test_m1", "test_m3", "test_m6")
ALL_SOURCES = [s for s, _ in FIXTURES.values()] + [MIXED]


def _funcs(tree):
    return [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _func(src, name):
    for n in _funcs(ast.parse(src)):
        if n.name == name:
            return n
    raise AssertionError(f"{name} not in fixture")


# ---------------------------------------------------------------- behavior 1
@pytest.mark.parametrize("key", sorted(FIXTURES))
def test_b1_fixture_golden_text_and_tree(base, key):
    src, expected = FIXTURES[key]
    new_text = foundry.find_constant_assert_tests(src)
    assert new_text == expected
    assert new_text == base.find_constant_assert_tests(src)
    tree = ast.parse(src)
    assert foundry.find_constant_assert_tests(tree) == expected
    assert foundry.find_constant_assert_tests(tree) == \
        base.find_constant_assert_tests(ast.parse(src))


def test_b1_mixed_file_flagged_in_line_order(base):
    got = foundry.find_constant_assert_tests(MIXED)
    assert got == MIXED_EXPECTED
    assert got == base.find_constant_assert_tests(MIXED)
    tree = ast.parse(MIXED)
    assert foundry.find_constant_assert_tests(tree) == MIXED_EXPECTED
    assert isinstance(got, tuple)


# ---------------------------------------------------------------- behavior 2
@pytest.mark.parametrize("src", ALL_SOURCES)
def test_b2_default_contract_matches_baseline(base, src):
    tree = ast.parse(src)
    funcs = _funcs(tree)
    assert funcs
    for f in funcs:
        assert foundry._assert_signals(f) == base._assert_signals(f), f.name


@pytest.mark.parametrize("key,name", [("b", "test_b"), ("c", "test_c")])
def test_b2_default_full_walk_sees_both(key, name):
    f = _func(FIXTURES[key][0], name)
    assert foundry._assert_signals(f) == (True, True)
    assert foundry._assert_signals(f, stop_on_real=False) == (True, True)


def test_b2_flag_is_keyword_only():
    f = _func(FIXTURES["b"][0], "test_b")
    with pytest.raises(TypeError):
        foundry._assert_signals(f, True)


# ---------------------------------------------------------------- behavior 3
def _deep_src():
    nested = "x"
    for _ in range(200):
        nested = f"g({nested})"
    lst = "[" + ", ".join(str(i) for i in range(300)) + "]"
    return (f"def test_deep(x):\n    assert x\n    y = {nested}\n"
            f"    z = {lst}\n")


def _count_walk(monkeypatch, call):
    orig = ast.walk
    box = {"n": 0}

    def counting(node):
        for n in orig(node):
            box["n"] += 1
            yield n

    monkeypatch.setattr(foundry.ast, "walk", counting)
    try:
        res = call()
    finally:
        monkeypatch.setattr(foundry.ast, "walk", orig)
    return res, box["n"]


def test_b3_early_exit_visits_under_half_the_nodes(monkeypatch):
    f = _func(_deep_src(), "test_deep")
    flagged, n_flag = _count_walk(
        monkeypatch, lambda: foundry._assert_signals(f, stop_on_real=True))
    full, n_full = _count_walk(monkeypatch, lambda: foundry._assert_signals(f))
    assert flagged == (False, True)
    assert full == (False, True)
    assert n_full > 600  # non-vacuity: the default really walks the subtree
    assert n_flag * 2 < n_full, (n_flag, n_full)


def test_b3_finder_also_exits_early(monkeypatch):
    src = _deep_src()
    tree = ast.parse(src)
    got, n_finder = _count_walk(
        monkeypatch, lambda: foundry.find_constant_assert_tests(tree))
    f = _func(src, "test_deep")
    _, n_full = _count_walk(monkeypatch, lambda: foundry._assert_signals(f))
    assert got == ()
    assert n_full > 600
    # the finder routes through the flag, so it too visits < half the nodes
    # a full walk of the function body costs (baseline finder: == n_full)
    assert n_finder * 2 < n_full, (n_finder, n_full)


# ---------------------------------------------------------------- behavior 4
def test_b4_constant_before_real_is_seen_with_flag():
    f = _func(FIXTURES["c"][0], "test_c")
    assert foundry._assert_signals(f, stop_on_real=True) == (True, True)
    assert foundry.find_constant_assert_tests(FIXTURES["c"][0]) == ()


def test_b4_real_before_constant_second_element_contracted():
    f = _func(FIXTURES["b"][0], "test_b")
    assert foundry._assert_signals(f, stop_on_real=True) in {(False, True), (True, True)}
    assert foundry.find_constant_assert_tests(FIXTURES["b"][0]) == ()


@pytest.mark.parametrize("key", sorted(FIXTURES))
def test_b4_flag_second_element_equals_default(key):
    for f in _funcs(ast.parse(FIXTURES[key][0])):
        c = foundry._assert_signals(f, stop_on_real=True)
        a = foundry._assert_signals(f)
        assert c[1] == a[1], f.name
        assert not (c[0] and not a[0]), f.name


# ---------------------------------------------------------------- behavior 5
K_SRC = "def test_k():\n    check(1)\n    assert True\n"


def _with_check(const):
    if isinstance(const, (set, frozenset)):
        return type(const)(set(const) | {"check"})
    return tuple(const) + ("check",)


def test_b5_weak_calls_read_at_call_time(monkeypatch, base):
    assert "check" not in foundry.WEAK_TEST_ASSERTION_CALLS
    assert foundry.find_constant_assert_tests(K_SRC) == ("test_k",)
    assert base.find_constant_assert_tests(K_SRC) == ("test_k",)
    monkeypatch.setattr(foundry, "WEAK_TEST_ASSERTION_CALLS",
                        _with_check(foundry.WEAK_TEST_ASSERTION_CALLS))
    monkeypatch.setattr(base, "WEAK_TEST_ASSERTION_CALLS",
                        _with_check(base.WEAK_TEST_ASSERTION_CALLS))
    assert foundry.find_constant_assert_tests(K_SRC) == ()
    assert base.find_constant_assert_tests(K_SRC) == ()


# ---------------------------------------------------------------- behavior 6
def test_b6_syntax_error_propagates(base):
    with pytest.raises(SyntaxError):
        foundry.find_constant_assert_tests("def test_(:\n")
    with pytest.raises(SyntaxError):
        base.find_constant_assert_tests("def test_(:\n")


# ---------------------------------------------------------------- behavior 7
def _tracked_test_files():
    files = sorted((ROOT / "tests").glob("test_*.py"))
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files", "tests"],
                       capture_output=True, text=True) \
        if shutil.which("git") else None
    if r is not None and r.returncode == 0 and r.stdout.strip():
        tracked = {ROOT / line for line in r.stdout.split()}
        files = [p for p in files if p in tracked]
    return files[:150]


def test_b7_real_tree_golden(base):
    files = _tracked_test_files()
    assert len(files) >= 100
    mismatches = []
    n_flag_vs_default = 0
    for p in files:
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        if foundry.find_constant_assert_tests(tree) != \
                base.find_constant_assert_tests(tree):
            mismatches.append(p.name)
        for f in _funcs(tree):
            c = foundry._assert_signals(f, stop_on_real=True)
            a = foundry._assert_signals(f)
            if c[1] != a[1] or (c[0] and not a[0]):
                n_flag_vs_default += 1
    assert mismatches == []
    assert n_flag_vs_default == 0


# ---------------------------------------------------------------- behavior 8
def test_b8_import_foundry_and_dispatcher():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
