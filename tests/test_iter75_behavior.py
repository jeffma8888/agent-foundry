"""Black-box behaviour tests for iter 75 -- item 20, bite 3 of ~4: the DORMANT
pure per-role MODEL-OVERRIDE resolver
`resolve_role_model_argv(base_argv, model_note, template=None)
-> RoleModelInvocation`
(plus the frozen `RoleModelInvocation` dataclass with fields model/argv and a
pure `overridden` property, the patchable module-level `MODEL_ARG_TEMPLATE`
constant defaulting to `("--model", "{model}")`, and the on-demand read-only
`foundry role-model [--model NOTE]` CLI). ZERO call site: nothing in the
pipeline invokes it this iteration.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-11) and the product's own OBSERVABLE behaviour only (running it).
The implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the pure core via `foundry.resolve_role_model_argv`,
the constant via `foundry.MODEL_ARG_TEMPLATE`, and the CLI via
`foundry.main(["role-model", ...])`. The dormancy / off-control-path checks use
only public RUNTIME introspection -- module attributes, compiled function name
tables (`__code__.co_names` recursed via `_co_names_deep`), `--help` output, and
a git `--quiet` exit-code probe -- plus, for the mechanical ASCII / leak-clean
acceptance criteria, `inspect.getsource` scoped to the NEW symbols only (the
established suite convention; never a whole-file scan / never `git diff`). Fully
offline and deterministic: NO subprocess/git/network/agent-run except the
fresh-import + `--help` regression probes and the control-path byte-unchanged
git `--quiet` probe.
"""
import dataclasses
import importlib.util
import inspect
import io
import contextlib
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths + constants (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

# The symbols this iteration ADDS. They must be dormant: no orchestrator and
# dispatcher.py reference any of them by name.
NEW_SYMBOLS = (
    "resolve_role_model_argv",
    "RoleModelInvocation",
    "MODEL_ARG_TEMPLATE",
    "role_model_cli",
)

_GIT_OK = subprocess.run(
    ["git", "rev-parse", "--is-inside-work-tree"],
    cwd=str(_ROOT), capture_output=True, text=True,
).returncode == 0


def _co_names_deep(fn):
    """Every name referenced by fn's code, recursing into nested code objects.
    Pure runtime introspection -- does NOT read the module source text."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _leak_guard():
    """Dynamically import the committed leak-guard, registering the module in
    sys.modules BEFORE exec so its own import machinery works."""
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter75_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cli(args):
    """Drive the CLI via foundry.main, capturing stdout + exit code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.main(list(args))
    return rc, buf.getvalue()


def _r(base, note, **kw):
    return foundry.resolve_role_model_argv(base, note, **kw)


# ==========================================================================
# Behavior 1 -- pure, total, never-raises, offline, deterministic
# ==========================================================================
def test_b01_total_never_raises_and_typed():
    cases = [
        ([], ""),
        (["run", "--task", "{prompt}"], "opus"),
        (("a", "b"), "  sonnet  "),
        (["--model", "{model}"], ""),          # weird base with a {model} token
        ([], "   "),
    ]
    for base, note in cases:
        r = _r(base, note)                     # must not raise
        assert type(r).__name__ == "RoleModelInvocation", (
            f"resolve_role_model_argv did not return RoleModelInvocation for {(base, note)!r}"
        )


def test_b01_deterministic_value_equality():
    for base, note in (([], ""), (["a"], "opus"), (("x", "y"), "  z ")):
        assert _r(base, note) == _r(base, note), (
            f"not deterministic / value-equal for {(base, note)!r}"
        )


def test_b01_no_filesystem_access(monkeypatch):
    """Pure: it opens no file. Sabotage builtins.open; the core still works."""
    def _boom(*a, **k):
        raise AssertionError("resolve_role_model_argv performed filesystem I/O")
    monkeypatch.setattr("builtins.open", _boom)
    r = _r(["a"], "opus")
    assert r.model == "opus"
    assert r.argv == ("a", "--model", "opus")


# ==========================================================================
# Behavior 2 -- frozen dataclass with exactly two fields: model, argv
# ==========================================================================
def test_b02_frozen_dataclass_exact_fields():
    assert dataclasses.is_dataclass(foundry.RoleModelInvocation)
    field_names = tuple(f.name for f in dataclasses.fields(foundry.RoleModelInvocation))
    assert field_names == ("model", "argv"), (
        f"RoleModelInvocation fields = {field_names}, expected ('model', 'argv')"
    )
    r = _r(["a"], "opus")
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.model = "sonnet"                     # frozen -> forbidden
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.argv = ()


def test_b02_field_types():
    r = _r(["a", "b"], "opus")
    assert isinstance(r.model, str)
    assert isinstance(r.argv, tuple)
    assert all(isinstance(x, str) for x in r.argv)


# ==========================================================================
# Behavior 3 -- passthrough (no override): empty or whitespace-only note
# ==========================================================================
def test_b03_passthrough_byte_identical_argv():
    for note in ("", "   ", "\t", "\n ", "  \t\n"):
        base = ["run", "--task", "{prompt}"]
        r = _r(base, note)
        assert r.argv == tuple(base), (
            f"passthrough note={note!r} did NOT return base argv unchanged: {r.argv!r}"
        )
        assert r.model == "", f"passthrough note={note!r} model={r.model!r}, expected ''"
        assert r.overridden is False, f"passthrough note={note!r} overridden={r.overridden}"


def test_b03_passthrough_no_extra_args_even_with_model_token_in_base():
    # a base already containing '{model}' is NOT substituted on passthrough
    r = _r(["--model", "{model}"], "")
    assert r.argv == ("--model", "{model}")
    assert r.overridden is False


# ==========================================================================
# Behavior 4 -- override applied: non-empty (stripped) note
# ==========================================================================
def test_b04_override_appends_stripped_model_args():
    r = _r(["run", "--task", "{prompt}"], "  opus  ")
    assert r.model == "opus", f"model not stripped: {r.model!r}"
    assert r.overridden is True
    assert r.argv == ("run", "--task", "{prompt}", "--model", "opus"), (
        f"override argv wrong: {r.argv!r}"
    )
    # model args are APPENDED after the base, in order
    assert r.argv[:3] == ("run", "--task", "{prompt}")


def test_b04_override_over_empty_base():
    r = _r([], "opus")
    assert r.argv == ("--model", "opus")
    assert r.model == "opus"
    assert r.overridden is True


# ==========================================================================
# Behavior 5 -- template substitution: {model} replaced per element
# ==========================================================================
def test_b05_default_template_substitution():
    r = _r(["a"], "opus")
    assert r.argv == ("a", "--model", "opus")


def test_b05_single_element_equals_template():
    r = _r(["a"], "opus", template=("--model={model}",))
    assert r.argv == ("a", "--model=opus"), f"{r.argv!r}"


def test_b05_element_without_model_token_appended_unchanged():
    r = _r([], "opus", template=("--flag", "{model}", "--extra"))
    assert r.argv == ("--flag", "opus", "--extra"), f"{r.argv!r}"


# ==========================================================================
# Behavior 6 -- MODEL_ARG_TEMPLATE read AT CALL TIME + explicit template wins
# ==========================================================================
def test_b06_module_template_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "MODEL_ARG_TEMPLATE", ("-m", "{model}"))
    r = _r(["a"], "opus")
    assert r.argv == ("a", "-m", "opus"), (
        f"monkeypatched MODEL_ARG_TEMPLATE not honored at call time: {r.argv!r}"
    )
    # (monkeypatch auto-restores the module global after the test)


def test_b06_restore_reverts_to_default():
    # after the previous test restores, the default template is back in effect
    r = _r(["a"], "opus")
    assert r.argv == ("a", "--model", "opus")


def test_b06_explicit_template_arg_wins(monkeypatch):
    monkeypatch.setattr(foundry, "MODEL_ARG_TEMPLATE", ("-m", "{model}"))
    r = _r(["a"], "opus", template=("--pick", "{model}"))
    assert r.argv == ("a", "--pick", "opus"), (
        f"explicit template= did not override module constant: {r.argv!r}"
    )


def test_b06_default_template_value():
    assert foundry.MODEL_ARG_TEMPLATE == ("--model", "{model}"), (
        f"MODEL_ARG_TEMPLATE default = {foundry.MODEL_ARG_TEMPLATE!r}"
    )


# ==========================================================================
# Behavior 7 -- base_argv never mutated; argv is a tuple; list==tuple base
# ==========================================================================
def test_b07_base_not_mutated_and_argv_is_tuple():
    base = ["run", "--task", "{prompt}"]
    snapshot = list(base)
    r = _r(base, "opus")
    assert base == snapshot, f"caller's list mutated: {base!r}"
    assert isinstance(r.argv, tuple)


def test_b07_list_and_tuple_base_yield_same_argv():
    assert _r(["a", "b"], "opus").argv == _r(("a", "b"), "opus").argv


# ==========================================================================
# Behavior 8 -- overridden property == bool(self.model)
# ==========================================================================
def test_b08_overridden_equals_bool_model():
    assert _r([], "").overridden is False
    assert _r([], "opus").overridden is True
    # a whitespace-only note strips to empty -> not overridden
    assert _r([], "   ").overridden is False


# ==========================================================================
# Behavior 9 -- CLI override: exit 0, summary includes model + overridden: true
# ==========================================================================
def test_b09_cli_override_exit0(capsys):
    rc, out = _cli(["role-model", "--model", "opus"])
    assert rc == 0, f"override returned {rc!r}, expected 0\n{out}"
    assert "overridden: true" in out, f"summary missing 'overridden: true':\n{out}"
    assert "opus" in out, f"summary does not name the applied model:\n{out}"


def test_b09_cli_override_resolves_over_agent_run_args(capsys):
    rc, out = _cli(["role-model", "--model", "opus"])
    # base argv comes from AGENT_RUN_ARGS; each of its elements appears
    for tok in foundry.AGENT_RUN_ARGS:
        assert tok in out, f"CLI did not print base-argv token {tok!r}:\n{out}"
    assert "--model" in out and "opus" in out


# ==========================================================================
# Behavior 10 -- CLI passthrough: exit 1, overridden: false, prints base argv
# ==========================================================================
def test_b10_cli_passthrough_no_model_exit1(capsys):
    rc, out = _cli(["role-model"])
    assert rc == 1, f"passthrough (no --model) returned {rc!r}, expected 1\n{out}"
    assert "overridden: false" in out, f"summary missing 'overridden: false':\n{out}"


def test_b10_cli_passthrough_empty_and_whitespace_note():
    for note in ("", "   ", "\t"):
        rc, out = _cli(["role-model", "--model", note])
        assert rc == 1, f"passthrough note={note!r} returned {rc!r}, expected 1\n{out}"
        assert "overridden: false" in out, f"note={note!r} missing 'overridden: false':\n{out}"


def test_b10_cli_passthrough_prints_base_argv_unchanged(capsys):
    rc, out = _cli(["role-model"])
    for tok in foundry.AGENT_RUN_ARGS:
        assert tok in out, f"passthrough did not print base token {tok!r}:\n{out}"


def test_b10_cli_writes_nothing_and_needs_no_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = sorted(x.name for x in tmp_path.iterdir())
    # no --config supplied (dispatched before load_config, like gate-verdict/lint-spec)
    rc_o, _ = _cli(["role-model", "--model", "opus"])
    rc_p, _ = _cli(["role-model"])
    after = sorted(x.name for x in tmp_path.iterdir())
    assert rc_o == 0 and rc_p == 1
    assert before == after == [], f"CLI wrote to disk: {before} -> {after}"


# ==========================================================================
# Behavior 11 -- CLI reads AGENT_RUN_ARGS + MODEL_ARG_TEMPLATE at call time
# ==========================================================================
def test_b11_cli_reads_agent_run_args_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "AGENT_RUN_ARGS", ["ZZBASE", "{prompt}"])
    rc, out = _cli(["role-model", "--model", "opus"])
    assert rc == 0
    assert "ZZBASE" in out, f"CLI did not read patched AGENT_RUN_ARGS:\n{out}"


def test_b11_cli_reads_model_arg_template_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "MODEL_ARG_TEMPLATE", ("--pick", "{model}"))
    rc, out = _cli(["role-model", "--model", "sonnet"])
    assert rc == 0
    assert "--pick" in out, f"CLI did not read patched MODEL_ARG_TEMPLATE:\n{out}"
    assert "sonnet" in out


# ==========================================================================
# Acceptance-criteria / non-regression block (offline)
# ==========================================================================
def test_ac_public_surface_and_import_intact():
    assert callable(foundry.resolve_role_model_argv)
    assert callable(foundry.role_model_cli)
    assert isinstance(foundry.MODEL_ARG_TEMPLATE, tuple)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"
    assert dispatcher is not None


def test_ac_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_ac_help_lists_role_model(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "role-model" in out, f"role-model missing from --help:\n{out}"
    for sub in ("run", "once", "doctor", "lint-spec", "gate-precheck", "gate-verdict"):
        assert sub in out, f"subcommand {sub!r} missing from --help (regression)"


def test_ac_dormant_zero_call_site():
    """No orchestrator and no dispatcher-module function references any new
    symbol by name (compiled name tables -- no source text read), nor names the
    `role-model` command string."""
    new = set(NEW_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), f"foundry.{fn.__name__} references dormant symbol(s): {refs}"
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in NEW_SYMBOLS:
        assert sym not in dtext, f"dispatcher.py references dormant symbol {sym!r}"
    assert "role-model" not in dtext, "dispatcher.py names the 'role-model' command string"


@pytest.mark.skipif(not _GIT_OK, reason="not inside a git work tree")
def test_ac_control_path_byte_unchanged():
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py", "scripts/"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, "dispatcher.py / scripts NOT byte-unchanged from HEAD"


def test_ac_new_symbols_ascii():
    """The NEW code is pure ASCII. Scoped to the new symbols via
    inspect.getsource -- NOT a whole-file scan (foundry.py carries pre-existing
    non-ASCII elsewhere -- the iter-67 trap)."""
    new_sources = [
        inspect.getsource(foundry.resolve_role_model_argv),
        inspect.getsource(foundry.RoleModelInvocation),
        inspect.getsource(foundry.role_model_cli),
        repr(foundry.MODEL_ARG_TEMPLATE),
    ]
    for src in new_sources:
        offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert offenders == [], offenders[:5]


def test_ac_leak_clean_and_matcher_armed():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "this test file leaks a denylisted token"
    # matcher is ARMED (not inert): a RUNTIME-built home-path needle IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"


def test_ac_this_test_file_ascii():
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []
