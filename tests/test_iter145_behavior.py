"""Black-box behaviour tests for iter 145 -- the roadmap-index wall becomes ONE
module-level global, a pure total verdict reports headroom against it, and
`foundry doctor` grows a THIRD advisory drift line.

Spec: products/_platform/state/iter-145/pm.md, Expected Behaviors 1-11.

  ROADMAP_INDEX_HARD_CHARS / ROADMAP_INDEX_NEAR_WALL_CHARS
  1.  both are module-level ints pinned at 54000 / 3000, and the hard-wall
      assertion messages in the LIVE brakes name ARCHIVING as the remedy rather
      than raising the budget.
  roadmap_index_budget(text) -- pure, total
  2.  returns a FROZEN dataclass carrying exactly six fields, with char_count /
      hard_budget / near_wall_margin / headroom derived from the globals; every
      field is read-only.
  3.  THE DISCRIMINATING CLAUSE: the boundary is INCLUSIVE (>=), so a text of
      exactly the budget is already over -- 9 / 10 / 11 chars against a patched
      budget of 10 give False / True / True. A strictly-greater boundary would be
      off by one against the live brake, which asserts `len(index) < HARD`.
  4.  both globals are read AT CALL TIME: patching either one changes a later
      call's verdict with no re-import.
  5.  near_wall is True iff not over_budget and 0 <= headroom <= margin, and the
      two flags are MUTUALLY EXCLUSIVE across a full sweep of the boundary.
  6.  total and I/O-free: "" and a huge text and multibyte text never raise, and
      a run under a tmp cwd leaves that tree byte-identical (files-as-bytes map
      PLUS the directory set).
  roadmap_index_line(cfg) -- the one-line reporter
  7.  exactly ONE non-empty line, never None, always prefixed, never raising,
      with three distinct outcomes: UNKNOWN (empty / missing / unreadable /
      directory path -- and NO WARN token, because "I cannot tell" is not
      evidence), OK (headroom > margin, carries count + headroom), WARN (near or
      over -- carries the token, count, headroom and the word "archive").
  8.  it composes roadmap_index_budget by its BARE module name, so a scripted
      stand-in forces WARN, forces OK, and a RAISING stand-in degrades to UNKNOWN.
  doctor surface
  9.  run_doctor_cli prints the line as an ADDITIONAL drift line and its exit code
      is UNCHANGED by it (0 on all-pass even when the line WARNs; 1 on one failing
      check even when the line reads OK); a RAISING line helper cannot crash it;
      run_doctor still returns exactly four Checks [power, agent, uv, remote].
  single source of truth
  10. two-sided: the live iter-140 / iter-141 wall assertions PASS at the real
      value and STILL FAIL with the global patched below the live index size, so
      the value-preserving edit did not hollow the brake.
  11. the live roadmap files record iteration 145 exactly once each and the index
      is under the wall (derived, never a pinned char count).
  Plus AC oracles: the new names are DORMANT on the control path, and README
  documents the third line without still claiming there are two.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-145 PM spec and the
product's own OBSERVABLE surface -- importing the module, CALLING its public
functions, reading `dataclasses.fields` / `__doc__`, driving the doctor CLI, and
reading files under `tests/` for CONVENTIONS plus the product README and roadmap
files (both explicitly allowed, and both are the SUBJECT of behaviors 10/11).
The implementation BODIES of foundry.py / dispatcher.py, the engineer's notes,
the reviewer's notes and `git diff` were NOT read. The dormancy oracle uses
`inspect.getsource` as an automated MATCHER (the convention iter-141 established)
without the source being read by the author.

Fully offline and deterministic: synthetic strings and `tmp_path` files only --
no subprocess, no git, no network, no sleep, no clock dependence, and nothing
written outside `tmp_path`. The live-lag seams are scripted in every doctor test
so no test reads the live `dispatcher.out`.
"""
import contextlib
import dataclasses
import inspect
import io
import os
import pathlib
import re
import stat
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tests"))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

import test_iter140_behavior as t140  # noqa: E402  (behavior 10, two-sided)
import test_iter141_behavior as t141  # noqa: E402  (behavior 10, two-sided)

THIS_ITER = 145
FIELDS = ["char_count", "hard_budget", "near_wall_margin",
          "headroom", "over_budget", "near_wall"]


# --------------------------------------------------------------------------
# helpers -- mirror the suite's existing conventions
# --------------------------------------------------------------------------
class _Chk:
    """Minimal stand-in check result for the doctor-CLI guards."""

    def __init__(self, name, ok, detail="detail-text"):
        self.name = name
        self.ok = ok
        self.detail = detail


def _cfg(**over):
    kw = dict(name="demo", repo="/no/such/repo", allowed_push_repo="demo")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _roadmap_cfg(tmp_path, text, *, name="IDX.md"):
    p = tmp_path / name
    p.write_text(text)
    return _cfg(roadmap=str(p), learnings=str(tmp_path / "no-such-learnings.md"))


def _stub_checks(monkeypatch, *, fail=None):
    for nm in ("power", "agent", "uv", "remote"):
        monkeypatch.setattr(
            foundry, f"check_{nm}",
            lambda *a, _n=nm, **k: _Chk(_n, _n != fail))


def _patch_lag(monkeypatch):
    """Script live_lag_line's upstream seams so NO test reads the live log."""
    monkeypatch.setattr(foundry, "parse_brain_launch", lambda *a, **k: 1000.0)
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: ((1, 900.0),))


def _doctor_out(cfg):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.run_doctor_cli(cfg)
    return rc, buf.getvalue()


def _index_lines(out):
    return [ln for ln in out.splitlines()
            if ln.startswith(foundry.ROADMAP_INDEX_PREFIX)]


def _snapshot(root):
    """(files-as-bytes, directory set) -- the pair a purity claim needs."""
    files, dirs = {}, set()
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_dir():
            dirs.add(rel)
        else:
            files[rel] = p.read_bytes()
    return files, dirs


# --------------------------------------------------------------------- Behavior 1
def test_b1_hard_and_near_wall_globals_are_pinned_ints():
    assert isinstance(foundry.ROADMAP_INDEX_HARD_CHARS, int) and \
        not isinstance(foundry.ROADMAP_INDEX_HARD_CHARS, bool)
    assert foundry.ROADMAP_INDEX_HARD_CHARS == 54000, \
        "the wall is PINNED: a red suite is paid down by ARCHIVING, not by raising it"
    assert isinstance(foundry.ROADMAP_INDEX_NEAR_WALL_CHARS, int) and \
        not isinstance(foundry.ROADMAP_INDEX_NEAR_WALL_CHARS, bool)
    assert foundry.ROADMAP_INDEX_NEAR_WALL_CHARS == 3000


def test_b1_live_brake_messages_name_archiving_as_the_remedy():
    """The escape hatch this iteration closes is 'raise the budget'; both live
    brakes must SAY so in the message the failing PM actually reads."""
    for mod, fn in ((t140, "test_b10_index_is_under_the_declared_budget"),
                    (t141, "test_ac_roadmap_records_this_iteration_in_both_files")):
        src = inspect.getsource(getattr(mod, fn))
        low = src.lower()
        assert "archive" in low, f"{mod.__name__}.{fn} does not name archiving"
        assert "not the remedy" in low, \
            f"{mod.__name__}.{fn} does not warn against raising the budget"


# --------------------------------------------------------------------- Behavior 2
def test_b2_result_is_a_frozen_dataclass_with_exactly_six_fields():
    v = foundry.roadmap_index_budget("abc")
    assert dataclasses.is_dataclass(v), type(v)
    assert [f.name for f in dataclasses.fields(v)] == FIELDS, \
        [f.name for f in dataclasses.fields(v)]
    assert type(v).__dataclass_params__.frozen is True


def test_b2_derived_fields_follow_the_globals():
    for text in ("", "abc", "x" * 5000, "e\u0301\u4e2d\u6587" * 40):
        v = foundry.roadmap_index_budget(text)
        assert v.char_count == len(text), (v, len(text))
        assert v.hard_budget == foundry.ROADMAP_INDEX_HARD_CHARS, v
        assert v.near_wall_margin == foundry.ROADMAP_INDEX_NEAR_WALL_CHARS, v
        assert v.headroom == v.hard_budget - v.char_count, v


@pytest.mark.parametrize("field", FIELDS)
def test_b2_every_field_is_read_only(field):
    v = foundry.roadmap_index_budget("abc")
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(v, field, 1)


# --------------------------------------------------------------------- Behavior 3
@pytest.mark.parametrize("n,expected", [(9, False), (10, True), (11, True)])
def test_b3_over_budget_boundary_is_inclusive(monkeypatch, n, expected):
    """The live brake asserts `len(index) < HARD`, so exactly HARD is ALREADY bad.
    A strictly-greater boundary (as the older smell verdict uses) would report OK
    on the very size that reverts the iteration."""
    monkeypatch.setattr(foundry, "ROADMAP_INDEX_HARD_CHARS", 10)
    monkeypatch.setattr(foundry, "ROADMAP_INDEX_NEAR_WALL_CHARS", 0)
    v = foundry.roadmap_index_budget("x" * n)
    assert v.over_budget is expected, (n, v)


def test_b3_boundary_agrees_with_the_live_brake_for_every_size(monkeypatch):
    """Cross-check against the brake's own predicate, not against a second copy
    of the threshold: over_budget must be exactly `not (len < HARD)`."""
    monkeypatch.setattr(foundry, "ROADMAP_INDEX_HARD_CHARS", 40)
    monkeypatch.setattr(foundry, "ROADMAP_INDEX_NEAR_WALL_CHARS", 5)
    for n in range(0, 60):
        v = foundry.roadmap_index_budget("x" * n)
        assert v.over_budget is (not (n < 40)), (n, v)


# --------------------------------------------------------------------- Behavior 4
def test_b4_hard_budget_is_read_at_call_time(monkeypatch):
    text = "x" * 100
    before = foundry.roadmap_index_budget(text)
    monkeypatch.setattr(foundry, "ROADMAP_INDEX_HARD_CHARS", 50)
    after = foundry.roadmap_index_budget(text)
    assert before.hard_budget == 54000 and after.hard_budget == 50, (before, after)
    assert before.headroom != after.headroom, (before, after)
    assert before.over_budget is False and after.over_budget is True, (before, after)


def test_b4_near_wall_margin_is_read_at_call_time(monkeypatch):
    text = "x" * (foundry.ROADMAP_INDEX_HARD_CHARS - 4000)
    before = foundry.roadmap_index_budget(text)
    assert before.near_wall_margin == 3000 and before.near_wall is False, before
    monkeypatch.setattr(foundry, "ROADMAP_INDEX_NEAR_WALL_CHARS", 5000)
    after = foundry.roadmap_index_budget(text)
    assert after.near_wall_margin == 5000, after
    assert after.near_wall is True, "margin was captured at def-time, not read live"


def test_b4_neither_global_is_a_default_argument():
    """A default argument would freeze the value at def-time even though a later
    patch of the global appears to work through some other path."""
    sig = inspect.signature(foundry.roadmap_index_budget)
    assert list(sig.parameters) == ["text"], sig
    for p in sig.parameters.values():
        assert p.default is inspect.Parameter.empty, sig


# --------------------------------------------------------------------- Behavior 5
def test_b5_near_wall_definition_and_mutual_exclusion(monkeypatch):
    monkeypatch.setattr(foundry, "ROADMAP_INDEX_HARD_CHARS", 100)
    monkeypatch.setattr(foundry, "ROADMAP_INDEX_NEAR_WALL_CHARS", 20)
    seen = set()
    for n in range(0, 130):
        v = foundry.roadmap_index_budget("x" * n)
        assert not (v.over_budget and v.near_wall), \
            f"both flags True at {n} chars -- the three outcomes are ambiguous: {v}"
        assert v.near_wall is ((not v.over_budget)
                               and 0 <= v.headroom <= v.near_wall_margin), (n, v)
        seen.add((v.over_budget, v.near_wall))
    assert seen == {(False, False), (False, True), (True, False)}, seen


# --------------------------------------------------------------------- Behavior 6
def test_b6_empty_text_is_full_headroom():
    v = foundry.roadmap_index_budget("")
    assert v.char_count == 0
    assert v.headroom == v.hard_budget
    assert v.over_budget is False and v.near_wall is False


@pytest.mark.parametrize("text", [
    "",
    "x",
    "x" * (54000 * 2),
    "\u4e2d\u6587 \U0001f600 caf\u00e9\n" * 500,
    "\n\n\n",
    "\x00binary-ish\x01",
])
def test_b6_total_never_raises(text):
    v = foundry.roadmap_index_budget(text)
    assert v.char_count == len(text)


def test_b6_performs_no_io(monkeypatch, tmp_path):
    """Snapshot is anchored AFTER any setup that legitimately writes -- there is
    none here, the function takes only a str -- and covers the directory set too,
    so a created-but-empty dir cannot slip through."""
    (tmp_path / "seed").mkdir()
    (tmp_path / "seed" / "a.txt").write_text("keep me")
    monkeypatch.chdir(tmp_path)
    before = _snapshot(tmp_path)
    for text in ("", "x" * 90000, "\u4e2d" * 10):
        foundry.roadmap_index_budget(text)
    assert _snapshot(tmp_path) == before, "the pure verdict touched the tmp tree"


# --------------------------------------------------------------------- Behavior 7
def test_b7_unknown_when_path_is_empty(tmp_path):
    line = foundry.roadmap_index_line(_cfg(roadmap=""))
    assert isinstance(line, str) and line.strip()
    assert line.startswith(foundry.ROADMAP_INDEX_PREFIX), line
    assert "UNKNOWN" in line, line
    assert foundry.ROADMAP_INDEX_WARN not in line, \
        f"'I cannot tell' must never be reported as a problem: {line!r}"


def test_b7_unknown_when_path_is_missing(tmp_path):
    line = foundry.roadmap_index_line(_cfg(roadmap=str(tmp_path / "nope.md")))
    assert "UNKNOWN" in line and foundry.ROADMAP_INDEX_WARN not in line, line


def test_b7_unknown_when_path_is_a_directory(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    line = foundry.roadmap_index_line(_cfg(roadmap=str(d)))
    assert "UNKNOWN" in line and foundry.ROADMAP_INDEX_WARN not in line, line


def test_b7_unknown_when_file_is_unreadable(tmp_path):
    p = tmp_path / "locked.md"
    p.write_text("x" * 100)
    p.chmod(0o000)
    try:
        if os.access(str(p), os.R_OK):        # running as root -- premise gone
            pytest.skip("cannot make a file unreadable in this environment")
        line = foundry.roadmap_index_line(_cfg(roadmap=str(p)))
    finally:
        p.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert "UNKNOWN" in line and foundry.ROADMAP_INDEX_WARN not in line, line


def test_b7_ok_when_headroom_exceeds_the_margin(tmp_path):
    cfg = _roadmap_cfg(tmp_path, "x" * 10)
    line = foundry.roadmap_index_line(cfg)
    assert line.startswith(foundry.ROADMAP_INDEX_PREFIX), line
    assert "OK" in line and foundry.ROADMAP_INDEX_WARN not in line, line
    assert "10" in line, f"char count missing: {line!r}"
    assert str(foundry.ROADMAP_INDEX_HARD_CHARS - 10) in line, \
        f"headroom missing: {line!r}"


@pytest.mark.parametrize("size,label", [(54000 - 100, "near"), (54000 + 500, "over")])
def test_b7_warn_when_near_or_over(tmp_path, size, label):
    cfg = _roadmap_cfg(tmp_path, "x" * size)
    line = foundry.roadmap_index_line(cfg)
    assert foundry.ROADMAP_INDEX_WARN in line, f"{label}: no WARN in {line!r}"
    assert str(size) in line, f"{label}: char count missing: {line!r}"
    assert str(foundry.ROADMAP_INDEX_HARD_CHARS - size) in line, \
        f"{label}: headroom missing: {line!r}"
    assert "archive" in line.lower(), f"{label}: remedy not named: {line!r}"


@pytest.mark.parametrize("size", [0, 10, 54000 - 1, 54000, 54000 + 5000])
def test_b7_always_exactly_one_non_empty_line(tmp_path, size):
    line = foundry.roadmap_index_line(_roadmap_cfg(tmp_path, "x" * size))
    assert line is not None
    assert isinstance(line, str) and line.strip()
    assert "\n" not in line.rstrip("\n"), f"embedded newline: {line!r}"
    assert len(line.rstrip("\n").splitlines()) == 1, line
    assert line.startswith(foundry.ROADMAP_INDEX_PREFIX), line


def test_b7_three_outcomes_are_distinct_strings(tmp_path):
    ok = foundry.roadmap_index_line(_roadmap_cfg(tmp_path, "x" * 10, name="a.md"))
    warn = foundry.roadmap_index_line(
        _roadmap_cfg(tmp_path, "x" * 53999, name="b.md"))
    unknown = foundry.roadmap_index_line(_cfg(roadmap=""))
    assert len({ok, warn, unknown}) == 3, (ok, warn, unknown)


# --------------------------------------------------------------------- Behavior 8
# The real verdict is captured at IMPORT time so a scripted stand-in built by
# `_fake` cannot recurse into the very seam the test just replaced.
_RESULT_TYPE = type(foundry.roadmap_index_budget(""))


def _fake(over=False, near=False, count=123, hard=54000, margin=3000):
    """A scripted verdict, constructed WITHOUT calling the (patched) seam."""
    return _RESULT_TYPE(char_count=count, hard_budget=hard,
                        near_wall_margin=margin, headroom=hard - count,
                        over_budget=over, near_wall=near)


def test_b8_scripted_stand_in_forces_warn(monkeypatch, tmp_path):
    cfg = _roadmap_cfg(tmp_path, "x" * 10)          # a genuinely tiny file
    monkeypatch.setattr(foundry, "roadmap_index_budget",
                        lambda text: _fake(over=True, count=99999))
    line = foundry.roadmap_index_line(cfg)
    assert foundry.ROADMAP_INDEX_WARN in line, \
        f"the stand-in did not bite -- not called by BARE module name: {line!r}"
    assert "99999" in line, line


def test_b8_scripted_stand_in_forces_ok(monkeypatch, tmp_path):
    cfg = _roadmap_cfg(tmp_path, "x" * 53999)       # a genuinely huge file
    monkeypatch.setattr(foundry, "roadmap_index_budget",
                        lambda text: _fake(count=7))
    line = foundry.roadmap_index_line(cfg)
    assert "OK" in line and foundry.ROADMAP_INDEX_WARN not in line, \
        f"the stand-in did not bite: {line!r}"


def test_b8_scripted_near_wall_stand_in_warns(monkeypatch, tmp_path):
    cfg = _roadmap_cfg(tmp_path, "x" * 10)
    monkeypatch.setattr(foundry, "roadmap_index_budget",
                        lambda text: _fake(near=True, count=53500))
    line = foundry.roadmap_index_line(cfg)
    assert foundry.ROADMAP_INDEX_WARN in line and "archive" in line.lower(), line


def test_b8_raising_stand_in_degrades_to_unknown(monkeypatch, tmp_path):
    cfg = _roadmap_cfg(tmp_path, "x" * 10)

    def boom(text):
        raise RuntimeError("scripted internal failure")

    monkeypatch.setattr(foundry, "roadmap_index_budget", boom)
    line = foundry.roadmap_index_line(cfg)
    assert isinstance(line, str) and line.strip()
    assert line.startswith(foundry.ROADMAP_INDEX_PREFIX), line
    assert "UNKNOWN" in line, f"an internal failure must degrade to UNKNOWN: {line!r}"
    assert foundry.ROADMAP_INDEX_WARN not in line, line


# --------------------------------------------------------------------- Behavior 9
def test_b9_doctor_prints_the_line_exactly_once(monkeypatch, tmp_path):
    _stub_checks(monkeypatch)
    _patch_lag(monkeypatch)
    rc, out = _doctor_out(_roadmap_cfg(tmp_path, "x" * 10))
    assert len(_index_lines(out)) == 1, out
    assert rc == 0


def test_b9_exit_stays_0_when_the_line_warns(monkeypatch, tmp_path):
    _stub_checks(monkeypatch)
    _patch_lag(monkeypatch)
    rc, out = _doctor_out(_roadmap_cfg(tmp_path, "x" * (54000 + 100)))
    assert _index_lines(out) and foundry.ROADMAP_INDEX_WARN in _index_lines(out)[0]
    assert rc == 0, f"an advisory drift line changed the exit code: rc={rc}\n{out}"


def test_b9_exit_stays_1_when_a_check_fails_and_the_line_is_ok(monkeypatch, tmp_path):
    _stub_checks(monkeypatch, fail="uv")
    _patch_lag(monkeypatch)
    rc, out = _doctor_out(_roadmap_cfg(tmp_path, "x" * 10))
    assert _index_lines(out) and "OK" in _index_lines(out)[0]
    assert rc == 1, f"a failing check must still exit 1: rc={rc}\n{out}"


def test_b9_four_check_lines_survive_the_new_line(monkeypatch, tmp_path):
    _stub_checks(monkeypatch)
    _patch_lag(monkeypatch)
    rc, out = _doctor_out(_roadmap_cfg(tmp_path, "x" * (54000 + 100)))
    for name in ("power", "agent", "uv", "remote"):
        assert name in out, f"doctor lost its {name} check:\n{out}"


def test_b9_a_raising_line_helper_cannot_crash_the_preflight(monkeypatch, tmp_path):
    _stub_checks(monkeypatch)
    _patch_lag(monkeypatch)

    def boom(cfg):
        raise RuntimeError("scripted line-helper failure")

    monkeypatch.setattr(foundry, "roadmap_index_line", boom)
    rc, out = _doctor_out(_roadmap_cfg(tmp_path, "x" * 10))
    assert rc == 0, f"a raising drift line broke the preflight: rc={rc}\n{out}"
    for name in ("power", "agent", "uv", "remote"):
        assert name in out, out


def test_b9_run_doctor_still_returns_exactly_four_checks(monkeypatch, tmp_path):
    _stub_checks(monkeypatch)
    checks = foundry.run_doctor(_roadmap_cfg(tmp_path, "x" * (54000 + 100)))
    assert [c.name for c in checks] == ["power", "agent", "uv", "remote"], \
        [c.name for c in checks]


def test_b9_the_new_line_is_not_a_check_and_not_in_json(monkeypatch, tmp_path):
    """Out of scope: the line may not leak into the machine payload."""
    _stub_checks(monkeypatch)
    checks = foundry.run_doctor(_roadmap_cfg(tmp_path, "x" * (54000 + 100)))
    blob = " ".join(f"{c.name} {c.ok} {getattr(c, 'detail', '')}" for c in checks)
    assert foundry.ROADMAP_INDEX_PREFIX not in blob, blob


# -------------------------------------------------------------------- Behavior 10
def test_b10_live_wall_assertions_pass_at_the_real_value():
    t140.test_b10_index_is_under_the_declared_budget()
    t141.test_ac_roadmap_records_this_iteration_in_both_files()


def test_b10_live_wall_assertions_still_fail_when_the_wall_is_lowered(monkeypatch):
    """A value-preserving 'single source of truth' edit is unfalsifiable by a green
    suite -- the assert could have been hollowed into `size < size`. Patch the
    global BELOW the live index size: both brakes must still bite."""
    live = len((_ROOT / "PLATFORM_ROADMAP.md").read_text())
    monkeypatch.setattr(foundry, "ROADMAP_INDEX_HARD_CHARS", 1000)
    assert live > 1000, "premise gone: the live index is smaller than the patch"
    with pytest.raises(AssertionError):
        t140.test_b10_index_is_under_the_declared_budget()
    with pytest.raises(AssertionError):
        t141.test_ac_roadmap_records_this_iteration_in_both_files()


def test_b10_no_bare_wall_literal_remains_in_either_brake():
    for mod in (t140, t141):
        src = pathlib.Path(inspect.getfile(mod)).read_text()
        assert "54000" not in src, \
            f"{mod.__name__} still hardcodes the wall instead of deriving it"
        assert "ROADMAP_INDEX_HARD_CHARS" in src, \
            f"{mod.__name__} does not derive the wall from the global"


# -------------------------------------------------------------------- Behavior 11
def test_b11_live_index_is_under_the_wall_and_records_this_iteration():
    index = (_ROOT / "PLATFORM_ROADMAP.md").read_text()
    archive = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text()
    assert len(index) < foundry.ROADMAP_INDEX_HARD_CHARS, (
        "PLATFORM_ROADMAP.md is %d chars, wall is < %d -- ARCHIVE spent prose; "
        "raising ROADMAP_INDEX_HARD_CHARS is NOT the remedy"
        % (len(index), foundry.ROADMAP_INDEX_HARD_CHARS))
    rows = [ln for ln in index.splitlines()
            if ln.startswith(f"- iter {THIS_ITER} ")]
    assert len(rows) == 1, f"expected one iter-{THIS_ITER} ledger row, got {rows}"
    assert len(rows[0]) <= 120, f"ledger row must stay terse: {len(rows[0])} chars"
    bullets = [ln for ln in archive.splitlines()
               if ln.startswith(f"- **iter {THIS_ITER} ")]
    assert len(bullets) == 1, \
        f"expected one iter-{THIS_ITER} archive bullet, got {bullets}"


# ------------------------------------------------------- acceptance-criteria oracles
NEW_NAMES = ("ROADMAP_INDEX_HARD_CHARS", "ROADMAP_INDEX_NEAR_WALL_CHARS",
             "roadmap_index_budget", "roadmap_index_line", "RoadmapIndexBudget",
             "ROADMAP_INDEX_PREFIX", "ROADMAP_INDEX_WARN")


@pytest.mark.parametrize("fn", ["run_iteration", "run_stage", "build_prompt"])
def test_ac_dormant_on_the_control_path(fn):
    src = inspect.getsource(getattr(foundry, fn))
    assert len(src) > 200, f"{fn} source looks empty -- the oracle would be vacuous"
    hits = [n for n in NEW_NAMES if n in src]
    assert hits == [], f"{fn} is on the control path and must not call {hits}"


def test_ac_dispatcher_has_no_call_site():
    src = (_ROOT / "dispatcher.py").read_text()
    assert len(src) > 1000, "dispatcher.py looks empty -- the oracle would be vacuous"
    hits = [n for n in NEW_NAMES if n in src]
    assert hits == [], f"dispatcher.py must stay byte-unchanged, found {hits}"


def test_ac_the_only_new_call_site_is_the_doctor_verb():
    src = inspect.getsource(foundry.run_doctor_cli)
    assert "roadmap_index_line" in src, \
        "the pedal is missing: run_doctor_cli does not call the line helper"
    src_doctor = inspect.getsource(foundry.run_doctor)
    assert not any(n in src_doctor for n in NEW_NAMES), \
        "run_doctor itself must be untouched (its 4-Check shape is pinned)"


def test_ac_older_smell_verdict_is_untouched():
    assert foundry.ROADMAP_SIZE_WARN_CHARS == 60000
    v = foundry.roadmap_size_verdict("x" * 10)
    assert v.budget == foundry.ROADMAP_SIZE_WARN_CHARS, v
    assert foundry.ROADMAP_SIZE_WARN_CHARS != foundry.ROADMAP_INDEX_HARD_CHARS, \
        "the smell threshold and the hard wall are different questions"


def test_ac_readme_documents_the_third_line():
    txt = (_ROOT / "README.md").read_text()
    # ADVANCED iter 164: doctor grew a FOURTH drift line, so the count word this
    # test pins moves with it. The invariant is unchanged -- the README announces
    # the CURRENT number of drift lines and never a stale one.
    assert re.search(r"(?i)\bfour drift lines\b", txt), \
        "README does not announce four drift lines"
    assert not re.search(r"(?i)\bthree drift lines\b", txt), \
        "README still claims there are three drift lines"
    assert foundry.ROADMAP_INDEX_PREFIX.rstrip(":") in txt
    assert "ROADMAP_INDEX_HARD_CHARS" in txt
    assert re.search(r"(?i)drift line ever changes doctor.s own exit code", txt), \
        "README dropped the exit-code guarantee for the drift lines"
    assert re.search(r"(?i)exactly four\s+Check", txt), \
        "README dropped the exactly-four-Checks guarantee"
