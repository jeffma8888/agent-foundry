"""Iteration 375 -- BLACK-BOX behavior tests for the b15 allow-list narrowing.

Spec under test: `products/_platform/state/iter-375/pm.md` --
"`test_b15_only_the_three_expected_test_files_differ_from_head` measures only test files
that exist at HEAD, so a brand-new behavior test no longer needs a hand-added allow-list
row."

  1.  `swept_test_paths` is a module-level PURE function over `--name-status` text:
      status `A` is DROPPED, `M` and `D` are KEPT.
  2.  It tolerates the real porcelain -- blank and whitespace-only lines, a tab-less
      line, a multi-field line (the LAST field is the path), a padded path, empty text
      -- and never raises for any string input.
  3.  b15 sources its `changed` set from that function over
      `--name-status --no-renames`, no longer calls `--name-only`, keeps its
      `pytest.skip` when git is unavailable, and still asserts `changed <= expected`
      with the SAME failure wording.
  4.  The deletion is provably inert: every retired candidate row is tracked at HEAD and
      is NOT `M`/`D` in the shipping tree, and no row with a LIVE sibling witness was
      retired.
  5.  The `f"tests/test_iter{THIS_ITER}_behavior.py"` row is RETAINED, and `THIS_ITER`
      stays frozen.
  6.  Staging-window green: with the tree staged into a THROWAWAY index copy the brake
      PASSES, with this very file staged as `A` and absent from `expected`; the real
      index's staged `tests/` content is unchanged by the measurement.
  7.  Positive control, two-sided: a synthetic `M` sweep of a path outside `expected`
      still REDS b15 with its own wording, and the same path as `A` does not.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-375 PM
spec, the pre-existing conventions under `tests/`, and the product's OWN observable
behavior by importing and CALLING public names that live under `tests/` -- the one tree
the contract grants in full.  This author did NOT read `foundry.py` / `dispatcher.py`
implementation source, the engineer's notes, the reviewer's notes,
`IMPLEMENTATION.patch`, or any `git diff` CONTENT: behaviors 4 and 6 run
`git diff HEAD --name-status --no-renames -- tests/`, which is the brake's own measured
input, is pathspec-restricted to `tests/`, and reports STATUS LETTERS AND PATHS only.
"""
from __future__ import annotations

import ast
import importlib
import os
import pathlib
import re
import shutil
import subprocess
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS_DIR = _ROOT / "tests"
OWNER_NAME = "test_iter204_behavior.py"
OWNER = TESTS_DIR / OWNER_NAME
SELF_NAME = pathlib.Path(__file__).name
B15 = "test_b15_only_the_three_expected_test_files_differ_from_head"
FAILURE_WORDING = "must NOT be swept; unexpected:"
_REL_PATH_RE = re.compile(r"tests/test_iter\d+_behavior\.py")

# The candidate population the spec MEASURED as existing for one reason only -- that
# `--name-only` cannot tell an addition from an edit (spec `## Why`).
CANDIDATE_ITERS = (226, 227, 229, 230, 231, 232, 323,
                   325, 335, 336, 338, 371, 372, 373)
CANDIDATE_PATHS = tuple(f"tests/test_iter{n}_behavior.py" for n in CANDIDATE_ITERS)

# Behavior 7's control: a path the spec verified is absent from `expected` (its premise
# is re-measured in the control test itself, never assumed).
CONTROL_PATH = "tests/test_iter124_behavior.py"

_brake = importlib.import_module("test_iter204_behavior")


# ---------------------------------------------------------------------------
# helpers -- all offline except the two git readers, which are STATUS-ONLY
# ---------------------------------------------------------------------------
class _Explode:
    """Any attribute access is an impurity report."""

    def __init__(self, label):
        self._label = label

    def __getattr__(self, name):
        raise AssertionError(
            f"swept_test_paths must be PURE; it reached for {self._label}.{name}")


def _git(*args, env=None):
    return subprocess.run(["git", *args], cwd=str(_ROOT),
                          capture_output=True, text=True, env=env)


def _git_available():
    return _git("rev-parse", "--git-dir").returncode == 0


def _b15_node():
    tree = ast.parse(OWNER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == B15:
            return node
    raise AssertionError(f"{B15} must still exist in {OWNER_NAME}")


def _b15_source():
    return ast.get_source_segment(OWNER.read_text(encoding="utf-8"), _b15_node()) or ""


def _expected_rows():
    """(string rows, unparsed non-string rows, total row count) of b15's `expected` set."""
    for node in ast.walk(_b15_node()):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "expected"):
            assert isinstance(node.value, ast.Set), \
                "`expected` must still be a SET literal the brake compares against"
            lits, other = set(), []
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    lits.add(elt.value)
                else:
                    other.append(ast.unparse(elt))
            return frozenset(lits), tuple(other), len(node.value.elts)
    raise AssertionError("b15 must still build an `expected` set literal")


def _resolved_expected():
    """`expected` with the one f-string row resolved through the frozen `THIS_ITER`."""
    lits, _, _ = _expected_rows()
    return lits | {f"tests/test_iter{_brake.THIS_ITER}_behavior.py"}


def _status_map(name_status_text):
    out = {}
    for line in name_status_text.splitlines():
        if "\t" not in line:
            continue
        fields = line.split("\t")
        out[fields[-1].strip()] = fields[0].strip()
    return out


def witness_claims(source_by_name, owner_name):
    """PURE oracle: {module name: sorted paths that module ASSERTS are allow-listed}.

    A witness is a sibling module that names `owner_name` and defines a `test_*`
    function with `allow_list` in its NAME.  What it claims is its OWN relative path
    (the "this module is on the allow-list" shape) plus every
    `tests/test_iterNN_behavior.py` literal inside such a function or its decorators
    (the parametrized "these forced paths are on the allow-list" shape).  Text in,
    dict out: no filesystem, git, network or clock.
    """
    claims = {}
    for name in sorted(source_by_name):
        if name == owner_name:
            continue
        text = source_by_name[name]
        if owner_name not in text:
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        witnesses = [fn for fn in ast.walk(tree)
                     if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and fn.name.startswith("test_") and "allow_list" in fn.name]
        if not witnesses:
            continue
        claimed = {"tests/" + name}
        for fn in witnesses:
            segment = ast.get_source_segment(text, fn) or ""
            for decorator in fn.decorator_list:
                segment += "\n" + ast.unparse(decorator)
            claimed |= set(_REL_PATH_RE.findall(segment))
        claims[name] = sorted(claimed)
    return claims


def dangling_witness_rows(source_by_name, owner_name, allow_listed):
    """PURE: every claimed path that `allow_listed` does not contain.

    A row another shipped module asserts the PRESENCE of is load-bearing however inert
    the brake itself finds it -- retiring it without retiring the witness reds that
    module.
    """
    return tuple(sorted({path
                         for claimed in witness_claims(source_by_name, owner_name).values()
                         for path in claimed
                         if path not in allow_listed}))


def _parses(text):
    try:
        ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    return True


def _live_sibling_sources():
    return {p.name: p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(TESTS_DIR.glob("test_iter*_behavior.py"))
            if p.name != SELF_NAME}


# ==========================================================================
# Behavior 1 -- a module-level PURE function that drops status `A`
# ==========================================================================
def test_b1_swept_test_paths_drops_added_and_keeps_modified_and_deleted():
    text = "M\ttests/a.py\nA\ttests/b.py\nD\ttests/c.py"
    assert _brake.swept_test_paths(text) == {"tests/a.py", "tests/c.py"}, \
        "status A must be DROPPED while M and D are KEPT"


def test_b1_the_function_is_module_level_and_returns_a_set():
    fn = getattr(_brake, "swept_test_paths", None)
    assert isinstance(fn, types.FunctionType), \
        "swept_test_paths must be a module-level function of the brake's own module"
    assert isinstance(fn(""), set), "it must return a set"


def test_b1_the_function_is_pure_with_every_io_global_exploded(monkeypatch):
    for name in ("subprocess", "os", "pathlib", "shutil", "importlib", "socket",
                 "time", "random", "urllib", "sys"):
        if hasattr(_brake, name):
            monkeypatch.setattr(_brake, name, _Explode(name))
    assert _brake.swept_test_paths("M\ttests/a.py\nA\ttests/b.py") == {"tests/a.py"}, \
        "the function must decide from TEXT alone"


def test_b1_the_functions_own_body_references_no_io_symbol():
    """Static half of purity: the CODE (not the prose) names no effectful symbol."""
    tree = ast.parse(OWNER.read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "swept_test_paths"), None)
    assert fn is not None, "swept_test_paths must exist as a def in the owner module"
    banned = {"subprocess", "os", "pathlib", "shutil", "socket", "time", "random",
              "urllib", "sys", "open", "Path", "input", "eval", "exec"}
    hits = sorted({n.id for n in ast.walk(fn)
                   if isinstance(n, ast.Name) and n.id in banned})
    assert hits == [], f"a PURE parser must not reference {hits}"


# ==========================================================================
# Behavior 2 -- it tolerates the real porcelain and never raises
# ==========================================================================
@pytest.mark.parametrize("text,want", [
    ("", set()),
    ("\n\n", set()),
    ("   \n\t \n", set()),
    ("tests/no_tab.py", set()),
    ("M\ttests/pad.py", {"tests/pad.py"}),
    ("M\t  tests/pad.py  ", {"tests/pad.py"}),
    ("M\ttests/old.py\ttests/new.py", {"tests/new.py"}),
    ("A\ttests/added.py\n\nM\ttests/edited.py\n", {"tests/edited.py"}),
    ("D\ttests/gone.py", {"tests/gone.py"}),
    ("M\t", set()),
])
def test_b2_porcelain_tolerance(text, want):
    assert _brake.swept_test_paths(text) == want


@pytest.mark.parametrize("hostile", [
    "", "\n", "\t", "\t\t\t", "A", "M", "M\t\t", "\x00", "M\t\x00",
    "M\ttests/a.py\r", "?? tests/untracked.py", "100\t0\ttests/numstat.py",
    "M" * 4000, "\t".join(["x"] * 50), "\N{SNOWMAN}\ttests/unicode.py",
])
def test_b2_total_never_raises_for_any_string(hostile):
    out = _brake.swept_test_paths(hostile)
    assert isinstance(out, set)


def test_b2_a_trailing_carriage_return_is_stripped_from_the_path():
    assert _brake.swept_test_paths("M\ttests/a.py\r") == {"tests/a.py"}


# ==========================================================================
# Behavior 3 -- b15 composes through it, unweakened
# ==========================================================================
def test_b3_b15_reads_name_status_and_no_longer_name_only():
    src = _b15_source()
    assert "--name-status" in src, "b15 must ask git for STATUS letters"
    assert "--no-renames" in src, "renames must stay off so a path is one row"
    assert "--name-only" not in src, "the status-blind flag must be GONE"
    assert "swept_test_paths(" in src, "b15 must source `changed` from the function"
    assert "pytest.skip" in src, "the git-unavailable skip must survive"


def test_b3_the_subset_comparison_and_wording_are_unchanged():
    src = _b15_source()
    assert "changed <= expected" in src, "the comparison must stay a SUBSET test"
    assert FAILURE_WORDING in src, "the failure wording must be unchanged"
    cmps = [n for n in ast.walk(_b15_node())
            if isinstance(n, ast.Compare) and isinstance(n.left, ast.Name)
            and n.left.id == "changed"]
    assert cmps, "b15 must still compare `changed` itself"
    assert any(isinstance(op, ast.LtE) for c in cmps for op in c.ops), \
        "`changed` must be compared with <=, never weakened to a bool or a count"


def test_b3_b15_skips_rather_than_reds_when_git_is_unavailable(monkeypatch):
    monkeypatch.setattr(_brake, "subprocess", types.SimpleNamespace(
        run=lambda *a, **k: types.SimpleNamespace(returncode=128, stdout="", stderr="")))
    with pytest.raises(pytest.skip.Exception):
        getattr(_brake, B15)()


def test_b3_b15_is_green_against_the_live_tree():
    if not _git_available():
        pytest.skip("git unavailable")
    getattr(_brake, B15)()


# ==========================================================================
# Behavior 4 -- the deletion is provably inert
# ==========================================================================
def test_b4_at_least_eight_candidate_rows_were_retired():
    resolved = _resolved_expected()
    retired = [p for p in CANDIDATE_PATHS if p not in resolved]
    assert len(retired) >= 8, (
        "the narrowing must retire the rows it freed; retired only "
        f"{sorted(retired)}")


def test_b4_every_retired_candidate_is_tracked_at_head():
    if not _git_available():
        pytest.skip("git unavailable")
    resolved = _resolved_expected()
    for path in CANDIDATE_PATHS:
        if path in resolved:
            continue
        assert _git("cat-file", "-e", f"HEAD:{path}").returncode == 0, \
            f"{path} was retired but is NOT tracked at HEAD -- it could re-red"


def test_b4_no_retired_candidate_is_modified_or_deleted_in_the_shipping_tree():
    if not _git_available():
        pytest.skip("git unavailable")
    r = _git("diff", "HEAD", "--name-status", "--no-renames", "--", "tests/")
    if r.returncode != 0:
        pytest.skip("git diff unavailable")
    status = _status_map(r.stdout)
    resolved = _resolved_expected()
    for path in CANDIDATE_PATHS:
        if path in resolved:
            continue
        assert not status.get(path, "").startswith(("M", "D")), \
            f"{path} was retired while status {status.get(path)!r} -- in-domain"


def test_b4_no_row_with_a_live_sibling_witness_was_retired():
    assert dangling_witness_rows(_live_sibling_sources(), OWNER_NAME,
                                 _resolved_expected()) == (), \
        "a row another shipped module asserts the PRESENCE of is load-bearing"


def test_b4_the_dangling_witness_oracle_can_red():
    fake = {"test_iter999_behavior.py":
            'OWNER = "test_iter204_behavior.py"\n'
            'def test_ac_this_module_is_on_the_b15_allow_list():\n'
            '    assert "still-here" in OWNER\n'}
    assert dangling_witness_rows(fake, OWNER_NAME, frozenset()) == \
        ("tests/test_iter999_behavior.py",), "the oracle must FIRE on a dangling witness"
    assert dangling_witness_rows(
        fake, OWNER_NAME, frozenset({"tests/test_iter999_behavior.py"})) == (), \
        "and must be SILENT once the row is present"


def test_b4_a_module_without_an_allow_list_witness_claims_nothing():
    fake = {"test_iter998_behavior.py":
            'OWNER = "test_iter204_behavior.py"\n'
            'def test_something_else():\n'
            '    assert OWNER\n'}
    assert witness_claims(fake, OWNER_NAME) == {}, \
        "merely NAMING the owner module must not make a module a witness"


def test_b4_the_witness_scan_is_non_vacuous_over_the_shipped_tree():
    sources = _live_sibling_sources()
    assert len(sources) >= 100, \
        f"the witness scan must read >=100 sibling modules, saw {len(sources)}"
    parsed = sum(1 for text in sources.values() if _parses(text))
    assert parsed >= 100, f"only {parsed} modules parsed; a silent scan cannot pass"


# ==========================================================================
# Behavior 5 -- the frozen f-string row is RETAINED
# ==========================================================================
def test_b5_the_frozen_f_string_row_is_retained():
    text = OWNER.read_text(encoding="utf-8")
    assert 'f"tests/test_iter{THIS_ITER}_behavior.py"' in text, \
        "the f-string row covers the very file every b15 repair must edit"
    _, non_strings, _ = _expected_rows()
    assert any("THIS_ITER" in row for row in non_strings), \
        "the f-string row must still be an ELEMENT of `expected`"


def test_b5_this_iter_stays_frozen_and_covers_the_owner_file():
    assert _brake.THIS_ITER == 204, "THIS_ITER must stay frozen at its own iteration"
    assert f"tests/{OWNER_NAME}" in _resolved_expected(), \
        "the owner file must be covered by `expected`"


# ==========================================================================
# Behavior 6 -- staging-window green against a THROWAWAY index
# ==========================================================================
def test_b6_the_brake_passes_in_the_staging_window(tmp_path):
    if not _git_available():
        pytest.skip("git unavailable")
    real_index = pathlib.Path(_git("rev-parse", "--absolute-git-dir").stdout.strip())
    real_index = real_index / "index"
    if not real_index.exists():
        pytest.skip("no index to copy")
    before = _git("diff", "--cached", "--name-only", "--", "tests/")
    copy = tmp_path / "throwaway-index"
    shutil.copy2(real_index, copy)
    env = dict(os.environ, GIT_INDEX_FILE=str(copy))
    if _git("add", "-A", env=env).returncode != 0:
        pytest.skip("git add into the throwaway index failed")
    r = _git("diff", "HEAD", "--name-status", "--no-renames", "--", "tests/", env=env)
    if r.returncode != 0:
        pytest.skip("git diff unavailable")
    changed = _brake.swept_test_paths(r.stdout)
    resolved = _resolved_expected()
    assert changed <= resolved, \
        f"the staging window must be GREEN; unexpected: {sorted(changed - resolved)}"
    mine = "tests/" + SELF_NAME
    status = _status_map(r.stdout)
    if mine in status:
        assert status[mine].startswith("A"), \
            f"this iteration's new test file must stage as A, saw {status[mine]!r}"
        assert mine not in resolved, "an A-status path must need NO allow-list row"
        assert mine not in changed, "an A-status path must not be judged at all"
    after = _git("diff", "--cached", "--name-only", "--", "tests/")
    assert (before.returncode, before.stdout) == (after.returncode, after.stdout), \
        "the REAL index's staged tests/ content must be untouched by this measurement"


# ==========================================================================
# Behavior 7 -- positive control, two-sided
# ==========================================================================
def _scripted_git(monkeypatch, stdout):
    monkeypatch.setattr(_brake, "subprocess", types.SimpleNamespace(
        run=lambda *a, **k: types.SimpleNamespace(
            returncode=0, stdout=stdout, stderr="")))


def test_b7_the_control_path_is_absent_from_expected():
    assert CONTROL_PATH not in _resolved_expected(), \
        f"{CONTROL_PATH} must stay OUT of `expected` for the control to mean anything"


def test_b7_a_modified_sweep_still_reds_the_narrowed_brake(monkeypatch):
    _scripted_git(monkeypatch, f"M\t{CONTROL_PATH}\n")
    with pytest.raises(AssertionError) as excinfo:
        getattr(_brake, B15)()
    message = str(excinfo.value)
    assert FAILURE_WORDING in message, message
    assert CONTROL_PATH in message, message


def test_b7_the_same_path_added_does_not_red(monkeypatch):
    _scripted_git(monkeypatch, f"A\t{CONTROL_PATH}\n")
    getattr(_brake, B15)()


def test_b7_the_control_is_a_real_member_of_the_swept_population():
    assert _brake.swept_test_paths(f"M\t{CONTROL_PATH}\n") == {CONTROL_PATH}
    assert _brake.swept_test_paths(f"A\t{CONTROL_PATH}\n") == set()


def test_b7_a_mixed_text_reds_only_on_the_modified_member(monkeypatch):
    _scripted_git(monkeypatch,
                  f"A\ttests/{SELF_NAME}\nM\t{CONTROL_PATH}\nM\ttests/{OWNER_NAME}\n")
    with pytest.raises(AssertionError) as excinfo:
        getattr(_brake, B15)()
    message = str(excinfo.value)
    assert CONTROL_PATH in message
    assert SELF_NAME not in message, \
        "an ADDED path must never appear in the failure report"


# ==========================================================================
# Behavior 4 (retry round) -- the retirement is MAXIMAL, and the spec's
# ">= 11" count is unattainable in ONE iteration
# ==========================================================================
def witness_free_candidates(source_by_name, owner_name, candidate_paths):
    """PURE: the candidate rows NO sibling module asserts the presence of.

    These are the only rows a single iteration may retire: a row a shipped module
    witnesses is load-bearing however inert the brake itself finds it.
    """
    claimed = {path
               for paths in witness_claims(source_by_name, owner_name).values()
               for path in paths}
    return tuple(p for p in candidate_paths if p not in claimed)


def test_b4_the_retirement_is_exactly_the_witness_free_population():
    """Stronger than a count: every FREE row went, and no WITNESSED row went."""
    sources = _live_sibling_sources()
    resolved = _resolved_expected()
    free = set(witness_free_candidates(sources, OWNER_NAME, CANDIDATE_PATHS))
    retired = {p for p in CANDIDATE_PATHS if p not in resolved}
    assert retired <= free, (
        "a WITNESSED row was retired -- its sibling module will red: "
        f"{sorted(retired - free)}")
    assert free <= retired, (
        "a row that was free to go was LEFT BEHIND, so the paydown is not maximal: "
        f"{sorted(free - retired)}")


def test_b4_the_maximum_attainable_count_is_measured_not_assumed():
    """Records WHY the spec's '>= 11' cannot be met: only 8 candidates are free."""
    free = witness_free_candidates(_live_sibling_sources(), OWNER_NAME, CANDIDATE_PATHS)
    assert len(CANDIDATE_PATHS) == 14, "the spec's candidate population is 14 rows"
    assert len(free) == 14 - 6, (
        "six candidates are witnessed by a sibling module, so at most eight are "
        f"retirable this iteration; measured free = {sorted(free)}")


_WITNESSED_CANDIDATES = tuple(
    p for p in CANDIDATE_PATHS
    if p not in witness_free_candidates(_live_sibling_sources(), OWNER_NAME,
                                        CANDIDATE_PATHS))


@pytest.mark.parametrize("path", _WITNESSED_CANDIDATES)
def test_b4_retiring_a_witness_would_put_its_own_module_back_in_domain(path):
    """The attractive escape from the 8-row ceiling is CIRCULAR.

    Retiring a witnessed row means EDITING that sibling module to drop its witness.
    An edited module is status `M`, which the narrowed brake KEEPS, so the module
    lands back in the judged population and still needs its row.  Both halves are
    measured here: the path is in-domain when edited, and it is covered today.
    """
    assert _brake.swept_test_paths(f"M\t{path}") == {path}, \
        "an EDITED sibling module is in-domain for the narrowed brake"
    assert path in _resolved_expected(), \
        "so its allow-list row must still be present while the witness lives"


# ==========================================================================
# Acceptance guard -- no pre-existing assertion was weakened, renamed or deleted
# ==========================================================================
def test_ac_no_test_function_of_the_owner_module_was_lost_or_renamed():
    if not _git_available():
        pytest.skip("git unavailable")
    shipped = _git("show", f"HEAD:tests/{OWNER_NAME}")
    if shipped.returncode != 0:
        pytest.skip("owner module not readable at HEAD")

    def _defs(source):
        return {n.name for n in ast.walk(ast.parse(source))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    before = _defs(shipped.stdout)
    after = _defs(OWNER.read_text(encoding="utf-8"))
    assert before <= after, f"assertions were DELETED or renamed: {sorted(before - after)}"
    # Subset, not equality: once this iteration is COMMITTED, HEAD is the new file and
    # the difference is empty -- a fresh-clone re-verification must still pass.
    assert after - before <= {"swept_test_paths"}, \
        f"only the specified helper may be new, saw {sorted(after - before)}"


def test_ac_the_owner_modules_assert_count_did_not_drop():
    if not _git_available():
        pytest.skip("git unavailable")
    shipped = _git("show", f"HEAD:tests/{OWNER_NAME}")
    if shipped.returncode != 0:
        pytest.skip("owner module not readable at HEAD")

    def _asserts(source):
        return sum(1 for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Assert))

    before, after = _asserts(shipped.stdout), _asserts(OWNER.read_text(encoding="utf-8"))
    assert after >= before, \
        f"the owner module lost assertions: {before} at HEAD -> {after} in the tree"


def test_ac_only_candidate_rows_left_the_expected_set():
    """A set-literal census, so a silent row loss elsewhere cannot hide.

    Deliberately a FLOOR and not an exact count: an exact row count would be a new
    frozen literal every future iteration has to edit, which is the very tax this
    iteration pays down.  The spec keeps 30 non-candidate rows, so anything below
    that means a row outside the candidate population was swept.
    """
    lits, non_strings, total = _expected_rows()
    assert len(non_strings) == 1, \
        f"the one f-string row must be the ONLY computed row, saw {non_strings}"
    assert total == len(lits) + 1, "every other row must be a plain string literal"
    non_candidate = [row for row in lits if row not in set(CANDIDATE_PATHS)]
    # 44 rows at HEAD minus the 14 candidates = the 30 the spec keeps OUT of scope,
    # and the computed f-string row is one of those 30, so it counts here too.
    survivors = len(non_candidate) + len(non_strings)
    assert survivors >= 30, (
        "the 30 rows outside the candidate population must not move; only "
        f"{survivors} survive ({sorted(non_candidate)})")
