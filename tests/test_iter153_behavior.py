"""Black-box behaviour tests for iter 153 -- the nine `Company*` roll-up
dataclasses stop hand-copying the three derived count properties and inherit ONE
shared module-level mixin, `foundry.CompanyRollupCounts`, with zero observable
behaviour change.

Under test (roadmap item (i)'s data-layer half, after iters 146 and 152 closed
the CLI half): `CompanyStatus`, `CompanyHistory`, `CompanyTiming`,
`CompanyWeakTests`, `CompanyConstantAsserts`, `CompanySkippedTests`,
`CompanyTestQuality`, `CompanyConfigLint`, `CompanyEvents` -- referred to
throughout as THE NINE -- and the new non-dataclass base they share.

THE BLOCKING CRITERION (spec Behaviors 3 + 4 + 5): the 27 local property
definitions must be GONE, not merely correct. In a frozen-dataclass family a
value assertion cannot prove a de-duplication -- a class that re-declares
`n_products` locally still returns the right number -- and the `__mro__` length
pin is one-sided for the same reason. Only `fget` IDENTITY against the mixin
plus ABSENCE from `vars(Cls)` carries it, so
`test_b05_defect_twin_proves_identity_and_vars_checks_are_two_sided` builds a
DEFECT TWIN *in this file* that re-declares one property locally: it must report
the CORRECT value while FAILING both of those two checks, in the same process
where all nine shipped classes pass them.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-153 PM
spec's Expected Behaviors (1-12), the conventions found under `tests/` (esp.
`tests/test_iter146_behavior.py` and `tests/test_iter152_behavior.py`, the
structural mirrors for this family), and the product's OWN OBSERVABLE behaviour
(constructing the public dataclasses, reading their public attributes and
`to_dict()` / `render()` output, and driving the `company-*` CLI verbs on a
synthetic dispatch config). `foundry.py`'s source text was NOT read, no
`inspect.getsource` is used anywhere in this file, and neither the engineer's nor
the reviewer's notes nor any `git diff` was consulted.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import io
import json
import pathlib
import pickle
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

# ---------------------------------------------------------------------------
# THE NINE, in the spec's exact order
# ---------------------------------------------------------------------------
NINE: tuple[str, ...] = (
    "CompanyStatus",
    "CompanyHistory",
    "CompanyTiming",
    "CompanyWeakTests",
    "CompanyConstantAsserts",
    "CompanySkippedTests",
    "CompanyTestQuality",
    "CompanyConfigLint",
    "CompanyEvents",
)

COUNT_NAMES: tuple[str, ...] = ("n_products", "n_disabled", "n_errors")
BASE_FIELDS: tuple[str, ...] = ("dispatch_path", "products", "disabled", "errors")
# the two members that declare one extra trailing field
EXTRA_FIELD: dict[str, str] = {"CompanyTiming": "threshold", "CompanyEvents": "kind_filter"}
EXTRA_KW: dict[str, dict[str, object]] = {
    "CompanyTiming": {"threshold": 1.0},
    "CompanyEvents": {"kind_filter": None},
}


def _mixin() -> type:
    m = getattr(foundry, "CompanyRollupCounts", None)
    assert isinstance(m, type), \
        f"foundry.CompanyRollupCounts must exist and be a class, got {m!r}"
    return m


def _cls(name: str) -> type:
    c = getattr(foundry, name, None)
    assert isinstance(c, type), f"foundry.{name} must exist and be a class, got {c!r}"
    return c


def _make(name: str, products=(), disabled=(), errors=()):
    """Construct one of THE NINE through its PUBLIC constructor."""
    kw: dict[str, object] = {
        "dispatch_path": "x.json",
        "products": products,
        "disabled": disabled,
        "errors": errors,
    }
    kw.update(EXTRA_KW.get(name, {}))
    return _cls(name)(**kw)


def _twins() -> tuple[type, type]:
    """Behavior 5 -- both twins are defined HERE, never in `foundry.py`.

    `GoodTwin` mirrors what the nine shipped classes must look like; `DefectTwin`
    is identical except that it re-declares `n_products` locally, i.e. exactly
    the de-duplication defect Behaviors 3 and 4 have to catch.
    """
    mixin = _mixin()

    @dataclasses.dataclass(frozen=True)
    class GoodTwin(mixin):  # type: ignore[misc, valid-type]
        dispatch_path: str
        products: tuple
        disabled: tuple
        errors: tuple

    @dataclasses.dataclass(frozen=True)
    class DefectTwin(mixin):  # type: ignore[misc, valid-type]
        dispatch_path: str
        products: tuple
        disabled: tuple
        errors: tuple

        @property
        def n_products(self) -> int:   # the DEFECT: a surviving local copy
            return len(self.products)

    return GoodTwin, DefectTwin


# ---------------------------------------------------------------------------
# Behavior 1 -- the mixin exists and is NOT a dataclass
# ---------------------------------------------------------------------------
def test_b01_mixin_exists_and_is_not_a_dataclass():
    mixin = _mixin()
    assert dataclasses.is_dataclass(mixin) is False, \
        "CompanyRollupCounts must NOT be a dataclass -- it declares no fields"
    assert hasattr(mixin, "__dataclass_fields__") is False, \
        "CompanyRollupCounts must not carry __dataclass_fields__"


# ---------------------------------------------------------------------------
# Behavior 2 -- it declares exactly the three properties and no annotated attrs
# ---------------------------------------------------------------------------
def test_b02_mixin_declares_exactly_the_three_properties_and_no_fields():
    mixin = _mixin()
    own = vars(mixin)
    props = {n for n, v in own.items() if isinstance(v, property)}
    assert props == set(COUNT_NAMES), \
        f"CompanyRollupCounts must declare exactly {COUNT_NAMES}, found {sorted(props)}"
    for name in COUNT_NAMES:
        assert isinstance(own[name], property), \
            f"CompanyRollupCounts.{name} must be a property, got {own[name]!r}"
    ann = getattr(mixin, "__annotations__", {}) or {}
    assert list(ann.keys()) == [], \
        f"CompanyRollupCounts must declare no annotated class attribute, found {list(ann)}"


# ---------------------------------------------------------------------------
# Behavior 3 -- 27 fget IDENTITY assertions against the shared body
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", NINE)
def test_b03_each_count_property_is_the_shared_one_by_identity(name):
    mixin = _mixin()
    cls = _cls(name)
    for attr in COUNT_NAMES:
        shipped = getattr(cls, attr, None)
        assert isinstance(shipped, property), \
            f"{name}.{attr} must still be a property, got {shipped!r}"
        assert shipped.fget is getattr(mixin, attr).fget, \
            (f"{name}.{attr} must be THE SHARED body from CompanyRollupCounts "
             f"(fget identity), not a hand-copy")


# ---------------------------------------------------------------------------
# Behavior 4 -- no local copy survives in vars(Cls)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", NINE)
def test_b04_no_local_count_definition_survives(name):
    cls = _cls(name)
    own = vars(cls)
    for attr in COUNT_NAMES:
        assert attr not in own, \
            (f"{name} must NOT declare {attr} locally -- the 27 hand-copies are "
             f"deleted, not shadowing the shared one")


# ---------------------------------------------------------------------------
# Behavior 5 -- two-sided control: the defect twin passes the VALUE check but
# fails the identity and vars() checks
# ---------------------------------------------------------------------------
def test_b05_defect_twin_proves_identity_and_vars_checks_are_two_sided():
    mixin = _mixin()
    good_cls, defect_cls = _twins()
    args = ("x.json", (1, 2, 3), (4,), (5, 6))
    good, defect = good_cls(*args), defect_cls(*args)

    # the defect twin is still VALUE-correct -- which is exactly why a value
    # assertion cannot prove a de-duplication
    assert defect.n_products == 3, "defect twin must report the CORRECT value"
    assert good.n_products == 3, "good twin must report the correct value too"

    # ... yet it FAILS Behavior 3 (identity)
    assert defect_cls.n_products.fget is not mixin.n_products.fget, \
        "defect twin must fail the fget identity check"
    assert good_cls.n_products.fget is mixin.n_products.fget, \
        "good twin must pass the fget identity check"

    # ... and FAILS Behavior 4 (vars absence)
    assert "n_products" in vars(defect_cls), \
        "defect twin must fail the vars() absence check"
    assert "n_products" not in vars(good_cls), \
        "good twin must pass the vars() absence check"

    # the untouched two are still shared on BOTH twins -- so the twin isolates
    # exactly one defect
    for attr in ("n_disabled", "n_errors"):
        for cls in (good_cls, defect_cls):
            assert getattr(cls, attr).fget is getattr(mixin, attr).fget
            assert attr not in vars(cls)


# ---------------------------------------------------------------------------
# Behavior 6 -- declared fields, names and order, unchanged
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", NINE)
def test_b06_declared_fields_names_and_order_unchanged(name):
    cls = _cls(name)
    assert dataclasses.is_dataclass(cls), f"{name} must still be a dataclass"
    expected = BASE_FIELDS + ((EXTRA_FIELD[name],) if name in EXTRA_FIELD else ())
    got = tuple(f.name for f in dataclasses.fields(cls))
    assert got == expected, f"{name} field names/order changed: {got} != {expected}"


# ---------------------------------------------------------------------------
# Behavior 7 -- still frozen, still value-comparing (+ the dataclass helpers)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", NINE)
def test_b07_still_frozen_and_value_comparing(name):
    inst = _make(name, products=(1, 2, 3), disabled=(4,), errors=(5, 6))
    twin = _make(name, products=(1, 2, 3), disabled=(4,), errors=(5, 6))
    assert inst == twin, f"{name} must still compare by value"
    assert not (inst != twin)
    for field in (f.name for f in dataclasses.fields(inst)):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(inst, field, "mutated")
    assert inst == twin, f"{name} must be unchanged after the frozen attempts"


@pytest.mark.parametrize("name", NINE)
def test_b07b_dataclass_helpers_still_work_through_the_shared_base(name):
    """Companion to Behavior 7: the helpers that read `__dataclass_fields__`.

    A base class that leaked a field would corrupt every one of these, and none
    is named in the spec's behaviour list.
    """
    inst = _make(name, products=(1, 2, 3), disabled=(4,), errors=(5, 6))
    field_names = [f.name for f in dataclasses.fields(inst)]

    moved = dataclasses.replace(inst, products=(1, 2))
    assert moved.n_products == 2 and moved.n_disabled == 1 and moved.n_errors == 2, \
        f"{name}: replace() must recompute the derived counts"

    as_dict = dataclasses.asdict(inst)
    assert list(as_dict.keys()) == field_names, \
        f"{name}: asdict() must return exactly the declared fields, got {list(as_dict)}"
    assert len(dataclasses.astuple(inst)) == len(field_names)

    assert copy.deepcopy(inst) == inst, f"{name}: deepcopy must round-trip"
    assert pickle.loads(pickle.dumps(inst)) == inst, f"{name}: pickle must round-trip"


# ---------------------------------------------------------------------------
# Behavior 8 -- the MRO is exactly (Cls, mixin, object)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", NINE)
def test_b08_mro_is_exactly_class_mixin_object(name):
    cls = _cls(name)
    mro = cls.__mro__
    assert len(mro) == 3, \
        f"{name}.__mro__ must be exactly 3 long (class, mixin, object), got {mro}"
    assert mro == (cls, _mixin(), object), f"{name}.__mro__ unexpected: {mro}"


# ---------------------------------------------------------------------------
# Behavior 9 -- the shared body computes the right counts for all nine
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", NINE)
def test_b09_counts_are_correct_through_the_shared_body(name):
    inst = _make(name, products=("a", "b", "c"), disabled=("d",), errors=("e", "f"))
    assert inst.n_products == 3, f"{name}.n_products"
    assert inst.n_disabled == 1, f"{name}.n_disabled"
    assert inst.n_errors == 2, f"{name}.n_errors"
    # and they track the underlying tuples, not a frozen snapshot
    other = _make(name, products=(), disabled=(), errors=())
    assert (other.n_products, other.n_disabled, other.n_errors) == (0, 0, 0)


# ---------------------------------------------------------------------------
# Behavior 10 -- to_dict() and render() intact for all nine
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", NINE)
def test_b10_to_dict_and_render_intact(name):
    inst = _make(name, products=(), disabled=(), errors=())
    d = inst.to_dict()
    assert isinstance(d, dict), f"{name}.to_dict() must return a dict, got {type(d)}"
    for attr in COUNT_NAMES:
        assert attr in d, f"{name}.to_dict() must still emit {attr}, got {sorted(d)}"
        assert d[attr] == 0, f"{name}.to_dict()[{attr!r}] must be 0, got {d[attr]!r}"
    out = inst.render()
    assert isinstance(out, str) and out.strip(), \
        f"{name}.render() must return a non-empty str, got {out!r}"
    # json-serialisable, i.e. the CLI's --json path stays viable
    json.dumps(d, default=str)


# ---------------------------------------------------------------------------
# Behavior 11 -- both modules still import and the CLI help still exits 0
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("module", ["foundry", "dispatcher"])
def test_b11_module_still_imports_in_a_fresh_interpreter(module):
    proc = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=90,
    )
    assert proc.returncode == 0, \
        f"import {module} failed rc={proc.returncode}: {proc.stderr[-800:]}"


def test_b11b_cli_help_still_exits_zero():
    buf = io.StringIO()
    with pytest.raises(SystemExit) as exc:
        with contextlib.redirect_stdout(buf):
            foundry.main(["--help"])
    assert exc.value.code in (0, None), f"--help must exit 0, got {exc.value.code!r}"
    assert buf.getvalue().strip(), "--help must print usage"


# ---------------------------------------------------------------------------
# Behavior 12 -- the nine `company-*` verbs still serialise through the shared
# body: human output non-empty, --json self-consistent (count == len(list))
# ---------------------------------------------------------------------------
def _company_verbs() -> list[str]:
    buf = io.StringIO()
    with contextlib.suppress(SystemExit):
        with contextlib.redirect_stdout(buf):
            foundry.main(["--help"])
    verbs = sorted(set(re.findall(r"company-[a-z0-9-]+", buf.getvalue())))
    assert len(verbs) >= 9, \
        f"expected at least the nine company-* verbs in --help, found {verbs}"
    return verbs


def _write_dispatch(tmp_path, work_items, name="foundry.config.json") -> str:
    p = pathlib.Path(tmp_path) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"work_items": work_items}))
    return str(p)


def _run_cli(argv) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.main(list(argv))
    return rc, buf.getvalue()


def test_b12_company_verbs_still_report_self_consistent_counts(tmp_path):
    dispatch = _write_dispatch(tmp_path, [{"name": "a", "config": "missing-a.json"}])
    checked = 0
    for verb in _company_verbs():
        rc, human = _run_cli([verb, "--config", dispatch])
        assert rc in (0, 1, 2), f"{verb} rc={rc}"
        assert human.strip(), f"{verb} printed nothing on the human path"
        rc_j, raw = _run_cli([verb, "--config", dispatch, "--json"])
        assert rc_j == rc, f"{verb} rc differs between human ({rc}) and --json ({rc_j})"
        payload = json.loads(raw)
        assert isinstance(payload, dict), f"{verb} --json must emit an object"
        for attr, listed in (("n_products", "products"),
                             ("n_disabled", "disabled"),
                             ("n_errors", "errors")):
            if attr in payload and isinstance(payload.get(listed), list):
                assert payload[attr] == len(payload[listed]), \
                    (f"{verb} --json: {attr}={payload[attr]!r} disagrees with "
                     f"len({listed})={len(payload[listed])} -- the shared count "
                     f"body no longer matches its own field")
                checked += 1
    assert checked >= 9, \
        f"expected at least 9 count/list agreements across the family, got {checked}"
