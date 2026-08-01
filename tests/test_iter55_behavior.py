"""Black-box behaviour tests for iter 55 -- the PURE, offline, deterministic AST
detector for UNCONDITIONALLY-SKIPPED `test*` functions
(`find_always_skipped_tests(source) -> tuple[str, ...]`).

This is the 3rd member of the item-6 weak-test detector family, after
`find_assertionless_tests` (iter 22 -- no assert node at all) and
`find_constant_assert_tests` (iter 47 -- a bare-literal `assert True`). A `test*`
decorated with an UNCONDITIONAL skip (`@pytest.mark.skip`, `@unittest.skip`, or a
constant-condition `skipif(True)` / `skipUnless(False)`) never runs, validates
nothing, yet reports the suite green. It ships DORMANT this iteration (no CLI
wiring; zero call site on any run path).

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-8) and the product's own OBSERVABLE behaviour only. The implementation
source (foundry.py / dispatcher.py internals), the engineer's and reviewer's notes,
and `git diff` were NOT read. Every check drives the PUBLIC interface: the pure fn
via `foundry.find_always_skipped_tests(...)` on Python SOURCE STRINGS, the sibling
detectors via `foundry.find_assertionless_tests(...)` /
`foundry.find_constant_assert_tests(...)`, and the patchable constant via
`foundry.WEAK_TEST_SKIP_NAMES`. The dormancy / off-control-path checks (Behavior 8)
use only public RUNTIME introspection -- module attributes and compiled function
name tables (`__code__.co_names`) -- NOT the source text, so "the run-path
functions do not reference the new symbol" is verified as "no compiled reference in
the run-path code objects", which honors isolation. Fully offline + deterministic:
no filesystem/subprocess/network/git/clock/agent-run (except the documented
`import foundry, dispatcher` regression probe). Every test source below is SYNTHETIC
-- no real internal tool/service/skill name, no absolute home-directory path -- so
the in-loop leak-guard passes on the ship commit.
"""
import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers (mirror tests/test_iter47_behavior.py compiled-introspection style)
# --------------------------------------------------------------------------
def _fn_names(fn):
    """Set of every global/attr name reachable from fn's compiled code object
    (recursing into nested code objects) -- public runtime introspection, NOT
    source text, so the dormancy check honors the isolation contract."""
    stack, seen, names = [fn.__code__], set(), set()
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names |= set(code.co_names)
        for c in code.co_consts:
            if isinstance(c, types.CodeType):
                stack.append(c)
    return names


def _module_names(module):
    """Union of names across every function/method reachable from a module's
    public namespace (recursively into nested code objects)."""
    names = set()
    for v in vars(module).values():
        if isinstance(v, types.FunctionType):
            names |= _fn_names(v)
        elif isinstance(v, type):
            for m in vars(v).values():
                if isinstance(m, types.FunctionType):
                    names |= _fn_names(m)
    return names


CTRL = ("build_prompt", "run_stage", "run_iteration", "run_continuous")
SIBLINGS = ("find_assertionless_tests", "find_constant_assert_tests",
            "weak_tests_cli", "constant_asserts_cli")
NEW_SYMBOL = "find_always_skipped_tests"


# ==========================================================================
# Behavior 1 -- unconditional `skip` flags: bare, dotted, called, with/no args
# ==========================================================================
def test_b1_unconditional_skip_all_forms_flagged():
    src = (
        "@skip\ndef test_bare(): pass\n\n"
        "@pytest.mark.skip\ndef test_dotted(): pass\n\n"
        "@unittest.skip\ndef test_us(): pass\n\n"
        '@pytest.mark.skip(reason="wip")\ndef test_called(): pass\n\n'
        '@unittest.skip("wip")\ndef test_us_arg(): pass\n'
    )
    r = foundry.find_always_skipped_tests(src)
    assert isinstance(r, tuple), f"result must be a tuple, got {type(r)}"
    assert all(isinstance(x, str) for x in r), f"elements must be str, got {r!r}"
    for name in ("test_bare", "test_dotted", "test_us", "test_called", "test_us_arg"):
        assert name in r, (
            f"an unconditional `skip` decorator (bare/dotted/called, with or without "
            f"args) must flag {name!r}; got {r!r}"
        )


# ==========================================================================
# Behavior 2 -- skipif/skipIf flags ONLY on a constant-truthy first arg
# ==========================================================================
def test_b2_skipif_constant_truthy_flagged():
    for src in (
        '@pytest.mark.skipif(True, reason="x")\ndef test_a(): pass\n',
        '@unittest.skipIf(1, "x")\ndef test_a(): pass\n',
    ):
        r = foundry.find_always_skipped_tests(src)
        assert r == ("test_a",), (
            f"a constant-truthy skipif/skipIf first arg must flag; src={src!r} got={r!r}"
        )


def test_b2_skipif_constant_falsy_not_flagged():
    for src in (
        '@pytest.mark.skipif(False, reason="x")\ndef test_a(): pass\n',
        '@unittest.skipIf(0, "x")\ndef test_a(): pass\n',
    ):
        r = foundry.find_always_skipped_tests(src)
        assert r == (), (
            f"a constant-falsy skipif/skipIf never skips -> not flagged; "
            f"src={src!r} got={r!r}"
        )


def test_b2_skipif_non_constant_not_flagged():
    # a runtime condition is UNKNOWN -> conservatively not flagged (no false positive)
    r = foundry.find_always_skipped_tests(
        '@pytest.mark.skipif(sys.platform == "win32", reason="x")\ndef test_a(): pass\n'
    )
    assert r == (), (
        f"a non-constant skipif condition is unknown -> conservatively NOT flagged; got {r!r}"
    )


# ==========================================================================
# Behavior 3 -- skipUnless flags ONLY on a constant-falsy first arg
# ==========================================================================
def test_b3_skipunless_constant_falsy_flagged():
    r = foundry.find_always_skipped_tests('@unittest.skipUnless(False, "x")\ndef test_a(): pass\n')
    assert r == ("test_a",), f"skipUnless(False) always skips -> flagged; got {r!r}"


def test_b3_skipunless_constant_truthy_not_flagged():
    r = foundry.find_always_skipped_tests('@unittest.skipUnless(True, "x")\ndef test_a(): pass\n')
    assert r == (), f"skipUnless(True) never skips -> not flagged; got {r!r}"


def test_b3_skipunless_non_constant_not_flagged():
    r = foundry.find_always_skipped_tests('@unittest.skipUnless(HAVE_LIB, "x")\ndef test_a(): pass\n')
    assert r == (), f"a non-constant skipUnless condition is unknown -> not flagged; got {r!r}"


# ==========================================================================
# Behavior 4 -- no skip decorator -> not flagged
# ==========================================================================
def test_b4_undecorated_not_flagged():
    assert foundry.find_always_skipped_tests("def test_a(): pass\n") == (), (
        "an undecorated test must not be flagged"
    )


def test_b4_non_skip_decorator_not_flagged():
    # parametrize's first positional arg is a constant string, yet it is NOT a
    # skip decorator -> must never be flagged.
    r = foundry.find_always_skipped_tests(
        '@pytest.mark.parametrize("n", [1, 2])\ndef test_a(n): pass\n'
    )
    assert r == (), f"a non-skip decorator (parametrize) must not flag; got {r!r}"


# ==========================================================================
# Behavior 5 -- every test* def considered; non-test names ignored; source order
# ==========================================================================
def test_b5_test_defs_only_in_source_order():
    src = (
        "@skip\ndef test_top(): pass\n\n"
        "@skip\nasync def test_async(): pass\n\n"
        "class TestX:\n    @skip\n    def test_method(self): pass\n\n"
        "@skip\ndef _helper(): pass\n\n"
        "@skip\ndef setup_module(): pass\n"
    )
    r = foundry.find_always_skipped_tests(src)
    assert r == ("test_top", "test_async", "test_method"), (
        f"only test*-named defs (top-level, async, and class methods) are considered, "
        f"in ascending source order; non-test names (_helper, setup_module) ignored; got {r!r}"
    )
    assert "_helper" not in r and "setup_module" not in r


# ==========================================================================
# Behavior 6 -- each flagged def appears once; ascending source (not alpha) order
# ==========================================================================
def test_b6_multiple_decorators_flag_once():
    r = foundry.find_always_skipped_tests(
        '@pytest.mark.parametrize("n", [1, 2])\n@pytest.mark.skip\ndef test_multi(n): pass\n'
    )
    assert r == ("test_multi",), (
        f"a test with multiple decorators incl. one skip appears exactly ONCE; got {r!r}"
    )


def test_b6_source_order_not_alphabetical():
    src = "@skip\ndef test_zebra(): pass\n\n@skip\ndef test_apple(): pass\n"
    r = foundry.find_always_skipped_tests(src)
    assert r == ("test_zebra", "test_apple"), (
        f"flagged tests return in ascending source/definition order, not alphabetical; got {r!r}"
    )


# ==========================================================================
# Behavior 7 -- invalid source raises SyntaxError verbatim; empty -> ()
# ==========================================================================
def test_b7_syntax_error_propagates():
    with pytest.raises(SyntaxError):
        foundry.find_always_skipped_tests("def (:")


def test_b7_empty_and_test_free_return_empty_tuple():
    assert foundry.find_always_skipped_tests("") == ()
    assert foundry.find_always_skipped_tests("x = 1\n") == ()


# ==========================================================================
# Behavior 8 -- WEAK_TEST_SKIP_NAMES patchable frozenset read at CALL time;
# dormant / off the control path; importable; siblings unchanged
# ==========================================================================
def test_b8_skip_names_default_is_frozenset_with_skip():
    assert isinstance(foundry.WEAK_TEST_SKIP_NAMES, frozenset), (
        f"WEAK_TEST_SKIP_NAMES must be a frozenset, got {type(foundry.WEAK_TEST_SKIP_NAMES)}"
    )
    assert "skip" in foundry.WEAK_TEST_SKIP_NAMES, (
        f"default membership must include 'skip'; got {foundry.WEAK_TEST_SKIP_NAMES!r}"
    )
    assert all(isinstance(x, str) for x in foundry.WEAK_TEST_SKIP_NAMES)


def test_b8_skip_names_read_at_call_time(monkeypatch):
    # adding a custom trailing-name makes a @mark.disable test newly appear
    monkeypatch.setattr(foundry, "WEAK_TEST_SKIP_NAMES", frozenset({"skip", "disable"}))
    assert foundry.find_always_skipped_tests("@mark.disable\ndef test_a(): pass\n") == ("test_a",), (
        "adding 'disable' to WEAK_TEST_SKIP_NAMES must make @mark.disable flag on a "
        "SUBSEQUENT call (constant read at call time)"
    )
    # removing 'skip' makes a plain @skip test no longer appear
    monkeypatch.setattr(foundry, "WEAK_TEST_SKIP_NAMES", frozenset())
    assert foundry.find_always_skipped_tests("@skip\ndef test_a(): pass\n") == (), (
        "clearing WEAK_TEST_SKIP_NAMES must make @skip no longer flag (read at call time)"
    )


def test_b8_both_modules_import():
    import subprocess
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b8_new_symbol_present_and_callable():
    assert callable(foundry.find_always_skipped_tests)
    for fn in CTRL + SIBLINGS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"


def test_b8_dormant_off_control_path():
    # the new symbol is referenced by NONE of the run-path functions NOR the
    # shipped weak-tests siblings (compiled-name introspection, not source text).
    for fn in CTRL + SIBLINGS:
        assert NEW_SYMBOL not in _fn_names(getattr(foundry, fn)), (
            f"foundry.{fn} references {NEW_SYMBOL!r} -- it must stay dormant / off the control path"
        )


def test_b8_dispatcher_does_not_reference_new_symbol():
    assert not hasattr(dispatcher, NEW_SYMBOL), f"dispatcher must not expose {NEW_SYMBOL!r}"
    assert NEW_SYMBOL not in _module_names(dispatcher), f"dispatcher references {NEW_SYMBOL!r}"


def test_b8_sibling_detectors_behaviour_unchanged():
    # black-box regression: iter-22 and iter-47 detectors behave exactly as before
    # (this bite adds only new symbols, edits no existing weak-test symbol).
    faf = foundry.find_assertionless_tests
    assert faf("def test_a():\n    pass\n") == ("test_a",)
    assert faf("def test_a():\n    assert 1 == 1\n") == ()
    fca = foundry.find_constant_assert_tests
    assert fca("def test_a():\n    assert True\n") == ("test_a",)
    assert fca("def test_a():\n    assert x == 1\n") == ()
