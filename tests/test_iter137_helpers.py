"""ENGINEER-owned unit tests for iter 137 -- the PURE helpers behind `new-product`.

Scope split, following the iter-126/128 precedent in this directory: this file
covers ONLY the pure functions (`product_config_template`, `product_name_error`,
`new_product_exit_code`, `new_product_next_steps`) -- no filesystem, no config
file, no `main()` call, no `FOUNDRY` rebind. The CLI's observable BEHAVIOR (the
spec's Expected Behaviors 3-13: the write, the refusals, the exit codes, the
byte-identical no-overwrite, `--force`, and the `USAGE.md` correction) belongs to
the ISOLATED tester in `tests/test_iter137_behavior.py`; authoring those here
would hand the judge its own oracle.

WHY it exists at all: the tester stage is this pipeline's #1 measured loss source,
so covering the new pure symbols here means a killed tester round can no longer
leave them completely untested.

Fully offline and deterministic: pure function calls only. The import root is
derived at RUNTIME from `__file__`, so no machine-specific path is committed.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402


# ---- product_config_template: the emitted keys are all schema-legal ---------- #
def test_template_has_no_unknown_keys():
    """Every emitted key is a `ProductConfig` field or a `_`-prefixed comment."""
    tpl = foundry.product_config_template(name="demo", repo="/nowhere/demo")
    assert foundry.unknown_config_keys(tpl) == ()


def test_template_work_root_is_explicit():
    """An EMPTY work_root would let resolve()'s default fire against the ambient
    FOUNDRY at load time -- the exact path by which a tmp-root test still writes
    into the real checkout. The template must therefore state it."""
    tpl = foundry.product_config_template(name="demo", repo="/nowhere/demo")
    assert tpl["work_root"] == "{FOUNDRY}/products/demo"


def test_template_is_review_only_by_default():
    tpl = foundry.product_config_template(name="demo", repo="/nowhere/demo")
    assert tpl["push_enabled"] is False


def test_template_leaves_vision_unset_not_guessed():
    """A guessed `<repo>/VISION.md` that does not exist yet is a lint ERROR; an
    unset one is a WARN. The scaffold must not ship a config that lints red."""
    tpl = foundry.product_config_template(name="demo", repo="/nowhere/demo")
    assert tpl["vision"] == ""


def test_template_allowed_push_repo_defaults_to_repo_tail():
    tpl = foundry.product_config_template(name="demo", repo="/nowhere/other-name")
    assert tpl["allowed_push_repo"] == "other-name"


def test_template_allowed_push_repo_override_wins():
    tpl = foundry.product_config_template(
        name="demo", repo="/nowhere/demo", allowed_push_repo="pushable")
    assert tpl["allowed_push_repo"] == "pushable"


def test_template_carries_one_nonempty_comment():
    tpl = foundry.product_config_template(name="demo", repo="/nowhere/demo")
    comments = [k for k in tpl if k.startswith(foundry.CONFIG_COMMENT_PREFIX)]
    assert len(comments) == 1
    assert isinstance(tpl[comments[0]], str) and tpl[comments[0]].strip()


def test_template_is_pure_and_deterministic():
    """Same inputs -> equal dicts, and mutating the result cannot affect the next
    call (no shared mutable default is handed out)."""
    first = foundry.product_config_template(name="demo", repo="/nowhere/demo")
    first["name"] = "mutated"
    second = foundry.product_config_template(name="demo", repo="/nowhere/demo")
    assert second["name"] == "demo"
    assert second == foundry.product_config_template(name="demo", repo="/nowhere/demo")


# ---- product_name_error: the refusal gate ----------------------------------- #
def test_name_error_accepts_plain_names():
    for good in ("demo", "_platform", "my-tool", "my_tool2"):
        assert foundry.product_name_error(good) is None, good


def test_name_error_rejects_unsafe_names_and_names_the_flag():
    for bad in ("", "   ", "a/b", "..", ".", "a\\b", "x\0y", "nested/deep/name"):
        reason = foundry.product_name_error(bad)
        assert reason is not None, bad
        assert "--name" in reason, reason


def test_name_error_never_raises_on_odd_input():
    """Total function: any string returns a str-or-None, never an exception."""
    for odd in ("\n", "..\\..", "a" * 300, "\u00e9", "-x"):
        assert foundry.product_name_error(odd) is None or isinstance(
            foundry.product_name_error(odd), str)


# ---- new_product_exit_code: the scoped 0/1 rule ----------------------------- #
def _lint(*findings: foundry.ConfigFinding) -> foundry.ConfigLint:
    return foundry.ConfigLint(config_path="demo", findings=tuple(findings))


def test_exit_code_zero_when_clean():
    assert foundry.new_product_exit_code(_lint()) == 0


def test_exit_code_one_for_an_argument_field_error():
    for field in foundry.NEW_PRODUCT_ARG_FIELDS:
        lint = _lint(foundry.ConfigFinding(field, "error", "boom"))
        assert foundry.new_product_exit_code(lint) == 1, field


def test_exit_code_ignores_non_argument_and_warn_findings():
    """`roles_dir` describes the CHECKOUT and `vision` is an edit the operator has
    not made yet -- both are printed but neither is fixable by re-running the verb
    with different arguments, so neither may set its exit code."""
    lint = _lint(
        foundry.ConfigFinding("roles_dir", "error", "checkout is incomplete"),
        foundry.ConfigFinding("vision", "warn", "vision path is unset"),
        foundry.ConfigFinding("repo", "warn", "only a warning"))
    assert foundry.new_product_exit_code(lint) == 0


# ---- new_product_next_steps: the paste-ready block -------------------------- #
def test_next_steps_names_the_written_path_and_the_portable_form():
    path = pathlib.PurePosixPath("/root/products/demo/config.json")
    text = foundry.new_product_next_steps("demo", pathlib.Path(str(path)))
    assert str(path) in text
    assert "{FOUNDRY}/products/demo/config.json" in text
    assert "work_items" in text
    assert "lint-config" in text
