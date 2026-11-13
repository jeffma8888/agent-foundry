"""Iteration 533 -- BLACK-BOX behavior tests: ``foundry changelog --since``.

Spec under test: products/_platform/state/iter-533/pm.md (9 Expected Behaviors).

ISOLATION CONTRACT (HONORED): written ONLY from the iter-533 PM spec, the
product README, ``tests/`` conventions and the product's observable behaviour
by RUNNING it. The implementation source, the engineer's/reviewer's notes and
``git diff`` were NOT read. Fully offline: the bare-name ``git`` seam and
``load_config`` are monkeypatched; no real git, no gitignored state.
"""
from __future__ import annotations

import datetime as dt

import foundry


def test_b1_parse_since_seven_days():
    assert foundry.parse_since("7d", today=dt.date(2026, 11, 12)) == "2026-11-05"


import json

import pytest

TODAY = dt.date(2026, 11, 12)
BASE_ARGV = ("log", "--oneline", "--no-decorate", "--format=%s")
LINES = (
    "feat: add widget (foundry iter 42)\n"
    "untagged commit\n"
    "fix: repair thing (foundry iter 41)\n"
    "docs: describe thing (foundry iter 40)\n"
)


def _cfg():
    return type("C", (), {"repo": ".", "product": "t", "name": "t"})()


class _Recorder:
    def __init__(self, out=LINES):
        self.calls = []
        self.out = out

    def __call__(self, cfg, *a, **kw):
        self.calls.append(tuple(a))
        return self.out


@pytest.fixture
def rec(monkeypatch):
    r = _Recorder()
    monkeypatch.setattr(foundry, "git", r)
    return r


@pytest.fixture
def cli(monkeypatch, rec, tmp_path):
    cfg = _cfg()
    monkeypatch.setattr(foundry, "load_config", lambda *a, **kw: cfg)
    path = str(tmp_path / "config.json")

    def run(*extra):
        return foundry.main(["changelog", "--config", path, *extra])
    return run


# ---- EB1 -------------------------------------------------------------------

@pytest.mark.parametrize("text,want", [
    ("7d", "2026-11-05"), ("0d", "2026-11-12"), ("30d", "2026-10-13"),
    ("2026-11-05", "2026-11-05"), ("2020-02-29", "2020-02-29"),
])
def test_b1_parse_since_values(text, want):
    assert foundry.parse_since(text, today=TODAY) == want


def test_b1_iso_date_ignores_today():
    for today in (dt.date(1999, 1, 1), dt.date(2030, 6, 6), None):
        assert foundry.parse_since("2026-11-05", today=today) == "2026-11-05"


def test_b1_today_none_uses_real_today():
    want = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    assert foundry.parse_since("7d") == want
    assert foundry.parse_since("0d", today=None) == dt.date.today().isoformat()


def test_b1_returns_str():
    assert isinstance(foundry.parse_since("3d", today=TODAY), str)


# ---- EB2 -------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "-3d", "garbage", "", "7", "d", "2026-13-01", "2026-11-5",
    "7D", "7 d", " 7d", "7days", "\uff17d", "2026-02-30", "26-11-05",
])
def test_b2_parse_since_rejects(bad):
    with pytest.raises(ValueError):
        foundry.parse_since(bad, today=TODAY)


# ---- EB3 -------------------------------------------------------------------

def test_b3_default_argv_unchanged(rec):
    foundry.gather_changelog(_cfg())
    foundry.gather_changelog(_cfg(), 2)
    foundry.gather_changelog(_cfg(), None)
    assert rec.calls == [BASE_ARGV] * 3


# ---- EB4 -------------------------------------------------------------------

def test_b4_since_appends_one_trailing_item(rec):
    foundry.gather_changelog(_cfg(), None, since="2026-11-05")
    assert rec.calls == [BASE_ARGV + ("--since=2026-11-05 00:00:00",)]


def test_b4_since_keeps_parsing_order_and_limit(rec):
    s = foundry.gather_changelog(_cfg(), 2, since="2026-11-05")
    assert len(rec.calls) == 1
    assert [e.iter_num for e in s.entries] == [42, 41]
    assert [e.prefix for e in s.entries] == ["feat", "fix"]
    full = foundry.gather_changelog(_cfg(), None, since="2026-11-05")
    assert [e.iter_num for e in full.entries] == [42, 41, 40]


# ---- EB5 -------------------------------------------------------------------

def test_b5_cli_forwards_since_keyword(monkeypatch, capsys):
    seen = []

    def fake(cfg, limit=None, **kw):
        seen.append((limit, kw))
        return foundry.summarize_changelog(entries=(), product="t")
    monkeypatch.setattr(foundry, "gather_changelog", fake)
    foundry.changelog_cli(_cfg(), limit=3, since="2026-11-05")
    assert seen and seen[-1][0] == 3
    assert seen[-1][1].get("since") == "2026-11-05"


def test_b5_cli_without_since_exit_codes(rec, capsys):
    assert foundry.changelog_cli(_cfg()) == 0
    out = capsys.readouterr().out
    assert "iter-42" in out and "add widget" in out
    rec.out = ""
    assert foundry.changelog_cli(_cfg()) == 2
    assert foundry.changelog_cli(_cfg(), as_json=True) == 2
    assert all("--since" not in " ".join(c) for c in rec.calls)


def test_b5_cli_without_since_output_matches_gather(rec, capsys):
    want = foundry.gather_changelog(_cfg()).render()
    foundry.changelog_cli(_cfg())
    assert want.strip() in capsys.readouterr().out


# ---- EB6 -------------------------------------------------------------------

def test_b6_main_iso_since(cli, rec, capsys):
    code = cli("--since", "2026-11-05")
    assert code == 0
    assert rec.calls[-1][-1] == "--since=2026-11-05 00:00:00"
    assert rec.calls[-1][:-1] == BASE_ARGV
    out = capsys.readouterr().out
    for word in ("add widget", "repair thing", "describe thing"):
        assert word in out
    assert "untagged" not in out


def test_b6_main_relative_since(cli, rec):
    cli("--since", "7d")
    want = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    assert rec.calls[-1][-1] == f"--since={want} 00:00:00"


def test_b6_main_no_since(cli, rec):
    cli()
    assert rec.calls == [BASE_ARGV]


def test_b6_main_since_empty_exit_2(cli, rec):
    rec.out = ""
    assert cli("--since", "2026-11-05") == 2


# ---- EB7 -------------------------------------------------------------------

@pytest.mark.parametrize("argv", [
    ("--since", "garbage"), ("--since=-3d",), ("--since", "-3d"),
    ("--since", "2026-13-01"),
])
def test_b7_bad_since_exits_2(cli, rec, capsys, argv):
    with pytest.raises(SystemExit) as ei:
        cli(*argv)
    assert ei.value.code == 2
    assert "--since" in capsys.readouterr().err
    assert rec.calls == []


# ---- EB8 -------------------------------------------------------------------

def test_b8_json_with_since_and_limit(cli, rec, capsys):
    code = cli("--since", "2026-11-05", "--limit", "2", "--json")
    assert code == 0
    doc = json.loads(capsys.readouterr().out)
    assert set(doc) == {"product", "total", "exit_code", "entries"}
    assert doc["total"] == 2 and len(doc["entries"]) == 2
    for e in doc["entries"]:
        assert set(e) == {"iter", "prefix", "subject"}
    assert "since" not in json.dumps(doc)
    assert rec.calls[-1][-1] == "--since=2026-11-05 00:00:00"


def test_b8_json_without_since_same_keys(cli, capsys):
    cli("--json")
    doc = json.loads(capsys.readouterr().out)
    assert set(doc) == {"product", "total", "exit_code", "entries"}


# ---- EB9 -------------------------------------------------------------------

def _readme():
    import pathlib
    return (pathlib.Path(foundry.__file__).resolve().parent / "README.md").read_text()


def test_b9_readme_usage_line_mentions_since():
    lines = [ln for ln in _readme().splitlines()
             if "foundry.py changelog --config" in ln]
    assert lines, "README #63 usage line missing"
    ln = lines[0]
    assert "--since" in ln and "Nd" in ln and "YYYY-MM-DD" in ln


def test_b9_help_names_both_forms(capsys):
    with pytest.raises(SystemExit):
        foundry.main(["changelog", "--help"])
    out = capsys.readouterr().out
    idx = out.index("--since")
    tail = out[idx:]
    assert "Nd" in tail and "YYYY-MM-DD" in tail
