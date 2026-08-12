"""Iteration 160 behavior tests -- a pure ``retry_ladder_lines()`` renderer that
derives every distinct per-failure-kind retry ladder by CALLING ``retry_delay``,
plus the corrected ladder clause in ``ARCHITECTURE.md`` / ``CONTINUOUS.md``,
guarded by a whole-rendered-line presence check.

BLACK-BOX / ISOLATION: written from
``products/_platform/state/iter-160/pm.md`` (Expected Behaviors 1-12) plus probing
the PUBLIC interface from an interpreter. The implementation source, the
engineer's notes, the reviewer's notes and ``git diff`` were NOT read. The only
implementation bytes any test here touches are read MECHANICALLY by
:func:`_refs_by_scope` (an AST scan for Behavior 11's dormancy claim), never by a
human reading them.

Offline by construction: no subprocess, no network, no clock, nothing written
anywhere. The only filesystem reads are the two shipped docs the spec names plus
the two modules the dormancy scan parses.

HAZARD PIN (inherited from iteration 159) -- do not "tidy" this into a star or
direct import. ``foundry`` exposes a module-level seam whose name begins with
``test_`` (``test_tree``); ``from foundry import *`` inside a COLLECTED module
re-exports it and pytest then calls it as a zero-argument test. Always reach
through ``foundry.``.

HAZARD PIN (this iteration) -- the DOCS render the ladder with the Unicode arrow
U+2192 while the RENDERER emits ASCII ``->`` (spec Behaviors 3 and 8). Measured:
the ASCII form of every rendered line is ABSENT from the raw bytes of both docs
and present only after folding. So every doc/line comparison MUST go through
:func:`_norm`, applied to BOTH sides; an ASCII-only matcher pointed at these docs
matches NOTHING and the guard fails open silently.
``test_b8_normaliser_is_load_bearing_two_sided`` is the control that keeps that
true, so do not delete it.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
import time

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

ARROW = "\u2192"  # U+2192, the docs' house style. This file stays pure ASCII.

DOCS = ("ARCHITECTURE.md", "CONTINUOUS.md")

# The five kinds the spec names as classified (Behavior 2 / the "Independently
# re-verified" block of pm.md).
SPEC_KINDS = ("timeout", "cli-error", "stalled", "service", "other")

TODAYS_LINES = (
    "timeout, cli-error: 1 -> 2 -> 4 min",
    "stalled: 1 -> 5 -> 20 min",
    "service, other: 10 -> 20 -> 40 min",
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _norm(text: str) -> str:
    """Behavior 8's normalisation: fold ``-->`` and U+2192 to ASCII ``->``, then
    collapse every run of whitespace to one space.

    ONE helper, applied to BOTH sides of every comparison, so a broken normaliser
    fails loudly on both instead of quietly matching nothing.
    """
    return " ".join(text.replace("-->", "->").replace(ARROW, "->").split())


def _doc_text(name: str) -> str:
    return (_ROOT / name).read_text(encoding="utf-8")


def _ladder_of(kind: str) -> tuple[int, ...]:
    """The spec's own definition of a ladder, built from the PUBLIC decision
    function: ``[retry_delay(kind, a) for a in range(1, MAX_ATTEMPTS)]``."""
    return tuple(
        foundry.retry_delay(kind, a) for a in range(1, foundry.MAX_ATTEMPTS)
    )


def _split(line: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split a rendered line into (kinds, minute-strings). Black-box parse of
    Behavior 3's shape ``<kinds>: <m1> -> <m2> -> ... min``."""
    head, _, tail = line.partition(":")
    assert _, f"line has no ':' separator: {line!r}"
    kinds = tuple(k.strip() for k in head.split(","))
    steps = tail.strip()
    assert steps.endswith("min"), f"line does not end in 'min': {line!r}"
    steps = steps[: -len("min")].strip()
    return kinds, tuple(s.strip() for s in steps.split("->"))


class _ImpureAccess(RuntimeError):
    """Raised by a poisoned seam when a supposedly pure function touches it."""


def _refs_by_scope(src: str, name: str) -> dict[str, list[int]]:
    """Map enclosing-function-name -> line numbers where ``name`` is REFERENCED
    (loaded, called or stored in a table). Module-level references are keyed
    ``"<module>"``; the target's own ``def`` is not a reference.

    AST-based on purpose: a text grep would also match the identifier inside a
    docstring or a comment ABOUT the function, which is the fail-open family this
    repo has now tripped twice (matching words about a construct, not the
    construct).
    """
    out: dict[str, list[int]] = {}

    def walk(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, child.name)
                continue
            if isinstance(child, ast.ClassDef):
                walk(child, scope)
                continue
            if isinstance(child, ast.Name) and child.id == name:
                out.setdefault(scope, []).append(child.lineno)
            elif isinstance(child, ast.Attribute) and child.attr == name:
                out.setdefault(scope, []).append(child.lineno)
            walk(child, scope)

    walk(ast.parse(src), "<module>")
    return out


# --------------------------------------------------------------------------
# Behavior 1 -- module-level, no required args, tuple[str, ...], PURE
# --------------------------------------------------------------------------


def test_b1_module_level_callable_no_required_args_returns_tuple_of_str():
    assert callable(foundry.retry_ladder_lines)
    lines = foundry.retry_ladder_lines()  # no arguments
    assert isinstance(lines, tuple), type(lines)
    assert all(isinstance(ln, str) for ln in lines), lines


def test_b1_is_pure_no_filesystem_subprocess_network_or_clock(monkeypatch):
    """Poison every I/O seam a pure renderer must not touch, then call it."""
    baseline = foundry.retry_ladder_lines()

    def poison(label):
        def _boom(*a, **k):
            raise _ImpureAccess(label)

        return _boom

    result = None
    error = None
    with monkeypatch.context() as m:
        import builtins
        import socket

        m.setattr(builtins, "open", poison("builtins.open"))
        m.setattr(pathlib.Path, "open", poison("Path.open"))
        m.setattr(pathlib.Path, "read_text", poison("Path.read_text"))
        m.setattr(pathlib.Path, "read_bytes", poison("Path.read_bytes"))
        m.setattr(pathlib.Path, "exists", poison("Path.exists"))
        m.setattr(subprocess, "run", poison("subprocess.run"))
        m.setattr(subprocess, "Popen", poison("subprocess.Popen"))
        m.setattr(subprocess, "check_output", poison("subprocess.check_output"))
        m.setattr(time, "time", poison("time.time"))
        m.setattr(time, "monotonic", poison("time.monotonic"))
        m.setattr(time, "sleep", poison("time.sleep"))
        m.setattr(socket, "socket", poison("socket.socket"))
        # CONTROL: a poison that has never fired is not evidence of purity.
        try:
            pathlib.Path("ARCHITECTURE.md").read_text(encoding="utf-8")
        except _ImpureAccess:
            harness_live = True
        else:  # pragma: no cover - defect path
            harness_live = False
        try:
            result = foundry.retry_ladder_lines()
        except _ImpureAccess as exc:  # pragma: no cover - defect path
            error = str(exc)
        except Exception as exc:  # pragma: no cover - defect path
            error = f"{type(exc).__name__}: {exc}"

    assert harness_live, "the I/O poisons were not wired; purity was never tested"
    assert error is None, f"retry_ladder_lines() is not pure: touched {error}"
    assert result == baseline


# --------------------------------------------------------------------------
# Behavior 2 -- one line per DISTINCT ladder, derived from retry_delay
# --------------------------------------------------------------------------


def test_b2_one_line_per_distinct_ladder_and_three_lines_today():
    ladders = {k: _ladder_of(k) for k in SPEC_KINDS}
    distinct = {v for v in ladders.values()}
    lines = foundry.retry_ladder_lines()
    assert len(lines) == len(distinct), (lines, sorted(distinct))
    assert len(lines) == 3, lines


def test_b2_kinds_sharing_a_ladder_share_one_line_and_appear_exactly_once():
    lines = foundry.retry_ladder_lines()
    seen: list[str] = []
    for line in lines:
        kinds, _steps = _split(line)
        seen.extend(kinds)
        first = _ladder_of(kinds[0])
        for k in kinds[1:]:
            assert _ladder_of(k) == first, (line, k, _ladder_of(k), first)
    # every classified kind is rendered exactly once, and no kind is invented
    assert sorted(seen) == sorted(SPEC_KINDS), seen
    # kinds on DIFFERENT lines must have DIFFERENT ladders
    per_line = [_ladder_of(_split(l)[0][0]) for l in lines]
    assert len(set(per_line)) == len(per_line), per_line


# --------------------------------------------------------------------------
# Behavior 3 -- shape, ASCII, and today's exact three lines
# --------------------------------------------------------------------------


def test_b3_returns_todays_exact_three_ladder_lines():
    assert foundry.retry_ladder_lines() == TODAYS_LINES


def test_b3_shape_is_kinds_colon_minutes_and_pure_ascii():
    for line in foundry.retry_ladder_lines():
        assert line.isascii(), line
        assert ARROW not in line
        assert "->" in line
        kinds, steps = _split(line)
        assert kinds and all(kinds)
        assert len(steps) == foundry.MAX_ATTEMPTS - 1, (line, steps)
        for s in steps:
            float(s)  # every step is a parseable number of minutes


def test_b3_each_rendered_minute_equals_the_real_delay_over_sixty():
    """The rendered figures must be the delays that actually FIRE: retries happen
    while attempt < MAX_ATTEMPTS, i.e. attempts 1..MAX_ATTEMPTS-1."""
    for line in foundry.retry_ladder_lines():
        kinds, steps = _split(line)
        expected = [
            foundry.retry_delay(kinds[0], a)
            for a in range(1, foundry.MAX_ATTEMPTS)
        ]
        assert [float(s) for s in steps] == [
            d / 60 for d in expected
        ], (line, expected)


# --------------------------------------------------------------------------
# Behavior 4 -- deterministic ordering
# --------------------------------------------------------------------------


def test_b4_two_calls_return_equal_tuples():
    assert foundry.retry_ladder_lines() == foundry.retry_ladder_lines()


def test_b4_lines_ordered_by_first_delay_ascending():
    firsts = [
        float(_split(l)[1][0]) for l in foundry.retry_ladder_lines()
    ]
    assert firsts == sorted(firsts), firsts


def _smallest_first_delay(lines):
    return min(float(_split(l)[1][0]) for l in lines)


def test_b4_tie_on_first_delay_broken_by_alphabetically_smallest_kind():
    """AMBIGUITY (reported to the PM): Behavior 4's "then by the first kind name
    alphabetically" has two readings, and two shipped ladders both start at 60s so
    the tie-break decides the whole tuple. Reading A = the line's LEADING kind
    (``timeout`` vs ``stalled`` -> stalled first). Reading B = the alphabetically
    smallest kind ON the line (``cli-error`` vs ``stalled`` -> the fast line
    first). Only reading B reproduces the three lines Behavior 3 enumerates, so
    the worked example is the tie-breaker and reading B is what is tested."""
    lines = foundry.retry_ladder_lines()
    tied = [l for l in lines if float(_split(l)[1][0]) == _smallest_first_delay(lines)]
    assert len(tied) >= 2, ("expected a real tie to exist", lines)
    keys = [min(_split(l)[0]) for l in tied]
    assert keys == sorted(keys), (tied, keys)


def test_b4_kinds_within_a_line_are_deterministic_across_calls():
    a = [_split(l)[0] for l in foundry.retry_ladder_lines()]
    b = [_split(l)[0] for l in foundry.retry_ladder_lines()]
    assert a == b


# --------------------------------------------------------------------------
# Behavior 5 -- minute formatting
# --------------------------------------------------------------------------


def test_b5_whole_minutes_render_as_integers():
    for line in foundry.retry_ladder_lines():
        _kinds, steps = _split(line)
        for s in steps:
            assert "." not in s, (line, s)  # 60 -> "1", never "1.0"


def test_b5_non_whole_minutes_render_with_one_decimal(monkeypatch):
    monkeypatch.setattr(foundry, "KIND_RETRY_LADDERS", {"stalled": [90, 90, 90]})
    lines = foundry.retry_ladder_lines()
    assert "stalled: 1.5 -> 1.5 -> 1.5 min" in lines, lines


def test_b5_never_emits_a_trailing_dot_zero(monkeypatch):
    """61s is 1.0166.. min: a literal "one decimal otherwise" would emit the
    forbidden "1.0", so the prohibition decides this case."""
    monkeypatch.setattr(foundry, "KIND_RETRY_LADDERS", {"stalled": [61, 61, 61]})
    for line in foundry.retry_ladder_lines():
        _kinds, steps = _split(line)
        for s in steps:
            assert not s.endswith(".0"), (line, s)
    assert "stalled: 1 -> 1 -> 1 min" in foundry.retry_ladder_lines()


# --------------------------------------------------------------------------
# Behavior 6 -- DERIVED at call time via bare-name global reads
# --------------------------------------------------------------------------


def test_b6_patching_kind_retry_ladders_changes_the_line(monkeypatch):
    monkeypatch.setattr(
        foundry, "KIND_RETRY_LADDERS", {"stalled": [120, 120, 120]}
    )
    assert "stalled: 2 -> 2 -> 2 min" in foundry.retry_ladder_lines()


def test_b6_patching_timeout_backoffs_changes_the_fast_line(monkeypatch):
    monkeypatch.setattr(foundry, "TIMEOUT_BACKOFFS", [30, 30, 30])
    assert "timeout, cli-error: 1 -> 1 -> 1 min" in foundry.retry_ladder_lines()


def test_b6_patching_backoffs_changes_the_default_line(monkeypatch):
    monkeypatch.setattr(foundry, "BACKOFFS", [900, 900, 900])
    assert "service, other: 15 -> 15 -> 15 min" in foundry.retry_ladder_lines()


def test_b6_patching_fast_retry_kinds_regroups_the_lines(monkeypatch):
    monkeypatch.setattr(foundry, "FAST_RETRY_KINDS", ("timeout",))
    lines = foundry.retry_ladder_lines()
    assert "timeout: 1 -> 2 -> 4 min" in lines, lines
    # cli-error has left the fast ladder, so it must not be rendered with it
    assert not any(l.startswith("timeout, cli-error") for l in lines), lines
    joined = " | ".join(lines)
    assert "cli-error" in joined, lines


def test_b6_smaller_max_attempts_emits_fewer_steps(monkeypatch):
    monkeypatch.setattr(foundry, "MAX_ATTEMPTS", 2)
    for line in foundry.retry_ladder_lines():
        _kinds, steps = _split(line)
        assert len(steps) == 1, (line, steps)


# --------------------------------------------------------------------------
# Behavior 7 -- non-vacuity floor
# --------------------------------------------------------------------------


def test_b7_non_vacuity_floor_for_shipped_constants():
    lines = foundry.retry_ladder_lines()
    assert lines != ()
    assert len(lines) >= 3, lines
    for line in lines:
        assert line.strip(), lines
        assert "min" in line, line


def test_b7_never_empty_even_at_max_attempts_one(monkeypatch):
    """AMBIGUITY (reported to the PM): Behavior 2's literal
    ``range(1, MAX_ATTEMPTS)`` is EMPTY at ``MAX_ATTEMPTS == 1``, which Behavior
    7's "never returns an empty tuple, no line is empty" forbids. Only one
    reading satisfies the explicit prohibition, so the prohibition is tested."""
    monkeypatch.setattr(foundry, "MAX_ATTEMPTS", 1)
    lines = foundry.retry_ladder_lines()
    assert lines != (), "empty tuple at MAX_ATTEMPTS=1 violates Behavior 7"
    for line in lines:
        assert line.strip(), lines
        assert "min" in line, line
        _kinds, steps = _split(line)
        assert steps and all(steps), (line, steps)


# --------------------------------------------------------------------------
# Behavior 8 -- both docs carry every rendered line (under ONE normaliser)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("doc", DOCS)
def test_b8_every_rendered_line_is_present_in_the_doc(doc):
    haystack = _norm(_doc_text(doc))
    for line in foundry.retry_ladder_lines():
        needle = _norm(line)
        assert needle in haystack, f"{doc} is missing the rendered ladder line: {needle!r}"


@pytest.mark.parametrize("doc", DOCS)
def test_b8_normaliser_is_load_bearing_two_sided(doc):
    """Control for the fail-open hazard: prove the docs really use U+2192, so an
    ASCII-blind matcher would find NOTHING, and prove the folded matcher fires."""
    raw = _doc_text(doc)
    assert ARROW in raw, f"{doc} lost its U+2192 house style; re-check this control"
    for line in foundry.retry_ladder_lines():
        assert line not in raw, (
            f"{doc} carries the ASCII form of {line!r}; this control no longer "
            "proves the normaliser is load-bearing"
        )
        assert _norm(line) in _norm(raw)


# --------------------------------------------------------------------------
# Behavior 9 -- two-sided drift control (a guard, not a snapshot)
# --------------------------------------------------------------------------


def test_b9_drifted_ladder_is_absent_from_both_docs(monkeypatch):
    before = foundry.retry_ladder_lines()
    monkeypatch.setattr(
        foundry, "KIND_RETRY_LADDERS", {"stalled": [120, 120, 120]}
    )
    after = foundry.retry_ladder_lines()
    assert after != before, "patching a ladder did not change the rendered lines"
    drifted = [l for l in after if l not in before]
    assert drifted, (before, after)
    for doc in DOCS:
        haystack = _norm(_doc_text(doc))
        for line in drifted:
            assert _norm(line) not in haystack, (
                f"{doc} already carries the DRIFTED line {line!r}; the presence "
                "guard would then be a snapshot, not a drift detector"
            )


# --------------------------------------------------------------------------
# Behavior 10 -- nothing else in the resilience text changed
# --------------------------------------------------------------------------


@pytest.mark.parametrize("doc", DOCS)
def test_b10_docs_still_state_four_attempts_and_the_cooldown_ladder(doc):
    normed = _norm(_doc_text(doc))
    assert "4 attempts" in normed, doc
    squashed = "".join(normed.split())
    assert "30m->1h->2h->4h" in squashed, doc


def test_b10_architecture_keeps_the_bold_resilience_name():
    doc = _doc_text("ARCHITECTURE.md")
    assert "**Resilience.**" in doc
    # the iteration-149 pin, restated in the same shape it asserts
    assert "resilience" in " ".join(doc.lower().split())


# --------------------------------------------------------------------------
# Behavior 11 -- additive-dormant: ZERO call sites in the pipeline
# --------------------------------------------------------------------------

PIPELINE_FUNCS = (
    "run_stage",
    "run_iteration",
    "build_prompt",
    "postrelease_step",
)


def test_b11_no_call_site_in_the_pipeline_or_dispatcher():
    foundry_refs = _refs_by_scope(
        (_ROOT / "foundry.py").read_text(encoding="utf-8"), "retry_ladder_lines"
    )
    for fn in PIPELINE_FUNCS:
        assert fn not in foundry_refs, (fn, foundry_refs.get(fn))
    # a CLI dispatch-table entry would be a MODULE-level reference
    assert "<module>" not in foundry_refs, foundry_refs["<module>"] if "<module>" in foundry_refs else None
    dispatcher_refs = _refs_by_scope(
        (_ROOT / "dispatcher.py").read_text(encoding="utf-8"), "retry_ladder_lines"
    )
    assert dispatcher_refs == {}, dispatcher_refs


def test_b11_dormancy_scanner_fires_on_a_planted_call_site():
    """Two-sided: a detector that has never fired is not evidence of health."""
    planted_in_stage = "def run_stage(x):\n    return retry_ladder_lines()\n"
    assert "run_stage" in _refs_by_scope(planted_in_stage, "retry_ladder_lines")

    planted_in_table = 'TABLE = {"retry-ladder": retry_ladder_lines}\n'
    assert "<module>" in _refs_by_scope(planted_in_table, "retry_ladder_lines")

    planted_attr = "def build_prompt():\n    foundry.retry_ladder_lines()\n"
    assert "build_prompt" in _refs_by_scope(planted_attr, "retry_ladder_lines")

    # and it must NOT fire on the definition alone, nor on prose ABOUT the name
    only_def = (
        'def retry_ladder_lines():\n'
        '    """retry_ladder_lines renders the ladders."""\n'
        '    return ()\n'
    )
    assert _refs_by_scope(only_def, "retry_ladder_lines") == {}


# --------------------------------------------------------------------------
# Behavior 12 -- both modules still import
# --------------------------------------------------------------------------


def test_b12_foundry_and_dispatcher_still_import():
    import importlib

    assert importlib.import_module("foundry") is not None
    assert importlib.import_module("dispatcher") is not None
