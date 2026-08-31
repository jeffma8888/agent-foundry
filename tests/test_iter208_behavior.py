"""Black-box behaviour tests for iter 208 -- README dormancy clauses stop denying
call sites that the live orchestrators UNCONDITIONALLY have, and a new pure
`dormancy_claim_gaps` oracle reds the suite whenever that class regresses.

The claim under test is a docs-vs-callgraph one: README item 38 (`scout-plan`) and
item 40 (`novelty-check`) each used to state that no orchestrator calls them, while
`run_iteration` calls `scout_phase_outcome` and `build_prompt` calls
`pm_novelty_block` as plain unconditional statements. A verb wrongly marked dormant
invites exactly the edit the quality bar forbids ("never edit a currently-running
loop's semantics"), because the doc promises there is no call site to break.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-208 PM spec's
Expected Behaviors (1-7) and Acceptance Criteria, the `tests/` conventions (esp.
tests/test_iter201_behavior.py for the I/O-door purity pattern and
tests/test_iter207_behavior.py for the `ast` census pattern), the tracked `README.md`
(a document the contract explicitly permits), and the product's own OBSERVABLE
behaviour, established by CALLING the shipped public function and reading its return
values. The engineer's notes, the reviewer's notes and `git diff` were NOT read, and
the implementation's source was NOT read for design. `foundry.py` is opened here ONLY
as `ast` INPUT, because Behavior 7 and Acceptance Criterion 2 are themselves
structural claims about the shipped module that the spec directs be measured that way
(derive `live_callees` from a real `ast` walk, never hard-code it).

Fully offline and deterministic: every fixture is a literal built in this file or a
`tmp_path` artifact, never the ambient gitignored tree (no iteration-state
counts, no dependency on the live dispatcher log), so a fresh clone decides every
assertion identically. The only
files read are the TRACKED `README.md`, `foundry.py` and `dispatcher.py`, all by a
path computed from `__file__` -- no absolute machine path appears anywhere in this
file (the iter-205 revert was caused by exactly such a literal in a fixture).
"""
import ast
import builtins
import inspect
import io
import os
import pathlib
import socket
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import foundry  # noqa: E402


# Behavior 1 -- the exact two rows the spec fixes, as (item, verb, core, orchestrator)
EXPECTED_SEAMS = (
    (38, "scout-plan", "scout_phase_outcome", "run_iteration"),
    (40, "novelty-check", "pm_novelty_block", "build_prompt"),
)

# Behavior 7 -- the control paths that must hold ZERO call sites (additive-dormant)
ORCHESTRATORS = (
    "run_iteration",
    "build_prompt",
    "run_execution_plan",
    "postrelease_step",
    "save_final_gate_round",
    "aggregate_gate_verdict",
    "decide_product_gate",
)

CORE = "dormancy_claim_gaps"


# --------------------------------------------------------------------------
# helpers -- structural measurement only, never a source read for design
# --------------------------------------------------------------------------
def _module_ast(basename):
    return ast.parse((REPO_ROOT / basename).read_text(encoding="utf-8"))


def _functions(tree):
    return {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _direct_callees(func_node):
    """Bare + attribute callee NAMES appearing anywhere inside one function body."""
    out = set()
    for n in ast.walk(func_node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def _live_callees_from_ast():
    """Behavior 4 / AC2: DERIVE the live set from the real orchestrator bodies.

    Hard-coding {"scout_phase_outcome", "pm_novelty_block"} would make Behavior 4
    pass forever; walking the shipped bodies means a refactor that drops a seam
    reds the row instead of silently agreeing with a stale table.
    """
    funcs = _functions(_module_ast("foundry.py"))
    live = set()
    for _item, _verb, _core, orchestrator in foundry.DORMANCY_LIVE_SEAMS:
        live |= _direct_callees(funcs[orchestrator])
    return live


def _readme_text():
    return (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def _readme_entry(text, item):
    """The item's own entry: its `# <n>. ` heading up to the NEXT such heading."""
    import re

    start = re.search(r"(?m)^# %d\. " % item, text)
    assert start is not None, f"README has no '# {item}. ' entry heading"
    rest = text[start.end():]
    nxt = re.search(r"(?m)^# \d+\. ", rest)
    return text[start.start(): start.end() + (nxt.start() if nxt else len(rest))]


def _deny(item, verb, phrase="the pipeline/gate/dispatcher never call it"):
    """A PLANTED known-bad entry -- built here, never taken from the ambient tree."""
    return f"# {item}. {verb}: does a read-only thing, {phrase} and it writes nothing:\n"


def _clean(item, verb):
    return f"# {item}. {verb}: does a read-only thing. Its CORE is LIVE:\n"


# --------------------------------------------------------------------------
# Behavior 1 -- DORMANCY_LIVE_SEAMS holds exactly the two rows
# --------------------------------------------------------------------------
def test_b1_seams_is_a_module_level_tuple_of_exactly_two_rows():
    seams = foundry.DORMANCY_LIVE_SEAMS
    assert isinstance(seams, tuple), f"expected a tuple, got {type(seams).__name__}"
    assert len(seams) == 2, f"spec fixes exactly TWO rows this iteration, got {len(seams)}"
    assert seams == EXPECTED_SEAMS


def test_b1_each_row_is_item_verb_core_orchestrator():
    for row in foundry.DORMANCY_LIVE_SEAMS:
        assert isinstance(row, tuple) and len(row) == 4, row
        item, verb, core, orchestrator = row
        assert isinstance(item, int) and not isinstance(item, bool)
        assert isinstance(verb, str) and verb
        assert isinstance(core, str) and core
        assert isinstance(orchestrator, str) and orchestrator


def test_b1_item_30_lint_manifest_is_deliberately_ABSENT():
    """Out of Scope: item 30's call site is GUARDED, so "live" is not a boolean and
    the spec scopes this table to UNCONDITIONAL call sites only."""
    assert 30 not in [row[0] for row in foundry.DORMANCY_LIVE_SEAMS]
    assert "lint_manifest" not in [row[2] for row in foundry.DORMANCY_LIVE_SEAMS]


# --------------------------------------------------------------------------
# Behavior 2 -- a module-level, TOTAL, pure function
# --------------------------------------------------------------------------
def test_b2_is_a_module_level_function_taking_text_and_a_name_set():
    fn = getattr(foundry, CORE)
    assert inspect.isfunction(fn), f"{CORE} must be a plain module-level function"
    assert fn.__module__ == "foundry"
    params = list(inspect.signature(fn).parameters)
    assert len(params) == 2, f"expected (readme_text, live_callees), got {params}"


def test_b2_denial_phrases_is_a_module_level_non_empty_string_table():
    phrases = foundry.DORMANCY_DENIAL_PHRASES
    assert isinstance(phrases, tuple) and phrases
    assert all(isinstance(p, str) and p for p in phrases)


@pytest.mark.parametrize(
    "case,text,callees",
    [
        ("empty text", "", ("scout_phase_outcome", "pm_novelty_block")),
        ("empty callees", _deny(38, "scout-plan"), ()),
        ("empty both", "", ()),
        ("generator", _deny(38, "scout-plan"), (n for n in ("pm_novelty_block",))),
        ("duplicates", _deny(40, "novelty-check"), ["scout_phase_outcome"] * 4),
        ("set", _deny(40, "novelty-check"), {"scout_phase_outcome"}),
        ("frozenset", "", frozenset()),
        ("unrelated names", "prose with no entry heading at all\n", ("os", "sys")),
    ],
)
def test_b2_is_total_and_always_returns_a_tuple_of_one_line_strings(case, text, callees):
    out = foundry.dormancy_claim_gaps(text, callees)
    assert isinstance(out, tuple), case
    for gap in out:
        assert isinstance(gap, str) and gap
        assert "\n" not in gap, f"{case}: gap descriptions must be ONE line: {gap!r}"


def test_b2_result_is_sorted_ascending_by_readme_item_number():
    live = ("pm_novelty_block", "scout_phase_outcome")
    # both rows denied, planted in DESCENDING order so a naive pass-through would fail
    text = _deny(40, "novelty-check") + _deny(38, "scout-plan")
    out = foundry.dormancy_claim_gaps(text, live)
    assert len(out) == 2, out
    assert "38" in out[0] and "40" in out[1], f"not sorted by item number: {out}"


def test_b2_performs_no_filesystem_subprocess_or_network_io(monkeypatch):
    """Every I/O door is slammed; the oracle must still answer the whole matrix."""
    readme = _readme_text()  # read BEFORE the doors close
    live = _live_callees_from_ast()

    def boom(*a, **k):  # pragma: no cover - must never run
        raise AssertionError(f"{CORE} performed I/O")

    monkeypatch.setattr(builtins, "open", boom)
    monkeypatch.setattr(io, "open", boom, raising=False)
    monkeypatch.setattr(pathlib.Path, "open", boom)
    monkeypatch.setattr(pathlib.Path, "read_text", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)
    monkeypatch.setattr(os, "system", boom)
    monkeypatch.setattr(socket, "socket", boom)

    assert foundry.dormancy_claim_gaps(readme, live) == ()
    assert len(foundry.dormancy_claim_gaps(_deny(38, "scout-plan"), live)) == 1
    assert foundry.dormancy_claim_gaps("", live) == ()


def test_b2_is_deterministic_and_mutates_neither_argument():
    text = _deny(38, "scout-plan") + _clean(40, "novelty-check")
    live = ["scout_phase_outcome", "pm_novelty_block"]
    first = foundry.dormancy_claim_gaps(text, live)
    for _ in range(5):
        assert foundry.dormancy_claim_gaps(text, live) == first
    assert text == _deny(38, "scout-plan") + _clean(40, "novelty-check")
    assert live == ["scout_phase_outcome", "pm_novelty_block"]


# --------------------------------------------------------------------------
# Behavior 3 -- a gap iff BOTH the core is live AND the entry denies the call site
# --------------------------------------------------------------------------
@pytest.mark.parametrize("item,verb,core,orchestrator", EXPECTED_SEAMS)
@pytest.mark.parametrize("denying", [True, False])
@pytest.mark.parametrize("is_live", [True, False])
def test_b3_gap_emitted_iff_live_AND_denying(item, verb, core, orchestrator, denying, is_live):
    text = _deny(item, verb) if denying else _clean(item, verb)
    live = (core,) if is_live else ("some_other_function",)
    out = foundry.dormancy_claim_gaps(text, live)
    if denying and is_live:
        assert len(out) == 1, f"expected ONE gap for item {item}, got {out}"
    else:
        assert out == (), f"item {item} denying={denying} live={is_live} -> {out}"


@pytest.mark.parametrize("item,verb,core,orchestrator", EXPECTED_SEAMS)
def test_b3_gap_text_names_item_verb_orchestrator_and_core(item, verb, core, orchestrator):
    (gap,) = foundry.dormancy_claim_gaps(_deny(item, verb), (core,))
    for token in (str(item), verb, orchestrator, core):
        assert token in gap, f"gap omits {token!r}: {gap!r}"


@pytest.mark.parametrize("phrase", list(foundry.DORMANCY_DENIAL_PHRASES))
def test_b3_every_shipped_denial_phrase_is_load_bearing(phrase):
    """Each phrase in the table must on its own turn a live seam into a gap --
    otherwise the table carries dead entries that read as coverage."""
    text = f"# 38. scout-plan: read-only, {phrase}, writes nothing:\n"
    assert len(foundry.dormancy_claim_gaps(text, ("scout_phase_outcome",))) == 1, phrase


def test_b3_entry_scope_stops_at_the_next_item_heading():
    """A denial belonging to a NEIGHBOUR entry must not be attributed to item 38."""
    text = _clean(38, "scout-plan") + _deny(39, "some-other-verb")
    assert foundry.dormancy_claim_gaps(text, ("scout_phase_outcome",)) == ()


def test_b3_entry_scope_covers_continuation_lines_up_to_the_next_heading():
    text = (
        "# 38. scout-plan: first line of the entry\n"
        "uv run python foundry.py scout-plan  # the pipeline/gate/dispatcher never call it\n"
        + _clean(39, "some-other-verb")
    )
    assert len(foundry.dormancy_claim_gaps(text, ("scout_phase_outcome",))) == 1


def test_b3_last_entry_extends_to_end_of_text():
    text = _clean(38, "scout-plan") + _deny(40, "novelty-check")  # no trailing heading
    (gap,) = foundry.dormancy_claim_gaps(text, ("pm_novelty_block",))
    assert "40" in gap


def test_b3_an_inline_pseudo_heading_is_not_an_entry():
    text = "prose that merely mentions # 38. and never call it, mid-line\n"
    assert foundry.dormancy_claim_gaps(text, ("scout_phase_outcome",)) == ()


def test_b3_denial_phrases_are_read_at_CALL_time(monkeypatch):
    text = "# 38. scout-plan: this verb is COMPLETELY UNWIRED today\n"
    live = ("scout_phase_outcome",)
    assert foundry.dormancy_claim_gaps(text, live) == ()
    monkeypatch.setattr(
        foundry,
        "DORMANCY_DENIAL_PHRASES",
        tuple(foundry.DORMANCY_DENIAL_PHRASES) + ("COMPLETELY UNWIRED",),
    )
    assert len(foundry.dormancy_claim_gaps(text, live)) == 1


def test_b3_seams_table_is_read_at_CALL_time(monkeypatch):
    """A patched table must steer the oracle -- proof it reads the module global
    rather than a def-time copy (the seam-visibility convention)."""
    monkeypatch.setattr(
        foundry, "DORMANCY_LIVE_SEAMS", ((99, "made-up", "made_up_core", "made_up_caller"),)
    )
    (gap,) = foundry.dormancy_claim_gaps(_deny(99, "made-up"), ("made_up_core",))
    assert "99" in gap and "made-up" in gap
    assert foundry.dormancy_claim_gaps(_deny(38, "scout-plan"), ("scout_phase_outcome",)) == ()


# --------------------------------------------------------------------------
# Behavior 4 -- THE BRAKE: the real README against the real callgraph is clean
# --------------------------------------------------------------------------
def test_b4_the_real_readme_against_the_ast_derived_callgraph_is_clean():
    live = _live_callees_from_ast()
    gaps = foundry.dormancy_claim_gaps(_readme_text(), live)
    assert gaps == (), "README denies a call site the code HAS:\n  " + "\n  ".join(gaps)


def test_b4_the_ast_derivation_is_not_vacuous():
    """If this reds, the seam moved -- which is the row this brake exists to catch,
    and it must never be silenced by a table that no longer matches the code."""
    live = _live_callees_from_ast()
    for _item, _verb, core, orchestrator in foundry.DORMANCY_LIVE_SEAMS:
        assert core in live, f"{orchestrator} no longer calls {core}"


@pytest.mark.parametrize("item,verb,core,orchestrator", EXPECTED_SEAMS)
def test_b4_readme_entry_of_each_row_would_red_if_the_denial_came_back(item, verb, core, orchestrator):
    """Two-sided proof the brake measures the REAL entry: splice the shipped entry's
    heading back together with a denial and the same call it clean -> exactly 1 gap."""
    live = _live_callees_from_ast()
    entry = _readme_entry(_readme_text(), item)
    regressed = entry.rstrip("\n") + " -- the pipeline/gate/dispatcher never call it\n"
    assert len(foundry.dormancy_claim_gaps(regressed, live)) == 1


# --------------------------------------------------------------------------
# Behavior 5 -- one denying item -> exactly one gap; a not-live core -> none
# --------------------------------------------------------------------------
def test_b5_a_denying_entry_for_a_live_core_yields_exactly_one_named_gap():
    text = _deny(38, "scout-plan") + _clean(40, "novelty-check")
    out = foundry.dormancy_claim_gaps(text, ("scout_phase_outcome", "pm_novelty_block"))
    assert len(out) == 1, out
    assert "38" in out[0] and "scout-plan" in out[0]


def test_b5_the_same_denying_text_is_clean_when_the_core_is_not_live():
    text = _deny(38, "scout-plan") + _deny(40, "novelty-check")
    assert foundry.dormancy_claim_gaps(text, ()) == ()
    assert foundry.dormancy_claim_gaps(text, ("unrelated_helper",)) == ()


def test_b5_both_rows_denied_and_both_live_yields_two_gaps():
    text = _deny(38, "scout-plan") + _deny(40, "novelty-check")
    out = foundry.dormancy_claim_gaps(text, ("scout_phase_outcome", "pm_novelty_block"))
    assert len(out) == 2, out


# --------------------------------------------------------------------------
# Behavior 6 -- the two README entries are reworded on the item-41 template
# --------------------------------------------------------------------------
def test_b6_item_38_no_longer_says_never_call_it():
    entry = _readme_entry(_readme_text(), 38)
    assert "never call it" not in entry
    assert "never calls it" not in entry


def test_b6_item_40_no_longer_says_it_is_not_consulted_yet():
    entry = _readme_entry(_readme_text(), 40)
    assert "does not consult it yet" not in entry
    assert "does not consult it" not in entry


@pytest.mark.parametrize("item,verb,core,orchestrator", EXPECTED_SEAMS)
def test_b6_each_entry_states_the_core_is_LIVE_and_names_orchestrator_and_core(
    item, verb, core, orchestrator
):
    entry = _readme_entry(_readme_text(), item)
    assert "LIVE" in entry, f"item {item} does not state the core is LIVE"
    assert orchestrator in entry, f"item {item} does not name {orchestrator}"
    assert core in entry, f"item {item} does not name {core}"


@pytest.mark.parametrize("item,verb,core,orchestrator", EXPECTED_SEAMS)
def test_b6_no_shipped_entry_carries_any_denial_phrase(item, verb, core, orchestrator):
    entry = _readme_entry(_readme_text(), item)
    for phrase in foundry.DORMANCY_DENIAL_PHRASES:
        assert phrase not in entry, f"item {item} still carries {phrase!r}"


# --------------------------------------------------------------------------
# Behavior 7 -- additive-dormant: imports clean, ZERO call sites on the control path
# --------------------------------------------------------------------------
def test_b7_foundry_and_dispatcher_still_import_cleanly():
    for mod in ("foundry", "dispatcher"):
        proc = subprocess.run(
            [sys.executable, "-c", f"import {mod}"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, f"import {mod} failed:\n{proc.stdout}\n{proc.stderr}"


def test_b7_zero_call_sites_in_any_orchestrator_or_the_release_gate():
    funcs = _functions(_module_ast("foundry.py"))
    for name in ORCHESTRATORS:
        assert name in funcs, f"orchestrator {name} vanished from foundry.py"
        assert CORE not in _direct_callees(funcs[name]), f"{CORE} is called from {name}"


def test_b7_zero_call_sites_anywhere_in_foundry_or_dispatcher():
    """Fully dormant: a loop in flight resumes byte-identically, so this iteration
    owes no dispatcher restart."""
    for basename in ("foundry.py", "dispatcher.py"):
        tree = _module_ast(basename)
        callees = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Name):
                    callees.add(f.id)
                elif isinstance(f, ast.Attribute):
                    callees.add(f.attr)
        assert CORE not in callees, f"{CORE} has a call site in {basename}"


# --------------------------------------------------------------------------
# Acceptance criteria -- rename guard + fresh-clone safety of this file itself
# --------------------------------------------------------------------------
def test_ac_every_core_name_resolves_to_a_real_module_level_function():
    """Rename guard: a renamed core must not silently empty the table."""
    for _item, _verb, core, orchestrator in foundry.DORMANCY_LIVE_SEAMS:
        obj = getattr(foundry, core, None)
        assert inspect.isfunction(obj), f"{core} is not a module-level function of foundry"
        assert obj.__module__ == "foundry"
        assert inspect.isfunction(getattr(foundry, orchestrator, None)), orchestrator


def test_ac_this_test_file_depends_on_tracked_files_only(tmp_path):
    """A fresh clone has no gitignored state; every input here is tracked or built
    in tmp_path, so the planted control never touches the ambient tree."""
    for basename in ("README.md", "foundry.py", "dispatcher.py"):
        assert (REPO_ROOT / basename).is_file(), basename
    # needles are ASSEMBLED, never written contiguously: a literal needle would
    # match this very assertion and the check would fail on a correct file
    body = pathlib.Path(__file__).read_text(encoding="utf-8")
    for needle in ("products/" + "_platform/state", "dispatcher" + ".out", "/" + "Users" + "/"):
        assert needle not in body, f"this file depends on {needle!r}"
    planted = tmp_path / "readme_fixture.md"
    planted.write_text(_deny(38, "scout-plan"), encoding="utf-8")
    assert len(foundry.dormancy_claim_gaps(planted.read_text(), ("scout_phase_outcome",))) == 1
