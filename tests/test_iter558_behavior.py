"""Black-box behaviour tests for iter 558 -- `foundry test-quality --files`
puts every non-`.py` path on a `not applicable:` line instead of parsing it as
Python; a run left with no Python file exits 0 with
`verdict: not applicable (no Python test files)`, never `verdict: clean`.

ISOLATION CONTRACT (HONORED): written only from the iter-558 PM spec's Expected
Behaviors 1-9, the tests/ conventions (tests/test_iter58_behavior.py), and the
product's own observable CLI output. The implementation source, the engineer's
and reviewer's notes and `git diff` were NOT read.

Fixtures are built in tmp_path; the config is a tmp JSON file whose repo is a
tmp dir, so no gitignored or machine-local state is read.
"""
import contextlib
import io
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402

NA_VERDICT = "not applicable (no Python test files)"

TS_TEXT = 'it("x", () => {});\n'
BAD_PY = "def test_x(:\n"
OK_PY = "def test_ok():\n    x = 1\n    assert x + 1 == 2\n"

# test_iter58 b06 pin for Python-only input (copied literal, not imported).
EXPECTED_KEYS_PY_ONLY = [
    "product", "files_scanned", "weak_findings", "constant_findings",
    "skipped_findings", "total_findings", "total_parse_errors", "clean",
    "exit_code", "verdict", "weak", "constant", "skipped", "parse_errors",
]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _write_cfg(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _fixtures(tmp_path):
    d = tmp_path / "fx"
    d.mkdir(exist_ok=True)
    (d / "a.test.ts").write_text(TS_TEXT)
    (d / "b.test.ts").write_text(TS_TEXT)
    (d / "a.spec.js").write_text("describe('y', function () { it('z'); });\n")
    (d / "test_bad.py").write_text(BAD_PY)
    (d / "test_ok.py").write_text(OK_PY)
    return d


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = foundry.main(argv)
        except SystemExit as e:  # argparse / sys.exit paths
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


def _tq(tmp_path, *paths, as_json=False, verb="test-quality"):
    cfg = _write_cfg(tmp_path)
    argv = [verb, "--config", str(cfg), "--files", *[str(p) for p in paths]]
    if as_json:
        argv.append("--json")
    return _run(argv)


def _last_line(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _na_lines(text):
    return [ln for ln in text.splitlines() if ln.startswith("  not applicable: ")]


def _sub(fn, n=0, **over):
    base = {"product": "p", "files_scanned": n, "findings": (), "parse_errors": ()}
    base.update(over)
    return fn(**base)


def _nothing_subs():
    return dict(
        weak=_sub(foundry.summarize_weak_tests),
        constant=_sub(foundry.summarize_constant_asserts),
        skipped=_sub(foundry.summarize_skipped_tests),
    )


# ==========================================================================
# EB1 -- a lone .ts file: exit 0, honest not-applicable verdict
# ==========================================================================
def test_eb1_ts_only_exits_zero_with_not_applicable_verdict(tmp_path):
    d = _fixtures(tmp_path)
    ts = d / "a.test.ts"
    rc, out, _ = _tq(tmp_path, ts)
    assert rc == 0, out
    assert "  files scanned: 0" in out.splitlines(), out
    assert "  parse errors: 0" in out.splitlines(), out
    assert f"  not applicable: {ts}" in out.splitlines(), out
    assert _last_line(out) == f"verdict: {NA_VERDICT}", out
    assert "verdict: clean" not in out
    assert "SyntaxError" not in out


# ==========================================================================
# EB2 -- the same run as --json
# ==========================================================================
def test_eb2_ts_only_json_document(tmp_path):
    d = _fixtures(tmp_path)
    ts = d / "a.test.ts"
    rc, out, _ = _tq(tmp_path, ts, as_json=True)
    assert rc == 0, out
    doc = json.loads(out)
    assert doc["exit_code"] == 0
    assert doc["clean"] is False
    assert doc["verdict"] == NA_VERDICT
    assert doc["files_scanned"] == 0
    assert doc["total_parse_errors"] == 0
    assert doc["not_applicable"] == [str(ts)]
    assert list(doc.keys())[-1] == "not_applicable", list(doc.keys())


# ==========================================================================
# EB3 -- a broken .py keeps today's behaviour (the other side of the pin)
# ==========================================================================
def test_eb3_broken_python_still_exits_one(tmp_path):
    d = _fixtures(tmp_path)
    bad = d / "test_bad.py"
    rc, out, _ = _tq(tmp_path, bad)
    assert rc == 1, out
    assert "  parse errors: 1" in out.splitlines(), out
    assert any("test_bad.py" in ln and "SyntaxError" in ln for ln in out.splitlines()), out
    assert _last_line(out) == "verdict: QUALITY ISSUES FOUND", out
    assert _na_lines(out) == [], out
    assert "not applicable" not in out


def test_eb3_broken_python_json_has_no_not_applicable_key(tmp_path):
    d = _fixtures(tmp_path)
    rc, out, _ = _tq(tmp_path, d / "test_bad.py", as_json=True)
    assert rc == 1, out
    doc = json.loads(out)
    assert "not_applicable" not in doc, list(doc.keys())
    assert list(doc.keys()) == EXPECTED_KEYS_PY_ONLY, list(doc.keys())


# ==========================================================================
# EB4 -- mixed .ts + broken .py: exit 1, only the .py is a parse error
# ==========================================================================
def test_eb4_mixed_ts_and_broken_py(tmp_path):
    d = _fixtures(tmp_path)
    ts, bad = d / "a.test.ts", d / "test_bad.py"
    rc, out, _ = _tq(tmp_path, ts, bad)
    assert rc == 1, out
    lines = out.splitlines()
    assert "  files scanned: 1" in lines, out
    assert "  parse errors: 1" in lines, out
    assert _na_lines(out) == [f"  not applicable: {ts}"], out
    syntax = [ln for ln in lines if "SyntaxError" in ln]
    assert len(syntax) == 1 and "test_bad.py" in syntax[0] and "a.test.ts" not in syntax[0], out
    assert _last_line(out) == "verdict: QUALITY ISSUES FOUND", out


# ==========================================================================
# EB5 -- mixed .ts + good .py: clean (a Python file WAS scanned)
# ==========================================================================
def test_eb5_mixed_ts_and_good_py_is_clean(tmp_path):
    d = _fixtures(tmp_path)
    ts, ok = d / "a.test.ts", d / "test_ok.py"
    rc, out, _ = _tq(tmp_path, ts, ok)
    assert rc == 0, out
    assert "  files scanned: 1" in out.splitlines(), out
    assert _na_lines(out) == [f"  not applicable: {ts}"], out
    assert _last_line(out) == "verdict: clean", out


def test_eb5_mixed_ts_and_good_py_json_clean_true(tmp_path):
    d = _fixtures(tmp_path)
    ts, ok = d / "a.test.ts", d / "test_ok.py"
    rc, out, _ = _tq(tmp_path, ts, ok, as_json=True)
    assert rc == 0, out
    doc = json.loads(out)
    assert doc["clean"] is True
    assert doc["verdict"] == "clean"
    assert doc["not_applicable"] == [str(ts)]


# ==========================================================================
# EB6 -- several non-Python files: one line each, in argv order
# ==========================================================================
def test_eb6_several_non_python_files_in_input_order(tmp_path):
    d = _fixtures(tmp_path)
    b, a = d / "b.test.ts", d / "a.spec.js"
    rc, out, _ = _tq(tmp_path, b, a)
    assert rc == 0, out
    assert _na_lines(out) == [f"  not applicable: {b}", f"  not applicable: {a}"], out
    assert _last_line(out) == f"verdict: {NA_VERDICT}", out
    rc2, out2, _ = _tq(tmp_path, a, b, as_json=True)
    assert rc2 == 0, out2
    assert json.loads(out2)["not_applicable"] == [str(a), str(b)]


# ==========================================================================
# EB7 -- empty --files and Python-only input are unchanged
# ==========================================================================
def test_eb7_empty_files_list_still_nothing_to_scan(tmp_path):
    rc, out, _ = _tq(tmp_path)
    assert rc == 2, out
    assert _last_line(out) == "verdict: nothing to scan", out
    assert "not applicable" not in out


def test_eb7_python_only_cli_output_shape_unchanged(tmp_path):
    d = _fixtures(tmp_path)
    rc, out, _ = _tq(tmp_path, d / "test_ok.py")
    assert rc == 0, out
    assert out.splitlines() == [
        "foundry test-quality -- demoprod",
        "  files scanned: 1",
        "  assertion-free tests: 0",
        "  constant-assert tests: 0",
        "  always-skipped tests: 0",
        "  total quality findings: 0",
        "  parse errors: 0",
        "verdict: clean",
    ], out


def test_eb7_summarize_without_kwarg_keeps_pinned_keys():
    s = foundry.summarize_test_quality(
        product="p",
        weak=_sub(foundry.summarize_weak_tests, 2, findings=(("a.py", "test_x"),)),
        constant=_sub(foundry.summarize_constant_asserts, 2),
        skipped=_sub(foundry.summarize_skipped_tests, 2),
    )
    d = s.to_dict()
    assert list(d.keys()) == EXPECTED_KEYS_PY_ONLY, list(d.keys())
    assert "not_applicable" not in d
    assert "not applicable" not in s.render()


# ==========================================================================
# EB8 -- only test-quality changes; sibling verbs and rglob mode untouched
# ==========================================================================
@pytest.mark.parametrize(
    "verb", ["weak-tests", "constant-asserts", "skipped-tests", "unfailable-asserts"]
)
def test_eb8_sibling_verbs_still_report_parse_error_on_ts(tmp_path, verb):
    d = _fixtures(tmp_path)
    rc, out, _ = _tq(tmp_path, d / "a.test.ts", verb=verb)
    assert rc == 1, (verb, out)
    assert "  parse errors: 1" in out.splitlines(), (verb, out)
    assert "not applicable" not in out, (verb, out)


def test_eb8_rglob_mode_never_yields_not_applicable(tmp_path):
    repo = tmp_path / "repo"
    tests = repo / "tests"
    tests.mkdir(parents=True)
    (tests / "test_ok.py").write_text(OK_PY)
    (tests / "a.test.ts").write_text(TS_TEXT)
    (tests / "test_weird.ts").write_text(TS_TEXT)
    cfg = foundry.ProductConfig(
        name="p",
        repo=str(repo),
        allowed_push_repo="p",
        vision=str(tmp_path / "VISION.md"),
        work_root=str(tmp_path / "work"),
    )
    s = foundry.gather_test_quality(cfg)
    assert tuple(getattr(s, "not_applicable", ())) == (), s
    assert "not_applicable" not in s.to_dict()
    assert "not applicable" not in s.render()


# ==========================================================================
# EB9 -- pure core: no filesystem
# ==========================================================================
def test_eb9_pure_core_not_applicable_flips_exit_two_to_zero():
    s = foundry.summarize_test_quality(product="p", not_applicable=("x.ts",), **_nothing_subs())
    assert s.exit_code == 0
    assert s.clean is False
    assert s.verdict == NA_VERDICT
    assert s.not_applicable == ("x.ts",)
    assert "  not applicable: x.ts" in s.render().splitlines()
    assert s.to_dict()["not_applicable"] == ["x.ts"]


def test_eb9_pure_core_without_not_applicable_stays_nothing_to_scan():
    s = foundry.summarize_test_quality(product="p", not_applicable=(), **_nothing_subs())
    assert s.exit_code == 2
    assert s.verdict == "nothing to scan"
    assert s.clean is False
    s2 = foundry.summarize_test_quality(product="p", **_nothing_subs())
    assert s2.exit_code == 2
    assert s2.verdict == "nothing to scan"
