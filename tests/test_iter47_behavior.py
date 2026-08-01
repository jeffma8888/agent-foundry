"""Black-box behaviour tests for iter 47 -- the PURE, offline, deterministic
AST detector for constant/tautological-assert `test*` functions
(`find_constant_assert_tests(source) -> tuple[str, ...]`).

This is the offline slice of roadmap item 6 ("agents emit assertions that pass
without validating behaviour") that the shipped iter-22 `find_assertionless_tests`
does NOT catch: an assertion-free test has NO `assert` node, but a bare-literal
`assert True` / `assert 1` / `assert "x"` HAS one, so it reads as "has a signal"
to the iter-22 detector while validating nothing. iter 47 flags exactly that
class. It ships DORMANT (no CLI wiring this bite; zero call site on any run path).

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-8) and the product's own OBSERVABLE behaviour only. The implementation
source (foundry.py / dispatcher.py internals), the engineer's and reviewer's notes,
and `git diff` were NOT read. Every check drives the PUBLIC interface: the pure fn
via `foundry.find_constant_assert_tests(...)` on Python SOURCE STRINGS, the
disjoint sibling via `foundry.find_assertionless_tests(...)`, the patchable
constant via `foundry.WEAK_TEST_ASSERTION_CALLS`. The dormancy / off-control-path
checks (Behavior 8) use only public RUNTIME introspection -- module attributes and
compiled function name tables (`__code__.co_names`) -- NOT the source text (so
"the run-path functions do not reference the new symbol" is verified as "no
compiled reference in the run-path code objects", which honors isolation). Fully
offline + deterministic: no filesystem/subprocess/network/git/clock/agent-run
(except the documented `import foundry, dispatcher` regression probe).
"""
import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers (mirror tests/test_iter22_behavior.py compiled-introspection style)
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
SIBLINGS = ("weak_tests_cli", "find_assertionless_tests",
            "_has_assertion_signal", "summarize_weak_tests")
NEW_SYMBOL = "find_constant_assert_tests"


# ==========================================================================
# Behavior 1 -- flags a constant-only-assert test
# ==========================================================================
def test_b1_assert_true_is_flagged():
    r = foundry.find_constant_assert_tests("def test_a():\n    assert True\n")
    assert r == ("test_a",), f"a constant-only `assert True` test must be flagged, got {r!r}"
    assert isinstance(r, tuple), f"result must be a tuple, got {type(r)}"
    assert all(isinstance(x, str) for x in r), f"result elements must be str, got {r!r}"


def test_b1_every_bare_literal_flags():
    cases = {
        "def test_int():\n    assert 1\n": ("test_int",),
        "def test_zero():\n    assert 0\n": ("test_zero",),
        "def test_none():\n    assert None\n": ("test_none",),
        "def test_false():\n    assert False\n": ("test_false",),
        "def test_str():\n    assert \"ok\"\n": ("test_str",),
        "def test_float():\n    assert 3.14\n": ("test_float",),
        "def test_bytes():\n    assert b\"x\"\n": ("test_bytes",),
    }
    for src, want in cases.items():
        got = foundry.find_constant_assert_tests(src)
        assert got == want, f"a bare-literal `assert <const>` must be flagged; src={src!r} got={got!r}"


def test_b1_assertion_message_still_flags():
    # only the `.test` is inspected, never the `.msg`.
    r = foundry.find_constant_assert_tests('def test_m():\n    assert True, "boom"\n')
    assert r == ("test_m",), (
        f"a constant `.test` with an assertion message must STILL flag; got {r!r}"
    )


# ==========================================================================
# Behavior 2 -- does NOT flag a test carrying any real assertion signal
# ==========================================================================
def test_b2_non_constant_asserts_not_flagged():
    for src in (
        "def test_a():\n    assert x\n",            # Name
        "def test_a():\n    assert x == 1\n",       # Compare
        "def test_a():\n    assert func()\n",       # Call
        "def test_a():\n    assert not True\n",     # UnaryOp -- conservatively REAL
    ):
        r = foundry.find_constant_assert_tests(src)
        assert r == (), f"a non-constant assert is a real signal (not flagged); src={src!r} got={r!r}"


def test_b2_constant_plus_real_signal_not_flagged():
    # constant assert + a genuine check -> the real signal masks it.
    for src in (
        "def test_b():\n    assert True\n    assert x == 1\n",                     # non-const assert
        "def test_c():\n    assert True\n    with pytest.raises(ValueError):\n        f()\n",  # weak-call
        "def test_d():\n    assert True\n    raise ValueError\n",                  # Raise
        "class T:\n    def test_e(self):\n        assert True\n        self.assertEqual(1, 1)\n",  # assert* call
        "def test_f():\n    assert True\n    assertTrue(x)\n",                     # bare assert* call
    ):
        r = foundry.find_constant_assert_tests(src)
        assert r == (), (
            f"a test with a constant AND a real assertion signal must NOT be flagged; "
            f"src={src!r} got={r!r}"
        )


def test_b2_constant_plus_non_assert_call_still_flags():
    # a non-`assert*` call that is NOT in WEAK_TEST_ASSERTION_CALLS is NOT a
    # signal, so a co-resident constant assert still stands alone -> flagged.
    r = foundry.find_constant_assert_tests("def test_a():\n    assert True\n    verify(x)\n")
    assert r == ("test_a",), (
        f"a plain non-assert call (`verify`) is not a signal, so the constant assert "
        f"still flags the test; got {r!r}"
    )


# ==========================================================================
# Behavior 3 -- disjoint from find_assertionless_tests (no double-report)
# ==========================================================================
def test_b3_no_assert_node_not_flagged():
    for src in (
        "def test_d():\n    x = compute()\n",
        "def test_e():\n    pass\n",
    ):
        r = foundry.find_constant_assert_tests(src)
        assert r == (), (
            f"a test with no assert node has no constant assert -> not this detector's job; "
            f"src={src!r} got={r!r}"
        )


def test_b3_result_sets_are_disjoint():
    # one source with all three species: assertion-free, constant-only, real-assert.
    src = (
        "def test_free():\n    x = compute()\n\n"
        "def test_const():\n    assert True\n\n"
        "def test_real():\n    assert y == 2\n"
    )
    constless = foundry.find_constant_assert_tests(src)
    assertless = foundry.find_assertionless_tests(src)
    assert "test_const" in constless and "test_free" not in constless and "test_real" not in constless, (
        f"find_constant_assert_tests must flag ONLY the constant-only test; got {constless!r}"
    )
    assert "test_free" in assertless and "test_const" not in assertless and "test_real" not in assertless, (
        f"find_assertionless_tests must flag ONLY the assertion-free test; got {assertless!r}"
    )
    assert set(constless) & set(assertless) == set(), (
        f"the two detectors' result sets must be disjoint; "
        f"constless={constless!r} assertless={assertless!r}"
    )


# ==========================================================================
# Behavior 4 -- every test* def considered; non-test names ignored
# ==========================================================================
def test_b4_class_method_flagged():
    r = foundry.find_constant_assert_tests("class T:\n    def test_m(self):\n        assert 1\n")
    assert r == ("test_m",), f"a class test-method with a constant assert must be flagged; got {r!r}"


def test_b4_async_test_flagged():
    r = foundry.find_constant_assert_tests("async def test_n():\n    assert True\n")
    assert r == ("test_n",), f"an async constant-only test must be flagged; got {r!r}"


def test_b4_non_test_names_never_considered():
    for src in (
        "def helper():\n    assert True\n",
        "def check_x():\n    assert 1\n",
    ):
        r = foundry.find_constant_assert_tests(src)
        assert r == (), (
            f"a function whose name does not start with `test` is never considered; "
            f"src={src!r} got={r!r}"
        )


# ==========================================================================
# Behavior 5 -- ascending source order, not alphabetical
# ==========================================================================
def test_b5_source_order_not_alphabetical():
    src = "def test_z():\n    assert True\n\ndef test_a():\n    assert 1\n"
    r = foundry.find_constant_assert_tests(src)
    assert r == ("test_z", "test_a"), (
        f"multiple flagged tests must return in ascending source (line) order, "
        f"not alphabetical; got {r!r}"
    )


# ==========================================================================
# Behavior 6 -- WEAK_TEST_ASSERTION_CALLS read at CALL time (monkeypatch bites)
# ==========================================================================
def test_b6_weak_calls_read_at_call_time(monkeypatch):
    src = "def test_p():\n    assert True\n    pytest.raises(ValueError)\n"
    assert foundry.find_constant_assert_tests(src) == (), (
        "with the default WEAK_TEST_ASSERTION_CALLS, the `raises` call is a real "
        "signal so the constant assert is masked -> not flagged"
    )
    monkeypatch.setattr(foundry, "WEAK_TEST_ASSERTION_CALLS", frozenset())
    assert foundry.find_constant_assert_tests(src) == ("test_p",), (
        "after clearing WEAK_TEST_ASSERTION_CALLS the `raises` call no longer counts, "
        "leaving only the constant assert -> the SAME source now flags test_p "
        "(the constant is read at call time)"
    )


# ==========================================================================
# Behavior 7 -- SyntaxError on invalid source; empty/test-free -> ()
# ==========================================================================
def test_b7_syntax_error_propagates():
    with pytest.raises(SyntaxError):
        foundry.find_constant_assert_tests("def (:")


def test_b7_empty_and_test_free_return_empty_tuple():
    assert foundry.find_constant_assert_tests("") == ()
    assert foundry.find_constant_assert_tests("x = 1") == ()


# ==========================================================================
# Behavior 8 -- dormant, off the control path, importable; sibling unchanged
# ==========================================================================
def test_b8_both_modules_import():
    import subprocess
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b8_new_symbol_present_and_callable():
    assert callable(foundry.find_constant_assert_tests)
    # pre-existing control-flow + sibling entry points still present + callable (regression)
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
    # honors isolation: compiled-name introspection of the dispatcher module,
    # NOT a read of dispatcher.py source text.
    assert not hasattr(dispatcher, NEW_SYMBOL), f"dispatcher must not expose {NEW_SYMBOL!r}"
    assert NEW_SYMBOL not in _module_names(dispatcher), f"dispatcher references {NEW_SYMBOL!r}"


def test_b8_sibling_detector_behaviour_unchanged():
    # black-box regression: the shipped find_assertionless_tests must behave
    # exactly as iter-22 specified (this bite adds only new symbols, edits nothing).
    faf = foundry.find_assertionless_tests
    assert faf("def test_a():\n    pass\n") == ("test_a",)                      # assertion-free flagged
    assert faf("def test_a():\n    assert 1 == 1\n") == ()                      # assert -> signal
    assert faf("class T:\n    def test_a(self):\n        self.assertEqual(1,1)\n") == ()
    assert faf("def test_a():\n    with pytest.raises(ValueError):\n        f()\n") == ()
    # crux of disjointness: a constant assert reads as "has a signal" to the OLD
    # detector, so find_assertionless_tests does NOT flag a constant-only test.
    assert faf("def test_a():\n    assert True\n") == (), (
        "the shipped find_assertionless_tests must still treat a constant assert as "
        "a signal (unchanged) -- it is find_constant_assert_tests' job to flag it"
    )
    assert faf("def test_zebra():\n    pass\n\ndef test_apple():\n    pass\n") == (
        "test_zebra", "test_apple")  # source order preserved
