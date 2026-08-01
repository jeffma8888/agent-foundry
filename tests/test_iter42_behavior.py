"""Black-box behaviour tests for iter 42 -- `foundry company-weak-tests` BITE 1 of
2 (the pure foundation): a NEW module-level, dormant, purely-additive,
output-preserving

    foundry.gather_weak_tests(cfg, files=None) -> WeakTestSummary

extracted from `weak_tests_cli`'s gathering, which now DELEGATES to it. Completes
the `gather_status` / `gather_history` / `gather_timing` / `gather_weak_tests`
symmetry so the company weak-test roll-up (bite 2, next iter) has ONE shared,
tested gathering seam. A STRUCTURAL MIRROR of the shipped iter-39 `gather_timing`
bite -- and leaner (no new WeakTestSummary accessor needed; the iter-22 core
already exposes everything summed).

NO `CompanyWeakTests`, NO `company-weak-tests` subcommand, NO `--json` for it, NO
new CLI/sentinel/config field this bite -- all deferred to bite 2.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-42 PM
spec's Expected Behaviors (1-4), the product README/roadmap, the `tests/`
conventions (esp. tests/test_iter39_behavior.py -- the `gather_timing` mirror --
and the iter-22/23 `weak-tests` seam tests), and the product's own OBSERVABLE
behaviour (by RUNNING it / public RUNTIME introspection: module attrs, `--help`
output, `inspect.signature`, compiled `__code__.co_names`/`co_consts` tables).
The implementation SOURCE (foundry.py / dispatcher.py source text), the
engineer's & reviewer's notes, and `git diff` were NOT read. Every check drives
the PUBLIC interface: the pure fns via `foundry.gather_weak_tests(...)` /
`foundry.summarize_weak_tests(...)` / `foundry.find_assertionless_tests(...)`,
and the CLI via `foundry.weak_tests_cli(...)` / `foundry.main(["weak-tests",
...])` against a TMP-`repo` config with real temp test files (the real foundry
repo is NEVER touched). Fully offline & deterministic: real temp files only; ZERO
real git / network / clock (except the documented `import foundry, dispatcher`
regression probe and the `--help` usage probe).
"""
import dataclasses
import inspect
import io
import json
import pathlib
import re
import subprocess
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers  (mirror tests/test_iter39_behavior.py + test_iter22/23_behavior.py)
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, files=None, **over):
    """A minimal product config in a tmp dir. `repo` is a TMP dir so the real
    foundry repo is NEVER touched. `files` is a {relative-path: source-text}
    mapping seeded under the repo."""
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


def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY; return (rc, out, err).
    Separate capture matters: the JSON path requires the JSON to be the ENTIRE
    stdout, so stderr noise must not contaminate the parse."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


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


# The genuinely-NEW iter-42 symbol. `find_assertionless_tests`,
# `_gather_weak_test_files`, `summarize_weak_tests`, `weak_tests_cli`,
# `WeakTestSummary`, `WEAK_TEST_GLOBS`, `WEAK_TEST_ASSERTION_CALLS` are all
# PRE-EXISTING (iter 22/23) and MUST be reused, not re-implemented.
NEW_SYMBOLS = ("gather_weak_tests",)
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")

# The Behavior-1 canonical fixture files.
_REPO_FILES = {
    "test_ok.py": "def test_a():\n    assert 1 == 1\n",   # asserts -> NOT a finding
    "test_weak.py": "def test_b():\n    pass\n",           # assertion-free -> finding
    "test_bad.py": "def (:\n",                             # unparseable -> parse_error
}


# ==========================================================================
# Behavior 1 -- gather_weak_tests repo-walk mode (output-preserving extraction)
# ==========================================================================
def test_b1_repo_walk_counts_finding_and_parse_error(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, files=_REPO_FILES)))
    s = foundry.gather_weak_tests(cfg)
    assert isinstance(s, foundry.WeakTestSummary)
    assert type(s).__name__ == "WeakTestSummary"
    assert s.product == cfg.name, "summary product == cfg.name"
    assert s.files_scanned == 3, f"all 3 test-glob files walked, got {s.files_scanned}"
    # exactly one assertion-free finding, whose function name is test_b
    assert len(s.findings) == 1, f"exactly one finding expected, got {s.findings!r}"
    assert s.findings[0][1] == "test_b", f"the flagged function must be test_b: {s.findings!r}"
    assert s.findings[0][0].endswith("test_weak.py"), f"finding path names the weak file: {s.findings!r}"
    # exactly one parse-error entry for the unparseable file
    assert len(s.parse_errors) == 1, f"exactly one parse_error expected, got {s.parse_errors!r}"
    assert s.parse_errors[0][0].endswith("test_bad.py"), f"parse_error names test_bad.py: {s.parse_errors!r}"
    # exit code follows the frozen WeakTestSummary derivation (findings -> 1)
    assert s.exit_code == 1


def test_b1_parse_error_entry_shape_is_type_and_str(tmp_path):
    """A raised SyntaxError/OSError is folded (never propagated) into a
    `(str(path), f"{type(exc).__name__}: {exc}")` parse_errors entry."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path, files={"test_bad.py": "def (:\n"})))
    s = foundry.gather_weak_tests(cfg)   # must NOT raise
    assert len(s.parse_errors) == 1
    path, message = s.parse_errors[0]
    assert isinstance(path, str) and path.endswith("test_bad.py")
    assert message.startswith("SyntaxError:"), \
        f"message must be '<ExcType>: <exc>', got {message!r}"
    assert message.strip(), "parse-error message must be non-empty"


def test_b1_equals_weak_tests_cli_human_output(tmp_path):
    """The load-bearing 'output-preserving' claim: what gather_weak_tests
    returns renders EXACTLY what `foundry weak-tests` prints -- same body + exit."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path, files=_REPO_FILES)))
    s = foundry.gather_weak_tests(cfg)
    rc, out, _ = _capture(lambda: foundry.weak_tests_cli(cfg))
    assert rc == s.exit_code, "weak_tests_cli exit code == gather_weak_tests().exit_code"
    assert out.rstrip("\n") == s.render().rstrip("\n"), \
        f"weak-tests human output must equal gather_weak_tests().render():\n{out}"


def test_b1_writes_nothing(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, files=_REPO_FILES)))
    before = _snapshot_tree(tmp_path)
    foundry.gather_weak_tests(cfg)
    foundry.gather_weak_tests(cfg, files=[str(pathlib.Path(cfg.repo) / "test_weak.py")])
    assert _snapshot_tree(tmp_path) == before, "gather_weak_tests wrote to disk (must be read-only)"


def test_b1_empty_repo_nothing_to_scan(tmp_path):
    # a file present but NOT matching WEAK_TEST_GLOBS -> nothing to scan.
    cfg = foundry.load_config(str(_write_cfg(tmp_path, files={"notatest.py": "def test_a():\n    pass\n"})))
    s = foundry.gather_weak_tests(cfg)
    assert s.files_scanned == 0 and s.exit_code == 2 and s.clean is False


def test_b1_delegates_to_summarize_weak_tests_by_bare_name(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, files=_REPO_FILES)))
    captured = {}
    sentinel = foundry.summarize_weak_tests(product="SENTINEL", files_scanned=0, findings=(), parse_errors=())

    def fake_sum(*, product, files_scanned, findings, parse_errors):
        captured["product"] = product
        captured["files_scanned"] = files_scanned
        captured["findings"] = tuple(findings)
        captured["parse_errors"] = tuple(parse_errors)
        return sentinel

    monkeypatch.setattr(foundry, "summarize_weak_tests", fake_sum)
    got = foundry.gather_weak_tests(cfg)
    assert got is sentinel, "gather_weak_tests must RETURN summarize_weak_tests(...)"
    assert captured["product"] == cfg.name
    assert captured["files_scanned"] == 3
    assert [f[1] for f in captured["findings"]] == ["test_b"]
    assert len(captured["parse_errors"]) == 1 and captured["parse_errors"][0][0].endswith("test_bad.py")


def test_b1_uses_find_assertionless_tests_seam(tmp_path, monkeypatch):
    """Monkeypatching foundry.find_assertionless_tests by bare name must bite."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path, files={
        "test_a.py": "def test_x():\n    assert 1\n",
        "test_b.py": "def test_y():\n    assert 1\n",
    })))
    monkeypatch.setattr(foundry, "find_assertionless_tests", lambda src: ("FORCED",))
    s = foundry.gather_weak_tests(cfg)
    # every parseable file now yields a single forced finding named FORCED
    assert s.files_scanned == 2
    assert [f[1] for f in s.findings] == ["FORCED", "FORCED"], \
        "monkeypatching foundry.find_assertionless_tests must control the findings"


def test_b1_uses_gather_weak_test_files_seam(tmp_path, monkeypatch):
    """Monkeypatching foundry._gather_weak_test_files by bare name controls which
    files the repo-walk visits."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path, files=_REPO_FILES)))
    only = [pathlib.Path(cfg.repo) / "test_weak.py"]
    monkeypatch.setattr(foundry, "_gather_weak_test_files", lambda repo: only)
    s = foundry.gather_weak_tests(cfg)
    assert s.files_scanned == 1, "only the monkeypatched file list is walked"
    assert [f[1] for f in s.findings] == ["test_b"]
    assert s.parse_errors == (), "the unparseable file was excluded by the patched walk"


# ==========================================================================
# Behavior 2 -- gather_weak_tests explicit-`files` mode
# ==========================================================================
def test_b2_files_mode_scans_exactly_given(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, files=_REPO_FILES)))
    weakpath = str(pathlib.Path(cfg.repo) / "test_weak.py")
    s = foundry.gather_weak_tests(cfg, files=[weakpath])
    assert s.files_scanned == 1, f"exactly the one --files path is scanned, got {s.files_scanned}"
    assert len(s.findings) == 1 and s.findings[0][1] == "test_b"
    # the repo's OTHER matched test files must NOT be walked
    assert all(not f[0].endswith("test_ok.py") for f in s.findings)
    assert s.parse_errors == (), "test_bad.py was not in the explicit files list"


def test_b2_files_mode_does_not_walk_repo(tmp_path, monkeypatch):
    """Isolation proof: with `files` given, `_gather_weak_test_files` is NOT
    consulted -- monkeypatch it to raise and confirm gather_weak_tests succeeds."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path, files=_REPO_FILES)))
    weakpath = str(pathlib.Path(cfg.repo) / "test_weak.py")

    def boom(repo):
        raise AssertionError("_gather_weak_test_files must NOT be consulted in files mode")

    monkeypatch.setattr(foundry, "_gather_weak_test_files", boom)
    s = foundry.gather_weak_tests(cfg, files=[weakpath])   # must NOT raise
    assert s.files_scanned == 1 and [f[1] for f in s.findings] == ["test_b"]


def test_b2_files_mode_multiple_paths(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, files={
        "test_weak.py": "def test_b():\n    pass\n",
        "test_weak2.py": "def test_c():\n    pass\n",
        "test_ignored.py": "def test_should_not_appear():\n    pass\n",
    })))
    p1 = str(pathlib.Path(cfg.repo) / "test_weak.py")
    p2 = str(pathlib.Path(cfg.repo) / "test_weak2.py")
    s = foundry.gather_weak_tests(cfg, files=[p1, p2])
    assert s.files_scanned == 2, f"exactly the two given paths, got {s.files_scanned}"
    assert sorted(f[1] for f in s.findings) == ["test_b", "test_c"]
    assert all("test_ignored.py" not in f[0] for f in s.findings), \
        "an unlisted repo file must NOT be scanned in files mode"


def test_b2_files_mode_folds_oserror(tmp_path):
    """A path.read_text() OSError (e.g. missing file) is folded into
    parse_errors -- never propagated."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path, files={"test_weak.py": "def test_b():\n    pass\n"})))
    missing = str(pathlib.Path(cfg.repo) / "does_not_exist.py")
    s = foundry.gather_weak_tests(cfg, files=[missing])   # must NOT raise
    assert s.files_scanned == 1
    assert len(s.parse_errors) == 1 and s.parse_errors[0][0].endswith("does_not_exist.py")
    assert s.parse_errors[0][1].startswith("FileNotFoundError:"), \
        f"the OSError type name must lead the message, got {s.parse_errors[0][1]!r}"


def test_b2_files_mode_empty_list_nothing_to_scan(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, files=_REPO_FILES)))
    s = foundry.gather_weak_tests(cfg, files=[])
    assert s.files_scanned == 0 and s.exit_code == 2 and s.clean is False


# ==========================================================================
# Behavior 3 -- weak_tests_cli delegates to gather_weak_tests; byte-identical
# ==========================================================================
def test_b3_cli_human_uses_gather_weak_tests_return(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    scripted = foundry.summarize_weak_tests(
        product="scriptedprod", files_scanned=3,
        findings=(("a.py", "test_a"), ("b.py", "test_b")), parse_errors=())
    monkeypatch.setattr(foundry, "gather_weak_tests", lambda cfg, files=None: scripted)
    rc, out, _ = _capture(lambda: foundry.weak_tests_cli(cfg))
    assert rc == scripted.exit_code, "weak_tests_cli must return gather_weak_tests().exit_code"
    assert out.rstrip("\n") == scripted.render().rstrip("\n"), \
        f"human output must equal gather_weak_tests().render():\n{out}"


def test_b3_cli_json_uses_gather_weak_tests_return(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    scripted = foundry.summarize_weak_tests(
        product="scriptedprod", files_scanned=3,
        findings=(("a.py", "test_a"),), parse_errors=())
    monkeypatch.setattr(foundry, "gather_weak_tests", lambda cfg, files=None: scripted)
    rc, out, _ = _capture(lambda: foundry.weak_tests_cli(cfg, as_json=True))
    assert rc == scripted.exit_code
    assert json.loads(out) == scripted.to_dict(), \
        "weak-tests --json must be json of gather_weak_tests().to_dict()"
    assert out.strip() == json.dumps(scripted.to_dict(), indent=2), \
        "the JSON doc must be indent=2 pretty-printed (byte-identical to iter-23)"


def test_b3_cli_delegation_is_a_single_seam(tmp_path, monkeypatch):
    """A fully-scripted duck object proves weak_tests_cli blindly consumes
    whatever gather_weak_tests returns -- render() for human, to_dict() for
    --json, exit_code for the return."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))

    class _Fake:
        exit_code = 7

        def render(self):
            return "FAKE-WEAK-RENDER"

        def to_dict(self):
            return {"scripted": True}

    monkeypatch.setattr(foundry, "gather_weak_tests", lambda cfg, files=None: _Fake())
    rc, out, _ = _capture(lambda: foundry.weak_tests_cli(cfg))
    assert rc == 7 and "FAKE-WEAK-RENDER" in out, \
        f"patched gather_weak_tests must be the single gathering seam:\n{out}"
    rc2, out2, _ = _capture(lambda: foundry.weak_tests_cli(cfg, as_json=True))
    assert rc2 == 7 and json.loads(out2) == {"scripted": True}


def test_b3_cli_forwards_files_to_gather_weak_tests(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    seen = []
    scripted = foundry.summarize_weak_tests(product="p", files_scanned=1, findings=(), parse_errors=())

    def fake_gather(cfg, files=None):
        seen.append(files)
        return scripted

    monkeypatch.setattr(foundry, "gather_weak_tests", fake_gather)
    foundry.weak_tests_cli(cfg, files=["/x/test_z.py"])
    assert seen == [["/x/test_z.py"]], f"--files must flow through to gather_weak_tests: {seen}"


def test_b3_cli_files_mode_byte_identical_to_directly_built_summary(tmp_path):
    """Behaviors 2+3 together: the CLI's human + --json + --files output is
    byte-identical to a DIRECTLY-built WeakTestSummary for the same scan."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path, files={
        "test_weak.py": "def test_b():\n    pass\n",
        "test_other.py": "def test_c():\n    pass\n",
    })))
    weakpath = str(pathlib.Path(cfg.repo) / "test_weak.py")
    expected = foundry.summarize_weak_tests(
        product=cfg.name, files_scanned=1,
        findings=((weakpath, "test_b"),), parse_errors=())
    before = _snapshot_tree(tmp_path)
    # human --files mode
    rc_h, out_h, _ = _capture(lambda: foundry.weak_tests_cli(cfg, files=[weakpath]))
    assert rc_h == expected.exit_code == 1
    assert out_h.rstrip("\n") == expected.render().rstrip("\n"), \
        f"human --files output must equal the directly-built summary render():\n{out_h}"
    assert "test_other.py" not in out_h, "--files must NOT walk the repo"
    # json --files mode
    rc_j, out_j, _ = _capture(lambda: foundry.weak_tests_cli(cfg, files=[weakpath], as_json=True))
    assert rc_j == expected.exit_code == 1
    assert json.loads(out_j) == expected.to_dict()
    assert out_j.strip() == json.dumps(expected.to_dict(), indent=2)
    assert _snapshot_tree(tmp_path) == before, "weak-tests wrote to disk (must be read-only)"


def test_b3_cli_output_preserved_end_to_end_via_main(tmp_path):
    """Regression: with real files, human + --json + --files + exit code via
    `main` behave exactly as iter 22/23 (no observable drift from the extraction)."""
    cfg_path = _write_cfg(tmp_path, files=_REPO_FILES)
    before = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["weak-tests", "--config", str(cfg_path)])
    assert rc == 1, f"a repo with a weak + unparseable test must exit 1:\n{out}"
    assert "test_weak.py" in out and "test_b" in out, f"finding must surface:\n{out}"
    assert re.search(r"(?i)parse error|syntaxerror", out), f"parse error must surface:\n{out}"
    assert "Traceback" not in out, f"CLI must degrade gracefully:\n{out}"
    # --json path is a single JSON document with the frozen 8-key shape
    rc_j, out_j = _run_cli(["weak-tests", "--config", str(cfg_path), "--json"])
    assert rc_j == 1
    doc = json.loads(out_j.strip())
    assert list(doc.keys()) == [
        "product", "files_scanned", "total_findings", "clean",
        "exit_code", "verdict", "findings", "parse_errors",
    ], f"to_dict key order drifted: {list(doc.keys())}"
    assert doc["files_scanned"] == 3 and doc["exit_code"] == 1
    assert _snapshot_tree(tmp_path) == before, "weak-tests wrote a file (must be read-only)"
    # a clean repo -> exit 0 (separate cfg, outside the read-only snapshot)
    clean_cfg = _write_cfg(tmp_path / "clean", files={"test_ok.py": "def test_a():\n    assert 1\n"})
    rc0, out0 = _run_cli(["weak-tests", "--config", str(clean_cfg)])
    assert rc0 == 0, f"an all-asserting repo must exit 0:\n{out0}"


def test_b3_reused_pure_symbols_unchanged():
    """WeakTestSummary (8-key to_dict / render / exit_code), the reused helpers,
    and the two patchable constants are UNCHANGED by this extraction."""
    s = foundry.summarize_weak_tests(
        product="p", files_scanned=2, findings=(("t.py", "test_a"),), parse_errors=())
    d = s.to_dict()
    assert list(d.keys()) == [
        "product", "files_scanned", "total_findings", "clean",
        "exit_code", "verdict", "findings", "parse_errors",
    ] and len(d) == 8
    assert s.exit_code == 1 and s.clean is False and s.total_findings == 1
    assert "test_a" in s.render() and "t.py" in s.render()
    # reused helpers still present + callable
    for name in ("find_assertionless_tests", "_gather_weak_test_files", "summarize_weak_tests",
                 "weak_tests_cli", "WeakTestSummary"):
        assert hasattr(foundry, name), f"reused symbol {name!r} vanished"
    # constants unchanged
    assert foundry.WEAK_TEST_GLOBS == ("test_*.py", "*_test.py")
    assert isinstance(foundry.WEAK_TEST_ASSERTION_CALLS, frozenset)
    for expected in ("raises", "warns", "fail"):
        assert expected in foundry.WEAK_TEST_ASSERTION_CALLS
    # weak_tests_cli signature preserved (cfg, files=None, as_json=False)
    sig = inspect.signature(foundry.weak_tests_cli)
    assert list(sig.parameters) == ["cfg", "files", "as_json"]
    assert sig.parameters["as_json"].default is False


# ==========================================================================
# Behavior 4 -- dormant, off the control path, import-safe, no new surface
# ==========================================================================
def test_b4_both_modules_import():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b4_new_surface_present_and_callable():
    assert callable(foundry.gather_weak_tests)
    sig = inspect.signature(foundry.gather_weak_tests)
    assert list(sig.parameters) == ["cfg", "files"], f"unexpected signature: {sig}"
    assert sig.parameters["files"].default is None
    # pre-existing control-flow entry points remain (regression)
    for fn in CONTROL_FLOW_FNS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"


def test_b4_gather_weak_tests_absent_from_foundry_control_flow():
    for fn_name in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references {sym!r} (must stay off the control path)"
        assert "weak-tests" not in consts, \
            f"{fn_name} embeds the 'weak-tests' subcommand literal"
        assert "company-weak-tests" not in consts, \
            f"{fn_name} contains the 'company-weak-tests' literal (that is bite 2)"


def test_b4_gather_weak_tests_absent_from_dispatcher():
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, consts = _module_names_consts(dispatcher)
    assert "gather_weak_tests" not in names, "dispatcher references gather_weak_tests"
    assert "company-weak-tests" not in consts, "dispatcher references the 'company-weak-tests' literal"


def test_b4_company_weak_tests_subcommand_present_after_bite2(capsys):
    # iter 42 (bite 1) shipped ONLY the `gather_weak_tests` foundation and this
    # guard asserted the `company-weak-tests` subcommand was still absent
    # ("deferred to bite 2"). iter 43 (bite 2) is that deferred bite: it
    # legitimately ships the subcommand, so the guard's retirement condition has
    # now occurred (identical to how iter 40 flipped the iter-39 `company-timing`
    # guard). The regression half (every pre-existing subcommand still present)
    # is kept; the negative half is flipped to assert the now-shipped
    # `company-weak-tests` subcommand appears in --help.
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    # every pre-existing subcommand (incl. the earlier company-* members) survives
    for sub in ("weak-tests", "company-status", "company-history", "company-timing"):
        assert sub in out, f"existing subcommand {sub!r} missing from --help:\n{out}"
    # ... and bite 2 has now added the `company-weak-tests` subcommand
    assert "company-weak-tests" in out, \
        "bite 2 (iter 43) must add the company-weak-tests subcommand"


def test_b4_running_writes_nothing(tmp_path):
    cfg_path = _write_cfg(tmp_path, files=_REPO_FILES)
    before = _snapshot_tree(tmp_path)
    rc, _ = _run_cli(["weak-tests", "--config", str(cfg_path)])
    assert rc in (0, 1, 2)
    assert _snapshot_tree(tmp_path) == before, "weak-tests created/modified files (read-only violation)"


def test_b4_release_sentinels_unchanged():
    _, consts = _module_names_consts(foundry)
    for sentinel in ("VERDICT:", "RESULT:", "ACTION:", "POSTRELEASE:"):
        assert any(sentinel in c for c in consts), \
            f"sentinel prefix {sentinel!r} vanished from foundry"
    for status in ("shipped", "no-ship", "infra-fail"):
        assert status in consts, f"res['status'] value {status!r} vanished from foundry"
