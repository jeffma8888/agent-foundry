"""Black-box behaviour tests for iter 494 -- read-time event re-classification:
`foundry events --reclassify` / `foundry company-events --reclassify` re-derive
the kind of every `info`-stamped (or unstamped) events.jsonl record from its
`msg` with today's `classify_event`, never overriding a meaningful stamp and
never rewriting the file.

ISOLATION CONTRACT (honored): written solely from the iter-494 PM spec's
Expected Behaviors (1-8), the README/roadmap, the conventions under `tests/`
and the product's OBSERVABLE runtime interface (public names, `--help`, CLI
output). The implementation source, the engineer's/reviewer's notes and
`git diff` were not read.

AMBIGUITY NOTE: the spec's Behavior 2/7 names a `reclassify=False` keyword on
`gather_events` / `events_cli` / `company_events_cli`, but shipped tests
(tests/test_iter44_behavior.py, tests/test_iter152_behavior.py) pin those
parameter lists exactly, and the spec also forbids editing past tests. The
public surface exposes the flag path as sibling seams
(`gather_events_reclassified`, `events_reclassified_cli`,
`company_events_reclassified_cli`) with the HEAD parameter lists, so the
flag-path behaviours are driven through those seams and through the CLI, and
the default path is pinned against HEAD-shaped fakes.

Fully offline: every config / events / dispatch file lives under tmp_path.
"""
import copy
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

NEEDLE = "auth " + "resume"
RESUME_FINAL = "iter 07 · final " + NEEDLE + " 1/24: re-running stage after hold"
RESUME_ENG = "iter 07 · engineer " + NEEDLE + " 2/24: x"


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
        rc = fn(*a, **k)
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


TWO_RECORDS = [
    {"ts": "2026-01-01T00:00:00", "kind": "info", "msg": RESUME_FINAL},
    {"ts": "2026-01-01T00:00:01", "kind": "info", "msg": "hello"},
]

MIXED = [
    {"ts": "t1", "kind": "info", "msg": RESUME_FINAL, "iter": 7},
    {"ts": "t2", "kind": "info", "msg": "hello"},
    {"ts": "t3", "kind": "info", "msg": "iter 08 · pm " + NEEDLE + " 1/24: y", "extra": [1, 2]},
    {"ts": "t4", "kind": "ship", "msg": "iter 09 · final " + NEEDLE + " 1/24: z"},
    {"ts": "t5", "msg": RESUME_ENG},
]


# --------------------------------------------------------------------------
# Behavior 1 -- effective_event_kind is pure and total
# --------------------------------------------------------------------------
@pytest.mark.parametrize("record,expected", [
    ({"kind": "ship", "msg": "auth resume 1/24"}, "ship"),
    ({"kind": "info", "msg": RESUME_FINAL}, "resume"),
    ({"msg": RESUME_ENG}, "resume"),
    ({"kind": "info", "msg": "hello"}, "info"),
    ({"kind": "info", "msg": 5}, "info"),
    ({}, "info"),
    (None, "info"),
    ("x", "info"),
    ({"kind": "", "msg": RESUME_ENG}, "resume"),
    ({"kind": None, "msg": RESUME_ENG}, "resume"),
    ({"kind": 3, "msg": RESUME_ENG}, "resume"),
    ({"kind": "revert", "msg": "hello"}, "revert"),
])
def test_behavior1_spec_examples(record, expected):
    assert foundry.effective_event_kind(record) == expected


@pytest.mark.parametrize("weird", [
    [], 0, 1.5, b"auth resume", object(), {"msg": None}, {"msg": ["a"]},
    {"kind": ["ship"], "msg": 7}, {1: 2},
])
def test_behavior1_total_never_raises_and_returns_str(weird):
    got = foundry.effective_event_kind(weird)
    assert isinstance(got, str) and got == "info"


def test_behavior1_never_mutates_argument():
    for rec in [dict(r) for r in MIXED] + [{"kind": "info", "msg": "hello"}]:
        before = copy.deepcopy(rec)
        foundry.effective_event_kind(rec)
        assert rec == before


def test_behavior1_reads_rules_by_bare_name_at_call_time(monkeypatch):
    rec = {"kind": "info", "msg": "hello there"}
    assert foundry.effective_event_kind(rec) == "info"
    monkeypatch.setattr(foundry, "EVENT_KIND_RULES", (("greet", ("hello",)),))
    assert foundry.effective_event_kind(rec) == "greet"
    # a non-default stamp still wins even under patched rules
    assert foundry.effective_event_kind({"kind": "ship", "msg": "hello"}) == "ship"


def test_behavior1_uses_classify_event_by_bare_name(monkeypatch):
    monkeypatch.setattr(foundry, "classify_event", lambda msg: "patched")
    assert foundry.effective_event_kind({"kind": "info", "msg": "anything"}) == "patched"
    assert foundry.effective_event_kind({"kind": "ship", "msg": "anything"}) == "ship"


# --------------------------------------------------------------------------
# Behavior 2 -- reclassified gather: filter / counts / limit on effective kinds
# --------------------------------------------------------------------------
def test_behavior2_reclassified_gather_counts_and_kind_counts(cfg):
    _write_events(cfg, MIXED)
    s = foundry.gather_events_reclassified(cfg)
    d = s.to_dict()
    assert d["total"] == 5 and d["matched"] == 5
    assert d["kind_counts"] == {"resume": 3, "info": 1, "ship": 1}
    assert [r["kind"] for r in d["events"]] == ["resume", "info", "resume", "ship", "resume"]


def test_behavior2_other_keys_preserved_only_kind_changes(cfg):
    _write_events(cfg, MIXED)
    s = foundry.gather_events_reclassified(cfg)
    got = list(s.records)
    assert len(got) == len(MIXED)
    for orig, new in zip(MIXED, got):
        expect = dict(orig)
        expect["kind"] = foundry.effective_event_kind(orig)
        assert new == expect


def test_behavior2_kind_filter_matches_effective_kind_and_limit_tails(cfg):
    _write_events(cfg, MIXED)
    s = foundry.gather_events_reclassified(cfg, kind="resume")
    assert s.total == 5 and s.matched == 3
    assert [r["ts"] for r in s.records] == ["t1", "t3", "t5"]
    s2 = foundry.gather_events_reclassified(cfg, kind="resume", limit=2)
    assert s2.matched == 3
    assert [r["ts"] for r in s2.records] == ["t3", "t5"]
    assert s2.to_dict()["shown"] == 2


def test_behavior2_default_gather_unchanged(cfg):
    _write_events(cfg, MIXED)
    s = foundry.gather_events(cfg)
    d = s.to_dict()
    assert d["kind_counts"] == {"info": 3, "ship": 1, "(none)": 1}, d["kind_counts"]
    assert "resume" not in d["kind_counts"]
    assert [r.get("kind") for r in s.records][:4] == ["info", "info", "info", "ship"]
    assert foundry.gather_events(cfg, kind="resume").matched == 0
    assert list(inspect.signature(foundry.gather_events).parameters) == ["cfg", "kind", "limit"]


def test_behavior2_malformed_lines_still_counted(cfg):
    _write_events(cfg, TWO_RECORDS, extra_lines=["{not json"])
    a = foundry.gather_events(cfg).to_dict()
    b = foundry.gather_events_reclassified(cfg).to_dict()
    assert a["parse_errors"] == b["parse_errors"] == 1
    assert a["total"] == b["total"] == 2


# --------------------------------------------------------------------------
# Behavior 3 -- never writes the events file
# --------------------------------------------------------------------------
def test_behavior3_reclassified_gather_never_writes(cfg):
    path = _write_events(cfg, MIXED, extra_lines=["garbage"])
    before = path.read_bytes()
    mtime = path.stat().st_mtime_ns
    tree_before = sorted(str(p) for p in path.parent.rglob("*"))
    foundry.gather_events_reclassified(cfg)
    foundry.gather_events_reclassified(cfg, kind="resume", limit=1)
    _capture(foundry.events_reclassified_cli, cfg, kind="resume", as_json=True)
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime
    assert sorted(str(p) for p in path.parent.rglob("*")) == tree_before


# --------------------------------------------------------------------------
# Behavior 4 -- CLI events --reclassify
# --------------------------------------------------------------------------
def test_behavior4_cli_events_reclassify_json(cfg, cfg_path):
    _write_events(cfg, TWO_RECORDS)
    r = _cli("events", "--config", str(cfg_path), "--kind", "resume", "--reclassify", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    d = json.loads(r.stdout)
    assert d["matched"] == 1 and d["total"] == 2
    assert [e["kind"] for e in d["events"]] == ["resume"]
    assert d["events"][0]["msg"] == RESUME_FINAL


def test_behavior4_cli_events_reclassify_human(cfg, cfg_path):
    _write_events(cfg, TWO_RECORDS)
    r = _cli("events", "--config", str(cfg_path), "--kind", "resume", "--reclassify")
    assert r.returncode == 0, r.stdout + r.stderr
    assert RESUME_FINAL in r.stdout
    assert "hello" not in r.stdout


def test_behavior4_without_flag_unchanged_exit2(cfg, cfg_path):
    _write_events(cfg, TWO_RECORDS)
    r = _cli("events", "--config", str(cfg_path), "--kind", "resume", "--json")
    assert r.returncode == 2, r.stdout + r.stderr
    d = json.loads(r.stdout)
    assert d["matched"] == 0 and d["total"] == 2 and d["events"] == []


# --------------------------------------------------------------------------
# Behavior 5 -- a non-default stamp is never re-kinded
# --------------------------------------------------------------------------
def test_behavior5_ship_stamp_kept(cfg, cfg_path):
    _write_events(cfg, [{"ts": "t", "kind": "ship", "msg": "iter 3 · final " + NEEDLE + " 1/2: q"}])
    r = _cli("events", "--config", str(cfg_path), "--reclassify", "--kind", "resume", "--json")
    assert r.returncode == 2 and json.loads(r.stdout)["matched"] == 0
    r = _cli("events", "--config", str(cfg_path), "--reclassify", "--kind", "ship", "--json")
    assert r.returncode == 0
    d = json.loads(r.stdout)
    assert d["matched"] == 1 and d["events"][0]["kind"] == "ship"


# --------------------------------------------------------------------------
# Behavior 6 -- company-events --reclassify over every enabled team
# --------------------------------------------------------------------------
def test_behavior6_company_events_reclassify_sums(tmp_path):
    items = []
    for n in ("alpha", "beta"):
        p = _write_cfg(tmp_path, n)
        _write_events(foundry.load_config(str(p)), TWO_RECORDS)
        items.append({"name": n, "config": str(p)})
    items.append({"name": "off", "config": str(tmp_path / "missing.json"), "enabled": False})
    disp = tmp_path / "dispatch.json"
    disp.write_text(json.dumps({"work_items": items}))
    r = _cli("company-events", "--config", str(disp), "--kind", "resume", "--reclassify", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    d = json.loads(r.stdout)
    assert d["matched"] == 2
    assert d["kind_counts"].get("resume") == 2
    assert [p["matched"] for p in d["products"]] == [1, 1]
    assert d["errors"] == []
    r2 = _cli("company-events", "--config", str(disp), "--kind", "resume", "--json")
    d2 = json.loads(r2.stdout)
    assert d2["matched"] == 0 and d2["kind_counts"].get("resume", 0) == 0


# --------------------------------------------------------------------------
# Behavior 7 -- seam compatibility: default path keeps HEAD call shapes
# --------------------------------------------------------------------------
def test_behavior7_main_without_flag_calls_head_shaped_events_cli(cfg_path, monkeypatch):
    calls = []

    def fake(cfg_arg, kind=None, limit=None, as_json=False):
        calls.append((kind, limit, as_json))
        return 5

    def boom(*a, **k):
        raise AssertionError("reclassified path used without --reclassify")

    monkeypatch.setattr(foundry, "events_cli", fake)
    monkeypatch.setattr(foundry, "events_reclassified_cli", boom)
    monkeypatch.setattr(foundry, "gather_events_reclassified", boom)
    rc = foundry.main(["events", "--config", str(cfg_path), "--kind", "x", "--limit", "2"])
    assert rc == 5 and calls == [("x", 2, False)]


def test_behavior7_main_without_flag_calls_head_shaped_company_events_cli(monkeypatch):
    calls = []
    monkeypatch.setattr(foundry, "company_events_cli",
                        lambda dp, kind=None, limit=None, as_json=False:
                        calls.append((dp, kind, limit, as_json)) or 4)

    def boom(*a, **k):
        raise AssertionError("reclassified path used without --reclassify")

    monkeypatch.setattr(foundry, "company_events_reclassified_cli", boom)
    monkeypatch.setattr(foundry, "gather_events_reclassified", boom)
    rc = foundry.main(["company-events", "--config", "d.json", "--kind", "k", "--json"])
    assert rc == 4 and calls == [("d.json", "k", None, True)]


def test_behavior7_default_events_cli_calls_head_shaped_gather(cfg, monkeypatch):
    seen = []
    real = foundry.gather_events

    def fake_gather(cfg_arg, kind=None, limit=None):
        seen.append((kind, limit))
        return real(cfg_arg, kind, limit)

    monkeypatch.setattr(foundry, "gather_events", fake_gather)
    _write_events(cfg, TWO_RECORDS)
    rc, out, _ = _capture(foundry.events_cli, cfg, kind="resume", as_json=True)
    assert rc == 2 and seen == [("resume", None)]
    assert json.loads(out)["matched"] == 0


def test_behavior7_main_with_flag_reclassifies_in_process(cfg, cfg_path):
    _write_events(cfg, TWO_RECORDS)
    rc, out, _ = _capture(foundry.main, ["events", "--config", str(cfg_path),
                                         "--kind", "resume", "--reclassify", "--json"])
    assert rc == 0 and json.loads(out)["matched"] == 1
    rc, out, _ = _capture(foundry.main, ["events", "--config", str(cfg_path),
                                         "--kind", "resume", "--json"])
    assert rc == 2 and json.loads(out)["matched"] == 0


def test_behavior7_flag_path_tolerates_head_shaped_gather_fake(cfg, monkeypatch):
    """With --reclassify, any gather_events fake of HEAD shape must still work
    (a reclassify= kwarg forwarded to it would raise TypeError)."""
    real = foundry.gather_events
    monkeypatch.setattr(foundry, "gather_events",
                        lambda c, kind=None, limit=None: real(c, kind, limit))
    _write_events(cfg, TWO_RECORDS)
    rc, out, _ = _capture(foundry.events_reclassified_cli, cfg, kind="resume", as_json=True)
    assert rc == 0 and json.loads(out)["matched"] == 1


def test_behavior7_shipped_signatures_unchanged():
    assert list(inspect.signature(foundry.gather_events).parameters) == ["cfg", "kind", "limit"]
    assert list(inspect.signature(foundry.events_cli).parameters) == ["cfg", "kind", "limit", "as_json"]
    assert list(inspect.signature(foundry.company_events_cli).parameters) == \
        ["dispatch_path", "kind", "limit", "as_json"]


# --------------------------------------------------------------------------
# Behavior 8 -- help, import, run_stage guard
# --------------------------------------------------------------------------
@pytest.mark.parametrize("verb", ["events", "company-events"])
def test_behavior8_help_lists_reclassify(verb):
    r = _cli(verb, "--help")
    assert r.returncode == 0
    assert "--reclassify" in r.stdout


def test_behavior8_import_clean_and_run_stage_has_no_classifier():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "classify_event" not in inspect.getsource(foundry.run_stage)
    assert "effective_event_kind" not in inspect.getsource(foundry.run_stage)
