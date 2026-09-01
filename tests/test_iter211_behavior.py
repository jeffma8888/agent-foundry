"""Black-box behaviour tests for iter 211 -- `roles/reviewer.md` gains ONE ADVISORY step that
runs the already-shipped composite `test-quality` scan, scoped with `--files` to the
iteration's own `tests/test_iterNN_behavior.py`, reported as a `[NIT]` that can never block.

Spec: products/_platform/state/iter-211/pm.md, Expected Behaviors 1-7.

  1. The card names the scoped invocation: one line carrying all four of
     `foundry.py test-quality`, `--config`, `--files`, `tests/test_iter`.
  2. The card fixes the verdict class as ADVISORY: in the section introduced by the heading
     naming `test-quality`, the token `[NIT]` occurs and a statement occurs that such a
     finding is never a `[BLOCKING]` finding.
  3. Silent-on-good (the load-bearing negative arm): a tmp_path file whose single test
     computes a value and asserts a non-constant comparison -> exit 0, and --json reports
     total_findings == 0, files_scanned == 1, clean is True.
  4. Fires-on-bad, per lens: a tmp_path file with (a) an assertion-free test, (b) a test whose
     only assert is a literal constant, (c) an unconditionally skipped test -> exit 1, and
     --json reports weak_findings >= 1, constant_findings >= 1, skipped_findings >= 1.
  5. --files honours paths OUTSIDE the config repo's own tests/ dir: files_scanned == 1 for
     both fixtures, proving the reviewer's scoping is real and no ambient tree is consulted.
  6. The --json `exit_code` equals the process exit code (0 for good, 1 for bad).
  7. The consumer lives on the PROMPT SURFACE, not in the brain: dispatcher.py contains no
     occurrence of `test-quality` / `test_quality`, and foundry + dispatcher both import
     cleanly in a fresh interpreter -- so no control flow and no resume semantics changed.
  Plus Acceptance-Criteria oracles: this iteration's own new test module scans CLEAN under
  the very command the card now asks the reviewer to run, and the iter-211 roadmap ledger row
  (<=120 chars) + archive bullet both exist.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-211 PM spec's Expected Behaviors and
Acceptance Criteria, the conventions of tests/ (the _ROOT/sys.path + literals-pinned-here +
_write_cfg + _capture shape of tests/test_iter170_behavior.py), the roadmap files that an
Acceptance Criterion makes a deliverable, and the product's OBSERVABLE surface -- CALLING the
shipped CLI and reading the shipped role card, which is itself this iteration's user-visible
artifact. NOT read: the implementation source of foundry.py / dispatcher.py, engineer.md,
reviewer.md, fix_review.md, IMPLEMENTATION.patch, or any git diff. (Disclosure: the bounded
foundry-learnings digest injected into this stage prompt contained [ENG/REV/FIX iter211]
entries I did not seek and cannot unread; no assertion below was derived from a named
implementation detail -- every clause traces to a numbered behavior or an acceptance
criterion. Behaviors 1-2 and 7 necessarily READ shipped artifact bytes, which is the
observable output the spec makes assertable; no foundry.py source is read anywhere.)

Offline and deterministic: every scanner fixture is synthesised in tmp_path, the real repo is
never mutated, no assertion depends on a file count or on gitignored local state (the iter-154
"passes only on this machine" trap), and the only subprocess is the fresh-interpreter import
probe Expected Behavior 7 requires.
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

THIS_ITER = 211
GAP = "GAP-023"
ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
REVIEWER_CARD = _ROOT / "roles" / "reviewer.md"
DISPATCHER = _ROOT / "dispatcher.py"

VERB = "test-quality"
# Pinned HERE (never imported from the artifact under test) so a silent rewording is caught.
INVOCATION_TOKENS = ("foundry.py test-quality", "--config", "--files", "tests/test_iter")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

# --- scanner fixtures (synthesised in tmp_path; NEVER collected by pytest) -----------------
# One test that COMPUTES a value and asserts a non-constant comparison on it: no lens may fire.
GOOD_SRC = (
    "def test_sum_of_a_range_is_computed_then_compared():\n"
    "    total = sum(range(4))\n"
    "    assert total == 6\n"
)
# (a) assertion-free, (b) only assert is a literal constant, (c) unconditional skip.
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
def _capture(fn):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = fn()
        except SystemExit as exc:          # argparse / early exit
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def _write_cfg(tmp_path, name="config.json"):
    """A minimal product config whose repo is an EMPTY tmp dir -- so any finding below can
    only have come from the --files path, never from an ambient tree."""
    repo = tmp_path / "cfgrepo"
    (repo / "tests").mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    out = tmp_path / name
    out.write_text(json.dumps(data))
    return out


def _fixture(tmp_path, src, name):
    """Write a scanner fixture OUTSIDE the config repo (Expected Behavior 5)."""
    p = tmp_path / "outside" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src)
    return p


def _scan_json(cfg, target):
    """Run the shipped composite verb exactly as the reviewer card asks, and return
    (process exit code, parsed --json document)."""
    code, out, err = _capture(lambda: foundry.main(
        [VERB, "--config", str(cfg), "--files", str(target), "--json"]))
    assert out.strip(), f"--json must print a document (stderr={err!r})"
    return code, json.loads(out)


def _card_sections(path=None):
    """[(heading_line, section_text)] for every markdown heading in the reviewer card."""
    lines = (path or REVIEWER_CARD).read_text().splitlines()
    heads = [i for i, ln in enumerate(lines) if _HEADING.match(ln)]
    out = []
    for n, i in enumerate(heads):
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        out.append((lines[i], "\n".join(lines[i:end])))
    return out


def _test_quality_sections(case_sensitive: bool, path=None):
    needle = VERB if case_sensitive else VERB.lower()
    return [(h, s) for h, s in _card_sections(path)
            if needle in (h if case_sensitive else h.lower())]


def _is_advisory(section: str) -> bool:
    """The Behavior-2 predicate, in one place so the guard below can falsify it."""
    return ("[NIT]" in section and "[BLOCKING]" in section
            and "never" in section.lower())


# ==========================================================================
# Behavior 1 -- the card names the SCOPED invocation (never repo-wide)
# ==========================================================================
def test_b1_reviewer_card_names_the_file_scoped_test_quality_invocation():
    lines = REVIEWER_CARD.read_text().splitlines()
    hits = [ln for ln in lines if all(tok in ln for tok in INVOCATION_TOKENS)]
    assert hits, (
        "roles/reviewer.md must carry at least one line naming the scoped invocation, i.e. "
        f"one line containing ALL of {INVOCATION_TOKENS}; missing tokens per candidate line: "
        + repr([(ln, [t for t in INVOCATION_TOKENS if t not in ln])
                for ln in lines if "test-quality" in ln][:6])
    )


def test_b1_every_scan_command_line_in_the_card_is_file_scoped():
    """'never repo-wide' arm: a line that INVOKES the verb must carry --files. Lines that
    merely discuss the verb in prose are not command lines and are not judged here."""
    offenders = [ln for ln in REVIEWER_CARD.read_text().splitlines()
                 if "foundry.py test-quality" in ln and "--files" not in ln]
    assert offenders == [], (
        f"an unscoped repo-wide invocation would report pre-existing findings: {offenders}"
    )


# ==========================================================================
# Behavior 2 -- the verdict class is fixed as ADVISORY, at the point of use
# ==========================================================================
def test_b2_the_test_quality_section_fixes_the_verdict_class_as_advisory():
    secs = _test_quality_sections(case_sensitive=False)
    assert len(secs) == 1, (
        "exactly one section of roles/reviewer.md must be introduced by a heading naming "
        f"{VERB!r}; found {len(secs)}: {[h for h, _ in secs]}"
    )
    heading, section = secs[0]
    assert _is_advisory(section), (
        f"the {VERB} section must fix the verdict class as advisory; heading={heading!r} "
        f"[NIT]={'[NIT]' in section} [BLOCKING]={'[BLOCKING]' in section} "
        f"never={'never' in section.lower()}; section was:\n{section}"
    )
    assert "[NIT]" in section, (
        f"the {VERB} section must name the advisory verdict token [NIT]; section was:\n{section}"
    )
    assert "[BLOCKING]" in section, (
        f"the {VERB} section must name [BLOCKING] to exclude it; section was:\n{section}"
    )
    assert "never" in section.lower(), (
        "the section must state that such a finding is NEVER a [BLOCKING] finding; "
        f"section was:\n{section}"
    )


def test_b2_heading_search_agrees_case_sensitively_and_case_insensitively():
    """The spec quotes `test-quality` as a literal, but a tester may reasonably search either
    way; a card whose heading only matches one of the two readings would pass or fail on which
    variant the tester happened to write, which the engineer cannot control. Require agreement."""
    strict = [h for h, _ in _test_quality_sections(case_sensitive=True)]
    loose = [h for h, _ in _test_quality_sections(case_sensitive=False)]
    assert strict == loose, (
        "the heading naming the verb must match BOTH readings (ship the spec literal's exact "
        f"bytes): case-sensitive={strict} case-insensitive={loose}"
    )


# ==========================================================================
# Behavior 3 -- SILENT ON GOOD (the load-bearing negative arm)
# ==========================================================================
def test_b3_scoped_scan_is_silent_on_a_good_test_file(tmp_path):
    cfg = _write_cfg(tmp_path)
    good = _fixture(tmp_path, GOOD_SRC, "test_iter_good_behavior.py")
    code, doc = _scan_json(cfg, good)
    assert code == 0, (
        f"{GAP}: a scan that cannot stay silent on a genuinely-asserting test would make the "
        f"reviewer's advisory step fire on every iteration; exit={code} doc={doc}"
    )
    assert doc["total_findings"] == 0, (
        f"{GAP}: total_findings must be 0 on a good file, got {doc['total_findings']}: {doc}"
    )
    assert doc["files_scanned"] == 1, doc
    assert doc["clean"] is True, f"clean must be the boolean True, got {doc['clean']!r}: {doc}"


# ==========================================================================
# Behavior 4 -- FIRES ON BAD, per lens
# ==========================================================================
def test_b4_scoped_scan_fires_on_each_lens(tmp_path):
    cfg = _write_cfg(tmp_path)
    bad = _fixture(tmp_path, BAD_SRC, "test_iter_bad_behavior.py")
    code, doc = _scan_json(cfg, bad)
    assert code == 1, (
        f"{GAP}: an assertion-free / constant-assert / unconditionally-skipped test passes the "
        f"suite, so the scan is the only oracle; exit={code} doc={doc}"
    )
    for key in ("weak_findings", "constant_findings", "skipped_findings"):
        assert doc[key] >= 1, f"{key} must be >=1 on the three-lens fixture, got {doc[key]}: {doc}"
    assert doc["clean"] is False, f"clean must be False when findings exist: {doc}"


# ==========================================================================
# Behavior 5 -- --files honours paths OUTSIDE the config repo's tests/ dir
# ==========================================================================
@pytest.mark.parametrize("src,name", [(GOOD_SRC, "good"), (BAD_SRC, "bad")])
def test_b5_files_scoping_is_real_for_a_path_outside_the_config_repo(tmp_path, src, name):
    cfg = _write_cfg(tmp_path)
    target = _fixture(tmp_path, src, f"test_iter_{name}_outside.py")
    assert not str(target).startswith(str(tmp_path / "cfgrepo")), (
        "fixture precondition: the target must live OUTSIDE the config repo"
    )
    _, doc = _scan_json(cfg, target)
    assert doc["files_scanned"] == 1, (
        f"exactly the one --files path must be scanned (no ambient tree), got "
        f"{doc['files_scanned']}: {doc}"
    )


# ==========================================================================
# Behavior 6 -- the JSON exit_code equals the process exit code
# ==========================================================================
@pytest.mark.parametrize("src,expected", [(GOOD_SRC, 0), (BAD_SRC, 1)])
def test_b6_json_exit_code_equals_the_process_exit_code(tmp_path, src, expected):
    cfg = _write_cfg(tmp_path)
    target = _fixture(tmp_path, src, "test_iter_exit_behavior.py")
    code, doc = _scan_json(cfg, target)
    assert code == expected, f"process exit must be {expected}, got {code}: {doc}"
    assert doc["exit_code"] == expected, f"doc exit_code must be {expected}: {doc}"
    assert doc["exit_code"] == code, (
        f"a machine consumer reads exit_code; it must equal the process code "
        f"({doc['exit_code']} != {code})"
    )


# ==========================================================================
# Behavior 7 -- the consumer lives on the PROMPT SURFACE, not in the brain
# ==========================================================================
def test_b7_dispatcher_never_mentions_the_scan_verb():
    txt = DISPATCHER.read_text()
    hits = sorted({t for t in ("test-quality", "test_quality") if t in txt})
    assert hits == [], (
        f"dispatcher.py must not learn the verb (prompt-surface change only), found {hits}"
    )


def test_b7_both_modules_still_import_in_a_fresh_interpreter():
    proc = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                          cwd=str(_ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


# ==========================================================================
# Acceptance Criteria oracles
# ==========================================================================
def test_ac_this_iterations_own_test_module_scans_clean_under_the_carded_command(tmp_path):
    """The check the card now asks the reviewer to run must pass on THIS iteration's own work.
    Path derived from __file__, so it is fresh-clone safe and carries no machine path."""
    cfg = _write_cfg(tmp_path)
    me = pathlib.Path(__file__).resolve()
    code, doc = _scan_json(cfg, me)
    assert code == 0 and doc["total_findings"] == 0, (
        f"this module must scan clean under `{VERB} --files`: {json.dumps(doc)[:900]}"
    )


def test_ac_roadmap_record_for_this_iteration_landed():
    ledger = [ln for ln in ROADMAP.read_text().splitlines()
              if ln.startswith(f"- iter {THIS_ITER} ")]
    assert len(ledger) == 1, f"exactly one iter-{THIS_ITER} ledger row required: {ledger}"
    assert len(ledger[0]) <= 120, f"ledger row must be <=120 chars, got {len(ledger[0])}"
    bullets = [ln for ln in ARCHIVE.read_text().splitlines()
               if ln.startswith(f"- **iter {THIS_ITER} ")]
    assert len(bullets) == 1, f"exactly one archive bullet required, got {len(bullets)}"


# ==========================================================================
# Two-sided guards on THIS module's own oracles -- an extractor that can never
# report a violation would certify Behaviors 1-2 vacuously (the GAP-023 shape,
# turned on the oracle itself). Synthetic cards only; the real card is untouched.
# ==========================================================================
_SYNTH_ABSENT = "# ROLE: Reviewer\n\n## Duties\n\n1. Read the diff.\n"
_SYNTH_UNSCOPED = (
    "# ROLE: Reviewer\n\n## Test-quality scan (advisory)\n\n"
    "Run `python3 <checkout>/foundry.py test-quality --config <cfg>` and report it.\n"
)
_SYNTH_BLOCKING = (
    "# ROLE: Reviewer\n\n## test-quality scan\n\n"
    "Run `python3 <checkout>/foundry.py test-quality --config <cfg> --files "
    "<checkout>/tests/test_iter<NN>_behavior.py` and file any finding as [BLOCKING].\n"
)


def _synth(tmp_path, body, name="card.md"):
    p = tmp_path / name
    p.write_text(body)
    return p


def test_guard_behavior1_token_check_fails_on_a_card_that_lacks_the_invocation(tmp_path):
    card = _synth(tmp_path, _SYNTH_ABSENT)
    hits = [ln for ln in card.read_text().splitlines()
            if all(tok in ln for tok in INVOCATION_TOKENS)]
    assert hits == [], "guard fixture must NOT contain the invocation"
    scoped = _synth(tmp_path, _SYNTH_BLOCKING, "scoped.md")
    ok = [ln for ln in scoped.read_text().splitlines()
          if all(tok in ln for tok in INVOCATION_TOKENS)]
    assert len(ok) == 1, f"the same predicate must FIRE on a card that does carry it: {ok}"


def test_guard_behavior1_unscoped_check_catches_a_repo_wide_command(tmp_path):
    card = _synth(tmp_path, _SYNTH_UNSCOPED)
    offenders = [ln for ln in card.read_text().splitlines()
                 if "foundry.py test-quality" in ln and "--files" not in ln]
    assert len(offenders) == 1, f"the never-repo-wide arm must fire on an unscoped line: {offenders}"


def test_guard_behavior2_advisory_predicate_is_two_sided(tmp_path):
    absent = _test_quality_sections(case_sensitive=False, path=_synth(tmp_path, _SYNTH_ABSENT))
    assert absent == [], f"no section may be found in a card with no such heading: {absent}"
    blocking = _test_quality_sections(
        case_sensitive=False, path=_synth(tmp_path, _SYNTH_BLOCKING, "b.md"))
    assert len(blocking) == 1, blocking
    assert not _is_advisory(blocking[0][1]), (
        "a section that files findings as [BLOCKING] and never says 'never' must NOT read as "
        f"advisory: {blocking[0][1]!r}"
    )


def test_guard_behavior2_case_agreement_check_can_fail(tmp_path):
    """The mixed-case heading in the unscoped fixture matches only the loose reading, so the
    agreement assertion is capable of failing -- it is not a tautology."""
    card = _synth(tmp_path, _SYNTH_UNSCOPED)
    strict = [h for h, _ in _test_quality_sections(case_sensitive=True, path=card)]
    loose = [h for h, _ in _test_quality_sections(case_sensitive=False, path=card)]
    assert strict == [] and len(loose) == 1, (strict, loose)


# ==========================================================================
# Behavior 6, literal reading -- a REAL child process's exit status
# ==========================================================================
@pytest.mark.parametrize("src,expected", [(GOOD_SRC, 0), (BAD_SRC, 1)])
def test_b6_real_subprocess_exit_status_matches_the_json_exit_code(tmp_path, src, expected):
    cfg = _write_cfg(tmp_path)
    target = _fixture(tmp_path, src, "test_iter_subproc_behavior.py")
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "foundry.py"), VERB,
         "--config", str(cfg), "--files", str(target), "--json"],
        cwd=str(_ROOT), capture_output=True, text=True)
    assert proc.returncode == expected, (proc.returncode, proc.stdout[-600:], proc.stderr[-600:])
    doc = json.loads(proc.stdout)
    assert doc["exit_code"] == proc.returncode, (doc.get("exit_code"), proc.returncode)
