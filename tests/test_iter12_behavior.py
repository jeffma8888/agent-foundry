"""Black-box behaviour tests for iter 12 -- wiring the pure `prd_status` parser
into the dispatcher as a DIAGNOSTIC per-shift progress line via a new pure
`foundry.dispatch_progress_line(cfg) -> str | None` helper (bite 2a of roadmap
item 1: REPORTING ONLY -- no control-flow / stop-semantics change).

ISOLATION CONTRACT (honored): these tests are written from the PM spec's
Expected Behaviors (1-9) and the product's own observable behaviour ONLY. The
implementation source of `foundry.py`/`dispatcher.py`, the engineer's and
reviewer's notes, and `git diff` were NOT read while authoring these tests.
Every check drives the PUBLIC surface: the pure helper via
`foundry.dispatch_progress_line(cfg)`, config resolution via
`foundry.load_config(...)`, and cross-checks recompute expected values with the
public `foundry.prd_status(...)`. The one structural behavior (9) is asserted
PROGRAMMATICALLY at runtime via `inspect.getsource` of the named public
functions / the dispatcher module -- encoding the spec's stated diagnostic-only
wiring contract, not any implementation quirk. Fully offline & deterministic:
real temp files only, NO subprocess/git/network/agent-run. The helper is driven
with a tmp product config whose `prd` points at a tmp file (or a nonexistent /
directory path) -- the real repo / real product configs are NEVER used.
"""
import inspect
import json
import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers -- synthetic prd JSON text + tmp configs (never the real repo)
# --------------------------------------------------------------------------
def _stories_text(stories, wrap=False):
    """JSON text for a story list. wrap=True -> {"stories": [...]}; else bare []."""
    return json.dumps({"stories": stories} if wrap else stories)


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


def _cfg_with_prd(tmp_path, prd_text=None, prd_name="prd.json", **over):
    """Config whose `prd` points at <repo>/<prd_name>; optionally seed that prd
    file with `prd_text` (None -> file absent). Returns the loaded ProductConfig."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    prd_path = repo / prd_name
    cfg_path = _write_cfg(tmp_path, prd=str(prd_path), **over)
    if prd_text is not None:
        prd_path.write_text(prd_text)
    return foundry.load_config(str(cfg_path))


def _snapshot_tree(root):
    """Map {relative-path: bytes} for every file under root (for no-write proof)."""
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }


# ==========================================================================
# Behavior 1 -- missing prd.json -> None (state of every current product)
# ==========================================================================
def test_b01_missing_prd_returns_none(tmp_path):
    cfg = _cfg_with_prd(tmp_path, prd_text=None)          # prd file absent
    assert not pathlib.Path(cfg.prd).exists(), "precondition: prd file must be absent"
    assert foundry.dispatch_progress_line(cfg) is None, (
        "missing cfg.prd must yield None (dispatcher logs no extra line today)"
    )


def test_b01_default_prd_path_absent_returns_none(tmp_path):
    # a config that never mentions prd -> default <repo>/prd.json, which is absent
    cfg_path = _write_cfg(tmp_path)
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    cfg = foundry.load_config(str(cfg_path))
    assert foundry.dispatch_progress_line(cfg) is None


# ==========================================================================
# Behavior 2 -- valid + >=1 pending -> "{name}: {p}/{t} stories pass (in progress)"
# ==========================================================================
def test_b02_pending_in_progress_bare_array(tmp_path):
    text = _stories_text([{"passes": True}, {"passes": False}, {"passes": False}])
    cfg = _cfg_with_prd(tmp_path, prd_text=text, name="demo")
    assert foundry.dispatch_progress_line(cfg) == "demo: 1/3 stories pass (in progress)"


def test_b02_pending_in_progress_wrapped_shape_equivalent(tmp_path):
    stories = [{"passes": True}, {"passes": False}, {"passes": False}]
    cfg = _cfg_with_prd(tmp_path, prd_text=_stories_text(stories, wrap=True), name="demo")
    # {"stories": [...]} must behave identically to the bare array
    assert foundry.dispatch_progress_line(cfg) == "demo: 1/3 stories pass (in progress)"


def test_b02_name_is_interpolated(tmp_path):
    text = _stories_text([{"passes": True}, {"passes": False}])
    cfg = _cfg_with_prd(tmp_path, prd_text=text, name="widgets")
    assert foundry.dispatch_progress_line(cfg) == "widgets: 1/2 stories pass (in progress)"


# ==========================================================================
# Behavior 3 -- all pass -> "{name}: {p}/{t} stories pass (COMPLETE)"
# ==========================================================================
def test_b03_all_pass_complete(tmp_path):
    text = _stories_text([{"passes": True}, {"passes": 1}, {"passes": True}])
    cfg = _cfg_with_prd(tmp_path, prd_text=text, name="demo")
    assert foundry.dispatch_progress_line(cfg) == "demo: 3/3 stories pass (COMPLETE)"


def test_b03_single_passing_story_complete(tmp_path):
    cfg = _cfg_with_prd(tmp_path, prd_text=_stories_text([{"passes": True}]), name="demo")
    assert foundry.dispatch_progress_line(cfg) == "demo: 1/1 stories pass (COMPLETE)"


# ==========================================================================
# Behavior 4 -- valid but empty -> "{name}: 0/0 stories pass (in progress)"
# ==========================================================================
def test_b04_valid_but_empty_in_progress(tmp_path):
    cfg = _cfg_with_prd(tmp_path, prd_text=_stories_text([]), name="demo")
    # total==0 is NOT complete (per PrdStatus.complete), so tag is (in progress)
    assert foundry.dispatch_progress_line(cfg) == "demo: 0/0 stories pass (in progress)"


# ==========================================================================
# Behavior 5 -- present but unparseable -> flagged, not silent
# ==========================================================================
@pytest.mark.parametrize("bad", ["not json", "42", "{}", "{not: valid json at all"])
def test_b05_present_but_unparseable_flagged(tmp_path, bad):
    cfg = _cfg_with_prd(tmp_path, prd_text=bad, name="demo")
    assert pathlib.Path(cfg.prd).exists(), "precondition: prd file must EXIST"
    line = foundry.dispatch_progress_line(cfg)
    assert line == "demo: prd.json present but unparseable", (
        f"unparseable prd should be flagged exactly, got {line!r}"
    )
    # the operator sees a problem -- and it is NOT dressed up as a progress line
    assert "stories pass" not in line, (
        f"unparseable message must not contain 'stories pass', got {line!r}"
    )


def test_b05_does_not_crash_on_unparseable(tmp_path):
    # a valid-JSON-but-wrong-shape ({} has no `stories` key) is unparseable, and
    # the helper must NOT raise while flagging it
    cfg = _cfg_with_prd(tmp_path, prd_text="{}", name="demo")
    line = foundry.dispatch_progress_line(cfg)  # must not raise
    assert line == "demo: prd.json present but unparseable"


# ==========================================================================
# Behavior 6 -- never raises; directory / weird cfg -> None
# ==========================================================================
def test_b06_prd_is_a_directory_returns_none(tmp_path):
    # cfg.prd points at a DIRECTORY, not a file -> unexpected -> None, no raise
    cfg = _cfg_with_prd(tmp_path, prd_text=None)
    pathlib.Path(cfg.prd).mkdir(parents=True, exist_ok=True)
    assert pathlib.Path(cfg.prd).is_dir()
    assert foundry.dispatch_progress_line(cfg) is None


def test_b06_never_raises_across_input_matrix(tmp_path):
    # exercise every category in one sweep and assert NONE raises, and each
    # returns either None or a str (never anything else, never an exception)
    cases = [
        None,                                             # missing file
        _stories_text([]),                                # valid empty
        _stories_text([{"passes": True}]),                # complete
        _stories_text([{"passes": True}, {"passes": False}]),  # pending
        _stories_text([{"passes": True}], wrap=True),     # wrapped complete
        "not json", "42", "{}", "[1, 2, 3]",              # invalid / non-object array
    ]
    for i, txt in enumerate(cases):
        sub = tmp_path / f"c{i}"
        sub.mkdir()
        cfg = _cfg_with_prd(sub, prd_text=txt, name="demo")
        try:
            r = foundry.dispatch_progress_line(cfg)
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"dispatch_progress_line raised on case {txt!r}: {e!r}")
        assert r is None or isinstance(r, str), f"case {txt!r} returned {r!r}"


# ==========================================================================
# Behavior 7 -- writes nothing
# ==========================================================================
def test_b07_writes_nothing(tmp_path):
    text = _stories_text([{"id": "S1", "passes": True}, {"id": "S2", "passes": False}])
    cfg = _cfg_with_prd(tmp_path, prd_text=text, name="demo")
    prd_path = pathlib.Path(cfg.prd)
    before_bytes = prd_path.read_bytes()
    before_repo = _snapshot_tree(cfg.repo)
    before_work = _snapshot_tree(cfg.work_root)

    for _ in range(3):  # any number of calls
        foundry.dispatch_progress_line(cfg)

    assert prd_path.read_bytes() == before_bytes, "cfg.prd was modified by the helper"
    assert _snapshot_tree(cfg.repo) == before_repo, "helper created/changed a file under the repo"
    assert _snapshot_tree(cfg.work_root) == before_work, "helper created a file under work_root"


# ==========================================================================
# Behavior 8 -- counts match prd_status (single source of truth)
# ==========================================================================
@pytest.mark.parametrize("stories", [
    [{"passes": True}, {"passes": False}, {"passes": False}, {"passes": False}, {"passes": False}],
    [{"passes": True}, {"passes": True}],
    [{"passes": True}, {"passes": False}, {"passes": 1}, {"id": "x"}],
    [],
])
def test_b08_counts_match_prd_status(tmp_path, stories):
    text = _stories_text(stories)
    st = foundry.prd_status(text)                 # public single source of truth
    cfg = _cfg_with_prd(tmp_path, prd_text=text, name="demo")
    line = foundry.dispatch_progress_line(cfg)
    # the summary produced by prd_status must appear verbatim in the line
    assert st.summary in line, f"line {line!r} missing prd_status summary {st.summary!r}"
    # and the embedded P/T numbers must equal prd_status.passed / .total exactly
    m = re.search(r"(\d+)/(\d+) stories pass", line)
    assert m, f"no 'P/T stories pass' fragment in {line!r}"
    assert (int(m.group(1)), int(m.group(2))) == (st.passed, st.total), (
        f"line counts {m.group(1)}/{m.group(2)} != prd_status {st.passed}/{st.total}"
    )
    # tag correctness ties back to prd_status.complete
    tag = "(COMPLETE)" if st.complete else "(in progress)"
    assert line.endswith(tag), f"line {line!r} should end with {tag!r} (complete={st.complete})"


# ==========================================================================
# Behavior 9 -- wiring exists, diagnostic-only, invariants intact (structural)
# ==========================================================================
def test_b09_modules_importable_and_helper_public():
    assert foundry is not None and dispatcher is not None
    assert callable(foundry.dispatch_progress_line)


def test_b09_dispatcher_references_the_helper():
    src = inspect.getsource(dispatcher)
    assert "foundry.dispatch_progress_line" in src, (
        "dispatcher.py must reference foundry.dispatch_progress_line (the per-shift "
        "reporting hook)"
    )


def test_b09_helper_is_off_the_control_path():
    # diagnostic-only: none of the loop-control entry points may reference it
    for fn in (foundry.run_iteration, foundry.run_continuous,
               foundry.run_stage, foundry.build_prompt):
        src = inspect.getsource(fn)
        assert "dispatch_progress_line" not in src, (
            f"foundry.{fn.__name__} references dispatch_progress_line -- it must be "
            f"diagnostic-only and OFF the control path"
        )


def test_b09_preexisting_control_flow_surface_intact():
    for name in ("build_prompt", "run_iteration", "run_continuous", "run_stage",
                 "prd_status", "prd_status_cli", "load_config"):
        assert callable(getattr(foundry, name)), f"foundry.{name} missing/not callable (regression)"
    assert hasattr(foundry, "PrdStatus")


def test_b09_iteration_numbering_and_layout_unchanged(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    assert foundry.next_iteration(cfg) == 1
    (cfg.state / "iter-03").mkdir(parents=True)
    (cfg.state / "iter-09").mkdir(parents=True)
    assert foundry.next_iteration(cfg) == 10
    assert cfg.state == pathlib.Path(cfg.work_root) / "state"


def test_b09_help_still_lists_all_subcommands(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for sub in ("run", "once", "doctor", "learnings", "agents", "lint-spec", "prd"):
        assert sub in out, f"subcommand {sub!r} missing from --help:\n{out}"
