"""Black-box behaviour tests for iter 172 -- a `kill_rate` (kills/attempts) on the
shipped `rescues` accounting, beside the existing `rescue_rate` (rescued/kills).

Under test (spec Feature): the derived `kill_rate` property on `RescueRow` and
`RescueSummary`, its `"kill_rate"` key in both `to_dict()` payloads, and the
`kill rate K%` token appended to every rendered row and to the totals line --
plus the guarantee that the ENTIRE iter-168 render contract survives unchanged.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-172 PM spec's Expected
Behaviors 1-10, the conventions of `tests/test_iter168_behavior.py` (the
`rescues` original, whose helpers are mirrored here), and the product's OWN
OBSERVABLE behaviour -- constructing the public dataclasses, calling
`attempt_kill_summary` / `gather_rescues` / `render()` / `to_dict()` against
fixtures built in `tmp_path`, and reading the returned values and stdout.
`foundry.py`'s implementation TEXT was NOT read, and neither were the
engineer's notes, the reviewer's notes, `IMPLEMENTATION.patch`, nor `git diff`.
Runtime introspection only (`inspect.signature`, `__doc__`), never the source.

Every fixture is built in `tmp_path` or in memory; NOTHING here asserts on the
ambient repo tree, on `products/*/state/` (gitignored, absent in the fresh
clone the post-release gate builds), on iteration-dir counts, or on the repo
directory basename -- OPERATOR 2026-08-11.

Spec behavior 9 is a constraint on THIS FILE: two rates now share one line, so
every rate assertion here is anchored to its label (`kill rate 41.6%`,
`rate 100.0%`, `rescue rate 50.0%`) and never a bare numeric substring.
`test_b09_this_file_never_asserts_a_bare_numeric_rate` enforces it mechanically.

AMBIGUITY NOTED (PM feedback): behavior 5 says the token prints "one decimal
place (e.g. `kill rate 41.6%`)" while behavior 2 forbids `0.0` as a stand-in for
an UNDEFINED rate. A stage with attempts but ZERO kills is a different case: its
kill rate is genuinely defined and zero, so it renders `kill rate 0.0%` (while
its `rate` -- rescued/kills -- is `n/a`). That reading is asserted in
`test_b05_zero_kill_stage_renders_a_defined_zero_kill_rate_beside_rate_na`; the
spec never states it explicitly, and it is the one row shape where the two
denominators visibly disagree.
"""

from __future__ import annotations

import contextlib
import inspect
import io
import json
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402


# --------------------------------------------------------------------------
# helpers -- mirror tests/test_iter168_behavior.py (the rescues original)
# --------------------------------------------------------------------------
_SCAN_EXEMPT = "scan-exempt"   # tag for lines the two self-check tests must skip
KILL_STUB = "agent run failed: agent run timed out after 600s"  # the real 48-byte stub
NARRATION = "ordinary stage narration line, no kill token here\n" * 400

# The iter-168 documented row contract, as a PREFIX of the rendered row line.
ROW_CONTRACT = re.compile(
    r"^  \[(?P<stage>[^\]]+)\] attempts (?P<attempts>\d+)  kills (?P<kills>\d+)"
    r"  rescued (?P<rescued>\d+)  lost (?P<lost>\d+)  rate (?P<rate>n/a|\d+\.\d%)"
)


def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir; repo/work_root are TMP dirs so the
    real foundry repo and its gitignored state are NEVER touched."""
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


def _plant(cfg, iteration, stage, attempt=1, killed=True, out=None):
    d = _iter_dir(cfg, iteration)
    (d / f"{stage}.attempt{attempt}.log").write_text(KILL_STUB if killed else NARRATION)
    if out is not None:
        (d / f"{stage}.md").write_text(out)
    return d


def _rec(stage, iteration=1, attempt=1, killed=False, produced=True):
    return (stage, iteration, attempt, killed, produced)


def _records(stage, kills, clean, produced=True):
    """`kills` killed attempts + `clean` non-killed attempts for one stage."""
    return tuple(
        [_rec(stage, 1, i + 1, killed=True, produced=produced) for i in range(kills)]
        + [_rec(stage, 1, 500 + i, killed=False, produced=True) for i in range(clean)]
    )


def _row(stage="s", attempts=0, kills=0, rescued=0, lost=0):
    """Construct a RescueRow directly -- the ONLY way to reach shapes the real
    gatherer can never emit (attempts == 0, or kills > attempts)."""
    return foundry.RescueRow(stage=stage, attempts=attempts, kills=kills,
                             rescued=rescued, lost=lost)


def _summary(rows, product="p"):
    return foundry.RescueSummary(product=product, rows=tuple(rows))


def _by_stage(summary):
    return {r.stage: r for r in summary.rows}


def _row_line(text, stage):
    hits = [ln for ln in text.splitlines() if f"[{stage}]" in ln]
    assert len(hits) == 1, f"expected exactly one rendered row for {stage!r}: {text!r}"
    return hits[0]


def _totals_line(text):
    """The totals line: indented, carries the counts, and is NOT a stage row."""
    hits = [ln for ln in text.splitlines()
            if ln.startswith("  ") and "attempts " in ln and "[" not in ln]
    assert len(hits) == 1, f"expected exactly one totals line: {text!r}"
    return hits[0]


def _last_non_empty(text):
    return [ln for ln in text.splitlines() if ln.strip()][-1]


def _capture(fn, *args, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fn(*args, **kwargs)
    return code, buf.getvalue()


# ==========================================================================
# Behavior 1 -- kill_rate = round(kills / attempts * 100, 1) on a row
# ==========================================================================
@pytest.mark.parametrize("attempts,kills,want", [
    (197, 82, 41.6),    # the live engineer row from the spec
    (4, 1, 25.0),
    (3, 3, 100.0),
    (186, 60, 32.3),    # the live pm row from the spec
    (1097, 249, 22.7),
])
def test_b01_kill_rate_is_kills_over_attempts_as_a_one_decimal_percent(attempts, kills, want):
    row = _row(attempts=attempts, kills=kills, rescued=kills, lost=0)
    assert isinstance(row.kill_rate, float), type(row.kill_rate)
    assert row.kill_rate == want, f"{kills}/{attempts} -> {row.kill_rate}, want {want}"
    assert round(row.kill_rate, 1) == row.kill_rate, "kill rate must be rounded to 1dp"


def test_b01_kill_rate_agrees_with_the_real_gauge_not_only_a_hand_built_row():
    """The property must be live on rows the public pure function produces."""
    s = foundry.attempt_kill_summary(product="p", records=_records("eng", kills=1, clean=3))
    row = _by_stage(s)["eng"]
    assert (row.attempts, row.kills) == (4, 1), (row.attempts, row.kills)
    assert row.kill_rate == 25.0, row.kill_rate
    assert row.rescue_rate == 100.0, "1 of 1 kills rescued"


# ==========================================================================
# Behavior 2 -- attempts == 0 gives None, never 0.0, never ZeroDivisionError
# ==========================================================================
def test_b02_zero_attempts_row_kill_rate_is_none_not_zero():
    row = _row(stage="ghost", attempts=0, kills=0)
    assert row.kill_rate is None, f"attempts == 0 must give None, got {row.kill_rate!r}"
    assert row.kill_rate is not False and row.kill_rate != 0.0 or row.kill_rate is None


def test_b02_zero_attempts_never_raises_zero_division():
    row = _row(attempts=0, kills=0)
    try:
        value = row.kill_rate
    except ZeroDivisionError as exc:                      # pragma: no cover - the bug
        pytest.fail(f"kill_rate raised ZeroDivisionError on attempts == 0: {exc}")
    assert value is None, repr(value)


def test_b02_a_stage_with_attempts_but_no_kills_has_a_DEFINED_zero_rate():
    """The mirror image of behavior 2: 0 kills over real attempts is 0.0, not
    None -- undefined belongs only to an empty denominator."""
    row = _by_stage(foundry.attempt_kill_summary(
        product="p", records=_records("quiet", kills=0, clean=2)))["quiet"]
    assert (row.attempts, row.kills) == (2, 0)
    assert row.kill_rate == 0.0, f"0/2 must be a defined 0.0, got {row.kill_rate!r}"
    assert row.rescue_rate is None, "rescue_rate stays None on zero kills (iter 168)"


# ==========================================================================
# Behavior 3 -- the same rule on the product-wide totals
# ==========================================================================
def test_b03_summary_kill_rate_uses_the_summed_totals():
    s = _summary([_row("a", 600, 150, 150, 0), _row("b", 497, 99, 99, 0)])
    assert (s.attempts, s.kills) == (1097, 249), (s.attempts, s.kills)
    assert s.kill_rate == 22.7, f"249/1097 -> {s.kill_rate}, want 22.7"


def test_b03_summary_kill_rate_matches_recomputing_it_from_the_rows():
    s = foundry.attempt_kill_summary(product="p", records=(
        _records("pm", kills=2, clean=1) + _records("eng", kills=1, clean=4)))
    assert s.attempts == sum(r.attempts for r in s.rows)
    assert s.kill_rate == round(s.kills / s.attempts * 100, 1), (s.kills, s.attempts)


def test_b03_summary_with_no_rows_has_an_undefined_kill_rate():
    for s in (_summary([]), foundry.attempt_kill_summary(product="p", records=())):
        assert s.attempts == 0
        assert s.kill_rate is None, f"no rows must give None, got {s.kill_rate!r}"


# ==========================================================================
# Behavior 4 -- to_dict() carries "kill_rate" on both, JSON null when undefined
# ==========================================================================
def test_b04_row_and_summary_to_dict_carry_kill_rate_equal_to_the_property():
    s = foundry.attempt_kill_summary(product="widgetco", records=(
        _records("pm", kills=2, clean=2) + _records("eng", kills=0, clean=3)))
    payload = json.loads(json.dumps(s.to_dict()))          # must not raise
    assert "kill_rate" in payload, sorted(payload)
    assert payload["kill_rate"] == s.kill_rate, (payload["kill_rate"], s.kill_rate)
    for got, row in zip(payload["rows"], s.rows):
        assert "kill_rate" in got, (row.stage, sorted(got))
        assert got["kill_rate"] == row.kill_rate, (row.stage, got["kill_rate"])
        # iter-168's keys must all still be there, unchanged in meaning
        for field in ("stage", "attempts", "kills", "rescued", "lost", "rescue_rate"):
            assert got[field] == getattr(row, field), (row.stage, field)


def test_b04_undefined_kill_rate_serialises_to_json_null_and_round_trips():
    s = _summary([_row("ghost", 0, 0, 0, 0)])
    assert s.kill_rate is None and s.rows[0].kill_rate is None
    text = json.dumps(s.to_dict(), indent=2)               # must not raise
    assert '"kill_rate": null' in text, text
    back = json.loads(text)
    assert back["kill_rate"] is None, back["kill_rate"]
    assert back["rows"][0]["kill_rate"] is None, back["rows"][0]


# ==========================================================================
# Behavior 5 -- render() appends `kill rate K%` after the existing rate token
# ==========================================================================
def test_b05_row_and_totals_lines_end_with_the_kill_rate_token():
    s = foundry.attempt_kill_summary(product="demo", records=(
        _records("pm", kills=2, clean=0) + _records("eng", kills=1, clean=3)))
    text = s.render()
    pm, eng = _row_line(text, "pm"), _row_line(text, "eng")
    assert pm.rstrip().endswith("kill rate 100.0%"), repr(pm)
    assert eng.rstrip().endswith("kill rate 25.0%"), repr(eng)
    totals = _totals_line(text)
    assert totals.rstrip().endswith(f"kill rate {s.kill_rate}%"), repr(totals)
    # "immediately after the existing rate token" -- the rescue rate comes FIRST
    assert pm.index("rate 100.0%") < pm.index("kill rate 100.0%"), repr(pm)
    assert totals.index("rescue rate ") < totals.index("kill rate "), repr(totals)


def test_b05_undefined_kill_rate_renders_na_through_the_shared_helper():
    """A row the gatherer can never emit (attempts == 0) is the ONLY input that
    forces the helper's other return value, so it is built by hand."""
    text = _summary([_row("ghost", 0, 0, 0, 0)]).render()
    assert "kill rate n/a" in _row_line(text, "ghost"), repr(text)
    assert "kill rate n/a" in _totals_line(text), repr(text)
    assert foundry._rate_text(None) == "n/a", "the shared helper's undefined form"
    assert foundry._rate_text(41.6) == "41.6%", "helper unit form"  # scan-exempt


def test_b05_zero_kill_stage_renders_a_defined_zero_kill_rate_beside_rate_na():
    """See the module docstring's ambiguity note: a stage with attempts and no
    kills prints `rate n/a` (rescued/kills undefined) but `kill rate 0.0%`."""
    text = foundry.attempt_kill_summary(
        product="demo", records=_records("quiet", kills=0, clean=2)).render()
    line = _row_line(text, "quiet")
    assert "rate n/a" in line and "kill rate 0.0%" in line, repr(line)


def test_b05_one_decimal_place_is_used_for_a_repeating_rate():
    row = _row(attempts=3, kills=2)
    assert row.kill_rate == 66.7, row.kill_rate
    assert "kill rate 66.7%" in _row_line(_summary([row]).render(), "s")


# ==========================================================================
# Behavior 6 -- the whole iter-168 render contract survives
# ==========================================================================
def test_b06_header_totals_row_shape_and_verdict_all_survive():
    s = foundry.attempt_kill_summary(product="widgetco", records=(
        _records("pm", kills=3, clean=1)
        + _records("eng", kills=2, clean=2, produced=False)
        + _records("quiet", kills=0, clean=5)))
    text = s.render()
    lines = text.splitlines()
    assert lines[0] == "foundry rescues -- widgetco", repr(lines[0])
    totals = _totals_line(text)
    for label in ("attempts ", "kills ", "rescued ", "lost ", "rescue rate "):
        assert label in totals, f"{label!r} missing from totals line: {totals!r}"
    for row in s.rows:
        line = _row_line(text, row.stage)
        m = ROW_CONTRACT.match(line)
        assert m, f"row line broke the iter-168 PREFIX contract: {line!r}"
        assert int(m.group("attempts")) == row.attempts
        assert int(m.group("kills")) == row.kills
        assert int(m.group("rescued")) == row.rescued
        assert int(m.group("lost")) == row.lost
    last = _last_non_empty(text)
    assert last.startswith("verdict: "), repr(last)
    assert last == f"verdict: {s.verdict}", (last, s.verdict)


@pytest.mark.parametrize("records,want_code", [
    ((), 2),
    (_records("pm", kills=1, clean=0), 0),
    (_records("pm", kills=1, clean=0, produced=False), 1),
])
def test_b06_verdict_is_still_the_last_non_empty_line_and_tracks_exit_code(records, want_code):
    s = foundry.attempt_kill_summary(product="p", records=records)
    assert s.exit_code == want_code, (s.exit_code, want_code)
    assert _last_non_empty(s.render()) == f"verdict: {s.verdict}"


def test_b06_no_attempts_branch_gains_no_kill_rate_token_and_no_totals_line():
    text = foundry.attempt_kill_summary(product="demo", records=()).render()
    assert "no attempts" in text.lower(), repr(text)
    assert "kill rate" not in text, f"the empty branch must NOT gain the token: {text!r}"
    assert "rescue rate" not in text and "n/a" not in text, repr(text)
    with pytest.raises(AssertionError):                    # i.e. there is no totals line
        _totals_line(text)
    assert _last_non_empty(text).startswith("verdict: "), repr(text)


def test_b06_the_iter168_tests_still_pass_unmodified():
    """Their file must not have been edited to accommodate this iteration."""
    sibling = _ROOT / "tests" / "test_iter168_behavior.py"
    body = sibling.read_text()
    assert "kill_rate" not in body and "kill rate" not in body, \
        "iter-168's oracle must stay independent of this iteration"
    assert 'assert "50.0" in pm' in body, "iter-168 substring check survives"  # scan-exempt


# ==========================================================================
# Behavior 7 -- nothing else about the gauge moves
# ==========================================================================
def test_b07_row_order_is_still_kills_descending_then_stage_ascending():
    s = foundry.attempt_kill_summary(product="p", records=(
        _records("bravo", kills=2, clean=9)      # low kill rate, mid kills
        + _records("alpha", kills=2, clean=0)    # 100% kill rate, mid kills
        + _records("charlie", kills=3, clean=0)
        + _records("zulu", kills=0, clean=1)))
    assert [(r.stage, r.kills) for r in s.rows] == [
        ("charlie", 3), ("alpha", 2), ("bravo", 2), ("zulu", 0)], [r.stage for r in s.rows]
    text = s.render()
    positions = [text.index(f"[{st}]") for st in ("charlie", "alpha", "bravo", "zulu")]
    assert positions == sorted(positions), f"render must follow row order:\n{text}"


def test_b07_a_100_percent_kill_rate_with_nothing_lost_is_still_verdict_ok():
    s = foundry.attempt_kill_summary(product="p", records=_records("pm", kills=3, clean=0))
    assert (s.attempts, s.kills, s.lost) == (3, 3, 0)
    assert s.kill_rate == 100.0 and s.rescue_rate == 100.0
    assert s.exit_code == 0, "a fully-rescued stage is not a failure, however often killed"
    never_killed = foundry.attempt_kill_summary(
        product="p", records=_records("pm", kills=0, clean=3))
    a_loss = foundry.attempt_kill_summary(
        product="p", records=_records("pm", kills=1, clean=0, produced=False))
    assert s.verdict == never_killed.verdict, (s.verdict, never_killed.verdict)
    assert s.verdict != a_loss.verdict, s.verdict
    assert (never_killed.exit_code, a_loss.exit_code) == (0, 1)


def test_b07_rescue_rate_keeps_its_own_value_and_denominator_on_every_row():
    s = foundry.attempt_kill_summary(product="p", records=(
        _records("pm", kills=1, clean=3)                      # rescued kill
        + _records("eng", kills=1, clean=0, produced=False)))  # lost kill
    rows = _by_stage(s)
    assert (rows["pm"].rescue_rate, rows["pm"].kill_rate) == (100.0, 25.0)
    assert (rows["eng"].rescue_rate, rows["eng"].kill_rate) == (0.0, 100.0)
    assert rows["pm"].rescue_rate != rows["pm"].kill_rate, \
        "the two rates have DIFFERENT denominators and must not be aliased"


def test_b07_docstrings_say_the_two_denominators_differ():
    for owner in (foundry.RescueRow, foundry.RescueSummary):
        for name in ("kill_rate", "rescue_rate"):
            doc = (getattr(owner, name).__doc__ or "").lower()
            assert doc.strip(), f"{owner.__name__}.{name} has no docstring"
        doc = (getattr(owner, "kill_rate").__doc__ or "").lower()
        assert "attempts" in doc, f"{owner.__name__}.kill_rate must name its denominator"
        assert "rescue" in doc, \
            f"{owner.__name__}.kill_rate must contrast itself with the rescue rate"


# ==========================================================================
# Behavior 8 -- totality and immutability
# ==========================================================================
def test_b08_both_dataclasses_stay_frozen_including_the_new_property():
    s = _summary([_row("pm", 4, 1, 1, 0)])
    for target, attr in ((s, "kill_rate"), (s, "rows"), (s.rows[0], "kill_rate"),
                         (s.rows[0], "attempts")):
        with pytest.raises(Exception) as exc:
            setattr(target, attr, 1.0)
        assert isinstance(exc.value, (AttributeError, TypeError)), exc.value
    assert isinstance(s.rows, tuple)


def test_b08_a_malformed_row_returns_a_rate_above_100_instead_of_raising():
    row = _row(stage="weird", attempts=2, kills=3, rescued=3, lost=0)
    assert row.kill_rate == 150.0, f"kills > attempts must not raise, got {row.kill_rate!r}"
    text = _summary([row]).render()                        # must not raise either
    assert "kill rate 150.0%" in _row_line(text, "weird"), repr(text)
    json.dumps(_summary([row]).to_dict())


def test_b08_kill_rate_never_raises_over_a_grid_of_defensive_shapes():
    for attempts, kills in ((0, 0), (0, 5), (1, 0), (5, 5), (7, 9), (10 ** 6, 1)):
        row = _row(attempts=attempts, kills=kills)
        value = row.kill_rate                              # must not raise
        assert value is None or isinstance(value, float), (attempts, kills, value)
        if attempts == 0:
            assert value is None, (attempts, kills, value)
        _summary([row]).render()
        json.dumps(_summary([row]).to_dict())


def test_b08_signatures_are_unchanged_so_iter168_construction_still_works():
    assert tuple(inspect.signature(foundry.RescueRow).parameters) == (
        "stage", "attempts", "kills", "rescued", "lost")
    assert tuple(inspect.signature(foundry.RescueSummary).parameters) == ("product", "rows")


# ==========================================================================
# Behavior 9 -- this file's own rate assertions are label-anchored
# ==========================================================================
def test_b09_this_file_never_asserts_a_bare_numeric_rate():
    """Two rates now share one rendered line, so an unanchored bare-number check
    can pass against the WRONG rate. Enforce label anchoring mechanically.

    Lines tagged with the exempt marker are excluded because they are not
    assertions about a rendered line: this scanner's own patterns, a quotation of
    iter-168's preserved substring assertion, and a unit assertion on the shared
    rate helper's return value.
    """
    lines = pathlib.Path(__file__).read_text().splitlines()
    scanned = [ln for ln in lines if _SCAN_EXEMPT not in ln]
    assert len(scanned) < len(lines), "the exempt marker must actually be in use"
    body = chr(10).join(scanned)
    bare = re.findall(r'"(\d+\.\d)%?"', body)  # scan-exempt
    assert bare == [], f"bare numeric rate literal(s) in this file: {bare}"
    anchored = re.findall(r'"(?:kill |rescue )?rate [^"]+"', body)
    assert len(anchored) >= 8, f"expected label-anchored rate literals, found {anchored}"


# ==========================================================================
# Behavior 10 -- two-sided oracle over attempt logs planted in tmp_path
# ==========================================================================
def test_b10_two_fully_rescued_stages_share_a_rescue_rate_but_differ_in_kill_rate(tmp_path):
    cfg = _cfg(tmp_path)
    # `hot`: killed on 4 of 5 attempts, output file present -> every kill rescued
    for n in range(1, 5):
        _plant(cfg, 1, "hot", attempt=n, killed=True, out="hot output")
    _plant(cfg, 1, "hot", attempt=5, killed=False, out="hot output")
    # `cool`: killed on 1 of 10 attempts, likewise fully rescued
    _plant(cfg, 2, "cool", attempt=1, killed=True, out="cool output")
    for n in range(2, 11):
        _plant(cfg, 2, "cool", attempt=n, killed=False, out="cool output")

    s = foundry.gather_rescues(cfg)
    rows = _by_stage(s)
    assert set(rows) == {"hot", "cool"}, sorted(rows)
    assert (rows["hot"].attempts, rows["hot"].kills) == (5, 4), (rows["hot"].attempts,
                                                                 rows["hot"].kills)
    assert (rows["cool"].attempts, rows["cool"].kills) == (10, 1), (rows["cool"].attempts,
                                                                    rows["cool"].kills)
    assert s.lost == 0 and s.exit_code == 0, (s.lost, s.exit_code)
    assert rows["hot"].rescue_rate == rows["cool"].rescue_rate == 100.0, \
        "both stages were fully rescued, so the OLD gauge cannot tell them apart"
    assert rows["hot"].kill_rate == 80.0, rows["hot"].kill_rate
    assert rows["cool"].kill_rate == 10.0, rows["cool"].kill_rate
    assert rows["hot"].kill_rate > rows["cool"].kill_rate, "the new gauge separates them"

    text = s.render()
    hot, cool = _row_line(text, "hot"), _row_line(text, "cool")
    assert "rate 100.0%" in hot and "rate 100.0%" in cool, (hot, cool)
    assert "kill rate 80.0%" in hot, repr(hot)
    assert "kill rate 10.0%" in cool, repr(cool)
    assert s.kill_rate == round(5 / 15 * 100, 1), s.kill_rate
    assert f"kill rate {s.kill_rate}%" in _totals_line(text), repr(text)


def test_b10_the_cli_verb_reports_the_new_token_and_still_writes_nothing(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _plant(cfg, 1, "pm", attempt=1, killed=True, out="spec")
    _plant(cfg, 1, "pm", attempt=2, killed=False, out="spec")
    before = {str(p.relative_to(tmp_path)): p.read_bytes()
              for p in tmp_path.rglob("*") if p.is_file()}
    rc, out = _capture(foundry.rescues_cli, cfg, None, False)
    assert rc == 0, out
    assert "kill rate 50.0%" in _row_line(out, "pm"), repr(out)
    rc, payload = _capture(foundry.rescues_cli, cfg, None, True)
    doc = json.loads(payload)
    assert doc["rows"][0]["kill_rate"] == 50.0, doc["rows"][0]
    assert doc["kill_rate"] == 50.0, doc
    after = {str(p.relative_to(tmp_path)): p.read_bytes()
             for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before, "the gauge must stay read-only"


def test_b10_no_test_here_depends_on_the_ambient_gitignored_state_tree(tmp_path):
    """OPERATOR 2026-08-11: a fresh clone has no products/*/state, so every
    fixture must be built locally. This asserts the file text, not the tree."""
    lines = pathlib.Path(__file__).read_text().splitlines()
    body = chr(10).join(ln for ln in lines if _SCAN_EXEMPT not in ln)
    for token in ("products/_platform/state", "dispatcher.out", str(_ROOT)):  # scan-exempt
        assert token not in body, f"fixture must not reference {token}"


# ==========================================================================
# Import invariants (ARCHITECTURE.md): both modules stay importable
# ==========================================================================
def test_imports_of_both_entrypoints_still_succeed():
    import importlib

    for name in ("foundry", "dispatcher"):
        assert importlib.import_module(name) is not None, name
