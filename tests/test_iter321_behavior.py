"""Black-box behaviour tests for iter 321 -- a write-early PLACEHOLDER scout
candidate is now distinguishable from a measured one in the decision log.

The iteration's product is a pure classifier plus one conditional render line:

  1-3. `scout_candidate_is_stub(candidate)` -- module-level, pure, TOTAL and
       spelling-agnostic: `True` for a write-early placeholder heading, `False`
       for a real (measured) candidate title, including a near-miss whose real
       title merely CONTAINS a placeholder word.
  4.   `DirectionsEntry.stub_candidates` -- the ordered flagged subset of
       `.candidates`, `()` when none, resolving the predicate by its BARE
       module name so `monkeypatch.setattr(foundry, ...)` is visible.
  5.   Both serialization schemas frozen: 6 `DirectionsEntry` fields / 6
       `to_dict` keys, 4 `DirectionsDigest.to_dict` keys, and `stub_candidates`
       in NEITHER payload.
  6.   `DirectionsDigest.render()` labels a stubbed block with exactly one
       `stubs: k of n ...` line between that block's last candidate line and
       its `winner:` line, emits nothing for a clean block, and changes neither
       the rollup line nor the `directions_ship_gaps` verdict.

ISOLATION CONTRACT (honored): every assertion here was derived from the PM
spec's Expected Behaviors 1-6 (`pm.md` in this iteration's state dir), from the
existing conventions under `tests/`, and from the product's OBSERVABLE output
by RUNNING it (`python3 foundry.py directions --config ... --limit 4`). The
engineer's notes, the reviewer's notes and `git diff` were NOT read, and the
implementation logic of `foundry.py` was NOT read.

PURITY: no subprocess, no git, no network, no filesystem fixture -- every
behaviour is an in-memory call driven by in-test literal tables, so nothing
here depends on gitignored local state (`state/`, `DIRECTIONS.md`, iteration
dirs) and the file is safe in a throwaway fresh clone.

XDIST-SAFETY: all mutation is `monkeypatch`-scoped and process-local.
"""
from __future__ import annotations

import dataclasses
import json
import re
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402


# --------------------------------------------------------------------- fixtures
# Behavior 1 -- 20 lines, each VERBATIM from this repo's own scout artifacts.
# Shape coverage: parenthesised and bare, comma- and space-joined, an ALL-CAPS
# form, a two-id form (B2/B3) and a digit-less id (C).
STUB_LINES = (
    "Candidate A1 -- (measuring)",
    "Candidate B3 -- (being measured)",
    "Candidate B3 -- (pending measurement)",
    "Candidate B3 -- (measurement in flight)",
    "Candidate B1 -- placeholder (measuring)",
    "Candidate B1 -- placeholder (being measured)",
    "Candidate B1 -- placeholder pending measurement",
    "Candidate B3 -- placeholder, being measured",
    "Candidate B3 -- placeholder, pending measurement",
    "Candidate A3 -- (placeholder, being measured)",
    "Candidate A3 -- TBD (measuring)",
    "Candidate B3 -- TBD (measurement in flight)",
    "Candidate B3 -- TBD (refining)",
    "Candidate C -- TBD (measurement in progress)",
    "Candidate C -- TBD",
    "Candidate C -- being measured",
    "Candidate A2 -- (in progress)",
    "Candidates B2/B3 -- IN PROGRESS",
    "Candidate A2 -- pending",
    "Candidate A2 -- (see refined file)",
)

# Behavior 2 -- 5 real titles VERBATIM from the same artifacts plus one planted
# near-miss. The em-dash row is 37 chars, so neither LENGTH nor dash style may
# be the discriminator; the last row is a real title that merely CONTAINS the
# placeholder word "pending", so the rule must be "NOTHING BUT placeholder
# words", never "contains one".
REAL_LINES = (
    "Candidate A1 -- the dual-scout default is the path only the RETIRED "
    "product takes: flip it, blast radius zero",
    "Candidate B2 -- the README front door is 61.7% single-line essays",
    "Candidate A3 -- give the two-sided roadmap-ledger flip a verb, because "
    "the seat that needs it is currently told to hand-write Python",
    "Candidate slate (new-capability lens)",
    "Candidate A3 \u2014 L1 ACT tool: tail_file",
    "Candidate B3 -- the roadmap tells the PM which items are pending, "
    "and it is stale",
)

STUBS_TEXT = ("stubs: {k} of {n} candidate line(s) are write-early "
              "placeholders, not measured candidates")


def _stubs_line(k, n):
    return STUBS_TEXT.format(k=k, n=n)


def _entry(iteration=1, candidates=("Candidate A1 -- a real measured thing",),
           winner="A1", action=None, sha=None, lenses=("performance-and-throughput",)):
    return foundry.DirectionsEntry(
        iteration=iteration,
        lenses=tuple(lenses),
        candidates=tuple(candidates),
        winner=winner,
        action=action,
        sha=sha,
    )


def _digest(entries, subjects=()):
    return foundry.DirectionsDigest(
        product="demoprod", entries=tuple(entries), ship_subjects=tuple(subjects))


def _subject(n):
    """A commit subject in the loop's own shape."""
    return "chore: some change (foundry iter " + str(n) + ")"


def _blocks(text):
    """Split a rendered log into {iteration: [lines]} -- anchored, no slicing."""
    out, cur = {}, None
    for line in text.splitlines():
        stripped = line.strip()
        m = re.match(r"^iter-(\d+)$", stripped)
        if m:
            cur = int(m.group(1))
            out[cur] = []
        elif cur is not None and stripped:
            out[cur].append(line)
    return out


def _id_first(line):
    """The third spelling: `parse_scout_candidates` output minus its id word."""
    return re.sub(r"(?i)^candidates?\s+", "", line, count=1)


def _spellings(line):
    """Raw heading, parse output, and id-first form of the SAME line."""
    return ("## " + line, line, _id_first(line))


# ============================================================ Behavior 1
def test_b1_every_write_early_placeholder_form_is_flagged():
    assert len(STUB_LINES) == 20 and len(set(STUB_LINES)) == 20
    for line in STUB_LINES:
        assert foundry.scout_candidate_is_stub(line) is True, line


def test_b1_covers_each_named_shape():
    """The spec names 5 shapes explicitly; none may be missing from the table."""
    joined = "\n".join(STUB_LINES)
    assert "(measuring)" in joined                      # parenthesised
    assert "Candidate A2 -- pending" in joined          # bare
    assert "placeholder, being measured" in joined      # comma-joined
    assert "IN PROGRESS" in joined                      # ALL-CAPS
    assert "Candidates B2/B3" in joined                 # two-id
    assert "Candidate C -- TBD" in joined               # digit-less id


def test_b1_the_two_id_form_flags_in_its_spelling_variants():
    """`Candidates B2/B3` is the verbatim fixture; the singular and the
    space-padded spellings of the same two-id shape must agree with it."""
    for line in ("Candidate B2/B3 -- pending",
                 "Candidates A1/A2 -- (measuring)",
                 "Candidate B2 / B3 -- TBD"):
        assert foundry.scout_candidate_is_stub(line) is True, line


# ============================================================ Behavior 2
def test_b2_every_real_measured_title_is_not_flagged():
    assert len(REAL_LINES) == 6 and len(set(REAL_LINES)) == 6
    for line in REAL_LINES:
        assert foundry.scout_candidate_is_stub(line) is False, line


def test_b2_the_near_miss_contains_a_placeholder_word_yet_is_real():
    """Guards against a `contains one placeholder word` implementation."""
    near_miss = REAL_LINES[-1]
    assert "pending" in near_miss
    assert foundry.scout_candidate_is_stub(near_miss) is False
    # ...while the same word ALONE after the id is a stub.
    assert foundry.scout_candidate_is_stub("Candidate A2 -- pending") is True


def test_b2_neither_length_nor_dash_style_is_the_discriminator():
    em_dash = REAL_LINES[4]
    assert "\u2014" in em_dash and len(em_dash) == 37, (em_dash, len(em_dash))
    assert foundry.scout_candidate_is_stub(em_dash) is False
    # A SHORTER em-dash line that is pure placeholder still flags,
    # and a LONGER `--` line that is pure placeholder still flags.
    assert foundry.scout_candidate_is_stub("Candidate A3 \u2014 TBD") is True
    assert foundry.scout_candidate_is_stub(
        "Candidate B3 -- placeholder, pending measurement") is True
    # `slate` must survive the id strip (the `\b` case).
    assert foundry.scout_candidate_is_stub("Candidate slate (new-capability lens)") is False


# ============================================================ Behavior 3
def test_b3_is_total_and_never_raises():
    junk = [
        None, "", "   ", "\t\n ", "##", "## ", "#", "--", "-- --", "\u2014",
        "()", "[]", "{}", ".,:;-", "42", "123 456", "\u4e2d\u6587",
        "Candidate", "Candidates", "candidate a1 -- (measuring)",
        "CANDIDATE A1 -- (MEASURING)", "x" * 500,
        "Candidate A1 -- (measuring)\nCandidate A2 -- real thing",
    ]
    for value in junk:
        got = foundry.scout_candidate_is_stub(value)
        assert isinstance(got, bool), (value, type(got))


def test_b3_empty_and_titleless_headings_are_stubs():
    for value in (None, "", "   ", "## Candidate A1", "## A1"):
        assert foundry.scout_candidate_is_stub(value) is True, repr(value)


def test_b3_all_three_spellings_agree_on_every_fixture():
    for line in STUB_LINES + REAL_LINES:
        verdicts = {form: foundry.scout_candidate_is_stub(form)
                    for form in _spellings(line)}
        assert len(set(verdicts.values())) == 1, verdicts
        # ...and the shared verdict is the RIGHT one, so agreement is not
        # bought by collapsing everything to one answer.
        assert set(verdicts.values()) == {line in STUB_LINES}, verdicts


def test_b3_all_three_spellings_agree_on_a_titleless_heading():
    for form in ("## Candidate A1", "Candidate A1", "A1", "## A1"):
        assert foundry.scout_candidate_is_stub(form) is True, form


def test_b3_is_case_insensitive_about_the_candidate_word_and_the_title():
    assert foundry.scout_candidate_is_stub("candidate a1 -- (measuring)") is True
    assert foundry.scout_candidate_is_stub("CANDIDATE A1 -- (MEASURING)") is True
    assert foundry.scout_candidate_is_stub("Candidate a1 -- TBD") is True


def test_b3_is_pure_repeated_calls_agree():
    for line in STUB_LINES[:5] + REAL_LINES[:2]:
        first = foundry.scout_candidate_is_stub(line)
        assert foundry.scout_candidate_is_stub(line) is first


def test_b3_is_total_for_non_string_inputs_too():
    """The spec's "never raises for ANY input" read at its widest: a non-str argument
    must still produce a bool rather than an AttributeError. The spec does not
    pin WHICH verdict a non-str gets, so only totality is asserted."""
    for value in (42, 3.5, True, [], {}, (), b"Candidate A1 -- (measuring)", object()):
        got = foundry.scout_candidate_is_stub(value)
        assert isinstance(got, bool), (repr(value)[:40], type(got))


# ============================================================ Behavior 4
def test_b4_stub_candidates_is_the_ordered_flagged_subset():
    cands = (REAL_LINES[1], STUB_LINES[0], REAL_LINES[3], STUB_LINES[14])
    got = _entry(candidates=cands).stub_candidates
    assert isinstance(got, tuple)
    assert got == (STUB_LINES[0], STUB_LINES[14])


def test_b4_stub_candidates_is_empty_when_every_candidate_is_measured():
    assert _entry(candidates=REAL_LINES).stub_candidates == ()
    assert _entry(candidates=()).stub_candidates == ()


def test_b4_stub_candidates_is_everything_when_every_candidate_is_a_stub():
    assert _entry(candidates=STUB_LINES).stub_candidates == STUB_LINES


def test_b4_stub_candidates_is_a_property_not_a_method():
    attr = foundry.DirectionsEntry.__dict__.get("stub_candidates")
    assert isinstance(attr, property), attr


def test_b4_property_resolves_the_predicate_by_its_bare_module_name(monkeypatch):
    all_real = _entry(candidates=REAL_LINES)
    assert all_real.stub_candidates == ()
    monkeypatch.setattr(foundry, "scout_candidate_is_stub", lambda c: True)
    assert all_real.stub_candidates == tuple(REAL_LINES)


def test_b4_property_seam_works_in_the_other_direction_too(monkeypatch):
    all_stubs = _entry(candidates=STUB_LINES)
    assert all_stubs.stub_candidates == STUB_LINES
    monkeypatch.setattr(foundry, "scout_candidate_is_stub", lambda c: False)
    assert all_stubs.stub_candidates == ()


# ============================================================ Behavior 5
def test_b5_directions_entry_declares_exactly_six_fields_in_order():
    names = [f.name for f in dataclasses.fields(foundry.DirectionsEntry)]
    assert names == ["iteration", "lenses", "candidates", "winner", "action", "sha"]
    assert "stub_candidates" not in names


def test_b5_entry_to_dict_still_has_exactly_its_six_pinned_keys():
    payload = _entry(candidates=STUB_LINES[:2], action="PUSHED", sha="abc1234").to_dict()
    assert list(payload.keys()) == [
        "iteration", "lenses", "candidates", "winner", "action", "sha"]
    assert "stub_candidates" not in payload


def test_b5_digest_to_dict_still_has_exactly_its_four_pinned_keys():
    payload = _digest([_entry(1, candidates=STUB_LINES[:3]), _entry(2)]).to_dict()
    assert list(payload.keys()) == ["product", "total", "exit_code", "entries"]
    assert "stub_candidates" not in payload
    for row in payload["entries"]:
        assert "stub_candidates" not in row


def test_b5_no_serialized_payload_mentions_the_new_property_anywhere():
    blob = json.dumps(_digest([_entry(1, candidates=STUB_LINES)]).to_dict())
    assert "stub_candidates" not in blob
    # The stub candidate LINES themselves are still carried (Behavior: the
    # existing parse is untouched, only the LABEL is new).
    assert STUB_LINES[0] in blob


def test_b5_entry_and_digest_are_still_frozen():
    entry = _entry()
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.iteration = 99
    digest = _digest([entry])
    with pytest.raises(dataclasses.FrozenInstanceError):
        digest.product = "other"


# ============================================================ Behavior 6
def test_b6_a_stubbed_block_carries_exactly_one_correctly_counted_label():
    cands = (STUB_LINES[0], REAL_LINES[1], STUB_LINES[3], REAL_LINES[3])
    text = _digest([_entry(300, candidates=cands)]).render()
    block = _blocks(text)[300]
    hits = [ln for ln in block if ln.strip() == _stubs_line(2, 4)]
    assert len(hits) == 1, block
    assert len([ln for ln in block if ln.strip().startswith("stubs:")]) == 1, block


def test_b6_the_label_counts_k_of_n_for_a_fully_stubbed_block():
    text = _digest([_entry(300, candidates=STUB_LINES[:6])]).render()
    assert _stubs_line(6, 6) in [ln.strip() for ln in _blocks(text)[300]]


def test_b6_label_sits_after_the_last_candidate_line_and_before_winner():
    cands = (STUB_LINES[0], REAL_LINES[1], STUB_LINES[3])
    block = _blocks(_digest([_entry(300, candidates=cands, winner="A1")]).render())[300]
    stripped = [ln.strip() for ln in block]
    label_at = stripped.index(_stubs_line(2, 3))
    candidate_ats = [i for i, ln in enumerate(stripped) if ln.startswith("- ")]
    winner_at = stripped.index("winner: A1")
    assert candidate_ats and max(candidate_ats) < label_at < winner_at, stripped


def test_b6_a_clean_digest_renders_no_stubs_substring_at_all():
    entries = [_entry(300, candidates=REAL_LINES), _entry(299, candidates=REAL_LINES[:2])]
    text = _digest(entries).render()
    assert "stubs:" not in text
    assert foundry.render_directions_doc(_digest(entries)).count("stubs:") == 0


def test_b6_only_the_stubbed_block_is_labelled_in_a_mixed_digest():
    entries = [_entry(300, candidates=STUB_LINES[:2]),
               _entry(299, candidates=REAL_LINES),
               _entry(298, candidates=(REAL_LINES[0], STUB_LINES[5]))]
    blocks = _blocks(_digest(entries).render())
    assert [ln.strip() for ln in blocks[300] if ln.strip().startswith("stubs:")] == \
        [_stubs_line(2, 2)]
    assert [ln for ln in blocks[299] if ln.strip().startswith("stubs:")] == []
    assert [ln.strip() for ln in blocks[298] if ln.strip().startswith("stubs:")] == \
        [_stubs_line(1, 2)]


def test_b6_the_label_is_the_only_line_added_everything_else_is_identical():
    """A clean block and a stubbed block differ by exactly that one line."""
    stub_text = _digest([_entry(300, candidates=STUB_LINES[:3], action="PUSHED",
                                sha="abc1234")]).render()
    clean_text = _digest([_entry(300, candidates=REAL_LINES[:3], action="PUSHED",
                                 sha="abc1234")]).render()

    def skeleton(text):
        return [ln for ln in text.splitlines()
                if not ln.strip().startswith(("- ", "stubs:"))]

    assert skeleton(stub_text) == skeleton(clean_text)
    assert len(stub_text.splitlines()) == len(clean_text.splitlines()) + 1


def test_b6_forcing_the_predicate_off_restores_the_unlabelled_render(monkeypatch):
    entries = [_entry(300, candidates=STUB_LINES[:3]),
               _entry(299, candidates=(REAL_LINES[0], STUB_LINES[1]))]
    labelled = _digest(entries).render()
    assert "stubs:" in labelled
    without = "\n".join(ln for ln in labelled.splitlines()
                        if not ln.strip().startswith("stubs:"))
    monkeypatch.setattr(foundry, "scout_candidate_is_stub", lambda c: False)
    assert _digest(entries).render().rstrip("\n") == without.rstrip("\n")


def test_b6_rollup_line_is_unchanged_and_still_last_when_all_entries_are_stubbed():
    entries = [_entry(n, candidates=STUB_LINES[:4]) for n in (300, 299, 298)]
    text = _digest(entries).render()
    assert text.count("stubs:") == 3
    assert text.rstrip().endswith("scouted iterations")
    assert text.rstrip().splitlines()[-1].strip() == "3 scouted iterations"


def test_b6_ship_gaps_verdict_is_identical_with_and_without_the_labels():
    """Non-vacuous: the brake must actually FIRE on this text.

    Rows render `ship: unknown` only when the digest itself carries no
    `ship_subjects`, so the subjects are handed to the BRAKE alone -- otherwise
    the same data would flip the row's label to `PUSHED (per git)` and the
    finding could never fire, leaving `() == ()`.
    """
    entries = [_entry(n, candidates=STUB_LINES[:3]) for n in (300, 299, 298)]
    text = foundry.render_directions_doc(_digest(entries))
    assert text.count("stubs:") == 3
    subjects = (_subject(299), _subject(298))
    with_labels = foundry.directions_ship_gaps(text, subjects)
    stripped = "\n".join(ln for ln in text.splitlines()
                         if not ln.strip().startswith("stubs:"))
    assert "stubs:" not in stripped
    without_labels = foundry.directions_ship_gaps(stripped, subjects)
    assert len(with_labels) == 2, with_labels
    assert with_labels == without_labels


def test_b6_ship_gaps_stays_identical_on_a_clean_and_a_mixed_document():
    for cands in (REAL_LINES, STUB_LINES[:2] + REAL_LINES[:2]):
        entries = [_entry(n, candidates=cands) for n in (300, 299, 298)]
        text = foundry.render_directions_doc(_digest(entries))
        subjects = (_subject(299),)
        stripped = "\n".join(ln for ln in text.splitlines()
                            if not ln.strip().startswith("stubs:"))
        assert foundry.directions_ship_gaps(text, subjects) == \
            foundry.directions_ship_gaps(stripped, subjects)


def test_b6_an_entry_with_no_candidates_at_all_is_never_labelled():
    """n == 0 implies k == 0, so the k >= 1 rule must not emit a `0 of 0` row."""
    text = _digest([_entry(300, candidates=(), winner=None)]).render()
    assert "stubs:" not in text
    assert text.rstrip().endswith("scouted iterations")
