"""Iteration 507 -- BLACK-BOX behavior tests: `foundry._test_function_nodes` stops
running a full `ast.walk` over expression nodes and walks only statement-bearing
children (stmt / excepthandler / match_case / mod) breadth-first in `_fields` order,
returning the IDENTICAL `test*` def nodes in the IDENTICAL order as the `ast.walk`
reference.

Spec under test: products/_platform/state/iter-507/pm.md, Expected Behaviors 1-6.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-507
PM spec, the conventions under `tests/`, and the product's OWN observable behavior
(its CLI / `main()` and its public names). The implementation source, the
engineer/reviewer notes, IMPLEMENTATION.patch and any `git diff` were NOT read.

FIXTURE SAFETY: the repo-wide sweep reads only `git ls-files '*.py'` (tracked, so a
fresh clone sees the same set); the CLI comparison builds its product in tmp_path; no
absolute machine path appears in this file.
"""
from __future__ import annotations

import ast
import contextlib
import inspect
import io
import json
import pathlib
import subprocess
import sys
import textwrap

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


# ---------------------------------------------------------------- reference


def _ref_nodes(tree):
    """The spec's oracle: `ast.walk` filtered to `test*` (async) defs."""
    if isinstance(tree, str):
        tree = ast.parse(tree)
    return [n for n in ast.walk(tree) if isinstance(n, _DEFS) and n.name.startswith("test")]


def _ids(nodes):
    return [id(n) for n in nodes]


def _names(nodes):
    return [(n.name, n.lineno) for n in nodes]


# ---------------------------------------------------------------- planted sources

PLANTED = {
    "a_try": """
        try:
            def test_try_body_1(): pass
            def test_try_body_2(): pass
        except ValueError:
            def test_handler_1(): pass
        except (KeyError, TypeError) as e:
            def test_handler_2(): pass
            def helper(): pass
        else:
            def test_else_1(): pass
        finally:
            def test_finally_1(): pass
            def test_finally_2(): pass
            class TestFin:
                def test_fin_method(self): pass
        def test_after_try(): pass
        try:
            try:
                def test_inner_try(): pass
            finally:
                def test_inner_finally(): pass
        except Exception:
            def test_outer_handler(): pass
    """,
    "b_match": """
        match command:
            case "go":
                def test_case_go(): pass
            case [x, y] if (lambda: x)():
                def test_case_seq_1(): pass
                def test_case_seq_2(): pass
            case {"k": v}:
                class TestInMatch:
                    def test_method_in_case(self): pass
            case _:
                def test_case_default(): pass
        def test_after_match(): pass
    """,
    "c_flow": """
        import contextlib
        if a:
            def test_if(): pass
        elif b:
            def test_elif(): pass
        else:
            def test_else(): pass
        for i in range(3):
            def test_for_body(): pass
        else:
            def test_for_else(): pass
        while cond:
            def test_while_body(): pass
        else:
            def test_while_else(): pass
        with contextlib.suppress(Exception):
            def test_with(): pass
        async def outer():
            async with ctx() as c:
                def test_async_with(): pass
            async for item in agen():
                def test_async_for(): pass
            else:
                def test_async_for_else(): pass
    """,
    "d_nesting": """
        class TestOuter:
            def test_outer_method(self): pass
            class TestInner:
                def test_inner_method(self): pass
                class TestDeepest:
                    async def test_deepest(self): pass
            def test_outer_method_2(self):
                def test_nested_in_method(): pass
        def test_top():
            def test_nested_1():
                def test_nested_2(): pass
            def test_sibling(): pass
        def test_top_2(): pass
    """,
    "e_async_and_nontests": """
        async def test_async_1(): pass
        def helper(): pass
        def _test_private(): pass
        def Test(): pass
        class Test:
            def check(self): pass
            def test_real(self): pass
        async def test_async_2():
            async def test_async_inner(): pass
        def testplain(): pass
    """,
    "f_trystar": """
        try:
            def test_trystar_body(): pass
        except* ValueError:
            def test_trystar_handler_1(): pass
        except* (KeyError, OSError):
            def test_trystar_handler_2(): pass
        else:
            def test_trystar_else(): pass
        finally:
            def test_trystar_finally(): pass
    """,
    "g_expressions": """
        import functools
        f = lambda x: [y for y in x if (lambda z: z)(y)]
        g = {k: v for k, v in {}.items()}
        h = (i for i in range(3))
        @functools.lru_cache(maxsize=(lambda: 1)())
        def test_decorated(a=lambda: 0, *, b=[c for c in "ab"]) -> (lambda: int):
            return [lambda q=1: q for _ in range(2)]
        class TestKw(metaclass=type, **{}):
            attr = [lambda: 0 for _ in ()]
            def test_kw(self, x=(lambda: (lambda: 1))()): pass
        def test_last(): pass
    """,
}


def _planted(key):
    return textwrap.dedent(PLANTED[key])


# ---------------------------------------------------------------- EB1 / EB4


@pytest.mark.parametrize("key", sorted(PLANTED))
def test_eb1_planted_trees_identical_ids_and_order(key):
    tree = ast.parse(_planted(key))
    ref = _ref_nodes(tree)
    assert len(ref) >= 3, "anti-vacuity: each planted source holds several test* defs"
    got = foundry._test_function_nodes(tree)
    assert _ids(got) == _ids(ref)


def test_eb1_try_fields_order_is_not_a_hand_picked_tuple():
    """Try._fields is (body, handlers, orelse, finalbody). The except-handler defs and
    the method of a class in `finally:` sit at the SAME BFS depth, so their relative
    order is decided purely by field order: handlers first. A body/orelse/finalbody/
    handlers tuple would put test_fin_method ahead of the handler defs."""
    assert ast.Try._fields[:2] == ("body", "handlers")
    tree = ast.parse(_planted("a_try"))
    names = [n.name for n in foundry._test_function_nodes(tree)]
    assert names == [n.name for n in _ref_nodes(tree)]
    assert names.index("test_handler_1") < names.index("test_handler_2") < names.index("test_fin_method")
    assert names[:3] == ["test_after_try", "test_try_body_1", "test_try_body_2"]


def test_eb1_nontests_excluded():
    tree = ast.parse(_planted("e_async_and_nontests"))
    names = {n.name for n in foundry._test_function_nodes(tree)}
    assert {"helper", "_test_private", "Test", "check"}.isdisjoint(names)
    assert {"test_async_1", "test_async_2", "test_async_inner", "test_real", "testplain"} <= names


def test_eb1_every_tracked_python_file_agrees():
    try:
        out = subprocess.run(
            ["git", "ls-files", "*.py"], cwd=_ROOT, capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("git unavailable")
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    paths = [p for p in out.stdout.splitlines() if p.strip()]
    checked = diffs = 0
    with_tests = 0
    for rel in paths:
        p = _ROOT / rel
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue
        checked += 1
        ref = _ref_nodes(tree)
        with_tests += bool(ref)
        if _ids(foundry._test_function_nodes(tree)) != _ids(ref):
            diffs += 1
    assert checked >= 50 and with_tests >= 50, "anti-vacuity: the sweep saw real test modules"
    assert diffs == 0


def test_eb4_expressions_agree_and_hide_nothing():
    src = _planted("g_expressions")
    got = foundry._test_function_nodes(src)
    assert _names(got) == _names(_ref_nodes(src))
    assert [n.name for n in got] == ["test_decorated", "test_last", "test_kw"]


class _Trap(ast.expr):
    """An expression node whose only child field raises when read: walking INTO an
    expression node (as `ast.walk` does) trips it; a statement-only walk never does."""

    _fields = ("boom",)

    @property
    def boom(self):
        raise RuntimeError("expression node expanded")


def test_eb4_statement_only_walk_never_expands_expression_nodes():
    tree = ast.parse("x = 1\ndef test_a():\n    y = 2\nclass TestC:\n    def test_m(self): pass\n")
    tree.body[0].value = _Trap()
    tree.body[1].body[0].value = _Trap()
    with pytest.raises(RuntimeError):  # anti-vacuity: the full ast.walk does trip it
        list(ast.walk(tree))
    got = foundry._test_function_nodes(tree)
    assert [n.name for n in got] == ["test_a", "test_m"]


# ---------------------------------------------------------------- EB2 / EB3


@pytest.mark.parametrize("key", sorted(PLANTED))
def test_eb2_text_input_matches_parsed_reference(key):
    src = _planted(key)
    got = foundry._test_function_nodes(src)
    assert isinstance(got, list)
    assert _names(got) == _names(_ref_nodes(ast.parse(src)))
    assert len(got) >= 3


@pytest.mark.parametrize(
    "bad", ["def test_x(:\n", "class T:\ndef test_y(): pass\n", "x = (\n", "a\x00b = 1\n"]
)
def test_eb3_syntax_error_identical_to_ast_parse(bad):
    with pytest.raises((SyntaxError, ValueError)) as ref:
        ast.parse(bad)
    with pytest.raises(type(ref.value)) as got:
        foundry._test_function_nodes(bad)
    assert str(got.value) == str(ref.value)
    if isinstance(ref.value, SyntaxError):
        assert (got.value.msg, got.value.lineno, got.value.offset) == (
            ref.value.msg, ref.value.lineno, ref.value.offset,
        )


def test_eb3_first_case_is_syntax_error():
    with pytest.raises(SyntaxError):
        foundry._test_function_nodes("def test_x(:\n")


# ---------------------------------------------------------------- EB5


def _product(tmp_path):
    repo = tmp_path / "repo"
    tests = repo / "tests"
    tests.mkdir(parents=True)
    (repo / ".git").mkdir()
    (tests / "test_alpha.py").write_text(textwrap.dedent("""
        import pytest
        def test_no_assert():
            x = 1
        def test_const():
            assert True
        @pytest.mark.skip(reason="x")
        def test_skipped():
            assert 1 == 2
        def test_good():
            assert sum([1, 2]) == 3
        class TestK:
            def test_method_no_assert(self):
                pass
            def test_method_good(self):
                assert [1] == [1]
    """))
    (tests / "test_beta.py").write_text(_planted("a_try") + _planted("f_trystar"))
    (tests / "test_gamma.py").write_text(_planted("b_match").replace("command", "cmd"))
    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / "VISION.md").write_text("v\n")
    (tmp_path / "ROADMAP.md").write_text("r\n")
    cfg = {
        "name": "x", "repo": str(repo), "allowed_push_repo": "none", "branch": "main",
        "vision": str(tmp_path / "VISION.md"), "roadmap": str(tmp_path / "ROADMAP.md"),
        "quality_ref": str(repo), "test_cmd": "true", "roles_dir": str(_ROOT / "roles"),
        "work_root": str(work), "quality_bar": "fixture", "push_enabled": False,
    }
    P = tmp_path / "products" / "x" / "config.json"
    P.parent.mkdir(parents=True)
    P.write_text(json.dumps(cfg, indent=2) + "\n")
    return P, tests


def _run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = foundry.main(argv)
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue()


@pytest.mark.parametrize("use_files", [False, True])
def test_eb5_test_quality_output_identical_to_ast_walk_reference(tmp_path, monkeypatch, use_files):
    P, tests = _product(tmp_path)
    argv = ["test-quality", "--config", str(P), "--json"]
    if use_files:
        argv += ["--files"] + [str(p) for p in sorted(tests.glob("test_*.py"))]
    new = _run_main(argv)
    assert "test_no_assert" in new[1], "anti-vacuity: planted findings reach the report"
    json.loads(new[1])
    monkeypatch.setattr(foundry, "_test_function_nodes", _ref_nodes)
    ref = _run_main(argv)
    assert new == ref
    # anti-vacuity: the seam really feeds the verb (an empty walk changes the output)
    monkeypatch.setattr(foundry, "_test_function_nodes", lambda t: [])
    assert _run_main(argv)[1] != new[1]


# ---------------------------------------------------------------- EB6


def test_eb6_signature_return_type_and_docstring():
    fn = foundry._test_function_nodes
    params = list(inspect.signature(fn).parameters.values())
    assert len(params) == 1
    assert params[0].kind in (params[0].POSITIONAL_ONLY, params[0].POSITIONAL_OR_KEYWORD)
    assert isinstance(fn("x = 1\n"), list) and fn("x = 1\n") == []
    assert isinstance(fn(ast.parse("def test_z(): pass\n")), list)
    doc = (fn.__doc__ or "").lower()
    assert "ast.walk" in doc
    assert "statement" in doc or "stmt" in doc
    assert "order" in doc
    assert "expression" in doc or "expr" in doc


def test_eb6_foundry_and_dispatcher_import():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=_ROOT, capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stderr
