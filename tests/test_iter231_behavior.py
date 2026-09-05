"""Iteration 231 -- BLACK-BOX behavior tests: prose can no longer arm a brake.

The product grows one PURE text oracle, ``foundry.prose_stripped_source``, which
blanks every comment and string literal of a Python source to spaces while keeping
its length, its lines and its columns.  The self-referential brake of iteration 214
(``test_ac_the_brake_pins_no_ambient_file_count``) then searches THAT instead of its
raw text, so a historical iteration number written in PROSE can never again equal an
ambient file count and red the whole suite.  The iteration also RE-LANDS the
behavior-complete work that exact coincidence destroyed one iteration ago.

Spec under test (products/_platform/state/iter-231/pm.md), Expected Behaviors 1-8:
   1. The helper exists, is module-level, takes one positional argument, is TOTAL
      (``""`` for ``None`` and any non-``str``) and never raises on any ``str``.
   2. Shape is preserved exactly for every source the tokenizer accepts: same
      ``len()``, same count of newlines, every newline at the SAME index.
   3. Prose is blanked to spaces and code is byte-identical -- including a
      MULTI-line triple-quoted literal, whose newlines survive.
   4. An f-string's literal text cannot smuggle a numeral.
   5. FAIL-CLOSED on source the tokenizer rejects: the input comes back UNCHANGED,
      so a caller searching the result can never see LESS than without the helper.
   6. The brake reads the stripped source, still fails per counter, and the disarm
      is MEASURED over the live brake file rather than asserted by fiat.
   7. The narrowed brake is still FAILABLE -- an ambient-count pin in CODE survives
      stripping, the same numeral in prose alone does not (both on synthetic text).
   8. The previous iteration's reverted feature is back and whole.

Also guarded, from the spec's ACCEPTANCE CRITERIA rather than its Expected Behaviors,
and decidable from TRACKED text alone so every verdict still holds in the fresh clone
the release gate verifies from (OPERATOR 2026-08-11 -- a shipped iteration went
post-release BROKEN on a precondition that was only true in one working tree):
   A. Both roadmap records land in the SAME diff as the code -- the product's own
      ``roadmap_ledger_gaps`` oracle reports NO gap for this iteration or the one it
      re-lands, and this iteration's ledger row is at most 120 chars.
   B. This module is on the b15 allow-list of ``tests/test_iter204_behavior.py``.
   C. ``import foundry`` and ``import dispatcher`` both succeed in-process.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-231 PM spec, the
conventions of ``tests/`` (the frozen-literal / criteria-suffix shape of
``tests/test_iter229_behavior.py`` and the counter derivation of
``tests/test_iter214_behavior.py``), and the product's OWN OBSERVABLE surface --
importing the modules and calling their public functions.  The implementation TEXT of
``foundry.py`` was NOT read; where a criterion is only decidable from source text (the
call-site shape of behavior 6) the text is passed to ``ast`` or to a machine scan and
never inspected by hand.  ``engineer.md``, ``reviewer.md``, ``IMPLEMENTATION.patch``
and ``git diff`` were NOT read.

Offline and deterministic: behaviors 1-5 and 7 touch no subprocess, git, network,
clock or file at all; behaviors 6 and 8 and the criteria read only TRACKED repo text
plus (behavior 6) two read-only ``git ls-files`` queries that SKIP rather than red
where git cannot answer.  No assertion reads a gitignored path, and no assertion
spells an ambient count of anything -- every count is derived.
"""

import ast
import io
import pathlib
import re
import subprocess
import sys
import tokenize

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe

THIS_ITER = 231
RELAND_ITER = THIS_ITER - 1

# Names are FIXED by the spec, so they are reached by string: a rename in the
# implementation must fail these tests loudly rather than silently stop testing.
HELPER = "prose_stripped_source"
BRAKE_TEST = "test_ac_the_brake_pins_no_ambient_file_count"
DRIFT_LINE = "test_touch_drift_line"
DRIFT_PREFIX_NAME = "TEST_TOUCH_PREFIX"

TESTS_DIR = _ROOT / "tests"
BRAKE_MODULE = TESTS_DIR / "test_iter214_behavior.py"
ALLOW_LIST_MODULE = TESTS_DIR / "test_iter204_behavior.py"
RELAND_MODULE = TESTS_DIR / "test_iter230_behavior.py"
README = _ROOT / "README.md"
ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"

# The nine paths the preserved patch of the re-landed iteration carries.  Named
# relative, NEVER absolute (an iteration was reverted for one absolute-home literal).
RELANDED_PATHS = (
    "DIRECTIONS.md",
    "PLATFORM_ROADMAP.md",
    "PLATFORM_ROADMAP_ARCHIVE.md",
    "README.md",
    "foundry.py",
    "tests/test_iter145_behavior.py",
    "tests/test_iter164_behavior.py",
    "tests/test_iter204_behavior.py",
    "tests/test_iter230_behavior.py",
)

DIGITS = re.compile(r"\b\d+\b")
DRIFT_PHRASE = re.compile(r"(?i)\bfive drift lines\b")

# Used ONLY inside the string fixtures below.  Deliberately a number that counts
# nothing in this repo, so no assertion here depends on the ambient tree.
SYNTH = "4242"
# The historical incident numeral of behavior 3's fixture, likewise inert here.
INCIDENT = "6000"

# Sources the tokenizer accepts, for behaviors 1 and 2.
ACCEPTED = (
    "",
    "\n",
    "x = 1\n",
    "x = 1\r\n",
    "#\n",
    "# a lone comment",
    'x = 1\n"""doc"""\n',
    "def f():\n    return 1  # tail\n",
    "s = 'a' + \"b\"  # both quote styles\n",
)

# Sources the tokenizer REJECTS, for behaviors 1 and 5.  Each witness is confirmed
# to raise on the running interpreter by the test itself, never assumed.
MALFORMED = ('x = "abc\n', 'x = """abc\n', "\x00")

B3_SRC = 'x = 1\n"""doc ' + INCIDENT + ' files"""\nassert n == ' + INCIDENT \
    + '  # ' + INCIDENT + '\n'
B3_CODE_LINE = "assert n == " + INCIDENT
B3_MULTILINE = 'a = 1\nD = """\nprose ' + INCIDENT + '\nmore ' + INCIDENT \
    + '\n"""\nb = 2\n'


def _strip(source):
    """The helper under test, reached by name so a rename reds loudly."""
    return getattr(foundry, HELPER)(source)


def _tokenizes(source: str) -> bool:
    try:
        list(tokenize.generate_tokens(io.StringIO(source).readline))
    except Exception:  # noqa: BLE001 -- any tokenizer refusal counts
        return False
    return True


def _newline_indexes(text: str):
    return tuple(index for index, char in enumerate(text) if char == "\n")


def _brake_source() -> str:
    return BRAKE_MODULE.read_text(encoding="utf-8")


def _brake_function():
    """The brake's ast node plus its module source, or a loud failure."""
    source = _brake_source()
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == BRAKE_TEST:
            return node, source
    pytest.fail(f"{BRAKE_MODULE.name} no longer defines {BRAKE_TEST}")


def _call_name(node) -> str:
    """The dotted-ish name of a call target, '' when it is not a plain name."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _population_or_skip():
    """The shipping population, derived the way the brake derives it, or SKIP.

    A machine with no git, or a checkout that is not a work tree, cannot support
    this check at all, and a red suite there would block every iteration for a
    reason the repo cannot fix.  So the failure mode is a skip, never a red.
    """
    queries = (("ls-files", "-c"), ("ls-files", "-o", "--exclude-standard"))
    paths = set()
    for query in queries:
        try:
            done = subprocess.run(
                ("git",) + query, cwd=str(_ROOT), capture_output=True,
                text=True, timeout=120, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            pytest.skip(f"cannot enumerate the shipping population: {exc}")
        paths.update(line for line in done.stdout.split("\n") if line)
    if not paths:
        pytest.skip("the shipping population is empty (not a git work tree?)")
    return paths


def _tests_py_count() -> int:
    """The brake's other counter, derived the same way it derives it."""
    return len([path for path in TESTS_DIR.rglob("*.py")
                if "__pycache__" not in path.parts])


# ---------------------------------------------------------------- behavior 1

def test_b1_the_helper_is_a_module_level_function_of_one_positional_argument():
    import inspect

    function = getattr(foundry, HELPER, None)
    assert inspect.isfunction(function), \
        f"foundry.{HELPER} must be a module-level function"
    assert function.__module__ == "foundry", \
        f"{HELPER} must be defined in foundry, not re-exported from elsewhere"
    parameters = list(inspect.signature(function).parameters.values())
    assert len(parameters) == 1, f"{HELPER} takes exactly one argument"
    assert parameters[0].kind in (inspect.Parameter.POSITIONAL_ONLY,
                                 inspect.Parameter.POSITIONAL_OR_KEYWORD), \
        f"{HELPER}'s single argument must be passable positionally"
    assert _strip("") == "", "the empty source strips to the empty string"


def test_b1_non_str_input_returns_empty_rather_than_raising():
    for value in (None, 7, 3.5, True, b"x = 1\n", ["x = 1"], {"x": 1}, object()):
        assert _strip(value) == "", \
            f"{HELPER}({type(value).__name__}) must return '' rather than raise"


def test_b1_no_str_input_makes_the_helper_raise():
    for source in ACCEPTED + MALFORMED + (B3_SRC, B3_MULTILINE):
        result = _strip(source)
        assert isinstance(result, str), \
            f"{HELPER} must return a str for every str input; got {type(result)}"


# ---------------------------------------------------------------- behavior 2

def test_b2_shape_is_preserved_for_every_source_the_tokenizer_accepts():
    for source in ACCEPTED + (B3_SRC, B3_MULTILINE):
        assert _tokenizes(source), \
            f"fixture must be tokenizable to be in scope: {source!r}"
        result = _strip(source)
        assert len(result) == len(source), \
            f"length changed for {source!r}: {len(source)} -> {len(result)}"
        assert result.count("\n") == source.count("\n"), \
            f"newline COUNT changed for {source!r}"
        assert _newline_indexes(result) == _newline_indexes(source), \
            f"newline POSITIONS changed for {source!r}, so line/col no longer map"


def test_b2_a_column_computed_on_the_stripped_text_still_points_at_real_source():
    result = _strip(B3_SRC)
    index = result.index(B3_CODE_LINE)
    assert B3_SRC[index:index + len(B3_CODE_LINE)] == B3_CODE_LINE, \
        "an offset found in the stripped text must address the same raw bytes"


# ---------------------------------------------------------------- behavior 3

def test_b3_prose_is_blanked_to_spaces_while_code_stays_byte_identical():
    result = _strip(B3_SRC)
    raw_lines = B3_SRC.split("\n")
    out_lines = result.split("\n")

    matches = list(re.finditer(r"\b" + INCIDENT + r"\b", result))
    assert len(matches) == 1, \
        f"expected exactly one surviving {INCIDENT}; got {len(matches)}"

    line_start = len(raw_lines[0]) + 1 + len(raw_lines[1]) + 1
    code_end = line_start + len(B3_CODE_LINE)
    assert line_start <= matches[0].start() < code_end, \
        "the surviving numeral must lie inside the assert line's CODE span"

    assert out_lines[0] == raw_lines[0], "a pure code line is byte-identical"
    assert out_lines[1] == " " * len(raw_lines[1]), \
        f"the docstring line must be spaces only; got {out_lines[1]!r}"
    assert out_lines[2].startswith(B3_CODE_LINE), "the assert code survives"
    assert out_lines[2][len(B3_CODE_LINE):].strip() == "", \
        f"the comment span must be spaces only; got {out_lines[2]!r}"
    assert len(out_lines[2]) == len(raw_lines[2]), "the code line keeps its width"
    assert "x = 1" in result and B3_CODE_LINE in result, \
        "both code substrings survive verbatim"


def test_b3_a_multiline_triple_quoted_literal_is_blanked_on_every_line():
    result = _strip(B3_MULTILINE)
    raw_lines = B3_MULTILINE.split("\n")
    out_lines = result.split("\n")

    assert re.search(r"\b" + INCIDENT + r"\b", result) is None, \
        "no line of a multi-line literal may keep a numeral"
    assert _newline_indexes(result) == _newline_indexes(B3_MULTILINE), \
        "the literal's own newlines must survive at the same indexes"
    for index in (2, 3, 4):
        assert out_lines[index] == " " * len(raw_lines[index]), \
            f"line {index} of the literal must be spaces only: {out_lines[index]!r}"
    assert out_lines[0] == "a = 1" and out_lines[5] == "b = 2", \
        "code on both sides of the literal is byte-identical"
    assert out_lines[1].startswith("D = "), "the assignment's code survives"


# ---------------------------------------------------------------- behavior 4

def test_b4_an_fstring_literal_cannot_smuggle_a_numeral():
    source = 'y = f"count {n} of 199"\n'
    assert _tokenizes(source), "the f-string fixture must be tokenizable"
    result = _strip(source)
    assert re.search(r"\b199\b", result) is None, \
        f"an f-string's literal text must not survive stripping: {result!r}"


def test_b4_an_fstring_format_spec_cannot_smuggle_a_numeral_either():
    source = 'y = f"{n:>199}"\n'
    if not _tokenizes(source):
        pytest.skip("this runtime's tokenizer rejects the format-spec fixture")
    result = _strip(source)
    assert re.search(r"\b199\b", result) is None, \
        f"an f-string FORMAT SPEC must not survive stripping: {result!r}"


# ---------------------------------------------------------------- behavior 5

def test_b5_fail_closed_identity_on_source_the_tokenizer_rejects():
    for source in MALFORMED:
        assert not _tokenizes(source), \
            f"witness must actually raise on this runtime: {source!r}"
        result = _strip(source)
        assert result == source, (
            "an untokenisable source must come back UNCHANGED so a caller "
            f"can never see LESS than the raw text; {source!r} -> {result!r}")


def test_b5_a_searcher_over_the_stripped_result_can_never_see_less():
    for source in MALFORMED:
        needle = re.compile(r"\bdef\b")
        witness = source + "def "
        if _tokenizes(witness):
            continue
        assert bool(needle.search(_strip(witness))) == bool(needle.search(witness)), \
            "on rejected source the helper must not hide anything from a searcher"


# ---------------------------------------------------------------- behavior 6

def test_b6_the_brake_searches_the_stripped_source_and_not_the_raw_text():
    node, _source = _brake_function()

    stripped_names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Assign) and isinstance(child.value, ast.Call) \
                and _call_name(child.value) == HELPER:
            for target in child.targets:
                if isinstance(target, ast.Name):
                    stripped_names.add(target.id)
    assert stripped_names, \
        f"{BRAKE_TEST} must bind the result of {HELPER} before searching it"

    searches = [child for child in ast.walk(node)
                if isinstance(child, ast.Call) and _call_name(child) == "search"]
    assert searches, f"{BRAKE_TEST} must still search for the counters"
    for call in searches:
        assert len(call.args) >= 2, "a search needs a pattern and a subject"
        subject = call.args[1]
        assert isinstance(subject, ast.Name) and subject.id in stripped_names, \
            "every search in the brake must run over the STRIPPED source"


def test_b6_the_brake_still_asserts_one_none_result_per_counter():
    node, _source = _brake_function()

    is_none_asserts = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Assert):
            continue
        test = child.test
        if isinstance(test, ast.Compare) and len(test.ops) == 1 \
                and isinstance(test.ops[0], ast.Is) \
                and isinstance(test.comparators[0], ast.Constant) \
                and test.comparators[0].value is None:
            is_none_asserts.append(child)
    assert is_none_asserts, \
        f"{BRAKE_TEST} must keep its `assert re.search(...) is None` shape"
    assert all(node_.msg is not None for node_ in is_none_asserts), \
        "each counter's assertion must carry its own message"

    loops = [child for child in ast.walk(node) if isinstance(child, ast.For)]
    assert loops, "the two counters must still be walked in one loop"
    pairs = [loop for loop in loops
             if isinstance(loop.iter, ast.Tuple) and len(loop.iter.elts) == 2]
    assert pairs, "the brake must still iterate exactly TWO (label, count) pairs"


def test_b6_the_disarm_is_measured_over_the_live_brake_file():
    population = _population_or_skip()
    tests_count = _tests_py_count()
    assert tests_count, "the tests directory must hold at least one module"

    raw = _brake_source()
    stripped = _strip(raw)
    assert stripped != raw, "the live brake file must contain SOME prose to blank"

    raw_integers = {int(match) for match in DIGITS.findall(raw)}
    stripped_integers = {int(match) for match in DIGITS.findall(stripped)}
    assert stripped_integers, \
        "sanity: the brake's CODE still carries integers, so this is not vacuous"
    assert stripped_integers <= raw_integers, \
        "stripping may only REMOVE integers, never invent one"

    ceiling = min(len(population), tests_count)
    survivors = sorted(value for value in stripped_integers if value >= ceiling)
    assert not survivors, (
        "every integer left in the brake's CODE must be below BOTH live counters, "
        f"or a future count can match it again; offenders: {survivors}")

    armed = sorted(value for value in raw_integers if value >= tests_count)
    assert armed, (
        "the RAW source must still spell an integer a future count can reach, "
        "otherwise this measurement proves nothing about the stripping")
    assert set(armed) - stripped_integers == set(armed), \
        "every such integer must have been blanked out of the searched text"


# ---------------------------------------------------------------- behavior 7

def test_b7_an_ambient_count_pin_written_in_code_still_reds_the_brake():
    source = ('"""A docstring naming ' + SYNTH + ' files."""\n'
              "paths = []\n"
              "assert len(paths) == " + SYNTH + "  # " + SYNTH + " again\n")
    assert _tokenizes(source), "the armed fixture must be tokenizable"
    result = _strip(source)
    matches = re.findall(r"\b" + SYNTH + r"\b", result)
    assert len(matches) == 1, (
        "a real ambient-count pin lives in CODE and must SURVIVE stripping, so "
        f"the narrowed brake still fires; matches={len(matches)}")


def test_b7_the_same_numeral_in_prose_alone_does_not_arm_the_brake():
    source = ('"""A docstring naming ' + SYNTH + ' files."""\n'
              "# and a comment naming " + SYNTH + " too\n"
              "assert len(paths) == 7\n")
    assert _tokenizes(source), "the disarmed fixture must be tokenizable"
    result = _strip(source)
    assert re.search(r"\b" + SYNTH + r"\b", result) is None, (
        "prose alone must NOT arm the brake -- that coincidence reverted a whole "
        f"behavior-complete iteration once; got {result!r}")
    assert "assert len(paths) == 7" in result, "the code of the fixture survives"


# ---------------------------------------------------------------- behavior 8

def test_b8_the_relanded_feature_symbols_are_back_on_the_module():
    prefix = getattr(foundry, DRIFT_PREFIX_NAME, None)
    assert prefix == "test-touch:", \
        f"foundry.{DRIFT_PREFIX_NAME} must be the re-landed sentinel prefix"
    drift = getattr(foundry, DRIFT_LINE, None)
    assert callable(drift), f"foundry.{DRIFT_LINE} must be a module-level callable"
    assert getattr(drift, "__module__", None) == "foundry", \
        f"{DRIFT_LINE} must be defined in foundry"


def test_b8_the_relanded_behavior_module_is_present_and_whole():
    assert RELAND_MODULE.is_file(), \
        f"{RELAND_MODULE.name} must be back in the tree after the re-land"
    source = RELAND_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    tests = [node.name for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")]
    assert tests, f"{RELAND_MODULE.name} must still define behavior tests"
    assert ast.get_docstring(tree), \
        f"{RELAND_MODULE.name} must keep its module docstring"


def test_b8_the_count_word_advance_is_back_in_both_prose_surfaces():
    assert DRIFT_PHRASE.search(README.read_text(encoding="utf-8")), \
        "README.md must name the advanced drift-line count again"
    doc = foundry.run_doctor_cli.__doc__ or ""
    assert DRIFT_PHRASE.search(doc), \
        "run_doctor_cli.__doc__ must name the advanced drift-line count again"


def test_b8_every_path_of_the_preserved_patch_is_present_in_the_tree():
    missing = [name for name in RELANDED_PATHS if not (_ROOT / name).is_file()]
    assert not missing, f"the re-land left paths absent from the tree: {missing}"
    empty = [name for name in RELANDED_PATHS
             if (_ROOT / name).stat().st_size == 0]
    assert not empty, f"the re-land left EMPTY files in the tree: {empty}"


# ------------------------------------------------- acceptance criteria A, B, C

def test_ac_a_both_roadmap_records_land_in_this_same_diff():
    gaps = foundry.roadmap_ledger_gaps(
        ROADMAP.read_text(encoding="utf-8"),
        ARCHIVE.read_text(encoding="utf-8"),
        (RELAND_ITER, THIS_ITER))
    assert gaps == [], \
        f"iteration(s) recorded in NEITHER roadmap file: {gaps}"


def test_ac_a_this_iterations_ledger_row_is_one_line_within_the_width_budget():
    rows = [line for line in ROADMAP.read_text(encoding="utf-8").splitlines()
            if line.startswith(f"- iter {THIS_ITER} ")]
    assert len(rows) == 1, f"expected exactly one iter-{THIS_ITER} ledger row"
    assert len(rows[0]) <= 120, f"the ledger row is {len(rows[0])} chars (max 120)"
    bullets = [line for line in ARCHIVE.read_text(encoding="utf-8").splitlines()
               if line.startswith(f"- **iter {THIS_ITER} ")]
    assert len(bullets) == 1, f"expected exactly one iter-{THIS_ITER} archive bullet"


def test_ac_b_this_module_is_on_the_b15_allow_list():
    needle = f'"tests/{pathlib.Path(__file__).name}"'
    text = ALLOW_LIST_MODULE.read_text(encoding="utf-8")
    assert needle in text, (
        f"{needle} must be allow-listed in {ALLOW_LIST_MODULE.name}, or the "
        "literal-class brake reds inside the gate's staging window")


def test_ac_c_both_top_level_modules_import_in_process():
    assert foundry.__name__ == "foundry"
    assert dispatcher.__name__ == "dispatcher"
    assert callable(getattr(foundry, "main", None)), \
        "foundry must keep its public entry point"


# ------------------------------------------------ behaviors 5, 6, 8 (retry round)
# Added by the retry round of this iteration. The first round left the module
# green but with three checks whose absence let a behavior pass for a weaker
# reason than the spec states; each addition below closes exactly one of those.


def test_b5_the_searcher_guarantee_is_exercised_by_every_witness():
    """Non-vacuity guard for the sibling searcher check.

    ``test_b5_a_searcher_over_the_stripped_result_can_never_see_less`` skips a
    witness whose ``+ "def "`` suffix happens to make the source tokenizable, so
    on some future runtime all three witnesses could skip and the guarantee would
    be asserted zero times while the test still reported green. This pins how
    many witnesses actually reach the assertion.
    """
    exercised = [source for source in MALFORMED
                 if not _tokenizes(source + "def ")]
    assert len(exercised) == len(MALFORMED), (
        "every malformed witness must stay untokenizable once a searchable "
        "needle is appended, otherwise the searcher guarantee is asserted on "
        f"fewer than all witnesses; exercised {len(exercised)} of "
        f"{len(MALFORMED)}")


def test_b6_each_counter_assertion_reports_its_own_label_and_count():
    """The spec asks for one message PER COUNTER naming the label and count.

    The sibling check only proves a message exists. A single shared literal
    message would satisfy that while leaving a red unable to say WHICH counter
    matched -- exactly the diagnosis cost that made the original coincidence
    expensive to read.
    """
    node, _source = _brake_function()

    pair_loops = [child for child in ast.walk(node)
                  if isinstance(child, ast.For)
                  and isinstance(child.iter, ast.Tuple)
                  and len(child.iter.elts) == 2]
    assert pair_loops, "the brake must still walk two (label, count) pairs"
    bound = set()
    for loop in pair_loops:
        for child in ast.walk(loop.target):
            if isinstance(child, ast.Name):
                bound.add(child.id)
    assert len(bound) >= 2, (
        "the loop must bind a LABEL and a COUNT separately, so a failure can "
        f"name both; bound {sorted(bound)}")

    messages = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Assert) or child.msg is None:
            continue
        test = child.test
        if isinstance(test, ast.Compare) and len(test.ops) == 1 \
                and isinstance(test.ops[0], ast.Is) \
                and isinstance(test.comparators[0], ast.Constant) \
                and test.comparators[0].value is None:
            messages.append(child.msg)
    assert messages, "the brake must keep a message on each `is None` assertion"
    for message in messages:
        referenced = {child.id for child in ast.walk(message)
                      if isinstance(child, ast.Name)}
        assert bound <= referenced, (
            "each counter's failure message must interpolate the label AND the "
            f"count it measured; loop binds {sorted(bound)}, message names "
            f"{sorted(referenced)}")


def test_b8_the_relanded_behavior_module_loads_by_path_and_exposes_its_tests():
    """Behavior 8 asks that EVERY test in the re-landed module passes.

    Running pytest inside pytest is not worth its cost here (the ambient suite
    already collects that module), but a file that parses can still be an
    unimportable stub, which would make the ambient collection ERROR rather than
    run it. Loading it by path -- registered in ``sys.modules`` first, the
    convention ``tests/test_iter219_behavior.py`` established -- proves it is
    importable in isolation and that its tests are real callables.
    """
    import importlib.util

    if not RELAND_MODULE.is_file():
        pytest.fail(f"{RELAND_MODULE.name} is absent, so the re-land is not whole")
    spec = importlib.util.spec_from_file_location(
        f"_iter{THIS_ITER}_reland_probe", RELAND_MODULE)
    assert spec is not None and spec.loader is not None, \
        f"{RELAND_MODULE.name} is not loadable as a module"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        callables = sorted(name for name in dir(module)
                           if name.startswith("test_")
                           and callable(getattr(module, name)))
    finally:
        sys.modules.pop(spec.name, None)
    assert callables, (
        f"{RELAND_MODULE.name} imports but exposes no runnable test callable, "
        "so the re-land landed a stub rather than the reverted work")
