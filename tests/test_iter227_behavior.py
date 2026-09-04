"""Iteration 227 -- BLACK-BOX behavior tests: a TRACKED, self-verifying corpus of REAL
`final.md` artifacts (`evals/gate/`) replayed against the ship-action gate by two DORMANT
helpers, `load_gate_eval_corpus` (the I/O seam) and `replay_gate_evals` (pure).

Spec under test: products/_platform/state/iter-227/pm.md, Expected Behaviors 1-6.

  1. `load_gate_eval_corpus(root)` reads `<root>/evals/gate/manifest.json` and returns a
     tuple of FROZEN `GateEvalCase` records SORTED BY `case_id`, one per entry, carrying
     case_id / parser / artifact / expect / source / sha256 / text.  Manifest order does
     not affect the result.
  2. It raises `ValueError` naming the offending `case_id` AND the bad value when a
     `parser` is not a key of `GATE_EVAL_PARSERS`, or a `sha256` disagrees with the
     artifact's bytes on disk.
  3. `replay_gate_evals(cases)` takes ANY iterable and returns frozen
     `GateEvalResult(case_id, parser, expect, actual, ok)` in the ITERABLE'S OWN order,
     with `actual = GATE_EVAL_PARSERS[parser](text)` and `ok = (actual == expect)`.  It is
     PURE -- proven here with every file/subprocess/network/clock seam patched to raise and
     the CWD moved to a tmp dir that has no `evals/` at all.
  4. Replaying the SHIPPED corpus yields `ok` True for every case.
  5. NON-VACUITY FLOOR: >= 4 cases, >= 3 with `source == "real"`, the `expect` set covers
     all three of "PUSHED" / "REVERTED" / None, and every `artifact` resolves to a readable
     file.  Floors (`>=`, `in`) only -- never frozen `==` counts.
  6. DORMANCY: an `ast` walk of `foundry.py` finds ZERO call sites for either new helper.

Behaviors 4 and 5 are the ones that could go silently vacuous (the failure mode iteration
227's scout measured in `roadmap_verb_figure_gaps`, green from birth because its subject
had been deleted), so each carries an explicit CONTROL that feeds a deliberately WRONG
input and asserts the check goes RED: `test_b4_control_*` flips every `expect` and demands
`ok` False, and `test_b5_control_*` proves each floor rejects a corpus that violates it.

Also guarded, from the spec's ACCEPTANCE CRITERIA rather than its Expected Behaviors, and
decidable from TRACKED text alone so it still holds in the throwaway fresh clone the
release gate builds (iteration 194 shipped BROKEN because its roadmap record was only
decidable after commit):
   A. This iteration's roadmap record lands in the SAME diff as the code -- exactly one
      `- iter 227 ` ledger row (<= 120 chars) in PLATFORM_ROADMAP.md, exactly one
      `- **iter 227 ` bullet in PLATFORM_ROADMAP_ARCHIVE.md, `roadmap_ledger_gaps` green
      and proved TWO-SIDED against a stripped in-memory copy, and the index inside the
      budget its OWN shipped helper reports (no literal floor is re-pinned here: four
      modules already name 4,000 while tests/test_iter185_behavior.py derives the binding
      4,120, and a fifth copy of the loose number is how a fix gets sized 120 chars too
      generously).
   B. `tests/test_iter227_behavior.py` is present in test_iter204's b15 allow-list, without
      which `git add -A` at the gate turns this very file into an unexpected diff member.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-227 PM spec, the conventions
already in tests/ (the docstring / frozen-literal / two-sided-control shape of
test_iter226_behavior.py and the dormancy walk of test_iter197_behavior.py), and the
product's OWN OBSERVABLE surface -- importing the modules, reading their PUBLIC constants,
CALLING their public functions, and (as tests/test_iter142_behavior.py already does)
letting the TEST read shipped, TRACKED text files at runtime.  The implementation TEXT of
foundry.py / dispatcher.py was NOT read by hand; neither were engineer.md, reviewer.md,
fix_review.md, IMPLEMENTATION.patch nor `git diff`.  The `ast` walk in Behavior 6 reads
foundry.py PROGRAMMATICALLY, which is the check the spec asks for, not a human read.

FIXTURE POLICY: every expectation about the corpus comes from the spec's own fixed table
(case ids, `expect`, `source`, destination paths), never from the shipped manifest, so a
manifest that disagrees with the spec FAILS here instead of validating itself.  Per
OPERATOR 2026-08-11 no assertion reads `products/**/state/` or any other gitignored path:
the spec records each artifact's gitignored provenance as PROSE and this module asserts
only over the TRACKED copies under `evals/`, which a fresh clone does have.

Offline and deterministic: no network, no subprocess, no sleeps, no clock, no git.  Nothing
in the tree is mutated -- every negative case is built inside `tmp_path`.
"""

import ast
import builtins
import dataclasses
import hashlib
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import time

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe

THIS_ITER = 227

FOUNDRY_PY = _ROOT / "foundry.py"
EVALS_GATE = _ROOT / "evals" / "gate"
MANIFEST = EVALS_GATE / "manifest.json"

NEW_NAMES = ("load_gate_eval_corpus", "replay_gate_evals")

SHIP_ACTION_PARSER = "parse_ship_action"

# The corpus the spec FIXES (`## The corpus`): id -> (expect, source, artifact).  These are
# the spec's values, deliberately NOT read back out of the shipped manifest.
SPEC_CASES = {
    "pushed-plain": ("PUSHED", "real", "ship_action/pushed-plain.md"),
    "reverted-plain": ("REVERTED", "real", "ship_action/reverted-plain.md"),
    "none-unrecognized-token": (None, "real", "ship_action/none-unrecognized-token.md"),
    "none-no-action-line": (None, "real", "ship_action/none-no-action-line.md"),
}

# Behavior 5's floors, as FLOORS.  A later iteration that adds a fifth case or a synthetic
# one must not have to touch this module.
MIN_CASES = 4
MIN_REAL_CASES = 3
REQUIRED_EXPECT_VALUES = ("PUSHED", "REVERTED", None)

INDEX_PATH = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE_PATH = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
LEDGER_ROW_PREFIX = "- iter %d " % THIS_ITER
ARCHIVE_BULLET_PREFIX = "- **iter %d " % THIS_ITER
LEDGER_ROW_MAX_CHARS = 120
ALLOW_LIST_OWNER = _ROOT / "tests" / "test_iter204_behavior.py"
THIS_TEST_REL = "tests/test_iter227_behavior.py"


# --------------------------------------------------------------------------- helpers


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _case(case_id, text, expect, parser=SHIP_ACTION_PARSER, source="synthetic", artifact=None):
    """A hand-built GateEvalCase -- Behavior 3 must work with no `evals/` dir at all."""
    data = text.encode("utf-8")
    return foundry.GateEvalCase(
        case_id=case_id,
        parser=parser,
        artifact=artifact or ("ship_action/%s.md" % case_id),
        expect=expect,
        source=source,
        sha256=_sha(data),
        text=text,
    )


def _write_corpus(root: pathlib.Path, entries):
    """Build a throwaway corpus under `root`; `entries` are (case_id, text, overrides...)."""
    gate = root / "evals" / "gate"
    (gate / "ship_action").mkdir(parents=True, exist_ok=True)
    cases = []
    for entry in entries:
        case_id, text = entry[0], entry[1]
        overrides = entry[2] if len(entry) > 2 else {}
        artifact = overrides.get("artifact", "ship_action/%s.md" % case_id)
        data = text.encode("utf-8")
        path = gate / artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        rec = {
            "case_id": case_id,
            "parser": SHIP_ACTION_PARSER,
            "artifact": artifact,
            "expect": overrides.get("expect", "PUSHED"),
            "source": overrides.get("source", "synthetic"),
            "sha256": overrides.get("sha256", _sha(data)),
        }
        for key in ("parser",):
            if key in overrides:
                rec[key] = overrides[key]
        cases.append(rec)
    (gate / "manifest.json").write_text(
        json.dumps({"version": 1, "cases": cases}, indent=2) + "\n", encoding="utf-8"
    )
    return root


def _shipped():
    return foundry.load_gate_eval_corpus(_ROOT)


def _lines_with(prefix, text):
    return [ln for ln in text.splitlines() if ln.startswith(prefix)]


# =========================================================== Behavior 1 -- the loader


def test_b1_returns_a_tuple_of_gate_eval_cases_sorted_by_case_id():
    cases = _shipped()
    assert isinstance(cases, tuple), "the loader must return a tuple, got %r" % type(cases)
    assert cases, "the shipped corpus must not be empty"
    assert all(isinstance(c, foundry.GateEvalCase) for c in cases)
    ids = [c.case_id for c in cases]
    assert ids == sorted(ids), "cases must come back sorted by case_id, got %r" % (ids,)
    assert len(set(ids)) == len(ids), "case ids must be unique, got %r" % (ids,)
    assert set(SPEC_CASES) <= set(ids), "spec-fixed cases missing: %r" % (
        sorted(set(SPEC_CASES) - set(ids)),
    )


def test_b1_every_specced_case_carries_the_specced_field_values():
    by_id = {c.case_id: c for c in _shipped()}
    for case_id, (expect, source, artifact) in sorted(SPEC_CASES.items()):
        c = by_id[case_id]
        assert isinstance(c.case_id, str) and c.case_id == case_id
        assert isinstance(c.parser, str) and c.parser in foundry.GATE_EVAL_PARSERS, (
            "%s names parser %r which is not a key of GATE_EVAL_PARSERS" % (case_id, c.parser)
        )
        assert c.parser == SHIP_ACTION_PARSER
        assert c.artifact == artifact, "%s artifact %r != spec %r" % (case_id, c.artifact, artifact)
        assert c.expect == expect and (c.expect is None) == (expect is None), (
            "%s expect %r != spec %r" % (case_id, c.expect, expect)
        )
        assert c.source == source
        assert isinstance(c.sha256, str) and len(c.sha256) == 64
        assert c.sha256 == c.sha256.lower() and all(ch in "0123456789abcdef" for ch in c.sha256)
        assert isinstance(c.text, str)


def test_b1_artifact_is_relative_to_the_gate_dir_and_text_is_that_file_decoded():
    for c in _shipped():
        path = EVALS_GATE / c.artifact
        assert path.is_file(), "artifact %r does not resolve under evals/gate/" % (c.artifact,)
        data = path.read_bytes()
        assert c.text == data.decode("utf-8"), "%s text is not the artifact decoded" % c.case_id
        assert c.sha256 == _sha(data), "%s sha256 disagrees with the file on disk" % c.case_id


def test_b1_records_are_frozen():
    c = _shipped()[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.expect = "PUSHED"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.text = ""  # type: ignore[misc]


def test_b1_the_shipped_manifest_has_the_specced_shape():
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    assert doc.get("version") == 1, "manifest version must be 1, got %r" % (doc.get("version"),)
    assert isinstance(doc.get("cases"), list) and doc["cases"], "`cases` must be a non-empty list"
    assert len(doc["cases"]) == len(_shipped()), "one record per manifest entry"


def test_b1_root_may_be_a_str_or_a_path():
    assert foundry.load_gate_eval_corpus(str(_ROOT)) == foundry.load_gate_eval_corpus(_ROOT)


def test_b1_manifest_order_does_not_affect_the_result(tmp_path):
    entries = [
        ("zulu", "ACTION: PUSHED aaa1111\n", {"expect": "PUSHED"}),
        ("alpha", "ACTION: REVERTED -- see detail\n", {"expect": "REVERTED"}),
        ("mike", "no sentinel here\n", {"expect": None}),
    ]
    forward = _write_corpus(tmp_path / "fwd", entries)
    backward = _write_corpus(tmp_path / "bwd", list(reversed(entries)))
    a = foundry.load_gate_eval_corpus(forward)
    b = foundry.load_gate_eval_corpus(backward)
    assert [c.case_id for c in a] == ["alpha", "mike", "zulu"]
    assert a == b, "manifest ORDER changed the loaded corpus"


# =============================================== Behavior 2 -- loud, named rejections


def test_b2_an_unknown_parser_raises_valueerror_naming_the_case_and_the_bad_value(tmp_path):
    bad = "parse_nothing_at_all"
    root = _write_corpus(
        tmp_path, [("pushed-plain", "ACTION: PUSHED abc1234\n", {"parser": bad})]
    )
    with pytest.raises(ValueError) as exc:
        foundry.load_gate_eval_corpus(root)
    msg = str(exc.value)
    assert "pushed-plain" in msg, "the message must name the offending case_id: %r" % msg
    assert bad in msg, "the message must name the bad value: %r" % msg


def test_b2_a_sha_mismatch_raises_valueerror_naming_the_case_and_the_bad_value(tmp_path):
    bad = "0" * 64
    root = _write_corpus(
        tmp_path, [("reverted-plain", "ACTION: REVERTED\n", {"sha256": bad, "expect": "REVERTED"})]
    )
    with pytest.raises(ValueError) as exc:
        foundry.load_gate_eval_corpus(root)
    msg = str(exc.value)
    assert "reverted-plain" in msg, "the message must name the offending case_id: %r" % msg
    assert bad in msg, "the message must name the bad value: %r" % msg


def test_b2_control_the_same_corpus_loads_cleanly_once_the_defect_is_removed(tmp_path):
    """Two-sided: the rejections above must come from the DEFECT, not from the fixture."""
    root = _write_corpus(tmp_path, [("pushed-plain", "ACTION: PUSHED abc1234\n")])
    cases = foundry.load_gate_eval_corpus(root)
    assert [c.case_id for c in cases] == ["pushed-plain"]
    assert cases[0].parser in foundry.GATE_EVAL_PARSERS


# ================================================ Behavior 3 -- the pure replay engine


def test_b3_results_come_back_in_the_iterables_own_order_not_sorted():
    order = ["zulu", "alpha", "mike"]
    cases = [_case(cid, "ACTION: PUSHED abc1234\n", "PUSHED") for cid in order]
    results = foundry.replay_gate_evals(cases)
    assert isinstance(results, tuple)
    assert [r.case_id for r in results] == order, "replay must preserve the iterable's own order"


def test_b3_accepts_any_iterable_including_a_generator_and_a_tuple():
    cases = [_case("a", "ACTION: PUSHED abc1234\n", "PUSHED"), _case("b", "nothing\n", None)]
    from_list = foundry.replay_gate_evals(cases)
    from_tuple = foundry.replay_gate_evals(tuple(cases))
    from_gen = foundry.replay_gate_evals(c for c in cases)
    assert from_list == from_tuple == from_gen
    assert foundry.replay_gate_evals([]) == ()


def test_b3_actual_is_the_named_parser_applied_to_the_text_and_ok_is_the_comparison():
    parser = foundry.GATE_EVAL_PARSERS[SHIP_ACTION_PARSER]
    text = "detail line\nACTION: PUSHED abc1234\n"
    hit = foundry.replay_gate_evals([_case("hit", text, "PUSHED")])[0]
    assert hit.actual == parser(text)
    assert hit.expect == "PUSHED" and hit.ok is True
    miss = foundry.replay_gate_evals([_case("miss", text, "REVERTED")])[0]
    assert miss.actual == parser(text) == "PUSHED"
    assert miss.expect == "REVERTED" and miss.ok is False, "ok must be the comparison, not a constant"
    none_case = foundry.replay_gate_evals([_case("none", "no sentinel\n", None)])[0]
    assert none_case.actual is None and none_case.ok is True, "a None expectation must be honoured"


def test_b3_results_are_frozen():
    r = foundry.replay_gate_evals([_case("a", "ACTION: PUSHED abc1234\n", "PUSHED")])[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.ok = False  # type: ignore[misc]


def test_b3_is_pure_no_file_subprocess_network_or_clock_access(tmp_path, monkeypatch):
    """Every I/O seam raises and the CWD has no `evals/` -- yet replay still answers."""
    cases = [
        _case("a", "ACTION: PUSHED abc1234\n", "PUSHED"),
        _case("b", "ACTION: PENDING (checkpoint)\n", None),
        _case("c", "ACTION: REVERTED -- blocker\n", "REVERTED"),
    ]
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "evals").exists()

    def _boom(*a, **k):  # pragma: no cover -- must never run
        raise AssertionError("replay_gate_evals performed I/O")

    monkeypatch.setattr(builtins, "open", _boom)
    monkeypatch.setattr(pathlib.Path, "read_text", _boom)
    monkeypatch.setattr(pathlib.Path, "read_bytes", _boom)
    monkeypatch.setattr(pathlib.Path, "open", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "check_output", _boom)
    monkeypatch.setattr(time, "time", _boom)
    monkeypatch.setattr(time, "monotonic", _boom)
    monkeypatch.setattr(time, "sleep", _boom)
    if hasattr(foundry, "subprocess"):
        monkeypatch.setattr(foundry.subprocess, "run", _boom, raising=False)
    try:
        results = foundry.replay_gate_evals(cases)
        snapshot = [(r.case_id, r.expect, r.actual, r.ok) for r in results]
    finally:
        monkeypatch.undo()
    assert snapshot == [
        ("a", "PUSHED", "PUSHED", True),
        ("b", None, None, True),
        ("c", "REVERTED", "REVERTED", True),
    ]


# ======================================= Behavior 4 -- the SHIPPED corpus, and a control


def test_b4_shipped_corpus_replays_ok_for_every_case():
    results = foundry.replay_gate_evals(_shipped())
    assert results, "the shipped corpus produced no results"
    bad = [(r.case_id, r.expect, r.actual) for r in results if not r.ok]
    assert bad == [], "shipped gate-eval corpus mismatches (case, expect, actual): %r" % (bad,)
    assert all(r.parser in foundry.GATE_EVAL_PARSERS for r in results)


def test_b4_control_flipping_every_expectation_turns_every_result_red():
    """Behavior 4 cannot be vacuously green: `ok` is computed, not a constant, and the
    corpus really does discriminate.  Nothing on disk is touched -- the flip is in memory."""
    flip = {"PUSHED": "REVERTED", "REVERTED": None, None: "PUSHED"}
    wrong = [dataclasses.replace(c, expect=flip[c.expect]) for c in _shipped()]
    results = foundry.replay_gate_evals(wrong)
    assert results, "no cases to control against"
    assert [r.ok for r in results] == [False] * len(results), (
        "a WRONG expectation stayed green -- behavior 4 is vacuous: %r"
        % ([(r.case_id, r.expect, r.actual, r.ok) for r in results],)
    )


# ================================================ Behavior 5 -- the NON-VACUITY FLOOR


def test_b5_the_shipped_corpus_meets_every_non_vacuity_floor():
    cases = _shipped()
    assert len(cases) >= MIN_CASES, "corpus holds %d case(s), floor is %d" % (
        len(cases), MIN_CASES,
    )
    real = [c for c in cases if c.source == "real"]
    assert len(real) >= MIN_REAL_CASES, "only %d real case(s), floor is %d" % (
        len(real), MIN_REAL_CASES,
    )
    assert all(c.source in ("real", "synthetic") for c in cases)
    expects = {c.expect for c in cases}
    for value in REQUIRED_EXPECT_VALUES:
        assert value in expects, (
            "expect value %r is absent, so the corpus cannot exercise that verdict" % (value,)
        )
    for c in cases:
        path = EVALS_GATE / c.artifact
        assert path.is_file(), "%s artifact %r is not a file" % (c.case_id, c.artifact)
        assert path.read_bytes(), "%s artifact %r is empty" % (c.case_id, c.artifact)


def test_b5_control_each_floor_rejects_a_corpus_that_violates_it():
    """The floor predicates are exercised against DELIBERATELY short corpora, so a future
    corpus that shrinks below any floor is provably caught rather than assumed to be."""
    cases = _shipped()
    thin = cases[:1]
    assert not len(thin) >= MIN_CASES
    assert not len([c for c in thin if c.source == "real"]) >= MIN_REAL_CASES
    pushed_only = tuple(c for c in cases if c.expect == "PUSHED")
    expects = {c.expect for c in pushed_only}
    assert pushed_only, "the shipped corpus has no PUSHED case to build the control from"
    missing = [v for v in REQUIRED_EXPECT_VALUES if v not in expects]
    assert missing, "a PUSHED-only corpus must violate the expect-coverage floor"
    assert not (EVALS_GATE / "ship_action" / "no-such-artifact.md").is_file()


# ==================================================== Behavior 6 -- proven DORMANCY


def test_b6_neither_new_helper_has_a_call_site_anywhere_in_foundry():
    """Dormant-additive: with zero call sites, no prompt, artifact, exit code or resume
    path can change this iteration."""
    src = FOUNDRY_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    # ANTI-VACUITY: "zero call sites" is trivially true for a name that does not exist --
    # measured, this very assertion passes against a pre-227 tree.  So first demand that
    # each helper IS defined exactly once at module level; only then is the count of zero
    # a statement about a shipped function.
    defined = [
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in NEW_NAMES
    ]
    for name in NEW_NAMES:
        assert defined.count(name) == 1, (
            "%s must be defined exactly once at module level in foundry.py, found %d"
            % (name, defined.count(name))
        )
    called = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name in NEW_NAMES:
            called.append((name, getattr(node, "lineno", -1)))
    assert called == [], "the new helpers must stay dormant, found call sites: %r" % (called,)


def test_b6_control_the_ast_walk_really_would_see_a_call_site():
    """The walk above is only meaningful if it can FIND a call -- prove it on a sample."""
    sample = "def f():\n    return load_gate_eval_corpus('.')\n"
    tree = ast.parse(sample)
    hits = [
        getattr(n.func, "id", None)
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) in NEW_NAMES
    ]
    assert hits == ["load_gate_eval_corpus"]


def test_b6_both_helpers_exist_and_both_modules_still_import():
    for name in NEW_NAMES:
        assert callable(getattr(foundry, name)), "%s must be a public callable" % name
    assert isinstance(foundry.GATE_EVAL_PARSERS, dict) and foundry.GATE_EVAL_PARSERS
    assert foundry.GATE_EVAL_PARSERS[SHIP_ACTION_PARSER] is foundry.parse_ship_action
    assert foundry.__name__ == "foundry"
    assert dispatcher.__name__ == "dispatcher"
    assert hasattr(foundry, "build_prompt") and hasattr(foundry, "run_stage")


# ================================ Acceptance criteria A/B -- tracked-text-only guards


def test_a_the_roadmap_record_ships_in_this_same_diff():
    index = INDEX_PATH.read_text(encoding="utf-8")
    archive = ARCHIVE_PATH.read_text(encoding="utf-8")
    rows = _lines_with(LEDGER_ROW_PREFIX, index)
    assert len(rows) == 1, "expected exactly one %r ledger row, found %d" % (
        LEDGER_ROW_PREFIX, len(rows),
    )
    assert len(rows[0]) <= LEDGER_ROW_MAX_CHARS, "ledger row is %d chars (max %d)" % (
        len(rows[0]), LEDGER_ROW_MAX_CHARS,
    )
    bullets = _lines_with(ARCHIVE_BULLET_PREFIX, archive)
    assert len(bullets) == 1, "expected exactly one %r archive bullet, found %d" % (
        ARCHIVE_BULLET_PREFIX, len(bullets),
    )
    assert foundry.roadmap_ledger_gaps(index, archive, (THIS_ITER,)) == []


def test_a_control_the_ledger_brake_is_two_sided():
    """Strip this iteration's record from IN-MEMORY copies and the oracle must FLIP.

    MEASURED oracle semantics (found by feeding it each side separately, not assumed):
    `roadmap_ledger_gaps` is an OR over the two files -- it reports a gap only when BOTH
    the index row AND the archive bullet are absent, so stripping one side alone leaves it
    green.  That is why the presence assertions in `test_a_...` above count EACH file's
    line separately: the shipped brake alone would accept a record that landed in only one
    of them, which is exactly the state iteration 194 shipped BROKEN in.
    """
    index = INDEX_PATH.read_text(encoding="utf-8")
    archive = ARCHIVE_PATH.read_text(encoding="utf-8")
    index_gone = "\n".join(
        ln for ln in index.splitlines() if not ln.startswith(LEDGER_ROW_PREFIX)
    )
    archive_gone = "\n".join(
        ln for ln in archive.splitlines() if not ln.startswith(ARCHIVE_BULLET_PREFIX)
    )
    assert LEDGER_ROW_PREFIX not in index_gone and ARCHIVE_BULLET_PREFIX not in archive_gone, \
        "the strip helpers did not remove the record they target"
    assert foundry.roadmap_ledger_gaps(index_gone, archive_gone, (THIS_ITER,)) == [THIS_ITER]
    # And the OR is real, in both directions -- documented, not assumed.
    assert foundry.roadmap_ledger_gaps(index_gone, archive, (THIS_ITER,)) == []
    assert foundry.roadmap_ledger_gaps(index, archive_gone, (THIS_ITER,)) == []


def test_a_the_index_is_inside_the_budget_its_own_helper_reports():
    budget = foundry.roadmap_index_budget(INDEX_PATH.read_text(encoding="utf-8"))
    assert not budget.over_budget, "roadmap index over budget: %r" % (budget,)
    assert not budget.near_wall, "roadmap index inside the near-wall margin: %r" % (budget,)


def test_b_this_file_is_in_the_b15_allow_list():
    owner = ALLOW_LIST_OWNER.read_text(encoding="utf-8")
    assert '"%s"' % THIS_TEST_REL in owner, (
        "%s must be allow-listed in %s, or `git add -A` at the gate makes it an "
        "unexpected diff member" % (THIS_TEST_REL, ALLOW_LIST_OWNER.name)
    )


# ================ Behavior 5 (extended) -- the corpus must really DISCRIMINATE
#
# Behaviors 4 and 5 as written are satisfiable by a DEGENERATE corpus: `ok` is True for any
# artifact whose parse happens to equal its own recorded `expect`, and the floors above count
# cases without auditing what is in them.  Four blank files labelled `expect: null` would
# clear every floor except expect-coverage.  These tests audit the CONTENT, driven by the
# spec's own `why` column (`## The corpus`), so a future corpus cannot decay into a shape
# that exercises nothing -- the exact failure iteration 227's scout measured in
# `roadmap_verb_figure_gaps`, which was green from birth because its subject was gone.

LEAK_GUARD_PATH = _ROOT / "scripts" / "leak_guard.py"
MIN_ARTIFACT_BYTES = 200
PUSHED_SENTINEL_RE = re.compile(r"^ACTION: PUSHED [0-9a-f]{7,40}$")
ACTION_PREFIX = "ACTION:"
RECOGNIZED_TOKENS = ("PUSHED", "REVERTED")


def _non_empty_lines(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines, "artifact is blank"
    return lines


def _action_lines(text):
    return [ln for ln in text.splitlines() if ln.startswith(ACTION_PREFIX)]


def _check_pushed_plain(text):
    """`why`: the happy path -- a real PUSHED sentinel as the LAST non-empty line."""
    last = _non_empty_lines(text)[-1]
    assert PUSHED_SENTINEL_RE.match(last), (
        "pushed-plain must end with a real `ACTION: PUSHED <sha>` sentinel, got %r" % last
    )


def _check_reverted_plain(text):
    """`why`: an honest revert -- a real REVERTED sentinel as the LAST non-empty line."""
    last = _non_empty_lines(text)[-1]
    assert last.startswith("ACTION: REVERTED"), (
        "reverted-plain must end with an `ACTION: REVERTED` sentinel, got %r" % last
    )


def _check_none_unrecognized_token(text):
    """`why`: GAP-006 in the wild -- a sentinel IS present, its token is just not one the
    gate recognizes.  Both halves matter: without an ACTION line this case would be a
    duplicate of `none-no-action-line` and the corpus would cover one hazard, not two."""
    actions = _action_lines(text)
    assert actions, (
        "none-unrecognized-token must CARRY an ACTION line -- with none it duplicates "
        "none-no-action-line and the corpus loses a distinct hazard"
    )
    for ln in actions:
        rest = ln[len(ACTION_PREFIX):].strip()
        token = rest.split()[0] if rest.split() else ""
        assert token not in RECOGNIZED_TOKENS, (
            "none-unrecognized-token carries a RECOGNIZED token %r (%r), so it no longer "
            "represents an unparseable verdict" % (token, ln)
        )


def _check_none_no_action_line(text):
    """`why`: a cap-killed checkpoint with no sentinel at all."""
    actions = _action_lines(text)
    assert actions == [], (
        "none-no-action-line must carry NO ACTION line at all, found %r" % (actions,)
    )


SHAPE_CHECKS = {
    "pushed-plain": _check_pushed_plain,
    "reverted-plain": _check_reverted_plain,
    "none-unrecognized-token": _check_none_unrecognized_token,
    "none-no-action-line": _check_none_no_action_line,
}


def test_b5_every_specced_case_has_a_shape_check_and_every_shape_check_holds():
    assert set(SHAPE_CHECKS) == set(SPEC_CASES), (
        "every spec-fixed case needs a content check, mismatch: %r"
        % (sorted(set(SHAPE_CHECKS) ^ set(SPEC_CASES)),)
    )
    by_id = {c.case_id: c for c in _shipped()}
    for case_id, check in sorted(SHAPE_CHECKS.items()):
        assert case_id in by_id, "spec-fixed case %r is absent from the corpus" % case_id
        check(by_id[case_id].text)


def test_b5_control_each_shape_check_rejects_the_wrong_artifact():
    """Two-sided: a shape check that accepts anything proves nothing.  Feed each checker an
    artifact it must REJECT and require it to raise."""
    by_id = {c.case_id: c.text for c in _shipped()}
    wrong_for = {
        "pushed-plain": "none-no-action-line",
        "reverted-plain": "pushed-plain",
        "none-unrecognized-token": "none-no-action-line",
        "none-no-action-line": "pushed-plain",
    }
    for case_id, other_id in sorted(wrong_for.items()):
        with pytest.raises(AssertionError):
            SHAPE_CHECKS[case_id](by_id[other_id])


def test_b5_the_shipped_corpus_drives_the_parser_to_all_three_real_verdicts():
    """The POINT of the iteration (GAP-006 evidence): tracked, real inputs that make the
    ship-action gate answer PUSHED, REVERTED and -- destructively -- None."""
    results = foundry.replay_gate_evals(_shipped())
    actual_of_passing = {r.actual for r in results if r.ok}
    for value in REQUIRED_EXPECT_VALUES:
        assert value in actual_of_passing, (
            "no shipped case makes the parser actually answer %r, so that verdict is "
            "recorded but never exercised; actuals seen: %r" % (value, actual_of_passing)
        )


def test_b5_manifest_integrity_fields_agree_with_the_bytes_on_disk():
    """Self-verifying corpus: every declared sha256 (non-optional, so this loop always does
    real work) and every declared `bytes` (present today, treated as optional) must match the
    file.  A byte floor catches decay into a stub, without pinning a frozen size -- the spec
    table's own `1770` for pushed-plain disagrees with its 7,906 total and the real 1,786."""
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for rec in doc["cases"]:
        path = EVALS_GATE / rec["artifact"]
        assert path.is_file(), "manifest names a missing artifact %r" % (rec["artifact"],)
        data = path.read_bytes()
        assert len(data) >= MIN_ARTIFACT_BYTES, (
            "%s is only %d bytes (floor %d) -- a stub cannot exercise a parser"
            % (rec["case_id"], len(data), MIN_ARTIFACT_BYTES)
        )
        assert rec["sha256"] == _sha(data), (
            "%s declares sha256 %r but the file hashes to %r"
            % (rec["case_id"], rec["sha256"], _sha(data))
        )
        if "bytes" in rec:
            assert rec["bytes"] == len(data), (
                "%s declares %r bytes, file is %d" % (rec["case_id"], rec["bytes"], len(data))
            )


def test_b5_the_shipped_corpus_is_leak_clean():
    """Acceptance criterion, kept live for every FUTURE case too: real artifacts captured
    from a developer machine are exactly the kind of file that carries an absolute home path,
    and this corpus is the first tracked data in the repo copied verbatim from gitignored
    runtime state."""
    # Registering in sys.modules BEFORE exec_module is required, not decorative: the
    # module defines a dataclass and `dataclasses` resolves its annotations through
    # `sys.modules[cls.__module__]`.  Same shape as tests/test_iter213_behavior.py.
    spec = importlib.util.spec_from_file_location("leak_guard_iter227_probe", LEAK_GUARD_PATH)
    lg = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = lg
    try:
        spec.loader.exec_module(lg)
    except Exception:  # pragma: no cover -- do not leave a half-built module behind
        sys.modules.pop(spec.name, None)
        raise
    patterns = lg.load_denylist(lg.DENYLIST_PATH.read_text(encoding="utf-8"))
    assert patterns, "the denylist compiled to ZERO patterns -- the scan would be vacuous"
    paths = [str(MANIFEST)] + [str(EVALS_GATE / c.artifact) for c in _shipped()]
    findings, scanned, missing = lg.scan_paths(paths, patterns)
    assert missing == (), "leak scan could not read %r" % (missing,)
    assert scanned == len(paths), (
        "leak scan read %d of %d corpus files -- a skipped file is an unscanned file"
        % (scanned, len(paths))
    )
    assert findings == (), "leak-guard findings in the shipped corpus: %r" % (findings,)
