"""Black-box behaviour tests for iter 164 -- doctor's FOURTH drift line:
stage-budget HEADROOM to the hard ~600s per-stage agent-CLI cap.

Public surface under test (module level in foundry.py):
  * STAGE_HARD_CAP_SECONDS (600) / STAGE_NEAR_CAP_MARGIN (60)
  * STAGE_BUDGET_PREFIX ("stage-budget:") / STAGE_BUDGET_WARN ("WARN")
  * StageBudgetVerdict            -- frozen, 9 fields + 2 derived properties
  * stage_budget_verdict(summary) -- PURE core
  * stage_budget_line(cfg)        -- one-line formatter, never raises
  * run_doctor_cli(cfg)           -- prints the line once, after roadmap_index_line
  * run_doctor(cfg)               -- still exactly four Checks

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the
iter-164 PM spec's Expected Behaviors 1-15 and Acceptance Criteria, the existing
conventions under tests/ (test_iter117_behavior.py for the stage-times fixture
line shapes, test_iter145_behavior.py for the doctor-CLI stubs and the tmp_path
snapshot helper), the product README / roadmap files the contract allows, and the
product's OWN observable behaviour by importing and CALLING its public names.
The implementation SOURCE of foundry.py was NOT read, nor the engineer's notes,
the reviewer's notes, or any git diff.

OFFLINE + FRESH-CLONE SAFE: no test reads the live (untracked) dispatcher.out.
Every branch is forced either through a scripted `gather_stage_times` seam with
hand-built group stubs, or through the REAL parser pointed at a fixture log built
inside tmp_path.  No subprocess, no git, no network, no clock dependency, and no
assertion on ambient or gitignored tree state -- the only ambient files read are
git-TRACKED ones the Acceptance Criteria name (README.md, the two roadmap files).
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import pathlib
import re
import socket
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

THIS_ITER = 164

README = _ROOT / "README.md"
ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"

# behavior 2 -- the COMPLETE attribute surface, in declaration order.
FIELDS = ["worst_stage", "worst_median", "headroom", "worst_timeouts",
          "worst_count", "near_wall_count", "group_count", "hard_cap", "margin"]
DERIVED = ("has_data", "near_wall")

# The MIDDLE DOT (U+00B7) separator dispatcher's log() emits; BUILT, never
# embedded, so this source file stays pure-ASCII bytes (iter-117 convention).
MID = "\u00b7"


# --------------------------------------------------------------------------
# stubs + helpers
# --------------------------------------------------------------------------
class _G:
    """Group stub carrying exactly the four attributes behavior 1 requires."""

    def __init__(self, stage, median_s, timeouts=0, count=1):
        self.stage = stage
        self.median_s = median_s
        self.timeouts = timeouts
        self.count = count


class _S:
    """Summary stub: any object exposing a `groups` iterable (behavior 1)."""

    def __init__(self, *groups):
        self.groups = tuple(groups)


class _Chk:
    """Minimal stand-in check result for the doctor-CLI guards (iter-145)."""

    def __init__(self, name, ok, detail="detail-text"):
        self.name = name
        self.ok = ok
        self.detail = detail


def _cfg(**over):
    kw = dict(name="demo", repo="/no/such/repo", allowed_push_repo="demo")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _seam(monkeypatch, result, record=None):
    """Script `gather_stage_times` by BARE module name (behavior 11).

    `result` is either the summary to return or an exception INSTANCE to raise.
    """

    def fake(*a, **kw):
        if record is not None:
            record.append((a[0] if a else kw.get("log_path"), kw))
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(foundry, "gather_stage_times", fake)


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


def _forbid_outside_world(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the pure core reached the outside world")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)
    monkeypatch.setattr(socket, "socket", boom)


# ---- real-parser fixture log builders (iter-117 line shapes, MM-DD HH:MM:SS) --
def _start(ts, team, it, stage, attempt):
    return f"- `{ts}` [{team}] iter {it} {MID} **{stage}** attempt {attempt} started"


def _produced(ts, team, it, stage, fname="out.md"):
    return f"- `{ts}` [{team}] iter {it} {MID} {stage} produced `{fname}`"


def _fixture_log(tmp_path, *lines, name="dispatcher.out"):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n")
    return p


def _line(cfg, **kw):
    return foundry.stage_budget_line(cfg, **kw)


# ==========================================================================
# Acceptance criterion -- the four module constants are pinned
# ==========================================================================
def test_ac_constants_exist_with_the_pinned_values():
    assert foundry.STAGE_HARD_CAP_SECONDS == 600
    assert foundry.STAGE_NEAR_CAP_MARGIN == 60
    assert foundry.STAGE_BUDGET_PREFIX == "stage-budget:"
    assert foundry.STAGE_BUDGET_WARN == "WARN"
    for nm in ("STAGE_HARD_CAP_SECONDS", "STAGE_NEAR_CAP_MARGIN"):
        v = getattr(foundry, nm)
        assert isinstance(v, int) and not isinstance(v, bool), nm
    # the iter-117 soft budget is explicitly OUT OF SCOPE and must be untouched
    assert foundry.STAGE_SOFT_BUDGET == 420


def test_ac_public_names_exist_at_module_level():
    for nm in ("StageBudgetVerdict", "stage_budget_verdict", "stage_budget_line"):
        assert hasattr(foundry, nm), nm
    assert callable(foundry.stage_budget_verdict)
    assert callable(foundry.stage_budget_line)


# ==========================================================================
# Behavior 1 -- stage_budget_verdict is PURE and duck-typed on `groups`
# ==========================================================================
def test_b1_verdict_is_pure_no_subprocess_no_socket_no_writes(monkeypatch, tmp_path):
    _forbid_outside_world(monkeypatch)
    before = _snapshot(tmp_path)
    v = foundry.stage_budget_verdict(_S(_G("pm", 300.0, 1, 9), _G("engineer", 590.0, 4, 20)))
    assert v.worst_stage == "engineer"
    assert _snapshot(tmp_path) == before, "the pure core wrote to disk"


def test_b1_accepts_any_object_exposing_groups(monkeypatch):
    """A plain stub, a list-backed `groups`, and a generator-free tuple all work."""
    _forbid_outside_world(monkeypatch)

    class _Loose:
        groups = [_G("tester", 455.0, 2, 12)]

    v = foundry.stage_budget_verdict(_Loose())
    assert (v.worst_stage, v.worst_median, v.worst_timeouts, v.worst_count) == \
        ("tester", 455.0, 2, 12)


def test_b1_integrates_with_the_real_parser_summary(tmp_path):
    """The REAL gather_stage_times summary is a valid input (fixture log only)."""
    p = _fixture_log(
        tmp_path,
        _start("08-05 10:00:00", "alpha", 1, "pm", 1),
        _produced("08-05 10:09:00", "alpha", 1, "pm"),          # 540s
        _start("08-05 11:00:00", "alpha", 2, "engineer", 1),
        _produced("08-05 11:10:00", "alpha", 2, "engineer"),    # 600s
        _start("08-05 12:00:00", "beta", 3, "pm", 1),
        _produced("08-05 12:01:00", "beta", 3, "pm"),           # 60s
    )
    v = foundry.stage_budget_verdict(foundry.gather_stage_times(str(p)))
    assert v.worst_stage == "engineer"
    assert v.worst_median == 600.0 and v.headroom == 0.0
    assert v.group_count == 3
    assert v.near_wall_count == 2   # engineer 0.0s, alpha/pm 60.0s (inclusive)
    assert v.has_data is True and v.near_wall is True


# ==========================================================================
# Behavior 2 -- frozen dataclass, exact attribute surface, 2 derived properties
# ==========================================================================
def test_b2_is_a_frozen_dataclass_with_exactly_nine_fields():
    assert dataclasses.is_dataclass(foundry.StageBudgetVerdict)
    assert foundry.StageBudgetVerdict.__dataclass_params__.frozen is True
    assert [f.name for f in dataclasses.fields(foundry.StageBudgetVerdict)] == FIELDS


def test_b2_attribute_surface_is_exhaustive_and_immutable():
    v = foundry.stage_budget_verdict(_S(_G("pm", 100.0, 3, 7)))
    for nm in list(FIELDS) + list(DERIVED):
        assert hasattr(v, nm), nm
    public = {n for n in dir(v) if not n.startswith("_")}
    assert public == set(FIELDS) | set(DERIVED), \
        "the spec calls this surface exhaustive; extras are undocumented API"
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.headroom = 1.0


def test_b2_derived_booleans_are_properties_on_the_class():
    for nm in DERIVED:
        assert isinstance(getattr(foundry.StageBudgetVerdict, nm), property), nm


def test_b2_has_data_and_near_wall_track_their_counts():
    ok = foundry.stage_budget_verdict(_S(_G("pm", 100.0)))
    assert ok.has_data is True and ok.near_wall is False
    hot = foundry.stage_budget_verdict(_S(_G("pm", 599.0)))
    assert hot.has_data is True and hot.near_wall is True
    empty = foundry.stage_budget_verdict(_S())
    assert empty.has_data is False and empty.near_wall is False


# ==========================================================================
# Behavior 3 -- worst = largest median; headroom = cap - median; ties by name
# ==========================================================================
def test_b3_worst_group_is_the_largest_median_with_its_counts():
    v = foundry.stage_budget_verdict(_S(
        _G("pm", 300.0, 2, 10), _G("engineer", 580.0, 7, 40), _G("final", 120.0, 0, 3)))
    assert v.worst_stage == "engineer"
    assert v.worst_median == 580.0
    assert v.headroom == 20.0 == v.hard_cap - v.worst_median
    assert (v.worst_timeouts, v.worst_count) == (7, 40)


def test_b3_headroom_can_go_negative_past_the_cap():
    v = foundry.stage_budget_verdict(_S(_G("engineer", 640.0, 9, 9)))
    assert v.headroom == -40.0, "a median past the cap must not clamp to zero"
    assert v.near_wall is True


def test_b3_tie_is_broken_deterministically_by_stage_name():
    a = foundry.stage_budget_verdict(_S(_G("zeta", 500.0), _G("alpha", 500.0)))
    b = foundry.stage_budget_verdict(_S(_G("alpha", 500.0), _G("zeta", 500.0)))
    assert a.worst_stage == b.worst_stage, "the tie-break must not depend on input order"
    # Spec says only "deterministically by stage name"; the most reasonable
    # reading of a name-ordered tie-break is the alphabetically FIRST name.
    assert a.worst_stage == "alpha"


# ==========================================================================
# Behavior 4 -- near_wall_count is INCLUSIVE of the margin; group_count totals
# ==========================================================================
def test_b4_near_wall_count_is_margin_inclusive_and_group_count_is_total():
    v = foundry.stage_budget_verdict(_S(
        _G("a", 540.0),    # headroom exactly 60 -> counted (<= margin)
        _G("b", 539.0),    # headroom 61 -> not counted
        _G("c", 600.0),    # headroom 0 -> counted
        _G("d", 10.0)))
    assert v.group_count == 4
    assert v.near_wall_count == 2
    assert v.near_wall is True


def test_b4_no_group_near_the_wall_counts_zero():
    v = foundry.stage_budget_verdict(_S(_G("pm", 100.0), _G("engineer", 200.0)))
    assert (v.group_count, v.near_wall_count) == (2, 0)
    assert v.near_wall is False


# ==========================================================================
# Behavior 5 -- empty groups: all-None worst, zero counts, no raise
# ==========================================================================
def test_b5_empty_groups_yields_a_none_verdict_without_raising():
    for empty in (_S(), type("E", (), {"groups": []})(), type("T", (), {"groups": ()})()):
        v = foundry.stage_budget_verdict(empty)
        assert v.worst_stage is None
        assert v.worst_median is None
        assert v.headroom is None
        assert v.near_wall_count == 0
        assert v.group_count == 0
        assert v.has_data is False
        assert v.near_wall is False
        assert v.hard_cap == foundry.STAGE_HARD_CAP_SECONDS
        assert v.margin == foundry.STAGE_NEAR_CAP_MARGIN


# ==========================================================================
# Behavior 6 -- both globals are read INSIDE the function body
# ==========================================================================
def test_b6_near_cap_margin_global_is_read_at_call_time(monkeypatch):
    groups = _S(_G("pm", 500.0), _G("engineer", 300.0))
    assert foundry.stage_budget_verdict(groups).near_wall_count == 0
    monkeypatch.setattr(foundry, "STAGE_NEAR_CAP_MARGIN", 150)
    v = foundry.stage_budget_verdict(groups)
    assert v.margin == 150
    assert v.near_wall_count == 1 and v.near_wall is True


def test_b6_hard_cap_global_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "STAGE_HARD_CAP_SECONDS", 900)
    v = foundry.stage_budget_verdict(_S(_G("pm", 500.0)))
    assert v.hard_cap == 900
    assert v.headroom == 400.0
    assert v.near_wall is False


def test_b6_globals_are_restored_by_monkeypatch_teardown():
    """Guards the two tests above from leaking a patched budget into the suite."""
    assert foundry.STAGE_HARD_CAP_SECONDS == 600
    assert foundry.STAGE_NEAR_CAP_MARGIN == 60


# ==========================================================================
# Behavior 7 -- the line is always a non-empty SINGLE-line str and never raises
# ==========================================================================
class _NoGroups:
    pass


class _BadGroups:
    groups = 17            # not iterable


class _JunkItems:
    groups = [None, object()]


_ADVERSARIAL = [
    pytest.param(_S(), id="empty-summary"),
    pytest.param(None, id="summary-none"),
    pytest.param(_NoGroups(), id="no-groups-attr"),
    pytest.param(_BadGroups(), id="groups-not-iterable"),
    pytest.param(_JunkItems(), id="junk-group-items"),
    pytest.param(_S(_G("pm", None)), id="median-none"),
    pytest.param(_S(_G("pm", "not-a-number")), id="median-str"),
    pytest.param(_S(_G(None, 500.0)), id="stage-none"),
    pytest.param(_S(_G("pm", float("nan"))), id="median-nan"),
    pytest.param(RuntimeError("boom"), id="gather-raises-runtime"),
    pytest.param(OSError("no such log"), id="gather-raises-oserror"),
    pytest.param(ValueError("undecodable"), id="gather-raises-valueerror"),
]


@pytest.mark.parametrize("result", _ADVERSARIAL)
def test_b7_line_is_one_nonempty_line_and_never_raises(monkeypatch, result):
    _seam(monkeypatch, result)
    out = _line(_cfg())
    assert isinstance(out, str)
    assert out.strip() != ""
    assert "\n" not in out and "\r" not in out
    assert out.startswith(foundry.STAGE_BUDGET_PREFIX)


@pytest.mark.parametrize("cfg", [None, object(), 17, "not-a-cfg"], ids=["none", "object", "int", "str"])
def test_b7_line_survives_a_hostile_cfg(monkeypatch, cfg):
    _seam(monkeypatch, _S(_G("pm", 100.0)))
    out = _line(cfg)
    assert isinstance(out, str) and out.strip() != "" and "\n" not in out
    assert out.startswith(foundry.STAGE_BUDGET_PREFIX)


# ==========================================================================
# Behavior 8 -- the WARN branch names the count, the stage and all four numbers
# ==========================================================================
def test_b8_warn_branch_carries_prefix_token_ratio_and_worst_numbers(monkeypatch):
    _seam(monkeypatch, _S(_G("engineer", 600.0, 11, 86), _G("pm", 300.0, 1, 20)))
    out = _line(_cfg())
    assert out.startswith(foundry.STAGE_BUDGET_PREFIX)
    assert foundry.STAGE_BUDGET_WARN in out
    assert "1/2" in out, "near-wall count OUT OF the group total"
    assert "engineer" in out
    assert "600.0" in out           # worst median
    assert "0.0" in out             # headroom
    assert re.search(r"(?<![0-9])11(?![0-9])", out), "worst timeouts"
    assert re.search(r"(?<![0-9])86(?![0-9])", out), "worst attempt count"
    assert "600" in out             # the hard cap is named


def test_b8_warn_fires_at_the_margin_boundary(monkeypatch):
    _seam(monkeypatch, _S(_G("pm", 540.0, 0, 4)))
    out = _line(_cfg())
    assert foundry.STAGE_BUDGET_WARN in out
    assert "1/1" in out


# ==========================================================================
# Behavior 9 -- the OK branch still names the worst stage, and never says WARN
# ==========================================================================
def test_b9_ok_branch_reports_the_worst_stage_without_warning(monkeypatch):
    _seam(monkeypatch, _S(_G("pm", 100.0, 0, 5), _G("final", 90.0, 0, 5)))
    out = _line(_cfg())
    assert out.startswith(foundry.STAGE_BUDGET_PREFIX)
    assert "OK" in out
    assert foundry.STAGE_BUDGET_WARN not in out
    assert "pm" in out
    assert "100.0" in out          # median
    assert "500.0" in out          # headroom
    assert "UNKNOWN" not in out


# ==========================================================================
# Behavior 10 -- the UNKNOWN branch claims nothing, via the seam AND for real
# ==========================================================================
@pytest.mark.parametrize("result", [
    pytest.param(_S(), id="no-groups"),
    pytest.param(RuntimeError("boom"), id="gather-raises"),
    pytest.param(_NoGroups(), id="degenerate-summary"),
    pytest.param(None, id="summary-none"),
])
def test_b10_unknown_branch_via_the_seam(monkeypatch, result):
    _seam(monkeypatch, result)
    out = _line(_cfg())
    assert out.startswith(foundry.STAGE_BUDGET_PREFIX)
    assert "UNKNOWN" in out
    assert foundry.STAGE_BUDGET_WARN not in out
    assert "OK" not in out, "the UNKNOWN branch must claim nothing about the budget"


def test_b10_unknown_for_real_against_the_actual_parser(tmp_path):
    """The steady state in a FRESH CLONE, where dispatcher.out does not exist.

    Proven against the REAL parser (no seam): a seam-mocked UNKNOWN only proves
    the formatter, while the deployment case is the parser meeting a log that is
    missing, empty, undecodable, a directory, or all about another team.
    """
    missing = tmp_path / "nope" / "dispatcher.out"

    empty = tmp_path / "empty.out"
    empty.write_text("")

    undecodable = tmp_path / "binary.out"
    undecodable.write_bytes(b"\xff\xfe\x00\x01 not utf-8 \xc3\x28")

    a_dir = tmp_path / "a_dir.out"
    a_dir.mkdir()

    other_team = _fixture_log(
        tmp_path,
        _start("08-05 10:00:00", "someone-else", 1, "pm", 1),
        _produced("08-05 10:09:00", "someone-else", 1, "pm"),
        name="other.out")

    noise = tmp_path / "noise.out"
    noise.write_text("not a dispatcher log at all\njust prose\n")

    for p in (missing, empty, undecodable, a_dir, other_team, noise):
        out = _line(_cfg(), log_path=str(p))
        assert out.startswith(foundry.STAGE_BUDGET_PREFIX), p.name
        assert "UNKNOWN" in out, (p.name, out)
        assert foundry.STAGE_BUDGET_WARN not in out, (p.name, out)
        assert "\n" not in out, p.name


def test_b10_real_parser_end_to_end_warns_on_a_hot_fixture_log(tmp_path):
    """The same real path, this time WITH data for cfg.name -> a real WARN."""
    p = _fixture_log(
        tmp_path,
        _start("08-05 10:00:00", "demo", 1, "engineer", 1),
        _produced("08-05 10:10:00", "demo", 1, "engineer"),      # 600s
        _start("08-05 11:00:00", "demo", 2, "final", 1),
        _produced("08-05 11:01:00", "demo", 2, "final"),         # 60s
        _start("08-05 12:00:00", "other", 3, "pm", 1),
        _produced("08-05 12:09:30", "other", 3, "pm"),           # other team: ignored
    )
    out = _line(_cfg(), log_path=str(p))
    assert foundry.STAGE_BUDGET_WARN in out
    assert "engineer" in out and "600.0" in out
    assert "1/2" in out, "the other team's group must be filtered out (behavior 11)"
    assert "\n" not in out


# ==========================================================================
# Behavior 11 -- the seam is called by BARE name with team=cfg.name
# ==========================================================================
def test_b11_gather_is_called_once_by_bare_name_with_the_team(monkeypatch):
    rec = []
    _seam(monkeypatch, _S(_G("pm", 100.0)), rec)
    _line(_cfg(name="alpha"))
    assert len(rec) == 1, "exactly one parser call per line"
    assert rec[0][1].get("team") == "alpha"


def test_b11_a_raising_gather_yields_unknown_not_an_exception(monkeypatch):
    _seam(monkeypatch, RuntimeError("parser exploded"))
    out = _line(_cfg())
    assert "UNKNOWN" in out and foundry.STAGE_BUDGET_WARN not in out


# ==========================================================================
# Behavior 12 -- writes NOTHING; default log path is FOUNDRY / dispatcher.out
# ==========================================================================
def test_b12_default_log_path_is_the_foundry_dispatcher_out(monkeypatch):
    rec = []
    _seam(monkeypatch, _S(_G("pm", 100.0)), rec)
    _line(_cfg())
    assert pathlib.Path(rec[0][0]) == foundry.FOUNDRY / "dispatcher.out"


def test_b12_an_explicit_log_path_is_forwarded_to_the_parser(monkeypatch, tmp_path):
    """Hermeticity precondition for the real-parser tests above: if the override
    were ignored they would silently read the live log and pass for the wrong
    reason."""
    rec = []
    _seam(monkeypatch, _S(_G("pm", 100.0)), rec)
    target = tmp_path / "elsewhere.out"
    _line(_cfg(), log_path=str(target))
    assert pathlib.Path(rec[0][0]) == target


def test_b12_line_writes_nothing_to_disk(tmp_path):
    p = _fixture_log(
        tmp_path,
        _start("08-05 10:00:00", "demo", 1, "engineer", 1),
        _produced("08-05 10:10:00", "demo", 1, "engineer"))
    before = _snapshot(tmp_path)
    _line(_cfg(), log_path=str(p))
    _line(_cfg(), log_path=str(tmp_path / "does-not-exist.out"))
    assert _snapshot(tmp_path) == before, "stage_budget_line touched the filesystem"


# ==========================================================================
# Behaviors 13/14 -- run_doctor_cli prints it ONCE, after roadmap_index_line,
# under its own belt, and its exit code is unchanged by the verdict
# ==========================================================================
def _stub_checks(monkeypatch, *, fail=None):
    for nm in ("power", "agent", "uv", "remote"):
        monkeypatch.setattr(
            foundry, f"check_{nm}",
            lambda *a, _n=nm, **k: _Chk(_n, _n != fail))


def _patch_lag(monkeypatch):
    """Script live_lag_line's upstream seams so NO test reads the live log."""
    monkeypatch.setattr(foundry, "parse_brain_launch", lambda *a, **k: 1000.0)
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: ((1, 900.0),))


def _doctor_cfg(tmp_path, text="# roadmap\n\nsome prose\n"):
    p = tmp_path / "IDX.md"
    p.write_text(text)
    return _cfg(roadmap=str(p), learnings=str(tmp_path / "no-such-learnings.md"))


def _doctor_out(cfg):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.run_doctor_cli(cfg)
    return rc, buf.getvalue()


def _budget_lines(out):
    return [ln for ln in out.splitlines()
            if ln.startswith(foundry.STAGE_BUDGET_PREFIX)]


def _first_index(out, prefix):
    lines = out.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith(prefix):
            return i
    return -1


def test_b13_doctor_prints_the_line_exactly_once(monkeypatch, tmp_path):
    _stub_checks(monkeypatch)
    _patch_lag(monkeypatch)
    _seam(monkeypatch, _S(_G("engineer", 600.0, 11, 86), _G("pm", 100.0, 0, 9)))
    rc, out = _doctor_out(_doctor_cfg(tmp_path))
    assert len(_budget_lines(out)) == 1, out
    assert rc == 0


def test_b13_the_line_comes_after_the_roadmap_index_line(monkeypatch, tmp_path):
    _stub_checks(monkeypatch)
    _patch_lag(monkeypatch)
    _seam(monkeypatch, _S(_G("pm", 100.0, 0, 9)))
    rc, out = _doctor_out(_doctor_cfg(tmp_path))
    idx = _first_index(out, foundry.ROADMAP_INDEX_PREFIX)
    bud = _first_index(out, foundry.STAGE_BUDGET_PREFIX)
    assert idx >= 0, "the third drift line vanished"
    assert bud > idx, "the fourth line must print AFTER the roadmap-index line"


def test_b13_doctor_calls_the_helper_by_bare_name(monkeypatch, tmp_path):
    """The pedal exists: doctor prints whatever the module-level seam returns."""
    _stub_checks(monkeypatch)
    _patch_lag(monkeypatch)
    sentinel = foundry.STAGE_BUDGET_PREFIX + " SENTINEL-iter164-marker"
    monkeypatch.setattr(foundry, "stage_budget_line", lambda *a, **k: sentinel)
    rc, out = _doctor_out(_doctor_cfg(tmp_path))
    assert sentinel in out.splitlines()
    assert rc == 0


def test_b13_a_raising_helper_degrades_to_unknown_and_does_not_abort(monkeypatch, tmp_path):
    _stub_checks(monkeypatch)
    _patch_lag(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("helper exploded")

    monkeypatch.setattr(foundry, "stage_budget_line", boom)
    rc, out = _doctor_out(_doctor_cfg(tmp_path))
    lines = _budget_lines(out)
    assert len(lines) == 1, out
    assert "UNKNOWN" in lines[0]
    assert foundry.STAGE_BUDGET_WARN not in lines[0]
    assert rc == 0, "the belt must not change doctor's exit code"
    # the three older drift lines still printed -> doctor did not abort early
    assert _first_index(out, foundry.ROADMAP_INDEX_PREFIX) >= 0


def test_b14_exit_code_is_unchanged_by_a_warning_line(monkeypatch, tmp_path):
    _stub_checks(monkeypatch)
    _patch_lag(monkeypatch)
    cfg = _doctor_cfg(tmp_path)

    _seam(monkeypatch, _S(_G("engineer", 600.0, 11, 86)))
    rc_warn, out_warn = _doctor_out(cfg)
    assert foundry.STAGE_BUDGET_WARN in _budget_lines(out_warn)[0]

    _seam(monkeypatch, _S(_G("pm", 10.0, 0, 3)))
    rc_ok, out_ok = _doctor_out(cfg)
    assert "OK" in _budget_lines(out_ok)[0]

    _seam(monkeypatch, RuntimeError("boom"))
    rc_unknown, out_unknown = _doctor_out(cfg)
    assert "UNKNOWN" in _budget_lines(out_unknown)[0]

    assert rc_warn == rc_ok == rc_unknown == 0


def test_b14_a_failing_check_still_drives_the_exit_code(monkeypatch, tmp_path):
    """The line is ADVISORY: the four checks alone decide doctor's verdict."""
    _stub_checks(monkeypatch, fail="uv")
    _patch_lag(monkeypatch)
    _seam(monkeypatch, _S(_G("pm", 10.0, 0, 3)))       # an OK line
    rc, out = _doctor_out(_doctor_cfg(tmp_path))
    assert rc != 0
    assert len(_budget_lines(out)) == 1


# ==========================================================================
# Behavior 15 -- run_doctor still returns exactly four Checks
# ==========================================================================
def test_b15_run_doctor_still_returns_exactly_four_checks(monkeypatch, tmp_path):
    _stub_checks(monkeypatch)
    checks = foundry.run_doctor(_doctor_cfg(tmp_path))
    assert len(list(checks)) == 4, "this iteration adds no Check"
    for c in checks:
        assert hasattr(c, "name") and hasattr(c, "ok")
    assert [c.name for c in checks] == ["power", "agent", "uv", "remote"]


def test_b15_out_of_scope_stage_times_surface_is_untouched():
    """The line is a second READER of the iter-117 parser, never a change to it."""
    for nm in ("parse_stage_attempts", "summarize_stage_times", "gather_stage_times",
               "stage_times_cli"):
        assert hasattr(foundry, nm), nm


# ==========================================================================
# Acceptance criteria -- README entry #47 and the two roadmap records
# ==========================================================================
def test_ac_readme_documents_the_fourth_drift_line_as_entry_47():
    text = README.read_text()
    m = re.search(r"^# 47\. (.*)$", text, re.M)
    assert m, "README has no `# 47.` entry"
    block = text[m.start():m.start() + 4000].lower()
    assert "doctor" in block
    assert "fourth" in block or "4th" in block
    assert foundry.STAGE_BUDGET_PREFIX in text[m.start():m.start() + 4000]
    assert "600" in block, "the entry must name the hard cap it prices"


def test_ac_roadmap_done_ledger_row_is_present_and_short():
    rows = [ln for ln in ROADMAP.read_text().splitlines()
            if re.match(r"^- iter 164 -- ", ln)]
    assert len(rows) == 1, rows
    assert len(rows[0]) <= 120, f"ledger row is {len(rows[0])} chars"


def test_ac_roadmap_archive_carries_the_verbatim_detail_bullet():
    bullets = [ln for ln in ARCHIVE.read_text().splitlines()
               if ln.startswith("- **iter 164 ")]
    assert len(bullets) == 1, bullets
    assert len(bullets[0]) > 400, "the archive bullet is the unbounded detail record"


def test_ac_roadmap_item_p_carries_the_refreshed_measurement():
    text = ROADMAP.read_text()
    assert "48 CLI verbs" in text, "item (p) still carries the stale 46-verb figure"
    assert "TWO absent" in text
    assert "new-product" in text and "preship" in text
    assert "46 CLI verbs" not in text


# ==========================================================================
# Regression -- the three OLDER drift lines survive the fourth
# ==========================================================================
def test_reg_all_four_drift_lines_print_exactly_once_each(monkeypatch, tmp_path):
    """Adding a fourth line must not cost the three that were already there.

    Two prior test modules were re-baselined for this iteration, so the
    "three drift lines" invariant they pinned is re-asserted here from the
    OBSERVABLE doctor output, at the new count of four.
    """
    _stub_checks(monkeypatch)
    _patch_lag(monkeypatch)
    _seam(monkeypatch, _S(_G("pm", 100.0, 0, 9)))
    rc, out = _doctor_out(_doctor_cfg(tmp_path))
    assert rc == 0
    prefixes = (foundry.LIVE_LAG_PREFIX, foundry.LEARNINGS_HEAD_PREFIX,
                foundry.ROADMAP_INDEX_PREFIX, foundry.STAGE_BUDGET_PREFIX)
    lines = out.splitlines()
    for pref in prefixes:
        hits = [ln for ln in lines if ln.startswith(pref)]
        assert len(hits) == 1, (pref, out)
    order = [_first_index(out, p) for p in prefixes]
    assert order == sorted(order), \
        "the fourth line must be LAST: %r" % (order,)
# ==========================================================================
# Acceptance criterion -- doctor's own docstring announces FOUR drift lines
# (RE-RUN addition: the criterion "its docstring is updated from THREE drift
# lines to FOUR" had no test. Asserted by RUNTIME INTROSPECTION of a public
# attribute, never by reading the implementation source -- the same idiom
# tests/test_iter162_behavior.py uses for its dormancy claim.)
# ==========================================================================
def test_ac_run_doctor_cli_docstring_announces_four_drift_lines():
    doc = foundry.run_doctor_cli.__doc__ or ""
    assert doc.strip(), "run_doctor_cli lost its docstring"
    assert re.search(r"(?i)\bfour\b", doc), \
        "docstring does not announce FOUR drift lines: %r" % doc[:200]
    assert not re.search(r"(?i)\bthree\b", doc), \
        "docstring still claims THREE drift lines: %r" % doc[:200]
    assert str(THIS_ITER) in doc, \
        "docstring does not attribute the fourth line to iter 164"
