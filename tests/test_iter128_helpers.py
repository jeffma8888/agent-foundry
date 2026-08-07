"""ENGINEER-owned unit tests for iter 128 -- the pure helpers behind the
fail-closed unknown-key guard at product-config load time.

Scope split (mandated by the iter-128 spec's "Required test-file split
(anti-stranding)" section, which exists because iterations 125-127 each had a
tester stage killed at the ~600s cap and iteration 125 threw away a green
implementation because no test file existed yet): this file covers the spec's
Expected Behaviors 1-3 ONLY -- `unknown_config_keys`, its `_`-prefixed comment
exemption, and `suggest_config_key`. The `load_config` CALL SITE (Behaviors 4-10:
the raise, the message content, the no-side-effect ordering, the live fleet and
the regressions) belongs to the isolated tester in `tests/test_iter128_behavior.py`.
Keeping helper coverage HERE means a lost tester stage can no longer leave the new
symbols completely untested.

Fully offline and deterministic: pure function calls only. No config file is read,
no subprocess, no git, no network, no clock. The import root is derived at RUNTIME
from `__file__`, so no machine-specific path is ever committed.
"""
import dataclasses
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402

# A minimal dict of REAL field names, used as the "nothing unknown here" control.
KNOWN_MINIMAL = {"name": "demo", "repo": "/nowhere/repo", "allowed_push_repo": "demo"}


# ---- Behavior 1: unknown_config_keys reports every non-field key ----------- #
def test_b1_all_known_keys_yield_nothing():
    assert foundry.unknown_config_keys(KNOWN_MINIMAL) == ()


def test_b1_empty_dict_yields_nothing():
    assert foundry.unknown_config_keys({}) == ()


def test_b1_every_declared_field_name_is_accepted():
    """Two-sided control: the helper must accept the WHOLE schema, not just a few
    fields -- otherwise a passing "known keys yield ()" test could hide a matcher
    that only ever recognises the three required fields."""
    every_field = {f.name: None for f in dataclasses.fields(foundry.ProductConfig)}
    assert foundry.unknown_config_keys(every_field) == ()


def test_b1_single_unknown_key_is_reported():
    raw = dict(KNOWN_MINIMAL, push_enable=False)
    assert foundry.unknown_config_keys(raw) == ("push_enable",)


def test_b1_several_unknown_keys_come_back_sorted_ascending():
    """Sorted output is what makes the operator message deterministic; insertion
    order here is deliberately reversed so ordering cannot pass by accident."""
    raw = dict(KNOWN_MINIMAL, zeta=1, alpha=2, mid=3)
    assert foundry.unknown_config_keys(raw) == ("alpha", "mid", "zeta")


def test_b1_known_fields_are_never_reported_alongside_an_unknown_one():
    raw = dict(KNOWN_MINIMAL, push_enabled=False, test_cmd="x", bogus=1)
    assert foundry.unknown_config_keys(raw) == ("bogus",)


@dataclasses.dataclass
class _ProbeSchema:
    """A stand-in schema used to prove the known-field set is read at CALL time."""
    name: str = ""
    iter128_probe_field: str = ""


def test_b1_known_set_is_reflected_at_call_time_not_hardcoded(monkeypatch):
    """The reflection requirement, made decidable: swap the schema the helper reads
    from module globals and the answer must change immediately. A hardcoded name
    list, or a set captured at def-time, would still call the probe field unknown --
    so this test fails on exactly the drift-prone designs the spec forbids."""
    probe = "iter128_probe_field"
    assert foundry.unknown_config_keys({probe: 1}) == (probe,)  # control: unknown today
    monkeypatch.setattr(foundry, "ProductConfig", _ProbeSchema)
    assert probe in foundry.config_field_names()
    assert foundry.unknown_config_keys({probe: 1}) == ()
    # ...and a real field of the OTHER schema is now correctly unknown
    assert foundry.unknown_config_keys({"push_enabled": 1}) == ("push_enabled",)


def test_b1_reflection_swap_is_undone_after_the_monkeypatch_test():
    """Guards the test above from leaking its patched schema into later tests."""
    assert "push_enabled" in foundry.config_field_names()


def test_b1_helper_does_not_mutate_its_input():
    raw = dict(KNOWN_MINIMAL, bogus=1)
    before = dict(raw)
    foundry.unknown_config_keys(raw)
    assert raw == before


# ---- Behavior 2: `_`-prefixed keys are adopter comments, always exempt ----- #
def test_b2_comment_keys_alongside_known_fields_yield_nothing():
    raw = dict(KNOWN_MINIMAL, _comment="why this product exists", _note="see roadmap")
    assert foundry.unknown_config_keys(raw) == ()


def test_b2_a_comment_key_alone_yields_nothing():
    assert foundry.unknown_config_keys({"_anything_at_all": 1}) == ()


def test_b2_exemption_is_prefix_only_not_substring():
    """A real typo containing an underscore must still be caught; only a LEADING
    underscore marks a comment."""
    assert foundry.unknown_config_keys({"push_enable": 1}) == ("push_enable",)
    assert foundry.unknown_config_keys({"a_comment": 1}) == ("a_comment",)


def test_b2_comment_key_does_not_mask_a_real_unknown_key_beside_it():
    raw = dict(KNOWN_MINIMAL, _comment="ok", push_enable=False)
    assert foundry.unknown_config_keys(raw) == ("push_enable",)


def test_b2_prefix_constant_is_the_documented_underscore():
    assert foundry.CONFIG_COMMENT_PREFIX == "_"


# ---- Behavior 3: suggest_config_key names the near miss, or nothing -------- #
@pytest.mark.parametrize("typo,expected", [
    ("push_enable", "push_enabled"),
    ("test_command", "test_cmd"),
])
def test_b3_near_miss_resolves_to_the_real_field(typo, expected):
    assert foundry.suggest_config_key(typo) == expected


@pytest.mark.parametrize("typo", ["push", "zzzzzzzz"])
def test_b3_no_close_match_returns_none(typo):
    """`push` is the load-bearing case: it is arguably the likeliest typo of all and
    difflib cannot resolve it, which is why the suggestion is a message-quality
    feature and never the trigger for the raise."""
    assert foundry.suggest_config_key(typo) is None


def test_b3_an_exact_field_name_suggests_itself():
    assert foundry.suggest_config_key("push_enabled") == "push_enabled"


def test_b3_suggestion_is_always_a_real_field_name_or_none():
    fields = set(foundry.config_field_names())
    for probe in ("push_enable", "test_command", "push", "zzzzzzzz", "vison",
                  "branchh", "reposs", "", "_comment"):
        got = foundry.suggest_config_key(probe)
        assert got is None or got in fields, f"{probe!r} suggested a non-field {got!r}"


def test_b3_empty_key_does_not_raise():
    assert foundry.suggest_config_key("") is None


# ---- internal helper: the per-key message fragment ------------------------- #
def test_describe_config_key_includes_the_hint_when_there_is_one():
    rendered = foundry.describe_config_key("push_enable")
    assert "push_enable" in rendered
    assert "push_enabled" in rendered


def test_describe_config_key_asserts_no_hint_it_does_not_have():
    """A message that invents a suggestion is worse than one with none: the operator
    would go and 'fix' a key that was never the problem."""
    rendered = foundry.describe_config_key("push")
    assert "push" in rendered
    assert "did you mean" not in rendered


def test_config_field_names_is_declaration_order_and_complete():
    declared = tuple(f.name for f in dataclasses.fields(foundry.ProductConfig))
    assert foundry.config_field_names() == declared
    assert "push_enabled" in declared and "test_cmd" in declared


# ---- the new error type is a ValueError so the dispatcher's skip path holds - #
def test_config_key_error_subclasses_value_error():
    assert issubclass(foundry.ConfigKeyError, ValueError)
