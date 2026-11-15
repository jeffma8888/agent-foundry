"""Black-box behaviour tests for iter 539 -- `foundry events --since Nd|YYYY-MM-DD`
keeps only the event records stamped on or after local midnight of that date,
applied BEFORE --kind / --limit, combinable with --json / --reclassify, and
leaves every invocation without the flag byte-identical.

ISOLATION CONTRACT (honored): written solely from the iter-539 PM spec's
Expected Behaviors (1-10), the README/roadmap, the conventions under `tests/`
and the product's OBSERVABLE runtime interface (public names, signatures,
`--help`, CLI output). The implementation source, the engineer's/reviewer's
notes and `git diff` were not read.

Fully offline: every config / events file lives under tmp_path. The CLI
fixtures use 2020-vs-2030 stamps so the local zone cannot matter.
"""
import copy
import datetime as dt
import importlib.util
import inspect
import io
import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import foundry  # noqa: E402

UTC = dt.timezone.utc
NEEDLE = "auth " + "resume"
RESUME_FINAL = "iter 07 · final " + NEEDLE + " 1/24: re-running stage after hold"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, name="demoprod"):
    base = pathlib.Path(tmp_path) / name
    base.mkdir(parents=True, exist_ok=True)
    data = {
        "name": name,
        "repo": str(base / "repo"),
        "allowed_push_repo": name,
        "vision": str(base / "VISION.md"),
        "work_root": str(base / "work"),
    }
    p = base / "config.json"
    p.write_text(json.dumps(data))
    return p


def _write_events(cfg, records, extra_lines=()):
    path = pathlib.Path(cfg.events_log)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r) for r in records] + list(extra_lines)
    path.write_text("\n".join(lines) + "\n")
    return path


def _capture(fn, *a, **k):
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        try:
            rc = fn(*a, **k)
        except SystemExit as exc:  # argparse errors
            rc = exc.code
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _cli(*args):
    return subprocess.run([sys.executable, str(REPO / "foundry.py"), *args],
                          capture_output=True, text=True, timeout=60)


@pytest.fixture
def cfg_path(tmp_path):
    return _write_cfg(tmp_path)


@pytest.fixture
def cfg(cfg_path):
    return foundry.load_config(str(cfg_path))


OLD = [
    {"ts": "2020-01-01T00:00:00+00:00", "kind": "ship", "msg": "old-ship"},
    {"ts": "2020-02-01T00:00:00+00:00", "kind": "info", "msg": "old-info"},
]
NEW = [
    {"ts": "2030-01-01T00:00:00+00:00", "kind": "ship", "msg": "new-ship-1"},
    {"ts": "2030-01-02T00:00:00+00:00", "kind": "backoff", "msg": "new-backoff"},
    {"ts": "2030-01-03T00:00:00+00:00", "kind": "ship", "msg": "new-ship-2"},
]
FIVE = OLD + NEW
MALFORMED = ["{not json", "also not json"]


def _json(cfg_path, *extra):
    rc, out, err = _capture(foundry.main, ["events", "--config", str(cfg_path), "--json", *extra])
    return rc, json.loads(out)


# --------------------------------------------------------------------------
# Behavior 1 -- events_window_start
# --------------------------------------------------------------------------
def test_behavior1_utc_midnight():
    got = foundry.events_window_start("2026-11-10", UTC)
    assert got == dt.datetime(2026, 11, 10, 0, 0, 0, tzinfo=UTC)
    assert got.tzinfo is not None
    assert (got.hour, got.minute, got.second, got.microsecond) == (0, 0, 0, 0)


def test_behavior1_negative_offset_instant():
    minus5 = dt.timezone(dt.timedelta(hours=-5))
    got = foundry.events_window_start("2026-11-10", minus5)
    assert got.tzinfo is not None
    assert got.astimezone(UTC) == dt.datetime(2026, 11, 10, 5, 0, 0, tzinfo=UTC)
    assert got.astimezone(UTC).isoformat() == "2026-11-10T05:00:00+00:00"


def test_behavior1_positive_offset_instant():
    plus1 = dt.timezone(dt.timedelta(hours=1))
    got = foundry.events_window_start("2026-11-10", plus1)
    assert got.astimezone(UTC) == dt.datetime(2026, 11, 9, 23, 0, 0, tzinfo=UTC)


def test_behavior1_default_is_aware_local_midnight():
    got = foundry.events_window_start("2026-11-10")
    assert got.tzinfo is not None
    local = got.astimezone()
    assert local.replace(tzinfo=None) == dt.datetime(2026, 11, 10, 0, 0, 0)
    # same instant as the spec's own local-midnight formula
    assert got == dt.datetime.combine(dt.date(2026, 11, 10), dt.time()).astimezone()


# --------------------------------------------------------------------------
# Behavior 2 -- filter_events_since is pure, total, inclusive, order-keeping
# --------------------------------------------------------------------------
START = dt.datetime(2026, 11, 10, 0, 0, 0, tzinfo=UTC)
B2_RECORDS = [
    {"id": "a", "ts": "2026-11-09T23:59:59+00:00"},   # DROP
    {"id": "b", "ts": "2026-11-10T00:00:00+00:00"},   # KEEP boundary
    {"id": "c", "ts": "2026-11-10T01:00:00+01:00"},   # KEEP same instant
    {"id": "d", "ts": "2026-11-10T00:30:00+01:00"},   # DROP
    {"id": "e", "ts": "2026-11-10T05:00:00"},         # KEEP naive=UTC
    {"id": "f", "ts": "garbage"},                     # DROP
    {"id": "g", "ts": 123},                           # DROP
    {"id": "h", "ts": None},                          # DROP
    {"id": "i"},                                      # DROP
]


def test_behavior2_spec_table_keeps_exactly_marked_in_order():
    got = foundry.filter_events_since(B2_RECORDS, START)
    assert [r["id"] for r in got] == ["b", "c", "e"]
    assert got[0] == B2_RECORDS[1]


@pytest.mark.parametrize("idx,keep", [
    (0, False), (1, True), (2, True), (3, False), (4, True),
    (5, False), (6, False), (7, False), (8, False),
])
def test_behavior2_each_row_alone(idx, keep):
    got = foundry.filter_events_since([B2_RECORDS[idx]], START)
    assert got == ([B2_RECORDS[idx]] if keep else [])


def test_behavior2_naive_stamp_read_as_utc_not_local():
    # one second before START as a naive stamp must drop; START itself keeps
    assert foundry.filter_events_since([{"ts": "2026-11-09T23:59:59"}], START) == []
    assert foundry.filter_events_since([{"ts": "2026-11-10T00:00:00"}], START) == [
        {"ts": "2026-11-10T00:00:00"}]


def test_behavior2_empty_and_no_mutation():
    assert foundry.filter_events_since([], START) == []
    snapshot = copy.deepcopy(B2_RECORDS)
    foundry.filter_events_since(B2_RECORDS, START)
    assert B2_RECORDS == snapshot


@pytest.mark.parametrize("weird_ts", ["", "2026-13-01T00:00:00", [1], {"a": 1}, 1.5, True])
def test_behavior2_weird_ts_never_raises(weird_ts):
    assert foundry.filter_events_since([{"ts": weird_ts}], START) == []


# --------------------------------------------------------------------------
# Behavior 3 -- CLI window keeps only the 2030 records
# --------------------------------------------------------------------------
def test_behavior3_cli_subprocess_window(cfg, cfg_path):
    _write_events(cfg, FIVE)
    res = _cli("events", "--config", str(cfg_path), "--since", "2025-01-01")
    assert res.returncode == 0, res.stderr
    for r in NEW:
        assert r["msg"] in res.stdout
    for r in OLD:
        assert r["msg"] not in res.stdout


def test_behavior3_cli_json_window(cfg, cfg_path):
    _write_events(cfg, FIVE)
    rc, doc = _json(cfg_path, "--since", "2025-01-01")
    assert rc == 0
    assert [e["msg"] for e in doc["events"]] == [r["msg"] for r in NEW]
    assert doc["shown"] == 3


def test_behavior3_nd_form_window(cfg, cfg_path):
    future = {"ts": "2099-06-01T00:00:00+00:00", "kind": "ship", "msg": "future"}
    _write_events(cfg, OLD + [future])
    rc, doc = _json(cfg_path, "--since", "7d")
    assert rc == 0
    assert [e["msg"] for e in doc["events"]] == ["future"]


# --------------------------------------------------------------------------
# Behavior 4 -- window first, then kind, then limit tail
# --------------------------------------------------------------------------
def test_behavior4_order_of_operations_json(cfg, cfg_path):
    _write_events(cfg, FIVE, extra_lines=MALFORMED)
    rc, doc = _json(cfg_path, "--since", "2025-01-01", "--kind", "ship", "--limit", "1")
    assert rc == 0
    assert [e["msg"] for e in doc["events"]] == ["new-ship-2"]
    assert doc["total"] == 5
    assert doc["matched"] == 2
    assert doc["shown"] == 1
    assert doc["parse_errors"] == len(MALFORMED)


def test_behavior4_order_of_operations_human(cfg, cfg_path):
    _write_events(cfg, FIVE)
    rc, out, _ = _capture(foundry.main, ["events", "--config", str(cfg_path),
                                         "--since", "2025-01-01", "--kind", "ship", "--limit", "1"])
    assert rc == 0
    assert "new-ship-2" in out
    assert "new-ship-1" not in out and "old-ship" not in out


def test_behavior4_limit_tail_is_after_window_not_before(cfg, cfg_path):
    # if the limit were applied before the window, limit 2 of the whole file
    # would still be the 2030 tail; put an old record LAST to tell them apart
    _write_events(cfg, NEW + [OLD[0]])
    rc, doc = _json(cfg_path, "--since", "2025-01-01", "--limit", "2")
    assert rc == 0
    assert [e["msg"] for e in doc["events"]] == ["new-backoff", "new-ship-2"]


def test_behavior4_gather_events_since_direct(cfg):
    _write_events(cfg, FIVE, extra_lines=MALFORMED)
    s = foundry.gather_events_since(cfg, kind="ship", limit=1, since="2025-01-01")
    d = s.to_dict()
    assert (d["total"], d["matched"], d["shown"], d["parse_errors"]) == (5, 2, 1, 2)
    assert [e["msg"] for e in d["events"]] == ["new-ship-2"]


def test_behavior4_gather_events_since_uses_gather_events_by_bare_name(cfg, monkeypatch):
    _write_events(cfg, FIVE)
    calls = []
    real = foundry.gather_events

    def spy(*a, **k):
        calls.append((a, k))
        return real(*a, **k)

    monkeypatch.setattr(foundry, "gather_events", spy)
    foundry.gather_events_since(cfg, kind="ship", limit=1, since="2025-01-01")
    assert len(calls) == 1
    a, k = calls[0]
    assert k.get("kind") is None and k.get("limit") is None
    assert len(a) <= 1 or all(x is None for x in a[1:])


# --------------------------------------------------------------------------
# Behavior 5 -- empty window / absent file
# --------------------------------------------------------------------------
def test_behavior5_empty_window_exits_2(cfg, cfg_path):
    _write_events(cfg, FIVE)
    rc, doc = _json(cfg_path, "--since", "2099-01-01")
    assert rc == 2
    assert doc["shown"] == 0
    rc2, _, _ = _capture(foundry.main, ["events", "--config", str(cfg_path), "--since", "2099-01-01"])
    assert rc2 == 2


def test_behavior5_absent_file_exits_2(cfg, cfg_path):
    assert not pathlib.Path(cfg.events_log).exists()
    rc, out, err = _capture(foundry.main, ["events", "--config", str(cfg_path), "--since", "7d"])
    assert rc == 2
    res = _cli("events", "--config", str(cfg_path), "--since", "7d")
    assert res.returncode == 2
    assert "Traceback" not in res.stderr


# --------------------------------------------------------------------------
# Behavior 6 -- bad --since values are argparse errors; file never read
# --------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["7w", "2026-1-5", "2026-02-30"])
def test_behavior6_bad_since_argparse_error(cfg, cfg_path, bad, monkeypatch):
    _write_events(cfg, FIVE)

    def boom(*a, **k):
        raise AssertionError("events file must not be read")

    for name in ("gather_events", "gather_events_since", "gather_events_reclassified",
                 "events_since_cli", "events_cli", "events_reclassified_cli"):
        if hasattr(foundry, name):
            monkeypatch.setattr(foundry, name, boom)
    rc, out, err = _capture(foundry.main, ["events", "--config", str(cfg_path), "--since", bad])
    assert rc == 2
    assert "--since" in err
    assert out == ""


@pytest.mark.parametrize("bad", ["7w", "2026-1-5", "2026-02-30"])
def test_behavior6_bad_since_subprocess(cfg_path, bad):
    res = _cli("events", "--config", str(cfg_path), "--since", bad)
    assert res.returncode == 2
    assert "error" in res.stderr.lower()
    assert "Traceback" not in res.stderr
    assert res.stdout == ""


# --------------------------------------------------------------------------
# Behavior 7 -- --json key set unchanged
# --------------------------------------------------------------------------
def test_behavior7_json_key_set_identical(cfg, cfg_path):
    _write_events(cfg, FIVE, extra_lines=MALFORMED)
    _, plain = _json(cfg_path)
    _, windowed = _json(cfg_path, "--since", "2025-01-01")
    _, empty = _json(cfg_path, "--since", "2099-01-01")
    assert set(windowed) == set(plain)
    assert set(empty) == set(plain)


# --------------------------------------------------------------------------
# Behavior 8 -- --since + --reclassify selects on read-time kind
# --------------------------------------------------------------------------
def test_behavior8_since_with_reclassify(cfg, cfg_path):
    recs = [
        {"ts": "2020-01-01T00:00:00+00:00", "kind": "info", "msg": RESUME_FINAL + " old"},
        {"ts": "2030-01-01T00:00:00+00:00", "kind": "info", "msg": RESUME_FINAL},
        {"ts": "2030-01-02T00:00:00+00:00", "kind": "info", "msg": "hello"},
    ]
    _write_events(cfg, recs)
    rc, doc = _json(cfg_path, "--since", "2025-01-01", "--reclassify", "--kind", "resume")
    assert rc == 0
    assert [e["msg"] for e in doc["events"]] == [RESUME_FINAL]
    rc2, doc2 = _json(cfg_path, "--since", "2025-01-01", "--kind", "resume")
    assert rc2 == 2
    assert doc2["events"] == []


def test_behavior8_gather_since_reclassify_uses_reclassified_gather(cfg, monkeypatch):
    _write_events(cfg, [{"ts": "2030-01-01T00:00:00+00:00", "kind": "info", "msg": RESUME_FINAL}])
    calls = []
    real = foundry.gather_events_reclassified

    def spy(*a, **k):
        calls.append((a, k))
        return real(*a, **k)

    monkeypatch.setattr(foundry, "gather_events_reclassified", spy)
    s = foundry.gather_events_since(cfg, kind="resume", since="2025-01-01", reclassify=True)
    assert len(calls) == 1
    assert [e["msg"] for e in s.to_dict()["events"]] == [RESUME_FINAL]


# --------------------------------------------------------------------------
# Behavior 9 -- without --since: identical to HEAD; pinned signatures
# --------------------------------------------------------------------------
def test_behavior9_pinned_signatures():
    assert list(inspect.signature(foundry.gather_events).parameters) == ["cfg", "kind", "limit"]
    assert list(inspect.signature(foundry.events_cli).parameters) == [
        "cfg", "kind", "limit", "as_json"]
    assert list(inspect.signature(foundry.company_events_cli).parameters) == [
        "dispatch_path", "kind", "limit", "as_json"]


def test_behavior9_default_golden(cfg, cfg_path):
    _write_events(cfg, FIVE, extra_lines=MALFORMED)
    rc, doc = _json(cfg_path)
    assert rc == 0
    assert [e["msg"] for e in doc["events"]] == [r["msg"] for r in FIVE]
    assert (doc["total"], doc["matched"], doc["shown"], doc["parse_errors"]) == (5, 5, 5, 2)


def _head_module():
    try:
        src = subprocess.run(["git", "-C", str(REPO), "show", "HEAD:foundry.py"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if src.returncode != 0 or not src.stdout:
        return None
    name = "foundry_head_iter539"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(REPO / "foundry.py")
    sys.modules[name] = mod
    try:
        exec(compile(src.stdout, str(REPO / "foundry.py"), "exec"), mod.__dict__)
    except Exception:
        sys.modules.pop(name, None)
        return None
    return mod


DEFAULT_INVOCATIONS = [
    [],
    ["--json"],
    ["--kind", "ship"],
    ["--kind", "ship", "--json"],
    ["--limit", "2"],
    ["--limit", "1", "--json"],
    ["--kind", "nope"],
    ["--reclassify"],
    ["--reclassify", "--kind", "resume", "--json"],
]


@pytest.mark.parametrize("extra", DEFAULT_INVOCATIONS)
def test_behavior9_default_output_identical_to_head(cfg, cfg_path, extra):
    head = _head_module()
    if head is None:
        pytest.skip("HEAD foundry.py not available via git")
    _write_events(cfg, FIVE + [{"ts": "2030-02-01T00:00:00+00:00", "kind": "info",
                                "msg": RESUME_FINAL}], extra_lines=MALFORMED)
    argv = ["events", "--config", str(cfg_path), *extra]
    now = _capture(foundry.main, list(argv))
    then = _capture(head.main, list(argv))
    assert now[:2] == then[:2]


# --------------------------------------------------------------------------
# Behavior 10 -- help and README
# --------------------------------------------------------------------------
def test_behavior10_help_lists_since():
    res = _cli("events", "--help")
    assert res.returncode == 0
    assert "--since" in res.stdout


def test_behavior10_readme_14_line_names_since():
    lines = (REPO / "README.md").read_text().splitlines()
    heads = [i for i, ln in enumerate(lines) if ln.lstrip().startswith("# 14.")]
    assert heads, "README has no '# 14.' section"
    i = heads[0]
    usage = next(ln for ln in lines[i + 1:] if ln.strip())
    assert "foundry.py events" in usage
    assert "--since" in usage
    assert "--reclassify" in usage  # edited in place, not split
