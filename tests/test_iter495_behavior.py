"""Iteration 495 -- BLACK-BOX behavior tests: `find_assertionless_tests` builds its
same-module delegation table (`_delegated_signal_names`) LAZILY -- only when the
first signal-less `test*` def is met, at most once per call, and never when
`WEAK_TEST_RESOLVE_DELEGATES` is False -- with results unchanged.

Spec under test (the iter-495 PM spec), Expected Behaviors 1-7:
   1. every call returns exactly what it returned before (literal golden tuples)
   2. 0 table builds for an all-signalled source / a source with no test* def
   3. exactly 1 table build per call with >= 2 signal-less tests (flag True)
   4. flag False -> 0 builds and every signal-less test flagged
   5. SyntaxError on invalid text still raised verbatim, 0 builds
   6. results stay in ascending source-line order
   7. `weak-tests` CLI (human + --json) stdout and exit code unchanged on a
      tmp_path fixture repo

ISOLATION HONORED: written from the spec, the repo's `tests/` conventions and the
product's RUNTIME surface only. No implementation source, engineer/reviewer note
or `git diff` was read.

ORACLE CHOICE: the spec allows a HEAD-copy second module OR literal tuples. A
HEAD-copy is meaningless once this file ships (HEAD *is* the change), so the
goldens are literal tuples / literal CLI text; the HEAD comparison was a one-off
scratch check recorded in the tester report. No timing assertions.

FIXTURES ARE STRING LITERALS; the CLI fixture repo is built in tmp_path. Offline,
fresh-clone safe: no ambient-tree assertion.
"""
from __future__ import annotations

import ast
import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402,F401  (import-safety probe -- the product quality bar)

WEAK = "find_assertionless_tests"
TABLE = "_delegated_signal_names"
FLAG = "WEAK_TEST_RESOLVE_DELEGATES"


def _weak(source):
    return getattr(foundry, WEAK)(source)


class _Spy:
    """Counting wrapper around the REAL table builder (result unchanged)."""

    def __init__(self, real):
        self.real = real
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.real(*args, **kwargs)


@pytest.fixture
def spy(monkeypatch):
    s = _Spy(getattr(foundry, TABLE))
    monkeypatch.setattr(foundry, TABLE, s)
    return s


# --------------------------------------------------------------------------
# fixture grid (source TEXT)
# --------------------------------------------------------------------------
GRID = '''
import pytest


def _helper_asserts(x):
    assert x == 1


def _helper_plain(x):
    return x


def _leaf(x):
    assert x


def _mid(x):
    _leaf(x)


def test_signalled():
    assert 1 + 1 == 2


def test_raises():
    with pytest.raises(ValueError):
        int("x")


def test_delegates():
    _helper_asserts(1)


def test_plain():
    _helper_plain(1)


def test_chain():
    _mid(1)


class TestK:
    def test_method_bare(self):
        pass

    def test_method_ok(self):
        assert True is True

    def test_method_delegates(self):
        _helper_asserts(1)


async def test_async_bare():
    pass


async def test_async_delegates():
    _helper_asserts(1)
'''

GRID_TRUE = ("test_plain", "test_chain", "test_method_bare", "test_async_bare")
GRID_FALSE = (
    "test_delegates", "test_plain", "test_chain", "test_method_bare",
    "test_method_delegates", "test_async_bare", "test_async_delegates",
)

ALL_SIGNALLED = '''
import pytest


def _helper_plain(x):
    return x


def test_a():
    assert _helper_plain(1) == 1


def test_b():
    with pytest.raises(KeyError):
        {}["k"]


class TestC:
    def test_c(self):
        assert self is not None


async def test_d():
    assert 3 > 2
'''

NO_TESTS = '''
def helper():
    return 1


class Thing:
    def method(self):
        assert self
'''

TWO_BARE = '''
def _helper_asserts(x):
    assert x


def test_one():
    _helper_asserts(1)


def test_two():
    pass


def test_three():
    _helper_asserts(2)


def test_ok():
    assert 1
'''


def _inputs(src):
    return [src, ast.parse(src)]


# --------------------------------------------------------------------------
# Behavior 1 -- results unchanged (literal goldens), str and ast.Module
# --------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["str", "module"])
def test_b1_grid_golden_flag_true(kind):
    src = GRID if kind == "str" else ast.parse(GRID)
    assert _weak(src) == GRID_TRUE


@pytest.mark.parametrize("kind", ["str", "module"])
def test_b1_grid_golden_flag_false(kind, monkeypatch):
    monkeypatch.setattr(foundry, FLAG, False)
    src = GRID if kind == "str" else ast.parse(GRID)
    assert _weak(src) == GRID_FALSE


def test_b1_return_type_is_tuple_of_str():
    out = _weak(GRID)
    assert isinstance(out, tuple)
    assert all(isinstance(n, str) for n in out)


@pytest.mark.parametrize(
    "src,expected",
    [
        (ALL_SIGNALLED, ()),
        (NO_TESTS, ()),
        (TWO_BARE, ("test_two",)),
        ("", ()),
    ],
)
def test_b1_small_goldens(src, expected):
    for inp in _inputs(src):
        assert _weak(inp) == expected


def test_b1_two_level_chain_still_flagged():
    out = _weak(GRID)
    assert "test_chain" in out
    assert "test_delegates" not in out


# --------------------------------------------------------------------------
# Behavior 2 -- 0 builds when nothing is signal-less
# --------------------------------------------------------------------------
@pytest.mark.parametrize("src", [ALL_SIGNALLED, NO_TESTS, ""])
def test_b2_zero_builds_when_no_bare_test(spy, src):
    for inp in _inputs(src):
        assert _weak(inp) == ()
    assert spy.calls == 0


# --------------------------------------------------------------------------
# Behavior 3 -- exactly one build per call with >= 2 bare tests
# --------------------------------------------------------------------------
def test_b3_one_build_per_call_two_bare(spy):
    assert _weak(TWO_BARE) == ("test_two",)
    assert spy.calls == 1


def test_b3_one_build_per_call_grid_many_bare(spy):
    # GRID has 7 signal-less defs; the table must be built once, not 7 times
    assert _weak(GRID) == GRID_TRUE
    assert spy.calls == 1
    assert _weak(ast.parse(GRID)) == GRID_TRUE
    assert spy.calls == 2


def test_b3_not_cached_across_calls(spy):
    for n in range(1, 4):
        _weak(TWO_BARE)
        assert spy.calls == n


def test_b3_single_bare_test_builds_once(spy):
    src = "def _h():\n    assert 1\n\n\ndef test_x():\n    _h()\n"
    assert _weak(src) == ()
    assert spy.calls == 1


# --------------------------------------------------------------------------
# Behavior 4 -- flag False: 0 builds, every signal-less test flagged
# --------------------------------------------------------------------------
def test_b4_flag_false_zero_builds_all_bare_flagged(spy, monkeypatch):
    monkeypatch.setattr(foundry, FLAG, False)
    assert _weak(GRID) == GRID_FALSE
    assert _weak(TWO_BARE) == ("test_one", "test_two", "test_three")
    assert spy.calls == 0


def test_b4_flag_read_at_call_time(spy, monkeypatch):
    monkeypatch.setattr(foundry, FLAG, False)
    assert _weak(TWO_BARE) == ("test_one", "test_two", "test_three")
    assert spy.calls == 0
    monkeypatch.setattr(foundry, FLAG, True)
    assert _weak(TWO_BARE) == ("test_two",)
    assert spy.calls == 1
    monkeypatch.setattr(foundry, FLAG, False)
    assert _weak(TWO_BARE) == ("test_one", "test_two", "test_three")
    assert spy.calls == 1


# --------------------------------------------------------------------------
# Behavior 5 -- SyntaxError raised verbatim, no build
# --------------------------------------------------------------------------
def test_b5_syntax_error_raised_no_build(spy):
    bad = "def test_x(:\n    pass\n"
    with pytest.raises(SyntaxError) as ei:
        _weak(bad)
    with pytest.raises(SyntaxError) as ref:
        ast.parse(bad)
    assert type(ei.value) is type(ref.value)
    assert ei.value.lineno == ref.value.lineno
    assert spy.calls == 0


# --------------------------------------------------------------------------
# Behavior 6 -- ascending source-line order
# --------------------------------------------------------------------------
def _def_lines(src):
    lines = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines.setdefault(node.name, node.lineno)
    return lines


@pytest.mark.parametrize("flag", [True, False])
def test_b6_ascending_source_order(flag, monkeypatch):
    monkeypatch.setattr(foundry, FLAG, flag)
    lines = _def_lines(GRID)
    out = _weak(GRID)
    assert len(out) >= 4
    assert [lines[n] for n in out] == sorted(lines[n] for n in out)


# --------------------------------------------------------------------------
# Behavior 7 -- CLI output unchanged on a tmp_path fixture repo
# --------------------------------------------------------------------------
MIX = '''def _helper_asserts(x):
    assert x == 1


def _helper_plain(x):
    return x


def test_delegates():
    _helper_asserts(1)


def test_plain():
    _helper_plain(1)


def test_signalled():
    assert 2 == 1 + 1
'''


def _fixture_config(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_mix.py").write_text(MIX)
    work = tmp_path / "work"
    work.mkdir()
    tracked = json.loads((_ROOT / "products" / "_platform" / "config.json").read_text())
    cfg = {}
    for k, v in tracked.items():
        if isinstance(v, str) and "{FOUNDRY}" in v:
            v = v.replace("{FOUNDRY}", str(repo))
        cfg[k] = v
    cfg["repo"] = str(repo)
    cfg["work_root"] = str(work)
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(cfg))
    return p, repo / "tests" / "test_mix.py"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(_ROOT / "foundry.py"), *args],
        capture_output=True, text=True, timeout=120,
    )


def test_b7_cli_human_golden(tmp_path):
    cfg, f = _fixture_config(tmp_path)
    r = _run("weak-tests", "--config", str(cfg))
    assert r.returncode == 1, r.stderr
    expected = (
        "foundry weak-tests -- _platform\n"
        "  files scanned: 1\n"
        "  assertion-free tests: 1\n"
        f"  {f} :: test_plain\n"
        "  parse errors: 0\n"
        "verdict: WEAK TESTS FOUND\n"
    )
    assert r.stdout == expected


def test_b7_cli_json_golden(tmp_path):
    cfg, f = _fixture_config(tmp_path)
    r = _run("weak-tests", "--config", str(cfg), "--json")
    assert r.returncode == 1, r.stderr
    expected = {
        "product": "_platform",
        "files_scanned": 1,
        "total_findings": 1,
        "clean": False,
        "exit_code": 1,
        "verdict": "WEAK TESTS FOUND",
        "findings": [{"file": str(f), "test": "test_plain"}],
        "parse_errors": [],
    }
    assert json.loads(r.stdout) == expected
    assert r.stdout.strip() == json.dumps(expected, indent=2)
