"""Iteration 242 -- BLACK-BOX behavior tests for `RESULT: BLOCKED`, a THIRD tester
disposition: routed like the unfinished-round case (no repair round) and honoured by
the ship gate under four conjunctive conditions, so a green, record-only,
legitimately blocked iteration ships its records instead of being destroyed.

Spec under test: products/_platform/state/iter-242/pm.md, Expected Behaviors 1-7:

  1. `parse_tester_result` accepts a THIRD token; PASS/FAIL unchanged; the other two
     sentinel channels do NOT gain it.
  2. `classify_test_report` returns the new verdict `"BLOCKED"`.
  3. Precedence is explicit and the CHECKPOINT MARKER OUTRANKS BLOCKED; the function
     stays TOTAL.
  4. Routing is BYTE-IDENTICAL for every disposition that exists today and a BLOCKED
     round buys NO repair round.
  5. Both I/O seams report BLOCKED, and their fail-closed degradation is unchanged.
  6. `roles/tester.md` documents the third token and its USE RULE, still pure ASCII.
  7. `roles/final.md` gate checklist item 2 carries the BLOCKED branch with all four
     conjunctive conditions, and every existing pin on that card still holds.

ISOLATION CONTRACT (HONORED): written ONLY from that PM spec, the conventions already
established under `tests/` (the `_report` / `_dir_with` report builders of
`tests/test_iter180_behavior.py`, the item-2 slice probe of its `test_b17`, and the
sentinel triples of `tests/test_iter201_behavior.py`), and the product's OWN
OBSERVABLE surface -- importing `foundry`, calling its public functions on synthetic
in-process strings and `tmp_path` fixtures, plus reading the two ROLE CARDS whose
TEXT the spec makes an Expected Behavior (6 and 7).  I did NOT read the implementation
source of `foundry.py` / `dispatcher.py`, nor `engineer.md`, `reviewer.md`,
`fix_review.md`, nor any `git diff`.

Every fixture is a synthetic string or a path under `tmp_path`: no subprocess, no git,
no network, no reliance on ambient (gitignored) state, and no absolute machine path or
personal identifier anywhere (OPERATOR 2026-08-11 / iteration 205).
"""

import itertools
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

MARKER = "PROGRESS: CHECKPOINT"

# The three dispositions that existed BEFORE this iteration, with the routing answer
# each one is contractually owed.  Frozen here so a regression is a diff, not a guess.
LEGACY_ROUTING = {
    "UNFINISHED": True,
    "RED": True,
    "PASS": False,
    "NONE": False,
}


def _body(verdict, *, prose="some prose", marker=False, trailing=True):
    """A realistic tester report whose LAST non-empty line is the sentinel.

    Mirrors `_report` in tests/test_iter180_behavior.py: multi-line detail ABOVE the
    sentinel, optional whitespace-only trailing lines below it.
    """
    lines = ["test report", "", prose]
    if marker:
        lines += ["", MARKER, "still missing: the full-suite run"]
    lines += ["", f"RESULT: {verdict}"]
    text = "\n".join(lines) + "\n"
    if trailing:
        text += "\n   \n\t\n"
    return text


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _dir_with(base, **reports):
    """tmp dir holding {report-name: verdict}; keys use `_` for `.` (tester2_md)."""
    d = pathlib.Path(base) / "iter"
    d.mkdir(parents=True, exist_ok=True)
    for key, verdict in reports.items():
        _write(d / key.replace("_md", ".md"), _body(verdict))
    return d


# =========================================================== Behavior 1: the parser
def test_b1_blocked_is_the_third_tester_token():
    """Behavior 1 -- the plain case, and the same case inside a real report body."""
    assert foundry.parse_tester_result("RESULT: BLOCKED") == "BLOCKED"
    assert foundry.parse_tester_result(_body("BLOCKED")) == "BLOCKED"


@pytest.mark.parametrize("text", [
    "RESULT: BLOCKED",
    "RESULT: BLOCKED\n",
    "  RESULT:  BLOCKED  ",
    "  RESULT:  BLOCKED  \n",
    "RESULT:BLOCKED",
    "RESULT:BLOCKED\n",
    "\tRESULT:\tBLOCKED\t\n",
    "detail line\n\nRESULT: BLOCKED\n\n   \n\t\n",
    "RESULT: BLOCKED\n\n\n",
])
def test_b1_blocked_tolerates_indentation_padding_and_trailing_blanks(text):
    """Behavior 1 -- indentation, padding, no space at all, trailing blank lines."""
    assert foundry.parse_tester_result(text) == "BLOCKED", repr(text)


def test_b1_the_two_original_tokens_are_unchanged():
    """Behavior 1 -- PASS and FAIL still parse to themselves, plain and in a body."""
    assert foundry.parse_tester_result("RESULT: PASS") == "PASS"
    assert foundry.parse_tester_result("RESULT: FAIL") == "FAIL"
    assert foundry.parse_tester_result(_body("PASS")) == "PASS"
    assert foundry.parse_tester_result(_body("FAIL")) == "FAIL"
    assert foundry.parse_tester_result("  RESULT:  PASS  \n") == "PASS"
    assert foundry.parse_tester_result("RESULT:FAIL\n") == "FAIL"


@pytest.mark.parametrize("text", [
    "RESULT: blocked",
    "RESULT: Blocked",
    "RESULT: BLOCKED extra",
    "RESULT: BLOCKED FAIL",
    "RESULT: BLOCKEDD",
    "RESULT:",
    "RESULT: ",
    "RESULT: MAYBE",
    "",
    "\n\n   \n",
    "RESULT: BLOCKED\nand then some prose about why\n",
    "BLOCKED",
    "VERDICT: BLOCKED",
])
def test_b1_near_misses_return_none_and_never_raise(text):
    """Behavior 1 -- the parser is TOTAL: every near miss is None, not an exception."""
    assert foundry.parse_tester_result(text) is None, repr(text)


def test_b1_the_other_two_channels_do_not_gain_the_token():
    """Behavior 1 -- BLOCKED belongs to the TESTER channel only."""
    assert foundry.parse_review_verdict("RESULT: BLOCKED") is None
    assert foundry.parse_review_verdict("VERDICT: BLOCKED") is None
    assert foundry.parse_review_verdict(_body("BLOCKED")) is None
    assert foundry.parse_postrelease_verdict("RESULT: BLOCKED") is None
    assert foundry.parse_postrelease_verdict("POSTRELEASE: BLOCKED") is None
    assert foundry.parse_postrelease_verdict("all checks ran\n\nBLOCKED\n") is None
    # ...and their own tokens are untouched by this iteration.
    assert foundry.parse_review_verdict("VERDICT: APPROVE") == "APPROVE"
    assert foundry.parse_review_verdict("VERDICT: CHANGES_REQUIRED") == "CHANGES_REQUIRED"
    assert foundry.parse_postrelease_verdict("POSTRELEASE: HEALTHY") == "HEALTHY"
    assert foundry.parse_postrelease_verdict("POSTRELEASE: BROKEN") == "BROKEN"


# ================================================ Behavior 2: the new classification
def test_b2_classify_reports_blocked_for_an_unmarked_blocked_body():
    """Behavior 2 -- an unmarked BLOCKED report classifies as the new verdict."""
    assert foundry.classify_test_report(_body("BLOCKED")) == "BLOCKED"
    assert foundry.classify_test_report("RESULT: BLOCKED") == "BLOCKED"
    assert foundry.classify_test_report("RESULT:BLOCKED\n\n  \n") == "BLOCKED"


def test_b2_a_mid_line_checkpoint_word_does_not_outrank_blocked():
    """Behavior 2 -- the marker must appear at a LINE START to outrank BLOCKED, so a
    report that merely MENTIONS the marker inside a sentence still classifies BLOCKED."""
    mid = f"the round was fine ({MARKER} was not needed)\n\nRESULT: BLOCKED\n"
    assert foundry.classify_test_report(mid) == "BLOCKED"


def test_b2_blocked_inherits_the_pre_existing_marker_indentation_rule():
    """Behavior 2/3 -- AMBIGUITY RESOLVED BY THE LEGACY TWIN (noted in tester.md): an
    INDENTED marker already counted as "at a line start" for `RESULT: FAIL` before this
    iteration, so BLOCKED must be treated IDENTICALLY rather than more strictly.  The
    assertion is the EQUALITY of the two, which is what "byte-identical routing" means."""
    for pad in ("   ", "\t"):
        fail_body = f"{pad}{MARKER}\n\nRESULT: FAIL\n"
        blocked_body = f"{pad}{MARKER}\n\nRESULT: BLOCKED\n"
        assert foundry.classify_test_report(fail_body) == "UNFINISHED", repr(pad)
        assert (foundry.classify_test_report(blocked_body)
                == foundry.classify_test_report(fail_body)), repr(pad)


# ================================================== Behavior 3: explicit precedence
def test_b3_an_earned_pass_outranks_the_marker():
    """Behavior 3 -- PASS wins even when the checkpoint marker is present."""
    assert foundry.classify_test_report(_body("PASS", marker=True)) == "PASS"
    assert foundry.classify_test_report(f"{MARKER}\n\nRESULT: PASS\n") == "PASS"


def test_b3_the_marker_outranks_blocked():
    """Behavior 3 -- a cap-killed round keeps buying its retry rounds; it is never
    read as a CONSIDERED block."""
    assert foundry.classify_test_report(_body("BLOCKED", marker=True)) == "UNFINISHED"
    assert foundry.classify_test_report(f"{MARKER}\n\nRESULT: BLOCKED\n") == "UNFINISHED"
    # the marker also still outranks FAIL (the pre-existing contract)
    assert foundry.classify_test_report(_body("FAIL", marker=True)) == "UNFINISHED"


def test_b3_unmarked_fail_is_red_and_unrecognised_is_none():
    """Behavior 3 -- the two legacy tails of the precedence chain are unchanged."""
    assert foundry.classify_test_report(_body("FAIL")) == "RED"
    assert foundry.classify_test_report("RESULT: FAIL") == "RED"
    assert foundry.classify_test_report("") == "NONE"
    assert foundry.classify_test_report("just prose, no sentinel\n") == "NONE"
    assert foundry.classify_test_report("RESULT: MAYBE") == "NONE"
    assert foundry.classify_test_report("RESULT: blocked") == "NONE"
    assert foundry.classify_test_report("RESULT: BLOCKED then prose\n") == "NONE"


def test_b3_classify_is_total_over_a_generated_corpus():
    """Behavior 3 -- it remains TOTAL: no input raises, and every answer is one of
    the five recognised verdicts."""
    allowed = {"PASS", "FAIL", "BLOCKED", "MAYBE", "blocked", "", "  "}
    pieces = ["", "RESULT:", "RESULT: ", MARKER, "\n", "  ", "prose", "\t"]
    verdicts = {"PASS", "RED", "UNFINISHED", "BLOCKED", "NONE"}
    for combo in itertools.product(pieces, repeat=3):
        for tok in sorted(allowed):
            text = "".join(combo) + tok
            got = foundry.classify_test_report(text)
            assert got in verdicts, f"{text!r} -> {got!r}"


# ================================================ Behavior 4: routing is unchanged
def test_b4_a_blocked_round_buys_no_repair_round():
    """Behavior 4 -- the whole point: BLOCKED is NOT a repair trigger."""
    assert foundry.needs_test_repair("BLOCKED") is False


def test_b4_the_repair_disposition_tuple_is_byte_identical():
    """Behavior 4 -- unchanged tuple, unchanged ORDER, still a tuple of str."""
    assert foundry.TEST_GATE_REPAIR_DISPOSITIONS == ("UNFINISHED", "RED")
    assert isinstance(foundry.TEST_GATE_REPAIR_DISPOSITIONS, tuple)
    assert all(isinstance(x, str) for x in foundry.TEST_GATE_REPAIR_DISPOSITIONS)
    assert "BLOCKED" not in foundry.TEST_GATE_REPAIR_DISPOSITIONS


@pytest.mark.parametrize("disposition,want", sorted(LEGACY_ROUTING.items()))
def test_b4_every_pre_existing_disposition_routes_exactly_as_before(disposition, want):
    """Behavior 4 -- routing is BYTE-IDENTICAL for every disposition that exists."""
    assert foundry.needs_test_repair(disposition) is want


@pytest.mark.parametrize("disposition", [
    "", "MAYBE", "BLOCKED", "blocked", "unfinished", "red", "PASSED", " RED ",
])
def test_b4_needs_test_repair_answers_true_for_exactly_two_tokens(disposition):
    """Behavior 4 -- fail-closed only for the two named tokens; everything else is
    False, and the predicate never raises."""
    assert foundry.needs_test_repair(disposition) is False, repr(disposition)


# ==================================================== Behavior 5: the two I/O seams
def test_b5_read_test_disposition_reports_blocked(tmp_path):
    """Behavior 5 -- the file-reading seam surfaces the new verdict."""
    p = _write(tmp_path / "tester.md", _body("BLOCKED"))
    assert foundry.read_test_disposition(p) == "BLOCKED"


def test_b5_read_test_disposition_still_degrades_fail_closed(tmp_path):
    """Behavior 5 -- a missing or unreadable path is STILL RED, not BLOCKED."""
    assert foundry.read_test_disposition(tmp_path / "absent.md") == "RED"
    a_dir = tmp_path / "a_directory.md"
    a_dir.mkdir()
    assert foundry.read_test_disposition(a_dir) == "RED"
    # and the two legacy readings are unchanged
    assert foundry.read_test_disposition(
        _write(tmp_path / "good.md", _body("PASS"))) == "PASS"
    assert foundry.read_test_disposition(
        _write(tmp_path / "red.md", _body("FAIL"))) == "RED"
    assert foundry.read_test_disposition(
        _write(tmp_path / "cut.md", _body("FAIL", marker=True))) == "UNFINISHED"


def test_b5_read_authoritative_tester_result_reports_blocked(tmp_path):
    """Behavior 5 -- the single-report case."""
    d = _dir_with(tmp_path, tester_md="BLOCKED")
    assert foundry.read_authoritative_tester_result(d) == "BLOCKED"


def test_b5_the_newest_report_decides_in_both_directions(tmp_path):
    """Behavior 5 -- FAIL then BLOCKED is BLOCKED; BLOCKED then FAIL is FAIL."""
    fail_then_blocked = _dir_with(tmp_path / "a", tester_md="FAIL", tester2_md="BLOCKED")
    assert foundry.read_authoritative_tester_result(fail_then_blocked) == "BLOCKED"
    blocked_then_fail = _dir_with(tmp_path / "b", tester_md="BLOCKED", tester2_md="FAIL")
    assert foundry.read_authoritative_tester_result(blocked_then_fail) == "FAIL"
    three = _dir_with(tmp_path / "c", tester_md="FAIL", tester2_md="PASS",
                      tester3_md="BLOCKED")
    assert foundry.read_authoritative_tester_result(three) == "BLOCKED"
    # an empty dir is still None (presence, not content, selects the report)
    empty = tmp_path / "d" / "iter"
    empty.mkdir(parents=True)
    assert foundry.read_authoritative_tester_result(empty) is None


# ===================================================== Behavior 6: roles/tester.md
def _card(name):
    text = (_ROOT / "roles" / name).read_text()
    text.encode("ascii")            # raises if a non-ASCII byte crept in
    return text


def test_b6_tester_card_names_all_three_tokens_and_stays_ascii():
    """Behavior 6 -- the final-line instruction enumerates the three tokens."""
    text = _card("tester.md")
    for token in ("RESULT: PASS", "RESULT: FAIL", "RESULT: BLOCKED"):
        assert token in text, token


def test_b6_tester_card_states_the_use_rule_for_blocked():
    """Behavior 6 -- the card must say WHEN to emit BLOCKED: no Expected Behavior
    implementable at all, a GREEN full suite, and a round that was NOT cut short
    (a cut-short round emits the checkpoint marker instead)."""
    text = _card("tester.md")
    lowered = text.lower()
    assert "blocked" in lowered
    assert MARKER in text, "the cut-short alternative must be named verbatim"
    assert "expected behavior" in lowered, "must scope BLOCKED to the behaviors"
    assert "green" in lowered, "must require a GREEN full suite"
    assert "cut short" in lowered, "must exclude the cut-short round"


# ====================================================== Behavior 7: roles/final.md
def _final_item2():
    """The gate checklist item-2 slice, sliced exactly as tests/test_iter180's
    test_b17 does: from the pinned opening string to the next line starting `3. `."""
    text = _card("final.md")
    assert "2. Tester result is PASS" in text, "the pinned item-2 opening string"
    start = text.index("2. Tester result is PASS")
    end = text.index("\n3. ", start)
    return text, text[start:end]


def test_b7_final_card_pins_still_hold():
    """Behavior 7 -- ASCII, the exact item-2 opening string, and item 2 still names
    the authoritative-report helper (the iteration-180 pin)."""
    text, item2 = _final_item2()
    assert item2.startswith("2. Tester result is PASS")
    assert ("authoritative_tester_report" in item2
            or "read_authoritative_tester_result" in item2), item2
    assert ("authoritative_tester_report" in text
            or "read_authoritative_tester_result" in text)


def test_b7_item2_carries_the_blocked_branch():
    """Behavior 7 -- the branch lives INSIDE item 2, not merely somewhere on the card."""
    _text, item2 = _final_item2()
    assert "BLOCKED" in item2, item2
    assert "RESULT: BLOCKED" in item2, "condition (a): the exact sentinel"


def test_b7_item2_states_all_four_conjunctive_conditions():
    """Behavior 7 -- (a) the sentinel, (b) item 1 still holds, (c) item 3's suite is
    green, (d) the change set is RECORD-ONLY, named by the two commands that measure
    it and by the excluded shapes."""
    _text, item2 = _final_item2()
    lowered = item2.lower()
    assert "RESULT: BLOCKED" in item2, "(a)"
    assert "item 1" in lowered, "(b) must point back at item 1"
    assert "item 3" in lowered, "(c) must point at item 3's full-suite run"
    assert "diff HEAD --name-only" in item2, "(d) first measuring command"
    assert "status --porcelain" in item2, "(d) second measuring command"
    for excluded in (".py", "roles/", "scripts/", ".gitignore"):
        assert excluded in item2, f"(d) must exclude {excluded}"
    assert "markdown" in lowered or ".md" in lowered, "(d) record-only shape"


def test_b7_item2_says_a_blocked_tree_failing_d_takes_the_revert_path():
    """Behavior 7 -- BLOCKED must be STRICTLY HARDER than PASS, never a bypass: the
    card states explicitly that a BLOCKED tree failing (d) is a gate FAILURE."""
    _text, item2 = _final_item2()
    assert "REVERTED" in item2 or "revert" in item2.lower(), item2


# ================================================== acceptance-criteria probes
def test_ac_both_modules_still_import():
    """Acceptance criterion: foundry and dispatcher stay importable."""
    import importlib
    assert importlib.import_module("foundry") is foundry
    assert importlib.import_module("dispatcher") is not None


def test_ac_no_absolute_machine_path_literal_in_this_file():
    """Iteration 205 was reverted for exactly one absolute-home-path literal in a new
    test fixture, so this file asserts its OWN cleanliness.  The banned prefixes are
    ASSEMBLED FROM PARTS so that the guard itself contributes no matching literal."""
    src = pathlib.Path(__file__).read_text()
    banned = ("/" + "Users" + "/", "/" + "home" + "/", "/" + "var" + "/folders/")
    for prefix in banned:
        assert src.count(prefix) == 0, prefix
