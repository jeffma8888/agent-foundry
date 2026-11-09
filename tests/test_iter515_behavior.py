"""iter 515: dispatcher.py honors SIGUSR1 as a graceful DRAIN (black-box).

Drives only the public surface: ``dispatcher.main([...])``, the module names
``DRAIN_SIGNAL`` / ``request_drain`` / ``drain_requested``, the dispatch log
and the docs. Every effect is monkeypatched at the same seams
test_dispatcher_resilience.py uses; no sleeping, no network, no real
subprocess.
"""
from __future__ import annotations

import os
import pathlib
import signal
import subprocess
import sys
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import dispatcher  # noqa: E402

HAS_USR1 = hasattr(signal, "SIGUSR1")
needs_usr1 = pytest.mark.skipif(not HAS_USR1, reason="platform lacks SIGUSR1")


class _Cfg:
    def __init__(self, name, stop_file):
        self.name = name
        self.stop_file = stop_file


class _NoSleep(Exception):
    pass


def _setup(tmp_path, monkeypatch, on_run=None):
    log = tmp_path / "DISPATCH_LOG.md"
    stop = tmp_path / "STOP"
    monkeypatch.setattr(dispatcher, "DISPATCH_LOG", log)
    monkeypatch.setattr(dispatcher, "STOP_FILE", stop)
    monkeypatch.setattr(dispatcher.subprocess, "Popen", lambda *a, **k: None)

    def _boom(*_a, **_k):
        raise _NoSleep("unexpected sleep")

    monkeypatch.setattr(dispatcher.time, "sleep", _boom)
    never = tmp_path / "TEAM_NEVER_STOPPED"
    monkeypatch.setattr(dispatcher.foundry, "load_config",
                        lambda p: _Cfg(pathlib.Path(p).stem, never))
    monkeypatch.setattr(dispatcher.foundry, "dispatch_progress_line",
                        lambda cfg: None)
    ran: list[str] = []

    def fake_run(cfg):
        ran.append(cfg.name)
        if on_run is not None:
            on_run(len(ran), cfg)
        return {"status": "shipped", "iteration": 7}

    monkeypatch.setattr(dispatcher.foundry, "run_iteration", fake_run)
    cfg_file = tmp_path / "dispatch.json"
    cfg_file.write_text(
        '{"work_items": ['
        '{"name": "A", "config": "A.json", "priority": 0},'
        '{"name": "B", "config": "B.json", "priority": 0}'
        ']}')
    argv = ["--config", str(cfg_file), "--max-shifts", "5"]
    return log, stop, ran, argv


def _lines(log):
    return log.read_text().splitlines() if log.exists() else []


# ---------------------------------------------------------------- behavior 1

def test_b1_names_exist_and_drain_signal_value():
    assert callable(dispatcher.request_drain)
    assert callable(dispatcher.drain_requested)
    if HAS_USR1:
        assert dispatcher.DRAIN_SIGNAL == signal.SIGUSR1
    else:
        assert dispatcher.DRAIN_SIGNAL is None


@needs_usr1
def test_b1_import_installs_no_handler():
    code = (
        "import signal,sys; sys.path.insert(0, sys.argv[1]);"
        "before = signal.getsignal(signal.SIGUSR1);"
        "import dispatcher;"
        "after = signal.getsignal(signal.SIGUSR1);"
        "print('SAME' if before == after else 'CHANGED', after)"
    )
    out = subprocess.run([sys.executable, "-c", code, str(ROOT)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("SAME"), out.stdout
    # anti-vacuity: the fresh-process default is SIG_DFL, never request_drain
    assert "request_drain" not in out.stdout


# ---------------------------------------------------------------- behavior 2

def test_b2_request_drain_sets_flag_and_returns_none():
    assert dispatcher.request_drain() is None
    assert dispatcher.drain_requested() is True
    # handler-shaped call must also be fine
    assert dispatcher.request_drain(10, None) is None
    assert dispatcher.drain_requested() is True


def test_b2_main_resets_flag_at_start(tmp_path, monkeypatch):
    seen = []
    log, _stop, ran, argv = _setup(
        tmp_path, monkeypatch,
        on_run=lambda n, cfg: seen.append(dispatcher.drain_requested()))
    dispatcher.request_drain()  # stale flag from a previous run
    assert dispatcher.drain_requested() is True
    rc = dispatcher.main(argv)
    assert rc == 0
    assert seen and seen[0] is False, seen
    assert len(ran) == 5, "a stale pre-main drain must not end the new run"
    assert not any("drain honored" in ln for ln in _lines(log))


# ---------------------------------------------------------------- behavior 3

@needs_usr1
def test_b3_handler_installed_during_main_and_restored(tmp_path, monkeypatch):
    during = []
    _log, _stop, _ran, argv = _setup(
        tmp_path, monkeypatch,
        on_run=lambda n, cfg: during.append(signal.getsignal(signal.SIGUSR1)))
    before = signal.getsignal(signal.SIGUSR1)
    try:
        assert dispatcher.main(argv) == 0
        assert during and all(h == dispatcher.request_drain for h in during)
        assert signal.getsignal(signal.SIGUSR1) == before
    finally:
        signal.signal(signal.SIGUSR1, before)


def _custom_handler(signum, frame):  # pragma: no cover - never fired
    pass


@needs_usr1
@pytest.mark.parametrize("prior", [signal.SIG_IGN, _custom_handler]
                         if HAS_USR1 else [None])
@pytest.mark.parametrize("path", ["drain", "max_shifts", "stop", "exception"])
def test_b3_restore_on_every_exit_path(tmp_path, monkeypatch, prior, path):
    stop_holder = {}

    def on_run(n, cfg):
        if path == "drain":
            dispatcher.request_drain()
        elif path == "stop":
            stop_holder["stop"].write_text("halt")
        elif path == "exception":
            raise KeyboardInterrupt

    log, stop, _ran, argv = _setup(tmp_path, monkeypatch, on_run=on_run)
    stop_holder["stop"] = stop
    original = signal.getsignal(signal.SIGUSR1)
    signal.signal(signal.SIGUSR1, prior)
    try:
        if path == "exception":
            with pytest.raises(KeyboardInterrupt):
                dispatcher.main(argv)
        else:
            dispatcher.main(argv)
        assert signal.getsignal(signal.SIGUSR1) == prior, path
    finally:
        signal.signal(signal.SIGUSR1, original)


# ---------------------------------------------------------------- behavior 4

@needs_usr1
def test_b4_drain_armed_line_after_dispatcher_up(tmp_path, monkeypatch):
    log, _stop, _ran, argv = _setup(tmp_path, monkeypatch)
    assert dispatcher.main(argv) == 0
    lines = _lines(log)
    armed = [i for i, ln in enumerate(lines) if "drain armed" in ln]
    assert len(armed) == 1, lines
    assert f"drain armed: kill -USR1 {os.getpid()}" in lines[armed[0]]
    up = [i for i, ln in enumerate(lines) if "dispatcher up" in ln]
    assert up and up[0] < armed[0]
    # it comes right after the up line, before any shift line
    shifts = [i for i, ln in enumerate(lines) if "shift 1:" in ln]
    assert shifts and armed[0] < shifts[0]


# ---------------------------------------------------------------- behavior 5

def _assert_drain_after_one(log, ran, rc):
    lines = _lines(log)
    text = "\n".join(lines)
    assert rc == 0
    assert ran == ["A"] or len(ran) == 1, ran
    assert any("shift 1:" in ln and "->" in ln for ln in lines), text
    assert not any("shift 2:" in ln for ln in lines), text
    h = [i for i, ln in enumerate(lines) if "drain honored after 1 shifts" in ln]
    d = [i for i, ln in enumerate(lines)
         if "dispatcher down; shifts this session=1" in ln]
    assert h and d and h[0] < d[0], text
    assert not any("max-shifts 5 reached" in ln for ln in lines), text


def test_b5_drain_via_request_drain_mid_shift(tmp_path, monkeypatch):
    log, _stop, ran, argv = _setup(
        tmp_path, monkeypatch,
        on_run=lambda n, cfg: dispatcher.request_drain() if n == 1 else None)
    rc = dispatcher.main(argv)
    _assert_drain_after_one(log, ran, rc)


@needs_usr1
def test_b5_drain_via_real_sigusr1_mid_shift(tmp_path, monkeypatch):
    log, _stop, ran, argv = _setup(
        tmp_path, monkeypatch,
        on_run=lambda n, cfg: os.kill(os.getpid(), signal.SIGUSR1)
        if n == 1 else None)
    rc = dispatcher.main(argv)
    _assert_drain_after_one(log, ran, rc)


def test_b5_drain_in_shift_3_stops_after_3(tmp_path, monkeypatch):
    log, _stop, ran, argv = _setup(
        tmp_path, monkeypatch,
        on_run=lambda n, cfg: dispatcher.request_drain() if n == 3 else None)
    rc = dispatcher.main(argv)
    assert rc == 0
    assert len(ran) == 3, ran
    text = log.read_text()
    assert "drain honored after 3 shifts" in text
    assert "dispatcher down; shifts this session=3" in text


# ---------------------------------------------------------------- behavior 6

def test_b6_no_drain_unchanged(tmp_path, monkeypatch):
    log, _stop, ran, argv = _setup(tmp_path, monkeypatch)
    rc = dispatcher.main(argv)
    assert rc == 0
    assert len(ran) == 5, ran
    text = log.read_text()
    assert "max-shifts 5 reached; stopping" in text
    assert "drain honored" not in text


# ---------------------------------------------------------------- behavior 7

def test_b7_drain_touches_no_sentinel_files(tmp_path, monkeypatch):
    before_root = sorted(p.name for p in ROOT.iterdir())
    log, stop, ran, argv = _setup(
        tmp_path, monkeypatch,
        on_run=lambda n, cfg: dispatcher.request_drain())
    tmp_before = {p.name for p in tmp_path.iterdir()}
    rc = dispatcher.main(argv)
    assert rc == 0 and len(ran) == 1
    assert not stop.exists(), "a drain must not write STOP"
    assert not (tmp_path / "TEAM_NEVER_STOPPED").exists()
    new_tmp = {p.name for p in tmp_path.iterdir()} - tmp_before
    assert new_tmp <= {"DISPATCH_LOG.md"}, new_tmp
    after_root = sorted(p.name for p in ROOT.iterdir())
    assert [n for n in after_root if n not in before_root] == []
    assert not (ROOT / "DRAIN").exists()


def test_b7_foundry_stopping_unaffected_by_drain(tmp_path):
    import foundry
    stop = tmp_path / "STOP"
    cfg = _Cfg("x", stop)
    dispatcher.request_drain()
    assert dispatcher.drain_requested() is True
    if hasattr(foundry, "stopping"):
        try:
            res = foundry.stopping(cfg)
        except Exception:  # signature differs; nothing more to assert here
            return
        assert not res, "a drain must never make a stage see STOP"


# ---------------------------------------------------------------- behavior 8

def test_b8_install_valueerror_runs_normally(tmp_path, monkeypatch):
    log, _stop, ran, argv = _setup(tmp_path, monkeypatch)
    real_signal = signal.signal

    def raising(signum, handler):
        if HAS_USR1 and signum == signal.SIGUSR1:
            raise ValueError("signal only works in main thread")
        return real_signal(signum, handler)

    monkeypatch.setattr(dispatcher.signal, "signal", raising)
    rc = dispatcher.main(argv)
    assert rc == 0
    assert len(ran) == 5
    text = log.read_text()
    assert "drain armed" not in text
    assert "Traceback" not in text
    assert "max-shifts 5 reached; stopping" in text


def test_b8_real_non_main_thread(tmp_path, monkeypatch):
    log, _stop, ran, argv = _setup(tmp_path, monkeypatch)
    box = {}

    def target():
        try:
            box["rc"] = dispatcher.main(argv)
        except BaseException as exc:  # pragma: no cover - reported below
            box["exc"] = exc

    t = threading.Thread(target=target)
    t.start()
    t.join(60)
    assert not t.is_alive()
    assert "exc" not in box, box.get("exc")
    assert box["rc"] == 0
    assert len(ran) == 5
    assert "drain armed" not in log.read_text()


def test_b8_drain_signal_none_installs_nothing(tmp_path, monkeypatch):
    log, _stop, ran, argv = _setup(tmp_path, monkeypatch)
    calls = []
    real_signal = signal.signal

    def spy(signum, handler):
        calls.append(signum)
        return real_signal(signum, handler)

    monkeypatch.setattr(dispatcher, "DRAIN_SIGNAL", None)
    monkeypatch.setattr(dispatcher.signal, "signal", spy)
    rc = dispatcher.main(argv)
    assert rc == 0 and len(ran) == 5
    if HAS_USR1:
        assert signal.SIGUSR1 not in calls, calls
    assert "drain armed" not in log.read_text()


# ---------------------------------------------------------------- behavior 9

def test_b9_docs_name_the_drain_and_the_upgrade_caveat():
    doc = dispatcher.__doc__ or ""
    usage = (ROOT / "USAGE.md").read_text()
    readme = (ROOT / "README.md").read_text()
    for name, text in (("dispatcher docstring", doc), ("USAGE.md", usage),
                       ("README.md", readme)):
        assert "USR1" in text, f"{name} does not name the SIGUSR1 drain"
        low = text.lower()
        assert "drain" in low, name
        assert "STOP" in text, f"{name} lacks the restart-once-with-STOP caveat"
        assert ("dies" in low or "kills" in low), (
            f"{name} does not warn that a pre-ship dispatcher dies on SIGUSR1")
        assert "default action" in low, name
    # USAGE: the drain is named inside the controls cheat-sheet section
    sec = usage.split("## Controls cheat-sheet", 1)
    assert len(sec) == 2, "USAGE.md lost its controls cheat-sheet"
    body = sec[1].split("\n## ", 1)[0]
    assert "kill -USR1" in body
