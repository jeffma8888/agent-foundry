"""Black-box behaviour tests for iter 112 -- prose-only bite: add one identical
`## WRITE-EARLY (checkpoint-first)` section to EVERY top-level core role card
under `roles/*.md`.

The section tells each stage to write a complete-but-minimal version of its
required output file as soon as its decision is made, then refine it in place, so
work survives the ~600s per-stage agent-CLI kill.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-112 PM
spec's Expected Behaviors (1-6), the product README / roadmap, the tests/
conventions (esp. the disk-read role-card assertion in
test_iter106_behavior.py::test_b12_roles_pm_md_has_rule and the meta-ASCII
precedent), and the product's own OBSERVABLE output (role cards read from disk;
`import foundry, dispatcher` exercised via a fresh subprocess). The implementation
SOURCE (foundry.py / dispatcher.py source text), the engineer's and reviewer's
notes, and `git diff` were NOT read. Every check drives an observable artifact:
the shipped role-card text on disk and the module import surface. Fully offline
and deterministic (real repo files + one local interpreter subprocess; no git /
network / agent-run).
"""
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLES_DIR = REPO_ROOT / "roles"

# The two required anchor substrings (both pure ASCII, verbatim from the spec).
MARKER = "WRITE-EARLY (checkpoint-first)"
MECHANISM = "write a complete-but-minimal version"

# The 8 known top-level core role cards the spec pins by name.
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


def _top_level_cards():
    """Top-level `roles/*.md` glob -- NON-recursive, so `roles/bench/` is excluded."""
    return sorted(ROLES_DIR.glob("*.md"))


# ==========================================================================
# Behavior 1 -- roles/pm.md contains the exact MARKER substring
# ==========================================================================
def test_b01_pm_md_contains_marker():
    pm_md = (ROLES_DIR / "pm.md").read_text()
    assert MARKER in pm_md


# ==========================================================================
# Behavior 2 -- the top-level glob is non-empty and includes the 8 known cards
# ==========================================================================
def test_b02_glob_nonempty_includes_known_cards():
    cards = _top_level_cards()
    assert cards, "roles/*.md glob returned no cards"
    names = {p.name for p in cards}
    missing = [c for c in KNOWN_CARDS if c not in names]
    assert missing == [], "known cards missing from top-level glob: %r" % missing


def test_b02_glob_is_non_recursive_excludes_bench():
    # bench cards live in roles/bench/ and must NOT appear in the top-level glob.
    names = {p.name for p in _top_level_cards()}
    for p in _top_level_cards():
        assert p.parent == ROLES_DIR, "glob leaked a nested file: %s" % p
    bench = ROLES_DIR / "bench"
    if bench.is_dir():
        bench_names = {p.name for p in bench.glob("*.md")}
        # a bench card sharing a name would still be a different path; assert the
        # glob never descended into bench by path.
        for p in _top_level_cards():
            assert bench not in p.parents, "top-level glob descended into bench: %s" % p


# ==========================================================================
# Behavior 3 -- EVERY top-level card contains the MARKER
#   count-with-marker == total count of top-level cards
# ==========================================================================
def test_b03_every_card_contains_marker():
    cards = _top_level_cards()
    without = [p.name for p in cards if MARKER not in p.read_text()]
    assert without == [], "top-level cards missing MARKER: %r" % without


def test_b03_marker_count_equals_total_count():
    cards = _top_level_cards()
    total = len(cards)
    with_marker = sum(1 for p in cards if MARKER in p.read_text())
    assert with_marker == total, (
        "%d/%d top-level cards carry the marker (a future card added without "
        "the rule must fail this)" % (with_marker, total)
    )


# ==========================================================================
# Behavior 4 -- EVERY top-level card also contains the MECHANISM sentence
# ==========================================================================
def test_b04_every_card_contains_mechanism():
    cards = _top_level_cards()
    without = [p.name for p in cards if MECHANISM not in p.read_text()]
    assert without == [], "top-level cards missing MECHANISM sentence: %r" % without


def test_b04_each_known_card_has_both_anchors():
    for name in KNOWN_CARDS:
        text = (ROLES_DIR / name).read_text()
        assert MARKER in text, "%s missing MARKER" % name
        assert MECHANISM in text, "%s missing MECHANISM" % name


# ==========================================================================
# Behavior 5 -- both modules stay importable (no code changed)
# ==========================================================================
def test_b05_import_foundry_and_dispatcher_exit_zero():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        "import foundry, dispatcher failed (rc=%d):\nstdout=%s\nstderr=%s"
        % (proc.returncode, proc.stdout, proc.stderr)
    )


# ==========================================================================
# Behavior 6 -- this test file is pure ASCII
# ==========================================================================
def test_b06_this_file_is_pure_ascii():
    pathlib.Path(__file__).read_bytes().decode("ascii")
