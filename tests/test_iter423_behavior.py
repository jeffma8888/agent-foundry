"""Black-box behaviour tests for iter 423 -- memoized `dormancy_reference_names`.

The iteration's product is a throughput fix behind `foundry.symbol_dormancy_class`:
the per-source AST reference-name set is now computed by a new pure, total,
module-level helper `foundry.dormancy_reference_names(source)` backed by a
bounded `functools.lru_cache` (`foundry._dormancy_reference_names_cached`,
`maxsize == foundry.DORMANCY_PARSE_CACHE_SIZE`), so a multi-symbol census parses
each distinct source text ONCE per process instead of once per symbol. The
classifier's contract (input coercion, precedence order, prose substring rule,
exact AST string match) is unchanged; the differential test below proves it.

ISOLATION CONTRACT (honored): every assertion below is derived from the PM
spec's Expected Behaviors 1-10 (`pm.md` in this iteration's state dir) and from
the conventions of the existing modules under `tests/` (notably
`tests/test_iter326_behavior.py`, which pins the classifier's precedence and
coercion rules that `_old_classify` re-states here). The engineer's notes, the
reviewer's notes, the implementation patch and `git diff` were NOT read; the new
helper is driven as a BLACK BOX through its public signature and return value.

Behaviours 1-7, 9 and 10 run on in-memory string fixtures: no `tmp_path`, no
git, no subprocess, no network. Behaviour 8 reads TRACKED text assets located at
RUNTIME from `foundry.__file__` (foundry.py, dispatcher.py, watchdog.py and
`tests/test_*.py`; never a gitignored `state/` path), so it holds in a
throwaway fresh clone.
"""
import ast
import itertools
import pathlib
import sys
import time
import warnings

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402


# --------------------------------------------------------------------------
# runtime-built paths + shared fixtures
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent

HELPER = "dormancy_reference_names"
CACHED = "_dormancy_reference_names_cached"
CONST = "DORMANCY_PARSE_CACHE_SIZE"
CLASSES = frozenset({"live", "unparseable", "test-only", "prose-only", "dormant"})
PRODUCTION_MODULES = ("foundry.py", "dispatcher.py", "watchdog.py")

SRC_BAD_SYNTAX = "def (:"
SRC_NUL = "x = 1\x00"
SRC_DEEP = "x = " + "1+" * 10000 + "1"  # RecursionError during AST construction


class _Stringy:
    """A non-`str` member of `production`/`tests` (iter-326 Behaviour 7 pin)."""

    def __init__(self, text):
        self._text = text

    def __str__(self):
        return self._text


def _helper():
    fn = getattr(foundry, HELPER, None)
    assert callable(fn), f"foundry.{HELPER} must be a module-level callable"
    return fn


def _cached():
    fn = getattr(foundry, CACHED, None)
    assert fn is not None and hasattr(fn, "cache_info") and hasattr(fn, "cache_clear"), \
        f"foundry.{CACHED} must be an lru_cache-wrapped callable"
    return fn


def _classify(**kwargs):
    got = foundry.symbol_dormancy_class(**kwargs)
    assert isinstance(got, str) and got in CLASSES, \
        f"return word must be one of {sorted(CLASSES)}, got {got!r}"
    return got


def _live_tree_sources():
    production = []
    for name in PRODUCTION_MODULES:
        path = _ROOT / name
        assert path.is_file(), f"{name} must exist in any clone of this repo"
        production.append(path.read_text(encoding="utf-8"))
    test_paths = sorted((_ROOT / "tests").glob("test_*.py"))
    assert len(test_paths) > 100, \
        f"expected the tracked behaviour suite, found {len(test_paths)} modules"
    return production, [p.read_text(encoding="utf-8") for p in test_paths]


# --------------------------------------------------------------------------
# Behaviour 1 -- module-level callable; Name.id + Attribute.attr + str constants
# --------------------------------------------------------------------------
def test_b1_reference_names_collects_names_attrs_and_str_constants():
    got = _helper()("a.b.c()\nd('e')\nx = 5\n")
    assert got == frozenset({"a", "b", "c", "d", "e", "x"}), got
    assert isinstance(got, frozenset), type(got).__name__


def test_b1_non_str_constants_contribute_nothing():
    assert _helper()("x = 5\ny = 2.5\nz = None\nw = True\nb = b'q'\n") == \
        frozenset({"x", "y", "z", "w", "b"})


def test_b1_a_definition_name_is_not_a_reference():
    # an ast.FunctionDef / ClassDef name is neither a Name nor an Attribute
    assert _helper()("def foo():\n    return 1\nclass Bar:\n    pass\n") == frozenset()


def test_b1_docstrings_ARE_str_constants_but_comments_are_not():
    got = _helper()('"""doc"""\n# comment_token\n')
    assert "doc" in got, got
    assert "comment_token" not in got, got


# --------------------------------------------------------------------------
# Behaviour 2 -- unparseable -> None; empty module -> frozenset()
# --------------------------------------------------------------------------
def test_b2_unparseable_source_returns_none():
    assert _helper()(SRC_BAD_SYNTAX) is None


@pytest.mark.parametrize("bad", [SRC_BAD_SYNTAX, SRC_NUL, SRC_DEEP],
                         ids=["syntax", "nul", "deep"])
def test_b2_every_parse_failure_class_returns_none(bad):
    assert _helper()(bad) is None


def test_b2_empty_source_is_an_empty_module_not_none():
    got = _helper()("")
    assert got is not None, "'' parses to an empty module and must not read as broken"
    assert got == frozenset()


def test_b2_none_versus_empty_is_load_bearing():
    # two-sided: the two Behaviour-2 outcomes are distinct observable values
    assert _helper()(SRC_BAD_SYNTAX) != _helper()("")


# --------------------------------------------------------------------------
# Behaviour 3 -- total over any input
# --------------------------------------------------------------------------
def test_b3_none_reads_as_empty_module():
    assert _helper()(None) == frozenset()


def test_b3_int_reads_as_its_text():
    assert _helper()(5) == frozenset()


def test_b3_unhashable_input_does_not_raise():
    got = _helper()(["x()"])
    assert isinstance(got, frozenset), f"expected a frozenset, got {got!r}"


@pytest.mark.parametrize("junk", [
    ["x()"], {"a": 1}, {1, 2}, (1,), b"x()", object(), 3.5, True, float("nan"),
    _Stringy("foo()\n"), _Stringy("def (:"),
], ids=["list", "dict", "set", "tuple", "bytes", "object", "float", "bool",
        "nan", "stringy-ok", "stringy-bad"])
def test_b3_never_raises_and_returns_frozenset_or_none(junk):
    got = _helper()(junk)
    assert got is None or isinstance(got, frozenset), repr(got)


def test_b3_a_stringy_member_is_read_as_its_str_text():
    assert _helper()(_Stringy("foo()\n")) == frozenset({"foo"})
    assert _helper()(_Stringy("def (:")) is None


def test_b3_is_deterministic_and_pure():
    src = "a.b\nc('d')\n"
    first = _helper()(src)
    assert all(_helper()(src) == first for _ in range(5))
    assert src == "a.b\nc('d')\n"


# --------------------------------------------------------------------------
# Behaviour 4 -- memo: once per DISTINCT source text
# --------------------------------------------------------------------------
def test_b4_fifty_symbols_over_three_sources_parse_each_source_once():
    cached = _cached()
    cached.cache_clear()
    p1, p2, t1 = "a = 1\n", "b = 2\n", "c = 3\n"
    words = [_classify(symbol=f"sym{k}", production=[p1, p2], tests=[t1])
             for k in range(50)]
    info = cached.cache_info()
    assert info.misses == 3, info
    assert info.currsize == 3, info
    assert info.hits == 147, info
    assert set(words) == {"dormant"}, set(words)


def test_b4_identical_texts_share_one_slot():
    cached = _cached()
    cached.cache_clear()
    same = "z = 1\n"
    _classify(symbol="q", production=[same, same, same], tests=[same])
    info = cached.cache_info()
    assert info.misses == 1 and info.currsize == 1 and info.hits == 3, info


def test_b4_cache_clear_resets_the_counters_two_sided():
    cached = _cached()
    _helper()("k = 1\n")
    cached.cache_clear()
    info = cached.cache_info()
    assert info.hits == 0 and info.misses == 0 and info.currsize == 0, info


# --------------------------------------------------------------------------
# Behaviour 5 -- verdict equivalence on a hand-built corpus (all five words)
# --------------------------------------------------------------------------
def test_b5a_positive_production_finding_beats_a_broken_test_source():
    assert _classify(symbol="alpha", production=["alpha()"], tests=[SRC_BAD_SYNTAX]) \
        == "live"


def test_b5b_broken_production_beats_a_test_finding():
    assert _classify(symbol="delta", production=[SRC_BAD_SYNTAX], tests=["delta()"]) \
        == "unparseable"


def test_b5c_test_only():
    assert _classify(symbol="delta", production=["pass"], tests=["delta()"]) \
        == "test-only"


def test_b5d_prose_only():
    assert _classify(symbol="epsilon", production=["pass"], tests=["pass"],
                     prose="see epsilon here") == "prose-only"


def test_b5e_dormant():
    assert _classify(symbol="zeta", production=["pass"], tests=["pass"], prose="") \
        == "dormant"


def test_b5f_attribute_shape_is_live():
    assert _classify(symbol="beta", production=["mod.beta"]) == "live"


def test_b5g_ast_string_match_is_exact_but_prose_match_is_substring():
    assert _classify(symbol="gamma", production=["'gamma'"]) == "live"
    assert _classify(symbol="gamma", production=["'gammas'"]) == "dormant"
    assert _classify(symbol="gamma", production=["pass"], prose="gammas") == "prose-only"


def test_b5_all_five_words_are_reachable():
    seen = {
        _classify(symbol="alpha", production=["alpha()"], tests=[SRC_BAD_SYNTAX]),
        _classify(symbol="delta", production=[SRC_BAD_SYNTAX], tests=["delta()"]),
        _classify(symbol="delta", production=["pass"], tests=["delta()"]),
        _classify(symbol="epsilon", production=["pass"], prose="see epsilon here"),
        _classify(symbol="zeta", production=["pass"], prose=""),
    }
    assert seen == CLASSES, seen


# --------------------------------------------------------------------------
# Behaviour 6 -- differential proof against the pre-iter-423 algorithm
# --------------------------------------------------------------------------
def _old_refers(source, wanted):
    """Pre-423 per-source rule: parse, then any(...) over Name/Attribute/str-Constant.

    Returns True (found) / False (not found) / None (unparseable)."""
    try:
        tree = ast.parse(source)
        return any(
            (isinstance(n, ast.Name) and n.id == wanted)
            or (isinstance(n, ast.Attribute) and n.attr == wanted)
            or (isinstance(n, ast.Constant) and isinstance(n.value, str)
                and n.value == wanted)
            for n in ast.walk(tree)
        )
    except (SyntaxError, ValueError, RecursionError):
        return None


def _old_classify(*, symbol, production=(), tests=(), prose=""):
    """The pre-iter-423 classifier, re-stated from the iter-326 behaviour pins.

    Precedence live > unparseable > test-only > prose-only > dormant; None
    iterables/prose read as empty; members read via str(); '' symbol is dormant.
    """
    wanted = "" if symbol is None else str(symbol)
    if not wanted:
        return "dormant"
    unparseable = False
    for src in (production or ()):
        hit = _old_refers(str(src), wanted)
        if hit is None:
            unparseable = True
        elif hit:
            return "live"
    in_tests = False
    for src in (tests or ()):
        hit = _old_refers(str(src), wanted)
        if hit is None:
            unparseable = True
        elif hit:
            in_tests = True
    if unparseable:
        return "unparseable"
    if in_tests:
        return "test-only"
    if wanted in ("" if prose is None else str(prose)):
        return "prose-only"
    return "dormant"


def _shape(kind, sym):
    return {
        "name": f"{sym}()\n",
        "attribute": f"mod.{sym}\n",
        "constant": f"x = '{sym}'\n",
        "absent": "pass\n",
        "broken": SRC_BAD_SYNTAX,
    }[kind]


def _b6_grid():
    cases = []
    for sym, kind, place, has_prose in itertools.product(
            ("alpha", "beta"), ("name", "attribute", "constant", "absent", "broken"),
            ("production", "tests"), (True, False)):
        other = "pass\n"
        case = dict(symbol=sym,
                    production=[_shape(kind, sym)] if place == "production" else [other],
                    tests=[_shape(kind, sym)] if place == "tests" else [other],
                    prose=f"see {sym} here" if has_prose else "")
        cases.append(case)
    # mixed rows: coercion + multi-source + both placements
    cases += [
        dict(symbol="alpha", production=None, tests=None, prose=None),
        dict(symbol=None, production=["alpha()\n"], tests=["alpha()\n"], prose="alpha"),
        dict(symbol="", production=['x = ""\n'], prose=""),
        dict(symbol="alpha", production=(_Stringy("bar = alpha\n"),)),
        dict(symbol="alpha", tests=(_Stringy("alpha()\n"),)),
        dict(symbol="alpha", production=["pass\n", SRC_BAD_SYNTAX, "alpha()\n"]),
        dict(symbol="alpha", production=[SRC_NUL], tests=["alpha()\n"]),
        dict(symbol="alpha", production=["", ""], tests=[""], prose=""),
        dict(symbol="alpha", production=["'alphas'\n"], tests=["alpha\n"], prose="alphas"),
        dict(symbol="alpha", production=["def alpha():\n    return 1\n"], prose="alpha is documented"),
    ]
    return cases


_B6_CASES = _b6_grid()


def test_b6_grid_is_large_enough_and_reaches_all_five_words():
    assert len(_B6_CASES) >= 40, len(_B6_CASES)
    assert {_old_classify(**c) for c in _B6_CASES} == CLASSES


@pytest.mark.parametrize("case", _B6_CASES,
                         ids=[f"case{i}" for i in range(len(_B6_CASES))])
def test_b6_new_classifier_agrees_with_the_pre_423_algorithm(case):
    assert _classify(**case) == _old_classify(**case), case


def test_b6_old_oracle_is_itself_two_sided():
    # the re-stated old algorithm must not be a constant function
    assert _old_classify(symbol="a", production=["a()"]) == "live"
    assert _old_classify(symbol="a", production=["pass"]) == "dormant"


# --------------------------------------------------------------------------
# Behaviour 7 -- bare-name seam resolved at call time
# --------------------------------------------------------------------------
def test_b7_monkeypatched_helper_forces_live(monkeypatch):
    monkeypatch.setattr(foundry, HELPER, lambda source: frozenset({"ghost"}))
    assert _classify(symbol="ghost", production=["pass"]) == "live"


def test_b7_monkeypatched_helper_forces_unparseable(monkeypatch):
    monkeypatch.setattr(foundry, HELPER, lambda source: None)
    assert _classify(symbol="ghost", production=["pass"]) == "unparseable"


def test_b7_seam_is_load_bearing_two_sided():
    # without the patch the same call is dormant, so Behaviour 7's words
    # can only come from the seam being consulted at call time
    assert _classify(symbol="ghost", production=["pass"]) == "dormant"


def test_b7_seam_receives_each_source_text(monkeypatch):
    seen = []

    def spy(source):
        seen.append(source)
        return frozenset()

    monkeypatch.setattr(foundry, HELPER, spy)
    assert _classify(symbol="q", production=["a = 1\n", "b = 2\n"], tests=["c = 3\n"]) \
        == "dormant"
    assert seen == ["a = 1\n", "b = 2\n", "c = 3\n"], seen


# --------------------------------------------------------------------------
# Behaviour 8 -- once-per-source over the REAL tracked tree (throughput proof)
# --------------------------------------------------------------------------
def _first_200_top_level_names(foundry_text):
    tree = ast.parse(foundry_text)
    names = [n.name for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    assert len(names) >= 200, len(names)
    return names[:200]


def test_b8_real_tree_census_parses_each_distinct_source_exactly_once_and_is_fast():
    production, tests_src = _live_tree_sources()
    names = _first_200_top_level_names(production[0])
    distinct = len(set(production) | set(tests_src))
    cached = _cached()
    cached.cache_clear()

    t0 = time.perf_counter()
    first = [_classify(symbol=s, production=production, tests=tests_src, prose="")
             for s in names]
    cold = time.perf_counter() - t0
    info1 = cached.cache_info()
    assert info1.misses == distinct, (info1, distinct)
    assert cold < 20.0, f"200-symbol cold pass took {cold:.2f}s"

    t0 = time.perf_counter()
    second = [_classify(symbol=s, production=production, tests=tests_src, prose="")
              for s in names]
    warm = time.perf_counter() - t0
    info2 = cached.cache_info()
    assert info2.misses == info1.misses, (info1, info2)
    assert warm < 2.0, f"200-symbol warm pass took {warm:.2f}s"
    assert first == second


def test_b8_real_tree_words_are_not_vacuous():
    production, tests_src = _live_tree_sources()
    names = _first_200_top_level_names(production[0])
    words = {_classify(symbol=s, production=production, tests=tests_src, prose="")
             for s in names[:40]}
    assert "live" in words, words
    # built at runtime from fragments so no single str constant in THIS module
    # equals the name (a literal here would make it read `test-only`)
    absent = "_".join(("no", "such", "symbol", "iter423", "zz"))
    assert _classify(symbol=absent, production=production,
                     tests=tests_src, prose="") == "dormant"


# --------------------------------------------------------------------------
# Behaviour 9 -- bounded and transparent beyond the bound
# --------------------------------------------------------------------------
def test_b9_bound_constant_and_cache_maxsize_agree():
    assert getattr(foundry, CONST, None) == 1024
    assert _cached().cache_info().maxsize == foundry.DORMANCY_PARSE_CACHE_SIZE


def test_b9_eviction_never_changes_a_word():
    words = {_classify(symbol=f"s{k}", production=[f"s{k}()"]) for k in range(1100)}
    assert words == {"live"}, words


def test_b9_currsize_never_exceeds_the_bound():
    cached = _cached()
    cached.cache_clear()
    for k in range(1100):
        _helper()(f"s{k}()")
    info = cached.cache_info()
    assert info.currsize <= foundry.DORMANCY_PARSE_CACHE_SIZE, info
    assert info.misses == 1100, info


# --------------------------------------------------------------------------
# Behaviour 10 -- docstrings and import hygiene
# --------------------------------------------------------------------------
def test_b10_classifier_docstring_names_the_helper():
    assert "dormancy_reference_names" in (foundry.symbol_dormancy_class.__doc__ or "")


def test_b10_helper_docstring_is_ascii_and_names_the_rule_owner_and_none():
    doc = _helper().__doc__
    assert doc, "helper docstring must be non-empty"
    assert doc.isascii(), [c for c in doc if not c.isascii()]
    assert "_callee_trailing_name" in doc
    assert "None" in doc


def test_b10_foundry_compiles_clean_under_warnings_as_errors():
    # in-process analog of `python3 -W error -c "import foundry"`: a SyntaxWarning
    # (e.g. an invalid escape in a non-raw docstring) surfaces at compile time
    src = (_ROOT / "foundry.py").read_text(encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        code = compile(src, "foundry.py", "exec")
    # the module code object binds the new helper and its bound at TOP level
    assert HELPER in code.co_names, "helper must be a module-level def"
    assert CONST in code.co_names, "cache-size constant must be module-level"


def test_b10_helper_and_cache_are_module_level_and_distinct():
    assert _helper() is not _cached()
    assert callable(_cached())
