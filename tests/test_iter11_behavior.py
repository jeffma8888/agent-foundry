"""Black-box behaviour tests for iter 11 -- the pure `prd_status(prd_text) ->
PrdStatus` parser for a per-product `prd.json` machine roadmap, the new
`ProductConfig.prd` field, and the additive on-demand `foundry prd --config
<cfg>` reporter CLI (exit 0 complete / 1 incomplete / 2 missing|invalid).

ISOLATION: written from the PM spec (Expected Behaviors 1-14) and the product's
own observable behaviour only. The implementation source (foundry.py internals),
the engineer/reviewer notes, and `git diff` were NOT read. Every check drives the
public interface: the pure core via `foundry.prd_status(...)` against synthetic
JSON strings, config resolution via `foundry.load_config(...)`, and the CLI via
`foundry.main(["prd", ...])` with a tmp JSON config whose `prd` points at a tmp
file (the real repo's prd path is NEVER used). Cross-checks recompute expected
values with the same public pure helper. Fully offline and deterministic -- real
temp files only, NO subprocess/git/network/agent-run except the `--help`
regression probe (which only prints usage + exits).
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers -- build synthetic prd JSON text + tmp configs (never the real repo)
# --------------------------------------------------------------------------
def _stories_text(stories, wrap=False):
    """JSON text for a story list. wrap=True -> {"stories": [...]}; else bare []."""
    return json.dumps({"stories": stories} if wrap else stories)


def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir (mirrors the suite's convention).
    `repo` is a TMP dir so the real foundry repo is never touched."""
    data = {
        "name": "demoprod",
        "repo": str(tmp_path / "repo"),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _cfg_with_prd(tmp_path, prd_text=None, prd_name="prd.json"):
    """Write a config whose `prd` points at <repo>/<prd_name>; optionally seed
    that prd file with `prd_text` (None -> file absent). Returns (cfg, cfg_path)."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    prd_path = repo / prd_name
    cfg_path = _write_cfg(tmp_path, prd=str(prd_path))
    if prd_text is not None:
        prd_path.write_text(prd_text)
    cfg = foundry.load_config(str(cfg_path))
    return cfg, cfg_path


def _snapshot_tree(root):
    """Map of {relative-path: bytes} for every file under root (for no-write proof)."""
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }


# ==========================================================================
# A. Pure parser  prd_status(prd_text: str) -> PrdStatus
# ==========================================================================

# --- Behavior 1 -- total == #story objects, passed == #truthy passes --------
def test_b01_total_and_passed_counts():
    r = foundry.prd_status(_stories_text(
        [{"id": "a", "passes": True}, {"id": "b", "passes": False}, {"id": "c"}]
    ))
    assert r.valid is True
    assert r.total == 3, f"total should equal the number of story objects, got {r.total}"
    assert r.passed == 1, f"passed should count truthy `passes`, got {r.passed}"


# --- Behavior 2 -- bare array and {"stories": [...]} are equivalent ---------
def test_b02_both_top_level_shapes_equivalent():
    stories = [{"passes": True}, {"passes": False}, {"passes": True}]
    bare = foundry.prd_status(_stories_text(stories, wrap=False))
    wrapped = foundry.prd_status(_stories_text(stories, wrap=True))
    assert bare.valid and wrapped.valid
    assert bare.total == wrapped.total == 3
    assert bare.passed == wrapped.passed == 2
    assert bare.pending == wrapped.pending, (
        f"bare vs wrapped disagree on pending: {bare.pending} != {wrapped.pending}"
    )


# --- Behavior 3 -- `passes` truthiness: true/1 pass; missing/false/null/0 not
def test_b03_passes_truthiness():
    # each of these counts as PASSED
    for val in (True, 1):
        r = foundry.prd_status(_stories_text([{"passes": val}]))
        assert r.passed == 1 and r.total == 1, f"passes={val!r} should count as passed"
    # each of these does NOT count as passed
    r = foundry.prd_status(_stories_text(
        [{"passes": False}, {"passes": None}, {"passes": 0}, {"id": "nokey"}]
    ))
    assert r.total == 4
    assert r.passed == 0, f"false/null/0/missing must not count as passed, got {r.passed}"


# --- Behavior 4 -- non-object list entries ignored entirely -----------------
def test_b04_non_object_entries_ignored():
    r = foundry.prd_status(_stories_text([{"passes": True}, "junk", 5]))
    assert r.total == 1, f"non-object entries must be excluded from total, got {r.total}"
    assert r.passed == 1
    assert r.pending == (), f"pending must exclude non-objects, got {r.pending}"
    # arrays/nulls are non-objects too
    r2 = foundry.prd_status(_stories_text([[1, 2], None, {"passes": False, "id": "S"}]))
    assert r2.total == 1 and r2.passed == 0
    assert r2.pending == ("S",)


# --- Behavior 5 -- complete iff valid AND >=1 story AND all pass ------------
def test_b05_complete_semantics():
    empty = foundry.prd_status(_stories_text([]))
    assert empty.valid is True and empty.total == 0
    assert empty.complete is False, "empty story list must NOT be complete"

    all_pass = foundry.prd_status(_stories_text([{"passes": True}, {"passes": 1}]))
    assert all_pass.total == 2 and all_pass.passed == 2
    assert all_pass.complete is True, "all-passing non-empty list must be complete"

    one_pending = foundry.prd_status(_stories_text([{"passes": True}, {"passes": False}]))
    assert one_pending.complete is False, "any pending story must make complete False"

    invalid = foundry.prd_status("not json at all")
    assert invalid.valid is False and invalid.complete is False


# --- Behavior 6 -- summary == exactly "{passed}/{total} stories pass" -------
def test_b06_summary_format():
    r = foundry.prd_status(_stories_text(
        [{"passes": True}, {"passes": True}, {"passes": False},
         {"passes": False}, {"passes": False}]
    ))
    assert r.passed == 2 and r.total == 5
    assert r.summary == "2/5 stories pass", f"summary was {r.summary!r}"
    # empty
    e = foundry.prd_status(_stories_text([]))
    assert e.summary == "0/0 stories pass", f"empty summary was {e.summary!r}"


# --- Behavior 7 -- pending identifiers: id|title|#k, file order, passers gone
def test_b07_pending_id_title_positional():
    # id present+truthy wins; else title; else #k (k = 1-based among story objs)
    r = foundry.prd_status(_stories_text([
        {"id": "S1", "passes": True},                 # passes -> absent
        {"id": "S2", "title": "T2", "passes": False}, # id wins -> "S2"
        {"title": "T3", "passes": False},             # title -> "T3"
        {"passes": False},                            # neither -> "#4"
    ]))
    assert r.pending == ("S2", "T3", "#4"), f"pending mismatch: {r.pending}"


def test_b07_positional_index_is_among_story_objects_not_raw_list():
    # non-object entries must NOT advance the positional counter: the pending
    # object below is the 3rd STORY OBJECT (positions among objects: 1,2,3),
    # so its fallback id is "#3" -- NOT "#5" (its raw list index).
    r = foundry.prd_status(_stories_text([
        {"passes": True},     # story-object #1 (passes)
        "junk",               # ignored
        {"passes": True},     # story-object #2 (passes)
        5,                    # ignored
        {"passes": False},    # story-object #3 (pending) -> "#3"
    ]))
    assert r.pending == ("#3",), f"positional id must count story objects only, got {r.pending}"


def test_b07_falsy_id_falls_through_to_title_then_positional():
    # empty-string / null id is NOT truthy -> fall back to title
    assert foundry.prd_status(_stories_text([{"id": "", "title": "T", "passes": False}])).pending == ("T",)
    assert foundry.prd_status(_stories_text([{"id": None, "title": "T", "passes": False}])).pending == ("T",)
    # falsy id AND falsy title -> positional "#1"
    assert foundry.prd_status(_stories_text([{"id": "", "title": "", "passes": False}])).pending == ("#1",)
    assert foundry.prd_status(_stories_text([{"id": None, "title": None, "passes": False}])).pending == ("#1",)


# --- Behavior 8 -- never raises; invalid/wrong-shape -> valid=False, zeros ---
def test_b08_never_raises_invalid_returns_false():
    empty_zero = ("", (False, 0, 0, ()))
    cases = {
        "": empty_zero[1],
        "{not valid json": (False, 0, 0, ()),          # malformed JSON
        "42": (False, 0, 0, ()),                        # valid JSON, not a list/obj
        '"x"': (False, 0, 0, ()),                       # valid JSON string
        "{}": (False, 0, 0, ()),                        # object with no `stories`
        '{"stories": "x"}': (False, 0, 0, ()),          # `stories` present but not an array
        "[1, 2, 3]": (True, 0, 0, ()),                  # array of non-objects -> valid, empty
    }
    for text, (valid, total, passed, pending) in cases.items():
        r = foundry.prd_status(text)  # must not raise
        assert r.valid is valid, f"{text!r}: valid expected {valid}, got {r.valid}"
        assert r.total == total, f"{text!r}: total expected {total}, got {r.total}"
        assert r.passed == passed, f"{text!r}: passed expected {passed}, got {r.passed}"
        assert r.pending == pending, f"{text!r}: pending expected {pending}, got {r.pending}"


# --- Behavior 9 -- frozen dataclass, value-equality on identical text -------
def test_b09_frozen_value_equality():
    import dataclasses
    text = _stories_text([{"id": "x", "passes": True}, {"id": "y", "passes": False}])
    a = foundry.prd_status(text)
    b = foundry.prd_status(text)
    assert type(a).__name__ == "PrdStatus"
    assert dataclasses.is_dataclass(a)
    assert a == b, "two prd_status calls on byte-identical text must compare =="
    # frozen: attribute assignment must raise
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.total = 999
    # required fields exist
    for f in ("valid", "total", "passed", "pending"):
        assert hasattr(a, f), f"PrdStatus missing field {f!r}"


# ==========================================================================
# B. Config field  ProductConfig.prd
# ==========================================================================

# --- Behavior 10 -- default <repo>/prd.json; explicit path w/ expansion -----
def test_b10_prd_defaults_to_repo_prd_json(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))  # config omits `prd`
    assert hasattr(cfg, "prd"), "ProductConfig has no `prd` field"
    assert pathlib.Path(cfg.prd) == pathlib.Path(cfg.repo) / "prd.json", (
        f"default prd should be <repo>/prd.json, got {cfg.prd!r}"
    )


def test_b10_explicit_prd_absolute_preserved(tmp_path):
    explicit = tmp_path / "custom" / "roadmap.json"
    cfg = foundry.load_config(str(_write_cfg(tmp_path, prd=str(explicit))))
    assert pathlib.Path(cfg.prd) == explicit, f"explicit prd path not honoured: {cfg.prd!r}"


def test_b10_tilde_and_foundry_expanded(tmp_path):
    import os
    # ~ expansion
    cfg_tilde = foundry.load_config(str(_write_cfg(tmp_path, prd="~/nowhere_iter11/prd.json")))
    assert cfg_tilde.prd == os.path.expanduser("~/nowhere_iter11/prd.json"), (
        f"~ not expanded in prd: {cfg_tilde.prd!r}"
    )
    # {FOUNDRY} expands the same way it does for another resolved field (vision),
    # so prd and vision under {FOUNDRY} share the same expanded root dir.
    cfg_f = foundry.load_config(str(_write_cfg(
        tmp_path, prd="{FOUNDRY}/sub/prd.json", vision="{FOUNDRY}/VISION.md")))
    assert "{FOUNDRY}" not in cfg_f.prd, f"{{FOUNDRY}} left unexpanded in prd: {cfg_f.prd!r}"
    assert pathlib.Path(cfg_f.prd).parent.parent == pathlib.Path(cfg_f.vision).parent, (
        f"{{FOUNDRY}} in prd expanded to a different root than in vision: "
        f"{cfg_f.prd!r} vs {cfg_f.vision!r}"
    )


def test_b10_backward_compatible_load_without_prd(tmp_path):
    # a config that lacks a `prd` key still loads without error (already exercised
    # by the default test, but assert the no-raise + other fields intact contract)
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    assert cfg.name == "demoprod"
    assert pathlib.Path(cfg.repo).name == "repo"


# ==========================================================================
# C. CLI subcommand  foundry prd --config <cfg>
# ==========================================================================

# --- Behavior 11 -- missing cfg.prd -> exit 2, names the path ---------------
def test_b11_missing_prd_exit2(tmp_path, capsys):
    cfg, cfg_path = _cfg_with_prd(tmp_path, prd_text=None)   # prd file absent
    assert not pathlib.Path(cfg.prd).exists(), "precondition: prd file must be absent"
    rc = foundry.main(["prd", "--config", str(cfg_path)])    # must not raise
    cap = capsys.readouterr()
    combined = cap.out + cap.err
    assert rc == 2, f"missing prd returned {rc!r}, expected 2"
    assert cfg.prd in combined, f"missing-path message did not name cfg.prd:\n{combined}"


# --- Behavior 12 -- valid + pending -> exit 1, prints path/summary/complete/pending
def test_b12_pending_exit1(tmp_path, capsys):
    text = _stories_text([
        {"id": "S1", "passes": True},
        {"id": "S2", "passes": False},
        {"title": "T3", "passes": False},
    ])
    cfg, cfg_path = _cfg_with_prd(tmp_path, prd_text=text)
    rc = foundry.main(["prd", "--config", str(cfg_path)])
    out = capsys.readouterr().out
    assert rc == 1, f"pending prd returned {rc!r}, expected 1"
    st = foundry.prd_status(text)
    assert st.summary == "1/3 stories pass"
    assert cfg.prd in out, f"report did not print the cfg.prd path:\n{out}"
    assert st.summary in out, f"report missing summary {st.summary!r}:\n{out}"
    assert "complete: False" in out, f"report missing 'complete: False':\n{out}"
    assert "pending:" in out, f"report missing 'pending:' line:\n{out}"
    for pid in st.pending:            # S2, T3
        assert pid in out, f"pending identifier {pid!r} not listed in report:\n{out}"


# --- Behavior 13 -- all-pass -> exit 0 complete:True; invalid shape -> exit 2
def test_b13_complete_exit0(tmp_path, capsys):
    text = _stories_text([{"id": "S1", "passes": True}, {"id": "S2", "passes": 1}])
    cfg, cfg_path = _cfg_with_prd(tmp_path, prd_text=text)
    rc = foundry.main(["prd", "--config", str(cfg_path)])
    out = capsys.readouterr().out
    assert rc == 0, f"complete prd returned {rc!r}, expected 0"
    assert "complete: True" in out, f"report missing 'complete: True':\n{out}"


def test_b13_invalid_shape_exit2(tmp_path, capsys):
    # exists but is not valid JSON of the expected shape
    cfg, cfg_path = _cfg_with_prd(tmp_path, prd_text="{not: valid json at all")
    rc = foundry.main(["prd", "--config", str(cfg_path)])
    cap = capsys.readouterr()
    combined = (cap.out + cap.err).lower()
    assert rc == 2, f"invalid prd returned {rc!r}, expected 2"
    assert "invalid" in combined and "json" in combined, (
        f"report did not indicate invalid JSON:\n{cap.out + cap.err}"
    )


# --- Behavior 14 -- CLI writes NO files -------------------------------------
def test_b14_cli_writes_nothing(tmp_path, capsys):
    text = _stories_text([{"id": "S1", "passes": True}, {"id": "S2", "passes": False}])
    cfg, cfg_path = _cfg_with_prd(tmp_path, prd_text=text)
    prd_path = pathlib.Path(cfg.prd)
    before_bytes = prd_path.read_bytes()
    before_repo = _snapshot_tree(cfg.repo)
    before_work = _snapshot_tree(cfg.work_root)

    for _ in range(2):  # run twice to be sure
        foundry.main(["prd", "--config", str(cfg_path)])
        capsys.readouterr()

    assert prd_path.read_bytes() == before_bytes, "cfg.prd was modified by `foundry prd`"
    assert _snapshot_tree(cfg.repo) == before_repo, "`foundry prd` created/changed a file under the repo"
    assert _snapshot_tree(cfg.work_root) == before_work, "`foundry prd` created a file under work_root"


# ==========================================================================
# D. Non-regression (offline)
# ==========================================================================
def test_d_modules_import_and_surface_intact():
    assert foundry is not None
    assert dispatcher is not None
    assert callable(foundry.prd_status)
    assert callable(foundry.prd_status_cli)
    assert hasattr(foundry, "PrdStatus")
    # pre-existing control-flow entry points must remain present + callable
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage"):
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"


def test_d_help_lists_all_subcommands(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for sub in ("run", "once", "doctor", "learnings", "agents", "lint-spec", "prd"):
        assert sub in out, f"subcommand {sub!r} missing from --help:\n{out}"
