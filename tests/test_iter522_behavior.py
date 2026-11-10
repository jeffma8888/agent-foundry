"""Iteration 522 -- BLACK-BOX behavior tests: `lint_config` warns when a set
`goal` will not reach the prompt as written (blank once collapsed, or longer
than GOAL_MAX_CHARS once collapsed).

Spec under test: products/_platform/state/iter-522/pm.md (EB1-EB11).

ISOLATION HONORED: written from `pm.md`, README.md, the roadmap files, the
repo's own `tests/` conventions and the product's RUNTIME surface (calling its
public functions and its CLI) ONLY.  No implementation source, no engineer /
reviewer note and no `git diff` was read.

FRESH-CLONE SAFE: every fixture is built under `tmp_path`; the shipped
products/*/config.json files are COPIED into tmp_path before loading so no
gitignored local overlay can leak in.  OFFLINE: the only subprocess is the
product's own `lint-config` CLI against a tmp_path config (EB8).
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

WARN_BLANK = "renders no prompt line"
LABEL = "- Operator goal (steer within the vision, never outside it): "


# --------------------------------------------------------------------------
# fixtures -- ALWAYS under tmp_path
# --------------------------------------------------------------------------
def _valid_cfg(tmp_path, **over):
    tmp_path = pathlib.Path(tmp_path)
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    vision = tmp_path / "VISION.md"
    vision.write_text("intent")
    roadmap = tmp_path / "ROADMAP.md"
    roadmap.write_text("roadmap")
    qref = tmp_path / "qref"
    qref.mkdir(exist_ok=True)
    roles = tmp_path / "roles"
    roles.mkdir(exist_ok=True)
    data = dict(name="prod", repo=str(repo), allowed_push_repo="prod",
                vision=str(vision), roadmap=str(roadmap),
                quality_ref=str(qref), roles_dir=str(roles),
                test_cmd="uv run pytest", push_enabled=True)
    data.update(over)
    return foundry.ProductConfig(**data)


def _goal_findings(lint):
    return [f for f in lint.findings if f.field == "goal"]


def _collapse(s):
    return " ".join(s.split())


def _words_of_len(n):
    """A goal string whose COLLAPSED form is exactly n chars."""
    base = ("ship the doctor json verb " * 40)
    s = _collapse(base)[:n]
    assert not s.endswith(" ")
    if len(s) < n:
        s = s + "x" * (n - len(s))
    s = s[:n - 1] + "y" if s[n - 1] == " " else s
    assert len(_collapse(s)) == n
    return s


def _padded(s, pad="   "):
    """Same collapsed text, but raw string longer: widen every space run."""
    out = s.replace(" ", pad)
    assert _collapse(out) == _collapse(s)
    return out


# --- EB1 -------------------------------------------------------------------
def test_eb1_default_goal_no_finding_and_identical(tmp_path):
    variants = [{}, {"name": ""}, {"vision": ""}, {"test_cmd": "   "},
                {"allowed_push_repo": ""}, {"name": 5},
                {"quality_ref": str(pathlib.Path(tmp_path) / "nq")}]
    for over in variants:
        default = foundry.lint_config(_valid_cfg(tmp_path, **over))
        explicit = foundry.lint_config(_valid_cfg(tmp_path, goal="", **over))
        assert _goal_findings(default) == [], over
        assert _goal_findings(explicit) == [], over
        assert explicit.findings == default.findings, over
        assert (explicit.verdict, explicit.exit_code) == (
            default.verdict, default.exit_code)
    clean = foundry.lint_config(_valid_cfg(tmp_path))
    assert list(clean.findings) == []
    assert clean.verdict == "OK" and clean.exit_code == 0


# --- EB2 -------------------------------------------------------------------
@pytest.mark.parametrize("goal", ["ship the doctor json", "x",
                                  "  leading and trailing  ",
                                  "a" * 300, "ship\tthe\nverb"])
def test_eb2_ordinary_goal_no_finding(tmp_path, goal):
    lint = foundry.lint_config(_valid_cfg(tmp_path, goal=goal))
    assert _goal_findings(lint) == []
    assert lint.verdict == "OK"


# --- EB3 -------------------------------------------------------------------
@pytest.mark.parametrize("goal", ["   ", "\n\t ", "\u2028", " ", "\xa0\n"])
def test_eb3_whitespace_goal_warns_once(tmp_path, goal):
    lint = foundry.lint_config(_valid_cfg(tmp_path, goal=goal))
    gf = _goal_findings(lint)
    assert len(gf) == 1, lint.findings
    assert gf[0].level == "warn"
    assert WARN_BLANK in gf[0].detail


# --- EB4 -------------------------------------------------------------------
@pytest.mark.parametrize("n", [301, 900])
def test_eb4_overcap_goal_warns_once(tmp_path, n):
    lint = foundry.lint_config(_valid_cfg(tmp_path, goal="x" * n))
    gf = _goal_findings(lint)
    assert len(gf) == 1, lint.findings
    f = gf[0]
    assert f.level == "warn"
    assert str(n) in f.detail
    assert "GOAL_MAX_CHARS=300" in f.detail
    assert "truncated" in f.detail
    assert WARN_BLANK not in f.detail


def test_eb4_detail_names_collapsed_not_raw_length(tmp_path):
    goal = _padded(_words_of_len(320))
    raw = len(goal)
    assert raw > 320
    gf = _goal_findings(foundry.lint_config(_valid_cfg(tmp_path, goal=goal)))
    assert len(gf) == 1
    assert "320" in gf[0].detail
    assert str(raw) not in gf[0].detail


# --- EB5 -------------------------------------------------------------------
def test_eb5_collapsed_300_padded_raw_no_finding(tmp_path):
    s = _words_of_len(300)
    for goal in (s, _padded(s), _padded(s, "  \n "), "  " + s + "\n\n"):
        assert len(_collapse(goal)) == 300
        lint = foundry.lint_config(_valid_cfg(tmp_path, goal=goal))
        assert _goal_findings(lint) == [], (len(goal), lint.findings)


def test_eb5_collapsed_301_warns(tmp_path):
    s = _words_of_len(301)
    for goal in (s, _padded(s)):
        gf = _goal_findings(foundry.lint_config(_valid_cfg(tmp_path, goal=goal)))
        assert len(gf) == 1 and gf[0].level == "warn"
        assert "301" in gf[0].detail


# --- EB6 -------------------------------------------------------------------
def test_eb6_cap_read_at_call_time(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry, "GOAL_MAX_CHARS", 10)
    gf = _goal_findings(foundry.lint_config(_valid_cfg(tmp_path, goal="x" * 11)))
    assert len(gf) == 1 and gf[0].level == "warn"
    assert "GOAL_MAX_CHARS=10" in gf[0].detail
    assert "11" in gf[0].detail
    assert _goal_findings(
        foundry.lint_config(_valid_cfg(tmp_path, goal="x" * 10))) == []


# --- EB7 -------------------------------------------------------------------
@pytest.mark.parametrize("goal", [5, ["a"], None, {"k": "v"}])
def test_eb7_mistyped_goal_lone_type_error(tmp_path, goal):
    lint = foundry.lint_config(_valid_cfg(tmp_path, goal=goal))
    gf = _goal_findings(lint)
    assert [f.level for f in gf] == ["error"], lint.findings
    assert lint.exit_code == 1


# --- EB8 -------------------------------------------------------------------
@pytest.mark.parametrize("goal", ["   ", "x" * 400])
def test_eb8_warning_never_flips_ok(tmp_path, goal):
    lint = foundry.lint_config(_valid_cfg(tmp_path, goal=goal))
    assert [f.field for f in lint.findings] == ["goal"]
    assert lint.verdict == "WARNINGS"
    assert lint.exit_code == 0
    assert lint.n_errors == 0
    assert lint.ok is True


def _write_json_cfg(tmp_path, **over):
    base = pathlib.Path(tmp_path)
    repo = base / "repo"
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    (base / "VISION.md").write_text("intent", encoding="utf-8")
    (base / "ROADMAP.md").write_text("roadmap", encoding="utf-8")
    (base / "qref").mkdir(exist_ok=True)
    (base / "roles").mkdir(exist_ok=True)
    data = dict(name="prod", repo=str(repo), allowed_push_repo="prod",
                vision=str(base / "VISION.md"),
                roadmap=str(base / "ROADMAP.md"),
                quality_ref=str(base / "qref"), roles_dir=str(base / "roles"),
                test_cmd="uv run pytest", push_enabled=True,
                work_root=str(base / "work"))
    data.update(over)
    path = base / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _cli(path):
    return subprocess.run(
        [sys.executable, str(_ROOT / "foundry.py"), "lint-config",
         "--config", str(path)],
        capture_output=True, text=True, timeout=60, cwd=str(_ROOT))


def test_eb8_cli_round_trip(tmp_path):
    ctl = _cli(_write_json_cfg(tmp_path / "ctl"))
    assert ctl.returncode == 0, ctl.stdout + ctl.stderr
    assert ctl.stdout.strip().splitlines()[-1] == "verdict: OK"

    r = _cli(_write_json_cfg(tmp_path / "ws", goal="   "))
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.strip().splitlines()
    assert lines[-1] == "verdict: WARNINGS"
    assert WARN_BLANK in r.stdout


# --- EB9 -------------------------------------------------------------------
def test_eb9_goal_finding_is_last(tmp_path):
    tmp_path = pathlib.Path(tmp_path)
    over = dict(name=5,  # wrong-type finding
                quality_ref=str(tmp_path / "nq"),  # quality_ref warn
                vision="", goal="\n\t ")
    lint = foundry.lint_config(_valid_cfg(tmp_path, **over))
    fields = [f.field for f in lint.findings]
    assert "name" in fields and "quality_ref" in fields
    assert fields[-1] == "goal"
    assert fields.count("goal") == 1
    assert lint.findings[-1].level == "warn"
    # the rest of the tuple is exactly what the same config gives sans goal
    base = foundry.lint_config(_valid_cfg(tmp_path, **dict(over, goal="")))
    assert tuple(lint.findings[:-1]) == tuple(base.findings)


def test_eb9_overcap_also_last(tmp_path):
    tmp_path = pathlib.Path(tmp_path)
    over = dict(test_cmd=7, quality_ref=str(tmp_path / "nq2"),
                goal="y" * 333)
    lint = foundry.lint_config(_valid_cfg(tmp_path, **over))
    assert lint.findings[-1].field == "goal"
    assert "333" in lint.findings[-1].detail
    base = foundry.lint_config(_valid_cfg(tmp_path, **dict(over, goal="")))
    assert tuple(lint.findings[:-1]) == tuple(base.findings)


# --- EB10 ------------------------------------------------------------------
def test_eb10_goal_line_unchanged(tmp_path):
    for goal in ("   ", "\n\t ", "\u2028", ""):
        assert foundry.goal_line(_valid_cfg(tmp_path, goal=goal), "pm") == ""
    s = "x" * 900
    line = foundry.goal_line(_valid_cfg(tmp_path, goal=s), "pm")
    assert line.rstrip("\n") == LABEL + "x" * 297 + "..."
    s301 = _padded(_words_of_len(301))
    line = foundry.goal_line(_valid_cfg(tmp_path, goal=s301), "pm")
    assert line.rstrip("\n") == LABEL + _collapse(s301)[:297] + "..."
    s300 = _padded(_words_of_len(300))
    line = foundry.goal_line(_valid_cfg(tmp_path, goal=s300), "pm")
    assert line.rstrip("\n") == LABEL + _collapse(s300)
    ok = foundry.goal_line(_valid_cfg(tmp_path, goal="ship the doctor json"),
                           "pm")
    assert ok.rstrip("\n") == LABEL + "ship the doctor json"
    # non-PM stages still get nothing
    assert foundry.goal_line(_valid_cfg(tmp_path, goal=s), "tester") == ""


def test_eb10_lint_does_not_mutate_config(tmp_path):
    cfg = _valid_cfg(tmp_path, goal="x" * 900)
    before = dataclasses.asdict(cfg)
    foundry.lint_config(cfg)
    assert dataclasses.asdict(cfg) == before


# --- EB11 ------------------------------------------------------------------
def test_eb11_shipped_configs_have_no_goal_finding(tmp_path):
    # the git-TRACKED product configs (untracked local products are ignored)
    tracked = ("_platform", "graphql-rest-gateway", "reflect-mcp", "repolens")
    shipped = [_ROOT / "products" / n / "config.json" for n in tracked]
    assert all(p.is_file() for p in shipped)
    for i, p in enumerate(shipped):
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "goal" not in data, p
        # copy so no gitignored sibling overlay (config.local.json) applies
        dst = pathlib.Path(tmp_path) / ("c%d" % i) / p.parent.name
        dst.mkdir(parents=True)
        shutil.copy(p, dst / "config.json")
        lint = foundry.lint_config(foundry.load_config(str(dst / "config.json")))
        assert _goal_findings(lint) == [], (p, lint.findings)
