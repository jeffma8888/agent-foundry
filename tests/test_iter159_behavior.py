"""Iteration 159 behavior tests -- one read + one ``ast.parse`` per test file for
the composite test-quality gather, with byte-identical output.

BLACK-BOX / ISOLATION: written from
``products/_platform/state/iter-159/pm.md`` (Expected Behaviors 1-8) plus probing
the PUBLIC interface from an interpreter. The implementation source, the
engineer's notes, the reviewer's notes and ``git diff`` were NOT read.

Offline by construction: every fixture is built under ``tmp_path``, no real
product repo is scanned, no subprocess, no network, no clock, nothing is written
outside ``tmp_path``.

HAZARD PIN -- do not "tidy" this into a star/direct import. ``foundry`` exposes a
module-level seam whose name begins with ``test_`` (``test_tree``). A
``from foundry import test_tree`` (or ``import *``) inside a COLLECTED test module
re-exports that name into the module namespace, where pytest collects it as a test
function and calls it with zero arguments -- the suite then goes red for a reason
that looks nothing like the change under test. Today it is safe only because
``pyproject.toml`` pins ``testpaths = ["tests"]`` (so ``foundry.py`` itself is
never collected) and no test module star-imports it. Always reach the seam as
``foundry.test_tree``.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402


# --------------------------------------------------------------------------
# fixtures -- a synthetic product repo, one file per detector (Behavior 6's
# named layout: assertion-free / constant-assert / always-skipped / clean /
# invalid Python)
# --------------------------------------------------------------------------

WEAK_SRC = "def test_no_assert():\n    x = 1\n"
CONST_SRC = "def test_constant():\n    assert True\n"
SKIP_SRC = "import pytest\n\n\n@pytest.mark.skip\ndef test_skipped():\n    assert 1 == 1\n"
CLEAN_SRC = "def test_clean():\n    assert 1 + 1 == 2\n"
BAD_SRC = "def test_bad(:\n"


def _repo(tmp_path):
    """Build the synthetic product repo; return (cfg, sorted file list)."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    for name, src in (
        ("test_weak.py", WEAK_SRC),
        ("test_const.py", CONST_SRC),
        ("test_skip.py", SKIP_SRC),
        ("test_clean.py", CLEAN_SRC),
        ("test_bad.py", BAD_SRC),
    ):
        (repo / "tests" / name).write_text(src)
    cfg = foundry.ProductConfig(
        name="p",
        repo=str(repo),
        allowed_push_repo="p",
        vision=str(tmp_path / "VISION.md"),
        work_root=str(tmp_path / "work"),
    )
    files = sorted((repo / "tests").glob("test_*.py"), key=str)
    return cfg, files


def _snapshot(root: pathlib.Path):
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def _composed(cfg, files):
    """The document built by composing the three lens gathers INDIVIDUALLY --
    the reference output the composite must reproduce key for key."""
    return foundry.summarize_test_quality(
        product=cfg.name,
        weak=foundry.gather_weak_tests(cfg, files),
        constant=foundry.gather_constant_asserts(cfg, files),
        skipped=foundry.gather_skipped_tests(cfg, files),
    ).to_dict()


def _counting(real, calls):
    def proxy(path):
        calls.append(str(path))
        return real(path)
    return proxy


# --------------------------------------------------------------------------
# Behavior 0 (acceptance criterion) -- the three new module-level names exist
# --------------------------------------------------------------------------

def test_b0_new_module_level_names_exist_and_cache_defaults_to_none():
    assert callable(foundry.parse_test_file), "parse_test_file must be module-level+callable"
    assert callable(foundry.test_tree), "test_tree must be module-level+callable"
    assert hasattr(foundry, "TEST_TREE_CACHE"), "TEST_TREE_CACHE slot must exist"
    assert foundry.TEST_TREE_CACHE is None, \
        f"TEST_TREE_CACHE default must be None, got {foundry.TEST_TREE_CACHE!r}"
    # non-vacuous control: the module really is the foundry module under test.
    assert callable(foundry.gather_test_quality)


# --------------------------------------------------------------------------
# Behavior 1 -- parse_test_file(path)
# --------------------------------------------------------------------------

def test_b1_parse_test_file_returns_ast_module_for_str_and_path(tmp_path):
    p = tmp_path / "test_clean.py"
    p.write_text(CLEAN_SRC)
    for arg in (p, str(p)):
        tree = foundry.parse_test_file(arg)
        assert isinstance(tree, ast.Module), f"expected ast.Module for {type(arg).__name__}"
    # control: the parse is real, not a stub -- the function def is in the tree.
    names = [n.name for n in ast.walk(foundry.parse_test_file(p))
             if isinstance(n, ast.FunctionDef)]
    assert names == ["test_clean"], f"parsed tree missing the real body: {names}"


def test_b1_parse_test_file_propagates_syntaxerror_verbatim(tmp_path):
    p = tmp_path / "test_bad.py"
    p.write_text(BAD_SRC)
    with pytest.raises(SyntaxError) as ei:
        foundry.parse_test_file(p)
    # the caller formats f"{type(exc).__name__}: {exc}" -- so the message must be
    # the one ast.parse itself raises, not a re-wrapped string.
    expected = None
    try:
        ast.parse(BAD_SRC)
    except SyntaxError as exc:
        expected = f"{type(exc).__name__}: {exc}"
    assert f"{type(ei.value).__name__}: {ei.value}" == expected, \
        "SyntaxError must propagate verbatim (same text as a bare ast.parse)"


def test_b1_parse_test_file_raises_oserror_on_missing_path(tmp_path):
    with pytest.raises(OSError):
        foundry.parse_test_file(tmp_path / "does_not_exist.py")


def test_b1_parse_test_file_creates_nothing_on_disk(tmp_path):
    p = tmp_path / "test_clean.py"
    p.write_text(CLEAN_SRC)
    before = _snapshot(tmp_path)
    foundry.parse_test_file(p)
    with pytest.raises(OSError):
        foundry.parse_test_file(tmp_path / "missing.py")
    assert _snapshot(tmp_path) == before, "parse_test_file must not create or modify files"


# --------------------------------------------------------------------------
# Behavior 2 -- the three finders accept an already-parsed tree
# --------------------------------------------------------------------------

FINDERS = ("find_assertionless_tests", "find_constant_assert_tests",
           "find_always_skipped_tests")

# (source, the finder that must FIRE on it, the name it must report)
POSITIVES = (
    (WEAK_SRC, "find_assertionless_tests", "test_no_assert"),
    (CONST_SRC, "find_constant_assert_tests", "test_constant"),
    (SKIP_SRC, "find_always_skipped_tests", "test_skipped"),
)


@pytest.mark.parametrize("finder", FINDERS)
@pytest.mark.parametrize("src", [WEAK_SRC, CONST_SRC, SKIP_SRC, CLEAN_SRC])
def test_b2_finder_agrees_between_tree_and_source(finder, src):
    fn = getattr(foundry, finder)
    from_source = fn(src)
    from_tree = fn(ast.parse(src))
    assert isinstance(from_source, tuple) and isinstance(from_tree, tuple)
    assert from_tree == from_source, \
        f"{finder} disagreed: tree={from_tree} source={from_source}"


@pytest.mark.parametrize("src,finder,name", POSITIVES)
def test_b2_positive_cases_are_non_vacuous_on_both_inputs(src, finder, name):
    """Control for the agreement test above: agreement is only evidence if the
    detector actually FIRES for at least one input in the fixture."""
    fn = getattr(foundry, finder)
    assert fn(src) == (name,), f"{finder} must fire on its positive fixture (source)"
    assert fn(ast.parse(src)) == (name,), f"{finder} must fire on its positive fixture (tree)"
    # ... and stay silent on the clean file, for both input kinds.
    assert fn(CLEAN_SRC) == () and fn(ast.parse(CLEAN_SRC)) == (), \
        f"{finder} must not fire on the clean fixture"


@pytest.mark.parametrize("finder", FINDERS)
def test_b2_source_text_still_raises_syntaxerror_verbatim(finder):
    fn = getattr(foundry, finder)
    with pytest.raises(SyntaxError):
        fn(BAD_SRC)


# --------------------------------------------------------------------------
# Behavior 3 -- test_tree(path) over the TEST_TREE_CACHE slot
# --------------------------------------------------------------------------

def test_b3_no_cache_means_every_call_parses(tmp_path, monkeypatch):
    p = tmp_path / "test_clean.py"
    p.write_text(CLEAN_SRC)
    calls = []
    monkeypatch.setattr(foundry, "TEST_TREE_CACHE", None)
    monkeypatch.setattr(foundry, "parse_test_file",
                        _counting(foundry.parse_test_file, calls))
    a = foundry.test_tree(p)
    b = foundry.test_tree(p)
    assert calls == [str(p), str(p)], \
        f"with no cache open, both calls must route to parse_test_file: {calls}"
    assert isinstance(a, ast.Module) and isinstance(b, ast.Module)


def test_b3_open_cache_parses_once_and_returns_identical_object(tmp_path, monkeypatch):
    p = tmp_path / "test_clean.py"
    p.write_text(CLEAN_SRC)
    other = tmp_path / "test_weak.py"
    other.write_text(WEAK_SRC)
    cache = {}
    calls = []
    monkeypatch.setattr(foundry, "TEST_TREE_CACHE", cache)
    monkeypatch.setattr(foundry, "parse_test_file",
                        _counting(foundry.parse_test_file, calls))
    first = foundry.test_tree(p)
    second = foundry.test_tree(str(p))
    third = foundry.test_tree(other)
    assert second is first, "a cached path must return the IDENTICAL tree object"
    assert calls == [str(p), str(other)], \
        f"each distinct path must be parsed exactly once: {calls}"
    assert set(cache) == {str(p), str(other)}, \
        f"cache must be keyed by str(path): {sorted(cache)}"
    assert cache[str(p)] is first


def test_b3_seam_is_called_by_bare_name(tmp_path, monkeypatch):
    """The bare-name seam contract: replacing foundry.parse_test_file must bite."""
    p = tmp_path / "test_clean.py"
    p.write_text(CLEAN_SRC)
    marker = ast.parse("x = 1")
    monkeypatch.setattr(foundry, "TEST_TREE_CACHE", None)
    monkeypatch.setattr(foundry, "parse_test_file", lambda path: marker)
    assert foundry.test_tree(p) is marker, \
        "test_tree must call parse_test_file by BARE name (monkeypatchable)"


# --------------------------------------------------------------------------
# Behavior 4 -- the composite parses each file once
# --------------------------------------------------------------------------

def test_b4_composite_parses_each_parseable_file_exactly_once(tmp_path, monkeypatch):
    cfg, files = _repo(tmp_path)
    calls = []
    monkeypatch.setattr(foundry, "parse_test_file",
                        _counting(foundry.parse_test_file, calls))
    foundry.gather_test_quality(cfg, files)
    parseable = [f for f in files if f.name != "test_bad.py"]
    assert len(parseable) >= 4, "control: the fixture must hold >=4 parseable files"
    for f in parseable:
        assert calls.count(str(f)) == 1, \
            f"{f.name} parsed {calls.count(str(f))}x, expected exactly 1 (was 3 before)"
    assert len(calls) <= len(parseable) + 3, \
        f"only the unparseable file may be retried per lens: {calls}"


def test_b4_parse_failures_are_recorded_per_lens_and_not_cached(tmp_path):
    cfg, files = _repo(tmp_path)
    bad = str(tmp_path / "repo" / "tests" / "test_bad.py")
    doc = foundry.gather_test_quality(cfg, files).to_dict()
    for lens in ("weak", "constant", "skipped"):
        errors = doc[lens]["parse_errors"]
        assert len(errors) == 1, f"{lens} must record its OWN parse_errors entry: {errors}"
        assert errors[0]["file"] == bad
        assert errors[0]["message"].startswith("SyntaxError: "), \
            f"{lens} parse_error message shape changed: {errors[0]['message']!r}"
    # The roll-up does NOT sum the three lenses (measured: 1, one distinct
    # unparseable file). Whatever the rule is, behavior 6 pins it -- the composite
    # must equal the individually-composed document. Asserted here as the
    # pre-existing value so a change in the roll-up cannot hide behind behavior 4.
    assert doc["total_parse_errors"] == 1, \
        f"roll-up parse-error count changed: {doc['total_parse_errors']}"


# --------------------------------------------------------------------------
# Behavior 5 -- the composite walks once
# --------------------------------------------------------------------------

def test_b5_files_none_walks_exactly_once(tmp_path, monkeypatch):
    cfg, _ = _repo(tmp_path)
    walks = []
    real = foundry._gather_weak_test_files

    def proxy(repo):
        walks.append(repo)
        return real(repo)

    monkeypatch.setattr(foundry, "_gather_weak_test_files", proxy)
    doc = foundry.gather_test_quality(cfg, None).to_dict()
    assert walks == [cfg.repo], \
        f"files=None must walk the repo exactly ONCE (was 3x): {walks}"
    assert doc["files_scanned"] == 5, "control: the single walk still found the fixture"


def test_b5_files_given_never_walks(tmp_path, monkeypatch):
    cfg, files = _repo(tmp_path)

    def boom(repo):
        raise AssertionError("must not walk the repo when files are supplied")

    monkeypatch.setattr(foundry, "_gather_weak_test_files", boom)
    doc = foundry.gather_test_quality(cfg, files).to_dict()
    assert doc["files_scanned"] == 5
    assert doc["total_findings"] == 3


# --------------------------------------------------------------------------
# Behavior 6 -- output-preserving, key for key
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["files", "none"])
def test_b6_composite_equals_individually_composed_document(tmp_path, mode):
    cfg, files = _repo(tmp_path)
    arg = files if mode == "files" else None
    got = foundry.gather_test_quality(cfg, arg).to_dict()
    expected = _composed(cfg, arg)
    assert list(got.keys()) == list(expected.keys()), "top-level key ORDER must be preserved"
    for key in expected:
        assert got[key] == expected[key], f"key {key!r} diverged: {got[key]!r} != {expected[key]!r}"
    assert got == expected


def test_b6_document_carries_the_expected_named_figures(tmp_path):
    """Non-vacuous control for the equality above: the fixture must actually
    exercise all three detectors plus a parse error, or the two documents could
    agree while both being empty."""
    cfg, files = _repo(tmp_path)
    d = foundry.gather_test_quality(cfg, files).to_dict()
    assert d["files_scanned"] == 5
    assert d["weak_findings"] == 1 and d["constant_findings"] == 1 and d["skipped_findings"] == 1
    assert d["total_findings"] == 3 and d["total_parse_errors"] == 1
    assert d["clean"] is False and d["exit_code"] == 1 and d["verdict"]
    assert d["weak"]["findings"][0]["test"] == "test_no_assert"
    assert d["constant"]["findings"][0]["test"] == "test_constant"
    assert d["skipped"]["findings"][0]["test"] == "test_skipped"


# --------------------------------------------------------------------------
# Behavior 7 -- no cache state survives the call
# --------------------------------------------------------------------------

def test_b7_cache_slot_is_none_before_and_after(tmp_path):
    cfg, files = _repo(tmp_path)
    assert foundry.TEST_TREE_CACHE is None
    foundry.gather_test_quality(cfg, files)
    assert foundry.TEST_TREE_CACHE is None, "the composite must restore the slot on return"
    foundry.gather_test_quality(cfg, None)
    assert foundry.TEST_TREE_CACHE is None


def test_b7_cache_slot_is_restored_when_a_lens_raises(tmp_path, monkeypatch):
    cfg, files = _repo(tmp_path)

    def boom(cfg, files=None):
        raise RuntimeError("lens exploded")

    monkeypatch.setattr(foundry, "gather_skipped_tests", boom)
    assert foundry.TEST_TREE_CACHE is None
    with pytest.raises(RuntimeError, match="lens exploded"):
        foundry.gather_test_quality(cfg, files)
    assert foundry.TEST_TREE_CACHE is None, \
        "the exception must propagate AND the slot must be restored (try/finally)"


def test_b7_nested_composite_returns_the_same_document(tmp_path, monkeypatch):
    """A real nested call: one lens gather re-enters the composite once (guarded),
    so the inner call runs with the OUTER cache already open."""
    cfg, files = _repo(tmp_path)
    unnested = foundry.gather_test_quality(cfg, files).to_dict()

    real_skipped = foundry.gather_skipped_tests
    seen = {"n": 0, "inner": None, "cache_open": None}

    def reentrant(cfg_, files_=None):
        seen["n"] += 1
        if seen["n"] == 1:
            seen["cache_open"] = foundry.TEST_TREE_CACHE is not None
            seen["inner"] = foundry.gather_test_quality(cfg_, files_).to_dict()
        return real_skipped(cfg_, files_)

    monkeypatch.setattr(foundry, "gather_skipped_tests", reentrant)
    outer = foundry.gather_test_quality(cfg, files).to_dict()
    assert seen["cache_open"] is True, "control: the outer call must have a cache open"
    assert seen["inner"] == unnested, "a nested composite must return the same document"
    assert outer == unnested, "nesting must not change the outer document"
    assert foundry.TEST_TREE_CACHE is None, "the OUTER call must restore None"


def test_b7_an_already_open_cache_is_restored_not_clobbered(tmp_path, monkeypatch):
    """Save/restore semantics: an inner call restores the value it SAVED, so a
    caller-owned cache survives (and gets reused, not bypassed)."""
    cfg, files = _repo(tmp_path)
    sentinel = {}
    monkeypatch.setattr(foundry, "TEST_TREE_CACHE", sentinel)
    doc = foundry.gather_test_quality(cfg, files).to_dict()
    assert foundry.TEST_TREE_CACHE is sentinel, \
        "the composite must restore the SAVED value, not hard-set None"
    assert sentinel, "an already-open cache must be REUSED (it should hold parsed trees)"
    monkeypatch.setattr(foundry, "TEST_TREE_CACHE", None)
    assert doc == foundry.gather_test_quality(cfg, files).to_dict(), \
        "an open outer cache must not change the document"


# --------------------------------------------------------------------------
# Behavior 8 -- no signature change to the three lens gathers
# --------------------------------------------------------------------------

LENSES = ("gather_weak_tests", "gather_constant_asserts", "gather_skipped_tests")


@pytest.mark.parametrize("lens", LENSES)
def test_b8_lens_gather_signature_is_still_cfg_files_none(lens):
    params = list(inspect.signature(getattr(foundry, lens)).parameters.values())
    assert [p.name for p in params] == ["cfg", "files"], \
        f"{lens} parameter NAMES changed: {[p.name for p in params]}"
    assert params[0].default is inspect.Parameter.empty
    assert params[1].default is None, f"{lens}: files must still default to None"


def _canned(kind):
    cls = {"weak": foundry.WeakTestSummary,
           "constant": foundry.ConstantAssertSummary,
           "skipped": foundry.SkippedTestSummary}[kind]
    return cls(product="canned", files_scanned=7,
               findings=(("canned.py", f"test_canned_{kind}"),), parse_errors=())


@pytest.mark.parametrize("lens,kind", list(zip(LENSES, ("weak", "constant", "skipped"))))
def test_b8_two_arg_lambda_replacement_reshapes_the_composite(tmp_path, monkeypatch, lens, kind):
    """The composite must pass the lens gathers NO extra argument: a
    `lambda cfg, files=None: <canned summary>` must be callable by it AND must
    reshape the reported figures (bare-name seam contract)."""
    cfg, files = _repo(tmp_path)
    canned = _canned(kind)
    monkeypatch.setattr(foundry, lens, lambda cfg, files=None: canned)
    doc = foundry.gather_test_quality(cfg, files).to_dict()
    assert doc[kind]["findings"] == [{"file": "canned.py", "test": f"test_canned_{kind}"}], \
        f"replacing foundry.{lens} must reshape the composite (no extra arg passed)"
    assert doc[f"{kind}_findings"] == 1


def test_b8_all_three_lambdas_at_once_still_compose(tmp_path, monkeypatch):
    cfg, files = _repo(tmp_path)
    for lens, kind in zip(LENSES, ("weak", "constant", "skipped")):
        canned = _canned(kind)
        monkeypatch.setattr(foundry, lens, lambda cfg, files=None, c=canned: c)
    doc = foundry.gather_test_quality(cfg, files).to_dict()
    assert doc["total_findings"] == 3 and doc["total_parse_errors"] == 0
    assert doc["files_scanned"] == 7, "figures must come from the replaced seams"


@pytest.mark.parametrize("lens", LENSES)
def test_b8_lens_gather_called_directly_with_no_cache_open(tmp_path, lens):
    """Called directly (no cache open) each lens gather still returns what the
    composite reports for the same fixture -- i.e. it did not become
    cache-dependent."""
    cfg, files = _repo(tmp_path)
    assert foundry.TEST_TREE_CACHE is None
    direct = getattr(foundry, lens)(cfg, files)
    key = {"gather_weak_tests": "weak", "gather_constant_asserts": "constant",
           "gather_skipped_tests": "skipped"}[lens]
    inside = foundry.gather_test_quality(cfg, files).to_dict()[key]
    assert direct.to_dict() == inside, f"{lens} standalone output diverged from the composite"
    assert foundry.TEST_TREE_CACHE is None, "a direct lens call must leave the slot None"
