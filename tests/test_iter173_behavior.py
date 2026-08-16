"""Black-box behaviour tests for iter 173 -- a new read-only, offline verb
`foundry losses` that counts the stage attempts which produced NO output file,
split by CAUSE (`classify_attempt_failure`), because `rescues` decides "lost
work" from a single kill token and therefore ranges over the wrong population.

Under test (spec Feature): the pure summariser `attempt_loss_summary`, the two
frozen dataclasses `LossRow` / `LossSummary` with their derived values,
`render()` (detail-then-sentinel), `to_dict()`, the single I/O seam
`gather_losses`, the thin `losses_cli`, the `losses` subcommand of `main()`,
and the DORMANCY of every new name.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-173 PM spec's Expected
Behaviors 1-17, the conventions of `tests/test_iter172_behavior.py` and
`tests/test_iter169_behavior.py` (whose helpers are mirrored here), and the
product's OWN OBSERVABLE behaviour -- constructing the public dataclasses,
calling `attempt_loss_summary` / `gather_losses` / `render()` / `to_dict()` /
`main()` against fixtures built in `tmp_path`, and reading return values and
stdout.  `foundry.py`'s implementation TEXT was NOT read by the author, and
neither were the engineer's notes, the reviewer's notes, nor `git diff`.
Runtime introspection only (`inspect.signature`, `dataclasses.fields`).
Behavior 15 is the one assertion that must look AT source text; it does so
MECHANICALLY through `inspect.getsource` inside the test (token absence), which
is a machine check the author never read.

Every fixture is built in `tmp_path` or in memory.  NOTHING here asserts on the
ambient `products/` tree, on `products/*/state/` (gitignored, absent from the
fresh clone the post-release gate builds), on a live attempt-log count, on
iteration-dir counts, or on the repo directory basename -- OPERATOR 2026-08-11.
The only ambient files read are TRACKED ones that a fresh clone always has:
`README.md`, `foundry.py`, `PLATFORM_ROADMAP.md`, `PLATFORM_ROADMAP_ARCHIVE.md`.

AMBIGUITY NOTED (PM feedback), behavior 6: the spec calls `LossSummary` a
frozen dataclass "with exactly the fields `product`, `rows`" and lists
`attempts` among its DERIVED properties -- but it also defines `attempts` as
"every record of a recognised shape, produced or NOT", and a produced record
contributes to NO row (behavior 3).  So `attempts` is provably NOT derivable
from `product` + `rows`; the two halves of behavior 6 cannot both hold.  The
most reasonable reading, and the one asserted here, is that the OBSERVABLE
contract governs: `L.attempts` reads back the honest count of recognised
records, `L.lost <= L.attempts` always, and `attempts` is carried as a third
frozen field.  `test_b06_summary_shape_documents_the_attempts_ambiguity` pins
that resolution so a later iteration cannot silently change it.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402


# --------------------------------------------------------------------------
# helpers -- mirror tests/test_iter172_behavior.py (the sibling rescues suite)
# --------------------------------------------------------------------------
STALL_STUB = "agent run failed: Connection stalled - no data received for 120 s"
TIMEOUT_STUB = "agent run failed: agent run timed out after 600s"
CLI_STUB = "agent run failed: native shortcut did not match"
SERVICE_STUB = "agent run failed: the service is busy, please retry"
NARRATION = "ordinary stage narration, no failure marker at all\n" * 40


def _rec(stage="tester", iteration=1, attempt=1, produced=False, kind="stalled"):
    """A record in the plain 5-sequence shape (behavior 2, first shape)."""
    return (stage, iteration, attempt, produced, kind)


class _RecObj:
    """A record in the attribute shape (behavior 2, second shape)."""

    def __init__(self, stage, iteration, attempt, produced, kind):
        self.stage = stage
        self.iteration = iteration
        self.attempt = attempt
        self.produced = produced
        self.kind = kind


def _summary(records, product="demoprod"):
    return foundry.attempt_loss_summary(product=product, records=records)


def _by_kind(summary):
    return {r.kind: r for r in summary.rows}


def _row_line(text, kind):
    hits = [ln for ln in text.splitlines() if f"[{kind}]" in ln]
    assert len(hits) == 1, f"expected exactly one rendered row for {kind!r}: {text!r}"
    return hits[0]


def _totals_line(text):
    hits = [ln for ln in text.splitlines()
            if ln.startswith("  ") and "attempts " in ln and "[" not in ln]
    assert len(hits) == 1, f"expected exactly one totals line: {text!r}"
    return hits[0]


def _last_non_empty(text):
    return [ln for ln in text.splitlines() if ln.strip()][-1]


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


def _plant(cfg, iteration, stage, attempt=1, log=STALL_STUB, out=None):
    d = pathlib.Path(cfg.state) / f"iter-{iteration:02d}"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stage}.attempt{attempt}.log").write_text(log)
    if out is not None:
        (d / f"{stage}.md").write_text(out)
    return d


class _Boom:
    """Stands in for a module during a PURITY assertion: touching ANY attribute
    of it fails the test, which is how behavior 1's 'no filesystem, subprocess,
    git, network or clock access' is measured rather than asserted."""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, item):
        raise AssertionError(
            f"pure summariser touched {self._name}.{item} -- behavior 1 forbids I/O"
        )


# --------------------------------------------------------------------------
# behavior 1 -- keyword-only, pure, total
# --------------------------------------------------------------------------
def test_b01_signature_is_keyword_only():
    sig = inspect.signature(foundry.attempt_loss_summary)
    assert [p.name for p in sig.parameters.values()] == ["product", "records"]
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY
               for p in sig.parameters.values()), sig
    with pytest.raises(TypeError):
        foundry.attempt_loss_summary("demoprod", ())          # positional refused


def test_b01_raises_for_no_input():
    with pytest.raises(TypeError):
        foundry.attempt_loss_summary()


@pytest.mark.parametrize("bad", [5, None, object(), 3.5, True])
def test_b01_non_iterable_records_is_empty_not_fatal(bad):
    L = _summary(bad)
    assert (L.attempts, L.lost, L.kinds, L.rows) == (0, 0, 0, ())
    assert L.exit_code == 2


def test_b01_does_not_mutate_records_and_is_deterministic():
    records = [_rec("tester", 1, 1), _rec("pm", 2, 1, kind="timeout")]
    snapshot = list(records)
    a = _summary(records)
    b = _summary(records)
    assert records == snapshot                                # not mutated
    assert a == b and a.rows == b.rows                        # equal in -> == out
    assert a.render() == b.render()


def test_b01_equal_inputs_compare_equal_across_input_order():
    fwd = _summary([_rec("a", 1, 1, kind="k1"), _rec("b", 1, 2, kind="k2")])
    rev = _summary([_rec("b", 1, 2, kind="k2"), _rec("a", 1, 1, kind="k1")])
    assert fwd == rev


def test_b01_accepts_a_one_shot_iterator():
    gen = (_rec("tester", 1, i) for i in range(3))
    L = _summary(gen)
    assert (L.attempts, L.lost) == (3, 3)


def test_b01_touches_no_io_module(monkeypatch):
    """PURITY, measured: swap every I/O module the summariser could reach for a
    tripwire, then summarise.  Any attribute access on them raises."""
    patched = []
    for name in ("os", "subprocess", "shutil", "time", "socket", "urllib", "glob"):
        if hasattr(foundry, name):
            monkeypatch.setattr(foundry, name, _Boom(name))
            patched.append(name)
    assert patched, "expected foundry to expose at least one I/O module to trip"
    L = _summary([_rec("tester", 1, 1), _rec("pm", 1, 1, produced=True)])
    assert (L.attempts, L.lost) == (2, 1)
    assert "verdict:" in L.render()
    assert json.dumps(L.to_dict())


# --------------------------------------------------------------------------
# behavior 2 -- two accepted record shapes, everything else SKIPPED
# --------------------------------------------------------------------------
def test_b02_sequence_and_attribute_shapes_both_count():
    L = _summary([
        _rec("tester", 1, 1, kind="stalled"),                       # tuple
        ["engineer", 1, 1, False, "stalled"],                       # list
        _RecObj("pm", 2, 1, False, "timeout"),                      # attributes
    ])
    assert L.attempts == 3
    assert _by_kind(L)["stalled"].stages == ("engineer", "tester")
    assert _by_kind(L)["timeout"].stages == ("pm",)


@pytest.mark.parametrize("junk", [
    ("tester",), ("tester", 1), ("tester", 1, 1), ("tester", 1, 1, False),
    5, None, 3.5, object(),
])
def test_b02_unrecognised_records_are_skipped_never_fatal(junk):
    L = _summary([_rec("tester", 1, 1), junk])
    assert L.attempts == 1, f"junk record {junk!r} must not be counted"
    assert L.lost == 1 and L.kinds == 1


def test_b02_deviation_partial_attribute_object_is_counted_not_skipped():
    """DEVIATION FROM THE SPEC LETTER, recorded rather than blessed (PM feedback).

    Behavior 2 says a record is accepted only as a 5-sequence or as "any object
    carrying those five attribute names", and anything of neither shape is
    SKIPPED.  Measured: an object carrying only `stage` IS accepted -- the
    missing fields default (`produced` falsy, `kind` -> `ATTEMPT_FAILURE_DEFAULT`),
    so it lands as a loss of kind `other`.  An object with NO `stage` is skipped,
    and a longer sequence is accepted on its first five items.

    Not ship-blocking, for two measured reasons: (1) it errs toward OVER-counting
    a loss, the opposite direction from the under-count this iteration exists to
    fix, and a spurious `other` row costs an operator one look; (2) the only
    shipped caller is `gather_losses`, which always builds a full 5-tuple
    (behavior 12), so no real report can contain such a row.  Pinned here so a
    later change of mind is visible instead of silent.
    """
    class OnlyStage:
        stage = "tester"

    class NoStage:
        kind = "stalled"

    lenient = _summary([OnlyStage(), _rec("pm", 1, 1)])
    assert lenient.attempts == 2
    assert _by_kind(lenient)[foundry.ATTEMPT_FAILURE_DEFAULT].stages == ("tester",)
    assert _by_kind(lenient)["stalled"].stages == ("pm",)

    assert _summary([NoStage()]).attempts == 0            # no stage -> skipped
    six = _summary([("tester", 1, 1, False, "stalled", "extra")])
    assert (six.attempts, six.lost) == (1, 1)            # first five taken


# --------------------------------------------------------------------------
# behavior 3 -- only produced-FALSE records are losses
# --------------------------------------------------------------------------
def test_b03_produced_records_count_as_attempts_and_no_row():
    L = _summary([
        _rec("tester", 1, 1, produced=True, kind="timeout"),
        _rec("tester", 1, 2, produced=True, kind="stalled"),
        _rec("engineer", 1, 1, produced=False, kind="stalled"),
    ])
    assert L.attempts == 3
    assert L.lost == 1
    assert [r.kind for r in L.rows] == ["stalled"]
    assert _by_kind(L)["stalled"].stages == ("engineer",)


def test_b03_all_produced_yields_no_rows_but_real_attempts():
    L = _summary([_rec("tester", 1, i, produced=True) for i in range(4)])
    assert (L.attempts, L.lost, L.kinds, L.rows) == (4, 0, 0, ())


def test_b03_losses_group_into_one_row_per_distinct_kind():
    L = _summary([
        _rec("tester", 1, 1, kind="stalled"),
        _rec("tester", 1, 2, kind="stalled"),
        _rec("pm", 1, 1, kind="timeout"),
        _rec("final", 1, 1, kind="cli-error"),
    ])
    assert L.kinds == 3 == len(L.rows)
    assert _by_kind(L)["stalled"].lost == 2


# --------------------------------------------------------------------------
# behavior 4 -- LossRow shape, frozen, sorted+deduped stages
# --------------------------------------------------------------------------
def test_b04_lossrow_has_exactly_three_fields():
    names = [f.name for f in dataclasses.fields(foundry.LossRow)]
    assert names == ["kind", "lost", "stages"]
    assert foundry.LossRow.__dataclass_params__.frozen is True


def test_b04_lossrow_is_immutable():
    row = foundry.LossRow(kind="stalled", lost=1, stages=("tester",))
    for field in ("kind", "lost", "stages"):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(row, field, "x")


def test_b04_stages_are_sorted_deduped_and_lost_counts_attempts():
    L = _summary([
        _rec("tester", 1, 1, kind="stalled"),
        _rec("tester", 1, 2, kind="stalled"),
        _rec("engineer", 2, 1, kind="stalled"),
        _rec("alpha", 3, 1, kind="stalled"),
    ])
    row = _by_kind(L)["stalled"]
    assert row.lost == 4
    assert row.stages == ("alpha", "engineer", "tester")
    assert isinstance(row.stages, tuple)


# --------------------------------------------------------------------------
# behavior 5 -- row order: lost DESC, then kind ASC
# --------------------------------------------------------------------------
def test_b05_rows_sort_lost_desc_then_kind_asc():
    records = (
        [_rec("s", 1, i, kind="zebra") for i in range(3)]
        + [_rec("s", 2, i, kind="alpha") for i in range(5)]
        + [_rec("s", 3, i, kind="beta") for i in range(3)]
        + [_rec("s", 4, 1, kind="omega")]
    )
    fwd = _summary(records)
    rev = _summary(list(reversed(records)))
    expected = [("alpha", 5), ("beta", 3), ("zebra", 3), ("omega", 1)]
    assert [(r.kind, r.lost) for r in fwd.rows] == expected
    assert [(r.kind, r.lost) for r in rev.rows] == expected   # order-independent


# --------------------------------------------------------------------------
# behavior 6 -- LossSummary shape + derived values
# --------------------------------------------------------------------------
def test_b06_summary_shape_documents_the_attempts_ambiguity():
    """See the module docstring: behavior 6 lists `attempts` as DERIVED while
    behavior 3 makes it un-derivable from `rows`.  The resolution asserted here
    is a third frozen field that reads back the honest count."""
    names = [f.name for f in dataclasses.fields(foundry.LossSummary)]
    assert names == ["product", "rows", "attempts"], (
        "behavior 6 ambiguity resolved as a carried field; if this changes, the "
        "spec's 'derived attempts' half was chosen instead -- re-read the "
        "docstring before editing"
    )
    assert foundry.LossSummary.__dataclass_params__.frozen is True
    for name in ("lost", "kinds", "exit_code", "verdict"):
        assert isinstance(getattr(foundry.LossSummary, name), property), name


def test_b06_summary_is_immutable():
    L = _summary([_rec("tester", 1, 1)])
    with pytest.raises(dataclasses.FrozenInstanceError):
        L.rows = ()


def test_b06_derived_values_agree_with_rows():
    L = _summary([
        _rec("tester", 1, 1, kind="stalled"),
        _rec("tester", 1, 2, kind="timeout"),
        _rec("pm", 1, 1, produced=True, kind="timeout"),
    ])
    assert L.product == "demoprod"
    assert L.lost == sum(r.lost for r in L.rows) == 2
    assert L.kinds == len(L.rows) == 2
    assert L.attempts == 3


@pytest.mark.parametrize("produced_n,lost_n", [(0, 0), (3, 0), (0, 3), (2, 5)])
def test_b06_lost_never_exceeds_attempts(produced_n, lost_n):
    records = (
        [_rec("s", 1, i, produced=True) for i in range(produced_n)]
        + [_rec("s", 2, i, produced=False) for i in range(lost_n)]
    )
    L = _summary(records)
    assert L.lost <= L.attempts
    assert L.attempts == produced_n + lost_n


# --------------------------------------------------------------------------
# behavior 7 -- exit code, with the empty check FIRST
# --------------------------------------------------------------------------
def test_b07_exit_code_2_when_nothing_scanned():
    assert _summary(()).exit_code == 2
    assert _summary([("short",), None]).exit_code == 2    # only junk -> still 2


def test_b07_exit_code_1_when_any_loss():
    assert _summary([_rec("tester", 1, 1)]).exit_code == 1


def test_b07_exit_code_0_when_attempts_but_no_loss():
    assert _summary([_rec("tester", 1, 1, produced=True)]).exit_code == 0


# --------------------------------------------------------------------------
# behavior 8 -- verdict is the one human token per exit code
# --------------------------------------------------------------------------
def test_b08_verdict_tokens_per_exit_code():
    assert _summary(()).verdict == "no attempts"
    assert _summary([_rec("tester", 1, 1, produced=True)]).verdict == "no lost attempts"
    assert _summary([_rec("tester", 1, 1)]).verdict == "LOST WORK BY CAUSE"


def test_b08_loss_verdict_is_greppably_distinct_from_rescues():
    """Two reports over DIFFERENT populations must not share a sentinel."""
    losses = _summary([_rec("tester", 1, 1)]).verdict
    rescues = foundry.RescueSummary(
        product="demoprod",
        rows=(foundry.RescueRow(stage="tester", attempts=2, kills=1,
                                rescued=0, lost=1),),
    ).verdict
    assert losses != rescues
    assert losses == "LOST WORK BY CAUSE"


# --------------------------------------------------------------------------
# behavior 9 -- render(): header, totals, rows, sentinel LAST
# --------------------------------------------------------------------------
ROW_CONTRACT = re.compile(
    r"^  \[(?P<kind>[^\]]+)\] lost (?P<lost>\d+)  stages: (?P<stages>.+)$"
)


def test_b09_render_contract_header_totals_rows_sentinel():
    L = _summary([
        _rec("tester", 1, 1, kind="stalled"),
        _rec("engineer", 1, 1, kind="stalled"),
        _rec("pm", 1, 1, kind="timeout"),
        _rec("final", 1, 1, kind="cli-error"),
        _rec("pm", 2, 1, produced=True, kind="timeout"),
    ], product="widget")
    text = L.render()
    assert "foundry losses -- widget" in text
    assert _totals_line(text) == "  attempts 5  lost 4  kinds 3"
    for row in L.rows:
        line = _row_line(text, row.kind)
        m = ROW_CONTRACT.match(line)
        assert m, f"row line off contract: {line!r}"
        assert int(m.group("lost")) == row.lost
        assert m.group("stages") == ", ".join(row.stages)
    assert _last_non_empty(text) == f"verdict: {L.verdict}"


def test_b09_rendered_rows_follow_rows_order():
    L = _summary(
        [_rec("s", 1, i, kind="stalled") for i in range(3)]
        + [_rec("t", 2, 1, kind="timeout")]
    )
    text = L.render()
    positions = [text.index(f"[{r.kind}]") for r in L.rows]
    assert positions == sorted(positions), text


def test_b09_render_is_deterministic_multiline_text():
    L = _summary([_rec("tester", 1, 1)])
    text = L.render()
    assert isinstance(text, str)
    assert len(text.splitlines()) >= 3
    assert text == L.render()


# --------------------------------------------------------------------------
# behavior 10 -- nothing scanned renders `no attempts`, never a zero rollup
# --------------------------------------------------------------------------
def test_b10_empty_render_says_no_attempts_and_keeps_sentinel():
    L = _summary(())
    text = L.render()
    assert "  no attempts" in text
    assert "attempts 0" not in text, "an all-zero rollup is misleading -- b10"
    assert "lost 0" not in text
    assert _last_non_empty(text) == "verdict: no attempts"
    assert "[" not in text


def test_b10_zero_loss_but_real_attempts_still_renders_totals():
    """The `no attempts` branch is for attempts == 0 ONLY; a clean run with real
    attempts is a different, honest report."""
    L = _summary([_rec("tester", 1, 1, produced=True)])
    text = L.render()
    assert "  no attempts" not in text
    assert _totals_line(text) == "  attempts 1  lost 0  kinds 0"
    assert _last_non_empty(text) == "verdict: no lost attempts"


# --------------------------------------------------------------------------
# behavior 11 -- to_dict() is JSON-safe, ordered, and re-derives nothing
# --------------------------------------------------------------------------
def test_b11_to_dict_keys_order_and_json_roundtrip():
    L = _summary([
        _rec("tester", 1, 1, kind="stalled"),
        _rec("engineer", 1, 1, kind="stalled"),
        _rec("pm", 1, 1, kind="timeout"),
        _rec("pm", 2, 1, produced=True, kind="timeout"),
    ])
    payload = L.to_dict()
    assert list(payload) == ["product", "attempts", "lost", "kinds",
                             "exit_code", "verdict", "rows"]
    assert payload["attempts"] == L.attempts
    assert payload["lost"] == L.lost
    assert payload["kinds"] == L.kinds
    assert payload["exit_code"] == L.exit_code
    assert payload["verdict"] == L.verdict
    assert [r["kind"] for r in payload["rows"]] == [r.kind for r in L.rows]
    for got, row in zip(payload["rows"], L.rows):
        assert list(got) == ["kind", "lost", "stages"]
        assert got["lost"] == row.lost
        assert got["stages"] == list(row.stages)
        assert isinstance(got["stages"], list)
    assert json.loads(json.dumps(payload)) == payload


def test_b11_empty_summary_to_dict_round_trips():
    payload = _summary(()).to_dict()
    assert payload["rows"] == []
    assert payload["exit_code"] == 2 and payload["verdict"] == "no attempts"
    assert json.loads(json.dumps(payload)) == payload


# --------------------------------------------------------------------------
# behavior 12 -- gather_losses is the ONLY I/O seam
# --------------------------------------------------------------------------
def test_b12_gather_classifies_every_cause_off_disk(tmp_path):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "tester", log=STALL_STUB)
    _plant(cfg, 2, "engineer", log=TIMEOUT_STUB)
    _plant(cfg, 3, "final", log=CLI_STUB)
    _plant(cfg, 4, "pm", log=SERVICE_STUB)
    _plant(cfg, 5, "reviewer", log=NARRATION)          # matches no marker
    L = foundry.gather_losses(cfg)
    assert isinstance(L, foundry.LossSummary)
    assert L.product == cfg.name
    assert L.attempts == 5 and L.lost == 5
    got = {r.kind: r.stages for r in L.rows}
    assert got["stalled"] == ("tester",)
    assert got["timeout"] == ("engineer",)
    assert got["cli-error"] == ("final",)
    assert got["service"] == ("pm",)
    assert got[foundry.ATTEMPT_FAILURE_DEFAULT] == ("reviewer",)
    assert L.exit_code == 1


def test_b12_an_attempt_with_output_present_is_not_a_loss(tmp_path):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "tester", log=TIMEOUT_STUB, out="the tester report")
    _plant(cfg, 2, "tester", log=TIMEOUT_STUB)          # no output beside it
    L = foundry.gather_losses(cfg)
    assert L.attempts == 2
    assert L.lost == 1
    assert [(r.kind, r.stages) for r in L.rows] == [("timeout", ("tester",))]


def test_b12_multiple_attempts_of_one_stage_all_count(tmp_path):
    cfg = _cfg(tmp_path)
    for attempt in (1, 2, 3):
        _plant(cfg, 7, "engineer", attempt=attempt, log=STALL_STUB)
    L = foundry.gather_losses(cfg)
    assert L.attempts == 3
    assert [(r.kind, r.lost, r.stages) for r in L.rows] == [("stalled", 3, ("engineer",))]


def test_b12_limit_scans_only_the_most_recent_iterations(tmp_path):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", log=TIMEOUT_STUB)
    _plant(cfg, 2, "engineer", log=STALL_STUB)
    _plant(cfg, 3, "final", log=CLI_STUB)
    assert foundry.gather_losses(cfg).attempts == 3
    newest = foundry.gather_losses(cfg, limit=1)
    assert newest.attempts == 1
    assert [(r.kind, r.stages) for r in newest.rows] == [("cli-error", ("final",))]
    two = foundry.gather_losses(cfg, limit=2)
    assert two.attempts == 2
    assert {r.kind for r in two.rows} == {"cli-error", "stalled"}


def test_b12_missing_state_dir_is_an_empty_summary_not_an_exception(tmp_path):
    cfg = _cfg(tmp_path)
    state = pathlib.Path(cfg.state)
    if state.exists():
        for child in sorted(state.rglob("*"), reverse=True):
            child.rmdir() if child.is_dir() else child.unlink()
        state.rmdir()
    assert not state.exists()
    L = foundry.gather_losses(cfg)
    assert (L.rows, L.attempts, L.lost) == ((), 0, 0)
    assert L.exit_code == 2 and L.verdict == "no attempts"
    assert "  no attempts" in L.render()


def test_b12_undecodable_log_falls_through_to_the_default_kind(tmp_path):
    cfg = _cfg(tmp_path)
    d = pathlib.Path(cfg.state) / "iter-01"
    d.mkdir(parents=True, exist_ok=True)
    (d / "engineer.attempt1.log").write_bytes(b"\xff\xfe\x00 not valid utf-8 \xc3")
    L = foundry.gather_losses(cfg)                       # must not raise
    assert L.attempts == 1 and L.lost == 1
    assert [r.kind for r in L.rows] == [foundry.ATTEMPT_FAILURE_DEFAULT]


def test_b12_non_attempt_files_in_the_state_dir_are_ignored(tmp_path):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "tester", log=STALL_STUB)
    d = pathlib.Path(cfg.state) / "iter-01"
    (d / "notes.md").write_text("prose")
    (d / "engineer.log").write_text(TIMEOUT_STUB)        # no .attemptN. segment
    L = foundry.gather_losses(cfg)
    assert L.attempts == 1
    assert [(r.kind, r.stages) for r in L.rows] == [("stalled", ("tester",))]


# --------------------------------------------------------------------------
# behavior 13 -- every module global is read INSIDE the function at CALL time
# --------------------------------------------------------------------------
def test_b13_attempt_log_glob_is_read_at_call_time(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "tester", log=STALL_STUB)
    assert foundry.gather_losses(cfg).attempts == 1
    monkeypatch.setattr(foundry, "ATTEMPT_LOG_GLOB", "iter-*/nothing-here*.log")
    reshaped = foundry.gather_losses(cfg)
    assert reshaped.attempts == 0 and reshaped.exit_code == 2


def test_b13_markers_and_default_are_read_at_call_time(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "tester", log=STALL_STUB)
    _plant(cfg, 2, "pm", log=TIMEOUT_STUB)
    monkeypatch.setattr(foundry, "ATTEMPT_FAILURE_MARKERS",
                        (("bespoke", ("no data received",)),))
    monkeypatch.setattr(foundry, "ATTEMPT_FAILURE_DEFAULT", "MYSTERY")
    L = foundry.gather_losses(cfg)
    assert {(r.kind, r.stages) for r in L.rows} == {
        ("bespoke", ("tester",)), ("MYSTERY", ("pm",))}


def test_b13_stage_output_names_is_read_at_call_time(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    d = _plant(cfg, 1, "tester", log=STALL_STUB)
    (d / "oracle.txt").write_text("the real output under another name")
    assert foundry.gather_losses(cfg).lost == 1          # oracle.txt unknown
    monkeypatch.setattr(foundry, "STAGE_OUTPUT_NAMES", {"tester": "oracle.txt"})
    reshaped = foundry.gather_losses(cfg)
    assert reshaped.attempts == 1
    assert reshaped.lost == 0 and reshaped.rows == ()


# --------------------------------------------------------------------------
# behavior 14 -- thin CLI + `losses` subcommand
# --------------------------------------------------------------------------
def test_b14_losses_cli_delegates_to_the_shared_thin_helper(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    seen = {}

    def recorder(gatherer, config, limit, as_json):
        seen.update(gatherer=gatherer, config=config, limit=limit, as_json=as_json)
        return 77

    monkeypatch.setattr(foundry, "_thin_gather_cli", recorder)
    assert foundry.losses_cli(cfg, 4, True) == 77
    assert seen["gatherer"] is foundry.gather_losses
    assert seen["config"] is cfg
    assert (seen["limit"], seen["as_json"]) == (4, True)


def test_b14_main_losses_prints_the_report_and_returns_the_exit_code(tmp_path, capsys):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _plant(cfg, 1, "tester", log=STALL_STUB)
    rc = foundry.main(["losses", "--config", str(cfg_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert f"foundry losses -- {cfg.name}" in out
    assert "  [stalled] lost 1  stages: tester" in out
    assert _last_non_empty(out) == "verdict: LOST WORK BY CAUSE"


def test_b14_main_losses_exit_0_when_clean_and_2_when_empty(tmp_path, capsys):
    clean = tmp_path / "clean"
    clean.mkdir()
    cfg_path = _write_cfg(clean)
    cfg = foundry.load_config(str(cfg_path))
    _plant(cfg, 1, "tester", log=NARRATION, out="report")
    assert foundry.main(["losses", "--config", str(cfg_path)]) == 0
    assert "verdict: no lost attempts" in capsys.readouterr().out

    empty = tmp_path / "empty"
    empty.mkdir()
    empty_cfg = _write_cfg(empty)
    assert foundry.main(["losses", "--config", str(empty_cfg)]) == 2
    assert "verdict: no attempts" in capsys.readouterr().out


def test_b14_main_losses_json_is_one_indented_document(tmp_path, capsys):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _plant(cfg, 1, "tester", log=STALL_STUB)
    rc = foundry.main(["losses", "--config", str(cfg_path), "--json"])
    raw = capsys.readouterr().out
    assert rc == 1
    payload = json.loads(raw)                            # ONE document, parses whole
    assert payload == foundry.gather_losses(cfg).to_dict()
    assert '\n  "product"' in raw, "expected json.dumps(..., indent=2)"
    assert raw.count('"product"') == 1
    assert "verdict:" not in raw, "json mode must not also print the text report"


def test_b14_main_losses_honours_limit(tmp_path, capsys):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _plant(cfg, 1, "pm", log=TIMEOUT_STUB)
    _plant(cfg, 2, "final", log=CLI_STUB)
    rc = foundry.main(["losses", "--config", str(cfg_path), "--limit", "1"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "  attempts 1  lost 1  kinds 1" in out
    assert "[cli-error]" in out and "[timeout]" not in out


def test_b14_main_losses_requires_config():
    with pytest.raises(SystemExit) as excinfo:
        foundry.main(["losses"])
    assert excinfo.value.code != 0


def test_b14_main_losses_writes_nothing_to_disk(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _plant(cfg, 1, "tester", log=STALL_STUB)
    foundry.gather_losses(cfg)                           # settle any lazy mkdir
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    assert foundry.main(["losses", "--config", str(cfg_path), "--json"]) == 1
    after = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    assert set(after) == set(before), "read-only verb created or removed a file"
    assert after == before, "read-only verb rewrote a file"


# --------------------------------------------------------------------------
# behavior 15 -- DORMANT: zero call sites in the running pipeline
# --------------------------------------------------------------------------
_NEW_NAMES = ("attempt_loss_summary", "LossRow", "LossSummary",
              "gather_losses", "losses_cli", "_loss_fields")


def _tokens_in(text):
    return {n for n in _NEW_NAMES if re.search(r"\b" + re.escape(n) + r"\b", text)}


def test_b15_no_call_site_in_the_running_pipeline():
    """Mechanical token scan, with a POSITIVE CONTROL in the same test so a
    fail-open scanner (regex that matches nothing) cannot pass this."""
    assert _tokens_in(inspect.getsource(foundry.losses_cli)), (
        "positive control failed: the scanner cannot see a known call site")
    for name in ("run_stage", "run_iteration", "build_prompt", "postrelease_step"):
        src = inspect.getsource(getattr(foundry, name))
        assert _tokens_in(src) == set(), f"{name} gained a call site -- b15"
    dispatcher_src = (_ROOT / "dispatcher.py").read_text(encoding="utf-8")
    assert _tokens_in(dispatcher_src) == set(), "dispatcher.py gained a call site"


@pytest.mark.parametrize("module", ["foundry", "dispatcher"])
def test_b15_module_still_imports_from_a_clean_interpreter(module):
    proc = subprocess.run([sys.executable, "-c", f"import {module}"],
                          cwd=str(_ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


# --------------------------------------------------------------------------
# behavior 16 -- README index section 51, iteration-169 brake still green
# --------------------------------------------------------------------------
def test_b16_readme_gains_one_new_index_section_and_invokes_the_verb():
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    numbers = re.findall(r"^# (\d+)\.", readme, re.M)
    assert len(numbers) == len(set(numbers)), "duplicate index section number"
    assert "51" in numbers
    # RELAXED iter 175: a `max(...)` equality froze a snapshot into a law.  The ship gate MANDATES
    # a new "# N." section for every new verb, so that assert reds the next add-a-verb iteration --
    # it red iteration 173 itself with every other gate green.  The intent (51 exists, numbers are
    # unique, ascending, gap-free) is now the derived contract, which tolerates the mandated growth.
    violations = foundry.readme_index_number_violations(
        numbers, required=("0", "42", "49", "50", "51"), contiguous=True)
    assert violations == (), "README section-number contract broken: %s" % (violations,)
    assert "foundry.py losses" in readme


def test_b16_live_verb_index_brake_is_green():
    verbs = foundry.foundry_cli_verbs((_ROOT / "foundry.py").read_text(encoding="utf-8"))
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "losses" in verbs
    assert len(verbs) >= 48
    audit = foundry.readme_verb_index_gaps(readme, verbs)
    assert audit.missing_verbs == ()
    assert audit.unknown_invocations == ()
    assert audit.sections_without_invocation == ()
    assert audit.ok is True


# --------------------------------------------------------------------------
# behavior 17 -- roadmap ledger row + archive bullet ship in this commit
# --------------------------------------------------------------------------
def test_b17_roadmap_ledger_carries_one_iter_173_row():
    rows = [ln for ln in (_ROOT / "PLATFORM_ROADMAP.md")
            .read_text(encoding="utf-8").splitlines() if ln.startswith("- iter 173 ")]
    assert len(rows) == 1, rows
    assert len(rows[0]) <= 120, f"ledger row is {len(rows[0])} chars"


def test_b17_archive_carries_one_iter_173_bullet():
    bullets = [ln for ln in (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md")
               .read_text(encoding="utf-8").splitlines()
               if ln.startswith("- **iter 173 ")]
    assert len(bullets) == 1, bullets


def test_b17_the_cli_verb_count_trap_is_respected():
    """REPOINTED iter 185 -- the trap this test NAMED is gone at the root.

    It pinned the literal 48-verb figure against the live roadmap while its own
    docstring recorded that refreshing the figure turns the suite red. Iteration
    185 replaced both pins with `roadmap_verb_figure_gaps`, which subsumes the old
    negative pin as well: ANY figure disagreeing with the live count is flagged,
    so no stale value needs naming.
    """
    roadmap = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    verbs = foundry.foundry_cli_verbs((_ROOT / "foundry.py").read_text(encoding="utf-8"))
    assert verbs, "control: the live CLI verb set failed to parse"
    assert foundry.roadmap_verb_figure_gaps(roadmap, len(verbs)) == ()


# --------------------------------------------------------------------------
# TESTER-RETRY additions (iteration 173, second tester round)
#
# The first tester round was cut short by the per-stage cap.  Nothing below
# hunts a regression -- these close five coverage gaps I found by re-reading
# the spec against the inherited tests, and every asserted value was probed
# live before it was written down:
#   (a) behavior 16 pins the NEW section number but not that PRE-EXISTING ones
#       did not move, and not the brake's stated SECTION floor (>= 49);
#   (b) behavior 12 defines `limit=N > 0` only, so 0 / negative / oversized
#       limits are an unspecified domain that must still be TOTAL;
#   (c) behavior 12's "missing or UNREADABLE state dir" -- only the missing
#       half was covered;
#   (d) behavior 12's "unreadable/undecodable log" -- only undecodable was
#       covered, and permission-denied is the failure this repo actually sees;
#   (e) behavior 2's 5-sequence rule has two traps a real log can produce:
#       a 5-CHARACTER string is a 5-sequence, and `kind` need not be a str.
# --------------------------------------------------------------------------
def _unreadable(path):
    """chmod 000 and CONFIRM it took effect; skip otherwise (root, or a
    filesystem that ignores mode bits) so the post-release fresh-clone
    re-verification cannot go flaky on an environment difference."""
    os.chmod(path, 0o000)
    try:
        os.listdir(path) if path.is_dir() else path.read_bytes()
    except PermissionError:
        return True
    except OSError:
        pass
    os.chmod(path, 0o755 if path.is_dir() else 0o644)
    pytest.skip("filesystem does not enforce mode bits here")


def test_b16_pre_existing_index_numbers_did_not_move():
    """Behavior 16: the new section is ADDITIVE.  Uniqueness alone would still
    pass if iteration 169's hand-pinned `# 49.` / `# 50.` had been renumbered, so
    assert the run is CONTIGUOUS and every pinned number survives.  Also assert
    the brake's SECTION floor, which the spec states (>= 49) and no other
    assertion here checks.

    RELAXED iter 175: this used to compare the sorted run against a `range()` of
    a LITERAL length, which encodes "52 sections existed when I was written" as
    "52 sections forever" -- the same snapshot-as-law defect as the sibling
    assert above, and the reason iteration 173 reverted.  The derived contract
    asserts the same four properties (unique, ascending, gap-free, the pinned
    numbers present) without any dependency on how far the index has grown."""
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    numbers = re.findall(r"^# (\d+)\.", readme, re.M)
    assert numbers, "no numbered README index found -- the matcher stopped matching"
    violations = foundry.readme_index_number_violations(
        numbers, required=("0", "42", "49", "50", "51"), contiguous=True)
    assert violations == (), (
        "index numbers must be unique, ascending and gap-free with 0/42/49/50/51 "
        "present, and must not be renumbered: %s" % (violations,))
    for pinned in ("\n# 49.", "\n# 50.", "\n# 51."):
        assert pinned in readme, f"{pinned!r} missing -- a section number moved"
    verbs = foundry.foundry_cli_verbs((_ROOT / "foundry.py").read_text(encoding="utf-8"))
    audit = foundry.readme_verb_index_gaps(readme, verbs)
    assert audit.sections_scanned >= 49, audit.sections_scanned


@pytest.mark.parametrize("limit", [0, -1, -99, 999])
def test_b12_limit_outside_the_specified_domain_is_total(tmp_path, limit):
    """Behavior 12 specifies `limit=N > 0` and is SILENT on 0, negative, or a
    limit larger than the number of iteration dirs.  AMBIGUITY NOTED (PM
    feedback).  The reasonable reading, and the one observed, is that a limit
    which cannot narrow the scan does not narrow it -- and above all it must
    never raise, because a non-total gauge is worse than a missing one."""
    cfg = _cfg(tmp_path)
    for i in (1, 2, 3):
        _plant(cfg, i, "tester", log=TIMEOUT_STUB)
    L = foundry.gather_losses(cfg, limit=limit)
    assert (L.attempts, L.lost) == (3, 3), f"limit={limit!r} narrowed or lost rows"
    assert L.exit_code == 1
    assert L == foundry.gather_losses(cfg)          # same as no limit at all


def test_b12_unreadable_iteration_dir_is_skipped_not_fatal(tmp_path):
    """Behavior 12: a missing or UNREADABLE state dir must yield a summary, never
    an exception.  Permission-denied on ONE iteration dir must not lose the
    others either."""
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "tester", log=TIMEOUT_STUB)
    blocked = _plant(cfg, 2, "pm", log=TIMEOUT_STUB)
    _unreadable(blocked)
    try:
        L = foundry.gather_losses(cfg)
    finally:
        os.chmod(blocked, 0o755)
    assert isinstance(L, foundry.LossSummary)
    assert (L.attempts, L.lost) == (1, 1), "the readable iteration was lost too"
    assert _by_kind(L)["timeout"].stages == ("tester",)


def test_b12_unreadable_log_counts_as_an_attempt_with_the_default_kind(tmp_path):
    """Behavior 12, last clause: an unreadable log is an attempt with NO
    evidence, so its kind falls through to `ATTEMPT_FAILURE_DEFAULT` -- it is
    not dropped (that would shrink the population the verb exists to fix) and it
    does not crash."""
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "tester", log=TIMEOUT_STUB)
    d = _plant(cfg, 2, "pm", log=TIMEOUT_STUB)
    log = d / "pm.attempt1.log"
    _unreadable(log)
    try:
        L = foundry.gather_losses(cfg)
    finally:
        os.chmod(log, 0o644)
    assert (L.attempts, L.lost) == (2, 2)
    rows = _by_kind(L)
    assert rows[foundry.ATTEMPT_FAILURE_DEFAULT].stages == ("pm",)
    assert rows["timeout"].stages == ("tester",)


@pytest.mark.parametrize("blob", ["abcde", b"abcde", "tester", "", "ab"])
def test_b02_text_that_merely_has_five_items_is_not_a_record(blob):
    """Behavior 2 trap: a 5-CHARACTER string IS a 5-sequence, so a naive
    length check would read `abcde` as stage 'a', iteration 'b', kind 'e' and
    invent a loss out of narration.  A str/bytes blob must be SKIPPED -- it
    contributes to nothing, including `attempts`."""
    L = _summary([blob, _rec("tester", 1, 1, kind="stalled")])
    assert (L.attempts, L.lost, L.kinds) == (1, 1, 1), (
        f"{blob!r} was mis-read as a record")
    assert _by_kind(L)["stalled"].stages == ("tester",)


def test_b02_a_trailing_extra_field_is_tolerated_not_fatal():
    """AMBIGUITY NOTED (PM feedback): behavior 2 names a 5-sequence and says
    anything of NEITHER shape is skipped, but is silent on a LONGER sequence.
    Observed reading, pinned here: the first five items are read and extras are
    ignored, which is the forgiving direction and cannot lose a real loss."""
    L = _summary([("tester", 1, 1, False, "stalled", "extra"),
                  ("pm", 2, 1, False, "timeout", "x", "y")])
    assert (L.attempts, L.lost) == (2, 2)
    assert _by_kind(L)["stalled"].stages == ("tester",)
    assert _by_kind(L)["timeout"].stages == ("pm",)


@pytest.mark.parametrize("kind,expected", [(None, "None"), (3, "3")])
def test_b04_non_str_kind_is_normalised_so_the_json_contract_holds(kind, expected):
    """Behaviors 4 and 11: `LossRow.kind` is typed `str` and `to_dict()` must be
    JSON-safe.  `kind` comes from a classifier over a log, so a caller CAN hand
    in a non-str; it must be coerced rather than leaking a non-string key into
    `render()` or `json.dumps`."""
    L = _summary([("tester", 1, 1, False, kind)])
    row, = L.rows
    assert isinstance(row.kind, str) and row.kind == expected
    assert f"[{expected}] lost 1" in L.render()
    assert json.loads(json.dumps(L.to_dict()))["rows"][0]["kind"] == expected
