"""Iteration 368 -- BLACK-BOX behavior tests: `drift_prompt_block(cfg)` is a
pure, total, WARN-ONLY, hard-capped renderer of THREE `doctor` drift lines whose
remedy is owed by the PM, wired at ONE call site in `build_prompt` gated to the
PM lead and the two scout seats.

Spec under test (products/_platform/state/iter-368/pm.md).  Iteration 368 RE-LANDS
iteration 367's reverted feed minus ONE fed row, so the spec renumbered its
behaviors while this module kept iteration 367's test-name prefixes.  The mapping
is therefore stated once, here, and every prefix below is to be read through it:

   spec 1  WARN-only, WARN lines verbatim, OK lines absent      -> test_b1_*
   spec 2  silent when healthy -- all-OK is the EMPTY string    -> test_b2_*
   spec 3  the verdict is read by FIXED POSITION, not substring -> test_b3_*
   spec 4  the reader agrees with the `live_lag_verdict` oracle -> test_b4_*
   spec 5  hard byte cap, read as a provably live module global -> test_b5_*
   spec 6  total -- a raising renderer degrades to nothing      -> test_b6_*
   spec 7  wired, and gated to the three proposing seats only   -> test_b7_*
   spec 8  `learnings_head_line` IS NOT COMPOSED, iter-118 holds
           -> test_b8_the_out_of_scope_renderers_are_not_composed (8a, raiser
              probe), test_b8_the_excluded_renderer_is_not_composed_even_when
              _it_warns (8a, direct), and
              test_b1_the_block_never_re_injects_a_head_bullet_the_budget
              _dropped (8b, with its own non-vacuity leg)
   spec 9  off the control and ship paths, so a loop resumes    -> test_b8_*
           (census names, kept from iteration 367)
   spec 10 no frozen path touched + live-tree non-vacuity       -> test_b9_*,
           test_b10_*

WHY ONE RENDERER IS EXCLUDED, measured: `learnings_head_line` NAMES its worst
over-budget learnings bullet and QUOTES that bullet's own text, so feeding it
carried back into the PM prompt the very text iteration 118's head budget had
just evicted -- which is what reverted iteration 367
(`tests/test_iter118_behavior.py`).  The exclusion is a PINNED behavior here, not
a footnote: it is why `learnings_head_line` sits in `OUT_OF_SCOPE` rather than in
`RENDERERS`.

ISOLATION HONORED: written from `pm.md`, the repo's own `tests/` conventions, the
roadmap files and the product's RUNTIME surface (calling its public functions,
`dir()` and `__doc__`) ONLY.  No implementation source file was read, and no
engineer / reviewer / fix note and no `git diff` output was read.

OFFLINE: no network and no clock.  Every renderer is replaced by a scripted
stand-in, so no real subprocess, git or log read happens inside behaviors 1-3 and
5-8.  Behaviors 4, 9 and 10 read only git-TRACKED state or the live config that
`doctor` itself reads, and each asserts a DERIVED property -- never a count.

FRESH-CLONE SAFE: every synthetic fixture is built under `tmp_path`; nothing is
asserted about the gitignored `products/_platform/state` tree (the trap that lost
iteration 154), and the two git-backed behaviors SKIP when git is unavailable.
"""
from __future__ import annotations

import inspect
import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

THIS_ITER = 368

BLOCK = "drift_prompt_block"
CAP = "PROMPT_DRIFT_BLOCK_CHARS"
GATE = "PROMPT_DRIFT_STAGES"
READER = "drift_line_verdict"

#: the THREE FED renderers: name -> the prefix its line must start with.  Both sides
#: are read off the module, so a rename of either is a red rather than a silent
#: pass.
RENDERERS = {
    "live_lag_line": "LIVE_LAG_PREFIX",
    "roadmap_index_line": "ROADMAP_INDEX_PREFIX",
    "stage_budget_line": "STAGE_BUDGET_PREFIX",
}

#: the three renderers the spec puts OUT of scope, each for a measured reason.
#: `learnings_head_line` is first because it is iteration 367's regression: it
#: quotes an over-budget head bullet's own text, so feeding it re-injects text
#: iteration 118 guarantees the prompt drops (behavior 8 pins this two-sided).
OUT_OF_SCOPE = ("learnings_head_line", "test_touch_line", "auth_loss_line")

WARN = "WARN"
OK = "OK"
UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------
# helpers -- every call goes through the BARE module name at CALL time, so a
# `monkeypatch.setattr(foundry, ...)` bites (the repo's shipped idiom)
# --------------------------------------------------------------------------
def _prefix(renderer: str) -> str:
    return getattr(foundry, RENDERERS[renderer])


def _line(renderer: str, verdict: str, body: str = "scripted body") -> str:
    """A drift line in the shape every `doctor` drift renderer really emits."""
    return "%s %s -- %s" % (_prefix(renderer), verdict, body)


def _script(monkeypatch, verdicts, body="scripted body"):
    """Replace all three FED renderers with stand-ins returning those verdicts.

    `verdicts` maps renderer name -> verdict token, or -> a callable used as the
    stand-in verbatim (for the raising and long-line probes).  Any renderer left
    out returns an OK line, which the block must drop.
    """
    rendered = {}
    for name in RENDERERS:
        want = verdicts.get(name, OK)
        if callable(want):
            monkeypatch.setattr(foundry, name, want)
            continue
        text = _line(name, want, body)
        rendered[name] = text
        monkeypatch.setattr(
            foundry, name, lambda *a, _t=text, **k: _t)
    return rendered


def _raiser(message="scripted renderer failure"):
    def _boom(*a, **k):
        raise RuntimeError(message)
    return _boom


def _block(cfg) -> str:
    return getattr(foundry, BLOCK)(cfg)


def _read(line, prefix) -> str:
    return getattr(foundry, READER)(line, prefix)


# --------------------------------------------------------------------------
# fixtures -- ALWAYS under tmp_path, never the ambient tree
# --------------------------------------------------------------------------
def _cfg(tmp_path, sub="p", **over):
    """A minimal synthetic product, loaded through the PUBLIC config seam."""
    base = pathlib.Path(tmp_path) / sub
    base.mkdir(parents=True, exist_ok=True)
    (base / "repo").mkdir(exist_ok=True)
    (base / "VISION.md").write_text("product vision text\n", encoding="utf-8")
    (base / "ROADMAP.md").write_text("- a roadmap item\n", encoding="utf-8")
    data = {
        "name": "demoprod",
        "repo": str(base / "repo"),
        "allowed_push_repo": "demoprod",
        "vision": str(base / "VISION.md"),
        "roadmap": str(base / "ROADMAP.md"),
        "work_root": str(base / "work"),
    }
    data.update(over)
    path = base / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    cfg = foundry.load_config(str(path))
    learnings = pathlib.Path(cfg.learnings)
    learnings.parent.mkdir(parents=True, exist_ok=True)
    learnings.write_text(
        "## Patterns\n\n- a durable rule\n\n- [ENG iter01] a lesson\n",
        encoding="utf-8")
    return cfg


def _it_dir(cfg, tmp_path=None):
    """The iteration state dir.

    ALWAYS built under `tmp_path` when one is supplied, and the live-config
    behaviors always supply one: `cfg.work_root` for the real product points at
    a GITIGNORED tree, so creating it here would both write untracked dirs into
    the shared checkout (iteration 219's race) and read ambient state a fresh
    clone does not have.
    """
    root = pathlib.Path(tmp_path) if tmp_path is not None else pathlib.Path(cfg.work_root)
    d = root / "state" / ("iter-%d" % THIS_ITER)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _prompt(cfg, stage, tmp_path=None):
    it = _it_dir(cfg, tmp_path)
    return foundry.build_prompt(cfg, THIS_ITER, stage, "pm.md",
                                it / ("%s.md" % stage), it, "extra context")


def _live_cfg():
    """The product's OWN config -- git-tracked, the file `doctor` itself reads."""
    path = _ROOT / "products" / "_platform" / "config.json"
    if not path.is_file():
        pytest.skip("live product config not present in this checkout")
    return foundry.load_config(str(path))


def _git(*args):
    return subprocess.run(["git", *args], cwd=str(_ROOT),
                          capture_output=True, text=True)


# ==========================================================================
# behavior 0 -- the surface, before anything is graded over it
# ==========================================================================
def test_b0_modules_import_and_the_named_surface_exists() -> None:
    """AC: the renderer and the cap land in foundry.py and stay importable."""
    assert foundry.__name__ == "foundry" and dispatcher.__name__ == "dispatcher"
    assert callable(getattr(foundry, BLOCK, None)), "foundry.%s missing" % BLOCK
    assert list(inspect.signature(getattr(foundry, BLOCK)).parameters) == ["cfg"], \
        "the block takes exactly one argument, the cfg"
    assert isinstance(getattr(foundry, CAP), int), "%s must be an int" % CAP
    assert callable(getattr(foundry, READER, None)), "foundry.%s missing" % READER


def test_b0_the_three_composed_renderers_are_all_present() -> None:
    """Absent any one of these, every scripted behavior below is vacuous."""
    for name, const in RENDERERS.items():
        assert callable(getattr(foundry, name, None)), "renderer %s missing" % name
        prefix = getattr(foundry, const, None)
        assert isinstance(prefix, str) and prefix, "%s must be a non-empty str" % const
    assert len(set(_prefix(n) for n in RENDERERS)) == len(RENDERERS), \
        "the fed prefixes must be distinct, else the per-line reader is ambiguous"


# ==========================================================================
# Behavior 1 -- WARN-only: WARN lines verbatim, OK lines absent
# ==========================================================================
def test_b1_only_the_warn_lines_survive(tmp_path, monkeypatch) -> None:
    cfg = _cfg(tmp_path, sub="b1")
    rendered = _script(monkeypatch, {"stage_budget_line": WARN,
                                     "live_lag_line": WARN})
    got = _block(cfg)
    for warned in ("stage_budget_line", "live_lag_line"):
        assert rendered[warned] in got, \
            "the %s WARN line must appear VERBATIM, got %r" % (warned, got)
    for healthy in ("roadmap_index_line",):
        assert rendered[healthy] not in got, \
            "an OK line must not reach the prompt: %r" % (rendered[healthy],)
        assert _prefix(healthy) not in got, \
            "not even the %s prefix may appear when its verdict is OK" % healthy
    assert len([ln for ln in got.splitlines() if ln.strip()]) == 2, \
        "exactly the two WARN lines, nothing else: %r" % (got,)


@pytest.mark.parametrize("warned", sorted(RENDERERS))
def test_b1_each_renderer_can_be_the_only_warning(tmp_path, monkeypatch, warned) -> None:
    """Every one of the three is individually deliverable -- no hard-coded pair."""
    cfg = _cfg(tmp_path, sub="b1each")
    rendered = _script(monkeypatch, {warned: WARN})
    got = _block(cfg)
    assert rendered[warned] in got, "%s must be deliverable alone" % warned
    assert [ln for ln in got.splitlines() if ln.strip()] == [rendered[warned]], \
        "only the single WARN line may survive, got %r" % (got,)


def test_b1_unknown_is_not_a_warning(tmp_path, monkeypatch) -> None:
    """The block is WARN-only: `I cannot tell` is not evidence of a problem."""
    cfg = _cfg(tmp_path, sub="b1unk")
    rendered = _script(monkeypatch, {n: UNKNOWN for n in RENDERERS})
    got = _block(cfg)
    assert got == "", "an all-UNKNOWN product must pay zero prompt chars, got %r" % (got,)
    for text in rendered.values():
        assert text not in got


# ==========================================================================
# Behavior 2 -- silent when healthy: the EMPTY string, not a heading
# ==========================================================================
def test_b2_all_ok_renders_the_empty_string(tmp_path, monkeypatch) -> None:
    cfg = _cfg(tmp_path, sub="b2")
    _script(monkeypatch, {n: OK for n in RENDERERS})
    got = _block(cfg)
    assert isinstance(got, str), "the block always returns a str, got %r" % (type(got),)
    assert got == "", \
        "an all-OK product pays ZERO prompt chars -- no heading, no whitespace, got %r" \
        % (got,)


def test_b2_a_healthy_product_leaves_the_prompt_byte_identical(tmp_path, monkeypatch) -> None:
    """The no-op safety argument, measured at the CALL SITE rather than asserted."""
    cfg = _cfg(tmp_path, sub="b2prompt")
    _script(monkeypatch, {n: OK for n in RENDERERS})
    healthy = _prompt(cfg, "pm")
    _script(monkeypatch, {n: UNKNOWN for n in RENDERERS})
    unknown = _prompt(cfg, "pm")
    assert healthy == unknown, \
        "neither an OK nor an UNKNOWN verdict may add one character to the prompt"


# ==========================================================================
# Behavior 3 -- the verdict is read by FIXED POSITION, never by substring
# ==========================================================================
@pytest.mark.parametrize("body", [
    "RuntimeError('WARN: could not read the log')",
    "OSError(2, 'WARN')",
    "the word WARN appears only in this prose",
])
def test_b3_an_unknown_line_whose_body_embeds_warn_is_not_selected(
        tmp_path, monkeypatch, body) -> None:
    """Iteration 209's shipped rule: `{exc!r}` can CONTAIN the 4-char token."""
    cfg = _cfg(tmp_path, sub="b3")
    rendered = _script(monkeypatch, {n: UNKNOWN for n in RENDERERS}, body=body)
    got = _block(cfg)
    assert WARN in rendered["live_lag_line"], \
        "fixture must actually embed the token, else this probe is vacuous"
    assert got == "", \
        "a substring reader would select this UNKNOWN line; got %r" % (got,)


def test_b3_the_reader_refuses_a_verdict_word_that_is_merely_a_prefix(
        tmp_path, monkeypatch) -> None:
    """`WARNING` is not `WARN`: an unrecognised token may never compare equal."""
    cfg = _cfg(tmp_path, sub="b3near")
    rendered = _script(monkeypatch, {n: "WARNING" for n in RENDERERS})
    got = _block(cfg)
    assert got == "", "`WARNING` must not read as the WARN verdict, got %r" % (got,)
    for name in RENDERERS:
        assert _read(rendered[name], _prefix(name)) != WARN


def test_b3_a_line_whose_prefix_is_not_at_the_start_is_not_selected(
        tmp_path, monkeypatch) -> None:
    """The prefix must anchor at position 0 -- a quoted line is not a verdict."""
    cfg = _cfg(tmp_path, sub="b3anchor")
    _script(monkeypatch, {
        name: (lambda *a, _p=_prefix(name), **k: "quoting `%s %s -- x`" % (_p, WARN))
        for name in RENDERERS})
    got = _block(cfg)
    assert got == "", "an embedded prefix is not a verdict position, got %r" % (got,)


# ==========================================================================
# Behavior 4 -- the block's reader agrees with the shipped verdict oracle
# ==========================================================================
def _rekey(line: str, own_prefix: str) -> str:
    """Re-key a drift line onto the live-lag prefix, byte-for-byte otherwise.

    `live_lag_verdict` is anchored to `LIVE_LAG_PREFIX`, so comparing the two
    readers on the OTHER three prefixes requires moving the line into the
    oracle's own namespace; everything after the prefix, including the verdict
    POSITION under test, is untouched.  (Ambiguity noted in tester.md: the spec
    says "the same token as `live_lag_verdict` does for that line", which is
    literally satisfiable only for the live-lag line, since the shipped oracle
    answers `""` for a foreign prefix by contract.)
    """
    assert line.startswith(own_prefix)
    return foundry.LIVE_LAG_PREFIX + line[len(own_prefix):]


@pytest.mark.parametrize("name", sorted(RENDERERS))
def test_b4_two_readers_of_one_fixed_position_never_disagree(name) -> None:
    """Driven by the REAL renderers on the live tree -- no scripted stand-in."""
    cfg = _live_cfg()
    line = getattr(foundry, name)(cfg)
    prefix = _prefix(name)
    assert isinstance(line, str) and line.startswith(prefix), \
        "%s must render a line starting with %r, got %r" % (name, prefix, line)
    mine = _read(line, prefix)
    theirs = foundry.live_lag_verdict(_rekey(line, prefix))
    assert mine == theirs, \
        "the block's reader (%r) and live_lag_verdict (%r) disagree on %s" \
        % (mine, theirs, name)
    assert mine in (WARN, OK, UNKNOWN), \
        "a real renderer must land on a recognised verdict, got %r" % (mine,)


def test_b4_the_native_line_needs_no_rekeying_to_agree() -> None:
    """Non-vacuity for the re-keying above: on live-lag both readers apply raw."""
    cfg = _live_cfg()
    line = foundry.live_lag_line(cfg)
    assert _read(line, foundry.LIVE_LAG_PREFIX) == foundry.live_lag_verdict(line), \
        "on its OWN prefix the new reader must equal the shipped oracle verbatim"


@pytest.mark.parametrize("verdict", [WARN, OK, UNKNOWN, "WARNING", "", "nonsense"])
@pytest.mark.parametrize("name", sorted(RENDERERS))
def test_b4_the_readers_agree_on_synthetic_lines_too(name, verdict) -> None:
    """The agreement is a property of the ALGORITHM, not of today's tree."""
    prefix = _prefix(name)
    line = "%s %s -- some body" % (prefix, verdict)
    assert _read(line, prefix) == foundry.live_lag_verdict(_rekey(line, prefix))


@pytest.mark.parametrize("junk", [None, "", 0, 3.5, object(), b"live-lag: WARN", []])
def test_b4_the_reader_is_total_over_junk(junk) -> None:
    """Same totality contract the shipped oracle states: a str, never a raise."""
    got = _read(junk, foundry.LIVE_LAG_PREFIX)
    assert isinstance(got, str), "reader must return a str for %r, got %r" % (junk, got)
    assert got not in (WARN, OK, UNKNOWN) or got == "", \
        "junk must not read as a verdict: %r -> %r" % (junk, got)


# ==========================================================================
# Behavior 5 -- hard byte cap, proved LIVE by shrinking the module global
# ==========================================================================
def _huge(name, chars=5000):
    body = "z" * chars
    return lambda *a, _p=_prefix(name), **k: "%s %s -- %s" % (_p, WARN, body)


def test_b5_three_five_thousand_char_warnings_are_capped(tmp_path, monkeypatch) -> None:
    cfg = _cfg(tmp_path, sub="b5")
    _script(monkeypatch, {n: _huge(n) for n in RENDERERS})
    got = _block(cfg)
    cap = getattr(foundry, CAP)
    assert len(got) <= cap, \
        "15,000 chars of WARN must be capped at %d, got %d" % (cap, len(got))
    assert len(got) > 0, "the cap must TRUNCATE, not blank the block"


def test_b5_the_constant_is_bounded_by_the_spec() -> None:
    cap = getattr(foundry, CAP)
    assert isinstance(cap, int) and 0 < cap <= 2000, \
        "%s must be a positive int <= 2000, got %r" % (CAP, cap)


@pytest.mark.parametrize("shrunk", [200, 120, 60])
def test_b5_the_cap_is_a_live_module_global_not_a_comment(
        tmp_path, monkeypatch, shrunk) -> None:
    cfg = _cfg(tmp_path, sub="b5live")
    _script(monkeypatch, {n: _huge(n) for n in RENDERERS})
    monkeypatch.setattr(foundry, "PROMPT_DRIFT_BLOCK_CHARS", shrunk)
    got = _block(cfg)
    assert len(got) <= shrunk, \
        "the cap is read at CALL time, so %d must bind; got %d" % (shrunk, len(got))


def test_b5_a_shrunken_cap_really_shortens_the_output(tmp_path, monkeypatch) -> None:
    """Non-vacuity: the two lengths must actually differ, else the probe proves
    nothing about the constant being consulted."""
    cfg = _cfg(tmp_path, sub="b5delta")
    _script(monkeypatch, {n: _huge(n) for n in RENDERERS})
    wide = len(_block(cfg))
    monkeypatch.setattr(foundry, "PROMPT_DRIFT_BLOCK_CHARS", 200)
    narrow = len(_block(cfg))
    assert narrow < wide, "shrinking the cap must shrink the block: %d !< %d" % (
        narrow, wide)


def test_b5_a_short_block_is_never_padded(tmp_path, monkeypatch) -> None:
    cfg = _cfg(tmp_path, sub="b5short")
    rendered = _script(monkeypatch, {"live_lag_line": WARN})
    got = _block(cfg)
    assert len(got) < getattr(foundry, CAP), "a one-line block must stay short"
    assert got.strip() == rendered["live_lag_line"], \
        "no padding, no heading: %r" % (got,)


# ==========================================================================
# Behavior 6 -- total: never raises, degrades to nothing, the others report
# ==========================================================================
@pytest.mark.parametrize("victim", sorted(RENDERERS))
def test_b6_a_raising_renderer_never_reaches_the_caller(
        tmp_path, monkeypatch, victim) -> None:
    cfg = _cfg(tmp_path, sub="b6")
    rendered = _script(monkeypatch, {n: WARN for n in RENDERERS})
    monkeypatch.setattr(foundry, victim, _raiser())
    got = _block(cfg)
    assert isinstance(got, str), "must degrade to a str, got %r" % (type(got),)
    assert _prefix(victim) not in got, \
        "a raising renderer contributes NOTHING, got %r" % (got,)
    for other in RENDERERS:
        if other == victim:
            continue
        assert rendered[other] in got, \
            "%s must still report while %s raises" % (other, victim)
    assert len([ln for ln in got.splitlines() if ln.strip()]) == len(RENDERERS) - 1, \
        "exactly the surviving siblings, one fewer than the fed set: %r" % (got,)


def test_b6_all_three_raising_degrades_to_the_empty_string(tmp_path, monkeypatch) -> None:
    cfg = _cfg(tmp_path, sub="b6all")
    _script(monkeypatch, {n: _raiser() for n in RENDERERS})
    got = _block(cfg)
    assert got == "", "a wholly broken gauge must cost zero prompt chars, got %r" % (got,)


@pytest.mark.parametrize("exc", [RuntimeError, ValueError, OSError, KeyError,
                                 TypeError, AttributeError])
def test_b6_any_exception_class_is_absorbed(tmp_path, monkeypatch, exc) -> None:
    cfg = _cfg(tmp_path, sub="b6cls")
    def _boom(*a, **k):
        raise exc("scripted failure")
    _script(monkeypatch, {n: WARN for n in RENDERERS})
    monkeypatch.setattr(foundry, "live_lag_line", _boom)
    got = _block(cfg)
    assert isinstance(got, str) and foundry.LIVE_LAG_PREFIX not in got


@pytest.mark.parametrize("junk", [None, 0, 3.5, object(), b"bytes", [], {}])
def test_b6_a_renderer_returning_a_non_string_is_absorbed(
        tmp_path, monkeypatch, junk) -> None:
    """Totality is about the RETURN too, not only the raise."""
    cfg = _cfg(tmp_path, sub="b6junk")
    rendered = _script(monkeypatch, {n: WARN for n in RENDERERS})
    monkeypatch.setattr(foundry, "live_lag_line", lambda *a, **k: junk)
    got = _block(cfg)
    assert isinstance(got, str), "non-str renderer output must not escape"
    assert rendered["stage_budget_line"] in got, "the healthy siblings still report"


def test_b6_a_broken_gauge_never_breaks_the_prompt(tmp_path, monkeypatch) -> None:
    """The reason totality matters: `build_prompt` must survive it."""
    cfg = _cfg(tmp_path, sub="b6prompt")
    _script(monkeypatch, {n: _raiser() for n in RENDERERS})
    out = _prompt(cfg, "pm")
    assert isinstance(out, str) and out, "build_prompt must still render"


# ==========================================================================
# Behavior 7 -- wired, and gated to the three proposing seats
# ==========================================================================
SEATS_WITH = ("pm", "pm_scout_a", "pm_scout_b")
SEATS_WITHOUT = ("engineer", "tester", "reviewer", "final")


@pytest.mark.parametrize("stage", SEATS_WITH)
def test_b7_the_proposing_seats_receive_the_block(tmp_path, monkeypatch, stage) -> None:
    cfg = _cfg(tmp_path, sub="b7in")
    rendered = _script(monkeypatch, {n: WARN for n in RENDERERS})
    out = _prompt(cfg, stage)
    block = _block(cfg)
    assert block, "fixture must produce a non-empty block, else this is vacuous"
    assert block in out, "stage %r must receive the drift block" % (stage,)
    for text in rendered.values():
        assert text in out, "every WARN line must reach %r" % (stage,)


@pytest.mark.parametrize("stage", SEATS_WITHOUT)
def test_b7_every_other_seat_is_untouched(tmp_path, monkeypatch, stage) -> None:
    cfg = _cfg(tmp_path, sub="b7out")
    rendered = _script(monkeypatch, {n: WARN for n in RENDERERS})
    out = _prompt(cfg, stage)
    for name, text in rendered.items():
        assert text not in out, \
            "stage %r must NOT pay for the drift block (%s leaked)" % (stage, name)
    assert _block(cfg) not in out


def test_b7_the_gate_is_a_module_global_and_matches_the_spec() -> None:
    gate = getattr(foundry, GATE, None)
    assert isinstance(gate, tuple), "%s must be a tuple, got %r" % (GATE, type(gate))
    assert set(gate) == set(SEATS_WITH), \
        "the gate must be exactly the three proposing seats, got %r" % (gate,)


def test_b7_the_gate_is_read_at_call_time(tmp_path, monkeypatch) -> None:
    """Shrinking the gate must remove a seat -- proving no seat is hard-coded."""
    cfg = _cfg(tmp_path, sub="b7gate")
    rendered = _script(monkeypatch, {n: WARN for n in RENDERERS})
    monkeypatch.setattr(foundry, GATE, ("pm",))
    assert rendered["live_lag_line"] in _prompt(cfg, "pm")
    for stage in ("pm_scout_a", "pm_scout_b"):
        assert rendered["live_lag_line"] not in _prompt(cfg, stage), \
            "%r must drop out when the gate no longer names it" % (stage,)


def test_b7_the_retry_variants_of_a_gated_stage_are_not_widened(
        tmp_path, monkeypatch) -> None:
    """A retry seat is a DIFFERENT stage name; the gate is exact, not a prefix."""
    cfg = _cfg(tmp_path, sub="b7retry")
    rendered = _script(monkeypatch, {n: WARN for n in RENDERERS})
    for stage in ("tester-retry", "tester-retry2", "fix", "fix-review", "postrelease"):
        if stage in getattr(foundry, GATE):
            continue
        assert rendered["live_lag_line"] not in _prompt(cfg, stage), \
            "stage %r is outside the gate and must stay unchanged" % (stage,)


def _prompt_outcome(cfg, stage, tmp_path):
    """`build_prompt`'s outcome as a comparable token, exception type included."""
    try:
        out = _prompt(cfg, stage, tmp_path)
    except Exception as exc:  # the point is to CLASSIFY it, not to tolerate it
        return type(exc).__name__
    return "str" if isinstance(out, str) else type(out).__name__


@pytest.mark.parametrize("bad", [None, "", 0, object()])
def test_b7_an_adversarial_stage_value_behaves_exactly_as_before_the_gate(
        tmp_path, monkeypatch, bad) -> None:
    """The gate must not widen or narrow `build_prompt`'s existing contract.

    MEASURED, not assumed: a non-`str` stage already raises `AttributeError`
    inside `build_prompt` itself on this tree (its own body upper-cases the
    stage), and that is NOT this iteration's business.  So the assertion is a
    DIFFERENTIAL one -- emptying the gate must not change the outcome token --
    which is red exactly when the new feed alters an adversarial path and green
    when the pre-existing behavior is preserved.
    """
    cfg = _cfg(tmp_path, sub="b7bad")
    _script(monkeypatch, {n: WARN for n in RENDERERS})
    with_gate = _prompt_outcome(cfg, bad, tmp_path)
    monkeypatch.setattr(foundry, GATE, ())
    without_gate = _prompt_outcome(cfg, bad, tmp_path)
    assert with_gate == without_gate, \
        "stage %r: outcome %r with the gate vs %r without -- the drift feed " \
        "changed an adversarial path" % (bad, with_gate, without_gate)


def test_b7_a_real_stage_name_still_renders_a_string(tmp_path, monkeypatch) -> None:
    """Non-vacuity for the differential above: the happy path must be a str."""
    cfg = _cfg(tmp_path, sub="b7happy")
    _script(monkeypatch, {n: WARN for n in RENDERERS})
    for stage in SEATS_WITH + SEATS_WITHOUT:
        assert _prompt_outcome(cfg, stage, tmp_path) == "str", \
            "stage %r must render a prompt string" % (stage,)


# ==========================================================================
# Behavior 8 -- off the control and ship paths (resume safety)
# ==========================================================================
CONTROL_FUNCS = ("run_stage", "run_iteration", "run_continuous",
                 "postrelease_step", "preship_cli")
NEW_SYMBOLS = (BLOCK, CAP, GATE)


@pytest.mark.parametrize("func", CONTROL_FUNCS)
@pytest.mark.parametrize("symbol", NEW_SYMBOLS)
def test_b8_no_control_path_function_mentions_the_new_symbols(func, symbol) -> None:
    """The shipped anti-delegation census shape: read the function's own source."""
    target = getattr(foundry, func, None)
    if target is None:
        pytest.skip("foundry.%s is absent from this checkout" % func)
    src = inspect.getsource(target)
    assert symbol not in src, \
        "%s must not appear in %s -- a loop in flight must resume byte-identically" \
        % (symbol, func)


@pytest.mark.parametrize("symbol", NEW_SYMBOLS)
def test_b8_the_dispatcher_is_untouched_by_the_new_symbols(symbol) -> None:
    path = _ROOT / "dispatcher.py"
    assert path.is_file(), "dispatcher.py must exist in the checkout"
    assert symbol not in path.read_text(encoding="utf-8"), \
        "%s must not appear in dispatcher.py" % symbol


def test_b8_the_census_is_not_vacuous() -> None:
    """The same census MUST find the symbols where they really are wired."""
    src = inspect.getsource(foundry.build_prompt)
    assert BLOCK in src, \
        "the census would be vacuous if it could not see the ONE real call site"
    hits = sum(1 for ln in src.splitlines() if BLOCK in ln)
    assert hits <= 3, \
        "ONE call site (plus at most its gate/comment line), got %d lines" % hits


@pytest.mark.parametrize("name", OUT_OF_SCOPE)
def test_b8_the_out_of_scope_renderers_are_not_composed(tmp_path, monkeypatch, name) -> None:
    """Behavior 8(a) + Out of Scope: none of the three excluded renderers is fed.

    A raiser stands in for the excluded name, so the assertion is that it is
    never CALLED at all -- `learnings_head_line` (iteration 367's regression),
    `test_touch_line` (needs a subprocess seam) and `auth_loss_line` (an
    already-cleared tense).
    """
    if not hasattr(foundry, name):
        pytest.skip("foundry.%s is absent from this checkout" % name)
    cfg = _cfg(tmp_path, sub="b8scope")
    _script(monkeypatch, {n: WARN for n in RENDERERS})
    monkeypatch.setattr(foundry, name, _raiser("%s must never be called" % name))
    got = _block(cfg)
    assert isinstance(got, str), "an out-of-scope renderer must not be composed"
    assert len([ln for ln in got.splitlines() if ln.strip()]) == len(RENDERERS)


# ==========================================================================
# Behavior 9 -- no frozen path is touched by this iteration
# ==========================================================================
FROZEN = ("dispatcher.py", ".gitignore", "scripts/")


def test_b9_this_iteration_touches_no_frozen_path() -> None:
    r = _git("diff", "--name-only", "HEAD")
    if r.returncode != 0:
        pytest.skip("git diff unavailable in this checkout")
    changed = tuple(ln.strip() for ln in r.stdout.splitlines() if ln.strip())
    hits = tuple(p for p in changed
                 if p in FROZEN[:2] or p.startswith(FROZEN[2]))
    assert hits == (), \
        "27 permanent guards freeze these paths byte-unchanged; touched: %r" % (hits,)


def test_b9_the_frozen_set_is_measured_not_assumed() -> None:
    """Non-vacuity: the three frozen paths must actually exist to be frozen."""
    assert (_ROOT / "dispatcher.py").is_file()
    assert (_ROOT / ".gitignore").is_file()
    assert (_ROOT / "scripts").is_dir()


# ==========================================================================
# Behavior 10 -- live-tree non-vacuity, as a DERIVED property
# ==========================================================================
def test_b10_the_live_block_is_well_formed() -> None:
    cfg = _live_cfg()
    got = _block(cfg)
    assert isinstance(got, str), "the live block must be a str, got %r" % (type(got),)
    prefixes = tuple(_prefix(n) for n in RENDERERS)
    for line in (ln for ln in got.splitlines() if ln.strip()):
        owner = tuple(p for p in prefixes if line.startswith(p))
        assert len(owner) == 1, \
            "every line must be owned by exactly one shipped prefix: %r" % (line,)
        assert _read(line, owner[0]) == WARN, \
            "every surviving line must carry WARN in the verdict POSITION: %r" % (line,)
    if got:
        assert got.endswith("\n"), "a non-empty block must be newline-terminated"
        assert len(got) <= getattr(foundry, CAP), "the live block honours the cap"


def test_b10_each_gauge_speaks_at_most_once_and_in_a_stable_order() -> None:
    """Derived, never a count, and never the TEXT of a renderer's default call.

    Deliberately NOT asserted here: that a surviving line equals
    `stage_budget_line(cfg)`.  Measured on this tree, the block reproduces the
    line `doctor` prints (`window 20 ... 0 no-output attempt(s) in 1`) while the
    renderer's own DEFAULT call reports the whole history (`... in 183`), so an
    equality here would pin an argument choice the spec never states -- and pin
    it to whichever variant happened to be on disk.
    """
    cfg = _live_cfg()
    got = _block(cfg)
    prefixes = [_prefix(n) for n in RENDERERS]
    seen = []
    for line in (ln for ln in got.splitlines() if ln.strip()):
        owner = [p for p in prefixes if line.startswith(p)]
        assert len(owner) == 1, "line %r has no single owning gauge" % (line,)
        assert owner[0] not in seen, \
            "gauge %r spoke twice -- one line per gauge" % (owner[0],)
        seen.append(owner[0])
    order = [prefixes.index(p) for p in seen]
    assert order == sorted(order), \
        "the gauges must render in one fixed order, got %r" % (seen,)


def test_b10_the_block_is_pure_over_repeated_calls() -> None:
    cfg = _live_cfg()
    assert _block(cfg) == _block(cfg), "the renderer must be pure"


def test_b10_the_live_prompt_carries_exactly_the_live_block(tmp_path) -> None:
    """End to end on the REAL config: what the block renders is what the PM sees."""
    cfg = _live_cfg()
    block = _block(cfg)
    if not block:
        pytest.skip("the live tree reports no drift, so there is nothing to deliver")
    out = _prompt(cfg, "pm", tmp_path)
    assert block in out, "the live PM prompt must carry the live drift block"
    assert block not in _prompt(cfg, "engineer", tmp_path), \
        "and the engineer seat must still not pay for it"


# ==========================================================================
# Behavior 5 (round-2 extension) -- the block is PURELY ADDITIVE, so it can
# never displace a steering-head bullet
#
# The spec's `## Triage` argues this in PROSE: scout B's stated "strongest
# objection" was that a new prompt block would spend the very budget
# `learnings-head: WARN` is warning about, and the PM answered that
# `PROMPT_LEARNINGS_HEAD_BUDGET_CHARS` is computed from the LEARNINGS text
# ALONE, so a block concatenated elsewhere "cannot elide one head bullet".
# That is a testable claim about observable output, and an argument nobody
# re-measures is an argument that rots -- so it is a brake here.
# ==========================================================================
HEAD_MARKER = "MARK%03d"
_HEAD_BULLETS = 40


def _cfg_with_binding_head(tmp_path, sub):
    """A synthetic product whose steering head is FAR over the head budget.

    Returns `(cfg, markers)`.  The learnings text is ~17k chars of uniquely
    marked `## Patterns` bullets, i.e. well past
    `PROMPT_LEARNINGS_HEAD_BUDGET_CHARS`, so the digest must DROP some of them
    -- which is what makes the displacement question non-vacuous.  Everything
    lives under `tmp_path`; nothing ambient is read.
    """
    cfg = _cfg(tmp_path, sub=sub)
    markers = [HEAD_MARKER % i for i in range(_HEAD_BULLETS)]
    body = "\n\n".join(
        "- %s a durable rule %s" % (m, "x" * 400) for m in markers)
    pathlib.Path(cfg.learnings).write_text(
        "## Patterns\n\n" + body + "\n\n## Recent lessons\n\n"
        "- [ENG iter01] a tail lesson\n",
        encoding="utf-8")
    return cfg, markers


def _surviving(prompt, markers):
    return tuple(m for m in markers if m in prompt)


def test_b5_the_fixture_really_binds_the_steering_head_budget(tmp_path) -> None:
    """Non-vacuity guard for the two displacement tests below.

    If every marker reached the prompt, "the same markers survive" would be
    trivially true and would grade nothing.
    """
    cfg, markers = _cfg_with_binding_head(tmp_path, "b5bind")
    kept = _surviving(_prompt(cfg, "pm", tmp_path), markers)
    assert 0 < len(kept) < len(markers), \
        "the head budget must DROP some bullets for this fixture to grade " \
        "anything: %d of %d survived" % (len(kept), len(markers))


def test_b5_the_block_cannot_displace_a_steering_head_bullet(
        tmp_path, monkeypatch) -> None:
    """Three 5,000-char WARNings must not cost the head one bullet."""
    cfg, markers = _cfg_with_binding_head(tmp_path, "b5displace")
    _script(monkeypatch, {n: OK for n in RENDERERS})
    quiet = _prompt(cfg, "pm", tmp_path)
    assert _block(cfg) == "", "the all-OK leg must contribute no block at all"
    _script(monkeypatch, {n: _huge(n) for n in RENDERERS})
    loud = _prompt(cfg, "pm", tmp_path)
    assert _block(cfg), "the WARN leg must contribute a non-empty block"
    assert _surviving(loud, markers) == _surviving(quiet, markers), \
        "the drift block displaced a steering-head bullet: %r vs %r" % (
            _surviving(loud, markers), _surviving(quiet, markers))


def test_b5_the_whole_prompt_cost_of_the_block_is_the_block_itself(
        tmp_path, monkeypatch) -> None:
    """Removing the block's own text from the loud prompt restores the quiet one.

    The strongest available form of "purely additive": not merely that the
    same bullets survive, but that the two prompts are BYTE-IDENTICAL once the
    block is taken back out, and that the entire cost is bounded by the cap.
    """
    cfg, _ = _cfg_with_binding_head(tmp_path, "b5cost")
    _script(monkeypatch, {n: OK for n in RENDERERS})
    quiet = _prompt(cfg, "pm", tmp_path)
    _script(monkeypatch, {n: _huge(n) for n in RENDERERS})
    loud = _prompt(cfg, "pm", tmp_path)
    block = _block(cfg)
    assert block and block in loud
    assert loud.replace(block, "") == quiet, \
        "the block is not purely additive -- removing it does not restore the " \
        "quiet prompt (%d vs %d chars)" % (len(loud.replace(block, "")), len(quiet))
    assert len(loud) - len(quiet) == len(block) <= getattr(foundry, CAP), \
        "the prompt must grow by exactly the capped block, grew by %d" % (
            len(loud) - len(quiet),)


def test_b5_a_smaller_cap_costs_the_prompt_proportionally_less(
        tmp_path, monkeypatch) -> None:
    """The end-to-end prompt cost tracks the module global, not a comment."""
    cfg, _ = _cfg_with_binding_head(tmp_path, "b5capcost")
    _script(monkeypatch, {n: OK for n in RENDERERS})
    quiet = _prompt(cfg, "pm", tmp_path)
    _script(monkeypatch, {n: _huge(n) for n in RENDERERS})
    at_cap = len(_prompt(cfg, "pm", tmp_path)) - len(quiet)
    monkeypatch.setattr(foundry, CAP, 200)
    shrunk = len(_prompt(cfg, "pm", tmp_path)) - len(quiet)
    assert 0 < shrunk <= 200 < at_cap, \
        "shrinking %s must shrink the PROMPT too: %d chars at the cap, %d at " \
        "200" % (CAP, at_cap, shrunk)


# ==========================================================================
# Behavior 1 (round-2 extension) -- WARN-only may not mean "re-injected":
# the block must not put back a head bullet the budget DROPPED
#
# MEASURED CONFLICT, not a hypothesis.  `learnings_head_line` names its WORST
# offender and quotes that bullet's own text, so feeding it to the PM seat
# re-injects text iteration 118 guarantees is dropped from the prompt.  The
# assertion is deliberately REMEDY-NEUTRAL: it pins the invariant (a dropped
# bullet's text stays out of the prompt), not which fix restores it.
# ==========================================================================
def test_b1_the_block_never_re_injects_a_head_bullet_the_budget_dropped(
        tmp_path, monkeypatch) -> None:
    """A drift line about a dropped bullet must not carry the bullet back in."""
    cfg = _cfg(tmp_path, sub="b1reinject")
    marker = "DROPPEDBULLETMARKER"
    pathlib.Path(cfg.learnings).write_text(
        "## Patterns\n\n- keeper rule\n\n- %s over-budget rule %s\n\n"
        "## Recent lessons\n\n- [ENG iter01] a tail lesson\n"
        % (marker, "y" * 300),
        encoding="utf-8")
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_HEAD_BUDGET_CHARS", 40)
    monkeypatch.setattr(foundry, GATE, ())
    without = _prompt(cfg, "pm", tmp_path)
    assert marker not in without, \
        "non-vacuity: with the drift feed OFF the budget must already have " \
        "dropped this bullet, else the test grades nothing"
    monkeypatch.setattr(foundry, GATE, ("pm",))
    with_feed = _prompt(cfg, "pm", tmp_path)
    leaked = [ln for ln in with_feed.splitlines() if marker in ln]
    assert not leaked, \
        "the drift block re-injected a bullet the head budget dropped -- " \
        "iteration 118's guarantee is that its text does NOT reach the " \
        "prompt; leaking line: %r" % (leaked[0][:200] if leaked else "",)


# ==========================================================================
# Two legs the ITERATION-368 spec states that iteration 367's module did not
# assert directly.  Both are cheap and both are load-bearing:
#   - spec behavior 2 words the no-op guarantee as "BYTE-IDENTICAL to the same
#     call with the feed GATED OFF", which is a different arm from "OK equals
#     UNKNOWN" already covered above;
#   - spec behavior 8(a) is pinned above only through a RAISER (proving the
#     excluded renderer is never called).  The property the final gate actually
#     reverted iteration 367 for is stronger: even a LOUD, well-formed WARN from
#     that renderer must contribute no byte.
# ==========================================================================
EXCLUDED = "learnings_head_line"
EXCLUDED_PREFIX = "LEARNINGS_HEAD_PREFIX"


def test_b2_all_ok_is_byte_identical_to_the_feed_gated_off(tmp_path, monkeypatch) -> None:
    """Spec behavior 2, second arm: an all-OK product pays ZERO prompt chars."""
    cfg = _cfg(tmp_path, sub="b2gateoff")
    _script(monkeypatch, {n: OK for n in RENDERERS})
    feed_on = _prompt(cfg, "pm", tmp_path)
    monkeypatch.setattr(foundry, GATE, ())
    feed_off = _prompt(cfg, "pm", tmp_path)
    assert feed_on == feed_off, \
        "an all-OK product must render the PM prompt byte-identically to the " \
        "feed being gated off (%d vs %d chars)" % (len(feed_on), len(feed_off))
    # non-vacuity: the comparison must be capable of failing
    _script(monkeypatch, {n: WARN for n in RENDERERS})
    monkeypatch.setattr(foundry, GATE, ("pm",))
    loud = _prompt(cfg, "pm", tmp_path)
    assert len(loud) > len(feed_off) and loud != feed_off, \
        "non-vacuity: with WARNings the gated-on prompt must DIFFER, else the " \
        "byte-identity above grades nothing"


def test_b8_the_excluded_renderer_is_not_composed_even_when_it_warns(
        tmp_path, monkeypatch) -> None:
    """Spec behavior 8(a), direct form -- iteration 367's regression, pinned.

    The raiser probe proves `learnings_head_line` is not CALLED.  This proves
    the consequence that reverted iteration 367: none of its text, and not even
    its prefix, may reach the block when it renders a loud WARN.
    """
    prefix = getattr(foundry, EXCLUDED_PREFIX, None)
    if not callable(getattr(foundry, EXCLUDED, None)) or not isinstance(prefix, str):
        pytest.skip("foundry.%s / %s absent from this checkout" % (EXCLUDED, EXCLUDED_PREFIX))
    fed = tuple(_prefix(n) for n in RENDERERS)
    assert prefix not in fed, \
        "non-vacuity: the excluded prefix must differ from all fed prefixes, " \
        "else `prefix not in got` is unfalsifiable (%r in %r)" % (prefix, fed)
    cfg = _cfg(tmp_path, sub="b8excl")
    rendered = _script(monkeypatch, {n: WARN for n in RENDERERS})
    marker = "EXCLUDEDRENDERERMARKER"
    monkeypatch.setattr(
        foundry, EXCLUDED,
        lambda *a, **k: "%s %s -- %s over budget" % (prefix, WARN, marker))
    got = _block(cfg)
    assert marker not in got, \
        "the excluded renderer's own text reached the block: %r" % (got,)
    assert prefix not in got, \
        "not even the excluded renderer's prefix may appear: %r" % (got,)
    assert sorted(ln for ln in got.splitlines() if ln.strip()) \
        == sorted(rendered.values()), \
        "exactly the three fed WARN lines, nothing else: %r" % (got,)
    # and the same exclusion must hold end to end, at the real call site
    out = _prompt(cfg, "pm", tmp_path)
    assert marker not in out and prefix not in out, \
        "the excluded renderer leaked into the PM prompt itself"
