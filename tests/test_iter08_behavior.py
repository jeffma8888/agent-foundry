"""Black-box behaviour tests for iter 08 -- inline the bounded learnings digest
into EVERY stage prompt via `build_prompt`.

ISOLATION: written from the PM spec (Expected Behaviors 1-8) and the product's
own observable behavior only. The implementation source (foundry.py internals),
the engineer/reviewer notes, and `git diff` were NOT read. Every check drives
the public interface: a minimal temp config built with `_write_cfg` +
`foundry.load_config`, a real `LEARNINGS.md` written at the path `cfg.learnings`
resolves to (`<work_root>/LEARNINGS.md`), then `foundry.build_prompt(...)` and
assertions on the returned STRING. Expected digests are computed via the public
pure helper `foundry.learnings_digest(...)`. Fully offline and deterministic --
real temp files only, NO subprocess/git/network/agent-run.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers (mirror the suite's conventions)
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


def _marker(i):
    return f"UNIQMARK-{i:03d}"


def _lesson(i, tag="ENG"):
    """A role-tagged lesson line: `- [ENG iterNN] <unique marker> ...`."""
    return f"- [{tag} iter{i:02d}] {_marker(i)} some durable detail text here"


def _patterns_head(*bullets):
    """A `## Patterns` head: heading + blurb + plain `- ` pattern bullets."""
    lines = ["## Patterns", "", "Read this head first; the tail is the history.", ""]
    lines += [f"- {b}" for b in bullets]
    return "\n".join(lines)


def _learnings_text(n_lessons, *patterns):
    """A realistic LEARNINGS.md: patterns head + chronological lessons tail."""
    head = _patterns_head(*patterns) if patterns else _patterns_head("a durable rule")
    tail = "\n".join(_lesson(i) for i in range(1, n_lessons + 1))
    return head + "\n\n## Chronological lessons\n\n" + tail + "\n"


def _count_bracket_lines(text):
    """Count lines whose left-stripped form starts with the 3 chars '- ['."""
    return sum(1 for ln in text.splitlines() if ln.lstrip().startswith("- ["))


def _build(cfg, stage, role_file, extra=""):
    it_dir = cfg.state / "iter-08"
    out = it_dir / role_file
    return foundry.build_prompt(cfg, 8, stage, role_file, out, it_dir, extra)


# --------------------------------------------------------------------------
# Behavior 1 -- digest inlined VERBATIM into the PM prompt
# --------------------------------------------------------------------------
def test_b01_digest_inlined_verbatim_pm(tmp_path):
    text = _learnings_text(5, "pattern bullet alpha", "pattern bullet beta")  # >=2 pats, >=3 lessons
    cfg = _cfg_with_learnings(tmp_path, text)
    prompt = _build(cfg, "pm", "pm.md", "")
    expected = foundry.learnings_digest(text, recent=foundry.PROMPT_LEARNINGS_RECENT)
    assert expected in prompt, (
        "learnings_digest(<file text>, recent=PROMPT_LEARNINGS_RECENT) is not a "
        "contiguous substring of the PM prompt (digest not inlined verbatim)"
    )


# --------------------------------------------------------------------------
# Behavior 2 -- same digest for a non-PM stage (stage-agnostic)
# --------------------------------------------------------------------------
def test_b02_same_digest_non_pm_stage(tmp_path):
    text = _learnings_text(5, "pattern alpha", "pattern beta")
    cfg = _cfg_with_learnings(tmp_path, text)
    expected = foundry.learnings_digest(text, recent=foundry.PROMPT_LEARNINGS_RECENT)
    pm_prompt = _build(cfg, "pm", "pm.md", "")
    eng_prompt = _build(cfg, "engineer", "engineer.md", "")
    assert expected in pm_prompt, "digest missing from pm prompt"
    assert expected in eng_prompt, "digest missing from engineer prompt (not stage-agnostic)"


# --------------------------------------------------------------------------
# Behavior 3 -- bounded by PROMPT_LEARNINGS_RECENT: newest N kept, oldest dropped
# --------------------------------------------------------------------------
def test_b03_bounded_newest_n_oldest_dropped(tmp_path, monkeypatch):
    N = 3
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_RECENT", N)
    # N+2 = 5 lesson lines; oldest 2 must be dropped, newest N kept.
    text = _learnings_text(N + 2, "a plain pattern rule")  # ids 1..5, markers UNIQMARK-001..005
    cfg = _cfg_with_learnings(tmp_path, text)
    prompt = _build(cfg, "pm", "pm.md", "")  # extra="" -> no stray '- [' from caller

    # newest N (ids 3,4,5) present
    for i in (3, 4, 5):
        assert _marker(i) in prompt, f"newest lesson {_marker(i)} missing from bounded prompt"
    # oldest 2 (ids 1,2) absent
    for i in (1, 2):
        assert _marker(i) not in prompt, f"oldest lesson {_marker(i)} leaked past the bound"
    # exactly N lesson lines in the whole prompt
    assert _count_bracket_lines(prompt) == N, (
        f"expected exactly {N} '- [' lesson lines in the prompt, "
        f"got {_count_bracket_lines(prompt)}"
    )
    # sanity: the pure helper at the patched bound also yields exactly N lesson lines
    assert _count_bracket_lines(
        foundry.learnings_digest(text, recent=foundry.PROMPT_LEARNINGS_RECENT)) == N


# --------------------------------------------------------------------------
# Behavior 4 -- the recent bound is a module int read at CALL time (patchable)
# --------------------------------------------------------------------------
def test_b04_recent_bound_is_module_int(tmp_path):
    # spec behavior 4: PROMPT_LEARNINGS_RECENT exists, int, >= 1 by default.
    assert hasattr(foundry, "PROMPT_LEARNINGS_RECENT")
    assert isinstance(foundry.PROMPT_LEARNINGS_RECENT, int)
    assert foundry.PROMPT_LEARNINGS_RECENT >= 1
    # patchability (read at call time, not captured at import) is proven end-to-end
    # in test_b03; here re-confirm the seam bites within build_prompt directly.
    text = _learnings_text(6)  # 6 lessons
    cfg = _cfg_with_learnings(tmp_path, text)
    import unittest.mock as mock
    with mock.patch.object(foundry, "PROMPT_LEARNINGS_RECENT", 2):
        prompt = _build(cfg, "engineer", "engineer.md", "")
    assert _count_bracket_lines(prompt) == 2, (
        "monkeypatched PROMPT_LEARNINGS_RECENT=2 did not bound the inlined digest "
        "-> bound is not read from the module global at call time"
    )


# --------------------------------------------------------------------------
# Behavior 5 -- missing learnings file -> no crash, placeholder digest
# --------------------------------------------------------------------------
def test_b05_missing_file_no_crash_placeholder(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    lp = pathlib.Path(cfg.learnings)
    if lp.exists():
        lp.unlink()
    assert not lp.exists(), "learnings file must be absent for this behavior"

    prompt = _build(cfg, "pm", "pm.md", "")  # must not raise
    assert isinstance(prompt, str) and prompt.strip(), "prompt must be a non-empty string"

    placeholder = foundry.learnings_digest("", recent=foundry.PROMPT_LEARNINGS_RECENT)
    assert placeholder in prompt, "placeholder digest for absent file not inlined"

    # full existing context still present
    assert cfg.repo in prompt
    assert str(pathlib.Path(cfg.roles_dir) / "pm.md") in prompt
    assert "re-delegate" in prompt


# --------------------------------------------------------------------------
# Behavior 6 -- existing prompt contract preserved (purely additive)
# --------------------------------------------------------------------------
def test_b06_existing_contract_preserved(tmp_path):
    text = _learnings_text(4, "p1", "p2")
    cfg = _cfg_with_learnings(tmp_path, text)
    prompt = _build(cfg, "engineer", "engineer.md", "EXTRA-TOKEN")

    assert cfg.repo in prompt
    assert str(pathlib.Path(cfg.roles_dir) / "engineer.md") in prompt
    assert "re-delegate" in prompt          # anti-delegation clause
    assert "EXTRA-TOKEN" in prompt          # passed extra text
    assert cfg.learnings in prompt          # append-path line KEPT


# --------------------------------------------------------------------------
# Behavior 7 -- a recognizable label introduces the inline digest block
# --------------------------------------------------------------------------
def test_b07_label_introduces_digest_block(tmp_path):
    text = _learnings_text(3)
    cfg = _cfg_with_learnings(tmp_path, text)
    prompt = _build(cfg, "pm", "pm.md", "")
    assert "Recent foundry learnings (bounded digest" in prompt, (
        "fixed label 'Recent foundry learnings (bounded digest' missing -> "
        "inline digest block is not greppable/distinguishable from the path line"
    )


# --------------------------------------------------------------------------
# Behavior 8 -- both modules import (whole-suite outcome verified by the runner)
# --------------------------------------------------------------------------
def test_b08_modules_import_and_helper_callable():
    assert foundry is not None
    assert dispatcher is not None
    assert callable(foundry.build_prompt)
    assert callable(foundry.learnings_digest)
