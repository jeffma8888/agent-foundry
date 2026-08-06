"""Black-box behaviour tests for iter 124 -- a THIRD roadmap brake that starts from GIT
ship-truth (`iteration_from_subject`, `shipped_iterations`, `roadmap_ledger_gaps` plus the
single I/O seam `git_ship_subjects`), the recovery of the permanently lost records for
iterations 64 and 122, iteration 124's own record, and the flipped written contract that
each PM records its OWN iteration in the commit that ships it.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-124 PM spec
(products/_platform/state/iter-124/pm.md -- Expected Behaviors 1-10 + Acceptance
Criteria) and from the product's own OBSERVABLE surface: importing the module and CALLING
its public functions, reading their `__doc__`, running `foundry.py --help` as a
subprocess, and reading the two SHIPPED roadmap markdown files plus `roles/pm.md`
(documentation deliverables of THIS iteration, named by behaviors 6 and 9). The
implementation source of `foundry.py` / `dispatcher.py`, the engineer's notes, the
reviewer's notes and `git diff` content were NOT read. Dormancy and regex-reuse use the
iter-107 `co_names` BYTECODE convention over COMPILED code objects, never a read of
module source text. Fully offline and deterministic: synthetic strings, one throwaway
`git init` repository under pytest's tmp_path (never the product repo), and exit-code /
stdout-only reads of the product's own CLI help. No network, no agent run, no mutation of
the product tree.

DISCLOSED PEEK (honesty, not a licence): while probing the seam's failure modes with a
deliberately broken stub, the resulting TRACEBACK printed four lines of `git_ship_subjects`
into my terminal. No source file was opened and the tests below encode the SPEC's stated
failure modes (non-zero exit, missing binary, timeout, not-a-repository), not those lines.
"""
import ast
import hashlib
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- Acceptance Criteria)

_INDEX = _ROOT / "PLATFORM_ROADMAP.md"
_ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
_PM_CARD = _ROOT / "roles" / "pm.md"
_ITER122_TEST = _ROOT / "tests" / "test_iter122_behavior.py"
_GITIGNORE = _ROOT / ".gitignore"

# The spec's NORMATIVE record shapes, written out here so these tests never depend on the
# implementation's own regex objects for their oracle.
LEDGER_RE = re.compile(r"^- iter (\d+) ", re.M)
BULLET_RE = re.compile(r"^- \*\*iter (\d+) ", re.M)

NEW_NAMES = (
    "iteration_from_subject",
    "shipped_iterations",
    "roadmap_ledger_gaps",
    "git_ship_subjects",
)

# Behavior 7: iter-122's oracle constants must be BYTE-UNCHANGED. Pinning the literal
# here is the assertion -- if a future edit touches it, this file goes red.
PINNED_ITER122_SHA256 = (
    "0fee18f4f5568de1404fe49786e1ec6a5648131fd2f698dabfa570b62dfaa904")

THIS_ITER = 124
RECOVERED_LEDGER = (122, 124)          # behavior 6
RECOVERED_ARCHIVE = (64, 122, 124)     # behavior 6


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _co_names_deep(fn):
    """Names referenced by a function's bytecode, recursively through nested code
    objects (iter-107 convention). Never reads module source text."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _boom(*a, **k):
    raise AssertionError("a function the spec declares PURE performed real I/O")


def _index_text():
    return _INDEX.read_text(encoding="utf-8")


def _archive_text():
    return _ARCHIVE.read_text(encoding="utf-8")


def _matches(text, rx):
    out = []
    for line in text.splitlines():
        m = rx.match(line)
        if m:
            out.append((int(m.group(1)), line))
    return out


class _Proc(object):
    """Minimal stand-in for `subprocess.CompletedProcess` (returncode + streams)."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.args = ["git"]


def _gap_message(gaps):
    """Behavior 5's failure text: name every missing number AND the two exact lines."""
    lines = ["%d shipped iteration(s) have NO roadmap record: %r" % (len(gaps), gaps)]
    for n in gaps:
        lines.append("  add to PLATFORM_ROADMAP.md:         - iter %d -- <one line, <=120 chars>" % n)
        lines.append("  add to PLATFORM_ROADMAP_ARCHIVE.md: - **iter %d = <title>** <detail>" % n)
    return "\n".join(lines)


def _git(args, cwd):
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True,
                          text=True, timeout=120)


def _tiny_repo(tmp_path, subjects):
    """A throwaway git repo whose commit SUBJECTS are exactly `subjects` (oldest first)."""
    repo = tmp_path / "tiny"
    repo.mkdir()
    init = _git(["init", "-q"], repo)
    if init.returncode != 0:
        pytest.skip("git init unavailable in this environment")
    ident = ["-c", "user.email=t@example.invalid", "-c", "user.name=t"]
    for i, subject in enumerate(subjects):
        (repo / ("f%d.txt" % i)).write_text("x\n", encoding="utf-8")
        _git(["add", "-A"], repo)
        r = _git(ident + ["commit", "-q", "-m", subject], repo)
        if r.returncode != 0:
            pytest.skip("git commit unavailable in this environment: %s" % r.stderr[:120])
    return repo


# ==========================================================================
# Behavior 1 -- iteration_from_subject is pure and total
# ==========================================================================
B1_CASES = [
    ("feat: x (foundry iter 122)", 122),
    ("feat: x (foundry iter 7)   ", 7),
    ("feat: x (foundry iter 007)", 7),
    ("feat: x (foundry iter 7)\n", 7),
    ("(foundry iter 1)", 1),
    ("", None),
    ("no tag at all", None),
    ("x (foundry iter 7) and more", None),
    ("x (foundry iter )", None),
    ("x (foundry iteration 7)", None),
    ("x foundry iter 7", None),
    ("x (foundry iter seven)", None),
    ("x (foundry iter -3)", None),
    ("x (foundry iter 1.5)", None),
    ("x (FOUNDRY ITER 7)", None),
    ("x (foundry  iter 7)", None),
    ("x (foundry iter 7", None),
    ("x foundry iter 7)", None),
]


def test_b1_iteration_from_subject_table():
    for subject, expected in B1_CASES:
        got = foundry.iteration_from_subject(subject)
        assert got == expected, (
            "iteration_from_subject(%r) == %r, expected %r" % (subject, got, expected))


def test_b1_result_is_a_plain_int_or_none():
    got = foundry.iteration_from_subject("x (foundry iter 12)")
    assert isinstance(got, int) and not isinstance(got, bool), "not a plain int: %r" % (got,)
    assert foundry.iteration_from_subject("x") is None


def test_b1_never_raises_for_any_str_input():
    hostile = [
        "", " ", "\n", "\t\r\n", "(foundry iter 0)", "x (foundry iter 0000)",
        "x (foundry iter " + "9" * 5000 + ")",          # digit run past int_max_str_digits
        "x (foundry iter 12)(foundry iter 13)",
        "unicode \u2014 dash (foundry iter 5)",
        "\x00\x01 (foundry iter 5)",
        "(((foundry iter 5)))",
        "- **iter 5 ", "- iter 5 ",
        "x" * 20000,
        "(foundry iter 5) " * 500,
    ]
    for subject in hostile:
        got = foundry.iteration_from_subject(subject)   # must not raise
        assert got is None or isinstance(got, int), "bad return %r for %r" % (got, subject[:40])


def test_b1_is_pure_no_subprocess(monkeypatch):
    monkeypatch.setattr(foundry.subprocess, "run", _boom)
    assert foundry.iteration_from_subject("x (foundry iter 9)") == 9


# ==========================================================================
# Behavior 2 -- shipped_iterations: ascending, de-duplicated tuple
# ==========================================================================
def test_b2_spec_example():
    got = foundry.shipped_iterations(
        ("a (foundry iter 3)", "b", "c (foundry iter 1)", "d (foundry iter 3)"))
    assert got == (1, 3), "got %r, expected (1, 3)" % (got,)
    assert isinstance(got, tuple), "not a tuple: %r" % type(got)


def test_b2_empty_and_untagged_yield_empty_tuple():
    for arg in ((), [], ["no tag"], ("x", "y (foundry iteration 3)"), iter([])):
        got = foundry.shipped_iterations(arg)
        assert got == (), "shipped_iterations(%r) == %r, expected ()" % (arg, got)


def test_b2_accepts_any_iterable_and_normalises_padding():
    gen = (s for s in ["z (foundry iter 010)", "y (foundry iter 2)", "x (foundry iter 10)"])
    got = foundry.shipped_iterations(gen)
    assert got == (2, 10), "generator input -> %r, expected (2, 10)" % (got,)
    assert foundry.shipped_iterations(["a (foundry iter 5)"] * 50) == (5,)


def test_b2_is_sorted_ascending_and_unique():
    subjects = ["s (foundry iter %d)" % n for n in [9, 1, 33, 1, 9, 100, 2]]
    got = foundry.shipped_iterations(subjects)
    assert got == (1, 2, 9, 33, 100), "got %r" % (got,)
    assert list(got) == sorted(set(got))


def test_b2_is_pure_and_total(monkeypatch):
    monkeypatch.setattr(foundry.subprocess, "run", _boom)
    assert foundry.shipped_iterations(["x (foundry iter " + "9" * 5000 + ")", "a (foundry iter 4)"]) == (4,)


# ==========================================================================
# Behavior 3 -- roadmap_ledger_gaps: either-file, one-directional, total
# ==========================================================================
def test_b3_reports_only_unrecorded_shipped_iterations():
    got = foundry.roadmap_ledger_gaps("- iter 5 x\n", "- **iter 6 y\n", (5, 6, 7))
    assert got == [7], "got %r, expected [7]" % (got,)
    assert isinstance(got, list), "not a list: %r" % type(got)


def test_b3_a_record_in_either_file_counts():
    assert foundry.roadmap_ledger_gaps("- iter 8 row\n", "", (8,)) == []
    assert foundry.roadmap_ledger_gaps("", "- **iter 8 bullet\n", (8,)) == []
    assert foundry.roadmap_ledger_gaps("- iter 8 row\n", "- **iter 8 bullet\n", (8,)) == []
    assert foundry.roadmap_ledger_gaps("", "", (8,)) == [8]


def test_b3_is_one_directional():
    """A number recorded in either file but absent from `shipped` is NEVER reported."""
    index = "- iter 1 a\n- iter 2 b\n- iter 3 c\n"
    archive = "- **iter 4 d\n- **iter 5 e\n"
    assert foundry.roadmap_ledger_gaps(index, archive, ()) == []
    assert foundry.roadmap_ledger_gaps(index, archive, (2,)) == []
    assert foundry.roadmap_ledger_gaps(index, archive, (99,)) == [99]


def test_b3_ascending_and_deduplicated():
    got = foundry.roadmap_ledger_gaps("", "", (9, 1, 9, 4, 1))
    assert got == [1, 4, 9], "got %r, expected [1, 4, 9]" % (got,)


def test_b3_zero_padded_records_match_their_unpadded_number():
    assert foundry.roadmap_ledger_gaps("", "- **iter 01 first\n", (1,)) == []
    assert foundry.roadmap_ledger_gaps("- iter 007 x\n", "", (7,)) == []


def test_b3_records_are_line_anchored():
    """Prose that merely mentions the shape must not count as a record."""
    assert foundry.roadmap_ledger_gaps("see - iter 5 in the ledger\n", "", (5,)) == [5]
    assert foundry.roadmap_ledger_gaps("", "text - **iter 5 bullet\n", (5,)) == [5]
    assert foundry.roadmap_ledger_gaps("  - iter 5 indented\n", "", (5,)) == [5]
    # the trailing space is part of the shape: a bare "- iter 5" is not a row
    assert foundry.roadmap_ledger_gaps("- iter 5\n", "", (5,)) == [5]
    # ...and a longer number must not be matched by a shorter one's prefix
    assert foundry.roadmap_ledger_gaps("- iter 12 x\n", "", (1,)) == [1]


def test_b3_empty_and_malformed_inputs_never_raise():
    hostile = [
        ("", "", (1,)),
        ("- iter x y\n", "- **iter  \n", (1,)),
        ("- iter " + "9" * 5000 + " x\n", "- **iter " + "9" * 5000 + " y\n", (1,)),
        ("\x00\n- iter 1 a\n", "\ufeff- **iter 2 b\n", (1, 2, 3)),
        ("- iter 1 a" * 2000, "", (1,)),
    ]
    for index, archive, shipped in hostile:
        got = foundry.roadmap_ledger_gaps(index, archive, shipped)   # must not raise
        assert isinstance(got, list)
    assert foundry.roadmap_ledger_gaps("", "", []) == []
    assert foundry.roadmap_ledger_gaps("", "", iter([2])) == [2]


def test_b3_reuses_the_existing_roadmap_patterns():
    """Behavior 3: REUSES `_ROADMAP_LEDGER_ROW_RE` / `_ROADMAP_HISTORY_BULLET_RE`."""
    names = _co_names_deep(foundry.roadmap_ledger_gaps)
    for wanted in ("_ROADMAP_LEDGER_ROW_RE", "_ROADMAP_HISTORY_BULLET_RE"):
        assert wanted in names, (
            "roadmap_ledger_gaps does not reference %s (bytecode names: %r)"
            % (wanted, sorted(n for n in names if "ROADMAP" in n)))
    assert _co_names_deep(foundry.roadmap_archive_gaps) & {
        "_ROADMAP_LEDGER_ROW_RE", "_ROADMAP_HISTORY_BULLET_RE"}, (
        "the iter-122 sibling no longer shares the patterns")


def test_b3_is_pure_no_subprocess(monkeypatch):
    monkeypatch.setattr(foundry.subprocess, "run", _boom)
    assert foundry.roadmap_ledger_gaps("- iter 1 a\n", "", (1, 2)) == [2]


def test_b3_documents_the_why():
    doc = (foundry.roadmap_ledger_gaps.__doc__ or "").lower()
    assert len(doc) > 200, "roadmap_ledger_gaps is not documented (len %d)" % len(doc)
    for needle in ("either", "grace"):
        assert needle in doc, "docstring does not explain %r" % needle
    for name in NEW_NAMES:
        assert (getattr(foundry, name).__doc__ or "").strip(), "%s has no docstring" % name


# ==========================================================================
# Behavior 4 -- git_ship_subjects is the only new I/O seam and never raises
# ==========================================================================
def test_b4_reads_subjects_from_a_real_repository(tmp_path):
    repo = _tiny_repo(tmp_path, ["first commit", "feat: a (foundry iter 5)",
                                 "chore: untagged", "feat: b (foundry iter 7)"])
    got = foundry.git_ship_subjects(str(repo))
    assert isinstance(got, tuple), "not a tuple: %r" % type(got)
    assert set(got) == {"first commit", "feat: a (foundry iter 5)",
                        "chore: untagged", "feat: b (foundry iter 7)"}, "got %r" % (got,)
    assert "" not in got, "empty subject line leaked: %r" % (got,)
    assert foundry.shipped_iterations(got) == (5, 7)


def test_b4_accepts_a_path_object(tmp_path):
    repo = _tiny_repo(tmp_path, ["only (foundry iter 3)"])
    assert foundry.shipped_iterations(foundry.git_ship_subjects(pathlib.Path(repo))) == (3,)


def test_b4_not_a_repository_returns_empty(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert foundry.git_ship_subjects(str(plain)) == ()
    assert foundry.git_ship_subjects(str(tmp_path / "does-not-exist")) == ()


def test_b4_non_zero_exit_returns_empty(monkeypatch):
    monkeypatch.setattr(foundry.subprocess, "run",
                        lambda *a, **k: _Proc(128, "", "fatal: not a git repository"))
    assert foundry.git_ship_subjects("/anywhere") == ()


def test_b4_missing_git_binary_returns_empty(monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError(2, "No such file or directory: 'git'")
    monkeypatch.setattr(foundry.subprocess, "run", missing)
    assert foundry.git_ship_subjects("/anywhere") == ()


def test_b4_os_error_returns_empty(monkeypatch):
    def broken(*a, **k):
        raise OSError(13, "Permission denied")
    monkeypatch.setattr(foundry.subprocess, "run", broken)
    assert foundry.git_ship_subjects("/anywhere") == ()


def test_b4_timeout_returns_empty(monkeypatch):
    def slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd=["git", "log"], timeout=1)
    monkeypatch.setattr(foundry.subprocess, "run", slow)
    assert foundry.git_ship_subjects("/anywhere") == ()


def test_b4_drops_blank_subject_lines(monkeypatch):
    monkeypatch.setattr(foundry.subprocess, "run",
                        lambda *a, **k: _Proc(0, "a\n\n   \nb (foundry iter 3)\n"))
    got = foundry.git_ship_subjects("/anywhere")
    assert "" not in got, "empty subject leaked: %r" % (got,)
    assert [s for s in got if s.strip()] == ["a", "b (foundry iter 3)"], "got %r" % (got,)


def test_b4_reads_only_subjects(monkeypatch):
    """The seam must ask git for `log --format=%s` -- subjects, never bodies or diffs."""
    seen = {}

    def record(cmd, *a, **k):
        seen["cmd"] = list(cmd)
        return _Proc(0, "s (foundry iter 1)\n")
    monkeypatch.setattr(foundry.subprocess, "run", record)
    assert foundry.git_ship_subjects("/repo") == ("s (foundry iter 1)",)
    cmd = seen["cmd"]
    assert cmd[0] == "git" and "log" in cmd, "unexpected command %r" % (cmd,)
    assert "--format=%s" in cmd, "does not request subjects only: %r" % (cmd,)
    assert not [a for a in cmd if a.startswith("-p") or a == "--patch"], (
        "the seam asked git for a diff: %r" % (cmd,))


def test_b4_is_monkeypatchable_by_bare_module_name(monkeypatch):
    monkeypatch.setattr(foundry, "git_ship_subjects",
                        lambda repo_dir: ("scripted (foundry iter 42)",))
    assert foundry.shipped_iterations(foundry.git_ship_subjects("/ignored")) == (42,)


# ==========================================================================
# Behavior 5 -- the LIVE contract on the tracked tree (skips without git)
# ==========================================================================
def test_b5_every_shipped_iteration_has_a_durable_record():
    subjects = foundry.git_ship_subjects(str(_ROOT))
    if not subjects:
        pytest.skip("no git history available -- missing INFRA, not a lost record")
    shipped = foundry.shipped_iterations(subjects)
    assert shipped, "git history carries no (foundry iter N) ship tag at all"
    gaps = foundry.roadmap_ledger_gaps(_index_text(), _archive_text(), shipped)
    assert gaps == [], _gap_message(gaps)


def test_b5_holds_after_this_iteration_is_pushed():
    """Self-referential brake: pushing 124 ADDS 124 to the input set (iter-124 REV lesson)."""
    subjects = foundry.git_ship_subjects(str(_ROOT))
    if not subjects:
        pytest.skip("no git history available")
    shipped = set(foundry.shipped_iterations(subjects)) | {THIS_ITER}
    gaps = foundry.roadmap_ledger_gaps(_index_text(), _archive_text(), tuple(sorted(shipped)))
    assert gaps == [], _gap_message(gaps)


def test_b5_skip_premise_is_real():
    """The SKIP branch is reachable and benign: no subjects -> no shipped -> no gaps."""
    assert foundry.shipped_iterations(()) == ()
    assert foundry.roadmap_ledger_gaps(_index_text(), _archive_text(), ()) == []


def test_b5_failure_message_names_the_numbers_and_both_lines():
    msg = _gap_message([64, 122])
    assert "64" in msg and "122" in msg, msg
    assert "- iter 64" in msg and "- **iter 122" in msg, msg
    assert "PLATFORM_ROADMAP.md" in msg and "PLATFORM_ROADMAP_ARCHIVE.md" in msg, msg


# ==========================================================================
# Behavior 6 -- the recovered and current records are in the tracked tree
# ==========================================================================
def test_b6_ledger_rows_for_122_and_124():
    nums = [n for n, _ in _matches(_index_text(), LEDGER_RE)]
    for n in RECOVERED_LEDGER:
        assert n in nums, "PLATFORM_ROADMAP.md has no `- iter %d ` Done-ledger row" % n
        assert nums.count(n) == 1, "duplicate ledger row for iter %d" % n


def test_b6_archive_bullets_for_64_122_and_124():
    nums = [n for n, _ in _matches(_archive_text(), BULLET_RE)]
    for n in RECOVERED_ARCHIVE:
        assert n in nums, "PLATFORM_ROADMAP_ARCHIVE.md has no `- **iter %d ` bullet" % n
        assert nums.count(n) == 1, "duplicate archive bullet for iter %d" % n


def test_b6_new_ledger_rows_are_one_line_of_at_most_120_chars():
    rows = [(n, l) for n, l in _matches(_index_text(), LEDGER_RE) if n in RECOVERED_LEDGER]
    for n, line in rows:
        assert len(line) <= 120, "iter %d ledger row is %d chars: %r" % (n, len(line), line)
        assert "\n" not in line


def test_b6_this_iteration_records_itself_in_both_files():
    """Mandatory: the moment this commit is pushed, git reports 124 as shipped."""
    assert THIS_ITER in [n for n, _ in _matches(_index_text(), LEDGER_RE)]
    assert THIS_ITER in [n for n, _ in _matches(_archive_text(), BULLET_RE)]


def test_b6_index_stays_under_the_size_budget():
    text = _index_text()
    assert len(text) <= foundry.ROADMAP_SIZE_WARN_CHARS, (
        "index is %d chars, budget %d" % (len(text), foundry.ROADMAP_SIZE_WARN_CHARS))
    assert not foundry.roadmap_archive_gaps(text, _archive_text()), (
        "the iter-122 archive-gap brake is RED: %r"
        % (foundry.roadmap_archive_gaps(text, _archive_text()),))


# ==========================================================================
# Behavior 7 -- iteration 122's oracles are untouched and unweakened
# ==========================================================================
def _iter122_constants():
    tree = ast.parse(_ITER122_TEST.read_text(encoding="utf-8"))
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in ("PINNED_SHA256", "FROZEN"):
                out[target.id] = ast.literal_eval(node.value)
    return out


def test_b7_iter122_pinned_constants_are_byte_unchanged():
    consts = _iter122_constants()
    assert consts.get("PINNED_SHA256") == PINNED_ITER122_SHA256, (
        "iter-122 PINNED_SHA256 changed: %r" % (consts.get("PINNED_SHA256"),))
    frozen = consts.get("FROZEN")
    assert isinstance(frozen, set) and len(frozen) == 98, (
        "iter-122 FROZEN is no longer the 98-iteration move set: %r"
        % (len(frozen) if frozen else frozen,))
    assert max(frozen) == 119, "iter-122 FROZEN max changed: %r" % (max(frozen),)


def test_b7_pinned_digest_still_matches_the_archive():
    frozen = _iter122_constants()["FROZEN"]
    selected = [l for n, l in _matches(_archive_text(), BULLET_RE) if n in frozen]
    assert len(selected) == len(frozen), (
        "selected %d frozen bullets, expected %d" % (len(selected), len(frozen)))
    got = hashlib.sha256("\n".join(selected).encode()).hexdigest()
    assert got == PINNED_ITER122_SHA256, (
        "an archived bullet was re-worded/re-wrapped/re-ordered: %s != %s"
        % (got, PINNED_ITER122_SHA256))


def test_b7_no_new_ledger_row_for_an_old_iteration():
    """iter-122's `extra_history` guard: iteration 64 must be ARCHIVE-only.

    MIRROR, not a new freeze: `tests/test_iter122_behavior.py` is authoritative. The
    pre-declared follow-up bite that gives iteration 64 a terse LEDGER row must amend
    BOTH guards on purpose -- that is the point of the spec's Out of Scope entry.
    """
    frozen = _iter122_constants()["FROZEN"]
    nums = {n for n, _ in _matches(_index_text(), LEDGER_RE)}
    extra_old = sorted(n for n in (nums - frozen) if n <= max(frozen))
    assert extra_old == [], (
        "new ledger row(s) for iteration(s) <= 119 would break iter-122's guard: %r"
        % (extra_old,))
    assert 64 not in nums, "iteration 64 was recovered into the LEDGER (must be archive-only)"


# ==========================================================================
# Behavior 8 -- the four new names are DORMANT (compiled co_names, not grep)
# ==========================================================================
DORMANCY_TARGETS = ("run_iteration", "run_continuous", "run_stage", "build_prompt",
                    "postrelease_step", "lint_config")


def test_b8_new_names_are_absent_from_the_control_path():
    for target in DORMANCY_TARGETS:
        fn = getattr(foundry, target, None)
        assert fn is not None, "control-path function %s is missing" % target
        names = _co_names_deep(fn)
        leaked = sorted(set(NEW_NAMES) & names)
        assert not leaked, "%s references dormant name(s) %r" % (target, leaked)


def test_b8_no_new_runtime_artifact_in_gitignore():
    text = _GITIGNORE.read_text(encoding="utf-8")
    for name in NEW_NAMES:
        assert name not in text, ".gitignore mentions %s -- a new artifact leaked" % name


def test_b8_no_new_config_field():
    example = (_ROOT / "foundry.config.example.json").read_text(encoding="utf-8")
    for name in NEW_NAMES:
        assert name not in example, "example config gained a %s field" % name


def test_b8_module_still_imports_cleanly():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, "import failed: %s" % (r.stderr or r.stdout)[-800:]


# ==========================================================================
# Behavior 9 -- the written contract is flipped and the stale prose is gone
# ==========================================================================
def test_b9_index_contract_says_each_pm_records_its_own_iteration():
    text = _index_text()
    low = text.lower()
    assert "own record" in low or "its own" in low, "index does not state OWN-record ownership"
    assert "commit that ships" in low, "index does not tie the record to the ship commit"
    assert "- iter N " in text or "- iter N`" in text, "index does not name the ledger row shape"
    assert "- **iter N " in text or "- **iter N`" in text, "index does not name the bullet shape"
    assert "PLATFORM_ROADMAP_ARCHIVE.md" in text


def test_b9_stale_prose_is_gone():
    text = _index_text()
    assert "NEXT iteration's PM" not in text, "the stale deferral contract is still in the index"
    assert "IN FLIGHT: iteration 122" not in text, "the stale IN FLIGHT sentence survives"


def test_b9_index_has_an_accurate_status_line():
    """FORWARD-STABLE form: a STATUS line must exist and name an iteration >= this one.

    Pinning the literal "124" here would turn RED on the next CORRECT iteration (which
    legitimately advances the status line) and the tempting repair would be to delete the
    brake -- the iter-83/84 freeze failure mode. So assert the SHAPE plus a floor.
    """
    text = _index_text()
    status_lines = [l for l in text.splitlines() if l.strip().upper().startswith("STATUS")]
    assert status_lines, (
        "no STATUS line replaced the stale IN FLIGHT sentence")
    numbers = [int(n) for l in status_lines for n in re.findall(r"\d{1,4}", l)]
    assert any(n >= THIS_ITER for n in numbers), (
        "the STATUS line is stale -- it names %r, nothing >= iteration %d: %r"
        % (numbers, THIS_ITER, status_lines[:3]))


def test_b9_pm_card_duty_3_tells_the_pm_to_record_its_own_iteration():
    text = _PM_CARD.read_text(encoding="utf-8")
    low = text.lower()
    assert "record your own iteration" in low, "roles/pm.md does not mandate the own-record"
    assert "never defer" in low, "roles/pm.md does not forbid deferring the record"
    assert "PLATFORM_ROADMAP.md" in text and "PLATFORM_ROADMAP_ARCHIVE.md" in text, (
        "roles/pm.md duty 3 does not name BOTH roadmap files")
    assert "- iter N " in text and "- **iter N " in text, (
        "roles/pm.md duty 3 does not name both record shapes")


# ==========================================================================
# Behavior 10 -- no new CLI verb: the SUITE is the pedal
# ==========================================================================
def test_b10_no_new_cli_verb():
    r = subprocess.run([sys.executable, str(_ROOT / "foundry.py"), "--help"],
                       cwd=str(_ROOT), capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, "foundry.py --help failed: %s" % (r.stderr or "")[-500:]
    out = r.stdout
    # Named in the spec's Out of Scope; matched as a VERB token, not as the bare word
    # "roadmap", so a future help epilog may still mention the roadmap in prose.
    assert "roadmap-check" not in out, "a roadmap-check CLI verb was added: %r" % out[:400]
    for name in NEW_NAMES:
        assert name.replace("_", "-") not in out, "%s became a CLI verb" % name
    assert "{run,once,doctor" in out, "the verb list is missing from --help: %r" % out[:200]


def test_b10_unknown_verb_is_still_rejected():
    r = subprocess.run([sys.executable, str(_ROOT / "foundry.py"), "not-a-real-verb-xyz"],
                       cwd=str(_ROOT), capture_output=True, text=True, timeout=180)
    assert r.returncode != 0, "foundry.py accepted an unknown verb"
