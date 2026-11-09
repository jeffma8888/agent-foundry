"""Iteration 518 -- BLACK-BOX behavior tests: `foundry doctor` prints a
never-blocking `drain-arm:` line saying whether the dispatcher started by the
LAST `dispatcher up` banner logged `drain armed: kill -USR1 <pid>`.

Offline and deterministic: all log text is a literal or written under tmp_path;
no assertion is made on the ambient dispatcher.out.
"""
from __future__ import annotations

import contextlib
import io
import os
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

BANNER_A = "- `11-07 09:00:00` dispatcher up; teams=2 concurrency=1\n"
BANNER_B = "- `11-08 13:56:52` dispatcher up; teams=2 concurrency=1\n"


def _armed(pid, stamp="11-08 13:56:53"):
    return f"- `{stamp}` drain armed: kill -USR1 {pid}\n"


OTHER = "- `11-08 13:57:00` shift 1 start\n"


# ------------------------------------------------------------------ EB1

def test_eb1_prefix_constant():
    assert foundry.DRAIN_ARM_PREFIX == "drain-arm:"


# ------------------------------------------------------------------ EB2

def test_eb2_banner_then_armed_returns_int_pid():
    pid = foundry.parse_drain_armed(BANNER_B + _armed(4321) + OTHER)
    assert pid == 4321
    assert type(pid) is int


def test_eb2_first_armed_line_after_last_banner_wins():
    text = BANNER_B + OTHER + _armed(11) + _armed(22)
    assert foundry.parse_drain_armed(text) == 11


def test_eb2_star_bullet_and_no_bullet_and_trailing_ws_accepted():
    assert foundry.parse_drain_armed(
        BANNER_B + "* `11-08 13:56:53` drain armed: kill -USR1 77   \n") == 77
    assert foundry.parse_drain_armed(
        BANNER_B + "`11-08 13:56:53` drain armed: kill -USR1 78\n") == 78
    assert foundry.parse_drain_armed(
        BANNER_B + "   - `11-08 13:56:53` drain armed: kill -USR1 79\n") == 79


def test_eb2_trailing_payload_after_pid_rejected():
    assert foundry.parse_drain_armed(
        BANNER_B + "- `11-08 13:56:53` drain armed: kill -USR1 79 extra\n") is None


def test_eb2_no_stamp_date_validation_on_banner():
    # The banner anchor is _BRAIN_UP_RE; stamp-date validation is NOT applied.
    banner = "- `02-30 00:00:00` dispatcher up; teams=2 concurrency=1\n"
    assert foundry.parse_drain_armed(banner + _armed(5)) == 5


@pytest.mark.parametrize("text", [
    "", None, "\n", "\n\n\n", "drain armed", "dispatcher up",
    "\x00\x01 dispatcher up \x7f", "dispatcher up " * 5000,
    BANNER_B + "x" * 20000, "\u4e2d\u6587 drain armed: kill -USR1 \u0663",
    BANNER_B + "- `11-08 13:56:53` drain armed: kill -USR1 \n",
    BANNER_B + "- `11-08 13:56:53` drain armed: kill -USR1 abc\n",
])
def test_eb2_total_never_raises_on_odd_input(text):
    res = foundry.parse_drain_armed(text)
    assert res is None or type(res) is int


def test_eb2_empty_and_none_return_none():
    assert foundry.parse_drain_armed("") is None
    assert foundry.parse_drain_armed(None) is None


# ------------------------------------------------------------------ EB3

def test_eb3_no_banner_returns_none():
    assert foundry.parse_drain_armed(
        "- `11-08 13:56:52` drain armed: kill -USR1 42") is None
    assert foundry.parse_drain_armed(OTHER + _armed(42)) is None


# ------------------------------------------------------------------ EB4

def test_eb4_armed_only_before_last_banner_does_not_count():
    assert foundry.parse_drain_armed(BANNER_A + _armed(111) + BANNER_B) is None
    assert foundry.parse_drain_armed(
        BANNER_A + _armed(111) + BANNER_B + OTHER) is None


def test_eb4_armed_after_last_banner_counts():
    assert foundry.parse_drain_armed(
        BANNER_A + _armed(111) + BANNER_B + _armed(222)) == 222


# ------------------------------------------------------------------ EB5

def test_eb5_quoted_fragment_in_payload_does_not_count():
    text = BANNER_B + "- `11-08 14:00:00` no output file: 'drain armed: kill -USR1 9'\n"
    assert foundry.parse_drain_armed(text) is None


def test_eb5_armed_text_without_stamp_does_not_count():
    assert foundry.parse_drain_armed(BANNER_B + "drain armed: kill -USR1 9\n") is None
    assert foundry.parse_drain_armed(BANNER_B + "- drain armed: kill -USR1 9\n") is None


# ------------------------------------------------------------------ EB6

def _assert_one_line(line):
    assert isinstance(line, str)
    assert "\n" not in line
    assert line.startswith("drain-arm: ")
    assert line.split()[1] in ("ARMED", "NOT", "UNKNOWN")


def test_eb6_no_banner_is_unknown():
    line = foundry.drain_arm_line(_armed(42))
    _assert_one_line(line)
    assert line.startswith("drain-arm: UNKNOWN -- ")


def test_eb6_armed_names_kill_usr1_pid():
    line = foundry.drain_arm_line(BANNER_B + _armed(4321))
    _assert_one_line(line)
    assert line.startswith("drain-arm: ARMED -- ")
    assert "kill -USR1 4321" in line


def test_eb6_banner_without_armed_is_not_armed():
    line = foundry.drain_arm_line(BANNER_A + _armed(111) + BANNER_B + OTHER)
    _assert_one_line(line)
    assert line.startswith("drain-arm: NOT ARMED -- ")
    assert "SIGUSR1" in line
    assert "kill" in line
    assert "111" not in line.split("--", 1)[0]


@pytest.mark.parametrize("text", ["", None, "\x00", "dispatcher up " * 3000])
def test_eb6_never_raises(text):
    line = foundry.drain_arm_line(text)
    _assert_one_line(line)
    assert not line.startswith("drain-arm: ARMED")


# ------------------------------------------------------------------ EB7

def _cfg(tmp_path):
    idx = tmp_path / "IDX.md"
    idx.write_text("# roadmap\n\nsome prose\n", encoding="utf-8")
    return foundry.ProductConfig(
        name="demo",
        repo="products/_platform/state/iter-518",
        allowed_push_repo="demo",
        roadmap=str(idx),
        learnings=str(tmp_path / "no-such-learnings.md"),
        work_root=str(tmp_path),
    )


@pytest.mark.parametrize("body", [
    BANNER_B + _armed(4321),
    BANNER_A + _armed(1) + BANNER_B,
    _armed(9),
])
def test_eb7_reads_explicit_log_path(tmp_path, body):
    log = tmp_path / "d.out"
    log.write_text(body, encoding="utf-8")
    assert foundry.drain_arm_status_line(_cfg(tmp_path), log_path=log) == \
        foundry.drain_arm_line(body)


def test_eb7_default_path_is_foundry_dispatcher_out(tmp_path, monkeypatch):
    fake_root = tmp_path / "root"
    fake_root.mkdir()
    (fake_root / "dispatcher.out").write_text(BANNER_B + _armed(6060), encoding="utf-8")
    monkeypatch.setattr(foundry, "FOUNDRY", fake_root)
    line = foundry.drain_arm_status_line(_cfg(tmp_path))
    assert line.startswith("drain-arm: ARMED -- ")
    assert "kill -USR1 6060" in line


def test_eb7_missing_file_is_unknown(tmp_path):
    line = foundry.drain_arm_status_line(_cfg(tmp_path), log_path=tmp_path / "nope.out")
    assert line.startswith("drain-arm: UNKNOWN")
    assert "\n" not in line


def test_eb7_directory_path_is_unknown(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    line = foundry.drain_arm_status_line(_cfg(tmp_path), log_path=d)
    assert line.startswith("drain-arm: UNKNOWN")


def test_eb7_non_utf8_file_never_raises_never_falsely_armed(tmp_path):
    p = tmp_path / "bin.out"
    p.write_bytes(b"\xff\xfe\x80 garbage \xc3\x28")
    line = foundry.drain_arm_status_line(_cfg(tmp_path), log_path=p)
    assert line.startswith("drain-arm: ")
    assert not line.startswith("drain-arm: ARMED")


def test_eb7_missing_default_file_is_unknown(tmp_path, monkeypatch):
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    monkeypatch.setattr(foundry, "FOUNDRY", empty_root)
    line = foundry.drain_arm_status_line(_cfg(tmp_path))
    assert line.startswith("drain-arm: UNKNOWN")


# ------------------------------------------------------------------ EB8/9 doctor

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


def _stub_doctor(monkeypatch, *, fail=None):
    for nm in ("power", "agent", "uv", "remote"):
        monkeypatch.setattr(
            foundry, f"check_{nm}",
            lambda *a, _n=nm, **k: _Chk(_n, _n != fail))
    monkeypatch.setattr(foundry, "parse_brain_launch", lambda *a, **k: 1000.0)
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: ((1, 900.0),))
    monkeypatch.setattr(foundry, "gather_stage_times",
                        lambda *a, **k: _S(_G("engineer", 100.0, 0, 9)))
    monkeypatch.setattr(foundry, "probe_test_touch",
                        lambda *a, **k: "clean -- 0 uncommitted path(s)")
    monkeypatch.setattr(foundry, "gather_losses",
                        lambda *a, **k: type("D", (), {"attempts": 10, "rows": ()})())
    monkeypatch.setattr(foundry, "probe_watchdog_arm", lambda *a, **k: None)


def _doctor(cfg):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.run_doctor_cli(cfg)
    return rc, buf.getvalue().splitlines()


VARIANTS = {
    "armed": BANNER_B + _armed(4321),
    "not": BANNER_A + _armed(1) + BANNER_B,
    "unknown": _armed(9),
}


def _script_status(monkeypatch, text):
    monkeypatch.setattr(foundry, "drain_arm_status_line",
                        lambda *a, **k: foundry.drain_arm_line(text))


@pytest.mark.parametrize("label", sorted(VARIANTS))
def test_eb8_exactly_one_line_after_watchdog_before_summary(monkeypatch, tmp_path, label):
    _stub_doctor(monkeypatch)
    _script_status(monkeypatch, VARIANTS[label])
    _rc, lines = _doctor(_cfg(tmp_path))
    hits = [i for i, ln in enumerate(lines) if ln.startswith("drain-arm:")]
    assert len(hits) == 1, lines
    wd = [i for i, ln in enumerate(lines) if ln.startswith("watchdog-arm:")]
    assert len(wd) == 1, lines
    assert hits[0] == wd[0] + 1, lines
    assert lines[hits[0]] == foundry.drain_arm_line(VARIANTS[label])
    rest = [ln for ln in lines[hits[0] + 1:] if ln.strip()]
    assert rest and all(ln.startswith("doctor:") for ln in rest), rest


def test_eb8_end_to_end_reads_default_dispatcher_out(monkeypatch, tmp_path):
    _stub_doctor(monkeypatch)
    root = tmp_path / "root"
    root.mkdir()
    (root / "dispatcher.out").write_text(BANNER_B + _armed(8080), encoding="utf-8")
    monkeypatch.setattr(foundry, "FOUNDRY", root)
    _rc, lines = _doctor(_cfg(tmp_path))
    hits = [ln for ln in lines if ln.startswith("drain-arm:")]
    assert len(hits) == 1
    assert hits[0].startswith("drain-arm: ARMED -- ") and "kill -USR1 8080" in hits[0]


def test_eb8_helper_raising_prints_unknown_and_doctor_finishes(monkeypatch, tmp_path):
    _stub_doctor(monkeypatch)

    def _boom(*a, **k):
        raise RuntimeError("helper exploded")

    monkeypatch.setattr(foundry, "drain_arm_status_line", _boom)
    rc, lines = _doctor(_cfg(tmp_path))
    hits = [ln for ln in lines if ln.startswith("drain-arm:")]
    assert len(hits) == 1, lines
    assert hits[0].startswith("drain-arm: UNKNOWN -- ")
    assert any(ln.startswith("doctor:") for ln in lines)
    assert isinstance(rc, int)


@pytest.mark.parametrize("fail", [None, "uv"])
def test_eb9_exit_code_independent_of_line(monkeypatch, tmp_path, fail):
    rcs = set()
    for text in VARIANTS.values():
        _stub_doctor(monkeypatch, fail=fail)
        _script_status(monkeypatch, text)
        rc, _ = _doctor(_cfg(tmp_path))
        rcs.add(rc)
    _stub_doctor(monkeypatch, fail=fail)
    monkeypatch.setattr(foundry, "drain_arm_status_line",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    rc, _ = _doctor(_cfg(tmp_path))
    rcs.add(rc)
    assert len(rcs) == 1, rcs


def test_eb9_failing_check_still_fails_and_passing_still_passes(monkeypatch, tmp_path):
    _stub_doctor(monkeypatch)
    _script_status(monkeypatch, VARIANTS["armed"])
    rc_ok, _ = _doctor(_cfg(tmp_path))
    _stub_doctor(monkeypatch, fail="uv")
    _script_status(monkeypatch, VARIANTS["armed"])
    rc_bad, _ = _doctor(_cfg(tmp_path))
    assert rc_ok == 0
    assert rc_bad != 0


# ------------------------------------------------------------------ EB10

def _no_side_effects(monkeypatch):
    def _forbid(*a, **k):
        raise AssertionError("helper must not signal or spawn")

    monkeypatch.setattr(os, "kill", _forbid)
    monkeypatch.setattr(subprocess, "run", _forbid)
    monkeypatch.setattr(subprocess, "Popen", _forbid)


def test_eb10_helpers_hold_with_kill_and_subprocess_forbidden(monkeypatch, tmp_path):
    _no_side_effects(monkeypatch)
    assert foundry.parse_drain_armed(BANNER_B + _armed(4321)) == 4321
    assert foundry.parse_drain_armed(BANNER_A + _armed(1) + BANNER_B) is None
    assert foundry.parse_drain_armed(_armed(1)) is None
    assert foundry.drain_arm_line(BANNER_B + _armed(4321)).startswith("drain-arm: ARMED")
    assert foundry.drain_arm_line(BANNER_B).startswith("drain-arm: NOT ARMED")
    assert foundry.drain_arm_line("").startswith("drain-arm: UNKNOWN")
    log = tmp_path / "d.out"
    log.write_text(BANNER_B + _armed(4321), encoding="utf-8")
    assert "kill -USR1 4321" in foundry.drain_arm_status_line(_cfg(tmp_path), log_path=log)
    assert foundry.drain_arm_status_line(
        _cfg(tmp_path), log_path=tmp_path / "missing").startswith("drain-arm: UNKNOWN")


def test_eb10_doctor_line_with_kill_and_subprocess_forbidden(monkeypatch, tmp_path):
    _stub_doctor(monkeypatch)
    root = tmp_path / "root"
    root.mkdir()
    (root / "dispatcher.out").write_text(BANNER_B, encoding="utf-8")
    monkeypatch.setattr(foundry, "FOUNDRY", root)
    _no_side_effects(monkeypatch)
    _rc, lines = _doctor(_cfg(tmp_path))
    hits = [ln for ln in lines if ln.startswith("drain-arm:")]
    assert len(hits) == 1
    assert hits[0].startswith("drain-arm: NOT ARMED -- ")
