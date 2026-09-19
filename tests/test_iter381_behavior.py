"""Iteration 381 -- black-box behavior tests (isolated tester seat).

Spec: products/_platform/state/iter-381/pm.md, Expected Behaviors 1-7.

  1. `learnings_head_region(text)` returns exactly the head lines the audit sizes.
  2. `head_unowned_lines(head)` is `()` for `[]`, a preamble-only head, a clean head.
  3. On a head mirroring the live corruption it returns exactly the five orphan indices.
  4. Purity: no mutation, never raises, every index is a non-blank non-`- ` line.
  5. `learnings_head_line` appends ONE `unowned` clause on all three sized branches.
  6. Two-sided: a clean head renders BYTE-IDENTICAL to the pre-change line (frozen
     literals minted from HEAD 3871c4f's own `learnings_head_line` in the tester seat);
     the UNKNOWN branch is unchanged and carries no clause.
  7. Composite: the doctor CLI prints exactly ONE head line carrying the clause; a
     raising helper degrades to the existing UNKNOWN branch, never a propagated error.

Every fixture is a synthetic string written under tmp_path.  Nothing here reads
`products/*/LEARNINGS.md` or any other gitignored path (OPERATOR 2026-08-11).
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402,F401  (import-safety probe -- the product quality bar)

CAP = foundry.PROMPT_LEARNINGS_HEAD_BULLET_CHARS        # 800
BUDGET = foundry.PROMPT_LEARNINGS_HEAD_BUDGET_CHARS     # 10000
MARGIN = foundry.PROMPT_LEARNINGS_HEAD_NEAR_WALL_CHARS  # 1500
PREFIX = foundry.LEARNINGS_HEAD_PREFIX
WARN = foundry.LEARNINGS_HEAD_WARN
CLAUSE_MARK = " -- and "          # the clause is appended after this separator


# --------------------------------------------------------------------------- #
# helpers -- RE-DERIVED from the spec's wording, never from the implementation
# --------------------------------------------------------------------------- #
def _bullet(name, n, ch="x"):
    return f"- **{name}** " + ch * n


TAIL = ["## Chronological lessons", "", "- [PM iter01] a lesson", ""]
PREAMBLE = [
    "## Patterns",
    "",
    "Durable, recurring rules distilled from the chronological lessons below.",
    "Read this head first; the tail is the full history.",
    "",
]
PROSE_1 = "pipeline. Proposed fix: a flush-left prose line whose `- ` opener was lost"
PROSE_2 = "and a second flush-left prose line that belongs to nobody"
ORPHAN_1 = "  indented orphan continuation one"
ORPHAN_2 = "  indented orphan continuation two"
ORPHAN_3 = "  indented orphan continuation three"
CORRUPTION = [PROSE_1, PROSE_2, "", ORPHAN_1, ORPHAN_2, ORPHAN_3, ""]
UNOWNED_LINES = [PROSE_1, PROSE_2, ORPHAN_1, ORPHAN_2, ORPHAN_3]


def _padding(k, per=600):
    """k extra clean bullets (each with one indented continuation) used to size a head."""
    out = []
    for i in range(k):
        out += [_bullet(f"p{i}", per, chr(97 + i % 26)), f"  continuation of p{i}", ""]
    return out


def _clean_head(*, a=60, b=60, c=60, pad=0, per=600):
    return PREAMBLE + [
        _bullet("A", a, "a"), "  indented continuation of A", "",
        _bullet("B", b, "b"), "  indented continuation of B", "",
        _bullet("C", c, "c"), "  indented continuation of C", "",
    ] + _padding(pad, per)


def _corrupt_head(*, a=60, b=60, c=60, pad=0, per=600):
    """Behavior 3's shape: preamble, A (+1 indented), B, blank, two flush-left prose
    lines, blank, three indented lines, then C (+1 indented)."""
    return PREAMBLE + [
        _bullet("A", a, "a"), "  indented continuation of A", "",
        _bullet("B", b, "b"), "",
        *CORRUPTION,
        _bullet("C", c, "c"), "  indented continuation of C", "",
    ] + _padding(pad, per)


def _text(head):
    return "\n".join(head + TAIL)


def _head_text(text):
    """The spec's region rule, re-derived: from the `## Patterns` line through
    (exclusive) the first later `## ` heading OR the first line left-stripping to `- [`."""
    lines = text.split("\n")
    start = next((i for i, ln in enumerate(lines)
                  if ln.lstrip().startswith("## Patterns")), None)
    if start is None:
        return None
    head = [lines[start]]
    for ln in lines[start + 1:]:
        s = ln.lstrip()
        if s.startswith("## ") or s.startswith("- ["):
            break
        head.append(ln)
    return "\n".join(head)


def _sized(builder, raw_chars, *, pad=12, per=600):
    """A head whose region measures EXACTLY `raw_chars`; the last padding bullet
    absorbs the difference.  The premise is asserted, never assumed."""
    base = builder(pad=pad, per=per)
    grow = raw_chars - len("\n".join(base))
    assert per + grow >= 1, (raw_chars, len("\n".join(base)))
    head = base[:-3] + [_bullet(f"p{pad - 1}", per + grow, "z"),
                        f"  continuation of p{pad - 1}", ""]
    assert len("\n".join(head)) == raw_chars, (len("\n".join(head)), raw_chars)
    return head


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


def _clause(line):
    """The appended clause, if any: everything from the FIRST ` -- and ` on."""
    i = line.find(CLAUSE_MARK)
    return "" if i < 0 else line[i:]


class _Chk:
    def __init__(self, name, ok, detail="detail-text"):
        self.name, self.ok, self.detail = name, ok, detail


def _stub_checks(monkeypatch, *, fail=None):
    for nm in ("power", "agent", "uv", "remote"):
        monkeypatch.setattr(
            foundry, f"check_{nm}", lambda *a, _n=nm, **k: _Chk(_n, _n != fail))


def _stub_sibling_lines(monkeypatch):
    """Script every OTHER drift line so the doctor run reads no live state."""
    for nm in [n for n in dir(foundry)
               if n.endswith("_line") and n != "learnings_head_line"]:
        monkeypatch.setattr(foundry, nm, lambda *a, _n=nm, **k: f"{_n}: scripted")


def _doctor_out(cfg):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.run_doctor_cli(cfg)
    return rc, buf.getvalue()


def _head_report_lines(out):
    return [ln for ln in out.splitlines() if ln.startswith(PREFIX)]


# --------------------------------------------------------------------------- #
# fixtures -- premises asserted at import time
# --------------------------------------------------------------------------- #
CLEAN_OK = _clean_head()
CLEAN_NEAR = _sized(_clean_head, BUDGET - MARGIN // 2)
CLEAN_OVER = _clean_head(c=9800)
CORRUPT_OK = _corrupt_head()
CORRUPT_NEAR = _sized(_corrupt_head, BUDGET - MARGIN // 2)
CORRUPT_OVER = _corrupt_head(c=9800)
PREAMBLE_ONLY = PREAMBLE + ["Just prose after the heading, no bullet at all.", ""]
EXPECTED_IDX = tuple(CORRUPT_OK.index(ln) for ln in UNOWNED_LINES)
EXPECTED_CHARS = len("\n".join(UNOWNED_LINES))

for _h in (CLEAN_OK, CORRUPT_OK):
    assert len("\n".join(_h)) < BUDGET - MARGIN, len("\n".join(_h))
for _h in (CLEAN_NEAR, CORRUPT_NEAR):
    assert 0 < BUDGET - len("\n".join(_h)) < MARGIN, len("\n".join(_h))
for _h in (CLEAN_OVER, CORRUPT_OVER):
    assert len("\n".join(_h)) > BUDGET, len("\n".join(_h))
for _h in (CLEAN_OK, CLEAN_NEAR, CLEAN_OVER, CORRUPT_OK, CORRUPT_NEAR, CORRUPT_OVER,
           PREAMBLE_ONLY):
    assert _head_text(_text(_h)).split("\n") == _h       # region == the head list
assert EXPECTED_IDX == tuple(sorted(EXPECTED_IDX)) and len(EXPECTED_IDX) == 5
assert all(not ln.startswith("- ") and ln.strip() for ln in UNOWNED_LINES)

SIZED = [("ok", CORRUPT_OK), ("near", CORRUPT_NEAR), ("over", CORRUPT_OVER)]
BRANCH_WORDS = {"ok": ["OK"], "near": [WARN, "STILL arrives whole"],
                "over": [WARN, "truncated"]}

# Behavior 6: BYTE-FROZEN pre-change lines.  Minted in the tester seat by loading
# `git show 3871c4f:foundry.py` (HEAD before the fold) as a second module via
# spec_from_file_location and calling ITS `learnings_head_line` on the three CLEAN
# fixtures and the missing-file cfg (the mint is recorded in iteration 381's tester.md).
FROZEN_OK = (
    "learnings-head: OK -- pinned `## Patterns` head is 435 chars in 3 bullet(s) "
    "and arrives whole in every stage prompt (bounds: 800 chars/bullet, 10000 total)"
)
FROZEN_NEAR = (
    "learnings-head: WARN -- pinned `## Patterns` head is 9250 chars in 15 bullet(s) "
    "and STILL arrives whole, but with only 750 chars of headroom under the "
    "10000-char total (margin 1500, cap 800 chars/bullet) -- retire or archive the "
    "spent directives NOW: past that wall the bound starts eliding head blocks from "
    "the BOTTOM in EVERY stage prompt"
)
FROZEN_OVER = (
    "learnings-head: WARN -- pinned `## Patterns` head is 10175 chars in 3 bullet(s) "
    "and does NOT arrive whole: 1 bullet(s) truncated, 0 dropped in EVERY stage "
    "prompt (bounds: 800 chars/bullet, 10000 total); worst is bullet #3 "
    "`**C** " + "c" * 74 + "` (truncated, losing 9038 of its 9838 chars) "
    "-- retire the spent directives"
)
FROZEN_MISSING = (
    "learnings-head: UNKNOWN -- no readable learnings log at missing.md; cannot size "
    "the pinned `## Patterns` head that every stage prompt carries"
)
FROZEN = {"ok": (CLEAN_OK, FROZEN_OK), "near": (CLEAN_NEAR, FROZEN_NEAR),
          "over": (CLEAN_OVER, FROZEN_OVER)}


# --------------------------------------------------------------------- Behavior 1
def test_b1_helpers_exist_as_module_level_callables():
    assert callable(getattr(foundry, "learnings_head_region", None))
    assert callable(getattr(foundry, "head_unowned_lines", None))


@pytest.mark.parametrize("head", [CLEAN_OK, CORRUPT_OK, CLEAN_NEAR, CORRUPT_OVER,
                                  PREAMBLE_ONLY])
def test_b1_region_is_exactly_what_the_audit_sizes(head):
    text = _text(head)
    region = foundry.learnings_head_region(text)
    assert isinstance(region, list) and all(isinstance(x, str) for x in region)
    assert region[0].lstrip().startswith("## Patterns"), region[0]
    assert region == head, (region, head)
    audit = foundry.learnings_head_audit(text, None, None)
    assert len("\n".join(region)) == audit.raw_chars, (len("\n".join(region)), audit)


def test_b1_region_matches_the_audit_for_the_bounded_call_shape_too():
    text = _text(CORRUPT_NEAR)
    region = foundry.learnings_head_region(text)
    assert len("\n".join(region)) == foundry.learnings_head_audit(text, CAP, BUDGET).raw_chars


def test_b1_a_lesson_line_terminates_the_region_without_any_later_heading():
    head = CLEAN_OK
    text = "\n".join(head + ["- [PM iter01] a lesson with no heading above it", ""])
    region = foundry.learnings_head_region(text)
    assert region == head, region
    assert not any(ln.lstrip().startswith("- [") for ln in region)
    assert len("\n".join(region)) == foundry.learnings_head_audit(text, None, None).raw_chars


def test_b1_an_indented_lesson_line_also_terminates_the_region():
    head = CLEAN_OK
    text = "\n".join(head + ["   - [PM iter01] indented lesson", ""])
    assert foundry.learnings_head_region(text) == head


def test_b1_a_later_heading_terminates_the_region():
    head = CLEAN_OK
    text = "\n".join(head + ["## Something else", "", "prose", ""])
    assert foundry.learnings_head_region(text) == head


@pytest.mark.parametrize("text", ["", "no pinned head at all\n\n- [PM iter01] a lesson\n",
                                  "## Chronological lessons\n\n- [PM iter01] x\n",
                                  "# Patterns\n\n- **a** x\n"])
def test_b1_no_patterns_heading_means_empty_region_and_zero_raw_chars(text):
    assert foundry.learnings_head_region(text) == []
    assert foundry.learnings_head_audit(text, None, None).raw_chars == 0


def test_b1_a_bare_patterns_heading_is_a_one_line_region():
    assert foundry.learnings_head_region("## Patterns") == ["## Patterns"]
    assert foundry.learnings_head_audit("## Patterns", None, None).raw_chars == \
        len("## Patterns")


# --------------------------------------------------------------------- Behavior 2
def test_b2_head_unowned_lines_empty_head_is_empty_tuple():
    out = foundry.head_unowned_lines([])
    assert out == () and isinstance(out, tuple), repr(out)


def test_b2_preamble_only_head_has_no_unowned_lines():
    assert foundry.head_unowned_lines(PREAMBLE_ONLY) == ()
    assert foundry.head_unowned_lines(["## Patterns"]) == ()
    assert foundry.head_unowned_lines(["## Patterns", "", "prose", "more prose"]) == ()


@pytest.mark.parametrize("head", [CLEAN_OK, CLEAN_NEAR, CLEAN_OVER])
def test_b2_a_clean_head_has_no_unowned_lines(head):
    out = foundry.head_unowned_lines(head)
    assert out == () and isinstance(out, tuple), repr(out)


def test_b2_trailing_blank_lines_and_blank_lines_between_bullets_are_clean():
    head = ["## Patterns", "", "- **a** x", "", "", "- **b** y", "  cont", "", "", ""]
    assert foundry.head_unowned_lines(head) == ()


# --------------------------------------------------------------------- Behavior 3
def test_b3_the_live_corruption_shape_yields_exactly_the_five_orphan_indices():
    out = foundry.head_unowned_lines(CORRUPT_OK)
    assert out == EXPECTED_IDX, (out, EXPECTED_IDX)
    assert [CORRUPT_OK[i] for i in out] == UNOWNED_LINES


def test_b3_indices_are_ascending_and_a_tuple():
    out = foundry.head_unowned_lines(CORRUPT_OK)
    assert isinstance(out, tuple)
    assert list(out) == sorted(out) and len(set(out)) == len(out)


def test_b3_no_index_from_a_c_or_the_preamble_and_never_a_blank():
    out = foundry.head_unowned_lines(CORRUPT_OK)
    ia, ic = CORRUPT_OK.index(_bullet("A", 60, "a")), CORRUPT_OK.index(_bullet("C", 60, "c"))
    owned = set(range(0, len(PREAMBLE))) | {ia, ia + 1} | {ic, ic + 1}
    assert not (set(out) & owned), (out, owned)
    assert all(CORRUPT_OK[i].strip() for i in out)
    assert not any(CORRUPT_OK[i] == "" for i in out)


@pytest.mark.parametrize("head", [CORRUPT_NEAR, CORRUPT_OVER])
def test_b3_the_five_indices_survive_padding_bullets_after_c(head):
    out = foundry.head_unowned_lines(head)
    assert [head[i] for i in out] == UNOWNED_LINES, out


def test_b3_the_first_flush_left_line_breaks_the_block_and_later_indented_lines_follow():
    """Only lines AT and AFTER the first flush-left line are unowned; the indented
    continuation BEFORE it stays owned."""
    head = ["## Patterns", "", "- **a** x", "  owned cont", "", "stray prose",
            "  now-unowned indented", "", "- **b** y", ""]
    out = foundry.head_unowned_lines(head)
    assert [head[i] for i in out] == ["stray prose", "  now-unowned indented"], out


def test_b3_a_flush_left_line_in_the_last_block_is_unowned_too():
    head = ["## Patterns", "", "- **a** x", "", "- **b** y", "", "tail prose", "  more"]
    out = foundry.head_unowned_lines(head)
    assert [head[i] for i in out] == ["tail prose", "  more"], out


# --------------------------------------------------------------------- Behavior 4
@pytest.mark.parametrize("head", [[], PREAMBLE_ONLY, CLEAN_OK, CORRUPT_OK, CORRUPT_OVER])
def test_b4_the_input_list_is_never_mutated(head):
    before = copy.deepcopy(head)
    foundry.head_unowned_lines(head)
    assert head == before


WEIRD = [
    [""], ["   "], ["\t"], ["", "", ""],
    ["## Patterns", "   ", "- **a** x", "   ", "\t", "  cont", "   "],
    ["- **a** x"], ["- "], ["-"], ["-x"], ["- **a** x", "- "],
    ["## Patterns", "", "- **a** x", "not indented", "   ", "  indented", ""],
    ["## Patterns", "", "prose", "- **a** x", "prose2", "- **b**", "\t tabbed"],
    ["## Patterns", "- **a** x", "## Nested heading inside", "- [PM iter01] lesson"],
    ["x" * 5000, "- **a** " + "y" * 5000, "z" * 5000],
    ["## Patterns", "", "- **a** x", "  ", "  ", "flush", "  ", "flush2"],
]


@pytest.mark.parametrize("head", WEIRD)
def test_b4_never_raises_and_every_index_is_a_non_blank_non_bullet_line(head):
    before = list(head)
    out = foundry.head_unowned_lines(head)
    assert isinstance(out, tuple)
    assert list(out) == sorted(out) and len(set(out)) == len(out)
    for i in out:
        assert 0 <= i < len(head), (i, head)
        assert head[i].strip() != "", (i, repr(head[i]))
        assert not head[i].startswith("- "), (i, head[i])
    assert head == before


def test_b4_whitespace_only_lines_are_skipped_never_returned():
    head = ["## Patterns", "", "- **a** x", "   ", "\t", "flush", "   ", "  ind", " \t "]
    out = foundry.head_unowned_lines(head)
    assert [head[i] for i in out] == ["flush", "  ind"], out


def test_b4_calling_twice_is_idempotent():
    assert foundry.head_unowned_lines(CORRUPT_OK) == foundry.head_unowned_lines(CORRUPT_OK)


# --------------------------------------------------------------------- Behavior 5
@pytest.mark.parametrize("key,head", SIZED)
def test_b5_the_clause_names_count_chars_and_both_shapes_on_every_sized_branch(
        tmp_path, key, head):
    line = foundry.learnings_head_line(_cfg_for(tmp_path, _text(head), name=f"{key}.md"))
    assert isinstance(line, str) and line and "\n" not in line, repr(line)
    assert line.startswith(PREFIX), line
    assert "5 unowned line(s)" in line, line
    assert f"({EXPECTED_CHARS} chars)" in line, (EXPECTED_CHARS, line)
    assert "flush-left" in line, line
    assert "headless" in line, line
    assert "unowned" in line, line
    for word in BRANCH_WORDS[key]:
        assert word in line, (word, line)


@pytest.mark.parametrize("key,head", SIZED)
def test_b5_the_line_still_carries_raw_chars_and_the_bullet_count(tmp_path, key, head):
    a = foundry.learnings_head_audit(_text(head), CAP, BUDGET)
    line = foundry.learnings_head_line(_cfg_for(tmp_path, _text(head), name=f"{key}.md"))
    assert str(a.raw_chars) in line, (a.raw_chars, line)
    assert f"{a.bullets} bullet(s)" in line, (a.bullets, line)
    assert a.bullets == 3 + (12 if key == "near" else 0), a


@pytest.mark.parametrize("key,head", SIZED)
def test_b5_the_clause_never_says_worst_or_losing(tmp_path, key, head):
    """Spec: the CLAUSE must never contain `worst`/`losing`.  On OK and near-wall the
    whole line is checked (iter-181 b11 / iter-337 b10 pin those branches); on the
    over-budget branch the pre-existing `worst is bullet #N ... losing` body is
    byte-frozen by test_iter337, so the check is scoped to the appended clause."""
    line = foundry.learnings_head_line(_cfg_for(tmp_path, _text(head), name=f"{key}.md"))
    clause = _clause(line)
    assert clause, line
    assert "unowned" in clause, clause
    low = clause.lower()
    assert "worst" not in low and "losing" not in low, clause
    if key != "over":
        assert "worst" not in line.lower() and "losing" not in line.lower(), line


@pytest.mark.parametrize("key,head", SIZED)
def test_b5_exactly_one_clause_is_appended(tmp_path, key, head):
    line = foundry.learnings_head_line(_cfg_for(tmp_path, _text(head), name=f"{key}.md"))
    assert line.count("unowned line(s)") == 1, line
    assert line.count("flush-left") == 1, line


def test_b5_the_count_and_chars_track_the_head_not_a_constant(tmp_path):
    head = ["## Patterns", "", "- **a** x", "", "orphan-one", "", "- **b** y", ""]
    line = foundry.learnings_head_line(_cfg_for(tmp_path, _text(head), name="one.md"))
    assert "1 unowned line(s)" in line, line
    assert f"({len('orphan-one')} chars)" in line, line
    head2 = ["## Patterns", "", "- **a** x", "", "orph", "  two", "  three", "- **b** y"]
    line2 = foundry.learnings_head_line(_cfg_for(tmp_path, _text(head2), name="two.md"))
    assert "3 unowned line(s)" in line2, line2
    assert f"({len(chr(10).join(['orph', '  two', '  three']))} chars)" in line2, line2


@pytest.mark.parametrize("key,head", SIZED)
def test_b5_branch_words_are_the_same_as_the_clean_head_of_that_branch(tmp_path, key, head):
    """The clause is APPENDED: the sized branch itself does not change when the head
    is corrupted -- the clean twin reaches the same OK/near-wall/over-budget words."""
    clean = FROZEN[key][0]
    dirty = foundry.learnings_head_line(_cfg_for(tmp_path, _text(head), name=f"d{key}.md"))
    tidy = foundry.learnings_head_line(_cfg_for(tmp_path, _text(clean), name=f"c{key}.md"))
    for word in BRANCH_WORDS[key]:
        assert word in dirty and word in tidy, (word, dirty, tidy)
    assert (WARN in dirty) == (WARN in tidy), (dirty, tidy)


# --------------------------------------------------------------------- Behavior 6
@pytest.mark.parametrize("key", ["ok", "near", "over"])
def test_b6_a_clean_head_renders_byte_identical_to_the_pre_change_line(tmp_path, key):
    head, frozen = FROZEN[key]
    assert not frozen.startswith("@@"), "frozen literal was never minted"
    line = foundry.learnings_head_line(_cfg_for(tmp_path, _text(head), name=f"{key}.md"))
    assert line == frozen, f"{key}: {line!r} != {frozen!r}"


@pytest.mark.parametrize("key", ["ok", "near", "over"])
def test_b6_a_clean_head_line_has_no_unowned_clause_and_keeps_its_tokens(tmp_path, key):
    head, _ = FROZEN[key]
    a = foundry.learnings_head_audit(_text(head), CAP, BUDGET)
    line = foundry.learnings_head_line(_cfg_for(tmp_path, _text(head), name=f"{key}.md"))
    assert "unowned" not in line, line
    assert "flush-left" not in line and "headless" not in line, line
    assert line.startswith(PREFIX), line
    assert str(a.raw_chars) in line and f"{a.bullets} bullet(s)" in line, (a, line)
    for word in BRANCH_WORDS[key]:
        assert word in line, (word, line)


def test_b6_the_frozen_literals_are_three_distinct_single_lines_with_the_shared_prefix():
    seen = {FROZEN_OK, FROZEN_NEAR, FROZEN_OVER}
    assert len(seen) == 3
    for s in seen:
        assert s.startswith(PREFIX) and "\n" not in s and "unowned" not in s, s
    assert "OK" in FROZEN_OK and WARN not in FROZEN_OK
    assert WARN in FROZEN_NEAR and "STILL arrives whole" in FROZEN_NEAR
    assert WARN in FROZEN_OVER and "truncated" in FROZEN_OVER


def test_b6_the_unknown_branch_is_unchanged_and_carries_no_clause(tmp_path):
    cfg = _cfg_for(tmp_path, learnings=str(tmp_path / "missing.md"))
    line = foundry.learnings_head_line(cfg)
    assert not FROZEN_MISSING.startswith("@@"), "frozen literal was never minted"
    assert line == FROZEN_MISSING, (line, FROZEN_MISSING)
    assert "UNKNOWN" in line and WARN not in line, line
    assert "unowned" not in line, line


def test_b6_an_unreadable_log_is_unknown_and_carries_no_clause(tmp_path):
    d = tmp_path / "a-directory-not-a-file.md"
    d.mkdir()
    line = foundry.learnings_head_line(_cfg_for(tmp_path, learnings=str(d)))
    assert line.startswith(PREFIX) and "UNKNOWN" in line, line
    assert WARN not in line and "unowned" not in line, line


def test_b6_the_iteration_337_frozen_ok_and_over_lines_still_hold(tmp_path):
    """Reuse the OLDER frozen oracles under a fresh fixture: the two bodies frozen by
    test_iter337 are what a clean head STILL renders."""
    under = ["## Patterns", "", _bullet("a", 100), "", _bullet("b", 100, "y"), ""]
    over = ["## Patterns", "", _bullet("a", 9000), "", _bullet("b", 700, "y"), "",
            _bullet("c", 700, "z"), ""]
    ok_line = foundry.learnings_head_line(_cfg_for(tmp_path, _text(under), name="u.md"))
    assert ok_line == (
        "learnings-head: OK -- pinned `## Patterns` head is 232 chars in 2 bullet(s) "
        "and arrives whole in every stage prompt "
        "(bounds: 800 chars/bullet, 10000 total)"), ok_line
    over_line = foundry.learnings_head_line(_cfg_for(tmp_path, _text(over), name="o.md"))
    assert over_line == (
        "learnings-head: WARN -- pinned `## Patterns` head is 10442 chars in 3 bullet(s) "
        "and does NOT arrive whole: 1 bullet(s) truncated, 0 dropped in EVERY stage "
        "prompt (bounds: 800 chars/bullet, 10000 total); worst is bullet #1 "
        "`**a** " + "x" * 74 + "` (truncated, losing 8209 of its 9009 chars) "
        "-- retire the spent directives"), over_line


# --------------------------------------------------------------------- Behavior 7
@pytest.mark.parametrize("key,head", SIZED)
def test_b7_doctor_prints_exactly_one_head_line_and_it_carries_the_clause(
        tmp_path, monkeypatch, key, head):
    _stub_checks(monkeypatch)
    _stub_sibling_lines(monkeypatch)
    cfg = _cfg_for(tmp_path, _text(head), name=f"doc-{key}.md")
    rc, out = _doctor_out(cfg)
    lines = _head_report_lines(out)
    assert len(lines) == 1, f"expected exactly ONE head line, got {lines}"
    assert "unowned" in lines[0] and "5 unowned line(s)" in lines[0], lines[0]
    assert lines[0] == foundry.learnings_head_line(cfg), (lines[0],)
    assert rc == 0, (rc, out)


def test_b7_a_clean_head_through_doctor_prints_one_line_without_the_clause(
        tmp_path, monkeypatch):
    _stub_checks(monkeypatch)
    _stub_sibling_lines(monkeypatch)
    rc, out = _doctor_out(_cfg_for(tmp_path, _text(CLEAN_OK), name="doc-clean.md"))
    lines = _head_report_lines(out)
    assert len(lines) == 1 and "unowned" not in lines[0], lines


def test_b7_the_clause_never_changes_the_doctor_exit_code(tmp_path, monkeypatch):
    _stub_checks(monkeypatch)
    _stub_sibling_lines(monkeypatch)
    rc_dirty, _ = _doctor_out(_cfg_for(tmp_path, _text(CORRUPT_OK), name="rc-d.md"))
    rc_clean, _ = _doctor_out(_cfg_for(tmp_path, _text(CLEAN_OK), name="rc-c.md"))
    assert rc_dirty == rc_clean == 0, (rc_dirty, rc_clean)
    _stub_checks(monkeypatch, fail="uv")
    rc_fail, out = _doctor_out(_cfg_for(tmp_path, _text(CORRUPT_OK), name="rc-f.md"))
    assert rc_fail != 0 and len(_head_report_lines(out)) == 1, (rc_fail, out)


@pytest.mark.parametrize("seam", ["head_unowned_lines", "learnings_head_region"])
@pytest.mark.parametrize("key,head", SIZED)
def test_b7_a_raising_helper_degrades_to_unknown_never_propagates(
        tmp_path, monkeypatch, seam, key, head):
    def boom(*a, **k):
        raise RuntimeError("scripted helper failure")

    monkeypatch.setattr(foundry, seam, boom)
    line = foundry.learnings_head_line(
        _cfg_for(tmp_path, _text(head), name=f"boom-{seam}-{key}.md"))
    assert isinstance(line, str) and line and "\n" not in line, repr(line)
    assert line.startswith(PREFIX), line
    assert "UNKNOWN" in line, line
    assert WARN not in line, line
    assert "unowned" not in line, line


@pytest.mark.parametrize("seam", ["head_unowned_lines", "learnings_head_region"])
def test_b7_a_raising_helper_still_yields_exactly_one_doctor_line(tmp_path, monkeypatch,
                                                                  seam):
    def boom(*a, **k):
        raise RuntimeError("scripted helper failure")

    _stub_checks(monkeypatch)
    _stub_sibling_lines(monkeypatch)
    monkeypatch.setattr(foundry, seam, boom)
    rc, out = _doctor_out(_cfg_for(tmp_path, _text(CORRUPT_OK), name=f"doc-{seam}.md"))
    lines = _head_report_lines(out)
    assert len(lines) == 1 and "UNKNOWN" in lines[0] and WARN not in lines[0], lines
    assert rc == 0, (rc, out)


def test_b7_the_helpers_are_read_as_module_globals_inside_the_line(tmp_path, monkeypatch):
    """Seam visibility: a scripted `head_unowned_lines` returning a fixed tuple must be
    what the line reports -- proof the orchestrator calls the bare module name."""
    monkeypatch.setattr(foundry, "head_unowned_lines", lambda head: (2,))
    line = foundry.learnings_head_line(_cfg_for(tmp_path, _text(CLEAN_OK), name="s.md"))
    assert "1 unowned line(s)" in line, line
    assert f"({len(CLEAN_OK[2])} chars)" in line, (CLEAN_OK[2], line)
    monkeypatch.setattr(foundry, "head_unowned_lines", lambda head: ())
    line2 = foundry.learnings_head_line(_cfg_for(tmp_path, _text(CORRUPT_OK), name="t.md"))
    assert "unowned" not in line2, line2


# ---------------------------------------------------------------- guard rails
def test_guard_the_audit_field_list_is_unchanged():
    """The spec forbids a new `LearningsHeadAudit` field (test_iter337 pins the list)."""
    import dataclasses
    names = [f.name for f in dataclasses.fields(foundry.LearningsHeadAudit)]
    assert "unowned" not in " ".join(names).lower(), names
    assert names[:6] == ["bullets", "raw_chars", "truncated", "dropped", "over_budget",
                         "worst_loss"], names


def test_guard_this_module_reads_no_gitignored_learnings_log():
    """Every fixture lives under tmp_path: no test body names the per-product config
    tree or the live learnings log (OPERATOR 2026-08-11; iter-154 lesson)."""
    body = pathlib.Path(__file__).read_text(encoding="utf-8").split('"""', 2)[2]
    live_log = "LEARNINGS" + ".md"
    product_tree = "prod" + "ucts/"
    assert live_log not in body, "a test body names the live log"
    assert product_tree not in body, "a test body names the per-product tree"
