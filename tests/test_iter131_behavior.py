"""Black-box behaviour tests for iter 131 -- widen `parse_scout_candidates` to a UNION
of the existing `## Candidate ...` prefix rule and a new id-first rule (`## A1 -- x`),
so the committed `DIRECTIONS.md` decision log stops dropping a quarter of every slate.

Spec: products/_platform/state/iter-131/pm.md, Expected Behaviors 1-11.

  1.  existing `## Candidate ...` rule preserved, including DIGIT-LESS ids
  2.  id-first headings accepted for all five real families (A/B/C/H/I)
  3.  separator-agnostic: `--`, en dash, em dash, colon, bare space, nothing
  4.  parenthetical + backtick-decorated ids parse in full
  5.  case-insensitive on BOTH branches
  6.  six real non-candidate decoy headings NEVER match (asserted NEGATIVELY)
  7.  digit bound (<=2) + word boundary: `## A 2026 ...` / `## A2026 ...` skipped
  8.  heading depth unchanged: only exactly two `#` qualify
  9.  still pure + total: () on empties, never raises for ANY string
  10. integration, offline: refresh_directions_file renders BOTH files' candidates
  11. docs oracle: `roles/pm_scout.md` `### Candidate heading contract` examples
      all parse through the real function
  Plus Acceptance-Criteria oracles: union-not-replacement (old-rule superset over
  the whole real slate corpus), docstring claims, purity by introspection, import
  safety, and the two PM roadmap ledger records.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-131 PM spec and from the
product's own OBSERVABLE surface -- importing the module, CALLING its public
functions, reading `__doc__`, and reading the role card / roadmap files the spec
names as deliverables. The implementation BODIES of foundry.py / dispatcher.py, the
engineer's notes (engineer.md), the reviewer's notes (reviewer.md) and `git diff`
were NOT read. The purity oracle uses compiled `co_names` runtime introspection
only, never the source text.

Offline and deterministic: synthetic fixture strings, throwaway tmp_path trees, and
read-only reads of committed repo docs. No network, no agent run, no subprocess
work, no sleeps, no mutation of the product tree.
"""
import json
import pathlib
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- Acceptance Criteria)

EMDASH = "\u2014"
ENDASH = "\u2013"

# Six real non-candidate headings, verbatim from real slates (Behavior 6).
DECOYS = (
    "## Measured grounding (this run, this tree)",
    "## Note for the PM lead (advisory only)",
    "## Considered, measured, and deliberately NOT proposed",
    "## Ranking",
    "## Diversity note",
    "## Deliberately NOT proposed",
)

CONTRACT_HEADING = "### Candidate heading contract"
FENCE = "```"


def _cands(text):
    return foundry.parse_scout_candidates(text)


def _old_rule(text):
    """The PRE-iter-131 matcher, transcribed from the spec's implementation note 2
    (`line.lower().startswith("## candidate")`, leading `#` run + whitespace
    stripped). Used only to prove the new rule is a SUPERSET, never a replacement.
    """
    out = []
    for line in (text or "").splitlines():
        if line.lower().startswith("## candidate"):
            out.append(line.lstrip("#").lstrip())
    return tuple(out)


def _fn_names(fn):
    stack, seen, names = [fn.__code__], set(), set()
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names |= set(code.co_names)
        for c in code.co_consts:
            if isinstance(c, types.CodeType):
                stack.append(c)
    return names


def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir -- `repo`/`work_root` are TMP dirs so
    the real foundry repo/state is NEVER touched."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


# ==========================================================================
# 1. Existing rule preserved (regression) -- DIGIT-LESS ids included
# ==========================================================================
def test_b01_digitless_candidate_ids_still_parse_in_order():
    t = ("# PM_SCOUT_A -- iteration 131\n\n"
         "## Candidate A -- alpha\n"
         "## Candidate B -- beta\n"
         "## Candidate C -- gamma\n")
    assert _cands(t) == (
        "Candidate A -- alpha", "Candidate B -- beta", "Candidate C -- gamma")


def test_b01_candidate_with_digits_still_parses():
    t = "## Candidate C1 -- one\n## Candidate C2 -- two\n"
    assert _cands(t) == ("Candidate C1 -- one", "Candidate C2 -- two")


def test_b01_file_order_is_preserved_across_both_branches():
    t = ("## Candidate B -- second-shape-first\n"
         "## A1 -- id-first-second\n"
         "## Candidate C3 -- third\n")
    assert _cands(t) == (
        "Candidate B -- second-shape-first", "A1 -- id-first-second",
        "Candidate C3 -- third")


# ==========================================================================
# 2. Id-first headings are accepted -- all five real families
# ==========================================================================
@pytest.mark.parametrize("ident", ["A1", "B2", "C1", "H1", "I3"])
def test_b02_all_five_real_id_families_parse(ident):
    t = f"# title\n\n## {ident} -- x\n"
    assert _cands(t) == (f"{ident} -- x",)


def test_b02_id_first_stripping_matches_candidate_branch():
    """Same `#`/whitespace stripping on the new branch as on the old one."""
    assert _cands("##\tA1 -- x\n") == ("A1 -- x",)
    assert _cands("##   B2 -- y\n") == ("B2 -- y",)


def test_b02_two_letter_ids_parse():
    assert _cands("## AB1 -- x\n") == ("AB1 -- x",)


def test_b02_multiple_id_first_headings_all_returned():
    t = "## A1 -- one\n\nprose\n\n## A2 -- two\n\n## A3 -- three\n"
    assert _cands(t) == ("A1 -- one", "A2 -- two", "A3 -- three")


# ==========================================================================
# 3. Separator-agnostic
# ==========================================================================
@pytest.mark.parametrize("sep", ["--", ENDASH, EMDASH, ":", ""])
def test_b03_every_separator_yields_a_match(sep):
    line = f"## A1 {sep} do the thing".replace("  ", " ")
    got = _cands(line + "\n")
    assert got == (line.lstrip("#").lstrip(),), f"separator {sep!r} lost"


def test_b03_bare_space_no_punctuation_matches():
    assert _cands("## A1 do the thing\n") == ("A1 do the thing",)


def test_b03_bare_id_alone_matches_and_returns_the_id():
    assert _cands("## A1\n") == ("A1",)


def test_b03_bare_id_alone_with_trailing_whitespace_matches():
    assert _cands("## H3   \n") == ("H3",)


# ==========================================================================
# 4. Parenthetical and backtick-decorated ids parse in full
# ==========================================================================
def test_b04_parenthetical_id_parses_in_full():
    t = "## C1 (primary) -- Bite 4a renderer\n"
    assert _cands(t) == ("C1 (primary) -- Bite 4a renderer",)


def test_b04_backtick_decorated_heading_parses_in_full():
    t = "## B1 -- `foundry doctor` advisory\n"
    assert _cands(t) == ("B1 -- `foundry doctor` advisory",)


# ==========================================================================
# 5. Case-insensitive on BOTH branches
# ==========================================================================
@pytest.mark.parametrize("line", [
    "## CANDIDATE A -- x",
    "## candidate a1 -- x",
    "## a1 -- x",
    "## b2 -- x",
])
def test_b05_case_insensitive_on_both_branches(line):
    assert _cands(line + "\n") == (line.lstrip("#").lstrip(),)


# ==========================================================================
# 6. Real non-candidate headings must NOT match  (two-sided decoys)
# ==========================================================================
@pytest.mark.parametrize("decoy", DECOYS)
def test_b06_each_real_decoy_heading_is_rejected(decoy):
    assert _cands(decoy + "\n") == (), f"decoy matched: {decoy!r}"


def test_b06_decoys_are_absent_even_beside_real_candidates():
    body = "# title\n\n" + "\n".join(DECOYS) + "\n## A1 -- real\n## Candidate B -- real2\n"
    got = _cands(body)
    assert got == ("A1 -- real", "Candidate B -- real2")
    for decoy in DECOYS:
        stripped = decoy.lstrip("#").lstrip()
        assert stripped not in got


# ==========================================================================
# 7. Digit bound and word boundary
# ==========================================================================
@pytest.mark.parametrize("line", ["## A 2026 retrospective", "## A2026 notes"])
def test_b07_over_long_digit_runs_are_rejected(line):
    assert _cands(line + "\n") == (), f"should not match: {line!r}"


def test_b07_two_digit_id_still_matches():
    assert _cands("## A12 -- x\n") == ("A12 -- x",)


# ==========================================================================
# 8. Heading depth unchanged -- exactly two `#`
# ==========================================================================
@pytest.mark.parametrize("line", [
    "### A1 -- x",
    "### Candidate A1 -- x",
    "# A1 -- x",
    "#### A1 -- x",
    "# Candidate A -- x",
])
def test_b08_only_double_hash_headings_qualify(line):
    assert _cands(line + "\n") == (), f"wrong depth accepted: {line!r}"


def test_b08_deeper_headings_do_not_shadow_a_real_double_hash():
    t = "### A1 -- nested\n## A2 -- real\n#### Candidate A -- nested\n"
    assert _cands(t) == ("A2 -- real",)


# ==========================================================================
# 9. Still pure and total
# ==========================================================================
@pytest.mark.parametrize("text", ["", "   ", "no headings at all\njust prose\n"])
def test_b09_empty_tuple_for_empty_or_headingless_text(text):
    assert _cands(text) == ()


def test_b09_decoys_only_yields_empty_tuple():
    assert _cands("\n".join(DECOYS) + "\n") == ()


@pytest.mark.parametrize("text", [
    None, "", "   ", "#", "##", "## ", "##\t", "\x00\x01", "#" * 3000,
    "## Candidate", "\r\n## A1 -- x\r\n", "## \u00e9\u00e8 \U0001f600 emoji\n",
    "## A1 -- \U0001f600\r\n", "x" * 200_000, "## A1 -- x\n" * 500,
])
def test_b09_never_raises_on_adversarial_input(text):
    out = foundry.parse_scout_candidates(text)
    assert isinstance(out, tuple)
    assert all(isinstance(x, str) for x in out)


def test_b09_crlf_line_endings_parse_without_carriage_returns_leaking():
    got = _cands("# t\r\n\r\n## A1 -- x\r\n## Candidate B -- y\r\n")
    assert got == ("A1 -- x", "Candidate B -- y")
    assert not any("\r" in g for g in got)


def test_b09_large_body_is_handled_and_finds_its_candidates():
    body = ("filler line\n" * 20_000) + "## A1 -- needle\n" + ("more filler\n" * 5)
    assert len(body) > 200_000
    assert _cands(body) == ("A1 -- needle",)


def test_b09_function_is_pure_no_io_names_referenced():
    names = _fn_names(foundry.parse_scout_candidates)
    forbidden = {"open", "read_text", "write_text", "subprocess", "run",
                 "Path", "os", "print", "requests"}
    assert not (names & forbidden), f"impure names referenced: {sorted(names & forbidden)}"


def test_b09_repeated_calls_are_deterministic():
    t = "## A1 -- x\n## Candidate B -- y\n"
    assert _cands(t) == _cands(t) == ("A1 -- x", "Candidate B -- y")


# ==========================================================================
# 10. The decision log renders the recovered candidates (integration, offline)
# ==========================================================================
def _scout_slate(which, iteration, headings):
    lines = [f"# PM_SCOUT_{which} {EMDASH} iteration {iteration} {EMDASH} lens: lens{which}",
             "", "## Slate"]
    lines += list(headings)
    lines += ["", "## Note to the PM lead", "prose the parser must ignore"]
    return "\n".join(lines) + "\n"


def test_b10_directions_block_holds_candidates_from_both_scout_shapes(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    d = pathlib.Path(cfg.state) / "iter-07"
    d.mkdir(parents=True, exist_ok=True)
    id_first = ["## A1 -- widen the parser", "## A2 -- rotate the lens pool",
                "## A3 -- append-only digest"]
    candidate_shape = ["## Candidate B -- harvest the transcript",
                       "## Candidate C1 -- self-healing endpoint"]
    (d / "pm_scout_a.md").write_text(_scout_slate("A", 7, id_first))
    (d / "pm_scout_b.md").write_text(_scout_slate("B", 7, candidate_shape))
    (d / "pm.md").write_text(f"# PM spec {EMDASH} iteration 7\n\n"
                             "## Triage\n**Pick: A1** because.\n\n## Feature\nbody\n")
    (d / "final.md").write_text("gate report\n\nACTION: PUSHED sha007\n")

    assert foundry.refresh_directions_file(cfg) is True
    text = (pathlib.Path(cfg.repo) / "DIRECTIONS.md").read_text()
    for expected in ("A1 -- widen the parser", "A2 -- rotate the lens pool",
                     "A3 -- append-only digest",
                     "Candidate B -- harvest the transcript",
                     "Candidate C1 -- self-healing endpoint"):
        assert expected in text, f"DIRECTIONS.md dropped candidate: {expected!r}"


def test_b10_id_first_only_iteration_is_no_longer_candidate_less(tmp_path):
    """The measured headline: a slate written ENTIRELY id-first used to parse to
    zero candidates, so its DIRECTIONS block read as a one-option iteration."""
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    d = pathlib.Path(cfg.state) / "iter-11"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pm_scout_a.md").write_text(
        _scout_slate("A", 11, [f"## B{i} {EMDASH} option {i}" for i in (1, 2, 3)]))
    digest = foundry.gather_directions(cfg)
    entry = [e for e in digest.entries if e.iteration == 11]
    assert entry, "scouted iteration missing from the digest"
    assert len(entry[0].candidates) == 3
    assert _old_rule(_scout_slate("A", 11, [f"## B{i} {EMDASH} option {i}"
                                            for i in (1, 2, 3)])) == ()


def test_b10_decoy_headings_do_not_leak_into_the_decision_log(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    d = pathlib.Path(cfg.state) / "iter-12"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pm_scout_a.md").write_text(
        _scout_slate("A", 12, ["## A1 -- real"] + list(DECOYS)))
    digest = foundry.gather_directions(cfg)
    entry = [e for e in digest.entries if e.iteration == 12][0]
    assert entry.candidates == ("A1 -- real",)


# ==========================================================================
# 11. The write-side contract is documented and cannot drift
# ==========================================================================
def _contract_section_lines():
    """Return (all_section_lines, fenced_example_lines) for the role card's
    `### Candidate heading contract` section.

    The scan toggles an in-fence flag, because a fenced EXAMPLE line is itself a
    `##` heading and a naive next-heading regex would truncate the section at its
    own first example.
    """
    card = (_ROOT / "roles" / "pm_scout.md").read_text().splitlines()
    starts = [i for i, l in enumerate(card) if l.strip() == CONTRACT_HEADING]
    assert starts, f"roles/pm_scout.md is missing the exact heading {CONTRACT_HEADING!r}"
    i = starts[0] + 1
    section, fenced, in_fence = [], [], False
    while i < len(card):
        line = card[i]
        s = line.strip()
        if s.startswith(FENCE):
            in_fence = not in_fence
            section.append(line)
            i += 1
            continue
        if not in_fence and s.startswith("#") and s.lstrip("#").startswith(" "):
            break  # next heading of any depth, outside a fence
        section.append(line)
        if in_fence:
            fenced.append(line)
        i += 1
    return section, fenced


def test_b11_role_card_contract_section_exists_with_a_fenced_block():
    section, fenced = _contract_section_lines()
    assert any(l.strip().startswith(FENCE) for l in section), \
        "the contract section has no fenced code block"
    assert fenced, "the fenced code block is empty"


def test_b11_every_fenced_example_heading_parses_through_the_real_function():
    _section, fenced = _contract_section_lines()
    examples = [l for l in fenced if l.strip().startswith("##")]
    assert len(examples) >= 3, \
        f"need >=3 example headings so the oracle cannot pass vacuously, got {len(examples)}"
    for line in examples:
        got = foundry.parse_scout_candidates(line + "\n")
        assert got == (line.strip().lstrip("#").lstrip(),), \
            f"role card documents a shape the parser rejects: {line!r}"


def test_b11_examples_cover_both_union_branches():
    _section, fenced = _contract_section_lines()
    examples = [l.strip() for l in fenced if l.strip().startswith("##")]
    assert any(l.lower().startswith("## candidate") for l in examples), \
        "no `## Candidate ...` example -- the old branch is undocumented"
    assert any(not l.lower().startswith("## candidate") for l in examples), \
        "no id-first example -- the new branch is undocumented"


def test_b11_no_stray_double_hash_line_outside_the_fence():
    """If the oracle ever widens to the whole section, it must still pass: no
    rejected-shape example may be written as a bare line outside the fence."""
    section, fenced = _contract_section_lines()
    fenced_set = {id(l) for l in fenced}
    for line in section:
        s = line.strip()
        if id(line) in fenced_set or s.startswith(FENCE):
            continue
        assert not s.startswith("##"), \
            f"rejected shapes must be inline prose, not a line: {line!r}"


# ==========================================================================
# Acceptance-Criteria oracles
# ==========================================================================
def test_ac_union_is_a_superset_of_the_old_rule_over_the_real_slate_corpus():
    """No currently-parsed heading can be lost: assert set(old) <= set(new) over
    EVERY scout slate on disk (mechanical; content is never displayed)."""
    slates = sorted((_ROOT / "products").glob("*/state/iter-*/pm_scout_*.md"))
    if len(slates) < 10:
        pytest.skip("no meaningful slate corpus in this checkout")
    losses, gained = [], 0
    for p in slates:
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        old, new = set(_old_rule(text)), set(foundry.parse_scout_candidates(text))
        if not old <= new:
            losses.append(p.name)
        if len(new) > len(old):
            gained += 1
    assert not losses, f"old-rule matches lost on {len(losses)} slates: {losses[:5]}"
    assert gained > 0, "the union recovered nothing on the real corpus"


def _is_write_early_checkpoint(text: str) -> bool:
    """True when a scout file self-declares as an UNFINISHED write-early checkpoint.

    Matched at a LINE START only (and case-sensitively, as the write-early
    convention spells these markers in caps), so ordinary prose mentioning
    progress mid-sentence can never exclude a finished slate. Pure and total.
    """
    for raw in text.splitlines():
        line = raw.lstrip()
        if line.startswith("STATUS:"):
            line = line[len("STATUS:"):].lstrip()
        if line.startswith("CHECKPOINT") or line.startswith("IN PROGRESS"):
            return True
    return False


def test_ac_no_real_slate_parses_to_zero_candidates_when_it_has_id_headings():
    """The parser must find candidates in every FINISHED slate on disk.

    THE POPULATION EXCLUDES SELF-DECLARED WRITE-EARLY CHECKPOINTS, which is what
    makes this brake measure the PARSER instead of the loop's cap-kill rate. A
    scout stage killed under the ~600s cap leaves behind the checkpoint it wrote
    first -- a file that says `STATUS: CHECKPOINT` / `IN PROGRESS` and carries no
    candidate heading YET -- so grading it as a parse failure scores the kill, not
    the parser, and the tally then grows with every future cap-kill in ANY
    product. Counting them also made this test body disagree with its own NAME: an
    unfinished placeholder has no id headings at all.

    That is the frozen-count-over-gitignored-growing-state trap (OPERATOR
    2026-08-11): `products/*/state/` is gitignored, so a fresh clone SKIPS here
    while a long-lived checkout accumulates unfinished slates until a frozen
    integer reds a correct iteration. Measured on this checkout: 937 slates, of
    which 89 self-declare incomplete (86 of those still parse, having been refined
    after their checkpoint) and exactly 3 are unfinished with zero candidates --
    and over the 848 FINISHED slates the parser misses ZERO. Iteration 131's own
    `<= 2` headroom is kept unchanged rather than retuned down to that 0.

    The population FLOOR is the two-sided half: a filter that emptied the corpus
    would satisfy the `<= 2` bound forever, so it must leave a real corpus behind.
    """
    slates = sorted((_ROOT / "products").glob("*/state/iter-*/pm_scout_*.md"))
    if len(slates) < 10:
        pytest.skip("no meaningful slate corpus in this checkout")
    finished, zero = [], []
    for path in slates:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if _is_write_early_checkpoint(text):
            continue
        finished.append(path)
        if not foundry.parse_scout_candidates(text):
            zero.append(path)
    assert len(finished) >= 10, (
        f"the checkpoint filter left only {len(finished)} of {len(slates)} slates"
        " -- it would satisfy the bound below vacuously")
    assert len(zero) <= 2, (
        f"{len(zero)} FINISHED slates still parse to zero candidates: "
        f"{[q.name for q in zero[:5]]}")


def test_ac_docstring_states_both_shapes_and_the_depth_exclusion():
    doc = (foundry.parse_scout_candidates.__doc__ or "").lower()
    assert doc, "parse_scout_candidates lost its docstring"
    for needle in ("candidate", "###", "pure", "total"):
        assert needle in doc, f"docstring does not state {needle!r}"
    assert "union" in doc or "either" in doc, \
        "docstring does not state that the two shapes are a union"


def test_ac_modules_stay_importable_and_control_path_intact():
    assert foundry.__name__ == "foundry" and dispatcher.__name__ == "dispatcher"
    for name in ("run_stage", "run_iteration", "run_continuous", "build_prompt",
                 "refresh_directions_file", "gather_directions",
                 "parse_scout_candidates"):
        assert callable(getattr(foundry, name, None)), f"missing callable {name}"


def test_ac_roadmap_records_this_iteration_in_both_ledgers():
    idx = (_ROOT / "PLATFORM_ROADMAP.md").read_text()
    arch = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text()
    rows = [l for l in idx.splitlines() if l.strip().startswith("- iter 131")]
    assert rows, "no `- iter 131 ...` Done-ledger row in PLATFORM_ROADMAP.md"
    assert len(rows[0]) <= 120, f"ledger row is {len(rows[0])} chars (max 120)"
    assert any(l.strip().startswith("- **iter 131") for l in arch.splitlines()), \
        "no `- **iter 131 ...` detail bullet in PLATFORM_ROADMAP_ARCHIVE.md"
