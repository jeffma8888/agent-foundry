"""Black-box behaviour tests for iter 326 -- `foundry.symbol_dormancy_class`.

The iteration's product is one pure, total, module-level oracle in `foundry.py`
that answers "is this symbol really dormant?" by counting NON-CALL references
across source CLASSES, returning exactly one of `live`, `unparseable`,
`test-only`, `prose-only`, `dormant`. It closes two measured blind spots of the
repo's only prior dormancy primitive (`call_site_count`, which counts `ast.Call`
nodes in ONE source): a symbol whose only consumer is `tests/`, and a symbol
reached through a STRING constant plus `getattr`.

ISOLATION CONTRACT (honored): every assertion below was derived from the PM
spec's Expected Behaviors 1-9 (`pm.md` in this iteration's state dir) and from
the conventions of the existing modules under `tests/`. The engineer's notes,
the reviewer's notes, the implementation patch and `git diff` were NOT read, and
the LOGIC of the new function was NOT read -- it is driven as a BLACK BOX
through its public keyword-only signature and its observable return word.

Behaviours 1-7 run entirely on in-memory string fixtures: no `tmp_path`, no
git, no subprocess, no network, no clock. Behaviours 8-9 read TRACKED text
assets located at RUNTIME from `foundry.__file__` (never a source-literal
absolute path, never a gitignored `state/` path, never a count of ambient
files), so they hold in a throwaway fresh clone.
"""
import inspect
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402


# --------------------------------------------------------------------------
# runtime-built paths (never a source-literal home path) + shared fixtures
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent

FN_NAME = "symbol_dormancy_class"
CLASSES = frozenset({"live", "unparseable", "test-only", "prose-only", "dormant"})

# the three PRODUCTION modules named by Behaviour 8, and the doc/script classes
# named by Behaviour 9 -- relative names only, resolved off `_ROOT` at runtime.
PRODUCTION_MODULES = ("foundry.py", "dispatcher.py", "watchdog.py")

# adversarial-but-legal sources reused by several behaviours
SRC_BAD_SYNTAX = "def (:\n"
SRC_NUL = "x = 1\x00"
SRC_DEEP = "x = " + "1+" * 10000 + "1"  # RecursionError during AST construction


class _Stringy:
    """A non-`str` member of `production`/`tests` (Behaviour 7)."""

    def __init__(self, text):
        self._text = text

    def __str__(self):
        return self._text


def _fn():
    fn = getattr(foundry, FN_NAME, None)
    assert callable(fn), f"foundry.{FN_NAME} must be a module-level callable"
    return fn


def _classify(**kwargs):
    """Drive the oracle and enforce the Behaviour-1 return contract every time."""
    got = _fn()(**kwargs)
    assert isinstance(got, str), f"expected a str, got {type(got).__name__}: {got!r}"
    assert got in CLASSES, \
        f"return word must be one of {sorted(CLASSES)}, got {got!r}"
    return got


def _read(*parts):
    return _ROOT.joinpath(*parts).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Behaviour 1 -- module-level callable, KEYWORD-ONLY params, closed return set
# --------------------------------------------------------------------------
def test_b1_is_module_level_callable_with_four_keyword_only_params():
    params = inspect.signature(_fn()).parameters
    assert list(params) == ["symbol", "production", "tests", "prose"], \
        f"parameter names/order must match the spec, got {list(params)}"
    for name, p in params.items():
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, \
            f"parameter {name!r} must be KEYWORD-ONLY, got {p.kind}"


def test_b1_symbol_is_required_and_the_other_three_default_to_empty():
    params = inspect.signature(_fn()).parameters
    assert params["symbol"].default is inspect.Parameter.empty, \
        "`symbol` must be required -- the question is meaningless without it"
    assert _classify(symbol="foo") == "dormant", \
        "production/tests/prose must default to empty, so a bare symbol is dormant"


def test_b1_rejects_positional_arguments():
    with pytest.raises(TypeError):
        _fn()("foo")


def test_b1_production_and_tests_take_source_TEXT_not_paths():
    # `role_card_doc_gaps`' contract: iterables of source text. A path-shaped
    # string is just text that happens to name a file and is never opened, so it
    # contributes no reference (if it were opened, `foundry.py` holds `foo`).
    assert _classify(symbol="foo", production=("foundry.py",)) == "dormant", \
        "a path-shaped member must be read as TEXT, never opened"


@pytest.mark.parametrize("wrap", [tuple, list, iter, lambda xs: (x for x in xs)])
def test_b1_accepts_any_iterable_of_sources(wrap):
    assert _classify(symbol="foo", production=wrap(["bar = foo\n"])) == "live"


def test_b1_every_class_word_is_reachable():
    reached = {
        _classify(symbol="foo", production=("foo()\n",)),
        _classify(symbol="foo", production=(SRC_BAD_SYNTAX,)),
        _classify(symbol="foo", tests=("foo()\n",)),
        _classify(symbol="foo", prose="foo\n"),
        _classify(symbol="foo"),
    }
    assert reached == CLASSES, \
        f"all five class words must be reachable, missing {sorted(CLASSES - reached)}"


# --------------------------------------------------------------------------
# Behaviour 2 -- zero references anywhere -> dormant; a DEF/docstring/comment
# mention of the symbol is NOT a reference
# --------------------------------------------------------------------------
def test_b2_nothing_anywhere_is_dormant():
    assert _classify(symbol="foo", production=(), tests=(), prose="") == "dormant"


def test_b2_the_symbols_own_definition_is_not_a_reference():
    assert _classify(symbol="foo",
                     production=("def foo():\n    return 1\n",)) == "dormant", \
        "an ast.FunctionDef name is not an ast.Name -- a lone def is dormant"


def test_b2_a_docstring_or_hash_comment_mention_is_not_a_reference():
    src = '"""This module used to call foo() before iter 300."""\n# foo, retired\n'
    assert _classify(symbol="foo", production=(src,)) == "dormant", \
        "a docstring or comment mention must not make a symbol look live"


def test_b2_an_unreferenced_symbol_stays_dormant_beside_busy_sources():
    busy = ("import os\n\n\ndef helper(x):\n    return os.path.join(x, 'y')\n",
            "class Widget:\n    def run(self):\n        return helper(1)\n")
    assert _classify(symbol="foo", production=busy, tests=busy,
                     prose="a paragraph about widgets\n") == "dormant"


def test_b2_the_defining_source_plus_a_prose_mention_is_prose_only_not_live():
    # two-sided control for the def-is-not-a-reference rule: if the `def` line
    # counted, this would read `live` instead of `prose-only`.
    assert _classify(symbol="foo",
                     production=("def foo():\n    return 1\n",),
                     prose="foo is documented here\n") == "prose-only"


# --------------------------------------------------------------------------
# Behaviour 3 -- ANY production reference -> live, for all three reference
# shapes independently; `live` OUTRANKS every other class
# --------------------------------------------------------------------------
@pytest.mark.parametrize("src", [
    "foo()\n",                      # ast.Name, called
    "bar = foo\n",                  # ast.Name, bare binding (NOT a call)
    "mod.foo(x)\n",                 # ast.Attribute
    'x = "foo"\n',                  # ast.Constant holding a str
    "y = [foo, 1]\n",               # ast.Name inside a container
    "z = getattr(mod, 'foo')\n",    # str constant as a getattr target
])
def test_b3_each_reference_shape_in_production_reads_live(src):
    assert _classify(symbol="foo", production=(src,)) == "live", \
        f"reference shape must count as live: {src!r}"


def test_b3_a_reference_in_ANY_production_source_counts():
    srcs = ("import os\n", "def other():\n    return 2\n", "bar = foo\n")
    assert _classify(symbol="foo", production=srcs) == "live", \
        "the walk must cover every production source, not just the first"


def test_b3_live_outranks_unparseable_because_a_positive_is_decisive():
    assert _classify(symbol="foo", production=("foo()\n",),
                     tests=(SRC_BAD_SYNTAX,)) == "live", \
        "only a NEGATIVE finding needs a clean parse"


def test_b3_live_outranks_test_only_and_prose_only():
    assert _classify(symbol="foo", production=("bar = foo\n",),
                     tests=("foo()\n", SRC_BAD_SYNTAX),
                     prose="foo everywhere\n") == "live"


def test_b3_an_unparseable_production_source_cannot_hide_a_live_sibling():
    assert _classify(symbol="foo",
                     production=(SRC_BAD_SYNTAX, "mod.foo(1)\n")) == "live"


# --------------------------------------------------------------------------
# Behaviour 4 -- zero production references + >=1 tests reference -> test-only
# (the FIRST of the two blind spots this iteration closes)
# --------------------------------------------------------------------------
def test_b4_a_symbol_consumed_only_by_the_suite_is_test_only_not_dormant():
    got = _classify(symbol="foo", tests=("assert foo() == 1\n",))
    assert got == "test-only", f"expected test-only, got {got!r}"
    assert got != "dormant", "the whole point: a suite consumer is not dormancy"


def test_b4_the_defining_production_source_does_not_change_test_only():
    assert _classify(symbol="foo",
                     production=("def foo():\n    return 1\n",
                                 "# foo is not wired up yet\n"),
                     tests=("bar = foo\n",)) == "test-only"


def test_b4_a_symbol_reached_through_a_STRING_in_tests_is_test_only():
    # the second measured blind spot: `GAPS_FN_NAME = "..."` + getattr is
    # invisible to every ast.Call and ast.Name walk.
    src = 'FN = "foo"\n\n\ndef test_it():\n    assert callable(getattr(mod, FN))\n'
    assert _classify(symbol="foo", tests=(src,)) == "test-only"


def test_b4_the_string_branch_is_load_bearing_two_sided():
    # control: the SAME test source with the string spelled differently holds no
    # reference at all, so the class collapses to dormant. If the str-constant
    # branch were absent, the case above would read dormant too -- exactly the
    # false positive that produced four wrong dormancy findings.
    src = 'FN = "fo" + "o"\n\n\ndef test_it():\n    assert callable(getattr(mod, FN))\n'
    assert _classify(symbol="foo", tests=(src,)) == "dormant"


def test_b4_test_only_outranks_prose_only():
    assert _classify(symbol="foo", tests=("foo()\n",),
                     prose="foo is also mentioned in prose\n") == "test-only"


# --------------------------------------------------------------------------
# Behaviour 5 -- prose is PLAIN TEXT, never parsed; substring semantics
# --------------------------------------------------------------------------
def test_b5_a_prose_only_mention_is_prose_only():
    assert _classify(symbol="foo", prose="ARCHITECTURE.md names foo here\n") \
        == "prose-only"


@pytest.mark.parametrize("blob", [
    "[tool.pytest.ini_options]\naddopts = -q --foo\nnames = foo\n",   # TOML
    "## Heading\n\n- `foo` -- a bullet with backticks and *stars*\n",  # markdown
    "def (: foo\n",                                                   # bad python
    "{ this is not: json, foo }\n",                                   # junk
])
def test_b5_prose_is_never_parsed_so_it_can_never_be_unparseable(blob):
    got = _classify(symbol="foo", prose=blob)
    assert got == "prose-only", f"prose must be scanned as plain text, got {got!r}"


def test_b5_prose_uses_substring_semantics():
    assert _classify(symbol="foo", prose="foobar\n") == "prose-only", \
        "a longer word containing the symbol still counts (documented)"


def test_b5_prose_without_the_symbol_leaves_the_verdict_dormant():
    assert _classify(symbol="foo", prose="nothing relevant here\n") == "dormant"


def test_b5_prose_cannot_upgrade_a_code_reference():
    assert _classify(symbol="foo", production=("foo()\n",), prose="foo\n") == "live"


# --------------------------------------------------------------------------
# Behaviour 6 -- a source that does not parse -> unparseable (fail-CLOSED),
# NEVER dormant and never test-only
# --------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [SRC_BAD_SYNTAX, SRC_NUL, SRC_DEEP])
def test_b6_every_parse_failure_class_folds_to_one_word_in_production(bad):
    got = _classify(symbol="foo", production=(bad,))
    assert got == "unparseable", f"expected unparseable, got {got!r}"


@pytest.mark.parametrize("bad", [SRC_BAD_SYNTAX, SRC_NUL, SRC_DEEP])
def test_b6_every_parse_failure_class_folds_to_one_word_in_tests(bad):
    got = _classify(symbol="foo", tests=(bad,))
    assert got == "unparseable", f"expected unparseable, got {got!r}"
    assert got != "dormant" and got != "test-only", \
        "an unreadable source must never be reported as absence"


def test_b6_unparseable_outranks_test_only():
    assert _classify(symbol="foo", tests=("foo()\n", SRC_BAD_SYNTAX)) \
        == "unparseable", "spec: never `test-only` when a source did not parse"


def test_b6_unparseable_outranks_prose_only():
    assert _classify(symbol="foo", production=(SRC_BAD_SYNTAX,),
                     prose="foo\n") == "unparseable"


def test_b6_the_bad_sources_really_are_bad_two_sided_control():
    # keeps the three fixtures honest: each must fail `ast.parse`, else the
    # assertions above would pass for the wrong reason.
    import ast
    for bad in (SRC_BAD_SYNTAX, SRC_NUL, SRC_DEEP):
        with pytest.raises(BaseException):
            ast.parse(bad)
    ast.parse("foo()\n")  # and a good source must still parse


# --------------------------------------------------------------------------
# Behaviour 7 -- pure and TOTAL: never raises, no I/O, mutates nothing,
# deterministic
# --------------------------------------------------------------------------
@pytest.mark.parametrize("symbol", ["", None])
def test_b7_an_empty_or_none_symbol_is_dormant_because_nothing_is_named(symbol):
    assert _classify(symbol=symbol, production=("foo()\n",),
                     tests=("foo()\n",), prose="foo") == "dormant"


def test_b7_an_empty_symbol_is_not_matched_by_an_empty_string_constant():
    # `"" in anything` is True and an `ast.Constant` may hold `""`, so the
    # guard has to be explicit rather than emergent.
    assert _classify(symbol="", production=('x = ""\n',), prose="") == "dormant"


def test_b7_a_non_str_member_is_read_as_its_str_text():
    assert _classify(symbol="foo", production=(_Stringy("bar = foo\n"),)) == "live"
    assert _classify(symbol="foo", tests=(_Stringy("foo()\n"),)) == "test-only"
    assert _classify(symbol="foo", production=(_Stringy("bar = baz\n"),)) == "dormant"


def test_b7_none_iterables_and_none_prose_read_as_empty():
    assert _classify(symbol="foo", production=None, tests=None, prose=None) \
        == "dormant"


def test_b7_an_empty_source_parses_to_an_empty_module():
    assert _classify(symbol="foo", production=("",), tests=("", "")) == "dormant", \
        "'' must parse to an empty module, not fail closed as unparseable"


@pytest.mark.parametrize("kwargs", [
    dict(symbol="foo"),
    dict(symbol="foo", production=("foo()\n",), tests=("bar = foo\n",), prose="foo"),
    dict(symbol="foo", production=(SRC_BAD_SYNTAX,)),
    dict(symbol=None),
    dict(symbol="foo", production=(1, 2.5, None, b"foo()", ["foo"], {"foo": 1})),
    dict(symbol="foo", production=(_Stringy("@@@ not python @@@"),)),
    dict(symbol="\n", production=("foo()\n",)),
    dict(symbol="foo", prose=12345),
    dict(symbol=12345, production=("x = 12345\n",)),
    dict(symbol="foo", production="bar = foo\n"),  # a bare str IS iterable
])
def test_b7_total_never_raises_for_adversarial_input(kwargs):
    _classify(**kwargs)  # the helper already pins str-ness and the closed set


def test_b7_is_deterministic():
    kwargs = dict(symbol="foo", production=("bar = foo\n",),
                  tests=("foo()\n",), prose="foo")
    first = _classify(**kwargs)
    assert all(_classify(**kwargs) == first for _ in range(4))


def test_b7_mutates_no_argument():
    prod = ["bar = foo\n", "import os\n"]
    tests_arg = ["foo()\n"]
    before = (list(prod), list(tests_arg))
    _classify(symbol="foo", production=prod, tests=tests_arg, prose="foo")
    assert (prod, tests_arg) == before, "arguments must not be mutated"


def test_b7_performs_no_filesystem_subprocess_network_or_clock_io(monkeypatch):
    import builtins
    import os
    import socket
    import subprocess
    import time

    def boom(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("impure I/O attempted by a pure oracle")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(os, "system", boom)
    monkeypatch.setattr(time, "time", boom)
    monkeypatch.setattr(time, "monotonic", boom)
    monkeypatch.setattr(builtins, "open", boom)
    monkeypatch.setattr(pathlib.Path, "read_text", boom)
    monkeypatch.setattr(pathlib.Path, "open", boom)

    assert _classify(symbol="foo", production=("foundry.py", "bar = foo\n"),
                     tests=("tests/test_iter1_behavior.py",),
                     prose="foo") == "live"


# --------------------------------------------------------------------------
# Behaviour 8 -- live-tree, two-sided, fresh-clone-safe
# --------------------------------------------------------------------------
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


@pytest.mark.parametrize("symbol", ["retry_ladder_lines", "dispatch_restart_line"])
def test_b8_a_test_only_symbol_of_the_live_tree_is_not_dormant(symbol):
    production, tests_src = _live_tree_sources()
    got = _classify(symbol=symbol, production=production, tests=tests_src)
    assert got != "dormant", (
        f"{symbol} has real consumers under tests/, so the oracle must not "
        f"call it dormant -- got {got!r}"
    )


def test_b8_the_live_tree_call_is_not_vacuous_two_sided():
    # fail-open control: the SAME symbols read `dormant` once the tests sources
    # are withheld, which is precisely the under-count `call_site_count` makes.
    production, _ = _live_tree_sources()
    for symbol in ("retry_ladder_lines", "dispatch_restart_line"):
        assert _classify(symbol=symbol, production=production) == "dormant", \
            f"{symbol} must read dormant from production alone (the old blind spot)"


def test_b8_a_genuinely_wired_symbol_of_the_live_tree_is_live():
    production, tests_src = _live_tree_sources()
    assert _classify(symbol="dispatch_progress_line", production=production,
                     tests=tests_src) == "live"
    assert _classify(symbol="dispatch_progress_line",
                     production=production) == "live", \
        "a production consumer alone must be enough for `live`"


def test_b8_a_symbol_absent_from_the_whole_tree_is_dormant():
    production, tests_src = _live_tree_sources()
    # ASSEMBLED at runtime on purpose: a verbatim literal here would land in
    # `tests/`, i.e. inside the very corpus this census reads, and the probe
    # would find ITSELF and report `test-only`. (Observed, then fixed.)
    absent = "_".join(("zz", "dormancy", "probe", "absent"))
    assert absent not in pathlib.Path(__file__).read_text(encoding="utf-8"), \
        "the absent-symbol probe must not occur verbatim in this file"
    assert _classify(symbol=absent, production=production,
                     tests=tests_src) == "dormant"


# --------------------------------------------------------------------------
# Behaviour 9 -- additive-dormant: zero call sites, no reference outside
# `foundry.py` and `tests/`, so a loop in flight resumes byte-identically
# --------------------------------------------------------------------------
def test_b9_the_new_function_has_zero_call_sites_in_foundry():
    source = _read("foundry.py")
    assert foundry.call_site_count(source, symbol=FN_NAME) == 0, \
        f"{FN_NAME} must be DORMANT -- no call site may exist yet"
    assert FN_NAME in source, \
        "two-sided control: the symbol must actually be defined in foundry.py"


def test_b9_the_new_function_is_named_in_no_control_path_file():
    targets = [_ROOT / "dispatcher.py", _ROOT / "watchdog.py", _ROOT / "launch.sh"]
    targets += sorted(p for p in (_ROOT / "scripts").rglob("*") if p.is_file())
    targets += sorted((_ROOT / "roles").glob("*.md"))
    present = [p for p in targets if p.is_file()]
    assert len(present) >= 10, \
        f"expected the tracked control-path files, found {len(present)}"
    hits = sorted(str(p.relative_to(_ROOT)) for p in present
                  if FN_NAME in p.read_text(encoding="utf-8", errors="replace"))
    assert hits == [], f"{FN_NAME} must not appear in any control path: {hits}"


def test_b9_the_dormancy_oracle_agrees_that_it_is_itself_not_production_wired():
    production, tests_src = _live_tree_sources()
    assert _classify(symbol=FN_NAME, production=production) == "dormant", \
        "the oracle applied to itself must report no production reference"
    assert _classify(symbol=FN_NAME, production=production,
                     tests=tests_src) == "test-only", \
        "its only consumer this iteration is this very test module"
