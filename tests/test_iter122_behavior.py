"""Black-box behaviour tests for iter 122 -- compact PLATFORM_ROADMAP.md into a terse
INDEX plus a new tracked PLATFORM_ROADMAP_ARCHIVE.md (byte-for-byte move), and ship a
module-level character budget with two PURE verdict functions that THIS SUITE enforces
so the index can never regrow and no archived iteration can be silently dropped.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-122 PM spec
(products/_platform/state/iter-122/pm.md -- Expected Behaviors 1-11 + Acceptance
Criteria) and from the product's own OBSERVABLE surface (importing it and CALLING the
public functions, plus reading the two SHIPPED roadmap markdown files, which for this
iteration ARE the deliverable). The implementation source of foundry.py /
dispatcher.py, the PM's split script, the engineer's notes, the reviewer's notes and
git diff CONTENT were NOT read. The dormancy / purity checks use the iter-107
_co_names_deep BYTECODE convention (code object co_names), never a read of module
source text. Fully offline and deterministic: synthetic strings, the two real markdown
files, one exit-code-only `git check-ignore` call (emits no diff text), and the
committed leak scanner run as a scanner over text. No network, no agent run, no
mutation of the repo tree.

FORWARD-STABILITY DEVIATION (documented as PM feedback in tester.md): Behaviors 4 and
5 are phrased in the spec as TOTALS ("exactly 98 lines matching ...", "hash of the 98
matching lines"). The index's own stated contract makes every FUTURE iteration append
one ledger row AND one archive bullet in the same commit, so a total-count assertion
turns RED on the next CORRECT iteration and would get it reverted -- and the tempting
repair is to delete the brake. These tests therefore anchor both behaviors to the
CLOSED, FROZEN SET of 98 iteration numbers the spec itself enumerates: each frozen
number must appear EXACTLY ONCE, the SHA-256 is taken over the bullets whose number is
IN that set (file order), and any extra ledger/archive number must be a FUTURE
iteration (> 119). That is exactly as strong as the total form today (verified: no
extras exist, so set-equality holds and the pinned digest matches byte-for-byte) and it
stays green as the archive legitimately grows.
"""
import hashlib
import importlib.util
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- Acceptance Criteria)

_INDEX = _ROOT / "PLATFORM_ROADMAP.md"
_ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
_THIS = pathlib.Path(__file__).resolve()
_LEAK_GUARD = _ROOT / "scripts" / "leak_guard.py"
_DENYLIST = _ROOT / "scripts" / "leak_denylist.txt"

# Home-path prefix built at RUNTIME so the contiguous literal never appears in this
# PUBLIC source (it is itself a committed denylist needle) -- iter-52/61 convention.
HOME_PREFIX = "/" + "Users" + "/"

# --- the spec's NORMATIVE regexes, verbatim -------------------------------------
LEDGER_RE = re.compile(r"^- iter (\d+) ")
BULLET_RE = re.compile(r"^- \*\*iter (\d+) ")

# Behavior 5's pinned digest, computed in the PM stage from the PRE-split file.
PINNED_SHA256 = "0fee18f4f5568de1404fe49786e1ec6a5648131fd2f698dabfa570b62dfaa904"

# Behavior 4's frozen set of the 98 iteration numbers that existed at MOVE time.
FROZEN = {
    1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
    24, 25, 26, 27, 28, 30, 31, 32, 39, 40, 42, 43, 44, 46, 47, 48, 49, 50, 51, 52,
    54, 55, 56, 57, 58, 59, 60, 61, 63, 65, 66, 67, 68, 69, 70, 72, 73, 74, 75, 76,
    77, 78, 79, 80, 81, 82, 83, 84, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98,
    99, 100, 101, 104, 105, 106, 107, 110, 112, 113, 114, 115, 116, 117, 118, 119,
}
LAST_FROZEN = max(FROZEN)  # 119 -- any extra row must be a FUTURE iteration


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _index_text():
    return _INDEX.read_text()


def _archive_text():
    return _ARCHIVE.read_text()


def _matches(text, rx):
    """Lines matching rx, IN FILE ORDER, paired with their captured int."""
    out = []
    for line in text.splitlines():
        m = rx.match(line)
        if m:
            out.append((int(m.group(1)), line))
    return out


def _co_names_deep(fn):
    """Names referenced by a function's bytecode, recursively through nested code
    objects (iter-107 convention). Never reads module source text."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _load_leak_guard():
    spec = importlib.util.spec_from_file_location("leak_guard_iter122_probe", _LEAK_GUARD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["leak_guard_iter122_probe"] = mod
    spec.loader.exec_module(mod)
    return mod


def _boom(*a, **k):
    raise AssertionError("a function the spec declares PURE performed real I/O")


# ==========================================================================
# Behavior 1 -- the archive file exists, is NOT gitignored, is titled, is big
# ==========================================================================
def test_b1_archive_exists_at_repo_root():
    assert _ARCHIVE.is_file(), (
        "PLATFORM_ROADMAP_ARCHIVE.md missing at the repo root -- the moved history "
        "would be LOST from the ship diff")


def test_b1_archive_is_not_gitignored():
    # exit-code-only: git check-ignore emits no diff text. Non-zero => NOT ignored.
    proc = subprocess.run(
        ["git", "check-ignore", "-q", str(_ARCHIVE)],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=60)
    assert proc.returncode != 0, (
        "PLATFORM_ROADMAP_ARCHIVE.md is matched by .gitignore -- it must SHIP")


def test_b1_archive_first_nonblank_line_is_the_title():
    first = next((l for l in _archive_text().splitlines() if l.strip()), "")
    assert first.startswith("# Platform Roadmap Archive"), (
        "archive's first non-blank line is %r" % first[:80])


def test_b1_archive_is_at_least_270k_chars():
    n = len(_archive_text())
    assert n >= 270_000, "archive is only %d chars (expected >= 270000)" % n


# ==========================================================================
# Behavior 2 -- zero fat history bullets left in the INDEX
# ==========================================================================
def test_b2_index_has_no_fat_iteration_bullets():
    left = _matches(_index_text(), BULLET_RE)
    assert left == [], (
        "%d fat history bullet(s) remain in the index, first is iter %s"
        % (len(left), left[0][0] if left else None))


# ==========================================================================
# Behavior 3 -- the index fits the shipped character budget
# ==========================================================================
def test_b3_index_fits_the_budget():
    # CHAR budget => measure with len(read_text()), never `wc -c` bytes.
    n = len(_index_text())
    assert n <= foundry.ROADMAP_SIZE_WARN_CHARS, (
        "index is %d chars, budget is %d" % (n, foundry.ROADMAP_SIZE_WARN_CHARS))


# ==========================================================================
# Behavior 4 -- the DONE LEDGER: heading, one terse row per frozen iteration
# ==========================================================================
def test_b4_index_has_a_done_ledger_heading():
    heads = [l for l in _index_text().splitlines()
             if l.lstrip().startswith("#") and "Done ledger" in l]
    assert heads, "no heading line containing 'Done ledger' in the index"


def test_b4_every_frozen_iteration_has_exactly_one_ledger_row():
    nums = [n for n, _ in _matches(_index_text(), LEDGER_RE)]
    missing = sorted(FROZEN - set(nums))
    assert not missing, "ledger rows missing for iterations %r" % missing
    dupes = sorted({n for n in nums if nums.count(n) > 1})
    assert not dupes, "duplicate ledger rows for iterations %r" % dupes


def test_b4_no_unexpected_historical_ledger_row():
    nums = {n for n, _ in _matches(_index_text(), LEDGER_RE)}
    extra_history = sorted(n for n in (nums - FROZEN) if n <= LAST_FROZEN)
    assert not extra_history, (
        "ledger gained historical iteration(s) %r that were not in the frozen move set"
        % extra_history)


def test_b4_every_ledger_row_is_terse():
    long_rows = [(n, len(l)) for n, l in _matches(_index_text(), LEDGER_RE)
                 if len(l) > 120]
    assert not long_rows, "ledger row(s) over 120 chars: %r" % long_rows


def test_b4_ledger_row_count_is_at_least_the_frozen_set():
    nums = [n for n, _ in _matches(_index_text(), LEDGER_RE)]
    assert len(nums) >= len(FROZEN), (
        "only %d ledger rows, the frozen move set has %d" % (len(nums), len(FROZEN)))


# ==========================================================================
# Behavior 5 -- BYTE-IDENTITY ORACLE: the move lost nothing and changed nothing
# ==========================================================================
def test_b5_archive_holds_exactly_one_bullet_per_frozen_iteration():
    nums = [n for n, _ in _matches(_archive_text(), BULLET_RE)]
    missing = sorted(FROZEN - set(nums))
    assert not missing, "archive is MISSING history bullets for %r" % missing
    dupes = sorted({n for n in nums if nums.count(n) > 1})
    assert not dupes, "archive has duplicate history bullets for %r" % dupes


def test_b5_frozen_bullets_hash_to_the_pinned_sha256():
    selected = [l for n, l in _matches(_archive_text(), BULLET_RE) if n in FROZEN]
    assert len(selected) == len(FROZEN), (
        "selected %d frozen bullets, expected %d" % (len(selected), len(FROZEN)))
    blob = "\n".join(selected)
    got = hashlib.sha256(blob.encode()).hexdigest()
    assert got == PINNED_SHA256, (
        "the moved history is NOT verbatim: sha256 %s != pinned %s"
        % (got, PINNED_SHA256))


# ==========================================================================
# Behavior 6 -- the budget constant
# ==========================================================================
def test_b6_budget_constant():
    v = foundry.ROADMAP_SIZE_WARN_CHARS
    assert isinstance(v, int) and not isinstance(v, bool), "not a plain int: %r" % (v,)
    assert v == 60000, "ROADMAP_SIZE_WARN_CHARS == %r, expected 60000" % (v,)


# ==========================================================================
# Behavior 7 -- roadmap_size_verdict fields + budget read AT CALL TIME
# ==========================================================================
@pytest.mark.parametrize("text", ["", "x", "a\nb", "a\nb\n", "line\n" * 500, "\u00e9\u00e9\n"])
def test_b7_verdict_fields_are_consistent_with_the_input(text):
    v = foundry.roadmap_size_verdict(text)
    assert v.char_count == len(text)
    assert v.line_count == len(text.splitlines())
    assert v.budget == foundry.ROADMAP_SIZE_WARN_CHARS
    assert v.over_budget is (v.char_count > v.budget)


def test_b7_budget_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "ROADMAP_SIZE_WARN_CHARS", 5)
    v = foundry.roadmap_size_verdict("x" * 10)
    assert v.budget == 5, "budget %r -- not read from the module global at call time" % (v.budget,)
    assert v.over_budget is True


def test_b7_verdict_keeps_the_budget_it_was_computed_under(monkeypatch):
    """A verdict is a SNAPSHOT: raising the global afterwards must not silently
    re-judge an already-returned verdict. (Reading of the spec's 'AT CALL TIME';
    flagged as an ambiguity in tester.md.)"""
    before = foundry.roadmap_size_verdict("x" * 10)
    monkeypatch.setattr(foundry, "ROADMAP_SIZE_WARN_CHARS", 5)
    assert before.budget == 60000
    assert before.over_budget is False


def test_b7_over_budget_is_a_real_bool(monkeypatch):
    monkeypatch.setattr(foundry, "ROADMAP_SIZE_WARN_CHARS", 3)
    assert foundry.roadmap_size_verdict("abcd").over_budget is True
    assert foundry.roadmap_size_verdict("ab").over_budget is False


# ==========================================================================
# Behavior 8 -- empty input and the strict > boundary
# ==========================================================================
def test_b8_empty_text_is_total_and_zero():
    v = foundry.roadmap_size_verdict("")
    assert (v.char_count, v.line_count, v.over_budget) == (0, 0, False)


def test_b8_exactly_budget_is_not_over_budget(monkeypatch):
    monkeypatch.setattr(foundry, "ROADMAP_SIZE_WARN_CHARS", 10)
    assert foundry.roadmap_size_verdict("x" * 10).over_budget is False
    assert foundry.roadmap_size_verdict("x" * 11).over_budget is True


def test_b8_exactly_budget_at_the_real_budget():
    n = foundry.ROADMAP_SIZE_WARN_CHARS
    assert foundry.roadmap_size_verdict("x" * n).over_budget is False
    assert foundry.roadmap_size_verdict("x" * (n + 1)).over_budget is True


# ==========================================================================
# Behavior 9 -- roadmap_archive_gaps: spec examples, purity, totality
# ==========================================================================
def test_b9_spec_examples():
    assert foundry.roadmap_archive_gaps("- iter 7 a\n- iter 9 b", "- **iter 7 = x") == [9]
    assert foundry.roadmap_archive_gaps("- iter 7 a", "- **iter 7 = x") == []
    assert foundry.roadmap_archive_gaps("", "") == []


def test_b9_archive_only_numbers_are_never_reported():
    assert foundry.roadmap_archive_gaps(
        "- iter 7 a", "- **iter 7 = x\n- **iter 8 = y\n- **iter 900 = z") == []


def test_b9_result_is_sorted_ascending_and_deduplicated():
    idx = "- iter 12 a\n- iter 3 b\n- iter 7 c\n- iter 3 d\n- iter 12 e"
    assert foundry.roadmap_archive_gaps(idx, "") == [3, 7, 12]


def test_b9_only_the_normative_patterns_count():
    # ledger needs the trailing space after the digits; archive bullets need the **
    assert foundry.roadmap_archive_gaps("- iter 9", "") == []
    assert foundry.roadmap_archive_gaps("  - iter 9 indented", "") == []
    assert foundry.roadmap_archive_gaps("- **iter 9 = bold in the index", "") == []
    assert foundry.roadmap_archive_gaps("- iter 5 a", "- iter 5 = not bold") == [5]


@pytest.mark.parametrize("idx,arc", [
    ("", ""),
    ("\n\n\n", "\n\n\n"),
    ("no markers at all", "none here either"),
    ("- iter x a", "- **iter y = b"),
    ("- iter 00042 a", "- **iter 42 = b"),
    ("- iter 9999999999999999999 a", ""),
    ("\u0000\u00ff weird \u4e2d\u6587", "@@@ ###"),
    ("- iter 1 " + "z" * 5000, ""),
])
def test_b9_is_total_and_never_raises(idx, arc):
    out = foundry.roadmap_archive_gaps(idx, arc)
    assert isinstance(out, list)
    assert all(isinstance(n, int) for n in out)
    assert out == sorted(set(out))


def test_b9_is_pure_no_filesystem_or_subprocess_names():
    names = _co_names_deep(foundry.roadmap_archive_gaps) | _co_names_deep(
        foundry.roadmap_size_verdict)
    for forbidden in ("read_text", "write_text", "open", "exists", "iterdir", "glob",
                      "run", "Popen", "check_output", "urlopen", "socket", "system"):
        assert forbidden not in names, (
            "a pure verdict function references %r" % forbidden)


def test_b9_is_pure_against_live_io_seams(monkeypatch):
    monkeypatch.setattr("builtins.open", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    assert foundry.roadmap_archive_gaps("- iter 7 a\n- iter 9 b", "- **iter 7 = x") == [9]
    assert foundry.roadmap_size_verdict("abc").char_count == 3


def test_b9_is_deterministic():
    idx, arc = "- iter 7 a\n- iter 9 b\n- iter 11 c", "- **iter 9 = x"
    first = foundry.roadmap_archive_gaps(idx, arc)
    for _ in range(5):
        assert foundry.roadmap_archive_gaps(idx, arc) == first


# ==========================================================================
# Behavior 10 -- THE BRAKE: applied to the real shipped files
# ==========================================================================
def test_b10_no_archive_gaps_in_the_real_repo_files():
    gaps = foundry.roadmap_archive_gaps(_index_text(), _archive_text())
    assert gaps == [], (
        "iteration(s) %r have a ledger row but NO archive history bullet -- history "
        "was dropped by the last roadmap write" % gaps)


def test_b10_real_index_is_not_over_budget():
    v = foundry.roadmap_size_verdict(_index_text())
    assert v.over_budget is False, (
        "PLATFORM_ROADMAP.md has regrown to %d chars, past the %d budget -- move the "
        "history to PLATFORM_ROADMAP_ARCHIVE.md instead of raising the budget"
        % (v.char_count, v.budget))


# ==========================================================================
# Behavior 11 -- public safety of the newly shipped archive
# ==========================================================================
def test_b11_archive_scans_clean_under_the_committed_denylist():
    if not (_LEAK_GUARD.exists() and _DENYLIST.exists()):
        pytest.skip("leak-guard not present in this repo (repo-agnostic)")
    lg = _load_leak_guard()
    patterns = lg.load_denylist(_DENYLIST.read_text())  # API takes TEXT, not a Path
    # two-sided: prove the matcher is LIVE before trusting a clean result
    assert len(lg.scan_text(HOME_PREFIX + "somebody/x", patterns)) >= 1, \
        "denylist appears inert (a home-path probe did not match)"
    for p in (_ARCHIVE, _INDEX, _THIS):
        txt = p.read_text()
        assert len(lg.scan_text(txt, patterns)) == 0, \
            "%s contains a denylisted token (would BLOCK this iteration's ship)" % p.name
        assert HOME_PREFIX not in txt, \
            "%s contains an absolute home-directory path" % p.name


# ==========================================================================
# Acceptance Criteria -- import safety and DORMANCY (no call site on the hot path)
# ==========================================================================
def test_ac_import_safety_of_both_modules():
    assert foundry.__file__ and dispatcher.__file__


@pytest.mark.parametrize("fname", [
    "run_iteration", "run_stage", "build_prompt", "postrelease_step", "lint_config",
])
def test_ac_new_code_has_no_call_site_on_the_control_path(fname):
    fn = getattr(foundry, fname, None)
    if fn is None:
        pytest.skip("%s not present in this build" % fname)
    names = _co_names_deep(fn)
    for new in ("roadmap_size_verdict", "roadmap_archive_gaps",
                "ROADMAP_SIZE_WARN_CHARS"):
        assert new not in names, (
            "%s references %s -- this iteration must ship DORMANT (no control-flow "
            "change, resume semantics untouched)" % (fname, new))


def test_ac_no_new_cli_verb_for_the_roadmap_size_check():
    for verb in ("roadmap-size", "roadmap_size", "roadmap-archive-gaps"):
        assert not hasattr(foundry, verb.replace("-", "_") + "_cli"), \
            "a CLI verb %r was shipped; the spec says the pedal is the suite test" % verb
