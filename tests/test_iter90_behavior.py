"""Black-box behaviour tests for iter 90 -- `foundry scout-plan --json`
(dual-PM-scout feature bite 1 observability, docs/DUAL_PM_SCOUT_SPEC.md): a
machine-readable JSON payload for the read-only dual-PM-scout PHASE PLANNER,
added ON TOP of the pre-existing dormant core (decide_scout_phase /
ScoutPhasePlan / scout_plan_cli, iter 80). The change is a clean
ADD-A-METHOD + ADD-A-FLAG: a new `ScoutPhasePlan.to_dict()` (5 keys) + an
`as_json: bool = False` kw param on the existing `scout_plan_cli` + a `--json`
store_true subparser arg + a one-line dispatch edit. ZERO call site: nothing in
the running loop invokes it. This is the FOURTH `--json` CLI in the org-design
observability cadence (iter 87 escalation-check, 88 cadence-review, 89
restaffing-review) and the LAST of the flat/`--flag` CLIs; the only new wrinkle
vs the prior three is the `stages` list-of-pairs -> list-of-`{stage,lens}`-dicts
serialization (so the two-level JSON round-trip holds).

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-15) and the product's own OBSERVABLE behaviour only (running it),
plus the tests/ dir (test_iter80_behavior.py for the core scout API + human
render, test_iter88_behavior.py for the flag-based `--json` convention -- tests/
is explicitly readable). The implementation source (foundry.py internals), the
engineer's and reviewer's notes, and `git diff` were NOT read to design these
behaviour tests. Every check drives the PUBLIC interface: the frozen value
object via `foundry.decide_scout_phase` + `ScoutPhasePlan.to_dict`, the CLI via
`foundry.scout_plan_cli` and `foundry.main(["scout-plan", ...])`. The dormancy
proof uses only public runtime introspection -- compiled function name tables
(`co_names` recursed) + a `dispatcher.py` source symbol-count -- and the
mechanical ASCII acceptance check uses `inspect.getsource` SCOPED to the two
new/changed symbols only (the established suite convention; never a whole-file
scan / never `git diff`). Fully offline and deterministic: no
subprocess/git/network except the fresh-import regression probe. There is
deliberately NO `git diff --quiet HEAD` control-path guard in this file -- the
iter-86 fix removed that over-broad freeze anti-pattern.
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

# The 5 keys to_dict() must expose, exactly. NO exit_code key.
EXPECTED_KEYS = {"enabled", "stages", "count", "stage_names", "verdict"}

# The three PRE-EXISTING scout symbols (they existed since iter 80, so a
# whole-file grep would FALSE-POSITIVE). Dormancy is proven ONLY against these
# specific symbols + the command string -- NOT the generic `to_dict` name (many
# other classes own a to_dict).
SCOUT_SYMBOLS = ("scout_plan_cli", "ScoutPhasePlan", "decide_scout_phase")

# Drive cases: (label, flag, lenses). Grounded in observed behaviour.
#   enabled-default -> 2 stages, DUAL, exit 1
#   disabled        -> 0 stages, SINGLE, exit 0
#   multi-lens      -> 3 stages pm_scout_a/b/c, DUAL, exit 1
#   enabled-empty   -> 0 stages but DUAL (verdict tracks the FLAG, not count), exit 1
ENABLED_DEFAULT = ("enabled-default", True, None)
DISABLED = ("disabled", False, None)
MULTI_LENS = ("multi-lens", True, ["x", "y", "z"])
ENABLED_EMPTY = ("enabled-empty", True, [])
CASES = (ENABLED_DEFAULT, DISABLED, MULTI_LENS, ENABLED_EMPTY)


def _plan(flag, lenses):
    """Build a ScoutPhasePlan through the pure public builder."""
    if lenses is None:
        return foundry.decide_scout_phase(flag)
    return foundry.decide_scout_phase(flag, lenses)


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
    spec = importlib.util.spec_from_file_location("leak_guard_iter90_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# Preconditions -- keep the value-object tests non-vacuous (the four drive
# cases really do behave as the spec's names claim)
# ==========================================================================
def test_precondition_cases_behave_as_named():
    p = _plan(*ENABLED_DEFAULT[1:])
    assert p.enabled is True and p.verdict == "DUAL" and p.count == 2
    p = _plan(*DISABLED[1:])
    assert p.enabled is False and p.verdict == "SINGLE" and p.count == 0
    p = _plan(*MULTI_LENS[1:])
    assert p.enabled is True and p.verdict == "DUAL" and p.count == 3
    p = _plan(*ENABLED_EMPTY[1:])
    assert p.enabled is True and p.verdict == "DUAL" and p.count == 0


# ==========================================================================
# Behavior 1 -- to_dict() has EXACTLY the 5 keys, fresh dict, no exit_code key
# ==========================================================================
def test_b01_to_dict_exact_5_keys():
    for _label, flag, lenses in CASES:
        d = _plan(flag, lenses).to_dict()
        assert isinstance(d, dict)
        assert set(d.keys()) == EXPECTED_KEYS, (
            "to_dict keys %r != %r" % (set(d.keys()), EXPECTED_KEYS)
        )
        assert len(d) == 5
        assert "exit_code" not in d


# ==========================================================================
# Behavior 2 -- `enabled` is the stored bool, emitted by IDENTITY
# ==========================================================================
def test_b02_enabled_by_identity():
    for _label, flag, lenses in CASES:
        p = _plan(flag, lenses)
        d = p.to_dict()
        assert d["enabled"] is p.enabled
        assert type(d["enabled"]) is bool


# ==========================================================================
# Behavior 3 -- count/verdict REUSE the frozen props; verdict tracks enabled
# ==========================================================================
def test_b03_count_and_verdict_reuse_props():
    for _label, flag, lenses in CASES:
        p = _plan(flag, lenses)
        d = p.to_dict()
        assert d["count"] == p.count
        assert type(d["count"]) is int
        assert d["verdict"] == p.verdict
        assert type(d["verdict"]) is str
        assert d["verdict"] == ("DUAL" if d["enabled"] else "SINGLE")


# ==========================================================================
# Behavior 4 -- `stages` is a JSON-native list of self-describing dicts in order
# ==========================================================================
def test_b04_stages_list_of_pair_dicts_in_order():
    for _label, flag, lenses in CASES:
        p = _plan(flag, lenses)
        d = p.to_dict()
        assert type(d["stages"]) is list, "stages must be a list, not a tuple"
        assert d["stages"] == [
            {"stage": name, "lens": lens} for name, lens in p.stages
        ]
        assert len(d["stages"]) == p.count
        for elem in d["stages"]:
            assert type(elem) is dict
            assert set(elem.keys()) == {"stage", "lens"}
            assert type(elem["stage"]) is str
            assert type(elem["lens"]) is str


# ==========================================================================
# Behavior 5 -- `stage_names` is a JSON-native list of the ordered stage names
# ==========================================================================
def test_b05_stage_names_list_matches():
    for _label, flag, lenses in CASES:
        p = _plan(flag, lenses)
        d = p.to_dict()
        assert type(d["stage_names"]) is list, "stage_names must be a list, not a tuple"
        assert d["stage_names"] == list(p.stage_names)
        assert d["stage_names"] == [s["stage"] for s in d["stages"]]


# ==========================================================================
# Behavior 6 -- THE discriminating assertion: two-level JSON round-trip holds
#               for every case (a tuple-valued stages/stage_names would fail)
# ==========================================================================
def test_b06_two_level_json_round_trip_all_cases():
    for label, flag, lenses in CASES:
        d = _plan(flag, lenses).to_dict()
        s = json.dumps(d)  # must not raise (a tuple-of-dataclasses would)
        assert json.loads(s) == d, "to_dict did not round-trip through JSON for %r" % label


def test_b06_bare_tuple_stages_would_break_round_trip():
    # Guard against a regression to `list(self.stages)` (inner tuples): prove the
    # round-trip is NOT vacuously true -- a naive tuple-of-pairs shape breaks it.
    naive = {"stages": [("pm_scout_a", "x")]}
    assert json.loads(json.dumps(naive)) != naive
    # ...while the real shape (list of {stage,lens} dicts) round-trips.
    real = _plan(True, ["x"]).to_dict()
    assert json.loads(json.dumps(real)) == real


# ==========================================================================
# Behavior 7 -- to_dict() is read-only / non-aliasing (fresh dict, no mutation
#               of the frozen instance even through nested tampering)
# ==========================================================================
def test_b07_read_only_and_fresh_dict():
    for _label, flag, lenses in CASES:
        p = _plan(flag, lenses)
        before = dataclasses.asdict(p)
        d1 = p.to_dict()
        # aggressive mutation incl. a nested stage-dict tamper when non-empty
        if d1["stages"]:
            d1["stages"][0]["lens"] = "TAMPERED"
        d1["stages"].append({"stage": "x", "lens": "y"})
        d1["stage_names"].append("EXTRA")
        d1["enabled"] = "TAMPERED"
        d1["count"] = 99999
        d1["verdict"] = "TAMPERED"
        d2 = p.to_dict()
        assert dataclasses.asdict(p) == before, "to_dict mutated the frozen instance"
        assert d2 == _plan(flag, lenses).to_dict(), "second to_dict was affected by mutation"
        assert d1 is not d2, "to_dict returned the same dict object across calls"


def test_b07_two_calls_equal():
    p = _plan(*MULTI_LENS[1:])
    assert p.to_dict() == p.to_dict()


# ==========================================================================
# Behavior 8 -- NO exit_code key / attribute
# ==========================================================================
def test_b08_no_exit_code():
    for _label, flag, lenses in CASES:
        assert "exit_code" not in _plan(flag, lenses).to_dict()
    assert not hasattr(foundry.ScoutPhasePlan, "exit_code")


# ==========================================================================
# Behavior 9 -- default CLI == as_json=False byte-for-byte + NOT valid JSON
# ==========================================================================
def test_b09_default_equals_explicit_false_and_not_json():
    for _label, flag, lenses in CASES:
        rc_def, out_def = _cap(lambda: foundry.scout_plan_cli(flag, lenses))
        rc_false, out_false = _cap(lambda: foundry.scout_plan_cli(flag, lenses, as_json=False))
        assert out_def == out_false, "default output != explicit as_json=False output"
        assert rc_def == rc_false
        with pytest.raises(json.JSONDecodeError):
            json.loads(out_def)


def test_b09_as_json_default_is_false():
    sig = inspect.signature(foundry.scout_plan_cli)
    assert "as_json" in sig.parameters, "scout_plan_cli must gain an as_json param"
    assert sig.parameters["as_json"].default is False


def test_b09_human_render_shape():
    # the existing 4-shape human render (armed baseline for the leak test below)
    _rc, out = _cap(lambda: foundry.scout_plan_cli(True, ["a", "b"], as_json=False))
    lines = out.splitlines()
    assert lines[0].startswith("scout-plan: dual_pm_scouts=True count=2")
    assert " (lens: " in lines[1] and " (lens: " in lines[2]
    assert lines[-1] == "verdict: DUAL"


# ==========================================================================
# Behavior 10 -- as_json=True prints EXACTLY json.dumps(to_dict, indent=2)+nl,
#                and NONE of the human-render lines leak in
# ==========================================================================
def test_b10_json_output_is_exact():
    for _label, flag, lenses in CASES:
        rc, out = _cap(lambda: foundry.scout_plan_cli(flag, lenses, as_json=True))
        expected = json.dumps(_plan(flag, lenses).to_dict(), indent=2) + "\n"
        assert out == expected, "as_json output != json.dumps(to_dict(), indent=2)+newline"
        assert json.loads(out) == _plan(flag, lenses).to_dict()


def test_b10_no_human_lines_leak_into_json():
    _, out = _cap(lambda: foundry.scout_plan_cli(True, ["a", "b"], as_json=True))
    for ln in out.splitlines():
        s = ln.strip()
        assert not s.startswith("scout-plan:"), "human header leaked into JSON: %r" % ln
        assert not s.startswith("verdict:"), "human verdict line leaked into JSON: %r" % ln
        assert " (lens: " not in ln, "human stage line leaked into JSON: %r" % ln


def test_b10_leak_discriminator_is_armed():
    # the SAME check would flag every line of the human render (non-vacuous)
    _, hout = _cap(lambda: foundry.scout_plan_cli(True, ["a", "b"], as_json=False))
    lines = [ln for ln in hout.splitlines() if ln.strip()]
    flagged = [
        ln for ln in lines
        if ln.strip().startswith("scout-plan:")
        or ln.strip().startswith("verdict:")
        or " (lens: " in ln
    ]
    assert flagged == lines, "leak discriminator is inert (would not flag the human render)"


# ==========================================================================
# Behavior 11 -- exit code identical in both modes == 1 if enabled else 0
# ==========================================================================
def test_b11_same_exit_code_both_modes():
    fixtures = [(ENABLED_DEFAULT, 1), (DISABLED, 0), (MULTI_LENS, 1), (ENABLED_EMPTY, 1)]
    for (_label, flag, lenses), code in fixtures:
        rc_h, _ = _cap(lambda: foundry.scout_plan_cli(flag, lenses, as_json=False))
        rc_j, _ = _cap(lambda: foundry.scout_plan_cli(flag, lenses, as_json=True))
        assert rc_h == rc_j == code, (
            "exit diverged for %r: human=%r json=%r expected=%r"
            % (flag, rc_h, rc_j, code)
        )
        # and it equals 1-if-enabled-else-0
        assert code == (1 if _plan(flag, lenses).enabled else 0)


# ==========================================================================
# Behavior 12 -- argparse `--json` store_true routed to as_json; --lens
#                passthrough; a value after --json rejected
# ==========================================================================
def test_b12_main_routes_as_json(monkeypatch):
    captured = {}

    def fake(dual_pm_scouts, lenses, as_json=False):
        captured.update(dual=dual_pm_scouts, lenses=lenses, as_json=as_json)
        return 0

    monkeypatch.setattr(foundry, "scout_plan_cli", fake)
    foundry.main(["scout-plan", "--dual-pm-scouts", "--json"])
    assert captured["as_json"] is True and captured["dual"] is True
    captured.clear()
    foundry.main(["scout-plan", "--dual-pm-scouts"])
    assert captured["as_json"] is False


def test_b12_lens_passthrough(monkeypatch):
    captured = {}

    def fake(dual_pm_scouts, lenses, as_json=False):
        captured.update(dual=dual_pm_scouts, lenses=lenses, as_json=as_json)
        return 1

    monkeypatch.setattr(foundry, "scout_plan_cli", fake)
    foundry.main(["scout-plan", "--dual-pm-scouts", "--lens", "a", "--lens", "b", "--json"])
    assert captured["lenses"] == ["a", "b"]
    assert captured["as_json"] is True


def test_b12_json_is_store_true():
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["scout-plan", "--dual-pm-scouts", "--json", "x"])
    assert ei.value.code != 0


# ==========================================================================
# Behavior 13 -- end-to-end through foundry.main (no spy): code + JSON body
# ==========================================================================
def test_b13_main_end_to_end_dual():
    rc, out = _cap(lambda: foundry.main(["scout-plan", "--dual-pm-scouts", "--json"]))
    assert rc == 1
    d = json.loads(out)
    assert d["verdict"] == "DUAL"
    assert d["enabled"] is True
    # sanity: the literal JSON booleans/labels are present
    assert '"verdict": "DUAL"' in out
    assert '"enabled": true' in out


def test_b13_main_end_to_end_single():
    rc, out = _cap(lambda: foundry.main(["scout-plan", "--json"]))
    assert rc == 0
    d = json.loads(out)
    assert d["verdict"] == "SINGLE"
    assert d["enabled"] is False
    assert d["count"] == 0
    assert d["stages"] == []
    assert d["stage_names"] == []


# ==========================================================================
# Behavior 14 -- DORMANCY: the running loop is unaffected (deep co_names scan,
#                NOT a grep -- these are PRE-EXISTING tokens since iter 80)
# ==========================================================================
def test_b14_orchestrators_do_not_reference_scout_symbols():
    new = set(SCOUT_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), "foundry.%s references scout symbol(s): %r" % (fn.__name__, refs)


def test_b14_dispatcher_has_zero_scout_references():
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in SCOUT_SYMBOLS:
        assert dtext.count(sym) == 0, "dispatcher.py references scout symbol %r" % sym
    assert dtext.count("scout-plan") == 0, "dispatcher.py names the scout-plan command string"


# ==========================================================================
# Behavior 15 -- fresh subprocess import + CLI writes nothing to disk
# ==========================================================================
def test_b15_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_b15_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for _label, flag, lenses in CASES:
        for as_json in (False, True):
            before = sorted(x.name for x in tmp_path.iterdir())
            _cap(lambda: foundry.scout_plan_cli(flag, lenses, as_json=as_json))
            after = sorted(x.name for x in tmp_path.iterdir())
            assert before == after, "CLI wrote to disk (%r, as_json=%s)" % (flag, as_json)


# ==========================================================================
# Acceptance-criteria / non-regression block (offline)
# ==========================================================================
def test_ac_public_surface_intact():
    assert callable(foundry.decide_scout_phase)
    assert callable(foundry.scout_plan_cli)
    assert dataclasses.is_dataclass(foundry.ScoutPhasePlan)
    assert callable(foundry.ScoutPhasePlan.to_dict)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), "foundry.%s missing (regression)" % fn
    # prior-bite cores remain present (no regression to the org-design family)
    assert callable(foundry.decide_restaffing)
    assert callable(foundry.decide_cadence_review)
    assert callable(foundry.classify_escalation)
    assert dispatcher is not None


def test_ac_help_lists_scout_plan(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "scout-plan" in out


def test_ac_scout_plan_subparser_help_has_json(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["scout-plan", "--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "--json" in out, "--json absent from scout-plan subparser help"
    assert "--dual-pm-scouts" in out
    assert "--lens" in out


def test_ac_new_symbols_ascii():
    """The new/changed code is pure ASCII. Scoped to the two symbols via
    inspect.getsource -- NOT a whole-file scan (foundry.py carries pre-existing
    non-ASCII elsewhere -- the iter-67 divider-em-dash trap)."""
    srcs = [
        inspect.getsource(foundry.ScoutPhasePlan.to_dict),
        inspect.getsource(foundry.scout_plan_cli),
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
