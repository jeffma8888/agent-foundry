"""Black-box behaviour tests for iter 05 -- a structured JSON event log
(`events.jsonl`) mirroring the human NIGHT_LOG (roadmap item 10).

ISOLATION: written SOLELY from the iter-05 PM spec (Expected Behaviors 1-14),
the existing test conventions under `tests/`, and the product's own runtime
interface. The implementation source of `foundry.py`, the engineer's/reviewer's
notes for this iteration, and `git diff` were NOT read. The public function
signatures (`emit_event(events_path, event, **fields) -> None`,
`log(cfg, msg) -> None`) and the `ProductConfig.events_log` property were
discovered by runtime introspection / driving the public interface (permitted),
not by reading source bodies.

Every effect is offline and deterministic: `emit_event` writes only to a
caller-supplied `tmp_path`; the `log()` integration behaviors use a
`ProductConfig` whose `work_root` is under `tmp_path`. No real
git/network/subprocess/agent-run except the Behavior-14 `git check-ignore`
probe, which touches no network.
"""
import json
import pathlib
import subprocess
import sys
from datetime import datetime

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402


# --------------------------------------------------------------------------
# helpers / fixtures (mirror the other test modules' conventions)
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


# ==========================================================================
# emit_event(events_path, event, **fields) -- the pure JSONL append helper
# ==========================================================================

# Behavior 1 -- creates the file and appends exactly one line
def test_b1_creates_file_and_one_line(tmp_path):
    p = tmp_path / "events.jsonl"
    assert not p.exists()
    foundry.emit_event(p, "started")
    assert p.exists()
    lines = _nonempty_lines(p)
    assert len(lines) == 1, f"expected exactly 1 line, got {len(lines)}"


# Behavior 2 -- each line is a valid JSON object carrying reserved keys ts + event
def test_b2_line_is_json_object_with_reserved_keys(tmp_path):
    p = tmp_path / "events.jsonl"
    foundry.emit_event(p, "started")
    obj = json.loads(_nonempty_lines(p)[0])
    assert isinstance(obj, dict)
    assert "ts" in obj, "reserved key 'ts' missing"
    assert "event" in obj, "reserved key 'event' missing"
    assert obj["event"] == "started"


# Behavior 3 -- ts is a timezone-AWARE ISO-8601 timestamp
def test_b3_ts_is_tz_aware_iso8601(tmp_path):
    p = tmp_path / "events.jsonl"
    foundry.emit_event(p, "started")
    obj = json.loads(_nonempty_lines(p)[0])
    dt = datetime.fromisoformat(obj["ts"])   # must parse
    assert dt.tzinfo is not None, "ts must be tz-aware (non-None tzinfo)"


# Behavior 4 -- extra **fields become top-level keys with types preserved
def test_b4_extra_fields_preserved_with_types(tmp_path):
    p = tmp_path / "events.jsonl"
    foundry.emit_event(p, "shipped", head="abc123", iteration=4)
    obj = json.loads(_nonempty_lines(p)[0])
    assert obj["event"] == "shipped"
    assert "ts" in obj
    assert obj["head"] == "abc123"
    assert isinstance(obj["head"], str)
    assert obj["iteration"] == 4
    assert isinstance(obj["iteration"], int) and not isinstance(obj["iteration"], bool)


# Behavior 5 -- append-only, one line per call, order preserved, prior bytes intact
def test_b5_append_only_order_preserved(tmp_path):
    p = tmp_path / "events.jsonl"
    foundry.emit_event(p, "a")
    first_bytes = p.read_bytes()
    foundry.emit_event(p, "b")
    lines = _nonempty_lines(p)
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "a"
    assert json.loads(lines[1])["event"] == "b"
    # the first line's bytes are unchanged by the 2nd call
    assert p.read_bytes().startswith(first_bytes), "2nd emit rewrote/mutated the 1st line"


# Behavior 6 -- parent directories are auto-created
def test_b6_parent_dirs_autocreated(tmp_path):
    p = tmp_path / "x" / "y" / "events.jsonl"
    assert not p.parent.exists()
    foundry.emit_event(p, "started")
    assert p.exists()
    lines = _nonempty_lines(p)
    assert len(lines) == 1
    json.loads(lines[0])   # valid JSON


# Behavior 7 -- a caller-supplied ts in **fields cannot shadow the real timestamp
def test_b7_caller_ts_cannot_shadow(tmp_path):
    p = tmp_path / "events.jsonl"
    foundry.emit_event(p, "e", ts="HACK")
    obj = json.loads(_nonempty_lines(p)[0])
    assert obj["ts"] != "HACK", "caller-supplied ts wrongly shadowed the real one"
    dt = datetime.fromisoformat(obj["ts"])
    assert dt.tzinfo is not None


# Behavior 8 -- a non-serializable field value degrades gracefully and never raises
def test_b8_non_serializable_field_degrades_gracefully(tmp_path):
    p = tmp_path / "events.jsonl"
    foundry.emit_event(p, "e", obj=object())   # must NOT raise
    obj = json.loads(_nonempty_lines(p)[0])    # still valid JSON
    assert "obj" in obj
    assert isinstance(obj["obj"], str), "non-serializable value must be rendered as a string"


# ==========================================================================
# ProductConfig.events_log -- the per-product path property
# ==========================================================================

# Behavior 9 -- cfg.events_log is <work_root>/events.jsonl (Path), beside night_log
def test_b9_events_log_path(cfg):
    assert isinstance(cfg.events_log, pathlib.Path)
    assert cfg.events_log == pathlib.Path(cfg.work_root) / "events.jsonl"
    assert cfg.events_log.parent == cfg.night_log.parent


# ==========================================================================
# log(cfg, msg) integration
# ==========================================================================

# Behavior 10 -- the human NIGHT_LOG line is byte-for-byte unchanged in format
def test_b10_night_log_human_line_unchanged(cfg):
    foundry.log(cfg, "iter 05 begins")
    last = _nonempty_lines(cfg.night_log)[-1]
    # format: - `<ts>` [<name>] <msg>
    assert last.startswith("- `"), f"unexpected human line prefix: {last!r}"
    suffix = "` [" + cfg.name + "] iter 05 begins"
    assert last.endswith(suffix), f"unexpected human line suffix: {last!r}"
    ts = last[len("- `"):last.index("` [")]
    assert ts.strip(), "backtick-wrapped timestamp is empty"


# Behavior 11 -- log() ALSO emits a JSON event mirroring the message
def test_b11_log_emits_json_mirror(cfg):
    foundry.log(cfg, "iter 05 begins")
    assert cfg.events_log.exists()
    lines = _nonempty_lines(cfg.events_log)
    assert len(lines) >= 1
    obj = json.loads(lines[-1])
    assert obj["event"] == "log"
    assert obj["product"] == cfg.name
    assert obj["msg"] == "iter 05 begins"
    dt = datetime.fromisoformat(obj["ts"])   # tz-aware per Behavior 3
    assert dt.tzinfo is not None


# Behavior 12 -- log() never breaks if the machine mirror fails; markdown still written
def test_b12_log_survives_mirror_failure(cfg, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("mirror emit exploded")
    monkeypatch.setattr(foundry, "emit_event", _boom)
    # must NOT raise even though the mirror emit raises
    foundry.log(cfg, "still logs")
    last = _nonempty_lines(cfg.night_log)[-1]
    assert last.endswith("] still logs"), "durable NIGHT_LOG line not written on mirror failure"
    assert cfg.name in last


# Behavior 13 -- the emit_event seam is monkeypatch-visible; called once per log()
def test_b13_emit_event_seam_monkeypatch_visible(cfg, monkeypatch):
    calls = []

    def _spy(events_path, event, **fields):
        calls.append((events_path, event, fields))

    monkeypatch.setattr(foundry, "emit_event", _spy)
    foundry.log(cfg, "iter 05 begins")
    assert len(calls) == 1, f"emit_event seam invoked {len(calls)} times, expected exactly 1"


# ==========================================================================
# Ship-diff hygiene
# ==========================================================================

# Behavior 14 -- products/*/events.jsonl is git-ignored
def test_b14_events_jsonl_is_gitignored():
    repo = pathlib.Path(foundry.__file__).resolve().parent
    proc = subprocess.run(
        ["git", "check-ignore", "products/_platform/events.jsonl"],
        capture_output=True, text=True, cwd=str(repo))
    assert proc.returncode == 0, (
        "git check-ignore did not report events.jsonl as ignored:\n"
        + proc.stdout + proc.stderr)
    assert "products/_platform/events.jsonl" in proc.stdout
