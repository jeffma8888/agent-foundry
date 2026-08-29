"""Iteration 197 -- BLACK-BOX behavior tests: a `GAP:` answer becomes OBLIGATORY in
`roles/pm.md` and MACHINE-CHECKABLE by a pure, dormant `gap_claim_verdict`, with a derived
brake (`gap_obligation_gaps`) that fires when a live prompt feed has no role-card obligation.

Spec under test: products/_platform/state/iter-197/pm.md, Expected Behaviors 1-13.

ISOLATION CONTRACT (HONORED): written from the iter-197 PM spec, the conventions already in
tests/, and the product's OWN observable surface -- importing the modules and CALLING their
public functions, and (as tests/test_iter142_behavior.py already does) letting the TEST read
shipped text files at runtime.  The implementation TEXT of foundry.py was not read by hand,
nor were engineer.md, reviewer.md or `git diff`.

  1. `parse_gap_claim(text) -> (claim, count)`: claim is the text after the FIRST qualifying
     `GAP:` line, stripped; count is how many lines qualify.  None/"" -> ("", 0).
  2. Only a line whose STRIPPED form starts with `GAP:` qualifies, so a register-feed record
     line (`- GAP-003 [orchestration / missing-contract] ...`) can never be misread as the
     PM's own answer.
  3. `gap_claim_verdict(text, feed)` returns a FROZEN record with claim/claims_found/verdict/
     detail plus derived `ok` and `answered`; a missing or non-mapping feed is an empty
     register, never an error.
  4. "absent" (no `GAP:` line): answered False, ok TRUE -- the gate blocks a FALSE claim,
     never a missing one.
  5. "declined" for `none` / `none -- <reason>` (case-insensitive on `none`): answered True,
     ok True, detail carries the reason, "" when none was given; a reason-less `GAP: none`
     is declined and NEVER malformed.
  6. "resolved" when the claim is an id present among the feed's records: ok True, detail
     names the matched id.
  7. "unverifiable" for a `GAP-<digits>` shape absent from records: ok TRUE, and the detail
     states BOTH causes (no such record OR gather_gaps filtered it out by status/gap_layers).
  8. "malformed" when the claim is decidable from TEXT ALONE as neither a declination nor an
     id shape: the ONLY verdict with ok False, and it needs no register.
  9. `claims_found > 1` is reported; the FIRST claim still decides the verdict.
 10. `to_dict()` is JSON-serialisable and carries every field plus ok/answered, so the record
     can never disagree with its own derived properties.
 11. `gap_obligation_gaps(card_text, *, wired)`: () when not wired; ("obligation-missing",)
     when wired and the card has no obligation; ("obligation-incomplete",) when only ONE of
     the two forms is stated; () when both are.
 12. As shipped, `roles/pm.md` states both forms and the brake returns () with `wired` DERIVED
     from whether `build_prompt`'s body references `pm_gap_block` -- never hardcoded.
 13. ZERO call site on any run path, and `import foundry, dispatcher` still succeeds.

Also guarded, from the spec's ACCEPTANCE CRITERIA rather than its Expected Behaviors, and
decidable from TRACKED text alone so it also holds in the clean clone `preship` builds:
   A. The two-sided proof is explicit -- at least one input per verdict, a `malformed` input
      that is ok=False and a `resolved` input that is ok=True, and the brake is proved to
      FIRE against pre-change card text rather than only to pass against the shipped one.
   B. This iteration's roadmap record lands in the SAME diff as the code.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- Behavior 13's in-process import-safety probe

THIS_ITER = 197
ROLES_DIR = _ROOT / "roles"
PM_CARD = ROLES_DIR / "pm.md"
FOUNDRY_PY = _ROOT / "foundry.py"

# The three new names plus the record type.  Behavior 13 allows them to reference each other.
NEW_NAMES = ("parse_gap_claim", "gap_claim_verdict", "gap_obligation_gaps", "GapClaimVerdict")


def _feed(*ids: str) -> dict[str, object]:
    """A `gather_gaps`-shaped mapping, scripted -- no register is ever read from disk."""
    return {
        "register": "/nonexistent/scripted/register",
        "records": tuple({"id": i, "title": f"scripted {i}"} for i in ids),
        "unreadable": 0,
    }


LIVE_FEED = _feed("GAP-003", "GAP-016")


# ---------------------------------------------------------------- Behavior 1


def test_b1_parse_gap_claim_returns_first_claim_and_a_count():
    assert foundry.parse_gap_claim("GAP: none -- roadmap hygiene") == ("none -- roadmap hygiene", 1)
    # FIRST qualifying line decides the claim; the count covers the WHOLE text.
    assert foundry.parse_gap_claim("   GAP:  GAP-003  \nprose\nGAP: none") == ("GAP-003", 2)
    assert foundry.parse_gap_claim("prose only, no claim") == ("", 0)


def test_b1_none_and_empty_are_total_and_return_the_empty_claim():
    assert foundry.parse_gap_claim(None) == ("", 0)
    assert foundry.parse_gap_claim("") == ("", 0)


# ---------------------------------------------------------------- Behavior 2


def test_b2_a_register_feed_record_line_never_qualifies_as_the_pms_own_answer():
    """The injected block's own lines start with `-`, so they cannot be misread as a claim."""
    injected = (
        "Open agent-gap-register records (external evidence feed):\n"
        "- GAP-003 [orchestration / missing-contract] no checkpoint-first contract under caps\n"
        "- GAP-016 [tool-use / missing-contract] action policy lives in prompt prose\n"
    )
    assert foundry.parse_gap_claim(injected) == ("", 0)
    assert foundry.gap_claim_verdict(injected, LIVE_FEED).verdict == "absent"

    # A real spec that carries BOTH the feed and its own answer resolves to the ANSWER.
    spec = injected + "\nGAP: GAP-003\n"
    claim, count = foundry.parse_gap_claim(spec)
    assert (claim, count) == ("GAP-003", 1), "only the PM's own `GAP:` line may qualify"


# ---------------------------------------------------------------- Behavior 3


def test_b3_record_is_frozen_and_exposes_the_specced_fields_and_properties():
    rec = foundry.gap_claim_verdict("GAP: GAP-003", LIVE_FEED)
    assert dataclasses.is_dataclass(rec)
    assert [f.name for f in dataclasses.fields(rec)] == [
        "claim",
        "claims_found",
        "verdict",
        "detail",
    ]
    assert isinstance(rec.ok, bool) and isinstance(rec.answered, bool)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.claim = "mutated"  # type: ignore[misc]


@pytest.mark.parametrize(
    "feed",
    [None, {}, "not a mapping", 42, [], {"records": None}, {"records": ({}, {"id": None})}],
)
def test_b3_a_missing_or_non_mapping_feed_is_an_empty_register_never_an_error(feed):
    rec = foundry.gap_claim_verdict("GAP: GAP-003", feed)
    assert rec.verdict == "unverifiable", "an empty register cannot confirm an id"
    assert rec.ok is True, "an unconfirmable id is never ship-blocking"


def test_b3_feed_argument_is_optional():
    assert foundry.gap_claim_verdict("GAP: GAP-003").verdict == "unverifiable"


def test_b3_records_may_be_any_sequence_of_mappings():
    """`gather_gaps` returns a TUPLE of stored dicts; a list must behave identically."""
    assert foundry.gap_claim_verdict("GAP: GAP-003", {"records": [{"id": "GAP-003"}]}).verdict == (
        "resolved"
    )


# ---------------------------------------------------------------- Behavior 4


def test_b4_absent_is_reportable_but_never_ship_blocking():
    rec = foundry.gap_claim_verdict("a spec with no gap line at all", LIVE_FEED)
    assert rec.verdict == "absent"
    assert rec.claim == "" and rec.claims_found == 0
    assert rec.answered is False
    assert rec.ok is True, "the gate blocks a FALSE claim, never a MISSING one"


# ---------------------------------------------------------------- Behavior 5


@pytest.mark.parametrize(
    "text,reason",
    [
        ("GAP: none", ""),
        ("GAP: none -- roadmap item, hygiene", "roadmap item, hygiene"),
        ("GAP: NONE -- shouting is still a declination", "shouting is still a declination"),
        ("GAP: None -- title case", "title case"),
    ],
)
def test_b5_declined_carries_the_reason_and_is_never_malformed(text, reason):
    rec = foundry.gap_claim_verdict(text, LIVE_FEED)
    assert rec.verdict == "declined", f"{text!r} is a deliberate declination"
    assert rec.detail == reason
    assert rec.answered is True and rec.ok is True


def test_b5_a_reasonless_declination_is_declined_not_malformed():
    """The distinction the spec calls out explicitly, asserted on its own."""
    assert foundry.gap_claim_verdict("GAP: none", LIVE_FEED).verdict != "malformed"


# ---------------------------------------------------------------- Behavior 6


def test_b6_resolved_matches_a_stored_record_id_and_names_it():
    rec = foundry.gap_claim_verdict("GAP: GAP-016", LIVE_FEED)
    assert rec.verdict == "resolved"
    assert rec.answered is True and rec.ok is True
    assert "GAP-016" in rec.detail


def test_b6_id_matching_is_case_insensitive_against_the_stored_id():
    assert foundry.gap_claim_verdict("GAP: gap-003", LIVE_FEED).verdict == "resolved"


def test_b6_resolution_tracks_the_FEED_not_a_hardcoded_list():
    """Two-sided: the SAME claim flips to unverifiable once the feed no longer holds the id."""
    assert foundry.gap_claim_verdict("GAP: GAP-016", LIVE_FEED).verdict == "resolved"
    assert foundry.gap_claim_verdict("GAP: GAP-016", _feed("GAP-003")).verdict == "unverifiable"


# ---------------------------------------------------------------- Behavior 7


def test_b7_unverifiable_is_not_ship_blocking_and_names_both_causes():
    rec = foundry.gap_claim_verdict("GAP: GAP-999", LIVE_FEED)
    assert rec.verdict == "unverifiable"
    assert rec.answered is True
    assert rec.ok is True, "absence from a FILTERED feed is not evidence of nonexistence"
    low = rec.detail.lower()
    assert "gap-999" in low
    assert "not exist" in low or "no such" in low, f"cause 1 missing from detail: {rec.detail!r}"
    assert "filter" in low, f"cause 2 (gather_gaps filtering) missing from detail: {rec.detail!r}"
    assert "status" in low and "gap_layers" in low, f"filter axes unnamed: {rec.detail!r}"


@pytest.mark.parametrize("claim", ["GAP-1", "gap-042", "GAP-0003"])
def test_b7_the_id_shape_is_gap_dash_at_least_one_digit_case_insensitive(claim):
    assert foundry.gap_claim_verdict(f"GAP: {claim}", _feed()).verdict == "unverifiable"


# ---------------------------------------------------------------- Behavior 8


@pytest.mark.parametrize(
    "text",
    [
        "GAP: banana",
        "GAP:",
        "GAP:    ",
        "GAP: GAP-",
        "GAP: nonetheless we shipped something",
    ],
)
def test_b8_malformed_is_the_text_only_verdict_and_the_only_not_ok_one(text):
    rec = foundry.gap_claim_verdict(text, LIVE_FEED)
    assert rec.verdict == "malformed", f"{text!r} is neither a declination nor an id shape"
    assert rec.answered is True
    assert rec.ok is False


def test_b8_malformed_needs_no_register_at_all():
    """Decidable from the TEXT ALONE: the verdict is identical with and without a feed."""
    with_feed = foundry.gap_claim_verdict("GAP: banana", LIVE_FEED)
    no_feed = foundry.gap_claim_verdict("GAP: banana", None)
    assert with_feed.verdict == no_feed.verdict == "malformed"
    assert with_feed.detail == no_feed.detail


def test_b8_malformed_is_the_ONLY_not_ok_verdict():
    """Anti-vacuous companion to every ok=True assertion above."""
    seen = {}
    for text in (
        "no claim",
        "GAP: none",
        "GAP: none -- reason",
        "GAP: GAP-003",
        "GAP: GAP-999",
        "GAP: banana",
    ):
        rec = foundry.gap_claim_verdict(text, LIVE_FEED)
        seen[rec.verdict] = rec.ok
    assert set(seen) == {"absent", "declined", "resolved", "unverifiable", "malformed"}, (
        f"every verdict must be reachable offline, saw {sorted(seen)}"
    )
    assert {v for v, ok in seen.items() if ok is False} == {"malformed"}


# ---------------------------------------------------------------- Behavior 9


def test_b9_multiple_claims_are_reported_and_the_first_one_decides():
    text = "GAP: GAP-003\nprose in between\nGAP: none -- contradictory second line\n"
    rec = foundry.gap_claim_verdict(text, LIVE_FEED)
    assert rec.claims_found == 2, "a contradictory second claim must be VISIBLE"
    assert rec.claim == "GAP-003" and rec.verdict == "resolved", "the FIRST claim decides"


def test_b9_a_contradictory_pair_is_never_silently_resolved():
    """The reverse order: a declination first, an id second, still reports both."""
    rec = foundry.gap_claim_verdict("GAP: none\nGAP: GAP-003\n", LIVE_FEED)
    assert rec.claims_found == 2
    assert rec.verdict == "declined"


# ---------------------------------------------------------------- Behavior 10


@pytest.mark.parametrize(
    "text", ["no claim", "GAP: none -- r", "GAP: GAP-003", "GAP: GAP-999", "GAP: banana"]
)
def test_b10_to_dict_is_json_serialisable_and_cannot_disagree_with_the_record(text):
    rec = foundry.gap_claim_verdict(text, LIVE_FEED)
    d = rec.to_dict()
    assert json.loads(json.dumps(d)) == d, "to_dict() must be JSON round-trippable"
    for field in dataclasses.fields(rec):
        assert d[field.name] == getattr(rec, field.name)
    assert d["ok"] is rec.ok
    assert d["answered"] is rec.answered
    assert set(d) == {f.name for f in dataclasses.fields(rec)} | {"ok", "answered"}


# ---------------------------------------------------------------- Behavior 11


BOTH_FORMS = "state `GAP: GAP-00N` on its own line, or `GAP: none -- <reason>` when deliberate"


def test_b11_nothing_is_owed_when_the_feed_is_not_wired():
    assert foundry.gap_obligation_gaps("a card with no gap wording at all", wired=False) == ()
    assert foundry.gap_obligation_gaps(None, wired=False) == ()


@pytest.mark.parametrize("card", [None, "", "duties: write a spec, size it, lint it"])
def test_b11_obligation_missing_fires_when_wired_and_the_card_is_silent(card):
    assert foundry.gap_obligation_gaps(card, wired=True) == ("obligation-missing",)


@pytest.mark.parametrize(
    "card",
    [
        "the spec must state `GAP: GAP-00N` on its own line",
        "the spec must state `GAP: none -- <reason>` when declining",
    ],
)
def test_b11_obligation_incomplete_fires_when_only_one_form_is_stated(card):
    assert foundry.gap_obligation_gaps(card, wired=True) == ("obligation-incomplete",)


def test_b11_both_forms_present_is_clean():
    assert foundry.gap_obligation_gaps(BOTH_FORMS, wired=True) == ()


# ---------------------------------------------------------------- Behavior 12


def _wired_derived_from_source() -> bool:
    """Behavior 12: `wired` is DERIVED, never hardcoded -- does `build_prompt` reference the
    feed helper?  Read programmatically from the shipping module, not asserted as a premise."""
    return "pm_gap_block" in inspect.getsource(foundry.build_prompt)


def test_b12_the_shipped_pm_card_satisfies_the_brake_with_wired_DERIVED():
    card = PM_CARD.read_text(encoding="utf-8")
    wired = _wired_derived_from_source()
    assert wired is True, "phase 2's CODE half shipped in iteration 192; if this flips, re-read the spec"
    assert foundry.gap_obligation_gaps(card, wired=wired) == (), (
        "roles/pm.md must state BOTH `GAP: GAP-00N` and `GAP: none -- <reason>` as shipped"
    )


def test_b12_unwiring_the_feed_RELAXES_the_brake_rather_than_asserting_a_false_premise():
    stripped = "\n".join(
        ln for ln in PM_CARD.read_text(encoding="utf-8").splitlines() if "GAP" not in ln
    )
    assert foundry.gap_obligation_gaps(stripped, wired=False) == (), "not wired, nothing owed"
    assert foundry.gap_obligation_gaps(stripped, wired=True) == ("obligation-missing",), (
        "the brake must FIRE against the PRE-CHANGE card, not merely pass against the shipped one"
    )


def test_b12_the_shipped_card_states_both_forms_verbatim_from_the_tracked_spec():
    card = PM_CARD.read_text(encoding="utf-8")
    assert "GAP: GAP-00N" in card
    assert "GAP: none -- <reason>" in card
    obligated = [
        ln for ln in card.splitlines() if "GAP:" in ln and ("REQUIRED" in ln or "required" in ln)
    ]
    assert obligated, "the card must make the `GAP:` line REQUIRED, not merely available"


# ---------------------------------------------------------------- Behavior 13


def test_b13_the_new_functions_have_zero_call_site_anywhere_in_the_module():
    """Dormant-additive: no other top-level statement, function or class may reference them,
    so no prompt, artifact or exit code can change this iteration."""
    src = FOUNDRY_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders: list[tuple[str, str]] = []
    for node in tree.body:
        owner = getattr(node, "name", None)
        if owner in NEW_NAMES:
            continue
        segment = ast.get_source_segment(src, node) or ""
        for name in NEW_NAMES:
            if name in segment:
                offenders.append((owner or type(node).__name__, name))
    assert offenders == [], f"the new helpers must stay dormant, found call sites: {offenders}"


def test_b13_both_modules_still_import():
    assert foundry.__name__ == "foundry"
    assert dispatcher.__name__ == "dispatcher"
    assert hasattr(foundry, "build_prompt") and hasattr(foundry, "run_stage")


@pytest.mark.parametrize(
    "text", [None, "", "GAP:", "gap: none", "GAP:none", "GAP: GAP-0003x", "\n\nGAP: x\nGAP: y\n"]
)
def test_b13_the_helpers_are_total_and_do_no_io(text):
    """Never raises for any input, for either helper, with or without a feed."""
    foundry.parse_gap_claim(text)
    foundry.gap_claim_verdict(text, None)
    foundry.gap_claim_verdict(text, LIVE_FEED)
    foundry.gap_obligation_gaps(text, wired=True)
    foundry.gap_obligation_gaps(text, wired=False)


def test_b13_a_lowercase_prefix_does_not_qualify():
    """AMBIGUITY NOTED (PM feedback): the spec makes `none` and the id shape explicitly
    case-INsensitive but says the LINE qualifies when its stripped form starts with `GAP:`.
    Tested as case-SENSITIVE on the prefix, which is the stricter and most literal reading and
    keeps the marker unambiguous in prose; `gap: none` therefore reads as `absent`, not
    `declined`.  Flagging rather than silently relying on it."""
    assert foundry.parse_gap_claim("gap: none") == ("", 0)
    assert foundry.gap_claim_verdict("gap: none", LIVE_FEED).verdict == "absent"


# --------------------------------------------- Acceptance criteria (tracked text only)


def test_ac_b_this_iterations_roadmap_record_lands_in_the_same_diff_as_the_code():
    index = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    archive = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text(encoding="utf-8")
    rows = [ln for ln in index.splitlines() if ln.startswith(f"- iter {THIS_ITER} ")]
    bullets = [ln for ln in archive.splitlines() if ln.startswith(f"- **iter {THIS_ITER} ")]
    assert len(rows) == 1, f"expected exactly one `- iter {THIS_ITER} ` ledger row, got {len(rows)}"
    assert len(rows[0]) <= 120, f"ledger row is {len(rows[0])} chars, the wall is 120"
    assert len(bullets) == 1, f"expected exactly one archive bullet, got {len(bullets)}"
    assert foundry.roadmap_ledger_gaps(index, archive, (THIS_ITER,)) == []
    assert foundry.roadmap_archive_gaps(index, archive) == []


def test_ac_b_the_roadmap_brakes_are_two_sided():
    """Fail-open guard: the brakes above must be able to FAIL on this very input."""
    index = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    archive = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text(encoding="utf-8")
    no_row = "\n".join(
        ln for ln in index.splitlines() if not ln.startswith(f"- iter {THIS_ITER} ")
    )
    no_bullet = "\n".join(
        ln for ln in archive.splitlines() if not ln.startswith(f"- **iter {THIS_ITER} ")
    )
    assert foundry.roadmap_archive_gaps(index, no_bullet) == [THIS_ITER]
    assert foundry.roadmap_ledger_gaps(no_row, no_bullet, (THIS_ITER,)) == [THIS_ITER]
