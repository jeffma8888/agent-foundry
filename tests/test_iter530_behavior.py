"""iter 530 -- the three scanner Company* roll-ups share ONE module-level to_dict.

Spec (products/_platform/state/iter-530/pm.md): `CompanyWeakTests`,
`CompanyConstantAsserts` and `CompanySkippedTests` each assign
`to_dict = _company_scan_to_dict` in their class body instead of carrying an
AST-identical hand-copy, and their JSON output (in-process and via the
`company-* --json` CLI) stays byte-identical to the HEAD copy of foundry.py.

Black-box: drives the public classes / `foundry.main`, compares against a
HEAD copy of foundry.py loaded from `git show HEAD:foundry.py` into tmp_path.
The only AST read is the spec's own behavior 8 (no `def to_dict` in the three
class bodies), which is a structural acceptance criterion.
"""
import ast
import contextlib
import importlib.util
import inspect
import io
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import foundry  # noqa: E402

TRIO = ("CompanyWeakTests", "CompanyConstantAsserts", "CompanySkippedTests")
SUMMARY = {
    "CompanyWeakTests": "WeakTestSummary",
    "CompanyConstantAsserts": "ConstantAssertSummary",
    "CompanySkippedTests": "SkippedTestSummary",
}
GATHER = {
    "CompanyWeakTests": "gather_weak_tests",
    "CompanyConstantAsserts": "gather_constant_asserts",
    "CompanySkippedTests": "gather_skipped_tests",
}
VERB = {
    "CompanyWeakTests": "company-weak-tests",
    "CompanyConstantAsserts": "company-constant-asserts",
    "CompanySkippedTests": "company-skipped-tests",
}
KEYS = ["dispatch_config", "products", "disabled", "errors", "n_products",
        "n_disabled", "n_errors", "n_flagged", "files_scanned",
        "total_findings", "total_parse_errors", "exit_code", "verdict"]
OTHER_ROLLUPS = ("CompanyTestQuality",)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
_HEAD_CACHE = {}


def _head_module(tmp_path_factory):
    """Load `git show HEAD:foundry.py` as a separate module (cached)."""
    if "mod" in _HEAD_CACHE:
        return _HEAD_CACHE["mod"]
    if shutil.which("git") is None:
        pytest.skip("git unavailable: cannot load the HEAD copy of foundry.py")
    r = subprocess.run(["git", "-C", str(ROOT), "show", "HEAD:foundry.py"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"git show HEAD:foundry.py failed: {r.stderr.strip()}")
    d = tmp_path_factory.mktemp("head_foundry")
    p = d / "foundry_head_iter530.py"
    p.write_text(r.stdout)
    name = "foundry_head_iter530"
    spec = importlib.util.spec_from_file_location(name, str(p))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses resolve their module via sys.modules
    spec.loader.exec_module(mod)
    _HEAD_CACHE["mod"] = mod
    return mod


def _populated(mod, cls_name):
    S = getattr(mod, SUMMARY[cls_name])
    C = getattr(mod, cls_name)
    p1 = S("alpha", 4, (("tests/test_a.py", "test_one"),),
           (("tests/test_bad.py", "SyntaxError: invalid syntax"),))
    p2 = S("beta", 2, (), ())
    return C("/d/foundry.config.json", (p1, p2), ("gamma",),
             (("delta", "config not found"),))


def _empty(mod, cls_name):
    C = getattr(mod, cls_name)
    return C("/d/foundry.config.json", (), (), ())


def _run_main(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = mod.main(argv)
    return rc, out.getvalue(), err.getvalue()


# ==========================================================================
# Behavior 1 -- module-level function, one positional parameter
# ==========================================================================
def test_b1_module_level_fn_one_positional_param():
    fn = getattr(foundry, "_company_scan_to_dict", None)
    assert fn is not None, "foundry._company_scan_to_dict must exist"
    assert callable(fn)
    assert "." not in fn.__qualname__, \
        f"must be module-level, got qualname {fn.__qualname__!r}"
    params = list(inspect.signature(fn).parameters.values())
    assert len(params) == 1, f"exactly one parameter expected, got {params}"
    assert params[0].kind in (inspect.Parameter.POSITIONAL_ONLY,
                              inspect.Parameter.POSITIONAL_OR_KEYWORD)


# ==========================================================================
# Behavior 2 -- each class assigns the SAME object in its own body
# ==========================================================================
@pytest.mark.parametrize("cls_name", TRIO)
def test_b2_to_dict_is_shared_fn_assigned_in_body(cls_name):
    fn = getattr(foundry, "_company_scan_to_dict", None)
    assert fn is not None, "foundry._company_scan_to_dict must exist"
    cls = getattr(foundry, cls_name)
    assert cls.to_dict is fn, f"{cls_name}.to_dict must be _company_scan_to_dict"
    assert "to_dict" in vars(cls), f"{cls_name} must assign to_dict in its own body"
    assert vars(cls)["to_dict"] is fn


# ==========================================================================
# Behavior 3 -- no base-class / mixin change
# ==========================================================================
@pytest.mark.parametrize("cls_name", TRIO)
def test_b3_mro_unchanged_and_counts_base_untouched(cls_name):
    assert "to_dict" not in vars(foundry.CompanyRollupCounts), \
        "CompanyRollupCounts must NOT gain a to_dict"
    cls = getattr(foundry, cls_name)
    assert len(cls.__mro__) == 3, f"{cls_name}.__mro__ changed: {cls.__mro__}"


# ==========================================================================
# Behavior 4 -- GOLDEN: byte-identical json.dumps vs the HEAD copy
# ==========================================================================
@pytest.mark.parametrize("cls_name", TRIO)
@pytest.mark.parametrize("fixture", ["populated", "empty"])
def test_b4_golden_json_byte_identical_to_head(cls_name, fixture, tmp_path_factory):
    head = _head_module(tmp_path_factory)
    build = _populated if fixture == "populated" else _empty
    new = json.dumps(build(foundry, cls_name).to_dict())
    old = json.dumps(build(head, cls_name).to_dict())
    assert new == old, f"{cls_name} {fixture}: JSON drifted from HEAD\nnew={new}\nold={old}"


def test_b4_populated_fixture_is_not_vacuous():
    inst = _populated(foundry, "CompanyWeakTests")
    d = inst.to_dict()
    assert d["n_products"] == 2 and d["n_disabled"] == 1 and d["n_errors"] == 1
    assert d["total_findings"] >= 1 and d["total_parse_errors"] >= 1


# ==========================================================================
# Behavior 5 -- exact key order, per-product payloads, JSON round-trip
# ==========================================================================
@pytest.mark.parametrize("cls_name", TRIO)
@pytest.mark.parametrize("fixture", ["populated", "empty"])
def test_b5_keys_order_products_roundtrip(cls_name, fixture):
    build = _populated if fixture == "populated" else _empty
    inst = build(foundry, cls_name)
    d = inst.to_dict()
    assert list(d) == KEYS, f"{cls_name}: key order {list(d)}"
    assert len(d["products"]) == len(inst.products)
    for i, p in enumerate(inst.products):
        assert d["products"][i] == p.to_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["dispatch_config"] == "/d/foundry.config.json"
    assert d["exit_code"] == inst.exit_code


# ==========================================================================
# Behavior 6 -- CLI --json stdout + exit code identical to HEAD
# ==========================================================================
def _patch_seams(monkeypatch, mod, cls_name, mode):
    S = getattr(mod, SUMMARY[cls_name])

    class _Cfg:
        def __init__(self, path):
            self._path = path

    def fake_load(path):
        if "missing" in str(path):
            raise FileNotFoundError(f"no such config: {path}")
        return _Cfg(str(path))

    def fake_gather(cfg, files=None):
        if mode == "clean" or "beta" in cfg._path:
            return S("beta" if "beta" in cfg._path else "alpha", 3, (), ())
        return S("alpha", 4, (("tests/test_a.py", "test_one"),),
                 (("tests/test_bad.py", "SyntaxError: x"),))

    monkeypatch.setattr(mod, "load_config", fake_load)
    monkeypatch.setattr(mod, GATHER[cls_name], fake_gather)


def _write_dispatch(tmp_path, with_error):
    items = [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
        {"name": "gamma", "config": str(tmp_path / "gamma.json"), "enabled": False},
    ]
    if with_error:
        items.append({"name": "delta", "config": str(tmp_path / "missing.json"),
                      "enabled": True})
    p = tmp_path / "foundry.config.json"
    p.write_text(json.dumps({"work_items": items}))
    return p


@pytest.mark.parametrize("cls_name", TRIO)
@pytest.mark.parametrize("mode", ["flagged", "clean"])
def test_b6_cli_json_identical_to_head(cls_name, mode, tmp_path, tmp_path_factory,
                                       monkeypatch):
    head = _head_module(tmp_path_factory)
    disp = _write_dispatch(tmp_path, with_error=(mode == "flagged"))
    argv = [VERB[cls_name], "--config", str(disp), "--json"]
    _patch_seams(monkeypatch, foundry, cls_name, mode)
    _patch_seams(monkeypatch, head, cls_name, mode)
    rc_new, out_new, _ = _run_main(foundry, argv)
    rc_old, out_old, _ = _run_main(head, argv)
    assert out_new == out_old, f"{cls_name} --json stdout drifted from HEAD"
    assert rc_new == rc_old
    doc = json.loads(out_new)
    assert list(doc) == KEYS
    assert doc["n_products"] == 2 and doc["n_disabled"] == 1
    if mode == "flagged":
        assert rc_new == 1 and doc["n_errors"] == 1 and doc["total_findings"] == 1
    else:
        assert rc_new == 0 and doc["n_errors"] == 0 and doc["total_findings"] == 0


# ==========================================================================
# Behavior 7 -- docstring names all three per-product payload types
# ==========================================================================
def test_b7_docstring_names_all_three_summaries():
    fn = getattr(foundry, "_company_scan_to_dict", None)
    assert fn is not None, "foundry._company_scan_to_dict must exist"
    doc = fn.__doc__ or ""
    assert doc.strip(), "docstring must be non-empty"
    for name in SUMMARY.values():
        assert name in doc, f"docstring must name {name}"


# ==========================================================================
# Behavior 8 -- no `def to_dict` left in the three class bodies
# ==========================================================================
def _classdefs():
    tree = ast.parse((ROOT / "foundry.py").read_text())
    return {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}


def test_b8_no_to_dict_def_in_trio_bodies():
    classes = _classdefs()
    count = 0
    for name in TRIO:
        assert name in classes, f"{name} must still be a top-level class"
        count += sum(1 for n in classes[name].body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name == "to_dict")
    assert count == 0, f"{count} `def to_dict` remain in the three class bodies"


@pytest.mark.parametrize("cls_name", OTHER_ROLLUPS)
def test_b8_other_rollups_keep_own_to_dict(cls_name):
    classes = _classdefs()
    assert cls_name in classes
    defs = [n for n in classes[cls_name].body
            if isinstance(n, ast.FunctionDef) and n.name == "to_dict"]
    assert len(defs) == 1, f"{cls_name} must keep its own def to_dict"
    assert getattr(foundry, cls_name).to_dict is not foundry._company_scan_to_dict
