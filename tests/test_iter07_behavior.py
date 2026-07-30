"""Black-box behaviour tests for iter 07 -- the bounded learnings digest.

ISOLATION: written from the PM spec (Expected Behaviors 1-16) and the product's
own observable behavior only. The implementation source (foundry.py internals),
the engineer/reviewer notes, and `git diff` were NOT read. Every check drives
the public interface: the pure function `foundry.learnings_digest(text, recent)`
against synthetic input strings, and the `foundry.py learnings` CLI via
`foundry.main([...])` with a temp config + temp learnings file + capsys. Fully
offline and deterministic -- no real subprocess/git/network/agent run (the one
`doctor` regression check monkeypatches its probe seams, per the iter-01 pattern;
the `--help` check runs `foundry.py --help`, which only prints usage and exits).
"""
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    """Mirror the config-writing helper used across the suite."""
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
    """Write a config + seed <work_root>/LEARNINGS.md (cfg.learnings) with text."""
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    lp = pathlib.Path(cfg.learnings)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(file_text)
    return cfg_path


def _lesson(i, tag="ROLE"):
    """A role-tagged lesson line (`- [ROLE iterNN] ...`) w/ a unique marker."""
    return f"- [{tag} iter{i:02d}] {_marker(i)} some durable detail text here"


def _marker(i):
    return f"lesson-marker-{i:03d}"


def _patterns_head(*bullets):
    """A `## Patterns` head: heading + blurb + plain `- ` pattern bullets."""
    lines = ["## Patterns", "", "Read this head first; the tail is the history.", ""]
    lines += [f"- {b}" for b in bullets]
    return "\n".join(lines)


def _split_at_recent_header(digest):
    """Return (patterns_portion, recent_portion) split at the count header."""
    marker = "## Recent lessons"
    idx = digest.find(marker)
    assert idx != -1, f"digest has no '## Recent lessons' header:\n{digest!r}"
    return digest[:idx], digest[idx:]


def _count_lesson_lines(text):
    """Count lines whose left-stripped form starts with the 3 chars '- ['."""
    return sum(1 for ln in text.splitlines() if ln.lstrip().startswith("- ["))


def _nonblank_lines(text):
    return [ln.rstrip() for ln in text.splitlines() if ln.strip()]


# --------------------------------------------------------------------------
# Behavior 1 -- Patterns head extracted verbatim, terminated by next `## `
# --------------------------------------------------------------------------
def test_b01_patterns_head_terminated_by_next_heading():
    head = _patterns_head("pattern bullet alpha", "pattern bullet beta")
    text = (head + "\n\n## Chronological lessons\n\n"
            + "\n".join(_lesson(i) for i in range(1, 6)) + "\n")
    digest = foundry.learnings_digest(text)
    patterns, _ = _split_at_recent_header(digest)
    assert "## Patterns" in patterns
    assert "- pattern bullet alpha" in patterns
    assert "- pattern bullet beta" in patterns
    # the next `## ` heading terminates the head -> not swallowed into patterns
    assert "## Chronological lessons" not in patterns
    # and the raw chronological heading is not reproduced anywhere in the digest
    assert "## Chronological lessons" not in digest


# --------------------------------------------------------------------------
# Behavior 2 -- head terminated by first lesson line when no `## ` intervenes
# --------------------------------------------------------------------------
def test_b02_patterns_head_terminated_by_first_lesson_line():
    head = _patterns_head("pat one", "pat two")
    # NO `## Chronological lessons` heading between the head and the lessons
    text = head + "\n" + "\n".join(_lesson(i) for i in range(1, 5)) + "\n"
    digest = foundry.learnings_digest(text)
    patterns, recent = _split_at_recent_header(digest)
    assert "- pat one" in patterns
    assert "- pat two" in patterns
    # the head stops before the first lesson line: no lesson markers in patterns
    for i in range(1, 5):
        assert _marker(i) not in patterns, f"lesson {i} leaked into the patterns head"
    # but the lessons still appear (in the recent-lessons portion)
    for i in range(1, 5):
        assert _marker(i) in recent


# --------------------------------------------------------------------------
# Behavior 3 -- recent-lessons truncation keeps the LAST k, drops the rest
# --------------------------------------------------------------------------
def test_b03_recent_lessons_truncation():
    text = "\n".join(_lesson(i) for i in range(1, 11)) + "\n"  # 10 lessons, ids 1..10
    digest = foundry.learnings_digest(text, recent=3)
    for i in (8, 9, 10):  # newest 3 kept
        assert _marker(i) in digest
    for i in range(1, 8):  # oldest 7 dropped
        assert _marker(i) not in digest


# --------------------------------------------------------------------------
# Behavior 4 -- recent >= total keeps all lessons
# --------------------------------------------------------------------------
def test_b04_recent_ge_total_keeps_all():
    text = "\n".join(_lesson(i) for i in range(1, 6)) + "\n"  # 5 lessons
    for k in (5, 12, 999):  # recent == total and recent > total
        digest = foundry.learnings_digest(text, recent=k)
        for i in range(1, 6):
            assert _marker(i) in digest


# --------------------------------------------------------------------------
# Behavior 5 -- relative order of kept lessons is preserved (oldest-kept first)
# --------------------------------------------------------------------------
def test_b05_lesson_order_preserved():
    text = "\n".join(_lesson(i) for i in range(1, 11)) + "\n"  # 10 lessons
    digest = foundry.learnings_digest(text, recent=4)  # keeps ids 7,8,9,10
    positions = [digest.find(_marker(i)) for i in (7, 8, 9, 10)]
    assert all(p != -1 for p in positions), positions
    assert positions == sorted(positions), f"kept lessons out of order: {positions}"


# --------------------------------------------------------------------------
# Behavior 6 -- accurate count header `## Recent lessons (last N of M)`
# --------------------------------------------------------------------------
def test_b06_accurate_count_header():
    text = "\n".join(_lesson(i) for i in range(1, 11)) + "\n"  # M = 10
    assert "## Recent lessons (last 3 of 10)" in foundry.learnings_digest(text, recent=3)
    # N == min(recent, M): recent > M -> N == M
    assert "## Recent lessons (last 10 of 10)" in foundry.learnings_digest(text, recent=50)


# --------------------------------------------------------------------------
# Behavior 7 -- no `## Patterns` section -> placeholder head
# --------------------------------------------------------------------------
def test_b07_no_patterns_section_placeholder_head():
    text = "\n".join(_lesson(i) for i in range(1, 4)) + "\n"  # lessons, no `## Patterns`
    digest = foundry.learnings_digest(text)
    patterns, recent = _split_at_recent_header(digest)
    # patterns portion is exactly the two content lines, in order
    assert _nonblank_lines(patterns) == ["## Patterns", "(none recorded yet)"]
    # the recent-lessons portion is still produced correctly
    assert "## Recent lessons (last 3 of 3)" in recent
    for i in range(1, 4):
        assert _marker(i) in recent


# --------------------------------------------------------------------------
# Behavior 8 -- zero lessons -> no crash, zero-count header, no lesson bullets
# --------------------------------------------------------------------------
def test_b08_zero_lessons_zero_count_header():
    text = _patterns_head("only a pattern bullet") + "\n"  # patterns, no lessons
    digest = foundry.learnings_digest(text)  # must not raise
    assert isinstance(digest, str)
    assert "## Patterns" in digest
    assert "## Recent lessons (last 0 of 0)" in digest
    assert _count_lesson_lines(digest) == 0  # no `- [` bullets anywhere


# --------------------------------------------------------------------------
# Behavior 9 -- empty input -> no crash (placeholder head + zero-count header)
# --------------------------------------------------------------------------
def test_b09_empty_input_no_crash():
    digest = foundry.learnings_digest("")
    assert isinstance(digest, str)
    patterns, recent = _split_at_recent_header(digest)
    assert _nonblank_lines(patterns) == ["## Patterns", "(none recorded yet)"]
    assert "## Recent lessons (last 0 of 0)" in recent


# --------------------------------------------------------------------------
# Behavior 10 -- plain `- ` pattern bullets are NOT counted as lessons
# --------------------------------------------------------------------------
def test_b10_pattern_bullets_not_counted_as_lessons():
    # plain `- ` bullets (no `[`), incl. one whose `[` is NOT adjacent to `- `
    head = _patterns_head("alpha rule", "beta rule", "see the note [ref] below")
    text = (head + "\n\n## Chronological lessons\n\n"
            + _lesson(1) + "\n" + _lesson(2) + "\n")
    digest = foundry.learnings_digest(text)
    # exactly the 2 real lesson lines counted toward M -> `of 2`
    assert "## Recent lessons (last 2 of 2)" in digest


# --------------------------------------------------------------------------
# Behavior 11 -- bounded output: old lessons dropped, digest smaller than input
# --------------------------------------------------------------------------
def test_b11_bounded_output_drops_old_lessons():
    text = (_patterns_head("p1", "p2") + "\n\n## Chronological lessons\n\n"
            + "\n".join(_lesson(i) for i in range(1, 31)) + "\n")  # 30 lessons
    digest = foundry.learnings_digest(text, recent=5)
    assert len(digest.encode("utf-8")) < len(text.encode("utf-8"))
    # exactly 5 lesson lines (count header starts with `## `, so it is excluded)
    assert _count_lesson_lines(digest) == 5


# --------------------------------------------------------------------------
# Behavior 12 -- CLI renders the digest to stdout and returns 0
# --------------------------------------------------------------------------
def test_b12_cli_renders_digest_returns_zero(tmp_path, capsys):
    file_text = (_patterns_head("cli pat one") + "\n\n## Chronological lessons\n\n"
                 + "\n".join(_lesson(i) for i in range(1, 7)) + "\n")  # 6 lessons
    cfg_path = _cfg_with_learnings(tmp_path, file_text)
    rc = foundry.main(["learnings", "--config", str(cfg_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "## Patterns" in out
    assert "## Recent lessons (last 6 of 6)" in out
    # exactly learnings_digest(file_text, recent=<default>) for that file
    assert foundry.learnings_digest(file_text, recent=12) in out


# --------------------------------------------------------------------------
# Behavior 13 -- `--recent` limits the rendered tail
# --------------------------------------------------------------------------
def test_b13_cli_recent_limits_tail(tmp_path, capsys):
    file_text = (_patterns_head("cli pat") + "\n\n## Chronological lessons\n\n"
                 + "\n".join(_lesson(i) for i in range(1, 7)) + "\n")  # 6 lessons
    cfg_path = _cfg_with_learnings(tmp_path, file_text)
    rc = foundry.main(["learnings", "--config", str(cfg_path), "--recent", "3"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "## Recent lessons (last 3 of 6)" in out
    assert _count_lesson_lines(out) == 3
    for i in (4, 5, 6):  # newest 3 shown
        assert _marker(i) in out
    for i in (1, 2, 3):  # older dropped
        assert _marker(i) not in out


# --------------------------------------------------------------------------
# Behavior 14 -- missing learnings file -> graceful empty digest, returns 0
# --------------------------------------------------------------------------
def test_b14_cli_missing_file_graceful(tmp_path, capsys):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    assert not pathlib.Path(cfg.learnings).exists()  # file truly absent
    rc = foundry.main(["learnings", "--config", str(cfg_path)])  # must not raise
    out = capsys.readouterr().out
    assert rc == 0
    assert "## Patterns" in out
    assert "(none recorded yet)" in out
    assert "## Recent lessons (last 0 of 0)" in out


# --------------------------------------------------------------------------
# Behavior 15 -- the default recent window is 12
# --------------------------------------------------------------------------
def test_b15_cli_default_recent_is_twelve(tmp_path, capsys):
    file_text = "\n".join(_lesson(i) for i in range(1, 21)) + "\n"  # 20 lessons, no head
    cfg_path = _cfg_with_learnings(tmp_path, file_text)
    rc = foundry.main(["learnings", "--config", str(cfg_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "## Recent lessons (last 12 of 20)" in out
    assert _count_lesson_lines(out) == 12


# --------------------------------------------------------------------------
# Behavior 16 -- the mechanism imports and breaks nothing (non-regression)
# --------------------------------------------------------------------------
def test_b16_mechanism_imports_and_is_callable():
    assert callable(foundry.learnings_digest)
    assert dispatcher is not None  # `import dispatcher` succeeded at module load


def test_b16_help_lists_all_subcommands():
    foundry_py = pathlib.Path(foundry.__file__).resolve()
    proc = subprocess.run(
        [sys.executable, str(foundry_py), "--help"],
        capture_output=True, text=True, cwd=str(foundry_py.parent),
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    for sub in ("run", "once", "doctor", "learnings"):
        assert sub in combined, f"subcommand {sub!r} missing from --help:\n{combined}"


def test_b16_doctor_still_dispatches(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)

    class _Chk:
        def __init__(self, name, ok):
            self.name, self.ok, self.detail = name, ok, "d"

    monkeypatch.setattr(foundry, "check_power", lambda *a, **k: _Chk("power", True))
    monkeypatch.setattr(foundry, "check_agent", lambda *a, **k: _Chk("agent", True))
    monkeypatch.setattr(foundry, "check_uv", lambda *a, **k: _Chk("uv", True))
    monkeypatch.setattr(foundry, "check_remote", lambda *a, **k: _Chk("remote", True))
    rc = foundry.main(["doctor", "--config", str(cfg_path)])
    assert isinstance(rc, int)  # parsed + dispatched without an argparse error
