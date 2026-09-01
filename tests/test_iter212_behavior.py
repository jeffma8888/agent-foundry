"""Iteration 212 behavior tests -- `test_quality_cli` composes its composite by
calling the shipped `gather_test_quality(cfg, files)` seam instead of carrying a
SECOND copy of the four-seam `summarize_test_quality(product=..., weak=...,
constant=..., skipped=...)` composition.

The change is behavior-preserving at the CLI's observable surface (text, JSON,
exit code), so most of this module is non-regression pinning; the one genuinely
NEW observable is that the seam is now on the CLI's path -- patching
`foundry.gather_test_quality` must change what the CLI prints and returns, and
the CLI must inherit the seam's single-walk / cache-restoring properties.

ISOLATION CONTRACT (HONORED): written ONLY from
`products/_platform/state/iter-212/pm.md` (Expected Behaviors 1-10), the
repo's `tests/` conventions (`tests/test_iter58_behavior.py` -- the CLI's own
behavior module, and `tests/test_iter159_behavior.py` -- the seam's single-walk /
cache module), and the product's OWN OBSERVABLE behaviour by RUNNING it. The
implementation source (`foundry.py` / `dispatcher.py` text), the engineer's notes,
the reviewer's notes and `git diff` were NOT read.

Offline & deterministic by construction: every fixture is built under `tmp_path`,
no real product repo is scanned, no network, no clock, no real git, no agent run
(the single documented exception is Behavior 10's `python -c "import foundry,
dispatcher"` importability probe). Nothing is written outside `tmp_path`.

HAZARD PIN (inherited from tests/test_iter159_behavior.py -- do not "tidy" this):
reach every seam as `foundry.<name>`. `foundry` exposes module-level names that
begin with `test_` (`test_tree`, `test_quality_cli`); a `from foundry import ...`
or star-import inside a COLLECTED test module re-exports them here, where pytest
collects them as zero-argument test functions and the suite goes red for a reason
that looks nothing like the change under test.
"""

from __future__ import annotations

import io
import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402


# --------------------------------------------------------------------------
# fixtures / helpers  (mirror tests/test_iter58_behavior.py + iter159)
# --------------------------------------------------------------------------

WEAK_SRC = "def test_no_assert():\n    x = 1\n"
CONST_SRC = "def test_constant():\n    assert True\n"
SKIP_SRC = "import pytest\n\n\n@pytest.mark.skip\ndef test_skipped():\n    assert 1 == 1\n"
CLEAN_SRC = "def test_clean():\n    assert 1 + 1 == 2\n"

EXPECTED_KEYS = [
    "product", "files_scanned", "weak_findings", "constant_findings",
    "skipped_findings", "total_findings", "total_parse_errors", "clean",
    "exit_code", "verdict", "weak", "constant", "skipped", "parse_errors",
]


def _W(**over):
    base = {"product": "p", "files_scanned": 0, "findings": (), "parse_errors": ()}
    base.update(over)
    return foundry.summarize_weak_tests(**base)


def _C(**over):
    base = {"product": "p", "files_scanned": 0, "findings": (), "parse_errors": ()}
    base.update(over)
    return foundry.summarize_constant_asserts(**base)


def _S(**over):
    base = {"product": "p", "files_scanned": 0, "findings": (), "parse_errors": ()}
    base.update(over)
    return foundry.summarize_skipped_tests(**base)


def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY -> (rc, out, err).
    Separate capture matters: the JSON path requires the JSON to be the ENTIRE
    stdout, so stderr noise must not contaminate the parse."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _prodcfg(tmp_path, repo="/nonexistent"):
    """ProductConfig with a NONEXISTENT repo by default, so a `--files` run that
    walks the repo cannot hide behind an ambient tree."""
    return foundry.ProductConfig(
        name="p",
        repo=repo,
        allowed_push_repo="p",
        vision=str(tmp_path / "VISION.md"),
        work_root=str(tmp_path / "work"),
    )


def _repo(tmp_path):
    """A synthetic product repo (one file per lens) -> (cfg, sorted file list)."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    for name, src in (
        ("test_weak.py", WEAK_SRC),
        ("test_const.py", CONST_SRC),
        ("test_skip.py", SKIP_SRC),
    ):
        (repo / "tests" / name).write_text(src)
    cfg = _prodcfg(tmp_path, repo=str(repo))
    files = sorted((repo / "tests").glob("test_*.py"), key=str)
    return cfg, files


def _snapshot_tree(root):
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*") if p.is_file()
    }


def _marker_summary():
    """A known composite carrying literals no real scan of the fixtures can
    produce -- so seeing them in the CLI's output proves the CLI consumed the
    patched seam's return value rather than composing its own."""
    return foundry.summarize_test_quality(
        product="SEAM_MARKER_PRODUCT",
        weak=_W(files_scanned=77, findings=(("marker_weak.py", "test_marker_weak"),)),
        constant=_C(files_scanned=77, findings=(("marker_const.py", "test_marker_const"),)),
        skipped=_S(files_scanned=77),
    )


# ==========================================================================
# Behavior 1 -- the CLI routes through the `gather_test_quality` seam
# ==========================================================================

def test_b01_cli_prints_the_patched_seams_summary_and_returns_its_exit_code(tmp_path, monkeypatch):
    """THE new observable. Pre-change control (measured by the PM stage): with the
    seam sabotaged the CLI ran to completion returning 0, i.e. it never called it."""
    cfg = _prodcfg(tmp_path)
    target = tmp_path / "test_clean.py"
    target.write_text(CLEAN_SRC)  # a genuinely CLEAN file -> a real scan gives 0
    marker = _marker_summary()
    seen = []

    def fake_seam(c, files=None):
        seen.append((c.name, tuple(files) if files is not None else None))
        return marker

    monkeypatch.setattr(foundry, "gather_test_quality", fake_seam)
    rc, out, err = _capture(
        lambda: foundry.test_quality_cli(cfg, files=[str(target)], as_json=False))

    assert seen == [("p", (str(target),))], (
        "the CLI must call gather_test_quality(cfg, files) exactly once with its "
        f"own arguments; calls seen: {seen}"
    )
    assert out == marker.render() + "\n", (
        "the CLI must print the SEAM's summary.render() verbatim\n"
        f"---got---\n{out}\n---want---\n{marker.render()}\n"
    )
    assert rc == marker.exit_code == 1, (
        f"the CLI must return the SEAM's exit_code ({marker.exit_code}), got {rc}"
    )
    assert "SEAM_MARKER_PRODUCT" in out and "test_marker_weak" in out, out
    assert err == "", f"nothing belongs on stderr: {err!r}"


def test_b01_cli_propagates_a_raise_from_the_seam(tmp_path, monkeypatch):
    """The two-sided half: if the CLI still composed its own copy it would run to
    completion (returning 0 on this clean file) and no exception would escape."""
    cfg = _prodcfg(tmp_path)
    target = tmp_path / "test_clean.py"
    target.write_text(CLEAN_SRC)

    def boom(c, files=None):
        raise RuntimeError("seam was called")

    monkeypatch.setattr(foundry, "gather_test_quality", boom)
    with pytest.raises(RuntimeError, match="seam was called"):
        _capture(lambda: foundry.test_quality_cli(cfg, files=[str(target)], as_json=False))


def test_b01_seam_also_bites_the_json_path(tmp_path, monkeypatch):
    cfg = _prodcfg(tmp_path)
    target = tmp_path / "test_clean.py"
    target.write_text(CLEAN_SRC)
    marker = _marker_summary()
    monkeypatch.setattr(foundry, "gather_test_quality", lambda c, files=None: marker)
    rc, out, _ = _capture(
        lambda: foundry.test_quality_cli(cfg, files=[str(target)], as_json=True))
    doc = json.loads(out)
    assert doc == marker.to_dict(), f"--json must serialise the SEAM's document: {doc}"
    assert rc == marker.exit_code == 1, rc


# ==========================================================================
# Behavior 2 -- clean tree unchanged
# ==========================================================================

def test_b02_clean_file_returns_0_and_text_ends_verdict_clean(tmp_path):
    cfg = _prodcfg(tmp_path)
    target = tmp_path / "test_clean.py"
    target.write_text(CLEAN_SRC)
    rc, out, err = _capture(
        lambda: foundry.test_quality_cli(cfg, files=[str(target)], as_json=False))
    assert rc == 0, f"a clean asserting test must exit 0, got {rc}\n{out}{err}"
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines[-1] == "verdict: clean", f"last line must be `verdict: clean`, got {lines[-1]!r}"
    assert "foundry test-quality -- p" in out, out
    assert "  files scanned: 1" in out, out
    assert "total quality findings: 0" in out, out


# ==========================================================================
# Behavior 3 -- findings tree unchanged (every triggered category named)
# ==========================================================================

def test_b03_each_category_is_named_and_exit_is_1(tmp_path):
    cfg, files = _repo(tmp_path)  # weak + constant + skipped, one file each
    rc, out, _ = _capture(
        lambda: foundry.test_quality_cli(cfg, files=[str(f) for f in files], as_json=False))
    assert rc == 1, f"quality issues must exit 1, got {rc}\n{out}"
    assert "[assertion-free] " in out, out
    assert "[constant-assert] " in out, out
    assert "[always-skipped] " in out, out
    assert "test_no_assert" in out and "test_constant" in out and "test_skipped" in out, out
    assert "  assertion-free tests: 1" in out, out
    assert "  constant-assert tests: 1" in out, out
    assert "  always-skipped tests: 1" in out, out
    assert "  total quality findings: 3" in out, out
    assert out.rstrip().endswith("verdict: QUALITY ISSUES FOUND"), out


# ==========================================================================
# Behavior 4 -- empty selection unchanged
# ==========================================================================

def test_b04_empty_files_returns_exit_2(tmp_path):
    cfg = _prodcfg(tmp_path)
    rc, out, _ = _capture(lambda: foundry.test_quality_cli(cfg, files=[], as_json=False))
    assert rc == 2, f"an empty --files selection scans nothing -> exit 2, got {rc}"
    assert out.rstrip().endswith("verdict: nothing to scan"), out


def test_b04_empty_files_json_also_returns_exit_2(tmp_path):
    cfg = _prodcfg(tmp_path)
    rc, out, _ = _capture(lambda: foundry.test_quality_cli(cfg, files=[], as_json=True))
    assert rc == 2, rc
    doc = json.loads(out)
    assert doc["exit_code"] == 2 and doc["verdict"] == "nothing to scan", doc


# ==========================================================================
# Behavior 5 -- --json unchanged: exactly ONE indent=2 document, same rc
# ==========================================================================

@pytest.mark.parametrize("kind,want_rc", [("clean", 0), ("dirty", 1)])
def test_b05_json_is_one_indent2_document_with_the_text_modes_exit_code(tmp_path, kind, want_rc):
    cfg = _prodcfg(tmp_path)
    target = tmp_path / "test_case.py"
    target.write_text(CLEAN_SRC if kind == "clean" else WEAK_SRC)
    files = [str(target)]

    rc_text, out_text, _ = _capture(
        lambda: foundry.test_quality_cli(cfg, files=files, as_json=False))
    rc_json, out_json, err_json = _capture(
        lambda: foundry.test_quality_cli(cfg, files=files, as_json=True))

    assert rc_text == rc_json == want_rc, (rc_text, rc_json, want_rc)
    assert err_json == "", f"the JSON path must keep stderr clean: {err_json!r}"
    # the ENTIRE stdout is ONE json document (a second one would fail to parse)
    doc = json.loads(out_json)
    assert list(doc.keys()) == EXPECTED_KEYS, f"key set/order changed: {list(doc.keys())}"
    assert out_json == json.dumps(doc, indent=2) + "\n", (
        "--json must print exactly json.dumps(summary.to_dict(), indent=2)\n"
        f"---got---\n{out_json!r}\n"
    )
    assert doc["exit_code"] == want_rc, doc
    # non-vacuous control: the JSON and the text agree on the verdict
    assert out_text.rstrip().endswith(f"verdict: {doc['verdict']}"), (out_text, doc["verdict"])


# ==========================================================================
# Behavior 6 -- the three sub-gather seams still bite THROUGH the CLI
# ==========================================================================

@pytest.mark.parametrize("seam,factory,marker", [
    ("gather_weak_tests", _W, "FAKE_WEAK"),
    ("gather_constant_asserts", _C, "FAKE_CONST"),
    ("gather_skipped_tests", _S, "FAKE_SKIP"),
])
def test_b06_each_sub_gather_seam_bites_through_the_cli(tmp_path, monkeypatch, seam, factory, marker):
    cfg = _prodcfg(tmp_path)
    target = tmp_path / "test_clean.py"
    target.write_text(CLEAN_SRC)  # clean under all three lenses

    base_rc, base_out, _ = _capture(
        lambda: foundry.test_quality_cli(cfg, files=[str(target)], as_json=False))
    assert base_rc == 0 and marker not in base_out, (base_rc, base_out)

    monkeypatch.setattr(
        foundry, seam,
        lambda c, files=None: factory(files_scanned=1, findings=(("fake.py", marker),)))
    rc, out, _ = _capture(
        lambda: foundry.test_quality_cli(cfg, files=[str(target)], as_json=False))
    assert marker in out, f"patching foundry.{seam} must change the CLI's output:\n{out}"
    assert rc == 1, f"a patched-in finding must flip the CLI's exit code, got {rc}"


# ==========================================================================
# Behavior 7 -- files=None walks the repo exactly ONCE
# ==========================================================================

def test_b07_files_none_walks_the_repo_exactly_once(tmp_path, monkeypatch):
    cfg, _ = _repo(tmp_path)
    walks = []
    real = foundry._gather_weak_test_files

    def proxy(repo):
        walks.append(str(repo))
        return real(repo)

    monkeypatch.setattr(foundry, "_gather_weak_test_files", proxy)
    rc, out, _ = _capture(lambda: foundry.test_quality_cli(cfg, files=None, as_json=False))
    assert walks == [cfg.repo], (
        f"files=None must walk the repo exactly ONCE (was 3x before this change): {walks}"
    )
    # control: the single walk still found the whole fixture and scored it
    assert "  files scanned: 3" in out, out
    assert rc == 1, (rc, out)


# ==========================================================================
# Behavior 8 -- files given never walks (non-regression pin)
# ==========================================================================

def test_b08_files_given_never_walks_the_repo(tmp_path, monkeypatch):
    cfg = _prodcfg(tmp_path)  # repo="/nonexistent"
    target = tmp_path / "test_weak.py"
    target.write_text(WEAK_SRC)

    def boom(repo):
        raise AssertionError(f"must not walk the repo when files are supplied: {repo}")

    monkeypatch.setattr(foundry, "_gather_weak_test_files", boom)
    rc, out, _ = _capture(
        lambda: foundry.test_quality_cli(cfg, files=[str(target)], as_json=False))
    assert rc == 1, (rc, out)
    assert "  files scanned: 1" in out, out
    assert "test_no_assert" in out, out


# ==========================================================================
# Behavior 9 -- the CLI leaves TEST_TREE_CACHE as it found it
# ==========================================================================

@pytest.mark.parametrize("mode", ["files", "none"])
def test_b09_cache_slot_is_none_before_and_after_a_cli_call(tmp_path, mode):
    cfg, files = _repo(tmp_path)
    assert foundry.TEST_TREE_CACHE is None, "precondition: the slot starts closed"
    arg = [str(f) for f in files] if mode == "files" else None
    _capture(lambda: foundry.test_quality_cli(cfg, files=arg, as_json=False))
    assert foundry.TEST_TREE_CACHE is None, \
        "the CLI must leave the cache slot as it found it (None)"


def test_b09_cache_slot_is_restored_when_a_lens_raises(tmp_path, monkeypatch):
    cfg, files = _repo(tmp_path)

    def boom(c, files=None):
        raise RuntimeError("lens exploded")

    monkeypatch.setattr(foundry, "gather_skipped_tests", boom)
    assert foundry.TEST_TREE_CACHE is None
    with pytest.raises(RuntimeError, match="lens exploded"):
        _capture(lambda: foundry.test_quality_cli(
            cfg, files=[str(f) for f in files], as_json=False))
    assert foundry.TEST_TREE_CACHE is None, \
        "the exception must propagate AND the slot must be restored (try/finally)"


# ==========================================================================
# Behavior 10 -- read-only CLI; both modules still import
# ==========================================================================

@pytest.mark.parametrize("mode,as_json", [("files", False), ("files", True), ("none", False)])
def test_b10_cli_writes_nothing_to_disk(tmp_path, mode, as_json):
    cfg, files = _repo(tmp_path)
    arg = [str(f) for f in files] if mode == "files" else None
    before = _snapshot_tree(tmp_path)
    _capture(lambda: foundry.test_quality_cli(cfg, files=arg, as_json=as_json))
    assert _snapshot_tree(tmp_path) == before, "the CLI wrote to disk (must be read-only)"


def test_b10_foundry_and_dispatcher_still_import():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"import regressed:\n{proc.stdout}\n{proc.stderr}"


def test_b10_public_surface_still_callable():
    """Non-vacuousness control for the whole module: the names it drives exist."""
    for name in ("test_quality_cli", "gather_test_quality", "summarize_test_quality",
                 "gather_weak_tests", "gather_constant_asserts", "gather_skipped_tests",
                 "_gather_weak_test_files"):
        assert callable(getattr(foundry, name)), f"foundry.{name} must be callable"
    assert hasattr(foundry, "TEST_TREE_CACHE")


# ==========================================================================
# Acceptance-criteria structural proof -- the SECOND copy is DELETED, not
# reshuffled. Public RUNTIME introspection only (compiled `__code__.co_names`
# tables and `__doc__`), never source text, so the isolation contract holds --
# the same technique tests/test_iter58_behavior.py uses for its dormancy checks.
# ==========================================================================

def _reachable_names(fn):
    """Every global/attr name reachable from fn's compiled code object,
    recursing into nested code objects."""
    out, stack = set(), [fn.__code__]
    while stack:
        code = stack.pop()
        out |= set(code.co_names)
        for const in code.co_consts:
            if hasattr(const, "co_names"):
                stack.append(const)
    return out


def test_ac_cli_calls_the_seam_and_no_longer_composes_it_itself():
    names = _reachable_names(foundry.test_quality_cli)
    assert "gather_test_quality" in names, (
        "test_quality_cli must call gather_test_quality by BARE name -- a bare-name "
        "call is what keeps monkeypatch.setattr(foundry, ...) biting"
    )
    # the duplicated composition is DELETED: the CLI no longer names the composer
    # nor any of the three sub-gathers it used to fold together itself.
    assert "summarize_test_quality" not in names, (
        "the CLI's own summarize_test_quality(...) composition must be DELETED, "
        "not merely supplemented by the seam call"
    )
    for sub in ("gather_weak_tests", "gather_constant_asserts", "gather_skipped_tests"):
        assert sub not in names, (
            f"the CLI must reach {sub} only THROUGH gather_test_quality, not directly"
        )
    # non-vacuousness control: the extractor really does see this function's names.
    assert names, "co_names extraction returned nothing -- the check would be vacuous"


def test_ac_module_no_longer_promises_work_it_has_already_done():
    """The promise is gone -- measured on a WHITESPACE-NORMALISED docstring.

    Two-sidedness note (measured this stage against the pre-change module): the owed
    sentence is WRAPPED in the source, so the phrase is NOT a contiguous substring of
    the raw `__doc__` even before this change -- a raw-substring form of this check
    PASSES on the pre-change module and is therefore vacuous. Both sides go through
    the one normaliser below, which makes the check fail pre-change and pass now.
    """
    doc = foundry.gather_test_quality.__doc__ or ""
    assert doc, "gather_test_quality must keep a docstring"
    norm = " ".join(doc.split())
    # non-vacuousness control for the normaliser itself: it must collapse real wrapping.
    assert " ".join("a\n    b".split()) == "a b", "the normaliser must collapse wrapping"
    assert "separate future bite" not in norm, (
        "gather_test_quality's docstring must stop promising the DRY refactor as an "
        "owed 'separate future bite' -- this iteration performed it"
    )
    assert "keeps its OWN inline composition" not in norm, (
        "the docstring must stop asserting the CLI carries its own inline composition"
    )
    # presence check only (true pre-change too, so NOT discriminating on its own):
    assert "test_quality_cli" in norm, (
        "the docstring should record that test_quality_cli now shares this seam"
    )


def test_ac_cli_docstring_names_the_seam_and_keeps_its_dormant_clause():
    doc = foundry.test_quality_cli.__doc__ or ""
    assert doc, "test_quality_cli must keep a docstring"
    assert "gather_test_quality" in doc, (
        "the CLI's docstring must name the seam it now composes through"
    )
    # the spec leaves item 25's wording ALONE -- pin that it was not opportunistically
    # edited while the surrounding sentences changed.
    assert "DORMANT" in doc, (
        "the CLI docstring's DORMANT clause is explicitly OUT OF SCOPE this iteration "
        "and must be left alone"
    )
