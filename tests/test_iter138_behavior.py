"""Black-box behaviour tests for iter 138 -- the pinned `## Patterns` steering head
arrives VERBATIM whenever its raw size fits the TOTAL head budget; per-bullet
truncation and bottom-dropping are a LAST RESORT that engage only when it does not.

Spec: products/_platform/state/iter-138/pm.md, Expected Behaviors 1-5.

  learnings_digest(text, ..., head_bullet_chars=None, head_chars=None)
  1.  FITS-WHOLE: raw head <= `head_chars` AND at least one bullet longer than
      `head_bullet_chars` -> the head region is byte-identical to the raw head
      slice, carries ZERO truncation markers, and NO `> [head bounded:` notice.
      Covered at the inclusive boundary too (raw == head_chars is a FIT; raw ==
      head_chars + 1 is not), and the lesson tail is proven unaffected.
  2.  OVER-BUDGET (unchanged): raw head > `head_chars` -> every over-cap bullet is
      truncated to EXACTLY the cap and ends in the marker, the head region fits the
      budget, admission is top-down (first bullet kept, bottom dropped), and there
      is EXACTLY ONE accurate notice as the LAST line of the head region.
  3.  ORACLE: `learnings_head_audit` agrees with what the digest renders in BOTH
      cases -- its counts equal the notice's numbers over-budget, and it reports
      truncated==0/dropped==0/over_budget==False exactly when no notice is emitted.
  4.  UNBOUNDED: both head bounds None -> the head region is the verbatim raw head
      and no notice, for a fitting AND an over-budget AND a dropping fixture (the
      None call shape can never clip).
  5.  `learnings_head_line` reports the OK branch for a fits-whole fixture (an
      over-cap bullet UNDER budget is no longer a warning) and WARN for an
      over-budget one.
  Plus acceptance-criteria oracles: `foundry` + `dispatcher` stay importable, the
  two head constants keep their shipped VALUES (out of scope this iteration), and
  the audit result type stays frozen with its five fields.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-138 PM spec and the
product's OBSERVABLE surface -- importing the module, CALLING its public functions,
`inspect`/`dataclasses` introspection, and reading files under `tests/` for
CONVENTIONS. The implementation BODIES of foundry.py / dispatcher.py, the
engineer's notes, the reviewer's notes and `git diff` were NOT read. The head-region
rule is RE-DERIVED here from the spec's own wording (`_head_text`), never mirrored
from the implementation.

Fully offline and deterministic: synthetic fixture strings and `tmp_path` files only
-- no subprocess, no git, no network, no agent run, no sleep, no clock dependence,
and nothing written outside `tmp_path`.
"""
import dataclasses
import json
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

CAP = foundry.PROMPT_LEARNINGS_HEAD_BULLET_CHARS      # 800
BUDGET = foundry.PROMPT_LEARNINGS_HEAD_BUDGET_CHARS   # 10000
MARKER = foundry.LEARNINGS_TRUNCATION_MARKER          # " [...]"
NOTICE_PREFIX = "> [head bounded:"
NOTICE_RE = re.compile(
    r"^> \[head bounded: (\d+) of (\d+) bullets truncated, (\d+) dropped")


# --------------------------------------------------------------------------
# fixtures + helpers -- RE-DERIVED from the spec's wording
# --------------------------------------------------------------------------
def _bullet(name, n, ch="x"):
    return f"- **{name}** " + ch * n


def _log(head_bullets, *, tail=True):
    """A synthetic learnings log: a `## Patterns` head then chronological lessons."""
    parts = ["## Patterns", ""]
    for b in head_bullets:
        parts += [b, ""]
    if tail:
        parts += ["## Chronological lessons", "", "- [PM iter01] a lesson", ""]
    return "\n".join(parts)


def _head_text(text):
    """The head region rule, re-derived: the contiguous slice of input lines from the
    `## Patterns` heading up to (exclusive) the first later `## ` heading OR the first
    lesson line (a line left-stripping to `- [`), whichever comes first."""
    lines = text.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("## Patterns"):
            start = i
            break
    if start is None:
        return None
    head = [lines[start]]
    for ln in lines[start + 1:]:
        s = ln.lstrip()
        if s.startswith("## ") or s.startswith("- ["):
            break
        head.append(ln)
    return "\n".join(head)


def _rendered_head(out):
    """The head region as the digest RENDERED it: from its `## Patterns` line up to
    (exclusive) the next `## ` heading it emits."""
    lines = out.split("\n")
    start = next((i for i, ln in enumerate(lines)
                  if ln.lstrip().startswith("## Patterns")), None)
    if start is None:
        return ""
    out_lines = [lines[start]]
    for ln in lines[start + 1:]:
        if ln.lstrip().startswith("## "):
            break
        out_lines.append(ln)
    return "\n".join(out_lines).rstrip("\n")


def _notices(out):
    return [ln for ln in out.split("\n") if ln.startswith(NOTICE_PREFIX)]


def _bullet_lines(region):
    return [ln for ln in region.split("\n") if ln.lstrip().startswith("- ")]


# FITS-WHOLE: one bullet WAY over the per-bullet cap, whole head far under budget.
FITS = _log([_bullet("a", 1500), _bullet("b", 200, "y"), _bullet("c", 200, "z")])
# OVER-BUDGET: the verbatim head genuinely exceeds the TOTAL budget.
OVER = _log([_bullet("a", 9000), _bullet("b", 700, "y"), _bullet("c", 700, "z")])
# DROPPING: many over-cap bullets -> even after truncation the head must shed some.
DROPPING = _log([_bullet(f"b{i}", 900) for i in range(20)])

# The fixtures' PREMISES are asserted, never assumed (a fixture that silently stops
# exercising its branch is the failure mode this guards).
assert len(_head_text(FITS)) <= BUDGET, len(_head_text(FITS))
assert any(len(b) > CAP for b in _bullet_lines(_head_text(FITS)))
assert len(_head_text(OVER)) > BUDGET, len(_head_text(OVER))
assert len(_head_text(DROPPING)) > BUDGET, len(_head_text(DROPPING))


def _write_cfg(tmp_path, **over):
    data = {
        "name": "demo",
        "repo": str(tmp_path / "repo"),
        "allowed_push_repo": "demo",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _cfg_for(tmp_path, text=None, *, learnings=None, name="L.md"):
    """A ProductConfig whose `learnings` points into tmp_path."""
    if learnings is None:
        target = tmp_path / name
        target.write_text(text if text is not None else "")
        learnings = str(target)
    return foundry.load_config(str(_write_cfg(tmp_path, learnings=learnings)))


# --------------------------------------------------------------------- Behavior 1
def test_b1_fitting_head_is_emitted_verbatim():
    out = foundry.learnings_digest(FITS, head_bullet_chars=CAP, head_chars=BUDGET)
    raw = _head_text(FITS)
    assert _rendered_head(out) == raw.rstrip("\n"), _rendered_head(out)[:400]
    assert raw.rstrip("\n") in out


def test_b1_fitting_head_carries_no_marker_and_no_notice():
    out = foundry.learnings_digest(FITS, head_bullet_chars=CAP, head_chars=BUDGET)
    region = _rendered_head(out)
    assert MARKER not in region, region[:400]
    assert _notices(out) == [], _notices(out)
    # the over-cap bullet survives at its FULL length, cap notwithstanding
    longest = max(len(b) for b in _bullet_lines(region))
    assert longest > CAP, longest


def test_b1_boundary_is_inclusive_at_exactly_the_budget():
    raw = _head_text(FITS)
    exact = foundry.learnings_digest(FITS, head_bullet_chars=CAP,
                                     head_chars=len(raw))
    assert _rendered_head(exact) == raw.rstrip("\n")
    assert _notices(exact) == []
    one_short = foundry.learnings_digest(FITS, head_bullet_chars=CAP,
                                         head_chars=len(raw) - 1)
    assert len(_notices(one_short)) == 1, _notices(one_short)
    assert MARKER in _rendered_head(one_short)


def test_b1_lesson_tail_is_unaffected_by_the_fits_whole_path():
    out = foundry.learnings_digest(FITS, head_bullet_chars=CAP, head_chars=BUDGET)
    assert "- [PM iter01] a lesson" in out
    assert "Recent lessons" in out


# --------------------------------------------------------------------- Behavior 2
def test_b2_over_cap_bullets_are_truncated_to_exactly_the_cap():
    out = foundry.learnings_digest(OVER, head_bullet_chars=CAP, head_chars=BUDGET)
    region = _rendered_head(out)
    bullets = _bullet_lines(region)
    assert bullets, region[:300]
    for b in bullets:
        assert len(b) <= CAP, (len(b), b[:80])
        if b.endswith(MARKER):
            assert len(b) == CAP, (len(b), CAP)
    assert any(b.endswith(MARKER) for b in bullets), bullets[:2]


def test_b2_over_budget_head_fits_the_budget_and_keeps_the_top():
    out = foundry.learnings_digest(DROPPING, head_bullet_chars=CAP,
                                   head_chars=BUDGET)
    region = _rendered_head(out)
    assert len(region) <= BUDGET, len(region)
    assert "**b0**" in region                      # admitted top-down
    assert "**b19**" not in region                 # bottom dropped


def test_b2_exactly_one_accurate_notice_ends_the_head_region():
    for text in (OVER, DROPPING):
        out = foundry.learnings_digest(text, head_bullet_chars=CAP,
                                       head_chars=BUDGET)
        notices = _notices(out)
        assert len(notices) == 1, notices
        region_lines = [ln for ln in _rendered_head(out).split("\n") if ln.strip()]
        assert region_lines[-1] == notices[0], region_lines[-3:]
        m = NOTICE_RE.match(notices[0])
        assert m, notices[0]
        a = foundry.learnings_head_audit(text, CAP, BUDGET)
        assert (int(m.group(1)), int(m.group(2)), int(m.group(3))) == \
            (a.truncated, a.bullets, a.dropped), (notices[0], a)


# --------------------------------------------------------------------- Behavior 3
def test_b3_audit_agrees_with_the_digest_in_the_fits_whole_case():
    a = foundry.learnings_head_audit(FITS, CAP, BUDGET)
    assert a.raw_chars == len(_head_text(FITS)), (a.raw_chars, a)
    assert a.bullets == 3, a
    assert (a.truncated, a.dropped, a.over_budget) == (0, 0, False), a
    out = foundry.learnings_digest(FITS, head_bullet_chars=CAP, head_chars=BUDGET)
    assert _notices(out) == []


def test_b3_audit_agrees_with_the_digest_in_the_over_budget_case():
    for text in (OVER, DROPPING):
        a = foundry.learnings_head_audit(text, CAP, BUDGET)
        assert a.over_budget is True, (text[:40], a)
        assert a.raw_chars == len(_head_text(text)), a
        assert a.truncated > 0 or a.dropped > 0, a
        out = foundry.learnings_digest(text, head_bullet_chars=CAP,
                                       head_chars=BUDGET)
        assert len(_notices(out)) == 1, _notices(out)


def test_b3_audit_never_reports_clipping_it_would_not_cause():
    """No-notice and no-clipping are the SAME condition, in both directions."""
    for text in (FITS, OVER, DROPPING):
        for cap, budget in ((CAP, BUDGET), (100, 400), (CAP, len(_head_text(text)))):
            a = foundry.learnings_head_audit(text, cap, budget)
            out = foundry.learnings_digest(text, head_bullet_chars=cap,
                                           head_chars=budget)
            clipped = bool(a.truncated or a.dropped)
            assert clipped == bool(_notices(out)), (text[:40], cap, budget, a,
                                                    _notices(out))
            assert clipped == a.over_budget, a


# --------------------------------------------------------------------- Behavior 4
def test_b4_unbounded_callers_never_clip_the_head():
    for text in (FITS, OVER, DROPPING):
        out = foundry.learnings_digest(text, head_bullet_chars=None,
                                       head_chars=None)
        raw = _head_text(text)
        assert _rendered_head(out) == raw.rstrip("\n"), text[:40]
        assert _notices(out) == [], _notices(out)
        a = foundry.learnings_head_audit(text, None, None)
        assert (a.truncated, a.dropped, a.over_budget) == (0, 0, False), a
        assert a.raw_chars == len(raw), a


def test_b4_default_digest_call_shape_is_unbounded():
    """The head bounds default to None, so the pre-iter-118 call shape is unclipped."""
    assert foundry.learnings_digest(OVER) == foundry.learnings_digest(
        OVER, head_bullet_chars=None, head_chars=None)
    assert _notices(foundry.learnings_digest(OVER)) == []


# --------------------------------------------------------------------- Behavior 5
def test_b5_head_line_reports_ok_for_a_fits_whole_file(tmp_path):
    line = foundry.learnings_head_line(_cfg_for(tmp_path, FITS))
    assert line and "\n" not in line, repr(line)
    assert foundry.LEARNINGS_HEAD_PREFIX in line and "OK" in line, line
    assert foundry.LEARNINGS_HEAD_WARN not in line, line


def test_b5_head_line_still_warns_for_an_over_budget_file(tmp_path):
    for text in (OVER, DROPPING):
        line = foundry.learnings_head_line(_cfg_for(tmp_path, text))
        assert line and "\n" not in line, repr(line)
        assert foundry.LEARNINGS_HEAD_PREFIX in line, line
        assert foundry.LEARNINGS_HEAD_WARN in line, line


def test_b5_head_line_is_unchanged_for_a_missing_file(tmp_path):
    line = foundry.learnings_head_line(
        _cfg_for(tmp_path, learnings=str(tmp_path / "nope" / "absent.md")))
    assert line and "\n" not in line, repr(line)
    assert "UNKNOWN" in line, line
    assert foundry.LEARNINGS_HEAD_WARN not in line, line


# ------------------------------------------------ acceptance-criteria oracles
def test_ac_modules_import_and_head_constants_keep_their_values():
    assert foundry.__name__ == "foundry" and dispatcher.__name__ == "dispatcher"
    assert CAP == 800, CAP
    assert BUDGET == 10000, BUDGET


def test_ac_audit_result_type_is_frozen_with_its_five_fields():
    a = foundry.learnings_head_audit(FITS, CAP, BUDGET)
    assert dataclasses.is_dataclass(a)
    assert [f.name for f in dataclasses.fields(a)] == [
        "bullets", "raw_chars", "truncated", "dropped", "over_budget"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.bullets = 99


def test_ac_empty_and_headless_text_do_not_raise():
    for text in ("", "no head here\n", "- [PM iter01] lesson only\n"):
        a = foundry.learnings_head_audit(text, CAP, BUDGET)
        assert (a.bullets, a.truncated, a.dropped, a.over_budget) == \
            (0, 0, 0, False), (text, a)
        out = foundry.learnings_digest(text, head_bullet_chars=CAP,
                                       head_chars=BUDGET)
        assert _notices(out) == []
