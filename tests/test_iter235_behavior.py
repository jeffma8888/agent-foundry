"""Black-box behaviour tests for iter 235 -- `foundry.log()` can no longer raise
(roadmap item 23, the `foundry.py` half of the crash-safety fix).

ISOLATION: written SOLELY from the iter-235 PM spec (`pm.md`, Expected Behaviors
1-7), the existing test conventions under `tests/` (the `_write_cfg`/`cfg`/
`_nonempty_lines` trio from `test_iter05_behavior.py`), and the product's own
runtime interface driven as a black box. The implementation source of
`foundry.py`, the engineer's/reviewer's notes for this iteration, and `git diff`
were NOT read. The only shape discovered by runtime introspection (permitted)
is that `ProductConfig.night_log` is a read-only property under `work_root`,
which is why Behaviors 4 and 5 make that PATH a directory instead of assigning
to the attribute.

Every effect is offline and deterministic: a `ProductConfig` whose `work_root`
is under `tmp_path`, plus `monkeypatch` over `builtins.print` and the
`foundry.emit_event` bare-name seam. No subprocess, no git, no network.
"""
import builtins
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402


# --------------------------------------------------------------------------
# helpers / fixtures (mirror test_iter05_behavior.py's conventions)
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    data = {
        "name": "demo",
        "repo": "{FOUNDRY}/products/demo/repo",
        "allowed_push_repo": "demo",
        "vision": "{FOUNDRY}/products/demo/VISION.md",
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def cfg(tmp_path):
    return foundry.load_config(str(_write_cfg(tmp_path)))


def _nonempty_lines(path):
    return [ln for ln in path.read_text().splitlines() if ln.strip()]


def _break_night_log(cfg):
    """Make the durable write fail with IsADirectoryError, black-box.

    `night_log` is a read-only property, so the spec's "point it at an existing
    DIRECTORY" is done by creating a directory AT that path.
    """
    cfg.night_log.parent.mkdir(parents=True, exist_ok=True)
    cfg.night_log.mkdir()
    assert cfg.night_log.is_dir()
    return cfg.night_log


# ==========================================================================
# Behavior 1 -- a dead console does not propagate out of log()
# ==========================================================================
def test_b1_dead_console_oserror_does_not_propagate(cfg, monkeypatch):
    def _dead(*a, **k):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(builtins, "print", _dead)
    assert foundry.log(cfg, "msg") is None, "log() must return None, not a value"


# ==========================================================================
# Behavior 2 -- the durable record still lands when the console is dead
# ==========================================================================
def test_b2_durable_line_lands_despite_dead_console(cfg, monkeypatch):
    def _dead(*a, **k):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(builtins, "print", _dead)
    foundry.log(cfg, "msg")
    monkeypatch.undo()

    assert cfg.night_log.exists(), "NIGHT_LOG was never created"
    last = _nonempty_lines(cfg.night_log)[-1]
    assert last.startswith("- `"), f"unexpected human line prefix: {last!r}"
    suffix = "` [" + cfg.name + "] msg"
    assert last.endswith(suffix), f"unexpected human line suffix: {last!r}"


# ==========================================================================
# Behavior 3 -- a closed stream does not propagate out of log()
# ==========================================================================
def test_b3_closed_stream_valueerror_does_not_propagate(cfg, monkeypatch):
    def _closed(*a, **k):
        raise ValueError("I/O operation on closed file")

    monkeypatch.setattr(builtins, "print", _closed)
    assert foundry.log(cfg, "msg") is None, "log() must return None, not a value"


# ==========================================================================
# Behavior 4 -- an unwritable night log does not propagate, AND the console
#               line is still attempted (the two guards are independent)
# ==========================================================================
def test_b4_unwritable_night_log_still_attempts_console(cfg, monkeypatch):
    _break_night_log(cfg)
    seen = []

    def _spy(*a, **k):
        seen.append(a[0] if a else None)

    monkeypatch.setattr(builtins, "print", _spy)
    assert foundry.log(cfg, "msg") is None, "log() must return None, not a value"
    monkeypatch.undo()

    assert len(seen) == 1, f"console attempted {len(seen)} times, expected exactly 1"
    assert isinstance(seen[0], str), f"console arg was not a str: {seen[0]!r}"
    assert seen[0].endswith("] msg"), f"unexpected console line: {seen[0]!r}"


# ==========================================================================
# Behavior 5 -- both writes failing still reaches the JSON mirror
# ==========================================================================
def test_b5_both_writes_failing_still_emits_mirror(cfg, monkeypatch):
    _break_night_log(cfg)
    events = []

    def _emit(events_path, event, **fields):
        events.append((events_path, event, fields))

    def _dead(*a, **k):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(foundry, "emit_event", _emit)
    monkeypatch.setattr(builtins, "print", _dead)
    assert foundry.log(cfg, "msg") is None, "log() must return None, not a value"
    monkeypatch.undo()

    assert len(events) == 1, f"emit_event seam invoked {len(events)} times, expected exactly 1"
    assert events[0][1] == "log", f"mirror event name was {events[0][1]!r}, expected 'log'"


# ==========================================================================
# Behavior 6 -- the console guard is narrow, not a blanket swallow
# ==========================================================================
def test_b6_console_guard_is_narrow_not_blanket(cfg, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(builtins, "print", _boom)
    with pytest.raises(RuntimeError, match="boom"):
        foundry.log(cfg, "msg")


# ==========================================================================
# Behavior 7 -- the healthy path is unchanged
# ==========================================================================
def test_b7_healthy_path_unchanged(cfg, monkeypatch):
    seen = []

    def _spy(*a, **k):
        seen.append(a[0] if a else None)

    monkeypatch.setattr(builtins, "print", _spy)
    foundry.log(cfg, "msg")
    monkeypatch.undo()

    night = _nonempty_lines(cfg.night_log)
    assert len(night) == 1, f"NIGHT_LOG holds {len(night)} non-empty lines, expected exactly 1"
    assert night[0].endswith("` [" + cfg.name + "] msg"), f"unexpected line: {night[0]!r}"

    assert cfg.events_log.exists(), "events.jsonl was never created"
    records = _nonempty_lines(cfg.events_log)
    assert len(records) == 1, f"events.jsonl holds {len(records)} records, expected exactly 1"
    obj = json.loads(records[0])
    assert obj["event"] == "log", f"mirror event was {obj['event']!r}, expected 'log'"
    assert obj["msg"] == "msg", f"mirror msg was {obj['msg']!r}, expected 'msg'"

    assert len(seen) == 1, f"console written {len(seen)} times, expected exactly 1"
