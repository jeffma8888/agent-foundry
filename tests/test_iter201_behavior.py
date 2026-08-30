"""Black-box behaviour tests for iter 201 -- the anchored-sentinel rule is written ONCE.

The pessimistic gate decides ship-or-revert from three sentinel parsers
(`parse_postrelease_verdict`, `parse_review_verdict`, `parse_tester_result`). All three
ran ONE rule -- *the verdict is the token on the LAST non-empty line, else `None`* --
written three times, so a fix could be applied to two of them; and a false `None` there
reads to the gate as a MISSING verdict, which is the class that has destroyed nine green
iterations. This iteration collapses them onto one private pure core
`_sentinel_token(text, prefix, allowed)`.

Because the blast radius of a defect is 3x while the diff is 1x, the DELIVERABLE here is
the golden equivalence matrix: the 18 x 3 = 54 expected values in `MATRIX` below are the
values the PM measured against unmodified HEAD `16857fe` BEFORE any change, and they are
encoded here as LITERAL expectations -- never as a self-comparison against the new code,
and never re-derived from the current implementation.

ISOLATION CONTRACT (honored): this file was written from the iter-201 PM spec's Expected
Behaviors 1-11 and from the product's own OBSERVABLE behaviour ONLY. `foundry.py`'s
implementation source, the engineer's notes, the reviewer's notes, `IMPLEMENTATION.patch`
and `git diff` were NOT read. Every check drives the public runtime interface: calling the
four public parsers and the new core, `inspect.signature` / `__doc__` introspection, a
monkeypatched seam spy on `foundry._sentinel_token`, guard objects that make any I/O
raise, and a `python -c "import foundry, dispatcher"` subprocess probe. The one structural
check (behavior 9's collapse brake) is a STATEMENT COUNT taken with `ast`, which is the
measurement the spec itself prescribes; no assertion in this file was shaped by reading a
function body. Public-safety: every fixture string is synthetic and generic -- no machine
path, no personal identifier, no vendor product name.
"""
import ast
import inspect
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------
# the three (parser, prefix, T0, T1) triples -- behavior 7's documented pairs
# --------------------------------------------------------------------------
POSTRELEASE = ("parse_postrelease_verdict", "POSTRELEASE:", ("HEALTHY", "BROKEN"))
REVIEW = ("parse_review_verdict", "VERDICT:", ("APPROVE", "CHANGES_REQUIRED"))
TESTER = ("parse_tester_result", "RESULT:", ("PASS", "FAIL"))
TRIPLES = (POSTRELEASE, REVIEW, TESTER)

CORE = "_sentinel_token"


def parser(name):
    return getattr(foundry, name)


# --------------------------------------------------------------------------
# behavior 8 -- the golden equivalence matrix, 18 inputs x 3 parsers.
# Each row is (case number, builder(P, T0, T1) -> text, expected(T0, T1) -> value).
# Expected values are the PM's pre-change measurements, encoded literally.
# --------------------------------------------------------------------------
T0 = lambda t0, t1: t0  # noqa: E731
T1 = lambda t0, t1: t1  # noqa: E731
NONE = lambda t0, t1: None  # noqa: E731

MATRIX = (
    (1, lambda p, t0, t1: "", NONE),
    (2, lambda p, t0, t1: None, NONE),
    (3, lambda p, t0, t1: "   \n\t\n  ", NONE),
    (4, lambda p, t0, t1: f"{p} {t0}", T0),
    (5, lambda p, t0, t1: f"{p}{t0}", T0),
    (6, lambda p, t0, t1: f"  {p}   {t0}   ", T0),
    (7, lambda p, t0, t1: f"{p} {t0}\n\n\n   \n", T0),
    (8, lambda p, t0, t1: f"intro\r\n{p} {t0}\r\n", T0),
    (9, lambda p, t0, t1: f"\t   {p} {t0}", T0),
    (10, lambda p, t0, t1: f"{p} {t1}\n{p} {t0}", T0),
    (11, lambda p, t0, t1: f"{p} {t0}\nlooks good to me", NONE),
    (12, lambda p, t0, t1: f"{p} {t0} looks good", NONE),
    (13, lambda p, t0, t1: f"{p} " + t0.lower(), NONE),
    (14, lambda p, t0, t1: f"{p} MAYBE", NONE),
    (15, lambda p, t0, t1: f"{p}", NONE),
    (16, lambda p, t0, t1: f"{p} {t0} {t1}", NONE),
    (17, lambda p, t0, t1: f"X{p} {t0}", NONE),
    (18, lambda p, t0, t1: f"{p}X {t0}", NONE),
)

CELLS = tuple(
    pytest.param(name, prefix, allowed, case, build, want, id=f"{name.split('_', 1)[1]}-{case}")
    for name, prefix, allowed in TRIPLES
    for case, build, want in MATRIX
)


def test_b8_matrix_has_exactly_54_cells():
    """The deliverable is the matrix: 18 inputs x 3 parsers, none quietly dropped."""
    assert len(MATRIX) == 18
    assert len(CELLS) == 54


@pytest.mark.parametrize("name,prefix,allowed,case,build,want", CELLS)
def test_b8_golden_equivalence_matrix_public_parser(name, prefix, allowed, case, build, want):
    """Each public parser returns EXACTLY the value measured at HEAD before the collapse."""
    text = build(prefix, allowed[0], allowed[1])
    expected = want(allowed[0], allowed[1])
    assert parser(name)(text) == expected, (
        f"{name} case {case}: input {text!r} must return {expected!r}"
    )


@pytest.mark.parametrize("name,prefix,allowed,case,build,want", CELLS)
def test_b8_golden_equivalence_matrix_core(name, prefix, allowed, case, build, want):
    """The core reproduces the same 54 cells when handed each parser's own pair."""
    text = build(prefix, allowed[0], allowed[1])
    expected = want(allowed[0], allowed[1])
    assert getattr(foundry, CORE)(text, prefix, allowed) == expected


# --------------------------------------------------------------------------
# behavior 1 -- the core exists module-level with the specified shape
# --------------------------------------------------------------------------
def test_b1_core_exists_as_a_module_level_callable():
    fn = getattr(foundry, CORE, None)
    assert callable(fn), "foundry._sentinel_token must exist as a module-level callable"
    assert fn.__module__ == "foundry"


def test_b1_core_accepts_text_prefix_allowed_in_that_order():
    params = list(inspect.signature(getattr(foundry, CORE)).parameters)
    assert params == ["text", "prefix", "allowed"]


def test_b1_core_is_positionally_callable_and_returns_str_or_none():
    fn = getattr(foundry, CORE)
    got = fn("RESULT: PASS", "RESULT:", ("PASS", "FAIL"))
    assert got == "PASS" and isinstance(got, str)
    assert fn("RESULT: nope", "RESULT:", ("PASS", "FAIL")) is None


def test_b1_core_is_defined_at_module_level_in_the_source_not_nested():
    """A nested definition would not be a shared single site."""
    tree = ast.parse((REPO_ROOT / "foundry.py").read_text(encoding="utf-8"))
    top = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert CORE in top


def test_b1_core_documents_the_rule_and_the_none_contract():
    doc = (getattr(foundry, CORE).__doc__ or "")
    assert doc.strip(), "the core needs a docstring stating the rule"
    low = doc.lower()
    assert "none" in low
    assert "last" in low and "non-empty" in low


# --------------------------------------------------------------------------
# behavior 2 -- the token of the LAST non-empty line, when it matches
# --------------------------------------------------------------------------
def test_b2_spec_example_verbatim():
    assert getattr(foundry, CORE)("RESULT: PASS", "RESULT:", ("PASS", "FAIL")) == "PASS"


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b2_every_allowed_token_is_returned_not_just_the_first(name, prefix, allowed):
    for token in allowed:
        assert parser(name)(f"{prefix} {token}") == token
        assert getattr(foundry, CORE)(f"{prefix} {token}", prefix, allowed) == token


def test_b2_the_last_non_empty_line_is_what_decides_not_the_first():
    text = "RESULT: FAIL\nsome prose in the middle\nRESULT: PASS\n\n"
    assert foundry.parse_tester_result(text) == "PASS"


# --------------------------------------------------------------------------
# behavior 3 -- None when the last non-empty line does not START WITH prefix
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b3_prefix_on_an_earlier_line_with_prose_after_is_none(name, prefix, allowed):
    assert parser(name)(f"{prefix} {allowed[0]}\nlooks good to me") is None


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b3_containing_the_prefix_without_starting_with_it_is_none(name, prefix, allowed):
    assert parser(name)(f"X{prefix} {allowed[0]}") is None
    assert parser(name)(f"see {prefix} {allowed[0]}") is None
    assert parser(name)(f"# {prefix} {allowed[0]}") is None


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b3_a_different_parsers_prefix_is_not_honored(name, prefix, allowed):
    """Cross-talk between the three gate channels must stay impossible."""
    for other_name, other_prefix, other_allowed in TRIPLES:
        if other_prefix == prefix:
            continue
        assert parser(name)(f"{other_prefix} {other_allowed[0]}") is None


def test_b3_no_sentinel_line_at_all_is_none():
    assert foundry.parse_tester_result("all good, shipping it") is None
    assert foundry.parse_review_verdict("looks fine\n\n") is None


# --------------------------------------------------------------------------
# behavior 4 -- None when the remainder is not a member of `allowed`
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
@pytest.mark.parametrize("remainder", ["MAYBE", "", " ", "PENDING", "PARTIAL", "0", "-"])
def test_b4_unknown_remainder_is_none(name, prefix, allowed, remainder):
    assert parser(name)(f"{prefix} {remainder}") is None


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b4_lowercase_and_mixed_case_tokens_are_none(name, prefix, allowed):
    for token in allowed:
        assert parser(name)(f"{prefix} {token.lower()}") is None
        assert parser(name)(f"{prefix} {token.capitalize()}") is None


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b4_bare_prefix_is_none(name, prefix, allowed):
    assert parser(name)(prefix) is None
    assert parser(name)(f"   {prefix}   ") is None


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b4_two_tokens_on_the_sentinel_line_is_none(name, prefix, allowed):
    assert parser(name)(f"{prefix} {allowed[0]} {allowed[1]}") is None
    assert parser(name)(f"{prefix} {allowed[0]} extra") is None


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b4_a_token_valid_for_another_channel_is_none_here(name, prefix, allowed):
    for _, _, other_allowed in TRIPLES:
        for token in other_allowed:
            if token in allowed:
                continue
            assert parser(name)(f"{prefix} {token}") is None


def test_b4_an_empty_allowed_set_can_never_yield_a_token():
    assert getattr(foundry, CORE)("RESULT: PASS", "RESULT:", ()) is None


# --------------------------------------------------------------------------
# behavior 5 -- totality: never raises, for any string or None
# --------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["", None, "   \n\t\n  "])
@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b5_empty_none_and_whitespace_are_none_not_a_raise(name, prefix, allowed, text):
    assert parser(name)(text) is None
    assert getattr(foundry, CORE)(text, prefix, allowed) is None


def _fuzz_texts():
    """A deterministic, generated corpus -- 'for any string it returns None, not a raise'."""
    pieces = ["", "RESULT:", "VERDICT:", "POSTRELEASE:", "PASS", "FAIL", "APPROVE",
              "CHANGES_REQUIRED", "HEALTHY", "BROKEN", " ", "\t", "\n", "\r\n", ":",
              "x", "0", "-", "%s", "{}", "\\", '"', "'"]
    out = []
    for i, a in enumerate(pieces):
        for j, b in enumerate(pieces):
            if (i * len(pieces) + j) % 3:
                continue
            out.append(a + b)
            out.append(b + "\n" + a)
    return tuple(dict.fromkeys(out))


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b5_total_over_a_generated_corpus(name, prefix, allowed):
    corpus = _fuzz_texts()
    assert len(corpus) > 100, "the corpus must be large enough to be worth calling a fuzz"
    for text in corpus:
        got = parser(name)(text)
        assert got is None or got in allowed, f"{name}({text!r}) -> {got!r}"
        core = getattr(foundry, CORE)(text, prefix, allowed)
        assert core is None or core in allowed
        assert core == got, "the core and its delegate must never disagree"


def test_b5_pathological_sizes_do_not_raise():
    fn = getattr(foundry, CORE)
    assert fn("\n" * 5000 + "RESULT: PASS", "RESULT:", ("PASS", "FAIL")) == "PASS"
    assert fn("x" * 20000, "RESULT:", ("PASS", "FAIL")) is None
    assert fn("RESULT: " + "P" * 20000, "RESULT:", ("PASS", "FAIL")) is None


# --------------------------------------------------------------------------
# behavior 6 -- whitespace / line-ending tolerance, all yielding the token
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b6_trailing_blank_and_whitespace_only_lines_are_ignored(name, prefix, allowed):
    t0 = allowed[0]
    assert parser(name)(f"{prefix} {t0}\n") == t0
    assert parser(name)(f"{prefix} {t0}\n\n\n   \n") == t0
    assert parser(name)(f"{prefix} {t0}\n\t\n \t \n") == t0


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b6_the_sentinel_line_may_be_indented(name, prefix, allowed):
    t0 = allowed[0]
    assert parser(name)(f"\t   {prefix} {t0}") == t0
    assert parser(name)(f"    {prefix} {t0}") == t0


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b6_the_token_may_be_padded_on_both_sides(name, prefix, allowed):
    t0 = allowed[0]
    assert parser(name)(f"  {prefix}   {t0}   ") == t0
    assert parser(name)(f"{prefix}\t{t0}\t") == t0


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b6_no_space_after_the_prefix_is_accepted(name, prefix, allowed):
    t0 = allowed[0]
    assert parser(name)(f"{prefix}{t0}") == t0


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b6_crlf_line_endings_are_accepted(name, prefix, allowed):
    t0 = allowed[0]
    assert parser(name)(f"intro\r\n{prefix} {t0}\r\n") == t0
    assert parser(name)(f"a\r\nb\r\n{prefix} {t0}") == t0


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b6_with_two_valid_sentinel_lines_the_last_one_wins(name, prefix, allowed):
    t0, t1 = allowed
    assert parser(name)(f"{prefix} {t1}\n{prefix} {t0}") == t0
    assert parser(name)(f"{prefix} {t0}\n{prefix} {t1}") == t1
    assert parser(name)(f"{prefix} {t0}\n\n{prefix} {t1}\n\n \n") == t1


# --------------------------------------------------------------------------
# behavior 7 -- the three public parsers are unchanged at the seam and DELEGATE
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b7_names_and_single_text_parameter_signatures_are_unchanged(name, prefix, allowed):
    fn = getattr(foundry, name, None)
    assert callable(fn), f"{name} must still exist"
    assert list(inspect.signature(fn).parameters) == ["text"]


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b7_docstrings_are_still_present_and_channel_specific(name, prefix, allowed):
    """AMBIGUITY (PM feedback): 'docstrings VERBATIM' cannot be proven from a black-box
    seat -- the pre-change text lives in the implementation source this role may not
    read. Tested here as the strongest observable proxy: still present, still substantial,
    and still naming this channel's own prefix and tokens."""
    doc = getattr(foundry, name).__doc__ or ""
    assert len(doc.strip()) > 200, f"{name} lost its docstring"
    assert prefix in doc
    for token in allowed:
        assert token in doc


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b7_each_parser_delegates_to_the_core_with_its_own_pair(name, prefix, allowed,
                                                               monkeypatch):
    """The seam must bite by BARE module name, and carry exactly the documented pair."""
    calls = []

    def spy(text, prefix_, allowed_):
        calls.append((text, prefix_, allowed_))
        return "SPY"

    monkeypatch.setattr(foundry, CORE, spy)
    got = parser(name)(f"{prefix} {allowed[0]}")
    assert got == "SPY", f"{name} does not route through foundry.{CORE}"
    assert len(calls) == 1
    text, prefix_, allowed_ = calls[0]
    assert text == f"{prefix} {allowed[0]}", "the text must be passed through unchanged"
    assert prefix_ == prefix
    assert tuple(allowed_) == allowed


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b7_the_pair_is_a_tuple_of_str_not_a_bare_string(name, prefix, allowed, monkeypatch):
    """A bare `str` for `allowed` makes membership a SUBSTRING test, so a truncated token
    would read as a confident verdict. Each parser must hand over a real token set."""
    seen = []
    monkeypatch.setattr(foundry, CORE, lambda t, p, a: seen.append(a))
    parser(name)(f"{prefix} {allowed[0]}")
    assert len(seen) == 1
    assert isinstance(seen[0], tuple), f"{name} passed {type(seen[0]).__name__}, not a tuple"
    assert all(isinstance(x, str) for x in seen[0])
    assert len(seen[0]) == 2


def test_b7_the_three_channels_use_three_distinct_pairs(monkeypatch):
    seen = {}
    for name, prefix, allowed in TRIPLES:
        monkeypatch.setattr(foundry, CORE, lambda t, p, a: seen.setdefault(p, tuple(a)))
        parser(name)(f"{prefix} {allowed[0]}")
    assert seen == {
        "POSTRELEASE:": ("HEALTHY", "BROKEN"),
        "VERDICT:": ("APPROVE", "CHANGES_REQUIRED"),
        "RESULT:": ("PASS", "FAIL"),
    }


# --------------------------------------------------------------------------
# behavior 9 -- the collapse brake: one statement per parser body after the docstring
# --------------------------------------------------------------------------
def _parser_bodies():
    tree = ast.parse((REPO_ROOT / "foundry.py").read_text(encoding="utf-8"))
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            has_doc = (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            )
            out[node.name] = len(body[1:]) if has_doc else len(body)
    return out


@pytest.mark.parametrize("name,prefix,allowed", TRIPLES)
def test_b9_each_parser_body_is_exactly_one_statement_after_its_docstring(name, prefix,
                                                                         allowed):
    """So the duplication cannot silently return: a re-inlined rule needs >1 statement."""
    bodies = _parser_bodies()
    assert name in bodies, f"{name} is not a def in foundry.py"
    assert bodies[name] == 1, (
        f"{name} has {bodies[name]} top-level statements after its docstring, expected 1 "
        "-- the anchored-sentinel rule must live only in the shared core"
    )


def test_b9_the_brake_oracle_is_two_sided():
    """The counter must be able to report more than 1, or it proves nothing."""
    bodies = _parser_bodies()
    assert bodies.get(CORE, 0) > 1, "the shared core is where the statements went"
    assert any(v > 1 for v in bodies.values())


# --------------------------------------------------------------------------
# behavior 10 -- parse_ship_action / parse_ship_sha are NOT modified
# --------------------------------------------------------------------------
def test_b10_parse_ship_action_and_sha_keep_their_current_values():
    line = "ACTION: PUSHED abc123"
    assert foundry.parse_ship_action(line) == "PUSHED"
    assert foundry.parse_ship_sha(line) == "abc123"


def test_b10_both_ship_parsers_return_none_for_empty_text():
    assert foundry.parse_ship_action("") is None
    assert foundry.parse_ship_sha("") is None


def test_b10_reverted_is_still_accepted_and_prose_after_the_token_still_reverts():
    assert foundry.parse_ship_action("ACTION: REVERTED") == "REVERTED"
    assert foundry.parse_ship_action("ACTION: PUSHED abc123\nnice work") is None
    assert foundry.parse_ship_action("ACTION: PENDING") is None


def test_b10_ship_parser_signatures_are_untouched():
    for name in ("parse_ship_action", "parse_ship_sha"):
        assert list(inspect.signature(getattr(foundry, name)).parameters) == ["text"]


def test_b10_the_ship_parsers_were_not_collapsed_this_iteration():
    """Out of scope per the spec: they genuinely diverge, so they keep >1 statement."""
    bodies = _parser_bodies()
    assert bodies.get("parse_ship_action", 0) > 1
    assert bodies.get("parse_ship_sha", 0) > 1


# --------------------------------------------------------------------------
# behavior 11 -- imports still clean; the core touches no filesystem/net/subprocess
# --------------------------------------------------------------------------
def test_b11_foundry_and_dispatcher_still_import_cleanly():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"import failed:\n{proc.stdout}\n{proc.stderr}"


def test_b11_the_core_performs_no_io_at_all(monkeypatch):
    """Every I/O door is slammed; the core must still answer the whole matrix."""
    import builtins
    import io
    import os
    import socket

    def boom(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("_sentinel_token performed I/O")

    monkeypatch.setattr(builtins, "open", boom)
    monkeypatch.setattr(io, "open", boom, raising=False)
    monkeypatch.setattr(pathlib.Path, "open", boom)
    monkeypatch.setattr(pathlib.Path, "read_text", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)
    monkeypatch.setattr(os, "system", boom)
    monkeypatch.setattr(socket, "socket", boom)

    fn = getattr(foundry, CORE)
    for name, prefix, allowed in TRIPLES:
        for case, build, want in MATRIX:
            text = build(prefix, allowed[0], allowed[1])
            assert fn(text, prefix, allowed) == want(allowed[0], allowed[1])
            assert parser(name)(text) == want(allowed[0], allowed[1])


def test_b11_the_core_is_deterministic_and_mutates_no_input():
    fn = getattr(foundry, CORE)
    allowed = ("PASS", "FAIL")
    text = "intro\nRESULT: PASS\n\n"
    first = fn(text, "RESULT:", allowed)
    for _ in range(5):
        assert fn(text, "RESULT:", allowed) == first
    assert text == "intro\nRESULT: PASS\n\n"
    assert allowed == ("PASS", "FAIL")


# --------------------------------------------------------------------------
# the matrix must DISCRIMINATE -- a golden matrix that passes every plausible
# wrong implementation is decoration. Each variant below is a rule someone could
# credibly write instead; every one must be caught by at least one of the 54 cells.
# (This exercises the ORACLE in this file, not the product: the variants are
# defined here and the product is never modified.)
# --------------------------------------------------------------------------
def _v_contains_instead_of_startswith(text, prefix, allowed):
    for line in reversed((text or "").splitlines()):
        if line.strip():
            if prefix in line:
                token = line.strip().split(prefix, 1)[1].strip()
                return token if token in allowed else None
            return None
    return None


def _v_first_match_instead_of_last(text, prefix, allowed):
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith(prefix):
            token = s[len(prefix):].strip()
            return token if token in allowed else None
    return None


def _v_no_strip_of_the_token(text, prefix, allowed):
    for line in reversed((text or "").splitlines()):
        if line.strip():
            s = line.strip()
            if not s.startswith(prefix):
                return None
            token = s[len(prefix):]
            return token if token in allowed else None
    return None


def _v_any_token_accepted(text, prefix, allowed):
    for line in reversed((text or "").splitlines()):
        if line.strip():
            s = line.strip()
            return s[len(prefix):].strip() if s.startswith(prefix) else None
    return None


def _v_literal_last_line_no_blank_skipping(text, prefix, allowed):
    lines = (text or "").splitlines()
    if not lines:
        return None
    s = lines[-1].strip()
    if not s.startswith(prefix):
        return None
    token = s[len(prefix):].strip()
    return token if token in allowed else None


def _v_scans_the_whole_text_for_a_token(text, prefix, allowed):
    for token in allowed:
        if token in (text or ""):
            return token
    return None


WRONG_VARIANTS = (
    ("prefix matched with `in` instead of `startswith`", _v_contains_instead_of_startswith),
    ("first matching line instead of the last", _v_first_match_instead_of_last),
    ("token not stripped before the membership test", _v_no_strip_of_the_token),
    ("any remainder accepted, no `allowed` check", _v_any_token_accepted),
    ("literal last line, blank lines not skipped", _v_literal_last_line_no_blank_skipping),
    ("token searched for anywhere in the text", _v_scans_the_whole_text_for_a_token),
)


@pytest.mark.parametrize("why,variant", WRONG_VARIANTS,
                         ids=[w for w, _ in WRONG_VARIANTS])
def test_matrix_is_two_sided_every_wrong_rule_is_caught(why, variant):
    caught = []
    for name, prefix, allowed in TRIPLES:
        for case, build, want in MATRIX:
            text = build(prefix, allowed[0], allowed[1])
            expected = want(allowed[0], allowed[1])
            try:
                got = variant(text, prefix, allowed)
            except Exception:
                caught.append((name, case, "raised"))
                continue
            if got != expected:
                caught.append((name, case, got))
    assert caught, f"the 54-cell matrix does NOT catch a rule that {why}"


def test_the_two_sidedness_check_would_pass_a_faithful_rule():
    """The control: a correct restatement of the rule must clear all 54 cells, or the
    variants above are being caught by an over-strict matrix rather than by being wrong."""
    def faithful(text, prefix, allowed):
        for line in reversed((text or "").splitlines()):
            s = line.strip()
            if not s:
                continue
            if not s.startswith(prefix):
                return None
            token = s[len(prefix):].strip()
            return token if token in allowed else None
        return None

    for name, prefix, allowed in TRIPLES:
        for case, build, want in MATRIX:
            text = build(prefix, allowed[0], allowed[1])
            assert faithful(text, prefix, allowed) == want(allowed[0], allowed[1]), (
                f"case {case} for {name} rejects a faithful restatement of the rule"
            )
