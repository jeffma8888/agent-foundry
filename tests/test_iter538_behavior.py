"""Iteration 538 -- BLACK-BOX card tests: roles/tester.md gains a `## SHIP HAZARDS`
section (H1 pinned sha / line number of a ship-rewritten file, H2 wall-clock ratio,
H3 unguarded optional-extra import) and roles/reviewer.md gains a
`## Ship-hazard tests -- each one is BLOCKING` section making each a [BLOCKING] finding.

Reads only TRACKED files (roles/, roadmap files) plus `git show HEAD:<card>` computed at
test time (skipped when git/HEAD is unavailable). This module itself honours H1-H3: no
sha literal, no line-number pin, no timing assertion, no optional-extra import.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

TESTER = _ROOT / "roles" / "tester.md"
REVIEWER = _ROOT / "roles" / "reviewer.md"
ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"

TESTER_HEADING = "## SHIP HAZARDS -- a NEW test must survive the ship that carries it"


def _lines(path: pathlib.Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _index_of_heading(lines: list[str], prefix: str) -> int:
    hits = [i for i, ln in enumerate(lines) if ln.startswith(prefix)]
    assert len(hits) == 1, (prefix, hits)
    return hits[0]


# ---------------------------------------------------------------- pure checkers
def _tester_section(text: str) -> str | None:
    """Body between the SHIP HAZARDS heading and `## Rules`, or None if misplaced/absent."""
    lines = text.splitlines()
    heads = [i for i, ln in enumerate(lines) if ln == TESTER_HEADING]
    if len(heads) != 1:
        return None
    h = heads[0]
    duties = [i for i, ln in enumerate(lines) if ln.startswith("## Duties")]
    rules = [i for i, ln in enumerate(lines) if ln.startswith("## Rules")]
    if len(duties) != 1 or len(rules) != 1:
        return None
    if not (duties[0] < h < rules[0]):
        return None
    return "\n".join(lines[h + 1:rules[0]])


def _tester_section_ok(text: str) -> bool:
    body = _tester_section(text)
    if body is None:
        return False
    if not all(lbl in body for lbl in ("H1", "H2", "H3")):
        return False
    low = body.lower()
    needed = ("sha", "line number", "directions.md", "wall-clock", "optional",
              "extra", "pytest.importorskip")
    return all(s in low for s in needed)


def _reviewer_section(text: str) -> tuple[str, str] | None:
    """(heading, body) of the single `## ...Ship-hazard...` section, correctly placed."""
    lines = text.splitlines()
    heads = [i for i, ln in enumerate(lines)
             if ln.startswith("## ") and "ship-hazard" in ln.lower()]
    if len(heads) != 1:
        return None
    h = heads[0]
    adv = [i for i, ln in enumerate(lines)
           if ln.startswith("## Advisory `test-quality` scan")]
    out = [i for i, ln in enumerate(lines) if ln.startswith("## Output")]
    if len(adv) != 1 or len(out) != 1 or not (adv[0] < h < out[0]):
        return None
    nxt = [i for i in range(h + 1, len(lines)) if lines[i].startswith("## ")]
    end = nxt[0] if nxt else len(lines)
    return lines[h], "\n".join(lines[h + 1:end])


def _reviewer_section_ok(text: str) -> bool:
    sec = _reviewer_section(text)
    if sec is None:
        return False
    heading, body = sec
    if "test-quality" in heading:
        return False
    for tok in ("[BLOCKING]", "[NIT]", "H1", "H2", "H3", "roles/tester.md", "SHIP HAZARDS"):
        if tok not in body:
            return False
    low = body.lower()
    return all(s in low for s in ("wall-clock", "importorskip", "line number"))


def _is_subsequence(old: list[str], new: list[str]) -> bool:
    it = iter(new)
    return all(any(x == y for y in it) for x in old)


def _drop_section(text: str, heading_pred) -> str:
    lines = text.splitlines()
    out, skipping = [], False
    for ln in lines:
        if ln.startswith("## "):
            skipping = heading_pred(ln)
        if not skipping:
            out.append(ln)
    return "\n".join(out) + "\n"


def _git_head(path: str) -> str:
    if shutil.which("git") is None:
        pytest.skip("git unavailable")
    r = subprocess.run(["git", "-C", str(_ROOT), "show", f"HEAD:{path}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"HEAD:{path} unavailable")
    return r.stdout


# ---------------------------------------------------------------- Behavior 1-2
def test_b1_tester_heading_once_between_duties_and_rules():
    lines = _lines(TESTER)
    assert lines.count(TESTER_HEADING) == 1
    h = lines.index(TESTER_HEADING)
    assert _index_of_heading(lines, "## Duties") < h < _index_of_heading(lines, "## Rules")


def test_b2_tester_section_names_h1_h2_h3_and_vocabulary():
    text = TESTER.read_text(encoding="utf-8")
    body = _tester_section(text)
    assert body is not None
    for lbl in ("H1", "H2", "H3"):
        assert lbl in body, lbl
    low = body.lower()
    for s in ("sha", "line number", "directions.md", "wall-clock", "optional",
              "extra", "pytest.importorskip"):
        assert s in low, s
    assert _tester_section_ok(text)


def test_b1_b2_checker_rejects_bad_tester_fixtures():
    text = TESTER.read_text(encoding="utf-8")
    # section removed -> rejected
    gone = _drop_section(text, lambda ln: ln.startswith("## SHIP HAZARDS"))
    assert not _tester_section_ok(gone)
    # section moved after `## Rules` -> rejected
    body = _tester_section(text)
    assert body is not None
    moved = gone.rstrip("\n") + "\n\n" + TESTER_HEADING + "\n" + body + "\n"
    assert not _tester_section_ok(moved)
    # duplicated heading -> rejected
    assert not _tester_section_ok(text + "\n" + TESTER_HEADING + "\n")
    # missing H3 vocabulary -> rejected
    stripped = text.replace("importorskip", "skipper").replace("H3", "Hx")
    assert not _tester_section_ok(stripped)


# ---------------------------------------------------------------- Behavior 3-4
def test_b3_reviewer_ship_hazard_section_placed_and_worded():
    text = REVIEWER.read_text(encoding="utf-8")
    heads = [ln for ln in text.splitlines()
             if ln.startswith("## ") and "ship-hazard" in ln.lower()]
    assert len(heads) == 1, heads
    sec = _reviewer_section(text)
    assert sec is not None, "section misplaced (must sit after advisory scan, before Output)"
    _, body = sec
    for tok in ("[BLOCKING]", "[NIT]", "H1", "H2", "H3", "roles/tester.md", "SHIP HAZARDS"):
        assert tok in body, tok
    low = body.lower()
    for s in ("wall-clock", "importorskip", "line number"):
        assert s in low, s
    assert _reviewer_section_ok(text)


def test_b4_reviewer_heading_not_test_quality_and_one_advisory_section_still_nit():
    text = REVIEWER.read_text(encoding="utf-8")
    sec = _reviewer_section(text)
    assert sec is not None
    assert "test-quality" not in sec[0]
    lines = text.splitlines()
    tq = [i for i, ln in enumerate(lines) if ln.startswith("## ") and "test-quality" in ln]
    assert len(tq) == 1, tq
    nxt = [i for i in range(tq[0] + 1, len(lines)) if lines[i].startswith("## ")]
    adv_body = "\n".join(lines[tq[0] + 1:nxt[0] if nxt else len(lines)])
    assert "ALWAYS" in adv_body and "[NIT]" in adv_body


def test_b3_b4_checker_rejects_bad_reviewer_fixtures():
    text = REVIEWER.read_text(encoding="utf-8")
    sec = _reviewer_section(text)
    assert sec is not None
    heading, _ = sec
    gone = _drop_section(text, lambda ln: "ship-hazard" in ln.lower())
    assert not _reviewer_section_ok(gone)
    # heading renamed to mention test-quality -> rejected
    assert not _reviewer_section_ok(text.replace(heading, heading + " (test-quality)"))
    # [BLOCKING] downgraded inside the section -> rejected
    body_only = text.split(heading, 1)[1].split("\n## Output", 1)[0]
    weakened = text.replace(body_only, body_only.replace("[BLOCKING]", "[NIT]"))
    assert not _reviewer_section_ok(weakened)


# ---------------------------------------------------------------- Behavior 5-7
@pytest.mark.parametrize("card", [TESTER, REVIEWER], ids=["tester", "reviewer"])
def test_b5_no_preship_in_either_card(card):
    assert "preship" not in card.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("card", [TESTER, REVIEWER], ids=["tester", "reviewer"])
def test_b6_role_card_verbs_unchanged(card):
    assert foundry.role_card_verbs(card.read_text(encoding="utf-8")) == ("test-quality",)


def test_b6_role_card_verbs_discriminates():
    text = TESTER.read_text(encoding="utf-8")
    extra = text + "\nRun `python3 foundry.py dormancy --config X` too.\n"
    assert foundry.role_card_verbs(extra) != ("test-quality",)


def test_b7_tester_card_pure_ascii():
    bad = [ln for ln in _lines(TESTER) if not ln.isascii()]
    assert bad == []


def test_b7_reviewer_added_lines_ascii():
    sec = _reviewer_section(REVIEWER.read_text(encoding="utf-8"))
    assert sec is not None
    heading, body = sec
    assert heading.isascii()
    assert all(ln.isascii() for ln in body.splitlines())
    head = _git_head("roles/reviewer.md").splitlines()
    head_set = set(head)
    added = [ln for ln in _lines(REVIEWER) if ln not in head_set]
    assert all(ln.isascii() for ln in added), [ln for ln in added if not ln.isascii()]


# ---------------------------------------------------------------- Behavior 8
@pytest.mark.parametrize("rel", ["roles/tester.md", "roles/reviewer.md"])
def test_b8_edit_is_additive_vs_head(rel):
    old = _git_head(rel).splitlines()
    new = _lines(_ROOT / rel)
    assert _is_subsequence(old, new)


def test_b8_tester_duty_1b_still_present():
    assert any(ln.startswith("1b.") for ln in _lines(TESTER))


def test_b8_subsequence_checker_discriminates():
    old = ["a", "b", "c"]
    assert _is_subsequence(old, ["a", "x", "b", "c"])
    assert not _is_subsequence(old, ["a", "c", "b"])
    assert not _is_subsequence(old, ["a", "b"])


# ---------------------------------------------------------------- Behavior 9
def test_b9_roadmap_ledger_row_and_archive_bullet():
    rows = [ln for ln in _lines(ROADMAP) if ln.startswith("- iter 538 ")]
    assert len(rows) >= 1
    assert all(len(r) <= 120 for r in rows), [len(r) for r in rows]
    assert any(ln.startswith("- **iter 538 ") for ln in _lines(ARCHIVE))
