"""Black-box behaviour tests for iter 548 -- HOTFIX (OPERATOR 2026-11-18b).

test_iter154 b3 counts git spawns instead of reading a clock, and
postrelease.md records the machine load average in a `- load_avg:` line.

ISOLATION: written from the iter-548 PM spec (Expected Behaviors 1-8), the
existing tests under tests/, and the product's public surface (calling its
functions, AST-level structure of tracked files). The implementation source of
foundry.py, the engineer/reviewer notes and `git diff` were NOT read.

Ship-hazard notes: no commit sha / line number is pinned (H1), no wall-clock
bound is asserted (H2), no optional extra is imported (H3). Ambient load and
core count are never asserted: os.getloadavg / os.cpu_count / _load_avg_text are
scripted through monkeypatch. The HEAD comparisons are written so they still
hold after the ship commit makes HEAD == worktree.
"""
import ast
import hashlib
import importlib.util
import inspect
import os
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tests"))
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import test_iter61_behavior as t61  # noqa: E402
import test_iter154_behavior as t154  # noqa: E402

_T154 = _ROOT / "tests" / "test_iter154_behavior.py"
_T204 = _ROOT / "tests" / "test_iter204_behavior.py"
_FOUNDRY = _ROOT / "foundry.py"
SHA = "abc123def456"
FAIL_LINE = "FAILED tests/x.py::test_y - boom"
DO_NOT_EDIT = ("run_iteration", "build_prompt", "capture_abort_patch",
               "gather_resumable", "resumable_open", "postrelease_step",
               "verify_fresh_clone")
ALLOWED_CHANGED = {"_write_postrelease_artifact", "_load_avg_text"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _has_git():
    if not (_ROOT / ".git").exists():
        return False
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(_ROOT),
                       capture_output=True, text=True, check=False)
    return r.returncode == 0


needs_git = pytest.mark.skipif(not _has_git(), reason="needs a git checkout")


def _head_text(rel):
    r = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=str(_ROOT),
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, f"git show HEAD:{rel} failed: {r.stderr!r}"
    return r.stdout


def _top_defs(src):
    tree = ast.parse(src)
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = ast.dump(node)
    return out


def _fn_node(src, name):
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _artifact_text(tmp_path, result, mod=foundry, name="pr.md"):
    p = tmp_path / name
    mod._write_postrelease_artifact(p, SHA, result)
    return p.read_text(encoding="utf-8")


def _last_nonempty(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def spawn_count_ok(argvs, calls):
    """Local replica of b3's predicate (spec behaviors 2+3): exactly 2 spawns per
    snapshot, all git, subcommands ("status", "ls-files") * calls."""
    return (len(argvs) == 2 * calls
            and all(a and a[0] == "git" for a in argvs)
            and tuple(a[1] for a in argvs) == ("status", "ls-files") * calls)


def _results():
    return (
        foundry.PostReleaseResult(True, False, "green", 4.2),
        foundry.PostReleaseResult(False, False, "fresh-clone test suite failed",
                                  12.5, (FAIL_LINE, "ERROR tests/z.py")),
        foundry.PostReleaseResult(True, True, "clone failed"),
        foundry.PostReleaseResult(False, False, "boom"),
    )


# ==========================================================================
# Behavior 1 -- b3 reads no clock
# ==========================================================================
def test_b1_b3_reads_no_clock():
    src = _T154.read_text(encoding="utf-8")
    tree = ast.parse(src)
    assigned = set()
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for t in targets:
            if isinstance(t, ast.Name):
                assigned.add(t.id)
    assert "_CALLS_BUDGET_S" not in assigned, "module must no longer define _CALLS_BUDGET_S"
    assert not hasattr(t154, "_CALLS_BUDGET_S")
    fn = _fn_node(src, "test_b3_snapshot_is_cheap")
    assert fn is not None, "test_b3_snapshot_is_cheap must still exist"
    body = ast.get_source_segment(src, fn) or ""
    for tok in ("time.monotonic", "time.time", "perf_counter", "elapsed"):
        assert tok not in body, f"b3 body still contains clock token {tok!r}"


def test_b1_time_import_dropped_or_still_used():
    src = _T154.read_text(encoding="utf-8")
    tree = ast.parse(src)
    imports_time = any(
        isinstance(n, ast.Import) and any(a.name == "time" for a in n.names)
        for n in tree.body)
    uses_time = any(isinstance(n, ast.Name) and n.id == "time" for n in ast.walk(tree))
    assert (not imports_time) or uses_time, \
        "`import time` must be dropped when nothing in the module uses it"


# ==========================================================================
# Behaviors 2-4 -- b3 counts spawns through a call-through wrapper
# ==========================================================================
def test_b2_b3_wraps_subprocess_run_with_monkeypatch():
    src = _T154.read_text(encoding="utf-8")
    fn = _fn_node(src, "test_b3_snapshot_is_cheap")
    assert fn is not None
    assert [a.arg for a in fn.args.args] == ["monkeypatch"], \
        "b3 must take pytest's monkeypatch fixture"
    body = ast.get_source_segment(src, fn) or ""
    assert "monkeypatch.setattr(subprocess" in body and '"run"' in body
    assert "2 * _CALLS" in body
    assert t154._CALLS == 20


def test_b2_b3_passes_on_the_real_tree(monkeypatch):
    """b3 goes green on the real tree, and an OUTER recorder (which b3's own
    wrapper calls through to) sees exactly the 40 spawns b3 claims to count."""
    real_run = subprocess.run
    outer = []

    def _outer(argv, *a, **k):
        outer.append(list(argv))
        return real_run(argv, *a, **k)

    monkeypatch.setattr(subprocess, "run", _outer)
    mp = pytest.MonkeyPatch()
    try:
        returned = t154.test_b3_snapshot_is_cheap(mp)
    finally:
        mp.undo()
    monkeypatch.undo()
    assert returned is None
    assert spawn_count_ok(outer, t154._CALLS), f"{len(outer)} outer spawns"


def test_b2_b3_goes_red_on_an_extra_git_call(monkeypatch):
    """Can-fail arm: a snapshot that spawns one extra git call per snapshot makes
    b3 raise AssertionError naming measured and expected counts."""
    real = t61._git_visible_snapshot

    def _extra(root, *a, **k):
        subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(_ROOT),
                       capture_output=True, text=True, check=False)
        return real(root, *a, **k)

    monkeypatch.setattr(t61, "_git_visible_snapshot", _extra)
    inner = pytest.MonkeyPatch()
    try:
        with pytest.raises(AssertionError) as exc:
            t154.test_b3_snapshot_is_cheap(inner)
    finally:
        inner.undo()
    msg = str(exc.value)
    assert "60" in msg and "40" in msg, f"failure must name measured+expected: {msg!r}"


def test_b3_predicate_replica_rejects_wrong_work():
    good = [["git", "status"], ["git", "ls-files"]] * 3
    assert spawn_count_ok(good, 3)
    three = [["git", "status"], ["git", "ls-files"], ["git", "rev-parse"]] * 3
    assert not spawn_count_ok(three, 3)
    swapped = [["git", "ls-files"], ["git", "status"]] * 3
    assert not spawn_count_ok(swapped, 3)
    dropped = [["git", "status"]] * 6
    assert not spawn_count_ok(dropped, 3)
    nongit = [["sh", "status"], ["git", "ls-files"]] * 3
    assert not spawn_count_ok(nongit, 3)


def test_b3_real_snapshot_spawns_status_then_ls_files(monkeypatch):
    real_run = subprocess.run
    argvs = []

    def _rec(argv, *a, **k):
        argvs.append(list(argv))
        return real_run(argv, *a, **k)

    monkeypatch.setattr(subprocess, "run", _rec)
    last = None
    for _ in range(3):
        last = t61._git_visible_snapshot(t154._REAL_PRODUCTS)
    monkeypatch.undo()
    assert spawn_count_ok(argvs, 3), f"unexpected spawns: {argvs!r}"
    # behavior 4: call-through yields a real 2-tuple of tuples
    assert isinstance(last, tuple) and len(last) == 2
    assert all(isinstance(p, tuple) for p in last)


def test_b4_b3_goes_red_on_a_stubbed_snapshot(monkeypatch):
    """If the snapshot returned a non-snapshot while doing the right spawns, b3's
    shape check must fire."""
    real = t61._git_visible_snapshot

    def _bad(root, *a, **k):
        real(root, *a, **k)
        return "not-a-snapshot"

    monkeypatch.setattr(t61, "_git_visible_snapshot", _bad)
    inner = pytest.MonkeyPatch()
    try:
        with pytest.raises(AssertionError):
            t154.test_b3_snapshot_is_cheap(inner)
    finally:
        inner.undo()


# ==========================================================================
# Behavior 5 -- foundry._load_avg_text()
# ==========================================================================
def test_b5_seam_is_module_level_zero_arg():
    fn = foundry.__dict__.get("_load_avg_text")
    assert inspect.isfunction(fn) and fn.__module__ == foundry.__name__
    assert len(inspect.signature(fn).parameters) == 0


def test_b5_formats_scripted_load(monkeypatch):
    monkeypatch.setattr(os, "getloadavg", lambda: (23.8, 30.9, 21.5))
    monkeypatch.setattr(os, "cpu_count", lambda: 12)
    assert foundry._load_avg_text() == "23.80/30.90/21.50 (12 cores)"
    monkeypatch.setattr(os, "getloadavg", lambda: (0.0, 1.005, 2.5))
    monkeypatch.setattr(os, "cpu_count", lambda: 1)
    assert foundry._load_avg_text() == f"{0.0:.2f}/{1.005:.2f}/{2.5:.2f} (1 cores)"


def test_b5_unknown_core_count(monkeypatch):
    monkeypatch.setattr(os, "getloadavg", lambda: (1.0, 2.0, 3.0))
    monkeypatch.setattr(os, "cpu_count", lambda: None)
    assert foundry._load_avg_text() == "1.00/2.00/3.00 (? cores)"


def test_b5_oserror_is_na(monkeypatch):
    def _boom():
        raise OSError("no load average here")

    monkeypatch.setattr(os, "getloadavg", _boom)
    monkeypatch.setattr(os, "cpu_count", lambda: 12)
    assert foundry._load_avg_text() == "n/a"


def test_b5_missing_getloadavg_is_na(monkeypatch):
    monkeypatch.delattr(os, "getloadavg", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 12)
    assert foundry._load_avg_text() == "n/a"


# ==========================================================================
# Behavior 6 -- the artifact carries one `- load_avg:` line in place
# ==========================================================================
def test_b6_signature_kept():
    params = list(inspect.signature(foundry._write_postrelease_artifact).parameters)
    assert params == ["artifact", "expected_sha", "result"]


@pytest.mark.parametrize("idx", range(4))
def test_b6_load_line_via_bare_name_seam(tmp_path, monkeypatch, idx):
    monkeypatch.setattr(foundry, "_load_avg_text", lambda: "X")
    lines = _artifact_text(tmp_path, _results()[idx]).splitlines()
    hits = [i for i, ln in enumerate(lines) if ln.startswith("- load_avg:")]
    assert len(hits) == 1, f"exactly one load_avg line expected: {lines!r}"
    i = hits[0]
    assert lines[i] == "- load_avg: X"
    assert lines[i - 1].startswith("- suite_seconds:"), lines
    assert lines[i + 1].startswith("- detail:"), lines


def test_b6_load_line_uses_scripted_os(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "getloadavg", lambda: (23.8, 30.9, 21.5))
    monkeypatch.setattr(os, "cpu_count", lambda: 12)
    text = _artifact_text(tmp_path, _results()[1])
    assert "- load_avg: 23.80/30.90/21.50 (12 cores)" in text.splitlines()


def test_b6_load_line_na_never_raises(tmp_path, monkeypatch):
    def _boom():
        raise OSError("x")

    monkeypatch.setattr(os, "getloadavg", _boom)
    text = _artifact_text(tmp_path, _results()[0])
    assert "- load_avg: n/a" in text.splitlines()


# ==========================================================================
# Behavior 7 -- rest of the artifact unchanged; parsers unchanged
# ==========================================================================
@pytest.mark.parametrize("idx", range(4))
def test_b7_sentinel_last_and_parsers(tmp_path, monkeypatch, idx):
    monkeypatch.setattr(foundry, "_load_avg_text", lambda: "1.00/2.00/3.00 (4 cores)")
    r = _results()[idx]
    text = _artifact_text(tmp_path, r)
    assert _last_nonempty(text) == r.sentinel
    assert r.sentinel in ("POSTRELEASE: HEALTHY", "POSTRELEASE: BROKEN")
    assert foundry.parse_postrelease_verdict(text) == r.sentinel.split(": ", 1)[1]
    secs = foundry.parse_suite_seconds(text)
    ts = getattr(r, "test_seconds", None)
    if ts is None:
        assert secs is None
    else:
        assert secs == pytest.approx(ts)


@pytest.fixture(scope="module")
def head_foundry(tmp_path_factory):
    if not _has_git():
        pytest.skip("needs a git checkout")
    d = tmp_path_factory.mktemp("head_foundry")
    p = d / "foundry_head548.py"
    p.write_text(_head_text("foundry.py"), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("foundry_head548", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["foundry_head548"] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop("foundry_head548", None)
    return mod


def _strip_load(text):
    return [ln for ln in text.splitlines() if not ln.startswith("- load_avg:")]


@pytest.mark.parametrize("idx", range(4))
def test_b7_byte_identical_to_head_minus_load_line(tmp_path, monkeypatch, head_foundry, idx):
    monkeypatch.setattr(foundry, "_load_avg_text", lambda: "9.99/9.99/9.99 (1 cores)")
    if hasattr(head_foundry, "_load_avg_text"):
        monkeypatch.setattr(head_foundry, "_load_avg_text",
                            lambda: "9.99/9.99/9.99 (1 cores)")
    r = _results()[idx]
    rh = head_foundry.PostReleaseResult(r.healthy, r.skipped_infra, r.detail,
                                        r.test_seconds, r.failures)
    new = _artifact_text(tmp_path, r, foundry, "new.md")
    old = _artifact_text(tmp_path, rh, head_foundry, "old.md")
    assert _strip_load(new) == _strip_load(old)
    assert foundry.parse_postrelease_verdict(new) == head_foundry.parse_postrelease_verdict(old)
    assert foundry.parse_suite_seconds(new) == head_foundry.parse_suite_seconds(old)


# ==========================================================================
# Behavior 8 -- nothing else changed; seam has one caller
# ==========================================================================
def test_b8_load_avg_text_called_only_from_artifact_writer():
    tree = ast.parse(_FOUNDRY.read_text(encoding="utf-8"))
    callers = set()
    for top in tree.body:
        for node in ast.walk(top):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (
                f.attr if isinstance(f, ast.Attribute) else None)
            if name == "_load_avg_text":
                callers.add(getattr(top, "name", "<module>"))
    assert callers == {"_write_postrelease_artifact"}, callers


def _pre_ship_scope_live():
    """True only while iter 548's own ledger row is not yet in HEAD's roadmap.

    WHY: "only the allowed defs changed vs HEAD" is a scope check for THIS
    iteration's edit. Once 548 ships, HEAD carries its row and a LATER
    iteration's legitimate code edit must not turn this red (the test_iter379
    pattern; iter 550 gated it)."""
    return "- iter 548 " not in _head_text("PLATFORM_ROADMAP.md")


@needs_git
def test_b8_changed_defs_within_allowed_set():
    if not _pre_ship_scope_live():
        pytest.skip("iter 548 already shipped; scope check is inert")
    head = _top_defs(_head_text("foundry.py"))
    work = _top_defs(_FOUNDRY.read_text(encoding="utf-8"))
    changed = {n for n in set(head) | set(work) if head.get(n) != work.get(n)}
    assert changed <= ALLOWED_CHANGED, f"unexpected changed defs: {sorted(changed - ALLOWED_CHANGED)}"
    for name in DO_NOT_EDIT:
        assert name in work, f"{name} missing from foundry.py"
        assert head.get(name) == work[name], f"DO-NOT-EDIT def {name} changed"


@needs_git
def test_b8_dispatcher_untouched():
    head = _head_text("dispatcher.py").encode("utf-8")
    work = (_ROOT / "dispatcher.py").read_bytes()
    assert hashlib.sha256(head).hexdigest() == hashlib.sha256(work).hexdigest()


def test_b8_iter204_row_for_forced_edit_sits_above_iter541_row():
    text = _T204.read_text(encoding="utf-8")
    row154 = '"tests/test_iter154_behavior.py"'
    row541 = '"tests/test_iter541_behavior.py"'
    assert row154 in text and row541 in text
    i154 = text.index(row154)
    i541 = text.index(row541)
    assert i154 < i541, "iter 548 row must sit ABOVE the iter 544 last-member row"
    window = text[max(0, i154 - 800):i154]
    assert "# iter 548:" in window, "the row needs its `# iter 548:` comment"


def test_b8_no_newest_ness_pin_in_forced_edit_file():
    import test_iter204_behavior as t204
    src = _T154.read_text(encoding="utf-8")
    assert t204.newest_ness_pin_sites({_T154.name: src}) == ()
    if _has_git():
        head_src = _head_text("tests/test_iter154_behavior.py")
        assert t204.newest_ness_pin_sites({_T154.name: head_src}) == ()


def test_b8_foundry_and_dispatcher_importable():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
