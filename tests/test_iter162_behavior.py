"""Iteration 162 behavior tests -- the DORMANT 'save-work' CLI verb that exports the
product repo's uncommitted work (tracked edits AND untracked new files) to
IMPLEMENTATION.patch in the newest iter-NN state dir WITHOUT mutating the real git
index.

Spec: products/_platform/state/iter-162/pm.md, Expected Behaviors 1-9.

  1. save_work_patch(cfg) writes the patch and returns its Path; bytes are the seam's
     text normalised to exactly ONE trailing newline and NOTHING else.
  2. One seam (worktree_patch_text) called by BARE module name, so a monkeypatch drives
     every branch with zero real git/subprocess/network.
  3. A clean tree writes nothing, returns None, and never clobbers an earlier rescue.
  4. Target = highest-NUMBERED iter-<digits> child of cfg.state, via iteration_numbers.
  5. TOTAL by construction: any failure yields None, never an exception.
  6. worktree_patch_text never mutates the real index and returns stdout only.
  7. Dormant: no new call site on the control path.
  8. The CLI prints exactly one 'save-work: ' line and exits 0 / 2 / 1 decidably.
  9. README documents the verb as the next numbered index entry, '# 46.'.

ISOLATION CONTRACT (HONORED): every check below was derived ONLY from the iter-162 PM
spec's Expected Behaviors, the pre-existing tests under tests/ (chiefly
tests/test_iter151_behavior.py for the tmp-config / scripted-seam idioms and
tests/test_iter160_behavior.py for the AST dormancy-scan idiom), the shipped README,
and the product's OWN observable behaviour driven through its public interface plus
runtime introspection. The implementation source of foundry.py, the engineer's notes,
the reviewer's notes and 'git diff' were NOT read by a human. The only implementation
bytes any test here touches are read MECHANICALLY by _refs_by_scope (an AST scan for
Behavior 7's dormancy claim).

Offline except for Behavior 6's single throwaway git repo built by the test itself in
tmp_path (the one real-git test the spec allows), one 'save-work' subprocess proving
the argparse wiring, and one clean-interpreter import probe. Nothing is written outside
tmp_path. Source is pure ASCII.

HAZARD PIN (inherited from iterations 159/160) -- do NOT "tidy" this into a star
import. foundry exposes a module-level seam whose name begins with 'test_'
(test_tree); 'from foundry import *' inside a COLLECTED module re-exports it and pytest
then calls it as a zero-argument test. Always reach through 'foundry.'.

READING PINNED FOR BEHAVIOR 3 (ambiguity, reported to the PM in tester.md): "an
existing patch is left BYTE-UNCHANGED" is scoped to the CLEAN-TREE path, not applied
unconditionally. Forced by the spec itself, three ways: behavior 3's own stated reason
("after the abort-path reset the tree IS clean"), its acceptance criterion (sentinel
first, then run "against a clean-tree seam"), and behaviors 1 + 8, which promise a
write and a SAVED exit for a non-empty diff -- an unconditional no-clobber guard would
refuse every second save and contradict both. Tested BOTH halves below.
"""

from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

README = _ROOT / "README.md"
PATCH_NAME = "IMPLEMENTATION.patch"

DIFF = (
    "diff --git a/foundry.py b/foundry.py\n"
    "index 1111111..2222222 100644\n"
    "--- a/foundry.py\n"
    "+++ b/foundry.py\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new"
)

# Control-path functions that must gain NO reference to the new names (spec b7).
# Every name is a confirmed module-level def in foundry.py.
CONTROL_PATH = (
    "run_iteration",
    "run_stage",
    "revert_repo",
    "next_iteration",
    "preship_verdict",
    "decide_product_gate",
    "product_gate_precheck",
)
NEW_NAMES = ("save_work_patch", "worktree_patch_text", "save_work_cli")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _cfg(tmp_path, **over):
    """A minimal product config whose repo/work_root live in tmp, so the real foundry
    repo and state tree are NEVER touched."""
    tmp_path = pathlib.Path(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "branch": "main",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    n = len(list(tmp_path.glob("cfg_*.json")))
    p = tmp_path / ("cfg_%d.json" % n)
    p.write_text(json.dumps(data), encoding="utf-8")
    return foundry.load_config(str(p))


def _iters(cfg, *names):
    """Create the given iter-NN dirs under cfg.state and return the state Path."""
    state = pathlib.Path(cfg.state)
    for n in names:
        (state / n).mkdir(parents=True, exist_ok=True)
    return state


def _seam(monkeypatch, text, calls=None):
    """Install a SCRIPTED worktree_patch_text seam -- zero real git."""

    def fake(cfg):
        if calls is not None:
            calls.append(cfg)
        if isinstance(text, Exception):
            raise text
        return text

    monkeypatch.setattr(foundry, "worktree_patch_text", fake)
    return calls


def _files_under(root):
    root = pathlib.Path(root)
    if not root.exists():
        return []
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def _one_line(capsys):
    """Assert exactly one non-empty stdout line and return it."""
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, "expected exactly one line, got %r" % (out,)
    return lines[0]


def _refs_by_scope(path, names):
    """MECHANICAL AST scan: name -> set of top-level scopes referencing it.

    A 'def <name>' statement is NOT a reference (FunctionDef.name is a str, not a
    Name node), so a function referencing only itself never appears.
    """
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    out = {n: set() for n in names}

    def walk(node, scope):
        for child in ast.iter_child_nodes(node):
            nxt = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if scope == "<module>":
                    nxt = child.name
            if isinstance(child, ast.Name) and child.id in out:
                out[child.id].add(scope)
            elif isinstance(child, ast.Attribute) and child.attr in out:
                out[child.attr].add(scope)
            walk(child, nxt)

    walk(tree, "<module>")
    return out


def _git(repo, *args, env=None):
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=120,
        env=env,
    )


def _tiny_repo(tmp_path):
    """A throwaway git repo holding one committed file, then: a MODIFIED tracked file,
    an UNTRACKED new file, and a STAGED new file."""
    repo = tmp_path / "gitrepo"
    repo.mkdir(parents=True, exist_ok=True)
    assert _git(repo, "init", "-q", "-b", "main").returncode == 0
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "tester")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "tracked.txt").write_text("original\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    assert _git(repo, "commit", "-q", "-m", "seed").returncode == 0
    (repo / "tracked.txt").write_text("edited\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("brand new\n", encoding="utf-8")
    (repo / "staged.txt").write_text("staged content\n", encoding="utf-8")
    _git(repo, "add", "staged.txt")
    return repo


# --------------------------------------------------------------------------
# behavior 1 -- writes the patch, returns the Path, bytes are the diff and nothing else
# --------------------------------------------------------------------------
def test_b1_writes_to_highest_iter_dir_and_returns_that_path(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-7", "iter-12")
    _seam(monkeypatch, DIFF)

    got = foundry.save_work_patch(cfg)

    want = state / "iter-12" / PATCH_NAME
    assert got == want, got
    assert want.exists()
    assert _files_under(state) == ["iter-12/" + PATCH_NAME]


def test_b1_written_bytes_are_the_seam_text_and_nothing_else(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-1")
    _seam(monkeypatch, DIFF)

    p = foundry.save_work_patch(cfg)

    assert p.read_bytes() == (DIFF + "\n").encode("utf-8")
    text = p.read_text(encoding="utf-8")
    assert text.startswith("diff --git ")
    # no banner, no timestamp, no reason string, no re-wrapping
    assert "save-work" not in text
    assert "ABORT" not in text.upper()
    assert text.count("\n") == DIFF.count("\n") + 1
    assert _files_under(state) == ["iter-1/" + PATCH_NAME]


@pytest.mark.parametrize(
    "raw",
    [DIFF, DIFF + "\n", DIFF + "\n\n", DIFF + "\n\n\n\n"],
)
def test_b1_trailing_newline_normalised_to_exactly_one(tmp_path, monkeypatch, raw):
    cfg = _cfg(tmp_path)
    _iters(cfg, "iter-3")
    _seam(monkeypatch, raw)

    p = foundry.save_work_patch(cfg)

    assert p is not None
    assert p.read_text(encoding="utf-8") == raw.rstrip("\n") + "\n"


def test_b1_patch_name_is_the_patchable_module_constant(tmp_path, monkeypatch):
    assert foundry.SAVE_WORK_PATCH_NAME == PATCH_NAME
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-5")
    _seam(monkeypatch, DIFF)
    monkeypatch.setattr(foundry, "SAVE_WORK_PATCH_NAME", "RESCUE.patch")

    p = foundry.save_work_patch(cfg)

    assert p.name == "RESCUE.patch"
    assert _files_under(state) == ["iter-5/RESCUE.patch"]


# --------------------------------------------------------------------------
# behavior 2 -- one seam, called by BARE module name, zero real subprocess
# --------------------------------------------------------------------------
def test_b2_seam_is_called_by_bare_name_with_the_cfg(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _iters(cfg, "iter-2")
    calls = _seam(monkeypatch, DIFF, calls=[])

    foundry.save_work_patch(cfg)

    assert len(calls) == 1, calls
    assert calls[0] is cfg


def test_b2_scripted_seam_means_zero_real_subprocess(tmp_path, monkeypatch):
    """Two-sided: with subprocess.run sabotaged the save STILL succeeds, which is only
    possible if the scripted seam displaced every real git call."""
    cfg = _cfg(tmp_path)
    _iters(cfg, "iter-4")
    _seam(monkeypatch, DIFF)

    def boom(*a, **k):
        raise AssertionError("save_work_patch ran a real subprocess")

    monkeypatch.setattr(foundry.subprocess, "run", boom)

    p = foundry.save_work_patch(cfg)

    assert p is not None and p.exists()


# --------------------------------------------------------------------------
# behavior 3 -- clean tree writes nothing and never clobbers an earlier rescue
# --------------------------------------------------------------------------
@pytest.mark.parametrize("blank", ["", "   ", "\n", "\n\n\n", "\t \n  \t"])
def test_b3_clean_tree_returns_none_and_writes_nothing(tmp_path, monkeypatch, blank):
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-8")
    _seam(monkeypatch, blank)

    assert foundry.save_work_patch(cfg) is None
    assert _files_under(state) == []


@pytest.mark.parametrize("blank", ["", "   ", "\n", "\t\n"])
def test_b3_earlier_rescue_survives_a_clean_tree_rerun(tmp_path, monkeypatch, blank):
    """AC: write a sentinel patch first, run against a clean-tree seam, assert the
    sentinel BYTES survive (not truncated, not deleted)."""
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-9")
    target = state / "iter-9" / PATCH_NAME
    sentinel = b"diff --git a/rescued b/rescued\n@@ -0,0 +1 @@\n+the work\n"
    target.write_bytes(sentinel)
    _seam(monkeypatch, blank)

    assert foundry.save_work_patch(cfg) is None
    assert target.exists()
    assert target.read_bytes() == sentinel


def test_b3_nonempty_diff_replaces_the_earlier_patch(tmp_path, monkeypatch):
    """The other half of the reading pinned in this module's docstring: behaviors 1 and
    8 promise a write and a SAVED exit, so no-clobber cannot be unconditional."""
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-9")
    target = state / "iter-9" / PATCH_NAME
    target.write_bytes(b"stale\n")
    _seam(monkeypatch, DIFF)

    p = foundry.save_work_patch(cfg)

    assert p == target
    assert target.read_text(encoding="utf-8") == DIFF + "\n"


# --------------------------------------------------------------------------
# behavior 4 -- highest-NUMBERED iter dir, via the iteration_numbers helper
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "names,winner",
    [
        (("iter-9", "iter-10"), "iter-10"),
        (("iter-99", "iter-151"), "iter-151"),
        (("iter-07", "iter-12"), "iter-12"),
        (("iter-2", "iter-0"), "iter-2"),
    ],
)
def test_b4_selection_is_numeric_not_lexical(tmp_path, monkeypatch, names, winner):
    cfg = _cfg(tmp_path)
    state = _iters(cfg, *names)
    _seam(monkeypatch, DIFF)

    p = foundry.save_work_patch(cfg)

    assert p == state / winner / PATCH_NAME
    assert _files_under(state) == [winner + "/" + PATCH_NAME]


def test_b4_non_matching_names_and_plain_files_are_ignored(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-3", "iter-x", "iterations", "iter-")
    (state / "iter-99").write_text("a FILE, not a dir\n", encoding="utf-8")
    (state / "notes.md").write_text("x\n", encoding="utf-8")
    _seam(monkeypatch, DIFF)

    p = foundry.save_work_patch(cfg)

    assert p == state / "iter-3" / PATCH_NAME
    assert (state / "iter-99").read_text(encoding="utf-8") == "a FILE, not a dir\n"


def test_b4_goes_through_the_iteration_numbers_helper(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _iters(cfg, "iter-1", "iter-6")
    _seam(monkeypatch, DIFF)
    real = foundry.iteration_numbers
    seen = []

    def spy(names):
        seen.append(list(names))
        return real(names)

    monkeypatch.setattr(foundry, "iteration_numbers", spy)

    p = foundry.save_work_patch(cfg)

    assert p is not None and p.parent.name == "iter-6"
    assert seen, "iteration_numbers was not consulted"


@pytest.mark.parametrize("kind", ["absent", "is_a_file", "empty", "no_iter_child"])
def test_b4_unusable_state_root_yields_none_and_writes_nothing(
    tmp_path, monkeypatch, kind
):
    cfg = _cfg(tmp_path)
    state = pathlib.Path(cfg.state)
    # MEASURED: load_config CREATES cfg.state eagerly, so the "missing" and
    # "not a directory" cases only exist after removing what it made.
    if state.exists():
        shutil.rmtree(state)
    if kind == "is_a_file":
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text("not a dir\n", encoding="utf-8")
    elif kind == "empty":
        state.mkdir(parents=True, exist_ok=True)
    elif kind == "no_iter_child":
        (state / "iter-x").mkdir(parents=True, exist_ok=True)
    _seam(monkeypatch, DIFF)

    assert foundry.save_work_patch(cfg) is None
    if kind == "absent":
        assert not state.exists(), "a missing state root must not be created"
    elif kind == "is_a_file":
        assert state.read_text(encoding="utf-8") == "not a dir\n"
    else:
        assert _files_under(state) == []


# --------------------------------------------------------------------------
# behavior 5 -- TOTAL by construction
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "exc",
    [RuntimeError("seam raised on purpose"), OSError("nope"), ValueError("bad bytes")],
)
def test_b5_a_raising_seam_yields_none_not_an_exception(tmp_path, monkeypatch, exc):
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-11")
    _seam(monkeypatch, exc)

    assert foundry.save_work_patch(cfg) is None
    assert _files_under(state) == []


def test_b5_a_directory_occupying_the_patch_path_yields_none(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-13")
    blocker = state / "iter-13" / PATCH_NAME
    blocker.mkdir(parents=True)
    _seam(monkeypatch, DIFF)

    assert foundry.save_work_patch(cfg) is None
    assert blocker.is_dir(), "the blocking directory must survive untouched"


def test_b5_a_read_only_target_dir_yields_none(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-14")
    target_dir = state / "iter-14"
    _seam(monkeypatch, DIFF)
    target_dir.chmod(0o500)
    try:
        assert foundry.save_work_patch(cfg) is None
    finally:
        target_dir.chmod(0o700)
    assert _files_under(state) == []


# --------------------------------------------------------------------------
# behavior 6 -- the ONE real-git test: never mutates the real index, stdout only
# --------------------------------------------------------------------------
def test_b6_worktree_patch_text_is_index_safe_and_covers_all_three_file_kinds(tmp_path):
    repo = _tiny_repo(tmp_path)
    cfg = _cfg(tmp_path, repo=str(repo))
    index = repo / ".git" / "index"
    before_index = hashlib.sha256(index.read_bytes()).hexdigest()
    before_status = _git(repo, "status", "--porcelain").stdout

    patch = foundry.worktree_patch_text(cfg)

    # positive control -- the comparison below is vacuous unless the patch is real
    assert patch.strip(), "empty patch: the index-safety comparison would be vacuous"
    assert "diff --git" in patch
    for name in ("tracked.txt", "untracked.txt", "staged.txt"):
        assert name in patch, "missing %s in patch:\n%s" % (name, patch)
    # stdout ONLY -- every line of a unified diff carries a diff prefix char
    for line in patch.splitlines():
        assert line[:1] in ("d", "i", "-", "+", "@", " ", "n", "\\", ""), line

    # two-sided index safety
    assert hashlib.sha256(index.read_bytes()).hexdigest() == before_index
    assert _git(repo, "status", "--porcelain").stdout == before_status
    assert "staged.txt" in before_status


def test_b6_patch_round_trips_through_the_destruction_it_exists_to_survive(tmp_path):
    repo = _tiny_repo(tmp_path)
    cfg = _cfg(tmp_path, repo=str(repo))
    patch_file = tmp_path / "rescue.patch"

    text = foundry.worktree_patch_text(cfg)
    patch_file.write_text(text.rstrip("\n") + "\n", encoding="utf-8")

    assert _git(repo, "reset", "--hard", "-q", "HEAD").returncode == 0
    assert _git(repo, "clean", "-fdq").returncode == 0
    assert not (repo / "untracked.txt").exists()
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "original\n"

    assert _git(repo, "apply", "--check", str(patch_file)).returncode == 0
    assert _git(repo, "apply", str(patch_file)).returncode == 0
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "edited\n"
    assert (repo / "untracked.txt").read_text(encoding="utf-8") == "brand new\n"
    assert (repo / "staged.txt").read_text(encoding="utf-8") == "staged content\n"


def _non_utf8_repo(tmp_path):
    """A real repo holding a byte that is invalid UTF-8 but carries NO NUL, so git
    classifies the file as TEXT and emits the raw byte in the diff. This is the input
    the seam's documented failure list (unlocatable index / non-zero exit / timeout /
    OS error) does NOT name."""
    repo = _tiny_repo(tmp_path)
    (repo / "latin.txt").write_bytes(b"caf\xe9 not utf8\n")
    cfg = _cfg(tmp_path, repo=str(repo))
    _iters(cfg, "iter-50")
    return cfg


def test_b6_non_utf8_working_tree_yields_a_string_not_an_exception(tmp_path):
    """Behavior 6: "Every subprocess call carries a timeout and a failure yields ''".
    A raise is not ''."""
    cfg = _non_utf8_repo(tmp_path)

    text = foundry.worktree_patch_text(cfg)

    assert isinstance(text, str)


def test_b5_non_utf8_working_tree_keeps_save_work_patch_total(tmp_path):
    """Behavior 5: any failure yields None rather than propagating an exception."""
    cfg = _non_utf8_repo(tmp_path)

    got = foundry.save_work_patch(cfg)

    assert got is None or got.exists()


def test_b8_non_utf8_working_tree_keeps_the_cli_decidable(tmp_path, capsys):
    """Behavior 8: the CLI always prints one 'save-work: ' line and returns 0/2/1."""
    cfg = _non_utf8_repo(tmp_path)

    rc = foundry.save_work_cli(cfg)

    line = _one_line(capsys)
    assert line.startswith("save-work: "), line
    assert rc in (0, 1, 2), rc
    # A dirty tree must never be reported as matching HEAD -- that is a WRONG METER,
    # and it is what merely widening the seam's except clause would produce.
    assert "NOTHING" not in line, line


def test_b1_non_utf8_patch_is_byte_exact_and_git_apply_restores_it(tmp_path):
    """Behaviors 1 + 6 PAIRED, through the CONSUMER: behavior 1 pins the written bytes as
    the diff "and NOTHING else -- ... so git apply takes the file unmodified", and
    behavior 6 pins "returns the diff's STDOUT ONLY".

    A dirty tree holding a byte that is invalid UTF-8 but NUL-free (git therefore treats
    the file as TEXT and emits the raw byte) is the case where a LOSSY decode is
    invisible to every other test in this file: the patch stays non-empty, the CLI still
    prints SAVED and still exits 0, yet each mangled byte becomes U+FFFD and git apply
    either refuses the patch or restores the wrong bytes. Only a round trip through
    git apply, after the reset+clean the rescue exists to survive, decides it.
    """
    cfg = _non_utf8_repo(tmp_path)
    repo = pathlib.Path(cfg.repo)
    # ALSO edit a TRACKED file to non-ASCII, so a mangled byte would have to survive a
    # real hunk body, not only a new-file blob.
    (repo / "tracked.txt").write_bytes(b"edited caf\xe9\n")
    latin_before = (repo / "latin.txt").read_bytes()
    tracked_before = (repo / "tracked.txt").read_bytes()

    index = repo / ".git" / "index"
    before_index = hashlib.sha256(index.read_bytes()).hexdigest()
    before_status = _git(repo, "status", "--porcelain").stdout

    got = foundry.save_work_patch(cfg)

    # behavior 6 again: the non-ASCII path must not have cost the index guarantee
    assert hashlib.sha256(index.read_bytes()).hexdigest() == before_index
    assert _git(repo, "status", "--porcelain").stdout == before_status
    assert got is not None, "nothing was saved for a DIRTY non-UTF-8 working tree"
    raw = got.read_bytes()
    assert b"\xe9" in raw, "the invalid byte did not survive: %r" % raw[:200]
    assert b"\xef\xbf\xbd" not in raw, "lossy decode -- U+FFFD landed in the patch"

    # the destruction the patch exists to survive
    assert _git(repo, "reset", "--hard", "-q", "HEAD").returncode == 0
    assert _git(repo, "clean", "-fdq").returncode == 0
    assert not (repo / "latin.txt").exists()
    assert got.exists(), "the patch must live outside the repo tree"

    chk = _git(repo, "apply", "--check", str(got))
    assert chk.returncode == 0, "git apply --check rejected the patch: %s" % chk.stderr
    assert _git(repo, "apply", str(got)).returncode == 0
    assert (repo / "latin.txt").read_bytes() == latin_before
    assert (repo / "tracked.txt").read_bytes() == tracked_before
    assert (repo / "untracked.txt").read_bytes() == b"brand new\n"
    assert (repo / "staged.txt").read_bytes() == b"staged content\n"


def test_b8_non_utf8_saved_line_reports_the_real_byte_count(tmp_path, capsys):
    """Behavior 8: the SAVED line reports "<N> bytes", so N must be the file's byte
    length even when the diff is not pure ASCII (a character count would be a wrong
    meter). Behavior 8 also forbids reporting a DIRTY tree as matching HEAD, so the
    exit code here is 0, not 2."""
    cfg = _non_utf8_repo(tmp_path)

    rc = foundry.save_work_cli(cfg)

    line = _one_line(capsys)
    target = pathlib.Path(cfg.state) / "iter-50" / PATCH_NAME
    assert rc == 0, line
    assert target.exists(), line
    n = len(target.read_bytes())
    assert line == "save-work: SAVED -- %d bytes to %s (git apply it to restore)" % (
        n,
        target,
    )


@pytest.mark.parametrize("kind", ["not_a_repo", "missing_repo"])
def test_b6_unlocatable_index_returns_empty_string(tmp_path, kind):
    if kind == "not_a_repo":
        repo = tmp_path / "plain"
        repo.mkdir()
        (repo / "f.txt").write_text("x\n", encoding="utf-8")
    else:
        repo = tmp_path / "does-not-exist"
    cfg = _cfg(tmp_path, repo=str(repo))

    assert foundry.worktree_patch_text(cfg) == ""


# --------------------------------------------------------------------------
# behavior 7 -- dormant: no new call site on the control path
# --------------------------------------------------------------------------
def test_b7_control_path_functions_do_not_reference_the_new_names():
    refs = _refs_by_scope(_ROOT / "foundry.py", NEW_NAMES + ("capture_abort_patch",))

    # SCAN-VALIDITY CONTROLS -- without these a green blacklist below could mean
    # "clean" or "the matcher is broken", and those are not the same result.
    assert sorted(refs["capture_abort_patch"]) == ["revert_repo"], refs
    assert "main" in refs["save_work_cli"], refs["save_work_cli"]
    assert refs["worktree_patch_text"], "the single git seam is called nowhere"

    for name in NEW_NAMES:
        collisions = sorted(refs[name] & set(CONTROL_PATH))
        assert collisions == [], "%s referenced on the control path: %s" % (
            name,
            collisions,
        )


def test_b7_only_main_and_the_features_own_call_tree_reference_the_new_names():
    """Behavior 7's positive half: referenced ONLY by main's argparse dispatch (plus
    the feature's own functions), never by anything else in the module."""
    refs = _refs_by_scope(_ROOT / "foundry.py", NEW_NAMES)
    scopes = set()
    for name in NEW_NAMES:
        scopes |= refs[name]
    outside = sorted(
        s
        for s in scopes
        if s != "main"
        and not s.startswith("save_work")
        and s != "worktree_patch_text"
    )
    assert outside == [], "unexpected referencing scopes: %s" % outside


def test_b7_dispatcher_never_references_the_new_names():
    refs = _refs_by_scope(_ROOT / "dispatcher.py", NEW_NAMES)
    assert {k: sorted(v) for k, v in refs.items()} == {n: [] for n in NEW_NAMES}


def test_b7_capture_abort_patch_gains_no_second_caller():
    refs = _refs_by_scope(_ROOT / "foundry.py", ("capture_abort_patch",))
    assert sorted(refs["capture_abort_patch"]) == ["revert_repo"], refs


# --------------------------------------------------------------------------
# behavior 8 -- the CLI prints exactly one line and exits decidably
# --------------------------------------------------------------------------
def test_b8_saved_branch_exits_0_with_the_pinned_line(tmp_path, monkeypatch, capsys):
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-20")
    _seam(monkeypatch, DIFF)

    rc = foundry.save_work_cli(cfg)

    target = state / "iter-20" / PATCH_NAME
    n = len(target.read_bytes())
    line = _one_line(capsys)
    assert rc == 0
    assert line.startswith("save-work: ")
    assert line == "save-work: SAVED -- %d bytes to %s (git apply it to restore)" % (
        n,
        target,
    )


def test_b8_nothing_branch_exits_2_with_the_pinned_line(tmp_path, monkeypatch, capsys):
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-21")
    _seam(monkeypatch, "")

    rc = foundry.save_work_cli(cfg)

    line = _one_line(capsys)
    assert rc == 2
    assert line == "save-work: NOTHING -- working tree matches HEAD, no patch written"
    assert _files_under(state) == []


def test_b8_no_iter_dir_is_a_failure_not_a_clean_tree(tmp_path, monkeypatch, capsys):
    """Unambiguous FAILED case: work EXISTS but there is nowhere to put it."""
    cfg = _cfg(tmp_path)
    pathlib.Path(cfg.state).mkdir(parents=True, exist_ok=True)
    _seam(monkeypatch, DIFF)

    rc = foundry.save_work_cli(cfg)

    line = _one_line(capsys)
    assert rc == 1
    assert line.startswith("save-work: FAILED -- "), line
    assert len(line) > len("save-work: FAILED -- "), "the line must name WHY"


def test_b8_unwritable_target_exits_1(tmp_path, monkeypatch, capsys):
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-22")
    blocker = state / "iter-22" / PATCH_NAME
    blocker.mkdir(parents=True)
    _seam(monkeypatch, DIFF)

    rc = foundry.save_work_cli(cfg)

    line = _one_line(capsys)
    assert rc == 1
    assert line.startswith("save-work: FAILED -- "), line


@pytest.mark.parametrize(
    "text,dirs,want_rc",
    [(DIFF, ("iter-30",), 0), ("", ("iter-30",), 2), (DIFF, (), 1)],
)
def test_b8_every_branch_prints_exactly_one_prefixed_line(
    tmp_path, monkeypatch, capsys, text, dirs, want_rc
):
    cfg = _cfg(tmp_path)
    pathlib.Path(cfg.state).mkdir(parents=True, exist_ok=True)
    if dirs:
        _iters(cfg, *dirs)
    _seam(monkeypatch, text)

    rc = foundry.save_work_cli(cfg)

    line = _one_line(capsys)
    assert rc == want_rc
    assert line.startswith("save-work: ")
    assert isinstance(rc, int)


def test_b8_verb_is_dispatched_after_load_config_end_to_end(tmp_path):
    """Real argparse dispatch in a fresh interpreter: a config-taking verb, like
    doctor. The repo is a plain dir, so the real seam finds no index -> NOTHING(2)."""
    cfg = _cfg(tmp_path)
    _iters(cfg, "iter-40")
    cfg_path = sorted(pathlib.Path(tmp_path).glob("cfg_*.json"))[-1]

    r = subprocess.run(
        [sys.executable, str(_ROOT / "foundry.py"), "save-work", "--config",
         str(cfg_path)],
        capture_output=True, text=True, timeout=180, cwd=str(tmp_path),
    )

    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, r.stdout + r.stderr
    assert lines[0].startswith("save-work: "), lines[0]
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)


def test_b8_save_work_requires_a_config():
    r = subprocess.run(
        [sys.executable, str(_ROOT / "foundry.py"), "save-work"],
        capture_output=True, text=True, timeout=180,
    )
    assert r.returncode != 0
    assert "--config" in (r.stdout + r.stderr)


def test_b8_cli_shares_one_target_rule_with_the_function(tmp_path, monkeypatch, capsys):
    """The CLI and save_work_patch are independent compositions of the same seam, so
    pin the shared target rule: rename the patchable constant and the CLI must follow."""
    cfg = _cfg(tmp_path)
    state = _iters(cfg, "iter-23")
    _seam(monkeypatch, DIFF)
    monkeypatch.setattr(foundry, "SAVE_WORK_PATCH_NAME", "RESCUE.patch")

    rc = foundry.save_work_cli(cfg)

    line = _one_line(capsys)
    assert rc == 0
    assert "RESCUE.patch" in line, line
    assert _files_under(state) == ["iter-23/RESCUE.patch"]


@pytest.mark.parametrize(
    "text,dirs", [(DIFF, ("iter-30",)), ("", ("iter-30",)), (DIFF, ())]
)
def test_b8_cli_exit_code_agrees_with_the_function_verdict(
    tmp_path, monkeypatch, capsys, text, dirs
):
    """Two entry points must never disagree about the same tree: rc == 0 exactly when
    save_work_patch returns a Path, on twin fixtures."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    ca = _cfg(tmp_path / "a")
    cb = _cfg(tmp_path / "b")
    for c in (ca, cb):
        pathlib.Path(c.state).mkdir(parents=True, exist_ok=True)
        if dirs:
            _iters(c, *dirs)
    _seam(monkeypatch, text)

    got = foundry.save_work_patch(ca)
    rc = foundry.save_work_cli(cb)

    _one_line(capsys)
    assert (got is not None) == (rc == 0), (got, rc)
    if got is not None:
        rel = got.relative_to(pathlib.Path(ca.state))
        assert (pathlib.Path(cb.state) / rel).exists(), rel


@pytest.mark.parametrize("text,want_rc", [(DIFF, 0), ("", 2)])
def test_b8_cli_observes_the_working_tree_exactly_once(
    tmp_path, monkeypatch, capsys, text, want_rc
):
    """DERIVED invariant, not a spec literal: a second observation of the same tree
    could disagree with the first and make the exit code a wrong meter."""
    cfg = _cfg(tmp_path)
    _iters(cfg, "iter-31")
    calls = _seam(monkeypatch, text, calls=[])

    rc = foundry.save_work_cli(cfg)

    _one_line(capsys)
    assert rc == want_rc
    assert len(calls) == 1, "the seam ran %d times" % len(calls)


# --------------------------------------------------------------------------
# behavior 9 -- README documents the verb
# --------------------------------------------------------------------------
def test_b9_readme_index_is_contiguous_and_46_names_save_work():
    text = README.read_text(encoding="utf-8")
    nums = [int(m.group(1)) for m in re.finditer(r"(?m)^# (\d+)\.", text)]
    assert nums, "no numbered command index found in README.md"
    assert len(nums) == len(set(nums)), "duplicate index numbers: %s" % nums
    assert sorted(nums) == list(range(0, max(nums) + 1)), "index has gaps: %s" % nums
    # RELAXED iter 164: a `== max` pin forbids the README growth the ship gate
    # mandates for every new documented surface (iter 164 added `# 47.`). The
    # intent -- contiguous, no duplicates, and 46 still names save-work -- holds.
    assert max(nums) >= 46, "index no longer reaches 46, got %d" % max(nums)

    entry = [ln for ln in text.splitlines() if ln.startswith("# 46.")]
    assert len(entry) == 1, entry
    assert "save-work" in entry[0], entry[0]


def test_ac_state_dir_is_already_gitignored_so_no_new_entry_is_needed():
    """AC: no new gitignore entry is needed and none is added. This is the same fact
    that makes the rescue survive the abort path's "git clean -fd" (no -x).
    Reads only the TRACKED .gitignore -- never the ambient untracked tree."""
    lines = [
        ln.strip()
        for ln in (_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        ln.rstrip("/") == "products/*/state" for ln in lines
    ), "no products/*/state ignore rule: the patch would leak into the ship diff"


# --------------------------------------------------------------------------
# acceptance criterion -- both modules still import in a clean interpreter
# --------------------------------------------------------------------------
def test_ac_foundry_and_dispatcher_import_cleanly():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher; print('ok')"],
        capture_output=True, text=True, timeout=180, cwd=str(_ROOT),
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ok" in r.stdout
