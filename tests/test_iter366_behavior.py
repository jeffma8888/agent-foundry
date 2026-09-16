"""Iteration 366 -- BLACK-BOX behavior tests: `find_assertionless_tests` counts a
call to a SAME-MODULE `def` as an assertion signal when that callee's OWN AST
subtree carries a signal -- exactly ONE level deep, proved from the callee's AST
and never from its name -- behind the module-level gate
`WEAK_TEST_RESOLVE_DELEGATES`.

Spec under test (products/_platform/state/iter-366/pm.md):
   1. same-module delegation IS a signal
   2. the callee must ACTUALLY carry a signal
   3. exactly ONE level -- no recursion
   4. a callee the module does not define is NOT a signal
   5. an attribute call resolves on its TRAILING name
   6. self-calls are NOT a signal
   7. a sibling `test_*` in the SAME module is a valid delegate
   8. gated by a module-level boolean READ AT CALL TIME; shipped default True
   9. monotonicity -- True-set is a SUBSET of False-set, over the tracked suite
  10. neighbours, totality, input polymorphism, order and purity untouched

ISOLATION HONORED: written from `pm.md`, the repo's own `tests/` conventions, the
roadmap files and the product's RUNTIME surface (calling its public functions and
reading `__doc__`) ONLY.  No implementation source file, no engineer / reviewer /
fixer note and no `git diff` was read.

FIXTURES ARE STRING LITERALS.  Every shape below is spelled as source TEXT, so the
repo's own live test-quality brakes see prose, not code.

OFFLINE + FRESH-CLONE SAFE: no network, no clock, and no ambient read except
Behavior 9's walk of `tests/*.py`, which git TRACKS, and which asserts a DERIVED
subset property -- never a hard-coded finding count.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
import time

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

THIS_ITER = 366

WEAK = "find_assertionless_tests"
CONST = "find_constant_assert_tests"
SKIPPED = "find_always_skipped_tests"
FLAG = "WEAK_TEST_RESOLVE_DELEGATES"


# --------------------------------------------------------------------------
# helpers -- every call goes through the BARE module name at CALL time, so a
# `monkeypatch.setattr(foundry, ...)` bites (the repo's shipped idiom)
# --------------------------------------------------------------------------
def _weak(source):
    return getattr(foundry, WEAK)(source)


def _const(source):
    return getattr(foundry, CONST)(source)


def _skipped(source):
    return getattr(foundry, SKIPPED)(source)


# --------------------------------------------------------------------------
# fixtures -- source TEXT only, one per Expected Behavior 1..7
# --------------------------------------------------------------------------
B1_SRC = (
    "def _check(v):\n"
    "    assert v\n"
    "\n"
    "\n"
    "def test_a():\n"
    "    _check(1)\n"
)

B2_SRC = (
    "def _noop(v):\n"
    "    print(v)\n"
    "\n"
    "\n"
    "def test_a():\n"
    "    _noop(1)\n"
)

B3_SRC = (
    "def _leaf():\n"
    "    assert True\n"
    "\n"
    "\n"
    "def _mid():\n"
    "    _leaf()\n"
    "\n"
    "\n"
    "def test_a():\n"
    "    _mid()\n"
)

B4_SRC = (
    "def test_a():\n"
    "    outside(1)\n"
    "\n"
    "\n"
    "def test_b():\n"
    "    mod.outside(1)\n"
)

B5_SRC = (
    "def _check():\n"
    "    assert True\n"
    "\n"
    "\n"
    "def test_a():\n"
    "    obj._check()\n"
)

B6_SRC = "def test_a():\n    test_a()\n"

B7_SRC = (
    "def test_a():\n"
    "    assert 1\n"
    "\n"
    "\n"
    "def test_b():\n"
    "    test_a()\n"
)

# name -> (source, expected with the gate True, expected with the gate False)
CASES = {
    "b1_same_module_delegate": (B1_SRC, (), ("test_a",)),
    "b2_signal_free_callee": (B2_SRC, ("test_a",), ("test_a",)),
    "b3_two_hop_chain": (B3_SRC, ("test_a",), ("test_a",)),
    "b4_undefined_callee": (B4_SRC, ("test_a", "test_b"), ("test_a", "test_b")),
    "b5_attribute_callee": (B5_SRC, (), ("test_a",)),
    "b6_self_call": (B6_SRC, ("test_a",), ("test_a",)),
    "b7_sibling_test_delegate": (B7_SRC, (), ("test_b",)),
}
CASE_IDS = sorted(CASES)

# defs deliberately out of alphabetical order -- pins ASCENDING LINE order
ORDER_SRC = (
    "def test_zebra():\n"
    "    x = 1\n"
    "\n"
    "\n"
    "def test_alpha():\n"
    "    y = 2\n"
)

BAD_SRC = "def test_bad(:\n"


# ==========================================================================
# Behavior 1 -- same-module delegation is a signal
# ==========================================================================
def test_b1_a_call_to_an_asserting_same_module_def_clears_the_test():
    got = _weak(B1_SRC)
    assert got == (), (
        "a test delegating to a same-module `def` that asserts must NOT be "
        "flagged; got " + repr(got)
    )


def test_b1_the_helper_itself_is_never_a_finding():
    """Anti-regression: the callee is not a `test*` name, so it can never enter
    the result set in either direction."""
    assert "_check" not in _weak(B1_SRC)
    assert "_check" not in _weak(B2_SRC)


# ==========================================================================
# Behavior 2 -- the callee must ACTUALLY carry a signal
# ==========================================================================
def test_b2_a_call_to_a_signal_free_same_module_def_is_not_a_signal():
    got = _weak(B2_SRC)
    assert got == ("test_a",), (
        "delegating to a same-module `def` whose body only prints must stay "
        "flagged; got " + repr(got)
    )


# ==========================================================================
# Behavior 3 -- exactly ONE level, no recursion
# ==========================================================================
def test_b3_a_two_hop_delegation_chain_stays_flagged():
    got = _weak(B3_SRC)
    assert got == ("test_a",), (
        "resolution is bounded to ONE level: `_mid` carries no signal of its "
        "own, so a test calling `_mid` stays flagged; got " + repr(got)
    )


def test_b3_the_one_hop_sibling_of_the_same_fixture_would_clear():
    """Non-vacuity for Behavior 3: the chain's LEAF does carry a signal, so the
    two-hop finding is a bound being honored, not a blind detector."""
    one_hop = B3_SRC.replace("def test_a():\n    _mid()\n", "def test_a():\n    _leaf()\n")
    assert _weak(one_hop) == (), (
        "a ONE-hop call to the asserting leaf must clear -- otherwise the "
        "two-hop assertion above proves nothing"
    )


# ==========================================================================
# Behavior 4 -- a callee the module does not define is not a signal
# ==========================================================================
def test_b4_callees_defined_outside_the_module_are_not_signals():
    got = _weak(B4_SRC)
    assert got == ("test_a", "test_b"), (
        "an imported / undefined callee must not clear a test, and results "
        "come back in ascending line order; got " + repr(got)
    )


# ==========================================================================
# Behavior 5 -- an attribute call resolves on its trailing name
# ==========================================================================
def test_b5_an_attribute_call_resolves_on_its_trailing_name():
    got = _weak(B5_SRC)
    assert got == (), (
        "`obj._check()` must resolve through the existing trailing-name rule "
        "to the same-module `_check`; got " + repr(got)
    )


# ==========================================================================
# Behavior 6 -- self-calls are not a signal
# ==========================================================================
def test_b6_a_self_call_never_clears_a_test():
    got = _weak(B6_SRC)
    assert got == ("test_a",), (
        "a test calling itself carries no assertion signal; got " + repr(got)
    )


# ==========================================================================
# Behavior 7 -- a sibling `test_*` in the SAME module is a valid delegate
# ==========================================================================
def test_b7_a_sibling_test_function_is_a_valid_delegate():
    got = _weak(B7_SRC)
    assert got == (), (
        "`test_b` delegating to the asserting sibling `test_a` must clear; "
        "got " + repr(got)
    )


# ==========================================================================
# Behaviors 1/2 -- shape pins the Acceptance Criteria name explicitly
# (`every `def`/`async def` name in `tree``, proved from the AST, not the name)
# ==========================================================================
ASYNC_CALLEE_SRC = (
    "async def _check():\n"
    "    assert True\n"
    "\n"
    "\n"
    "def test_a():\n"
    "    _check()\n"
)

ASYNC_TEST_SRC = (
    "def _check():\n"
    "    assert True\n"
    "\n"
    "\n"
    "async def test_a():\n"
    "    _check()\n"
)

IMPORT_SHADOW_SRC = (
    "import helpers as _check\n"
    "\n"
    "\n"
    "def test_a():\n"
    "    _check(1)\n"
)

LATE_CALLEE_SRC = (
    "def test_a():\n"
    "    _check(1)\n"
    "\n"
    "\n"
    "def _check(v):\n"
    "    assert v\n"
)


def test_b1_an_async_def_callee_is_a_valid_delegate():
    got = _weak(ASYNC_CALLEE_SRC)
    assert got == (), (
        "an `async def` callee whose subtree asserts must clear its caller; "
        "got " + repr(got)
    )


def test_b1_an_async_test_function_can_delegate_too():
    got = _weak(ASYNC_TEST_SRC)
    assert got == (), (
        "an `async def test_a` delegating to an asserting helper must clear; "
        "got " + repr(got)
    )


def test_b1_the_delegate_table_is_built_from_defs_not_from_names_in_scope():
    """An `import ... as _check` binds the name but is not a `def`, so it can
    carry no proved signal -- the table is AST evidence, not name matching."""
    got = _weak(IMPORT_SHADOW_SRC)
    assert got == ("test_a",), (
        "an imported name must never be resolved as a same-module delegate; "
        "got " + repr(got)
    )


def test_b1_a_callee_defined_after_its_caller_still_clears():
    """Module-wide resolution, not a single top-down pass."""
    got = _weak(LATE_CALLEE_SRC)
    assert got == (), (
        "definition order must not decide the verdict; got " + repr(got)
    )


# ==========================================================================
# Behavior 8 -- gated by a module-level boolean READ AT CALL TIME
# ==========================================================================
def test_b8_the_shipped_default_is_true():
    assert hasattr(foundry, FLAG), FLAG + " must exist at module level"
    value = getattr(foundry, FLAG)
    assert value is True, (
        FLAG + " must ship as the boolean True, got " + repr(value)
    )


@pytest.mark.parametrize("case", CASE_IDS)
def test_b8_every_case_matches_its_expected_value_with_the_gate_on(case, monkeypatch):
    source, expected_on, _ = CASES[case]
    monkeypatch.setattr(foundry, FLAG, True)
    got = _weak(source)
    assert got == expected_on, case + " with the gate True: got " + repr(got)


@pytest.mark.parametrize("case", CASE_IDS)
def test_b8_the_gate_is_read_at_call_time_not_captured_at_def_time(case, monkeypatch):
    """The flag is patched AFTER import, so a def-time capture would ignore it."""
    source, _, expected_off = CASES[case]
    monkeypatch.setattr(foundry, FLAG, False)
    got = _weak(source)
    assert got == expected_off, (
        case + " with the gate False must reproduce today's pre-delegation "
        "verdict; got " + repr(got)
    )


def test_b8_the_gate_only_moves_the_three_delegation_cases():
    """Pins WHICH cases the gate is allowed to move -- 1, 5 and 7 flip, the
    other four are identical either way (spec Behavior 8, both halves)."""
    flips = sorted(c for c in CASES if CASES[c][1] != CASES[c][2])
    assert flips == [
        "b1_same_module_delegate",
        "b5_attribute_callee",
        "b7_sibling_test_delegate",
    ], "the gate must move exactly Behaviors 1, 5 and 7: " + repr(flips)


# ==========================================================================
# Behavior 9 -- monotonicity, proved over the git-TRACKED suite
# ==========================================================================
def _tracked_test_files():
    """Relative paths of every `*.py` git tracks under `tests/`.

    Tracked-ness is what makes this fresh-clone safe: a gitignored file cannot
    be in the clone the post-release verifier builds.  Falls back to a plain
    glob only if `git` is unavailable, which is equivalent in a clean clone.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", "tests"],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout
        names = [n for n in out.split("\0") if n.endswith(".py")]
    except Exception:  # pragma: no cover -- git-less environment
        names = []
    if not names:  # pragma: no cover -- fallback only
        names = sorted(
            str(p.relative_to(_ROOT)) for p in (_ROOT / "tests").glob("*.py")
        )
    return names


def _parsed_tracked_trees():
    trees = {}
    for name in _tracked_test_files():
        path = _ROOT / name
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover
            continue
        try:
            trees[name] = ast.parse(text)
        except SyntaxError:  # pragma: no cover -- a deliberate bad fixture file
            continue
    return trees


def test_b9_the_gate_narrows_monotonically_over_every_tracked_test_file(monkeypatch):
    trees = _parsed_tracked_trees()
    assert len(trees) >= 2, (
        "the tracked `tests/` walk found too few parseable files to be "
        "meaningful: " + repr(sorted(trees))
    )

    monkeypatch.setattr(foundry, FLAG, True)
    with_on = {name: set(_weak(tree)) for name, tree in trees.items()}
    monkeypatch.setattr(foundry, FLAG, False)
    with_off = {name: set(_weak(tree)) for name, tree in trees.items()}

    widened = sorted(n for n in trees if not with_on[n] <= with_off[n])
    assert widened == [], (
        "delegation must only ever CLEAR a finding, never invent one; these "
        "files gained findings with the gate on: " + repr(widened)
    )

    differed = sorted(n for n in trees if with_on[n] != with_off[n])
    assert differed, (
        "non-vacuity: no tracked test file changed verdict, so the subset "
        "assertion above is vacuous on this tree"
    )


# ==========================================================================
# Behavior 10 -- neighbours, totality, polymorphism, order and purity
# ==========================================================================
@pytest.mark.parametrize("case", CASE_IDS)
def test_b10_the_two_neighbour_lenses_are_blind_to_the_gate(case, monkeypatch):
    source = CASES[case][0]
    monkeypatch.setattr(foundry, FLAG, True)
    const_on, skipped_on = _const(source), _skipped(source)
    monkeypatch.setattr(foundry, FLAG, False)
    const_off, skipped_off = _const(source), _skipped(source)
    assert const_on == const_off, (
        CONST + " changed with the gate on " + case + ": "
        + repr(const_on) + " vs " + repr(const_off)
    )
    assert skipped_on == skipped_off, (
        SKIPPED + " changed with the gate on " + case + ": "
        + repr(skipped_on) + " vs " + repr(skipped_off)
    )


def test_b10_the_neighbour_parity_check_is_not_vacuous():
    """At least one fixture makes a neighbour lens speak, so the parity
    assertions above are comparing real output, not two empty tuples."""
    assert _const(B7_SRC) != (), (
        CONST + " is expected to flag the constant `assert 1` in the "
        "Behavior-7 fixture; got " + repr(_const(B7_SRC))
    )


@pytest.mark.parametrize("case", CASE_IDS)
@pytest.mark.parametrize("gate", [True, False])
def test_b10_a_pre_parsed_module_agrees_with_source_text(case, gate, monkeypatch):
    source = CASES[case][0]
    monkeypatch.setattr(foundry, FLAG, gate)
    from_text = _weak(source)
    from_tree = _weak(ast.parse(source))
    assert from_text == from_tree, (
        case + " disagrees between text and tree input at gate " + repr(gate)
        + ": " + repr(from_text) + " vs " + repr(from_tree)
    )


@pytest.mark.parametrize("gate", [True, False])
def test_b10_invalid_python_still_raises_syntaxerror_verbatim(gate, monkeypatch):
    monkeypatch.setattr(foundry, FLAG, gate)
    with pytest.raises(SyntaxError):
        _weak(BAD_SRC)


@pytest.mark.parametrize("gate", [True, False])
def test_b10_results_stay_in_ascending_line_order(gate, monkeypatch):
    monkeypatch.setattr(foundry, FLAG, gate)
    got = _weak(ORDER_SRC)
    assert got == ("test_zebra", "test_alpha"), (
        "results must come back in ascending SOURCE order, not alphabetically; "
        "got " + repr(got)
    )


def test_b10_the_input_tree_is_not_mutated():
    tree = ast.parse(B1_SRC)
    before = ast.dump(tree)
    _weak(tree)
    assert ast.dump(tree) == before, "the input tree must not be mutated"


def test_b10_two_calls_on_equal_input_agree():
    first, second = _weak(B3_SRC), _weak(B3_SRC)
    assert first == second == ("test_a",), (
        "the lens must be deterministic: " + repr(first) + " vs " + repr(second)
    )


def test_b10_the_lens_touches_no_subprocess_no_clock_and_no_file(monkeypatch):
    seen = []
    real_run = foundry.subprocess.run
    real_time = time.time
    real_read = pathlib.Path.read_text

    def run_spy(*a, **k):  # pragma: no cover -- a hit is the failure
        seen.append(("subprocess.run", a[:1]))
        return real_run(*a, **k)

    def time_spy(*a, **k):  # pragma: no cover -- a hit is the failure
        seen.append(("time.time", a))
        return real_time(*a, **k)

    def read_spy(self, *a, **k):  # pragma: no cover -- a hit is the failure
        seen.append(("Path.read_text", str(self)))
        return real_read(self, *a, **k)

    monkeypatch.setattr(foundry.subprocess, "run", run_spy)
    monkeypatch.setattr(time, "time", time_spy)
    monkeypatch.setattr(pathlib.Path, "read_text", read_spy)
    got = _weak(B1_SRC + B2_SRC.replace("test_a", "test_probe"))
    monkeypatch.undo()
    assert got == ("test_probe",), (
        "the probe fixture must still be analysed: " + repr(got)
    )
    assert seen == [], (
        "a pure AST scan must not shell out, read the clock or touch a file: "
        + repr(seen)
    )


# ==========================================================================
# Acceptance criteria that are observable from OUTSIDE the implementation
# ==========================================================================
def test_ac_the_docstring_states_the_new_rule_its_bound_and_its_evidence():
    doc = " ".join((getattr(foundry, WEAK).__doc__ or "").split())
    for token in ("SAME MODULE", "ONE level", FLAG, "CALL time"):
        assert token in doc, (
            "the docstring must state the delegation rule; missing "
            + repr(token) + " in: " + doc
        )
    lowered = doc.lower()
    assert "proved from its ast" in lowered, (
        "the docstring must say the signal is PROVED from the callee's AST"
    )
    assert "never inferred from its name" in lowered, (
        "the docstring must say the signal is NOT inferred from the callee name"
    )


def test_ac_both_shipped_modules_still_import():
    assert foundry.__name__ == "foundry"
    assert dispatcher.__name__ == "dispatcher"


def test_ac_the_gate_is_not_a_config_field_or_a_cli_flag():
    """Out of Scope: the knob is a module constant only."""
    cfg = _ROOT / "products" / "_platform" / "config.json"
    assert FLAG not in cfg.read_text(encoding="utf-8"), (
        FLAG + " must not appear in the product config -- it is a module constant"
    )
