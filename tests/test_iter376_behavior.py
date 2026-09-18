"""Black-box behaviour tests for iter 376 -- ARCHITECTURE invariant-count canon.

Spec: products/_platform/state/iter-376/pm.md, Expected Behaviors 1-8.

  1. `architecture_invariant_names(doc)` extracts the TOP-LEVEL bolded bullets of the
     `## N. Invariants ...` span, in source order, one trailing period stripped, and
     EXCLUDES a bolded bullet that lives in a LATER `## N+1. ...` section.
  2. only TOP-LEVEL bullets count -- an INDENTED `  - **Delta.**` and an inline
     `**Epsilon:**` emphasis inside the span are both absent from the result.
  3. total and pure -- `""`, no-heading text and a bullet-free span all yield `()`,
     nothing raises, arguments are not mutated, no filesystem/subprocess/network/clock.
  4. `invariant_count_gaps(citing, doc)` reports a DISAGREEING count claim as one
     `InvariantCountGap(claimed, expected, phrase)`; two claims -> two records in
     source order.
  5. an AGREEING claim yields `()` in digit form, word form and with one intervening
     word (`six hard-won invariants`, README's live shape).
  6. negative controls -- live roadmap prose carrying a SINGULAR `invariant` far from a
     number, and `five whole hard-won invariants` (TWO intervening words), extract NO
     claim at all, so a widened pattern cannot land silently.
  7. LIVE TREE calibration -- `names(ARCHITECTURE.md)` is non-empty and both
     `gaps(VISION.md, ARCH)` and `gaps(README.md, ARCH)` are `()`, with the mandatory
     VACUITY GUARD that the claim pattern finds >= 1 claim in EACH citing document.
     Only the RELATION is asserted; the literal count is never pinned.
  8. LIVE TREE -- the iteration-numbering bullet is MOVED, not deleted: it is absent
     from the invariants span, present (text-preserved) in `## 5. Memory model`, and
     iteration 149's `quality_bar_invariant_gaps` brake is still `()` and non-vacuous.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-376
PM spec's Expected Behaviors / Acceptance Criteria, from pre-existing modules under
`tests/` (chiefly `tests/test_iter149_behavior.py`, the sibling brake in this same
family, for the purity-by-co_names and live-tree/anti-vacuity conventions), and from the
product's OWN observable behaviour by CALLING its public interface. The implementation
source of `foundry.py`, the engineer's notes, the reviewer's notes and `git diff` were
NOT read. `ARCHITECTURE.md` / `VISION.md` / `README.md` are read at RUN TIME by the live
behaviours because the spec requires it; the expected TEXT of the moved bullet comes from
the spec's own Acceptance Criterion, not from the shipped document. Zero network; the
only subprocess is the two-module clean-interpreter import probe.
"""
import pathlib
import re
import subprocess
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)

_ROOT = pathlib.Path(__file__).resolve().parents[1]
LIVE_ARCH = _ROOT / "ARCHITECTURE.md"
LIVE_VISION = _ROOT / "VISION.md"
LIVE_README = _ROOT / "README.md"
LIVE_CFG = _ROOT / "products" / "_platform" / "config.json"

INVARIANT_HEADING = "## 3. Invariants (do not regress these)"

# ---- fixtures -------------------------------------------------------------
DOC_B1 = """# synthetic architecture

Some preamble prose.

## 3. Invariants (do not regress these)

- **Alpha.** the first invariant, trailing period inside the bold.
- **Beta** the second invariant, no trailing period inside the bold.
- **Gamma.** the third invariant.

## 4. Something else

- **Delta-later.** a bolded bullet OUTSIDE the invariants span.
"""

DOC_B2 = """## 3. Invariants (do not regress these)

- **Alpha.** a top-level invariant.
  - **Delta.** an INDENTED sub-bullet, which is NOT an invariant.
- **Beta.** another top-level invariant.

Prose carrying an inline **Epsilon:** emphasis that must never read as an invariant,
exactly like the real section's **Post-release re-verification:** paragraph.

## 4. Next section
"""

DOC_NO_BULLETS = """## 3. Invariants (do not regress these)

Only prose lives here, with an inline **Zeta:** emphasis and nothing else.

## 4. Next
"""

# The live roadmap shape from the spec's behaviour 6 -- SINGULAR `invariant`, and the
# number is many words away from it.
ROADMAP_PROSE = ("| 4 | Risk-split the final gate (test-only diff = light gate) | ... "
                 "\u00a73 full-suite-rerun invariant untouched |")

# The moved bullet, quoted from the spec's first Acceptance Criterion (NOT from the
# shipped document). Compared after whitespace collapse + backslash removal.
MOVED_BULLET = ("- **Iteration numbering** continues across restarts by scanning "
                "`state/iter-*`.")

HOSTILE = [
    "", " ", "\n\n", "##", "## 3.", "## 3. Invariants",
    "- **Alpha.** a bullet with no heading at all",
    "## 3. Invariantsomething\n\n- **Alpha.** near-miss heading\n",
    "## 33. Invariants (x)\n\n- **Alpha.** two-digit section\n",
    "**Alpha.** bold with no bullet marker",
    "- ** ** empty bold",
    "- **" + "x" * 3000 + "**",
    "x" * 5000,
    "\u00e9\u4e2d",
]

# names that would mean a "pure" helper reached the filesystem, a subprocess, the
# network or the clock (convention borrowed from tests/test_iter149_behavior.py)
IO_NAMES = frozenset({
    "open", "read_text", "write_text", "read_bytes", "write_bytes", "Path",
    "mkdir", "unlink", "remove", "rename", "load_config", "loads", "dump",
    "dumps", "subprocess", "check_output", "Popen", "urlopen", "socket",
    "requests", "input", "shutil", "glob", "sleep", "monotonic",
    "datetime", "now", "random", "environ", "getenv", "system", "popen",
})


# ---- helpers --------------------------------------------------------------
def _names(doc):
    return foundry.architecture_invariant_names(doc)


def _gaps(citing, doc):
    return foundry.invariant_count_gaps(citing, doc)


def _doc_with(count, heading=INVARIANT_HEADING):
    """A synthetic architecture doc whose invariants span holds `count` bullets."""
    body = "\n".join("- **Inv%d.** prose for invariant %d." % (i, i)
                      for i in range(1, count + 1))
    return "%s\n\n%s\n\n## 4. Next section\n\n- **Outside.** later.\n" % (heading, body)


def _co_names_deep(fn):
    """Every name referenced by fn, including names inside nested code objects."""
    seen, names = set(), set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names.update(code.co_names)
        names.update(getattr(code, "co_varnames", ()))
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                stack.append(const)
    return names


def _norm(text):
    return " ".join(text.replace("\\", "").split())


def _section_span(text, heading_prefix):
    """The lines from `heading_prefix` up to (excluding) the next `## ` heading."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith(heading_prefix):
            start = i
            break
    assert start is not None, "no heading starting %r" % (heading_prefix,)
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


def _claim_count(text):
    return len(list(foundry.INVARIANT_COUNT_CLAIM_RE.finditer(text)))


DOC_SIX = _doc_with(6)


# ==========================================================================
# contract -- the named surface exists and the globals are read AT CALL TIME
# ==========================================================================
def test_contract_named_surface_exists_on_foundry():
    for name in ("architecture_invariant_names", "invariant_count_gaps"):
        fn = getattr(foundry, name, None)
        assert callable(fn), "foundry.%s is missing or not callable" % name
        assert fn.__module__ == "foundry", (name, fn.__module__)
    rec = getattr(foundry, "InvariantCountGap", None)
    assert rec is not None, "foundry.InvariantCountGap is missing"
    assert tuple(getattr(rec, "_fields", ())) == ("claimed", "expected", "phrase"), \
        getattr(rec, "_fields", None)
    for g in ("ARCHITECTURE_INVARIANT_HEADING_RE", "INVARIANT_COUNT_CLAIM_RE",
              "INVARIANT_COUNT_WORDS"):
        assert hasattr(foundry, g), "foundry.%s is missing" % g


def test_contract_the_record_is_frozen():
    rec = foundry.InvariantCountGap(claimed=1, expected=2, phrase="one invariants")
    try:
        rec.claimed = 9
    except AttributeError:
        pass
    else:
        raise AssertionError("InvariantCountGap is mutable")
    assert (rec.claimed, rec.expected, rec.phrase) == (1, 2, "one invariants")


def test_contract_heading_pattern_is_read_at_call_time(monkeypatch):
    doc = "## Zeta invariants here\n\n- **Alpha.** x.\n\n## 4. Next\n"
    assert _names(doc) == (), _names(doc)
    monkeypatch.setattr(foundry, "ARCHITECTURE_INVARIANT_HEADING_RE",
                        re.compile(r"^##\s+Zeta\b.*$", re.M))
    assert _names(doc) == ("Alpha",), _names(doc)


def test_contract_claim_pattern_and_word_map_are_read_at_call_time(monkeypatch):
    assert _gaps("eleven invariants", DOC_SIX) == ()
    monkeypatch.setattr(
        foundry, "INVARIANT_COUNT_CLAIM_RE",
        re.compile(r"\b(eleven)\s+invariants\b", re.I))
    monkeypatch.setattr(foundry, "INVARIANT_COUNT_WORDS", {"eleven": 11})
    got = _gaps("eleven invariants", DOC_SIX)
    assert got == ((11, 6, "eleven invariants"),), got


# ==========================================================================
# Behavior 1 -- section-scoped extraction, source order, period stripped
# ==========================================================================
def test_b1_extracts_the_span_bullets_in_source_order():
    got = _names(DOC_B1)
    assert got == ("Alpha", "Beta", "Gamma"), got
    assert isinstance(got, tuple) and all(isinstance(n, str) for n in got)


def test_b1_a_later_sections_bolded_bullet_is_excluded():
    assert "Delta-later" not in _names(DOC_B1)
    assert not any("later" in n.lower() for n in _names(DOC_B1)), _names(DOC_B1)


def test_b1_exactly_one_trailing_period_is_stripped():
    doc = ("## 3. Invariants (x)\n\n- **Alpha.** a.\n- **Beta** b.\n"
           "- **Gamma..** c.\n\n## 4. Next\n")
    assert _names(doc) == ("Alpha", "Beta", "Gamma."), _names(doc)


# ==========================================================================
# Behavior 2 -- only TOP-LEVEL bullets count
# ==========================================================================
def test_b2_indented_sub_bullet_and_inline_bold_are_not_invariants():
    got = _names(DOC_B2)
    assert got == ("Alpha", "Beta"), got
    assert "Delta" not in got and "Epsilon" not in got
    assert not any("Epsilon" in n or "Delta" in n for n in got), got


def test_b2_the_real_sections_inline_shape_never_reads_as_an_invariant():
    """`**Post-release re-verification:**` lives inline in the real section."""
    doc = ("## 3. Invariants (x)\n\n- **Alpha.** a.\n\n"
           "**Post-release re-verification:** prose about the gate.\n\n## 4. Next\n")
    assert _names(doc) == ("Alpha",), _names(doc)


# ==========================================================================
# Behavior 3 -- total and pure
# ==========================================================================
def test_b3_empty_missing_heading_and_bullet_free_span_all_yield_empty():
    assert _names("") == ()
    assert _names("no heading here, just prose") == ()
    assert _names(DOC_NO_BULLETS) == (), _names(DOC_NO_BULLETS)


def test_b3_totality_no_hostile_input_raises_from_either_function():
    for text in HOSTILE:
        got = _names(text)
        assert isinstance(got, tuple), (text[:40], got)
        gaps = _gaps(text, text)
        assert isinstance(gaps, tuple), (text[:40], gaps)
        for g in gaps:
            assert len(tuple(g)) == 3, g


def test_b3_arguments_are_not_mutated_and_results_are_deterministic():
    citing = "The five invariants in ARCHITECTURE.md are inviolable (a, b)."
    doc = DOC_SIX
    before = (citing[:], doc[:])
    assert len({_names(doc) for _ in range(5)}) == 1
    assert len({_gaps(citing, doc) for _ in range(5)}) == 1
    assert (citing, doc) == before


def test_b3_both_helpers_are_pure_no_io_subprocess_network_or_clock():
    for fn in (foundry.architecture_invariant_names, foundry.invariant_count_gaps):
        leaked = IO_NAMES & _co_names_deep(fn)
        assert leaked == frozenset(), \
            "%s must be pure; it references %s" % (fn.__name__, sorted(leaked))


# ==========================================================================
# Behavior 4 -- a disagreeing claim is one record with both numbers + phrase
# ==========================================================================
def test_b4_a_disagreeing_claim_is_reported_with_both_numbers_and_the_phrase():
    assert len(_names(DOC_SIX)) == 6, _names(DOC_SIX)   # vacuity guard for the doc side
    citing = "The five invariants in ARCHITECTURE.md are inviolable (a, b)."
    got = _gaps(citing, DOC_SIX)
    assert got == ((5, 6, "five invariants"),), got
    assert len(got) == 1
    assert got[0].claimed == 5 and got[0].expected == 6
    assert "five invariants" in got[0].phrase


def test_b4_a_disagreeing_digit_claim_is_reported_too():
    got = _gaps("README says 5 invariants.", DOC_SIX)
    assert got == ((5, 6, "5 invariants"),), got


def test_b4_two_disagreeing_claims_yield_two_records_in_source_order():
    citing = ("The five invariants in ARCHITECTURE.md are inviolable (a, b). "
              "Elsewhere this file wrongly says three invariants.")
    got = _gaps(citing, DOC_SIX)
    assert [g.claimed for g in got] == [5, 3], got
    assert [g.expected for g in got] == [6, 6], got
    assert got == ((5, 6, "five invariants"), (3, 6, "three invariants")), got


# ==========================================================================
# Behavior 5 -- an agreeing claim yields nothing, digit and word form
# ==========================================================================
def test_b5_agreeing_claims_yield_no_records():
    for citing in ("six invariants", "6 invariants", "six hard-won invariants"):
        assert _gaps(citing, DOC_SIX) == (), (citing, _gaps(citing, DOC_SIX))
        assert _claim_count(citing) >= 1, citing   # agreement, not a missed claim


def test_b5_agreement_is_measured_against_the_actual_bullet_count():
    five = _doc_with(5)
    assert len(_names(five)) == 5
    assert _gaps("five invariants", five) == ()
    assert _gaps("six invariants", five) == ((6, 5, "six invariants"),)


# ==========================================================================
# Behavior 6 -- negative controls: the shapes that would make the rule lie
# ==========================================================================
def test_b6_live_roadmap_prose_with_a_singular_invariant_extracts_no_claim():
    assert _claim_count(ROADMAP_PROSE) == 0, ROADMAP_PROSE
    assert _gaps(ROADMAP_PROSE, DOC_SIX) == (), _gaps(ROADMAP_PROSE, DOC_SIX)


def test_b6_two_intervening_words_is_past_the_documented_limit_of_one():
    text = "five whole hard-won invariants"
    assert _claim_count(text) == 0, text
    assert _gaps(text, DOC_SIX) == (), _gaps(text, DOC_SIX)


def test_b6_one_intervening_word_is_still_inside_the_limit():
    """Two-sided control for the test above -- the limit is ONE, not ZERO."""
    assert _claim_count("five hard-won invariants") == 1
    assert _gaps("five hard-won invariants", DOC_SIX) == \
        ((5, 6, "five hard-won invariants"),)


# ==========================================================================
# Behavior 7 -- LIVE TREE calibration + mandatory vacuity guard
# ==========================================================================
def test_b7_live_architecture_extraction_is_non_empty():
    names = _names(LIVE_ARCH.read_text())
    assert names, "architecture_invariant_names(ARCHITECTURE.md) is empty"
    assert all(n and n.strip() == n for n in names), names


def test_b7_live_vision_and_readme_counts_agree_with_architecture():
    arch = LIVE_ARCH.read_text()
    for path in (LIVE_VISION, LIVE_README):
        gaps = _gaps(path.read_text(), arch)
        assert gaps == (), "%s disagrees with ARCHITECTURE.md: %s" % (path.name, gaps)


def test_b7_vacuity_guard_each_citing_document_carries_at_least_one_claim():
    for path in (LIVE_VISION, LIVE_README):
        n = _claim_count(path.read_text())
        assert n >= 1, \
            "%s yields %d count claim(s) -- behaviour 7 would be vacuously green" % (
                path.name, n)


def test_b7_the_relation_holds_claimed_equals_the_live_bullet_count():
    """RELATION only -- the literal count is never pinned here (iter-185 trap)."""
    arch = LIVE_ARCH.read_text()
    expected = len(_names(arch))
    for path in (LIVE_VISION, LIVE_README):
        text = path.read_text()
        claims = list(foundry.INVARIANT_COUNT_CLAIM_RE.finditer(text))
        assert claims, path.name
        for m in claims:
            tok = m.group(1).lower()
            claimed = int(tok) if tok.isdigit() else foundry.INVARIANT_COUNT_WORDS[tok]
            assert claimed == expected, (path.name, m.group(0), claimed, expected)


def test_b7_two_sided_live_proof_a_planted_sixth_bullet_makes_both_fire():
    """Behaviour 7 must be ABLE to red: a brake that only ever returns () is untested.
    The planted bullet is inserted into a COPY of the text; no file is written."""
    arch = LIVE_ARCH.read_text()
    m = re.search(r"^##\s+\d+\.\s+Invariants\b.*$", arch, re.M)
    assert m, "no invariants heading in ARCHITECTURE.md"
    planted = (arch[:m.end()] + "\n\n- **Synthetic planted.** not a real invariant."
               + arch[m.end():])
    expected = len(_names(arch)) + 1
    assert len(_names(planted)) == expected, _names(planted)
    for path in (LIVE_VISION, LIVE_README):
        gaps = _gaps(path.read_text(), planted)
        assert len(gaps) == 1, (path.name, gaps)
        assert gaps[0].expected == expected, (path.name, gaps)
        assert gaps[0].claimed == expected - 1, (path.name, gaps)
        assert "invariants" in gaps[0].phrase, (path.name, gaps)


def test_b7_architecture_itself_carries_no_count_claim_so_it_cannot_self_red():
    assert _claim_count(LIVE_ARCH.read_text()) == 0, \
        "ARCHITECTURE.md now carries a count claim of its own"


# ==========================================================================
# Behavior 8 -- LIVE TREE: moved, not deleted, and iteration 149 stays green
# ==========================================================================
def test_b8_iteration_numbering_is_not_an_invariant_any_more():
    names = _names(LIVE_ARCH.read_text())
    assert not any("iteration numbering" in n.lower() for n in names), names


def test_b8_the_bullet_is_preserved_inside_the_memory_model_section():
    span = _section_span(LIVE_ARCH.read_text(), "## 5. Memory model")
    for fragment in ("**Iteration numbering**", "continues across restarts",
                     "state/iter-"):
        assert fragment in span, \
            "%r is not in the `## 5. Memory model` span" % (fragment,)
    moved = [ln for ln in span.splitlines() if "**Iteration numbering**" in ln]
    assert len(moved) == 1, moved
    assert _norm(moved[0]) == _norm(MOVED_BULLET), (moved[0], MOVED_BULLET)


def test_b8_the_bullet_is_gone_from_the_invariants_span():
    span = _section_span(LIVE_ARCH.read_text(), "## 3. Invariants")
    assert "Iteration numbering" not in span, span[-400:]


def test_b8_iteration_149s_quality_bar_brake_is_still_green_and_non_vacuous():
    bar = foundry.load_config(str(LIVE_CFG)).quality_bar
    cited = foundry.quality_bar_invariants(bar)
    assert cited, "quality_bar_invariants is empty -- the older brake went vacuous"
    gaps = foundry.quality_bar_invariant_gaps(bar, LIVE_ARCH.read_text())
    assert gaps == (), "the move broke iteration 149's brake: %s" % (gaps,)


def test_b8_bare_modules_still_import_in_a_clean_interpreter():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
