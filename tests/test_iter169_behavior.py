"""Black-box behaviour tests for iter 169 -- the README "# N." command index becomes a DERIVED
contract: a pure `readme_verb_index_gaps(readme_text, verbs)` audit plus a two-sided live brake,
and the two entries the index was missing (`new-product`, `preship`).

Spec: products/_platform/state/iter-169/pm.md, Expected Behaviors 1-10.

  1. `readme_verb_index_gaps` -> frozen `ReadmeVerbIndexAudit` with exactly
     missing_verbs / sections_without_invocation / unknown_invocations / sections_scanned / ok,
     `ok` true IFF the first three tuples are all empty (each proven to flip it on its own).
  2. A section is a line matching ^#\\s+\\d+\\. ; its body runs to the next such line or EOF;
     `sections_scanned` counts those lines ("## 2." and "#3." are NOT sections).
  3. COVERED iff some section BODY contains `foundry.py <verb>` whitespace-separated -- proven
     two-sided (line present -> not missing; same text with the line deleted -> missing) plus the
     near-miss cases (`foundry.py statusx`, `dispatcher.py status`, preamble-only invocation).
  4. DERIVED EXEMPTION, never an allowlist: a verb-less section is reported UNLESS its body
     contains `dispatcher.py`; document order preserved for several.
  5. `unknown_invocations` = every `foundry.py <name>` whose name is not in `verbs`, sorted.
  6. Totality: non-str/empty readme -> sections_scanned 0 and every supplied verb missing;
     non-iterable `verbs` -> treated as EMPTY; non-str members ignored; nothing ever raises.
  7. `render()` names every finding category with its members, is a single all-clear line when
     ok, and never raises (also on hand-built pathological audits).
  8. LIVE BRAKE, two-sided: the repo's real README.md + `foundry_cli_verbs(foundry.py)` is `ok`
     with no unknown invocations; strip one covered verb's invocations and that verb goes missing.
  9. README.md carries "# 49." (new-product) and "# 50." (preship), each with a runnable
     invocation line, iter 117's "# 42." is untouched and every section number is unique.
 10. `import foundry` / `import dispatcher` still succeed in a FRESH interpreter.
  Plus Acceptance-Criteria oracles: the audit does NO I/O, is deterministic, adds no
  ProductConfig key, and the iteration-169 Done-ledger row exists.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-169 PM spec's Expected Behaviors, the
conventions of `tests/` (the `_ROOT`/`sys.path` + literals-pinned-here shape of
test_iter142_behavior.py), and the product's OBSERVABLE surface -- CALLING the public function
and reading the SHIPPED prose of README.md / PLATFORM_ROADMAP.md, which Behaviors 8-9 make the
deliverable itself.  The implementation bodies of `foundry.py` / `dispatcher.py`, the engineer's
notes (`engineer.md`), the reviewer's notes (`reviewer.md`) and `git diff` were NOT read;
`foundry.py`'s text is passed to the function under test as DATA only, never inspected.

Offline and deterministic: no network, no agent run, no sleeps, no clock; the only subprocesses
are the two fresh-interpreter import probes Behavior 10 names.  Nothing in the repo is mutated.
"""
from __future__ import annotations

import dataclasses
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

THIS_ITER = 169
README = _ROOT / "README.md"
ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"

# Pinned HERE (not imported from the module under test) so a change to either would be caught.
FIELDS = ("missing_verbs", "sections_without_invocation", "unknown_invocations",
          "sections_scanned", "ok")
SECTION_RE = re.compile(r"^#\s+\d+\.", re.MULTILINE)


def _audit(text, verbs):
    return foundry.readme_verb_index_gaps(text, verbs)


def _readme_text() -> str:
    return README.read_text(encoding="utf-8")


def _live_verbs() -> tuple:
    return foundry.foundry_cli_verbs((_ROOT / "foundry.py").read_text(encoding="utf-8"))


# --------------------------------------------------------------- 1. shape + ok contract

def test_b1_frozen_dataclass_with_exactly_the_specced_fields():
    dc = foundry.ReadmeVerbIndexAudit
    assert dataclasses.is_dataclass(dc), "ReadmeVerbIndexAudit must be a dataclass"
    assert dc.__dataclass_params__.frozen, "the audit must be FROZEN"
    assert tuple(f.name for f in dataclasses.fields(dc)) == FIELDS


def test_b1_ok_is_true_only_when_the_first_three_tuples_are_empty():
    clear = _audit("# 1. status\n\n    foundry.py status\n", ("status",))
    assert (clear.missing_verbs, clear.sections_without_invocation,
            clear.unknown_invocations) == ((), (), ())
    assert clear.ok is True

    # each of the three findings, in isolation, must flip ok to False
    missing = _audit("# 1. status\n\n    foundry.py status\n", ("status", "run"))
    assert missing.missing_verbs == ("run",) and missing.ok is False
    assert (missing.sections_without_invocation, missing.unknown_invocations) == ((), ())

    verbless = _audit("# 1. prose only\n\nnothing runnable here\n", ())
    assert verbless.sections_without_invocation == ("1",) and verbless.ok is False
    assert (verbless.missing_verbs, verbless.unknown_invocations) == ((), ())

    unknown = _audit("# 1. status\n\n    foundry.py status\n    foundry.py frobnicate\n",
                     ("status",))
    assert unknown.unknown_invocations == ("frobnicate",) and unknown.ok is False
    assert (unknown.missing_verbs, unknown.sections_without_invocation) == ((), ())


def test_b1_result_type_is_the_audit_and_ok_is_a_real_bool():
    a = _audit("# 1. x\n foundry.py status\n", ("status",))
    assert isinstance(a, foundry.ReadmeVerbIndexAudit)
    assert isinstance(a.ok, bool) and isinstance(a.sections_scanned, int)
    for name in FIELDS[:3]:
        assert isinstance(getattr(a, name), tuple)


# --------------------------------------------------------------- 2. section grammar

def test_b2_section_headings_are_hash_space_digits_dot_only():
    text = ("# 1. one\nprose\n"
            "## 2. two hashes is not a section\n"
            "#3. no space is not a section\n"
            "#  4. extra space still counts\nprose\n")
    a = _audit(text, ())
    assert a.sections_scanned == 2, "only '# 1.' and '#  4.' are sections"
    assert a.sections_without_invocation == ("1", "4")


def test_b2_a_body_runs_to_the_next_section_heading():
    text = ("# 1. alpha\nprose only\n"
            "# 2. beta\n    foundry.py status\n")
    a = _audit(text, ("status",))
    assert a.sections_scanned == 2
    assert a.missing_verbs == (), "section 2 covers status"
    assert a.sections_without_invocation == ("1",), "the invocation belongs to section 2 only"


def test_b2_sections_scanned_matches_an_independent_count_of_the_real_readme():
    text = _readme_text()
    assert _audit(text, ()).sections_scanned == len(SECTION_RE.findall(text))


# --------------------------------------------------------------- 3. coverage rule

def test_b3_two_sided_present_then_deleted():
    with_line = "# 7. status\n\n    foundry.py status --json\n"
    assert _audit(with_line, ("status",)).missing_verbs == ()
    without = with_line.replace("    foundry.py status --json\n", "")
    assert _audit(without, ("status",)).missing_verbs == ("status",)


def test_b3_coverage_is_whitespace_separated_not_a_substring():
    a = _audit("# 1. x\n    foundry.py statusx\n", ("status",))
    assert a.missing_verbs == ("status",), "'statusx' must not cover 'status'"
    assert a.unknown_invocations == ("statusx",)
    assert _audit("# 1. x\n    foundry.py  status\n", ("status",)).missing_verbs == ()


def test_b3_only_the_foundry_py_shape_counts():
    assert _audit("# 1. x\n    dispatcher.py status\n", ("status",)).missing_verbs == ("status",)
    preamble = "foundry.py status\n\n# 1. x\n    dispatcher.py run\n"
    assert _audit(preamble, ("status",)).missing_verbs == ("status",), \
        "an invocation outside every section body covers nothing"


def test_b3_hyphenated_verbs_are_covered_by_their_own_invocation():
    text = "# 49. new-product\n\n    foundry.py new-product --repo r --name n\n"
    assert _audit(text, ("new-product",)).missing_verbs == ()
    assert _audit(text, ("new-product", "preship")).missing_verbs == ("preship",)


def test_b3_missing_verbs_is_sorted():
    a = _audit("# 1. x\n dispatcher.py\n", ("zebra", "alpha", "middle"))
    assert a.missing_verbs == ("alpha", "middle", "zebra")


# --------------------------------------------------------------- 4. derived exemption

def test_b4_a_dispatcher_section_is_exempt_and_needs_no_allowlist():
    exempt = "# 3. run the brain\n\n    nohup python3 dispatcher.py run &\n"
    assert _audit(exempt, ()).sections_without_invocation == ()
    neither = "# 3. run the brain\n\n    just prose\n"
    assert _audit(neither, ()).sections_without_invocation == ("3",)


def test_b4_sections_without_invocation_is_in_document_order():
    text = ("# 9. nine\nprose\n"
            "# 2. two\nprose\n"
            "# 5. five\n    foundry.py status\n"
            "# 1. one\n    dispatcher.py run\n"
            "# 7. seven\nprose\n")
    a = _audit(text, ("status",))
    assert a.sections_without_invocation == ("9", "2", "7"), "document order, not sorted"


def test_b4_a_section_with_both_a_verb_and_dispatcher_is_not_a_finding():
    text = "# 3. both\n    dispatcher.py run\n    foundry.py status\n"
    a = _audit(text, ("status",))
    assert a.ok is True and a.sections_without_invocation == ()


# --------------------------------------------------------------- 5. unknown invocations

def test_b5_unknown_invocations_are_reported_sorted_and_deduped():
    text = ("# 1. x\n    foundry.py status\n"
            "# 2. y\n    foundry.py zeta\n    foundry.py alpha\n    foundry.py zeta\n")
    a = _audit(text, ("status",))
    assert a.unknown_invocations == ("alpha", "zeta")
    assert a.ok is False


def test_b5_a_known_verb_is_never_an_unknown_invocation():
    a = _audit("# 1. x\n    foundry.py preship\n", ("preship",))
    assert a.unknown_invocations == () and a.ok is True


# --------------------------------------------------------------- 6. totality

@pytest.mark.parametrize("bad", [None, 123, 4.5, b"# 1. x", ["# 1. x"], {"a": 1}, object()])
def test_b6_non_str_readme_scans_nothing_and_reports_every_verb_missing(bad):
    a = _audit(bad, ("beta", "alpha"))
    assert a.sections_scanned == 0
    assert a.missing_verbs == ("alpha", "beta")
    assert (a.sections_without_invocation, a.unknown_invocations) == ((), ())
    assert a.ok is False


def test_b6_empty_readme_behaves_like_a_non_str_one():
    a = _audit("", ("beta", "alpha"))
    assert a.sections_scanned == 0 and a.missing_verbs == ("alpha", "beta")


def test_b6_empty_verbs_with_empty_text_is_ok():
    a = _audit("", ())
    assert (a.sections_scanned, a.missing_verbs, a.ok) == (0, (), True)


@pytest.mark.parametrize("bad_verbs", [None, 5, 4.5, object(), True])
def test_b6_non_iterable_verbs_is_treated_as_empty(bad_verbs):
    a = _audit("# 1. x\n    foundry.py status\n", bad_verbs)
    assert a.missing_verbs == ()


def test_b6_non_str_members_of_verbs_are_ignored():
    a = _audit("# 1. x\n    foundry.py status\n", ("status", 7, None, object()))
    assert a.missing_verbs == () and a.ok is True
    b = _audit("# 1. x\n    dispatcher.py run\n", ("run", 7, None))
    assert b.missing_verbs == ("run",), "only the str member is audited"


@pytest.mark.parametrize("text", [None, "", "# 1.", "#\t1. tab", "\x00# 1. nul\n",
                                  "# 1. x\nfoundry.py\n", "foundry.py \n# 1. x\n",
                                  "# 0. zero\n" * 200])
@pytest.mark.parametrize("verbs", [(), ("status",), ["run", 3], (None,)])
def test_b6_never_raises(text, verbs):
    a = _audit(text, verbs)
    assert isinstance(a, foundry.ReadmeVerbIndexAudit)


# --------------------------------------------------------------- 7. render()

def test_b7_render_names_every_finding_category_and_its_members():
    text = ("# 1. prose only\nnothing\n"
            "# 2. x\n    foundry.py status\n    foundry.py frobnicate\n")
    a = _audit(text, ("status", "run"))
    assert (a.missing_verbs, a.sections_without_invocation, a.unknown_invocations) == \
        (("run",), ("1",), ("frobnicate",))
    out = a.render()
    assert isinstance(out, str) and out.strip()
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) >= 4, f"expected a banner plus one line per category, got {lines!r}"
    for members in (("run",), ("1",), ("frobnicate",)):
        assert any(all(m in ln for m in members) for ln in lines), \
            f"no line reports {members!r} in {out!r}"


def test_b7_render_is_a_single_explicit_all_clear_line_when_ok():
    a = _audit("# 1. x\n    foundry.py status\n", ("status",))
    assert a.ok is True
    out = a.render()
    lines = [ln for ln in out.splitlines() if ln.strip()]
    # spec 7: "a single explicit all-clear line" -- read as exactly one line beyond the
    # scan banner (the banner itself is asserted separately below).
    assert len(lines) == 2, f"expected banner + ONE all-clear line, got {lines!r}"
    assert str(a.sections_scanned) in lines[0]
    assert lines[1].strip(), "the all-clear line must say something"


def test_b7_render_never_raises_on_a_hand_built_audit():
    weird = [
        foundry.ReadmeVerbIndexAudit((), (), (), 0, True),
        foundry.ReadmeVerbIndexAudit(("a",), ("1",), ("b",), -3, False),
        foundry.ReadmeVerbIndexAudit(tuple(str(i) for i in range(50)), (), (), 1, False),
        foundry.ReadmeVerbIndexAudit(("uni\u00e9",), ("\u00e91",), (), 2, False),
    ]
    for a in weird:
        assert isinstance(a.render(), str)


# --------------------------------------------------------------- 8. live brake (two-sided)

def test_b8_live_readme_has_no_index_gaps():
    text = _readme_text()
    verbs = _live_verbs()
    assert len(verbs) >= 48, f"non-vacuity floor: derived only {len(verbs)} verbs"
    a = _audit(text, verbs)
    assert a.sections_scanned >= 49, f"non-vacuity floor: {a.sections_scanned} sections"
    assert a.missing_verbs == (), f"CLI verbs with no README index entry: {a.missing_verbs}"
    assert a.unknown_invocations == (), \
        f"README invokes names the CLI does not accept: {a.unknown_invocations}"
    assert a.sections_without_invocation == (), \
        f"sections invoking neither a verb nor dispatcher.py: {a.sections_without_invocation}"
    assert a.ok is True


@pytest.mark.parametrize("verb", ["preship", "new-product", "doctor"])
def test_b8_the_brake_is_not_vacuous_known_bad_sample(verb):
    text = _readme_text()
    verbs = _live_verbs()
    assert verb in verbs, f"{verb} must be a real CLI verb"
    stripped = text.replace("foundry.py " + verb, "REMOVED_FOR_THIS_TEST")
    assert stripped != text, f"README must invoke 'foundry.py {verb}' somewhere"
    a = _audit(stripped, verbs)
    assert verb in a.missing_verbs, "the audit must go RED when an index entry loses its verb"
    assert a.ok is False


# --------------------------------------------------------------- 9. the two new README entries

@pytest.mark.parametrize("number,verb", [("49", "new-product"), ("50", "preship")])
def test_b9_readme_gained_a_section_per_missing_verb(number, verb):
    text = _readme_text()
    heads = SECTION_RE.findall(text)
    assert "# " + number + "." in [h.strip() for h in heads], \
        f"expected a '# {number}.' section, saw {heads[-4:]}"
    bodies = _sections(text)
    body = bodies[number]
    assert verb in body.splitlines()[0], f"section {number} must be titled for {verb}"
    assert "foundry.py " + verb in body, f"section {number} needs a runnable invocation"


def test_b9_existing_section_numbers_are_untouched():
    text = _readme_text()
    numbers = [h.strip().lstrip("#").strip().rstrip(".") for h in SECTION_RE.findall(text)]
    assert len(numbers) == len(set(numbers)), f"duplicate section numbers: {numbers}"
    assert "42" in numbers, "iter 117's '# 42.' assert must stay green"
    assert numbers == sorted(numbers, key=int), "sections must stay in ascending order"
    assert index_numbers_pin_violations(numbers) == (), \
        f"README section-number contract broken: "\
        f"{index_numbers_pin_violations(numbers)}; tail was {numbers[-4:]}"


def index_numbers_pin_violations(numbers: list[str]) -> tuple[str, ...]:
    """The README section-number contract as a PURE rule over the number list; () means clean.

    WHY presence-plus-order instead of position: `readme_verb_index_gaps` (this iteration's own
    brake) REQUIRES every CLI verb to own a numbered README section, so every add-a-verb iteration
    appends one.  Pinning "49" and "50" as the LAST two sections therefore froze a snapshot into a
    law and deadlocked that entire class of work -- iteration 173 reverted on exactly this assert
    with every other gate green.  Adjacency still rejects a deletion, a duplicate, a reorder and a
    gap between the pair, while tolerating precisely the growth the contract mandates.

    WHY it is a module-level function rather than inline asserts: a rule reachable only through the
    live README can never be shown to reject a known-bad input, so it can rot into a fail-open
    check.  Exposed here (the shape `index_growth_allowance` in tests/test_iter167_behavior.py
    already established) it can be exercised two-sided over synthetic lists.
    """
    out: list[str] = []
    if len(numbers) != len(set(numbers)):
        out.append("duplicate section numbers")
    if "42" not in numbers:
        out.append("'42' missing")
    try:
        ascending = list(numbers) == sorted(numbers, key=int)
    except (TypeError, ValueError):  # a non-integer section number is itself a violation
        ascending = False
        out.append("non-integer section number")
    if not ascending:
        out.append("not in ascending integer order")
    for pinned in ("49", "50"):
        if pinned not in numbers:
            out.append("'%s' missing" % pinned)
    if "49" in numbers and "50" in numbers:
        if numbers.index("50") != numbers.index("49") + 1:
            out.append("'50' does not immediately follow '49'")
    return tuple(out)


def _sections(text: str) -> dict:
    """{section number -> body incl. its heading line}, computed here, not imported."""
    out, starts = {}, [m.start() for m in SECTION_RE.finditer(text)]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        chunk = text[start:end]
        out[chunk.split(".", 1)[0].lstrip("#").strip()] = chunk
    return out


# --------------------------------------------------------------- 10. + AC oracles

@pytest.mark.parametrize("mod", ["foundry", "dispatcher"])
def test_b10_module_imports_in_a_fresh_interpreter(mod):
    p = subprocess.run([sys.executable, "-c", "import " + mod], cwd=str(_ROOT),
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr


def test_ac_the_audit_does_no_io(monkeypatch):
    def boom(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("the function under test performed I/O")

    text, verbs = _readme_text(), _live_verbs()
    monkeypatch.setattr("builtins.open", boom)
    monkeypatch.setattr(pathlib.Path, "read_text", boom)
    monkeypatch.setattr(pathlib.Path, "open", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    a = _audit(text, verbs)
    assert a.ok is True
    assert isinstance(a.render(), str)


def test_ac_the_audit_is_deterministic():
    text, verbs = _readme_text(), _live_verbs()
    assert _audit(text, verbs) == _audit(text, verbs)
    assert _audit(text, verbs).render() == _audit(text, verbs).render()


def test_ac_no_new_product_config_key():
    names = {f.name for f in dataclasses.fields(foundry.ProductConfig)}
    for token in ("readme", "verb_index", "index_gap"):
        assert not [n for n in names if token in n], \
            f"no new ProductConfig key expected, saw {token!r} in {sorted(names)}"


def test_ac_roadmap_carries_the_iteration_169_done_ledger_row():
    text = ROADMAP.read_text(encoding="utf-8")
    rows = [ln for ln in text.splitlines()
            if ln.startswith("- iter " + str(THIS_ITER) + " --")]
    assert rows, "the Done ledger needs a row for iteration 169"
