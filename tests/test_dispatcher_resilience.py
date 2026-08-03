"""Dispatcher resilience: logging and per-team config loading must never kill
the always-on brain.

Regression origin: a live dispatcher died mid-shift with an uncaught
OSError(5, 'Input/output error'). The dispatcher had inherited stdout from the
session that launched it; when that session went away, the next ``print`` in
``dlog`` raised EIO, escaped the main loop, and took the whole company down
after 68 successful shifts. Nothing was wrong with the work itself.

Fully offline and deterministic: no network, no real sleeping, no real
subprocesses. Every effect (stdout, the log file, config loading, the product
iteration, the sleep-assertion subprocess) is monkeypatched at a seam.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import dispatcher  # noqa: E402  (repo root injected above)


class _DeadStream:
    """A stdout whose writes fail exactly the way a dead terminal does."""

    def write(self, *_a, **_k):
        raise OSError(5, "Input/output error")

    def flush(self, *_a, **_k):
        raise OSError(5, "Input/output error")


class _StubCfg:
    def __init__(self, name: str, stop_file: pathlib.Path):
        self.name = name
        self.stop_file = stop_file


# --------------------------------------------------------------------------
# dlog must never raise
# --------------------------------------------------------------------------

def test_dlog_happy_path_writes_file_and_stdout(tmp_path, monkeypatch, capsys):
    log = tmp_path / "DISPATCH_LOG.md"
    monkeypatch.setattr(dispatcher, "DISPATCH_LOG", log)
    dispatcher.dlog("hello world")
    assert "hello world" in log.read_text()
    assert "hello world" in capsys.readouterr().out


def test_dlog_survives_dead_stdout(tmp_path, monkeypatch):
    """The exact failure that killed the live loop: stdout raises EIO."""
    log = tmp_path / "DISPATCH_LOG.md"
    monkeypatch.setattr(dispatcher, "DISPATCH_LOG", log)
    monkeypatch.setattr(sys, "stdout", _DeadStream())
    dispatcher.dlog("survives dead stdout")  # must not raise
    # the durable record still lands even though stdout is gone
    assert "survives dead stdout" in log.read_text()


def test_dlog_survives_unwritable_log_file(tmp_path, monkeypatch, capsys):
    """An unwritable log path must not stop the loop; stdout still gets it."""
    missing_parent = tmp_path / "no-such-dir" / "DISPATCH_LOG.md"
    monkeypatch.setattr(dispatcher, "DISPATCH_LOG", missing_parent)
    dispatcher.dlog("still printed")  # must not raise
    assert "still printed" in capsys.readouterr().out
    assert not missing_parent.exists()


def test_dlog_survives_both_sinks_failing(tmp_path, monkeypatch):
    """Belt and braces: neither sink available is still not fatal."""
    monkeypatch.setattr(
        dispatcher, "DISPATCH_LOG", tmp_path / "no-such-dir" / "log.md")
    monkeypatch.setattr(sys, "stdout", _DeadStream())
    dispatcher.dlog("swallowed entirely")  # must not raise


# --------------------------------------------------------------------------
# one bad team config must not kill the company
# --------------------------------------------------------------------------

def test_bad_team_config_skips_only_that_team(tmp_path, monkeypatch):
    log = tmp_path / "DISPATCH_LOG.md"
    monkeypatch.setattr(dispatcher, "DISPATCH_LOG", log)
    monkeypatch.setattr(dispatcher, "STOP_FILE", tmp_path / "NO_STOP")
    # never hold a real sleep-assertion in a test
    monkeypatch.setattr(dispatcher.subprocess, "Popen", lambda *a, **k: None)

    never = tmp_path / "NEVER_STOPPED"

    def fake_load_config(path: str):
        if "broken" in path:
            raise FileNotFoundError(f"no such config: {path}")
        return _StubCfg("good_team", never)

    ran: list[str] = []

    def fake_run_iteration(cfg):
        ran.append(cfg.name)
        return {"status": "shipped", "iteration": 7}

    monkeypatch.setattr(dispatcher.foundry, "load_config", fake_load_config)
    monkeypatch.setattr(dispatcher.foundry, "run_iteration", fake_run_iteration)
    monkeypatch.setattr(
        dispatcher.foundry, "dispatch_progress_line", lambda cfg: None)

    cfg_file = tmp_path / "dispatch.json"
    cfg_file.write_text(
        '{"work_items": ['
        '{"name": "broken_team", "config": "broken.json", "priority": 0},'
        '{"name": "good_team", "config": "good.json", "priority": 10}'
        ']}')

    # max_shifts=1 -> returns as soon as the good team takes its one shift
    rc = dispatcher.main(["--config", str(cfg_file), "--max-shifts", "1"])

    assert rc == 0, "a bad team config must not fail the dispatcher"
    assert ran == ["good_team"], (
        "the healthy team must still get its shift; the broken team must be "
        f"skipped, not run. ran={ran}")
    text = log.read_text()
    assert "config load failed for broken_team" in text, (
        f"the skip was not reported in the dispatch log:\n{text}")
    assert "skipping this team" in text
