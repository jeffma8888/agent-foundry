"""Black-box behaviour tests for iter 323 -- the read-only
`foundry unfailable-asserts --config <cfg> [--files ...] [--json]` CLI that
finally surfaces the already-shipped (iter-186) `find_unfailable_assert_tests`
detector, in the exact shape its three siblings (`weak-tests` #12,
`constant-asserts` #21, `skipped-tests` #23) ship with.

WHY THE FOURTH LENS IS NOT REDUNDANT (spec's "Why", re-asserted as Behavior 8):
an `assert <real check> or True` carries a REAL signal, so the three shipped
detectors all return nothing for it -- it does not merely escape them, it
VOUCHES for the function holding it.

Public surface exercised here (a STRUCTURAL MIRROR of the iter-56
`skipped-tests` machinery): frozen `UnfailableAssertSummary`, the pure
keyword-only `summarize_unfailable_asserts(...)`, the `gather_unfailable_asserts`
seam, and the `unfailable_asserts_cli` / `main(["unfailable-asserts", ...])`
entry.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-323 PM
spec's Expected Behaviors (1-11), the product README/roadmap, the `tests/`
conventions (esp. tests/test_iter56_behavior.py -- the skipped-tests CLI mirror
-- tests/test_iter186_behavior.py -- the detector -- and
tests/test_iter229_behavior.py -- the "hand the source text to the PUBLIC
oracle, never read it yourself" README-index convention), and the product's OWN
OBSERVABLE behaviour, obtained by RUNNING it and by PUBLIC RUNTIME
introspection (module attributes, `dataclasses.fields`, `__code__.co_names`,
`__doc__`). foundry.py's and dispatcher.py's SOURCE TEXT were NOT read by this
author: where a behaviour is ABOUT the source (Behavior 10), the text is handed
UNREAD to the product's own shipped auditors (`foundry_cli_verbs`,
`readme_verb_index_gaps`), which is the established convention. The engineer's
notes, the reviewer's notes, and `git diff` were NOT consulted.

Fully offline and deterministic: every scan runs against a TMP-`repo` config
holding real temp files, so the real foundry repo is NEVER scanned or written;
zero git, network, clock or agent-run (except the documented
`import foundry, dispatcher` regression probe). Every fixture source below is
SYNTHETIC -- no real internal tool/service name and no absolute home path -- so
the in-loop leak guard passes on the ship commit.
"""
from __future__ import annotations

import dataclasses
import dis
import io
import json
import pathlib
import types

import pytest

import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402

VERB = "unfailable-asserts"
SOURCE = _ROOT / "foundry.py"
README = _ROOT / "README.md"

# the four NEW public symbols this iteration adds
NEW_SYMBOLS = (
    "UnfailableAssertSummary",
    "summarize_unfailable_asserts",
    "gather_unfailable_asserts",
    "unfailable_asserts_cli",
)

# --- synthetic fixture sources -------------------------------------------
CLEAN = "def test_ok():\n    assert 1 + 1 == 2\n"
DIRTY = "def test_x():\n    assert True\n"
# the three unfailable KINDS, one per function, alphabetically shuffled
KIND_LITERAL = "def test_kind_literal():\n    assert True\n"
KIND_TUPLE = 'def test_kind_tuple():\n    assert (1 == 2, "boom")\n'
KIND_OR = "def test_kind_or():\n    assert 1 == 2 or True\n"
# ONE function holding all THREE kinds -- must appear EXACTLY once
THREE_IN_ONE = (
    "def test_zzz_three_kinds():\n"
    "    assert True\n"
    '    assert (1 == 2, "boom")\n'
    "    assert 1 == 2 or True\n"
)
FIRST_ALPHA = "def test_aaa_first():\n    assert True\n"
# a string literal merely SPELLING an unfailable shape is DATA
DATA_ONLY = (
    "def test_data_not_code():\n"
    '    a = "assert True"\n'
    '    b = "assert cond or True"\n'
    '    c = "assert (cond, \'msg\')"\n'
    "    assert a != b != c\n"
)
UNPARSEABLE = "def test_broken(:\n    assert 1 == 1\n"


# --------------------------------------------------------------------------
# helpers  (mirror tests/test_iter56_behavior.py)
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, files=None, **over):
    """A minimal product config in a tmp dir. `repo` is a TMP dir so the real
    foundry repo is NEVER scanned. `files` is a {relative-path: source-text}
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
    return p, repo


def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY; return (rc, out, err).
    Separate capture matters: Behavior 7 requires the JSON to be the ENTIRE
    stdout, so stderr noise must not contaminate the parse."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _run(cfg_path, *extra):
    return _capture(lambda: foundry.main([VERB, "--config", str(cfg_path), *extra]))


def _snapshot(root):
    """{relative-path: bytes} for every file under root (no-write proof)."""
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def _paths(root):
    root = pathlib.Path(root)
    return {str(p.relative_to(root)) for p in root.rglob("*")}


def _last_nonempty(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines, f"report was empty:\n{text!r}"
    return lines[-1]


def _deep_names(fn):
    """Every global/attr name reachable from fn's compiled code object
    (recursing into nested code objects) -- PUBLIC RUNTIME introspection, NOT
    source text, so the dormancy check honors the isolation contract."""
    stack, seen, names = [fn.__code__], set(), set()
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names |= set(code.co_names)
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                stack.append(const)
    return names


def _module_functions(mod):
    return {n: v for n, v in vars(mod).items()
            if isinstance(v, types.FunctionType)
            and getattr(v, "__module__", None) == mod.__name__}


def _thin_wrapper_count():
    """DERIVED (Behavior 11): the module-level functions whose body is a single
    `return _gather_test_scan(...)`. Measured at RUNTIME from the compiled
    bytecode, never from source text: such a wrapper (a) names
    `_gather_test_scan`, (b) performs EXACTLY ONE call, and (c) carries EXACTLY
    ONE return -- so a caller that merely mentions the helper inside a larger
    body is excluded."""
    out = []
    for name, fn in _module_functions(foundry).items():
        code = fn.__code__
        if "_gather_test_scan" not in code.co_names:
            continue
        ops = [i.opname for i in dis.get_instructions(code)]
        calls = sum(1 for o in ops if o.startswith("CALL"))
        returns = sum(1 for o in ops if o.startswith("RETURN_"))
        if calls == 1 and returns == 1:
            out.append(name)
    return sorted(out)


# ==========================================================================
# Behavior 1 -- clean scan of the repo exits 0
# ==========================================================================
def test_b1_clean_repo_scan_exits_zero(tmp_path):
    cfg, _repo = _write_cfg(tmp_path, {"tests/test_ok.py": CLEAN,
                                       "tests/test_more.py": CLEAN})
    rc, out, err = _run(cfg)
    assert rc == 0, f"clean repo must exit 0, got {rc}\nSTDOUT:\n{out}\nSTDERR:\n{err}"
    assert "files scanned: 2" in out, f"both files must be scanned:\n{out}"
    assert "parse errors: 0" in out, f"no parse errors expected:\n{out}"


def test_b1_scan_walks_cfg_repo_not_the_process_cwd(tmp_path):
    """The verb resolves `cfg.repo`, not the process cwd -- which is the REAL
    foundry repo (200+ test files) while pytest runs, so a cwd walk would
    report a far larger count and a path outside tmp_path."""
    cfg, repo = _write_cfg(tmp_path, {"tests/test_ok.py": CLEAN,
                                      "tests/test_bad.py": DIRTY})
    rc, out, _ = _run(cfg)
    assert rc == 1, out
    assert "files scanned: 2" in out, \
        f"exactly the 2 files under cfg.repo must be scanned:\n{out}"
    _rc, out_j, _ = _run(cfg, "--json")
    paths = [f["file"] for f in json.loads(out_j)["findings"]]
    assert paths == [str(repo / "tests" / "test_bad.py")], \
        f"the scanned path must live under cfg.repo ({repo}), got {paths}"


# ==========================================================================
# Behavior 2 -- a dirty repo exits 1 and names BOTH path and function
# ==========================================================================
def test_b2_dirty_repo_exits_1_and_names_file_and_function(tmp_path):
    cfg, repo = _write_cfg(tmp_path, {"tests/test_bad.py": DIRTY})
    rc, out, err = _run(cfg)
    assert rc == 1, f"a dirty repo must exit 1, got {rc}\n{out}\n{err}"
    assert str(repo / "tests" / "test_bad.py") in out, \
        f"report must name the FILE PATH:\n{out}"
    assert "test_x" in out, f"report must name the TEST FUNCTION:\n{out}"
    assert "unfailable-assert tests: 1" in out, f"count must be 1:\n{out}"


# ==========================================================================
# Behavior 3 -- `--files` scans EXACTLY those paths and never walks the repo
# ==========================================================================
def test_b3_files_scans_exactly_the_given_paths(tmp_path):
    cfg, repo = _write_cfg(tmp_path, {
        "tests/test_ok.py": CLEAN,
        "tests/test_bad.py": DIRTY,
        "tests/test_elsewhere.py": DIRTY,
    })
    clean, dirty = repo / "tests/test_ok.py", repo / "tests/test_bad.py"

    rc, out, _ = _run(cfg, "--files", str(clean), str(dirty))
    assert "files scanned: 2" in out, f"exactly the 2 given paths:\n{out}"
    assert rc == 1, f"one of the two is dirty -> exit 1, got {rc}\n{out}"
    assert "test_elsewhere.py" not in out, \
        f"--files must NOT walk the repo:\n{out}"


def test_b3_files_with_only_the_clean_path_exits_zero(tmp_path):
    """A dirty file exists ELSEWHERE in the repo; --files must not see it."""
    cfg, repo = _write_cfg(tmp_path, {
        "tests/test_ok.py": CLEAN,
        "tests/test_bad.py": DIRTY,
    })
    rc, out, _ = _run(cfg, "--files", str(repo / "tests/test_ok.py"))
    assert rc == 0, f"only the clean path was given -> exit 0, got {rc}\n{out}"
    assert "files scanned: 1" in out, f"exactly 1 file scanned:\n{out}"
    assert "test_x" not in out, f"the repo's other dirty file leaked in:\n{out}"


# ==========================================================================
# Behavior 4 -- zero files scanned exits 2, and that check PRECEDES findings
# ==========================================================================
def test_b4_empty_repo_exits_2_nothing_to_scan(tmp_path):
    cfg, _repo = _write_cfg(tmp_path, {})
    rc, out, _ = _run(cfg)
    assert rc == 2, f"zero files scanned must exit 2, got {rc}\n{out}"
    assert "nothing to scan" in out, f"report must say nothing to scan:\n{out}"
    assert "files scanned: 0" in out, out


def test_b4_files_with_no_paths_exits_2_even_with_a_dirty_repo(tmp_path):
    cfg, _repo = _write_cfg(tmp_path, {"tests/test_bad.py": DIRTY})
    rc, out, _ = _run(cfg, "--files")
    assert rc == 2, f"--files with no paths must exit 2, got {rc}\n{out}"
    assert "nothing to scan" in out, out


def test_b4_nothing_to_scan_outranks_findings_in_the_pure_core(tmp_path):
    """The precedence claim, isolated in the PURE summarizer: 0 files scanned
    reports 2 even when findings are present, never a false 0."""
    s = foundry.summarize_unfailable_asserts(
        product="demoprod", files_scanned=0,
        findings=(("tests/test_bad.py", "test_x"),), parse_errors=())
    assert s.exit_code == 2, f"nothing-to-scan must outrank findings: {s}"
    assert "nothing to scan" in s.verdict, s.verdict
    assert s.clean is False, s


# ==========================================================================
# Behavior 5 -- a parse/read failure degrades gracefully and still exits 1
# ==========================================================================
def test_b5_unparseable_file_is_reported_and_the_scan_continues(tmp_path):
    """`test_a_broken.py` sorts BEFORE `test_z_bad.py`, so the later good
    path's finding proves the scan CONTINUED past the failure."""
    cfg, repo = _write_cfg(tmp_path, {
        "tests/test_a_broken.py": UNPARSEABLE,
        "tests/test_z_bad.py": DIRTY,
    })
    rc, out, err = _run(cfg)
    assert rc == 1, f"a parse error must exit 1, got {rc}\n{out}\n{err}"
    assert "parse errors: 1" in out, f"one parse error expected:\n{out}"
    assert str(repo / "tests/test_a_broken.py") in out, \
        f"the parse-error entry must carry the PATH:\n{out}"
    assert "SyntaxError:" in out, \
        f"the entry must carry `<ExcType>: <msg>`:\n{out}"
    assert "test_x" in out, \
        f"the LATER good path's finding must still appear:\n{out}"
    assert err.strip() == "", f"nothing may be dumped on stderr:\n{err!r}"


def test_b5_unreadable_path_is_an_oserror_entry_not_a_crash(tmp_path):
    cfg, repo = _write_cfg(tmp_path, {"tests/test_z_bad.py": DIRTY})
    missing = repo / "tests/does_not_exist.py"
    rc, out, err = _run(cfg, "--files", str(missing), str(repo / "tests/test_z_bad.py"))
    assert rc == 1, f"an unreadable path must exit 1, got {rc}\n{out}"
    assert "parse errors: 1" in out, out
    assert str(missing) in out, f"the entry must carry the PATH:\n{out}"
    assert "Error:" in out, f"the entry must carry `<ExcType>: <msg>`:\n{out}"
    assert "test_x" in out, f"the later good path must still be scanned:\n{out}"
    assert err.strip() == "", err


def test_b5_a_parse_error_alone_still_exits_1(tmp_path):
    cfg, _repo = _write_cfg(tmp_path, {"tests/test_broken.py": UNPARSEABLE})
    rc, out, _ = _run(cfg)
    assert rc == 1, f"parse error with zero findings must still exit 1, got {rc}\n{out}"
    assert "unfailable-assert tests: 0" in out, out


# ==========================================================================
# Behavior 6 -- the LAST non-empty line is a `verdict:` token agreeing with rc
# ==========================================================================
@pytest.mark.parametrize("label,files,extra,rc_want", [
    ("clean", {"tests/test_ok.py": CLEAN}, (), 0),
    ("findings", {"tests/test_bad.py": DIRTY}, (), 1),
    ("parse-errors", {"tests/test_broken.py": UNPARSEABLE}, (), 1),
    ("nothing", {}, (), 2),
])
def test_b6_verdict_is_the_last_line_and_agrees_with_the_exit_code(
        tmp_path, label, files, extra, rc_want):
    cfg, _repo = _write_cfg(tmp_path, files)
    rc, out, _ = _run(cfg, *extra)
    assert rc == rc_want, f"{label}: expected rc {rc_want}, got {rc}\n{out}"
    last = _last_nonempty(out)
    assert last.startswith("verdict:"), \
        f"{label}: last non-empty line must be the verdict token, got {last!r}\n{out}"
    # the token AGREES with the exit code
    if rc_want == 0:
        assert "clean" in last, f"{label}: {last!r}"
    elif rc_want == 2:
        assert "nothing to scan" in last, f"{label}: {last!r}"
    else:
        assert "clean" not in last and "nothing to scan" not in last, \
            f"{label}: a red verdict must not read clean: {last!r}"


def test_b6_a_clean_report_prints_no_test_function_name(tmp_path):
    cfg, _repo = _write_cfg(tmp_path, {"tests/test_ok.py": CLEAN})
    rc, out, err = _run(cfg)
    assert rc == 0, out
    assert "test_ok" not in out, \
        f"a clean report must name no test FUNCTION anywhere:\n{out}"
    assert "::" not in out, f"no finding rows expected in a clean report:\n{out}"
    assert err.strip() == "", err


# ==========================================================================
# Behavior 7 -- `--json` is exactly one indent=2 document, same figures, same rc
# ==========================================================================
@pytest.mark.parametrize("label,files,extra", [
    ("clean", {"tests/test_ok.py": CLEAN}, ()),
    ("findings", {"tests/test_bad.py": DIRTY}, ()),
    ("parse-errors", {"tests/test_broken.py": UNPARSEABLE}, ()),
    ("nothing", {}, ()),
])
def test_b7_json_is_one_document_with_an_identical_exit_code(
        tmp_path, label, files, extra):
    cfg, _repo = _write_cfg(tmp_path, files)
    rc_h, out_h, _ = _run(cfg, *extra)
    rc_j, out_j, err_j = _run(cfg, *extra, "--json")
    assert rc_j == rc_h, \
        f"{label}: --json rc {rc_j} must equal the human rc {rc_h}"
    assert err_j.strip() == "", f"{label}: stderr must stay empty:\n{err_j!r}"
    doc = json.loads(out_j)  # raises if stdout is not pure JSON
    assert out_j.strip() == json.dumps(doc, indent=2), (
        f"{label}: stdout must be EXACTLY one json.dumps(..., indent=2) "
        f"document:\n{out_j!r}")
    # same figures as the human report
    assert doc["exit_code"] == rc_h, doc
    assert f"files scanned: {doc['files_scanned']}" in out_h, (doc, out_h)
    assert f"unfailable-assert tests: {doc['total_findings']}" in out_h, (doc, out_h)
    assert f"parse errors: {len(doc['parse_errors'])}" in out_h, (doc, out_h)
    assert doc["verdict"] in _last_nonempty(out_h), (doc, out_h)
    assert doc["clean"] is (rc_h == 0), doc


def test_b7_json_honours_files_the_same_way(tmp_path):
    cfg, repo = _write_cfg(tmp_path, {
        "tests/test_ok.py": CLEAN,
        "tests/test_bad.py": DIRTY,
    })
    clean = str(repo / "tests/test_ok.py")
    rc_h, out_h, _ = _run(cfg, "--files", clean)
    rc_j, out_j, _ = _run(cfg, "--files", clean, "--json")
    assert rc_h == rc_j == 0, (rc_h, rc_j, out_h, out_j)
    doc = json.loads(out_j)
    assert doc["files_scanned"] == 1, doc
    assert doc["findings"] == [], f"--files must not walk the repo in JSON mode: {doc}"


# ==========================================================================
# Behavior 8 -- the detector's semantics reach the report unchanged
# ==========================================================================
def test_b8_each_of_the_three_unfailable_kinds_is_flagged(tmp_path):
    cfg, _repo = _write_cfg(tmp_path, {
        "tests/test_k1.py": KIND_LITERAL,
        "tests/test_k2.py": KIND_TUPLE,
        "tests/test_k3.py": KIND_OR,
    })
    rc, out, _ = _run(cfg)
    assert rc == 1, out
    for name in ("test_kind_literal", "test_kind_tuple", "test_kind_or"):
        assert name in out, f"kind {name} must be flagged:\n{out}"
    assert "unfailable-assert tests: 3" in out, out


def test_b8_a_function_with_three_unfailable_asserts_appears_exactly_once(tmp_path):
    cfg, _repo = _write_cfg(tmp_path, {"tests/test_three.py": THREE_IN_ONE})
    rc, out, _ = _run(cfg)
    assert rc == 1, out
    assert out.count("test_zzz_three_kinds") == 1, \
        f"de-duplication failed -- the function appears more than once:\n{out}"
    assert "unfailable-assert tests: 1" in out, out
    _rc, out_j, _ = _run(cfg, "--json")
    doc = json.loads(out_j)
    assert doc["total_findings"] == 1, doc
    assert len(doc["findings"]) == 1, doc


def test_b8_results_are_sorted_alphabetically_by_name(tmp_path):
    """`test_zzz_three_kinds` is written FIRST in the file and
    `test_aaa_first` second, so file order and alphabetical order differ."""
    body = THREE_IN_ONE + FIRST_ALPHA
    cfg, _repo = _write_cfg(tmp_path, {"tests/test_order.py": body})
    rc, out_j, _ = _run(cfg, "--json")
    assert rc == 1, out_j
    names = [f["test"] for f in json.loads(out_j)["findings"]]
    assert names == sorted(names), f"findings must be name-sorted, got {names}"
    assert names == ["test_aaa_first", "test_zzz_three_kinds"], names


def test_b8_a_string_literal_spelling_the_shape_is_data_not_a_finding(tmp_path):
    cfg, _repo = _write_cfg(tmp_path, {"tests/test_data.py": DATA_ONLY})
    rc, out, _ = _run(cfg)
    assert rc == 0, f"string DATA must not be flagged, got rc {rc}\n{out}"
    assert "test_data_not_code" not in out, out
    assert "unfailable-assert tests: 0" in out, out


def test_b8_the_summary_core_is_frozen_with_the_familys_four_fields():
    s = foundry.summarize_unfailable_asserts(
        product="demoprod", files_scanned=1,
        findings=(("tests/test_bad.py", "test_x"),), parse_errors=())
    assert dataclasses.is_dataclass(s), s
    assert type(s).__dataclass_params__.frozen is True, \
        "sibling parity: the summary must be FROZEN"
    assert [f.name for f in dataclasses.fields(s)] == \
        ["product", "files_scanned", "findings", "parse_errors"], \
        [f.name for f in dataclasses.fields(s)]
    for prop in ("total_findings", "clean", "exit_code", "verdict"):
        assert isinstance(getattr(type(s), prop, None), property), \
            f"sibling parity: `{prop}` must be a derived property"
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.files_scanned = 99
    with pytest.raises(TypeError):
        foundry.summarize_unfailable_asserts("demoprod", 1, (), ())  # keyword-only
    assert s.exit_code == 1 and s.clean is False and s.total_findings == 1, s
    assert isinstance(s.render(), str) and s.render().strip(), s.render()
    assert isinstance(s.to_dict(), dict) and s.to_dict(), s.to_dict()


def test_b8_the_gather_seam_resolves_its_detector_by_bare_name(tmp_path):
    """The acceptance criterion's monkeypatch contract: patching the DETECTOR
    on the module must bite THROUGH the thin wrapper (call-time resolution)."""
    cfg_path, repo = _write_cfg(tmp_path, {"tests/test_ok.py": CLEAN})
    cfg = foundry.load_config(str(cfg_path))
    real = foundry.gather_unfailable_asserts(cfg)
    assert real.total_findings == 0, real

    seen = []

    def fake_detector(tree):
        seen.append(tree)
        return ("test_injected",)

    import unittest.mock as _mock
    with _mock.patch.object(foundry, "find_unfailable_assert_tests", fake_detector):
        patched = foundry.gather_unfailable_asserts(cfg)
    assert seen, "the detector seam was resolved at DEF time, not CALL time"
    assert [n for _p, n in patched.findings] == ["test_injected"], patched
    assert patched.exit_code == 1, patched


# ==========================================================================
# Behavior 9 -- the verb is DORMANT and writes nothing
# ==========================================================================
@pytest.mark.parametrize("orchestrator", ["run_iteration", "run_continuous"])
def test_b9_no_new_symbol_is_reachable_from_the_run_path(orchestrator):
    names = _deep_names(getattr(foundry, orchestrator))
    hits = sorted(set(NEW_SYMBOLS) & names)
    assert hits == [], f"{orchestrator} must not reference {hits}"


def test_b9_mains_argparse_dispatch_is_the_only_caller():
    assert "unfailable_asserts_cli" in _deep_names(foundry.main), \
        "main() must dispatch the new verb"
    callers = sorted(
        n for n, fn in _module_functions(foundry).items()
        if n != "main" and "unfailable_asserts_cli" in _deep_names(fn))
    assert callers == [], f"only main() may call the cli, found {callers}"


def test_b9_dispatcher_never_references_the_new_symbols():
    assert set(NEW_SYMBOLS) & set(vars(dispatcher)) == set(), \
        "dispatcher must not import the new symbols"
    hits = {}
    for name, fn in _module_functions(dispatcher).items():
        found = sorted(set(NEW_SYMBOLS) & _deep_names(fn))
        if found:
            hits[name] = found
    assert hits == {}, f"dispatcher references the new symbols: {hits}"


def test_b9_no_role_card_and_no_config_field_mentions_the_verb(tmp_path):
    roles = sorted((_ROOT / "roles").glob("*.md"))
    assert roles, "expected role cards under roles/"
    offenders = [
        p.name for p in roles
        if VERB in p.read_text(encoding="utf-8")
        or any(s in p.read_text(encoding="utf-8") for s in NEW_SYMBOLS)
    ]
    assert offenders == [], f"role cards must stay unwired: {offenders}"

    cfg_path, _repo = _write_cfg(tmp_path, {"tests/test_ok.py": CLEAN})
    cfg = foundry.load_config(str(cfg_path))
    bad = [f.name for f in dataclasses.fields(cfg)
           if "unfailable" in f.name.lower()]
    assert bad == [], f"no config field may be added for this verb: {bad}"


def test_b9_running_the_verb_writes_nothing_into_the_scanned_repo(tmp_path):
    cfg, repo = _write_cfg(tmp_path, {"tests/test_bad.py": DIRTY,
                                      "tests/test_ok.py": CLEAN})
    before = _snapshot(repo)
    rc, _out, _ = _run(cfg)
    assert rc == 1
    _rc, _out, _ = _run(cfg, "--json")
    assert _snapshot(repo) == before, "the scanned repo must be byte-unchanged"


def test_b9_the_verbs_disk_footprint_equals_a_shipped_siblings(tmp_path):
    """The spec says "creates no directories". Measured black-box, the verb's
    OWN body creates none: its footprint is IDENTICAL to the shipped
    `skipped-tests` sibling's, and the only paths either creates are the
    `--config` work/state dirs every `--config` verb makes. Recorded as a spec
    AMBIGUITY, not a defect (see tester.md)."""
    def footprint(verb):
        root = tmp_path / verb
        root.mkdir()
        cfg, _repo = _write_cfg(root, {"tests/test_ok.py": CLEAN})
        before = _paths(root)
        rc, _out, _ = _capture(
            lambda: foundry.main([verb, "--config", str(cfg)]))
        return rc, sorted(p for p in _paths(root) - before)

    rc_new, made_new = footprint(VERB)
    rc_old, made_old = footprint("skipped-tests")
    assert rc_new == rc_old == 0, (rc_new, rc_old)
    assert made_new == made_old, (
        f"the new verb must not add disk effects its shipped sibling lacks: "
        f"new={made_new} sibling={made_old}")


# ==========================================================================
# Behavior 10 -- the README verb index has no gap for the new verb
# ==========================================================================
def test_b10_the_verb_is_registered_and_indexed_in_the_readme():
    """The verb census and the README index are the product's OWN PUBLIC
    oracles; the source text is handed to them, never read by this author."""
    verbs = foundry.foundry_cli_verbs(SOURCE.read_text(encoding="utf-8"))
    assert VERB in verbs, f"{VERB} is not a registered subcommand: {sorted(verbs)[:8]}..."
    audit = foundry.readme_verb_index_gaps(README.read_text(encoding="utf-8"), verbs)
    for tup in ("missing_verbs", "sections_without_invocation", "unknown_invocations"):
        found = tuple(getattr(audit, tup))
        assert VERB not in str(found), f"{VERB} appears in {tup}: {found}"
    assert audit.missing_verbs == (), audit.missing_verbs
    assert audit.sections_without_invocation == (), audit.sections_without_invocation
    assert audit.unknown_invocations == (), audit.unknown_invocations
    assert audit.ok is True, audit


def test_b10_the_readme_section_invokes_the_verb_in_the_copyable_form():
    text = README.read_text(encoding="utf-8")
    assert f"foundry.py {VERB}" in text, \
        "README must gain a section INVOKING the verb"
    lines = [ln for ln in text.splitlines() if f"foundry.py {VERB}" in ln]
    assert lines, text[:200]
    assert any(ln.strip().startswith("uv run python foundry.py") for ln in lines), (
        "iteration 142's rule: there is no bare `foundry` on PATH, so the "
        f"README invocation must be the `uv run python` form; got {lines}")


# ==========================================================================
# Behavior 11 -- the shared helper's docstring count is DERIVED, not stale
# ==========================================================================
def test_b11_gather_test_scan_docstring_count_matches_its_wrapper_count():
    doc = foundry._gather_test_scan.__doc__ or ""
    assert doc.strip(), "_gather_test_scan must keep a docstring"
    wrappers = _thin_wrapper_count()
    assert len(wrappers) == 4, \
        f"expected 4 thin wrappers over _gather_test_scan, found {wrappers}"
    assert "gather_unfailable_asserts" in wrappers, wrappers
    first = doc.strip().splitlines()[0]
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
    want, stale = words[len(wrappers)], words.get(len(wrappers) - 1)
    assert want in first.lower(), (
        f"the docstring's FIRST LINE must state the DERIVED count "
        f"({len(wrappers)} -> {want!r}); got {first!r}")
    assert f"all {stale} " not in doc.lower(), (
        f"the docstring still claims 'all {stale}' while {len(wrappers)} "
        f"wrappers call it: {first!r}")


# ==========================================================================
# Behavior 7 (extended, retry round) -- family parity of the JSON document
# ==========================================================================
SIBLINGS = ("skipped-tests", "constant-asserts", "weak-tests")


@pytest.mark.parametrize("sibling", SIBLINGS)
def test_b7_json_keys_match_every_shipped_sibling(tmp_path, sibling):
    """"the same figures as the human report" is checked above; this pins the
    OTHER half of "in the exact shape its three siblings ship with" -- the JSON
    document's key set must be identical to each shipped sibling's, so the new
    lens is consumable by anything already reading the family."""
    def keys(verb):
        root = tmp_path / verb
        root.mkdir()
        cfg, _repo = _write_cfg(root, {"tests/test_ok.py": CLEAN})
        rc, out, _ = _capture(
            lambda: foundry.main([verb, "--config", str(cfg), "--json"]))
        return rc, sorted(json.loads(out))

    rc_new, keys_new = keys(VERB)
    rc_old, keys_old = keys(sibling)
    assert rc_new == rc_old == 0, (rc_new, rc_old)
    assert keys_new == keys_old, (
        f"JSON key parity with `{sibling}` broken: "
        f"new={keys_new} sibling={keys_old}")


# ==========================================================================
# Acceptance criteria (extended, retry round) -- REUSE, not a fourth body
# ==========================================================================
def test_ac_the_gather_seam_resolves_its_summarizer_by_bare_name(tmp_path):
    """Companion to the detector-seam test: the spec requires BOTH
    `find_unfailable_assert_tests` AND `summarize_unfailable_asserts` to be
    passed by BARE name, resolved at CALL time, so a monkeypatch on the module
    bites through the thin wrapper."""
    cfg_path, _repo = _write_cfg(tmp_path, {"tests/test_ok.py": CLEAN})
    cfg = foundry.load_config(str(cfg_path))
    sentinel = object()
    seen = []

    def fake_summarize(**kw):
        seen.append(kw)
        return sentinel

    import unittest.mock as _mock
    with _mock.patch.object(foundry, "summarize_unfailable_asserts", fake_summarize):
        got = foundry.gather_unfailable_asserts(cfg)
    assert got is sentinel, (
        "the summarizer was resolved at DEF time, not CALL time -- "
        f"monkeypatching foundry.summarize_unfailable_asserts did not bite: {got!r}")
    assert seen and set(seen[0]) == {
        "product", "files_scanned", "findings", "parse_errors"}, seen
    assert seen[0]["files_scanned"] == 1, seen


def test_ac_the_cli_delegates_to_the_shared_thin_printer(tmp_path):
    """`unfailable_asserts_cli` must be a THIN wrapper over the shared
    `_thin_gather_cli`, not a fourth copied body: patching the shared printer
    on the module must intercept the whole call and its return value must be the
    verb's exit code."""
    assert hasattr(foundry, "_thin_gather_cli"), \
        "the shared thin printer is missing from the public module namespace"
    cfg_path, _repo = _write_cfg(tmp_path, {"tests/test_ok.py": CLEAN})
    calls = []

    def fake_thin(*a, **kw):
        calls.append((a, kw))
        return 7

    import unittest.mock as _mock
    with _mock.patch.object(foundry, "_thin_gather_cli", fake_thin):
        rc, out, err = _run(cfg_path)
    assert calls, (
        "unfailable_asserts_cli did not route through _thin_gather_cli -- "
        "a fourth copied body would ignore the patch")
    assert rc == 7, (
        f"the cli must RETURN the shared printer's exit code, got {rc}")
    assert out.strip() == "" and err.strip() == "", (
        f"the wrapper must not print on its own:\nSTDOUT {out!r}\nSTDERR {err!r}")
    assert "gather_unfailable_asserts" in _deep_names(foundry.unfailable_asserts_cli), \
        "the cli must name its own gather seam by BARE name"


# ==========================================================================
# regression: the two modules still import (acceptance criterion 1)
# ==========================================================================
def test_modules_still_import():
    import importlib
    for name in ("foundry", "dispatcher"):
        assert importlib.import_module(name) is not None
