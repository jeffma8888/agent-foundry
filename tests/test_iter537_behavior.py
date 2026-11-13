"""Iteration 537 -- BLACK-BOX behavior tests: one pure `_yearless_span_s(begin, end)`
helper owns the yearless-stamp span rule, and the three walkers
(`parse_stage_attempts`, `pending_stage_starts`, `open_holds`) call it by bare name
while each keeps its OWN negative-value tail.

Spec under test: products/_platform/state/iter-537/pm.md, Expected Behaviors 1-8.

ISOLATION CONTRACT (HONORED): written ONLY from that PM spec and the conventions under
`tests/` (the `dispatcher.out` line builders of tests/test_iter534_behavior.py),
driving the product's PUBLIC functions plus an `ast` walk of the module file that the
spec itself names as the observable (behavior 6).  I did NOT read the implementation
source, engineer.md, reviewer.md, or any `git diff`.

Every log fixture is a SYNTHETIC STRING built in-process: no git, no network, no
gitignored state, no real clock (`now` is always passed explicitly).
"""

import ast
import inspect
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

MID = "\u00b7"
TEAM = "_platform"
ITER = 537


# --------------------------------------------------------------------------
# fixture builders -- the EXACT dispatcher.out line shapes (test_iter534 `_pre`)
# --------------------------------------------------------------------------
def _pre(ts, team=TEAM, it=ITER):
    return f"- `{ts}` [{team}] iter {it} {MID} "


def _start(ts, stage="tester", attempt=1):
    return _pre(ts) + f"**{stage}** attempt {attempt} started"


def _produced(ts, stage="tester", fname="tester.md"):
    return _pre(ts) + f"{stage} produced `{fname}`"


def _backoff(ts, stage="tester", mins=30, kind="auth"):
    return _pre(ts) + f"{stage} backing off {mins} min (failure kind: {kind})"


def _mk(*lines):
    return "\n".join(lines) + "\n"


def _st(s):
    return foundry.parse_log_stamp(s)


def _reference(b, e):
    """The pre-change inline formula, verbatim from the spec (behavior 4)."""
    d = int((e - b).total_seconds())
    if d < 0:
        d += 86400
    if d < 0 and b.month == 12 and e.month == 1:
        d = int((e - b.replace(year=b.year - 1)).total_seconds())
    return d


# (begin, end, expected) -- behavior 2 (non-negative) and behavior 3 (negative)
B2_ROWS = [
    ("03-10 10:00:00", "03-10 10:05:00", 300),
    ("03-10 23:55:00", "03-10 00:05:00", 600),
    ("09-06 23:59:30", "09-07 00:00:30", 60),
    ("12-31 23:55:00", "01-01 00:10:00", 900),
    ("12-30 12:00:00", "01-01 12:00:00", 172800),
    ("02-29 23:00:00", "03-01 01:00:00", 7200),
    ("01-01 00:00:00", "12-31 00:00:00", 31536000),
]
B3_ROWS = [
    ("03-10 10:00:00", "03-08 10:00:00", -86400),
    ("12-20 10:00:00", "12-18 10:00:00", -86400),
    ("11-30 23:55:00", "01-01 00:10:00", -28856700),
]
ALL_ROWS = B2_ROWS + B3_ROWS
_IDS = [f"{b}->{e}" for b, e, _ in ALL_ROWS]


# --------------------------------------------------------------------------
# Behavior 1 -- module-level, two positional datetimes, returns int, pure
# --------------------------------------------------------------------------
def test_b1_helper_is_module_level_two_positional_returns_int():
    fn = getattr(foundry, "_yearless_span_s", None)
    assert callable(fn), "foundry._yearless_span_s missing"
    assert inspect.isfunction(fn)
    assert fn.__module__ == foundry.__name__
    params = list(inspect.signature(fn).parameters.values())
    assert [p.name for p in params] == ["begin", "end"]
    for p in params:
        assert p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        assert p.default is p.empty
    got = fn(_st("03-10 10:00:00"), _st("03-10 10:05:00"))
    assert type(got) is int


def test_b1_helper_is_pure_no_io(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("helper performed I/O")

    import builtins
    import subprocess
    import time

    monkeypatch.setattr(builtins, "open", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(time, "time", _boom)
    monkeypatch.setattr(time, "sleep", _boom)
    for b, e, want in ALL_ROWS:
        assert foundry._yearless_span_s(_st(b), _st(e)) == want


# --------------------------------------------------------------------------
# Behaviors 2 & 3 -- exact helper values, including unclamped negatives
# --------------------------------------------------------------------------
@pytest.mark.parametrize("b,e,want", B2_ROWS, ids=[f"{b}->{e}" for b, e, _ in B2_ROWS])
def test_b2_helper_values(b, e, want):
    got = foundry._yearless_span_s(_st(b), _st(e))
    assert got == want
    assert got >= 0


@pytest.mark.parametrize("b,e,want", B3_ROWS, ids=[f"{b}->{e}" for b, e, _ in B3_ROWS])
def test_b3_helper_does_not_clamp(b, e, want):
    got = foundry._yearless_span_s(_st(b), _st(e))
    assert got == want
    assert got < 0


# --------------------------------------------------------------------------
# Behavior 4 -- equals the pre-change inline formula on every row
# --------------------------------------------------------------------------
@pytest.mark.parametrize("b,e,want", ALL_ROWS, ids=_IDS)
def test_b4_matches_reference_formula(b, e, want):
    bb, ee = _st(b), _st(e)
    assert _reference(bb, ee) == want  # the spec's table agrees with the formula
    assert foundry._yearless_span_s(bb, ee) == _reference(bb, ee)


# --------------------------------------------------------------------------
# Behavior 5 -- each walker keeps its OWN tail
# --------------------------------------------------------------------------
@pytest.mark.parametrize("b,e,want", ALL_ROWS, ids=_IDS)
def test_b5_parse_stage_attempts_clamps_to_zero(b, e, want):
    got = foundry.parse_stage_attempts(_mk(_start(b), _produced(e)))
    assert len(got) == 1, got
    assert got[0].stage == "tester"
    assert got[0].duration_s == max(want, 0)


@pytest.mark.parametrize("b,e,want", ALL_ROWS, ids=_IDS)
def test_b5_pending_stage_starts_clamps_to_zero(b, e, want):
    got = foundry.pending_stage_starts(_mk(_start(b)), e, cap=600)
    assert len(got) == 1, got
    rec = got[0]
    s = max(want, 0)
    assert rec.elapsed_s == s
    assert rec.headroom_s == 600 - s
    assert rec.stale == (s >= 600)


@pytest.mark.parametrize("b,e,want", ALL_ROWS, ids=_IDS)
def test_b5_open_holds_drops_negative_and_expired(b, e, want):
    got = foundry.open_holds(_mk(_backoff(b)), e)
    if want < 0 or want >= 1800:
        assert got == ()
    else:
        assert len(got) == 1, got
        assert got[0].elapsed_s == want
        assert got[0].remaining_s == 1800 - want


@pytest.mark.parametrize("b,e,want", B3_ROWS, ids=[f"{b}->{e}" for b, e, _ in B3_ROWS])
def test_b5_future_ghost_never_a_zero_elapsed_hold(b, e, want):
    got = foundry.open_holds(_mk(_backoff(b)), e)
    assert got == ()
    assert not any(h.elapsed_s == 0 for h in got)


# --------------------------------------------------------------------------
# Behavior 6 -- single owner, by an ast walk of foundry.py
# --------------------------------------------------------------------------
_WALKERS = ("parse_stage_attempts", "pending_stage_starts", "open_holds")


def _module_funcs():
    tree = ast.parse(pathlib.Path(foundry.__file__).read_text(encoding="utf-8"))
    return {n.name: n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}, tree


def test_b6_one_day_constant_loaded_only_in_helper():
    funcs, tree = _module_funcs()
    owners = set()
    for top in tree.body:
        for node in ast.walk(top):
            if (isinstance(node, ast.Name) and node.id == "_ONE_DAY_S"
                    and isinstance(node.ctx, ast.Load)):
                owner = top.name if isinstance(
                    top, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else "<module>"
                owners.add(owner)
    assert owners == {"_yearless_span_s"}, owners
    assert "_yearless_span_s" in funcs


@pytest.mark.parametrize("name", _WALKERS)
def test_b6_walkers_call_helper_by_bare_name_and_no_year_replace(name):
    funcs, _ = _module_funcs()
    fn = funcs[name]
    bare_calls = [n for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id == "_yearless_span_s"]
    assert bare_calls, f"{name} does not call _yearless_span_s by bare name"
    year_replace = [n for n in ast.walk(fn)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "replace"
                    and any(k.arg == "year" for k in n.keywords)]
    assert year_replace == [], f"{name} still carries a .replace(year=...) copy"


# --------------------------------------------------------------------------
# Behavior 7 -- bare-name seam: monkeypatching the helper reaches all three
# --------------------------------------------------------------------------
@pytest.mark.parametrize("b,e", [("03-10 10:00:00", "03-10 10:05:00"),
                                 ("12-31 23:55:00", "01-01 00:10:00"),
                                 ("03-10 10:00:00", "03-08 10:00:00")])
def test_b7_monkeypatched_helper_reaches_all_three_walkers(monkeypatch, b, e):
    monkeypatch.setattr(foundry, "_yearless_span_s", lambda bb, ee: 42)
    att = foundry.parse_stage_attempts(_mk(_start(b), _produced(e)))
    assert len(att) == 1 and att[0].duration_s == 42
    pend = foundry.pending_stage_starts(_mk(_start(b)), e, cap=600)
    assert len(pend) == 1 and pend[0].elapsed_s == 42
    holds = foundry.open_holds(_mk(_backoff(b)), e)
    assert len(holds) == 1 and holds[0].elapsed_s == 42
    assert holds[0].remaining_s == 1800 - 42
