"""Behaviour tests for iter 489 -- the four per-product test-scan Summary value
classes (WeakTestSummary, ConstantAssertSummary, SkippedTestSummary,
UnfailableAssertSummary) fold onto ONE private ClassVar base `_TestScanSummary`
with byte-identical observable output.

Spec: products/_platform/state/iter-489/pm.md, Expected Behaviors 1-11.

ISOLATION: written by the tester stage under its black-box contract -- the
spec, tests/, README and the product's runtime output only; no implementation
source, no diff, no engineer/reviewer notes. Every golden string is a hard-coded
literal (never built from the ClassVars), the CLI run uses a tmp_path product
fixture, and no git history or gitignored state is read.
"""
import dataclasses
import inspect
import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import foundry  # noqa: E402

FIELDS = ["product", "files_scanned", "findings", "parse_errors"]

# name -> (VERB, COUNT_LABEL, DIRTY_VERDICT), literal from the spec's Design.
TRIPLES = {
    "WeakTestSummary": ("weak-tests", "assertion-free tests", "WEAK TESTS FOUND"),
    "ConstantAssertSummary": ("constant-asserts", "constant-assert tests",
                              "CONSTANT ASSERTS FOUND"),
    "SkippedTestSummary": ("skipped-tests", "always-skipped tests",
                           "ALWAYS-SKIPPED TESTS FOUND"),
    "UnfailableAssertSummary": ("unfailable-asserts", "unfailable-assert tests",
                                "UNFAILABLE ASSERTS FOUND"),
}

# Hard-coded golden dirty renders (B5) -- NOT derived from the ClassVars.
GOLDEN_DIRTY = {
    "WeakTestSummary": (
        "foundry weak-tests -- p\n  files scanned: 1\n  assertion-free tests: 1\n"
        "  a.py :: test_x\n  parse errors: 0\nverdict: WEAK TESTS FOUND"),
    "ConstantAssertSummary": (
        "foundry constant-asserts -- p\n  files scanned: 1\n  constant-assert tests: 1\n"
        "  a.py :: test_x\n  parse errors: 0\nverdict: CONSTANT ASSERTS FOUND"),
    "SkippedTestSummary": (
        "foundry skipped-tests -- p\n  files scanned: 1\n  always-skipped tests: 1\n"
        "  a.py :: test_x\n  parse errors: 0\nverdict: ALWAYS-SKIPPED TESTS FOUND"),
    "UnfailableAssertSummary": (
        "foundry unfailable-asserts -- p\n  files scanned: 1\n  unfailable-assert tests: 1\n"
        "  a.py :: test_x\n  parse errors: 0\nverdict: UNFAILABLE ASSERTS FOUND"),
}

NAMES = sorted(TRIPLES)
MOVED = ("render", "to_dict", "verdict", "exit_code", "clean", "total_findings")


def _cls(name):
    return getattr(foundry, name)


# B1 -------------------------------------------------------------------------
@pytest.mark.parametrize("name", NAMES)
def test_b1_importable_dataclass_with_exact_fields(name):
    C = _cls(name)
    assert dataclasses.is_dataclass(C)
    assert [f.name for f in dataclasses.fields(C)] == FIELDS


# B2 -------------------------------------------------------------------------
@pytest.mark.parametrize("name", NAMES)
def test_b2_subclass_of_shared_base(name):
    base = foundry._TestScanSummary
    assert isinstance(base, type)
    assert issubclass(_cls(name), base)
    assert _cls(name) is not base


def test_b2_all_four_share_one_base_object():
    bases = {c for n in NAMES for c in _cls(n).__mro__
             if c.__name__ == "_TestScanSummary"}
    assert bases == {foundry._TestScanSummary}


# B3 -------------------------------------------------------------------------
@pytest.mark.parametrize("name", NAMES)
def test_b3_no_moved_method_in_own_vars(name):
    own = vars(_cls(name))
    present = [m for m in MOVED if m in own]
    assert present == [], f"{name} still defines {present} itself"


@pytest.mark.parametrize("name", NAMES)
def test_b3_class_source_is_thin(name):
    n = len(inspect.getsource(_cls(name)).splitlines())
    assert n <= 40, f"{name} source is {n} lines (> 40)"


# B4 -------------------------------------------------------------------------
@pytest.mark.parametrize("name", NAMES)
def test_b4_classvar_triple_and_not_fields(name):
    C = _cls(name)
    verb, label, dirty = TRIPLES[name]
    assert (C.VERB, C.COUNT_LABEL, C.DIRTY_VERDICT) == (verb, label, dirty)
    field_names = {f.name for f in dataclasses.fields(C)}
    for attr in ("VERB", "COUNT_LABEL", "DIRTY_VERDICT"):
        assert attr not in field_names
    # Instances read the same class strings.
    inst = C("p", 1, (), ())
    assert inst.VERB == verb


# B5 -------------------------------------------------------------------------
@pytest.mark.parametrize("name", NAMES)
def test_b5_golden_dirty_render(name):
    C = _cls(name)
    s = C(product="p", files_scanned=1, findings=(("a.py", "test_x"),), parse_errors=())
    assert s.render() == GOLDEN_DIRTY[name]
    assert s.exit_code == 1
    assert s.clean is False
    assert s.total_findings == 1
    assert s.verdict == TRIPLES[name][2]


# B6 -------------------------------------------------------------------------
@pytest.mark.parametrize("name", NAMES)
def test_b6_parse_error_only_is_dirty(name):
    C = _cls(name)
    s = C("p", 2, (), (("b.py", "boom"),))
    lines = s.render().splitlines()
    idx = lines.index("  parse errors: 1")
    assert lines[idx + 1] == "  b.py: boom"
    assert "  assertion-free tests: 0" in lines or any(
        l.endswith(": 0") for l in lines[1:idx])
    assert s.exit_code == 1
    assert s.clean is False
    assert s.verdict == TRIPLES[name][2]
    assert lines[-1] == "verdict: " + TRIPLES[name][2]


# B7 -------------------------------------------------------------------------
@pytest.mark.parametrize("name", NAMES)
def test_b7_clean_and_empty(name):
    C = _cls(name)
    clean = C("p", 3, (), ())
    assert clean.exit_code == 0
    assert clean.clean is True
    assert clean.verdict == "clean"
    assert "::" not in clean.render()
    assert clean.render().splitlines()[-1] == "verdict: clean"
    empty = C("p", 0, (), ())
    assert empty.exit_code == 2
    assert empty.clean is False
    assert empty.verdict == "nothing to scan"


# B8 -------------------------------------------------------------------------
@pytest.mark.parametrize("name", NAMES)
def test_b8_to_dict_contract_and_json_roundtrip(name):
    C = _cls(name)
    s = C("p", 4, (("a.py", "test_x"), ("c.py", "test_y")), (("b.py", "boom"),))
    d = s.to_dict()
    assert list(d) == ["product", "files_scanned", "total_findings", "clean",
                       "exit_code", "verdict", "findings", "parse_errors"]
    assert d["product"] == "p"
    assert d["files_scanned"] == 4
    assert d["total_findings"] == 2
    assert d["clean"] is False
    assert d["exit_code"] == 1
    assert d["verdict"] == TRIPLES[name][2]
    assert d["findings"] == [{"file": "a.py", "test": "test_x"},
                             {"file": "c.py", "test": "test_y"}]
    assert d["parse_errors"] == [{"file": "b.py", "message": "boom"}]
    assert json.loads(json.dumps(d)) == d
    clean = C("p", 3, (), ()).to_dict()
    assert (clean["clean"], clean["exit_code"], clean["verdict"]) == (True, 0, "clean")
    assert clean["findings"] == [] and clean["parse_errors"] == []


# B9 -------------------------------------------------------------------------
@pytest.mark.parametrize("name", NAMES)
def test_b9_frozen(name):
    s = _cls(name)("p", 1, (), ())
    for field in FIELDS:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(s, field, None)


@pytest.mark.parametrize("name", NAMES)
def test_b9_equality_and_hash(name):
    C = _cls(name)
    a = C("p", 1, (("a.py", "t"),), ())
    b = C("p", 1, (("a.py", "t"),), ())
    assert a == b
    assert hash(a) == hash(b)
    assert a != C("q", 1, (("a.py", "t"),), ())


def test_b9_cross_class_not_equal():
    w = foundry.WeakTestSummary("p", 1, (), ())
    s = foundry.SkippedTestSummary("p", 1, (), ())
    assert w != s
    assert not (w == s)


@pytest.mark.parametrize("name", NAMES)
def test_b9_repr_names_the_class(name):
    r = repr(_cls(name)("p", 1, (), ()))
    assert r.startswith(name + "(product='p'"), r


# B10 ------------------------------------------------------------------------
def _write_cfg(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_demo.py").write_text(
        "def test_nothing_checked():\n    x = 1 + 1\n")
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(data))
    return cfg


def _run(args):
    return subprocess.run([sys.executable, str(REPO / "foundry.py"), *args],
                          capture_output=True, text=True, cwd=str(REPO))


def test_b10_weak_tests_cli_text(tmp_path):
    cfg = _write_cfg(tmp_path)
    p = _run(["weak-tests", "--config", str(cfg)])
    assert p.returncode == 1, p.stdout + p.stderr
    assert "assertion-free tests: 1" in p.stdout
    assert "verdict: WEAK TESTS FOUND" in p.stdout
    assert "test_nothing_checked" in p.stdout


def test_b10_weak_tests_cli_json(tmp_path):
    cfg = _write_cfg(tmp_path)
    p = _run(["weak-tests", "--config", str(cfg), "--json"])
    assert p.returncode == 1, p.stdout + p.stderr
    d = json.loads(p.stdout)
    assert d["exit_code"] == 1
    assert d["verdict"] == "WEAK TESTS FOUND"
    assert d["total_findings"] == 1


# B11 ------------------------------------------------------------------------
def test_b11_import_foundry_and_dispatcher():
    p = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       capture_output=True, text=True, cwd=str(REPO))
    assert p.returncode == 0, p.stderr
