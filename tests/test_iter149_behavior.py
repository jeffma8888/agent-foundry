"""Black-box behaviour tests for iter 149 -- honest `quality_bar` invariant citations.

Spec: products/_platform/state/iter-149/pm.md, Expected Behaviors 1-12.

  1.  `quality_bar_invariants(bar)` is PURE and TOTAL and returns the names of the
      parenthesized list that follows `documented in <DOC>`, whitespace-stripped, in
      source order, empty fragments dropped.
  2.  it returns `()` for text with no citation (`""`, `"no citation here"`) and never
      raises on an UNBALANCED citation (`"documented in ARCHITECTURE.md (a, b"`).
  3.  `quality_bar_invariant_gaps(bar, doc)` is PURE and TOTAL and returns exactly the
      cited names NOT findable in `doc` (case-insensitive, whitespace-collapsed),
      in source order; names that ARE found are absent.
  4.  gaps is case-insensitive in BOTH directions.
  5.  gaps is whitespace-insensitive (a cited `pessimistic gate` matches
      `pessimistic\\ngate` and `pessimistic  gate`).
  6.  both functions are deterministic over 5 calls and mutate no argument.
  7.  LIVE TREE: the real `products/_platform/config.json` bar has ZERO gaps against the
      real `ARCHITECTURE.md`.
  8.  LIVE TREE anti-vacuity: that same live bar yields >= 5 cited names, so a future
      re-wording that breaks extraction turns the suite RED instead of making 7 vacuous.
  9.  LIVE TREE: the specific defect is gone -- the live bar contains neither
      `revert-on-doubt` nor `single-brain dispatch`, and DOES cite `resilience`.
  10. LIVE TREE two-sided proof: the live bar with one cited name replaced by
      `nonexistent-invariant` yields exactly `("nonexistent-invariant",)`.
  11. the `quality_bar` change is VALUE-ONLY: the config still parses as JSON, still
      loads through `load_config`, and its top-level key set is unchanged.
  12. `foundry` and `dispatcher` still import in a clean interpreter.

ISOLATION CONTRACT (HONORED): every check below was derived ONLY from the iter-149 PM
spec's Expected Behaviors, the pre-existing tests under `tests/` (chiefly
`tests/test_iter140_behavior.py` for the bytecode purity guard and
`tests/test_iter147_behavior.py` for the clean-interpreter import probe), and the
product's OWN observable behaviour by driving its public interface from a probe
interpreter. The implementation source of `foundry.py`, the engineer's and reviewer's
notes, and `git diff` were NOT read. The one exception, disclosed: the frozen
`CONFIG_TOP_LEVEL_KEYS` tuple below was measured from the pre-change COMMITTED config
via `git show HEAD:<config>` reduced to its KEY NAMES ONLY (never its values), because
behavior 11's "unchanged key set" has no other before-state; no implementation file was
read to obtain it. Zero network; the only subprocess is the two-module import probe.
Source is pure-ASCII: non-ASCII hostile input is built from escapes, never embedded.
"""
import json
import pathlib
import subprocess
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)

_ROOT = pathlib.Path(__file__).resolve().parents[1]
LIVE_CFG = _ROOT / "products" / "_platform" / "config.json"
LIVE_DOC = _ROOT / "ARCHITECTURE.md"

# The invariant names the spec's Acceptance Criteria require the live bar to cite.
REQUIRED_CITED = ("output-file success", "anti-delegation", "pessimistic gate",
                  "tester isolation", "resilience", "single-brain")

# The two names the iteration exists to remove -- neither is findable in ARCHITECTURE.md.
BANNED_IN_BAR = ("revert-on-doubt", "single-brain dispatch")

# Behavior 11 before-state: top-level keys of the PRE-CHANGE committed config, measured
# once from `git show HEAD:products/_platform/config.json` (key names only, no values).
# EXTENDED (not weakened) by iteration 192: `_platform` opted the external gap feed on, so the
# key set legitimately GREW by `gap_register` + `gap_layers`. The freeze stays an EXACT equality --
# the property iter 149 wanted was "no key silently appears or disappears", not "this file never
# gains a field" (same extend-don't-loosen move iter 188 made to iter 157's FROZEN_FIELDS).
CONFIG_TOP_LEVEL_KEYS = ("allowed_push_repo", "branch", "dual_pm_scouts", "gap_layers",
                         "gap_register", "name",
                         "push_enabled", "quality_bar", "quality_ref", "repo", "roadmap",
                         "roles_dir", "test_cmd", "vision", "work_root")

PLANTED = "nonexistent-invariant"

# names that would mean a "pure" helper reached the filesystem, a subprocess, the
# network or the clock (convention borrowed from tests/test_iter140_behavior.py)
IO_NAMES = frozenset({
    "open", "read_text", "write_text", "read_bytes", "write_bytes", "Path",
    "mkdir", "unlink", "remove", "rename", "load_config", "loads", "dump",
    "dumps", "subprocess", "check_output", "Popen", "urlopen", "socket",
    "requests", "input", "shutil", "glob", "sleep", "monotonic",
    "datetime", "now", "random", "environ", "getenv", "system", "popen",
})

# Inputs that must never raise (totality). Non-ASCII is built from escapes.
HOSTILE = [
    "", " ", "\n\n", "(", ")", "()", "no citation here",
    "documented in (",
    "documented in ARCHITECTURE.md (a, b",          # unbalanced
    "documented in ARCHITECTURE.md ()",             # empty citation
    "documented in ARCHITECTURE.md (,,,)",          # only separators
    "documented in ARCHITECTURE.md (((a)))",        # nested parens
    "documented in ARCHITECTURE.md (a) documented in ARCHITECTURE.md (b)",
    "documented in  ARCHITECTURE.md\t(a,\nb)",      # exotic whitespace
    "documented in ARCHITECTURE.md (\u00e9, \u4e2d)",   # non-ASCII names
    "x" * 5000,
]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
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


def _cited(bar):
    return foundry.quality_bar_invariants(bar)


def _gaps(bar, doc):
    return foundry.quality_bar_invariant_gaps(bar, doc)


def _live_bar():
    """The bar EXACTLY as build_prompt would inline it, via the public loader."""
    return foundry.load_config(str(LIVE_CFG)).quality_bar


def _live_doc():
    return LIVE_DOC.read_text()


def _bar(names, doc_name="ARCHITECTURE.md", prefix="", suffix=""):
    """A synthetic quality bar citing `names`, shaped like the real one."""
    return "%sdocumented in %s (%s).%s" % (prefix, doc_name, ", ".join(names), suffix)


# ==========================================================================
# Behavior 1 -- extraction: anchored, ordered, stripped, empties dropped
# ==========================================================================
def test_b1_extracts_the_cited_names_in_source_order():
    got = _cited(_bar(["a", "b", "c"]))
    assert got == ("a", "b", "c"), got
    assert isinstance(got, tuple) and all(isinstance(n, str) for n in got)


def test_b1_strips_surrounding_whitespace_and_drops_empty_names():
    assert _cited("documented in ARCHITECTURE.md ( a ,  b ,c )") == ("a", "b", "c")
    assert _cited("documented in ARCHITECTURE.md (a, , c)") == ("a", "c")
    assert _cited("documented in ARCHITECTURE.md (a, b,)") == ("a", "b")


def test_b1_is_anchored_past_an_earlier_parenthesized_group():
    """The real bar contains `importable (python -c import)` BEFORE the citation, so a
    naive first-`(...)` parse would return that instead and the brake would be nonsense."""
    bar = _bar(["x", "y"], prefix="must keep it importable (python -c import), and ")
    assert _cited(bar) == ("x", "y"), _cited(bar)
    assert "python -c import" not in _cited(bar)


def test_b1_is_pure_no_filesystem_subprocess_network_or_clock():
    for fn in (foundry.quality_bar_invariants, foundry.quality_bar_invariant_gaps):
        leaked = IO_NAMES & _co_names_deep(fn)
        assert leaked == frozenset(), \
            "%s must be pure; it references %s" % (fn.__name__, sorted(leaked))


# ==========================================================================
# Behavior 2 -- no citation / unbalanced parens -> () and never raises
# ==========================================================================
def test_b2_no_citation_yields_an_empty_tuple():
    assert _cited("no citation here") == ()
    assert _cited("") == ()
    assert _cited("Improvements must keep tests/ green.") == ()


def test_b2_unbalanced_citation_yields_an_empty_tuple_without_raising():
    assert _cited("documented in ARCHITECTURE.md (a, b") == ()


def test_b2_totality_no_hostile_input_raises_from_either_function():
    for text in HOSTILE:
        got = _cited(text)
        assert isinstance(got, tuple), (text[:40], got)
        gaps = _gaps(text, "a b c")
        assert isinstance(gaps, tuple), (text[:40], gaps)
        # every reported gap is one of the extracted names
        assert set(gaps) <= set(got), (text[:40], got, gaps)


def test_b2_gaps_tolerates_a_hostile_doc_too():
    for doc in ("", " ", "\n", "(", "x" * 5000, "\u00e9"):
        assert isinstance(_gaps(_bar(["a"]), doc), tuple)


# ==========================================================================
# Behavior 3 -- gaps = cited names NOT findable in the doc, in source order
# ==========================================================================
def test_b3_reports_only_the_missing_names_in_source_order():
    bar = _bar(["alpha", "beta", "gamma", "delta"])
    doc = "we document beta here, and delta over there"
    assert _gaps(bar, doc) == ("alpha", "gamma")


def test_b3_a_fully_documented_bar_has_no_gaps():
    assert _gaps(_bar(["alpha", "beta"]), "alpha and beta are documented") == ()


def test_b3_an_empty_doc_leaves_every_cited_name_as_a_gap():
    assert _gaps(_bar(["alpha", "beta"]), "") == ("alpha", "beta")


def test_b3_no_citation_means_no_gaps():
    assert _gaps("no citation here", "") == ()
    assert _gaps("", "anything") == ()


# ==========================================================================
# Behavior 4 -- case-insensitive in BOTH directions
# ==========================================================================
def test_b4_case_insensitive_bar_against_lowercase_doc():
    assert _gaps(_bar(["Output-File Success"]), "output-file success") == ()


def test_b4_case_insensitive_lowercase_bar_against_shouting_doc():
    assert _gaps(_bar(["anti-delegation"]), "ANTI-DELEGATION") == ()
    assert _gaps(_bar(["TeStEr IsOlAtIoN"]), "tester ISOLATION") == ()


# ==========================================================================
# Behavior 5 -- whitespace-insensitive (runs collapse to one space)
# ==========================================================================
def test_b5_a_cited_name_matches_across_a_newline_in_the_doc():
    assert _gaps(_bar(["pessimistic gate"]), "Independent, pessimistic\ngate") == ()


def test_b5_a_cited_name_matches_a_doubled_space_and_a_tab_in_the_doc():
    assert _gaps(_bar(["pessimistic gate"]), "pessimistic  gate") == ()
    assert _gaps(_bar(["pessimistic gate"]), "pessimistic\tgate") == ()


def test_b5_whitespace_inside_the_cited_name_is_collapsed_too():
    assert _gaps("documented in ARCHITECTURE.md (pessimistic  gate)",
                 "pessimistic gate") == ()


def test_b5_collapsing_does_not_erase_a_real_difference():
    """Whitespace kindness must not become stemming: a name the doc lacks is a gap."""
    assert _gaps(_bar(["pessimistic gate"]), "pessimistic") == ("pessimistic gate",)


# ==========================================================================
# Behavior 6 -- deterministic, non-mutating
# ==========================================================================
def test_b6_five_calls_return_equal_results():
    bar, doc = _bar(["alpha", "beta"]), "beta only"
    assert len({_cited(bar) for _ in range(5)}) == 1
    assert len({_gaps(bar, doc) for _ in range(5)}) == 1
    assert _gaps(bar, doc) == ("alpha",)


def test_b6_arguments_are_not_mutated():
    bar, doc = _bar(["alpha", "beta"]), "beta only"
    before_bar, before_doc = bar[:], doc[:]
    _cited(bar)
    _gaps(bar, doc)
    assert bar == before_bar and doc == before_doc


def test_b6_live_calls_are_deterministic_too():
    bar, doc = _live_bar(), _live_doc()
    assert len({_cited(bar) for _ in range(5)}) == 1
    assert len({_gaps(bar, doc) for _ in range(5)}) == 1


# ==========================================================================
# Behavior 7 -- LIVE TREE: the shipped fix, zero gaps
# ==========================================================================
def test_b7_live_bar_cites_only_names_findable_in_architecture_md():
    gaps = _gaps(_live_bar(), _live_doc())
    assert gaps == (), "live quality_bar cites names absent from ARCHITECTURE.md: %s" % (gaps,)


# ==========================================================================
# Behavior 8 -- LIVE TREE anti-vacuity: the guard must be ABLE to fail
# ==========================================================================
def test_b8_live_bar_extraction_is_non_empty_so_behavior_7_is_not_vacuous():
    cited = _cited(_live_bar())
    assert len(cited) >= 5, \
        "extraction yielded %d name(s) %s -- behavior 7 would be vacuously green" % (
            len(cited), cited)
    assert all(n and n.strip() == n for n in cited), cited


def test_b8_the_documented_vacuity_risk_is_named_in_the_docstrings():
    """Acceptance criterion: the docstrings must name the vacuity risk of behavior 8."""
    docs = " ".join((foundry.quality_bar_invariants.__doc__ or "",
                     foundry.quality_bar_invariant_gaps.__doc__ or "")).lower()
    assert docs.strip(), "both helpers must carry docstrings"
    assert "vacu" in docs, "no helper docstring names the vacuity risk"


def test_b8_every_required_invariant_name_is_cited():
    cited = _cited(_live_bar())
    missing = [n for n in REQUIRED_CITED if n not in cited]
    assert missing == [], "live bar no longer cites %s (cited: %s)" % (missing, cited)


# ==========================================================================
# Behavior 9 -- LIVE TREE: the specific defect is gone
# ==========================================================================
def test_b9_live_bar_no_longer_names_the_two_unfindable_invariants():
    low = _live_bar().lower()
    for banned in BANNED_IN_BAR:
        assert banned.lower() not in low, "live quality_bar still names %r" % (banned,)


def test_b9_live_bar_cites_the_real_resilience_invariant():
    assert "resilience" in [n.lower() for n in _cited(_live_bar())]
    assert "resilience" in _collapsed(_live_doc()), \
        "ARCHITECTURE.md does not carry `resilience` -- the citation would be a new gap"


def _collapsed(text):
    return " ".join(text.lower().split())


# ==========================================================================
# Behavior 10 -- LIVE TREE two-sided proof that behavior 7 bites
# ==========================================================================
def test_b10_a_planted_bad_name_in_the_live_bar_is_reported_as_the_only_gap():
    bar, doc = _live_bar(), _live_doc()
    cited = _cited(bar)
    assert cited, "nothing cited -- behavior 10 cannot be built"
    for name in cited:
        bad = bar.replace(name, PLANTED)
        assert bad != bar, name
        assert _gaps(bad, doc) == (PLANTED,), \
            "replacing %r did not yield exactly the planted gap: %s" % (
                name, _gaps(bad, doc))


def test_b10_the_planted_name_is_genuinely_absent_from_the_document():
    """Positive control for the negative result above."""
    assert PLANTED not in _collapsed(_live_doc())


# ==========================================================================
# Behavior 11 -- the config change is VALUE-ONLY
# ==========================================================================
def test_b11_live_config_still_parses_as_json():
    data = json.loads(LIVE_CFG.read_text())
    assert isinstance(data, dict) and data


def test_b11_top_level_key_set_is_unchanged():
    data = json.loads(LIVE_CFG.read_text())
    assert tuple(sorted(data)) == CONFIG_TOP_LEVEL_KEYS, sorted(data)


def test_b11_load_config_still_loads_the_live_config():
    cfg = foundry.load_config(str(LIVE_CFG))
    assert cfg.name == "_platform", cfg.name
    assert isinstance(cfg.quality_bar, str) and cfg.quality_bar.strip()
    assert cfg.test_cmd and cfg.repo and cfg.branch


# ==========================================================================
# Behavior 12 -- import safety
# ==========================================================================
def test_b12_bare_modules_import_in_a_clean_interpreter():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_b12_both_helpers_are_module_level_callables_on_foundry():
    for name in ("quality_bar_invariants", "quality_bar_invariant_gaps"):
        fn = getattr(foundry, name, None)
        assert callable(fn), "foundry.%s is missing or not callable" % name
        assert fn.__module__ == "foundry", (name, fn.__module__)
