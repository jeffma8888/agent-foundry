"""Black-box behaviour tests for iter 104 -- a real CHARACTER budget for the
`learnings_digest` helper (per-lesson truncation + a newest-first total-char cap
on the lessons tail), opted into by `build_prompt` so the digest inlined into
every stage prompt can no longer grow without bound.

ISOLATION CONTRACT (honored): this file was written from the PM spec
(products/_platform/state/iter-104/pm.md, Expected Behaviors 1-11) and the
product's own OBSERVABLE behaviour only (running it), plus the pre-existing
learnings-core tests under tests/ (test_iter07/08/09/98). The implementation
source (foundry.py internals), the engineer's and reviewer's notes, and
`git diff` (and `git show HEAD:foundry.py`) were NOT read. Every check drives the
PUBLIC interface: the pure helper `foundry.learnings_digest(...)`, the prompt
builder `foundry.build_prompt(...)`, the CLI `foundry.learnings_cli(...)`, and
`foundry.render_agents_md(...)`, against synthetic input strings and a TMP config
whose learnings file lives under a temp work_root (the real foundry repo is NEVER
touched). Fully offline and deterministic -- real temp files only, no
subprocess/git/network/agent-run.
"""
import contextlib
import inspect
import io
import json
import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers (mirror the suite's conventions in test_iter07/08_behavior.py)
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    data = {
        "name": "demo",
        "repo": "{FOUNDRY}/products/demo/repo",
        "allowed_push_repo": "demo",
        "vision": "{FOUNDRY}/products/demo/VISION.md",
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _cfg_with_learnings(tmp_path, file_text):
    """Load a config + seed <work_root>/LEARNINGS.md (cfg.learnings) with text."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    lp = pathlib.Path(cfg.learnings)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(file_text)
    return cfg


def _lesson_of_len(i, length, tag="ROLE"):
    """A role-tagged lesson line `- [TAG iterNN] U### ...` of EXACT char length."""
    prefix = f"- [{tag} iter{i:02d}] U{i:03d} "
    assert length >= len(prefix), (length, len(prefix))
    line = prefix + ("x" * (length - len(prefix)))
    assert len(line) == length
    return line


def _lesson(i, tag="ROLE"):
    """A short role-tagged lesson line with a unique marker."""
    return f"- [{tag} iter{i:02d}] {_marker(i)} durable detail text"


def _marker(i):
    return f"mark-{i:03d}"


def _patterns_head(*bullets):
    lines = ["## Patterns", "", "Read this head first; the tail is the history.", ""]
    lines += [f"- {b}" for b in bullets]
    return "\n".join(lines)


def _learnings_text(lessons, *patterns):
    """patterns head + chronological lessons tail (lessons = list of full lines)."""
    head = _patterns_head(*patterns) if patterns else _patterns_head("a durable rule")
    return head + "\n\n## Chronological lessons\n\n" + "\n".join(lessons) + "\n"


def _emitted_lessons(digest):
    """The lesson lines actually emitted: left-stripped form starts with '- ['."""
    return [ln for ln in digest.splitlines() if ln.lstrip().startswith("- [")]


def _head_portion(digest):
    """Everything before the '## Recent lessons' count header."""
    idx = digest.find("## Recent lessons")
    assert idx != -1, f"digest has no '## Recent lessons' header:\n{digest!r}"
    return digest[:idx]


def _header_counts(digest):
    m = re.search(r"## Recent lessons \(last (\d+) of (\d+)\)", digest)
    assert m is not None, f"no count header in digest:\n{digest!r}"
    return int(m.group(1)), int(m.group(2))


def _id_of(line):
    return int(line.split("iter")[1].split("]")[0])


MARK = foundry.LEARNINGS_TRUNCATION_MARKER
LC = foundry.PROMPT_LEARNINGS_LESSON_CHARS
BC = foundry.PROMPT_LEARNINGS_BUDGET_CHARS


# --------------------------------------------------------------------------
# Behavior 1 -- backward-compatible default (both budget params None)
# --------------------------------------------------------------------------
def test_b01_default_is_backward_compatible():
    # a lesson far longer than the per-lesson cap must appear IN FULL by default
    long_body = "z" * (LC + 500)
    long_lesson = f"- [ENG iter07] HEADMARK {long_body} TAILMARK"
    text = _learnings_text([_lesson(1), _lesson(2), long_lesson], "pattern a", "pattern b")

    d_default = foundry.learnings_digest(text)
    d_none = foundry.learnings_digest(text, max_chars=None, lesson_chars=None)
    d_rec = foundry.learnings_digest(text, recent=12)
    # both-None (and recent=default-12) reproduce today's exact output
    assert d_default == d_none == d_rec

    # the over-long lesson is present in FULL, and NO truncation marker appears
    assert "TAILMARK" in d_default, "default digest dropped the tail of a long lesson"
    assert MARK not in d_default, "default digest inserted a truncation marker"
    # structure preserved: head + count header + all 3 lessons present
    assert "## Patterns" in d_default
    k, m = _header_counts(d_default)
    assert (k, m) == (3, 3), (k, m)
    for i in (1, 2):
        assert _marker(i) in d_default


def test_b01_recent_still_bounds_by_count_when_no_budget():
    text = _learnings_text([_lesson(i) for i in range(1, 11)])  # 10 lessons
    d = foundry.learnings_digest(text, recent=3)
    assert _header_counts(d) == (3, 10)
    for i in (8, 9, 10):
        assert _marker(i) in d
    for i in range(1, 8):
        assert _marker(i) not in d


# --------------------------------------------------------------------------
# Behavior 2 -- per-lesson truncation (and its boundary)
# --------------------------------------------------------------------------
def test_b02_per_lesson_truncation_and_boundary():
    C = 60
    assert C > len(MARK)
    eqC = _lesson_of_len(1, C)        # length exactly C -> unchanged
    cplus1 = _lesson_of_len(2, C + 1)  # length C+1 -> truncated to C, ends w/ marker
    short = _lesson_of_len(3, 40)      # length < C -> unchanged
    text = _learnings_text([eqC, cplus1, short])

    d = foundry.learnings_digest(text, recent=50, lesson_chars=C)
    em = {_id_of(ln): ln for ln in _emitted_lessons(d)}
    assert set(em) == {1, 2, 3}

    # every emitted lesson line is within the cap
    for ln in em.values():
        assert len(ln) <= C, (len(ln), ln)

    # exactly-C lesson: unchanged, no marker
    assert em[1] == eqC
    assert not em[1].endswith(MARK)
    assert len(em[1]) == C

    # C+1 lesson: truncated to EXACTLY C, ends with marker, == line[:C-len(MARK)] + MARK
    assert len(em[2]) == C
    assert em[2].endswith(MARK)
    assert em[2] == cplus1[: C - len(MARK)] + MARK

    # short lesson: unchanged, no marker
    assert em[3] == short
    assert not em[3].endswith(MARK)


def test_b02_marker_is_spec_literal_ascii():
    # Behaviors 2/9 name the marker literally as " [...]"
    assert MARK == " [...]"
    assert MARK.isascii() and len(MARK) > 0


# --------------------------------------------------------------------------
# Behavior 3 -- total-budget admission, newest-first, contiguous suffix
# --------------------------------------------------------------------------
def test_b03_budget_admits_newest_contiguous_suffix():
    L = 100
    n = 6
    lessons = [_lesson_of_len(i, L) for i in range(1, n + 1)]  # ids 1..6, each 100
    text = _learnings_text(lessons)
    B = 350  # 3 lessons (300) fit; a 4th (400) would exceed
    d = foundry.learnings_digest(text, recent=50, max_chars=B)
    em = _emitted_lessons(d)
    ids = [_id_of(ln) for ln in em]

    # emitted total within budget
    assert sum(len(ln) for ln in em) <= B
    # emitted in document (ascending) order
    assert ids == sorted(ids), ids
    # a CONTIGUOUS SUFFIX of the window (the newest that fit): ids [4,5,6]
    assert ids == [4, 5, 6], ids
    # stopping condition: adding the next-older lesson would exceed B
    dropped_next = L  # length of the first-dropped (id 3) line, untruncated
    assert sum(len(ln) for ln in em) + dropped_next > B


def test_b03_degenerate_newest_exceeds_tiny_budget():
    lessons = [_lesson_of_len(i, 100) for i in range(1, 5)]  # M = 4
    text = _learnings_text(lessons)
    d = foundry.learnings_digest(text, recent=50, max_chars=50)  # even newest (100) > 50
    em = _emitted_lessons(d)
    assert em == []  # empty (contiguous-empty) suffix, no negative-slice wrap-around
    k, m = _header_counts(d)
    assert (k, m) == (0, 4), (k, m)


# --------------------------------------------------------------------------
# Behavior 4 -- truncation and budget compose
# --------------------------------------------------------------------------
def test_b04_truncation_and_budget_compose():
    C = 200
    B = 700
    # each lesson far longer than C -> each truncates to EXACTLY C (200);
    # under B=700, floor(700/200)=3 truncated lines (600) fit, a 4th (800) would exceed.
    lessons = [_lesson_of_len(i, 1000) for i in range(1, 9)]  # ids 1..8
    text = _learnings_text(lessons)
    d = foundry.learnings_digest(text, recent=50, max_chars=B, lesson_chars=C)
    em = _emitted_lessons(d)

    # invariant 1: every emitted line <= C
    for ln in em:
        assert len(ln) <= C, (len(ln), ln)
    # invariant 2: emitted total <= B
    assert sum(len(ln) for ln in em) <= B
    # newest contiguous suffix (ids 6,7,8) in ascending order
    ids = [_id_of(ln) for ln in em]
    assert ids == sorted(ids)
    assert ids == [6, 7, 8], ids
    # each was truncated (ends with marker, since each source is 1000 > 200)
    for ln in em:
        assert ln.endswith(MARK)
        assert len(ln) == C


# --------------------------------------------------------------------------
# Behavior 5 -- header reflects the KEPT count after budget drop
# --------------------------------------------------------------------------
def test_b05_header_reflects_kept_and_total():
    lessons = [_lesson_of_len(i, 100) for i in range(1, 11)]  # M = 10
    text = _learnings_text(lessons)
    d = foundry.learnings_digest(text, recent=50, max_chars=350)  # 3 fit
    k, m = _header_counts(d)
    assert m == 10, "M must be the total count of ALL lesson lines, unaffected by budget"
    assert k == len(_emitted_lessons(d)), (k, len(_emitted_lessons(d)))
    assert k == 3, k


def test_b05_total_unaffected_by_truncation():
    lessons = [_lesson_of_len(i, 1000) for i in range(1, 6)]  # M = 5, all long
    text = _learnings_text(lessons)
    # truncation only (generous budget) -> all 5 kept, header still "of 5"
    d = foundry.learnings_digest(text, recent=50, lesson_chars=200, max_chars=100000)
    k, m = _header_counts(d)
    assert (k, m) == (5, 5), (k, m)


# --------------------------------------------------------------------------
# Behavior 6 -- head is always verbatim; budget/truncation touch only lessons
# --------------------------------------------------------------------------
def test_b06_head_verbatim_under_budget():
    long_pattern = "y" * (LC + 1500)  # a pattern bullet far longer than the cap
    lessons = [_lesson_of_len(i, 500) for i in range(1, 6)]
    text = _learnings_text(lessons, long_pattern, "another rule")
    d = foundry.learnings_digest(text, recent=50, max_chars=100, lesson_chars=60)
    head = _head_portion(d)
    # the over-long PATTERN bullet appears in full in the head, untouched
    assert ("- " + long_pattern) in head, "long pattern bullet was truncated in the head"
    assert MARK not in head, "truncation marker leaked into the verbatim head"
    assert "## Patterns" in head


def test_b06_placeholder_head_under_budget():
    # no '## Patterns' section -> placeholder head still emitted, even with budget
    lessons = [_lesson_of_len(i, 1000) for i in range(1, 4)]
    text = "\n".join(lessons) + "\n"
    d = foundry.learnings_digest(text, recent=50, max_chars=100, lesson_chars=60)
    head = _head_portion(d)
    nonblank = [ln.rstrip() for ln in head.splitlines() if ln.strip()]
    assert nonblank == ["## Patterns", "(none recorded yet)"], nonblank
    assert MARK not in head


# --------------------------------------------------------------------------
# Behavior 7 -- bounded oracle (the regression test the docstring lacked)
# --------------------------------------------------------------------------
def test_b07_bounded_oracle_pathological_input():
    C = 800
    B = 5000
    R = 50
    # 30 lessons, each 6000 chars (far exceeding C AND collectively far exceeding B)
    lessons = [_lesson_of_len(i, 6000) for i in range(1, 31)]
    text = _learnings_text(lessons)
    d = foundry.learnings_digest(text, recent=R, max_chars=B, lesson_chars=C)
    em = _emitted_lessons(d)
    # the lessons section total is bounded by B
    assert sum(len(ln) for ln in em) <= B, sum(len(ln) for ln in em)
    # every emitted lesson line is bounded by C
    assert all(len(ln) <= C for ln in em), [len(ln) for ln in em]
    # and (sanity) the budget actually bound (fewer than all 30 kept)
    assert 0 < len(em) < 30, len(em)


def test_b07_bounded_oracle_with_module_defaults():
    # the same oracle using the real module constants as the budget knobs
    lessons = [_lesson_of_len(i, LC + 4000) for i in range(1, 40)]
    text = _learnings_text(lessons)
    d = foundry.learnings_digest(text, recent=100, max_chars=BC, lesson_chars=LC)
    em = _emitted_lessons(d)
    assert sum(len(ln) for ln in em) <= BC
    assert all(len(ln) <= LC for ln in em)


# --------------------------------------------------------------------------
# Behavior 8 -- constants
# --------------------------------------------------------------------------
def test_b08_constants_types_and_ordering():
    assert isinstance(foundry.PROMPT_LEARNINGS_LESSON_CHARS, int)
    assert isinstance(foundry.PROMPT_LEARNINGS_BUDGET_CHARS, int)
    assert 0 < foundry.PROMPT_LEARNINGS_LESSON_CHARS < foundry.PROMPT_LEARNINGS_BUDGET_CHARS
    assert isinstance(foundry.LEARNINGS_TRUNCATION_MARKER, str)
    assert len(foundry.LEARNINGS_TRUNCATION_MARKER) > 0
    assert foundry.LEARNINGS_TRUNCATION_MARKER.isascii()


def test_b08_constant_spec_values():
    # values named explicitly in the PM spec's Design section
    assert foundry.PROMPT_LEARNINGS_LESSON_CHARS == 800
    assert foundry.PROMPT_LEARNINGS_BUDGET_CHARS == 10000
    assert foundry.LEARNINGS_TRUNCATION_MARKER == " [...]"


def test_b08_existing_recent_constant_unchanged():
    # spec Out of Scope: PROMPT_LEARNINGS_RECENT value is not changed by this iter
    assert isinstance(foundry.PROMPT_LEARNINGS_RECENT, int)
    assert foundry.PROMPT_LEARNINGS_RECENT >= 1


# --------------------------------------------------------------------------
# Behavior 9 -- build_prompt inlines a BOUNDED digest
# --------------------------------------------------------------------------
def test_b09_build_prompt_inlines_bounded_digest(tmp_path):
    long_body = "z" * (LC + 800)
    long_lesson = f"- [ENG iter42] HEADSENT {long_body} TAILSENT"
    text = _learnings_text([_lesson(1), long_lesson], "a rule")
    cfg = _cfg_with_learnings(tmp_path, text)

    it_dir = cfg.state / "iter-104"
    out = it_dir / "pm.md"
    prompt = foundry.build_prompt(cfg, 104, "pm", "pm.md", out, it_dir, "")

    # the over-long lesson is inlined in TRUNCATED form
    assert MARK in prompt, "no truncation marker in the inlined digest"
    assert "HEADSENT" in prompt, "the head of the long lesson is missing from the prompt"
    assert "TAILSENT" not in prompt, "the full body of the long lesson leaked into the prompt"
    # no inlined lesson line exceeds the per-lesson cap
    bracket = [ln for ln in prompt.splitlines() if ln.lstrip().startswith("- [")]
    assert bracket, "no inlined lesson lines found in the prompt"
    for ln in bracket:
        assert len(ln) <= LC, (len(ln), ln)


def test_b09_build_prompt_total_bounded(tmp_path):
    # many long lessons -> the inlined lessons tail is bounded by the budget
    lessons = [_lesson_of_len(i, LC + 2000) for i in range(1, 30)]
    text = _learnings_text(lessons)
    cfg = _cfg_with_learnings(tmp_path, text)
    it_dir = cfg.state / "iter-104"
    out = it_dir / "engineer.md"
    prompt = foundry.build_prompt(cfg, 104, "engineer", "engineer.md", out, it_dir, "")
    bracket = [ln for ln in prompt.splitlines() if ln.lstrip().startswith("- [")]
    assert sum(len(ln) for ln in bracket) <= BC
    assert all(len(ln) <= LC for ln in bracket)


# --------------------------------------------------------------------------
# Behavior 10 -- CLI / agents parity preserved (FULL, untruncated content)
# --------------------------------------------------------------------------
def _cap(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    return rc, buf.getvalue()


def test_b10_human_cli_emits_full_digest(tmp_path):
    long_body = "z" * (LC + 600)
    long_lesson = f"- [ENG iter11] {long_body} TAILFULL"
    text = _learnings_text([_lesson(1), long_lesson])
    cfg = _cfg_with_learnings(tmp_path, text)
    rc, out = _cap(lambda: foundry.learnings_cli(cfg, recent=12))
    assert rc == 0
    # the human path prints exactly the UNBUDGETED digest + newline
    assert out == foundry.learnings_digest(text, recent=12) + "\n"
    assert "TAILFULL" in out, "human CLI truncated a lesson (budget leaked into the CLI)"
    assert MARK not in out


def test_b10_json_cli_emits_full_content(tmp_path):
    long_body = "z" * (LC + 600)
    long_lesson = f"- [ENG iter11] {long_body} TAILFULLJSON"
    text = _learnings_text([_lesson(1), long_lesson])
    cfg = _cfg_with_learnings(tmp_path, text)
    rc, out = _cap(lambda: foundry.learnings_cli(cfg, recent=12, as_json=True))
    assert rc == 0
    obj = json.loads(out)
    assert "TAILFULLJSON" in out, "--json CLI truncated a lesson"
    # the full lesson is present in the recent_lessons bucket, untruncated
    joined = "\n".join(obj["recent_lessons"])
    assert "TAILFULLJSON" in joined
    assert MARK not in joined


def test_b10_render_agents_md_emits_full_content():
    long_body = "z" * (LC + 600)
    long_lesson = f"- [ENG iter11] {long_body} TAILAGENTS"
    text = _learnings_text([_lesson(1), long_lesson])
    out = foundry.render_agents_md(text, "SomeProduct", recent=12)
    # embeds the UNBUDGETED digest verbatim
    assert foundry.learnings_digest(text, recent=12) in out
    assert "TAILAGENTS" in out, "render_agents_md truncated a lesson"
    assert MARK not in out


def test_b10_cli_signature_has_no_budget_params():
    # parity: learnings_cli was NOT given budget params (so it stays full-content)
    params = list(inspect.signature(foundry.learnings_cli).parameters)
    assert params == ["cfg", "recent", "as_json"], params


# --------------------------------------------------------------------------
# Behavior 11 -- imports + dormancy + resume
# --------------------------------------------------------------------------
def test_b11_modules_import_and_public_api_callable():
    assert foundry is not None
    assert dispatcher is not None
    for name in ("learnings_digest", "build_prompt", "learnings_cli", "render_agents_md"):
        assert callable(getattr(foundry, name)), name


def test_b11_orchestrators_present():
    for name in ("run_iteration", "run_continuous", "run_stage",
                 "run_scout_phase", "run_execution_plan"):
        assert hasattr(foundry, name), f"orchestrator {name} missing"
        assert callable(getattr(foundry, name))


def test_b11_learnings_digest_signature_is_additive():
    params = inspect.signature(foundry.learnings_digest).parameters
    assert list(params) == ["text", "recent", "max_chars", "lesson_chars"], list(params)
    assert params["recent"].default == 12
    assert params["max_chars"].default is None
    assert params["lesson_chars"].default is None
