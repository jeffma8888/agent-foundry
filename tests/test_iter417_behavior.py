"""Iteration 417 behavior tests -- the suite's first shared helper module,
``tests/_shared.py``, holding two pure functions ``split_source_lines(source)``
and ``source_segment(lines, node)`` that together are byte-identical to
``ast.get_source_segment(source, node)`` but O(1) per node, with the eight
``ast.get_source_segment`` call sites in ``test_iter197`` / ``test_iter179`` /
``test_iter204`` rewritten onto them.

BLACK-BOX / ISOLATION (honored): every assertion below was derived from the PM
spec (``pm.md``, iteration 417: Feature / Why / Out of Scope -- its Expected
Behaviors list is a checkpoint stub) and from the iter-417 rows of
``PLATFORM_ROADMAP.md`` / ``PLATFORM_ROADMAP_ARCHIVE.md``, plus the conventions
of the existing modules under ``tests/``. The engineer's notes, the reviewer's
notes, ``IMPLEMENTATION.patch`` and ``git diff`` were NOT read. ``tests/`` is
inside the isolation contract's read set, so the three consumer modules and the
new helper module are read MECHANICALLY (``ast.parse`` of their text) to count
call sites; the helper's behavior is asserted only through its public names.

Offline by construction: no subprocess, no git, no network, nothing written
anywhere. Filesystem reads are ``foundry.py`` and files under ``tests/``, all
located at RUNTIME from this file's location (never a source-literal absolute
path, never a gitignored path, never a count of ambient files).

The oracle for "byte-identical" is the stdlib itself, but the stdlib call is
the quadratic cost this iteration removes (~10 ms per call on foundry.py), so
the foundry.py comparison is a bounded SAMPLE of nodes (Behavior 4) while the
synthetic corner-case sources compare EVERY node (Behavior 3).

HAZARD PIN (inherited from iter 159/160) -- always reach through ``foundry.``;
``from foundry import *`` re-exports a seam named ``test_tree`` that pytest then
collects as a zero-argument test.
"""

from __future__ import annotations

import ast
import fnmatch
import importlib
import pathlib
import sys
import time
from collections.abc import Sequence

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

TESTS_DIR = pathlib.Path(__file__).resolve().parent
SHARED_PATH = TESTS_DIR / "_shared.py"
SHARED_MODULE = "_shared"
PUBLIC_NAMES = ("split_source_lines", "source_segment")
CONSUMERS = (
    "test_iter197_behavior.py",
    "test_iter179_behavior.py",
    "test_iter204_behavior.py",
)
SPEC_CALL_SITES = 8
# Non-boundary characters: str.splitlines() breaks on all of these, the parser
# (and therefore ast.get_source_segment) breaks on NONE of them.
NON_BOUNDARIES = ("\x0c", "\x85", "\u2028", "\x1c", "\x1d", "\x1e", "\x0b")

# Synthetic sources exercising every line-end convention the parser accepts,
# plus multi-byte characters (col offsets are UTF-8 BYTE offsets) and the
# non-boundary control characters inside string literals.
SYNTHETIC_SOURCES = {
    "lf": "x = 1\ny = 'héllo'\nz = (1,\n     2)\ndef f(a, *b, c=3):\n    return [a, b, c]\n",
    "crlf": "x = 1\r\ny = 'héllo'\r\nz = (1,\r\n     2)\r\nclass K:\r\n    v = 'ü'\r\n",
    "cr": "x = 1\ry = 'héllo'\rz = (1,\r     2)\rw = {'k': 'ü'}\r",
    "formfeed": "x = 1\n\fy = 'a\fb'\nz = 'ü\x85\u2028\x1c\x1d\x1e\x0b'\nw = (1,\n\f  2)\n",
    "multibyte": "a='日本語'\r\nb = ( 'x' ,\r 2 ,\n 3 )\nc = '😀' + 'é'*2\nd=1",
    "no_trailing_newline": "x = 1\ny = 2",
    "empty": "",
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _shared():
    """Import the helper lazily so 'unchanged' behaviors stay green at HEAD."""
    try:
        return importlib.import_module(SHARED_MODULE)
    except ModuleNotFoundError as exc:  # pragma: no cover - HEAD control
        pytest.fail(f"tests/{SHARED_MODULE}.py must be importable by bare name: {exc}")


def _fns():
    mod = _shared()
    split = getattr(mod, PUBLIC_NAMES[0], None)
    seg = getattr(mod, PUBLIC_NAMES[1], None)
    assert callable(split), f"{SHARED_MODULE}.{PUBLIC_NAMES[0]} must be callable"
    assert callable(seg), f"{SHARED_MODULE}.{PUBLIC_NAMES[1]} must be callable"
    return split, seg


def _module_ast(name: str) -> ast.Module:
    path = TESTS_DIR / name
    assert path.is_file(), f"{path} must exist"
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _calls(tree: ast.Module, *, attr_of: str | None = None, name: str | None = None) -> list[ast.Call]:
    """Call nodes whose callee is ``<attr_of>.<name>`` (attr_of given) or bare ``name``."""
    out: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if attr_of is not None:
            if (
                isinstance(fn, ast.Attribute)
                and fn.attr == name
                and isinstance(fn.value, ast.Name)
                and fn.value.id == attr_of
            ):
                out.append(node)
        elif isinstance(fn, ast.Name) and fn.id == name:
            out.append(node)
    return out


def _imported_from_shared(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == SHARED_MODULE and node.level == 0:
            names.update(alias.name for alias in node.names)
    return names


class _CountingLines(Sequence):
    """A line list that records every index/slice access and refuses iteration,
    so a per-node cost that scales with the number of lines is observable."""

    def __init__(self, lines):
        self._lines = list(lines)
        self.gets = 0

    def __getitem__(self, item):
        self.gets += 1
        return self._lines[item]

    def __len__(self):
        return len(self._lines)

    def __iter__(self):  # pragma: no cover - only reached on a regression
        raise AssertionError("source_segment must not iterate the whole line list")


# --------------------------------------------------------------------------
# Behavior 1 -- the shared module exists with exactly the two public functions
# --------------------------------------------------------------------------
def test_b1_shared_module_exists_and_is_importable_by_bare_name():
    assert SHARED_PATH.is_file(), "tests/_shared.py must exist"
    mod = _shared()
    assert pathlib.Path(mod.__file__).resolve() == SHARED_PATH.resolve()
    for name in PUBLIC_NAMES:
        assert callable(getattr(mod, name, None)), f"{SHARED_MODULE}.{name} must be a callable"


def test_b1_public_surface_is_exactly_the_two_spec_functions():
    tree = _module_ast("_shared.py")
    public_defs = sorted(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    )
    assert public_defs == sorted(PUBLIC_NAMES), public_defs
    # "Two pure functions": no class-based API, no module-level side effects.
    assert not any(isinstance(n, ast.ClassDef) for n in tree.body)


def test_b1_no_tests_package_init_so_bare_name_import_is_the_convention():
    # The roadmap row: importable "because pytest's prepend import mode puts
    # tests/ on sys.path with no tests/__init__.py".
    assert not (TESTS_DIR / "__init__.py").exists()


# --------------------------------------------------------------------------
# Behavior 2 -- split_source_lines splits exactly as the parser counts lines
# --------------------------------------------------------------------------
@pytest.mark.parametrize("key", sorted(SYNTHETIC_SOURCES))
def test_b2_split_is_lossless_with_ends_kept(key):
    split, _ = _fns()
    src = SYNTHETIC_SOURCES[key]
    lines = split(src)
    assert isinstance(lines, list)
    assert all(isinstance(line, str) for line in lines)
    assert "".join(lines) == src, "ends must be kept so the join is the source"


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
def test_b2_lf_crlf_and_lone_cr_each_end_a_line(ending):
    split, _ = _fns()
    src = ending.join(["a = 1", "b = 2", "c = 3"]) + ending
    lines = [line for line in split(src) if line]  # drop any trailing empty sentinel
    assert lines == ["a = 1" + ending, "b = 2" + ending, "c = 3" + ending]


def test_b2_crlf_is_one_line_end_not_two():
    split, _ = _fns()
    lines = [line for line in split("a\r\nb\r\n") if line]
    assert lines == ["a\r\n", "b\r\n"], lines


@pytest.mark.parametrize("ch", NON_BOUNDARIES)
def test_b2_non_parser_line_breaks_do_not_split(ch):
    split, _ = _fns()
    src = f"s = 'p{ch}q'\nt = 2\n"
    lines = [line for line in split(src) if line]
    assert lines == [f"s = 'p{ch}q'\n", "t = 2\n"], lines


def test_b2_empty_source_yields_no_content_lines():
    split, _ = _fns()
    assert [line for line in split("") if line] == []


# --------------------------------------------------------------------------
# Behavior 3 -- source_segment is byte-identical to the stdlib on EVERY node of
# the synthetic sources, including the None cases
# --------------------------------------------------------------------------
@pytest.mark.parametrize("key", sorted(k for k in SYNTHETIC_SOURCES if SYNTHETIC_SOURCES[k]))
def test_b3_every_node_matches_stdlib_on_synthetic_sources(key):
    split, seg = _fns()
    src = SYNTHETIC_SOURCES[key]
    tree = ast.parse(src)
    lines = split(src)
    compared = 0
    for node in ast.walk(tree):
        expected = ast.get_source_segment(src, node)
        got = seg(lines, node)
        assert got == expected, (key, type(node).__name__, expected, got)
        if expected is not None:
            assert isinstance(got, str)
            assert got.encode() == expected.encode()
        compared += 1
    assert compared >= 3, "walk must have covered real nodes"


def test_b3_multibyte_columns_slice_by_utf8_bytes():
    split, seg = _fns()
    src = "a = '日本語'; b = 'é'\n"
    tree = ast.parse(src)
    lines = split(src)
    consts = [n for n in ast.walk(tree) if isinstance(n, ast.Constant)]
    got = [seg(lines, n) for n in sorted(consts, key=lambda n: n.col_offset)]
    assert got == ["'日本語'", "'é'"], got
    for n in consts:
        assert seg(lines, n) == ast.get_source_segment(src, n)


def test_b3_returns_none_exactly_when_stdlib_does():
    split, seg = _fns()
    src = "x = 1\n"
    lines = split(src)
    module = ast.parse(src)                       # no lineno / col_offset at all
    no_end = ast.Constant(value=1, lineno=1, col_offset=0)   # end_* left None
    detached = ast.Name(id="x", ctx=ast.Load())   # positionless, hand-built
    for node in (module, no_end, detached):
        assert ast.get_source_segment(src, node) is None
        assert seg(lines, node) is None, type(node).__name__
    # and the positive control on the same source
    assign = module.body[0]
    assert seg(lines, assign) == ast.get_source_segment(src, assign) == "x = 1"
    assert seg(lines, assign.value) == "1"


def test_b3_multiline_node_spans_first_middle_and_last_lines():
    split, seg = _fns()
    src = "pre = 0\nz = (1,\n     2,\n     3)\npost = 4\n"
    tree = ast.parse(src)
    lines = split(src)
    z = tree.body[1]
    assert seg(lines, z) == "z = (1,\n     2,\n     3)"
    assert seg(lines, z) == ast.get_source_segment(src, z)
    assert seg(lines, z.value) == "(1,\n     2,\n     3)"


# --------------------------------------------------------------------------
# Behavior 4 -- byte-identical on foundry.py (the real 1.5 MB consumer) and
# O(1) per node: the number of line accesses does not depend on the line count,
# and the whole top-level walk takes milliseconds, not seconds
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def foundry_source():
    src = (_ROOT / "foundry.py").read_text(encoding="utf-8")
    return src, ast.parse(src, filename="foundry.py")


def test_b4_matches_stdlib_on_a_bounded_sample_of_foundry_nodes(foundry_source):
    split, seg = _fns()
    src, tree = foundry_source
    lines = split(src)
    top = list(tree.body)
    assert len(top) >= 100, "foundry.py is expected to have hundreds of top-level statements"
    # Every ~27th top-level statement, plus the first/last, plus a spread of
    # deep nodes: ~60 stdlib calls, well under a second, every kind of span.
    step = max(1, len(top) // 30)
    sample = top[::step] + [top[0], top[-1]]
    deep = [n for n in ast.walk(top[len(top) // 2]) if hasattr(n, "lineno")]
    sample += deep[:: max(1, len(deep) // 25)]
    assert len(sample) >= 30
    for node in sample:
        expected = ast.get_source_segment(src, node)
        assert seg(lines, node) == expected, type(node).__name__


def test_b4_whole_top_level_walk_is_fast(foundry_source):
    split, seg = _fns()
    src, tree = foundry_source
    lines = split(src)
    t0 = time.perf_counter()
    segments = [seg(lines, node) for node in tree.body]
    elapsed = time.perf_counter() - t0
    assert all(isinstance(s, str) and s for s in segments)
    # Spec/roadmap measurement: 0.0011 s for 810 nodes vs 7.94 s via the stdlib.
    # A 2 s bound is >1000x headroom for xdist contention while still ruling out
    # the quadratic re-split (which cannot finish in 2 s on this file).
    assert elapsed < 2.0, f"{len(segments)} segments took {elapsed:.3f} s"


def test_b4_line_accesses_per_node_are_independent_of_line_count(foundry_source):
    split, seg = _fns()
    src = SYNTHETIC_SOURCES["lf"]
    tree = ast.parse(src)
    base_lines = split(src)
    padded_lines = base_lines + ["pad = 0\n"] * 50_000
    for node in ast.walk(tree):
        a, b = _CountingLines(base_lines), _CountingLines(padded_lines)
        got_a, got_b = seg(a, node), seg(b, node)
        assert got_a == got_b == ast.get_source_segment(src, node)
        assert a.gets == b.gets, (type(node).__name__, a.gets, b.gets)
        assert a.gets <= 3, f"{type(node).__name__}: {a.gets} line accesses for one node"


# --------------------------------------------------------------------------
# Behavior 5 -- the eight call sites in the three named consumers moved onto
# the shared slicer, one split per source; nothing else in scope
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", CONSUMERS)
def test_b5_consumer_imports_both_helpers_from_shared(name):
    tree = _module_ast(name)
    imported = _imported_from_shared(tree)
    assert set(PUBLIC_NAMES) <= imported, (name, imported)


@pytest.mark.parametrize("name", CONSUMERS)
def test_b5_consumer_has_no_stdlib_get_source_segment_call(name):
    tree = _module_ast(name)
    stale = _calls(tree, attr_of="ast", name="get_source_segment")
    assert stale == [], f"{name}: {len(stale)} ast.get_source_segment call(s) remain at lines {[c.lineno for c in stale]}"


@pytest.mark.parametrize("name", CONSUMERS)
def test_b5_consumer_splits_once_per_source_and_slices_per_node(name):
    tree = _module_ast(name)
    splits = _calls(tree, name=PUBLIC_NAMES[0])
    segs = _calls(tree, name=PUBLIC_NAMES[1])
    assert splits, f"{name}: no split_source_lines call"
    assert segs, f"{name}: no source_segment call"
    assert len(splits) <= len(segs), (name, len(splits), len(segs))
    # every slice call hands the pre-split lines (a Name), never the raw source
    for call in segs:
        assert len(call.args) == 2, ast.dump(call)
        assert isinstance(call.args[0], ast.Name), ast.dump(call)


def test_b5_exactly_the_spec_eight_call_sites_across_the_three_consumers():
    total = sum(len(_calls(_module_ast(name), name=PUBLIC_NAMES[1])) for name in CONSUMERS)
    assert total == SPEC_CALL_SITES, total


def test_b5_out_of_scope_helper_not_moved_into_shared():
    # Out of Scope: "Moving `_co_names_deep` or any other duplicated helper".
    tree = _module_ast("_shared.py")
    names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    assert "_co_names_deep" not in names, names


# --------------------------------------------------------------------------
# Behavior 6 -- the helper is not a test module: pytest's python_files and the
# foundry WEAK_TEST_GLOBS census both skip it, and it defines nothing collectable
# --------------------------------------------------------------------------
def test_b6_shared_is_not_collected_as_a_test_module():
    basename = SHARED_PATH.name
    assert not basename.startswith("test_")
    for pattern in ("test_*.py", "*_test.py"):  # pytest's default python_files
        assert not fnmatch.fnmatch(basename, pattern), pattern
    globs = getattr(foundry, "WEAK_TEST_GLOBS", None)
    assert globs, "foundry.WEAK_TEST_GLOBS must exist"
    assert not any(fnmatch.fnmatch(basename, g) for g in globs), globs
    tree = _module_ast(basename)
    collectable = [
        n.name
        for n in tree.body
        if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"))
        or (isinstance(n, ast.ClassDef) and n.name.startswith("Test"))
    ]
    assert collectable == [], collectable


def test_b6_shared_is_pure_no_io_no_process_no_network():
    tree = _module_ast("_shared.py")
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    banned = {"subprocess", "os", "socket", "urllib", "requests", "shutil", "pathlib", "io", "time"}
    assert not (imported & banned), imported & banned
    assert not _calls(tree, name="open"), "pure helpers must not open files"
