"""Black-box behaviour tests for iter 15 -- the PURE, offline, repo-agnostic
diff-scope classifier `classify_gate_scope(changed_paths) -> GateScope` (buckets
every changed path into test/doc/source and derives a conservative `light`
verdict = every changed path is a test file) plus the DORMANT on-demand
`foundry gate-scope --config <cfg> [--base REF] [--files ...]` CLI that reports
the classification. The final gate does NOT consult it this iteration.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-13) and the product's own OBSERVABLE behaviour only. The
implementation source (foundry.py / dispatcher.py internals), the engineer's and
reviewer's notes, and `git diff` were NOT read. Every check drives the PUBLIC
interface: the pure fn via `foundry.classify_gate_scope(...)`, the constants via
`foundry.GATE_TEST_DIR_NAMES` / `foundry.GATE_DOC_SUFFIXES`, and the CLI via
`foundry.main(["gate-scope", ...])` against a TMP-`repo` config (the real repo is
never touched). The dormancy / off-control-path checks (Behavior 13) use only
public RUNTIME introspection -- module attributes, `--help` output, and compiled
function name/const tables (`__code__.co_names` / `co_consts`) -- NOT the source
text. Fully offline and deterministic: real temp files only; the git-driven CLI
path is forced through the documented module-level `foundry.run_cmd` seam, so
there is NO real subprocess / git / network / agent-run (except the `--help`
regression probe, which only prints usage + exits).
"""
import io
import json
import pathlib
import re
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
class _Res:
    """Stand-in for the run_cmd result type: only `.ok`/`.out` are contracted
    (mirrors tests/test_iter02_behavior.py + tests/test_iter13_behavior.py)."""
    def __init__(self, ok, out=""):
        self.ok = bool(ok)
        self.out = out


def make_diff_seam(out_lines, *, ok=True, recorder=None):
    """Scripted, offline replacement for foundry.run_cmd. Returns the given
    newline-joined paths for a `git diff --name-only` invocation; records every
    call for argv/cwd assertions."""
    payload = "\n".join(out_lines)

    def _run_cmd(args, cwd=None, timeout=None):
        if recorder is not None:
            recorder.append({"args": list(args), "cwd": cwd})
        return _Res(ok, payload if ok else "fatal: bad revision")
    return _run_cmd


def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir (mirrors the suite's convention).
    `repo` is a TMP dir so the real foundry repo is NEVER touched."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
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


NEW_SYMBOLS = (
    "classify_gate_scope", "GateScope", "gate_scope_cli",
    "GATE_TEST_DIR_NAMES", "GATE_DOC_SUFFIXES",
)
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")


# ==========================================================================
# A. Pure classifier  classify_gate_scope(changed_paths) -> GateScope
# ==========================================================================

# --- Behavior 1 -- empty / blank-only input -> nothing, not light ----------
def test_b01_empty_input_not_light():
    r = foundry.classify_gate_scope([])
    assert (r.changed, r.source, r.test, r.doc) == ((), (), (), ()), \
        f"empty input must produce all-empty buckets, got {r!r}"
    assert r.light is False, "empty diff must NOT be light"
    assert r.scope == "full", f"empty diff scope must be 'full', got {r.scope!r}"


def test_b01_whitespace_only_entries_dropped():
    blank = foundry.classify_gate_scope(["", "  ", "\t"])
    empty = foundry.classify_gate_scope([])
    assert (blank.changed, blank.source, blank.test, blank.doc) \
        == (empty.changed, empty.source, empty.test, empty.doc), \
        f"whitespace-only entries must be dropped, got {blank!r}"
    assert blank.light is False and blank.scope == "full"


# --- Behavior 2 -- test files -> test bucket, light ------------------------
def test_b02_test_files_are_light():
    paths = ["tests/test_x.py", "src/pkg/foo_test.py", "conftest.py", "a/b/tests/helper.py"]
    r = foundry.classify_gate_scope(paths)
    assert list(r.test) == paths, f"all four must be test paths in input order, got {r.test!r}"
    assert r.source == (), f"no source expected, got {r.source!r}"
    assert r.doc == (), f"no doc expected, got {r.doc!r}"
    assert r.light is True, "an all-test diff must be light"
    assert r.scope == "light", f"scope must be 'light', got {r.scope!r}"


# --- Behavior 3 -- source files -> source bucket, full ---------------------
def test_b03_source_files_are_full():
    paths = ["foundry.py", "dispatcher.py", "src/pkg/app.py"]
    r = foundry.classify_gate_scope(paths)
    assert list(r.source) == paths, f"all three must be source, got {r.source!r}"
    assert r.test == (), f"no test expected, got {r.test!r}"
    assert r.doc == (), f"no doc expected, got {r.doc!r}"
    assert r.light is False, "a source diff must NOT be light"
    assert r.scope == "full", f"scope must be 'full', got {r.scope!r}"


# --- Behavior 4 -- doc files -> doc bucket, NOT light (conservative) --------
def test_b04_doc_files_not_light():
    paths = ["README.md", "ARCHITECTURE.md", "roles/pm.md", "docs/x.rst", "notes.txt"]
    r = foundry.classify_gate_scope(paths)
    assert list(r.doc) == paths, f"all five must be doc, got {r.doc!r}"
    assert r.source == (), f"no source expected, got {r.source!r}"
    assert r.test == (), f"no test expected, got {r.test!r}"
    assert r.light is False, "a doc-only diff is deliberately NOT light (docs may encode behavior)"
    assert r.scope == "full", f"scope must be 'full', got {r.scope!r}"


# --- Behavior 5 -- test-check wins over doc-suffix -------------------------
def test_b05_test_check_beats_doc_suffix():
    r = foundry.classify_gate_scope(["tests/fixtures/sample.md"])
    assert r.test == ("tests/fixtures/sample.md",), \
        f"a .md file under a test dir must be TEST, got test={r.test!r} doc={r.doc!r}"
    assert r.doc == (), "the doc bucket must be empty (test-check wins)"
    assert r.light is True, "a test-dir doc-suffixed file makes an all-test, light diff"
    assert r.scope == "light"


def test_b05_test_basename_with_doc_suffix_is_test():
    # a doc-suffixed basename that also matches a test-basename rule -> TEST.
    r = foundry.classify_gate_scope(["conftest.py"])
    assert r.test == ("conftest.py",) and r.doc == () and r.source == ()


# --- Behavior 6 -- any source OR doc makes the diff full -------------------
def test_b06_test_plus_source_is_full():
    r = foundry.classify_gate_scope(["tests/test_x.py", "foundry.py"])
    assert r.test == ("tests/test_x.py",), f"test bucket wrong: {r.test!r}"
    assert r.source == ("foundry.py",), f"source bucket wrong: {r.source!r}"
    assert r.doc == ()
    assert r.light is False, "presence of source must defeat light"
    assert r.scope == "full"


def test_b06_test_plus_doc_is_full():
    r = foundry.classify_gate_scope(["tests/test_x.py", "README.md"])
    assert r.test == ("tests/test_x.py",)
    assert r.doc == ("README.md",)
    assert r.light is False, "presence of a doc must defeat light (conservative)"
    assert r.scope == "full"


# --- Behavior 7 -- partition invariant -------------------------------------
def test_b07_partition_invariant():
    raw = [
        "tests/test_a.py", "foundry.py", "README.md", "", "  ",
        "src/pkg/x.py", "conftest.py", "docs/y.rst", "\t", "roles/pm.md",
    ]
    r = foundry.classify_gate_scope(raw)
    nonblank = [p for p in raw if p.strip()]
    # order preserved after dropping blanks
    assert list(r.changed) == nonblank, f"changed must preserve input order sans blanks, got {r.changed!r}"
    test, doc, source, changed = set(r.test), set(r.doc), set(r.source), set(r.changed)
    # pairwise disjoint
    assert test & doc == set(), f"test/doc overlap: {test & doc}"
    assert test & source == set(), f"test/source overlap: {test & source}"
    assert doc & source == set(), f"doc/source overlap: {doc & source}"
    # exact cover
    assert changed == test | doc | source, "buckets must exactly cover changed"
    assert len(r.test) + len(r.doc) + len(r.source) == len(r.changed), \
        "bucket sizes must sum to len(changed)"


# --- Behavior 8 -- total/never-raises + call-time constant read ------------
def test_b08_never_raises_for_any_string_iterable():
    weird = iter([
        "a/b/c/d/e.py", "..", ".", "/abs/path.py", "no_ext",
        "spaces in name.md", "un\u00efcode.txt", "a" * 300 + ".py", "///",
    ])
    r = foundry.classify_gate_scope(weird)  # accepts a generator, must not raise
    assert isinstance(r, foundry.GateScope)
    # exhaustive partition still holds on the exotic input
    assert len(r.test) + len(r.doc) + len(r.source) == len(r.changed)


def test_b08_doc_suffixes_read_at_call_time(monkeypatch):
    before = foundry.classify_gate_scope(["app.py"])
    assert before.source == ("app.py",), "a plain .py is source under default suffixes"
    monkeypatch.setattr(foundry, "GATE_DOC_SUFFIXES", foundry.GATE_DOC_SUFFIXES + (".py",))
    after = foundry.classify_gate_scope(["app.py"])
    assert after.doc == ("app.py",), "patching GATE_DOC_SUFFIXES must reclassify a later call's .py as doc"
    assert after.source == (), "app.py must leave the source bucket after the patch"
    # a genuine test .py still wins for test even with .py in doc suffixes
    t = foundry.classify_gate_scope(["tests/test_x.py"])
    assert t.test == ("tests/test_x.py",), "test-check must still beat the (patched) doc suffix"


def test_b08_test_dir_names_read_at_call_time(monkeypatch):
    before = foundry.classify_gate_scope(["vendor/lib.py"])
    assert before.source == ("vendor/lib.py",), "vendor/ is source under default dir names"
    monkeypatch.setattr(foundry, "GATE_TEST_DIR_NAMES", foundry.GATE_TEST_DIR_NAMES + ("vendor",))
    after = foundry.classify_gate_scope(["vendor/lib.py"])
    assert after.test == ("vendor/lib.py",), "patching GATE_TEST_DIR_NAMES must reclassify a later path as test"
    assert after.source == ()


# --- Behavior 9 -- `light` semantics + `scope` derivation ------------------
def test_b09_light_semantics():
    # light iff >=1 change AND no source AND no doc
    assert foundry.classify_gate_scope([]).light is False              # 0 changes
    assert foundry.classify_gate_scope(["tests/test_a.py"]).light is True
    assert foundry.classify_gate_scope(["tests/test_a.py", "x.py"]).light is False   # source present
    assert foundry.classify_gate_scope(["tests/test_a.py", "x.md"]).light is False   # doc present
    # scope tracks light exactly
    for paths, exp in [([], "full"), (["tests/test_a.py"], "light"),
                       (["x.py"], "full"), (["x.md"], "full")]:
        r = foundry.classify_gate_scope(paths)
        assert r.scope == exp, f"{paths}: scope expected {exp!r}, got {r.scope!r}"
        assert (r.scope == "light") == r.light, "scope and light must agree"


def test_b09_gatescope_is_frozen_dataclass():
    import dataclasses
    r = foundry.classify_gate_scope(["tests/test_a.py"])
    assert type(r).__name__ == "GateScope"
    assert dataclasses.is_dataclass(r)
    for f in ("changed", "source", "test", "doc"):
        assert isinstance(getattr(r, f), tuple), f"field {f!r} must be a tuple, got {type(getattr(r,f))}"
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.changed = ()  # frozen: assignment must raise


# --- Constant defaults -----------------------------------------------------
def test_constants_are_patchable_tuples_with_sane_defaults():
    assert isinstance(foundry.GATE_TEST_DIR_NAMES, tuple) and foundry.GATE_TEST_DIR_NAMES
    assert isinstance(foundry.GATE_DOC_SUFFIXES, tuple) and foundry.GATE_DOC_SUFFIXES
    assert "tests" in foundry.GATE_TEST_DIR_NAMES, "a generic 'tests' dir name expected by default"
    assert ".md" in foundry.GATE_DOC_SUFFIXES, "a generic '.md' doc suffix expected by default"


# ==========================================================================
# B. CLI  foundry gate-scope --config <cfg> [--base REF] [--files ...]
# ==========================================================================

# --- Behavior 10 -- --files coverage-only -> exit 0, scope: light ----------
def test_b10_files_light_exit0(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    before_repo, before_work = _snapshot_tree(cfg.repo), _snapshot_tree(cfg.work_root)
    before_cfgdir = _snapshot_tree(tmp_path)
    files = ["tests/test_a.py", "b/tests/c.py"]
    rc, out = _run_cli(["gate-scope", "--config", str(cfg_path), "--files", *files])
    assert rc == 0, f"coverage-only diff must exit 0, got {rc}\n{out}"
    assert "scope: light" in out, f"report must contain literal 'scope: light':\n{out}"
    st = foundry.classify_gate_scope(files)
    # bucket counts reported (label + count, whitespace-tolerant)
    for label, n in (("changed", len(st.changed)), ("test", len(st.test)),
                     ("doc", len(st.doc)), ("source", len(st.source))):
        assert re.search(rf"{label}\D*{n}\b", out), f"report missing count for {label}={n}:\n{out}"
    # writes NOTHING
    assert _snapshot_tree(cfg.repo) == before_repo, "gate-scope wrote under the repo"
    assert _snapshot_tree(cfg.work_root) == before_work, "gate-scope wrote under work_root"
    assert _snapshot_tree(tmp_path) == before_cfgdir, "gate-scope wrote a new file in the config dir"


# --- Behavior 11 -- --files has source -> exit 1, scope: full --------------
def test_b11_files_full_exit1(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    before = _snapshot_tree(tmp_path)
    files = ["foundry.py", "tests/test_a.py"]
    rc, out = _run_cli(["gate-scope", "--config", str(cfg_path), "--files", *files])
    assert rc == 1, f"a diff containing source must exit 1, got {rc}\n{out}"
    assert "scope: full" in out, f"report must contain literal 'scope: full':\n{out}"
    assert _snapshot_tree(tmp_path) == before, "gate-scope wrote to disk"


# --- Behavior 12 -- git-driven path via the run_cmd seam -------------------
def test_b12_git_path_light_exit0(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    rec = []
    monkeypatch.setattr(foundry, "run_cmd",
                        make_diff_seam(["tests/test_a.py", "pkg/tests/b.py", "conftest.py"], recorder=rec))
    before = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["gate-scope", "--config", str(cfg_path)])
    assert rc == 0, f"test-only git diff must exit 0, got {rc}\n{out}"
    assert "scope: light" in out, f"report must contain 'scope: light':\n{out}"
    # the seam was driven with a git diff --name-only against origin/<branch> in cfg.repo
    diff_calls = [c for c in rec if "diff" in c["args"] and "--name-only" in c["args"]]
    assert diff_calls, f"run_cmd was not called with a 'git diff --name-only' argv: {rec}"
    joined = " ".join(diff_calls[0]["args"])
    assert f"origin/{cfg.branch}" in joined, f"default base must be origin/<branch>: {joined!r}"
    assert cfg.repo in joined or diff_calls[0]["cwd"] == cfg.repo, \
        f"the diff must reference cfg.repo (argv or cwd): args={diff_calls[0]['args']} cwd={diff_calls[0]['cwd']}"
    assert _snapshot_tree(tmp_path) == before, "git-path gate-scope wrote to disk"


def test_b12_git_path_full_exit1(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    monkeypatch.setattr(foundry, "run_cmd",
                        make_diff_seam(["tests/test_a.py", "foundry.py"]))
    rc, out = _run_cli(["gate-scope", "--config", str(cfg_path)])
    assert rc == 1, f"git diff containing a source path must exit 1, got {rc}\n{out}"
    assert "scope: full" in out, f"report must contain 'scope: full':\n{out}"


def test_b12_git_path_custom_base(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    rec = []
    monkeypatch.setattr(foundry, "run_cmd",
                        make_diff_seam(["tests/test_a.py"], recorder=rec))
    rc, out = _run_cli(["gate-scope", "--config", str(cfg_path), "--base", "deadbeef"])
    assert rc == 0, f"custom-base test-only diff must exit 0, got {rc}\n{out}"
    diff_calls = [c for c in rec if "diff" in c["args"] and "--name-only" in c["args"]]
    joined = " ".join(diff_calls[0]["args"])
    assert "deadbeef" in joined, f"--base value must appear in the diff argv: {joined!r}"
    assert f"origin/{cfg.branch}" not in joined, \
        f"--base must OVERRIDE the origin/<branch> default: {joined!r}"


def test_b12_git_seam_failure_exit2_writes_nothing(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    monkeypatch.setattr(foundry, "run_cmd", make_diff_seam([], ok=False))
    before_repo = _snapshot_tree(cfg.repo)
    before_cfgdir = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["gate-scope", "--config", str(cfg_path)])
    assert rc == 2, f"a failing git seam must exit 2, got {rc}\n{out}"
    assert out.strip(), "exit 2 must print an error line"
    assert _snapshot_tree(cfg.repo) == before_repo, "failed git path wrote under the repo"
    assert _snapshot_tree(tmp_path) == before_cfgdir, "failed git path wrote to disk"


def test_b12_cli_classification_matches_pure_helper(tmp_path, monkeypatch):
    # the CLI adds NO classification logic beyond splitlines -> classify_gate_scope;
    # so its verdict must equal the pure helper on the same seam output.
    cfg_path = _write_cfg(tmp_path)
    lines = ["tests/test_a.py", "src/x.py", "README.md", "conftest.py"]
    monkeypatch.setattr(foundry, "run_cmd", make_diff_seam(lines))
    rc, out = _run_cli(["gate-scope", "--config", str(cfg_path)])
    st = foundry.classify_gate_scope(lines)
    assert st.scope == "full"
    assert rc == (0 if st.light else 1), "CLI exit must track classify_gate_scope(.light)"
    assert f"scope: {st.scope}" in out
    for label, n in (("test", len(st.test)), ("doc", len(st.doc)), ("source", len(st.source))):
        assert re.search(rf"{label}\D*{n}\b", out), f"CLI bucket count for {label} must match helper:\n{out}"


# ==========================================================================
# C. Behavior 13 -- dormant & off the control path (public introspection)
# ==========================================================================
def test_b13_both_modules_import():
    import subprocess
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b13_new_surface_present_and_callable():
    assert callable(foundry.classify_gate_scope)
    assert callable(foundry.gate_scope_cli)
    assert hasattr(foundry, "GateScope")
    assert isinstance(foundry.GATE_TEST_DIR_NAMES, tuple)
    assert isinstance(foundry.GATE_DOC_SUFFIXES, tuple)
    # pre-existing control-flow entry points remain present + callable (regression)
    for fn in CONTROL_FLOW_FNS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"


def test_b13_new_symbols_absent_from_foundry_control_flow():
    for fn_name in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, f"{fn_name} references new symbol {sym!r} (must stay off the control path)"
        assert "gate-scope" not in consts, f"{fn_name} embeds the 'gate-scope' string (must stay off the control path)"


def test_b13_new_symbols_absent_from_dispatcher():
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, consts = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in names, f"dispatcher references new symbol {sym!r}"
    assert "gate-scope" not in consts, "dispatcher embeds the 'gate-scope' subcommand string"


def test_b13_help_lists_existing_plus_gate_scope(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for sub in ("run", "once", "doctor", "learnings", "agents", "lint-spec", "prd", "gate-scope"):
        assert sub in out, f"subcommand {sub!r} missing from --help:\n{out}"


def test_b13_sentinels_and_status_values_unchanged():
    # Non-regression: the additive bite must not remove/rename the release
    # sentinels or the ship-outcome status vocabulary. Encoded via public
    # compiled-const introspection (not source text). The four release-sentinel
    # PREFIXES are role-output parse literals and are reliably present:
    _, consts = _module_names_consts(foundry)
    for sentinel in ("VERDICT:", "RESULT:", "ACTION:", "POSTRELEASE:"):
        assert any(sentinel in c for c in consts), f"sentinel prefix {sentinel!r} vanished from foundry"
    # The ship-outcome res["status"] values that flow through the gate parsing
    # are exact literals -> assert intact:
    for status in ("shipped", "no-ship", "infra-fail"):
        assert status in consts, f"res['status'] value {status!r} vanished from foundry"
    # NOTE (PM feedback / ambiguity): the spec also lists "stopped" as a status
    # value, but it is a documented STOP-file outcome (see ARCHITECTURE.md /
    # CONTINUOUS.md), NOT a locatable Python string literal in either module, and
    # no existing test asserts it as a literal. Its non-regression is therefore
    # guarded by the full control-flow suite (iter02/03 drive run_iteration /
    # run_continuous and assert res["status"]), not by a brittle literal scan.
    # We still confirm the status-producing entry points remain intact:
    for fn in ("run_iteration", "run_continuous"):
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing (status-producer regression)"
