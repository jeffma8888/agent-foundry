"""Iteration 487 -- suite-wide guard: no test asserts on an unscoped `git diff HEAD`.

Why: iter-469 EB5/EB6 ran `git diff ... HEAD` with no pathspec, so they read
whatever a LATER iteration had uncommitted. They were red in every worktree
after 469 and green only in a fresh clone, which trained every gate to ignore
a red suite. Iter 487 re-scoped them to their own commit; this module stops the
pattern from coming back.

`unscoped_head_diff_lines` is a pure AST scan: a list/tuple literal or a call's
positional-argument list is a hit when its string constants include both the
diff verb and the HEAD ref (exact element equality) but no `--` pathspec
separator. Four pre-existing modules are allowlisted with a reason each; the
allowlist is itself checked for rot so a stale entry cannot linger.

The needles below are built by concatenation so this module scans clean.
"""
from __future__ import annotations

import ast
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS_DIR = _ROOT / "tests"

DIFF_NEEDLE = "di" + "ff"
HEAD_NEEDLE = "HE" + "AD"
PATHSPEC_SEP = "-" + "-"

# Module filename -> why its unscoped HEAD diff is not a working-tree fossil.
ALLOWLIST: dict[str, str] = {
    "test_iter151_behavior.py": "fake-git seam keys",
    "test_iter368_behavior.py": "helper output filtered to a frozen set",
    "test_iter379_behavior.py": "gated by its pre-commit window, inert after ship",
    "test_iter420_behavior.py": "expected-call literal against a monkeypatched seam",
}


def _string_elements(nodes: list[ast.expr]) -> set[str]:
    """The string constants among a sequence of AST nodes (others are ignored)."""
    return {
        n.value for n in nodes
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


def _is_unscoped_head_diff(nodes: list[ast.expr]) -> bool:
    """True when the elements name the diff verb and HEAD but carry no `--`."""
    strings = _string_elements(nodes)
    return (
        DIFF_NEEDLE in strings
        and HEAD_NEEDLE in strings
        and PATHSPEC_SEP not in strings
    )


def unscoped_head_diff_lines(source: str) -> list[int]:
    """Sorted line numbers of unscoped `git diff ... HEAD` argument sequences.

    Returns [] for unparsable source and never raises, so one broken file
    cannot mask the scan of every other module.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    hits: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            elements = list(node.elts)
        elif isinstance(node, ast.Call):
            elements = list(node.args)
        else:
            continue
        if _is_unscoped_head_diff(elements):
            hits.add(node.lineno)
    return sorted(hits)


def _scan_tests_dir() -> dict[str, list[int]]:
    """Map every tests/*.py filename with at least one hit to its hit lines."""
    found: dict[str, list[int]] = {}
    for path in sorted(TESTS_DIR.glob("*.py")):
        lines = unscoped_head_diff_lines(path.read_text(encoding="utf-8"))
        if lines:
            found[path.name] = lines
    return found


# ---------------------------------------------------------------------------
# Two-sided proof of the scanner on synthetic sources
# ---------------------------------------------------------------------------

def _src(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_list_literal_unscoped_head_diff_is_a_hit() -> None:
    source = _src(
        "import subprocess",
        f"subprocess.run(['git', '{DIFF_NEEDLE}', '--stat', '{HEAD_NEEDLE}'])",
    )
    assert unscoped_head_diff_lines(source) == [2]


def test_call_positional_args_unscoped_head_diff_is_a_hit() -> None:
    source = _src(
        "x = 1",
        "y = 2",
        f"_git('{DIFF_NEEDLE}', '--name-only', '{HEAD_NEEDLE}')",
    )
    assert unscoped_head_diff_lines(source) == [3]


def test_tuple_literal_is_a_hit() -> None:
    source = _src(f"ARGS = ('git', '{DIFF_NEEDLE}', '{HEAD_NEEDLE}')")
    assert unscoped_head_diff_lines(source) == [1]


def test_pathspec_separator_scopes_the_diff() -> None:
    source = _src(
        f"CMD = ['git', '{DIFF_NEEDLE}', '{HEAD_NEEDLE}', '{PATHSPEC_SEP}', 'x.py']"
    )
    assert unscoped_head_diff_lines(source) == []


def test_git_show_of_a_commit_is_not_a_hit() -> None:
    source = _src("CMD = ['git', 'show', '--numstat', 'd9c40f7']")
    assert unscoped_head_diff_lines(source) == []


def test_head_tilde_is_not_exact_head() -> None:
    source = _src(f"CMD = ['git', '{DIFF_NEEDLE}', '{HEAD_NEEDLE}~1']")
    assert unscoped_head_diff_lines(source) == []


def test_unparsable_source_returns_empty() -> None:
    assert unscoped_head_diff_lines("def f(:") == []


def test_this_module_scans_clean() -> None:
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert unscoped_head_diff_lines(source) == []


# ---------------------------------------------------------------------------
# Suite-wide guard + allowlist anti-rot
# ---------------------------------------------------------------------------

def test_no_unscoped_head_diff_outside_allowlist() -> None:
    offenders = [
        f"tests/{name}:{line}"
        for name, lines in _scan_tests_dir().items()
        if name not in ALLOWLIST
        for line in lines
    ]
    assert offenders == [], (
        "test(s) run an unscoped `git diff ... HEAD`, which reads a later "
        "iteration's uncommitted work; scope it to a commit or a `--` "
        f"pathspec: {offenders}"
    )


def test_allowlist_has_no_stale_entries() -> None:
    found = _scan_tests_dir()
    stale = [
        name for name in ALLOWLIST
        if not (TESTS_DIR / name).is_file() or name not in found
    ]
    assert stale == [], f"stale allowlist entries (missing or 0 hits): {stale}"


def test_iter469_module_is_clean_and_not_allowlisted() -> None:
    assert "test_iter469_behavior.py" not in ALLOWLIST
    source = (TESTS_DIR / "test_iter469_behavior.py").read_text(encoding="utf-8")
    assert unscoped_head_diff_lines(source) == []


def test_allowlist_is_exactly_the_four_reasoned_modules() -> None:
    assert set(ALLOWLIST) == {
        "test_iter151_behavior.py",
        "test_iter368_behavior.py",
        "test_iter379_behavior.py",
        "test_iter420_behavior.py",
    }
    assert all(reason.strip() for reason in ALLOWLIST.values())
