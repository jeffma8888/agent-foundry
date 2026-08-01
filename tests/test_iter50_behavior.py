"""Black-box behaviour tests for iter 50 -- item 16 BITE 2: make the committed,
portable leak-guard (`scripts/leak_guard.py`, shipped DORMANT in iter 49)
RUNNABLE via a `main()` CLI + a single `run_git` git-tree scan seam.

The new public surface: `main(argv=None) -> int`, the single I/O seam
`run_git(args, *, repo) -> str`, `scan_paths`, `scan_ref`, the frozen
`LeakReport`, and the patchable module constant `LEAK_GUARD_SKIP_PATHS`. The
scanner reads a temp/committed base64 denylist, prints `path:line: snippet`
findings to STDOUT, a one-line summary/errors to STDERR, and exits 0 clean /
1 findings / 2 error. It stays a STANDALONE script off the pipeline control
path (nothing imports it).

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-50 PM
spec's Expected Behaviors (1-10), the product README/roadmap, the `tests/`
conventions (esp. tests/test_iter49_behavior.py -- the sibling bite-1 core --
for the module-loading / dormancy style), and the product's OWN OBSERVABLE
behaviour by RUNNING it (importing the module from its committed path and
driving `main` / the `run_git` seam). The implementation SOURCE of
`scripts/leak_guard.py` / `foundry.py` / `dispatcher.py` (as logic to mirror),
the engineer's and reviewer's notes, and the *content* of `git diff` were NOT
read for their logic. The one `git diff --quiet` call (Behavior 10) emits NO
diff text -- it is an exit-code-only assertion of the byte-unchanged invariant,
not a reading of the diff. Every NEEDLE used to exercise MATCHING is SYNTHETIC
(`WIDGET` / `zap`) -- this test file contains NO real sensitive token and NO
personal home path (temp paths are runtime values, never hard-coded), so it
cannot itself trip the ship-gate's own leak scan on push. Fully offline &
deterministic: no real git/network; every `--ref` scan replaces the single
`run_git` seam with a pure fake; the only subprocess is the documented
`import foundry, dispatcher` dormancy probe.
"""
import contextlib
import importlib.util
import io
import os
import pathlib
import re
import subprocess
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_leak_guard():
    """Load the committed module from its repo-relative path (spec-endorsed:
    there is no conftest.py). Register in sys.modules BEFORE exec so the frozen
    `LeakReport` dataclass resolves its own module."""
    src = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["leak_guard"] = mod
    spec.loader.exec_module(mod)
    return mod


lg = _load_leak_guard()


def _tok(word):
    """A token-aware SYNTHETIC needle pattern (non-letter boundaries)."""
    return r"(?<![A-Za-z])" + word + r"(?![A-Za-z])"


def _mk_denylist(tmp_path, *patterns, name="dl.txt"):
    """Write a temp denylist of encode_pattern(...) lines; return its path str."""
    dl = tmp_path / name
    dl.write_text("\n".join(lg.encode_pattern(p) for p in patterns) + "\n")
    return str(dl)


def _run(argv):
    """Drive the CLI, capturing (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = lg.main(argv)
    return rc, out.getvalue(), err.getvalue()


def _out_lines(stdout):
    return [ln for ln in stdout.splitlines() if ln]


# ==========================================================================
# Behavior 1 -- --files clean -> exit 0, no findings on STDOUT
# ==========================================================================
def test_b1_files_clean_exit0_no_findings(tmp_path):
    dl = _mk_denylist(tmp_path, _tok("WIDGET"))
    f = tmp_path / "clean.txt"
    f.write_text("nothing to see here\njust ordinary prose\n")
    rc, out, err = _run(["--files", str(f), "--denylist", dl])
    assert rc == 0, f"a clean --files scan must exit 0; got {rc}, stderr={err!r}"
    assert out == "", f"a clean scan must print NO finding line to STDOUT; got {out!r}"


# ==========================================================================
# Behavior 2 -- --files with a needle -> exit 1, precise `path:line: snippet`
# ==========================================================================
def test_b2_files_needle_exit1_precise_report(tmp_path):
    dl = _mk_denylist(tmp_path, _tok("WIDGET"))
    f = tmp_path / "hit.txt"
    snippet = "WIDGET here"                       # stripped form of the match line
    # needle on physical line 3 (blank/padding around it must not shift the count)
    f.write_text(f"line one\nline two\n   {snippet}   \nline four\n")
    rc, out, err = _run(["--files", str(f), "--denylist", dl])
    assert rc == 1, f"a needle must exit 1; got {rc}"
    expected = f"{f}:3: {snippet}"
    assert expected in out.splitlines(), (
        f"STDOUT must contain EXACTLY the finding line {expected!r} "
        f"(path as passed, 1-based physical line, stripped snippet); got {out!r}"
    )
    # the human summary belongs on STDERR, never mixed into STDOUT finding lines
    assert "finding" not in out, f"the summary must not leak onto STDOUT; got {out!r}"
    assert "finding" in err, f"the one-line summary must be on STDERR; got {err!r}"


def test_b2_snippet_stripped_and_truncated_to_90(tmp_path):
    dl = _mk_denylist(tmp_path, _tok("WIDGET"))
    f = tmp_path / "long.txt"
    f.write_text("WIDGET " + ("x" * 200) + "\n")
    rc, out, err = _run(["--files", str(f), "--denylist", dl])
    assert rc == 1
    line = _out_lines(out)[0]
    prefix = f"{f}:1: "
    assert line.startswith(prefix), f"finding line must start with {prefix!r}; got {line!r}"
    snippet = line[len(prefix):]
    assert len(snippet) == 90, f"snippet must be truncated to 90 chars; got len {len(snippet)}"


# ==========================================================================
# Behavior 3 -- token-aware: benign superstring NOT flagged; bare token IS
# ==========================================================================
def test_b3_benign_superstring_not_flagged(tmp_path):
    dl = _mk_denylist(tmp_path, _tok("zap"))
    benign = tmp_path / "benign.txt"
    benign.write_text("this is gazapping around\nzapper too\nunzap here\n")
    rc, out, err = _run(["--files", str(benign), "--denylist", dl])
    assert rc == 0, f"benign superstrings of the token must NOT flag; got {rc}, out={out!r}"
    assert out == ""


def test_b3_bare_token_is_flagged(tmp_path):
    dl = _mk_denylist(tmp_path, _tok("zap"))
    bare = tmp_path / "bare.txt"
    bare.write_text("we should zap it now\n")
    rc, out, err = _run(["--files", str(bare), "--denylist", dl])
    assert rc == 1, f"the bare token on its own must flag; got {rc}"
    assert f"{bare}:1: " in out, f"finding must name the bare-token file; got {out!r}"


# ==========================================================================
# Behavior 4 -- self-skip (path ends with a LEAK_GUARD_SKIP_PATHS entry)
# ==========================================================================
def test_b4_self_skip_via_monkeypatched_constant(monkeypatch, tmp_path):
    dl = _mk_denylist(tmp_path, _tok("WIDGET"))
    # the constant is read at call time -> a monkeypatch must bite.
    monkeypatch.setattr(lg, "LEAK_GUARD_SKIP_PATHS", ("skipme.txt",))
    skipped = tmp_path / "skipme.txt"
    skipped.write_text("WIDGET lives here\n")
    rc, out, err = _run(["--files", str(skipped), "--denylist", dl])
    assert rc == 0, f"a path ending with a skip entry must NOT be scanned; got {rc}, out={out!r}"
    assert out == ""
    # a non-skipped sibling with the SAME needle IS flagged
    sib = tmp_path / "other.txt"
    sib.write_text("WIDGET lives here\n")
    rc2, out2, err2 = _run(["--files", str(sib), "--denylist", dl])
    assert rc2 == 1, f"a non-skipped sibling with the same needle must be flagged; got {rc2}"
    assert f"{sib}:1: " in out2


def test_b4_default_skip_paths_include_guard_files():
    assert "scripts/leak_guard.py" in lg.LEAK_GUARD_SKIP_PATHS, (
        f"default skip set must include the guard's own path; got {lg.LEAK_GUARD_SKIP_PATHS!r}"
    )
    assert "scripts/leak_denylist.txt" in lg.LEAK_GUARD_SKIP_PATHS, (
        f"default skip set must include the denylist path; got {lg.LEAK_GUARD_SKIP_PATHS!r}"
    )


# ==========================================================================
# Behavior 5 -- --ref mode drives the single run_git seam (fully offline)
# ==========================================================================
def test_b5_ref_mode_via_run_git_seam(monkeypatch, tmp_path):
    dl = _mk_denylist(tmp_path, _tok("WIDGET"))
    calls = []

    def fake_git(args, *, repo):
        calls.append(list(args))
        if args[0] == "ls-tree":
            return "a.txt\0b.txt\0\0"          # trailing empty entries ignored
        if args[0] == "show":
            target = args[1]
            if target.endswith("a.txt"):
                return "clean blob\nno needle\n"
            if target.endswith("b.txt"):
                return "top line\nWIDGET leaked here\nbottom\n"
        raise AssertionError(f"unexpected git call {args!r}")

    monkeypatch.setattr(lg, "run_git", fake_git)
    rc, out, err = _run(["--ref", "MYREF", "--denylist", dl])
    assert rc == 1, f"a needle in a blob must exit 1; got {rc}"
    assert "b.txt:2: WIDGET leaked here" in out.splitlines(), (
        f"finding must name the blob's repo-relative path + 1-based line; got {out!r}"
    )
    # exact seam argv shapes (ls-tree first, then a `show REF:path` per blob)
    assert ["ls-tree", "-r", "--name-only", "-z", "MYREF"] in calls, calls
    assert ["show", "MYREF:a.txt"] in calls, calls
    assert ["show", "MYREF:b.txt"] in calls, calls


def test_b5_ref_mode_all_clean_exit0(monkeypatch, tmp_path):
    dl = _mk_denylist(tmp_path, _tok("WIDGET"))

    def fake_git(args, *, repo):
        if args[0] == "ls-tree":
            return "x.txt\0y.txt\0"
        return "totally clean\nprose only\n"

    monkeypatch.setattr(lg, "run_git", fake_git)
    rc, out, err = _run(["--ref", "SOMEREF", "--denylist", dl])
    assert rc == 0, f"an all-clean tree must exit 0; got {rc}, out={out!r}"
    assert out == ""


# ==========================================================================
# Behavior 6 -- default ref is HEAD (neither --files nor --ref)
# ==========================================================================
def test_b6_default_ref_is_head(monkeypatch, tmp_path):
    dl = _mk_denylist(tmp_path, _tok("WIDGET"))
    calls = []

    def fake_git(args, *, repo):
        calls.append(list(args))
        if args[0] == "ls-tree":
            return "only.txt\0"
        return "clean content\n"

    monkeypatch.setattr(lg, "run_git", fake_git)
    rc, out, err = _run(["--denylist", dl])          # neither --files nor --ref
    assert rc == 0
    ls = [c for c in calls if c and c[0] == "ls-tree"]
    show = [c for c in calls if c and c[0] == "show"]
    assert ls and ls[0][-1] == "HEAD", f"ls-tree must default to literal HEAD; got {ls!r}"
    assert show and all(c[1].startswith("HEAD:") for c in show), (
        f"every `show` must target HEAD:<path>; got {show!r}"
    )


# ==========================================================================
# Behavior 7 -- bad denylist -> exit 2, one error line, no traceback
# ==========================================================================
def test_b7_bad_denylist_invalid_base64_exit2_no_traceback(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text("!!! definitely not base64 !!!\n")
    clean = tmp_path / "c.txt"
    clean.write_text("hello world\n")
    rc, out, err = _run(["--files", str(clean), "--denylist", str(bad)])
    assert rc == 2, f"a bad denylist must exit 2; got {rc}"
    err_lines = _out_lines(err)
    assert len(err_lines) == 1, f"exactly one error line expected; got {err_lines!r}"
    assert err_lines[0].startswith("error:"), f"error line must start with 'error:'; got {err_lines[0]!r}"
    assert "Traceback" not in err and "Traceback" not in out, "no Python traceback may escape main"


def test_b7_bad_denylist_invalid_regex_exit2(tmp_path):
    bad = tmp_path / "badre.txt"
    bad.write_text(lg.encode_pattern("[unclosed") + "\n")   # decodes to an invalid regex
    clean = tmp_path / "c.txt"
    clean.write_text("hello\n")
    rc, out, err = _run(["--files", str(clean), "--denylist", str(bad)])
    assert rc == 2, f"a denylist line decoding to invalid regex must exit 2; got {rc}"
    assert "Traceback" not in err, "no Python traceback may escape main"


# ==========================================================================
# Behavior 8 -- git-seam failure -> exit 2, no findings, no traceback
# ==========================================================================
def test_b8_git_seam_failure_exit2_no_findings(monkeypatch, tmp_path):
    dl = _mk_denylist(tmp_path, _tok("WIDGET"))

    def boom(args, *, repo):
        raise RuntimeError("simulated git failure")

    monkeypatch.setattr(lg, "run_git", boom)
    rc, out, err = _run(["--ref", "HEAD", "--denylist", dl])
    assert rc == 2, f"a git-seam failure must exit 2; got {rc}"
    assert out == "", f"a failed scan must report no findings; got {out!r}"
    err_lines = _out_lines(err)
    assert len(err_lines) == 1 and err_lines[0].startswith("error:"), (
        f"exactly one 'error:' line expected on STDERR; got {err_lines!r}"
    )
    assert "Traceback" not in err, "no Python traceback may escape main"


# ==========================================================================
# Behavior 9 -- multiple findings ordered + STDERR summary count
# ==========================================================================
def test_b9_multiple_findings_ordered_with_summary_count(tmp_path):
    dl = _mk_denylist(tmp_path, _tok("WIDGET"))
    f1 = tmp_path / "f1.txt"
    f1.write_text("WIDGET a\nclean\nWIDGET b\n")
    f2 = tmp_path / "f2.txt"
    f2.write_text("nothing here\nWIDGET c\n")
    rc, out, err = _run(["--files", str(f1), str(f2), "--denylist", dl])
    assert rc == 1
    lines = _out_lines(out)
    assert lines == [
        f"{f1}:1: WIDGET a",
        f"{f1}:3: WIDGET b",
        f"{f2}:2: WIDGET c",
    ], f"findings must be ordered by file scan order then ascending line; got {lines!r}"
    m = re.search(r"(\d+)\s+finding", err)
    assert m and int(m.group(1)) == len(lines), (
        f"STDERR summary finding-count must equal reported findings ({len(lines)}); err={err!r}"
    )


# ==========================================================================
# Behavior 10 -- dormant, off control path, offline, writes nothing, stdlib-only
# ==========================================================================
def test_b10_import_foundry_dispatcher_ok():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b10_foundry_dispatcher_do_not_reference_leak_guard():
    # fresh interpreter (this test process already imported leak_guard): importing
    # the pipeline must not pull in leak_guard nor reference a leak_guard symbol.
    probe = (
        "import sys; import foundry, dispatcher; "
        "print('LG_IMPORTED' if 'leak_guard' in sys.modules else 'LG_ABSENT'); "
        "ns = 'leak_guard' in vars(foundry) or 'leak_guard' in vars(dispatcher); "
        "print('REFERENCED' if ns else 'UNREFERENCED')"
    )
    r = subprocess.run([sys.executable, "-c", probe], cwd=str(_ROOT),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "LG_ABSENT" in r.stdout, (
        f"importing the pipeline must NOT import leak_guard (dormant); stdout={r.stdout!r}"
    )
    assert "UNREFERENCED" in r.stdout, (
        f"neither foundry nor dispatcher may reference a leak_guard symbol; stdout={r.stdout!r}"
    )


def test_b10_control_path_files_byte_unchanged():
    # Resume-safety invariant. `git diff --quiet` emits NO diff content (exit code
    # only), so this honors the isolation contract's "do not read git diff": it
    # asserts the byte-unchanged BEHAVIOR, never studies the diff text.
    # NOTE (iter-52): roles/ REMOVED from this byte-unchanged set. Role PROMPTS
    # (roles/*.md) are read fresh from disk each stage and are legitimately edited
    # by iterations (iter-52 wires the leak-guard into roles/final.md), so they are
    # NOT the pipeline control path. NOTE (iter-54): foundry.py ALSO REMOVED --
    # foundry.py is routinely extended additively each iteration (iter-54 adds
    # company-constant-asserts); the real resume-safety invariant is dispatcher.py
    # + a clean import + an additive-only diff, not a foundry.py byte-freeze.
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, (
        "dispatcher.py must be byte-unchanged from HEAD "
        "(resume-safe: leak_guard is off the pipeline control path)"
    )


def test_b10_files_scan_uses_no_git_seam_and_writes_nothing(monkeypatch, tmp_path):
    dl = _mk_denylist(tmp_path, _tok("WIDGET"))

    def _no_git(*a, **k):
        raise AssertionError("run_git must NOT be called in --files mode")

    # if a --files scan touched git it would blow up here -> proves --files makes
    # its ONLY external effect through nothing (no git/subprocess/network).
    monkeypatch.setattr(lg, "run_git", _no_git)
    work = tmp_path / "work"
    work.mkdir()
    f = work / "clean.txt"
    f.write_text("plain text only\n")
    before = set(os.listdir(work))
    rc, out, err = _run(["--files", str(f), "--denylist", dl])
    after = set(os.listdir(work))
    assert rc == 0, f"a clean --files scan must exit 0 without touching git; got {rc}, err={err!r}"
    assert before == after, f"a --files scan must create no file; new: {after - before}"


def test_b10_new_symbols_importable():
    for name in ("main", "run_git", "scan_paths", "scan_ref", "LeakReport",
                 "LEAK_GUARD_SKIP_PATHS"):
        assert hasattr(lg, name), f"public symbol {name!r} must be importable from leak_guard"
    assert callable(lg.main) and callable(lg.run_git)


def test_b10_stdlib_only():
    mods = {v.__name__.split(".")[0] for v in vars(lg).values()
            if isinstance(v, types.ModuleType)}
    nonstd = sorted(m for m in mods if m not in sys.stdlib_module_names)
    assert nonstd == [], f"leak_guard must import only stdlib modules; non-stdlib: {nonstd}"
