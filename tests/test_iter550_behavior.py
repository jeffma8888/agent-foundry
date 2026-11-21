"""Iteration 550 (OPERATOR 2026-11-18c pin RETRY of reverted iter 549) -- BLACK-BOX behavior tests: when the clean-clone suite fails,
`foundry preship` names the failing test ids (OPERATOR 2026-11-18c) in its text report
and in `--json` (`failing_tests`), reusing post-release's `test_failure_lines` cap and
`_failure_bullets` rendering.  Exit codes and the verdict are unchanged.

Spec under test: products/_platform/state/iter-550/pm.md, Expected Behaviors 1-11.

ISOLATION HONORED: written from `pm.md`, the repo's own `tests/` conventions (chiefly
tests/test_iter517_behavior.py's scripted-seam harness) and the product's RUNTIME
surface (public names, signatures, dataclass fields, CLI stdout) ONLY.  No
implementation source, no engineer / reviewer note and no `git diff` output was read.
The HEAD-comparison arms import the HEAD revision of foundry.py as a second module and
compare RUNTIME outputs only.

OFFLINE: every external effect of the behaviors under test goes through scripted
`run_cmd` / `cleanup_clone` / `_monotonic` stand-ins set by BARE module name.  The only
real subprocesses are the gated HEAD-revision reads (skipped when the checkout has no git
history) and nothing else.

FRESH-CLONE SAFE: every fixture lives under `tmp_path`; nothing asserts on gitignored
state, a commit sha, or a line number.  Every HEAD-baseline arm goes through the
`head_foundry` fixture, which SKIPS once HEAD's roadmap index or archive carries iter 550
(549's eb6 diffed against HEAD and went red the moment its own ship commit landed).
"""
from __future__ import annotations

import contextlib
import dataclasses
import importlib.util
import inspect
import io
import itertools
import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

SHA = "b" * 40
PARENT = "a" * 40
INTERP = "/opt/py/cpython-3.14.4-macos/bin/python3.14"
PARENT_DIR_NAME = "preship_parent_clone"

ID_A = "FAILED tests/test_a.py::test_x - AssertionError"
ID_B = "ERROR tests/test_b.py::test_y - RuntimeError: boom"
_SUMMARY_HDR = "=========================== short test summary info ============================"

EXISTING_KEYS = ["verified", "incomplete", "exit_code", "detail", "sentinel",
                 "test_seconds", "verified_sha", "worktree_scope"]


def _out(lines, tail="2 failed, 10 passed in 3.21s"):
    return "\n".join(["collected 12 items", "", "=== FAILURES ===", "___ test_x ___",
                      "E   assert 1 == 2", _SUMMARY_HDR] + list(lines) + [
                      "=" * 20 + " " + tail + " " + "=" * 20]) + "\n"


RED_OUT = _out([ID_A, ID_B])


def _broken(out=RED_OUT, detail=None, **kw):
    return foundry.PreshipResult(
        verified=False, incomplete=False,
        detail=foundry.PRESHIP_SUITE_FAILED_DETAIL if detail is None else detail,
        suite_output=out, **kw)


def _nonempty(text):
    return [ln for ln in text.splitlines() if ln.strip()]


def _last(text):
    return _nonempty(text)[-1]


# --------------------------------------------------------------------------
# HEAD module (second import of the HEAD revision of foundry.py) -- GATED
# --------------------------------------------------------------------------
def _head_text(rel):
    try:
        proc = subprocess.run(["git", "-C", str(_ROOT), "show", "HEAD:" + rel],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def _pre_ship_scope_live():
    return ("- iter 550 " not in _head_text("PLATFORM_ROADMAP.md")
            and "- **iter 550 " not in _head_text("PLATFORM_ROADMAP_ARCHIVE.md"))


@pytest.fixture(scope="module")
def head_foundry(tmp_path_factory):
    if not _pre_ship_scope_live():
        pytest.skip("iter 550 already shipped; HEAD baseline is no longer the pre-change tree")
    try:
        proc = subprocess.run(["git", "-C", str(_ROOT), "show", "HEAD:foundry.py"],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        pytest.skip("git unavailable: %s" % exc)
    if proc.returncode != 0 or not proc.stdout.strip():
        pytest.skip("no git history (archive copy?)")
    d = tmp_path_factory.mktemp("head_foundry")
    path = d / "foundry_head_iter550.py"
    path.write_text(proc.stdout, encoding="utf-8")
    name = "foundry_head_iter550"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    yield mod
    sys.modules.pop(name, None)


def _head_result(head, res):
    """Rebuild `res` field-for-field in the HEAD module."""
    kw = {f.name: getattr(res, f.name) for f in dataclasses.fields(res)}
    return head.PreshipResult(**kw)


# ==========================================================================
# Acceptance -- property, not a field
# ==========================================================================
def test_ac_failing_tests_is_a_read_only_property():
    attr = inspect.getattr_static(foundry.PreshipResult, "failing_tests")
    assert isinstance(attr, property)
    assert attr.fset is None
    names = [f.name for f in dataclasses.fields(foundry.PreshipResult)]
    assert "failing_tests" not in names
    assert len(names) == 7
    assert names[-2:] == ["verified_sha", "worktree_scope"]


def test_ac_dataclass_fields_unchanged_from_head(head_foundry):
    now = [(f.name, f.default) for f in dataclasses.fields(foundry.PreshipResult)]
    then = [(f.name, f.default) for f in dataclasses.fields(head_foundry.PreshipResult)]
    assert now == then


def test_ac_failing_tests_cannot_be_assigned():
    r = _broken()
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        r.failing_tests = ("x",)


# ==========================================================================
# EB1 -- ids in output order
# ==========================================================================
def test_eb1_broken_lists_failed_and_error_ids_in_order():
    r = _broken()
    assert r.exit_code == 1
    assert r.failing_tests == (ID_A, ID_B)
    assert isinstance(r.failing_tests, tuple)


def test_eb1_order_follows_the_output_not_sorting():
    r = _broken(out=_out([ID_B, ID_A]))
    assert r.failing_tests == (ID_B, ID_A)


def test_eb1_equals_test_failure_lines_of_the_suite_output():
    r = _broken()
    assert r.failing_tests == foundry.test_failure_lines(RED_OUT)


# ==========================================================================
# EB2 -- render(): bullets above the sentinel
# ==========================================================================
def test_eb2_render_lists_ids_under_a_failing_tests_bullet_above_sentinel():
    text = _broken().render()
    lines = text.splitlines()
    assert "- failing tests:" in lines, text
    i = lines.index("- failing tests:")
    assert lines[i + 1] == "  - " + ID_A
    assert lines[i + 2] == "  - " + ID_B
    s = lines.index("PRESHIP: BROKEN")
    assert i < s and i + 2 < s
    assert _last(text) == "PRESHIP: BROKEN"
    assert text.count("PRESHIP:") == 1


def test_eb2_block_sits_after_exit_code_line():
    lines = _broken().render().splitlines()
    ec = next(i for i, ln in enumerate(lines) if ln.startswith("  exit code:"))
    assert lines[ec + 1] == "- failing tests:"


def test_eb2_block_matches_failure_bullets_rendering():
    text = _broken().render()
    block = foundry._failure_bullets("failing tests:", (ID_A, ID_B))
    assert block and block.strip() in text


def test_eb2_ids_never_leak_into_detail():
    r = _broken()
    assert r.detail == foundry.PRESHIP_SUITE_FAILED_DETAIL
    assert ID_A not in r.detail


# ==========================================================================
# EB3 -- to_dict(): 9 keys, failing_tests last, JSON round-trip
# ==========================================================================
def test_eb3_to_dict_has_nine_keys_failing_tests_last():
    d = _broken(test_seconds=4.5, verified_sha=SHA, worktree_scope="clean").to_dict()
    assert list(d) == EXISTING_KEYS + ["failing_tests"], list(d)
    assert len(d) == 9
    assert d["failing_tests"] == [ID_A, ID_B]
    assert d["exit_code"] == 1 and d["sentinel"] == "PRESHIP: BROKEN"
    assert d["detail"] == foundry.PRESHIP_SUITE_FAILED_DETAIL
    assert d["test_seconds"] == 4.5 and d["verified_sha"] == SHA
    assert d["worktree_scope"] == "clean"
    assert "suite_output" not in d


def test_eb3_json_round_trip():
    d = _broken().to_dict()
    assert json.loads(json.dumps(d)) == d


def test_eb3_existing_values_equal_head(head_foundry):
    r = _broken(test_seconds=4.5, verified_sha=SHA, worktree_scope="clean")
    now = r.to_dict()
    then = _head_result(head_foundry, r).to_dict()
    for k in then:
        if k == "failing_tests":
            continue
        assert now[k] == then[k], k
    assert set(now) - set(then) <= {"failing_tests"}


# ==========================================================================
# EB4 -- cap: first 10 ids + "... and N more", each cut to 300 chars
# ==========================================================================
def test_eb4_thirteen_failures_capped_at_ten_plus_more_line():
    lines = ["FAILED tests/t.py::test_%02d" % i for i in range(13)]
    r = _broken(out=_out(lines))
    ft = r.failing_tests
    assert len(ft) == 11
    assert list(ft[:10]) == lines[:10]
    assert "3 more" in ft[10] and ft[10].startswith("...")
    assert ft == foundry.test_failure_lines(_out(lines))
    assert r.to_dict()["failing_tests"] == list(ft)


def test_eb4_each_id_cut_to_line_max():
    assert foundry.TEST_FAILURE_LINE_MAX == 300
    long_id = "FAILED tests/test_deep.py::test_param[" + "x" * 400 + "] - AssertionError"
    r = _broken(out=_out([long_id, ID_B]))
    ft = r.failing_tests
    assert len(ft) == 2
    assert len(ft[0]) <= foundry.TEST_FAILURE_LINE_MAX
    assert long_id.startswith(ft[0].rstrip(".…")[:250])
    assert ft == foundry.test_failure_lines(_out([long_id, ID_B]))
    assert all(len(x) <= foundry.TEST_FAILURE_LINE_MAX for x in ft)


# ==========================================================================
# EB5 -- VERIFIED / INCOMPLETE never list ids
# ==========================================================================
def _verified(out=RED_OUT):
    return foundry.PreshipResult(verified=True, incomplete=False, detail="ok",
                                 suite_output=out, verified_sha=SHA)


def _incomplete(out=RED_OUT):
    return foundry.PreshipResult(verified=False, incomplete=True,
                                 detail="parent fails the same: " + ID_A,
                                 suite_output=out)


@pytest.mark.parametrize("make,code", [(_verified, 0), (_incomplete, 2)])
def test_eb5_non_broken_results_have_no_failing_tests(make, code):
    r = make()
    assert r.exit_code == code
    assert r.failing_tests == ()
    assert r.to_dict()["failing_tests"] == []
    assert "failing tests:" not in r.render()


@pytest.mark.parametrize("make", [_verified, _incomplete])
def test_eb5_render_byte_identical_to_head(head_foundry, make):
    r = make()
    assert r.render() == _head_result(head_foundry, r).render()


# ==========================================================================
# EB6 -- BROKEN without a failure summary line
# ==========================================================================
@pytest.mark.parametrize("out", [None, "", "collected 3 items\n3 errors in 0.1s\n",
                                 "=== FAILURES ===\n1 failed in 0.2s\n"])
def test_eb6_broken_without_summary_lines_has_no_block(out):
    r = _broken(out=out)
    assert r.exit_code == 1
    assert r.failing_tests == ()
    assert "failing tests:" not in r.render()
    assert _last(r.render()) == "PRESHIP: BROKEN"
    assert r.to_dict()["failing_tests"] == []


def test_eb6_sha_mismatch_style_broken_no_block():
    r = _broken(out=None, detail="clone HEAD does not match the commit about to be pushed")
    assert r.exit_code == 1 and r.failing_tests == ()


@pytest.mark.parametrize("out", [None, "", "collected 3 items\n3 passed\n"])
def test_eb6_render_byte_identical_to_head(head_foundry, out):
    r = _broken(out=out)
    assert r.render() == _head_result(head_foundry, r).render()


RED_RENDER = "\n".join([
    "foundry preship (local-clone re-verification)",
    "  verified:      False",
    "  incomplete:    False",
    "  suite wall:    n/a",
    "  verified sha:  unknown",
    "  worktree:      unknown",
    "  detail:        " + foundry.PRESHIP_SUITE_FAILED_DETAIL,
    "  exit code:     1",
    "- failing tests:",
    "  - " + ID_A,
    "  - " + ID_B,
    "PRESHIP: BROKEN",
])


def test_eb6_red_render_equals_fixed_literal():
    assert _broken().render() == RED_RENDER


# ==========================================================================
# EB7 / EB9 -- preship_cli end to end (scripted seams, offline)
# ==========================================================================
def _cfg(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    return foundry.ProductConfig(name="demo", repo=str(repo), allowed_push_repo="demo",
                                 work_root=str(work), test_cmd="uv run pytest",
                                 setup_cmd="uv sync")


def _kind(argv, cwd):
    joined = " ".join(argv) + " " + str(cwd or "")
    pre = "p:" if PARENT_DIR_NAME in joined else ""
    if "--porcelain" in argv:
        return "porcelain"
    if "--shortstat" in argv:
        return "shortstat"
    if argv[:3] == ["uv", "python", "find"]:
        return pre + "find"
    if "rev-parse" in argv:
        if any(a.endswith("^") for a in argv):
            return "parent_resolve"
        return pre + "sha"
    if "checkout" in argv:
        return pre + "checkout"
    if len(argv) > 1 and argv[0] == "git" and argv[1] == "clone":
        return pre + "clone"
    if "sync" in argv:
        return pre + "setup"
    return pre + "test"


def _install(monkeypatch, *, head_out=RED_OUT, parent_out=None, parent_test_ok=True):
    calls = []
    if parent_out is None:
        parent_out = "12 passed in 1.0s\n"

    def fake_run_cmd(args, cwd=None, timeout=None, **kw):
        argv = [str(a) for a in args]
        kind = _kind(argv, cwd)
        calls.append(kind)
        if kind == "porcelain":
            return foundry.CmdResult(True, "")
        if kind == "shortstat":
            return foundry.CmdResult(True, "")
        if kind == "parent_resolve":
            return foundry.CmdResult(True, PARENT + "\n")
        if kind == "sha":
            return foundry.CmdResult(True, SHA + "\n")
        if kind == "p:sha":
            return foundry.CmdResult(True, PARENT + "\n")
        if kind == "test":
            return foundry.CmdResult(False, head_out)
        if kind == "p:test":
            return foundry.CmdResult(parent_test_ok, parent_out)
        if kind == "p:find":
            return foundry.CmdResult(True, INTERP + "\n")
        return foundry.CmdResult(True, kind + " output")

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(foundry, "cleanup_clone", lambda d: None)
    monkeypatch.setattr(foundry, "_monotonic", lambda: 0.0)
    monkeypatch.setattr(subprocess, "run", _no_real_subprocess)
    monkeypatch.setattr(subprocess, "Popen", _no_real_subprocess)
    return calls


def _no_real_subprocess(*a, **k):  # pragma: no cover - tripwire
    raise AssertionError("real subprocess call during an offline behavior: %r" % (a,))


def _run_cli(cfg, as_json=False):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.preship_cli(cfg, as_json=as_json)
    return rc, buf.getvalue()


def test_eb7_cli_text_lists_ids_above_broken(monkeypatch, tmp_path):
    calls = _install(monkeypatch)
    rc, out = _run_cli(_cfg(tmp_path))
    assert rc == 1, out
    assert "test" in calls
    lines = out.splitlines()
    assert "- failing tests:" in lines, out
    i = lines.index("- failing tests:")
    assert lines[i + 1:i + 3] == ["  - " + ID_A, "  - " + ID_B], out
    assert _last(out) == "PRESHIP: BROKEN"
    assert out.count("PRESHIP:") == 1
    assert i < lines.index("PRESHIP: BROKEN")


def test_eb7_cli_json_lists_ids(monkeypatch, tmp_path):
    _install(monkeypatch)
    rc, out = _run_cli(_cfg(tmp_path), as_json=True)
    d = json.loads(out)  # exactly one JSON document
    assert rc == 1
    assert d["exit_code"] == 1 and d["sentinel"] == "PRESHIP: BROKEN"
    assert d["failing_tests"] == [ID_A, ID_B]
    assert list(d)[-1] == "failing_tests" and len(d) == 9
    assert d["detail"] == foundry.PRESHIP_SUITE_FAILED_DETAIL


def test_eb7_cli_json_parent_fails_differently_still_lists(monkeypatch, tmp_path):
    _install(monkeypatch, parent_out=_out([ID_A]), parent_test_ok=False)
    rc, out = _run_cli(_cfg(tmp_path), as_json=True)
    d = json.loads(out)
    assert rc == 1 and d["failing_tests"] == [ID_A, ID_B]


def test_eb9_parent_identical_set_downgrades_with_empty_list(monkeypatch, tmp_path):
    calls = _install(monkeypatch, parent_out=_out([ID_B, ID_A]), parent_test_ok=False)
    rc, out = _run_cli(_cfg(tmp_path), as_json=True)
    d = json.loads(out)
    assert "p:test" in calls
    assert rc == 2 and d["exit_code"] == 2 and d["incomplete"] is True, d
    assert d["sentinel"] == "PRESHIP: INCOMPLETE"
    assert d["failing_tests"] == []
    assert ID_A in d["detail"] and ID_B in d["detail"]


def test_eb9_parent_identical_set_text_has_no_block(monkeypatch, tmp_path):
    _install(monkeypatch, parent_out=_out([ID_B, ID_A]), parent_test_ok=False)
    rc, out = _run_cli(_cfg(tmp_path))
    assert rc == 2
    assert "failing tests:" not in out
    assert _last(out) == "PRESHIP: INCOMPLETE"


def test_eb9_parent_leg_detail_equals_head(monkeypatch, tmp_path, head_foundry):
    _install(monkeypatch, parent_out=_out([ID_B, ID_A]), parent_test_ok=False)
    rc, out = _run_cli(_cfg(tmp_path), as_json=True)
    d = json.loads(out)
    r = foundry.PreshipResult(verified=d["verified"], incomplete=d["incomplete"],
                              detail=d["detail"], suite_output=RED_OUT)
    assert r.failing_tests == ()
    head = _head_result(head_foundry, r)
    assert head.exit_code == 2 and head.render() == r.render()


# ==========================================================================
# EB8 -- verdict invariance vs HEAD for every preship_verdict flag combination
# ==========================================================================
_FLAGS = ("clone_ok", "setup_ok", "test_ok", "sha_ok", "budget_exhausted")


def test_eb8_flag_names_match_spec():
    params = inspect.signature(foundry.preship_verdict).parameters
    assert tuple(params) == _FLAGS
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values())


@pytest.mark.parametrize("combo", list(itertools.product((False, True), repeat=5)))
def test_eb8_preship_verdict_identical_to_head(head_foundry, combo):
    kw = dict(zip(_FLAGS, combo))
    now = foundry.preship_verdict(**kw)
    then = head_foundry.preship_verdict(**kw)
    assert now.exit_code == then.exit_code
    assert now.sentinel == then.sentinel
    assert now.detail == then.detail
    assert now.render() == then.render()
    assert now.failing_tests == ()
    d_now, d_then = now.to_dict(), then.to_dict()
    assert {k: v for k, v in d_now.items() if k != "failing_tests"} == \
        {k: v for k, v in d_then.items() if k != "failing_tests"}


def test_eb8_all_three_verdicts_are_reached():
    seen = {foundry.preship_verdict(**dict(zip(_FLAGS, c))).exit_code
            for c in itertools.product((False, True), repeat=5)}
    assert seen == {0, 1, 2}


def test_eb8_suite_failed_detail_constant_equals_head(head_foundry):
    assert foundry.PRESHIP_SUITE_FAILED_DETAIL == head_foundry.PRESHIP_SUITE_FAILED_DETAIL


@pytest.mark.parametrize("make", [_broken, _verified, _incomplete])
def test_eb8_exit_code_and_sentinel_identical_to_head(head_foundry, make):
    r = make()
    h = _head_result(head_foundry, r)
    assert (r.exit_code, r.sentinel, r.detail) == (h.exit_code, h.sentinel, h.detail)


# ==========================================================================
# EB10 -- ship-survival: no HEAD baseline outside the gated helpers
# ==========================================================================
_GATED_HELPERS = {"_head_text", "head_foundry"}


def _head_literal_owners():
    import ast
    tree = ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))
    owners = []
    for top in tree.body:
        for node in ast.walk(top):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value.startswith("HEAD" + ":")):
                owners.append(getattr(top, "name", "<module>"))
    return owners


def test_eb10_head_refs_only_inside_gated_helpers():
    owners = _head_literal_owners()
    assert owners, "expected the gated helpers to reference HEAD:"
    assert set(owners) <= _GATED_HELPERS, owners


def test_eb10_head_foundry_checks_gate_before_git_show():
    src = inspect.getsource(head_foundry.__wrapped__ if hasattr(head_foundry, "__wrapped__")
                            else head_foundry)
    gate = src.find("_pre_ship_scope_live()")
    show = src.find('"HEAD:foundry.py"')
    assert 0 <= gate < show, (gate, show)


@pytest.mark.parametrize("roadmap,archive,live", [
    ("", "", True),
    ("- iter 549 -- x\n", "- **iter 549 -- y\n", True),
    ("- iter 550 -- shipped\n", "", False),
    ("", "- **iter 550 -- shipped\n", False),
    ("- iter 550 -- a\n", "- **iter 550 -- b\n", False),
])
def test_eb10_scope_gate_keys_on_index_or_archive(monkeypatch, roadmap, archive, live):
    texts = {"PLATFORM_ROADMAP.md": roadmap, "PLATFORM_ROADMAP_ARCHIVE.md": archive}
    monkeypatch.setitem(globals(), "_head_text", lambda rel: texts[rel])
    assert _pre_ship_scope_live() is live


def test_eb10_no_iter549_oracle_file_exists():
    assert not (_ROOT / "tests" / "test_iter549_behavior.py").exists()


def test_eb10_ledger_has_one_550_row_and_no_549_row():
    idx = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8").splitlines()
    arc = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text(encoding="utf-8").splitlines()
    rows = [ln for ln in idx if ln.startswith("- iter 550 ")]
    assert len(rows) == 1, rows
    assert len(rows[0]) <= 120, len(rows[0])
    assert not [ln for ln in idx if ln.startswith("- iter 549 ")]
    bullets = [ln for ln in arc if ln.startswith("- **iter 550 ")]
    assert len(bullets) == 1, bullets
    assert not [ln for ln in arc if ln.startswith("- **iter 549 ")]


def test_eb10_foundry_and_dispatcher_import():
    proc = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                          cwd=str(_ROOT), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr


# ==========================================================================
# EB11 -- roles/tester.md H1 names the HEAD-baseline hazard
# ==========================================================================
def _h1_bullet():
    lines = (_ROOT / "roles" / "tester.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("- H1 "))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("- H2 "))
    return "\n".join(lines[start:end])


def test_eb11_h1_names_head_baseline_hazard():
    h1 = " ".join(_h1_bullet().split())
    assert "git show " + "HEAD" + ":" in h1
    assert "549" in h1


def test_eb11_h1_names_both_safe_alternatives():
    h1 = " ".join(_h1_bullet().split())
    assert "fixed literal" in h1
    assert "- iter N " in h1


def test_eb11_hazard_labels_keep_order_under_ship_hazards():
    text = (_ROOT / "roles" / "tester.md").read_text(encoding="utf-8")
    sec = text.index("## SHIP HAZARDS")
    h1, h2, h3 = (text.index("- " + k + " ", sec) for k in ("H1", "H2", "H3"))
    nxt = text.find("\n## ", sec + 1)
    assert sec < h1 < h2 < h3 < (nxt if nxt != -1 else len(text) + 1)
