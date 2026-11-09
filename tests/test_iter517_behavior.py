"""Iteration 517 -- BLACK-BOX behavior tests: `foundry preship` re-runs a failing clone
suite at HEAD's PARENT and downgrades BROKEN (exit 1) to INCOMPLETE (exit 2) ONLY when
the parent fails the IDENTICAL, NON-EMPTY set of tests -- evidence about the machine,
not the tree.

Spec under test: products/_platform/state/iter-517/pm.md, Expected Behaviors 1-12.

ISOLATION HONORED: written from `pm.md`, the repo's own `tests/` conventions (chiefly
tests/test_iter156_behavior.py and tests/test_iter198_behavior.py) and the product's
RUNTIME surface (public names, signatures, dataclass fields, compiled bytecode names,
CLI stdout) ONLY.  No implementation source, no engineer / reviewer note and no
`git diff` output was read.

OFFLINE: every external effect goes through scripted `run_cmd` / `_monotonic` /
`cleanup_clone` stand-ins set by BARE module name; no real git, subprocess, clone or
network call happens in any behavior test.  The only subprocess is the
`import foundry, dispatcher` importability probe.

FRESH-CLONE SAFE: every fixture lives under `tmp_path`; nothing asserts on gitignored
state.

Incident shape (Acceptance Criteria): the HEAD and parent outputs carry the SAME four
FAILED lines in DIFFERENT orders, two of them longer than 300 chars (the cap of the
display helper `test_failure_lines`), and preship must answer exit 2; changing one parent
line AFTER char 300 must answer exit 1.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import pathlib
import subprocess
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402

THIS_ITER = 517
SHA = "b" * 40
PARENT = "a" * 40
OTHER_SHA = "c" * 40
INTERP = "/opt/py/cpython-3.14.4-macos/bin/python3.14"

PARENT_DIR_NAME = "preship_parent_clone"
NEW_NAMES = ("rerun_suite_at_parent", "preship_parent_drift", "failing_summary_set")

LONG_A = "FAILED tests/test_deep.py::test_param[" + "x" * 320 + "-alpha] - AssertionError"
LONG_B = "FAILED tests/test_deep.py::test_param[" + "x" * 320 + "-beta] - AssertionError"
SHORT_1 = "FAILED tests/test_one.py::test_first - SyntaxError: invalid syntax"
SHORT_2 = "ERROR tests/test_two.py::test_second - RuntimeError: boom"
FOUR = [LONG_A, SHORT_1, LONG_B, SHORT_2]

_SUMMARY_HDR = "=========================== short test summary info ============================"


def _out(lines, tail="4 failed, 10 passed in 3.21s"):
    return "\n".join(["collected 14 items", "", "=== FAILURES ===", "___ test_x ___",
                      "E   assert 1 == 2", _SUMMARY_HDR] + list(lines) + [
                      "=" * 20 + " " + tail + " " + "=" * 20]) + "\n"


HEAD_OUT = _out(FOUR)
PARENT_OUT = _out([SHORT_2, LONG_B, SHORT_1, LONG_A])          # same set, other order
PARENT_OUT_DIFF_AFTER_300 = _out([SHORT_2, LONG_B[:-len("AssertionError")] + "ValueError",
                                  SHORT_1, LONG_A])
assert LONG_B[:300] == PARENT_OUT_DIFF_AFTER_300.splitlines()[7][:300]  # fixture sanity


def _fss(out):
    return foundry.failing_summary_set(out)


def _drift(h, p):
    return foundry.preship_parent_drift(h, p)


# --------------------------------------------------------------------------
# harness -- mirrors tests/test_iter156/198 (`_cfg`, `_kind`, scripted seams)
# --------------------------------------------------------------------------
def _cfg(tmp_path, **over):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    kw = dict(name="demo", repo=str(repo), allowed_push_repo="demo",
              work_root=str(work), test_cmd="uv run pytest", setup_cmd="uv sync")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _kind(argv, cwd):
    """Classify one scripted argv.  Parent-leg commands are told apart from the HEAD
    clone's by the parent clone dir appearing in the argv or the cwd."""
    joined = " ".join(argv) + " " + str(cwd or "")
    par = PARENT_DIR_NAME in joined
    pre = "p:" if par else ""
    if "--porcelain" in argv:
        return "porcelain"
    if "--shortstat" in argv:
        return "shortstat"
    if argv[:3] == ["uv", "python", "find"]:
        return pre + "find"
    if "rev-parse" in argv:
        if any(a.endswith("^") for a in argv):
            return "parent_resolve"
        return pre + "sha"
    if "checkout" in argv:
        return pre + "checkout"
    if len(argv) > 1 and argv[0] == "git" and argv[1] == "clone":
        return pre + "clone"
    if "sync" in argv:
        return pre + "setup"
    return pre + "test"


class _H:
    def __init__(self):
        self.calls = []
        self.events = []

    @property
    def kinds(self):
        return [c["kind"] for c in self.calls]

    def parent_kinds(self):
        return [k for k in self.kinds if k.startswith("p:") or k == "parent_resolve"]


def _install(monkeypatch, h, *, head_out=HEAD_OUT, head_test_ok=False, clone_sha=SHA,
             parent_out=PARENT_OUT, parent_test_ok=False, resolve=(True, PARENT + "\n"),
             fail=(), raise_kind=None, find=(True, "\n  " + INTERP + "  \nsecond\n"),
             clock=None, cleanup_raises=False, test_cost=None):
    """Script `run_cmd`, `cleanup_clone`, `_monotonic` by BARE module name."""
    box = {"t": 0.0}

    def fake_run_cmd(args, cwd=None, timeout=None, **kw):
        argv = [str(a) for a in args]
        kind = _kind(argv, cwd)
        h.calls.append({"argv": argv, "cwd": cwd, "timeout": timeout, "kind": kind})
        h.events.append(("cmd", kind))
        if raise_kind is not None and kind == raise_kind:
            raise RuntimeError("boom-seam-xyz")
        if kind in fail:
            return foundry.CmdResult(False, kind + " failed")
        if kind == "porcelain":
            return foundry.CmdResult(True, " M a.py\n")
        if kind == "shortstat":
            return foundry.CmdResult(True, " 1 file changed, 2 insertions(+)")
        if kind == "parent_resolve":
            return foundry.CmdResult(*resolve)
        if kind == "sha":
            in_clone = "preship_clone" in " ".join(argv) + " " + str(cwd or "")
            return foundry.CmdResult(True, (clone_sha if in_clone else SHA) + "\n")
        if kind == "p:sha":
            return foundry.CmdResult(True, PARENT + "\n")
        if kind == "test":
            return foundry.CmdResult(head_test_ok, head_out)
        if kind == "p:test":
            if test_cost is not None:
                box["t"] += test_cost(timeout)
            return foundry.CmdResult(parent_test_ok, parent_out)
        if kind == "p:find":
            return foundry.CmdResult(*find)
        return foundry.CmdResult(True, kind + " output")

    def fake_cleanup(clone_dir):
        h.events.append(("cleanup", str(clone_dir)))
        if cleanup_raises:
            raise RuntimeError("cleanup-boom")

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(foundry, "cleanup_clone", fake_cleanup)
    monkeypatch.setattr(foundry, "_monotonic", clock or (lambda: box["t"]))
    return box


def _run_cli(cfg, as_json=False):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.preship_cli(cfg, as_json=as_json)
    return rc, buf.getvalue()


def _last(out):
    return [ln for ln in out.splitlines() if ln.strip()][-1]


def _res(verified=False, incomplete=False, detail="d-baseline", secs=12.5, out=HEAD_OUT):
    return foundry.PreshipResult(verified=verified, incomplete=incomplete, detail=detail,
                                 test_seconds=secs, suite_output=out)


def _fake_verify(monkeypatch, result):
    monkeypatch.setattr(foundry, "verify_local_clone", lambda c, s, d: result)


def _code_names(fn):
    """Compiled-bytecode introspection (co_names/co_consts) -- NOT source text."""
    stack, seen, names = [fn.__code__], set(), set()
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names |= set(code.co_names)
        for c in code.co_consts:
            if isinstance(c, types.CodeType):
                stack.append(c)
            elif isinstance(c, str):
                names.add(c)
    return names


# ==========================================================================
# Behavior 1 -- failing_summary_set: whole lines, no caps, total
# ==========================================================================
def test_b1_keeps_failed_and_error_lines_stripped():
    out = "  FAILED tests/a.py::t1 - x  \nERROR tests/b.py::t2\nPASSED tests/c.py::t3\n"
    assert _fss(out) == frozenset({"FAILED tests/a.py::t1 - x", "ERROR tests/b.py::t2"})


def test_b1_returns_a_frozenset():
    assert isinstance(_fss(HEAD_OUT), frozenset)
    assert _fss(HEAD_OUT) == frozenset(FOUR)


@pytest.mark.parametrize("out", [None, ""])
def test_b1_none_and_empty_give_the_empty_set(out):
    assert _fss(out) == frozenset()


@pytest.mark.parametrize("line", ["=== FAILURES ===", "1 failed", "4 failed, 1 passed",
                                  "failed tests/a.py::t", "FAILEDtests/a.py::t",
                                  "ERRORS", "Error tests/a.py::t", "FAILED", "ERROR",
                                  "x FAILED tests/a.py::t", "_ ERROR collecting x _"])
def test_b1_non_summary_lines_are_never_members(line):
    assert _fss(line + "\nFAILED tests/k.py::keep\n") == frozenset({"FAILED tests/k.py::keep"})


def test_b1_no_length_cap_400005_char_line_kept_whole():
    line = "FAILED " + "z" * 399_998
    assert len(line) == 400_005
    got = _fss("head\n" + line + "\ntail\n")
    assert got == frozenset({line})
    assert len(next(iter(got))) == 400_005


def test_b1_no_count_cap_fifteen_lines_fifteen_members():
    lines = ["FAILED tests/t.py::test_%02d" % i for i in range(15)]
    assert len(_fss("\n".join(lines))) == 15
    # contrast: the display helper caps -- this extractor must not
    assert len(foundry.test_failure_lines("\n".join(lines))) < 15


def test_b1_duplicate_lines_collapse():
    assert _fss("FAILED a\nFAILED a\n  FAILED a\n") == frozenset({"FAILED a"})


@pytest.mark.parametrize("out", ["\x00\x01", "FAILED \udcff", "\r\nFAILED x\r\n", "\t" * 50,
                                 "ERROR " * 1000, "\u2028FAILED y", "FAILED "])
def test_b1_never_raises_for_any_str(out):
    got = _fss(out)
    assert isinstance(got, frozenset)


# ==========================================================================
# Behavior 2 -- preship_parent_drift: identical non-empty set only
# ==========================================================================
def test_b2_identical_set_any_order_is_drift():
    assert _drift(HEAD_OUT, PARENT_OUT) is True


def test_b2_identical_text_is_drift():
    assert _drift(HEAD_OUT, HEAD_OUT) is True


@pytest.mark.parametrize("h,p", [
    ("", ""), (None, None), ("1 failed", "1 failed"),       # both empty
    ("", HEAD_OUT), (None, HEAD_OUT),                       # head empty
    (HEAD_OUT, None),                                       # parent None
    (HEAD_OUT, ""),                                         # parent empty
    (HEAD_OUT, _out(FOUR[:3])),                             # strict subset
    (HEAD_OUT, _out(FOUR + ["FAILED tests/extra.py::t"])),  # strict superset
    (HEAD_OUT, PARENT_OUT_DIFF_AFTER_300),                  # same 300-char prefix
])
def test_b2_every_non_identical_case_is_not_drift(h, p):
    assert _drift(h, p) is False


def test_b2_300_char_prefix_trap_is_real_for_the_display_helper():
    """Anti-vacuity: the display helper DOES conflate these -- the drift oracle must not."""
    a = {ln[:300] for ln in foundry.test_failure_lines(HEAD_OUT)}
    b = {ln[:300] for ln in foundry.test_failure_lines(PARENT_OUT_DIFF_AFTER_300)}
    assert a == b
    assert _fss(HEAD_OUT) != _fss(PARENT_OUT_DIFF_AFTER_300)


@pytest.mark.parametrize("h,p", [("\x00", None), (None, "\udcff"), ("FAILED " * 9999, "")])
def test_b2_never_raises(h, p):
    assert _drift(h, p) in (True, False)


# ==========================================================================
# Behavior 3 -- PreshipResult gains suite_output, shape otherwise pinned
# ==========================================================================
def test_b3_field_order_and_flags():
    fields = dataclasses.fields(foundry.PreshipResult)
    names = [f.name for f in fields]
    assert names[:4] == ["verified", "incomplete", "detail", "test_seconds"]
    assert names[-2:] == ["verified_sha", "worktree_scope"]
    assert "suite_output" in names and names.count("suite_output") == 1
    assert len(names) == 7
    f = next(f for f in fields if f.name == "suite_output")
    assert f.default is None and f.repr is False and f.compare is False


def test_b3_positional_construction_still_works_and_defaults_none():
    a = foundry.PreshipResult(True, False, "d")
    b = foundry.PreshipResult(True, False, "d", 1.5)
    assert a.suite_output is None and b.suite_output is None
    assert b.test_seconds == 1.5


def test_b3_to_dict_eight_keys_and_render_byte_identical():
    base = dict(verified=False, incomplete=False, detail="d", test_seconds=1.5,
                verified_sha=SHA, worktree_scope="s")
    plain = foundry.PreshipResult(**base)
    carry = foundry.PreshipResult(**base, suite_output=HEAD_OUT)
    assert carry.to_dict() == plain.to_dict()
    assert len(carry.to_dict()) == 8 and "suite_output" not in carry.to_dict()
    assert carry.render() == plain.render()
    assert carry == plain
    assert "test_one.py" not in repr(carry)


# ==========================================================================
# Behavior 4 -- verify_local_clone captures the suite's .out
# ==========================================================================
@pytest.mark.parametrize("test_ok", [True, False])
def test_b4_suite_output_is_the_suite_out_when_issued(monkeypatch, tmp_path, test_ok):
    h = _H()
    _install(monkeypatch, h, head_test_ok=test_ok)
    res = foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "clone")
    assert "test" in h.kinds
    assert res.suite_output == HEAD_OUT
    assert res.exit_code == (0 if test_ok else 1)


@pytest.mark.parametrize("fail", [("clone",), ("setup",)])
def test_b4_suite_output_none_when_suite_never_issued(monkeypatch, tmp_path, fail):
    h = _H()
    _install(monkeypatch, h, fail=fail)
    res = foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "clone")
    assert "test" not in h.kinds
    assert res.suite_output is None
    want = foundry.preship_verdict(clone_ok=fail != ("clone",), setup_ok=False,
                                   test_ok=False, sha_ok=False, budget_exhausted=False)
    assert (res.verified, res.incomplete, res.detail) == \
        (want.verified, want.incomplete, want.detail)
    assert not h.parent_kinds()


def test_b4_verdicts_unchanged_vs_preship_verdict(monkeypatch, tmp_path):
    h = _H()
    _install(monkeypatch, h)
    res = foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "clone")
    want = foundry.preship_verdict(clone_ok=True, setup_ok=True, test_ok=False,
                                   sha_ok=False, budget_exhausted=False)
    assert (res.verified, res.incomplete, res.detail) == \
        (want.verified, want.incomplete, want.detail)
    assert not h.parent_kinds()


# ==========================================================================
# Behavior 5 -- PRESHIP_PARENT_BUDGET_SECONDS, read at call time
# ==========================================================================
def test_b5_budget_global_is_a_float_180():
    v = foundry.PRESHIP_PARENT_BUDGET_SECONDS
    assert isinstance(v, float) and v == 180.0


@pytest.mark.parametrize("budget", [30.0, 7.0, 180.0])
def test_b5_budget_is_read_at_call_time(monkeypatch, tmp_path, budget):
    h = _H()
    _install(monkeypatch, h, clock=lambda: 1000.0)
    monkeypatch.setattr(foundry, "PRESHIP_PARENT_BUDGET_SECONDS", budget)
    foundry.rerun_suite_at_parent(_cfg(tmp_path), PARENT, tmp_path / PARENT_DIR_NAME)
    assert len(h.calls) == 5
    want = foundry.preship_step_timeout(budget)
    assert [c["timeout"] for c in h.calls] == [want] * 5


# ==========================================================================
# Behavior 6 -- rerun_suite_at_parent
# ==========================================================================
def _rerun(monkeypatch, tmp_path, **kw):
    h = _H()
    _install(monkeypatch, h, **kw)
    cfg = _cfg(tmp_path)
    d = tmp_path / PARENT_DIR_NAME
    got = foundry.rerun_suite_at_parent(cfg, PARENT, d)
    return h, cfg, d, got


def test_b6_exact_five_command_sequence(monkeypatch, tmp_path):
    h, cfg, d, got = _rerun(monkeypatch, tmp_path)
    argvs = [c["argv"] for c in h.calls]
    assert argvs == [
        ["git", "clone", str(cfg.repo), str(d)],
        ["git", "-C", str(d), "checkout", "--detach", PARENT],
        ["uv", "sync"],
        ["uv", "run", "pytest"],
        ["uv", "python", "find"],
    ]
    for c in h.calls[2:]:
        assert str(c["cwd"]) == str(d), c
    assert got == (PARENT_OUT, INTERP)


def test_b6_passing_suite_out_is_returned_too(monkeypatch, tmp_path):
    h, cfg, d, got = _rerun(monkeypatch, tmp_path, parent_test_ok=True,
                            parent_out="14 passed\n")
    assert got == ("14 passed\n", INTERP)


@pytest.mark.parametrize("find", [(False, INTERP + "\n"), (True, ""), (True, "\n  \n")])
def test_b6_interpreter_unknown_when_find_fails_or_empty(monkeypatch, tmp_path, find):
    h, cfg, d, got = _rerun(monkeypatch, tmp_path, find=find)
    assert got == (PARENT_OUT, "unknown")


@pytest.mark.parametrize("fail", [("p:clone",), ("p:checkout",), ("p:setup",)])
def test_b6_pre_suite_failure_gives_none(monkeypatch, tmp_path, fail):
    h, cfg, d, got = _rerun(monkeypatch, tmp_path, fail=fail)
    assert got[0] is None
    order = ["p:clone", "p:checkout", "p:setup", "p:test", "p:find"]
    assert h.kinds == order[:len(h.kinds)], h.kinds  # issued in order, a prefix
    assert "p:test" not in h.kinds or got[0] is None


def test_b6_budget_exhausted_before_suite_issues_no_suite(monkeypatch, tmp_path):
    seq = iter([0.0, 0.0, 0.0] + [10_000.0] * 50)
    h, cfg, d, got = _rerun(monkeypatch, tmp_path, clock=lambda: next(seq))
    assert got[0] is None
    assert "p:test" not in h.kinds
    assert "p:find" not in h.kinds


def test_b6_zero_budget_issues_no_command(monkeypatch, tmp_path):
    monkeypatch.setattr(foundry, "PRESHIP_PARENT_BUDGET_SECONDS", 0.0)
    h, cfg, d, got = _rerun(monkeypatch, tmp_path)
    assert h.calls == []
    assert got == (None, "unknown")


def test_b6_suite_failing_after_whole_slice_gives_none(monkeypatch, tmp_path):
    h, cfg, d, got = _rerun(monkeypatch, tmp_path, test_cost=lambda t: float(t))
    assert "p:test" in h.kinds
    assert got[0] is None


def test_b6_suite_failing_quickly_keeps_its_out(monkeypatch, tmp_path):
    h, cfg, d, got = _rerun(monkeypatch, tmp_path, test_cost=lambda t: 1.0)
    assert got[0] == PARENT_OUT


def test_b6_timeouts_track_remaining_budget(monkeypatch, tmp_path):
    h, cfg, d, got = _rerun(monkeypatch, tmp_path, test_cost=lambda t: 50.0)
    ts = [c["timeout"] for c in h.calls]
    assert all(t is not None and t > 0 for t in ts), ts
    assert ts[0] == foundry.preship_step_timeout(180.0)
    k = h.kinds.index("p:find")
    assert ts[k] <= foundry.preship_step_timeout(130.0), ts


def _cleanup_wraps(h, d):
    assert h.events, h.events
    assert h.events[0] == ("cleanup", str(d)), h.events
    assert h.events[-1] == ("cleanup", str(d)), h.events


@pytest.mark.parametrize("kw", [{}, {"fail": ("p:clone",)}, {"fail": ("p:setup",)},
                                {"raise_kind": "p:test"}, {"raise_kind": "p:clone"}])
def test_b6_cleanup_runs_first_and_last(monkeypatch, tmp_path, kw):
    h, cfg, d, got = _rerun(monkeypatch, tmp_path, **kw)
    _cleanup_wraps(h, d)


@pytest.mark.parametrize("raise_kind", ["p:clone", "p:checkout", "p:setup", "p:test",
                                        "p:find"])
def test_b6_any_run_cmd_raise_gives_none_unknown(monkeypatch, tmp_path, raise_kind):
    h, cfg, d, got = _rerun(monkeypatch, tmp_path, raise_kind=raise_kind)
    assert got == (None, "unknown")


def test_b6_raising_clock_gives_none_unknown(monkeypatch, tmp_path):
    def boom():
        raise RuntimeError("clock-boom")
    h, cfg, d, got = _rerun(monkeypatch, tmp_path, clock=boom)
    assert got == (None, "unknown")


def test_b6_raising_cleanup_never_raises_and_is_never_partial(monkeypatch, tmp_path):
    """AMBIGUITY (noted in tester.md): the spec says "any exception from any seam yields
    (None, 'unknown')", while the iter-156 convention it reuses says a raising
    `cleanup_clone` never changes a verdict.  Pinned here: it never raises, and the
    answer is one of those two whole shapes -- never a half-filled tuple."""
    h, cfg, d, got = _rerun(monkeypatch, tmp_path, cleanup_raises=True)
    assert got in ((None, "unknown"), (PARENT_OUT, INTERP)), got


# ==========================================================================
# Behaviors 7-9 -- preship_cli end to end (incident replay)
# ==========================================================================
def test_b8_incident_replay_identical_set_gives_incomplete(monkeypatch, tmp_path):
    h = _H()
    _install(monkeypatch, h)
    cfg = _cfg(tmp_path)
    rc, out = _run_cli(cfg)
    assert rc == 2, out
    assert _last(out) == "PRESHIP: INCOMPLETE", out
    assert out.count("PRESHIP:") == 1, out
    assert h.parent_kinds() == ["parent_resolve", "p:clone", "p:checkout", "p:setup",
                                "p:test", "p:find"], h.kinds
    # the parent leg runs AFTER the HEAD leg
    assert h.kinds.index("parent_resolve") > h.kinds.index("test")
    resolve = next(c for c in h.calls if c["kind"] == "parent_resolve")
    assert resolve["argv"] == ["git", "-C", str(cfg.repo), "rev-parse", SHA + "^"]
    pclone = next(c for c in h.calls if c["kind"] == "p:clone")
    assert pclone["argv"][-1] == str(pathlib.Path(cfg.state) / PARENT_DIR_NAME)


def test_b8_incident_detail_names_parent_interp_count_and_lines(monkeypatch, tmp_path):
    h = _H()
    _install(monkeypatch, h)
    rc, out = _run_cli(_cfg(tmp_path), as_json=True)
    d = json.loads(out)
    assert rc == 2
    assert d["exit_code"] == 2 and d["incomplete"] is True and d["verified"] is False
    assert len(d) == 8, sorted(d)
    det = d["detail"]
    assert det.startswith("the declared suite FAILED inside a clean local clone, but its "
                          "PARENT"), det
    assert PARENT in det and INTERP in det and "4 test(s)" in det
    assert "; ".join(foundry.test_failure_lines(HEAD_OUT)) in det
    assert d["verified_sha"] == SHA
    assert d["worktree_scope"] and "uncommitted" in d["worktree_scope"]


def test_b8_test_seconds_and_sha_preserved(monkeypatch, tmp_path):
    h = _H()
    _install(monkeypatch, h)
    base = foundry.PreshipResult(False, False, "d-baseline", 12.5, suite_output=HEAD_OUT,
                                 verified_sha=SHA)
    _fake_verify(monkeypatch, base)
    rc, out = _run_cli(_cfg(tmp_path), as_json=True)
    d = json.loads(out)
    assert rc == 2 and d["test_seconds"] == 12.5 and d["verified_sha"] == SHA


def test_b8_count_matches_the_failing_set_size(monkeypatch, tmp_path):
    lines = ["FAILED tests/t.py::test_%02d" % i for i in range(13)]
    h = _H()
    _install(monkeypatch, h, head_out=_out(lines), parent_out=_out(lines[::-1]))
    rc, out = _run_cli(_cfg(tmp_path), as_json=True)
    assert rc == 2 and "13 test(s)" in json.loads(out)["detail"]


@pytest.mark.parametrize("parent_out,kw", [
    (PARENT_OUT_DIFF_AFTER_300, {}),                       # differs after char 300
    (_out(FOUR[:3]), {}),                                  # strict subset
    (_out(FOUR + ["FAILED tests/new.py::t"]), {}),         # strict superset
    ("14 passed\n", {"parent_test_ok": True}),             # parent green
    (PARENT_OUT, {"fail": ("p:clone",)}),                  # parent_out None
    (PARENT_OUT, {"fail": ("p:setup",)}),                  # parent_out None
])
def test_b9_not_identical_stays_broken_with_unchanged_detail(monkeypatch, tmp_path,
                                                             parent_out, kw):
    h = _H()
    _install(monkeypatch, h)
    baseline = foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "x")
    h = _H()
    _install(monkeypatch, h, parent_out=parent_out, **kw)
    rc, out = _run_cli(_cfg(tmp_path), as_json=True)
    d = json.loads(out)
    assert rc == 1 and d["exit_code"] == 1 and d["sentinel"] == "PRESHIP: BROKEN", d
    assert d["detail"] == baseline.detail
    assert "p:clone" in h.kinds  # the leg did run


def test_b9_text_form_broken_sentinel(monkeypatch, tmp_path):
    h = _H()
    _install(monkeypatch, h, parent_out=PARENT_OUT_DIFF_AFTER_300)
    rc, out = _run_cli(_cfg(tmp_path))
    assert rc == 1 and _last(out) == "PRESHIP: BROKEN", out


@pytest.mark.parametrize("resolve", [(False, "fatal: bad revision"), (True, ""),
                                     (True, "\n  \n")])
def test_b7_unresolvable_parent_leaves_result(monkeypatch, tmp_path, resolve):
    h = _H()
    _install(monkeypatch, h, resolve=resolve)
    rc, out = _run_cli(_cfg(tmp_path))
    assert rc == 1 and _last(out) == "PRESHIP: BROKEN"
    assert "parent_resolve" in h.kinds
    assert not [k for k in h.kinds if k.startswith("p:")], h.kinds


# ==========================================================================
# Behavior 10 -- no new command when the leg's conditions do not hold
# ==========================================================================
@pytest.mark.parametrize("kw,code", [
    ({"head_test_ok": True}, 0),                                  # VERIFIED
    ({"head_out": "boom\n2 failed\n=== FAILURES ===\n"}, 1),      # no FAILED line
    ({"head_out": ""}, 1),
    ({"fail": ("clone",)}, 2),                                    # suite never ran
    ({"fail": ("setup",)}, 2),
])
def test_b10_no_parent_leg_commands(monkeypatch, tmp_path, kw, code):
    h = _H()
    _install(monkeypatch, h, **kw)
    rc, out = _run_cli(_cfg(tmp_path))
    assert rc == code, out
    assert h.parent_kinds() == [], h.kinds
    assert not any(PARENT_DIR_NAME in " ".join(c["argv"]) + str(c["cwd"]) for c in h.calls)


def test_b10_incomplete_verdict_runs_no_parent_leg(monkeypatch, tmp_path):
    h = _H()
    _install(monkeypatch, h)
    _fake_verify(monkeypatch, _res(verified=False, incomplete=True))
    rc, out = _run_cli(_cfg(tmp_path))
    assert rc == 2 and h.parent_kinds() == []


def test_b10_sha_mismatch_result_with_failed_lines_runs_no_leg(monkeypatch, tmp_path):
    """A BROKEN whose suite PASSED (sha mismatch) has no FAILED lines in a real run;
    script a passing out to keep it realistic, and assert no leg."""
    h = _H()
    _install(monkeypatch, h, head_test_ok=True, head_out="14 passed\n", clone_sha=OTHER_SHA)
    rc, out = _run_cli(_cfg(tmp_path))
    assert rc == 1 and _last(out) == "PRESHIP: BROKEN"
    assert h.parent_kinds() == []


# ==========================================================================
# Behavior 11 -- fail-safe
# ==========================================================================
@pytest.mark.parametrize("seam", ["rerun_suite_at_parent", "preship_parent_drift"])
def test_b11_raising_new_seam_leaves_broken(monkeypatch, tmp_path, seam):
    h = _H()
    _install(monkeypatch, h)

    def boom(*a, **kw):
        raise RuntimeError("seam-boom")
    monkeypatch.setattr(foundry, seam, boom)
    rc, out = _run_cli(_cfg(tmp_path))
    assert rc == 1 and _last(out) == "PRESHIP: BROKEN", out


def test_b11_raising_parent_rev_parse_leaves_broken(monkeypatch, tmp_path):
    h = _H()
    _install(monkeypatch, h, raise_kind="parent_resolve")
    rc, out = _run_cli(_cfg(tmp_path))
    assert rc == 1 and _last(out) == "PRESHIP: BROKEN", out
    assert "parent_resolve" in h.kinds


def test_b11_raising_failing_summary_set_never_raises_out(monkeypatch, tmp_path):
    h = _H()
    _install(monkeypatch, h)

    def boom(*a, **kw):
        raise RuntimeError("fss-boom")
    monkeypatch.setattr(foundry, "failing_summary_set", boom)
    rc, out = _run_cli(_cfg(tmp_path))
    assert rc == 1, out


# ==========================================================================
# Behavior 12 -- off the loop
# ==========================================================================
@pytest.mark.parametrize("fn", ["run_iteration", "run_stage", "run_continuous"])
def test_b12_loop_functions_do_not_reach_the_parent_leg(fn):
    names = _code_names(getattr(foundry, fn))
    assert names, fn
    for n in NEW_NAMES:
        assert n not in names, (fn, n)


def test_b12_walker_sees_the_wiring_in_preship_cli():
    """Anti-vacuity: the same walker DOES see the new names where they are wired."""
    seen, todo, names = set(), [foundry.preship_cli], set()
    while todo:  # follow foundry-level callees transitively (private helpers included)
        fn = todo.pop()
        if fn in seen:
            continue
        seen.add(fn)
        got = _code_names(fn)
        names |= got
        for n in got:
            obj = getattr(foundry, n, None) if n.isidentifier() else None
            if isinstance(obj, types.FunctionType) and obj.__module__ == foundry.__name__:
                todo.append(obj)
    assert "rerun_suite_at_parent" in names and "preship_parent_drift" in names


def test_b12_dispatcher_does_not_name_the_new_functions():
    for n in NEW_NAMES:
        assert not hasattr(dispatcher, n), n
    names = set()
    for obj in vars(dispatcher).values():
        if isinstance(obj, types.FunctionType) and obj.__module__ == dispatcher.__name__:
            names |= _code_names(obj)
    assert names  # anti-vacuity: the walker saw dispatcher's functions
    for n in NEW_NAMES:
        assert n not in names, n


def test_b12_both_modules_import():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"], cwd=str(_ROOT),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
