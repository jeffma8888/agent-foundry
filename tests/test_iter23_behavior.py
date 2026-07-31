"""Black-box behaviour tests for iter 23 -- a machine-readable `--json` output
mode over the read-only `foundry weak-tests` assertion-free-test scan (iter 22).
ALL additive in foundry.py:

  * a PURE `WeakTestSummary.to_dict() -> dict` (8 fixed-order keys: the 2 stored
    fields `product`/`files_scanned`, the 4 derived props `total_findings`/
    `clean`/`exit_code`/`verdict` REUSED verbatim, and `findings`/`parse_errors`
    serialized as ordered lists of `{"file","test"}` / `{"file","message"}`),
  * `weak_tests_cli(cfg, files=None, as_json: bool = False) -> int` -- on True it
    prints ONE JSON document (the whole stdout) == the summary's `to_dict()` and
    returns the SAME exit code as the human path; on False/default it is
    byte-identical to iter 22,
  * a `weak-tests --json` argparse flag (`store_true`, default off, coexisting
    with `--files`) routed by `main`.

ISOLATION CONTRACT (honored): this file was written from the iter-23 PM spec's
Expected Behaviors (1-9) and the product's own OBSERVABLE behaviour ONLY. The
implementation source (foundry.py / dispatcher.py internals), the engineer's and
reviewer's notes, and `git diff` were NOT read. Every check drives the PUBLIC
interface: the pure `WeakTestSummary(...).to_dict()` via the public builder
`foundry.summarize_weak_tests(...)`, and the CLI via `foundry.weak_tests_cli(cfg,
files=..., as_json=...)` / `foundry.main(["weak-tests", ...])` against a
TMP-`repo` config with real temp test files (the real foundry repo is NEVER
touched). Derived-key correctness is proven by SELF-CONSISTENT reconstruction
(rebuild a summary from the JSON's stored+list fields and compare its to_dict()),
never by re-reading the implementation. The off-control-path checks (Behavior 9)
use only public RUNTIME introspection -- compiled function name/const tables
(`__code__.co_names`/`co_consts`) and `dispatcher` module attributes -- NOT the
source text. Fully offline & deterministic: no network, no git, no agent-run
(only the documented `import foundry, dispatcher` regression probe as a
subprocess); real temp files only; every CLI test snapshots the tmp tree to prove
the read-only / writes-nothing contract.
"""
import inspect
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
# helpers  (mirror tests/test_iter19_behavior.py + test_iter22_behavior.py)
# --------------------------------------------------------------------------
# Behavior 1: to_dict() must have EXACTLY these 8 keys in THIS order.
EXPECTED_KEYS = [
    "product", "files_scanned", "total_findings", "clean",
    "exit_code", "verdict", "findings", "parse_errors",
]
NEW_SYMBOLS = ("summarize_weak_tests", "weak_tests_cli", "WeakTestSummary")
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")


def _write_cfg(tmp_path, files=None, **over):
    """A minimal product config in a tmp dir (mirrors the suite's convention).
    `repo` is a TMP dir so the real foundry repo is NEVER touched. `files` is a
    {relative-path: source-text} mapping seeded under the repo."""
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
    Separate capture matters: Behaviors 3/5 require the JSON to be the ENTIRE
    stdout, so stderr noise must not contaminate the parse."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _reconstruct_to_dict(d):
    """Rebuild a WeakTestSummary from the parsed JSON's stored + list fields via
    the PUBLIC builder and return its to_dict(). If the payload is a faithful,
    self-consistent serialization, this equals `d` -- proving every derived key
    (`total_findings`/`clean`/`exit_code`/`verdict`) was re-derived from the
    stored data, without reading any implementation seam."""
    findings = tuple((f["file"], f["test"]) for f in d["findings"])
    parse_errors = tuple((p["file"], p["message"]) for p in d["parse_errors"])
    s2 = foundry.summarize_weak_tests(
        product=d["product"], files_scanned=d["files_scanned"],
        findings=findings, parse_errors=parse_errors,
    )
    return s2.to_dict()


def _summaries():
    """A spread of public summaries covering every exit-code branch."""
    return [
        foundry.summarize_weak_tests(product="p", files_scanned=2, findings=(), parse_errors=()),                    # clean / 0
        foundry.summarize_weak_tests(product="q", files_scanned=0, findings=(), parse_errors=()),                    # nothing / 2
        foundry.summarize_weak_tests(product="r", files_scanned=3,
                                     findings=(("a_test.py", "test_x"), ("b_test.py", "test_y")),
                                     parse_errors=()),                                                                # findings / 1
        foundry.summarize_weak_tests(product="s", files_scanned=1, findings=(),
                                     parse_errors=(("bad_test.py", "SyntaxError: bad"),)),                            # parse-error / 1
        foundry.summarize_weak_tests(product="t", files_scanned=4,
                                     findings=(("c_test.py", "test_z"),),
                                     parse_errors=(("ugly_test.py", "cannot read"),)),                                # both / 1
    ]


# ==========================================================================
# Behavior 1 -- to_dict() has EXACTLY 8 keys in the mandated order; derived
#               keys REUSE the frozen properties; stored keys are the fields
# ==========================================================================
def test_b1_keys_exact_and_ordered():
    for s in _summaries():
        d = s.to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == EXPECTED_KEYS, (
            f"to_dict keys/order wrong.\n got: {list(d.keys())}\nwant: {EXPECTED_KEYS}")
        assert len(d) == 8


def test_b1_stored_fields_and_derived_reuse_properties():
    for s in _summaries():
        d = s.to_dict()
        # stored fields verbatim
        assert d["product"] == s.product and isinstance(d["product"], str)
        assert d["files_scanned"] == s.files_scanned and isinstance(d["files_scanned"], int)
        # four derived keys mirror the frozen properties EXACTLY (reused, not re-derived)
        assert d["total_findings"] == s.total_findings and isinstance(d["total_findings"], int)
        assert d["total_findings"] == len(s.findings), (
            "total_findings must equal len(findings)")
        assert d["clean"] == s.clean and isinstance(d["clean"], bool)
        assert d["exit_code"] == s.exit_code and isinstance(d["exit_code"], int)
        assert d["verdict"] == s.verdict and isinstance(d["verdict"], str)
        # verdict is the SAME token render() prints
        assert d["verdict"] in s.render(), (
            f"verdict token {d['verdict']!r} not present in render():\n{s.render()}")
        # list-typed payload fields
        assert isinstance(d["findings"], list)
        assert isinstance(d["parse_errors"], list)


# ==========================================================================
# Behavior 2 -- findings/parse_errors serialization + order + round-trip
# ==========================================================================
def test_b2_findings_serialized_ordered_and_exact_keys():
    s = foundry.summarize_weak_tests(
        product="p", files_scanned=3,
        findings=(("z_test.py", "test_zebra"), ("a_test.py", "test_apple")),
        parse_errors=())
    d = s.to_dict()
    assert d["findings"] == [
        {"file": "z_test.py", "test": "test_zebra"},
        {"file": "a_test.py", "test": "test_apple"},
    ], f"findings must preserve source order + shape, got {d['findings']!r}"
    for obj in d["findings"]:
        assert set(obj.keys()) == {"file", "test"}, f"finding obj keys wrong: {obj!r}"


def test_b2_parse_errors_serialized_ordered_and_exact_keys():
    s = foundry.summarize_weak_tests(
        product="p", files_scanned=2, findings=(),
        parse_errors=(("first.py", "msg one"), ("second.py", "msg two")))
    d = s.to_dict()
    assert d["parse_errors"] == [
        {"file": "first.py", "message": "msg one"},
        {"file": "second.py", "message": "msg two"},
    ], f"parse_errors must preserve order + shape, got {d['parse_errors']!r}"
    for obj in d["parse_errors"]:
        assert set(obj.keys()) == {"file", "message"}, f"parse-error obj keys wrong: {obj!r}"


def test_b2_json_native_dumps_and_round_trip_including_empty():
    for s in _summaries():
        d = s.to_dict()
        text = json.dumps(d)                      # must not raise
        assert json.loads(text) == d, "to_dict() must survive a dumps/loads round-trip"
    # explicit empty-lists case round-trips too
    empty = foundry.summarize_weak_tests(product="e", files_scanned=1, findings=(), parse_errors=()).to_dict()
    assert empty["findings"] == [] and empty["parse_errors"] == []
    assert json.loads(json.dumps(empty)) == empty


def test_b2_reconstruction_is_self_consistent():
    # rebuilding a summary from the serialized dict reproduces the SAME dict
    for s in _summaries():
        d = s.to_dict()
        assert _reconstruct_to_dict(d) == d, "to_dict() is not a self-consistent serialization"


# ==========================================================================
# Behavior 3 -- weak_tests_cli(cfg, as_json=True): one JSON doc == to_dict(),
#               returns summary.exit_code, parsed exit_code == returned int
# ==========================================================================
def test_b3_json_path_findings(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"test_dirty.py": "def test_a():\n    pass\n"})
    cfg = foundry.load_config(str(cfg_path))
    before = _snapshot_tree(tmp_path)
    rc_json, out_json, _ = _capture(lambda: foundry.weak_tests_cli(cfg, as_json=True))
    # the WHOLE stdout parses as ONE JSON document into a dict
    d = json.loads(out_json)
    assert isinstance(d, dict)
    assert list(d.keys()) == EXPECTED_KEYS
    # same integer as the human path for the SAME state; parsed exit_code == returned int
    rc_human, _, _ = _capture(lambda: foundry.weak_tests_cli(cfg))
    assert rc_json == rc_human == d["exit_code"] == 1
    assert d["product"] == cfg.name
    # payload is a faithful, self-consistent serialization
    assert _reconstruct_to_dict(d) == d
    # read-only
    assert _snapshot_tree(tmp_path) == before, "weak-tests --json wrote to disk (must be read-only)"


def test_b3_json_path_clean(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"test_clean.py": "def test_ok():\n    assert 1\n"})
    cfg = foundry.load_config(str(cfg_path))
    rc_json, out_json, _ = _capture(lambda: foundry.weak_tests_cli(cfg, as_json=True))
    d = json.loads(out_json)
    rc_human, _, _ = _capture(lambda: foundry.weak_tests_cli(cfg))
    assert rc_json == rc_human == d["exit_code"] == 0
    assert _reconstruct_to_dict(d) == d


# ==========================================================================
# Behavior 4 -- default / as_json=False byte-identical to iter 22 human render
# ==========================================================================
def test_b4_default_param_is_false():
    sig = inspect.signature(foundry.weak_tests_cli)
    assert sig.parameters["as_json"].default is False, (
        f"as_json default must be False, got {sig.parameters['as_json'].default!r}")


def test_b4_default_equals_false_and_is_human_not_json(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"test_dirty.py": "def test_a():\n    pass\n"})
    cfg = foundry.load_config(str(cfg_path))
    before = _snapshot_tree(tmp_path)
    rc_default, out_default, _ = _capture(lambda: foundry.weak_tests_cli(cfg))
    rc_false, out_false, _ = _capture(lambda: foundry.weak_tests_cli(cfg, as_json=False))
    # default == explicit as_json=False, byte-for-byte
    assert out_default == out_false, "default must equal as_json=False output byte-for-byte"
    assert rc_default == rc_false == 1
    # the human output for a file+finding is NOT a single JSON document
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_default)
    # it names the finding (iter-22 human surface regression guard)
    assert "test_dirty.py" in out_default and "test_a" in out_default
    assert _snapshot_tree(tmp_path) == before, "human weak-tests wrote to disk (must be read-only)"


def test_b4_files_mode_behaves_same_in_both_modes(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={
        "test_target.py": "def test_a():\n    pass\n",
        "test_other.py": "def test_b():\n    pass\n",
    })
    cfg = foundry.load_config(str(cfg_path))
    target = str(pathlib.Path(cfg.repo) / "test_target.py")
    # human --files mode: only the target file/test surfaces
    rc_h, out_h, _ = _capture(lambda: foundry.weak_tests_cli(cfg, files=[target]))
    assert rc_h == 1 and "test_target.py" in out_h and "test_other.py" not in out_h
    # json --files mode: files_scanned == 1, only the target in findings
    rc_j, out_j, _ = _capture(lambda: foundry.weak_tests_cli(cfg, files=[target], as_json=True))
    dj = json.loads(out_j)
    assert rc_j == rc_h == dj["exit_code"] == 1
    assert dj["files_scanned"] == 1
    assert [f["file"] for f in dj["findings"]] == [target] or all(
        "test_other.py" not in f["file"] for f in dj["findings"])
    assert all("test_other.py" not in f["file"] for f in dj["findings"]), (
        f"--json must not walk the repo when --files is given:\n{dj['findings']}")


# ==========================================================================
# Behavior 5 -- main(["weak-tests", ..., "--json"]) end-to-end
# ==========================================================================
def test_b5_main_json_flag_routes_json(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"test_dirty.py": "def test_a():\n    pass\n"})
    rc_json, out_json, _ = _capture(
        lambda: foundry.main(["weak-tests", "--config", str(cfg_path), "--json"]))
    d = json.loads(out_json)                       # whole stdout is JSON
    assert list(d.keys()) == EXPECTED_KEYS
    assert d["exit_code"] == rc_json == 1
    assert _reconstruct_to_dict(d) == d
    # non-json path: human report, SAME exit code
    rc_human, out_human, _ = _capture(
        lambda: foundry.main(["weak-tests", "--config", str(cfg_path)]))
    assert rc_human == rc_json == 1
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_human)
    assert "test_a" in out_human


def test_b5_json_flag_is_store_true_default_off(tmp_path):
    # no --json -> the parsed exit code + human (non-json) output; --json store_true
    cfg_path = _write_cfg(tmp_path, files={"test_clean.py": "def test_a():\n    assert 1\n"})
    rc, out, _ = _capture(lambda: foundry.main(["weak-tests", "--config", str(cfg_path)]))
    assert rc == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


def test_b5_json_and_files_coexist(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={
        "test_target.py": "def test_a():\n    pass\n",
        "test_other.py": "def test_b():\n    pass\n",
    })
    cfg = foundry.load_config(str(cfg_path))
    target = str(pathlib.Path(cfg.repo) / "test_target.py")
    rc, out, _ = _capture(
        lambda: foundry.main(["weak-tests", "--config", str(cfg_path), "--json", "--files", target]))
    d = json.loads(out)
    assert rc == d["exit_code"] == 1
    assert d["files_scanned"] == 1


# ==========================================================================
# Behavior 6 -- --json honours --files (re-serializes the SAME snapshot)
# ==========================================================================
def test_b6_json_files_matches_human_files_snapshot(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={
        "test_target.py": "def test_a():\n    pass\n",
        "test_extra_dirty.py": "def test_should_not_appear():\n    pass\n",
        "test_clean.py": "def test_c():\n    assert 1\n",
    })
    cfg = foundry.load_config(str(cfg_path))
    target = str(pathlib.Path(cfg.repo) / "test_target.py")
    before = _snapshot_tree(tmp_path)
    rc, out, _ = _capture(lambda: foundry.weak_tests_cli(cfg, files=[target], as_json=True))
    d = json.loads(out)
    assert rc == d["exit_code"] == 1
    assert d["files_scanned"] == 1, f"exactly one --files path must be scanned: {d}"
    # only the target file surfaces; the repo's other matched files are NOT walked
    assert all("test_extra_dirty.py" not in f["file"] for f in d["findings"])
    assert all("test_should_not_appear" != f["test"] for f in d["findings"])
    assert d["total_findings"] == 1 and d["clean"] is False
    # the JSON re-serializes the SAME snapshot the human --files path produces
    assert _reconstruct_to_dict(d) == d
    assert _snapshot_tree(tmp_path) == before, "weak-tests --json --files wrote to disk"


# ==========================================================================
# Behavior 7 -- clean / findings / parse-error JSON payloads
# ==========================================================================
def test_b7a_clean_payload(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"test_ok.py": "def test_a():\n    assert True\n"})
    cfg = foundry.load_config(str(cfg_path))
    rc, out, _ = _capture(lambda: foundry.weak_tests_cli(cfg, as_json=True))
    d = json.loads(out)
    assert d["total_findings"] == 0
    assert d["clean"] is True
    assert d["findings"] == []
    assert d["parse_errors"] == []
    assert d["exit_code"] == 0 and rc == 0


def test_b7b_findings_payload(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"test_weak.py": "def test_a():\n    pass\n"})
    cfg = foundry.load_config(str(cfg_path))
    rc, out, _ = _capture(lambda: foundry.weak_tests_cli(cfg, as_json=True))
    d = json.loads(out)
    assert d["total_findings"] >= 1
    assert d["clean"] is False
    assert any("test_weak.py" in f["file"] and f["test"] == "test_a" for f in d["findings"]), (
        f"findings must name the offending file+test: {d['findings']}")
    assert d["exit_code"] == 1 and rc == 1


def test_b7c_parse_error_payload(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"test_bad.py": "def (:\n"})
    cfg = foundry.load_config(str(cfg_path))
    rc, out, _ = _capture(lambda: foundry.weak_tests_cli(cfg, as_json=True))
    d = json.loads(out)
    assert d["clean"] is False
    assert any("test_bad.py" in p["file"] and isinstance(p["message"], str) and p["message"].strip()
               for p in d["parse_errors"]), (
        f"parse_errors must name the unparseable file + a non-empty message: {d['parse_errors']}")
    assert d["exit_code"] == 1 and rc == 1


# ==========================================================================
# Behavior 8 -- nothing-to-scan JSON is valid (files_scanned==0, exit 2)
# ==========================================================================
def test_b8_nothing_to_scan_via_empty_files(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"test_x.py": "def test_a():\n    pass\n"})
    cfg = foundry.load_config(str(cfg_path))
    rc, out, _ = _capture(lambda: foundry.weak_tests_cli(cfg, files=[], as_json=True))
    d = json.loads(out)                            # still ONE valid JSON document
    assert d["files_scanned"] == 0
    assert d["total_findings"] == 0
    assert d["clean"] is False
    assert d["findings"] == [] and d["parse_errors"] == []
    assert d["exit_code"] == 2 and rc == 2


def test_b8_nothing_to_scan_via_empty_repo(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={"notatest.py": "def test_a():\n    pass\n"})
    cfg = foundry.load_config(str(cfg_path))
    rc, out, _ = _capture(lambda: foundry.weak_tests_cli(cfg, as_json=True))
    d = json.loads(out)
    assert d["files_scanned"] == 0 and d["exit_code"] == 2 and rc == 2
    # the non-json nothing-to-scan human output is unchanged from iter 22 (exit 2, not JSON)
    rc_h, out_h, _ = _capture(lambda: foundry.weak_tests_cli(cfg))
    assert rc_h == 2
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_h)


# ==========================================================================
# Behavior 9 -- purely additive / invariants preserved
# ==========================================================================
def _fn_names_consts(fn):
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


def test_b9_both_modules_import():
    import subprocess
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b9_control_flow_fns_present_and_do_not_reference_new_surface():
    for fn in CONTROL_FLOW_FNS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"
        names, consts = _fn_names_consts(getattr(foundry, fn))
        for sym in NEW_SYMBOLS + ("to_dict",):
            assert sym not in names, (
                f"{fn} references {sym!r} -- the JSON surface must stay off the control path")
        assert "weak-tests" not in consts, f"{fn} embeds the 'weak-tests' subcommand string"


def test_b9_dispatcher_untouched_by_new_surface():
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, consts = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in names, f"dispatcher references new symbol {sym!r}"
    assert "weak-tests" not in consts, "dispatcher embeds the 'weak-tests' subcommand string"


def test_b9_json_path_writes_nothing(tmp_path):
    cfg_path = _write_cfg(tmp_path, files={
        "test_dirty.py": "def test_a():\n    pass\n",
        "test_clean.py": "def test_b():\n    assert 1\n",
    })
    cfg = foundry.load_config(str(cfg_path))
    before = _snapshot_tree(tmp_path)
    rc, _, _ = _capture(lambda: foundry.weak_tests_cli(cfg, as_json=True))
    assert rc in (0, 1, 2)
    assert _snapshot_tree(tmp_path) == before, "weak-tests --json created/modified files (read-only violation)"


def test_b9_sentinels_and_status_vocab_unchanged():
    _, consts = _module_names_consts(foundry)
    for sentinel in ("VERDICT:", "RESULT:", "ACTION:", "POSTRELEASE:"):
        assert any(sentinel in c for c in consts), f"sentinel prefix {sentinel!r} vanished from foundry"
    for status in ("shipped", "no-ship", "infra-fail"):
        assert status in consts, f"res['status'] value {status!r} vanished from foundry"


def test_b9_help_lists_weak_tests_and_json_flag(capsys):
    # top-level help still lists the subcommand
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    top = capsys.readouterr().out
    assert "weak-tests" in top, f"weak-tests missing from top-level --help:\n{top}"
    # the subcommand help advertises the new --json flag (coexisting with --files)
    with pytest.raises(SystemExit) as ei2:
        foundry.main(["weak-tests", "--help"])
    assert ei2.value.code == 0
    sub = capsys.readouterr().out
    assert "--json" in sub and "--files" in sub, f"weak-tests help missing --json/--files:\n{sub}"
