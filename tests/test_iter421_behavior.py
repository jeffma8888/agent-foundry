"""Iteration 421 -- BLACK-BOX behavior tests: the `test-quality` scan moves to the seat that
can run it.

`roles/tester.md` gains duty `1b.` (run `foundry.py test-quality --config ... --files
<own module>` before the `RESULT:` line and fix every finding first); `roles/reviewer.md`'s
PRECONDITION bullet is re-worded to state the stage order (reviewer runs BEFORE tester) and
hand the scan over, so the nine-per-ten `SKIPPED -- file does not exist yet` notes stop.
No `foundry.py` / `dispatcher.py` code changes.

Spec under test (products/_platform/state/iter-421/pm.md), Expected Behaviors 1-11:
   1. Duty `1b.` inserted VERBATIM between the end of duty 1 (`...cost the whole
      iteration.`) and `2. Run the FULL suite ...`; no duty renumbered.
   2. `role_card_verbs(tester) == ("test-quality",)`; `role_card_verb_gaps(...) == ()`.
   3. One tester line carries all four iter-211 INVOCATION_TOKENS; every `foundry.py
      test-quality` line carries `--files`.
   4. Line ORDER: the unique invocation line sits after `FILE FIRST` and before `Run the
      FULL suite`; the 1b block carries six pinned literals.
   5. Tester card pure ASCII, every previously pinned literal kept, last non-empty line
      byte-identical, exactly one `1b.` line.
   6. Reviewer PRECONDITION bullet replaced VERBATIM by the eight-line stage-order bullet;
      the old wording is gone.
   7. Reviewer card: one `test-quality` heading (both case readings agree); its section
      carries `[NIT]`, `[BLOCKING]`, `never`, `roles/tester.md`, `duty 1b`, `BEFORE the
      Tester`, lacks `say so in your notes` / `SKIP the scan`, is ASCII; verbs/gaps clean;
      every invocation line carries `--files`.
   8. Self-application: the carded command on THIS module exits 0 with `verdict: clean`;
      `--json` says files_scanned 1 / total_findings 0 / clean True / exit_code 0.
   9. Two-sided proof in tmp_path: a real-asserting file -> 0 findings, exit 0; an
      assertion-free + constant-assert + always-skipped file -> each lens >= 1, exit 1.
  10. The three oracles are present and behave; `import foundry, dispatcher` OK in a fresh
      interpreter; `dispatcher.py` carries zero `test-quality`.
  11. Roadmap index row (<= 120 chars) + archive bullet for iter 421; `roadmap_ledger_gaps`
      == [] on the worktree.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-421 PM spec, the conventions
of `tests/` (the `_ROOT`/sys.path + literals-pinned-here + `_write_cfg` + tmp_path fixture
idiom of `tests/test_iter211_behavior.py`, the `lowered` literal idiom of
`tests/test_iter242_behavior.py`), and the product's OWN OBSERVABLE surface: running the
CLI, calling public oracles, and reading the two role cards, which are THIS iteration's
user-visible artifacts.  `foundry.py` text is passed to the public `foundry_cli_verbs`
oracle only, never read by the author.  `engineer.md`, `reviewer.md` (the report),
`IMPLEMENTATION.patch` and `git diff` were NOT read.

Offline and deterministic: scanner fixtures are synthesised in `tmp_path`; the only
subprocesses are the carded scan command (Behaviors 8-9) and the fresh-interpreter import
probe (Behavior 10), all with `sys.executable` and paths derived from `_ROOT` -- no absolute
machine path appears as a literal.  No assertion reads a gitignored path, counts files in
the ambient tree, or compares the worktree against git HEAD.

Ambiguity notes for the PM (tested the most reasonable reading):
  * Behavior 9 names the lenses `assertion_free` / `constant_assert` / `always_skipped`, but
    `test-quality --json` prints the counts as `weak_findings` / `constant_findings` /
    `skipped_findings` (read from the JSON as the spec instructs); those keys are pinned.
  * Behavior 10's `git diff --stat HEAD -- foundry.py dispatcher.py` clause and Behavior 6's
    "other 62 lines byte-identical" clause are HEAD-relative: a shipped test on them is
    vacuous in a fresh clone and would redden every FUTURE iteration that edits those files
    before its commit (the iter-244 freeze cost).  They are measured once in the tester
    report instead; this module pins the durable parts (oracles present and behaving,
    imports, zero `test-quality` in dispatcher.py, verbatim bullet, old wording absent).
  * Behavior 5's `green` and `expected behavior` appear upper-cased in the card, so they are
    pinned case-insensitively, exactly as iter 242 pins them.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

THIS_ITER = 421
GAP = "GAP-023"
VERB = "test-quality"
TESTER_CARD = _ROOT / "roles" / "tester.md"
REVIEWER_CARD = _ROOT / "roles" / "reviewer.md"
ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
DISPATCHER = _ROOT / "dispatcher.py"
FOUNDRY_SRC = _ROOT / "foundry.py"
PRODUCT_CONFIG = _ROOT / "products" / "_platform" / "config.json"
THIS_MODULE = pathlib.Path(__file__).resolve()

# Pinned HERE (never derived from the artifact under test) so a silent rewording is caught.
INVOCATION_TOKENS = ("foundry.py test-quality", "--config", "--files", "tests/test_iter")
DUTY_1_END = "and cost the whole iteration."
DUTY_2_LINE = "2. Run the FULL suite (the quality-check command from Context)."
TESTER_LAST_LINE = (
    "- Append notable lessons to the foundry learnings log as `- [TEST iterNN] ...`."
)
DUTY_1B_LINES = (
    "1b. SCAN THE MODULE, do not eyeball it -- once the file covers the behaviors and",
    "   BEFORE you write the `RESULT:` line, run the foundry's offline scan for tests",
    "   that cannot fail (assertion-free, constant assert, always skipped), SCOPED to",
    "   your own module and never repo-wide:",
    "   `python3 <checkout>/foundry.py test-quality --config <PRODUCT_CONFIG> --files "
    "<checkout>/tests/test_iterNN_behavior.py`",
    "   `<checkout>` is the PARENT of the `roles/` directory this card lives in;",
    "   `<PRODUCT_CONFIG>` is the path on the `- Product config` line of your prompt's",
    "   `## Context` block, taken verbatim; keep `--files` ABSOLUTE (`run_stage` passes",
    "   no `cwd=`). Exit 0 prints `verdict: clean` -- quote that line in your report.",
    "   Exit 1 names each finding as `<file> :: <test>`: fix every one in YOUR module",
    "   before reporting, because a test that cannot fail verifies nothing. Running",
    "   the product's CLI is inside your isolation contract; reading its source is",
    "   not. The scan takes under a second on one module, so it never delays a",
    "   checkpoint, and the Reviewer runs BEFORE you, so this scan is yours alone.",
)
BLOCK_1B_LITERALS = (
    "verdict: clean", "RESULT:", "never repo-wide", "Exit 1", "fix every one",
    "isolation contract",
)
TESTER_KEPT_LITERALS = (
    "PROGRESS: CHECKPOINT", "tests/test_iter", "RESULT: PASS", "RESULT: FAIL",
    "RESULT: BLOCKED", "cut short",
)
TESTER_KEPT_CI_LITERALS = ("file first", "green", "expected behavior")

PRECONDITION_LINES = (
    "- PRECONDITION: the pipeline runs you BEFORE the Tester (`run_stage` order: engineer ->",
    "  reviewer -> tester -> final), so in a normal review that module does not exist yet and",
    "  the scan is the TESTER's step (`roles/tester.md`, duty 1b), not yours. When the file is",
    "  absent, skip the scan WITHOUT a finding and WITHOUT a SKIPPED note: nothing was missed.",
    "  Run it here ONLY when the module already exists on disk. A path the scanner cannot open",
    "  is reported as a `parse errors:` line and exits 1 -- a false alarm, never a finding. Keep",
    "  `--files` ABSOLUTE: `run_stage` passes no `cwd=`, so a relative path raises that identical",
    "  ABSENT signature from any stage cwd and would hide a scan that never ran.",
)
OLD_PRECONDITION_START = "- PRECONDITION: if that file does not exist under"
REVIEWER_SECTION_REQUIRED = (
    "[NIT]", "[BLOCKING]", "roles/tester.md", "duty 1b", "BEFORE the Tester",
)
REVIEWER_SECTION_FORBIDDEN = ("say so in your notes", "SKIP the scan")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_DUTY_START = re.compile(r"^(\d+[a-z]?)\. ")

# --- scanner fixtures (synthesised in tmp_path; NEVER collected by pytest) -----------------
GOOD_SRC = (
    "def test_sum_of_a_range_is_computed_then_compared():\n"
    "    total = sum(range(4))\n"
    "    assert total == 6\n"
)
BAD_SRC = (
    "import pytest\n"
    "\n"
    "\n"
    "def test_a_has_no_assert_at_all():\n"
    "    value = 1 + 1\n"
    "\n"
    "\n"
    "def test_b_only_assert_is_a_literal_constant():\n"
    "    assert True\n"
    "\n"
    "\n"
    "@pytest.mark.skip(reason=\"unconditional skip fixture\")\n"
    "def test_c_is_unconditionally_skipped():\n"
    "    value = 2\n"
    "    assert value == 2\n"
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _lines(path: pathlib.Path) -> list[str]:
    return path.read_text().splitlines()


def _only_index(lines: list[str], needle: str) -> int:
    hits = [i for i, ln in enumerate(lines) if needle in ln]
    assert len(hits) == 1, f"expected exactly one line containing {needle!r}, got {hits}"
    return hits[0]


def _sections(path: pathlib.Path) -> list[tuple[str, str]]:
    """[(heading_line, section_text)] for every markdown heading in a card."""
    lines = _lines(path)
    heads = [i for i, ln in enumerate(lines) if _HEADING.match(ln)]
    out = []
    for n, i in enumerate(heads):
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        out.append((lines[i], "\n".join(lines[i:end])))
    return out


def _verb_sections(path: pathlib.Path, case_sensitive: bool) -> list[tuple[str, str]]:
    needle = VERB if case_sensitive else VERB.lower()
    return [(h, s) for h, s in _sections(path)
            if needle in (h if case_sensitive else h.lower())]


def _cli_verbs() -> tuple[str, ...]:
    return foundry.foundry_cli_verbs(FOUNDRY_SRC.read_text())


def _run_scan(cfg: pathlib.Path, target: pathlib.Path, *extra: str):
    """The carded command, verbatim shape: `python3 <checkout>/foundry.py test-quality
    --config <cfg> --files <abs path>` run from the repo root via sys.executable."""
    argv = [sys.executable, str(FOUNDRY_SRC), VERB, "--config", str(cfg),
            "--files", str(target), *extra]
    return subprocess.run(argv, cwd=str(_ROOT), capture_output=True, text=True, timeout=120)


def _scan_json(cfg: pathlib.Path, target: pathlib.Path):
    proc = _run_scan(cfg, target, "--json")
    assert proc.stdout.strip(), f"--json must print a document (stderr={proc.stderr!r})"
    return proc.returncode, json.loads(proc.stdout)


def _write_cfg(tmp_path: pathlib.Path) -> pathlib.Path:
    """A minimal product config whose repo is an EMPTY tmp dir, so any finding can only
    have come from the --files path, never from an ambient tree."""
    repo = tmp_path / "cfgrepo"
    (repo / "tests").mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    out = tmp_path / "config.json"
    out.write_text(json.dumps(data))
    return out


def _fixture(tmp_path: pathlib.Path, src: str, name: str) -> pathlib.Path:
    p = tmp_path / "outside" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src)
    return p


# ==========================================================================
# Behavior 1 -- duty 1b inserted VERBATIM, in place, nothing renumbered
# ==========================================================================
def test_b1_duty_1b_block_is_the_verbatim_fourteen_lines():
    lines = _lines(TESTER_CARD)
    start = _only_index(lines, DUTY_1B_LINES[0])
    block = lines[start:start + len(DUTY_1B_LINES)]
    assert block == list(DUTY_1B_LINES), (
        f"{GAP}: duty 1b must be the spec's fourteen lines verbatim; first divergence: "
        + repr(next(((a, b) for a, b in zip(block, DUTY_1B_LINES) if a != b),
                    ("<length>", (len(block), len(DUTY_1B_LINES)))))
    )


def test_b1_duty_1b_sits_between_the_end_of_duty_1_and_duty_2():
    lines = _lines(TESTER_CARD)
    start = _only_index(lines, DUTY_1B_LINES[0])
    assert lines[start - 1].endswith(DUTY_1_END), (
        f"the line before 1b must be the end of duty 1 ({DUTY_1_END!r}); got {lines[start - 1]!r}"
    )
    after = lines[start + len(DUTY_1B_LINES)]
    assert after == DUTY_2_LINE, f"the line after the 1b block must be {DUTY_2_LINE!r}; got {after!r}"


def test_b1_no_existing_duty_is_renumbered():
    labels = [m.group(1) for m in map(_DUTY_START.match, _lines(TESTER_CARD)) if m]
    assert labels == ["1", "1b", "2", "3"], (
        f"duties must read 1, 1b, 2, 3 in order (no renumbering); got {labels}"
    )


def test_b1_duty_2_and_duty_3_keep_their_text():
    lines = _lines(TESTER_CARD)
    assert DUTY_2_LINE in lines, "duty 2 line must be byte-identical"
    threes = [ln for ln in lines if ln.startswith("3. ")]
    assert threes == ["3. Write your output file (`tester.md` in the state dir):"], threes


# ==========================================================================
# Behavior 2 -- the public verb oracles see exactly `test-quality`
# ==========================================================================
def test_b2_tester_card_names_exactly_the_test_quality_verb():
    verbs = foundry.role_card_verbs(TESTER_CARD.read_text())
    assert verbs == (VERB,), f"roles/tester.md must name exactly {VERB!r}; got {verbs!r}"


def test_b2_tester_card_has_no_verb_gap_against_the_live_cli():
    gaps = foundry.role_card_verb_gaps(TESTER_CARD.read_text(), _cli_verbs())
    assert gaps == (), f"every verb the tester card teaches must exist in the CLI; gaps={gaps!r}"


# ==========================================================================
# Behavior 3 -- the scoped invocation, and never repo-wide
# ==========================================================================
def test_b3_one_tester_line_carries_all_four_invocation_tokens():
    lines = _lines(TESTER_CARD)
    hits = [ln for ln in lines if all(tok in ln for tok in INVOCATION_TOKENS)]
    assert hits, (
        "roles/tester.md must carry a line with ALL of "
        f"{INVOCATION_TOKENS}; candidates: "
        + repr([(ln, [t for t in INVOCATION_TOKENS if t not in ln])
                for ln in lines if VERB in ln][:6])
    )


def test_b3_every_test_quality_command_line_in_tester_card_is_file_scoped():
    offenders = [ln for ln in _lines(TESTER_CARD)
                 if "foundry.py test-quality" in ln and "--files" not in ln]
    assert offenders == [], f"an unscoped repo-wide invocation would report old findings: {offenders}"


# ==========================================================================
# Behavior 4 -- line ORDER inside the card, and the 1b block's literals
# ==========================================================================
def test_b4_invocation_line_sits_after_file_first_and_before_full_suite():
    lines = _lines(TESTER_CARD)
    invocation = _only_index(lines, "foundry.py test-quality")
    file_first = next(i for i, ln in enumerate(lines) if "FILE FIRST" in ln)
    full_suite = next(i for i, ln in enumerate(lines) if "Run the FULL suite" in ln)
    assert file_first < invocation < full_suite, (
        f"order must be FILE FIRST ({file_first}) < invocation ({invocation}) < "
        f"Run the FULL suite ({full_suite})"
    )


def _block_1b() -> str:
    lines = _lines(TESTER_CARD)
    start = _only_index(lines, DUTY_1B_LINES[0])
    end = next(i for i, ln in enumerate(lines) if ln.startswith("2. Run the FULL suite"))
    assert start < end, (start, end)
    return "\n".join(lines[start:end])


@pytest.mark.parametrize("literal", BLOCK_1B_LITERALS)
def test_b4_the_1b_block_carries_each_pinned_literal(literal):
    block = _block_1b()
    assert literal in block, f"the 1b block must contain {literal!r}; block was:\n{block}"


# ==========================================================================
# Behavior 5 -- ASCII, kept literals, last line, exactly one 1b
# ==========================================================================
def test_b5_tester_card_is_pure_ascii():
    text = TESTER_CARD.read_text()
    bad = [(i + 1, ln) for i, ln in enumerate(text.splitlines()) if not ln.isascii()]
    assert bad == [], f"roles/tester.md must stay pure ASCII; non-ASCII lines: {bad}"
    assert text.encode("ascii")  # would raise UnicodeEncodeError on any non-ASCII byte


@pytest.mark.parametrize("literal", TESTER_KEPT_LITERALS)
def test_b5_tester_card_keeps_each_case_sensitive_literal(literal):
    text = TESTER_CARD.read_text()
    assert literal in text, f"previously pinned literal {literal!r} must survive the edit"


@pytest.mark.parametrize("literal", TESTER_KEPT_CI_LITERALS)
def test_b5_tester_card_keeps_each_case_insensitive_literal(literal):
    lowered = TESTER_CARD.read_text().lower()
    assert literal in lowered, f"previously pinned literal {literal!r} (any case) must survive"


def test_b5_tester_card_last_non_empty_line_is_unchanged():
    non_empty = [ln for ln in _lines(TESTER_CARD) if ln.strip()]
    assert non_empty[-1] == TESTER_LAST_LINE, f"last non-empty line moved: {non_empty[-1]!r}"


def test_b5_tester_card_has_exactly_one_1b_line():
    starts = [ln for ln in _lines(TESTER_CARD) if ln.startswith("1b.")]
    assert len(starts) == 1, f"exactly one line may start with '1b.'; got {starts}"


# ==========================================================================
# Behavior 6 -- the reviewer PRECONDITION bullet, verbatim, old wording gone
# ==========================================================================
def test_b6_reviewer_precondition_bullet_is_the_verbatim_eight_lines():
    lines = _lines(REVIEWER_CARD)
    start = _only_index(lines, PRECONDITION_LINES[0])
    block = lines[start:start + len(PRECONDITION_LINES)]
    assert block == list(PRECONDITION_LINES), (
        f"{GAP}: the PRECONDITION bullet must be the spec's eight lines verbatim; first "
        "divergence: "
        + repr(next(((a, b) for a, b in zip(block, PRECONDITION_LINES) if a != b),
                    ("<length>", (len(block), len(PRECONDITION_LINES)))))
    )


def test_b6_reviewer_card_has_exactly_one_precondition_bullet_and_no_old_wording():
    text = REVIEWER_CARD.read_text()
    starts = [ln for ln in text.splitlines() if ln.startswith("- PRECONDITION:")]
    assert len(starts) == 1, f"exactly one PRECONDITION bullet; got {starts}"
    assert OLD_PRECONDITION_START not in text, "the old PRECONDITION opening must be gone"
    assert "scan that never ran." in text, "the bullet's closing sentence must be present"


def test_b6_precondition_bullet_follows_the_invocation_line_inside_the_verb_section():
    lines = _lines(REVIEWER_CARD)
    invocation = _only_index(lines, "foundry.py test-quality")
    bullet = _only_index(lines, PRECONDITION_LINES[0])
    assert invocation < bullet, (invocation, bullet)
    secs = _verb_sections(REVIEWER_CARD, case_sensitive=True)
    assert len(secs) == 1, [h for h, _ in secs]
    assert "\n".join(PRECONDITION_LINES) in secs[0][1], "bullet must live in the verb section"


# ==========================================================================
# Behavior 7 -- the reviewer's test-quality section, after the edit
# ==========================================================================
def test_b7_exactly_one_test_quality_heading_in_both_case_readings():
    strict = [h for h, _ in _verb_sections(REVIEWER_CARD, case_sensitive=True)]
    loose = [h for h, _ in _verb_sections(REVIEWER_CARD, case_sensitive=False)]
    assert len(strict) == 1, f"exactly one heading must name {VERB!r}; got {strict}"
    assert strict == loose, f"case-sensitive={strict} case-insensitive={loose}"


def _reviewer_verb_section() -> str:
    secs = _verb_sections(REVIEWER_CARD, case_sensitive=True)
    assert len(secs) == 1, [h for h, _ in secs]
    return secs[0][1]


@pytest.mark.parametrize("literal", REVIEWER_SECTION_REQUIRED)
def test_b7_section_carries_each_required_literal(literal):
    section = _reviewer_verb_section()
    assert literal in section, f"the {VERB} section must contain {literal!r}; was:\n{section}"


def test_b7_section_still_says_never():
    section = _reviewer_verb_section()
    assert "never" in section.lower(), f"the section must keep 'never' (any case):\n{section}"


@pytest.mark.parametrize("literal", REVIEWER_SECTION_FORBIDDEN)
def test_b7_section_dropped_each_old_phrase(literal):
    section = _reviewer_verb_section()
    assert literal not in section, f"old wording {literal!r} must be gone from:\n{section}"


def test_b7_section_is_pure_ascii():
    section = _reviewer_verb_section()
    bad = [ln for ln in section.splitlines() if not ln.isascii()]
    assert bad == [], f"the {VERB} section must be ASCII; offenders: {bad}"


def test_b7_reviewer_card_verbs_include_test_quality_with_no_gap():
    text = REVIEWER_CARD.read_text()
    verbs = foundry.role_card_verbs(text)
    assert VERB in verbs, f"reviewer card must still name {VERB!r}; got {verbs!r}"
    gaps = foundry.role_card_verb_gaps(text, _cli_verbs())
    assert gaps == (), f"reviewer card verb gaps must be empty; got {gaps!r}"


def test_b7_every_test_quality_command_line_in_reviewer_card_is_file_scoped():
    offenders = [ln for ln in _lines(REVIEWER_CARD)
                 if "foundry.py test-quality" in ln and "--files" not in ln]
    assert offenders == [], f"unscoped invocation lines in reviewer card: {offenders}"


# ==========================================================================
# Behavior 8 -- self-application: THIS module passes the carded scan
# ==========================================================================
def test_b8_this_module_scans_clean_in_human_mode():
    proc = _run_scan(PRODUCT_CONFIG, THIS_MODULE)
    assert proc.returncode == 0, (
        f"{GAP}: this module must pass the step the tester card mandates; "
        f"exit={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "verdict: clean" in proc.stdout.splitlines(), (
        f"stdout must carry the line 'verdict: clean'; stdout={proc.stdout!r}"
    )


def test_b8_this_module_scans_clean_in_json_mode():
    code, doc = _scan_json(PRODUCT_CONFIG, THIS_MODULE)
    assert code == 0, doc
    assert doc["files_scanned"] == 1, doc
    assert doc["total_findings"] == 0, doc
    assert doc["clean"] is True, doc
    assert doc["exit_code"] == 0, doc


# ==========================================================================
# Behavior 9 -- two-sided proof of the same command in tmp_path
# ==========================================================================
def test_b9_the_carded_command_is_silent_on_a_real_asserting_test(tmp_path):
    cfg = _write_cfg(tmp_path)
    good = _fixture(tmp_path, GOOD_SRC, "test_good_behavior.py")
    code, doc = _scan_json(cfg, good)
    assert code == 0, f"{GAP}: a real assertion must not fire any lens; exit={code} doc={doc}"
    assert doc["total_findings"] == 0, doc
    assert doc["files_scanned"] == 1, doc
    assert doc["clean"] is True, doc
    assert doc["exit_code"] == 0, doc


def test_b9_the_carded_command_fires_each_lens_on_the_bad_fixture(tmp_path):
    cfg = _write_cfg(tmp_path)
    bad = _fixture(tmp_path, BAD_SRC, "test_bad_behavior.py")
    code, doc = _scan_json(cfg, bad)
    assert code == 1, f"{GAP}: a test that cannot fail must be named; exit={code} doc={doc}"
    # Key names as `test-quality --json` prints them (read from the JSON, not guessed).
    assert doc["weak_findings"] >= 1, f"assertion-free lens must fire: {doc}"
    assert doc["constant_findings"] >= 1, f"constant-assert lens must fire: {doc}"
    assert doc["skipped_findings"] >= 1, f"always-skipped lens must fire: {doc}"
    assert doc["clean"] is False, doc
    assert doc["exit_code"] == 1, doc
    assert doc["files_scanned"] == 1, doc


def test_b9_bad_fixture_names_each_offending_test_by_lens(tmp_path):
    cfg = _write_cfg(tmp_path)
    bad = _fixture(tmp_path, BAD_SRC, "test_bad_behavior.py")
    _, doc = _scan_json(cfg, bad)
    named = {lens: {f["test"] for f in doc[lens]["findings"]}
             for lens in ("weak", "constant", "skipped")}
    assert "test_a_has_no_assert_at_all" in named["weak"], named
    assert "test_b_only_assert_is_a_literal_constant" in named["constant"], named
    assert "test_c_is_unconditionally_skipped" in named["skipped"], named


# ==========================================================================
# Behavior 10 -- oracles unchanged in behavior; no brain change
# ==========================================================================
def test_b10_the_three_oracles_are_present_and_behave():
    verbs = _cli_verbs()
    assert isinstance(verbs, tuple) and VERB in verbs, verbs
    assert all(isinstance(v, str) for v in verbs), verbs
    assert foundry.role_card_verbs("") == ()
    assert foundry.role_card_verb_gaps("", verbs) == ()
    probe = "run `python3 <checkout>/foundry.py no-such-verb-xyz --config C`"
    assert foundry.role_card_verbs(probe) == ("no-such-verb-xyz",)
    assert foundry.role_card_verb_gaps(probe, verbs) == ("no-such-verb-xyz",)


def test_b10_foundry_and_dispatcher_import_in_a_fresh_interpreter():
    proc = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                          cwd=str(_ROOT), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, f"import failed: {proc.stderr!r}"


def test_b10_dispatcher_carries_zero_test_quality_occurrences():
    text = DISPATCHER.read_text()
    assert text.count(VERB) == 0, f"dispatcher.py must not mention {VERB!r}"
    assert text.count("test_quality") == 0, "dispatcher.py must not mention test_quality"


# ==========================================================================
# Behavior 11 -- roadmap ledger row + archive bullet
# ==========================================================================
def test_b11_roadmap_index_holds_exactly_one_short_row_for_this_iteration():
    rows = [ln for ln in _lines(ROADMAP) if ln.startswith(f"- iter {THIS_ITER} -- ")]
    assert len(rows) == 1, f"exactly one index row for iter {THIS_ITER}; got {rows}"
    assert len(rows[0]) <= 120, f"row must be <= 120 chars, is {len(rows[0])}: {rows[0]!r}"


def test_b11_roadmap_archive_holds_exactly_one_bullet_for_this_iteration():
    bullets = [ln for ln in _lines(ARCHIVE) if ln.startswith(f"- **iter {THIS_ITER} -- ")]
    assert len(bullets) == 1, f"exactly one archive bullet for iter {THIS_ITER}; got {len(bullets)}"


def test_b11_roadmap_ledger_gaps_is_empty_for_this_iteration():
    gaps = foundry.roadmap_ledger_gaps(ROADMAP.read_text(), ARCHIVE.read_text(), (THIS_ITER,))
    assert gaps == [], f"roadmap_ledger_gaps must be [] for iter {THIS_ITER}; got {gaps}"
