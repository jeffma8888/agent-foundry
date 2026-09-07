"""Iteration 240 -- BLACK-BOX behavior tests for `foundry inflight`: a dormant,
read-only verb that reports the PENDING stage attempt(s) the iteration-117 parser
family (`parse_stage_attempts`) discards by design, priced against the agent CLI's
~600s hard per-stage cap.

Spec under test: products/_platform/state/iter-240/pm.md, Expected Behaviors 1-6:

  1. `pending_stage_starts(text, now, *, cap=None)` decides WHICH starts are pending
     and is pure + total (never raises for any `str`).
  2. elapsed / headroom / stale arithmetic, with the cap READ AT CALL TIME and `now`
     taken as a `MM-DD HH:MM:SS` LOG-STAMP STRING (never a `dt.datetime`).
  3. Deterministic order (elapsed DESC, ties `(team, iteration, stage)` ASC) and a
     frozen, JSON-native `PendingStage`.
  4. `inflight_cli(log_path, *, now=None, as_json=False) -> int`: 0/1/2 exit contract
     over ONE `gather_pending_stages` seam called by BARE module name.
  5. The rendered report: per-row fields, the `STALE` token, the `INFLIGHT_PREFIX`
     anchor + effective cap, and a NON-EMPTY no-pending line.
  6. Registration (`inflight --help`, dispatched before `load_config`), DORMANCY (no
     call site in `run_iteration` / `run_stage` / `build_prompt` / `dispatcher.py`),
     and the README verb row.

ISOLATION CONTRACT (HONORED): written ONLY from that PM spec, the conventions already
established under `tests/` (the `dispatcher.out` line builders of
`tests/test_iter148_behavior.py` / `tests/test_iter234_behavior.py`), the product's
README (explicitly permitted), and the product's OWN OBSERVABLE surface -- importing
`foundry`, calling its public functions, `inspect`/`dataclasses` introspection of
declared signatures, code-object introspection for the dormancy proof, and running
`python3 foundry.py inflight --help` as a subprocess.  I did NOT read the
implementation source of `foundry.py`/`dispatcher.py`, nor `engineer.md`,
`reviewer.md`, nor any `git diff`.

Every log fixture below is a SYNTHETIC STRING built in-process, and every path is under
`tmp_path`: no reliance on the ambient (gitignored) `dispatcher.out`, no git, no
network, no subprocess except the one `--help` registration probe (OPERATOR 2026-08-11
-- a precondition true only in one working tree is not a precondition).
"""

import dataclasses
import inspect
import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

# The MIDDLE DOT (U+00B7) separator emitted by log(); built from its code point, never
# embedded, following tests/test_iter148_behavior.py and tests/test_iter234_behavior.py.
MID = "\u00b7"

TEAM = "_platform"
ITER = 240
FIELDS = ("team", "iteration", "stage", "attempt", "elapsed_s", "headroom_s", "stale")


# --------------------------------------------------------------------------
# fixture builders -- the EXACT dispatcher.out line shapes
# --------------------------------------------------------------------------
def _start(ts, stage, attempt=1, team=TEAM, it=ITER):
    return f"- `{ts}` [{team}] iter {it} {MID} **{stage}** attempt {attempt} started"


def _produced(ts, stage, fname="out.md", team=TEAM, it=ITER):
    return f"- `{ts}` [{team}] iter {it} {MID} {stage} produced `{fname}`"


def _nooutput(ts, stage, attempt=1, tail=None, maxa=4, team=TEAM, it=ITER):
    base = (f"- `{ts}` [{team}] iter {it} {MID} {stage} "
            f"no output file (attempt {attempt}/{maxa})")
    return base + (f"; tail: '{tail}'" if tail else "; retrying")


def _mk(*lines):
    return "\n".join(lines) + "\n"


def _dicts(recs):
    return [r.to_dict() for r in recs]


def _keys(recs):
    return [(r.team, r.iteration, r.stage, r.attempt) for r in recs]


def _rec(team, it, stage, attempt, elapsed_s, headroom_s, stale):
    """Build a PendingStage the way a caller would -- positional, declared order."""
    return foundry.PendingStage(team, it, stage, attempt, elapsed_s, headroom_s, stale)


# One pending engineer start, 30s before `NOW`.
START_TS = "09-06 10:00:00"
NOW = "09-06 10:00:30"
PENDING_LOG = _mk(_start(START_TS, "engineer", 1))


# --------------------------------------------------------------------------
# preflight -- the fixture builders really are the shapes the parser family
# reads, so an empty result below is the NEW function's verdict and never a
# typo in this module (otherwise every "no record" assertion is vacuous).
# --------------------------------------------------------------------------
def test_b0_fixture_shape_is_the_real_one():
    complete = _mk(_start(START_TS, "engineer", 1),
                   _produced("09-06 10:05:30", "engineer", "engineer.md"))
    assert len(foundry.parse_stage_attempts(complete)) == 1, \
        "fixture builders do not match the shapes parse_stage_attempts reads"
    # ... and the same log MINUS its terminal is exactly PENDING_LOG.
    assert complete.splitlines()[0] + "\n" == PENDING_LOG


def test_b0_public_names_and_signatures_exist_as_specified():
    assert inspect.signature(foundry.pending_stage_starts).parameters.keys() >= {
        "text", "now", "cap"}
    assert inspect.signature(foundry.gather_pending_stages).parameters.keys() >= {
        "log_path", "now", "cap"}
    assert inspect.signature(foundry.inflight_cli).parameters.keys() >= {
        "log_path", "now", "as_json"}
    assert [f.name for f in dataclasses.fields(foundry.PendingStage)] == list(FIELDS)


# ==========================================================================
# Behavior 1 -- WHICH starts are pending; pure and total
# ==========================================================================
@pytest.mark.parametrize("text", [
    "",
    "   \n\t\n \n",
    "hello\nworld\n",
    _mk("- `09-06 10:00:00` some other log line entirely",
        "2026-09-06 unrelated INFO something started"),
])
def test_b1_no_matching_lines_yields_empty(text):
    assert foundry.pending_stage_starts(text, NOW) == ()


def test_b1_dangling_start_yields_exactly_one_record_with_its_own_fields():
    got = foundry.pending_stage_starts(PENDING_LOG, NOW)
    assert len(got) == 1, f"expected 1 pending record, got {_dicts(got)!r}"
    rec = got[0]
    assert rec.team == TEAM
    assert rec.iteration == ITER and isinstance(rec.iteration, int)
    assert rec.stage == "engineer"
    assert rec.attempt == 1 and isinstance(rec.attempt, int)


def test_b1_start_then_produced_yields_empty():
    text = _mk(_start(START_TS, "engineer", 1),
               _produced("09-06 10:00:10", "engineer", "engineer.md"))
    assert foundry.pending_stage_starts(text, NOW) == ()


def test_b1_start_nooutput_start_yields_one_record_at_attempt_two():
    text = _mk(_start("09-06 09:50:00", "engineer", 1),
               _nooutput("09-06 10:00:00", "engineer", 1),
               _start("09-06 10:00:10", "engineer", 2))
    got = foundry.pending_stage_starts(text, NOW)
    assert len(got) == 1, f"expected 1 in-flight retry, got {_dicts(got)!r}"
    assert got[0].attempt == 2, \
        f"in-flight retry reported as attempt {got[0].attempt}, not 2"
    # and it is priced from the SECOND start (20s), not the first (600s)
    assert got[0].elapsed_s == 20


def test_b1_terminal_with_no_preceding_start_yields_empty():
    assert foundry.pending_stage_starts(
        _mk(_produced("09-06 10:00:10", "engineer", "engineer.md")), NOW) == ()
    assert foundry.pending_stage_starts(
        _mk(_nooutput("09-06 10:00:10", "engineer", 1)), NOW) == ()


def test_b1_start_shaped_text_inside_a_tail_repr_creates_no_record():
    """The anchored-match guarantee: a failure tail that QUOTES a start line must not
    manufacture a pending record for the quoted stage."""
    embedded = _start("09-06 10:00:20", "reviewer", 1)
    text = _mk(_start(START_TS, "engineer", 1),
               _nooutput("09-06 10:00:25", "engineer", 1, tail=embedded))
    got = foundry.pending_stage_starts(text, NOW)
    assert got == (), f"tail repr leaked a phantom record: {_dicts(got)!r}"
    # the same embedded text alone, INSIDE a tail, is likewise inert
    solo = _mk(_nooutput("09-06 10:00:25", "tester", 1, tail=embedded))
    assert foundry.pending_stage_starts(solo, NOW) == ()


MALFORMED = [
    _start("13-45 99:99:99", "engineer", 1),          # regex-shaped, undateable stamp
    "- `09-06 10:00:00` [_platform] iter abc " + MID + " **engineer** attempt 1 started",
    "- `09-06 10:00:00` [_platform] iter 240 " + MID + " **engineer** attempt x started",
    "- `09-06 10:00:00` [_platform] iter 240",        # truncated
    "- `` [] iter " + MID + " ** ** attempt started",
    "\x00\x01 garbage " + MID + " attempt 1 started",
]

# Valid-but-extreme lines: these are NOT malformed (a long team name or an exotic stage
# label is still a well-formed start), so they are held to the never-raise contract only.
# Measured this stage: the 4,000-char-team line PARSES, which is the correct reading of
# "a malformed stamp, a non-integer iteration or attempt, or a truncated line is SKIPPED"
# -- length is not one of the three malformations the spec names.
STRESS = [
    "- `09-06 10:00:00` [" + "x" * 4000 + "] iter 240 " + MID + " **s** attempt 1 started",
    "- `09-06 10:00:00` [team-\u00e9\u4e2d] iter 240 " + MID + " **st\u00e5ge** attempt 1 started",
    _start("09-06 10:00:00", "engineer", 999999),
]


@pytest.mark.parametrize("bad", MALFORMED + STRESS)
def test_b1_malformed_lines_never_raise(bad):
    out = foundry.pending_stage_starts(_mk(bad), NOW)
    assert isinstance(out, tuple)


def test_b1_malformed_lines_are_skipped_and_the_remainder_survives():
    text = _mk(*(MALFORMED + [_start(START_TS, "engineer", 1)]))
    got = foundry.pending_stage_starts(text, NOW)
    assert _keys(got) == [(TEAM, ITER, "engineer", 1)], \
        f"well-formed remainder lost or polluted: {_dicts(got)!r}"


def test_b1_is_pure_no_io_no_clock_doors_touched(monkeypatch):
    """Slam every ambient door shut and assert the RIGHT records still come back --
    a per-line `except: continue` would otherwise swallow an impure call and read
    as a clean-but-empty result."""
    import builtins
    import io
    import os
    import socket
    import time

    def boom(*a, **k):
        raise AssertionError("pending_stage_starts touched an ambient door")

    for target, attr in ((builtins, "open"), (io, "open"),
                         (pathlib.Path, "read_text"), (pathlib.Path, "open"),
                         (subprocess, "run"), (subprocess, "Popen"),
                         (subprocess, "check_output"), (socket, "socket"),
                         (os, "system"), (time, "time"), (time, "monotonic")):
        monkeypatch.setattr(target, attr, boom)
    got = foundry.pending_stage_starts(PENDING_LOG, NOW)
    assert _keys(got) == [(TEAM, ITER, "engineer", 1)]
    assert got[0].elapsed_s == 30


def test_b1_uses_the_now_argument_not_the_wall_clock():
    """Same text, two different `now` values -> two different elapsed values, so the
    measurement is a function of the ARGUMENT."""
    a = foundry.pending_stage_starts(PENDING_LOG, "09-06 10:00:30")[0]
    b = foundry.pending_stage_starts(PENDING_LOG, "09-06 10:01:30")[0]
    assert (a.elapsed_s, b.elapsed_s) == (30, 90)
    # and it is deterministic: repeated calls agree
    assert foundry.pending_stage_starts(PENDING_LOG, NOW)[0] == a


# ==========================================================================
# Behavior 2 -- elapsed / headroom / stale, cap read at call time
# ==========================================================================
def test_b2_elapsed_is_whole_seconds_between_the_two_stamps():
    rec = foundry.pending_stage_starts(PENDING_LOG, "09-06 10:02:05")[0]
    assert rec.elapsed_s == 125 and isinstance(rec.elapsed_s, int)


def test_b2_midnight_crossing_adds_one_day_once():
    text = _mk(_start("09-06 23:59:30", "engineer", 1))
    rec = foundry.pending_stage_starts(text, "09-07 00:00:30")[0]
    assert rec.elapsed_s == 60


def test_b2_a_now_more_than_a_day_earlier_clamps_at_zero_never_negative():
    text = _mk(_start("12-31 23:59:00", "engineer", 1))
    rec = foundry.pending_stage_starts(text, "01-01 00:01:00")[0]
    assert rec.elapsed_s >= 0, "elapsed_s went negative"
    assert rec.elapsed_s == 0


def test_b2_headroom_is_cap_minus_elapsed_and_may_be_negative():
    rec = foundry.pending_stage_starts(PENDING_LOG, NOW, cap=600)[0]
    assert rec.headroom_s == 600 - 30
    over = foundry.pending_stage_starts(PENDING_LOG, "09-06 10:20:00", cap=600)[0]
    assert over.elapsed_s == 1200
    assert over.headroom_s == -600, "negative headroom was clamped away"


def test_b2_stale_is_elapsed_ge_cap_and_the_boundary_is_inclusive():
    below = foundry.pending_stage_starts(PENDING_LOG, "09-06 10:09:59", cap=600)[0]
    assert (below.elapsed_s, below.stale, below.headroom_s) == (599, False, 1)
    at = foundry.pending_stage_starts(PENDING_LOG, "09-06 10:10:00", cap=600)[0]
    assert at.elapsed_s == 600
    assert at.stale is True, "elapsed == cap must be STALE (the CLI kills AT the wall)"
    assert at.headroom_s == 0
    above = foundry.pending_stage_starts(PENDING_LOG, "09-06 10:10:01", cap=600)[0]
    assert above.stale is True and above.headroom_s == -1


def test_b2_cap_none_reads_the_module_global_at_call_time(monkeypatch):
    fresh = foundry.pending_stage_starts(PENDING_LOG, NOW)[0]
    assert fresh.stale is False and fresh.headroom_s == foundry.STAGE_HARD_CAP_SECONDS - 30
    monkeypatch.setattr(foundry, "STAGE_HARD_CAP_SECONDS", 10)
    flipped = foundry.pending_stage_starts(PENDING_LOG, NOW)[0]
    assert flipped.stale is True, "cap was captured at import time, not read at call time"
    assert flipped.headroom_s == -20


def test_b2_explicit_cap_overrides_the_module_global(monkeypatch):
    monkeypatch.setattr(foundry, "STAGE_HARD_CAP_SECONDS", 10)
    rec = foundry.pending_stage_starts(PENDING_LOG, NOW, cap=600)[0]
    assert (rec.stale, rec.headroom_s) == (False, 570)


@pytest.mark.parametrize("bad_now", ["", "   ", "not a stamp", "13-45 99:99:99",
                                     "2026-09-06 10:00:30"])
def test_b2_an_undateable_now_yields_no_records_and_never_raises(bad_now):
    got = foundry.pending_stage_starts(PENDING_LOG, bad_now)
    assert got == (), f"a guessed measurement leaked for now={bad_now!r}: {_dicts(got)!r}"


# ==========================================================================
# Behavior 3 -- deterministic order, frozen JSON-native record
# ==========================================================================
def test_b3_records_are_ordered_by_elapsed_descending():
    text = _mk(_start("09-06 10:00:00", "engineer", 1),          # 300s
               _start("09-06 09:55:00", "reviewer", 1, it=239),  # 600s
               _start("09-06 10:04:00", "tester", 1, it=241))    # 60s
    got = foundry.pending_stage_starts(text, "09-06 10:05:00")
    assert [r.elapsed_s for r in got] == [600, 300, 60]


def test_b3_equal_elapsed_ties_break_ascending_and_are_order_independent():
    lines = [
        _start(START_TS, "reviewer", 1, team="zteam", it=240),
        _start(START_TS, "engineer", 1, team="ateam", it=240),
        _start(START_TS, "tester", 1, team="ateam", it=239),
        _start(START_TS, "aaa", 1, team="ateam", it=240),
    ]
    forward = foundry.pending_stage_starts(_mk(*lines), NOW)
    backward = foundry.pending_stage_starts(_mk(*reversed(lines)), NOW)
    assert {r.elapsed_s for r in forward} == {30}
    assert _keys(forward) == [("ateam", 239, "tester", 1),
                             ("ateam", 240, "aaa", 1),
                             ("ateam", 240, "engineer", 1),
                             ("zteam", 240, "reviewer", 1)]
    assert _keys(forward) == _keys(backward), "order depends on line order"


def test_b3_pendingstage_is_frozen_with_value_equality():
    a = _rec(TEAM, ITER, "engineer", 1, 30, 570, False)
    b = _rec(TEAM, ITER, "engineer", 1, 30, 570, False)
    assert a == b and a is not b
    assert {a, b} == {a}, "frozen dataclass is not hashable / not value-equal"
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.elapsed_s = 99


def test_b3_to_dict_is_json_native_and_round_trips():
    rec = foundry.pending_stage_starts(PENDING_LOG, NOW)[0]
    d = rec.to_dict()
    assert set(d) == set(FIELDS)
    blob = json.dumps(d)                       # must not raise
    assert json.loads(blob) == d
    for key, want in (("team", str), ("iteration", int), ("stage", str),
                      ("attempt", int), ("elapsed_s", int), ("headroom_s", int),
                      ("stale", bool)):
        assert isinstance(d[key], want), f"{key} is {type(d[key])!r}, not {want!r}"


# ==========================================================================
# Behavior 4 -- inflight_cli exit-code contract over ONE seam
# ==========================================================================
def _seam(monkeypatch, records):
    """Replace the gather seam; the CLI must call it BY BARE MODULE NAME."""
    calls = []

    def fake(log_path, **kwargs):
        calls.append((log_path, kwargs))
        return tuple(records)

    monkeypatch.setattr(foundry, "gather_pending_stages", fake)
    return calls


def test_b4_exit_2_when_nothing_is_pending(monkeypatch, capsys):
    calls = _seam(monkeypatch, [])
    rc = foundry.inflight_cli("no-such-log.out")
    assert rc == 2
    assert calls, "inflight_cli did not go through the gather_pending_stages seam"
    assert capsys.readouterr().out.strip() != ""


def test_b4_exit_0_when_pending_and_none_stale(monkeypatch, capsys):
    _seam(monkeypatch, [_rec(TEAM, ITER, "engineer", 1, 30, 570, False)])
    assert foundry.inflight_cli("x.out") == 0
    capsys.readouterr()


def test_b4_exit_1_when_any_record_is_stale(monkeypatch, capsys):
    _seam(monkeypatch, [_rec(TEAM, ITER, "engineer", 1, 30, 570, False),
                        _rec(TEAM, ITER, "tester", 2, 700, -100, True)])
    assert foundry.inflight_cli("x.out") == 1
    capsys.readouterr()


def test_b4_missing_log_path_exits_2_without_raising(tmp_path, capsys):
    missing = tmp_path / "nope" / "dispatcher.out"
    assert foundry.inflight_cli(missing) == 2
    assert foundry.inflight_cli(str(missing)) == 2
    assert foundry.inflight_cli(tmp_path) == 2          # a DIRECTORY is unreadable text
    assert capsys.readouterr().out.strip() != ""


def test_b4_real_log_file_is_read_and_priced(tmp_path, capsys):
    log = tmp_path / "dispatcher.out"
    log.write_text(PENDING_LOG, encoding="utf-8")
    assert foundry.inflight_cli(log, now=NOW) == 0
    out = capsys.readouterr().out
    assert "engineer" in out and "30" in out


def test_b4_writes_nothing_to_disk(tmp_path, monkeypatch, capsys):
    log = tmp_path / "dispatcher.out"
    log.write_text(PENDING_LOG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    digest = log.read_bytes()
    for as_json in (False, True):
        foundry.inflight_cli(log, now=NOW, as_json=as_json)
    capsys.readouterr()
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert log.read_bytes() == digest, "inflight_cli mutated its input log"


def test_b4_json_mode_prints_exactly_one_indent_2_document(tmp_path, capsys):
    log = tmp_path / "dispatcher.out"
    log.write_text(PENDING_LOG, encoding="utf-8")
    rc = foundry.inflight_cli(log, now=NOW, as_json=True)
    out = capsys.readouterr().out
    doc = json.loads(out)                       # ONE document, or this raises
    assert json.dumps(doc, indent=2).strip() == out.strip()
    assert doc.get("exit_code") == rc, "payload exit_code disagrees with the return code"
    recs = doc["pending"] if "pending" in doc else next(
        v for v in doc.values() if isinstance(v, list))
    assert len(recs) == 1 and set(recs[0]) == set(FIELDS)


def test_b4_json_mode_no_pending_still_emits_one_valid_document(tmp_path, capsys):
    log = tmp_path / "dispatcher.out"
    log.write_text("nothing to see here\n", encoding="utf-8")
    rc = foundry.inflight_cli(log, as_json=True, now=NOW)
    doc = json.loads(capsys.readouterr().out)
    assert rc == 2 and doc.get("exit_code") == 2


def test_b4_now_none_makes_the_layer_supply_the_real_clock(tmp_path, capsys):
    """A start stamped `now` must price at a near-zero elapsed when `now` is omitted --
    proving the CLI layer supplies `dt.datetime.now().strftime(_TS_FMT)`."""
    import datetime as dt
    stamp = dt.datetime.now().strftime(foundry._TS_FMT)
    log = tmp_path / "dispatcher.out"
    log.write_text(_mk(_start(stamp, "engineer", 1)), encoding="utf-8")
    rc = foundry.inflight_cli(log)
    out = capsys.readouterr().out
    assert rc == 0, f"a just-started attempt did not price as fresh: {out!r}"
    recs = foundry.gather_pending_stages(log)
    assert len(recs) == 1
    assert 0 <= recs[0].elapsed_s <= 60, f"elapsed off the real clock: {recs[0]!r}"


# ==========================================================================
# Behavior 5 -- the rendered report
# ==========================================================================
def _render(monkeypatch, capsys, records):
    _seam(monkeypatch, records)
    foundry.inflight_cli("x.out")
    return capsys.readouterr().out


def test_b5_row_names_team_iter_stage_attempt_elapsed_and_headroom(monkeypatch, capsys):
    out = _render(monkeypatch, capsys,
                  [_rec(TEAM, ITER, "engineer", 3, 412, 188, False)])
    row = [ln for ln in out.splitlines()
           if "engineer" in ln and not ln.startswith(foundry.INFLIGHT_PREFIX)]
    assert row, f"no row rendered for the pending attempt:\n{out}"
    line = row[0]
    for token in (TEAM, f"iter {ITER}", "engineer", "attempt 3", "412", "188"):
        assert token in line, f"row is missing {token!r}: {line!r}"


def test_b5_stale_token_appears_only_on_stale_rows(monkeypatch, capsys):
    out = _render(monkeypatch, capsys,
                  [_rec(TEAM, ITER, "tester", 2, 900, -300, True),
                   _rec(TEAM, ITER, "engineer", 1, 30, 570, False)])
    stale_rows = [ln for ln in out.splitlines() if "tester" in ln]
    fresh_rows = [ln for ln in out.splitlines() if "engineer" in ln]
    assert stale_rows and "STALE" in stale_rows[0]
    assert fresh_rows and "STALE" not in fresh_rows[0], \
        f"non-stale row carries the STALE token: {fresh_rows[0]!r}"


def test_b5_first_line_anchors_on_the_prefix_and_names_the_effective_cap(
        monkeypatch, capsys):
    assert isinstance(foundry.INFLIGHT_PREFIX, str) and foundry.INFLIGHT_PREFIX
    out = _render(monkeypatch, capsys, [_rec(TEAM, ITER, "engineer", 1, 30, 570, False)])
    first = out.splitlines()[0]
    assert first.startswith(foundry.INFLIGHT_PREFIX), \
        f"first line is not anchored on INFLIGHT_PREFIX: {first!r}"
    assert str(foundry.STAGE_HARD_CAP_SECONDS) in first, \
        f"first line does not name the effective cap: {first!r}"


def test_b5_no_pending_renders_one_non_empty_line(monkeypatch, capsys):
    out = _render(monkeypatch, capsys, [])
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected exactly one line, got {lines!r}"
    assert lines[0].startswith(foundry.INFLIGHT_PREFIX)
    assert "STALE" not in lines[0]


# ==========================================================================
# Behavior 6 -- registration, dormancy, README row
# ==========================================================================
def test_b6_help_exits_0_and_names_the_three_flags():
    proc = subprocess.run([sys.executable, "foundry.py", "inflight", "--help"],
                          cwd=str(_ROOT), capture_output=True, text=True, timeout=90)
    assert proc.returncode == 0, f"--help exited {proc.returncode}: {proc.stderr!r}"
    for flag in ("--log", "--now", "--json"):
        assert flag in proc.stdout, f"{flag} missing from help:\n{proc.stdout}"


def test_b6_runs_without_a_config_flag(tmp_path):
    """Dispatched BEFORE load_config, like stage-times: an EMPTY cwd (no config.json,
    no products/) must still produce a clean 0/1/2 exit, never a config error."""
    log = tmp_path / "dispatcher.out"
    log.write_text(PENDING_LOG, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "foundry.py"), "inflight",
         "--log", str(log), "--now", NOW],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=90)
    assert proc.returncode in (0, 1, 2), \
        f"exit {proc.returncode}; stderr={proc.stderr!r}"
    assert "Traceback" not in proc.stderr
    assert proc.stdout.strip(), "no report on stdout"


def _referenced(fn):
    """Every name and string constant reachable from a function's code object."""
    seen, stack = set(), [fn.__code__]
    while stack:
        code = stack.pop()
        seen.update(code.co_names)
        for const in code.co_consts:
            if hasattr(const, "co_names"):
                stack.append(const)
            elif isinstance(const, str):
                seen.add(const)
    return seen


NEW_NAMES = {"pending_stage_starts", "gather_pending_stages", "inflight_cli",
             "PendingStage"}


@pytest.mark.parametrize("fname", ["run_iteration", "run_stage", "build_prompt"])
def test_b6_dormant_no_call_site_on_the_control_path(fname):
    hits = NEW_NAMES & _referenced(getattr(foundry, fname))
    assert hits == set(), f"{fname} references {sorted(hits)} -- the verb is not dormant"


def test_b6_dormant_dispatcher_never_references_the_new_names():
    import dispatcher
    for name in dir(dispatcher):
        obj = getattr(dispatcher, name)
        if inspect.isfunction(obj) and getattr(obj, "__module__", "") == "dispatcher":
            hits = NEW_NAMES & _referenced(obj)
            assert hits == set(), f"dispatcher.{name} references {sorted(hits)}"
    src_names = {n for n in dir(dispatcher)} & NEW_NAMES
    assert src_names == set(), f"dispatcher re-exports {sorted(src_names)}"


def test_b6_readme_verb_list_gains_an_inflight_row():
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    rows = [ln for ln in readme.splitlines()
            if ln.startswith("# ") and "`inflight`" in ln]
    assert rows, "README verb list has no row naming `inflight`"
    assert any("inflight" in ln and "foundry.py" in ln for ln in readme.splitlines()), \
        "README shows no runnable `foundry.py inflight` invocation"


def test_b6_both_modules_still_import():
    for mod in ("foundry", "dispatcher"):
        proc = subprocess.run([sys.executable, "-c", f"import {mod}"],
                              cwd=str(_ROOT), capture_output=True, text=True, timeout=90)
        assert proc.returncode == 0, f"import {mod} failed: {proc.stderr!r}"
