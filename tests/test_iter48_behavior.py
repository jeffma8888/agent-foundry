"""Black-box behaviour tests for iter 48 -- the read-only `foundry
constant-asserts --config <cfg> [--files ...] [--json]` CLI that surfaces the
shipped (iter-47) `find_constant_assert_tests` detector: it reports `test*`
functions whose ONLY assertion signal is a constant/tautological assert
(`assert True` / `assert 1` / `assert "x"`) -- the weak-test class that
`foundry weak-tests` (iter 22, which flags assertion-FREE tests) structurally
MISSES because a constant assert CARRIES an assert node.

New public surface exercised here (a STRUCTURAL MIRROR of the shipped
weak-tests machinery, differing ONLY in the detector it parses through and three
human labels): frozen `ConstantAssertSummary`, pure keyword-only
`summarize_constant_asserts(...)`, the `gather_constant_asserts` seam, and the
`constant_asserts_cli` / `main(["constant-asserts", ...])` entry.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-48 PM
spec's Expected Behaviors (1-10), the product README/roadmap, the `tests/`
conventions (esp. tests/test_iter22_behavior.py -- the weak-tests mirror -- and
tests/test_iter47_behavior.py -- the detector), and the product's OWN OBSERVABLE
behaviour (by RUNNING it / public RUNTIME introspection: module attrs,
`--help` output, compiled `__code__.co_names` tables). The implementation SOURCE
(foundry.py / dispatcher.py source text), the engineer's and reviewer's notes,
and `git diff` were NOT read. Behavior 8's weak-tests non-regression is verified
as a BLACK-BOX matrix of the shipped `weak-tests` OBSERVABLE output/JSON/exit
(NOT a `git show HEAD:foundry.py` two-module byte-diff, which would require
loading prior implementation source -- that is the reviewer's/engineer's tool,
not the isolated tester's). Every check drives the PUBLIC interface: the summary
builder via `foundry.summarize_constant_asserts(...)`, the seam via
`foundry.gather_constant_asserts(...)`, and the CLI via
`foundry.constant_asserts_cli(...)` / `foundry.main([...])` against a TMP-`repo`
config with real temp test files (the real foundry repo is NEVER touched). The
dormancy / off-control-path checks (Behavior 9) use only public RUNTIME
introspection (module attributes + compiled `__code__.co_names`), NOT source
text. Fully offline & deterministic: real temp files only, ZERO real
git/network/clock/agent-run (except the documented `import foundry, dispatcher`
regression probe and the `--help` usage probe); every CLI test snapshots the tmp
tree to prove the writes-nothing / read-only contract.
"""
import contextlib
import dataclasses
import io
import json
import pathlib
import subprocess
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers  (mirror tests/test_iter22_behavior.py + test_iter42_behavior.py)
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


def _fn_names(fn):
    """Set of every global/attr name reachable from fn's compiled code object
    (recursing into nested code objects) -- public runtime introspection, NOT
    source text, so the dormancy check honors the isolation contract."""
    stack, seen, names = [fn.__code__], set(), set()
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names |= set(code.co_names)
        for c in code.co_consts:
            if isinstance(c, types.CodeType):
                stack.append(c)
    return names


def _module_names(module):
    """Union of names across every function/method reachable from a module's
    public namespace (recursively into nested code objects)."""
    names = set()
    for v in vars(module).values():
        if isinstance(v, types.FunctionType):
            names |= _fn_names(v)
        elif isinstance(v, type):
            for m in vars(v).values():
                if isinstance(m, types.FunctionType):
                    names |= _fn_names(m)
    return names


NEW_SYMBOLS = (
    "ConstantAssertSummary",
    "summarize_constant_asserts",
    "gather_constant_asserts",
    "constant_asserts_cli",
)
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")

# a single source carrying all three species: assertion-free, constant-only,
# and a real (Compare) assert -- the disjointness fixture reused across tests.
MIX_SRC = (
    "def test_free():\n    x = compute()\n\n"
    "def test_const():\n    assert True\n\n"
    "def test_real():\n    assert y == 2\n"
)


# ==========================================================================
# Behavior 1 -- summarize_constant_asserts: fields, keyword-only, frozen
# ==========================================================================
def test_b01_summary_basic_fields():
    s = foundry.summarize_constant_asserts(
        product="p", files_scanned=2, findings=(("a.py", "test_x"),), parse_errors=()
    )
    assert type(s).__name__ == "ConstantAssertSummary", f"wrong type: {type(s).__name__}"
    assert dataclasses.is_dataclass(s)
    assert s.product == "p", s.product
    assert s.files_scanned == 2, s.files_scanned
    assert s.findings == (("a.py", "test_x"),), s.findings
    assert s.parse_errors == (), s.parse_errors
    assert s.total_findings == 1, f"total_findings must count findings, got {s.total_findings}"


def test_b01_keyword_only():
    with pytest.raises(TypeError):
        foundry.summarize_constant_asserts("p", 0, (), ())


def test_b01_frozen():
    s = foundry.summarize_constant_asserts(product="p", files_scanned=1, findings=(), parse_errors=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.files_scanned = 99


# ==========================================================================
# Behavior 2 -- exit_code / clean / verdict properties
# ==========================================================================
def _mk(files_scanned=2, findings=(), parse_errors=()):
    return foundry.summarize_constant_asserts(
        product="p", files_scanned=files_scanned, findings=findings, parse_errors=parse_errors
    )


def test_b02_exit_code_nothing_to_scan_checked_first():
    # files_scanned==0 -> 2, and this is checked FIRST (even with findings present).
    assert _mk(files_scanned=0).exit_code == 2
    assert _mk(files_scanned=0, findings=(("a.py", "t"),)).exit_code == 2, (
        "files_scanned==0 must win even when findings is non-empty (checked FIRST)"
    )


def test_b02_exit_code_findings_or_parse_errors():
    assert _mk(files_scanned=2, findings=(("a.py", "t"),)).exit_code == 1
    assert _mk(files_scanned=2, parse_errors=(("b.py", "SyntaxError: x"),)).exit_code == 1, (
        "parse_errors alone (findings empty) must still yield exit_code 1"
    )


def test_b02_exit_code_clean():
    assert _mk(files_scanned=2).exit_code == 0


def test_b02_clean_property():
    assert _mk(files_scanned=2).clean is True
    assert _mk(files_scanned=0).clean is False, "nothing-scanned must NOT be clean"
    assert _mk(files_scanned=2, findings=(("a.py", "t"),)).clean is False
    assert _mk(files_scanned=2, parse_errors=(("b.py", "e"),)).clean is False


def test_b02_verdict_map():
    assert _mk(files_scanned=2).verdict == "clean"
    assert _mk(files_scanned=2, findings=(("a.py", "t"),)).verdict == "CONSTANT ASSERTS FOUND"
    assert _mk(files_scanned=0).verdict == "nothing to scan"


# ==========================================================================
# Behavior 3 -- render(): deterministic multi-line report contract
# ==========================================================================
def test_b03_render_substrings_and_last_line():
    s = foundry.summarize_constant_asserts(
        product="demo", files_scanned=3,
        findings=(("x.py", "test_a"), ("y.py", "test_b")),
        parse_errors=(("bad.py", "SyntaxError: boom"),),
    )
    text = s.render()
    assert isinstance(text, str) and text.strip()
    assert "foundry constant-asserts -- demo" in text, text
    assert "files scanned: 3" in text, text
    assert "constant-assert tests: 2" in text, text
    # one `  <file> :: <test>` line per finding, in order
    assert "x.py :: test_a" in text, text
    assert "y.py :: test_b" in text, text
    assert text.index("x.py :: test_a") < text.index("y.py :: test_b"), "findings must render in order"
    # parse errors count + one `  <file>: <message>` line per error
    assert "parse errors: 1" in text, text
    assert "bad.py: SyntaxError: boom" in text, text
    # the LAST non-empty line is `verdict: <token>` matching exit_code
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[-1] == "verdict: CONSTANT ASSERTS FOUND", f"last non-empty line: {lines[-1]!r}"


def test_b03_render_clean_shows_no_test_names():
    s = foundry.summarize_constant_asserts(product="demo", files_scanned=2, findings=(), parse_errors=())
    text = s.render()
    assert "constant-assert tests: 0" in text, text
    assert "parse errors: 0" in text, text
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[-1] == "verdict: clean", f"clean verdict last line, got {lines[-1]!r}"


def test_b03_render_last_line_matches_exit_code():
    # verdict is the ONE source of truth for render()'s last line for every state.
    for s in (_mk(files_scanned=0), _mk(files_scanned=2), _mk(files_scanned=2, findings=(("a.py", "t"),))):
        lines = [ln for ln in s.render().splitlines() if ln.strip()]
        assert lines[-1] == f"verdict: {s.verdict}", (
            f"render last line must be `verdict: {s.verdict}`, got {lines[-1]!r}"
        )


# ==========================================================================
# Behavior 4 -- to_dict(): 8 keys in order, JSON-native, round-trips
# ==========================================================================
def test_b04_to_dict_exact_keys_in_order():
    s = foundry.summarize_constant_asserts(
        product="p", files_scanned=2,
        findings=(("a.py", "test_x"),), parse_errors=(("b.py", "SyntaxError: boom"),),
    )
    d = s.to_dict()
    assert list(d.keys()) == [
        "product", "files_scanned", "total_findings", "clean",
        "exit_code", "verdict", "findings", "parse_errors",
    ], f"to_dict keys/order wrong: {list(d.keys())}"


def test_b04_to_dict_list_shapes_in_order():
    s = foundry.summarize_constant_asserts(
        product="p", files_scanned=3,
        findings=(("a.py", "test_x"), ("b.py", "test_y")),
        parse_errors=(("c.py", "SyntaxError: boom"),),
    )
    d = s.to_dict()
    assert d["findings"] == [{"file": "a.py", "test": "test_x"}, {"file": "b.py", "test": "test_y"}], d["findings"]
    assert d["parse_errors"] == [{"file": "c.py", "message": "SyntaxError: boom"}], d["parse_errors"]


def test_b04_to_dict_round_trips_including_empty():
    for s in (
        foundry.summarize_constant_asserts(product="p", files_scanned=2, findings=(), parse_errors=()),
        foundry.summarize_constant_asserts(
            product="p", files_scanned=2,
            findings=(("a.py", "test_x"),), parse_errors=(("b.py", "SyntaxError: e"),),
        ),
    ):
        d = s.to_dict()
        assert json.loads(json.dumps(d)) == d, f"to_dict must round-trip via json: {d}"


def test_b04_to_dict_reuses_frozen_properties():
    # the derived values reuse the properties, so they can never disagree.
    s = foundry.summarize_constant_asserts(
        product="p", files_scanned=2, findings=(("a.py", "test_x"),), parse_errors=()
    )
    d = s.to_dict()
    assert d["total_findings"] == s.total_findings
    assert d["clean"] == s.clean
    assert d["exit_code"] == s.exit_code
    assert d["verdict"] == s.verdict


# ==========================================================================
# Behavior 5 -- gather_constant_asserts(cfg, files=[...]) scans EXACTLY those
# ==========================================================================
def test_b05_gather_files_scans_exactly_given(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={
        "test_target.py": "def test_c():\n    assert True\n",
        "test_other.py": "def test_should_not_appear():\n    assert 1\n",
    })
    cfg = foundry.load_config(str(cfg_path))
    target = str(pathlib.Path(cfg.repo) / "test_target.py")
    before = _snapshot_tree(tmp_path)
    s = foundry.gather_constant_asserts(cfg, files=[target])
    assert s.files_scanned == 1, f"exactly the given path count, got {s.files_scanned}"
    assert s.findings == ((target, "test_c"),), s.findings
    # the repo's OTHER matched test file must NOT be walked
    assert all("test_other" not in f and "test_should_not_appear" not in name for f, name in s.findings)
    assert _snapshot_tree(tmp_path) == before, "gather wrote to disk (must be read-only)"


def test_b05_gather_files_order_is_given_then_source_order(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={
        "test_zzz.py": "def test_z1():\n    assert True\n\ndef test_z2():\n    assert 1\n",
        "test_aaa.py": "def test_a1():\n    assert 0\n",
    })
    cfg = foundry.load_config(str(cfg_path))
    zzz = str(pathlib.Path(cfg.repo) / "test_zzz.py")
    aaa = str(pathlib.Path(cfg.repo) / "test_aaa.py")
    # findings follow the GIVEN files order, then source order within a file --
    # NOT sorted alphabetically by path.
    s1 = foundry.gather_constant_asserts(cfg, files=[zzz, aaa])
    assert [n for _, n in s1.findings] == ["test_z1", "test_z2", "test_a1"], s1.findings
    s2 = foundry.gather_constant_asserts(cfg, files=[aaa, zzz])
    assert [n for _, n in s2.findings] == ["test_a1", "test_z1", "test_z2"], s2.findings


def test_b05_gather_parse_error_continues_never_raises(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={
        "test_bad.py": "def (:\n",
        "test_ok.py": "def test_c():\n    assert True\n",
    })
    cfg = foundry.load_config(str(cfg_path))
    bad = str(pathlib.Path(cfg.repo) / "test_bad.py")
    ok = str(pathlib.Path(cfg.repo) / "test_ok.py")
    before = _snapshot_tree(tmp_path)
    s = foundry.gather_constant_asserts(cfg, files=[bad, ok])  # must not raise
    assert s.files_scanned == 2, s.files_scanned
    assert s.findings == ((ok, "test_c"),), s.findings
    assert len(s.parse_errors) == 1, s.parse_errors
    pe_file, pe_msg = s.parse_errors[0]
    assert pe_file == bad, pe_file
    assert pe_msg.startswith("SyntaxError:"), f"parse-error message must be `Type: msg`, got {pe_msg!r}"
    assert _snapshot_tree(tmp_path) == before, "gather wrote to disk (must be read-only)"


# ==========================================================================
# Behavior 6 -- gather(cfg, files=None) walks cfg.repo via WEAK_TEST_GLOBS
# ==========================================================================
def test_b06_gather_walk_finds_constant_assert(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"test_dirty.py": "def test_c():\n    assert True\n"})
    cfg = foundry.load_config(str(cfg_path))
    s = foundry.gather_constant_asserts(cfg, files=None)
    assert s.files_scanned == 1, s.files_scanned
    assert [n for _, n in s.findings] == ["test_c"], s.findings
    assert s.exit_code == 1


def test_b06_gather_walk_nothing_to_scan(tmp_path):
    # a file present but NOT matching WEAK_TEST_GLOBS -> nothing to scan.
    cfg_path = _write_cfg(tmp_path, files={"notatest.py": "def test_c():\n    assert True\n"})
    cfg = foundry.load_config(str(cfg_path))
    s = foundry.gather_constant_asserts(cfg, files=None)
    assert s.files_scanned == 0, s.files_scanned
    assert s.exit_code == 2


# ==========================================================================
# Behavior 7 -- constant_asserts_cli(cfg, files, as_json): print + return code
# ==========================================================================
def test_b07_cli_text_prints_render(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"test_dirty.py": "def test_c():\n    assert True\n"})
    cfg = foundry.load_config(str(cfg_path))
    before = _snapshot_tree(tmp_path)
    rc, out, err = _capture(lambda: foundry.constant_asserts_cli(cfg, files=None, as_json=False))
    assert rc == 1, f"a constant-assert test must exit 1, got {rc}\n{out}{err}"
    assert "foundry constant-asserts -- demoprod" in out, out
    assert "test_c" in out and "test_dirty.py" in out, out
    assert out.rstrip().endswith("verdict: CONSTANT ASSERTS FOUND"), out
    assert _snapshot_tree(tmp_path) == before, "cli wrote to disk (must be read-only)"


def test_b07_cli_json_prints_to_dict(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"test_dirty.py": "def test_c():\n    assert True\n"})
    cfg = foundry.load_config(str(cfg_path))
    before = _snapshot_tree(tmp_path)
    rc, out, err = _capture(lambda: foundry.constant_asserts_cli(cfg, files=None, as_json=True))
    assert rc == 1, f"exit code identical in json mode, got {rc}"
    doc = json.loads(out)  # the ENTIRE stdout must be the JSON document
    assert list(doc.keys()) == [
        "product", "files_scanned", "total_findings", "clean",
        "exit_code", "verdict", "findings", "parse_errors",
    ], doc
    assert doc["exit_code"] == 1 and doc["verdict"] == "CONSTANT ASSERTS FOUND"
    assert doc["findings"][0]["test"] == "test_c", doc["findings"]
    assert _snapshot_tree(tmp_path) == before, "cli wrote to disk (must be read-only)"


def test_b07_cli_return_and_selection_identical_both_modes(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={
        "test_dirty.py": "def test_c():\n    assert True\n",
        "test_clean.py": "def test_real():\n    assert x == 1\n",
    })
    cfg = foundry.load_config(str(cfg_path))
    target = str(pathlib.Path(cfg.repo) / "test_dirty.py")
    rc_text, _, _ = _capture(lambda: foundry.constant_asserts_cli(cfg, files=[target], as_json=False))
    rc_json, out_json, _ = _capture(lambda: foundry.constant_asserts_cli(cfg, files=[target], as_json=True))
    assert rc_text == rc_json == 1, (rc_text, rc_json)
    # --files selection is identical in both modes: only the one target file scanned
    doc = json.loads(out_json)
    assert doc["files_scanned"] == 1, doc
    assert [f["test"] for f in doc["findings"]] == ["test_c"], doc


# ==========================================================================
# Behavior 8 -- disjointness across the two CLIs + weak-tests non-regression
# ==========================================================================
def test_b08_disjointness_across_the_two_clis(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"test_mix.py": MIX_SRC})
    cfg = foundry.load_config(str(cfg_path))
    mix = str(pathlib.Path(cfg.repo) / "test_mix.py")
    rc_w, out_w, _ = _capture(lambda: foundry.main(["weak-tests", "--config", str(cfg_path), "--files", mix]))
    rc_c, out_c, _ = _capture(lambda: foundry.main(["constant-asserts", "--config", str(cfg_path), "--files", mix]))
    # no-assert test appears ONLY under weak-tests
    assert "test_free" in out_w and "test_free" not in out_c, (out_w, out_c)
    # constant-only test appears ONLY under constant-asserts
    assert "test_const" in out_c and "test_const" not in out_w, (out_w, out_c)
    # a real (Compare) assert appears under NEITHER
    assert "test_real" not in out_w and "test_real" not in out_c, (out_w, out_c)
    assert rc_w == 1 and rc_c == 1, (rc_w, rc_c)


def test_b08_weak_tests_output_unchanged_nonregression(tmp_path):
    # BLACK-BOX non-regression: the shipped `weak-tests` observable behaviour
    # (which flags assertion-FREE tests and treats a constant assert as "a
    # signal") must be byte-stable per its iter-22/23 spec -- this additive bite
    # adds a SIBLING command and must not perturb it.
    cfg_path = _write_cfg(tmp_path, files={
        "test_free.py": "def test_free():\n    x = compute()\n",
        "test_const.py": "def test_const():\n    assert True\n",
        "test_real.py": "def test_real():\n    assert y == 2\n",
    })
    cfg = foundry.load_config(str(cfg_path))
    repo = pathlib.Path(cfg.repo)
    free = str(repo / "test_free.py")
    const = str(repo / "test_const.py")
    real = str(repo / "test_real.py")
    # assertion-free -> flagged (exit 1, names it)
    rc, out, _ = _capture(lambda: foundry.main(["weak-tests", "--config", str(cfg_path), "--files", free]))
    assert rc == 1 and "test_free" in out, (rc, out)
    # constant-only -> weak-tests treats the constant assert as a signal -> clean (exit 0), no name
    rc, out, _ = _capture(lambda: foundry.main(["weak-tests", "--config", str(cfg_path), "--files", const]))
    assert rc == 0 and "test_const" not in out, (rc, out)
    # real assert -> clean (exit 0)
    rc, out, _ = _capture(lambda: foundry.main(["weak-tests", "--config", str(cfg_path), "--files", real]))
    assert rc == 0 and "test_real" not in out, (rc, out)
    # weak-tests JSON shape unchanged (same 8-key document)
    rc, out, _ = _capture(lambda: foundry.main(["weak-tests", "--config", str(cfg_path), "--files", free, "--json"]))
    doc = json.loads(out)
    assert list(doc.keys()) == [
        "product", "files_scanned", "total_findings", "clean",
        "exit_code", "verdict", "findings", "parse_errors",
    ], doc
    assert doc["findings"][0]["test"] == "test_free", doc


# ==========================================================================
# Behavior 9 -- DORMANT / off-control-path; both modules import
# ==========================================================================
def test_b09_new_surface_present_and_callable():
    assert isinstance(foundry.ConstantAssertSummary, type)
    assert callable(foundry.summarize_constant_asserts)
    assert callable(foundry.gather_constant_asserts)
    assert callable(foundry.constant_asserts_cli)
    # pre-existing control-flow entry points remain present + callable (regression)
    for fn in CONTROL_FLOW_FNS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"


def test_b09_control_flow_fns_do_not_reference_new_symbols():
    for fn_name in CONTROL_FLOW_FNS:
        names = _fn_names(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, (
                f"{fn_name} references new symbol {sym!r} (must stay off the control path)"
            )


def test_b09_dispatcher_does_not_reference_new_symbols():
    # honors isolation: compiled-name introspection of the dispatcher module,
    # NOT a read of dispatcher.py source text.
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names = _module_names(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in names, f"dispatcher references new symbol {sym!r}"


def test_b09_both_modules_import():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


# ==========================================================================
# Behavior 10 -- main(["constant-asserts", ...]) dispatch + exit codes + --json
# ==========================================================================
def test_b10_main_text_dispatch_returns_exit_code(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"test_dirty.py": "def test_c():\n    assert True\n"})
    rc, out, _ = _capture(lambda: foundry.main(["constant-asserts", "--config", str(cfg_path)]))
    assert rc == 1, (rc, out)
    assert "foundry constant-asserts -- demoprod" in out and "test_c" in out, out


def test_b10_main_json_routes_as_json(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"test_dirty.py": "def test_c():\n    assert True\n"})
    rc, out, _ = _capture(lambda: foundry.main(["constant-asserts", "--config", str(cfg_path), "--json"]))
    assert rc == 1, (rc, out)
    doc = json.loads(out)  # the ENTIRE stdout is a JSON document
    assert doc["exit_code"] == 1 and doc["findings"][0]["test"] == "test_c", doc


def test_b10_main_exit_codes_0_1_2(tmp_path):
    # clean -> 0
    p0 = _write_cfg(tmp_path / "clean", files={"test_ok.py": "def test_real():\n    assert x == 1\n"})
    rc0, _, _ = _capture(lambda: foundry.main(["constant-asserts", "--config", str(p0)]))
    assert rc0 == 0, rc0
    # findings -> 1
    p1 = _write_cfg(tmp_path / "dirty", files={"test_bad.py": "def test_c():\n    assert True\n"})
    rc1, _, _ = _capture(lambda: foundry.main(["constant-asserts", "--config", str(p1)]))
    assert rc1 == 1, rc1
    # nothing to scan -> 2
    p2 = _write_cfg(tmp_path / "empty", files={"notatest.py": "def test_c():\n    assert True\n"})
    rc2, _, _ = _capture(lambda: foundry.main(["constant-asserts", "--config", str(p2)]))
    assert rc2 == 2, rc2


def test_b10_missing_config_is_usage_error():
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["constant-asserts"])
    assert ei.value.code != 0, "constant-asserts without --config must be a usage error"


def test_b10_help_lists_constant_asserts():
    buf = io.StringIO()
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stdout(buf):
            foundry.main(["--help"])
    assert ei.value.code == 0
    out = buf.getvalue()
    assert "constant-asserts" in out, f"--help must list the new subcommand:\n{out}"
    assert "weak-tests" in out, f"--help must still list weak-tests (regression):\n{out}"
