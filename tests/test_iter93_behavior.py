"""Black-box behaviour tests for iter 93 -- `foundry role-model --json`
(item 20 bite 3): a machine-readable JSON payload for the read-only, DORMANT
per-role MODEL-OVERRIDE resolution CLI, added ON TOP of the pre-existing dormant
core (RoleModelInvocation / resolve_role_model_argv / role_model_cli, shipped
iter 75). The change is a clean ADD-A-METHOD + ADD-A-FLAG: a new
`RoleModelInvocation.to_dict()` + an `as_json: bool = False` kw param on the
existing `role_model_cli` + a `--json` store_true subparser arg + a one-line
dispatch edit. ZERO call site: nothing in the running loop invokes it. This is a
`--flag` CLI (optional `--model` note, no `--file`): its exit is 0/1
(override-applied / passthrough), with NO file-not-found exit-2 branch -- so it
mirrors scout-plan #38 / cadence-review #36, NOT the `--file` CLIs
gate-precheck #31 / gate-verdict #32 which read 0/1/2.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-15) and the product's own OBSERVABLE behaviour only (running it). The
implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the frozen value object via
`foundry.resolve_role_model_argv` + `RoleModelInvocation.to_dict`, the CLI via
`foundry.role_model_cli` and `foundry.main(["role-model", ...])`. The two
canonical drive cases are grounded in observed behaviour: OVERRIDE =
resolve_role_model_argv(AGENT_RUN_ARGS, "opus") (model "opus", overridden True,
argv base + ("--model","opus"), exit 0); PASSTHROUGH =
resolve_role_model_argv(AGENT_RUN_ARGS, "   ") (model "", overridden False, argv
== base unchanged, exit 1). The dormancy proof uses only public runtime
introspection -- compiled function name tables (`co_names` recursed via
`_co_names_deep`) + a `dispatcher.py` source symbol-count -- and the mechanical
ASCII acceptance check uses `inspect.getsource` SCOPED to the two new/changed
symbols only (the established suite convention; never a whole-file scan / never
`git diff`). Fully offline and deterministic: no subprocess/git/network except
the fresh-import regression probe. There is deliberately NO `git diff --quiet
HEAD` control-path guard in this file -- the iter-86 fix removed that over-broad
freeze anti-pattern.
"""
import contextlib
import dataclasses
import importlib.util
import inspect
import io
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths + constants (module located via the BARE __file__ object,
# never a quoted source-literal main-module name -- the iter-54 meta-scanner)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

# The 3 keys to_dict() must expose, IN THIS ORDER. The str-list `argv` is a
# STORED field declared before the derived `overridden` property, so it lands in
# the MIDDLE (opposite gate-verdict/gate-precheck where the str-list was a prop
# and landed LAST). NO exit_code key.
KEY_ORDER = ["model", "argv", "overridden"]
EXPECTED_KEYS = set(KEY_ORDER)

# The three PRE-EXISTING role-model symbols (they shipped iter 75, so a
# whole-file grep would FALSE-POSITIVE). Dormancy is proven ONLY against these
# specific symbols + the command string -- NEVER the generic `to_dict` name
# (~30 other classes own a to_dict).
RM_SYMBOLS = ("RoleModelInvocation", "role_model_cli", "resolve_role_model_argv")

OVERRIDE_NOTE = "opus"
PASSTHROUGH_NOTES = ("", "   ", "\t", "\n ", "  \t\n")
# The 4 human-render line prefixes -- the leak discriminator.
HUMAN_PREFIXES = ("role-model:", "argv:", "model:", "overridden:")


def _r(note):
    """Resolve over the live AGENT_RUN_ARGS base -- the CLI's own base."""
    return foundry.resolve_role_model_argv(foundry.AGENT_RUN_ARGS, note)


def _cap(fn):
    """Run a callable, capturing stdout + the returned code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    return rc, buf.getvalue()


def _co_names_deep(fn):
    """Every name referenced by fn's code, recursing nested code objects. Pure
    runtime introspection -- does NOT read the module source text."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _leak_guard():
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter93_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# Preconditions -- keep the value-object tests non-vacuous (the two canonical
# cases really do behave as the spec's names claim)
# ==========================================================================
def test_precondition_canonical_cases_behave_as_named():
    ov = _r(OVERRIDE_NOTE)
    assert ov.model == "opus"
    assert ov.overridden is True
    assert ov.argv[-2:] == ("--model", "opus")
    assert ov.argv[:len(foundry.AGENT_RUN_ARGS)] == tuple(foundry.AGENT_RUN_ARGS)
    for note in PASSTHROUGH_NOTES:
        pt = _r(note)
        assert pt.model == "", "passthrough note=%r model=%r" % (note, pt.model)
        assert pt.overridden is False
        assert pt.argv == tuple(foundry.AGENT_RUN_ARGS)


# ==========================================================================
# Behavior 1 -- to_dict() is a FRESH dict with EXACTLY the 3 keys, in order
#               (str-list `argv` in the MIDDLE, `overridden` LAST); no exit_code
#               key; hasattr(RoleModelInvocation,"exit_code") False
# ==========================================================================
def test_b01_to_dict_exact_3_keys_in_order():
    for note in (OVERRIDE_NOTE, "   ", ""):
        d = _r(note).to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == KEY_ORDER, (
            "to_dict key order %r != %r" % (list(d.keys()), KEY_ORDER)
        )
        assert set(d.keys()) == EXPECTED_KEYS
        assert len(d) == 3
        assert "exit_code" not in d


def test_b01_no_exit_code_attribute():
    assert not hasattr(foundry.RoleModelInvocation, "exit_code")


def test_b01_fresh_dict_each_call():
    inv = _r(OVERRIDE_NOTE)
    assert inv.to_dict() is not inv.to_dict(), "to_dict returned the same dict across calls"


# ==========================================================================
# Behavior 2 -- to_dict()["model"] == the stored model field verbatim (a str)
# ==========================================================================
def test_b02_model_key_equals_stored_field():
    ov = _r(OVERRIDE_NOTE)
    assert ov.to_dict()["model"] == ov.model == "opus"
    assert isinstance(ov.to_dict()["model"], str)
    for note in PASSTHROUGH_NOTES:
        pt = _r(note)
        assert pt.to_dict()["model"] == pt.model == ""
        assert isinstance(pt.to_dict()["model"], str)


# ==========================================================================
# Behavior 3 -- to_dict()["argv"] is a LIST (not a tuple) == list(self.argv);
#               elements are plain strings (the escalation-check str-list class)
# ==========================================================================
def test_b03_argv_is_list_matching_field():
    for note in (OVERRIDE_NOTE, "   ", ""):
        inv = _r(note)
        d = inv.to_dict()
        assert type(d["argv"]) is list, "argv must be a list, not a tuple"
        assert d["argv"] == list(inv.argv)
        assert all(type(x) is str for x in d["argv"])


def test_b03_argv_override_contents():
    d = _r(OVERRIDE_NOTE).to_dict()
    assert d["argv"] == list(foundry.AGENT_RUN_ARGS) + ["--model", "opus"]


def test_b03_argv_passthrough_equals_base():
    d = _r("   ").to_dict()
    assert d["argv"] == list(foundry.AGENT_RUN_ARGS)


# ==========================================================================
# Behavior 4 -- to_dict()["overridden"] == the overridden property (a bool)
# ==========================================================================
def test_b04_overridden_key_equals_property():
    ov = _r(OVERRIDE_NOTE)
    assert ov.to_dict()["overridden"] == ov.overridden is True
    assert type(ov.to_dict()["overridden"]) is bool
    for note in PASSTHROUGH_NOTES:
        pt = _r(note)
        assert pt.to_dict()["overridden"] == pt.overridden is False
        assert type(pt.to_dict()["overridden"]) is bool


# ==========================================================================
# Behavior 5 -- THE DISCRIMINATING ROUND-TRIP over override + passthrough, plus
#               a non-vacuity guard proving a bare-tuple argv would FAIL it
# ==========================================================================
def test_b05_json_round_trip_override_and_passthrough():
    for note in (OVERRIDE_NOTE, "   ", ""):
        d = _r(note).to_dict()
        s = json.dumps(d)  # must not raise
        assert json.loads(s) == d, (
            "to_dict did not round-trip through JSON for note=%r (tuple leaked?)" % (note,)
        )


def test_b05_round_trip_non_vacuous_bare_tuple_fails():
    """Prove the round-trip is a real discriminator: the shape a bare
    `self.argv` (a tuple) would produce breaks `==` whenever argv is non-empty
    (json reads a tuple back as a list)."""
    d = _r(OVERRIDE_NOTE).to_dict()
    assert len(d["argv"]) > 0, "override argv unexpectedly empty -- guard would be vacuous"
    assert json.loads(json.dumps(d)) == d
    bad = dict(d)
    bad["argv"] = tuple(d["argv"])
    assert json.loads(json.dumps(bad)) != bad, (
        "round-trip check is vacuous -- a tuple-valued argv did not break equality"
    )


# ==========================================================================
# Behavior 6 -- to_dict() is read-only: mutating the returned dict never touches
#               the frozen instance; a fresh to_dict() is unaffected
# ==========================================================================
def test_b06_to_dict_read_only():
    for note in (OVERRIDE_NOTE, "   "):
        inv = _r(note)
        before = dataclasses.asdict(inv)
        d1 = inv.to_dict()
        d1["argv"].append("BOGUS")
        d1["model"] = "TAMPERED"
        d1["NEWKEY"] = 1
        d2 = inv.to_dict()
        assert dataclasses.asdict(inv) == before, "to_dict mutated the frozen instance"
        assert d2 == _r(note).to_dict(), "second to_dict was affected by mutation"
        assert d1 is not d2
        assert d1["argv"] is not d2["argv"], "argv list is shared across calls"


def test_b06_two_calls_equal_but_distinct():
    inv = _r(OVERRIDE_NOTE)
    a, b = inv.to_dict(), inv.to_dict()
    assert a == b
    assert a is not b


# ==========================================================================
# Behavior 7 -- default (as_json=False) prints BYTE-IDENTICAL human render for
#               override + passthrough; exit code unchanged; default param False
# ==========================================================================
def test_b07_default_equals_explicit_false():
    for note in (OVERRIDE_NOTE, "   ", ""):
        rc_def, out_def = _cap(lambda: foundry.role_model_cli(note))
        rc_false, out_false = _cap(lambda: foundry.role_model_cli(note, as_json=False))
        assert out_def == out_false, "default output != explicit as_json=False for note=%r" % (note,)
        assert rc_def == rc_false


def test_b07_as_json_default_is_false():
    sig = inspect.signature(foundry.role_model_cli)
    assert "as_json" in sig.parameters, "role_model_cli must gain an as_json param"
    assert sig.parameters["as_json"].default is False


def test_b07_human_render_is_four_lines():
    _, out = _cap(lambda: foundry.role_model_cli(OVERRIDE_NOTE))
    lines = out.splitlines()
    assert len(lines) == 4, "human render is not 4 lines: %r" % (lines,)
    assert lines[0] == "role-model:"


# ==========================================================================
# Behavior 8 -- the default (human) stdout is NOT valid JSON
# ==========================================================================
def test_b08_default_stdout_not_json():
    for note in (OVERRIDE_NOTE, "   ", ""):
        _, out = _cap(lambda: foundry.role_model_cli(note))
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)


# ==========================================================================
# Behavior 9 -- as_json=True prints EXACTLY json.dumps(to_dict(), indent=2)+nl,
#               with NO human line leaking; the leak check is armed/non-vacuous
# ==========================================================================
def test_b09_json_output_is_exact():
    for note in (OVERRIDE_NOTE, "   ", ""):
        _, out = _cap(lambda: foundry.role_model_cli(note, as_json=True))
        expected = json.dumps(_r(note).to_dict(), indent=2) + "\n"
        assert out == expected, "as_json output != json.dumps(to_dict(), indent=2)+newline for %r" % (note,)
        assert json.loads(out) == _r(note).to_dict()


def test_b09_no_human_lines_leak_into_json():
    for note in (OVERRIDE_NOTE, "   "):
        _, out = _cap(lambda: foundry.role_model_cli(note, as_json=True))
        for ln in out.splitlines():
            assert not ln.strip().startswith(HUMAN_PREFIXES), "human line %r leaked into JSON" % ln


def test_b09_leak_discriminator_is_armed():
    """The SAME prefix check must flag EVERY line of the human render -- else it
    is inert and its pass on JSON is meaningless."""
    _, human = _cap(lambda: foundry.role_model_cli(OVERRIDE_NOTE, as_json=False))
    lines = human.splitlines()
    flagged = [ln for ln in lines if ln.strip().startswith(HUMAN_PREFIXES)]
    assert len(lines) == 4, "human render unexpectedly not 4 lines: %r" % (lines,)
    assert len(flagged) == len(lines), (
        "leak discriminator is inert -- it did not flag every human line: %r" % (lines,)
    )


def test_b09_json_lines_start_with_brace_bracket_or_quote():
    _, out = _cap(lambda: foundry.role_model_cli(OVERRIDE_NOTE, as_json=True))
    for ln in out.splitlines():
        s = ln.strip()
        assert s == "" or s[0] in "{}[]\"", "JSON line does not start with a JSON token: %r" % ln


# ==========================================================================
# Behavior 10 -- exit code IDENTICAL in both modes == 0 if overridden else 1;
#                NO exit-2 branch (this is a --flag CLI, not a --file CLI)
# ==========================================================================
def test_b10_same_exit_code_both_modes():
    fixtures = [(OVERRIDE_NOTE, 0), ("   ", 1), ("", 1), ("\t", 1)]
    for note, code in fixtures:
        rc_h, _ = _cap(lambda: foundry.role_model_cli(note, as_json=False))
        rc_j, _ = _cap(lambda: foundry.role_model_cli(note, as_json=True))
        inv = _r(note)
        assert rc_h == rc_j == code, (
            "exit code diverged for note=%r: human=%r json=%r expected=%r" % (note, rc_h, rc_j, code)
        )
        assert code == (0 if inv.overridden else 1)


def test_b10_no_exit_two_branch():
    """A --flag CLI has no file-not-found path: every note yields exit 0 or 1."""
    for note in (OVERRIDE_NOTE, "sonnet", "", "   ", "\t", "\n ", "  x  "):
        for as_json in (False, True):
            rc, _ = _cap(lambda: foundry.role_model_cli(note, as_json=as_json))
            assert rc in (0, 1), "note=%r as_json=%s yielded exit %r (expected 0/1)" % (note, as_json, rc)


# ==========================================================================
# Behavior 11 -- both modes write NOTHING to disk
# ==========================================================================
def test_b11_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for note in (OVERRIDE_NOTE, "   ", ""):
        for as_json in (False, True):
            before = sorted(x.name for x in tmp_path.iterdir())
            _cap(lambda: foundry.role_model_cli(note, as_json=as_json))
            after = sorted(x.name for x in tmp_path.iterdir())
            assert before == after == [], "CLI wrote to disk (note=%r, as_json=%s)" % (note, as_json)


# ==========================================================================
# Behavior 12 -- argparse routing: --json is store_true; the dispatch spy proves
#                as_json True when present / False when absent; --model passed
# ==========================================================================
def test_b12_json_store_true_via_dispatch_spy(monkeypatch):
    captured = {}

    def fake(model_note, as_json=False):
        captured.update(model_note=model_note, as_json=as_json)
        return 0

    monkeypatch.setattr(foundry, "role_model_cli", fake)
    foundry.main(["role-model", "--model", "opus", "--json"])
    assert captured == {"model_note": "opus", "as_json": True}
    captured.clear()
    foundry.main(["role-model", "--model", "opus"])
    assert captured == {"model_note": "opus", "as_json": False}


# ==========================================================================
# Behavior 13 -- --model is optional (default "" -> passthrough exit 1); an
#                unrecognized positional after --json causes SystemExit
# ==========================================================================
def test_b13_model_optional_defaults_to_passthrough():
    rc, out = _cap(lambda: foundry.main(["role-model", "--json"]))
    assert rc == 1
    d = json.loads(out)
    assert d["model"] == "" and d["overridden"] is False


def test_b13_json_takes_no_value():
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["role-model", "--json", "bogus"])
    assert ei.value.code != 0


# ==========================================================================
# Behavior 14 -- end-to-end via foundry.main: override (exit 0) + passthrough
#                (exit 1)
# ==========================================================================
def test_b14_end_to_end_override():
    rc, out = _cap(lambda: foundry.main(["role-model", "--model", "opus", "--json"]))
    d = json.loads(out)
    assert rc == 0
    assert d["overridden"] is True
    assert d["model"] == "opus"
    assert isinstance(d["argv"], list)
    assert d["argv"][-2:] == ["--model", "opus"]


def test_b14_end_to_end_passthrough():
    rc, out = _cap(lambda: foundry.main(["role-model", "--json"]))
    d = json.loads(out)
    assert rc == 1
    assert d["overridden"] is False
    assert d["model"] == ""
    assert d["argv"] == list(foundry.AGENT_RUN_ARGS)


def test_b14_end_to_end_human_and_json_agree_on_exit():
    argv = ["role-model", "--model", "opus"]
    rc_h, out_h = _cap(lambda: foundry.main(argv))
    rc_j, out_j = _cap(lambda: foundry.main(argv + ["--json"]))
    assert rc_h == rc_j == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_h)
    json.loads(out_j)  # must parse


# ==========================================================================
# Behavior 15 -- DORMANCY: the running loop is unaffected
# ==========================================================================
def test_b15_orchestrators_do_not_reference_role_model_symbols():
    new = set(RM_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), "foundry.%s references role-model symbol(s): %r" % (fn.__name__, refs)


def test_b15_dispatcher_has_zero_role_model_references():
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in RM_SYMBOLS:
        assert dtext.count(sym) == 0, "dispatcher.py references role-model symbol %r" % sym
    assert dtext.count("role-model") == 0, "dispatcher.py names the role-model command string"


def test_b15_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


# ==========================================================================
# Acceptance-criteria / non-regression block
# ==========================================================================
def test_ac_public_surface_intact():
    assert callable(foundry.resolve_role_model_argv)
    assert callable(foundry.role_model_cli)
    assert dataclasses.is_dataclass(foundry.RoleModelInvocation)
    assert callable(foundry.RoleModelInvocation.to_dict)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), "foundry.%s missing (regression)" % fn
    assert dispatcher is not None


def test_ac_help_lists_role_model(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "role-model" in out
    for sub in ("run", "once", "gate-precheck", "gate-verdict"):
        assert sub in out, "subcommand %r missing from --help (regression)" % sub


def test_ac_new_symbols_ascii():
    """Scoped to the two symbols via inspect.getsource -- NOT a whole-file scan
    (foundry.py carries pre-existing non-ASCII elsewhere -- the iter-67 trap)."""
    srcs = [
        inspect.getsource(foundry.RoleModelInvocation.to_dict),
        inspect.getsource(foundry.role_model_cli),
    ]
    for src in srcs:
        offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert offenders == [], offenders[:5]


def test_ac_this_test_file_ascii():
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


def test_ac_leak_clean_and_matcher_armed():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "this test file leaks a denylisted token"
    # matcher is ARMED (not inert): a runtime-built home path IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"
