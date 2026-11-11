"""Iteration 525 -- BLACK-BOX behavior tests: a red clone suite whose output names no
parsable failing test gets a `; BROKEN -- no failing names parsed from <runner>` clause
on its preship BROKEN detail, and roles/final.md says a passing re-run never overturns
exit 1.

Spec under test: products/_platform/state/iter-525/pm.md, Expected Behaviors 1-10.

ISOLATION HONORED: written from `pm.md`, the repo's own `tests/` conventions (chiefly
tests/test_iter524_behavior.py and tests/test_iter517_behavior.py) and the product's
RUNTIME surface (public names, signatures) ONLY.  No implementation source, no
engineer / reviewer note and no `git diff` output was read.

OFFLINE: literal fixtures, scripted `run_cmd` / `cleanup_clone` / `rerun_suite_at_parent`
/ `verify_local_clone` seams set by BARE module name; no real git, subprocess or network
(except the two `python -c import` checks of behavior 10).
FRESH-CLONE SAFE: every fixture lives in this module or under `tmp_path`; the only repo
file read is the git-tracked roles/*.md.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

SHA = "b" * 40
PARENT = "a" * 40
CONST = ("the declared test suite FAILED inside a clean local clone of the commit "
         "about to be pushed")
CLAUSE = "; BROKEN -- no failing names parsed from "
PYTEST_RED = ("============ FAILURES ============\n"
              "FAILED tests/test_x.py::test_one - assert 1 == 2\n"
              "FAILED tests/test_x.py::test_two - boom\n"
              "2 failed, 3 passed in 0.10s\n")


# ==========================================================================
# Behavior 1 -- preship_runner_label(test_cmd), pure and total
# ==========================================================================
@pytest.mark.parametrize("cmd, want", [
    ("uv run  --with pytest\tpytest -q", "`uv run --with pytest pytest -q`"),
    ("uv run pytest -q", "`uv run pytest -q`"),
    ("  npm\n test  ", "`npm test`"),
    ("   ", "unknown"),
    ("", "unknown"),
    (None, "unknown"),
])
def test_b1_label_examples(cmd, want):
    assert foundry.preship_runner_label(cmd) == want


def test_b1_label_max_is_int_120():
    assert isinstance(foundry.PRESHIP_RUNNER_LABEL_MAX, int)
    assert foundry.PRESHIP_RUNNER_LABEL_MAX == 120


def test_b1_long_command_truncated():
    cmd = "x" * 300
    got = foundry.preship_runner_label(cmd)
    assert len(got) == 122
    assert got == "`" + "x" * 117 + "...`"


def test_b1_exactly_max_not_truncated():
    cmd = "y" * 120
    assert foundry.preship_runner_label(cmd) == "`" + cmd + "`"
    assert foundry.preship_runner_label("y" * 121) == "`" + "y" * 117 + "...`"


def test_b1_long_collapses_before_cut():
    cmd = "a  " * 100  # collapses to 199 chars
    c = " ".join(cmd.split())
    assert foundry.preship_runner_label(cmd) == "`" + c[:117] + "...`"


def test_b1_max_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "PRESHIP_RUNNER_LABEL_MAX", 10)
    assert foundry.preship_runner_label("abcdefghijklmnop") == "`abcdefg...`"
    assert foundry.preship_runner_label("abcdefghij") == "`abcdefghij`"


class _BadStr:
    def __str__(self):
        raise RuntimeError("no str")


class _BadSplitStr(str):
    def split(self, *a, **k):
        raise RuntimeError("no split")

    def __str__(self):
        return self


@pytest.mark.parametrize("bad", [_BadStr(), _BadSplitStr("pytest -q")])
def test_b1_never_raises_on_hostile_input(bad):
    assert foundry.preship_runner_label(bad) == "unknown"


def test_b1_non_str_ok_input_is_stringified():
    assert foundry.preship_runner_label(42) == "`42`"


# ==========================================================================
# Behavior 2 -- PRESHIP_SUITE_FAILED_DETAIL, preship_verdict bytes unchanged
# ==========================================================================
def test_b2_constant_exact():
    assert foundry.PRESHIP_SUITE_FAILED_DETAIL == CONST


def test_b2_preship_verdict_uses_constant():
    v = foundry.preship_verdict(clone_ok=True, setup_ok=True, test_ok=False,
                                sha_ok=False, budget_exhausted=False)
    assert v.detail == CONST
    assert v.exit_code == 1 and v.verified is False and v.incomplete is False


# ==========================================================================
# Behaviors 3-6, 8 -- _preship_parent_leg
# ==========================================================================
def _cfg(tmp_path, test_cmd="uv run pytest -q"):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    return foundry.ProductConfig(name="demo", repo=str(repo), allowed_push_repo="demo",
                                 work_root=str(work), test_cmd=test_cmd,
                                 setup_cmd="true")


def _script(monkeypatch, parent_out=None):
    calls = {"cmd": [], "rerun": []}

    def fake_run_cmd(args, cwd=None, timeout=None, **kw):
        argv = [str(a) for a in args]
        calls["cmd"].append(argv)
        if "rev-parse" in argv and any(a.endswith("^") for a in argv):
            return foundry.CmdResult(True, PARENT + "\n")
        if "rev-parse" in argv:
            return foundry.CmdResult(True, SHA + "\n")
        return foundry.CmdResult(True, "")

    def fake_rerun(cfg, parent_sha, clone_dir):
        calls["rerun"].append(parent_sha)
        return parent_out, "/usr/bin/python3"

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(foundry, "cleanup_clone", lambda *a, **k: None)
    monkeypatch.setattr(foundry, "rerun_suite_at_parent", fake_rerun)
    return calls


def _red(out, detail=CONST):
    return foundry.PreshipResult(verified=False, incomplete=False, detail=detail,
                                 test_seconds=7.5, suite_output=out, verified_sha=SHA)


EMPTY_SET_OUTPUTS = [
    None,
    "",
    "boom\n2 failed\n=== FAILURES ===\n",
    "   × suite one > fails here 3ms\n   × top level fail 0ms\n",
]


@pytest.mark.parametrize("out", EMPTY_SET_OUTPUTS)
def test_b3_fixture_outputs_parse_to_empty_set(out):
    assert not foundry.failing_summary_set(out)


@pytest.mark.parametrize("out", EMPTY_SET_OUTPUTS)
@pytest.mark.parametrize("test_cmd", ["uv run pytest -q", "npm  test", "   "])
def test_b3_empty_set_gains_clause(monkeypatch, tmp_path, out, test_cmd):
    _script(monkeypatch)
    cfg = _cfg(tmp_path, test_cmd)
    base = _red(out)
    got = foundry._preship_parent_leg(cfg, SHA, base)
    assert got.exit_code == 1
    assert got.incomplete is False and got.verified is False
    assert got.detail == CONST + CLAUSE + foundry.preship_runner_label(test_cmd)
    assert got.test_seconds == base.test_seconds
    assert got.verified_sha == base.verified_sha
    assert got.suite_output == base.suite_output


def test_b3_unknown_runner_literal(monkeypatch, tmp_path):
    _script(monkeypatch)
    got = foundry._preship_parent_leg(_cfg(tmp_path, ""), SHA, _red(""))
    assert got.detail == CONST + "; BROKEN -- no failing names parsed from unknown"


@pytest.mark.parametrize("out", EMPTY_SET_OUTPUTS)
def test_b4_no_commands_on_empty_set_path(monkeypatch, tmp_path, out):
    calls = _script(monkeypatch)
    foundry._preship_parent_leg(_cfg(tmp_path), SHA, _red(out))
    assert calls["cmd"] == []
    assert calls["rerun"] == []


def test_b4_rerun_never_called_even_if_it_would_raise(monkeypatch, tmp_path):
    _script(monkeypatch)

    def boom(*a, **k):
        raise AssertionError("rerun_suite_at_parent must not be called")

    monkeypatch.setattr(foundry, "rerun_suite_at_parent", boom)
    got = foundry._preship_parent_leg(_cfg(tmp_path), SHA, _red("boom\n2 failed\n"))
    assert got.exit_code == 1 and got.detail.startswith(CONST + CLAUSE)


SHA_MISMATCH = foundry.preship_verdict(clone_ok=True, setup_ok=True, test_ok=True,
                                       sha_ok=False, budget_exhausted=False)


@pytest.mark.parametrize("base", [
    dataclasses.replace(SHA_MISMATCH, suite_output="1 passed in 0.01s\n"),
    SHA_MISMATCH,
    foundry.PreshipResult(False, False, "d-baseline", suite_output=""),
    foundry.PreshipResult(False, False, "d-baseline", suite_output=None),
    foundry.PreshipResult(False, False, CONST + " (extra)", suite_output=""),
])
def test_b5_other_exit1_empty_set_untouched(monkeypatch, tmp_path, base):
    assert base.exit_code == 1
    calls = _script(monkeypatch)
    got = foundry._preship_parent_leg(_cfg(tmp_path), SHA, base)
    assert got.exit_code == 1
    assert got.detail == base.detail
    assert "no failing names parsed" not in got.detail
    assert calls["cmd"] == [] and calls["rerun"] == []


@pytest.mark.parametrize("base", [
    foundry.PreshipResult(True, False, "all good", 3.0, suite_output="1 passed\n"),
    foundry.PreshipResult(False, True, "clone failed", None, suite_output=None),
    foundry.PreshipResult(False, True, CONST, None, suite_output=""),
])
def test_b5_exit0_and_exit2_unchanged(monkeypatch, tmp_path, base):
    calls = _script(monkeypatch)
    got = foundry._preship_parent_leg(_cfg(tmp_path), SHA, base)
    assert got == base
    assert calls["rerun"] == []


def test_b6_differing_parent_detail_unchanged(monkeypatch, tmp_path):
    parent = "FAILED tests/test_x.py::test_one - assert 1 == 2\n1 failed\n"
    calls = _script(monkeypatch, parent_out=parent)
    base = _red(PYTEST_RED)
    got = foundry._preship_parent_leg(_cfg(tmp_path), SHA, base)
    assert calls["rerun"] == [PARENT]
    assert got.exit_code == 1 and got.detail == CONST
    assert "no failing names parsed" not in got.detail


def test_b6_unresolved_parent_detail_unchanged(monkeypatch, tmp_path):
    calls = _script(monkeypatch, parent_out=PYTEST_RED)

    def fake_run_cmd(args, cwd=None, timeout=None, **kw):
        calls["cmd"].append([str(a) for a in args])
        return foundry.CmdResult(False, "fatal: bad revision")

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    got = foundry._preship_parent_leg(_cfg(tmp_path), SHA, _red(PYTEST_RED))
    assert got.exit_code == 1 and got.detail == CONST
    assert calls["rerun"] == []


def test_b6_identical_parent_incomplete_without_clause(monkeypatch, tmp_path):
    calls = _script(monkeypatch, parent_out=PYTEST_RED)
    got = foundry._preship_parent_leg(_cfg(tmp_path), SHA, _red(PYTEST_RED))
    assert calls["rerun"] == [PARENT]
    assert got.exit_code == 2 and got.incomplete is True
    assert f"PARENT {PARENT}" in got.detail
    assert "IDENTICAL set of 2 test(s)" in got.detail
    assert "no failing names parsed" not in got.detail


def test_b8_raising_label_keeps_original(monkeypatch, tmp_path):
    _script(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("label exploded")

    monkeypatch.setattr(foundry, "preship_runner_label", boom)
    base = _red("boom\n2 failed\n")
    got = foundry._preship_parent_leg(_cfg(tmp_path), SHA, base)
    assert got.exit_code == 1
    assert got.detail == CONST
    assert got == base


def test_b8_label_called_by_bare_name(monkeypatch, tmp_path):
    _script(monkeypatch)
    monkeypatch.setattr(foundry, "preship_runner_label", lambda c: "<RUNNER>")
    got = foundry._preship_parent_leg(_cfg(tmp_path), SHA, _red(""))
    assert got.detail == CONST + CLAUSE + "<RUNNER>"


# ==========================================================================
# Behavior 7 -- preship_cli end to end
# ==========================================================================
def _run_cli(monkeypatch, tmp_path, as_json):
    _script(monkeypatch)
    base = foundry.PreshipResult(False, False, CONST, 4.0,
                                 suite_output="boom\n2 failed\n", verified_sha=SHA)
    monkeypatch.setattr(foundry, "verify_local_clone", lambda c, s, d: base)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.preship_cli(_cfg(tmp_path, "uv run pytest -q"), as_json=as_json)
    return rc, buf.getvalue()


WANT_SPAN = "BROKEN -- no failing names parsed from `uv run pytest -q`"


def test_b7_cli_text(monkeypatch, tmp_path):
    rc, out = _run_cli(monkeypatch, tmp_path, False)
    assert rc == 1
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines[-1] == "PRESHIP: BROKEN"
    detail = [ln for ln in lines if ln.startswith("  detail:")]
    assert detail, out
    assert WANT_SPAN in detail[0]


def test_b7_cli_json(monkeypatch, tmp_path):
    rc, out = _run_cli(monkeypatch, tmp_path, True)
    d = json.loads(out)
    assert rc == 1
    assert d["exit_code"] == 1
    assert d["sentinel"] == "PRESHIP: BROKEN"
    assert d["detail"].endswith(WANT_SPAN)


# ==========================================================================
# Behavior 9 -- roles/final.md card sentence
# ==========================================================================
EXIT2_SPAN = "Exit `2` (PRESHIP: INCOMPLETE) is evidence about the MACHINE, not the tree"
EXIT1_SPAN = ("exit `1` (PRESHIP: BROKEN) is decisive evidence about the tree and is a "
              "BLOCKING gate failure")


def _preship_bullets(text):
    return [ln for ln in text.splitlines()
            if ln.startswith("- ") and "preship" in ln]


def _card_ok(text):
    bullets = _preship_bullets(text)
    if len(bullets) != 1:
        return False
    b = bullets[0]
    return ("A passing re-run never overturns exit 1" in b
            and "no failing names parsed" in b
            and EXIT2_SPAN in b and EXIT1_SPAN in b
            and b.index(EXIT2_SPAN) < b.index("A passing re-run never overturns exit 1"))


def test_b9_live_card_has_both_spans():
    text = (_ROOT / "roles" / "final.md").read_text(encoding="utf-8")
    assert _card_ok(text), _preship_bullets(text)


def test_b9_predicate_can_fail_on_old_wording():
    old = ("- **Pre-ship local-clone gate.** Run preship. The rule is ASYMMETRIC: "
           + EXIT1_SPAN + ". " + EXIT2_SPAN + " -- proceed.\n")
    assert _preship_bullets(old)
    assert not _card_ok(old)
    lower = old.rstrip("\n") + " a passing re-run never overturns exit 1; no failing names parsed\n"
    assert not _card_ok(lower)  # case-sensitive
    good = old.rstrip("\n") + " A passing re-run never overturns exit 1; no failing names parsed\n"
    assert _card_ok(good)
    assert not _card_ok(good + "- also preship here\n")


def test_b9_action_sentinel_rules_still_present():
    text = (_ROOT / "roles" / "final.md").read_text(encoding="utf-8")
    assert "ACTION: PUSHED" in text and "ACTION: REVERTED" in text


def test_b9_no_other_role_card_bullet_names_preship():
    for p in sorted((_ROOT / "roles").glob("*.md")):
        if p.name == "final.md":
            continue
        assert not _preship_bullets(p.read_text(encoding="utf-8")), p.name


# ==========================================================================
# Behavior 10 -- importable
# ==========================================================================
@pytest.mark.parametrize("mod", ["foundry", "dispatcher"])
def test_b10_importable(mod):
    r = subprocess.run([sys.executable, "-c", f"import {mod}"], cwd=str(_ROOT),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
