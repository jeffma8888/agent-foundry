"""Iteration 379 -- BLACK-BOX behavior tests: `roles/pm_scout.md` teaches the shipped
`dormancy` verb, and two pure rules (`role_card_verbs`, `role_card_verb_gaps`) let the
suite assert that every verb ANY role card teaches is a verb the CLI accepts.

Spec under test: products/_platform/state/iter-379/pm.md.

  1.  Card teaches the verb: exact `### Classify a symbol before calling it dead or
      dormant` sub-heading inside `## Inputs`, AFTER the `### DIRECTIONS.md is an INPUT,
      not just an output` sub-section and BEFORE `## What to produce`; the exact
      invocation line and the exact rule fragment are present verbatim (case-sensitive).
  2.  Card growth is bounded: the new sub-section is <= 12 lines; the card is pure ASCII;
      the committed leak-guard reports 0 findings on it.
  3.  `role_card_verbs(card_text)` is PURE and TOTAL: sorted, de-duplicated tuple[str];
      `""` / non-`str` / no-invocation -> `()`; `foundry.py --help` contributes nothing;
      duplicates collapse; the argument is not mutated; equal inputs are `==`; it never
      raises; its shape agrees with `_README_INVOCATION_RE` on one line only.
  4.  `role_card_verb_gaps(card_text, verbs)`: the spec's two-sided in-memory example;
      `""` / non-`str` card -> `()` for any `verbs`; non-`str` members are ignored.
  5.  LIVE ADOPTION PIN: the scout card yields BOTH `directions` and `dormancy`, and
      `dormancy` is in `foundry_cli_verbs(<foundry.py text>)` -- in the SAME test.
  6.  Repo-wide brake: every `roles/*.md` has `role_card_verb_gaps(...) == ()` against the
      live CLI verb set, the 8 named cards exist, and >= 6 of them teach >= 1 verb.
  7.  Additive-dormant: no control-path function, CLI verb function or `dispatcher.py`
      names either new function; `import foundry, dispatcher` works; frozen paths are
      byte-unchanged against HEAD (skipped without git).
  8.  Scout-card contracts preserved: `scout_lens_audit(...).ok` is True (and equal to
      HEAD's when git is available); the `## WRITE-EARLY (checkpoint-first)` heading and
      the iter-233 anchor phrase remain in order; `### Candidate heading contract` remains.
  +   Ledger: the iteration's roadmap row + archive bullet are in the tree (every
      iteration since 230 pins this); this test file passes the leak-guard.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-379 PM
spec, the product README / roadmap / archive TEXT, the role cards as the ARTIFACT under
test, the pre-existing conventions under `tests/` (iterations 81, 175, 233, 244 and 378),
and the product's OWN observable behavior by importing and CALLING its public names
(`__doc__` included).  The implementation SOURCE of `foundry.py` / `dispatcher.py` was
NOT read by this author, nor the engineer's notes, the reviewer's notes,
`IMPLEMENTATION.patch`, or any `git diff` (the two git probes below read only an exit
code, a file NAME list restricted to frozen paths, and HEAD's copy of the scout card).

FRESH-CLONE SAFE / OFFLINE: every fixture for behaviors 3/4 is an in-memory string; the
only ambient files read are TRACKED (`roles/*.md`, `foundry.py`, `scripts/leak_guard.py`,
`PLATFORM_ROADMAP.md`, `PLATFORM_ROADMAP_ARCHIVE.md`) and are reached through
`pathlib.Path(__file__).resolve().parents[1]`, never an absolute machine path.  No
subprocess other than `git` (guarded by a skip) is spawned.  No real username, home
path or vendor name appears in any fixture.
"""
from __future__ import annotations

import importlib.util
import inspect
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe (the quality bar)

THIS_ITER = 379

ROLES = _ROOT / "roles"
SCOUT_CARD = ROLES / "pm_scout.md"
FOUNDRY_PY = pathlib.Path(foundry.__file__).resolve()  # the CLI source, as TEXT input
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

# ---- spec literals (behavior 1), verbatim
NEW_HEADING = "### Classify a symbol before calling it dead or dormant"
PRIOR_HEADING = "### DIRECTIONS.md is an INPUT, not just an output"
INPUTS_HEADING = "## Inputs"
PRODUCE_HEADING = "## What to produce"
INVOCATION = ("python3 <checkout>/foundry.py dormancy --config PRODUCT_CONFIG "
              "--symbol <name> [--symbol <name> ...] [--json]")
RULE_FRAGMENT = "never report a symbol as dead or dormant from a hand-rolled census"
MAX_SUBSECTION_LINES = 12

# ---- behavior 6: the eight cards the spec names, and the non-vacuity floor
EIGHT_CARDS = ("engineer", "final", "fix", "pm", "pm_scout", "reporter", "reviewer", "tester")
TEACHING_FLOOR = 6

# ---- behavior 7: the two new names and the control path (iter-175 convention)
NEW_NAMES = ("role_card_verbs", "role_card_verb_gaps")
CONTROL_PATH = ("run_stage", "run_iteration", "build_prompt", "postrelease_step", "main")

# ---- behavior 8: prior pins (iter-233 / iter-131)
WRITE_EARLY_HEADING = "## WRITE-EARLY (checkpoint-first)"
DIRECTIONS_ANCHOR = "DIRECTIONS.md is an INPUT"
CANDIDATE_HEADING = "### Candidate heading contract"

# ---- behavior 4: the spec's in-memory card, verbatim
GAP_CARD = "run python3 <c>/foundry.py retired-verb and foundry.py directions\nfoundry.py --help"

_GIT_OK = subprocess.run(
    ["git", "rev-parse", "--is-inside-work-tree"],
    cwd=str(_ROOT), capture_output=True, text=True,
).returncode == 0


# ---------------------------------------------------------------- helpers


def _card_text(name: str = "pm_scout") -> str:
    return (ROLES / f"{name}.md").read_text(encoding="utf-8")


def _cli_verbs() -> tuple:
    return foundry.foundry_cli_verbs(FOUNDRY_PY.read_text(encoding="utf-8"))


def _subsection_lines(text: str, heading: str) -> list:
    """Lines from `heading` up to (not including) the next `## ` / `### ` line."""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln == heading]
    assert len(starts) == 1, f"{heading!r} must appear exactly once, found {len(starts)}"
    out = []
    for ln in lines[starts[0]:]:
        if out and (ln.startswith("## ") or ln.startswith("### ")):
            break
        out.append(ln)
    return out


def _leak_guard():
    """Import the committed leak-guard the way iteration 81's pins do."""
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter379_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _leak_findings(text: str):
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    return mod.scan_text(text, denylist)


# =========================================================== 1. card teaches the verb


def test_b1_new_subheading_present_exactly_once() -> None:
    text = _card_text()
    assert text.count(NEW_HEADING) == 1
    assert (NEW_HEADING + "\n") in text, "heading must be its own line"


def test_b1_subheading_sits_inside_inputs_after_directions_and_before_produce() -> None:
    text = _card_text()
    i_inputs = text.index(INPUTS_HEADING + "\n")
    i_prior = text.index(PRIOR_HEADING)
    i_new = text.index(NEW_HEADING)
    i_produce = text.index(PRODUCE_HEADING)
    assert i_inputs < i_prior < i_new < i_produce, (i_inputs, i_prior, i_new, i_produce)
    # no OTHER `## ` heading opens between `## Inputs` and the new sub-section
    between = text[i_inputs + len(INPUTS_HEADING):i_new]
    assert not re.search(r"^## ", between, flags=re.M), "new sub-section left `## Inputs`"


def test_b1_exact_invocation_line_is_present_verbatim() -> None:
    text = _card_text()
    assert INVOCATION in text
    # it is one whole line (allowing the card's backtick fencing around it)
    line = next(ln for ln in text.splitlines() if INVOCATION in ln)
    assert line.strip().strip("`") == INVOCATION, line


def test_b1_exact_rule_fragment_is_present_verbatim_and_case_sensitive() -> None:
    text = _card_text()
    assert RULE_FRAGMENT in text
    assert RULE_FRAGMENT.upper() not in text  # a case-mangled copy is not the literal


def test_b1_both_literals_live_inside_the_new_subsection() -> None:
    body = "\n".join(_subsection_lines(_card_text(), NEW_HEADING))
    assert INVOCATION in body
    assert RULE_FRAGMENT in body


# =========================================================== 2. card growth is bounded


def test_b2_subsection_is_at_most_12_lines_including_heading_and_blanks() -> None:
    lines = _subsection_lines(_card_text(), NEW_HEADING)
    assert lines[0] == NEW_HEADING
    assert 1 <= len(lines) <= MAX_SUBSECTION_LINES, (len(lines), lines)


def test_b2_subsection_walker_stops_at_the_next_heading() -> None:
    # oracle self-check: the walker's cut rule is the spec's ("next `## ` or `### `")
    sample = "### A\nx\n\n### B\ny\n## C\n"
    assert _subsection_lines(sample, "### A") == ["### A", "x", ""]
    assert _subsection_lines(sample, "### B") == ["### B", "y"]


def test_b2_card_is_pure_ascii() -> None:
    raw = SCOUT_CARD.read_bytes()
    assert all(b < 128 for b in raw), "roles/pm_scout.md is not pure ASCII"


def test_b2_card_passes_committed_leak_guard() -> None:
    assert _leak_findings(_card_text()) == ()


def test_b2_leak_matcher_is_armed() -> None:
    # guard against a false-clean: a RUNTIME-built home-path shape must be flagged
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert _leak_findings(needle), "leak matcher is inert (false-clean risk)"


# =========================================================== 3. role_card_verbs: pure + total


def test_b3_is_a_module_level_function_with_a_docstring_stating_the_contract() -> None:
    fn = getattr(foundry, "role_card_verbs", None)
    assert inspect.isfunction(fn)
    doc = fn.__doc__ or ""
    for word in ("PURE", "TOTAL", "DORMANT"):
        assert word in doc, f"docstring must state {word}"


@pytest.mark.parametrize("bad", ["", None, 42, 3.5, b"foundry.py dormancy", ["foundry.py x"], {}])
def test_b3_empty_or_non_str_returns_empty_tuple(bad) -> None:
    assert foundry.role_card_verbs(bad) == ()


def test_b3_text_with_no_invocation_returns_empty_tuple() -> None:
    assert foundry.role_card_verbs("run the suite\nthen write tester.md\n") == ()
    assert foundry.role_card_verbs("python3 foundry.py") == ()  # bare, no verb token


def test_b3_returns_sorted_deduped_tuple_of_str() -> None:
    card = ("Run `python3 <checkout>/foundry.py status --config X`, then\n"
            "`foundry.py doctor` and again foundry.py status; finally foundry.py agents.\n")
    out = foundry.role_card_verbs(card)
    assert isinstance(out, tuple)
    assert all(isinstance(v, str) for v in out)
    assert out == ("agents", "doctor", "status")
    assert list(out) == sorted(set(out))


def test_b3_help_flag_is_not_a_verb() -> None:
    assert foundry.role_card_verbs("foundry.py --help") == ()
    assert foundry.role_card_verbs("python3 foundry.py --help\nfoundry.py -h") == ()
    assert foundry.role_card_verbs("foundry.py --help and foundry.py doctor") == ("doctor",)


def test_b3_invocation_must_be_on_one_line() -> None:
    assert foundry.role_card_verbs("foundry.py\ndormancy") == ()
    assert foundry.role_card_verbs("foundry.py \t dormancy") == ("dormancy",)


def test_b3_argument_is_not_mutated_and_equal_inputs_are_equal() -> None:
    a = "x foundry.py dormancy\ny foundry.py directions\n"
    b = "x foundry.py dormancy\ny foundry.py directions\n"
    before = a[:]
    r1 = foundry.role_card_verbs(a)
    r2 = foundry.role_card_verbs(b)
    assert a == before
    assert r1 == r2 == ("directions", "dormancy")
    assert foundry.role_card_verbs(a) == r1  # idempotent on repeat


def test_b3_never_raises_on_hostile_text() -> None:
    hostile = ["\x00foundry.py \x00", "foundry.py " * 5000, "\n" * 100, "foundry.py -", "FOUNDRY.PY doctor",
               "foundry.py 9lives foundry.py _under foundry.py dash-ed"]
    for text in hostile:
        out = foundry.role_card_verbs(text)
        assert isinstance(out, tuple)
    assert foundry.role_card_verbs("foundry.py 9lives foundry.py _under foundry.py dash-ed") == \
        ("9lives", "dash-ed")  # `_under` starts with `_`, outside the README shape


def test_b3_shape_agrees_with_the_readme_invocation_regex() -> None:
    # the spec says the extractor REUSES `_README_INVOCATION_RE`: on every live card the
    # result must equal the sorted de-duplicated matches of that very pattern
    pat = foundry._README_INVOCATION_RE
    for card in sorted(ROLES.glob("*.md")):
        text = card.read_text(encoding="utf-8")
        expected = tuple(sorted(set(m.group(1) for m in pat.finditer(text))))
        assert foundry.role_card_verbs(text) == expected, card.name


# =========================================================== 4. role_card_verb_gaps: drift rule


def test_b4_is_a_module_level_function_with_a_docstring_stating_the_contract() -> None:
    fn = getattr(foundry, "role_card_verb_gaps", None)
    assert inspect.isfunction(fn)
    doc = fn.__doc__ or ""
    for word in ("PURE", "TOTAL", "DORMANT"):
        assert word in doc, f"docstring must state {word}"


def test_b4_spec_example_two_sided() -> None:
    assert foundry.role_card_verb_gaps(GAP_CARD, ("directions",)) == ("retired-verb",)
    assert foundry.role_card_verb_gaps(GAP_CARD, ("directions", "retired-verb")) == ()


def test_b4_result_is_sorted_tuple_and_flag_is_never_a_gap() -> None:
    card = "foundry.py zeta\nfoundry.py alpha\nfoundry.py --help\nfoundry.py alpha"
    assert foundry.role_card_verb_gaps(card, ()) == ("alpha", "zeta")
    assert foundry.role_card_verb_gaps(card, ["alpha"]) == ("zeta",)
    assert foundry.role_card_verb_gaps(card, iter(["alpha", "zeta"])) == ()


@pytest.mark.parametrize("card", ["", None, 0, b"foundry.py x"])
@pytest.mark.parametrize("verbs", [(), ("directions",), None, "directions", [1, None]])
def test_b4_empty_or_non_str_card_returns_empty_for_any_verbs(card, verbs) -> None:
    assert foundry.role_card_verb_gaps(card, verbs) == ()


def test_b4_non_str_members_of_verbs_are_ignored() -> None:
    assert foundry.role_card_verb_gaps(GAP_CARD, (None, 42, "directions", b"retired-verb")) == \
        ("retired-verb",)
    assert foundry.role_card_verb_gaps(GAP_CARD, (None, 42, "directions", "retired-verb")) == ()


def test_b4_arguments_are_not_mutated_and_equal_inputs_are_equal() -> None:
    verbs = ["directions"]
    card = GAP_CARD[:]
    r1 = foundry.role_card_verb_gaps(card, verbs)
    r2 = foundry.role_card_verb_gaps(GAP_CARD, ["directions"])
    assert verbs == ["directions"] and card == GAP_CARD
    assert r1 == r2 == ("retired-verb",)


# =========================================================== 5. live adoption pin


def test_b5_scout_card_teaches_directions_and_dormancy_and_cli_accepts_dormancy() -> None:
    taught = foundry.role_card_verbs(_card_text("pm_scout"))
    assert "directions" in taught, taught
    assert "dormancy" in taught, taught  # RED on HEAD before this iteration's card edit
    cli = _cli_verbs()
    assert "dormancy" in cli, "retiring `dormancy` must fail here, AT the card"
    assert "directions" in cli


def test_b5_scout_card_teaches_exactly_the_two_verbs() -> None:
    # the spec measured HEAD at exactly ("directions",); the edit adds exactly one verb
    assert foundry.role_card_verbs(_card_text("pm_scout")) == ("directions", "dormancy")


# =========================================================== 6. repo-wide card-vs-CLI brake


def test_b6_the_eight_named_cards_exist() -> None:
    names = sorted(p.stem for p in ROLES.glob("*.md"))
    for stem in EIGHT_CARDS:
        assert stem in names, f"roles/{stem}.md missing"


@pytest.mark.parametrize("stem", EIGHT_CARDS)
def test_b6_every_card_teaches_only_live_cli_verbs(stem) -> None:
    gaps = foundry.role_card_verb_gaps(_card_text(stem), _cli_verbs())
    assert gaps == (), f"roles/{stem}.md teaches verb(s) the CLI does not accept: {gaps}"


def test_b6_every_card_on_disk_teaches_only_live_cli_verbs() -> None:
    verbs = _cli_verbs()
    assert len(verbs) >= 10, "CLI verb extractor went vacuous"
    for card in sorted(ROLES.glob("*.md")):
        gaps = foundry.role_card_verb_gaps(card.read_text(encoding="utf-8"), verbs)
        assert gaps == (), f"{card.name}: {gaps}"


def test_b6_non_vacuity_floor_at_least_six_cards_teach_a_verb() -> None:
    teaching = [s for s in EIGHT_CARDS if foundry.role_card_verbs(_card_text(s)) != ()]
    assert len(teaching) >= TEACHING_FLOOR, teaching


def test_b6_the_brake_fails_on_a_retired_verb_in_memory() -> None:
    # the direction that hurts: a card teaching a verb the CLI dropped is reported
    verbs = tuple(v for v in _cli_verbs() if v != "dormancy")
    assert foundry.role_card_verb_gaps(_card_text("pm_scout"), verbs) == ("dormancy",)


# =========================================================== 7. additive-dormant


def test_b7_both_modules_import_in_process() -> None:
    assert foundry.__name__ == "foundry" and dispatcher.__name__ == "dispatcher"


@pytest.mark.parametrize("fn_name", CONTROL_PATH)
def test_b7_no_control_path_function_names_either_new_function(fn_name) -> None:
    fn = getattr(foundry, fn_name, None)
    assert fn is not None, f"control-path function {fn_name} vanished"
    body = inspect.getsource(fn)
    for name in NEW_NAMES:
        assert name not in body, f"{name} must stay DORMANT, but {fn_name} references it"


def test_b7_no_cli_verb_function_names_either_new_function() -> None:
    cli_fns = [n for n in dir(foundry) if n.endswith("_cli") and inspect.isfunction(getattr(foundry, n))]
    assert len(cli_fns) >= 10, cli_fns
    for fn_name in cli_fns:
        body = inspect.getsource(getattr(foundry, fn_name))
        for name in NEW_NAMES:
            assert name not in body, f"{name} must stay DORMANT, but {fn_name} references it"


def test_b7_dispatcher_does_not_name_either_new_function() -> None:
    text = DISPATCHER_PY.read_text(encoding="utf-8")
    for name in NEW_NAMES:
        assert name not in text
        assert not hasattr(dispatcher, name)


def test_b7_no_other_role_card_names_the_new_functions() -> None:
    for card in sorted(ROLES.glob("*.md")):
        text = card.read_text(encoding="utf-8")
        for name in NEW_NAMES:
            assert name not in text, f"{name} leaked into roles/{card.name}"


FROZEN_PATHS = ("dispatcher.py", "watchdog.py", "scripts/", "README.md", "ARCHITECTURE.md",
                ".gitignore", "products/_platform/config.json")
ALLOWED_TO_MOVE = {"foundry.py", "roles/pm_scout.md", "PLATFORM_ROADMAP.md",
                   "PLATFORM_ROADMAP_ARCHIVE.md", "products/_platform/LEARNINGS.md",
                   "tests/test_iter379_behavior.py",
                   # FORCED cross-file test edit, disclosed: iteration 244's `roles/`
                   # frozen-paths brake keeps an allow-list (`roles/final.md` since 325,
                   # `roles/pm.md` since 364) and reds BY CONSTRUCTION for any spec that
                   # edits a card, so the ONLY way behavior 1 and a green suite coexist
                   # is one more allow-list member there.  Its assertion is pinned
                   # unchanged by `test_b7_iter244_brake_is_widened_not_weakened`.
                   "tests/test_iter244_behavior.py"}


def _in_this_iterations_precommit_window() -> bool:
    """True only while HEAD does NOT yet carry iteration 379's ledger row.

    WHY scope the diff-vs-HEAD checks this way instead of an every-suite
    byte-frozen guard over `<frozen paths>`: such a guard reds BY CONSTRUCTION
    inside the pre-commit window of every LATER iteration that legitimately edits
    one of the frozen paths (iteration 244's `roles/` guard has been widened three
    times for exactly that reason, and `tests/test_control_path_freeze_scope.py`
    forbids freezing README.md / roles/ at all). Keying on HEAD's ledger makes the
    scope check live exactly when it is meaningful -- this iteration's engineer,
    tester and final-gate runs before the ship commit -- and inert afterwards,
    including in the throwaway fresh clone every ship is re-verified from."""
    if not _GIT_OK:
        return False
    r = subprocess.run(["git", "show", "HEAD:PLATFORM_ROADMAP.md"], cwd=str(_ROOT),
                       capture_output=True, text=True)
    return r.returncode == 0 and f"- iter {THIS_ITER} " not in r.stdout


def _changed_vs_head() -> set:
    r = subprocess.run(["git", "diff", "HEAD", "--name-only"], cwd=str(_ROOT),
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("git diff unavailable")
    return {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}


def test_b7_frozen_paths_byte_unchanged_in_this_iterations_window() -> None:
    if not _in_this_iterations_precommit_window():
        pytest.skip("iteration 379 already shipped (or no git): scope check is inert")
    changed = _changed_vs_head()
    moved = sorted(p for p in changed
                   if any(p == f or (f.endswith("/") and p.startswith(f)) for f in FROZEN_PATHS))
    assert moved == [], f"frozen path(s) changed against HEAD: {moved}"


def test_b7_only_the_spec_named_paths_move_in_this_iterations_window() -> None:
    if not _in_this_iterations_precommit_window():
        pytest.skip("iteration 379 already shipped (or no git): scope check is inert")
    changed = _changed_vs_head()
    assert changed <= ALLOWED_TO_MOVE, sorted(changed - ALLOWED_TO_MOVE)
    assert "roles/pm_scout.md" in changed, "the card edit behavior 1 requires is absent"


def test_b7_iter244_brake_is_widened_not_weakened() -> None:
    # two-sided, from the isolated seat (iter-377 lesson): the OLD brake's verbatim
    # assertion line is still there, the scout card is now allow-listed, and every
    # OTHER card is still frozen by that brake (a widening, never a loosening).
    text = (_ROOT / "tests" / "test_iter244_behavior.py").read_text(encoding="utf-8")
    assert 'assert unexpected == [], f"frozen paths changed: {unexpected}"' in text
    m = re.search(r"^\s*allowed = \{([^}]*)\}", text, flags=re.M)
    assert m, "iter-244 allow-list literal vanished"
    listed = set(re.findall(r'"roles/([a-z_]+)\.md"', m.group(1)))
    assert "pm_scout" in listed
    for stem in ("engineer", "fix", "reporter", "reviewer", "tester"):
        assert stem not in listed, f"roles/{stem}.md must stay frozen in the 244 brake"


# =========================================================== 8. scout-card contracts preserved


def test_b8_lens_audit_still_ok() -> None:
    audit = foundry.scout_lens_audit(foundry.PM_SCOUT_LENS_POOL, _card_text("pm_scout"))
    assert audit.ok is True, audit
    assert audit.undocumented == () and audit.orphaned == ()


@pytest.mark.skipif(not _GIT_OK, reason="not inside a git work tree")
def test_b8_lens_audit_verdict_equals_heads() -> None:
    r = subprocess.run(["git", "show", "HEAD:roles/pm_scout.md"], cwd=str(_ROOT),
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("HEAD copy of the card unavailable")
    head_ok = foundry.scout_lens_audit(foundry.PM_SCOUT_LENS_POOL, r.stdout).ok
    now_ok = foundry.scout_lens_audit(foundry.PM_SCOUT_LENS_POOL, _card_text("pm_scout")).ok
    assert now_ok == head_ok


def test_b8_write_early_heading_and_anchor_phrase_remain_in_order() -> None:
    text = _card_text("pm_scout")
    assert WRITE_EARLY_HEADING in text
    assert DIRECTIONS_ANCHOR in text
    assert text.index(WRITE_EARLY_HEADING) < text.index(DIRECTIONS_ANCHOR)
    # the new sub-section cannot delay the checkpoint either
    assert text.index(WRITE_EARLY_HEADING) < text.index(NEW_HEADING)


def test_b8_candidate_heading_contract_remains() -> None:
    text = _card_text("pm_scout")
    assert text.count(CANDIDATE_HEADING + "\n") == 1
    assert text.index(NEW_HEADING) < text.index(CANDIDATE_HEADING)


# =========================================================== ledger + self-hygiene


def test_ledger_the_pm_records_for_this_iteration_are_in_the_tree() -> None:
    index = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    archive = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text(encoding="utf-8")
    assert foundry.roadmap_ledger_gaps(index, archive, (THIS_ITER,)) == [], \
        f"iteration {THIS_ITER} is missing a ledger row or archive bullet"
    assert foundry.roadmap_archive_gaps(index, archive) == [], \
        "index and archive disagree about which iterations shipped"


def test_ledger_row_is_at_most_120_chars() -> None:
    index = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    rows = [ln for ln in index.splitlines() if ln.startswith(f"- iter {THIS_ITER} ")]
    assert len(rows) == 1, rows
    assert len(rows[0]) <= 120, len(rows[0])


def test_ac_this_test_file_leak_clean_and_ascii() -> None:
    raw = THIS_TEST.read_bytes()
    assert all(b < 128 for b in raw)
    assert _leak_findings(raw.decode("ascii")) == ()


# =========================================================== RETRY-ROUND EXTENSIONS
# The first tester round was cap-killed after leaving the file above; this round
# re-checked every claim it made and closed the gaps the spec still left uncovered:
# the taught invocation is RUN (a card teaching a flag the parser rejects passes
# every literal-presence test), behavior 5 is proved TWO-SIDED from this seat
# (HEAD's card yields exactly `("directions",)` inside the pre-commit window),
# behavior 7's "only the two def lines and their own docstrings" is scanned over
# the WHOLE `foundry.py` text (not just per control-path function), and the
# spec's `python -c "import foundry, dispatcher"` runs in a FRESH interpreter.

CARD_CLASS_LINE_ANCHOR = "Quote its class per symbol"
PRODUCT_CONFIG = _ROOT / "products" / "_platform" / "config.json"


def _card_quoted_classes() -> set:
    """The dormancy class names the card itself quotes (backticked on ONE line)."""
    line = next(ln for ln in _card_text().splitlines() if CARD_CLASS_LINE_ANCHOR in ln)
    names = set(re.findall(r"`([a-z][a-z-]*)`", line))
    assert names, line
    return names


def test_b1_taught_invocation_is_accepted_by_the_cli_with_repeated_symbol_and_json() -> None:
    # Substitute the card's placeholders exactly as the seat would: <checkout> ->
    # the repo root, PRODUCT_CONFIG -> the tracked platform config, and TWO
    # `--symbol <name>` flags to exercise the `[--symbol <name> ...]` repetition.
    import json
    assert PRODUCT_CONFIG.exists(), "tracked platform config missing (fresh-clone unsafe?)"
    argv = [sys.executable, str(FOUNDRY_PY), "dormancy", "--config", str(PRODUCT_CONFIG),
            "--symbol", "role_card_verbs", "--symbol", "role_card_verb_gaps", "--json"]
    r = subprocess.run(argv, cwd=str(_ROOT), capture_output=True, text=True, timeout=90)
    assert r.returncode in (0, 1), (r.returncode, r.stderr[-800:])  # 1 = >=1 dormant, per card
    payload = json.loads(r.stdout)  # `--json` means well-formed JSON on stdout
    assert payload.get("errors") == [], payload.get("errors")
    rows = payload.get("rows")
    assert isinstance(rows, list) and len(rows) == 2, rows
    names = {row[0] for row in rows}
    assert names == set(NEW_NAMES), rows
    # every class the verb prints is a class the card teaches the seat to quote
    quoted = _card_quoted_classes()
    for name, klass in rows:
        assert klass in quoted, (name, klass, sorted(quoted))


def test_b1_card_quotes_the_four_dormancy_classes() -> None:
    assert _card_quoted_classes() == {"live", "test-only", "prose-only", "dormant"}


def test_b2_subsection_line_count_is_measured_not_assumed() -> None:
    # the walker's result must be a non-trivial body: heading + prose + the two literals
    lines = _subsection_lines(_card_text(), NEW_HEADING)
    assert len(lines) >= 4, lines
    assert sum(1 for ln in lines if ln.strip()) >= 3, lines


@pytest.mark.parametrize("verbs", [frozenset({"directions", "retired-verb"}),
                                   {"directions": 1, "retired-verb": 2}.keys(),
                                   (v for v in ("directions", "retired-verb"))])
def test_b4_any_iterable_of_verbs_is_accepted(verbs) -> None:
    assert foundry.role_card_verb_gaps(GAP_CARD, verbs) == ()


def test_b5_head_card_teaches_exactly_directions_in_this_iterations_window() -> None:
    # TWO-SIDED proof of the adoption pin from the isolated seat: before this
    # iteration's commit HEAD's card must yield exactly ("directions",) -- the
    # value the spec measured -- while the worktree card yields both verbs.
    if not _in_this_iterations_precommit_window():
        pytest.skip("iteration 379 already shipped (or no git): HEAD carries the edit")
    r = subprocess.run(["git", "show", "HEAD:roles/pm_scout.md"], cwd=str(_ROOT),
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("HEAD copy of the card unavailable")
    assert foundry.role_card_verbs(r.stdout) == ("directions",)
    assert foundry.role_card_verbs(_card_text("pm_scout")) == ("directions", "dormancy")


def test_b7_foundry_text_names_the_new_functions_only_inside_their_own_defs() -> None:
    # spec 7: `rg -n 'role_card_verbs|role_card_verb_gaps' foundry.py` shows only the
    # two `def` lines and their own docstrings/comments -- i.e. every mentioning line
    # lies inside the source span of one of the two functions themselves.
    text_lines = FOUNDRY_PY.read_text(encoding="utf-8").splitlines()
    spans = []
    for name in NEW_NAMES:
        _, start = inspect.getsourcelines(getattr(foundry, name))
        n = len(inspect.getsource(getattr(foundry, name)).splitlines())
        spans.append(range(start, start + n))
    def_lines = [i for i, ln in enumerate(text_lines, 1)
                 if re.match(r"^def (role_card_verbs|role_card_verb_gaps)\(", ln)]
    assert len(def_lines) == 2, def_lines
    outside = [f"{i}: {ln.strip()}" for i, ln in enumerate(text_lines, 1)
               if any(name in ln for name in NEW_NAMES)
               and not any(i in span for span in spans)]
    assert outside == [], "new functions are referenced outside their own defs:\n" + \
        "\n".join(outside)


def test_b7_fresh_interpreter_imports_both_modules() -> None:
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
