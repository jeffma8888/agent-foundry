"""Iteration 413 behavior tests -- ``foundry.parse_triage_winner`` gains Rule 0:
a LINE-ANCHORED, UPPERCASE ``PICK`` label outranks the first ``[ABC][0-9]`` id in
the Triage section, so the tracked decision log stops crediting a pool-summary
bullet's first id as the winner. Rule 0 (spec, Expected Behaviors header) is one
compiled pattern applied to the text AFTER the ``## Triage`` heading line with
``re.MULTILINE``::

    ^[ \\t\\-*#>]*PICK\\b[^\\n]{0,24}?\\b([A-Z][0-9])\\b

first match wins and returns group 1; no match -> Rule 1 -> Rule 2 exactly as
before (tests/test_iter115_behavior.py ``test_b03_*`` + tests/test_iter324_behavior.py
are the zero-regression oracle and were NOT edited).

BLACK-BOX / ISOLATION (honored): every assertion below was derived from the PM
spec's Expected Behaviors 1-12 (``products/_platform/state/iter-413/pm.md``) and
from the conventions of the existing modules under ``tests/`` (iter115's
``_write_cfg`` / ``_iter_dir`` / scout-body shape, iter324's ``winner`` driver).
The implementation source, the engineer's notes, the reviewer's notes and
``git diff`` were NOT read.

Offline by construction: no subprocess, no git, no network, no clock. Every
fixture for Behaviors 1-10 is a pure in-memory string. Behavior 11 builds its
product entirely under ``tmp_path``; Behavior 12 reads ONE tracked file
(``roles/pm.md``) located at runtime from this file's location. No test reads
``DIRECTIONS.md``, ``products/*/state/`` or any other ambient repo path.

HAZARD PIN (inherited from iter 159/160) -- always reach through ``foundry.``;
``from foundry import *`` re-exports a seam named ``test_tree`` that pytest then
collects as a zero-argument test.

HAZARD PIN (iter 413, measured this stage) -- ``gather_directions`` only sees
ZERO-PADDED ``iter-NN`` dirs (``iter-7`` yielded no entries, ``iter-07`` did), so
Behavior 11 uses iter115's ``_iter_dir`` shape even though the spec prose says
``state/iter-7/``.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

EMDASH = "\u2014"
LABEL = "PICK"
WINDOW = 24


def winner(text):
    """Drive the PUBLIC parser exactly as the reporting path does."""
    return foundry.parse_triage_winner(text)


def _gap(line, ident):
    """Chars between the end of the PICK label and the start of `ident` on `line`
    (the spec's 24-char window is measured here, not counted by eye)."""
    return line.index(ident) - (line.index(LABEL) + len(LABEL))


# Behavior 1's body, reused verbatim by Behavior 11.
B1_TEXT = (
    "## Triage\n"
    "- Pool = scout A + scout B; both 3/3 measured, but A1 and A3 are still "
    "`Hypothesis:` rows.\n"
    "- PICK: **B1** -- one auth attempt, then a hold.\n"
    "- Strongest alternative: **A2**.\n"
)


# ==========================================================================
# Behavior 1 -- the iter-411 shape resolves to the labelled pick (was A1)
# ==========================================================================
def test_b01_iter411_shape_resolves_to_labelled_pick():
    assert winner(B1_TEXT) == "B1"


def test_b01_pool_bullet_id_is_no_longer_the_winner():
    # The first [ABC][0-9] token after the heading is A1 -- Rule 1 alone would
    # return it; the label must outrank it.
    assert winner(B1_TEXT) != "A1"


# ==========================================================================
# Behavior 2 -- the iter-132 shape (prose pool line, bold label + scout
#               qualifier) resolves to the labelled pick (was A1)
# ==========================================================================
B2_TEXT = (
    "## Triage\n\n"
    "Candidate pool = the combined slate: A1 (x), A2 (y), B1 (z).\n\n"
    "**PICK: scout-B B1.** It is roadmap item (a).\n"
)


def test_b02_iter132_shape_resolves_to_labelled_pick():
    assert winner(B2_TEXT) == "B1"


# ==========================================================================
# Behavior 3 -- bullet, bold, blockquote, heading and indent prefixes all carry
#               the label
# ==========================================================================
@pytest.mark.parametrize(
    "label_line",
    ["- PICK: B3", "* **PICK: B3**", "> PICK: B3", "### PICK: B3", "  PICK: B3"],
)
def test_b03_prefixes_are_label_carriers(label_line):
    text = "## Triage\nA1 is the pool.\n" + label_line + "\n"
    assert winner(text) == "B3"


# ==========================================================================
# Behavior 4 -- the label is UPPERCASE-only; `Pick` / `pick` stay prose and the
#               zero-regression oracle fixtures keep their HEAD values
# ==========================================================================
@pytest.mark.parametrize(
    "text,expected",
    [
        ("## Triage\n- B2 is weaker.\n- Pick: **B1**\n", "B2"),          # Rule 1
        ("## Triage\nWe did not pick A2; A3 wins.\n", "A2"),             # Rule 1
    ],
)
def test_b04_mixed_and_lower_case_labels_are_prose(text, expected):
    assert winner(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        # tests/test_iter115_behavior.py::test_b03_* fixtures, HEAD values
        ("# PM spec -- iteration 115\n\n## Triage\n**Pick: C1 (Scout A)** for "
         "sequencing reasons.\n\n## Feature\nbody mentioning A4 later\n", "C1"),
        ("Candidate A9 was rejected earlier in prose.\n## Triage\nPick: C1\n", "C1"),
        ("no triage here\nPick: C1", None),
        ("## Triage\nno id token at all", None),
        ("## triage\nPick: B2\n", "B2"),
        # tests/test_iter324_behavior.py Rule-2 compositions, HEAD values --
        # an uppercase PICK label with NO [A-Z][0-9] in its window must still
        # hand these to Rule 2 unchanged.
        ("## Triage\n**Pick: v** (PM_SCOUT_A candidate #2 -- x)\n", "A2"),
        ("## Triage\nPICK: PM_SCOUT_B's Candidate B -- x\n", "B2"),
        ("## Triage\n**PICK: SCOUT B candidate 2** -- x\n", "B2"),
        ("## Triage\n**Pick: v** (Scout B, candidate 1).\n", "B1"),
        ("## Triage\n**PICK: scout-A H1** -- x\n", "H1"),
        ("## Triage\n**PICK: scout B's I1** -- x\n", "I1"),
        ("## Triage\n**PICK: scout B's candidate S1 -- x**\n", "S1"),
        ("## Triage\n**HOTFIX FLAG PRESENT, so there is no candidate contest.**\n",
         None),
        ("## Triage\nscouts proposed candidate 2 each\n", None),
    ],
)
def test_b04_oracle_fixtures_keep_their_head_values(text, expected):
    assert winner(text) == expected


# ==========================================================================
# Behavior 5 -- the label must OPEN the line; `PICKED` is not the label
# ==========================================================================
def test_b05_mid_line_label_is_not_anchored():
    text = "## Triage\n- Strongest alternative A2; my PICK: **B1**\n"
    assert winner(text) == "A2"


def test_b05_picked_fails_the_word_boundary_and_rule1_finds_b2_first():
    assert winner("## Triage\nPICKED B2 over A1\n") == "B2"


# ==========================================================================
# Behavior 6 -- the id must start within 24 chars of the label
# ==========================================================================
_B6_OUT = "PICK: roadmap #218 -- pin the H1 distribution mode."
_B6_IN_22 = "**PICK: scout B's candidate B1** -- x"
_B6_IN_24 = "**PICK: scout A's candidate **A2, in its SMALL variant**"


def test_b06_window_edges_are_measured_not_eyeballed():
    assert _gap(_B6_OUT, "H1") == 26
    assert _gap(_B6_IN_22, "B1") == 22
    assert _gap(_B6_IN_24, "A2") == WINDOW


def test_b06_26_chars_is_outside_the_window_and_stays_none():
    # tests/test_iter324_behavior.py::test_b5's fixture, must stay None.
    assert winner("## Triage\n" + _B6_OUT + "\n") is None


@pytest.mark.parametrize(
    "line,expected",
    [(_B6_IN_22, "B1"), (_B6_IN_24, "A2")],
)
def test_b06_ids_inside_the_window_resolve(line, expected):
    assert winner("## Triage\n" + line + "\n") == expected


# ==========================================================================
# Behavior 7 -- Rule 0 accepts ids outside [ABC] when LABELLED
# ==========================================================================
def test_b07_labelled_h1_resolves():
    assert winner("## Triage\n**PICK: H1** -- hotfix round, no contest.\n") == "H1"


def test_b07_unlabelled_out_of_alphabet_ids_stay_none():
    assert winner("## Triage\nsee H1 and L0 and S3 in the prose below.\n") is None


# ==========================================================================
# Behavior 8 -- a label line with no id in its window falls through
# ==========================================================================
def test_b08_label_without_id_falls_through_to_rule1_over_whole_section():
    text = ("## Triage\nPICK: roadmap row 96 -- overrides both slates.\n"
            "B2 was the runner-up.\n")
    assert winner(text) == "B2"


def test_b08_label_without_any_id_stays_none():
    text = ("## Triage\n**PICK: a new roadmap row 96 -- this overrides both "
            "scout slates.**\n")
    assert winner(text) is None


# ==========================================================================
# Behavior 9 -- the heading rule still gates Rule 0; only the FIRST heading
#               counts and Rule 0 scans everything after it
# ==========================================================================
def test_b09_label_before_the_heading_is_invisible():
    assert winner("PICK: **B1**\n## Triage\nA2 is the pool.\n") == "A2"


def test_b09_no_heading_means_none_even_with_a_label():
    assert winner("PICK: **B1**\nno heading here\n") is None


def test_b09_rule0_scans_everything_after_the_first_heading():
    assert winner("## Triage\nA1 is the pool.\n## Triage\nPICK: B2\n") == "B2"


def test_b09_derived_first_regex_match_wins_over_an_idless_label_line():
    # Derived from the spec's "first match wins" regex definition: an earlier
    # label line with NO id in its window does not consume Rule 0; a later
    # labelled line still outranks Rule 1's A1.
    text = "## Triage\nPICK: roadmap row 96\nA1 is weaker.\nPICK: B3\n"
    assert winner(text) == "B3"


# ==========================================================================
# Behavior 10 -- totality is unchanged
# ==========================================================================
@pytest.mark.parametrize(
    "bad",
    [None, "", "\x00## Triage\x00PICK: \x00", "## Triage\nPICK:" + "x" * 5000,
     "#" * 4000],
)
def test_b10_never_raises_and_returns_none_or_str(bad):
    r = winner(bad)
    assert r is None or isinstance(r, str)


def test_b10_5000_char_label_line_returns_none():
    assert winner("## Triage\nPICK:" + "x" * 5000) is None


# ==========================================================================
# Behavior 11 -- the decision log heals from the bodies alone (tmp_path only)
# ==========================================================================
def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir (tests/test_iter115_behavior.py
    shape). `repo`/`work_root` are TMP dirs so the real repo/state is NEVER
    touched."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _iter_dir(cfg, iteration):
    return pathlib.Path(cfg.state) / f"iter-{iteration:02d}"


def _scout_body(which, iteration, lens, cands):
    lines = [f"# PM_SCOUT_{which} {EMDASH} iteration {iteration} {EMDASH} lens: {lens}",
             "", "## Slate"]
    lines += [f"## Candidate {c}" for c in cands]
    lines += ["", "## Note to the PM lead", "prose the candidate parser ignores"]
    return "\n".join(lines) + "\n"


def _healed_product(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    d = _iter_dir(cfg, 7)
    d.mkdir(parents=True, exist_ok=True)
    (d / "pm_scout_a.md").write_text(
        _scout_body("A", 7, "narrative-and-docs", ("A1 -- alpha", "A2 -- beta",
                                                   "A3 -- gamma")))
    (d / "pm_scout_b.md").write_text(
        _scout_body("B", 7, "new-capability", ("B1 -- delta",)))
    (d / "pm.md").write_text(f"# PM spec {EMDASH} iteration 7\n\n" + B1_TEXT)
    return cfg


def test_b11_gather_directions_records_the_labelled_winner(tmp_path):
    cfg = _healed_product(tmp_path)
    digest = foundry.gather_directions(cfg)
    assert [e.iteration for e in digest.entries] == [7]
    assert digest.entries[0].winner == "B1"


def test_b11_rendered_directions_doc_carries_the_winner_line(tmp_path):
    cfg = _healed_product(tmp_path)
    doc = foundry.render_directions_doc(foundry.gather_directions(cfg))
    assert "winner: B1" in doc
    assert any(ln.strip() == "winner: B1" for ln in doc.splitlines())
    assert "winner: A1" not in doc


def test_b11_touches_nothing_outside_tmp_path(tmp_path):
    cfg = _healed_product(tmp_path)
    assert pathlib.Path(cfg.state).resolve().is_relative_to(tmp_path.resolve())
    assert pathlib.Path(cfg.repo).resolve().is_relative_to(tmp_path.resolve())


# ==========================================================================
# Behavior 12 -- the PM card teaches the label (ONE tracked file read)
# ==========================================================================
_CARD = _ROOT / "roles" / "pm.md"
_FIVE_WORDS = "reads that uppercase label first"


def test_b12_card_carries_the_five_words_on_one_line():
    text = _CARD.read_text(encoding="utf-8")
    assert _FIVE_WORDS in text
    assert any(_FIVE_WORDS in ln for ln in text.splitlines())


def test_b12_sentence_follows_name_it_inside_duty_1b():
    text = _CARD.read_text(encoding="utf-8")
    flat = " ".join(text.split())
    anchor = "(name it)."
    assert anchor in flat
    after = flat[flat.index(anchor) + len(anchor):].lstrip()
    assert after.startswith("Lead the section with `PICK: **<id>**` on its own line:")
    assert ("the decision log (`directions` / `DIRECTIONS.md`) reads that uppercase "
            "label first, before any other id in the section.") in after[:400]

