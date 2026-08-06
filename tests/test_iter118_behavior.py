"""Black-box behaviour tests for iter 118 -- close the `## Patterns` HEAD exemption
in the `learnings_digest` character budget: a per-bullet-block truncation cap plus a
total head budget, both OPTIONAL and defaulting to today's byte-identical output, with
`build_prompt` opting in so the saving is real on the hot path now.

ISOLATION CONTRACT (HONORED): this file was written from the iter-118 PM spec
(`products/_platform/state/iter-118/pm.md`, Expected Behaviors 1-13 + Acceptance
Criteria) and the product's own OBSERVABLE behaviour only (running it), plus the
pre-existing learnings-core tests under `tests/` (test_iter08/98/104) for CONVENTIONS.
The implementation source of `foundry.py` / `dispatcher.py`, the engineer's and
reviewer's notes, and `git diff` were NOT read. Every check drives the PUBLIC
interface: `foundry.learnings_digest(...)`, `foundry.build_prompt(...)`,
`foundry.learnings_cli(...)`, `foundry.render_agents_md(...)` and the public
docstring/doc text. The head-extraction rule and the bullet-block grouping rule are
RE-DERIVED here from the spec's own wording (`_expected_head_lines`, `_split_head`),
never mirrored from the implementation. Fully offline and deterministic: synthetic
strings plus real temp files only -- no subprocess, git, network or agent-run. Two
doc files are read as SHIPPED PROSE (the spec's Acceptance Criteria name them):
`ARCHITECTURE.md` and the real `products/_platform/LEARNINGS.md`, the latter as
measurement INPUT expressed only as inequalities/comparisons with NO hard-coded
current char count.
"""
import contextlib
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
import dispatcher  # noqa: E402

_ARCH = _ROOT / "ARCHITECTURE.md"
_REAL_LEARNINGS = _ROOT / "products" / "_platform" / "LEARNINGS.md"

MARK = foundry.LEARNINGS_TRUNCATION_MARKER
PLACEHOLDER_HEAD = ("## Patterns", "(none recorded yet)")
NOTICE_RE = re.compile(
    r"^> \[head bounded: (\d+) of (\d+) bullets truncated, (\d+) dropped"
    r" -- full text in the learnings log\]$"
)


# --------------------------------------------------------------------------
# helpers -- all RE-DERIVED from the spec's wording, not from the implementation
# --------------------------------------------------------------------------
def _is_h2(line):
    return line.lstrip().startswith("## ")


def _is_lesson(line):
    return line.lstrip().startswith("- [")


def _expected_head_lines(text):
    """Spec Behavior 3's rule: the exact contiguous slice of input lines from the
    `## Patterns` heading to (exclusive) the first later `## ` heading OR the first
    lesson line; the fixed two-line placeholder when there is no `## Patterns`."""
    lines = text.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("## Patterns"):
            start = i
            break
    if start is None:
        return list(PLACEHOLDER_HEAD)
    head = [lines[start]]
    for ln in lines[start + 1:]:
        if _is_h2(ln) or _is_lesson(ln):
            break
        head.append(ln)
    return head


def _head_region(digest):
    """The emitted head region: everything before the `## Recent lessons` count
    header, minus the two joining newlines the digest puts between them."""
    idx = digest.find("## Recent lessons")
    assert idx != -1, f"digest has no '## Recent lessons' header:\n{digest!r}"
    region = digest[:idx]
    assert region.endswith("\n\n"), f"head/header separator changed: {region[-6:]!r}"
    return region[:-2]


def _notice_of(digest):
    """(core_head, notice_line_or_None). Asserts spec Behavior 9's placement: at
    most ONE notice, and it is the LAST line of the head region, followed by one
    blank line and then the `## Recent lessons` header."""
    head = _head_region(digest)
    lines = head.split("\n")
    hits = [ln for ln in lines if ln.startswith("> [head bounded")]
    assert len(hits) <= 1, f"more than one notice line: {hits}"
    if not hits:
        return head, None
    assert lines[-1] == hits[0], (
        f"notice is not the LAST line of the head region: {lines[-3:]!r}")
    return "\n".join(lines[:-1]), hits[0]


def _split_head(core_head):
    """Spec's grouping rule: the PREAMBLE is the head lines before the first bullet
    block; a BULLET BLOCK starts at a head line beginning with `- ` at column 0 and
    runs through every following head line up to (exclusive) the next such line or
    the end of the head."""
    lines = core_head.split("\n")
    idxs = [i for i, ln in enumerate(lines) if ln.startswith("- ")]
    if not idxs:
        return core_head, []
    preamble = "\n".join(lines[:idxs[0]])
    blocks = []
    for k, i in enumerate(idxs):
        end = idxs[k + 1] if k + 1 < len(idxs) else len(lines)
        blocks.append("\n".join(lines[i:end]))
    return preamble, blocks


def _block_of_len(tag, length):
    """A single-line bullet block of EXACT char length."""
    prefix = f"- {tag} "
    assert length >= len(prefix), (length, len(prefix))
    b = prefix + ("x" * (length - len(prefix)))
    assert len(b) == length
    return b


PREAMBLE_LINES = ["## Patterns", "", "Intro prose line.", ""]
PREAMBLE = "\n".join(PREAMBLE_LINES)


def _lesson(i, tag="ROLE", body="durable detail"):
    return f"- [{tag} iter{i:02d}] mark-{i:03d} {body}"


def _text(blocks, lessons=None, preamble_lines=None):
    """head (preamble + blocks) terminated by the FIRST LESSON LINE, so the head
    slice ends exactly at the last bullet with no trailing blank line -- which keeps
    the block-length arithmetic in these tests exact."""
    lessons = lessons or [_lesson(1)]
    pre = list(PREAMBLE_LINES if preamble_lines is None else preamble_lines)
    head = "\n".join(pre + list(blocks))
    return head + "\n" + "\n".join(lessons) + "\n"


def _emitted_lessons(digest):
    return [ln for ln in digest.splitlines() if _is_lesson(ln)]


def _cfg(tmp_path, learnings_text):
    data = {
        "name": "demo",
        "repo": "{FOUNDRY}/products/demo/repo",
        "allowed_push_repo": "demo",
        "vision": "{FOUNDRY}/products/demo/VISION.md",
        "work_root": str(tmp_path / "work"),
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    cfg = foundry.load_config(str(p))
    lp = pathlib.Path(cfg.learnings)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(learnings_text)
    return cfg


def _prompt(cfg, stage="pm", role_file="pm.md", iteration=118):
    it_dir = cfg.state / f"iter-{iteration}"
    return foundry.build_prompt(
        cfg, iteration, stage, role_file, it_dir / role_file, it_dir, "")


def _cap(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    return rc, buf.getvalue()


# --------------------------------------------------------------------------
# Behavior 1 -- two new module-level int constants with exact default values
# --------------------------------------------------------------------------
def test_b01_head_constants_exist_with_spec_values():
    assert foundry.PROMPT_LEARNINGS_HEAD_BULLET_CHARS == 800
    assert foundry.PROMPT_LEARNINGS_HEAD_BUDGET_CHARS == 10000


def test_b01_head_constants_are_plain_ints_and_ordered():
    assert isinstance(foundry.PROMPT_LEARNINGS_HEAD_BULLET_CHARS, int)
    assert isinstance(foundry.PROMPT_LEARNINGS_HEAD_BUDGET_CHARS, int)
    assert not isinstance(foundry.PROMPT_LEARNINGS_HEAD_BULLET_CHARS, bool)
    assert not isinstance(foundry.PROMPT_LEARNINGS_HEAD_BUDGET_CHARS, bool)
    # a per-bullet cap above the total budget would be meaningless
    assert (len(MARK)
            < foundry.PROMPT_LEARNINGS_HEAD_BULLET_CHARS
            < foundry.PROMPT_LEARNINGS_HEAD_BUDGET_CHARS)


def test_b01_out_of_scope_lesson_constants_unchanged():
    # spec Out of Scope: no change to the iter-104 lesson-side values
    assert foundry.PROMPT_LEARNINGS_LESSON_CHARS == 800
    assert foundry.PROMPT_LEARNINGS_BUDGET_CHARS == 10000
    assert foundry.LEARNINGS_TRUNCATION_MARKER == " [...]"


# --------------------------------------------------------------------------
# Behavior 2 -- signature is purely additive
# --------------------------------------------------------------------------
def test_b02_signature_additive_new_keyword_params():
    params = inspect.signature(foundry.learnings_digest).parameters
    names = list(params)
    assert names[:4] == ["text", "recent", "max_chars", "lesson_chars"], names
    assert params["recent"].default == 12
    assert params["max_chars"].default is None
    assert params["lesson_chars"].default is None
    for new in ("head_bullet_chars", "head_chars"):
        assert new in names, f"{new} missing from learnings_digest signature"
        assert params[new].default is None, new
        assert params[new].kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ), new
    # both new params come AFTER the four existing ones (older positional callers safe)
    assert names.index("head_bullet_chars") >= 4
    assert names.index("head_chars") >= 4


def test_b02_new_params_usable_independently_by_keyword():
    text = _text([_block_of_len("a", 200), _block_of_len("b", 200)])
    # each alone must be accepted and take effect independently
    only_cap = foundry.learnings_digest(text, head_bullet_chars=60)
    only_budget = foundry.learnings_digest(text, head_chars=len(PREAMBLE) + 201)
    assert MARK in _head_region(only_cap)
    assert MARK not in _head_region(only_budget)
    assert _notice_of(only_cap)[1] is not None
    assert _notice_of(only_budget)[1] is not None


# --------------------------------------------------------------------------
# Behavior 3 -- BACK-COMPAT: both None => verbatim head, byte-identical, no notice
# --------------------------------------------------------------------------
def _backcompat_inputs():
    long_block = "- " + ("L" * 4000)
    multi = "- first line of a long bullet " + ("m" * 900) + "\n  continued " + ("n" * 900)
    return {
        "rich": _text([long_block, "- short rule", multi], [_lesson(i) for i in (1, 2, 3)]),
        "h2_terminated": (PREAMBLE + "\n" + long_block
                          + "\n\n## Chronological lessons\n\n" + _lesson(1) + "\n"),
        "no_patterns": _lesson(1) + "\n" + _lesson(2) + "\n",
        "preamble_only": (PREAMBLE + "\n\n## Chronological lessons\n\n" + _lesson(1) + "\n"),
        "empty": "",
    }


@pytest.mark.parametrize("key", sorted(_backcompat_inputs()))
def test_b03_default_is_byte_identical_and_head_verbatim(key):
    text = _backcompat_inputs()[key]
    d_default = foundry.learnings_digest(text)
    d_explicit_none = foundry.learnings_digest(
        text, head_bullet_chars=None, head_chars=None)
    assert d_default == d_explicit_none, "explicit None differs from the default"

    core, notice = _notice_of(d_default)
    assert notice is None, f"default emitted a notice line: {notice!r}"
    assert MARK not in core, "default digest truncated the head"
    # the emitted head is the EXACT contiguous input slice (re-derived from the spec)
    assert core == "\n".join(_expected_head_lines(text)), repr(core)



def test_b03_default_matches_iter104_frozen_shape():
    """The iter-08/104 frozen tests pin `learnings_digest(text, recent=N)` as a
    contiguous substring of the built prompt; that only holds if the DEFAULT call is
    unchanged for a small head. Same guarantee, asserted directly here."""
    text = _text(["- small rule a", "- small rule b"], [_lesson(1), _lesson(2)])
    assert foundry.learnings_digest(text, recent=foundry.PROMPT_LEARNINGS_RECENT) == \
        foundry.learnings_digest(text, recent=foundry.PROMPT_LEARNINGS_RECENT,
                                 head_bullet_chars=None, head_chars=None)


# --------------------------------------------------------------------------
# Behavior 4 -- PER-BULLET TRUNCATION and its exact boundary
# --------------------------------------------------------------------------
def test_b04_per_block_truncation_boundary_exact():
    C = 60
    assert C > len(MARK)
    eqC = _block_of_len("eq", C)          # exactly C -> verbatim
    cplus1 = _block_of_len("gt", C + 1)   # C+1 -> truncated to EXACTLY C
    short = _block_of_len("lt", 30)       # < C -> verbatim
    text = _text([eqC, cplus1, short])

    d = foundry.learnings_digest(text, head_bullet_chars=C)
    core, notice = _notice_of(d)
    _, blocks = _split_head(core)
    assert len(blocks) == 3, blocks

    for b in blocks:
        assert len(b) <= C, (len(b), b)

    assert blocks[0] == eqC and not blocks[0].endswith(MARK)
    assert len(blocks[1]) == C
    assert blocks[1].endswith(MARK)
    assert blocks[1] == cplus1[: C - len(MARK)] + MARK
    assert blocks[2] == short and not blocks[2].endswith(MARK)
    # exactly one block was truncated -> the notice says 1 of 3, 0 dropped
    assert NOTICE_RE.match(notice).groups() == ("1", "3", "0"), notice


def test_b04_every_block_within_cap_for_many_sizes():
    C = 120
    sizes = [10, 119, 120, 121, 400, 4000]
    text = _text([_block_of_len(f"s{i}", n) for i, n in enumerate(sizes)])
    core, _ = _notice_of(foundry.learnings_digest(text, head_bullet_chars=C))
    _, blocks = _split_head(core)
    assert len(blocks) == len(sizes)
    for n, b in zip(sizes, blocks):
        assert len(b) <= C, (n, len(b))
        if n > C:
            assert len(b) == C and b.endswith(MARK), (n, b)
        else:
            assert not b.endswith(MARK), (n, b)


# --------------------------------------------------------------------------
# Behavior 5 -- GROUPING: multi-line bullets are ONE block; preamble verbatim
# --------------------------------------------------------------------------
def test_b05_multiline_bullet_is_one_block():
    first = "- head line " + ("h" * 80)
    cont1 = "  continuation one " + ("c" * 80)
    cont2 = "  continuation two TAILSENTINEL"
    block = "\n".join([first, cont1, cont2])
    text = _text([block, "- second bullet"])

    # unbounded: all three lines present, still ONE block by the grouping rule
    core_full, notice_full = _notice_of(foundry.learnings_digest(text))
    assert notice_full is None
    _, blocks_full = _split_head(core_full)
    assert len(blocks_full) == 2, blocks_full
    assert blocks_full[0] == block
    assert "TAILSENTINEL" in core_full

    # capped below the first line's own length: the continuations are cut as part of
    # the SAME block -- they are never emitted as separate bullets
    C = 60
    core, notice = _notice_of(foundry.learnings_digest(text, head_bullet_chars=C))
    _, blocks = _split_head(core)
    assert len(blocks) == 2, blocks
    assert len(blocks[0]) == C and blocks[0].endswith(MARK)
    assert blocks[0] == block[: C - len(MARK)] + MARK
    assert "TAILSENTINEL" not in core, "continuation survived its block's truncation"
    assert blocks[1] == "- second bullet"
    # M counts BLOCKS (2), not head lines (4)
    assert NOTICE_RE.match(notice).group(2) == "2", notice


def test_b05_preamble_always_verbatim_and_counted_in_budget():
    blocks = [_block_of_len("a", 100), _block_of_len("b", 100)]
    text = _text(blocks)
    # budget = preamble length exactly -> zero blocks admitted, preamble still verbatim
    core, notice = _notice_of(foundry.learnings_digest(text, head_chars=len(PREAMBLE)))
    assert core == PREAMBLE, repr(core)
    assert _split_head(core)[1] == []
    assert NOTICE_RE.match(notice).groups() == ("0", "2", "2"), notice

    # one char less than (preamble + newline + first block) still admits nothing:
    # the preamble is counted INSIDE the budget
    tight = len(PREAMBLE) + 1 + 100 - 1
    core2, notice2 = _notice_of(foundry.learnings_digest(text, head_chars=tight))
    assert _split_head(core2)[1] == []
    assert core2 == PREAMBLE
    # exactly enough -> the first block fits
    core3, notice3 = _notice_of(foundry.learnings_digest(text, head_chars=tight + 1))
    assert _split_head(core3)[1] == [blocks[0]]
    assert len(core3) == len(PREAMBLE) + 1 + 100


def test_b05_preamble_verbatim_even_with_tiny_bullet_cap():
    text = _text([_block_of_len("a", 500)], preamble_lines=PREAMBLE_LINES)
    core, _ = _notice_of(foundry.learnings_digest(text, head_bullet_chars=20))
    pre, _ = _split_head(core)
    assert pre == PREAMBLE, repr(pre)


# --------------------------------------------------------------------------
# Behavior 6 -- TOTAL HEAD BUDGET: top-down admission, stop at first overflow
# --------------------------------------------------------------------------
def test_b06_budget_admits_top_down_prefix_and_bounds_head():
    L = 50
    n = 6
    blocks = [_block_of_len(f"b{i}", L) for i in range(n)]
    text = _text(blocks)
    # the admitted head length for k blocks is preamble + k*(1 + L)
    for k in range(n + 1):
        B = len(PREAMBLE) + k * (1 + L)
        core, notice = _notice_of(foundry.learnings_digest(text, head_chars=B))
        _, emitted = _split_head(core)
        assert emitted == blocks[:k], (B, k, emitted)
        assert len(core) <= B, (len(core), B)
        assert len(core) == B
        if k < n:
            assert notice is not None
            assert NOTICE_RE.match(notice).groups() == ("0", str(n), str(n - k)), notice
            # stopping condition: the NEXT block would have exceeded the budget
            assert len(core) + 1 + L > B
        else:
            assert notice is None, notice


def test_b06_head_bounded_for_arbitrary_budgets():
    blocks = [_block_of_len(f"b{i}", 40 + 7 * i) for i in range(8)]
    text = _text(blocks)
    for B in range(len(PREAMBLE), len(PREAMBLE) + 400, 13):
        core, _ = _notice_of(foundry.learnings_digest(text, head_chars=B))
        assert len(core) <= B, (B, len(core))
        _, emitted = _split_head(core)
        # always a top-down PREFIX of the input blocks
        assert emitted == blocks[: len(emitted)], (B, emitted)


# --------------------------------------------------------------------------
# Behavior 7 -- PRECEDENCE PRESERVED: dropping is from the BOTTOM
# --------------------------------------------------------------------------
def test_b07_first_block_survives_whenever_any_admitted():
    first = "- FIRSTRULE operator directive " + ("f" * 60)
    last = "- LASTRULE newest appended " + ("l" * 60)
    blocks = [first, _block_of_len("mid", 90), last]
    text = _text(blocks)
    B = len(PREAMBLE) + 1 + len(first)  # room for exactly one block
    core, notice = _notice_of(foundry.learnings_digest(text, head_chars=B))
    _, emitted = _split_head(core)
    assert emitted == [first], emitted
    assert "FIRSTRULE" in core
    assert "LASTRULE" not in core, "dropped from the TOP instead of the BOTTOM"
    assert NOTICE_RE.match(notice).groups() == ("0", "3", "2"), notice


def test_b07_drop_is_a_contiguous_bottom_suffix():
    blocks = [_block_of_len(f"b{i}", 60) for i in range(5)]
    text = _text(blocks)
    for k in range(1, 6):
        B = len(PREAMBLE) + k * 61
        core, _ = _notice_of(foundry.learnings_digest(text, head_chars=B))
        _, emitted = _split_head(core)
        assert emitted == blocks[:k], (k, emitted)


# --------------------------------------------------------------------------
# Behavior 8 -- ORDER OF OPERATIONS: truncate FIRST, budget SECOND
# --------------------------------------------------------------------------
def test_b08_truncation_then_budget_compose():
    C = 20
    n = 3
    blocks = [_block_of_len(f"b{i}", 500) for i in range(n)]  # all >> C
    text = _text(blocks)
    # after truncation each block is EXACTLY C, so k blocks fit iff
    # preamble + k*(1+C) <= B  -- budget arithmetic uses TRUNCATED lengths
    for k in range(n + 1):
        B = len(PREAMBLE) + k * (1 + C)
        core, notice = _notice_of(foundry.learnings_digest(
            text, head_bullet_chars=C, head_chars=B))
        _, emitted = _split_head(core)
        assert len(emitted) == k, (B, k, emitted)
        # invariant 1: every emitted block within the cap
        assert all(len(b) == C and b.endswith(MARK) for b in emitted), emitted
        # invariant 2: the emitted head within the budget
        assert len(core) <= B, (len(core), B)
        # every block here is over the cap, so a notice is always due
        assert notice is not None, (B, k)
        assert NOTICE_RE.match(notice).groups() == (str(k), str(n), str(n - k)), notice


def test_b08_budget_measured_after_truncation_not_before():
    C = 30
    blocks = [_block_of_len(f"b{i}", 900) for i in range(4)]
    text = _text(blocks)
    # a budget far below the UNTRUNCATED total but big enough for all 4 truncated
    B = len(PREAMBLE) + 4 * (1 + C)
    assert B < sum(len(b) for b in blocks)
    core, notice = _notice_of(foundry.learnings_digest(
        text, head_bullet_chars=C, head_chars=B))
    _, emitted = _split_head(core)
    assert len(emitted) == 4, emitted  # nothing dropped: truncation happened FIRST
    assert NOTICE_RE.match(notice).groups() == ("4", "4", "0"), notice


# --------------------------------------------------------------------------
# Behavior 9 -- LOUD NOTICE: exact form, exactly once, only when something elided
# --------------------------------------------------------------------------
def test_b09_notice_exact_form_and_placement():
    blocks = [_block_of_len(f"b{i}", 300) for i in range(4)]
    text = _text(blocks)
    C = 100
    B = len(PREAMBLE) + 2 * (1 + C)
    d = foundry.learnings_digest(text, head_bullet_chars=C, head_chars=B)
    core, notice = _notice_of(d)
    assert notice == (
        "> [head bounded: 2 of 4 bullets truncated, 2 dropped"
        " -- full text in the learnings log]"
    ), notice
    assert d.count(notice) == 1, "notice emitted more than once"
    # placement: notice, then ONE blank line, then the count header
    idx = d.find(notice)
    after = d[idx + len(notice):]
    assert after.startswith("\n\n## Recent lessons ("), repr(after[:40])


def test_b09_no_notice_when_nothing_elided():
    blocks = ["- rule one", "- rule two"]
    text = _text(blocks)
    d = foundry.learnings_digest(text, head_bullet_chars=800, head_chars=10000)
    assert "head bounded" not in d, d
    assert MARK not in d
    assert d == foundry.learnings_digest(text), "no-op bounds changed the output"


def test_b09_notice_counts_truncated_and_dropped_separately():
    # 5 blocks: the first two are long (truncated), the rest short; the budget then
    # drops the bottom two -> T counts EMITTED truncated blocks only.
    C = 50
    blocks = [_block_of_len("t0", 400), _block_of_len("t1", 400),
              _block_of_len("s2", 20), _block_of_len("s3", 20),
              _block_of_len("s4", 20)]
    text = _text(blocks)
    # admit exactly 3: 50 + 50 + 20 with joins
    B = len(PREAMBLE) + (1 + C) + (1 + C) + (1 + 20)
    core, notice = _notice_of(foundry.learnings_digest(
        text, head_bullet_chars=C, head_chars=B))
    _, emitted = _split_head(core)
    assert len(emitted) == 3, emitted
    assert NOTICE_RE.match(notice).groups() == ("2", "5", "2"), notice


def test_b09_notice_absent_from_digest_when_head_params_none():
    blocks = [_block_of_len(f"b{i}", 5000) for i in range(6)]
    text = _text(blocks)
    d = foundry.learnings_digest(text)
    assert "head bounded" not in d


# --------------------------------------------------------------------------
# Behavior 10 -- BUDGET ORACLE on pathological input
# --------------------------------------------------------------------------
def _pathological(head_blocks=30, head_block_len=4000, lessons=30, lesson_len=4000):
    blocks = [_block_of_len(f"h{i}", head_block_len) for i in range(head_blocks)]
    ls = [f"- [ENG iter{i:02d}] " + ("y" * lesson_len) for i in range(1, lessons + 1)]
    return _text(blocks, ls)


def test_b10_bounded_oracle_pathological_input():
    text = _pathological()
    assert len(text) > 100_000, len(text)
    R, MB, LC, HC, HB = 50, 10_000, 800, 800, 10_000
    d = foundry.learnings_digest(
        text, recent=R, max_chars=MB, lesson_chars=LC,
        head_bullet_chars=HC, head_chars=HB)
    assert len(d) <= HB + MB + 300, len(d)
    # and the two halves are each individually bounded
    core, notice = _notice_of(d)
    assert len(core) <= HB, len(core)
    assert notice is not None
    assert sum(len(ln) for ln in _emitted_lessons(d)) <= MB


def test_b10_bounded_oracle_with_module_defaults():
    text = _pathological(head_blocks=40, lessons=40)
    assert len(text) > 100_000, len(text)
    HB = foundry.PROMPT_LEARNINGS_HEAD_BUDGET_CHARS
    MB = foundry.PROMPT_LEARNINGS_BUDGET_CHARS
    d = foundry.learnings_digest(
        text,
        recent=foundry.PROMPT_LEARNINGS_RECENT,
        max_chars=MB,
        lesson_chars=foundry.PROMPT_LEARNINGS_LESSON_CHARS,
        head_bullet_chars=foundry.PROMPT_LEARNINGS_HEAD_BULLET_CHARS,
        head_chars=HB,
    )
    assert len(d) <= HB + MB + 300, len(d)
    # the guard bit: without the head bound the SAME call is far larger
    unbounded_head = foundry.learnings_digest(
        text, recent=foundry.PROMPT_LEARNINGS_RECENT, max_chars=MB,
        lesson_chars=foundry.PROMPT_LEARNINGS_LESSON_CHARS)
    assert len(unbounded_head) > HB + MB + 300


def test_b10_oracle_holds_across_a_grid_of_budgets():
    text = _pathological(head_blocks=12, head_block_len=3000, lessons=12, lesson_len=3000)
    for HC, HB, LC, MB in ((200, 1000, 200, 1000), (800, 5000, 800, 5000),
                           (60, 300, 60, 300)):
        d = foundry.learnings_digest(text, recent=50, max_chars=MB, lesson_chars=LC,
                                     head_bullet_chars=HC, head_chars=HB)
        assert len(d) <= HB + MB + 300, (HC, HB, LC, MB, len(d))


# --------------------------------------------------------------------------
# Behavior 11 -- build_prompt opts in, reading MODULE GLOBALS at call time
# --------------------------------------------------------------------------
def test_b11_build_prompt_bounds_the_head_by_default(tmp_path):
    big = "- OPERATOR DIRECTIVE HEADSENT " + ("z" * 3000) + " TAILSENT"
    text = _text([big, "- short rule"], [_lesson(1)])
    cfg = _cfg(tmp_path, text)
    prompt = _prompt(cfg)
    assert "HEADSENT" in prompt, "the head of the long bullet is missing from the prompt"
    assert "TAILSENT" not in prompt, "the full 3KB head bullet leaked into the prompt"
    assert MARK in prompt
    assert "head bounded:" in prompt, "no loud notice in the built prompt"


def test_b11_build_prompt_reads_bullet_cap_as_module_global(tmp_path, monkeypatch):
    text = _text(["- rule alpha is quite long here", "- rule beta"], [_lesson(1)])
    cfg = _cfg(tmp_path, text)
    assert "head bounded:" not in _prompt(cfg)  # no-op at the real constants
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_HEAD_BULLET_CHARS", 12)
    prompt = _prompt(cfg)
    assert "head bounded:" in prompt, (
        "monkeypatching PROMPT_LEARNINGS_HEAD_BULLET_CHARS did not change the prompt "
        "(constant captured at def-time instead of read at call-time)")
    assert MARK in prompt


def test_b11_build_prompt_reads_head_budget_as_module_global(tmp_path, monkeypatch):
    blocks = [_block_of_len("a", 120), "- DROPME rule beta"]
    text = _text(blocks, [_lesson(1)])
    cfg = _cfg(tmp_path, text)
    assert "head bounded:" not in _prompt(cfg)
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_HEAD_BUDGET_CHARS",
                        len(PREAMBLE) + 1 + 120)
    prompt = _prompt(cfg)
    assert "head bounded:" in prompt, (
        "monkeypatching PROMPT_LEARNINGS_HEAD_BUDGET_CHARS did not change the prompt")
    assert "DROPME" not in prompt, "the over-budget bullet was not dropped"


def test_b11_learnings_digest_itself_untouched_by_the_monkeypatch(tmp_path, monkeypatch):
    text = _text(["- rule alpha is quite long here"], [_lesson(1)])
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_HEAD_BULLET_CHARS", 12)
    # the pure helper still defaults to None -> verbatim head; only build_prompt opts in
    d = foundry.learnings_digest(text)
    assert "head bounded:" not in d
    assert MARK not in d


def test_b11_same_bounded_head_for_every_stage(tmp_path):
    big = "- " + ("q" * 3000)
    cfg = _cfg(tmp_path, _text([big], [_lesson(1)]))
    pm = _prompt(cfg, "pm", "pm.md")
    eng = _prompt(cfg, "engineer", "engineer.md")
    expect = foundry.learnings_digest(
        pathlib.Path(cfg.learnings).read_text(),
        recent=foundry.PROMPT_LEARNINGS_RECENT,
        max_chars=foundry.PROMPT_LEARNINGS_BUDGET_CHARS,
        lesson_chars=foundry.PROMPT_LEARNINGS_LESSON_CHARS,
        head_bullet_chars=foundry.PROMPT_LEARNINGS_HEAD_BULLET_CHARS,
        head_chars=foundry.PROMPT_LEARNINGS_HEAD_BUDGET_CHARS,
    )
    assert expect in pm, "the fully-bounded digest is not inlined verbatim in the pm prompt"
    assert expect in eng, "the fully-bounded digest is not inlined in the engineer prompt"


# --------------------------------------------------------------------------
# Behavior 12 -- NON-PROMPT CALLERS UNCHANGED (full verbatim head)
# --------------------------------------------------------------------------
def _full_head_text():
    return _text(["- " + ("w" * 6000) + " TAILFULL", "- another rule"],
                 [_lesson(1), _lesson(2)])


def test_b12_human_cli_emits_full_head(tmp_path):
    text = _full_head_text()
    cfg = _cfg(tmp_path, text)
    rc, out = _cap(lambda: foundry.learnings_cli(cfg, recent=12))
    assert rc == 0
    assert out == foundry.learnings_digest(text, recent=12) + "\n"
    assert "TAILFULL" in out, "the human CLI truncated the head"
    assert MARK not in out
    assert "head bounded" not in out


def test_b12_json_cli_emits_full_head(tmp_path):
    text = _full_head_text()
    cfg = _cfg(tmp_path, text)
    rc, out = _cap(lambda: foundry.learnings_cli(cfg, recent=12, as_json=True))
    assert rc == 0
    obj = json.loads(out)
    joined = "\n".join(obj["head"])
    assert "TAILFULL" in joined, "--json truncated the head"
    assert MARK not in joined
    assert not any("head bounded" in ln for ln in obj["head"])


def test_b12_render_agents_md_emits_full_head():
    text = _full_head_text()
    out = foundry.render_agents_md(text, "SomeProduct", recent=12)
    assert foundry.learnings_digest(text, recent=12) in out
    assert "TAILFULL" in out, "render_agents_md truncated the head"
    assert MARK not in out
    assert "head bounded" not in out


def test_b12_non_prompt_signatures_gained_no_head_params():
    assert list(inspect.signature(foundry.learnings_cli).parameters) == \
        ["cfg", "recent", "as_json"]
    assert list(inspect.signature(foundry.render_agents_md).parameters) == \
        ["learnings_text", "product_name", "recent"]


# --------------------------------------------------------------------------
# Behavior 13 -- ROBUST, NEVER RAISES on the degenerate shapes
# --------------------------------------------------------------------------
def test_b13_no_patterns_section_placeholder_head_no_notice():
    text = _lesson(1) + "\n" + _lesson(2) + "\n"
    d = foundry.learnings_digest(text, head_bullet_chars=5, head_chars=5)
    core, notice = _notice_of(d)
    assert [ln for ln in core.split("\n") if ln.strip()] == list(PLACEHOLDER_HEAD), core
    assert notice is None, f"placeholder head emitted a notice (M == 0): {notice!r}"
    assert MARK not in core


def test_b13_head_with_zero_bullet_blocks_no_notice():
    text = PREAMBLE + "\n\n## Chronological lessons\n\n" + _lesson(1) + "\n"
    d = foundry.learnings_digest(text, head_bullet_chars=5, head_chars=5)
    core, notice = _notice_of(d)
    assert notice is None, f"preamble-only head emitted a notice: {notice!r}"
    assert "Intro prose line." in core
    assert MARK not in core


def test_b13_budget_below_preamble_drops_every_block():
    blocks = [_block_of_len(f"b{i}", 100) for i in range(3)]
    text = _text(blocks)
    core, notice = _notice_of(foundry.learnings_digest(text, head_chars=1))
    assert _split_head(core)[1] == [], core
    assert NOTICE_RE.match(notice).groups() == ("0", "3", "3"), notice
    # documented assumption: the guarantee head <= B only holds for B >= len(preamble)
    assert core == PREAMBLE


def test_b13_empty_text_never_raises():
    d = foundry.learnings_digest("", head_bullet_chars=1, head_chars=1)
    assert "## Patterns" in d
    assert "(none recorded yet)" in d
    assert "head bounded" not in d


@pytest.mark.parametrize("hc", [None, 0, 1, 7, 800])
@pytest.mark.parametrize("hb", [None, 0, 1, 25, 10000])
def test_b13_never_raises_across_a_grid_of_degenerate_bounds(hc, hb):
    multi = "- bullet " + ("k" * 300) + "\n  cont " + ("j" * 300)
    for text in ("", "\n", "## Patterns\n", _lesson(1) + "\n",
                 _text([multi, "- x"], [_lesson(1), _lesson(2)])):
        out = foundry.learnings_digest(text, head_bullet_chars=hc, head_chars=hb)
        assert isinstance(out, str)
        assert "## Patterns" in out
        assert out.count("head bounded") <= 1


# --------------------------------------------------------------------------
# Acceptance Criteria -- real-log measurement, docstring, ARCHITECTURE.md, imports
# --------------------------------------------------------------------------
def _require_real_learnings():
    """Read the real log, or SKIP -- added by the [FINAL iter118] gate.

    `products/*/LEARNINGS.md` is GITIGNORED (a per-machine runtime artifact), so it
    is ABSENT from a fresh clone: the post-release fresh-clone gate, CI, and any
    public checkout. Reading it unconditionally made `uv run pytest -q` FAIL on a
    clean checkout of the shipped commit while passing in the dispatcher's working
    tree -- a failure the working-tree suite structurally cannot see. The condition
    is a RUNTIME file check (never a constant), so this is not an always-skipped
    test: wherever the log exists -- the dispatcher machine, i.e. exactly where the
    real-log regression has value -- the test RUNS and asserts everything.
    """
    if not _REAL_LEARNINGS.is_file():
        pytest.skip(
            f"{_REAL_LEARNINGS} is a gitignored per-machine runtime artifact and is "
            "absent in a fresh clone; the real-log measurement runs where it exists")
    return _REAL_LEARNINGS.read_text()


def test_ac_real_learnings_log_head_is_bounded_on_the_prompt_path():
    """Measured against the REAL log, expressed only as inequalities/comparisons --
    no hard-coded char count (the log grows every iteration)."""
    text = _require_real_learnings()
    HB = foundry.PROMPT_LEARNINGS_HEAD_BUDGET_CHARS
    HC = foundry.PROMPT_LEARNINGS_HEAD_BULLET_CHARS
    MB = foundry.PROMPT_LEARNINGS_BUDGET_CHARS
    LC = foundry.PROMPT_LEARNINGS_LESSON_CHARS
    R = foundry.PROMPT_LEARNINGS_RECENT

    bounded = foundry.learnings_digest(
        text, recent=R, max_chars=MB, lesson_chars=LC,
        head_bullet_chars=HC, head_chars=HB)
    head_unbounded = foundry.learnings_digest(
        text, recent=R, max_chars=MB, lesson_chars=LC)

    core, _ = _notice_of(bounded)
    assert len(core) <= HB, (len(core), HB)
    for b in _split_head(core)[1]:
        assert len(b) <= HC, len(b)

    # the precondition is DERIVED from the same data, so a future failure explains itself
    full_core, _ = _notice_of(head_unbounded)
    oversized = [len(b) for b in _split_head(full_core)[1] if len(b) > HC]
    assert len(bounded) < len(head_unbounded), (
        "the prompt-path digest is not strictly shorter than the same call with the "
        f"head params None (oversized head blocks today: {oversized}; head len "
        f"{len(full_core)} vs budget {HB}) -- if the head has been curated so that "
        "every block is within the cap AND the total is within the budget, the bound "
        "is correctly a no-op and this assertion needs revisiting")
    assert len(bounded) <= HB + MB + 300, len(bounded)


def test_ac_real_log_cli_view_still_shows_the_full_head(tmp_path):
    """The operator-facing renderers must still show the real head in FULL."""
    text = _require_real_learnings()
    cfg = _cfg(tmp_path, text)
    rc, out = _cap(lambda: foundry.learnings_cli(cfg, recent=foundry.PROMPT_LEARNINGS_RECENT))
    assert rc == 0
    # Line-anchored ON PURPOSE. A bare `"head bounded" not in out` substring test
    # self-poisons: it greps the very log it reads for its own marker string, so it
    # fails the moment any LESSON BULLET quotes the marker in prose (a role did
    # exactly that in iter 120). That is log CONTENT, not a leak. A real notice is
    # always its OWN line starting `> [head bounded` -- the same predicate this
    # module's `_notice_of` already uses. Proven two-sided: it still FIRES on a
    # genuinely head-bounded digest, and does NOT fire on prose that mentions it.
    leaked = [ln for ln in out.split("\n") if ln.startswith("> [head bounded")]
    assert not leaked, f"the head bound leaked into the CLI view: {leaked}"
    unbounded_head = "\n".join(_expected_head_lines(text))
    assert unbounded_head in out, "the CLI view no longer shows the full verbatim head"


def test_ac_docstring_no_longer_claims_the_head_is_never_bounded():
    doc = foundry.learnings_digest.__doc__ or ""
    low = doc.lower()
    assert "never truncated or budgeted" not in low, (
        "the docstring still claims the head is NEVER truncated or budgeted")
    for name in ("head_bullet_chars", "head_chars"):
        assert name in doc, f"{name} is not documented in the docstring"


def test_ac_architecture_documents_the_closed_head_exemption():
    arch = _ARCH.read_text()
    assert "PROMPT_LEARNINGS_HEAD_BULLET_CHARS" in arch
    assert "PROMPT_LEARNINGS_HEAD_BUDGET_CHARS" in arch
    low = arch.lower()
    assert "head" in low and "bounded" in low
    # the CLI / AGENTS.md renderers are documented as still showing the FULL head
    assert "full" in low
    assert "agents.md" in low


def test_ac_modules_import_and_public_api_callable():
    assert foundry is not None and dispatcher is not None
    for name in ("learnings_digest", "build_prompt", "learnings_cli",
                 "render_agents_md"):
        assert callable(getattr(foundry, name)), name
    for name in ("run_iteration", "run_continuous", "run_stage"):
        assert callable(getattr(foundry, name)), name
