"""Black-box behaviour tests for iter 51 -- item 16 BITE 2b: a portable
one-command pre-push hook installer (``scripts/install_hooks.sh``) that arms the
committed leak-guard as a git ``pre-push`` hook, plus README/ARCHITECTURE docs.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-51 PM
spec's Expected Behaviors (1-8) + Acceptance Criteria, the product
README/ARCHITECTURE/roadmap docs, the ``tests/`` conventions (esp.
tests/test_iter50_behavior.py for the leak_guard module-loading style and
tests/test_iter03_behavior.py for the real-local-git subprocess-harness style),
and the product's OWN OBSERVABLE behaviour by RUNNING it -- installing the hook
in throwaway temp repos, inspecting the hook FILE the installer PRODUCES, and
driving the armed hook + ``leak_guard`` public interface. The implementation
SOURCE of ``scripts/install_hooks.sh`` / ``scripts/leak_guard.py`` /
``foundry.py`` / ``dispatcher.py`` (as logic to mirror), the engineer's and
reviewer's notes, and the CONTENT of ``git diff`` were NOT read for their logic.
Two allowed exceptions, both "running the product on data", not reading-as-logic:
(a) Behavior 8 feeds the installer's RAW TEXT to ``leak_guard.scan_text`` as
scanner INPUT for the public-safety self-scan -- this is running the scanner, not
mirroring the installer's shell; (b) the byte-unchanged AC check uses
``git diff --quiet`` which emits NO diff text (exit-code-only assertion).

Fully offline & deterministic: all git is LOCAL (``git init``/``commit`` in temp
repos, no network/clone); env pins ``GIT_CONFIG_GLOBAL``/``GIT_CONFIG_SYSTEM`` to
/dev/null so no user config (e.g. ``core.hooksPath``) perturbs the result. Every
NEEDLE used to exercise MATCHING is SYNTHETIC (``WIDGET``); the home-path
liveness probe is BUILT AT RUNTIME by concatenation so the literal contiguous
string never appears in this PUBLIC source; a meta self-scan proves this test
file itself scans clean against the COMMITTED denylist, so it cannot trip the
ship-gate's own leak scan on push.
"""
import importlib.util
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_THIS = pathlib.Path(__file__).resolve()
_REAL_LEAK_GUARD = _ROOT / "scripts" / "leak_guard.py"
_REAL_INSTALLER = _ROOT / "scripts" / "install_hooks.sh"
_REAL_DENYLIST = _ROOT / "scripts" / "leak_denylist.txt"
_README = _ROOT / "README.md"
_ARCH = _ROOT / "ARCHITECTURE.md"

# The spec names the foundry marker as e.g. "installed by agent-foundry"; the
# load-bearing, phrasing-robust substring is the product name itself.
MARKER = "agent-foundry"
# Token-aware SYNTHETIC needle (non-letter boundaries) -- never a real token.
WIDGET_PATTERN = r"(?<![A-Za-z])WIDGET(?![A-Za-z])"
ZEROS = "0" * 40
# Home-path prefix built at RUNTIME so the contiguous literal never appears
# in this PUBLIC source (it is itself a committed denylist needle).
HOME_PREFIX = "/" + "Users" + "/"


def _load_leak_guard():
    """Load the committed scanner from its repo path (spec-endorsed; no conftest).
    Register in sys.modules BEFORE exec so its frozen dataclass resolves."""
    spec = importlib.util.spec_from_file_location("leak_guard", _REAL_LEAK_GUARD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["leak_guard"] = mod
    spec.loader.exec_module(mod)
    return mod


lg = _load_leak_guard()


def _git_env(**extra):
    """Preserve PATH (so the armed hook's `python3` resolves) but isolate git
    from any user global/system config that could redirect hooks or identity."""
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_AUTHOR_NAME"] = "t"
    env["GIT_AUTHOR_EMAIL"] = "t@e.x"
    env["GIT_COMMITTER_NAME"] = "t"
    env["GIT_COMMITTER_EMAIL"] = "t@e.x"
    env.update(extra)
    return env


def _run(args, cwd, env=None, stdin=None):
    return subprocess.run(
        [str(a) for a in args], cwd=str(cwd), env=env, input=stdin,
        capture_output=True, text=True,
    )


def _git(args, cwd, env):
    r = _run(["git", *args], cwd, env)
    assert r.returncode == 0, f"git {args} failed rc={r.returncode}: {r.stderr}"
    return r.stdout


def _synthetic_denylist_text(*patterns):
    """A `#`-comment header + one base64 `encode_pattern(...)` line per pattern."""
    lines = ["# synthetic denylist (test-only)"]
    lines += [lg.encode_pattern(p) for p in patterns]
    return "\n".join(lines) + "\n"


def _mk_repo(tmp_path, name, *, denylist_text, extra_files=None):
    """A throwaway git repo whose scripts/ holds COPIES of the real guard +
    installer + a (usually synthetic) denylist; returns (repo, head_sha, env)."""
    repo = tmp_path / name
    repo.mkdir()
    env = _git_env()
    _git(["init", "-q"], repo, env)
    scripts = repo / "scripts"
    scripts.mkdir()
    shutil.copy(_REAL_LEAK_GUARD, scripts / "leak_guard.py")
    shutil.copy(_REAL_INSTALLER, scripts / "install_hooks.sh")
    (scripts / "leak_denylist.txt").write_text(denylist_text)
    for rel, content in (extra_files or {}).items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    _git(["add", "-A"], repo, env)
    _git(["commit", "-q", "-m", "init"], repo, env)
    head = _git(["rev-parse", "HEAD"], repo, env).strip()
    return repo, head, env


def _install(repo, env):
    return _run(["sh", "scripts/install_hooks.sh"], repo, env)


def _hook(repo):
    return repo / ".git" / "hooks" / "pre-push"


def _backup(repo):
    return repo / ".git" / "hooks" / "pre-push.backup"


def _invoke_hook(repo, env, stdin_line):
    return _run(["sh", str(_hook(repo))], repo, env, stdin=stdin_line)


def _is_owner_exec(path):
    return bool(path.stat().st_mode & stat.S_IXUSR)


# --------------------------------------------------------------------------
# Behavior 1 -- Fresh install (no existing hook)
# --------------------------------------------------------------------------
def test_b1_fresh_install_creates_armed_hook(tmp_path):
    repo, _head, env = _mk_repo(
        tmp_path, "b1", denylist_text=_synthetic_denylist_text(WIDGET_PATTERN))
    assert not _hook(repo).exists()

    r = _install(repo, env)
    assert r.returncode == 0, f"installer rc={r.returncode}: {r.stderr}"
    assert "pre-push" in r.stdout, f"stdout lacked 'pre-push': {r.stdout!r}"

    hook = _hook(repo)
    assert hook.is_file()
    assert _is_owner_exec(hook), "hook is not owner-executable"
    text = hook.read_text()
    assert text.startswith("#!/bin/sh"), f"hook shebang wrong: {text[:40]!r}"
    assert MARKER in text, "hook lacks the foundry marker substring"
    assert "leak_guard.py" in text, "hook does not reference leak_guard.py"


# --------------------------------------------------------------------------
# Behavior 2 -- Idempotent re-run (no spurious backup for our own hook)
# --------------------------------------------------------------------------
def test_b2_idempotent_rerun_no_backup(tmp_path):
    repo, _head, env = _mk_repo(
        tmp_path, "b2", denylist_text=_synthetic_denylist_text(WIDGET_PATTERN))
    assert _install(repo, env).returncode == 0
    r2 = _install(repo, env)
    assert r2.returncode == 0, f"second install rc={r2.returncode}: {r2.stderr}"

    hook = _hook(repo)
    assert hook.is_file()
    assert _is_owner_exec(hook)
    text = hook.read_text()
    assert MARKER in text and "leak_guard.py" in text
    assert not _backup(repo).exists(), (
        "re-installing over our OWN marked hook must NOT create a backup")


# --------------------------------------------------------------------------
# Behavior 3 -- Foreign hook preserved (backed up, then not clobbered)
# --------------------------------------------------------------------------
def test_b3_foreign_hook_backed_up_then_preserved(tmp_path):
    repo, _head, env = _mk_repo(
        tmp_path, "b3", denylist_text=_synthetic_denylist_text(WIDGET_PATTERN))
    foreign = "#!/bin/sh\necho operator custom hook\nexit 0\n"
    hook = _hook(repo)
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_bytes(foreign.encode())
    hook.chmod(0o755)
    foreign_bytes = hook.read_bytes()
    assert MARKER not in foreign  # a genuinely foreign hook

    r = _install(repo, env)
    assert r.returncode == 0, f"installer rc={r.returncode}: {r.stderr}"
    bak = _backup(repo)
    assert bak.exists(), "foreign hook was not backed up"
    assert bak.read_bytes() == foreign_bytes, "backup is not byte-identical"
    assert MARKER in hook.read_text(), "pre-push is not the foundry hook now"

    # Running AGAIN (now over our marked hook) preserves the first backup.
    r2 = _install(repo, env)
    assert r2.returncode == 0
    assert bak.read_bytes() == foreign_bytes, (
        "re-run overwrote the preserved foreign backup")


def test_b3_extra_later_foreign_hook_does_not_clobber_first_backup(tmp_path):
    """Hardening (slightly beyond the literal spec 'AGAIN'): a SECOND foreign
    hook appearing after the first install must not clobber the first backup --
    exercises the '[ ! -e backup ]' guard directly, upholding the spec's
    'the first foreign hook is preserved' guarantee."""
    repo, _head, env = _mk_repo(
        tmp_path, "b3x", denylist_text=_synthetic_denylist_text(WIDGET_PATTERN))
    hook = _hook(repo)
    hook.parent.mkdir(parents=True, exist_ok=True)
    first = b"#!/bin/sh\necho FIRST foreign\n"
    hook.write_bytes(first)
    hook.chmod(0o755)
    assert _install(repo, env).returncode == 0
    assert _backup(repo).read_bytes() == first

    # Operator drops a DIFFERENT foreign hook, then re-installs.
    second = b"#!/bin/sh\necho SECOND foreign\n"
    hook.write_bytes(second)
    hook.chmod(0o755)
    assert _install(repo, env).returncode == 0
    assert _backup(repo).read_bytes() == first, (
        "a later foreign hook clobbered the preserved first backup")


# --------------------------------------------------------------------------
# Behavior 4 -- Not a git repository
# --------------------------------------------------------------------------
def test_b4_not_a_git_repo_fails_and_writes_nothing(tmp_path):
    installer_dir = tmp_path / "installer"
    installer_dir.mkdir()
    shutil.copy(_REAL_INSTALLER, installer_dir / "install_hooks.sh")
    nonrepo = tmp_path / "nonrepo"
    nonrepo.mkdir()
    # Ceiling = the non-repo dir's parent so no ANCESTOR repo is discovered.
    env = _git_env(GIT_CEILING_DIRECTORIES=str(tmp_path))

    r = _run(["sh", str(installer_dir / "install_hooks.sh")], nonrepo, env)
    assert r.returncode != 0, "installer should fail outside any git repo"
    assert r.stderr.strip(), "expected an explanatory STDERR message"
    assert not (nonrepo / "pre-push").exists()
    assert not (nonrepo / ".git").exists()


# --------------------------------------------------------------------------
# Behavior 5 -- Armed hook ALLOWS a clean push
# --------------------------------------------------------------------------
def test_b5_armed_hook_allows_clean_push(tmp_path):
    repo, head, env = _mk_repo(
        tmp_path, "b5",
        denylist_text=_synthetic_denylist_text(WIDGET_PATTERN),
        extra_files={"readme.txt": "hello world, nothing to see here\n"})
    assert _install(repo, env).returncode == 0
    line = f"refs/heads/main {head} refs/heads/main {ZEROS}\n"
    r = _invoke_hook(repo, env, line)
    assert r.returncode == 0, (
        f"clean push blocked rc={r.returncode}\nOUT:{r.stdout}\nERR:{r.stderr}")


# --------------------------------------------------------------------------
# Behavior 6 -- Armed hook BLOCKS a leaky push
# --------------------------------------------------------------------------
def test_b6_armed_hook_blocks_leaky_push(tmp_path):
    repo, head, env = _mk_repo(
        tmp_path, "b6",
        denylist_text=_synthetic_denylist_text(WIDGET_PATTERN),
        extra_files={"leak.txt": "config token WIDGET should be caught\n"})
    assert _install(repo, env).returncode == 0
    line = f"refs/heads/main {head} refs/heads/main {ZEROS}\n"
    r = _invoke_hook(repo, env, line)
    assert r.returncode != 0, "leaky push was NOT blocked"
    combined = r.stdout + r.stderr
    assert re.search(r"leak\.txt:\d+", combined), (
        f"offending file:line for leak.txt not in output:\n{combined}")


# --------------------------------------------------------------------------
# Behavior 7 -- Branch-deletion line skipped
# --------------------------------------------------------------------------
def test_b7_branch_deletion_line_skipped(tmp_path):
    # Same leaky repo as B6, but the pushed local sha is all zeros (deletion).
    repo, _head, env = _mk_repo(
        tmp_path, "b7",
        denylist_text=_synthetic_denylist_text(WIDGET_PATTERN),
        extra_files={"leak.txt": "config token WIDGET should be caught\n"})
    assert _install(repo, env).returncode == 0
    line = f"refs/heads/main {ZEROS} refs/heads/main {ZEROS}\n"
    r = _invoke_hook(repo, env, line)
    assert r.returncode == 0, (
        f"a deletion (all-zeros localsha) line must scan nothing and exit 0; "
        f"rc={r.returncode}\nOUT:{r.stdout}\nERR:{r.stderr}")


# --------------------------------------------------------------------------
# Behavior 8 -- Public-safety + docs
# --------------------------------------------------------------------------
def _committed_patterns():
    return lg.load_denylist(_REAL_DENYLIST.read_text())


def test_b8_installer_scans_clean_against_committed_denylist():
    patterns = _committed_patterns()
    findings = lg.scan_text(_REAL_INSTALLER.read_text(), patterns)
    assert len(findings) == 0, (
        f"install_hooks.sh leaks against committed denylist: {findings}")
    # No absolute home path in the installer.
    assert HOME_PREFIX not in _REAL_INSTALLER.read_text()


def test_b8_committed_denylist_is_a_live_matcher():
    """A clean self-scan is only meaningful if the denylist actually matches.
    Build the probe at RUNTIME so the literal string never appears in source."""
    patterns = _committed_patterns()
    probe = HOME_PREFIX + "somebody/x"  # runtime-built; matches home-path needle
    assert len(lg.scan_text(probe, patterns)) >= 1, (
        "committed denylist matched nothing -- the clean self-scan is not "
        "genuine (inert patterns)")


def test_b8_docs_mention_installer_and_bite3_remaining():
    readme = _README.read_text()
    arch = _ARCH.read_text()
    assert "install_hooks.sh" in readme, "README lacks install_hooks.sh"
    assert "install_hooks.sh" in arch, "ARCHITECTURE lacks install_hooks.sh"
    # Must NOT claim the in-loop final-gate step is wired; it is bite 3.
    assert ("bite 3" in arch.lower()) or ("not yet wired" in arch.lower()), (
        "ARCHITECTURE must mark the in-loop final-gate check as bite 3 / not "
        "yet wired")


def test_b8_meta_this_test_file_is_ship_clean():
    """This PUBLIC test file must itself pass the ship-gate leak scan."""
    patterns = _committed_patterns()
    text = _THIS.read_text()
    assert len(lg.scan_text(text, patterns)) == 0, (
        "this test file would trip the ship-gate leak scan")
    assert HOME_PREFIX not in text  # no absolute home path literal


# --------------------------------------------------------------------------
# Acceptance-criteria invariants (resume-safety; NOT numbered behaviors)
# --------------------------------------------------------------------------
def test_ac_guard_and_control_path_byte_unchanged():
    """`git diff --quiet` emits NO diff text -- exit-code-only assertion of the
    byte-unchanged invariant (honors the isolation contract)."""
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--",
         "scripts/leak_guard.py", "scripts/leak_denylist.txt",
         "foundry.py", "dispatcher.py", "roles/"],
        cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, (
        "guard/control-path files are NOT byte-unchanged from HEAD")


def test_ac_foundry_and_dispatcher_still_import():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, f"import failed: {r.stderr}"
