"""Iteration 516 -- BLACK-BOX behavior tests: HOTFIX making the deep-nesting
parse-failure fixtures interpreter-proof (cpython 3.14 parses a 10000-deep `1+` chain).

Spec under test: products/_platform/state/iter-516/pm.md, Expected Behaviors 1, 2, 4, 5
(EB3 is a scoped run under the fresh-clone interpreter and EB7 is a no-touch rule; both
were checked by the tester out of band and are recorded in tester.md).

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-516
PM spec, the conventions under `tests/`, and the tracked test files read as TEXT / `ast`
(the surface the spec defines).  The engineer/reviewer notes, IMPLEMENTATION.patch and
any `git diff` were NOT read.  test_iter326 / test_iter423 are NOT imported.

FIXTURE SAFETY: only tracked files under tests/ are read; no gitignored state and no
absolute machine path appear in this file.  The banned old literal is assembled from
pieces so this module itself never carries it.
"""
from __future__ import annotations

import ast
import os
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TESTS = _ROOT / "tests"
T326 = _TESTS / "test_iter326_behavior.py"
T423 = _TESTS / "test_iter423_behavior.py"
T204 = _TESTS / "test_iter204_behavior.py"

NEW_DEPTH = 200000
# the banned old fixture text, assembled so this file does not contain it verbatim
_OLD_LITERAL = '"1+" * ' + "1" + "0000"
_NEW_LITERAL = '"1+" * ' + str(NEW_DEPTH)
EXPECTED_SRC_DEEP = "x = " + "1+" * NEW_DEPTH + "1"


def _module_assign(path: pathlib.Path, name: str) -> ast.expr:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = [n.value for n in tree.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
    assert len(hits) == 1, f"{path.name}: expected one module-level {name}, got {len(hits)}"
    return hits[0]


def _const_eval(node: ast.expr):
    """Evaluate a pure-constant str expression (Constant / + / *) without importing."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mult)):
        lhs, rhs = _const_eval(node.left), _const_eval(node.right)
        return lhs + rhs if isinstance(node.op, ast.Add) else lhs * rhs
    raise AssertionError(f"SRC_DEEP is not a constant expression: {ast.dump(node)}")


# --------------------------------------------------------------------------
# EB1 -- SRC_DEEP is the 200000-deep chain in both files; the old text is gone
# --------------------------------------------------------------------------
@pytest.mark.parametrize("path", [T326, T423], ids=["iter326", "iter423"])
def test_eb1_src_deep_is_the_200000_deep_chain(path):
    value = _const_eval(_module_assign(path, "SRC_DEEP"))
    assert value == EXPECTED_SRC_DEEP
    assert len(value) == 400005


@pytest.mark.parametrize("path", [T326, T423], ids=["iter326", "iter423"])
def test_eb1_src_deep_line_spells_the_new_constant_and_keeps_a_comment(path):
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
             if ln.startswith("SRC_DEEP")]
    assert len(lines) == 1, lines
    assert _NEW_LITERAL in lines[0], lines[0]
    assert "#" in lines[0].split(_NEW_LITERAL, 1)[1], \
        f"the existing trailing comment must be kept: {lines[0]!r}"


def test_eb1_no_file_under_tests_contains_the_old_literal():
    offenders = sorted(p.name for p in _TESTS.rglob("*.py")
                       if _OLD_LITERAL in p.read_text(encoding="utf-8", errors="replace"))
    assert offenders == []
    # anti-vacuity: the scan really walks the suite and the needle is well-formed
    assert T326.exists() and T423.exists()
    assert _OLD_LITERAL.endswith("10000") and _OLD_LITERAL.startswith('"1+"')


# --------------------------------------------------------------------------
# EB2 -- the deep source fails ast.parse here; a trivial source still parses
# --------------------------------------------------------------------------
def test_eb2_deep_source_fails_to_parse_under_the_running_interpreter():
    with pytest.raises((RecursionError, SyntaxError, MemoryError)):
        ast.parse(EXPECTED_SRC_DEEP)


def test_eb2_two_sided_control_a_trivial_source_parses():
    tree = ast.parse("foo()\n")
    assert isinstance(tree, ast.Module) and len(tree.body) == 1


# --------------------------------------------------------------------------
# EB4 -- test_iter326's two b6 parametrizes carry short ids
# --------------------------------------------------------------------------
B6_FUNCS = ("test_b6_every_parse_failure_class_folds_to_one_word_in_production",
            "test_b6_every_parse_failure_class_folds_to_one_word_in_tests")


@pytest.mark.parametrize("func", B6_FUNCS, ids=["production", "tests"])
def test_eb4_b6_parametrize_carries_short_ids(func):
    tree = ast.parse(T326.read_text(encoding="utf-8"))
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == func]
    assert len(fns) == 1, func
    decos = [d for d in fns[0].decorator_list
             if isinstance(d, ast.Call) and getattr(d.func, "attr", None) == "parametrize"
             and d.args and isinstance(d.args[0], ast.Constant) and d.args[0].value == "bad"]
    assert len(decos) == 1, f"{func}: expected one parametrize('bad', ...)"
    arg_names = [e.id for e in decos[0].args[1].elts]
    assert arg_names == ["SRC_BAD_SYNTAX", "SRC_NUL", "SRC_DEEP"]
    ids = {k.arg: k.value for k in decos[0].keywords}.get("ids")
    assert ids is not None, f"{func}: parametrize has no ids="
    assert [e.value for e in ids.elts] == ["syntax", "nul", "deep"]


def test_eb4_collected_nodeids_are_short_and_name_deep():
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    cmd = [sys.executable, "-m", "pytest", "-n", "0", "--collect-only", "-q",
           "-p", "no:cacheprovider", str(T326)]
    proc = subprocess.run(cmd, cwd=_ROOT, env=env, capture_output=True, text=True,
                          timeout=300)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-3000:]
    ids = [ln for ln in proc.stdout.splitlines() if "::" in ln]
    assert len(ids) > 10, proc.stdout[-2000:]
    for func in B6_FUNCS:
        assert any(ln.endswith(f"{func}[deep]") for ln in ids), func
    too_long = [len(ln) for ln in ids if len(ln) > 300]
    assert too_long == [], f"{len(too_long)} nodeids over 300 chars, max {max(too_long)}"


# --------------------------------------------------------------------------
# EB5 -- test_iter204 b15 allow-lists the iter423 edit with an iter 516 comment
# --------------------------------------------------------------------------
B15 = "test_b15_only_the_three_expected_test_files_differ_from_head"


def test_eb5_b15_expected_set_contains_iter423_with_a_516_hotfix_comment():
    src = T204.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == B15]
    assert len(fns) == 1
    sets = [n.value for n in ast.walk(fns[0])
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "expected" for t in n.targets)
            and isinstance(n.value, ast.Set)]
    assert len(sets) == 1, "b15 must hold one `expected = {...}` set literal"
    members = [e.value for e in sets[0].elts if isinstance(e, ast.Constant)]
    assert "tests/test_iter423_behavior.py" in members
    assert "tests/test_iter326_behavior.py" in members
    # the comment sits inside the set literal, above the iter423 row
    seg_lines = src.splitlines()[sets[0].lineno - 1:sets[0].end_lineno]
    idx = [i for i, ln in enumerate(seg_lines) if '"tests/test_iter423_behavior.py"' in ln]
    assert len(idx) == 1
    preceding = "\n".join(seg_lines[max(0, idx[0] - 8):idx[0] + 1])
    assert re.search(r"#.*iter 516", preceding), preceding
    assert re.search(r"#.*FORCED", preceding), preceding
