"""Iteration 244 -- BLACK-BOX behavior tests: a pure, total, DORMANT derivation of the
tester disposition vocabulary from the classifier's OWN source text, plus the LIVE doc
brake that pins ``ARCHITECTURE.md`` to that vocabulary through the ALREADY-SHIPPED
``sentinel_dormancy_gaps`` checker.

Spec under test (products/_platform/state/iter-244/pm.md), Expected Behaviors 1-8:
   1. ``tester_disposition_tokens(source_text)`` -- module-level, takes SOURCE TEXT
      (never a path); on the live ``foundry.py`` returns exactly
      ``("BLOCKED", "NONE", "PASS", "RED", "UNFINISHED")``: the sorted, de-duplicated
      tuple of every string literal returned by the module-level
      ``def classify_test_report``.
   2. DERIVED, not frozen -- a synthetic classifier returning ``"ALPHA"``/``"BETA"``
      yields ``("ALPHA", "BETA")``; a sixth literal ``"SKIPPED"`` shows up; a source
      with no module-level ``classify_test_report`` yields ``()``.
   3. Scoping is STRUCTURAL and non-string returns are skipped -- a definition inside a
      ``class`` body or nested in another ``def`` is NOT read (``()`` when it is the only
      one); ``return x`` / ``return 1`` / ``return f"{x}"`` / bare ``return`` / bytes are
      skipped, leaving exactly the one string literal, no exception.
   4. PURE and TOTAL -- ``()`` for ``""``, for non-``str`` arguments, for unparseable
      source (``SyntaxError``, embedded NUL); raises for NO input; does not mutate its
      argument; and returns the right answer for an in-memory string while
      ``builtins.open``, ``io.open``, ``pathlib.Path.read_text``, ``subprocess.run``,
      ``socket.socket``, ``os.system`` and ``time.time`` are all raisers.
   5. LIVE DOC BRAKE -- ``sentinel_dormancy_gaps(ARCH, tokens=tester_disposition_tokens(SRC),
      symbol="classify_test_report", call_sites=call_site_count(SRC, symbol=...)) == ()``.
   6. The brake is FALSIFIABLE, not vacuous -- stripping exactly one token's backticked
      citation returns exactly ``("token-not-cited:<TOKEN>",)``, five times; plus a
      non-vacuity floor on the derived tuple itself (>= 5 members, ``"BLOCKED"`` in it).
   7. The doc states the REAL contract -- ``classify_test_report``,
      ``read_test_disposition`` and ``TEST_GATE_REPAIR_DISPOSITIONS`` cited as exact
      backticked spans; the stage-4 rows and the sentinel paragraph no longer frame the
      disposition space as exactly two outcomes; and the prose says ``BLOCKED`` earns no
      repair round and is the one non-``PASS`` disposition the gate may admit, record-only,
      under ``roles/final.md``'s conjunctive conditions.
   8. Nothing else moves -- ``foundry`` and ``dispatcher`` import; the pre-existing
      ``ship_decision`` brake over the same doc still returns ``()``; ``dispatcher.py``,
      ``scripts/``, ``.gitignore``, ``roles/`` and ``launch.sh`` are byte-unchanged vs
      ``HEAD``; and the new function has ZERO call sites outside its own ``def``.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-244 PM spec, the
conventions of ``tests/`` (mirroring ``tests/test_iter239_behavior.py``'s purity raisers
and dormancy census and ``tests/test_iter204_behavior.py``'s name-only git probe), and
the product's OWN OBSERVABLE surface -- importing ``foundry`` and calling the public
oracles.  I did NOT read the implementation source of ``foundry.py`` (behavior 3/8 hand
it to ``ast`` as opaque TEXT, read programmatically), nor ``engineer.md``, nor
``reviewer.md``, nor ``git diff`` output (behavior 8 reads NAMES only, never content).
``ARCHITECTURE.md`` is the DOCUMENT UNDER TEST, not implementation source, and every
assertion on it encodes a spec claim.

Every path read below (``foundry.py``, ``dispatcher.py``, ``watchdog.py``,
``ARCHITECTURE.md``) is GIT-TRACKED, so these preconditions hold in a throwaway fresh
clone -- OPERATOR 2026-08-11.  No absolute machine path appears anywhere in this file
(OPERATOR/iter-205 leak guard).  Fixtures for behaviors 1-4 and 6 are in-memory strings.
"""

import ast
import builtins
import io
import os
import pathlib
import re
import socket
import subprocess
import sys
import time

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe (behavior 8)

THIS_ITER = 244

_FOUNDRY_PY = _ROOT / "foundry.py"
_DISPATCHER_PY = _ROOT / "dispatcher.py"
_WATCHDOG_PY = _ROOT / "watchdog.py"
_ARCH = _ROOT / "ARCHITECTURE.md"

NEW_NAME = "tester_disposition_tokens"
CLASSIFIER = "classify_test_report"

# The five dispositions the spec says the live classifier routes (behavior 1).  Kept as a
# literal so the test states the SPEC's claim; behaviors 2/6 prove the shipped helper
# DERIVES rather than hard-codes them.
LIVE_TOKENS = ("BLOCKED", "NONE", "PASS", "RED", "UNFINISHED")

# Symbols behavior 7 requires the doc to cite as exact backticked spans.
REQUIRED_CITATIONS = (CLASSIFIER, "read_test_disposition", "TEST_GATE_REPAIR_DISPOSITIONS")


def _read(path):
    return path.read_text(encoding="utf-8")


def _collapse(text):
    """Whitespace-collapse for proximity assertions on prose (case PRESERVED)."""
    return re.sub(r"\s+", " ", text)


def _backticked(doc, span):
    """True when ``span`` appears in ``doc`` as an exact backtick-delimited span."""
    return ("`" + span + "`") in doc


def _strip_one_citation(doc, token):
    """Remove the BACKTICKS from every inline span containing ``token`` -- the text stays,
    only its citation status is destroyed.  Other tokens' spans are untouched."""
    return re.sub(
        r"`([^`\n]*)`",
        lambda m: m.group(1) if token in m.group(1) else m.group(0),
        doc,
    )


def _tokens():
    return foundry.tester_disposition_tokens(_read(_FOUNDRY_PY))


def _brake(doc, tokens, symbol):
    src = _read(_FOUNDRY_PY)
    return foundry.sentinel_dormancy_gaps(
        doc,
        tokens=tokens,
        symbol=symbol,
        call_sites=foundry.call_site_count(src, symbol=symbol),
    )


def _call_sites_outside_own_def(source_text, name):
    """Independent ``ast`` census: ``Call`` nodes whose callee names ``name``, excluding
    any that sit inside ``name``'s own ``def``.  Deliberately a SECOND implementation, so
    behavior 8 does not lean on the product's own counter."""
    tree = ast.parse(source_text)
    own_defs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    own_spans = [(d.lineno, getattr(d, "end_lineno", d.lineno)) for d in own_defs]
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        called = getattr(fn, "id", None) or getattr(fn, "attr", None)
        if called != name:
            continue
        line = getattr(node, "lineno", 0)
        if any(lo <= line <= hi for lo, hi in own_spans):
            continue
        hits.append(line)
    return tuple(hits)


# ---------------------------------------------------------------- behavior 1


def test_b1_derivation_exists_at_module_level_and_answers_the_live_tree():
    fn = getattr(foundry, NEW_NAME, None)
    assert callable(fn), f"foundry.{NEW_NAME} must be a module-level callable"
    assert _tokens() == LIVE_TOKENS


def test_b1_takes_source_text_never_a_path():
    """Handing it the PATH STRING of the live file must NOT yield the live answer --
    the argument is TEXT, so a path is just unparseable/irrelevant source."""
    got = foundry.tester_disposition_tokens("foundry.py")
    assert got == (), f"a path string must not be read as source; got {got!r}"


# ---------------------------------------------------------------- behavior 2

_SYNTH_TWO = (
    "def classify_test_report(text):\n"
    "    if text:\n"
    '        return "BETA"\n'
    '    return "ALPHA"\n'
)

_SYNTH_SIXTH = (
    "def classify_test_report(text):\n"
    '    if text == 1:\n        return "PASS"\n'
    '    if text == 2:\n        return "UNFINISHED"\n'
    '    if text == 3:\n        return "BLOCKED"\n'
    '    if text == 4:\n        return "RED"\n'
    '    if text == 5:\n        return "SKIPPED"\n'
    '    return "NONE"\n'
)


def test_b2_derived_not_frozen_synthetic_two_literals():
    assert foundry.tester_disposition_tokens(_SYNTH_TWO) == ("ALPHA", "BETA")


def test_b2_a_sixth_disposition_shows_up():
    got = foundry.tester_disposition_tokens(_SYNTH_SIXTH)
    assert "SKIPPED" in got
    assert got == ("BLOCKED", "NONE", "PASS", "RED", "SKIPPED", "UNFINISHED")


def test_b2_no_module_level_classifier_yields_empty():
    assert foundry.tester_disposition_tokens('def other(t):\n    return "PASS"\n') == ()


def test_b2_result_is_sorted_and_deduped():
    dup = 'def classify_test_report(t):\n    if t:\n        return "Z"\n    return "Z"\n'
    assert foundry.tester_disposition_tokens(dup) == ("Z",)
    unsorted = (
        "def classify_test_report(t):\n"
        '    if t:\n        return "ZULU"\n'
        '    if not t:\n        return "alpha"\n'
        '    return "MIKE"\n'
    )
    got = foundry.tester_disposition_tokens(unsorted)
    assert got == tuple(sorted(got)) and len(got) == len(set(got))


# ---------------------------------------------------------------- behavior 3


def test_b3_class_scoped_definition_is_not_read():
    src = "class Grader:\n    def classify_test_report(self, t):\n" '        return "PASS"\n'
    assert foundry.tester_disposition_tokens(src) == ()


def test_b3_nested_definition_is_not_read():
    src = (
        "def outer():\n"
        "    def classify_test_report(t):\n"
        '        return "PASS"\n'
        "    return classify_test_report\n"
    )
    assert foundry.tester_disposition_tokens(src) == ()


def test_b3_module_level_wins_when_a_shadowed_one_also_exists():
    src = (
        "class Grader:\n"
        "    def classify_test_report(self, t):\n"
        '        return "INNER"\n'
        "def classify_test_report(t):\n"
        '    return "OUTER"\n'
    )
    assert foundry.tester_disposition_tokens(src) == ("OUTER",)


def test_b3_non_string_returns_are_skipped_without_raising():
    src = (
        "def classify_test_report(t):\n"
        "    if t == 0:\n        return marker\n"
        "    if t == 1:\n        return 1\n"
        '    if t == 2:\n        return f"{marker}"\n'
        "    if t == 3:\n        return\n"
        '    if t == 4:\n        return b"BYTES"\n'
        "    if t == 5:\n        return 2.5\n"
        "    if t == 6:\n        return None\n"
        '    return "ONLY"\n'
    )
    assert foundry.tester_disposition_tokens(src) == ("ONLY",)


# ---------------------------------------------------------------- behavior 4


def test_b4_total_over_empty_nonstr_and_unparseable():
    assert foundry.tester_disposition_tokens("") == ()
    for bad in (None, 123, 2.5, b'def classify_test_report(t):\n    return "PASS"\n', ["x"], {}):
        assert foundry.tester_disposition_tokens(bad) == (), f"non-str {type(bad).__name__}"
    assert foundry.tester_disposition_tokens("def classify_test_report(:\n") == ()
    assert foundry.tester_disposition_tokens('def classify_test_report(t):\n    return "PASS"\n\x00') == ()


def test_b4_raises_for_no_input():
    with pytest.raises(TypeError):
        foundry.tester_disposition_tokens()


def test_b4_does_not_mutate_its_argument():
    src = _SYNTH_TWO
    before = "".join(src)
    foundry.tester_disposition_tokens(src)
    assert src == before


def test_b4_pure_with_every_io_and_clock_entry_point_raising(monkeypatch):
    def boom(*a, **k):  # pragma: no cover -- must never be reached
        raise AssertionError("tester_disposition_tokens performed I/O or read the clock")

    with monkeypatch.context() as mp:
        mp.setattr(builtins, "open", boom)
        mp.setattr(io, "open", boom)
        mp.setattr(pathlib.Path, "read_text", boom)
        mp.setattr(pathlib.Path, "read_bytes", boom)
        mp.setattr(subprocess, "run", boom)
        mp.setattr(subprocess, "check_output", boom)
        mp.setattr(socket, "socket", boom)
        mp.setattr(os, "system", boom)
        mp.setattr(time, "time", boom)
        got = foundry.tester_disposition_tokens(_SYNTH_TWO)
        got_empty = foundry.tester_disposition_tokens("")
    assert got == ("ALPHA", "BETA")
    assert got_empty == ()


def test_b4_is_deterministic_across_repeated_calls():
    first = _tokens()
    assert first == _tokens() == _tokens()


# ---------------------------------------------------------------- behavior 5


def test_b5_live_doc_brake_is_satisfied_by_the_shipping_doc():
    assert _brake(_read(_ARCH), _tokens(), CLASSIFIER) == ()


def test_b5_two_sided_same_oracle_reds_a_doc_with_the_citations_stripped():
    """Two-sidedness DEMONSTRATED: the identical call that returns () for the shipped
    doc returns all five gaps once every citation is de-backticked."""
    arch = _read(_ARCH)
    tokens = _tokens()
    stripped = arch
    for token in tokens:
        stripped = _strip_one_citation(stripped, token)
    gaps = _brake(stripped, tokens, CLASSIFIER)
    assert gaps == tuple(f"token-not-cited:{t}" for t in tokens)
    assert _brake(arch, tokens, CLASSIFIER) == ()


# ---------------------------------------------------------------- behavior 6


@pytest.mark.parametrize("token", LIVE_TOKENS)
def test_b6_removing_exactly_one_citation_reds_exactly_that_token(token):
    arch = _read(_ARCH)
    tokens = _tokens()
    assert token in tokens
    gaps = _brake(_strip_one_citation(arch, token), tokens, CLASSIFIER)
    assert gaps == (f"token-not-cited:{token}",)


def test_b6_non_vacuity_floor_on_the_derived_vocabulary():
    tokens = _tokens()
    assert len(tokens) >= 5, tokens
    assert "BLOCKED" in tokens, tokens
    # An unreadable / unparseable source can never satisfy behavior 5 by handing the
    # brake an empty tuple: an empty vocabulary is REJECTED by this floor.
    assert foundry.tester_disposition_tokens("") == ()


# ---------------------------------------------------------------- behavior 7


def test_b7_doc_cites_the_three_symbols_as_exact_backticked_spans():
    arch = _read(_ARCH)
    for symbol in REQUIRED_CITATIONS:
        assert _backticked(arch, symbol), f"{symbol} must appear as a backticked span"
    # negative twin: the checker is not unconditionally true
    assert not _backticked(arch, "read_test_dispositions")


def test_b7_stage4_rows_no_longer_frame_the_space_as_two_outcomes():
    arch = _read(_ARCH)
    stage4 = [line for line in arch.splitlines() if line.startswith("| 4 |")]
    assert stage4, "the stage-4 pipeline row must still exist"
    assert any("five" in line.lower() for line in stage4), stage4
    lower = arch.lower()
    assert "two-valued" not in lower
    for token in LIVE_TOKENS:
        assert _backticked(arch, token) or ("`RESULT: " + token + "`") in arch, token


def test_b7_sentinel_paragraph_names_five_not_two():
    col = _collapse(_read(_ARCH))
    marker = col.find("PROGRESS: CHECKPOINT")
    assert marker != -1, "the mandated marker line must still be documented"
    window = col[max(0, marker - 400): marker + 600]
    assert "five" in window.lower(), window
    assert "FIVE-valued" in col


def test_b7_prose_says_blocked_earns_no_repair_round():
    col = _collapse(_read(_ARCH))
    idx = col.find("TEST_GATE_REPAIR_DISPOSITIONS")
    assert idx != -1
    window = col[max(0, idx - 500): idx + 500]
    assert "repair round" in window.lower(), window
    assert "UNFINISHED" in window and "RED" in window, window
    # The routed pair is named as the WHOLE of the repair set, which is what excludes
    # BLOCKED -- and the shipped tuple is byte-identical to that pair.
    assert foundry.TEST_GATE_REPAIR_DISPOSITIONS == ("UNFINISHED", "RED")


def test_b7_prose_says_blocked_is_the_record_only_admissible_non_pass():
    col = _collapse(_read(_ARCH))
    needed = ("record-only", "roles/final.md", "conjunctive", "non-`pass`")
    found = False
    for m in re.finditer("BLOCKED", col):
        window = col[m.start(): m.start() + 1200].lower()
        if all(n in window for n in needed):
            found = True
            break
    assert found, "no window around BLOCKED states the record-only conjunctive contract"


# ---------------------------------------------------------------- behavior 8


def test_b8_both_entry_modules_import():
    assert foundry.__name__ == "foundry"
    assert dispatcher.__name__ == "dispatcher"
    for module in ("foundry", "dispatcher"):
        proc = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]


def test_b8_preexisting_ship_decision_brake_over_the_same_doc_still_holds():
    assert _brake(_read(_ARCH), foundry.SHIP_DECISION_TOKENS, "ship_decision") == ()


def test_b8_frozen_paths_are_byte_unchanged_against_head():
    proc = subprocess.run(
        [
            "git", "diff", "HEAD", "--name-only", "--",
            "dispatcher.py", "scripts/", ".gitignore", "roles/", "launch.sh",
        ],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:  # no git / no HEAD -- nothing to assert against
        pytest.skip("git unavailable in this environment")
    changed = [line for line in proc.stdout.splitlines() if line.strip()]
    assert changed == [], f"frozen paths changed: {changed}"


def test_b8_new_function_is_dormant_zero_call_sites():
    for path in (_FOUNDRY_PY, _DISPATCHER_PY, _WATCHDOG_PY):
        if not path.exists():
            continue
        hits = _call_sites_outside_own_def(_read(path), NEW_NAME)
        assert hits == (), f"{path.name} calls {NEW_NAME} at lines {hits}"


def test_b8_classifier_still_has_its_one_live_call_site():
    """Guards the OTHER half of the reused brake: the classifier is NOT dormant, so the
    stale-dormant-claim branch (not the missing-dormancy branch) is the reachable one."""
    src = _read(_FOUNDRY_PY)
    assert foundry.call_site_count(src, symbol=CLASSIFIER) == 1
    assert len(_call_sites_outside_own_def(src, CLASSIFIER)) == 1
