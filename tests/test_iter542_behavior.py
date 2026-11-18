"""Black-box behaviour tests for iter 542 -- an operator-written
`state/iter-N/PARKED.md` parks a `foundry resumable` row: never OPEN, never
flagged by --write, shown with a one-line reason, reversible by deletion.

ISOLATION CONTRACT (honored): written solely from the iter-542 PM spec's
Expected Behaviors (1-12), the README, the conventions under `tests/` and the
product's OBSERVABLE runtime interface (public names, CLI output).  The
implementation source, the engineer's/reviewer's notes and `git diff` were
not read.

Fully offline: every config and state dir is built under tmp_path; no ambient
products/*/state path is asserted (state/ is gitignored, absent in a clone).
The B9 expectations were minted ONCE from HEAD f618a81's module and are
frozen literals here (no live HEAD comparison, so the ship commit cannot
turn them red).
"""
import io
import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import foundry  # noqa: E402

PATCH = "ABORTED_IMPLEMENTATION.patch"
APPROVE = "Review notes.\n\nVERDICT: APPROVE\n"
PASS = "Tests ok.\n\nRESULT: PASS\n"
PUSHED = "Shipped.\n\nACTION: PUSHED abc123\n"
PARK = "PARKED.md"


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
    return p, base / "work"


def _iter_dir(work, name, files):
    d = work / "state" / name
    d.mkdir(parents=True, exist_ok=True)
    for fname, text in files.items():
        (d / fname).write_text(text)
    return d


def _candidate_files(**extra):
    files = {PATCH: "diff --git a/x b/x\n", "reviewer.md": APPROVE, "tester.md": PASS}
    files.update(extra)
    return files


def _capture(fn, *a, **k):
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        try:
            rc = fn(*a, **k)
        except SystemExit as e:
            rc = e.code
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _run(cfg_path, *flags):
    return _capture(foundry.main, ["resumable", "--config", str(cfg_path), *flags])


def _cli(*args):
    return subprocess.run([sys.executable, str(REPO / "foundry.py"), *args],
                          capture_output=True, text=True, timeout=60)


def _snapshot(root):
    root = pathlib.Path(root)
    return sorted((str(p.relative_to(root)), p.is_dir(),
                   None if p.is_dir() else p.read_bytes())
                  for p in root.rglob("*"))


def _lines(text):
    return [ln for ln in text.splitlines() if ln.strip()]


def _row(text, name):
    hits = [ln for ln in text.splitlines() if ln.startswith(name + "  ")]
    assert len(hits) == 1, (name, text)
    return hits[0]


def _word(text, name):
    return _row(text, name).split()[1]


def _json_rows(out):
    doc = json.loads(out)
    return doc, {r["iteration"]: r for r in doc["rows"]}


@pytest.fixture
def mixed(tmp_path):
    """Spec B3 tree: iter-5 superseded by iter-7 PUSHED, iter-9 open,
    iter-11 parked."""
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-5", _candidate_files())
    _iter_dir(work, "iter-7", {"final.md": PUSHED})
    _iter_dir(work, "iter-9", _candidate_files())
    _iter_dir(work, "iter-11", _candidate_files(**{PARK: "re-land keeps failing review\n"}))
    return cfg_path, work


@pytest.fixture
def lone(tmp_path):
    """Spec B2 tree: a single candidate iter-9 holding PARKED.md."""
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-9", _candidate_files(**{PARK: "patch no longer applies\n"}))
    return cfg_path, work


# --------------------------------------------------------------------------
# Behavior 1 -- constant
# --------------------------------------------------------------------------
def test_b1_park_name():
    assert foundry.RESUMABLE_PARK_NAME == "PARKED.md"


# --------------------------------------------------------------------------
# Behavior 2 -- a lone parked candidate
# --------------------------------------------------------------------------
def test_b2_lone_parked_exits_zero(lone):
    rc, out, err = _run(lone[0])
    assert rc == 0, (out, err)
    row = _row(out, "iter-9")
    assert row.startswith("iter-9  parked  state/iter-9/ABORTED_IMPLEMENTATION.patch  (tester.md)")
    assert row.endswith("  -- patch no longer applies")
    assert _lines(out)[-1] == "resumable (demoprod): 0 open, 0 superseded, 1 parked"


def test_b2_subprocess_exit_and_ascii(lone):
    proc = _cli("resumable", "--config", str(lone[0]))
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr
    assert proc.stdout.isascii()
    assert str(lone[1]) not in proc.stdout  # relative paths only


# --------------------------------------------------------------------------
# Behavior 3 -- mixed fixture
# --------------------------------------------------------------------------
def test_b3_mixed_words_and_exit(mixed):
    rc, out, _ = _run(mixed[0])
    assert rc == 1
    assert _word(out, "iter-5") == "superseded"
    assert _word(out, "iter-9") == "open"
    assert _word(out, "iter-11") == "parked"
    assert _row(out, "iter-11").endswith("  -- re-land keeps failing review")
    assert not _row(out, "iter-9").rstrip().endswith("review")
    assert " -- " not in _row(out, "iter-9")
    assert " -- " not in _row(out, "iter-5")
    assert _lines(out)[-1] == "resumable (demoprod): 1 open, 1 superseded, 1 parked"
    assert not any(ln.startswith("iter-7  ") for ln in out.splitlines())


# --------------------------------------------------------------------------
# Behavior 4 -- parked outranks superseded; counts partition the rows
# --------------------------------------------------------------------------
def test_b4_parked_outranks_superseded(mixed):
    (mixed[1] / "state" / "iter-5" / PARK).write_text("stale\n")
    rc, out, _ = _run(mixed[0])
    assert rc == 1
    assert _word(out, "iter-5") == "parked"
    assert _lines(out)[-1] == "resumable (demoprod): 1 open, 0 superseded, 2 parked"
    rc, jout, _ = _run(mixed[0], "--json")
    doc, rows = _json_rows(jout)
    assert rows[5]["parked"] is True and rows[5]["open"] is False
    assert doc["open_count"] == 1
    assert doc["superseded_count"] == 0
    assert doc["parked_count"] == 2


@pytest.mark.parametrize("park_in", [(), ("iter-11",), ("iter-5",), ("iter-5", "iter-9"),
                                     ("iter-5", "iter-9", "iter-11")])
def test_b4_counts_sum_to_rows(mixed, park_in):
    for name in park_in:
        (mixed[1] / "state" / name / PARK).write_text("x\n")
    # iter-11 holds PARKED.md by fixture; drop it unless parametrized in
    if "iter-11" not in park_in:
        (mixed[1] / "state" / "iter-11" / PARK).unlink()
    rc, jout, _ = _run(mixed[0], "--json")
    doc = json.loads(jout)
    parked = doc.get("parked_count", 0)
    assert parked == len(park_in)
    assert doc["open_count"] + doc["superseded_count"] + parked == len(doc["rows"]) == 3
    assert doc["exit_code"] == rc
    assert rc == (1 if doc["open_count"] else 0)


# --------------------------------------------------------------------------
# Behavior 5 -- reason text
# --------------------------------------------------------------------------
@pytest.mark.parametrize("body,reason", [
    ("patch no longer applies\n", "patch no longer applies"),
    ("\n\n   first real line   \nsecond line\n", "first real line"),
    ("no trailing newline", "no trailing newline"),
    ("", "(no reason given)"),
    ("   \n\t\n  \n", "(no reason given)"),
    ("y" * 300 + "\n", "y" * 120),
    ("z" * 120 + "\n", "z" * 120),
])
def test_b5_reason_text(lone, body, reason):
    (lone[1] / "state" / "iter-9" / PARK).write_text(body)
    rc, out, _ = _run(lone[0])
    assert rc == 0
    assert _row(out, "iter-9").endswith("  -- " + reason)
    _, jout, _ = _run(lone[0], "--json")
    _, rows = _json_rows(jout)
    assert rows[9]["park_reason"] == reason
    assert len(rows[9]["park_reason"]) <= 120


def test_b5_unreadable_directory_still_parks(lone):
    p = lone[1] / "state" / "iter-9" / PARK
    p.unlink()
    p.mkdir()
    rc, out, err = _run(lone[0])
    assert rc == 0, err
    assert _word(out, "iter-9") == "parked"
    assert _row(out, "iter-9").endswith("  -- (unreadable)")
    assert "Traceback" not in err


def test_b5_unreadable_oserror_still_parks(lone, monkeypatch):
    real = pathlib.Path.read_text

    def boom(self, *a, **k):
        if self.name == PARK:
            raise OSError("denied")
        return real(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", boom)
    real_open = open

    def boom_open(file, *a, **k):
        if pathlib.Path(str(file)).name == PARK:
            raise OSError("denied")
        return real_open(file, *a, **k)

    monkeypatch.setattr("builtins.open", boom_open)
    rc, out, err = _run(lone[0])
    assert rc == 0, err
    assert _row(out, "iter-9").endswith("  -- (unreadable)")


# --------------------------------------------------------------------------
# Behavior 6 -- --json
# --------------------------------------------------------------------------
def test_b6_json_parked_row(mixed):
    rc, jout, _ = _run(mixed[0], "--json")
    doc, rows = _json_rows(jout)
    assert rc == 1 and doc["exit_code"] == 1
    assert rows[11]["open"] is False
    assert rows[11]["parked"] is True
    assert rows[11]["park_reason"] == "re-land keeps failing review"
    assert doc["parked_count"] == 1
    assert rows[9]["open"] is True


def test_b6_json_lone_exit_code_matches(lone):
    proc = _cli("resumable", "--config", str(lone[0]), "--json")
    doc = json.loads(proc.stdout)  # exactly one JSON document
    assert proc.returncode == 0 == doc["exit_code"]
    assert doc["parked_count"] == 1


def test_b6_json_no_park_keys_when_none_parked(mixed):
    (mixed[1] / "state" / "iter-11" / PARK).unlink()
    _, jout, _ = _run(mixed[0], "--json")
    doc = json.loads(jout)
    assert "parked_count" not in doc
    for r in doc["rows"]:
        assert "parked" not in r and "park_reason" not in r
    assert "park" not in jout


# --------------------------------------------------------------------------
# Behavior 7 -- --write skips parked dirs
# --------------------------------------------------------------------------
def test_b7_write_only_open_dir(mixed):
    work = mixed[1]
    rc, out, err = _run(mixed[0], "--write")
    assert rc == 1, err
    assert (work / "state" / "iter-9" / "RESUMABLE.md").is_file()
    assert not (work / "state" / "iter-11" / "RESUMABLE.md").exists()
    assert not (work / "state" / "iter-5" / "RESUMABLE.md").exists()


def test_b7_parked_keeps_existing_flag_bytes(mixed):
    flag = mixed[1] / "state" / "iter-11" / "RESUMABLE.md"
    flag.write_bytes(b"hand-written flag\nRESUMABLE: iter-11\n")
    rc, out, _ = _run(mixed[0], "--write")
    assert flag.read_bytes() == b"hand-written flag\nRESUMABLE: iter-11\n"
    row = _row(out, "iter-11")
    assert "  [flagged]" in row
    assert row.index("  [flagged]") < row.index("  -- re-land keeps failing review")
    assert row.endswith("  -- re-land keeps failing review")
    _, jout, _ = _run(mixed[0], "--json")
    _, rows = _json_rows(jout)
    assert rows[11]["flagged"] is True and rows[11]["parked"] is True


# --------------------------------------------------------------------------
# Behavior 8 -- reversible; the verb never touches PARKED.md
# --------------------------------------------------------------------------
def test_b8_delete_unparks(mixed):
    _run(mixed[0])
    (mixed[1] / "state" / "iter-11" / PARK).unlink()
    rc, out, _ = _run(mixed[0])
    assert rc == 1
    assert _word(out, "iter-11") == "open"
    assert "parked" not in out
    _, jout, _ = _run(mixed[0], "--json")
    assert "parked" not in jout


@pytest.mark.parametrize("flags", [(), ("--json",)])
def test_b8_read_runs_change_nothing(mixed, flags):
    before = _snapshot(mixed[1])
    _run(mixed[0], *flags)
    assert _snapshot(mixed[1]) == before


def test_b8_write_never_touches_park_files(mixed):
    state = mixed[1] / "state"
    (state / "iter-5" / PARK).write_text("old\n")
    parks_before = {p: p.read_bytes() for p in state.rglob(PARK)}
    before = _snapshot(mixed[1])
    _run(mixed[0], "--write")
    after = _snapshot(mixed[1])
    added = [e for e in after if e not in before]
    assert [e[0] for e in added] == [str(pathlib.Path("state", "iter-9", "RESUMABLE.md"))]
    assert {p: p.read_bytes() for p in state.rglob(PARK)} == parks_before
    assert not (state / "iter-9" / PARK).exists()


# --------------------------------------------------------------------------
# Behavior 9 -- byte-identical when nothing is parked (frozen HEAD literals)
# --------------------------------------------------------------------------
HEAD_TEXT = (
    "iter-5  superseded  state/iter-5/ABORTED_IMPLEMENTATION.patch  (tester.md)\n"
    "iter-9  open  state/iter-9/ABORTED_IMPLEMENTATION.patch  (tester.md)\n"
    "iter-11  open  state/iter-11/ABORTED_IMPLEMENTATION.patch  (tester.md)  [flagged]\n"
    "resumable (demoprod): 2 open, 1 superseded\n"
)
HEAD_JSON = (
    '{\n  "product": "demoprod",\n  "rows": [\n'
    '    {\n      "iteration": 5,\n      "patch": "state/iter-5/ABORTED_IMPLEMENTATION.patch",\n'
    '      "tester_report": "tester.md",\n      "open": false,\n      "flagged": false\n    },\n'
    '    {\n      "iteration": 9,\n      "patch": "state/iter-9/ABORTED_IMPLEMENTATION.patch",\n'
    '      "tester_report": "tester.md",\n      "open": true,\n      "flagged": false\n    },\n'
    '    {\n      "iteration": 11,\n      "patch": "state/iter-11/ABORTED_IMPLEMENTATION.patch",\n'
    '      "tester_report": "tester.md",\n      "open": true,\n      "flagged": true\n    }\n'
    '  ],\n  "open_count": 2,\n  "superseded_count": 1,\n  "exit_code": 1\n}\n'
)


@pytest.fixture
def unparked(tmp_path):
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-5", _candidate_files())
    _iter_dir(work, "iter-7", {"final.md": PUSHED})
    _iter_dir(work, "iter-9", _candidate_files())
    _iter_dir(work, "iter-11", _candidate_files(**{"RESUMABLE.md": "hand\n"}))
    return cfg_path, work


def test_b9_text_byte_identical(unparked):
    assert _run(unparked[0]) == (1, HEAD_TEXT, "")


def test_b9_json_byte_identical(unparked):
    assert _run(unparked[0], "--json") == (1, HEAD_JSON, "")


def test_b9_empty_state_unchanged(tmp_path):
    cfg_path, work = _write_cfg(tmp_path)
    (work / "state").mkdir(parents=True)
    rc, out, _ = _run(cfg_path)
    assert rc == 0
    assert "parked" not in out
    _, jout, _ = _run(cfg_path, "--json")
    assert "parked" not in jout


# --------------------------------------------------------------------------
# Behavior 10 -- duty-0a contract
# --------------------------------------------------------------------------
def test_b10_only_open_rows_parked_exits_zero(tmp_path):
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-3", _candidate_files(**{PARK: "a\n"}))
    _iter_dir(work, "iter-4", _candidate_files(**{PARK: "b\n"}))
    proc = _cli("resumable", "--config", str(cfg_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _lines(proc.stdout)[-1] == "resumable (demoprod): 0 open, 0 superseded, 2 parked"


def test_b10_pm_card_keys_on_exit_one():
    text = (REPO / "roles" / "pm.md").read_text()
    assert "Exit 1\n    means at least one OPEN row" in text or \
        "Exit 1 means at least one OPEN row" in " ".join(text.split())


# --------------------------------------------------------------------------
# Behavior 11 -- seams
# --------------------------------------------------------------------------
def test_b11_identity_seam_reopens(lone, monkeypatch):
    assert callable(foundry.apply_resumable_parks)
    monkeypatch.setattr(foundry, "apply_resumable_parks", lambda cfg, summary: summary)
    rc, out, _ = _run(lone[0])
    assert rc == 1
    assert _word(out, "iter-9") == "open"


def test_b11_seam_called_and_gather_once(lone, monkeypatch):
    calls = {"gather": 0, "park": 0}
    real_gather = foundry.gather_resumable
    real_park = foundry.apply_resumable_parks

    def g(*a, **k):
        calls["gather"] += 1
        return real_gather(*a, **k)

    def p(*a, **k):
        calls["park"] += 1
        return real_park(*a, **k)

    monkeypatch.setattr(foundry, "gather_resumable", g)
    monkeypatch.setattr(foundry, "apply_resumable_parks", p)
    for flags in ((), ("--json",), ("--write",)):
        calls.update(gather=0, park=0)
        rc, out, _ = _run(lone[0], *flags)
        assert rc == 0
        assert calls == {"gather": 1, "park": 1}, flags


def test_b11_row_defaults_keep_old_constructors():
    import dataclasses
    names = [f.name for f in dataclasses.fields(foundry.ResumableRow)]
    assert names[-2:] == ["parked", "park_reason"]
    defaults = {f.name: f.default for f in dataclasses.fields(foundry.ResumableRow)}
    assert defaults["parked"] is False and defaults["park_reason"] == ""


# --------------------------------------------------------------------------
# Behavior 12 -- README + imports
# --------------------------------------------------------------------------
def _readme_68():
    text = (REPO / "README.md").read_text()
    start = text.index("\n# 68. ")
    end = text.find("\n# ", start + 1)
    return text[start:] if end < 0 else text[start:end]


def test_b12_readme_names_parked():
    sec = _readme_68()
    assert "PARKED.md" in sec
    assert "`parked`" in sec or " parked " in sec
    low = sec.lower()
    assert "--write" in sec and "skip" in low
    assert "never writes `parked.md`" in low or "never writes parked.md" in low
    assert "delet" in low and "unpark" in low


def test_b12_imports():
    proc = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                          cwd=str(REPO), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
