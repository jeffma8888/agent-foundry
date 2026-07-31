"""Black-box behaviour tests for iter 22 -- the PURE, offline, deterministic
AST detector for assertion-free `test*` functions
(`find_assertionless_tests(source) -> tuple[str, ...]`), the frozen
`WeakTestSummary` + pure keyword-only `summarize_weak_tests(...)` builder, the
patchable module constants `WEAK_TEST_GLOBS` / `WEAK_TEST_ASSERTION_CALLS`, and
the DORMANT on-demand `foundry weak-tests --config <cfg> [--files ...]` CLI that
scans test files and reports assertion-free tests (a test that passes without
validating anything = a false green). The pipeline/gate does NOT consult it.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-17) and the product's own OBSERVABLE behaviour only. The
implementation source (foundry.py / dispatcher.py internals), the engineer's and
reviewer's notes, and `git diff` were NOT read. Every check drives the PUBLIC
interface: the pure fn via `foundry.find_assertionless_tests(...)`, the summary
builder via `foundry.summarize_weak_tests(...)`, the constants via
`foundry.WEAK_TEST_GLOBS` / `foundry.WEAK_TEST_ASSERTION_CALLS`, and the CLI via
`foundry.main(["weak-tests", ...])` against a TMP-`repo` config (the real repo is
never touched). The dormancy / off-control-path checks (Behavior 17) use only
public RUNTIME introspection -- module attributes, `--help` output, and compiled
function name/const tables (`__code__.co_names` / `co_consts`) -- NOT the source
text (so "dispatcher.py source does not reference them" is verified as
"no compiled reference in the dispatcher module", which honors isolation).
Fully offline and deterministic: no subprocess (except the documented
`import foundry, dispatcher` regression probe and the `--help` usage probe), no
network, no git, no agent-run. Real temp files only; every CLI test snapshots the
tmp tree to prove the read-only / writes-nothing contract.
"""
import dataclasses
import io
import pathlib
import re
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers  (mirror tests/test_iter15_behavior.py conventions)
# --------------------------------------------------------------------------
def _run_cli(argv):
    """Drive foundry.main capturing (rc, stdout+stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue() + err.getvalue()


def _write_cfg(tmp_path, files=None, **over):
    """A minimal product config in a tmp dir (mirrors the suite's convention).
    `repo` is a TMP dir so the real foundry repo is NEVER touched. `files` is a
    {relative-path: source-text} mapping seeded under the repo."""
    import json
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
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _snapshot_tree(root):
    """Map {relative-path: bytes} for every file under root (no-write proof)."""
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*") if p.is_file()
    }


def _fn_names_consts(fn):
    """Recursively gather (co_names set, str-consts set) reachable from fn's
    compiled code object -- public runtime introspection, not source text."""
    stack, seen = [fn.__code__], set()
    names, consts = set(), set()
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names |= set(code.co_names)
        for c in code.co_consts:
            if isinstance(c, str):
                consts.add(c)
            elif isinstance(c, types.CodeType):
                stack.append(c)
    return names, consts


def _module_names_consts(module):
    """Union of names/str-consts across every function/method reachable from a
    module's public namespace (recursively into nested code objects)."""
    names, consts = set(), set()
    for v in vars(module).values():
        if isinstance(v, types.FunctionType):
            n, c = _fn_names_consts(v)
            names |= n
            consts |= c
        elif isinstance(v, type):
            for m in vars(v).values():
                if isinstance(m, types.FunctionType):
                    n, c = _fn_names_consts(m)
                    names |= n
                    consts |= c
    return names, consts


NEW_SYMBOLS = ("find_assertionless_tests", "summarize_weak_tests", "weak_tests_cli")
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")


# ==========================================================================
# A. Pure scanner  find_assertionless_tests(source) -> tuple[str, ...]
# ==========================================================================

# --- Behavior 1 -- assertion-free test IS flagged -------------------------
def test_b01_assertion_free_test_is_flagged():
    r = foundry.find_assertionless_tests("def test_a():\n    pass\n")
    assert r == ("test_a",), f"an assertion-free test* must be flagged, got {r!r}"
    assert isinstance(r, tuple), f"result must be a tuple, got {type(r)}"


# --- Behavior 2 -- an `assert` statement is a signal ----------------------
def test_b02_assert_statement_not_flagged():
    r = foundry.find_assertionless_tests("def test_a():\n    assert 1 == 1\n")
    assert r == (), f"a test with an `assert` must NOT be flagged, got {r!r}"


# --- Behavior 3 -- class-method discovery + 'starts with assert' call -----
def test_b03_class_method_assert_call_not_flagged():
    src = "class TestX:\n    def test_a(self):\n        self.assertEqual(1, 1)\n"
    r = foundry.find_assertionless_tests(src)
    assert r == (), (
        "a class test-method whose call name starts with 'assert' "
        f"(self.assertEqual) must NOT be flagged, got {r!r}"
    )


# --- Behavior 4 -- pytest.raises context manager is a signal --------------
def test_b04_pytest_raises_ctx_not_flagged():
    src = "def test_a():\n    with pytest.raises(ValueError):\n        f()\n"
    r = foundry.find_assertionless_tests(src)
    assert r == (), (
        "callee trailing-name 'raises' is in the default WEAK_TEST_ASSERTION_CALLS "
        f"so the test must NOT be flagged, got {r!r}"
    )


# --- Behavior 5 -- a `raise` statement is a signal ------------------------
def test_b05_raise_statement_not_flagged():
    src = "def test_a():\n    if cond:\n        raise AssertionError\n"
    r = foundry.find_assertionless_tests(src)
    assert r == (), f"a `raise` statement is an assertion signal, got {r!r}"


# --- Behavior 6 -- only `test*` names are candidates ----------------------
def test_b06_non_test_names_ignored():
    src = "def helper():\n    pass\n\ndef test_a():\n    assert g()\n"
    r = foundry.find_assertionless_tests(src)
    assert r == (), (
        "`helper` (non-test name) is never a candidate and `test_a` asserts, "
        f"so the result must be empty, got {r!r}"
    )


# --- Behavior 7 -- ASCENDING SOURCE ORDER, not alphabetical ---------------
def test_b07_findings_in_source_order():
    src = "def test_zebra():\n    pass\n\ndef test_apple():\n    pass\n"
    r = foundry.find_assertionless_tests(src)
    assert r == ("test_zebra", "test_apple"), (
        "multiple assertion-free tests must be returned in ascending source "
        f"(line) order, not alphabetical, got {r!r}"
    )


# --- Behavior 8 -- async test functions are considered --------------------
def test_b08_async_test_flagged():
    r = foundry.find_assertionless_tests("async def test_a():\n    pass\n")
    assert r == ("test_a",), f"an async assertion-free test* must be flagged, got {r!r}"


# --- Behavior 9 -- invalid Python raises SyntaxError ----------------------
def test_b09_syntax_error_propagates():
    with pytest.raises(SyntaxError):
        foundry.find_assertionless_tests("def (:\n")


# --- Behavior 10 -- WEAK_TEST_ASSERTION_CALLS read at CALL time -----------
def test_b10_assertion_calls_patchable_at_call_time(monkeypatch):
    src = "def test_a():\n    verify(x)\n"
    assert foundry.find_assertionless_tests(src) == ("test_a",), (
        "with the default calls, `verify(x)` is not an assertion signal so the "
        "test is flagged"
    )
    monkeypatch.setattr(
        foundry, "WEAK_TEST_ASSERTION_CALLS",
        foundry.WEAK_TEST_ASSERTION_CALLS | {"verify"},
    )
    assert foundry.find_assertionless_tests(src) == (), (
        "after adding 'verify' to WEAK_TEST_ASSERTION_CALLS the SAME source must "
        "return () -- the constant is read at call time"
    )


# --- constant defaults / patchable-shape ----------------------------------
def test_constants_have_sane_defaults():
    assert foundry.WEAK_TEST_GLOBS == ("test_*.py", "*_test.py"), (
        f"default WEAK_TEST_GLOBS wrong: {foundry.WEAK_TEST_GLOBS!r}"
    )
    calls = foundry.WEAK_TEST_ASSERTION_CALLS
    assert isinstance(calls, frozenset), f"WEAK_TEST_ASSERTION_CALLS must be a frozenset, got {type(calls)}"
    for expected in ("raises", "warns", "fail"):
        assert expected in calls, f"default WEAK_TEST_ASSERTION_CALLS must include {expected!r}: {calls!r}"


# ==========================================================================
# B. summarize_weak_tests(...) + frozen WeakTestSummary
# ==========================================================================

# --- Behavior 16 -- exit-code / clean derivation --------------------------
def test_b16_summary_nothing_to_scan():
    s = foundry.summarize_weak_tests(product="p", files_scanned=0, findings=(), parse_errors=())
    assert s.exit_code == 2, f"files_scanned=0 must yield exit_code 2, got {s.exit_code}"
    assert s.clean is False, f"nothing-scanned must NOT be clean, got clean={s.clean!r}"


def test_b16_summary_clean():
    s = foundry.summarize_weak_tests(product="p", files_scanned=2, findings=(), parse_errors=())
    assert s.exit_code == 0, f"scanned+no-findings must yield exit_code 0, got {s.exit_code}"
    assert s.clean is True, f"scanned+no-findings must be clean, got clean={s.clean!r}"


def test_b16_summary_with_findings():
    s = foundry.summarize_weak_tests(
        product="p", files_scanned=2, findings=(("t.py", "test_a"),), parse_errors=()
    )
    assert s.exit_code == 1, f"findings must yield exit_code 1, got {s.exit_code}"
    assert s.clean is False, f"findings must NOT be clean, got clean={s.clean!r}"
    assert s.total_findings == 1, f"total_findings must count findings, got {s.total_findings}"


def test_b16_summary_is_frozen_dataclass_with_fields_and_render():
    s = foundry.summarize_weak_tests(
        product="p", files_scanned=2, findings=(("t.py", "test_a"),), parse_errors=()
    )
    assert type(s).__name__ == "WeakTestSummary"
    assert dataclasses.is_dataclass(s)
    field_names = {f.name for f in dataclasses.fields(s)}
    for f in ("product", "files_scanned", "findings", "parse_errors"):
        assert f in field_names, f"WeakTestSummary missing field {f!r}: {field_names}"
    # frozen: assignment must raise
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.files_scanned = 99
    # render() is a str that surfaces the finding
    text = s.render()
    assert isinstance(text, str) and text.strip(), "render() must return non-empty text"
    assert "test_a" in text and "t.py" in text, f"render() must name the finding:\n{text}"


def test_b16_summarize_is_keyword_only():
    # the builder is documented keyword-only -> positional args must be rejected.
    with pytest.raises(TypeError):
        foundry.summarize_weak_tests("p", 0, (), ())


# ==========================================================================
# C. CLI  foundry weak-tests --config <cfg> [--files ...]
# ==========================================================================

# --- Behavior 11 -- one dirty file -> exit 1, names file + test -----------
def test_b11_cli_one_dirty_file_exit1(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"test_dirty.py": "def test_a():\n    pass\n"})
    cfg = foundry.load_config(str(cfg_path))
    before = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["weak-tests", "--config", str(cfg_path)])
    assert rc == 1, f"a repo with an assertion-free test must exit 1, got {rc}\n{out}"
    assert "test_dirty.py" in out, f"stdout must name the dirty file path:\n{out}"
    assert "test_a" in out, f"stdout must name the assertion-free test `test_a`:\n{out}"
    assert _snapshot_tree(tmp_path) == before, "weak-tests wrote to disk (must be read-only)"


# --- Behavior 12 -- all clean -> exit 0, no finding names -----------------
def test_b12_cli_all_clean_exit0(tmp_path):
    cfg_path = _write_cfg(
        tmp_path, files={"test_clean.py": "def test_should_not_appear():\n    assert True\n"}
    )
    before = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["weak-tests", "--config", str(cfg_path)])
    assert rc == 0, f"an all-asserting repo must exit 0, got {rc}\n{out}"
    assert "test_should_not_appear" not in out, (
        f"a clean result must not list any test-function name from the file:\n{out}"
    )
    assert _snapshot_tree(tmp_path) == before, "weak-tests wrote to disk (must be read-only)"


# --- Behavior 13 -- nothing to scan -> exit 2 -----------------------------
def test_b13_cli_nothing_to_scan_exit2(tmp_path):
    # a file present but NOT matching WEAK_TEST_GLOBS -> nothing to scan.
    cfg_path = _write_cfg(tmp_path, files={"notatest.py": "def test_a():\n    pass\n"})
    before = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["weak-tests", "--config", str(cfg_path)])
    assert rc == 2, f"a repo with no test-glob-matching file must exit 2, got {rc}\n{out}"
    assert _snapshot_tree(tmp_path) == before, "weak-tests wrote to disk (must be read-only)"


# --- Behavior 14 -- --files scans EXACTLY the given paths -----------------
def test_b14_cli_files_seam_scans_only_given(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={
        "test_other_dirty.py": "def test_other_should_not_appear():\n    pass\n",
        "test_other_clean.py": "def test_clean_fn():\n    assert 1\n",
        "test_target.py": "def test_a():\n    pass\n",
    })
    cfg = foundry.load_config(str(cfg_path))
    target = str(pathlib.Path(cfg.repo) / "test_target.py")
    before = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["weak-tests", "--config", str(cfg_path), "--files", target])
    assert rc == 1, f"--files pointing at one assertion-free file must exit 1, got {rc}\n{out}"
    assert "test_target.py" in out and "test_a" in out, (
        f"the report must reference the given target file + its weak test:\n{out}"
    )
    # the repo's OTHER matched test files must NOT be walked -> absent from output
    assert "test_other_dirty.py" not in out, f"--files must NOT walk the repo:\n{out}"
    assert "test_other_should_not_appear" not in out, f"--files must NOT walk the repo:\n{out}"
    # files_scanned == 1 (exactly the one --files path), observable as the count
    assert re.search(r"files\s*scanned\D*1\b", out), (
        f"exactly one file must be scanned (files_scanned=1):\n{out}"
    )
    assert _snapshot_tree(tmp_path) == before, "weak-tests wrote to disk (must be read-only)"


# --- Behavior 15 -- unparseable test file -> exit 1, listed, no crash -----
def test_b15_cli_unparseable_file_exit1(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"test_bad.py": "def (:\n"})
    before = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["weak-tests", "--config", str(cfg_path)])
    assert rc == 1, f"an unparseable test file must exit 1, got {rc}\n{out}"
    assert "test_bad.py" in out, f"stdout must list the unparseable file:\n{out}"
    assert re.search(r"(?i)parse error|syntaxerror", out), (
        f"stdout must report the file as a parse error:\n{out}"
    )
    assert "Traceback" not in out, f"the CLI must degrade gracefully (no traceback):\n{out}"
    assert _snapshot_tree(tmp_path) == before, "weak-tests wrote to disk (must be read-only)"


def test_cli_missing_config_flag_is_error(tmp_path):
    # --config is required -> argparse exits non-zero (regression / usage guard).
    with pytest.raises(SystemExit) as ei:
        _run_cli(["weak-tests"])
    assert ei.value.code != 0, "weak-tests without --config must be a usage error"


# ==========================================================================
# D. Behavior 17 -- DORMANT & off the control path (public introspection)
# ==========================================================================
def test_b17_both_modules_import():
    import subprocess
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b17_new_surface_present_and_callable():
    assert callable(foundry.find_assertionless_tests)
    assert callable(foundry.summarize_weak_tests)
    assert callable(foundry.weak_tests_cli)
    assert hasattr(foundry, "WeakTestSummary")
    assert isinstance(foundry.WEAK_TEST_GLOBS, tuple)
    assert isinstance(foundry.WEAK_TEST_ASSERTION_CALLS, frozenset)
    # pre-existing control-flow entry points remain present + callable (regression)
    for fn in CONTROL_FLOW_FNS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"


def test_b17_help_lists_existing_plus_weak_tests(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for sub in ("run", "once", "doctor", "learnings", "agents",
                "lint-spec", "prd", "gate-scope", "status", "weak-tests"):
        assert sub in out, f"subcommand {sub!r} missing from --help:\n{out}"


def test_b17_new_symbols_absent_from_foundry_control_flow():
    for fn_name in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, (
                f"{fn_name} references new symbol {sym!r} (must stay off the control path)"
            )
        assert "weak-tests" not in consts, (
            f"{fn_name} embeds the 'weak-tests' subcommand string (must stay off the control path)"
        )


def test_b17_new_symbols_absent_from_dispatcher():
    # honors isolation: verified via compiled-const/name introspection of the
    # dispatcher module, NOT by reading dispatcher.py source text.
    for sym in NEW_SYMBOLS + ("WeakTestSummary",):
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, consts = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in names, f"dispatcher references new symbol {sym!r}"
    assert "weak-tests" not in consts, "dispatcher embeds the 'weak-tests' subcommand string"


def test_b17_cli_run_writes_nothing(tmp_path):
    # running the CLI over a tmp repo leaves that repo's file state unchanged.
    cfg_path = _write_cfg(tmp_path, files={
        "test_dirty.py": "def test_a():\n    pass\n",
        "test_clean.py": "def test_b():\n    assert 1\n",
    })
    before = _snapshot_tree(tmp_path)
    rc, _ = _run_cli(["weak-tests", "--config", str(cfg_path)])
    assert rc in (0, 1, 2), f"unexpected exit code {rc}"
    assert _snapshot_tree(tmp_path) == before, "weak-tests created/modified files (must be read-only)"


def test_b17_sentinels_unchanged():
    # Non-regression: the additive bite must not remove/rename the release
    # sentinels or the ship-outcome status vocabulary (public const introspection).
    _, consts = _module_names_consts(foundry)
    for sentinel in ("VERDICT:", "RESULT:", "ACTION:", "POSTRELEASE:"):
        assert any(sentinel in c for c in consts), f"sentinel prefix {sentinel!r} vanished from foundry"
    for status in ("shipped", "no-ship", "infra-fail"):
        assert status in consts, f"res['status'] value {status!r} vanished from foundry"
