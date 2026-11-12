"""Iteration 528 -- BLACK-BOX behavior tests for `foundry inflight` HOLD rows: the verb
also names each stage currently waiting out a `backing off N min (failure kind: K)`
sleep between attempts (re-land of iteration 527's reviewed design).

Spec under test: products/_platform/state/iter-528/pm.md, Expected Behaviors 1-11
(`PendingHold`, `open_holds`, `gather_open_holds`, `INFLIGHT_HOLD`, the
`render_inflight(records, holds=())` extension and the `inflight_cli` exit/JSON
contract).

ISOLATION CONTRACT (HONORED): written ONLY from that PM spec, the conventions under
`tests/` (the `dispatcher.out` line builders of tests/test_iter240_behavior.py), and
the product's OWN OBSERVABLE surface -- importing `foundry`, calling its public
functions, `inspect`/`dataclasses` introspection of declared signatures, code-object
introspection for the off-control-path proof, and running `foundry.py inflight` as a
subprocess.  I did NOT read the implementation source, engineer.md, reviewer.md, or
any `git diff`.

Every log fixture is a SYNTHETIC STRING built in-process and every path is under
`tmp_path`; no git, no network, no real clock (the CLI cases pass `--now`).
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

MID = "\u00b7"
TEAM = "_platform"
ITER = 527
HOLD_FIELDS = ("team", "iteration", "stage", "kind", "wait_s", "elapsed_s",
               "remaining_s")


# --------------------------------------------------------------------------
# fixture builders -- the EXACT dispatcher.out line shapes
# --------------------------------------------------------------------------
def _pre(ts, team=TEAM, it=ITER):
    return f"- `{ts}` [{team}] iter {it} {MID} "


def _backoff(ts, stage, mins, kind, team=TEAM, it=ITER, suffix=""):
    return (_pre(ts, team, it)
            + f"{stage} backing off {mins} min (failure kind: {kind}){suffix}")


def _start(ts, stage, attempt=1, team=TEAM, it=ITER):
    return _pre(ts, team, it) + f"**{stage}** attempt {attempt} started"


def _produced(ts, stage, fname="out.md", team=TEAM, it=ITER):
    return _pre(ts, team, it) + f"{stage} produced `{fname}`"


def _nooutput(ts, stage, attempt=1, team=TEAM, it=ITER, tail=None):
    base = _pre(ts, team, it) + f"{stage} no output file (attempt {attempt}/4)"
    return base + (f"; tail: '{tail}'" if tail else "; retrying")


def _resume(ts, stage, k=1, m=24, team=TEAM, it=ITER):
    return _pre(ts, team, it) + f"{stage} auth resume {k}/{m}: re-running stage after hold"


def _mk(*lines):
    return "\n".join(lines) + "\n"


B1_LINE = (f"- `11-11 15:13:28` [_platform] iter 527 {MID} pm_scout_b backing off "
           f"30 min (failure kind: auth) -- auth hold: waiting for the account")
NOW = "11-11 15:20:00"
B1_LOG = _mk(B1_LINE)
B1_REC = ("_platform", 527, "pm_scout_b", "auth", 1800, 392, 1408)
B1_ROW = ("  [_platform] iter 527 pm_scout_b HOLD -- backing off (failure kind: auth), "
          "elapsed 392s of a 1800s wait, re-run in 1408s")


def _t(h):
    return tuple(getattr(h, f) for f in HOLD_FIELDS)


def _ts(holds):
    return [_t(h) for h in holds]


def _hold(*vals):
    return foundry.PendingHold(*vals)


# ==========================================================================
# B0 -- names, signatures, dataclass shape
# ==========================================================================
def test_b0_public_names_and_signatures():
    assert foundry.INFLIGHT_HOLD == "HOLD"
    assert dataclasses.is_dataclass(foundry.PendingHold)
    assert [f.name for f in dataclasses.fields(foundry.PendingHold)] == list(HOLD_FIELDS)
    assert list(inspect.signature(foundry.open_holds).parameters) == ["text", "now"]
    sig = inspect.signature(foundry.gather_open_holds)
    assert "log_path" in sig.parameters
    assert sig.parameters["now"].kind is inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["now"].default is None
    rsig = inspect.signature(foundry.render_inflight)
    params = list(rsig.parameters.values())
    assert len(params) >= 2 and params[1].name == "holds" and params[1].default == ()


def test_b0_pendinghold_is_frozen_and_to_dict_is_exact_json():
    h = _hold(*B1_REC)
    with pytest.raises(dataclasses.FrozenInstanceError):
        h.wait_s = 1  # type: ignore[misc]
    d = h.to_dict()
    assert set(d) == set(HOLD_FIELDS) and len(d) == 7
    assert json.loads(json.dumps(d)) == d
    assert d == dict(zip(HOLD_FIELDS, B1_REC))


# ==========================================================================
# B1 -- hold opened
# ==========================================================================
def test_b1_spec_example_exact_record():
    got = foundry.open_holds(B1_LOG, NOW)
    assert _ts(got) == [B1_REC]
    assert isinstance(got[0], foundry.PendingHold)


def test_b1_ladder_line_without_suffix_and_kind_is_stripped():
    text = _mk(_backoff("11-11 18:11:51", "pm_scout_a", 5, " stalled ",
                        team="repolens", it=477))
    got = foundry.open_holds(text, "11-11 18:12:51")
    assert _ts(got) == [("repolens", 477, "pm_scout_a", "stalled", 300, 60, 240)]


def test_b1_hold_after_a_failed_attempt_is_open():
    text = _mk(_start("11-11 15:00:00", "tester"),
               _nooutput("11-11 15:00:16", "tester"),
               _backoff("11-11 15:00:17", "tester", 5, "stalled"))
    got = foundry.open_holds(text, "11-11 15:01:17")
    assert _ts(got) == [(TEAM, ITER, "tester", "stalled", 300, 60, 240)]


# ==========================================================================
# B2 -- closed, replaced, per-key isolation
# ==========================================================================
@pytest.mark.parametrize("closer", [
    _start("11-11 15:15:00", "pm_scout_b", 2),
    _produced("11-11 15:15:00", "pm_scout_b", "pm_scout_b.md"),
    _nooutput("11-11 15:15:00", "pm_scout_b", 2),
    _resume("11-11 15:15:00", "pm_scout_b", 1, 24),
], ids=["start", "produced", "no_output", "auth_resume"])
def test_b2_a_later_closer_for_the_same_key_ends_the_hold(closer):
    assert foundry.open_holds(_mk(B1_LINE, closer), NOW) == ()


@pytest.mark.parametrize("other", [
    _start("11-11 15:15:00", "engineer", 1),                      # other stage
    _produced("11-11 15:15:00", "pm_scout_b", it=528),            # other iteration
    _resume("11-11 15:15:00", "pm_scout_b", team="repolens"),     # other team
    _nooutput("11-11 15:15:00", "pm_scout_a"),
], ids=["other_stage", "other_iter", "other_team", "other_stage_noout"])
def test_b2_lines_for_other_keys_never_close_a_hold(other):
    assert _ts(foundry.open_holds(_mk(B1_LINE, other), NOW)) == [B1_REC]


def test_b2_later_backoff_replaces_the_earlier_hold():
    text = _mk(B1_LINE, _backoff("11-11 15:18:00", "pm_scout_b", 5, "stalled"))
    assert _ts(foundry.open_holds(text, NOW)) == [
        (TEAM, ITER, "pm_scout_b", "stalled", 300, 120, 180)]


def test_b2_replacement_by_an_expired_backoff_reports_nothing():
    # newest wins even when the newest is already past its wait
    text = _mk(B1_LINE, _backoff("11-11 15:14:00", "pm_scout_b", 1, "stalled"))
    assert foundry.open_holds(text, NOW) == ()


def test_b2_close_then_reopen_reports_the_reopened_hold():
    text = _mk(B1_LINE, _resume("11-11 15:14:00", "pm_scout_b"),
               _nooutput("11-11 15:14:30", "pm_scout_b", 2),
               _backoff("11-11 15:19:00", "pm_scout_b", 20, "auth"))
    assert _ts(foundry.open_holds(text, NOW)) == [
        (TEAM, ITER, "pm_scout_b", "auth", 1200, 60, 1140)]


# ==========================================================================
# B3 -- only open holds; boundaries; midnight rule
# ==========================================================================
@pytest.mark.parametrize("now,expected", [
    ("11-11 15:13:28", [(TEAM, ITER, "pm_scout_b", "auth", 1800, 0, 1800)]),
    ("11-11 15:43:27", [(TEAM, ITER, "pm_scout_b", "auth", 1800, 1799, 1)]),
    ("11-11 15:43:28", []),
    ("11-11 16:00:00", []),
], ids=["elapsed0", "wait_minus_1", "elapsed_eq_wait", "past"])
def test_b3_open_window_boundaries(now, expected):
    assert _ts(foundry.open_holds(B1_LOG, now)) == expected


def test_b3_zero_minute_backoff_is_never_reported():
    text = _mk(_backoff("11-11 15:20:00", "engineer", 0, "stalled"))
    assert foundry.open_holds(text, "11-11 15:20:00") == ()


def test_b3_midnight_rollover_adds_one_day():
    text = _mk(_backoff("11-11 23:55:00", "engineer", 20, "stalled"))
    assert _ts(foundry.open_holds(text, "11-12 00:05:00")) == [
        (TEAM, ITER, "engineer", "stalled", 1200, 600, 600)]


def test_b3_ghost_from_a_later_date_is_skipped_not_clamped():
    text = _mk(_backoff("11-13 15:00:00", "engineer", 30, "auth"))
    assert foundry.open_holds(text, "11-11 15:00:00") == ()


# ==========================================================================
# B4 -- pure, total, malformed input, ordering
# ==========================================================================
@pytest.mark.parametrize("text", [
    "", "\n", "garbage", "\x00\ufffd", "- `` [] iter  \u00b7 ", B1_LINE[:40],
    "x" * 5000, B1_LOG * 3,
])
def test_b4_total_for_any_text(text):
    assert isinstance(foundry.open_holds(text, NOW), tuple)


@pytest.mark.parametrize("now", ["", "not a stamp", "99-99 99:99:99", "11-11"])
def test_b4_undateable_now_returns_empty(now):
    assert foundry.open_holds(B1_LOG, now) == ()


@pytest.mark.parametrize("bad", [
    f"- `11-1x 15:13:28` [_platform] iter 527 {MID} pm_scout_b backing off 30 min (failure kind: auth)",
    f"- `11-11 15:13:28` [_platform] iter abc {MID} pm_scout_b backing off 30 min (failure kind: auth)",
    f"- `11-11 15:13:28` [_platform] iter 527 {MID} pm_scout_b backing off xx min (failure kind: auth)",
    f"- `11-11 15:13:28` [_platform] iter 527 {MID} pm_scout_b backing off 30 min (failure kind: auth",
    f"- `11-11 15:13:28` [_platform] iter 527 {MID} pm_scout_b backing off",
], ids=["bad_stamp", "bad_iter", "bad_minutes", "no_close_paren", "truncated"])
def test_b4_malformed_lines_are_ignored_and_the_remainder_survives(bad):
    other = _backoff("11-11 15:19:00", "engineer", 5, "stalled")
    got = foundry.open_holds(_mk(bad, other), NOW)
    assert _ts(got) == [(TEAM, ITER, "engineer", "stalled", 300, 60, 240)]


def test_b4_backoff_text_quoted_in_a_payload_is_not_a_hold():
    tail = "x backing off 5 min (failure kind: auth) y"
    text = _mk(_nooutput("11-11 15:19:00", "tester", tail=tail))
    assert foundry.open_holds(text, NOW) == ()
    # also inside a produced/start payload of another stage
    quoted = _pre("11-11 15:19:00") + "tester note: engineer backing off 5 min (failure kind: auth)"
    assert foundry.open_holds(_mk(quoted), NOW) == ()


def test_b4_sorted_by_remaining_then_key():
    text = _mk(
        _backoff("11-11 15:19:00", "zeta", 20, "auth"),            # remaining 1140
        _backoff("11-11 15:19:00", "beta", 5, "stalled"),          # remaining 240
        _backoff("11-11 15:19:00", "alpha", 5, "stalled", it=600),  # 240, iter 600
        _backoff("11-11 15:19:00", "gamma", 5, "stalled", team="zz"),  # 240, team zz
        _backoff("11-11 15:19:00", "alpha", 5, "stalled"),         # 240
    )
    got = foundry.open_holds(text, NOW)
    keys = [(h.team, h.iteration, h.stage, h.remaining_s) for h in got]
    assert keys == [
        (TEAM, ITER, "alpha", 240),
        (TEAM, ITER, "beta", 240),
        (TEAM, 600, "alpha", 240),
        ("zz", ITER, "gamma", 240),
        (TEAM, ITER, "zeta", 1140),
    ]


def test_b4_pure_same_input_same_output():
    assert foundry.open_holds(B1_LOG, NOW) == foundry.open_holds(B1_LOG, NOW)


# ==========================================================================
# B5 -- the gather seam
# ==========================================================================
def test_b5_seam_matches_the_pure_function(tmp_path):
    log = tmp_path / "dispatcher.out"
    log.write_text(B1_LOG, encoding="utf-8")
    assert foundry.gather_open_holds(log, now=NOW) == foundry.open_holds(B1_LOG, NOW)
    assert _ts(foundry.gather_open_holds(str(log), now=NOW)) == [B1_REC]


def test_b5_seam_reads_through_read_dispatcher_log_by_bare_name(monkeypatch):
    calls = []

    def fake(path, *a, **k):
        calls.append(path)
        return B1_LOG
    monkeypatch.setattr(foundry, "read_dispatcher_log", fake)
    assert _ts(foundry.gather_open_holds("nowhere.out", now=NOW)) == [B1_REC]
    assert calls


def test_b5_missing_unreadable_or_directory_returns_empty(tmp_path):
    assert foundry.gather_open_holds(tmp_path / "missing.out", now=NOW) == ()
    assert foundry.gather_open_holds(tmp_path, now=NOW) == ()
    binf = tmp_path / "bin.out"
    binf.write_bytes(b"\xff\xfe\x00\x81" * 50)
    assert isinstance(foundry.gather_open_holds(binf, now=NOW), tuple)


# ==========================================================================
# B6 / B7 -- render
# ==========================================================================
def _pending(stale=False):
    return foundry.PendingStage(TEAM, 528, "engineer", 1, 30, 570, stale)


RECORD_SETS = [(), (_pending(),), (_pending(), _pending(True))]


@pytest.mark.parametrize("records", RECORD_SETS, ids=["empty", "one", "two_stale"])
def test_b6_no_holds_is_byte_identical(records):
    base = foundry.render_inflight(records)
    assert isinstance(base, str) and base.strip()
    assert foundry.render_inflight(records, ()) == base
    assert foundry.render_inflight(records, holds=()) == base
    assert "HOLD" not in base


@pytest.mark.parametrize("records", RECORD_SETS, ids=["empty", "one", "two_stale"])
def test_b7_with_holds_appends_header_and_rows_in_given_order(records):
    base = foundry.render_inflight(records)
    h1 = _hold(*B1_REC)
    h2 = _hold("repolens", 477, "pm_scout_a", "stalled", 300, 60, 240)
    out = foundry.render_inflight(records, (h1, h2))
    bl = base.splitlines()
    ol = out.splitlines()
    assert ol[:len(bl)] == bl, "existing text changed when holds were added"
    assert ol[len(bl):] == [
        "  holds: 2 stage(s) waiting out a backoff between attempts",
        B1_ROW,
        "  [repolens] iter 477 pm_scout_a HOLD -- backing off (failure kind: stalled), "
        "elapsed 60s of a 300s wait, re-run in 240s",
    ]
    assert sum(foundry.INFLIGHT_HOLD in ln for ln in ol) == 2


# ==========================================================================
# B8 / B9 / B10 -- CLI text, exit code, JSON
# ==========================================================================
def _write(tmp_path, text, name="dispatcher.out"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_b8_cli_subprocess_prints_hold_row_and_exits_0(tmp_path):
    log = _write(tmp_path, B1_LOG)
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "foundry.py"), "inflight", "--log", str(log),
         "--now", NOW], cwd=str(tmp_path), capture_output=True, text=True, timeout=90)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert B1_ROW in proc.stdout.splitlines()
    assert "Traceback" not in proc.stderr


def test_b9_hold_only_exits_0(tmp_path, capsys):
    assert foundry.inflight_cli(_write(tmp_path, B1_LOG), now=NOW) == 0
    assert B1_ROW in capsys.readouterr().out.splitlines()


def test_b9_nothing_and_missing_still_exit_2(tmp_path, capsys):
    assert foundry.inflight_cli(_write(tmp_path, "nothing\n"), now=NOW) == 2
    assert foundry.inflight_cli(tmp_path / "missing.out", now=NOW) == 2
    # an expired hold is not in flight
    assert foundry.inflight_cli(_write(tmp_path, B1_LOG, "x.out"),
                                now="11-11 16:30:00") == 2
    assert "HOLD" not in capsys.readouterr().out


def test_b9_stale_pending_still_exits_1_with_a_hold(tmp_path, capsys):
    text = _mk(_start("11-11 14:00:00", "engineer", 1, it=528), B1_LINE)
    assert foundry.inflight_cli(_write(tmp_path, text), now=NOW) == 1
    capsys.readouterr()


def test_b9_fresh_pending_plus_hold_exits_0(tmp_path, capsys):
    text = _mk(_start("11-11 15:19:30", "engineer", 1, it=528), B1_LINE)
    assert foundry.inflight_cli(_write(tmp_path, text), now=NOW) == 0
    out = capsys.readouterr().out
    assert B1_ROW in out.splitlines()


def test_b9_cli_uses_gather_open_holds_by_bare_name(tmp_path, monkeypatch, capsys):
    seen = []

    def fake(log_path, *, now=None):
        seen.append(now)
        return (_hold("<T>", 1, "<STAGE>", "k", 600, 1, 599),)
    monkeypatch.setattr(foundry, "gather_open_holds", fake)
    rc = foundry.inflight_cli(_write(tmp_path, "nothing\n"), now=NOW)
    assert rc == 0 and seen == [NOW]
    assert "<STAGE>" in capsys.readouterr().out


def test_b10_json_adds_holds_and_keeps_exit_code(tmp_path, capsys):
    rc = foundry.inflight_cli(_write(tmp_path, B1_LOG), now=NOW, as_json=True)
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0 and doc["exit_code"] == 0
    assert doc["hold_count"] == 1
    assert doc["holds"] == [dict(zip(HOLD_FIELDS, B1_REC))]


def test_b10_json_existing_keys_unchanged_and_empty_holds(tmp_path, capsys, monkeypatch):
    log = _write(tmp_path, _mk(_start("11-11 15:19:30", "engineer", 1, it=528)))
    foundry.inflight_cli(log, now=NOW, as_json=True)
    with_new = json.loads(capsys.readouterr().out)
    assert with_new["hold_count"] == 0 and with_new["holds"] == []
    # The pre-existing payload is what's left when the two new keys are removed;
    # compare with the payload produced when gather_open_holds is forced empty
    # and a hold-bearing log is used -- the old keys must not depend on holds.
    log2 = _write(tmp_path, _mk(_start("11-11 15:19:30", "engineer", 1, it=528),
                                B1_LINE), "y.out")
    foundry.inflight_cli(log2, now=NOW, as_json=True)
    with_hold = json.loads(capsys.readouterr().out)
    for d in (with_new, with_hold):
        d.pop("hold_count")
        d.pop("holds")
    assert with_new == with_hold
    assert with_new["exit_code"] == 0


def test_b10_json_nothing_exits_2(tmp_path, capsys):
    rc = foundry.inflight_cli(_write(tmp_path, "nothing\n"), now=NOW, as_json=True)
    doc = json.loads(capsys.readouterr().out)
    assert rc == 2 and doc["exit_code"] == 2
    assert doc["hold_count"] == 0 and doc["holds"] == []


# ==========================================================================
# B11 -- off the control path
# ==========================================================================
NEW_NAMES = {"open_holds", "gather_open_holds", "PendingHold"}


def _referenced(fn):
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


@pytest.mark.parametrize("fname", ["run_stage", "run_iteration", "run_continuous",
                                   "build_prompt", "postrelease_step"])
def test_b11_control_path_never_mentions_new_names(fname):
    fn = getattr(foundry, fname)
    assert not (_referenced(fn) & NEW_NAMES), fname


def test_b11_dispatcher_never_mentions_new_names():
    src = (_ROOT / "dispatcher.py").read_text(encoding="utf-8")
    for name in NEW_NAMES:
        assert name not in src, name
