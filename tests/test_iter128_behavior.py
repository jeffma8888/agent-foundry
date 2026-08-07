"""Black-box behaviour tests for iter 128 -- the fail-closed unknown-key guard
at product-config load time (the `load_config` call site).

Covers Expected Behaviors 4-10 of the iter-128 PM spec. Behaviors 1-3 (the two
pure helpers `unknown_config_keys` / `suggest_config_key`) are owned by
`tests/test_iter128_helpers.py`, per the spec's required test-file split.

ISOLATION: written from the PM spec and the product's own observable RUNTIME
behaviour ONLY. The implementation source (`foundry.py`), the engineer's and
reviewer's notes, and `git diff` were NOT read. Fully offline and
deterministic: no subprocess, git, or network. Every assertion drives
`foundry.load_config` on a config written under `tmp_path`, except Behavior 9,
which loads the repo's real product configs read-only (they resolve to work
roots that already exist).

Message-shape note (Behaviors 4/5): the spec fixes WHAT the message must say
(the offending key; the suggestion when there is one; no suggestion when there
is not) but not its wording. So the "no suggestion was asserted" oracle is
wording-independent: it requires that no `ProductConfig` field name is *named*
(single-quoted) in the message. Quoting is how the message refers to a specific
key, while an informational listing of the whole known-field set is unquoted --
so this oracle survives rewording but still fails if a bogus suggestion is
emitted.
"""
import dataclasses
import json
import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _write_cfg(tmp_path, **over):
    """Mirror the config-writing helper used by tests/test_foundry.py."""
    data = {
        "name": "demo",
        "repo": "{FOUNDRY}/products/demo/repo",
        "allowed_push_repo": "demo",
        "vision": "{FOUNDRY}/products/demo/VISION.md",
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _field_names():
    """The schema, reflected at call time -- never a hardcoded list."""
    return {f.name for f in dataclasses.fields(foundry.ProductConfig)}


def _named_keys(msg):
    """The keys the message NAMES, i.e. every single-quoted token in it."""
    return set(re.findall(r"'([^']*)'", msg))


# ---------------------------------------------------------------- Behavior 4
def test_b4_unknown_key_with_suggestion_raises_naming_key_and_suggestion(tmp_path):
    """`"push_enable": false` -- the silent-push hazard -- is rejected, and the
    message carries BOTH the offending key and the nearest field name."""
    path = str(_write_cfg(tmp_path, push_enable=False))
    with pytest.raises(foundry.ConfigKeyError) as exc:
        foundry.load_config(path)
    msg = str(exc.value)
    assert "push_enable" in msg
    assert "push_enabled" in msg
    # both are NAMED as keys, so the operator can tell typo from suggestion
    named = _named_keys(msg)
    assert "push_enable" in named
    assert "push_enabled" in named


def test_b4_second_hazard_test_command_suggests_test_cmd(tmp_path):
    """The other measured hazard: a mistyped `test_command` silently ran a
    different quality gate than the adopter believed was running."""
    path = str(_write_cfg(tmp_path, test_command="echo hi"))
    with pytest.raises(foundry.ConfigKeyError) as exc:
        foundry.load_config(path)
    msg = str(exc.value)
    assert "test_command" in msg
    assert "test_cmd" in _named_keys(msg)


# ---------------------------------------------------------------- Behavior 5
def test_b5_unknown_key_without_suggestion_raises_and_asserts_no_suggestion(tmp_path):
    """A bare `"push"` has no near match, so it must STILL be rejected -- and
    the message must not invent a suggestion."""
    path = str(_write_cfg(tmp_path, push=False))
    with pytest.raises(foundry.ConfigKeyError) as exc:
        foundry.load_config(path)
    msg = str(exc.value)
    assert "push" in msg
    # nothing that is a real field name may be NAMED as a suggestion here
    assert _named_keys(msg) & _field_names() == set(), msg


def test_b5_totally_unrelated_key_also_rejected_without_suggestion(tmp_path):
    path = str(_write_cfg(tmp_path, zzzzzzzz=1))
    with pytest.raises(foundry.ConfigKeyError) as exc:
        foundry.load_config(path)
    msg = str(exc.value)
    assert "zzzzzzzz" in msg
    assert _named_keys(msg) & _field_names() == set(), msg


# ---------------------------------------------------------------- Behavior 6
def test_b6_config_key_error_is_a_value_error_subclass():
    """`dispatcher.py`'s existing `except Exception` skip-and-log path catches
    it with no dispatcher change."""
    assert issubclass(foundry.ConfigKeyError, ValueError)
    assert issubclass(foundry.ConfigKeyError, Exception)


def test_b6_raise_is_catchable_as_plain_exception(tmp_path):
    """The dispatcher catches `Exception`, so prove the raise is caught there
    (and that the repr it logs carries the offending key)."""
    path = str(_write_cfg(tmp_path, bogus_dispatcher_key=1))
    caught = None
    try:
        foundry.load_config(path)
    except Exception as exc:  # exactly what dispatcher.py does
        caught = exc
    assert caught is not None, "load_config accepted an unknown key"
    assert "bogus_dispatcher_key" in repr(caught)


# ---------------------------------------------------------------- Behavior 7
def test_b7_rejected_config_creates_no_directories(tmp_path):
    """The guard sits AHEAD of the work_root/state mkdirs, so a rejected config
    leaves no filesystem trace."""
    work = tmp_path / "work"
    assert not work.exists()
    path = str(_write_cfg(tmp_path, work_root=str(work), push_enable=False))
    with pytest.raises(foundry.ConfigKeyError):
        foundry.load_config(path)
    assert not work.exists(), "work_root was created despite the rejection"
    assert not (work / "state").exists(), "state dir was created despite the rejection"


def test_b7_accepted_config_does_still_create_them(tmp_path):
    """Control for Behavior 7: the mkdirs are skipped only on rejection."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    assert pathlib.Path(cfg.work_root).is_dir()
    assert cfg.state.is_dir()


# ---------------------------------------------------------------- Behavior 8
def test_b8_underscore_prefixed_keys_are_accepted(tmp_path):
    """The repo's own dispatcher configs document `_comment`/`_note` as a
    comment convention, so an adopter will copy it into a product config."""
    cfg = foundry.load_config(str(_write_cfg(
        tmp_path, _comment="why this product exists", _note="ping me first")))
    assert cfg.name == "demo"


def test_b8_underscore_keys_change_no_resolved_field(tmp_path):
    """Every resolved field equals what the same config without the comment
    keys produces. Both loads use the SAME config path, so no path-derived
    value can differ for an incidental reason."""
    plain = foundry.load_config(str(_write_cfg(tmp_path)))
    commented = foundry.load_config(str(_write_cfg(
        tmp_path, _comment="c", _note="n", _owner="someone")))
    for name in sorted(_field_names()):
        assert getattr(commented, name) == getattr(plain, name), name
    # and the derived paths too
    assert commented.state == plain.state
    assert commented.night_log == plain.night_log
    assert commented.stop_file == plain.stop_file


# ---------------------------------------------------------------- Behavior 9
def test_b9_every_real_product_config_still_loads():
    """Live-fleet inertness: the guard may only fire on a FUTURE mistake.
    Deliberately not pinned to a count of four, so adding a product to the
    fleet cannot false-red this test."""
    paths = sorted(REPO_ROOT.glob("products/*/config.json"))
    assert paths, "no product configs found to check"
    for p in paths:
        cfg = foundry.load_config(str(p))
        assert cfg.name, f"{p} loaded with an empty name"


# --------------------------------------------------------------- Behavior 10
def test_b10_missing_required_field_still_raises(tmp_path):
    """Regression, unchanged: `load_config` already failed closed on a config
    missing a required field, and still does."""
    data = json.loads(_write_cfg(tmp_path).read_text())
    data.pop("allowed_push_repo")
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    with pytest.raises(TypeError):
        foundry.load_config(str(p))


def test_b10_known_only_config_resolves_exactly_as_before(tmp_path):
    """Regression, unchanged: a config of only known keys yields the same
    values as before this iteration (the pre-iteration contract, restated)."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    assert cfg.name == "demo"
    assert cfg.allowed_push_repo == "demo"
    assert cfg.branch == "main"
    assert cfg.push_enabled is True
    # the two defaults the measured hazards would have silently kept
    assert cfg.test_cmd == "uv run pytest"
    assert cfg.roles_dir == str(foundry.FOUNDRY / "roles")
    assert cfg.learnings.endswith("LEARNINGS.md")
    assert "{FOUNDRY}" not in cfg.repo and str(foundry.FOUNDRY) in cfg.repo
    assert cfg.state == pathlib.Path(cfg.work_root) / "state"


def test_b10_overridden_known_keys_still_take_effect(tmp_path):
    """The guard rejects UNKNOWN keys only -- a correctly spelled override must
    still win over its default."""
    cfg = foundry.load_config(str(_write_cfg(
        tmp_path, push_enabled=False, test_cmd="echo hi", branch="release")))
    assert cfg.push_enabled is False
    assert cfg.test_cmd == "echo hi"
    assert cfg.branch == "release"
