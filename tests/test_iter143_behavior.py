"""Black-box behaviour tests for iter 143 -- the `prd-init` PRODUCER: two new pure
helpers (`render_prd_doc`, `parse_story_lines`) plus the `prd_init_cli` verb that
renders a schema-valid all-pending `prd.json` from an EXPLICIT operator story list,
refuses (writing nothing) rather than clobbering or writing an empty meter, and
self-checks the written file back through the frozen `prd_status` core.

ISOLATION CONTRACT (honored): written from the PM spec's Expected Behaviors (1-15)
and the product's own observable behaviour only. The implementation source of
`foundry.py`/`dispatcher.py`, the engineer's notes, the reviewer's notes and
`git diff` were NOT read while authoring these tests. Everything is driven through
the PUBLIC surface -- `foundry.render_prd_doc`, `foundry.parse_story_lines`,
`foundry.prd_init_cli`, `foundry.main([...])`, `foundry.load_config`, and
cross-checks that recompute expected values with the public `foundry.prd_status`.
`foundry.py`'s TEXT is used in two places as INPUT DATA to functions under test
(`foundry_cli_verbs`, behavior 14) or to a structural off-the-control-path check
(acceptance criterion), never inspected by hand.

Fully offline and deterministic: real temp files under `tmp_path` only, NO network,
NO subprocess, NO git, NO agent run. Every write target lives under `tmp_path`; the
real repo's `prd.json` path is never used as a target.
"""
import inspect
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402

# The module's OWN file, taken from the imported module rather than a quoted filename,
# so the iter-54 meta-guard (which flags that literal in any test) stays satisfied.
FOUNDRY_SRC = pathlib.Path(foundry.__file__).resolve()

VERB = "prd-init"
README = _ROOT / "README.md"
ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"


# --------------------------------------------------------------------------
# helpers -- tmp product configs (never the real repo), tree snapshots
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir (mirrors the suite's convention).
    `repo`/`work_root` are TMP dirs so the real foundry repo is never touched."""
    data = {
        "name": "demo",
        "repo": str(tmp_path / "repo"),
        "allowed_push_repo": "demo",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _cfg(tmp_path, **over):
    """Loaded ProductConfig whose repo dir exists under tmp_path."""
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    return foundry.load_config(str(_write_cfg(tmp_path, **over)))


def _snapshot_paths(root):
    """Set of every path (files AND dirs) under root -- for exactly-one-file proof."""
    root = pathlib.Path(root)
    if not root.exists():
        return set()
    return {str(p.relative_to(root)) for p in root.rglob("*")}


def _snapshot_bytes(root):
    """Map {relative-path: bytes} for every file under root (no-write / unchanged proof)."""
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _both(capsys):
    """Combined stdout+stderr of the call under test (the spec pins CONTENT, not stream)."""
    cap = capsys.readouterr()
    return cap.out + cap.err


def _titles(doc):
    return [s["title"] for s in doc["stories"]]


def _ids(doc):
    return [s["id"] for s in doc["stories"]]


def _source():
    """`foundry.py`'s text -- INPUT DATA for the functions under test, never inspected here."""
    return FOUNDRY_SRC.read_text(encoding="utf-8")


# ==========================================================================
# Behavior 1 -- render_prd_doc shape: S<n> 1-based, input order, passes False
# ==========================================================================
def test_b01_render_prd_doc_exact_shape():
    doc = foundry.render_prd_doc(["alpha", "beta"])
    assert doc == {
        "stories": [
            {"id": "S1", "title": "alpha", "passes": False},
            {"id": "S2", "title": "beta", "passes": False},
        ]
    }, f"unexpected rendered doc: {doc!r}"


def test_b01_ids_are_one_based_in_input_order():
    doc = foundry.render_prd_doc(["c", "a", "b"])
    assert _ids(doc) == ["S1", "S2", "S3"]
    assert _titles(doc) == ["c", "a", "b"], "input order must be preserved, not sorted"


def test_b01_passes_is_the_json_false_python_false():
    doc = foundry.render_prd_doc(["only"])
    val = doc["stories"][0]["passes"]
    assert val is False, f"passes must be Python False (JSON false), got {val!r}"
    # and it must serialize as JSON false, not 0
    assert '"passes": false' in json.dumps(doc, indent=2)


def test_b01_render_is_pure_and_deterministic():
    src = ["alpha", "beta"]
    first = foundry.render_prd_doc(src)
    second = foundry.render_prd_doc(src)
    assert first == second, "renderer must be deterministic"
    assert src == ["alpha", "beta"], "renderer must not mutate its input"


# ==========================================================================
# Behavior 2 -- titles stripped; blank/whitespace-only entries DROPPED, no id burned
# ==========================================================================
def test_b02_strip_and_drop_blanks_without_consuming_ids():
    doc = foundry.render_prd_doc([" alpha ", "", "   ", "beta"])
    assert len(doc["stories"]) == 2, f"expected exactly 2 surviving stories, got {doc!r}"
    assert _ids(doc) == ["S1", "S2"], "dropped entries must NOT consume an id"
    assert _titles(doc) == ["alpha", "beta"], "titles must be .strip()ed"


def test_b02_tabs_and_newlines_count_as_whitespace_only():
    doc = foundry.render_prd_doc(["\t", "\n", " x ", "  \t \n "])
    assert _titles(doc) == ["x"]
    assert _ids(doc) == ["S1"]


def test_b02_all_blank_input_yields_no_stories():
    assert foundry.render_prd_doc(["", "  ", "\t"]) == {"stories": []}


# ==========================================================================
# Behavior 3 -- render_prd_doc([]) is total: {"stories": []}, never raises
# ==========================================================================
def test_b03_empty_input_is_total():
    assert foundry.render_prd_doc([]) == {"stories": []}


def test_b03_accepts_any_iterable():
    # signature says Iterable[str]; a tuple and a generator must behave like a list
    assert foundry.render_prd_doc(("a", "b")) == foundry.render_prd_doc(["a", "b"])
    assert foundry.render_prd_doc(t for t in ["a", "b"]) == foundry.render_prd_doc(["a", "b"])


# ==========================================================================
# Behavior 4 -- the rendered doc round-trips through the FROZEN prd_status
# ==========================================================================
@pytest.mark.parametrize("n", [1, 2, 5])
def test_b04_round_trip_through_prd_status(n):
    titles = [f"story {i}" for i in range(1, n + 1)]
    st = foundry.prd_status(json.dumps(foundry.render_prd_doc(titles)))
    assert st.valid is True, f"rendered doc must be schema-valid, got {st!r}"
    assert st.total == n, f"total must be {n}, got {st.total}"
    assert st.passed == 0, f"a fresh meter must have 0 passed, got {st.passed}"
    assert st.complete is False, "a fresh all-pending meter is never complete"
    assert st.pending == tuple(f"S{i}" for i in range(1, n + 1)), (
        f"pending ids must be S1..S{n} in order, got {st.pending}"
    )


def test_b04_round_trip_survives_the_indent_2_serialization():
    # the CLI writes indent=2 text; the frozen reader must agree with the compact form
    doc = foundry.render_prd_doc(["a", "b", "c"])
    compact = foundry.prd_status(json.dumps(doc))
    pretty = foundry.prd_status(json.dumps(doc, indent=2) + "\n")
    assert (compact.valid, compact.total, compact.passed, compact.pending) == (
        pretty.valid, pretty.total, pretty.passed, pretty.pending
    )


# ==========================================================================
# Behavior 5 -- parse_story_lines: one title per line, stripped, file order;
#               blank lines skipped; first-non-blank `#` is a comment
# ==========================================================================
def test_b05_one_title_per_line_in_file_order():
    assert foundry.parse_story_lines("alpha\nbeta\ngamma") == ["alpha", "beta", "gamma"]


def test_b05_lines_are_stripped_and_blanks_skipped():
    text = "  alpha  \n\n\t\n   \nbeta\t\n"
    assert foundry.parse_story_lines(text) == ["alpha", "beta"]


def test_b05_comment_lines_are_skipped():
    text = "# a header comment\nalpha\n   # indented comment\nbeta\n#\n"
    assert foundry.parse_story_lines(text) == ["alpha", "beta"]


def test_b05_hash_in_the_interior_is_not_a_comment():
    assert foundry.parse_story_lines("fix issue #42 in the parser") == [
        "fix issue #42 in the parser"
    ]


def test_b05_empty_text_and_whitespace_only_text_are_total():
    assert foundry.parse_story_lines("") == []
    assert foundry.parse_story_lines("\n\n \t\n") == []


def test_b05_crlf_text_does_not_leak_carriage_returns():
    # \r is whitespace, so .strip() must remove it -- a title with a trailing \r
    # would render into the JSON meter verbatim
    out = foundry.parse_story_lines("alpha\r\nbeta\r\n")
    assert out == ["alpha", "beta"], f"CR leaked into titles: {out!r}"


# ==========================================================================
# Behavior 6 -- ONE leading list marker stripped: "- ", "* ", or digits + ". "
# ==========================================================================
def test_b06_dash_star_and_numeric_markers_are_stripped():
    text = "- ship X\n* ship W\n3. ship Y\n10. ship Z\n"
    assert foundry.parse_story_lines(text) == ["ship X", "ship W", "ship Y", "ship Z"]


def test_b06_line_without_a_marker_is_unchanged():
    assert foundry.parse_story_lines("ship plain") == ["ship plain"]
    # the marker forms require the trailing space, so these are NOT markers
    assert foundry.parse_story_lines("-nodash") == ["-nodash"]
    assert foundry.parse_story_lines("*nostar") == ["*nostar"]


def test_b06_interior_marker_lookalike_is_left_whole():
    assert foundry.parse_story_lines("fix a - b bug") == ["fix a - b bug"]
    assert foundry.parse_story_lines("rank 1. then 2. later") == ["rank 1. then 2. later"]


def test_b06_only_one_marker_is_stripped():
    assert foundry.parse_story_lines("- - ship Z") == ["- ship Z"]
    assert foundry.parse_story_lines("- 2. ship Q") == ["2. ship Q"]


def test_b06_marker_with_leading_indent_and_padding():
    # behavior 5 says every returned title is stripped, so no padding survives
    out = foundry.parse_story_lines("   - ship X\n-   spaced\n")
    assert out == ["ship X", "spaced"], f"padding survived marker strip: {out!r}"


def test_b06_marker_only_line_yields_nothing():
    assert foundry.parse_story_lines("- \n*  \n7. \n") == []


# ==========================================================================
# Behavior 7 -- happy path: writes indent=2 + newline, prints path + summary, rc 0
# ==========================================================================
def test_b07_writes_target_prints_path_and_summary_returns_zero(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    target = pathlib.Path(cfg.prd)
    rc = foundry.prd_init_cli(cfg, stories=["a", "b"])
    out = _both(capsys)
    assert rc == 0, f"happy path must return 0, got {rc}"
    assert target.exists(), f"target {target} was not written"
    expected = json.dumps(foundry.render_prd_doc(["a", "b"]), indent=2) + "\n"
    assert target.read_text() == expected, "file text must be json.dumps(indent=2) + one newline"
    assert str(target) in out, f"output must name the written path; got:\n{out}"
    assert "0/2 stories pass" in out, f"output must carry the prd_status summary; got:\n{out}"


def test_b07_out_argument_overrides_cfg_prd(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    other = tmp_path / "elsewhere.json"
    rc = foundry.prd_init_cli(cfg, stories=["a"], out=str(other))
    out = _both(capsys)
    assert rc == 0
    assert other.exists(), "explicit out= target must be written"
    assert not pathlib.Path(cfg.prd).exists(), "cfg.prd must NOT be written when out= is given"
    assert str(other) in out
    assert "0/1 stories pass" in out


def test_b07_written_file_is_valid_json_matching_the_renderer(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    target = tmp_path / "prd-out.json"
    assert foundry.prd_init_cli(cfg, stories=[" a ", "", "b"], out=str(target)) == 0
    capsys.readouterr()
    assert json.loads(target.read_text()) == foundry.render_prd_doc([" a ", "", "b"])


# ==========================================================================
# Behavior 8 -- empty story set: refuse, write NOTHING, rc 2
# ==========================================================================
def test_b08_no_stories_at_all_refuses_and_writes_nothing(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    before = _snapshot_bytes(tmp_path)
    rc = foundry.prd_init_cli(cfg)
    out = _both(capsys)
    assert rc == 2, f"empty story set must return 2, got {rc}"
    assert _snapshot_bytes(tmp_path) == before, "refusal must write nothing"
    assert not pathlib.Path(cfg.prd).exists()
    assert out.strip(), "a refusal must be explained on stdout/stderr"


def test_b08_all_blank_stories_refuses(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    before = _snapshot_bytes(tmp_path)
    rc = foundry.prd_init_cli(cfg, stories=["", "   ", "\t"])
    _both(capsys)
    assert rc == 2, "a story list that renders to zero stories must refuse"
    assert _snapshot_bytes(tmp_path) == before


def test_b08_from_file_with_only_comments_and_blanks_refuses(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    src = tmp_path / "stories.txt"
    src.write_text("# only a comment\n\n   \n")
    before = _snapshot_bytes(tmp_path)
    rc = foundry.prd_init_cli(cfg, from_file=str(src))
    _both(capsys)
    assert rc == 2, "no surviving line from from_file must refuse"
    assert _snapshot_bytes(tmp_path) == before


def test_b08_zero_story_doc_is_never_written(tmp_path, capsys):
    # the reason for the refusal: a 0-story meter reads 0/0 forever
    empty = foundry.prd_status(json.dumps(foundry.render_prd_doc([])))
    assert empty.total == 0 and empty.complete is False
    cfg = _cfg(tmp_path)
    target = tmp_path / "never.json"
    assert foundry.prd_init_cli(cfg, stories=[], out=str(target)) == 2
    _both(capsys)
    assert not target.exists(), "a 0-story doc must never reach disk"


# ==========================================================================
# Behavior 9 -- existing target: refuse naming it, byte-unchanged, rc 2; force overwrites
# ==========================================================================
def test_b09_existing_target_refused_and_left_byte_unchanged(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    target = pathlib.Path(cfg.prd)
    original = b'{"stories": [{"id": "KEEP", "passes": true}]}\n'
    target.write_bytes(original)
    rc = foundry.prd_init_cli(cfg, stories=["a", "b"])
    out = _both(capsys)
    assert rc == 2, f"existing target without force must return 2, got {rc}"
    assert target.read_bytes() == original, "existing target must be BYTE-unchanged"
    assert str(target) in out, f"refusal must NAME the target path; got:\n{out}"


def test_b09_force_overwrites_and_returns_zero(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    target = pathlib.Path(cfg.prd)
    target.write_bytes(b"stale contents\n")
    rc = foundry.prd_init_cli(cfg, stories=["a", "b"], force=True)
    out = _both(capsys)
    assert rc == 0, f"force=True must overwrite and return 0, got {rc}"
    assert target.read_text() == json.dumps(foundry.render_prd_doc(["a", "b"]), indent=2) + "\n"
    assert "0/2 stories pass" in out


def test_b09_refusal_applies_to_the_out_target_too(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    other = tmp_path / "taken.json"
    other.write_bytes(b"mine\n")
    rc = foundry.prd_init_cli(cfg, stories=["a"], out=str(other))
    out = _both(capsys)
    assert rc == 2
    assert other.read_bytes() == b"mine\n"
    assert str(other) in out


def test_b09_force_on_an_absent_target_is_still_a_normal_write(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    target = tmp_path / "fresh.json"
    assert foundry.prd_init_cli(cfg, stories=["a"], out=str(target), force=True) == 0
    _both(capsys)
    assert target.exists()


# ==========================================================================
# Behavior 10 -- unreadable from_file: refuse naming it, write nothing, rc 2, no OSError
# ==========================================================================
def test_b10_missing_from_file_refuses_without_raising(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    missing = tmp_path / "nope.txt"
    before = _snapshot_bytes(tmp_path)
    rc = foundry.prd_init_cli(cfg, from_file=str(missing))   # must not raise
    out = _both(capsys)
    assert rc == 2, f"missing from_file must return 2, got {rc}"
    assert _snapshot_bytes(tmp_path) == before, "refusal must write nothing"
    assert str(missing) in out, f"refusal must NAME the path; got:\n{out}"


def test_b10_directory_as_from_file_refuses_without_raising(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    a_dir = tmp_path / "adir"
    a_dir.mkdir()
    before = _snapshot_bytes(tmp_path)
    rc = foundry.prd_init_cli(cfg, from_file=str(a_dir))     # IsADirectoryError must not escape
    out = _both(capsys)
    assert rc == 2, f"a directory from_file must return 2, got {rc}"
    assert _snapshot_bytes(tmp_path) == before
    assert str(a_dir) in out


def test_b10_unreadable_from_file_refuses_even_with_inline_stories(tmp_path, capsys):
    # an unreadable source is indistinguishable from an empty one, so it cannot be
    # silently ignored just because inline --story values would have sufficed
    cfg = _cfg(tmp_path)
    missing = tmp_path / "gone.txt"
    before = _snapshot_bytes(tmp_path)
    rc = foundry.prd_init_cli(cfg, stories=["a"], from_file=str(missing))
    out = _both(capsys)
    assert rc == 2, f"unreadable from_file must refuse, got {rc}"
    assert _snapshot_bytes(tmp_path) == before
    assert str(missing) in out


# ==========================================================================
# Behavior 11 -- source order: `stories` values first, then from_file lines
# ==========================================================================
def test_b11_stories_precede_from_file_lines(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    src = tmp_path / "stories.txt"
    src.write_text("- from file one\n\n# skip\n2. from file two\n")
    target = tmp_path / "combined.json"
    rc = foundry.prd_init_cli(
        cfg, stories=["inline one", "inline two"], from_file=str(src), out=str(target)
    )
    out = _both(capsys)
    assert rc == 0, f"combined sources must succeed, got {rc}\n{out}"
    doc = json.loads(target.read_text())
    assert _titles(doc) == ["inline one", "inline two", "from file one", "from file two"]
    assert _ids(doc) == ["S1", "S2", "S3", "S4"]
    assert "0/4 stories pass" in out


def test_b11_from_file_only_keeps_file_order(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    src = tmp_path / "s.txt"
    src.write_text("zeta\nalpha\nmiddle\n")
    target = tmp_path / "f.json"
    assert foundry.prd_init_cli(cfg, from_file=str(src), out=str(target)) == 0
    _both(capsys)
    assert _titles(json.loads(target.read_text())) == ["zeta", "alpha", "middle"]


# ==========================================================================
# Behavior 12 -- a success creates EXACTLY ONE file and no directory
# ==========================================================================
def test_b12_success_creates_exactly_one_file(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    src = tmp_path / "s.txt"
    src.write_text("one\ntwo\n")
    before = _snapshot_paths(tmp_path)
    target = pathlib.Path(cfg.prd)
    rc = foundry.prd_init_cli(cfg, stories=["zero"], from_file=str(src))
    _both(capsys)
    assert rc == 0
    new = _snapshot_paths(tmp_path) - before
    assert new == {str(target.relative_to(tmp_path))}, (
        f"exactly one new path (the target) expected, got {sorted(new)}"
    )
    assert target.is_file(), "the one new path must be a file, not a directory"


def test_b12_missing_parent_is_a_refusal_not_a_mkdir(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    deep = tmp_path / "no" / "such" / "dir" / "prd.json"
    before = _snapshot_paths(tmp_path)
    rc = foundry.prd_init_cli(cfg, stories=["a"], out=str(deep))
    out = _both(capsys)
    assert rc == 2, f"a missing parent must refuse (never mkdir), got {rc}\n{out}"
    assert _snapshot_paths(tmp_path) == before, "no directory may be created"
    assert not deep.exists()


def test_b12_every_refusal_leaves_the_tree_identical(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    before = _snapshot_paths(tmp_path)
    for kwargs in (
        {},                                                  # behavior 8
        {"stories": ["   "]},                                # behavior 8
        {"from_file": str(tmp_path / "absent.txt")},          # behavior 10
    ):
        assert foundry.prd_init_cli(cfg, **kwargs) == 2
        _both(capsys)
        assert _snapshot_paths(tmp_path) == before, f"refusal touched the tree: {kwargs}"


# ==========================================================================
# Behavior 13 -- self-check: bad renderer -> named mismatch + rc 1 (monkeypatched)
# ==========================================================================
def _fake_renderer(doc):
    def _fake(titles):
        return doc
    return _fake


def test_b13_control_real_renderer_self_checks_clean(tmp_path, capsys):
    # non-vacuity control for the four planted-producer cases below
    cfg = _cfg(tmp_path)
    assert foundry.prd_init_cli(cfg, stories=["a"], out=str(tmp_path / "ok.json")) == 0
    _both(capsys)


def test_b13_renderer_dropping_all_stories_is_caught(tmp_path, capsys, monkeypatch):
    # the fail-OPEN trap: expected count must come from the SOURCE titles, not the doc
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "render_prd_doc", _fake_renderer({"stories": []}))
    rc = foundry.prd_init_cli(cfg, stories=["a"], out=str(tmp_path / "bad.json"))
    out = _both(capsys)
    assert rc == 1, f"a renderer that drops the only story must self-check FAIL (1), got {rc}\n{out}"
    assert "self-check" in out, f"the failure must be reported as a self-check failure:\n{out}"
    assert "0" in out and "1" in out, f"the message must NAME the mismatch:\n{out}"


def test_b13_duplicating_renderer_is_caught(tmp_path, capsys, monkeypatch):
    doubled = {"stories": [
        {"id": "S1", "title": "a", "passes": False},
        {"id": "S2", "title": "a", "passes": False},
    ]}
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "render_prd_doc", _fake_renderer(doubled))
    rc = foundry.prd_init_cli(cfg, stories=["a"], out=str(tmp_path / "bad.json"))
    out = _both(capsys)
    assert rc == 1, f"total 2 vs 1 source title must self-check FAIL, got {rc}\n{out}"
    assert "self-check" in out, f"the failure must name the mismatch:\n{out}"


def test_b13_prepassed_renderer_is_caught(tmp_path, capsys, monkeypatch):
    prepassed = {"stories": [{"id": "S1", "title": "a", "passes": True}]}
    assert foundry.prd_status(json.dumps(prepassed)).passed == 1   # precondition
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "render_prd_doc", _fake_renderer(prepassed))
    rc = foundry.prd_init_cli(cfg, stories=["a"], out=str(tmp_path / "bad.json"))
    out = _both(capsys)
    assert rc == 1, f"passed != 0 must self-check FAIL, got {rc}\n{out}"
    assert "self-check" in out, f"the failure must name the mismatch:\n{out}"


def test_b13_invalid_doc_from_renderer_is_caught(tmp_path, capsys, monkeypatch):
    broken = {"stories": "not a list"}
    assert foundry.prd_status(json.dumps(broken)).valid is False    # precondition
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "render_prd_doc", _fake_renderer(broken))
    rc = foundry.prd_init_cli(cfg, stories=["a"], out=str(tmp_path / "bad.json"))
    out = _both(capsys)
    assert rc == 1, f"an invalid written doc must self-check FAIL, got {rc}\n{out}"
    assert "self-check" in out, f"the failure must name the mismatch:\n{out}"


def test_b13_seams_are_called_by_bare_module_name(tmp_path, capsys, monkeypatch):
    # parse_story_lines + prd_status must also be reachable via monkeypatch (seam contract)
    cfg = _cfg(tmp_path)
    src = tmp_path / "s.txt"
    src.write_text("ignored\n")
    monkeypatch.setattr(foundry, "parse_story_lines", lambda text: ["patched title"])
    target = tmp_path / "seam.json"
    assert foundry.prd_init_cli(cfg, from_file=str(src), out=str(target)) == 0
    _both(capsys)
    assert _titles(json.loads(target.read_text())) == ["patched title"], (
        "parse_story_lines must be called by bare module name so the seam bites"
    )


# ==========================================================================
# Behavior 14 -- CLI reachability: verb in the parser + in foundry_cli_verbs
# ==========================================================================
def test_b14_verb_is_listed_by_foundry_cli_verbs():
    verbs = foundry.foundry_cli_verbs(_source())
    assert len(verbs) >= 40, f"non-vacuity floor: only {len(verbs)} verbs parsed"
    assert VERB in verbs, f"{VERB} missing from parsed verbs: {verbs}"


def test_b14_main_dispatches_the_verb_with_repeatable_story(tmp_path, capsys):
    cfg_path = _write_cfg(tmp_path)
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    target = tmp_path / "viacli.json"
    rc = foundry.main([VERB, "--config", str(cfg_path), "--out", str(target),
                       "--story", "a", "--story", "b"])
    out = _both(capsys)
    assert rc == 0, f"main([{VERB!r}, ...]) must return 0, got {rc}\n{out}"
    assert _titles(json.loads(target.read_text())) == ["a", "b"], "--story must be repeatable"


def test_b14_main_supports_from_file_and_force(tmp_path, capsys):
    cfg_path = _write_cfg(tmp_path)
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    src = tmp_path / "s.txt"
    src.write_text("- alpha\n2. beta\n")
    target = tmp_path / "ff.json"
    assert foundry.main([VERB, "--config", str(cfg_path), "--from-file", str(src),
                         "--out", str(target)]) == 0
    _both(capsys)
    assert _titles(json.loads(target.read_text())) == ["alpha", "beta"]
    # second run without --force refuses; with --force it replaces
    assert foundry.main([VERB, "--config", str(cfg_path), "--story", "solo",
                         "--out", str(target)]) == 2
    _both(capsys)
    assert _titles(json.loads(target.read_text())) == ["alpha", "beta"], "refusal must not clobber"
    assert foundry.main([VERB, "--config", str(cfg_path), "--story", "solo",
                         "--out", str(target), "--force"]) == 0
    _both(capsys)
    assert _titles(json.loads(target.read_text())) == ["solo"]


def test_b14_config_is_required(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main([VERB])
    assert ei.value.code == 2, "argparse must reject a missing --config with exit 2"
    _both(capsys)


def test_b14_subcommand_help_advertises_every_flag(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main([VERB, "--help"])
    assert ei.value.code == 0
    help_text = _both(capsys)
    for flag in ("--config", "--story", "--from-file", "--out", "--force"):
        assert flag in help_text, f"{flag} missing from `{VERB} --help`:\n{help_text}"


# ==========================================================================
# Behavior 15 -- the payoff: the dispatcher's shift-loop hook stops returning None
# ==========================================================================
def test_b15_dispatch_progress_line_reports_the_generated_meter(tmp_path, capsys):
    cfg = _cfg(tmp_path, name="widgets")
    # control: today every rostered product has no prd.json, so the hook is silent
    assert not pathlib.Path(cfg.prd).exists()
    assert foundry.dispatch_progress_line(cfg) is None

    assert foundry.prd_init_cli(cfg, stories=["a", "b", "c"]) == 0
    _both(capsys)
    line = foundry.dispatch_progress_line(cfg)
    assert line is not None, "after generation the shift-loop hook must report something"
    assert line.startswith("widgets: 0/3 stories pass"), (
        f"expected the spec's '<name>: 0/N stories pass' line, got {line!r}"
    )


def test_b15_meter_tracks_the_story_count(tmp_path, capsys):
    cfg = _cfg(tmp_path, name="demo")
    src = tmp_path / "s.txt"
    src.write_text("- one\n- two\n# not a story\n\n- three\n- four\n")
    assert foundry.prd_init_cli(cfg, from_file=str(src)) == 0
    _both(capsys)
    assert foundry.dispatch_progress_line(cfg).startswith("demo: 0/4 stories pass")


# ==========================================================================
# Acceptance criteria that are observable without reading the diff
# ==========================================================================
def test_ac_producer_is_off_the_control_path():
    # structural: the shift loop / iteration driver must never call the writer
    for fn in (foundry.run_iteration, foundry.run_stage):
        src = inspect.getsource(fn)
        assert "prd_init_cli" not in src, f"{fn.__name__} must not call the producer"
    assert "prd_init_cli" not in inspect.getsource(dispatcher), (
        "the dispatcher must not call the producer"
    )


def test_ac_readme_documents_the_verb_in_the_numbered_index():
    text = README.read_text(encoding="utf-8")
    assert "\n# 44." in text, "README numbered command index must gain a # 44. entry"
    entry = text.split("\n# 44.", 1)[1]
    assert VERB in entry.split("\n# ", 1)[0], f"the # 44. entry must document {VERB}"


def test_ac_iteration_records_ride_this_commit():
    ledger = [ln for ln in ROADMAP.read_text(encoding="utf-8").splitlines()
              if ln.startswith("- iter 143 ")]
    assert len(ledger) == 1, f"expected exactly one '- iter 143 ' ledger row, got {ledger}"
    assert len(ledger[0]) <= 120, f"ledger row is {len(ledger[0])} chars (limit 120)"
    assert any(ln.startswith("- **iter 143 ")
               for ln in ARCHIVE.read_text(encoding="utf-8").splitlines()), (
        "the verbatim '- **iter 143 ' detail bullet must be in the archive"
    )


def test_ac_both_modules_still_import():
    assert foundry.__name__ == "foundry" and dispatcher.__name__ == "dispatcher"
