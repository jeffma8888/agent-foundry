"""Iteration 186 -- BLACK-BOX behavior tests: a 4th test-quality lens,
`find_unfailable_assert_tests`, which flags an `assert` that is TRUE BY
CONSTRUCTION, plus the LIVE suite brake holding the repo's own `tests/` tree at
ZERO such findings.

Spec under test (products/_platform/state/iter-186/pm.md):
   1. the function exists; `str | ast.AST` -> sorted, de-duplicated `tuple[str, ...]`
   2. kind `or-truthy`      -- BoolOp/Or with ANY truthy Constant operand
   3. kind `nonempty-tuple` -- Tuple literal with >= 1 element (empty tuple NOT flagged)
   4. kind `bare-truthy`    -- truthy Constant test (False / 0 / None NOT flagged)
   5. known-good set stays clean -- no false positives
   6. scope (`test*` only, async counted, nested found) and de-duplication
   7. string literals are not code
   8. AST-input parity, and a pre-parsed tree is NOT re-parsed
   9. totality BY PARITY with the sibling detector, and purity
  10. complementarity vs the two shipped assert lenses, proved on a FIXTURE
  11. LIVE BRAKE -- the repo's own tracked `tests/` tree carries ZERO findings,
      guarded by two anti-vacuity floors
  12. the one live instance (tests/test_iter152_behavior.py) is a REAL assertion now
  13. dormant / resume-safe -- no shipped consumer, both modules still import

ISOLATION HONORED: written from `pm.md`, the repo's own `tests/` conventions, the
roadmap files, the product config and the product's RUNTIME surface (calling its
public functions, `--help`, and `__doc__`) ONLY.  No implementation source file,
no engineer/reviewer/fixer notes and no `git diff` was read.

FIXTURES ARE STRING LITERALS ONLY.  This module spells every bad shape more often
than any other file in the repo, and behavior 7 is what makes that safe -- one test
below runs the detector over THIS file and requires `()`.

OFFLINE + FRESH-CLONE SAFE: no subprocess, no network, no clock.  The only
assertions about the ambient tree are over `tests/`, which git TRACKS; every other
fixture is a string literal or a `tmp_path` file.
"""
from __future__ import annotations

import ast
import contextlib
import inspect
import io
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

THIS_ITER = 186
THIS_FILE = pathlib.Path(__file__).name

NEW = "find_unfailable_assert_tests"
SIB = "find_constant_assert_tests"
WEAK = "find_assertionless_tests"
SKIPPED = "find_always_skipped_tests"
WALK = "_gather_weak_test_files"

# Anti-vacuity floors for the LIVE brake (behavior 11).  The spec measured the
# tracked tests/ tree at 164 files / 4,949 `test*` functions; these floors sit
# below that (an ordinary deletion must not red the build) and far above zero, so
# an empty walk or a stubbed detector cannot satisfy the brake.
MIN_LIVE_FILES = 160
MIN_LIVE_TEST_FUNCS = 4900

ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
ITER152 = _ROOT / "tests" / "test_iter152_behavior.py"


# --------------------------------------------------------------------------
# helpers -- every call goes through the BARE module name so monkeypatch works
# --------------------------------------------------------------------------
def _new(source):
    return getattr(foundry, NEW)(source)


def _sib(source):
    return getattr(foundry, SIB)(source)


def _fn(*lines, name="test_a", head="def"):
    """Build a one-function module SOURCE STRING from statement lines."""
    body = "".join("    " + ln + "\n" for ln in lines)
    return head + " " + name + "():\n" + body


def _outcome(fn, arg):
    """Total outcome of a call: a value, or the exception TYPE NAME it raised."""
    try:
        return ("value", fn(arg))
    except Exception as exc:                      # noqa: BLE001 -- parity probe
        return ("raise", type(exc).__name__)


def _count_test_funcs(source):
    """Independent census of `test*` functions -- never uses the lens under test."""
    tree = ast.parse(source)
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
    )


def _capture(fn):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = fn()
        except SystemExit as exc:                 # argparse / early exit
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def _write_cfg(tmp_path, files=None, **over):
    """A minimal product config whose repo is a TMP dir."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    for rel, body in (files or {}).items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    out = tmp_path / "config.json"
    out.write_text(json.dumps(data))
    return out


# --------------------------------------------------------------------------
# FIXTURES -- string literals, never live code (behavior 7)
# --------------------------------------------------------------------------
OR_TRUTHY = (
    "assert x == 1 or True",
    "assert True or x == 1",
    "assert x or 1",
    'assert x or "msg"',
)

NONEMPTY_TUPLE = (
    'assert (cond, "msg")',
    "assert (cond,)",
)

BARE_TRUTHY = (
    "assert True",
    "assert 1",
    'assert "msg"',
)

POSITIVE = OR_TRUTHY + NONEMPTY_TUPLE + BARE_TRUTHY

KNOWN_GOOD = (
    "assert x == y",
    "assert fn(a) == ()",
    "assert x or y",
    "assert x or False",
    "assert x or None",
    "assert not x",
    "assert len(v) >= 48",
    "assert isinstance(a, str)",
    'assert x == y, "msg"',
    "assert ()",            # falsy -- ALWAYS fails; a different defect (behavior 3)
    "assert False",         # behavior 4
    "assert 0",
    "assert None",
    "assert x or []",       # Out of Scope -- no dataflow inference
    "assert x == x",        # Out of Scope -- no tautology inference
)

# The live iter-152 shape, reproduced as a fixture (behavior 10): real asserts
# PLUS one ` or True` tail.  A string literal, so it is not code here.
ITER152_SHAPE = '''def test_b01_shared_body_takes_two_new_optional_passthrough_params():
    sig = inspect.signature(shared)
    params = list(sig.parameters)
    assert len(params) == 6, "exactly two NEW pass-through parameters expected"
    for name in params[4:]:
        assert sig.parameters[name].kind is not inspect.Parameter.KEYWORD_ONLY or True
'''

# behavior 7 -- the bad shape appears ONLY inside a nested string literal
STRING_ONLY = (
    'SRC = "def test_a():\\n    assert x or True\\n"\n'
    'OTHER = """def test_b():\\n    assert True\\n"""\n'
    "def test_real():\n"
    "    assert helper(SRC) == ()\n"
)


# ==========================================================================
# Behavior 1 -- existence, signature, return contract
# ==========================================================================
def test_b01_exists_as_a_module_level_callable_mirroring_its_sibling():
    fn = getattr(foundry, NEW, None)
    assert callable(fn), NEW + " must exist as a module-level function in foundry"
    new_params = list(inspect.signature(fn).parameters)
    sib_params = list(inspect.signature(getattr(foundry, SIB)).parameters)
    assert len(new_params) == 1, "one input parameter expected, got " + repr(new_params)
    assert new_params == sib_params, (
        "the new lens must MIRROR " + SIB + "'s parameter name: "
        + repr(new_params) + " vs " + repr(sib_params)
    )


def test_b01_returns_a_sorted_deduped_tuple_of_names():
    src = _fn("assert True", name="test_zeta") + "\n" + _fn("assert 1", name="test_alpha")
    got = _new(src)
    assert isinstance(got, tuple), "return type must be a tuple, got " + type(got).__name__
    assert all(isinstance(n, str) for n in got), "members must be str: " + repr(got)
    assert got == ("test_alpha", "test_zeta"), "result must be sorted: " + repr(got)
    assert len(set(got)) == len(got), "result must be de-duplicated: " + repr(got)


def test_b01_returns_empty_tuple_when_there_are_no_findings():
    got = _new(_fn("assert x == y"))
    assert got == (), "a clean source must yield the empty tuple, got " + repr(got)


# ==========================================================================
# Behavior 2 -- kind `or-truthy`
# ==========================================================================
@pytest.mark.parametrize("line", OR_TRUTHY)
def test_b02_or_with_any_truthy_constant_operand_is_flagged(line):
    got = _new(_fn(line))
    assert got == ("test_a",), "or-truthy shape " + repr(line) + " must flag: " + repr(got)


def test_b02_the_truthy_operand_may_sit_on_either_side_of_the_or():
    left = _new(_fn("assert True or x == 1"))
    right = _new(_fn("assert x == 1 or True"))
    assert left == right == ("test_a",), (
        "operand ORDER must not matter: left=" + repr(left) + " right=" + repr(right)
    )


# ==========================================================================
# Behavior 3 -- kind `nonempty-tuple`
# ==========================================================================
@pytest.mark.parametrize("line", NONEMPTY_TUPLE)
def test_b03_nonempty_tuple_literal_is_flagged(line):
    got = _new(_fn(line))
    assert got == ("test_a",), "tuple footgun " + repr(line) + " must flag: " + repr(got)


def test_b03_empty_tuple_is_not_flagged_it_always_fails():
    got = _new(_fn("assert ()"))
    assert got == (), (
        "`assert ()` is FALSY -- it always fails, a different defect, out of this lens: "
        + repr(got)
    )


# ==========================================================================
# Behavior 4 -- kind `bare-truthy`
# ==========================================================================
@pytest.mark.parametrize("line", BARE_TRUTHY)
def test_b04_truthy_constant_test_is_flagged(line):
    got = _new(_fn(line))
    assert got == ("test_a",), "bare-truthy " + repr(line) + " must flag: " + repr(got)


@pytest.mark.parametrize("line", ["assert False", "assert 0", "assert None"])
def test_b04_falsy_constant_test_is_not_flagged(line):
    got = _new(_fn(line))
    assert got == (), repr(line) + " is falsy -- it always FAILS, so not this lens: " + repr(got)


# ==========================================================================
# Behavior 5 -- no false positives on the known-good set
# ==========================================================================
@pytest.mark.parametrize("line", KNOWN_GOOD)
def test_b05_known_good_asserts_are_never_flagged(line):
    got = _new(_fn(line))
    assert got == (), "false positive on known-good " + repr(line) + ": " + repr(got)


def test_b05_a_message_is_not_part_of_the_asserts_test():
    """`assert x == y, "msg"` -- the message is `.msg`, never `.test`."""
    with_msg = _new(_fn('assert x == y, "msg"'))
    without = _new(_fn("assert x == y"))
    assert with_msg == without == (), (
        "an assert MESSAGE must not be read as the test: " + repr(with_msg) + " vs " + repr(without)
    )


def test_b05_the_whole_known_good_set_is_clean_in_one_module():
    got = _new(_fn(*KNOWN_GOOD))
    assert got == (), "the whole known-good body must stay clean: " + repr(got)


# ==========================================================================
# Behavior 6 -- scope and de-duplication
# ==========================================================================
def test_b06_a_non_test_helper_is_not_considered():
    got = _new(_fn("assert True", name="_helper"))
    assert got == (), "only `test*` functions are in scope: " + repr(got)


def test_b06_an_async_test_function_is_considered():
    got = _new(_fn("assert True", name="test_async_one", head="async def"))
    assert got == ("test_async_one",), "an `async def test_*` must be in scope: " + repr(got)


def test_b06_three_unfailable_asserts_report_the_function_exactly_once():
    got = _new(_fn("assert True", "assert x or 1", 'assert (c, "m")', name="test_thrice"))
    assert got == ("test_thrice",), "de-duplication required, got " + repr(got)
    assert len(got) == 1, "exactly one entry for three findings, got " + repr(got)


def test_b06_a_test_function_nested_inside_another_function_is_found():
    src = "def outer():\n    def test_nested():\n        assert True\n    return test_nested\n"
    got = _new(src)
    assert "test_nested" in got, "a nested `test*` function must be found: " + repr(got)


def test_b06_a_test_method_on_a_class_is_considered():
    """Reasonable-reading note: the spec does not name class methods; the shipped
    sibling lens flags them, so parity is the most reasonable reading."""
    src = "class TestThing:\n    def test_m(self):\n        assert 1\n"
    assert _new(src) == _sib(src), (
        "class-method scope must agree with the sibling lens: "
        + repr(_new(src)) + " vs " + repr(_sib(src))
    )


# ==========================================================================
# Behavior 7 -- string literals are not code
# ==========================================================================
def test_b07_the_bad_shape_inside_a_string_literal_is_not_a_finding():
    got = _new(STRING_ONLY)
    assert got == (), (
        "a fixture STRING spelling the bad shape must not be flagged (behavior 7): " + repr(got)
    )


def test_b07_this_very_test_module_reports_zero_findings():
    """Load-bearing: this file spells every bad shape, in string literals only."""
    src = pathlib.Path(__file__).read_text()
    assert " or True" in src, "sanity: this module is expected to SPELL the bad shape"
    got = _new(src)
    assert got == (), THIS_FILE + " must itself be clean under the new lens: " + repr(got)


# ==========================================================================
# Behavior 8 -- AST-input parity, and no re-parse of a pre-parsed tree
# ==========================================================================
@pytest.mark.parametrize("line", POSITIVE + KNOWN_GOOD)
def test_b08_ast_input_matches_string_input(line):
    src = _fn(line)
    assert _new(ast.parse(src)) == _new(src), (
        "AST-input parity broken for " + repr(line) + ": "
        + repr(_new(ast.parse(src))) + " vs " + repr(_new(src))
    )


def test_b08_a_pre_parsed_tree_is_not_re_parsed(monkeypatch):
    src = _fn("assert x or 1")
    tree = ast.parse(src)
    calls = []
    real = ast.parse

    def spy(*a, **k):
        calls.append(a[:1])
        return real(*a, **k)

    monkeypatch.setattr(ast, "parse", spy)
    got = _new(tree)
    assert got == ("test_a",), "a pre-parsed tree must still be analysed: " + repr(got)
    assert calls == [], "a pre-parsed tree must NOT be re-parsed, saw " + repr(len(calls))


# ==========================================================================
# Behavior 9 -- totality BY PARITY with the sibling, and purity
# ==========================================================================
@pytest.mark.parametrize("arg", [None, b"def test_a():\n    assert True\n", 123, "", []])
def test_b09_degenerate_input_behaves_exactly_like_the_sibling(arg):
    """Agreement, never a restated convention: whatever `constant-asserts` does on
    this input -- return `()` or raise -- the new lens does the same."""
    assert _outcome(_new, arg) == _outcome(_sib, arg), (
        "totality parity broken for " + repr(arg) + ": new="
        + repr(_outcome(_new, arg)) + " sibling=" + repr(_outcome(_sib, arg))
    )


def test_b09_two_calls_on_equal_input_are_equal():
    src = _fn("assert True", "assert x == y", name="test_pure")
    first, second = _new(src), _new(src)
    assert first == second == ("test_pure",), (
        "the lens must be deterministic: " + repr(first) + " vs " + repr(second)
    )


def test_b09_the_argument_is_not_mutated():
    tree = ast.parse(_fn("assert x or 1"))
    before = ast.dump(tree)
    _new(tree)
    assert ast.dump(tree) == before, "the input tree must not be mutated"


def test_b09_touches_no_subprocess_and_no_clock(monkeypatch):
    seen = []
    real_run, real_time = foundry.subprocess.run, foundry.time.time

    def run_spy(*a, **k):
        seen.append(("subprocess.run", a[:1]))
        return real_run(*a, **k)

    def time_spy(*a, **k):
        seen.append(("time.time", a))
        return real_time(*a, **k)

    monkeypatch.setattr(foundry.subprocess, "run", run_spy)
    monkeypatch.setattr(foundry.time, "time", time_spy)
    got = _new(_fn("assert True", *KNOWN_GOOD, name="test_impure_probe"))
    assert got == ("test_impure_probe",), "the probe fixture must still be analysed: " + repr(got)
    assert seen == [], "a pure AST lens must not shell out or read the clock: " + repr(seen)


# ==========================================================================
# Behavior 10 -- complementarity, proved on a FIXTURE (never the live file)
# ==========================================================================
def test_b10_the_two_shipped_assert_lenses_are_blind_to_the_iter152_shape():
    weak = getattr(foundry, WEAK)(ITER152_SHAPE)
    const = _sib(ITER152_SHAPE)
    assert weak == (), WEAK + " is expected to be blind to this shape, got " + repr(weak)
    assert const == (), SIB + " is expected to be blind to this shape, got " + repr(const)


def test_b10_the_new_lens_catches_the_iter152_shape_the_others_miss():
    got = _new(ITER152_SHAPE)
    assert got == ("test_b01_shared_body_takes_two_new_optional_passthrough_params",), (
        "the 4th lens must flag the shape both shipped lenses miss: " + repr(got)
    )


def test_b10_the_same_function_stripped_of_the_bad_tail_is_clean():
    """Two-sided: the lens fires on the ` or True` tail, not on the function."""
    clean = ITER152_SHAPE.replace(" or True", "")
    assert _new(clean) == (), (
        "without the unfailable tail the function must be clean: " + repr(_new(clean))
    )


# ==========================================================================
# Behavior 11 -- LIVE BRAKE over the repo's own tracked tests/ tree
# ==========================================================================
def test_b11_live_tests_tree_carries_zero_unfailable_asserts():
    files = getattr(foundry, WALK)(str(_ROOT))
    names = [pathlib.Path(p).name for p in files]
    assert len(files) >= MIN_LIVE_FILES, (
        "anti-vacuity floor: the walk must cover >= %d files, saw %d"
        % (MIN_LIVE_FILES, len(files))
    )
    assert THIS_FILE in names, "the walk MUST include this iteration's new test file"
    total_funcs = 0
    findings = {}
    for p in files:
        src = pathlib.Path(p).read_text()
        total_funcs += _count_test_funcs(src)
        got = _new(src)
        if got:
            findings[pathlib.Path(p).name] = got
    assert total_funcs >= MIN_LIVE_TEST_FUNCS, (
        "anti-vacuity floor: >= %d `test*` functions expected, counted %d"
        % (MIN_LIVE_TEST_FUNCS, total_funcs)
    )
    assert findings == {}, "the tracked tests/ tree must carry ZERO unfailable asserts: " + repr(
        findings
    )


def test_b11_the_brake_trips_when_an_unfailable_assert_is_added(tmp_path):
    """The OTHER side of the brake, proved on a tmp repo so the real tree is untouched."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_clean.py").write_text(_fn("assert x == y"))
    before = getattr(foundry, WALK)(str(repo))
    assert [p.name for p in before] == ["test_clean.py"], repr(before)
    assert sum(len(_new(p.read_text())) for p in before) == 0, "the clean repo must score 0"
    (repo / "tests" / "test_bad.py").write_text(_fn("assert x == 1 or True", name="test_bad_one"))
    after = getattr(foundry, WALK)(str(repo))
    total = sum(len(_new(p.read_text())) for p in after)
    assert total == 1, "adding one unfailable assert must trip the brake, scored " + repr(total)


def test_b11_a_stubbed_detector_cannot_satisfy_this_module(monkeypatch):
    """Anti-vacuity as an executable claim: with the lens stubbed to always return
    `()` every positive fixture in this module goes blind, so the zero-findings
    brake is only meaningful alongside those fixtures."""
    real = [src for src in POSITIVE if _new(_fn(src)) == ("test_a",)]
    assert len(real) == len(POSITIVE), "every positive fixture must flag for real: " + repr(real)
    monkeypatch.setattr(foundry, NEW, lambda source: ())
    blind = [src for src in POSITIVE if _new(_fn(src)) == ()]
    assert len(blind) == len(POSITIVE), (
        "an always-() stub must be blind to every positive fixture: " + repr(blind)
    )


# ==========================================================================
# Behavior 12 -- the one live instance is a REAL assertion now
# ==========================================================================
def test_b12_the_iter152_file_no_longer_carries_the_unfailable_tail():
    src = ITER152.read_text()
    assert src.count(" or True") == 0, (
        "tests/test_iter152_behavior.py must carry no ` or True` tail, found "
        + repr(src.count(" or True"))
    )
    assert _new(src) == (), "the repaired file must be clean under the new lens: " + repr(_new(src))


def test_b12_the_repaired_assertion_is_real_and_carries_a_message():
    tree = ast.parse(ITER152.read_text())
    target = "test_b01_shared_body_takes_two_new_optional_passthrough_params"
    fns = [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == target
    ]
    assert len(fns) == 1, "expected exactly one " + target + ", found " + repr(len(fns))
    kw_asserts = [
        a
        for a in ast.walk(fns[0])
        if isinstance(a, ast.Assert) and "KEYWORD_ONLY" in ast.dump(a.test)
    ]
    assert len(kw_asserts) == 1, (
        "expected exactly one KEYWORD_ONLY assertion, found " + repr(len(kw_asserts))
    )
    node = kw_asserts[0]
    assert not isinstance(node.test, ast.BoolOp), (
        "the repaired assertion must not be an Or-chain any more: " + ast.dump(node.test)
    )
    assert node.msg is not None, "the repaired assertion must carry a message"


# ==========================================================================
# Behavior 13 -- dormant / resume-safe
# ==========================================================================
def test_b13_both_modules_still_import():
    assert foundry.__name__ == "foundry", "foundry must stay importable"
    assert dispatcher.__name__ == "dispatcher", "dispatcher must stay importable"


def test_b13_no_new_cli_surface_names_the_lens():
    tokens = ("unfailable", "unfailable-asserts", "UnfailableAssert")
    code, top, _ = _capture(lambda: foundry.main(["--help"]))
    assert top, "top-level --help must still print (exit " + repr(code) + ")"
    assert [t for t in tokens if t in top] == [], top
    for verb in ("weak-tests", "constant-asserts", "skipped-tests", "test-quality"):
        _, txt, _ = _capture(lambda v=verb: foundry.main([v, "--help"]))
        assert [t for t in tokens if t in txt] == [], (verb, txt)


def test_b13_the_dispatcher_namespace_and_product_config_do_not_name_the_lens():
    assert getattr(dispatcher, NEW, None) is None, "the dispatcher must not import the lens"
    cfg_text = (_ROOT / "products" / "_platform" / "config.json").read_text()
    assert "unfailable" not in cfg_text.lower(), "no config field may name the lens: " + cfg_text
    for card in sorted((_ROOT / "roles").glob("*.md")):
        assert "unfailable" not in card.read_text().lower(), "role card names the lens: " + card.name


def test_b13_no_shipped_hygiene_verb_consults_the_new_lens(tmp_path, monkeypatch):
    """Dormancy proved by BEHAVIOR: make the lens explode, then run every shipped
    test-quality verb -- a live call site would surface as an error here."""
    cfg = _write_cfg(tmp_path, {"tests/test_a.py": _fn("assert x == y")})

    def boom(source):
        raise AssertionError("DORMANT contract: no shipped verb may consult " + NEW)

    monkeypatch.setattr(foundry, NEW, boom)
    for verb in ("weak-tests", "constant-asserts", "skipped-tests", "test-quality"):
        code, out, err = _capture(lambda v=verb: foundry.main([v, "--config", str(cfg)]))
        assert code in (0, 1), (verb, code, out, err)
        assert "DORMANT contract" not in (out + err), (verb, out, err)


# ==========================================================================
# Acceptance criteria -- docstring contract and the roadmap record
# ==========================================================================
def test_ac_docstring_states_the_three_kinds_the_dormant_status_and_the_overlap():
    doc = getattr(foundry, NEW).__doc__ or ""
    assert doc.strip(), NEW + " must carry a docstring"
    missing = [k for k in ("or-truthy", "nonempty-tuple", "bare-truthy") if k not in doc]
    assert missing == [], "docstring must name all three kinds; missing " + repr(missing)
    assert "DORMANT" in doc, "docstring must record the DORMANT status: " + doc
    assert "OVERLAP" in doc.upper(), "docstring must document the constant-asserts OVERLAP: " + doc


def test_ac_docstring_overlap_claim_is_true_of_the_code():
    """The documented overlap is not prose-only: a function whose only signal is
    `assert True` must be flagged by BOTH lenses."""
    src = _fn("assert True", name="test_both")
    assert _new(src) == ("test_both",), repr(_new(src))
    assert _sib(src) == ("test_both",), (
        "the documented OVERLAP with constant-asserts must hold: " + repr(_sib(src))
    )


def test_ac_roadmap_record_lands_in_this_commit():
    ledger = [ln for ln in ROADMAP.read_text().splitlines()
              if ln.startswith("- iter %d " % THIS_ITER)]
    assert len(ledger) == 1, "exactly one iter-%d ledger row required: %r" % (THIS_ITER, ledger)
    assert len(ledger[0]) <= 120, "ledger row must be <=120 chars, got %d" % len(ledger[0])
    bullets = [ln for ln in ARCHIVE.read_text().splitlines()
               if ln.startswith("- **iter %d " % THIS_ITER)]
    assert len(bullets) == 1, "exactly one archive bullet required, got %d" % len(bullets)
