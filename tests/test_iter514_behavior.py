"""Iteration 514 -- BLACK-BOX behavior tests: the seven run-path foundry.py docstrings that
denied having a call site ("ZERO call site" / "DORMANT this iter" / ...) are reworded to
name a real live caller, and a test-local brake reds when any function reachable from the
run roots carries such a denial.

Spec under test: products/_platform/state/iter-514/pm.md, Expected Behaviors 1-5 (EB6/EB7
are git-keyed and were checked in-process by the tester, not pinned here).

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-514
PM spec, the product README / roadmap text, the conventions under `tests/`, and the
product's OWN observable surface (its tracked source parsed as data through `ast`, which
is exactly the surface the spec defines).  The engineer/reviewer notes,
IMPLEMENTATION.patch and any `git diff` were NOT read.

FIXTURE SAFETY: only the tracked foundry.py / dispatcher.py plus inline fixture strings
are read; no gitignored state and no absolute machine path appear in this file.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]

DENIALS = ("ZERO call site", "DORMANT this iter", "DORMANT executor", "no orchestrator")
# machine-path prefixes, assembled so this file itself carries no banned token
_ABS_PREFIXES = ("/" + "Us" + "ers/", "/" + "ho" + "me/")
RUN_ROOTS = ("run_iteration", "run_stage", "run_continuous")
SEVEN = ("verify_fresh_clone", "resolve_agent_endpoint", "select_scout_lenses",
         "run_scout_phase", "derive_scout_stage_specs", "derive_execution_plan",
         "run_execution_plan")


# ---------------------------------------------------------------- pure helpers


def _flat(text: str | None) -> str:
    return " ".join((text or "").split())


def _excluded(name: str) -> bool:
    return name.endswith("_cli") or name == "main"


def _module_functions(src: str) -> dict[str, ast.AST]:
    tree = ast.parse(src)
    return {n.name: n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _refs(node: ast.AST, names) -> set[str]:
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in names:
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute) and sub.attr in names:
            out.add(sub.attr)
    return out


def _closure(foundry_src: str, dispatcher_src: str) -> set[str]:
    funcs = _module_functions(foundry_src)
    disp = set(re.findall(r"\bfoundry\.([A-Za-z_]\w*)", dispatcher_src))
    roots = [n for n in (*RUN_ROOTS, *sorted(disp)) if n in funcs and not _excluded(n)]
    seen: set[str] = set()
    todo = list(roots)
    while todo:
        name = todo.pop()
        if name in seen or _excluded(name):
            continue
        seen.add(name)
        for ref in _refs(funcs[name], funcs):
            if ref not in seen and not _excluded(ref):
                todo.append(ref)
    return seen


def run_path_dormancy_denials(foundry_src: str, dispatcher_src: str) -> list[str]:
    """Sorted names of run-root-closure functions whose docstring carries a DENIAL."""
    funcs = _module_functions(foundry_src)
    hits = []
    for name in _closure(foundry_src, dispatcher_src):
        doc = _flat(ast.get_docstring(funcs[name]))
        if any(d in doc for d in DENIALS):
            hits.append(name)
    return sorted(hits)


def _src(name: str) -> str:
    return (_ROOT / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- EB1 / EB3: real tree


def test_eb3_real_tree_has_no_run_path_denials():
    assert run_path_dormancy_denials(_src("foundry.py"), _src("dispatcher.py")) == []


def test_eb3_seven_targets_are_in_the_closure_so_the_brake_sees_them():
    closure = _closure(_src("foundry.py"), _src("dispatcher.py"))
    assert set(SEVEN) <= closure, sorted(set(SEVEN) - closure)


@pytest.mark.parametrize("target", SEVEN)
def test_eb1_docstring_carries_no_denial_and_is_ascii(target):
    funcs = _module_functions(_src("foundry.py"))
    doc = ast.get_docstring(funcs[target])
    assert doc, f"{target} lost its docstring"
    flat = _flat(doc)
    assert [d for d in DENIALS if d in flat] == []
    assert doc.isascii()
    assert [t for t in _ABS_PREFIXES if t in doc] == []


# ---------------------------------------------------------------- EB2: real live caller


@pytest.mark.parametrize("target", SEVEN)
def test_eb2_docstring_names_a_real_live_caller_in_backticks(target):
    funcs = _module_functions(_src("foundry.py"))
    doc = ast.get_docstring(funcs[target]) or ""
    named = set(re.findall(r"`([A-Za-z_]\w*)", doc))
    callers = sorted(f for f in named
                     if f in funcs and f != target and target in _refs(funcs[f], {target}))
    assert callers, f"{target}: backticked names {sorted(named)} include no real caller"


# ---------------------------------------------------------------- EB4: can-fail fixtures


def test_eb4_direct_callee_denial_is_flagged():
    src = (
        "def run_iteration():\n"
        "    helper()\n"
        "def helper():\n"
        "    '''Has ZERO call site in the pipeline.'''\n"
    )
    assert run_path_dormancy_denials(src, "") == ["helper"]


def test_eb4_transitive_wrapped_denial_is_flagged():
    src = (
        "def run_iteration():\n"
        "    a()\n"
        "def a():\n"
        "    '''Fine.'''\n"
        "    return b()\n"
        "def b():\n"
        "    '''This helper is DORMANT\n"
        "    this iteration; later bite.'''\n"
    )
    assert run_path_dormancy_denials(src, "") == ["b"]


def test_eb4_each_denial_phrase_is_flagged_and_case_sensitive():
    for phrase in DENIALS:
        src = (f"def run_stage():\n    x()\ndef x():\n    '''{phrase} here.'''\n")
        assert run_path_dormancy_denials(src, "") == ["x"], phrase
    lower = "def run_stage():\n    x()\ndef x():\n    '''zero call site here.'''\n"
    assert run_path_dormancy_denials(lower, "") == []


def test_eb4_attribute_reference_is_followed():
    src = (
        "import sys\n"
        "def run_continuous():\n"
        "    return sys.modules[__name__].c\n"
        "def c():\n"
        "    '''no orchestrator calls this.'''\n"
    )
    assert run_path_dormancy_denials(src, "") == ["c"]


# ---------------------------------------------------------------- EB5: exclusions


def test_eb5_denial_reached_only_through_cli_or_main_is_ignored():
    src = (
        "def run_iteration():\n"
        "    pass\n"
        "def status_cli():\n"
        "    only_cli()\n"
        "def main():\n"
        "    only_main()\n"
        "def only_cli():\n"
        "    '''ZERO call site.'''\n"
        "def only_main():\n"
        "    '''DORMANT executor.'''\n"
    )
    assert run_path_dormancy_denials(src, "foundry.status_cli() foundry.main()") == []


def test_eb5_closure_does_not_enter_cli_called_from_run_root():
    src = (
        "def run_iteration():\n"
        "    thing_cli()\n"
        "def thing_cli():\n"
        "    deep()\n"
        "def deep():\n"
        "    '''ZERO call site.'''\n"
    )
    assert run_path_dormancy_denials(src, "") == []


def test_eb5_unreached_denial_is_ignored():
    src = (
        "def run_iteration():\n"
        "    pass\n"
        "def orphan():\n"
        "    '''ZERO call site; no orchestrator.'''\n"
    )
    assert run_path_dormancy_denials(src, "") == []


def test_eb5_dispatcher_reference_is_a_root():
    src = (
        "def run_iteration():\n"
        "    pass\n"
        "def watched():\n"
        "    '''DORMANT this iter.'''\n"
    )
    assert run_path_dormancy_denials(src, "") == []
    assert run_path_dormancy_denials(src, "x = foundry.watched(cfg)\n") == ["watched"]


def test_eb3_result_is_sorted():
    src = (
        "def run_iteration():\n"
        "    zed(); alpha()\n"
        "def zed():\n"
        "    '''ZERO call site.'''\n"
        "def alpha():\n"
        "    '''no orchestrator.'''\n"
    )
    assert run_path_dormancy_denials(src, "") == ["alpha", "zed"]
