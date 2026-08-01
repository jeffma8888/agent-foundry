"""Black-box behaviour tests for iter 49 -- item 16 BITE 1: the NEW committed,
portable, offline leak-guard CORE (`scripts/leak_guard.py`) plus a
self-leak-safe committed denylist (`scripts/leak_denylist.txt`).

The module exposes the pure functions `encode_pattern` / `load_denylist` /
`scan_text` and the `DENYLIST_PATH` constant. It ships DORMANT (zero call site):
nothing in the running pipeline imports it, so it cannot regress a live loop.
Its job is to let a later bite wire a CLI + the final-gate pre-push check that
blocks a leaky ship. Because the repo is PUBLIC, the committed denylist stores
its needles URL-safe-base64-encoded so the plaintext file reveals no secret, and
a self-scan (Behavior 8) proves both committed files are clean.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-49 PM
spec's Expected Behaviors (1-9), the product README/roadmap, the `tests/`
conventions (esp. tests/test_iter47_behavior.py -- the sibling detector -- for
the dormancy / compiled-introspection style), and the product's OWN OBSERVABLE
behaviour by RUNNING it (importing the module from its committed path and
driving its public functions) plus public RUNTIME introspection (module
attributes, imported-module objects). The implementation SOURCE of
`scripts/leak_guard.py` / `foundry.py` / `dispatcher.py` (as logic to mirror),
the engineer's and reviewer's notes, and `git diff` were NOT read for their
logic. Behavior 8 feeds the committed files' raw TEXT to `scan_text` as DATA
(the spec's own instruction), not as source to study. Every NEEDLE used to
exercise MATCHING is SYNTHETIC (`WIDGET` / `ALPHA` / `zap` / `HIT` / ...) -- this
test file contains NO real sensitive token and NO personal home path. Fully
offline & deterministic: no network, no git, and the only subprocess is the
documented `import foundry, dispatcher` dormancy probe.
"""
import base64
import importlib.util
import os
import pathlib
import re
import subprocess
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_URLSAFE_B64_ALPHABET = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_="
)


def _load_leak_guard():
    """Load the committed module from its repo-relative path (spec-endorsed:
    there is no conftest.py). Register in sys.modules before exec so a
    self-referential import would resolve."""
    src = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["leak_guard"] = mod
    spec.loader.exec_module(mod)
    return mod


lg = _load_leak_guard()


# ==========================================================================
# Behavior 1 -- encode_pattern round-trips and hides the literal
# ==========================================================================
def test_b1_encode_round_trips():
    for p in (r"\bWIDGET\b", r"(?<![A-Za-z])zap(?![A-Za-z])",
              r"\bmulti_word_token\b", r"PLAIN", r"a.b-c_d"):
        enc = lg.encode_pattern(p)
        assert isinstance(enc, str), f"encode_pattern must return str; got {type(enc)}"
        assert enc.isascii(), f"encode_pattern output must be ASCII; got {enc!r}"
        decoded = base64.urlsafe_b64decode(enc).decode("utf-8")
        assert decoded == p, (
            f"encode_pattern({p!r}) must URL-safe-base64-decode back to the exact "
            f"pattern; decoded {decoded!r}"
        )


def test_b1_encode_uses_only_urlsafe_alphabet():
    for p in (r"\bWIDGET\b", r"(?<![A-Za-z])zap(?![A-Za-z])", r"a.b-c_d/x+y"):
        enc = lg.encode_pattern(p)
        assert set(enc) <= _URLSAFE_B64_ALPHABET, (
            f"encode_pattern must emit only the URL-safe base64 alphabet "
            f"(A-Z a-z 0-9 - _ =); got {enc!r}"
        )
        assert "/" not in enc and "+" not in enc, (
            f"URL-safe base64 must never contain '/' or '+'; got {enc!r}"
        )


def test_b1_encode_hides_the_literal():
    # when the pattern contains ASCII letters, the pattern must NOT appear as a
    # substring of its encoding (the raw literal is hidden -- the whole point of
    # a committed guard in a PUBLIC repo).
    for p in (r"\bWIDGET\b", r"\bmulti_word_token\b", r"PLAIN"):
        enc = lg.encode_pattern(p)
        assert p not in enc, f"raw pattern {p!r} leaked into its encoding {enc!r}"
    # the visible letter-run of the WIDGET example is also hidden
    assert "WIDGET" not in lg.encode_pattern(r"\bWIDGET\b")


# ==========================================================================
# Behavior 2 -- load_denylist parses, orders (file order), and skips
# ==========================================================================
def test_b2_parse_order_skip():
    p1, p2, p3 = r"\bALPHA\b", r"\bBETA\b", r"\bGAMMA\b"
    text = "\n".join([
        "# a leading comment -- no needle here",
        "",
        "    # an indented comment (first non-blank char is '#')",
        lg.encode_pattern(p1),
        "   ",                       # whitespace-only line
        lg.encode_pattern(p2),
        "",
        lg.encode_pattern(p3),
    ])
    pats = lg.load_denylist(text)
    assert isinstance(pats, tuple), f"load_denylist must return a tuple; got {type(pats)}"
    assert len(pats) == 3, f"exactly the 3 encoded lines must load (blanks/comments skipped); got {len(pats)}"
    assert all(isinstance(p, re.Pattern) for p in pats), "each entry must be a compiled re.Pattern"
    # FILE order preserved; each compiled pattern matches its own synthetic source
    assert pats[0].search("ALPHA"), "pattern 0 must match its own synthetic source (ALPHA)"
    assert pats[1].search("BETA"), "pattern 1 must match its own synthetic source (BETA)"
    assert pats[2].search("GAMMA"), "pattern 2 must match its own synthetic source (GAMMA)"


def test_b2_order_is_file_order_not_alphabetical():
    # ZULU encoded BEFORE ALPHA -> result must be [ZULU, ALPHA], not sorted.
    text = "\n".join([lg.encode_pattern(r"\bZULU\b"), lg.encode_pattern(r"\bALPHA\b")])
    pats = lg.load_denylist(text)
    assert pats[0].search("ZULU") and pats[1].search("ALPHA"), (
        "load_denylist must preserve FILE order, not sort alphabetically"
    )


def test_b2_all_comment_or_blank_yields_empty():
    assert lg.load_denylist("# just a comment\n\n   \n") == ()
    assert lg.load_denylist("") == ()


# ==========================================================================
# Behavior 3 -- compiled case-insensitively
# ==========================================================================
def test_b3_case_insensitive():
    pats = lg.load_denylist(lg.encode_pattern(r"\bTOPSECRET\b"))
    assert lg.scan_text("TOPSECRET", pats), "must flag the upper-case form"
    assert lg.scan_text("topsecret", pats), "must flag the lower-case form (compiled IGNORECASE)"
    assert lg.scan_text("TopSecret", pats), "must flag a mixed-case form"


# ==========================================================================
# Behavior 4 -- fail-loud on a broken denylist (never silently drop)
# ==========================================================================
def test_b4a_invalid_base64_raises_with_line_number():
    text = "\n".join([lg.encode_pattern(r"\bOK\b"), "!!! not base64 !!!"])
    with pytest.raises(ValueError) as ei:
        lg.load_denylist(text)
    assert "2" in str(ei.value), (
        f"a non-URL-safe-base64 line must raise ValueError naming its 1-based line "
        f"number (2); got {ei.value!r}"
    )


def test_b4b_invalid_regex_raises_with_line_number():
    # decodes to '[unclosed' -> an invalid regex.
    text = "\n".join([lg.encode_pattern(r"\bOK\b"), lg.encode_pattern("[unclosed")])
    with pytest.raises(ValueError) as ei:
        lg.load_denylist(text)
    assert "2" in str(ei.value), (
        f"a line decoding to an invalid regex must raise ValueError naming line 2; "
        f"got {ei.value!r}"
    )


def test_b4_line_number_counts_physical_lines():
    # blanks/comments before the broken line are still counted -> physical line 5.
    text = "\n".join(["# comment", "", lg.encode_pattern(r"\bOK\b"), "", "!!!bad!!!"])
    with pytest.raises(ValueError) as ei:
        lg.load_denylist(text)
    assert "5" in str(ei.value), (
        f"the reported 1-based line number must count physical lines (blanks/comments "
        f"included); expected 5, got {ei.value!r}"
    )


def test_b4_does_not_silently_drop():
    # a broken line must RAISE, never be quietly skipped leaving fewer patterns.
    good = lg.encode_pattern(r"\bOK\b")
    with pytest.raises(ValueError):
        lg.load_denylist("\n".join([good, "@@@notb64@@@", good]))


# ==========================================================================
# Behavior 5 -- clean text -> no findings (empty tuple)
# ==========================================================================
def test_b5_clean_text_no_findings():
    pats = lg.load_denylist("\n".join([lg.encode_pattern(r"\bALPHA\b"),
                                       lg.encode_pattern(r"\bBETA\b")]))
    r = lg.scan_text("nothing to see here\njust ordinary prose\n", pats)
    assert r == (), f"clean text must yield an empty tuple; got {r!r}"
    assert lg.scan_text("", pats) == (), "empty text must yield an empty tuple"


# ==========================================================================
# Behavior 6 -- finding report shape
# ==========================================================================
def test_b6_line_numbers_and_snippets():
    pats = lg.load_denylist(lg.encode_pattern(r"\bHIT\b"))
    text = "line one\nHIT here\nline three\nalso HIT\nline five"
    r = lg.scan_text(text, pats)
    assert r == ((2, "HIT here"), (4, "also HIT")), (
        f"scan_text must return 1-based line numbers in ascending source order with "
        f"stripped snippets; got {r!r}"
    )
    assert isinstance(r, tuple) and all(isinstance(rec, tuple) and len(rec) == 2 for rec in r)


def test_b6_at_most_one_record_per_line():
    # two DIFFERENT patterns both match line 1 -> a single record for that line.
    pats = lg.load_denylist("\n".join([lg.encode_pattern(r"\bHIT\b"),
                                       lg.encode_pattern(r"\bALSO\b")]))
    r = lg.scan_text("HIT and ALSO on one line", pats)
    assert len(r) == 1, f"at most one record per matching line even if several patterns hit; got {r!r}"
    assert r[0][0] == 1


def test_b6_snippet_stripped_and_truncated():
    pats = lg.load_denylist(lg.encode_pattern(r"\bHIT\b"))
    r = lg.scan_text("   HIT padded   ", pats)
    assert r[0][1] == "HIT padded", f"snippet must be whitespace-stripped; got {r[0][1]!r}"
    long_line = "HIT " + ("x" * 200)
    r2 = lg.scan_text(long_line, pats)
    assert len(r2[0][1]) == 90, f"snippet must be truncated to 90 chars; got len {len(r2[0][1])}"


# ==========================================================================
# Behavior 7 -- token-aware (benign words are not false positives)
# ==========================================================================
def test_b7_token_aware():
    pats = lg.load_denylist(lg.encode_pattern(r"(?<![A-Za-z])zap(?![A-Za-z])"))
    assert lg.scan_text("zap", pats), "a standalone token must flag"
    assert lg.scan_text("run zap now", pats), "a token bounded by spaces must flag"
    assert lg.scan_text("zapper", pats) == (), "a longer word containing the token must NOT flag"
    assert lg.scan_text("unzap", pats) == (), "a prefixed word must NOT flag"
    assert lg.scan_text("bezapper", pats) == (), "an embedded token must NOT flag"


# ==========================================================================
# Behavior 8 -- self-leak-safe (the committed guard is clean)
# ==========================================================================
def test_b8_committed_denylist_populated():
    committed = lg.load_denylist(lg.DENYLIST_PATH.read_text())
    assert len(committed) >= 1, "the committed denylist must be populated (>=1 pattern)"
    assert all(isinstance(p, re.Pattern) for p in committed)


def test_b8_committed_files_scan_clean():
    # feed the raw text of BOTH committed files to scan_text as DATA -- neither
    # may contain any token the denylist is built to catch. This assertion holds
    # no raw sensitive token itself.
    committed = lg.load_denylist(lg.DENYLIST_PATH.read_text())
    guard_text = (_ROOT / "scripts" / "leak_guard.py").read_text()
    deny_text = lg.DENYLIST_PATH.read_text()
    r_guard = lg.scan_text(guard_text, committed)
    r_deny = lg.scan_text(deny_text, committed)
    assert r_guard == (), f"scripts/leak_guard.py must scan clean; findings at lines {[n for n, _ in r_guard]}"
    assert r_deny == (), f"scripts/leak_denylist.txt must scan clean; findings at lines {[n for n, _ in r_deny]}"


def test_b8_committed_patterns_are_live_matchers():
    # Prove the loaded committed set is a set of LIVE matchers, not inert no-op
    # regexes (a bug that compiled patterns matching nothing would ALSO scan
    # clean). For every committed pattern that reduces to a plain literal, that
    # literal must match. The literal core is computed IN MEMORY at runtime from
    # the compiled pattern and is NEVER written into this file's source, so no
    # raw needle appears in this test.
    committed = lg.load_denylist(lg.DENYLIST_PATH.read_text())
    live = 0
    for p in committed:
        core = re.sub(r"\(\?<![^)]*\)", "", p.pattern)   # strip lookbehind
        core = re.sub(r"\(\?![^)]*\)", "", core)         # strip lookahead
        core = core.replace(r"\b", "").replace(r"\.", ".")
        core = core.replace(r"\-", "-").replace(r"\_", "_")
        if not re.search(r"[\\\[\](){}?*+^$|]", core):   # reduced to a plain literal
            assert p.search(core), "a committed pattern failed to match its own literal core (inert?)"
            live += 1
    assert live >= 1, "at least one committed pattern must be provably live"


# ==========================================================================
# Behavior 9 -- dormant, off the control path, offline, stdlib-only
# ==========================================================================
def test_b9_import_foundry_dispatcher_ok():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b9_foundry_dispatcher_do_not_reference_leak_guard():
    # run in a FRESH interpreter (this test process already imported leak_guard):
    # importing foundry/dispatcher must not pull in leak_guard, and neither
    # module namespace may reference a leak_guard symbol.
    probe = (
        "import sys; import foundry, dispatcher; "
        "print('LG_IMPORTED' if 'leak_guard' in sys.modules else 'LG_ABSENT'); "
        "ns = 'leak_guard' in vars(foundry) or 'leak_guard' in vars(dispatcher); "
        "print('REFERENCED' if ns else 'UNREFERENCED')"
    )
    r = subprocess.run([sys.executable, "-c", probe], cwd=str(_ROOT),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "LG_ABSENT" in r.stdout, (
        f"importing foundry/dispatcher must NOT import leak_guard (dormant); stdout={r.stdout!r}"
    )
    assert "UNREFERENCED" in r.stdout, (
        f"neither foundry nor dispatcher may reference a leak_guard symbol; stdout={r.stdout!r}"
    )


def test_b9_pure_functions_write_no_file(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    cwd = os.getcwd()
    os.chdir(work)
    try:
        before = set(os.listdir(work))
        lg.encode_pattern(r"\bX\b")
        pats = lg.load_denylist(lg.encode_pattern(r"\bY\b"))
        lg.scan_text("Y appears here\nnothing else", pats)
        after = set(os.listdir(work))
    finally:
        os.chdir(cwd)
    assert before == after, f"pure functions must write no file; created {after - before}"


def test_b9_imports_are_stdlib_only():
    mods = {v.__name__.split(".")[0] for v in vars(lg).values()
            if isinstance(v, types.ModuleType)}
    nonstd = sorted(m for m in mods if m not in sys.stdlib_module_names)
    assert nonstd == [], f"leak_guard must import only stdlib modules; non-stdlib: {nonstd}"
