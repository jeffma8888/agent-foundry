"""Iteration 378 -- BLACK-BOX behavior tests: `probe_watchdog_arm` reads cron's own
`no crontab for` sentence on a non-zero `crontab -l` as an EMPTY listing (verdict
`no-schedule`) instead of UNKNOWN; every other failed read stays UNKNOWN (`None`).

Spec under test: products/_platform/state/iter-378/pm.md, read together with README
section `# 60.` (the `watchdog-arm` contract) and iteration 373's pins under `tests/`.

  1.  `WATCHDOG_ARM_EMPTY_LISTING_MARKERS: tuple[str, ...]` exists, is a `tuple`, and
      contains the exact string `"no crontab for"`.
  2.  Seam -> `CmdResult(False, "crontab: no crontab for someuser\\n")` returns EXACTLY
      `watchdog_arm_line("")` (byte-identical) and the seam is called exactly once.
  3.  Marker match is a case-insensitive substring test over the whole `out`:
      `"No Crontab For someuser"` also reads `no-schedule`; `"no crontab fo"` -> `None`.
  4.  UNCHANGED failed reads: `(False, "")`, `(False, <armed-looking listing>)` and
      `(False, "run_cmd could not execute [...]: OSError")` all return `None`.
  5.  Marker consulted ONLY on the not-ok path: an `ok=True` listing whose comment
      mentions the phrase returns the `armed` line exactly as `watchdog_arm_line(out)`.
  6.  Read at CALL time: with the constant patched to `()` the behavior-2 input returns
      `None`; restoring it returns the `no-schedule` line again.
  7.  Public-safety: the username cron appends never reaches the returned line, which
      equals the constant `watchdog_arm_line("")` (built from no text of `out`).
  8.  A seam that RAISES still returns `None`.
  9.  End to end: `watchdog_arm_cli()` prints ONE line starting `watchdog-arm: no-schedule`,
      containing neither `UNKNOWN` nor the username, and returns 0.
  10. Docs agree with code: the probe's docstring names the constant; README `# 60.`
      names the constant, still carries the amended "AN UNREAD LISTING IS ITS OWN WORD"
      sentence, and no longer says a non-zero listing can ONLY read UNKNOWN.
  +   Ledger: the iteration's roadmap row + archive bullet are in the tree (the
      convention every iteration since 230 pins), and iteration 373's pins still pass.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-378 PM
spec, the product README / roadmap / archive TEXT, the pre-existing conventions under
`tests/` (iteration 373's file in particular), and the product's OWN observable behavior
by importing and CALLING its public names (`__doc__` included) and running the verb
in-process.  The implementation SOURCE of `foundry.py` / `dispatcher.py` was NOT read by
this author, nor the engineer's notes, the reviewer's notes, `IMPLEMENTATION.patch`, or
any `git diff`.

FRESH-CLONE SAFE / OFFLINE: `foundry.run_cmd` is scripted in EVERY case, so no real
`crontab`, subprocess, git, network or clock is touched; every listing is a synthetic
in-memory string; the only ambient files read are TRACKED (`README.md`,
`PLATFORM_ROADMAP.md`, `PLATFORM_ROADMAP_ARCHIVE.md`, `tests/test_iter373_behavior.py`)
and are reached through `pathlib.Path(__file__).parents[1]`, never an absolute machine
path.  No real username appears in any fixture (`someuser` / `zqxuser77` are synthetic).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe (the quality bar)

THIS_ITER = 378

MARKER = "no crontab for"
CONSTANT_NAME = "WATCHDOG_ARM_EMPTY_LISTING_MARKERS"
NO_SCHEDULE = "no-schedule"
ARMED = "armed"
NOT_ARMED = "NOT-ARMED"
VERDICT_WORDS = (ARMED, NOT_ARMED, NO_SCHEDULE)

# Synthetic usernames only -- never a real one (public-safety AC).
USER = "someuser"
ODD_USER = "zqxuser77"

CRON_EMPTY_STDERR = f"crontab: no crontab for {USER}\n"          # behavior 2 (verbatim)
CRON_EMPTY_MIXED_CASE = f"No Crontab For {USER}"                  # behavior 3
CRON_EMPTY_TRUNCATED = "no crontab fo"                            # behavior 3 (marker absent)
RUN_CMD_OSERROR = "run_cmd could not execute ['crontab', '-l']: OSError"  # behavior 4
COMMENTED_PHRASE_LISTING = f"# no crontab for {USER}\n*/5 * * * * python3 watchdog.py\n"


# ---------------------------------------------------------------- helpers


def _script_run_cmd(monkeypatch, *, ok=True, out="", raises=None):
    """Replace the ONE listing seam by BARE module name; return the call recorder.

    Returns the SHIPPED `CmdResult` (the frozen dataclass the spec names) rather than a
    stand-in, so the test drives exactly the type the production seam yields."""
    calls: list[tuple] = []

    def _fake(args, cwd=None, timeout=None):
        calls.append((tuple(args) if args is not None else None, cwd, timeout))
        if raises is not None:
            raise raises
        return foundry.CmdResult(ok, out)

    monkeypatch.setattr(foundry, "run_cmd", _fake)
    return calls


def _capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = fn()
    return rc, buf.getvalue()


def _armed_listing() -> str:
    return (
        "# a disabled job, not an entry\n"
        "*/5 * * * * cd repo && python3 watchdog.py --once\n"
        "0 * * * * echo housekeeping\n"
    )


def _empty_line() -> str:
    """The shipped `no-schedule` sentence for an EMPTY listing -- the behavior-2 oracle."""
    return foundry.watchdog_arm_line("")


def _readme_text() -> str:
    return (_ROOT / "README.md").read_text(encoding="utf-8")


def _readme_section(text: str, heading_no: int) -> str:
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if re.match(rf"^#\s*{heading_no}\.", ln):
            start = i
            break
    assert start is not None, f"README has no `# {heading_no}.` section"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^#\s*\d+\.", lines[j]):
            end = j
            break
    return "\n".join(lines[start:end])


# ---------------------------------------------------------------- shipped-type preconditions


def test_cmdresult_is_the_frozen_two_field_dataclass_the_spec_names() -> None:
    """The spec scripts the seam with `CmdResult(ok, out)`; pin that shape so every
    fixture below constructs the production type and not a look-alike."""
    import dataclasses
    assert dataclasses.is_dataclass(foundry.CmdResult)
    assert [f.name for f in dataclasses.fields(foundry.CmdResult)] == ["ok", "out"]
    res = foundry.CmdResult(False, "x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        res.ok = True  # type: ignore[misc]


def test_the_empty_listing_oracle_is_the_shipped_no_schedule_sentence() -> None:
    """`watchdog_arm_line("")` is the oracle behaviors 2/3/6/7/9 compare against; assert
    it is the `no-schedule` verdict with a ZERO count, so a later change to the pure
    core cannot silently move every oracle below."""
    line = _empty_line()
    assert line.split()[0] == NO_SCHEDULE, line
    assert re.search(r"\b0\b", line), f"an empty listing must count 0 entries: {line!r}"
    assert "\n" not in line


# ---------------------------------------------------------------- behavior 1


def test_b1_marker_constant_is_a_tuple_containing_the_cron_sentence() -> None:
    markers = getattr(foundry, CONSTANT_NAME, None)
    assert markers is not None, f"foundry.{CONSTANT_NAME} is missing"
    assert isinstance(markers, tuple), f"must be a tuple, got {type(markers).__name__}"
    assert MARKER in markers, f"exact string {MARKER!r} missing from {markers!r}"


def test_b1_every_marker_is_a_non_empty_str() -> None:
    """An empty-string member would be a substring of EVERY output and flip every failed
    read to `no-schedule` -- the fail-OPEN direction the verb exists to avoid."""
    markers = foundry.WATCHDOG_ARM_EMPTY_LISTING_MARKERS
    assert markers, "the tuple must not be empty"
    for m in markers:
        assert isinstance(m, str) and m.strip(), f"bad marker member: {m!r}"


# ---------------------------------------------------------------- behavior 2


def test_b2_cron_no_crontab_sentence_on_a_failed_read_yields_the_empty_listing_line(
        monkeypatch) -> None:
    calls = _script_run_cmd(monkeypatch, ok=False, out=CRON_EMPTY_STDERR)
    got = foundry.probe_watchdog_arm()
    assert got == _empty_line(), f"expected the byte-identical no-schedule line:\n{got!r}"
    assert len(calls) == 1, f"the seam must be called EXACTLY once: {calls}"


def test_b2_the_seam_is_reached_with_the_shipped_listing_cmd_and_timeout(monkeypatch) -> None:
    calls = _script_run_cmd(monkeypatch, ok=False, out=CRON_EMPTY_STDERR)
    foundry.probe_watchdog_arm()
    args, _cwd, timeout = calls[0]
    assert args == tuple(foundry.WATCHDOG_ARM_LISTING_CMD), args
    assert timeout == foundry.WATCHDOG_ARM_TIMEOUT_SECONDS, timeout


def test_b2_result_is_a_str_opening_with_the_no_schedule_verdict(monkeypatch) -> None:
    _script_run_cmd(monkeypatch, ok=False, out=CRON_EMPTY_STDERR)
    got = foundry.probe_watchdog_arm()
    assert isinstance(got, str) and got.split()[0] == NO_SCHEDULE, got


# ---------------------------------------------------------------- behavior 3


@pytest.mark.parametrize("out", [
    CRON_EMPTY_MIXED_CASE,
    f"NO CRONTAB FOR {USER}",
    f"crontab: No CronTab FoR {USER}\n",
    f"some prefix text\ncrontab: no crontab for {USER}\ntrailing\n",   # anywhere in out
    f"   no crontab for {USER}",                                      # leading whitespace
], ids=["title-case", "upper", "mixed", "embedded-line", "leading-ws"])
def test_b3_match_is_a_case_insensitive_substring_over_the_whole_out(monkeypatch, out) -> None:
    calls = _script_run_cmd(monkeypatch, ok=False, out=out)
    assert foundry.probe_watchdog_arm() == _empty_line(), out
    assert len(calls) == 1


@pytest.mark.parametrize("out", [
    CRON_EMPTY_TRUNCATED,
    "no crontab fo\n",
    "no  crontab for someone",     # double space breaks the exact substring
    "nocrontabfor someone",
    "no crontab",
    "crontab for someuser",
], ids=["truncated", "truncated-nl", "double-space", "glued", "prefix-only", "suffix-only"])
def test_b3_a_near_miss_of_the_marker_stays_unknown(monkeypatch, out) -> None:
    calls = _script_run_cmd(monkeypatch, ok=False, out=out)
    assert foundry.probe_watchdog_arm() is None, f"{out!r} must NOT read as empty"
    assert len(calls) == 1


# ---------------------------------------------------------------- behavior 4


@pytest.mark.parametrize("out", [
    "",
    _armed_listing(),
    RUN_CMD_OSERROR,
    "crontab: command not found",
    "crontab: you are not allowed to use this program",
    "timed out after 5s",
    "\x00\xff garbage \n\n",
], ids=["empty", "armed-looking", "oserror", "missing-binary", "permission", "timeout", "garbage"])
def test_b4_every_other_failed_read_still_returns_none(monkeypatch, out) -> None:
    calls = _script_run_cmd(monkeypatch, ok=False, out=out)
    assert foundry.probe_watchdog_arm() is None, f"failed read {out[:40]!r} leaked a verdict"
    assert len(calls) == 1


def test_b4_a_failed_read_of_an_armed_looking_listing_never_reads_armed(monkeypatch) -> None:
    """The armed-looking body is the sharp edge: a not-ok listing that NAMES watchdog.py
    must not be graded as if it had read."""
    _script_run_cmd(monkeypatch, ok=False, out=_armed_listing())
    got = foundry.probe_watchdog_arm()
    assert got is None, got


# ---------------------------------------------------------------- behavior 5


def test_b5_marker_is_ignored_on_the_ok_path_a_real_listing_is_never_re_read_as_empty(
        monkeypatch) -> None:
    calls = _script_run_cmd(monkeypatch, ok=True, out=COMMENTED_PHRASE_LISTING)
    got = foundry.probe_watchdog_arm()
    assert got == foundry.watchdog_arm_line(COMMENTED_PHRASE_LISTING), got
    assert got.split()[0] == ARMED, f"a live watchdog entry must read armed: {got!r}"
    assert got != _empty_line()
    assert len(calls) == 1


def test_b5_ok_listing_holding_only_the_phrase_as_a_comment_reads_the_pure_line(
        monkeypatch) -> None:
    """Both routes to `no-schedule` must agree, but for the RIGHT reason: on the ok path
    the pure core decides, and here it happens to be `no-schedule` because the only line
    is a comment -- the output must equal `watchdog_arm_line(out)` regardless."""
    out = f"# no crontab for {USER}\n"
    _script_run_cmd(monkeypatch, ok=True, out=out)
    got = foundry.probe_watchdog_arm()
    assert got == foundry.watchdog_arm_line(out), got


def test_b5_ok_listing_with_uncommented_phrase_reads_not_armed_not_empty(monkeypatch) -> None:
    """An UNCOMMENTED entry whose body carries the phrase is one entry, none matching."""
    out = f"0 * * * * echo no crontab for {USER}\n"
    _script_run_cmd(monkeypatch, ok=True, out=out)
    got = foundry.probe_watchdog_arm()
    assert got == foundry.watchdog_arm_line(out), got
    assert got.split()[0] == NOT_ARMED, got


# ---------------------------------------------------------------- behavior 6


def test_b6_markers_are_read_at_call_time(monkeypatch) -> None:
    _script_run_cmd(monkeypatch, ok=False, out=CRON_EMPTY_STDERR)
    original = foundry.WATCHDOG_ARM_EMPTY_LISTING_MARKERS
    monkeypatch.setattr(foundry, CONSTANT_NAME, ())
    assert foundry.probe_watchdog_arm() is None, \
        "with NO markers a failed read must stay UNKNOWN -- the tuple was captured at def-time"
    monkeypatch.setattr(foundry, CONSTANT_NAME, original)
    assert foundry.probe_watchdog_arm() == _empty_line()


def test_b6_a_substituted_marker_bites_at_call_time(monkeypatch) -> None:
    """The positive direction of behavior 6: a different marker set is honored."""
    _script_run_cmd(monkeypatch, ok=False, out="schedule table absent for this account")
    assert foundry.probe_watchdog_arm() is None
    monkeypatch.setattr(foundry, CONSTANT_NAME, ("table absent",))
    assert foundry.probe_watchdog_arm() == _empty_line()


# ---------------------------------------------------------------- behavior 7


def test_b7_the_username_cron_appends_never_reaches_the_returned_line(monkeypatch) -> None:
    out = f"crontab: no crontab for {ODD_USER}"
    assert ODD_USER in out  # positive control on the fixture
    _script_run_cmd(monkeypatch, ok=False, out=out)
    got = foundry.probe_watchdog_arm()
    assert got is not None
    assert ODD_USER not in got, f"the username leaked: {got!r}"
    assert got == _empty_line(), "the line must be the CONSTANT sentence, built from no text of out"


def test_b7_the_line_is_invariant_over_any_username_and_any_surrounding_text(monkeypatch) -> None:
    needles = (ODD_USER, "/opt/nowhere/bin/resurrect.sh", "ACTION: PUSHED 0ffbeef", "PRESHIP: GO", "w" * 300)
    out = "crontab: no crontab for " + " ".join(needles) + "\n"
    for n in needles:
        assert n in out
    _script_run_cmd(monkeypatch, ok=False, out=out)
    got = foundry.probe_watchdog_arm()
    assert got == _empty_line()
    for n in needles:
        assert n not in got, f"text of out reached the verdict: {n[:40]!r}"


# ---------------------------------------------------------------- behavior 8


@pytest.mark.parametrize("exc", [
    OSError("no crontab binary"),
    TimeoutError("listing hung"),
    RuntimeError("seam misbehaved"),
    ValueError("bad args"),
], ids=["oserror", "timeout", "runtime", "value"])
def test_b8_a_raising_seam_still_returns_none(monkeypatch, exc) -> None:
    calls = _script_run_cmd(monkeypatch, raises=exc)
    assert foundry.probe_watchdog_arm() is None
    assert len(calls) == 1


# ---------------------------------------------------------------- behavior 9


def test_b9_cli_end_to_end_prints_one_no_schedule_line_and_exits_zero(monkeypatch) -> None:
    _script_run_cmd(monkeypatch, ok=False, out=CRON_EMPTY_STDERR)
    rc, out = _capture(foundry.watchdog_arm_cli)
    assert rc == 0, f"rc={rc}\n{out}"
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected ONE line, got {lines}"
    line = lines[0].strip()
    assert line.startswith(f"{foundry.WATCHDOG_ARM_PREFIX} {NO_SCHEDULE}"), line
    assert "UNKNOWN" not in line, line
    assert USER not in line, f"username leaked into the CLI line: {line!r}"
    body = line[len(foundry.WATCHDOG_ARM_PREFIX):].strip()
    assert body == _empty_line(), body


def test_b9_cli_via_real_dispatch_reads_no_schedule_on_the_cron_sentence(monkeypatch) -> None:
    _script_run_cmd(monkeypatch, ok=False, out=CRON_EMPTY_STDERR)
    rc, out = _capture(lambda: foundry.main(["watchdog-arm"]))
    assert rc == 0, f"rc={rc}\n{out}"
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, lines
    assert lines[0].split()[1] == NO_SCHEDULE, lines[0]
    assert "UNKNOWN" not in lines[0]


def test_b9_cli_still_reads_unknown_on_every_other_failed_read(monkeypatch) -> None:
    """The 373 contract survives: only the cron sentence moved."""
    for out in ("", RUN_CMD_OSERROR, "crontab: command not found"):
        _script_run_cmd(monkeypatch, ok=False, out=out)
        rc, text = _capture(foundry.watchdog_arm_cli)
        assert rc == 0
        body = text.strip()[len(foundry.WATCHDOG_ARM_PREFIX):].strip()
        for word in VERDICT_WORDS:
            assert word not in body, f"{out!r}: a failed read leaked {word}: {body!r}"


def test_b9_cli_writes_nothing_to_disk(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    _script_run_cmd(monkeypatch, ok=False, out=CRON_EMPTY_STDERR)
    before = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")}
    _capture(foundry.watchdog_arm_cli)
    after = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")}
    assert after == before, "the report-only verb wrote to disk"


# ---------------------------------------------------------------- behavior 10


def test_b10_probe_docstring_names_the_marker_constant() -> None:
    doc = foundry.probe_watchdog_arm.__doc__ or ""
    assert CONSTANT_NAME in doc, "the probe docstring does not name the constant"
    # Behavior 10 asks ONLY that the constant be named; the sentence itself lives in
    # the constant, so its literal is asserted on the README leg, not here.


def test_b10_readme_section_sixty_names_the_constant_and_the_sentence() -> None:
    section = _readme_section(_readme_text(), 60)
    assert "watchdog-arm" in section
    assert CONSTANT_NAME in section, "README `# 60.` does not name the constant"
    assert MARKER in section, "README `# 60.` does not name cron's own sentence"
    assert NO_SCHEDULE in section


def test_b10_readme_amended_sentence_is_kept_not_deleted() -> None:
    section = _readme_section(_readme_text(), 60)
    assert "AN UNREAD LISTING IS ITS OWN WORD" in section, \
        "the sentence was to be AMENDED, not deleted"
    idx_kept = section.index("AN UNREAD LISTING IS ITS OWN WORD")
    idx_const = section.index(CONSTANT_NAME)
    assert idx_const > idx_kept, "the amendment must follow the kept sentence"
    assert "UNKNOWN" in section, "the README must still name the residual UNKNOWN state"


def test_b10_readme_no_longer_says_a_non_zero_listing_can_only_read_unknown() -> None:
    section = _readme_section(_readme_text(), 60)
    tail = section[section.index("AN UNREAD LISTING IS ITS OWN WORD"):]
    low = tail.lower()
    assert "can only read unknown" not in low
    assert "only ever read unknown" not in low
    assert "always unknown" not in low
    # The amended sentence must carry BOTH halves of the new rule.
    assert "completed read" in low or "is a completed read" in low, \
        "README must state the cron sentence IS a completed read"
    assert "any other non-zero" in low or "every other non-zero" in low, \
        "README must state every OTHER non-zero result stays UNKNOWN"


def test_b10_no_new_readme_section_was_added_verb_index_still_clean() -> None:
    verbs = foundry.foundry_cli_verbs((_ROOT / "foundry.py").read_text(encoding="utf-8"))
    audit = foundry.readme_verb_index_gaps(_readme_text(), verbs)
    assert audit.ok and audit.missing_verbs == (), \
        f"missing={audit.missing_verbs} unknown={audit.unknown_invocations}"


# ---------------------------------------------------------------- out-of-scope pins


def test_oos_unchanged_constants_and_the_no_schedule_sentence() -> None:
    assert foundry.WATCHDOG_ARM_TOKEN == "watchdog.py"
    assert tuple(foundry.WATCHDOG_ARM_LISTING_CMD) == ("crontab", "-l")
    assert foundry.WATCHDOG_ARM_PREFIX == "watchdog-arm:"


def test_oos_iteration_373_pins_still_pass_when_loaded_and_called_directly() -> None:
    """The spec forbids editing `tests/test_iter373_behavior.py`; from the isolated seat
    the two-sided proof is: its verbatim b7 assertions are still in the file, AND the
    pinned functions still pass when called directly."""
    path = _ROOT / "tests" / "test_iter373_behavior.py"
    text = path.read_text(encoding="utf-8")
    assert "def test_b7_probe_returns_none_when_the_seam_is_not_ok(" in text
    assert "def test_b7_probe_returns_none_when_the_seam_raises(" in text
    assert "def test_b8_a_not_ok_seam_reaches_the_unknown_state_end_to_end(" in text
    spec = importlib.util.spec_from_file_location("_iter373_probe_378", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    mp = pytest.MonkeyPatch()
    try:
        mod.test_b7_probe_returns_none_when_the_seam_is_not_ok(mp)
        mp.undo()
        mod.test_b7_probe_returns_none_when_the_seam_raises(mp)
        mp.undo()
        mod.test_b8_a_not_ok_seam_reaches_the_unknown_state_end_to_end(mp)
    finally:
        mp.undo()


def test_oos_dispatcher_does_not_name_the_new_constant() -> None:
    import inspect
    assert CONSTANT_NAME not in inspect.getsource(dispatcher)
    assert not hasattr(dispatcher, CONSTANT_NAME)


# ---------------------------------------------------------------- ledger


def test_ledger_the_pm_records_for_this_iteration_are_in_the_tree() -> None:
    index = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    archive = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text(encoding="utf-8")
    assert foundry.roadmap_ledger_gaps(index, archive, (THIS_ITER,)) == [], \
        f"iteration {THIS_ITER} is missing a ledger row or archive bullet"
    assert foundry.roadmap_archive_gaps(index, archive) == [], \
        "index and archive disagree about which iterations shipped"


def test_ledger_row_is_at_most_120_chars() -> None:
    index = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    rows = [ln for ln in index.splitlines() if ln.startswith(f"- iter {THIS_ITER} --")]
    assert rows, f"no `- iter {THIS_ITER} --` row in PLATFORM_ROADMAP.md"
    for r in rows:
        assert len(r) <= 120, f"ledger row too long ({len(r)}): {r!r}"
