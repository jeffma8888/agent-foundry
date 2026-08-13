"""Black-box behaviour tests for iter 170 -- the shared weak-test file gather scopes its walk
to the repo's OWN tests directory, so the four test-hygiene verbs (and their four company
roll-ups) stop reporting findings from gitignored foreign trees.

Spec: products/_platform/state/iter-170/pm.md, Expected Behaviors 1-8.

  1. tests/test_a.py + state/test_b.py + products/p/test_c.py -> EXACTLY tests/test_a.py.
  2. No tests/ dir -> the pre-change whole-repo walk, unchanged (fallback).
  3. WEAK_TEST_ROOT_DIRS patched to ("suite",) -> EXACTLY suite/test_a.py (read at CALL time:
     the same repo is gathered BEFORE and AFTER the patch in one test, so an import-time
     capture is ruled out).
  4. WEAK_TEST_ROOT_DIRS patched to () -> whole-repo walk again (behavior 2's fallback).
  5. Both globs still apply under a scoped root; result deduped and sorted ascending.
  6. Pruning survives scoping: a hidden component directly under the scan root and a
     DIRECTORY named test_dir.py are both excluded -- and a hidden component ABOVE the repo
     excludes nothing (the relative_to anchor stays at the repo).
  7. --files mode untouched: gather_weak_tests(cfg, files=[p]) scans exactly p and never
     consults the gather (patched to raise to prove it).
  8. LIVE PROPERTY on this repo (never an ambient COUNT): every returned path's first
     component relative to the repo root is tests, and no returned path has a products
     component. Anchored on a git-TRACKED file (tests/test_foundry.py) so it holds in a
     fresh clone too.
  Plus Acceptance-Criteria oracles: the constant's shape/default, list[Path] + sorted +
  deduped return contract (asserted on EVERY gather in this file), read-only and
  subprocess-free, no new ProductConfig field, a fresh-interpreter import probe, the
  iteration-170 roadmap ledger row (<=120 chars) + archive bullet, the downstream
  test-quality report actually dropping foreign state trees, and hostile patched tuples
  never raising inside a read-only verb.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-170 PM spec's Expected Behaviors,
the conventions of tests/ (the _ROOT/sys.path + literals-pinned-here + _write_cfg shape of
test_iter42_behavior.py and test_iter58_behavior.py), the roadmap files that Acceptance
Criteria make the deliverable itself, and the product's OBSERVABLE surface -- CALLING the
public functions and the CLI. The implementation source of foundry.py / dispatcher.py, the
engineer's notes (engineer.md), the reviewer's notes (reviewer.md / fix_review.md),
IMPLEMENTATION.patch and git diff were NOT read. (Disclosure: the bounded foundry-learnings
digest injected into this stage's prompt contained [ENG iter170] / [REV iter170] / [FIX
iter170] entries I did not seek and cannot unread; no assertion here was derived from a
named implementation detail -- every clause below traces to a numbered spec behavior or an
acceptance criterion.)

Offline and deterministic: every fixture is built in tmp_path, the real foundry repo is
never mutated, and the only subprocess is the documented fresh-interpreter import probe.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

THIS_ITER = 170
ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"

# Pinned HERE (never imported from the module under test) so a default change is caught.
DEFAULT_ROOTS = ("tests",)
GLOBS = ("test_*.py", "*_test.py")

# Assertion-free body -> a weak-test finding, so the same source doubles as CLI input.
_WEAK_SRC = "def test_x():\n    pass\n"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _repo(tmp_path, *rels, name="repo"):
    """A tmp repo seeded with the given relative FILE paths (the real repo is untouched)."""
    repo = tmp_path / name
    repo.mkdir(parents=True, exist_ok=True)
    for rel in rels:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_WEAK_SRC)
    return repo


def _gather(repo):
    """Call the seam and enforce the Acceptance-Criteria return contract on EVERY call."""
    out = foundry._gather_weak_test_files(str(repo))
    assert isinstance(out, list), f"return type must stay a list, got {type(out).__name__}"
    assert all(isinstance(p, pathlib.Path) for p in out), f"members must be pathlib.Path: {out!r}"
    assert out == sorted(out), f"result must be sorted ascending: {out!r}"
    assert len(set(out)) == len(out), f"result must be deduped: {out!r}"
    return out


def _rel(repo, paths):
    repo = pathlib.Path(repo)
    return [pathlib.Path(p).relative_to(repo).as_posix() for p in paths]


def _write_cfg(tmp_path, files=None, **over):
    """A minimal product config whose repo is a TMP dir."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    for rel, body in (files or {}).items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    out = tmp_path / "config.json"
    out.write_text(json.dumps(data))
    return out


def _snapshot(root):
    root = pathlib.Path(root)
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _capture(fn):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = fn()
        except SystemExit as exc:          # argparse / early exit
            code = exc.code
    return code, out.getvalue(), err.getvalue()


# ==========================================================================
# Behavior 1 -- the walk is scoped to the repo's own tests dir
# ==========================================================================
def test_b1_scopes_the_walk_to_the_repos_own_tests_dir(tmp_path):
    repo = _repo(tmp_path, "tests/test_a.py", "state/test_b.py", "products/p/test_c.py")
    got = _rel(repo, _gather(repo))
    assert got == ["tests/test_a.py"], (
        f"only the repo's own suite may be gathered, got {got}"
    )


def test_b1_deeply_nested_files_under_the_scoped_root_are_still_found(tmp_path):
    repo = _repo(tmp_path, "tests/unit/deep/test_a.py", "products/p/state/i/test_c.py")
    got = _rel(repo, _gather(repo))
    assert got == ["tests/unit/deep/test_a.py"], got


# ==========================================================================
# Behavior 2 -- no tests/ dir -> the pre-change whole-repo walk (fallback)
# ==========================================================================
def test_b2_repo_without_a_tests_dir_walks_the_whole_repo(tmp_path):
    repo = _repo(tmp_path, "test_a.py", "pkg/test_b.py")
    assert not (repo / "tests").exists(), "fixture precondition: no tests/ dir"
    got = _rel(repo, _gather(repo))
    assert got == ["pkg/test_b.py", "test_a.py"], (
        f"with no tests/ dir the gather must be byte-identical to the old walk, got {got}"
    )


def test_b2_a_tests_FILE_is_not_a_root(tmp_path):
    """Only an existing DIRECTORY named in the tuple may become a walk root; a plain file
    called tests must leave the fallback in place (most reasonable reading of the spec)."""
    repo = _repo(tmp_path, "test_a.py", "pkg/test_b.py")
    (repo / "tests").write_text("not a directory\n")
    got = _rel(repo, _gather(repo))
    assert got == ["pkg/test_b.py", "test_a.py"], got


# ==========================================================================
# Behavior 3 -- WEAK_TEST_ROOT_DIRS is read at CALL time
# ==========================================================================
def test_b3_roots_tuple_is_read_at_call_time_not_captured_at_import(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "suite/test_a.py", "tests/test_b.py")
    before = _rel(repo, _gather(repo))
    assert before == ["tests/test_b.py"], f"default must scope to tests/, got {before}"
    monkeypatch.setattr(foundry, "WEAK_TEST_ROOT_DIRS", ("suite",))
    after = _rel(repo, _gather(repo))
    assert after == ["suite/test_a.py"], (
        f"patched tuple must bite on the SAME already-imported module, got {after}"
    )


def test_b3_several_roots_are_all_walked(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "suite/test_a.py", "tests/test_b.py", "state/test_c.py")
    monkeypatch.setattr(foundry, "WEAK_TEST_ROOT_DIRS", ("suite", "tests"))
    got = _rel(repo, _gather(repo))
    assert got == ["suite/test_a.py", "tests/test_b.py"], got


# ==========================================================================
# Behavior 4 -- an EMPTY tuple restores the whole-repo walk
# ==========================================================================
def test_b4_empty_roots_tuple_walks_the_whole_repo_again(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "tests/test_a.py", "state/test_b.py")
    monkeypatch.setattr(foundry, "WEAK_TEST_ROOT_DIRS", ())
    got = _rel(repo, _gather(repo))
    assert got == ["state/test_b.py", "tests/test_a.py"], (
        f"an empty tuple must replay the pre-change walk, got {got}"
    )


def test_b4_a_named_root_that_does_not_exist_falls_back_too(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "tests/test_a.py", "state/test_b.py")
    monkeypatch.setattr(foundry, "WEAK_TEST_ROOT_DIRS", ("nope",))
    got = _rel(repo, _gather(repo))
    assert got == ["state/test_b.py", "tests/test_a.py"], got


# ==========================================================================
# Behavior 5 -- both globs, deduped, sorted ascending
# ==========================================================================
def test_b5_both_globs_apply_under_a_scoped_root_deduped_and_sorted(tmp_path):
    repo = _repo(tmp_path,
                 "tests/test_a.py",        # test_*.py
                 "tests/b_test.py",        # *_test.py
                 "tests/test_both_test.py",  # BOTH globs -> must appear once
                 "tests/helper.py")        # neither glob
    got = _rel(repo, _gather(repo))
    assert got == ["tests/b_test.py", "tests/test_a.py", "tests/test_both_test.py"], got


# ==========================================================================
# Behavior 6 -- pruning rules survive the scoping
# ==========================================================================
def test_b6_hidden_component_under_the_scan_root_and_non_regular_file_are_pruned(tmp_path):
    repo = _repo(tmp_path,
                 "tests/test_ok.py",
                 "tests/.hidden/test_x.py",
                 "tests/.git/test_g.py")
    (repo / "tests" / "test_dir.py").mkdir()          # a DIRECTORY, not a regular file
    got = _rel(repo, _gather(repo))
    assert got == ["tests/test_ok.py"], (
        f"hidden components and non-regular files must stay excluded, got {got}"
    )


def test_b6_hidden_component_ABOVE_the_repo_excludes_nothing(tmp_path):
    """The hidden/.git rule is measured relative to the REPO, so a hidden ancestor of the
    repo itself must not empty the report."""
    repo = _repo(tmp_path / ".hidden_parent", "tests/test_a.py", "tests/b_test.py")
    got = _rel(repo, _gather(repo))
    assert got == ["tests/b_test.py", "tests/test_a.py"], got


# ==========================================================================
# Behavior 7 -- --files mode is untouched
# ==========================================================================
def test_b7_files_mode_scans_exactly_the_given_path_and_never_gathers(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path, files={
        "tests/test_own.py": _WEAK_SRC,
        "state/test_snap.py": _WEAK_SRC,
    })
    cfg = foundry.load_config(str(cfg_path))
    target = str(pathlib.Path(cfg.repo) / "state" / "test_snap.py")

    def boom(repo):
        raise AssertionError("_gather_weak_test_files must NOT be consulted in --files mode")

    monkeypatch.setattr(foundry, "_gather_weak_test_files", boom)
    summary = foundry.gather_weak_tests(cfg, files=[target])       # must NOT raise
    assert summary.files_scanned == 1, summary.files_scanned
    assert [f for f, _ in summary.findings] == [target], summary.findings


# ==========================================================================
# Behavior 8 -- live property on THIS repo (never an ambient count)
# ==========================================================================
def test_b8_live_gather_returns_only_paths_under_tests_and_no_products():
    got = _gather(_ROOT)
    assert got, "this repo HAS a tests/ dir, so the live gather must return something"
    rels = [p.relative_to(_ROOT) for p in got]
    outside = [r.as_posix() for r in rels if r.parts[0] != "tests"]
    assert outside == [], f"first component must be tests for every path: {outside[:10]}"
    foreign = [r.as_posix() for r in rels if "products" in r.parts]
    assert foreign == [], f"no returned path may carry a products component: {foreign[:10]}"


def test_b8_live_gather_includes_a_git_tracked_test_file():
    """Anchored on a TRACKED file, so the property is meaningful in a fresh clone (no
    ambient count, no gitignored precondition)."""
    tracked = _ROOT / "tests" / "test_foundry.py"
    assert tracked.is_file(), "fixture precondition: tests/test_foundry.py is tracked"
    assert tracked in _gather(_ROOT), "a tracked tests/ file must still be gathered"


# ==========================================================================
# Acceptance Criteria oracles
# ==========================================================================
def test_ac_roots_constant_shape_and_default():
    roots = foundry.WEAK_TEST_ROOT_DIRS
    assert isinstance(roots, tuple), f"must be a tuple, got {type(roots).__name__}"
    assert roots == DEFAULT_ROOTS, f"default must be {DEFAULT_ROOTS!r}, got {roots!r}"
    assert all(isinstance(r, str) for r in roots), roots
    assert foundry.WEAK_TEST_GLOBS == GLOBS, f"globs must not change: {foundry.WEAK_TEST_GLOBS!r}"


def test_ac_gather_is_read_only_and_spawns_no_subprocess(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "tests/test_a.py", "state/test_b.py")

    def boom(*a, **k):
        raise AssertionError("the gather must not shell out (no git / check-ignore)")

    for name in ("run", "check_output", "check_call", "call", "Popen"):
        monkeypatch.setattr(subprocess, name, boom)
    before = _snapshot(repo)
    assert _rel(repo, _gather(repo)) == ["tests/test_a.py"]
    assert _snapshot(repo) == before, "the gather wrote to disk (it must be read-only)"


def test_ac_no_new_product_config_field():
    names = {f.name for f in dataclasses.fields(foundry.ProductConfig)}
    offenders = sorted(n for n in names if "weak_test_root" in n or n == "test_roots")
    assert offenders == [], f"no config field may be added for the roots tuple: {offenders}"


def test_ac_modules_still_import_in_a_fresh_interpreter():
    proc = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                          cwd=str(_ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_ac_test_quality_report_drops_foreign_state_trees(tmp_path):
    """The downstream user-visible payoff: one seam, the shipped verb's report."""
    cfg_path = _write_cfg(tmp_path, files={
        "tests/test_own.py": _WEAK_SRC,
        "products/dead/state/iter-39/test_snapshot.py": _WEAK_SRC,
        "state/test_local.py": _WEAK_SRC,
    })
    code, out, _ = _capture(lambda: foundry.main(
        ["test-quality", "--config", str(cfg_path), "--json"]))
    doc = json.loads(out)
    assert code == 1 and doc["exit_code"] == 1, (code, doc.get("exit_code"))
    blob = json.dumps(doc)
    assert "test_own.py" in blob, blob
    assert "test_snapshot.py" not in blob, f"a foreign snapshot leaked into the report:\n{blob}"
    assert "test_local.py" not in blob, f"a non-suite root file leaked into the report:\n{blob}"


def test_ac_test_quality_human_verdict_and_exit_code_unchanged(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"tests/test_own.py": _WEAK_SRC})
    code, out, _ = _capture(lambda: foundry.main(["test-quality", "--config", str(cfg_path)]))
    assert code == 1, code
    assert "[assertion-free]" in out, out
    clean = _write_cfg(tmp_path / "clean", files={"tests/test_ok.py": "def test_r():\n    assert a == 1\n"})
    code2, _, _ = _capture(lambda: foundry.main(["test-quality", "--config", str(clean)]))
    assert code2 == 0, code2


def test_ac_roadmap_record_for_this_iteration_landed():
    ledger = [ln for ln in ROADMAP.read_text().splitlines()
              if ln.startswith(f"- iter {THIS_ITER} ")]
    assert len(ledger) == 1, f"exactly one iter-{THIS_ITER} ledger row required: {ledger}"
    assert len(ledger[0]) <= 120, f"ledger row must be <=120 chars, got {len(ledger[0])}"
    bullets = [ln for ln in ARCHIVE.read_text().splitlines()
               if ln.startswith(f"- **iter {THIS_ITER} ")]
    assert len(bullets) == 1, f"exactly one archive bullet required, got {len(bullets)}"


@pytest.mark.parametrize("roots", [
    ("",), (".",), ("/abs",), ("..",), ("tests/../..",), ("tests/nested",),
    ("missing",), ("tests", "tests"), ("tests", "missing"), "tests", (),
])
def test_ac_hostile_roots_tuple_never_raises_in_a_read_only_verb(tmp_path, monkeypatch, roots):
    """A patchable module constant is attacker-shaped input to a read-only report verb."""
    repo = _repo(tmp_path, "tests/test_a.py", "state/test_b.py")
    monkeypatch.setattr(foundry, "WEAK_TEST_ROOT_DIRS", roots)
    out = foundry._gather_weak_test_files(str(repo))
    assert isinstance(out, list), f"{roots!r} must not break the return contract: {out!r}"
    assert all(isinstance(p, pathlib.Path) for p in out), out


def test_ac_no_new_cli_surface_for_the_roots_tuple():
    """AC: no new CLI verb and no `--help` change -- the roots tuple stays a module-level
    constant, so neither the top-level help nor any of the four hygiene verbs may grow an
    option (or a verb) naming it."""
    tokens = ("--roots", "--root-dirs", "--test-root", "--weak-test-root", "WEAK_TEST_ROOT")
    _, top, _ = _capture(lambda: foundry.main(["--help"]))
    assert top, "top-level --help must still print"
    assert [t for t in tokens if t in top] == [], top
    for verb in ("weak-tests", "constant-asserts", "skipped-tests", "test-quality"):
        _, txt, _ = _capture(lambda v=verb: foundry.main([v, "--help"]))
        assert [t for t in tokens if t in txt] == [], (verb, txt)
        opts = {w.strip(",") for w in txt.split() if w.startswith("--")}
        assert opts == {"--config", "--files", "--json", "--help"}, (verb, sorted(opts))
