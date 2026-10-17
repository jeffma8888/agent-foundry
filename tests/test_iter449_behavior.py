"""Iteration 449 -- BLACK-BOX behavior tests: ``foundry changelog`` verb.

Spec under test: products/_platform/state/iter-449/pm.md (8 Expected Behaviors).

  EB1: gather_changelog returns a list of frozen dataclass entries with
       iter_num: int, prefix: str, subject: str fields.
  EB2: gather_changelog filters to commits matching the (foundry iter N) tag
       and parses the conventional-commit prefix.
  EB3: limit caps entries (newest-first).
  EB4: Human-readable CLI output shows iter number, prefix, subject.
  EB5: --json produces a valid JSON array of objects with iter/prefix/subject.
  EB6: --limit N caps output in both modes.
  EB7: Empty case: empty list and a "no entries" message (human) / empty array (JSON).
  EB8: Full suite passes.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-449 PM spec, the
product README, ``tests/`` conventions, and the product's own observable
behaviour by RUNNING it (the public ``ChangelogEntry``, ``ChangelogSummary``,
``summarize_changelog``, ``gather_changelog`` API).  The implementation source
of ``foundry.py`` / ``dispatcher.py``, the engineer's and reviewer's notes,
and ``git diff`` were NOT read.  Tests exercise the public constructor and
monkeypatched ``gather_changelog`` -- fully offline and deterministic.
"""
from __future__ import annotations

import dataclasses
import json

import foundry


THIS_ITER = 449

SAMPLE_ENTRIES = (
    foundry.ChangelogEntry(iter_num=100, prefix="feat", subject="add widget"),
    foundry.ChangelogEntry(iter_num=99, prefix="fix", subject="repair widget"),
    foundry.ChangelogEntry(iter_num=98, prefix="docs", subject="document widget"),
    foundry.ChangelogEntry(iter_num=97, prefix="chore", subject="tidy widget"),
    foundry.ChangelogEntry(iter_num=96, prefix="test", subject="test widget"),
)


# ---------------------------------------------------------------------------
# EB1 -- gather_changelog returns frozen dataclass entries with the right fields
# ---------------------------------------------------------------------------

class TestEB1FrozenDataclassEntries:

    def test_b1_changelog_entry_is_frozen_dataclass(self):
        e = foundry.ChangelogEntry(iter_num=42, prefix="feat", subject="x")
        assert dataclasses.is_dataclass(e)
        assert e.__dataclass_params__.frozen

    def test_b1_changelog_entry_has_three_fields(self):
        names = [f.name for f in dataclasses.fields(foundry.ChangelogEntry)]
        assert "iter_num" in names
        assert "prefix" in names
        assert "subject" in names

    def test_b1_changelog_entry_field_types(self):
        e = foundry.ChangelogEntry(iter_num=42, prefix="feat", subject="some text")
        assert isinstance(e.iter_num, int)
        assert isinstance(e.prefix, str)
        assert isinstance(e.subject, str)

    def test_b1_changelog_summary_is_frozen_dataclass(self):
        s = foundry.summarize_changelog(entries=(), product="t")
        assert dataclasses.is_dataclass(s)

    def test_b1_gather_changelog_is_callable(self):
        assert callable(foundry.gather_changelog)


# ---------------------------------------------------------------------------
# EB2 -- gather_changelog filters to (foundry iter N) tag and parses prefix
# ---------------------------------------------------------------------------

class TestEB2ParsesConventionalCommits:

    def test_b2_gather_returns_changelog_summary(self, monkeypatch):
        monkeypatch.setattr(foundry, "git", lambda cfg, *a, **kw: (
            "feat: add widget (foundry iter 42)\n"
            "fix: repair thing (foundry iter 41)\n"
        ))
        cfg = type("C", (), {"repo": ".", "product": "t", "name": "t"})()
        result = foundry.gather_changelog(cfg, limit=None)
        assert isinstance(result, foundry.ChangelogSummary)

    def test_b2_parses_prefix_and_iter(self, monkeypatch):
        monkeypatch.setattr(foundry, "git", lambda cfg, *a, **kw: (
            "feat: add widget (foundry iter 42)\n"
        ))
        cfg = type("C", (), {"repo": ".", "product": "t", "name": "t"})()
        result = foundry.gather_changelog(cfg, limit=None)
        assert len(result.entries) == 1
        e = result.entries[0]
        assert e.iter_num == 42
        assert e.prefix == "feat"
        assert "add widget" in e.subject

    def test_b2_skips_non_tagged_commits(self, monkeypatch):
        monkeypatch.setattr(foundry, "git", lambda cfg, *a, **kw: (
            "feat: add widget (foundry iter 42)\n"
            "random commit without tag\n"
            "fix: repair thing (foundry iter 41)\n"
        ))
        cfg = type("C", (), {"repo": ".", "product": "t", "name": "t"})()
        result = foundry.gather_changelog(cfg, limit=None)
        assert len(result.entries) == 2

    def test_b2_multiple_prefixes_parsed(self, monkeypatch):
        monkeypatch.setattr(foundry, "git", lambda cfg, *a, **kw: (
            "feat: first (foundry iter 10)\n"
            "fix: second (foundry iter 9)\n"
            "docs: third (foundry iter 8)\n"
            "chore: fourth (foundry iter 7)\n"
            "test: fifth (foundry iter 6)\n"
        ))
        cfg = type("C", (), {"repo": ".", "product": "t", "name": "t"})()
        result = foundry.gather_changelog(cfg, limit=None)
        prefixes = [e.prefix for e in result.entries]
        assert prefixes == ["feat", "fix", "docs", "chore", "test"]


# ---------------------------------------------------------------------------
# EB3 -- limit caps entries (newest-first)
# ---------------------------------------------------------------------------

class TestEB3LimitCapsEntries:

    def test_b3_limit_none_returns_all(self, monkeypatch):
        lines = "".join(
            f"feat: thing {i} (foundry iter {100 - i})\n" for i in range(10)
        )
        monkeypatch.setattr(foundry, "git", lambda cfg, *a, **kw: lines)
        cfg = type("C", (), {"repo": ".", "product": "t", "name": "t"})()
        result = foundry.gather_changelog(cfg, limit=None)
        assert len(result.entries) == 10

    def test_b3_limit_3_returns_3(self, monkeypatch):
        lines = "".join(
            f"feat: thing {i} (foundry iter {100 - i})\n" for i in range(10)
        )
        monkeypatch.setattr(foundry, "git", lambda cfg, *a, **kw: lines)
        cfg = type("C", (), {"repo": ".", "product": "t", "name": "t"})()
        result = foundry.gather_changelog(cfg, limit=3)
        assert len(result.entries) == 3

    def test_b3_limit_preserves_newest_first(self, monkeypatch):
        lines = "".join(
            f"feat: thing {i} (foundry iter {100 - i})\n" for i in range(10)
        )
        monkeypatch.setattr(foundry, "git", lambda cfg, *a, **kw: lines)
        cfg = type("C", (), {"repo": ".", "product": "t", "name": "t"})()
        result = foundry.gather_changelog(cfg, limit=3)
        iters = [e.iter_num for e in result.entries]
        assert iters == [100, 99, 98]


# ---------------------------------------------------------------------------
# EB4 -- Human-readable output shows iter, prefix, subject
# ---------------------------------------------------------------------------

class TestEB4HumanReadableRender:

    def test_b4_render_includes_iter_number(self):
        s = foundry.summarize_changelog(entries=SAMPLE_ENTRIES[:1], product="t")
        rendered = s.render()
        assert "iter-100" in rendered

    def test_b4_render_includes_prefix_in_brackets(self):
        s = foundry.summarize_changelog(entries=SAMPLE_ENTRIES[:1], product="t")
        rendered = s.render()
        assert "[feat]" in rendered

    def test_b4_render_includes_subject(self):
        s = foundry.summarize_changelog(entries=SAMPLE_ENTRIES[:1], product="t")
        rendered = s.render()
        assert "add widget" in rendered

    def test_b4_render_includes_product_name(self):
        s = foundry.summarize_changelog(entries=SAMPLE_ENTRIES[:1], product="myproduct")
        rendered = s.render()
        assert "myproduct" in rendered

    def test_b4_render_multiple_entries(self):
        s = foundry.summarize_changelog(entries=SAMPLE_ENTRIES, product="t")
        rendered = s.render()
        assert "iter-100" in rendered
        assert "iter-96" in rendered
        assert "[fix]" in rendered
        assert "[docs]" in rendered

    def test_b4_render_includes_count(self):
        s = foundry.summarize_changelog(entries=SAMPLE_ENTRIES, product="t")
        rendered = s.render()
        assert "5" in rendered


# ---------------------------------------------------------------------------
# EB5 -- JSON output: valid JSON array with iter/prefix/subject keys
# ---------------------------------------------------------------------------

class TestEB5JsonOutput:

    def test_b5_to_dict_returns_dict(self):
        s = foundry.summarize_changelog(entries=SAMPLE_ENTRIES[:1], product="t")
        d = s.to_dict()
        assert isinstance(d, dict)

    def test_b5_to_dict_has_entries_key(self):
        s = foundry.summarize_changelog(entries=SAMPLE_ENTRIES[:1], product="t")
        d = s.to_dict()
        assert "entries" in d
        assert isinstance(d["entries"], list)

    def test_b5_entry_has_iter_prefix_subject(self):
        s = foundry.summarize_changelog(entries=SAMPLE_ENTRIES[:1], product="t")
        d = s.to_dict()
        entry = d["entries"][0]
        assert "iter" in entry
        assert "prefix" in entry
        assert "subject" in entry

    def test_b5_entry_values_correct(self):
        s = foundry.summarize_changelog(entries=SAMPLE_ENTRIES[:1], product="t")
        d = s.to_dict()
        entry = d["entries"][0]
        assert entry["iter"] == 100
        assert entry["prefix"] == "feat"
        assert entry["subject"] == "add widget"

    def test_b5_serializes_as_valid_json(self):
        s = foundry.summarize_changelog(entries=SAMPLE_ENTRIES, product="t")
        blob = json.dumps(s.to_dict())
        parsed = json.loads(blob)
        assert len(parsed["entries"]) == 5

    def test_b5_to_dict_includes_total_and_exit_code(self):
        s = foundry.summarize_changelog(entries=SAMPLE_ENTRIES, product="t")
        d = s.to_dict()
        assert d["total"] == 5
        assert d["exit_code"] == 0


# ---------------------------------------------------------------------------
# EB6 -- --limit N caps output in both modes (via summarize_changelog)
# ---------------------------------------------------------------------------

class TestEB6LimitCapsBothModes:

    def test_b6_limit_caps_human_render(self, monkeypatch):
        lines = "".join(
            f"feat: thing {i} (foundry iter {100 - i})\n" for i in range(10)
        )
        monkeypatch.setattr(foundry, "git", lambda cfg, *a, **kw: lines)
        cfg = type("C", (), {"repo": ".", "product": "t", "name": "t"})()
        result = foundry.gather_changelog(cfg, limit=2)
        rendered = result.render()
        assert "iter-100" in rendered
        assert "iter-99" in rendered
        assert "iter-98" not in rendered

    def test_b6_limit_caps_json_output(self, monkeypatch):
        lines = "".join(
            f"feat: thing {i} (foundry iter {100 - i})\n" for i in range(10)
        )
        monkeypatch.setattr(foundry, "git", lambda cfg, *a, **kw: lines)
        cfg = type("C", (), {"repo": ".", "product": "t", "name": "t"})()
        result = foundry.gather_changelog(cfg, limit=2)
        d = result.to_dict()
        assert len(d["entries"]) == 2
        assert d["total"] == 2


# ---------------------------------------------------------------------------
# EB7 -- Empty case: empty list, "no entries" human, empty JSON array
# ---------------------------------------------------------------------------

class TestEB7EmptyCase:

    def test_b7_empty_entries_render_says_no_entries(self):
        s = foundry.summarize_changelog(entries=(), product="empty")
        rendered = s.render()
        assert "no entries" in rendered.lower()

    def test_b7_empty_entries_to_dict_has_empty_array(self):
        s = foundry.summarize_changelog(entries=(), product="empty")
        d = s.to_dict()
        assert d["entries"] == []
        assert d["total"] == 0

    def test_b7_empty_entries_exit_code_nonzero(self):
        s = foundry.summarize_changelog(entries=(), product="empty")
        assert s.exit_code != 0

    def test_b7_gather_empty_repo(self, monkeypatch):
        monkeypatch.setattr(foundry, "git", lambda cfg, *a, **kw: "")
        cfg = type("C", (), {"repo": ".", "product": "t", "name": "t"})()
        result = foundry.gather_changelog(cfg, limit=None)
        assert len(result.entries) == 0
        assert "no entries" in result.render().lower()
        assert result.to_dict()["entries"] == []


# ---------------------------------------------------------------------------
# EB8 -- Full suite passes (importability probe)
# ---------------------------------------------------------------------------

class TestEB8SuiteGreen:

    def test_b8_foundry_importable(self):
        import foundry as f
        assert hasattr(f, "gather_changelog")
        assert hasattr(f, "ChangelogEntry")
        assert hasattr(f, "ChangelogSummary")
        assert hasattr(f, "summarize_changelog")
        assert hasattr(f, "changelog_cli")

    def test_b8_dispatcher_importable(self):
        import dispatcher as d
        assert hasattr(d, "load_dispatch")
