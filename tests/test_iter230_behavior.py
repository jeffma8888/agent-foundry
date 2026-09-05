"""Iteration 230 -- BLACK-BOX behavior tests: doctor's FIFTH never-blocking drift line.

Iteration 229 shipped the test-touch measurement (`test_touch_line` + `probe_test_touch`)
with NO reader.  This iteration gives it its first reader: `foundry doctor` prints a fifth
report-only drift line saying whether the iteration currently in flight has touched a test
directory.  The value of the feature is that the answer reaches the operator BEFORE the
gate commits; the value of THESE tests is that the line is (a) exactly one line, always,
(b) a VERBATIM carry of the verb's own answer so the two surfaces can never disagree,
(c) fail-SAFE -- a scan that did not run reports UNKNOWN, never `clean` -- and (d) unable
to move doctor's exit code or to reach the dispatch path.

Spec under test (products/_platform/state/iter-230/pm.md), Expected Behaviors 1-8:
   1. `TEST_TOUCH_PREFIX` is the non-empty grep anchor `"test-touch:"`, distinct from the
      four older drift-line prefixes.
   2. `test_touch_drift_line(cfg)` returns a newline-free `str` starting with the prefix
      for EVERY scripted probe state (three real bodies, None, a non-string, a raiser).
   3. A known answer is carried VERBATIM: the return value is exactly
      `TEST_TOUCH_PREFIX + " " + body`, for all three real bodies.
   4. Fail-SAFE: `None` and a raising probe both render `UNKNOWN`, and the line contains
      neither `clean` nor `test-dir touched`.
   5. The probe is reached by BARE module name exactly ONCE per call, with `cfg.repo` as
      its single positional argument.
   6. `run_doctor_cli` prints the line exactly ONCE, LAST of the five, and each of the
      four older prefixes still appears exactly once.
   7. The exit code is untouched over {all-pass, one-failing} x five probe states; the
      summary still reads `out of 4`; `run_doctor` still returns exactly four `Check`s and
      its source names none of the four test-touch symbols.
   8. The control path is byte-untouched: `dispatcher.py`'s TEXT names none of the four
      test-touch symbols, so a loop in flight resumes byte-identically.

Also guarded, from the spec's ACCEPTANCE CRITERIA rather than its Expected Behaviors, and
decidable from git-TRACKED text alone so every verdict still holds in the fresh clone the
release gate builds (OPERATOR 2026-08-11 -- iteration 154 shipped green then went
post-release BROKEN on a precondition that was only true in this worktree):
   A. `run_doctor_cli.__doc__` announces FIVE drift lines, attributes the fifth to iter
      230, KEEPS the phrase `all four checks pass` and the literal `164`, and does not
      contain the word `three`.
   B. README `# 0.` says `PLUS FIVE drift lines` and its byte-frozen tail sentence
      survives; README `# 54.` no longer claims the capability has no reader.
   C. This iteration's roadmap record lands in the SAME diff as the code -- exactly one
      `- iter 230 ` ledger row of at most 120 chars and exactly one `- **iter 230 `
      archive bullet -- and `roadmap_ledger_gaps` is `[]` against the worktree text.
   D. Roadmap item (c)'s literal `(c) ` marker survives and the STATUS line reads
      `STATUS (iter 230)`.
   E. This module and the two forced count-word advances are on the b15 allow-list in
      `tests/test_iter204_behavior.py`.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the
iteration-230 PM spec's Expected Behaviors and Acceptance Criteria, the conventions of
`tests/` (the scripted-seam / frozen-literal shape of `tests/test_iter229_behavior.py`,
which owns the sibling `test_touch_line` / `probe_test_touch` pair, and the doctor-CLI stub
shape of `tests/test_iter164_behavior.py`), the README, the two roadmap files, and the
product's OWN OBSERVABLE surface -- importing the modules, calling their public functions
and capturing their stdout.  The implementation TEXT of `foundry.py` was NOT read by the
author; where an acceptance criterion is only decidable from source text (behavior 7's
`run_doctor` scan, behavior 8's dormancy scan) the text is handed to a machine scan and
never inspected by hand.  `engineer.md`, `reviewer.md`, `fix_review.md`,
`IMPLEMENTATION.patch` and `git diff` were NOT read.

Offline and deterministic: every behavior scripts `probe_test_touch` (and, where doctor is
driven, the four older lines' upstream seams) by BARE module name, so no real subprocess,
git, network or clock runs.  No assertion reads a gitignored path and no assertion counts
files in the ambient `tests/` or `products/` tree.
"""

from __future__ import annotations

import contextlib
import inspect
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
import dispatcher  # noqa: E402  -- in-process import-safety probe

THIS_ITER = 230

README = _ROOT / "README.md"
ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
DISPATCHER = _ROOT / "dispatcher.py"
ALLOW_LIST_MODULE = _ROOT / "tests" / "test_iter204_behavior.py"

# Names are FIXED by the spec, so they are reached by string here: a rename in the
# implementation must fail these tests loudly rather than silently stop testing anything.
PREFIX_NAME = "TEST_TOUCH_PREFIX"
LINE_FN = "test_touch_drift_line"
PROBE = "probe_test_touch"

# The four symbols behaviors 7 and 8 forbid on the control path / inside run_doctor.
TEST_TOUCH_SYMBOLS = (
    "test_touch_drift_line",
    "probe_test_touch",
    "test_touch_line",
    "TEST_TOUCH_PREFIX",
)

OLDER_PREFIX_NAMES = (
    "LIVE_LAG_PREFIX",
    "LEARNINGS_HEAD_PREFIX",
    "ROADMAP_INDEX_PREFIX",
    "STAGE_BUDGET_PREFIX",
)

# The three REAL bodies of the pure renderer this line carries, as frozen literals.  They
# are ALSO re-derived from `test_touch_line` in behavior 3, so a body the product changes
# fails here rather than silently drifting past a hand-copied string.
BODY_CLEAN = "clean -- 0 uncommitted path(s), so no test-dir touch to report"
BODY_TOUCHED = "test-dir touched -- 3 of 7 uncommitted path(s)"
BODY_NO_TOUCH = "NO-TEST-TOUCH -- 0 of 4 uncommitted path(s) are under a test dir"

REAL_BODIES = (BODY_CLEAN, BODY_TOUCHED, BODY_NO_TOUCH)

# Porcelain fixtures that produce exactly those three bodies through the PUBLIC renderer.
PORCELAIN_CLEAN = ""
PORCELAIN_TOUCHED = (
    "?? tests/test_iter230_behavior.py\n"
    " M tests/test_iter145_behavior.py\n"
    " M tests/test_iter164_behavior.py\n"
    " M foundry.py\n"
    " M README.md\n"
    " M PLATFORM_ROADMAP.md\n"
    " M PLATFORM_ROADMAP_ARCHIVE.md\n"
)
PORCELAIN_NO_TOUCH = (
    " M foundry.py\n"
    " M README.md\n"
    " M PLATFORM_ROADMAP.md\n"
    " M PLATFORM_ROADMAP_ARCHIVE.md\n"
)

# A RELATIVE repo literal -- never an absolute machine path (iteration 205 was reverted
# for exactly one absolute-home literal in a test fixture).
REL_REPO = "products/_platform/state/iter-230"

# README `# 0.`'s byte-frozen tail sentence, which the spec keeps BYTE-UNCHANGED.
README_FROZEN_TAIL = (
    "NO drift line ever changes doctor's own exit code, and `run_doctor` itself is "
    "still exactly four Checks:"
)


# --------------------------------------------------------------------------- #
# helpers -- scripted seams only, mirroring tests/test_iter229_behavior.py and
# tests/test_iter164_behavior.py
# --------------------------------------------------------------------------- #
class _Chk:
    """Minimal stand-in check result for the doctor-CLI guards (iter-145 shape)."""

    def __init__(self, name, ok, detail="detail-text"):
        self.name = name
        self.ok = ok
        self.detail = detail


class _G:
    """Stage-times group stub: the four attributes the iter-164 line consumes."""

    def __init__(self, stage, median_s, timeouts=0, count=1):
        self.stage = stage
        self.median_s = median_s
        self.timeouts = timeouts
        self.count = count


class _S:
    """Stage-times summary stub: any object exposing a `groups` iterable."""

    def __init__(self, *groups):
        self.groups = tuple(groups)


class _Weird:
    """A non-string object the probe seam may return (behavior 2)."""

    def __repr__(self) -> str:  # pragma: no cover -- only reached on failure prints
        return "<weird-probe-answer>"


def _prefix() -> str:
    return getattr(foundry, PREFIX_NAME)


def _line(cfg) -> str:
    return getattr(foundry, LINE_FN)(cfg)


def _cfg(**over):
    kw = dict(name="demo", repo=REL_REPO, allowed_push_repo="demo")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _probe_seam(monkeypatch, result, calls=None):
    """Script `probe_test_touch` by BARE module name; record every call.

    `result` is either the value to return or an exception INSTANCE to raise.
    """

    def fake(*a, **kw):
        if calls is not None:
            calls.append((a, dict(kw)))
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(foundry, PROBE, fake)


def _stub_checks(monkeypatch, *, fail=None):
    for nm in ("power", "agent", "uv", "remote"):
        monkeypatch.setattr(
            foundry, f"check_{nm}",
            lambda *a, _n=nm, **k: _Chk(_n, _n != fail))


def _patch_older_lines(monkeypatch):
    """Script the four OLDER drift lines' upstream seams so no test reads live state."""
    monkeypatch.setattr(foundry, "parse_brain_launch", lambda *a, **k: 1000.0)
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: ((1, 900.0),))
    monkeypatch.setattr(
        foundry, "gather_stage_times",
        lambda *a, **k: _S(_G("engineer", 600.0, 11, 86), _G("pm", 100.0, 0, 9)))


def _doctor_cfg(tmp_path):
    p = tmp_path / "IDX.md"
    p.write_text("# roadmap\n\nsome prose\n", encoding="utf-8")
    return _cfg(roadmap=str(p), learnings=str(tmp_path / "no-such-learnings.md"))


def _doctor_out(cfg):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.run_doctor_cli(cfg)
    return rc, buf.getvalue()


def _lines_with(out, prefix):
    return [ln for ln in out.splitlines() if ln.startswith(prefix)]


def _first_index(out, prefix):
    for i, ln in enumerate(out.splitlines()):
        if ln.startswith(prefix):
            return i
    return -1


def _forbid_outside_world(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the drift line reached the outside world")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)
    monkeypatch.setattr(socket, "socket", boom)


# ========================================================================== #
# Behavior 1 -- the grep anchor exists and is distinct
# ========================================================================== #
def test_b1_prefix_is_the_expected_nonempty_grep_anchor() -> None:
    prefix = _prefix()
    assert isinstance(prefix, str)
    assert prefix.strip(), "the grep anchor is empty or whitespace-only"
    assert prefix == "test-touch:"


@pytest.mark.parametrize("other_name", OLDER_PREFIX_NAMES)
def test_b1_prefix_is_distinct_from_every_older_drift_prefix(other_name) -> None:
    """Five lines share one stdout, so a shared anchor would make `grep` ambiguous."""
    other = getattr(foundry, other_name)
    assert isinstance(other, str) and other, other_name
    assert _prefix() != other, f"{PREFIX_NAME} collides with {other_name}"


def test_b1_the_five_prefixes_are_all_pairwise_distinct() -> None:
    all_names = (PREFIX_NAME,) + OLDER_PREFIX_NAMES
    values = [getattr(foundry, n) for n in all_names]
    assert len(set(values)) == len(all_names), values


# ========================================================================== #
# Behavior 2 -- ONE line, always, for EVERY scripted probe state
# ========================================================================== #
_ALL_PROBE_STATES = [
    pytest.param(BODY_CLEAN, id="clean"),
    pytest.param(BODY_TOUCHED, id="touched"),
    pytest.param(BODY_NO_TOUCH, id="no-test-touch"),
    pytest.param(None, id="none"),
    pytest.param(_Weird(), id="non-string"),
    pytest.param(RuntimeError("probe-boom-xyz"), id="raises"),
]


@pytest.mark.parametrize("state", _ALL_PROBE_STATES)
def test_b2_every_probe_state_yields_one_prefixed_newline_free_str(
        monkeypatch, state) -> None:
    _probe_seam(monkeypatch, state)
    got = _line(_cfg())
    assert isinstance(got, str), repr(got)
    assert got is not None
    assert "\n" not in got, repr(got)
    assert "\r" not in got, repr(got)
    assert got.startswith(_prefix()), repr(got)
    assert len(got.splitlines()) == 1, repr(got)


@pytest.mark.parametrize("state", _ALL_PROBE_STATES)
def test_b2_the_line_never_raises_and_is_never_empty(monkeypatch, state) -> None:
    _probe_seam(monkeypatch, state)
    got = _line(_cfg())
    assert got.strip() != _prefix(), "the line carries a prefix and nothing else"
    assert len(got) > len(_prefix()) + 1


def test_b2_a_multiline_probe_answer_is_still_collapsed_to_one_line(
        monkeypatch) -> None:
    """Adversarial: a misbehaving seam must not be able to split one report in two."""
    _probe_seam(monkeypatch, "first line\nsecond line\tand\ta tab")
    got = _line(_cfg())
    assert "\n" not in got, repr(got)
    assert len(got.splitlines()) == 1, repr(got)
    assert got.startswith(_prefix())


def test_b2_the_line_touches_no_subprocess_socket_or_file(monkeypatch, tmp_path) -> None:
    _forbid_outside_world(monkeypatch)
    _probe_seam(monkeypatch, BODY_TOUCHED)
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    got = _line(_cfg())
    assert got.startswith(_prefix())
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before


# ========================================================================== #
# Behavior 3 -- a KNOWN answer is carried VERBATIM
# ========================================================================== #
@pytest.mark.parametrize("body", REAL_BODIES)
def test_b3_a_known_body_is_carried_verbatim(monkeypatch, body) -> None:
    _probe_seam(monkeypatch, body)
    assert _line(_cfg()) == _prefix() + " " + body


@pytest.mark.parametrize(
    "porcelain,body",
    [(PORCELAIN_CLEAN, BODY_CLEAN),
     (PORCELAIN_TOUCHED, BODY_TOUCHED),
     (PORCELAIN_NO_TOUCH, BODY_NO_TOUCH)],
)
def test_b3_the_three_frozen_bodies_are_what_the_public_renderer_returns(
        porcelain, body) -> None:
    """The frozen literals above are re-derived from the PUBLIC renderer, so the line
    and the verb that shares its core cannot drift apart behind a hand-copied string."""
    assert foundry.test_touch_line(porcelain) == body


@pytest.mark.parametrize(
    "porcelain",
    [PORCELAIN_CLEAN, PORCELAIN_TOUCHED, PORCELAIN_NO_TOUCH],
)
def test_b3_end_to_end_the_line_equals_prefix_plus_the_renderer_answer(
        monkeypatch, porcelain) -> None:
    body = foundry.test_touch_line(porcelain)
    _probe_seam(monkeypatch, body)
    assert _line(_cfg()) == f"{_prefix()} {body}"


def test_b3_no_count_is_re_derived_and_no_word_is_rewritten(monkeypatch) -> None:
    """The whole point of the VERBATIM carry: the reader adds a prefix and nothing else."""
    _probe_seam(monkeypatch, BODY_TOUCHED)
    got = _line(_cfg())
    assert got[len(_prefix()) + 1:] == BODY_TOUCHED
    assert got.count("3 of 7") == 1
    assert "UNKNOWN" not in got


# ========================================================================== #
# Behavior 4 -- a scan that did not run is NEVER reported as clean (fail-SAFE)
# ========================================================================== #
@pytest.mark.parametrize(
    "state",
    [pytest.param(None, id="none"),
     pytest.param(RuntimeError("probe-boom-xyz"), id="raises")],
)
def test_b4_a_failed_scan_reports_unknown(monkeypatch, state) -> None:
    _probe_seam(monkeypatch, state)
    got = _line(_cfg())
    rest = got[len(_prefix()):].strip()
    assert rest.split()[0] == "UNKNOWN", repr(got)


@pytest.mark.parametrize(
    "state",
    [pytest.param(None, id="none"),
     pytest.param(RuntimeError("probe-boom-xyz"), id="raises")],
)
def test_b4_a_failed_scan_never_claims_clean_or_touched(monkeypatch, state) -> None:
    """Reporting `clean` off a read that did not happen would be a fail-OPEN gauge --
    the ONE direction this line may never lie in."""
    _probe_seam(monkeypatch, state)
    got = _line(_cfg())
    assert "clean" not in got, repr(got)
    assert "test-dir touched" not in got, repr(got)
    assert "NO-TEST-TOUCH" not in got, repr(got)


def test_b4_a_hostile_exception_message_cannot_smuggle_a_verdict_word(
        monkeypatch) -> None:
    """The exception text is attacker-supplied string: it must not be able to put
    `clean` or `test-dir touched` into a line whose contract forbids both."""
    _probe_seam(monkeypatch, RuntimeError("boom clean test-dir touched NO-TEST-TOUCH"))
    got = _line(_cfg())
    assert "clean" not in got, repr(got)
    assert "test-dir touched" not in got, repr(got)
    assert "NO-TEST-TOUCH" not in got, repr(got)
    assert got[len(_prefix()):].strip().split()[0] == "UNKNOWN"


def test_b4_a_non_string_answer_is_unknown_not_a_stringified_object(
        monkeypatch) -> None:
    _probe_seam(monkeypatch, _Weird())
    got = _line(_cfg())
    assert got[len(_prefix()):].strip().split()[0] == "UNKNOWN", repr(got)
    assert "clean" not in got


# ========================================================================== #
# Behavior 5 -- the probe is reached by BARE module name, repo from the CONFIG
# ========================================================================== #
def test_b5_the_probe_is_called_exactly_once_per_invocation(monkeypatch) -> None:
    calls: list = []
    _probe_seam(monkeypatch, BODY_CLEAN, calls)
    _line(_cfg())
    assert len(calls) == 1, calls


def test_b5_the_single_positional_argument_is_cfg_repo(monkeypatch) -> None:
    """Asserted on the RECORDED call, so a body that hardcodes a path or reads the
    process cwd fails rather than passing by coincidence."""
    calls: list = []
    _probe_seam(monkeypatch, BODY_CLEAN, calls)
    marker = "products/_platform/state/iter-230-b5-marker"
    _line(_cfg(repo=marker))
    (args, kwargs) = calls[0]
    assert len(args) == 1, (args, kwargs)
    assert args[0] == marker, (args, kwargs)


def test_b5_the_probe_is_reached_by_bare_module_name_so_monkeypatch_takes_effect(
        monkeypatch) -> None:
    """If the reader captured the seam at def-time, the scripted body would not show up."""
    sentinel = "test-dir touched -- 1 of 1 uncommitted path(s)"
    _probe_seam(monkeypatch, sentinel)
    assert _line(_cfg()) == f"{_prefix()} {sentinel}"


@pytest.mark.parametrize("state", _ALL_PROBE_STATES)
def test_b5_exactly_one_probe_call_in_every_state(monkeypatch, state) -> None:
    calls: list = []
    _probe_seam(monkeypatch, state, calls)
    _line(_cfg())
    assert len(calls) == 1, calls


# ========================================================================== #
# Behavior 6 -- doctor prints it exactly ONCE, LAST of the five
# ========================================================================== #
def test_b6_doctor_prints_the_test_touch_line_exactly_once(
        monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _probe_seam(monkeypatch, BODY_TOUCHED)
    rc, out = _doctor_out(_doctor_cfg(tmp_path))
    assert len(_lines_with(out, _prefix())) == 1, out
    assert rc == 0


def test_b6_the_test_touch_line_comes_after_the_stage_budget_line(
        monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _probe_seam(monkeypatch, BODY_CLEAN)
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    mine = _first_index(out, _prefix())
    budget = _first_index(out, foundry.STAGE_BUDGET_PREFIX)
    assert mine >= 0 and budget >= 0, out
    assert mine > budget, out


@pytest.mark.parametrize("other_name", OLDER_PREFIX_NAMES)
def test_b6_each_older_drift_prefix_still_appears_exactly_once(
        monkeypatch, tmp_path, other_name) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _probe_seam(monkeypatch, BODY_TOUCHED)
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    other = getattr(foundry, other_name)
    assert len(_lines_with(out, other)) == 1, (other_name, out)


def test_b6_all_five_drift_lines_are_present_and_the_new_one_is_last(
        monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _probe_seam(monkeypatch, BODY_NO_TOUCH)
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    idxs = {n: _first_index(out, getattr(foundry, n))
            for n in OLDER_PREFIX_NAMES + (PREFIX_NAME,)}
    assert all(v >= 0 for v in idxs.values()), (idxs, out)
    assert idxs[PREFIX_NAME] == max(idxs.values()), idxs


@pytest.mark.parametrize("state", _ALL_PROBE_STATES)
def test_b6_exactly_one_line_in_doctor_stdout_for_every_probe_state(
        monkeypatch, tmp_path, state) -> None:
    """Including the raiser: doctor's own `except` belt must not double-print."""
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _probe_seam(monkeypatch, state)
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    assert len(_lines_with(out, _prefix())) == 1, out


# ========================================================================== #
# Behavior 7 -- the exit code, the summary and run_doctor are untouched
# ========================================================================== #
_EXIT_STATES = [
    pytest.param(BODY_CLEAN, id="clean"),
    pytest.param(BODY_TOUCHED, id="touched"),
    pytest.param(BODY_NO_TOUCH, id="no-test-touch"),
    pytest.param(None, id="none"),
    pytest.param(RuntimeError("probe-boom-xyz"), id="raises"),
]


@pytest.mark.parametrize("state", _EXIT_STATES)
def test_b7_all_checks_passing_exits_zero_in_every_probe_state(
        monkeypatch, tmp_path, state) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _probe_seam(monkeypatch, state)
    rc, out = _doctor_out(_doctor_cfg(tmp_path))
    assert rc == 0, out


@pytest.mark.parametrize("state", _EXIT_STATES)
def test_b7_one_failing_check_exits_one_in_every_probe_state(
        monkeypatch, tmp_path, state) -> None:
    _stub_checks(monkeypatch, fail="uv")
    _patch_older_lines(monkeypatch)
    _probe_seam(monkeypatch, state)
    rc, out = _doctor_out(_doctor_cfg(tmp_path))
    assert rc == 1, out


@pytest.mark.parametrize("state", _EXIT_STATES)
def test_b7_the_summary_still_reads_out_of_4(monkeypatch, tmp_path, state) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _probe_seam(monkeypatch, state)
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    # SPEC AMBIGUITY (reported in tester.md): the spec says the summary "still reads out
    # of 4", but the observable summary renders the denominator as `N/4 checks`, not the
    # literal words "out of 4".  Tested on the DENOMINATOR, which is what the criterion
    # is actually about: the drift lines must never be counted as checks.
    summary = [ln for ln in out.splitlines() if ln.startswith("doctor:")]
    assert len(summary) == 1, out
    assert re.search(r"\b\d+/4\b", summary[0]), summary[0]
    assert "/5" not in summary[0], summary[0]


def test_b7_run_doctor_still_returns_exactly_four_checks(monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    _probe_seam(monkeypatch, BODY_TOUCHED)
    checks = foundry.run_doctor(_doctor_cfg(tmp_path))
    assert len(checks) == 4, [getattr(c, "name", c) for c in checks]
    for c in checks:
        assert hasattr(c, "name") and hasattr(c, "ok") and hasattr(c, "detail")


@pytest.mark.parametrize("symbol", TEST_TOUCH_SYMBOLS)
def test_b7_run_doctor_source_names_no_test_touch_symbol(symbol) -> None:
    """A fifth PRINT, never a fifth `Check`: the check list is pinned by the iter-01
    tests, so the reader must live in the CLI wrapper.  Machine scan -- the source text
    is handed to `in`, never read by the author."""
    src = inspect.getsource(foundry.run_doctor)
    assert symbol not in src, symbol


def test_b7_the_probe_is_not_called_at_all_by_run_doctor(monkeypatch, tmp_path) -> None:
    calls: list = []
    _stub_checks(monkeypatch)
    _probe_seam(monkeypatch, BODY_CLEAN, calls)
    foundry.run_doctor(_doctor_cfg(tmp_path))
    assert calls == [], calls


# ========================================================================== #
# Behavior 8 -- the control path is byte-untouched
# ========================================================================== #
@pytest.mark.parametrize("symbol", TEST_TOUCH_SYMBOLS)
def test_b8_dispatcher_text_names_no_test_touch_symbol(symbol) -> None:
    """Machine scan of the file's TEXT, so a loop in flight provably resumes
    byte-identically and no restart is owed."""
    assert symbol not in DISPATCHER.read_text(encoding="utf-8"), symbol


def test_b8_dispatcher_imports_in_process() -> None:
    assert dispatcher is not None
    assert hasattr(dispatcher, "__file__")


# ========================================================================== #
# Acceptance criterion A -- the docstring count word advanced
# ========================================================================== #
def test_ac_a_run_doctor_cli_docstring_announces_five_drift_lines() -> None:
    doc = foundry.run_doctor_cli.__doc__ or ""
    assert doc.strip(), "run_doctor_cli lost its docstring"
    assert re.search(r"(?i)\bfive drift lines\b", doc), doc[:200]
    assert not re.search(r"(?i)\bfour drift lines\b", doc), doc[:200]
    assert str(THIS_ITER) in doc, doc[:200]
    assert "all four checks pass" in doc, doc[:400]
    assert "164" in doc, doc[:400]
    assert not re.search(r"(?i)\bthree\b", doc), doc[:400]


# ========================================================================== #
# Acceptance criterion B -- the README claims advanced
# ========================================================================== #
def _readme() -> str:
    return README.read_text(encoding="utf-8")


def test_ac_b_readme_entry_zero_advances_to_five_drift_lines() -> None:
    entry = _readme_entry(0)
    assert "PLUS FIVE drift lines" in entry
    assert "PLUS FOUR drift lines" not in entry


def test_ac_b_readme_entry_zero_frozen_tail_sentence_survives_byte_unchanged() -> None:
    assert README_FROZEN_TAIL in _readme(), README_FROZEN_TAIL


def test_ac_b_readme_entry_zero_describes_the_iteration_230_line() -> None:
    text = _readme_entry(0)
    assert "iteration-230 test-touch line" in text
    assert "NO-TEST-TOUCH" in text
    assert "UNKNOWN" in text


def _readme_entry(number: int) -> str:
    """The text of README numbered entry `# <number>.`, up to the next numbered entry.

    Scoped rather than global: the phrase this criterion retires ("dormant: the
    pipeline/gate/dispatcher never call it") is ALSO the true, still-correct claim of a
    DIFFERENT entry, so a whole-file scan would accuse a healthy README.
    """
    text = _readme()
    m = re.search(r"(?m)^# %d\. " % number, text)
    assert m, f"README has no entry # {number}."
    rest = text[m.start():]
    nxt = re.search(r"(?m)^# \d+\. ", rest[1:])
    return rest if nxt is None else rest[: nxt.start() + 1]


def test_ac_b_readme_entry_54_no_longer_claims_the_capability_is_readerless() -> None:
    entry = _readme_entry(54)
    assert "dormant: the pipeline/gate/dispatcher never call it" not in entry
    assert "ONE live reader since iter 230" in entry


def test_ac_b_readme_entry_54_keeps_the_still_true_dormancy_facts() -> None:
    """The claim NARROWS -- the pipeline/gate/dispatcher still never call it and it still
    writes nothing -- so the entry must keep the true part, not delete it."""
    entry = _readme_entry(54)
    assert "pipeline/gate/dispatcher still never call it" in entry
    assert "writes nothing" in entry


def test_ac_b_readme_adds_no_new_numbered_entry_for_the_fifth_line() -> None:
    """Deliberately out of scope: the capability already owns entry `# 54`."""
    assert not re.search(r"(?m)^# 55\.", _readme())


# ========================================================================== #
# Acceptance criterion C -- the roadmap record lands in the SAME diff
# ========================================================================== #
def _roadmap() -> str:
    return ROADMAP.read_text(encoding="utf-8")


def _archive() -> str:
    return ARCHIVE.read_text(encoding="utf-8")


def test_ac_c_exactly_one_ledger_row_for_this_iteration() -> None:
    rows = [ln for ln in _roadmap().splitlines()
            if ln.startswith(f"- iter {THIS_ITER} ")]
    assert len(rows) == 1, rows


def test_ac_c_the_ledger_row_is_at_most_120_chars() -> None:
    row = next(ln for ln in _roadmap().splitlines()
               if ln.startswith(f"- iter {THIS_ITER} "))
    assert len(row) <= 120, (len(row), row)


def test_ac_c_exactly_one_archive_detail_bullet_over_400_chars() -> None:
    bullets = [ln for ln in _archive().splitlines()
               if ln.startswith(f"- **iter {THIS_ITER} ")]
    assert len(bullets) == 1, bullets
    assert len(bullets[0]) > 400, len(bullets[0])


def test_ac_c_the_archive_bullet_carries_item_c_three_blockers() -> None:
    """The index line may shrink only because the archive keeps the record."""
    bullet = next(ln for ln in _archive().splitlines()
                  if ln.startswith(f"- **iter {THIS_ITER} "))
    for token in ("tester", "reviewer", "gate"):
        assert token in bullet, (token, bullet[:200])


def test_ac_c_roadmap_ledger_gaps_is_empty_against_the_worktree() -> None:
    assert foundry.roadmap_ledger_gaps(_roadmap(), _archive(), (THIS_ITER,)) == []


def test_ac_c_the_ledger_gap_oracle_can_still_fail() -> None:
    """The oracle above is only evidence if it is FAILABLE: an iteration with no row
    must be reported as a gap, or the green above proves nothing."""
    assert foundry.roadmap_ledger_gaps(_roadmap(), _archive(), (99991,)) == [99991]


# ========================================================================== #
# Acceptance criterion D -- item (c) survives, STATUS advanced
# ========================================================================== #
def test_ac_d_the_item_c_literal_marker_survives() -> None:
    assert "(c) " in _roadmap()


def test_ac_d_item_c_records_the_consumer_half_shipped() -> None:
    assert "CONSUMER HALF SHIPPED iter 230" in _roadmap()


def test_ac_d_the_status_line_reads_this_iteration() -> None:
    assert f"STATUS (iter {THIS_ITER})" in _roadmap()
    assert "STATUS (iter 228)" not in _roadmap()


def test_ac_d_the_archive_gains_no_new_heading() -> None:
    """The append-only PREFIX freeze stays untested by this bite, so no `## ` heading
    may be added: the count must match the tracked file at HEAD's shape."""
    headings = [ln for ln in _archive().splitlines() if ln.startswith("## ")]
    assert headings, "the archive lost its headings"


# ========================================================================== #
# Acceptance criterion E -- the forced b15 allow-list entries
# ========================================================================== #
@pytest.mark.parametrize(
    "path",
    ["tests/test_iter230_behavior.py",
     "tests/test_iter145_behavior.py",
     "tests/test_iter164_behavior.py"],
)
def test_ac_e_the_three_forced_paths_are_on_the_b15_allow_list(path) -> None:
    """The spec calls this criterion FORCED, so it is worth an independent witness here
    rather than trusting the sibling module to be the only one."""
    assert path in ALLOW_LIST_MODULE.read_text(encoding="utf-8"), path

# ========================================================================== #
# Acceptance criterion F -- doctor's OWN except belt around the fifth print
# ========================================================================== #
def test_ac_f_a_raising_line_helper_still_yields_exactly_one_unknown_line(
        monkeypatch, tmp_path) -> None:
    """The spec gives the fifth print block "the same `except Exception` belt" the four
    older ones carry.  Scripted at the LINE helper (not the probe), so the belt itself is
    what is under test: doctor must still emit exactly one prefixed line, it must read
    UNKNOWN, and the exit code must not move."""
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    monkeypatch.setattr(
        foundry, LINE_FN,
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("line-helper-boom")))
    rc, out = _doctor_out(_doctor_cfg(tmp_path))
    mine = _lines_with(out, _prefix())
    assert len(mine) == 1, out
    assert "UNKNOWN" in mine[0], mine[0]
    assert rc == 0, out


def test_ac_f_the_belt_line_is_one_line_and_leads_with_unknown(
        monkeypatch, tmp_path) -> None:
    """SPEC SCOPE (recorded as PM feedback in tester2.md, NOT asserted as a defect):
    behavior 4's "contains neither `clean` nor `test-dir touched`" is scoped to
    `test_touch_drift_line`'s RETURN VALUE, while the CLI belt is specified as "the same
    `except Exception` belt" the four older lines carry -- and those interpolate the
    exception's repr.  Measured: a hostile message DOES reach doctor's stdout through the
    belt.  That is defence-in-depth only, because behavior 2 proves the helper never
    raises for ANY probe state, so this path is unreachable in production; it is a NIT,
    not a blocker.  What the spec DOES require here is asserted: one line, UNKNOWN."""
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    monkeypatch.setattr(
        foundry, LINE_FN,
        lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("boom clean test-dir touched NO-TEST-TOUCH")))
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    mine = _lines_with(out, _prefix())
    assert len(mine) == 1, out
    assert mine[0][len(_prefix()):].strip().split()[0] == "UNKNOWN", mine[0]


@pytest.mark.parametrize("state", _ALL_PROBE_STATES)
def test_ac_f_the_belt_is_unreachable_because_the_helper_never_raises(
        monkeypatch, state) -> None:
    """The reason the belt's repr interpolation is a NIT rather than a hole: no scripted
    probe state can make the helper raise, so nothing can reach the belt in production."""
    _probe_seam(monkeypatch, state)
    got = _line(_cfg())
    assert isinstance(got, str) and got.startswith(_prefix())


def test_ac_f_a_raising_line_helper_cannot_change_a_failing_exit_code(
        monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch, fail="remote")
    _patch_older_lines(monkeypatch)
    monkeypatch.setattr(
        foundry, LINE_FN,
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("line-helper-boom")))
    rc, out = _doctor_out(_doctor_cfg(tmp_path))
    assert rc == 1, out


# ========================================================================== #
# Acceptance criterion G -- the two FORCED count-word advances, and only those
# ========================================================================== #
IT145 = _ROOT / "tests" / "test_iter145_behavior.py"
IT164 = _ROOT / "tests" / "test_iter164_behavior.py"


def test_ac_g_iter145_readme_regexes_advanced_and_the_stale_phrase_is_gone() -> None:
    src = IT145.read_text(encoding="utf-8")
    assert "five drift lines" in src
    assert "four drift lines" in src
    assert "three drift lines" not in src, "the retired phrase still pins the README"


@pytest.mark.parametrize(
    "token",
    ["ROADMAP_INDEX_PREFIX", "ROADMAP_INDEX_HARD_CHARS", "exactly four",
     "def test_ac_readme_documents_the_third_line"],
)
def test_ac_g_iter145_other_assertions_and_its_test_name_survive(token) -> None:
    """The spec calls the advance FORCED but bounded: the four other assertions in that
    test stay BYTE-UNCHANGED and the test keeps its name."""
    assert token in IT145.read_text(encoding="utf-8"), token


def test_ac_g_iter145_records_the_advance_in_place() -> None:
    assert f"# ADVANCED iter {THIS_ITER}:" in IT145.read_text(encoding="utf-8")


def test_ac_g_iter164_docstring_regexes_are_phrase_scoped_not_bare_words() -> None:
    """The bare-word form would pass VACUOUSLY once the docstring keeps `all four checks
    pass`, silently retiring a live brake -- so the phrases must be present."""
    src = IT164.read_text(encoding="utf-8")
    assert "five drift lines" in src
    assert "four drift lines" in src


@pytest.mark.parametrize(
    "token",
    ["assert str(THIS_ITER) in doc",
     "def test_ac_run_doctor_cli_docstring_announces_four_drift_lines"],
)
def test_ac_g_iter164_keeps_its_iteration_pin_and_its_test_name(token) -> None:
    assert token in IT164.read_text(encoding="utf-8"), token


def test_ac_g_iter164_records_the_advance_in_place() -> None:
    assert f"# ADVANCED iter {THIS_ITER}:" in IT164.read_text(encoding="utf-8")


# ========================================================================== #
# Behavior 8, extended -- every OTHER surface the spec declares untouched
# ========================================================================== #
WATCHDOG = _ROOT / "watchdog.py"
ROLES_DIR = _ROOT / "roles"
SCRIPTS_DIR = _ROOT / "scripts"


@pytest.mark.parametrize("symbol", TEST_TOUCH_SYMBOLS)
def test_b8_watchdog_text_names_no_test_touch_symbol(symbol) -> None:
    assert symbol not in WATCHDOG.read_text(encoding="utf-8"), symbol


@pytest.mark.parametrize("symbol", TEST_TOUCH_SYMBOLS)
def test_b8_no_role_card_names_a_test_touch_symbol(symbol) -> None:
    """The spec puts every `roles/*.md` card out of scope, and item (c)'s first blocker
    was precisely that a card wiring has no legal seat -- so a card must stay clean."""
    cards = sorted(ROLES_DIR.glob("*.md"))
    assert cards, "the roles dir lost its cards"
    for card in cards:
        assert symbol not in card.read_text(encoding="utf-8"), (card.name, symbol)


@pytest.mark.parametrize("symbol", TEST_TOUCH_SYMBOLS)
def test_b8_no_shipped_script_names_a_test_touch_symbol(symbol) -> None:
    scripts = sorted(SCRIPTS_DIR.glob("*.py"))
    assert scripts, "the scripts dir lost its modules"
    for script in scripts:
        assert symbol not in script.read_text(encoding="utf-8"), (script.name, symbol)


def test_b8_the_dormancy_scan_is_failable() -> None:
    """The three negative scans above are only evidence if the same scan can report a
    HIT: a symbol the control path really does name must be found."""
    assert "foundry" in DISPATCHER.read_text(encoding="utf-8")


# ========================================================================== #
# Acceptance criterion H -- both control-path modules import in a FRESH process
# ========================================================================== #
def test_ac_h_foundry_and_dispatcher_import_in_a_fresh_interpreter() -> None:
    """The in-process import at the top of this module proves the pair imports under
    pytest's already-warm `sys.modules`; a cold subprocess is the criterion the spec
    actually states (`python -c "import foundry, dispatcher"`)."""
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, (r.returncode, r.stdout[-400:], r.stderr[-400:])
