"""Black-box behaviour tests for iter 139 -- the two GATE role cards (roles/final.md and
roles/tester.md) each carry a verify-first EXCEPTION inside their WRITE-EARLY section, and a
new pure `write_early_card_audit` plus a LIVE suite brake make that rule impossible to drop
silently.

Spec: products/_platform/state/iter-139/pm.md, Expected Behaviors 1-9.

  1. roles/final.md holds the two generic WRITE-EARLY anchors AND the exception anchor; its
     added text says the ACTION line is written ONCE, only when the decision is real, never
     as a placeholder, and names PUSHED / REVERTED as the only recognised tokens. Pure ASCII.
  2. roles/tester.md holds the same three substrings, and states BOTH hazards: a cut-short
     report must carry PROGRESS: CHECKPOINT verbatim (an unmarked RESULT: FAIL reads as a
     genuinely red suite), and a checkpointed claim must be measured, not predicted. Pure ASCII.
  3. the other six cards keep BOTH generic anchors and contain the exception anchor NOWHERE;
     the non-recursive roles/*.md glob is still exactly the 8 known cards.
  4. four module-level constants exist with the declared values, and the audit reads all four
     as module globals INSIDE its body (proved by monkeypatching each one and watching the
     verdict move).
  5. write_early_card_audit(cards) returns a frozen 4-field record; every case in the spec's
     case list is driven, including the sentinel/non-sentinel asymmetry, the absent-card case,
     the empty mapping, sorted-by-name ordering, and ok-iff-all-tuples-empty over a table.
  6. pure and total: no I/O names in the code object, argument unmutated, deterministic,
     non-str values treated as EMPTY text rather than raising, record frozen.
  7. LIVE BRAKE: the 8 real cards read off disk audit clean -- plus two known-bad twins that
     prove the brake is not vacuous (a gate card's exception removed, a card deleted).
  8. DORMANT: no other module-level foundry function names it, dispatcher has no such
     attribute, and a fresh subprocess `import foundry, dispatcher` exits 0.
  9. this test file is pure ASCII.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-139 PM spec's Expected Behaviors,
the tests/ conventions (the disk-read role-card assertions of test_iter112_behavior.py and
the audit-function shape of test_iter133_behavior.py), and the OBSERVABLE surface of the
product -- role cards read off disk, importing the modules, CALLING the public function, and
runtime introspection of code objects / dataclass fields. The implementation SOURCE text of
foundry.py and dispatcher.py, the engineer's notes (engineer.md), the reviewer's notes
(reviewer.md) and `git diff` were NOT read.

Offline and deterministic: synthetic cards are built in memory, the only reads are committed
repo files, nothing in the tree is mutated, and the single subprocess is a local
fresh-interpreter import probe (no git, no network, no agent run, no sleeps).
"""
from __future__ import annotations

import dataclasses
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (dormancy probe -- Behavior 8)

ROLES_DIR = _ROOT / "roles"

# The anchor strings, held as literals so the test pins the CONTRACT rather than
# echoing whatever the module happens to define (Behavior 4 compares the two).
MARKER = "WRITE-EARLY (checkpoint-first)"
MECHANISM = "write a complete-but-minimal version"
EXCEPTION_ANCHOR = "EXCEPTION for this card"

SENTINEL_CARDS = ("final.md", "tester.md")

KNOWN_CARDS = (
    "engineer.md",
    "final.md",
    "fix.md",
    "pm.md",
    "pm_scout.md",
    "reporter.md",
    "reviewer.md",
    "tester.md",
)
NON_SENTINEL_CARDS = tuple(n for n in KNOWN_CARDS if n not in SENTINEL_CARDS)

# A card text carrying every required substring.
CLEAN_GATE_TEXT = "\n".join(
    ["## " + MARKER, "So " + MECHANISM + " of your output file.", "**" + EXCEPTION_ANCHOR + " -- verify first.**"]
)
CLEAN_PLAIN_TEXT = "\n".join(["## " + MARKER, "So " + MECHANISM + " of your output file."])


def _top_level_cards():
    """Non-recursive roles/*.md glob, so any roles/<subdir>/ is excluded."""
    return sorted(ROLES_DIR.glob("*.md"))


def _card_text(name: str) -> str:
    return (ROLES_DIR / name).read_text()


def _write_early_section(name: str) -> str:
    """The card text from the WRITE-EARLY heading up to the NEXT top-level heading.

    Black-box slice of the shipped artifact: it proves the exception lives INSIDE the
    WRITE-EARLY section rather than anywhere in the file.
    """
    text = _card_text(name)
    start = text.index(MARKER)
    rest = text[start:]
    nxt = rest.find("\n## ")
    return rest if nxt == -1 else rest[:nxt]


def _non_ascii(data: bytes):
    return [(i, b) for i, b in enumerate(data) if b > 127]


# ==========================================================================
# Behavior 1 -- roles/final.md carries its exception
# ==========================================================================
@pytest.mark.parametrize("needle", [MARKER, MECHANISM, EXCEPTION_ANCHOR])
def test_b01_final_card_holds_all_three_substrings(needle):
    assert needle in _card_text("final.md")


def test_b01_final_exception_lives_inside_the_write_early_section():
    assert EXCEPTION_ANCHOR in _write_early_section("final.md")


def test_b01_final_exception_names_only_recognised_tokens():
    section = _write_early_section("final.md")
    assert "PUSHED" in section
    assert "REVERTED" in section


def test_b01_final_exception_says_written_once_and_never_a_placeholder():
    section = _write_early_section("final.md")
    lowered = section.lower()
    assert "once" in lowered
    assert "placeholder" in lowered


def test_b01_final_card_is_pure_ascii():
    assert _non_ascii((ROLES_DIR / "final.md").read_bytes()) == []


# ==========================================================================
# Behavior 2 -- roles/tester.md carries its exception
# ==========================================================================
@pytest.mark.parametrize("needle", [MARKER, MECHANISM, EXCEPTION_ANCHOR])
def test_b02_tester_card_holds_all_three_substrings(needle):
    assert needle in _card_text("tester.md")


def test_b02_tester_exception_lives_inside_the_write_early_section():
    assert EXCEPTION_ANCHOR in _write_early_section("tester.md")


def test_b02_tester_exception_states_the_marker_hazard():
    section = _write_early_section("tester.md")
    assert "PROGRESS: CHECKPOINT" in section
    assert "RESULT: FAIL" in section


def test_b02_tester_exception_states_the_measured_vs_predicted_hazard():
    lowered = _write_early_section("tester.md").lower()
    assert "measured" in lowered
    assert "predicted" in lowered


def test_b02_tester_card_is_pure_ascii():
    assert _non_ascii((ROLES_DIR / "tester.md").read_bytes()) == []


# ==========================================================================
# Behavior 3 -- the other six cards are untouched in shape
# ==========================================================================
@pytest.mark.parametrize("name", NON_SENTINEL_CARDS)
def test_b03_non_gate_card_keeps_both_generic_anchors(name):
    text = _card_text(name)
    assert MARKER in text
    assert MECHANISM in text


@pytest.mark.parametrize("name", NON_SENTINEL_CARDS)
def test_b03_non_gate_card_has_no_exception_anchor(name):
    assert EXCEPTION_ANCHOR not in _card_text(name)


def test_b03_roles_glob_is_exactly_the_eight_known_cards():
    assert tuple(p.name for p in _top_level_cards()) == KNOWN_CARDS


def test_b03_exception_anchor_appears_in_exactly_two_cards():
    hits = [p.name for p in _top_level_cards() if EXCEPTION_ANCHOR in p.read_text()]
    assert tuple(hits) == SENTINEL_CARDS


# ==========================================================================
# Behavior 4 -- the four constants, read at call time
# ==========================================================================
def test_b04_constant_values():
    assert foundry.WRITE_EARLY_MARKER == MARKER
    assert foundry.WRITE_EARLY_MECHANISM == MECHANISM
    assert foundry.WRITE_EARLY_EXCEPTION_ANCHOR == EXCEPTION_ANCHOR
    assert foundry.SENTINEL_VERDICT_CARDS == SENTINEL_CARDS


def test_b04_sentinel_cards_is_an_immutable_tuple_of_str():
    value = foundry.SENTINEL_VERDICT_CARDS
    assert isinstance(value, tuple)
    assert all(isinstance(v, str) for v in value)


def test_b04_marker_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "WRITE_EARLY_MARKER", "ZZ-PATCHED-MARKER")
    patched_ok = foundry.write_early_card_audit({"pm.md": "ZZ-PATCHED-MARKER " + MECHANISM})
    assert patched_ok.missing_marker == ()
    old_now_bad = foundry.write_early_card_audit({"pm.md": MARKER + " " + MECHANISM})
    assert old_now_bad.missing_marker == ("pm.md",)
    assert old_now_bad.ok is False


def test_b04_mechanism_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "WRITE_EARLY_MECHANISM", "ZZ-PATCHED-MECHANISM")
    assert foundry.write_early_card_audit({"pm.md": MARKER + " ZZ-PATCHED-MECHANISM"}).ok is True
    assert foundry.write_early_card_audit({"pm.md": CLEAN_PLAIN_TEXT}).missing_mechanism == ("pm.md",)


def test_b04_exception_anchor_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "WRITE_EARLY_EXCEPTION_ANCHOR", "ZZ-PATCHED-EXCEPTION")
    assert foundry.write_early_card_audit({"final.md": CLEAN_GATE_TEXT}).missing_exception == ("final.md",)
    patched = foundry.write_early_card_audit({"final.md": CLEAN_PLAIN_TEXT + " ZZ-PATCHED-EXCEPTION"})
    assert patched.missing_exception == ()
    assert patched.ok is True


def test_b04_sentinel_card_names_are_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "SENTINEL_VERDICT_CARDS", ("pm.md",))
    now_sentinel = foundry.write_early_card_audit({"pm.md": CLEAN_PLAIN_TEXT})
    assert now_sentinel.missing_exception == ("pm.md",)
    assert now_sentinel.ok is False
    no_longer_sentinel = foundry.write_early_card_audit({"final.md": CLEAN_PLAIN_TEXT})
    assert no_longer_sentinel.missing_exception == ()
    assert no_longer_sentinel.ok is True


# ==========================================================================
# Behavior 5 -- the frozen 4-field record and every declared case
# ==========================================================================
def test_b05_record_has_exactly_the_four_declared_fields():
    record = foundry.write_early_card_audit({})
    assert [f.name for f in dataclasses.fields(record)] == [
        "missing_marker",
        "missing_mechanism",
        "missing_exception",
        "ok",
    ]


def test_b05_ok_is_a_stored_field_not_a_property():
    record = foundry.write_early_card_audit({})
    assert "ok" in {f.name for f in dataclasses.fields(record)}
    assert not isinstance(getattr(type(record), "ok", None), property)
    assert isinstance(record.ok, bool)


def test_b05_field_runtime_types():
    record = foundry.write_early_card_audit({"final.md": CLEAN_PLAIN_TEXT, "pm.md": ""})
    for name in ("missing_marker", "missing_mechanism", "missing_exception"):
        value = getattr(record, name)
        assert isinstance(value, tuple)
        assert all(isinstance(v, str) for v in value)


def test_b05_all_good_mapping_is_clean():
    cards = {"final.md": CLEAN_GATE_TEXT, "tester.md": CLEAN_GATE_TEXT, "pm.md": CLEAN_PLAIN_TEXT}
    record = foundry.write_early_card_audit(cards)
    assert record.missing_marker == ()
    assert record.missing_mechanism == ()
    assert record.missing_exception == ()
    assert record.ok is True


def test_b05_missing_marker_is_reported():
    record = foundry.write_early_card_audit({"pm.md": "So " + MECHANISM + " of it."})
    assert record.missing_marker == ("pm.md",)
    assert record.ok is False


def test_b05_missing_mechanism_is_reported():
    record = foundry.write_early_card_audit({"pm.md": "## " + MARKER})
    assert record.missing_mechanism == ("pm.md",)
    assert record.ok is False


def test_b05_sentinel_card_missing_the_exception_is_reported():
    for name in SENTINEL_CARDS:
        record = foundry.write_early_card_audit({name: CLEAN_PLAIN_TEXT})
        assert record.missing_exception == (name,)
        assert record.ok is False


def test_b05_non_sentinel_card_missing_the_exception_is_reported_nowhere():
    record = foundry.write_early_card_audit({"pm.md": CLEAN_PLAIN_TEXT})
    assert record.missing_exception == ()
    assert record.missing_marker == ()
    assert record.missing_mechanism == ()
    assert record.ok is True


def test_b05_absent_sentinel_card_is_reported_nowhere():
    record = foundry.write_early_card_audit({"pm.md": CLEAN_PLAIN_TEXT})
    assert "final.md" not in record.missing_exception
    assert "tester.md" not in record.missing_exception
    assert record.ok is True


def test_b05_empty_mapping_is_ok():
    record = foundry.write_early_card_audit({})
    assert (record.missing_marker, record.missing_mechanism, record.missing_exception) == ((), (), ())
    assert record.ok is True


def test_b05_tuples_are_sorted_by_card_name():
    cards = {"zz.md": "", "mm.md": "", "aa.md": ""}
    record = foundry.write_early_card_audit(cards)
    assert record.missing_marker == ("aa.md", "mm.md", "zz.md")
    assert record.missing_mechanism == ("aa.md", "mm.md", "zz.md")


def test_b05_sentinel_exception_tuple_is_sorted_by_card_name():
    record = foundry.write_early_card_audit({"tester.md": CLEAN_PLAIN_TEXT, "final.md": CLEAN_PLAIN_TEXT})
    assert record.missing_exception == ("final.md", "tester.md")


@pytest.mark.parametrize(
    "cards",
    [
        {},
        {"pm.md": CLEAN_PLAIN_TEXT},
        {"pm.md": ""},
        {"final.md": CLEAN_GATE_TEXT},
        {"final.md": CLEAN_PLAIN_TEXT},
        {"final.md": "## " + MARKER},
        {"tester.md": "So " + MECHANISM},
        {"final.md": CLEAN_GATE_TEXT, "tester.md": CLEAN_PLAIN_TEXT},
        {"final.md": CLEAN_GATE_TEXT, "tester.md": CLEAN_GATE_TEXT, "pm.md": CLEAN_PLAIN_TEXT},
        {"a.md": "", "b.md": CLEAN_PLAIN_TEXT},
    ],
)
def test_b05_ok_is_exactly_the_conjunction(cards):
    record = foundry.write_early_card_audit(cards)
    expected = not (record.missing_marker or record.missing_mechanism or record.missing_exception)
    assert record.ok is expected


# ==========================================================================
# Behavior 6 -- pure and total
# ==========================================================================
FORBIDDEN_EFFECT_NAMES = (
    "open",
    "read_text",
    "write_text",
    "Path",
    "subprocess",
    "run",
    "check_output",
    "popen",
    "system",
    "time",
    "sleep",
    "datetime",
    "now",
    "urlopen",
    "requests",
    "glob",
    "environ",
    "getenv",
)


def test_b06_code_object_names_no_io_or_clock():
    names = set(foundry.write_early_card_audit.__code__.co_names)
    assert names.isdisjoint(FORBIDDEN_EFFECT_NAMES), sorted(names & set(FORBIDDEN_EFFECT_NAMES))


def test_b06_argument_is_not_mutated():
    cards = {"final.md": CLEAN_GATE_TEXT, "pm.md": ""}
    before = dict(cards)
    foundry.write_early_card_audit(cards)
    assert cards == before


def test_b06_is_deterministic_for_equal_arguments():
    cards = {"final.md": CLEAN_PLAIN_TEXT, "pm.md": ""}
    assert foundry.write_early_card_audit(cards) == foundry.write_early_card_audit(dict(cards))


@pytest.mark.parametrize("value", [None, 42, b"bytes", [], {}, 3.5, True])
def test_b06_non_str_value_is_treated_as_empty_text(value):
    record = foundry.write_early_card_audit({"final.md": value})
    assert record.missing_marker == ("final.md",)
    assert record.missing_mechanism == ("final.md",)
    assert record.missing_exception == ("final.md",)
    assert record.ok is False


def test_b06_non_str_value_on_a_non_sentinel_card_does_not_raise():
    record = foundry.write_early_card_audit({"pm.md": None})
    assert record.missing_marker == ("pm.md",)
    assert record.missing_exception == ()
    assert record.ok is False


@pytest.mark.parametrize("field", ["missing_marker", "missing_mechanism", "missing_exception", "ok"])
def test_b06_record_is_frozen(field):
    record = foundry.write_early_card_audit({})
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(record, field, ())


# ==========================================================================
# Behavior 7 -- LIVE BRAKE (the consumer)
# ==========================================================================
def _live_mapping():
    return {p.name: p.read_text() for p in _top_level_cards()}


def test_b07_live_cards_audit_clean():
    record = foundry.write_early_card_audit(_live_mapping())
    assert record.missing_marker == ()
    assert record.missing_mechanism == ()
    assert record.missing_exception == ()
    assert record.ok is True


def test_b07_live_mapping_key_set_equals_the_known_cards():
    assert set(_live_mapping()) == set(KNOWN_CARDS)


@pytest.mark.parametrize("name", SENTINEL_CARDS)
def test_b07_brake_is_not_vacuous_when_a_gate_card_loses_its_exception(name):
    """Known-bad twin: strip the exception anchor from ONE gate card in memory only."""
    cards = _live_mapping()
    cards[name] = cards[name].replace(EXCEPTION_ANCHOR, "some other heading")
    record = foundry.write_early_card_audit(cards)
    assert record.missing_exception == (name,)
    assert record.ok is False


def test_b07_brake_is_not_vacuous_when_a_generic_anchor_is_reworded():
    cards = _live_mapping()
    cards["engineer.md"] = cards["engineer.md"].replace(MECHANISM, "write something eventually")
    record = foundry.write_early_card_audit(cards)
    assert record.missing_mechanism == ("engineer.md",)
    assert record.ok is False


def test_b07_deleting_a_card_changes_the_key_set():
    cards = _live_mapping()
    cards.pop("fix.md")
    assert set(cards) != set(KNOWN_CARDS)


# ==========================================================================
# Behavior 8 -- DORMANT, so resume semantics are unchanged
# ==========================================================================
def test_b08_no_other_foundry_function_names_the_audit():
    target = "write_early_card_audit"
    callers = []
    for name, obj in vars(foundry).items():
        code = getattr(obj, "__code__", None)
        if code is None or name == target:
            continue
        if getattr(obj, "__module__", None) != "foundry":
            continue
        if target in code.co_names:
            callers.append(name)
    assert callers == []


def test_b08_dispatcher_has_no_such_attribute():
    assert not hasattr(dispatcher, "write_early_card_audit")


def test_b08_fresh_subprocess_import_exits_zero():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr


# ==========================================================================
# Behavior 9 -- this test file is pure ASCII
# ==========================================================================
def test_b09_this_test_file_is_pure_ascii():
    assert _non_ascii(pathlib.Path(__file__).read_bytes()) == []
