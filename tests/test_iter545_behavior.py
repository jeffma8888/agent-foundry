"""Black-box behaviour tests for iter 545 -- ARCHITECTURE.md §3 states that a revert
keeps approved work, pinned by a drift oracle derived from `revert_repo`'s AST.

Spec: products/_platform/state/iter-545/pm.md, Expected Behaviors 1-9.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-545
PM spec, from pre-existing modules under `tests/` (conventions), and from the product's
public interface. The engineer's/reviewer's notes and `git diff` output were NOT read by
the author. The oracle parses `foundry.py` at RUN TIME because the spec defines a
CODE-DERIVED drift check; its expected names come from the spec, not from the source.
Only TRACKED files (`foundry.py`, `ARCHITECTURE.md`) are read, resolved from this file's
own location. No network; subprocesses are a clean-interpreter import probe and `git`.
"""
import ast
import difflib
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FOUNDRY_PY = ROOT / "foundry.py"
ARCH_MD = ROOT / "ARCHITECTURE.md"

sys.path.insert(0, str(ROOT))

EXPECTED_INVARIANTS = (
    "Output-file success",
    "Independent, pessimistic gate",
    "Tester isolation",
    "Anti-delegation clause",
    "Resilience",
)


# --------------------------------------------------------------------------- oracle
def _is_reset_call(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "git"
        and any(isinstance(a, ast.Constant) and a.value == "reset" for a in node.args)
    )


def pre_reset_calls(src):
    """Bare-name calls made in `revert_repo`'s body BEFORE its first `git(..., "reset")`."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ()
    fn = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "revert_repo"),
        None,
    )
    if fn is None:
        return ()
    out = []
    for stmt in fn.body:
        if any(_is_reset_call(n) for n in ast.walk(stmt)):
            break
        calls = [
            n for n in ast.walk(stmt)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        ]
        calls.sort(key=lambda n: (n.lineno, n.col_offset))
        out.extend(c.func.id for c in calls)
    return tuple(out)


def section3(doc):
    lines = doc.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("## 3. Invariants")), None)
    if start is None:
        return ""
    end = next(
        (j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def undocumented(names, doc):
    span = section3(doc)
    return tuple(n for n in names if f"`{n}`" not in span)


def _live_src():
    return FOUNDRY_PY.read_text(encoding="utf-8")


def _live_doc():
    return ARCH_MD.read_text(encoding="utf-8")


def _flat(text):
    return " ".join(text.split())


def _git(*args):
    if shutil.which("git") is None:
        pytest.skip("git unavailable")
    proc = subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True, text=True
    )
    return proc


# --------------------------------------------------------------------------- B1
def test_b1_live_pre_reset_calls_exact_in_source_order():
    assert pre_reset_calls(_live_src()) == (
        "capture_abort_patch",
        "flag_resumable_after_revert",
    )


# --------------------------------------------------------------------------- B2
def test_b2_each_pre_reset_name_backticked_in_section3():
    names = pre_reset_calls(_live_src())
    assert names, "oracle vacuous: no pre-reset calls found"
    span = section3(_live_doc())
    assert span, "## 3. Invariants span missing"
    for n in names:
        assert f"`{n}`" in span, n
    assert undocumented(names, _live_doc()) == ()


# --------------------------------------------------------------------------- B3
@pytest.mark.parametrize("token", ["`RESUMABLE.md`", "`PARKED.md`", "`resumable`"])
def test_b3_section3_names_resumable_artifacts(token):
    # strict reading: the literal backticked token itself is in the span
    assert token in section3(_live_doc()), token


def test_b3_section3_names_foundry_resumable_verb():
    assert "foundry resumable" in _flat(section3(_live_doc()))


def test_b3_section3_mentions_duty_0a():
    assert "duty 0a" in _flat(section3(_live_doc()))


# --------------------------------------------------------------------------- B4
SYNTH_SRC = '''
def helper():
    pass

def revert_repo(cfg, reason):
    try:
        capture_abort_patch(cfg)
    except Exception:
        pass
    new_hook(cfg)
    git(cfg, "reset", "--hard", f"origin/{cfg.branch}")
    after_hook(cfg)
'''


def test_b4_synthetic_new_hook_detected_and_post_reset_excluded():
    got = pre_reset_calls(SYNTH_SRC)
    assert got == ("capture_abort_patch", "new_hook")
    assert "after_hook" not in got


def test_b4_reset_inside_try_still_stops_walk():
    src = (
        "def revert_repo(cfg, reason):\n"
        "    a(cfg)\n"
        "    try:\n"
        "        git(cfg, 'reset', '--hard', 'x')\n"
        "    except Exception:\n"
        "        pass\n"
        "    b(cfg)\n"
    )
    assert pre_reset_calls(src) == ("a",)


def test_b4_nested_function_named_revert_repo_not_used():
    src = (
        "class C:\n"
        "    def revert_repo(self):\n"
        "        x()\n"
        "        git(self, 'reset')\n"
    )
    assert pre_reset_calls(src) == ()


# --------------------------------------------------------------------------- B5
SYNTH_DOC = """# Doc

## 3. Invariants (do not regress these)

- **Independent, pessimistic gate.** before reset `revert_repo` calls `capture_abort_patch`.

## 4. Something else

Here `new_hook` is mentioned, but outside section 3.
"""


def test_b5_check_is_scoped_to_section3():
    assert undocumented(("capture_abort_patch", "new_hook"), SYNTH_DOC) == ("new_hook",)


def test_b5_documented_in_section3_clears():
    doc = SYNTH_DOC.replace("`capture_abort_patch`.", "`capture_abort_patch` and `new_hook`.")
    assert undocumented(("capture_abort_patch", "new_hook"), doc) == ()


# --------------------------------------------------------------------------- B6
@pytest.mark.parametrize("src", ["", "def other():\n    pass\n", "def broken(:\n"])
def test_b6_source_without_revert_repo_returns_empty(src):
    assert pre_reset_calls(src) == ()


@pytest.mark.parametrize("doc", ["", "# Title\n\n## 4. Other\n`capture_abort_patch`\n"])
def test_b6_doc_without_section3_everything_undocumented(doc):
    names = ("capture_abort_patch", "flag_resumable_after_revert")
    assert undocumented(names, doc) == names


# --------------------------------------------------------------------------- B7
def test_b7_invariant_names_unchanged():
    import foundry

    assert tuple(foundry.architecture_invariant_names(_live_doc())) == EXPECTED_INVARIANTS


# --------------------------------------------------------------------------- B8
def _head_arch():
    proc = _git("show", "HEAD:ARCHITECTURE.md")
    if proc.returncode != 0:
        pytest.skip("git HEAD unavailable")
    return proc.stdout


def test_b8_architecture_changed_only_by_insertion():
    head = _head_arch()
    work = _live_doc()
    diff = list(difflib.ndiff(head.splitlines(), work.splitlines()))
    removed = [l[2:] for l in diff if l.startswith("- ")]
    assert len(removed) <= 1, removed
    if removed:
        line = removed[0].strip()
        # the one removed line is the split anchor: its two halves both survive
        ok = any(
            line[:k].strip() in work and line[k:].strip() in work
            for k in range(1, len(line))
        )
        assert ok, f"removed line not a split anchor: {line!r}"
    # every HEAD line survives in order (insertion-only): HEAD is a subsequence modulo anchor
    sm = difflib.SequenceMatcher(a=head.splitlines(), b=work.splitlines(), autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    assert matched >= len(head.splitlines()) - 1


def test_b8_post_release_paragraph_still_in_section3():
    assert "**Post-release re-verification:**" in section3(_live_doc())


def test_b8_section3_gained_revert_keeps_work_text():
    flat = _flat(section3(_live_doc()))
    assert "`capture_abort_patch`" in flat
    assert "`flag_resumable_after_revert`" in flat


# --------------------------------------------------------------------------- B9
def test_b9_clean_import_of_foundry_and_dispatcher():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_b9_no_code_diff_in_foundry_or_dispatcher():
    head = _git("rev-parse", "--verify", "HEAD")
    if head.returncode != 0:
        pytest.skip("git HEAD unavailable")
    proc = _git("diff", "HEAD", "--", "foundry.py", "dispatcher.py")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
