"""Iteration 216 -- black-box tests: an UNFINISHED checkpoint claim must ANCHOR a line.

SPEC: products/_platform/state/iter-216/pm.md, Expected Behaviors 1-12.

TESTER ISOLATION: written from the spec alone. The implementation source, the
engineer's notes, the reviewer's notes and ``git diff`` were not read in this
stage. Every assertion drives the public interface only --
``carries_unfinished_marker``, ``classify_test_report``,
``read_test_disposition`` -- and asserts an observable return value.

OFFLINE AND HERMETIC: every fixture is a string built in-process from the module
global ``UNFINISHED_TEST_MARKER``, so no fixture hard-codes the marker's current
value. There is no subprocess, git or network call, and the only filesystem use
is ``tmp_path`` for Behavior 11's pre-existing ``read_test_disposition`` seam --
nothing here reads the ambient tree, whose ``products/*/state`` artifacts are
gitignored and absent from a fresh clone (the iteration-154 trap).

WHY NO CORPUS ASSERTION LIVES HERE: the spec's verdict-neutrality claim (748
historical ``tester*.md`` artifacts, zero verdict changes) was re-measured
independently in the tester stage and is reported in ``tester.md``. It is
deliberately NOT a test: its whole input set is gitignored state.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import dispatcher  # noqa: E402,F401  (import-safety probe)
import foundry  # noqa: E402

MARK = foundry.UNFINISHED_TEST_MARKER
VERDICTS = ("PASS", "UNFINISHED", "RED", "NONE")


# ---------------------------------------------------------------- Behavior 1

def test_b1_predicate_exists_at_module_level_and_is_a_pure_bool() -> None:
    """Behavior 1 -- the new predicate is a module-level callable returning bool."""
    fn = getattr(foundry, "carries_unfinished_marker", None)
    assert callable(fn), "carries_unfinished_marker must exist at module level"
    got = fn(f"detail\n{MARK}\nRESULT: FAIL")
    assert got is True, "a marker alone on its own line is a checkpoint claim"


def test_b1_marker_as_the_whole_body_counts() -> None:
    """Behavior 1 -- the degenerate single-line body still counts."""
    assert foundry.carries_unfinished_marker(MARK) is True


# ---------------------------------------------------------------- Behavior 2

@pytest.mark.parametrize(
    "body",
    [
        "## {m}",
        "#{m}",
        "  * {m}",
        "- {m}",
        "> {m}",
        "`{m}`",
        "  > ## **`{m}`**",
        "{m} -- full suite still outstanding",
        "prior line\n   ## {m} -- ran out of clock\nRESULT: FAIL",
    ],
    ids=[
        "heading", "heading_no_space", "bullet_star", "bullet_dash", "blockquote",
        "code_span", "stacked_decoration", "trailing_prose", "embedded_in_report",
    ],
)
def test_b2_decoration_discriminates_the_anchored_rule_from_strict_equality(
        body: str) -> None:
    """Behavior 2 -- the fail-open guard: strict line EQUALITY must NOT be used.

    Every fixture here is False under ``line.strip() == MARK`` and must be True
    under the shipped rule; the spec measured 9 real cap-killed rounds that
    equality would have re-routed to the fix-tests path. The second assertion is
    a self-check on the FIXTURE, so a future edit cannot quietly weaken this test
    into one that both candidate rules satisfy (the spec's own control note found
    the 4 pre-existing classifier modules do exactly that: 300 passed under BOTH).
    """
    text = body.format(m=MARK)
    assert foundry.carries_unfinished_marker(text) is True
    assert MARK not in [ln.strip() for ln in text.splitlines()], (
        "fixture must not be a bare equality match, or it cannot discriminate "
        "the anchored rule from strict equality")


@pytest.mark.parametrize(
    "body",
    ["\t{m}", "{m}   ", "    {m}", "\t  {m}\t "],
    ids=["tab_indent", "trailing_space", "space_indent", "tab_both_sides"],
)
def test_b2_surrounding_whitespace_is_tolerated(body: str) -> None:
    """Behavior 2 -- surrounding whitespace alone.

    Kept SEPARATE from the discriminating cases above on purpose: ``.strip()``
    already absorbs whitespace, so these pass under strict equality too and carry
    none of the prefix-vs-equality load.
    """
    assert foundry.carries_unfinished_marker(body.format(m=MARK)) is True


def test_b2_documented_residual_a_line_start_denial_still_counts() -> None:
    """Behavior 2, disclosed residual: decoration tolerance is deliberately fail-OPEN.

    A sentence that DENIES the marker still counts when the marker OPENS the line
    inside a code span. That follows from the spec naming the backtick as
    tolerated decoration, and it is pinned here so a later narrowing of intent
    breaks a test on purpose instead of silently. Reported as PM feedback.
    """
    body = f"`{MARK}` marker the previous round carried is deliberately absent."
    assert foundry.carries_unfinished_marker(body) is True


# ---------------------------------------------------------------- Behavior 3

@pytest.mark.parametrize(
    "body",
    [
        "the marker `{m}` is correctly ABSENT",
        "the gate will read the verdict I intend, and `{m}` is correctly ABSENT",
        "I will not write {m} in this report.",
        "NOT-{m}",
        "see roles/tester.md for the {m} line contract",
    ],
    ids=["absent_claim", "full_sentence", "refusal", "glued_prefix", "reference"],
)
def test_b3_midline_prose_occurrence_is_not_a_claim(body: str) -> None:
    """Behavior 3 -- a marker discussed mid-line is not a checkpoint claim."""
    assert foundry.carries_unfinished_marker(body.format(m=MARK)) is False


# ---------------------------------------------------------------- Behavior 4

@pytest.mark.parametrize(
    "body",
    ["", "   ", "\n\n\t\n", "all green\nRESULT: PASS", "boom\nRESULT: FAIL"],
    ids=["empty", "spaces", "whitespace_lines", "pass_body", "fail_body"],
)
def test_b4_absent_or_blank_is_false(body: str) -> None:
    """Behavior 4 -- no occurrence at all is False, including blank bodies."""
    assert foundry.carries_unfinished_marker(body) is False


def test_b4_predicate_is_none_safe() -> None:
    """Behavior 4 -- ``text or ""`` handling preserved: None is False, never raising.

    AMBIGUITY NOTE (reported to the PM): Behavior 4 says "None-safe input
    (``text or ""`` handling preserved)" without saying whether the predicate or
    only ``classify_test_report`` absorbs None. Both readings are asserted; the
    stricter one (the predicate itself is total on None) is the one tested here.
    """
    assert foundry.carries_unfinished_marker(None) is False
    assert foundry.classify_test_report(None) == "NONE"


# ---------------------------------------------------------------- Behavior 5

def test_b5_classifier_calls_the_predicate_by_bare_module_name(monkeypatch) -> None:
    """Behavior 5 -- the seam is monkeypatchable, and it moves the verdict BOTH ways."""
    monkeypatch.setattr(foundry, "carries_unfinished_marker", lambda text: True)
    assert foundry.classify_test_report("prose with no token at all") == "UNFINISHED"

    monkeypatch.setattr(foundry, "carries_unfinished_marker", lambda text: False)
    assert foundry.classify_test_report(f"{MARK}\nRESULT: FAIL") == "RED"
    assert foundry.classify_test_report(MARK) == "NONE"


def test_b5_seam_restores_after_monkeypatch() -> None:
    """Behavior 5 control -- the real predicate is back, so the seam test is not sticky."""
    assert foundry.classify_test_report(f"{MARK}\nRESULT: FAIL") == "UNFINISHED"


# ---------------------------------------------------------------- Behavior 6

def test_b6_marker_global_is_read_at_call_time(monkeypatch) -> None:
    """Behavior 6 -- the marker is read from the module global on every call."""
    monkeypatch.setattr(foundry, "UNFINISHED_TEST_MARKER", "HALFWAY-DONE")
    assert foundry.classify_test_report("HALFWAY-DONE\nRESULT: FAIL") == "UNFINISHED"
    assert foundry.classify_test_report(f"{MARK}\nRESULT: FAIL") == "RED"
    assert foundry.carries_unfinished_marker("HALFWAY-DONE") is True
    assert foundry.carries_unfinished_marker(MARK) is False


def test_b6_a_decorated_patched_marker_is_still_anchored(monkeypatch) -> None:
    """Behavior 6 + 2 -- decoration tolerance follows the patched value, not the shipped one."""
    monkeypatch.setattr(foundry, "UNFINISHED_TEST_MARKER", "HALFWAY-DONE")
    assert foundry.carries_unfinished_marker("## HALFWAY-DONE -- tail") is True
    assert foundry.carries_unfinished_marker("mid HALFWAY-DONE line") is False


# ------------------------------------------------------------- Behaviors 7-8

def test_b7_midline_prose_marker_plus_anchored_fail_is_red() -> None:
    """Behavior 7 -- THE behavior change: a prose mention no longer buys retry rounds.

    Verbatim shape of the sharpest real artifact the spec cites: a report stating
    the marker is ABSENT was classified as CARRYING it, and so spent both
    ``UNFINISHED_TEST_RETRY_STAGES`` rounds instead of a fix pass.
    """
    body = (
        "the gate will read the verdict I intend, and "
        f"`{MARK}` is correctly ABSENT\nRESULT: FAIL\n"
    )
    assert foundry.classify_test_report(body) == "RED"


def test_b8_midline_prose_marker_without_a_verdict_is_none() -> None:
    """Behavior 8 -- same prose mention with no recognizable verdict is NONE."""
    body = f"the marker `{MARK}` is correctly ABSENT"
    assert foundry.classify_test_report(body) == "NONE"


# ---------------------------------------------------------------- Behavior 9

@pytest.mark.parametrize(
    "body,expected",
    [
        ("{m}\nRESULT: PASS", "PASS"),
        ("detail\n{m}\nRESULT: FAIL", "UNFINISHED"),
        ("## {m}\nstill running", "UNFINISHED"),
        ("boom\nRESULT: FAIL", "RED"),
        ("hello world", "NONE"),
    ],
    ids=["pass_outranks_marker", "fail_plus_marker", "marker_no_verdict",
         "fail_no_marker", "unrecognizable"],
)
def test_b9_the_five_unchanged_classifications(body: str, expected: str) -> None:
    """Behavior 9 -- the four-step decision order and all four return values hold."""
    assert foundry.classify_test_report(body.format(m=MARK)) == expected


def test_b9_pass_outranks_a_marker_of_any_shape() -> None:
    """Behavior 9 -- an earned PASS beats a checkpoint claim in every decoration shape."""
    for shape in ("{m}", "## {m}", "`{m}`", "- {m} -- tail"):
        body = shape.format(m=MARK) + "\nRESULT: PASS"
        assert foundry.classify_test_report(body) == "PASS", body


# --------------------------------------------------------------- Behavior 10

@pytest.mark.parametrize(
    "text",
    ["", "   ", "\n\n\t\n", "\x00", "x" * 100_000, "\r\n\r\nRESULT: FAIL\r\n"],
    ids=["empty", "spaces", "whitespace", "nul", "long", "crlf_fail"],
)
def test_b10_classifier_stays_total(text: str) -> None:
    """Behavior 10 -- total: one of the four verdicts, never an exception."""
    assert foundry.classify_test_report(text) in VERDICTS


@pytest.mark.parametrize(
    "text",
    ["", "   ", "\n\n\t\n", "\x00", "x" * 100_000, "\r\n\r\nRESULT: FAIL\r\n"],
    ids=["empty", "spaces", "whitespace", "nul", "long", "crlf_fail"],
)
def test_b10_predicate_stays_total(text: str) -> None:
    """Behavior 10 -- the new predicate is total on the same inputs."""
    assert foundry.carries_unfinished_marker(text) in (True, False)


def test_b10_crlf_line_start_marker_is_still_anchored() -> None:
    """Behavior 10 -- CRLF bodies must not defeat the line anchor."""
    assert foundry.carries_unfinished_marker(f"detail\r\n{MARK}\r\n") is True


# --------------------------------------------------------------- Behavior 11

def test_b11_read_test_disposition_is_behaviorally_unchanged(tmp_path) -> None:
    """Behavior 11 -- the reader still maps a real file through the classifier."""
    good = tmp_path / "tester_pass.md"
    good.write_text("all green\nRESULT: PASS\n", encoding="utf-8")
    assert foundry.read_test_disposition(good) == "PASS"

    part = tmp_path / "tester_part.md"
    part.write_text(f"got through 3 behaviors\n{MARK}\nRESULT: FAIL\n", encoding="utf-8")
    assert foundry.read_test_disposition(part) == "UNFINISHED"

    red = tmp_path / "tester_red.md"
    red.write_text("assertion blew up\nRESULT: FAIL\n", encoding="utf-8")
    assert foundry.read_test_disposition(red) == "RED"


def test_b11_read_test_disposition_returns_red_for_an_unreadable_path(tmp_path) -> None:
    """Behavior 11 -- unreadable stays pessimistic: RED for absent path and for a dir."""
    assert foundry.read_test_disposition(tmp_path / "absent.md") == "RED"
    a_dir = tmp_path / "a_dir"
    a_dir.mkdir()
    assert foundry.read_test_disposition(a_dir) == "RED"


def test_b11_the_behavior_change_is_visible_through_the_reader(tmp_path) -> None:
    """Behaviors 7 + 11 -- the new routing reaches the on-disk path the loop uses."""
    p = tmp_path / "tester_prose.md"
    p.write_text(f"the marker `{MARK}` is correctly ABSENT\nRESULT: FAIL\n",
                 encoding="utf-8")
    assert foundry.read_test_disposition(p) == "RED"


# --------------------------------------------------------------- Behavior 12

def test_b12_new_symbol_name_and_docstring_are_ascii_only() -> None:
    """Behavior 12 -- public-repo safety: ASCII-only name and docstring."""
    fn = foundry.carries_unfinished_marker
    assert fn.__name__ == "carries_unfinished_marker"
    assert fn.__name__.isascii()
    doc = fn.__doc__ or ""
    assert doc.strip(), "the new predicate must carry a docstring"
    assert doc.isascii(), "docstring must be ASCII-only"


def test_b12_the_predicate_does_not_self_hit_on_its_own_docstring() -> None:
    """Behavior 12 control -- a docstring that quotes the marker must not claim it.

    Same family as the suffix-census self-hit that reverted an earlier iteration:
    if the new docstring illustrates the marker at a line start, the predicate
    would report a checkpoint claim for any body containing that docstring.
    """
    doc = foundry.carries_unfinished_marker.__doc__ or ""
    assert foundry.carries_unfinished_marker(doc) is False
