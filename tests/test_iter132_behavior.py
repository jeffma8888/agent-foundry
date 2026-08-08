"""Black-box behaviour tests for iter 132 -- the every-suite control-path freeze
guards policed by tests/test_control_path_freeze_scope.py are now selected by guard
BEHAVIOR (an argv-element "git diff --quiet HEAD --" pathspec) instead of by the one
literal function name GUARD_NAME, which closes a fail-open detector.

Spec: products/_platform/state/iter-132/pm.md, Expected Behaviors 1-8.

  1. element-form selection: every token standalone; a substring does not count
  2. mention is not invocation (precision) -- prose is one long constant
  3. total on bad input: broken source, empty source, empty dir, unparsable
     neighbour file
  4. known-bad IS reported, planted under a name that is NOT GUARD_NAME, which is
     what proves the fail-open is closed
  5. known-good is NOT reported, so behavior 4 cannot pass by flagging everything
  6. non-vacuity floor on the live tree, and the floor assertion actually FIRES
  7. strict superset of the old exact-name population (12 of 26; none lost)
  8. both original assertions still hold over the wider population, and each
     failure message names the offending file
  Plus Acceptance-Criteria oracles: the three original test functions survive by
  name, the decided public surface exists, the module docstring keeps the
  iter-83/84/85 regression history and states the new rule plus the residual holes,
  import safety in a fresh interpreter, and the two PM roadmap records.

ISOLATION CONTRACT (HONORED): written from the iter-132 PM spec and from the
OBSERVABLE surface of the module under test -- importing it, CALLING its public
functions and its three test functions, and reading __doc__ -- plus the roadmap
files the spec names as deliverables. The engineer's notes, the reviewer's notes and
git diff were NOT read. The pre-132 selector used as the fail-open and superset
oracle is re-derived here by an INDEPENDENT AST scan for the literal GUARD_NAME,
which is the whole of the old rule as stated in the spec's Feature section.

Offline and deterministic: every synthesized module source is a single
triple-quoted blob, every planted sample lives under tmp_path, and nothing in the
product tree is mutated. No network, no git, no agent run.

NOTE ON SHAPE: each synthesized sample is ONE string constant on purpose. Spelled
as separate token literals inside a test function, the new selector would select
THIS file's own tests as freeze guards, and the live-tree assertions would then
demand that they freeze the control path -- a red suite manufactured out of healthy
tests. That hazard is itself Behavior 2 working as specified.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

_TESTS_DIR = pathlib.Path(__file__).resolve().parent
_ROOT = _TESTS_DIR.parent
sys.path.insert(0, str(_TESTS_DIR))
import test_control_path_freeze_scope as scope  # noqa: E402

# The argv tokens, spelled as ONE constant then split -- see NOTE ON SHAPE above.
_TOKENS = tuple("git diff --quiet HEAD --".split())
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

# ---------------------------------------------------------------------------
# Synthesized sample modules (single blobs; planted only under tmp_path)
# ---------------------------------------------------------------------------

GOOD_GUARD_SRC = '''\
import subprocess


def test_b13_control_path_byte_unchanged():
    """A narrow, legitimate every-suite freeze guard."""
    proc = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py", "scripts/"],
        capture_output=True,
    )
    assert proc.returncode == 0, "the control path changed"
'''

BAD_GUARD_SRC = '''\
import subprocess


def test_b99_docs_and_roles_byte_unchanged():
    """The iter-83/84 anti-pattern, planted under a NON-policed name."""
    proc = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--",
         "dispatcher.py", "README.md", "roles/"],
        capture_output=True,
    )
    assert proc.returncode == 0
'''

HOLLOW_GUARD_SRC = '''\
import subprocess


def test_b98_narrowed_until_hollow_byte_unchanged():
    """Selected, but it no longer covers the real control path."""
    proc = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "scripts/"],
        capture_output=True,
    )
    assert proc.returncode == 0
'''

MENTION_ONLY_SRC = '''\
def test_documents_the_command_without_running_it():
    """We deliberately do not run git diff --quiet HEAD -- dispatcher.py here."""
    assert True
'''

SUBSTRING_ONLY_SRC = '''\
import subprocess


def test_tokens_appear_only_as_substrings():
    argv = ["git diff", "--quiet HEAD", "--", "dispatcher.py"]
    subprocess.run(argv)
'''

TWO_GUARDS_SRC = '''\
import subprocess


def test_zz_declared_first_byte_unchanged():
    subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py"])


async def test_aa_declared_second_byte_unchanged():
    subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py"])
'''


def _plant(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def _names_matching_the_old_rule(source):
    """The PRE-132 selector, re-derived from the spec's Feature section: a guard was
    any function whose NAME is literally GUARD_NAME. Used only as an oracle."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    return [node.name for node in ast.walk(tree)
            if isinstance(node, _FUNCTION_NODES) and node.name == scope.GUARD_NAME]


def _old_population():
    """(file name, guard name) pairs the old rule policed on the LIVE tree."""
    pairs = set()
    for path in sorted(_TESTS_DIR.glob("test_*.py")):
        for name in _names_matching_the_old_rule(path.read_text(encoding="utf-8")):
            pairs.add((path.name, name))
    return pairs


# ---------------------------------------------------------------------------
# Behavior 1 -- element-form selection
# ---------------------------------------------------------------------------

def test_b1_element_form_selects_a_real_guard():
    assert scope.guard_names_in_source(GOOD_GUARD_SRC) == [
        "test_b13_control_path_byte_unchanged"]


def test_b1_a_token_present_only_as_a_substring_does_not_count():
    assert scope.guard_names_in_source(SUBSTRING_ONLY_SRC) == []


def test_b1_both_function_flavours_selected_in_source_text_order():
    assert scope.guard_names_in_source(TWO_GUARDS_SRC) == [
        "test_zz_declared_first_byte_unchanged",
        "test_aa_declared_second_byte_unchanged",
    ]


def test_b1_the_token_set_is_the_documented_argv_shape():
    assert tuple(scope.GIT_DIFF_TOKENS) == _TOKENS


# ---------------------------------------------------------------------------
# Behavior 2 -- mention is not invocation
# ---------------------------------------------------------------------------

def test_b2_mention_is_not_invocation():
    assert scope.guard_names_in_source(MENTION_ONLY_SRC) == []


def test_b2_a_mention_only_module_is_never_forced_to_freeze_the_control_path(tmp_path):
    """Precision has teeth: a selected prose-only test would be reported hollow."""
    _plant(tmp_path, "test_planted_mention.py", MENTION_ONLY_SRC)
    assert scope.freeze_guards(tmp_path) == []
    assert scope.hollow_guards(tmp_path) == []
    assert scope.forbidden_freezes(tmp_path) == []


# ---------------------------------------------------------------------------
# Behavior 3 -- total on bad input
# ---------------------------------------------------------------------------

def test_b3_broken_and_empty_source_yield_no_guards_and_raise_nothing():
    assert scope.guard_names_in_source("def broken(:\n") == []
    assert scope.guard_names_in_source("") == []
    assert scope.guard_names_in_source("\x00") == []
    assert scope.guard_names_in_source("   \n\n") == []


def test_b3_empty_directory_yields_no_guards(tmp_path):
    assert scope.freeze_guards(tmp_path) == []
    assert scope.forbidden_freezes(tmp_path) == []
    assert scope.hollow_guards(tmp_path) == []


def test_b3_one_unparsable_file_does_not_mask_the_rest(tmp_path):
    _plant(tmp_path, "test_planted_broken.py", "def broken(:\n")
    _plant(tmp_path, "test_planted_good.py", GOOD_GUARD_SRC)
    assert [name for _, name in scope.freeze_guards(tmp_path)] == [
        "test_b13_control_path_byte_unchanged"]


def test_b3_non_test_files_in_the_directory_are_not_scanned(tmp_path):
    _plant(tmp_path, "helper_not_a_test.py", GOOD_GUARD_SRC)
    assert scope.freeze_guards(tmp_path) == []


# ---------------------------------------------------------------------------
# Behavior 4 -- known-bad is reported (the fail-open is closed)
# ---------------------------------------------------------------------------

def test_b4_known_bad_guard_is_reported_with_file_and_forbidden_path(tmp_path):
    _plant(tmp_path, "test_planted_bad.py", BAD_GUARD_SRC)
    offenders = scope.forbidden_freezes(tmp_path)
    assert len(offenders) == 2, offenders
    blob = " | ".join(offenders)
    assert "test_planted_bad.py" in blob
    for bad in scope.FORBIDDEN:
        assert bad in blob, (bad, blob)
    assert [name for _, name in scope.freeze_guards(tmp_path)] == [
        "test_b99_docs_and_roles_byte_unchanged"]


def test_b4_the_planted_guard_is_invisible_to_the_old_name_only_selector():
    assert scope.guard_names_in_source(BAD_GUARD_SRC) == [
        "test_b99_docs_and_roles_byte_unchanged"]
    assert _names_matching_the_old_rule(BAD_GUARD_SRC) == []
    assert "test_b99_docs_and_roles_byte_unchanged" != scope.GUARD_NAME


def test_b4_the_meta_test_itself_goes_red_on_a_planted_known_bad_guard(
        tmp_path, monkeypatch):
    _plant(tmp_path, "test_planted_bad.py", BAD_GUARD_SRC)
    monkeypatch.setattr(scope, "TESTS_DIR", tmp_path)
    monkeypatch.setattr(scope, "EXPECTED_MIN_GUARD_COUNT", 1)
    # Non-vacuity FIRST: prove the scan really moved and really found the guard,
    # otherwise the failure below could be an empty scan failing for its own reason.
    scope.test_the_guard_still_exists_somewhere()
    with pytest.raises(AssertionError) as excinfo:
        scope.test_control_path_guards_do_not_freeze_docs_or_roles()
    message = str(excinfo.value)
    assert "test_planted_bad.py" in message
    for bad in scope.FORBIDDEN:
        assert bad in message, (bad, message)


# ---------------------------------------------------------------------------
# Behavior 5 -- known-good is not reported
# ---------------------------------------------------------------------------

def test_b5_known_good_guard_is_selected_but_not_reported(tmp_path):
    _plant(tmp_path, "test_planted_good.py", GOOD_GUARD_SRC)
    assert len(scope.freeze_guards(tmp_path)) == 1
    assert scope.forbidden_freezes(tmp_path) == []
    assert scope.hollow_guards(tmp_path) == []


def test_b5_all_three_meta_tests_pass_over_a_clean_planted_guard(
        tmp_path, monkeypatch):
    _plant(tmp_path, "test_planted_good.py", GOOD_GUARD_SRC)
    monkeypatch.setattr(scope, "TESTS_DIR", tmp_path)
    monkeypatch.setattr(scope, "EXPECTED_MIN_GUARD_COUNT", 1)
    scope.test_the_guard_still_exists_somewhere()
    scope.test_control_path_guards_do_not_freeze_docs_or_roles()
    scope.test_control_path_guards_still_cover_the_real_control_path()


# ---------------------------------------------------------------------------
# Behavior 6 -- non-vacuity floor, and it fires
# ---------------------------------------------------------------------------

def test_b6_live_population_clears_the_non_vacuity_floor():
    guards = scope.freeze_guards()
    assert scope.EXPECTED_MIN_GUARD_COUNT >= 26, scope.EXPECTED_MIN_GUARD_COUNT
    assert len(guards) >= scope.EXPECTED_MIN_GUARD_COUNT, (
        "measured %d behavior-selected guards on the live tree" % len(guards))


def test_b6_the_scan_root_is_redirectable(tmp_path, monkeypatch):
    """The seam that makes behaviors 1-5 provable at all: re-pointing TESTS_DIR must
    move the DEFAULT scan too, or every offline probe passes vacuously over an
    empty tree -- exactly the fail-open class this module exists to catch."""
    _plant(tmp_path, "test_planted_good.py", GOOD_GUARD_SRC)
    monkeypatch.setattr(scope, "TESTS_DIR", tmp_path)
    assert [name for _, name in scope.freeze_guards()] == [
        "test_b13_control_path_byte_unchanged"]


def test_b6_the_floor_actually_fires_when_the_population_shrinks(
        tmp_path, monkeypatch):
    monkeypatch.setattr(scope, "TESTS_DIR", tmp_path)  # empty directory
    with pytest.raises(AssertionError) as excinfo:
        scope.test_the_guard_still_exists_somewhere()
    message = str(excinfo.value)
    assert "found 0" in message, message
    assert str(scope.EXPECTED_MIN_GUARD_COUNT) in message, message
    assert "freeze_guards" in message, message


# ---------------------------------------------------------------------------
# Behavior 7 -- strict superset of the old population
# ---------------------------------------------------------------------------

def test_b7_new_population_is_a_strict_superset_of_the_old_one():
    guards = scope.freeze_guards()
    new_pairs = {(path.name, name) for path, name in guards}
    assert len(new_pairs) == len(guards), "guard pairs must be unique"
    old_pairs = _old_population()
    assert len(old_pairs) == 12, sorted(old_pairs)
    assert old_pairs < new_pairs, sorted(old_pairs - new_pairs)
    assert len(new_pairs - old_pairs) >= 14, len(new_pairs - old_pairs)


def test_b7_every_old_guard_is_still_policed_by_name_and_file():
    policed = {(path.name, name) for path, name in scope.freeze_guards()}
    for pair in _old_population():
        assert pair in policed, pair


# ---------------------------------------------------------------------------
# Behavior 8 -- both original assertions hold over the wider population
# ---------------------------------------------------------------------------

def test_b8_original_assertions_hold_over_the_wider_live_population():
    assert scope.forbidden_freezes() == []
    assert scope.hollow_guards() == []
    scope.test_control_path_guards_do_not_freeze_docs_or_roles()
    scope.test_control_path_guards_still_cover_the_real_control_path()


def test_b8_a_hollowed_guard_is_named_in_the_failure_message(
        tmp_path, monkeypatch):
    _plant(tmp_path, "test_planted_hollow.py", HOLLOW_GUARD_SRC)
    monkeypatch.setattr(scope, "TESTS_DIR", tmp_path)
    monkeypatch.setattr(scope, "EXPECTED_MIN_GUARD_COUNT", 1)
    scope.test_the_guard_still_exists_somewhere()          # non-vacuity
    scope.test_control_path_guards_do_not_freeze_docs_or_roles()  # clean on FORBIDDEN
    hollow = scope.hollow_guards()
    assert len(hollow) == 1, hollow
    assert "test_planted_hollow.py" in hollow[0]
    assert scope.CONTROL_PATH_FILE in hollow[0]
    with pytest.raises(AssertionError) as excinfo:
        scope.test_control_path_guards_still_cover_the_real_control_path()
    assert "test_planted_hollow.py" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Acceptance-Criteria oracles
# ---------------------------------------------------------------------------

def test_ac_the_three_original_test_functions_survive_by_name():
    for name in ("test_the_guard_still_exists_somewhere",
                 "test_control_path_guards_do_not_freeze_docs_or_roles",
                 "test_control_path_guards_still_cover_the_real_control_path"):
        assert callable(getattr(scope, name, None)), name


def test_ac_the_decided_public_surface_exists_and_keeps_its_meaning():
    for name in ("GUARD_NAME", "FORBIDDEN", "CONTROL_PATH_FILE", "GIT_DIFF_TOKENS",
                 "EXPECTED_MIN_GUARD_COUNT", "is_freeze_guard",
                 "guard_names_in_source", "freeze_guards", "forbidden_freezes",
                 "hollow_guards"):
        assert hasattr(scope, name), name
    assert scope.GUARD_NAME == "test_ac_control_path_byte_unchanged"
    assert tuple(scope.FORBIDDEN) == ("README.md", "roles/")
    assert scope.CONTROL_PATH_FILE == "dispatcher.py"


def test_ac_is_freeze_guard_decides_a_single_function_node():
    good = ast.parse(GOOD_GUARD_SRC).body[-1]
    mention = ast.parse(MENTION_ONLY_SRC).body[-1]
    assert scope.is_freeze_guard(good) is True
    assert scope.is_freeze_guard(mention) is False


def test_ac_module_docstring_keeps_the_history_and_states_the_new_rule():
    doc = scope.__doc__ or ""
    for marker in ("iter-83", "iter-84", "iter-85"):
        assert marker in doc, marker
    assert "GIT_DIFF_TOKENS" in doc
    low = doc.lower()
    assert "standalone" in low
    assert "residual" in low
    assert "iter-132" in low


def test_ac_imports_still_succeed_in_a_fresh_interpreter():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_ac_roadmap_records_for_this_iteration_exist():
    index = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    archive = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text(encoding="utf-8")
    assert "- iter 132 " in index
    assert "- **iter 132 " in archive


def test_ac_this_file_is_not_itself_selected_as_a_freeze_guard():
    """A test file that spelled the tokens as separate literals would be selected,
    and then the live hollow-guard assertion would demand it freeze the control
    path. Assert the shape rule on THIS file so the trap cannot be reintroduced."""
    own = pathlib.Path(__file__).resolve()
    assert scope.guard_names_in_source(own.read_text(encoding="utf-8")) == []
    assert own.name not in {path.name for path, _ in scope.freeze_guards()}
