"""Iteration 189 -- BLACK-BOX behavior tests: a cap-killed final stage != a refusal.

Spec under test (products/_platform/state/iter-189/pm.md), Expected Behaviors 1-11:
   1. PUSHED + moved head -> SHIP, and ship/retry/revert agree with the verdict
   2. PUSHED + moved head -> SHIP for ALL FOUR kill x retries combinations
   3. PUSHED + UNMOVED head -> REVERT (all four), detail names the branch head
   4. explicit REVERTED -> REVERT on ALL EIGHT combinations, even when also killed
   5. no token + killed + retries left -> RETRY (both head values), detail = MACHINE
   6. no token + killed + NO retries -> REVERT (both head values), retry budget spent
   7. no token + NOT killed -> REVERT (all four): the stage COMPLETED and stayed mute
   8. every non-token action string behaves EXACTLY as None on all 8 combinations
   9. totality over the full 64-input cross-product; exactly one flag True; sentinel
  10. TODAY-EQUIVALENCE: never ships what today would not, and the revert delta is
      EXACTLY the no-token + killed + retries-left cells
  11. dormancy, AST-verified: zero call sites, and the three live orchestrators plus
      dispatcher.py never even spell the new names
      -- ITERATION 194 WIRED THE FEATURE, so the two assertions that froze the
      DORMANT state are inverted IN PLACE to the exact wired values (one call site,
      inside `run_iteration`; an exact per-orchestrator name table). The
      dispatcher.py half is UNCHANGED and still green: that module is untouched.

ISOLATION CONTRACT (HONORED): written from the iter-189 PM spec, the conventions of the
existing `tests/test_iter18*_behavior.py` modules, and the product's OWN OBSERVABLE
surface (calling its public functions).  `foundry.py`'s implementation TEXT was NOT read
by the author, and neither were `engineer.md`, `reviewer.md`, `IMPLEMENTATION.patch`, nor
`git diff`.  Behavior 11 mandates an `ast` walk, so this MODULE parses `foundry.py` as
data at runtime -- that is the spec's own oracle, not the author reading the source.

OFFLINE + FRESH-CLONE SAFE: every assertion is a pure in-memory call or an `ast` walk of
the module under test.  No subprocess, no git, no network, no clock, no filesystem WRITE,
no assertion about the ambient tree, a directory basename, a file count, or an absolute
machine path.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

THIS_ITER = 189

# ---------------------------------------------------------------------------
# the input table, built ONCE and reused by every behavior (spec, closing note)
# ---------------------------------------------------------------------------
TOKEN_ACTIONS = ("PUSHED", "REVERTED")
# behavior 8 names these five verbatim; "pushed" pins case-sensitivity
NON_TOKEN_ACTIONS = ("PENDING", "MAYBE", "", "   ", "pushed")
NO_TOKEN_ACTIONS = (None,) + NON_TOKEN_ACTIONS          # 6 values
ACTIONS = (None,) + TOKEN_ACTIONS + NON_TOKEN_ACTIONS   # 8 values
BOOLS = (False, True)
# (head_moved, attempt_killed, retries_remaining) -- 8 combinations
FLAG_COMBOS = tuple((h, k, r) for h in BOOLS for k in BOOLS for r in BOOLS)
# 8 actions x 8 flag combinations = the 64 calls the spec names
GRID = tuple((a,) + combo for a in ACTIONS for combo in FLAG_COMBOS)

FEATURE_NAMES = ("ship_decision", "ShipDecision", "SHIP_DECISION_TOKENS",
                 "attempt_killed", "retries_remaining")
LIVE_ORCHESTRATORS = ("run_stage", "run_iteration", "build_prompt")


def _d(action, head_moved, attempt_killed, retries_remaining):
    """Drive the public decision function by keyword only."""
    return foundry.ship_decision(action=action, head_moved=head_moved,
                                 attempt_killed=attempt_killed,
                                 retries_remaining=retries_remaining)


def _today_ships(action, head_moved):
    """The live rule this bite must not widen: `action == "PUSHED" and head_moved`."""
    return action == "PUSHED" and bool(head_moved)


# ---------------------------------------------------------------------------
# behavior 1 + the module constant
# ---------------------------------------------------------------------------
def test_b1_pushed_with_moved_head_is_ship():
    d = _d("PUSHED", True, False, True)
    assert d.verdict == "SHIP"
    assert d.ship is True
    assert d.retry is False
    assert d.revert is False


def test_b1_token_constant_is_the_closed_vocabulary():
    assert foundry.SHIP_DECISION_TOKENS == ("SHIP", "RETRY", "REVERT")


# ---------------------------------------------------------------------------
# behavior 2 -- a kill never voids a ship the branch head corroborates
# ---------------------------------------------------------------------------
def test_b2_ship_survives_every_kill_and_retry_combination():
    seen = []
    for killed in BOOLS:
        for retries in BOOLS:
            d = _d("PUSHED", True, killed, retries)
            assert d.verdict == "SHIP", (killed, retries, d)
            assert d.ship is True, (killed, retries, d)
            seen.append((killed, retries))
    assert len(seen) == 4


# ---------------------------------------------------------------------------
# behavior 3 -- PUSHED claimed, branch head says otherwise
# ---------------------------------------------------------------------------
def test_b3_pushed_without_head_movement_always_reverts():
    for killed in BOOLS:
        for retries in BOOLS:
            d = _d("PUSHED", False, killed, retries)
            assert d.verdict == "REVERT", (killed, retries, d)
            assert d.revert is True
            assert d.ship is False
            # the spec requires the detail to NAME the unmoved branch head
            assert "head" in d.detail.lower(), d.detail


# ---------------------------------------------------------------------------
# behavior 4 -- an explicit token is authoritative, kill or no kill
# ---------------------------------------------------------------------------
def test_b4_explicit_reverted_is_authoritative_on_all_eight_combinations():
    combos = 0
    for head, killed, retries in FLAG_COMBOS:
        d = _d("REVERTED", head, killed, retries)
        assert d.verdict == "REVERT", (head, killed, retries, d)
        assert d.revert is True
        assert d.retry is False, "an explicit refusal must never be retried"
        # names it as the gate's OWN explicit verdict (wording latitude allowed)
        low = d.detail.lower()
        assert any(w in low for w in ("explicit", "reverted", "declin")), d.detail
        combos += 1
    assert combos == 8


# ---------------------------------------------------------------------------
# behavior 5 -- the whole point: a cap kill is evidence about the MACHINE
# ---------------------------------------------------------------------------
def test_b5_killed_with_retries_left_is_retry_for_both_head_values():
    for head in BOOLS:
        d = _d(None, head, True, True)
        assert d.verdict == "RETRY", (head, d)
        assert d.retry is True
        assert d.ship is False
        assert d.revert is False
        low = d.detail.lower()
        assert any(w in low for w in ("machine", "kill", "timeout", "timed out")), d.detail


# ---------------------------------------------------------------------------
# behavior 6 -- retries are finite; an exhausted budget still reverts
# ---------------------------------------------------------------------------
def test_b6_killed_without_retries_reverts_for_both_head_values():
    for head in BOOLS:
        d = _d(None, head, True, False)
        assert d.verdict == "REVERT", (head, d)
        assert d.revert is True
        assert d.retry is False
        assert "retr" in d.detail.lower(), d.detail


# ---------------------------------------------------------------------------
# behavior 7 -- a stage that COMPLETED and wrote no verdict is a refusal
# ---------------------------------------------------------------------------
def test_b7_completed_stage_with_no_verdict_reverts():
    for head in BOOLS:
        for retries in BOOLS:
            d = _d(None, head, False, retries)
            assert d.verdict == "REVERT", (head, retries, d)
            assert d.revert is True
            assert d.retry is False
            assert "complet" in d.detail.lower(), d.detail


def test_b3_to_b7_the_four_revert_causes_are_distinguishable():
    """Four different reasons must not collapse into one opaque string."""
    details = {
        "pushed_but_head_unmoved": _d("PUSHED", False, False, True).detail,
        "explicit_reverted": _d("REVERTED", True, False, True).detail,
        "killed_no_retries": _d(None, True, True, False).detail,
        "completed_no_verdict": _d(None, True, False, True).detail,
    }
    assert len(set(details.values())) == 4, details


# ---------------------------------------------------------------------------
# behavior 8 -- every non-token action is byte-for-byte a missing token
# ---------------------------------------------------------------------------
def test_b8_non_token_actions_behave_exactly_as_none():
    for bad in NON_TOKEN_ACTIONS:
        for head, killed, retries in FLAG_COMBOS:
            got = _d(bad, head, killed, retries)
            baseline = _d(None, head, killed, retries)
            assert got == baseline, (repr(bad), head, killed, retries, got, baseline)


def test_b8_matching_is_case_sensitive_and_exact():
    lowered = _d("pushed", True, False, True)
    assert lowered.verdict != "SHIP"
    assert lowered.ship is False
    assert lowered == _d(None, True, False, True)


# ---------------------------------------------------------------------------
# behavior 9 -- totality over the whole 64-input cross-product
# ---------------------------------------------------------------------------
def test_b9_totality_over_the_full_cross_product():
    assert len(GRID) == 64
    assert len(set(GRID)) == 64
    for action, head, killed, retries in GRID:
        d = _d(action, head, killed, retries)          # must not raise
        cell = (repr(action), head, killed, retries)
        assert d.verdict in foundry.SHIP_DECISION_TOKENS, cell
        assert isinstance(d.detail, str) and d.detail.strip(), cell
        flags = (d.ship, d.retry, d.revert)
        assert all(isinstance(f, bool) for f in flags), cell
        assert sum(flags) == 1, (cell, flags)
        assert d.sentinel == "SHIPGATE: " + d.verdict, cell


def test_b9_flags_agree_with_the_verdict_on_every_cell():
    want = {"SHIP": (True, False, False),
            "RETRY": (False, True, False),
            "REVERT": (False, False, True)}
    for action, head, killed, retries in GRID:
        d = _d(action, head, killed, retries)
        assert (d.ship, d.retry, d.revert) == want[d.verdict], (repr(action), d)


# ---------------------------------------------------------------------------
# behavior 10 -- TODAY-EQUIVALENCE pins the blast radius
# ---------------------------------------------------------------------------
def test_b10_never_ships_anything_today_would_not():
    for action, head, killed, retries in GRID:
        d = _d(action, head, killed, retries)
        assert d.ship is _today_ships(action, head), (repr(action), head, killed, retries)


def test_b10_revert_delta_is_exactly_the_killed_with_retries_cells():
    differs = set()
    for action, head, killed, retries in GRID:
        d = _d(action, head, killed, retries)
        if d.revert is not (not _today_ships(action, head)):
            differs.add((action, head, killed, retries))
    expected = {(a, h, True, True) for a in NO_TOKEN_ACTIONS for h in BOOLS}
    assert len(expected) == 12
    assert differs == expected


# ---------------------------------------------------------------------------
# behavior 11 -- dormancy, AST-verified rather than grepped
# ---------------------------------------------------------------------------
def _foundry_source():
    return pathlib.Path(foundry.__file__).read_text(encoding="utf-8")


def _parents(tree):
    out = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            out[child] = parent
    return out


def _called_name(node):
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _enclosing_scopes(node, parents):
    names = []
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(cur.name)
        cur = parents.get(cur)
    return names


def test_b11_the_call_matcher_is_not_vacuous():
    """Two-sided proof: the SAME walk must find a call that really is there.

    A zero result is only evidence if the matcher can return non-zero.  A
    line-range-filtered grep produced a false "no call sites" reading at iteration
    188's gate, so this pins the detector before the detector pins the feature.
    """
    # (a) unit-prove the helper on synthetic source: BOTH call shapes must resolve
    synthetic = ast.parse("f(1)\nobj.g(2)\n")
    resolved = [_called_name(n) for n in ast.walk(synthetic) if isinstance(n, ast.Call)]
    assert "f" in resolved, resolved          # ast.Name  callee
    assert "g" in resolved, resolved          # ast.Attribute callee
    # (b) prove it returns NON-ZERO on the real module, so a zero is a fact not a bug
    tree = ast.parse(_foundry_source())
    named = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _called_name(n)]
    assert len(named) > 500, len(named)


def test_b11_ship_decision_has_exactly_one_call_site_inside_run_iteration():
    """INVERTED at iteration 194, which WIRED the feature at the live final gate.

    Behavior 11 froze this at ZERO call sites while the function was dormant.  That
    literal MOVED when the dormancy legitimately ended, so it is re-pinned to the
    EXACT expected value -- one call, in `run_iteration` -- rather than loosened to a
    `>=` or a subset check, which would silently stop constraining anything (the
    iteration-192 gate lesson: a frozen-literal test must move when what it freezes
    grows, and the defect to hunt is an `==` becoming a weaker comparison).
    """
    tree = ast.parse(_foundry_source())
    parents = _parents(tree)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and _called_name(n) == "ship_decision"]
    assert len(calls) == 1, ["line %d" % n.lineno for n in calls]
    scopes = _enclosing_scopes(calls[0], parents)
    assert "run_iteration" in scopes, scopes


def test_b11_ship_decision_type_is_constructed_only_inside_its_own_feature():
    """The result TYPE must be built by the feature and by nobody else.

    AMBIGUITY NOTED (PM feedback): behavior 11 as literally written -- zero `Call`
    nodes naming `ship_decision` OR `ShipDecision` from any enclosing function -- is
    unsatisfiable, because a pure function cannot return its own frozen result type
    without constructing it.  Tested here as the strongest satisfiable reading: zero
    calls to `ship_decision` ANYWHERE (above), and every `ShipDecision(...)` call is
    inside the feature's own scope.
    """
    tree = ast.parse(_foundry_source())
    parents = _parents(tree)
    foreign = []
    internal = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and _called_name(n) == "ShipDecision":
            scopes = _enclosing_scopes(n, parents)
            if not ({"ship_decision", "ShipDecision"} & set(scopes)):
                foreign.append((n.lineno, tuple(scopes)))
            else:
                internal.append(n.lineno)
    assert foreign == [], foreign
    # anti-vacuous: the feature MUST build its own result type somewhere
    assert internal, "no ShipDecision(...) construction found at all"


# INVERTED at iteration 194: `run_iteration` now spells three of the five feature
# names, and the other two orchestrators still spell NONE.  Pinned as an EXACT
# per-orchestrator tuple in `FEATURE_NAMES` order, so the surviving strength is
# real: `ShipDecision` and `SHIP_DECISION_TOKENS` must stay OUT of every
# orchestrator (the caller reads the verdict through the derived `.ship` / `.retry`
# properties and never builds or enumerates the type), and `run_stage` /
# `build_prompt` must stay byte-clean of the whole vocabulary.  Note
# `"attempt_killed"` is matched as a SUBSTRING, so it is satisfied by both the
# keyword argument and the `stage_attempt_killed` helper's name.
ORCHESTRATOR_FEATURE_NAMES = {
    "run_stage": (),
    "build_prompt": (),
    "run_iteration": ("ship_decision", "attempt_killed", "retries_remaining"),
}


def test_b11_live_orchestrators_spell_exactly_the_expected_feature_names():
    assert tuple(sorted(ORCHESTRATOR_FEATURE_NAMES)) == tuple(sorted(LIVE_ORCHESTRATORS))
    src = _foundry_source()
    tree = ast.parse(src)
    checked = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name in LIVE_ORCHESTRATORS:
            segment = ast.get_source_segment(src, node) or ""
            assert segment, node.name
            spelled = tuple(name for name in FEATURE_NAMES if name in segment)
            assert spelled == ORCHESTRATOR_FEATURE_NAMES[node.name], (node.name, spelled)
            checked.append(node.name)
    for want in LIVE_ORCHESTRATORS:
        assert want in checked, (want, checked)


def test_b11_dispatcher_does_not_spell_the_new_names():
    text = pathlib.Path(dispatcher.__file__).read_text(encoding="utf-8")
    assert len(text) > 1000, "dispatcher source unexpectedly empty -- claim would be vacuous"
    for name in FEATURE_NAMES:
        assert name not in text, name


# ---------------------------------------------------------------------------
# acceptance criteria that are observable black-box
# ---------------------------------------------------------------------------
def test_ac_result_type_is_a_frozen_two_field_dataclass():
    cls = foundry.ShipDecision
    assert dataclasses.is_dataclass(cls)
    assert tuple(f.name for f in dataclasses.fields(cls)) == ("verdict", "detail")
    d = _d("PUSHED", True, False, True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.verdict = "REVERT"


def test_ac_flags_and_sentinel_are_derived_properties_never_fields():
    cls = foundry.ShipDecision
    field_names = {f.name for f in dataclasses.fields(cls)}
    for name in ("ship", "retry", "revert", "sentinel"):
        assert name not in field_names, name
        assert isinstance(getattr(cls, name), property), name


def test_ac_signature_is_keyword_only_with_exactly_the_four_inputs():
    sig = inspect.signature(foundry.ship_decision)
    assert tuple(sig.parameters) == ("action", "head_moved", "attempt_killed",
                                     "retries_remaining")
    for p in sig.parameters.values():
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, p.name
    with pytest.raises(TypeError):
        foundry.ship_decision("PUSHED", True, False, True)


def test_ac_placed_after_the_parse_function_whose_output_it_consumes():
    tree = ast.parse(_foundry_source())
    lines = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            lines.setdefault(node.name, node.lineno)
    assert "parse_ship_action" in lines
    assert "ship_decision" in lines
    assert lines["ship_decision"] > lines["parse_ship_action"]
