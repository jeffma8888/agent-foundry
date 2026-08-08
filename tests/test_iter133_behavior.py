"""Black-box behaviour tests for iter 133 -- every lens the live scout rotation can
assign is now DEFINED in the scout role card, the retired fixed a/b lens mapping is
gone from the three tracked docs, and a new pure `scout_lens_audit` makes the
pool/card agreement a SUITE assertion instead of prose nobody checks.

Spec: products/_platform/state/iter-133/pm.md, Expected Behaviors 1-10.

  1.  definitions are read only from the lens section, in CARD order; an
      identically shaped bullet in a LATER section is ignored
  2.  a pool entry with no definition lands in `undocumented`, in POOL order
  3.  a definition with no pool entry lands in `orphaned`, in CARD order
  4.  `ok` is exactly the conjunction (matching pair True, each single defect
      False, both defects False, and re-derived over a table of shapes)
  5.  precision: a quoted bullet WITHOUT the ` -- ` separator is prose, not a
      definition -- with the separated twin as the positive control
  6.  total and pure: empty card, empty pool + empty card, headingless card,
      hostile inputs never raise, determinism, arguments unmutated, and purity
      proved by runtime code-object introspection rather than by the docstring
  7.  the verdict is a frozen dataclass with the four declared fields
  8.  LIVE BRAKE: the real pool is fully documented in the real card -- plus the
      two known-bad twins that prove the brake is not vacuous (a definition
      removed, and a 7th lens added to the pool)
  9.  the scout card no longer presumes a two-lens world
  10. the three tracked docs no longer assert the retired mapping, and each
      describes the lens as ROTATED by `select_scout_lenses` over the pool
  Plus Acceptance-Criteria oracles: the docstring states purity/totality/dormancy,
  the function really is DORMANT (no call site anywhere in either module, proved by
  introspection), the four new lens definitions are instruction rather than a
  restatement of their own names, the two roadmap records + retired NEXT UP item
  (f) + the roadmap size budget, and import safety in a fresh interpreter.

ISOLATION CONTRACT (HONORED): written from the iter-133 PM spec and from the
OBSERVABLE surface of the modules under test -- importing them, CALLING the public
function, reading `__doc__`, and runtime introspection of code objects -- plus the
role cards, docs and roadmap files the spec names as deliverables. The
implementation BODIES of foundry.py / dispatcher.py, the engineer's notes
(engineer.md), the reviewer's notes (reviewer.md) and `git diff` were NOT read; no
source text of either module is read by this file.

Offline and deterministic: every synthetic card is built in memory, the only reads
are of committed repo docs, nothing in the tree is mutated, and the single
subprocess is a local fresh-interpreter import probe (no network, no git, no agent
run, no sleeps).
"""
from __future__ import annotations

import dataclasses
import pathlib
import subprocess
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- Acceptance Criteria)

# ---------------------------------------------------------------------------
# Fixtures / constants
# ---------------------------------------------------------------------------

SIX_LENSES = (
    "new-capability",
    "hardening/DX",
    "integration-and-adoption",
    "simplification-and-deletion",
    "performance-and-throughput",
    "narrative-and-docs",
)
# The four that reached a live scout as a bare NAME before this iteration.
FOUR_NEW_LENSES = SIX_LENSES[2:]

# The two retired-mapping literals Behavior 10 forbids. Held here as constants
# deliberately and safely: the spec scopes the ban to three named doc files and
# explicitly never to tests/, so naming them here cannot enrol this file in the
# policed population.
RETIRED_MAPPINGS = ("(new-capability lens)", "(hardening/DX lens)")
TWO_LENS_PHRASE = "the other lens"

SCOUT_CARD = _ROOT / "roles" / "pm_scout.md"
PM_CARD = _ROOT / "roles" / "pm.md"
ARCH_DOC = _ROOT / "ARCHITECTURE.md"
DUAL_SPEC = _ROOT / "docs" / "DUAL_PM_SCOUT_SPEC.md"
ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ROADMAP_ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"

LENS_HEADING = "## Your assigned lens"
SEP = " -- "


def _definition(name: str, prose: str) -> str:
    return '- "' + name + '"' + SEP + prose


def _card(defs, *, extra_lines=(), later_section_defs=()) -> str:
    """Build a synthetic scout card: a lens section, then a LATER `## ` section."""
    lines = ["# ROLE: PM Scout (synthetic fixture)", "", LENS_HEADING, ""]
    lines.extend(_definition(n, p) for n, p in defs)
    lines.extend(extra_lines)
    if later_section_defs:
        lines.extend(["", "## Inputs", ""])
        lines.extend(_definition(n, p) for n, p in later_section_defs)
    return "\n".join(lines) + "\n"


def _audit(pool, card):
    return foundry.scout_lens_audit(pool, card)


def _lens_section(card_text: str) -> str:
    """Independent re-derivation of the lens section, for the AC prose oracle."""
    out, inside = [], False
    for line in card_text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line.strip().lower() == LENS_HEADING.lower()
            continue
        if inside:
            out.append(line)
    return "\n".join(out)


def _definition_bodies(card_text: str) -> dict:
    """name -> definition prose (first line plus its indented continuations)."""
    bodies, current = {}, None
    for line in _lens_section(card_text).splitlines():
        if line.startswith('- "') and '"' + SEP in line:
            name = line[3:].split('"', 1)[0]
            current = name
            bodies[name] = line.split('"' + SEP, 1)[1].strip()
        elif current and line.startswith("  ") and line.strip():
            bodies[current] += " " + line.strip()
        elif not line.strip():
            current = None
    return bodies


_IMPURE_NAMES = frozenset(
    {
        "open",
        "subprocess",
        "socket",
        "time",
        "sleep",
        "monotonic",
        "datetime",
        "now",
        "os",
        "environ",
        "getenv",
        "system",
        "popen",
        "pathlib",
        "Path",
        "read_text",
        "write_text",
        "glob",
        "urlopen",
        "requests",
        "urllib",
        "check_output",
        "print",
    }
)


def _all_code_names(fn) -> set:
    """Every global/attribute name referenced by `fn`, nested code included."""
    seen, stack = set(), [fn.__code__]
    while stack:
        code = stack.pop()
        seen.update(code.co_names)
        stack.extend(c for c in code.co_consts if isinstance(c, types.CodeType))
    return seen


def _module_functions(module):
    for name in dir(module):
        obj = getattr(module, name, None)
        if isinstance(obj, types.FunctionType):
            yield name, obj
        elif isinstance(obj, type):
            for attr in vars(obj).values():
                if isinstance(attr, types.FunctionType):
                    yield name + "." + attr.__name__, attr


# ---------------------------------------------------------------------------
# Behavior 1 -- definitions are read only from the lens section
# ---------------------------------------------------------------------------


def test_behavior1_definitions_come_only_from_the_lens_section_in_card_order():
    card = _card(
        [("alpha", "do alpha work"), ("beta", "do beta work")],
        later_section_defs=[("gamma", "must be ignored")],
    )
    verdict = _audit(("alpha", "beta"), card)
    assert verdict.defined == ("alpha", "beta")
    assert "gamma" not in verdict.defined, "a bullet after the next `## ` heading leaked in"


def test_behavior1_defined_order_follows_the_card_not_the_pool():
    card = _card([("alpha", "a"), ("beta", "b")])
    assert _audit(("beta", "alpha"), card).defined == ("alpha", "beta")
    reordered = _card([("beta", "b"), ("alpha", "a")])
    assert _audit(("alpha", "beta"), reordered).defined == ("beta", "alpha")


def test_behavior1_a_later_section_bullet_is_genuinely_not_a_definition():
    """Not merely absent from `defined`: the pool entry it names is UNDOCUMENTED."""
    card = _card([("alpha", "a")], later_section_defs=[("gamma", "ignored")])
    verdict = _audit(("alpha", "gamma"), card)
    assert verdict.undocumented == ("gamma",)
    assert verdict.ok is False


def test_behavior1_scanning_stops_at_the_next_two_hash_heading_only():
    """A deeper `### ` sub-heading does not end the lens section."""
    card = (
        LENS_HEADING
        + "\n"
        + _definition("alpha", "a")
        + "\n### a sub-heading inside the section\n"
        + _definition("beta", "b")
        + "\n"
    )
    assert _audit(("alpha", "beta"), card).defined == ("alpha", "beta")


# ---------------------------------------------------------------------------
# Behavior 2 -- undocumented, in POOL order
# ---------------------------------------------------------------------------


def test_behavior2_pool_entry_without_a_definition_is_undocumented_in_pool_order():
    card = _card([("beta", "b")])
    verdict = _audit(("zulu", "alpha", "beta", "yankee"), card)
    assert verdict.undocumented == ("zulu", "alpha", "yankee")
    assert verdict.ok is False


def test_behavior2_undocumented_is_pool_order_not_sorted_order():
    card = _card([("beta", "b")])
    verdict = _audit(("yankee", "alpha", "zulu", "beta"), card)
    assert verdict.undocumented == ("yankee", "alpha", "zulu")
    assert verdict.undocumented != tuple(sorted(verdict.undocumented))


# ---------------------------------------------------------------------------
# Behavior 3 -- orphaned, in CARD order
# ---------------------------------------------------------------------------


def test_behavior3_definition_without_a_pool_entry_is_orphaned_in_card_order():
    card = _card([("zulu", "z"), ("alpha", "a"), ("aardvark", "aa")])
    verdict = _audit(("alpha",), card)
    assert verdict.orphaned == ("zulu", "aardvark")
    assert verdict.undocumented == ()
    assert verdict.ok is False
    assert verdict.orphaned != tuple(sorted(verdict.orphaned))


# ---------------------------------------------------------------------------
# Behavior 4 -- ok is exactly the conjunction
# ---------------------------------------------------------------------------


def test_behavior4_ok_is_exactly_the_conjunction_of_the_two_defect_lists():
    card = _card([("alpha", "a"), ("beta", "b")])
    matching = _audit(("alpha", "beta"), card)
    assert (matching.undocumented, matching.orphaned) == ((), ())
    assert matching.ok is True

    only_undocumented = _audit(("alpha", "beta", "gamma"), card)
    assert only_undocumented.undocumented == ("gamma",)
    assert only_undocumented.orphaned == ()
    assert only_undocumented.ok is False

    only_orphaned = _audit(("alpha",), card)
    assert only_orphaned.undocumented == ()
    assert only_orphaned.orphaned == ("beta",)
    assert only_orphaned.ok is False

    both = _audit(("gamma",), card)
    assert both.undocumented and both.orphaned
    assert both.ok is False


def test_behavior4_conjunction_holds_over_a_table_of_shapes():
    shapes = [
        ((), ""),
        (("alpha",), ""),
        ((), _card([("alpha", "a")])),
        (("alpha",), _card([("alpha", "a")])),
        (("alpha", "beta"), _card([("beta", "b"), ("gamma", "g")])),
        (("alpha",), _card([("alpha", "a")], later_section_defs=[("alpha", "dup")])),
        (("alpha",), "no lens heading at all\n"),
    ]
    for pool, card in shapes:
        verdict = _audit(pool, card)
        expected = not verdict.undocumented and not verdict.orphaned
        assert verdict.ok is expected, f"ok disagreed with its own lists for {pool!r}"
        assert isinstance(verdict.ok, bool)


# ---------------------------------------------------------------------------
# Behavior 5 -- precision: a quoted bullet that is not a definition
# ---------------------------------------------------------------------------


def test_behavior5_quoted_bullet_without_the_separator_is_prose_not_a_definition():
    name = "hardening/DX"
    non_definitions = [
        '- "' + name + '" is one of the six lenses',
        '- "' + name + '"-- glued to the closing quote',
        '- "' + name + '": a colon instead of the separator',
        '- "' + name + '" --no space after the dashes',
        'prose mentioning "' + name + '" -- outside a bullet entirely',
        'x - "' + name + '" -- a bullet dash that does not open the line',
    ]
    for line in non_definitions:
        card = LENS_HEADING + "\n\n" + line + "\n"
        verdict = _audit((name,), card)
        assert verdict.defined == (), f"prose silently documented a lens: {line!r}"
        assert verdict.undocumented == (name,)
        assert verdict.ok is False


def test_behavior5_indentation_is_not_part_of_the_rule_documented_ambiguity():
    """AMBIGUITY, tested at its most reasonable reading and reported as PM feedback.

    Behavior 5 scopes precision to the ` -- ` SEPARATOR and says nothing about
    indentation, and Behavior 1's form (`- "NAME" -- prose`) does not forbid leading
    whitespace. The observed rule is indentation-insensitive: an indented bullet
    inside the lens section IS a definition. That is the lenient reading and it is
    harmless for the live card (whose continuation lines are indented PROSE, not
    bullets), but it means a future card could document a lens from a nested
    sub-bullet. Pinned here so the choice is deliberate rather than incidental.
    """
    name = "hardening/DX"
    card = LENS_HEADING + "\n\n  " + _definition(name, "indented but still a definition") + "\n"
    verdict = _audit((name,), card)
    assert verdict.defined == (name,)
    assert verdict.ok is True


def test_behavior5_positive_control_the_separated_twin_is_a_definition():
    """The known-good half: precision above is not just 'nothing ever matches'."""
    name = "hardening/DX"
    card = LENS_HEADING + "\n\n" + _definition(name, "harden what exists") + "\n"
    verdict = _audit((name,), card)
    assert verdict.defined == (name,)
    assert verdict.undocumented == ()
    assert verdict.ok is True


def test_behavior5_an_empty_quoted_name_is_not_a_definition():
    card = LENS_HEADING + "\n\n" + '- ""' + SEP + "empty name\n"
    verdict = _audit(("alpha",), card)
    assert verdict.defined == ()
    assert verdict.orphaned == ()
    assert verdict.undocumented == ("alpha",)


# ---------------------------------------------------------------------------
# Behavior 6 -- total and pure
# ---------------------------------------------------------------------------


def test_behavior6_empty_card_reports_every_pool_entry():
    pool = ("alpha", "beta")
    verdict = _audit(pool, "")
    assert verdict.defined == ()
    assert verdict.undocumented == pool
    assert verdict.orphaned == ()
    assert verdict.ok is False


def test_behavior6_empty_pool_and_empty_card_is_ok():
    verdict = _audit((), "")
    assert (verdict.defined, verdict.undocumented, verdict.orphaned) == ((), (), ())
    assert verdict.ok is True


def test_behavior6_card_with_no_lens_heading_defines_nothing_and_does_not_raise():
    card = _definition("alpha", "a") + "\n\n## Inputs\n\n" + _definition("beta", "b") + "\n"
    verdict = _audit(("alpha", "beta"), card)
    assert verdict.defined == ()
    assert verdict.undocumented == ("alpha", "beta")
    assert verdict.ok is False


def test_behavior6_never_raises_on_hostile_input():
    pool = ("alpha", "beta")
    hostile = [
        "",
        "\n",
        LENS_HEADING,
        LENS_HEADING + "\n",
        "## \n- \"alpha\"" + SEP + "a\n",
        LENS_HEADING + "\r\n- \"alpha\"" + SEP + "a\r\n",
        LENS_HEADING + "\n- \"alpha\"" + SEP,
        LENS_HEADING + "\n- \"al\"pha\"" + SEP + "nested quote\n",
        LENS_HEADING + "\n\x00 null byte\n",
        LENS_HEADING + "\n- \"\u00e9\u00e8\"" + SEP + "unicode name\n",
        LENS_HEADING + "\n" + ("x" * 20000) + "\n",
        "#" * 200,
    ]
    for text in hostile:
        verdict = _audit(pool, text)
        assert isinstance(verdict, foundry.LensDocAudit)
        assert isinstance(verdict.defined, tuple)


def test_behavior6_deterministic_and_does_not_mutate_its_arguments():
    pool = ["alpha", "beta", "gamma"]
    snapshot = list(pool)
    card = _card([("alpha", "a"), ("beta", "b")])
    first = _audit(pool, card)
    second = _audit(pool, card)
    assert first == second
    assert pool == snapshot, "the pool argument was mutated"
    assert _audit(tuple(pool), card) == first, "a tuple pool differs from a list pool"


def test_behavior6_purity_proved_by_runtime_code_introspection():
    """A real oracle for the docstring's purity claim -- not a re-read of the prose.

    Walks the compiled code object (and any nested code objects) and asserts the
    referenced-name set never touches the filesystem, subprocess, network or clock
    surfaces. Cannot be defeated by an indirect call the way a source grep can.
    """
    names = _all_code_names(foundry.scout_lens_audit)
    leaks = sorted(names & _IMPURE_NAMES)
    assert not leaks, f"scout_lens_audit references impure names: {leaks}"


# ---------------------------------------------------------------------------
# Behavior 7 -- the verdict is frozen
# ---------------------------------------------------------------------------


def test_behavior7_verdict_is_a_frozen_dataclass_with_the_declared_fields():
    verdict = _audit(("alpha",), _card([("alpha", "a")]))
    assert dataclasses.is_dataclass(verdict)
    assert type(verdict).__dataclass_params__.frozen is True
    assert tuple(f.name for f in dataclasses.fields(verdict)) == (
        "defined",
        "undocumented",
        "orphaned",
        "ok",
    )
    for field in ("defined", "undocumented", "orphaned"):
        assert isinstance(getattr(verdict, field), tuple)
    assert isinstance(verdict.ok, bool)


def test_behavior7_assigning_to_any_field_raises_frozen_instance_error():
    verdict = _audit(("alpha",), _card([("alpha", "a")]))
    for field in ("defined", "undocumented", "orphaned", "ok"):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(verdict, field, ())


# ---------------------------------------------------------------------------
# Behavior 8 -- LIVE BRAKE
# ---------------------------------------------------------------------------


def test_behavior8_live_pool_is_fully_documented_in_the_live_scout_card():
    card = SCOUT_CARD.read_text(encoding="utf-8")
    verdict = _audit(foundry.PM_SCOUT_LENS_POOL, card)
    assert verdict.undocumented == (), (
        "lenses the live rotation can assign but the scout card does not define: "
        f"{verdict.undocumented}"
    )
    assert verdict.orphaned == (), (
        f"lenses defined in the scout card but absent from the pool: {verdict.orphaned}"
    )
    assert verdict.ok is True
    for lens in SIX_LENSES:
        assert lens in verdict.defined, f"lens not defined in the scout card: {lens}"


def test_behavior8_complements_the_exact_six_tuple_assertion_on_the_pool():
    assert tuple(foundry.PM_SCOUT_LENS_POOL) == SIX_LENSES


def test_behavior8_the_brake_fires_when_a_live_definition_is_removed():
    """Known-bad twin #1: without this, the live assertion could be vacuous."""
    card = SCOUT_CARD.read_text(encoding="utf-8")
    target = "narrative-and-docs"
    mutated = "\n".join(
        line for line in card.splitlines() if not line.startswith('- "' + target + '"')
    )
    assert mutated != card, "fixture did not actually remove a definition line"
    verdict = _audit(foundry.PM_SCOUT_LENS_POOL, mutated)
    assert target in verdict.undocumented
    assert verdict.ok is False


def test_behavior8_the_brake_fires_on_an_undocumented_seventh_lens():
    """Known-bad twin #2: the exact scenario the brake exists to make impossible."""
    card = SCOUT_CARD.read_text(encoding="utf-8")
    seventh = "an-undocumented-seventh-lens"
    verdict = _audit(tuple(foundry.PM_SCOUT_LENS_POOL) + (seventh,), card)
    assert verdict.undocumented == (seventh,)
    assert verdict.orphaned == ()
    assert verdict.ok is False


# ---------------------------------------------------------------------------
# Behavior 9 -- the scout card no longer presumes two lenses
# ---------------------------------------------------------------------------


def test_behavior9_scout_card_does_not_contain_the_two_lens_phrase():
    card = SCOUT_CARD.read_text(encoding="utf-8")
    # matcher proven on a known-positive string first: a negative result is not
    # evidence of absence until the matcher has fired on something.
    assert TWO_LENS_PHRASE in "do not propose candidates from " + TWO_LENS_PHRASE
    assert TWO_LENS_PHRASE not in card, "the scout card still presumes a two-lens world"


def test_behavior9_stay_in_lens_instruction_is_phrased_against_the_assigned_lens():
    low = SCOUT_CARD.read_text(encoding="utf-8").lower()
    assert "stay inside" in low
    assert "assigned" in low
    assert "rotat" in low, "the card does not tell the scout the lens rotates"


# ---------------------------------------------------------------------------
# Behavior 10 -- the three tracked docs
# ---------------------------------------------------------------------------


def test_behavior10_three_tracked_docs_no_longer_assert_the_retired_mapping():
    planted = "scout A " + RETIRED_MAPPINGS[0] + ", scout B " + RETIRED_MAPPINGS[1]
    for literal in RETIRED_MAPPINGS:
        assert literal in planted, "the forbidden-literal matcher is inert"
    for path in (PM_CARD, ARCH_DOC, DUAL_SPEC):
        text = path.read_text(encoding="utf-8")
        for literal in RETIRED_MAPPINGS:
            assert literal not in text, f"{path.name} still asserts {literal}"


def test_behavior10_three_tracked_docs_describe_the_rotation_instead():
    for path in (PM_CARD, ARCH_DOC, DUAL_SPEC):
        text = path.read_text(encoding="utf-8")
        assert "select_scout_lenses" in text, f"{path.name} does not name the rotation"
        assert "PM_SCOUT_LENS_POOL" in text, f"{path.name} does not name the pool"
        assert "rotat" in text.lower(), f"{path.name} does not say the lens rotates"


def test_behavior10_pm_card_keeps_its_own_two_slate_phrase():
    """Scope check: Behavior 9's ban is the SCOUT card only.

    `roles/pm.md`'s diversity guard talks about the two SLATES the PM triages, which
    is correct and must survive an over-broad application of Behavior 9.
    """
    assert TWO_LENS_PHRASE in PM_CARD.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Acceptance-Criteria oracles
# ---------------------------------------------------------------------------


def test_ac_docstring_states_purity_totality_and_dormancy():
    doc = (foundry.scout_lens_audit.__doc__ or "").lower()
    assert doc.strip(), "scout_lens_audit has no docstring"
    for claim in ("pure", "total", "dormant"):
        assert claim in doc, f"docstring does not state the {claim} claim"
    assert "zero call site" in doc or "no call site" in doc


def test_ac_function_is_dormant_no_call_site_in_either_module():
    """Additive-dormant, so an in-flight loop's resume semantics are unchanged."""
    target = "scout_lens_audit"
    callers = []
    for module in (foundry, dispatcher):
        for name, fn in _module_functions(module):
            if name.split(".")[0] == target:
                continue
            if target in _all_code_names(fn):
                callers.append(module.__name__ + "." + name)
    assert not callers, f"{target} is no longer dormant; referenced by {callers}"


def test_ac_four_new_lens_definitions_are_instruction_not_a_restatement():
    bodies = _definition_bodies(SCOUT_CARD.read_text(encoding="utf-8"))
    assert set(SIX_LENSES) <= set(bodies), f"missing definitions: {set(SIX_LENSES) - set(bodies)}"
    for lens in FOUR_NEW_LENSES:
        body = bodies[lens]
        assert len(body) >= 120, f"{lens} definition is too thin to generate from: {body!r}"
        assert len(body.split()) >= 20, f"{lens} definition is not instruction: {body!r}"
        # not merely the name's own words echoed back
        name_words = {w for w in lens.replace("/", "-").split("-") if len(w) > 3}
        residual = [w for w in body.lower().split() if w.strip(".,;:`\"'") not in name_words]
        assert len(residual) >= 15, f"{lens} definition restates its own name: {body!r}"


def test_ac_roadmap_records_land_with_this_iteration():
    roadmap = ROADMAP.read_text(encoding="utf-8")
    ledger = [ln for ln in roadmap.splitlines() if ln.startswith("- iter 133 ")]
    assert len(ledger) == 1, f"expected exactly one iter-133 Done ledger row, got {len(ledger)}"
    assert len(ledger[0]) <= 120, f"ledger row is {len(ledger[0])} chars (max 120)"

    archive = ROADMAP_ARCHIVE.read_text(encoding="utf-8")
    bullets = [ln for ln in archive.splitlines() if ln.startswith("- **iter 133 ")]
    assert len(bullets) == 1, f"expected exactly one iter-133 archive bullet, got {len(bullets)}"
    assert len(bullets[0]) > len(ledger[0]), "the archive bullet should carry the detail"


def test_ac_next_up_item_f_is_retired():
    roadmap = ROADMAP.read_text(encoding="utf-8")
    assert "(f) SHIPPED iter 133" in roadmap, "NEXT UP item (f) was not retired"


def test_ac_roadmap_index_still_inside_its_size_budget():
    budget = getattr(foundry, "ROADMAP_SIZE_WARN_CHARS", 60000)
    size = len(ROADMAP.read_text(encoding="utf-8"))
    assert size < budget, f"roadmap index is {size} chars, budget {budget}"


def test_ac_both_modules_import_in_a_fresh_interpreter():
    result = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher; print('ok')"],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "ok" in result.stdout


def test_ac_public_surface_exists_with_the_decided_signature():
    import inspect

    params = list(inspect.signature(foundry.scout_lens_audit).parameters)
    assert params == ["pool", "card_text"], f"unexpected signature: {params}"
