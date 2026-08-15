"""Black-box behaviour tests for iter 180 -- the `outcomes` ledger must read the
AUTHORITATIVE tester report (the newest ROUND actually present in an iteration dir),
not a hardcoded `tester.md`.

Spec: products/_platform/state/iter-180/pm.md, Expected Behaviors 1-17.

   1. `TESTER_REPORT_BASE` is a module-level `str` == "tester.md".
   2. `tester_report_round(name)` -> trailing digit-run of the stem as an `int`.
   3. `tester_report_round` is TOTAL: 0, never raises, for any digit-less name.
   4. `tester_report_names()` -> round-ASCENDING tuple, no duplicates, base first;
      on the shipped `STAGE_OUTPUT_NAMES` exactly ("tester.md","tester2.md","tester3.md").
   5. ... DERIVED from `STAGE_OUTPUT_NAMES` at CALL time (monkeypatch bites both ways).
   6. ... admits ONLY the strict `tester<digits>.md` shape.
   7. `authoritative_tester_report(present)` -> LAST known name present.
   8. ... `None` when none present; unrelated names ignored.
   9. ... TOTAL (empty / None / generator / duplicates) and touches NO filesystem.
  10. `read_authoritative_tester_result(dir)` -> verdict of the newest present report.
  11. ... three-report and single-report cases.
  12. ... `None` when the newest PRESENT report has no `RESULT:` sentinel, even if an
      OLDER report parses cleanly (pessimistic, no fallback).
  13. ... `None`, never raising, for an empty dir / a missing dir / an `OSError`.
  14. `gather_outcomes` gets every row's tester value through the BARE-NAME
      `read_authoritative_tester_result` seam and holds no hardcoded "tester.md".
  15. End-to-end over a `tmp_path` product: tester.md FAIL + tester2.md PASS -> row
      `tester == "PASS"`, `tester_passed == 1` / `tester_failed == 0`; review/action
      unaffected.
  16. The frozen machine contracts are byte-identical (4-key record, 8-key summary).
  17. `roles/final.md` gate checklist item 2 names the helper; the file stays ASCII.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-180 PM spec, the `tests/`
conventions (`tests/test_iter100_behavior.py`, the `outcomes` template this iteration
corrects, and `tests/test_iter101_behavior.py` for the frozen key tuples), the tracked
`roles/final.md` role card named by Behavior 17, and the product's own OBSERVABLE
behaviour via its public interface / runtime introspection. `foundry.py`'s
implementation source, the engineer's and reviewer's notes and `git diff` were NOT read.

HERMETIC: every fixture is built under `tmp_path`; the only ambient path any test reads
is the TRACKED `roles/final.md` (Behavior 17 is about that file), so a fresh clone
passes -- no assertion depends on gitignored state (`products/*/state/`, iteration dirs,
`LEARNINGS.md`), which is the iter-155 trap. No network, no subprocess, no git, no
clock, no sleeps.

XDIST-SAFETY: all mutation is `monkeypatch`-scoped and process-local, safe under
`-n auto`. The two tests that patch `pathlib.Path` / `builtins` do so inside a
`monkeypatch.context()` block that is exited BEFORE any assertion runs, so a failure
report can still touch the filesystem.
"""
from __future__ import annotations

import builtins
import inspect
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

# Frozen machine contracts, quoted from tests/test_iter101_behavior.py (Behavior 16).
RECORD_KEYS = ("iteration", "review", "tester", "action")
SUMMARY_KEYS = ("product", "total", "approved", "changes_required",
                "tester_passed", "tester_failed", "exit_code", "records")

SHIPPED_NAMES = ("tester.md", "tester2.md", "tester3.md")


# --------------------------------------------------------------------------- helpers
def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir; `repo`/`work_root` are TMP dirs so the
    real foundry repo/state is NEVER touched (mirrors tests/test_iter100_behavior.py)."""
    pathlib.Path(tmp_path).mkdir(parents=True, exist_ok=True)
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
    """`state` is a DERIVED property, so a ProductConfig must come from load_config."""
    return foundry.load_config(str(_write_cfg(tmp_path, **over)))


def _iter_dir(cfg, iteration):
    d = pathlib.Path(cfg.state) / f"iter-{iteration:02d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _report(d, name, verdict):
    """Write a tester report whose LAST non-empty line is the role-owned sentinel."""
    (pathlib.Path(d) / name).write_text(
        f"test report {name}\n\nsome prose\n\nRESULT: {verdict}\n\n   \n\t\n"
    )


def _dir_with(tmp_path, **reports):
    """tmp dir holding {report-name: verdict}; keys use `_` for `.` (tester2_md)."""
    d = tmp_path / "iter"
    d.mkdir(parents=True, exist_ok=True)
    for key, verdict in reports.items():
        _report(d, key.replace("_md", ".md"), verdict)
    return d


def _boom(*a, **k):  # pragma: no cover - only reached if a no-I/O contract breaks
    raise AssertionError("filesystem touched")


# ------------------------------------------------------------------ Behaviors 1-3
def test_b01_tester_report_base_is_module_level_str():
    """Behavior 1."""
    assert isinstance(foundry.TESTER_REPORT_BASE, str)
    assert foundry.TESTER_REPORT_BASE == "tester.md"


@pytest.mark.parametrize("name,want", [
    ("tester.md", 0),
    ("tester2.md", 2),
    ("tester3.md", 3),
    ("tester12.md", 12),
    # Behavior 2's rule is "trailing digit-run of the STEM", so a name whose stem ends
    # in a digit scores that digit even when it is not a report at all. Harmless: the
    # strict shape gate (Behavior 6) keeps such a name out of `tester_report_names()`
    # and `authoritative_tester_report` ignores it outright (proved in b08).
    ("tester.attempt1.log", 1),
])
def test_b02_tester_report_round_reads_trailing_digit_run(name, want):
    """Behavior 2."""
    got = foundry.tester_report_round(name)
    assert got == want, f"{name!r} -> {got!r}, want {want!r}"
    assert isinstance(got, int) and not isinstance(got, bool)


@pytest.mark.parametrize("name", [
    "", "reviewer.md", "testerp.md", "tester.md.bak", "tester", "final.md",
    "2tester.md", "tester_2.md.txt", "tester.log", "tester-rerun.md",
])
def test_b03_tester_report_round_is_total_and_defaults_to_zero(name):
    """Behavior 3 -- total: 0 and never raises for any name with no trailing run."""
    assert foundry.tester_report_round(name) == 0


# -------------------------------------------------------------------- Behavior 4
def test_b04_tester_report_names_shape_and_shipped_value():
    """Behavior 4."""
    names = foundry.tester_report_names()
    assert isinstance(names, tuple)
    assert all(isinstance(n, str) for n in names)
    assert names == SHIPPED_NAMES, f"got {names!r}"
    # ordered by round ASCENDING, so the authoritative report is LAST
    rounds = [foundry.tester_report_round(n) for n in names]
    assert rounds == sorted(rounds) == [0, 2, 3]
    assert len(set(names)) == len(names), "no duplicates"
    assert names[0] == foundry.TESTER_REPORT_BASE
    assert names[-1] == "tester3.md"


def test_b04b_tester_report_names_is_stable_across_calls():
    """Behavior 4 -- a derived selector must be a function, not a coin flip."""
    assert foundry.tester_report_names() == foundry.tester_report_names()


# ----------------------------------------------------------------- Behaviors 5-6
def test_b05_tester_report_names_derives_from_the_table_at_call_time(monkeypatch):
    """Behavior 5 -- a NEW tester-prefixed retry stage joins the tail automatically."""
    monkeypatch.setattr(
        foundry, "STAGE_OUTPUT_NAMES",
        dict(foundry.STAGE_OUTPUT_NAMES, **{"tester-retry3": "tester4.md"}),
    )
    names = foundry.tester_report_names()
    assert names[-1] == "tester4.md", f"got {names!r}"
    assert names == SHIPPED_NAMES + ("tester4.md",)


def test_b05b_tester_report_names_empty_table_is_base_only(monkeypatch):
    """Behavior 5 -- the base is always seeded, even with no routing table at all."""
    monkeypatch.setattr(foundry, "STAGE_OUTPUT_NAMES", {})
    assert foundry.tester_report_names() == (foundry.TESTER_REPORT_BASE,)


@pytest.mark.parametrize("bad", ["testerp.md", "tester{iteration:02d}.md"])
def test_b06_tester_report_names_admits_only_the_strict_shape(monkeypatch, bad):
    """Behavior 6 -- non-`tester<digits>.md` values are rejected, not round-0'd in."""
    monkeypatch.setattr(foundry, "STAGE_OUTPUT_NAMES", {"tester-weird": bad})
    names = foundry.tester_report_names()
    assert bad not in names, f"{bad!r} leaked into {names!r}"
    assert names == (foundry.TESTER_REPORT_BASE,)


# ----------------------------------------------------------------- Behaviors 7-9
@pytest.mark.parametrize("present,want", [
    ({"tester.md", "tester2.md"}, "tester2.md"),
    ({"tester.md", "tester2.md", "tester3.md"}, "tester3.md"),
    ({"tester.md"}, "tester.md"),
    ({"tester.md", "tester3.md"}, "tester3.md"),       # a gap is fine
    ({"tester3.md"}, "tester3.md"),
])
def test_b07_authoritative_picks_the_last_present_round(present, want):
    """Behavior 7."""
    assert foundry.authoritative_tester_report(present) == want


@pytest.mark.parametrize("present", [
    {"reviewer.md", "final.md", "tester.attempt1.log", "testerp.md"},
    {"pm.md"},
    {"tester.md.bak"},
])
def test_b08_authoritative_is_none_when_absent_and_ignores_unrelated(present):
    """Behavior 8."""
    assert foundry.authoritative_tester_report(present) is None


def test_b09_authoritative_is_total():
    """Behavior 9 -- empty / None / generator / duplicates all accepted."""
    assert foundry.authoritative_tester_report([]) is None
    assert foundry.authoritative_tester_report(set()) is None
    assert foundry.authoritative_tester_report(None) is None
    gen = (n for n in ("tester.md", "tester2.md"))
    assert foundry.authoritative_tester_report(gen) == "tester2.md"
    dupes = ["tester.md", "tester.md", "tester2.md", "tester2.md"]
    assert foundry.authoritative_tester_report(dupes) == "tester2.md"


def test_b09b_authoritative_touches_no_filesystem(monkeypatch, tmp_path):
    """Behavior 9 -- prove it is PURE: every filesystem door is booby-trapped, and the
    trap is removed BEFORE the assertion so a failure report can still read files."""
    monkeypatch.chdir(tmp_path)
    with monkeypatch.context() as m:
        m.setattr(pathlib.Path, "is_file", _boom)
        m.setattr(pathlib.Path, "exists", _boom)
        m.setattr(pathlib.Path, "open", _boom)
        m.setattr(pathlib.Path, "read_text", _boom)
        m.setattr(builtins, "open", _boom)
        got = foundry.authoritative_tester_report({"tester.md", "tester2.md"})
        got_none = foundry.authoritative_tester_report({"reviewer.md"})
    assert got == "tester2.md"
    assert got_none is None


# --------------------------------------------------------------- Behaviors 10-13
def test_b10_read_authoritative_two_report_case(tmp_path):
    """Behavior 10 -- the cap-killed `tester.md` checkpoint does NOT decide the row."""
    d = _dir_with(tmp_path, tester_md="FAIL", tester2_md="PASS")
    assert foundry.read_authoritative_tester_result(d) == "PASS"


def test_b11_read_authoritative_three_report_and_single_cases(tmp_path):
    """Behavior 11 -- iteration 177's real shape (FAIL/FAIL/PASS), plus the 338-row
    single-report majority."""
    three = _dir_with(tmp_path / "a", tester_md="FAIL", tester2_md="FAIL",
                      tester3_md="PASS")
    assert foundry.read_authoritative_tester_result(three) == "PASS"
    one = _dir_with(tmp_path / "b", tester_md="PASS")
    assert foundry.read_authoritative_tester_result(one) == "PASS"
    only_fail = _dir_with(tmp_path / "c", tester_md="FAIL")
    assert foundry.read_authoritative_tester_result(only_fail) == "FAIL"
    gap = _dir_with(tmp_path / "d", tester_md="PASS", tester3_md="FAIL")
    assert foundry.read_authoritative_tester_result(gap) == "FAIL"


def test_b12_newest_present_unparseable_is_none_even_with_a_clean_older(tmp_path):
    """Behavior 12 -- presence decides WHICH report is authoritative; its parse result
    is then reported as-is. No fallback to an older, cleaner report."""
    d = tmp_path / "iter"
    d.mkdir(parents=True)
    _report(d, "tester.md", "PASS")
    (d / "tester2.md").write_text("cut short by the stage cap\n\nPROGRESS: CHECKPOINT\n")
    assert foundry.read_authoritative_tester_result(d) is None

    d2 = tmp_path / "iter2"
    d2.mkdir(parents=True)
    _report(d2, "tester.md", "FAIL")
    _report(d2, "tester2.md", "PASS")
    (d2 / "tester3.md").write_text("")            # empty newest report
    assert foundry.read_authoritative_tester_result(d2) is None


def test_b13_read_authoritative_is_total(tmp_path, monkeypatch):
    """Behavior 13 -- empty dir / missing dir / OSError all return None, never raise."""
    empty = tmp_path / "empty"
    empty.mkdir(parents=True)
    (empty / "reviewer.md").write_text("VERDICT: APPROVE\n")
    assert foundry.read_authoritative_tester_result(empty) is None
    assert foundry.read_authoritative_tester_result(tmp_path / "nope" / "iter") is None

    d = _dir_with(tmp_path, tester_md="PASS")
    with monkeypatch.context() as m:
        m.setattr(pathlib.Path, "is_file", _oserror)
        got = foundry.read_authoritative_tester_result(d)
    assert got is None, "an OSError from the probe must read as None"


def _oserror(*a, **k):
    raise OSError(5, "Input/output error")


# --------------------------------------------------------------- Behaviors 14-15
def test_b14_gather_outcomes_uses_the_bare_name_seam(tmp_path, monkeypatch):
    """Behavior 14 -- monkeypatching the module-level seam changes the ledger."""
    cfg = _cfg(tmp_path)
    for n in (1, 2):
        d = _iter_dir(cfg, n)
        (d / "reviewer.md").write_text("notes\n\nVERDICT: APPROVE\n")
        _report(d, "tester.md", "FAIL")
    monkeypatch.setattr(foundry, "read_authoritative_tester_result", lambda p: "PASS")
    summary = foundry.gather_outcomes(cfg)
    assert [r.tester for r in summary.records] == ["PASS", "PASS"]
    assert summary.tester_passed == 2 and summary.tester_failed == 0

    monkeypatch.setattr(foundry, "read_authoritative_tester_result", lambda p: None)
    summary2 = foundry.gather_outcomes(cfg)
    assert [r.tester for r in summary2.records] == [None, None]
    assert summary2.tester_passed == 0 and summary2.tester_failed == 0


def test_b14b_gather_outcomes_holds_no_hardcoded_tester_md():
    """Behavior 14 -- the literal is gone from the function, docstring included."""
    src = inspect.getsource(foundry.gather_outcomes)
    assert "tester.md" not in src, "gather_outcomes still hardcodes a report filename"
    assert "read_authoritative_tester_result" in src


def test_b15_end_to_end_tmp_product_ledger(tmp_path):
    """Behavior 15 -- the real iter-177/179 shape, hermetic, through the public seam."""
    cfg = _cfg(tmp_path)
    d = _iter_dir(cfg, 7)
    (d / "reviewer.md").write_text("review notes\n\nVERDICT: APPROVE\n")
    _report(d, "tester.md", "FAIL")               # cap-killed checkpoint
    _report(d, "tester2.md", "PASS")              # the round the gate acted on
    (d / "final.md").write_text("gate notes\n\nACTION: PUSHED\n")

    summary = foundry.gather_outcomes(cfg)
    assert len(summary.records) == 1
    row = summary.records[0]
    assert row.iteration == 7
    assert row.tester == "PASS", f"row was {row!r}"
    assert summary.tester_passed == 1
    assert summary.tester_failed == 0
    # untouched columns
    assert row.review == "APPROVE"
    assert row.action == "PUSHED"
    assert summary.approved == 1 and summary.changes_required == 0
    # the human surface agrees with the machine surface
    assert "PASS" in summary.render()


# ------------------------------------------------------------------- Behavior 16
def test_b16_frozen_dict_contracts_are_byte_identical(tmp_path):
    """Behavior 16 -- no new key on either value object."""
    rec = foundry.IterationOutcome(iteration=1, review="APPROVE", tester="PASS",
                                   action="PUSHED")
    assert list(rec.to_dict().keys()) == list(RECORD_KEYS)
    cfg = _cfg(tmp_path)
    d = _iter_dir(cfg, 1)
    _report(d, "tester2.md", "PASS")
    summary = foundry.gather_outcomes(cfg)
    keys = list(summary.to_dict().keys())
    assert keys == list(SUMMARY_KEYS), f"got {keys!r}"
    assert len(keys) == 8


# ------------------------------------------------------------------- Behavior 17
def test_b17_final_role_card_names_the_helper_and_stays_ascii():
    """Behavior 17 -- the gate stops re-deriving the authoritative report by hand."""
    card = _ROOT / "roles" / "final.md"
    text = card.read_text()
    text.encode("ascii")                          # raises if a non-ASCII byte crept in
    assert ("authoritative_tester_report" in text
            or "read_authoritative_tester_result" in text)
    # the mention must live in gate checklist item 2, not merely somewhere in the file
    start = text.index("2. Tester result is PASS")
    end = text.index("\n3. ", start)
    item2 = text[start:end]
    assert ("authoritative_tester_report" in item2
            or "read_authoritative_tester_result" in item2), item2


# ------------------------------------------------------ acceptance-criteria probes
def test_ac_both_modules_still_import():
    """Acceptance criterion: foundry and dispatcher stay importable."""
    import importlib
    assert importlib.import_module("foundry") is foundry
    assert importlib.import_module("dispatcher") is not None
