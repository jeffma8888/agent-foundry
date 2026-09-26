"""Behavior tests for iteration 414: `foundry directions --topic TERM`.

The topic surface is a SIBLING of the pinned `directions_cli` (whose signature and
one-statement body `tests/test_iter165_behavior.py` b06/b09 freeze), so:

  * `filter_directions(digest, term)`, `archive_topic_hits(text, term)` and
    `render_topic_report(digest, hits, term)` are PURE (no I/O);
  * `read_roadmap_archive(cfg)` is the ONLY new I/O seam and never raises;
  * `directions_topic_cli(cfg, topic, limit=None, as_json=False) -> int` is the
    printer, and `main` routes `--topic` to it BEFORE the untouched old verb.

Every fixture lives under `tmp_path`; the git seam behind `gather_directions` is
scripted to `()` so no subprocess runs.
"""
import dataclasses
import inspect
import io
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402

EMDASH = "\u2014"


# ------------------------------------------------------------------ fixtures


def _write_cfg(tmp_path, **over):
    tmp_path = pathlib.Path(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _iter_dir(cfg, iteration):
    return pathlib.Path(cfg.state) / f"iter-{iteration:02d}"


def _snapshot_tree(root):
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def _write_scouted(cfg, iteration, cands, winner):
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    body = [f"# PM_SCOUT_A {EMDASH} iteration {iteration} {EMDASH} lens: dx", "", "## Slate"]
    body += [f"## Candidate {c}" for c in cands]
    (d / "pm_scout_a.md").write_text("\n".join(body) + "\n")
    (d / "pm.md").write_text(f"# PM spec\n\n## Triage\nPICK: **{winner}**\n\n## Feature\nx\n")
    return d


def _entry(iteration, cands, winner="A1"):
    return foundry.DirectionsEntry(iteration=iteration, lenses=("dx",), candidates=tuple(cands),
                                   winner=winner, action=None, sha=None)


def _digest():
    return foundry.DirectionsDigest(product="demoprod", entries=(
        _entry(9, ("A1 -- foundry salvage census", "B1 -- doctor line")),
        _entry(8, ("A1 -- resume verb",)),
        _entry(7, ("B1 -- Salvage preserved patches",)),
    ), ship_subjects=("iter 9 -- x",))


def _capture(fn):
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        try:
            rc = fn()
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 2
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


@pytest.fixture
def product(tmp_path, monkeypatch):
    """A tmp product with ONE scouted iter-07 (A1 -- foundry salvage), a roadmap
    path and a sibling archive holding `- **iter 3 -- resume verb.**`."""
    monkeypatch.setattr(foundry, "git_ship_subjects", lambda repo: ())
    roadmap = tmp_path / "PLATFORM_ROADMAP.md"
    roadmap.write_text("# roadmap\n")
    (tmp_path / "PLATFORM_ROADMAP_ARCHIVE.md").write_text("- **iter 3 -- resume verb.**\n")
    cfg = foundry.load_config(str(_write_cfg(tmp_path, roadmap=str(roadmap))))
    _write_scouted(cfg, 7, ("A1 -- foundry salvage",), "A1")
    return cfg


# ------------------------------------------- 1. old verb is byte-untouched


def test_b01_directions_cli_signature_and_body_unchanged_and_main_routes_without_topic(tmp_path, monkeypatch):
    assert tuple(inspect.signature(foundry.directions_cli).parameters) == ("cfg", "limit", "as_json")
    monkeypatch.setattr(foundry, "git_ship_subjects", lambda repo: ())
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    rc, out, _ = _capture(lambda: foundry.directions_cli(cfg))
    assert rc == 2 and "no scouted iterations yet" in out
    _write_scouted(cfg, 7, ("A1 -- foundry salvage",), "A1")
    rc, out, _ = _capture(lambda: foundry.directions_cli(cfg))
    assert rc == 0 and "iter-07" in out

    calls = []
    monkeypatch.setattr(foundry, "directions_cli",
                        lambda c, limit=None, as_json=False: calls.append(("old", limit, as_json)) or 0)
    monkeypatch.setattr(foundry, "directions_topic_cli",
                        lambda c, topic, limit=None, as_json=False: calls.append(("topic", topic, limit, as_json)) or 0)
    rc, _, _ = _capture(lambda: foundry.main(["directions", "--config", str(tmp_path / "config.json")]))
    assert rc == 0 and calls == [("old", None, False)]
    rc, _, _ = _capture(lambda: foundry.main(
        ["directions", "--config", str(tmp_path / "config.json"), "--topic", "salvage", "--limit", "3", "--json"]))
    assert rc == 0 and calls == [("old", None, False), ("topic", "salvage", 3, True)]


# ------------------------------------------------------- 2/3. pure filter


def test_b02_filter_keeps_iterations_whose_candidates_contain_term_case_insensitively():
    d = _digest()
    fd = foundry.filter_directions(d, "SALVAGE")
    assert fd.entries == (d.entries[0], d.entries[2])
    assert fd.ship_subjects == d.ship_subjects
    assert fd.total == 2 and fd.exit_code == 0
    assert fd.product == d.product
    assert d.entries == _digest().entries  # input untouched


def test_b03_filter_is_total_and_never_matches_winner_or_lens():
    d = _digest()
    assert foundry.filter_directions(d, "").entries == d.entries
    bare = foundry.DirectionsDigest(product="p", entries=(_entry(5, ()), _entry(4, ("A1 -- x",))))
    for term in ("", "x", "A1"):
        assert all(e.candidates for e in foundry.filter_directions(bare, term).entries), term
    assert foundry.filter_directions(bare, "").entries == (bare.entries[1],)
    winner_only = foundry.DirectionsDigest(product="p", entries=(_entry(6, ("A1 -- nothing",), winner="B1"),))
    assert foundry.filter_directions(winner_only, "B1").entries == ()
    assert foundry.filter_directions(winner_only, "dx").entries == ()  # lens never matches
    assert foundry.filter_directions(foundry.DirectionsDigest(product="p", entries=()), "x").exit_code == 2


# ------------------------------------------------------ 4. archive hits


def test_b04_archive_hits_are_matching_record_bullets_in_file_order_cut_to_120():
    long_line = "- **iter 168 -- Salvage AGAIN " + "x" * 200 + "**"
    text = ("- **iter 161 -- foundry salvage: census.**\n"
            "- **iter 215 -- recoverable: git apply --check.**\n"
            "prose mentioning salvage\n" + long_line + "\n")
    hits = foundry.archive_topic_hits(text, "salvage")
    assert hits == ((161, "- **iter 161 -- foundry salvage: census.**"), (168, long_line.strip()[:120]))
    assert len(hits[1][1]) == 120
    assert foundry.archive_topic_hits("", "x") == ()
    assert [h[0] for h in foundry.archive_topic_hits(text, "")] == [161, 215, 168]
    assert isinstance(hits, tuple)


# ------------------------------------------------------- 5. archive seam


def test_b05_read_roadmap_archive_degrades_to_empty_and_derives_sibling_from_stem(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    assert cfg.roadmap == "" and foundry.read_roadmap_archive(cfg) == ""
    roadmap = tmp_path / "PLATFORM_ROADMAP.md"
    cfg2 = foundry.load_config(str(_write_cfg(tmp_path, roadmap=str(roadmap))))
    assert foundry.read_roadmap_archive(cfg2) == ""  # sibling missing
    (tmp_path / "PLATFORM_ROADMAP_ARCHIVE.md").mkdir()
    assert foundry.read_roadmap_archive(cfg2) == ""  # sibling is a directory
    (tmp_path / "PLATFORM_ROADMAP_ARCHIVE.md").rmdir()
    (tmp_path / "PLATFORM_ROADMAP_ARCHIVE.md").write_text("- **iter 1 -- a.**\nbody\n")
    assert foundry.read_roadmap_archive(cfg2) == "- **iter 1 -- a.**\nbody\n"
    other = tmp_path / "ROADMAP.md"
    cfg3 = foundry.load_config(str(_write_cfg(tmp_path, roadmap=str(other))))
    (tmp_path / "ROADMAP_ARCHIVE.md").write_text("Z\n")
    assert foundry.read_roadmap_archive(cfg3) == "Z\n"


# ------------------------------------------------------------ 6. report


def test_b06_report_is_topic_line_then_digest_then_archive_block():
    fd = foundry.filter_directions(_digest(), "salvage")
    hits = ((161, "- **iter 161 -- foundry salvage: census.**"),)
    rep = foundry.render_topic_report(fd, hits, "salvage")
    lines = rep.split("\n")
    assert lines[0] == 'topic: "salvage" -- 2 scouted iteration(s), 1 archive bullet(s)'
    assert "\n\n" + fd.render() + "\n" in rep
    assert rep.endswith("\narchive:\n- iter 161 -- foundry salvage: census.**\n")
    assert not rep.endswith("\n\n")

    empty = foundry.DirectionsDigest(product="demoprod", entries=())
    rep0 = foundry.render_topic_report(empty, hits, "salvage")
    assert rep0.startswith('topic: "salvage" -- 0 scouted iteration(s), 1 archive bullet(s)\n')
    assert "no scouted iterations yet" not in rep0
    rep_none = foundry.render_topic_report(fd, (), "salvage")
    assert rep_none.endswith("\narchive: none\n") and "archive:\n" not in rep_none


# ------------------------------------------------ 7/8/9/10. the printer


def test_b07_topic_cli_exit_is_0_on_any_hit_and_2_on_none(product):
    rc, out, _ = _capture(lambda: foundry.directions_topic_cli(product, "salvage"))
    assert rc == 0
    assert out.split("\n")[0] == 'topic: "salvage" -- 1 scouted iteration(s), 0 archive bullet(s)'
    assert "iter-07" in out and "archive: none" in out
    rc, out, _ = _capture(lambda: foundry.directions_topic_cli(product, "resume"))
    assert rc == 0 and "0 scouted iteration(s), 1 archive bullet(s)" in out
    assert "- iter 3 -- resume verb.**" in out
    rc, out, _ = _capture(lambda: foundry.directions_topic_cli(product, "outages"))
    assert rc == 2 and "archive: none" in out


def test_b08_limit_composes_before_the_filter_via_one_bare_name_gather_call(product, monkeypatch):
    calls = []

    def scripted(cfg, limit):
        calls.append((cfg, limit))
        return _digest()

    monkeypatch.setattr(foundry, "gather_directions", scripted)
    rc, out, _ = _capture(lambda: foundry.directions_topic_cli(product, "salvage", limit=5))
    assert rc == 0 and calls == [(product, 5)]
    assert "iter-09" in out and "iter-07" in out and "iter-08" not in out


def test_b09_json_with_topic_is_one_document(product):
    rc, out, _ = _capture(lambda: foundry.directions_topic_cli(product, "salvage", as_json=True))
    doc = json.loads(out)
    assert rc == 0 and set(doc) == {"topic", "directions", "archive"}
    assert doc["topic"] == "salvage"
    expected = foundry.filter_directions(foundry.gather_directions(product, None), "salvage").to_dict()
    assert doc["directions"] == expected and doc["archive"] == []
    rc, out, _ = _capture(lambda: foundry.directions_topic_cli(product, "resume", as_json=True))
    assert rc == 0 and json.loads(out)["archive"] == [{"iteration": 3, "text": "- **iter 3 -- resume verb.**"}]
    rc, out, _ = _capture(lambda: foundry.directions_topic_cli(product, "outages", as_json=True))
    assert rc == 2 and json.loads(out)["directions"]["total"] == 0


def test_b10_topic_cli_is_read_only(product, tmp_path):
    before = _snapshot_tree(tmp_path)
    for term, js in (("salvage", False), ("resume", True), ("outages", False)):
        _capture(lambda: foundry.directions_topic_cli(product, term, as_json=js))
    foundry.read_roadmap_archive(product)
    foundry.filter_directions(_digest(), "x")
    assert _snapshot_tree(tmp_path) == before


# ---------------------------------------------------------- 11. CLI wiring


def test_b11_directions_help_lists_topic_and_the_verb_list_is_unchanged():
    rc, out, _ = _capture(lambda: foundry.main(["directions", "--help"]))
    assert rc == 0 and "--topic TERM" in out
    rc, top, _ = _capture(lambda: foundry.main(["--help"]))
    assert rc == 0 and "topic" not in top.replace("--topic", "")
    assert set(dataclasses.asdict(foundry.DirectionsDigest(product="p", entries=()))) == {
        "product", "entries", "ship_subjects"}
    assert inspect.signature(foundry.directions_topic_cli).parameters["limit"].default is None
    assert inspect.signature(foundry.directions_topic_cli).parameters["as_json"].default is False


# =========================================================================== #
# TESTER-derived section (isolated seat, iteration 414).  Everything below was
# re-derived from the spec's Expected Behaviors 1-12 and drives the PUBLIC
# interface -- `foundry.main(["directions", ..., "--topic", TERM])` -- so it
# does not depend on the sibling printer's name.  Provenance: the eleven tests
# above were inherited from the fix pass; these are independent.
# =========================================================================== #

import re  # noqa: E402

import dispatcher  # noqa: E402,F401  (Behavior 11: both modules import)

_HERE = pathlib.Path(__file__).resolve().parents[1]
_ROADMAP = _HERE / "PLATFORM_ROADMAP.md"
_ARCHIVE = _HERE / "PLATFORM_ROADMAP_ARCHIVE.md"
THIS_ITER = 414


@pytest.fixture
def product2(tmp_path, monkeypatch):
    """Tmp product for the CLI path: ONE scouted iter-07 (candidate `A1 --
    foundry salvage`) and a sibling archive with TWO record bullets plus a
    prose line that names the term but is not a record."""
    monkeypatch.setattr(foundry, "git_ship_subjects", lambda repo: ())
    roadmap = tmp_path / "PLATFORM_ROADMAP.md"
    roadmap.write_text("# roadmap\n- iter 3 -- resume verb.\n")
    (tmp_path / "PLATFORM_ROADMAP_ARCHIVE.md").write_text(
        "- **iter 3 -- resume verb.**\n"
        "prose that says salvage but is not a record\n"
        "- **iter 5 -- Salvage twice.**\n")
    cfg_path = _write_cfg(tmp_path, roadmap=str(roadmap))
    cfg = foundry.load_config(str(cfg_path))
    _write_scouted(cfg, 7, ("A1 -- foundry salvage",), "A1")
    return cfg, cfg_path


def _main(cfg_path, *extra):
    return _capture(lambda: foundry.main(["directions", "--config", str(cfg_path), *extra]))


# ----------------------------------------------------- 7. exit codes via main


def test_t07_main_topic_exit_0_on_scouted_hit_0_on_archive_only_hit_2_on_none(product2):
    cfg, cfg_path = product2
    rc, out, err = _main(cfg_path, "--topic", "salvage")
    assert rc == 0 and err == "", (rc, err)
    lines = out.split("\n")
    assert lines[0] == 'topic: "salvage" -- 1 scouted iteration(s), 1 archive bullet(s)'
    assert "iter-07" in out and "foundry salvage" in out
    assert out.endswith("\narchive:\n- iter 5 -- Salvage twice.**\n")
    assert "prose that says salvage" not in out  # only record bullets are hits
    assert "- iter 3 --" not in out  # a non-matching record is not a hit

    rc, out, _ = _main(cfg_path, "--topic", "RESUME")  # term case never matters
    assert rc == 0
    assert out.split("\n")[0] == 'topic: "RESUME" -- 0 scouted iteration(s), 1 archive bullet(s)'
    assert "no scouted iterations yet" not in out and "iter-07" not in out
    assert out.endswith("\narchive:\n- iter 3 -- resume verb.**\n")

    rc, out, _ = _main(cfg_path, "--topic", "outages")
    assert rc == 2
    assert out.split("\n")[0] == 'topic: "outages" -- 0 scouted iteration(s), 0 archive bullet(s)'
    assert [ln for ln in out.split("\n") if ln.strip()] == [
        'topic: "outages" -- 0 scouted iteration(s), 0 archive bullet(s)', "archive: none"]


def test_t07_archive_seam_is_called_by_bare_name_from_the_cli_path(product2, monkeypatch):
    cfg, cfg_path = product2
    seen = []

    def scripted_archive(c):
        seen.append(c.name)
        return "- **iter 77 -- outages verb shipped.**\n"

    monkeypatch.setattr(foundry, "read_roadmap_archive", scripted_archive)
    rc, out, _ = _main(cfg_path, "--topic", "outages")
    assert rc == 0 and seen == ["demoprod"]
    assert out.split("\n")[0] == 'topic: "outages" -- 0 scouted iteration(s), 1 archive bullet(s)'
    assert out.endswith("\narchive:\n- iter 77 -- outages verb shipped.**\n")


# ---------------------------------------------- 8. --limit before the filter


def test_t08_main_limit_is_passed_to_one_gather_call_and_filter_runs_after(product2, monkeypatch):
    cfg, cfg_path = product2
    calls = []

    def scripted(c, limit):
        calls.append((c.name, limit))
        return _digest()

    monkeypatch.setattr(foundry, "gather_directions", scripted)
    rc, out, _ = _main(cfg_path, "--limit", "5", "--topic", "salvage")
    assert rc == 0 and calls == [("demoprod", 5)]
    assert out.split("\n")[0] == 'topic: "salvage" -- 2 scouted iteration(s), 1 archive bullet(s)'
    assert "iter-09" in out and "iter-07" in out and "iter-08" not in out
    assert out.index("iter-09") < out.index("iter-07")  # digest order preserved


# ------------------------------------------------ 9. --json --topic via main


def test_t09_main_json_topic_is_one_document_with_three_keys(product2):
    cfg, cfg_path = product2
    rc, out, err = _main(cfg_path, "--topic", "salvage", "--json")
    assert rc == 0 and err == ""
    doc = json.loads(out)  # exactly one document, nothing else on stdout
    assert list(doc) == ["topic", "directions", "archive"] or set(doc) == {"topic", "directions", "archive"}
    assert doc["topic"] == "salvage"
    expected = foundry.filter_directions(foundry.gather_directions(cfg, None), "salvage").to_dict()
    assert doc["directions"] == expected
    assert doc["directions"]["total"] == 1 and doc["directions"]["exit_code"] == 0
    assert doc["archive"] == [{"iteration": 5, "text": "- **iter 5 -- Salvage twice.**"}]

    rc, out, _ = _main(cfg_path, "--topic", "e", "--json")  # matches both bullets
    assert rc == 0
    assert json.loads(out)["archive"] == [
        {"iteration": 3, "text": "- **iter 3 -- resume verb.**"},
        {"iteration": 5, "text": "- **iter 5 -- Salvage twice.**"}]

    rc, out, _ = _main(cfg_path, "--topic", "outages", "--json")
    doc = json.loads(out)
    assert rc == 2 and doc["archive"] == [] and doc["directions"]["entries"] == []
    assert doc["directions"]["exit_code"] == 2


def test_t09_json_without_topic_is_the_plain_digest_document(product2):
    cfg, cfg_path = product2
    rc, out, _ = _main(cfg_path, "--json")
    doc = json.loads(out)
    assert rc == 0 and "topic" not in doc and "archive" not in doc
    assert doc == foundry.gather_directions(cfg, None).to_dict()


# ------------------------------------------------------------ 10. read-only


def test_t10_cli_path_never_writes_under_the_product(product2, tmp_path):
    cfg, cfg_path = product2
    before = _snapshot_tree(tmp_path)
    for args in (("--topic", "salvage"), ("--topic", "resume", "--json"),
                 ("--topic", "outages"), ("--topic", "", "--json"), ("--limit", "1", "--topic", "x")):
        _main(cfg_path, *args)
    assert _snapshot_tree(tmp_path) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        ["PLATFORM_ROADMAP.md", "PLATFORM_ROADMAP_ARCHIVE.md", "config.json", "repo", "work"])


# ------------------------------------------------------- 6. report shape


def test_t06_report_exact_layout_with_two_hits_and_all_three_degenerate_forms():
    fd = foundry.filter_directions(_digest(), "salvage")
    assert fd.total == 2
    hits = ((161, "- **iter 161 -- foundry salvage: census.**"),
            (170, "- **iter 170 -- Salvage AGAIN**"))  # 170: not in iter228's COMPACTED_ITERS census
    rep = foundry.render_topic_report(fd, hits, "salvage")
    topic_line = 'topic: "salvage" -- 2 scouted iteration(s), 2 archive bullet(s)'
    assert rep.startswith(topic_line + "\n\n" + fd.render() + "\n")
    assert rep.endswith("\narchive:\n- iter 161 -- foundry salvage: census.**\n- iter 170 -- Salvage AGAIN**\n")
    assert rep.count("archive:") == 1 and "**iter" not in rep
    assert "\n\n\n" not in rep and not rep.endswith("\n\n")
    # the archive block is the tail: nothing follows the last hit line
    assert rep.split("archive:\n", 1)[1] == "- iter 161 -- foundry salvage: census.**\n- iter 170 -- Salvage AGAIN**\n"

    empty = foundry.DirectionsDigest(product="demoprod", entries=())
    both_empty = foundry.render_topic_report(empty, (), "zz")
    assert [ln for ln in both_empty.split("\n") if ln.strip()] == [
        'topic: "zz" -- 0 scouted iteration(s), 0 archive bullet(s)', "archive: none"]
    assert both_empty.endswith("\n") and not both_empty.endswith("\n\n")
    assert "no scouted iterations yet" not in both_empty and "demoprod" not in both_empty

    digest_only = foundry.render_topic_report(fd, (), "salvage")
    assert digest_only.startswith('topic: "salvage" -- 2 scouted iteration(s), 0 archive bullet(s)\n\n' + fd.render() + "\n")
    assert digest_only.endswith("\narchive: none\n")

    archive_only = foundry.render_topic_report(empty, hits[:1], "salvage")
    assert archive_only.startswith('topic: "salvage" -- 0 scouted iteration(s), 1 archive bullet(s)\n')
    assert archive_only.endswith("\narchive:\n- iter 161 -- foundry salvage: census.**\n")
    assert "foundry directions" not in archive_only


# ------------------------------------------------ 2/3/4. pure-function edges


def test_t02_filter_uses_casefold_and_matches_any_candidate_position():
    d = foundry.DirectionsDigest(product="p", entries=(
        _entry(3, ("A1 -- Straße rule",)),
        _entry(2, ("A1 -- nothing", "B2 -- tail SALVAGE")),
        _entry(1, ("A1 -- salvag",)),
    ))
    assert foundry.filter_directions(d, "STRASSE").entries == (d.entries[0],)  # casefold, not lower
    assert foundry.filter_directions(d, "salvage").entries == (d.entries[1],)  # 2nd candidate counts
    assert foundry.filter_directions(d, "salvage").total == 1
    assert foundry.filter_directions(d, "SALVAGE").entries == foundry.filter_directions(d, "salvage").entries
    assert foundry.filter_directions(d, "zzz").entries == ()
    assert foundry.filter_directions(d, "zzz").exit_code == 2
    assert foundry.filter_directions(d, "zzz").product == "p"
    assert isinstance(foundry.filter_directions(d, "a").entries, tuple)


def test_t04_archive_hits_casefold_and_exact_120_boundary_and_non_record_lines():
    exactly = "- **iter 12 -- " + "s" * (120 - len("- **iter 12 -- ") - 2) + "**"
    assert len(exactly) == 120
    text = ("- **iter 12 -- Salvage a.**\n"
            "- iter 13 -- salvage plain bullet (not a record)\n"
            "  - **iter 14 -- salvage nested**\n"
            f"{exactly}\n"
            "## heading with salvage\n")
    hits = foundry.archive_topic_hits(text, "SALVAGE")
    assert hits[0] == (12, "- **iter 12 -- Salvage a.**")
    assert all(isinstance(i, int) for i, _ in hits)
    assert [i for i, _ in hits] == sorted(i for i, _ in hits) and 13 not in [i for i, _ in hits]
    s_hits = foundry.archive_topic_hits(text, "sss")
    assert s_hits == ((12, exactly),) and len(s_hits[0][1]) == 120
    assert foundry.archive_topic_hits("no records at all\n", "") == ()
    assert foundry.archive_topic_hits("- **iter 9 -- x.**", "x") == ((9, "- **iter 9 -- x.**"),)  # no trailing NL


# ----------------------------------------------------- 11. CLI wiring + 12


def test_t11_directions_help_names_topic_and_the_verb_set_gains_no_verb():
    rc, out, _ = _capture(lambda: foundry.main(["directions", "--help"]))
    assert rc == 0 and "--topic TERM" in out
    for old_flag in ("--config", "--limit", "--json"):
        assert old_flag in out, old_flag
    rc, top, _ = _capture(lambda: foundry.main(["--help"]))
    assert rc == 0
    m = re.search(r"\{([^}]*)\}", top.replace("\n", "").replace(" ", ""))
    assert m, top[:400]
    verbs = set(m.group(1).split(","))
    assert "directions" in verbs and not {v for v in verbs if "topic" in v}
    # the flag is a flag: `directions --topic` without --config is a usage error, not a verb
    rc, _, err = _capture(lambda: foundry.main(["directions", "--topic", "x"]))
    assert rc == 2 and "--config" in err


def test_t12_ledger_rows_for_this_iteration_are_in_tracked_text():
    idx, arc = _ROADMAP.read_text(encoding="utf-8"), _ARCHIVE.read_text(encoding="utf-8")
    assert foundry.roadmap_ledger_gaps(idx, arc, (THIS_ITER,)) == []
    rows = [ln for ln in idx.splitlines() if ln.startswith(f"- iter {THIS_ITER} ")]
    assert len(rows) == 1 and len(rows[0]) <= 120, rows
    assert "--topic" in rows[0]
    bullets = [ln for ln in arc.splitlines() if ln.startswith(f"- **iter {THIS_ITER} ")]
    assert len(bullets) == 1, len(bullets)
    # the verb's own reader agrees with the plain scan
    assert [i for i, _ in foundry.archive_topic_hits(arc, "--topic")] .count(THIS_ITER) == 1


# =========================================================================== #
# TESTER-RETRY section (attempt 2, isolated seat).  The killed round's tests
# above were treated as UNVERIFIED and re-run; everything below adds the angles
# they left open: the plain verb through `main` on a REAL tmp product (Behavior
# 1), `--limit` before the filter WITHOUT a scripted gather (Behavior 8), the
# archive seam when the sibling is absent or unreadable (Behavior 5), text/json
# agreement (Behaviors 7+9), plain-substring (no regex) matching, and the
# filtered digest as a first-class digest (Behavior 2).
# =========================================================================== #

import os  # noqa: E402


def _product3(tmp_path, monkeypatch, *, roadmap=None, archive_text=None, scouted=()):
    """Tmp product with the given scouted (iteration, candidates) pairs; the
    roadmap path is only set when asked, and the archive only written when given."""
    monkeypatch.setattr(foundry, "git_ship_subjects", lambda repo: ())
    over = {}
    if roadmap is not None:
        rm = tmp_path / roadmap
        rm.write_text("# roadmap\n")
        over["roadmap"] = str(rm)
        if archive_text is not None:
            (tmp_path / (rm.stem + "_ARCHIVE.md")).write_text(archive_text)
    cfg_path = _write_cfg(tmp_path, **over)
    cfg = foundry.load_config(str(cfg_path))
    for iteration, cands in scouted:
        _write_scouted(cfg, iteration, cands, "A1")
    return cfg, cfg_path


def _topic_line_counts(out):
    m = re.match(r'topic: "(.*)" -- (\d+) scouted iteration\(s\), (\d+) archive bullet\(s\)$',
                 out.split("\n")[0])
    assert m, out.split("\n")[0]
    return m.group(1), int(m.group(2)), int(m.group(3))


# ------------------------------------ 1. plain verb through main, real product


def test_r01_plain_directions_via_main_equals_directions_cli_and_carries_no_topic_tokens(product2, monkeypatch):
    cfg, cfg_path = product2
    for extra, kwargs in (((), {}), (("--limit", "1"), {"limit": 1}), (("--json",), {"as_json": True})):
        rc_main, out_main, err_main = _main(cfg_path, *extra)
        rc_cli, out_cli, err_cli = _capture(lambda: foundry.directions_cli(cfg, **kwargs))
        assert (rc_main, out_main, err_main) == (rc_cli, out_cli, err_cli), extra
        assert rc_main == 0 and out_main
        assert "topic:" not in out_main and "archive" not in out_main, extra
    # zero scouted iterations: the old sentinel and exit 2 survive untouched
    cfg_e, cfg_e_path = _product3(pathlib.Path(cfg_path).parent / "empty", monkeypatch)
    rc_main, out_main, _ = _main(cfg_e_path)
    rc_cli, out_cli, _ = _capture(lambda: foundry.directions_cli(cfg_e))
    assert (rc_main, out_main) == (rc_cli, out_cli) and rc_cli == 2
    assert "no scouted iterations yet" in out_cli and "topic:" not in out_cli


# --------------------------------- 8. --limit BEFORE the filter, unscripted


def test_r08_limit_is_applied_before_the_topic_filter_on_a_real_product(tmp_path, monkeypatch):
    cfg, cfg_path = _product3(tmp_path, monkeypatch, roadmap="PLATFORM_ROADMAP.md",
                              scouted=((7, ("A1 -- foundry salvage",)), (8, ("A1 -- resume verb",))))
    # newest-first, limit 1 keeps iter-08 only; the filter then finds no salvage
    rc, out, _ = _main(cfg_path, "--limit", "1", "--topic", "salvage")
    assert rc == 2 and _topic_line_counts(out) == ("salvage", 0, 0)
    assert "iter-07" not in out and "iter-08" not in out and "archive: none" in out
    # limit 2 reaches iter-07, so the same term now hits
    rc, out, _ = _main(cfg_path, "--limit", "2", "--topic", "salvage")
    assert rc == 0 and _topic_line_counts(out) == ("salvage", 1, 0)
    assert "iter-07" in out and "iter-08" not in out
    # the newest iteration survives limit 1 when the term names it
    rc, out, _ = _main(cfg_path, "--limit", "1", "--topic", "resume")
    assert rc == 0 and _topic_line_counts(out) == ("resume", 1, 0)
    assert "iter-08" in out and "iter-07" not in out
    # no limit: both scouted iterations, newest first
    rc, out, _ = _main(cfg_path, "--topic", "A1")
    assert rc == 0 and _topic_line_counts(out) == ("A1", 2, 0)
    assert out.index("iter-08") < out.index("iter-07")


# ------------------------- 5. archive absent / unset / unreadable via the CLI


def test_r05_topic_with_no_archive_reports_none_and_creates_no_file(tmp_path, monkeypatch):
    # (i) roadmap unset (the _write_cfg default): archive is simply "none"
    cfg, cfg_path = _product3(tmp_path, monkeypatch, scouted=((7, ("A1 -- foundry salvage",)),))
    assert cfg.roadmap == ""
    before = _snapshot_tree(tmp_path)
    rc, out, err = _main(cfg_path, "--topic", "salvage")
    assert rc == 0 and err == "" and _topic_line_counts(out) == ("salvage", 1, 0)
    assert out.endswith("\narchive: none\n")
    rc, out, _ = _main(cfg_path, "--topic", "nothing-here")
    assert rc == 2 and out.endswith("\narchive: none\n")
    assert _snapshot_tree(tmp_path) == before
    # (ii) roadmap set, sibling archive missing: still "none", still nothing created
    cfg2, cfg2_path = _product3(tmp_path, monkeypatch, roadmap="PLATFORM_ROADMAP.md",
                                scouted=((7, ("A1 -- foundry salvage",)),))
    assert not (tmp_path / "PLATFORM_ROADMAP_ARCHIVE.md").exists()
    before = _snapshot_tree(tmp_path)
    rc, out, _ = _main(cfg2_path, "--topic", "salvage", "--json")
    assert rc == 0 and json.loads(out)["archive"] == []
    rc, out, _ = _main(cfg2_path, "--topic", "salvage")
    assert rc == 0 and out.endswith("\narchive: none\n")
    assert not (tmp_path / "PLATFORM_ROADMAP_ARCHIVE.md").exists()
    assert _snapshot_tree(tmp_path) == before


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores file modes")
def test_r05_unreadable_archive_degrades_to_empty_instead_of_raising(tmp_path, monkeypatch):
    cfg, cfg_path = _product3(tmp_path, monkeypatch, roadmap="PLATFORM_ROADMAP.md",
                              archive_text="- **iter 3 -- resume verb.**\n",
                              scouted=((7, ("A1 -- foundry salvage",)),))
    arc = tmp_path / "PLATFORM_ROADMAP_ARCHIVE.md"
    assert foundry.read_roadmap_archive(cfg) == "- **iter 3 -- resume verb.**\n"
    arc.chmod(0o000)
    try:
        assert foundry.read_roadmap_archive(cfg) == ""
        rc, out, err = _main(cfg_path, "--topic", "resume")
        assert rc == 2 and err == "" and _topic_line_counts(out) == ("resume", 0, 0)
        assert out.endswith("\narchive: none\n")
    finally:
        arc.chmod(0o644)
    assert foundry.read_roadmap_archive(cfg) == "- **iter 3 -- resume verb.**\n"


# --------------------------------------- 7+9. text and json agree on counts


def test_r09_text_topic_line_counts_agree_with_the_json_document(product2):
    cfg, cfg_path = product2
    for term in ("salvage", "resume", "e", "outages", "", "SALVAGE", "Candidate"):
        rc_t, out_t, _ = _main(cfg_path, "--topic", term)
        rc_j, out_j, _ = _main(cfg_path, "--topic", term, "--json")
        doc = json.loads(out_j)
        shown, scouted, bullets = _topic_line_counts(out_t)
        assert shown == term == doc["topic"]
        assert scouted == doc["directions"]["total"] == len(doc["directions"]["entries"]), term
        assert bullets == len(doc["archive"]), term
        assert rc_t == rc_j == (0 if scouted or bullets else 2), term
        assert doc["directions"]["exit_code"] == (0 if scouted else 2), term
        for hit in doc["archive"]:
            assert set(hit) == {"iteration", "text"} and isinstance(hit["iteration"], int)
            assert len(hit["text"]) <= 120 and hit["text"].startswith("- **iter %d " % hit["iteration"])
    # the empty term matches every scouted iteration and every archive bullet
    rc, out, _ = _main(cfg_path, "--topic", "")
    assert rc == 0 and _topic_line_counts(out) == ("", 1, 2)


# ----------------------- out-of-scope guard: plain substring, never a regex


def test_r07_topic_is_a_plain_substring_not_a_regex_and_may_contain_spaces(product2):
    cfg, cfg_path = product2
    rc, out, _ = _main(cfg_path, "--topic", "A1 -- foundry")  # spans the candidate id and text
    assert rc == 0 and _topic_line_counts(out) == ("A1 -- foundry", 1, 0)
    rc, out, _ = _main(cfg_path, "--topic", "verb.")  # literal dot
    assert rc == 0 and _topic_line_counts(out) == ("verb.", 0, 1)
    rc, out, _ = _main(cfg_path, "--topic", "v.rb")  # a regex would match "verb"
    assert rc == 2 and _topic_line_counts(out) == ("v.rb", 0, 0)
    rc, out, _ = _main(cfg_path, "--topic", "salv.*")  # a regex would match "salvage"
    assert rc == 2 and _topic_line_counts(out) == ("salv.*", 0, 0)
    rc, out, _ = _main(cfg_path, "--topic", "**iter")  # literal stars, present in every record
    assert rc == 0 and _topic_line_counts(out) == ("**iter", 0, 2)
    assert foundry.archive_topic_hits("- **iter 3 -- a+b.**\n", "a+b") == ((3, "- **iter 3 -- a+b.**"),)
    assert foundry.archive_topic_hits("- **iter 3 -- aab.**\n", "a+b") == ()
    assert foundry.filter_directions(_digest(), "salv.*").entries == ()
    assert foundry.filter_directions(_digest(), "[Ss]alvage").entries == ()


# ------------------------------ 2. the filtered digest is a real digest


def test_r02_filtered_digest_is_a_first_class_digest_that_renders_and_serialises():
    d = _digest()
    fd = foundry.filter_directions(d, "salvage")
    assert type(fd) is foundry.DirectionsDigest and fd is not d
    assert [e.iteration for e in fd.entries] == [9, 7]
    doc = fd.to_dict()
    assert doc["total"] == 2 and doc["exit_code"] == 0
    assert [e["iteration"] for e in doc["entries"]] == [9, 7]
    assert doc["product"] == "demoprod"
    rendered = fd.render()
    assert "iter-09" in rendered and "iter-07" in rendered and "iter-08" not in rendered
    assert "no scouted iterations yet" not in rendered
    # filtering twice with the same term is idempotent
    assert foundry.filter_directions(fd, "salvage") == fd
    # filtering the filtered digest with a term only the dropped entry had is empty
    assert foundry.filter_directions(fd, "resume").entries == ()
    # the source digest is untouched by any of the above
    assert d == _digest()
