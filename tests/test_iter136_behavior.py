"""Black-box behaviour tests for iter 136 -- size the pinned `## Patterns` steering
head and report it as ONE non-blocking `doctor` line, plus a re-statused discovery
plan doc.

Spec: products/_platform/state/iter-136/pm.md, Expected Behaviors 1-13.
(Behavior 14 -- the steering-head surgery itself -- is verified by MEASUREMENT in
the tester log, NOT by a suite test: its subject is a gitignored file that is ABSENT
in the fresh clone the post-release gate uses.)

  learnings_head_audit(text, bullet_cap=800, head_budget=10000)  -- pure
  1.  an OVER-BUDGET 9000/700/700-char head reports bullets==3,
      raw_chars==len(verbatim head), truncated==1, dropped==0, over_budget True.
      (Sizes raised at iteration 138: per-bullet truncation is now a LAST RESORT
      that runs only when the verbatim head exceeds the TOTAL budget, so the
      original 1200/300/300 head -- under the budget -- now arrives whole.)
  2.  a 3x200-char head reports the same bullets/raw_chars discipline with
      truncated==0, dropped==0, over_budget False.
  3.  head-region rule: the head ends at the FIRST later `## ` heading OR the first
      lesson line (left-strips to `- [`), whichever comes first -- an archive
      section's bullets and a trailing lesson line are BOTH excluded.
  4.  the unbounded call shape (None, None) never reports clipping, yet still
      reports the real bullets/raw_chars.
  5.  no `## Patterns` section, and empty text, report all-zero/False and do not
      raise.
  6.  ANTI-DRIFT ORACLE: for the SAME text and caps the audit's numbers equal the
      ones `learnings_digest` renders in its own `> [head bounded: C of B bullets
      truncated, D dropped ...]` notice, and an under-budget head produces NO
      notice line at all.
  learnings_head_line(cfg)  -- the one-line reporter, shaped like live_lag_line
  7.  over-budget file -> exactly ONE line carrying the prefix constant, the WARN
      token, the bullet count, the raw head char count and the budget exceeded.
  8.  within-budget file -> one line with the prefix and `OK`, and NO WARN token.
  9.  missing / unreadable path -> one non-empty line saying `UNKNOWN`, no WARN,
      no exception ("I cannot tell" is never reported as a problem).
  10. seam robustness: a RAISING `learnings_head_audit` still yields one non-empty
      `UNKNOWN` line -- proof the audit is called by its BARE module name.
  doctor surface
  11. `run_doctor_cli` prints the head line IN ADDITION to the four
      `[PASS]/[FAIL]` lines, the live-lag line and the summary line, exactly once,
      and NEVER changes the exit code (0 all-pass even when over budget, 1 on a
      failing check).
  12. `run_doctor` still returns exactly four `Check`s named power, agent, uv,
      remote, in that order (the iter-01 contract).
  doc truth
  13. `docs/DISCOVERY_LOOP_PLAN.md` carries a verified STATUS block: each of bites
      1-4 named, >= 4 SHIPPED markers, >= 1 SATISFIED marker, and every original
      bite heading plus the section-8 embargo text still present (nothing deleted).
  Plus two acceptance-criteria oracles: the result type is FROZEN, and this file
  reads no gitignored steering log.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-136 PM spec and the
product's own OBSERVABLE surface -- importing the module, CALLING its public
functions, reading `__doc__` / `inspect.signature`, running the doctor CLI, and
reading files under `tests/` for CONVENTIONS. The implementation BODIES of
foundry.py / dispatcher.py, the engineer's notes, the reviewer's notes, the
fix-review notes and `git diff` were NOT read. The head-region rule and the
head-text measurement are RE-DERIVED here from the spec's own wording
(`_head_text`), never mirrored from the implementation.

Fully offline and deterministic: synthetic fixture strings and `tmp_path` files
only -- no subprocess, no git, no network, no agent run, no sleep, no clock
dependence, and nothing written outside `tmp_path`. One SHIPPED doc file is read
as prose because Behavior 13 is about that doc.
"""
import contextlib
import dataclasses
import inspect
import io
import json
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

_DOC = _ROOT / "docs" / "DISCOVERY_LOOP_PLAN.md"
_THIS = pathlib.Path(__file__).resolve()

# The shipped prompt bounds this iteration reports against (spec's "Why").
CAP = foundry.PROMPT_LEARNINGS_HEAD_BULLET_CHARS      # 800
BUDGET = foundry.PROMPT_LEARNINGS_HEAD_BUDGET_CHARS   # 10000

# iter-118's rendered notice, re-declared here (spec Behavior 6 names its shape).
NOTICE_RE = re.compile(
    r"^> \[head bounded: (\d+) of (\d+) bullets truncated, (\d+) dropped"
)


# --------------------------------------------------------------------------
# fixtures + helpers -- RE-DERIVED from the spec's wording
# --------------------------------------------------------------------------
def _bullet(name, n, ch="x"):
    return f"- **{name}** " + ch * n


def _log(head_bullets, *, tail=True, archive=()):
    """A synthetic learnings log: a `## Patterns` head, an optional archive
    section, then the chronological lessons."""
    parts = ["## Patterns", ""]
    for b in head_bullets:
        parts += [b, ""]
    if archive:
        parts += ["## Archive of completed operator directives", ""]
        for b in archive:
            parts += [b, ""]
    if tail:
        parts += ["## Chronological lessons", "", "- [PM iter01] a lesson", ""]
    return "\n".join(parts)


def _head_text(text):
    """Spec Behavior 3's rule, re-derived: the contiguous slice of input lines from
    the `## Patterns` heading up to (exclusive) the first later `## ` heading OR the
    first lesson line (a line left-stripping to `- [`), whichever comes first."""
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


# RE-FIXTURED at iteration 138, which made per-bullet truncation a LAST RESORT: the
# bounds now elide nothing unless the VERBATIM head exceeds the TOTAL budget. The
# original 1200/300/300 head was over the per-bullet CAP but 8,158 chars UNDER
# `BUDGET`, so it arrives WHOLE under the new order and can no longer exercise the
# truncate-then-drop path at all. Sizes are raised so the head genuinely overflows
# while the elision this fixture exists to measure is unchanged (bullets==3,
# truncated==1, dropped==0). No assertion was weakened; the PREMISE was repaired,
# and it is asserted below rather than assumed.
OVER = _log([_bullet("a", 9000), _bullet("b", 700, "y"), _bullet("c", 700, "z")])
assert len(_head_text(OVER)) > BUDGET, (
    f"OVER must exceed the total head budget to exercise the bounds: "
    f"{len(_head_text(OVER))} <= {BUDGET}")
UNDER = _log([_bullet("a", 200), _bullet("b", 200, "y"), _bullet("c", 200, "z")])
DROPPING = _log([_bullet(f"b{i}", 900) for i in range(20)])


class _Chk:
    """Minimal stand-in check result (mirrors the suite's convention)."""

    def __init__(self, name, ok, detail="detail-text"):
        self.name = name
        self.ok = ok
        self.detail = detail


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


def _stub_checks(monkeypatch, ok=True):
    for nm in ("power", "agent", "uv", "remote"):
        monkeypatch.setattr(foundry, f"check_{nm}", lambda *a, _n=nm, **k: _Chk(_n, ok))


def _head_lines(out):
    return [ln for ln in out.splitlines() if foundry.LEARNINGS_HEAD_PREFIX in ln]


# --------------------------------------------------------------------- Behavior 1
def test_b1_over_budget_head_is_sized_exactly():
    a = foundry.learnings_head_audit(OVER, CAP, BUDGET)
    assert a.bullets == 3, a
    assert a.raw_chars == len(_head_text(OVER)), (a.raw_chars, len(_head_text(OVER)))
    assert a.truncated == 1, a
    assert a.dropped == 0, a
    assert a.over_budget is True, a


def test_b1_defaults_match_the_shipped_prompt_bounds():
    """The documented default call shape must equal the explicit one."""
    assert foundry.learnings_head_audit(OVER) == foundry.learnings_head_audit(
        OVER, CAP, BUDGET)
    sig = inspect.signature(foundry.learnings_head_audit)
    assert sig.parameters["bullet_cap"].default == CAP
    assert sig.parameters["head_budget"].default == BUDGET


# --------------------------------------------------------------------- Behavior 2
def test_b2_within_budget_head_reports_no_clipping():
    a = foundry.learnings_head_audit(UNDER, CAP, BUDGET)
    assert a.bullets == 3, a
    assert a.raw_chars == len(_head_text(UNDER)), a
    assert (a.truncated, a.dropped, a.over_budget) == (0, 0, False), a


# --------------------------------------------------------------------- Behavior 3
def test_b3_head_stops_at_the_next_h2_heading():
    text = _log([_bullet("a", 10), _bullet("b", 10, "y")],
                archive=[_bullet("old1", 10), _bullet("old2", 10)])
    a = foundry.learnings_head_audit(text, CAP, BUDGET)
    assert a.bullets == 2, f"archive bullets leaked into the head: {a}"
    assert a.raw_chars == len(_head_text(text)), a
    assert "old1" not in _head_text(text)


def test_b3_head_stops_at_the_first_lesson_line():
    text = ("## Patterns\n\n" + _bullet("a", 10) + "\n\n" + _bullet("b", 10, "y")
            + "\n- [PM iter01] a lesson\n" + _bullet("c", 10, "z") + "\n")
    a = foundry.learnings_head_audit(text, CAP, BUDGET)
    assert a.bullets == 2, f"a bullet BELOW the first lesson line was counted: {a}"
    assert a.raw_chars == len(_head_text(text)), a


def test_b3_whichever_boundary_comes_first_wins():
    """Same two bullets, two different terminators -> the same head."""
    by_h2 = _log([_bullet("a", 10), _bullet("b", 10, "y")])
    by_lesson = "## Patterns\n\n" + _bullet("a", 10) + "\n\n" + _bullet("b", 10, "y") \
        + "\n- [PM iter01] x\n"
    assert foundry.learnings_head_audit(by_h2, CAP, BUDGET).bullets == \
        foundry.learnings_head_audit(by_lesson, CAP, BUDGET).bullets == 2


# --------------------------------------------------------------------- Behavior 4
@pytest.mark.parametrize("text", [OVER, UNDER, DROPPING])
def test_b4_unbounded_call_shape_never_reports_clipping(text):
    a = foundry.learnings_head_audit(text, None, None)
    assert (a.truncated, a.dropped, a.over_budget) == (0, 0, False), a
    bounded = foundry.learnings_head_audit(text, CAP, BUDGET)
    assert a.bullets == bounded.bullets, "bullet count must not depend on the caps"
    assert a.raw_chars == bounded.raw_chars == len(_head_text(text)), a


# --------------------------------------------------------------------- Behavior 5
@pytest.mark.parametrize("text", [
    "",
    "no patterns section here at all\n",
    "# Title\n\n## Chronological lessons\n\n- [PM iter01] a\n",
    "## Patterns are discussed elsewhere\n",   # not a `## Patterns` head start? see note
])
def test_b5_degenerate_inputs_are_total(text):
    a = foundry.learnings_head_audit(text, CAP, BUDGET)
    assert (a.truncated, a.dropped, a.over_budget) == (0, 0, False), (text[:30], a)
    assert a.bullets == 0, (text[:30], a)


def test_b5_no_patterns_section_is_zero_not_placeholder():
    a = foundry.learnings_head_audit("## Chronological lessons\n\n- [PM iter01] a\n",
                                     CAP, BUDGET)
    assert a.bullets == 0 and a.raw_chars >= 0 and a.over_budget is False, a


# --------------------------------------------------------------------- Behavior 6
@pytest.mark.parametrize("text,label", [(OVER, "over"), (DROPPING, "dropping")])
def test_b6_audit_numbers_equal_the_digest_notice(text, label):
    """The audit must not be a second, divergent implementation of the bounding."""
    a = foundry.learnings_head_audit(text, CAP, BUDGET)
    digest = foundry.learnings_digest(text, recent=10, head_bullet_chars=CAP,
                                      head_chars=BUDGET)
    notices = [ln for ln in digest.split("\n") if NOTICE_RE.match(ln)]
    assert len(notices) == 1, f"{label}: expected ONE head-bounded notice, got {notices}"
    c, b, d = (int(x) for x in NOTICE_RE.match(notices[0]).groups())
    assert (a.truncated, a.bullets, a.dropped) == (c, b, d), (
        f"{label}: audit {a} disagrees with the digest notice {notices[0]!r}")
    assert a.over_budget is True, a


def test_b6_under_budget_head_emits_no_notice_at_all():
    a = foundry.learnings_head_audit(UNDER, CAP, BUDGET)
    assert a.over_budget is False, a
    digest = foundry.learnings_digest(UNDER, recent=10, head_bullet_chars=CAP,
                                      head_chars=BUDGET)
    assert not [ln for ln in digest.split("\n") if ln.startswith("> [head bounded")], (
        "over_budget False must mean the digest carries NO head-bounded notice")


# --------------------------------------------------------------------- Behavior 7
def test_b7_over_budget_file_reports_one_warn_line(tmp_path):
    cfg = _cfg_for(tmp_path, DROPPING)
    line = foundry.learnings_head_line(cfg)
    a = foundry.learnings_head_audit(DROPPING, CAP, BUDGET)
    assert line and "\n" not in line, repr(line)
    assert foundry.LEARNINGS_HEAD_PREFIX in line, line
    assert foundry.LEARNINGS_HEAD_WARN in line, line
    for token in (str(a.bullets), str(a.raw_chars), str(BUDGET)):
        assert token in line, f"missing {token!r} in: {line}"


# --------------------------------------------------------------------- Behavior 8
def test_b8_within_budget_file_reports_ok_without_warn(tmp_path):
    line = foundry.learnings_head_line(_cfg_for(tmp_path, UNDER))
    assert line and "\n" not in line, repr(line)
    assert foundry.LEARNINGS_HEAD_PREFIX in line and "OK" in line, line
    assert foundry.LEARNINGS_HEAD_WARN not in line, line


# --------------------------------------------------------------------- Behavior 9
def test_b9_missing_file_is_unknown_not_a_warning(tmp_path):
    cfg = _cfg_for(tmp_path, learnings=str(tmp_path / "nope" / "absent.md"))
    line = foundry.learnings_head_line(cfg)
    assert line and "\n" not in line and "UNKNOWN" in line, repr(line)
    assert foundry.LEARNINGS_HEAD_WARN not in line, line


def test_b9_unreadable_path_is_unknown_and_does_not_raise(tmp_path):
    a_dir = tmp_path / "a_directory"
    a_dir.mkdir()
    line = foundry.learnings_head_line(_cfg_for(tmp_path, learnings=str(a_dir)))
    assert line and "\n" not in line and "UNKNOWN" in line, repr(line)
    assert foundry.LEARNINGS_HEAD_WARN not in line, line


# -------------------------------------------------------------------- Behavior 10
def test_b10_raising_audit_seam_is_absorbed(tmp_path, monkeypatch):
    cfg = _cfg_for(tmp_path, DROPPING)

    def boom(*a, **k):
        raise RuntimeError("scripted audit failure")

    monkeypatch.setattr(foundry, "learnings_head_audit", boom)
    line = foundry.learnings_head_line(cfg)     # must NOT propagate
    assert line and "\n" not in line and "UNKNOWN" in line, repr(line)
    assert foundry.LEARNINGS_HEAD_WARN not in line, line


# -------------------------------------------------------------------- Behavior 11
def _doctor_out(cfg):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.run_doctor_cli(cfg)
    return rc, buf.getvalue()


def test_b11_doctor_prints_the_head_line_in_addition(tmp_path, monkeypatch):
    _stub_checks(monkeypatch)
    monkeypatch.setattr(foundry, "live_lag_line", lambda *a, **k: "ZZLAGZZ one line")
    rc, out = _doctor_out(_cfg_for(tmp_path, DROPPING))
    assert len(_head_lines(out)) == 1, f"expected exactly ONE head line:\n{out}"
    assert foundry.LEARNINGS_HEAD_WARN in _head_lines(out)[0], out
    assert len([ln for ln in out.splitlines() if "ZZLAGZZ" in ln]) == 1, out
    for nm in ("power", "agent", "uv", "remote"):
        assert f"[PASS] {nm}" in out, f"doctor lost its {nm} check line:\n{out}"
    assert [ln for ln in out.splitlines() if ln.startswith("doctor:")], (
        f"summary line vanished:\n{out}")
    assert rc == 0, out


def test_b11_over_budget_head_does_not_change_the_exit_code(tmp_path, monkeypatch):
    codes = {}
    for label, text in (("over", DROPPING), ("ok", UNDER)):
        for ok in (True, False):
            _stub_checks(monkeypatch, ok=ok)
            monkeypatch.setattr(foundry, "live_lag_line", lambda *a, **k: "lag line")
            cfg = _cfg_for(tmp_path, text, name=f"L-{label}-{ok}.md")
            codes[(label, ok)] = _doctor_out(cfg)[0]
    assert codes[("over", True)] == codes[("ok", True)] == 0, codes
    assert codes[("over", False)] == codes[("ok", False)] == 1, codes


def test_b11_doctor_survives_a_raising_head_seam(tmp_path, monkeypatch):
    """The head line is non-blocking: it can never break doctor."""
    _stub_checks(monkeypatch)
    monkeypatch.setattr(foundry, "live_lag_line", lambda *a, **k: "lag line")

    def boom(*a, **k):
        raise RuntimeError("scripted audit failure")

    monkeypatch.setattr(foundry, "learnings_head_audit", boom)
    rc, out = _doctor_out(_cfg_for(tmp_path, DROPPING))
    assert rc == 0, out
    assert len(_head_lines(out)) == 1 and "UNKNOWN" in _head_lines(out)[0], out


# -------------------------------------------------------------------- Behavior 12
def test_b12_run_doctor_still_returns_the_four_iter01_checks(tmp_path, monkeypatch):
    _stub_checks(monkeypatch)
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    assert [c.name for c in foundry.run_doctor(cfg)] == \
        ["power", "agent", "uv", "remote"]


# -------------------------------------------------------------------- Behavior 13
def _status_block(text):
    lines = text.split("\n")
    start = next((i for i, ln in enumerate(lines)
                  if ln.startswith("## ") and "STATUS" in ln), None)
    assert start is not None, "no `## ...STATUS...` heading in the discovery plan doc"
    block = [lines[start]]
    for ln in lines[start + 1:]:
        if ln.startswith("## "):
            break
        block.append(ln)
    return "\n".join(block)


def test_b13_discovery_plan_carries_a_verified_status_block():
    text = _DOC.read_text()
    block = _status_block(text)
    for n in (1, 2, 3, 4):
        assert f"Bite {n}" in block, f"status block never mentions Bite {n}:\n{block}"
    assert block.count("SHIPPED") >= 4, f"fewer than four SHIPPED markers:\n{block}"
    assert "SATISFIED" in block, f"no SATISFIED marker for the embargo:\n{block}"


def test_b13_status_block_anchors_each_bite_to_code():
    """A status claim without an anchor is the same rot being fixed."""
    block = _status_block(_DOC.read_text())
    anchors = re.findall(r"(?:foundry\.py|roles/[\w.-]+):\d+", block)
    assert len(anchors) >= 4, f"fewer than four code anchors in the block: {anchors}"


def test_b13_nothing_was_deleted_from_the_original_plan():
    text = _DOC.read_text()
    for n in (1, 2, 3, 4):
        assert re.search(rf"^##\s*\d+\.\s*Bite {n}\b", text, re.M), \
            f"original `Bite {n}` heading was removed"
    assert re.search(r"^##\s*\d+\.\s*Priority", text, re.M), \
        "the section-8 Priority heading was removed"
    assert "Do not ship another" in text, "the original embargo sentence was removed"


# ----------------------------------------------- Acceptance-criteria oracles
def test_ac_result_type_is_frozen():
    """Frozen, and the five fields THIS iteration shipped are all present.

    iter 181 appended a DEFAULTED `worst_loss`, so an exact-SET pin failed on a
    purely additive change. Re-aimed at the two properties it was protecting --
    the five original names are still there, and every field beyond them is
    defaulted, so this iteration's five-keyword construction still works.
    """
    a = foundry.learnings_head_audit(UNDER, CAP, BUDGET)
    assert dataclasses.is_dataclass(a)
    fields = dataclasses.fields(a)
    assert {"bullets", "raw_chars", "truncated", "dropped",
            "over_budget"} <= {f.name for f in fields}
    for extra in fields:
        if extra.name in ("bullets", "raw_chars", "truncated", "dropped",
                          "over_budget"):
            continue
        assert (extra.default is not dataclasses.MISSING
                or extra.default_factory is not dataclasses.MISSING), extra
    assert foundry.LearningsHeadAudit(
        bullets=0, raw_chars=0, truncated=0, dropped=0, over_budget=False)
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.bullets = 999


def test_ac_audit_is_deterministic_and_clock_free():
    assert foundry.learnings_head_audit(OVER, CAP, BUDGET) == \
        foundry.learnings_head_audit(OVER, CAP, BUDGET)


def test_ac_no_suite_test_here_reads_the_gitignored_steering_log():
    """The real steering log is ABSENT in the fresh clone the post-release gate
    uses, so a test that read it would ship a BROKEN post-release.

    Mechanical: every READ call site in this file is inspected, and none may name
    the steering log or the product state dir. Prose that merely cites the spec
    path is not a read, so the guard is scoped to read call sites rather than to
    the whole file. The forbidden tokens are assembled at runtime so this guard
    cannot trip on its own source."""
    forbidden = ("LEARNINGS" + ".md", "_plat" + "form", "products/")
    reads = ("read_text(", "read_bytes(", "open(", "readlines(")
    offenders = [ln for ln in _THIS.read_text().split("\n")
                 if any(r in ln for r in reads)
                 and any(t in ln for t in forbidden)]
    assert not offenders, f"read call site names a gitignored path: {offenders}"
    # And the only SHIPPED file this module reads is the discovery-plan doc.
    assert _DOC.is_file() and _DOC.name == "DISCOVERY_LOOP_PLAN.md"
