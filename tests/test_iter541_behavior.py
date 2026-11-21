"""Black-box behaviour tests for iter 541 -- `roles/pm.md` duty 0a ("resume
before feature": consult `foundry.py resumable` and re-land the lowest OPEN
row) plus the RESUMABLE.md `exclude:` rider that names the product's own
roadmap file.

ISOLATION CONTRACT (honored): written solely from the iter-541 PM spec's
Expected Behaviors (1-9), the README, the conventions under `tests/`, the role
card text the spec names, and the product's OBSERVABLE runtime interface
(public names, CLI output). The implementation source, the engineer's and
reviewer's notes and `git diff` were not read.  HEAD comparisons use
`git show HEAD:<path>` and ast segment equality only (no reading for design).

Fully offline: every config and state dir is built under tmp_path; no ambient
products/*/state path is asserted.  HEAD-keyed arms skip when no git is
available (e.g. a `git archive` copy) and pass trivially after the ship commit
-- the lasting signal comes from the content arms.
"""
import ast
import difflib
import functools
import importlib.util
import io
import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
import foundry  # noqa: E402
from _shared import source_segment, split_source_lines  # noqa: E402

PM_CARD = REPO / "roles" / "pm.md"
PATCH = "ABORTED_IMPLEMENTATION.patch"
APPROVE = "Review notes.\n\nVERDICT: APPROVE\n"
PASS = "Tests ok.\n\nRESULT: PASS\n"

# HEAD (iter 540) template for the bite-1 fixture row, hard-coded verbatim.
EXPECTED_PLATFORM_FLAG = (
    "# RESUMABLE -- iter-9: an approved + tested tree was reverted with no ship decision\n"
    "\n"
    "patch: state/iter-9/ABORTED_IMPLEMENTATION.patch\n"
    "review: VERDICT: APPROVE\n"
    "tester: tester.md RESULT: PASS\n"
    "exclude: DIRECTIONS.md and the roadmap ledger rows (PLATFORM_ROADMAP.md / "
    "PLATFORM_ROADMAP_ARCHIVE.md) -- re-write them for the landing iteration\n"
    "\n"
    "RESUMABLE: iter-9\n"
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _card():
    return PM_CARD.read_text(encoding="utf-8")


def _head(relpath):
    try:
        proc = subprocess.run(["git", "-C", str(REPO), "show", f"HEAD:{relpath}"],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _head_or_skip(relpath):
    text = _head(relpath)
    if text is None:
        pytest.skip("no git HEAD available")
    return text


def _duties_lines(text):
    """(offset, line) pairs of the `## Duties` section, keepends."""
    out, off, inside = [], 0, False
    for ln in text.splitlines(True):
        if ln.startswith("## "):
            inside = ln.strip() == "## Duties"
        elif inside:
            out.append((off, ln))
        off += len(ln)
    return out


def _starts(text, prefix):
    return [off for off, ln in _duties_lines(text) if ln.startswith(prefix)]


def _first(text, prefix):
    offs = _starts(text, prefix)
    assert offs, f"no line starting {prefix!r} in ## Duties"
    return offs[0]


def _segment(text, start_prefix, end_prefix):
    a = _first(text, start_prefix)
    b = _first(text, end_prefix)
    assert a < b
    return text[a:b]


def _duty_0a(text=None):
    return _segment(text if text is not None else _card(), "0a. ", "0b. ")


def _is_subsequence(needles, hay):
    it = iter(hay)
    return all(any(n == h for h in it) for n in needles)


def _write_cfg(tmp_path, name="demoprod", roadmap=None):
    base = pathlib.Path(tmp_path) / name
    base.mkdir(parents=True, exist_ok=True)
    data = {
        "name": name,
        "repo": str(base / "repo"),
        "allowed_push_repo": name,
        "vision": str(base / "VISION.md"),
        "work_root": str(base / "work"),
    }
    if roadmap is not None:
        data["roadmap"] = roadmap
    p = base / "config.json"
    p.write_text(json.dumps(data))
    return p, base / "work"


def _iter_dir(work, name, files):
    d = work / "state" / name
    d.mkdir(parents=True, exist_ok=True)
    for fname, text in files.items():
        (d / fname).write_text(text)
    return d


def _candidate_files():
    return {PATCH: "diff --git a/x b/x\n", "reviewer.md": APPROVE, "tester.md": PASS}


def _open_row(tmp_path, roadmap=None):
    cfg_path, work = _write_cfg(tmp_path, roadmap=roadmap)
    _iter_dir(work, "iter-9", _candidate_files())
    cfg = foundry.load_config(str(cfg_path))
    rows = [r for r in foundry.gather_resumable(cfg).rows if r.open]
    assert len(rows) == 1 and rows[0].iteration == 9
    return cfg, rows[0], work


def _capture(fn, *a, **k):
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        try:
            rc = fn(*a, **k)
        except SystemExit as e:
            rc = e.code
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _exclude_line(text):
    lines = [ln for ln in text.splitlines() if ln.startswith("exclude:")]
    assert len(lines) == 1, text
    return lines[0]


# --------------------------------------------------------------------------
# Behavior 1 -- duty 0a exists and is ordered
# --------------------------------------------------------------------------
def test_b1_duty_0a_exists_in_duties():
    assert len(_starts(_card(), "0a. ")) == 1


def test_b1_duty_0a_ordered():
    text = _card()
    o0, o0a, o0b, o1 = (_first(text, p) for p in ("0. ", "0a. ", "0b. ", "1. "))
    assert o0 < o0a < o0b
    assert o0a < o1


def test_b1_prefixes_not_confused():
    # "0. ", "0a. ", "0b. " must be distinct lines (prefix check, not substring find)
    text = _card()
    offs = {p: _first(text, p) for p in ("0. ", "0a. ", "0b. ")}
    assert len(set(offs.values())) == 3


# --------------------------------------------------------------------------
# Behavior 2 -- duty 0a names the command and its exit codes
# --------------------------------------------------------------------------
@pytest.mark.parametrize("needle", [
    "foundry.py resumable --config PRODUCT_CONFIG",
    "Exit 1",
    "OPEN",
    "LOWEST",
    "ONLY feature",
    "RESUMABLE.md",
    "git apply --check",
    "exclude:",
    "RESUMES: iter-N",
    "Exit 0 or 2",
])
def test_b2_duty_0a_contains(needle):
    seg = _duty_0a()
    # tolerate the card's hard line wraps for multi-word literals
    flat = " ".join(seg.split())
    assert needle in seg or needle in flat


def test_b2_needles_absent_from_a_mutated_card():
    text = _card()
    seg = _duty_0a(text)
    mutated = text.replace(seg, "0a. **Second: resume.** placeholder\n", 1)
    assert "git apply --check" not in _duty_0a(mutated)
    assert "RESUMES: iter-N" not in _duty_0a(mutated)


# --------------------------------------------------------------------------
# Behavior 3 -- hotfix still wins; duty 0 byte-identical to HEAD
# --------------------------------------------------------------------------
def test_b3_hotfix_wins_in_0a():
    seg = _duty_0a()
    assert "hotfix" in seg
    assert "wins" in seg


def test_b3_duty_0_byte_identical_to_head():
    head = _head_or_skip("roles/pm.md")
    text = _card()
    now0 = _segment(text, "0. ", "0a. ")
    # HEAD has no 0a, so its duty 0 ends at the next duty heading (0b.)
    head0 = head[_first(head, "0. "):min(o for o in (_starts(head, "0a. ") + _starts(head, "0b. ")))]
    assert now0 == head0


def test_b3_duty_0_unchanged_content_marker():
    seg = _segment(_card(), "0. ", "0a. ")
    assert "Only when no flag is present do you pick a roadmap feature below." in seg


# --------------------------------------------------------------------------
# Behavior 4 -- override list in duty 1b
# --------------------------------------------------------------------------
def test_b4_1b_mentions_0a_and_resumable():
    seg = _segment(_card(), "1b. ", "2. ")
    assert "0a" in seg
    assert "resumable" in seg


def test_b4_1b_head_lines_preserved_in_order():
    head = _head_or_skip("roles/pm.md")
    head_lines = _segment(head, "1b. ", "2. ").splitlines()
    now_lines = _segment(_card(), "1b. ", "2. ").splitlines()
    assert _is_subsequence(head_lines, now_lines)


def test_b4_override_sentence_text():
    flat = " ".join(_segment(_card(), "1b. ", "2. ").split())
    assert "Duties 0 and 0a outrank all of this" in flat


# --------------------------------------------------------------------------
# Behavior 5 -- the verb is taught and real
# --------------------------------------------------------------------------
def _cli_verbs():
    return foundry.foundry_cli_verbs((REPO / "foundry.py").read_text(encoding="utf-8"))


def test_b5_pm_card_teaches_resumable():
    assert "resumable" in foundry.role_card_verbs(_card())


def test_b5_resumable_is_a_cli_verb():
    assert "resumable" in _cli_verbs()


def test_b5_no_verb_gaps():
    assert foundry.role_card_verb_gaps(_card(), _cli_verbs()) == ()


# --------------------------------------------------------------------------
# Behavior 6 -- additive card edit; no other role card moved
# --------------------------------------------------------------------------
def test_b6_pm_card_edit_is_insert_only():
    head = _head_or_skip("roles/pm.md").splitlines(True)
    now = _card().splitlines(True)
    ops = {tag for tag, *_ in difflib.SequenceMatcher(None, head, now, autojunk=False).get_opcodes()}
    assert ops <= {"equal", "insert"}, ops


def _pre_ship_scope_live():
    """True only while iter 541's own ledger row is not yet in HEAD's roadmap.

    WHY: "no other role card differs" is a worktree scope check for iter 541's
    edit. Once 541 ships, a LATER iteration's legitimate role-card edit must
    not turn it red (the test_iter379 pattern; iter 550 gated it)."""
    return "- iter 541 " not in (_head("PLATFORM_ROADMAP.md") or "")


def test_b6_no_other_role_card_differs():
    if _head("roles/pm.md") is None:
        pytest.skip("no git HEAD available")
    if not _pre_ship_scope_live():
        pytest.skip("iter 541 already shipped; scope check is inert")
    proc = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "roles"],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0
    changed = [ln[3:].strip() for ln in proc.stdout.splitlines() if ln.strip()]
    assert [c for c in changed if c != "roles/pm.md"] == []


# --------------------------------------------------------------------------
# Behavior 7 -- flag names the product's roadmap
# --------------------------------------------------------------------------
def test_b7_product_md_roadmap(tmp_path):
    cfg, row, work = _open_row(tmp_path, roadmap=str(tmp_path / "proj" / "PRODUCT.md"))
    path = foundry.write_resumable_flag(cfg, row)
    assert path is not None and pathlib.Path(path).is_file()
    excl = _exclude_line(pathlib.Path(path).read_text())
    assert "DIRECTIONS.md" in excl
    assert "PRODUCT.md" in excl
    assert "roadmap" in excl
    assert "PLATFORM_ROADMAP" not in excl


def test_b7_roadmap_md_in_subdir(tmp_path):
    cfg, row, work = _open_row(tmp_path, roadmap=str(tmp_path / "proj" / "docs" / "ROADMAP.md"))
    text = pathlib.Path(foundry.write_resumable_flag(cfg, row)).read_text()
    excl = _exclude_line(text)
    assert "ROADMAP.md" in excl and "PLATFORM_ROADMAP" not in excl
    assert str(tmp_path) not in text  # no absolute path leaks


def test_b7_only_exclude_line_differs(tmp_path):
    cfg, row, work = _open_row(tmp_path, roadmap=str(tmp_path / "PRODUCT.md"))
    text = pathlib.Path(foundry.write_resumable_flag(cfg, row)).read_text()
    a = [ln for ln in text.splitlines() if not ln.startswith("exclude:")]
    b = [ln for ln in EXPECTED_PLATFORM_FLAG.splitlines() if not ln.startswith("exclude:")]
    assert a == b


# --------------------------------------------------------------------------
# Behavior 8 -- _platform flag text byte-identical
# --------------------------------------------------------------------------
def test_b8_render_default_byte_identical(tmp_path):
    cfg, row, work = _open_row(tmp_path)
    assert foundry.render_resumable_flag(row) == EXPECTED_PLATFORM_FLAG


def test_b8_platform_roadmap_config_byte_identical(tmp_path):
    cfg, row, work = _open_row(tmp_path, roadmap=str(tmp_path / "x" / "PLATFORM_ROADMAP.md"))
    path = foundry.write_resumable_flag(cfg, row)
    assert pathlib.Path(path).read_text() == EXPECTED_PLATFORM_FLAG


def test_b8_empty_roadmap_falls_back(tmp_path):
    cfg, row, work = _open_row(tmp_path, roadmap="")
    path = foundry.write_resumable_flag(cfg, row)
    assert pathlib.Path(path).read_text() == EXPECTED_PLATFORM_FLAG


def test_b8_matches_head_module(tmp_path):
    src = _head_or_skip("foundry.py")
    hp = tmp_path / "foundry_head_copy.py"
    hp.write_text(src)
    spec = importlib.util.spec_from_file_location("foundry_head_copy_541", hp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["foundry_head_copy_541"] = mod
    try:
        spec.loader.exec_module(mod)
        cfg, row, work = _open_row(tmp_path / "f")
        hrow = mod.ResumableRow(**{f: getattr(row, f) for f in row._fields}) \
            if hasattr(row, "_fields") else row
        assert mod.render_resumable_flag(hrow) == foundry.render_resumable_flag(row)
    finally:
        sys.modules.pop("foundry_head_copy_541", None)


# --------------------------------------------------------------------------
# Behavior 9 -- no other surface moves
# --------------------------------------------------------------------------
PINNED_DEFS = ("run_iteration", "build_prompt", "capture_abort_patch",
               "gather_resumable", "resumable_open")


@functools.lru_cache(maxsize=4)
def _defs(src):
    """Top-level def/class name -> source segment, last name wins.

    WHY split once + memoize: the stdlib segment call re-splits the whole
    source per node, which made the 5 b9 params cost ~16 s each on the
    ~32k-line foundry.py. The cache key is the source TEXT, never a path, so
    an edited worktree is a new key and can never be served a stale map. The
    shared cached dict is read-only by contract; callers only index it.
    """
    tree = ast.parse(src)
    lines = split_source_lines(src)
    return {n.name: source_segment(lines, n) for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


@pytest.mark.parametrize("name", PINNED_DEFS)
def test_b9_pinned_def_unchanged(name):
    head = _defs(_head_or_skip("foundry.py"))
    now = _defs((REPO / "foundry.py").read_text(encoding="utf-8"))
    assert name in now and name in head
    assert now[name] == head[name]


def test_b9_dispatcher_unchanged():
    head = _head_or_skip("dispatcher.py")
    assert (REPO / "dispatcher.py").read_text(encoding="utf-8") == head


def _mixed(root):
    cfg_path, work = _write_cfg(root)
    _iter_dir(work, "iter-5", _candidate_files())
    _iter_dir(work, "iter-7", {"final.md": "Shipped.\n\nACTION: PUSHED abc123\n"})
    _iter_dir(work, "iter-9", _candidate_files())
    return cfg_path


@pytest.mark.parametrize("flags", [(), ("--json",)])
def test_b9_cli_output_matches_head(tmp_path, flags):
    src = _head_or_skip("foundry.py")
    hp = tmp_path / "foundry_head_cli.py"
    hp.write_text(src)
    spec = importlib.util.spec_from_file_location("foundry_head_cli_541", hp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["foundry_head_cli_541"] = mod
    try:
        spec.loader.exec_module(mod)
        cfg_path = _mixed(tmp_path / "m")
        argv = ["resumable", "--config", str(cfg_path), *flags]
        now = _capture(foundry.main, list(argv))
        then = _capture(mod.main, list(argv))
    finally:
        sys.modules.pop("foundry_head_cli_541", None)
    assert now[0] == then[0] == 1
    assert now[1] == then[1]
    assert "iter-9" in now[1]


def test_b9_cli_mixed_fixture_observable(tmp_path):
    cfg_path = _mixed(tmp_path)
    rc, out, _ = _capture(foundry.main, ["resumable", "--config", str(cfg_path), "--json"])
    assert rc == 1
    rows = json.loads(out)["rows"]
    assert {r["iteration"]: r["open"] for r in rows} == {5: False, 9: True}


def test_b9_imports():
    proc = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                          cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
