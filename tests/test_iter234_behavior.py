"""Iteration 234 -- BLACK-BOX behavior tests: the ONE stage-log stamp parser that five
timing readers share must not silently drop a leap-day (``02-29``) row.

Spec under test (products/_platform/state/iter-234/pm.md), Expected Behaviors 1-6:

   1. A LEAP-DAY ATTEMPT IS EMITTED -- a ``02-29`` start + produced pair yields exactly
      ONE ``StageAttempt`` (team ``_platform``, iteration 234, stage ``engineer``,
      attempt 1, ``duration_s=330``, ``produced=True``, ``kind=""``).  Pre-fix value
      quoted by the spec: ``0`` attempts, ``[]``.
   2. A LEAP-DAY RETRY SEQUENCE IS EMITTED IN TERMINAL ORDER -- four ``02-29`` lines
      yield exactly TWO attempts, in order
      ``(1, 600, produced=False, kind="timeout")`` then ``(2, 300, True, "")``.
   3. NON-LEAP-DAY OUTPUT IS UNCHANGED -- four inputs (a plain pair, an ordinary
      midnight crossing, the year rollover pinned by ``## Out of Scope`` item 2, and
      the ``kind``-carrying terminals) compared as EXACT ``to_dict()`` dicts, not by eye.
   4. TOTALITY IS PRESERVED -- regex-shaped but impossible dates (``13-01``, ``02-30``,
      ``00-00``) still yield ``[]`` and raise nothing, and one impossible pair mixed
      with one valid ``02-28`` pair still yields exactly the ``02-28`` attempt.
   5. THE STAMP CONVERSION IS A NAMED, MONKEYPATCHABLE MODULE-LEVEL SEAM --
      ``foundry.parse_log_stamp(ts) -> datetime | None`` exists, is leap-year-dated,
      returns ``None`` for impossible/empty input, never raises for ANY ``str``, and is
      called BY BARE NAME so ``monkeypatch.setattr(foundry, "parse_log_stamp", ...)``
      empties Behavior 1's result.
   6. ``_TS_FMT`` IS UNCHANGED -- ``foundry._TS_FMT == "%m-%d %H:%M:%S"`` still holds and
      formatting a datetime through it still yields a year-less ``MM-DD HH:MM:SS``
      string, so the two ``strftime`` emitters keep their output shape.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-234 PM spec, the
conventions already established under ``tests/`` (the ``dispatcher.out`` line builders
of ``tests/test_iter148_behavior.py``), and the product's OWN OBSERVABLE surface --
importing ``foundry`` and calling its public functions plus ``inspect``/``dataclasses``
introspection of their declared signatures.  I did NOT read the implementation source of
``foundry.py``, nor ``engineer.md``, ``reviewer.md`` or ``git diff``.

Every input below is a SYNTHETIC STRING built in-process and handed to a pure function:
no subprocess, no git, no filesystem, no network, no wall clock, no ambient tree state
(OPERATOR 2026-08-11 -- a precondition that is only true in one working tree is not a
precondition).  ``02-29`` is used as a LITERAL calendar shape, never derived from
``today()``: a parser whose verdict changes with the year is the defect, not the fix.
"""

import dataclasses
import datetime as dt
import inspect
import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

# The MIDDLE DOT (U+00B7) separator emitted by log(); built from its code point, never
# embedded, following tests/test_iter148_behavior.py:57-59.
MID = "\u00b7"

TEAM = "_platform"
ITER = 234

# The MEASURED failure tail the spec names for Behaviors 2 and 3d.
TAIL_TIMEOUT = "agent run timed out after 600s"

_FIELDS = ("team", "iteration", "stage", "attempt", "duration_s", "produced", "kind")


# --------------------------------------------------------------------------
# fixture builders -- the EXACT dispatcher.out line shapes
# (tests/test_iter148_behavior.py:76-93 conventions, reproduced not imported)
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


def _dicts(attempts):
    return [a.to_dict() for a in attempts]


def _expect(stage, attempt, duration_s, produced, kind, team=TEAM, it=ITER):
    """The FULL expected to_dict() mapping -- every declared field, no subset."""
    return {"team": team, "iteration": it, "stage": stage, "attempt": attempt,
            "duration_s": duration_s, "produced": produced, "kind": kind}


# The two Behavior-1 lines, verbatim from the spec (02-29, 10:00:00 -> 10:05:30 = 330s).
B1_LOG = _mk(
    _start("02-29 10:00:00", "engineer", 1),
    _produced("02-29 10:05:30", "engineer", "engineer.md"),
)


# --------------------------------------------------------------------------
# preflight: the fixtures themselves are well formed, so a 0-attempt result is
# the PARSER's verdict and never a typo in this module (a fixture the parser
# cannot see at all would make every assertion below vacuously "unchanged").
# --------------------------------------------------------------------------
def test_b0_fixture_shape_is_the_real_one():
    """The builders differ from a MEASURED-good baseline only in the stamp."""
    baseline = _mk(_start("02-28 10:00:00", "engineer", 1),
                   _produced("02-28 10:05:30", "engineer", "engineer.md"))
    assert baseline.replace("02-28", "02-29") == B1_LOG
    # and that baseline really is parseable, so the fixture is not the variable
    assert len(foundry.parse_stage_attempts(baseline)) == 1


# --------------------------------------------------------------------------
# Behavior 1 -- a leap-day attempt is emitted
# --------------------------------------------------------------------------
def test_b1_leap_day_attempt_is_emitted():
    got = foundry.parse_stage_attempts(B1_LOG)
    assert len(got) == 1, f"leap-day row dropped: {_dicts(got)!r}"
    assert got[0].to_dict() == _expect("engineer", 1, 330, True, "")


def test_b1_leap_day_matches_the_non_leap_twin_field_for_field():
    """Same log, one day earlier: only the calendar date differs, so every parsed
    field must be identical.  This is the whole defect in one assertion."""
    twin = B1_LOG.replace("02-29", "02-28")
    assert _dicts(foundry.parse_stage_attempts(B1_LOG)) == \
        _dicts(foundry.parse_stage_attempts(twin))


# --------------------------------------------------------------------------
# Behavior 2 -- a leap-day RETRY sequence, in terminal order
# --------------------------------------------------------------------------
def test_b2_leap_day_retry_sequence_in_terminal_order():
    log = _mk(
        _start("02-29 01:00:00", "tester", 1),
        _nooutput("02-29 01:10:00", "tester", 1, tail=TAIL_TIMEOUT),
        _start("02-29 01:10:05", "tester", 2),
        _produced("02-29 01:15:05", "tester", "tester.md"),
    )
    got = foundry.parse_stage_attempts(log)
    assert len(got) == 2, f"expected 2 leap-day attempts, got {_dicts(got)!r}"
    assert _dicts(got) == [
        _expect("tester", 1, 600, False, "timeout"),
        _expect("tester", 2, 300, True, ""),
    ]


# --------------------------------------------------------------------------
# Behavior 3 -- non-leap-day output is unchanged, as EXACT to_dict() dicts
# --------------------------------------------------------------------------
def test_b3a_plain_non_leap_pair():
    log = _mk(_start("02-28 10:00:00", "engineer", 1),
              _produced("02-28 10:05:30", "engineer", "engineer.md"))
    assert _dicts(foundry.parse_stage_attempts(log)) == \
        [_expect("engineer", 1, 330, True, "")]


def test_b3b_ordinary_midnight_crossing():
    log = _mk(_start("06-01 23:59:30", "pm", 1),
              _produced("06-02 00:00:10", "pm", "pm.md"))
    assert _dicts(foundry.parse_stage_attempts(log)) == \
        [_expect("pm", 1, 40, True, "")]


def test_b3c_year_rollover_pins_the_known_under_report():
    """NO-REGRESSION PIN of the separate defect held out by `## Out of Scope` item 2
    (the two stamps land in the SAME synthetic year, so one added day cannot close a
    ~364-day gap).  duration_s=0 is PINNED here as today's value, NOT endorsed."""
    log = _mk(_start("12-31 23:59:30", "pm", 1),
              _produced("01-01 00:00:10", "pm", "pm.md"))
    assert _dicts(foundry.parse_stage_attempts(log)) == \
        [_expect("pm", 1, 0, True, "")]


def test_b3d_terminals_still_carry_their_kind_verdict():
    failed = _mk(_start("02-28 01:00:00", "tester", 1),
                 _nooutput("02-28 01:10:00", "tester", 1, tail=TAIL_TIMEOUT))
    assert _dicts(foundry.parse_stage_attempts(failed)) == \
        [_expect("tester", 1, 600, False, "timeout")]
    # the kind is the classifier's own verdict, not a literal this test invented
    assert foundry.classify_attempt_failure(TAIL_TIMEOUT) == "timeout"
    ok = _mk(_start("02-28 02:00:00", "tester", 1),
             _produced("02-28 02:00:30", "tester", "tester.md"))
    assert _dicts(foundry.parse_stage_attempts(ok)) == \
        [_expect("tester", 1, 30, True, "")]


# --------------------------------------------------------------------------
# Behavior 4 -- totality: an impossible date is skipped, never fatal
# --------------------------------------------------------------------------
def test_b4_impossible_dates_are_skipped_not_fatal():
    for bad in ("13-01", "02-30", "00-00"):
        log = _mk(_start(f"{bad} 10:00:00", "engineer", 1),
                  _produced(f"{bad} 10:05:30", "engineer", "engineer.md"))
        # the stamps DO match the regex shape the parser scans for
        assert re.search(r"`\d\d-\d\d \d\d:\d\d:\d\d`", log)
        assert foundry.parse_stage_attempts(log) == [], f"{bad} was not skipped"


def test_b4_impossible_and_valid_pair_mixed():
    log = _mk(
        _start("00-00 09:00:00", "engineer", 1),
        _produced("00-00 09:05:30", "engineer", "engineer.md"),
        _start("02-28 10:00:00", "engineer", 1),
        _produced("02-28 10:05:30", "engineer", "engineer.md"),
    )
    assert _dicts(foundry.parse_stage_attempts(log)) == \
        [_expect("engineer", 1, 330, True, "")]


# --------------------------------------------------------------------------
# Behavior 5 -- the conversion is a named, monkeypatchable module-level seam
# --------------------------------------------------------------------------
def test_b5_seam_exists_with_the_declared_signature():
    fn = getattr(foundry, "parse_log_stamp", None)
    assert callable(fn), "parse_log_stamp is not a module-level callable"
    sig = inspect.signature(fn)
    assert list(sig.parameters) == ["ts"], sig
    assert "str" in str(sig.parameters["ts"].annotation)
    ret = str(sig.return_annotation)
    assert "datetime" in ret and "None" in ret, ret
    doc = inspect.getdoc(fn) or ""
    assert "leap" in doc.lower(), "docstring must say WHY the year must be a leap year"


def test_b5_seam_verdicts():
    got = foundry.parse_log_stamp("02-29 10:00:00")
    assert isinstance(got, dt.datetime)
    assert (got.month, got.day, got.hour, got.minute, got.second) == (2, 29, 10, 0, 0)
    assert got.year % 4 == 0 and (got.year % 100 != 0 or got.year % 400 == 0), \
        f"synthetic year {got.year} is not a leap year"
    for bad in ("02-30 10:00:00", "13-01 10:00:00", ""):
        assert foundry.parse_log_stamp(bad) is None, bad


def test_b5_seam_is_total_over_str_input():
    """NEVER raises for ANY str.  A bounded but adversarial census, built here."""
    cases = [
        "", " ", "\n", "\t", "x", "02-29", "02-29 10:00", "02-29 25:00:00",
        "02-29 10:60:00", "02-29 10:00:60", "0-0 0:0:0", "99-99 99:99:99",
        "-1--1 10:00:00", "02/29 10:00:00", "02-29T10:00:00", "02-29 10:00:00 ",
        " 02-29 10:00:00", "02-29 10:00:00.5", "02-29 10:00:00Z", "\u00b7",
        "\x00", "ff-ff ff:ff:ff", "02-29 10:00:00\n", "2024-02-29 10:00:00",
        "12-31 23:59:59", "01-01 00:00:00", "02-28 10:00:00",
    ]
    # every MM-DD combination against a fixed time: 10,000 inputs, no clock, no I/O
    cases += [f"{m:02d}-{d:02d} 10:00:00" for m in range(100) for d in range(100)]
    for ts in cases:
        out = foundry.parse_log_stamp(ts)  # must not raise
        assert out is None or isinstance(out, dt.datetime), (ts, out)
    # non-vacuous: the census really does contain both verdicts
    assert foundry.parse_log_stamp("02-29 10:00:00") is not None
    assert foundry.parse_log_stamp("13-13 10:00:00") is None


def test_b5_parse_stage_attempts_calls_the_seam_by_bare_name(monkeypatch):
    assert len(foundry.parse_stage_attempts(B1_LOG)) == 1  # control
    monkeypatch.setattr(foundry, "parse_log_stamp", lambda ts: None)
    assert foundry.parse_stage_attempts(B1_LOG) == [], \
        "parse_stage_attempts did not read parse_log_stamp by bare module name"


# --------------------------------------------------------------------------
# Behavior 6 -- _TS_FMT is unchanged, so the strftime emitters keep their shape
# --------------------------------------------------------------------------
def test_b6_ts_fmt_unchanged_and_still_year_less():
    assert foundry._TS_FMT == "%m-%d %H:%M:%S"
    # a FIXED epoch (never today()), formatted through the live constant
    stamp = dt.datetime.fromtimestamp(1_700_000_000).strftime(foundry._TS_FMT)
    assert re.fullmatch(r"\d\d-\d\d \d\d:\d\d:\d\d", stamp), stamp
    assert "2023" not in stamp and "17000" not in stamp
    # and a leap stamp formatted through it round-trips back through the new seam
    leap = dt.datetime(2024, 2, 29, 10, 0, 0).strftime(foundry._TS_FMT)
    assert leap == "02-29 10:00:00"
    assert foundry.parse_log_stamp(leap) is not None


# --------------------------------------------------------------------------
# shape guard: the dataclass contract these expectations are written against
# --------------------------------------------------------------------------
def test_stage_attempt_field_set_is_the_one_asserted():
    assert dataclasses.is_dataclass(foundry.StageAttempt)
    assert tuple(f.name for f in dataclasses.fields(foundry.StageAttempt)) == _FIELDS
    one = foundry.parse_stage_attempts(B1_LOG)[0]
    assert tuple(one.to_dict()) == _FIELDS
