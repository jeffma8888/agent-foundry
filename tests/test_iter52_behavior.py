"""Black-box behaviour tests for iter 52 -- item 16 BITE 3 (COMPLETES item 16):
wire the ``final`` role to run the committed leak-guard (``scripts/leak_guard.py``)
as a hard, repo-agnostic, fail-CLOSED in-loop pre-push gate check, and flip the
ARCHITECTURE.md / README.md docs from "not yet wired / future step" to WIRED.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-52 PM
spec's Expected Behaviors (1-9) + Acceptance Criteria, plus the product's own
SHIPPED OBSERVABLE OUTPUT -- for this bite the feature IS the shipped prose, and
the spec explicitly declares "the observable output is the shipped text of
``roles/final.md``, ``ARCHITECTURE.md``, ``README.md``, and the byte-diff of the
non-prose files". So reading those prose files to assert the spec's NAMED
substrings/ordering is the black-box test (the same pattern the iter-50/51 tests
use to assert README/ARCHITECTURE content). Every assertion is derived from the
SPEC (which pins the exact substrings), NOT by mirroring the engineer's optional
phrasing; for the two spec-FLEXIBLE behaviours (B3 conditional phrasing, B4
exit-code phrasing) the spec lists several acceptable forms and the test accepts
ANY of them. The implementation SOURCE of ``foundry.py`` / ``dispatcher.py`` /
``scripts/leak_guard.py`` (as logic to mirror), the engineer's and reviewer's
notes, and the CONTENT of ``git diff`` were NOT read. Two allowed exceptions,
both "running the product on data", not reading-as-logic: (a) Behavior 9 feeds
each shipped file's RAW TEXT to ``leak_guard.scan_text`` as scanner INPUT for the
public-safety self-scan -- running the scanner, not mirroring it; (b) the
byte-unchanged check (Behavior 8) uses ``git diff --quiet`` which emits NO diff
text (exit-code-only assertion).

Fully offline & deterministic: no subprocess/git-repo harness, no network, no
agent run -- pure file-content substring/ordering assertions + a self-leak scan +
a ``git diff --quiet`` byte-unchanged check (the LIGHTEST test class). Every
home-path probe is BUILT AT RUNTIME by concatenation so the literal contiguous
string never appears in this PUBLIC source; a meta self-scan proves this test
file itself scans clean against the COMMITTED denylist, so it cannot trip the
ship-gate's own leak scan on push.
"""
import importlib.util
import pathlib
import re
import subprocess
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_THIS = pathlib.Path(__file__).resolve()
_FINAL = _ROOT / "roles" / "final.md"
_ARCH = _ROOT / "ARCHITECTURE.md"
_README = _ROOT / "README.md"
_ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
_REAL_LEAK_GUARD = _ROOT / "scripts" / "leak_guard.py"
_REAL_DENYLIST = _ROOT / "scripts" / "leak_denylist.txt"

# The spec's Behavior 2 pins the exact command the gate step must name.
PINNED = "python3 <repo>/scripts/leak_guard.py --ref HEAD --repo <repo>"
# Home-path prefix built at RUNTIME so the contiguous literal never appears in
# this PUBLIC source (it is itself a committed denylist needle).
HOME_PREFIX = "/" + "Users" + "/"

# Every file that goes PUBLIC in this iteration's ship diff -- each must scan
# clean, because the very commit that wires the gate is itself scanned by it.
_SHIPPED_FILES = (
    _FINAL, _ARCH, _README, _ROADMAP, _THIS,
    _ROOT / "tests" / "test_iter50_behavior.py",
    _ROOT / "tests" / "test_iter51_behavior.py",
)


def _load_leak_guard():
    """Load the committed scanner from its repo path (spec-endorsed; no conftest).
    Register in sys.modules BEFORE exec so its frozen dataclass resolves."""
    spec = importlib.util.spec_from_file_location("leak_guard", _REAL_LEAK_GUARD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["leak_guard"] = mod
    spec.loader.exec_module(mod)
    return mod


lg = _load_leak_guard()


def _final():
    return _FINAL.read_text()


def _section(text, start_marker, *end_markers):
    """Slice from start_marker to the first following end_marker (or EOF)."""
    i = text.find(start_marker)
    assert i != -1, f"section start {start_marker!r} not found"
    ends = [text.find(m, i + len(start_marker)) for m in end_markers]
    ends = [e for e in ends if e != -1]
    j = min(ends) if ends else len(text)
    return text[i:j]


def _committed_patterns():
    # load_denylist takes the file TEXT, NOT a Path (iter-51 API gotcha).
    return lg.load_denylist(_REAL_DENYLIST.read_text())


# --------------------------------------------------------------------------
# Behavior 1 -- the leak-guard gate step is present in roles/final.md
# --------------------------------------------------------------------------
def test_b1_gate_step_present_in_final():
    final = _final()
    assert "scripts/leak_guard.py" in final, (
        "roles/final.md does not reference scripts/leak_guard.py")
    assert "--ref HEAD" in final, "roles/final.md lacks the --ref HEAD scan flag"


def test_b1_gate_step_is_a_sixth_checklist_item():
    """The new step is a 6th item under 'Gate checklist (ALL must hold to ship)'
    -- the five prior items survive and a 6th referencing the scanner is added."""
    gate = _section(_final(), "## Gate checklist", "## If ALL pass")
    for n in range(1, 7):
        assert re.search(rf"(?m)^{n}\.", gate), (
            f"gate-checklist item {n}. missing (expected 5 prior + the new 6th)")
    assert "leak_guard.py" in gate, (
        "the leak-guard step is not inside the gate checklist section")


# --------------------------------------------------------------------------
# Behavior 2 -- pinned invocation, scans HEAD, positioned BEFORE the push
# --------------------------------------------------------------------------
def test_b2_pinned_command_present():
    assert PINNED in _final(), (
        f"roles/final.md lacks the pinned invocation {PINNED!r}")


def test_b2_leak_guard_runs_before_push_file_wide():
    """Spec parenthetical: the pinned run's first char index in the FILE is less
    than the index of `push origin`."""
    final = _final()
    i_scan = final.find(PINNED)
    i_push = final.find("push origin")
    assert i_scan != -1 and i_push != -1
    assert i_scan < i_push, (
        f"leak-guard run (idx {i_scan}) must precede push origin (idx {i_push})")


def test_b2_leak_guard_runs_before_push_within_ship_section():
    """Within the 'If ALL pass -- ship' section, the scanner run precedes push."""
    ship = _section(_final(), "## If ALL pass", "## If ANY fail")
    i_scan = ship.find("leak_guard.py")
    i_push = ship.find("push origin")
    assert i_scan != -1, "ship section does not run the leak-guard"
    assert i_push != -1, "ship section has no push step"
    assert i_scan < i_push, (
        "in the ship section the leak-guard run must come BEFORE push origin")


# --------------------------------------------------------------------------
# Behavior 3 -- repo-agnostic: skipped when the repo lacks the scanner
# --------------------------------------------------------------------------
def test_b3_check_is_conditional_on_scanner_presence():
    """Spec permits several conditional phrasings; accept ANY of them and
    require an explicit skip-when-absent so an unguarded product is not blocked.
    (Ambiguity noted as PM feedback: the exact phrasing is spec-flexible.)"""
    flow = _final().lower()
    accepted = (
        "[ -f",                     # a shell -f presence guard
        "if the repo has",
        "if the repo carries",
        "when the repo carries",
        "if the repo does not carry",
    )
    assert any(form in flow for form in accepted), (
        "roles/final.md does not condition the check on scanner presence "
        f"(none of {accepted} found)")
    assert "skip" in flow, (
        "roles/final.md does not state the check is SKIPPED when the repo lacks "
        "the scanner (would false-block an unguarded product)")


# --------------------------------------------------------------------------
# Behavior 4 -- non-zero exit = BLOCKING revert, fail-closed, exit 2 also blocks
# --------------------------------------------------------------------------
def test_b4_nonzero_exit_blocks_and_reverts():
    flow = _final().lower()
    assert "non-zero" in flow, "roles/final.md does not tie a non-zero exit to anything"
    assert "revert" in flow, "a leak hit is not routed to the revert path"


def test_b4_fail_closed_exit_2_also_blocks():
    """Fail-CLOSED: exit 2 (scanner error) must ALSO block, not just exit 1 --
    the guard must never be defeated by making itself error."""
    flow = _final().lower()
    exit1 = ("exit 1", "1 (a leaked", "1 = leaked")
    exit2 = ("exit 2", "2 (the scanner", "2 = scanner error", "2 (scanner")
    assert any(f in flow for f in exit1), (
        f"exit 1 (a found token) not tied to a block (none of {exit1})")
    assert any(f in flow for f in exit2), (
        f"exit 2 (scanner error) not tied to a block -- fail-closed requires it "
        f"(none of {exit2})")
    assert ("fail-closed" in flow) or ("fail closed" in flow), (
        "roles/final.md does not state the check is fail-closed")


# --------------------------------------------------------------------------
# Behavior 5 -- the existing gate contract is PRESERVED (additive-only edit)
# --------------------------------------------------------------------------
def test_b5_prior_ship_contract_preserved_verbatim():
    final = _final()
    preserved = (
        "ACTION: PUSHED",
        "ACTION: REVERTED",
        "(foundry iter NN)",
        "NEVER force-push",
        "git -C <repo> reset --hard origin/<branch>",
        "{feat, fix, chore, docs, test}",
    )
    missing = [s for s in preserved if s not in final]
    assert not missing, f"prior ship-contract substrings were altered/removed: {missing}"


# --------------------------------------------------------------------------
# Behavior 6 -- ARCHITECTURE.md §7 documents the now-WIRED gate step
# --------------------------------------------------------------------------
def test_b6_architecture_marks_gate_wired():
    arch = _ARCH.read_text()
    assert "not yet wired" not in arch, (
        "ARCHITECTURE.md still says 'not yet wired' -- the gate is now wired")
    sec = _section(arch, "## 7.", "\n## ")
    low = sec.lower()
    assert "leak_guard.py" in sec, "§7 does not name the scanner"
    assert "wired" in low, "§7 does not state the gate step is WIRED"
    assert "final" in low, "§7 does not attribute the check to the final role"
    assert "bite 3" in low, "§7 does not tie the wiring to item 16 bite 3"


# --------------------------------------------------------------------------
# Behavior 7 -- README public-safety section is accurate after wiring
# --------------------------------------------------------------------------
def test_b7_readme_public_safety_no_longer_future_step():
    readme = _README.read_text()
    assert "future step" not in readme, (
        "README still calls the final-gate check a 'future step'")
    sec = _section(readme, "## Public-safety", "\n## ")
    low = sec.lower()
    assert "wired" in low, (
        "README public-safety section does not reflect the check is wired")
    assert "final gate" in low or "final-gate" in low, (
        "README public-safety section does not reference the final gate")


# --------------------------------------------------------------------------
# Behavior 8 -- non-prose files byte-unchanged; both modules import
# --------------------------------------------------------------------------
def test_b8_non_prose_files_byte_unchanged():
    """`git diff --quiet` emits NO diff text -- exit-code-only assertion (honors
    the isolation contract). roles/ is EXCLUDED: role prompts are read-fresh each
    stage and are legitimately edited by iterations, so they are not the pipeline
    control path; the spec's Behavior 8 names exactly these four files."""
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--",
         "foundry.py", "dispatcher.py",
         "scripts/leak_guard.py", "scripts/leak_denylist.txt"],
        cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, (
        "non-prose control-path/guard files are NOT byte-unchanged from HEAD")


def test_b8_foundry_and_dispatcher_still_import():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, f"import failed: {r.stderr}"


# --------------------------------------------------------------------------
# Behavior 9 -- self-leak safe (the iter-49/50/51 load-bearing rule)
# --------------------------------------------------------------------------
def test_b9_all_shipped_files_scan_clean():
    patterns = _committed_patterns()
    for path in _SHIPPED_FILES:
        txt = path.read_text()
        findings = lg.scan_text(txt, patterns)
        assert len(findings) == 0, (
            f"{path.name} leaks against the committed denylist: {findings}")
        assert HOME_PREFIX not in txt, (
            f"{path.name} contains an absolute home path")


def test_b9_committed_denylist_is_a_live_matcher():
    """A clean self-scan is only meaningful if the denylist actually matches.
    Build the probe at RUNTIME so the literal string never appears in source."""
    patterns = _committed_patterns()
    probe = HOME_PREFIX + "somebody/x"  # runtime-built; matches the home-path needle
    assert len(lg.scan_text(probe, patterns)) >= 1, (
        "committed denylist matched nothing -- the clean self-scan is not "
        "genuine (inert patterns)")


def test_b9_meta_this_test_file_is_ship_clean():
    """This PUBLIC test file must itself pass the ship-gate leak scan."""
    patterns = _committed_patterns()
    text = _THIS.read_text()
    assert len(lg.scan_text(text, patterns)) == 0, (
        "this test file would trip the ship-gate leak scan")
    assert HOME_PREFIX not in text, "this test file contains an absolute home path"
