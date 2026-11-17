"""Black-box behaviour tests for iter 540 -- `foundry resumable`: list every
iteration whose approved + tested tree was reverted without a ship decision,
classify it OPEN / SUPERSEDED, and (with --write) drop RESUMABLE.md flags.

ISOLATION CONTRACT (honored): written solely from the iter-540 PM spec's
Expected Behaviors (1-11), the README, the conventions under `tests/` and the
product's OBSERVABLE runtime interface (public names, `--help`, CLI output).
The implementation source, the engineer's/reviewer's notes and `git diff`
were not read.

Fully offline: every config and state dir is built under tmp_path; no ambient
products/*/state path is asserted (state/ is gitignored, absent in a clone).
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
CHANGES = "Review notes.\n\nVERDICT: CHANGES_REQUIRED\n"
QUOTED_APPROVE = "I would write VERDICT: APPROVE if it were fine.\nMore prose after it.\n"
PASS = "Tests ok.\n\nRESULT: PASS\n"
FAIL = "Tests red.\n\nRESULT: FAIL\n"


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
    return sorted((str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns)
                  for p in root.rglob("*"))


def _last_line(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


@pytest.fixture
def mixed(tmp_path):
    """Spec Behavior 3 tree: iter-5 superseded by iter-7 PUSHED, iter-9 open."""
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-5", _candidate_files())
    _iter_dir(work, "iter-7", {"final.md": "Shipped.\n\nACTION: PUSHED abc123\n"})
    _iter_dir(work, "iter-9", _candidate_files())
    return cfg_path, work


# --------------------------------------------------------------------------
# Behavior 1 -- pure predicate resumable_candidate
# --------------------------------------------------------------------------
GOOD_NAMES = ["reviewer.md", PATCH, "tester.md"]


def test_b1_candidate_true_when_all_hold():
    assert foundry.resumable_candidate(GOOD_NAMES, "APPROVE", "PASS", None) is True


def test_b1_candidate_accepts_any_iterable():
    assert foundry.resumable_candidate(set(GOOD_NAMES), "APPROVE", "PASS", None) is True
    assert foundry.resumable_candidate(tuple(GOOD_NAMES), "APPROVE", "PASS", None) is True


@pytest.mark.parametrize("names,review,test,final", [
    (["reviewer.md", "tester.md"], "APPROVE", "PASS", None),          # no patch
    (["IMPLEMENTATION.patch"], "APPROVE", "PASS", None),              # wrong patch name
    (GOOD_NAMES, "CHANGES_REQUIRED", "PASS", None),
    (GOOD_NAMES, None, "PASS", None),
    (GOOD_NAMES, "approve", "PASS", None),
    (GOOD_NAMES, "APPROVE", "FAIL", None),
    (GOOD_NAMES, "APPROVE", "BLOCKED", None),
    (GOOD_NAMES, "APPROVE", None, None),
    (GOOD_NAMES, "APPROVE", "PASS", "PUSHED"),
    (GOOD_NAMES, "APPROVE", "PASS", "REVERTED"),
    (None, "APPROVE", "PASS", None),
    ([], "APPROVE", "PASS", None),
    (iter(()), "APPROVE", "PASS", None),
    (None, None, None, None),
])
def test_b1_candidate_false_otherwise(names, review, test, final):
    assert foundry.resumable_candidate(names, review, test, final) is False


# --------------------------------------------------------------------------
# Behavior 2 -- pure resumable_open
# --------------------------------------------------------------------------
@pytest.mark.parametrize("iteration,pushed,expected", [
    (5, [7], False),
    (5, [3, 7], False),
    (5, (6,), False),
    (5, [5], True),          # same iteration does not supersede itself
    (5, [1, 2, 4], True),
    (5, [], True),
    (5, None, True),
    (9, {7, 5}, True),
])
def test_b2_open(iteration, pushed, expected):
    assert foundry.resumable_open(iteration, pushed) is expected


# --------------------------------------------------------------------------
# Behavior 3 -- human report
# --------------------------------------------------------------------------
def test_b3_human_report(mixed):
    cfg_path, _ = mixed
    rc, out, _err = _run(cfg_path)
    assert rc == 1
    lines = out.splitlines()
    row5 = [ln for ln in lines if "state/iter-5/ABORTED_IMPLEMENTATION.patch" in ln]
    row9 = [ln for ln in lines if "state/iter-9/ABORTED_IMPLEMENTATION.patch" in ln]
    assert len(row5) == 1 and len(row9) == 1
    assert "iter-5" in row5[0] and "superseded" in row5[0].lower()
    assert "iter-9" in row9[0] and "open" in row9[0].lower()
    assert "superseded" not in row9[0].lower()
    assert not any("iter-7" in ln for ln in lines)
    last = _last_line(out)
    assert "1 open" in last and "1 superseded" in last


# --------------------------------------------------------------------------
# Behavior 4 -- not candidates
# --------------------------------------------------------------------------
NON_CANDIDATES = {
    "iter-1": {"reviewer.md": APPROVE, "tester.md": PASS},
    "iter-2": _candidate_files(**{"reviewer.md": CHANGES}),
    "iter-3": _candidate_files(**{"reviewer.md": QUOTED_APPROVE}),
    "iter-4": _candidate_files(**{"tester2.md": FAIL}),
    "iter-6": _candidate_files(**{"final.md": "Reverted.\n\nACTION: REVERTED\n"}),
    "iter-8": _candidate_files(**{"final.md": "Shipped.\n\nACTION: PUSHED deadbeef\n"}),
    "iter-x": _candidate_files(),
    "scratch": _candidate_files(),
}


@pytest.mark.parametrize("dirname", sorted(NON_CANDIDATES))
def test_b4_each_non_candidate_alone(tmp_path, dirname):
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, dirname, NON_CANDIDATES[dirname])
    rc, out, _ = _run(cfg_path)
    assert rc == 0, out
    assert "ABORTED_IMPLEMENTATION.patch" not in out
    assert "0 open" in _last_line(out)
    rc, out, _ = _run(cfg_path, "--json")
    assert rc == 0
    assert json.loads(out)["rows"] == []


def test_b4_all_non_candidates_together(tmp_path):
    cfg_path, work = _write_cfg(tmp_path)
    for name, files in NON_CANDIDATES.items():
        _iter_dir(work, name, files)
    rc, out, _ = _run(cfg_path, "--json")
    doc = json.loads(out)
    assert rc == 0 and doc["exit_code"] == 0
    assert doc["rows"] == []
    assert doc["open_count"] == 0


# --------------------------------------------------------------------------
# Behavior 5 -- authoritative tester round
# --------------------------------------------------------------------------
def test_b5_tester2_pass_beats_tester_fail(tmp_path):
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-12", _candidate_files(**{"tester.md": FAIL, "tester2.md": PASS}))
    rc, out, _ = _run(cfg_path)
    assert rc == 1
    row = [ln for ln in out.splitlines() if "state/iter-12/" in ln]
    assert len(row) == 1 and "tester2.md" in row[0]
    rc, out, _ = _run(cfg_path, "--json")
    doc = json.loads(out)
    assert [r["iteration"] for r in doc["rows"]] == [12]
    assert doc["rows"][0]["tester_report"] == "tester2.md"


def test_b5_plain_tester_report_named(tmp_path):
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-12", _candidate_files())
    rc, out, _ = _run(cfg_path, "--json")
    assert json.loads(out)["rows"][0]["tester_report"] == "tester.md"


# --------------------------------------------------------------------------
# Behavior 6 -- unfinished final gate
# --------------------------------------------------------------------------
@pytest.mark.parametrize("final_text", [
    "Final gate notes, still verifying.\n",
    "VERIFIED: suite=green key=abc+def\nVERDICT: something\n",
    "",
])
def test_b6_final_without_action_is_candidate(tmp_path, final_text):
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-20", _candidate_files(**{"final.md": final_text}))
    rc, out, _ = _run(cfg_path, "--json")
    doc = json.loads(out)
    assert rc == 1
    assert [r["iteration"] for r in doc["rows"]] == [20]
    assert doc["rows"][0]["open"] is True


# --------------------------------------------------------------------------
# Behavior 7 -- exit codes
# --------------------------------------------------------------------------
def test_b7_empty_state_exit_0_with_summary(tmp_path):
    cfg_path, work = _write_cfg(tmp_path)
    (work / "state").mkdir(parents=True)
    rc, out, _ = _run(cfg_path)
    assert rc == 0
    assert "0 open" in _last_line(out)


def test_b7_only_superseded_exit_0(tmp_path):
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-3", _candidate_files())
    _iter_dir(work, "iter-4", {"final.md": "ACTION: PUSHED 1234567\n"})
    rc, out, _ = _run(cfg_path)
    assert rc == 0
    last = _last_line(out)
    assert "0 open" in last and "1 superseded" in last


def test_b7_open_exit_1(mixed):
    rc, _, _ = _run(mixed[0])
    assert rc == 1


def test_b7_missing_state_exit_2_nothing_created(tmp_path):
    cfg_path, work = _write_cfg(tmp_path)
    assert not work.exists()
    proc = _cli("resumable", "--config", str(cfg_path))
    assert proc.returncode == 2
    assert "Traceback" not in proc.stdout + proc.stderr
    assert not work.exists()
    proc = _cli("resumable", "--config", str(cfg_path), "--write")
    assert proc.returncode == 2
    assert "Traceback" not in proc.stdout + proc.stderr
    assert not work.exists()


def test_b7_state_is_a_file_exit_2(tmp_path):
    cfg_path, work = _write_cfg(tmp_path)
    work.mkdir(parents=True)
    (work / "state").write_text("not a dir")
    before = _snapshot(work)
    proc = _cli("resumable", "--config", str(cfg_path), "--write")
    assert proc.returncode == 2
    assert "Traceback" not in proc.stdout + proc.stderr
    assert _snapshot(work) == before


# --------------------------------------------------------------------------
# Behavior 8 -- JSON
# --------------------------------------------------------------------------
def test_b8_json_document(mixed):
    cfg_path, _ = mixed
    rc, out, _ = _run(cfg_path, "--json")
    doc = json.loads(out)
    assert rc == 1 and doc["exit_code"] == 1
    for key in ("product", "rows", "open_count", "superseded_count", "exit_code"):
        assert key in doc
    assert doc["product"] == "demoprod"
    assert doc["open_count"] == 1 and doc["superseded_count"] == 1
    iters = [r["iteration"] for r in doc["rows"]]
    assert iters == [5, 9]
    for r in doc["rows"]:
        assert isinstance(r["iteration"], int)
        assert r["patch"] == f"state/iter-{r['iteration']}/ABORTED_IMPLEMENTATION.patch"
        assert r["tester_report"] == "tester.md"
        assert isinstance(r["open"], bool) and isinstance(r["flagged"], bool)
        assert r["flagged"] is False
    assert doc["rows"][0]["open"] is False and doc["rows"][1]["open"] is True


def test_b8_json_sorted_numerically_not_lexically(tmp_path):
    cfg_path, work = _write_cfg(tmp_path)
    for n in (100, 9, 23):
        _iter_dir(work, f"iter-{n}", _candidate_files())
    rc, out, _ = _run(cfg_path, "--json")
    assert [r["iteration"] for r in json.loads(out)["rows"]] == [9, 23, 100]


def test_b8_json_flagged_true_when_resumable_exists(tmp_path):
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-9", _candidate_files(**{"RESUMABLE.md": "hand-written\n"}))
    rc, out, _ = _run(cfg_path, "--json")
    assert json.loads(out)["rows"][0]["flagged"] is True


def test_b8_json_via_subprocess_exactly_one_document(mixed):
    proc = _cli("resumable", "--config", str(mixed[0]), "--json")
    assert proc.returncode == 1
    doc = json.loads(proc.stdout)  # raises if more than one document
    assert doc["exit_code"] == 1


# --------------------------------------------------------------------------
# Behavior 9 -- read-only by default
# --------------------------------------------------------------------------
def test_b9_read_only(mixed):
    cfg_path, work = mixed
    before = _snapshot(work)
    _run(cfg_path)
    _run(cfg_path, "--json")
    assert _snapshot(work) == before
    assert not list(work.rglob("RESUMABLE.md"))


# --------------------------------------------------------------------------
# Behavior 10 -- --write
# --------------------------------------------------------------------------
def test_b10_write_open_only(mixed):
    cfg_path, work = mixed
    rc_plain, _, _ = _run(cfg_path)
    rc, out, _ = _run(cfg_path, "--write")
    assert rc == rc_plain == 1
    assert "wrote state/iter-9/RESUMABLE.md" in out
    assert "iter-5/RESUMABLE.md" not in out
    assert (work / "state" / "iter-9" / "RESUMABLE.md").is_file()
    assert not (work / "state" / "iter-5" / "RESUMABLE.md").exists()
    assert not (work / "state" / "iter-7" / "RESUMABLE.md").exists()


def test_b10_written_content(mixed):
    cfg_path, work = mixed
    _run(cfg_path, "--write")
    text = (work / "state" / "iter-9" / "RESUMABLE.md").read_text()
    lines = [ln.strip() for ln in text.splitlines()]
    assert "patch: state/iter-9/ABORTED_IMPLEMENTATION.patch" in lines
    assert "review: VERDICT: APPROVE" in lines
    assert "tester: tester.md RESULT: PASS" in lines
    excl = [ln for ln in lines if ln.startswith("exclude:")]
    assert excl and "DIRECTIONS.md" in excl[0] and "roadmap" in excl[0].lower()
    assert _last_line(text) == "RESUMABLE: iter-9"
    assert str(work) not in text
    assert str(work.resolve()) not in text


def test_b10_written_content_names_tester2(tmp_path):
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-31", _candidate_files(**{"tester.md": FAIL, "tester2.md": PASS}))
    _run(cfg_path, "--write")
    text = (work / "state" / "iter-31" / "RESUMABLE.md").read_text()
    assert "tester: tester2.md RESULT: PASS" in [ln.strip() for ln in text.splitlines()]
    assert _last_line(text) == "RESUMABLE: iter-31"


def test_b10_never_overwrites(tmp_path):
    cfg_path, work = _write_cfg(tmp_path)
    d = _iter_dir(work, "iter-9", _candidate_files(**{"RESUMABLE.md": "operator pin\n"}))
    rc, out, _ = _run(cfg_path, "--write")
    assert rc == 1
    assert (d / "RESUMABLE.md").read_bytes() == b"operator pin\n"
    assert "wrote" not in out


def test_b10_second_write_is_noop(mixed):
    cfg_path, work = mixed
    _run(cfg_path, "--write")
    before = _snapshot(work)
    rc, out, _ = _run(cfg_path, "--write")
    assert rc == 1
    assert "wrote" not in out
    assert _snapshot(work) == before
    rc, out, _ = _run(cfg_path, "--json")
    rows = json.loads(out)["rows"]
    assert {r["iteration"]: r["flagged"] for r in rows} == {5: False, 9: True}


def test_b10_write_with_no_open_exit_0_writes_nothing(tmp_path):
    cfg_path, work = _write_cfg(tmp_path)
    _iter_dir(work, "iter-3", _candidate_files())
    _iter_dir(work, "iter-4", {"final.md": "ACTION: PUSHED 1234567\n"})
    before = _snapshot(work)
    rc, out, _ = _run(cfg_path, "--write")
    assert rc == 0
    assert _snapshot(work) == before


# --------------------------------------------------------------------------
# Behavior 11 -- help and wiring
# --------------------------------------------------------------------------
def test_b11_help():
    proc = _cli("resumable", "--help")
    assert proc.returncode == 0
    assert "--write" in proc.stdout and "--json" in proc.stdout


def test_b11_missing_config_exit_2():
    proc = _cli("resumable")
    assert proc.returncode == 2


def test_b11_readme_entry():
    text = (REPO / "README.md").read_text()
    entries = [ln for ln in text.splitlines() if ln.startswith("# ") and "resumable" in ln]
    assert len(entries) >= 1
    import re
    assert any(re.match(r"^# \d+\.", ln) for ln in entries)


def test_b11_seams_are_module_level():
    for name in ("resumable_candidate", "resumable_open", "gather_resumable",
                 "write_resumable_flag"):
        assert callable(getattr(foundry, name, None)), name


def test_b11_gather_seam_bites_via_monkeypatch(mixed, monkeypatch):
    cfg_path, _ = mixed
    calls = []
    real = foundry.gather_resumable

    def spy(*a, **k):
        calls.append(a)
        return real(*a, **k)

    monkeypatch.setattr(foundry, "gather_resumable", spy)
    rc, _, _ = _run(cfg_path, "--json")
    assert rc == 1
    assert len(calls) == 1


def test_b11_summary_shape(mixed):
    cfg_path, _ = mixed
    cfg = foundry.load_config(str(cfg_path))
    summary = foundry.gather_resumable(cfg)
    assert summary.exit_code == 1
    assert isinstance(summary.render(), str) and "1 open" in summary.render()
    d = summary.to_dict()
    assert d["open_count"] == 1 and d["superseded_count"] == 1
    with pytest.raises(Exception):
        summary.exit_code = 0  # frozen
