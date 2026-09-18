"""Iteration 373 -- BLACK-BOX behavior tests for `watchdog-arm`: a read-only, report-only
verb that says whether any periodic-schedule entry on this box invokes the shipped
`watchdog.py` resurrection path.

Spec under test: products/_platform/state/iter-373/pm.md ("one read-only, report-only
verb printing a single `watchdog-arm:` line -- a three-valued verdict on whether any
periodic-schedule entry on this box invokes the shipped `watchdog.py`"), read together
with README section `# 60.`, which documents the verb's own contract.

  1.  An UNCOMMENTED entry naming `WATCHDOG_ARM_TOKEN` -> one line opening with the
      lowercase word `armed`, naming BOTH the matching count and the uncommented total.
  2.  Uncommented entries, none naming the token -> one line opening with the uppercase
      alarm `NOT-ARMED`, naming the total and carrying a remedy naming the token.
  3.  Only blanks and `#` comments -> `no-schedule`; a COMMENTED-OUT token entry is no
      entry at all, so it reads `no-schedule` and can NEVER read `armed`.
  4.  The three leading verdict words are pairwise distinct and no body contains another
      body's leading word.
  5.  COUNTS ONLY: no text the function did not author reaches its output (an
      absolute-looking path, a ship sentinel, a preship token, a 300-char run).
  6.  TOTAL: over a hostile table it always returns a non-empty single-line `str` and
      raises nothing.
  7.  `probe_watchdog_arm()` -> `None` on a not-ok seam AND on a raising seam; on success
      exactly `watchdog_arm_line(<seam stdout>)`; the seam is reached by BARE module name
      and called EXACTLY ONCE.
  8.  `watchdog_arm_cli()` prints EXACTLY ONE line opening with `WATCHDOG_ARM_PREFIX`,
      renders a `None` probe as an UNKNOWN sentence sharing no leading verdict word with
      the three real bodies, returns 0 in all FOUR states, and writes nothing to disk.
  9.  DORMANT + RESUME-SAFE: `dispatcher.py` and the eight pipeline/gate functions name
      none of the new symbols, `run_doctor` is still exactly four `Check`s, and README
      `# 0.` still reads `PLUS SIX drift lines` and still lacks `PLUS FIVE drift lines`.
  10. `readme_verb_index_gaps` audits `ok=True` / `missing_verbs=()` over the live README
      and the live verb set -- TWO-SIDED: delete the `# 60.` section and the same audit
      reports `missing_verbs=('watchdog-arm',)`, so the section is a ship requirement.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-373 PM
spec, the product README / roadmap / archive TEXT, the pre-existing conventions under
`tests/`, and the product's OWN observable behavior by importing and CALLING its public
names and by running `foundry.py watchdog-arm --help`.  The implementation SOURCE of
`foundry.py` / `dispatcher.py` was NOT read by this author, nor the engineer's notes, the
reviewer's notes, the fix notes, `IMPLEMENTATION.patch`, or any `git diff`.  Behavior 9's
symbol census is a MACHINE scan (`inspect.getsource` inside the test), which is the
convention iterations 336 and 361 already use for the same invariant.

FRESH-CLONE SAFE / OFFLINE: every listing is a synthetic in-memory string; the only
filesystem writes happen inside `tmp_path`; the only ambient files read are TRACKED
(`README.md`, `foundry.py`, `PLATFORM_ROADMAP.md`, `PLATFORM_ROADMAP_ARCHIVE.md`) and are
reached through `pathlib.Path(__file__).parents[1]`, never an absolute machine path.  No
real subprocess, git, network or clock: `foundry.run_cmd` is scripted in every case that
would otherwise read the live schedule, and the repo's ambient crontab is never consulted.
"""
from __future__ import annotations

import contextlib
import inspect
import io
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe (the quality bar)

THIS_ITER = 373

ARMED = "armed"
NOT_ARMED = "NOT-ARMED"
NO_SCHEDULE = "no-schedule"
VERDICT_WORDS = (ARMED, NOT_ARMED, NO_SCHEDULE)

NEW_SYMBOLS = (
    "WATCHDOG_ARM_PREFIX",
    "WATCHDOG_ARM_TOKEN",
    "WATCHDOG_ARM_LISTING_CMD",
    "WATCHDOG_ARM_TIMEOUT_SECONDS",
    "watchdog_arm_line",
    "probe_watchdog_arm",
    "watchdog_arm_cli",
)

# The eight functions the spec pins as byte-free of the new verb (behavior 9).
DORMANT_HOSTS = (
    "run_iteration", "run_stage", "build_prompt", "run_continuous",
    "postrelease_step", "preship_cli", "run_doctor", "run_doctor_cli",
)

# Needles for behavior 5.  Each one is asserted PRESENT in the fixture listing first
# (a positive control), so a typo here can never make the absence legs vacuous.
NEEDLE_PATH = "/opt/nowhere/bin/resurrect.sh"
NEEDLE_SHIP = "ACTION: PUSHED 0ffbeef"
NEEDLE_PRESHIP = "PRESHIP: GO"
NEEDLE_RUN = "z" * 300
NEEDLES = (NEEDLE_PATH, NEEDLE_SHIP, NEEDLE_PRESHIP, NEEDLE_RUN)

# ---------------------------------------------------------------- helpers


class _Res:
    """Stand-in for the run_cmd result type: only `.ok` / `.out` are contracted."""

    def __init__(self, ok, out=""):
        self.ok = ok
        self.out = out


def _script_run_cmd(monkeypatch, *, ok=True, out="", raises=None):
    """Replace the ONE listing seam by BARE module name; return the call recorder."""
    calls: list[tuple] = []

    def _fake(args, cwd=None, timeout=None):
        calls.append((tuple(args) if args is not None else None, cwd, timeout))
        if raises is not None:
            raise raises
        return _Res(ok, out)

    monkeypatch.setattr(foundry, "run_cmd", _fake)
    return calls


def _capture(fn):
    """Run fn() with stdout+stderr captured; return (rc, out)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = fn()
    return rc, buf.getvalue()


def _armed_listing() -> str:
    """2 matching entries out of 5 uncommented -- a count pair that cannot coincide."""
    return (
        "# a disabled job, not an entry\n"
        "\n"
        "PATH=/usr/bin:/bin\n"
        "*/5 * * * * cd repo && python3 watchdog.py --once\n"
        "0 * * * * echo housekeeping\n"
        "17 3 * * * python3 watchdog.py --daily\n"
        "*/9 * * * * true\n"
    )


def _not_armed_listing() -> str:
    """3 uncommented entries, none of them the resurrection probe."""
    return (
        "# watchdog.py used to live here\n"
        "0 * * * * echo housekeeping\n"
        "*/9 * * * * true\n"
        "30 4 * * * echo rotate-logs\n"
    )


def _no_schedule_listing() -> str:
    return "# */5 * * * * python3 watchdog.py\n"


def _bodies() -> dict:
    return {
        ARMED: foundry.watchdog_arm_line(_armed_listing()),
        NOT_ARMED: foundry.watchdog_arm_line(_not_armed_listing()),
        NO_SCHEDULE: foundry.watchdog_arm_line(_no_schedule_listing()),
    }


def _readme_text() -> str:
    return (_ROOT / "README.md").read_text(encoding="utf-8")


def _readme_section(text: str, heading_no: int) -> str:
    """The `# NN.` section body, up to (not including) the next `# NN.` heading."""
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


def _live_verbs() -> tuple:
    return foundry.foundry_cli_verbs((_ROOT / "foundry.py").read_text(encoding="utf-8"))


def _doctor_cfg(tmp_path):
    idx = tmp_path / "IDX.md"
    idx.write_text("# roadmap\n\nsome prose\n", encoding="utf-8")
    return foundry.ProductConfig(
        name="demo",
        repo="products/_platform/state/iter-373",
        allowed_push_repo="demo",
        roadmap=str(idx),
        learnings=str(tmp_path / "no-such-learnings.md"),
        work_root=str(tmp_path),
    )


def _stub_checks(monkeypatch):
    class _Chk:
        def __init__(self, name, ok, detail="detail-text"):
            self.name, self.ok, self.detail = name, ok, detail

    for nm in ("power", "agent", "uv", "remote"):
        monkeypatch.setattr(foundry, f"check_{nm}",
                            lambda *a, _n=nm, **k: _Chk(_n, True))


def _tree(root: pathlib.Path) -> set:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


# ---------------------------------------------------------------- constants


def test_constants_are_the_documented_shapes() -> None:
    assert foundry.WATCHDOG_ARM_PREFIX == "watchdog-arm:"
    assert foundry.WATCHDOG_ARM_TOKEN == "watchdog.py"
    assert isinstance(foundry.WATCHDOG_ARM_TIMEOUT_SECONDS, int)
    assert foundry.WATCHDOG_ARM_TIMEOUT_SECONDS > 0
    cmd = foundry.WATCHDOG_ARM_LISTING_CMD
    assert isinstance(cmd, (tuple, list)) and cmd, f"listing cmd must be a sequence: {cmd!r}"
    assert all(isinstance(a, str) for a in cmd)


def test_prefix_is_pairwise_distinct_from_the_six_shipped_drift_prefixes() -> None:
    """AC: a reader must never confuse this line with a doctor drift line."""
    shipped = [
        foundry.LIVE_LAG_PREFIX, foundry.LEARNINGS_HEAD_PREFIX,
        foundry.ROADMAP_INDEX_PREFIX, foundry.STAGE_BUDGET_PREFIX,
        foundry.TEST_TOUCH_PREFIX, foundry.AUTH_LOSS_PREFIX,
    ]
    assert len(set(shipped)) == 6, f"expected six distinct drift prefixes: {shipped}"
    mine = foundry.WATCHDOG_ARM_PREFIX
    for other in shipped:
        assert mine != other
        assert mine not in other and other not in mine, \
            f"{mine!r} collides with the shipped drift prefix {other!r}"


# ---------------------------------------------------------------- behavior 1


def test_b1_armed_returns_one_lowercase_armed_line() -> None:
    line = foundry.watchdog_arm_line(_armed_listing())
    assert isinstance(line, str) and line
    assert "\n" not in line, f"verdict must be ONE line: {line!r}"
    assert line.split()[0] == ARMED, f"leading word must be lowercase `armed`: {line!r}"


def test_b1_armed_names_both_the_matching_count_and_the_uncommented_total() -> None:
    line = foundry.watchdog_arm_line(_armed_listing())
    assert re.search(r"\b2\b", line), f"matching count 2 missing: {line!r}"
    assert re.search(r"\b5\b", line), f"uncommented total 5 missing: {line!r}"


def test_b1_a_single_matching_entry_is_enough_to_read_armed() -> None:
    line = foundry.watchdog_arm_line(f"*/5 * * * * python3 {foundry.WATCHDOG_ARM_TOKEN}\n")
    assert line.split()[0] == ARMED, line
    assert re.search(r"\b1\b", line), f"the 1-of-1 counts must both appear: {line!r}"


def test_b1_the_match_is_the_token_and_not_a_bare_substring_of_the_word() -> None:
    """A `watchdog` mention with no `.py` is NOT the resurrection probe."""
    line = foundry.watchdog_arm_line("*/5 * * * * echo watchdog is a nice word\n")
    assert line.split()[0] == NOT_ARMED, line


# ---------------------------------------------------------------- behavior 2


def test_b2_not_armed_is_the_uppercase_alarm_naming_the_total() -> None:
    line = foundry.watchdog_arm_line(_not_armed_listing())
    assert "\n" not in line and line
    assert line.split()[0] == NOT_ARMED, f"leading word must be `NOT-ARMED`: {line!r}"
    assert re.search(r"\b3\b", line), f"uncommented total 3 missing: {line!r}"


def test_b2_not_armed_carries_a_remedy_naming_the_token() -> None:
    line = foundry.watchdog_arm_line(_not_armed_listing())
    head, _, remedy = line.partition(NOT_ARMED)
    assert head == ""
    assert foundry.WATCHDOG_ARM_TOKEN in remedy, \
        f"the alarm must say WHAT to add: {line!r}"


# ---------------------------------------------------------------- behavior 3


def test_b3_blank_and_comment_only_listing_reads_no_schedule() -> None:
    for listing in ("", "\n\n\n", "# just a note\n\n#another\n", "   \n\t\n"):
        line = foundry.watchdog_arm_line(listing)
        assert line.split()[0] == NO_SCHEDULE, f"{listing!r} -> {line!r}"


def test_b3_a_commented_out_token_entry_is_no_entry_at_all() -> None:
    """A comment is not a schedule: the spec's own fixture, verbatim."""
    line = foundry.watchdog_arm_line(_no_schedule_listing())
    assert line.split()[0] == NO_SCHEDULE, line
    assert ARMED not in line, f"a disabled job must NEVER read armed: {line!r}"


def test_b3_a_commented_token_entry_beside_a_live_one_still_reads_not_armed() -> None:
    """The comment may not contribute to the MATCH count either."""
    listing = (f"# */5 * * * * python3 {foundry.WATCHDOG_ARM_TOKEN}\n"
               "0 * * * * echo housekeeping\n")
    line = foundry.watchdog_arm_line(listing)
    assert line.split()[0] == NOT_ARMED, line
    assert re.search(r"\b1\b", line), f"one uncommented entry must be counted: {line!r}"


def test_b3_indented_comment_markers_are_still_comments() -> None:
    line = foundry.watchdog_arm_line("   # */5 * * * * python3 watchdog.py\n\t#x\n")
    assert line.split()[0] == NO_SCHEDULE, line


# ---------------------------------------------------------------- behavior 4


def test_b4_the_three_leading_verdict_words_are_pairwise_distinct() -> None:
    bodies = _bodies()
    leads = [b.split()[0] for b in bodies.values()]
    assert leads == [ARMED, NOT_ARMED, NO_SCHEDULE], leads
    assert len(set(leads)) == 3, leads


@pytest.mark.parametrize("mine", VERDICT_WORDS)
def test_b4_no_body_contains_another_bodys_leading_word(mine) -> None:
    bodies = _bodies()
    body = bodies[mine]
    for other in VERDICT_WORDS:
        if other == mine:
            continue
        assert other not in body, \
            f"the {mine} body carries the {other} verdict word: {body!r}"


# ---------------------------------------------------------------- behavior 5


def _hostile_listing(with_token: bool) -> str:
    entries = [
        f"0 * * * * {NEEDLE_PATH}",
        f"1 * * * * echo {NEEDLE_SHIP}",
        f"2 * * * * echo {NEEDLE_PRESHIP}",
        f"3 * * * * echo {NEEDLE_RUN}",
    ]
    if with_token:
        entries.append(f"4 * * * * python3 {foundry.WATCHDOG_ARM_TOKEN}")
    return "\n".join(entries) + "\n"


@pytest.mark.parametrize("with_token", [False, True], ids=["not-armed", "armed"])
def test_b5_positive_control_the_needles_really_are_in_the_fixture(with_token) -> None:
    """Without this leg every absence assertion below could pass on a typo."""
    listing = _hostile_listing(with_token)
    for needle in NEEDLES:
        assert needle in listing, f"needle absent from the FIXTURE: {needle[:40]!r}"


@pytest.mark.parametrize("with_token", [False, True], ids=["not-armed", "armed"])
def test_b5_counts_only_no_entry_body_reaches_the_output(with_token) -> None:
    line = foundry.watchdog_arm_line(_hostile_listing(with_token))
    expect = ARMED if with_token else NOT_ARMED
    assert line.split()[0] == expect, line
    for needle in NEEDLES:
        assert needle not in line, \
            f"an entry body reached the verdict ({needle[:40]!r}): {line!r}"
    assert "\n" not in line


def test_b5_the_verdict_stays_short_however_long_the_entries_are() -> None:
    """A counts-only line cannot grow with the listing."""
    small = foundry.watchdog_arm_line("0 * * * * echo hi\n")
    big = foundry.watchdog_arm_line("0 * * * * echo " + ("y" * 5000) + "\n")
    assert small == big, f"the verdict varied with an entry BODY:\n{small!r}\n{big!r}"


# ---------------------------------------------------------------- behavior 6


HOSTILE_INPUTS = [
    ("empty", ""),
    ("whitespace", "   \n\t \n \n"),
    ("non-str-int", 12345),
    ("non-str-none", None),
    ("non-str-list", ["0 * * * * python3 watchdog.py"]),
    ("crlf", "0 * * * * python3 watchdog.py\r\n1 * * * * echo hi\r\n"),
    ("tabs", "\t0 * * * * echo hi\n\t*/5 * * * * python3 watchdog.py\n"),
    ("one-huge-line", "0 * * * * echo " + ("q" * 10000)),
    ("shorter-than-token", "a"),
    ("no-trailing-newline", "0 * * * * echo hi"),
    ("bare-token-only", "watchdog.py"),
]


@pytest.mark.parametrize("label,value", HOSTILE_INPUTS, ids=[i for i, _ in HOSTILE_INPUTS])
def test_b6_total_over_the_hostile_table(label, value) -> None:
    line = foundry.watchdog_arm_line(value)
    assert isinstance(line, str), f"{label} -> {type(line).__name__}"
    assert line.strip(), f"{label} -> empty verdict {line!r}"
    assert "\n" not in line, f"{label} -> multi-line verdict {line!r}"
    assert line.split()[0] in VERDICT_WORDS, f"{label} -> unknown verdict {line!r}"


def test_b6_crlf_endings_do_not_glue_entries_into_one() -> None:
    line = foundry.watchdog_arm_line(
        "0 * * * * python3 watchdog.py\r\n1 * * * * echo hi\r\n")
    assert line.split()[0] == ARMED, line
    assert re.search(r"\b2\b", line), f"CRLF must split into TWO entries: {line!r}"


def test_b6_a_non_str_never_reads_armed() -> None:
    """Fail SAFE: an unparseable input may not claim the watchdog is running."""
    for value in (None, 12345, 3.5, object(), b"*/5 * * * * python3 watchdog.py"):
        line = foundry.watchdog_arm_line(value)
        assert line.split()[0] != ARMED, f"{value!r} -> {line!r}"


# ---------------------------------------------------------------- behavior 7


def test_b7_probe_returns_none_when_the_seam_is_not_ok(monkeypatch) -> None:
    calls = _script_run_cmd(monkeypatch, ok=False, out=_armed_listing())
    assert foundry.probe_watchdog_arm() is None
    assert len(calls) == 1, f"the seam must be called EXACTLY once: {calls}"


def test_b7_probe_returns_none_when_the_seam_raises(monkeypatch) -> None:
    calls = _script_run_cmd(monkeypatch, raises=OSError("no crontab binary"))
    assert foundry.probe_watchdog_arm() is None
    assert len(calls) == 1, f"the seam must be called EXACTLY once: {calls}"


@pytest.mark.parametrize("listing_fn,expect", [
    (_armed_listing, ARMED),
    (_not_armed_listing, NOT_ARMED),
    (_no_schedule_listing, NO_SCHEDULE),
], ids=["armed", "not-armed", "no-schedule"])
def test_b7_probe_success_returns_exactly_the_pure_line(monkeypatch, listing_fn, expect) -> None:
    listing = listing_fn()
    calls = _script_run_cmd(monkeypatch, ok=True, out=listing)
    got = foundry.probe_watchdog_arm()
    assert got == foundry.watchdog_arm_line(listing), \
        f"probe must return the PURE line verbatim:\n{got!r}"
    assert got.split()[0] == expect, got
    assert len(calls) == 1, f"the seam must be called EXACTLY once: {calls}"


def test_b7_the_seam_bites_by_bare_module_name(monkeypatch) -> None:
    """If the seam were captured at def-time this recorder would stay empty and the
    real machine schedule would be read instead."""
    calls = _script_run_cmd(monkeypatch, ok=True, out="0 * * * * echo hi\n")
    foundry.probe_watchdog_arm()
    assert len(calls) == 1
    args, _cwd, timeout = calls[0]
    assert args == tuple(foundry.WATCHDOG_ARM_LISTING_CMD), args
    assert timeout == foundry.WATCHDOG_ARM_TIMEOUT_SECONDS, timeout


def test_b7_probe_is_read_only_and_writes_nothing(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    _script_run_cmd(monkeypatch, ok=True, out=_armed_listing())
    before = _tree(tmp_path)
    foundry.probe_watchdog_arm()
    assert _tree(tmp_path) == before, "the probe wrote to disk"


# ---------------------------------------------------------------- behavior 8


CLI_STATES = [
    ("armed", _armed_listing),
    ("not-armed", _not_armed_listing),
    ("no-schedule", _no_schedule_listing),
]


@pytest.mark.parametrize("label,listing_fn", CLI_STATES, ids=[l for l, _ in CLI_STATES])
def test_b8_cli_prints_exactly_one_prefixed_line_and_exits_zero(
        monkeypatch, label, listing_fn) -> None:
    _script_run_cmd(monkeypatch, ok=True, out=listing_fn())
    rc, out = _capture(foundry.watchdog_arm_cli)
    assert rc == 0, f"{label}: rc={rc}\n{out}"
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, f"{label}: expected ONE line, got {lines}"
    assert lines[0].strip().startswith(foundry.WATCHDOG_ARM_PREFIX), lines[0]
    body = lines[0].strip()[len(foundry.WATCHDOG_ARM_PREFIX):].strip()
    assert body == foundry.watchdog_arm_line(listing_fn()), \
        f"{label}: the CLI must render the pure line verbatim: {body!r}"


def test_b8_unknown_state_prints_one_prefixed_line_and_exits_zero(monkeypatch) -> None:
    monkeypatch.setattr(foundry, "probe_watchdog_arm", lambda *a, **k: None)
    rc, out = _capture(foundry.watchdog_arm_cli)
    assert rc == 0, f"an unread listing must still exit 0\n{out}"
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, lines
    assert lines[0].strip().startswith(foundry.WATCHDOG_ARM_PREFIX), lines[0]


def test_b8_unknown_shares_no_leading_verdict_word_with_the_real_bodies(monkeypatch) -> None:
    """A listing that did not read must never read as `no-schedule`."""
    monkeypatch.setattr(foundry, "probe_watchdog_arm", lambda *a, **k: None)
    _rc, out = _capture(foundry.watchdog_arm_cli)
    body = out.strip()[len(foundry.WATCHDOG_ARM_PREFIX):].strip()
    assert body, out
    for word in VERDICT_WORDS:
        assert word not in body, \
            f"the UNKNOWN sentence carries the {word} verdict word: {body!r}"
    assert body.split()[0] not in VERDICT_WORDS, body


def test_b8_a_not_ok_seam_reaches_the_unknown_state_end_to_end(monkeypatch) -> None:
    """The real chain, not a patched probe: `crontab -l` failing must read UNKNOWN."""
    _script_run_cmd(monkeypatch, ok=False, out="")
    rc, out = _capture(foundry.watchdog_arm_cli)
    assert rc == 0, out
    body = out.strip()[len(foundry.WATCHDOG_ARM_PREFIX):].strip()
    for word in VERDICT_WORDS:
        assert word not in body, f"a failed read leaked a verdict word: {body!r}"


def test_b8_cli_exits_zero_in_all_four_states(monkeypatch) -> None:
    seen = []
    for probe in (_armed_listing(), _not_armed_listing(), _no_schedule_listing(), None):
        if probe is None:
            monkeypatch.setattr(foundry, "probe_watchdog_arm", lambda *a, **k: None)
        else:
            monkeypatch.setattr(foundry, "probe_watchdog_arm",
                                lambda *a, _p=probe, **k: foundry.watchdog_arm_line(_p))
        rc, out = _capture(foundry.watchdog_arm_cli)
        seen.append(rc)
        assert out.strip(), "a state printed nothing"
    assert seen == [0, 0, 0, 0], seen


@pytest.mark.parametrize("label,listing_fn", CLI_STATES + [("unknown", None)],
                         ids=["armed", "not-armed", "no-schedule", "unknown"])
def test_b8_cli_writes_nothing_to_disk(monkeypatch, tmp_path, label, listing_fn) -> None:
    monkeypatch.chdir(tmp_path)
    if listing_fn is None:
        _script_run_cmd(monkeypatch, ok=False, out="")
    else:
        _script_run_cmd(monkeypatch, ok=True, out=listing_fn())
    before = _tree(tmp_path)
    _capture(foundry.watchdog_arm_cli)
    assert _tree(tmp_path) == before, f"{label}: the report-only verb wrote to disk"


def test_b8_the_verb_is_reachable_through_the_real_cli_dispatch(monkeypatch) -> None:
    """In-process, no subprocess: `main(["watchdog-arm"])` must reach the verb."""
    _script_run_cmd(monkeypatch, ok=True, out=_armed_listing())
    rc, out = _capture(lambda: foundry.main(["watchdog-arm"]))
    assert rc == 0, f"rc={rc}\n{out}"
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, lines
    assert lines[0].strip().startswith(foundry.WATCHDOG_ARM_PREFIX), lines[0]
    assert lines[0].split()[1] == ARMED, lines[0]


def test_b8_the_verb_takes_no_config(monkeypatch, tmp_path) -> None:
    """`--config` is deliberately absent: the schedule belongs to the MACHINE."""
    _script_run_cmd(monkeypatch, ok=True, out=_armed_listing())
    cfg = tmp_path / "config.json"
    cfg.write_text("{}\n", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        _capture(lambda: foundry.main(["watchdog-arm", "--config", str(cfg)]))
    assert excinfo.value.code == 2, f"argparse must reject --config: {excinfo.value.code}"


def test_b8_cli_signature_takes_no_required_argument() -> None:
    sig = inspect.signature(foundry.watchdog_arm_cli)
    required = [p for p in sig.parameters.values()
                if p.default is inspect.Parameter.empty
                and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    assert required == [], f"the verb must need no config: {sig}"


# ---------------------------------------------------------------- behavior 9


@pytest.mark.parametrize("symbol", NEW_SYMBOLS)
def test_b9_dispatcher_names_none_of_the_new_symbols(symbol) -> None:
    src = inspect.getsource(dispatcher)
    assert symbol not in src, f"{symbol} reached dispatcher.py -- resume semantics moved"
    assert not hasattr(dispatcher, symbol), f"{symbol} is bound in the dispatcher namespace"


@pytest.mark.parametrize("host", DORMANT_HOSTS)
@pytest.mark.parametrize("symbol", NEW_SYMBOLS)
def test_b9_the_pipeline_and_gate_functions_stay_dormant(host, symbol) -> None:
    fn = getattr(foundry, host, None)
    assert fn is not None, f"foundry.{host} disappeared"
    src = inspect.getsource(fn)
    assert symbol not in src, f"{symbol} reached {host}: the verb is no longer dormant"


def test_b9_run_doctor_is_still_exactly_four_checks(monkeypatch, tmp_path) -> None:
    _stub_checks(monkeypatch)
    checks = foundry.run_doctor(_doctor_cfg(tmp_path))
    assert len(list(checks)) == 4, f"run_doctor is pinned at four Checks: {checks}"


def test_b9_readme_section_zero_still_reads_plus_six_drift_lines() -> None:
    section = _readme_section(_readme_text(), 0)
    assert "PLUS SIX drift lines" in section, "README `# 0.` lost its count word"
    assert "PLUS FIVE drift lines" not in section, "README `# 0.` regressed to FIVE"
    assert "PLUS SEVEN drift lines" not in section, \
        "the seventh drift line is OUT OF SCOPE for iteration 373"


def test_b9_the_new_verb_added_no_drift_line_to_section_zero() -> None:
    section = _readme_section(_readme_text(), 0)
    assert foundry.WATCHDOG_ARM_PREFIX not in section, \
        "watchdog-arm became a doctor drift line, which the spec puts out of scope"


# ---------------------------------------------------------------- behavior 10


def test_b10_the_verb_is_in_the_live_verb_set() -> None:
    verbs = _live_verbs()
    assert "watchdog-arm" in verbs, f"verb not registered: {verbs}"


def test_b10_readme_verb_index_audits_clean() -> None:
    audit = foundry.readme_verb_index_gaps(_readme_text(), _live_verbs())
    assert audit.missing_verbs == (), f"undocumented verbs: {audit.missing_verbs}"
    assert audit.ok, (
        f"missing={audit.missing_verbs} "
        f"no-invocation={audit.sections_without_invocation} "
        f"unknown={audit.unknown_invocations}")


def test_b10_two_sided_deleting_section_sixty_reds_the_same_audit() -> None:
    """Proves the `# 60.` section is a SHIP REQUIREMENT, not documentation polish."""
    text = _readme_text()
    section = _readme_section(text, 60)
    assert "watchdog-arm" in section, "`# 60.` does not document the verb"
    without = text.replace(section, "")
    assert without != text
    audit = foundry.readme_verb_index_gaps(without, _live_verbs())
    assert audit.missing_verbs == ("watchdog-arm",), \
        f"deleting `# 60.` must red the audit: {audit.missing_verbs}"
    assert not audit.ok


def test_b10_section_sixty_carries_no_bare_cli_invocation() -> None:
    section = _readme_section(_readme_text(), 60)
    assert foundry.bare_foundry_cli_findings(section, _live_verbs()) == [], \
        "the new README section invokes foundry.py without the documented runner"


def test_b10_roadmap_verb_figure_needs_no_repin() -> None:
    index = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    assert foundry.roadmap_verb_figure_gaps(index, len(_live_verbs())) == (), \
        "a roadmap verb-count figure went stale"


def test_b10_the_pm_records_for_this_iteration_are_in_the_tree() -> None:
    index = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    archive = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text(encoding="utf-8")
    assert foundry.roadmap_ledger_gaps(index, archive, (THIS_ITER,)) == [], \
        f"iteration {THIS_ITER} is missing a ledger row or archive bullet"
    assert foundry.roadmap_archive_gaps(index, archive) == [], \
        "index and archive disagree about which iterations shipped"
