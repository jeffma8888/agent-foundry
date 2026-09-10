"""Black-box behaviour tests for iter 322 -- the SCOPED per-loop infra-cooldown claim.

The iteration's product is a doc-vs-code scoping repair on the foundry's own
inviolable-invariant text: `ARCHITECTURE.md`'s Resilience bullet promised a
per-loop cooldown ladder unconditionally, while the ladder lives only in
`run_continuous` and the SUPPORTED entry point (`launch.sh` -> `dispatcher.py`)
has none. Two new pure, DORMANT functions -- `infra_cooldown_owners` and
`cooldown_claim_scope_gaps` -- police the scoping so the prose cannot drift
back.

ISOLATION CONTRACT (honored): every assertion below was derived from the PM
spec's Expected Behaviors 1-8 (`pm.md` in this iteration's state dir) and from
the conventions of the existing modules under `tests/`. The engineer's notes,
the reviewer's notes and `git diff` were NOT read, and the implementation LOGIC
of the two new functions was NOT read -- they are driven as black boxes through
their public signatures and their observable return values.

Fully offline and deterministic: no subprocess, no git, no network, no agent
run, no clock. Six of the eight behaviours run entirely on in-memory string
fixtures; the other two read TRACKED text assets located at RUNTIME from
`foundry.__file__` (never a source-literal absolute path, never a gitignored
`state/` path, never a count of ambient files).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402


# --------------------------------------------------------------------------
# runtime-built paths (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent

OWNERS_FN_NAME = "infra_cooldown_owners"
GAPS_FN_NAME = "cooldown_claim_scope_gaps"


def _read(*parts):
    return _ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _owners_fn():
    fn = getattr(foundry, OWNERS_FN_NAME, None)
    assert callable(fn), f"foundry.{OWNERS_FN_NAME} must be a module-level callable"
    return fn


def _gaps_fn():
    fn = getattr(foundry, GAPS_FN_NAME, None)
    assert callable(fn), f"foundry.{GAPS_FN_NAME} must be a module-level callable"
    return fn


def _assert_str_tuple(got):
    assert isinstance(got, tuple), f"expected a tuple, got {type(got).__name__}: {got!r}"
    assert all(isinstance(x, str) for x in got), f"every member must be str: {got!r}"


def _assert_sorted_unique(got):
    _assert_str_tuple(got)
    assert list(got) == sorted(got), f"not sorted ascending: {got!r}"
    assert len(set(got)) == len(got), f"not de-duplicated: {got!r}"


# --------------------------------------------------------------------------
# Behaviour 1 -- module-level callable, one positional arg, NON-VACUITY FLOOR
# --------------------------------------------------------------------------
def test_b1_owners_is_module_level_callable_taking_one_positional():
    import inspect

    fn = _owners_fn()
    params = list(inspect.signature(fn).parameters.values())
    assert len(params) == 1, f"expected exactly one parameter, got {params}"
    assert params[0].kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ), f"the single parameter must be positional, got {params[0].kind}"


def test_b1_owners_on_shipping_foundry_is_exactly_run_continuous():
    """NON-VACUITY FLOOR -- every gap result below is worthless without this."""
    got = _owners_fn()(_read("foundry.py"))
    assert got == ("run_continuous",), got
    _assert_str_tuple(got)
    assert len(got) == 1, f"expected a 1-tuple, got {len(got)} members: {got!r}"


# --------------------------------------------------------------------------
# Behaviour 2 -- ownership is by NAME reference, never by text
# --------------------------------------------------------------------------
B2_FIXTURE = (
    "COOLDOWNS = [1]\n"
    "def prose():\n"
    '    """mentions COOLDOWNS."""\n'
    '    return "COOLDOWNS"\n'
    "def user():\n"
    "    return COOLDOWNS[0]\n"
)


def test_b2_prose_and_string_literals_never_make_an_owner():
    got = _owners_fn()(B2_FIXTURE)
    assert got == ("user",), got


def test_b2_scanner_cannot_report_itself_on_the_real_module():
    got = _owners_fn()(_read("foundry.py"))
    assert OWNERS_FN_NAME not in got, (
        f"the scanner reported itself -- the symbol must be held as a string "
        f"literal inside the function: {got!r}"
    )
    assert GAPS_FN_NAME not in got, got


# --------------------------------------------------------------------------
# Behaviour 3 -- scoping is STRUCTURAL over the module body
# --------------------------------------------------------------------------
B3_FIXTURE = (
    "COOLDOWNS = [1]\n"
    "class K:\n"
    "    def m(self):\n"
    "        return COOLDOWNS\n"
    "def outer():\n"
    "    def inner():\n"
    "        return COOLDOWNS\n"
    "async def acoro():\n"
    "    return COOLDOWNS\n"
)


def test_b3_nested_and_method_defs_are_never_owners_in_their_own_right():
    got = _owners_fn()(B3_FIXTURE)
    assert got == ("acoro", "outer"), got
    assert "m" not in got, got
    assert "inner" not in got, got


# --------------------------------------------------------------------------
# Behaviour 4 -- total, honest when empty, never raises
# --------------------------------------------------------------------------
B4_EMPTY_CASES = [
    ("empty string", ""),
    ("None", None),
    ("int", 42),
    ("bytes", b"COOLDOWNS = 1"),
    # the spec's bytes fixture holds NO function defs, so it cannot tell a
    # str-type-check apart from an empty parse; this one can.
    ("bytes with a real owner def", b"COOLDOWNS=[1]\ndef u():\n    return COOLDOWNS\n"),
    ("unparseable", "def (:"),
    ("valid module, no reference", "X = 1\ndef f():\n    return X\n"),
]


def test_b4_owners_is_total_and_returns_empty_tuple_for_every_unusable_input():
    fn = _owners_fn()
    for label, value in B4_EMPTY_CASES:
        got = fn(value)
        assert got == (), f"{label}: expected (), got {got!r}"
        _assert_str_tuple(got)


def test_b4_owners_result_is_sorted_deduplicated_deterministic_and_non_mutating():
    fn = _owners_fn()
    src = (
        "COOLDOWNS = [1]\n"
        "def zeta():\n"
        "    return COOLDOWNS\n"
        "def alpha():\n"
        "    x = COOLDOWNS\n"
        "    y = COOLDOWNS\n"
        "    return (x, y)\n"
        "def mid():\n"
        "    return len(COOLDOWNS)\n"
    )
    before = src
    got = fn(src)
    assert got == ("alpha", "mid", "zeta"), got
    _assert_sorted_unique(got)
    assert fn(src) == got, "two calls on the same input must compare =="
    assert src == before, "the argument was mutated"


# --------------------------------------------------------------------------
# Behaviour 5 -- gaps are scoped to the markdown LIST ITEM holding the anchor
# --------------------------------------------------------------------------
def test_b5_name_in_the_same_item_including_continuation_lines_is_clean():
    got = _gaps_fn()(
        ("run_continuous",),
        "- a\n- b 30m x\n  y run_continuous\n- c\n",
        anchor="30m",
    )
    assert got == (), got


def test_b5_name_in_a_different_item_does_not_scope_the_claim():
    got = _gaps_fn()(
        ("run_continuous",),
        "- a run_continuous\n- b 30m x\n- c\n",
        anchor="30m",
    )
    assert got == ("run_continuous",), got


def test_b5_marker_flavours_and_anchor_on_a_continuation_line():
    fn = _gaps_fn()
    # numbered marker: the name sits in a DIFFERENT item -> reported
    assert fn(
        ("run_continuous",), "1. claim 30m here\n2. other run_continuous\n", anchor="30m"
    ) == ("run_continuous",)
    # numbered marker: same item -> clean
    assert (
        fn(("run_continuous",), "1. claim 30m run_continuous\n2. other\n", anchor="30m")
        == ()
    )
    # '*' and '+' markers are recognised the same way
    assert fn(("run_continuous",), "* a run_continuous\n* b 30m\n", anchor="30m") == (
        "run_continuous",
    )
    assert fn(("run_continuous",), "+ a 30m run_continuous\n+ b\n", anchor="30m") == ()
    # anchor found on a CONTINUATION line -> the item is the marker line above it
    assert (
        fn(
            ("run_continuous",),
            "- a\n- b x\n  y 30m run_continuous\n- c\n",
            anchor="30m",
        )
        == ()
    )
    assert fn(
        ("run_continuous",), "- a run_continuous\n- b x\n  y 30m\n- c\n", anchor="30m"
    ) == ("run_continuous",)


def test_b5_matching_is_case_sensitive_verbatim_substring():
    fn = _gaps_fn()
    assert fn(("run_continuous",), "- claim 30m RUN_CONTINUOUS\n", anchor="30m") == (
        "run_continuous",
    )
    # a verbatim substring inside a longer token still counts as present
    assert fn(("run_continuous",), "- claim 30m foundry.run_continuous()\n", anchor="30m") == ()


def test_b5_result_is_sorted_and_deduplicated():
    got = _gaps_fn()(["zeta", "alpha", "alpha", "mid"], "- claim 30m mid\n", anchor="30m")
    assert got == ("alpha", "zeta"), got
    _assert_sorted_unique(got)


def test_b5_owners_argument_is_not_mutated():
    fn = _gaps_fn()
    owners = ["zeta", "alpha", "alpha"]
    snapshot = list(owners)
    doc = "- claim 30m x\n"
    fn(owners, doc, anchor="30m")
    assert owners == snapshot, f"owners was mutated: {owners!r}"
    assert fn(owners, doc, anchor="30m") == fn(owners, doc, anchor="30m")


# --------------------------------------------------------------------------
# Behaviour 6 -- fail CLOSED, never a vacuous pass; never raises
# --------------------------------------------------------------------------
FULL = ("alpha", "zeta")


def test_b6_unusable_doc_or_anchor_returns_the_full_sorted_owners_tuple():
    fn = _gaps_fn()
    unusable = [
        ("anchor absent", "- a alpha zeta\n- b\n", "30m"),
        ("empty doc", "", "30m"),
        ("doc is None", None, "30m"),
        ("doc is int", 7, "30m"),
        ("doc is bytes", b"- a 30m alpha zeta\n", "30m"),
        ("empty anchor", "- a 30m alpha zeta\n", ""),
        ("anchor is None", "- a 30m alpha zeta\n", None),
        ("anchor is int", "- a 30m alpha zeta\n", 7),
    ]
    for label, doc, anchor in unusable:
        got = fn(["zeta", "alpha"], doc, anchor=anchor)
        assert got == FULL, f"{label}: expected {FULL}, got {got!r}"
        _assert_sorted_unique(got)


def test_b6_empty_or_non_iterable_owners_is_clean_whatever_the_doc_says():
    fn = _gaps_fn()
    for owners in ((), [], set(), None, 42, 3.5, object()):
        for doc, anchor in (("", "30m"), (None, None), ("- a 30m\n", "30m")):
            got = fn(owners, doc, anchor=anchor)
            assert got == (), f"owners={owners!r} doc={doc!r}: expected (), got {got!r}"


def test_b6_anchor_is_keyword_only():
    import inspect

    params = list(inspect.signature(_gaps_fn()).parameters.values())
    by_name = {p.name: p for p in params}
    assert "anchor" in by_name, params
    assert by_name["anchor"].kind is inspect.Parameter.KEYWORD_ONLY, by_name["anchor"].kind


# --------------------------------------------------------------------------
# Behaviour 7 -- the SHIPPING tree is clean on all three docs
# --------------------------------------------------------------------------
def _line_hits(text, needle):
    return [i + 1 for i, line in enumerate(text.splitlines()) if needle in line]


def test_b7_all_three_shipped_docs_scope_the_claim():
    owners = _owners_fn()(_read("foundry.py"))
    assert owners == ("run_continuous",), f"non-vacuity floor broke: {owners!r}"
    fn = _gaps_fn()
    for name, anchor in (
        ("ARCHITECTURE.md", "30m"),
        ("CONTINUOUS.md", "30m"),
        ("README.md", "infra-cooldown"),
    ):
        got = fn(owners, _read(name), anchor=anchor)
        assert got == (), f"{name} (anchor {anchor!r}) is unscoped: {got!r}"


def test_b7_each_anchor_occurs_on_exactly_one_line_so_it_cannot_be_retargeted():
    for name, anchor in (
        ("ARCHITECTURE.md", "30m"),
        ("CONTINUOUS.md", "30m"),
        ("README.md", "infra-cooldown"),
    ):
        hits = _line_hits(_read(name), anchor)
        assert len(hits) == 1, f"{name}: {anchor!r} must occur on exactly 1 line, got {hits}"


def test_b7_the_unqualified_per_loop_claim_is_gone_from_architecture():
    text = _read("ARCHITECTURE.md")
    assert "Per loop: after 2 consecutive" not in text
    # the ladder literal and the owner name both survive in the same document
    assert "30m" in text
    assert "run_continuous" in text


# --------------------------------------------------------------------------
# Behaviour 8 -- dormant and resume-safe
# --------------------------------------------------------------------------
def test_b8_both_new_functions_have_zero_call_sites_in_foundry():
    src = _read("foundry.py")
    for symbol in (OWNERS_FN_NAME, GAPS_FN_NAME):
        got = foundry.call_site_count(src, symbol=symbol)
        assert got == 0, f"{symbol} must be dormant, call_site_count={got!r}"
    # NON-VACUITY FLOOR for the dormancy oracle itself: a symbol that IS called
    # must count above zero, otherwise the two zeros above prove nothing.
    live = foundry.call_site_count(src, symbol="run_iteration")
    assert isinstance(live, int) and live > 0, f"dormancy oracle is vacuous: {live!r}"


def test_b8_neither_name_leaks_into_the_pipeline_surfaces():
    surfaces = ["dispatcher.py", "watchdog.py", "launch.sh"]
    surfaces += [
        str(p.relative_to(_ROOT)) for p in sorted((_ROOT / "roles").glob("*.md"))
    ]
    for rel in surfaces:
        text = _read(rel)
        for symbol in (OWNERS_FN_NAME, GAPS_FN_NAME):
            assert symbol not in text, f"{rel} references {symbol}"


def test_b8_the_dispatcher_still_has_no_ladder():
    text = _read("dispatcher.py")
    assert "COOLDOWNS" not in text
    assert _owners_fn()(text) == ()


def test_b8_both_modules_still_import():
    import importlib

    for name in ("foundry", "dispatcher"):
        assert importlib.import_module(name) is not None
