"""Iteration 521 -- BLACK-BOX behavior tests: an optional per-product `goal`
config field rendered as ONE `## Context` line for the three PM seats only.

Spec under test: products/_platform/state/iter-521/pm.md (EB1-EB11; EB12 is the
import check, done by hand per the iter-520 TEST lesson and NOT pinned here).

ISOLATION HONORED: written from `pm.md`, README.md, the roadmap files, the
repo's own `tests/` conventions and the product's RUNTIME surface (calling its
public functions and its CLI) ONLY.  No implementation source, no engineer /
reviewer note and no `git diff` was read.

FRESH-CLONE SAFE: every fixture is built under `tmp_path`; nothing is asserted
about gitignored state.  OFFLINE: the only subprocess is the product's own
`overlay` CLI against a tmp_path config (EB10).
"""
from __future__ import annotations

import builtins
import dataclasses
import json
import pathlib
import socket
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

THIS_ITER = 521
LABEL = "- Operator goal (steer within the vision, never outside it): "
GOAL = "ship the X verb"
PM_SEATS = ("pm", "pm_scout_a", "pm_scout_b")
OTHER_STAGES = ("engineer", "reviewer", "tester", "fix", "final")
ALL_STAGES = PM_SEATS + OTHER_STAGES
VISION_PREFIX = "- Product vision (fixed intent, stay inside it): "
ROADMAP_PREFIX = "- Product roadmap file (PM owns): "


# --------------------------------------------------------------------------
# fixtures -- ALWAYS under tmp_path
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, sub="p", **over) -> pathlib.Path:
    base = pathlib.Path(tmp_path) / sub
    base.mkdir(parents=True, exist_ok=True)
    (base / "repo").mkdir(exist_ok=True)
    (base / "VISION.md").write_text("product vision text\n", encoding="utf-8")
    (base / "ROADMAP.md").write_text("- a roadmap item\n", encoding="utf-8")
    data = {
        "name": "demoprod",
        "repo": str(base / "repo"),
        "allowed_push_repo": "demoprod",
        "vision": str(base / "VISION.md"),
        "roadmap": str(base / "ROADMAP.md"),
        "work_root": str(base / "work"),
    }
    data.update(over)
    path = base / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _cfg(tmp_path, sub="p", **over):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, sub, **over)))
    learnings = pathlib.Path(cfg.learnings)
    learnings.parent.mkdir(parents=True, exist_ok=True)
    learnings.write_text("## Patterns\n\n- a durable rule\n\n- [ENG iter01] a lesson\n",
                         encoding="utf-8")
    return cfg


def _prompt(cfg, stage, tmp_path):
    it = pathlib.Path(tmp_path) / "state" / ("iter-%d" % THIS_ITER)
    it.mkdir(parents=True, exist_ok=True)
    return foundry.build_prompt(cfg, THIS_ITER, stage, "%s.md" % stage,
                                it / ("%s.md" % stage), it, "extra context")


# --------------------------------------------------------------------------
# EB1 -- field declared right after quality_bar, default "", tail unchanged
# --------------------------------------------------------------------------
def test_eb1_goal_field_type_default_and_position() -> None:
    fields = {f.name: f for f in dataclasses.fields(foundry.ProductConfig)}
    assert "goal" in fields
    f = fields["goal"]
    assert f.type in ("str", str)
    assert f.default == ""
    names = list(foundry.config_field_names())
    i = names.index("quality_bar")
    assert names[i + 1] == "goal"
    assert names.count("goal") == 1
    assert names[-2:] == ["notify_cmd", "auth_resume_max"]


# --------------------------------------------------------------------------
# EB2 -- load_config: absent -> "", present -> value, overlay -> value
# --------------------------------------------------------------------------
def test_eb2_absent_goal_loads_empty(tmp_path) -> None:
    cfg = foundry.load_config(str(_write_cfg(tmp_path, "absent")))
    assert cfg.goal == ""


def test_eb2_present_goal_loads_verbatim(tmp_path) -> None:
    cfg = foundry.load_config(str(_write_cfg(tmp_path, "present", goal=GOAL)))
    assert cfg.goal == GOAL


def test_eb2_overlay_goal_loads(tmp_path) -> None:
    path = _write_cfg(tmp_path, "ovl")
    (path.parent / "config.local.json").write_text(json.dumps({"goal": GOAL}),
                                                   encoding="utf-8")
    cfg = foundry.load_config(str(path))
    assert cfg.goal == GOAL


# --------------------------------------------------------------------------
# EB3 -- constants
# --------------------------------------------------------------------------
def test_eb3_constants() -> None:
    assert foundry.PROMPT_GOAL_LABEL == LABEL
    assert type(foundry.GOAL_MAX_CHARS) is int
    assert foundry.GOAL_MAX_CHARS == 300


# --------------------------------------------------------------------------
# EB4 -- empty-result arms
# --------------------------------------------------------------------------
def _with_goal(tmp_path, goal, sub="g"):
    return dataclasses.replace(_cfg(tmp_path, sub), goal=goal)


@pytest.mark.parametrize("stage", OTHER_STAGES + ("", "PM", "unknown"))
def test_eb4_non_pm_stage_gives_empty(tmp_path, stage) -> None:
    assert foundry.goal_line(_with_goal(tmp_path, GOAL), stage) == ""


@pytest.mark.parametrize("stage", PM_SEATS)
def test_eb4_pm_seat_gives_a_line(tmp_path, stage) -> None:
    assert foundry.goal_line(_with_goal(tmp_path, GOAL), stage) == LABEL + GOAL + "\n"


@pytest.mark.parametrize("goal", ["", " ", "\n\t \r\n", "\u2028 \x0b"])
def test_eb4_blank_goal_gives_empty(tmp_path, goal) -> None:
    cfg = _with_goal(tmp_path, goal)
    for stage in PM_SEATS:
        assert foundry.goal_line(cfg, stage) == ""


@pytest.mark.parametrize("goal", [None, 5, 3.5, b"ship it", ["ship"], {"a": 1}, True])
def test_eb4_non_str_goal_gives_empty(tmp_path, goal) -> None:
    cfg = _with_goal(tmp_path, goal)
    for stage in PM_SEATS:
        assert foundry.goal_line(cfg, stage) == ""


def test_eb4_stage_set_is_read_live(tmp_path, monkeypatch) -> None:
    cfg = _with_goal(tmp_path, GOAL)
    monkeypatch.setattr(foundry, "PROMPT_DRIFT_STAGES", ("engineer",))
    assert foundry.goal_line(cfg, "engineer") == LABEL + GOAL + "\n"
    assert foundry.goal_line(cfg, "pm") == ""


# --------------------------------------------------------------------------
# EB5 -- collapse, strip, cap, exactly one newline
# --------------------------------------------------------------------------
def test_eb5_spec_example(tmp_path) -> None:
    cfg = _with_goal(tmp_path, "  ship\n the   X verb ")
    assert foundry.goal_line(cfg, "pm") == (
        "- Operator goal (steer within the vision, never outside it): ship the X verb\n")


def test_eb5_unicode_line_breaks_collapse(tmp_path) -> None:
    cfg = _with_goal(tmp_path, "a\r\nb\u2028c\x0bd\x0ce\x1cf\x85g\th")
    out = foundry.goal_line(cfg, "pm_scout_a")
    assert out == LABEL + "a b c d e f g h\n"
    assert len(out.splitlines()) == 1
    assert out.count("\n") == 1 and out.endswith("\n")


@pytest.mark.parametrize("n", [299, 300])
def test_eb5_at_or_under_cap_is_not_truncated(tmp_path, n) -> None:
    out = foundry.goal_line(_with_goal(tmp_path, "a" * n), "pm")
    assert out == LABEL + "a" * n + "\n"


@pytest.mark.parametrize("n", [301, 400, 5000])
def test_eb5_over_cap_is_truncated_with_ellipsis(tmp_path, n) -> None:
    out = foundry.goal_line(_with_goal(tmp_path, "a" * n), "pm_scout_b")
    assert out == LABEL + "a" * 297 + "...\n"
    assert len(out) == len(LABEL) + 300 + 1


def test_eb5_cap_measured_after_collapse(tmp_path) -> None:
    # 300 visible chars spread with whitespace runs -> collapses to <= 300, no truncation
    goal = "  " + " \n\t ".join(["x" * 9] * 30) + "  "  # 30*9 + 29 spaces = 299
    out = foundry.goal_line(_with_goal(tmp_path, goal), "pm")
    assert out == LABEL + " ".join(["x" * 9] * 30) + "\n"
    assert "..." not in out


def test_eb5_cap_is_read_live(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(foundry, "GOAL_MAX_CHARS", 10)
    out = foundry.goal_line(_with_goal(tmp_path, "abcdefghijKLMN"), "pm")
    assert out == LABEL + "abcdefg...\n"


# --------------------------------------------------------------------------
# EB6 -- total, no I/O
# --------------------------------------------------------------------------
class _Weird:
    def __str__(self):
        raise RuntimeError("boom")

    def __len__(self):
        raise RuntimeError("boom")


@pytest.mark.parametrize("goal", [None, 0, _Weird(), object(), float("nan"), ("a",)])
def test_eb6_never_raises_and_does_no_io(tmp_path, monkeypatch, goal) -> None:
    cfg = _with_goal(tmp_path, goal)

    def _no(*a, **k):
        raise AssertionError("I/O attempted")

    monkeypatch.setattr(subprocess, "run", _no)
    monkeypatch.setattr(subprocess, "Popen", _no)
    monkeypatch.setattr(builtins, "open", _no)
    monkeypatch.setattr(socket, "socket", _no)
    for stage in ALL_STAGES:
        assert foundry.goal_line(cfg, stage) == ""


def test_eb6_real_goal_does_no_io(tmp_path, monkeypatch) -> None:
    cfg = _with_goal(tmp_path, GOAL)

    def _no(*a, **k):
        raise AssertionError("I/O attempted")

    monkeypatch.setattr(subprocess, "run", _no)
    monkeypatch.setattr(builtins, "open", _no)
    monkeypatch.setattr(pathlib.Path, "read_text", _no)
    assert foundry.goal_line(cfg, "pm") == LABEL + GOAL + "\n"


def test_eb6_cfg_without_goal_attribute_does_not_raise() -> None:
    class _Bare:
        pass

    # most reasonable reading of "any cfg": a missing attribute degrades to ""
    assert foundry.goal_line(_Bare(), "pm") == ""


# --------------------------------------------------------------------------
# EB7 -- wired by BARE name, right after the vision line
# --------------------------------------------------------------------------
def _line_index(lines, prefix):
    hits = [i for i, l in enumerate(lines) if l.startswith(prefix)]
    assert len(hits) == 1, (prefix, hits)
    return hits[0]


def test_eb7_monkeypatched_goal_line_bites_at_the_right_spot(tmp_path, monkeypatch) -> None:
    cfg = _cfg(tmp_path, "wire")
    seen = []

    def _fake(c, stage):
        seen.append(stage)
        return "SENTINEL-GOAL-LINE\n"

    monkeypatch.setattr(foundry, "goal_line", _fake)
    lines = _prompt(cfg, "pm", tmp_path).splitlines()
    assert "pm" in seen
    v = _line_index(lines, VISION_PREFIX)
    r = _line_index(lines, ROADMAP_PREFIX)
    assert lines[v + 1] == "SENTINEL-GOAL-LINE"
    assert r == v + 2


# --------------------------------------------------------------------------
# EB8 -- empty goal = byte-identical prompt, every stage
# --------------------------------------------------------------------------
@pytest.mark.parametrize("stage", ALL_STAGES)
def test_eb8_empty_goal_is_byte_identical(tmp_path, monkeypatch, stage) -> None:
    cfg = _cfg(tmp_path, "empty")
    assert cfg.goal == ""
    real = _prompt(cfg, stage, tmp_path)
    monkeypatch.setattr(foundry, "goal_line", lambda c, s: "")
    stub = _prompt(cfg, stage, tmp_path)
    assert real == stub
    assert LABEL not in real


# --------------------------------------------------------------------------
# EB9 -- non-blank goal: PM seats get one line; others unchanged
# --------------------------------------------------------------------------
@pytest.mark.parametrize("stage", PM_SEATS)
def test_eb9_pm_seats_render_the_line_once_after_vision(tmp_path, stage) -> None:
    empty = _prompt(_cfg(tmp_path, "e9", goal=""), stage, tmp_path)
    cfg = _cfg(tmp_path, "g9", goal=GOAL)
    p = _prompt(cfg, stage, tmp_path)
    assert p != empty  # can-fail: the goal DOES change the PM-seat prompt
    lines = p.splitlines()
    want = LABEL + GOAL
    assert lines.count(want) == 1
    v = _line_index(lines, VISION_PREFIX)
    assert lines[v + 1] == want
    assert lines[v + 2].startswith(ROADMAP_PREFIX)


@pytest.mark.parametrize("stage", OTHER_STAGES)
def test_eb9_other_stages_never_see_the_goal(tmp_path, stage) -> None:
    # same directory for both configs so every path in the prompt matches
    cfg_e = _cfg(tmp_path, "same", goal="")
    cfg_g = dataclasses.replace(cfg_e, goal=GOAL)
    p_e = _prompt(cfg_e, stage, tmp_path)
    p_g = _prompt(cfg_g, stage, tmp_path)
    assert LABEL not in p_g
    assert GOAL not in p_g
    assert "Operator goal" not in p_g
    assert p_g == p_e


@pytest.mark.parametrize("stage", PM_SEATS)
def test_eb9_pm_diff_is_exactly_the_one_line(tmp_path, stage) -> None:
    cfg_e = _cfg(tmp_path, "same", goal="")
    cfg_g = dataclasses.replace(cfg_e, goal=GOAL)
    e = _prompt(cfg_e, stage, tmp_path).splitlines()
    g = _prompt(cfg_g, stage, tmp_path).splitlines()
    assert len(g) == len(e) + 1
    v = _line_index(g, VISION_PREFIX)
    assert g[:v + 1] + g[v + 2:] == e


# --------------------------------------------------------------------------
# EB10 -- overlay CLI round-trip on a tmp_path fixture
# --------------------------------------------------------------------------
def test_eb10_overlay_set_goal_round_trip(tmp_path) -> None:
    path = _write_cfg(tmp_path, "cli")
    before = path.read_bytes()
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "foundry.py"), "overlay", "--config", str(path),
         "--set", "goal=" + GOAL],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    local = path.parent / "config.local.json"
    assert local.is_file()
    assert json.loads(local.read_text(encoding="utf-8"))["goal"] == GOAL
    assert path.read_bytes() == before
    assert foundry.load_config(str(path)).goal == GOAL


# --------------------------------------------------------------------------
# EB11 -- README sentence
# --------------------------------------------------------------------------
def test_eb11_readme_names_the_goal_field() -> None:
    text = (_ROOT / "README.md").read_text(encoding="utf-8")
    entry = [l for l in text.splitlines() if l.startswith("# 67.")]
    assert len(entry) == 1
    idx = text.index(entry[0])
    window = text[idx: idx + len(entry[0]) + 2000]
    assert "`goal`" in window
    assert "Operator goal (steer within the vision, never outside it):" in window
    assert 'overlay --config products/<name>/config.json --set "goal=' in window
    low = window.lower()
    assert "scout" in low and "pm" in low
    assert "empty or absent goal changes no prompt" in low
