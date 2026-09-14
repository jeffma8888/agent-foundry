"""Black-box behaviour tests for iter 337 -- the `learnings-head:` gauge gains a
NEAR-WALL WARN that fires BEFORE the prompt bound starts eliding the pinned
`## Patterns` head.

Spec: products/_platform/state/iter-337/pm.md, Expected Behaviors 1-12.

  audit = learnings_head_audit(text, bullet_cap, head_budget)
  1.  `PROMPT_LEARNINGS_HEAD_NEAR_WALL_CHARS` is a module-level `int` == 1500, declared
      beside the two existing `PROMPT_LEARNINGS_HEAD_*` constants, and read as a module
      GLOBAL inside the audit body (monkeypatch takes effect with no re-import).
  2.  `LearningsHeadAudit` gains exactly two DEFAULTED fields AFTER `worst_loss` --
      `headroom: int | None = None`, `near_wall: bool = False`; the first five names and
      their order are unchanged, the class is still frozen, and the five-keyword
      construction still works.
  3.  Roomy head -> `near_wall is False`, `headroom == head_budget - raw_chars`.
  4.  Headroom of exactly 0, of exactly `margin`, and of one value strictly between ->
      `near_wall is True` AND `over_budget is False` (the interval is CLOSED both ends).
  5.  Over-budget head -> `near_wall is False`, `headroom < 0`; and NO input yields
      `near_wall` and `over_budget` together.
  6.  `head_budget=None` -> `headroom is None`, `near_wall is False`, while
      `bullets`/`raw_chars` still describe the real head.
  7.  No `## Patterns` section, and `""` -> the all-zero, not-over-budget audit;
      `near_wall is False`; nothing raises.
  8.  The six pre-existing fields are UNCHANGED for every input, and iteration 136's
      anti-drift oracle still holds against `learnings_digest`'s own
      `> [head bounded: ...]` notice.
  9.  `learnings_head_line(cfg)` has FOUR outcomes; UNKNOWN and OK carry no WARN token;
      the OK text and the OVER-budget WARN text are BYTE-IDENTICAL to today (frozen
      literals below); every branch returns one non-empty newline-free `str`, never
      `None`, and never raises -- including when `head_bullet_losses` raises.
  10. The NEAR-WALL line carries the WARN token, `raw_chars`, the bullet count, the
      headroom, the margin and a retire/archive remedy, and claims NOTHING is elided.
  11. `run_doctor_cli` prints exactly ONE `learnings-head:` line and its exit code is
      identical across all four branches.
  12. README `# 0.` describes the near-wall outcome and names the new constant, while
      `PLUS SIX drift lines` still appears, `PLUS FIVE drift lines` still does not, and
      iteration 230's byte-frozen tail sentence survives byte-unchanged.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-337 PM spec and the product's
OBSERVABLE surface -- importing the module, CALLING its public functions,
`dataclasses` introspection, driving the doctor CLI in-process, one MECHANICAL regex
census over the shipped module text (no body was read), and reading files under
`tests/` for CONVENTIONS plus the tracked product README. The implementation BODIES of
foundry.py / dispatcher.py, the engineer's notes, the reviewer's notes and `git diff`
were NOT read. The head-region rule and the bullet-BLOCK rule are RE-DERIVED here from
the spec's wording, mirroring `tests/test_iter181_behavior.py`.

Fully offline and deterministic: synthetic fixture strings and `tmp_path` files only --
no git, no network, no subprocess, no sleep, no clock dependence, nothing written
outside `tmp_path`, and NO read of any gitignored `products/*/LEARNINGS.md` (iteration
154's trap: that path is ABSENT in the fresh clone the post-release verifier builds).
"""

from __future__ import annotations

import contextlib
import dataclasses
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

CAP = foundry.PROMPT_LEARNINGS_HEAD_BULLET_CHARS        # 800
BUDGET = foundry.PROMPT_LEARNINGS_HEAD_BUDGET_CHARS     # 10000
MARGIN = foundry.PROMPT_LEARNINGS_HEAD_NEAR_WALL_CHARS  # 1500 (behavior 1)
PREFIX = foundry.LEARNINGS_HEAD_PREFIX
WARN = foundry.LEARNINGS_HEAD_WARN
NOTICE_RE = re.compile(
    r"^> \[head bounded: (\d+) of (\d+) bullets truncated, (\d+) dropped")
ORIGINAL_FIELDS = ("bullets", "raw_chars", "truncated", "dropped", "over_budget")
CARRIED_FIELDS = ORIGINAL_FIELDS + ("worst_loss",)


# --------------------------------------------------------------------------- #
# helpers -- RE-DERIVED from the spec's wording (iter-181 conventions)
# --------------------------------------------------------------------------- #
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
    """The head-region rule: the contiguous slice of lines from the `## Patterns`
    heading up to (exclusive) the first later `## ` heading OR the first lesson line
    (a line left-stripping to `- [`), whichever comes first."""
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


def _head_lines_of(text):
    return _head_text(text).split("\n")


def _blocks(head):
    """A block OPENS on a head line starting with `- ` at COLUMN 0 and runs to the next
    such line or the head's end.  Preamble prose before the first bullet is no block."""
    out, cur = [], None
    for ln in head:
        if ln.startswith("- "):
            if cur is not None:
                out.append(cur)
            cur = [ln]
        elif cur is not None:
            cur.append(ln)
    if cur is not None:
        out.append(cur)
    return out


def _notices(out):
    return [ln for ln in out.split("\n") if ln.startswith("> [head bounded:")]


def _sized(raw_chars, *, per=600, n=12, tag="s"):
    """A synthetic log whose HEAD region measures EXACTLY `raw_chars` characters.

    The last bullet absorbs the difference.  The premise is ASSERTED, never assumed --
    a fixture that silently stops exercising its branch is the failure mode here.
    """
    bs = [_bullet(f"{tag}{i}", per, chr(97 + i % 26)) for i in range(n)]
    base = len(_head_text(_log(bs)))
    grow = raw_chars - base
    assert per + grow >= 1, (raw_chars, base, per)
    bs[-1] = _bullet(f"{tag}{n - 1}", per + grow, "z")
    text = _log(bs)
    assert len(_head_text(text)) == raw_chars, (len(_head_text(text)), raw_chars)
    return text


def _write_cfg(tmp_path, **over):
    data = {
        "name": "demo",
        "repo": str(tmp_path / "repo"),
        "allowed_push_repo": "demo",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / f"config-{len(list(tmp_path.iterdir()))}.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _cfg_for(tmp_path, text=None, *, learnings=None, name="L.md"):
    """A ProductConfig whose `learnings` points into tmp_path (NEVER a real log)."""
    if learnings is None:
        target = tmp_path / name
        target.write_text(text if text is not None else "", encoding="utf-8")
        learnings = str(target)
    return foundry.load_config(str(_write_cfg(tmp_path, learnings=learnings)))


class _Chk:
    """Minimal stand-in check result for the doctor-CLI guards (iter-145 shape)."""

    def __init__(self, name, ok, detail="detail-text"):
        self.name = name
        self.ok = ok
        self.detail = detail


def _stub_checks(monkeypatch, *, fail=None):
    for nm in ("power", "agent", "uv", "remote"):
        monkeypatch.setattr(
            foundry, f"check_{nm}", lambda *a, _n=nm, **k: _Chk(_n, _n != fail))


def _stub_sibling_lines(monkeypatch):
    """Script every OTHER drift line so no doctor test reads live state.  The gauge
    under test is the ONLY unscripted line."""
    for nm in [n for n in dir(foundry)
               if n.endswith("_line") and n != "learnings_head_line"]:
        monkeypatch.setattr(foundry, nm, lambda *a, _n=nm, **k: f"{_n}: scripted")


def _head_report_lines(out):
    return [ln for ln in out.splitlines() if ln.startswith(PREFIX)]


def _doctor_out(cfg):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.run_doctor_cli(cfg)
    return rc, buf.getvalue()


# --------------------------------------------------------------------------- #
# fixtures -- synthetic strings only, with their PREMISES asserted at import
# --------------------------------------------------------------------------- #
UNDER = _log([_bullet("a", 100), _bullet("b", 100, "y")])
FITS = _log([_bullet("a", 1500), _bullet("b", 200, "y"), _bullet("c", 200, "z")])
OVER = _log([_bullet("a", 9000), _bullet("b", 700, "y"), _bullet("c", 700, "z")])
DROPPING = _log([_bullet(f"b{i}", 900) for i in range(20)])
PREAMBLE_ONLY = "\n".join(["## Patterns", "", "just prose, no bullets", "",
                           "## Chronological lessons", "", "- [PM iter01] x", ""])
NOHEAD = "no pinned head at all\n\n- [PM iter01] a lesson\n"

NEAR_ZERO = _sized(BUDGET, tag="z")                   # headroom == 0
NEAR_EDGE = _sized(BUDGET - MARGIN, tag="e")          # headroom == MARGIN
NEAR_MID = _sized(BUDGET - (MARGIN // 2), tag="m")    # strictly between
JUST_ROOMY = _sized(BUDGET - MARGIN - 1, tag="r")     # one char clear of the margin
JUST_OVER = _sized(BUDGET + 50, tag="o")              # over the wall

assert len(_head_text(UNDER)) < BUDGET - MARGIN, len(_head_text(UNDER))
assert len(_head_text(FITS)) < BUDGET - MARGIN, len(_head_text(FITS))
assert len(_head_text(OVER)) > BUDGET, len(_head_text(OVER))
assert len(_head_text(DROPPING)) > BUDGET, len(_head_text(DROPPING))
assert _blocks(_head_lines_of(PREAMBLE_ONLY)) == []
assert _head_text(NOHEAD) is None
assert len(_head_text(NEAR_ZERO)) == BUDGET
assert len(_head_text(NEAR_EDGE)) == BUDGET - MARGIN
assert 0 < BUDGET - len(_head_text(NEAR_MID)) < MARGIN

# TODAY's OK and OVER bodies, as byte-frozen literals (behavior 9).  Verified
# character-for-character against the SHIPPING renderer by
# `test_b9_the_two_frozen_bodies_are_what_the_renderer_returns` -- so this brake
# reds on a re-worded OK/OVER branch, not merely on a re-worded fixture.
OK_LINE_FROZEN = (
    "learnings-head: OK -- pinned `## Patterns` head is 232 chars in 2 bullet(s) "
    "and arrives whole in every stage prompt "
    "(bounds: 800 chars/bullet, 10000 total)"
)
OVER_LINE_FROZEN = (
    "learnings-head: WARN -- pinned `## Patterns` head is 10442 chars in 3 bullet(s) "
    "and does NOT arrive whole: 1 bullet(s) truncated, 0 dropped in EVERY stage "
    "prompt (bounds: 800 chars/bullet, 10000 total); worst is bullet #1 "
    "`**a** " + "x" * 74 + "` (truncated, losing 8209 of its 9009 chars) "
    "-- retire the spent directives"
)


# --------------------------------------------------------------------- Behavior 1
def test_b1_near_wall_constant_is_a_module_level_int_1500():
    value = foundry.PROMPT_LEARNINGS_HEAD_NEAR_WALL_CHARS
    assert isinstance(value, int) and not isinstance(value, bool), repr(value)
    assert value == 1500, value


def test_b1_constant_is_declared_beside_its_two_siblings():
    """MECHANICAL census, no body read: the three `PROMPT_LEARNINGS_HEAD_*` names are
    column-0 declarations within a few lines of each other in the shipped module."""
    src = (_ROOT / "foundry.py").read_text(encoding="utf-8")
    assert "PROMPT_LEARNINGS_HEAD_NEAR_WALL_CHARS" in \
        foundry.prompt_learnings_constants(src)
    at = {}
    for i, ln in enumerate(src.split("\n")):
        m = re.match(r"^(PROMPT_LEARNINGS_HEAD_[A-Z_]+)\s*[:=]", ln)
        if m and m.group(1) not in at:
            at[m.group(1)] = i
    assert set(at) == {"PROMPT_LEARNINGS_HEAD_BUDGET_CHARS",
                       "PROMPT_LEARNINGS_HEAD_BULLET_CHARS",
                       "PROMPT_LEARNINGS_HEAD_NEAR_WALL_CHARS"}, sorted(at)
    # "BESIDE", read mechanically: the three are CONSECUTIVE module-level assignments
    # -- only comments and blank lines separate them, never another binding.  (A
    # documented margin earns a comment block, so a raw line-distance bound is wrong.)
    lo, hi = min(at.values()), max(at.values())
    between = [ln for ln in src.split("\n")[lo:hi + 1]
               if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*[:=]", ln)]
    assert len(between) == 3, between


def test_b1_margin_is_read_as_a_module_global_inside_the_audit_body(monkeypatch):
    # JUST_ROOMY sits ONE char clear of the shipped margin, so widening the margin by
    # one MUST flip the verdict on a SUBSEQUENT call -- with no re-import.
    assert foundry.learnings_head_audit(JUST_ROOMY, CAP, BUDGET).near_wall is False
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_HEAD_NEAR_WALL_CHARS", MARGIN + 1)
    assert foundry.learnings_head_audit(JUST_ROOMY, CAP, BUDGET).near_wall is True
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_HEAD_NEAR_WALL_CHARS", 0)
    assert foundry.learnings_head_audit(NEAR_MID, CAP, BUDGET).near_wall is False
    assert foundry.learnings_head_audit(NEAR_ZERO, CAP, BUDGET).near_wall is True
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_HEAD_NEAR_WALL_CHARS", 9_000_000)
    assert foundry.learnings_head_audit(UNDER, CAP, BUDGET).near_wall is True


# --------------------------------------------------------------------- Behavior 2
def test_b2_exactly_two_new_defaulted_fields_after_worst_loss():
    names = [f.name for f in dataclasses.fields(foundry.LearningsHeadAudit)]
    assert names[:5] == list(ORIGINAL_FIELDS), names
    assert names == list(ORIGINAL_FIELDS) + ["worst_loss", "headroom", "near_wall"], names
    by = {f.name: f for f in dataclasses.fields(foundry.LearningsHeadAudit)}
    assert by["headroom"].default is None
    assert by["near_wall"].default is False
    assert str(by["headroom"].type).replace("'", "") == "int | None"
    assert str(by["near_wall"].type).replace("'", "") == "bool"
    for f in dataclasses.fields(foundry.LearningsHeadAudit):
        if f.name not in ORIGINAL_FIELDS:
            assert f.default is not dataclasses.MISSING, f.name


def test_b2_five_keyword_construction_still_works_and_defaults():
    a = foundry.LearningsHeadAudit(bullets=1, raw_chars=2, truncated=0, dropped=0,
                                   over_budget=False)
    assert (a.bullets, a.raw_chars, a.truncated, a.dropped) == (1, 2, 0, 0)
    assert a.over_budget is False
    assert a.worst_loss is None
    assert a.headroom is None
    assert a.near_wall is False


def test_b2_the_audit_is_still_frozen():
    assert foundry.LearningsHeadAudit.__dataclass_params__.frozen is True
    a = foundry.learnings_head_audit(UNDER, CAP, BUDGET)
    for field, value in (("near_wall", True), ("headroom", 7), ("bullets", 9)):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(a, field, value)


# --------------------------------------------------------------------- Behavior 3
def test_b3_roomy_head_reports_headroom_and_no_near_wall():
    for text in (UNDER, FITS, JUST_ROOMY):
        a = foundry.learnings_head_audit(text, CAP, BUDGET)
        assert a.near_wall is False, (text[:40], a)
        assert a.headroom == BUDGET - a.raw_chars, a
        assert a.headroom > MARGIN, a
        assert a.over_budget is False, a


def test_b3_headroom_formula_holds_for_arbitrary_budgets():
    for budget in (500, 2000, 7500, BUDGET, 40_000):
        for text in (UNDER, FITS, OVER, DROPPING, NEAR_MID):
            a = foundry.learnings_head_audit(text, CAP, budget)
            assert a.headroom == budget - a.raw_chars, (budget, a)


# --------------------------------------------------------------------- Behavior 4
@pytest.mark.parametrize("text,expected", [
    (NEAR_ZERO, 0),
    (NEAR_EDGE, MARGIN),
    (NEAR_MID, MARGIN // 2),
])
def test_b4_the_near_wall_interval_is_closed_at_both_ends(text, expected):
    a = foundry.learnings_head_audit(text, CAP, BUDGET)
    assert a.headroom == expected, a
    assert a.near_wall is True, a
    assert a.over_budget is False, a
    assert (a.truncated, a.dropped) == (0, 0), a
    assert a.worst_loss is None, a


def test_b4_the_closed_interval_holds_for_a_monkeypatched_margin(monkeypatch):
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_HEAD_NEAR_WALL_CHARS", 400)
    for headroom in (0, 1, 399, 400):
        a = foundry.learnings_head_audit(_sized(BUDGET - headroom), CAP, BUDGET)
        assert (a.headroom, a.near_wall, a.over_budget) == (headroom, True, False), a
    a = foundry.learnings_head_audit(_sized(BUDGET - 401), CAP, BUDGET)
    assert (a.headroom, a.near_wall) == (401, False), a


# --------------------------------------------------------------------- Behavior 5
def test_b5_over_budget_head_is_never_near_wall_and_reports_negative_headroom():
    for text in (OVER, DROPPING, JUST_OVER):
        a = foundry.learnings_head_audit(text, CAP, BUDGET)
        assert a.over_budget is True, a
        assert a.near_wall is False, a
        assert a.headroom is not None and a.headroom < 0, a
        assert a.headroom == BUDGET - a.raw_chars, a


def test_b5_no_input_is_ever_both_near_wall_and_over_budget():
    texts = [UNDER, FITS, OVER, DROPPING, PREAMBLE_ONLY, NOHEAD, "", NEAR_ZERO,
             NEAR_EDGE, NEAR_MID, JUST_ROOMY, JUST_OVER]
    texts += [_sized(n) for n in range(BUDGET - 2000, BUDGET + 400, 173)]
    for text in texts:
        for cap in (None, 40, CAP):
            for budget in (None, 60, 1000, BUDGET, 50_000):
                a = foundry.learnings_head_audit(text, cap, budget)
                assert not (a.near_wall and a.over_budget), (cap, budget, a)
                if a.near_wall:
                    assert a.headroom is not None and a.headroom >= 0, a


# --------------------------------------------------------------------- Behavior 6
def test_b6_the_unbounded_call_shape_declares_no_wall_and_no_verdict():
    for text in (UNDER, FITS, OVER, DROPPING, NEAR_ZERO, NEAR_MID, PREAMBLE_ONLY, ""):
        a = foundry.learnings_head_audit(text, CAP, None)
        assert a.headroom is None, a
        assert a.near_wall is False, a
        head = _head_text(text)
        assert a.raw_chars == (0 if head is None else len(head)), (a, head)
        assert a.bullets == (0 if head is None else len(_blocks(head.split("\n")))), a


def test_b6_no_margin_can_make_the_unbounded_shape_warn(monkeypatch):
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_HEAD_NEAR_WALL_CHARS", 10 ** 9)
    for text in (UNDER, NEAR_ZERO, OVER):
        a = foundry.learnings_head_audit(text, CAP, None)
        assert (a.headroom, a.near_wall) == (None, False), a


# --------------------------------------------------------------------- Behavior 7
@pytest.mark.parametrize("text", ["", NOHEAD, "no head\n", "\n\n\n"])
def test_b7_a_head_less_log_is_the_all_zero_not_over_budget_audit(text):
    a = foundry.learnings_head_audit(text, CAP, BUDGET)
    assert (a.bullets, a.raw_chars, a.truncated, a.dropped) == (0, 0, 0, 0), a
    assert a.over_budget is False, a
    assert a.near_wall is False, a
    assert a.worst_loss is None, a
    # AMBIGUITY NOTED (PM feedback): the spec calls this "the all-zero audit" but
    # `headroom` is a REPORT of the declared wall, so behavior 3's formula governs and
    # a head of 0 chars has the FULL budget of headroom.  Either reading keeps
    # `near_wall is False`, which is what the spec pins.
    assert a.headroom == BUDGET, a


def test_b7_nothing_raises_on_degenerate_inputs():
    for text in ("", "\n", NOHEAD, PREAMBLE_ONLY, "## Patterns", "## Patterns\n\n"):
        for cap in (None, 0, 1, CAP):
            for budget in (None, 0, 1, BUDGET):
                a = foundry.learnings_head_audit(text, cap, budget)
                assert isinstance(a, foundry.LearningsHeadAudit)
                assert isinstance(a.near_wall, bool)


# --------------------------------------------------------------------- Behavior 8
def test_b8_the_six_carried_fields_are_untouched_by_the_new_verdict():
    """The carried fields cannot depend on the near-wall margin: re-auditing the same
    input under three margins must leave all six byte-identical."""
    def snap(text, cap, budget):
        a = foundry.learnings_head_audit(text, cap, budget)
        return tuple(
            getattr(a, f) if f != "worst_loss" else (
                None if a.worst_loss is None else
                (a.worst_loss.index, a.worst_loss.label, a.worst_loss.raw_chars,
                 a.worst_loss.elided_chars, a.worst_loss.kind))
            for f in CARRIED_FIELDS)

    for text in (UNDER, FITS, OVER, DROPPING, NEAR_ZERO, NEAR_MID, "", NOHEAD):
        for cap in (None, 40, CAP):
            for budget in (None, 500, BUDGET):
                base = snap(text, cap, budget)
                for margin in (0, 1, 10 ** 9):
                    with pytest.MonkeyPatch.context() as mp:
                        mp.setattr(foundry,
                                   "PROMPT_LEARNINGS_HEAD_NEAR_WALL_CHARS", margin)
                        assert snap(text, cap, budget) == base, (text[:30], margin)


def test_b8_iteration_136_anti_drift_oracle_still_holds():
    """audit.bullets/truncated/dropped == the three numbers `learnings_digest` renders
    in its own `> [head bounded: ...]` notice, and an in-budget head renders none."""
    for text in (OVER, DROPPING):
        for cap, budget in ((CAP, BUDGET), (40, 600), (200, 3000)):
            digest = foundry.learnings_digest(text, 12, None, None, cap, budget)
            notices = _notices(digest)
            a = foundry.learnings_head_audit(text, cap, budget)
            assert len(notices) == 1, (notices, cap, budget)
            m = NOTICE_RE.match(notices[0])
            assert m, notices[0]
            n_trunc, n_bullets, n_drop = (int(m.group(1)), int(m.group(2)),
                                          int(m.group(3)))
            assert (a.truncated, a.bullets, a.dropped) == (n_trunc, n_bullets, n_drop), (
                notices[0], a)
            assert a.over_budget is True, a


def test_b8_an_in_budget_head_still_produces_no_notice_at_all():
    for text in (UNDER, FITS, NEAR_ZERO, NEAR_EDGE, NEAR_MID, JUST_ROOMY):
        a = foundry.learnings_head_audit(text, CAP, BUDGET)
        assert a.over_budget is False, a
        assert _notices(foundry.learnings_digest(text, 12, None, None, CAP, BUDGET)) == []


def test_b8_raw_chars_is_still_the_head_region_length():
    for text in (UNDER, FITS, OVER, DROPPING, NEAR_ZERO, PREAMBLE_ONLY, NOHEAD, ""):
        head = _head_text(text)
        a = foundry.learnings_head_audit(text, CAP, BUDGET)
        assert a.raw_chars == (0 if head is None else len(head)), (a, text[:30])


# --------------------------------------------------------------------- Behavior 9
def _four_lines(tmp_path):
    return {
        "unknown": foundry.learnings_head_line(
            _cfg_for(tmp_path, learnings=str(tmp_path / "absent.md"))),
        "ok": foundry.learnings_head_line(_cfg_for(tmp_path, UNDER, name="ok.md")),
        "near": foundry.learnings_head_line(_cfg_for(tmp_path, NEAR_MID, name="near.md")),
        "over": foundry.learnings_head_line(_cfg_for(tmp_path, OVER, name="over.md")),
    }


def test_b9_there_are_exactly_four_distinct_outcomes(tmp_path):
    lines = _four_lines(tmp_path)
    assert len(set(lines.values())) == 4, lines
    assert "UNKNOWN" in lines["unknown"], lines["unknown"]
    assert WARN not in lines["unknown"], lines["unknown"]
    assert WARN not in lines["ok"], lines["ok"]
    assert WARN in lines["near"], lines["near"]
    assert WARN in lines["over"], lines["over"]
    for key, line in lines.items():
        assert isinstance(line, str) and line, (key, repr(line))
        assert "\n" not in line, (key, repr(line))
        assert line.startswith(PREFIX), (key, line)


def test_b9_the_two_frozen_bodies_are_what_the_renderer_returns(tmp_path):
    assert foundry.learnings_head_line(
        _cfg_for(tmp_path, UNDER, name="ok.md")) == OK_LINE_FROZEN
    assert foundry.learnings_head_line(
        _cfg_for(tmp_path, OVER, name="over.md")) == OVER_LINE_FROZEN


def test_b9_no_branch_raises_or_returns_none(tmp_path):
    for text in (UNDER, FITS, OVER, DROPPING, NEAR_ZERO, NEAR_EDGE, NEAR_MID,
                 JUST_ROOMY, JUST_OVER, PREAMBLE_ONLY, NOHEAD, "", "## Patterns"):
        line = foundry.learnings_head_line(
            _cfg_for(tmp_path, text, name=f"f{abs(hash(text)) % 10 ** 8}.md"))
        assert isinstance(line, str) and line and "\n" not in line, repr(line)
        assert line.startswith(PREFIX), line


def test_b9_a_raising_loss_helper_is_absorbed_on_every_branch(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("scripted loss failure")

    monkeypatch.setattr(foundry, "head_bullet_losses", boom)
    for name, text in (("ok", UNDER), ("near", NEAR_MID), ("over", OVER),
                       ("drop", DROPPING)):
        line = foundry.learnings_head_line(
            _cfg_for(tmp_path, text, name=f"boom-{name}.md"))   # must NOT propagate
        assert line and "\n" not in line, repr(line)
        assert line.startswith(PREFIX), line


def test_b9_an_unreadable_log_is_unknown_not_a_crash(tmp_path):
    d = tmp_path / "a-directory-not-a-file.md"
    d.mkdir()
    line = foundry.learnings_head_line(_cfg_for(tmp_path, learnings=str(d)))
    assert line.startswith(PREFIX) and "UNKNOWN" in line, line
    assert WARN not in line, line


# -------------------------------------------------------------------- Behavior 10
@pytest.mark.parametrize("text", [NEAR_ZERO, NEAR_EDGE, NEAR_MID])
def test_b10_the_near_wall_line_names_headroom_and_margin_and_the_remedy(tmp_path, text):
    a = foundry.learnings_head_audit(text, CAP, BUDGET)
    assert a.near_wall is True, a
    line = foundry.learnings_head_line(
        _cfg_for(tmp_path, text, name=f"nw{a.raw_chars}.md"))
    assert WARN in line, line
    assert str(a.raw_chars) in line, (a.raw_chars, line)
    assert f"{a.bullets} bullet(s)" in line, (a.bullets, line)
    assert str(a.headroom) in line, (a.headroom, line)
    assert str(MARGIN) in line, (MARGIN, line)
    low = line.lower()
    assert ("retire" in low or "archiv" in low), line
    assert "directive" in low, line


@pytest.mark.parametrize("text", [NEAR_ZERO, NEAR_EDGE, NEAR_MID])
def test_b10_the_near_wall_line_claims_nothing_is_elided(tmp_path, text):
    line = foundry.learnings_head_line(
        _cfg_for(tmp_path, text, name=f"clean{len(text)}.md"))
    low = line.lower()
    assert "bullet(s) truncated" not in low, line
    assert "truncated" not in low, line
    assert "dropped" not in low, line
    assert "worst" not in low, line
    assert "losing" not in low, line
    assert foundry.learnings_head_audit(text, CAP, BUDGET).worst_loss is None


def test_b10_the_near_wall_line_is_not_the_over_budget_line(tmp_path):
    near = foundry.learnings_head_line(_cfg_for(tmp_path, NEAR_MID, name="n.md"))
    over = foundry.learnings_head_line(_cfg_for(tmp_path, OVER, name="o.md"))
    assert near != over
    assert "does NOT arrive whole" not in near, near
    assert "does NOT arrive whole" in over, over


# -------------------------------------------------------------------- Behavior 11
@pytest.mark.parametrize("key,text", [("unknown", None), ("ok", UNDER),
                                      ("near", NEAR_MID), ("over", OVER)])
def test_b11_doctor_prints_exactly_one_head_line_per_branch(tmp_path, monkeypatch,
                                                            key, text):
    _stub_checks(monkeypatch)
    _stub_sibling_lines(monkeypatch)
    cfg = (_cfg_for(tmp_path, learnings=str(tmp_path / "gone.md")) if text is None
           else _cfg_for(tmp_path, text, name=f"{key}.md"))
    rc, out = _doctor_out(cfg)
    lines = _head_report_lines(out)
    assert len(lines) == 1, f"expected exactly ONE head line, got {lines}"
    assert lines[0] == foundry.learnings_head_line(cfg), (lines[0],)
    assert rc == 0, (rc, out)


def test_b11_the_exit_code_is_identical_across_all_four_branches(tmp_path, monkeypatch):
    _stub_checks(monkeypatch)
    _stub_sibling_lines(monkeypatch)
    codes = {}
    for key, text in (("unknown", None), ("ok", UNDER), ("near", NEAR_MID),
                      ("over", OVER), ("drop", DROPPING)):
        cfg = (_cfg_for(tmp_path, learnings=str(tmp_path / "gone2.md")) if text is None
               else _cfg_for(tmp_path, text, name=f"rc-{key}.md"))
        codes[key] = _doctor_out(cfg)[0]
    assert len(set(codes.values())) == 1, codes
    assert set(codes.values()) == {0}, codes


def test_b11_a_near_wall_head_does_not_mask_a_failing_check(tmp_path, monkeypatch):
    """The gauge stays a pure reporter: the exit code still comes from the Checks."""
    _stub_checks(monkeypatch, fail="uv")
    _stub_sibling_lines(monkeypatch)
    rc_near, out_near = _doctor_out(_cfg_for(tmp_path, NEAR_MID, name="f-near.md"))
    rc_ok, _ = _doctor_out(_cfg_for(tmp_path, UNDER, name="f-ok.md"))
    assert rc_near == rc_ok != 0, (rc_near, rc_ok)
    assert len(_head_report_lines(out_near)) == 1, out_near


# -------------------------------------------------------------------- Behavior 12
README = _ROOT / "README.md"
# README `# 0.`'s byte-frozen tail sentence (iteration 230 froze it; this iteration
# inserts MID-entry and must leave it byte-unchanged).
README_FROZEN_TAIL = (
    "NO drift line ever changes doctor's own exit code, and `run_doctor` itself is "
    "still exactly four Checks:"
)


def _readme_entry(number: int) -> str:
    """The text of README numbered entry `# <number>.`, up to the next numbered entry."""
    text = README.read_text(encoding="utf-8")
    start = text.index(f"# {number}. ")
    rest = text[start + 1:]
    m = re.search(r"\n# \d+\. ", rest)
    return rest[:m.start()] if m else rest


def test_b12_readme_entry_zero_describes_the_near_wall_outcome():
    entry = _readme_entry(0)
    assert "PROMPT_LEARNINGS_HEAD_NEAR_WALL_CHARS" in entry, entry[:200]
    low = entry.lower()
    assert "near-wall" in low, entry[:200]
    assert "fourth outcome" in low, entry[:200]


def test_b12_readme_entry_zero_keeps_its_six_drift_line_count_word():
    entry = _readme_entry(0)
    assert "PLUS SIX drift lines" in entry, entry[:200]
    assert "PLUS FIVE drift lines" not in entry, entry[:200]
    assert "seventh drift line" not in entry.lower(), entry[:200]


def test_b12_iteration_230_frozen_tail_sentence_survives_byte_unchanged():
    assert README_FROZEN_TAIL in README.read_text(encoding="utf-8")
    entry = _readme_entry(0)
    assert README_FROZEN_TAIL in entry, entry[-200:]
    # INSERTED MID-ENTRY: the new clause lands before iteration 230's frozen tail, and
    # the frozen tail is still the LAST sentence of the entry's prose.
    tail_at = entry.index(README_FROZEN_TAIL)
    assert entry.index("PROMPT_LEARNINGS_HEAD_NEAR_WALL_CHARS") < tail_at
    prose = entry[:tail_at + len(README_FROZEN_TAIL)]
    assert prose.rstrip().endswith(README_FROZEN_TAIL), prose[-120:]
    assert "exceeding it alone no longer WARNs)" in entry, "iter-138 clause survives"


# ------------------------------------------------- acceptance-criteria oracles
def test_ac_modules_still_import_and_no_new_surface_was_added():
    assert foundry.__name__ == "foundry" and dispatcher.__name__ == "dispatcher"
    drift = sorted(n for n in dir(foundry) if n.endswith("_line"))
    assert "learnings_head_line" in drift
    assert "learnings_head_near_wall_line" not in drift, drift
    assert not hasattr(foundry, "run_learnings_head_cli"), "no new CLI verb"


def test_ac_this_module_reads_only_tracked_files():
    """Iteration 154's trap: a gitignored precondition passes here and BREAKS in the
    fresh clone the post-release verifier builds.  Every fixture above is a synthetic
    in-memory string, and the only repo files this module reads are TRACKED ones."""
    body = pathlib.Path(__file__).read_text(encoding="utf-8")
    # (the census pattern matches its OWN source line, so keep only filename-shaped
    # hits -- a self-match is not a repo read)
    read = {m for m in re.findall(r'_ROOT / "([^"]+)"', body)
            if re.fullmatch(r"[\w./-]+", m)}
    assert read == {"foundry.py", "README.md"}, read
    for tracked in ("foundry.py", "README.md"):
        assert (_ROOT / tracked).is_file(), tracked
    # ...and every `learnings=` target this module hands a ProductConfig is built
    # under `tmp_path`, never a repo path (the census skips its own pattern hits).
    targets = [m
               for ln in body.split("\n")
               if not ln.strip().startswith("#") and "findall" not in ln
               for m in re.findall(r"learnings=([^,)\n]+)", ln)]
    assert targets, "the cfg fixtures disappeared"
    # `None` is `_cfg_for`'s own keyword default and its sentinel for "build the log
    # yourself"; the branch that consumes it must write under tmp_path, so pin that
    # branch here rather than exempting the token blindly.
    assert "target = tmp_path / name" in body
    # (`str(d` is how the `)`-terminated census clips `str(d)`, and `d` is itself
    # `tmp_path / "a-directory-not-a-file.md"` -- pin that binding, not the spelling.)
    assert 'd = tmp_path / "a-directory-not-a-file.md"' in body
    for target in targets:
        assert ("tmp_path" in target
                or target in ("learnings", "str(d", "None")), target
