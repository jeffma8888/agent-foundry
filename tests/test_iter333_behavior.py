"""Iteration 333 -- BLACK-BOX behavior tests: the external practice-register seam.

The iteration's product is `pm_practice_block`, the practice-side twin of the
gap-side `pm_gap_block` (iters 188/192): a read-only seam that injects an
EXTERNAL register's own generated `DIGEST.md` -- bounded, verbatim, never
re-ranked -- into the PM lead's prompt, and nothing else's.

ISOLATION CONTRACT (HONORED).  Every assertion below was derived from this
iteration's PM spec (`pm.md`, Expected Behaviors 1-11) and from the conventions
of the existing modules under `tests/` (chiefly `test_iter192_behavior.py`, the
twin seam's own iteration).  I did NOT read `foundry.py`'s implementation text,
`engineer.md`, `reviewer.md`, `IMPLEMENTATION.patch`, or `git diff`.  The new
surface is driven as a BLACK BOX: public functions called, module constants and
`inspect.signature` read, observable return strings asserted.

OFFLINE + FRESH-CLONE SAFE.  Every register fixture is built in `tmp_path`; no
test reads the real sibling register, asserts that its directory exists, pins an
ambient file count, spawns a subprocess, touches the network, or reads the
wall clock where the spec makes the clock an argument.  Behavior 11 asserts the
DECLARED tracked config only (OPERATOR 2026-08-11: a fresh clone has just the
tracked configs).  No absolute machine path and no username appears as a source
literal -- every path is built at runtime from `__file__` or `tmp_path`.
"""
from __future__ import annotations

import builtins
import datetime as dt
import inspect
import json
import os
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

THIS_ITER = 333

# the spec's own reference day, used everywhere `today` is an argument
TODAY = dt.date(2026, 9, 13)
ASOF = "2026-09-04"

HEADER_1 = "EXTERNAL PRACTICE REGISTER (read-only, generated digest): "
FEED_KEYS = {"register", "digest", "asof", "records", "unreadable"}

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
    "fix-tests": "tester.md",
    "tester-rerun": "tester.md",
    "tester-retry": "tester.md",
    "tester-retry2": "tester.md",
}


def _core_stages() -> tuple[str, ...]:
    """The stage names of `derive_stage_sequence(None)`.

    NOTE (the trap this helper exists to close): the sequence yields StageSpec
    OBJECTS, not strings, so `spec != "pm"` is true for every element and a
    loop written over the raw specs tests the non-pm branch five times and the
    pm branch never.  Read `.stage`.
    """
    return tuple(spec.stage for spec in foundry.derive_stage_sequence(None))


def _all_stages() -> tuple[str, ...]:
    """Every stage name `build_prompt` is asked to serve, derived structurally."""
    names = list(_core_stages())
    names.extend(("fix", "pm_scout_a", "pm_scout_b"))
    names.extend(sorted(foundry.STAGE_OUTPUT_NAMES))
    out: list[str] = []
    for name in names:
        if name not in out:
            out.append(name)
    return tuple(out)


# --------------------------------------------------------------------------
# fixtures -- ALWAYS under tmp_path so the real repo/state can never be touched
# --------------------------------------------------------------------------
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


def _load(base, label, common, **over):
    data = dict(common)
    data.update(over)
    path = pathlib.Path(base) / ("%s.json" % label)
    path.write_text(json.dumps(data), encoding="utf-8")
    cfg = foundry.load_config(str(path))
    lp = pathlib.Path(cfg.learnings)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text("## Patterns\n\n- a durable rule\n\n- [ENG iter01] a lesson\n",
                  encoding="utf-8")
    return cfg


def _cfg(tmp_path, sub="p", **over):
    base, common = _base_tree(tmp_path, sub=sub)
    return _load(base, "config", common, **over)


def _digest(asof=ASOF, body="a practice rule body\n"):
    """A digest shaped like the provider's: title, then a self-dating line 2."""
    return "# Practice register digest\nGenerated as of %s from 12 records\n\n%s" % (
        asof, body)


def _register(root, digest=None, records=3, extras=True):
    """Build `<root>/DIGEST.md` + `<root>/practices/<n>.json`. Returns str(root)."""
    root = pathlib.Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if digest is not None:
        (root / "DIGEST.md").write_text(digest, encoding="utf-8")
    prac = root / "practices"
    prac.mkdir(exist_ok=True)
    for i in range(records):
        (prac / ("p%02d.json" % i)).write_text(
            json.dumps({"id": "P-%02d" % i, "title": "a practice"}), encoding="utf-8")
    if extras:
        (prac / "notes.txt").write_text("not a record\n", encoding="utf-8")
        (prac / "skip.json.bak").write_text("{}\n", encoding="utf-8")
    return str(root)


_OMIT = object()  # "write NO DIGEST.md" -- distinct from "use the default digest"


def _opted_in(tmp_path, sub="p", digest=_OMIT, records=3, extras=True):
    """A cfg whose `practice_register` points at a freshly built tmp register."""
    base, common = _base_tree(tmp_path, sub=sub)
    if digest is _OMIT:
        digest = _digest()
    reg = _register(base / "reg", digest=digest, records=records, extras=extras)
    return _load(base, "config", common, practice_register=reg), reg


def _feed(register="", digest="", asof="", records=0, unreadable=0):
    return {"register": register, "digest": digest, "asof": asof,
            "records": records, "unreadable": unreadable}


def _prompt(cfg, stage):
    it_dir = pathlib.Path(cfg.work_root) / "state" / ("iter-%d" % THIS_ITER)
    it_dir.mkdir(parents=True, exist_ok=True)
    role = ROLE_FILE.get(stage, "pm.md")
    return foundry.build_prompt(cfg, THIS_ITER, stage, role,
                                it_dir / ("%s.md" % stage), it_dir, "extra!")


# --------------------------------------------------------------------------
# behavior 0 -- the DOMAIN, asserted before any matrix is measured over it
# --------------------------------------------------------------------------
def test_b0_stage_domain_is_not_vacuous() -> None:
    """A prompt/seam matrix over an empty or pm-less domain proves nothing."""
    core = _core_stages()
    assert core, "derive_stage_sequence(None) served no stage -- vacuous domain"
    assert all(isinstance(s, str) and s for s in core), core
    assert "pm" in core, (
        "no 'pm' stage in %r -- the seam's ONLY speaking branch would never be "
        "probed and a non-pm-only loop would report a false clean sweep" % (core,))
    assert len(_all_stages()) >= len(core)


def test_b0_modules_import_and_surface_exists() -> None:
    """The product quality bar: both modules import; the named surface is present."""
    assert foundry.__name__ == "foundry" and dispatcher.__name__ == "dispatcher"
    for name in ("gather_practices", "practice_age_days", "practice_advice",
                 "pm_practice_block", "PRACTICE_DIGEST_MAX_CHARS",
                 "PRACTICE_TRUNCATION_MARK"):
        assert hasattr(foundry, name), "foundry.%s missing" % name
    assert list(inspect.signature(foundry.pm_practice_block).parameters) == \
        ["cfg", "stage"]
    assert list(inspect.signature(foundry.gather_practices).parameters) == ["cfg"]
    assert list(inspect.signature(foundry.practice_age_days).parameters) == \
        ["asof", "today"]
    assert list(inspect.signature(foundry.practice_advice).parameters) == \
        ["feed", "today"]


# --------------------------------------------------------------------------
# behavior 1 -- the config field
# --------------------------------------------------------------------------
def test_b1_dataclass_field_defaults_to_empty_string() -> None:
    fields = getattr(foundry.ProductConfig, "__dataclass_fields__", {})
    assert "practice_register" in fields, "ProductConfig lacks practice_register"
    assert fields["practice_register"].default == ""
    assert fields["practice_register"].type in ("str", str)


def test_b1_config_omitting_the_key_loads_unchanged(tmp_path) -> None:
    """Every EXISTING config (which omits the key) must still load, with ''."""
    base, common = _base_tree(tmp_path)
    path = base / "x.json"
    path.write_text(json.dumps(common), encoding="utf-8")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "practice_register" not in raw, raw
    cfg = foundry.load_config(str(path))
    assert cfg.practice_register == ""


def test_b1_tilde_path_is_expanded_by_resolve(tmp_path) -> None:
    """A '~/...' value comes back ABSOLUTE with no literal tilde left."""
    cfg = _cfg(tmp_path, practice_register="~/some/dir")
    val = cfg.practice_register
    assert isinstance(val, str) and val
    assert "~" not in val, val
    assert os.path.isabs(val), val
    assert val.endswith(os.path.join("some", "dir")), val
    # same treatment as the sibling register field
    cfg2 = _cfg(tmp_path, sub="q", gap_register="~/some/dir",
                practice_register="~/some/dir")
    assert cfg2.practice_register == cfg2.gap_register


def test_b1_resolve_is_idempotent_on_the_new_field(tmp_path) -> None:
    """Fuzz past the spec: a second resolve() must not re-expand or mangle."""
    cfg = _cfg(tmp_path, practice_register="~/some/dir")
    once = cfg.practice_register
    cfg.resolve()
    assert cfg.practice_register == once


# --------------------------------------------------------------------------
# behavior 2 -- unconfigured gather is silent and does ZERO I/O
# --------------------------------------------------------------------------
def test_b2_unconfigured_gather_returns_the_empty_feed(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    assert cfg.practice_register == ""
    feed = foundry.gather_practices(cfg)
    assert set(feed) == FEED_KEYS, feed
    assert feed["register"] == "" and feed["digest"] == "" and feed["asof"] == ""
    assert feed["records"] == 0 and feed["unreadable"] == 0


def test_b2_unconfigured_gather_touches_no_file(tmp_path, monkeypatch) -> None:
    """With Path.read_text and Path.glob booby-trapped, the call still returns."""
    cfg = _cfg(tmp_path)

    def boom(*a, **k):
        raise AssertionError("unconfigured gather_practices performed I/O")

    monkeypatch.setattr(pathlib.Path, "read_text", boom)
    monkeypatch.setattr(pathlib.Path, "glob", boom)
    monkeypatch.setattr(pathlib.Path, "iterdir", boom)
    monkeypatch.setattr(pathlib.Path, "exists", boom)
    monkeypatch.setattr(builtins, "open", boom)
    feed = foundry.gather_practices(cfg)
    assert feed == _feed(), feed


# --------------------------------------------------------------------------
# behavior 3 -- configured gather reads the register
# --------------------------------------------------------------------------
def test_b3_configured_gather_reads_digest_asof_and_counts(tmp_path) -> None:
    text = _digest()
    cfg, reg = _opted_in(tmp_path, digest=text, records=3, extras=True)
    feed = foundry.gather_practices(cfg)
    assert set(feed) == FEED_KEYS, feed
    assert str(feed["register"]) == reg, feed["register"]
    assert feed["digest"] == text, repr(feed["digest"])[:200]
    assert feed["asof"] == ASOF
    assert feed["records"] == 3, "non-.json siblings must not count: %r" % (feed,)
    assert feed["unreadable"] == 0


def test_b3_digest_is_uncut_at_the_gather_layer(tmp_path) -> None:
    """The cap belongs to the RENDER layer; gather returns the file byte-for-byte."""
    body = "z" * (foundry.PRACTICE_DIGEST_MAX_CHARS + 500)
    text = _digest(body=body)
    cfg, _ = _opted_in(tmp_path, digest=text)
    feed = foundry.gather_practices(cfg)
    assert feed["digest"] == text
    assert len(feed["digest"]) > foundry.PRACTICE_DIGEST_MAX_CHARS


def test_b3_record_count_scales_and_ignores_non_json(tmp_path) -> None:
    for k in (0, 1, 7):
        cfg, _ = _opted_in(tmp_path, sub="k%d" % k, records=k, extras=True)
        assert foundry.gather_practices(cfg)["records"] == k


def test_b3_asof_must_be_on_line_two(tmp_path) -> None:
    """Fuzz: a stamp on line 1 or line 3 is not the register's self-date."""
    late = "# title\nno stamp here\nas of 2026-09-04 buried on line 3\n"
    cfg, _ = _opted_in(tmp_path, sub="late", digest=late)
    feed = foundry.gather_practices(cfg)
    assert feed["digest"] == late
    assert feed["asof"] == "", (
        "a stamp on line 3 was accepted as the register self-date: %r" % (feed,))
    assert feed["unreadable"] == 0


# --------------------------------------------------------------------------
# behavior 4 -- gather is TOTAL on a broken register
# --------------------------------------------------------------------------
def test_b4_absent_register_dir(tmp_path) -> None:
    base, common = _base_tree(tmp_path, sub="absent")
    missing = str(base / "no-such-register")
    cfg = _load(base, "config", common, practice_register=missing)
    feed = foundry.gather_practices(cfg)
    assert set(feed) == FEED_KEYS
    assert str(feed["register"]) == missing
    assert feed["digest"] == "" and feed["asof"] == ""
    assert feed["unreadable"] == 1
    assert feed["records"] == 0


def test_b4_register_without_a_digest_file(tmp_path) -> None:
    cfg, reg = _opted_in(tmp_path, sub="nodigest", digest=None, records=2,
                         extras=False)
    assert not (pathlib.Path(reg) / "DIGEST.md").exists()
    feed = foundry.gather_practices(cfg)
    assert feed["digest"] == "" and feed["asof"] == ""
    assert feed["unreadable"] == 1
    assert feed["records"] == 2, "the glob still counts what it can: %r" % (feed,)


def test_b4_digest_is_a_directory(tmp_path) -> None:
    base, common = _base_tree(tmp_path, sub="dirdigest")
    reg = pathlib.Path(_register(base / "reg", digest=None, records=1,
                                extras=False))
    (reg / "DIGEST.md").mkdir()
    cfg = _load(base, "config", common, practice_register=str(reg))
    feed = foundry.gather_practices(cfg)
    assert feed["digest"] == "" and feed["asof"] == ""
    assert feed["unreadable"] == 1
    assert feed["records"] == 1


def test_b4_short_digest_is_readable_but_undated(tmp_path) -> None:
    """Fewer than 2 lines -> asof '' with unreadable 0: readable, just undated."""
    for text in ("only one line\n", "no trailing newline", ""):
        cfg, _ = _opted_in(tmp_path, sub="short%d" % len(text), digest=text)
        feed = foundry.gather_practices(cfg)
        assert feed["digest"] == text, repr(feed["digest"])
        assert feed["asof"] == ""
        assert feed["unreadable"] == 0, (
            "a short-but-readable digest was reported UNREADABLE: %r" % (feed,))


def test_b4_no_exception_escapes_for_any_broken_shape(tmp_path) -> None:
    """Totality, stated as one sweep: every shape returns the 5-key dict."""
    base, common = _base_tree(tmp_path, sub="sweep")
    shapes = []
    shapes.append(str(base / "gone"))                       # absent
    empty = base / "emptydir"
    empty.mkdir()
    shapes.append(str(empty))                               # dir, no digest, no practices
    filereg = base / "afile"
    filereg.write_text("i am a file, not a dir\n", encoding="utf-8")
    shapes.append(str(filereg))                             # register IS a file
    binreg = pathlib.Path(_register(base / "binary", digest=None))
    (binreg / "DIGEST.md").write_bytes(b"\xff\xfe\x00not utf8\x80")
    shapes.append(str(binreg))                              # undecodable digest
    for i, reg in enumerate(shapes):
        cfg = _load(base, "cfg%d" % i, common, practice_register=reg)
        feed = foundry.gather_practices(cfg)
        assert set(feed) == FEED_KEYS, (reg, feed)
        assert isinstance(feed["records"], int)
        assert feed["unreadable"] in (0, 1), (reg, feed)
        assert isinstance(feed["digest"], str) and isinstance(feed["asof"], str)


# --------------------------------------------------------------------------
# behavior 5 -- age is a PURE function of two inputs
# --------------------------------------------------------------------------
class _NoClockDate(dt.date):
    @classmethod
    def today(cls):  # pragma: no cover -- must never be reached
        raise AssertionError("practice_age_days read the wall clock")


class _NoClockDateTime(dt.datetime):
    @classmethod
    def now(cls, tz=None):  # pragma: no cover
        raise AssertionError("practice_age_days read the wall clock")

    @classmethod
    def today(cls):  # pragma: no cover
        raise AssertionError("practice_age_days read the wall clock")

    @classmethod
    def utcnow(cls):  # pragma: no cover
        raise AssertionError("practice_age_days read the wall clock")


class _DtShim:
    """`datetime` with every clock entry point booby-trapped."""
    date = _NoClockDate
    datetime = _NoClockDateTime
    timedelta = dt.timedelta
    timezone = dt.timezone


def test_b5_age_is_the_day_difference() -> None:
    assert foundry.practice_age_days(ASOF, TODAY) == 9


def test_b5_a_future_stamp_is_negative() -> None:
    assert foundry.practice_age_days("2026-09-20", TODAY) == -7


def test_b5_bad_stamps_return_none_and_never_raise() -> None:
    for bad in ("", "not-a-date", "2026-13-45", "2026-9-4"):
        assert foundry.practice_age_days(bad, TODAY) is None, bad


def test_b5_extra_bad_shapes_fuzzed_past_the_spec() -> None:
    """Shapes the spec never lists -- all must be None, none may raise.

    The list is deliberately SHAPE-focused: a strict `YYYY-MM-DD` contract must
    reject an impossible date, a compact date, an ISO datetime, a suffix, a sign
    and a slash separator -- all of which it does (measured, not assumed).
    """
    for bad in ("2026-02-30", "20260904", "0000-00-00", "2026-09-04T00:00:00",
                "as of 2026-09-04", "9999-99-99", "-2026-09-04", "+2026-09-04",
                "2026/09/04", "2026-09-04Z", "2026-09-04 extra", "2026-09",
                "13-09-2026"):
        got = foundry.practice_age_days(bad, TODAY)
        assert got is None, "%r -> %r (expected None)" % (bad, got)


def test_b5_surrounding_whitespace_is_tolerated_measured_not_assumed() -> None:
    """OBSERVED contract, wider than the spec's letter and benign.

    The spec pins the REJECTIONS by shape (`2026-9-4` must be None, and it is),
    but says nothing about padding.  Measured: leading/trailing spaces, tabs and
    newlines around an otherwise exact stamp still parse.  That is a superset of
    the spec, not a violation -- and it can never fire in production, because the
    only producer of `asof` is the digest's own `as of <ISO>` extraction.  Pinned
    here so a future tightening is a DELIBERATE choice rather than a silent one.
    """
    for padded in (" 2026-09-04", "2026-09-04 ", "\t2026-09-04\n", "\n2026-09-04"):
        assert foundry.practice_age_days(padded, TODAY) == 9, repr(padded)
    # the strictness that DOES matter is untouched by the padding tolerance
    assert foundry.practice_age_days(" 2026-9-4 ", TODAY) is None


def test_b5_valid_far_stamps_still_compute() -> None:
    assert foundry.practice_age_days("2026-09-13", TODAY) == 0
    assert foundry.practice_age_days("1999-12-31", TODAY) == \
        (TODAY - dt.date(1999, 12, 31)).days


def test_b5_reads_no_clock_when_today_is_supplied(monkeypatch) -> None:
    """A supplied `today` must be USED, not merely accepted."""
    monkeypatch.setattr(foundry, "dt", _DtShim)
    assert foundry.practice_age_days(ASOF, TODAY) == 9
    assert foundry.practice_age_days("2026-09-20", TODAY) == -7
    assert foundry.practice_age_days("not-a-date", TODAY) is None
    # and a DIFFERENT today gives a different answer -- so it is not a constant
    assert foundry.practice_age_days(ASOF, dt.date(2030, 1, 1)) == \
        (dt.date(2030, 1, 1) - dt.date(2026, 9, 4)).days


def test_b5_is_deterministic_and_side_effect_free(tmp_path) -> None:
    before = sorted(p.name for p in pathlib.Path(tmp_path).iterdir())
    first = foundry.practice_age_days(ASOF, TODAY)
    assert foundry.practice_age_days(ASOF, TODAY) == first
    assert sorted(p.name for p in pathlib.Path(tmp_path).iterdir()) == before


# --------------------------------------------------------------------------
# behavior 6 -- the header
# --------------------------------------------------------------------------
def test_b6_header_three_lines(tmp_path) -> None:
    cfg, reg = _opted_in(tmp_path, sub="hdr", records=3)
    feed = foundry.gather_practices(cfg)
    block = foundry.practice_advice(feed, today=TODAY)
    lines = block.split("\n")
    assert lines[0] == HEADER_1 + reg, repr(lines[0])
    assert "3 practice record(s) in practices/*.json" in lines[1], repr(lines[1])
    assert "digest as of 2026-09-04 (9 day(s) old)" in lines[1], repr(lines[1])
    low = lines[2].lower()
    assert "verbatim" in low, repr(lines[2])
    assert "6000" in lines[2], repr(lines[2])
    assert ("re-rank" in low or "rerank" in low), repr(lines[2])
    assert "value" in low and "confidence" in low, repr(lines[2])


def test_b6_digest_body_is_present_verbatim(tmp_path) -> None:
    text = _digest(body="RULE-ONE: artifact-gated stage success\nRULE-TWO: x\n")
    cfg, _ = _opted_in(tmp_path, sub="body", digest=text)
    block = foundry.practice_advice(foundry.gather_practices(cfg), today=TODAY)
    assert text in block, "the digest was not passed through verbatim"


def test_b6_empty_register_is_the_only_silent_case(tmp_path) -> None:
    assert foundry.practice_advice(_feed(), today=TODAY) == ""
    cfg = _cfg(tmp_path, sub="silent")
    assert foundry.practice_advice(foundry.gather_practices(cfg), today=TODAY) == ""
    # even a feed that carries a digest is silent when no register is named
    assert foundry.practice_advice(
        _feed(digest="text", asof=ASOF, records=4), today=TODAY) == ""


def test_b6_age_word_tracks_today(tmp_path) -> None:
    """Fuzz: the age is rendered from `today`, not from the real clock."""
    cfg, _ = _opted_in(tmp_path, sub="age")
    feed = foundry.gather_practices(cfg)
    block = foundry.practice_advice(feed, today=dt.date(2026, 9, 5))
    assert "digest as of 2026-09-04 (1 day(s) old)" in block.split("\n")[1]


# --------------------------------------------------------------------------
# behavior 7 -- a configured-but-broken register still ANNOUNCES itself
# --------------------------------------------------------------------------
def test_b7_broken_register_announces_unreadable(tmp_path) -> None:
    reg = str(pathlib.Path(tmp_path) / "gone-register")
    block = foundry.practice_advice(_feed(register=reg, unreadable=1), today=TODAY)
    assert block != "", "a configured-but-broken register went silent"
    assert reg in block
    assert "UNREADABLE" in block, block


def test_b7_broken_register_from_a_real_absent_dir(tmp_path) -> None:
    """End to end: gather + advise over a register path that does not exist."""
    base, common = _base_tree(tmp_path, sub="e2e")
    missing = str(base / "nope")
    cfg = _load(base, "config", common, practice_register=missing)
    block = foundry.practice_advice(foundry.gather_practices(cfg), today=TODAY)
    assert block.split("\n")[0] == HEADER_1 + missing
    assert "UNREADABLE" in block


def test_b7_readable_but_undated_says_unknown(tmp_path) -> None:
    cfg, reg = _opted_in(tmp_path, sub="undated", digest="one line only\n",
                         records=2)
    feed = foundry.gather_practices(cfg)
    assert feed["asof"] == "" and feed["unreadable"] == 0
    block = foundry.practice_advice(feed, today=TODAY)
    assert "digest as of unknown (age unknown)" in block.split("\n")[1], \
        repr(block.split("\n")[1])


def test_b7_no_register_and_broken_register_never_collapse(tmp_path) -> None:
    silent = foundry.practice_advice(_feed(), today=TODAY)
    broken = foundry.practice_advice(
        _feed(register=str(pathlib.Path(tmp_path) / "r"), unreadable=1), today=TODAY)
    assert silent == "" and broken != ""


# --------------------------------------------------------------------------
# behavior 8 -- the cap is real and VISIBLE
# --------------------------------------------------------------------------
def test_b8_constants() -> None:
    assert foundry.PRACTICE_DIGEST_MAX_CHARS == 6000
    assert foundry.PRACTICE_TRUNCATION_MARK == " [...]"


def test_b8_over_cap_digest_is_sliced_and_marked() -> None:
    cap = foundry.PRACTICE_DIGEST_MAX_CHARS
    mark = foundry.PRACTICE_TRUNCATION_MARK
    payload = "".join("abcdefghij"[i % 10] for i in range(cap + 1))
    block = foundry.practice_advice(
        _feed(register="reg-dir", digest=payload, asof=ASOF, records=1), today=TODAY)
    assert payload[:cap] + mark in block, "cap slice + visible mark missing"
    assert payload not in block, "the full over-cap digest leaked into the block"
    assert mark in block


def test_b8_exactly_at_cap_is_verbatim_and_unmarked() -> None:
    cap = foundry.PRACTICE_DIGEST_MAX_CHARS
    payload = "".join("abcdefghij"[i % 10] for i in range(cap))
    block = foundry.practice_advice(
        _feed(register="reg-dir", digest=payload, asof=ASOF, records=1), today=TODAY)
    assert payload in block, "an exactly-at-cap digest was not passed verbatim"
    assert foundry.PRACTICE_TRUNCATION_MARK not in block, "spurious cap mark"


def test_b8_at_cap_digest_ending_in_a_newline_is_still_verbatim() -> None:
    """The shape real files have: last char is a newline, and the block still
    may not end with one.  A naive rstrip satisfies one clause by breaking the
    other."""
    cap = foundry.PRACTICE_DIGEST_MAX_CHARS
    payload = "y" * (cap - 1) + "\n"
    assert len(payload) == cap
    block = foundry.practice_advice(
        _feed(register="reg-dir", digest=payload, asof=ASOF, records=1), today=TODAY)
    assert payload in block, "trailing-newline digest was mangled at exactly the cap"
    assert foundry.PRACTICE_TRUNCATION_MARK not in block
    assert not block.endswith("\n")


def test_b8_block_never_ends_with_a_newline(tmp_path) -> None:
    cap = foundry.PRACTICE_DIGEST_MAX_CHARS
    cases = [
        _feed(register="r", digest="short\n", asof=ASOF, records=1),
        _feed(register="r", digest="no trailing newline", asof=ASOF, records=1),
        _feed(register="r", digest="x" * (cap + 50), asof=ASOF, records=9),
        _feed(register="r", digest="z" * cap, asof="", records=0),
        _feed(register="r", digest="", asof="", records=0, unreadable=1),
        _feed(register="r", digest="a\n\n\n", asof=ASOF, records=2),
    ]
    for feed in cases:
        block = foundry.practice_advice(feed, today=TODAY)
        assert block, feed
        assert not block.endswith("\n"), repr(block[-40:])
    cfg, _ = _opted_in(tmp_path, sub="nl")
    live = foundry.practice_advice(foundry.gather_practices(cfg), today=TODAY)
    assert live and not live.endswith("\n")


def test_b8_neither_function_writes_to_disk(tmp_path, monkeypatch) -> None:
    cfg, reg = _opted_in(tmp_path, sub="ro")

    def _tree(root):
        root = pathlib.Path(root)
        return sorted((str(p.relative_to(root)), p.stat().st_size if p.is_file() else -1)
                      for p in root.rglob("*"))

    before = _tree(tmp_path)

    def boom(*a, **k):
        raise AssertionError("a write reached the filesystem")

    real_open = builtins.open

    def guard_open(file, mode="r", *a, **k):
        if any(ch in mode for ch in "wax+"):
            raise AssertionError("open(%r, %r) -- write mode" % (file, mode))
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(pathlib.Path, "write_text", boom)
    monkeypatch.setattr(pathlib.Path, "write_bytes", boom)
    monkeypatch.setattr(pathlib.Path, "mkdir", boom)
    monkeypatch.setattr(pathlib.Path, "touch", boom)
    monkeypatch.setattr(builtins, "open", guard_open)
    feed = foundry.gather_practices(cfg)
    block = foundry.practice_advice(feed, today=TODAY)
    monkeypatch.undo()
    assert block and reg in block
    assert _tree(tmp_path) == before, "the read-only pair changed the tree"


# --------------------------------------------------------------------------
# behavior 9 -- the seam contract
# --------------------------------------------------------------------------
def test_b9_every_non_pm_stage_is_silent(tmp_path) -> None:
    cfg, reg = _opted_in(tmp_path, sub="seam")
    core = _core_stages()
    non_pm = [s for s in core if s != "pm"]
    assert non_pm and len(non_pm) == len(core) - 1, core
    for stage in non_pm:
        assert foundry.pm_practice_block(cfg, stage) == "", stage
    # widen past the spec: every OTHER stage build_prompt serves, too
    for stage in _all_stages():
        if stage != "pm":
            assert foundry.pm_practice_block(cfg, stage) == "", stage


def test_b9_pm_stage_equals_advice_plus_one_newline(tmp_path) -> None:
    cfg, _ = _opted_in(tmp_path, sub="pmseam")
    expected = foundry.practice_advice(foundry.gather_practices(cfg)) + "\n"
    got = foundry.pm_practice_block(cfg, "pm")
    assert got == expected
    assert got.endswith("\n") and not got.endswith("\n\n")


def test_b9_callees_are_reached_by_bare_module_name(tmp_path, monkeypatch) -> None:
    cfg, _ = _opted_in(tmp_path, sub="bare")
    scripted = _feed(register="scripted-register", digest="d", asof=ASOF, records=2)
    seen = []
    monkeypatch.setattr(foundry, "gather_practices", lambda c: (seen.append(c), scripted)[1])
    monkeypatch.setattr(foundry, "practice_advice", lambda *a, **k: "SCRIPTED")
    assert foundry.pm_practice_block(cfg, "pm") == "SCRIPTED\n"
    assert seen and seen[0] is cfg, "cfg was not forwarded to gather_practices"


def test_b9_non_pm_does_not_even_call_the_callees(tmp_path, monkeypatch) -> None:
    cfg, _ = _opted_in(tmp_path, sub="lazy")

    def boom(*a, **k):
        raise AssertionError("a non-pm stage evaluated the practice feed")

    monkeypatch.setattr(foundry, "gather_practices", boom)
    monkeypatch.setattr(foundry, "practice_advice", boom)
    for stage in [s for s in _all_stages() if s != "pm"]:
        assert foundry.pm_practice_block(cfg, stage) == "", stage


def test_b9_either_callee_raising_yields_empty_string(tmp_path, monkeypatch) -> None:
    cfg, _ = _opted_in(tmp_path, sub="fail")

    def boom(*a, **k):
        raise RuntimeError("scripted explosion")

    with monkeypatch.context() as m:
        m.setattr(foundry, "gather_practices", boom)
        assert foundry.pm_practice_block(cfg, "pm") == ""
    with monkeypatch.context() as m:
        m.setattr(foundry, "practice_advice", boom)
        assert foundry.pm_practice_block(cfg, "pm") == ""
    with monkeypatch.context() as m:
        m.setattr(foundry, "gather_practices", lambda c: "not-a-dict")
        assert foundry.pm_practice_block(cfg, "pm") in ("", )


def test_b9_unconfigured_pm_stage_is_silent(tmp_path) -> None:
    cfg = _cfg(tmp_path, sub="seamoff")
    assert foundry.pm_practice_block(cfg, "pm") == ""


# --------------------------------------------------------------------------
# behavior 10 -- wired ONCE, after the gap block, dormant without opt-in
# --------------------------------------------------------------------------
PRAC_SENTINEL = "ZZ-ITER333-PRACTICE-SENTINEL-ZZ"
GAP_SENTINEL = "ZZ-ITER333-GAP-SENTINEL-ZZ"


def test_b10_exactly_one_call_site_per_prompt(tmp_path, monkeypatch) -> None:
    cfg = _cfg(tmp_path, sub="once")
    for stage in _all_stages():
        calls = []
        with monkeypatch.context() as m:
            m.setattr(foundry, "pm_practice_block",
                      lambda c, s: (calls.append(s), PRAC_SENTINEL + "\n")[1])
            text = _prompt(cfg, stage)
        assert len(calls) == 1, "%s: %d calls to the seam" % (stage, len(calls))
        assert calls[0] == stage, "the real stage string was not forwarded"
        assert text.count(PRAC_SENTINEL) == 1, stage


def test_b10_practice_block_follows_the_gap_block(tmp_path, monkeypatch) -> None:
    cfg = _cfg(tmp_path, sub="order")
    with monkeypatch.context() as m:
        m.setattr(foundry, "pm_gap_block", lambda c, s: GAP_SENTINEL + "\n")
        m.setattr(foundry, "pm_practice_block", lambda c, s: PRAC_SENTINEL + "\n")
        text = _prompt(cfg, "pm")
    assert GAP_SENTINEL in text and PRAC_SENTINEL in text
    assert text.index(PRAC_SENTINEL) > text.index(GAP_SENTINEL)


def test_b10_unconfigured_prompts_are_byte_identical(tmp_path, monkeypatch) -> None:
    cfg = _cfg(tmp_path, sub="ident")
    assert cfg.practice_register == ""
    for stage in _all_stages():
        live = _prompt(cfg, stage)
        with monkeypatch.context() as m:
            m.setattr(foundry, "pm_practice_block", lambda c, s: "")
            pre = _prompt(cfg, stage)
        assert live == pre, "stage %s moved without an opt-in" % stage
        assert "EXTERNAL PRACTICE REGISTER" not in live, stage


def test_b10_configured_pm_prompt_really_speaks(tmp_path) -> None:
    """The other half of the dormancy check: a DELETED call site would pass the
    byte-identity test forever.  With the register configured the pm prompt MUST
    carry the block, and no other stage may."""
    cfg, reg = _opted_in(tmp_path, sub="live")
    pm_text = _prompt(cfg, "pm")
    assert HEADER_1 + reg in pm_text, "the pm prompt lost the practice block"
    assert pm_text.count("EXTERNAL PRACTICE REGISTER") == 1
    for stage in [s for s in _all_stages() if s != "pm"]:
        assert "EXTERNAL PRACTICE REGISTER" not in _prompt(cfg, stage), stage


def test_b10_seam_failure_leaves_the_prompt_buildable(tmp_path, monkeypatch) -> None:
    """Fail-soft survives the wiring: a broken feed must not break a prompt."""
    cfg, _ = _opted_in(tmp_path, sub="soft")

    def boom(*a, **k):
        raise RuntimeError("scripted explosion")

    with monkeypatch.context() as m:
        m.setattr(foundry, "gather_practices", boom)
        text = _prompt(cfg, "pm")
    assert text and "EXTERNAL PRACTICE REGISTER" not in text


# --------------------------------------------------------------------------
# behavior 11 -- the tracked opt-in (declaration only, never the sibling dir)
# --------------------------------------------------------------------------
def test_b11_tracked_platform_config_declares_a_tilde_register() -> None:
    path = _ROOT / "products" / "_platform" / "config.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    val = raw.get("practice_register", "")
    assert isinstance(val, str) and val, "the tracked config has no opt-in"
    assert val.startswith("~/"), (
        "the opt-in must be a tilde path, never an absolute machine path: %r" % val)
    assert not os.path.isabs(val)
    cfg = foundry.load_config(str(path))
    assert cfg.practice_register, "load_config dropped the declared register"
    assert "~" not in cfg.practice_register
    assert os.path.isabs(cfg.practice_register)
    # deliberately NOT asserted: that the register directory exists (it lives
    # outside this repo and is absent from a fresh clone on another machine).


def test_b11_no_other_product_config_opts_in() -> None:
    products = _ROOT / "products"
    for cfgfile in sorted(products.glob("*/config.json")):
        raw = json.loads(cfgfile.read_text(encoding="utf-8"))
        val = raw.get("practice_register", "")
        if cfgfile.parent.name == "_platform":
            assert val
        else:
            assert val == "", "%s unexpectedly opted in" % cfgfile.parent.name
        if val:
            assert val.startswith("~/"), cfgfile


# --------------------------------------------------------------------------
# EXTENSION (tester-retry round) -- edges the spec leaves implicit, each one
# MEASURED against the shipped surface before it was pinned here.  Two of them
# are recorded as documented ambiguities rather than requirements; those say so
# in their own docstring and assert only what the spec actually licenses.
# --------------------------------------------------------------------------
def test_b3x_asof_requires_the_as_of_marker(tmp_path) -> None:
    """Behavior 3 says line 2 *contains* `as of <ISO>`; a bare date is not it.

    Measured: a line-2 date with no `as of` marker yields `asof == ""`, so the
    extraction is anchored on the marker rather than on any date-shaped text.
    That is the reading that keeps a digest sentence like "12 records, 2026 so
    far" from being mistaken for the register's self-date.
    """
    cfg, _ = _opted_in(tmp_path, sub="nomarker",
                       digest="# title\n2026-09-04 generated\n\nbody\n")
    feed = foundry.gather_practices(cfg)
    assert feed["asof"] == "", (
        "a bare line-2 date was read as the register self-date: %r" % (feed,))
    assert feed["unreadable"] == 0, feed


def test_b3x_asof_takes_the_stamp_that_follows_the_marker(tmp_path) -> None:
    """Two dates on line 2: the one after `as of` wins, the other is ignored."""
    cfg, _ = _opted_in(
        tmp_path, sub="twodates",
        digest="# title\nas of 2026-09-04 superseding 2026-08-01\n\nbody\n")
    assert foundry.gather_practices(cfg)["asof"] == ASOF


def test_b3x_nested_json_records_do_not_count(tmp_path) -> None:
    """The spec's count is literally `practices/*.json` -- one level, no walk."""
    base, common = _base_tree(tmp_path, sub="nested")
    reg = pathlib.Path(_register(base / "reg", digest=_digest(), records=2,
                                 extras=False))
    sub = reg / "practices" / "sub"
    sub.mkdir()
    (sub / "deep.json").write_text("{}", encoding="utf-8")
    cfg = _load(base, "config", common, practice_register=str(reg))
    feed = foundry.gather_practices(cfg)
    assert feed["records"] == 2, (
        "a nested practices/sub/*.json was counted -- the spec's glob is one "
        "level deep: %r" % (feed,))
    assert feed["unreadable"] == 0


def test_b3x_practices_that_is_a_file_counts_zero_and_stays_readable(tmp_path) -> None:
    """Totality at the count layer: `practices` present but not a directory.

    Behavior 4's rule is that `records` is whatever the glob could count, and a
    digest that reads fine is not `unreadable`.  Both hold here.
    """
    base, common = _base_tree(tmp_path, sub="pracfile")
    reg = base / "reg"
    reg.mkdir(parents=True)
    (reg / "DIGEST.md").write_text(_digest(), encoding="utf-8")
    (reg / "practices").write_text("i am a file, not a dir\n", encoding="utf-8")
    cfg = _load(base, "config", common, practice_register=str(reg))
    feed = foundry.gather_practices(cfg)
    assert feed["records"] == 0, feed
    assert feed["asof"] == ASOF and feed["unreadable"] == 0, feed
    assert foundry.practice_advice(feed, today=TODAY).split("\n")[1].startswith(
        "0 practice record(s) in practices/*.json"), feed


def test_b3x_a_json_named_directory_never_raises(tmp_path) -> None:
    """DOCUMENTED AMBIGUITY, not a pinned requirement.

    A glob for `*.json` also matches a DIRECTORY whose name ends `.json`, and
    measurement confirms such a directory is included in `records` (3 where 2
    files exist).  The spec says "k `*.json` files", so strictly that is an
    over-count -- but it cannot occur in the real register (the provider writes
    files) and the spec's own fixture list only asks that `notes.txt` and
    `skip.json.bak` be excluded, which they are.  Pinning 3 here would make an
    accident into a contract, so this test asserts only totality and leaves the
    exact number to the PM: see the tester report's NIT.
    """
    base, common = _base_tree(tmp_path, sub="jsondir")
    reg = pathlib.Path(_register(base / "reg", digest=_digest(), records=2,
                                 extras=False))
    (reg / "practices" / "weird.json").mkdir()
    cfg = _load(base, "config", common, practice_register=str(reg))
    feed = foundry.gather_practices(cfg)
    assert set(feed) == FEED_KEYS, feed
    assert isinstance(feed["records"], int) and feed["records"] >= 2, feed
    assert feed["unreadable"] == 0 and feed["asof"] == ASOF, feed


def test_b3x_unicode_digest_survives_the_round_trip(tmp_path) -> None:
    """Non-ASCII text is read and rendered without mangling or escaping."""
    text = _digest(body="rule: \u00e9\u00e9\u00e9 and \u65e5\u672c\u8a9e\n")
    cfg, _ = _opted_in(tmp_path, sub="uni", digest=text)
    feed = foundry.gather_practices(cfg)
    assert feed["digest"] == text
    assert text in foundry.practice_advice(feed, today=TODAY)


def test_b3x_crlf_digest_is_newline_normalized(tmp_path) -> None:
    """DOCUMENTED AMBIGUITY against behavior 3's phrase "byte-for-byte".

    Measured: a CRLF `DIGEST.md` comes back with LF line endings -- i.e. the
    read is text-mode with universal newlines, so "byte-for-byte" holds for the
    LF files the provider actually generates but not for a CRLF one.  This is
    the same treatment the sibling register gets and it loses no content, so it
    is pinned as OBSERVED (the stamp is still found, the body still round-trips
    modulo `\r`) rather than reported as a defect.
    """
    crlf = "# title\r\nas of 2026-09-04 from 12 records\r\n\r\nbody line\r\n"
    cfg, _ = _opted_in(tmp_path, sub="crlf", digest=crlf)
    feed = foundry.gather_practices(cfg)
    assert feed["asof"] == ASOF, feed
    assert feed["unreadable"] == 0, feed
    assert feed["digest"] == crlf.replace("\r\n", "\n"), repr(feed["digest"])
    assert "body line" in foundry.practice_advice(feed, today=TODAY)


def test_b3x_gather_is_repeatable_and_leaves_the_register_alone(tmp_path) -> None:
    """Read-only means the second call sees exactly what the first one did."""
    cfg, reg = _opted_in(tmp_path, sub="twice")
    regp = pathlib.Path(reg)
    before = sorted((str(q.relative_to(regp)), q.is_file()) for q in regp.rglob("*"))
    first = foundry.gather_practices(cfg)
    assert foundry.gather_practices(cfg) == first
    assert sorted((str(q.relative_to(regp)), q.is_file())
                  for q in regp.rglob("*")) == before


def test_b6x_zero_records_still_renders_the_count_form(tmp_path) -> None:
    """The spec's `<n> practice record(s)` form is not pluralized away at n=0/1."""
    for k in (0, 1):
        cfg, _ = _opted_in(tmp_path, sub="cnt%d" % k, records=k, extras=False)
        line2 = foundry.practice_advice(
            foundry.gather_practices(cfg), today=TODAY).split("\n")[1]
        assert line2.startswith("%d practice record(s) in practices/*.json" % k), \
            repr(line2)


def test_b6x_today_defaults_to_the_real_clock() -> None:
    """`practice_advice(feed)` with no `today` must still date the digest.

    Asserted robustly (no exact day count) so a run that straddles midnight
    cannot flake: a stamp of TODAY's real date must render an age, never the
    `age unknown` wording reserved for an undated digest.
    """
    stamp = dt.date.today().isoformat()
    block = foundry.practice_advice(
        _feed(register="reg-dir", digest="d", asof=stamp, records=1))
    line2 = block.split("\n")[1]
    assert "digest as of %s" % stamp in line2, repr(line2)
    assert "day(s) old" in line2, repr(line2)
    assert "age unknown" not in line2, repr(line2)


def test_b8x_the_cap_counts_CHARACTERS_not_bytes() -> None:
    """A multibyte payload is sliced at 6000 CHARS, per "a plain char slice"."""
    cap = foundry.PRACTICE_DIGEST_MAX_CHARS
    mark = foundry.PRACTICE_TRUNCATION_MARK
    payload = "\u00e9" * (cap + 1)
    assert len(payload.encode("utf-8")) > cap  # bytes and chars really differ
    block = foundry.practice_advice(
        _feed(register="reg-dir", digest=payload, asof=ASOF, records=1), today=TODAY)
    assert payload[:cap] + mark in block, "multibyte digest was not char-sliced"
    at_cap = "\u00e9" * cap
    block2 = foundry.practice_advice(
        _feed(register="reg-dir", digest=at_cap, asof=ASOF, records=1), today=TODAY)
    assert at_cap in block2 and mark not in block2


def test_b8x_no_off_by_one_at_the_cap_boundary() -> None:
    """Exactly `cap` chars survive -- not cap+1, not cap-1."""
    cap = foundry.PRACTICE_DIGEST_MAX_CHARS
    mark = foundry.PRACTICE_TRUNCATION_MARK
    payload = "".join("0123456789"[i % 10] for i in range(cap + 25))
    block = foundry.practice_advice(
        _feed(register="reg-dir", digest=payload, asof=ASOF, records=1), today=TODAY)
    assert payload[:cap] + mark in block
    assert payload[:cap + 1] not in block, "one char past the cap was emitted"
    assert block.count(mark) == 1, "the cap mark was rendered more than once"


def test_b9x_odd_stage_values_never_raise(tmp_path) -> None:
    """The seam is total in its `stage` argument: only exact `pm` speaks."""
    cfg, _ = _opted_in(tmp_path, sub="oddstage")
    assert foundry.pm_practice_block(cfg, "pm") != ""
    for stage in (None, "", "PM", "Pm", "pm ", " pm", "pm2", "unknown-stage", 0):
        got = foundry.pm_practice_block(cfg, stage)
        assert got == "", "stage %r spoke: %r" % (stage, got[:60])


def test_b9x_a_cfg_without_the_field_fails_soft(tmp_path) -> None:
    """A cfg-shaped object with no `practice_register` returns '', not a crash.

    This is the `except Exception: return ""` contract seen from outside: the
    seam is called on every prompt build, so it may never be the thing that
    breaks one.
    """
    class _Bare:
        pass

    assert foundry.pm_practice_block(_Bare(), "pm") == ""
    assert foundry.pm_practice_block(None, "pm") == ""


def test_b10x_the_pm_prompt_carries_the_digest_BODY_end_to_end(tmp_path) -> None:
    """Header presence is not enough: the payload must survive the whole chain.

    config -> gather -> advice -> seam -> build_prompt, asserted on the text the
    PM lead would actually read.
    """
    marker = "PRACTICE-BODY-MARKER-ITER333"
    text = _digest(body="RULE: %s\n" % marker)
    cfg, reg = _opted_in(tmp_path, sub="e2ebody", digest=text)
    pm_text = _prompt(cfg, "pm")
    assert HEADER_1 + reg in pm_text
    assert marker in pm_text, "the digest body never reached the pm prompt"
    assert text in pm_text, "the digest was not passed through verbatim"
    for stage in [s for s in _all_stages() if s != "pm"]:
        assert marker not in _prompt(cfg, stage), stage


def test_b10x_a_broken_register_still_announces_inside_the_pm_prompt(tmp_path) -> None:
    """Behaviors 7 and 10 crossed: silence must not be how a break presents."""
    base, common = _base_tree(tmp_path, sub="e2ebroken")
    missing = str(base / "no-such-register")
    cfg = _load(base, "config", common, practice_register=missing)
    pm_text = _prompt(cfg, "pm")
    assert missing in pm_text
    assert "UNREADABLE" in pm_text
    assert pm_text.count("EXTERNAL PRACTICE REGISTER") == 1
