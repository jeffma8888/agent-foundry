"""Black-box behaviour tests for iter 158 -- the roadmap index sheds its spent
prose (every deleted byte recoverable from the archive) and a pure, DORMANT
`roadmap_spent_blocks(index_text, archive_text)` detector names index blocks
whose record already lives in the archive.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-158 PM spec's Expected
Behaviors 1-9, the conventions found under `tests/`, the two git-TRACKED
markdown deliverables behaviors 7-9 are ABOUT (`PLATFORM_ROADMAP.md` and
`PLATFORM_ROADMAP_ARCHIVE.md` -- those files ARE the artifact under test, not
implementation source), the pre-existing live pins under `tests/` that constrain
those same files, and the product's own OBSERVABLE behaviour (importing the
public name, reading its signature, and CALLING it). `foundry.py` /
`dispatcher.py` SOURCE was not read. Neither the engineer's notes, the
reviewer's notes, the fix notes, nor any `git diff` was consulted.

Every synthetic fixture is built in-process or in `tmp_path`; no test depends on
gitignored local state, on git, or on the network. Per the 2026-08-11 operator
rule, the only ambient files any test touches are git-TRACKED ones the spec
names.

SPEC DEFECT recorded here rather than encoded (see tester.md, behavior 7): the
spec requires the literal `(f) SHIPPED iter 133` to be ABSENT from the index,
but `tests/test_iter133_behavior.py:621` requires it PRESENT. Encoding the spec
verbatim would manufacture a permanently unsatisfiable suite and halt all
shipping, so behavior 7 is tested on its INTENT for item (f): the spent BODY is
retired to the archive and only a minimal stub remains.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

THIS_ITER = 158

ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ROADMAP_ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"

# behavior 2 -- the synthetic block every unit fixture is built from.
SYN_INDEX = (
    "(y) an unrelated live item that stays put. "
    "(z) SHIPPED iter 777 -- fully done, full record in the archive. "
    "(aa) the next item.\n"
)
SYN_ARCHIVE = "- **iter 777 -- the detail bullet for the synthetic block.**\n"

# behavior 7 -- spans the spec requires GONE from the index, verbatim.
RETIRED_SUBSTRINGS = (
    "(b) SHIPPED iter 128",
    "(e) SHIPPED iter 135",
    "(h) SHIPPED iter 142",
    "(m) SHIPPED iter 149",
    "(a) SHIPPED iter 132",
    "(i) SHIPPED iter 152",
    "## Detailed spec -- item 11",
    "## Item 16 --",
)

# behavior 7 -- live clauses that had to be hoisted out before the deletion.
LIVE_CLAUSES = (
    "Only the OPTIONAL 25-guard",
    "DE-LISTED by iteration 130's scout A",
    "DE-LISTED by iteration 126's spec",
    "ALSO STILL OPEN: the iteration-121 RETRY",
)

# behavior 7 -- every surviving item marker; no letter renumbered or dropped.
SURVIVING_MARKERS = (
    "(a) ", "(c) ", "(d) ", "(g) ", "(i) ", "(j) ", "(k) ", "(l) ",
    "(o) ", "(p) ", "(q) ", "(r) ", "(s) ", "(t) ",
)

COMPACTION_HEADING = "## Compacted from the index by iter 158"


def _index_text() -> str:
    return ROADMAP.read_text(encoding="utf-8")


def _archive_text() -> str:
    return ROADMAP_ARCHIVE.read_text(encoding="utf-8")


def _blocks(index_text: str, archive_text: str):
    return foundry.roadmap_spent_blocks(index_text, archive_text)


# --------------------------------------------------------------------------
# behavior 1 -- the detector's shape and its totality
# --------------------------------------------------------------------------

def test_behavior1_detector_exists_at_module_level_and_is_callable():
    assert hasattr(foundry, "roadmap_spent_blocks"), "roadmap_spent_blocks is missing from foundry"
    assert callable(foundry.roadmap_spent_blocks)


def test_behavior1_returns_a_tuple_of_frozen_records_with_the_named_fields():
    out = _blocks(SYN_INDEX, SYN_ARCHIVE)
    assert isinstance(out, tuple), "expected a tuple, got %r" % type(out)
    assert out, "the synthetic spent block should have been named"
    rec = out[0]
    assert dataclasses.is_dataclass(rec), "each record should be a dataclass"
    assert rec.__dataclass_params__.frozen is True, "records must be FROZEN"
    names = [f.name for f in dataclasses.fields(rec)]
    for field in ("label", "iteration", "chars", "live_clause_markers"):
        assert field in names, "record is missing field %r (has %r)" % (field, names)
    assert isinstance(rec.label, str)
    assert isinstance(rec.iteration, int) and not isinstance(rec.iteration, bool)
    assert isinstance(rec.chars, int)
    assert isinstance(rec.live_clause_markers, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.label = "mutated"


def test_behavior1_to_dict_is_json_serializable_primitives_only():
    rec = _blocks(SYN_INDEX, SYN_ARCHIVE)[0]
    d = rec.to_dict()
    assert isinstance(d, dict)
    encoded = json.dumps(d, sort_keys=True)
    assert json.loads(encoded) == d, "to_dict() must round-trip through JSON unchanged"
    for key, value in d.items():
        assert isinstance(key, str), "non-str key %r" % (key,)
        assert isinstance(value, (str, int, float, bool, list, dict)) or value is None, (
            "field %r carries non-primitive %r" % (key, type(value))
        )
    assert d["label"] == "(z)"
    assert d["iteration"] == 777
    assert d["chars"] > 0
    assert isinstance(d["live_clause_markers"], list), "tuple must degrade to a JSON list"


@pytest.mark.parametrize(
    "index_text,archive_text",
    [
        ("", ""),
        ("no item markers whatsoever, just prose", "nothing here either"),
        ("(z) SHIPPED iter -- no number at all.", "- **iter 777 -- d.**"),
        ("(z) SHIPPED iter 777 -- unterminated span with no next marker", ""),
        ("## ARCHIVED by iter notanumber -- heading with no int", "- **iter 1 -- d.**"),
        ("\n\n\n", "\n\n\n"),
        ("(z) SHIPPED iter 777 -- unicode span \u2014 em dash \u00e9\u00fc.", SYN_ARCHIVE),
        ("- **iter 777 -- looks like an archive bullet in the index**", SYN_ARCHIVE),
    ],
)
def test_behavior1_never_raises_for_any_string_input(index_text, archive_text):
    out = _blocks(index_text, archive_text)
    assert isinstance(out, tuple)


def test_behavior1_empty_and_marker_free_inputs_return_an_empty_tuple():
    assert _blocks("", "") == ()
    assert _blocks("no item markers whatsoever, just prose", "nothing") == ()


def test_behavior1_detector_is_pure_it_does_not_mutate_its_inputs():
    index_before, archive_before = SYN_INDEX, SYN_ARCHIVE
    _blocks(index_before, archive_before)
    assert index_before == SYN_INDEX and archive_before == SYN_ARCHIVE


# --------------------------------------------------------------------------
# behaviors 2 + 3 -- archived means spent; unarchived means keep
# --------------------------------------------------------------------------

def test_behavior2_an_archived_shipped_block_is_named_exactly_once():
    out = _blocks(SYN_INDEX, SYN_ARCHIVE)
    assert len(out) == 1, "expected exactly one named block, got %r" % ([r.label for r in out],)
    rec = out[0]
    assert rec.label == "(z)", "label was %r" % (rec.label,)
    assert rec.iteration == 777, "iteration was %r" % (rec.iteration,)
    assert rec.chars > 0, "chars was %r" % (rec.chars,)
    assert rec.chars <= len(SYN_INDEX), "chars %d exceeds the whole index" % rec.chars


def test_behavior3_an_unarchived_block_is_not_named():
    out = _blocks(SYN_INDEX, "- **iter 776 -- a bullet for a DIFFERENT iteration.**\n")
    assert [r.label for r in out] == [], (
        "an unarchived block must NOT be named -- deleting it would lose information; got %r"
        % ([(r.label, r.iteration) for r in out],)
    )
    assert _blocks(SYN_INDEX, "") == ()


def test_behavior3_the_archive_bullet_prefix_must_match_exactly():
    # A near-miss bullet (no `- **iter ` prefix) does not count as archived.
    out = _blocks(SYN_INDEX, "iter 777 -- mentioned in passing, not a frozen bullet\n")
    assert out == (), "a non-bullet mention must not license deletion; got %r" % (out,)


# --------------------------------------------------------------------------
# behavior 4 -- the hoist-before-delete signal
# --------------------------------------------------------------------------

@pytest.mark.parametrize("marker", ["STILL OPEN", "DE-LISTED", "remains"])
def test_behavior4_a_live_clause_marker_is_reported(marker):
    index_text = (
        "(y) unrelated. (z) SHIPPED iter 777 -- done, but %s in this span. (aa) next.\n" % marker
    )
    out = _blocks(index_text, SYN_ARCHIVE)
    assert len(out) == 1, "block should still be named, got %r" % (out,)
    assert out[0].live_clause_markers, "live_clause_markers must be NON-EMPTY for %r" % marker
    assert marker in out[0].live_clause_markers, (
        "expected %r among %r" % (marker, out[0].live_clause_markers)
    )


def test_behavior4_all_three_markers_are_reported_together():
    index_text = (
        "(y) unrelated. (z) SHIPPED iter 777 -- STILL OPEN, DE-LISTED, and work remains. (aa) next.\n"
    )
    out = _blocks(index_text, SYN_ARCHIVE)
    assert len(out) == 1
    assert set(out[0].live_clause_markers) == {"STILL OPEN", "DE-LISTED", "remains"}, (
        "got %r" % (out[0].live_clause_markers,)
    )


def test_behavior4_a_clean_spent_block_reports_no_markers():
    out = _blocks(SYN_INDEX, SYN_ARCHIVE)
    assert out[0].live_clause_markers == (), (
        "a span with no live marker must report an EMPTY tuple, got %r"
        % (out[0].live_clause_markers,)
    )
    assert out[0].to_dict()["live_clause_markers"] == []


# --------------------------------------------------------------------------
# behavior 5 -- tombstone sections obey the same rule
# --------------------------------------------------------------------------

def test_behavior5_an_archived_tombstone_section_is_detected_with_its_heading_as_label():
    index_text = (
        "# Roadmap\n\n"
        "## Detailed spec -- item 11: ARCHIVED by iter 777 -- moved verbatim to the archive\n\n"
        "A body line that is entirely spent.\n\n"
        "## Some later live section\n\nstill live\n"
    )
    out = _blocks(index_text, SYN_ARCHIVE)
    labels = [r.label for r in out]
    assert len(out) == 1, "expected exactly one detected section, got %r" % (labels,)
    rec = out[0]
    assert "ARCHIVED by iter 777" in rec.label, "label must carry the heading text, got %r" % rec.label
    assert rec.label.startswith("## "), "label should be the heading, got %r" % rec.label
    assert rec.iteration == 777
    assert rec.chars > 0


def test_behavior5_an_unarchived_tombstone_section_is_not_detected():
    index_text = (
        "# Roadmap\n\n## Item 99 -- ARCHIVED by iter 777 -- moved\n\nbody\n\n## Later\n\nlive\n"
    )
    out = _blocks(index_text, "- **iter 776 -- other.**\n")
    assert out == (), "an unarchived section must not be named, got %r" % ([r.label for r in out],)


def test_behavior5_sections_and_item_blocks_are_reported_together():
    index_text = (
        "# Roadmap\n\n(y) live. (z) SHIPPED iter 777 -- spent blurb. (aa) next.\n\n"
        "## Item 99 -- ARCHIVED by iter 777 -- moved\n\nbody\n\n## Later\n\nlive\n"
    )
    out = _blocks(index_text, SYN_ARCHIVE)
    assert len(out) == 2, "expected both kinds, got %r" % ([r.label for r in out],)
    assert any(r.label == "(z)" for r in out)
    assert any(r.label.startswith("## ") for r in out)


# --------------------------------------------------------------------------
# behavior 6 -- the real files, no count assertion (moving target)
# --------------------------------------------------------------------------

def test_behavior6_real_files_return_a_tuple_and_do_not_raise():
    out = _blocks(_index_text(), _archive_text())
    assert isinstance(out, tuple)
    for rec in out:
        assert isinstance(rec.label, str) and rec.label
        assert isinstance(rec.iteration, int)
        assert isinstance(rec.chars, int) and rec.chars >= 0
        json.dumps(rec.to_dict())


# --------------------------------------------------------------------------
# behavior 7 -- the index after the compaction
# --------------------------------------------------------------------------

def test_behavior7_retired_spans_are_absent_from_the_index():
    index = _index_text()
    still_present = [s for s in RETIRED_SUBSTRINGS if s in index]
    assert still_present == [], "spent prose still in the index: %r" % (still_present,)


def test_behavior7_item_f_spent_body_is_retired_even_though_its_marker_is_pinned():
    # SPEC DEFECT reconciled: the spec wants `(f) SHIPPED iter 133` gone, but
    # tests/test_iter133_behavior.py:621 asserts it PRESENT. Tested on intent:
    # only a minimal stub survives and the spent body is recoverable from the
    # archive.
    index = _index_text()
    marker = "(f) SHIPPED iter 133"
    assert marker in index, (
        "the iter-133 acceptance test pins this literal in the index; removing it reds the suite"
    )
    start = index.index(marker)
    nxt = index.find("(g) ", start)
    assert nxt > start, "could not find the following item marker to bound item (f)"
    span = index[start:nxt]
    assert len(span) <= 120, (
        "item (f) should be a minimal stub, not a blurb -- it is %d chars: %r" % (len(span), span)
    )
    assert "PM_SCOUT_LENS_POOL" not in index, "item (f)'s spent body is still in the index"


def test_behavior7_the_item16_stub_no_longer_carries_its_tombstone_blurb():
    index = _index_text()
    assert "## Item 16 --" not in index, "the old tombstone heading is still in the index"
    heads = [ln for ln in index.splitlines() if ln.startswith("## Item 16")]
    assert len(heads) == 1, (
        "tests/test_iter140_behavior.py pins exactly one `## Item 16` heading in the index, got %d"
        % len(heads)
    )
    assert len(heads[0]) <= 600, "the surviving stub heading is %d chars" % len(heads[0])


def test_behavior7_every_live_clause_survived_verbatim():
    index = _index_text()
    missing = [c for c in LIVE_CLAUSES if c not in index]
    assert missing == [], "live clauses were LOST by the compaction: %r" % (missing,)


def test_behavior7_no_item_letter_was_renumbered_or_dropped():
    index = _index_text()
    missing = [m for m in SURVIVING_MARKERS if m not in index]
    assert missing == [], "surviving item markers vanished: %r" % (missing,)


# --------------------------------------------------------------------------
# behavior 8 -- the archive gains exactly two things
# --------------------------------------------------------------------------

def test_behavior8_archive_gains_exactly_one_compaction_section_and_one_bullet():
    archive = _archive_text()
    assert archive.count(COMPACTION_HEADING) == 1, (
        "expected exactly one %r heading, got %d" % (COMPACTION_HEADING, archive.count(COMPACTION_HEADING))
    )
    headings = [ln for ln in archive.splitlines() if ln.startswith("## ")]
    assert headings[-1] == COMPACTION_HEADING, (
        "the compaction section must be APPENDED last, but the last heading is %r" % headings[-1]
    )
    bullets = [ln for ln in archive.splitlines() if ln.startswith("- **iter 158 ")]
    assert len(bullets) == 1, "expected exactly one iter-158 archive bullet, got %d" % len(bullets)


def test_behavior8_the_compaction_body_is_non_empty_and_names_each_moved_span():
    archive = _archive_text()
    body = archive.split(COMPACTION_HEADING, 1)[1]
    assert len(body.strip()) > 500, "the compaction body is suspiciously short (%d chars)" % len(body)
    for label in ("(a)", "(b)", "(e)", "(f)", "(h)", "(i)", "(m)"):
        assert "-- %s iter" % label in body, "the compaction body does not name moved span %s" % label


def test_behavior8_every_literal_the_index_lost_is_recoverable_from_the_archive():
    archive = _archive_text()
    body = archive.split(COMPACTION_HEADING, 1)[1]
    unrecoverable = [
        s for s in ("(b) SHIPPED iter 128", "(e) SHIPPED iter 135", "(h) SHIPPED iter 142",
                    "(m) SHIPPED iter 149", "(a) SHIPPED iter 132", "(i) SHIPPED iter 152")
        if s not in body
    ]
    assert unrecoverable == [], (
        "these deleted spans are NOT recoverable from the archive: %r" % (unrecoverable,)
    )
    assert "PM_SCOUT_LENS_POOL" in body, "item (f)'s moved body is not in the archive"


def test_behavior8_the_append_did_not_disturb_the_archives_existing_structure():
    archive = _archive_text()
    # one frozen bullet per iteration, none duplicated by the append
    bullets = [ln for ln in archive.splitlines() if ln.startswith("- **iter ")]
    iters = [re.match(r"- \*\*iter (\d+) ", ln).group(1) for ln in bullets]
    dupes = sorted({i for i in iters if iters.count(i) > 1})
    assert dupes == [], "the append duplicated frozen archive bullets for iterations %r" % (dupes,)
    # the quoted `## Item 16` heading must NOT have become a second real heading
    item16 = [ln for ln in archive.splitlines() if ln.startswith("## Item 16")]
    assert len(item16) == 1, (
        "tests/test_iter140_behavior.py pins exactly one `## Item 16` heading in the archive, got %d"
        % len(item16)
    )


# --------------------------------------------------------------------------
# behavior 9 -- the real-file records, and the EXISTING wall only
# --------------------------------------------------------------------------

def test_behavior9_archive_has_no_gaps_for_the_index():
    gaps = foundry.roadmap_archive_gaps(_index_text(), _archive_text())
    assert gaps == [] or tuple(gaps) == (), "roadmap_archive_gaps reported %r" % (gaps,)


def test_behavior9_exactly_one_ledger_row_of_at_most_120_chars():
    rows = [ln for ln in _index_text().splitlines() if ln.startswith("- iter %d " % THIS_ITER)]
    assert len(rows) == 1, "expected exactly one iter-158 Done ledger row, got %d" % len(rows)
    assert len(rows[0]) <= 120, "ledger row is %d chars (max 120)" % len(rows[0])


def test_behavior9_index_is_inside_the_existing_hard_wall():
    # The EXISTING 54,000 wall only. Per Out of Scope, no tighter assertion is
    # added here: a `near_wall is False` pin would install a NEW wall ~3,000
    # chars tighter than the one this iteration escaped.
    wall = foundry.ROADMAP_INDEX_HARD_CHARS
    size = len(_index_text())
    assert size < wall, "roadmap index is %d chars, hard wall %d" % (size, wall)


def test_behavior9_budget_reporter_still_reads_the_index_and_agrees_on_the_size():
    budget = foundry.roadmap_index_budget(_index_text())
    assert budget.char_count == len(_index_text())
    assert budget.hard_budget == foundry.ROADMAP_INDEX_HARD_CHARS
    assert budget.over_budget is False


# --------------------------------------------------------------------------
# acceptance criteria -- both modules import in a FRESH interpreter
# --------------------------------------------------------------------------

def test_ac_both_modules_import_in_a_fresh_interpreter():
    result = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher; print('ok')"],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, "import failed: %s" % (result.stderr[-2000:],)
    assert "ok" in result.stdout


def test_ac_detector_ships_dormant_no_new_cli_verb():
    verbs = foundry.foundry_cli_verbs(_ROOT.joinpath("foundry.py").read_text(encoding="utf-8"))
    names = set(verbs) if not isinstance(verbs, dict) else set(verbs.keys())
    # control: a fail-open empty census would pass the loop below vacuously.
    assert len(names) >= 40 and "doctor" in names, "verb census looks fail-open: %r" % (len(names),)
    for forbidden in ("spent-blocks", "roadmap-spent-blocks", "spent"):
        assert forbidden not in names, "iteration shipped an out-of-scope CLI verb %r" % forbidden
