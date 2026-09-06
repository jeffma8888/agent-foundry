"""Iteration 238 -- BLACK-BOX behavior tests: a pure, total, dormant extractor for
the module-level ``PROMPT_LEARNINGS_*`` budget constants, plus the two DERIVED
documentation brakes it exists to power.

Spec under test (products/_platform/state/iter-238/pm.md), Expected Behaviors 1-5:
   1. EXTRACTION, SORTED AND DE-DUPLICATED -- two module-level names (one assigned
      twice) come back as a sorted 2-tuple, each name once, declaration order
      irrelevant, a ``tuple`` and not a list or a set.
   2. MODULE-LEVEL ONLY, PREFIX-EXACT -- a name bound inside a ``def`` body, a name
      bound inside a ``class`` body, and three near-miss prefixes are all excluded,
      while an annotated module-level assignment is included.
   3. TOTAL, HONEST WHEN EMPTY, AND PURE -- empty text, unrelated text, syntactically
      invalid text, ``None`` and ``123`` each return ``()`` and raise nothing; two
      calls agree; the input is unchanged; and the call performs no filesystem,
      subprocess, network or clock access.
   4. THE MEMBERSHIP BRAKE, AGAINST THE SHIPPING TREE -- every name the extractor
      derives from the text of ``foundry.py`` appears verbatim in ``ARCHITECTURE.md``.
      Proved non-vacuous (>= 7 names, including ``PROMPT_LEARNINGS_ROLE_RESERVE`` and
      ``PROMPT_LEARNINGS_LABEL``) and proved FAILABLE by planting an undocumented
      constant on an in-memory COPY of that text -- ``foundry.py`` on disk is not
      modified.
   5. THE COUNT-WORD BRAKE, OVER FOUR NAMED OPERATOR DOCS -- ``README.md``,
      ``ARCHITECTURE.md``, ``USAGE.md`` and ``CONTINUOUS.md`` contain no number word or
      digit run immediately preceding the constant prefix, so no prose states a
      count that a new constant can falsify.  The ledger / archive / DIRECTIONS files
      and ``docs/*`` + ``tests/*`` are deliberately OUT of scope: their job is to quote
      retired prose, including this iteration\'s own archive bullet.  Proved failable
      against a literal control string.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-238 PM spec, the
conventions of ``tests/`` (see ``tests/test_iter233_behavior.py``, the same
derive-the-claim-from-the-code template), and the product\'s OWN OBSERVABLE surface --
importing ``foundry`` and calling the one public oracle under test.  I did not read the
implementation source of ``foundry.py`` (it is handed to the oracle as opaque TEXT,
read programmatically inside behavior 4), nor ``engineer.md``, ``reviewer.md``, nor
``git diff``.

Every path read below is GIT-TRACKED repo content (``foundry.py``, ``ARCHITECTURE.md``,
``README.md``, ``USAGE.md``, ``CONTINUOUS.md``), so these preconditions hold in a
throwaway fresh clone -- OPERATOR 2026-08-11: a shipped iteration went post-release
BROKEN on a precondition that was true only in one working tree.  No subprocess, no
git, no network, no clock, no tmp_path.
"""

import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

_FOUNDRY_PY = _ROOT / "foundry.py"
_ARCHITECTURE = _ROOT / "ARCHITECTURE.md"

# Behavior 5's scan scope -- an EXPLICIT four-file allow-list, per the spec.
_SCANNED_DOCS = ("README.md", "ARCHITECTURE.md", "USAGE.md", "CONTINUOUS.md")

# Behavior 5's pattern, verbatim from the spec: a number word or digit run
# immediately preceding the constant prefix, with an optional backtick between.
_COUNT_WORD_RE = re.compile(
    r"(?i)\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+[`]?PROMPT_LEARNINGS"
)

# Behavior 5's control string, verbatim from the spec: the pattern MUST match it, so a
# clean scan of the four docs is known to be a real result and not a dead regex.
_CONTROL = "the same digest core WITHOUT the five `PROMPT_LEARNINGS_*` budgets"

_PREFIX = "PROMPT_LEARNINGS_"


def _oracle():
    """The single public entry point under test."""
    return foundry.prompt_learnings_constants


def _read(path):
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------- behavior 1


def test_b1_extraction_is_sorted_deduplicated_and_a_tuple():
    """Sorted, each name once, declaration order irrelevant, a real ``tuple``."""
    source = "\n".join(
        (
            "PROMPT_LEARNINGS_ZEBRA = 1",
            "PROMPT_LEARNINGS_ALPHA = 2",
            "PROMPT_LEARNINGS_ALPHA = 3",
        )
    )
    got = _oracle()(source)
    assert got == ("PROMPT_LEARNINGS_ALPHA", "PROMPT_LEARNINGS_ZEBRA"), got
    assert isinstance(got, tuple), type(got)
    assert not isinstance(got, list) and not isinstance(got, (set, frozenset)), type(got)


def test_b1_declaration_order_does_not_change_the_result():
    """The reverse declaration order yields the identical tuple."""
    forward = "PROMPT_LEARNINGS_ZEBRA = 1\nPROMPT_LEARNINGS_ALPHA = 2\n"
    backward = "PROMPT_LEARNINGS_ALPHA = 2\nPROMPT_LEARNINGS_ZEBRA = 1\n"
    assert _oracle()(forward) == _oracle()(backward)
    assert _oracle()(forward) == ("PROMPT_LEARNINGS_ALPHA", "PROMPT_LEARNINGS_ZEBRA")


# ---------------------------------------------------------------- behavior 2


_SCOPE_AND_PREFIX_SOURCE = """
def f():
    PROMPT_LEARNINGS_INFUNC = 1
    return PROMPT_LEARNINGS_INFUNC


class C:
    PROMPT_LEARNINGS_INCLASS = 2


OTHER_PROMPT_LEARNINGS_X = 3
PROMPT_LEARNING_Y = 4
PROMPT_LEARNINGS = 5
PROMPT_LEARNINGS_ANNOT: int = 5
"""


def test_b2_module_level_only_and_prefix_exact():
    """def-body, class-body and three near-miss prefixes out; annotated assign in."""
    got = _oracle()(_SCOPE_AND_PREFIX_SOURCE)
    assert got == ("PROMPT_LEARNINGS_ANNOT",), got


def test_b2_each_excluded_name_is_individually_absent():
    """Name the four exclusions one by one, so a failure says WHICH rule broke."""
    got = _oracle()(_SCOPE_AND_PREFIX_SOURCE)
    for excluded in (
        "PROMPT_LEARNINGS_INFUNC",
        "PROMPT_LEARNINGS_INCLASS",
        "OTHER_PROMPT_LEARNINGS_X",
        "PROMPT_LEARNING_Y",
        "PROMPT_LEARNINGS",
    ):
        assert excluded not in got, excluded
    assert "PROMPT_LEARNINGS_ANNOT" in got


# ---------------------------------------------------------------- behavior 3


def test_b3_total_over_empty_unrelated_invalid_and_non_string_inputs():
    """Five hostile inputs, each ``()``, nothing raised."""
    for bad in ("", "x = 1", "def f( this is not python", None, 123):
        got = _oracle()(bad)
        assert got == (), (bad, got)
        assert isinstance(got, tuple), (bad, type(got))


def test_b3_repeat_calls_agree_and_the_input_is_unchanged():
    source = "PROMPT_LEARNINGS_ALPHA = 1\nPROMPT_LEARNINGS_BETA = 2\n"
    before = str(source)
    first = _oracle()(source)
    second = _oracle()(source)
    assert first == second == ("PROMPT_LEARNINGS_ALPHA", "PROMPT_LEARNINGS_BETA")
    assert source == before


def test_b3_the_call_is_pure_no_io_no_subprocess_no_socket_no_clock(monkeypatch):
    """Every ambient side-effect door is slammed for the duration of ONE call.

    A pure function cannot notice; anything that reads a file, shells out, opens a
    socket or asks the clock raises here instead of silently passing.
    """
    import builtins
    import io
    import os
    import socket
    import subprocess
    import time

    def _boom(*_a, **_k):  # pragma: no cover - only runs if purity is violated
        raise AssertionError("prompt_learnings_constants performed a side effect")

    monkeypatch.setattr(builtins, "open", _boom)
    monkeypatch.setattr(io, "open", _boom, raising=False)
    monkeypatch.setattr(pathlib.Path, "read_text", _boom)
    monkeypatch.setattr(pathlib.Path, "open", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "check_output", _boom)
    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom, raising=False)
    monkeypatch.setattr(os, "system", _boom)
    monkeypatch.setattr(time, "time", _boom)
    monkeypatch.setattr(time, "monotonic", _boom)

    got = _oracle()("PROMPT_LEARNINGS_ALPHA = 1\n")
    assert got == ("PROMPT_LEARNINGS_ALPHA",), got


# ---------------------------------------------------------------- behavior 4


def test_b4_every_derived_constant_is_named_in_architecture_md():
    """THE MEMBERSHIP BRAKE: derive from the code, assert the design doc names each."""
    derived = _oracle()(_read(_FOUNDRY_PY))
    architecture = _read(_ARCHITECTURE)
    missing = sorted(name for name in derived if name not in architecture)
    assert missing == [], (
        "ARCHITECTURE.md does not name these shipped PROMPT_LEARNINGS_* constants: "
        + ", ".join(missing)
    )


def test_b4_the_derived_set_is_non_vacuous():
    """>= 7 names, and the two the spec names explicitly are among them."""
    derived = _oracle()(_read(_FOUNDRY_PY))
    assert len(derived) >= 7, derived
    assert "PROMPT_LEARNINGS_ROLE_RESERVE" in derived, derived
    assert "PROMPT_LEARNINGS_LABEL" in derived, derived
    assert all(name.startswith(_PREFIX) for name in derived), derived
    assert list(derived) == sorted(set(derived)), derived


def test_b4_planted_undocumented_constant_proves_the_brake_can_fail():
    """The membership assertion is failable, and the plant never touches disk."""
    original_bytes = _FOUNDRY_PY.read_bytes()
    planted_name = "PROMPT_LEARNINGS_ZZZ_UNDOCUMENTED"
    planted_source = original_bytes.decode("utf-8") + "\n" + planted_name + " = 1\n"

    derived = _oracle()(planted_source)
    assert planted_name in derived, derived
    assert planted_name not in _read(_ARCHITECTURE)

    # The COPY was mutated, never the shipping file.
    assert _FOUNDRY_PY.read_bytes() == original_bytes
    assert planted_name not in original_bytes.decode("utf-8")


# ---------------------------------------------------------------- behavior 5


def test_b5_no_operator_doc_states_a_count_of_the_constants():
    """THE COUNT-WORD BRAKE over exactly four named docs."""
    offenders = []
    for name in _SCANNED_DOCS:
        text = _read(_ROOT / name)
        for match in _COUNT_WORD_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(name + ":" + str(line) + ": " + match.group(0))
    assert offenders == [], "count word before PROMPT_LEARNINGS: " + "; ".join(offenders)


def test_b5_the_count_word_pattern_still_matches_its_control_string():
    """Non-vacuity: a dead regex would pass the scan above for free."""
    assert _COUNT_WORD_RE.search(_CONTROL)


def test_b5_the_scan_scope_is_real_and_reaches_both_drifted_surfaces():
    """A missing or empty doc would make the scan trivially clean.

    MEASURED this stage: only 2 of the 4 scoped docs mention the prefix at all
    (``ARCHITECTURE.md`` 7 times, ``README.md`` once; ``USAGE.md`` and
    ``CONTINUOUS.md`` zero), so the scan is asserted non-trivial where it can bite --
    the two surfaces the spec names as drifted -- rather than in all four files.
    """
    mentions = []
    for name in _SCANNED_DOCS:
        path = _ROOT / name
        assert path.is_file(), name
        text = _read(path)
        assert text.strip(), name
        if _PREFIX in text:
            mentions.append(name)
    assert "README.md" in mentions, mentions
    assert "ARCHITECTURE.md" in mentions, mentions
