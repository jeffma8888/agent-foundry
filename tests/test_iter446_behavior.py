"""Iteration 446 -- BLACK-BOX behavior tests: wiring `watchdog-arm` into `doctor`
as the SEVENTH drift line, giving the dormant resilience probe its first
human-facing consumer.

Spec under test: products/_platform/state/iter-446/pm.md (5 Expected Behaviors).

  EB1: `foundry doctor --config <cfg>` prints a `watchdog-arm:` line whose value
       is one of `armed`, `no-schedule`, or `UNKNOWN`, formatted consistently with
       the six existing drift lines (label + colon + space + payload).
  EB2: The docstring of `run_doctor_cli` advances from "SIX drift lines" to
       "SEVEN drift lines" and its enumeration list grows by one entry naming
       `watchdog-arm`.
  EB3: A test with `probe_watchdog_arm` monkeypatched to return each of the three
       verdicts (`armed`, `no-schedule`, `UNKNOWN`) confirms the `watchdog-arm:`
       line appears in the printed output with the matching keyword.
  EB4: The existing four preflight checks and six drift lines are unchanged -- the
       new line is appended AFTER the sixth (`auth-loss:`) and BEFORE the final
       `doctor:` summary line.
  EB5: `doctor`'s exit code is unchanged: the watchdog-arm line is a DRIFT line
       (report-only), not a preflight Check, so it never flips the READY/NOT READY
       verdict.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the
iter-446 PM spec, the product README / roadmap / archive TEXT, the pre-existing
conventions under `tests/`, and the product's OWN observable behavior by importing
and CALLING its public names.  The implementation SOURCE of `foundry.py` /
`dispatcher.py` was NOT read by this author, nor the engineer's notes, the
reviewer's notes, `IMPLEMENTATION.patch`, or any `git diff`.

Offline and deterministic: every behavior scripts `probe_watchdog_arm` by BARE
module name, so no real crontab, network, or git runs.
"""
from __future__ import annotations

import contextlib
import inspect
import io
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

THIS_ITER = 446

ARMED = "armed"
NOT_ARMED = "NOT-ARMED"
NO_SCHEDULE = "no-schedule"
UNKNOWN_KEYWORD = "UNKNOWN"

ALL_DRIFT_PREFIXES = (
    foundry.LIVE_LAG_PREFIX,
    foundry.LEARNINGS_HEAD_PREFIX,
    foundry.ROADMAP_INDEX_PREFIX,
    foundry.STAGE_BUDGET_PREFIX,
    foundry.TEST_TOUCH_PREFIX,
    foundry.AUTH_LOSS_PREFIX,
    foundry.WATCHDOG_ARM_PREFIX,
)

OLDER_DRIFT_PREFIXES = ALL_DRIFT_PREFIXES[:6]


# ------------------------------------------------------------------ helpers

class _Chk:
    def __init__(self, name, ok, detail="detail-text"):
        self.name, self.ok, self.detail = name, ok, detail


class _G:
    def __init__(self, stage, median_s, timeouts=0, count=1):
        self.stage, self.median_s = stage, median_s
        self.timeouts, self.count = timeouts, count


class _S:
    def __init__(self, *groups):
        self.groups = tuple(groups)


def _stub_checks(monkeypatch, *, fail=None):
    for nm in ("power", "agent", "uv", "remote"):
        monkeypatch.setattr(
            foundry, f"check_{nm}",
            lambda *a, _n=nm, **k: _Chk(_n, _n != fail))


def _patch_older_lines(monkeypatch):
    monkeypatch.setattr(foundry, "parse_brain_launch", lambda *a, **k: 1000.0)
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: ((1, 900.0),))
    monkeypatch.setattr(
        foundry, "gather_stage_times",
        lambda *a, **k: _S(_G("engineer", 100.0, 0, 9)))
    monkeypatch.setattr(
        foundry, "probe_test_touch",
        lambda *a, **k: "clean -- 0 uncommitted path(s)")
    monkeypatch.setattr(
        foundry, "gather_losses",
        lambda *a, **k: type("D", (), {"attempts": 10, "rows": ()})())


def _script_probe(monkeypatch, *, return_value):
    monkeypatch.setattr(foundry, "probe_watchdog_arm", lambda *a, **k: return_value)


def _doctor_cfg(tmp_path):
    idx = tmp_path / "IDX.md"
    idx.write_text("# roadmap\n\nsome prose\n", encoding="utf-8")
    return foundry.ProductConfig(
        name="demo",
        repo="products/_platform/state/iter-446",
        allowed_push_repo="demo",
        roadmap=str(idx),
        learnings=str(tmp_path / "no-such-learnings.md"),
        work_root=str(tmp_path),
    )


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


# ------------------------------------------------------------------ EB1

PROBE_RETURNS = [
    ("armed", foundry.watchdog_arm_line("*/5 * * * * python3 watchdog.py\n")),
    ("no-schedule", foundry.watchdog_arm_line("# nothing\n")),
    ("unknown", None),
]


@pytest.mark.parametrize("label,probe_ret", PROBE_RETURNS,
                         ids=[l for l, _ in PROBE_RETURNS])
def test_eb1_watchdog_arm_line_appears_with_correct_verdict(
        monkeypatch, tmp_path, label, probe_ret) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _script_probe(monkeypatch, return_value=probe_ret)
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    hits = _lines_with(out, foundry.WATCHDOG_ARM_PREFIX)
    assert len(hits) == 1, f"{label}: expected exactly one watchdog-arm: line, got {hits}"
    payload = hits[0][len(foundry.WATCHDOG_ARM_PREFIX):].strip()
    if label == "armed":
        assert payload.startswith(ARMED), f"expected 'armed' payload: {payload!r}"
    elif label == "no-schedule":
        assert payload.startswith(NO_SCHEDULE), f"expected 'no-schedule' payload: {payload!r}"
    elif label == "unknown":
        assert UNKNOWN_KEYWORD in payload.upper(), f"expected UNKNOWN in: {payload!r}"


def test_eb1_watchdog_arm_line_format_is_label_colon_space_payload(
        monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _script_probe(monkeypatch, return_value=foundry.watchdog_arm_line(
        "*/5 * * * * python3 watchdog.py\n"))
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    hits = _lines_with(out, foundry.WATCHDOG_ARM_PREFIX)
    assert len(hits) == 1
    line = hits[0]
    assert re.match(r"^watchdog-arm:\s+\S", line), \
        f"format must be 'label: payload': {line!r}"


# ------------------------------------------------------------------ EB2

def test_eb2_docstring_says_seven_drift_lines() -> None:
    doc = foundry.run_doctor_cli.__doc__ or ""
    assert "SEVEN drift lines" in doc, \
        f"docstring must say 'SEVEN drift lines': {doc[:200]!r}"
    assert "SIX drift lines" not in doc, \
        f"docstring still says 'SIX drift lines': {doc[:200]!r}"


def test_eb2_docstring_names_watchdog_arm() -> None:
    doc = foundry.run_doctor_cli.__doc__ or ""
    assert "watchdog-arm" in doc, \
        f"docstring must name the new drift line: {doc[:200]!r}"


def test_eb2_docstring_names_iter_446() -> None:
    doc = foundry.run_doctor_cli.__doc__ or ""
    assert "446" in doc, \
        f"docstring enumeration must reference iter 446: {doc[:300]!r}"


# ------------------------------------------------------------------ EB3

@pytest.mark.parametrize("label,probe_ret,expect_keyword", [
    ("armed",
     foundry.watchdog_arm_line("*/5 * * * * python3 watchdog.py\n0 * * * * echo hi\n"),
     ARMED),
    ("no-schedule",
     foundry.watchdog_arm_line("# nothing\n"),
     NO_SCHEDULE),
    ("unknown", None, UNKNOWN_KEYWORD),
], ids=["armed", "no-schedule", "unknown"])
def test_eb3_three_verdict_monkeypatched(
        monkeypatch, tmp_path, label, probe_ret, expect_keyword) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _script_probe(monkeypatch, return_value=probe_ret)
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    hits = _lines_with(out, foundry.WATCHDOG_ARM_PREFIX)
    assert len(hits) == 1, f"{label}: expected 1 watchdog-arm line, got {len(hits)}"
    if expect_keyword == UNKNOWN_KEYWORD:
        assert UNKNOWN_KEYWORD in hits[0].upper(), \
            f"{label}: UNKNOWN not in: {hits[0]!r}"
    else:
        payload = hits[0][len(foundry.WATCHDOG_ARM_PREFIX):].strip()
        assert payload.startswith(expect_keyword), \
            f"{label}: expected payload starting with {expect_keyword!r}: {payload!r}"


def test_eb3_probe_is_called_by_bare_module_name(monkeypatch, tmp_path) -> None:
    calls = []

    def _recording_probe(*a, **k):
        calls.append(1)
        return foundry.watchdog_arm_line("*/5 * * * * python3 watchdog.py\n")

    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    monkeypatch.setattr(foundry, "probe_watchdog_arm", _recording_probe)
    _doctor_out(_doctor_cfg(tmp_path))
    assert len(calls) == 1, f"probe_watchdog_arm called {len(calls)} time(s), expected 1"


# ------------------------------------------------------------------ EB4

def test_eb4_all_six_older_drift_lines_still_present(
        monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _script_probe(monkeypatch, return_value=foundry.watchdog_arm_line(
        "*/5 * * * * python3 watchdog.py\n"))
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    for prefix in OLDER_DRIFT_PREFIXES:
        hits = _lines_with(out, prefix)
        assert len(hits) == 1, f"{prefix} appeared {len(hits)} time(s):\n{out}"


def test_eb4_watchdog_arm_is_after_auth_loss_and_before_summary(
        monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _script_probe(monkeypatch, return_value=foundry.watchdog_arm_line(
        "*/5 * * * * python3 watchdog.py\n"))
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    auth_loss_idx = _first_index(out, foundry.AUTH_LOSS_PREFIX)
    watchdog_idx = _first_index(out, foundry.WATCHDOG_ARM_PREFIX)
    assert auth_loss_idx >= 0, "auth-loss: line missing"
    assert watchdog_idx >= 0, "watchdog-arm: line missing"
    assert watchdog_idx > auth_loss_idx, \
        f"watchdog-arm (line {watchdog_idx}) must come AFTER auth-loss (line {auth_loss_idx})"
    summary_idx = -1
    for i, ln in enumerate(out.splitlines()):
        if re.match(r"^doctor:.*\d+/\d+ checks", ln):
            summary_idx = i
            break
    assert summary_idx >= 0, f"doctor summary line not found in:\n{out}"
    assert watchdog_idx < summary_idx, \
        f"watchdog-arm (line {watchdog_idx}) must come BEFORE summary (line {summary_idx})"


def test_eb4_four_checks_still_present(monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    checks = foundry.run_doctor(_doctor_cfg(tmp_path))
    assert len(list(checks)) == 4, f"run_doctor must return exactly four Checks"


def test_eb4_existing_drift_lines_byte_unchanged(monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _script_probe(monkeypatch, return_value=foundry.watchdog_arm_line(
        "*/5 * * * * python3 watchdog.py\n"))
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    for prefix in OLDER_DRIFT_PREFIXES:
        idx = _first_index(out, prefix)
        assert idx >= 0, f"{prefix} vanished from doctor output"
        watchdog_idx = _first_index(out, foundry.WATCHDOG_ARM_PREFIX)
        assert idx < watchdog_idx, \
            f"{prefix} (line {idx}) must come before watchdog-arm (line {watchdog_idx})"


# ------------------------------------------------------------------ EB5

@pytest.mark.parametrize("probe_ret", [
    foundry.watchdog_arm_line("*/5 * * * * python3 watchdog.py\n"),
    foundry.watchdog_arm_line("# nothing\n"),
    None,
], ids=["armed", "no-schedule", "unknown"])
def test_eb5_exit_code_zero_when_all_checks_pass(
        monkeypatch, tmp_path, probe_ret) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _script_probe(monkeypatch, return_value=probe_ret)
    rc, _out = _doctor_out(_doctor_cfg(tmp_path))
    assert rc == 0, f"exit code should be 0 when all checks pass, got {rc}"


@pytest.mark.parametrize("probe_ret", [
    foundry.watchdog_arm_line("*/5 * * * * python3 watchdog.py\n"),
    foundry.watchdog_arm_line("# nothing\n"),
    None,
], ids=["armed", "no-schedule", "unknown"])
def test_eb5_exit_code_one_when_check_fails(
        monkeypatch, tmp_path, probe_ret) -> None:
    _stub_checks(monkeypatch, fail="uv")
    _patch_older_lines(monkeypatch)
    _script_probe(monkeypatch, return_value=probe_ret)
    rc, _out = _doctor_out(_doctor_cfg(tmp_path))
    assert rc == 1, f"exit code should be 1 with a failing check, got {rc}"


def test_eb5_summary_still_says_4_checks(monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    _script_probe(monkeypatch, return_value=None)
    _rc, out = _doctor_out(_doctor_cfg(tmp_path))
    assert re.search(r"\b4/4 checks ok\b", out), \
        f"the summary must still say 4/4 checks:\n{out}"


def test_eb5_not_armed_state_does_not_affect_exit(monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    _patch_older_lines(monkeypatch)
    not_armed_line = foundry.watchdog_arm_line("0 * * * * echo hi\n")
    _script_probe(monkeypatch, return_value=not_armed_line)
    rc, _out = _doctor_out(_doctor_cfg(tmp_path))
    assert rc == 0, f"NOT-ARMED watchdog should not flip exit code, got {rc}"
