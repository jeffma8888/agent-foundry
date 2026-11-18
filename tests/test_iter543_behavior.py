"""Black-box behaviour tests for iter 543 -- `revert_repo` flags the current
iteration's approved + tested tree with `state/iter-N/RESUMABLE.md` right after
capturing ABORTED_IMPLEMENTATION.patch, via the swallow-safe module-level seam
`flag_resumable_after_revert(cfg)`.

ISOLATION CONTRACT (honored): written solely from the iter-543 PM spec's
Expected Behaviors (1-12), the README, the conventions under `tests/` and the
product's OBSERVABLE runtime interface (public names, CLI output).  The
implementation source, the engineer's/reviewer's notes and `git diff` were not
read.

Fully offline: every config and state dir is built under tmp_path; `git` and
`log` are scripted seams, so no real reset/clean ever runs.  No commit sha,
line number or ambient products/*/state path is asserted.
"""
import io
import json
import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import foundry  # noqa: E402

PATCH = "ABORTED_IMPLEMENTATION.patch"
FLAG = "RESUMABLE.md"
PARK = "PARKED.md"
APPROVE = "Review notes.\n\nVERDICT: APPROVE\n"
CHANGES = "Review notes.\n\nVERDICT: REQUEST_CHANGES\n"
PASS = "Tests ok.\n\nRESULT: PASS\n"
FAIL = "Tests red.\n\nRESULT: FAIL\n"
PUSHED = "Shipped.\n\nACTION: PUSHED abc123\n"
REVERTED = "Gate said no.\n\nACTION: REVERTED blocking finding\n"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, name="demoprod", roadmap=None):
    base = pathlib.Path(tmp_path) / name
    base.mkdir(parents=True, exist_ok=True)
    data = {
        "name": name,
        "repo": str(base / "repo"),
        "allowed_push_repo": name,
        "vision": str(base / "VISION.md"),
        "work_root": str(base / "work"),
    }
    if roadmap is not None:
        data["roadmap"] = roadmap
    p = base / "config.json"
    p.write_text(json.dumps(data))
    return p, base / "work"


def _load(cfg_path):
    return foundry.load_config(str(cfg_path))


def _iter_dir(work, name, files):
    d = work / "state" / name
    d.mkdir(parents=True, exist_ok=True)
    for fname, text in files.items():
        (d / fname).write_text(text)
    return d


def _candidate_files(**extra):
    files = {PATCH: "diff --git a/x b/x\n", "reviewer.md": APPROVE, "tester.md": PASS}
    files.update(extra)
    return files


def _capture(fn, *a, **k):
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        try:
            rc = fn(*a, **k)
        except SystemExit as e:
            rc = e.code
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _seams(monkeypatch, events=None):
    """Scripted git + log recorders sharing one event list."""
    events = [] if events is None else events

    def fake_git(cfg, *args, **kw):
        flags = sorted(p.name for p in pathlib.Path(cfg.state).rglob(FLAG)) \
            if pathlib.Path(cfg.state).exists() else []
        events.append(("git", tuple(args), tuple(flags)))
        return ""

    monkeypatch.setattr(foundry, "git", fake_git)
    monkeypatch.setattr(foundry, "log", lambda cfg, msg: events.append(("log", msg)))
    return events


def _gits(events):
    return [e[1] for e in events if e[0] == "git"]


def _logs(events):
    return [e[1] for e in events if e[0] == "log"]


def _flags(work):
    st = work / "state"
    return sorted(str(p.relative_to(st)) for p in st.rglob(FLAG)) if st.exists() else []


def _row_for(cfg, n):
    rows = [r for r in foundry.gather_resumable(cfg).rows if r.iteration == n]
    assert len(rows) == 1, rows
    return rows[0]


def _roadmap_name(cfg):
    return pathlib.Path(getattr(cfg, "roadmap", "") or "").name or "PLATFORM_ROADMAP.md"


def _boom(*a, **k):
    raise RuntimeError("seam raised on purpose")


@pytest.fixture
def b1(tmp_path):
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-7", _candidate_files())
    return cfg_path, work, _load(cfg_path)


# --------------------------------------------------------------------------
# Behavior 1 -- candidate newest dir gets RESUMABLE.md, byte-exact
# --------------------------------------------------------------------------
def test_b1_revert_writes_flag_byte_exact(b1, monkeypatch):
    cfg_path, work, cfg = b1
    expected = foundry.render_resumable_flag(_row_for(cfg, 7), _roadmap_name(cfg))
    _seams(monkeypatch)
    assert foundry.revert_repo(cfg, "final stage failed") is None
    flag = work / "state" / "iter-7" / FLAG
    assert flag.is_file(), _flags(work)
    text = flag.read_text()
    assert text == expected
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[-1] == "RESUMABLE: iter-7"
    assert "state/iter-7/ABORTED_IMPLEMENTATION.patch" in text
    assert str(work) not in text


def test_b1_resumable_verb_lists_flagged(b1, monkeypatch):
    cfg_path, work, cfg = b1
    _seams(monkeypatch)
    rc0, out0, _ = _capture(foundry.main, ["resumable", "--config", str(cfg_path)])
    assert "[flagged]" not in out0
    foundry.revert_repo(cfg, "final stage failed")
    rc, out, err = _capture(foundry.main, ["resumable", "--config", str(cfg_path)])
    hits = [ln for ln in out.splitlines() if ln.startswith("iter-7  ")]
    assert len(hits) == 1, out
    assert hits[0].endswith("  [flagged]"), hits[0]


def test_b1_roadmap_basename_from_config(tmp_path, monkeypatch):
    cfg_path, work = _write_cfg(tmp_path, roadmap=str(tmp_path / "proj" / "PRODUCT.md"))
    _iter_dir(work, "iter-7", _candidate_files())
    cfg = _load(cfg_path)
    expected = foundry.render_resumable_flag(_row_for(cfg, 7), "PRODUCT.md")
    _seams(monkeypatch)
    foundry.revert_repo(cfg, "final stage failed")
    assert (work / "state" / "iter-7" / FLAG).read_text() == expected


# --------------------------------------------------------------------------
# Behavior 2 -- reset/clean order unchanged, after the flag; log lines
# --------------------------------------------------------------------------
def test_b2_git_order_and_logs(b1, monkeypatch):
    cfg_path, work, cfg = b1
    events = _seams(monkeypatch)
    foundry.revert_repo(cfg, "final stage failed")
    branch = cfg.branch
    gits = [e for e in events if e[0] == "git"]
    calls = [g[1] for g in gits]
    reset = ("reset", "--hard", "origin/%s" % branch)
    assert reset in calls and ("clean", "-fd") in calls, calls
    assert calls.index(reset) < calls.index(("clean", "-fd"))
    # the flag already existed on disk when reset ran
    reset_ev = gits[calls.index(reset)]
    assert FLAG in reset_ev[2], reset_ev
    logs = _logs(events)
    assert logs[-1] == "repo reverted to origin/%s (final stage failed)" % branch, logs
    flag_logs = [i for i, m in enumerate(logs[:-1]) if "state/iter-7/RESUMABLE.md" in m]
    assert flag_logs, logs


# --------------------------------------------------------------------------
# Behavior 3 -- explicit ship decision: no flag
# --------------------------------------------------------------------------
@pytest.mark.parametrize("final", [REVERTED, PUSHED], ids=["reverted", "pushed"])
def test_b3_ship_decision_writes_nothing(tmp_path, monkeypatch, final):
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-7", _candidate_files(**{"final.md": final}))
    cfg = _load(cfg_path)
    events = _seams(monkeypatch)
    foundry.revert_repo(cfg, "r")
    assert _flags(work) == []
    assert not any(FLAG in m for m in _logs(events))
    assert ("clean", "-fd") in _gits(events)


# --------------------------------------------------------------------------
# Behavior 4 -- non-candidates
# --------------------------------------------------------------------------
NON_CANDIDATES = {
    "no-patch": lambda: {k: v for k, v in _candidate_files().items() if k != PATCH},
    "request-changes": lambda: _candidate_files(**{"reviewer.md": CHANGES}),
    "tester-fail": lambda: _candidate_files(**{"tester.md": FAIL}),
    "no-tester": lambda: {k: v for k, v in _candidate_files().items() if k != "tester.md"},
}


@pytest.mark.parametrize("key", sorted(NON_CANDIDATES))
def test_b4_non_candidate_writes_nothing(tmp_path, monkeypatch, key):
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-7", NON_CANDIDATES[key]())
    cfg = _load(cfg_path)
    events = _seams(monkeypatch)
    foundry.revert_repo(cfg, "r")
    assert _flags(work) == []
    assert not any(FLAG in m for m in _logs(events))


# --------------------------------------------------------------------------
# Behavior 5 -- parked
# --------------------------------------------------------------------------
def test_b5_parked_writes_nothing(tmp_path, monkeypatch):
    cfg_path, work = _write_cfg(tmp_path)
    d = _iter_dir(work, "iter-7", _candidate_files(**{PARK: "re-land keeps failing\n"}))
    before = (d / PARK).read_bytes()
    cfg = _load(cfg_path)
    _seams(monkeypatch)
    foundry.revert_repo(cfg, "r")
    assert _flags(work) == []
    assert (d / PARK).read_bytes() == before


# --------------------------------------------------------------------------
# Behavior 6 -- already flagged: bytes kept, no log
# --------------------------------------------------------------------------
def test_b6_existing_flag_untouched(tmp_path, monkeypatch):
    cfg_path, work = _write_cfg(tmp_path)
    operator = b"operator note \xe2\x9c\x93\nkeep me\n"
    d = _iter_dir(work, "iter-7", _candidate_files())
    (d / FLAG).write_bytes(operator)
    cfg = _load(cfg_path)
    events = _seams(monkeypatch)
    foundry.revert_repo(cfg, "r")
    assert (d / FLAG).read_bytes() == operator
    assert not any("RESUMABLE" in m for m in _logs(events)), _logs(events)


# --------------------------------------------------------------------------
# Behavior 7 -- only the newest dir
# --------------------------------------------------------------------------
def test_b7_older_candidate_not_backfilled(tmp_path, monkeypatch):
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-3", _candidate_files())
    _iter_dir(work, "iter-8", {"reviewer.md": CHANGES})
    cfg = _load(cfg_path)
    assert _row_for(cfg, 3).open  # precondition: iter-3 is a real open row
    _seams(monkeypatch)
    foundry.revert_repo(cfg, "r")
    assert _flags(work) == []


def test_b7_newest_candidate_only(tmp_path, monkeypatch):
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-3", _candidate_files())
    _iter_dir(work, "iter-8", _candidate_files())
    cfg = _load(cfg_path)
    _seams(monkeypatch)
    foundry.revert_repo(cfg, "r")
    assert _flags(work) == ["iter-8/" + FLAG]


def test_b7_numeric_not_lexical_newest(tmp_path, monkeypatch):
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-9", _candidate_files())
    _iter_dir(work, "iter-10", _candidate_files())
    cfg = _load(cfg_path)
    _seams(monkeypatch)
    foundry.revert_repo(cfg, "r")
    assert _flags(work) == ["iter-10/" + FLAG]


# --------------------------------------------------------------------------
# Behavior 8 -- swallow-safe
# --------------------------------------------------------------------------
@pytest.mark.parametrize("seam", ["flag_resumable_after_revert", "write_resumable_flag",
                                  "gather_resumable"])
def test_b8_raising_seam_does_not_stop_revert(b1, monkeypatch, seam):
    cfg_path, work, cfg = b1
    events = _seams(monkeypatch)
    monkeypatch.setattr(foundry, seam, _boom)
    assert foundry.revert_repo(cfg, "boom") is None
    calls = _gits(events)
    reset = ("reset", "--hard", "origin/%s" % cfg.branch)
    assert reset in calls and ("clean", "-fd") in calls
    assert calls.index(reset) < calls.index(("clean", "-fd"))
    assert _logs(events)[-1] == "repo reverted to origin/%s (boom)" % cfg.branch
    assert _flags(work) == []


def test_b8_missing_state_dir_returns_none(tmp_path, monkeypatch):
    cfg_path, work = _write_cfg(tmp_path)
    cfg = _load(cfg_path)
    _seams(monkeypatch)
    assert not (work / "state").exists() or not any((work / "state").iterdir())
    assert foundry.flag_resumable_after_revert(cfg) is None


def test_b8_no_iter_dirs_returns_none(tmp_path, monkeypatch):
    cfg_path, work = _write_cfg(tmp_path)
    (work / "state" / "notes").mkdir(parents=True)
    cfg = _load(cfg_path)
    _seams(monkeypatch)
    assert foundry.flag_resumable_after_revert(cfg) is None
    assert _flags(work) == []


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root ignores directory permissions")
def test_b8_unwritable_target_returns_none(b1, monkeypatch):
    cfg_path, work, cfg = b1
    _seams(monkeypatch)
    d = work / "state" / "iter-7"
    os.chmod(d, 0o500)
    try:
        assert foundry.flag_resumable_after_revert(cfg) is None
    finally:
        os.chmod(d, 0o755)
    assert not (d / FLAG).exists()


# --------------------------------------------------------------------------
# Behavior 9 -- bare-name seam, ordering
# --------------------------------------------------------------------------
def test_b9_spy_called_once_between_capture_and_reset(b1, monkeypatch):
    cfg_path, work, cfg = b1
    events = _seams(monkeypatch)
    monkeypatch.setattr(foundry, "capture_abort_patch",
                        lambda c, r: events.append(("capture", r)))
    monkeypatch.setattr(foundry, "flag_resumable_after_revert",
                        lambda c: events.append(("flag", c)))
    foundry.revert_repo(cfg, "r1")
    flags = [e for e in events if e[0] == "flag"]
    assert len(flags) == 1 and flags[0][1] is cfg, events
    kinds = [e[0] if e[0] != "git" else e[1][0] for e in events]
    assert kinds.index("capture") < kinds.index("flag") < kinds.index("reset"), kinds
    foundry.revert_repo(cfg, "r2")
    assert len([e for e in events if e[0] == "flag"]) == 2


# --------------------------------------------------------------------------
# Behavior 10 -- direct call: Path then None
# --------------------------------------------------------------------------
def test_b10_direct_call_idempotent(b1, monkeypatch):
    cfg_path, work, cfg = b1
    _seams(monkeypatch)
    got = foundry.flag_resumable_after_revert(cfg)
    assert isinstance(got, pathlib.Path), got
    assert got == work / "state" / "iter-7" / FLAG or got.resolve() == (
        work / "state" / "iter-7" / FLAG).resolve()
    before = got.read_bytes()
    assert foundry.flag_resumable_after_revert(cfg) is None
    assert got.read_bytes() == before


# --------------------------------------------------------------------------
# Behavior 11 -- importable (pins are enforced by test_iter541 b9 / test_iter512 b7)
# --------------------------------------------------------------------------
def test_b11_import_foundry_and_dispatcher():
    proc = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                          cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr


# --------------------------------------------------------------------------
# Behavior 12 -- README #68 sentence; stale comment gone
# --------------------------------------------------------------------------
def _readme_68():
    text = (REPO / "README.md").read_text()
    lines = [ln for ln in text.splitlines() if ln.startswith("# 68.")]
    assert lines, "README has no # 68. section"
    return " ".join(lines)


def test_b12_readme_68_mentions_pipeline_flag():
    sec = _readme_68()
    assert "revert_repo" in sec
    assert "RESUMABLE.md" in sec
    assert "pipeline" in sec.lower()


def test_b12_stale_comment_removed():
    assert "CLI-only today" not in (REPO / "foundry.py").read_text()
