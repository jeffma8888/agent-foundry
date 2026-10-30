"""iter 492 -- black-box tests: `merge_committed_directions` keeps the candidate
lines of every already-committed DIRECTIONS.md iteration block verbatim, and
`refresh_directions_file` writes merge(render(gather(cfg)), existing_text).

Public surface only: foundry.merge_committed_directions / refresh_directions_file
/ render_directions_doc / gather_directions, driven with in-memory strings and
tmp_path fixtures. Never reads the ambient DIRECTIONS.md or any state dir.
"""
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[1]
EMDASH = "\u2014"
# built by concatenation so no vendor-looking literal sits in the source
VENDOR = "Real" + "Vendor" + "Name"
HEADER = "# Foundry directions\n\nfoundry directions -- demoprod\n"


def _block(n, cands, winner="A1", ship="pending (not yet decided)",
           lenses="hardening/DX"):
    lines = ["  iter-%02d" % n, "    lenses: " + lenses]
    lines += ["    - " + c for c in cands]
    lines += ["    winner: " + winner, "    ship: " + ship]
    return lines


def _doc(*blocks, count=None):
    lines = HEADER.rstrip("\n").split("\n")
    for b in blocks:
        lines += b
    lines.append("%d scouted iterations" % (count if count is not None else len(blocks)))
    return "\n".join(lines) + "\n"


def _merge(rendered, committed):
    return foundry.merge_committed_directions(rendered, committed)


def _block_lines(doc, n):
    """Lines of iteration block n (header line excluded) from a doc string."""
    out, inside = [], False
    for ln in doc.split("\n"):
        m = foundry._DIRECTIONS_ITER_LINE_RE.match(ln)
        if m:
            inside = int(m.group(1)) == n
            continue
        if inside:
            if ln and not ln.startswith("    "):
                break
            out.append(ln)
    return out


def _cands(doc, n):
    return [ln for ln in _block_lines(doc, n) if ln.strip().startswith("- ")]


# ============================================================== Behavior 1
def test_b1_function_is_public_and_takes_two_params():
    import inspect
    fn = getattr(foundry, "merge_committed_directions", None)
    assert callable(fn)
    assert list(inspect.signature(fn).parameters) == ["rendered", "committed"]


def test_b1_committed_candidate_lines_replace_rendered_in_committed_order():
    rendered = _doc(_block(9, ["Candidate A1 -- fresh one", "Candidate A2 -- fresh two"],
                           ship="PUSHED feed123"))
    committed = _doc(_block(9, ["Candidate A2 -- frozen two", "Candidate A1 -- frozen one"]))
    out = _merge(rendered, committed)
    assert _cands(out, 9) == ["    - Candidate A2 -- frozen two",
                              "    - Candidate A1 -- frozen one"]
    assert "fresh" not in out


def test_b1_every_non_candidate_line_keeps_its_rendered_position():
    rendered = _doc(_block(9, ["Candidate A1 -- r1", "Candidate B1 -- r2"],
                           winner="B1", ship="PUSHED feed123", lenses="new-lens"),
                    _block(8, ["Candidate A1 -- old r"], ship="REVERTED"),
                    count=40)
    committed = _doc(_block(9, ["Candidate A1 -- c1", "Candidate B1 -- c2"],
                            winner="unknown", lenses="stale-lens"),
                     _block(8, ["Candidate A1 -- old c"]),
                     count=39)
    out = _merge(rendered, committed)
    r_lines, o_lines = rendered.split("\n"), out.split("\n")
    assert len(o_lines) == len(r_lines)
    for i, (r, o) in enumerate(zip(r_lines, o_lines)):
        if r.strip().startswith("- "):
            assert o.strip().startswith("- "), i
        else:
            assert o == r, (i, r, o)
    # labels and rollup come from the RENDER, not the committed text
    assert "    lenses: new-lens" in out and "stale-lens" not in out
    assert "    winner: B1" in out and "    ship: REVERTED" in out
    assert "40 scouted iterations" in out and "39 scouted" not in out
    assert out.endswith("40 scouted iterations\n")


def test_b1_blocks_absent_from_committed_pass_through_unchanged():
    new = _block(11, ["Candidate A1 -- brand new", "Candidate B1 -- also new"])
    rendered = _doc(new, _block(10, ["Candidate A1 -- r"]))
    committed = _doc(_block(10, ["Candidate A1 -- c"]))
    out = _merge(rendered, committed)
    assert _cands(out, 11) == ["    - Candidate A1 -- brand new",
                               "    - Candidate B1 -- also new"]
    assert "\n".join(new) in out
    assert _cands(out, 10) == ["    - Candidate A1 -- c"]


def test_b1_matching_is_by_iteration_number_not_position():
    rendered = _doc(_block(21, ["Candidate A1 -- r21"]), _block(20, ["Candidate A1 -- r20"]))
    committed = _doc(_block(20, ["Candidate A1 -- c20"]), _block(19, ["Candidate A1 -- c19"]))
    out = _merge(rendered, committed)
    assert _cands(out, 21) == ["    - Candidate A1 -- r21"]
    assert _cands(out, 20) == ["    - Candidate A1 -- c20"]
    assert "c19" not in out and "iter-19" not in out


def test_b1_bare_dash_candidate_lines_count_as_candidates():
    rendered = _doc(_block(5, ["B1 -- render text", "B2 -- render two"]))
    committed = _doc(_block(5, ["B1 -- frozen text", "B2 -- frozen two"]))
    out = _merge(rendered, committed)
    assert _cands(out, 5) == ["    - B1 -- frozen text", "    - B2 -- frozen two"]


# ============================================================== Behavior 2
def test_b2_spec_example_redaction_survives_and_ship_settles():
    committed = _doc(_block(7, ["Candidate A1 -- [provider] stalled"],
                            ship="pending (not yet decided)"))
    new8 = _block(8, ["Candidate A1 -- eight", "Candidate B1 -- eight b"], winner="B1")
    rendered = _doc(new8, _block(7, ["Candidate A1 -- " + VENDOR + " stalled"],
                                 ship="PUSHED abc1234"))
    out = _merge(rendered, committed)
    assert "    - Candidate A1 -- [provider] stalled" in out
    assert VENDOR not in out
    assert "    ship: PUSHED abc1234" in _block_lines(out, 7)
    assert "pending (not yet decided)" not in "\n".join(_block_lines(out, 7))
    assert "\n".join(new8) in out
    assert _block_lines(out, 8) == new8[1:]


# ============================================================== Behavior 3
def test_b3_empty_or_non_str_committed_returns_rendered_bytes():
    rendered = _doc(_block(3, ["Candidate A1 -- x"]))
    for committed in ("", None, 42, b"  iter-03\n    - Candidate A1 -- y\n", ["x"], {}):
        out = _merge(rendered, committed)
        assert out == rendered, repr(committed)
        assert isinstance(out, str)


def test_b3_committed_without_any_iter_block_returns_rendered_bytes():
    rendered = _doc(_block(3, ["Candidate A1 -- x"]))
    for committed in ("PRE-EXISTING", "# Foundry directions\n\n    - Candidate A1 -- y\n",
                      "iter 3\n- Candidate A1 -- z\n", "\n\n\n"):
        assert _merge(rendered, committed) == rendered, repr(committed)


def test_b3_non_str_rendered_is_returned_unchanged():
    committed = _doc(_block(3, ["Candidate A1 -- y"]))
    for rendered in (None, 42, b"bytes", ["  iter-03"]):
        assert _merge(rendered, committed) is rendered


def test_b3_never_raises_on_odd_strings():
    odd = ["", "\n", "  iter-01\n", "  iter-01", "  iter-01\n    - a\n  iter-01\n    - b\n",
           "x\r\n  iter-02\r\n    - c\r\n", "  iter-99999999999999999999\n    - d\n"]
    for r in odd:
        for c in odd:
            out = _merge(r, c)
            assert isinstance(out, str), (r, c)


def test_b3_rendered_without_trailing_newline_round_trips():
    rendered = _doc(_block(3, ["Candidate A1 -- x"])).rstrip("\n")
    committed = _doc(_block(3, ["Candidate A1 -- frozen"]))
    out = _merge(rendered, committed)
    assert not out.endswith("\n")
    assert out == rendered.replace("Candidate A1 -- x", "Candidate A1 -- frozen")


# ============================================================== Behavior 4
def test_b4_count_mismatch_keeps_rendered_lines_other_blocks_still_merged():
    rendered = _doc(_block(31, ["Candidate A1 -- r1", "Candidate A2 -- r2", "Candidate A3 -- r3"]),
                    _block(30, ["Candidate A1 -- r30"]))
    committed = _doc(_block(31, ["Candidate A1 -- c1", "Candidate A2 -- c2"]),
                     _block(30, ["Candidate A1 -- c30"]))
    out = _merge(rendered, committed)
    assert _cands(out, 31) == ["    - Candidate A1 -- r1", "    - Candidate A2 -- r2",
                               "    - Candidate A3 -- r3"]
    assert "c1" not in out and "c2" not in out
    assert _cands(out, 30) == ["    - Candidate A1 -- c30"]


def test_b4_committed_with_more_candidates_is_not_frozen_either():
    rendered = _doc(_block(4, ["Candidate A1 -- r1"]))
    committed = _doc(_block(4, ["Candidate A1 -- c1", "Candidate B1 -- c2"]))
    assert _merge(rendered, committed) == rendered


def test_b4_identical_text_is_a_fixed_point():
    doc = _doc(_block(6, ["Candidate A1 -- a", "Candidate B1 -- b"]), _block(5, ["B1 -- c"]))
    assert _merge(doc, doc) == doc


# ============================================================== Behavior 5
def _write_cfg(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {"name": "demoprod", "repo": str(repo), "allowed_push_repo": "demoprod",
            "vision": str(tmp_path / "VISION.md"), "work_root": str(tmp_path / "work"),
            "dual_pm_scouts": False}
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(data))
    return foundry.load_config(str(p))


def _target(cfg):
    return pathlib.Path(cfg.repo) / "DIRECTIONS.md"


def _patch_render(monkeypatch, text):
    monkeypatch.setattr(foundry, "gather_directions", lambda c: "DIGEST")
    monkeypatch.setattr(foundry, "render_directions_doc",
                        lambda dg: text if dg == "DIGEST" else "WRONG-DIGEST")


RENDER_7 = _doc(_block(8, ["Candidate A1 -- eight"]),
                _block(7, ["Candidate A1 -- " + VENDOR + " stalled"], ship="PUSHED abc1234"))
COMMIT_7 = _doc(_block(7, ["Candidate A1 -- [provider] stalled"]))


def test_b5_existing_file_is_merged_and_returns_true(tmp_path, monkeypatch):
    cfg = _write_cfg(tmp_path)
    _target(cfg).write_text(COMMIT_7, encoding="utf-8")
    _patch_render(monkeypatch, RENDER_7)
    assert foundry.refresh_directions_file(cfg) is True
    got = _target(cfg).read_text(encoding="utf-8")
    assert got == _merge(RENDER_7, COMMIT_7)
    assert "[provider] stalled" in got and VENDOR not in got
    assert "    ship: PUSHED abc1234" in got


def test_b5_absent_file_gets_exactly_the_plain_render(tmp_path, monkeypatch):
    cfg = _write_cfg(tmp_path)
    assert not _target(cfg).exists()
    _patch_render(monkeypatch, RENDER_7)
    assert foundry.refresh_directions_file(cfg) is True
    assert _target(cfg).read_text(encoding="utf-8") == RENDER_7


def test_b5_merge_is_called_by_bare_name(tmp_path, monkeypatch):
    cfg = _write_cfg(tmp_path)
    _target(cfg).write_text(COMMIT_7, encoding="utf-8")
    _patch_render(monkeypatch, RENDER_7)
    seen = []

    def spy(rendered, committed):
        seen.append((rendered, committed))
        return "SPY-OUT"
    monkeypatch.setattr(foundry, "merge_committed_directions", spy)
    assert foundry.refresh_directions_file(cfg) is True
    assert seen == [(RENDER_7, COMMIT_7)]
    assert _target(cfg).read_text(encoding="utf-8") == "SPY-OUT"


def test_b5_raising_merge_falls_back_to_plain_render(tmp_path, monkeypatch):
    cfg = _write_cfg(tmp_path)
    _target(cfg).write_text(COMMIT_7, encoding="utf-8")
    _patch_render(monkeypatch, RENDER_7)

    def boom(*a, **k):
        raise RuntimeError("merge raised on purpose")
    monkeypatch.setattr(foundry, "merge_committed_directions", boom)
    assert foundry.refresh_directions_file(cfg) is True
    assert _target(cfg).read_text(encoding="utf-8") == RENDER_7


def test_b5_unreadable_existing_bytes_fall_back_to_plain_render(tmp_path, monkeypatch):
    cfg = _write_cfg(tmp_path)
    _target(cfg).write_bytes(b"\xff\xfe\x00  iter-07\n    - \xc3(\n")
    _patch_render(monkeypatch, RENDER_7)
    assert foundry.refresh_directions_file(cfg) is True
    assert _target(cfg).read_text(encoding="utf-8") == RENDER_7


def test_b5_raising_gather_returns_false_and_leaves_file_untouched(tmp_path, monkeypatch):
    cfg = _write_cfg(tmp_path)
    _target(cfg).write_text(COMMIT_7, encoding="utf-8")

    def boom(c):
        raise RuntimeError("gather raised on purpose")
    monkeypatch.setattr(foundry, "gather_directions", boom)
    assert foundry.refresh_directions_file(cfg) is False
    assert _target(cfg).read_text(encoding="utf-8") == COMMIT_7


# ============================================================== Behavior 6
def test_b6_two_refreshes_over_unchanged_state_are_byte_identical(tmp_path, monkeypatch):
    cfg = _write_cfg(tmp_path)
    _target(cfg).write_text(COMMIT_7, encoding="utf-8")
    _patch_render(monkeypatch, RENDER_7)
    assert foundry.refresh_directions_file(cfg) is True
    first = _target(cfg).read_bytes()
    assert foundry.refresh_directions_file(cfg) is True
    assert _target(cfg).read_bytes() == first


def _seed_scouted(cfg, n, title):
    d = pathlib.Path(cfg.state) / ("iter-%02d" % n)
    d.mkdir(parents=True, exist_ok=True)
    (d / "pm_scout_a.md").write_text(
        "# PM_SCOUT_A %s iteration %d %s lens: cap\n## Candidate C1 -- %s\n"
        % (EMDASH, n, EMDASH, title))
    (d / "pm.md").write_text("## Triage\nPick: C1\n")
    return d


def test_b6_real_gather_end_to_end_hand_redaction_survives_and_ship_settles(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry, "git_ship_subjects", lambda repo_dir: ())
    cfg = _write_cfg(tmp_path)
    d3 = _seed_scouted(cfg, 3, VENDOR + " stopped sending data")
    assert foundry.refresh_directions_file(cfg) is True
    doc = _target(cfg).read_text(encoding="utf-8")
    assert VENDOR in doc
    # the operator hand-redacts the committed candidate line
    _target(cfg).write_text(doc.replace(VENDOR, "[provider]"), encoding="utf-8")
    # later: the iteration ships and a new iteration is scouted
    (d3 / "final.md").write_text("ACTION: PUSHED s3cafe\n")
    _seed_scouted(cfg, 4, "a fresh idea")
    assert foundry.refresh_directions_file(cfg) is True
    doc2 = _target(cfg).read_text(encoding="utf-8")
    assert VENDOR not in doc2
    assert "[provider] stopped sending data" in doc2
    assert any("PUSHED s3cafe" in ln for ln in _block_lines(doc2, 3))
    assert any("a fresh idea" in ln for ln in _cands(doc2, 4))
    # idempotent over the now-unchanged state
    assert foundry.refresh_directions_file(cfg) is True
    assert _target(cfg).read_text(encoding="utf-8") == doc2


# ============================================================== import guard
def test_both_modules_import_in_a_fresh_interpreter():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
