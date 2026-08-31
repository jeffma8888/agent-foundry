"""Black-box behaviour tests for iter 205 -- `authoritative_tester_report` must REFUSE a
bare `str` / `bytes` / `bytearray` LOUDLY instead of silently answering `None`, because
`None` from this helper is the positive reading "no tester report is present" and a
pessimistic release gate turns that into `ACTION: REVERTED`.

Spec: products/_platform/state/iter-206/pm.md -- the operator-directed RETRY of iter 205.
Behaviors 1-8 are carried VERBATIM from the iter-205 spec; Behavior 9 is the addition
the revert bought. Expected Behaviors 1-9.

   1. `authoritative_tester_report(x)` raises `TypeError` when `x` is a `str` -- for all
      three real shapes: an absolute state-dir path, a single name `"tester.md"`, and `""`
      (falsy, so it reached `None` today; the rule is purely type-shaped).
   2. ... raises `TypeError` when `x` is `bytes` or `bytearray`.
   3. The message names BOTH the received type AND the expected shape (an iterable of
      report NAMES, or `None`), so a stage agent can repair the call from the traceback.
   4. PARITY -- every shape accepted today returns exactly its current value.
   5. PARITY -- shapes that are neither `str` nor iterable (`pathlib.Path`, `int`,
      `object`) still raise `TypeError`. The guard ADDS a refused case; it never converts
      a raise into an answer or an answer into a raise.
   6. `authoritative_tester_report.__doc__` states the refusal -- no totality claim is
      left unqualified.
   7. `read_authoritative_tester_result(dir)` is UNCHANGED end-to-end on real directories,
      so the new guard can never fire on the live path.
   8. `roles/final.md` gate checklist item 2 carries the list-shaped call clause, stays
      pure ASCII, and still names a helper (so iter 180's `test_b17` brake stays green).
   9. `STR_SHAPES[0]` is a RELATIVE path literal -- the public-safety regression the
      iter-205 revert bought -- and all three `str` shapes of Behavior 1 still stand.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-205 and iter-206 PM specs,
the `tests/`
conventions (`tests/test_iter180_behavior.py`, which owns this helper family), the tracked
`roles/final.md` role card named by Behavior 8, and the product's OBSERVABLE behaviour via
its public interface (calls + `__doc__`). `foundry.py`'s implementation source, the
engineer's and reviewer's notes and `git diff` were NOT read. Every assertion is on an
observable answer, message, docstring or tracked artifact -- never on an implementation
detail. Behavior 9 was added by the iteration-206 tester under the same contract: it
asserts a property of THIS file's own fixture, so it needs no implementation knowledge.

HERMETIC: Behavior 7's fixtures are built under `tmp_path`. The only ambient paths read are
TRACKED ones -- `roles/final.md` (Behavior 8) and `tests/*.py` (the blast-radius census) --
so a FRESH CLONE passes; no assertion touches gitignored state (`products/*/state/`,
`LEARNINGS.md`), which is the iter-154/155 trap. No network, no subprocess, no git, no
clock, no sleeps.

XDIST-SAFETY: nothing here mutates module globals or the cwd, so every test is
process-local and safe under `-n auto`.
"""
from __future__ import annotations

import os.path
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

# The three real wrong shapes the spec names, as a `str`.
STR_SHAPES = (
    "products/_platform/state/iter-204",  # dir path
    "tester.md",                                                          # a single name
    "",                                                                   # falsy -> None
)


# --------------------------------------------------------------------------- helpers
def _report(d, name, verdict):
    """A tester report whose LAST non-empty line is the role-owned sentinel (mirrors
    tests/test_iter180_behavior.py)."""
    (pathlib.Path(d) / name).write_text(
        f"test report {name}\n\nsome prose\n\nRESULT: {verdict}\n\n   \n\t\n"
    )


def _dir_with(base, **reports):
    """tmp dir holding {report-name: verdict}; keys use `_md` for `.md`."""
    d = pathlib.Path(base)
    d.mkdir(parents=True, exist_ok=True)
    for key, verdict in reports.items():
        _report(d, key.replace("_md", ".md"), verdict)
    return d


def _item2(text):
    """The gate checklist item 2 SPAN of roles/final.md, not merely the whole file."""
    start = text.index("2. Tester result is PASS")
    return text[start:text.index("\n3. ", start)]


# -------------------------------------------------------------------- Behaviors 1-2
@pytest.mark.parametrize("bad", STR_SHAPES)
def test_b01_a_bare_str_is_refused_loudly(bad):
    """Behavior 1 -- every real `str` shape raises instead of answering None.

    `""` matters most: it is FALSY, so it reached the `None` fallback today. Guarding on
    type BEFORE falsiness is what makes the rule statable in one clause with no exception.
    """
    with pytest.raises(TypeError):
        foundry.authoritative_tester_report(bad)


@pytest.mark.parametrize("bad", [b"tester.md", bytearray(b"tester.md"), b"", bytearray()])
def test_b02_bytes_and_bytearray_are_refused(bad):
    """Behavior 2 -- the other two element-wise-iterating scalar types, empty included."""
    with pytest.raises(TypeError):
        foundry.authoritative_tester_report(bad)


# ---------------------------------------------------------------------- Behavior 3
@pytest.mark.parametrize("bad,typename", [
    (STR_SHAPES[0], "str"),
    (STR_SHAPES[1], "str"),
    (STR_SHAPES[2], "str"),
    (b"tester.md", "bytes"),
    (bytearray(b"tester.md"), "bytearray"),
])
def test_b03_message_names_the_received_type_and_the_expected_shape(bad, typename):
    """Behavior 3 -- repairable from the traceback alone, without reading foundry.py."""
    with pytest.raises(TypeError) as exc:
        foundry.authoritative_tester_report(bad)
    msg = str(exc.value)
    low = msg.lower()
    assert typename in msg, f"received type {typename!r} not named: {msg!r}"
    # the expected shape: an ITERABLE of report NAMES, or None
    assert "iterable" in low, msg
    assert "name" in low, msg
    assert "none" in low, msg


def test_b03b_message_is_ascii_and_actionable():
    """Behavior 3 -- the message survives a plain-text log and names a working call."""
    with pytest.raises(TypeError) as exc:
        foundry.authoritative_tester_report("tester.md")
    msg = str(exc.value)
    msg.encode("ascii")                     # raises if a smart quote / dash crept in
    assert "authoritative_tester_report" in msg, msg
    assert "read_authoritative_tester_result" in msg, (
        "the message should point at the sibling that DOES take a directory: " + msg
    )


# ---------------------------------------------------------------------- Behavior 4
def _gen():
    return (n for n in ("tester.md", "tester2.md"))


@pytest.mark.parametrize("arg,want,label", [
    (None, None, "None"),
    ([], None, "empty list"),
    (set(), None, "empty set"),
    (["tester.md"], "tester.md", "single-name list"),
    ({"tester.md", "tester2.md"}, "tester2.md", "two-round set"),
    ({"tester.md", "tester3.md"}, "tester3.md", "gap set -- a missing middle round"),
    ({"tester.md", "tester2.md", "tester3.md"}, "tester3.md", "three-round set"),
    (["tester.md", "tester.md", "tester2.md", "tester2.md"], "tester2.md", "duplicates"),
    ({"reviewer.md"}, None, "unrelated name only"),
    (("tester.md", "tester2.md"), "tester2.md", "tuple"),
])
def test_b04_every_accepted_shape_keeps_its_current_answer(arg, want, label):
    """Behavior 4 -- PARITY. The guard must not disturb any shape that answers today."""
    assert foundry.authoritative_tester_report(arg) == want, label


def test_b04b_a_one_shot_generator_still_answers():
    """Behavior 4 -- the generator case, kept separate because it cannot be reused."""
    assert foundry.authoritative_tester_report(_gen()) == "tester2.md"


# ---------------------------------------------------------------------- Behavior 5
@pytest.mark.parametrize("bad", [
    pathlib.Path("/a/b"),
    123,
    object(),
    3.5,
    True,
])
def test_b05_non_iterable_shapes_still_raise_type_error(bad):
    """Behavior 5 -- PARITY on the other side: these raised before and still raise, so
    the guard only ADDS a refused case."""
    with pytest.raises(TypeError):
        foundry.authoritative_tester_report(bad)


# ---------------------------------------------------------------------- Behavior 6
def test_b06_docstring_states_the_refusal():
    """Behavior 6 -- the docstring cannot advertise a contract the code dropped."""
    doc = foundry.authoritative_tester_report.__doc__
    assert doc, "the helper lost its docstring"
    assert "TypeError" in doc, "the docstring does not name the exception it now raises"
    for t in ("str", "bytes", "bytearray"):
        assert t in doc, f"the docstring does not name the refused type {t!r}"


def test_b06b_no_totality_claim_is_left_unqualified():
    """Behavior 6 -- a paragraph promising TOTAL / 'accepted without raising' must carry
    its own scope or the exception, so the sentence cannot be read as unconditional."""
    doc = foundry.authoritative_tester_report.__doc__
    qualifiers = ("SHOULD", "should", "RAISES", "raises", "TypeError", "except")
    for para in doc.split("\n\n"):
        flat = " ".join(para.split())
        if "TOTAL" in flat or "accepted without raising" in flat:
            assert any(q in flat for q in qualifiers), (
                "unqualified totality claim still in the docstring: " + flat
            )


# ---------------------------------------------------------------------- Behavior 7
def test_b07_sibling_unchanged_on_real_directories(tmp_path):
    """Behavior 7 -- the live path is a REGRESSION pin: it builds a list internally, so
    the new guard can never fire on it."""
    two = _dir_with(tmp_path / "two", tester_md="FAIL", tester2_md="PASS")
    assert foundry.read_authoritative_tester_result(two) == "PASS"

    three = _dir_with(tmp_path / "three", tester_md="FAIL", tester2_md="FAIL",
                      tester3_md="PASS")
    assert foundry.read_authoritative_tester_result(three) == "PASS"

    one = _dir_with(tmp_path / "one", tester_md="PASS")
    assert foundry.read_authoritative_tester_result(one) == "PASS"

    only_fail = _dir_with(tmp_path / "fail", tester_md="FAIL")
    assert foundry.read_authoritative_tester_result(only_fail) == "FAIL"

    gap = _dir_with(tmp_path / "gap", tester_md="PASS", tester3_md="FAIL")
    assert foundry.read_authoritative_tester_result(gap) == "FAIL"


def test_b07b_sibling_still_answers_none_not_raises_for_the_negative_cases(tmp_path):
    """Behavior 7 -- empty dir / missing dir / unparseable newest report -> None."""
    empty = tmp_path / "empty"
    empty.mkdir(parents=True)
    (empty / "reviewer.md").write_text("VERDICT: APPROVE\n")
    assert foundry.read_authoritative_tester_result(empty) is None

    assert foundry.read_authoritative_tester_result(tmp_path / "nope" / "iter") is None

    d = _dir_with(tmp_path / "checkpoint", tester_md="PASS")
    (d / "tester2.md").write_text("cut short by the stage cap\n\nPROGRESS: CHECKPOINT\n")
    assert foundry.read_authoritative_tester_result(d) is None


def test_b07c_the_family_now_refuses_the_wrong_shape_consistently(tmp_path):
    """Behavior 7 / the spec's `Why` -- the sibling already raised on a `str`; after this
    iteration the SAFE call teaches you the same lesson as the DANGEROUS one."""
    with pytest.raises(TypeError):
        foundry.read_authoritative_tester_result(str(tmp_path))
    with pytest.raises(TypeError):
        foundry.authoritative_tester_report(str(tmp_path))


# ---------------------------------------------------------------------- Behavior 8
def test_b08_final_card_item2_carries_the_call_shape_clause():
    """Behavior 8 -- the gate agent is told the list-shaped call IN item 2."""
    text = (_ROOT / "roles" / "final.md").read_text()
    text.encode("ascii")                    # the card stays pure ASCII
    item2 = _item2(text)
    # iter 180's test_b17 brake: item 2 still names at least one helper
    assert ("authoritative_tester_report" in item2
            or "read_authoritative_tester_result" in item2), item2
    # the new clause: a LIST of names, the refusal, and the directory-shaped alternative
    assert "TypeError" in item2, item2
    assert "pathlib.Path" in item2, item2
    assert re.search(r"\[\s*['\"]tester\.md['\"]", item2), (
        "item 2 should show the list-shaped call literally: " + item2
    )


def test_b08b_the_clause_names_both_halves_of_the_family():
    """Behavior 8 -- both routes are spelled out, so neither is guessed."""
    item2 = _item2((_ROOT / "roles" / "final.md").read_text())
    assert "authoritative_tester_report" in item2, item2
    assert "read_authoritative_tester_result" in item2, item2


# ---------------------------------------------------------------------- Behavior 9
def test_b09_the_str_fixture_is_a_relative_path_literal():
    """Behavior 9 -- the public-safety regression the iter-205 revert bought.

    Iteration 205 reached its release gate with an APPROVE review, an authoritative
    tester PASS and a green suite, and its own gate reverted it fail-CLOSED because
    this fixture was an ABSOLUTE machine path -- a banned SHAPE in shipped code. The
    guard under test is purely TYPE-shaped, so no assertion in Behaviors 1-3 reads the
    string's CONTENT and a relative literal is equivalent coverage. Pinned here so the
    next iteration that edits this constant learns the constraint before its gate does.
    """
    assert os.path.isabs(STR_SHAPES[0]) is False, STR_SHAPES[0]


def test_b09b_all_three_str_shapes_of_behavior_1_still_stand():
    """Behavior 9 -- equivalence only holds if the three shapes SURVIVED the repair:
    a directory path, a single report name, and the falsy `""` that reached `None`."""
    assert len(STR_SHAPES) == 3, STR_SHAPES
    assert [type(s) for s in STR_SHAPES] == [str, str, str], STR_SHAPES
    assert STR_SHAPES[1] == "tester.md", STR_SHAPES
    assert STR_SHAPES[2] == "", STR_SHAPES
    assert "/" in STR_SHAPES[0], "the dir-path shape must still BE a path, not a name"


# ------------------------------------------------------ acceptance-criteria probes
def test_ac_both_modules_still_import():
    """Acceptance criterion: foundry and dispatcher stay importable."""
    import importlib
    assert importlib.import_module("foundry") is foundry
    assert importlib.import_module("dispatcher") is not None


def test_ac_no_other_test_passes_a_bare_scalar_as_the_first_argument():
    """Acceptance criterion (blast radius), measured rather than assumed: no OTHER test
    file under `tests/` hands `authoritative_tester_report` a quoted/bytes first argument,
    so the guard cannot have forced an existing test to change.

    Parsed in-process with `re.finditer` over the file text -- NOT via a shell grep, whose
    output compression has been measured to mangle long identifiers in this environment.
    """
    pat = re.compile(r"(?<![\w])authoritative_tester_report\(\s*([^\n)]*)")
    offenders = []
    seen = 0
    for p in sorted((_ROOT / "tests").glob("test_*.py")):
        if p.name == pathlib.Path(__file__).name:
            continue                        # this file refuses those shapes ON PURPOSE
        for m in pat.finditer(p.read_text()):
            seen += 1
            arg = m.group(1).strip()
            if arg.startswith(("'", '"', "b'", 'b"', "f'", 'f"')):
                offenders.append(f"{p.name}: {arg[:60]}")
    assert not offenders, offenders
    assert seen > 0, "the census found no call sites at all -- the pattern is wrong"
