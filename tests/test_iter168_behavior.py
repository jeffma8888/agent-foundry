"""Black-box behaviour tests for iter 168 -- `foundry rescues`: per-stage
accounting of agent-CLI hard kills split into RESCUED (the stage's output file
was already non-empty, so `run_stage` returned success) and LOST.

Under test (spec Feature): `attempt_kill_summary` (PURE, over injected records),
the read-only `gather_rescues` seam with its two module-level patchable knobs
`ATTEMPT_LOG_GLOB` / `ATTEMPT_KILL_TOKENS`, and the
`foundry rescues [--config C] [--limit N] [--json]` CLI verb.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-168 PM spec's Expected
Behaviors 1-13, the tests/ conventions (esp. tests/test_iter39_behavior.py, the
ledger-verb original, and tests/test_iter165_behavior.py, the `_thin_gather_cli`
mirror), and the product's OWN OBSERVABLE behaviour (calling the public
functions and `main()` against fixtures built in `tmp_path`, then reading return
codes, stdout and runtime signatures). `foundry.py`'s implementation TEXT was
NOT read, and neither were the engineer's notes, the reviewer's notes, nor
`git diff`.

Every fixture is built in `tmp_path`; nothing here asserts anything about the
ambient repo tree (spec Out of Scope: `products/*/state/` is gitignored, so the
fresh clone that post-release builds carries none of those logs).

AMBIGUITY NOTED (PM feedback, tested per the Feature statement rather than the
behavior-9 shorthand): behavior 9 says `produced=True iff the sibling <stage>.md`
exists and is non-empty, but the Feature paragraph defines RESCUED as "the
stage's output file was already non-empty, so `run_stage` returned success".
Those two readings disagree for stage labels whose output file is not
`<stage>.md` (e.g. a `fix-review` stage writing `fix_review.md`). The SEMANTIC
reading is the one asserted here, because it is the number the verb exists to
report; the convention case (`pm.md` for `pm`) is asserted too and holds under
both readings.
"""

from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402


# --------------------------------------------------------------------------
# helpers -- mirror tests/test_iter39_behavior.py (the ledger-verb original)
# --------------------------------------------------------------------------
KILL_STUB = "agent run failed: agent run timed out after 600s"  # the real 48-byte stub
NARRATION = "ordinary stage narration line, no kill token here\n" * 400


def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir; repo/work_root are TMP dirs so the
    real foundry repo and state are NEVER touched."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _cfg(tmp_path, **over):
    return foundry.load_config(str(_write_cfg(tmp_path, **over)))


def _iter_dir(cfg, iteration):
    d = pathlib.Path(cfg.state) / f"iter-{iteration:02d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _plant(cfg, iteration, stage, attempt=1, killed=True, out=None, out_name=None):
    """Plant `<stage>.attempt<N>.log` under iter-NN. `out` (when not None) writes
    the stage's output file -- `out=""` plants an EMPTY one. `out_name` overrides
    the file name for stages whose `run_stage` out_name is not `<stage>.md`."""
    d = _iter_dir(cfg, iteration)
    (d / f"{stage}.attempt{attempt}.log").write_text(KILL_STUB if killed else NARRATION)
    if out is not None:
        (d / (out_name or f"{stage}.md")).write_text(out)
    return d


def _rec(stage, iteration=1, attempt=1, killed=False, produced=True):
    """One injected record in the spec's tuple shape."""
    return (stage, iteration, attempt, killed, produced)


def _capture(fn, *args, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fn(*args, **kwargs)
    return code, buf.getvalue()


def _run_cli(argv):
    """Drive foundry.main capturing (rc, stdout, stderr) SEPARATELY: behavior 13
    constrains stdout alone in --json mode."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _snapshot(root):
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def _by_stage(summary):
    return {r.stage: r for r in summary.rows}


def _row_line(text, stage):
    hits = [ln for ln in text.splitlines() if f"[{stage}]" in ln]
    assert len(hits) == 1, f"expected exactly one rendered row for {stage!r}: {text!r}"
    return hits[0]


class FakeResult:
    """Stand-in summary for the delegation tests (behavior 13)."""

    def __init__(self, exit_code=0, text="FAKE-RENDER-SENTINEL", payload=None):
        self.exit_code = exit_code
        self._text = text
        self._payload = {"kind": "fake", "n": 3} if payload is None else payload
        self.render_calls = 0
        self.to_dict_calls = 0

    def render(self):
        self.render_calls += 1
        return self._text

    def to_dict(self):
        self.to_dict_calls += 1
        return self._payload


class RecordingGather:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


# ==========================================================================
# Behavior 1 -- injected records, frozen result, no mutation, no I/O
# ==========================================================================
def test_b01_summary_accepts_record_tuples_and_leaves_them_unmutated(tmp_path):
    records = [_rec("pm", killed=True, produced=True), _rec("pm", attempt=2)]
    before = [tuple(r) for r in records]
    s = foundry.attempt_kill_summary(product="p", records=tuple(records))
    assert s.product == "p"
    assert [tuple(r) for r in records] == before, "input records must not be mutated"


def test_b01_summary_and_rows_reject_attribute_assignment(tmp_path):
    s = foundry.attempt_kill_summary(product="p", records=(_rec("pm", killed=True),))
    for target, attr in ((s, "attempts"), (s.rows[0], "stage")):
        with pytest.raises(Exception) as exc:
            setattr(target, attr, "mutated")
        assert isinstance(exc.value, (AttributeError, TypeError)), exc.value
    assert isinstance(s.rows, tuple), f"rows must be an immutable tuple, got {type(s.rows)}"


def test_b01_pure_function_touches_no_filesystem(tmp_path, monkeypatch):
    """Acceptance criterion: no filesystem/subprocess/git/network in the body."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sentinel.txt").write_text("keep")
    before = _snapshot(tmp_path)
    s = foundry.attempt_kill_summary(
        product="p", records=(_rec("pm", killed=True), _rec("eng", killed=True, produced=False)))
    s.render()
    json.dumps(s.to_dict())
    assert _snapshot(tmp_path) == before, "pure summary must write nothing"


# ==========================================================================
# Behavior 2 -- one row per stage; kills == rescued + lost
# ==========================================================================
def test_b02_per_stage_counts_and_kills_equal_rescued_plus_lost():
    records = (
        _rec("pm", 1, 1, killed=True, produced=True),    # rescued kill
        _rec("pm", 1, 2, killed=True, produced=False),   # lost kill
        _rec("pm", 2, 1, killed=False, produced=True),   # ordinary attempt
        _rec("eng", 1, 1, killed=True, produced=True),   # rescued kill
        _rec("quiet", 1, 1, killed=False, produced=True),
    )
    s = foundry.attempt_kill_summary(product="p", records=records)
    rows = _by_stage(s)
    assert set(rows) == {"pm", "eng", "quiet"}, "exactly one row per distinct stage"
    assert (rows["pm"].attempts, rows["pm"].kills, rows["pm"].rescued, rows["pm"].lost) == (3, 2, 1, 1)
    assert (rows["eng"].attempts, rows["eng"].kills, rows["eng"].rescued, rows["eng"].lost) == (1, 1, 1, 0)
    assert (rows["quiet"].attempts, rows["quiet"].kills, rows["quiet"].rescued,
            rows["quiet"].lost) == (1, 0, 0, 0)
    for r in s.rows:
        assert r.kills == r.rescued + r.lost, f"{r.stage}: kills != rescued + lost"


def test_b02_a_not_killed_attempt_never_counts_as_rescued_or_lost():
    """produced=False WITHOUT a kill is not a loss -- only killed rows split."""
    s = foundry.attempt_kill_summary(
        product="p", records=(_rec("pm", killed=False, produced=False),))
    r = s.rows[0]
    assert (r.attempts, r.kills, r.rescued, r.lost) == (1, 0, 0, 0), (r.attempts, r.kills)
    assert s.lost == 0 and s.exit_code == 0


# ==========================================================================
# Behavior 3 -- kills DESC, ties broken by stage name ASC
# ==========================================================================
def test_b03_rows_sort_by_kills_desc_then_stage_asc():
    records = (
        _rec("bravo", 1, 1, killed=True), _rec("bravo", 1, 2, killed=True),
        _rec("alpha", 1, 1, killed=True), _rec("alpha", 1, 2, killed=True),
        _rec("charlie", 1, 1, killed=True), _rec("charlie", 1, 2, killed=True),
        _rec("charlie", 1, 3, killed=True),
        _rec("zulu", 1, 1, killed=False),
    )
    s = foundry.attempt_kill_summary(product="p", records=records)
    assert [(r.stage, r.kills) for r in s.rows] == [
        ("charlie", 3), ("alpha", 2), ("bravo", 2), ("zulu", 0)], [r.stage for r in s.rows]
    text = s.render()
    positions = [text.index(f"[{st}]") for st in ("charlie", "alpha", "bravo", "zulu")]
    assert positions == sorted(positions), f"render must follow row order:\n{text}"


# ==========================================================================
# Behavior 4 -- rescue_rate rounding, None when kills == 0, n/a vs JSON null
# ==========================================================================
@pytest.mark.parametrize("rescued,lost,want", [(1, 2, 33.3), (2, 1, 66.7), (1, 0, 100.0),
                                               (0, 1, 0.0), (1, 1, 50.0)])
def test_b04_rescue_rate_is_percent_rounded_to_one_decimal(rescued, lost, want):
    records = tuple([_rec("s", 1, i, killed=True, produced=True) for i in range(rescued)]
                    + [_rec("s", 1, 50 + i, killed=True, produced=False) for i in range(lost)])
    row = foundry.attempt_kill_summary(product="p", records=records).rows[0]
    assert row.rescue_rate == want, f"{rescued}/{rescued + lost} -> {row.rescue_rate}, want {want}"
    assert round(row.rescue_rate, 1) == row.rescue_rate, "rate must be rounded to 1dp"


def test_b04_zero_kill_row_rate_is_none_renders_na_and_json_null():
    s = foundry.attempt_kill_summary(product="p", records=(_rec("quiet", killed=False),))
    row = s.rows[0]
    assert row.rescue_rate is None, f"kills == 0 must give None, got {row.rescue_rate!r}"
    assert "n/a" in _row_line(s.render(), "quiet"), s.render()
    payload = json.loads(json.dumps(s.to_dict()))
    assert payload["rows"][0]["rescue_rate"] is None, payload["rows"][0]
    assert '"rescue_rate": null' in json.dumps(s.to_dict(), indent=2)


# ==========================================================================
# Behavior 5 -- product-wide totals are the sums of the rows
# ==========================================================================
def test_b05_totals_equal_the_sum_of_rows():
    records = (
        _rec("pm", 1, 1, killed=True, produced=True),
        _rec("pm", 1, 2, killed=True, produced=False),
        _rec("eng", 1, 1, killed=True, produced=True),
        _rec("eng", 2, 1, killed=False, produced=True),
        _rec("tester", 3, 1, killed=False, produced=False),
    )
    s = foundry.attempt_kill_summary(product="p", records=records)
    for field in ("attempts", "kills", "rescued", "lost"):
        assert getattr(s, field) == sum(getattr(r, field) for r in s.rows), field
    assert (s.attempts, s.kills, s.rescued, s.lost) == (5, 3, 2, 1)
    assert s.kills == s.rescued + s.lost


# ==========================================================================
# Behavior 6 -- exit_code mirrors the weak-tests / skipped-tests contract
# ==========================================================================
def test_b06_exit_code_2_when_there_were_no_attempts_at_all():
    assert foundry.attempt_kill_summary(product="p", records=()).exit_code == 2


def test_b06_exit_code_1_when_any_attempt_was_lost():
    s = foundry.attempt_kill_summary(product="p", records=(
        _rec("pm", killed=True, produced=True), _rec("eng", killed=True, produced=False)))
    assert s.lost == 1 and s.exit_code == 1, (s.lost, s.exit_code)


def test_b06_exit_code_0_when_every_kill_was_rescued():
    s = foundry.attempt_kill_summary(product="p", records=(
        _rec("pm", 1, 1, killed=True, produced=True),
        _rec("pm", 1, 2, killed=True, produced=True)))
    assert (s.kills, s.lost) == (2, 0)
    assert s.exit_code == 0, "a killed-but-RESCUED attempt is NOT a failure"


# ==========================================================================
# Behavior 7 -- render() text and to_dict() carry the same numbers
# ==========================================================================
def test_b07_render_names_product_and_every_number_per_row():
    records = (
        _rec("pm", 1, 1, killed=True, produced=True),
        _rec("pm", 1, 2, killed=True, produced=False),
        _rec("eng", 1, 1, killed=False, produced=True),
    )
    s = foundry.attempt_kill_summary(product="widgetco", records=records)
    text = s.render()
    assert "widgetco" in text, text
    assert len(text.splitlines()) > 1, "render must be multi-line"
    row = _by_stage(s)["pm"]
    assert (row.attempts, row.kills, row.rescued, row.lost) == (2, 2, 1, 1)
    pm = _row_line(text, "pm")
    for label, value in (("attempts", row.attempts), ("kills", row.kills),
                         ("rescued", row.rescued), ("lost", row.lost)):
        assert f"{label} {value}" in pm, f"{label} {value} missing from rendered row: {pm!r}"
    assert "50.0" in pm, f"rate missing from rendered pm row: {pm!r}"
    assert "[eng]" in text


def test_b07_to_dict_is_json_serialisable_and_agrees_with_the_objects():
    records = (
        _rec("pm", 1, 1, killed=True, produced=True),
        _rec("pm", 1, 2, killed=True, produced=False),
        _rec("eng", 1, 1, killed=True, produced=True),
    )
    s = foundry.attempt_kill_summary(product="widgetco", records=records)
    payload = json.loads(json.dumps(s.to_dict()))       # must not raise
    assert payload["product"] == "widgetco"
    for field in ("attempts", "kills", "rescued", "lost"):
        assert payload[field] == getattr(s, field), field
    assert len(payload["rows"]) == len(s.rows)
    for got, row in zip(payload["rows"], s.rows):
        assert got["stage"] == row.stage
        for field in ("attempts", "kills", "rescued", "lost", "rescue_rate"):
            assert got[field] == getattr(row, field), (row.stage, field)


# ==========================================================================
# Behavior 8 -- the empty case degrades, it does not raise
# ==========================================================================
def test_b08_no_records_gives_zero_rows_zero_totals_exit_2_and_a_message():
    s = foundry.attempt_kill_summary(product="p", records=())
    assert s.rows == ()
    assert (s.attempts, s.kills, s.rescued, s.lost) == (0, 0, 0, 0)
    assert s.exit_code == 2
    text = s.render()                                    # must not raise
    assert "no attempts" in text.lower(), text
    assert "p" in text
    json.dumps(s.to_dict())


# ==========================================================================
# Behavior 9 -- the read-only gather seam over a tmp_path state tree
# ==========================================================================
def test_b09_gather_derives_stage_and_splits_rescued_from_lost(tmp_path):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", killed=True, out="spec text")        # rescued: non-empty pm.md
    _plant(cfg, 1, "engineer", killed=True, out="")           # lost: EMPTY engineer.md
    _plant(cfg, 2, "tester", killed=True)                     # lost: no output file at all
    s = foundry.gather_rescues(cfg)
    assert s.product == cfg.name
    rows = _by_stage(s)
    assert set(rows) == {"pm", "engineer", "tester"}, sorted(rows)
    assert (rows["pm"].kills, rows["pm"].rescued, rows["pm"].lost) == (1, 1, 0)
    assert (rows["engineer"].kills, rows["engineer"].rescued, rows["engineer"].lost) == (1, 0, 1), \
        "an EMPTY sibling output file is NOT a rescue"
    assert (rows["tester"].kills, rows["tester"].rescued, rows["tester"].lost) == (1, 0, 1), \
        "a missing sibling output file is NOT a rescue"
    assert (s.attempts, s.kills, s.rescued, s.lost) == (3, 3, 1, 2)
    assert s.exit_code == 1


def test_b09_gather_counts_each_attempt_file_of_the_same_stage(tmp_path):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", attempt=1, killed=True)
    _plant(cfg, 1, "pm", attempt=2, killed=True, out="spec")
    _plant(cfg, 1, "pm", attempt=3, killed=False)
    row = _by_stage(foundry.gather_rescues(cfg))["pm"]
    assert (row.attempts, row.kills) == (3, 2), (row.attempts, row.kills)
    # attempt 2 produced the output file, so both kills read as rescued (same dir)
    assert row.rescued + row.lost == row.kills


def test_b09_produced_follows_the_stage_output_file_even_when_it_is_renamed(tmp_path):
    """Feature statement: RESCUED == the stage's output file was already
    non-empty. A `fix-review` stage writes `fix_review.md`, so the row must read
    RESCUED (behavior 9's `<stage>.md` shorthand does not cover it -- see the
    module docstring's ambiguity note)."""
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "fix-review", killed=True, out="review notes", out_name="fix_review.md")
    row = _by_stage(foundry.gather_rescues(cfg))["fix-review"]
    assert (row.kills, row.rescued, row.lost) == (1, 1, 0), \
        "a renamed-output stage that DID write its file must count as rescued, not lost"


def test_b09_attempt_log_glob_is_module_level_and_patchable(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", killed=True, out="spec")
    assert foundry.ATTEMPT_LOG_GLOB == "iter-*/*.attempt*.log", foundry.ATTEMPT_LOG_GLOB
    assert foundry.gather_rescues(cfg).attempts == 1
    monkeypatch.setattr(foundry, "ATTEMPT_LOG_GLOB", "iter-*/*.nomatch.log")
    blind = foundry.gather_rescues(cfg)
    assert (blind.attempts, blind.rows, blind.exit_code) == (0, (), 2), \
        "the seam must read ATTEMPT_LOG_GLOB from module globals at CALL time"


def test_b09_limit_keeps_only_the_newest_iteration_dirs(tmp_path):
    cfg = _cfg(tmp_path)
    for n, stage in ((1, "oldest"), (2, "middle"), (3, "newest")):
        _plant(cfg, n, stage, killed=True, out="x")
    assert set(_by_stage(foundry.gather_rescues(cfg))) == {"oldest", "middle", "newest"}
    assert set(_by_stage(foundry.gather_rescues(cfg, 1))) == {"newest"}
    assert set(_by_stage(foundry.gather_rescues(cfg, 2))) == {"middle", "newest"}
    assert set(_by_stage(foundry.gather_rescues(cfg, limit=None))) == {"oldest", "middle", "newest"}
    for lim in (3, 5, 99):
        assert foundry.gather_rescues(cfg, lim).attempts == 3, f"limit {lim} over-trimmed"


def test_b09_gather_writes_nothing(tmp_path):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", killed=True, out="spec")
    _plant(cfg, 2, "tester", killed=False)
    before = _snapshot(tmp_path)
    foundry.gather_rescues(cfg)
    foundry.gather_rescues(cfg, 1)
    assert _snapshot(tmp_path) == before, "the gather seam is read-only"


def test_b09_missing_state_dir_degrades_to_the_empty_summary(tmp_path):
    cfg = _cfg(tmp_path)                                  # state dir never created
    s = foundry.gather_rescues(cfg)                       # must not raise
    assert (s.attempts, s.rows, s.exit_code) == (0, (), 2)


# ==========================================================================
# Behavior 10 -- kill detection is two-sided against planted logs
# ==========================================================================
def test_b10_kill_token_detection_is_two_sided(tmp_path):
    cfg = _cfg(tmp_path)
    stub = _iter_dir(cfg, 1) / "pm.attempt1.log"
    stub.write_text(KILL_STUB)                            # the real ~48-byte kill stub
    assert len(stub.read_bytes()) <= 60, "fixture must be the tiny kill stub"
    (_iter_dir(cfg, 1) / "tester.attempt1.log").write_text(NARRATION)
    assert len(NARRATION) > 2000, "fixture must be a multi-KB normal narration log"
    rows = _by_stage(foundry.gather_rescues(cfg))
    assert rows["pm"].kills == 1, "a log carrying the kill token reads killed=True"
    assert rows["tester"].kills == 0, "a normal narration log reads killed=False"
    assert rows["tester"].attempts == 1, "a non-killed attempt is still an attempt"
    assert foundry.ATTEMPT_KILL_TOKENS == ("agent run timed out after",), \
        foundry.ATTEMPT_KILL_TOKENS


# ==========================================================================
# Behavior 11 -- ATTEMPT_KILL_TOKENS is honoured as data
# ==========================================================================
def test_b11_added_kill_token_flips_the_same_fixture_from_false_to_true(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    (_iter_dir(cfg, 1) / "eng.attempt1.log").write_text(
        "Connection stalled -- no data received for 120 s\n")
    assert _by_stage(foundry.gather_rescues(cfg))["eng"].kills == 0, \
        "baseline: the default token set must not match this log"
    monkeypatch.setattr(foundry, "ATTEMPT_KILL_TOKENS",
                        tuple(foundry.ATTEMPT_KILL_TOKENS) + ("Connection stalled",))
    row = _by_stage(foundry.gather_rescues(cfg))["eng"]
    assert row.kills == 1, "an added token must be honoured as data, not hard-coded"
    assert row.lost == 1 and foundry.gather_rescues(cfg).exit_code == 1


# ==========================================================================
# Behavior 12 -- a malformed tree never raises
# ==========================================================================
def test_b12_filenames_not_matching_the_attempt_shape_are_skipped(tmp_path):
    cfg = _cfg(tmp_path)
    d = _iter_dir(cfg, 1)
    (d / "garbage.log").write_text(KILL_STUB)             # no `.attemptN`
    (d / "weird.attemptX.log").write_text(KILL_STUB)      # non-numeric attempt
    (d / "pm.md").write_text("spec")
    _plant(cfg, 1, "pm", killed=True, out="spec")
    s = foundry.gather_rescues(cfg)                       # must not raise
    assert set(_by_stage(s)) == {"pm"}, sorted(_by_stage(s))
    assert s.attempts == 1, f"malformed names must be skipped, got {s.attempts} attempts"


def test_b12_undecodable_log_counts_as_an_attempt_with_killed_false(tmp_path):
    cfg = _cfg(tmp_path)
    (_iter_dir(cfg, 1) / "bad.attempt1.log").write_bytes(
        b"\xff\xfe\x00 agent run timed out after 600s")
    s = foundry.gather_rescues(cfg)                       # must not raise
    row = _by_stage(s)["bad"]
    assert (row.attempts, row.kills) == (1, 0), \
        "an undecodable log is an attempt with killed=False (absence of evidence)"
    assert s.attempts == 1, "the denominator must still count the row"


def test_b12_unreadable_log_and_directory_shaped_log_never_raise(tmp_path):
    cfg = _cfg(tmp_path)
    d = _iter_dir(cfg, 1)
    (d / "dirlog.attempt1.log").mkdir()                   # a DIRECTORY where a log is expected
    locked = d / "locked.attempt1.log"
    locked.write_text(KILL_STUB)
    os.chmod(locked, 0o000)
    try:
        s = foundry.gather_rescues(cfg)                   # must not raise
        rows = _by_stage(s)
        assert set(rows) == {"dirlog", "locked"}, sorted(rows)
        for stage in ("dirlog", "locked"):
            assert (rows[stage].attempts, rows[stage].kills) == (1, 0), stage
    finally:
        os.chmod(locked, 0o600)


# ==========================================================================
# Behavior 13 -- the CLI verb
# ==========================================================================
def test_b13_rescues_cli_signature_mirrors_the_ledger_verbs():
    assert inspect.isfunction(foundry.rescues_cli)
    assert tuple(inspect.signature(foundry.rescues_cli).parameters) == ("cfg", "limit", "as_json")


def test_b13_human_mode_prints_render_and_returns_exit_code(tmp_path):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", killed=True, out="spec")
    _plant(cfg, 1, "tester", killed=True)                 # a LOST attempt -> exit 1
    expected = foundry.gather_rescues(cfg)
    rc, out = _capture(foundry.rescues_cli, cfg, None, False)
    assert out == expected.render() + "\n", repr(out)
    assert rc == expected.exit_code == 1, (rc, expected.exit_code)


def test_b13_json_mode_stdout_is_exactly_one_indent_two_document(tmp_path):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", killed=True, out="spec")
    expected = foundry.gather_rescues(cfg)
    rc, out = _capture(foundry.rescues_cli, cfg, None, True)
    assert out == json.dumps(expected.to_dict(), indent=2) + "\n", repr(out[:400])
    assert json.loads(out) == expected.to_dict(), "stdout must be ONE parseable document"
    assert rc == expected.exit_code


def test_b13_cli_resolves_the_gather_seam_from_module_globals(tmp_path, monkeypatch):
    """The verb body is `_thin_gather_cli(gather_rescues, cfg, limit, as_json)`
    called by BARE module name, so patching the seam must take effect."""
    fake = FakeResult(exit_code=7, text="FAKE-RENDER-SENTINEL",
                      payload={"fake": True, "rows": []})
    rec = RecordingGather(fake)
    monkeypatch.setattr(foundry, "gather_rescues", rec)
    cfg = _cfg(tmp_path)
    rc, out = _capture(foundry.rescues_cli, cfg, 5, False)
    assert rc == 7, "the verb must return the summary's own exit_code"
    assert out == "FAKE-RENDER-SENTINEL\n", repr(out)
    assert len(rec.calls) == 1, rec.calls
    args, kwargs = rec.calls[0]
    assert kwargs == {} and len(args) == 2, (args, kwargs)
    assert args[0] is cfg and args[1] == 5, args
    assert fake.to_dict_calls == 0, "human mode must not call to_dict()"
    rc, out = _capture(foundry.rescues_cli, cfg, None, True)
    assert rc == 7 and json.loads(out) == {"fake": True, "rows": []}, repr(out)
    assert fake.render_calls == 1, "json mode must not call render() again"


def test_b13_main_dispatches_the_registered_verb(tmp_path, monkeypatch):
    """A verb can be REGISTERED with argparse and never dispatched -- then it
    silently does nothing while imports and the suite stay green."""
    fake = FakeResult(exit_code=7, text="DISPATCH-SENTINEL", payload={"ok": 1})
    rec = RecordingGather(fake)
    monkeypatch.setattr(foundry, "gather_rescues", rec)
    cfg_path = _write_cfg(tmp_path)
    rc, out, _ = _run_cli(["rescues", "--config", str(cfg_path)])
    assert rc == 7, f"main() must return the verb's exit code, got {rc}"
    assert "DISPATCH-SENTINEL" in out, repr(out)
    assert len(rec.calls) == 1, "main() must actually call the verb"
    assert rec.calls[0][0][1] is None, f"default --limit must be None, got {rec.calls[0][0][1]!r}"


def test_b13_main_passes_limit_through_and_json_mode_is_pure_json(tmp_path, monkeypatch):
    fake = FakeResult(exit_code=0, payload={"product": "x", "rows": []})
    rec = RecordingGather(fake)
    monkeypatch.setattr(foundry, "gather_rescues", rec)
    cfg_path = _write_cfg(tmp_path)
    rc, out, _ = _run_cli(["rescues", "--config", str(cfg_path), "--limit", "3", "--json"])
    assert rc == 0
    assert rec.calls[0][0][1] == 3, f"--limit must reach the seam, got {rec.calls[0][0][1]!r}"
    assert json.loads(out) == {"product": "x", "rows": []}, repr(out)
    assert out == json.dumps({"product": "x", "rows": []}, indent=2) + "\n", repr(out)


def test_b13_verb_is_read_only_end_to_end(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _plant(cfg, 1, "pm", killed=True, out="spec")
    _plant(cfg, 2, "tester", killed=True)
    before = _snapshot(tmp_path)
    for argv in (["rescues", "--config", str(cfg_path)],
                 ["rescues", "--config", str(cfg_path), "--json"],
                 ["rescues", "--config", str(cfg_path), "--limit", "1"]):
        rc, out, _ = _run_cli(argv)
        assert rc == 1, (argv, rc)
        assert out.strip(), f"{argv} produced no stdout"
    assert _snapshot(tmp_path) == before, "the verb must write nothing"


def test_b13_empty_state_dir_exits_2_through_the_cli(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    rc, out, _ = _run_cli(["rescues", "--config", str(cfg_path)])
    assert rc == 2, f"nothing to scan must exit 2, got {rc}"
    assert "no attempts" in out.lower(), repr(out)
