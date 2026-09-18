"""Iteration 374 -- BLACK-BOX behavior tests for the COMPANY ROLL-UP CONSTRUCTOR COLLAPSE.

Spec under test: products/_platform/state/iter-374/pm.md -- "One shared, pure packer
builds every `Company*` roll-up; the 9 public `summarize_company*` names survive as thin
delegating wrappers."  Expected Behaviors, numbered as in the spec:

  1. Each roll-up constructor returns the same frozen `Company*` type with the same field
     values as before: the fields are exactly the parameter names and every value is
     passed THROUGH by identity (no copy, no reorder, no swap).
  2. Keyword-only is preserved: a positional argument still raises `TypeError`, on every
     member, even when every required keyword is also supplied.
  3. The two extra-kwarg members keep their 5th field (`threshold` on
     `summarize_company_timing`, `kind_filter` on `summarize_company_events`): required,
     keyword-only, forwarded to the field -- AND the other members still REFUSE those two
     keywords, so the shared packer's `**extra` channel leaks no field sideways.
  4. Exactly ONE module-level function performs the packing: over the LIVE module the
     family shares exactly one module-level callee, patching that one callee intercepts
     EVERY member, and the census is proved non-vacuous by a positive control that plants
     a member which packs inline.
  5. END-TO-END (not in the spec's list; the observable surface of Behaviors 1+3): all ten
     `company-*` CLI verbs still emit a parseable `--json` roll-up carrying the roll-up
     field names, and the two extra-field verbs carry their 5th field.

MEMBERSHIP IS DISCOVERED, NOT LISTED.  The spec says "the 9 `summarize_company*`", but the
family is defined by its RETURN TYPE, and one member (`summarize_stops` -> `CompanyStops`)
is invisible to a `summarize_company*` prefix scan.  Every census below walks the module
for functions whose return annotation names a `Company*` type, so the tenth member cannot
fall out of scope; Behavior 4 is only TRUE if it is included, and the prefix-scan blind
spot is pinned explicitly.

ISOLATION CONTRACT (HONORED): every assertion was derived ONLY from the iter-374 PM spec,
the pre-existing conventions under `tests/`, and the product's OWN observable behavior --
importing the module and CALLING its public names, plus running `foundry.py --help` and
the `company-*` verbs.  The implementation SOURCE of `foundry.py` / `dispatcher.py` was
NOT read by this author, nor the engineer's notes, the reviewer's notes,
`IMPLEMENTATION.patch`, or any `git diff`.  Behavior 4's shared-callee census is a MACHINE
scan (`__code__.co_names` inside the test), the convention iterations 336/361/373 already
use for module-level structural invariants.

FRESH-CLONE SAFE / OFFLINE: no fixture depends on gitignored state.  The only ambient
files touched are TRACKED (`foundry.py`, `foundry.config.json`) and are reached through
`pathlib.Path(__file__).parents[1]`, never an absolute machine path.  Behavior 5 tolerates
any of the verb's three documented exit codes, so a clone with no run history still
passes.  No network, no git, no clock.
"""
from __future__ import annotations

import dataclasses
import inspect
import json
import pathlib
import subprocess
import sys
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import foundry  # noqa: E402

BASE_FIELDS = ("dispatch_path", "products", "disabled", "errors")
# member -> (5th field name, a value for it)
EXTRA_FIELD = {
    "summarize_company_timing": ("threshold", 12.5),
    "summarize_company_events": ("kind_filter", "ship"),
}
# every member, discovered by return type, must be reachable as a CLI verb
FAMILY_FLOOR = 10


# ==========================================================================
# discovery helpers (also exercised by Behavior 4's positive control)
# ==========================================================================
def rollup_family(namespace: dict) -> dict:
    """Module-level functions whose return annotation names a `Company*` roll-up."""
    found = {}
    for name, value in namespace.items():
        if not isinstance(value, types.FunctionType):
            continue
        try:
            ret = inspect.signature(value).return_annotation
        except (TypeError, ValueError):  # pragma: no cover - defensive
            continue
        if isinstance(ret, str) and ret.startswith("Company"):
            found[name] = value
    return found


def shared_callees(namespace: dict, family: dict) -> set:
    """Module-level function names called by EVERY member of `family`."""
    module_functions = {
        name for name, value in namespace.items() if isinstance(value, types.FunctionType)
    }
    per_member = [
        set(fn.__code__.co_names) & module_functions - {name}
        for name, fn in family.items()
    ]
    if not per_member:
        return set()
    return set.intersection(*per_member)


def kwargs_for(name: str, fn) -> dict:
    """Distinct sentinel value per parameter, so a swap or a drop cannot pass."""
    values = {
        "dispatch_path": f"products/_platform/state/iter-374/{name}.json",
        "products": (object(),),
        "disabled": ("disabled-product",),
        "errors": (("broken-product", "gather failed"),),
    }
    if name in EXTRA_FIELD:
        field, value = EXTRA_FIELD[name]
        values[field] = value
    return {p: values[p] for p in inspect.signature(fn).parameters}


LIVE_FAMILY = rollup_family(vars(foundry))
FAMILY_NAMES = sorted(LIVE_FAMILY)


def test_family_discovery_found_the_whole_family() -> None:
    """Guard the population every other census below is scoped to."""
    assert len(FAMILY_NAMES) >= FAMILY_FLOOR, FAMILY_NAMES
    prefixed = [n for n in FAMILY_NAMES if n.startswith("summarize_company")]
    assert len(prefixed) >= 9, prefixed
    # the member a `summarize_company*` prefix scan MISSES -- in scope on purpose
    assert "summarize_stops" in FAMILY_NAMES, FAMILY_NAMES
    assert "summarize_stops" not in prefixed


# ==========================================================================
# Behavior 1 -- same frozen type, same field values, passed through by identity
# ==========================================================================
def normalized(field: str, value: object) -> object:
    """The roll-up's OBSERVED normalization: sequences become tuples, and the
    `errors` pairs become tuples of tuples.  Measured identically on every member."""
    if field == "errors":
        return tuple(tuple(pair) for pair in value)  # type: ignore[union-attr]
    if field in ("products", "disabled"):
        return tuple(value)  # type: ignore[call-overload]
    return value


@pytest.mark.parametrize("name", FAMILY_NAMES)
def test_b1_member_returns_its_frozen_rollup_with_the_same_field_values(name: str) -> None:
    fn = LIVE_FAMILY[name]
    expected_type = getattr(foundry, inspect.signature(fn).return_annotation)
    payload = kwargs_for(name, fn)

    result = fn(**payload)

    assert type(result) is expected_type, f"{name} must still return {expected_type!r}"
    assert dataclasses.is_dataclass(result)
    assert type(result).__dataclass_params__.frozen, f"{expected_type!r} must be frozen"
    assert tuple(f.name for f in dataclasses.fields(result)) == tuple(payload), (
        f"{name}: fields must be exactly its parameter names, in order"
    )
    for field, value in payload.items():
        assert getattr(result, field) == normalized(field, value), (
            f"{name}.{field} lost its value"
        )
    # the products payload is carried, never copied
    assert result.products is payload["products"], f"{name} copied its products payload"
    assert result.dispatch_path is payload["dispatch_path"]


@pytest.mark.parametrize("name", FAMILY_NAMES)
def test_b1_sequence_fields_are_normalized_to_tuples_on_every_member(name: str) -> None:
    """One shared packer means ONE normalization contract, identical across the family."""
    fn = LIVE_FAMILY[name]
    payload = kwargs_for(name, fn)
    payload["products"] = [object(), object()]          # list in
    payload["disabled"] = ["one", "two"]
    payload["errors"] = [["broken-product", "gather failed"]]

    result = fn(**payload)

    assert isinstance(result.products, tuple) and len(result.products) == 2
    assert result.disabled == ("one", "two")
    assert result.errors == (("broken-product", "gather failed"),)
    assert all(isinstance(pair, tuple) for pair in result.errors)


@pytest.mark.parametrize("name", FAMILY_NAMES)
def test_b1_result_is_immutable(name: str) -> None:
    fn = LIVE_FAMILY[name]
    result = fn(**kwargs_for(name, fn))
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.dispatch_path = "mutated"


def test_b1_the_four_shared_fields_are_common_to_every_member() -> None:
    for name, fn in LIVE_FAMILY.items():
        params = tuple(inspect.signature(fn).parameters)
        assert params[:4] == BASE_FIELDS, f"{name} has {params!r}"


# ==========================================================================
# Behavior 2 -- keyword-only preserved: a positional argument still raises TypeError
# ==========================================================================
@pytest.mark.parametrize("name", FAMILY_NAMES)
def test_b2_every_parameter_is_keyword_only(name: str) -> None:
    params = inspect.signature(LIVE_FAMILY[name]).parameters
    assert params, name
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values()), (
        f"{name} must expose only keyword-only parameters, got "
        f"{[(p.name, str(p.kind)) for p in params.values()]}"
    )


@pytest.mark.parametrize("name", FAMILY_NAMES)
def test_b2_one_extra_positional_is_refused_even_with_all_keywords(name: str) -> None:
    fn = LIVE_FAMILY[name]
    payload = kwargs_for(name, fn)
    fn(**payload)  # the same call succeeds by keyword
    with pytest.raises(TypeError):
        fn("positional", **payload)


@pytest.mark.parametrize("name", FAMILY_NAMES)
def test_b2_all_arguments_positional_is_refused(name: str) -> None:
    fn = LIVE_FAMILY[name]
    with pytest.raises(TypeError):
        fn(*kwargs_for(name, fn).values())


# ==========================================================================
# Behavior 3 -- the two extra-kwarg members keep their 5th field, and only they do
# ==========================================================================
@pytest.mark.parametrize("name,field,value", [(n, f, v) for n, (f, v) in EXTRA_FIELD.items()])
def test_b3_extra_field_survives_and_is_required(name: str, field: str, value: object) -> None:
    fn = LIVE_FAMILY[name]
    params = inspect.signature(fn).parameters
    assert field in params, f"{name} lost its 5th parameter {field!r}"
    assert params[field].kind is inspect.Parameter.KEYWORD_ONLY
    assert params[field].default is inspect.Parameter.empty, (
        f"{name}.{field} must stay REQUIRED, not acquire a default"
    )

    payload = kwargs_for(name, fn)
    result = fn(**payload)
    assert getattr(result, field) == value
    assert field in {f.name for f in dataclasses.fields(result)}

    payload.pop(field)
    with pytest.raises(TypeError):
        fn(**payload)


@pytest.mark.parametrize("name", FAMILY_NAMES)
def test_b3_no_other_member_accepts_the_extra_keywords(name: str) -> None:
    fn = LIVE_FAMILY[name]
    mine = EXTRA_FIELD.get(name, (None, None))[0]
    for field, value in EXTRA_FIELD.values():
        if field == mine:
            continue
        payload = kwargs_for(name, fn)
        payload[field] = value
        with pytest.raises(TypeError):
            fn(**payload)


@pytest.mark.parametrize("name", FAMILY_NAMES)
def test_b3_an_unknown_keyword_is_still_refused(name: str) -> None:
    fn = LIVE_FAMILY[name]
    payload = kwargs_for(name, fn)
    payload["bogus_field"] = 1
    with pytest.raises(TypeError):
        fn(**payload)


# ==========================================================================
# Behavior 4 -- EXACTLY ONE module-level function performs the packing
# ==========================================================================
def test_b4_the_family_shares_exactly_one_module_level_callee() -> None:
    shared = shared_callees(vars(foundry), LIVE_FAMILY)
    assert len(shared) == 1, (
        f"the {len(FAMILY_NAMES)} roll-up constructors must share exactly ONE "
        f"module-level packer, found {sorted(shared)!r}"
    )
    packer_name = shared.pop()
    packer = getattr(foundry, packer_name)
    assert isinstance(packer, types.FunctionType)


def test_b4_patching_that_one_callee_intercepts_every_member(monkeypatch) -> None:
    shared = shared_callees(vars(foundry), LIVE_FAMILY)
    assert len(shared) == 1, sorted(shared)
    packer_name = shared.pop()

    seen: list[tuple] = []
    sentinel = object()

    def recorder(*args: object, **kwargs: object) -> object:
        seen.append((args, tuple(sorted(kwargs))))
        return sentinel

    monkeypatch.setattr(foundry, packer_name, recorder)
    for name in FAMILY_NAMES:
        fn = LIVE_FAMILY[name]
        assert fn(**kwargs_for(name, fn)) is sentinel, (
            f"{name} does not pack through {packer_name} (reached by bare module name)"
        )
    assert len(seen) == len(FAMILY_NAMES)


def _synthetic_namespace(beta_body: str) -> dict:
    """Two roll-up-shaped functions; `beta_body` decides whether beta shares the packer.

    The return annotations are set EXPLICITLY: under `from __future__ import
    annotations` a quoted annotation would compile to the literal `"'CompanyAlpha'"`,
    so the control must not depend on how the annotation was spelled."""
    namespace: dict = {}
    source = (
        "def pack(ctor, **kw):\n"
        "    return ctor(**kw)\n"
        "def make_alpha():\n"
        "    return pack(dict)\n"
        "def make_beta():\n"
        f"    return {beta_body}\n"
    )
    exec(compile(source, "<census-control>", "exec"), namespace)
    namespace["make_alpha"].__annotations__ = {"return": "CompanyAlpha"}
    namespace["make_beta"].__annotations__ = {"return": "CompanyBeta"}
    return namespace


def test_b4_positive_control_an_inline_packer_breaks_the_census() -> None:
    """The census must be able to RED: plant a member that packs INLINE."""
    shared = _synthetic_namespace("pack(dict)")
    family = rollup_family(shared)
    assert sorted(family) == ["make_alpha", "make_beta"], sorted(family)
    assert shared_callees(shared, family) == {"pack"}, (
        "control: the census must SEE the shared packer in the shared case"
    )

    inline = _synthetic_namespace("dict()")
    family = rollup_family(inline)
    assert sorted(family) == ["make_alpha", "make_beta"], sorted(family)
    assert shared_callees(inline, family) == set(), (
        "the census would be VACUOUS: it failed to notice an inline packer"
    )


def test_b4_positive_control_a_second_shared_helper_also_reds() -> None:
    """`len(shared) == 1` must also red on the OPPOSITE failure: two shared callees."""
    namespace: dict = {}
    source = (
        "def pack(ctor, **kw):\n"
        "    return ctor(**kw)\n"
        "def also(x):\n"
        "    return x\n"
        "def make_alpha():\n"
        "    return also(pack(dict))\n"
        "def make_beta():\n"
        "    return also(pack(dict))\n"
    )
    exec(compile(source, "<census-control-two>", "exec"), namespace)
    namespace["make_alpha"].__annotations__ = {"return": "CompanyAlpha"}
    namespace["make_beta"].__annotations__ = {"return": "CompanyBeta"}
    family = rollup_family(namespace)
    assert shared_callees(namespace, family) == {"pack", "also"}


# ==========================================================================
# Behavior 5 -- END-TO-END: the company-* verbs still emit a JSON roll-up
# ==========================================================================
# verb -> its 5th JSON field, if any.  `--json` renames `dispatch_path` to
# `dispatch_config`; the other three roll-up fields keep their names.
CLI_VERBS = {
    "company-status": None,
    "company-stops": None,
    "company-history": None,
    "company-timing": "threshold",
    "company-weak-tests": None,
    "company-events": "kind_filter",
    "company-constant-asserts": None,
    "company-skipped-tests": None,
    "company-test-quality": None,
    "company-lint-config": None,
}
JSON_ROLLUP_FIELDS = ("dispatch_config", "products", "disabled", "errors")
# One subprocess per verb costs ~2s, so the end-to-end leg drives the three verbs
# that cover every field shape: the plain roll-up and BOTH 5th fields.
SUBPROCESS_VERBS = ("company-status", "company-timing", "company-events")


def run_foundry(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "foundry.py"), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_b5_every_family_member_still_has_a_cli_verb() -> None:
    """Cross-check the constructor family against the live CLI surface."""
    help_text = run_foundry("--help").stdout
    assert len(CLI_VERBS) >= FAMILY_FLOOR, sorted(CLI_VERBS)
    missing = sorted(v for v in CLI_VERBS if v not in help_text)
    assert missing == [], f"verbs vanished from the CLI: {missing}"


@pytest.mark.parametrize("verb", SUBPROCESS_VERBS)
def test_b5_company_verb_emits_a_json_rollup(verb: str) -> None:
    proc = run_foundry(verb, "--json")
    assert proc.returncode in (0, 1, 2), (
        f"{verb} exited {proc.returncode}\nSTDERR: {proc.stderr[-800:]}"
    )
    doc = json.loads(proc.stdout)
    assert isinstance(doc, dict)
    for field in JSON_ROLLUP_FIELDS:
        assert field in doc, f"{verb} --json lost {field!r}: {sorted(doc)!r}"
    extra_field = CLI_VERBS[verb]
    if extra_field is not None:
        assert extra_field in doc, f"{verb} --json lost {extra_field!r}: {sorted(doc)!r}"
