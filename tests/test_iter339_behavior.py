"""Iteration 339 -- BLACK-BOX behavior tests: the PM-prompt SCOUT SLATE YIELD seam.

The iteration's product is `pm_slate_block(it_dir, stage)`, a fifth member of the
`pm_*_block` prompt-feed family: it injects one bounded `- scout X:` yield line per
PRESENT scout slate file into the PM lead's prompt, labelling an all-placeholder
slate as unfit, computed through the already-shipped `parse_scout_candidates` and
`scout_candidate_is_stub` oracles.

ISOLATION CONTRACT (HONORED).  Every assertion below was derived from this
iteration's PM spec (`pm.md`, Expected Behaviors 1-8 plus its Acceptance
Criteria) and from the conventions of the existing modules under `tests/`
(chiefly `test_iter333_behavior.py`, the previous `pm_*_block` iteration, and
`test_iter321_behavior.py`, which owns the stub oracle's fixtures).  I did NOT
read `foundry.py`'s implementation text, `engineer.md`, `reviewer.md`,
`IMPLEMENTATION.patch`, or `git diff`.  The new surface is driven as a BLACK BOX:
public functions called, `inspect.signature` read, observable return strings
asserted.

OFFLINE + FRESH-CLONE SAFE.  Every iteration-dir fixture is built under
`tmp_path`; no test reads the real `products/*/state` tree, pins an ambient file
count, spawns a subprocess, touches the network or reads the wall clock.  No
absolute machine path and no username appears as a source literal -- every path
is built at runtime from `__file__` or `tmp_path`.

SELF-VALIDATING FIXTURES.  The stub/measured heading literals are transcribed
from `tests/test_iter321_behavior.py` (the oracle's own iteration) and every one
of them is re-checked against `scout_candidate_is_stub` before it is used to
grade the new seam, so a fixture that drifts fails loudly instead of making a
yield assertion vacuous.
"""
from __future__ import annotations

import inspect
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

THIS_ITER = 339

SEAM = "pm_slate_block"
UNFIT = "SLATE UNFIT"

# Three MEASURED candidate titles, verbatim from tests/test_iter321_behavior.py's
# REAL_LINES (the oracle's own iteration proves each is NOT a stub).
MEASURED = (
    "Candidate A1 -- the dual-scout default is the path only the RETIRED "
    "product takes: flip it, blast radius zero",
    "Candidate A2 -- the README front door is 61.7% single-line essays",
    "Candidate A3 -- give the two-sided roadmap-ledger flip a verb, because "
    "the seat that needs it is currently told to hand-write Python",
)

# Three write-early PLACEHOLDER titles, verbatim shapes from the same file's
# STUB_LINES, with distinct ids so no dedupe can collapse the slate.
STUBS = (
    "Candidate A1 -- (measuring)",
    "Candidate A2 -- pending",
    "Candidate A3 -- TBD",
)

ROLE_FILE = {
    "pm": "pm.md",
    "engineer": "engineer.md",
    "reviewer": "reviewer.md",
    "tester": "tester.md",
    "final": "final.md",
    "fix": "fix.md",
    "reporter": "reporter.md",
    "pm_scout_a": "pm_scout.md",
    "pm_scout_b": "pm_scout.md",
    "fix-review": "reviewer.md",
    "tester-rerun": "tester.md",
    "tester-retry": "tester.md",
    "tester-retry2": "tester.md",
}


# --------------------------------------------------------------------------
# stage domain -- derived structurally, never hand-listed
# --------------------------------------------------------------------------
def _core_stages() -> tuple[str, ...]:
    """The stage NAMES of `derive_stage_sequence(None)`.

    The sequence yields StageSpec objects, not strings, so a loop over the raw
    specs would test the non-pm branch every time and the pm branch never.
    """
    return tuple(spec.stage for spec in foundry.derive_stage_sequence(None))


def _all_stages() -> tuple[str, ...]:
    """Every stage name `build_prompt` is asked to serve."""
    names = list(_core_stages())
    names.extend(("fix", "pm_scout_a", "pm_scout_b"))
    names.extend(sorted(foundry.STAGE_OUTPUT_NAMES))
    out: list[str] = []
    for name in names:
        if name not in out:
            out.append(name)
    return tuple(out)


def _other_stages() -> tuple[str, ...]:
    return tuple(s for s in _all_stages() if s != "pm")


# --------------------------------------------------------------------------
# fixtures -- ALWAYS under tmp_path
# --------------------------------------------------------------------------
def _slate_text(headings) -> str:
    """A scout slate in the shape the scouts really write."""
    body = ["# Candidate slate (a lens heading)", ""]
    for head in headings:
        body.append("## " + head)
        body.append("")
        body.append("some prose under the heading")
        body.append("")
    return "\n".join(body)


def _it_dir(tmp_path, sub="it", a=None, b=None, raw=None):
    """Build an iteration state dir under tmp_path.

    `a`/`b` are heading tuples (written as slate text); `raw` is a mapping of
    file name -> bytes written verbatim, for the totality probes.
    """
    d = pathlib.Path(tmp_path) / sub / ("iter-%d" % THIS_ITER)
    d.mkdir(parents=True, exist_ok=True)
    if a is not None:
        (d / "pm_scout_a.md").write_text(_slate_text(a), encoding="utf-8")
    if b is not None:
        (d / "pm_scout_b.md").write_text(_slate_text(b), encoding="utf-8")
    for name, payload in (raw or {}).items():
        (d / name).write_bytes(payload)
    return d


def _block(it_dir, stage="pm"):
    return getattr(foundry, SEAM)(str(it_dir), stage)


def _base_tree(tmp_path, sub="p"):
    base = pathlib.Path(tmp_path) / sub
    base.mkdir(parents=True, exist_ok=True)
    (base / "repo").mkdir(exist_ok=True)
    (base / "VISION.md").write_text("product vision text\n", encoding="utf-8")
    (base / "ROADMAP.md").write_text("- a roadmap item\n", encoding="utf-8")
    return base, {
        "name": "demoprod",
        "repo": str(base / "repo"),
        "allowed_push_repo": "demoprod",
        "vision": str(base / "VISION.md"),
        "roadmap": str(base / "ROADMAP.md"),
        "work_root": str(base / "work"),
    }


def _cfg(tmp_path, sub="p", **over):
    base, common = _base_tree(tmp_path, sub=sub)
    data = dict(common)
    data.update(over)
    path = base / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    cfg = foundry.load_config(str(path))
    lp = pathlib.Path(cfg.learnings)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text("## Patterns\n\n- a durable rule\n\n- [ENG iter01] a lesson\n",
                  encoding="utf-8")
    return cfg


def _prompt(cfg, stage, it_dir=None):
    if it_dir is None:
        it_dir = pathlib.Path(cfg.work_root) / "state" / ("iter-%d" % THIS_ITER)
        it_dir.mkdir(parents=True, exist_ok=True)
    role = ROLE_FILE.get(stage, "pm.md")
    return foundry.build_prompt(cfg, THIS_ITER, stage, role,
                                pathlib.Path(it_dir) / ("%s.md" % stage),
                                pathlib.Path(it_dir), "extra!")


# ==========================================================================
# behavior 0 -- the DOMAIN and the surface, before anything is graded over them
# ==========================================================================
def test_b0_modules_import_and_the_named_surface_exists() -> None:
    """AC: the seam exists at module level, importable, params exactly (it_dir, stage)."""
    assert foundry.__name__ == "foundry" and dispatcher.__name__ == "dispatcher"
    assert hasattr(foundry, SEAM), "foundry.%s missing" % SEAM
    assert callable(getattr(foundry, SEAM))
    assert list(inspect.signature(getattr(foundry, SEAM)).parameters) == \
        ["it_dir", "stage"], inspect.signature(getattr(foundry, SEAM))


def test_b0_the_reused_oracles_are_still_present() -> None:
    """The yield must be COMPOSED from these; absent, every yield test is vacuous."""
    for name in ("parse_scout_candidates", "scout_candidate_is_stub", "build_prompt"):
        assert hasattr(foundry, name), "foundry.%s missing" % name


def test_b0_stage_domain_is_not_vacuous() -> None:
    core = _core_stages()
    assert core, "derive_stage_sequence(None) served no stage -- vacuous domain"
    assert all(isinstance(s, str) and s for s in core), core
    assert "pm" in core, (
        "no 'pm' stage in %r -- the seam's ONLY speaking branch would never be "
        "probed and a non-pm loop would report a false clean sweep" % (core,))
    assert len(_other_stages()) >= 4, _other_stages()


def test_b0_fixture_headings_agree_with_the_shipped_stub_oracle() -> None:
    """Self-validating fixtures: drift here would silently void behaviors 1/4/6."""
    assert len(MEASURED) == 3 and len(set(MEASURED)) == 3
    assert len(STUBS) == 3 and len(set(STUBS)) == 3
    for line in MEASURED:
        assert foundry.scout_candidate_is_stub(line) is False, line
    for line in STUBS:
        assert foundry.scout_candidate_is_stub(line) is True, line


def test_b0_fixture_slate_text_parses_to_exactly_three_candidates() -> None:
    """The `n` of every `k of n` below comes from this parse; prove it is 3."""
    for headings in (MEASURED, STUBS):
        got = foundry.parse_scout_candidates(_slate_text(headings))
        assert len(got) == 3, (headings, got)
        assert tuple(got) == tuple(headings), got


# ==========================================================================
# behavior 1 -- a measured slate yields `3 of 3`, never `0 of 3`; one trailing \n
# ==========================================================================
def test_b1_measured_slate_reports_three_of_three(tmp_path) -> None:
    d = _it_dir(tmp_path, sub="b1", a=MEASURED)
    got = _block(d, "pm")
    assert got, "the pm prompt got no yield line for a present slate"
    assert "3 of 3" in got, got
    assert "0 of 3" not in got, got


def test_b1_names_the_seat_it_measured(tmp_path) -> None:
    d = _it_dir(tmp_path, sub="b1name", a=MEASURED)
    got = _block(d, "pm")
    assert "scout A" in got or "scout a" in got, got
    assert "- scout " in got, ("the spec's own `- scout X:` line shape is absent", got)


def test_b1_last_character_is_exactly_one_newline(tmp_path) -> None:
    d = _it_dir(tmp_path, sub="b1nl", a=MEASURED, b=MEASURED)
    got = _block(d, "pm")
    assert got[-1] == "\n", repr(got[-8:])
    assert not got.endswith("\n\n"), (
        "trailing blank line -- the f-string run would grow a gap", repr(got[-8:]))


# ==========================================================================
# behavior 2 -- every non-pm stage gets "" even with both slates present + unfit
# ==========================================================================
def test_b2_every_non_pm_stage_is_silent(tmp_path) -> None:
    d = _it_dir(tmp_path, sub="b2", a=STUBS, b=STUBS)
    assert _block(d, "pm") != "", "precondition: the pm branch must speak here"
    for stage in _other_stages():
        assert _block(d, stage) == "", stage


def test_b2_the_five_stages_the_spec_names_by_hand_are_silent(tmp_path) -> None:
    """Named explicitly so a shrunken `_all_stages()` cannot hide a regression."""
    d = _it_dir(tmp_path, sub="b2named", a=STUBS, b=STUBS)
    for stage in ("engineer", "reviewer", "tester", "final", "pm_scout_a"):
        assert _block(d, stage) == "", stage


def test_b2_stage_matching_is_not_a_prefix_or_substring_test(tmp_path) -> None:
    """`pm_scout_a` starts with `pm`; `startswith` would leak the block to it."""
    d = _it_dir(tmp_path, sub="b2pfx", a=MEASURED)
    for stage in ("pm_scout_a", "pm_scout_b", "pm-lead", "pmx", "PM", " pm"):
        assert _block(d, stage) == "", stage


# ==========================================================================
# behavior 3 -- no slate files at all => "" (byte-identical prompt)
# ==========================================================================
def test_b3_empty_iteration_dir_yields_nothing(tmp_path) -> None:
    d = _it_dir(tmp_path, sub="b3")
    assert list(d.iterdir()) == [], list(d.iterdir())
    assert _block(d, "pm") == ""


def test_b3_other_iteration_files_do_not_wake_the_seam(tmp_path) -> None:
    d = _it_dir(tmp_path, sub="b3other")
    (d / "pm.md").write_text("## Candidate A1 -- a measured thing\n", encoding="utf-8")
    (d / "engineer.md").write_text("## Candidate B1 -- another\n", encoding="utf-8")
    (d / "scout_a.md").write_text("## Candidate C1 -- near-miss name\n", encoding="utf-8")
    assert _block(d, "pm") == "", "a non-slate file was read as a slate"


def test_b3_a_missing_iteration_dir_is_also_silent(tmp_path) -> None:
    """A non-scouted iteration must never make the prompt unbuildable."""
    missing = pathlib.Path(tmp_path) / "b3missing" / ("iter-%d" % THIS_ITER)
    assert not missing.exists()
    got = _block(missing, "pm")
    assert isinstance(got, str) and got == "", repr(got)


# ==========================================================================
# behavior 4 -- all-stub => `0 of 3` + `SLATE UNFIT`; measured => no unfit token
# ==========================================================================
def test_b4_all_stub_slate_is_zero_of_three_and_unfit(tmp_path) -> None:
    d = _it_dir(tmp_path, sub="b4", a=STUBS)
    got = _block(d, "pm")
    assert "0 of 3" in got, got
    assert UNFIT in got, got


def test_b4_measured_slate_carries_no_unfit_token(tmp_path) -> None:
    d = _it_dir(tmp_path, sub="b4ok", a=MEASURED)
    got = _block(d, "pm")
    assert "3 of 3" in got, got
    assert UNFIT not in got, got


def test_b4_unfit_is_per_seat_not_per_iteration(tmp_path) -> None:
    """One dead seat must not condemn the live one, nor the reverse."""
    d = _it_dir(tmp_path, sub="b4mix", a=MEASURED, b=STUBS)
    got = _block(d, "pm")
    lines = [ln for ln in got.splitlines() if ln.strip()]
    a_lines = [ln for ln in lines if "scout A" in ln or "scout a" in ln]
    b_lines = [ln for ln in lines if "scout B" in ln or "scout b" in ln]
    assert len(a_lines) == 1, lines
    assert len(b_lines) == 1, lines
    assert UNFIT not in a_lines[0], a_lines
    assert UNFIT in b_lines[0], b_lines
    assert "3 of 3" in a_lines[0], a_lines
    assert "0 of 3" in b_lines[0], b_lines


def test_b4_the_total_is_the_real_heading_count_not_a_hardcoded_three(tmp_path) -> None:
    """`k of n`: n must come from the parse, or a 5- or 1-candidate slate lies."""
    five = MEASURED + STUBS[1:]          # 3 measured + 2 placeholders
    d5 = _it_dir(tmp_path, sub="b4five", a=five)
    assert len(foundry.parse_scout_candidates(_slate_text(five))) == 5
    got5 = _block(d5, "pm")
    assert "3 of 5" in got5, got5
    assert UNFIT not in got5, got5

    d1 = _it_dir(tmp_path, sub="b4one", a=(STUBS[0],))
    got1 = _block(d1, "pm")
    assert "0 of 1" in got1, got1
    assert UNFIT in got1, got1


def test_b4_the_block_stays_bounded_and_does_not_dump_the_slate(tmp_path) -> None:
    """`Out of Scope` promises the block needs no budget knob because it is short
    BY CONSTRUCTION.  A seam that pasted the candidate titles would break that
    promise silently while every `k of n` assertion stayed green."""
    d = _it_dir(tmp_path, sub="b4bound", a=MEASURED, b=STUBS)
    got = _block(d, "pm")
    for title in MEASURED + STUBS:
        assert title not in got, ("a candidate title leaked into the prompt", title)
    seat_lines = [ln for ln in got.splitlines() if ln.strip().startswith("- scout ")]
    assert len(seat_lines) == 2, got
    for ln in seat_lines:
        assert len(ln) <= 200, (len(ln), ln)


def test_b4_a_partly_measured_slate_is_not_unfit(tmp_path) -> None:
    """The token means NOTHING measured, not `some placeholder present`."""
    d = _it_dir(tmp_path, sub="b4part",
                a=(MEASURED[0], STUBS[1], STUBS[2]))
    got = _block(d, "pm")
    assert "1 of 3" in got, got
    assert UNFIT not in got, got


# ==========================================================================
# behavior 5 -- only seats whose file EXISTS are named
# ==========================================================================
def test_b5_absent_seat_is_not_named(tmp_path) -> None:
    d = _it_dir(tmp_path, sub="b5", a=MEASURED)
    assert not (d / "pm_scout_b.md").exists()
    got = _block(d, "pm")
    assert "scout A" in got or "scout a" in got, got
    assert "scout B" not in got and "scout b" not in got, got


def test_b5_the_b_only_case_is_symmetric(tmp_path) -> None:
    d = _it_dir(tmp_path, sub="b5b", b=STUBS)
    got = _block(d, "pm")
    assert "scout B" in got or "scout b" in got, got
    assert "scout A" not in got and "scout a" not in got, got
    assert "0 of 3" in got and UNFIT in got, got


def test_b5_both_present_names_both_exactly_once(tmp_path) -> None:
    d = _it_dir(tmp_path, sub="b5both", a=MEASURED, b=MEASURED)
    got = _block(d, "pm")
    yields = [ln for ln in got.splitlines() if ln.strip().startswith("- scout ")]
    assert len(yields) == 2, got
    assert len({ln for ln in yields}) == 2, got


# ==========================================================================
# behavior 6 -- COMPOSED from the shipped oracles, resolved by BARE module name
# ==========================================================================
def test_b6_stub_oracle_is_reached_through_the_module_global(tmp_path, monkeypatch) -> None:
    d = _it_dir(tmp_path, sub="b6stub", a=MEASURED)
    assert "3 of 3" in _block(d, "pm"), "precondition: measured slate reads 3 of 3"
    with monkeypatch.context() as m:
        m.setattr(foundry, "scout_candidate_is_stub", lambda c: True)
        got = _block(d, "pm")
    assert "0 of 3" in got, (
        "the seam did not route through foundry.scout_candidate_is_stub", got)
    assert UNFIT in got, got


def test_b6_parser_is_reached_through_the_module_global(tmp_path, monkeypatch) -> None:
    d = _it_dir(tmp_path, sub="b6parse", a=MEASURED, b=STUBS)
    with monkeypatch.context() as m:
        m.setattr(foundry, "parse_scout_candidates", lambda t: ())
        got = _block(d, "pm")
    assert isinstance(got, str), repr(got)
    for ln in [x for x in got.splitlines() if x.strip().startswith("- scout ")]:
        assert "0 of 0" in ln, (
            "the seam did not route through foundry.parse_scout_candidates", ln)


def test_b6_the_seam_contains_no_second_stub_signal_of_its_own(tmp_path, monkeypatch) -> None:
    """The composition contract, from the other side: with the oracle forced
    FALSE an all-placeholder slate must read fully measured."""
    d = _it_dir(tmp_path, sub="b6false", a=STUBS)
    assert "0 of 3" in _block(d, "pm"), "precondition: stub slate reads 0 of 3"
    with monkeypatch.context() as m:
        m.setattr(foundry, "scout_candidate_is_stub", lambda c: False)
        got = _block(d, "pm")
    assert "3 of 3" in got, got
    assert UNFIT not in got, got


# ==========================================================================
# behavior 7 -- TOTAL: never raises
# ==========================================================================
def test_b7_undecodable_bytes_do_not_raise(tmp_path) -> None:
    d = _it_dir(tmp_path, sub="b7bytes", raw={"pm_scout_a.md": b"\xff\xfe\x00"})
    got = _block(d, "pm")
    assert isinstance(got, str), repr(got)
    yields = [ln for ln in got.splitlines() if ln.strip().startswith("- scout ")]
    for ln in yields:
        assert "0 of 0" in ln, ln


def test_b7_empty_slate_file_does_not_raise(tmp_path) -> None:
    d = _it_dir(tmp_path, sub="b7empty", raw={"pm_scout_b.md": b""})
    got = _block(d, "pm")
    assert isinstance(got, str), repr(got)
    for ln in [x for x in got.splitlines() if x.strip().startswith("- scout ")]:
        assert "0 of 0" in ln, ln


def test_b7_a_directory_where_a_slate_belongs_does_not_raise(tmp_path) -> None:
    d = _it_dir(tmp_path, sub="b7dir")
    (d / "pm_scout_a.md").mkdir()
    assert (d / "pm_scout_a.md").is_dir()
    got = _block(d, "pm")
    assert isinstance(got, str), repr(got)
    for ln in [x for x in got.splitlines() if x.strip().startswith("- scout ")]:
        assert "0 of 0" in ln, ln


def test_b7_a_broken_oracle_does_not_break_the_prompt(tmp_path, monkeypatch) -> None:
    """Fail-soft on the composition edge too: the seam is prompt-feed, never a gate."""
    d = _it_dir(tmp_path, sub="b7boom", a=MEASURED)

    def boom(*a, **k):
        raise RuntimeError("scripted explosion")

    for name in ("parse_scout_candidates", "scout_candidate_is_stub"):
        with monkeypatch.context() as m:
            m.setattr(foundry, name, boom)
            got = getattr(foundry, SEAM)(str(d), "pm")
        assert isinstance(got, str), (name, repr(got))


@pytest.mark.parametrize("bad", [None, "", "   ", 0, 42, b"x", object()])
def test_b7_adversarial_it_dir_values_never_raise(bad) -> None:
    got = getattr(foundry, SEAM)(bad, "pm")
    assert isinstance(got, str), (repr(bad), repr(got))


@pytest.mark.parametrize("bad", [None, "", 0, object()])
def test_b7_adversarial_stage_values_never_raise(tmp_path, bad) -> None:
    d = _it_dir(tmp_path, sub="b7stage", a=MEASURED)
    got = getattr(foundry, SEAM)(str(d), bad)
    assert isinstance(got, str), (repr(bad), repr(got))
    assert got == "", "a non-pm stage value spoke: %r" % (got,)


def test_b7_repeated_calls_are_deterministic_and_read_only(tmp_path) -> None:
    d = _it_dir(tmp_path, sub="b7det", a=MEASURED, b=STUBS)
    before = sorted(p.name for p in d.iterdir())
    first = _block(d, "pm")
    second = _block(d, "pm")
    assert first == second, (first, second)
    assert sorted(p.name for p in d.iterdir()) == before, "the seam wrote to it_dir"


# ==========================================================================
# behavior 8 -- build_prompt consumes the seam EXACTLY ONCE, pm only
# ==========================================================================
SENTINEL = "SENTINEL339"


def test_b8_pm_prompt_carries_the_sentinel_exactly_once(tmp_path, monkeypatch) -> None:
    cfg = _cfg(tmp_path, sub="b8once")
    with monkeypatch.context() as m:
        m.setattr(foundry, SEAM, lambda d, s: SENTINEL + "\n")
        text = _prompt(cfg, "pm")
    assert text.count(SENTINEL) == 1, text.count(SENTINEL)


def test_b8_no_other_stage_carries_the_sentinel(tmp_path, monkeypatch) -> None:
    cfg = _cfg(tmp_path, sub="b8other")
    for stage in _other_stages():
        with monkeypatch.context() as m:
            m.setattr(foundry, SEAM, lambda d, s: SENTINEL + "\n")
            text = _prompt(cfg, stage)
        assert text.count(SENTINEL) == 0, stage


def test_b8_the_call_site_forwards_the_real_stage_string(tmp_path, monkeypatch) -> None:
    cfg = _cfg(tmp_path, sub="b8fwd")
    calls: list = []

    with monkeypatch.context() as m:
        m.setattr(foundry, SEAM, lambda d, s: (calls.append((d, s)), SENTINEL + "\n")[1])
        _prompt(cfg, "pm")
    assert len(calls) == 1, calls
    assert calls[0][1] == "pm", calls


def test_b8_the_live_seam_really_speaks_inside_the_pm_prompt(tmp_path) -> None:
    """The other half of the dormancy check -- a DELETED call site would pass a
    byte-identity test forever, so drive the REAL seam through build_prompt."""
    cfg = _cfg(tmp_path, sub="b8live")
    it_dir = pathlib.Path(cfg.work_root) / "state" / ("iter-%d" % THIS_ITER)
    it_dir.mkdir(parents=True, exist_ok=True)
    (it_dir / "pm_scout_a.md").write_text(_slate_text(STUBS), encoding="utf-8")
    (it_dir / "pm_scout_b.md").write_text(_slate_text(MEASURED), encoding="utf-8")
    pm_text = _prompt(cfg, "pm", it_dir=it_dir)
    assert UNFIT in pm_text, "the pm prompt lost the live slate block"
    assert pm_text.count(UNFIT) == 1, (
        "the live seam was consumed more than once", pm_text.count(UNFIT))
    assert "0 of 3" in pm_text and "3 of 3" in pm_text
    for stage in _other_stages():
        other = _prompt(cfg, stage, it_dir=it_dir)
        assert UNFIT not in other, stage


def test_b8_unscouted_prompts_are_byte_identical_to_a_silenced_seam(tmp_path, monkeypatch) -> None:
    """AC/behavior 3 at the prompt level: with no slate present every stage's
    prompt equals the prompt built with the seam forced to ""."""
    cfg = _cfg(tmp_path, sub="b8ident")
    for stage in _all_stages():
        live = _prompt(cfg, stage)
        with monkeypatch.context() as m:
            m.setattr(foundry, SEAM, lambda d, s: "")
            silenced = _prompt(cfg, stage)
        assert live == silenced, "stage %s moved without a slate present" % stage
