"""Iteration 430 behavior tests -- ARCHITECTURE.md stale claim fix and dormant
``architecture_gate_recovery_claim_gaps`` guard.

The iteration replaces line 71's present-tense "8 rounds are still recoverable
from the attempt logs on disk" with a past-tense historical note, adds a dormant
guard ``architecture_gate_recovery_claim_gaps(doc, *, anchor)`` that detects the
stale claim pattern, and bumps the ``_paragraph_around(`` count pin from 3 to 4
in ``test_iter419_behavior.py``.

ISOLATION CONTRACT (honored): every assertion below derives from the PM spec's
Expected Behaviors 1-8 (``products/_platform/state/iter-430/pm.md``) and from
existing test conventions under ``tests/`` (iter419, iter423 suites). The
implementation source, engineer's notes, reviewer's notes, and ``git diff``
were NOT read. The guard function is driven as a BLACK BOX through its public
signature and return value.

No subprocess, no git, no network, no clock. Filesystem reads are limited to
the TRACKED ``ARCHITECTURE.md`` and production modules located at RUNTIME from
``foundry.__file__`` -- never a gitignored ``state/`` path.
"""

from __future__ import annotations

import importlib
import inspect
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

FN_NAME = "architecture_gate_recovery_claim_gaps"
ARCH_PATH = _ROOT / "ARCHITECTURE.md"

ANCHOR = "ACTION: REVERTED"


def _fn():
    fn = getattr(foundry, FN_NAME, None)
    assert fn is not None, f"foundry.{FN_NAME} must exist"
    assert callable(fn), f"foundry.{FN_NAME} must be callable"
    return fn


def _arch_text():
    return ARCH_PATH.read_text()


def _module_src(name):
    p = _ROOT / name
    assert p.exists(), f"{name} missing"
    return p.read_text()


# ── Behavior 1: line 71 carries past-tense text, no present-tense count ──

def test_b1_edited_line_is_past_tense():
    doc = _arch_text()
    para = " ".join(_paragraph_lines(doc, ANCHOR))
    assert "before iteration 194 closed the gap" in para, (
        "Expected past-tense phrasing about iteration 194 closing the gap"
    )
    assert "8 rounds are still recoverable" not in para, (
        "Old stale claim must be removed"
    )


def test_b1_no_present_tense_recoverable_count():
    doc = _arch_text()
    para = " ".join(_paragraph_lines(doc, ANCHOR))
    present_tense_pattern = re.compile(
        r"\d[^.!?]*\brecoverable\b|\brecoverable\b[^.!?]*\d"
    )
    assert not present_tense_pattern.search(para), (
        "No digit+recoverable co-occurrence should remain in the paragraph"
    )


def test_b1_no_recoverable_in_edited_sentence():
    doc = _arch_text()
    para = " ".join(_paragraph_lines(doc, ANCHOR))
    assert "iteration 194 closed" in para, (
        "Could not find the replacement sentence in the paragraph"
    )
    sentences = re.split(r"[.!?]", para)
    for s in sentences:
        if "iteration 194 closed" in s:
            assert "recoverable" not in s.lower(), (
                "The replacement sentence must not contain 'recoverable'"
            )
            break


# ── Behavior 2: surrounding sentences unchanged ──

_SENTINEL_TOKENS = (
    "SHIP_DECISION_TOKENS",
    "ship_decision",
    "SHIP",
    "RETRY",
    "REVERT",
    "FINAL_GATE_MAX_ROUNDS",
)


def _paragraph_lines(text, anchor):
    lines = text.split("\n")
    anchor_idx = None
    for i, line in enumerate(lines):
        if anchor in line:
            anchor_idx = i
            break
    if anchor_idx is None:
        return []
    start = anchor_idx
    while start > 0 and lines[start - 1].strip():
        start -= 1
    end = anchor_idx
    while end < len(lines) - 1 and lines[end + 1].strip():
        end += 1
    return lines[start : end + 1]


def test_b2_sentinel_tokens_intact():
    doc = _arch_text()
    para = "\n".join(_paragraph_lines(doc, ANCHOR))
    assert len(para) > 100, "Paragraph must be non-trivial"
    for token in ("ship_decision", "SHIP_DECISION_TOKENS"):
        assert token in para, f"Sentinel token {token!r} must remain in the paragraph"
    broader = "\n".join(_paragraph_lines(doc, "FINAL_GATE_MAX_ROUNDS"))
    for token in _SENTINEL_TOKENS:
        assert token in doc, f"Sentinel token {token!r} must exist in ARCHITECTURE.md"


def test_b2_ship_decision_paragraph_mentions_vocabulary():
    doc = _arch_text()
    para = "\n".join(_paragraph_lines(doc, ANCHOR))
    for t in ("SHIP", "RETRY", "REVERT"):
        assert t in para, f"Vocabulary token {t!r} must remain in the paragraph"


# ── Behavior 3: function exists with correct signature ──

def test_b3_function_exists_and_signature():
    fn = _fn()
    sig = inspect.signature(fn)
    params = list(sig.parameters.keys())
    assert "doc" in params, "First param must be 'doc'"
    assert "anchor" in params, "Must accept 'anchor' keyword"
    p_anchor = sig.parameters["anchor"]
    assert p_anchor.default == ANCHOR, (
        f"Default anchor must be {ANCHOR!r}, got {p_anchor.default!r}"
    )


def test_b3_return_type_is_tuple():
    fn = _fn()
    result = fn("some irrelevant text without the anchor")
    assert isinstance(result, tuple), f"Must return tuple, got {type(result)}"


# ── Behavior 4: guard returns () on the LIVE ARCHITECTURE.md ──

def test_b4_live_doc_returns_empty():
    fn = _fn()
    doc = _arch_text()
    result = fn(doc)
    assert result == (), f"Live ARCHITECTURE.md must produce (), got {result!r}"


# ── Behavior 5: guard returns non-empty on old text ──

OLD_SENTENCE = "and 8 rounds are still recoverable from the attempt logs on disk"


def _build_old_paragraph():
    return (
        "Until iteration 194 the final gate collapsed both into the same "
        "answer as an explicit\n"
        "ACTION: REVERTED, so a gate killed at the hard per-stage cap "
        "mid-verification destroyed\n"
        "an otherwise-green iteration -- which happened nine times "
        + OLD_SENTENCE
        + ".\n"
        "That answer is right for a stage that RAN TO COMPLETION "
        "(no verdict is evidence about the artifact) and lossy for one "
        "that was KILLED. ship_decision is the fix."
    )


def test_b5_old_text_returns_nonempty():
    fn = _fn()
    old_doc = _build_old_paragraph()
    result = fn(old_doc)
    assert len(result) > 0, (
        "Old text with 'recoverable' + digit must produce non-empty tuple"
    )
    assert all(isinstance(s, str) for s in result), "Every gap must be a string"


def test_b5_old_text_names_the_stale_claim():
    fn = _fn()
    old_doc = _build_old_paragraph()
    result = fn(old_doc)
    combined = " ".join(result).lower()
    assert "recoverable" in combined or "stale" in combined, (
        f"Finding should name the stale claim, got {result!r}"
    )


# ── Behavior 5 variants: single-deletion mutation tests ──

def test_b5_digit_alone_no_false_positive():
    fn = _fn()
    doc_digit_only = (
        "ACTION: REVERTED, so 8 attempts were tried.\n"
        "ship_decision is the fix."
    )
    result = fn(doc_digit_only)
    assert result == (), (
        "A digit without 'recoverable' must not trigger the guard"
    )


def test_b5_recoverable_alone_no_false_positive():
    fn = _fn()
    doc_word_only = (
        "ACTION: REVERTED, the recoverable verb was introduced.\n"
        "ship_decision handles retries."
    )
    result = fn(doc_word_only)
    assert result == (), (
        "'recoverable' without a digit in the same sentence must not trigger"
    )


# ── Behavior 3 edge cases: fail-closed on bad input ──

def test_b3_empty_string_returns_nonempty():
    fn = _fn()
    result = fn("")
    assert len(result) > 0, "Empty doc must produce a non-empty tuple (fail-closed)"


def test_b3_non_matching_doc_returns_nonempty():
    fn = _fn()
    result = fn("This document has no relevant content at all.")
    assert len(result) > 0, (
        "A doc missing the anchor must produce a non-empty tuple (fail-closed)"
    )


# ── Behavior 6: sentinel_dormancy_gaps tests remain green ──
# (verified by the full suite run; no separate re-invocation needed,
#  but we can spot-check the pinned tokens exist in the live doc)

def test_b6_sentinel_dormancy_tokens_present():
    doc = _arch_text()
    for token in _SENTINEL_TOKENS:
        assert token in doc, (
            f"Token {token!r} must exist in ARCHITECTURE.md for "
            "sentinel_dormancy_gaps tests to remain green"
        )


# ── Behavior 7: importability ──

def test_b7_foundry_importable():
    m = importlib.import_module("foundry")
    assert m is foundry


def test_b7_dispatcher_importable():
    m = importlib.import_module("dispatcher")
    assert m is not None


# ── Behavior 8 (dormancy): zero call sites outside the def ──

def test_b8_dormant_no_call_sites_outside_def():
    module_src = _module_src("foundry.py")
    block = inspect.getsource(_fn())
    assert module_src.count(block) == 1, "Def block must appear exactly once"
    remainder = module_src.replace(block, "", 1)
    assert remainder.count(f"{FN_NAME}(") == 0, (
        f"{FN_NAME}( referenced outside its def -- not dormant"
    )


def test_b8_dispatcher_never_names_the_guard():
    disp_src = _module_src("dispatcher.py")
    assert disp_src.count(FN_NAME) == 0, (
        f"{FN_NAME} leaked into dispatcher.py"
    )


def test_b8_paragraph_around_count_pin():
    module_src = _module_src("foundry.py")
    assert module_src.count("_paragraph_around(") == 4, (
        f"Expected 4 _paragraph_around( call sites, got "
        f"{module_src.count('_paragraph_around(')}"
    )
