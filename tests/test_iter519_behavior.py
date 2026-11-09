"""Iteration 519 -- BLACK-BOX behavior tests: every `dispatcher.out` reader goes
through two module-level seams, `dispatcher_log_path(log_path=None)` (defaulting
resolver) and `read_dispatcher_log(log_path)` (non-defaulting, UTF-8
errors="replace", never raises), so one undecodable byte no longer splits the
doctor lenses (live-lag / drain-arm / stage-times / stage-budget / inflight).

ISOLATION CONTRACT (honored): written from the iter-519 PM spec's Expected
Behaviors 1-8, existing fixture conventions under tests/ (test_iter164,
test_iter209, test_iter240, test_iter518) and the product's observable
behaviour only. The implementation source, engineer/reviewer notes and
`git diff` were NOT read.

OFFLINE + FRESH-CLONE SAFE: every log lives under tmp_path; `git_ship_commits`
is monkeypatched wherever live-lag runs; no subprocess, no git, no network, and
no assertion on the ambient (gitignored) dispatcher.out.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import sys
import textwrap

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402,F401  (EB8 import-safety probe)

MID = "\u00b7"  # dispatcher's log() separator, built not embedded
BANNER = "- `11-08 13:56:52` dispatcher up; teams=2 concurrency=1\n"
BAD_LINE = b"- `11-08 13:57:00` tail: 'agent said caf\xe9'\n"
BINARY = b"\xff\xfe\x00\x01 not utf-8 \xc3\x28"
NOW = "09-06 10:00:30"
# The default log name, assembled so this file's own text never matters.
LOG_NAME = "dispatcher" + ".out"


def _armed(pid, stamp="11-08 13:56:53"):
    return f"- `{stamp}` drain armed: kill -USR1 {pid}\n"


def _start(ts, stage, attempt=1, team="demo", it=1):
    return f"- `{ts}` [{team}] iter {it} {MID} **{stage}** attempt {attempt} started\n"


def _produced(ts, stage, fname="out.md", team="demo", it=1):
    return f"- `{ts}` [{team}] iter {it} {MID} {stage} produced `{fname}`\n"


COMPLETED = _start("08-05 10:00:00", "pm") + _produced("08-05 10:09:00", "pm", "pm.md")
PENDING = _start("09-06 10:00:00", "engineer")


def _cfg():
    return foundry.ProductConfig(name="demo", repo="/no/such/repo",
                                 allowed_push_repo="demo")


def _no_git(monkeypatch):
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: [])


# ------------------------------------------------------------------ EB1

def test_eb1_falsy_defaults_to_foundry_dispatcher_out():
    assert foundry.dispatcher_log_path(None) == foundry.FOUNDRY / LOG_NAME
    assert foundry.dispatcher_log_path("") == foundry.FOUNDRY / LOG_NAME
    assert foundry.dispatcher_log_path() == foundry.FOUNDRY / LOG_NAME


def test_eb1_default_reads_foundry_global_at_call_time(monkeypatch, tmp_path):
    monkeypatch.setattr(foundry, "FOUNDRY", tmp_path)
    assert foundry.dispatcher_log_path(None) == tmp_path / LOG_NAME
    assert foundry.dispatcher_log_path("") == tmp_path / LOG_NAME


def test_eb1_explicit_path_passes_through():
    want = pathlib.Path("x/y.out")
    assert foundry.dispatcher_log_path("x/y.out") == want
    assert foundry.dispatcher_log_path(pathlib.Path("x/y.out")) == want
    assert isinstance(foundry.dispatcher_log_path("x/y.out"), pathlib.Path)


# ------------------------------------------------------------------ EB2

def test_eb2_valid_utf8_returned_exactly(tmp_path):
    p = tmp_path / "ok.out"
    text = BANNER + "caf\u00e9 \u4e2d\u6587 " + MID + "\n"
    p.write_text(text, encoding="utf-8")
    assert foundry.read_dispatcher_log(p) == text
    assert foundry.read_dispatcher_log(str(p)) == text


def test_eb2_bad_byte_is_replaced_not_fatal(tmp_path):
    p = tmp_path / "bad.out"
    p.write_bytes(b"line one\nbad \xe9 byte\nline three\n")
    got = foundry.read_dispatcher_log(p)
    assert isinstance(got, str)
    assert "line one" in got
    assert "line three" in got
    assert "\ufffd" in got


def test_eb2_missing_dir_none_give_empty(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    assert foundry.read_dispatcher_log(tmp_path / "nope.out") == ""
    assert foundry.read_dispatcher_log(d) == ""
    assert foundry.read_dispatcher_log(None) == ""


def test_eb2_none_does_not_read_ambient_default(monkeypatch, tmp_path):
    # read_dispatcher_log does NO defaulting: even with a real default log
    # present under FOUNDRY, None reads nothing.
    (tmp_path / LOG_NAME).write_text(BANNER + _armed(7), encoding="utf-8")
    monkeypatch.setattr(foundry, "FOUNDRY", tmp_path)
    assert foundry.read_dispatcher_log(None) == ""
    assert foundry.read_dispatcher_log("") == ""


# ------------------------------------------------------------------ EB3

def test_eb3_live_lag_and_drain_arm_judge_same_banner(monkeypatch, tmp_path):
    _no_git(monkeypatch)
    log = tmp_path / "d.out"
    log.write_bytes(BANNER.encode("utf-8") + BAD_LINE)
    st = foundry.live_lag_status(_cfg(), log)
    assert st.verdict == foundry.LIVE_LAG_OK, st.render()
    assert "no datable" not in st.render()
    assert "11-08 13:56:52" in st.render()
    line = foundry.drain_arm_status_line(_cfg(), log)
    assert line.startswith("drain-arm: NOT ARMED"), line


def test_eb3_bad_byte_before_banner_also_tolerated(monkeypatch, tmp_path):
    _no_git(monkeypatch)
    log = tmp_path / "d.out"
    log.write_bytes(BAD_LINE + BANNER.encode("utf-8") + _armed(4242).encode() + BAD_LINE)
    st = foundry.live_lag_status(_cfg(), log)
    assert st.verdict == foundry.LIVE_LAG_OK, st.render()
    line = foundry.drain_arm_status_line(_cfg(), log)
    assert line.startswith("drain-arm: ARMED"), line
    assert "4242" in line


# ------------------------------------------------------------------ EB4

def test_eb4_stage_times_unchanged_by_bad_line(tmp_path):
    clean = tmp_path / "clean.out"
    clean.write_text(COMPLETED, encoding="utf-8")
    dirty = tmp_path / "dirty.out"
    dirty.write_bytes(COMPLETED.encode("utf-8") + BAD_LINE)
    a = foundry.gather_stage_times(clean)
    b = foundry.gather_stage_times(dirty)
    assert a.exit_code != 2, "fixture does not parse -- comparison would be vacuous"
    assert b.exit_code == a.exit_code
    assert b.total == a.total
    assert b.total >= 1
    assert len(b.groups) == len(a.groups) >= 1


def test_eb4_stage_budget_line_unchanged_by_bad_line(tmp_path):
    clean = tmp_path / "clean.out"
    clean.write_text(COMPLETED, encoding="utf-8")
    dirty = tmp_path / "dirty.out"
    dirty.write_bytes(COMPLETED.encode("utf-8") + BAD_LINE)
    a = foundry.stage_budget_line(_cfg(), log_path=str(clean))
    b = foundry.stage_budget_line(_cfg(), log_path=str(dirty))
    assert "UNKNOWN" not in a
    assert b == a


def test_eb4_pending_stages_unchanged_by_bad_line(tmp_path):
    clean = tmp_path / "clean.out"
    clean.write_text(PENDING, encoding="utf-8")
    dirty = tmp_path / "dirty.out"
    dirty.write_bytes(PENDING.encode("utf-8") + BAD_LINE)
    a = foundry.gather_pending_stages(clean, now=NOW)
    b = foundry.gather_pending_stages(dirty, now=NOW)
    assert len(a) == 1
    assert len(b) == 1
    assert [r.to_dict() for r in b] == [r.to_dict() for r in a]


def test_eb4_gather_none_still_reads_nothing(monkeypatch, tmp_path):
    # The non-defaulting arm: a real default log under FOUNDRY must NOT be read.
    (tmp_path / LOG_NAME).write_text(COMPLETED + PENDING, encoding="utf-8")
    monkeypatch.setattr(foundry, "FOUNDRY", tmp_path)
    assert foundry.gather_stage_times(None).exit_code == 2
    assert len(foundry.gather_pending_stages(None, now=NOW)) == 0


# ------------------------------------------------------------------ EB5

def _seam(monkeypatch, text, calls):
    def fake(p):
        calls.append(p)
        return text
    monkeypatch.setattr(foundry, "read_dispatcher_log", fake)


def test_eb5_drain_arm_reads_through_seam(monkeypatch, tmp_path):
    calls = []
    _seam(monkeypatch, BANNER + _armed(4242), calls)
    line = foundry.drain_arm_status_line(_cfg(), str(tmp_path / "nope"))
    assert line.startswith("drain-arm: ARMED"), line
    assert "4242" in line
    assert calls


def test_eb5_live_lag_reads_through_seam(monkeypatch, tmp_path):
    _no_git(monkeypatch)
    calls = []
    _seam(monkeypatch, BANNER, calls)
    st = foundry.live_lag_status(_cfg(), str(tmp_path / "nope"))
    assert st.verdict == foundry.LIVE_LAG_OK, st.render()
    assert calls


def test_eb5_stage_times_and_budget_read_through_seam(monkeypatch, tmp_path):
    calls = []
    _seam(monkeypatch, COMPLETED, calls)
    s = foundry.gather_stage_times(str(tmp_path / "nope"))
    assert s.exit_code != 2
    assert s.total == 1
    line = foundry.stage_budget_line(_cfg(), log_path=str(tmp_path / "nope"))
    assert "UNKNOWN" not in line, line
    assert len(calls) >= 2


def test_eb5_pending_reads_through_seam(monkeypatch, tmp_path):
    calls = []
    _seam(monkeypatch, PENDING, calls)
    recs = foundry.gather_pending_stages(str(tmp_path / "nope"), now=NOW)
    assert len(recs) == 1
    assert recs[0].stage == "engineer"
    assert calls


def test_eb5_defaulting_callers_hand_seam_the_resolved_default(monkeypatch, tmp_path):
    _no_git(monkeypatch)
    monkeypatch.setattr(foundry, "FOUNDRY", tmp_path)
    calls = []
    _seam(monkeypatch, BANNER + _armed(99), calls)
    assert foundry.drain_arm_status_line(_cfg()).startswith("drain-arm: ARMED")
    assert foundry.live_lag_status(_cfg()).verdict == foundry.LIVE_LAG_OK
    assert calls
    assert all(pathlib.Path(c) == tmp_path / LOG_NAME for c in calls), calls


# ------------------------------------------------------------------ EB6

def _make(kind, tmp_path):
    if kind == "missing":
        return tmp_path / "nope.out"
    if kind == "dir":
        d = tmp_path / "adir"
        d.mkdir()
        return d
    p = tmp_path / "bin.out"
    p.write_bytes(BINARY)
    return p


@pytest.mark.parametrize("kind", ["missing", "dir", "binary"])
def test_eb6_degradations_unchanged(monkeypatch, tmp_path, kind):
    _no_git(monkeypatch)
    p = _make(kind, tmp_path)
    budget = foundry.stage_budget_line(_cfg(), log_path=str(p))
    assert "UNKNOWN" in budget, budget
    assert "WARN" not in budget, budget
    drain = foundry.drain_arm_status_line(_cfg(), p)
    assert drain.startswith("drain-arm: ")
    assert not drain.startswith("drain-arm: ARMED"), drain
    assert foundry.live_lag_status(_cfg(), p).verdict == foundry.LIVE_LAG_UNKNOWN
    assert foundry.gather_stage_times(p).exit_code == 2
    assert len(foundry.gather_pending_stages(p, now=NOW)) == 0


# ------------------------------------------------------------------ EB7

CALLERS = ("gather_stage_times", "gather_pending_stages", "live_lag_status",
           "drain_arm_status_line", "stage_budget_line")
HELPERS = ("dispatcher_log_path", "read_dispatcher_log")


def _body_src(name):
    """Function source with its docstring removed, via AST."""
    src = textwrap.dedent(inspect.getsource(getattr(foundry, name)))
    tree = ast.parse(src)
    fn = tree.body[0]
    assert isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)), name
    body = fn.body
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    fn.body = body or [ast.Pass()]
    return ast.unparse(fn)


@pytest.mark.parametrize("name", CALLERS)
def test_eb7_callers_have_no_private_read_or_default(name):
    body = _body_src(name)
    assert ".read_text(" not in body, f"{name} still reads the file itself"
    assert repr(LOG_NAME) not in body and f'"{LOG_NAME}"' not in body, \
        f"{name} still names the default log itself"


def test_eb7_only_reader_contains_read_text():
    holders = [n for n in CALLERS + HELPERS if ".read_text(" in _body_src(n)]
    assert holders == ["read_dispatcher_log"]


def test_eb7_helpers_are_module_level_functions():
    for n in HELPERS:
        fn = getattr(foundry, n)
        assert inspect.isfunction(fn)
        assert fn.__module__ == "foundry"


# ------------------------------------------------------------------ EB8

def test_eb8_both_modules_import():
    import importlib
    assert importlib.import_module("foundry") is foundry
    d = importlib.import_module("dispatcher")
    assert hasattr(d, "main")
