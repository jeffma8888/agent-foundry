"""Iteration 243 -- BLACK-BOX behavior tests for SENTENCE-ALIGNED truncation of the
inlined lesson tail: the per-lesson cut lands at the last COMPLETE sentence inside the
SAME cap instead of mid-word, via the new pure `truncate_lesson_at_sentence`.

Spec under test: products/_platform/state/iter-243/pm.md, Expected Behaviors 1-7:

  1. FITS => VERBATIM (no marker), at the exact boundary and for the empty string.
  2. SENTENCE-ALIGNED CUT: the LARGEST sentence end inside `body` at index
     >= `cap // 2` wins, and the result is exactly `body[:i] + MARK`.
  3. FLOOR => TODAY'S MID-WORD CUT, BYTE-IDENTICAL (`body + MARK`, length == cap).
  4. ABBREVIATION GUARD: `LESSON_SENTENCE_ABBREVS` disqualifies a candidate, proved
     LIVE by disabling it and watching the same input cut AT the `e.g.`.
  5. PREFIX AND LENGTH INVARIANTS -- the non-lossy claim, over a varied table.
  6. THE ONE LIVE CALL SITE MOVES and the seam is visible to `monkeypatch.setattr`;
     `lesson_chars=None` stays byte-identical and `digest_truncations` still counts.
  7. THE HEAD PATH IS UNTOUCHED (still mid-word, exactly the cap), and the function
     is pure and total.

ISOLATION CONTRACT (HONORED): written ONLY from that PM spec, from the conventions
already established under `tests/` (the log/lesson fixture builders of
`tests/test_iter104_behavior.py`, the head-region probes of
`tests/test_iter138_behavior.py`, and the `prompt_metrics` call shape of
`tests/test_iter144_behavior.py`), and from the product's OWN OBSERVABLE surface --
importing `foundry`, calling its public functions on synthetic in-process strings, and
`inspect` introspection.  I did NOT read the implementation source of `foundry.py` /
`dispatcher.py`, nor `engineer.md`, `reviewer.md`, `fix_review.md`, nor any `git diff`.
The cut rule below (`_sentence_end_indices` / `_expected`) is RE-DERIVED from the
spec's own wording, never mirrored from the implementation.

Fully offline and deterministic: synthetic strings only -- no filesystem write, no
subprocess, no git, no network, no clock, no reliance on ambient (gitignored) state
such as `products/_platform/LEARNINGS.md`, and no absolute machine path or personal
identifier anywhere (OPERATOR 2026-08-11 / iteration 205).
"""

import builtins
import inspect
import os
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

MARK = foundry.LEARNINGS_TRUNCATION_MARKER          # " [...]"
LC = foundry.PROMPT_LEARNINGS_LESSON_CHARS          # 800, out of scope this iteration
CAP = 60                                            # a small, hand-checkable cap
FLOOR = CAP // 2                                    # 30

assert len(MARK) == 6, MARK
assert CAP > len(MARK)


# ---------------------------------------------------------------------------
# the SPEC, re-derived as an independent oracle
# ---------------------------------------------------------------------------
def _body(line, cap):
    """The spec's `body`: `line[:cap - len(MARK)]`."""
    return line[: cap - len(MARK)]


def _sentence_end_indices(body):
    """Behavior 2's *sentence end*: an index `i` such that `body[i-1]` is one of
    `.` `!` `?` and `body[i]` EXISTS and is whitespace."""
    return [i for i in range(1, len(body))
            if body[i - 1] in ".!?" and body[i].isspace()]


def _expected(line, cap, abbrevs=None):
    """Behaviors 1-4 as one oracle, written from the spec text alone."""
    if len(line) <= cap:
        return line
    if abbrevs is None:
        abbrevs = foundry.LESSON_SENTENCE_ABBREVS
    lowered = tuple(a.lower() for a in abbrevs)
    body = _body(line, cap)
    for i in sorted(_sentence_end_indices(body), reverse=True):
        if i < cap // 2:
            break                                   # every later one is lower too
        if any(body[:i].lower().endswith(a) for a in lowered):
            continue                                # Behavior 4: not a sentence end
        return body[:i] + MARK
    return body + MARK                              # Behavior 3: the floor


# ---------------------------------------------------------------------------
# fixtures -- every PREMISE asserted, never assumed
# ---------------------------------------------------------------------------
# B2: a 200-char line whose ONLY sentence end inside `body` is at index 40.
ONE_END_AT_40 = "a" * 39 + ". " + "z" * 159
# B3: no `.`/`!`/`?` in `body` at all.
NO_PUNCT = "z" * 200
# B3: the only sentence end (index 20) sits BELOW the floor.
END_BELOW_FLOOR = "First sentence here. " + "z" * 200
# B4: a real sentence end at 32 plus a HIGHER `e.g.` candidate at 41.
EG_GUARDED = "Ship it when the suite is green. See e.g. " + "z" * 200
EG_GUARDED_UPPER = "Ship it when the suite is green. See E.G. " + "z" * 200
# B4: the `e.g.` candidate at 40 is the ONLY one -> falls back to the floor.
EG_ONLY_CANDIDATE = "a" * 35 + " e.g. " + "z" * 200
# B2 boundary: a sentence end at EXACTLY the floor, and one just below it.
END_AT_FLOOR = "a" * (FLOOR - 1) + ". " + "z" * 200
END_ONE_BELOW_FLOOR = "a" * (FLOOR - 2) + ". " + "z" * 200
# B2: two sentence ends above the floor -> the LARGER wins.
TWO_ENDS_ABOVE_FLOOR = "One sentence that is fairly long. Two! " + "z" * 200
# B2: the whitespace after the terminator need not be a space.
TAB_AFTER_DOT = "Sentence ends here with a tab after the dot." + "\t" + "z" * 200
# B5 edge: `body` ends exactly AT a `.`, so `body[i]` does not exist -> no candidate.
DOT_AT_BODY_END = "x" * (CAP - len(MARK) - 1) + "." + " trailing words here " * 4

assert _sentence_end_indices(_body(ONE_END_AT_40, CAP)) == [40]
assert _sentence_end_indices(_body(NO_PUNCT, CAP)) == []
assert _sentence_end_indices(_body(END_BELOW_FLOOR, CAP)) == [20]
assert _sentence_end_indices(_body(EG_GUARDED, CAP)) == [32, 41]
assert _sentence_end_indices(_body(EG_GUARDED_UPPER, CAP)) == [32, 41]
assert _sentence_end_indices(_body(EG_ONLY_CANDIDATE, CAP)) == [40]
assert _sentence_end_indices(_body(END_AT_FLOOR, CAP)) == [FLOOR]
assert _sentence_end_indices(_body(END_ONE_BELOW_FLOOR, CAP)) == [FLOOR - 1]
assert _sentence_end_indices(_body(TWO_ENDS_ABOVE_FLOOR, CAP)) == [33, 38]
assert _sentence_end_indices(_body(TAB_AFTER_DOT, CAP)) == [44]
assert _sentence_end_indices(_body(DOT_AT_BODY_END, CAP)) == []
assert _body(DOT_AT_BODY_END, CAP).endswith("."), _body(DOT_AT_BODY_END, CAP)[-5:]
for _f in (ONE_END_AT_40, NO_PUNCT, END_BELOW_FLOOR, EG_GUARDED, EG_GUARDED_UPPER,
           EG_ONLY_CANDIDATE, END_AT_FLOOR, END_ONE_BELOW_FLOOR,
           TWO_ENDS_ABOVE_FLOOR, TAB_AFTER_DOT, DOT_AT_BODY_END):
    assert len(_f) > CAP, len(_f)


# log / digest fixture builders -- conventions from tests/test_iter104_behavior.py
def _lesson_of_len(i, length, tag="ROLE"):
    prefix = f"- [{tag} iter{i:02d}] U{i:03d} "
    assert length >= len(prefix), (length, len(prefix))
    line = prefix + ("x" * (length - len(prefix)))
    assert len(line) == length
    return line


def _patterns_head(*bullets):
    lines = ["## Patterns", "", "Read this head first; the tail is the history.", ""]
    lines += [f"- {b}" for b in bullets]
    return "\n".join(lines)


def _learnings_text(lessons, *patterns):
    head = _patterns_head(*patterns) if patterns else _patterns_head("a durable rule")
    return head + "\n\n## Chronological lessons\n\n" + "\n".join(lessons) + "\n"


def _emitted_lessons(digest):
    return [ln for ln in digest.splitlines() if ln.lstrip().startswith("- [")]


def _rendered_head(out):
    """The head region as the digest RENDERED it (convention: iter 138)."""
    lines = out.split("\n")
    start = next((i for i, ln in enumerate(lines)
                  if ln.lstrip().startswith("## Patterns")), None)
    if start is None:
        return ""
    kept = [lines[start]]
    for ln in lines[start + 1:]:
        if ln.lstrip().startswith("## "):
            break
        kept.append(ln)
    return "\n".join(kept).rstrip("\n")


def _bullet_lines(region):
    return [ln for ln in region.split("\n") if ln.lstrip().startswith("- ")]


# =========================================================== Behavior 1
def test_b1_a_line_that_fits_is_returned_verbatim_with_no_marker():
    for line in ("", "short", "- [ROLE iter01] a whole small lesson.",
                 "x" * (CAP - 1)):
        got = foundry.truncate_lesson_at_sentence(line, CAP)
        assert got == line, (got, line)
        assert MARK not in got or MARK in line, got


def test_b1_the_boundary_is_inclusive_at_exactly_the_cap():
    exact = _lesson_of_len(1, CAP)
    assert len(exact) == CAP
    assert foundry.truncate_lesson_at_sentence(exact, CAP) == exact
    assert not foundry.truncate_lesson_at_sentence(exact, CAP).endswith(MARK)
    # one character over is the FIRST input that is allowed to change
    over = _lesson_of_len(2, CAP + 1)
    assert foundry.truncate_lesson_at_sentence(over, CAP) != over
    assert foundry.truncate_lesson_at_sentence(over, CAP).endswith(MARK)


def test_b1_the_empty_string_is_returned_unchanged():
    assert foundry.truncate_lesson_at_sentence("", CAP) == ""
    assert foundry.truncate_lesson_at_sentence("", len(MARK) + 1) == ""


# =========================================================== Behavior 2
def test_b2_cuts_at_the_last_sentence_end_and_not_at_the_cap():
    """The spec's worked example: cap=60, the only sentence end is at 40 -> 46 chars."""
    got = foundry.truncate_lesson_at_sentence(ONE_END_AT_40, CAP)
    body = _body(ONE_END_AT_40, CAP)
    assert got == body[:40] + MARK, got
    assert len(got) == 46, len(got)
    assert len(got) < CAP, (len(got), CAP)          # shorter than today's cut


def test_b2_the_result_shape_is_marker_after_a_terminator():
    for line in (ONE_END_AT_40, EG_GUARDED, TWO_ENDS_ABOVE_FLOOR, END_AT_FLOOR,
                 TAB_AFTER_DOT):
        got = foundry.truncate_lesson_at_sentence(line, CAP)
        assert got.endswith(MARK), got
        assert got[: -len(MARK)][-1] in ".!?", got
        assert len(got) <= CAP, (len(got), CAP)


def test_b2_the_largest_sentence_end_wins():
    got = foundry.truncate_lesson_at_sentence(TWO_ENDS_ABOVE_FLOOR, CAP)
    body = _body(TWO_ENDS_ABOVE_FLOOR, CAP)
    assert got == body[:38] + MARK, got
    assert got.endswith("Two!" + MARK), got         # the LATER end, not the first


def test_b2_the_floor_is_inclusive():
    at_floor = foundry.truncate_lesson_at_sentence(END_AT_FLOOR, CAP)
    assert at_floor == _body(END_AT_FLOOR, CAP)[:FLOOR] + MARK, at_floor
    assert len(at_floor) == FLOOR + len(MARK)
    just_below = foundry.truncate_lesson_at_sentence(END_ONE_BELOW_FLOOR, CAP)
    assert just_below == _body(END_ONE_BELOW_FLOOR, CAP) + MARK, just_below
    assert len(just_below) == CAP                   # rejected -> Behavior 3


def test_b2_any_terminator_counts_and_whitespace_need_not_be_a_space():
    tab = foundry.truncate_lesson_at_sentence(TAB_AFTER_DOT, CAP)
    assert tab == _body(TAB_AFTER_DOT, CAP)[:44] + MARK, tab
    for term in ".!?":
        line = "This clause is long enough to clear the floor" + term + " " + "z" * 200
        got = foundry.truncate_lesson_at_sentence(line, CAP)
        assert got.endswith(term + MARK), got


def test_b2_holds_at_the_realistic_shipped_cap():
    """The same geometry at the cap the pipeline actually uses (800), unchanged here."""
    tail = "Then a long trailing clause that will be cut. " * 40
    line = "- [PM iter99] The mechanism is a sentence-aligned cut. " + tail
    assert len(line) > LC
    got = foundry.truncate_lesson_at_sentence(line, LC)
    assert got == _expected(line, LC), got[-90:]
    assert got.endswith(MARK) and got[: -len(MARK)].endswith("."), got[-40:]
    assert len(got) <= LC and len(got) < LC          # a real byte saving


# =========================================================== Behavior 3
def test_b3_no_sentence_end_at_all_reproduces_the_mid_word_cut():
    got = foundry.truncate_lesson_at_sentence(NO_PUNCT, CAP)
    assert got == NO_PUNCT[: CAP - len(MARK)] + MARK, got
    assert len(got) == CAP, len(got)


def test_b3_a_sentence_end_below_the_floor_reproduces_the_mid_word_cut():
    got = foundry.truncate_lesson_at_sentence(END_BELOW_FLOOR, CAP)
    assert got == END_BELOW_FLOOR[: CAP - len(MARK)] + MARK, got
    assert len(got) == CAP, len(got)


def test_b3_floor_output_is_byte_identical_to_the_legacy_helper():
    """`_truncate_lesson` is unchanged (acceptance criterion 1), so the floor path
    must agree with it byte for byte."""
    assert callable(foundry._truncate_lesson)
    for line in (NO_PUNCT, END_BELOW_FLOOR, END_ONE_BELOW_FLOOR, EG_ONLY_CANDIDATE,
                 DOT_AT_BODY_END):
        legacy = foundry._truncate_lesson(line, CAP)
        assert foundry.truncate_lesson_at_sentence(line, CAP) == legacy, line[:40]
        assert len(legacy) == CAP


def test_b3_a_terminator_at_the_very_end_of_body_is_not_a_sentence_end():
    """`body[i]` must EXIST: a `.` as body's last character has no following char."""
    got = foundry.truncate_lesson_at_sentence(DOT_AT_BODY_END, CAP)
    assert got == _body(DOT_AT_BODY_END, CAP) + MARK, got
    assert len(got) == CAP, len(got)


# =========================================================== Behavior 4
def test_b4_the_abbrev_tuple_is_module_level_and_carries_eg_and_ie():
    abbrevs = foundry.LESSON_SENTENCE_ABBREVS
    assert isinstance(abbrevs, tuple), type(abbrevs)
    lowered = {a.lower() for a in abbrevs}
    assert {"e.g.", "i.e."} <= lowered, abbrevs


def test_b4_an_eg_candidate_is_skipped_for_the_next_real_sentence_end():
    got = foundry.truncate_lesson_at_sentence(EG_GUARDED, CAP)
    body = _body(EG_GUARDED, CAP)
    assert got == body[:32] + MARK, got
    assert got == "Ship it when the suite is green." + MARK, got
    assert "e.g." not in got, got                    # the dangling lead-in is gone


def test_b4_the_guard_is_case_insensitive():
    got = foundry.truncate_lesson_at_sentence(EG_GUARDED_UPPER, CAP)
    assert got == _body(EG_GUARDED_UPPER, CAP)[:32] + MARK, got
    assert "E.G." not in got, got


def test_b4_a_guarded_only_candidate_falls_back_to_the_floor():
    got = foundry.truncate_lesson_at_sentence(EG_ONLY_CANDIDATE, CAP)
    assert got == EG_ONLY_CANDIDATE[: CAP - len(MARK)] + MARK, got
    assert len(got) == CAP, len(got)


def test_b4_the_guard_is_live_not_vacuous(monkeypatch):
    """With the tuple emptied, the SAME inputs cut AT the `e.g.` -- so the guard is
    what changed the answer above, not an accident of the fixture."""
    monkeypatch.setattr(foundry, "LESSON_SENTENCE_ABBREVS", ())
    got = foundry.truncate_lesson_at_sentence(EG_GUARDED, CAP)
    assert got == _body(EG_GUARDED, CAP)[:41] + MARK, got
    assert got.endswith("e.g." + MARK), got
    got2 = foundry.truncate_lesson_at_sentence(EG_ONLY_CANDIDATE, CAP)
    assert got2 == _body(EG_ONLY_CANDIDATE, CAP)[:40] + MARK, got2
    assert got2.endswith("e.g." + MARK), got2
    assert len(got2) < CAP, len(got2)


def test_b4_a_custom_abbrev_tuple_is_honoured(monkeypatch):
    """The tuple is the mechanism, so a different member changes the cut."""
    line = "Ship it when the suite is green. See cf. " + "z" * 200
    assert _sentence_end_indices(_body(line, CAP)) == [32, 40]
    assert foundry.truncate_lesson_at_sentence(line, CAP) == \
        _body(line, CAP)[:40] + MARK                 # `cf.` is NOT guarded today
    monkeypatch.setattr(foundry, "LESSON_SENTENCE_ABBREVS", ("cf.",))
    assert foundry.truncate_lesson_at_sentence(line, CAP) == \
        _body(line, CAP)[:32] + MARK


# =========================================================== Behavior 5
INVARIANT_TABLE = (
    "",                                              # empty
    "tiny.",                                         # fits
    _lesson_of_len(3, CAP),                          # exactly the cap
    "." * 200,                                       # pure punctuation, no whitespace
    "?! . ?! . " * 30,                               # pure punctuation WITH whitespace
    "z" * 900,                                       # one giant unterminated run
    "One giant sentence with no internal stop that just keeps going until it ends.",
    DOT_AT_BODY_END,                                 # body ends exactly at a `.`
    ONE_END_AT_40,
    NO_PUNCT,
    END_BELOW_FLOOR,
    EG_GUARDED,
    EG_ONLY_CANDIDATE,
    TWO_ENDS_ABOVE_FLOOR,
    TAB_AFTER_DOT,
    "- [ROLE iter07] Already ends in the marker." + MARK,
    "Unicode: nao pode inventar texto. " + "u" * 300,
    "Sentence.\nA newline is whitespace too. " + "w" * 300,
)
CAPS = (len(MARK) + 1, 7, 12, 31, CAP, 200, 799, LC)


@pytest.mark.parametrize("line", INVARIANT_TABLE)
def test_b5_length_and_prefix_invariants_hold_for_every_cap(line):
    for cap in CAPS:
        got = foundry.truncate_lesson_at_sentence(line, cap)
        assert len(got) <= cap, (cap, len(got), got[:60])
        stem = got[: -len(MARK)] if got.endswith(MARK) else got
        assert line.startswith(stem), (cap, stem[-40:], line[:60])


@pytest.mark.parametrize("line", INVARIANT_TABLE)
def test_b5_matches_the_independently_derived_spec_oracle(line):
    for cap in CAPS:
        assert foundry.truncate_lesson_at_sentence(line, cap) == _expected(line, cap), \
            (cap, line[:60])


def test_b5_nothing_is_invented_reordered_or_recased():
    for line in INVARIANT_TABLE:
        got = foundry.truncate_lesson_at_sentence(line, CAP)
        stem = got[: -len(MARK)] if got.endswith(MARK) else got
        assert stem == line[: len(stem)], (stem[-30:], line[:40])
        assert len(stem) <= len(line)


def test_b5_a_pure_punctuation_line_and_a_giant_sentence_are_both_safe():
    punct = foundry.truncate_lesson_at_sentence("." * 200, CAP)
    assert punct == "." * (CAP - len(MARK)) + MARK, punct
    giant = "G" * 200 + "."
    assert foundry.truncate_lesson_at_sentence(giant, CAP) == \
        giant[: CAP - len(MARK)] + MARK


# =========================================================== Behavior 6
def _digest_fixture():
    """One over-cap lesson with a sentence end above the floor, plus two small ones."""
    over = ("- [ENG iter07] HEADMARK the mechanism is the sentence-aligned cut. "
            + "z" * 400 + " TAILMARK")
    return _learnings_text([_lesson_of_len(1, 40), _lesson_of_len(2, 45), over]), over


def test_b6_the_seam_is_visible_to_monkeypatch():
    text, _ = _digest_fixture()
    import unittest.mock as _mock  # stdlib, offline

    with _mock.patch.object(foundry, "truncate_lesson_at_sentence",
                            lambda *a, **k: "- [XX iter00] STUB-SENTINEL"):
        stubbed = foundry.learnings_digest(text, recent=50, lesson_chars=120)
    assert "STUB-SENTINEL" in stubbed, _emitted_lessons(stubbed)
    live = foundry.learnings_digest(text, recent=50, lesson_chars=120)
    assert "STUB-SENTINEL" not in live
    assert stubbed != live


def test_b6_the_seam_is_not_consulted_when_no_lesson_cap_is_given():
    text, _ = _digest_fixture()
    import unittest.mock as _mock

    with _mock.patch.object(foundry, "truncate_lesson_at_sentence",
                            lambda *a, **k: "- [XX iter00] STUB-SENTINEL"):
        out = foundry.learnings_digest(text, recent=50, lesson_chars=None)
    assert "STUB-SENTINEL" not in out, _emitted_lessons(out)


def test_b6a_lesson_chars_none_is_unchanged_full_text_and_no_marker():
    text, over = _digest_fixture()
    default = foundry.learnings_digest(text)
    explicit = foundry.learnings_digest(text, max_chars=None, lesson_chars=None)
    assert default == explicit
    assert "HEADMARK" in default and "TAILMARK" in default
    assert MARK not in default, "an uncapped digest inserted a truncation marker"
    assert over in default, "the over-cap lesson was not emitted in full"


def test_b6_the_emitted_lesson_is_sentence_aligned_end_to_end():
    text, over = _digest_fixture()
    C = 120
    d = foundry.learnings_digest(text, recent=50, lesson_chars=C)
    emitted = _emitted_lessons(d)
    hit = [ln for ln in emitted if "HEADMARK" in ln]
    assert len(hit) == 1, emitted
    assert hit[0] == _expected(over, C), hit[0]
    assert hit[0].endswith("sentence-aligned cut." + MARK), hit[0]
    assert len(hit[0]) < C, (len(hit[0]), C)         # shorter than the old cut
    for ln in emitted:
        assert len(ln) <= C, (len(ln), ln[:50])


def test_b6b_an_over_cap_lesson_still_ends_in_the_marker_and_is_counted():
    text, _ = _digest_fixture()
    C = 120
    d = foundry.learnings_digest(text, recent=50, lesson_chars=C)
    assert MARK in d
    assert [ln for ln in _emitted_lessons(d) if ln.endswith(MARK)]
    m = foundry.prompt_metrics(d, d, "")
    assert m.digest_truncations == 1, m.digest_truncations


def test_b6_the_public_signature_did_not_move():
    params = list(inspect.signature(foundry.learnings_digest).parameters)
    assert params[:4] == ["text", "recent", "max_chars", "lesson_chars"], params
    sig = inspect.signature(foundry.truncate_lesson_at_sentence)
    assert list(sig.parameters) == ["line", "cap"], list(sig.parameters)


# =========================================================== Behavior 7
# A head bullet whose sentence end (index 70) sits ABOVE the floor of the 120 cap, so
# a head path that WRONGLY moved to the new function would emit 76 chars, not 120.
HEAD_CAP = 120
HEAD_BULLET = "- **h** " + "H" * 61 + ". " + "y" * 400
HEAD_BUDGET = 200
assert _sentence_end_indices(_body(HEAD_BULLET, HEAD_CAP)) == [70]
assert 70 >= HEAD_CAP // 2
assert len(foundry.truncate_lesson_at_sentence(HEAD_BULLET, HEAD_CAP)) == 76


def _head_log():
    return ("## Patterns\n\n" + HEAD_BULLET + "\n\n" + "- **k** " + "k" * 400
            + "\n\n## Chronological lessons\n\n" + _lesson_of_len(1, 40) + "\n")


def test_b7_head_bullets_are_still_cut_mid_word_to_exactly_the_cap():
    log = _head_log()
    assert len(_head_text_len(log)) > HEAD_BUDGET
    out = foundry.learnings_digest(log, head_bullet_chars=HEAD_CAP,
                                  head_chars=HEAD_BUDGET)
    bullets = [b for b in _bullet_lines(_rendered_head(out)) if b.startswith("- **h**")]
    assert len(bullets) == 1, _rendered_head(out)[:400]
    got = bullets[0]
    assert got.endswith(MARK), got
    assert len(got) == HEAD_CAP, (len(got), HEAD_CAP)
    assert got == HEAD_BULLET[: HEAD_CAP - len(MARK)] + MARK, got
    assert got[: -len(MARK)][-1] not in ".!?", got   # still mid-word, NOT aligned


def _head_text_len(text):
    """The raw head slice (convention: iter 138) -- used only to assert the fixture is
    genuinely over budget, which is what forces per-bullet truncation."""
    lines = text.split("\n")
    start = next(i for i, ln in enumerate(lines)
                 if ln.lstrip().startswith("## Patterns"))
    kept = [lines[start]]
    for ln in lines[start + 1:]:
        s = ln.lstrip()
        if s.startswith("## ") or s.startswith("- ["):
            break
        kept.append(ln)
    return "\n".join(kept)


def test_b7_the_head_path_does_not_route_through_the_new_seam():
    log = _head_log()
    import unittest.mock as _mock

    live = foundry.learnings_digest(log, head_bullet_chars=HEAD_CAP,
                                    head_chars=HEAD_BUDGET)
    with _mock.patch.object(foundry, "truncate_lesson_at_sentence",
                            lambda *a, **k: "- **h** STUB-SENTINEL"):
        stubbed = foundry.learnings_digest(log, head_bullet_chars=HEAD_CAP,
                                          head_chars=HEAD_BUDGET)
    assert "STUB-SENTINEL" not in _rendered_head(stubbed), _rendered_head(stubbed)[:300]
    assert _rendered_head(stubbed) == _rendered_head(live)


def test_b7_the_function_is_deterministic_and_leaves_its_input_alone():
    for line in INVARIANT_TABLE:
        before = line
        first = foundry.truncate_lesson_at_sentence(line, CAP)
        second = foundry.truncate_lesson_at_sentence(line, CAP)
        assert first == second, line[:40]
        assert line == before


def test_b7_the_function_is_total_over_a_fuzz_table():
    seeds = list(INVARIANT_TABLE) + [
        "!", "?", ".", " ", "\t", "\n", "a.b.c.d.e.f.", "e.g. i.e. e.g. ",
        "A. " * 100, "..!!??  " * 50, "x" * 4000,
    ]
    for line in seeds:
        for cap in range(len(MARK) + 1, 48):
            got = foundry.truncate_lesson_at_sentence(line, cap)
            assert isinstance(got, str)
            assert len(got) <= cap, (cap, len(got))


def test_b7_the_function_performs_no_io(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("truncate_lesson_at_sentence performed I/O")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(os, "system", _boom)
    monkeypatch.setattr(builtins, "open", _boom)
    got = foundry.truncate_lesson_at_sentence(EG_GUARDED, CAP)
    monkeypatch.undo()
    assert got == _expected(EG_GUARDED, CAP), got


# ================================================== acceptance-criteria oracles
def test_ac_the_new_names_are_module_level_and_not_prompt_learnings_prefixed():
    assert callable(foundry.truncate_lesson_at_sentence)
    assert isinstance(foundry.LESSON_SENTENCE_ABBREVS, tuple)
    assert not hasattr(foundry, "PROMPT_LEARNINGS_SENTENCE_ABBREVS")
    # the two shipped caps are explicitly OUT OF SCOPE and must not have moved
    assert foundry.PROMPT_LEARNINGS_LESSON_CHARS == 800
    assert foundry.PROMPT_LEARNINGS_BUDGET_CHARS == 10000


def test_ac_both_modules_stay_importable():
    assert foundry.__name__ == "foundry"
    assert dispatcher.__name__ == "dispatcher"


def test_ac_no_absolute_machine_path_or_home_literal_in_this_test_file():
    """OPERATOR 2026-08-11 / iteration 205: the banned absolute-path SHAPE is what
    fails the leak guard, so the needles are ASSEMBLED here rather than written as
    literals -- this file must contain no such literal, including in this test."""
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    for needle in ("/" + "Users" + "/", "/" + "home" + "/", "/" + "root" + "/"):
        assert needle not in src, needle
    # Every needle above is ASSEMBLED for a reason: a source-self-scanning test whose
    # needle is a literal always matches ITSELF, so it can only ever be red.
