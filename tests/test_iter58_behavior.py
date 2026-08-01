"""Black-box behaviour tests for iter 58 -- the read-only `foundry test-quality
--config <cfg> [--files ...] [--json]` per-product COMPOSITE test-quality gate
that folds all THREE offline "validates-nothing" scans into ONE scan / ONE
0/1/2 exit code / ONE three-way verdict / ONE JSON document: #12 `weak-tests`
(assertion-free), #21 `constant-asserts` (constant/tautological assert), #23
`skipped-tests` (never runs). It is the QUALITY-axis parallel of the #15 launch
`preflight` composite, calling the SHIPPED `gather_weak_tests` /
`gather_constant_asserts` / `gather_skipped_tests` seams by BARE module name and
rolling their frozen summaries up into a frozen `TestQualitySummary`.

New public surface exercised here: frozen `TestQualitySummary`, the pure
keyword-only `summarize_test_quality(*, product, weak, constant, skipped)`, and
the thin `test_quality_cli(cfg, files=None, as_json=False)` / the
`main(["test-quality", ...])` entry.

OVERLAP note (a first-class correctness item, per the iter-56/57/58
disjoint-vs-overlap lesson): `constant-asserts` is DISJOINT from `weak-tests` by
the detectors' construction (a constant assert CARRIES an assert node, so an
assertion-free scan can never also flag it), BUT an always-skipped test CAN also
be assertion-free AND can carry a constant assert -- so `skipped` findings CAN
OVERLAP `weak` and `constant`. Therefore `total_findings` is a per-CATEGORY
triage total in which a test flagged by two lenses counts once in EACH category
(intentionally NOT a de-duplicated distinct-test count).

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-58 PM
spec's Expected Behaviors (1-9), the product README/roadmap, the `tests/`
conventions (esp. tests/test_iter48_behavior.py -- the constant-asserts
per-product CLI, the closest sibling weight class), and the product's OWN
OBSERVABLE behaviour (by RUNNING it / public RUNTIME introspection: module
attributes, `--help` output, compiled `__code__.co_names` tables). The
implementation SOURCE (foundry.py / dispatcher.py source text), the engineer's
and reviewer's notes, and `git diff` were NOT read. Every check drives the
PUBLIC interface: the composite builder via `foundry.summarize_test_quality(...)`
over directly-constructed frozen sub-summaries, and the CLI via
`foundry.test_quality_cli(...)` / `foundry.main([...])` against a
ProductConfig with `repo="/nonexistent"` + synthetic temp `--files` (the real
foundry repo is NEVER touched, and the nonexistent repo proves `--files` does
not walk it). The dormancy / off-control-path checks use only public RUNTIME
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
# helpers  (mirror tests/test_iter48_behavior.py)
# --------------------------------------------------------------------------
def _W(**over):
    """Build a frozen sub-`WeakTestSummary` (assertion-free lens)."""
    base = {"product": "p", "files_scanned": 0, "findings": (), "parse_errors": ()}
    base.update(over)
    return foundry.summarize_weak_tests(**base)


def _C(**over):
    """Build a frozen sub-`ConstantAssertSummary` (constant-assert lens)."""
    base = {"product": "p", "files_scanned": 0, "findings": (), "parse_errors": ()}
    base.update(over)
    return foundry.summarize_constant_asserts(**base)


def _S(**over):
    """Build a frozen sub-`SkippedTestSummary` (always-skipped lens)."""
    base = {"product": "p", "files_scanned": 0, "findings": (), "parse_errors": ()}
    base.update(over)
    return foundry.summarize_skipped_tests(**base)


def _TQ(product="p", weak=None, constant=None, skipped=None, **fs):
    """Build the composite. `fs` optionally sets a shared files_scanned for the
    three defaulted sub-summaries so a caller can say `_TQ(files_scanned=3)`."""
    n = fs.pop("files_scanned", 0)
    return foundry.summarize_test_quality(
        product=product,
        weak=weak if weak is not None else _W(files_scanned=n),
        constant=constant if constant is not None else _C(files_scanned=n),
        skipped=skipped if skipped is not None else _S(files_scanned=n),
    )


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


def _prodcfg(tmp_path, repo="/nonexistent"):
    """A directly-constructed ProductConfig with a NONEXISTENT repo (proving
    `--files` does not walk it), for the CLI seam tests."""
    return foundry.ProductConfig(
        name="p",
        repo=repo,
        allowed_push_repo="p",
        vision=str(tmp_path / "VISION.md"),
        work_root=str(tmp_path / "work"),
    )


def _write_cfg(tmp_path, **over):
    """A minimal product config JSON file (for the `main(["test-quality", ...])`
    dispatch tests). `repo` is a TMP dir so the real foundry repo is NEVER
    touched."""
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


NEW_SYMBOLS = ("TestQualitySummary", "summarize_test_quality", "test_quality_cli")
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")

# A synthetic test source whose test_over is BOTH assertion-free AND
# @pytest.mark.skip-decorated -> it overlaps the weak-tests and skipped-tests
# lenses. test_real has a real (Compare) assert -> flagged by none.
OVERLAP_SRC = (
    "import pytest\n\n"
    "@pytest.mark.skip\n"
    "def test_over():\n    pass\n\n"
    "def test_real():\n    assert x == 1\n"
)


# ==========================================================================
# Behavior 1 -- pure clean composite (+ fields / keyword-only / frozen / type)
# ==========================================================================
def test_b01_clean_composite():
    s = foundry.summarize_test_quality(
        product="p",
        weak=_W(files_scanned=3), constant=_C(files_scanned=3), skipped=_S(files_scanned=3),
    )
    assert type(s).__name__ == "TestQualitySummary", f"wrong type: {type(s).__name__}"
    assert dataclasses.is_dataclass(s)
    assert s.files_scanned == 3, s.files_scanned
    assert s.weak_findings == 0, s.weak_findings
    assert s.constant_findings == 0, s.constant_findings
    assert s.skipped_findings == 0, s.skipped_findings
    assert s.total_findings == 0, s.total_findings
    assert s.total_parse_errors == 0, s.total_parse_errors
    assert s.clean is True, s.clean
    assert s.exit_code == 0, s.exit_code
    assert s.verdict == "clean", s.verdict


def test_b01_fields_are_the_three_sub_summaries():
    w, c, sk = _W(files_scanned=1), _C(files_scanned=1), _S(files_scanned=1)
    s = foundry.summarize_test_quality(product="prod", weak=w, constant=c, skipped=sk)
    assert s.product == "prod", s.product
    assert s.weak is w, "weak field must be the given sub-summary"
    assert s.constant is c, "constant field must be the given sub-summary"
    assert s.skipped is sk, "skipped field must be the given sub-summary"


def test_b01_keyword_only():
    with pytest.raises(TypeError):
        foundry.summarize_test_quality("p", _W(), _C(), _S())


def test_b01_frozen():
    s = _TQ(files_scanned=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.product = "x"


def test_b01_files_scanned_is_weak_value_invariant():
    # documented invariant: files_scanned == self.weak.files_scanned (all three
    # lenses walk the identical set in a real run).
    s = foundry.summarize_test_quality(
        product="p", weak=_W(files_scanned=7), constant=_C(files_scanned=7), skipped=_S(files_scanned=7),
    )
    assert s.files_scanned == 7 == s.weak.files_scanned


# ==========================================================================
# Behavior 2 -- single-lens finding gates each yield exit_code 1
# ==========================================================================
def test_b02_lone_weak_finding_gates():
    s = foundry.summarize_test_quality(
        product="p",
        weak=_W(files_scanned=1, findings=(("t.py", "test_x"),)),
        constant=_C(files_scanned=1), skipped=_S(files_scanned=1),
    )
    assert s.weak_findings == 1, s.weak_findings
    assert s.total_findings == 1, s.total_findings
    assert s.clean is False, s.clean
    assert s.exit_code == 1, s.exit_code
    assert s.verdict == "QUALITY ISSUES FOUND", s.verdict


def test_b02_lone_constant_finding_gates():
    s = foundry.summarize_test_quality(
        product="p",
        weak=_W(files_scanned=1),
        constant=_C(files_scanned=1, findings=(("t.py", "test_x"),)),
        skipped=_S(files_scanned=1),
    )
    assert s.constant_findings == 1 and s.total_findings == 1
    assert s.exit_code == 1 and s.verdict == "QUALITY ISSUES FOUND"


def test_b02_lone_skipped_finding_gates():
    s = foundry.summarize_test_quality(
        product="p",
        weak=_W(files_scanned=1), constant=_C(files_scanned=1),
        skipped=_S(files_scanned=1, findings=(("t.py", "test_x"),)),
    )
    assert s.skipped_findings == 1 and s.total_findings == 1
    assert s.exit_code == 1 and s.verdict == "QUALITY ISSUES FOUND"


# ==========================================================================
# Behavior 3 -- pure nothing-to-scan; and the all-2-vs-any exit rule
# ==========================================================================
def test_b03_nothing_to_scan():
    s = _TQ(files_scanned=0)  # all three sub-summaries files_scanned==0 (each exit 2)
    assert s.files_scanned == 0, s.files_scanned
    assert s.total_findings == 0, s.total_findings
    assert s.clean is False, "nothing-to-scan must NOT be clean"
    assert s.exit_code == 2, s.exit_code
    assert s.verdict == "nothing to scan", s.verdict


def test_b03_exit_2_only_when_all_lenses_nothing():
    # per the exit_code rule: 2 iff every lens had nothing to scan; a single
    # lens that DID scan (exit 0) with no findings -> composite is clean (0),
    # NOT 2. Robust to independently-constructed sub-summaries.
    s = foundry.summarize_test_quality(
        product="p",
        weak=_W(files_scanned=0),      # exit 2
        constant=_C(files_scanned=3),  # exit 0
        skipped=_S(files_scanned=3),   # exit 0
    )
    assert (s.weak.exit_code, s.constant.exit_code, s.skipped.exit_code) == (2, 0, 0)
    assert s.exit_code == 0, "not-all-2 with no findings must be clean(0), not 2"
    assert s.verdict == "clean"


def test_b03_findings_win_over_nothing_to_scan():
    # a finding anywhere (exit 1) beats a lens that scanned nothing (exit 2).
    s = foundry.summarize_test_quality(
        product="p",
        weak=_W(files_scanned=0),   # exit 2
        constant=_C(files_scanned=0),  # exit 2
        skipped=_S(files_scanned=1, findings=(("t.py", "test_x"),)),  # exit 1
    )
    assert s.exit_code == 1 and s.verdict == "QUALITY ISSUES FOUND"


# ==========================================================================
# Behavior 4 -- pure OVERLAP is category-weighted (NOT de-duplicated)
# ==========================================================================
def test_b04_overlap_is_category_weighted():
    s = foundry.summarize_test_quality(
        product="p",
        weak=_W(files_scanned=1, findings=(("t.py", "test_over"),)),
        constant=_C(files_scanned=1),
        skipped=_S(files_scanned=1, findings=(("t.py", "test_over"),)),
    )
    assert s.weak_findings == 1, s.weak_findings
    assert s.skipped_findings == 1, s.skipped_findings
    assert s.constant_findings == 0, s.constant_findings
    # the shared test counts once PER CATEGORY -> 2, not a de-duplicated 1.
    assert s.total_findings == 2, f"category-weighted total must be 2, got {s.total_findings}"
    assert s.exit_code == 1, s.exit_code


def test_b04_triple_overlap_counts_three():
    # a test flagged by all three lenses counts once in each -> total 3.
    f = (("t.py", "test_all"),)
    s = foundry.summarize_test_quality(
        product="p",
        weak=_W(files_scanned=1, findings=f),
        constant=_C(files_scanned=1, findings=f),
        skipped=_S(files_scanned=1, findings=f),
    )
    assert (s.weak_findings, s.constant_findings, s.skipped_findings) == (1, 1, 1)
    assert s.total_findings == 3, s.total_findings


# ==========================================================================
# Behavior 5 -- parse-error dedup (identical) + distinct union (different)
# ==========================================================================
def test_b05_parse_error_dedup_identical():
    pe = (("bad.py", "SyntaxError: boom"),)
    s = foundry.summarize_test_quality(
        product="p",
        weak=_W(files_scanned=1, parse_errors=pe),
        constant=_C(files_scanned=1, parse_errors=pe),
        skipped=_S(files_scanned=1, parse_errors=pe),
    )
    assert len(s.parse_errors) == 1, f"identical parse errors must dedup to 1, got {s.parse_errors}"
    assert s.parse_errors == pe, s.parse_errors
    assert s.total_parse_errors == 1, s.total_parse_errors
    assert s.exit_code == 1, s.exit_code
    assert s.clean is False, s.clean


def test_b05_parse_error_distinct_union_first_seen_order():
    s = foundry.summarize_test_quality(
        product="p",
        weak=_W(files_scanned=1, parse_errors=(("a.py", "SyntaxError: a"),)),
        constant=_C(files_scanned=1, parse_errors=(("b.py", "SyntaxError: b"),)),
        skipped=_S(files_scanned=1, parse_errors=(("c.py", "SyntaxError: c"),)),
    )
    # distinct union in first-seen order: weak, then constant, then skipped.
    assert s.parse_errors == (
        ("a.py", "SyntaxError: a"),
        ("b.py", "SyntaxError: b"),
        ("c.py", "SyntaxError: c"),
    ), s.parse_errors
    assert s.total_parse_errors == 3, s.total_parse_errors


def test_b05_parse_error_partial_overlap_dedups():
    # a shared entry appears once; the distinct ones follow in first-seen order.
    shared = ("dup.py", "SyntaxError: dup")
    s = foundry.summarize_test_quality(
        product="p",
        weak=_W(files_scanned=1, parse_errors=(shared,)),
        constant=_C(files_scanned=1, parse_errors=(shared, ("only_c.py", "SyntaxError: c"))),
        skipped=_S(files_scanned=1, parse_errors=(shared,)),
    )
    assert s.parse_errors == (shared, ("only_c.py", "SyntaxError: c")), s.parse_errors
    assert s.total_parse_errors == 2, s.total_parse_errors


# ==========================================================================
# Behavior 6 -- to_dict(): 14 keys in order, JSON-safe, round-trips
# ==========================================================================
EXPECTED_KEYS = [
    "product", "files_scanned", "weak_findings", "constant_findings",
    "skipped_findings", "total_findings", "total_parse_errors", "clean",
    "exit_code", "verdict", "weak", "constant", "skipped", "parse_errors",
]


def test_b06_to_dict_exact_keys_in_order():
    s = foundry.summarize_test_quality(
        product="p",
        weak=_W(files_scanned=2, findings=(("a.py", "test_x"),)),
        constant=_C(files_scanned=2),
        skipped=_S(files_scanned=2),
    )
    d = s.to_dict()
    assert list(d.keys()) == EXPECTED_KEYS, f"to_dict keys/order wrong: {list(d.keys())}"


def test_b06_to_dict_sub_docs_verbatim():
    s = foundry.summarize_test_quality(
        product="p",
        weak=_W(files_scanned=2, findings=(("a.py", "test_x"),)),
        constant=_C(files_scanned=2, findings=(("b.py", "test_y"),)),
        skipped=_S(files_scanned=2, findings=(("c.py", "test_z"),)),
    )
    d = s.to_dict()
    assert d["weak"] == s.weak.to_dict(), "weak sub-doc must be the sub to_dict() verbatim"
    assert d["constant"] == s.constant.to_dict(), "constant sub-doc must be verbatim"
    assert d["skipped"] == s.skipped.to_dict(), "skipped sub-doc must be verbatim"


def test_b06_to_dict_parse_errors_array_of_objects():
    s = foundry.summarize_test_quality(
        product="p",
        weak=_W(files_scanned=1, parse_errors=(("a.py", "SyntaxError: a"),)),
        constant=_C(files_scanned=1, parse_errors=(("b.py", "SyntaxError: b"),)),
        skipped=_S(files_scanned=1),
    )
    d = s.to_dict()
    assert d["parse_errors"] == [
        {"file": "a.py", "message": "SyntaxError: a"},
        {"file": "b.py", "message": "SyntaxError: b"},
    ], d["parse_errors"]


def test_b06_to_dict_scalars_equal_properties():
    s = foundry.summarize_test_quality(
        product="p",
        weak=_W(files_scanned=2, findings=(("a.py", "test_x"),)),
        constant=_C(files_scanned=2),
        skipped=_S(files_scanned=2, findings=(("a.py", "test_x"),)),
    )
    d = s.to_dict()
    assert d["product"] == s.product
    assert d["files_scanned"] == s.files_scanned
    assert d["weak_findings"] == s.weak_findings
    assert d["constant_findings"] == s.constant_findings
    assert d["skipped_findings"] == s.skipped_findings
    assert d["total_findings"] == s.total_findings
    assert d["total_parse_errors"] == s.total_parse_errors
    assert d["clean"] == s.clean
    assert d["exit_code"] == s.exit_code
    assert d["verdict"] == s.verdict


def test_b06_to_dict_round_trips_including_empty():
    for s in (
        _TQ(files_scanned=2),
        foundry.summarize_test_quality(
            product="p",
            weak=_W(files_scanned=2, findings=(("a.py", "test_x"),)),
            constant=_C(files_scanned=2, parse_errors=(("b.py", "SyntaxError: e"),)),
            skipped=_S(files_scanned=2, findings=(("a.py", "test_x"),)),
        ),
    ):
        d = s.to_dict()
        assert json.loads(json.dumps(d)) == d, f"to_dict must round-trip via json: {d}"


# ==========================================================================
# Behavior 7 -- render(): deterministic multi-line report contract
# ==========================================================================
def test_b07_render_substrings_and_tagged_findings():
    s = foundry.summarize_test_quality(
        product="demo",
        weak=_W(files_scanned=3, findings=(("wf.py", "test_free"),)),
        constant=_C(files_scanned=3, findings=(("cf.py", "test_const"),)),
        skipped=_S(files_scanned=3, findings=(("sf.py", "test_skip"),),
                   parse_errors=(("bad.py", "SyntaxError: boom"),)),
    )
    text = s.render()
    assert isinstance(text, str) and text.strip()
    assert "foundry test-quality -- demo" in text, text
    assert "files scanned: 3" in text, text
    assert "assertion-free tests: 1" in text, text
    assert "constant-assert tests: 1" in text, text
    assert "always-skipped tests: 1" in text, text
    assert "total quality findings: 3" in text, text
    # one tagged line per finding, per lens
    assert "[assertion-free] wf.py :: test_free" in text, text
    assert "[constant-assert] cf.py :: test_const" in text, text
    assert "[always-skipped] sf.py :: test_skip" in text, text
    # parse errors count + one `  <file>: <message>` line
    assert "parse errors: 1" in text, text
    assert "bad.py: SyntaxError: boom" in text, text
    # LAST non-empty line is `verdict: <token>` matching exit_code
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[-1] == "verdict: QUALITY ISSUES FOUND", f"last non-empty line: {lines[-1]!r}"


def test_b07_render_overlap_appears_under_both_tags():
    s = foundry.summarize_test_quality(
        product="p",
        weak=_W(files_scanned=1, findings=(("t.py", "test_over"),)),
        constant=_C(files_scanned=1),
        skipped=_S(files_scanned=1, findings=(("t.py", "test_over"),)),
    )
    text = s.render()
    assert "[assertion-free] t.py :: test_over" in text, text
    assert "[always-skipped] t.py :: test_over" in text, text
    assert "total quality findings: 2" in text, text


def test_b07_render_clean_shows_no_finding_lines():
    s = _TQ(files_scanned=2)
    text = s.render()
    assert "assertion-free tests: 0" in text, text
    assert "constant-assert tests: 0" in text, text
    assert "always-skipped tests: 0" in text, text
    assert "total quality findings: 0" in text, text
    assert "[assertion-free]" not in text, "clean composite must print NO finding lines"
    assert "[constant-assert]" not in text
    assert "[always-skipped]" not in text
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[-1] == "verdict: clean", f"clean verdict last line, got {lines[-1]!r}"


def test_b07_render_last_line_matches_verdict_every_state():
    for s in (_TQ(files_scanned=0), _TQ(files_scanned=2),
              foundry.summarize_test_quality(
                  product="p",
                  weak=_W(files_scanned=2, findings=(("a.py", "t"),)),
                  constant=_C(files_scanned=2), skipped=_S(files_scanned=2))):
        lines = [ln for ln in s.render().splitlines() if ln.strip()]
        assert lines[-1] == f"verdict: {s.verdict}", (
            f"render last line must be `verdict: {s.verdict}`, got {lines[-1]!r}"
        )


# ==========================================================================
# Behavior 8 -- test_quality_cli(cfg, files, as_json): 3 seams bite; print+rc
# ==========================================================================
def test_b08_cli_over_nonexistent_repo_scans_only_given_files(tmp_path):
    cfg = _prodcfg(tmp_path)  # repo="/nonexistent"
    target = tmp_path / "test_over.py"
    target.write_text(OVERLAP_SRC)
    before = _snapshot_tree(tmp_path)
    rc, out, err = _capture(lambda: foundry.test_quality_cli(cfg, files=[str(target)], as_json=False))
    assert rc == 1, f"an overlapping quality issue must exit 1, got {rc}\n{out}{err}"
    assert "foundry test-quality -- p" in out, out
    # test_over is BOTH assertion-free AND always-skipped -> under BOTH tags
    assert "[assertion-free]" in out and "test_over" in out, out
    assert "[always-skipped]" in out, out
    assert out.rstrip().endswith("verdict: QUALITY ISSUES FOUND"), out
    assert _snapshot_tree(tmp_path) == before, "cli wrote to disk (must be read-only)"


def test_b08_cli_json_prints_composite_doc(tmp_path):
    cfg = _prodcfg(tmp_path)
    target = tmp_path / "test_over.py"
    target.write_text(OVERLAP_SRC)
    rc, out, _ = _capture(lambda: foundry.test_quality_cli(cfg, files=[str(target)], as_json=True))
    assert rc == 1, rc
    doc = json.loads(out)  # the ENTIRE stdout is the JSON document
    assert list(doc.keys()) == EXPECTED_KEYS, doc
    assert doc["exit_code"] == 1 and doc["verdict"] == "QUALITY ISSUES FOUND"
    # embeds the three sub-docs
    for k in ("weak", "constant", "skipped"):
        assert isinstance(doc[k], dict) and "findings" in doc[k], doc[k]


def test_b08_cli_empty_files_returns_exit_2(tmp_path):
    cfg = _prodcfg(tmp_path)
    rc, out, _ = _capture(lambda: foundry.test_quality_cli(cfg, files=[], as_json=False))
    assert rc == 2, f"empty --files scans nothing -> exit 2, got {rc}"
    assert out.rstrip().endswith("verdict: nothing to scan"), out


def test_b08_each_gather_seam_bites_independently(tmp_path, monkeypatch):
    cfg = _prodcfg(tmp_path)
    target = tmp_path / "test_x.py"
    target.write_text("def test_x():\n    assert y == 1\n")  # clean under all lenses

    # weak seam
    monkeypatch.setattr(foundry, "gather_weak_tests",
                        lambda c, files=None: _W(files_scanned=1, findings=(("fake.py", "FAKE_WEAK"),)))
    rc, out, _ = _capture(lambda: foundry.test_quality_cli(cfg, files=[str(target)], as_json=False))
    assert "FAKE_WEAK" in out and rc == 1, (rc, out)
    monkeypatch.undo()

    # constant seam
    monkeypatch.setattr(foundry, "gather_constant_asserts",
                        lambda c, files=None: _C(files_scanned=1, findings=(("fake.py", "FAKE_CONST"),)))
    rc, out, _ = _capture(lambda: foundry.test_quality_cli(cfg, files=[str(target)], as_json=False))
    assert "FAKE_CONST" in out and rc == 1, (rc, out)
    monkeypatch.undo()

    # skipped seam
    monkeypatch.setattr(foundry, "gather_skipped_tests",
                        lambda c, files=None: _S(files_scanned=1, findings=(("fake.py", "FAKE_SKIP"),)))
    rc, out, _ = _capture(lambda: foundry.test_quality_cli(cfg, files=[str(target)], as_json=False))
    assert "FAKE_SKIP" in out and rc == 1, (rc, out)


def test_b08_cli_returns_summary_exit_code_clean(tmp_path):
    cfg = _prodcfg(tmp_path)
    target = tmp_path / "test_clean.py"
    target.write_text("def test_real():\n    assert z == 3\n")  # a real assert, runs
    before = _snapshot_tree(tmp_path)
    rc, out, _ = _capture(lambda: foundry.test_quality_cli(cfg, files=[str(target)], as_json=False))
    assert rc == 0, f"a clean asserting test must exit 0, got {rc}\n{out}"
    assert out.rstrip().endswith("verdict: clean"), out
    assert _snapshot_tree(tmp_path) == before, "cli wrote to disk (must be read-only)"


# ==========================================================================
# Behavior 9 -- main(["test-quality", ...]) dispatch + --json + --help + dormancy
# ==========================================================================
def test_b09_main_overlap_shows_both_tags(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    target = tmp_path / "test_over.py"
    target.write_text(OVERLAP_SRC)
    rc, out, _ = _capture(lambda: foundry.main(["test-quality", "--config", str(cfg_path), "--files", str(target)]))
    assert rc == 1, (rc, out)
    assert "[assertion-free]" in out and "[always-skipped]" in out, out
    assert out.count("test_over") >= 2, f"test_over must appear under BOTH tags:\n{out}"


def test_b09_main_json_embeds_three_sub_docs(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    target = tmp_path / "test_over.py"
    target.write_text(OVERLAP_SRC)
    rc, out, _ = _capture(lambda: foundry.main(
        ["test-quality", "--config", str(cfg_path), "--files", str(target), "--json"]))
    assert rc == 1, rc
    doc = json.loads(out)
    assert doc["exit_code"] == 1
    for k in ("weak", "constant", "skipped"):
        assert isinstance(doc[k], dict), doc


def test_b09_main_clean_exit_0(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    target = tmp_path / "test_clean.py"
    target.write_text("def test_real():\n    assert a == 1\n")
    rc, _, _ = _capture(lambda: foundry.main(["test-quality", "--config", str(cfg_path), "--files", str(target)]))
    assert rc == 0, rc


def test_b09_main_missing_config_is_usage_error():
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["test-quality"])
    assert ei.value.code != 0, "test-quality without --config must be a usage error"


def test_b09_help_lists_test_quality_and_siblings():
    buf = io.StringIO()
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stdout(buf):
            foundry.main(["--help"])
    assert ei.value.code == 0
    out = buf.getvalue()
    assert "test-quality" in out, f"--help must list the new subcommand:\n{out}"
    for sib in ("weak-tests", "constant-asserts", "skipped-tests"):
        assert sib in out, f"--help must still list {sib} (no regression):\n{out}"


def test_b09_new_surface_present_and_callable():
    assert isinstance(foundry.TestQualitySummary, type)
    assert callable(foundry.summarize_test_quality)
    assert callable(foundry.test_quality_cli)
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
